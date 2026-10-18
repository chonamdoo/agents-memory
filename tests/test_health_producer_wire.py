from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from agents_memory import spool as spool_module
from agents_memory.domain import CaptureCommand, DomainError, EffectState
from agents_memory.health import (
    CodeFileObservation,
    CodeObservationCommand,
    SessionObservationCommand,
)
from agents_memory.spool import PAYLOAD_RETENTION_SECONDS, ProducerSpool


def health_command(kind, key="health-one"):
    common = {
        "binding_id": "binding-one", "expected_binding_revision": 1,
        "idempotency_key": key,
    }
    if kind == "code":
        return CodeObservationCommand(
            **common, workspace_id="workspace-one", expected_workspace_revision=1,
            root_fingerprint="a" * 64, sequence=1, observed_at=datetime.now(UTC),
            files=[CodeFileObservation(
                relative_path="src/module.py", status="present", file_digest="b" * 64,
                byte_length=7, symbol_coverage="complete",
            )], coverage="linked_paths",
        )
    return SessionObservationCommand(
        **common, stream_id="stream-one", segment_id="segment-one", event_id="event-one",
        sequence=1, event="end", root_run_id=None, agent_path="child-one",
        origin_keys=["capture-origin"], coverage="partial",
        gaps=["HOST_ROOT_LINEAGE_UNOBSERVED", "HOST_SESSION_WINDOW_UNOBSERVED"],
    )


def committed(command, **changes):
    return {
        "id": "operation:" + uuid.uuid4().hex, "binding_id": "binding-one",
        "kind": command.kind, "state": "health_recorded", "epoch": 1,
        "artifact_id": "health:" + uuid.uuid4().hex, "effect": "committed", **changes,
    }


@pytest.mark.parametrize("kind", ["code", "session"])
def test_fixed_health_envelopes_share_capture_spool_and_routes(tmp_path, kind):
    path = tmp_path / "capture.sqlite3"
    command = health_command(kind)
    source = CaptureCommand(
        binding_id="binding-one", idempotency_key="capture-one", origin_key="capture-origin",
        speaker="human", body="An authorized prompt window.",
    )
    spool = ProducerSpool(path, "deployment-one", "binding-one", 65536)
    calls = []

    class Endpoint:
        def request(self, route, payload):
            calls.append((route, payload))
            if route == "/api/capture":
                return {"id": "capture-operation", "effect": "committed"}
            return committed(command)

    try:
        assert spool.enqueue(command)["state"] == "durably_spooled"
        assert spool.enqueue(source)["state"] == "durably_spooled"
        assert spool.flush(Endpoint())["committed"] == 2
        receipt = spool.disposition(command.idempotency_key)
        assert receipt["state"] == "committed"
        assert receipt["health_kind"] == command.kind
        assert receipt["health_reference"].startswith("health:")
        assert "source_pointer" not in receipt
    finally:
        spool.close()
    assert [route for route, _ in calls] == ["/api/health", "/api/capture"]
    reopened = ProducerSpool(path, "deployment-one", "binding-one", 65536)
    try:
        assert reopened.enqueue(command) == {**receipt, "replay": True}
        assert reopened.status()["pending"] == 0
    finally:
        reopened.close()


@pytest.mark.parametrize("kind", ["code", "session"])
def test_health_minimal_ack_never_deletes_a_pending_observation(tmp_path, kind):
    command = health_command(kind)
    spool = ProducerSpool(tmp_path / "capture.sqlite3", "deployment-one", "binding-one", 65536)

    class Endpoint:
        def request(self, route, payload):
            return {"id": "ambiguous-operation", "effect": "committed"}

    try:
        spool.enqueue(command)
        result = spool.flush(Endpoint())
        assert result["committed"] == 0
        assert result["pending"] == 1
        assert result["errors"] == ["HEALTH_RECEIPT_INVALID"]
        assert spool.disposition(command.idempotency_key)["state"] == "durably_spooled"
    finally:
        spool.close()


@pytest.mark.parametrize("changes", [
    {"binding_id": "other-binding"}, {"kind": "capture"}, {"state": "pending"},
    {"artifact_id": None}, {"effect": "not_committed"},
    {"capture_disposition": "ignored"}, {"source_id": "source-one"},
])
def test_health_ack_requires_exact_kind_scope_reference_and_commit(tmp_path, changes):
    command = health_command("code")
    spool = ProducerSpool(tmp_path / "capture.sqlite3", "deployment-one", "binding-one", 65536)

    class Endpoint:
        def request(self, route, payload):
            return committed(command, **changes)

    try:
        spool.enqueue(command)
        result = spool.flush(Endpoint())
        assert result["pending"] == 1 and result["committed"] == 0
        assert result["errors"] == ["HEALTH_RECEIPT_INVALID"]
    finally:
        spool.close()


def test_unknown_health_dispatch_retains_original_envelope_before_capture(tmp_path):
    command = health_command("session")
    spool = ProducerSpool(tmp_path / "capture.sqlite3", "deployment-one", "binding-one", 65536)
    calls = []

    class Endpoint:
        failed = False

        def request(self, route, payload):
            calls.append((route, payload))
            if not self.failed:
                self.failed = True
                raise DomainError("SERVICE_UNAVAILABLE", "No private diagnostics", effect=EffectState.UNKNOWN)
            if route == "/api/capture":
                return {"id": "capture-operation", "effect": "committed"}
            return committed(command)

    endpoint = Endpoint()
    try:
        spool.enqueue(command)
        spool.enqueue(CaptureCommand(
            binding_id="binding-one", idempotency_key="capture-one", origin_key="capture-origin",
            speaker="human", body="An independent prompt.",
        ))
        assert spool.flush(endpoint)["pending"] == 2
        assert spool.flush(endpoint)["pending"] == 0
        assert calls[0] == calls[1]
        assert [route for route, _ in calls] == ["/api/health", "/api/health", "/api/capture"]
    finally:
        spool.close()


def test_health_overflow_does_not_reserve_metadata_or_consume_capture_capacity(tmp_path):
    spool = ProducerSpool(tmp_path / "capture.sqlite3", "deployment-one", "binding-one", 8192)
    accepted = 0
    try:
        for index in range(32):
            command = health_command("session", key=f"health-{index}")
            try:
                spool.enqueue(command, health_state=("sequence", {"value": index + 1}))
                accepted += 1
            except DomainError as error:
                assert error.code == "SPOOL_FULL"
                break
        assert accepted > 0
        assert spool.read_health_state("sequence") == {"value": accepted}
        result = spool.enqueue(CaptureCommand(
            binding_id="binding-one", idempotency_key="capture-one", origin_key="capture-one",
            speaker="human", body="Still able to capture the next prompt.",
        ))
        assert result["state"] == "durably_spooled"
        assert spool.status()["gaps"]["SPOOL_FULL"] >= 1
    finally:
        spool.close()


def test_health_expiry_keeps_body_free_gap_and_does_not_refresh_original_age(tmp_path, monkeypatch):
    now = [2000000.0]
    monkeypatch.setattr(spool_module.time, "time", lambda: now[0])
    spool = ProducerSpool(tmp_path / "capture.sqlite3", "deployment-one", "binding-one", 65536)
    command = health_command("session")
    try:
        spool.enqueue(command)
        now[0] += PAYLOAD_RETENTION_SECONDS - 1
        assert spool.enqueue(command)["replay"] is True
        now[0] += 2
        assert spool.disposition(command.idempotency_key)["state"] == "expired"
        status = spool.status()
        assert status["pending"] == 0
        assert status["gaps"]["SPOOL_PAYLOAD_EXPIRED"] == 1
        assert "capture-origin" not in str(status)
    finally:
        spool.close()


@pytest.mark.parametrize("kind", ["code", "session"])
def test_authoritative_retired_health_ack_clears_payload_without_claiming_current_observation(tmp_path, kind):
    command = health_command(kind)
    spool = ProducerSpool(tmp_path / "capture.sqlite3", "deployment-one", "binding-one", 65536)

    class Endpoint:
        def request(self, route, payload):
            return committed(command, state="retracted")

    try:
        spool.enqueue(command)
        assert spool.flush(Endpoint())["pending"] == 0
        receipt = spool.disposition(command.idempotency_key)
        assert receipt["state"] == "discarded"
        assert receipt["health_kind"] == command.kind
        assert "source_pointer" not in receipt
        assert spool.enqueue(command)["state"] == "discarded"
    finally:
        spool.close()
