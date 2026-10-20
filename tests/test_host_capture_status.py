from __future__ import annotations

import asyncio
import json
import sqlite3
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
        historical_count=historical_count, spool_path=runtime / "capture.sqlite3",
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
async def test_permanently_refused_capture_remains_degraded_despite_retained_gap_history(capture_status_world):
    world = capture_status_world
    world.state.error = "SCOPE_DENIED"
    body = "A refused capture must not be advertised as delivered."
    result = await world.capture(body)
    assert result["state"] == "degraded"
    assert result["stdout"]["warning"]
    assert result["capture"]["state"] == "quarantined"
    assert "source_pointer" not in result["capture"]
    assert result["capture"]["quarantined"] == 1
    assert result["capture"]["gaps"]["SPOOL_RECEIPT_REPLAY_EXPIRED"] >= world.historical_count
    exposed = json.dumps(result)
    assert "synthetic_private_capture_failure" not in exposed
    assert body not in exposed


@pytest.mark.asyncio
async def test_deferred_durable_capture_is_silent_until_its_backlog_is_stale(capture_status_world):
    world = capture_status_world
    world.state.error = "SERVICE_UNAVAILABLE"
    deferred = await world.capture("A deferred capture stays durable while the service is busy.")
    assert deferred["state"] == "ok"
    assert "warning" not in deferred["stdout"]
    assert deferred["capture"]["state"] == "durably_spooled"
    assert "source_pointer" not in deferred["capture"]
    assert deferred["capture"]["pending"] == 1
    with sqlite3.connect(world.spool_path) as spool:
        spool.execute("UPDATE outbox SET created_at=created_at-?", (hosts.CAPTURE_BACKLOG_ALERT_SECONDS + 1,))
    stale = await world.capture("A second capture behind a stale backlog.")
    assert stale["state"] == "degraded"
    assert stale["stdout"]["warning"] == "agents-memory: HOST_CAPTURE_DEGRADED"
    assert stale["capture"]["oldest_pending_capture_seconds"] > hosts.CAPTURE_BACKLOG_ALERT_SECONDS
    world.state.error = None
    delivered = await world.capture("The service recovered and drains the backlog.")
    assert delivered["state"] == "ok"
    assert delivered["capture"]["state"] == "committed"
    assert delivered["capture"]["pending"] == 0


@pytest.mark.asyncio
async def test_retryable_failure_other_than_a_busy_service_warns_at_once(capture_status_world):
    world = capture_status_world
    world.state.error = "CREDENTIAL_REVOKED"
    result = await world.capture("A capture refused by a revoked credential stays spooled.")
    assert result["capture"]["state"] == "durably_spooled"
    assert result["state"] == "degraded"
    assert result["stdout"]["warning"] == "agents-memory: HOST_CAPTURE_DEGRADED"
