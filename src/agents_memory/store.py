from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import re
import unicodedata
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import asyncpg

from .config import MODEL_PURPOSES, Settings, resolve_binding
from .constants import BOUNDED_CONTEXT_MARKER, HOST_CONTEXT_BYTES
from .domain import (
    ActiveRule,
    Admission,
    Binding,
    BindingRelocation,
    CaptureCommand,
    Claim,
    ClaimDraft,
    Consolidation,
    ContextCommand,
    DomainError,
    EffectState,
    EvidenceSpan,
    Extraction,
    FeedbackCommand,
    JobLease,
    Operation,
    Principal,
    Quote,
    RecordCommand,
    ReflectionDraft,
    Relation,
    RevisionRef,
    Role,
    RuleApproval,
    RuleProposal,
    RuleScope,
    Selector,
    Source,
    canonical_digest,
)
from .journal import DeletionJournal
from .migrations import MIGRATION, MIGRATIONS


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _json(value) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _decode(value):
    return json.loads(value) if isinstance(value, str) else value


def _entity(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _denied() -> DomainError:
    return DomainError("SCOPE_DENIED", "The credential does not grant this resource", status=403)


def _missing() -> DomainError:
    return DomainError("NOT_FOUND", "No available resource exists in this project", status=404)


def _connection_arguments(settings: Settings) -> tuple[str, dict]:
    parts = urlsplit(settings.database_dsn)
    query = dict(parse_qsl(parts.query))
    schema = query.pop("schema", None)
    options = {"passfile": "/dev/null"}
    if schema is not None:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
            raise DomainError("CONFIG_INVALID", "The authority schema name is invalid")
        options["server_settings"] = {"search_path": f'"{schema}"'}
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)), options


class Store:
    def __init__(self, settings: Settings, journal: DeletionJournal) -> None:
        if journal.deployment_id != settings.deployment_id or journal.directory.resolve() != settings.journal_dir.resolve():
            raise DomainError("CONFIG_INVALID", "The independent journal must match this deployment")
        state = settings.state_dir.resolve()
        independent = settings.journal_dir.resolve()
        if state.is_relative_to(independent) or independent.is_relative_to(state):
            raise DomainError("CONFIG_INVALID", "The journal cannot be contained in the deployment restore unit")
        self.settings = settings
        self.journal = journal
        self.pool: asyncpg.Pool | None = None
        self._ready = False

    async def open(self) -> None:
        await self._open()

    async def open_restore_recovery(self) -> None:
        if self.settings.migrator_dsn is None or self.settings.database_dsn != self.settings.migrator_dsn:
            raise DomainError("PRIVATE_RECOVERY_REQUIRED", "Restore authentication requires the explicit private operator connection", status=403)
        await self._open(allow_prior_migration=True)

    async def _open(self, allow_prior_migration: bool = False) -> None:
        if self.pool is not None:
            return
        dsn, options = _connection_arguments(self.settings)
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=8, command_timeout=30, **options)
        try:
            async with pool.acquire() as connection:
                version = int(await connection.fetchval("SHOW server_version_num"))
                vector = await connection.fetchval("SELECT extversion FROM pg_extension WHERE extname='vector'")
                if not 180000 <= version < 190000 or vector is None or tuple(map(int, vector.split('.'))) < (0, 8, 7):
                    raise DomainError("DATABASE_VERSION_UNSUPPORTED", "PostgreSQL 18 and pgvector >=0.8.7 are required", status=503)
                migration = await connection.fetchval("SELECT version_num FROM alembic_version")
                if migration != MIGRATION and not (allow_prior_migration and migration in MIGRATIONS):
                    raise DomainError("MIGRATION_REQUIRED", "Run the explicit operator migrator", status=503)
        except asyncpg.UndefinedTableError:
            await pool.close()
            raise DomainError("MIGRATION_REQUIRED", "Run the explicit operator migrator", status=503) from None
        except BaseException:
            await pool.close()
            raise
        self.pool = pool
        self._ready = False

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None
        self._ready = False

    @asynccontextmanager
    async def _tx(self, barrier: bool = True) -> AsyncIterator[tuple[asyncpg.Connection, asyncpg.Record]]:
        if self.pool is None:
            raise DomainError("STORE_CLOSED", "The authority connection is not open", status=503)
        journal = await asyncio.to_thread(self.journal.verify) if barrier else None
        try:
            async with self.pool.acquire() as connection:
                async with connection.transaction():
                    clock = await connection.fetchrow("SELECT * FROM am_clock WHERE singleton FOR UPDATE")
                    if clock is None:
                        raise DomainError("MIGRATION_REQUIRED", "The authority clock is missing", status=503)
                    if clock["deployment_id"] is not None and (
                        clock["deployment_id"] != self.settings.deployment_id or clock["realm"] != self.settings.realm
                    ):
                        raise _denied()
                    if barrier and (not self._ready or clock["journal_head"] != journal["head"]):
                        raise DomainError("DELETION_BARRIER", "Reconcile the independent deletion journal before use", status=503)
                    yield connection, clock
        except (asyncpg.PostgresConnectionError, asyncpg.InterfaceError, OSError, TimeoutError):
            from .domain import EffectState
            raise DomainError("DATABASE_UNAVAILABLE", "The authority connection failed; reconcile the durable receipt before retry", status=503, effect=EffectState.UNKNOWN) from None

    async def _tick(self, connection) -> int:
        return await connection.fetchval("UPDATE am_clock SET epoch=epoch+1 WHERE singleton RETURNING epoch")

    def _token_hash(self, token: str) -> str:
        if len(token.encode()) < 32 or len(token.encode()) > 4096:
            raise DomainError("TOKEN_INVALID", "Credentials require 32 to 4096 bytes", status=401)
        return hashlib.sha256((self.settings.deployment_id + "\0" + token).encode()).hexdigest()

    async def _credential(self, connection, credential_id: str) -> Principal:
        row = await connection.fetchrow("SELECT * FROM am_credentials WHERE id=$1 AND active AND realm=$2", credential_id, self.settings.realm)
        if row is None:
            raise DomainError("AUTH_DENIED", "The current credential is unavailable", status=401)
        bindings = await connection.fetch("SELECT binding_id FROM am_grants WHERE credential_id=$1 ORDER BY binding_id", credential_id)
        return Principal(id=row["principal_id"], credential_id=row["id"], realm=row["realm"], role=row["role"], generation=row["generation"], bindings=tuple(item["binding_id"] for item in bindings))

    async def _actor(self, connection, actor: Principal, binding_id: str | None = None, roles: tuple[Role, ...] | None = None) -> Principal:
        current = await self._credential(connection, actor.credential_id)
        if (current.id, current.realm, current.role, current.generation) != (actor.id, actor.realm, actor.role, actor.generation):
            raise _denied()
        if roles is not None and current.role not in roles:
            raise _denied()
        if binding_id is not None:
            if binding_id not in current.bindings:
                raise _denied()
            exists = await connection.fetchval("SELECT 1 FROM am_bindings WHERE id=$1 AND realm=$2", binding_id, current.realm)
            if not exists:
                raise _denied()
        return current

    @classmethod
    async def preflight_initialization(cls, settings: Settings, operator_token: str, owner_id: str, *, resume: bool) -> Principal | None:
        store = cls(settings, DeletionJournal(settings.journal_dir, settings.deployment_id))
        token_hash = store._token_hash(operator_token)
        dsn, options = _connection_arguments(settings)
        try:
            connection = await asyncpg.connect(dsn, timeout=30, command_timeout=30, **options)
            try:
                async with connection.transaction(readonly=True):
                    tables = await connection.fetch("""SELECT c.relname FROM pg_class c
                        JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=current_schema()
                        AND c.relkind IN ('r','p','v','m') AND NOT EXISTS(
                            SELECT 1 FROM pg_depend d WHERE d.classid='pg_class'::regclass AND d.objid=c.oid AND d.deptype='e')""")
                    names = {row["relname"] for row in tables}
                    if not names:
                        return None
                    if "am_clock" not in names or "am_credentials" not in names:
                        raise DomainError("INITIALIZATION_SCOPE_DENIED", "The requested authority schema is not empty or a matching initialization", status=403)
                    expected = {"alembic_version", "am_clock", "am_credentials", "am_bindings", "am_grants",
                        "am_receipts", "am_operations", "am_sources", "am_floors", "am_claims", "am_claim_sources",
                        "am_spans", "am_entities", "am_relations", "am_relation_sources", "am_relation_claims",
                        "am_reflections", "am_reflection_sources", "am_reflection_claims", "am_proposals",
                        "am_proposal_sources", "am_rules", "am_rule_targets", "am_feedback", "am_routes",
                        "am_jobs", "am_admissions", "am_origin_reservations"}
                    if names - expected:
                        raise DomainError("INITIALIZATION_SCOPE_DENIED", "The authority schema contains unrelated state", status=403)
                    clock = await connection.fetchrow("SELECT * FROM am_clock WHERE singleton")
                    if clock is None:
                        raise DomainError("INITIALIZATION_SCOPE_DENIED", "The authority clock is unavailable", status=403)
                    if clock["deployment_id"] is None and clock["realm"] is None and clock["journal_head"] is None:
                        for name in sorted(names - {"am_clock", "alembic_version"}):
                            if await connection.fetchval(f'SELECT EXISTS(SELECT 1 FROM "{name}")'):
                                raise DomainError("INITIALIZATION_SCOPE_DENIED", "The authority schema contains existing state", status=403)
                        return None
                    return await store._resumed_bootstrap(connection, clock, token_hash, owner_id, resume)
            finally:
                await connection.close()
        except (asyncpg.PostgresConnectionError, asyncpg.InterfaceError, OSError, TimeoutError):
            raise DomainError("DATABASE_UNAVAILABLE", "Initialization authority preflight is unavailable", status=503) from None

    async def _resumed_bootstrap(self, connection, clock, token_hash: str, owner_id: str, resume: bool) -> Principal:
        if not resume or clock["deployment_id"] != self.settings.deployment_id or clock["realm"] != self.settings.realm:
            raise DomainError("INITIALIZATION_SCOPE_DENIED", "Only explicit matching initialization recovery may reuse authority", status=403)
        credential_id = await connection.fetchval("""SELECT id FROM am_credentials WHERE token_hash=$1
            AND active AND role='operator' AND principal_id=$2 AND realm=$3""", token_hash, owner_id, self.settings.realm)
        if credential_id is None:
            raise DomainError("INITIALIZATION_SCOPE_DENIED", "The initialization credential and owner do not match", status=403)
        return await self._credential(connection, credential_id)

    async def bootstrap(self, operator_token: str, owner_id: str, *, resume: bool = False) -> Principal:
        token_hash = self._token_hash(operator_token)
        credential_id = _id("credential")
        actor = Principal(id=owner_id, credential_id=credential_id, realm=self.settings.realm, role=Role.OPERATOR, generation=1, bindings=())
        async with self._tx(barrier=False) as (connection, clock):
            if clock["deployment_id"] is not None or await connection.fetchval("SELECT EXISTS(SELECT 1 FROM am_credentials)"):
                actor = await self._resumed_bootstrap(connection, clock, token_hash, owner_id, resume)
                journal = await asyncio.to_thread(self.journal.verify)
                await self._reconcile_locked(connection, journal, await asyncio.to_thread(self.journal.entries))
                self._ready = True
                return actor
            if self.journal.directory.exists() and (self.journal.directory / "key").exists():
                journal = await asyncio.to_thread(self.journal.verify)
            else:
                journal = await asyncio.to_thread(self.journal.initialize)
            await connection.execute("INSERT INTO am_credentials(id,principal_id,realm,role,token_hash) VALUES($1,$2,$3,'operator',$4)", credential_id, owner_id, self.settings.realm, token_hash)
            await connection.execute("UPDATE am_clock SET deployment_id=$1,realm=$2,journal_head=$3,epoch=epoch+1 WHERE singleton", self.settings.deployment_id, self.settings.realm, journal["head"])
            await self._apply_floors(connection, await asyncio.to_thread(self.journal.entries))
        self._ready = True
        return actor

    async def authenticate(self, token: str, roles: tuple[Role, ...] | None = None) -> Principal:
        token_hash = self._token_hash(token)
        async with self._tx(barrier=False) as (connection, _):
            credential = await connection.fetchval("SELECT id FROM am_credentials WHERE token_hash=$1 AND active AND realm=$2", token_hash, self.settings.realm)
            if credential is None:
                raise DomainError("AUTH_DENIED", "The current credential is unavailable", status=401)
            actor = await self._credential(connection, credential)
            if roles is not None and actor.role not in roles:
                raise _denied()
            return actor

    async def _receipt(self, connection, actor: Principal, binding_id: str, kind: str, key: str, digest: str):
        if not key:
            raise DomainError("IDEMPOTENCY_KEY_REQUIRED", "A nonempty business request key is required")
        row = await connection.fetchrow("SELECT * FROM am_receipts WHERE principal_id=$1 AND binding_id=$2 AND kind=$3 AND request_key=$4", actor.id, binding_id, kind, key)
        if row is not None and row["digest"] != digest:
            raise DomainError("IDEMPOTENCY_CONFLICT", "The request key is already bound to different arguments")
        return row

    async def _save_receipt(self, connection, actor, binding_id, kind, key, digest, target_id=None, result=None) -> None:
        await connection.execute("INSERT INTO am_receipts(principal_id,binding_id,kind,request_key,digest,target_id,result) VALUES($1,$2,$3,$4,$5,$6,$7::jsonb)", actor.id, binding_id, kind, key, digest, target_id, _json(result or {}))

    def _binding(self, row) -> Binding:
        return Binding.model_validate(dict(row))

    async def register_binding(self, actor: Principal, label: str, locator: str | None, key: str) -> Binding:
        value = Binding(id=_id("binding"), realm=self.settings.realm, owner_id=actor.id, label=label, locator=locator, revision=1)
        digest = canonical_digest({"label": label, "locator": locator})
        async with self._tx() as (connection, _):
            current = await self._actor(connection, actor, roles=(Role.OPERATOR,))
            receipt = await self._receipt(connection, current, "realm", "register_binding", key, digest)
            if receipt:
                row = await connection.fetchrow("SELECT * FROM am_bindings WHERE id=$1 AND owner_id=$2 AND realm=$3", receipt["target_id"], current.id, current.realm)
                if row is None:
                    raise _missing()
                return self._binding(row)
            await connection.execute("INSERT INTO am_bindings(id,realm,owner_id,label,locator) VALUES($1,$2,$3,$4,$5)", value.id, value.realm, value.owner_id, value.label, value.locator)
            await connection.execute("INSERT INTO am_grants(credential_id,binding_id) VALUES($1,$2)", current.credential_id, value.id)
            await connection.execute("UPDATE am_clock SET roster_revision=roster_revision+1 WHERE singleton")
            await self._tick(connection)
            await self._save_receipt(connection, current, "realm", "register_binding", key, digest, value.id)
            return value

    async def relocate_binding(self, actor: Principal, command: BindingRelocation) -> Binding:
        digest = canonical_digest(command.model_dump(mode="json"))
        async with self._tx() as (connection, _):
            current = await self._actor(connection, actor, command.binding_id, roles=(Role.OPERATOR,))
            row = await connection.fetchrow("SELECT * FROM am_bindings WHERE id=$1 AND realm=$2 AND owner_id=$3", command.binding_id, current.realm, current.id)
            if row is None:
                raise _denied()
            receipt = await self._receipt(connection, current, command.binding_id, "relocate_binding", command.idempotency_key, digest)
            if receipt:
                result = json.loads(receipt["result"]) if isinstance(receipt["result"], str) else receipt["result"]
                committed = Binding.model_validate(result)
                if row["locator"] != committed.locator or row["revision"] != committed.revision:
                    raise DomainError("BINDING_RELOCATION_CONFLICT", "The committed relocation was superseded", effect=EffectState.COMMITTED)
                return committed
            if row["revision"] != command.expected_revision or row["locator"] != command.expected_locator:
                raise DomainError("BINDING_RELOCATION_CONFLICT", "The project locator or revision changed")
            updated = await connection.fetchrow("UPDATE am_bindings SET locator=$2,revision=revision+1 WHERE id=$1 RETURNING *", command.binding_id, command.locator)
            value = self._binding(updated)
            await self._tick(connection)
            await self._save_receipt(connection, current, command.binding_id, "relocate_binding", command.idempotency_key, digest, value.id, value.model_dump(mode="json"))
            return value

    async def list_bindings(self, actor: Principal) -> list[Binding]:
        async with self._tx() as (connection, _):
            current = await self._actor(connection, actor)
            rows = await connection.fetch("SELECT b.* FROM am_bindings b JOIN am_grants g ON g.binding_id=b.id WHERE g.credential_id=$1 AND b.realm=$2 ORDER BY b.id", current.credential_id, current.realm)
            return [self._binding(row) for row in rows]

    async def target_set_revision(self, actor: Principal) -> int:
        async with self._tx() as (connection, clock):
            await self._actor(connection, actor)
            return clock["roster_revision"]

    async def issue_token(self, actor: Principal, role: Role, bindings: tuple[str, ...], token: str) -> Principal:
        digest = self._token_hash(token)
        if len(set(bindings)) != len(bindings):
            raise DomainError("SCOPE_INVALID", "Project grants must be distinct")
        if self.settings.mode == "company" and role == Role.APPROVER:
            raise DomainError("SHARED_APPROVAL_UNAVAILABLE", "Managed approver credentials require an independent identity boundary", status=503)
        async with self._tx() as (connection, _):
            current = await self._actor(connection, actor, roles=(Role.OPERATOR,))
            for binding_id in bindings:
                await self._actor(connection, current, binding_id)
            if await connection.fetchval("SELECT EXISTS(SELECT 1 FROM am_credentials WHERE token_hash=$1)", digest):
                raise DomainError("TOKEN_CONFLICT", "This credential token has already been issued")
            credential_id = _id("credential")
            await connection.execute("INSERT INTO am_credentials(id,principal_id,realm,role,token_hash) VALUES($1,$2,$3,$4,$5)", credential_id, current.id, current.realm, role.value, digest)
            await connection.executemany("INSERT INTO am_grants(credential_id,binding_id) VALUES($1,$2)", [(credential_id, binding_id) for binding_id in bindings])
            await self._tick(connection)
            return await self._credential(connection, credential_id)

    async def _credential_revocation_impact(self, connection, actor: Principal, credential_id: str) -> dict:
        target = await connection.fetchrow("SELECT * FROM am_credentials WHERE id=$1 AND realm=$2 AND principal_id=$3", credential_id, actor.realm, actor.id)
        if target is None:
            raise _missing()
        rows = await connection.fetch("""SELECT r.id,p.required FROM am_rules r JOIN am_proposals p ON p.id=r.proposal_id
            WHERE r.approver_credential_id=$1 AND r.state='active' ORDER BY r.id""", credential_id)
        return {"credential_id": credential_id, "revoked": not target["active"],
            "affected_rule_ids": [row["id"] for row in rows],
            "required_rule_ids": [row["id"] for row in rows if row["required"]]}

    async def credential_revocation_impact(self, actor: Principal, credential_id: str) -> dict:
        async with self._tx() as (connection, clock):
            current = await self._actor(connection, actor, roles=(Role.OPERATOR,))
            return {**await self._credential_revocation_impact(connection, current, credential_id), "epoch": clock["epoch"]}

    async def revoke_token(self, actor: Principal, credential_id: str, *, acknowledge_required: bool = False) -> dict:
        async with self._tx() as (connection, clock):
            current = await self._actor(connection, actor, roles=(Role.OPERATOR,))
            impact = await self._credential_revocation_impact(connection, current, credential_id)
            if impact["required_rule_ids"] and not acknowledge_required:
                raise DomainError("REQUIRED_RULE_REVOCATION_ACK_REQUIRED", "Revocation invalidates required rules; inspect credential_revocation_impact and explicitly acknowledge this impact")
            epoch = clock["epoch"]
            if not impact["revoked"]:
                await connection.execute("UPDATE am_credentials SET active=false,generation=generation+1 WHERE id=$1", credential_id)
                await connection.execute("UPDATE am_rules SET state='retracted',revision=revision+1 WHERE approver_credential_id=$1 AND state='active'", credential_id)
                epoch = await self._tick(connection)
            return {**impact, "revoked": True, "epoch": epoch}

    def _operation(self, row) -> Operation:
        return Operation(id=row["id"], binding_id=row["binding_id"], kind=row["kind"], state=row["state"], source_id=row["source_id"], artifact_id=row["artifact_id"], successor_operation_id=row["successor_operation_id"], error_code=row["error_code"], epoch=row["epoch"])

    async def _operation_row(self, connection, binding_id: str, operation_id: str):
        row = await connection.fetchrow("SELECT * FROM am_operations WHERE id=$1 AND binding_id=$2", operation_id, binding_id)
        if row is None:
            raise _missing()
        return row

    async def _new_operation(self, connection, actor, binding_id, kind, state="accepted", error=None):
        operation_id = _id("operation")
        epoch = await self._tick(connection)
        return await connection.fetchrow("INSERT INTO am_operations(id,binding_id,credential_id,kind,state,error_code,epoch) VALUES($1,$2,$3,$4,$5,$6,$7) RETURNING *", operation_id, binding_id, actor.credential_id, kind, state, error, epoch)

    async def _queue_capacity(self, connection) -> None:
        count = await connection.fetchval("SELECT count(*) FROM am_jobs WHERE state IN ('pending','leased','blocked','failed')")
        if count >= self.settings.queue_limit:
            raise DomainError("QUEUE_FULL", "The durable backlog and recovery queue are full", status=429)

    async def _enqueue(self, connection, actor, operation_id, binding_id, kind, source_ids, claim_ids=(), query_source_id=None, snapshot=None) -> str:
        await self._queue_capacity(connection)
        job_id = _id("job")
        await connection.execute("INSERT INTO am_jobs(id,binding_id,operation_id,credential_id,credential_generation,kind,source_ids,claim_ids,query_source_id,snapshot) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)", job_id, binding_id, operation_id, actor.credential_id, actor.generation, kind, list(source_ids), list(claim_ids), query_source_id, snapshot)
        return job_id

    async def _insert_source(self, connection, actor, command: CaptureCommand, operation_id: str) -> str:
        source_id = _id("source")
        source_token = await asyncio.to_thread(self.journal.source_token, source_id)
        origin_token = await asyncio.to_thread(self.journal.origin_token, command.binding_id, command.origin_key)
        value = command.model_dump(mode="json", exclude={"idempotency_key"})
        await connection.execute("INSERT INTO am_sources(id,binding_id,realm,body,speaker,kind,origin_key,origin_token,source_token,origin_digest,root_run_id,agent_path,snapshot,event_time,operation_id) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)", source_id, command.binding_id, actor.realm, command.body, command.speaker, command.kind, command.origin_key, origin_token, source_token, canonical_digest(value), command.root_run_id, command.agent_path, command.snapshot, command.event_time, operation_id)
        return source_id

    async def _capture(self, connection, actor, command: CaptureCommand, kind="capture", receipt_payload=None) -> Operation:
        digest = canonical_digest(receipt_payload or command)
        receipt = await self._receipt(connection, actor, command.binding_id, kind, command.idempotency_key, digest)
        if receipt:
            return self._operation(await self._operation_row(connection, command.binding_id, receipt["target_id"]))
        if len(command.body.encode()) > self.settings.max_capture_bytes:
            raise DomainError("BODY_TOO_LARGE", "The source exceeds the configured capture bound", status=413)
        ignored = command.injected or command.speaker == "memory" or "<agents-memory-context" in command.body or "[agents-memory:injected]" in command.body or BOUNDED_CONTEXT_MARKER in command.body
        if ignored:
            row = await self._new_operation(connection, actor, command.binding_id, kind, "semantic_ready", "CAPTURE_IGNORED")
        else:
            origin_token = await asyncio.to_thread(self.journal.origin_token, command.binding_id, command.origin_key)
            original = await connection.fetchrow("SELECT * FROM am_sources WHERE origin_token=$1 AND binding_id=$2", origin_token, command.binding_id)
            origin_digest = canonical_digest(command.model_dump(mode="json", exclude={"idempotency_key"}))
            reservation = await connection.fetchrow("SELECT * FROM am_origin_reservations WHERE origin_token=$1 AND binding_id=$2", origin_token, command.binding_id)
            if reservation:
                if reservation["origin_digest"] != origin_digest:
                    raise DomainError("ORIGIN_CONFLICT", "The origin event is already bound to different evidence")
                if kind != "correct" or (reservation["principal_id"], reservation["request_key"], reservation["intent_digest"]) != (actor.id, command.idempotency_key, digest):
                    raise DomainError("ORIGIN_RESERVED", "This origin belongs to a pending correction; retry its original request key")
            if kind == "correct" and (
                (original is not None and (original["state"] != "active" or original["body"] is None))
                or await connection.fetchval("SELECT EXISTS(SELECT 1 FROM am_floors WHERE kind='origin' AND token=$1)", origin_token)
            ):
                raise DomainError("CORRECTION_ORIGIN_CONFLICT", "The reserved replacement origin is no longer eligible")
            if original:
                if original["origin_digest"] != origin_digest:
                    raise DomainError("ORIGIN_CONFLICT", "The origin event is already bound to different evidence")
                row = await self._operation_row(connection, command.binding_id, original["operation_id"])
            elif await connection.fetchval("SELECT EXISTS(SELECT 1 FROM am_floors WHERE kind='origin' AND token=$1)", origin_token):
                row = await self._new_operation(connection, actor, command.binding_id, kind, "retracted", "ORIGIN_RETRACTED")
            else:
                await self._queue_capacity(connection)
                row = await self._new_operation(connection, actor, command.binding_id, kind)
                source_id = await self._insert_source(connection, actor, command, row["id"])
                await connection.execute("UPDATE am_operations SET source_id=$2 WHERE id=$1", row["id"], source_id)
                await self._enqueue(connection, actor, row["id"], command.binding_id, "extract", (source_id,), snapshot=command.snapshot)
                row = await self._operation_row(connection, command.binding_id, row["id"])
        await self._save_receipt(connection, actor, command.binding_id, kind, command.idempotency_key, digest, row["id"])
        if kind == "correct":
            await connection.execute("DELETE FROM am_origin_reservations WHERE origin_token=$1 AND principal_id=$2 AND request_key=$3 AND intent_digest=$4",
                await asyncio.to_thread(self.journal.origin_token, command.binding_id, command.origin_key), actor.id, command.idempotency_key, digest)
            await connection.execute("""UPDATE am_receipts SET result=$5::jsonb WHERE principal_id=$1 AND binding_id=$2
                AND kind='correct_intent' AND request_key=$3 AND digest=$4""", actor.id, command.binding_id,
                command.idempotency_key, digest, _json({"state": "completed", "logical_retraction": "committed", "replacement_capture": "committed", "operation_id": row["id"]}))
        return self._operation(row)

    async def capture(self, actor: Principal, command: CaptureCommand) -> Operation:
        async with self._tx() as (connection, _):
            current = await self._actor(connection, actor, command.binding_id, (Role.PRODUCER, Role.OPERATOR))
            return await self._capture(connection, current, command)

    async def _derivation_sources(self, connection, source_ids: tuple[str, ...]) -> list[str]:
        refs = tuple(("extract_source", source_id) for source_id in source_ids)
        tokens = await asyncio.to_thread(self.journal.artifact_tokens, refs)
        floors = await connection.fetch("SELECT token FROM am_floors WHERE kind='artifact' AND token=ANY($1::text[])", list(tokens.values()))
        withdrawn = {row["token"] for row in floors}
        return [source_id for (_, source_id), token in tokens.items() if token in withdrawn]

    async def _derivation_allowed(self, connection, source_ids: tuple[str, ...]) -> None:
        if await self._derivation_sources(connection, source_ids):
            raise DomainError("DERIVATION_RETRACTED", "This immutable source cannot regenerate withdrawn claims; provide genuinely revised evidence")

    async def reprocess(self, actor: Principal, binding_id: str, source_id: str, key: str) -> Operation:
        digest = canonical_digest({"source_id": source_id})
        async with self._tx() as (connection, _):
            current = await self._actor(connection, actor, binding_id, (Role.OPERATOR,))
            receipt = await self._receipt(connection, current, binding_id, "reprocess", key, digest)
            if receipt:
                return self._operation(await self._operation_row(connection, binding_id, receipt["target_id"]))
            source = await self._source_row(connection, binding_id, source_id)
            await self._derivation_allowed(connection, (source_id,))
            await self._route(connection, self.settings.models.revision(), "extraction")
            if await connection.fetchval("""SELECT EXISTS(SELECT 1 FROM am_jobs j JOIN am_operations o ON o.id=j.operation_id
                WHERE o.source_id=$1 AND j.kind IN ('extract','consolidate') AND j.state IN ('pending','leased'))""", source_id):
                raise DomainError("REPROCESS_BUSY", "This source already has a live durable processing owner")
            retired = await connection.fetch("""UPDATE am_jobs j SET state='superseded',error_code='REPROCESS_REPLACED',
                generation=generation+1,lease_token=NULL,deadline=NULL WHERE state IN ('blocked','failed')
                AND kind IN ('extract','consolidate') AND EXISTS(SELECT 1 FROM am_operations o
                    WHERE o.id=j.operation_id AND o.source_id=$1) RETURNING operation_id""", source_id)
            await self._queue_capacity(connection)
            operation = await self._new_operation(connection, current, binding_id, "reprocess")
            if retired:
                await connection.execute("UPDATE am_operations SET successor_operation_id=$2 WHERE id=ANY($1::text[]) AND state IN ('accepted','pending','blocked','failed')", [row["operation_id"] for row in retired], operation["id"])
            await connection.execute("UPDATE am_operations SET source_id=$2 WHERE id=$1", operation["id"], source_id)
            await self._enqueue(connection, current, operation["id"], binding_id, "extract", (source_id,), snapshot=source["snapshot"])
            await self._save_receipt(connection, current, binding_id, "reprocess", key, digest, operation["id"])
            return self._operation(await self._operation_row(connection, binding_id, operation["id"]))

    async def record(self, actor: Principal, command: RecordCommand) -> Operation:
        binding_id = resolve_binding(actor, command.binding_id)
        async with self._tx() as (connection, clock):
            current = await self._actor(connection, actor, binding_id, (Role.AGENT, Role.OPERATOR))
            digest = canonical_digest(command.model_copy(update={"binding_id": binding_id}))
            receipt = await self._receipt(connection, current, binding_id, "record", command.idempotency_key, digest)
            if receipt:
                return self._operation(await self._operation_row(connection, binding_id, receipt["target_id"]))
            if command.kind == "note":
                origin = canonical_digest({"principal_id": current.id, "request_key": command.idempotency_key})
                capture = CaptureCommand(binding_id=binding_id, idempotency_key=command.idempotency_key, origin_key=f"agent-note:{origin}", body=command.body, speaker="agent_note")
                return await self._capture(connection, current, capture, kind="record", receipt_payload=command.model_copy(update={"binding_id": binding_id}))
            proposal = RuleProposal(binding_id=binding_id, idempotency_key=command.idempotency_key, body=command.body)
            row = await self._new_operation(connection, current, binding_id, "record", "semantic_ready")
            info = await self._create_proposal(connection, current, proposal, clock, row["id"])
            await connection.execute("UPDATE am_operations SET artifact_id=$2,source_id=$3 WHERE id=$1", row["id"], info["proposal_id"], info["source_id"])
            await self._save_receipt(connection, current, binding_id, "record", command.idempotency_key, digest, row["id"])
            return self._operation(await self._operation_row(connection, binding_id, row["id"]))

    async def feedback(self, actor: Principal, command: FeedbackCommand) -> Operation:
        binding_id = resolve_binding(actor, command.binding_id)
        async with self._tx() as (connection, _):
            current = await self._actor(connection, actor, binding_id, (Role.AGENT, Role.OPERATOR))
            digest = canonical_digest(command.model_copy(update={"binding_id": binding_id}))
            receipt = await self._receipt(connection, current, binding_id, "feedback", command.idempotency_key, digest)
            if receipt:
                return self._operation(await self._operation_row(connection, binding_id, receipt["target_id"]))
            await self._ref_metadata(connection, binding_id, command.target_ref)
            operation = await self._new_operation(connection, current, binding_id, "feedback", "semantic_ready")
            source_id = None
            if command.body is not None:
                source_id = await self._insert_source(connection, current, CaptureCommand(binding_id=binding_id, idempotency_key=command.idempotency_key, origin_key=f"feedback:{operation['id']}", body=command.body, speaker="agent_note"), operation["id"])
            artifact_id = _id("feedback")
            await connection.execute("INSERT INTO am_feedback(id,binding_id,target_ref,kind,source_id) VALUES($1,$2,$3,$4,$5)", artifact_id, binding_id, command.target_ref, command.kind, source_id)
            await connection.execute("UPDATE am_operations SET source_id=$2,artifact_id=$3 WHERE id=$1", operation["id"], source_id, artifact_id)
            await self._save_receipt(connection, current, binding_id, "feedback", command.idempotency_key, digest, operation["id"])
            return self._operation(await self._operation_row(connection, binding_id, operation["id"]))

    async def operation(self, actor: Principal, binding_id: str, operation_id: str) -> Operation:
        async with self._tx() as (connection, _):
            await self._actor(connection, actor, binding_id)
            return self._operation(await self._operation_row(connection, binding_id, operation_id))

    def _source(self, row) -> Source:
        return Source(id=row["id"], binding_id=row["binding_id"], realm=row["realm"], revision=row["revision"], body=row["body"], speaker=row["speaker"], origin_key=row["origin_key"], root_run_id=row["root_run_id"], snapshot=row["snapshot"], event_time=row["event_time"], recorded_at=row["recorded_at"], state=row["state"])

    async def _source_row(self, connection, binding_id: str, source_id: str, snapshot=None, enforce_snapshot=False):
        row = await connection.fetchrow("SELECT * FROM am_sources WHERE id=$1 AND binding_id=$2 AND realm=$3 AND state='active' AND body IS NOT NULL", source_id, binding_id, self.settings.realm)
        if row is None:
            raise DomainError("SOURCE_INELIGIBLE", "The source is not currently eligible")
        if enforce_snapshot and row["snapshot"] is not None and row["snapshot"] != snapshot:
            raise DomainError("SNAPSHOT_INELIGIBLE", "The source belongs to a different snapshot")
        return row

    async def source(self, actor: Principal, binding_id: str, source_id: str) -> Source:
        async with self._tx() as (connection, _):
            await self._actor(connection, actor, binding_id)
            return self._source(await self._source_row(connection, binding_id, source_id))

    async def _claim_row(self, connection, binding_id: str, claim_id: str, snapshot: str | None, enforce_time: bool = True):
        row = await connection.fetchrow("""SELECT c.* FROM am_claims c WHERE c.id=$1 AND c.binding_id=$2 AND c.state='active' AND c.draft IS NOT NULL
          AND (c.snapshot IS NULL OR c.snapshot=$3)
          AND (c.superseded_by IS NULL OR EXISTS(SELECT 1 FROM am_claims canonical
            WHERE canonical.id=c.superseded_by AND canonical.state='active' AND canonical.draft IS NOT NULL))
          AND (NOT $5::boolean OR ((c.valid_from IS NULL OR c.valid_from<=clock_timestamp())
            AND (c.valid_until IS NULL OR c.valid_until>clock_timestamp())))
          AND EXISTS(SELECT 1 FROM am_claim_sources d WHERE d.claim_id=c.id)
          AND NOT EXISTS(SELECT 1 FROM am_claim_sources d JOIN am_sources s ON s.id=d.source_id
            WHERE d.claim_id=c.id AND (s.state<>'active' OR s.body IS NULL OR s.revision<>d.source_revision OR s.binding_id<>c.binding_id OR s.realm<>$4 OR (s.snapshot IS NOT NULL AND s.snapshot IS DISTINCT FROM $3)))""", claim_id, binding_id, snapshot, self.settings.realm, enforce_time)
        if row is None:
            raise DomainError("CLAIM_INELIGIBLE", "The claim is not currently eligible")
        return row

    async def _claim(self, connection, row) -> Claim:
        spans = await connection.fetch("""SELECT span.*,source.speaker AS source_speaker,
            source.event_time AS source_event_time,source.recorded_at AS source_recorded_at FROM am_spans span
            JOIN am_sources source ON source.id=span.source_id WHERE span.claim_id=$1 ORDER BY span.ordinal""", row["id"])
        inputs = await connection.fetch("SELECT source_id FROM am_claim_sources WHERE claim_id=$1 ORDER BY source_id", row["id"])
        evidence = tuple(EvidenceSpan(source_id=span["source_id"], source_revision=span["source_revision"], source_speaker=span["source_speaker"], source_event_time=span["source_event_time"], source_recorded_at=span["source_recorded_at"], byte_start=span["byte_start"], byte_end=span["byte_end"], quote=span["quote"]) for span in spans)
        draft = dict(_decode(row["draft"]))
        draft["evidence"] = [Quote(source_id=span.source_id, quote=span.quote, byte_start=span.byte_start) for span in evidence]
        return Claim(id=row["id"], binding_id=row["binding_id"], draft=ClaimDraft.model_validate(draft), evidence=evidence, input_source_ids=tuple(item["source_id"] for item in inputs), snapshot=row["snapshot"], created_at=row["created_at"], state=row["state"])

    async def claim(self, actor: Principal, binding_id: str, claim_id: str, snapshot: str | None = None) -> Claim:
        async with self._tx() as (connection, _):
            await self._actor(connection, actor, binding_id)
            return await self._claim(connection, await self._claim_row(connection, binding_id, claim_id, snapshot))

    async def _ref_metadata(self, connection, binding_id: str, ref: str) -> tuple[str, asyncpg.Record]:
        for kind, table in (
            ("operation", "am_operations"), ("source", "am_sources"),
            ("claim", "am_claims"), ("proposal", "am_proposals"),
            ("reflection", "am_reflections"), ("feedback", "am_feedback"),
            ("relation", "am_relations"),
        ):
            row = await connection.fetchrow(f"SELECT * FROM {table} WHERE id=$1 AND binding_id=$2", ref, binding_id)
            if row is not None:
                return kind, row
        row = await connection.fetchrow("""SELECT r.* FROM am_rules r JOIN am_rule_targets t ON t.rule_id=r.id
            WHERE r.id=$1 AND t.binding_id=$2""", ref, binding_id)
        if row is not None:
            return "rule", row
        raise _missing()

    async def _dependencies(self, connection, table: str, column: str, ref: str, snapshot=None, enforce_snapshot=False) -> list:
        rows = await connection.fetch(f"""SELECT s.*, d.source_revision AS expected_revision
            FROM {table} d JOIN am_sources s ON s.id=d.source_id WHERE d.{column}=$1 ORDER BY s.id""", ref)
        if any(
            row["state"] != "active" or row["body"] is None or row["revision"] != row["expected_revision"]
            or row["realm"] != self.settings.realm
            or (enforce_snapshot and row["snapshot"] is not None and row["snapshot"] != snapshot)
            for row in rows
        ):
            raise DomainError("INPUT_INELIGIBLE", "An actual input is no longer eligible")
        return rows

    async def inspect(self, actor: Principal, binding_id: str, ref: str, snapshot: str | None = None) -> dict:
        async with self._tx() as (connection, clock):
            current = await self._actor(connection, actor, binding_id)
            kind, row = await self._ref_metadata(connection, binding_id, ref)
            result = {"id": ref, "kind": kind, "epoch": clock["epoch"], "state": row.get("state", "candidate")}
            pending = await connection.fetch("""SELECT request_key,result FROM am_receipts WHERE principal_id=$1
                AND binding_id=$2 AND kind='correct_intent' AND target_id=$3 AND result->>'state'<>'completed'
                ORDER BY request_key LIMIT 9""", current.id, binding_id, ref)
            if pending:
                result["pending_corrections"] = [{"request_key": item["request_key"], **dict(_decode(item["result"]))} for item in pending[:8]]
                result["pending_corrections_partial"] = len(pending) > 8
            if kind == "operation":
                result.update(self._operation(row).model_dump(mode="json"))
                jobs = await connection.fetch("SELECT id,kind,state,error_code,attempts,generation FROM am_jobs WHERE operation_id=$1 AND binding_id=$2 ORDER BY created_at,id LIMIT 8", ref, binding_id)
                result["jobs"] = [dict(job) for job in jobs]
                return result
            if kind == "source":
                result.update(revision=row["revision"], snapshot=row["snapshot"], speaker=row["speaker"])
                if row["state"] == "active" and row["body"] is not None:
                    if row["snapshot"] is not None and row["snapshot"] != snapshot:
                        raise DomainError("SNAPSHOT_INELIGIBLE", "The source belongs to a different snapshot")
                    encoded = row["body"].encode()
                    result.update(body=encoded[:4096].decode(errors="ignore"), partial=len(encoded) > 4096)
                return result
            if row.get("state") == "retracted":
                return result
            if kind == "claim":
                claim = await self._claim(connection, await self._claim_row(connection, binding_id, ref, snapshot))
                evidence = []
                remaining = 4096
                for span in claim.evidence:
                    encoded = span.quote.encode()
                    item = span.model_dump(mode="json")
                    if len(encoded) > remaining:
                        item.pop("quote")
                    else:
                        remaining -= len(encoded)
                    evidence.append(item)
                result.update(statement=claim.draft.statement, evidence=evidence, input_source_ids=claim.input_source_ids, snapshot=claim.snapshot)
            elif kind == "reflection":
                await self._dependencies(connection, "am_reflection_sources", "reflection_id", ref, snapshot, True)
                manifest = await connection.fetch("SELECT claim_id FROM am_reflection_claims WHERE reflection_id=$1 ORDER BY claim_id", ref)
                if not manifest:
                    raise DomainError("INPUT_INELIGIBLE", "The reflection input manifest is unavailable")
                claims = {
                    item["claim_id"]: await self._claim(
                        connection, await self._claim_row(connection, binding_id, item["claim_id"], snapshot),
                    )
                    for item in manifest
                }
                draft = ReflectionDraft.model_validate(_decode(row["draft"]))
                limitations = []
                size = len(json.dumps({"sentences": [], "limitations": []}).encode("utf-8"))
                for limitation in draft.limitations:
                    added = len(json.dumps(limitation, ensure_ascii=False).encode("utf-8")) + 2 * bool(limitations)
                    if size + added > 4096:
                        break
                    size += added
                    limitations.append(limitation)
                sentences = []
                for sentence in draft.sentences if len(limitations) == len(draft.limitations) else ():
                    provenance = {
                        (span.source_id, span.source_revision): span.model_dump(mode="json", exclude={
                            "quote", "byte_start", "byte_end",
                        })
                        for claim_id in sentence.claim_ids for span in claims[claim_id].evidence
                    }
                    item = {
                        **sentence.model_dump(mode="json"),
                        "source_provenance": list(provenance.values()),
                    }
                    added = len(json.dumps(item, ensure_ascii=False).encode("utf-8")) + 2 * bool(sentences)
                    if size + added > 4096:
                        break
                    size += added
                    sentences.append(item)
                result.update(
                    sentences=sentences, limitations=limitations, candidate=True,
                    partial=len(sentences) < len(draft.sentences) or len(limitations) < len(draft.limitations),
                )
            elif kind == "relation":
                relation = await self._relation_row(connection, binding_id, ref, snapshot)
                result.update(left_id=relation["left_id"], right_id=relation["right_id"], relation_kind=relation["kind"], reason=relation["reason"])
            elif kind in {"proposal", "rule"}:
                proposal_id = ref if kind == "proposal" else row["proposal_id"]
                proposal = row if kind == "proposal" else await connection.fetchrow("SELECT * FROM am_proposals WHERE id=$1", proposal_id)
                await self._dependencies(connection, "am_proposal_sources", "proposal_id", proposal_id)
                if kind == "rule":
                    active = await self._active_rule(connection, row)
                    result.update(digest=active.digest, revision=active.revision, scope=active.scope.value, target_bindings=tuple(target for target in active.target_bindings if target in current.bindings))
                else:
                    result.update(digest=proposal["digest"], target_set_revision=proposal["target_set_revision"])
                body = (await self._source_row(connection, proposal["binding_id"], proposal["source_id"]))["body"]
                result.update(required=proposal["required"], selector=_decode(proposal["selector"]), candidate=kind == "proposal")
                if len(body.encode()) <= 4096:
                    result["body"] = body
                else:
                    result["partial"] = True
            elif kind == "feedback":
                result.update(target_ref=row["target_ref"], feedback_kind=row["kind"], candidate=True)
                if row["source_id"]:
                    source = await self._source_row(connection, binding_id, row["source_id"])
                    if len(source["body"].encode()) <= 4096:
                        result["body"] = source["body"]
                    else:
                        result["partial"] = True
            return result

    def _vector_revision_or_none(self) -> str | None:
        try:
            return self.settings.models.vector_revision()
        except DomainError:
            return None

    async def _stats(self, connection, binding_id: str, epoch: int, snapshot: str | None = None) -> dict:
        sources = await connection.fetchval("SELECT count(*) FROM am_sources WHERE binding_id=$1 AND state='active' AND body IS NOT NULL AND (snapshot IS NULL OR snapshot=$2)", binding_id, snapshot)
        vector_revision = self._vector_revision_or_none()
        indexed = await connection.fetchrow("""SELECT count(*) AS active,
            count(*) FILTER (WHERE c.embedding IS NULL OR $3::text IS NULL OR c.vector_revision IS DISTINCT FROM $3) AS stale
            FROM am_claims c WHERE c.binding_id=$1 AND c.state='active' AND c.draft IS NOT NULL AND c.superseded_by IS NULL
            AND (c.snapshot IS NULL OR c.snapshot=$2) AND (c.valid_from IS NULL OR c.valid_from<=clock_timestamp())
            AND (c.valid_until IS NULL OR c.valid_until>clock_timestamp())
            AND EXISTS(SELECT 1 FROM am_claim_sources d WHERE d.claim_id=c.id)
            AND NOT EXISTS(SELECT 1 FROM am_claim_sources d JOIN am_sources s ON s.id=d.source_id
            WHERE d.claim_id=c.id AND (s.state<>'active' OR s.revision<>d.source_revision OR s.body IS NULL
                OR s.binding_id<>c.binding_id OR s.realm<>$4
                OR (s.snapshot IS NOT NULL AND s.snapshot IS DISTINCT FROM $2)))""", binding_id, snapshot, vector_revision, self.settings.realm)
        operations = await connection.fetch("SELECT state,count(*) AS count FROM am_operations WHERE binding_id=$1 GROUP BY state", binding_id)
        jobs = await connection.fetch("SELECT state,count(*) AS count FROM am_jobs WHERE binding_id=$1 GROUP BY state", binding_id)
        job_counts = {row["state"]: row["count"] for row in jobs}
        operation_counts = {row["state"]: row["count"] for row in operations}
        current_operations = await connection.fetch("""SELECT o.state,count(*) AS count FROM am_operations o
            WHERE o.binding_id=$1 AND EXISTS(SELECT 1 FROM am_jobs j WHERE j.operation_id=o.id
                AND j.state IN ('pending','leased','blocked','failed')) GROUP BY o.state""", binding_id)
        current_counts = {row["state"]: row["count"] for row in current_operations}
        recovery = await connection.fetch("SELECT id,operation_id,state,error_code,attempts,generation FROM am_jobs WHERE binding_id=$1 AND state IN ('blocked','failed') ORDER BY created_at,id LIMIT 8", binding_id)
        return {"binding_id": binding_id, "epoch": epoch, "active_sources": sources,
                "active_claims": indexed["active"], "stale_index_claims": indexed["stale"], "vector_revision": vector_revision,
                "pending": current_counts.get("accepted", 0) + current_counts.get("pending", 0),
                "blocked": current_counts.get("blocked", 0), "failed": current_counts.get("failed", 0),
                "current_operations": current_counts,
                "historical_operations": operation_counts, "historical_jobs": job_counts,
                "dlq": job_counts.get("failed", 0),
                "partial": bool(indexed["stale"]), "scope": "all_eligible_granted_project_rows", "snapshot": snapshot,
                "recovery_jobs": [dict(job) for job in recovery],
                "recovery_partial": job_counts.get("blocked", 0) + job_counts.get("failed", 0) > len(recovery)}

    async def stats(self, actor: Principal, binding_id: str, snapshot: str | None = None) -> dict:
        async with self._tx() as (connection, clock):
            await self._actor(connection, actor, binding_id)
            return await self._stats(connection, binding_id, clock["epoch"], snapshot)

    async def index_status(self, actor: Principal, binding_id: str, snapshot: str | None = None, limit: int = 32, after: str | None = None) -> dict:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 64 or (
            after is not None and (not isinstance(after, str) or not re.fullmatch(r"claim_[a-f0-9]{32}", after))
        ):
            raise DomainError("INDEX_LIMIT_INVALID", "Index recovery requires a bounded limit and claim cursor")
        async with self._tx() as (connection, clock):
            await self._actor(connection, actor, binding_id, (Role.OPERATOR,))
            revision = self._vector_revision_or_none()
            rows = await connection.fetch("""SELECT c.id,c.route_revision,c.vector_revision FROM am_claims c
                WHERE c.binding_id=$1 AND c.state='active' AND c.draft IS NOT NULL AND c.superseded_by IS NULL
                AND (c.snapshot IS NULL OR c.snapshot=$2) AND ($4::text IS NULL OR c.id>$4)
                AND (c.valid_from IS NULL OR c.valid_from<=clock_timestamp()) AND (c.valid_until IS NULL OR c.valid_until>clock_timestamp())
                AND (c.embedding IS NULL OR $3::text IS NULL OR c.vector_revision IS DISTINCT FROM $3)
                AND EXISTS(SELECT 1 FROM am_claim_sources d WHERE d.claim_id=c.id)
                AND NOT EXISTS(SELECT 1 FROM am_claim_sources d JOIN am_sources s ON s.id=d.source_id
                    WHERE d.claim_id=c.id AND (s.state<>'active' OR s.body IS NULL OR s.revision<>d.source_revision
                        OR s.binding_id<>c.binding_id OR s.realm<>$6 OR (s.snapshot IS NOT NULL AND s.snapshot IS DISTINCT FROM $2)))
                ORDER BY c.id LIMIT $5""", binding_id, snapshot, revision, after, limit + 1, self.settings.realm)
            selected = rows[:limit]
            return {"binding_id": binding_id, "epoch": clock["epoch"], "snapshot": snapshot, "vector_revision": revision,
                "claims": [dict(row) for row in selected], "partial": len(rows) > limit,
                "next_after": selected[-1]["id"] if len(rows) > limit else None,
                "stats": await self._stats(connection, binding_id, clock["epoch"], snapshot)}

    async def recover_index(self, actor: Principal, binding_id: str, claim_ids: tuple[str, ...], key: str, snapshot: str | None = None) -> Operation:
        if not claim_ids or len(claim_ids) > 32 or len(set(claim_ids)) != len(claim_ids):
            raise DomainError("INDEX_INPUT_INVALID", "Index recovery requires one to 32 distinct existing claims")
        selected = tuple(sorted(claim_ids))
        digest = canonical_digest({"claim_ids": selected, "snapshot": snapshot})
        async with self._tx() as (connection, _):
            current = await self._actor(connection, actor, binding_id, (Role.OPERATOR,))
            receipt = await self._receipt(connection, current, binding_id, "recover_index", key, digest)
            if receipt:
                return self._operation(await self._operation_row(connection, binding_id, receipt["target_id"]))
            await self._route(connection, self.settings.models.revision(), "embedding")
            self.settings.models.vector_revision()
            inputs = set()
            for claim_id in selected:
                claim = await self._claim_row(connection, binding_id, claim_id, snapshot)
                if claim["superseded_by"] is not None:
                    raise DomainError("CLAIM_SUPERSEDED", "Recover the canonical claim rather than an obsolete extraction generation")
                sources = await connection.fetch("SELECT source_id FROM am_claim_sources WHERE claim_id=$1", claim_id)
                inputs.update(row["source_id"] for row in sources)
            if len(inputs) > 128:
                raise DomainError("MANIFEST_TOO_LARGE", "The complete recovery source lineage exceeds the bounded input")
            for source_id in sorted(inputs):
                await self._source_row(connection, binding_id, source_id, snapshot, True)
            owners = await connection.fetch("""SELECT id,operation_id,state,claim_ids,snapshot FROM am_jobs WHERE binding_id=$1
                AND kind='reindex' AND state IN ('pending','leased','blocked','failed') AND claim_ids && $2::text[]""",
                binding_id, list(selected))
            if any(row["state"] in {"pending", "leased"} or tuple(sorted(row["claim_ids"])) != selected or row["snapshot"] != snapshot for row in owners):
                raise DomainError("INDEX_RECOVERY_BUSY", "These claims already have a durable index recovery owner; retry that job")
            if owners:
                await connection.execute("""UPDATE am_jobs SET state='superseded',error_code='INDEX_RECOVERY_REPLACED',
                    generation=generation+1,lease_token=NULL,deadline=NULL WHERE id=ANY($1::text[])""", [row["id"] for row in owners])
            await self._queue_capacity(connection)
            operation = await self._new_operation(connection, current, binding_id, "reindex")
            if owners:
                await connection.execute("UPDATE am_operations SET successor_operation_id=$2 WHERE id=ANY($1::text[])",
                    [row["operation_id"] for row in owners], operation["id"])
            await self._enqueue(connection, current, operation["id"], binding_id, "reindex", tuple(sorted(inputs)), selected, snapshot=snapshot)
            await self._save_receipt(connection, current, binding_id, "recover_index", key, digest, operation["id"])
            return self._operation(operation)

    def _vector(self, value: list[float]) -> str:
        if len(value) != 1024 or any(isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item) or abs(item) > 3.4028234663852886e38 for item in value):
            raise DomainError("VECTOR_INVALID", "A finite 1024-dimensional model vector is required")
        if sum(item * item for item in value) == 0:
            raise DomainError("VECTOR_INVALID", "A zero model vector is not a usable embedding")
        return "[" + ",".join(str(float(item)) for item in value) + "]"

    async def _route(self, connection, revision: str, purpose: str) -> None:
        if purpose not in MODEL_PURPOSES or purpose not in self.settings.allowed_model_purposes:
            raise DomainError("MODEL_ROUTE_BLOCKED", "The model purpose is not configured", status=503)
        if revision != self.settings.models.revision():
            raise DomainError("MODEL_ROUTE_BLOCKED", "The model manifest does not match the configured route", status=503)
        purposes = (purpose, "embedding") if purpose == "extraction" else (purpose,)
        for item in purposes:
            if item not in self.settings.allowed_model_purposes:
                raise DomainError("MODEL_ROUTE_BLOCKED", "The model purpose is not configured", status=503)
            row = await connection.fetchrow("SELECT * FROM am_routes WHERE purpose=$1 AND enabled AND revision=$2", item, revision)
            if row is None:
                raise DomainError("MODEL_ROUTE_BLOCKED", "The current model route is not approved", status=503)

    async def search(self, actor: Principal, binding_id: str, query_vector: list[float], lexical_tokens: list[str], snapshot: str | None, limit: int = 20) -> list[tuple[Claim, tuple[str, ...]]]:
        vector = self._vector(query_vector)
        if not 1 <= limit <= 100 or len(lexical_tokens) > 2048 or any(not isinstance(token, str) or not token or len(token.encode()) > 1024 for token in lexical_tokens):
            raise DomainError("SEARCH_LIMIT_INVALID", "The retrieval bounds are invalid")
        async with self._tx() as (connection, _):
            await self._actor(connection, actor, binding_id)
            revision = self.settings.models.revision()
            await self._route(connection, revision, "embedding")
            vector_revision = self.settings.models.vector_revision()
            rows = await connection.fetch("""WITH eligible AS MATERIALIZED (
                SELECT c.* FROM am_claims c WHERE c.binding_id=$1 AND c.state='active' AND c.draft IS NOT NULL AND c.superseded_by IS NULL
                AND (c.snapshot IS NULL OR c.snapshot=$3)
                AND (c.valid_from IS NULL OR c.valid_from<=clock_timestamp()) AND (c.valid_until IS NULL OR c.valid_until>clock_timestamp())
                AND EXISTS(SELECT 1 FROM am_claim_sources d WHERE d.claim_id=c.id)
                AND NOT EXISTS(SELECT 1 FROM am_claim_sources d JOIN am_sources s ON s.id=d.source_id WHERE d.claim_id=c.id
                  AND (s.state<>'active' OR s.body IS NULL OR s.revision<>d.source_revision OR s.binding_id<>$1 OR s.realm<>$7
                    OR (s.snapshot IS NOT NULL AND s.snapshot IS DISTINCT FROM $3)))
            ), vector_candidates AS (
                SELECT id, row_number() OVER(ORDER BY embedding OPERATOR(public.<=>) $4::public.vector,id) AS rank
                FROM eligible WHERE embedding IS NOT NULL AND vector_revision=$2
                ORDER BY embedding OPERATOR(public.<=>) $4::public.vector,id LIMIT $6
            ), lexical_candidates AS (
                SELECT x.id, row_number() OVER(ORDER BY
                  cardinality(ARRAY(SELECT unnest(x.lexical_tokens) INTERSECT SELECT unnest($5::text[]))) DESC,x.id) AS rank
                FROM am_claims x JOIN eligible e ON e.id=x.id WHERE x.lexical_tokens && $5::text[]
                ORDER BY cardinality(ARRAY(SELECT unnest(x.lexical_tokens) INTERSECT SELECT unnest($5::text[]))) DESC,x.id LIMIT $6
            ), entity_candidates AS (
                SELECT c.id,row_number() OVER(ORDER BY count(*) DESC,c.id) AS rank
                FROM eligible c JOIN am_entities e ON e.claim_id=c.id WHERE e.search_name=ANY($8::text[])
                GROUP BY c.id ORDER BY count(*) DESC,c.id LIMIT $6
            ), arms AS (
                SELECT id,rank,'vector'::text AS arm FROM vector_candidates UNION ALL
                SELECT id,rank,'lexical' FROM lexical_candidates UNION ALL SELECT id,rank,'entity' FROM entity_candidates
            ), fused AS (
                SELECT id,sum(1.0/(60+rank)) AS score,array_agg(arm ORDER BY arm) AS arms
                FROM arms GROUP BY id ORDER BY score DESC,id LIMIT $6
            ) SELECT c.*,f.arms FROM fused f JOIN eligible c ON c.id=f.id ORDER BY f.score DESC,c.id""",
                binding_id, vector_revision, snapshot, vector, list(dict.fromkeys(lexical_tokens)), limit, self.settings.realm,
                list(dict.fromkeys(_entity(token) for token in lexical_tokens)))
            return [(await self._claim(connection, row), tuple(row["arms"])) for row in rows]

    async def _relation_row(self, connection, binding_id: str, relation_id: str, snapshot: str | None):
        row = await connection.fetchrow("SELECT * FROM am_relations WHERE id=$1 AND binding_id=$2 AND state='active'", relation_id, binding_id)
        if row is None:
            raise DomainError("RELATION_INELIGIBLE", "The relation is no longer current")
        sources = await self._dependencies(connection, "am_relation_sources", "relation_id", relation_id, snapshot, True)
        manifest = await connection.fetch("SELECT claim_id FROM am_relation_claims WHERE relation_id=$1 ORDER BY claim_id", relation_id)
        if not sources or not manifest:
            raise DomainError("RELATION_INELIGIBLE", "The complete relation input manifest is unavailable")
        for claim_id in {row["left_id"], row["right_id"], *(item["claim_id"] for item in manifest)}:
            await self._claim_row(connection, binding_id, claim_id, snapshot)
        return row

    async def relations(self, actor: Principal, binding_id: str, claim_ids: tuple[str, ...], snapshot: str | None = None) -> list[Relation]:
        if len(claim_ids) > 100:
            raise DomainError("MANIFEST_TOO_LARGE", "The relation input set is too large")
        async with self._tx() as (connection, _):
            await self._actor(connection, actor, binding_id)
            rows = connection.cursor("""SELECT r.* FROM am_relations r WHERE r.binding_id=$1 AND r.state='active'
                AND (r.left_id=ANY($2::text[]) OR r.right_id=ANY($2::text[])) ORDER BY r.id""", binding_id, list(claim_ids), prefetch=64)
            result = []
            seen = set()
            async for row in rows:
                try:
                    await self._relation_row(connection, binding_id, row["id"], snapshot)
                except DomainError as error:
                    if error.code not in {"RELATION_INELIGIBLE", "INPUT_INELIGIBLE", "CLAIM_INELIGIBLE"}:
                        raise
                    continue
                key = (row["left_id"], row["right_id"], row["kind"])
                if key in seen:
                    continue
                seen.add(key)
                if len(result) == 128:
                    raise DomainError("RELATION_CONTEXT_OVERFLOW", "The complete current relation set exceeds the bounded context")
                result.append(Relation(id=row["id"], left_id=row["left_id"], right_id=row["right_id"], kind=row["kind"], reason=row["reason"]))
            return result

    async def _create_proposal(self, connection, actor, command: RuleProposal, clock, operation_id: str) -> dict:
        if actor.role == Role.AGENT and command.required:
            raise _denied()
        for source_id in command.source_ids:
            await self._source_row(connection, command.binding_id, source_id)
        source_id = await self._insert_source(connection, actor, CaptureCommand(
            binding_id=command.binding_id, idempotency_key=command.idempotency_key,
            origin_key=f"rule-proposal:{operation_id}", body=command.body, speaker="agent_note",
        ), operation_id)
        proposal_id = _id("proposal")
        digest = canonical_digest({
            "proposal": command.model_dump(mode="json", exclude={"idempotency_key"}),
            "principal_id": actor.id, "realm": actor.realm, "target_set_revision": clock["roster_revision"],
        })
        await connection.execute("""INSERT INTO am_proposals(id,binding_id,principal_id,source_id,selector,exceptions,required,digest,target_set_revision)
            VALUES($1,$2,$3,$4,$5::jsonb,$6::jsonb,$7,$8,$9)""", proposal_id, command.binding_id, actor.id, source_id,
            _json(command.selector), _json(command.exceptions), command.required, digest, clock["roster_revision"])
        for input_id in sorted({source_id, *command.source_ids}):
            row = await self._source_row(connection, command.binding_id, input_id)
            await connection.execute("INSERT INTO am_proposal_sources(proposal_id,source_id,source_revision) VALUES($1,$2,$3)", proposal_id, input_id, row["revision"])
        return {"proposal_id": proposal_id, "digest": digest, "target_set_revision": clock["roster_revision"], "source_id": source_id, "state": "candidate"}

    async def propose_rule(self, actor: Principal, command: RuleProposal) -> dict:
        async with self._tx() as (connection, clock):
            current = await self._actor(connection, actor, command.binding_id, (Role.AGENT, Role.OPERATOR, Role.APPROVER))
            digest = canonical_digest(command)
            receipt = await self._receipt(connection, current, command.binding_id, "propose_rule", command.idempotency_key, digest)
            if receipt:
                result = dict(_decode(receipt["result"]))
                row = await connection.fetchrow("SELECT state FROM am_proposals WHERE id=$1", receipt["target_id"])
                result["state"] = row["state"] if row else "retracted"
                return result
            operation = await self._new_operation(connection, current, command.binding_id, "propose_rule", "semantic_ready")
            result = await self._create_proposal(connection, current, command, clock, operation["id"])
            await connection.execute("UPDATE am_operations SET artifact_id=$2,source_id=$3 WHERE id=$1", operation["id"], result["proposal_id"], result["source_id"])
            await self._save_receipt(connection, current, command.binding_id, "propose_rule", command.idempotency_key, digest, result["proposal_id"], result)
            return result

    async def _active_rule(self, connection, row) -> ActiveRule:
        if row["state"] != "active":
            raise DomainError("RULE_INELIGIBLE", "The approved rule revision is no longer active")
        proposal = await connection.fetchrow("SELECT * FROM am_proposals WHERE id=$1 AND state='candidate'", row["proposal_id"])
        if proposal is None:
            raise DomainError("RULE_INELIGIBLE", "The approved proposal is no longer eligible")
        approver = await self._credential(connection, row["approver_credential_id"])
        if approver.generation != row["approver_generation"] or approver.role not in (Role.OPERATOR, Role.APPROVER):
            raise DomainError("RULE_INELIGIBLE", "The approval authority is no longer current")
        approval = RuleApproval.model_validate(_decode(row["approval"]))
        self._verify_shared_signature(approver, approval)
        sources = await self._dependencies(connection, "am_proposal_sources", "proposal_id", proposal["id"])
        body = next((source["body"] for source in sources if source["id"] == proposal["source_id"]), None)
        if body is None:
            raise DomainError("RULE_INELIGIBLE", "The exact approved body is unavailable")
        targets = await connection.fetch("SELECT binding_id FROM am_rule_targets WHERE rule_id=$1 ORDER BY binding_id", row["id"])
        target_ids = tuple(target["binding_id"] for target in targets)
        if not target_ids or any(target not in approver.bindings for target in target_ids):
            raise DomainError("RULE_INELIGIBLE", "The exact approval grants are no longer current")
        if approval.proposal_id != proposal["id"] or approval.expected_digest != proposal["digest"] or approval.scope.value != row["scope"] or tuple(sorted(approval.target_bindings)) != target_ids or approval.target_set_revision != row["target_set_revision"]:
            raise DomainError("RULE_INELIGIBLE", "The approved target meaning changed")
        expected = canonical_digest({
            "proposal_digest": proposal["digest"], "scope": row["scope"], "target_bindings": list(target_ids),
            "target_set_revision": row["target_set_revision"], "approver_id": approver.id,
            "realm": self.settings.realm, "deployment_id": self.settings.deployment_id,
        })
        if expected != row["digest"]:
            raise DomainError("RULE_INELIGIBLE", "The exact approval digest is invalid")
        return ActiveRule(id=row["id"], revision=row["revision"], digest=row["digest"], body=body,
            selector=Selector.model_validate(_decode(proposal["selector"])), exceptions=tuple(_decode(proposal["exceptions"])),
            required=proposal["required"], scope=row["scope"], target_bindings=target_ids,
            source_ids=tuple(source["id"] for source in sources))

    async def rules(self, actor: Principal, binding_id: str) -> list[ActiveRule]:
        async with self._tx() as (connection, _):
            current = await self._actor(connection, actor, binding_id)
            rows = await connection.fetch("""SELECT r.* FROM am_rules r JOIN am_rule_targets t ON t.rule_id=r.id
                WHERE t.binding_id=$1 AND r.state='active' ORDER BY r.id""", binding_id)
            result = []
            for row in rows:
                active = await self._active_rule(connection, row)
                visible = await connection.fetch("SELECT id FROM am_sources WHERE id=ANY($1::text[]) AND binding_id=ANY($2::text[])", list(active.source_ids), list(current.bindings))
                result.append(active.model_copy(update={
                    "target_bindings": tuple(target for target in active.target_bindings if target in current.bindings),
                    "source_ids": tuple(source["id"] for source in sorted(visible, key=lambda item: item["id"])),
                }))
            return result

    def _verify_shared_signature(self, actor: Principal, command: RuleApproval) -> None:
        if self.settings.mode != "company" or command.scope != RuleScope.SHARED:
            return
        if not self.settings.strong_shared_approval or self.settings.approver_public_key is None:
            raise DomainError("SHARED_APPROVAL_UNAVAILABLE", "A separately managed approval signer is required", status=503)
        if command.approver_signature is None:
            raise DomainError("SHARED_APPROVAL_DENIED", "The exact approval requires the configured signer", status=403)
        from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.hazmat.primitives.serialization import load_pem_public_key

        from .domain import approval_signing_payload
        try:
            key = load_pem_public_key(self.settings.approver_public_key.read_bytes())
            if not isinstance(key, Ed25519PublicKey):
                raise ValueError("Wrong key type")
            signature = base64.b64decode(command.approver_signature, validate=True)
            key.verify(signature, approval_signing_payload(self.settings.deployment_id, self.settings.realm, actor.id, command))
        except (OSError, ValueError, InvalidSignature, UnsupportedAlgorithm):
            raise DomainError("SHARED_APPROVAL_DENIED", "The exact approval signature cannot be verified", status=403) from None

    async def approve_rule(self, actor: Principal, command: RuleApproval) -> ActiveRule:
        self._verify_shared_signature(actor, command)
        async with self._tx() as (connection, clock):
            current = await self._actor(connection, actor, roles=(Role.OPERATOR, Role.APPROVER))
            proposal = await connection.fetchrow("SELECT * FROM am_proposals WHERE id=$1", command.proposal_id)
            if proposal is None:
                raise _missing()
            await self._actor(connection, current, proposal["binding_id"])
            targets = tuple(sorted(command.target_bindings))
            if len(set(targets)) != len(targets):
                raise DomainError("TARGET_SET_INVALID", "Approval targets must be distinct")
            for target in targets:
                await self._actor(connection, current, target)
            digest = canonical_digest(command.model_dump(mode="json", exclude={"approver_signature"}))
            receipt = await self._receipt(connection, current, proposal["binding_id"], "approve_rule", command.idempotency_key, digest)
            if receipt:
                row = await connection.fetchrow("SELECT * FROM am_rules WHERE id=$1", receipt["target_id"])
                return await self._active_rule(connection, row)
            if proposal["state"] != "candidate" or proposal["digest"] != command.expected_digest:
                raise DomainError("APPROVAL_STALE", "The exact proposal digest is no longer eligible")
            previous = await connection.fetchrow("SELECT * FROM am_rules WHERE proposal_id=$1 ORDER BY revision DESC,id LIMIT 1", proposal["id"])
            if command.target_set_revision != proposal["target_set_revision"]:
                raise DomainError("APPROVAL_STALE", "The proposal target snapshot changed")
            # New cross-project approvals require the current roster. Local approval and
            # exact frozen reapproval do not acquire authority over later roster entries.
            if previous is None and command.scope != RuleScope.LOCAL_PROJECT and command.target_set_revision != clock["roster_revision"]:
                raise DomainError("APPROVAL_STALE", "The project roster changed after the proposal snapshot")
            if command.scope == RuleScope.LOCAL_PROJECT and targets != (proposal["binding_id"],):
                raise DomainError("TARGET_SET_INVALID", "Local-project approval must target exactly this project")
            if command.scope == RuleScope.MY_PROJECTS:
                owned = await connection.fetch("SELECT id FROM am_bindings WHERE id=ANY($1::text[]) AND owner_id=$2 AND realm=$3", list(targets), current.id, current.realm)
                if len(owned) != len(targets):
                    raise _denied()
            await self._dependencies(connection, "am_proposal_sources", "proposal_id", proposal["id"])
            if await connection.fetchval("SELECT EXISTS(SELECT 1 FROM am_rules WHERE proposal_id=$1 AND state='active')", proposal["id"]):
                raise DomainError("APPROVAL_CONFLICT", "This immutable proposal already has an active approval revision")
            if previous:
                frozen = await connection.fetch("SELECT binding_id FROM am_rule_targets WHERE rule_id=$1 ORDER BY binding_id", previous["id"])
                if command.scope.value != previous["scope"] or targets != tuple(row["binding_id"] for row in frozen) or command.target_set_revision != previous["target_set_revision"]:
                    raise DomainError("APPROVAL_CONFLICT", "Reapproval must retain the exact frozen approval scope and targets")
            revision = previous["revision"] + 1 if previous else 1
            rule_id = _id("rule")
            active_digest = canonical_digest({
                "proposal_digest": proposal["digest"], "scope": command.scope.value,
                "target_bindings": list(targets), "target_set_revision": command.target_set_revision,
                "approver_id": current.id, "realm": current.realm, "deployment_id": self.settings.deployment_id,
            })
            await connection.execute("""INSERT INTO am_rules(id,proposal_id,revision,digest,scope,target_set_revision,approver_credential_id,approver_generation,approval)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb)""", rule_id, proposal["id"], revision, active_digest, command.scope.value,
                command.target_set_revision, current.credential_id, current.generation, _json(command))
            await connection.executemany("INSERT INTO am_rule_targets(rule_id,binding_id) VALUES($1,$2)", [(rule_id, target) for target in targets])
            await self._tick(connection)
            await self._save_receipt(connection, current, proposal["binding_id"], "approve_rule", command.idempotency_key, digest, rule_id)
            active = await self._active_rule(connection, await connection.fetchrow("SELECT * FROM am_rules WHERE id=$1", rule_id))
            if active.required:
                from .context import compose
                try:
                    compose(ContextCommand(query="Required rule approval", max_bytes=HOST_CONTEXT_BYTES - len(BOUNDED_CONTEXT_MARKER.encode()) - 1),
                        (active.model_copy(update={"selector": Selector()}),), (), (), protected_action=True)
                except DomainError as error:
                    if error.code != "REQUIRED_CONTEXT_OVERFLOW":
                        raise
                    raise DomainError("REQUIRED_RULE_TOO_LARGE", "The exact required rule cannot fit the minimum supported UTF-8 host envelope", status=413) from error
            return active

    async def withdraw_rule(self, actor: Principal, binding_id: str, rule_id: str, key: str) -> dict:
        digest = canonical_digest({"rule_id": rule_id})
        async with self._tx() as (connection, _):
            current = await self._actor(connection, actor, binding_id, (Role.OPERATOR, Role.APPROVER))
            receipt = await self._receipt(connection, current, binding_id, "withdraw_rule", key, digest)
            if receipt:
                return dict(_decode(receipt["result"]))
            row = await connection.fetchrow("""SELECT r.* FROM am_rules r JOIN am_rule_targets t ON t.rule_id=r.id
                WHERE r.id=$1 AND t.binding_id=$2""", rule_id, binding_id)
            if row is None:
                raise _missing()
            if current.role == Role.APPROVER and row["approver_credential_id"] != current.credential_id:
                raise _denied()
            await connection.execute("UPDATE am_rules SET state='retracted',revision=revision+1 WHERE id=$1 AND state='active'", rule_id)
            epoch = await self._tick(connection)
            result = {"id": rule_id, "state": "withdrawn", "epoch": epoch}
            await self._save_receipt(connection, current, binding_id, "withdraw_rule", key, digest, rule_id, result)
            return result

    async def configure_route(self, actor: Principal, revision: str, purposes: tuple[str, ...], enabled: bool) -> None:
        if not re.fullmatch(r"[a-f0-9]{64}", revision) or not purposes or len(set(purposes)) != len(purposes) or any(purpose not in MODEL_PURPOSES for purpose in purposes):
            raise DomainError("ROUTE_INVALID", "The exact route revision and purposes are required")
        if enabled and (revision != self.settings.models.revision() or any(purpose not in self.settings.allowed_model_purposes for purpose in purposes)):
            raise DomainError("MODEL_ROUTE_BLOCKED", "The model route is not configured", status=503)
        async with self._tx() as (connection, _):
            await self._actor(connection, actor, roles=(Role.OPERATOR,))
            epoch = await self._tick(connection)
            if enabled:
                await connection.execute(
                    "UPDATE am_routes SET enabled=false,epoch=$1 WHERE purpose<>ALL($2::text[]) AND enabled",
                    epoch, list(self.settings.allowed_model_purposes),
                )
            for purpose in purposes:
                await connection.execute("""INSERT INTO am_routes(purpose,revision,enabled,epoch) VALUES($1,$2,$3,$4)
                    ON CONFLICT(purpose) DO UPDATE SET revision=EXCLUDED.revision,enabled=EXCLUDED.enabled,epoch=EXCLUDED.epoch""", purpose, revision, enabled, epoch)

    def _lease(self, row) -> JobLease:
        return JobLease(job_id=row["id"], lease_token=row["lease_token"], generation=row["generation"],
            deadline=row["deadline"], kind=row["kind"], binding_id=row["binding_id"],
            operation_id=row["operation_id"], credential_id=row["credential_id"], source_ids=tuple(row["source_ids"]),
            claim_ids=tuple(row["claim_ids"]), query_source_id=row["query_source_id"], attempts=row["attempts"])

    async def _fence(self, connection, lease: JobLease, *, allow_renewed_deadline: bool = False):
        row = await connection.fetchrow("""SELECT * FROM am_jobs WHERE id=$1 AND state='leased'
            AND lease_token=$2 AND generation=$3 AND (deadline=$4 OR ($5 AND deadline>$4))
            AND deadline>clock_timestamp() FOR UPDATE""",
            lease.job_id, lease.lease_token, lease.generation, lease.deadline, allow_renewed_deadline)
        current = self._lease(row) if row is not None else None
        if current is not None and allow_renewed_deadline:
            current = current.model_copy(update={"deadline": lease.deadline})
        if current != lease:
            raise DomainError("LEASE_STALE", "This worker lease is no longer current")
        return row

    async def claim_job(self) -> JobLease | None:
        async with self._tx() as (connection, _):
            exhausted = await connection.fetch("""UPDATE am_jobs SET state='failed',error_code='LEASE_EXHAUSTED',
                generation=generation+1,lease_token=NULL,deadline=NULL
                WHERE ((state='leased' AND deadline<=clock_timestamp()) OR state='pending') AND attempts>=$1
                RETURNING operation_id""", self.settings.job_attempt_limit)
            if exhausted:
                epoch = await self._tick(connection)
                await connection.execute("UPDATE am_operations SET state='failed',error_code='LEASE_EXHAUSTED',epoch=$2 WHERE id=ANY($1::text[])", [row["operation_id"] for row in exhausted], epoch)
            row = await connection.fetchrow("""SELECT * FROM am_jobs WHERE
                (state='pending' AND available_at<=clock_timestamp()) OR (state='leased' AND deadline<=clock_timestamp())
                ORDER BY available_at,created_at,id FOR UPDATE SKIP LOCKED LIMIT 1""")
            if row is None:
                return None
            row = await connection.fetchrow("""UPDATE am_jobs SET state='leased',lease_token=$2,
                generation=generation+1,attempts=attempts+1,deadline=clock_timestamp()+$3*interval '1 second',error_code=NULL
                WHERE id=$1 RETURNING *""", row["id"], _id("lease"), self.settings.lease_seconds)
            await connection.execute("UPDATE am_operations SET state='pending',error_code=NULL WHERE id=$1", row["operation_id"])
            return self._lease(row)

    async def heartbeat(self, lease: JobLease) -> JobLease:
        async with self._tx() as (connection, _):
            await self._fence(connection, lease)
            row = await connection.fetchrow("UPDATE am_jobs SET deadline=clock_timestamp()+$2*interval '1 second' WHERE id=$1 RETURNING *", lease.job_id, self.settings.lease_seconds)
            return self._lease(row)

    async def fail_job(self, lease: JobLease, code: str, blocked: bool = False) -> None:
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code):
            code = "JOB_FAILED"
        async with self._tx() as (connection, _):
            row = await self._fence(connection, lease)
            state = "blocked" if blocked else ("failed" if row["attempts"] >= self.settings.job_attempt_limit else "pending")
            delay = min(300, 2 ** min(row["attempts"], 8))
            await connection.execute("""UPDATE am_jobs SET state=$2,error_code=$3,generation=generation+1,
                lease_token=NULL,deadline=NULL,available_at=clock_timestamp()+$4*interval '1 second' WHERE id=$1""", lease.job_id, state, code, delay)
            epoch = await self._tick(connection)
            await connection.execute("UPDATE am_operations SET state=$2,error_code=$3,epoch=$4 WHERE id=$1", lease.operation_id, state, code, epoch)

    async def retry_job(self, actor: Principal, job_id: str) -> None:
        async with self._tx() as (connection, _):
            current = await self._actor(connection, actor, roles=(Role.OPERATOR,))
            row = await connection.fetchrow("SELECT * FROM am_jobs WHERE id=$1", job_id)
            if row is None or row["binding_id"] not in current.bindings:
                raise _missing()
            await self._actor(connection, current, row["binding_id"])
            if row["state"] not in ("blocked", "failed"):
                raise DomainError("JOB_NOT_RETRYABLE", "Only blocked or dead-letter jobs can be explicitly retried")
            for source_id in row["source_ids"]:
                await self._source_row(connection, row["binding_id"], source_id, row["snapshot"], True)
            await connection.execute("""UPDATE am_jobs SET state='pending',error_code=NULL,generation=generation+1,attempts=0,
                lease_token=NULL,deadline=NULL,credential_id=$2,credential_generation=$3,available_at=clock_timestamp() WHERE id=$1""",
                job_id, current.credential_id, current.generation)
            epoch = await self._tick(connection)
            await connection.execute("UPDATE am_operations SET state='pending',error_code=NULL,epoch=$2 WHERE id=$1", row["operation_id"], epoch)

    def _admission(self, row) -> Admission:
        return Admission(id=row["id"], binding_id=row["binding_id"], credential_id=row["credential_id"],
            credential_generation=row["credential_generation"], epoch=row["epoch"], route_revision=row["route_revision"],
            purpose=row["purpose"], sources=tuple(RevisionRef.model_validate(item) for item in _decode(row["sources"])),
            claim_ids=tuple(row["claim_ids"]), deadline=row["deadline"], job_id=row["job_id"],
            lease_token=row["lease_token"], generation=row["generation"])

    async def _route_epochs(self, connection, revision: str, purpose: str) -> dict:
        await self._route(connection, revision, purpose)
        purposes = [purpose, "embedding"] if purpose == "extraction" else [purpose]
        rows = await connection.fetch("SELECT purpose,epoch FROM am_routes WHERE purpose=ANY($1::text[])", purposes)
        return {row["purpose"]: row["epoch"] for row in rows}

    async def _new_admission(self, connection, clock, actor, binding_id, claim_ids, source_ids, route_revision, purpose, snapshot=None, lease=None) -> Admission:
        if len(claim_ids) > 64 or len(source_ids) > 128 or len(set(claim_ids)) != len(claim_ids):
            raise DomainError("MANIFEST_TOO_LARGE", "The complete input manifest exceeds the bounded model input")
        route_epochs = await self._route_epochs(connection, route_revision, purpose)
        inputs = set(source_ids)
        for claim_id in claim_ids:
            claim = await self._claim_row(connection, binding_id, claim_id, snapshot, purpose != "consolidation")
            if lease is not None and lease.kind == "reindex" and claim["superseded_by"] is not None:
                raise DomainError("CLAIM_SUPERSEDED", "The queued extraction generation was superseded")
            rows = await connection.fetch("SELECT source_id FROM am_claim_sources WHERE claim_id=$1", claim_id)
            inputs.update(row["source_id"] for row in rows)
        if len(inputs) > 128:
            raise DomainError("MANIFEST_TOO_LARGE", "The complete source lineage exceeds the bounded input")
        sources = []
        for source_id in sorted(inputs):
            row = await self._source_row(connection, binding_id, source_id, snapshot, True)
            sources.append({"id": source_id, "revision": row["revision"]})
        deadline = await connection.fetchval("SELECT clock_timestamp()+$1*interval '1 second'", self.settings.models.timeout_seconds + self.settings.lease_seconds)
        admission_id = _id("admission")
        row = await connection.fetchrow("""INSERT INTO am_admissions(id,binding_id,credential_id,credential_generation,epoch,
            deletion_generation,route_revision,purpose,route_epochs,sources,claim_ids,deadline,snapshot,job_id,lease_token,generation)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10::jsonb,$11,$12,$13,$14,$15,$16) RETURNING *""",
            admission_id, binding_id, actor.credential_id, actor.generation, clock["epoch"], clock["deletion_generation"],
            route_revision, purpose, _json(route_epochs), _json(sources), list(claim_ids), deadline, snapshot,
            lease.job_id if lease else None, lease.lease_token if lease else None, lease.generation if lease else None)
        return self._admission(row)

    async def admit_job(self, lease: JobLease, route_revision: str, purpose: str) -> Admission:
        expected = {"extract": "extraction", "consolidate": "consolidation", "reflect": "reflection", "reindex": "embedding"}
        if purpose != expected.get(lease.kind):
            raise DomainError("ADMISSION_PURPOSE_INVALID", "The purpose does not match the durable job")
        async with self._tx() as (connection, clock):
            # Admission may have waited behind this owner's heartbeat on am_clock;
            # heartbeat and publication still require the exact current deadline.
            row = await self._fence(connection, lease, allow_renewed_deadline=True)
            actor = await self._credential(connection, row["credential_id"])
            await self._actor(connection, actor, row["binding_id"])
            if actor.generation != row["credential_generation"]:
                raise DomainError("AUTH_DENIED", "The job credential generation is no longer current", status=401)
            source_ids = tuple(sorted({*row["source_ids"], *([row["query_source_id"]] if row["query_source_id"] else [])}))
            if lease.kind == "extract":
                await self._derivation_allowed(connection, source_ids)
            return await self._new_admission(connection, clock, actor, row["binding_id"], tuple(row["claim_ids"]),
                source_ids, route_revision, purpose, row["snapshot"], lease)

    async def admit_read(self, actor: Principal, binding_id: str, claim_ids: tuple[str, ...], route_revision: str, purpose: str, snapshot: str | None = None) -> Admission:
        if purpose not in ("embedding", "rerank", "reflection"):
            raise DomainError("ADMISSION_PURPOSE_INVALID", "The read-time purpose is invalid")
        async with self._tx() as (connection, clock):
            current = await self._actor(connection, actor, binding_id)
            return await self._new_admission(connection, clock, current, binding_id, claim_ids, (), route_revision, purpose, snapshot)

    async def _recheck(self, connection, clock, admission: Admission):
        row = await connection.fetchrow("SELECT * FROM am_admissions WHERE id=$1 AND deadline>clock_timestamp()", admission.id)
        if row is None or self._admission(row) != admission:
            raise DomainError("ADMISSION_STALE", "The durable input admission is no longer current")
        actor = await self._credential(connection, admission.credential_id)
        await self._actor(connection, actor, admission.binding_id)
        if actor.generation != admission.credential_generation:
            raise DomainError("ADMISSION_STALE", "The admitted credential generation changed")
        route_epochs = await self._route_epochs(connection, admission.route_revision, admission.purpose)
        if route_epochs != _decode(row["route_epochs"]):
            raise DomainError("ADMISSION_STALE", "The model route approval changed after admission")
        for source in admission.sources:
            current = await self._source_row(connection, admission.binding_id, source.id, row["snapshot"], True)
            if current["revision"] != source.revision:
                raise DomainError("ADMISSION_STALE", "An actual input source revision changed")
        for claim_id in admission.claim_ids:
            claim = await self._claim_row(connection, admission.binding_id, claim_id, row["snapshot"], admission.purpose != "consolidation")
            if admission.job_id is not None and admission.purpose == "embedding" and claim["superseded_by"] is not None:
                raise DomainError("ADMISSION_STALE", "The indexed extraction generation was superseded")
        if admission.job_id is not None:
            job = await connection.fetchrow("""SELECT * FROM am_jobs WHERE id=$1 AND state='leased'
                AND lease_token=$2 AND generation=$3 AND deadline>clock_timestamp()""",
                admission.job_id, admission.lease_token, admission.generation)
            if job is None or tuple(job["claim_ids"]) != admission.claim_ids:
                raise DomainError("LEASE_STALE", "The admitted worker lease is no longer current")
        return row

    async def recheck(self, admission: Admission) -> int:
        async with self._tx() as (connection, clock):
            await self._recheck(connection, clock, admission)
            return clock["epoch"]

    async def admitted_sources(self, admission: Admission) -> list[Source]:
        async with self._tx() as (connection, clock):
            row = await self._recheck(connection, clock, admission)
            return [self._source(await self._source_row(connection, admission.binding_id, item.id, row["snapshot"], True)) for item in admission.sources]

    async def admitted_claims(self, admission: Admission) -> list[Claim]:
        async with self._tx() as (connection, clock):
            row = await self._recheck(connection, clock, admission)
            return [await self._claim(connection, await self._claim_row(connection, admission.binding_id, claim_id, row["snapshot"], admission.purpose != "consolidation")) for claim_id in admission.claim_ids]

    async def _publish_fence(self, connection, clock, lease: JobLease, admission: Admission, kind: str):
        if lease.kind != kind or admission.job_id != lease.job_id or admission.lease_token != lease.lease_token or admission.generation != lease.generation:
            raise DomainError("LEASE_STALE", "The result does not belong to this job admission")
        job = await self._fence(connection, lease)
        await self._recheck(connection, clock, admission)
        return job

    async def _finish_job(self, connection, lease: JobLease, state="semantic_ready", artifact_id=None) -> Operation:
        await connection.execute("UPDATE am_jobs SET state='done',lease_token=NULL,deadline=NULL WHERE id=$1", lease.job_id)
        epoch = await self._tick(connection)
        await connection.execute("UPDATE am_operations SET state=$2,error_code=NULL,epoch=$3,artifact_id=COALESCE($4,artifact_id) WHERE id=$1", lease.operation_id, state, epoch, artifact_id)
        return self._operation(await self._operation_row(connection, lease.binding_id, lease.operation_id))

    def _spans(self, draft: ClaimDraft, sources: dict[str, Source]) -> tuple[EvidenceSpan, ...]:
        result = []
        for evidence in draft.evidence:
            source = sources.get(evidence.source_id)
            if source is None:
                raise DomainError("EVIDENCE_INVALID", "Evidence must belong to the actual admitted source manifest")
            body = source.body.encode("utf-8")
            quote = evidence.quote.encode("utf-8")
            start = evidence.byte_start
            if start is None:
                start = body.find(quote)
                if start < 0 or body.find(quote, start + 1) >= 0:
                    raise DomainError("EVIDENCE_AMBIGUOUS", "Repeated or absent evidence requires an exact UTF-8 byte offset")
            if isinstance(start, bool) or not isinstance(start, int) or start < 0:
                raise DomainError("EVIDENCE_INVALID", "Evidence requires a nonnegative UTF-8 byte offset")
            end = start + len(quote)
            if body[start:end] != quote:
                raise DomainError("EVIDENCE_INVALID", "The quote must match the original UTF-8 byte span exactly")
            try:
                body[:start].decode("utf-8")
                body[:end].decode("utf-8")
            except UnicodeDecodeError:
                raise DomainError("EVIDENCE_INVALID", "Evidence offsets must align to UTF-8 boundaries") from None
            result.append(EvidenceSpan(source_id=source.id, source_revision=source.revision, source_speaker=source.speaker, source_event_time=source.event_time, source_recorded_at=source.recorded_at, byte_start=start, byte_end=end, quote=evidence.quote))
        return tuple(result)

    async def publish_reindex(self, lease: JobLease, admission: Admission, vectors: list[list[float]], lexical_rows: list[list[str]]) -> Operation:
        if not admission.claim_ids or len(vectors) != len(admission.claim_ids) or len(lexical_rows) != len(admission.claim_ids):
            raise DomainError("INDEX_LENGTH_INVALID", "Every admitted existing claim requires exactly one vector and lexical row")
        vector_rows = [self._vector(vector) for vector in vectors]
        if any(len(row) > 2048 or any(not isinstance(token, str) or not token or len(token.encode()) > 1024 for token in row) for row in lexical_rows):
            raise DomainError("LEXICAL_INVALID", "The lexical rows exceed the bounded index contract")
        async with self._tx() as (connection, clock):
            await self._publish_fence(connection, clock, lease, admission, "reindex")
            if admission.purpose != "embedding":
                raise DomainError("ADMISSION_PURPOSE_INVALID", "Index publication requires embedding admission")
            revision = self.settings.models.vector_revision()
            for claim_id, vector, tokens in zip(admission.claim_ids, vector_rows, lexical_rows, strict=True):
                await connection.execute("""UPDATE am_claims SET embedding=$2::public.vector,lexical_tokens=$3,vector_revision=$4
                    WHERE id=$1 AND binding_id=$5 AND state='active' AND superseded_by IS NULL""",
                    claim_id, vector, list(dict.fromkeys(tokens)), revision, lease.binding_id)
            return await self._finish_job(connection, lease)

    async def _equivalent_claim(self, connection, binding_id: str, draft: ClaimDraft, evidence: tuple[EvidenceSpan, ...], admission: Admission, snapshot: str | None) -> str | None:
        rows = await connection.fetch("""SELECT c.* FROM am_claims c WHERE c.binding_id=$1 AND c.state='active'
            AND c.draft=$2::jsonb AND c.snapshot IS NOT DISTINCT FROM $3
            AND ARRAY(SELECT d.source_id FROM am_claim_sources d WHERE d.claim_id=c.id ORDER BY d.source_id)=$4::text[]
            ORDER BY c.created_at,c.id""", binding_id, _json(draft.model_dump(mode="json", exclude={"evidence"})), snapshot,
            sorted(source.id for source in admission.sources))
        matches = []
        for row in rows:
            try:
                await self._claim_row(connection, binding_id, row["id"], snapshot, False)
            except DomainError as error:
                if error.code != "CLAIM_INELIGIBLE":
                    raise
                continue
            if (await self._claim(connection, row)).evidence == evidence:
                matches.append(row["id"])
        if not matches:
            return None
        canonical = matches[0]
        await connection.execute("UPDATE am_claims SET superseded_by=$2 WHERE id=ANY($1::text[])", matches[1:], canonical)
        await connection.execute("UPDATE am_claims SET superseded_by=NULL WHERE id=$1", canonical)
        if len(matches) > 1:
            retired = await connection.fetch("""UPDATE am_jobs SET state='retracted',error_code='CLAIM_SUPERSEDED',
                generation=generation+1,lease_token=NULL,deadline=NULL WHERE kind='reindex'
                AND state IN ('pending','leased','blocked','failed') AND claim_ids && $1::text[] RETURNING operation_id""", matches[1:])
            if retired:
                epoch = await self._tick(connection)
                await connection.execute("UPDATE am_operations SET state='retracted',error_code='CLAIM_SUPERSEDED',epoch=$2 WHERE id=ANY($1::text[])",
                    [row["operation_id"] for row in retired], epoch)
        return canonical

    async def publish_extraction(self, lease: JobLease, admission: Admission, extraction: Extraction, vectors: list[list[float]], lexical_rows: list[list[str]]) -> Operation:
        if len(vectors) != len(extraction.claims) or len(lexical_rows) != len(extraction.claims):
            raise DomainError("INDEX_LENGTH_INVALID", "Every extracted claim requires exactly one vector and lexical row")
        vector_rows = [self._vector(vector) for vector in vectors]
        if any(len(row) > 2048 or any(not isinstance(token, str) or not token or len(token.encode()) > 1024 for token in row) for row in lexical_rows):
            raise DomainError("LEXICAL_INVALID", "The lexical rows exceed the bounded index contract")
        async with self._tx() as (connection, clock):
            job = await self._publish_fence(connection, clock, lease, admission, "extract")
            if admission.purpose != "extraction":
                raise DomainError("ADMISSION_PURPOSE_INVALID", "Extraction publication requires extraction admission")
            await self._derivation_allowed(connection, tuple(item.id for item in admission.sources))
            sources = {item.id: self._source(await self._source_row(connection, lease.binding_id, item.id, job["snapshot"], True)) for item in admission.sources}
            spans = [self._spans(draft, sources) for draft in extraction.claims]
            vector_revision = self.settings.models.vector_revision()
            claim_ids = []
            entities = set()
            for draft, evidence, vector, tokens in zip(extraction.claims, spans, vector_rows, lexical_rows, strict=True):
                reused = await self._equivalent_claim(connection, lease.binding_id, draft, evidence, admission, job["snapshot"])
                if reused is not None:
                    await connection.execute("UPDATE am_claims SET embedding=$2::public.vector,lexical_tokens=$3,vector_revision=$4 WHERE id=$1",
                        reused, vector, list(dict.fromkeys(tokens)), vector_revision)
                    if reused not in claim_ids:
                        claim_ids.append(reused)
                    entities.update(_entity(entity) for entity in {draft.subject, *draft.entities})
                    continue
                claim_id = _id("claim")
                claim_ids.append(claim_id)
                await connection.execute("""INSERT INTO am_claims(id,binding_id,draft,snapshot,route_revision,embedding,lexical_tokens,valid_from,valid_until,vector_revision,extraction_operation_id)
                    VALUES($1,$2,$3::jsonb,$4,$5,$6::public.vector,$7,$8,$9,$10,$11)""", claim_id, lease.binding_id,
                    _json(draft.model_dump(mode="json", exclude={"evidence"})), job["snapshot"], admission.route_revision, vector,
                    list(dict.fromkeys(tokens)), draft.valid_from, draft.valid_until, vector_revision, lease.operation_id)
                for input_source in admission.sources:
                    await connection.execute("INSERT INTO am_claim_sources(claim_id,source_id,source_revision) VALUES($1,$2,$3)", claim_id, input_source.id, input_source.revision)
                for ordinal, span in enumerate(evidence):
                    await connection.execute("""INSERT INTO am_spans(claim_id,ordinal,source_id,source_revision,byte_start,byte_end,quote)
                        VALUES($1,$2,$3,$4,$5,$6,$7)""", claim_id, ordinal, span.source_id, span.source_revision, span.byte_start, span.byte_end, span.quote)
                for entity in sorted({draft.subject, *draft.entities}):
                    entities.add(_entity(entity))
                    await connection.execute("INSERT INTO am_entities(claim_id,name,search_name) VALUES($1,$2,$3)", claim_id, entity, _entity(entity))
            if not claim_ids:
                return await self._finish_job(connection, lease)
            related = await connection.fetch("""SELECT DISTINCT c.id FROM am_claims c JOIN am_entities e ON e.claim_id=c.id
                WHERE c.binding_id=$1 AND c.state='active' AND c.superseded_by IS NULL
                AND c.snapshot IS NOT DISTINCT FROM $2 AND NOT(c.id=ANY($3::text[])) AND e.search_name=ANY($4::text[])
                AND NOT EXISTS(SELECT 1 FROM am_claim_sources d JOIN am_sources s ON s.id=d.source_id
                    WHERE d.claim_id=c.id AND (s.state<>'active' OR s.revision<>d.source_revision OR s.body IS NULL OR s.binding_id<>c.binding_id OR s.realm<>$6))
                ORDER BY c.id LIMIT $5""", lease.binding_id, job["snapshot"], claim_ids, list(entities), max(0, 32 - len(claim_ids)), self.settings.realm)
            inputs = tuple([*claim_ids, *(row["id"] for row in related)])
            source_rows = await connection.fetch("SELECT DISTINCT source_id FROM am_claim_sources WHERE claim_id=ANY($1::text[]) ORDER BY source_id", list(inputs))
            await connection.execute("UPDATE am_jobs SET state='done',lease_token=NULL,deadline=NULL WHERE id=$1", lease.job_id)
            actor = await self._credential(connection, lease.credential_id)
            await self._enqueue(connection, actor, lease.operation_id, lease.binding_id, "consolidate", tuple(row["source_id"] for row in source_rows), inputs, snapshot=job["snapshot"])
            epoch = await self._tick(connection)
            await connection.execute("UPDATE am_operations SET state='pending',error_code=NULL,epoch=$2 WHERE id=$1", lease.operation_id, epoch)
            return self._operation(await self._operation_row(connection, lease.binding_id, lease.operation_id))

    async def publish_consolidation(self, lease: JobLease, admission: Admission, result: Consolidation) -> Operation:
        async with self._tx() as (connection, clock):
            await self._publish_fence(connection, clock, lease, admission, "consolidate")
            if admission.purpose != "consolidation":
                raise DomainError("ADMISSION_PURPOSE_INVALID", "Consolidation publication requires consolidation admission")
            ids = set(admission.claim_ids)
            claims = {}
            admission_row = await connection.fetchrow("SELECT snapshot FROM am_admissions WHERE id=$1", admission.id)
            for claim_id in ids:
                claims[claim_id] = await self._claim(connection, await self._claim_row(connection, lease.binding_id, claim_id, admission_row["snapshot"], False))
            seen = set()
            for relation in result.relations:
                if relation.left_id == relation.right_id or relation.left_id not in ids or relation.right_id not in ids:
                    raise DomainError("RELATION_INVALID", "Both relation endpoints must belong to the actual input manifest")
                left, right = claims[relation.left_id], claims[relation.right_id]
                if relation.kind == "duplicates":
                    left_source = await self._source_row(connection, lease.binding_id, left.evidence[0].source_id)
                    right_source = await self._source_row(connection, lease.binding_id, right.evidence[0].source_id)
                    fields = ("polarity", "modality", "conditions", "exceptions", "valid_from", "valid_until", "kind")
                    if left.snapshot != right.snapshot or left_source["speaker"] != right_source["speaker"] or any(getattr(left.draft, field) != getattr(right.draft, field) for field in fields):
                        raise DomainError("RELATION_INVALID", "Different conditions, time, polarity or authority cannot be duplicates")
                key = (relation.left_id, relation.right_id, relation.kind)
                if key in seen:
                    raise DomainError("RELATION_INVALID", "A result cannot repeat the same semantic relation")
                seen.add(key)
                # Only an identical complete derivation may reuse a stored artifact.
                # Independent manifests remain separate; logical recall collapses eligible results.
                existing = await connection.fetchval("""SELECT r.id FROM am_relations r WHERE r.binding_id=$1
                    AND r.left_id=$2 AND r.right_id=$3 AND r.kind=$4 AND r.state='active'
                    AND ARRAY(SELECT d.claim_id FROM am_relation_claims d WHERE d.relation_id=r.id ORDER BY d.claim_id)=$5::text[]
                    AND (SELECT jsonb_agg(jsonb_build_array(d.source_id,d.source_revision) ORDER BY d.source_id)
                        FROM am_relation_sources d WHERE d.relation_id=r.id)=$6::jsonb
                    ORDER BY r.id LIMIT 1""", lease.binding_id, relation.left_id, relation.right_id, relation.kind,
                    sorted(admission.claim_ids), _json([[source.id, source.revision] for source in sorted(admission.sources, key=lambda item: item.id)]))
                if existing is not None:
                    continue
                relation_id = _id("relation")
                await connection.execute("INSERT INTO am_relations(id,binding_id,left_id,right_id,kind,reason) VALUES($1,$2,$3,$4,$5,$6)", relation_id, lease.binding_id, relation.left_id, relation.right_id, relation.kind, relation.reason)
                for source in admission.sources:
                    await connection.execute("INSERT INTO am_relation_sources(relation_id,source_id,source_revision) VALUES($1,$2,$3)", relation_id, source.id, source.revision)
                for claim_id in admission.claim_ids:
                    await connection.execute("INSERT INTO am_relation_claims(relation_id,claim_id) VALUES($1,$2)", relation_id, claim_id)
            return await self._finish_job(connection, lease)

    def _reflection_request(self, actor: Principal, command: ContextCommand) -> tuple[str, str]:
        if command.mode != "reflect" or command.idempotency_key is None:
            raise DomainError("REFLECTION_KEY_REQUIRED", "Reflection requires an explicit mode and durable request key")
        binding_id = resolve_binding(actor, command.binding_id)
        return binding_id, canonical_digest(command.model_copy(update={"binding_id": binding_id}))

    async def _reflection_receipt(self, connection, actor: Principal, binding_id: str, command: ContextCommand, digest: str):
        row = await connection.fetchrow("SELECT * FROM am_receipts WHERE principal_id=$1 AND binding_id=$2 AND kind='reflect' AND request_key=$3", actor.id, binding_id, command.idempotency_key)
        if row is not None and row["digest"] != digest:
            manifest = await connection.fetchrow("SELECT claim_ids FROM am_jobs WHERE operation_id=$1 AND kind='reflect'", row["target_id"])
            legacy = canonical_digest({
                "command": command.model_copy(update={"binding_id": binding_id}).model_dump(mode="json"),
                "claim_ids": list(manifest["claim_ids"]) if manifest else [],
            })
            if row["digest"] == legacy:
                await connection.execute("UPDATE am_receipts SET digest=$4 WHERE principal_id=$1 AND binding_id=$2 AND kind='reflect' AND request_key=$3", actor.id, binding_id, command.idempotency_key, digest)
            else:
                raise DomainError("IDEMPOTENCY_CONFLICT", "The request key is already bound to different arguments")
        return row

    async def reflection_receipt(self, actor: Principal, command: ContextCommand) -> Operation | None:
        binding_id, digest = self._reflection_request(actor, command)
        async with self._tx() as (connection, _):
            current = await self._actor(connection, actor, binding_id)
            receipt = await self._reflection_receipt(connection, current, binding_id, command, digest)
            if receipt:
                return self._operation(await self._operation_row(connection, binding_id, receipt["target_id"]))
            return None

    async def submit_reflection(self, actor: Principal, command: ContextCommand, claim_ids: tuple[str, ...]) -> Operation:
        binding_id, digest = self._reflection_request(actor, command)
        async with self._tx() as (connection, _):
            current = await self._actor(connection, actor, binding_id)
            receipt = await self._reflection_receipt(connection, current, binding_id, command, digest)
            if receipt:
                return self._operation(await self._operation_row(connection, binding_id, receipt["target_id"]))
            if not claim_ids or len(claim_ids) > 32 or len(set(claim_ids)) != len(claim_ids):
                raise DomainError("REFLECTION_INPUT_INVALID", "Reflection requires a bounded nonempty actual input manifest")
            inputs = set()
            for claim_id in claim_ids:
                await self._claim_row(connection, binding_id, claim_id, command.snapshot)
                rows = await connection.fetch("SELECT source_id FROM am_claim_sources WHERE claim_id=$1", claim_id)
                inputs.update(row["source_id"] for row in rows)
            await self._queue_capacity(connection)
            operation = await self._new_operation(connection, current, binding_id, "reflect")
            query = CaptureCommand(binding_id=binding_id, idempotency_key=command.idempotency_key,
                origin_key=f"reflection-query:{operation['id']}", body=command.query, speaker="agent_note", kind="query", snapshot=command.snapshot)
            source_id = await self._insert_source(connection, current, query, operation["id"])
            inputs.add(source_id)
            await connection.execute("UPDATE am_operations SET source_id=$2 WHERE id=$1", operation["id"], source_id)
            await self._enqueue(connection, current, operation["id"], binding_id, "reflect", tuple(sorted(inputs)), claim_ids, source_id, command.snapshot)
            await self._save_receipt(connection, current, binding_id, "reflect", command.idempotency_key, digest, operation["id"])
            return self._operation(await self._operation_row(connection, binding_id, operation["id"]))

    async def publish_reflection(self, lease: JobLease, admission: Admission, result: ReflectionDraft) -> Operation:
        from .semantic import validate_reflection
        async with self._tx() as (connection, clock):
            job = await self._publish_fence(connection, clock, lease, admission, "reflect")
            if admission.purpose != "reflection":
                raise DomainError("ADMISSION_PURPOSE_INVALID", "Reflection publication requires reflection admission")
            claims = [await self._claim(connection, await self._claim_row(connection, lease.binding_id, claim_id, job["snapshot"])) for claim_id in admission.claim_ids]
            validate_reflection(result, claims)
            artifact_id = _id("reflection")
            await connection.execute("INSERT INTO am_reflections(id,binding_id,draft) VALUES($1,$2,$3::jsonb)", artifact_id, lease.binding_id, _json(result))
            for source in admission.sources:
                await connection.execute("INSERT INTO am_reflection_sources(reflection_id,source_id,source_revision) VALUES($1,$2,$3)", artifact_id, source.id, source.revision)
            for claim_id in admission.claim_ids:
                await connection.execute("INSERT INTO am_reflection_claims(reflection_id,claim_id) VALUES($1,$2)", artifact_id, claim_id)
            return await self._finish_job(connection, lease, artifact_id=artifact_id)

    async def _deletion_targets(self, connection, binding_id: str, ref: str) -> tuple[list, tuple[tuple[str, str], ...]]:
        kind, row = await self._ref_metadata(connection, binding_id, ref)
        artifacts = () if kind == "source" else ((kind, ref),)
        source_ids = []
        if kind == "source":
            source_ids = [ref]
        elif kind == "claim":
            inputs = await connection.fetch("SELECT source_id FROM am_claim_sources WHERE claim_id=$1", ref)
            canonical = row.get("superseded_by") or ref
            equivalent = await connection.fetch("SELECT id FROM am_claims WHERE binding_id=$1 AND (id=$2 OR superseded_by=$2)", binding_id, canonical)
            claim_ids = [item["id"] for item in equivalent]
            artifacts = tuple(sorted({*artifacts, *(("claim", claim_id) for claim_id in claim_ids), *(("extract_source", item["source_id"]) for item in inputs)}))
            queries = await connection.fetch("SELECT DISTINCT query_source_id FROM am_jobs WHERE binding_id=$1 AND kind='reflect' AND claim_ids && $2::text[] AND query_source_id IS NOT NULL", binding_id, claim_ids)
            source_ids = [item["query_source_id"] for item in queries]
        elif kind == "reflection":
            queries = await connection.fetch("""SELECT DISTINCT j.query_source_id FROM am_jobs j JOIN am_operations o ON o.id=j.operation_id
                WHERE o.artifact_id=$1 AND o.binding_id=$2 AND j.kind='reflect' AND j.query_source_id IS NOT NULL""", ref, binding_id)
            source_ids = [item["query_source_id"] for item in queries]
        elif kind in {"proposal", "rule"}:
            proposal_id = ref if kind == "proposal" else row["proposal_id"]
            proposal = await connection.fetchrow("SELECT * FROM am_proposals WHERE id=$1", proposal_id)
            source_ids = [proposal["source_id"]]
            artifacts = tuple(sorted({*artifacts, ("proposal", proposal_id)}))
        elif kind in {"operation", "feedback"}:
            if kind == "operation" and row["artifact_id"]:
                descendants, derived = await self._deletion_targets(connection, binding_id, row["artifact_id"])
                return descendants, tuple(sorted({*artifacts, *derived}))
            if row["source_id"]:
                source = await connection.fetchrow("SELECT * FROM am_sources WHERE id=$1", row["source_id"])
                if kind == "feedback" or source["operation_id"] == row["id"]:
                    source_ids = [source["id"]]
        sources = await connection.fetch("SELECT id,binding_id,realm,origin_key,state FROM am_sources WHERE id=ANY($1::text[]) ORDER BY id", source_ids)
        if len(sources) != len(set(source_ids)) or any(source["binding_id"] != binding_id or source["realm"] != self.settings.realm for source in sources):
            raise _denied()
        return await self._source_descendants(connection, binding_id, list(sources)), artifacts

    async def _target_sources(self, connection, binding_id: str, ref: str) -> list:
        sources, _ = await self._deletion_targets(connection, binding_id, ref)
        return sources

    async def _correction_authority(self, connection, actor: Principal, binding_id: str, target_ref: str) -> None:
        if actor.role != Role.PRODUCER:
            return
        kind, row = await self._ref_metadata(connection, binding_id, target_ref)
        if kind not in {"source", "claim"}:
            raise _denied()
        source_ids = [row["id"]] if kind == "source" else [
            item["source_id"] for item in await connection.fetch("SELECT source_id FROM am_claim_sources WHERE claim_id=$1", target_ref)
        ]
        if await connection.fetchval("""SELECT EXISTS(SELECT 1 FROM am_proposal_sources d
            WHERE d.source_id=ANY($1::text[])) OR EXISTS(SELECT 1 FROM am_sources s JOIN am_operations o ON o.id=s.operation_id
            WHERE s.id=ANY($1::text[]) AND o.kind NOT IN ('capture','correct'))""", source_ids):
            raise _denied()

    async def _source_descendants(self, connection, binding_id: str, sources: list) -> list:
        rows = await connection.fetch("""WITH RECURSIVE edges(parent_id,child_id) AS (
            SELECT d.source_id,p.source_id FROM am_proposal_sources d JOIN am_proposals p ON p.id=d.proposal_id WHERE p.binding_id=$2
            UNION SELECT unnest(j.source_ids),j.query_source_id FROM am_jobs j
                WHERE j.binding_id=$2 AND j.kind='reflect' AND j.query_source_id IS NOT NULL
        ), affected(id) AS (
            SELECT unnest($1::text[]) UNION SELECT e.child_id FROM affected a JOIN edges e ON e.parent_id=a.id
        ) SELECT s.id,s.binding_id,s.realm,s.origin_key,s.state FROM affected a JOIN am_sources s ON s.id=a.id
            WHERE s.binding_id=$2 AND s.realm=$3 ORDER BY s.id""",
            [source["id"] for source in sources], binding_id, self.settings.realm)
        return list(rows)

    async def _refresh_deletion_floor(self, connection, binding_id: str, sources: list) -> tuple[list, dict, list[dict]]:
        current = await self._source_descendants(connection, binding_id, sources)
        known = {source["id"] for source in sources}
        additional = [source for source in current if source["id"] not in known]
        if additional:
            await self._append_deletion_intent(binding_id, additional)
        journal, entries = await asyncio.to_thread(self.journal._snapshot)
        return current, journal, entries

    async def _apply_floors(self, connection, entries: list[dict]) -> tuple[int, int]:
        tokens = {(kind, token) for entry in entries for kind, field in (("source", "source_tokens"), ("origin", "origin_tokens"), ("artifact", "artifact_tokens")) for token in entry.get(field, [])}
        if tokens:
            await connection.executemany("INSERT INTO am_floors(kind,token) VALUES($1,$2) ON CONFLICT DO NOTHING", sorted(tokens))
        artifact_floors = {token for kind, token in tokens if kind == "artifact"}
        artifacts_retracted = 0
        if artifact_floors:
            tables = {
                "claim": "am_claims", "relation": "am_relations", "reflection": "am_reflections",
                "proposal": "am_proposals", "rule": "am_rules", "operation": "am_operations", "feedback": "am_feedback",
            }
            refs = []
            for kind, table in tables.items():
                refs.extend((kind, row["id"]) for row in await connection.fetch(f"SELECT id FROM {table} WHERE state<>'retracted'"))
            mapped = await asyncio.to_thread(self.journal.artifact_tokens, tuple(refs))
            for kind, table in tables.items():
                ids = [ref for (item_kind, ref), token in mapped.items() if item_kind == kind and token in artifact_floors]
                if ids:
                    await connection.execute(f"UPDATE {table} SET state='retracted' WHERE id=ANY($1::text[]) AND state<>'retracted'", ids)
                    artifacts_retracted += len(ids)
        rows = await connection.fetch("""UPDATE am_sources s SET state='retracted',revision=revision+1 WHERE state='active'
            AND EXISTS(SELECT 1 FROM am_floors f WHERE (f.kind='source' AND f.token=s.source_token) OR (f.kind='origin' AND f.token=s.origin_token))
            RETURNING id""")
        count = len(rows)
        while True:
            await connection.execute("""UPDATE am_proposals p SET state='retracted' WHERE state<>'retracted'
                AND EXISTS(SELECT 1 FROM am_proposal_sources d JOIN am_sources s ON s.id=d.source_id
                    WHERE d.proposal_id=p.id AND (s.state<>'active' OR s.revision<>d.source_revision OR s.body IS NULL))""")
            descendants = await connection.fetch("""UPDATE am_sources s SET state='retracted',revision=revision+1
                WHERE s.state='active' AND EXISTS(SELECT 1 FROM am_proposals p WHERE p.source_id=s.id AND p.state='retracted') RETURNING s.id""")
            count += len(descendants)
            if not descendants:
                break
        await connection.execute("""UPDATE am_claims c SET state='retracted' WHERE state='active'
            AND EXISTS(SELECT 1 FROM am_claim_sources d JOIN am_sources s ON s.id=d.source_id
                WHERE d.claim_id=c.id AND (s.state<>'active' OR s.revision<>d.source_revision OR s.body IS NULL))""")
        await connection.execute("""UPDATE am_claims c SET state='retracted' WHERE c.state='active' AND EXISTS(
            SELECT 1 FROM am_claims canonical WHERE canonical.id=c.superseded_by AND canonical.state<>'active')""")
        await connection.execute("""UPDATE am_relations r SET state='retracted' WHERE state='active' AND (
            EXISTS(SELECT 1 FROM am_relation_sources d JOIN am_sources s ON s.id=d.source_id
                WHERE d.relation_id=r.id AND (s.state<>'active' OR s.revision<>d.source_revision OR s.body IS NULL))
            OR EXISTS(SELECT 1 FROM am_relation_claims d JOIN am_claims c ON c.id=d.claim_id
                WHERE d.relation_id=r.id AND c.state<>'active'))""")
        await connection.execute("""UPDATE am_reflections r SET state='retracted' WHERE state='active' AND (
            EXISTS(SELECT 1 FROM am_reflection_sources d JOIN am_sources s ON s.id=d.source_id
                WHERE d.reflection_id=r.id AND (s.state<>'active' OR s.revision<>d.source_revision OR s.body IS NULL))
            OR EXISTS(SELECT 1 FROM am_reflection_claims d JOIN am_claims c ON c.id=d.claim_id
                WHERE d.reflection_id=r.id AND c.state<>'active'))""")
        await connection.execute("""UPDATE am_rules r SET state='retracted',revision=revision+1 WHERE state='active'
            AND EXISTS(SELECT 1 FROM am_proposals p WHERE p.id=r.proposal_id AND p.state='retracted')""")
        await connection.execute("""UPDATE am_operations o SET state='retracted',error_code='SOURCE_RETRACTED'
            WHERE state<>'retracted' AND (
                EXISTS(SELECT 1 FROM am_sources s WHERE s.id=o.source_id AND s.state<>'active')
                OR EXISTS(SELECT 1 FROM am_reflections r WHERE r.id=o.artifact_id AND r.state='retracted')
                OR EXISTS(SELECT 1 FROM am_proposals p WHERE p.id=o.artifact_id AND p.state='retracted'))""")
        active_sources = await connection.fetch("SELECT id FROM am_sources WHERE state='active'")
        withdrawn = await self._derivation_sources(connection, tuple(row["id"] for row in active_sources)) if artifact_floors else []
        if withdrawn:
            await connection.execute("""WITH invalidated AS (
                UPDATE am_jobs SET state='retracted',generation=generation+1,lease_token=NULL,deadline=NULL,error_code='DERIVATION_RETRACTED'
                WHERE kind='extract' AND state IN ('pending','leased','blocked','failed') AND source_ids && $1::text[]
                RETURNING operation_id
            ) UPDATE am_operations SET state='retracted',error_code='DERIVATION_RETRACTED'
                WHERE id IN (SELECT operation_id FROM invalidated) AND state IN ('accepted','pending','blocked','failed')""", withdrawn)
        replans = await connection.fetch("""SELECT j.*,o.source_id AS original_source_id FROM am_jobs j
            JOIN am_operations o ON o.id=j.operation_id WHERE j.kind='consolidate'
            AND j.state IN ('pending','leased','blocked','failed') AND o.state<>'retracted'
            AND (EXISTS(SELECT 1 FROM am_sources s WHERE s.id=ANY(j.source_ids) AND s.state<>'active')
                OR EXISTS(SELECT 1 FROM am_claims c WHERE c.id=ANY(j.claim_ids) AND c.state<>'active'))""")
        for job in replans:
            claims = []
            for claim_id in job["claim_ids"]:
                try:
                    await self._claim_row(connection, job["binding_id"], claim_id, job["snapshot"], False)
                except DomainError as error:
                    if error.code not in {"CLAIM_INELIGIBLE", "INPUT_INELIGIBLE"}:
                        raise
                    continue
                claims.append(claim_id)
            sources = await connection.fetch("SELECT DISTINCT source_id FROM am_claim_sources WHERE claim_id=ANY($1::text[]) ORDER BY source_id", claims)
            source_ids = sorted({*(row["source_id"] for row in sources), *([job["original_source_id"]] if job["original_source_id"] else [])})
            # Reuse the durable owner, but fence every worker admitted against the old manifest.
            await connection.execute("""UPDATE am_jobs SET state='pending',source_ids=$2,claim_ids=$3,
                generation=generation+1,lease_token=NULL,deadline=NULL,attempts=0,error_code=NULL,
                available_at=clock_timestamp() WHERE id=$1""", job["id"], source_ids, claims)
            epoch = await self._tick(connection)
            await connection.execute("UPDATE am_operations SET state='pending',error_code=NULL,epoch=$2 WHERE id=$1", job["operation_id"], epoch)
        await connection.execute("""WITH retracted_jobs AS (
            UPDATE am_jobs j SET state='retracted',generation=generation+1,lease_token=NULL,deadline=NULL,error_code='INPUT_RETRACTED'
            WHERE state IN ('pending','leased','blocked','failed') AND (
                EXISTS(SELECT 1 FROM am_sources s WHERE s.id=ANY(j.source_ids) AND s.state<>'active')
                OR EXISTS(SELECT 1 FROM am_claims c WHERE c.id=ANY(j.claim_ids) AND c.state<>'active')
                OR EXISTS(SELECT 1 FROM am_operations o WHERE o.id=j.operation_id AND o.state='retracted'))
            RETURNING operation_id
        ) UPDATE am_operations o SET state='failed',error_code='INPUT_RETRACTED'
            WHERE o.id IN (SELECT operation_id FROM retracted_jobs) AND o.state IN ('accepted','pending','blocked','failed')""")
        return count, artifacts_retracted

    async def _reconcile_locked(self, connection, journal: dict, entries: list[dict]) -> int:
        source_tokens = {token for entry in entries for token in entry["source_tokens"]}
        origin_tokens = {token for entry in entries for token in entry["origin_tokens"]}
        descendants = await connection.fetch("""WITH RECURSIVE edges(parent_id,child_id) AS (
            SELECT d.source_id,p.source_id FROM am_proposal_sources d JOIN am_proposals p ON p.id=d.proposal_id
                JOIN am_sources s ON s.id=d.source_id AND s.binding_id=p.binding_id
            UNION SELECT input.source_id,j.query_source_id FROM am_jobs j CROSS JOIN LATERAL unnest(j.source_ids) input(source_id)
                JOIN am_sources s ON s.id=input.source_id AND s.binding_id=j.binding_id
                JOIN am_sources q ON q.id=j.query_source_id AND q.binding_id=j.binding_id
                WHERE j.kind='reflect' AND j.query_source_id IS NOT NULL
        ), affected(id) AS (
            SELECT s.id FROM am_sources s WHERE s.realm=$3 AND (s.source_token=ANY($1::text[]) OR s.origin_token=ANY($2::text[]))
            UNION SELECT e.child_id FROM affected a JOIN edges e ON e.parent_id=a.id
        ) SELECT s.id,s.binding_id,s.origin_key,s.source_token,s.origin_token FROM affected a
            JOIN am_sources s ON s.id=a.id WHERE s.realm=$3 ORDER BY s.binding_id,s.id""",
            sorted(source_tokens), sorted(origin_tokens), self.settings.realm)
        missing = {}
        for source in descendants:
            if source["source_token"] not in source_tokens or source["origin_token"] not in origin_tokens:
                missing.setdefault(source["binding_id"], []).append(source)
        if missing:
            for binding_id, sources in missing.items():
                await self._append_deletion_intent(binding_id, sources)
            latest, latest_entries = await asyncio.to_thread(self.journal._snapshot)
            journal.update(latest)
            entries[:] = latest_entries
        count, artifacts_retracted = await self._apply_floors(connection, entries)
        previous = await connection.fetchval("SELECT journal_head FROM am_clock WHERE singleton")
        if count or artifacts_retracted or previous != journal["head"]:
            await connection.execute("UPDATE am_clock SET journal_head=$1,deletion_generation=deletion_generation+1 WHERE singleton", journal["head"])
            epoch = await self._tick(connection)
            await connection.execute("UPDATE am_operations SET epoch=$1 WHERE state='retracted'", epoch)
        return count

    async def reconcile_journal(self, expected_head: str | None = None) -> dict:
        self._ready = False
        await asyncio.to_thread(self.journal.verify, expected_head)
        async with self._tx(barrier=False) as (connection, clock):
            if clock["deployment_id"] is None:
                raise DomainError("BOOTSTRAP_REQUIRED", "Initialize this explicit deployment first", status=503)
            journal, entries = await asyncio.to_thread(self.journal._snapshot, expected_head)
            count = await self._reconcile_locked(connection, journal, entries)
            epoch = await connection.fetchval("SELECT epoch FROM am_clock WHERE singleton")
        latest = await asyncio.to_thread(self.journal.verify, journal["head"])
        self._ready = True
        return {"head": latest["head"], "sequence": latest["sequence"], "reapplied_sources": count, "epoch": epoch,
                "barrier": "reconciled", "freshness": "expected_head_verified" if expected_head is not None else "local_chain_only",
                "joint_rollback_recency_proven": False}

    async def _deletion_status(self, connection, source_ids: list[str], epoch: int, state: str) -> dict:
        admissions = await connection.fetchval("""SELECT EXISTS(SELECT 1 FROM am_admissions a
            WHERE EXISTS(SELECT 1 FROM jsonb_array_elements(a.sources) input WHERE input->>'id'=ANY($1::text[])))""", source_ids)
        purged = bool(source_ids) and await connection.fetchval("SELECT count(*)=count(*) FILTER (WHERE state='purged' AND body IS NULL) FROM am_sources WHERE id=ANY($1::text[])", source_ids)
        return {"state": state, "epoch": epoch, "logical_retraction": "committed",
                "local_drain": "local_drain_pending" if admissions else "unknown",
                "provider_completion": "provider_completion_unknown",
                "delivered_context_copies": "unknown",
                "physical_purge": "physically_purged" if purged else "not_purged",
                "backup_retention": "unknown"}

    async def _append_deletion_intent(self, binding_id: str, sources: list, artifacts: tuple[tuple[str, str], ...] = ()) -> dict:
        from .domain import EffectState
        try:
            arguments = (binding_id, tuple(source["id"] for source in sources), tuple(source["origin_key"] for source in sources))
            if artifacts:
                return await asyncio.to_thread(self.journal.append, *arguments, artifacts)
            return await asyncio.to_thread(self.journal.append, *arguments)
        except DomainError as error:
            raise DomainError(error.code, error.message, status=error.status, effect=EffectState.UNKNOWN) from error
        except OSError:
            raise DomainError("DELETION_BARRIER", "The deletion intent durability is unknown; reconcile the independent journal", status=503, effect=EffectState.UNKNOWN) from None

    async def _sync_deletion_journal(self) -> None:
        async with self._tx(barrier=False) as (connection, _):
            journal, entries = await asyncio.to_thread(self.journal._snapshot)
            await self._reconcile_locked(connection, journal, entries)
        self._ready = True

    async def _commit_deletion(self, binding_id: str, sources: list, artifacts: tuple[tuple[str, str], ...], correction_intent: tuple[str, str, str] | None = None) -> tuple[list, dict]:
        await self._append_deletion_intent(binding_id, sources, artifacts)
        async with self._tx(barrier=False) as (connection, _):
            sources, journal, entries = await self._refresh_deletion_floor(connection, binding_id, sources)
            await self._reconcile_locked(connection, journal, entries)
            if correction_intent is not None:
                principal_id, key, digest = correction_intent
                await connection.execute("""UPDATE am_receipts SET result=$5::jsonb WHERE principal_id=$1 AND binding_id=$2
                    AND kind='correct_intent' AND request_key=$3 AND digest=$4 AND result->>'state'<>'completed'""",
                    principal_id, binding_id, key, digest, _json({"state": "partial", "logical_retraction": "committed",
                        "replacement_capture": "pending", "retry_same_key": True}))
        self._ready = True
        return sources, journal

    async def _deletion_error(self, error: DomainError) -> DomainError:
        from .domain import EffectState
        try:
            await self._sync_deletion_journal()
        except DomainError:
            return DomainError(error.code, error.message, status=error.status, effect=EffectState.UNKNOWN)
        effect = EffectState.UNKNOWN if error.effect == EffectState.UNKNOWN else EffectState.COMMITTED
        return DomainError(error.code, error.message, status=error.status, effect=effect)

    async def retract(self, actor: Principal, binding_id: str, ref: str, key: str) -> dict:
        digest = canonical_digest({"ref": ref})
        await self._sync_deletion_journal()
        async with self._tx() as (connection, _):
            current = await self._actor(connection, actor, binding_id, (Role.OPERATOR,))
            receipt = await self._receipt(connection, current, binding_id, "retract", key, digest)
            if receipt:
                return dict(_decode(receipt["result"]))
            sources, artifacts = await self._deletion_targets(connection, binding_id, ref)
            intent = await self._receipt(connection, current, binding_id, "retract_intent", key, digest)
            if intent is None:
                await self._save_receipt(connection, current, binding_id, "retract_intent", key, digest, ref, {"state": "pending"})
        try:
            sources, journal = await asyncio.shield(self._commit_deletion(binding_id, sources, artifacts))
            async with self._tx() as (connection, _):
                current = await self._actor(connection, actor, binding_id, (Role.OPERATOR,))
                receipt = await self._receipt(connection, current, binding_id, "retract", key, digest)
                if receipt:
                    return dict(_decode(receipt["result"]))
                epoch = await connection.fetchval("SELECT epoch FROM am_clock WHERE singleton")
                result = await self._deletion_status(connection, [source["id"] for source in sources], epoch, "retracted")
                result.update(ref=ref, head=journal["head"])
                await self._save_receipt(connection, current, binding_id, "retract", key, digest, ref, result)
                return result
        except DomainError as error:
            raise await self._deletion_error(error) from error

    async def _correction_failure(self, actor: Principal, binding_id: str, key: str, digest: str, sources: list, artifacts: tuple[tuple[str, str], ...], error: DomainError) -> DomainError:
        logical_retraction = "unknown"
        try:
            await self._sync_deletion_journal()
            source_tokens = [await asyncio.to_thread(self.journal.source_token, source["id"]) for source in sources]
            origin_tokens = [await asyncio.to_thread(self.journal.origin_token, binding_id, source["origin_key"]) for source in sources]
            artifact_tokens = list((await asyncio.to_thread(self.journal.artifact_tokens, artifacts)).values())
            async with self._tx(barrier=False) as (connection, _):
                completed = await self._receipt(connection, actor, binding_id, "correct", key, digest)
                if completed is not None:
                    await self._operation_row(connection, binding_id, completed["target_id"])
                    return DomainError(error.code, "The complete correction has a durable receipt; replay the same original request key to read its operation",
                        status=error.status, effect=EffectState.COMMITTED)
                floors = await connection.fetchval("""SELECT count(*) FROM am_floors WHERE
                    (kind='source' AND token=ANY($1::text[])) OR (kind='origin' AND token=ANY($2::text[]))
                    OR (kind='artifact' AND token=ANY($3::text[]))""", source_tokens, origin_tokens, artifact_tokens)
                expected = len(set(source_tokens)) + len(set(origin_tokens)) + len(set(artifact_tokens))
                if expected and floors == expected:
                    logical_retraction = "committed"
                result = {"state": "partial" if logical_retraction == "committed" else "pending_unknown",
                    "logical_retraction": logical_retraction, "replacement_capture": "pending_or_unknown",
                    "retry_same_key": True, "error_code": error.code}
                await connection.execute("""UPDATE am_receipts SET result=$5::jsonb WHERE principal_id=$1 AND binding_id=$2
                    AND kind='correct_intent' AND request_key=$3 AND digest=$4 AND result->>'state'<>'completed'""",
                    actor.id, binding_id, key, digest, _json(result))
        except (DomainError, OSError):
            pass
        code = "CORRECTION_PARTIAL" if logical_retraction == "committed" else "CORRECTION_UNKNOWN"
        return DomainError(code, "Correction completion is unconfirmed; inspect the pending intent and retry the same original request key",
            status=error.status, effect=EffectState.UNKNOWN)

    async def correct(self, actor: Principal, binding_id: str, target_ref: str, command: CaptureCommand) -> Operation:
        if command.binding_id != binding_id or command.injected or command.speaker == "memory" or len(command.body.encode()) > self.settings.max_capture_bytes or "<agents-memory-context" in command.body or "[agents-memory:injected]" in command.body or BOUNDED_CONTEXT_MARKER in command.body:
            raise DomainError("CORRECTION_INVALID", "An explicit correction requires new eligible evidence in the same project")
        corrected = command.model_copy(update={"kind": "correction"})
        payload = {"target_ref": target_ref, "command": corrected.model_dump(mode="json")}
        digest = canonical_digest(payload)
        await self._sync_deletion_journal()
        async with self._tx() as (connection, _):
            current = await self._actor(connection, actor, binding_id, (Role.PRODUCER, Role.OPERATOR))
            receipt = await self._receipt(connection, current, binding_id, "correct", corrected.idempotency_key, digest)
            if receipt:
                return self._operation(await self._operation_row(connection, binding_id, receipt["target_id"]))
            intent = await self._receipt(connection, current, binding_id, "correct_intent", corrected.idempotency_key, digest)
            await self._correction_authority(connection, current, binding_id, target_ref)
            sources, artifacts = await self._deletion_targets(connection, binding_id, target_ref)
            origin_token = await asyncio.to_thread(self.journal.origin_token, binding_id, corrected.origin_key)
            origin_digest = canonical_digest(corrected.model_dump(mode="json", exclude={"idempotency_key"}))
            original = await connection.fetchrow("SELECT origin_digest,state,body IS NOT NULL AS has_body FROM am_sources WHERE origin_token=$1 AND binding_id=$2", origin_token, binding_id)
            if original and original["origin_digest"] != origin_digest:
                raise DomainError("ORIGIN_CONFLICT", "The origin event is already bound to different evidence")
            if any(source["origin_key"] == corrected.origin_key for source in sources) or await connection.fetchval(
                "SELECT EXISTS(SELECT 1 FROM am_floors WHERE kind='origin' AND token=$1)", origin_token
            ) or (original is not None and (original["state"] != "active" or not original["has_body"])):
                raise DomainError("CORRECTION_ORIGIN_CONFLICT", "A correction requires a new eligible origin event")
            reservation = await connection.fetchrow("SELECT * FROM am_origin_reservations WHERE origin_token=$1", origin_token)
            if reservation is not None:
                if reservation["origin_digest"] != origin_digest:
                    raise DomainError("ORIGIN_CONFLICT", "The origin event is already bound to different evidence")
                if (reservation["binding_id"], reservation["principal_id"], reservation["request_key"], reservation["intent_digest"]) != (binding_id, current.id, corrected.idempotency_key, digest):
                    raise DomainError("ORIGIN_RESERVED", "This origin belongs to another pending correction")
            else:
                await connection.execute("""INSERT INTO am_origin_reservations(origin_token,binding_id,origin_digest,principal_id,request_key,intent_digest)
                    VALUES($1,$2,$3,$4,$5,$6)""", origin_token, binding_id, origin_digest, current.id, corrected.idempotency_key, digest)
            if intent is None:
                if original is None:
                    await self._queue_capacity(connection)
                await self._save_receipt(connection, current, binding_id, "correct_intent", corrected.idempotency_key, digest, target_ref,
                    {"state": "pending_unknown", "logical_retraction": "unknown", "replacement_capture": "pending", "retry_same_key": True})
        try:
            await asyncio.shield(self._commit_deletion(binding_id, sources, artifacts, (current.id, corrected.idempotency_key, digest)))
            async with self._tx() as (connection, _):
                current = await self._actor(connection, actor, binding_id, (Role.PRODUCER, Role.OPERATOR))
                return await self._capture(connection, current, corrected, "correct", payload)
        except DomainError as error:
            raise await self._correction_failure(current, binding_id, corrected.idempotency_key, digest, sources, artifacts, error) from error
        except asyncio.CancelledError:
            await asyncio.shield(self._correction_failure(current, binding_id, corrected.idempotency_key, digest, sources, artifacts,
                DomainError("CORRECTION_CANCELLED", "Correction response was cancelled", effect=EffectState.UNKNOWN)))
            raise

    async def purge(self, actor: Principal, binding_id: str, ref: str, key: str) -> dict:
        digest = canonical_digest({"ref": ref})
        async with self._tx() as (connection, _):
            current = await self._actor(connection, actor, binding_id, (Role.OPERATOR,))
            receipt = await self._receipt(connection, current, binding_id, "purge", key, digest)
            if receipt:
                return dict(_decode(receipt["result"]))
            kind, target = await self._ref_metadata(connection, binding_id, ref)
            sources = await self._target_sources(connection, binding_id, ref)
            if target.get("state") not in {"retracted", "purged"} or any(source["state"] == "active" for source in sources):
                raise DomainError("RETRACTION_REQUIRED", "Commit logical retraction before physical purge")
            source_ids = [source["id"] for source in sources]
            while True:
                proposals = await connection.fetch("""SELECT DISTINCT p.source_id FROM am_proposals p
                    JOIN am_proposal_sources d ON d.proposal_id=p.id WHERE d.source_id=ANY($1::text[]) AND p.state='retracted'""", source_ids)
                expanded = sorted({*source_ids, *(row["source_id"] for row in proposals)})
                if expanded == source_ids:
                    break
                source_ids = expanded
            await connection.execute("UPDATE am_sources SET body=NULL,state='purged' WHERE id=ANY($1::text[]) AND state<>'active'", source_ids)
            claims = await connection.fetch("SELECT DISTINCT claim_id FROM am_claim_sources WHERE source_id=ANY($1::text[])", source_ids)
            claim_ids = sorted({*(row["claim_id"] for row in claims), *([ref] if kind == "claim" else [])})
            await connection.execute("UPDATE am_claims SET draft=NULL,embedding=NULL,lexical_tokens='{}',state='retracted' WHERE id=ANY($1::text[])", claim_ids)
            await connection.execute("UPDATE am_spans SET quote=NULL WHERE claim_id=ANY($1::text[])", claim_ids)
            await connection.execute("DELETE FROM am_entities WHERE claim_id=ANY($1::text[])", claim_ids)
            await connection.execute("""UPDATE am_relations SET reason=NULL,state='retracted' WHERE id IN
                (SELECT relation_id FROM am_relation_sources WHERE source_id=ANY($1::text[]))""", source_ids)
            await connection.execute("""UPDATE am_reflections SET draft=NULL,state='retracted' WHERE id IN
                (SELECT reflection_id FROM am_reflection_sources WHERE source_id=ANY($1::text[]))""", source_ids)
            await connection.execute("""UPDATE am_relations SET reason=NULL WHERE state='retracted' AND
                (id=$1 OR id IN (SELECT relation_id FROM am_relation_claims WHERE claim_id=ANY($2::text[])))""", ref, claim_ids)
            await connection.execute("""UPDATE am_reflections SET draft=NULL WHERE state='retracted' AND
                (id=$1 OR id IN (SELECT reflection_id FROM am_reflection_claims WHERE claim_id=ANY($2::text[])))""", ref, claim_ids)
            await connection.execute("""UPDATE am_proposals SET selector='{}',exceptions='[]',state='retracted' WHERE id IN
                (SELECT proposal_id FROM am_proposal_sources WHERE source_id=ANY($1::text[]))""", source_ids)
            await connection.execute("UPDATE am_receipts SET result=result-'request' WHERE binding_id=$1 AND kind='reflect' AND result ? 'request'", binding_id)
            epoch = await self._tick(connection)
            result = await self._deletion_status(connection, source_ids, epoch, "purged")
            result.update(ref=ref, database_body_rows_removed=len(source_ids), database_claim_rows_scrubbed=len(claim_ids),
                          storage_media_erasure="unknown", wal_and_backup_erasure="unknown")
            await self._save_receipt(connection, current, binding_id, "purge", key, digest, ref, result)
            return result

    async def delivery(self, actor: Principal, binding_id: str, admissions: tuple[Admission, ...], rule_versions: tuple[tuple[str, int, str], ...], snapshot: str | None = None, relation_ids: tuple[str, ...] = ()) -> dict:
        if len(admissions) > 16 or len(rule_versions) > 1024 or len(relation_ids) > 128 or len(set(relation_ids)) != len(relation_ids):
            raise DomainError("MANIFEST_TOO_LARGE", "The final delivery manifest is too large")
        async with self._tx() as (connection, clock):
            current = await self._actor(connection, actor, binding_id)
            for admission in admissions:
                if admission.binding_id != binding_id or admission.credential_id != current.credential_id:
                    raise _denied()
                try:
                    row = await self._recheck(connection, clock, admission)
                except DomainError:
                    raise DomainError("CONTEXT_STALE", "The delivered actual inputs are no longer current") from None
                if row["snapshot"] != snapshot:
                    raise DomainError("CONTEXT_STALE", "The delivery snapshot differs from its admitted inputs")
            for relation_id in relation_ids:
                try:
                    await self._relation_row(connection, binding_id, relation_id, snapshot)
                except DomainError:
                    raise DomainError("CONTEXT_STALE", "A delivered relation or its complete input lineage is no longer current") from None
            rows = await connection.fetch("""SELECT r.* FROM am_rules r JOIN am_rule_targets t ON t.rule_id=r.id
                WHERE t.binding_id=$1 AND r.state='active' ORDER BY r.id""", binding_id)
            expected = []
            for row in rows:
                rule = await self._active_rule(connection, row)
                expected.append((rule.id, rule.revision, rule.digest))
            if tuple(sorted(expected)) != tuple(sorted(rule_versions)) or len({item[0] for item in rule_versions}) != len(rule_versions):
                raise DomainError("CONTEXT_STALE", "The complete active rule snapshot changed before delivery")
            return {"epoch": clock["epoch"], "stats": await self._stats(connection, binding_id, clock["epoch"], snapshot)}

    async def recover_after_restore(self, owner_id: str, operator_token: str, expected_head: str) -> Principal:
        if self.settings.migrator_dsn is None or self.settings.database_dsn != self.settings.migrator_dsn:
            raise DomainError("PRIVATE_RECOVERY_REQUIRED", "Restore recovery requires the explicit private operator connection", status=403)
        if not re.fullmatch(r"[a-f0-9]{64}", expected_head):
            raise DomainError("DELETION_BARRIER", "Restore recovery requires an externally retained deletion head", status=503)
        token_hash = self._token_hash(operator_token)
        credential_id = _id("credential")
        Principal(id=owner_id, credential_id=credential_id, realm=self.settings.realm, role=Role.OPERATOR, generation=1, bindings=())
        self._ready = False
        await asyncio.to_thread(self.journal.verify, expected_head)
        async with self._tx(barrier=False) as (connection, clock):
            if clock["deployment_id"] != self.settings.deployment_id or clock["realm"] != self.settings.realm:
                raise _denied()
            owner = await connection.fetchval("SELECT EXISTS(SELECT 1 FROM am_credentials WHERE principal_id=$1 AND realm=$2)", owner_id, self.settings.realm)
            if not owner:
                raise _missing()
            if await connection.fetchval("SELECT EXISTS(SELECT 1 FROM am_credentials WHERE token_hash=$1)", token_hash):
                raise DomainError("TOKEN_CONFLICT", "Restore recovery requires a freshly generated operator credential")
            journal, entries = await asyncio.to_thread(self.journal._snapshot, expected_head)
            await self._reconcile_locked(connection, journal, entries)
            await connection.execute("UPDATE am_credentials SET active=false,generation=generation+1")
            await connection.execute("UPDATE am_rules SET state='retracted',revision=revision+1 WHERE state='active'")
            epoch = await self._tick(connection)
            await connection.execute("UPDATE am_routes SET enabled=false,epoch=$1", epoch)
            await connection.execute("""UPDATE am_jobs SET state='blocked',error_code='AUTH_REISSUE_REQUIRED',generation=generation+1,
                lease_token=NULL,deadline=NULL WHERE state IN ('pending','leased','blocked','failed')""")
            await connection.execute("""UPDATE am_operations o SET state='blocked',error_code='AUTH_REISSUE_REQUIRED',epoch=$1
                WHERE state IN ('accepted','pending','blocked','failed') AND EXISTS(
                    SELECT 1 FROM am_jobs j WHERE j.operation_id=o.id AND j.state='blocked')""", epoch)
            await connection.execute("INSERT INTO am_credentials(id,principal_id,realm,role,token_hash) VALUES($1,$2,$3,'operator',$4)", credential_id, owner_id, self.settings.realm, token_hash)
            bindings = await connection.fetch("SELECT id FROM am_bindings WHERE owner_id=$1 AND realm=$2 ORDER BY id", owner_id, self.settings.realm)
            if bindings:
                await connection.executemany("INSERT INTO am_grants(credential_id,binding_id) VALUES($1,$2)", [(credential_id, binding["id"]) for binding in bindings])
            actor = await self._credential(connection, credential_id)
        try:
            await asyncio.to_thread(self.journal.verify, journal["head"])
        except DomainError as error:
            from .domain import EffectState
            raise DomainError(error.code, error.message, status=error.status, effect=EffectState.UNKNOWN) from error
        self._ready = True
        return actor
