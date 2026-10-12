from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import struct
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl, unquote, urlsplit

from .config import Settings
from .domain import DomainError, EffectState, Principal, Role
from .journal import DeletionJournal
from .migrations import MIGRATION, MIGRATIONS, migrate, restore_preparation_sql
from .private_io import private_write, sync_file
from .store import Store

# This is a framing format, not an encryption format. The entire envelope is
# authenticated/encrypted by the installed age implementation, including EOF.
_MAGIC = b"agent-memory-pg-age-envelope\x00\x01"
_CHUNK = 65536
_HEAD = re.compile(r"[a-f0-9]{64}")
_SCHEMA = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_TABLES = frozenset({
    "alembic_version", "am_clock", "am_credentials", "am_bindings", "am_grants",
    "am_receipts", "am_operations", "am_sources", "am_floors", "am_claims",
    "am_claim_sources", "am_spans", "am_entities", "am_relations",
    "am_relation_sources", "am_relation_claims", "am_reflections", "am_reflection_sources",
    "am_reflection_claims", "am_proposals", "am_proposal_sources", "am_rules",
    "am_rule_targets", "am_feedback", "am_routes", "am_jobs", "am_admissions",
    "am_origin_reservations",
})
_LEGACY_FIELDS = frozenset({"format", "deployment_id", "realm", "schema", "owner_id",
    "backup_head", "postgres_version", "vector_version", "migration_version", "created_at"})
_FIELDS = _LEGACY_FIELDS | {"migration_versions"}
_PRIOR_TABLES = _TABLES - {"am_origin_reservations"}
_LEGACY_TABLES = _PRIOR_TABLES - {"am_relation_claims"}


@dataclass(frozen=True)
class BackupRuntime:
    """Explicit local binaries/owned Docker endpoint; no discovery or fallback.

    Local PG binary paths must be absolute. Docker PG binary names are the
    installed pg_dump/pg_restore/psql inside the explicitly selected own container.
    docker_config is the directory containing a private config.json, not the
    config.json path. docker_host must be a local unix:// socket.
    """

    age_binary: Path
    mode: Literal["local", "docker"] = "local"
    pg_dump_binary: Path | str = "pg_dump"
    pg_restore_binary: Path | str = "pg_restore"
    psql_binary: Path | str = "psql"
    docker_binary: Path | None = None
    docker_config: Path | None = None
    docker_host: str | None = None
    docker_container: str | None = None
    docker_pg_host: str = "/var/run/postgresql"
    docker_pg_port: int = 5432
    postgres_version: str = "18.6"
    vector_version: str = "0.8.7"
    migration_version: str = MIGRATION
    timeout_seconds: float = 3600
    max_archive_bytes: int = 64 * 1024**3


def _error(code: str, message: str, *, started: bool = False) -> DomainError:
    return DomainError(code, message, effect=EffectState.UNKNOWN if started else EffectState.NOT_STARTED)


def _private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise _error("PATH_DENIED", "Operations require an owned private directory")


def _file(path: Path, *, private: bool = True, maximum: int | None = None) -> int:
    """Open without following links and validate the object, not a prior stat."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or (private and info.st_mode & 0o077)
                or (maximum is not None and info.st_size > maximum)):
            os.close(descriptor)
            raise _error("PATH_DENIED", "The operations input is not an owned permitted local file")
        return descriptor
    except OSError:
        raise _error("PATH_DENIED", "The operations input is unavailable") from None


def _read_private(path: Path, maximum: int = 65536, *, private: bool = True) -> bytes:
    descriptor = _file(path, private=private, maximum=maximum)
    with os.fdopen(descriptor, "rb") as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise _error("PATH_DENIED", "The operations input exceeds its bound")
    return raw


def _token(path: Path) -> str:
    try:
        token = _read_private(path, 4097).decode("utf-8").strip()
        if not 32 <= len(token.encode()) <= 4096:
            raise ValueError
        return token
    except (UnicodeError, ValueError):
        raise _error("TOKEN_INVALID", "The private operator credential is invalid") from None


def _destination(settings: Settings, path: Path) -> Path:
    path = Path(path)
    if not path.is_absolute() or any(part == ".." for part in path.parts):
        raise _error("PATH_DENIED", "An absolute local output path is required")
    # Refuse symlinked ancestors as well as the final entry. This is a G0 owned
    # path convention, not protection against an unrestricted same-UID process.
    for parent in (*path.parents, path):
        if parent.is_symlink():
            raise _error("PATH_DENIED", "An operations output cannot traverse a symlink")
    journal = settings.journal_dir.resolve()
    if path.is_relative_to(journal) or journal.is_relative_to(path):
        raise _error("PATH_DENIED", "Operations cannot replace the independent deletion journal")
    if path in {settings.state_dir / "authority.lock", settings.state_dir / "restore-barrier.json"}:
        raise _error("PATH_DENIED", "Operations cannot replace authority interlock files")
    if path.exists():
        raise _error("OUTPUT_EXISTS", "Operations never overwrite an existing output")
    _private_directory(path.parent)
    return path


@contextmanager
def authority_lock(settings: Settings, exclusive: bool = False) -> Iterator[None]:
    """Nonblocking process-local authority interlock for all supported paths.

    Serve holds a shared lock for its *whole* lifespan, including worker drain.
    CLI authority commands hold shared locks; restore and migration hold exclusive.
    Do not wrap backup/restore/migration in another lock. This cannot fence arbitrary
    SQL clients or other software that deliberately ignores the package contract.
    """
    _private_directory(settings.state_dir)
    descriptor = os.open(settings.state_dir / "authority.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise _error("PATH_DENIED", "The authority lock is not a private owned file")
        try:
            fcntl.flock(descriptor, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError:
            raise _error("AUTHORITY_BUSY", "Stop and drain the local service and authority commands before restore or migration") from None
        marker = settings.state_dir / "restore-barrier.json"
        if not exclusive and (marker.exists() or marker.is_symlink()):
            raise _error("RESTORE_RECOVERY_REQUIRED", "An interrupted restore must be recovered before authority use")
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _dsn(dsn: str) -> tuple[str, dict[str, str]]:
    parts = urlsplit(dsn)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    schema = query.pop("schema", "public")
    if parts.scheme not in {"postgres", "postgresql"} or parts.fragment or query or not _SCHEMA.fullmatch(schema):
        raise _error("CONFIG_INVALID", "Operations require a local PostgreSQL URL with only the schema option")
    host = unquote(parts.hostname or "")
    if not host:
        raise _error("CONFIG_INVALID", "Operations require an explicit local database endpoint")
    if "," in host or (host not in {"127.0.0.1", "::1"} and not host.startswith("/")):
        raise _error("EGRESS_DENIED", "Database operations require a local PostgreSQL endpoint")
    try:
        values = {
            "PGHOST": host, "PGPORT": str(parts.port or 5432),
            "PGDATABASE": unquote(parts.path.lstrip("/")),
            "PGUSER": unquote(parts.username or ""), "PGPASSWORD": unquote(parts.password or ""),
        }
    except ValueError:
        raise _error("CONFIG_INVALID", "The local database address is invalid") from None
    if not values["PGDATABASE"] or not values["PGUSER"] or any("\n" in v or "\r" in v or "\x00" in v for v in values.values()):
        raise _error("CONFIG_INVALID", "Explicit local database/user values without control characters are required")
    return schema, values


def _binary(path: Path | str) -> str:
    value = Path(path)
    if not value.is_absolute() or not value.is_file() or not os.access(value, os.X_OK):
        raise _error("BINARY_REQUIRED", "An explicit installed local operations binary is required")
    return str(value)


def _runtime(runtime: BackupRuntime) -> None:
    _binary(runtime.age_binary)
    if (runtime.mode not in {"local", "docker"} or runtime.postgres_version != "18.6"
            or runtime.vector_version != "0.8.7" or runtime.migration_version != MIGRATION
            or runtime.timeout_seconds <= 0 or runtime.max_archive_bytes < _CHUNK):
        raise _error("RUNTIME_INVALID", "The operations runtime must match the supported migration and database pins")
    if runtime.mode == "local":
        _binary(runtime.pg_dump_binary)
        _binary(runtime.pg_restore_binary)
        _binary(runtime.psql_binary)
        return
    if runtime.docker_binary is None or runtime.docker_config is None:
        raise _error("RUNTIME_INVALID", "An explicit private Docker client configuration is required")
    _binary(runtime.docker_binary)
    _read_private(runtime.docker_config / "config.json")
    host = urlsplit(runtime.docker_host or "")
    if host.scheme != "unix" or host.netloc or host.query or host.fragment or not host.path.startswith("/"):
        raise _error("EGRESS_DENIED", "Docker operations require an explicit local Unix socket")
    try:
        socket_info = Path(host.path).stat()
        if not stat.S_ISSOCK(socket_info.st_mode) or socket_info.st_uid != os.getuid():
            raise ValueError
    except (OSError, ValueError):
        raise _error("RUNTIME_INVALID", "The owned local Docker socket is unavailable") from None
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", runtime.docker_container or "")
            or str(runtime.pg_dump_binary) != "pg_dump" or str(runtime.pg_restore_binary) != "pg_restore"
            or str(runtime.psql_binary) != "psql"
            or not 1 <= runtime.docker_pg_port <= 65535
            or (runtime.docker_pg_host not in {"127.0.0.1", "::1"} and not runtime.docker_pg_host.startswith("/"))
            or any(c in runtime.docker_pg_host for c in ",\r\n\x00")):
        raise _error("RUNTIME_INVALID", "The explicit owned Docker PostgreSQL runtime is invalid")


def _environment() -> dict[str, str]:
    # Do not inherit PG*, proxy, AGE/plugin, Docker contexts, or tracing settings.
    return {"PATH": os.defpath, "LANG": "C", "LC_ALL": "C", "PGPASSFILE": "/dev/null"}


class _Processes:
    def __init__(self) -> None:
        self.children: list[asyncio.subprocess.Process] = []

    async def start(self, argv: list[str], *, env: dict[str, str] | None = None, stdout=asyncio.subprocess.PIPE) -> asyncio.subprocess.Process:
        process = await asyncio.create_subprocess_exec(*argv, stdin=asyncio.subprocess.PIPE,
            stdout=stdout, stderr=asyncio.subprocess.DEVNULL, env=env or _environment(), limit=_CHUNK * 2)
        self.children.append(process)
        return process

    async def close(self) -> None:
        for process in self.children:
            process.stdin.close()
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
        async def drain(process: asyncio.subprocess.Process) -> None:
            if process.stdout is not None:
                while await process.stdout.read(_CHUNK):
                    pass
            await process.wait()
        # wait() alone can hang on a killed child with a paused unread PIPE.
        await asyncio.gather(*(drain(process) for process in self.children))


@asynccontextmanager
async def _processes() -> AsyncIterator[_Processes]:
    processes = _Processes()
    try:
        yield processes
    finally:
        await processes.close()


async def _close_stores(*stores: Store | None, started: bool) -> None:
    results = await asyncio.gather(*(store.close() for store in stores if store is not None), return_exceptions=True)
    if any(isinstance(result, BaseException) for result in results):
        raise _error("OPERATIONS_CLOSE_FAILED", "The local authority connection cleanup failed; reconcile the operation state", started=started)


async def _write(process: asyncio.subprocess.Process, raw: bytes) -> None:
    process.stdin.write(raw)
    await process.stdin.drain()


async def _finish(process: asyncio.subprocess.Process) -> None:
    process.stdin.close()
    if await process.wait() != 0:
        raise _error("OPERATIONS_BINARY_FAILED", "A local operations binary failed; no raw diagnostic is retained")


async def _bounded_output(reader: asyncio.StreamReader, maximum: int) -> bytes:
    raw = bytearray()
    while chunk := await reader.read(min(_CHUNK, maximum + 1 - len(raw))):
        raw.extend(chunk)
        if len(raw) > maximum:
            raise _error("OPERATIONS_OUTPUT_TOO_LARGE", "The local operations metadata exceeds its bound")
    return bytes(raw)


async def _pg(processes: _Processes, runtime: BackupRuntime, kind: str, dsn: str, args: list[str], *, stdout=asyncio.subprocess.PIPE) -> asyncio.subprocess.Process:
    _, values = _dsn(dsn)
    values["PGAPPNAME"] = "agent-memory-ops-" + ("restore" if kind == "psql" else kind)
    binary = {"dump": runtime.pg_dump_binary, "restore": runtime.pg_restore_binary,
        "psql": runtime.psql_binary}[kind]
    if runtime.mode == "local":
        env = _environment() | values | {"PGCONNECT_TIMEOUT": "15"}
        return await processes.start([_binary(binary), *args], env=env, stdout=stdout)
    # Password and connection values are pipe data, never docker -e argv.
    # The fixed shell consumes six lines before invoking the selected tool.
    values["PGHOST"] = runtime.docker_pg_host
    values["PGPORT"] = str(runtime.docker_pg_port)
    script = "IFS= read -r PGHOST && IFS= read -r PGPORT && IFS= read -r PGDATABASE && IFS= read -r PGUSER && IFS= read -r PGPASSWORD && IFS= read -r PGAPPNAME && unset PGSERVICE PGSERVICEFILE PGOPTIONS && export PGHOST PGPORT PGDATABASE PGUSER PGPASSWORD PGAPPNAME && export PGCONNECT_TIMEOUT=15 PGPASSFILE=/dev/null && "
    if kind == "psql" and "--file=-" in args:
        guard = _docker_guard(dsn)
        # Reservation is acknowledged before launching this executor. No EXIT
        # trap: a killed wrapper must leave its guard, not claim its child exited.
        script += f'test -d "{guard}" || exit 79; "$@"; status=$?; rmdir "{guard}" || exit 79; exit "$status"'
    else:
        script += 'exec "$@"'
    process = await processes.start([str(runtime.docker_binary), "--config", str(runtime.docker_config),
        "--host", str(runtime.docker_host), "exec", "-i", str(runtime.docker_container),
        "sh", "-c", script, "memory-pg", str(binary), *args], stdout=stdout)
    await _write(process, ("\n".join(values[k] for k in ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD", "PGAPPNAME")) + "\n").encode())
    return process


async def _versions(processes: _Processes, runtime: BackupRuntime, dsn: str) -> None:
    for kind, name in (("dump", b"pg_dump"), ("restore", b"pg_restore"), ("psql", b"psql")):
        process = await _pg(processes, runtime, kind, dsn, ["--version"])
        process.stdin.close()
        raw = await _bounded_output(process.stdout, 1024)
        if await process.wait() != 0 or not re.match(
                re.escape(name) + rb" \(PostgreSQL\) " + re.escape(runtime.postgres_version.encode()) + rb"(?:\s|$)", raw):
            raise _error("DATABASE_VERSION_UNSUPPORTED", "The selected PostgreSQL tools do not match the pinned version")


async def _restore_transaction(processes: _Processes, runtime: BackupRuntime,
        dsn: str, metadata: dict, decrypt: asyncio.subprocess.Process, checked: dict) -> dict:
    """Boundedly stream archive SQL; only authenticated successful EOF can commit.

    Explicit BEGIN/COMMIT is intentional: psql --single-transaction would commit
    on stdin EOF even when the upstream pg_restore/age process failed. Closing or
    killing this session before the final COMMIT instead rolls all DDL/data back.
    """
    executor = await _pg(processes, runtime, "psql", dsn,
        ["--no-psqlrc", "--set=ON_ERROR_STOP=1", "--file=-"],
        stdout=asyncio.subprocess.DEVNULL)
    await _write(executor, ("BEGIN;\n" + restore_preparation_sql(
        metadata["migration_version"], metadata["schema"])).encode())
    producer = await _pg(processes, runtime, "restore", dsn,
        ["--file=-", "--clean", "--if-exists", "--exit-on-error",
         "--no-owner", "--no-privileges", "--schema=" + metadata["schema"]])

    async def feed_archive() -> dict:
        restored = await _read_frames(decrypt.stdout,
            lambda raw: _write(producer, raw), runtime.max_archive_bytes)
        producer.stdin.close()
        if await decrypt.wait() != 0 or restored != checked:
            raise _error("ARCHIVE_INVALID", "The encrypted restore stream failed validation")
        return restored

    async def forward_sql() -> None:
        while raw := await producer.stdout.read(_CHUNK):
            await _write(executor, raw)
        if await producer.wait() != 0:
            raise _error("OPERATIONS_BINARY_FAILED", "The local restore SQL producer failed; no raw diagnostic is retained")

    tasks = [asyncio.create_task(feed_archive()), asyncio.create_task(forward_sql())]
    try:
        restored, _ = await asyncio.gather(*tasks)
        await _write(executor, b"\nCOMMIT;\n")
        await _finish(executor)
        return restored
    finally:
        for pending in tasks:
            if not pending.done():
                pending.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def _docker_guard(dsn: str) -> str:
    schema, values = _dsn(dsn)
    digest = hashlib.sha256((values["PGDATABASE"] + "\0" + schema).encode()).hexdigest()
    return "/tmp/agent-memory-mcp-restore-" + digest


async def _docker_control(processes: _Processes, runtime: BackupRuntime, dsn: str, *, reserve: bool = False) -> None:
    if runtime.mode != "docker":
        return
    script = 'umask 077; mkdir "$1"' if reserve else 'test ! -e "$1"'
    process = await processes.start([str(runtime.docker_binary), "--config", str(runtime.docker_config),
        "--host", str(runtime.docker_host), "exec", str(runtime.docker_container),
        "sh", "-c", script, "memory-restore-interlock", _docker_guard(dsn)],
        stdout=asyncio.subprocess.DEVNULL)
    process.stdin.close()
    if await process.wait() != 0:
        raise _error("RESTORE_EXECUTOR_UNOBSERVED", "The owned Docker restore executor has not been observed exited; inspect and stop it before private recovery")


async def _require_restore_idle(store: Store) -> None:
    async with store.pool.acquire() as connection:
        active = await connection.fetchval("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND application_name='agent-memory-ops-restore')")
    if active:
        raise _error("RESTORE_EXECUTOR_UNOBSERVED", "An earlier restore database session is still active; wait for observed exit before recovery")


async def _require_application_defaults(settings: Settings, connection) -> None:
    schema, application = _dsn(settings.database_dsn)
    _, migrator = _dsn(settings.migrator_dsn)
    if application["PGUSER"] == migrator["PGUSER"]:
        return
    # Infrastructure ACLs are not archive authority. Never silently reinstall
    # old archived grants or invent new grants after replacing the tables.
    usage = await connection.fetchval("SELECT has_schema_privilege($1::name,$2::text,'USAGE')", application["PGUSER"], schema)
    rows = await connection.fetch("""
        SELECT a.privilege_type FROM pg_default_acl d
        LEFT JOIN pg_namespace n ON n.oid=d.defaclnamespace
        CROSS JOIN LATERAL aclexplode(d.defaclacl) a
        JOIN pg_roles owner_role ON owner_role.oid=d.defaclrole
        JOIN pg_roles app_role ON app_role.oid=a.grantee
        WHERE d.defaclobjtype='r' AND owner_role.rolname=$1 AND app_role.rolname=$2
          AND (d.defaclnamespace=0 OR n.nspname=$3)
    """, migrator["PGUSER"], application["PGUSER"], schema)
    required = {"SELECT", "INSERT", "UPDATE", "DELETE"}
    if not usage or not required.issubset({row["privilege_type"] for row in rows}):
        raise _error("APPLICATION_DEFAULT_PRIVILEGES_REQUIRED",
            "Before restore or migration, the private migrator must have default table grants to the distinct application role, and that role must have schema USAGE")


def _key_material(path: Path, *, identity: bool) -> bytes:
    raw = _read_private(path, private=identity)
    try:
        lines = [line.strip() for line in raw.decode("ascii").splitlines() if line.strip() and not line.lstrip().startswith("#")]
        pattern = r"AGE-SECRET-KEY-1[0-9A-Z]+" if identity else r"age1[0-9a-z]+"
        if not lines or len(lines) > 64 or any(not re.fullmatch(pattern, line) for line in lines):
            raise ValueError
    except (UnicodeError, ValueError):
        raise _error("AGE_KEY_INVALID", "Only native local age identities/recipients are supported; plugins and remote key sources are unavailable") from None
    return ("\n".join(lines) + "\n").encode()


async def _metadata(store: Store, connection, runtime: BackupRuntime, owner: Principal) -> dict:
    # Operational metadata only. All authority mutation/recovery remains Store's.
    version = int(await connection.fetchval("SHOW server_version_num"))
    vector = await connection.fetchval("SELECT extversion FROM pg_extension WHERE extname='vector'")
    migration = await connection.fetchval("SELECT version_num FROM alembic_version")
    clock = await connection.fetchrow("SELECT deployment_id,realm,journal_head FROM am_clock WHERE singleton")
    schema, _ = _dsn(store.settings.database_dsn)
    if (version != 180006 or vector != runtime.vector_version or migration != runtime.migration_version):
        raise _error("DATABASE_VERSION_UNSUPPORTED", "The live database does not match the operations pins")
    if clock is None or clock["deployment_id"] != store.settings.deployment_id or clock["realm"] != store.settings.realm:
        raise _error("SCOPE_DENIED", "The live authority does not match the selected deployment and realm")
    return {"format": 2, "deployment_id": store.settings.deployment_id, "realm": store.settings.realm,
        "schema": schema, "owner_id": owner.id, "backup_head": clock["journal_head"],
        "postgres_version": runtime.postgres_version, "vector_version": vector,
        "migration_version": migration, "migration_versions": list(MIGRATIONS),
        "created_at": datetime.now(UTC).isoformat()}


def _validate_metadata(metadata: dict, settings: Settings, runtime: BackupRuntime, owner_id: str) -> None:
    schema, _ = _dsn(settings.database_dsn)
    if (not isinstance(metadata, dict) or type(metadata.get("format")) is not int
            or metadata["format"] not in {1, 2}
            or set(metadata) != (_LEGACY_FIELDS if metadata["format"] == 1 else _FIELDS)
            or any(not isinstance(metadata[k], str) for k in _LEGACY_FIELDS - {"format"})
            or not _HEAD.fullmatch(metadata["backup_head"])):
        raise _error("ARCHIVE_INVALID", "The encrypted backup metadata is invalid")
    if metadata["format"] == 1:
        if metadata["migration_version"] != MIGRATIONS[0]:
            raise _error("RESTORE_SCOPE_DENIED", "The legacy archive has an unsupported authority revision")
    else:
        archived_version = metadata["migration_version"]
        if (archived_version not in MIGRATIONS
                or metadata["migration_versions"] != list(MIGRATIONS[:MIGRATIONS.index(archived_version) + 1])):
            raise _error("RESTORE_SCOPE_DENIED", "The archive has an unsupported ordered authority migration manifest")
    expected = {"deployment_id": settings.deployment_id, "realm": settings.realm, "schema": schema,
        "owner_id": owner_id, "postgres_version": runtime.postgres_version,
        "vector_version": runtime.vector_version}
    if any(metadata[k] != value for k, value in expected.items()):
        raise _error("RESTORE_SCOPE_DENIED", "The authenticated archive does not match the selected deployment, realm, owner, schema and pins")


async def _read_header(reader: asyncio.StreamReader) -> dict:
    if await reader.readexactly(len(_MAGIC)) != _MAGIC:
        raise _error("ARCHIVE_INVALID", "The encrypted backup envelope is invalid")
    length = struct.unpack("!I", await reader.readexactly(4))[0]
    if not 1 <= length <= 8192:
        raise _error("ARCHIVE_INVALID", "The encrypted backup metadata exceeds its bound")
    try:
        metadata = json.loads(await reader.readexactly(length))
    except (ValueError, UnicodeError):
        raise _error("ARCHIVE_INVALID", "The encrypted backup metadata is invalid") from None
    if not isinstance(metadata, dict):
        raise _error("ARCHIVE_INVALID", "The encrypted backup metadata is invalid")
    return metadata


async def _read_frames(reader: asyncio.StreamReader, sink: Callable[[bytes], Awaitable[None]], maximum: int) -> dict:
    digest = hashlib.sha256()
    size = 0
    prefix = bytearray()
    while True:
        length = struct.unpack("!I", await reader.readexactly(4))[0]
        if length == 0:
            break
        if length > _CHUNK or size + length > maximum:
            raise _error("ARCHIVE_INVALID", "The backup dump framing exceeds its bound")
        raw = await reader.readexactly(length)
        prefix.extend(raw[:max(0, 5 - len(prefix))])
        size += length
        digest.update(raw)
        await sink(raw)
    if bytes(prefix) != b"PGDMP" or await reader.readexactly(32) != digest.digest() or await reader.read(1):
        raise _error("ARCHIVE_INVALID", "The encrypted dump is incomplete or corrupt")
    return {"dump_sha256": digest.hexdigest(), "dump_bytes": size}


def _validate_toc(raw: bytes, schema: str, tables: frozenset[str] = _TABLES) -> None:
    """Reject other schemas/objects before any destructive connection is made."""
    found_tables: set[str] = set()
    data: set[str] = set()
    try:
        for line in raw.decode("utf-8").splitlines():
            if not line or line.startswith(";"):
                continue
            match = re.fullmatch(r"\d+; \d+ \d+ (TABLE DATA|FK CONSTRAINT|CHECK CONSTRAINT|CONSTRAINT|TABLE|INDEX) (\S+) (.+)", line)
            if match is None or match[2] != schema:
                raise ValueError
            kind, _, tail = match.groups()
            name = tail.split()[0]
            if kind == "INDEX":
                if not (re.fullmatch(r"am_[a-z0-9_]+", name) or name == "alembic_version_pkc"):
                    raise ValueError
            elif name not in tables:
                raise ValueError
            if kind == "TABLE":
                found_tables.add(name)
            if kind == "TABLE DATA":
                data.add(name)
        if found_tables != tables or data != tables:
            raise ValueError
    except (UnicodeError, ValueError, IndexError):
        raise _error("ARCHIVE_SCOPE_DENIED", "The dump contains unsupported objects or an incomplete authority schema") from None


async def _decrypt(processes: _Processes, runtime: BackupRuntime, archive: Path, identity: bytes) -> asyncio.subprocess.Process:
    process = await processes.start([_binary(runtime.age_binary), "--decrypt", "--identity", "-", str(archive)])
    await _write(process, identity)
    process.stdin.close()
    return process


async def _preflight(processes: _Processes, runtime: BackupRuntime, settings: Settings, archive: Path,
        identity: bytes, owner_id: str, *, listing: bool) -> tuple[dict, dict]:
    decrypt = await _decrypt(processes, runtime, archive, identity)
    metadata = await _read_header(decrypt.stdout)
    _validate_metadata(metadata, settings, runtime, owner_id)
    # --file=- traverses/decompresses all data without any database connection.
    # --list separately constrains the TOC, since list alone doesn't validate data.
    process = await _pg(processes, runtime, "restore", settings.migrator_dsn,
        ["--list"] if listing else ["--file=-", "--no-owner", "--no-privileges"],
        stdout=asyncio.subprocess.PIPE if listing else asyncio.subprocess.DEVNULL)
    task = asyncio.create_task(_bounded_output(process.stdout, 262144)) if listing else None
    async def feed(raw: bytes) -> None:
        try:
            await _write(process, raw)
        except (BrokenPipeError, ConnectionResetError):
            # --list exits after reading the catalog, without consuming table
            # data. Still authenticate/drain the complete age envelope below.
            if not listing:
                raise
    async def validate_stream() -> dict:
        result = await _read_frames(decrypt.stdout, feed, runtime.max_archive_bytes)
        await _finish(process)
        if await decrypt.wait() != 0:
            raise _error("ARCHIVE_INVALID", "The age archive is incomplete, corrupt, or cannot be decrypted")
        return result

    validation = asyncio.create_task(validate_stream())
    try:
        if task is None:
            result = await validation
        else:
            result, toc = await asyncio.gather(validation, task)
            revision = metadata["migration_version"]
            tables = _LEGACY_TABLES if revision == MIGRATIONS[0] else (
                _PRIOR_TABLES if revision == MIGRATIONS[1] else _TABLES
            )
            _validate_toc(toc, metadata["schema"], tables)
        return metadata, result
    finally:
        tasks = [validation] + ([task] if task is not None else [])
        for pending in tasks:
            if not pending.done():
                pending.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@asynccontextmanager
async def _staging(settings: Settings) -> AsyncIterator[Path]:
    _private_directory(settings.state_dir)
    directory = Path(tempfile.mkdtemp(prefix=".encrypted-ops-", dir=settings.state_dir))
    try:
        yield directory
    finally:
        # Only encrypted archives and public recipients are staged; identities
        # reach age through stdin and never create a durable staging copy.
        for item in directory.iterdir():
            item.unlink()
        directory.rmdir()


def _publish(source: Path, destination: Path) -> None:
    # Same-directory encrypted staging enables atomic, no-clobber publication.
    with source.open("rb") as stream:
        sync_file(stream.fileno())
    os.link(source, destination, follow_symlinks=False)
    source.unlink()
    descriptor = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


async def _copy_encrypted(source: Path, target: Path, maximum: int) -> dict:
    descriptor = _file(source, maximum=maximum)
    digest = hashlib.sha256()
    size = 0
    try:
        private_write(target, b"")
        with os.fdopen(descriptor, "rb") as incoming, target.open("ab") as outgoing:
            descriptor = -1
            while raw := incoming.read(_CHUNK):
                size += len(raw)
                if size > maximum:
                    raise _error("ARCHIVE_INVALID", "The encrypted archive exceeds its bound")
                digest.update(raw)
                outgoing.write(raw)
                await asyncio.sleep(0)
            outgoing.flush()
            sync_file(outgoing.fileno())
    finally:
        if descriptor != -1:
            os.close(descriptor)
    return {"archive_sha256": digest.hexdigest(), "archive_bytes": size}


def _receipt(metadata: dict, dump: dict) -> dict:
    return {"deployment_id": metadata["deployment_id"], "realm": metadata["realm"],
        "schema": metadata["schema"], "backup_head": metadata["backup_head"],
        "backup_head_is_latest_witness": False, "postgres_version": metadata["postgres_version"],
        "vector_version": metadata["vector_version"], "migration_version": metadata["migration_version"],
        "migration_versions": metadata.get("migration_versions", [MIGRATIONS[0]]), **dump}


async def backup(settings: Settings, operator_token_file: Path, destination: Path,
        recipients_file: Path, runtime: BackupRuntime) -> dict:
    """Stream one consistent selected-authority pg_dump directly through age."""
    store = Store(settings, DeletionJournal(settings.journal_dir, settings.deployment_id))
    temporary: Path | None = None
    publishing = False
    try:
        with authority_lock(settings):
            async with asyncio.timeout(runtime.timeout_seconds), _processes() as processes, _staging(settings) as staging:
                _runtime(runtime)
                schema, _ = _dsn(settings.database_dsn)
                destination = _destination(settings, destination)
                private_write(staging / "recipients", _key_material(recipients_file, identity=False))
                token = _token(operator_token_file)
                await store.open()
                actor = await store.authenticate(token, (Role.OPERATOR,))
                await store.reconcile_journal()
                await _versions(processes, runtime, settings.database_dsn)
                temporary = destination.parent / (".memory-encrypted-" + secrets.token_hex(16))
                private_write(temporary, b"")
                with temporary.open("wb") as output:
                    encrypt = await processes.start([_binary(runtime.age_binary), "--encrypt", "--recipients-file", str(staging / "recipients")], stdout=output)
                    async with store.pool.acquire() as connection:
                        async with connection.transaction(isolation="repeatable_read", readonly=True):
                            metadata = await _metadata(store, connection, runtime, actor)
                            _validate_metadata(metadata, settings, runtime, actor.id)
                            snapshot = await connection.fetchval("SELECT pg_export_snapshot()")
                            args = ["--format=custom", "--no-owner", "--no-privileges", "--strict-names", "--snapshot=" + snapshot]
                            args.extend('--table="' + schema + '"."' + name + '"' for name in sorted(_TABLES))
                            dump = await _pg(processes, runtime, "dump", settings.database_dsn, args)
                            dump.stdin.close()
                            header = json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode()
                            await _write(encrypt, _MAGIC + struct.pack("!I", len(header)) + header)
                            digest = hashlib.sha256()
                            size = 0
                            while raw := await dump.stdout.read(_CHUNK):
                                size += len(raw)
                                if size > runtime.max_archive_bytes:
                                    raise _error("BACKUP_TOO_LARGE", "The selected dump exceeds the local archive limit")
                                digest.update(raw)
                                await _write(encrypt, struct.pack("!I", len(raw)) + raw)
                            if await dump.wait() != 0 or size < 5:
                                raise _error("BACKUP_FAILED", "The local authority dump did not complete")
                            await _write(encrypt, struct.pack("!I", 0) + digest.digest())
                            await _finish(encrypt)
                if temporary.stat().st_size > runtime.max_archive_bytes:
                    raise _error("BACKUP_TOO_LARGE", "The encrypted archive exceeds the local archive limit")
                # A credential revoked during the snapshot cannot publish a backup.
                await store.authenticate(token, (Role.OPERATOR,))
                publishing = True
                _publish(temporary, destination)
                return {"effect": "committed", "encrypted": "age", **_receipt(metadata,
                    {"dump_sha256": digest.hexdigest(), "dump_bytes": size}),
                    "journal_included": False, "plaintext_dump_persisted": False,
                    "storage_media_erasure_claimed": False}
    except DomainError as error:
        raise _error(error.code, error.message, started=publishing) from None
    except (OSError, ValueError, TimeoutError, asyncio.IncompleteReadError, ConnectionError):
        raise _error("BACKUP_FAILED", "The local encrypted backup did not complete", started=publishing) from None
    except Exception:
        raise _error("BACKUP_FAILED", "The local encrypted backup could not be completed", started=publishing) from None
    finally:
        await _close_stores(store, started=publishing)
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                raise _error("BACKUP_CLEANUP_FAILED", "The private encrypted staging output could not be removed", started=publishing) from None


async def migrate_authority(settings: Settings, operator_token_file: Path,
        confirm_deployment: str) -> dict:
    """Explicit private upgrade, authenticated before DDL and interlocked with serve."""
    if confirm_deployment != settings.deployment_id:
        raise _error("MIGRATION_CONFIRMATION_REQUIRED", "Confirm the selected deployment before migration")
    if settings.migrator_dsn is None:
        raise _error("PRIVATE_MIGRATION_REQUIRED", "Migration requires the explicit private operator connection")
    schema, application = _dsn(settings.database_dsn)
    private_schema, migrator = _dsn(settings.migrator_dsn)
    if schema != private_schema or any(application[key] != migrator[key]
            for key in ("PGHOST", "PGPORT", "PGDATABASE")):
        raise _error("MIGRATION_SCOPE_DENIED", "The private migrator must address the selected authority database and schema")
    with authority_lock(settings, exclusive=True):
        marker = settings.state_dir / "restore-barrier.json"
        if marker.exists() or marker.is_symlink():
            raise _error("RESTORE_RECOVERY_REQUIRED", "Recover the interrupted restore before migration")
        token = _read_private(operator_token_file, 4096).decode("utf-8").strip()
        private_settings = settings.model_copy(update={"database_dsn": settings.migrator_dsn})
        store = Store(private_settings, DeletionJournal(settings.journal_dir, settings.deployment_id))
        try:
            await store.open_restore_recovery()
            actor = await store.authenticate(token, (Role.OPERATOR,))
            async with store.pool.acquire() as connection:
                previous = await connection.fetchval("SELECT version_num FROM alembic_version")
                await _require_application_defaults(settings, connection)
        finally:
            await store.close()
        try:
            result = await asyncio.to_thread(migrate, settings.migrator_dsn)
        except Exception:
            raise _error("MIGRATION_UNVERIFIED", "The explicit migration result is unknown; inspect the revision and rerun the idempotent operator migration", started=True) from None
        application_store = Store(settings, store.journal)
        try:
            await application_store.open()
            await application_store.reconcile_journal()
            current = await application_store.authenticate(token, (Role.OPERATOR,))
            if current.credential_id != actor.credential_id:
                raise _error("MIGRATION_UNVERIFIED", "The current operator could not be verified through the application connection", started=True)
        except Exception:
            raise _error("MIGRATION_UNVERIFIED", "The schema upgrade committed but application authority verification failed", started=True) from None
        finally:
            await application_store.close()
        return {**result, "previous_migration": previous, "deployment_id": settings.deployment_id,
                "realm": settings.realm, "application_verified": True}


async def restore(settings: Settings, operator_token_file: Path, archive: Path,
        identity_file: Path, expected_head: str, operator_out: Path,
        confirm_deployment: str, runtime: BackupRuntime) -> dict:
    """Exclusive private restore followed by Store's credential/floor recovery.

    expected_head must be independently retained outside the restored DB/archive.
    Its provenance/freshness cannot be attested by a local string argument.
    The published fence is itself an authority effect: if publication leaves a
    marker, failure reports unknown and requires private recovery before executor launch.
    Retrying still requires a live current operator; there is no unauthenticated
    recovery API or fallback to a credential taken from the encrypted archive.

    Distinct non-DDL application roles require independently configured schema
    USAGE and migrator default SELECT/INSERT/UPDATE/DELETE table privileges.
    Archived ACLs are never applied; successful recovery verifies the fresh
    operator credential through the application connection before lifting the fence.
    """
    started = False
    store = Store(settings, DeletionJournal(settings.journal_dir, settings.deployment_id))
    recovery: Store | None = None
    try:
        if confirm_deployment != settings.deployment_id:
            raise _error("RESTORE_CONFIRMATION_REQUIRED", "Explicit confirmation of the selected deployment is required")
        if not isinstance(expected_head, str) or not _HEAD.fullmatch(expected_head):
            raise _error("DELETION_BARRIER", "An independently retained latest deletion head is required, not the backup head")
        if settings.migrator_dsn is None or _dsn(settings.migrator_dsn)[0] != _dsn(settings.database_dsn)[0]:
            raise _error("PRIVATE_RECOVERY_REQUIRED", "Restore requires the matching private migrator connection")
        # App/migrator must address the same exact local database, differing only
        # in credentials. Restoring one database then recovering another is denied.
        _, application = _dsn(settings.database_dsn)
        _, migrator = _dsn(settings.migrator_dsn)
        if any(application[k] != migrator[k] for k in ("PGHOST", "PGPORT", "PGDATABASE")):
            raise _error("RESTORE_SCOPE_DENIED", "The private migrator must address the selected authority database")
        with authority_lock(settings, exclusive=True):
            marker = settings.state_dir / "restore-barrier.json"
            if marker.exists() or marker.is_symlink():
                raise _error("RESTORE_RECOVERY_REQUIRED", "Recover the existing restore fence before attempting another restore")
            async with asyncio.timeout(runtime.timeout_seconds), _processes() as processes, _staging(settings) as staging:
                _runtime(runtime)
                operator_out = _destination(settings, operator_out)
                identity = _key_material(identity_file, identity=True)
                token = _token(operator_token_file)
                await store.open()
                actor = await store.authenticate(token, (Role.OPERATOR,))
                # Journal verification finishes/releases its flock before DB clock
                # reconciliation. Never hold the journal lock around pg_restore.
                await asyncio.to_thread(store.journal.verify, expected_head)
                reconciled = await store.reconcile_journal(expected_head)
                current_head = reconciled["head"]
                async with store.pool.acquire() as connection:
                    live = await _metadata(store, connection, runtime, actor)
                    await _require_application_defaults(settings, connection)
                await _versions(processes, runtime, settings.migrator_dsn)
                encrypted = await _copy_encrypted(archive, staging / "archive.age", runtime.max_archive_bytes)
                metadata, checked = await _preflight(processes, runtime, settings, staging / "archive.age", identity, actor.id, listing=True)
                full_metadata, full_checked = await _preflight(processes, runtime, settings, staging / "archive.age", identity, actor.id, listing=False)
                if metadata != full_metadata or checked != full_checked:
                    raise _error("ARCHIVE_INVALID", "The encrypted archive changed during validation")
                _validate_metadata(metadata, settings, runtime, live["owner_id"])
                await store.authenticate(token, (Role.OPERATOR,))
                await asyncio.to_thread(store.journal.verify, current_head)
                await _docker_control(processes, runtime, settings.migrator_dsn)
                await _require_restore_idle(store)
                decrypt = await _decrypt(processes, runtime, staging / "archive.age", identity)
                if await _read_header(decrypt.stdout) != metadata:
                    raise _error("ARCHIVE_INVALID", "The encrypted archive changed before restore")
                # Store the fresh token privately *before* destructive work so
                # loss of the response/file publish cannot lose a committed token.
                # It is not active until Store recovery commits.
                new_token = secrets.token_urlsafe(48)
                private_write(operator_out, new_token + "\n")
                try:
                    private_write(marker, json.dumps({"deployment_id": settings.deployment_id,
                        "realm": settings.realm, "effect": "unknown", "phase": "fenced_before_executor",
                        "code": "RESTORE_RECOVERY_REQUIRED"}))
                finally:
                    started = marker.exists() or marker.is_symlink()
                await store.close()
                private_write(marker, json.dumps({"deployment_id": settings.deployment_id,
                    "realm": settings.realm, "effect": "unknown", "phase": "executor_may_have_started",
                    "code": "RESTORE_RECOVERY_REQUIRED"}), replace=True)
                await _docker_control(processes, runtime, settings.migrator_dsn, reserve=True)
                restored = await _restore_transaction(processes, runtime,
                    settings.migrator_dsn, metadata, decrypt, checked)
                migrated = await asyncio.to_thread(migrate, settings.migrator_dsn)
                if migrated["migration"] != MIGRATION:
                    raise _error("RESTORE_RECOVERY_REQUIRED", "The restored schema did not reach the supported authority migration", started=True)
                private_settings = settings.model_copy(update={"database_dsn": settings.migrator_dsn})
                recovery = Store(private_settings, store.journal)
                await recovery.open()
                await _docker_control(processes, runtime, settings.migrator_dsn)
                await _require_restore_idle(recovery)
                recovered = await recovery.recover_after_restore(actor.id, new_token, current_head)
                recovery_head = (await asyncio.to_thread(store.journal.verify))["head"]
                await recovery.close()
                await store.open()
                reconciled = await store.reconcile_journal(recovery_head)
                verified = await store.authenticate(new_token, (Role.OPERATOR,))
                if verified.credential_id != recovered.credential_id:
                    raise _error("RESTORE_RECOVERY_REQUIRED", "The recovered credential is not usable on the application connection", started=True)
                marker.unlink()
                descriptor = os.open(settings.state_dir, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                return {"effect": "committed", **_receipt(metadata, restored), **encrypted,
                    "authority_migration_versions": list(MIGRATIONS),
                    "credential_id": recovered.credential_id, "tokens_rotated": True,
                    "rules_need_reapproval": True, "routes_disabled": True, "jobs_fenced": True,
                    "deletion_floors_reapplied": True, "expected_head": expected_head,
                    "journal_head": reconciled["head"], "journal_head_advanced": reconciled["head"] != expected_head,
                    "head_witness_provenance": "operator_supplied_independently_retained_not_attested",
                    "journal_restored": False, "storage_media_erasure_claimed": False,
                    "old_approval_receipts_active": False}
    except DomainError as error:
        if started:
            raise _error("RESTORE_RECOVERY_REQUIRED", "Restore crossed the authority fencing boundary; state is unknown and remains blocked pending private recovery", started=True) from None
        raise _error(error.code, error.message) from None
    except asyncio.CancelledError:
        if started:
            raise _error("RESTORE_RECOVERY_REQUIRED", "Restore was interrupted after authority fencing; private recovery is required", started=True) from None
        raise
    except Exception:
        raise _error("RESTORE_RECOVERY_REQUIRED" if started else "RESTORE_NOT_STARTED",
            "Restore crossed the authority fencing boundary; state is unknown and remains blocked pending private recovery" if started
            else "The encrypted archive or local restore prerequisites could not be verified; restore did not start", started=started) from None
    finally:
        await _close_stores(store, recovery, started=started)


async def recover_interrupted_restore(settings: Settings, operator_token_file: Path,
        expected_head: str, operator_out: Path, confirm_deployment: str,
        runtime: BackupRuntime) -> dict:
    """Recover a fenced authority without claiming an unknown restore applied.

    This is a private operator path, never an HTTP/MCP handler. Authentication
    comes from the current live DB: use the still-current/backup-era operator
    token, or the prewritten fresh token if a previous recovery already committed.
    A marker or archive token/owner field is never authentication.
    """
    store = Store(settings, DeletionJournal(settings.journal_dir, settings.deployment_id))
    recovery: Store | None = None
    started = False
    try:
        if confirm_deployment != settings.deployment_id:
            raise _error("RESTORE_CONFIRMATION_REQUIRED", "Explicit confirmation of the selected deployment is required")
        if not isinstance(expected_head, str) or not _HEAD.fullmatch(expected_head):
            raise _error("DELETION_BARRIER", "An independently retained latest deletion head is required")
        if settings.migrator_dsn is None:
            raise _error("PRIVATE_RECOVERY_REQUIRED", "Recovery requires the matching private migrator connection")
        schema, application = _dsn(settings.database_dsn)
        private_schema, migrator = _dsn(settings.migrator_dsn)
        if schema != private_schema or any(application[k] != migrator[k] for k in ("PGHOST", "PGPORT", "PGDATABASE")):
            raise _error("RESTORE_SCOPE_DENIED", "The private migrator must address the selected authority database and schema")
        with authority_lock(settings, exclusive=True):
            async with asyncio.timeout(runtime.timeout_seconds), _processes() as processes:
                _runtime(runtime)
                marker = settings.state_dir / "restore-barrier.json"
                if not marker.exists():
                    raise _error("RECOVERY_NOT_REQUIRED", "No interrupted local restore requires recovery")
                # Its presence is a fence, not a source of identity or role.
                _read_private(marker, 8192)
                await _docker_control(processes, runtime, settings.migrator_dsn)
                operator_out = _destination(settings, operator_out)
                recovery = Store(settings.model_copy(update={"database_dsn": settings.migrator_dsn}), store.journal)
                await recovery.open_restore_recovery()
                token = _token(operator_token_file)
                actor = await recovery.authenticate(token, (Role.OPERATOR,))
                await asyncio.to_thread(store.journal.verify, expected_head)
                await _require_restore_idle(recovery)
                await _docker_control(processes, runtime, settings.migrator_dsn)
                await recovery.close()
                started = True
                migrated = await asyncio.to_thread(migrate, settings.migrator_dsn)
                if migrated["migration"] != MIGRATION:
                    raise _error("RESTORE_RECOVERY_REQUIRED", "Private recovery could not migrate the interrupted schema", started=True)
                await store.open()
                actor = await store.authenticate(token, (Role.OPERATOR,))
                async with store.pool.acquire() as connection:
                    await _metadata(store, connection, runtime, actor)
                    await _require_application_defaults(settings, connection)
                new_token = secrets.token_urlsafe(48)
                private_write(operator_out, new_token + "\n")
                await store.close()
                await recovery.open()
                await _require_restore_idle(recovery)
                await _docker_control(processes, runtime, settings.migrator_dsn)
                recovered = await recovery.recover_after_restore(actor.id, new_token, expected_head)
                recovery_head = (await asyncio.to_thread(store.journal.verify))["head"]
                await recovery.close()
                await store.open()
                reconciled = await store.reconcile_journal(recovery_head)
                verified = await store.authenticate(new_token, (Role.OPERATOR,))
                if verified.credential_id != recovered.credential_id:
                    raise _error("RESTORE_RECOVERY_REQUIRED", "The recovered credential is not usable on the application connection", started=True)
                marker.unlink()
                descriptor = os.open(settings.state_dir, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                return {"effect": "committed", "deployment_id": settings.deployment_id, "realm": settings.realm,
                    "schema": schema, "archive_replacement": "unknown_not_attested",
                    "authority_migration_versions": list(MIGRATIONS),
                    "credential_id": recovered.credential_id, "tokens_rotated": True,
                    "rules_need_reapproval": True, "routes_disabled": True, "jobs_fenced": True,
                    "deletion_floors_reapplied": True, "expected_head": expected_head,
                    "journal_head": reconciled["head"], "journal_head_advanced": reconciled["head"] != expected_head,
                    "head_witness_provenance": "operator_supplied_independently_retained_not_attested",
                    "journal_restored": False, "storage_media_erasure_claimed": False,
                    "old_approval_receipts_active": False}
    except DomainError as error:
        raise _error(error.code if not started else "RESTORE_RECOVERY_REQUIRED",
            error.message if not started else "Private recovery started; authority remains blocked until recovery succeeds",
            started=started) from None
    except asyncio.CancelledError:
        if started:
            raise _error("RESTORE_RECOVERY_REQUIRED", "Private recovery was interrupted; authority remains fenced", started=True) from None
        raise
    except Exception:
        raise _error("RESTORE_RECOVERY_REQUIRED", "Private recovery could not be completed; authority remains fenced", started=started) from None
    finally:
        await _close_stores(store, recovery, started=started)
