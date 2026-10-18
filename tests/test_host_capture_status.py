from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from test_host_boundaries import installation as installation
from test_host_boundaries import native
from test_spool_boundaries import capture_authority as capture_authority

from agents_memory import hosts
from agents_memory.domain import CaptureCommand, DomainError, EffectState
from agents_memory.spool import ProducerSpool


@pytest_asyncio.fixture
async def capture_status_world(installation, capture_authority, monkeypatch):
    project, settings, agent, producer, _ = installation
    store, actor, binding = capture_authority
    receipt_path = Path(hosts.install_host(
        settings, project, binding, "omp", agent, producer,
    )["receipt"])
    runtime = Path(hosts.load_receipt(receipt_path)["runtime_dir"])
    loop = asyncio.get_running_loop()
    state = SimpleNamespace(error=None, sequence=0)

    class Endpoint:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, route, payload):
            assert route == "/api/capture"
            if state.error is not None:
                raise DomainError(
                    state.error, "synthetic_private_capture_failure",
                    status=403 if state.error == "SCOPE_DENIED" else 503,
                    effect=EffectState.NOT_STARTED if state.error == "SCOPE_DENIED" else EffectState.UNKNOWN,
                )
            command = CaptureCommand.model_validate(payload)
            operation = asyncio.run_coroutine_threadsafe(store.capture(actor, command), loop).result(timeout=30)
            return operation.model_dump(mode="json")

    monkeypatch.setattr(hosts, "LocalClient", Endpoint)

    async def capture(body):
        state.sequence += 1
        return await asyncio.to_thread(
            hosts.handle_hook, receipt_path, native(
                project, "omp", "input", text=body, source="interactive",
                adapter_turn_id=f"capture-status-{state.sequence}",
            ),
        )

    spool = ProducerSpool(runtime / "capture.sqlite3", settings.deployment_id, binding, settings.spool_limit_bytes)
    try:
        receipt_limit = spool.receipt_limit
    finally:
        spool.close()
    last = await capture("Historical observed source 0; retain the offline limitation.")
    assert last["capture"]["state"] == "committed"
    for index in range(1, receipt_limit + 2):
        last = await capture(f"Historical observed source {index}; retain the offline limitation.")
        assert last["capture"]["state"] == "committed"
    historical_count = last["capture"]["gaps"]["SPOOL_RECEIPT_REPLAY_EXPIRED"]
    assert historical_count > 0
    return SimpleNamespace(
        capture=capture, state=state, store=store, actor=actor, binding=binding,
        historical_count=historical_count,
    )


@pytest.mark.asyncio
async def test_successful_capture_does_not_reclassify_retained_receipt_history_as_new_failure(capture_status_world):
    world = capture_status_world
    body = "The newly captured source still requires a separate agent judgment."
    result = await world.capture(body)
    assert result["capture"]["state"] == "committed"
    pointer = result["capture"]["source_pointer"]
    source = await world.store.inspect(world.actor, world.binding, pointer["source_id"])
    assert source["body"] == body
    assert result["state"] == "ok"
    assert "warning" not in result["stdout"]
    assert result["capture"]["candidate_ready"] == "not_claimed"
    assert result["capture"]["gaps"]["SPOOL_RECEIPT_REPLAY_EXPIRED"] > world.historical_count
    assert result["capture"]["pending"] == result["capture"]["quarantined"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("code,delivery", (
    ("SERVICE_UNAVAILABLE", "durably_spooled"),
    ("SCOPE_DENIED", "quarantined"),
))
async def test_current_capture_failure_remains_degraded_despite_retained_gap_history(capture_status_world, code, delivery):
    world = capture_status_world
    world.state.error = code
    body = "A current unavailable capture must not be advertised as delivered."
    result = await world.capture(body)
    assert result["state"] == "degraded"
    assert result["stdout"]["warning"]
    assert result["capture"]["state"] == delivery
    assert "source_pointer" not in result["capture"]
    assert result["capture"]["pending" if delivery == "durably_spooled" else "quarantined"] == 1
    assert result["capture"]["gaps"]["SPOOL_RECEIPT_REPLAY_EXPIRED"] >= world.historical_count
    exposed = json.dumps(result)
    assert "synthetic_private_capture_failure" not in exposed
    assert body not in exposed
