from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import unicodedata
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import asyncpg

from .config import Settings, resolve_binding
from .constants import BOUNDED_CONTEXT_MARKER, HOST_CONTEXT_BYTES
from .database import CANDIDATE_VECTOR_SQL, INSTALLED_VECTOR_SQL, require_server
from .domain import (
    ActiveRule,
    Binding,
    BindingRelocation,
    CaptureCommand,
    CaptureCoverage,
    Claim,
    ClaimDraft,
    ClaimMeaning,
    ContextCommand,
    DomainError,
    EffectState,
    EvidenceSpan,
    FeedbackCommand,
    NonmodelAdmission,
    Operation,
    Principal,
    Quote,
    ReflectionDraft,
    Relation,
    RevisionRef,
    Role,
    RuleApproval,
    RuleProposal,
    RuleScope,
    Selector,
    Source,
    SourcePointer,
    canonical_digest,
    reject_source_secrets,
)
from .journal import DeletionJournal
from .migrations import MIGRATION, MIGRATIONS
from .selection import (
    ClaimJudgmentCommand,
    RecordInput,
    RejectionComparison,
    SourceSelectionCommand,
    resolve_selection,
    selection_contract_revision,
    source_window,
)

REJECTION_CANDIDATE_LIMIT = 8
REJECTION_INDEX_TOKEN_LIMIT = 16
REJECTION_HISTORY_EXAMINED_LIMIT = 32
REJECTION_IDENTITY_EXAMINED_LIMIT = 32
REJECTION_DISCLOSURE_NODE_LIMIT = 256
REJECTION_DISCLOSURE_DEPTH_LIMIT = 32
REJECTION_REVIEW_LIMIT = 16
_DISCLOSURE_ERRORS = frozenset({
    "NOT_FOUND", "SOURCE_INELIGIBLE", "SNAPSHOT_INELIGIBLE", "INPUT_INELIGIBLE",
    "CLAIM_INELIGIBLE", "RELATION_INELIGIBLE", "RULE_INELIGIBLE",
    "REJECTION_REFERENCE_INVALID",
})
_DISCLOSURE_CONTEXT: ContextVar[tuple[tuple[str, ...], list[int], dict] | None] = ContextVar(
    "rejection_disclosure_context", default=None,
)

_HEALTH_REUSE_SQL = """
    NOT EXISTS(SELECT 1 FROM am_claim_health h WHERE h.claim_id=c.id AND
        (h.claim_revision<>c.revision OR h.operator_review='reject' OR h.needs_review
            OR h.restore_unknown OR h.freshness='stale'))
    AND NOT EXISTS(SELECT 1 FROM am_claim_sources d JOIN am_sources s ON s.id=d.source_id
        WHERE d.claim_id=c.id AND s.health_restore_revision=d.source_revision
        AND NOT EXISTS(SELECT 1 FROM am_claim_health h WHERE h.claim_id=c.id
            AND h.claim_revision=c.revision AND h.operator_review='accept' AND NOT h.restore_unknown))
    AND NOT EXISTS(SELECT 1 FROM am_code_links l
        LEFT JOIN am_code_observations o ON o.id=l.observation_id
        LEFT JOIN am_code_workspaces w ON w.id=o.workspace_id
        LEFT JOIN am_credentials p ON p.id=w.producer_credential_id
        LEFT JOIN am_bindings b ON b.id=w.binding_id
        LEFT JOIN am_health_policies hp ON hp.binding_id=w.binding_id
        WHERE l.claim_id=c.id AND l.claim_revision=c.revision AND
            (o.id IS NULL OR o.state<>'active' OR o.metadata IS NULL OR o.binding_id<>c.binding_id
             OR w.state<>'active' OR w.binding_id<>c.binding_id OR w.revision<>o.workspace_revision
             OR hp.enabled IS NOT TRUE
             OR w.binding_revision<>b.revision OR NOT p.active OR p.generation<>w.producer_generation
             OR p.role<>'producer' OR p.realm<>b.realm
             OR NOT EXISTS(SELECT 1 FROM am_grants g WHERE g.credential_id=p.id AND g.binding_id=c.binding_id)
             OR o.metadata->>'status'<>'present'
             OR (o.symbol_name<>'' AND COALESCE(o.metadata->'symbol','null'::jsonb)='null'::jsonb)))
"""
_CODE_CONTEXT_SQL = """NOT EXISTS(SELECT 1 FROM am_code_links l
    JOIN am_code_observations o ON o.id=l.observation_id
    WHERE l.claim_id=c.id AND l.claim_revision=c.revision
        AND ({workspace}::text IS NULL OR o.workspace_id<>{workspace}))"""


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


def _connection_failed() -> DomainError:
    return DomainError("DATABASE_UNAVAILABLE", "The authority connection failed; reconcile the durable receipt before retry",
        status=503, effect=EffectState.UNKNOWN)


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
        self._journal_check: asyncio.Task[dict] | None = None

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
                require_server(
                    await connection.fetchval("SHOW server_version_num"),
                    await connection.fetchval(INSTALLED_VECTOR_SQL),
                )
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

    async def _verified_journal(self) -> dict:
        """Share the one live verification, including after a caller's timeout."""
        check = self._journal_check
        if check is None or check.done():
            check = asyncio.create_task(asyncio.to_thread(self.journal.verify))
            self._journal_check = check
        return await asyncio.shield(check)

    async def readiness(self, *, timeout: float = 2) -> dict:
        """Round-trip identity and the deletion barrier without spawning work per probe."""
        result = {
            "ready": False, "db_ready": False,
            "deployment_id": self.settings.deployment_id, "realm": self.settings.realm,
        }
        try:
            async with asyncio.timeout(timeout):
                async with self._tx(lock=False) as (_, clock):
                    if clock["deployment_id"] != self.settings.deployment_id or clock["realm"] != self.settings.realm:
                        raise DomainError("AUTHORITY_UNAVAILABLE", "The authority identity does not match", status=503)
        except Exception:
            return result
        return {**result, "ready": True, "db_ready": True}

    async def close(self) -> None:
        # Cancelling a probe must not cancel its thread and release ownership.
        # Drain that owned work before the store disappears; failure remains
        # visible to transaction/readiness callers, not a shutdown operation.
        if self._journal_check is not None:
            await asyncio.gather(self._journal_check, return_exceptions=True)
            self._journal_check = None
        if self.pool is not None:
            await self.pool.close()
            self.pool = None
        self._ready = False

    @asynccontextmanager
    async def _tx(self, barrier: bool = True, lock: bool = True) -> AsyncIterator[tuple[asyncpg.Connection, asyncpg.Record]]:
        """Serialize writers on the global clock; ``lock=False`` is a read-only transaction that never waits for it."""
        if self.pool is None:
            raise DomainError("STORE_CLOSED", "The authority connection is not open", status=503)
        journal = await self._verified_journal() if barrier else None
        try:
            connection = await self.pool.acquire(timeout=self.settings.pool_acquire_timeout_seconds)
        except TimeoutError:
            raise DomainError("DATABASE_BUSY", "No authority connection became available before the deadline; retry later", status=503) from None
        except (asyncpg.PostgresConnectionError, asyncpg.InterfaceError, OSError):
            raise _connection_failed() from None
        try:
            async with connection.transaction(readonly=not lock):
                clock = await connection.fetchrow("SELECT * FROM am_clock WHERE singleton FOR UPDATE" if lock else "SELECT * FROM am_clock WHERE singleton")
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
            raise _connection_failed() from None
        finally:
            await self.pool.release(connection)

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

    @asynccontextmanager
    async def operator_authority(self, actor: Principal) -> AsyncIterator[Principal]:
        """Serialize short synchronous file effects with revocation; never await other work inside."""
        async with self._tx() as (connection, _):
            yield await self._actor(connection, actor, roles=(Role.OPERATOR,))

    @classmethod
    async def preflight_initialization(cls, settings: Settings, operator_token: str, owner_id: str, *, resume: bool) -> Principal | None:
        store = cls(settings, DeletionJournal(settings.journal_dir, settings.deployment_id))
        token_hash = store._token_hash(operator_token)
        dsn, options = _connection_arguments(settings)
        try:
            connection = await asyncpg.connect(dsn, timeout=30, command_timeout=30, **options)
            try:
                async with connection.transaction(readonly=True):
                    require_server(await connection.fetchval("SHOW server_version_num"), await connection.fetchval(CANDIDATE_VECTOR_SQL))
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
                        "am_jobs", "am_admissions", "am_origin_reservations",
                        "am_selection_policies", "am_source_selections", "am_selection_sources",
                        "am_pending_judgments", "am_retired_jobs", "am_claim_judgments",
                        "am_rejection_evidence", "am_rejection_tokens",
                        "am_health_policies", "am_code_workspaces", "am_code_observations", "am_claim_health",
                        "am_code_links", "am_health_events", "am_session_observations"}
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

    async def resolve_issued_credential(self, actor: Principal, token: str, *, role: Role) -> str | None:
        """Resolve an uncertain issuance after its clock-locked commit or rollback."""
        token_hash = self._token_hash(token)
        async with self._tx() as (connection, _):
            current = await self._actor(connection, actor, roles=(Role.OPERATOR,))
            row = await connection.fetchrow(
                "SELECT id,role FROM am_credentials WHERE token_hash=$1 AND active AND realm=$2",
                token_hash, current.realm,
            )
            if row is None:
                return None
            if row["role"] != role:
                raise _denied()
            return row["id"]

    async def authenticate(self, token: str, roles: tuple[Role, ...] | None = None) -> Principal:
        token_hash = self._token_hash(token)
        # Every mutating transaction rechecks the credential under the clock lock through _actor.
        async with self._tx(barrier=False, lock=False) as (connection, _):
            credential = await connection.fetchval("SELECT id FROM am_credentials WHERE token_hash=$1 AND active AND realm=$2", token_hash, self.settings.realm)
            if credential is None:
                raise DomainError("AUTH_DENIED", "The current credential is unavailable", status=401)
            actor = await self._credential(connection, credential)
            if roles is not None and actor.role not in roles:
                raise _denied()
            return actor

    async def authenticate_external(
        self, credential_id: str, generation: int, roles: tuple[Role, ...] | None = None,
    ) -> Principal:
        async with self._tx(barrier=False, lock=False) as (connection, _):
            actor = await self._credential(connection, credential_id)
            if type(generation) is not int or actor.generation != generation:
                raise DomainError("AUTH_DENIED", "The current credential generation is unavailable", status=401)
            if roles is not None and actor.role not in roles:
                raise _denied()
            return actor

    async def client_bootstrap(self, actor: Principal, binding_id: str) -> tuple[Principal, int]:
        async with self._tx(lock=False) as (connection, _):
            current = await self._actor(connection, actor, binding_id, (Role.AGENT, Role.PRODUCER))
            if current.bindings != (binding_id,):
                raise _denied()
            revision = await connection.fetchval(
                "SELECT revision FROM am_bindings WHERE id=$1 AND realm=$2", binding_id, current.realm,
            )
            if revision is None:
                raise _denied()
            return current, revision

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

    async def grant_binding(self, actor: Principal, credential_id: str, binding_id: str) -> Principal:
        """Extend one active agent credential this operator issued to a project the operator holds."""
        async with self._tx() as (connection, _):
            current = await self._actor(connection, actor, binding_id, roles=(Role.OPERATOR,))
            role = await connection.fetchval("""SELECT role FROM am_credentials WHERE id=$1 AND realm=$2
                AND principal_id=$3 AND active""", credential_id, current.realm, current.id)
            if role != Role.AGENT.value:
                raise _denied()
            await connection.execute("INSERT INTO am_grants(credential_id,binding_id) VALUES($1,$2) ON CONFLICT DO NOTHING", credential_id, binding_id)
            await self._tick(connection)
            return await self._credential(connection, credential_id)

    async def authorize(self, actor: Principal, binding_id: str) -> Principal:
        """Read-only grant check for responses that carry no project data."""
        async with self._tx(lock=False) as (connection, _):
            return await self._actor(connection, actor, binding_id, (Role.AGENT, Role.OPERATOR, Role.APPROVER))

    async def pending_snapshots(self, actor: Principal, binding_id: str) -> tuple[str | None, ...]:
        async with self._tx(lock=False) as (connection, _):
            await self._actor(connection, actor, binding_id, (Role.AGENT, Role.OPERATOR))
            rows = await connection.fetch("""SELECT DISTINCT snapshot FROM am_pending_judgments WHERE binding_id=$1
                AND state='pending' AND kind IN ('source_selection','cleanup','health')
                ORDER BY snapshot NULLS FIRST LIMIT 64""", binding_id)
            return tuple(row["snapshot"] for row in rows)

    async def decided_ranges(
        self, actor: Principal, binding_id: str, source_id: str, source_revision: int, snapshot: str | None,
    ) -> tuple[tuple[int, int], ...]:
        """Byte ranges already holding a complete remember/discard, matching pending resolution."""
        async with self._tx(lock=False) as (connection, _):
            await self._actor(connection, actor, binding_id, (Role.AGENT, Role.OPERATOR))
            rows = await self._current_selection_rows(connection, binding_id, snapshot)
            return tuple(
                (row["byte_start"], row["byte_end"]) for row in rows
                if row["source_id"] == source_id and row["source_revision"] == source_revision
                and row["label"] in {"remember", "discard"} and row["coverage"] == "complete_window")

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
        return Operation(id=row["id"], binding_id=row["binding_id"], kind=row["kind"], state=row["state"], source_id=row["source_id"], artifact_id=row["artifact_id"], successor_operation_id=row["successor_operation_id"], error_code=row["error_code"], epoch=row["epoch"],
            source_pointer=SourcePointer.model_validate(_decode(row["source_pointer"])) if row.get("source_pointer") else None,
            capture_disposition=row.get("capture_disposition"), selection_label=row.get("selection_label"))

    async def _operation_row(self, connection, binding_id: str, operation_id: str):
        row = await connection.fetchrow("SELECT * FROM am_operations WHERE id=$1 AND binding_id=$2", operation_id, binding_id)
        if row is None:
            raise _missing()
        return row

    async def _new_operation(self, connection, actor, binding_id, kind, state="accepted", error=None):
        operation_id = _id("operation")
        epoch = await self._tick(connection)
        return await connection.fetchrow("""INSERT INTO am_operations(id,binding_id,credential_id,kind,state,error_code,epoch,actor_generation)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8) RETURNING *""",
            operation_id, binding_id, actor.credential_id, kind, state, error, epoch, actor.generation)

    async def _insert_source(
        self, connection, actor, command: CaptureCommand, operation_id: str,
    ) -> str:
        source_id = _id("source")
        independent_work = command.speaker not in {"agent_note", "memory"}
        if independent_work:
            backlog = await connection.fetchval(
                """SELECT count(*) FROM am_pending_judgments p
                   WHERE p.binding_id=$1 AND p.kind='source_selection'
                     AND p.state IN ('pending','held')
                     AND EXISTS(
                         SELECT 1 FROM am_sources s
                         WHERE s.id=ANY(p.source_ids) AND s.binding_id=p.binding_id
                           AND s.state='active' AND s.body IS NOT NULL
                           AND s.speaker NOT IN ('memory','agent_note')
                     )""",
                command.binding_id,
            )
            if backlog >= self.settings.queue_limit:
                raise DomainError(
                    "QUEUE_FULL", "The project's bounded source-selection backlog is full",
                    status=429,
                )
        source_token = await asyncio.to_thread(self.journal.source_token, source_id)
        origin_token = await asyncio.to_thread(
            self.journal.origin_token, command.binding_id, command.origin_key,
        )
        value = command.digest_payload("idempotency_key")
        await connection.execute(
            """INSERT INTO am_sources(
                   id,binding_id,realm,body,speaker,kind,origin_key,origin_token,
                   source_token,origin_digest,root_run_id,agent_path,snapshot,
                   event_time,operation_id,producer_generation,capture_coverage
               ) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17::jsonb)""",
            source_id, command.binding_id, actor.realm, command.body, command.speaker,
            command.kind, command.origin_key, origin_token, source_token,
            canonical_digest(value), command.root_run_id, command.agent_path,
            command.snapshot, command.event_time, operation_id, actor.generation,
            _json(command.coverage),
        )
        if independent_work:
            await connection.execute(
                """INSERT INTO am_pending_judgments(
                       id,binding_id,kind,source_ids,snapshot
                   ) VALUES($1,$2,'source_selection',$3,$4)""",
                _id("pending"), command.binding_id, [source_id], command.snapshot,
            )
            await self._refresh_late_session_capture(connection, command.binding_id, command.origin_key)
        return source_id

    async def _point_operation(self, connection, operation_id: str, source_id: str) -> None:
        source = self._source(await self._source_row(connection, await connection.fetchval("SELECT binding_id FROM am_operations WHERE id=$1", operation_id), source_id))
        revision = await connection.fetchval("SELECT revision FROM am_bindings WHERE id=$1", source.binding_id)
        pointer = SourcePointer(source_id=source.id, source_revision=source.revision,
            binding_id=source.binding_id, binding_revision=revision, snapshot=source.snapshot,
            source_speaker=source.speaker, source_event_time=source.event_time,
            source_recorded_at=source.recorded_at, byte_length=len(source.body.encode()), coverage=source.coverage)
        await connection.execute("UPDATE am_operations SET source_id=$2,source_pointer=$3::jsonb,capture_disposition='captured' WHERE id=$1", operation_id, source_id, _json(pointer))

    async def _capture(self, connection, actor, command: CaptureCommand, kind="capture", receipt_payload=None) -> Operation:
        digest = canonical_digest(receipt_payload or command.digest_payload())
        receipt = await self._receipt(connection, actor, command.binding_id, kind, command.idempotency_key, digest)
        if receipt:
            return self._operation(await self._operation_row(connection, command.binding_id, receipt["target_id"]))
        if len(command.body.encode()) > self.settings.max_capture_bytes:
            raise DomainError("BODY_TOO_LARGE", "The source exceeds the configured capture bound", status=413)
        if command.contradicts_coverage():
            raise DomainError("CAPTURE_COVERAGE_INVALID", "Producer-reported coverage contradicts the captured body length")
        ignored = command.injected or command.speaker == "memory" or "<agents-memory-context" in command.body or "[agents-memory:injected]" in command.body or BOUNDED_CONTEXT_MARKER in command.body
        if ignored:
            row = await self._new_operation(connection, actor, command.binding_id, kind, "captured", "CAPTURE_IGNORED")
            await connection.execute("UPDATE am_operations SET capture_disposition='ignored' WHERE id=$1", row["id"])
            row = await self._operation_row(connection, command.binding_id, row["id"])
        else:
            origin_token = await asyncio.to_thread(self.journal.origin_token, command.binding_id, command.origin_key)
            original = await connection.fetchrow("SELECT * FROM am_sources WHERE origin_token=$1 AND binding_id=$2", origin_token, command.binding_id)
            origin_digest = canonical_digest(command.digest_payload("idempotency_key"))
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
                await connection.execute("UPDATE am_operations SET capture_disposition='retracted' WHERE id=$1", row["id"])
                row = await self._operation_row(connection, command.binding_id, row["id"])
            else:
                row = await self._new_operation(connection, actor, command.binding_id, kind, "captured")
                source_id = await self._insert_source(connection, actor, command, row["id"])
                await self._point_operation(connection, row["id"], source_id)
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

    async def _selection_contract(self, connection, actor: Principal, binding_id: str) -> dict:
        binding = await connection.fetchrow("SELECT revision,realm FROM am_bindings WHERE id=$1 AND realm=$2", binding_id, actor.realm)
        if binding is None:
            raise _denied()
        contract = selection_contract_revision()
        return {"revision": contract, "epoch": 0, "binding_revision": binding["revision"]}


    async def _schedule_cleanup_group(
        self,
        connection,
        binding_id: str,
        snapshot: str | None,
        claim_ids: list[str],
    ) -> str | None:
        pending_id = await connection.fetchval("""
            SELECT id FROM am_pending_judgments
            WHERE binding_id=$1 AND COALESCE(snapshot,'')=COALESCE($2::text,'')
                AND kind='cleanup' AND state IN ('pending','held')
            LIMIT 1
        """, binding_id, snapshot)
        if pending_id is not None:
            return None

        recent = await connection.fetchval("""
            SELECT created_at>clock_timestamp()-$3*interval '1 second'
            FROM am_pending_judgments
            WHERE binding_id=$1 AND COALESCE(snapshot,'')=COALESCE($2::text,'')
                AND kind='cleanup'
            ORDER BY created_at DESC
            LIMIT 1
        """, binding_id, snapshot, self.settings.cleanup_interval_seconds)
        if recent:
            return None

        claims, sources = await self._judgment_inputs(
            connection, binding_id, snapshot, claim_ids
        )
        if not claims:
            return None

        manifest = self._claim_manifest(claims, sources, snapshot)
        judgment = await connection.fetchrow("""
            SELECT * FROM am_claim_judgments
            WHERE binding_id=$1 AND manifest_digest=$2 AND state='active'
            ORDER BY created_at DESC,id DESC
            LIMIT 1
        """, binding_id, canonical_digest(manifest))
        if judgment is not None and await self._judgment_disclosure(
            connection, binding_id, judgment, snapshot
        ):
            return None

        return await connection.fetchval("""
            INSERT INTO am_pending_judgments(id,binding_id,kind,claim_ids,snapshot)
            VALUES($1,$2,'cleanup',$3,$4)
            ON CONFLICT DO NOTHING
            RETURNING id
        """, _id("pending"), binding_id, [item.id for item in claims], snapshot)

    async def schedule_cleanup(self) -> dict:
        async with self._tx() as (connection, clock):
            progress = _decode(clock["cleanup_progress"])
            if not progress:
                high = await connection.fetchrow("""
                    SELECT
                        COALESCE((
                            SELECT sequence FROM am_pending_judgments
                            ORDER BY sequence DESC LIMIT 1
                        ),0) AS pending_high,
                        COALESCE((
                            SELECT cleanup_sequence FROM am_claims
                            ORDER BY cleanup_sequence DESC LIMIT 1
                        ),0) AS claim_high
                """)
                progress = {
                    "pending_high": high["pending_high"],
                    "pending_after": 0,
                    "claim_high": high["claim_high"],
                    "claim_after": 0,
                    "group_after": None,
                }

            pending = await connection.fetch("""
                SELECT p.*,b.realm FROM am_pending_judgments p
                JOIN am_bindings b ON b.id=p.binding_id
                WHERE p.kind='cleanup' AND p.state IN ('pending','held')
                    AND p.sequence>$1 AND p.sequence<=$2
                ORDER BY p.sequence
                LIMIT 32
            """, progress["pending_after"], progress["pending_high"])
            terminalized = 0
            for item in pending:
                if item["realm"] != self.settings.realm:
                    continue
                claims, _ = await self._judgment_inputs(
                    connection, item["binding_id"], item["snapshot"], item["claim_ids"]
                )
                if not claims:
                    await self._terminalize_cleanup(connection, item["id"])
                    terminalized += 1
            if pending:
                progress["pending_after"] = pending[-1]["sequence"]
            pending_more = await connection.fetchval("""
                SELECT EXISTS(
                    SELECT 1 FROM am_pending_judgments
                    WHERE kind='cleanup' AND state IN ('pending','held')
                        AND sequence>$1 AND sequence<=$2
                )
            """, progress["pending_after"], progress["pending_high"])
            if not pending_more:
                progress["pending_after"] = progress["pending_high"]

            created = []
            examined_pages = 0
            examined_claims = 0
            examined_bindings = 0

            while examined_pages < 4 and examined_bindings < 32:
                first = await connection.fetchval("""
                    SELECT cleanup_sequence FROM am_claims
                    WHERE cleanup_sequence>$1 AND cleanup_sequence<=$2
                    ORDER BY cleanup_sequence
                    LIMIT 1
                """, progress["claim_after"], progress["claim_high"])
                if first is None:
                    progress["claim_after"] = progress["claim_high"]
                    progress["group_after"] = None
                    break

                page_start = ((first - 1) // 20) * 20 + 1
                page_end = min(page_start + 19, progress["claim_high"])
                rows = await connection.fetch("""
                    SELECT c.id,c.binding_id,c.snapshot,c.cleanup_sequence,b.realm
                    FROM am_claims c JOIN am_bindings b ON b.id=c.binding_id
                    WHERE c.cleanup_sequence BETWEEN $1 AND $2
                    ORDER BY c.cleanup_sequence
                    LIMIT 20
                """, page_start, page_end)
                examined_pages += 1
                examined_claims += len(rows)

                groups = {}
                for row in rows:
                    if row["realm"] != self.settings.realm:
                        continue
                    key = (
                        row["binding_id"],
                        row["snapshot"] is not None,
                        row["snapshot"] or "",
                    )
                    groups.setdefault(key, []).append(row["id"])

                group_after = (
                    tuple(progress["group_after"])
                    if progress["group_after"] is not None else None
                )
                incomplete = False
                for key in sorted(groups):
                    if group_after is not None and key <= group_after:
                        continue
                    if examined_bindings == 32:
                        incomplete = True
                        break

                    examined_bindings += 1
                    snapshot = key[2] if key[1] else None
                    inserted = await self._schedule_cleanup_group(
                        connection, key[0], snapshot, groups[key]
                    )
                    if inserted is not None:
                        created.append(inserted)
                    progress["group_after"] = list(key)

                if incomplete:
                    break

                progress["claim_after"] = page_end
                progress["group_after"] = None

            claim_more = await connection.fetchval("""
                SELECT EXISTS(
                    SELECT 1 FROM am_claims
                    WHERE cleanup_sequence>$1 AND cleanup_sequence<=$2
                )
            """, progress["claim_after"], progress["claim_high"])
            more = bool(pending_more or claim_more)
            if more:
                saved_progress = progress
            else:
                saved_progress = {}
                more = bool(await connection.fetchval("""
                    SELECT EXISTS(
                        SELECT 1 FROM am_claims WHERE cleanup_sequence>$1
                    )
                """, progress["claim_high"]))

            await connection.execute("""
                UPDATE am_clock SET cleanup_progress=$1::jsonb WHERE singleton
            """, _json(saved_progress))
            return {
                "created": len(created),
                "pending_ids": created,
                "more": more,
                "examined_pending": len(pending),
                "terminalized": terminalized,
                "examined_pages": examined_pages,
                "examined_claims": examined_claims,
                "examined_bindings": examined_bindings,
            }

    async def _record_claim_judgment(self, connection, clock, actor: Principal, binding_id: str, command: ClaimJudgmentCommand) -> Operation:
        digest = canonical_digest(command.model_copy(update={"binding_id": binding_id}))
        receipt = await self._receipt(connection, actor, binding_id, "record", command.idempotency_key, digest)
        if receipt:
            return self._operation(await self._operation_row(connection, binding_id, receipt["target_id"]))
        admitted = await connection.fetchrow("SELECT * FROM am_admissions WHERE id=$1 AND binding_id=$2 AND purpose='claim_judgment' AND kind='nonmodel'", command.admission_id, binding_id)
        if admitted is None:
            return await self._consumed_admission(connection, actor, binding_id, command, digest,
                "Inspect the bounded claim judgment manifest first")
        admission = self._nonmodel_admission(admitted)
        await self._recheck_nonmodel(connection, clock, actor, admission)
        if command.manifest_digest != admission.request_digest or [item.model_dump() for item in command.claims] != _decode(admitted["claim_revisions"]) or command.sources != admission.sources:
            raise DomainError("JUDGMENT_MANIFEST_INVALID", "The judgment must match the complete inspected claim and source revision manifest")
        claims = [await self._claim(connection, await self._claim_row(connection, binding_id, item.id, admission.snapshot)) for item in command.claims]
        from .domain import Consolidation, RelationDraft
        from .semantic import validate_consolidation
        relations = tuple(RelationDraft(left_id=item.left_id, right_id=item.right_id,
            kind="duplicates" if item.relation == "duplicate" else item.relation, reason=item.reason) for item in command.relations)
        try:
            validate_consolidation(Consolidation(relations=relations), claims)
        except DomainError:
            raise DomainError("JUDGMENT_RELATION_INVALID", "The relation loses polarity, scope, qualifications or valid time") from None
        operation = await self._new_operation(connection, actor, binding_id, "claim_judgment", "candidate_ready")
        judgment_id = _id("judgment")
        await connection.execute("""INSERT INTO am_claim_judgments(id,binding_id,operation_id,credential_id,credential_generation,
            admission_id,manifest_digest,claims,sources,relations,reason,snapshot) VALUES($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9::jsonb,$10::jsonb,$11,$12)""",
            judgment_id, binding_id, operation["id"], actor.credential_id, actor.generation, admission.id,
            command.manifest_digest, _json([item.model_dump() for item in command.claims]),
            _json([item.model_dump() for item in command.sources]), _json([item.model_dump() for item in command.relations]), command.reason, admission.snapshot)
        for relation in relations:
            relation_id = _id("relation")
            await connection.execute(
                """INSERT INTO am_relations(id,binding_id,left_id,right_id,kind,reason,judgment_id)
                VALUES($1,$2,$3,$4,$5,$6,$7)""",
                relation_id, binding_id, relation.left_id, relation.right_id,
                relation.kind, relation.reason, judgment_id,
            )
            for source in command.sources:
                await connection.execute(
                    """INSERT INTO am_relation_sources(relation_id,source_id,source_revision)
                    VALUES($1,$2,$3)""",
                    relation_id, source.id, source.revision,
                )
            for claim in command.claims:
                await connection.execute(
                    "INSERT INTO am_relation_claims(relation_id,claim_id) VALUES($1,$2)",
                    relation_id, claim.id,
                )
        await connection.execute("UPDATE am_operations SET artifact_id=$2 WHERE id=$1", operation["id"], judgment_id)
        if admission.pending_id is not None:
            await connection.execute("""UPDATE am_pending_judgments SET state='resolved',resolved_at=clock_timestamp()
                WHERE id=$1 AND binding_id=$2 AND kind='cleanup' AND state IN ('pending','held')""",
                admission.pending_id, binding_id)
        await self._save_receipt(connection, actor, binding_id, "record", command.idempotency_key, digest, operation["id"],
            self._consumed_record(admission, command, binding_id))
        await connection.execute("DELETE FROM am_admissions WHERE id=$1", admission.id)
        return self._operation(await self._operation_row(connection, binding_id, operation["id"]))

    async def _record_selection(self, connection, clock, actor: Principal, binding_id: str, command: SourceSelectionCommand) -> Operation:
        digest = canonical_digest(command.model_copy(update={"binding_id": binding_id}))
        receipt = await self._receipt(connection, actor, binding_id, "record", command.idempotency_key, digest)
        if receipt:
            return self._operation(await self._operation_row(connection, binding_id, receipt["target_id"]))
        admitted = await connection.fetchrow("SELECT * FROM am_admissions WHERE id=$1 AND binding_id=$2 AND purpose='source_selection' AND kind='nonmodel'", command.admission_id, binding_id)
        if admitted is None:
            return await self._consumed_admission(connection, actor, binding_id, command, digest,
                "Inspect the original source window before submitting its judgment")
        admission = self._nonmodel_admission(admitted)
        await self._recheck_nonmodel(connection, clock, actor, admission)
        if admission.request_digest != command.window_digest or admission.snapshot != command.snapshot or admission.sources != (RevisionRef(id=command.source_id, revision=command.source_revision),):
            raise DomainError("SELECTION_STALE", "The judgment does not match the inspected original window")
        policy = await self._selection_contract(connection, actor, binding_id)
        source = self._source(await self._source_row(connection, binding_id, command.source_id, command.snapshot, True))
        extraction = resolve_selection(command, source, policy["binding_revision"], policy["revision"], policy["epoch"])
        rejection_inputs, _ = await self._selection_comparisons(
            connection, clock, actor, binding_id, command, admitted, source, policy)
        if extraction.claims:
            await self._derivation_allowed(connection, (source.id,))
        # Rejection and derivation floors report their specific reason before the single-winner refusal.
        if command.label != "review":
            await self._refuse_decided_window(connection, binding_id, source, command, policy["revision"])
        row = await self._new_operation(connection, actor, binding_id, "source_selection",
            "candidate_ready" if extraction.claims else "selection_recorded")
        selection_id = _id("selection")
        await connection.execute("""INSERT INTO am_source_selections(id,binding_id,operation_id,credential_id,credential_generation,
            realm,binding_revision,snapshot,source_id,source_revision,byte_start,byte_end,window_digest,judgment_digest,
            policy_revision,policy_epoch,label,coverage,reason,prior_rejection_ids,rejection_comparisons,
            request_snapshot,rejection_inputs,rejection_review_ids,deletion_generation)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21::jsonb,$22,$23::jsonb,$24,$25)""",
            selection_id, binding_id, row["id"], actor.credential_id, actor.generation, actor.realm,
            policy["binding_revision"], source.snapshot, source.id, source.revision, command.byte_start,
            command.byte_end, command.window_digest, digest, policy["revision"], policy["epoch"], command.label, command.coverage,
            command.reason, list(command.prior_rejection_ids), _json([item.model_dump() for item in command.rejection_comparisons]),
            command.snapshot, _json(rejection_inputs), list(command.rejection_review_ids), clock["deletion_generation"])
        await connection.execute("INSERT INTO am_selection_sources(selection_id,source_id,source_revision) VALUES($1,$2,$3)", selection_id, source.id, source.revision)
        if command.label == "discard":
            await self._index_rejection(connection, binding_id, selection_id)
        from .lexical import tokens as tokenize
        for draft in extraction.claims:
            evidence = self._spans(draft, {source.id: source})
            tokens = tokenize(" ".join((draft.statement, draft.subject, draft.predicate, draft.object, *draft.entities)))
            claim_id = _id("claim")
            await connection.execute("""INSERT INTO am_claims(id,binding_id,draft,snapshot,route_revision,lexical_tokens,
                valid_from,valid_until,extraction_operation_id,capability,interpretation_role,selection_id,policy_revision)
                VALUES($1,$2,$3::jsonb,$4,NULL,$5,$6,$7,$8,'agent_judged','caller_grounded_candidate',$9,$10)""",
                claim_id, binding_id, _json(draft.model_dump(mode="json", exclude={"evidence"})), source.snapshot,
                tokens, draft.valid_from, draft.valid_until, row["id"], selection_id, policy["revision"])
            await connection.execute("INSERT INTO am_claim_sources(claim_id,source_id,source_revision) VALUES($1,$2,$3)", claim_id, source.id, source.revision)
            for ordinal, span in enumerate(evidence):
                await connection.execute("""INSERT INTO am_spans(claim_id,ordinal,source_id,source_revision,byte_start,byte_end,quote)
                    VALUES($1,$2,$3,$4,$5,$6,$7)""", claim_id, ordinal, span.source_id, span.source_revision, span.byte_start, span.byte_end, span.quote)
            for entity in sorted({draft.subject, *draft.entities}):
                await connection.execute("INSERT INTO am_entities(claim_id,name,search_name) VALUES($1,$2,$3)", claim_id, entity, _entity(entity))
        await self._point_operation(connection, row["id"], source.id)
        await connection.execute("UPDATE am_operations SET artifact_id=$2,selection_label=$3 WHERE id=$1", row["id"], selection_id, command.label)
        if command.label != "review":
            await self._resolve_current_source_work(connection, binding_id, source.id)
        await self._save_receipt(connection, actor, binding_id, "record", command.idempotency_key, digest, row["id"],
            self._consumed_record(admission, command, binding_id))
        await connection.execute("DELETE FROM am_admissions WHERE id=$1", admission.id)
        return self._operation(await self._operation_row(connection, binding_id, row["id"]))

    @staticmethod
    def _business_digest(command: SourceSelectionCommand | ClaimJudgmentCommand, binding_id: str) -> str:
        """Judgment identity without the caller's idempotency key."""
        return canonical_digest(command.model_dump(mode="json", exclude={"idempotency_key"}) | {"binding_id": binding_id})

    def _consumed_record(self, admission: NonmodelAdmission, command: SourceSelectionCommand | ClaimJudgmentCommand, binding_id: str) -> dict:
        """Durable consumed-admission record kept on the record receipt; receipt digests stay unchanged."""
        return {"admission_id": admission.id, "purpose": command.kind, "business_digest": self._business_digest(command, binding_id)}

    async def _consumed_admission(self, connection, actor: Principal, binding_id: str,
            command: SourceSelectionCommand | ClaimJudgmentCommand, digest: str, stale_message: str) -> Operation:
        """Return the original operation when a lost response is retried with a new key and the same admission."""
        consumed = await connection.fetchrow("""SELECT target_id,result FROM am_receipts WHERE principal_id=$1 AND binding_id=$2
            AND kind='record' AND result->>'admission_id'=$3 AND result->>'purpose'=$4 ORDER BY request_key LIMIT 1""",
            actor.id, binding_id, command.admission_id, command.kind)
        if consumed is None:
            raise DomainError("ADMISSION_STALE", stale_message)
        if _decode(consumed["result"])["business_digest"] != self._business_digest(command, binding_id):
            raise DomainError("ADMISSION_CONSUMED", "This admission already recorded a different judgment; inspect again to judge anew")
        await self._save_receipt(connection, actor, binding_id, "record", command.idempotency_key, digest, consumed["target_id"])
        return self._operation(await self._operation_row(connection, binding_id, consumed["target_id"]))

    async def _refuse_decided_window(self, connection, binding_id: str, source: Source,
            command: SourceSelectionCommand, policy_revision: str) -> None:
        """One complete remember/discard wins per window; a later discard does not block remember's reopen rules.

        Only a remember whose published claims were all withdrawn stops holding the window; one that never
        published claims keeps it.
        """
        winner = await connection.fetchval("""SELECT q.operation_id FROM am_source_selections q
            WHERE q.binding_id=$1 AND q.source_id=$2 AND q.source_revision=$3 AND q.state='active'
            AND q.label IN ('remember','discard') AND q.coverage='complete_window' AND q.policy_revision=$4
            AND q.request_snapshot IS NOT DISTINCT FROM $5
            AND int8range(q.byte_start::bigint,q.byte_end::bigint,'[)') && int8range($6::bigint,$7::bigint,'[)')
            AND NOT (q.label='discard' AND $8='remember')
            AND NOT (q.label='remember' AND EXISTS(SELECT 1 FROM am_claims c WHERE c.selection_id=q.id)
                AND NOT EXISTS(SELECT 1 FROM am_claims c WHERE c.selection_id=q.id AND c.state='active'))
            ORDER BY q.created_at,q.id LIMIT 1""",
            binding_id, source.id, source.revision, policy_revision, command.snapshot,
            command.byte_start, command.byte_end, command.label)
        if winner is not None:
            raise DomainError("SELECTION_ALREADY_RECORDED",
                f"Operation {winner} already holds the complete judgment for an overlapping window; inspect it or retract it first")

    async def record(self, actor: Principal, command: RecordInput) -> Operation:
        binding_id = resolve_binding(actor, command.binding_id)
        async with self._tx() as (connection, clock):
            current = await self._actor(connection, actor, binding_id, (Role.AGENT, Role.OPERATOR))
            from .health import CodeLinkCommand, HealthAssessmentCommand

            if isinstance(command, (CodeLinkCommand, HealthAssessmentCommand)):
                return await self._record_health(connection, clock, current, command, receipt_kind="record")
            if isinstance(command, SourceSelectionCommand):
                return await self._record_selection(connection, clock, current, binding_id, command)
            if isinstance(command, ClaimJudgmentCommand):
                return await self._record_claim_judgment(connection, clock, current, binding_id, command)
            digest = canonical_digest(command.model_copy(update={"binding_id": binding_id}))
            receipt = await self._receipt(connection, current, binding_id, "record", command.idempotency_key, digest)
            if receipt:
                return self._operation(await self._operation_row(connection, binding_id, receipt["target_id"]))
            if command.kind == "note":
                origin = canonical_digest({"principal_id": current.id, "request_key": command.idempotency_key})
                capture = CaptureCommand(binding_id=binding_id, idempotency_key=command.idempotency_key, origin_key=f"agent-note:{origin}", body=command.body, speaker="agent_note")
                return await self._capture(connection, current, capture, kind="record", receipt_payload=command.model_copy(update={"binding_id": binding_id}))
            proposal = RuleProposal(binding_id=binding_id, idempotency_key=command.idempotency_key, body=command.body)
            row = await self._new_operation(connection, current, binding_id, "record", "captured")
            info = await self._create_proposal(connection, current, proposal, clock, row["id"])
            await connection.execute("UPDATE am_operations SET artifact_id=$2,source_id=$3 WHERE id=$1", row["id"], info["proposal_id"], info["source_id"])
            await self._save_receipt(connection, current, binding_id, "record", command.idempotency_key, digest, row["id"])
            return self._operation(await self._operation_row(connection, binding_id, row["id"]))

    async def _rejection_sources(
        self, connection, binding_id: str, ref: str,
    ) -> list[str]:
        visited = set()
        while True:
            if ref in visited or len(visited) >= REJECTION_DISCLOSURE_DEPTH_LIMIT:
                raise DomainError(
                    "REJECTION_REFERENCE_INVALID", "The rejection target lineage is cyclic",
                )
            visited.add(ref)
            kind, row = await self._ref_metadata(connection, binding_id, ref)
            if kind != "operation":
                break
            target = row["artifact_id"] or row["source_id"]
            if target is None:
                return []
            ref = target
        if kind == "source":
            return [row["id"]]
        dependencies = {
            "claim": ("am_claim_sources", "claim_id"),
            "selection": ("am_selection_sources", "selection_id"),
            "relation": ("am_relation_sources", "relation_id"),
            "reflection": ("am_reflection_sources", "reflection_id"),
            "proposal": ("am_proposal_sources", "proposal_id"),
        }
        if kind in dependencies:
            table, column = dependencies[kind]
            rows = await connection.fetch(
                f"""SELECT source_id FROM {table}
                    WHERE {column}=$1 ORDER BY source_id LIMIT 129""",
                ref,
            )
            if len(rows) > 128:
                raise DomainError(
                    "REJECTION_REFERENCE_INVALID", "The rejection source manifest is too large",
                )
            return [item["source_id"] for item in rows]
        if kind == "judgment":
            sources = _decode(row["sources"])
            if len(sources) > 128:
                raise DomainError(
                    "REJECTION_REFERENCE_INVALID", "The rejection source manifest is too large",
                )
            return sorted({item["id"] for item in sources})
        return []

    async def feedback(self, actor: Principal, command: FeedbackCommand) -> Operation:
        binding_id = resolve_binding(actor, command.binding_id)
        async with self._tx() as (connection, _):
            current = await self._actor(connection, actor, binding_id, (Role.AGENT, Role.OPERATOR))
            digest = canonical_digest(command.model_copy(update={"binding_id": binding_id}))
            receipt = await self._receipt(connection, current, binding_id, "feedback", command.idempotency_key, digest)
            if receipt:
                return self._operation(await self._operation_row(connection, binding_id, receipt["target_id"]))
            await self._ref_metadata(connection, binding_id, command.target_ref)
            rejected_sources = []
            if command.kind == "reject":
                rejected_sources = await self._rejection_sources(connection, binding_id, command.target_ref)
            operation = await self._new_operation(connection, current, binding_id, "feedback", "captured")
            source_id = None
            if command.body is not None:
                source_id = await self._insert_source(connection, current, CaptureCommand(binding_id=binding_id, idempotency_key=command.idempotency_key, origin_key=f"feedback:{operation['id']}", body=command.body, speaker="agent_note"), operation["id"])
                await self._point_operation(connection, operation["id"], source_id)
            artifact_id = _id("feedback")
            await connection.execute("INSERT INTO am_feedback(id,binding_id,target_ref,kind,source_id,reason,rejected_source_ids) VALUES($1,$2,$3,$4,$5,$6,$7)", artifact_id, binding_id, command.target_ref, command.kind, source_id, command.body, rejected_sources)
            if command.kind == "reject":
                await self._index_rejection(connection, binding_id, artifact_id)
            if command.kind in {"correct", "retract_request"}:
                await self._enqueue_health(connection, binding_id, "feedback:" + artifact_id,
                    payload={"cause": "feedback_candidate", "feedback_ref": artifact_id})
            await connection.execute("UPDATE am_operations SET source_id=$2,artifact_id=$3 WHERE id=$1", operation["id"], source_id, artifact_id)
            await self._save_receipt(connection, current, binding_id, "feedback", command.idempotency_key, digest, operation["id"])
            return self._operation(await self._operation_row(connection, binding_id, operation["id"]))

    async def operation(self, actor: Principal, binding_id: str, operation_id: str) -> Operation:
        async with self._tx() as (connection, _):
            await self._actor(connection, actor, binding_id)
            return self._operation(await self._operation_row(connection, binding_id, operation_id))

    def _source(self, row) -> Source:
        return Source(id=row["id"], binding_id=row["binding_id"], realm=row["realm"], revision=row["revision"], body=row["body"], speaker=row["speaker"], origin_key=row["origin_key"], root_run_id=row["root_run_id"], snapshot=row["snapshot"], event_time=row["event_time"], recorded_at=row["recorded_at"], state=row["state"],
            coverage=CaptureCoverage.model_validate(_decode(row["capture_coverage"])))

    async def _source_row(
        self, connection, binding_id: str, source_id: str,
        snapshot=None, enforce_snapshot=False,
    ):
        row = await connection.fetchrow(
            """SELECT * FROM am_sources
               WHERE id=$1 AND binding_id=$2 AND realm=$3
                 AND state='active' AND body IS NOT NULL""",
            source_id, binding_id, self.settings.realm,
        )
        if row is None:
            raise DomainError("SOURCE_INELIGIBLE", "The source is not currently eligible")
        if enforce_snapshot and row["snapshot"] is not None and row["snapshot"] != snapshot:
            raise DomainError(
                "SNAPSHOT_INELIGIBLE", "The source belongs to a different snapshot",
            )
        has_reason_owner = await connection.fetchval(
            """SELECT EXISTS(SELECT 1 FROM am_feedback WHERE binding_id=$1 AND source_id=$2)
                OR EXISTS(SELECT 1 FROM am_health_events WHERE binding_id=$1 AND reason_source_id=$2)""",
            binding_id, source_id,
        )
        if has_reason_owner and await self._disclosure_manifest(
            connection, binding_id, source_id, snapshot,
        ) is None:
            raise DomainError(
                "INPUT_INELIGIBLE", "The reason source or its exact target lineage is not currently eligible",
            )
        return row

    async def source(self, actor: Principal, binding_id: str, source_id: str) -> Source:
        async with self._tx() as (connection, _):
            await self._actor(connection, actor, binding_id, (Role.AGENT, Role.OPERATOR, Role.APPROVER))
            return self._source(await self._source_row(connection, binding_id, source_id))

    async def _claim_row(self, connection, binding_id: str, claim_id: str, snapshot: str | None, enforce_time: bool = True):
        row = await connection.fetchrow("""SELECT c.* FROM am_claims c WHERE c.id=$1 AND c.binding_id=$2 AND c.state='active' AND c.draft IS NOT NULL
          AND (c.snapshot IS NULL OR c.snapshot=$3)
          AND (c.selection_id IS NULL OR EXISTS(SELECT 1 FROM am_source_selections q WHERE q.id=c.selection_id AND q.state='active'))
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
        return Claim(id=row["id"], binding_id=row["binding_id"], draft=ClaimDraft.model_validate(draft), evidence=evidence, input_source_ids=tuple(item["source_id"] for item in inputs), snapshot=row["snapshot"], created_at=row["created_at"], state=row["state"],
            interpretation_role=row["interpretation_role"], selection_id=row["selection_id"], policy_revision=row["policy_revision"],
            revision=row["revision"], awaiting_revalidation=row["awaiting_revalidation"])

    async def claim(self, actor: Principal, binding_id: str, claim_id: str, snapshot: str | None = None) -> Claim:
        async with self._tx() as (connection, _):
            await self._actor(connection, actor, binding_id, (Role.AGENT, Role.OPERATOR, Role.APPROVER))
            return await self._claim(connection, await self._claim_row(connection, binding_id, claim_id, snapshot))

    async def _ref_metadata(self, connection, binding_id: str, ref: str) -> tuple[str, asyncpg.Record]:
        for kind, table in (
            ("operation", "am_operations"), ("source", "am_sources"),
            ("claim", "am_claims"), ("proposal", "am_proposals"),
            ("reflection", "am_reflections"), ("feedback", "am_feedback"),
            ("relation", "am_relations"),
            ("selection", "am_source_selections"),
            ("judgment", "am_claim_judgments"),
            ("pending", "am_pending_judgments"),
            ("health_event", "am_health_events"), ("session_observation", "am_session_observations"),
            ("code_observation", "am_code_observations"), ("health_workspace", "am_code_workspaces"),
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

    async def _new_caller_admission(self, connection, clock, actor, binding_id, purpose, request_digest, snapshot,
        claims=(), sources=(), relation_ids=(), rejection_ids=(), pending_id=None, *, health_manifest=None, code_workspace_id=None) -> NonmodelAdmission:
        policy = await self._selection_contract(connection, actor, binding_id)
        if health_manifest is None:
            health_manifest = await self._admitted_health_manifest(connection, binding_id,
                [item.id for item in claims], relation_ids,
                code_workspace_id=code_workspace_id, workspace_scoped=purpose == 'caller_recall')
        await connection.execute("""DELETE FROM am_admissions WHERE id IN (SELECT id FROM am_admissions
            WHERE kind='nonmodel' AND deadline<=clock_timestamp() LIMIT 64)""")
        row = await connection.fetchrow("""INSERT INTO am_admissions(id,binding_id,credential_id,credential_generation,epoch,
            deletion_generation,route_revision,purpose,route_epochs,sources,claim_ids,deadline,snapshot,
            kind,binding_revision,realm,policy_revision,policy_epoch,relation_ids,request_digest,claim_revisions,
            rejection_ids,pending_id,health_manifest)
            VALUES($1,$2,$3,$4,$5,$6,NULL,$7,'{}',$8::jsonb,$9,clock_timestamp()+$10*interval '1 second',
            $11,'nonmodel',$12,$13,$14,0,$15,$16,$17::jsonb,$18,$19,$20::jsonb) RETURNING *""",
            _id('admission'), binding_id, actor.credential_id, actor.generation, clock['epoch'], clock['deletion_generation'],
            purpose, _json([item.model_dump() for item in sources]), [item.id for item in claims],
            self.settings.read_admission_timeout_seconds, snapshot, policy['binding_revision'], actor.realm,
            policy['revision'], list(relation_ids), request_digest, _json([item.model_dump() for item in claims]),
            list(rejection_ids), pending_id, _json(health_manifest))
        return self._nonmodel_admission(row)

    async def _judgment_inputs(self, connection, binding_id, snapshot, claim_ids=None) -> tuple[tuple[RevisionRef, ...], tuple[RevisionRef, ...]]:
        rows = connection.cursor("""SELECT c.id FROM am_claims c WHERE c.binding_id=$1 AND c.state='active'
            AND c.capability='agent_judged' AND c.draft IS NOT NULL AND (c.snapshot IS NULL OR c.snapshot=$2)
            AND (c.valid_from IS NULL OR c.valid_from<=clock_timestamp())
            AND (c.valid_until IS NULL OR c.valid_until>clock_timestamp())
            AND ($3::text[] IS NULL OR c.id=ANY($3)) ORDER BY c.id""",
            binding_id, snapshot, list(claim_ids) if claim_ids is not None else None, prefetch=32)
        claims = []
        inputs = {}
        async for item in rows:
            try:
                row = await self._claim_row(connection, binding_id, item["id"], snapshot)
                await self._reuse_claim(connection, row)
            except DomainError as error:
                if error.code == "CLAIM_INELIGIBLE":
                    continue
                raise
            claims.append(RevisionRef(id=row["id"], revision=row["revision"]))
            dependencies = await connection.fetch("SELECT source_id,source_revision FROM am_claim_sources WHERE claim_id=$1", row["id"])
            for dependency in dependencies:
                inputs[dependency["source_id"]] = RevisionRef(id=dependency["source_id"], revision=dependency["source_revision"])
            if len(claims) == 20:
                break
        return tuple(claims), tuple(inputs[key] for key in sorted(inputs))

    def _claim_manifest(self, claims, sources, snapshot) -> dict:
        return {"claims": [item.model_dump() for item in claims], "sources": [item.model_dump() for item in sources], "snapshot": snapshot}

    async def _terminalize_cleanup(self, connection, pending_id: str) -> None:
        await connection.execute("""UPDATE am_pending_judgments SET state='resolved',resolved_at=clock_timestamp(),
            reason='Cleanup obsolete: no manifest claims remain eligible'
            WHERE id=$1 AND kind='cleanup' AND state IN ('pending','held')""", pending_id)

    async def _judgment_manifest(self, connection, clock, actor, binding_id, snapshot, claim_ids=None, *, pending_id=None) -> dict:
        if claim_ids is not None and (not 1 <= len(claim_ids) <= 20 or len(set(claim_ids)) != len(claim_ids)):
            raise DomainError("JUDGMENT_MANIFEST_INVALID", "Choose one to twenty unique claim IDs")
        pending = None
        if pending_id is not None:
            pending = await connection.fetchrow("""SELECT * FROM am_pending_judgments WHERE id=$1 AND binding_id=$2
                AND kind='cleanup' AND state IN ('pending','held') AND (snapshot IS NULL OR snapshot=$3)""",
                pending_id, binding_id, snapshot)
            if pending is None or (claim_ids is not None and list(claim_ids) != list(pending["claim_ids"])):
                raise DomainError("ADMISSION_STALE", "The cleanup identity or original claim manifest changed")
            claim_ids = pending["claim_ids"]
        claims, sources = await self._judgment_inputs(connection, binding_id, snapshot, claim_ids)
        if pending is None:
            candidates = await connection.fetch("""SELECT * FROM am_pending_judgments WHERE binding_id=$1
                AND kind='cleanup' AND state IN ('pending','held') AND (snapshot IS NULL OR snapshot=$2)
                ORDER BY sequence""", binding_id, snapshot)
            for candidate in candidates:
                if claim_ids is not None and list(claim_ids) != list(candidate["claim_ids"]):
                    continue
                current_claims, current_sources = await self._judgment_inputs(connection, binding_id, snapshot, candidate["claim_ids"])
                if current_claims == claims and current_sources == sources:
                    pending = candidate
                    break
        if pending is None and claim_ids is not None and {item.id for item in claims} != set(claim_ids):
            raise DomainError("CLAIM_INELIGIBLE", "Every explicitly selected claim must remain eligible in this project and snapshot")
        manifest = self._claim_manifest(claims, sources, snapshot)
        if len(sources) > 128:
            raise DomainError("MANIFEST_TOO_LARGE", "The complete claim judgment evidence exceeds its bounded manifest")
        digest = canonical_digest(manifest)
        if not claims:
            if pending is not None:
                await self._terminalize_cleanup(connection, pending["id"])
            return {**manifest, "admission_id": None, "manifest_digest": digest,
                "pending_id": pending["id"] if pending is not None else None,
                "judgment_required": False, "cleanup_disposition": "obsolete", "relations": [],
                "relation_ids": [], "relation_context_partial": False}
        relations = await self._lexical_relations(connection, binding_id, tuple(item.id for item in claims), snapshot)
        admission = await self._new_caller_admission(connection, clock, actor, binding_id, "claim_judgment", digest,
            snapshot, claims=claims, sources=sources, relation_ids=tuple(item["id"] for item in relations),
            pending_id=pending["id"] if pending is not None else None)
        return {**manifest, "admission_id": admission.id, "manifest_digest": digest, "pending_id": admission.pending_id,
            "relation_ids": [item["id"] for item in relations], "relation_context_partial": len(relations) > 8,
            "relations": [{"id": item["id"], "left_id": item["left_id"], "right_id": item["right_id"],
                "relation": "duplicate" if item["kind"] == "duplicates" else item["kind"]} for item in relations[:8]],
            "judgment_required": True, "inspect_claims_before_judgment": True, "inspect_relations_before_judgment": bool(relations)}

    async def _judgment_disclosure(
        self, connection, binding_id: str, row, snapshot: str | None,
    ) -> bool:
        if (
            row["binding_id"] != binding_id
            or row["state"] != "active"
            or (row["snapshot"] is not None and row["snapshot"] != snapshot)
            or row["relations"] is None
        ):
            return False
        try:
            for item in _decode(row["claims"]):
                claim = await self._claim_row(connection, binding_id, item["id"], snapshot)
                if claim["revision"] != item["revision"]:
                    return False
            for item in _decode(row["sources"]):
                source = await self._source_row(
                    connection, binding_id, item["id"], snapshot, True,
                )
                if source["revision"] != item["revision"]:
                    return False
            assertions = _decode(row["relations"])
            if assertions:
                edges = await connection.fetch(
                    """SELECT id,left_id,right_id,kind,reason FROM am_relations
                    WHERE binding_id=$1 AND judgment_id=$2 AND state='active'""",
                    binding_id, row["id"],
                )
                owned = {
                    (edge["left_id"], edge["right_id"], edge["kind"], edge["reason"]): edge["id"]
                    for edge in edges
                }
                for assertion in assertions:
                    key = (
                        assertion["left_id"],
                        assertion["right_id"],
                        "duplicates" if assertion["relation"] == "duplicate"
                        else assertion["relation"],
                        assertion["reason"],
                    )
                    relation_id = owned.get(key)
                    if relation_id is None:
                        return False
                    await self._relation_row(
                        connection, binding_id, relation_id, snapshot,
                        reuse=False,
                    )
        except DomainError as error:
            if error.code not in {
                "CLAIM_INELIGIBLE", "SOURCE_INELIGIBLE", "SNAPSHOT_INELIGIBLE",
                "RELATION_INELIGIBLE", "INPUT_INELIGIBLE",
            }:
                raise
            return False
        return True

    async def _selection_disclosure(
        self, connection, binding_id: str, row, snapshot: str | None,
    ) -> bool:
        return (
            await self._disclosure_manifest(
                connection, binding_id, row["id"], snapshot,
            )
            is not None
        )

    async def _pending_page(self, connection, clock, binding_id, snapshot, cursor, max_bytes) -> dict:
        if type(cursor) is not int or cursor < 0 or type(max_bytes) is not int or not 256 <= max_bytes <= 4096:
            raise DomainError("PENDING_PAGE_INVALID", "Pending inspection requires a bounded cursor and byte budget")
        rows = await connection.fetch("""SELECT p.id,p.sequence,p.kind,p.state,p.source_ids,p.claim_ids,p.original_job_id,p.snapshot,p.health_revision
            FROM am_pending_judgments p WHERE p.binding_id=$1 AND p.state IN ('pending','held')
            AND (p.snapshot IS NULL OR p.snapshot=$2) AND p.sequence>$3
            ORDER BY p.sequence LIMIT 33""", binding_id, snapshot, cursor)
        result = {"kind": "pending", "epoch": clock["epoch"], "items": [], "next_cursor": None, "partial": False}
        for row in rows[:32]:
            item = dict(row)
            if item["kind"] != "health":
                item.pop("health_revision")
            item["source_count"], item["claim_count"] = len(item["source_ids"]), len(item["claim_ids"])
            item["source_ids"], item["claim_ids"] = item["source_ids"][:4], item["claim_ids"][:4]
            proposed = {**result, "items": [*result["items"], item], "next_cursor": row["sequence"], "partial": True}
            if len(_json(proposed).encode()) > max_bytes:
                break
            result["items"].append(item)
        result["partial"] = len(result["items"]) < len(rows)
        result["next_cursor"] = result["items"][-1]["sequence"] if result["partial"] and result["items"] else None
        if rows and not result["items"]:
            raise DomainError("PENDING_PAGE_TOO_LARGE", "The pending item requires a larger inspection budget", status=413)
        return result

    async def _rejection_input(
        self, connection, binding_id: str, snapshot: str | None,
        rejection_id: str, *,
        _path: tuple[str, ...] = (),
        _budget: list[int] | None = None,
    ) -> dict | None:
        try:
            kind, row = await self._ref_metadata(connection, binding_id, rejection_id)
        except DomainError as error:
            if error.code == "NOT_FOUND":
                return None
            raise
        if row.get("state", "active") != "active":
            return None
        if kind == "selection" and row["label"] == "discard":
            source_ids = [row["source_id"]]
            disposition = "discard"
            target = {
                "source_revision": row["source_revision"],
                "window_digest": row["window_digest"],
                "byte_start": row["byte_start"],
                "byte_end": row["byte_end"],
                "judgment_digest": row["judgment_digest"],
                "snapshot": row["snapshot"],
                "request_snapshot": row["request_snapshot"],
            }
        elif kind == "feedback" and row["kind"] == "reject":
            source_ids = list(row["rejected_source_ids"])
            if row["source_id"]:
                source_ids.append(row["source_id"])
            disposition = "reject"
            target = {
                "id": row["target_ref"],
                "source_ids": list(row["rejected_source_ids"]),
            }
        else:
            raise DomainError(
                "REJECTION_REFERENCE_INVALID", "Reference an actual persisted rejection",
            )
        if len(set(source_ids)) > 129:
            return None
        manifest = await self._disclosure_manifest(
            connection, binding_id, rejection_id, snapshot,
            _path=_path, _budget=_budget,
        )
        if manifest is None:
            return None
        inputs = []
        expected = {
            item["source_id"]: item
            for item in await connection.fetch(
                """SELECT source_id,source_revision,body_digest FROM am_rejection_evidence
                   WHERE binding_id=$1 AND rejection_id=$2""",
                binding_id, rejection_id,
            )
        }
        for source_id in sorted(set(source_ids)):
            source = await connection.fetchrow(
                """SELECT * FROM am_sources
                   WHERE id=$1 AND binding_id=$2 AND realm=$3
                     AND state='active' AND body IS NOT NULL
                     AND (snapshot IS NULL OR snapshot=$4)""",
                source_id, binding_id, self.settings.realm, snapshot,
            )
            if source is None:
                return None
            value = self._source_input(source)
            if kind == "selection" and source["revision"] != row["source_revision"]:
                return None
            if source["speaker"] not in {"agent_note", "memory"}:
                indexed = expected.get(source_id)
                if (
                    indexed is None
                    or indexed["source_revision"] != source["revision"]
                    or indexed["body_digest"] != value["body_digest"]
                ):
                    return None
            inputs.append(value)
        value = {
            "id": row["id"],
            "reason": row["reason"],
            "state": row["state"],
            "disposition": disposition,
            "target": target,
            "sources": inputs,
            "reason_source_id": row["source_id"] if kind == "feedback" else None,
            "lineage_digest": canonical_digest(manifest),
        }
        return {**value, "input_digest": canonical_digest(value)}

    

    async def _bind_rejection_inputs(
        self, connection, admission_id: str, binding_id: str, snapshot: str | None,
    ) -> None:
        ids = await connection.fetchval(
            "SELECT rejection_ids FROM am_admissions WHERE id=$1 AND binding_id=$2",
            admission_id, binding_id,
        )
        if ids is None or len(ids) > 8 or len(set(ids)) != len(ids):
            raise DomainError("ADMISSION_STALE", "The rejection admission is invalid")
        inputs = {}
        for rejection_id in ids:
            item = await self._rejection_input(connection, binding_id, snapshot, rejection_id)
            if item is None:
                raise DomainError(
                    "ADMISSION_STALE", "The inspected rejection is no longer current",
                )
            inputs[rejection_id] = item["input_digest"]
        await connection.execute(
            "UPDATE am_admissions SET rejection_inputs=$2::jsonb WHERE id=$1",
            admission_id, _json(inputs),
        )

    async def _recheck_rejection_inputs(self, connection, admitted) -> None:
        inputs = _decode(admitted["rejection_inputs"])
        if (
            not isinstance(inputs, dict)
            or len(inputs) > 8
            or set(inputs) != set(admitted["rejection_ids"])
        ):
            raise DomainError(
                "ADMISSION_STALE", "The inspected rejection inputs are incomplete",
            )
        for rejection_id, digest in inputs.items():
            item = await self._rejection_input(
                connection, admitted["binding_id"], admitted["snapshot"], rejection_id,
            )
            if item is None or item["input_digest"] != digest:
                raise DomainError(
                    "ADMISSION_STALE", "The inspected rejection evidence changed",
                )

    async def _selection_comparisons(
        self, connection, clock, actor: Principal, binding_id: str,
        command: SourceSelectionCommand, admitted, source: Source, policy: dict,
    ) -> tuple[dict, dict]:
        direct = {
            item.rejection_id: item.model_dump()
            for item in command.rejection_comparisons
        }
        inspected = _decode(admitted["rejection_inputs"])
        if not set(direct).issubset(set(admitted["rejection_ids"])):
            raise DomainError(
                "REJECTION_COMPARISON_REQUIRED",
                "Direct comparisons must reference the inspected rejection page",
            )
        if {
            key for key, item in direct.items() if item["decision"] == "reopen"
        } != set(command.prior_rejection_ids):
            raise DomainError(
                "REJECTION_REFERENCE_INVALID",
                "Each direct reopening requires its exact prior rejection reference",
            )
        if command.label == "review" and set(direct) != set(admitted["rejection_ids"]):
            raise DomainError(
                "REJECTION_COMPARISON_REQUIRED",
                "Review each rejection in the inspected bounded page",
            )
    
        current = {}
        compared = {}
        validated_reviews = set()
        active_reviews = set()
    
        async def current_input(rejection_id: str) -> dict:
            if rejection_id not in current:
                item = await self._rejection_input(
                    connection, binding_id, command.snapshot, rejection_id,
                )
                if item is None:
                    raise DomainError(
                        "REJECTION_REVIEW_STALE",
                        "A compared rejection is no longer currently eligible",
                    )
                current[rejection_id] = item
            return current[rejection_id]
    
        async def add_comparison(item: dict, input_digest: str) -> None:
            parsed = RejectionComparison.model_validate(item)
            rejection = await current_input(parsed.rejection_id)
            if rejection["input_digest"] != input_digest:
                raise DomainError(
                    "REJECTION_REVIEW_STALE", "Compared rejection evidence changed",
                )
            saved = compared.get(parsed.rejection_id)
            if saved is not None and saved["decision"] != parsed.decision:
                raise DomainError(
                    "REJECTION_REFERENCE_INVALID", "Rejection comparisons disagree",
                )
            if parsed.rejection_id not in compared and len(compared) >= 128:
                raise DomainError(
                    "REJECTION_REVIEW_STALE", "The bounded comparison manifest is exceeded",
                )
            compared[parsed.rejection_id] = parsed.model_dump()
    
        for rejection_id, item in direct.items():
            if rejection_id not in inspected:
                raise DomainError("ADMISSION_STALE", "The rejection fingerprint is missing")
            await add_comparison(item, inspected[rejection_id])
    
        expected = (
            actor.credential_id, actor.generation, actor.realm,
            policy["binding_revision"], command.snapshot, source.snapshot,
            source.id, source.revision, command.byte_start, command.byte_end,
            command.window_digest, policy["revision"], policy["epoch"],
            clock["deletion_generation"],
        )
    
        async def visit_review(review_id: str) -> None:
            if review_id in active_reviews:
                raise DomainError(
                    "REJECTION_REVIEW_STALE", "Rejection review lineage contains a cycle",
                )
            if review_id in validated_reviews:
                return
            if len(validated_reviews) + len(active_reviews) >= REJECTION_REVIEW_LIMIT:
                raise DomainError(
                    "REJECTION_REVIEW_STALE", "The bounded rejection review lineage is exceeded",
                )
            review = await connection.fetchrow(
                "SELECT * FROM am_source_selections WHERE id=$1 AND binding_id=$2",
                review_id, binding_id,
            )
            if review is None or review["state"] != "active" or review["label"] != "review":
                raise DomainError("REJECTION_REVIEW_STALE", "Reference a current review receipt")
            actual = (
                review["credential_id"], review["credential_generation"], review["realm"],
                review["binding_revision"], review["request_snapshot"], review["snapshot"],
                review["source_id"], review["source_revision"], review["byte_start"],
                review["byte_end"], review["window_digest"], review["policy_revision"],
                review["policy_epoch"], review["deletion_generation"],
            )
            if actual != expected:
                raise DomainError(
                    "REJECTION_REVIEW_STALE",
                    "The review no longer matches current authority and the exact source window",
                )
            inputs = _decode(review["rejection_inputs"])
            comparisons = _decode(review["rejection_comparisons"])
            if (
                not isinstance(inputs, dict)
                or not isinstance(comparisons, list)
                or len(comparisons) > 16
                or len(review["rejection_review_ids"]) > 16
            ):
                raise DomainError("REJECTION_REVIEW_STALE", "The review manifest is invalid")
            try:
                parsed = [RejectionComparison.model_validate(item) for item in comparisons]
            except ValueError:
                raise DomainError(
                    "REJECTION_REVIEW_STALE", "The saved comparisons are invalid",
                ) from None
            ids = {item.rejection_id for item in parsed}
            if len(ids) != len(parsed) or set(inputs) != ids or {
                item.rejection_id for item in parsed if item.decision == "reopen"
            } != set(review["prior_rejection_ids"]):
                raise DomainError(
                    "REJECTION_REVIEW_STALE", "The review has an incomplete evidence manifest",
                )
            active_reviews.add(review_id)
            try:
                for item in parsed:
                    await add_comparison(item.model_dump(), inputs[item.rejection_id])
                for parent_id in review["rejection_review_ids"]:
                    await visit_review(parent_id)
            finally:
                active_reviews.remove(review_id)
            validated_reviews.add(review_id)
    
        for review_id in command.rejection_review_ids:
            await visit_review(review_id)
    
        body_digest = hashlib.sha256(source.body.encode()).hexdigest()
        origin_digest = hashlib.sha256(source.origin_key.encode()).hexdigest()
        for rejection_id, comparison in compared.items():
            if comparison["decision"] != "reopen":
                continue
            if source.speaker not in {"human", "tool", "document"}:
                raise DomainError(
                    "EVIDENCE_REJECTED",
                    "Reopening requires independent human, tool, or document evidence",
                )
            evidence = [
                original for original in current[rejection_id]["sources"]
                if original["speaker"] not in {"agent_note", "memory"}
                and original["id"] != current[rejection_id]["reason_source_id"]
            ]
            if not evidence or any(
                original["id"] == source.id
                or original["body_digest"] == body_digest
                or original["origin_digest"] == origin_digest
                for original in evidence
            ):
                raise DomainError(
                    "EVIDENCE_REJECTED", "Reopening requires independent new source evidence",
                )
    
        if command.label == "remember":
            await self._refuse_rejected_identity(
                connection, binding_id, command.snapshot, source,
                command.byte_start, command.byte_end,
            )
            required, _ = await self._required_rejections(
                connection, binding_id, command.snapshot, source,
            )
            for item in required:
                rejection_id = item["id"]
                if (
                    rejection_id not in compared
                    or rejection_id not in current
                    or current[rejection_id]["input_digest"] != item["input_digest"]
                ):
                    raise DomainError(
                        "REJECTION_COMPARISON_REQUIRED",
                        "Compare the current bounded relevant rejection candidates",
                    )
    
        return {
            rejection_id: current[rejection_id]["input_digest"]
            for rejection_id in direct
        }, compared

    async def _source_judgment_context(
        self, connection, binding_id, snapshot, *,
        rejection_cursor: str | None = None,
        source_id: str | None = None,
    ) -> dict:
        accepted_rows = await connection.fetch(
            f"""SELECT c.id,c.revision,c.draft->>'statement' AS statement
               FROM am_claims c
               WHERE c.binding_id=$1 AND c.state='active'
                 AND c.capability='agent_judged' AND c.draft IS NOT NULL
                 AND (c.snapshot IS NULL OR c.snapshot=$2)
                 AND (c.valid_from IS NULL OR c.valid_from<=clock_timestamp())
                 AND (c.valid_until IS NULL OR c.valid_until>clock_timestamp())
                 AND ({_HEALTH_REUSE_SQL})
               ORDER BY c.created_at DESC,c.id LIMIT 9""",
            binding_id, snapshot,
        )
        accepted = []
        for row in accepted_rows:
            try:
                await self._claim_row(connection, binding_id, row["id"], snapshot)
                if await self._disclosure_manifest(
                    connection, binding_id, row["id"], snapshot,
                ) is None:
                    continue
            except DomainError as error:
                if error.code not in _DISCLOSURE_ERRORS:
                    raise
                continue
            accepted.append(dict(row))

        review_rows = await connection.fetch(
            """SELECT c.id,c.revision,h.version,h.review_event_id,e.reason_source_id
               FROM am_claims c JOIN am_claim_health h
                 ON h.claim_id=c.id AND h.claim_revision=c.revision
               JOIN am_health_events e ON e.id=h.review_event_id AND e.binding_id=c.binding_id
                 AND e.kind='memory_review' AND e.target_ref=c.id
               WHERE c.binding_id=$1 AND c.state='active' AND c.capability='agent_judged'
                 AND h.operator_review='reject' AND (c.snapshot IS NULL OR c.snapshot=$2)
                 AND (c.valid_from IS NULL OR c.valid_from<=clock_timestamp())
                 AND (c.valid_until IS NULL OR c.valid_until>clock_timestamp())
               ORDER BY c.created_at DESC,c.id LIMIT 9""",
            binding_id, snapshot,
        )
        health_dispositions = []
        for row in review_rows:
            try:
                await self._source_judgment_health_manifest(
                    connection, binding_id, snapshot, [{
                        "id": row["id"], "revision": row["revision"], "review_event_id": row["review_event_id"],
                    }],
                )
                reason = await self._source_row(connection, binding_id, row["reason_source_id"], snapshot, True)
            except DomainError as error:
                if error.code not in _DISCLOSURE_ERRORS and error.code != "ADMISSION_STALE":
                    raise
                continue
            item = {
                "claim_ref": {"id": row["id"], "revision": row["revision"]},
                "health_version": row["version"], "review_event_id": row["review_event_id"],
                "decision": "reject", "reason_source_ref": reason["id"],
                "reason_source_revision": reason["revision"],
                "grounding": "operator_disposition_not_independent_source",
            }
            if len(reason["body"].encode("utf-8")) <= 128:
                item["reason"] = reason["body"]
            else:
                item["reason_requires_inspection"] = True
            health_dispositions.append(item)
            if len(health_dispositions) == 8:
                break
    
        required = []
        index_metadata = None
        if source_id is not None:
            source = self._source(
                await self._source_row(connection, binding_id, source_id, snapshot, True)
            )
            if source.speaker not in {"agent_note", "memory"}:
                required, index_metadata = await self._required_rejections(
                    connection, binding_id, snapshot, source,
                )
    
        history = None
        if rejection_cursor is not None or source_id is None:
            history = await self._rejection_history_page(
                connection, binding_id, snapshot, rejection_cursor,
            )
            displayed = history["items"]
        else:
            displayed = required
    
        def bounded(rows, field):
            values = []
            for row in rows[:8]:
                item = dict(row)
                if field == "reason":
                    item = {
                        name: item[name]
                        for name in ("id", "reason", "state", "disposition", "input_digest")
                    }
                if item[field] is None:
                    item[f"{field}_unavailable"] = True
                elif len(item[field].encode()) > 128:
                    item.pop(field)
                    item[f"{field}_requires_inspection"] = True
                values.append(item)
            return values
    
        return {
            "accepted_memories": bounded(accepted, "statement"),
            "rejections": bounded(displayed, "reason"),
            "health_dispositions": health_dispositions,
            "health_dispositions_partial": True,
            "required_rejection_ids": [item["id"] for item in required],
            "required_candidate_index": index_metadata,
            "rejection_page_kind": "optional_history" if history else "required_candidates",
            "rejections_next_cursor": history["next_cursor"] if history else None,
            "rejections_partial": history["partial"] if history else False,
            "optional_history": {
                "start_cursor": "history", "required_for_publication": False,
                **({"examined_rows": history["examined_rows"],
                    "examined_row_limit": REJECTION_HISTORY_EXAMINED_LIMIT,
                    "coverage": "live_history_pages_not_a_frozen_catalog"} if history else {}),
            },
            "context_partial": True,
        }

    async def _source_judgment_health_manifest(self, connection, binding_id, snapshot, inputs) -> list[dict]:
        if len(inputs) > 16:
            raise DomainError("MANIFEST_TOO_LARGE", "The bounded source judgment health inputs exceed their limit")
        result = []
        for item in inputs:
            try:
                claim = await self._claim_row(connection, binding_id, item["id"], snapshot)
                disclosure = await self._disclosure_manifest(connection, binding_id, item["id"], snapshot)
                if claim["revision"] != item["revision"] or disclosure is None:
                    raise DomainError("ADMISSION_STALE", "An actual source judgment input changed")
                manifest = {
                    "input": item, "health": await self._claim_health_manifest(connection, claim),
                    "disclosure": disclosure,
                }
                if item.get("review_event_id"):
                    event = await connection.fetchrow(
                        "SELECT * FROM am_health_events WHERE id=$1 AND binding_id=$2",
                        item["review_event_id"], binding_id,
                    )
                    if event is None or not await self._health_event_visible(connection, binding_id, event, snapshot):
                        raise DomainError("ADMISSION_STALE", "An actual source judgment review input changed")
                    reason_disclosure = await self._disclosure_manifest(
                        connection, binding_id, event["reason_source_id"], snapshot,
                    )
                    if reason_disclosure is None:
                        raise DomainError("ADMISSION_STALE", "An actual source judgment review reason changed")
                    manifest["review_disclosure"] = {
                        "id": event["id"], "kind": event["kind"], "target_ref": event["target_ref"],
                        "payload_digest": canonical_digest(_decode(event["payload"])),
                        "reason": reason_disclosure,
                    }
            except DomainError as error:
                if error.code not in _DISCLOSURE_ERRORS:
                    raise
                raise DomainError("ADMISSION_STALE", "An actual source judgment input is no longer disclosed") from None
            result.append(manifest)
        return result

    async def inspect(
        self, actor: Principal, binding_id: str, ref: str, snapshot: str | None = None, *,
        byte_start: int = 0, max_bytes: int = 4096, claim_ids: tuple[str, ...] | None = None,
        rejection_cursor: str | None = None, representation_bytes: int | None = None,
        measure_json: Callable[[dict], int] | None = None,
    ) -> dict:
        from .representation import serialized_json_bytes, stored_record_window

        representation_bytes = self.settings.max_inspection_json_bytes if representation_bytes is None else representation_bytes
        measure_json = serialized_json_bytes if measure_json is None else measure_json

        if snapshot is not None:
            if not isinstance(snapshot, str) or not 1 <= len(snapshot) <= 512:
                raise DomainError("INPUT_INVALID", "Choose a bounded snapshot", status=400)
            reject_source_secrets(snapshot)
        if type(byte_start) is not int or not 0 <= byte_start <= 9223372036854775807:
            raise DomainError("INPUT_INVALID", "The inspection cursor exceeds its integer bound", status=400)
        if type(max_bytes) is not int or not 1 <= max_bytes <= 4096:
            raise DomainError("INPUT_INVALID", "Choose a bounded inspection byte budget", status=400)
        if claim_ids is not None and (
            ref != "judgment" or not isinstance(claim_ids, tuple) or not 1 <= len(claim_ids) <= 20
            or any(not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", identifier) for identifier in claim_ids)
            or len(set(claim_ids)) != len(claim_ids)
        ):
            raise DomainError("JUDGMENT_MANIFEST_INVALID", "Choose up to20 unique claim IDs for judgment inspection")
        if rejection_cursor is not None and (
            not isinstance(rejection_cursor, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", rejection_cursor)
            or ref in {"pending", "judgment"}
        ):
            raise DomainError("INPUT_INVALID", "Rejection cursors apply only to source inspection", status=400)
        async with self._tx() as (connection, clock):
            current = await self._actor(connection, actor, binding_id, (Role.AGENT, Role.OPERATOR, Role.APPROVER))
            if ref == "health" or ref.startswith("health:"):
                if current.role == Role.APPROVER:
                    raise _denied()
                return await self._inspect_health(
                    connection, clock, current, binding_id, ref, snapshot,
                    byte_start=byte_start, max_bytes=max_bytes,
                    representation_bytes=representation_bytes, measure_json=measure_json)
            if ref == "pending":
                return await self._pending_page(connection, clock, binding_id, snapshot, byte_start, max_bytes)
            if ref == "judgment":
                if byte_start != 0 or max_bytes != 4096:
                    raise DomainError("JUDGMENT_MANIFEST_INVALID", "Window arguments require a stored record reference")
                return {"kind": "claim_judgment", **await self._judgment_manifest(connection, clock, current, binding_id, snapshot, claim_ids=claim_ids)}
            kind, row = await self._ref_metadata(connection, binding_id, ref)
            if kind in {"health_event", "session_observation", "code_observation", "health_workspace"}:
                if current.role == Role.APPROVER:
                    raise _denied()
                if kind == "health_event":
                    return await self._inspect_health(
                        connection, clock, current, binding_id, "health:event:" + ref, snapshot,
                        byte_start=byte_start, max_bytes=max_bytes,
                        representation_bytes=representation_bytes, measure_json=measure_json)
            if rejection_cursor is not None and kind != "source":
                raise DomainError("INPUT_INVALID", "Rejection cursors apply only to source inspection", status=400)
            if kind not in {"source", "claim", "judgment", "selection", "feedback", "proposal", "rule"} and (byte_start != 0 or max_bytes != 4096):
                raise DomainError("SOURCE_WINDOW_INVALID", "Window arguments require a source or stored record")
            if kind in {"pending", "judgment"} and row["snapshot"] is not None and row["snapshot"] != snapshot:
                raise DomainError("SNAPSHOT_INELIGIBLE", "The judgment belongs to a different snapshot")
            result = {"id": ref, "kind": kind, "epoch": clock["epoch"], "state": row.get("state", "candidate")}
            if kind == "pending":
                if row["kind"] == "health":
                    if current.role == Role.APPROVER:
                        raise _denied()
                    return await self._inspect_health(
                        connection, clock, current, binding_id, "health:item:" + row["id"], snapshot,
                        byte_start=byte_start, max_bytes=max_bytes,
                        representation_bytes=representation_bytes, measure_json=measure_json)
                result.update(pending_kind=row["kind"], source_ids=row["source_ids"], claim_ids=row["claim_ids"],
                    reason=row["reason"], original_job_id=row["original_job_id"])
                if row["kind"] == "cleanup" and row["state"] in {"pending", "held"}:
                    result["judgment_manifest"] = await self._judgment_manifest(
                        connection, clock, current, binding_id, snapshot, row["claim_ids"], pending_id=row["id"],
                    )
                    refreshed = await connection.fetchrow("SELECT state,reason,resolved_at FROM am_pending_judgments WHERE id=$1", row["id"])
                    result.update(state=refreshed["state"], reason=refreshed["reason"])
                return result
            if kind == "judgment":
                visible = await self._judgment_disclosure(connection, binding_id, row, snapshot)
                result.update(manifest_digest=row["manifest_digest"], claims=_decode(row["claims"]), sources=_decode(row["sources"]),
                    relations=_decode(row["relations"]) if visible and row["relations"] is not None else None,
                    reason=row["reason"] if visible else None, snapshot=row["snapshot"])
                if visible and (byte_start != 0 or max_bytes != 4096 or measure_json(result) > representation_bytes):
                    return stored_record_window(result, byte_start, max_bytes, representation_bytes, measure_json=measure_json)
                return result
            pending = await connection.fetch("""SELECT request_key,result FROM am_receipts WHERE principal_id=$1
                AND binding_id=$2 AND kind='correct_intent' AND target_id=$3 AND result->>'state'<>'completed'
                ORDER BY request_key LIMIT 9""", current.id, binding_id, ref)
            if pending:
                result["pending_corrections"] = [{"request_key": item["request_key"], **dict(_decode(item["result"]))} for item in pending[:8]]
                result["pending_corrections_partial"] = len(pending) > 8
            if kind == "operation":
                result.update(self._operation(row).model_dump(mode="json"))
                jobs = await connection.fetch("""SELECT j.id,j.kind,j.state,j.error_code,j.attempts,j.generation,
                    j.created_at,j.retired_at,r.original->>'state' AS original_state,r.successor_id,p.state AS caller_disposition
                    FROM am_jobs j LEFT JOIN am_retired_jobs r ON r.job_id=j.id
                    LEFT JOIN am_pending_judgments p ON p.id=r.successor_id
                    WHERE j.operation_id=$1 AND j.binding_id=$2 ORDER BY j.created_at,j.id LIMIT 8""", ref, binding_id)
                result["jobs"] = [{**dict(job), "created_at": job["created_at"].isoformat(),
                    "retired_at": job["retired_at"].isoformat() if job["retired_at"] is not None else None} for job in jobs]
                return result
            if kind == "source":
                result.update(revision=row["revision"], snapshot=row["snapshot"], speaker=row["speaker"])
                if row["state"] != "active" or row["body"] is None:
                    return result
                source = self._source(await self._source_row(connection, binding_id, ref, snapshot, True))
                policy = await self._selection_contract(connection, current, binding_id)
                independent_work = source.speaker not in {"agent_note", "memory"}
                result["judgment_required"] = independent_work
                if independent_work:
                    result["judgment_context"] = await self._source_judgment_context(
                        connection, binding_id, snapshot, rejection_cursor=rejection_cursor, source_id=source.id,
                    )
                else:
                    result["judgment_context"] = {
                        "accepted_memories": [], "rejections": [], "required_rejection_ids": [],
                        "health_dispositions": [], "health_dispositions_partial": False,
                        "rejection_page_kind": "non_independent_note",
                        "rejections_next_cursor": None, "rejections_partial": False, "context_partial": False,
                    }
                result.update(source_window(source, byte_start, max_bytes, policy["binding_revision"],
                    policy["revision"], policy["epoch"], request_snapshot=snapshot,
                    representation_bytes=representation_bytes - 256, measure_json=measure_json, metadata=result))
                if independent_work:
                    context = result["judgment_context"]
                    inputs = [{"id": item["id"], "revision": item["revision"]}
                              for item in context["accepted_memories"]]
                    inputs.extend({
                        "id": item["claim_ref"]["id"], "revision": item["claim_ref"]["revision"],
                        "review_event_id": item["review_event_id"],
                    } for item in context["health_dispositions"])
                    health_manifest = await self._admitted_health_manifest(connection, binding_id, ())
                    health_manifest["source_judgment"] = await self._source_judgment_health_manifest(
                        connection, binding_id, snapshot, inputs,
                    )
                    admission = await self._new_caller_admission(connection, clock, current, binding_id, "source_selection",
                        result["window_digest"], snapshot, sources=(RevisionRef(id=source.id, revision=source.revision),),
                        rejection_ids=tuple(item["id"] for item in context["rejections"]),
                        health_manifest=health_manifest)
                    await self._bind_rejection_inputs(connection, admission.id, binding_id, snapshot)
                    result["admission_id"] = admission.id
                    result["admission_deadline"] = admission.deadline.isoformat()
                else:
                    result["admission_id"] = None
                    result["admission_deadline"] = None
                return result
            if kind == "selection":
                if not await self._selection_disclosure(connection, binding_id, row, snapshot):
                    return {
                        **{name: result[name] for name in ("id", "kind", "epoch", "state")},
                        **{name: row[name] for name in ("source_id", "source_revision", "snapshot", "label")},
                    }
                result.update({name: row[name] for name in ("source_id", "source_revision", "binding_revision", "snapshot",
                    "request_snapshot", "byte_start", "byte_end", "window_digest", "judgment_digest", "policy_revision",
                    "policy_epoch", "label", "coverage", "reason", "prior_rejection_ids", "rejection_review_ids")})
                result["rejection_comparisons"] = _decode(row["rejection_comparisons"])
                claims = await connection.fetch("SELECT id FROM am_claims WHERE selection_id=$1 AND state='active' ORDER BY id", ref)
                result["claim_ids"] = [item["id"] for item in claims]
                result["interpretation_role"] = "caller_grounded_candidate"
                inputs = await connection.fetch("""SELECT s.id,s.speaker,s.event_time,s.recorded_at,s.capture_coverage,
                    s.producer_generation,d.source_revision FROM am_selection_sources d JOIN am_sources s ON s.id=d.source_id
                    WHERE d.selection_id=$1 ORDER BY s.id""", ref)
                result["source_provenance"] = [{"source_id": item["id"], "source_revision": item["source_revision"],
                    "source_speaker": item["speaker"], "source_event_time": item["event_time"].isoformat() if item["event_time"] else None,
                    "source_recorded_at": item["recorded_at"].isoformat(), "producer_generation": item["producer_generation"],
                    "capture_coverage": _decode(item["capture_coverage"])} for item in inputs]
                if byte_start != 0 or max_bytes != 4096 or measure_json(result) > representation_bytes:
                    return stored_record_window(result, byte_start, max_bytes, representation_bytes, measure_json=measure_json)
                return result
            if row.get("state") == "retracted":
                return result
            if kind == "claim":
                claim = await self._claim(connection, await self._claim_row(connection, binding_id, ref, snapshot))
                result.update(statement=claim.draft.statement,
                    evidence=[span.model_dump(mode="json") for span in claim.evidence],
                    input_source_ids=claim.input_source_ids, snapshot=claim.snapshot,
                    interpretation_role=claim.interpretation_role, selection_id=claim.selection_id, policy_revision=claim.policy_revision,
                    revision=claim.revision, awaiting_revalidation=claim.awaiting_revalidation,
                    draft=claim.draft.model_dump(mode="json", exclude={"evidence"}))
                result["judgment_context_refs"] = [
                    {"ref": source_id, "snapshot": snapshot} for source_id in claim.input_source_ids
                ]
                if byte_start != 0 or max_bytes != 4096 or measure_json(result) > representation_bytes:
                    return stored_record_window(result, byte_start, max_bytes, representation_bytes, measure_json=measure_json)
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
                    interpretation_role="model_derived_candidate", awaiting_revalidation=True,
                    partial=len(sentences) < len(draft.sentences) or len(limitations) < len(draft.limitations),
                )
            elif kind == "relation":
                relation = await self._relation_row(connection, binding_id, ref, snapshot, reuse=False)
                result.update(
                    left_id=relation["left_id"],
                    right_id=relation["right_id"],
                    relation_kind=(
                        "duplicate" if relation["kind"] == "duplicates"
                        else relation["kind"]
                    ),
                    reason=relation["reason"],
                    interpretation_role=(
                        "caller_judged_relation" if relation["judgment_id"]
                        else "model_derived_relation"
                    ),
                    awaiting_revalidation=relation["judgment_id"] is None,
                )
            elif kind in {"proposal", "rule"}:
                proposal_id = ref if kind == "proposal" else row["proposal_id"]
                proposal = row if kind == "proposal" else await connection.fetchrow(
                    "SELECT * FROM am_proposals WHERE id=$1", proposal_id)
                if proposal is None:
                    raise _denied()
                dependencies = await self._dependencies(connection, "am_proposal_sources", "proposal_id", proposal_id)
                complete_approval_view = (
                    proposal["binding_id"] in current.bindings and bool(dependencies)
                    and all(source["binding_id"] in current.bindings for source in dependencies))
                if kind == "proposal" and not complete_approval_view:
                    raise _denied()
                body_source = next((source for source in dependencies if source["id"] == proposal["source_id"]), None)
                if complete_approval_view and body_source is None:
                    raise DomainError("INPUT_INELIGIBLE", "The exact proposed body is unavailable")
                if kind == "rule":
                    active = await self._active_rule(connection, row)
                    result.update(
                        digest=active.digest, revision=active.revision, scope=active.scope.value,
                        target_bindings=tuple(target for target in active.target_bindings if target in current.bindings))
                else:
                    result.update(digest=proposal["digest"], target_set_revision=proposal["target_set_revision"])
                result.update(
                    body=body_source["body"] if complete_approval_view else active.body,
                    required=proposal["required"], selector=_decode(proposal["selector"]),
                    exceptions=_decode(proposal["exceptions"]), candidate=kind == "proposal",
                    input_sources=[{"id": source["id"], "revision": source["expected_revision"]}
                        for source in dependencies if source["binding_id"] in current.bindings],
                    approval_inspection_complete=complete_approval_view,
                    inspection_authority={
                        "credential_id": current.credential_id, "generation": current.generation,
                        "realm": current.realm, "binding_id": binding_id,
                        "binding_revision": await connection.fetchval(
                            "SELECT revision FROM am_bindings WHERE id=$1", binding_id)})
                if complete_approval_view:
                    result.update(
                        proposal_id=proposal_id, proposal_digest=proposal["digest"],
                        body_source_ref={"id": body_source["id"], "revision": body_source["revision"]})
                if byte_start != 0 or max_bytes != 4096 or measure_json(result) > representation_bytes:
                    return stored_record_window(result, byte_start, max_bytes, representation_bytes, measure_json=measure_json)
            elif kind == "feedback":
                if not await self._feedback_disclosure(connection, binding_id, row, snapshot):
                    return {name: result[name] for name in ("id", "kind", "epoch", "state")}
                result.update(target_ref=row["target_ref"], feedback_kind=row["kind"], reason=row["reason"], source_id=row["source_id"], candidate=True)
                if row["source_id"]:
                    source = await self._source_row(connection, binding_id, row["source_id"], snapshot, True)
                    result["body"] = source["body"]
                if byte_start != 0 or max_bytes != 4096 or measure_json(result) > representation_bytes:
                    return stored_record_window(result, byte_start, max_bytes, representation_bytes, measure_json=measure_json)
            return result

    async def _current_selection_rows(self, connection, binding_id: str, snapshot: str | None) -> list:
        rows = connection.cursor("""SELECT q.* FROM am_source_selections q
            JOIN am_sources s ON s.id=q.source_id
            WHERE q.binding_id=$1 AND q.state='active'
            AND q.policy_revision=$3 AND q.label IN ('remember','discard','review')
            AND (q.snapshot IS NULL OR q.snapshot IS NOT DISTINCT FROM $2)
            AND (q.request_snapshot IS NULL OR q.request_snapshot IS NOT DISTINCT FROM $2)
            AND s.binding_id=$1 AND s.realm=$4 AND s.state='active' AND s.body IS NOT NULL
            AND s.revision=q.source_revision ORDER BY q.source_id,q.byte_start,q.id""",
            binding_id, snapshot, selection_contract_revision(), self.settings.realm, prefetch=32)
        current = []
        async for row in rows:
            if await self._selection_disclosure(connection, binding_id, row, snapshot):
                current.append(row)
        return current

    @staticmethod
    def _ranges_cover(rows, length: int) -> bool:
        end = 0
        for row in sorted(rows, key=lambda item: (item["byte_start"], item["byte_end"])):
            if row["byte_start"] > end:
                return False
            end = max(end, row["byte_end"])
            if end >= length:
                return True
        return length == 0

    async def _current_coverage(self, connection, binding_id: str, snapshot: str | None) -> tuple[dict, list]:
        rows = await self._current_selection_rows(connection, binding_id, snapshot)
        classified, ranges, labels = set(), {}, {}
        for row in rows:
            labels[row["label"]] = labels.get(row["label"], 0) + 1
            if row["label"] in {"remember", "discard"}:
                classified.add(row["source_id"])
                if row["coverage"] == "complete_window":
                    ranges.setdefault(row["source_id"], []).append(row)
        unclassified = incomplete = 0
        sources = connection.cursor("""SELECT id,octet_length(body) AS size,capture_coverage
            FROM am_sources WHERE binding_id=$1 AND realm=$3 AND state='active' AND body IS NOT NULL
            AND speaker NOT IN ('memory','agent_note') AND (snapshot IS NULL OR snapshot=$2)
            ORDER BY id""", binding_id, snapshot, self.settings.realm, prefetch=32)
        async for source in sources:
            coverage = _decode(source["capture_coverage"])
            unclassified += source["id"] not in classified
            incomplete += (
                coverage.get("status") != "observed_window" or bool(coverage.get("gaps"))
                or not self._ranges_cover(ranges.get(source["id"], ()), source["size"]))
        return {"unclassified_sources": unclassified, "incomplete_sources": incomplete}, [
            {"label": label, "count": count} for label, count in sorted(labels.items())]

    async def _resolve_current_source_work(self, connection, binding_id: str, source_id: str) -> None:
        pending = connection.cursor("""SELECT * FROM am_pending_judgments WHERE binding_id=$1
            AND kind IN ('source_selection','legacy_revalidation') AND state IN ('pending','held')
            AND $2=ANY(source_ids) ORDER BY sequence""", binding_id, source_id, prefetch=32)
        async for item in pending:
            rows = await self._current_selection_rows(connection, binding_id, item["snapshot"])
            complete = True
            for identifier in item["source_ids"]:
                source = await connection.fetchrow("""SELECT octet_length(body) AS size FROM am_sources
                    WHERE id=$1 AND binding_id=$2 AND realm=$3 AND state='active' AND body IS NOT NULL
                    AND (snapshot IS NULL OR snapshot IS NOT DISTINCT FROM $4)""",
                    identifier, binding_id, self.settings.realm, item["snapshot"])
                decided = [
                    row for row in rows if row["source_id"] == identifier
                    and row["label"] in {"remember", "discard"} and row["coverage"] == "complete_window"]
                if source is None or not self._ranges_cover(decided, source["size"]):
                    complete = False
                    break
            if complete:
                await connection.execute("""UPDATE am_pending_judgments SET state='resolved',
                    resolved_at=clock_timestamp() WHERE id=$1""", item["id"])

    async def _stats(self, connection, binding_id: str, epoch: int, snapshot: str | None = None, *,
        code_workspace_id: str | None = None, workspace_scoped: bool = False) -> dict:
        sources = await connection.fetchval("SELECT count(*) FROM am_sources WHERE binding_id=$1 AND state='active' AND body IS NOT NULL AND (snapshot IS NULL OR snapshot=$2)", binding_id, snapshot)
        lexical = True
        vector_revision = None
        indexed = await connection.fetchrow("""SELECT count(*) AS active,
            count(*) FILTER (WHERE c.capability='full_semantic' AND (c.embedding IS NULL OR $3::text IS NULL OR c.vector_revision IS DISTINCT FROM $3)) AS stale,
            count(*) FILTER (WHERE c.capability='agent_judged' AND c.policy_revision IS DISTINCT FROM $6::text) AS previous_policy
            FROM am_claims c WHERE c.binding_id=$1 AND c.state='active' AND c.draft IS NOT NULL AND c.superseded_by IS NULL
            AND c.capability=$5
            AND (c.selection_id IS NULL OR EXISTS(SELECT 1 FROM am_source_selections q WHERE q.id=c.selection_id AND q.state='active'))
            AND (c.snapshot IS NULL OR c.snapshot=$2) AND (c.valid_from IS NULL OR c.valid_from<=clock_timestamp())
            AND (c.valid_until IS NULL OR c.valid_until>clock_timestamp())
            AND EXISTS(SELECT 1 FROM am_claim_sources d WHERE d.claim_id=c.id)
            AND NOT EXISTS(SELECT 1 FROM am_claim_sources d JOIN am_sources s ON s.id=d.source_id
            WHERE d.claim_id=c.id AND (s.state<>'active' OR s.revision<>d.source_revision OR s.body IS NULL
                OR s.binding_id<>c.binding_id OR s.realm<>$4
                OR (s.snapshot IS NOT NULL AND s.snapshot IS DISTINCT FROM $2)))""", binding_id, snapshot, vector_revision, self.settings.realm, self.settings.capability,
            selection_contract_revision() if lexical else None)
        operations = await connection.fetch("SELECT state,count(*) AS count FROM am_operations WHERE binding_id=$1 GROUP BY state", binding_id)
        jobs = await connection.fetch("""SELECT COALESCE(r.original->>'state',j.state) AS state,count(*) AS count
            FROM am_jobs j LEFT JOIN am_retired_jobs r ON r.job_id=j.id
            WHERE j.binding_id=$1 GROUP BY COALESCE(r.original->>'state',j.state)""", binding_id)
        job_counts = {row["state"]: row["count"] for row in jobs}
        operation_counts = {row["state"]: row["count"] for row in operations}
        current_operations = await connection.fetch("""SELECT state,count(*) AS count FROM am_pending_judgments
            WHERE binding_id=$1 AND (snapshot IS NULL OR snapshot=$2) AND state IN ('pending','held') GROUP BY state""", binding_id, snapshot)
        current_counts = {row["state"]: row["count"] for row in current_operations}
        current_jobs = await connection.fetch("""SELECT COALESCE(r.original->>'state',j.state) AS state,count(*) AS count
            FROM am_jobs j LEFT JOIN am_retired_jobs r ON r.job_id=j.id
            LEFT JOIN am_pending_judgments p ON p.id=r.successor_id WHERE j.binding_id=$1
            AND (j.snapshot IS NULL OR j.snapshot=$2)
            AND (j.retired_at IS NULL OR p.state IN ('pending','held'))
            GROUP BY COALESCE(r.original->>'state',j.state)""", binding_id, snapshot)
        live_job_counts = {row["state"]: row["count"] for row in current_jobs}
        recovery = await connection.fetch("""SELECT j.id,j.operation_id,j.state,j.error_code,j.attempts,j.generation,
            r.original->>'state' AS original_state,r.successor_id,p.state AS caller_disposition,
            (j.retired_at IS NULL OR p.state IN ('pending','held')) AS unresolved
            FROM am_jobs j LEFT JOIN am_retired_jobs r ON r.job_id=j.id
            LEFT JOIN am_pending_judgments p ON p.id=r.successor_id WHERE j.binding_id=$1
            AND COALESCE(r.original->>'state',j.state) IN ('blocked','failed') ORDER BY j.created_at,j.id LIMIT 8""", binding_id)
        result = {"binding_id": binding_id, "epoch": epoch, "active_sources": sources,
                "capability": self.settings.capability,
                "active_claims": indexed["active"], "stale_index_claims": indexed["stale"], "vector_revision": vector_revision,
                "pending": current_counts.get("pending", 0),
                "blocked": current_counts.get("held", 0), "failed": live_job_counts.get("failed", 0),
                "current_operations": current_counts, "current_jobs": live_job_counts,
                "historical_operations": operation_counts, "historical_jobs": job_counts,
                "dlq": live_job_counts.get("failed", 0),
                "partial": bool(indexed["stale"]), "scope": "all_eligible_granted_project_rows", "snapshot": snapshot,
                "recovery_jobs": [dict(job) for job in recovery],
                "recovery_partial": job_counts.get("blocked", 0) + job_counts.get("failed", 0) > len(recovery)}
        if lexical:
            coverage, labels = await self._current_coverage(connection, binding_id, snapshot)
            result.update(coverage={**dict(coverage), "previous_policy_claims": indexed["previous_policy"]},
                classification_labels={row["label"]: row["count"] for row in labels})
        result["legacy_claims_awaiting_revalidation"] = await connection.fetchval("SELECT count(*) FROM am_claims WHERE binding_id=$1 AND state='active' AND awaiting_revalidation", binding_id)
        result["retired_jobs"] = await connection.fetchval("SELECT count(*) FROM am_jobs WHERE binding_id=$1 AND retired_at IS NOT NULL", binding_id)
        result["health"] = await self._current_health_stats(connection, binding_id, snapshot,
            code_workspace_id=code_workspace_id, workspace_scoped=workspace_scoped)
        return result

    async def stats(self, actor: Principal, binding_id: str, snapshot: str | None = None) -> dict:
        async with self._tx() as (connection, clock):
            await self._actor(connection, actor, binding_id)
            return await self._stats(connection, binding_id, clock["epoch"], snapshot)

    def _nonmodel_admission(self, row) -> NonmodelAdmission:
        if row["request_digest"] is None or row["health_manifest"] is None:
            raise DomainError("ADMISSION_STALE", "Inspect the inputs again under the current judgment contract")
        return NonmodelAdmission(id=row["id"], binding_id=row["binding_id"], binding_revision=row["binding_revision"],
            credential_id=row["credential_id"], credential_generation=row["credential_generation"], realm=row["realm"],
            epoch=row["epoch"], deletion_generation=row["deletion_generation"], policy_revision=row["policy_revision"],
            policy_epoch=row["policy_epoch"], sources=tuple(RevisionRef.model_validate(item) for item in _decode(row["sources"])),
            claim_ids=tuple(row["claim_ids"]), snapshot=row["snapshot"], deadline=row["deadline"], request_digest=row["request_digest"],
            health_manifest_digest=canonical_digest(_decode(row["health_manifest"])),
            relation_ids=tuple(row["relation_ids"]), rejection_ids=tuple(row["rejection_ids"]), pending_id=row["pending_id"])

    async def _lexical_relations(
        self, connection, binding_id: str, claim_ids: tuple[str, ...], snapshot: str | None, *,
        code_workspace_id: str | None = None, workspace_scoped: bool = False,
    ) -> list:
        rows = await connection.fetch("""SELECT * FROM am_relations WHERE binding_id=$1 AND state='active' AND judgment_id IS NOT NULL
            AND (left_id=ANY($2::text[]) OR right_id=ANY($2::text[])) ORDER BY id""", binding_id, list(claim_ids))
        eligible = []
        seen = set()
        for row in rows:
            key = (row["left_id"], row["right_id"], row["kind"])
            if key in seen:
                continue
            try:
                await self._relation_row(
                    connection, binding_id, row["id"], snapshot,
                    code_workspace_id=code_workspace_id, workspace_scoped=workspace_scoped)
            except DomainError as error:
                if error.code not in {"RELATION_INELIGIBLE", "INPUT_INELIGIBLE", "CLAIM_INELIGIBLE"}:
                    raise
                continue
            seen.add(key)
            if len(eligible) == 128:
                raise DomainError("RELATION_CONTEXT_OVERFLOW", "The complete relation input exceeds the bounded context")
            eligible.append(row)
        return eligible

    async def search_lexical(
        self, actor: Principal, binding_id: str, lexical_tokens: list[str], snapshot: str | None, limit: int = 20, *,
        request_digest: str, code_workspace_id: str | None = None,
    ) -> tuple[list[tuple[Claim, tuple[str, ...]]], NonmodelAdmission]:
        if not re.fullmatch(r"[a-f0-9]{64}", request_digest):
            raise DomainError("ADMISSION_REQUEST_INVALID", "A canonical recall request digest is required")
        if type(limit) is not int or not 1 <= limit <= 20 or len(lexical_tokens) > 2048 or any(
            not isinstance(token, str) or not token or len(token.encode()) > 1024 for token in lexical_tokens
        ):
            raise DomainError("SEARCH_LIMIT_INVALID", "The retrieval bounds are invalid")
        async with self._tx() as (connection, clock):
            current = await self._actor(connection, actor, binding_id, (Role.AGENT, Role.OPERATOR))
            rows = await connection.fetch(f"""WITH eligible AS MATERIALIZED (
                SELECT c.* FROM am_claims c JOIN am_source_selections q ON q.id=c.selection_id
                WHERE c.binding_id=$1 AND c.state='active' AND c.draft IS NOT NULL AND c.superseded_by IS NULL
                AND c.capability='agent_judged' AND q.state='active' AND q.realm=$4
                AND (c.snapshot IS NULL OR c.snapshot=$3)
                AND (c.valid_from IS NULL OR c.valid_from<=clock_timestamp()) AND (c.valid_until IS NULL OR c.valid_until>clock_timestamp())
                AND ({_HEALTH_REUSE_SQL}) AND ({_CODE_CONTEXT_SQL.format(workspace="$7")})
                AND EXISTS(SELECT 1 FROM am_claim_sources d WHERE d.claim_id=c.id)
                AND NOT EXISTS(SELECT 1 FROM am_claim_sources d JOIN am_sources s ON s.id=d.source_id WHERE d.claim_id=c.id
                    AND (s.state<>'active' OR s.body IS NULL OR s.revision<>d.source_revision OR s.binding_id<>$1 OR s.realm<>$4
                    OR (s.snapshot IS NOT NULL AND s.snapshot IS DISTINCT FROM $3)))
            ), lexical_candidates AS (
                SELECT id,row_number() OVER(ORDER BY cardinality(ARRAY(SELECT unnest(lexical_tokens) INTERSECT SELECT unnest($2::text[]))) DESC,id) AS rank
                FROM eligible WHERE lexical_tokens && $2::text[]
                ORDER BY cardinality(ARRAY(SELECT unnest(lexical_tokens) INTERSECT SELECT unnest($2::text[]))) DESC,id LIMIT $5
            ), entity_candidates AS (
                SELECT c.id,row_number() OVER(ORDER BY count(*) DESC,c.id) AS rank
                FROM eligible c JOIN am_entities e ON e.claim_id=c.id WHERE e.search_name=ANY($6::text[])
                GROUP BY c.id ORDER BY count(*) DESC,c.id LIMIT $5
            ), arms AS (
                SELECT id,rank,'lexical'::text AS arm FROM lexical_candidates
                UNION ALL SELECT id,rank,'entity' FROM entity_candidates
            ), fused AS (
                SELECT id,sum(1.0/(60+rank)) AS score,array_agg(arm ORDER BY arm) AS arms
                FROM arms GROUP BY id ORDER BY score DESC,id LIMIT $5
            ) SELECT c.*,f.arms FROM fused f JOIN eligible c ON c.id=f.id ORDER BY f.score DESC,c.id""",
                binding_id, list(dict.fromkeys(lexical_tokens)), snapshot, current.realm, limit,
                list(dict.fromkeys(_entity(token) for token in lexical_tokens)), code_workspace_id)
            claim_ids = tuple(row["id"] for row in rows)
            relations = await self._lexical_relations(
                connection, binding_id, claim_ids, snapshot,
                code_workspace_id=code_workspace_id, workspace_scoped=True)
            dependencies = await connection.fetch("""SELECT DISTINCT source_id FROM am_claim_sources WHERE claim_id=ANY($1::text[])
                UNION SELECT source_id FROM am_relation_sources WHERE relation_id=ANY($2::text[]) ORDER BY source_id""",
                list(claim_ids), [row["id"] for row in relations])
            inputs = {row["source_id"] for row in dependencies}
            relation_claims = await connection.fetch("""SELECT DISTINCT claim_id FROM am_relation_claims WHERE relation_id=ANY($1::text[])
                UNION SELECT unnest($2::text[]) AS claim_id""", [row["id"] for row in relations],
                sorted({endpoint for row in relations for endpoint in (row["left_id"], row["right_id"])}))
            for item in relation_claims:
                sources = await connection.fetch("SELECT source_id FROM am_claim_sources WHERE claim_id=$1", item["claim_id"])
                inputs.update(row["source_id"] for row in sources)
            if len(inputs) > 128:
                raise DomainError("MANIFEST_TOO_LARGE", "The complete lexical and relation source lineage exceeds the input limit")
            sources = []
            for source_id in sorted(inputs):
                source = await self._source_row(connection, binding_id, source_id, snapshot, True)
                sources.append({"id": source_id, "revision": source["revision"]})
            admission = await self._new_caller_admission(connection, clock, current, binding_id, "caller_recall",
                request_digest, snapshot,
                claims=tuple(RevisionRef(id=claim["id"], revision=claim["revision"]) for claim in rows),
                sources=tuple(RevisionRef.model_validate(source) for source in sources),
                relation_ids=tuple(relation["id"] for relation in relations), code_workspace_id=code_workspace_id)
            return [(await self._claim(connection, claim), tuple(claim["arms"])) for claim in rows], admission

    async def _recheck_nonmodel(self, connection, clock, actor: Principal, admission: NonmodelAdmission):
        row = await connection.fetchrow("""SELECT * FROM am_admissions WHERE id=$1 AND kind='nonmodel'
            AND deadline>clock_timestamp()""", admission.id)
        if row is None or self._nonmodel_admission(row) != admission:
            raise DomainError('ADMISSION_STALE', 'The durable nonmodel input admission expired or changed')
        current = await self._actor(connection, actor, admission.binding_id, (Role.AGENT, Role.OPERATOR))
        if (current.credential_id, current.generation, current.realm) != (
            admission.credential_id, admission.credential_generation, admission.realm):
            raise DomainError('ADMISSION_STALE', 'The admitted credential changed')
        policy = await self._selection_contract(connection, current, admission.binding_id)
        if (policy['revision'], policy['epoch'], policy['binding_revision'], clock['deletion_generation']) != (
            admission.policy_revision, admission.policy_epoch, admission.binding_revision, admission.deletion_generation):
            raise DomainError('ADMISSION_STALE', 'The binding, selection policy or deletion generation changed')
        saved_health = _decode(row['health_manifest'])
        if row['purpose'] == 'health_work':
            live_health, _ = await self._health_work_manifest(
                connection, admission.binding_id, saved_health['pending_id'], admission.snapshot)
        elif row['purpose'] == 'health_claim':
            live_health, _ = await self._claim_review_manifest(connection, admission.binding_id,
                admission.claim_ids[0], admission.snapshot, saved_health['nominated'])
        elif row['purpose'] == 'health_feedback':
            live_health, _ = await self._feedback_health_manifest(
                connection, admission.binding_id, saved_health['feedback_ref'], admission.snapshot)
        else:
            live_health = await self._admitted_health_manifest(connection, admission.binding_id,
                admission.claim_ids, admission.relation_ids,
                code_workspace_id=saved_health['workspace']['id'], workspace_scoped=saved_health['workspace']['scoped'])
            if row["purpose"] == "source_selection":
                live_health["source_judgment"] = await self._source_judgment_health_manifest(
                    connection, admission.binding_id, admission.snapshot,
                    [item["input"] for item in saved_health.get("source_judgment", ())],
                )
        if live_health != saved_health:
            raise DomainError('ADMISSION_STALE', 'An actual health, code, review, policy or work dependency changed')
        if admission.pending_id is not None:
            pending = await connection.fetchrow("""SELECT * FROM am_pending_judgments WHERE id=$1 AND binding_id=$2
                AND kind='cleanup' AND state IN ('pending','held') AND (snapshot IS NULL OR snapshot=$3)""",
                admission.pending_id, admission.binding_id, admission.snapshot)
            if pending is None:
                raise DomainError('ADMISSION_STALE', 'The admitted cleanup item is no longer pending')
            claims, sources = await self._judgment_inputs(connection, admission.binding_id, admission.snapshot, pending['claim_ids'])
            if [item.model_dump() for item in claims] != _decode(row['claim_revisions']) or sources != admission.sources:
                raise DomainError('ADMISSION_STALE', 'The eligible cleanup manifest changed')
        for item in admission.sources:
            source = await self._source_row(connection, admission.binding_id, item.id, admission.snapshot, True)
            if source['revision'] != item.revision:
                raise DomainError('ADMISSION_STALE', 'An actual source revision changed')
        revisions = {item['id']: item['revision'] for item in _decode(row['claim_revisions'])}
        for claim_id in admission.claim_ids:
            claim = await self._claim_row(connection, admission.binding_id, claim_id, admission.snapshot)
            if claim['capability'] != 'agent_judged' or claim['revision'] != revisions.get(claim_id):
                raise DomainError('ADMISSION_STALE', 'An actual candidate origin or revision changed')
            if row['purpose'] not in {'health_claim', 'health_work'}:
                await self._reuse_claim(connection, claim)
        if row['purpose'] not in {'health_claim', 'health_work', 'health_feedback'}:
            relations = await self._lexical_relations(connection, admission.binding_id, admission.claim_ids, admission.snapshot,
                code_workspace_id=saved_health['workspace']['id'], workspace_scoped=saved_health['workspace']['scoped'])
            if tuple(item['id'] for item in relations) != tuple(row['relation_ids']):
                raise DomainError('ADMISSION_STALE', 'The complete relation snapshot changed')
        if row['purpose'] == 'source_selection':
            await self._recheck_rejection_inputs(connection, row)
        return row

    async def recheck_judgment_admission(
        self, actor: Principal, binding_id: str, admission_id: str, request_digest: str,
        snapshot: str | None, *, purpose: str,
    ) -> None:
        """Recheck the original durable inputs without refreshing or consuming their authority."""
        async with self._tx() as (connection, clock):
            current = await self._actor(connection, actor, binding_id, (Role.AGENT, Role.OPERATOR))
            row = await connection.fetchrow("""SELECT * FROM am_admissions
                WHERE id=$1 AND binding_id=$2 AND kind='nonmodel' AND purpose=$3
                AND purpose IN ('source_selection','claim_judgment','health_work')""",
                admission_id, binding_id, purpose)
            if row is None or row["request_digest"] != request_digest or row["snapshot"] != snapshot:
                raise DomainError("ADMISSION_STALE", "The original judgment input admission changed")
            await self._recheck_nonmodel(connection, clock, current, self._nonmodel_admission(row))

    async def recall_admission(self, actor: Principal, binding_id: str, admission_id: str, request_digest: str, snapshot: str | None) -> tuple[NonmodelAdmission, list[Claim]]:
        async with self._tx() as (connection, clock):
            current = await self._actor(connection, actor, binding_id, (Role.AGENT, Role.OPERATOR))
            row = await connection.fetchrow("SELECT * FROM am_admissions WHERE id=$1 AND binding_id=$2 AND purpose='caller_recall' AND kind='nonmodel'", admission_id, binding_id)
            if row is None or row["request_digest"] != request_digest or row["snapshot"] != snapshot:
                raise DomainError("ADMISSION_STALE", "The saved candidate manifest belongs to a different request")
            admission = self._nonmodel_admission(row)
            await self._recheck_nonmodel(connection, clock, current, admission)
            claims = [await self._claim(connection, await self._claim_row(connection, binding_id, claim_id, snapshot)) for claim_id in admission.claim_ids]
            return admission, claims

    async def _relation_row(
        self, connection, binding_id: str, relation_id: str, snapshot: str | None, *,
        reuse: bool = True, code_workspace_id: str | None = None, workspace_scoped: bool = False,
    ):
        row = await connection.fetchrow("SELECT * FROM am_relations WHERE id=$1 AND binding_id=$2 AND state='active'", relation_id, binding_id)
        if row is None:
            raise DomainError("RELATION_INELIGIBLE", "The relation is no longer current")
        sources = await self._dependencies(connection, "am_relation_sources", "relation_id", relation_id, snapshot, True)
        manifest = await connection.fetch("SELECT claim_id FROM am_relation_claims WHERE relation_id=$1 ORDER BY claim_id", relation_id)
        if not sources or not manifest:
            raise DomainError("RELATION_INELIGIBLE", "The complete relation input manifest is unavailable")
        claims = {claim_id: await self._claim_row(connection, binding_id, claim_id, snapshot)
            for claim_id in {row["left_id"], row["right_id"], *(item["claim_id"] for item in manifest)}}
        if reuse:
            for claim in claims.values():
                await self._reuse_claim(connection, claim)
                if workspace_scoped:
                    await self._require_workspace_claim(connection, claim, code_workspace_id)
        if row["judgment_id"] is not None:
            judgment = await connection.fetchrow("""SELECT * FROM am_claim_judgments
                WHERE id=$1 AND binding_id=$2 AND state='active'""", row["judgment_id"], binding_id)
            if judgment is None or (judgment["snapshot"] is not None and judgment["snapshot"] != snapshot):
                raise DomainError("RELATION_INELIGIBLE", "The caller judgment is no longer current")
            assertions = _decode(judgment["relations"])
            if assertions is None or not any(
                assertion["left_id"] == row["left_id"]
                and assertion["right_id"] == row["right_id"]
                and (
                    "duplicates" if assertion["relation"] == "duplicate"
                    else assertion["relation"]
                ) == row["kind"]
                and assertion["reason"] == row["reason"]
                for assertion in assertions
            ):
                raise DomainError(
                    "RELATION_INELIGIBLE",
                    "The relation is not an assertion of its owning judgment",
                )
            claim_revisions = {item["id"]: item["revision"] for item in _decode(judgment["claims"])}
            source_revisions = {item["id"]: item["revision"] for item in _decode(judgment["sources"])}
            if claim_revisions != {claim_id: claim["revision"] for claim_id, claim in claims.items()} or source_revisions != {
                source["id"]: source["revision"] for source in sources
            }:
                raise DomainError("RELATION_INELIGIBLE", "The exact caller judgment input revisions are no longer current")
        return row

    async def relations(self, actor: Principal, binding_id: str, claim_ids: tuple[str, ...], snapshot: str | None = None, *,
        code_workspace_id: str | None = None, workspace_scoped: bool = False) -> list[Relation]:
        if len(claim_ids) > 100:
            raise DomainError("MANIFEST_TOO_LARGE", "The relation input set is too large")
        async with self._tx() as (connection, _):
            await self._actor(connection, actor, binding_id)
            rows = connection.cursor("""SELECT r.* FROM am_relations r WHERE r.binding_id=$1 AND r.state='active' AND r.judgment_id IS NOT NULL
                AND (r.left_id=ANY($2::text[]) OR r.right_id=ANY($2::text[])) ORDER BY r.id""", binding_id, list(claim_ids), prefetch=64)
            result = []
            seen = set()
            async for row in rows:
                key = (row["left_id"], row["right_id"], row["kind"])
                if key in seen:
                    continue
                try:
                    await self._relation_row(connection, binding_id, row["id"], snapshot,
                        code_workspace_id=code_workspace_id, workspace_scoped=workspace_scoped)
                except DomainError as error:
                    if error.code not in {"RELATION_INELIGIBLE", "INPUT_INELIGIBLE", "CLAIM_INELIGIBLE"}:
                        raise
                    continue
                seen.add(key)
                if len(result) == 128:
                    raise DomainError("RELATION_CONTEXT_OVERFLOW", "The complete current relation set exceeds the bounded context")
                result.append(Relation(
                    id=row["id"], left_id=row["left_id"], right_id=row["right_id"],
                    kind="duplicate" if row["kind"] == "duplicates" else row["kind"],
                    reason=row["reason"],
                ))
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
        await self._point_operation(connection, operation_id, source_id)
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
            operation = await self._new_operation(connection, current, command.binding_id, "propose_rule", "captured")
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
        elif kind == "selection":
            inputs = await connection.fetch(
                "SELECT source_id FROM am_selection_sources WHERE selection_id=$1",
                ref,
            )
            claims = await connection.fetch(
                "SELECT id FROM am_claims WHERE selection_id=$1",
                ref,
            )
            extraction_floors = (
                tuple(("extract_source", item["source_id"]) for item in inputs)
                if row["label"] == "remember" and claims else ()
            )
            artifacts = tuple(sorted({
                *artifacts,
                *(("claim", item["id"]) for item in claims),
                *extraction_floors,
            }))
        elif kind == "judgment":
            relations = await connection.fetch("SELECT id FROM am_relations WHERE judgment_id=$1", ref)
            artifacts = tuple(sorted({*artifacts, *(("relation", item["id"]) for item in relations)}))
        elif kind == "reflection":
            queries = await connection.fetch("""SELECT DISTINCT j.query_source_id FROM am_jobs j JOIN am_operations o ON o.id=j.operation_id
                WHERE o.artifact_id=$1 AND o.binding_id=$2 AND j.kind='reflect' AND j.query_source_id IS NOT NULL""", ref, binding_id)
            source_ids = [item["query_source_id"] for item in queries]
        elif kind in {"proposal", "rule"}:
            proposal_id = ref if kind == "proposal" else row["proposal_id"]
            proposal = await connection.fetchrow("SELECT * FROM am_proposals WHERE id=$1", proposal_id)
            source_ids = [proposal["source_id"]]
            artifacts = tuple(sorted({*artifacts, ("proposal", proposal_id)}))
        elif kind == "health_event":
            source_ids = [row["reason_source_id"]] if row["reason_source_id"] else []
        elif kind in {"operation", "feedback"}:
            if kind == "operation" and row["artifact_id"]:
                descendants, derived = await self._deletion_targets(connection, binding_id, row["artifact_id"])
                artifacts = tuple(sorted({*artifacts, *derived}))
                return await self._source_descendants(connection, binding_id, descendants,
                    [target for artifact_kind, target in artifacts if artifact_kind != "extract_source"]), artifacts
            if row["source_id"]:
                source = await connection.fetchrow("SELECT * FROM am_sources WHERE id=$1", row["source_id"])
                if kind == "feedback" or source["operation_id"] == row["id"]:
                    source_ids = [source["id"]]
        sources = await connection.fetch("SELECT id,binding_id,realm,origin_key,state FROM am_sources WHERE id=ANY($1::text[]) ORDER BY id", source_ids)
        if len(sources) != len(set(source_ids)) or any(source["binding_id"] != binding_id or source["realm"] != self.settings.realm for source in sources):
            raise _denied()
        return await self._source_descendants(connection, binding_id, list(sources),
            [target for artifact_kind, target in artifacts if artifact_kind != "extract_source"]), artifacts

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

    def _deletion_edges(self) -> str:
        return """edges(parent_id,child_id) AS (
            SELECT d.source_id,p.source_id FROM am_proposal_sources d JOIN am_proposals p ON p.id=d.proposal_id
            UNION SELECT unnest(source_ids),query_source_id FROM am_jobs WHERE kind='reflect' AND query_source_id IS NOT NULL
            UNION SELECT unnest(claim_ids),query_source_id FROM am_jobs WHERE kind='reflect' AND query_source_id IS NOT NULL
            UNION SELECT source_id,claim_id FROM am_claim_sources
            UNION SELECT source_id,selection_id FROM am_selection_sources
            UNION SELECT source_id,relation_id FROM am_relation_sources
            UNION SELECT claim_id,relation_id FROM am_relation_claims
            UNION SELECT source_id,reflection_id FROM am_reflection_sources
            UNION SELECT claim_id,reflection_id FROM am_reflection_claims
            UNION SELECT source_id,proposal_id FROM am_proposal_sources
            UNION SELECT d->>'id',j.id FROM am_claim_judgments j CROSS JOIN LATERAL jsonb_array_elements(j.sources) d
            UNION SELECT d->>'id',j.id FROM am_claim_judgments j CROSS JOIN LATERAL jsonb_array_elements(j.claims) d
            UNION SELECT source_id,id FROM am_operations WHERE source_id IS NOT NULL
            UNION SELECT artifact_id,id FROM am_operations WHERE artifact_id IS NOT NULL
            UNION SELECT proposal_id,id FROM am_rules
            UNION SELECT target_ref,source_id FROM am_feedback WHERE source_id IS NOT NULL
            UNION SELECT id,source_id FROM am_feedback WHERE source_id IS NOT NULL
            UNION SELECT source_id,id FROM am_feedback WHERE source_id IS NOT NULL
            UNION SELECT unnest(rejected_source_ids),source_id FROM am_feedback WHERE source_id IS NOT NULL
            UNION SELECT target_ref,id FROM am_health_events WHERE target_ref IS NOT NULL AND kind<>'feedback_resolution'
            UNION SELECT target_ref,reason_source_id FROM am_health_events
                WHERE kind='feedback_resolution' AND target_ref IS NOT NULL AND reason_source_id IS NOT NULL
            UNION SELECT payload->>'assessment_event_id',id FROM am_health_events
                WHERE kind='health_assessment' AND payload ? 'assessment_event_id'
            UNION SELECT d.value,p.id FROM am_pending_judgments p
                CROSS JOIN LATERAL jsonb_array_elements_text(
                    COALESCE(p.health_payload->'session_observation_ids','[]')) d WHERE p.kind='health'
            UNION SELECT unnest(source_ids),id FROM am_health_events
            UNION SELECT unnest(claim_ids),id FROM am_health_events
            UNION SELECT id,reason_source_id FROM am_health_events WHERE reason_source_id IS NOT NULL
            UNION SELECT reason_source_id,id FROM am_health_events WHERE reason_source_id IS NOT NULL
            UNION SELECT workspace_id,id FROM am_code_observations
            UNION SELECT unnest(source_ids),id FROM am_pending_judgments WHERE kind='health'
            UNION SELECT unnest(claim_ids),id FROM am_pending_judgments WHERE kind='health'
            UNION SELECT d->>'id',o.id FROM am_session_observations o
                CROSS JOIN LATERAL jsonb_array_elements(COALESCE(o.payload->'source_refs','[]')) d
            UNION SELECT d->>'id',o.id FROM am_session_observations o
                CROSS JOIN LATERAL jsonb_array_elements(COALESCE(o.payload->'claim_refs','[]')) d
            UNION SELECT s.id,o.id FROM am_session_observations o JOIN am_sources s
                ON s.binding_id=o.binding_id AND s.producer_generation=o.credential_generation
                AND o.payload->'origin_keys' ? s.origin_key
                JOIN am_operations p ON p.id=s.operation_id AND p.credential_id=o.credential_id
        )"""

    async def _floored_artifact_ids(self, connection, tokens: set[str]) -> list[str]:
        if not tokens:
            return []
        tables = {"claim": "am_claims", "selection": "am_source_selections", "relation": "am_relations",
            "reflection": "am_reflections", "proposal": "am_proposals", "rule": "am_rules",
            "operation": "am_operations", "feedback": "am_feedback", "judgment": "am_claim_judgments",
            "pending": "am_pending_judgments", "health_event": "am_health_events",
            "session_observation": "am_session_observations", "code_observation": "am_code_observations",
            "health_workspace": "am_code_workspaces"}
        refs = []
        for kind, table in tables.items():
            refs.extend((kind, row["id"]) for row in await connection.fetch(f"SELECT id FROM {table}"))
        mapped = await asyncio.to_thread(self.journal.artifact_tokens, tuple(refs))
        return [ref for (_, ref), token in mapped.items() if token in tokens]

    async def _source_descendants(self, connection, binding_id: str, sources: list, artifact_ids: list[str] | None = None) -> list:
        rows = await connection.fetch(f"""WITH RECURSIVE {self._deletion_edges()}, affected(id) AS (
            SELECT unnest($1::text[]) UNION SELECT e.child_id FROM affected a JOIN edges e ON e.parent_id=a.id
        ) SELECT s.id,s.binding_id,s.realm,s.origin_key,s.state FROM affected a JOIN am_sources s ON s.id=a.id
            WHERE s.binding_id=$2 AND s.realm=$3 ORDER BY s.id""",
            [*(source["id"] for source in sources), *(artifact_ids or [])], binding_id, self.settings.realm)
        return list(rows)

    async def _refresh_deletion_floor(self, connection, binding_id: str, sources: list) -> tuple[list, dict, list[dict]]:
        current = await self._source_descendants(connection, binding_id, sources)
        known = {source["id"] for source in sources}
        additional = [source for source in current if source["id"] not in known]
        if additional:
            await self._append_deletion_intent(binding_id, additional)
        journal, entries = await asyncio.to_thread(self.journal._snapshot)
        return current, journal, entries

    async def _scrub_purge_floors(self, connection) -> None:
        floors = await connection.fetch("SELECT kind,token FROM am_floors WHERE kind LIKE 'purge_%'")
        if not floors:
            return
        artifact_floors = {row["token"] for row in floors if row["kind"] == "purge_artifact"}
        artifact_ids = await self._floored_artifact_ids(connection, artifact_floors)
        sources = await connection.fetch(f"""WITH RECURSIVE {self._deletion_edges()}, affected(id) AS (
            SELECT s.id FROM am_sources s WHERE EXISTS(SELECT 1 FROM am_floors f
                WHERE (f.kind='purge_source' AND f.token=s.source_token) OR (f.kind='purge_origin' AND f.token=s.origin_token))
            UNION SELECT unnest($1::text[])
            UNION SELECT e.child_id FROM affected a JOIN edges e ON e.parent_id=a.id
        ) SELECT s.id FROM am_sources s JOIN affected a ON a.id=s.id""", artifact_ids)
        source_ids = [row["id"] for row in sources]
        tables = {"claim": "am_claims", "selection": "am_source_selections", "relation": "am_relations",
            "reflection": "am_reflections", "proposal": "am_proposals", "rule": "am_rules",
            "operation": "am_operations", "feedback": "am_feedback", "judgment": "am_claim_judgments",
            "health_event": "am_health_events", "session_observation": "am_session_observations",
            "code_observation": "am_code_observations", "health_workspace": "am_code_workspaces"}
        refs = []
        for kind, table in tables.items():
            refs.extend((kind, row["id"]) for row in await connection.fetch(f"SELECT id FROM {table}"))
        refs = tuple(refs)
        mapped = await asyncio.to_thread(self.journal.artifact_tokens, refs)
        targets = {kind: [ref for (item_kind, ref), token in mapped.items()
            if item_kind == kind and token in artifact_floors] for kind in tables}
        selected = await connection.fetch("SELECT id FROM am_claims WHERE selection_id=ANY($1::text[])", targets["selection"])
        derived = await connection.fetch("SELECT DISTINCT claim_id FROM am_claim_sources WHERE source_id=ANY($1::text[])", source_ids)
        claim_ids = sorted({*targets["claim"], *(row["id"] for row in selected), *(row["claim_id"] for row in derived)})
        await connection.execute("""UPDATE am_sources SET body=NULL,state='purged'
            WHERE id=ANY($1::text[]) AND state<>'active'
            AND (body IS NOT NULL OR state IS DISTINCT FROM 'purged')""", source_ids)
        await connection.execute("""UPDATE am_claims SET draft=NULL,embedding=NULL,lexical_tokens='{}',state='retracted'
            WHERE id=ANY($1::text[]) AND (draft IS NOT NULL OR embedding IS NOT NULL
                OR lexical_tokens IS DISTINCT FROM '{}'::text[] OR state IS DISTINCT FROM 'retracted')""", claim_ids)
        await connection.execute("UPDATE am_spans SET quote=NULL WHERE claim_id=ANY($1::text[]) AND quote IS NOT NULL", claim_ids)
        await connection.execute("DELETE FROM am_entities WHERE claim_id=ANY($1::text[])", claim_ids)
        await connection.execute("""UPDATE am_relations SET reason=NULL,state='retracted' WHERE (id=ANY($1::text[])
            OR id IN (SELECT relation_id FROM am_relation_sources WHERE source_id=ANY($2::text[]))
            OR id IN (SELECT relation_id FROM am_relation_claims WHERE claim_id=ANY($3::text[])))
            AND (reason IS NOT NULL OR state IS DISTINCT FROM 'retracted')""", targets["relation"], source_ids, claim_ids)
        await connection.execute("""UPDATE am_reflections SET draft=NULL,state='retracted' WHERE (id=ANY($1::text[])
            OR id IN (SELECT reflection_id FROM am_reflection_sources WHERE source_id=ANY($2::text[]))
            OR id IN (SELECT reflection_id FROM am_reflection_claims WHERE claim_id=ANY($3::text[])))
            AND (draft IS NOT NULL OR state IS DISTINCT FROM 'retracted')""", targets["reflection"], source_ids, claim_ids)
        await connection.execute("""UPDATE am_proposals SET selector='{}',exceptions='[]',state='retracted'
            WHERE (id=ANY($1::text[]) OR id IN (SELECT proposal_id FROM am_proposal_sources WHERE source_id=ANY($2::text[])))
            AND (selector IS DISTINCT FROM '{}'::jsonb OR exceptions IS DISTINCT FROM '[]'::jsonb
                OR state IS DISTINCT FROM 'retracted')""", targets["proposal"], source_ids)
        await connection.execute("""UPDATE am_receipts SET result=result-'request' WHERE kind='reflect' AND result ? 'request'
            AND target_id IN (SELECT id FROM am_operations WHERE artifact_id IN (SELECT id FROM am_reflections WHERE draft IS NULL))""")
        await connection.execute("""UPDATE am_claim_judgments j SET relations=NULL,reason=NULL,state='retracted' WHERE (id=ANY($1::text[])
            OR EXISTS(SELECT 1 FROM jsonb_array_elements(j.sources) d WHERE d->>'id'=ANY($2::text[]))
            OR EXISTS(SELECT 1 FROM jsonb_array_elements(j.claims) d WHERE d->>'id'=ANY($3::text[]))
            OR id IN (SELECT judgment_id FROM am_relations WHERE reason IS NULL AND judgment_id IS NOT NULL))
            AND (relations IS NOT NULL OR reason IS NOT NULL OR state IS DISTINCT FROM 'retracted')""",
            targets["judgment"], source_ids, claim_ids)
        await connection.execute("""UPDATE am_source_selections SET reason=NULL,rejection_comparisons='[]'
            WHERE (id=ANY($1::text[]) OR source_id=ANY($2::text[]))
            AND (reason IS NOT NULL OR rejection_comparisons IS DISTINCT FROM '[]'::jsonb)""", targets["selection"], source_ids)
        await connection.execute("""UPDATE am_feedback SET reason=NULL
            WHERE (id=ANY($1::text[]) OR source_id=ANY($2::text[]) OR rejected_source_ids && $2::text[])
            AND reason IS NOT NULL""", targets["feedback"], source_ids)
        await self._apply_health_deletions(connection, scrub=True)

    async def _reopen_source_work(
        self, connection, source_ids: tuple[str, ...],
    ) -> None:
        if not source_ids:
            return
        rows = await connection.fetch(
            """SELECT s.id,s.binding_id,s.snapshot FROM am_sources s
            WHERE s.id=ANY($1::text[]) AND s.realm=$2
            AND s.state='active' AND s.body IS NOT NULL
            AND s.speaker NOT IN ('memory','agent_note')
            AND NOT COALESCE((
                SELECT range_agg(int8range(q.byte_start::bigint,q.byte_end::bigint,'[)'))
                FROM am_source_selections q
                WHERE q.binding_id=s.binding_id AND q.source_id=s.id
                AND q.source_revision=s.revision AND q.state='active'
                AND q.label IN ('remember','discard')
                AND q.coverage='complete_window' AND q.policy_revision=$3
                    AND (q.request_snapshot IS NULL OR q.request_snapshot IS NOT DISTINCT FROM s.snapshot)
            ), '{}'::int8multirange)
                @> int8range(0,octet_length(s.body)::bigint,'[)')
            ORDER BY s.binding_id,s.id""",
            list(source_ids), self.settings.realm, selection_contract_revision(),
        )
        withdrawn = set(await self._derivation_sources(
            connection, tuple(row["id"] for row in rows),
        ))
        for source in rows:
            if source["id"] in withdrawn:
                continue
            await connection.execute(
                """UPDATE am_pending_judgments p
                SET state=CASE WHEN p.kind='legacy_revalidation' AND EXISTS(
                    SELECT 1 FROM unnest(p.source_ids) AS input(id)
                    LEFT JOIN am_sources s ON s.id=input.id
                    WHERE s.id IS NULL OR s.state<>'active' OR s.body IS NULL
                    OR s.speaker IN ('memory','agent_note')
                ) THEN 'held' ELSE 'pending' END,
                resolved_at=NULL
                WHERE p.binding_id=$1 AND $2=ANY(p.source_ids)
                AND p.kind IN ('source_selection','legacy_revalidation')
                AND p.state='resolved'
                    AND NOT COALESCE((
                        SELECT range_agg(int8range(q.byte_start::bigint,q.byte_end::bigint,'[)'))
                        FROM am_source_selections q JOIN am_sources original ON original.id=q.source_id
                        WHERE q.binding_id=p.binding_id AND q.source_id=$2
                          AND q.source_revision=original.revision AND q.state='active'
                          AND q.label IN ('remember','discard') AND q.coverage='complete_window'
                          AND q.policy_revision=$3
                          AND (q.request_snapshot IS NULL OR q.request_snapshot IS NOT DISTINCT FROM p.snapshot)
                    ),'{}'::int8multirange) @> int8range(0,
                        (SELECT octet_length(body)::bigint FROM am_sources WHERE id=$2),'[)')""",
                source["binding_id"], source["id"], selection_contract_revision(),
            )
            exists = await connection.fetchval(
                """SELECT EXISTS(SELECT 1 FROM am_pending_judgments p
                WHERE p.binding_id=$1 AND $2=ANY(p.source_ids)
                AND p.kind IN ('source_selection','legacy_revalidation')
                AND p.state IN ('pending','held'))""",
                source["binding_id"], source["id"],
            )
            if not exists:
                await connection.execute(
                    """INSERT INTO am_pending_judgments(
                        id,binding_id,kind,source_ids,snapshot
                    ) VALUES($1,$2,'source_selection',$3,$4)""",
                    _id("pending"), source["binding_id"], [source["id"]],
                    source["snapshot"],
                )


    async def _prune_rejection_index(self, connection) -> None:
        await connection.execute("""DELETE FROM am_rejection_evidence e WHERE
            NOT EXISTS(SELECT 1 FROM am_sources s WHERE s.id=e.source_id
                AND s.binding_id=e.binding_id AND s.state='active'
                AND s.body IS NOT NULL AND s.revision=e.source_revision)
            OR EXISTS(SELECT 1 FROM am_source_selections q WHERE q.id=e.rejection_id
                AND (q.state<>'active' OR q.label<>'discard'))
            OR EXISTS(SELECT 1 FROM am_feedback f WHERE f.id=e.rejection_id
                AND (f.state<>'active' OR f.kind<>'reject'))""")
        await connection.execute("""DELETE FROM am_rejection_tokens t WHERE NOT EXISTS(
            SELECT 1 FROM am_rejection_evidence e
            WHERE e.binding_id=t.binding_id AND e.rejection_id=t.rejection_id)""")


    async def _apply_floors(self, connection, entries: list[dict], *, scrub: bool = False) -> tuple[int, int]:
        tokens = {(kind, token) for entry in entries for kind, field in (("source", "source_tokens"), ("origin", "origin_tokens"), ("artifact", "artifact_tokens")) for token in entry.get(field, [])}
        tokens.update((f"purge_{kind}", token) for entry in entries if entry.get("purge")
            for kind, field in (("source", "source_tokens"), ("origin", "origin_tokens"), ("artifact", "artifact_tokens"))
            for token in entry.get(field, []))
        if tokens:
            kinds, values = zip(*sorted(tokens))
            inserted = await connection.fetch("""INSERT INTO am_floors(kind,token) SELECT * FROM unnest($1::text[],$2::text[])
                ON CONFLICT DO NOTHING RETURNING kind""", list(kinds), list(values))
            scrub = scrub or any(row["kind"].startswith("purge_") for row in inserted)
        artifact_floors = {token for kind, token in tokens if kind == "artifact"}
        artifacts_retracted = 0
        reopen_source_ids = set()
        if artifact_floors:
            tables = {
                "claim": "am_claims", "relation": "am_relations", "reflection": "am_reflections",
                "proposal": "am_proposals", "rule": "am_rules", "operation": "am_operations", "feedback": "am_feedback",
                "selection": "am_source_selections",
                "judgment": "am_claim_judgments", "pending": "am_pending_judgments",
                "health_event": "am_health_events", "session_observation": "am_session_observations",
                "code_observation": "am_code_observations", "health_workspace": "am_code_workspaces",
            }
            refs = []
            for kind, table in tables.items():
                predicate = "" if kind == "selection" else " WHERE state<>'retracted'"
                refs.extend(
                    (kind, row["id"])
                    for row in await connection.fetch(f"SELECT id FROM {table}{predicate}")
                )
            mapped = await asyncio.to_thread(self.journal.artifact_tokens, tuple(refs))
            for kind, table in tables.items():
                ids = [ref for (item_kind, ref), token in mapped.items() if item_kind == kind and token in artifact_floors]
                if ids:
                    if kind == "selection":
                        affected = await connection.fetch(
                            """SELECT DISTINCT d.source_id
                            FROM am_source_selections q
                            JOIN am_selection_sources d ON d.selection_id=q.id
                            WHERE q.id=ANY($1::text[])
                            AND NOT EXISTS(
                                SELECT 1 FROM am_claims c WHERE c.selection_id=q.id
                            )""",
                            ids,
                        )
                        reopen_source_ids.update(row["source_id"] for row in affected)
                    retracted = await connection.fetch(
                        f"""UPDATE {table} SET state='retracted'
                        WHERE id=ANY($1::text[]) AND state<>'retracted'
                        RETURNING id""",
                        ids,
                    )
                    artifacts_retracted += len(retracted)
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
        await connection.execute("""UPDATE am_source_selections q SET state='retracted' WHERE state='active'
            AND EXISTS(SELECT 1 FROM am_selection_sources d JOIN am_sources s ON s.id=d.source_id
                WHERE d.selection_id=q.id AND (s.state<>'active' OR s.revision<>d.source_revision OR s.body IS NULL))""")
        await connection.execute("""UPDATE am_claims c SET state='retracted' WHERE c.state='active'
            AND EXISTS(SELECT 1 FROM am_source_selections q WHERE q.id=c.selection_id AND q.state<>'active')""")
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
        await connection.execute("""UPDATE am_claim_judgments j SET state='retracted' WHERE state='active' AND (
            EXISTS(SELECT 1 FROM jsonb_array_elements(j.sources) d LEFT JOIN am_sources s ON s.id=d->>'id'
                WHERE s.id IS NULL OR s.state<>'active' OR s.body IS NULL OR s.revision<>(d->>'revision')::bigint)
            OR EXISTS(SELECT 1 FROM jsonb_array_elements(j.claims) d LEFT JOIN am_claims c ON c.id=d->>'id'
                WHERE c.id IS NULL OR c.state<>'active' OR c.draft IS NULL OR c.revision<>(d->>'revision')::bigint)
            OR EXISTS(SELECT 1 FROM am_relations r WHERE r.judgment_id=j.id AND r.state='retracted'))""")
        await connection.execute("""WITH eligible AS (
            SELECT p.id,p.state,
                ARRAY(SELECT s.id FROM unnest(p.source_ids) WITH ORDINALITY input(id,ordinal)
                    JOIN am_sources s ON s.id=input.id WHERE s.binding_id=p.binding_id AND s.realm=$1
                    AND s.state='active' AND s.body IS NOT NULL
                    AND (s.snapshot IS NULL OR s.snapshot IS NOT DISTINCT FROM p.snapshot) ORDER BY input.ordinal) AS source_ids,
                ARRAY(SELECT c.id FROM unnest(p.claim_ids) WITH ORDINALITY input(id,ordinal)
                    JOIN am_claims c ON c.id=input.id WHERE c.binding_id=p.binding_id AND c.state='active'
                    AND c.draft IS NOT NULL ORDER BY input.ordinal) AS claim_ids
            FROM am_pending_judgments p WHERE p.kind='legacy_revalidation' AND p.state IN ('pending','held')
        ), desired AS (
            SELECT e.id,e.source_ids,e.claim_ids,CASE
                WHEN cardinality(e.source_ids)=0 THEN 'retracted'
                WHEN e.state='held' THEN 'held'
                WHEN EXISTS(SELECT 1 FROM am_sources s WHERE s.id=ANY(e.source_ids)
                    AND s.speaker IN ('memory','agent_note')) THEN 'held'
                ELSE 'pending' END AS state FROM eligible e
        ) UPDATE am_pending_judgments p SET source_ids=d.source_ids,claim_ids=d.claim_ids,state=d.state
            FROM desired d WHERE p.id=d.id AND (p.source_ids IS DISTINCT FROM d.source_ids
                OR p.claim_ids IS DISTINCT FROM d.claim_ids OR p.state IS DISTINCT FROM d.state)""", self.settings.realm)
        await connection.execute("""UPDATE am_pending_judgments p SET state='retracted' WHERE state IN ('pending','held')
            AND p.kind<>'legacy_revalidation'
            AND (EXISTS(SELECT 1 FROM am_sources s WHERE s.id=ANY(p.source_ids) AND s.state<>'active')
                OR EXISTS(SELECT 1 FROM am_claims c WHERE c.id=ANY(p.claim_ids) AND c.state<>'active'))""")
        await connection.execute("""UPDATE am_feedback f SET state='retracted' WHERE state<>'retracted' AND (
            EXISTS(SELECT 1 FROM am_sources s WHERE s.id=f.source_id AND (s.state<>'active' OR s.body IS NULL))
            OR EXISTS(SELECT 1 FROM am_sources s WHERE s.id=ANY(f.rejected_source_ids) AND (s.state<>'active' OR s.body IS NULL)))""")
        await connection.execute("""UPDATE am_reflections r SET state='retracted' WHERE state='active' AND (
            EXISTS(SELECT 1 FROM am_reflection_sources d JOIN am_sources s ON s.id=d.source_id
                WHERE d.reflection_id=r.id AND (s.state<>'active' OR s.revision<>d.source_revision OR s.body IS NULL))
            OR EXISTS(SELECT 1 FROM am_reflection_claims d JOIN am_claims c ON c.id=d.claim_id
                WHERE d.reflection_id=r.id AND c.state<>'active'))""")
        await connection.execute("""UPDATE am_rules r SET state='retracted',revision=revision+1 WHERE state='active'
            AND EXISTS(SELECT 1 FROM am_proposals p WHERE p.id=r.proposal_id AND p.state='retracted')""")
        await self._apply_health_deletions(connection, scrub=False)
        await connection.execute("""UPDATE am_operations o SET state='retracted',error_code='SOURCE_RETRACTED',
            source_pointer=NULL,capture_disposition=CASE WHEN source_id IS NOT NULL THEN 'retracted' ELSE capture_disposition END
            WHERE state<>'retracted' AND (
                EXISTS(SELECT 1 FROM am_sources s WHERE s.id=o.source_id AND s.state<>'active')
                OR EXISTS(SELECT 1 FROM am_reflections r WHERE r.id=o.artifact_id AND r.state='retracted')
                OR EXISTS(SELECT 1 FROM am_proposals p WHERE p.id=o.artifact_id AND p.state='retracted')
                OR EXISTS(SELECT 1 FROM am_source_selections q WHERE q.id=o.artifact_id AND q.state='retracted')
                OR EXISTS(SELECT 1 FROM am_claim_judgments j WHERE j.id=o.artifact_id AND j.state='retracted'))""")
        await connection.execute("""UPDATE am_operations SET source_pointer=NULL,capture_disposition='retracted'
            WHERE state='retracted' AND source_pointer IS NOT NULL""")
        await connection.execute("""UPDATE am_operations o SET state='selection_recorded' WHERE o.state='candidate_ready'
            AND EXISTS(SELECT 1 FROM am_source_selections q WHERE q.id=o.artifact_id AND q.state='active')
            AND NOT EXISTS(SELECT 1 FROM am_claims c WHERE c.selection_id=o.artifact_id AND c.state='active' AND c.draft IS NOT NULL)""")
        await self._reopen_source_work(
            connection, tuple(sorted(reopen_source_ids)),
        )
        await self._prune_rejection_index(connection)
        if scrub:
            await self._scrub_purge_floors(connection)
        return count, artifacts_retracted

    async def _reconcile_locked(self, connection, journal: dict, entries: list[dict], *, scrub: bool = False) -> int:
        source_tokens = {token for entry in entries for token in entry["source_tokens"]}
        origin_tokens = {token for entry in entries for token in entry["origin_tokens"]}
        artifact_ids = await self._floored_artifact_ids(connection,
            {token for entry in entries for token in entry.get("artifact_tokens", [])})
        descendants = await connection.fetch(f"""WITH RECURSIVE {self._deletion_edges()}, affected(id) AS (
            SELECT s.id FROM am_sources s WHERE s.realm=$3 AND (s.source_token=ANY($1::text[]) OR s.origin_token=ANY($2::text[]))
            UNION SELECT unnest($4::text[])
            UNION SELECT e.child_id FROM affected a JOIN edges e ON e.parent_id=a.id
        ) SELECT s.id,s.binding_id,s.origin_key,s.source_token,s.origin_token FROM affected a
            JOIN am_sources s ON s.id=a.id WHERE s.realm=$3 ORDER BY s.binding_id,s.id""",
            sorted(source_tokens), sorted(origin_tokens), self.settings.realm, artifact_ids)
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
        count, artifacts_retracted = await self._apply_floors(connection, entries, scrub=scrub)
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
        admissions = await connection.fetchval("""SELECT EXISTS(SELECT 1 FROM am_admissions a WHERE a.deadline>clock_timestamp()
            AND EXISTS(SELECT 1 FROM jsonb_array_elements(a.sources) input WHERE input->>'id'=ANY($1::text[])))""", source_ids)
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
                operation = await self._new_operation(connection, current, binding_id, "retract", "retracted")
                await connection.execute("UPDATE am_operations SET artifact_id=$2 WHERE id=$1", operation["id"], ref)
                result.update(operation_id=operation["id"])
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
        if command.contradicts_coverage():
            raise DomainError("CAPTURE_COVERAGE_INVALID", "Producer-reported coverage contradicts the replacement body length")
        corrected = command.model_copy(update={"kind": "correction"})
        payload = {"target_ref": target_ref, "command": corrected.digest_payload()}
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
            origin_digest = canonical_digest(corrected.digest_payload("idempotency_key"))
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
        await self._sync_deletion_journal()
        async with self._tx() as (connection, _):
            current = await self._actor(connection, actor, binding_id, (Role.OPERATOR,))
            receipt = await self._receipt(connection, current, binding_id, "purge", key, digest)
            if receipt:
                return dict(_decode(receipt["result"]))
            intent = await self._receipt(connection, current, binding_id, "purge_intent", key, digest)
            _, target = await self._ref_metadata(connection, binding_id, ref)
            sources, artifacts = await self._deletion_targets(connection, binding_id, ref)
            if target.get("state") not in {"retracted", "purged"} or any(source["state"] == "active" for source in sources):
                raise DomainError("RETRACTION_REQUIRED", "Commit logical retraction before physical purge")
            if intent is None:
                await self._save_receipt(connection, current, binding_id, "purge_intent", key, digest, ref, {"state": "pending"})
        try:
            await asyncio.to_thread(self.journal.append, binding_id, tuple(source["id"] for source in sources),
                tuple(source["origin_key"] for source in sources), artifacts, purge=True)
            await self._sync_deletion_journal()
            async with self._tx() as (connection, _):
                current = await self._actor(connection, actor, binding_id, (Role.OPERATOR,))
                receipt = await self._receipt(connection, current, binding_id, "purge", key, digest)
                if receipt:
                    return dict(_decode(receipt["result"]))
                sources, artifacts = await self._deletion_targets(connection, binding_id, ref)
                source_ids = [source["id"] for source in sources]
                derived = await connection.fetch("SELECT DISTINCT claim_id FROM am_claim_sources WHERE source_id=ANY($1::text[])", source_ids)
                claim_ids = {*(item["claim_id"] for item in derived), *(target for kind, target in artifacts if kind == "claim")}
                epoch = await self._tick(connection)
                result = await self._deletion_status(connection, source_ids, epoch, "purged")
                result.update(ref=ref, database_body_rows_removed=len(source_ids), database_claim_rows_scrubbed=len(claim_ids),
                    storage_media_erasure="unknown", wal_and_backup_erasure="unknown")
                await self._save_receipt(connection, current, binding_id, "purge", key, digest, ref, result)
                return result
        except DomainError as error:
            raise await self._deletion_error(error) from error
        except OSError:
            raise DomainError("DELETION_BARRIER", "Purge intent durability is unknown; reconcile the independent journal",
                status=503, effect=EffectState.UNKNOWN) from None

    async def delivery(self, actor: Principal, binding_id: str, admissions: tuple[()], rule_versions: tuple[tuple[str, int, str], ...], snapshot: str | None = None, relation_ids: tuple[str, ...] = (), *, nonmodel_admission: NonmodelAdmission | None = None, selected_claim_ids: tuple[str, ...] = ()) -> dict:
        if len(admissions) > 16 or len(rule_versions) > 1024 or len(relation_ids) > 128 or len(set(relation_ids)) != len(relation_ids):
            raise DomainError("MANIFEST_TOO_LARGE", "The final delivery manifest is too large")
        async with self._tx() as (connection, clock):
            current = await self._actor(connection, actor, binding_id)
            workspace_id = None
            if admissions or (nonmodel_admission is None and (selected_claim_ids or relation_ids)):
                raise DomainError("CONTEXT_STALE", "Caller-judged delivery requires its actual nonmodel admission")
            if nonmodel_admission is not None:
                if nonmodel_admission.binding_id != binding_id or nonmodel_admission.snapshot != snapshot:
                    raise DomainError("CONTEXT_STALE", "Delivery requires its actual request-bound admission")
                if len(selected_claim_ids) > 20 or len(set(selected_claim_ids)) != len(selected_claim_ids) or not set(selected_claim_ids).issubset(nonmodel_admission.claim_ids):
                    raise DomainError("CONTEXT_STALE", "Delivered claims must be a bounded subset of the admitted pool")
                try:
                    manifest = await self._recheck_nonmodel(connection, clock, current, nonmodel_admission)
                except DomainError:
                    raise DomainError("CONTEXT_STALE", "The delivered actual inputs are no longer current") from None
                if manifest["purpose"] != "caller_recall" or not set(relation_ids).issubset(manifest["relation_ids"]):
                    raise DomainError("CONTEXT_STALE", "Delivered relations must belong to the recall snapshot")
                workspace_id = _decode(manifest["health_manifest"])["workspace"]["id"]
            for relation_id in relation_ids:
                try:
                    await self._relation_row(connection, binding_id, relation_id, snapshot,
                        code_workspace_id=workspace_id, workspace_scoped=True)
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
            return {"epoch": clock["epoch"], "stats": await self._stats(connection, binding_id, clock["epoch"], snapshot,
                code_workspace_id=workspace_id, workspace_scoped=True)}

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
            await self._reconcile_locked(connection, journal, entries, scrub=True)
            await connection.execute("UPDATE am_credentials SET active=false,generation=generation+1")
            await connection.execute("UPDATE am_rules SET state='retracted',revision=revision+1 WHERE state='active'")
            epoch = await self._tick(connection)
            await connection.execute("UPDATE am_routes SET enabled=false,epoch=$1", epoch)
            await connection.execute("UPDATE am_selection_policies SET enabled=false,epoch=$1", epoch)
            await connection.execute("UPDATE am_sources SET health_restore_revision=revision WHERE state='active' AND body IS NOT NULL")
            await connection.execute("""INSERT INTO am_claim_health(claim_id,claim_revision,binding_id)
                SELECT id,revision,binding_id FROM am_claims WHERE state='active' AND draft IS NOT NULL
                ON CONFLICT DO NOTHING""")
            await connection.execute("""UPDATE am_claim_health h SET version=version+1,restore_unknown=true,
                needs_review=true,support='unknown',freshness='unknown',operator_review=NULL,
                review_event_id=NULL,assessment_event_id=NULL
                FROM am_claims c WHERE c.id=h.claim_id AND c.state='active' AND c.draft IS NOT NULL""")
            await connection.execute("UPDATE am_health_policies SET revision=revision+1,enabled=false,allow_jev_health=false")
            await connection.execute("DELETE FROM am_admissions")
            await connection.execute("""UPDATE am_jobs SET state='blocked',error_code='AUTH_REISSUE_REQUIRED',generation=generation+1,
                lease_token=NULL,deadline=NULL WHERE state IN ('pending','leased','blocked','failed') AND retired_at IS NULL""")
            await connection.execute("""UPDATE am_operations o SET state='blocked',error_code='AUTH_REISSUE_REQUIRED',epoch=$1
                WHERE state IN ('accepted','pending','blocked','failed') AND EXISTS(
                    SELECT 1 FROM am_jobs j WHERE j.operation_id=o.id AND j.state='blocked' AND j.retired_at IS NULL)""", epoch)
            await connection.execute("UPDATE am_pending_judgments SET state='held' WHERE state='pending'")
            await connection.execute("""SELECT setval(pg_get_serial_sequence('am_pending_judgments','sequence'),
                COALESCE((SELECT max(sequence) FROM am_pending_judgments),0)+1,false)""")
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

    def _source_input(self, row) -> dict:
        return {
            "id": row["id"],
            "revision": row["revision"],
            "realm": row["realm"],
            "snapshot": row["snapshot"],
            "speaker": row["speaker"],
            "event_time": row["event_time"].isoformat() if row["event_time"] else None,
            "recorded_at": row["recorded_at"].isoformat(),
            "coverage": _decode(row["capture_coverage"]),
            "body_digest": hashlib.sha256(row["body"].encode()).hexdigest(),
            "origin_digest": hashlib.sha256(row["origin_key"].encode()).hexdigest(),
        }

    def _disclosure_record(self, kind: str, row) -> dict:
        fields = (
            "id", "binding_id", "realm", "state", "revision", "snapshot",
            "request_snapshot", "kind", "target_ref", "artifact_id", "source_id",
            "source_revision", "source_ids", "rejected_source_ids",
            "byte_start", "byte_end", "window_digest", "judgment_digest",
            "manifest_digest", "digest", "label", "coverage", "policy_revision",
            "policy_epoch", "binding_revision", "credential_id",
            "credential_generation", "deletion_generation",
            "prior_rejection_ids", "rejection_review_ids", "judgment_id",
            "left_id", "right_id", "proposal_id", "valid_from", "valid_until",
            "superseded_by",
        )
        value = {"kind": kind}
        for name in fields:
            if name in row:
                item = row[name]
                value[name] = item.isoformat() if hasattr(item, "isoformat") else item
        for name in (
            "claims", "sources", "relations", "rejection_inputs",
            "rejection_comparisons", "draft", "selector", "exceptions",
        ):
            if name in row:
                value[name] = _decode(row[name])
        if "reason" in row:
            reason = row["reason"]
            value["reason_digest"] = (
                hashlib.sha256(reason.encode()).hexdigest()
                if reason is not None else None
            )
        return value

    async def _disclosure_manifest(
        self,
        connection,
        binding_id: str,
        ref: str,
        snapshot: str | None,
        *,
        _path: tuple[str, ...] = (),
        _budget: list[int] | None = None,
        _skip_feedback_owner: str | None = None,
        _omit_reason_source: str | None = None,
    ) -> dict | None:
        inherited = _DISCLOSURE_CONTEXT.get()
        if inherited is not None and _budget is None:
            _path, _budget = inherited[:2]
        budget = _budget if _budget is not None else [REJECTION_DISCLOSURE_NODE_LIMIT]
        if ref in _path or len(_path) >= REJECTION_DISCLOSURE_DEPTH_LIMIT:
            return None
        cache = inherited[2] if inherited is not None else {}
        key = (binding_id, ref, snapshot, _skip_feedback_owner, _omit_reason_source)
        if key in cache:
            return cache[key]
        token = _DISCLOSURE_CONTEXT.set(((*_path, ref), budget, cache))
        try:
            manifest = await self._disclosure_manifest_inner(
                connection, binding_id, ref, snapshot,
                _path=_path, _budget=budget,
                _skip_feedback_owner=_skip_feedback_owner,
                _omit_reason_source=_omit_reason_source,
            )
            if manifest is not None:
                cache[key] = manifest
            return manifest
        finally:
            _DISCLOSURE_CONTEXT.reset(token)

    async def _feedback_disclosure(
        self, connection, binding_id: str, row, snapshot: str | None,
    ) -> bool:
        return (
            await self._disclosure_manifest(
                connection, binding_id, row["id"], snapshot,
            )
            is not None
        )

    async def _index_rejection(self, connection, binding_id: str, rejection_id: str) -> None:
        from .lexical import tokens

        kind, row = await self._ref_metadata(connection, binding_id, rejection_id)
        if kind == "selection" and row["label"] == "discard":
            ids = [row["source_id"]]
        elif kind == "feedback" and row["kind"] == "reject":
            ids = list(row["rejected_source_ids"])
        else:
            raise DomainError(
                "REJECTION_REFERENCE_INVALID", "Index an actual persisted rejection",
            )
        if len(ids) > 128:
            raise DomainError(
                "REJECTION_REFERENCE_INVALID", "The rejection evidence manifest exceeds its bound",
            )
        await connection.execute(
            "DELETE FROM am_rejection_tokens WHERE binding_id=$1 AND rejection_id=$2",
            binding_id, rejection_id,
        )
        await connection.execute(
            "DELETE FROM am_rejection_evidence WHERE binding_id=$1 AND rejection_id=$2",
            binding_id, rejection_id,
        )
        scoped_sources = await connection.fetch(
            "SELECT snapshot FROM am_sources WHERE id=ANY($1::text[]) AND binding_id=$2",
            ids, binding_id,
        )
        scopes = {source["snapshot"] for source in scoped_sources if source["snapshot"] is not None}
        current_ref, visited = rejection_id, set()
        for _ in range(REJECTION_DISCLOSURE_DEPTH_LIMIT):
            if current_ref in visited:
                return
            visited.add(current_ref)
            target_kind, target = await self._ref_metadata(connection, binding_id, current_ref)
            scopes.update(target[name] for name in ("snapshot", "request_snapshot")
                          if target.get(name) is not None)
            if target_kind == "operation":
                current_ref = target["artifact_id"] or target["source_id"]
            elif target_kind == "feedback":
                current_ref = target["target_ref"]
            elif target_kind == "relation":
                current_ref = target["judgment_id"]
            elif target_kind == "rule":
                current_ref = target["proposal_id"]
            else:
                break
            if current_ref is None:
                break
        else:
            return
        if len(scopes) > 1:
            return
        scope = next(iter(scopes), None)
        if await self._disclosure_manifest(connection, binding_id, rejection_id, scope) is None:
            return
        token_digests = set()
        for source_id in sorted(set(ids)):
            source = await connection.fetchrow(
                """SELECT * FROM am_sources
                   WHERE id=$1 AND binding_id=$2 AND realm=$3
                     AND state='active' AND body IS NOT NULL
                     AND speaker NOT IN ('agent_note','memory')""",
                source_id, binding_id, self.settings.realm,
            )
            if source is None:
                continue
            if kind == "selection" and source["revision"] != row["source_revision"]:
                continue
            start = row["byte_start"] if kind == "selection" else None
            end = row["byte_end"] if kind == "selection" else None
            body = source["body"]
            indexed_body = (
                body.encode()[start:end].decode()
                if start is not None and end is not None else body
            )
            await connection.execute(
                """INSERT INTO am_rejection_evidence(
                       binding_id,rejection_id,source_id,source_revision,
                       body_digest,byte_start,byte_end,snapshot
                   ) VALUES($1,$2,$3,$4,$5,$6,$7,$8)""",
                binding_id, rejection_id, source_id, source["revision"],
                hashlib.sha256(body.encode()).hexdigest(), start, end, scope or "",
            )
            token_digests.update(
                hashlib.sha256(token.encode()).hexdigest()
                for token in tokens(indexed_body)[:REJECTION_INDEX_TOKEN_LIMIT]
            )
        if token_digests:
            await connection.executemany(
                """INSERT INTO am_rejection_tokens(binding_id,token_digest,rejection_id,snapshot)
                   VALUES($1,$2,$3,$4)""",
                [
                    (binding_id, token_digest, rejection_id, scope or "")
                    for token_digest in sorted(token_digests)
                ],
            )

    async def _required_rejections(
        self, connection, binding_id: str, snapshot: str | None, source: Source,
    ) -> tuple[list[dict], dict]:
        from .lexical import tokens

        probe_tokens = [
            hashlib.sha256(token.encode()).hexdigest()
            for token in tokens(source.body)[:REJECTION_INDEX_TOKEN_LIMIT]
        ]
        scopes = [""] if snapshot is None else ["", snapshot]
        hits = await connection.fetch(
            """WITH probes AS (
                   SELECT DISTINCT value AS token_digest FROM unnest($2::text[]) value
               ), hits AS (
                   SELECT found.rejection_id,probes.token_digest
                   FROM probes CROSS JOIN unnest($3::text[]) scope(snapshot)
                   CROSS JOIN LATERAL (
                       SELECT t.rejection_id FROM am_rejection_tokens t
                       LEFT JOIN am_source_selections q ON q.id=t.rejection_id
                       LEFT JOIN am_feedback f ON f.id=t.rejection_id
                       WHERE t.binding_id=$1 AND t.token_digest=probes.token_digest
                         AND t.snapshot=scope.snapshot
                         AND COALESCE(q.state,f.state)='active'
                       ORDER BY t.rejection_id LIMIT $4
                   ) found
               )
               SELECT rejection_id,count(*) AS matches
               FROM hits GROUP BY rejection_id
               ORDER BY matches DESC,rejection_id LIMIT 32""",
            binding_id, probe_tokens, scopes, REJECTION_CANDIDATE_LIMIT // len(scopes),
        )
        eligible = []
        examined = 0
        for hit in hits:
            examined += 1
            item = await self._rejection_input(
                connection, binding_id, snapshot, hit["rejection_id"],
            )
            if item is not None:
                eligible.append(item)
                if len(eligible) == REJECTION_CANDIDATE_LIMIT:
                    break
        metadata = {
            "method": "bounded_lexical_token_index",
            "meaning_judged_by_index": False,
            "required_limit": REJECTION_CANDIDATE_LIMIT,
            "posting_probe_bound": REJECTION_INDEX_TOKEN_LIMIT * REJECTION_CANDIDATE_LIMIT,
            "examined_rejection_rows": examined,
            "candidate_scan_bound": REJECTION_HISTORY_EXAMINED_LIMIT,
            "coverage": "bounded_index_sample_not_exhaustive_history",
            "exhaustive": False,
        }
        return eligible, metadata

    async def _rejection_history_page(
        self, connection, binding_id: str, snapshot: str | None,
        cursor: str | None = None,
    ) -> dict:
        after = None if cursor in {None, "history"} else cursor
        rows = await connection.fetch(
            """SELECT id FROM (
                   SELECT id FROM am_source_selections
                   WHERE binding_id=$1 AND label='discard' AND state='active'
                   UNION ALL
                   SELECT id FROM am_feedback
                   WHERE binding_id=$1 AND kind='reject' AND state='active'
               ) rejected
               WHERE ($2::text IS NULL OR id>$2)
               ORDER BY id LIMIT 33""",
            binding_id, after,
        )
        items = []
        examined = 0
        last = after
        for row in rows[:REJECTION_HISTORY_EXAMINED_LIMIT]:
            examined += 1
            last = row["id"]
            item = await self._rejection_input(connection, binding_id, snapshot, row["id"])
            if item is not None:
                items.append(item)
                if len(items) == REJECTION_CANDIDATE_LIMIT:
                    break
        partial = examined < len(rows)
        return {
            "items": items,
            "next_cursor": last if partial else None,
            "partial": partial,
            "examined_rows": examined,
            "examined_row_limit": REJECTION_HISTORY_EXAMINED_LIMIT,
            "optional": True,
            "coverage": "live_history_page_not_a_frozen_complete_catalog",
        }

    async def _refuse_rejected_identity(
        self, connection, binding_id: str, snapshot: str | None,
        source: Source, byte_start: int, byte_end: int,
    ) -> None:
        body_digest = hashlib.sha256(source.body.encode()).hexdigest()
        rows = await connection.fetch(
            """WITH same_source AS (
                   SELECT e.rejection_id FROM am_rejection_evidence e
                   JOIN am_sources s ON s.id=e.source_id
                   LEFT JOIN am_source_selections q ON q.id=e.rejection_id
                   LEFT JOIN am_feedback f ON f.id=e.rejection_id
                   WHERE e.binding_id=$1 AND e.source_id=$2
                     AND e.source_revision=s.revision
                     AND e.snapshot=ANY($8::text[])
                     AND COALESCE(q.state,f.state)='active'
                     AND s.state='active' AND s.body IS NOT NULL
                     AND s.realm=$6
                     AND (s.snapshot IS NULL OR s.snapshot=$7)
                     AND (
                         e.byte_start IS NULL
                         OR (e.byte_start<$5 AND e.byte_end>$4)
                     )
                   ORDER BY e.rejection_id LIMIT 33
               ), copied_body AS (
                   SELECT e.rejection_id FROM am_rejection_evidence e
                   JOIN am_sources s ON s.id=e.source_id
                   LEFT JOIN am_source_selections q ON q.id=e.rejection_id
                   LEFT JOIN am_feedback f ON f.id=e.rejection_id
                   WHERE e.binding_id=$1 AND e.body_digest=$3 AND e.source_id<>$2
                     AND e.source_revision=s.revision
                     AND e.snapshot=ANY($8::text[])
                     AND COALESCE(q.state,f.state)='active'
                     AND s.state='active' AND s.body IS NOT NULL
                     AND s.realm=$6
                     AND (s.snapshot IS NULL OR s.snapshot=$7)
                   ORDER BY e.rejection_id LIMIT 33
               )
               SELECT rejection_id FROM (
                   SELECT rejection_id FROM same_source
                   UNION SELECT rejection_id FROM copied_body
               ) matches ORDER BY rejection_id LIMIT 33""",
            binding_id, source.id, body_digest, byte_start, byte_end,
            self.settings.realm, snapshot, [""] if snapshot is None else ["", snapshot],
        )
        for row in rows[:REJECTION_IDENTITY_EXAMINED_LIMIT]:
            item = await self._rejection_input(
                connection, binding_id, snapshot, row["rejection_id"],
            )
            if item is None:
                continue
            for original in item["sources"]:
                if (
                    original["speaker"] in {"agent_note", "memory"}
                    or original["id"] == item["reason_source_id"]
                ):
                    continue
                if original["id"] != source.id and original["body_digest"] == body_digest:
                    raise DomainError(
                        "EVIDENCE_REJECTED",
                        "Copied rejected original evidence cannot publish new candidates",
                    )
                if original["id"] == source.id and (
                    item["disposition"] == "reject"
                    or (
                        item["target"]["byte_start"] < byte_end
                        and item["target"]["byte_end"] > byte_start
                    )
                ):
                    raise DomainError(
                        "EVIDENCE_REJECTED",
                        "Overlapping rejected original evidence cannot publish new candidates",
                    )
        if len(rows) > REJECTION_IDENTITY_EXAMINED_LIMIT:
            raise DomainError(
                "EVIDENCE_IDENTITY_UNRESOLVED",
                "The bounded evidence-identity check cannot establish independent evidence",
            )

    async def _disclosure_manifest_inner(
        self,
        connection,
        binding_id: str,
        ref: str,
        snapshot: str | None,
        *,
        _path: tuple[str, ...] = (),
        _budget: list[int] | None = None,
        _skip_feedback_owner: str | None = None,
        _omit_reason_source: str | None = None,
    ) -> dict | None:
        budget = _budget if _budget is not None else [REJECTION_DISCLOSURE_NODE_LIMIT]
        if ref in _path or len(_path) >= REJECTION_DISCLOSURE_DEPTH_LIMIT or budget[0] <= 0:
            return None
        budget[0] -= 1
        path = (*_path, ref)
        try:
            kind, row = await self._ref_metadata(connection, binding_id, ref)
            if kind != "rule" and row.get("binding_id") != binding_id:
                return None
            if row.get("realm", self.settings.realm) != self.settings.realm:
                return None
            if row.get("state") in {"retracted", "purged", "held", "resolved"}:
                return None
            if (kind not in {"operation", "proposal"} and row.get("state", "active") != "active"
                    and not (kind == "feedback" and row["kind"] != "reject" and row["state"] == "candidate")):
                return None
            if any(
                row.get(name) is not None and row[name] != snapshot
                for name in ("snapshot", "request_snapshot")
            ):
                return None

            record = self._disclosure_record(kind, row)
            children = []

            async def add(child_ref: str, **options) -> dict | None:
                manifest = await self._disclosure_manifest(
                    connection, binding_id, child_ref, snapshot,
                    _path=path, _budget=budget, **options,
                )
                if manifest is not None:
                    children.append(manifest)
                return manifest

            async def source_dependencies(table: str, column: str) -> bool:
                dependencies = await connection.fetch(
                    f"""SELECT source_id,source_revision FROM {table}
                        WHERE {column}=$1 ORDER BY source_id LIMIT 129""",
                    ref,
                )
                if not dependencies or len(dependencies) > 128:
                    return False
                for item in dependencies:
                    manifest = await add(item["source_id"])
                    if manifest is None or manifest["record"]["revision"] != item["source_revision"]:
                        return False
                return True

            if kind == "source":
                if row["state"] != "active" or row["body"] is None:
                    return None
                record = {"kind": "source", **self._source_input(row)}
                owners = await connection.fetch(
                    """SELECT id FROM am_feedback
                       WHERE binding_id=$1 AND source_id=$2 ORDER BY id LIMIT 17""",
                    binding_id, ref,
                )
                if len(owners) > 16:
                    return None
                for owner in owners:
                    if owner["id"] == _skip_feedback_owner:
                        continue
                    if await add(owner["id"], _omit_reason_source=ref) is None:
                        return None
                health_owners = await connection.fetch(
                    """SELECT * FROM am_health_events
                       WHERE binding_id=$1 AND reason_source_id=$2 ORDER BY id LIMIT 17""",
                    binding_id, ref,
                )
                if len(health_owners) > 16:
                    return None
                for owner in health_owners:
                    if budget[0] <= 0 or not await self._health_event_visible(connection, binding_id, owner, snapshot):
                        return None
                    budget[0] -= 1
                    dependencies = set(owner["source_ids"]) | set(owner["claim_ids"])
                    if owner["kind"] == "feedback_resolution":
                        target = await connection.fetchrow(
                            "SELECT target_ref FROM am_feedback WHERE id=$1 AND binding_id=$2",
                            owner["target_ref"], binding_id,
                        )
                        if target is None:
                            return None
                        # Follow the live target, not erasable candidate text or its historical request scope.
                        dependencies.add(target["target_ref"])
                    for dependency in sorted(dependencies):
                        if await add(dependency) is None:
                            return None
                    children.append({"record": {
                        "kind": "health_reason_owner", "id": owner["id"], "event_kind": owner["kind"],
                        "target_ref": owner["target_ref"], "source_ids": list(owner["source_ids"]),
                        "claim_ids": list(owner["claim_ids"]), "payload_digest": canonical_digest(_decode(owner["payload"])),
                    }, "children": []})

            elif kind == "operation":
                target = row["artifact_id"] or row["source_id"]
                if target is None or await add(target) is None:
                    return None

            elif kind == "feedback":
                if await add(row["target_ref"]) is None:
                    return None
                if row["source_id"] and row["source_id"] != _omit_reason_source:
                    if await add(
                        row["source_id"], _skip_feedback_owner=row["id"],
                    ) is None:
                        return None
                rejected_ids = list(row["rejected_source_ids"])
                if len(rejected_ids) > 128:
                    return None
                for source_id in sorted(set(rejected_ids)):
                    if source_id == row["source_id"]:
                        continue
                    if await add(source_id) is None:
                        return None

            elif kind == "selection":
                if not await source_dependencies("am_selection_sources", "selection_id"):
                    return None
                source_matches = [
                    child for child in children
                    if child["record"]["id"] == row["source_id"]
                ]
                if (
                    not source_matches
                    or source_matches[0]["record"]["revision"] != row["source_revision"]
                ):
                    return None
                saved = _decode(row["rejection_inputs"])
                comparisons = _decode(row["rejection_comparisons"])
                if not isinstance(saved, dict) or not isinstance(comparisons, list):
                    return None
                if len(comparisons) > 16 or len(row["rejection_review_ids"]) > 16:
                    return None
                try:
                    parsed = [RejectionComparison.model_validate(item) for item in comparisons]
                except ValueError:
                    return None
                comparison_ids = {item.rejection_id for item in parsed}
                if len(comparison_ids) != len(parsed) or set(saved) != comparison_ids:
                    return None
                if {
                    item.rejection_id for item in parsed if item.decision == "reopen"
                } != set(row["prior_rejection_ids"]):
                    return None
                for rejection_id in sorted(comparison_ids):
                    rejection = await self._rejection_input(
                        connection, binding_id, snapshot, rejection_id,
                        _path=path, _budget=budget,
                    )
                    if rejection is None or rejection["input_digest"] != saved[rejection_id]:
                        return None
                    children.append({
                        "record": {
                            "kind": "rejection_input",
                            "id": rejection_id,
                            "input_digest": rejection["input_digest"],
                        },
                        "children": [],
                    })
                for review_id in row["rejection_review_ids"]:
                    review = await connection.fetchrow(
                        """SELECT label FROM am_source_selections
                           WHERE id=$1 AND binding_id=$2""",
                        review_id, binding_id,
                    )
                    if review is None or review["label"] != "review":
                        return None
                    if await add(review_id) is None:
                        return None

            elif kind == "claim":
                await self._claim_row(connection, binding_id, ref, snapshot, False)
                if not await source_dependencies("am_claim_sources", "claim_id"):
                    return None

            elif kind == "judgment":
                if not await self._judgment_disclosure(connection, binding_id, row, snapshot):
                    return None
                claims = _decode(row["claims"])
                sources = _decode(row["sources"])
                if len(claims) > 20 or len(sources) > 128:
                    return None
                for item in (*claims, *sources):
                    child = await add(item["id"])
                    if child is None or child["record"]["revision"] != item["revision"]:
                        return None

            elif kind == "relation":
                await self._relation_row(connection, binding_id, ref, snapshot, reuse=False)
                if not await source_dependencies("am_relation_sources", "relation_id"):
                    return None
                claims = await connection.fetch(
                    """SELECT claim_id FROM am_relation_claims
                       WHERE relation_id=$1 ORDER BY claim_id LIMIT 21""",
                    ref,
                )
                if not claims or len(claims) > 20:
                    return None
                for claim_id in sorted({
                    row["left_id"], row["right_id"], *(item["claim_id"] for item in claims),
                }):
                    if await add(claim_id) is None:
                        return None
                if row["judgment_id"] and await add(row["judgment_id"]) is None:
                    return None

            elif kind == "reflection":
                if row["draft"] is None:
                    return None
                if not await source_dependencies("am_reflection_sources", "reflection_id"):
                    return None
                claims = await connection.fetch(
                    """SELECT claim_id FROM am_reflection_claims
                       WHERE reflection_id=$1 ORDER BY claim_id LIMIT 21""",
                    ref,
                )
                if not claims or len(claims) > 20:
                    return None
                for item in claims:
                    if await add(item["claim_id"]) is None:
                        return None

            elif kind == "proposal":
                if row["state"] not in {"candidate", "active"}:
                    return None
                if not await source_dependencies("am_proposal_sources", "proposal_id"):
                    return None

            elif kind == "rule":
                await self._active_rule(connection, row)
                if await add(row["proposal_id"]) is None:
                    return None

            else:
                return None

            return {"record": record, "children": children}
        except DomainError as error:
            if error.code not in _DISCLOSURE_ERRORS:
                raise
            return None


    async def _health_policy(self, connection, binding_id: str) -> dict:
        row = await connection.fetchrow('SELECT * FROM am_health_policies WHERE binding_id=$1', binding_id)
        return dict(row) if row else {'binding_id': binding_id, 'revision': 0, 'enabled': False,
            'allow_jev_health': False, 'max_audit_sources': 16, 'max_audit_claims': 20, 'max_audit_bytes': 32768}

    async def health_policy(self, actor: Principal, binding_id: str) -> dict:
        async with self._tx(lock=False) as (connection, _):
            await self._actor(connection, actor, binding_id, (Role.AGENT, Role.OPERATOR))
            return await self._health_policy(connection, binding_id)

    async def _health_state(self, connection, claim) -> dict:
        row = await connection.fetchrow('SELECT * FROM am_claim_health WHERE claim_id=$1', claim['id'])
        if row is not None and row['claim_revision'] != claim['revision']:
            raise DomainError('HEALTH_STALE', 'The exact claim health revision changed')
        if row is None:
            restored = await connection.fetchval('''SELECT EXISTS(SELECT 1 FROM am_claim_sources d
                JOIN am_sources s ON s.id=d.source_id WHERE d.claim_id=$1
                AND s.health_restore_revision=d.source_revision)''', claim['id'])
            return {'claim_id': claim['id'], 'claim_revision': claim['revision'], 'binding_id': claim['binding_id'],
                'version': 1, 'support': 'unknown', 'freshness': 'unknown', 'needs_review': restored,
                'restore_unknown': restored, 'operator_review': None, 'review_event_id': None,
                'assessment_event_id': None}
        return dict(row)

    async def _ensure_health_state(self, connection, claim) -> dict:
        initial = await self._health_state(connection, claim)
        await connection.execute('''INSERT INTO am_claim_health(claim_id,claim_revision,binding_id,restore_unknown,needs_review)
            VALUES($1,$2,$3,$4,$4) ON CONFLICT DO NOTHING''',
            claim['id'], claim['revision'], claim['binding_id'], initial['restore_unknown'])
        return await self._health_state(connection, claim)

    async def _code_dependencies(self, connection, claim) -> list[dict]:
        rows = await connection.fetch('''SELECT o.* FROM am_code_links d
            JOIN am_code_observations o ON o.id=d.observation_id
            WHERE d.claim_id=$1 AND d.claim_revision=$2 ORDER BY o.workspace_id,o.relative_path,o.symbol_name,o.id''',
            claim['id'], claim['revision'])
        policy_enabled = (await self._health_policy(connection, claim['binding_id']))['enabled'] if rows else False
        dependencies = []
        for row in rows:
            workspace = await connection.fetchrow('SELECT * FROM am_code_workspaces WHERE id=$1', row['workspace_id'])
            valid = (policy_enabled and row['state'] == 'active' and row['metadata'] is not None and workspace is not None
                and workspace['state'] == 'active' and workspace['revision'] == row['workspace_revision']
                and workspace['binding_id'] == claim['binding_id'] and workspace['binding_revision'] ==
                await connection.fetchval('SELECT revision FROM am_bindings WHERE id=$1', claim['binding_id']))
            if valid:
                try:
                    producer = await self._credential(connection, workspace['producer_credential_id'])
                    valid = (producer.generation == workspace['producer_generation'] and producer.role == Role.PRODUCER
                        and claim['binding_id'] in producer.bindings)
                except DomainError as error:
                    if error.code not in {'AUTH_DENIED', 'SCOPE_DENIED'}:
                        raise
                    valid = False
            metadata = _decode(row['metadata']) if row['metadata'] else None
            valid = valid and metadata['status'] == 'present' and (not row['symbol_name'] or metadata.get('symbol') is not None)
            dependencies.append({'ref': row['id'], 'workspace_id': row['workspace_id'],
                'workspace_revision': row['workspace_revision'], 'relative_path': row['relative_path'],
                'symbol_name': row['symbol_name'], 'fingerprint': row['fingerprint'], 'usable': bool(valid)})
        return dependencies

    async def _claim_health_manifest(self, connection, claim) -> dict:
        return {'claim': {'id': claim['id'], 'revision': claim['revision']},
            'health': await self._health_state(connection, claim),
            'code': await self._code_dependencies(connection, claim)}

    async def _reuse_claim(self, connection, claim) -> None:
        eligible = await connection.fetchval(f'''SELECT EXISTS(SELECT 1 FROM am_claims c WHERE c.id=$1
            AND c.binding_id=$2 AND c.revision=$3 AND ({_HEALTH_REUSE_SQL}))''',
            claim['id'], claim['binding_id'], claim['revision'])
        if not eligible:
            raise DomainError('CLAIM_INELIGIBLE', 'This ordinary claim requires current health review before reuse')

    async def _require_workspace_claim(self, connection, claim, workspace_id: str | None) -> None:
        eligible = await connection.fetchval(f"""SELECT EXISTS(SELECT 1 FROM am_claims c
            WHERE c.id=$1 AND c.binding_id=$2 AND c.revision=$3
            AND ({_CODE_CONTEXT_SQL.format(workspace="$4")}))""",
            claim["id"], claim["binding_id"], claim["revision"], workspace_id)
        if not eligible:
            raise DomainError("CLAIM_INELIGIBLE", "The ordinary claim belongs to another explicit code workspace")

    async def _admitted_health_manifest(
        self, connection, binding_id: str, claim_ids, relation_ids=(), *,
        code_workspace_id: str | None = None, workspace_scoped: bool = False,
    ) -> dict:
        workspace = {"id": code_workspace_id, "scoped": workspace_scoped}
        if workspace_scoped and code_workspace_id is not None:
            registered = await connection.fetchrow("""SELECT w.* FROM am_code_workspaces w
                JOIN am_bindings b ON b.id=w.binding_id WHERE w.id=$1 AND w.binding_id=$2
                AND w.state='active' AND w.binding_revision=b.revision""", code_workspace_id, binding_id)
            if registered is None:
                raise DomainError("HEALTH_WORKSPACE_SCOPE", "The explicit code workspace is no longer registered")
            try:
                producer = await self._credential(connection, registered["producer_credential_id"])
            except DomainError as error:
                if error.code != "AUTH_DENIED" or error.status != 401:
                    raise
                raise DomainError("HEALTH_WORKSPACE_SCOPE", "The registered observation authority changed") from None
            if (producer.role != Role.PRODUCER or producer.generation != registered["producer_generation"]
                    or binding_id not in producer.bindings):
                raise DomainError("HEALTH_WORKSPACE_SCOPE", "The registered observation authority changed")
            workspace.update(
                revision=registered["revision"], root_fingerprint=registered["root_fingerprint"],
                producer_credential_id=producer.credential_id, producer_generation=producer.generation)
        ids = set(claim_ids)
        if relation_ids:
            rows = await connection.fetch("""SELECT claim_id FROM am_relation_claims WHERE relation_id=ANY($1::text[])
                UNION SELECT left_id FROM am_relations WHERE id=ANY($1::text[])
                UNION SELECT right_id FROM am_relations WHERE id=ANY($1::text[])""", list(relation_ids))
            ids.update(row["claim_id"] for row in rows)
        if len(ids) > 64:
            raise DomainError("MANIFEST_TOO_LARGE", "The complete relation health manifest exceeds its bound")
        result = []
        for identifier in sorted(ids):
            claim = await connection.fetchrow("SELECT * FROM am_claims WHERE id=$1 AND binding_id=$2", identifier, binding_id)
            if claim is None:
                raise DomainError("CLAIM_INELIGIBLE", "A health dependency is unavailable")
            if workspace_scoped:
                await self._require_workspace_claim(connection, claim, code_workspace_id)
            result.append(await self._claim_health_manifest(connection, claim))
        return {"claims": result, "workspace": workspace}

    async def _health_input_snapshot(self, connection, binding_id, source_ids, claim_ids) -> str | None:
        scopes = await connection.fetch('''SELECT DISTINCT snapshot FROM (
            SELECT snapshot FROM am_sources WHERE id=ANY($1::text[]) AND binding_id=$3
            UNION SELECT snapshot FROM am_claims WHERE id=ANY($2::text[]) AND binding_id=$3
            ) scopes WHERE snapshot IS NOT NULL''', list(source_ids), list(claim_ids), binding_id)
        if len(scopes) > 1:
            raise DomainError('SESSION_SNAPSHOT_CONFLICT', 'Split incompatible snapshot observations into separate segments')
        return scopes[0]['snapshot'] if scopes else None

    async def _health_event(self, connection, actor, command, operation_id, *, target=None,
        source_ids=(), claim_ids=(), payload=None, reason=None) -> str:
        identifier = _id('health')
        reason_source = None
        if reason:
            reason_snapshot = await self._health_input_snapshot(connection, command.binding_id, source_ids, claim_ids)
            if command.kind == 'health_work_disposition':
                reason_snapshot = command.snapshot
            reason_source = await self._insert_source(connection, actor, CaptureCommand(
                binding_id=command.binding_id, idempotency_key=command.idempotency_key,
                origin_key=f'health-reason:{identifier}', body=reason, speaker='agent_note', snapshot=reason_snapshot), operation_id)
        await connection.execute('''INSERT INTO am_health_events(id,binding_id,operation_id,kind,
            credential_id,credential_generation,realm,role,target_ref,reason_source_id,source_ids,claim_ids,payload)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13::jsonb)''',
            identifier, command.binding_id, operation_id, command.kind, actor.credential_id, actor.generation,
            actor.realm, actor.role.value, target, reason_source, list(source_ids), list(claim_ids), _json(payload or {}))
        return identifier

    async def _require_health_capacity(self, connection, binding_id: str) -> None:
        count = await connection.fetchval('''SELECT count(*) FROM am_pending_judgments
            WHERE binding_id=$1 AND kind='health' AND state IN ('pending','held')''', binding_id)
        if count >= self.settings.queue_limit:
            raise DomainError('QUEUE_FULL', 'The bounded health backlog is full', status=429)

    async def _enqueue_health(self, connection, binding_id: str, key: str, *, sources=(), claims=(), payload=None) -> str:
        existing = await connection.fetchrow('''SELECT * FROM am_pending_judgments
            WHERE binding_id=$1 AND kind='health' AND health_key=$2''', binding_id, key)
        if existing is not None and existing['state'] == 'retracted':
            return existing['id']
        data = payload or {}
        source_ids, claim_ids = sorted(set(sources)), sorted(set(claims))
        snapshot = await self._health_input_snapshot(connection, binding_id, source_ids, claim_ids)
        if len(source_ids) > 128 or len(claim_ids) > 20:
            raise DomainError('MANIFEST_TOO_LARGE', 'Split the explicit health work into bounded manifests')
        if existing is not None:
            previous = _decode(existing['health_payload'])
            disposition = previous.pop('disposition', None)
            terminal_unknown = (existing['state'] == 'resolved' and disposition is not None
                and disposition.get('decision') == 'close_unknown' and disposition.get('event_ref') is not None)
            changed = (source_ids != list(existing['source_ids']) or claim_ids != list(existing['claim_ids'])
                or data != previous or snapshot != existing['snapshot'])
            if changed:
                # New evidence does not transfer authority to reopen terminal unknown work.
                if terminal_unknown:
                    data = {**data, 'disposition': disposition}
                elif existing['state'] not in {'pending', 'held'}:
                    await self._require_health_capacity(connection, binding_id)
                await connection.execute('''UPDATE am_pending_judgments SET source_ids=$2,claim_ids=$3,
                    health_payload=$4::jsonb,health_revision=health_revision+1,
                    state=CASE WHEN $6 THEN 'resolved' ELSE 'pending' END,
                    resolved_at=CASE WHEN $6 THEN resolved_at ELSE NULL END,snapshot=$5 WHERE id=$1''',
                    existing['id'], source_ids, claim_ids, _json(data), snapshot, terminal_unknown)
            return existing['id']
        await self._require_health_capacity(connection, binding_id)
        identifier = _id('pending')
        await connection.execute('''INSERT INTO am_pending_judgments(id,binding_id,kind,source_ids,claim_ids,
            health_key,health_revision,health_payload,snapshot) VALUES($1,$2,'health',$3,$4,$5,1,$6::jsonb,$7)''',
            identifier, binding_id, source_ids, claim_ids, key, _json(data), snapshot)
        return identifier

    async def health(self, actor: Principal, command) -> Operation:
        from .health import HEALTH_ADAPTER
        command = HEALTH_ADAPTER.validate_python(command)
        async with self._tx() as (connection, clock):
            return await self._record_health(connection, clock, actor, command)

    async def _record_health(self, connection, clock, actor, command, *, receipt_kind='health') -> Operation:
        from .health import (
            CodeLinkCommand,
            CodeObservationCommand,
            FeedbackResolutionCommand,
            HealthAssessmentCommand,
            HealthPolicyCommand,
            HealthWorkDispositionCommand,
            HealthWorkspaceCommand,
            MemoryReviewCommand,
            SessionObservationCommand,
        )
        if isinstance(command, (HealthPolicyCommand, HealthWorkspaceCommand, MemoryReviewCommand, FeedbackResolutionCommand,
                HealthWorkDispositionCommand)):
            roles = (Role.OPERATOR,)
        elif isinstance(command, (CodeObservationCommand, SessionObservationCommand)):
            roles = (Role.PRODUCER, Role.OPERATOR)
        else:
            roles = (Role.AGENT, Role.OPERATOR)
        current = await self._actor(connection, actor, command.binding_id, roles)
        digest = canonical_digest(command)
        receipt = await self._receipt(connection, current, command.binding_id, receipt_kind, command.idempotency_key, digest)
        if receipt:
            return self._operation(await self._operation_row(connection, command.binding_id, receipt['target_id']))
        if command.kind in {'code_link', 'health_assessment'}:
            other_kind = 'record' if receipt_kind == 'health' else 'health'
            other = await self._receipt(connection, current, command.binding_id, other_kind, command.idempotency_key, digest)
            if other:
                await self._save_receipt(connection, current, command.binding_id, receipt_kind,
                    command.idempotency_key, digest, other['target_id'])
                return self._operation(await self._operation_row(connection, command.binding_id, other['target_id']))
        revision = await connection.fetchval('SELECT revision FROM am_bindings WHERE id=$1', command.binding_id)
        if revision != command.expected_binding_revision:
            raise DomainError('HEALTH_STALE', 'The binding revision changed')
        if isinstance(command, (CodeObservationCommand, SessionObservationCommand, HealthAssessmentCommand)):
            if not (await self._health_policy(connection, command.binding_id))['enabled']:
                raise DomainError('HEALTH_DISABLED', 'Health processing requires current explicit authorization')
        operation = await self._new_operation(connection, current, command.binding_id, command.kind, 'health_recorded')
        if isinstance(command, HealthPolicyCommand):
            policy = await self._health_policy(connection, command.binding_id)
            if policy['revision'] != command.expected_policy_revision:
                raise DomainError('HEALTH_STALE', 'The health policy revision changed')
            await connection.execute('''INSERT INTO am_health_policies(binding_id,revision,enabled,allow_jev_health,
                max_audit_sources,max_audit_claims,max_audit_bytes) VALUES($1,$2,$3,$4,$5,$6,$7)
                ON CONFLICT(binding_id) DO UPDATE SET revision=EXCLUDED.revision,enabled=EXCLUDED.enabled,
                allow_jev_health=EXCLUDED.allow_jev_health,max_audit_sources=EXCLUDED.max_audit_sources,
                max_audit_claims=EXCLUDED.max_audit_claims,max_audit_bytes=EXCLUDED.max_audit_bytes''',
                command.binding_id, policy['revision'] + 1, command.enabled, command.allow_jev_health,
                command.max_audit_sources, command.max_audit_claims, command.max_audit_bytes)
            artifact = await self._health_event(connection, current, command, operation['id'],
                payload={'policy_revision': policy['revision'] + 1})
        elif isinstance(command, HealthWorkspaceCommand):
            workspace = await connection.fetchrow('SELECT * FROM am_code_workspaces WHERE id=$1', command.workspace_id)
            if workspace and workspace['binding_id'] != command.binding_id:
                raise _denied()
            if workspace is not None and workspace["state"] != "active":
                raise DomainError("HEALTH_WORKSPACE_RETRACTED", "A withdrawn workspace cannot be reactivated; register a new identity")
            if (workspace['revision'] if workspace else 0) != command.expected_workspace_revision:
                raise DomainError('HEALTH_STALE', 'The workspace revision changed')
            producer = await self._credential(connection, command.producer_credential_id)
            if producer.role != Role.PRODUCER or command.binding_id not in producer.bindings:
                raise _denied()
            if workspace is None and await connection.fetchval(
                'SELECT count(*) FROM am_code_workspaces WHERE binding_id=$1', command.binding_id) >= 16:
                raise DomainError('MANIFEST_TOO_LARGE', 'The binding workspace registry is full')
            await connection.execute('''INSERT INTO am_code_workspaces(id,binding_id,revision,root_fingerprint,
                producer_credential_id,producer_generation,binding_revision) VALUES($1,$2,$3,$4,$5,$6,$7)
                ON CONFLICT(id) DO UPDATE SET revision=EXCLUDED.revision,root_fingerprint=EXCLUDED.root_fingerprint,
                producer_credential_id=EXCLUDED.producer_credential_id,producer_generation=EXCLUDED.producer_generation,
                binding_revision=EXCLUDED.binding_revision,last_sequence=0,state='active' ''',
                command.workspace_id, command.binding_id, command.expected_workspace_revision + 1,
                command.root_fingerprint, producer.credential_id, producer.generation, revision)
            await connection.execute("UPDATE am_code_observations SET state='retracted' WHERE workspace_id=$1", command.workspace_id)
            await self._stale_workspace_claims(connection, command.binding_id, command.workspace_id)
            artifact = command.workspace_id
            await self._health_event(connection, current, command, operation['id'], target=artifact,
                payload={'workspace_revision': command.expected_workspace_revision + 1})
        elif isinstance(command, CodeObservationCommand):
            artifact = await self._record_code_observation(connection, current, command, operation['id'])
        elif isinstance(command, SessionObservationCommand):
            artifact = await self._record_session_observation(connection, current, command, operation['id'])
        elif isinstance(command, (CodeLinkCommand, MemoryReviewCommand)):
            artifact = await self._record_claim_health(connection, clock, current, command, operation['id'])
        elif isinstance(command, HealthAssessmentCommand):
            artifact = await self._record_health_assessment(connection, clock, current, command, operation['id'])
        elif isinstance(command, HealthWorkDispositionCommand):
            artifact = await self._record_health_work_disposition(connection, current, command, operation['id'])
        else:
            artifact = await self._resolve_health_feedback(connection, clock, current, command, operation['id'])
        if isinstance(command, (HealthWorkspaceCommand, CodeObservationCommand, CodeLinkCommand)):
            if isinstance(command, CodeLinkCommand):
                producer_ids = await connection.fetch('''SELECT DISTINCT w.producer_credential_id AS id
                    FROM am_code_links l JOIN am_code_observations o ON o.id=l.observation_id
                    JOIN am_code_workspaces w ON w.id=o.workspace_id WHERE l.claim_id=$1''', command.claim_ref.id)
            else:
                producer_ids = await connection.fetch('''SELECT producer_credential_id AS id FROM am_code_workspaces
                    WHERE id=$1 AND binding_id=$2''', command.workspace_id, command.binding_id)
            for producer_row in producer_ids:
                try:
                    producer = await self._credential(connection, producer_row['id'])
                except DomainError as error:
                    if error.code != 'AUTH_DENIED' or error.status != 401 or producer_row['id'] == current.credential_id:
                        raise
                    continue
                await self._health_observer(connection, producer, command.binding_id)
        await connection.execute('UPDATE am_operations SET artifact_id=$2 WHERE id=$1', operation['id'], artifact)
        await self._save_receipt(connection, current, command.binding_id, receipt_kind,
            command.idempotency_key, digest, operation['id'])
        return self._operation(await self._operation_row(connection, command.binding_id, operation['id']))

    async def _stale_workspace_claims(self, connection, binding_id: str, workspace_id: str, *, changed_paths=None) -> None:
        rows = await connection.fetch('''SELECT DISTINCT c.* FROM am_claims c JOIN am_code_links d ON d.claim_id=c.id
            AND d.claim_revision=c.revision JOIN am_code_observations o ON o.id=d.observation_id
            WHERE c.binding_id=$1 AND c.state='active' AND o.workspace_id=$2
            AND (o.state<>'active' OR o.workspace_revision<>(SELECT revision FROM am_code_workspaces WHERE id=$2))
            AND ($3::text[] IS NULL OR o.relative_path=ANY($3))''',
            binding_id, workspace_id, sorted(changed_paths) if changed_paths is not None else None)
        for claim in rows:
            await self._ensure_health_state(connection, claim)
            await connection.execute("""UPDATE am_claim_health SET version=version+1,freshness='stale',needs_review=true
                WHERE claim_id=$1""", claim['id'])
            sources = await connection.fetch('SELECT source_id FROM am_claim_sources WHERE claim_id=$1', claim['id'])
            await self._enqueue_health(connection, binding_id, 'code:' + claim['id'],
                claims=[claim['id']], sources=[source['source_id'] for source in sources],
                payload={'cause': 'code_dependency_changed', 'health_version': (await self._health_state(connection, claim))['version']})

    async def _record_code_observation(self, connection, actor, command, operation_id: str) -> str:
        workspace = await connection.fetchrow('SELECT * FROM am_code_workspaces WHERE id=$1 AND binding_id=$2',
            command.workspace_id, command.binding_id)
        if workspace is None or workspace['state'] != 'active':
            raise _denied()
        try:
            producer = await self._credential(connection, workspace['producer_credential_id'])
        except DomainError as error:
            if error.code != 'AUTH_DENIED' or error.status != 401 or workspace['producer_credential_id'] == actor.credential_id:
                raise
            raise _denied() from None
        if (producer.role != Role.PRODUCER or producer.generation != workspace['producer_generation']
            or command.binding_id not in producer.bindings
            or (actor.role == Role.PRODUCER and actor.credential_id != producer.credential_id)):
            raise _denied()
        if (workspace['revision'] != command.expected_workspace_revision
            or workspace['binding_revision'] != command.expected_binding_revision
            or workspace['root_fingerprint'] != command.root_fingerprint):
            raise DomainError('HEALTH_STALE', 'The registered workspace identity changed')
        if command.sequence <= workspace['last_sequence']:
            raise DomainError('OBSERVATION_OUT_OF_ORDER', 'A newer registered workspace observation already exists')
        old_paths = set(await connection.fetchval("""SELECT COALESCE(array_agg(DISTINCT relative_path),'{}')
            FROM am_code_observations WHERE workspace_id=$1 AND state='active'""", workspace['id']))
        if len(old_paths | {file.relative_path for file in command.files}) > 32:
            raise DomainError('MANIFEST_TOO_LARGE', 'A workspace supports at most32 explicit observed paths')
        refs, changed_paths = [], set()
        for file in command.files:
            base = file.model_dump(mode='json', exclude={'symbols'})
            # Every symbol witness remains file-digest bound. Even an unchanged symbol stales when its file changes.
            desired = {'': {**base, 'symbol': None}}
            for symbol in file.symbols:
                if symbol.qualified_name in desired:
                    raise DomainError('CODE_ANCHOR_AMBIGUOUS', 'A qualified symbol must identify exactly one bounded span')
                desired[symbol.qualified_name] = {**base, 'symbol': symbol.model_dump(mode='json')}
            previous = await connection.fetch("""SELECT * FROM am_code_observations WHERE workspace_id=$1
                AND relative_path=$2 AND state='active' ORDER BY symbol_name""", workspace['id'], file.relative_path)
            previous = {row['symbol_name']: row for row in previous}
            for name in sorted(set(previous) | set(desired)):
                prior = previous.get(name)
                metadata = desired.get(name)
                fingerprint = canonical_digest(metadata) if metadata else None
                if prior and fingerprint == prior['fingerprint'] and prior['workspace_revision'] == workspace['revision']:
                    refs.append(prior['id'])
                    continue
                changed_paths.add(file.relative_path)
                if prior:
                    await connection.execute("UPDATE am_code_observations SET state='retracted' WHERE id=$1", prior['id'])
                if metadata is None:
                    continue
                identifier = _id('code')
                await connection.execute('''INSERT INTO am_code_observations(id,binding_id,workspace_id,workspace_revision,
                    relative_path,symbol_name,sequence,fingerprint,metadata) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb)''',
                    identifier, command.binding_id, workspace['id'], workspace['revision'], file.relative_path, name,
                    command.sequence, fingerprint, _json(metadata))
                refs.append(identifier)
        await connection.execute('UPDATE am_code_workspaces SET last_sequence=$2 WHERE id=$1', workspace['id'], command.sequence)
        if changed_paths:
            await self._stale_workspace_claims(connection, command.binding_id, workspace['id'], changed_paths=changed_paths)
        return await self._health_event(connection, actor, command, operation_id, target=workspace['id'],
            payload={'observation_refs': refs, 'sequence': command.sequence,
                'coverage': command.coverage, 'provenance': 'producer_reported',
                'observed_at': command.observed_at.isoformat()})

    async def _usable_observations(self, connection, binding_id: str, refs) -> list:
        if len(set(refs)) != len(refs):
            raise DomainError('CODE_ANCHOR_INVALID', 'Code observations must be distinct')
        if refs and not (await self._health_policy(connection, binding_id))['enabled']:
            raise DomainError('HEALTH_DISABLED', 'Code anchors require currently authorized observation')
        rows = []
        for identifier in refs:
            row = await connection.fetchrow('''SELECT o.*,w.producer_credential_id,w.producer_generation,w.binding_revision,
                w.revision AS current_workspace_revision,w.state AS workspace_state FROM am_code_observations o
                JOIN am_code_workspaces w ON w.id=o.workspace_id WHERE o.id=$1 AND o.binding_id=$2''', identifier, binding_id)
            if row is None or row['state'] != 'active' or row['workspace_state'] != 'active' or row['metadata'] is None:
                raise DomainError('CODE_ANCHOR_INVALID', 'Every required code anchor must remain available')
            try:
                producer = await self._credential(connection, row['producer_credential_id'])
            except DomainError as error:
                if error.code != 'AUTH_DENIED' or error.status != 401:
                    raise
                raise DomainError('CODE_ANCHOR_INVALID', 'The registered code authority changed') from None
            revision = await connection.fetchval('SELECT revision FROM am_bindings WHERE id=$1', binding_id)
            if (producer.role != Role.PRODUCER or producer.generation != row['producer_generation']
                or binding_id not in producer.bindings or row['workspace_revision'] != row['current_workspace_revision']
                or revision != row['binding_revision']):
                raise DomainError('CODE_ANCHOR_INVALID', 'The registered code authority changed')
            metadata = _decode(row['metadata'])
            if metadata['status'] != 'present' or (row['symbol_name'] and metadata.get('symbol') is None):
                raise DomainError('CODE_ANCHOR_INVALID', 'An unavailable anchor cannot be waived by a review')
            rows.append(row)
        return rows

    async def _health_admission(self, connection, clock, actor, binding_id: str, admission_id: str, purpose: str):
        row = await connection.fetchrow("""SELECT * FROM am_admissions WHERE id=$1 AND binding_id=$2
            AND purpose=$3 AND kind='nonmodel'""", admission_id, binding_id, purpose)
        if row is None:
            raise DomainError('ADMISSION_STALE', 'Inspect the current bounded health input first')
        await self._recheck_nonmodel(connection, clock, actor, self._nonmodel_admission(row))
        return row, _decode(row['health_manifest'])

    async def _record_claim_health(self, connection, clock, actor, command, operation_id: str) -> str:
        from .health import CodeLinkCommand
        _, manifest = await self._health_admission(connection, clock, actor, command.binding_id,
            command.admission_id, 'health_claim')
        claim = await self._claim_row(connection, command.binding_id, command.claim_ref.id, manifest['snapshot'])
        state = await self._ensure_health_state(connection, claim)
        if (claim['revision'] != command.claim_ref.revision or state['version'] != command.expected_health_version
            or manifest['claims'][0]['claim'] != command.claim_ref.model_dump()):
            raise DomainError('HEALTH_STALE', 'The exact inspected claim or health version changed')
        if isinstance(command, CodeLinkCommand):
            rows = await self._usable_observations(connection, command.binding_id, command.observation_refs)
            permitted = set(manifest['available_observation_refs'])
            if not set(command.observation_refs).issubset(permitted):
                raise DomainError('ADMISSION_STALE', 'Inspect every code observation before linking it')
            for row in rows:
                await connection.execute('''INSERT INTO am_code_links(claim_id,claim_revision,observation_id)
                    VALUES($1,$2,$3) ON CONFLICT DO NOTHING''', claim['id'], claim['revision'], row['id'])
            count = await connection.fetchval('SELECT count(*) FROM am_code_links WHERE claim_id=$1 AND claim_revision=$2',
                claim['id'], claim['revision'])
            if count > 32:
                raise DomainError('MANIFEST_TOO_LARGE', 'A claim supports at most32 explicit code dependencies')
            event = await self._health_event(connection, actor, command, operation_id, target=claim['id'],
                claim_ids=[claim['id']], payload={'claim_ref': command.claim_ref.model_dump(),
                    'added_observation_refs': command.observation_refs}, reason=command.reason)
            await connection.execute('UPDATE am_claim_health SET version=version+1 WHERE claim_id=$1', claim['id'])
        else:
            if state['review_event_id'] != command.expected_review_event_id:
                raise DomainError('HEALTH_STALE', 'The prior operator review event changed')
            old = await self._code_dependencies(connection, claim)
            if command.decision == 'accept':
                rows = await self._usable_observations(connection, command.binding_id, command.revalidated_observation_refs)
                if not set(command.revalidated_observation_refs).issubset(set(manifest['available_observation_refs'])):
                    raise DomainError('ADMISSION_STALE', 'Inspect every revalidation observation before accepting')
                expected = {(item['workspace_id'], item['relative_path'], item['symbol_name']) for item in old}
                actual = {(item['workspace_id'], item['relative_path'], item['symbol_name']) for item in rows}
                if len(actual) != len(rows) or expected != actual:
                    raise DomainError('CODE_ANCHOR_INVALID', 'Accept must revalidate the complete existing dependency identities')
                # Only an explicit exact operator Accept can replace stale links; agents can only add links.
                await connection.execute('DELETE FROM am_code_links WHERE claim_id=$1 AND claim_revision=$2',
                    claim['id'], claim['revision'])
                for row in rows:
                    await connection.execute('INSERT INTO am_code_links(claim_id,claim_revision,observation_id) VALUES($1,$2,$3)',
                        claim['id'], claim['revision'], row['id'])
            event = await self._health_event(connection, actor, command, operation_id, target=claim['id'],
                claim_ids=[claim['id']], payload={'claim_ref': command.claim_ref.model_dump(),
                    'decision': command.decision, 'prior_review_event_id': state['review_event_id'],
                    'prior_health_version': state['version'], 'provenance': 'human_presence_unattested',
                    'revalidated_observation_refs': command.revalidated_observation_refs}, reason=command.reason)
            await connection.execute('''UPDATE am_claim_health SET version=version+1,operator_review=$2,review_event_id=$3,
                needs_review=CASE WHEN $2='accept' THEN false ELSE needs_review END,
                restore_unknown=CASE WHEN $2='accept' THEN false ELSE restore_unknown END,
                freshness=CASE WHEN $2='accept' THEN $4 ELSE freshness END WHERE claim_id=$1''',
                claim['id'], command.decision, event, 'observed_current' if old else 'unknown')
            await connection.execute('''UPDATE am_pending_judgments SET state='resolved',resolved_at=clock_timestamp(),
                health_payload=health_payload - 'disposition',health_revision=health_revision+1
                WHERE binding_id=$1 AND kind='health' AND health_key=$2 AND state<>'retracted' ''',
                command.binding_id, 'code:' + claim['id'])
        await connection.execute('DELETE FROM am_admissions WHERE id=$1', command.admission_id)
        return event

    async def _record_session_observation(self, connection, actor, command, operation_id: str) -> str:
        if len(command.claim_refs) > 20:
            raise DomainError('MANIFEST_TOO_LARGE', 'A segment supports at most 20 exact target claims')
        if actor.role == Role.PRODUCER and not await connection.fetchval('''SELECT EXISTS(SELECT 1 FROM am_code_workspaces
            WHERE binding_id=$1 AND producer_credential_id=$2 AND producer_generation=$3 AND state='active'
            AND binding_revision=$4)''', command.binding_id, actor.credential_id, actor.generation,
            command.expected_binding_revision):
            raise _denied()
        prior = await connection.fetchrow('''SELECT * FROM am_session_observations WHERE binding_id=$1
            AND credential_id=$2 AND credential_generation=$3 AND stream_id=$4 AND segment_id=$5
            AND (event_id=$6 OR sequence=$7)''', command.binding_id, actor.credential_id, actor.generation,
            command.stream_id, command.segment_id, command.event_id, command.sequence)
        digest = canonical_digest(command.model_dump(mode='json', exclude={'idempotency_key'}))
        if prior is not None:
            if prior['digest'] != digest or prior['state'] != 'active':
                raise DomainError('SESSION_OBSERVATION_CONFLICT', 'The segment event identity already names different data')
            return prior['id']
        count = await connection.fetchval('''SELECT count(*) FROM am_session_observations WHERE binding_id=$1
            AND credential_id=$2 AND credential_generation=$3 AND stream_id=$4 AND segment_id=$5''',
            command.binding_id, actor.credential_id, actor.generation, command.stream_id, command.segment_id)
        if count >= 128:
            raise DomainError('MANIFEST_TOO_LARGE', 'Close a new explicitly identified bounded segment')
        identifier = _id('session')
        await connection.execute('''INSERT INTO am_session_observations(id,binding_id,credential_id,credential_generation,
            stream_id,segment_id,event_id,sequence,digest,payload) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb)''',
            identifier, command.binding_id, actor.credential_id, actor.generation, command.stream_id,
            command.segment_id, command.event_id, command.sequence, digest,
            _json(command.model_dump(mode='json', exclude={'idempotency_key'})))
        await self._refresh_session_work(connection, command.binding_id, actor.credential_id, actor.generation,
            command.stream_id, command.segment_id)
        return identifier

    async def _refresh_session_work(self, connection, binding_id, credential_id, generation, stream_id, segment_id) -> None:
        rows = await connection.fetch('''SELECT * FROM am_session_observations WHERE binding_id=$1 AND credential_id=$2
            AND credential_generation=$3 AND stream_id=$4 AND segment_id=$5 AND state='active' ORDER BY sequence''',
            binding_id, credential_id, generation, stream_id, segment_id)
        if not rows:
            return
        events = [_decode(row['payload']) for row in rows]
        if any(event is None for event in events):
            return
        current_revision = await connection.fetchval('SELECT revision FROM am_bindings WHERE id=$1', binding_id)
        if any(event['expected_binding_revision'] != current_revision for event in events):
            raise DomainError('HEALTH_STALE', 'The observed segment binding authority changed')
        sources, claims, origins, gaps = {}, {}, set(), set()
        roots = {event['root_run_id'] for event in events}
        agents = {event['agent_path'] for event in events}
        if len(roots) != 1 or len(agents) != 1:
            raise DomainError('SESSION_OBSERVATION_CONFLICT', 'A segment cannot change its declared root or agent identity')
        root, agent_path = next(iter(roots)), next(iter(agents))
        for event in events:
            gaps.update(event['gaps'])
            if event['coverage'] != 'observed_segment':
                gaps.add('SESSION_PARTIAL_CAPTURE')
            origins.update(event['origin_keys'])
            for ref in event['source_refs']:
                if ref['id'] in sources and sources[ref['id']] != ref['revision']:
                    raise DomainError('HEALTH_STALE', 'A session declares conflicting exact source revisions')
                sources[ref['id']] = ref['revision']
            for ref in event['claim_refs']:
                if ref['id'] in claims and claims[ref['id']] != ref['revision']:
                    raise DomainError('HEALTH_STALE', 'A session declares conflicting exact claim revisions')
                claims[ref['id']] = ref['revision']
        if len(origins) > 128 or len(sources) > 128 or len(claims) > 20:
            raise DomainError('MANIFEST_TOO_LARGE', 'Split the observed session into bounded segments')
        producer = await self._credential(connection, credential_id)
        for origin in sorted(origins):
            found = await connection.fetchrow('''SELECT s.* FROM am_sources s JOIN am_operations o ON o.id=s.operation_id
                WHERE s.binding_id=$1 AND s.origin_key=$2 AND o.credential_id=$3 AND s.producer_generation=$4''',
                binding_id, origin, credential_id, generation)
            if found is None:
                gaps.add('SESSION_ORIGIN_PENDING')
            else:
                sources[found['id']] = found['revision']
        for identifier, revision in sources.items():
            source = await connection.fetchrow('''SELECT s.*,o.credential_id FROM am_sources s
                JOIN am_operations o ON o.id=s.operation_id WHERE s.id=$1 AND s.binding_id=$2''', identifier, binding_id)
            if (source is None or source['state'] != 'active' or source['body'] is None or source['revision'] != revision
                or source['speaker'] in {'agent_note', 'memory'} or source['realm'] != producer.realm
                or source['credential_id'] != credential_id or source['producer_generation'] != generation
                or source['root_run_id'] != root or source['agent_path'] != agent_path):
                raise DomainError('SESSION_SOURCE_INVALID', 'A segment source must match its registered producer and declared lineage')
        for identifier, revision in claims.items():
            claim = await connection.fetchrow('''SELECT revision,state,draft FROM am_claims
                WHERE id=$1 AND binding_id=$2''', identifier, binding_id)
            if claim is None or claim['state'] != 'active' or claim['draft'] is None or claim['revision'] != revision:
                raise DomainError('HEALTH_STALE', 'An observed target claim revision changed')
        boundaries = [event for event in events if event['event'] != 'checkpoint']
        closed = bool(boundaries) and boundaries[-1]['event'] in {'end', 'interrupted'}
        if not closed:
            gaps.add('SESSION_CLOSE_UNOBSERVED')
        if not boundaries or boundaries[0]['event'] not in {'start', 'resume'}:
            gaps.add('SESSION_START_UNOBSERVED')
        if rows[0]['sequence'] != 1 or any(b['sequence'] != a['sequence'] + 1 for a, b in zip(rows, rows[1:])):
            gaps.add('SESSION_SEQUENCE_GAP')
        if boundaries and boundaries[-1]['event'] == 'interrupted':
            gaps.add('SESSION_INTERRUPTED')
        if len(sources) > 128:
            raise DomainError('MANIFEST_TOO_LARGE', 'The complete session origin manifest exceeds128 sources')
        key = 'session:' + canonical_digest({'credential_id': credential_id, 'generation': generation,
            'stream_id': stream_id, 'segment_id': segment_id})
        pending_id = await self._enqueue_health(connection, binding_id, key, sources=sources, claims=claims,
            payload={'cause': 'observed_session', 'session_observation_ids': [row['id'] for row in rows],
                'source_refs': [{'id': identifier, 'revision': revision} for identifier, revision in sorted(sources.items())],
                'claim_refs': [{'id': identifier, 'revision': revision} for identifier, revision in sorted(claims.items())],
                'unresolved_origin_keys': sorted(origins) if 'SESSION_ORIGIN_PENDING' in gaps else [],
                'coverage': 'partial' if gaps else 'observed_segment', 'gaps': sorted(gaps),
                'scope': 'authorized_observed_segment_not_full_session', 'human_presence': 'unattested'})
        if not closed or not sources:
            await connection.execute('''UPDATE am_pending_judgments SET state='held',
                reason='Awaiting observed segment close and independent captured-source watermark'
                WHERE id=$1 AND state IN ('pending','held')''', pending_id)

    async def _refresh_late_session_capture(self, connection, binding_id, origin_key: str) -> None:
        rows = connection.cursor('''SELECT DISTINCT o.credential_id,o.credential_generation,o.stream_id,o.segment_id
            FROM am_session_observations o JOIN am_credentials c ON c.id=o.credential_id
                AND c.active AND c.generation=o.credential_generation
            WHERE o.binding_id=$1 AND o.state='active' AND o.payload->'origin_keys' ? $2''',
            binding_id, origin_key, prefetch=16)
        async for row in rows:
            try:
                await self._refresh_session_work(connection, binding_id, row['credential_id'], row['credential_generation'],
                    row['stream_id'], row['segment_id'])
            except DomainError as error:
                if error.code not in {'HEALTH_STALE', 'SESSION_SOURCE_INVALID', 'SESSION_SNAPSHOT_CONFLICT',
                    'MANIFEST_TOO_LARGE', 'QUEUE_FULL', 'CLAIM_INELIGIBLE'}:
                    raise
                # Health metadata must not roll back an independently valid source capture.
                key = 'session:' + canonical_digest({'credential_id': row['credential_id'],
                    'generation': row['credential_generation'], 'stream_id': row['stream_id'], 'segment_id': row['segment_id']})
                await connection.execute('''UPDATE am_pending_judgments SET
                    state=CASE WHEN state='resolved' THEN 'resolved' ELSE 'held' END,
                    resolved_at=CASE WHEN state='resolved' THEN resolved_at ELSE NULL END,
                    reason='Observed session health refresh requires explicit review',health_revision=health_revision+1,
                    health_payload=health_payload || jsonb_build_object('refresh_error_code',$3::text)
                        || CASE WHEN state='resolved' AND NOT (health_payload ? 'disposition')
                            THEN jsonb_build_object('disposition',jsonb_build_object(
                                'decision','deferred_unknown','assessment_complete',false)) ELSE '{}'::jsonb END
                    WHERE binding_id=$1 AND kind='health' AND health_key=$2
                    AND state<>'retracted'
                    AND (state NOT IN ('held','resolved') OR health_payload->>'refresh_error_code' IS DISTINCT FROM $3)''',
                    binding_id, key, error.code)

    async def _health_work_manifest(self, connection, binding_id: str, pending_id: str, snapshot: str | None) -> tuple[dict, dict]:
        pending = await connection.fetchrow("""SELECT * FROM am_pending_judgments WHERE id=$1 AND binding_id=$2
            AND kind='health' AND state IN ('pending','held')""", pending_id, binding_id)
        if pending is None:
            raise DomainError('ADMISSION_STALE', 'This health work is no longer pending')
        if pending['snapshot'] is not None and pending['snapshot'] != snapshot:
            raise DomainError('SNAPSHOT_INELIGIBLE', 'The health work belongs to a different request snapshot')
        policy = await self._health_policy(connection, binding_id)
        payload = _decode(pending['health_payload'])
        gaps = set(payload.get('gaps', []))
        if payload.get('refresh_error_code'):
            gaps.add('SESSION_REFRESH_INCOMPLETE')
        if len(pending['source_ids']) > policy['max_audit_sources']:
            raise DomainError('HEALTH_BUNDLE_TOO_LARGE', 'The complete source manifest exceeds current explicit policy')
        from .lexical import tokens as tokenize
        source_rows, source_refs, tokens = [], [], set()
        for identifier in pending['source_ids']:
            source = await self._source_row(connection, binding_id, identifier, snapshot, True)
            raw = source['body'].encode('utf-8')
            source_rows.append((source, raw))
            source_refs.append({'id': identifier, 'revision': source['revision']})
            tokens.update(tokenize(raw[:4096].decode('utf-8', errors='ignore')))
        claim_ids = list(pending['claim_ids'])
        if not claim_ids and source_refs:
            rows = await connection.fetch("""SELECT c.id FROM am_claims c WHERE c.binding_id=$1 AND c.state='active'
                AND c.draft IS NOT NULL AND c.superseded_by IS NULL AND c.capability='agent_judged'
                AND c.lexical_tokens && $2::text[] AND (c.snapshot IS NULL OR c.snapshot IS NOT DISTINCT FROM $3)
                AND (c.valid_from IS NULL OR c.valid_from<=clock_timestamp())
                AND (c.valid_until IS NULL OR c.valid_until>clock_timestamp())
                AND (c.selection_id IS NULL OR EXISTS(SELECT 1 FROM am_source_selections q
                    WHERE q.id=c.selection_id AND q.state='active'))
                AND EXISTS(SELECT 1 FROM am_claim_sources d WHERE d.claim_id=c.id)
                AND NOT EXISTS(SELECT 1 FROM am_claim_sources d JOIN am_sources s ON s.id=d.source_id
                    WHERE d.claim_id=c.id AND (s.state<>'active' OR s.body IS NULL OR s.revision<>d.source_revision
                        OR s.binding_id<>$1 OR s.realm<>$5 OR (s.snapshot IS NOT NULL AND s.snapshot IS DISTINCT FROM $3)))
                ORDER BY cardinality(ARRAY(SELECT unnest(c.lexical_tokens) INTERSECT SELECT unnest($2::text[]))) DESC,c.id
                LIMIT $4""", binding_id, sorted(tokens)[:2048], snapshot, policy['max_audit_claims'] + 1,
                self.settings.realm)
            if len(rows) > policy['max_audit_claims']:
                gaps.add('AUDIT_TARGET_CANDIDATES_PARTIAL')
            claim_ids = [row['id'] for row in rows[:policy['max_audit_claims']]]
        if len(claim_ids) > policy['max_audit_claims']:
            raise DomainError('HEALTH_BUNDLE_TOO_LARGE', 'The complete target manifest exceeds current explicit policy')
        claims, manifests = [], []
        for identifier in claim_ids:
            claim = await self._claim_row(connection, binding_id, identifier, snapshot)
            meaning = ClaimMeaning.model_validate(_decode(claim['draft'])).model_dump(mode='json')
            manifests.append({**await self._claim_health_manifest(connection, claim),
                'meaning_digest': canonical_digest(meaning)})
            claims.append({'id': claim['id'], 'revision': claim['revision'], **meaning})
        remaining = policy['max_audit_bytes'] - sum(len(json.dumps(claim,
            ensure_ascii=False, separators=(',', ':')).encode('utf-8')) for claim in claims)
        if remaining < 4 * len(source_rows):
            raise DomainError('HEALTH_BUNDLE_TOO_LARGE', 'Complete claim meanings and nonempty source windows exceed current policy')
        sources = []
        for index, (source, raw) in enumerate(source_rows):
            available = min(4096, remaining - 4 * (len(source_rows) - index - 1))
            body = raw[:available].decode('utf-8', errors='ignore')
            length = len(body.encode('utf-8'))
            remaining -= length
            capture = _decode(source['capture_coverage'])
            complete = length == len(raw)
            if not complete:
                gaps.add('AUDIT_SOURCE_WINDOW_PARTIAL')
            if capture.get('status') != 'observed_window' or capture.get('gaps'):
                gaps.add('AUDIT_CAPTURE_PARTIAL')
            sources.append({'source_ref': {'id': source['id'], 'revision': source['revision']},
                'body': body, 'byte_start': 0, 'byte_end': length, 'total_bytes': len(raw),
                'speaker': source['speaker'], 'capture_coverage': capture,
                'coverage': 'complete_captured_window' if complete else 'partial_captured_window',
                'scope': 'captured_source_not_session', 'human_presence': 'unattested'})
        if not claims:
            gaps.add('AUDIT_NO_TARGET_EVIDENCE')
        if not source_refs:
            gaps.add('AUDIT_NO_SOURCE_EVIDENCE')
        observations = payload.get('session_observation_ids', [])
        rows = await connection.fetch("""SELECT payload FROM am_session_observations
            WHERE binding_id=$1 AND id=ANY($2::text[]) AND state='active' ORDER BY sequence""",
            binding_id, observations) if observations else []
        boundaries = []
        for row in rows:
            event = _decode(row['payload'])['event']
            if event != 'checkpoint':
                boundaries.append(event)
        observed_window_closed = (payload.get('cause') == 'observed_session' and len(rows) == len(observations)
            and bool(boundaries) and boundaries[-1] in {'end', 'interrupted'}
            and not payload.get('unresolved_origin_keys') and not payload.get('refresh_error_code'))
        manifest = {'purpose': 'health_work', 'pending_id': pending_id, 'pending_revision': pending['health_revision'],
            'payload_digest': canonical_digest(payload), 'policy': policy, 'claims': manifests,
            'input_sources': source_refs, 'snapshot': snapshot,
            'observed_window_closed': observed_window_closed,
            'evidence_windows': [{'ref': source['source_ref'], 'byte_start': source['byte_start'], 'byte_end': source['byte_end'],
                'digest': hashlib.sha256(source['body'].encode('utf-8')).hexdigest()} for source in sources],
            'coverage': {'scope': 'bounded_authorized_inputs', 'complete': not gaps, 'partial': bool(gaps), 'gaps': sorted(gaps)}}
        return manifest, {'sources': sources, 'claims': claims}

    async def _record_health_assessment(self, connection, clock, actor, command, operation_id: str) -> str:
        _, manifest = await self._health_admission(connection, clock, actor, command.binding_id,
            command.admission_id, 'health_work')
        if not manifest['policy']['enabled']:
            raise DomainError('HEALTH_DISABLED', 'Health processing requires current explicit authorization')
        if (command.pending_id != manifest['pending_id'] or canonical_digest(manifest) != command.health_manifest_digest
            or [item.model_dump() for item in command.input_sources] != manifest['input_sources']
            or [item.model_dump() for item in command.input_claims] != [item['claim'] for item in manifest['claims']]):
            raise DomainError('HEALTH_STALE', 'Health results must cover the complete exact inspected manifest')
        windows = {item['ref']['id']: item for item in manifest['evidence_windows']}
        source_revisions = {item.id: item.revision for item in command.input_sources}
        for assessment in command.assessments:
            for evidence in assessment.evidence:
                window = windows.get(evidence.source_ref.id)
                if (window is None or source_revisions.get(evidence.source_ref.id) != evidence.source_ref.revision
                    or evidence.byte_start < window['byte_start'] or evidence.byte_end > window['byte_end']):
                    raise DomainError('EVIDENCE_INVALID', 'Assessment evidence must belong to its exact admitted source window')
                source = await self._source_row(connection, command.binding_id, evidence.source_ref.id,
                    manifest['snapshot'], True)
                if source['speaker'] in {'memory', 'agent_note'}:
                    raise DomainError('EVIDENCE_INVALID', 'Reasons and injected memory are not independent health grounding')
                raw = source['body'].encode('utf-8')
                if raw[evidence.byte_start:evidence.byte_end] != evidence.quote.encode('utf-8'):
                    raise DomainError('EVIDENCE_INVALID', 'Health evidence must match the exact original UTF-8 bytes')
        event = await self._health_event(connection, actor, command, operation_id,
            target=command.pending_id, source_ids=[item.id for item in command.input_sources],
            claim_ids=[item.id for item in command.input_claims],
            payload={'health_manifest_digest': command.health_manifest_digest,
                'input_sources': [item.model_dump() for item in command.input_sources],
                'input_claims': [item.model_dump() for item in command.input_claims],
                'coverage': manifest['coverage'], 'evaluation_receipt_digest': command.evaluation_receipt_digest})
        for assessment in command.assessments:
            claim = await self._claim_row(connection, command.binding_id, assessment.claim_ref.id, manifest['snapshot'])
            await self._ensure_health_state(connection, claim)
            assessment_event = await self._health_event(connection, actor, command, operation_id, target=claim['id'],
                source_ids=[item.id for item in command.input_sources], claim_ids=[claim['id']],
                payload={'assessment': assessment.model_dump(mode='json', exclude={'reason'}),
                    'assessment_event_id': event, 'health_manifest_digest': command.health_manifest_digest,
                    'input_sources': [item.model_dump() for item in command.input_sources]},
                reason=assessment.reason)
            if assessment.support == 'contradicted' or assessment.freshness == 'stale':
                await connection.execute('''UPDATE am_claim_health SET version=version+1,support=$2,
                    freshness=CASE WHEN $3='stale' THEN 'stale' ELSE freshness END,
                    needs_review=true,assessment_event_id=$4 WHERE claim_id=$1''',
                    claim['id'], assessment.support, assessment.freshness, assessment_event)
            else:
                # A machine can add evidence, never reverse Reject, stale code or restore quarantine.
                await connection.execute('''UPDATE am_claim_health SET version=version+1,support=$2,
                    freshness=CASE WHEN freshness='stale' THEN freshness ELSE $3 END,
                    assessment_event_id=$4 WHERE claim_id=$1''',
                    claim['id'], assessment.support if manifest['coverage']['complete'] else 'unknown',
                    assessment.freshness if manifest['coverage']['complete'] else 'unknown', assessment_event)
        # Completing bounded observed work does not affirm any claim's freshness.
        disposition = 'resolved' if manifest['observed_window_closed'] else 'held'
        await connection.execute('''UPDATE am_pending_judgments SET state=$2,
            reason=CASE WHEN $2='held' THEN 'Bounded health evidence incomplete; operator or next-agent review required' ELSE reason END,
            resolved_at=CASE WHEN $2='resolved' THEN clock_timestamp() ELSE NULL END WHERE id=$1''',
            command.pending_id, disposition)
        await connection.execute('DELETE FROM am_admissions WHERE id=$1', command.admission_id)
        return event

    async def _record_health_work_disposition(self, connection, actor, command, operation_id: str) -> str:
        pending = await connection.fetchrow("""SELECT * FROM am_pending_judgments WHERE binding_id=$1
            AND id=$2 AND kind='health' AND state<>'retracted'""", command.binding_id, command.pending_id)
        if pending is None or pending['health_revision'] != command.expected_pending_revision:
            raise DomainError('HEALTH_STALE', 'Inspect the current exact health work revision')
        if pending['snapshot'] is not None and pending['snapshot'] != command.snapshot:
            raise DomainError('SNAPSHOT_INELIGIBLE', 'The health work belongs to a different request snapshot')
        payload = _decode(pending['health_payload'])
        if payload.get('feedback_ref'):
            raise DomainError('HEALTH_DISPOSITION_INVALID', 'Feedback candidates require their exact accept or decline workflow')
        if command.decision == 'close_unknown':
            if pending['state'] not in {'pending', 'held'}:
                raise DomainError('HEALTH_STALE', 'Only outstanding work can be closed as unknown')
        else:
            if pending['state'] != 'resolved' or payload.get('disposition', {}).get('decision') not in {'close_unknown', 'deferred_unknown'}:
                raise DomainError('HEALTH_STALE', 'Only terminal unknown work can be explicitly reopened')
            await self._require_health_capacity(connection, command.binding_id)
        event = await self._health_event(connection, actor, command, operation_id, target=pending['id'],
            payload={'decision': command.decision, 'pending_revision': pending['health_revision'],
                'snapshot': command.snapshot, 'assessment_complete': False}, reason=command.reason)
        if command.decision == 'close_unknown':
            payload['disposition'] = {'decision': 'close_unknown', 'event_ref': event, 'assessment_complete': False}
        else:
            payload.pop('disposition', None)
        await connection.execute("""UPDATE am_pending_judgments SET state=$2,health_revision=health_revision+1,
            health_payload=$3::jsonb,resolved_at=CASE WHEN $2='resolved' THEN clock_timestamp() ELSE NULL END,
            reason='Explicit work disposition; no claim approval or completeness asserted' WHERE id=$1""",
            pending['id'], 'resolved' if command.decision == 'close_unknown' else 'held', _json(payload))
        return event

    async def _feedback_health_manifest(self, connection, binding_id, feedback_ref, snapshot) -> tuple[dict, dict]:
        feedback = await connection.fetchrow("SELECT * FROM am_feedback WHERE id=$1 AND binding_id=$2 AND kind IN ('correct','retract_request')",
            feedback_ref, binding_id)
        if feedback is None:
            raise _missing()
        disclosure = await self._disclosure_manifest(connection, binding_id, feedback_ref, snapshot)
        reason = None
        if disclosure is not None and feedback['source_id']:
            row = await connection.fetchrow("""SELECT revision,state,body FROM am_sources WHERE id=$1 AND binding_id=$2
                AND realm=$3""", feedback['source_id'], binding_id, self.settings.realm)
            if row and row['state'] == 'active':
                reason = row['body']
        manifest = {'purpose': 'health_feedback', 'feedback_ref': feedback_ref,
            'version': feedback['health_version'], 'resolution_event_id': feedback['resolution_event_id'],
            'target_ref': feedback['target_ref'], 'kind': feedback['kind'], 'state': feedback['state'],
            'snapshot': snapshot, 'disclosure': disclosure, 'reason_digest': canonical_digest({'reason': reason})}
        candidate = {'id': feedback_ref, 'kind': feedback['kind'],
            'version': feedback['health_version'], 'resolution_event_id': feedback['resolution_event_id'],
            'body': reason, 'body_unavailable': reason is None, 'candidate': True}
        if disclosure is not None:
            candidate['target_ref'] = feedback['target_ref']
        return manifest, candidate


    async def _resolve_health_feedback(self, connection, clock, actor, command, operation_id: str) -> str:
        _, manifest = await self._health_admission(connection, clock, actor, command.binding_id,
            command.admission_id, 'health_feedback')
        if command.feedback_ref != manifest['feedback_ref'] or command.expected_feedback_version != manifest['version']:
            raise DomainError('HEALTH_STALE', 'The inspected feedback version changed')
        if command.decision == 'accept':
            successor = await self._operation_row(connection, command.binding_id, command.successor_operation_id)
            try:
                principal = await self._credential(connection, successor['credential_id'])
            except DomainError as error:
                if error.code != 'AUTH_DENIED' or error.status != 401 or successor['credential_id'] == actor.credential_id:
                    raise
                raise _denied() from None
            if (command.binding_id not in principal.bindings or principal.role not in {Role.OPERATOR, Role.PRODUCER}
                    or successor['actor_generation'] != principal.generation):
                raise _denied()
            if manifest['kind'] == 'correct':
                matched = await connection.fetchval("""SELECT EXISTS(SELECT 1 FROM am_receipts i JOIN am_receipts r
                    ON r.principal_id=i.principal_id AND r.binding_id=i.binding_id AND r.request_key=i.request_key
                    AND r.digest=i.digest AND r.kind='correct'
                    WHERE i.binding_id=$1 AND i.kind='correct_intent' AND i.target_id=$2
                    AND i.result->>'state'='completed' AND r.target_id=$3)""",
                    command.binding_id, manifest['target_ref'], successor['id'])
                if successor['kind'] != 'correct' or successor['state'] not in {'captured', 'candidate_ready', 'selection_recorded'} or not matched:
                    raise DomainError('FEEDBACK_SUCCESSOR_INVALID', 'Accept requires the matching committed authorized correction')
                await self._source_row(connection, command.binding_id, successor['source_id'])
            else:
                matched = await connection.fetchval("""SELECT EXISTS(SELECT 1 FROM am_receipts WHERE binding_id=$1
                    AND kind='retract' AND target_id=$2 AND result->>'operation_id'=$3
                    AND result->>'logical_retraction'='committed')""",
                    command.binding_id, manifest['target_ref'], successor['id'])
                if successor['kind'] != 'retract' or successor['artifact_id'] != manifest['target_ref'] or not matched:
                    raise DomainError('FEEDBACK_SUCCESSOR_INVALID', 'Accept requires the matching committed authorized retraction')
        event = await self._health_event(connection, actor, command, operation_id, target=command.feedback_ref,
            payload={'decision': command.decision, 'prior_version': manifest['version'],
                'prior_resolution_event_id': manifest['resolution_event_id'],
                'successor_operation_id': command.successor_operation_id,
                'provenance': 'human_presence_unattested'}, reason=command.reason)
        await connection.execute('''UPDATE am_feedback SET health_version=health_version+1,resolution_event_id=$2
            WHERE id=$1''', command.feedback_ref, event)
        await connection.execute("""UPDATE am_pending_judgments SET state='resolved',resolved_at=clock_timestamp()
            WHERE binding_id=$1 AND kind='health' AND health_key=$2""",
            command.binding_id, 'feedback:' + command.feedback_ref)
        await connection.execute('DELETE FROM am_admissions WHERE id=$1', command.admission_id)
        return event

    async def health_observer(self, actor: Principal, binding_id: str) -> dict:
        async with self._tx(lock=False) as (connection, _):
            current = await self._actor(connection, actor, binding_id, (Role.PRODUCER, Role.OPERATOR))
            return await self._health_observer(connection, current, binding_id)

    async def _health_observer(self, connection, current, binding_id: str) -> dict:
        policy = await self._health_policy(connection, binding_id)
        revision = await connection.fetchval('SELECT revision FROM am_bindings WHERE id=$1', binding_id)
        rows = await connection.fetch("""SELECT * FROM am_code_workspaces WHERE binding_id=$1 AND state='active'
            AND ($2='operator' OR (producer_credential_id=$3 AND producer_generation=$4))
            ORDER BY id""", binding_id, current.role.value, current.credential_id, current.generation)
        workspaces = []
        for row in rows:
            try:
                producer = await self._credential(connection, row['producer_credential_id'])
            except DomainError as error:
                if error.code != 'AUTH_DENIED' or error.status != 401:
                    raise
                continue
            if producer.role != Role.PRODUCER or producer.generation != row['producer_generation'] or binding_id not in producer.bindings:
                continue
            linked = await connection.fetch("""SELECT DISTINCT o.relative_path,o.symbol_name FROM am_code_links d
                JOIN am_code_observations o ON o.id=d.observation_id JOIN am_claims c ON c.id=d.claim_id
                WHERE o.workspace_id=$1 AND c.binding_id=$2 AND c.state='active' AND d.claim_revision=c.revision
                ORDER BY o.relative_path,o.symbol_name""", row['id'], binding_id)
            paths = {}
            for item in linked:
                paths.setdefault(item['relative_path'], [])
                if item['symbol_name']:
                    paths[item['relative_path']].append(item['symbol_name'])
            observations = await connection.fetch("""SELECT id,relative_path,symbol_name,metadata FROM am_code_observations
                WHERE workspace_id=$1 AND state='active'
                AND (symbol_name='' OR id IN (SELECT observation_id FROM am_code_links))
                ORDER BY relative_path,symbol_name""", row['id'])
            workspaces.append({'workspace_id': row['id'], 'revision': row['revision'],
                'binding_revision': row['binding_revision'], 'root_fingerprint': row['root_fingerprint'],
                'producer_credential_id': row['producer_credential_id'], 'last_sequence': row['last_sequence'],
                'linked_paths': [{'relative_path': path, 'symbol_names': names} for path, names in paths.items()],
                'current_observations': [{'ref': item['id'], 'relative_path': item['relative_path'],
                    'symbol_name': item['symbol_name'], **_decode(item['metadata'])} for item in observations],
                'coverage': {'complete': True, 'scope': 'registered_explicit_observations_not_filesystem_catalog'}})
        result = {'kind': 'health_observer', 'binding_id': binding_id, 'binding_revision': revision,
            'policy': policy, 'workspaces': workspaces, 'coverage': {'complete': True, 'scope': 'authorized_registered_workspaces'}}
        from .representation import serialized_json_bytes
        if serialized_json_bytes(result) > self.settings.max_inspection_json_bytes:
            raise DomainError('HEALTH_OBSERVER_TOO_LARGE', 'The complete producer-safe registry exceeds its response bound', status=413)
        return result

    async def _claim_review_manifest(self, connection, binding_id, claim_id, snapshot, nominated=None) -> tuple[dict, dict]:
        claim = await self._claim_row(connection, binding_id, claim_id, snapshot)
        state = await self._claim_health_manifest(connection, claim)
        classification_eligible = await self._health_classification_eligible(connection, binding_id, claim, snapshot)
        current = []
        identities = {(item['workspace_id'], item['relative_path'], item['symbol_name']) for item in state['code']}
        for workspace_id, path, symbol in sorted(identities):
            row = await connection.fetchrow("""SELECT * FROM am_code_observations WHERE workspace_id=$1 AND relative_path=$2
                AND symbol_name=$3 AND state='active' AND binding_id=$4""", workspace_id, path, symbol, binding_id)
            if row is not None:
                current.append(row)
        if nominated is not None:
            row = await connection.fetchrow('SELECT * FROM am_code_observations WHERE id=$1 AND binding_id=$2',
                nominated, binding_id)
            if row is None or row['state'] != 'active':
                raise DomainError('CODE_ANCHOR_INVALID', 'The nominated observation is unavailable')
            if all(item['id'] != row['id'] for item in current):
                current.append(row)
        if len(current) > 32:
            raise DomainError('MANIFEST_TOO_LARGE', 'Inspect and link at most32 dependencies per exact revision')
        observations = [{'ref': row['id'], 'workspace_id': row['workspace_id'],
            'workspace_revision': row['workspace_revision'], 'relative_path': row['relative_path'],
            'symbol_name': row['symbol_name'], 'fingerprint': row['fingerprint'],
            'metadata': _decode(row['metadata'])} for row in current]
        manifest = {'purpose': 'health_claim', 'snapshot': snapshot, 'claims': [state],
            'classification_eligible': classification_eligible,
            'available_observation_refs': [row['id'] for row in current],
            'available_observations': observations, 'nominated': nominated,
            'policy': await self._health_policy(connection, binding_id)}
        reusable = classification_eligible
        try:
            await self._reuse_claim(connection, claim)
        except DomainError as error:
            if error.code != 'CLAIM_INELIGIBLE':
                raise
            reusable = False
        return manifest, {'claim': (await self._claim(connection, claim)).model_dump(mode='json'),
            'health': {**state['health'], 'reusable': reusable}, 'code_observations': observations,
            'dependency_digest': canonical_digest(manifest),
            'reuse_scope': 'current_source_request_snapshot_and_health_dependencies_not_every_context_selector'}

    async def _inspect_health(self, connection, clock, actor, binding_id, ref, snapshot, *,
        byte_start, max_bytes, representation_bytes, measure_json) -> dict:
        from .representation import stored_record_window
        if ref == 'health:quarantine':
            rows = await connection.fetch("""SELECT id,cleanup_sequence FROM am_claims WHERE binding_id=$1
                AND state='active' AND draft IS NOT NULL AND superseded_by IS NULL AND capability='agent_judged'
                AND cleanup_sequence>$2 AND (snapshot IS NULL OR snapshot IS NOT DISTINCT FROM $3)
                ORDER BY cleanup_sequence LIMIT 129""", binding_id, byte_start, snapshot)
            result = {'kind': 'health_quarantine', 'items': [], 'next_byte': None,
                'coverage': {'scope': 'live_current_snapshot_quarantine_not_context_workspace', 'complete': False}}
            last_sequence = byte_start
            for row in rows[:128]:
                try:
                    claim = await self._claim_row(connection, binding_id, row['id'], snapshot)
                except DomainError as error:
                    if error.code != 'CLAIM_INELIGIBLE':
                        raise
                    last_sequence = row['cleanup_sequence']
                    continue
                eligible = await self._health_classification_eligible(connection, binding_id, claim, snapshot)
                state = await self._health_state(connection, claim)
                reusable = True
                if eligible and state['operator_review'] != 'reject':
                    try:
                        await self._reuse_claim(connection, claim)
                    except DomainError as error:
                        if error.code != 'CLAIM_INELIGIBLE':
                            raise
                        reusable = False
                if eligible and not reusable:
                    item = {'ref': 'health:claim:' + claim['id'], 'claim_id': claim['id'],
                        'revision': claim['revision'], 'health_version': state['version']}
                    candidate = {**result, 'items': result['items'] + [item], 'next_byte': last_sequence}
                    if len(result['items']) == 32 or measure_json(candidate) > min(max_bytes, representation_bytes):
                        if not result['items']:
                            raise DomainError('HEALTH_BUNDLE_TOO_LARGE', 'A quarantine item exceeds the requested byte bound', status=413)
                        result['next_byte'] = last_sequence
                        return result
                    result['items'].append(item)
                last_sequence = row['cleanup_sequence']
            result['next_byte'] = last_sequence if len(rows) > 128 else None
            result['coverage']['complete'] = result['next_byte'] is None
            return result
        if ref == 'health':
            rows = await connection.fetch("""SELECT id,sequence,state,health_key,health_revision,health_payload FROM am_pending_judgments
                WHERE binding_id=$1 AND kind='health' AND (state IN ('pending','held') OR (state='resolved'
                    AND health_payload->'disposition'->>'decision' IN ('close_unknown','deferred_unknown'))) AND sequence>$2
                AND (snapshot IS NULL OR snapshot IS NOT DISTINCT FROM $3) ORDER BY sequence LIMIT 33""",
                binding_id, byte_start, snapshot)
            result = {'kind': 'health_pending', 'binding_id': binding_id, 'items': [], 'next_byte': None,
                'coverage': {'scope': 'live_health_work_pages', 'complete': False}}
            for row in rows:
                item = {'ref': 'health:item:' + row['id'], 'pending_id': row['id'], 'state': row['state'],
                    'health_revision': row['health_revision']}
                candidate = {**result, 'items': result['items'] + [item]}
                if len(result['items']) == 32 or measure_json(candidate) > min(max_bytes, representation_bytes):
                    if not result['items']:
                        raise DomainError('HEALTH_BUNDLE_TOO_LARGE', 'The health page header exceeds the requested byte bound', status=413)
                    result['next_byte'] = result.pop('_last_sequence')
                    return result
                result['items'].append(item)
                result['_last_sequence'] = row['sequence']
            result.pop('_last_sequence', None)
            result['coverage']['complete'] = True
            return result
        prefix, separator, identifier = ref.removeprefix('health:').partition(':')
        if not separator:
            raise _missing()
        if prefix == 'workspace':
            workspace = await connection.fetchrow('SELECT * FROM am_code_workspaces WHERE id=$1 AND binding_id=$2',
                identifier, binding_id)
            if workspace is None:
                raise _missing()
            observations = await connection.fetch("""SELECT id,relative_path,symbol_name,workspace_revision,metadata
                FROM am_code_observations WHERE workspace_id=$1 AND state='active' ORDER BY relative_path,symbol_name""", identifier)
            result = {'id': identifier, 'kind': 'health_workspace', 'state': workspace['state'], 'epoch': clock['epoch'],
                'workspace_id': identifier, 'revision': workspace['revision'], 'root_fingerprint': workspace['root_fingerprint'],
                'binding_revision': workspace['binding_revision'],
                'observations': [{'ref': item['id'], 'relative_path': item['relative_path'], 'symbol_name': item['symbol_name'],
                    'workspace_revision': item['workspace_revision'], 'metadata': _decode(item['metadata'])} for item in observations],
                'coverage': {'complete': True, 'scope': 'registered_observations_not_filesystem_catalog'}}
            if byte_start or max_bytes != 4096 or measure_json(result) > representation_bytes:
                return stored_record_window(result, byte_start, max_bytes, representation_bytes, measure_json=measure_json)
            return result
        if prefix == 'event':
            event = await connection.fetchrow('SELECT * FROM am_health_events WHERE id=$1 AND binding_id=$2', identifier, binding_id)
            if event is None:
                raise _missing()
            visible = await self._health_event_visible(connection, binding_id, event, snapshot)
            result = {'id': identifier, 'kind': 'health_event', 'state': event['state'], 'epoch': clock['epoch'],
                'event_kind': event['kind'], 'created_at': event['created_at'].isoformat(), 'payload': None, 'reason_source_ref': None}
            if visible:
                result.update(payload=_decode(event['payload']), reason_source_ref=event['reason_source_id'],
                    authority={'credential_id': event['credential_id'], 'generation': event['credential_generation'],
                        'role': event['role'], 'realm': event['realm'], 'human_presence': 'unattested'})
            if byte_start or max_bytes != 4096 or measure_json(result) > representation_bytes:
                return stored_record_window(result, byte_start, max_bytes, representation_bytes, measure_json=measure_json)
            return result
        if prefix == 'history':
            await self._claim_row(connection, binding_id, identifier, snapshot, False)
            rows = await connection.fetch("""SELECT id,kind,created_at FROM am_health_events WHERE binding_id=$1
                AND target_ref=$2 ORDER BY created_at DESC,id DESC OFFSET $3 LIMIT 9""", binding_id, identifier, byte_start)
            result = {'kind': 'health_history', 'claim_id': identifier, 'items': [],
                'next_byte': None, 'coverage': {'scope': 'live_history_pages_not_frozen_catalog', 'complete': False}}
            for row in rows[:8]:
                item = {'ref': 'health:event:' + row['id'], 'kind': row['kind'], 'created_at': row['created_at'].isoformat()}
                if measure_json({**result, 'items': result['items'] + [item]}) > min(max_bytes, representation_bytes):
                    break
                result['items'].append(item)
            more = len(rows) > len(result['items'])
            if more and not result['items']:
                raise DomainError('HEALTH_BUNDLE_TOO_LARGE', 'A history item exceeds the requested response bound', status=413)
            result['next_byte'] = byte_start + len(result['items']) if more else None
            result['coverage']['complete'] = not more
            return result
        if byte_start != 0 or max_bytes != 4096:
            raise DomainError('HEALTH_WINDOW_INVALID', 'Health work and admissions require one complete bounded response')
        if prefix == 'item':
            pending = await connection.fetchrow('''SELECT snapshot,health_payload,state,health_revision FROM am_pending_judgments
                WHERE id=$1 AND binding_id=$2 AND kind='health' AND state<>'retracted' ''', identifier, binding_id)
            if pending is None:
                raise DomainError('ADMISSION_STALE', 'This health work is no longer pending')
            if pending['snapshot'] is not None and pending['snapshot'] != snapshot:
                raise DomainError('SNAPSHOT_INELIGIBLE', 'The health work belongs to a different request snapshot')
            pending_payload = _decode(pending['health_payload'])
            disposition = pending_payload.get('disposition', {})
            if pending['state'] == 'resolved':
                if disposition.get('decision') not in {'close_unknown', 'deferred_unknown'}:
                    raise DomainError('ADMISSION_STALE', 'This bounded health work was already processed')
                return {'kind': 'health_work_disposition', 'pending_id': identifier, 'state': 'resolved',
                    'health_revision': pending['health_revision'], 'disposition': disposition['decision'],
                    'assessment_complete': False, 'admission': None,
                    'coverage': {'complete': False, 'scope': 'terminal_unknown_not_fact_assessment'}}
            if pending_payload.get('cause') == 'feedback_candidate':
                return await self._inspect_health(connection, clock, actor, binding_id,
                    'health:feedback:' + pending_payload['feedback_ref'], snapshot, byte_start=byte_start,
                    max_bytes=max_bytes, representation_bytes=representation_bytes, measure_json=measure_json)
            manifest, bundle = await self._health_work_manifest(connection, binding_id, identifier, snapshot)
            sources = tuple(RevisionRef.model_validate(item) for item in manifest['input_sources'])
            claims = tuple(RevisionRef.model_validate(item['claim']) for item in manifest['claims'])
            admission = await self._new_caller_admission(connection, clock, actor, binding_id, 'health_work',
                canonical_digest(manifest), manifest['snapshot'], sources=sources, claims=claims, health_manifest=manifest)
            result = {'kind': 'health_work', 'pending_id': identifier, 'binding_id': binding_id,
                'binding_revision': admission.binding_revision, 'health_manifest_digest': canonical_digest(manifest),
                'admission': admission.model_dump(mode='json'), 'input_sources': manifest['input_sources'],
                'input_claims': [item['claim'] for item in manifest['claims']], **bundle,
                'observed_window_closed': manifest['observed_window_closed'],
                'policy': manifest['policy'], 'coverage': manifest['coverage']}
        elif prefix == 'claim':
            claim_id, _, nominated = identifier.partition(':observation:')
            manifest, bundle = await self._claim_review_manifest(connection, binding_id, claim_id, snapshot, nominated or None)
            source_refs = await connection.fetch('SELECT source_id,source_revision FROM am_claim_sources WHERE claim_id=$1 ORDER BY source_id',
                claim_id)
            admission = await self._new_caller_admission(connection, clock, actor, binding_id, 'health_claim',
                canonical_digest(manifest), snapshot,
                claims=(RevisionRef.model_validate(manifest['claims'][0]['claim']),),
                sources=tuple(RevisionRef(id=item['source_id'], revision=item['source_revision']) for item in source_refs),
                health_manifest=manifest)
            history = await connection.fetch("""SELECT id,kind,created_at FROM am_health_events WHERE binding_id=$1
                AND target_ref=$2 ORDER BY created_at DESC,id DESC LIMIT 9""", binding_id, claim_id)
            result = {'kind': 'memory_health', **bundle, 'admission': admission.model_dump(mode='json'),
                'history': [{'ref': 'health:event:' + row['id'], 'kind': row['kind'],
                    'created_at': row['created_at'].isoformat()} for row in history[:8]],
                'history_partial': len(history) > 8,
                'history_continuation': {'ref': 'health:history:' + claim_id, 'byte_start': 8} if len(history) > 8 else None,
                'coverage': {'complete': True, 'scope': 'exact_claim_and_current_dependency_candidates'}}
        elif prefix == 'feedback':
            manifest, bundle = await self._feedback_health_manifest(connection, binding_id, identifier, snapshot)
            admission = await self._new_caller_admission(connection, clock, actor, binding_id, 'health_feedback',
                canonical_digest(manifest), snapshot, health_manifest=manifest)
            result = {'kind': 'health_feedback', 'candidate': bundle, 'admission': admission.model_dump(mode='json'),
                'coverage': {'complete': True, 'scope': 'exact_feedback_candidate_not_grounding'}}
        else:
            raise _missing()
        if measure_json(result) > representation_bytes:
            raise DomainError('HEALTH_BUNDLE_TOO_LARGE', 'The complete health admission bundle exceeds the representation bound', status=413)
        return result

    async def _health_event_visible(self, connection, binding_id, event, snapshot) -> bool:
        if event['state'] != 'active' or event['payload'] is None or event['realm'] != self.settings.realm:
            return False
        for identifier in event['claim_ids']:
            try:
                await self._claim_row(connection, binding_id, identifier, snapshot, False)
            except DomainError as error:
                if error.code not in _DISCLOSURE_ERRORS:
                    raise
                return False
        for identifier in event['source_ids']:
            row = await connection.fetchrow('''SELECT state,body IS NOT NULL AS available,snapshot FROM am_sources
                WHERE id=$1 AND binding_id=$2 AND realm=$3''', identifier, binding_id, self.settings.realm)
            if row is None or row['state'] != 'active' or not row['available'] or (row['snapshot'] is not None and row['snapshot'] != snapshot):
                return False
        if event['reason_source_id'] and event['kind'] != 'feedback_resolution':
            row = await connection.fetchrow('SELECT state,body IS NOT NULL AS available FROM am_sources WHERE id=$1',
                event['reason_source_id'])
            if row is None or row['state'] != 'active' or not row['available']:
                return False
        payload = _decode(event['payload'])
        if payload.get('snapshot') is not None and payload['snapshot'] != snapshot:
            return False
        claim_refs = list(payload.get('input_claims', []))
        if payload.get('claim_ref'):
            claim_refs.append(payload['claim_ref'])
        if payload.get('assessment', {}).get('claim_ref'):
            claim_refs.append(payload['assessment']['claim_ref'])
        for ref in claim_refs:
            row = await connection.fetchrow('SELECT revision FROM am_claims WHERE id=$1 AND binding_id=$2',
                ref['id'], binding_id)
            if row is None or row['revision'] != ref['revision']:
                return False
        for ref in payload.get('input_sources', []):
            row = await connection.fetchrow('SELECT revision FROM am_sources WHERE id=$1 AND binding_id=$2',
                ref['id'], binding_id)
            if row is None or row['revision'] != ref['revision']:
                return False
        return True

    async def _health_classification_eligible(self, connection, binding_id, claim, snapshot) -> bool:
        if (claim['capability'] != 'agent_judged' or claim['awaiting_revalidation']
                or claim['superseded_by'] is not None or claim['selection_id'] is None):
            return False
        selection = await connection.fetchrow('SELECT * FROM am_source_selections WHERE id=$1', claim['selection_id'])
        return (selection is not None and selection['policy_revision'] == selection_contract_revision()
            and await self._selection_disclosure(connection, binding_id, selection, snapshot))

    async def _current_health_stats(self, connection, binding_id: str, snapshot: str | None, *,
        code_workspace_id: str | None = None, workspace_scoped: bool = False) -> dict:
        counts = {'ordinary_claims': 0, 'reusable': 0, 'rejected': 0, 'needs_review': 0, 'unknown_after_restore': 0,
            'withheld': 0, 'unknown_assessments': 0}
        rows = connection.cursor("""SELECT id FROM am_claims WHERE binding_id=$1 AND state='active'
            AND draft IS NOT NULL AND superseded_by IS NULL AND capability='agent_judged'
            AND (snapshot IS NULL OR snapshot IS NOT DISTINCT FROM $2) ORDER BY id""",
            binding_id, snapshot, prefetch=32)
        async for row in rows:
            try:
                claim = await self._claim_row(connection, binding_id, row['id'], snapshot)
            except DomainError as error:
                if error.code != 'CLAIM_INELIGIBLE':
                    raise
                continue
            if not await self._health_classification_eligible(connection, binding_id, claim, snapshot):
                continue
            if workspace_scoped:
                try:
                    await self._require_workspace_claim(connection, claim, code_workspace_id)
                except DomainError as error:
                    if error.code != 'CLAIM_INELIGIBLE':
                        raise
                    continue
            state = await self._health_state(connection, claim)
            counts['ordinary_claims'] += 1
            counts['rejected'] += state['operator_review'] == 'reject'
            counts['needs_review'] += state['needs_review']
            counts['unknown_after_restore'] += state['restore_unknown']
            counts['unknown_assessments'] += bool(state['assessment_event_id'] is not None
                and state['operator_review'] is None and (state['support'] == 'unknown' or state['freshness'] == 'unknown'))
            try:
                await self._reuse_claim(connection, claim)
            except DomainError as error:
                if error.code != 'CLAIM_INELIGIBLE':
                    raise
                counts['withheld'] += state['operator_review'] != 'reject'
            else:
                counts['reusable'] += 1
        counts['closed_unknown_work'] = await connection.fetchval("""SELECT count(*) FROM am_pending_judgments
            WHERE binding_id=$1 AND kind='health' AND state='resolved'
            AND health_payload->'disposition'->>'decision' IN ('close_unknown','deferred_unknown')
            AND (snapshot IS NULL OR snapshot IS NOT DISTINCT FROM $2)""", binding_id, snapshot)
        return {**counts, 'enabled': (await self._health_policy(connection, binding_id))['enabled'],
            'scope': 'current_structurally_eligible_ordinary_claims',
            'accuracy_is_not_relevance': True, 'snapshot': snapshot}


    async def _apply_health_deletions(self, connection, *, scrub: bool) -> None:
        await connection.execute("""UPDATE am_code_observations o SET state='retracted'
            FROM am_code_workspaces w WHERE o.workspace_id=w.id AND w.state<>'active' AND o.state='active'""")
        await connection.execute("""UPDATE am_session_observations o SET state='retracted' WHERE o.state='active' AND (
            EXISTS(SELECT 1 FROM jsonb_array_elements(COALESCE(o.payload->'source_refs','[]')) d
                LEFT JOIN am_sources s ON s.id=d->>'id' WHERE s.id IS NULL OR s.state<>'active'
                    OR s.body IS NULL OR s.revision<>(d->>'revision')::bigint)
            OR EXISTS(SELECT 1 FROM jsonb_array_elements(COALESCE(o.payload->'claim_refs','[]')) d
                LEFT JOIN am_claims c ON c.id=d->>'id' WHERE c.id IS NULL OR c.state<>'active' OR c.draft IS NULL OR c.revision<>(d->>'revision')::bigint)
            OR EXISTS(SELECT 1 FROM am_sources s JOIN am_operations p ON p.id=s.operation_id
                WHERE s.binding_id=o.binding_id AND p.credential_id=o.credential_id
                AND s.producer_generation=o.credential_generation AND o.payload->'origin_keys' ? s.origin_key
                AND (s.state<>'active' OR s.body IS NULL)))""")
        await connection.execute("""UPDATE am_pending_judgments p SET state='retracted' WHERE p.kind='health'
            AND p.state<>'retracted' AND (
                EXISTS(SELECT 1 FROM unnest(p.source_ids) d(id) LEFT JOIN am_sources s ON s.id=d.id
                    WHERE s.id IS NULL OR s.state<>'active' OR s.body IS NULL)
                OR EXISTS(SELECT 1 FROM unnest(p.claim_ids) d(id) LEFT JOIN am_claims c ON c.id=d.id
                    WHERE c.id IS NULL OR c.state<>'active' OR c.draft IS NULL)
                OR
                EXISTS(SELECT 1 FROM am_feedback f WHERE p.health_payload->>'feedback_ref'=f.id
                    AND f.state='retracted' AND f.source_id IN (SELECT id FROM am_sources WHERE state='purged'))
                OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(
                    COALESCE(p.health_payload->'session_observation_ids','[]')) d
                    JOIN am_session_observations o ON o.id=d.value WHERE o.state='retracted'))""")
        await connection.execute("""UPDATE am_health_events e SET state='retracted' WHERE e.state='active' AND (
            EXISTS(SELECT 1 FROM am_sources s WHERE s.id=ANY(e.source_ids) AND (s.state<>'active' OR s.body IS NULL))
            OR EXISTS(SELECT 1 FROM am_claims c WHERE c.id=ANY(e.claim_ids) AND (c.state<>'active' OR c.draft IS NULL))
            OR (e.kind<>'feedback_resolution' AND EXISTS(SELECT 1 FROM am_sources s
                WHERE s.id=e.reason_source_id AND (s.state<>'active' OR s.body IS NULL)))
            OR (e.kind<>'feedback_resolution' AND EXISTS(SELECT 1 FROM am_feedback f WHERE f.id=e.target_ref AND f.state='retracted'))
            OR EXISTS(SELECT 1 FROM am_pending_judgments p WHERE p.id=e.target_ref AND p.state='retracted'))""")
        await connection.execute("""UPDATE am_health_events e SET state='retracted'
            FROM am_health_events parent WHERE e.state='active' AND e.kind='health_assessment'
            AND e.payload->>'assessment_event_id'=parent.id AND parent.state<>'active'""")
        await connection.execute("""UPDATE am_claim_health h SET version=version+1,needs_review=true,
            support='unknown',freshness=CASE WHEN h.freshness='stale' THEN 'stale' ELSE 'unknown' END,
            operator_review=CASE WHEN r.invalid AND h.operator_review='accept' THEN NULL ELSE h.operator_review END,
            review_event_id=CASE WHEN r.invalid THEN NULL ELSE h.review_event_id END,
            assessment_event_id=CASE WHEN a.invalid THEN NULL ELSE h.assessment_event_id END
            FROM (SELECT claim_id,review_event_id IS NOT NULL AND NOT EXISTS(
                SELECT 1 FROM am_health_events e WHERE e.id=p.review_event_id AND e.state='active') AS invalid
                FROM am_claim_health p) r,
                (SELECT claim_id,assessment_event_id IS NOT NULL AND NOT EXISTS(
                SELECT 1 FROM am_health_events e WHERE e.id=p.assessment_event_id AND e.state='active') AS invalid
                FROM am_claim_health p) a
            WHERE r.claim_id=h.claim_id AND a.claim_id=h.claim_id AND (r.invalid OR a.invalid)""")
        await connection.execute("""UPDATE am_operations o SET state='retracted',error_code='SOURCE_RETRACTED'
            WHERE o.state<>'retracted' AND (
                EXISTS(SELECT 1 FROM am_health_events e WHERE e.id=o.artifact_id AND e.state='retracted')
                OR EXISTS(SELECT 1 FROM am_session_observations s WHERE s.id=o.artifact_id AND s.state='retracted')
                OR EXISTS(SELECT 1 FROM am_code_observations c WHERE c.id=o.artifact_id AND c.state='retracted')
                OR EXISTS(SELECT 1 FROM am_code_workspaces w WHERE w.id=o.artifact_id AND w.state='retracted'))""")
        if not scrub:
            return
        await connection.execute("UPDATE am_health_events SET payload=NULL WHERE state='retracted' AND payload IS NOT NULL")
        await connection.execute("UPDATE am_session_observations SET payload=NULL WHERE state='retracted' AND payload IS NOT NULL")
        await connection.execute("UPDATE am_code_observations SET metadata=NULL WHERE state='retracted' AND metadata IS NOT NULL")
        await connection.execute("""UPDATE am_pending_judgments SET health_payload='{}',reason=NULL
            WHERE kind='health' AND state='retracted'""")
        await connection.execute("""DELETE FROM am_code_links l USING am_claims c WHERE c.id=l.claim_id
            AND c.state='retracted' AND c.draft IS NULL""")

