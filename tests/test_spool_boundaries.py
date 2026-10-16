import asyncio
import json
import os
import sqlite3
import uuid
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import asyncpg
import pytest
import pytest_asyncio

from agents_memory import spool as spool_module
from agents_memory.config import Settings
from agents_memory.domain import (
    CaptureCommand,
    CaptureCoverage,
    DomainError,
    EffectState,
    canonical_digest,
)
from agents_memory.journal import DeletionJournal
from agents_memory.migrations import migrate
from agents_memory.spool import ProducerSpool
from agents_memory.store import Store


def envelope(**changes):
    return CaptureCommand.model_validate({
        "binding_id": "binding-001", "idempotency_key": "capture-001",
        "origin_key": "origin-001", "body": "Do not export customer data.",
        "speaker": "human", **changes,
    })


@pytest.mark.parametrize("version", [(3, 44, 5), (3, 50, 6), (3, 51, 2)])
def test_unsupported_sqlite_cannot_create_capture_storage(tmp_path, monkeypatch, version):
    monkeypatch.setattr(sqlite3, "sqlite_version_info", version)
    directory = tmp_path / "refused"
    with pytest.raises(DomainError) as caught:
        ProducerSpool(directory / "outbox.sqlite", "deployment-001", "binding-001", 65536)
    assert caught.value.code == "SPOOL_SQLITE_UNSUPPORTED"
    assert caught.value.effect is EffectState.NOT_STARTED
    assert not directory.exists()


def test_durable_retry_does_not_accept_changed_evidence(tmp_path):
    path = tmp_path / "outbox.sqlite"
    spool = ProducerSpool(path, "deployment-001", "binding-001", 65536)
    spool.enqueue(envelope())
    spool.close()
    reopened = ProducerSpool(path, "deployment-001", "binding-001", 65536)
    try:
        assert reopened.enqueue(envelope()) == {"state": "durably_spooled", "replay": True}
        with pytest.raises(DomainError) as caught:
            reopened.enqueue(envelope(body="Export customer data."))
        assert caught.value.code == "IDEMPOTENCY_CONFLICT"
    finally:
        reopened.close()


@pytest.mark.parametrize("version", [None, (3, 44, 6), (3, 50, 7), (3, 51, 3)])
def test_another_project_cannot_take_existing_outbox(tmp_path, monkeypatch, version):
    if version is not None:
        monkeypatch.setattr(sqlite3, "sqlite_version_info", version)
    path = tmp_path / "outbox.sqlite"
    spool = ProducerSpool(path, "deployment-001", "binding-001", 65536)
    spool.enqueue(envelope())
    spool.close()
    with pytest.raises(DomainError) as caught:
        ProducerSpool(path, "deployment-001", "binding-002", 65536)
    assert caught.value.code == "SPOOL_SCOPE_CONFLICT"
    reopened = ProducerSpool(path, "deployment-001", "binding-001", 65536)
    try:
        assert reopened.enqueue(envelope())["replay"] is True
    finally:
        reopened.close()


@pytest.mark.parametrize("changes", [{"injected": True}, {"speaker": "memory"}, {"binding_id": "binding-002"}])
def test_retrieved_or_wrong_project_data_cannot_become_capture(tmp_path, changes):
    spool = ProducerSpool(tmp_path / "outbox.sqlite", "deployment-001", "binding-001", 65536)
    try:
        with pytest.raises(DomainError) as caught:
            spool.enqueue(envelope(**changes))
        assert caught.value.code in {"CAPTURE_INJECTED_REJECTED", "SPOOL_SCOPE_CONFLICT"}
        assert spool.status()["pending"] == 0
    finally:
        spool.close()


def test_overflow_is_a_durable_visible_gap_not_an_acceptance(tmp_path):
    path = tmp_path / "outbox.sqlite"
    spool = ProducerSpool(path, "deployment-001", "binding-001", 1)
    try:
        with pytest.raises(DomainError) as caught:
            spool.enqueue(envelope())
        assert caught.value.code == "SPOOL_FULL"
    finally:
        spool.close()
    reopened = ProducerSpool(path, "deployment-001", "binding-001", 65536)
    try:
        assert reopened.status()["gaps"] == {"SPOOL_FULL": 1}
        assert reopened.status()["pending"] == 0
        assert reopened.enqueue(envelope())["replay"] is False
    finally:
        reopened.close()


def test_spool_does_not_follow_or_chmod_an_existing_symlink(tmp_path):
    target = tmp_path / "unrelated.txt"
    target.write_text("preserve me", encoding="utf-8")
    original_mode = target.stat().st_mode
    path = tmp_path / "outbox.sqlite"
    path.symlink_to(target)
    with pytest.raises(DomainError) as caught:
        ProducerSpool(path, "deployment-001", "binding-001", 65536)
    assert caught.value.code == "SPOOL_PATH_DENIED"
    assert target.read_text(encoding="utf-8") == "preserve me"
    assert target.stat().st_mode == original_mode


def test_poison_head_is_counted_quarantined_and_later_rows_deliver_in_order(tmp_path):
    path = tmp_path / "outbox.sqlite"
    spool = ProducerSpool(path, "deployment-001", "binding-001", 65536)
    calls = []

    class Endpoint:
        def request(self, route, payload):
            calls.append(payload)
            if payload["idempotency_key"] == "capture-001":
                raise DomainError("ORIGIN_CONFLICT", "Rejected source", status=409)
            return {"effect": "committed", "id": "operation-" + payload["idempotency_key"]}

    try:
        for index in range(1, 5):
            spool.enqueue(envelope(idempotency_key=f"capture-{index:03}", origin_key=f"origin-{index:03}"))
        result = spool.flush(Endpoint(), limit=3)
        assert result["committed"] == 2
        assert result["pending"] == 1
        assert result["quarantined"] == 1
        assert result["blocked"] == {"ORIGIN_CONFLICT": 1}
        assert spool.inspect()["entries"][0]["key"] == "capture-001"
        assert "Do not export" not in str(spool.inspect())
        result = spool.flush(Endpoint())
        assert result["pending"] == 0
        assert [payload["idempotency_key"] for payload in calls] == [f"capture-{index:03}" for index in range(1, 5)]
    finally:
        spool.close()
    reopened = ProducerSpool(path, "deployment-001", "binding-001", 65536)
    try:
        assert reopened.status()["quarantined"] == 1
        assert reopened.enqueue(envelope(idempotency_key="capture-002", origin_key="origin-002")) == {
            "state": "committed", "replay": True, "operation_id": "operation-capture-002",
        }
        with pytest.raises(DomainError) as caught:
            reopened.enqueue(envelope(idempotency_key="capture-002", origin_key="origin-002", body="Different evidence"))
        assert caught.value.code == "IDEMPOTENCY_CONFLICT"
    finally:
        reopened.close()


@pytest.mark.parametrize("code,status", [
    ("AUTH_DENIED", 401), ("SERVICE_DRAINING", 503), ("QUEUE_FULL", 429),
    ("SERVICE_UNAVAILABLE", 503), ("AUTHORITY_UNAVAILABLE", 503),
    ("DELETION_BARRIER", 409),
])
def test_transient_failure_stops_ordered_drain_without_poisoning_remaining_rows(tmp_path, code, status):
    spool = ProducerSpool(tmp_path / "outbox.sqlite", "deployment-001", "binding-001", 65536)
    calls = []

    class Endpoint:
        reject = True

        def request(self, route, payload):
            calls.append(payload["idempotency_key"])
            if self.reject:
                raise DomainError(code, "No raw diagnostics", status=status)
            return {"effect": "committed", "id": "operation-" + payload["idempotency_key"]}

    endpoint = Endpoint()
    try:
        for index in range(3):
            spool.enqueue(envelope(idempotency_key=f"capture-{index}", origin_key=f"origin-{index}"))
        result = spool.flush(endpoint)
        assert calls == ["capture-0"]
        assert result["pending"] == 3
        assert result["quarantined"] == 0
        assert result["blocked"] == {}
        endpoint.reject = False
        assert spool.flush(endpoint)["pending"] == 0
        assert calls == ["capture-0", "capture-0", "capture-1", "capture-2"]
    finally:
        spool.close()


@pytest.mark.parametrize("effect", [EffectState.NOT_STARTED, EffectState.NOT_COMMITTED])
def test_confirmed_invalid_coverage_quarantines_head_and_delivers_later_capture(tmp_path, effect):
    path = tmp_path / "outbox.sqlite"
    spool = ProducerSpool(path, "deployment-001", "binding-001", 65536)
    invalid = envelope(coverage=CaptureCoverage(status="observed_window", original_bytes=1))
    valid = envelope(idempotency_key="capture-002", origin_key="origin-002")
    sent = []

    class Endpoint:
        def request(self, route, payload):
            sent.append(payload["idempotency_key"])
            if payload["idempotency_key"] == invalid.idempotency_key:
                raise DomainError("CAPTURE_COVERAGE_INVALID", "Confirmed coverage rejection", effect=effect)
            return {"effect": "committed", "id": "operation-valid"}

    try:
        spool.enqueue(invalid)
        spool.enqueue(valid)
        result = spool.flush(Endpoint())
        assert sent == [invalid.idempotency_key, valid.idempotency_key]
        assert result["committed"] == result["newly_quarantined"] == 1
        assert result["pending"] == 0
        assert result["errors"] == ["CAPTURE_COVERAGE_INVALID"]
        assert result["blocked"] == {"CAPTURE_COVERAGE_INVALID": 1}
    finally:
        spool.close()
    reopened = ProducerSpool(path, "deployment-001", "binding-001", 65536)
    try:
        assert reopened.status()["quarantined"] == 1
        assert reopened.enqueue(invalid)["replay"] is True
        assert reopened.disposition(valid.idempotency_key) == {"state": "committed", "operation_id": "operation-valid"}
    finally:
        reopened.close()


@pytest.mark.parametrize("code", ["INPUT_INVALID", "CAPTURE_COVERAGE_INVALID"])
def test_quarantine_retry_and_discard_are_explicit_and_durable(tmp_path, code):
    path = tmp_path / "outbox.sqlite"
    spool = ProducerSpool(path, "deployment-001", "binding-001", 65536)

    class Reject:
        def request(self, route, payload):
            raise DomainError(code, "No raw evidence", status=422)

    try:
        spool.enqueue(envelope())
        spool.enqueue(envelope(idempotency_key="capture-002", origin_key="origin-002"))
        spool.flush(Reject())
        assert spool.status()["quarantined"] == 2
        result = spool.resolve("capture-001")
        assert result["state"] == "durably_spooled" and result["pending"] == 1
        result = spool.resolve("capture-002", discard=True)
        assert result["quarantined"] == 0
        assert result["gaps"]["SPOOL_DISCARDED"] == 1
    finally:
        spool.close()
    reopened = ProducerSpool(path, "deployment-001", "binding-001", 65536)
    try:
        assert reopened.status()["pending"] == 1
        assert reopened.enqueue(envelope(idempotency_key="capture-002", origin_key="origin-002"))["state"] == "discarded"
        assert reopened.inspect("capture-002")["entries"] == []
        with pytest.raises(DomainError) as caught:
            reopened.resolve("capture-002")
        assert caught.value.code == "SPOOL_ENTRY_NOT_FOUND"
    finally:
        reopened.close()


@pytest.mark.parametrize("response", [None, [], {"effect": "unknown", "id": "operation-001"}, {"effect": "committed", "id": 12}])
def test_unknown_capture_receipt_preserves_head_for_safe_business_key_replay(tmp_path, response):
    spool = ProducerSpool(tmp_path / "outbox.sqlite", "deployment-001", "binding-001", 65536)
    calls = []

    class Endpoint:
        def request(self, route, payload):
            calls.append(payload)
            return response

    try:
        spool.enqueue(envelope())
        spool.enqueue(envelope(idempotency_key="capture-002", origin_key="origin-002"))
        result = spool.flush(Endpoint())
        assert len(calls) == 1
        assert result["errors"] == ["CAPTURE_RECEIPT_INVALID"]
        assert result["pending"] == 2
        assert result["quarantined"] == 0
    finally:
        spool.close()


@pytest.mark.parametrize("code", ["ORIGIN_CONFLICT", "CAPTURE_COVERAGE_INVALID"])
def test_unknown_effect_never_becomes_permanent_quarantine_even_with_conflict_code(tmp_path, code):
    path = tmp_path / "outbox.sqlite"
    spool = ProducerSpool(path, "deployment-001", "binding-001", 65536)
    calls = []

    class Endpoint:
        def request(self, route, payload):
            calls.append(payload)
            raise DomainError(code, "Unreconciled upstream outcome", effect=EffectState.UNKNOWN)

    try:
        spool.enqueue(envelope())
        spool.enqueue(envelope(idempotency_key="capture-002", origin_key="origin-002"))
        result = spool.flush(Endpoint())
        assert len(calls) == 1
        assert result["pending"] == 2 and result["quarantined"] == 0
        assert result["errors"] == [code] and result["blocked"] == {}
    finally:
        spool.close()
    reopened = ProducerSpool(path, "deployment-001", "binding-001", 65536)
    try:
        assert reopened.status()["pending"] == 2
        assert reopened.status()["quarantined"] == 0
        assert reopened.enqueue(envelope())["replay"] is True
    finally:
        reopened.close()


@pytest.mark.parametrize("lost_ack", [False, True])
def test_overlapping_flushes_preserve_single_owner_and_unknown_row(tmp_path, lost_ack):
    path = tmp_path / "outbox.sqlite"
    first = ProducerSpool(path, "deployment-001", "binding-001", 65536)
    second = ProducerSpool(path, "deployment-001", "binding-001", 65536)
    sent = []

    class Committed:
        def request(self, route, payload):
            sent.append(payload["idempotency_key"])
            return {"effect": "committed", "id": "operation-" + payload["idempotency_key"]}

    class Forbidden:
        def request(self, route, payload):
            raise AssertionError("A second flusher dispatched the current owner's row")

    class Inflight:
        def request(self, route, payload):
            busy = second.flush(Forbidden())
            assert busy["committed"] == 0 and busy["pending"] == 1
            second.enqueue(envelope(idempotency_key="following", origin_key="following"))
            if lost_ack:
                raise DomainError("SERVICE_UNAVAILABLE", "Synthetic lost ACK", effect=EffectState.UNKNOWN)
            return {"effect": "committed", "id": "operation-capture-001"}

    try:
        first.enqueue(envelope())
        first.flush(Inflight())
        assert first.status()["pending"] == (2 if lost_ack else 1)
        second.flush(Committed())
        assert sent == (["capture-001", "following"] if lost_ack else ["following"])
        assert first.status()["pending"] == first.status()["quarantined"] == 0
        assert first.disposition("capture-001") == {"state": "committed", "operation_id": "operation-capture-001"}
    finally:
        first.close()
        second.close()


@pytest.mark.parametrize("boundary", ["connect", "pragma", "schema"])
def test_constructor_storage_failure_closes_any_open_connection(tmp_path, monkeypatch, boundary):
    original_connect = sqlite3.connect
    connections = []

    class FaultConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, statement, *args):
            if boundary == "pragma":
                raise sqlite3.OperationalError("sensitive SQLite failure")
            return self.connection.execute(statement, *args)

        def executescript(self, statement):
            raise sqlite3.OperationalError("sensitive SQLite failure")

        def close(self):
            self.connection.close()

    def connect(*args, **kwargs):
        if boundary == "connect":
            raise sqlite3.OperationalError("sensitive SQLite failure")
        connection = original_connect(*args, **kwargs)
        connections.append(connection)
        return FaultConnection(connection)

    monkeypatch.setattr(spool_module.sqlite3, "connect", connect)
    with pytest.raises(DomainError) as caught:
        ProducerSpool(tmp_path / "outbox.sqlite", "deployment-001", "binding-001", 65536)
    assert caught.value.code == "HOST_SPOOL_UNAVAILABLE"
    assert "sensitive SQLite" not in str(caught.value)
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")


def test_successful_receipt_growth_is_bounded_and_storage_counts_sqlite_sidecars(tmp_path):
    path = tmp_path / "outbox.sqlite"
    spool = ProducerSpool(path, "deployment-001", "binding-001", 4096)

    class Committed:
        def request(self, route, payload):
            return {"effect": "committed", "id": "operation-" + payload["idempotency_key"]}

    try:
        for index in range(spool.receipt_limit * 4):
            spool.enqueue(envelope(idempotency_key=f"capture-{index}", origin_key=f"origin-{index}"))
            assert spool.flush(Committed())["committed"] == 1
            status = spool.status()
            assert status["retained_receipts"] <= status["receipt_limit"]
            assert status["storage_bytes"] <= status["storage_limit_bytes"]
        companions = (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm"))
        assert status["storage_bytes"] == sum(item.stat().st_size for item in companions if item.exists())
        assert status["bytes"] == status["pending"] == status["quarantined"] == 0
        assert status["storage_bytes"] > status["bytes"]
        assert status["gaps"]["SPOOL_RECEIPT_REPLAY_EXPIRED"] > 0
        last = spool.receipt_limit * 4 - 1
        assert spool.enqueue(envelope(idempotency_key=f"capture-{last}", origin_key=f"origin-{last}"))["replay"] is True
        old = spool.enqueue(envelope(idempotency_key="capture-0", origin_key="origin-0"))
        assert old["replay"] is False
        assert old["receipt_replay"] == "unavailable_server_idempotency_reconciliation"
    finally:
        spool.close()


def test_time_expired_replay_never_claims_a_local_prior_result(tmp_path):
    path = tmp_path / "outbox.sqlite"
    spool = ProducerSpool(path, "deployment-001", "binding-001", 65536)

    class Committed:
        def request(self, route, payload):
            return {"effect": "committed", "id": "operation-original"}

    try:
        spool.enqueue(envelope())
        spool.flush(Committed())
        spool.db.execute("UPDATE receipts SET created_at=0")
        with pytest.raises(DomainError) as caught:
            spool.disposition("capture-001")
        assert caught.value.code == "SPOOL_REPLAY_EXPIRED_OR_UNKNOWN"
        retry = spool.enqueue(envelope())
        assert retry["state"] == "durably_spooled"
        assert retry["replay"] is False
        assert retry["receipt_replay"] == "unavailable_server_idempotency_reconciliation"
        assert spool.status()["gaps"]["SPOOL_RECEIPT_REPLAY_EXPIRED"] == 1
        assert spool.flush(Committed())["committed"] == 1
        assert spool.disposition("capture-001") == {"state": "committed", "operation_id": "operation-original"}
    finally:
        spool.close()


def test_bounded_receipt_housekeeping_never_discards_active_or_quarantined_work(tmp_path):
    spool = ProducerSpool(tmp_path / "outbox.sqlite", "deployment-001", "binding-001", 65536)

    class Rejected:
        def request(self, route, payload):
            if payload["idempotency_key"] == "capture-001":
                raise DomainError("ORIGIN_CONFLICT", "confirmed rejected source")
            raise DomainError("SERVICE_UNAVAILABLE", "retry later")

    try:
        spool.enqueue(envelope())
        spool.enqueue(envelope(idempotency_key="capture-active", origin_key="origin-active"))
        spool.flush(Rejected())
        with spool._transaction():
            spool.db.executemany(
                "INSERT INTO receipts(key,digest,state,operation_id,created_at) VALUES(?,?,'committed',NULL,0)",
                [(f"old-{index:03}", "0" * 64) for index in range(300)],
            )
        spool._housekeep()
        status = spool.status()
        assert status["pending"] == status["quarantined"] == 1
        assert spool.disposition("capture-active")["state"] == "durably_spooled"
        assert spool.disposition("capture-001") == {"state": "quarantined", "code": "ORIGIN_CONFLICT"}
    finally:
        spool.close()


def test_physical_sqlite_limit_refuses_new_work_even_when_body_budget_has_room(tmp_path):
    path = tmp_path / "outbox.sqlite"
    spool = ProducerSpool(path, "deployment-001", "binding-001", 65536)

    class Rejected:
        def request(self, route, payload):
            raise DomainError("ORIGIN_CONFLICT", "confirmed source rejection")

    try:
        spool.enqueue(envelope())
        spool.flush(Rejected())
        spool.enqueue(envelope(idempotency_key="capture-active", origin_key="origin-active"))
        # Model an older database with successful receipts predating the physical bound.
        spool.db.execute("PRAGMA max_page_count=10000").fetchone()
        with spool._transaction():
            spool.db.executemany(
                "INSERT INTO receipts(key,digest,state,operation_id,created_at) VALUES(?,?,'committed',?,0)",
                [(f"legacy-{index:04}", "0" * 64, "r" * 512) for index in range(2000)],
            )
    finally:
        spool.close()

    reopened = ProducerSpool(path, "deployment-001", "binding-001", 4096)
    try:
        before = reopened.status()
        incoming = envelope(idempotency_key="capture-new", origin_key="origin-new")
        assert before["bytes"] + len(incoming.model_dump_json().encode("utf-8")) < reopened.limit_bytes
        assert before["storage_bytes"] > before["storage_limit_bytes"]
        with pytest.raises(DomainError) as caught:
            reopened.enqueue(incoming)
        assert caught.value.code == "SPOOL_FULL"
        assert reopened.disposition("capture-active")["state"] == "durably_spooled"
        assert reopened.disposition("capture-001") == {"state": "quarantined", "code": "ORIGIN_CONFLICT"}
        status = reopened.status()
        assert status["pending"] == status["quarantined"] == 1
        assert status["gaps"]["SPOOL_FULL"] == 1
    finally:
        reopened.close()


@pytest.fixture
def clock(monkeypatch):
    now = [1_700_000_000.0]
    monkeypatch.setattr(spool_module.time, "time", lambda: now[0])
    return now


@pytest.mark.parametrize("kind,boundary", [
    ("pending", "status"), ("pending", "disposition"), ("pending", "replay"), ("pending", "flush"),
    ("quarantine", "status"), ("quarantine", "inspect"), ("quarantine", "disposition"),
    ("quarantine", "replay"), ("quarantine", "flush"), ("quarantine", "resolve"),
])
def test_payload_expiry_is_visible_body_free_and_never_transmitted(tmp_path, clock, kind, boundary):
    path = tmp_path / "outbox.sqlite"
    command = envelope(body="ttl-private-marker-1cb7a672-do-not-retain")
    spool = ProducerSpool(path, "deployment-001", "binding-001", 65536)

    class Rejected:
        def request(self, route, payload):
            raise DomainError("INPUT_INVALID", "Confirmed rejection", effect=EffectState.NOT_COMMITTED)

    class NeverSent:
        def request(self, route, payload):
            pytest.fail("An expired capture reached the endpoint")

    try:
        spool.enqueue(command)
        if kind == "quarantine":
            assert spool.flush(Rejected())["quarantined"] == 1
        clock[0] += 24 * 60 * 60
        if boundary == "replay":
            result = spool.enqueue(command)
            assert result == {"state": "expired", "replay": True, "operation_id": None}
        elif boundary == "resolve":
            result = spool.resolve(command.idempotency_key)
            assert result["state"] == "expired"
        elif boundary == "disposition":
            result = spool.disposition(command.idempotency_key)
            assert result == {"state": "expired", "operation_id": None}
        elif boundary == "inspect":
            result = spool.inspect(command.idempotency_key)
            assert result["entries"] == []
        elif boundary == "flush":
            result = spool.flush(NeverSent())
            assert result["committed"] == 0
        else:
            result = spool.status()
        status = spool.status()
        assert status["pending"] == status["quarantined"] == status["bytes"] == 0
        assert status["gaps"]["SPOOL_PAYLOAD_EXPIRED"] == 1
        assert status["payload_retention_seconds"] == 24 * 60 * 60
        assert spool.disposition(command.idempotency_key) == {"state": "expired", "operation_id": None}
        assert spool.enqueue(command)["state"] == "expired"
        with pytest.raises(DomainError) as caught:
            spool.enqueue(envelope(body="Changed expired evidence"))
        assert caught.value.code == "IDEMPOTENCY_CONFLICT"
        assert spool.flush(NeverSent())["committed"] == 0
        assert command.body not in str(result)
        for companion in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
            if companion.exists():
                assert command.body.encode("utf-8") not in companion.read_bytes()
    finally:
        spool.close()
    reopened = ProducerSpool(path, "deployment-001", "binding-001", 65536)
    try:
        assert reopened.status()["gaps"]["SPOOL_PAYLOAD_EXPIRED"] == 1
        assert reopened.disposition(command.idempotency_key)["state"] == "expired"
    finally:
        reopened.close()


@pytest.mark.parametrize("code", ["INPUT_INVALID", "CAPTURE_COVERAGE_INVALID"])
def test_payload_original_age_survives_unknown_retry_quarantine_replay_and_reopen(tmp_path, clock, code):
    path = tmp_path / "outbox.sqlite"
    spool = ProducerSpool(path, "deployment-001", "binding-001", 65536)

    class Unknown:
        def request(self, route, payload):
            raise DomainError("SERVICE_UNAVAILABLE", "Outcome unavailable", effect=EffectState.UNKNOWN)

    class Rejected:
        def request(self, route, payload):
            raise DomainError(code, "Confirmed rejection", effect=EffectState.NOT_COMMITTED)

    class NeverSent:
        def request(self, route, payload):
            pytest.fail("A retry renewed the original capture age")

    try:
        spool.enqueue(envelope())
        clock[0] += 6 * 60 * 60
        assert spool.flush(Unknown())["pending"] == 1
        assert spool.enqueue(envelope())["replay"] is True
        clock[0] += 6 * 60 * 60
        assert spool.flush(Rejected())["quarantined"] == 1
        assert spool.enqueue(envelope())["replay"] is True
    finally:
        spool.close()
    clock[0] += 6 * 60 * 60
    reopened = ProducerSpool(path, "deployment-001", "binding-001", 65536)
    try:
        assert reopened.resolve("capture-001")["state"] == "durably_spooled"
        assert reopened.enqueue(envelope())["replay"] is True
        clock[0] += 6 * 60 * 60
        result = reopened.flush(NeverSent())
        assert result["committed"] == result["pending"] == result["quarantined"] == 0
        assert result["gaps"]["SPOOL_PAYLOAD_EXPIRED"] == 1
        assert reopened.disposition("capture-001") == {"state": "expired", "operation_id": None}
    finally:
        reopened.close()


def test_old_spool_schema_discards_unknown_age_payloads_without_renewal_or_receipt_loss(tmp_path, clock):
    path = tmp_path / "outbox.sqlite"
    path.touch(mode=0o600)
    commands = [
        envelope(idempotency_key=key, origin_key="origin-" + key)
        for key in ("legacy-pending", "legacy-failure", "legacy-quarantine", "legacy-committed")
    ]
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            "CREATE TABLE identity (slot INTEGER PRIMARY KEY, deployment TEXT NOT NULL, binding TEXT NOT NULL);"
            "INSERT INTO identity VALUES(1,'deployment-001','binding-001');"
            "CREATE TABLE outbox (key TEXT PRIMARY KEY, digest TEXT NOT NULL, payload TEXT NOT NULL, bytes INTEGER NOT NULL, failure TEXT);"
            "CREATE TABLE quarantine (key TEXT PRIMARY KEY, digest TEXT NOT NULL, payload TEXT NOT NULL, bytes INTEGER NOT NULL, failure TEXT NOT NULL);"
            "CREATE TABLE receipts (key TEXT PRIMARY KEY, digest TEXT NOT NULL, state TEXT NOT NULL, operation_id TEXT, created_at REAL NOT NULL DEFAULT 0);"
        )
        for command in commands:
            payload = json.dumps(command.digest_payload(), separators=(",", ":"))
            digest = canonical_digest(command.digest_payload())
            table = "quarantine" if command.idempotency_key == "legacy-quarantine" else "outbox"
            failure = "INPUT_INVALID" if command.idempotency_key in {"legacy-failure", "legacy-quarantine"} else None
            connection.execute(
                f"INSERT INTO {table} VALUES(?,?,?,?,?)",
                (command.idempotency_key, digest, payload, len(payload.encode("utf-8")), failure),
            )
            if command.idempotency_key == "legacy-committed":
                connection.execute(
                    "INSERT INTO receipts VALUES(?,?,'committed','operation-legacy',?)",
                    (command.idempotency_key, digest, clock[0]),
                )
        connection.commit()
    finally:
        connection.close()

    calls = []

    class Committed:
        def request(self, route, payload):
            calls.append(payload["idempotency_key"])
            return {"effect": "committed", "id": "operation-fresh"}

    spool = ProducerSpool(path, "deployment-001", "binding-001", 65536)
    try:
        status = spool.status()
        assert status["pending"] == status["quarantined"] == status["bytes"] == 0
        assert status["gaps"] == {"SPOOL_PAYLOAD_AGE_UNKNOWN": 4}
        for command in commands[:3]:
            assert spool.enqueue(command)["state"] == "expired"
            assert spool.disposition(command.idempotency_key)["state"] == "expired"
        assert spool.enqueue(commands[3]) == {
            "state": "committed", "replay": True, "operation_id": "operation-legacy",
        }
        assert spool.flush(Committed())["committed"] == 0
        assert spool.enqueue(envelope(idempotency_key="fresh-capture", origin_key="origin-fresh"))["replay"] is False
        assert spool.flush(Committed())["committed"] == 1
        assert calls == ["fresh-capture"]
    finally:
        spool.close()
    reopened = ProducerSpool(path, "deployment-001", "binding-001", 65536)
    try:
        assert reopened.status()["gaps"] == {"SPOOL_PAYLOAD_AGE_UNKNOWN": 4}
        assert reopened.disposition("legacy-committed") == {"state": "committed", "operation_id": "operation-legacy"}
        assert reopened.enqueue(commands[0])["state"] == "expired"
    finally:
        reopened.close()


def test_expired_backlogs_larger_than_housekeeping_batches_do_not_block_or_send_old_work(tmp_path, clock):
    path = tmp_path / "outbox.sqlite"
    spool = ProducerSpool(path, "deployment-001", "binding-001", 262144)
    count = spool_module.HOUSEKEEPING_ROWS + 9
    sent = []

    class Rejected:
        def request(self, route, payload):
            if payload["idempotency_key"].startswith("quarantine-"):
                raise DomainError("INPUT_INVALID", "Confirmed rejection", effect=EffectState.NOT_COMMITTED)
            raise DomainError("SERVICE_UNAVAILABLE", "Not sent")

    class Committed:
        def request(self, route, payload):
            sent.append(payload["idempotency_key"])
            return {"effect": "committed", "id": "operation-fresh"}

    try:
        for prefix in ("quarantine", "pending"):
            for index in range(count):
                key = f"{prefix}-{index:03}"
                spool.enqueue(envelope(idempotency_key=key, origin_key="origin-" + key))
        spool.flush(Rejected(), limit=128)
        spool.flush(Rejected(), limit=128)
        assert spool.status()["pending"] == spool.status()["quarantined"] == count
        clock[0] += 60 * 60
        spool.enqueue(envelope(idempotency_key="fresh-capture", origin_key="origin-fresh"))
        clock[0] += 23 * 60 * 60
        result = spool.flush(Committed(), limit=128)
        assert sent == ["fresh-capture"]
        assert result["committed"] == 1
        assert result["pending"] == result["quarantined"] == result["bytes"] == 0
        assert result["gaps"]["SPOOL_PAYLOAD_EXPIRED"] == 2 * count
        assert result["retained_receipts"] <= result["receipt_limit"]
        assert result["storage_bytes"] <= result["storage_limit_bytes"]
        assert spool.inspect()["entries"] == []
        assert spool.disposition(f"quarantine-{count - 1:03}")["state"] == "expired"
    finally:
        spool.close()
    reopened = ProducerSpool(path, "deployment-001", "binding-001", 262144)
    try:
        assert reopened.status()["gaps"]["SPOOL_PAYLOAD_EXPIRED"] == 2 * count
        assert reopened.disposition("fresh-capture") == {"state": "committed", "operation_id": "operation-fresh"}
    finally:
        reopened.close()


@pytest.mark.parametrize("outcome", ["committed", "rejected", "unknown"])
def test_drain_rechecks_each_payload_age_and_preserves_actual_remote_effect(tmp_path, clock, outcome):
    spool = ProducerSpool(tmp_path / "outbox.sqlite", "deployment-001", "binding-001", 65536)
    sent = []

    class Endpoint:
        def request(self, route, payload):
            sent.append(payload["idempotency_key"])
            clock[0] += 2
            assert spool.status()["pending"] == 0
            if outcome == "rejected":
                raise DomainError("INPUT_INVALID", "Confirmed rejection", effect=EffectState.NOT_COMMITTED)
            if outcome == "unknown":
                raise DomainError("SERVICE_UNAVAILABLE", "Outcome unavailable", effect=EffectState.UNKNOWN)
            return {"effect": "committed", "id": "operation-before-expiry"}

    try:
        spool.enqueue(envelope())
        spool.enqueue(envelope(idempotency_key="capture-002", origin_key="origin-002"))
        clock[0] += 24 * 60 * 60 - 1
        result = spool.flush(Endpoint())
        assert sent == ["capture-001"]
        assert result["pending"] == result["quarantined"] == result["bytes"] == 0
        assert result["gaps"]["SPOOL_PAYLOAD_EXPIRED"] == 2
        if outcome == "committed":
            assert result["committed"] == 1
            assert spool.disposition("capture-001") == {"state": "committed", "operation_id": "operation-before-expiry"}
        else:
            assert result["committed"] == 0
            assert spool.disposition("capture-001") == {"state": "expired", "operation_id": None}
        assert spool.disposition("capture-002") == {"state": "expired", "operation_id": None}
    finally:
        spool.close()


@pytest_asyncio.fixture
async def capture_authority(tmp_path):
    raw_dsn = os.environ.get("PG_TEST_DSN")
    if not raw_dsn:
        pytest.skip("PG_TEST_DSN required for actual model-free capture authority")
    parts = urlsplit(raw_dsn)
    query = dict(parse_qsl(parts.query))
    query.pop("schema", None)
    admin_dsn = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    schema = "am_host_capture_" + uuid.uuid4().hex
    admin = await asyncpg.connect(admin_dsn)
    store = None
    try:
        await admin.execute(f'CREATE SCHEMA "{schema}"')
        query["schema"] = schema
        dsn = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
        await asyncio.to_thread(migrate, dsn)
        settings = Settings(
            deployment_id="capture-test", realm="capture-company", mode="company",
            capability="agent_judged", database_dsn=dsn,
            state_dir=tmp_path / "authority", journal_dir=tmp_path / "journal",
        )
        store = Store(settings, DeletionJournal(settings.journal_dir, settings.deployment_id))
        await store.open()
        token = "capture-test-operator-" + "a" * 32
        actor = await store.bootstrap(token, "capture-owner")
        binding = await store.register_binding(actor, "Synthetic capture", None, "register")
        actor = await store.authenticate(token)
        yield store, actor, binding.id
    finally:
        if store is not None:
            await store.close()
        await admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await admin.close()


@pytest_asyncio.fixture
async def capture_endpoint(capture_authority):
    store, actor, _ = capture_authority
    loop = asyncio.get_running_loop()
    sent = []

    class Endpoint:
        def request(self, route, payload):
            assert route == "/api/capture"
            sent.append(payload["idempotency_key"])
            command = CaptureCommand.model_validate(payload)
            operation = asyncio.run_coroutine_threadsafe(store.capture(actor, command), loop).result(timeout=30)
            return operation.model_dump(mode="json")

    return Endpoint(), sent


@pytest.mark.asyncio
async def test_store_invalid_coverage_quarantines_head_before_valid_capture(tmp_path, capture_authority, capture_endpoint):
    store, actor, binding = capture_authority
    endpoint, sent = capture_endpoint
    invalid = envelope(binding_id=binding, coverage=CaptureCoverage(status="observed_window", original_bytes=1))
    valid = envelope(binding_id=binding, idempotency_key="valid-after-coverage", origin_key="valid-after-coverage")
    path = tmp_path / "producer" / "capture.sqlite3"

    def drain():
        spool = ProducerSpool(path, "capture-test", binding, 65536)
        try:
            spool.enqueue(invalid)
            spool.enqueue(valid)
            result = spool.flush(endpoint)
            return result, spool.disposition(valid.idempotency_key)
        finally:
            spool.close()

    result, receipt = await asyncio.to_thread(drain)
    assert sent == [invalid.idempotency_key, valid.idempotency_key]
    assert result["committed"] == result["newly_quarantined"] == 1
    assert result["pending"] == 0 and result["blocked"] == {"CAPTURE_COVERAGE_INVALID": 1}
    committed = await store.capture(actor, valid)
    assert receipt["source_pointer"] == committed.source_pointer.model_dump(mode="json")


@pytest.mark.asyncio
async def test_authoritative_pointer_survives_lost_ack_reopen_and_exact_key_reconciliation(tmp_path, capture_authority):
    store, actor, binding = capture_authority
    command = envelope(
        binding_id=binding, body="한국어 조건: offline에서만 저장",
        coverage=CaptureCoverage(status="observed_window", original_bytes=len("한국어 조건: offline에서만 저장".encode()), gaps=("SESSION_UNOBSERVED",)),
    )
    path = tmp_path / "producer" / "capture.sqlite3"
    spool = ProducerSpool(path, "capture-test", binding, 65536)
    spool.enqueue(command)
    operation = await store.capture(actor, command)
    assert operation.state == "captured"
    pending = await store.inspect(actor, binding, "pending")
    assert any(item["kind"] == "source_selection" and operation.source_id in item["source_ids"] for item in pending["items"])

    class LostAck:
        def request(self, route, payload):
            raise DomainError("SERVICE_UNAVAILABLE", "Committed response was lost", effect=EffectState.UNKNOWN)

    assert spool.flush(LostAck())["pending"] == 1
    spool.close()
    replayed = await store.capture(actor, command)
    assert replayed.id == operation.id

    class Reconciled:
        def request(self, route, payload):
            return replayed.model_dump(mode="json")

    reopened = ProducerSpool(path, "capture-test", binding, 65536)
    try:
        assert reopened.flush(Reconciled())["committed"] == 1
        result = reopened.disposition(command.idempotency_key)
        pointer = result["source_pointer"]
        assert pointer["source_id"] == operation.source_id
        assert pointer["source_revision"] == operation.source_pointer.source_revision
        assert pointer["source_event_time"] is None
        assert pointer["source_recorded_at"] == replayed.source_pointer.model_dump(mode="json")["source_recorded_at"]
        assert pointer["coverage"]["provenance"] == "producer_reported"
        assert command.body not in json.dumps(result, ensure_ascii=False)
        assert reopened.enqueue(command)["source_pointer"] == pointer
    finally:
        reopened.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation_kind", ["capture", "correct"])
@pytest.mark.parametrize("malformation", [
    "revision", "clock", "binding", "body", "disposition", "source_identity",
    "operation_binding", "missing_pointer", "missing_disposition", "null_pointer",
    "null_disposition", "pointer_null_only", "disposition_null_only", "retracted_live",
    "false_retraction", "legacy_scope", "legacy_epoch", "legacy_extra",
    "record", "feedback", "reflection",
])
async def test_malformed_committed_pointer_keeps_original_head_and_blocks_later_delivery(tmp_path, capture_authority, operation_kind, malformation):
    store, actor, binding = capture_authority
    command = envelope(binding_id=binding)
    if operation_kind == "correct":
        original = await store.capture(actor, envelope(binding_id=binding, idempotency_key="original", origin_key="original"))
        command = command.model_copy(update={"kind": "correction"})
        operation = await store.correct(actor, binding, original.source_id, command)
    else:
        operation = await store.capture(actor, command)
    ack = operation.model_dump(mode="json")
    if malformation == "revision":
        ack["source_pointer"]["source_revision"] = True
    elif malformation == "clock":
        ack["source_pointer"]["source_recorded_at"] = "2026-10-13T00:00:00"
    elif malformation == "binding":
        ack["source_pointer"]["binding_id"] = "another-binding"
    elif malformation == "body":
        ack["source_pointer"]["body"] = command.body
    elif malformation == "disposition":
        ack["capture_disposition"] = "ignored"
    elif malformation == "source_identity":
        ack["source_id"] = "another-source"
    elif malformation == "operation_binding":
        ack["binding_id"] = "another-binding"
    elif malformation == "missing_pointer":
        ack.pop("source_pointer")
    elif malformation == "missing_disposition":
        ack.pop("capture_disposition")
    elif malformation == "null_pointer":
        ack["source_pointer"] = None
    elif malformation == "null_disposition":
        ack["capture_disposition"] = None
    elif malformation == "pointer_null_only":
        ack["source_pointer"] = None
        ack.pop("capture_disposition")
    elif malformation == "disposition_null_only":
        ack["capture_disposition"] = None
        ack.pop("source_pointer")
    elif malformation == "retracted_live":
        ack["state"] = "retracted"
    elif malformation == "false_retraction":
        ack["source_pointer"] = None
        ack["capture_disposition"] = "retracted"
    elif malformation.startswith("legacy_"):
        ack["source_pointer"] = ack["capture_disposition"] = None
        if malformation == "legacy_scope":
            ack["binding_id"] = "another-binding"
        elif malformation == "legacy_epoch":
            ack["epoch"] = True
        else:
            ack["body"] = command.body
    else:
        ack["kind"] = malformation
    sent = []

    class Malformed:
        def request(self, route, payload):
            sent.append(payload["idempotency_key"])
            return ack

    path = tmp_path / "producer" / "capture.sqlite3"
    spool = ProducerSpool(path, "capture-test", binding, 65536)
    try:
        spool.enqueue(command)
        spool.enqueue(envelope(binding_id=binding, idempotency_key="second", origin_key="second"))
        result = spool.flush(Malformed())
        assert result["committed"] == 0 and result["pending"] == 2
        assert result["errors"] == ["CAPTURE_RECEIPT_INVALID"]
        assert sent == [command.idempotency_key]
        assert spool.disposition(command.idempotency_key) == {"state": "durably_spooled"}
    finally:
        spool.close()
    reopened = ProducerSpool(path, "capture-test", binding, 65536)
    try:
        assert reopened.status()["pending"] == 2
        assert reopened.enqueue(command)["replay"] is True
    finally:
        reopened.close()


def test_late_commit_does_not_renew_original_receipt_age(tmp_path, clock):
    path = tmp_path / "capture.sqlite3"
    spool = ProducerSpool(path, "deployment-001", "binding-001", 65536)
    command = envelope()
    digest = canonical_digest(command.digest_payload())
    try:
        spool.enqueue(command)
        spool._store_receipt(command.idempotency_key, digest, "expired", None)
        clock[0] += 12 * 60 * 60
        spool._store_receipt(command.idempotency_key, digest, "committed", "late-operation")
        assert spool.disposition(command.idempotency_key)["operation_id"] == "late-operation"
        clock[0] += 12 * 60 * 60 + 1
        with pytest.raises(DomainError) as caught:
            spool.disposition(command.idempotency_key)
        assert caught.value.code == "SPOOL_REPLAY_EXPIRED_OR_UNKNOWN"
    finally:
        spool.close()


@pytest.mark.asyncio
async def test_committed_ignored_source_never_delivers_a_selectable_pointer(tmp_path, capture_authority):
    store, actor, binding = capture_authority
    command = envelope(binding_id=binding, body="[agents-memory:injected] not new evidence")
    operation = await store.capture(actor, command)
    assert operation.capture_disposition == "ignored" and operation.source_pointer is None

    class Committed:
        def request(self, route, payload):
            return operation.model_dump(mode="json")

    spool = ProducerSpool(tmp_path / "producer" / "capture.sqlite3", "capture-test", binding, 65536)
    try:
        spool.enqueue(command)
        assert spool.flush(Committed())["committed"] == 1
        result = spool.disposition(command.idempotency_key)
        assert result["capture_disposition"] == "ignored"
        assert "source_pointer" not in result
    finally:
        spool.close()


@pytest.mark.asyncio
async def test_receipt_persistence_and_outbox_deletion_rollback_together(tmp_path, capture_authority, monkeypatch):
    store, actor, binding = capture_authority
    command = envelope(binding_id=binding)
    operation = await store.capture(actor, command)

    class Committed:
        def request(self, route, payload):
            return operation.model_dump(mode="json")

    path = tmp_path / "producer" / "capture.sqlite3"
    spool = ProducerSpool(path, "capture-test", binding, 65536)
    spool.enqueue(command)
    original = spool._store_receipt

    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        raise sqlite3.OperationalError("interrupted ACK transaction")

    monkeypatch.setattr(spool, "_store_receipt", interrupted)
    try:
        with pytest.raises(sqlite3.OperationalError):
            spool.flush(Committed())
    finally:
        spool.close()
    reopened = ProducerSpool(path, "capture-test", binding, 65536)
    try:
        assert reopened.disposition(command.idempotency_key) == {"state": "durably_spooled"}
        assert reopened.flush(Committed())["committed"] == 1
        assert reopened.disposition(command.idempotency_key)["source_pointer"]["source_id"] == operation.source_id
    finally:
        reopened.close()


@pytest.mark.asyncio
async def test_legacy_capture_ack_reopens_without_inventing_pointer_revision_or_clocks(tmp_path, capture_authority):
    store, actor, binding = capture_authority
    command = envelope(binding_id=binding)
    operation = await store.capture(actor, command)
    legacy = operation.model_dump(mode="json", exclude={"source_pointer", "capture_disposition", "selection_label"})

    class LegacyEndpoint:
        def request(self, route, payload):
            return legacy

    path = tmp_path / "producer" / "capture.sqlite3"
    spool = ProducerSpool(path, "capture-test", binding, 65536)
    try:
        spool.enqueue(command)
        assert spool.flush(LegacyEndpoint())["committed"] == 1
    finally:
        spool.close()
    reopened = ProducerSpool(path, "capture-test", binding, 65536)
    try:
        result = reopened.disposition(command.idempotency_key)
        assert result == {"state": "committed", "operation_id": operation.id}
        assert reopened.enqueue(command) == {**result, "replay": True}
        assert all(key not in json.dumps(result) for key in ("source_revision", "source_event_time", "source_recorded_at"))
    finally:
        reopened.close()


@pytest.mark.asyncio
async def test_precompany_migration_lost_ack_replay_drains_explicit_null_provenance_and_next_capture(tmp_path, capture_authority, capture_endpoint):
    from test_store_authority import historical_schema_fixture

    store, actor, binding = capture_authority
    endpoint, sent = capture_endpoint
    command = envelope(binding_id=binding)
    following = envelope(binding_id=binding, idempotency_key="after-legacy", origin_key="after-legacy")
    path = tmp_path / "producer" / "capture.sqlite3"
    committed = {}

    class LostAck:
        def request(self, route, payload):
            committed.update(endpoint.request(route, payload))
            raise DomainError("SERVICE_UNAVAILABLE", "Committed response was lost", effect=EffectState.UNKNOWN)

    def lose_ack():
        spool = ProducerSpool(path, "capture-test", binding, 65536)
        try:
            spool.enqueue(command)
            spool.enqueue(following)
            result = spool.flush(LostAck())
            assert result["pending"] == 2 and result["quarantined"] == 0
        finally:
            spool.close()

    await asyncio.to_thread(lose_ack)
    assert sent == [command.idempotency_key]
    await historical_schema_fixture(store, 3)
    await store.close()
    await asyncio.to_thread(migrate, store.settings.database_dsn)
    await store.open()
    await store.reconcile_journal()
    async with store.pool.acquire() as connection:
        row = await connection.fetchrow("SELECT source_pointer,capture_disposition FROM am_operations WHERE id=$1", committed["id"])
    assert row["source_pointer"] is None and row["capture_disposition"] is None
    legacy = await store.capture(actor, command)
    ack = legacy.model_dump(mode="json")
    assert ack["source_pointer"] is None and ack["capture_disposition"] is None
    assert legacy.id == committed["id"]

    def reconcile():
        spool = ProducerSpool(path, "capture-test", binding, 65536)
        try:
            result = spool.flush(endpoint)
            assert result["committed"] == 2 and result["pending"] == result["quarantined"] == 0
            assert result["errors"] == []
        finally:
            spool.close()

    await asyncio.to_thread(reconcile)
    assert sent == [command.idempotency_key, command.idempotency_key, following.idempotency_key]
    next_operation = await store.capture(actor, following)
    reopened = ProducerSpool(path, "capture-test", binding, 65536)
    try:
        receipt = {"state": "committed", "operation_id": legacy.id}
        assert reopened.disposition(command.idempotency_key) == receipt
        assert reopened.enqueue(command) == {**receipt, "replay": True}
        assert reopened.disposition(following.idempotency_key)["source_pointer"] == next_operation.source_pointer.model_dump(mode="json")
    finally:
        reopened.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("retracted", [False, True])
async def test_completed_correction_origin_capture_replay_preserves_authoritative_receipt(tmp_path, capture_authority, capture_endpoint, retracted):
    store, actor, binding = capture_authority
    endpoint, sent = capture_endpoint
    original = await store.capture(actor, envelope(binding_id=binding, idempotency_key="original", origin_key="original"))
    correction = envelope(binding_id=binding, idempotency_key="correct", origin_key="replacement", kind="correction", body="Keep customer data inside this project.")
    corrected = await store.correct(actor, binding, original.source_id, correction)
    assert corrected.kind == "correct" and corrected.capture_disposition == "captured"
    replay = correction.model_copy(update={"idempotency_key": "capture-correction-origin"})
    if retracted:
        await store.retract(actor, binding, corrected.source_id, "retract-correction")
    authoritative = await store.capture(actor, replay)
    assert authoritative.id == corrected.id and authoritative.kind == "correct"
    following = envelope(binding_id=binding, idempotency_key="after-correct", origin_key="after-correct")
    path = tmp_path / "producer" / "capture.sqlite3"

    def drain():
        spool = ProducerSpool(path, "capture-test", binding, 65536)
        try:
            spool.enqueue(replay)
            spool.enqueue(following)
            result = spool.flush(endpoint)
            assert result["committed"] == 2 and result["pending"] == result["quarantined"] == 0
            assert result["errors"] == []
        finally:
            spool.close()

    await asyncio.to_thread(drain)
    assert sent == [replay.idempotency_key, following.idempotency_key]
    reopened = ProducerSpool(path, "capture-test", binding, 65536)
    try:
        receipt = reopened.disposition(replay.idempotency_key)
        assert receipt["operation_id"] == corrected.id
        assert receipt["capture_disposition"] == ("retracted" if retracted else "captured")
        if retracted:
            assert authoritative.source_pointer is None
            assert "source_pointer" not in receipt
        else:
            assert receipt["source_pointer"] == corrected.source_pointer.model_dump(mode="json")
        assert reopened.enqueue(replay) == {**receipt, "replay": True}
    finally:
        reopened.close()


def test_fresh_legacy_secret_behind_a_transient_head_is_scrubbed_before_delivery(tmp_path):
    path = tmp_path / "producer" / "capture.sqlite3"
    secret = "ghp_" + "a" * 36
    spool = ProducerSpool(path, "deployment-001", "binding-001", 65536)
    spool.enqueue(envelope(idempotency_key="safe-first"))
    command = envelope(idempotency_key="legacy-second", origin_key="legacy-origin")
    spool.enqueue(command)
    payload = command.model_dump(mode="json")
    payload.update(body=secret, idempotency_key=secret)
    encoded = json.dumps(payload)
    spool.db.execute(
        "UPDATE outbox SET key=?,payload=?,digest=?,bytes=? WHERE key=?",
        (secret, encoded, "legacy-source-digest", len(encoded), "legacy-second"),
    )
    spool.close()
    reopened = ProducerSpool(path, "deployment-001", "binding-001", 65536)
    calls = []

    class UnavailableEndpoint:
        def request(self, route, payload):
            calls.append(payload["idempotency_key"])
            raise DomainError("SERVICE_UNAVAILABLE", "Delivery cannot start", status=503)

    try:
        result = reopened.flush(UnavailableEndpoint())
        assert calls == ["safe-first"]
        assert result["pending"] == 1 and result["quarantined"] == 1
        assert result["gaps"]["SOURCE_SECRET_REJECTED"] == 1
        entry, = reopened.inspect()["entries"]
        assert entry["code"] == "SOURCE_SECRET_REJECTED"
        assert entry["effect"] == entry["prior_effect"] == "unknown"
        assert entry["bytes"] == 0 and entry["digest"] == "" and entry["key"] != secret
        assert reopened.db.execute("SELECT key FROM outbox").fetchall() == [("safe-first",)]
        assert reopened.db.execute("SELECT digest,payload,bytes FROM quarantine").fetchall() == [("", "", 0)]
        assert secret not in json.dumps(reopened.inspect())
        for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
            if candidate.exists():
                assert secret.encode() not in candidate.read_bytes()
        with pytest.raises(DomainError) as caught:
            reopened.resolve(entry["key"])
        assert caught.value.code == "SOURCE_SECRET_REJECTED" and caught.value.effect == EffectState.UNKNOWN
    finally:
        reopened.close()


@pytest.mark.parametrize("table", ["outbox", "quarantine"])
def test_secret_legacy_payload_is_body_free_with_unknown_prior_effect(tmp_path, table):
    path = tmp_path / "producer" / "capture.sqlite3"
    secret = "ghp_" + "a" * 36
    command = envelope()
    spool = ProducerSpool(path, "deployment-001", "binding-001", 65536)
    spool.enqueue(command)
    payload = command.model_dump(mode="json")
    payload["body"] = secret
    payload["idempotency_key"] = secret
    encoded = json.dumps(payload)
    spool.db.execute("UPDATE outbox SET key=?,payload=?,digest=?,bytes=?", (secret, encoded, "legacy-source-digest", len(encoded)))
    if table == "quarantine":
        spool.db.execute(
            "INSERT INTO quarantine SELECT key,digest,payload,bytes,'INPUT_INVALID',created_at,expires_at FROM outbox"
        )
        spool.db.execute("DELETE FROM outbox")
    spool.close()
    reopened = ProducerSpool(path, "deployment-001", "binding-001", 65536)
    attempts = []

    class ForbiddenEndpoint:
        def request(self, route, payload):
            attempts.append(payload)
            raise AssertionError("A refused legacy source must not be dispatched")

    try:
        result = reopened.flush(ForbiddenEndpoint())
        assert not attempts and result["pending"] == 0 and result["quarantined"] == 1
        entry, = reopened.inspect()["entries"]
        assert entry["code"] == "SOURCE_SECRET_REJECTED"
        assert entry["effect"] == entry["prior_effect"] == "unknown"
        assert entry["bytes"] == 0 and entry["digest"] == ""
        assert secret not in json.dumps(reopened.inspect())
        row = reopened.db.execute("SELECT key,digest,payload,bytes FROM quarantine").fetchone()
        assert row[1:] == ("", "", 0) and row[0] != secret
        with pytest.raises(DomainError) as caught:
            reopened.resolve(entry["key"])
        assert caught.value.effect == EffectState.UNKNOWN
        assert reopened.disposition(entry["key"])["prior_effect"] == "unknown"
        assert reopened.resolve(entry["key"], discard=True)["state"] == "discarded"
    finally:
        reopened.close()
    assert secret.encode() not in path.read_bytes()


@pytest.mark.parametrize("table", ["outbox", "quarantine"])
@pytest.mark.parametrize("secret_field", ["body", "idempotency_key"])
@pytest.mark.parametrize("age,boundary", [
    ("expired", "open"), ("unknown", "open"), ("missing_columns", "open"),
    ("expired", "housekeep"), ("unknown", "housekeep"),
])
def test_aged_legacy_secret_never_creates_a_secret_derived_expiry_receipt(tmp_path, clock, table, secret_field, age, boundary):
    path = tmp_path / "producer" / "capture.sqlite3"
    path.parent.mkdir(mode=0o700)
    path.touch(mode=0o600)
    spool = ProducerSpool(path, "deployment-001", "binding-001", 65536) if boundary == "housekeep" else None
    secret = "ghp_" + "a" * 36
    payload = envelope(idempotency_key="legacy-secret").model_dump(mode="json")
    payload[secret_field] = secret
    secret_key = payload["idempotency_key"]
    secret_digest = canonical_digest(payload)
    safe = envelope(idempotency_key="safe-expiring", origin_key="safe-expiring")
    committed = envelope(idempotency_key="safe-committed", origin_key="safe-committed")
    created_at = clock[0] - spool_module.PAYLOAD_RETENTION_SECONDS
    expires_at = clock[0] if age == "expired" else 0
    ages = "" if age == "missing_columns" else ",created_at REAL NOT NULL DEFAULT 0,expires_at REAL NOT NULL DEFAULT 0"
    connection = sqlite3.connect(path)
    try:
        if boundary == "open":
            connection.executescript(
                "CREATE TABLE identity (slot INTEGER PRIMARY KEY, deployment TEXT NOT NULL, binding TEXT NOT NULL);"
                "INSERT INTO identity VALUES(1,'deployment-001','binding-001');"
                f"CREATE TABLE outbox (key TEXT PRIMARY KEY, digest TEXT NOT NULL, payload TEXT NOT NULL, bytes INTEGER NOT NULL, failure TEXT{ages});"
                f"CREATE TABLE quarantine (key TEXT PRIMARY KEY, digest TEXT NOT NULL, payload TEXT NOT NULL, bytes INTEGER NOT NULL, failure TEXT NOT NULL{ages});"
                "CREATE TABLE receipts (key TEXT PRIMARY KEY, digest TEXT NOT NULL, state TEXT NOT NULL, operation_id TEXT, created_at REAL NOT NULL DEFAULT 0);"
            )
        for key, digest, body in (
            (secret_key, secret_digest, payload),
            (safe.idempotency_key, canonical_digest(safe.digest_payload()), safe.model_dump(mode="json")),
        ):
            encoded = json.dumps(body)
            values = (key, digest, encoded, len(encoded.encode("utf-8")), "INPUT_INVALID")
            if age == "missing_columns":
                connection.execute(f"INSERT INTO {table}(key,digest,payload,bytes,failure) VALUES(?,?,?,?,?)", values)
            else:
                connection.execute(
                    f"INSERT INTO {table}(key,digest,payload,bytes,failure,created_at,expires_at) VALUES(?,?,?,?,?,?,?)",
                    (*values, created_at, expires_at),
                )
        connection.execute(
            "INSERT INTO receipts(key,digest,state,operation_id,created_at) VALUES(?,?,'committed','operation-safe',?)",
            (committed.idempotency_key, canonical_digest(committed.digest_payload()), clock[0]),
        )
        connection.commit()
    finally:
        connection.close()
    if spool is None:
        spool = ProducerSpool(path, "deployment-001", "binding-001", 65536)
    try:
        inspection = spool.inspect()
        gap = "SPOOL_PAYLOAD_EXPIRED" if age == "expired" else "SPOOL_PAYLOAD_AGE_UNKNOWN"
        assert inspection["entries"] == []
        assert inspection["pending"] == inspection["quarantined"] == inspection["bytes"] == 0
        assert inspection["gaps"] == {gap: 2, "SOURCE_SECRET_REJECTED": 1}
        assert inspection["retained_receipts"] == 2
        assert secret not in json.dumps(inspection) and secret_digest not in json.dumps(inspection)
        assert spool.db.execute("SELECT 1 FROM receipts WHERE key=? OR digest=?", (secret_key, secret_digest)).fetchone() is None
        with pytest.raises(DomainError) as caught:
            spool.disposition(secret_key)
        assert caught.value.code == "SPOOL_REPLAY_EXPIRED_OR_UNKNOWN"
        assert secret not in json.dumps(caught.value.public())
        assert spool.disposition(safe.idempotency_key) == {"state": "expired", "operation_id": None}
        assert spool.enqueue(safe) == {"state": "expired", "operation_id": None, "replay": True}
        assert spool.enqueue(committed) == {"state": "committed", "operation_id": "operation-safe", "replay": True}
        persisted = "\n".join(spool.db.iterdump())
        assert secret not in persisted and secret_digest not in persisted
        for companion in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
            if companion.exists():
                data = companion.read_bytes()
                assert secret.encode() not in data and secret_digest.encode() not in data
    finally:
        spool.close()
    reopened = ProducerSpool(path, "deployment-001", "binding-001", 65536)
    try:
        assert reopened.status()["gaps"] == {gap: 2, "SOURCE_SECRET_REJECTED": 1}
        assert reopened.disposition(committed.idempotency_key) == {"state": "committed", "operation_id": "operation-safe"}
        assert secret not in "\n".join(reopened.db.iterdump())
    finally:
        reopened.close()


@pytest.mark.parametrize("malformation", ["type", "extra", "digest", "key"])
def test_legacy_spool_requires_complete_typed_identity_before_dispatch(tmp_path, malformation):
    spool = ProducerSpool(tmp_path / "producer" / "capture.sqlite3", "deployment-001", "binding-001", 65536)
    command = envelope()
    try:
        spool.enqueue(command)
        payload = command.model_dump(mode="json")
        if malformation == "type":
            payload["injected"] = "false"
        elif malformation == "extra":
            payload["invented_authority"] = True
        elif malformation == "key":
            payload["idempotency_key"] = "another-key"
        spool.db.execute(
            "UPDATE outbox SET payload=?,digest=?",
            (json.dumps(payload), "wrong-digest" if malformation == "digest" else canonical_digest(command.digest_payload())),
        )
        attempts = []

        class ForbiddenEndpoint:
            def request(self, route, payload):
                attempts.append(payload)
                raise AssertionError("Invalid legacy payload reached dispatch")

        result = spool.flush(ForbiddenEndpoint())
        assert not attempts and result["errors"] == ["SPOOL_PAYLOAD_INVALID"]
        assert result["pending"] == 0 and result["newly_quarantined"] == 1
        entry, = spool.inspect()["entries"]
        assert entry["prior_effect"] == "unknown" and entry["bytes"] == 0
    finally:
        spool.close()


@pytest.mark.parametrize("body", (
    " \tNegation: do not export.\r\n예외도 보존합니다.  ",
    "-----BEGIN PRIVATE KEY-----\n" + " " * 64 + "\n-----END PRIVATE KEY-----",
))
def test_typed_enqueue_does_not_reclassify_or_rewrite_admitted_source(tmp_path, monkeypatch, body):
    command = envelope(body=body)
    spool = ProducerSpool(tmp_path / "producer" / "capture.sqlite3", "deployment-001", "binding-001", 65536)
    try:
        def forbidden_scan(text):
            raise AssertionError("Typed admission was scanned again during enqueue")

        monkeypatch.setattr("agents_memory.domain.reject_source_secrets", forbidden_scan)
        spool.enqueue(command)
        row = spool.db.execute("SELECT payload,digest FROM outbox").fetchone()
        assert json.loads(row[0])["body"].encode() == command.body.encode()
        assert row[1] == canonical_digest(command.digest_payload())
    finally:
        spool.close()


def test_stale_source_scrub_preserves_acknowledged_replacement(tmp_path, monkeypatch):
    path = tmp_path / "producer" / "capture.sqlite3"
    left = ProducerSpool(path, "deployment-001", "binding-001", 65536)
    right = ProducerSpool(path, "deployment-001", "binding-001", 65536)

    try:
        safe = envelope()
        left.enqueue(safe)
        digest, payload = left.db.execute(
            "SELECT digest,payload FROM outbox WHERE key=?", (safe.idempotency_key,),
        ).fetchone()
        legacy = json.loads(payload)
        legacy["body"] = "ghp_" + "a" * 36
        invalid = json.dumps(legacy)
        left.db.execute(
            "UPDATE outbox SET payload=?,bytes=? WHERE key=?",
            (invalid, len(invalid.encode()), safe.idempotency_key),
        )

        original = left._quarantine_invalid
        acknowledged = []

        def replace_after_classification(*args, **kwargs):
            assert not acknowledged
            right._scrub_legacy_sources()
            acknowledged.append(right.enqueue(safe))
            assert acknowledged[0]["state"] == "durably_spooled"
            return original(*args, **kwargs)

        monkeypatch.setattr(left, "_quarantine_invalid", replace_after_classification)
        left._scrub_legacy_sources()
        result = left.status()
        assert len(acknowledged) == 1
        retained = left.db.execute(
            "SELECT digest,payload FROM outbox WHERE key=?", (safe.idempotency_key,),
        ).fetchone()
        assert retained == (digest, payload), "A stale classifier deleted an acknowledged safe replacement"
        assert result["pending"] == 1 and result["quarantined"] == 1
        assert result["gaps"] == {"SOURCE_SECRET_REJECTED": 1}
    finally:
        right.close()
        left.close()


@pytest.mark.parametrize("outcome", ("committed", "rejected"))
def test_late_network_result_preserves_acknowledged_replacement_after_receipt_eviction(tmp_path, clock, outcome):
    path = tmp_path / "producer" / "capture.sqlite3"
    left = ProducerSpool(path, "deployment-001", "binding-001", 65536)
    right = ProducerSpool(path, "deployment-001", "binding-001", 65536)
    original = envelope()
    replacement = envelope(origin_key="replacement-origin", body="Retain the independently captured replacement.")
    acknowledged = []

    class LateOriginal:
        def request(self, route, payload):
            assert payload["body"] == original.body
            clock[0] += 2
            assert right.status()["pending"] == 0
            assert right.disposition(original.idempotency_key)["state"] == "expired"
            for index in range(right.receipt_limit):
                right.enqueue(envelope(idempotency_key=f"receipt-filler-{index}", origin_key=f"filler-origin-{index}"))
            clock[0] += 24 * 60 * 60 + 1
            assert right.status()["pending"] == 0
            assert right.db.execute("SELECT 1 FROM receipts WHERE key=?", (original.idempotency_key,)).fetchone() is None
            acknowledged.append(right.enqueue(replacement))
            assert acknowledged[0]["state"] == "durably_spooled"
            if outcome == "rejected":
                raise DomainError("INPUT_INVALID", "Original envelope was rejected", effect=EffectState.NOT_COMMITTED)
            return {"effect": "committed", "id": "operation-original"}

    try:
        left.enqueue(original)
        clock[0] += 24 * 60 * 60 - 1
        result = left.flush(LateOriginal(), limit=1)
        assert len(acknowledged) == 1
        retained = right.db.execute("SELECT digest,payload FROM outbox WHERE key=?", (replacement.idempotency_key,)).fetchone()
        assert retained is not None, "A late result removed another envelope's durable acknowledgment"
        assert retained[0] == canonical_digest(replacement.digest_payload())
        assert json.loads(retained[1])["body"] == replacement.body
        assert right.disposition(replacement.idempotency_key) == {"state": "durably_spooled"}
        assert result["pending"] == 1 and result["quarantined"] == 0
        assert result["committed"] == (1 if outcome == "committed" else 0)
    finally:
        right.close()
        left.close()
