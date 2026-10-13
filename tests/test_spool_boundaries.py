import json
import sqlite3

import pytest

from agents_memory import spool as spool_module
from agents_memory.domain import CaptureCommand, DomainError, EffectState, canonical_digest
from agents_memory.spool import ProducerSpool


def envelope(**changes):
    return CaptureCommand.model_validate({
        "binding_id": "binding-001", "idempotency_key": "capture-001",
        "origin_key": "origin-001", "body": "Do not export customer data.",
        "speaker": "human", **changes,
    })


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


def test_another_project_cannot_take_existing_outbox(tmp_path):
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


def test_quarantine_retry_and_discard_are_explicit_and_durable(tmp_path):
    path = tmp_path / "outbox.sqlite"
    spool = ProducerSpool(path, "deployment-001", "binding-001", 65536)

    class Reject:
        def request(self, route, payload):
            raise DomainError("INPUT_INVALID", "No raw evidence", status=422)

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


def test_unknown_effect_never_becomes_permanent_quarantine_even_with_conflict_code(tmp_path):
    spool = ProducerSpool(tmp_path / "outbox.sqlite", "deployment-001", "binding-001", 65536)
    calls = []

    class Endpoint:
        def request(self, route, payload):
            calls.append(payload)
            raise DomainError("ORIGIN_CONFLICT", "Unreconciled upstream outcome", effect=EffectState.UNKNOWN)

    try:
        spool.enqueue(envelope())
        spool.enqueue(envelope(idempotency_key="capture-002", origin_key="origin-002"))
        result = spool.flush(Endpoint())
        assert len(calls) == 1
        assert result["pending"] == 2 and result["quarantined"] == 0
    finally:
        spool.close()


@pytest.mark.parametrize("late_rejection", [False, True])
def test_overlapping_drains_preserve_confirmed_receipt_without_duplicate_local_failure(tmp_path, late_rejection):
    path = tmp_path / "outbox.sqlite"
    first = ProducerSpool(path, "deployment-001", "binding-001", 65536)
    second = ProducerSpool(path, "deployment-001", "binding-001", 65536)

    class Committed:
        def request(self, route, payload):
            return {"effect": "committed", "id": "operation-001"}

    class Overlap:
        def request(self, route, payload):
            assert second.flush(Committed())["committed"] == 1
            if late_rejection:
                raise DomainError("ORIGIN_CONFLICT", "Older rejected attempt after confirmed parallel commit")
            return {"effect": "committed", "id": "operation-001"}

    try:
        first.enqueue(envelope())
        result = first.flush(Overlap())
        assert result["pending"] == result["quarantined"] == 0
        assert first.disposition("capture-001") == {"state": "committed", "operation_id": "operation-001"}
        assert first.enqueue(envelope()) == {"state": "committed", "replay": True, "operation_id": "operation-001"}
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


def test_payload_original_age_survives_unknown_retry_quarantine_replay_and_reopen(tmp_path, clock):
    path = tmp_path / "outbox.sqlite"
    spool = ProducerSpool(path, "deployment-001", "binding-001", 65536)

    class Unknown:
        def request(self, route, payload):
            raise DomainError("SERVICE_UNAVAILABLE", "Outcome unavailable", effect=EffectState.UNKNOWN)

    class Rejected:
        def request(self, route, payload):
            raise DomainError("INPUT_INVALID", "Confirmed rejection", effect=EffectState.NOT_COMMITTED)

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
            payload = json.dumps(command.model_dump(mode="json"), separators=(",", ":"))
            digest = canonical_digest(command.model_dump(mode="json"))
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
