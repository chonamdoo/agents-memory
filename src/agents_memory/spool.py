from __future__ import annotations

import json
import os
import sqlite3
import stat
import time
import uuid
from contextlib import contextmanager, suppress
from pathlib import Path

from pydantic import ValidationError

from .client import LocalClient
from .domain import (
    CaptureCommand,
    DomainError,
    EffectState,
    Operation,
    SourcePointer,
    canonical_digest,
    reject_source_secrets,
)
from .wire import decode_json

TRANSIENT_CODES = {
    "AUTH_DENIED", "UNAUTHORIZED", "CREDENTIAL_REVOKED", "CREDENTIAL_INVALID",
    "SERVICE_UNAVAILABLE", "SERVICE_DRAINING", "AUTHORITY_UNAVAILABLE", "QUEUE_FULL",
    "DELETION_BARRIER", "RESTORE_RECOVERY_REQUIRED", "RESPONSE_INVALID",
    "RESPONSE_TOO_LARGE", "CAPTURE_RECEIPT_INVALID",
}
PERMANENT_CODES = {
    "ORIGIN_CONFLICT", "IDEMPOTENCY_CONFLICT", "SCOPE_DENIED", "ROLE_DENIED",
    "BODY_TOO_LARGE", "INPUT_TOO_LARGE", "INPUT_INVALID", "CAPTURE_INJECTED_REJECTED",
    "ORIGIN_RETRACTED", "SOURCE_RETRACTED", "CAPTURE_COVERAGE_INVALID",
}
LOCAL_QUARANTINE_CODES = {"SOURCE_SECRET_REJECTED", "SPOOL_PAYLOAD_INVALID"}

PAYLOAD_RETENTION_SECONDS = 24 * 60 * 60
RECEIPT_RETENTION_SECONDS = 24 * 60 * 60
RECEIPT_MAX_COUNT = 4096
HOUSEKEEPING_ROWS = 128


class ProducerSpool:
    def __init__(self, path: Path, deployment_id: str, binding_id: str, limit_bytes: int) -> None:
        self.path = path
        self.deployment_id = deployment_id
        self.binding_id = binding_id
        self.limit_bytes = limit_bytes
        if limit_bytes < 1 or path.is_symlink() or path.parent.is_symlink():
            raise DomainError("SPOOL_PATH_DENIED", "The outbox must use a private owned local path")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory = path.parent.stat()
        if directory.st_uid != os.getuid() or directory.st_mode & 0o077:
            raise DomainError("SPOOL_PATH_DENIED", "The outbox directory must be owned and private")
        for companion in (Path(str(path) + "-wal"), Path(str(path) + "-shm")):
            if companion.is_symlink():
                raise DomainError("SPOOL_PATH_DENIED", "The outbox cannot follow sidecar symlinks")
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise DomainError("SPOOL_PATH_DENIED", "The outbox file must be owned and private")
        finally:
            os.close(descriptor)
        self.receipt_limit = min(RECEIPT_MAX_COUNT, max(16, limit_bytes // 8192))
        self.storage_limit_bytes = 2 * limit_bytes + 262144
        connection = None
        try:
            self.db = connection = sqlite3.connect(path, timeout=1, isolation_level=None)
            self.db.execute("PRAGMA auto_vacuum=INCREMENTAL")
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute("PRAGMA fullfsync=ON")
            self.db.execute("PRAGMA checkpoint_fullfsync=ON")
            self.db.execute("PRAGMA busy_timeout=1000")
            self.db.execute("PRAGMA secure_delete=ON")
            self.db.execute("PRAGMA journal_size_limit=65536")
            page_size = self.db.execute("PRAGMA page_size").fetchone()[0]
            self.db.execute(f"PRAGMA max_page_count={max(32, (self.storage_limit_bytes - 131072) // page_size)}")
            self.db.executescript(
                "CREATE TABLE IF NOT EXISTS identity (slot INTEGER PRIMARY KEY CHECK(slot=1), deployment TEXT NOT NULL, binding TEXT NOT NULL);"
                "CREATE TABLE IF NOT EXISTS outbox (key TEXT PRIMARY KEY, digest TEXT NOT NULL, payload TEXT NOT NULL, bytes INTEGER NOT NULL, failure TEXT, created_at REAL NOT NULL DEFAULT 0, expires_at REAL NOT NULL DEFAULT 0);"
                "CREATE TABLE IF NOT EXISTS gaps (code TEXT PRIMARY KEY, count INTEGER NOT NULL);"
                "CREATE TABLE IF NOT EXISTS quarantine (key TEXT PRIMARY KEY, digest TEXT NOT NULL, payload TEXT NOT NULL, bytes INTEGER NOT NULL, failure TEXT NOT NULL, created_at REAL NOT NULL DEFAULT 0, expires_at REAL NOT NULL DEFAULT 0);"
                "CREATE TABLE IF NOT EXISTS receipts (key TEXT PRIMARY KEY, digest TEXT NOT NULL, state TEXT NOT NULL, operation_id TEXT, created_at REAL NOT NULL DEFAULT 0);"
            )
            with self._transaction():
                identity = self.db.execute("SELECT deployment,binding FROM identity WHERE slot=1").fetchone()
                if identity is None:
                    self.db.execute("INSERT INTO identity VALUES(1,?,?)", (deployment_id, binding_id))
                elif identity != (deployment_id, binding_id):
                    raise DomainError("SPOOL_SCOPE_CONFLICT", "The outbox belongs to another deployment or project")
                columns = {row[1] for row in self.db.execute("PRAGMA table_info(receipts)")}
                if "created_at" not in columns:
                    self.db.execute("ALTER TABLE receipts ADD COLUMN created_at REAL NOT NULL DEFAULT 0")
                for column in ("source_pointer", "capture_disposition"):
                    if column not in columns:
                        self.db.execute(f"ALTER TABLE receipts ADD COLUMN {column} TEXT")
                self.db.execute("CREATE INDEX IF NOT EXISTS receipt_age ON receipts(created_at,key)")
                legacy_tables = []
                for table in ("outbox", "quarantine"):
                    columns = {row[1] for row in self.db.execute(f"PRAGMA table_info({table})")}
                    for column in ("created_at", "expires_at"):
                        if column not in columns:
                            self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column} REAL NOT NULL DEFAULT 0")
                    if not {"created_at", "expires_at"} <= columns:
                        legacy_tables.append(table)
                    else:
                        self.db.execute(f"CREATE INDEX IF NOT EXISTS {table}_expiry ON {table}(expires_at,key)")
                self._prune_payloads(tuple(legacy_tables))
                for table in legacy_tables:
                    self.db.execute(f"CREATE INDEX IF NOT EXISTS {table}_expiry ON {table}(expires_at,key)")
                for key, failure in self.db.execute("SELECT key,failure FROM outbox WHERE failure IS NOT NULL LIMIT ?", (HOUSEKEEPING_ROWS,)).fetchall():
                    if failure in PERMANENT_CODES:
                        self.db.execute(
                            "INSERT OR IGNORE INTO quarantine(key,digest,payload,bytes,failure,created_at,expires_at) "
                            "SELECT key,digest,payload,bytes,failure,created_at,expires_at FROM outbox WHERE key=?",
                            (key,),
                        )
                        self.db.execute("DELETE FROM outbox WHERE key=?", (key,))
                self._prune_receipts()
            self._scrub_legacy_sources()
            self._housekeep()
        except Exception as error:
            if connection is not None:
                with suppress(sqlite3.Error):
                    connection.close()
            if isinstance(error, sqlite3.Error):
                raise DomainError("HOST_SPOOL_UNAVAILABLE", "The private producer spool is unavailable") from None
            raise

    @contextmanager
    def _transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except Exception:
            if self.db.in_transaction:
                with suppress(sqlite3.Error):
                    self.db.execute("ROLLBACK")
            raise

    def _gap(self, code: str, count: int = 1) -> None:
        self.db.execute("INSERT INTO gaps VALUES(?,?) ON CONFLICT(code) DO UPDATE SET count=count+excluded.count", (code, count))

    def _prune_receipts(self) -> None:
        rows = self.db.execute(
            "SELECT key FROM receipts WHERE created_at<? ORDER BY created_at,key LIMIT ?",
            (time.time() - RECEIPT_RETENTION_SECONDS, HOUSEKEEPING_ROWS),
        ).fetchall()
        remaining = HOUSEKEEPING_ROWS - len(rows)
        if remaining:
            expired = {row[0] for row in rows}
            candidates = self.db.execute(
                "SELECT key FROM receipts ORDER BY (state='committed') DESC,created_at DESC,key DESC LIMIT ? OFFSET ?",
                (remaining, self.receipt_limit),
            ).fetchall()
            rows.extend(row for row in candidates if row[0] not in expired)
        if rows:
            self.db.executemany("DELETE FROM receipts WHERE key=?", rows)
            self._gap("SPOOL_RECEIPT_REPLAY_EXPIRED", len(rows))

    def _prune_payloads(self, legacy_tables: tuple[str, ...] = ()) -> None:
        now = time.time()
        for table in ("outbox", "quarantine"):
            if table in legacy_tables:
                query = f"SELECT key,digest,0,payload FROM {table} ORDER BY key LIMIT ?"
                parameters = (HOUSEKEEPING_ROWS,)
            else:
                query = f"SELECT key,digest,expires_at,payload FROM {table} WHERE expires_at<=? ORDER BY expires_at,key LIMIT ?"
                parameters = (now, HOUSEKEEPING_ROWS)
            while rows := self.db.execute(query, parameters).fetchall():
                secret_keys = {
                    key for key, _, _, payload in rows
                    if self._payload_rejection(key, payload) == "SOURCE_SECRET_REJECTED"
                }
                self.db.executemany(f"DELETE FROM {table} WHERE key=?", ((key,) for key, _, _, _ in rows))
                self.db.executemany(
                    "INSERT INTO receipts(key,digest,state,operation_id,created_at) VALUES(?,?,'expired',NULL,?) "
                    "ON CONFLICT(key) DO NOTHING",
                    ((key, digest, now) for key, digest, _, _ in rows if key not in secret_keys),
                )
                if secret_keys:
                    self._gap("SOURCE_SECRET_REJECTED", len(secret_keys))
                unknown_age = sum(expires_at == 0 for _, _, expires_at, _ in rows)
                if unknown_age:
                    self._gap("SPOOL_PAYLOAD_AGE_UNKNOWN", unknown_age)
                if len(rows) > unknown_age:
                    self._gap("SPOOL_PAYLOAD_EXPIRED", len(rows) - unknown_age)
                self._prune_receipts()

    def _housekeep(self) -> None:
        with self._transaction():
            self._prune_payloads()
            self._prune_receipts()
        self.db.execute("PRAGMA incremental_vacuum(64)").fetchall()
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()

    def _storage_bytes(self) -> int:
        return sum(path.stat().st_size for path in (
            self.path, Path(str(self.path) + "-wal"), Path(str(self.path) + "-shm"),
        ) if path.exists())

    def _store_receipt(
        self, key: str, digest: str, state: str, operation: str | None,
        *, pointer: SourcePointer | None = None, disposition: str | None = None,
    ) -> None:
        encoded = pointer.model_dump_json() if pointer is not None else None
        self.db.execute(
            "INSERT INTO receipts(key,digest,state,operation_id,created_at,source_pointer,capture_disposition) VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET state=excluded.state,operation_id=COALESCE(receipts.operation_id,excluded.operation_id),"
            "source_pointer=CASE WHEN excluded.capture_disposition IS NOT NULL THEN excluded.source_pointer ELSE receipts.source_pointer END,"
            "capture_disposition=COALESCE(excluded.capture_disposition,receipts.capture_disposition) WHERE receipts.digest=excluded.digest",
            (key, digest, state, operation, time.time(), encoded, disposition),
        )
        self._prune_receipts()

    def _receipt_result(self, row: tuple) -> dict:
        state, operation, encoded, disposition = row
        result = {"state": state, "operation_id": operation}
        if disposition == "captured" and encoded is None:
            raise DomainError("CAPTURE_RECEIPT_INVALID", "The persisted capture pointer is missing", effect=EffectState.UNKNOWN)
        if encoded is not None:
            try:
                pointer = SourcePointer.model_validate_json(encoded, strict=True)
                if disposition != "captured":
                    raise ValueError("Contradictory persisted capture disposition")
                self._validate_pointer(pointer)
            except (ValidationError, ValueError):
                raise DomainError("CAPTURE_RECEIPT_INVALID", "The persisted capture pointer is invalid", effect=EffectState.UNKNOWN) from None
            result["source_pointer"] = pointer.model_dump(mode="json")
        if disposition is not None:
            if disposition not in {"captured", "ignored", "retracted", "unresolved"}:
                raise DomainError("CAPTURE_RECEIPT_INVALID", "The persisted capture disposition is invalid", effect=EffectState.UNKNOWN)
            result["capture_disposition"] = disposition
        return result

    def _validate_pointer(self, pointer: SourcePointer) -> None:
        if (
            pointer.binding_id != self.binding_id
            or pointer.source_speaker not in {"human", "assistant", "tool", "document", "agent_note", "memory"}
            or pointer.source_recorded_at.tzinfo is None
            or (pointer.source_event_time is not None and pointer.source_event_time.tzinfo is None)
            or len(pointer.model_dump_json().encode("utf-8")) > 8192
        ):
            raise ValueError("Invalid authoritative source pointer")

    def _capture_ack(self, result: object) -> tuple[str, SourcePointer | None, str | None]:
        if not isinstance(result, dict) or result.get("effect") != "committed":
            raise ValueError("Unconfirmed capture ACK")
        if not isinstance(result.get("id"), str) or not result["id"] or len(result["id"].encode("utf-8")) > 512:
            raise ValueError("Invalid operation identity")
        if set(result) <= {"effect", "id"}:
            return result["id"], None, None
        operation = Operation.model_validate_json(json.dumps(result, allow_nan=False), strict=True)
        if operation.binding_id != self.binding_id or operation.kind not in {"capture", "correct"}:
            raise ValueError("Capture scope mismatch")
        if ("source_pointer" in result) != ("capture_disposition" in result):
            raise ValueError("Incomplete capture provenance")
        pointer, disposition = operation.source_pointer, operation.capture_disposition
        if pointer is None and disposition is None:
            return operation.id, None, None
        if disposition is None or (disposition == "captured" and pointer is None):
            raise ValueError("Missing capture provenance")
        if pointer is not None:
            self._validate_pointer(pointer)
            if disposition != "captured" or pointer.source_id != operation.source_id:
                raise ValueError("Contradictory capture pointer")
        if disposition == "retracted" and operation.state != "retracted":
            raise ValueError("Contradictory retraction ACK")
        if operation.state == "retracted" and disposition != "retracted":
            raise ValueError("Retracted source cannot supply a live capture pointer")
        return operation.id, pointer, disposition

    def close(self) -> None:
        self.db.close()

    def enqueue(self, command: CaptureCommand) -> dict:
        if command.binding_id != self.binding_id:
            raise DomainError("SPOOL_SCOPE_CONFLICT", "The envelope targets another project")
        if command.injected or command.speaker == "memory":
            raise DomainError("CAPTURE_INJECTED_REJECTED", "Retrieved memory cannot become new evidence")
        envelope = command.model_dump(mode="json")
        digest = canonical_digest(command.digest_payload())
        payload = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
        size = len(payload.encode("utf-8"))
        self._housekeep()
        overflow = False
        with self._transaction():
            self._prune_payloads()
            receipt = self.db.execute("SELECT digest,state,operation_id,source_pointer,capture_disposition FROM receipts WHERE key=? AND created_at>=?", (command.idempotency_key, time.time() - RECEIPT_RETENTION_SECONDS)).fetchone()
            if receipt is not None:
                if receipt[0] != digest:
                    raise DomainError("IDEMPOTENCY_CONFLICT", "The outbox retry key has another envelope")
                return {**self._receipt_result(receipt[1:]), "replay": True}
            existing = self.db.execute(
                "SELECT digest FROM outbox WHERE key=? UNION ALL SELECT digest FROM quarantine WHERE key=?",
                (command.idempotency_key, command.idempotency_key),
            ).fetchone()
            if existing is not None:
                if existing[0] != digest:
                    raise DomainError("IDEMPOTENCY_CONFLICT", "The outbox retry key has another envelope")
                return {"state": "durably_spooled", "replay": True}
            used = self.db.execute("SELECT COALESCE(SUM(bytes),0) FROM (SELECT bytes FROM outbox UNION ALL SELECT bytes FROM quarantine)").fetchone()[0]
            if used + size > self.limit_bytes or self._storage_bytes() + 2 * size + 16384 > self.storage_limit_bytes:
                self._gap("SPOOL_FULL")
                overflow = True
            else:
                created_at = time.time()
                self.db.execute(
                    "INSERT INTO outbox(key,digest,payload,bytes,failure,created_at,expires_at) VALUES(?,?,?,?,NULL,?,?)",
                    (command.idempotency_key, digest, payload, size, created_at, created_at + PAYLOAD_RETENTION_SECONDS),
                )
        self._housekeep()
        if overflow:
            raise DomainError("SPOOL_FULL", "No envelope was accepted; the durable gap counter increased", status=429)
        return {"state": "durably_spooled", "replay": False, "receipt_replay": "unavailable_server_idempotency_reconciliation"}

    def status(self) -> dict:
        self._housekeep()
        count = self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]
        dead = self.db.execute("SELECT COUNT(*) FROM quarantine").fetchone()[0]
        size = self.db.execute("SELECT COALESCE(SUM(bytes),0) FROM (SELECT bytes FROM outbox UNION ALL SELECT bytes FROM quarantine)").fetchone()[0]
        gaps = dict(self.db.execute("SELECT code,count FROM gaps"))
        blocked = dict(self.db.execute("SELECT failure,COUNT(*) FROM quarantine GROUP BY failure"))
        receipts = self.db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
        return {
            "pending": count, "quarantined": dead, "bytes": size, "limit_bytes": self.limit_bytes,
            "storage_bytes": self._storage_bytes(), "storage_limit_bytes": self.storage_limit_bytes,
            "retained_receipts": receipts, "receipt_limit": self.receipt_limit,
            "receipt_retention_seconds": RECEIPT_RETENTION_SECONDS,
            "payload_retention_seconds": PAYLOAD_RETENTION_SECONDS,
            "expired_replay": "no_local_prior_result_reconcile_same_envelope_with_server",
            "gaps": gaps, "blocked": blocked,
        }

    def disposition(self, key: str) -> dict:
        self._housekeep()
        receipt = self.db.execute("SELECT state,operation_id,source_pointer,capture_disposition FROM receipts WHERE key=? AND created_at>=?", (key, time.time() - RECEIPT_RETENTION_SECONDS)).fetchone()
        if receipt is not None:
            return self._receipt_result(receipt)
        rejected = self.db.execute("SELECT failure FROM quarantine WHERE key=?", (key,)).fetchone()
        if rejected is not None:
            if rejected[0] in LOCAL_QUARANTINE_CODES:
                return {"state": "quarantined", "code": rejected[0], "effect": "unknown", "prior_effect": "unknown", "replay": "unavailable"}
            return {"state": "quarantined", "code": rejected[0]}
        if self.db.execute("SELECT 1 FROM outbox WHERE key=?", (key,)).fetchone() is not None:
            return {"state": "durably_spooled"}
        raise DomainError("SPOOL_REPLAY_EXPIRED_OR_UNKNOWN", "No local replay result remains; reconcile the original envelope with server idempotency")

    def inspect(self, key: str | None = None, limit: int = 32) -> dict:
        if not 1 <= limit <= 128:
            raise DomainError("SPOOL_LIMIT_INVALID", "Choose a bounded inspection limit")
        self._housekeep()
        rows = self.db.execute(
            "SELECT key,digest,bytes,failure FROM quarantine WHERE (? IS NULL OR key=?) ORDER BY rowid LIMIT ?",
            (key, key, limit),
        ).fetchall()
        entries = [
            {**dict(zip(("key", "digest", "bytes", "code"), row, strict=True)),
             **({"effect": "unknown", "prior_effect": "unknown", "replay": "unavailable"} if row[3] in LOCAL_QUARANTINE_CODES else {})}
            for row in rows
        ]
        return {"entries": entries, **self.status()}

    def resolve(self, key: str, *, discard: bool = False) -> dict:
        self._housekeep()
        state = "discarded" if discard else "durably_spooled"
        with self._transaction():
            self._prune_payloads()
            row = self.db.execute("SELECT key,digest,failure FROM quarantine WHERE key=?", (key,)).fetchone()
            if row is None:
                receipt = self.db.execute(
                    "SELECT state FROM receipts WHERE key=? AND created_at>=?",
                    (key, time.time() - RECEIPT_RETENTION_SECONDS),
                ).fetchone()
                if receipt is None or receipt[0] != "expired":
                    raise DomainError("SPOOL_ENTRY_NOT_FOUND", "No quarantined envelope has this key")
                state = "expired"
            else:
                if not discard and row[2] in LOCAL_QUARANTINE_CODES:
                    raise DomainError(row[2], "This body-free quarantine cannot be replayed; its prior remote effect is unknown", effect=EffectState.UNKNOWN)
                if discard:
                    self._store_receipt(row[0], row[1], "discarded", None)
                    self._gap("SPOOL_DISCARDED")
                else:
                    self.db.execute(
                        "INSERT INTO outbox(key,digest,payload,bytes,failure,created_at,expires_at) "
                        "SELECT key,digest,payload,bytes,NULL,created_at,expires_at FROM quarantine WHERE key=?",
                        (key,),
                    )
                self.db.execute("DELETE FROM quarantine WHERE key=?", (key,))
        self._housekeep()
        return {"state": state, **self.status()}

    def _payload_rejection(self, key: str, payload: str) -> str | None:
        try:
            reject_source_secrets(key)
            CaptureCommand.model_validate_json(
                json.dumps(decode_json(payload.encode("utf-8")), ensure_ascii=False, allow_nan=False), strict=True,
            )
        except DomainError as error:
            return error.code if error.code == "SOURCE_SECRET_REJECTED" else "SPOOL_PAYLOAD_INVALID"
        except (ValidationError, ValueError, TypeError, UnicodeError):
            return "SPOOL_PAYLOAD_INVALID"
        return None

    def _scrub_legacy_sources(self) -> None:
        for table in ("outbox", "quarantine"):
            cursor = 0
            while rows := self.db.execute(
                f"SELECT rowid,key,digest,payload FROM {table} WHERE rowid>? AND payload<>'' ORDER BY rowid LIMIT ?",
                (cursor, HOUSEKEEPING_ROWS),
            ).fetchall():
                for rowid, key, digest, payload in rows:
                    cursor = rowid
                    code = self._payload_rejection(key, payload)
                    if code is None:
                        continue
                    if table == "outbox":
                        self._quarantine_invalid(key, digest, payload, code)
                    else:
                        with self._transaction():
                            changed = self.db.execute(
                                "UPDATE quarantine SET key=?,digest='',payload='',bytes=0,failure=? "
                                "WHERE key=? AND digest=? AND payload=?",
                                ("quarantine:" + uuid.uuid4().hex, code, key, digest, payload),
                            ).rowcount
                            if changed:
                                self._gap(code)

    def _quarantine_invalid(self, key: str, digest: str, payload: str, code: str) -> int:
        with self._transaction():
            inserted = self.db.execute(
                "INSERT INTO quarantine(key,digest,payload,bytes,failure,created_at,expires_at) "
                "SELECT ?,'','',0,?,created_at,expires_at FROM outbox "
                "WHERE key=? AND digest=? AND payload=? "
                "AND NOT EXISTS (SELECT 1 FROM receipts WHERE key=? AND state='committed')",
                ("quarantine:" + uuid.uuid4().hex, code, key, digest, payload, key),
            ).rowcount
            if inserted:
                self.db.execute("DELETE FROM outbox WHERE key=? AND digest=? AND payload=?", (key, digest, payload))
                self._gap(code)
            else:
                self.db.execute(
                    "DELETE FROM outbox WHERE key=? AND digest=? AND payload=? "
                    "AND EXISTS (SELECT 1 FROM receipts WHERE key=? AND state='committed')",
                    (key, digest, payload, key),
                )
        return inserted

    def flush(self, client: LocalClient, limit: int = 32) -> dict:
        if not 1 <= limit <= 128:
            raise DomainError("SPOOL_LIMIT_INVALID", "Choose a bounded flush limit")
        self._housekeep()
        accepted, quarantined = 0, 0
        failures = []
        keys = self.db.execute(
            "SELECT key FROM outbox WHERE expires_at>? ORDER BY rowid LIMIT ?",
            (time.time(), limit),
        ).fetchall()
        for (key,) in keys:
            row = self.db.execute(
                "SELECT digest,payload FROM outbox WHERE key=? AND expires_at>?",
                (key, time.time()),
            ).fetchone()
            if row is None:
                continue
            digest, payload = row
            try:
                command = CaptureCommand.model_validate_json(
                    json.dumps(decode_json(payload.encode("utf-8")), ensure_ascii=False, allow_nan=False), strict=True,
                )
                if command.binding_id != self.binding_id or command.idempotency_key != key:
                    raise ValueError("Spool source identity mismatch")
                if command.injected or command.speaker == "memory":
                    raise ValueError("Injected source is not evidence")
                if canonical_digest(command.digest_payload()) != digest:
                    raise ValueError("Spool source digest mismatch")
            except DomainError as error:
                code = error.code if error.code == "SOURCE_SECRET_REJECTED" else "SPOOL_PAYLOAD_INVALID"
                moved = self._quarantine_invalid(key, digest, payload, code)
                quarantined += moved
                if moved:
                    failures.append(code)
                continue
            except (ValidationError, ValueError, TypeError, UnicodeError):
                moved = self._quarantine_invalid(key, digest, payload, "SPOOL_PAYLOAD_INVALID")
                quarantined += moved
                if moved:
                    failures.append("SPOOL_PAYLOAD_INVALID")
                continue
            try:
                result = client.request("/api/capture", command.model_dump(mode="json"))
            except DomainError as error:
                failures.append(error.code)
                permanent = (
                    error.code in PERMANENT_CODES and error.code not in TRANSIENT_CODES
                    and error.effect in {EffectState.NOT_STARTED, EffectState.NOT_COMMITTED}
                )
                if not permanent:
                    break
                with self._transaction():
                    inserted = self.db.execute(
                        "INSERT OR IGNORE INTO quarantine(key,digest,payload,bytes,failure,created_at,expires_at) "
                        "SELECT key,digest,payload,bytes,?,created_at,expires_at FROM outbox "
                        "WHERE key=? AND digest=? AND payload=? AND expires_at>? "
                        "AND NOT EXISTS (SELECT 1 FROM receipts WHERE key=? AND state='committed')",
                        (error.code, key, digest, payload, time.time(), key),
                    ).rowcount
                    if inserted:
                        self.db.execute("DELETE FROM outbox WHERE key=? AND digest=? AND payload=?", (key, digest, payload))
                quarantined += inserted
                continue
            try:
                operation, pointer, disposition = self._capture_ack(result)
            except (ValidationError, ValueError, TypeError, UnicodeError):
                failures.append("CAPTURE_RECEIPT_INVALID")
                break
            with self._transaction():
                replacement = self.db.execute(
                    "SELECT 1 FROM (SELECT digest,payload FROM outbox WHERE key=? "
                    "UNION ALL SELECT digest,payload FROM quarantine WHERE key=?) "
                    "WHERE digest<>? OR payload<>? LIMIT 1", (key, key, digest, payload),
                ).fetchone()
                if replacement is None:
                    self._store_receipt(key, digest, "committed", operation, pointer=pointer, disposition=disposition)
                    self.db.execute("DELETE FROM quarantine WHERE key=? AND digest=? AND payload=?", (key, digest, payload))
                    self.db.execute("DELETE FROM outbox WHERE key=? AND digest=? AND payload=?", (key, digest, payload))
            accepted += 1
        self._housekeep()
        return {"committed": accepted, "newly_quarantined": quarantined, "errors": failures, **self.status()}
