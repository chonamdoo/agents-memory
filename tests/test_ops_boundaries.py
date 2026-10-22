from __future__ import annotations

import asyncio
import hashlib
import json
import os
import struct
import subprocess
import threading
import uuid
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import asyncpg
import pytest
import pytest_asyncio

from agents_memory import ops
from agents_memory.config import Settings
from agents_memory.domain import CaptureCommand, DomainError, EffectState, Role
from agents_memory.journal import DeletionJournal
from agents_memory.migrations import MIGRATION, MIGRATIONS, migrate
from agents_memory.ops import (
    _MAGIC,
    BackupRuntime,
    _destination,
    _dsn,
    _read_frames,
    _read_header,
    _validate_metadata,
    authority_lock,
    backup,
    recover_interrupted_restore,
    restore,
)
from agents_memory.private_io import private_write
from agents_memory.store import Store

TOKEN = "ops-boundary-current-operator-" + "a" * 40


@pytest.fixture
def settings(tmp_path):
    dsn = "postgresql://memory:private-database-secret@127.0.0.1:5432/memory?schema=memory"
    return Settings(deployment_id="deployment_ops", realm="personal_ops", mode="personal",
        database_dsn=dsn, migrator_dsn=dsn, state_dir=tmp_path / "authority",
        journal_dir=tmp_path / "independent-journal")


def metadata(settings):
    return {"format": 2, "deployment_id": settings.deployment_id, "realm": settings.realm,
        "schema": "memory", "owner_id": "owner_ops", "backup_head": "a" * 64,
        "postgres_version": "18.6", "vector_version": "0.8.7", "migration_version": MIGRATION,
        "migration_versions": list(MIGRATIONS), "created_at": "2026-10-12T00:00:00+00:00"}


def versioned_metadata(settings, revision):
    value = metadata(settings)
    value["migration_version"] = revision
    value["migration_versions"] = list(MIGRATIONS[:MIGRATIONS.index(revision) + 1])
    return value


def legacy_metadata(settings):
    value = metadata(settings)
    value["format"] = 1
    value["migration_version"] = MIGRATIONS[0]
    del value["migration_versions"]
    return value


def reader(raw):
    stream = asyncio.StreamReader()
    stream.feed_data(raw)
    stream.feed_eof()
    return stream


def framed_dump(raw):
    return struct.pack("!I", len(raw)) + raw + struct.pack("!I", 0) + hashlib.sha256(raw).digest()


@pytest.mark.parametrize("key,value", [
    ("deployment_id", "other_deployment"), ("realm", "company_customer"),
    ("schema", "other_schema"), ("owner_id", "self_reported_owner"),
    ("migration_version", "other_migration"),
])
def test_encrypted_metadata_cannot_select_another_authority(settings, key, value):
    envelope = metadata(settings)
    envelope[key] = value
    with pytest.raises(DomainError) as denied:
        _validate_metadata(envelope, settings, "owner_ops")
    assert denied.value.code == "RESTORE_SCOPE_DENIED"
    assert denied.value.effect == EffectState.NOT_STARTED


@pytest.mark.parametrize("mutation", [
    lambda value: dict(value, backup_head=""),
    lambda value: dict(value, format=True),
    lambda value: dict(value, current_latest_head="a" * 64),
    lambda value: dict(value, backup_head=None),
])
def test_metadata_cannot_claim_a_latest_head_or_change_envelope_shape(settings, mutation):
    with pytest.raises(DomainError) as denied:
        _validate_metadata(mutation(metadata(settings)), settings, "owner_ops")
    assert denied.value.code == "ARCHIVE_INVALID"


@pytest.mark.asyncio
async def test_envelope_detects_truncation_corruption_and_trailing_payload():
    payload = framed_dump(b"PGDMPbounded-parser-input")
    for invalid in (payload[:-1], payload[:-1] + bytes([payload[-1] ^ 1]), payload + b"extra"):
        consumed = []
        async def sink(raw):
            consumed.append(raw)
        with pytest.raises((DomainError, asyncio.IncompleteReadError)):
            await _read_frames(reader(invalid), sink, 65536)
    # A chunk bound is checked before forwarding it to a restore consumer.
    consumed = []
    async def sink(raw):
        consumed.append(raw)
    with pytest.raises(DomainError):
        await _read_frames(reader(struct.pack("!I", 65537)), sink, 1048576)
    assert consumed == []


@pytest.mark.asyncio
async def test_envelope_header_is_bounded_before_json_or_dump_processing():
    with pytest.raises(DomainError) as denied:
        await _read_header(reader(_MAGIC + struct.pack("!I", 8193)))
    assert denied.value.code == "ARCHIVE_INVALID"


def test_output_refuses_existing_files_symlinks_journal_and_interlock(settings, tmp_path):
    owned = tmp_path / "operator-key"
    private_write(owned, "keep-existing-secret")
    link = tmp_path / "link"
    link.symlink_to(owned)
    for output in (owned, link, settings.journal_dir / "head", settings.state_dir / "restore-barrier.json"):
        with pytest.raises(DomainError):
            _destination(settings, output)
    assert owned.read_text() == "keep-existing-secret"
    assert not settings.journal_dir.exists()


def test_authority_lock_permits_live_backup_but_denies_live_restore(settings):
    with authority_lock(settings):
        with authority_lock(settings):
            pass
        with pytest.raises(DomainError) as denied:
            with authority_lock(settings, exclusive=True):
                pytest.fail("exclusive restore entered a live shared authority")
        assert denied.value.code == "AUTHORITY_BUSY"
    with authority_lock(settings, exclusive=True):
        with pytest.raises(DomainError):
            with authority_lock(settings):
                pytest.fail("service entered exclusive restore")


def test_interrupted_restore_fence_is_not_an_authentication_receipt(settings):
    with authority_lock(settings, exclusive=True):
        private_write(settings.state_dir / "restore-barrier.json", '{"owner_id":"self-reported","role":"operator"}')
    with pytest.raises(DomainError) as denied:
        with authority_lock(settings):
            pytest.fail("shared authority ignored an interrupted restore")
    assert denied.value.code == "RESTORE_RECOVERY_REQUIRED"
    # Exclusive recovery may enter, but must authenticate the real DB itself.
    with authority_lock(settings, exclusive=True):
        pass


@pytest.mark.parametrize("dsn", [
    "postgresql://memory:do-not-log@remote.example/memory?schema=memory",
    "postgresql://memory:do-not-log@127.0.0.1/memory?schema=memory&host=remote.example",
    "postgresql://memory:do-not-log@127.0.0.1/memory?schema=other%3BDROP",
])
def test_database_scope_refusal_does_not_leak_credentials(dsn):
    with pytest.raises(DomainError) as denied:
        _dsn(dsn)
    assert "do-not-log" not in json.dumps(denied.value.public())
    assert "remote.example" not in json.dumps(denied.value.public())


@pytest.mark.asyncio
@pytest.mark.parametrize("expected,confirmation,code", [
    ("", "deployment_ops", "DELETION_BARRIER"),
    (None, "deployment_ops", "DELETION_BARRIER"),
    ("a" * 64, "other_deployment", "RESTORE_CONFIRMATION_REQUIRED"),
])
async def test_restore_requires_explicit_scope_and_independent_head_before_effects(settings, tmp_path, expected, confirmation, code):
    with pytest.raises(DomainError) as denied:
        await restore(settings, tmp_path / "missing-token", tmp_path / "missing-archive",
            tmp_path / "missing-identity", expected, tmp_path / "new-operator", confirmation,
            BackupRuntime(Path("/not-invoked/age")))
    assert denied.value.code == code
    assert denied.value.effect == EffectState.NOT_STARTED
    assert not settings.state_dir.exists()
    assert not settings.journal_dir.exists()
    assert not (tmp_path / "new-operator").exists()


@pytest.mark.asyncio
async def test_restore_refuses_running_supported_authority_before_binary_or_database_work(settings, tmp_path):
    with authority_lock(settings):
        with pytest.raises(DomainError) as denied:
            await restore(settings, tmp_path / "token", tmp_path / "archive", tmp_path / "identity",
                "a" * 64, tmp_path / "operator-new", settings.deployment_id, BackupRuntime(Path("/not-invoked/age")))
    assert denied.value.code == "AUTHORITY_BUSY"
    assert denied.value.effect == EffectState.NOT_STARTED
    assert not (tmp_path / "operator-new").exists()


@pytest.fixture
def binary_runtime():
    # Integration uses real binaries only, supplied explicitly by the operator.
    # Docker runtime JSON uses the same public dataclass as the product CLI.
    encoded = os.environ.get("OPS_TEST_RUNTIME")
    if encoded:
        values = json.loads(encoded)
        for key in ("age_binary", "docker_binary", "docker_config"):
            if values.get(key) is not None:
                values[key] = Path(values[key])
        runtime = BackupRuntime(**values)
    else:
        keys = ("AGE_TEST_BINARY", "PG_DUMP_TEST_BINARY", "PG_RESTORE_TEST_BINARY", "PSQL_TEST_BINARY")
        if not all(os.environ.get(key) for key in keys):
            pytest.skip("Explicit real age/PG18.6 dump/restore/psql operations binaries required")
        runtime = BackupRuntime(Path(os.environ[keys[0]]), pg_dump_binary=Path(os.environ[keys[1]]),
            pg_restore_binary=Path(os.environ[keys[2]]), psql_binary=Path(os.environ[keys[3]]))
    keygen = os.environ.get("AGE_KEYGEN_TEST_BINARY")
    if not keygen:
        pytest.skip("Explicit real AGE_KEYGEN_TEST_BINARY required")
    return runtime, Path(keygen)


@pytest_asyncio.fixture
async def live_authority(tmp_path):
    raw_dsn = os.environ.get("PG_TEST_DSN")
    if not raw_dsn:
        pytest.skip("PG_TEST_DSN required for isolated real authority boundary tests")
    parts = urlsplit(raw_dsn)
    query = dict(parse_qsl(parts.query))
    query.pop("schema", None)
    admin_dsn = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    schema = "am_ops_test_" + uuid.uuid4().hex
    root = tmp_path.resolve() / "ops-private"
    root.mkdir(mode=0o700)
    admin = await asyncpg.connect(admin_dsn)
    store = None
    try:
        await admin.execute(f'CREATE SCHEMA "{schema}"')
        query["schema"] = schema
        dsn = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
        await asyncio.to_thread(migrate, dsn)
        settings = Settings(deployment_id="deployment_ops", realm="personal_ops", mode="personal",
            database_dsn=dsn, migrator_dsn=dsn, state_dir=root / "authority", journal_dir=root / "journal")
        store = Store(settings, DeletionJournal(settings.journal_dir, settings.deployment_id))
        await store.open()
        actor = await store.bootstrap(TOKEN, "owner_ops")
        binding = await store.register_binding(actor, "Synthetic ops boundary", None, "binding-ops")
        actor = await store.authenticate(TOKEN)
        private_write(root / "operator", TOKEN)
        yield store, actor, binding, settings, root
    finally:
        if store is not None:
            await store.close()
        await admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await admin.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("archived_index", range(len(MIGRATIONS) - 1))
async def test_private_operator_migrates_prior_schema_without_rotating_credentials_or_resurrecting_sources(live_authority, archived_index):
    from test_store_authority import historical_schema_fixture

    store, actor, binding, settings, root = live_authority
    selected = await store.capture(actor, CaptureCommand(binding_id=binding.id,
        idempotency_key="migration-current", origin_key="migration-current",
        body="Synthetic eligible migration evidence.", speaker="human"))
    if archived_index < 5:
        async with store.pool.acquire() as connection:
            await connection.execute("""INSERT INTO am_operations
                (id,binding_id,credential_id,kind,state,source_id,error_code,epoch)
                SELECT 'historical_failed_operation',$1,$2,'reprocess','failed',$3,'HISTORICAL_FAILURE',epoch
                FROM am_clock WHERE singleton""", binding.id, actor.credential_id, selected.source_id)
            await connection.execute("""INSERT INTO am_jobs
                (id,binding_id,operation_id,credential_id,credential_generation,kind,source_ids,state,attempts,error_code)
                VALUES('historical_failed_job',$1,'historical_failed_operation',$2,$3,'extract',$4,'failed',2,'HISTORICAL_FAILURE')""",
                binding.id, actor.credential_id, actor.generation, [selected.source_id])
    withdrawn = await store.capture(actor, CaptureCommand(binding_id=binding.id,
        idempotency_key="migration-withdrawn", origin_key="migration-withdrawn",
        body="Synthetic withdrawn migration evidence.", speaker="human"))
    await store.retract(actor, binding.id, withdrawn.source_id, "migration-floor")
    head = store.journal.verify()["head"]
    journal_files = {path.name: path.read_bytes() for path in settings.journal_dir.iterdir() if path.is_file()}
    async with store.pool.acquire() as connection:
        credentials = await connection.fetch("SELECT * FROM am_credentials ORDER BY id")
    await historical_schema_fixture(store, archived_index)
    async with store.pool.acquire() as connection:
        assert await connection.fetch("SELECT * FROM am_credentials ORDER BY id") == credentials
        assert set(await connection.fetchval("""SELECT array_agg(table_name) FROM information_schema.tables
            WHERE table_schema=current_schema() AND table_type='BASE TABLE'""")) == ops._ARCHIVE_TABLES[MIGRATIONS[archived_index]]
        sequences = {row["relname"] for row in await connection.fetch(
            """SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
               WHERE n.nspname=current_schema() AND c.relkind='S'""")}
        assert sequences == (set(ops._IDENTITY_SEQUENCES) if archived_index >= 5 else set())
        columns = {(row["table_name"], row["column_name"]) for row in await connection.fetch(
            "SELECT table_name,column_name FROM information_schema.columns WHERE table_schema=current_schema()")}
        for table, column, introduced in (
            ("am_feedback", "state", 1), ("am_claims", "vector_revision", 2),
            ("am_claims", "extraction_operation_id", 2), ("am_claims", "superseded_by", 2),
            ("am_operations", "successor_operation_id", 3), ("am_operations", "source_pointer", 4),
            ("am_sources", "capture_coverage", 4), ("am_claims", "capability", 4),
            ("am_admissions", "relation_ids", 4), ("am_claims", "awaiting_revalidation", 5),
            ("am_source_selections", "reason", 5), ("am_admissions", "request_digest", 5),
            ("am_operations", "actor_generation", 6), ("am_sources", "health_restore_revision", 6),
            ("am_admissions", "health_manifest", 6), ("am_pending_judgments", "health_key", 6),
            ("am_pending_judgments", "health_revision", 6), ("am_pending_judgments", "health_payload", 6),
            ("am_feedback", "health_version", 6), ("am_feedback", "resolution_event_id", 6),
        ):
            assert ((table, column) in columns) == (archived_index >= introduced)
    assert journal_files == {path.name: path.read_bytes() for path in settings.journal_dir.iterdir() if path.is_file()}
    await store.close()
    with pytest.raises(DomainError) as ordinary:
        await store.open()
    assert ordinary.value.code == "MIGRATION_REQUIRED"
    config = root / "legacy-deployment.json"
    legacy = {**settings.model_dump(mode="json"), "capability": "full_semantic",
              "models": {"generation_url": "http://127.0.0.1:8000"},
              "allowed_model_purposes": ["extraction"], "lease_seconds": 120,
              "heartbeat_seconds": 10, "job_attempt_limit": 4}
    original = (json.dumps(legacy) + "\n").encode()
    private_write(config, original)
    result = await ops.migrate_authority(settings, root / "operator", settings.deployment_id,
                                         config_path=config, original_config=original)
    assert result["previous_migration"] == MIGRATIONS[archived_index]
    assert result["migration"] == MIGRATION and result["application_verified"]
    upgraded = json.loads(config.read_bytes())
    assert upgraded["capability"] == "agent_judged" and "models" not in upgraded
    retained = settings.state_dir / ("config-upgrade-" + hashlib.sha256(original).hexdigest() + ".json")
    assert retained.read_bytes() == original
    assert (root / "operator").read_text() == TOKEN
    await store.open()
    await store.reconcile_journal(head)
    current = await store.authenticate(TOKEN, (Role.OPERATOR,))
    assert current.credential_id == actor.credential_id
    assert (await store.source(current, binding.id, selected.source_id)).body == "Synthetic eligible migration evidence."
    async with store.pool.acquire() as connection:
        if archived_index < 5:
            preserved = await connection.fetchrow("""SELECT r.original->>'state' AS state,
                r.original->>'error_code' AS error_code,r.original->>'attempts' AS attempts,
                r.original_operation->>'state' AS operation_state,j.state AS retired_state,p.state AS pending_state
                FROM am_retired_jobs r JOIN am_jobs j ON j.id=r.job_id
                JOIN am_pending_judgments p ON p.id=r.successor_id WHERE r.job_id='historical_failed_job'""")
            assert dict(preserved) == {"state": "failed", "error_code": "HISTORICAL_FAILURE", "attempts": "2",
                "operation_state": "failed", "retired_state": "retired", "pending_state": "pending"}
        else:
            assert await connection.fetchval("SELECT count(*) FROM am_retired_jobs") == 0
    retired = await store.inspect(current, binding.id, withdrawn.source_id)
    assert retired["state"] == "retracted" and retired.get("body") is None
    assert store.journal.verify()["head"] == head


@pytest.mark.asyncio
async def test_previous_revision_archive_restores_after_escalation_migration(live_authority, binary_runtime):
    store, actor, binding, settings, root = live_authority
    runtime, keygen = binary_runtime
    identity, recipients = age_keys(root, keygen)
    assert "am_judge_escalations" not in ops._ARCHIVE_TABLES["0007_memory_health"]
    assert "am_judge_escalations" in ops._ARCHIVE_TABLES[MIGRATION]
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == MIGRATION == "0008_judge_escalations"
    archived = await store.capture(actor, CaptureCommand(binding_id=binding.id, idempotency_key="escalation-archive",
        origin_key="escalation-archive", body="Synthetic archived source.", speaker="human"))
    archive = root / "prior-0007.age"
    await historical_encrypted_archive(store, actor, archive, recipients, runtime, MIGRATIONS.index("0007_memory_health"))
    async with store.pool.acquire() as connection:
        pending_id = await connection.fetchval("SELECT id FROM am_pending_judgments WHERE $1=ANY(source_ids)",
            archived.source_id)
        # Current-only state that references the archived table: restore preparation must clear it first.
        await connection.execute("""INSERT INTO am_judge_escalations(pending_id,binding_id,binding_revision,scope,reason,
                credential_id,provider,provider_revision) VALUES($1,$2,1,'item','uncertain',$3,'jev',1)""",
            pending_id, binding.id, actor.credential_id)
        await connection.execute("UPDATE am_pending_judgments SET escalation_generation=3 WHERE id=$1", pending_id)
    head = store.journal.verify()["head"]
    await store.close()

    result = await restore(settings, root / "operator", archive, identity, head,
        root / "restored-operator", settings.deployment_id, runtime)

    assert result["migration_versions"] == list(MIGRATIONS[:7])
    assert result["authority_migration_versions"] == list(MIGRATIONS)
    await store.open()
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == MIGRATION
        assert await connection.fetchval("SELECT count(*) FROM am_judge_escalations") == 0
        assert await connection.fetchval("SELECT escalation_generation FROM am_pending_judgments WHERE id=$1",
            pending_id) == 0


@pytest.mark.asyncio
async def test_private_migration_refuses_agent_credential_before_old_schema_changes(live_authority):
    from test_store_authority import historical_schema_fixture

    store, actor, binding, settings, root = live_authority
    agent_token = "synthetic-migration-agent-" + "a" * 40
    await store.issue_token(actor, Role.AGENT, (binding.id,), agent_token)
    private_write(root / "agent", agent_token)
    await historical_schema_fixture(store, 2)
    await store.close()
    config = root / "legacy.json"
    original = json.dumps({**settings.model_dump(mode="json"),
                           "capability": "full_semantic", "models": {}}).encode()
    private_write(config, original)
    with pytest.raises(DomainError) as denied:
        await ops.migrate_authority(settings, root / "agent", settings.deployment_id,
                                     config_path=config, original_config=original)
    assert denied.value.code == "SCOPE_DENIED" and denied.value.effect == EffectState.NOT_STARTED
    assert config.read_bytes() == original
    assert not list(settings.state_dir.glob("config-upgrade-*.json"))
    private = Store(settings, store.journal)
    await private.open_restore_recovery()
    try:
        async with private.pool.acquire() as connection:
            assert await connection.fetchval("SELECT version_num FROM alembic_version") == MIGRATIONS[2]
            assert not await connection.fetchval("""SELECT EXISTS(SELECT 1 FROM information_schema.columns
                WHERE table_schema=current_schema() AND table_name='am_operations' AND column_name='successor_operation_id')""")
    finally:
        await private.close()


@pytest.mark.asyncio
async def test_operator_migration_refuses_live_service_and_restore_fence_before_database_work(settings, tmp_path):
    with authority_lock(settings):
        with pytest.raises(DomainError) as busy:
            await ops.migrate_authority(settings, tmp_path / "missing-token", settings.deployment_id)
        assert busy.value.code == "AUTHORITY_BUSY" and busy.value.effect == EffectState.NOT_STARTED
    private_write(settings.state_dir / "restore-barrier.json", '{"effect":"unknown"}')
    with pytest.raises(DomainError) as fenced:
        await ops.migrate_authority(settings, tmp_path / "missing-token", settings.deployment_id)
    assert fenced.value.code == "RESTORE_RECOVERY_REQUIRED" and fenced.value.effect == EffectState.NOT_STARTED


def age_keys(tmp_path, keygen):
    identity = tmp_path / "identity.age"
    subprocess.run([str(keygen), "-o", str(identity)], check=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env={"PATH": os.defpath, "LANG": "C"})
    identity.chmod(0o600)
    public = subprocess.run([str(keygen), "-y", str(identity)], check=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        env={"PATH": os.defpath, "LANG": "C"}).stdout
    recipients = tmp_path / "recipients.age"
    private_write(recipients, public)
    return identity, recipients


async def historical_encrypted_archive(store, actor, archive, recipients, runtime, archived_index=1):
    from test_store_authority import historical_schema_fixture

    async with store.pool.acquire() as connection:
        value = await ops._metadata(store, connection, runtime, actor)
    value["migration_version"] = MIGRATIONS[archived_index]
    value["migration_versions"] = list(MIGRATIONS[:archived_index + 1])
    await historical_schema_fixture(store, archived_index)
    await store.close()
    try:
        private_write(archive, b"")
        async with ops._processes() as processes:
            with archive.open("wb") as output:
                encrypt = await processes.start([str(runtime.age_binary), "--encrypt",
                    "--recipients-file", str(recipients)], stdout=output)
                args = ["--format=custom", "--no-owner", "--no-privileges", "--strict-names"]
                args.extend('--table="' + value["schema"] + '"."' + name + '"'
                    for name in sorted(ops._ARCHIVE_TABLES[value["migration_version"]]))
                dump = await ops._pg(processes, runtime, "dump", store.settings.database_dsn, args)
                dump.stdin.close()
                header = json.dumps(value).encode()
                await ops._write(encrypt, _MAGIC + struct.pack("!I", len(header)) + header)
                digest = hashlib.sha256()
                while raw := await dump.stdout.read(ops._CHUNK):
                    digest.update(raw)
                    await ops._write(encrypt, struct.pack("!I", len(raw)) + raw)
                assert await dump.wait() == 0
                await ops._write(encrypt, struct.pack("!I", 0) + digest.digest())
                await ops._finish(encrypt)
    finally:
        await asyncio.to_thread(migrate, store.settings.database_dsn)
        await store.open()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "preparation", "archive_sql"])
async def test_real_format_two_prior_restore_rolls_back_current_lineage_and_reservations_on_failure(
        live_authority, binary_runtime, monkeypatch, failure):
    store, actor, binding, settings, root = live_authority
    runtime, keygen = binary_runtime
    identity, recipients = age_keys(root, keygen)
    old = await store.capture(actor, CaptureCommand(binding_id=binding.id, idempotency_key="prior-source",
        origin_key="prior-source", body="Synthetic historical source.", speaker="human"))
    archive = root / "prior-0002.age"
    await historical_encrypted_archive(store, actor, archive, recipients, runtime)
    await store.retract(actor, binding.id, old.source_id, "post-archive-floor")
    current = await store.capture(actor, CaptureCommand(binding_id=binding.id, idempotency_key="current-source",
        origin_key="current-source", body="Synthetic current authority source.", speaker="human"))
    async with store.pool.acquire() as connection:
        await connection.execute("""INSERT INTO am_claims(id,binding_id,route_revision,vector_revision,extraction_operation_id)
            VALUES('current_claim_a',$1,'synthetic-route','synthetic-vector',$2),
                  ('current_claim_b',$1,'synthetic-route','synthetic-vector',$2)""", binding.id, current.id)
        await connection.execute("UPDATE am_claims SET superseded_by='current_claim_a' WHERE id='current_claim_b'")
        await connection.execute("""INSERT INTO am_claim_sources
            VALUES('current_claim_a',$1,1),('current_claim_b',$1,1)""", current.source_id)
        await connection.execute("""INSERT INTO am_relations(id,binding_id,left_id,right_id,kind,reason)
            VALUES('current_relation',$1,'current_claim_a','current_claim_b','contradicts','Synthetic lineage')""", binding.id)
        await connection.execute("INSERT INTO am_relation_claims VALUES('current_relation','current_claim_a')")
        await connection.execute("INSERT INTO am_relation_sources VALUES('current_relation',$1,1)", current.source_id)
        await connection.execute("""INSERT INTO am_origin_reservations
            VALUES('current-reservation',$1,'synthetic-digest',$2,'synthetic-key','synthetic-intent')""", binding.id, actor.id)
        before = {table: [dict(row) for row in await connection.fetch(f"SELECT * FROM {table} ORDER BY 1")]
            for table in ("am_sources", "am_claims", "am_claim_sources", "am_relations", "am_relation_sources",
                "am_relation_claims", "am_origin_reservations")}
    head = store.journal.verify()["head"]
    await store.close()
    if failure:
        with monkeypatch.context() as injected:
            if failure == "preparation":
                prepare = ops.restore_preparation_sql
                injected.setattr(ops, "restore_preparation_sql",
                    lambda revision, schema: prepare(revision, schema) + "SELECT 1/0;\n")
            else:
                write = ops._write
                async def failing_sql(process, raw):
                    if raw == b"\nCOMMIT;\n":
                        raw = b"\nSELECT 1/0;\nCOMMIT;\n"
                    await write(process, raw)
                injected.setattr(ops, "_write", failing_sql)
            with pytest.raises(DomainError) as failed:
                await restore(settings, root / "operator", archive, identity, head,
                    root / "failed-operator", settings.deployment_id, runtime)
        assert failed.value.code == "RESTORE_RECOVERY_REQUIRED"
        assert failed.value.effect == EffectState.UNKNOWN
        assert "Synthetic" not in json.dumps(failed.value.public())
        await store.open()
        async with store.pool.acquire() as connection:
            assert await connection.fetchval("SELECT version_num FROM alembic_version") == MIGRATION
            after = {table: [dict(row) for row in await connection.fetch(f"SELECT * FROM {table} ORDER BY 1")]
                for table in before}
            assert after == before
            assert await connection.fetchval("SELECT extraction_operation_id FROM am_claims WHERE id='current_claim_a'") == current.id
        assert (settings.state_dir / "restore-barrier.json").exists()
        await store.close()
        await recover_interrupted_restore(settings, root / "operator", head,
            root / "recovery-operator", settings.deployment_id, runtime)
        private_write(root / "operator", (root / "recovery-operator").read_text(), replace=True)
    result = await restore(settings, root / "operator", archive, identity, head,
        root / "successful-operator", settings.deployment_id, runtime)
    assert result["migration_versions"] == list(MIGRATIONS[:2])
    assert result["authority_migration_versions"] == list(MIGRATIONS)
    assert result["tokens_rotated"] and result["jobs_fenced"] and result["routes_disabled"]
    await store.open()
    fresh = await store.authenticate((root / "successful-operator").read_text().strip(), (Role.OPERATOR,))
    with pytest.raises(DomainError):
        await store.authenticate(TOKEN)
    with pytest.raises(DomainError):
        await store.source(fresh, binding.id, old.source_id)
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == MIGRATION
        assert await connection.fetchval("SELECT to_regclass('am_origin_reservations')") is not None
        assert await connection.fetchval("SELECT COUNT(*) FROM am_jobs WHERE state='leased'") == 0
    assert not (settings.state_dir / "restore-barrier.json").exists()


@pytest.mark.asyncio
async def test_backup_and_restore_deny_real_agent_credential_before_effects(live_authority, binary_runtime):
    store, actor, binding, settings, root = live_authority
    runtime, keygen = binary_runtime
    identity, recipients = age_keys(root, keygen)
    agent_token = "agent-must-not-backup-" + "z" * 40
    await store.issue_token(actor, Role.AGENT, (binding.id,), agent_token)
    private_write(root / "agent", agent_token)
    with pytest.raises(DomainError) as denied:
        await backup(settings, root / "agent", root / "unauthorized.age", recipients, runtime)
    assert denied.value.effect == EffectState.NOT_STARTED
    assert not (root / "unauthorized.age").exists()
    with pytest.raises(DomainError) as restore_denied:
        await restore(settings, root / "agent", root / "not-read.age", identity, store.journal.verify()["head"],
            root / "unauthorized-operator", settings.deployment_id, runtime)
    assert restore_denied.value.effect == EffectState.NOT_STARTED
    assert not (root / "unauthorized-operator").exists()
    assert not (settings.state_dir / "restore-barrier.json").exists()
    await store.authenticate(TOKEN, (Role.OPERATOR,))


@pytest.mark.asyncio
async def test_corrupt_encrypted_archive_and_wrong_head_preserve_live_authority(live_authority, binary_runtime):
    store, actor, binding, settings, root = live_authority
    runtime, keygen = binary_runtime
    identity, recipients = age_keys(root, keygen)
    source = await store.capture(actor, CaptureCommand(binding_id=binding.id, idempotency_key="ops-source",
        origin_key="ops-source", body="Synthetic retained text; never company data.", speaker="human"))
    archived = await backup(settings, root / "operator", root / "backup.age", recipients, runtime)
    assert archived["backup_head_is_latest_witness"] is False
    original = (root / "backup.age").read_bytes()
    private_write(root / "truncated.age", original[:-1])
    head = store.journal.verify()["head"]
    journal_files = {name: (settings.journal_dir / name).read_bytes() for name in ("key", "metadata", "entries", "head")}
    for archive, expected in ((root / "backup.age", "0" * 64), (root / "truncated.age", head)):
        with pytest.raises(DomainError) as denied:
            await restore(settings, root / "operator", archive, identity, expected,
                root / "operator-new", settings.deployment_id, runtime)
        assert denied.value.effect == EffectState.NOT_STARTED
        assert TOKEN not in json.dumps(denied.value.public())
        assert not (root / "operator-new").exists()
        assert not (settings.state_dir / "restore-barrier.json").exists()
        await store.authenticate(TOKEN, (Role.OPERATOR,))
        assert (await store.source(actor, binding.id, source.source_id)).body.startswith("Synthetic retained")
    assert journal_files == {name: (settings.journal_dir / name).read_bytes() for name in journal_files}


@pytest.mark.asyncio
async def test_restored_old_snapshot_cannot_resurrect_a_deleted_source(live_authority, binary_runtime):
    store, actor, binding, settings, root = live_authority
    runtime, keygen = binary_runtime
    identity, recipients = age_keys(root, keygen)
    source = await store.capture(actor, CaptureCommand(binding_id=binding.id, idempotency_key="before-backup",
        origin_key="before-backup", body="Synthetic old snapshot text.", speaker="human"))
    async with store.pool.acquire() as connection:
        archived_sequence = await connection.fetchval("SELECT max(sequence) FROM am_pending_judgments")
    archived = await backup(settings, root / "operator", root / "before-retract.age", recipients, runtime)
    await store.retract(actor, binding.id, source.source_id, "after-backup-retract")
    expected_head = store.journal.verify()["head"]
    assert expected_head != archived["backup_head"]
    await store.close()
    receipt = await restore(settings, root / "operator", root / "before-retract.age", identity,
        expected_head, root / "operator-rotated", settings.deployment_id, runtime)
    assert receipt["tokens_rotated"] and receipt["rules_need_reapproval"] and receipt["routes_disabled"]
    assert receipt["journal_restored"] is False
    assert receipt["expected_head"] == expected_head
    assert "Synthetic old snapshot text." not in json.dumps(receipt)
    assert TOKEN not in json.dumps(receipt)
    await store.open()
    await store.reconcile_journal(expected_head)
    with pytest.raises(DomainError):
        await store.authenticate(TOKEN)
    current = await store.authenticate((root / "operator-rotated").read_text().strip(), (Role.OPERATOR,))
    after_restore = await store.capture(current, CaptureCommand(binding_id=binding.id, idempotency_key="after-restore",
        origin_key="after-restore", body="Synthetic fresh post-restore evidence.", speaker="human"))
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT sequence FROM am_pending_judgments WHERE $1=ANY(source_ids)",
            after_restore.source_id) > archived_sequence
    with pytest.raises(DomainError):
        await store.source(current, binding.id, source.source_id)
    assert not (settings.state_dir / "restore-barrier.json").exists()


@pytest.mark.asyncio
async def test_recovery_marker_never_grants_operator_authority(live_authority, binary_runtime):
    store, actor, binding, settings, root = live_authority
    runtime, _ = binary_runtime
    await store.issue_token(actor, Role.AGENT, (binding.id,), "not-an-operator-" + "z" * 40)
    private_write(root / "agent", "not-an-operator-" + "z" * 40)
    settings.state_dir.mkdir(mode=0o700)
    marker = settings.state_dir / "restore-barrier.json"
    private_write(marker, json.dumps({"owner_id": actor.id, "role": "operator"}))
    with pytest.raises(DomainError) as denied:
        await recover_interrupted_restore(settings, root / "agent", store.journal.verify()["head"],
            root / "operator-recovery", settings.deployment_id, runtime)
    assert denied.value.effect == EffectState.NOT_STARTED
    assert marker.exists()
    assert not (root / "operator-recovery").exists()


@pytest.mark.asyncio
async def test_authenticated_private_recovery_rotates_without_claiming_archive_applied(live_authority, binary_runtime):
    store, actor, _, settings, root = live_authority
    runtime, _ = binary_runtime
    settings.state_dir.mkdir(mode=0o700)
    marker = settings.state_dir / "restore-barrier.json"
    private_write(marker, '{"effect":"unknown","code":"RESTORE_RECOVERY_REQUIRED"}')
    head = store.journal.verify()["head"]
    receipt = await recover_interrupted_restore(settings, root / "operator", head,
        root / "operator-recovered", settings.deployment_id, runtime)
    assert receipt["archive_replacement"] == "unknown_not_attested"
    assert receipt["tokens_rotated"] and receipt["rules_need_reapproval"]
    assert receipt["routes_disabled"] and receipt["jobs_fenced"]
    assert not marker.exists()
    assert TOKEN not in json.dumps(receipt)
    await store.reconcile_journal(head)
    with pytest.raises(DomainError):
        await store.authenticate(TOKEN)
    recovered = await store.authenticate((root / "operator-recovered").read_text().strip(), (Role.OPERATOR,))
    assert recovered.id == actor.id


@pytest.mark.parametrize("manifest", [[], list(reversed(MIGRATIONS)), [MIGRATIONS[-1]], "0002_directional_tombstones"])
def test_ordered_migration_manifest_cannot_be_omitted_reordered_or_forged(settings, manifest):
    value = metadata(settings)
    value["migration_versions"] = manifest
    with pytest.raises(DomainError) as denied:
        _validate_metadata(value, settings, "owner_ops")
    assert denied.value.code == "RESTORE_SCOPE_DENIED"
    assert denied.value.effect == EffectState.NOT_STARTED


def test_known_legacy_archive_keeps_exact_old_table_scope(settings):
    _validate_metadata(legacy_metadata(settings), settings, "owner_ops")
    def toc(tables):
        entries = [f"{number}; 0 0 {kind} memory {table} memory"
            for number, (table, kind) in enumerate(
                ((table, kind) for table in sorted(tables) for kind in ("TABLE", "TABLE DATA")), 1)]
        if tables in (ops._ARCHIVE_TABLES["0006_agent_judged"], ops._ARCHIVE_TABLES["0007_memory_health"],
                      ops._ARCHIVE_TABLES["0008_judge_escalations"]):
            entries.extend([
                "900; 0 0 SEQUENCE memory am_pending_judgments_sequence_seq memory",
                "901; 0 0 SEQUENCE SET memory am_pending_judgments_sequence_seq memory",
                "902; 0 0 SEQUENCE memory am_claims_cleanup_sequence_seq memory",
                "903; 0 0 SEQUENCE SET memory am_claims_cleanup_sequence_seq memory",
            ])
        return "\n".join(entries).encode()
    legacy = ops._ARCHIVE_TABLES["0001_authority"]
    directional = ops._ARCHIVE_TABLES["0002_directional_tombstones"]
    ops._validate_toc(toc(legacy), "memory", legacy)
    ops._validate_toc(toc(directional), "memory", directional)
    ops._validate_toc(toc(ops._TABLES), "memory")
    with pytest.raises(DomainError):
        ops._validate_toc(toc(ops._TABLES), "memory", legacy)
    with pytest.raises(DomainError):
        ops._validate_toc(toc(legacy), "memory")
    with pytest.raises(DomainError):
        ops._validate_toc(toc(ops._TABLES), "memory", directional)
    with pytest.raises(DomainError):
        ops._validate_toc(toc(directional), "memory")
    selection = ops._ARCHIVE_TABLES["0005_company_selection"]
    ops._validate_toc(toc(selection), "memory", selection)
    with pytest.raises(DomainError):
        ops._validate_toc(toc(selection), "memory")
    with pytest.raises(DomainError):
        ops._validate_toc(toc(ops._TABLES), "memory", selection)


@pytest.mark.parametrize("revision", MIGRATIONS)
def test_versioned_sequence_inventory_is_exact(revision):
    tables = ops._ARCHIVE_TABLES[revision]
    table_entries = [
        f"{number}; 0 0 {kind} memory {table} memory"
        for number, (table, kind) in enumerate(
            ((table, kind) for table in sorted(tables)
             for kind in ("TABLE", "TABLE DATA")), 1
        )
    ]
    sequence_entries = [
        "900; 0 0 SEQUENCE memory am_pending_judgments_sequence_seq memory",
        "901; 0 0 SEQUENCE SET memory am_pending_judgments_sequence_seq memory",
        "902; 0 0 SEQUENCE memory am_claims_cleanup_sequence_seq memory",
        "903; 0 0 SEQUENCE SET memory am_claims_cleanup_sequence_seq memory",
    ]
    expected = sequence_entries if revision in {"0006_agent_judged", "0007_memory_health", "0008_judge_escalations"} else []
    ops._validate_toc(
        "\n".join([*table_entries, *expected]).encode(), "memory", tables
    )
    invalid = (
        [
            [],
            *[
                sequence_entries[:index] + sequence_entries[index + 1:]
                for index in range(len(sequence_entries))
            ],
        ]
        if revision in {"0006_agent_judged", "0007_memory_health", "0008_judge_escalations"}
        else [
            sequence_entries,
            sequence_entries[:2],
            sequence_entries[2:],
        ]
    )
    for entries in invalid:
        with pytest.raises(DomainError) as denied:
            ops._validate_toc(
                "\n".join([*table_entries, *entries]).encode(), "memory", tables
            )
        assert denied.value.code == "ARCHIVE_SCOPE_DENIED"
        assert denied.value.effect == EffectState.NOT_STARTED


@pytest.mark.parametrize("pollution", [
    "904; 0 0 SEQUENCE memory unrelated_sequence memory",
    "904; 0 0 SEQUENCE SET memory unrelated_sequence memory",
    "904; 0 0 SEQUENCE public am_pending_judgments_sequence_seq memory",
    "904; 0 0 SEQUENCE public am_claims_cleanup_sequence_seq memory",
    "904; 0 0 SEQUENCE OWNED BY memory am_pending_judgments_sequence_seq memory",
    "904; 0 0 SEQUENCE OWNED BY memory am_claims_cleanup_sequence_seq memory",
    "904; 0 0 SEQUENCE memory am_pending_judgments_sequence_seq memory",
    "904; 0 0 SEQUENCE SET memory am_pending_judgments_sequence_seq memory",
    "904; 0 0 SEQUENCE memory am_claims_cleanup_sequence_seq memory",
    "904; 0 0 SEQUENCE SET memory am_claims_cleanup_sequence_seq memory",
])
def test_identity_sequence_never_admits_unrelated_serial_or_duplicate_objects(pollution):
    entries = [
        f"{number}; 0 0 {kind} memory {table} memory"
        for number, (table, kind) in enumerate(
            ((table, kind) for table in sorted(ops._TABLES)
             for kind in ("TABLE", "TABLE DATA")), 1
        )
    ]
    entries.extend([
        "900; 0 0 SEQUENCE memory am_pending_judgments_sequence_seq memory",
        "901; 0 0 SEQUENCE SET memory am_pending_judgments_sequence_seq memory",
        "902; 0 0 SEQUENCE memory am_claims_cleanup_sequence_seq memory",
        "903; 0 0 SEQUENCE SET memory am_claims_cleanup_sequence_seq memory",
        pollution,
    ])
    with pytest.raises(DomainError) as denied:
        ops._validate_toc("\n".join(entries).encode(), "memory")
    assert denied.value.code == "ARCHIVE_SCOPE_DENIED"


@pytest.mark.parametrize("sequence", [
    "am_pending_judgments_sequence_seq",
    "am_claims_cleanup_sequence_seq",
])
@pytest.mark.parametrize("definition_owner,data_owner", [
    ("other", "memory"), ("memory", "other"), ("other", "other"),
])
def test_identity_sequence_owner_must_match_its_table(
    sequence, definition_owner, data_owner
):
    entries = [
        f"{number}; 0 0 {kind} memory {table} memory"
        for number, (table, kind) in enumerate(
            ((table, kind) for table in sorted(ops._TABLES)
             for kind in ("TABLE", "TABLE DATA")), 1
        )
    ]
    for index, name in enumerate((
        "am_pending_judgments_sequence_seq",
        "am_claims_cleanup_sequence_seq",
    )):
        owner = definition_owner if name == sequence else "memory"
        set_owner = data_owner if name == sequence else "memory"
        entries.extend([
            f"{900 + index * 2}; 0 0 SEQUENCE memory {name} {owner}",
            f"{901 + index * 2}; 0 0 SEQUENCE SET memory {name} {set_owner}",
        ])
    with pytest.raises(DomainError) as denied:
        ops._validate_toc("\n".join(entries).encode(), "memory")
    assert denied.value.code == "ARCHIVE_SCOPE_DENIED"


@pytest.fixture
def simulated_restore(settings, tmp_path, monkeypatch):
    state = SimpleNamespace(failure=None, pg_starts=0, rotations=0, journal_rechecks=0,
        schema_revision=MIGRATION, archive_revision=MIGRATION, guard=False, events=[],
        active_tokens={TOKEN: "credential_original"}, journal_head="a" * 64, advance_at=None)
    dump = b"PGDMPsynthetic-parser-stream"
    checked = {"dump_sha256": hashlib.sha256(dump).hexdigest(), "dump_bytes": len(dump)}

    class Journal:
        def verify(self, expected=None):
            if expected is not None:
                assert expected == state.journal_head
            return {"head": state.journal_head}

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield object()

    class Authority:
        def __init__(self, selected, journal):
            self.settings = selected
            self.journal = journal
            self.pool = Pool()

        async def open(self):
            assert state.schema_revision == MIGRATION
            state.events.append("normal_open")

        async def open_restore_recovery(self):
            assert self.settings.database_dsn == self.settings.migrator_dsn
            assert state.schema_revision in MIGRATIONS
            state.events.append("private_recovery_open")

        async def close(self):
            marker = settings.state_dir / "restore-barrier.json"
            if state.failure == "close" and marker.exists():
                state.failure = None
                raise OSError("injected close failure after fence")

        async def authenticate(self, token, roles):
            credential = state.active_tokens.get(token)
            if credential is None:
                raise DomainError("AUTH_DENIED", "The current credential is unavailable")
            return SimpleNamespace(id="owner_ops", credential_id=credential)

        async def reconcile_journal(self, expected):
            assert state.schema_revision == MIGRATION
            self.journal.verify(expected)
            if state.advance_at == "initial" and state.journal_head == "a" * 64:
                state.journal_head = "c" * 64
            state.journal_rechecks += 1
            state.events.append("journal_reconcile")
            return {"head": state.journal_head}

        async def recover_after_restore(self, owner, token, expected):
            assert state.schema_revision == MIGRATION
            assert owner == "owner_ops"
            self.journal.verify(expected)
            if state.advance_at == "recovery":
                state.journal_head = "d" * 64
            state.rotations += 1
            state.active_tokens = {token: "credential_rotated"}
            state.events.append("authority_recovery")
            return SimpleNamespace(id=owner, credential_id="credential_rotated")

    async def no_effect(*args, **kwargs):
        return None

    async def live_metadata(store, connection, runtime, actor):
        assert state.schema_revision == MIGRATION
        return metadata(settings)

    async def copy_archive(source, target, maximum):
        private_write(target, b"synthetic-encrypted-unit-input")
        return {"archive_sha256": "b" * 64, "archive_bytes": 30}

    async def preflight(processes, runtime, selected, archive, identity, owner, *, listing):
        assert isinstance(identity, bytes)
        assert not (archive.parent / "identity").exists()
        value = legacy_metadata(settings) if state.archive_revision == MIGRATIONS[0] else versioned_metadata(settings, state.archive_revision)
        return value, checked

    async def decrypt(processes, runtime, archive, identity):
        assert isinstance(identity, bytes)
        assert not (archive.parent / "identity").exists()
        value = legacy_metadata(settings) if state.archive_revision == MIGRATIONS[0] else versioned_metadata(settings, state.archive_revision)
        header = json.dumps(value).encode()
        async def exited():
            return 0
        return SimpleNamespace(stdout=reader(_MAGIC + struct.pack("!I", len(header)) + header + framed_dump(dump)),
            wait=exited)

    async def control(processes, runtime, dsn, *, reserve=False):
        if state.guard:
            raise DomainError("RESTORE_EXECUTOR_UNOBSERVED", "The container executor has not been observed exited")
        if reserve and state.failure == "reserve":
            state.failure = None
            raise OSError("injected reservation transport failure")

    async def transaction(processes, runtime, dsn, value, decrypt, expected):
        assert (settings.state_dir / "restore-barrier.json").exists()
        state.pg_starts += 1
        state.events.append("restore_transaction")
        restored = await _read_frames(decrypt.stdout, no_effect, runtime.max_archive_bytes)
        assert restored == expected
        assert await decrypt.wait() == 0
        state.schema_revision = state.archive_revision
        return restored

    def upgrade(dsn):
        state.events.append("migrate")
        if state.failure == "migrate":
            state.failure = None
            raise RuntimeError("injected interrupted legacy migration")
        state.schema_revision = MIGRATION
        return {"migration": MIGRATION}

    monkeypatch.setattr(ops, "Store", Authority)
    monkeypatch.setattr(ops, "DeletionJournal", lambda *args: Journal())
    monkeypatch.setattr(ops, "_runtime", lambda runtime: None)
    monkeypatch.setattr(ops, "_metadata", live_metadata)
    monkeypatch.setattr(ops, "_require_application_defaults", no_effect)
    monkeypatch.setattr(ops, "_require_restore_idle", no_effect)
    monkeypatch.setattr(ops, "_versions", no_effect)
    monkeypatch.setattr(ops, "_copy_encrypted", copy_archive)
    monkeypatch.setattr(ops, "_preflight", preflight)
    monkeypatch.setattr(ops, "_decrypt", decrypt)
    monkeypatch.setattr(ops, "_docker_control", control)
    monkeypatch.setattr(ops, "_restore_transaction", transaction)
    monkeypatch.setattr(ops, "migrate", upgrade)
    private_write(tmp_path / "operator", TOKEN)
    private_write(tmp_path / "identity", "AGE-SECRET-KEY-1" + "A" * 32 + "\n")
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize("published", (False, True))
async def test_restore_fence_write_failure_matches_published_authority_effect(settings, tmp_path, simulated_restore, monkeypatch, published):
    original_write = ops.private_write
    marker = settings.state_dir / "restore-barrier.json"

    def interrupted_write(path, *args, **kwargs):
        if path == marker:
            if published:
                original_write(path, *args, **kwargs)
            raise OSError("injected marker publication failure")
        return original_write(path, *args, **kwargs)

    monkeypatch.setattr(ops, "private_write", interrupted_write)
    with pytest.raises(DomainError) as interrupted:
        await restore(settings, tmp_path / "operator", tmp_path / "archive", tmp_path / "identity",
            "a" * 64, tmp_path / "prepared-operator", settings.deployment_id, BackupRuntime(Path("/not-invoked/age")))
    assert simulated_restore.pg_starts == 0 and marker.exists() == published
    assert interrupted.value.effect == (EffectState.UNKNOWN if published else EffectState.NOT_STARTED)
    assert interrupted.value.code == ("RESTORE_RECOVERY_REQUIRED" if published else "RESTORE_NOT_STARTED")
    assert not (tmp_path / "prepared-operator").exists()
    monkeypatch.setattr(ops, "private_write", original_write)
    if published:
        with pytest.raises(DomainError) as denied:
            with authority_lock(settings):
                pytest.fail("published fence allowed ordinary authority access")
        assert denied.value.code == "RESTORE_RECOVERY_REQUIRED"
        await recover_interrupted_restore(settings, tmp_path / "operator", "a" * 64,
            tmp_path / "recovered-operator", settings.deployment_id, BackupRuntime(Path("/not-invoked/age")))
        assert not marker.exists() and simulated_restore.rotations == 1
    else:
        with authority_lock(settings):
            assert simulated_restore.active_tokens[TOKEN] == "credential_original"
        with pytest.raises(DomainError) as unnecessary:
            await recover_interrupted_restore(settings, tmp_path / "operator", "a" * 64,
                tmp_path / "recovered-operator", settings.deployment_id, BackupRuntime(Path("/not-invoked/age")))
        assert unnecessary.value.code == "RECOVERY_NOT_REQUIRED"
        assert simulated_restore.rotations == 0
        retried = await restore(settings, tmp_path / "operator", tmp_path / "archive", tmp_path / "identity",
            "a" * 64, tmp_path / "prepared-operator", settings.deployment_id, BackupRuntime(Path("/not-invoked/age")))
        assert retried["effect"] == "committed"
        assert simulated_restore.pg_starts == 1 and simulated_restore.rotations == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("published", (False, True))
async def test_fresh_token_publication_failure_keeps_private_recovery_fence(
        settings, tmp_path, simulated_restore, monkeypatch, published):
    output = tmp_path / "prepared-operator"
    original_write = ops.private_write

    def interrupted_write(path, *args, **kwargs):
        if path == output:
            if published:
                original_write(path, *args, **kwargs)
            raise OSError("injected fresh token publication failure")
        return original_write(path, *args, **kwargs)

    with monkeypatch.context() as injected:
        injected.setattr(ops, "private_write", interrupted_write)
        with pytest.raises(DomainError) as interrupted:
            await restore(settings, tmp_path / "operator", tmp_path / "archive", tmp_path / "identity",
                "a" * 64, output, settings.deployment_id, BackupRuntime(Path("/not-invoked/age")))
    assert interrupted.value.effect == EffectState.UNKNOWN
    assert interrupted.value.code == "RESTORE_RECOVERY_REQUIRED"
    assert simulated_restore.pg_starts == 0
    assert output.exists() == published
    if published:
        assert output.read_text().strip() not in simulated_restore.active_tokens
    with pytest.raises(DomainError) as blocked:
        with authority_lock(settings):
            pytest.fail("fresh token failure lifted the authority fence")
    assert blocked.value.code == "RESTORE_RECOVERY_REQUIRED"
    recovered = await recover_interrupted_restore(settings, tmp_path / "operator", "a" * 64,
        tmp_path / "recovered-operator", settings.deployment_id, BackupRuntime(Path("/not-invoked/age")))
    assert recovered["effect"] == "committed"
    assert recovered["archive_replacement"] == "unknown_not_attested"
    assert not (settings.state_dir / "restore-barrier.json").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("published", (False, True))
async def test_real_restore_fence_failure_preserves_exact_retry_or_private_recovery(
        live_authority, binary_runtime, monkeypatch, published):
    store, actor, binding, settings, root = live_authority
    runtime, keygen = binary_runtime
    identity, recipients = age_keys(root, keygen)
    await store.capture(actor, CaptureCommand(binding_id=binding.id, idempotency_key="fence-source",
        origin_key="fence-source", body="Synthetic fence regression.", speaker="human"))
    archive = root / "fence-backup.age"
    await backup(settings, root / "operator", archive, recipients, runtime)
    head = store.journal.verify()["head"]
    await store.close()
    marker = settings.state_dir / "restore-barrier.json"
    output = root / "fresh-operator"
    original_write = ops.private_write

    def interrupted_write(path, *args, **kwargs):
        if path == marker:
            if published:
                original_write(path, *args, **kwargs)
            raise OSError("injected first fence publication failure")
        return original_write(path, *args, **kwargs)

    with monkeypatch.context() as injected:
        injected.setattr(ops, "private_write", interrupted_write)
        with pytest.raises(DomainError) as interrupted:
            await restore(settings, root / "operator", archive, identity, head,
                output, settings.deployment_id, runtime)
    assert marker.exists() == published
    assert not output.exists()
    assert interrupted.value.effect == (EffectState.UNKNOWN if published else EffectState.NOT_STARTED)
    assert interrupted.value.code == ("RESTORE_RECOVERY_REQUIRED" if published else "RESTORE_NOT_STARTED")
    if published:
        with pytest.raises(DomainError) as blocked:
            with authority_lock(settings):
                pytest.fail("published fence allowed ordinary authority")
        assert blocked.value.code == "RESTORE_RECOVERY_REQUIRED"
        recovered = await recover_interrupted_restore(settings, root / "operator", head,
            output, settings.deployment_id, runtime)
        assert recovered["archive_replacement"] == "unknown_not_attested"
    else:
        retried = await restore(settings, root / "operator", archive, identity, head,
            output, settings.deployment_id, runtime)
        assert retried["effect"] == "committed"
    assert not marker.exists()
    await store.open()
    current = await store.authenticate(output.read_text().strip(), (Role.OPERATOR,))
    assert current.id == actor.id
    with pytest.raises(DomainError):
        await store.authenticate(TOKEN, (Role.OPERATOR,))


@pytest.mark.asyncio
async def test_real_cli_backup_restore_and_recovery_rotate_operator(live_authority, binary_runtime):
    from agents_memory import cli

    store, actor, binding, settings, root = live_authority
    runtime, keygen = binary_runtime
    identity, recipients = age_keys(root, keygen)
    config = root / "deployment.json"
    private_write(config, settings.model_dump_json())
    base = ["--config", str(config), "--token-file", str(root / "operator")]
    runtime_arguments = ["--age-binary", str(runtime.age_binary), "--runtime", runtime.mode]
    if runtime.mode == "docker":
        runtime_arguments += ["--docker-binary", str(runtime.docker_binary),
            "--docker-config", str(runtime.docker_config), "--docker-host", runtime.docker_host,
            "--docker-container", runtime.docker_container]
    else:
        runtime_arguments += ["--pg-dump-binary", str(runtime.pg_dump_binary),
            "--pg-restore-binary", str(runtime.pg_restore_binary), "--psql-binary", str(runtime.psql_binary)]
    archive = root / "cli-backup.age"
    backed_up = await cli.execute(cli.parser().parse_args(base + ["backup"] + runtime_arguments
        + ["--output", str(archive), "--recipients-file", str(recipients)]))
    assert backed_up["effect"] == "committed" and archive.stat().st_size > 0
    head = store.journal.verify()["head"]
    await store.close()
    fresh = root / "cli-restored-operator"
    restored = await cli.execute(cli.parser().parse_args(base + ["restore"] + runtime_arguments
        + ["--archive", str(archive), "--identity-file", str(identity), "--expected-head", head,
            "--operator-out", str(fresh), "--confirm-deployment", settings.deployment_id]))
    assert restored["effect"] == "committed" and restored["tokens_rotated"]
    await store.open()
    await store.authenticate(fresh.read_text().strip(), (Role.OPERATOR,))
    with pytest.raises(DomainError):
        await store.authenticate(TOKEN, (Role.OPERATOR,))
    marker = settings.state_dir / "restore-barrier.json"
    private_write(marker, '{"effect":"unknown","code":"RESTORE_RECOVERY_REQUIRED"}')
    head = store.journal.verify()["head"]
    await store.close()
    recovered_output = root / "cli-recovered-operator"
    recovered = await cli.execute(cli.parser().parse_args(["--config", str(config), "--token-file", str(fresh),
        "restore-recover"] + runtime_arguments + ["--expected-head", head, "--operator-out", str(recovered_output),
            "--confirm-deployment", settings.deployment_id]))
    assert recovered["effect"] == "committed"
    assert recovered["archive_replacement"] == "unknown_not_attested"
    assert not marker.exists()
    await store.open()
    await store.authenticate(recovered_output.read_text().strip(), (Role.OPERATOR,))
    with pytest.raises(DomainError):
        await store.authenticate(fresh.read_text().strip(), (Role.OPERATOR,))


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,phase", [("close", "fenced_before_executor"), ("reserve", "executor_may_have_started")])
async def test_restore_preexecutor_failure_reports_unknown_fence_and_is_recoverable(settings, tmp_path, simulated_restore, failure, phase):
    state = simulated_restore
    state.failure = failure
    runtime = BackupRuntime(Path("/not-invoked/age"))
    with pytest.raises(DomainError) as interrupted:
        await restore(settings, tmp_path / "operator", tmp_path / "archive", tmp_path / "identity",
            "a" * 64, tmp_path / "prepared-operator", settings.deployment_id, runtime)
    assert interrupted.value.code == "RESTORE_RECOVERY_REQUIRED"
    assert interrupted.value.effect == EffectState.UNKNOWN
    assert state.pg_starts == 0
    marker = settings.state_dir / "restore-barrier.json"
    assert json.loads(marker.read_text())["effect"] == "unknown"
    assert json.loads(marker.read_text())["phase"] == phase
    with pytest.raises(DomainError) as fenced:
        with authority_lock(settings):
            pytest.fail("authority entered a fenced restore")
    assert fenced.value.code == "RESTORE_RECOVERY_REQUIRED"
    recovered = await recover_interrupted_restore(settings, tmp_path / "operator", "a" * 64,
        tmp_path / "recovered-operator", settings.deployment_id, runtime)
    assert recovered["effect"] == "committed"
    assert recovered["archive_replacement"] == "unknown_not_attested"
    assert recovered["tokens_rotated"] and recovered["rules_need_reapproval"]
    assert recovered["routes_disabled"] and recovered["jobs_fenced"]
    assert state.rotations == 1
    assert not marker.exists()
    assert list(settings.state_dir.glob(".encrypted-ops-*")) == []


@pytest.mark.asyncio
async def test_existing_restore_fence_refuses_a_second_archive_attempt(settings, tmp_path, simulated_restore):
    marker = settings.state_dir / "restore-barrier.json"
    private_write(marker, '{"effect":"unknown","code":"RESTORE_RECOVERY_REQUIRED"}')
    before = marker.read_bytes()
    with pytest.raises(DomainError) as denied:
        await restore(settings, tmp_path / "operator", tmp_path / "archive", tmp_path / "identity",
            "a" * 64, tmp_path / "prepared-operator", settings.deployment_id, BackupRuntime(Path("/not-invoked/age")))
    assert denied.value.code == "RESTORE_RECOVERY_REQUIRED"
    assert simulated_restore.pg_starts == 0
    assert marker.read_bytes() == before
    assert not (tmp_path / "prepared-operator").exists()


@pytest.mark.asyncio
async def test_unobserved_container_executor_blocks_private_recovery(settings, tmp_path, simulated_restore):
    marker = settings.state_dir / "restore-barrier.json"
    private_write(marker, '{"effect":"unknown","code":"RESTORE_RECOVERY_REQUIRED"}')
    simulated_restore.guard = True
    with pytest.raises(DomainError) as denied:
        await recover_interrupted_restore(settings, tmp_path / "operator", "a" * 64,
            tmp_path / "recovered-operator", settings.deployment_id, BackupRuntime(Path("/not-invoked/age")))
    assert denied.value.code == "RESTORE_EXECUTOR_UNOBSERVED"
    assert marker.exists()
    assert simulated_restore.rotations == 0
    assert "migrate" not in simulated_restore.events
    assert not (tmp_path / "recovered-operator").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("interrupt_upgrade", [False, True])
@pytest.mark.parametrize("archive_revision", MIGRATIONS[:-1])
async def test_prior_restore_migrates_before_floor_reconciliation_and_recovers_interrupted_upgrade(settings, tmp_path, simulated_restore, interrupt_upgrade, archive_revision):
    state = simulated_restore
    state.archive_revision = archive_revision
    if interrupt_upgrade:
        state.failure = "migrate"
        with pytest.raises(DomainError) as interrupted:
            await restore(settings, tmp_path / "operator", tmp_path / "archive", tmp_path / "identity",
                "a" * 64, tmp_path / "prepared-operator", settings.deployment_id, BackupRuntime(Path("/not-invoked/age")))
        assert interrupted.value.effect == EffectState.UNKNOWN
        assert state.schema_revision == archive_revision
        assert state.rotations == 0
        result = await recover_interrupted_restore(settings, tmp_path / "operator", "a" * 64,
            tmp_path / "recovered-operator", settings.deployment_id, BackupRuntime(Path("/not-invoked/age")))
        assert result["archive_replacement"] == "unknown_not_attested"
        assert "private_recovery_open" in state.events
    else:
        result = await restore(settings, tmp_path / "operator", tmp_path / "archive", tmp_path / "identity",
            "a" * 64, tmp_path / "prepared-operator", settings.deployment_id, BackupRuntime(Path("/not-invoked/age")))
        expected_versions = list(MIGRATIONS[:MIGRATIONS.index(archive_revision) + 1])
        assert result["migration_versions"] == expected_versions
    assert result["effect"] == "committed"
    assert result["authority_migration_versions"] == list(MIGRATIONS)
    assert state.pg_starts == 1
    assert state.rotations == 1
    assert state.events.index("restore_transaction") < state.events.index("migrate") < state.events.index("authority_recovery")
    assert state.schema_revision == MIGRATION
    assert not (settings.state_dir / "restore-barrier.json").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["dump", "restore", "psql"])
async def test_local_libpq_uses_explicit_empty_password_without_user_pgpass(settings, monkeypatch, kind):
    launched = []
    class Processes:
        async def start(self, argv, *, env, stdout):
            launched.append((argv, env))
            return object()
    monkeypatch.setattr(ops, "_binary", lambda binary: str(binary))
    dsn = "postgresql://memory@127.0.0.1:5432/memory?schema=memory"
    await ops._pg(Processes(), BackupRuntime(Path("/not-invoked/age")), kind, dsn, ["--version"])
    assert launched[0][1]["PGPASSWORD"] == ""
    assert launched[0][1]["PGPASSFILE"] == "/dev/null"
    assert "HOME" not in launched[0][1]


@pytest.mark.asyncio
@pytest.mark.parametrize("action,advance_at", [("restore", "initial"), ("restore", "recovery"), ("recover", "recovery")])
async def test_authenticated_journal_extension_is_carried_to_final_restore_receipt(settings, tmp_path, simulated_restore, action, advance_at):
    state = simulated_restore
    state.advance_at = advance_at
    runtime = BackupRuntime(Path("/not-invoked/age"))
    if action == "restore":
        receipt = await restore(settings, tmp_path / "operator", tmp_path / "archive", tmp_path / "identity",
            "a" * 64, tmp_path / "prepared-operator", settings.deployment_id, runtime)
    else:
        private_write(settings.state_dir / "restore-barrier.json", '{"effect":"unknown","code":"RESTORE_RECOVERY_REQUIRED"}')
        receipt = await recover_interrupted_restore(settings, tmp_path / "operator", "a" * 64,
            tmp_path / "recovered-operator", settings.deployment_id, runtime)
    assert receipt["effect"] == "committed"
    assert receipt["expected_head"] == "a" * 64
    assert receipt["journal_head"] == state.journal_head
    assert receipt["journal_head"] != receipt["expected_head"]
    assert receipt["journal_head_advanced"] is True
    assert state.rotations == 1
    assert not (settings.state_dir / "restore-barrier.json").exists()


@pytest.mark.parametrize("revision", MIGRATIONS)
def test_format_two_archive_accepts_exact_historical_ordered_migration_prefix(settings, revision):
    value = versioned_metadata(settings, revision)
    _validate_metadata(value, settings, "owner_ops")
    value["migration_versions"] = list(reversed(value["migration_versions"])) + ["unrecognized"]
    with pytest.raises(DomainError) as denied:
        _validate_metadata(value, settings, "owner_ops")
    assert denied.value.code == "RESTORE_SCOPE_DENIED"


@pytest.mark.parametrize("helper", ["operations", "private"])
def test_fifo_operator_input_is_refused_without_waiting_for_a_writer(tmp_path, helper):
    import sys

    fifo = tmp_path / "operator-fifo"
    os.mkfifo(fifo, 0o600)
    script = (
        "import sys; from pathlib import Path; "
        "from agents_memory.ops import _read_private; "
        "from agents_memory.private_io import private_read; "
        "from agents_memory.domain import DomainError; "
        "read = _read_private if sys.argv[2] == 'operations' else private_read; "
        "\ntry: read(Path(sys.argv[1]), 4096)"
        "\nexcept DomainError as error: assert error.code == 'PATH_DENIED'"
        "\nelse: raise AssertionError('FIFO was accepted')"
    )
    subprocess.run([sys.executable, "-c", script, str(fifo), helper], check=True, timeout=5)


@pytest.mark.asyncio
async def test_oversized_restore_toc_aborts_and_drains_real_child_before_wait_deadlock(settings, tmp_path, monkeypatch):
    import sys

    value = metadata(settings)
    encoded = json.dumps(value).encode()
    dump = b"PGDMPbounded-preflight-input"
    envelope = _MAGIC + struct.pack("!I", len(encoded)) + encoded + framed_dump(dump)
    children = []

    async def decrypt(*args):
        async def exited():
            return 0
        return SimpleNamespace(stdout=reader(envelope), wait=exited)

    async def pg(processes, runtime, kind, dsn, args, **kwargs):
        assert args == ["--list"]
        script = "import sys; sys.stdout.buffer.write(b'x' * (2 * 1024**2)); sys.stdout.buffer.flush(); sys.stdin.buffer.read()"
        process = await processes.start([sys.executable, "-c", script])
        children.append(process)
        return process

    monkeypatch.setattr(ops, "_decrypt", decrypt)
    monkeypatch.setattr(ops, "_pg", pg)
    async def preflight():
        async with ops._processes() as processes:
            return await ops._preflight(processes, BackupRuntime(Path("/not-invoked/age")), settings,
                tmp_path / "archive.age", b"private-identity-not-forwarded", "owner_ops", listing=True)
    with pytest.raises(DomainError) as denied:
        await asyncio.wait_for(preflight(), timeout=5)
    assert denied.value.code == "OPERATIONS_OUTPUT_TOO_LARGE"
    assert children and all(child.returncode is not None for child in children)


@pytest.mark.asyncio
@pytest.mark.parametrize("revision,format_version", [(MIGRATIONS[0], 1), *((revision, 2) for revision in MIGRATIONS)])
@pytest.mark.parametrize("pollution", [None, "missing_source", "foreign_table", "wrong_selection_shape"])
async def test_dump_preflight_accepts_only_complete_revision_matched_authority(
        settings, tmp_path, monkeypatch, revision, format_version, pollution):
    value = legacy_metadata(settings) if format_version == 1 else versioned_metadata(settings, revision)
    tables = set(ops._ARCHIVE_TABLES[revision])
    if pollution == "missing_source":
        tables.remove("am_sources")
    elif pollution == "foreign_table":
        tables.add("private_foreign_evidence")
    elif pollution == "wrong_selection_shape":
        if "am_source_selections" in tables:
            tables.remove("am_source_selections")
        else:
            tables.add("am_source_selections")
    toc = "\n".join(f"{number}; 0 0 {kind} memory {table} memory"
        for number, (table, kind) in enumerate(
            ((table, kind) for table in sorted(tables) for kind in ("TABLE", "TABLE DATA")), 1)).encode()
    if revision in {"0006_agent_judged", "0007_memory_health", "0008_judge_escalations"}:
        toc += (b"\n900; 0 0 SEQUENCE memory am_pending_judgments_sequence_seq memory"
            b"\n901; 0 0 SEQUENCE SET memory am_pending_judgments_sequence_seq memory"
            b"\n902; 0 0 SEQUENCE memory am_claims_cleanup_sequence_seq memory"
            b"\n903; 0 0 SEQUENCE SET memory am_claims_cleanup_sequence_seq memory")
    header = json.dumps(value).encode()
    envelope = _MAGIC + struct.pack("!I", len(header)) + header + framed_dump(b"PGDMPvalidated-old-shape")
    class Input:
        def write(self, raw):
            pass
        async def drain(self):
            pass
        def close(self):
            pass
    async def exited():
        return 0
    async def decrypt(*args):
        return SimpleNamespace(stdout=reader(envelope), wait=exited)
    async def pg(*args, **kwargs):
        return SimpleNamespace(stdout=reader(toc), stdin=Input(), wait=exited)
    monkeypatch.setattr(ops, "_decrypt", decrypt)
    monkeypatch.setattr(ops, "_pg", pg)
    if pollution is None:
        archived, checked = await ops._preflight(object(), BackupRuntime(Path("/not-invoked/age")), settings,
            tmp_path / "archive.age", b"private-identity", "owner_ops", listing=True)
        assert archived == value and checked["dump_bytes"] == len(b"PGDMPvalidated-old-shape")
        return
    with pytest.raises(DomainError) as denied:
        await ops._preflight(object(), BackupRuntime(Path("/not-invoked/age")), settings,
            tmp_path / "archive.age", b"private-identity", "owner_ops", listing=True)
    assert denied.value.code == "ARCHIVE_SCOPE_DENIED"
    assert denied.value.effect == EffectState.NOT_STARTED


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "producer_failure", "cancel", "invalid_envelope"])
async def test_streamed_sql_transaction_commits_only_after_complete_upstream_success(
        settings, tmp_path, monkeypatch, outcome):
    import sys

    dump = b"PGDMPsynthetic-transaction-boundary"
    checked = {"dump_sha256": hashlib.sha256(dump).hexdigest(), "dump_bytes": len(dump)}
    envelope = framed_dump(dump)
    if outcome == "invalid_envelope":
        envelope = envelope[:-1]
    async def decrypted():
        return 0
    decrypt = SimpleNamespace(stdout=reader(envelope), wait=decrypted)
    marker = tmp_path / "commit-observed"
    children = []
    writes = []
    original_write = ops._write

    async def record_write(process, raw):
        writes.append(len(raw))
        await original_write(process, raw)

    async def pg(processes, runtime, kind, dsn, args, **kwargs):
        if kind == "psql":
            assert args == ["--no-psqlrc", "--set=ON_ERROR_STOP=1", "--file=-"]
            script = (
                "import sys; from pathlib import Path; tail=b''"
                "\nwhile chunk := sys.stdin.buffer.read(65536):"
                "\n tail=(tail+chunk)[-64:]"
                "\n if b'\\nCOMMIT;\\n' in tail: Path(sys.argv[1]).write_text('commit-observed')"
            )
            argv = [sys.executable, "-c", script, str(marker)]
        else:
            assert kind == "restore" and "--file=-" in args and "--clean" in args
            assert not any(arg.startswith("--dbname") for arg in args)
            script = (
                "import sys,time; sys.stdout.buffer.write(b'x'*(2*1024**2));"
                "sys.stdout.buffer.flush(); sys.stdin.buffer.read();"
                + ("time.sleep(60);" if outcome == "cancel" else "")
                + ("sys.exit(7)" if outcome == "producer_failure" else "sys.exit(0)")
            )
            argv = [sys.executable, "-c", script]
        process = await processes.start(argv, **kwargs)
        children.append(process)
        return process

    monkeypatch.setattr(ops, "_pg", pg)
    monkeypatch.setattr(ops, "_write", record_write)

    async def transaction():
        async with ops._processes() as processes:
            return await ops._restore_transaction(processes, BackupRuntime(Path("/not-invoked/age")),
                settings.migrator_dsn, metadata(settings), decrypt, checked)

    if outcome == "success":
        assert await asyncio.wait_for(transaction(), timeout=5) == checked
        assert marker.read_text() == "commit-observed"
    else:
        expected = TimeoutError if outcome == "cancel" else (
            asyncio.IncompleteReadError if outcome == "invalid_envelope" else DomainError)
        with pytest.raises(expected):
            await asyncio.wait_for(transaction(), timeout=1 if outcome == "cancel" else 5)
        assert not marker.exists()
    assert children and all(child.returncode is not None for child in children)
    assert writes and max(writes) <= ops._CHUNK


@pytest.mark.asyncio
@pytest.mark.parametrize("psql_identity", ["psql (PostgreSQL) 17.6", "pg_dump (PostgreSQL) 18.6"])
async def test_psql_version_or_executable_mismatch_is_rejected_before_restore_executor(settings, monkeypatch, psql_identity):
    kinds = []
    async def pg(processes, runtime, kind, dsn, args):
        kinds.append(kind)
        assert args == ["--version"]
        class Input:
            def close(self):
                pass
        async def exited():
            return 0
        identity = {"dump": "pg_dump (PostgreSQL) 18.6",
            "restore": "pg_restore (PostgreSQL) 18.6", "psql": psql_identity}[kind]
        return SimpleNamespace(stdin=Input(), stdout=reader((identity + "\n").encode()), wait=exited)
    monkeypatch.setattr(ops, "_pg", pg)
    with pytest.raises(DomainError) as denied:
        await ops._versions(object(), BackupRuntime(Path("/not-invoked/age")), settings.migrator_dsn)
    assert kinds == ["dump", "restore", "psql"]
    assert denied.value.code == "DATABASE_VERSION_UNSUPPORTED"
    assert denied.value.effect == EffectState.NOT_STARTED


@pytest.mark.asyncio
@pytest.mark.parametrize("published", (False, True))
async def test_explicit_cli_config_upgrade_preserves_original_when_publication_is_uncertain(
        live_authority, monkeypatch, published):
    from agents_memory import cli
    from agents_memory.config import load_settings

    store, actor, _, settings, root = live_authority
    config = root / "legacy-config.json"
    original = json.dumps({**settings.model_dump(mode="json"), "capability": "full_semantic",
                           "models": {}, "allowed_model_purposes": []}).encode()
    private_write(config, original)
    head = store.journal.verify()["head"]
    await store.close()
    write = ops.private_write

    def interrupted(path, content, **options):
        if path == config and options.get("replace"):
            if published:
                write(path, content, **options)
            raise OSError("Synthetic uncertain config publication")
        return write(path, content, **options)

    args = cli.parser().parse_args([
        "--config", str(config), "--token-file", str(root / "operator"), "migrate",
        "--upgrade-config", "--confirm-deployment", settings.deployment_id,
    ])
    monkeypatch.setattr(ops, "private_write", interrupted)
    with pytest.raises(DomainError) as uncertain:
        await cli.execute(args)
    assert uncertain.value.code == "CONFIG_UPGRADE_RECOVERY_REQUIRED"
    assert uncertain.value.effect == EffectState.UNKNOWN
    retained = settings.state_dir / ("config-upgrade-" + hashlib.sha256(original).hexdigest() + ".json")
    assert retained.read_bytes() == original
    if not published:
        assert config.read_bytes() == original
        with pytest.raises(DomainError) as obsolete:
            load_settings(config)
        assert obsolete.value.code == "CONFIG_UPGRADE_REQUIRED"
    else:
        assert load_settings(config) == settings
    monkeypatch.setattr(ops, "private_write", write)
    repaired = await cli.execute(args)
    assert repaired["effect"] == "committed" and repaired["config_upgraded"]
    assert load_settings(config) == settings and retained.read_bytes() == original
    await store.open()
    current = await store.authenticate(TOKEN, (Role.OPERATOR,))
    assert current.credential_id == actor.credential_id
    assert store.journal.verify()["head"] == head


@pytest.mark.asyncio
@pytest.mark.parametrize("protected", (
    "authority.lock", "restore-barrier.json", "initialization-intent.json", "initialization-result.json",
))
async def test_config_upgrade_cannot_replace_authority_interlocks_or_initialization_evidence(settings, tmp_path, protected):
    settings = settings.model_copy(update={"migrator_dsn": settings.database_dsn})
    settings.state_dir.mkdir(mode=0o700)
    path = settings.state_dir / protected
    original = settings.model_dump_json().encode()
    private_write(path, original)
    with pytest.raises(DomainError) as denied:
        await ops.migrate_authority(settings, tmp_path / "not-read-token", settings.deployment_id,
                                     config_path=path, original_config=original)
    assert denied.value.code == "PATH_DENIED" and denied.value.effect == EffectState.NOT_STARTED
    assert path.read_bytes() == original


def pending_model_approval(settings):
    raw = (
        json.dumps({
            "format": 1,
            "request": "1" * 64,
            "before": "2" * 64,
            "target": "3" * 64,
        }, indent=2) + "\n"
    ).encode()
    private_write(settings.state_dir / "model-approval-intent.json", raw)
    return raw, hashlib.sha256(raw).hexdigest()


@pytest.mark.asyncio
@pytest.mark.parametrize("historical_index", (3, 4))
@pytest.mark.parametrize("interruption", (None, "migration", "retirement"))
async def test_real_historical_approval_retirement_preserves_unknown_evidence_and_restarts(
    live_authority, monkeypatch, historical_index, interruption,
):
    from test_store_authority import historical_schema_fixture

    from agents_memory import cli

    store, actor, binding, settings, root = live_authority
    async with store.pool.acquire() as connection:
        await connection.execute(
            "INSERT INTO am_routes(purpose,revision,enabled,epoch) VALUES('extraction',$1,true,7)",
            "f" * 64,
        )
        credentials = await connection.fetch("SELECT * FROM am_credentials ORDER BY id")
    raw, digest = pending_model_approval(settings)
    await historical_schema_fixture(store, historical_index)
    await store.close()

    config = root / "deployment.json"
    original = json.dumps({
        **settings.model_dump(mode="json"),
        "capability": "full_semantic",
        "models": {},
        "allowed_model_purposes": ["extraction"],
        "lease_seconds": 120,
        "heartbeat_seconds": 10,
        "job_attempt_limit": 4,
    }).encode()
    private_write(config, original)

    original_migrate = ops.migrate
    original_finish = ops._finish_model_approval_recovery
    fired = False

    def interrupted_migrate(dsn):
        nonlocal fired
        result = original_migrate(dsn)
        if interruption == "migration" and not fired:
            fired = True
            raise OSError("deterministic lost committed migration response")
        return result

    def interrupted_finish(current_settings, confirmed_digest, confirmed_raw):
        nonlocal fired
        original_finish(current_settings, confirmed_digest, confirmed_raw)
        if interruption == "retirement" and not fired:
            fired = True
            raise OSError("deterministic lost retirement response")

    monkeypatch.setattr(ops, "migrate", interrupted_migrate)
    monkeypatch.setattr(ops, "_finish_model_approval_recovery", interrupted_finish)
    argv = [
        "--config", str(config), "--token-file", str(root / "operator"),
        "migrate", "--confirm-deployment", settings.deployment_id,
        "--upgrade-config", "--retire-model-approval-intent", digest,
    ]
    if interruption is not None:
        with pytest.raises(DomainError) as uncertain:
            await cli.execute(cli.parser().parse_args(argv))
        assert uncertain.value.effect == EffectState.UNKNOWN

    result = await cli.execute(cli.parser().parse_args(argv))
    assert result["application_verified"] and result["model_approval_retired"]
    assert result["historical_approval_effect"] == "unknown_not_attested"
    assert result["routes_disabled"]
    assert not (settings.state_dir / "model-approval-intent.json").exists()
    retained = settings.state_dir / ("model-approval-retired-" + digest + ".json")
    assert retained.read_bytes() == raw
    audit = json.loads((settings.state_dir / ("model-approval-recovery-" + digest + ".json")).read_bytes())
    assert audit["migration_before_recovery"] == MIGRATIONS[historical_index]
    assert audit["historical_approval_effect"] == "unknown_not_attested"
    assert audit["routes_before_recovery"] == [{
        "purpose": "extraction", "revision": "f" * 64, "enabled": True, "epoch": 7,
    }]
    assert retained.stat().st_mode & 0o077 == 0
    assert (root / "operator").read_text() == TOKEN

    await store.open()
    await store.reconcile_journal()
    current = await store.authenticate(TOKEN, (Role.OPERATOR,))
    assert current.credential_id == actor.credential_id
    async with store.pool.acquire() as connection:
        assert not await connection.fetchval("SELECT EXISTS(SELECT 1 FROM am_routes WHERE enabled)")
        assert await connection.fetch("SELECT * FROM am_credentials ORDER BY id") == credentials
    replay = await cli.execute(cli.parser().parse_args(argv))
    assert replay["application_verified"] is True and replay["model_approval_retired"] is True
    assert retained.read_bytes() == raw


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ("ordinary", "wrong_operator", "wrong_digest", "busy", "approval_busy"))
async def test_model_approval_refusal_leaves_evidence_routes_and_revision_unchanged(
    live_authority, case,
):
    from test_store_authority import historical_schema_fixture

    store, actor, binding, settings, root = live_authority
    agent_token = "approval-recovery-agent-" + "a" * 40
    await store.issue_token(actor, Role.AGENT, (binding.id,), agent_token)
    private_write(root / "agent", agent_token)
    raw, digest = pending_model_approval(settings)
    async with store.pool.acquire() as connection:
        await connection.execute(
            "INSERT INTO am_routes(purpose,revision,enabled,epoch) VALUES('extraction',$1,true,9)",
            "f" * 64,
        )
    await historical_schema_fixture(store, 3)
    async with store.pool.acquire() as connection:
        routes = await connection.fetch("SELECT * FROM am_routes ORDER BY purpose")
        epoch = await connection.fetchval("SELECT epoch FROM am_clock WHERE singleton")
    await store.close()

    kwargs = {}
    token_file = root / "operator"
    if case != "ordinary":
        kwargs["retire_model_approval_intent"] = "0" * 64 if case == "wrong_digest" else digest
    if case == "wrong_operator":
        token_file = root / "agent"

    async def refuse():
        with pytest.raises(DomainError) as denied:
            await ops.migrate_authority(settings, token_file, settings.deployment_id, **kwargs)
        assert denied.value.effect == EffectState.NOT_STARTED
        expected = {
            "ordinary": "UPGRADE_RECOVERY_REQUIRED",
            "wrong_operator": "SCOPE_DENIED",
            "wrong_digest": "MODEL_APPROVAL_RECOVERY_CONFLICT",
            "busy": "AUTHORITY_BUSY",
            "approval_busy": "MODEL_APPROVAL_BUSY",
        }
        assert denied.value.code == expected[case]

    if case == "busy":
        with authority_lock(settings):
            await refuse()
    elif case == "approval_busy":
        with ops._model_approval_recovery_lock(settings):
            await refuse()
    else:
        await refuse()
    assert (settings.state_dir / "model-approval-intent.json").read_bytes() == raw
    assert not list(settings.state_dir.glob("model-approval-retired-*.json"))
    assert not list(settings.state_dir.glob("model-approval-recovery-*.json"))

    private = Store(
        settings.model_copy(update={"database_dsn": settings.migrator_dsn}),
        store.journal,
    )
    try:
        await private.open_restore_recovery()
        async with private.pool.acquire() as connection:
            assert await connection.fetchval("SELECT version_num FROM alembic_version") == MIGRATIONS[3]
            assert await connection.fetch("SELECT * FROM am_routes ORDER BY purpose") == routes
            assert await connection.fetchval("SELECT epoch FROM am_clock WHERE singleton") == epoch
    finally:
        await private.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("historical_index", (3, 4))
async def test_forward_migration_activates_only_candidate_rejection_feedback(
    live_authority, historical_index,
):
    from test_store_authority import historical_schema_fixture

    from agents_memory.domain import FeedbackCommand

    store, actor, binding, settings, root = live_authority
    source = await store.capture(
        actor,
        CaptureCommand(
            binding_id=binding.id,
            idempotency_key="historical-reject-source",
            origin_key="historical-reject-source",
            body="Original human evidence requiring rejection preservation.",
            speaker="human",
        ),
    )
    rejection = await store.feedback(
        actor,
        FeedbackCommand(
            binding_id=binding.id,
            idempotency_key="historical-reject",
            target_ref=source.id,
            kind="reject",
            body="Do not reuse this original human evidence.",
        ),
    )
    async with store.pool.acquire() as connection:
        await connection.execute(
            "UPDATE am_feedback SET state='candidate' WHERE id=$1",
            rejection.artifact_id,
        )
        await connection.execute(
            """INSERT INTO am_feedback(id,binding_id,target_ref,kind,state)
               VALUES('historical_retracted',$1,$2,'reject','retracted')""",
            binding.id, source.id,
        )
    correction = await store.feedback(actor, FeedbackCommand(
        binding_id=binding.id, idempotency_key="historical-correction",
        target_ref=source.id, kind="correct", body="A retained correction is not a rejection.",
    ))
    async with store.pool.acquire() as connection:
        await connection.execute("UPDATE am_feedback SET state='candidate' WHERE id=$1", correction.artifact_id)
        await connection.execute(
            "DELETE FROM am_pending_judgments WHERE binding_id=$1 AND kind='health' AND health_key=$2",
            binding.id, "feedback:" + correction.artifact_id)
    await historical_schema_fixture(store, historical_index)
    await store.close()
    result = await ops.migrate_authority(
        settings, root / "operator", settings.deployment_id,
    )
    assert result["previous_migration"] == MIGRATIONS[historical_index]
    await store.open()
    await store.reconcile_journal()
    async with store.pool.acquire() as connection:
        assert await connection.fetchval(
            "SELECT state FROM am_feedback WHERE id=$1", rejection.artifact_id,
        ) == "active"
        assert await connection.fetchval(
            "SELECT state FROM am_feedback WHERE id='historical_retracted'",
        ) == "retracted"
        assert await connection.fetchval(
            "SELECT state FROM am_feedback WHERE id=$1", correction.artifact_id,
        ) == "candidate"
        retained = await connection.fetchrow(
            "SELECT reason,rejected_source_ids FROM am_feedback WHERE id=$1",
            rejection.artifact_id,
        )
        assert retained["reason"] == "Do not reuse this original human evidence."
        assert retained["rejected_source_ids"] == [source.source_id]
    disclosed = await store.inspect(actor, binding.id, rejection.artifact_id)
    assert disclosed["reason"] == retained["reason"]


@pytest.mark.asyncio
async def test_pending_model_approval_preflight_refusal_is_not_started(live_authority):
    store, actor, binding, settings, root = live_authority
    raw, _ = pending_model_approval(settings)
    async with store.pool.acquire() as connection:
        before = await connection.fetchval("SELECT epoch FROM am_clock WHERE singleton")
    with pytest.raises(DomainError) as caught:
        await ops.migrate_authority(settings, root / "operator", settings.deployment_id)
    assert caught.value.code == "UPGRADE_RECOVERY_REQUIRED"
    assert caught.value.effect == EffectState.NOT_STARTED
    assert (settings.state_dir / "model-approval-intent.json").read_bytes() == raw
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT epoch FROM am_clock WHERE singleton") == before


@pytest.mark.asyncio
async def test_cancelled_migration_fences_service_until_real_thread_stops_and_explicit_recovery(live_authority, monkeypatch):
    from test_store_authority import historical_schema_fixture

    store, _, _, settings, root = live_authority
    await historical_schema_fixture(store, 4)
    await store.close()
    config = root / "cancelled-upgrade.json"
    original = json.dumps({**settings.model_dump(mode="json"), "capability": "full_semantic", "models": {}}).encode()
    private_write(config, original)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    actual_migrate = ops.migrate

    def gated_migrate(dsn):
        entered.set()
        try:
            if not release.wait(15):
                raise TimeoutError("The test did not release its owned migration worker")
            return actual_migrate(dsn)
        finally:
            finished.set()

    monkeypatch.setattr(ops, "migrate", gated_migrate)
    task = asyncio.create_task(ops.migrate_authority(
        settings, root / "operator", settings.deployment_id, config_path=config, original_config=original,
    ))
    try:
        assert await asyncio.to_thread(entered.wait, 15)
        for _ in range(2):
            task.cancel()
            await asyncio.sleep(0)
            with pytest.raises(DomainError) as busy:
                with authority_lock(settings):
                    pytest.fail("A service entered while the cancelled migration worker was still alive")
            assert busy.value.code == "AUTHORITY_BUSY"
        release.set()
        with pytest.raises(DomainError) as interrupted:
            await task
        assert interrupted.value.code == "MIGRATION_UNVERIFIED" and interrupted.value.effect == EffectState.UNKNOWN
        assert finished.is_set()
        with pytest.raises(DomainError) as fenced:
            with authority_lock(settings):
                pytest.fail("A service entered before the cancelled migration was verified")
        assert fenced.value.code == "RESTORE_RECOVERY_REQUIRED"
        assert config.read_bytes() == original
        monkeypatch.setattr(ops, "migrate", actual_migrate)
        recovered = await ops.migrate_authority(
            settings, root / "operator", settings.deployment_id, config_path=config, original_config=original,
        )
        assert recovered["effect"] == "committed" and recovered["application_verified"]
        with authority_lock(settings):
            await store.open()
            current = await store.authenticate(TOKEN, (Role.OPERATOR,))
            assert current.realm == settings.realm
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        assert await asyncio.to_thread(finished.wait, 15)


@pytest.mark.asyncio
async def test_uncertain_migration_fence_refuses_other_actor_request_and_restore_recovery(live_authority, monkeypatch):
    from test_store_authority import historical_schema_fixture

    store, actor, binding, settings, root = live_authority
    agent_token = "migration-fence-agent-" + "a" * 40
    await store.issue_token(actor, Role.AGENT, (binding.id,), agent_token)
    private_write(root / "agent", agent_token)
    await historical_schema_fixture(store, 4)
    await store.close()
    config = root / "uncertain-upgrade.json"
    original = json.dumps({**settings.model_dump(mode="json"), "capability": "full_semantic", "models": {}}).encode()
    private_write(config, original)
    actual_migrate = ops.migrate

    def lost_result(dsn):
        actual_migrate(dsn)
        raise OSError("The committed migration response was lost")

    monkeypatch.setattr(ops, "migrate", lost_result)
    with pytest.raises(DomainError) as uncertain:
        await ops.migrate_authority(
            settings, root / "operator", settings.deployment_id, config_path=config, original_config=original,
        )
    assert uncertain.value.code == "MIGRATION_UNVERIFIED" and uncertain.value.effect == EffectState.UNKNOWN
    with pytest.raises(DomainError) as fenced:
        with authority_lock(settings):
            pytest.fail("The unknown migration allowed ordinary authority use")
    assert fenced.value.code == "RESTORE_RECOVERY_REQUIRED"
    marker = settings.state_dir / "restore-barrier.json"
    retained_marker = marker.read_bytes()
    with pytest.raises(DomainError) as denied:
        await ops.migrate_authority(
            settings, root / "agent", settings.deployment_id, config_path=config, original_config=original,
        )
    assert denied.value.code == "SCOPE_DENIED" and denied.value.effect == EffectState.NOT_STARTED
    other = root / "other-config.json"
    private_write(other, original)
    with pytest.raises(DomainError) as conflict:
        await ops.migrate_authority(
            settings, root / "operator", settings.deployment_id, config_path=other, original_config=original,
        )
    assert conflict.value.code == "MIGRATION_RECOVERY_CONFLICT" and conflict.value.effect == EffectState.NOT_STARTED
    with pytest.raises(DomainError) as wrong_recovery:
        await recover_interrupted_restore(
            settings, root / "operator", store.journal.verify()["head"], root / "not-created-token",
            settings.deployment_id, BackupRuntime(Path("/not-invoked/age")),
        )
    assert wrong_recovery.value.code == "MIGRATION_RECOVERY_REQUIRED"
    assert wrong_recovery.value.effect == EffectState.NOT_STARTED
    assert marker.read_bytes() == retained_marker and not (root / "not-created-token").exists()
    assert config.read_bytes() == original and other.read_bytes() == original
    monkeypatch.setattr(ops, "migrate", actual_migrate)
    recovered = await ops.migrate_authority(
        settings, root / "operator", settings.deployment_id, config_path=config, original_config=original,
    )
    assert recovered["application_verified"] and recovered["effect"] == "committed"
    assert not marker.exists()
    await store.open()
    current = await store.authenticate(TOKEN, (Role.OPERATOR,))
    assert current.credential_id == actor.credential_id


@pytest.mark.asyncio
@pytest.mark.parametrize("published", (False, True))
async def test_uncertain_config_migration_keeps_consumer_fence_until_original_bound_recovery(
    live_authority, monkeypatch, published,
):
    from agents_memory import cli
    from agents_memory.config import load_settings

    store, actor, _, settings, root = live_authority
    await store.close()
    config = root / "fenced-config.json"
    original = json.dumps({**settings.model_dump(mode="json"), "capability": "full_semantic", "models": {}}).encode()
    private_write(config, original)
    write = ops.private_write

    def interrupted(path, content, **options):
        if path == config and options.get("replace"):
            if published:
                write(path, content, **options)
            raise OSError("The configuration publication response was lost")
        return write(path, content, **options)

    arguments = cli.parser().parse_args([
        "--config", str(config), "--token-file", str(root / "operator"), "migrate",
        "--upgrade-config", "--confirm-deployment", settings.deployment_id,
    ])
    monkeypatch.setattr(ops, "private_write", interrupted)
    with pytest.raises(DomainError) as uncertain:
        await cli.execute(arguments)
    assert uncertain.value.code == "CONFIG_UPGRADE_RECOVERY_REQUIRED" and uncertain.value.effect == EffectState.UNKNOWN
    with pytest.raises(DomainError) as fenced:
        with authority_lock(settings):
            pytest.fail("A consumer entered after an unverified configuration publication")
    assert fenced.value.code == "RESTORE_RECOVERY_REQUIRED"
    retained = settings.state_dir / ("config-upgrade-" + hashlib.sha256(original).hexdigest() + ".json")
    assert retained.read_bytes() == original
    monkeypatch.setattr(ops, "private_write", write)
    recovered = await cli.execute(arguments)
    assert recovered["effect"] == "committed" and recovered["application_verified"]
    assert load_settings(config) == settings and retained.read_bytes() == original
    with authority_lock(settings):
        await store.open()
        current = await store.authenticate(TOKEN, (Role.OPERATOR,))
        assert current.credential_id == actor.credential_id


class LiveDatabase:
    def __init__(self, settings, version, vector):
        self.settings, self.version, self.vector = settings, version, vector

    async def fetchval(self, query):
        if "server_version_num" in query:
            return str(self.version)
        if "extversion" in query:
            return self.vector
        return MIGRATION

    async def fetchrow(self, query):
        return {"deployment_id": self.settings.deployment_id, "realm": self.settings.realm, "journal_head": "b" * 64}


@pytest.mark.asyncio
@pytest.mark.parametrize("version,vector,expected", [
    (180006, "0.8.7", ("18.6", "0.8.7")), (180007, "0.8.8", ("18.7", "0.8.8")), (180012, "0.9.0", ("18.12", "0.9.0")),
])
async def test_backup_accepts_the_serving_contract_and_records_live_versions(settings, version, vector, expected):
    store = SimpleNamespace(settings=settings)
    live = await ops._metadata(store, LiveDatabase(settings, version, vector),
        BackupRuntime(Path("/not-invoked/age")), SimpleNamespace(id="owner_ops"))
    assert (live["postgres_version"], live["vector_version"]) == expected
    archived = metadata(settings) | {"postgres_version": expected[0], "vector_version": expected[1]}
    _validate_metadata(archived, settings, "owner_ops")


@pytest.mark.asyncio
@pytest.mark.parametrize("version,vector", [(170009, "0.8.7"), (190000, "0.8.7"), (180006, "0.8.6"), (180006, None), (180006, "0.8")])
async def test_unsupported_live_database_is_refused_before_backup_effects(settings, version, vector):
    with pytest.raises(DomainError) as denied:
        await ops._metadata(SimpleNamespace(settings=settings), LiveDatabase(settings, version, vector),
            BackupRuntime(Path("/not-invoked/age")), SimpleNamespace(id="owner_ops"))
    assert (denied.value.code, denied.value.effect) == ("DATABASE_VERSION_UNSUPPORTED", EffectState.NOT_STARTED)


@pytest.mark.parametrize("key,value", [
    ("postgres_version", "19.0"), ("postgres_version", "18"), ("postgres_version", "18.6.1"),
    ("vector_version", "0.8.6"), ("vector_version", "0.8"),
])
def test_unsupported_archive_versions_are_refused_before_restore(settings, key, value):
    with pytest.raises(DomainError) as denied:
        _validate_metadata(metadata(settings) | {key: value}, settings, "owner_ops")
    assert (denied.value.code, denied.value.effect) == ("DATABASE_VERSION_UNSUPPORTED", EffectState.NOT_STARTED)


@pytest.mark.parametrize("identity,accepted", [
    (b"pg_dump (PostgreSQL) 18.7\n", True), (b"pg_dump (PostgreSQL) 18.12 (Homebrew)\n", True),
    (b"pg_dump (PostgreSQL) 17.6\n", False), (b"pg_restore (PostgreSQL) 18.7\n", False), (b"pg_dump (PostgreSQL) 18\n", False),
])
def test_operation_tools_share_the_supported_major(identity, accepted):
    from agents_memory.database import require_tool
    if accepted:
        assert require_tool("pg_dump", identity).startswith("18.")
    else:
        with pytest.raises(DomainError) as denied:
            require_tool("pg_dump", identity)
        assert (denied.value.code, denied.value.effect) == ("DATABASE_VERSION_UNSUPPORTED", EffectState.NOT_STARTED)


async def unsupported_tools(*args):
    raise DomainError("DATABASE_VERSION_UNSUPPORTED", "synthetic unsupported tools")


@pytest.mark.asyncio
@pytest.mark.parametrize("unsupported", ["tools", "live_server"])
async def test_backup_refuses_unsupported_versions_before_staging_recipients_or_journal(settings, tmp_path, monkeypatch, unsupported):
    events = []

    class Authority:
        def __init__(self, selected, journal):
            self.settings = selected

        async def open(self):
            events.append("open")
            if unsupported == "live_server":
                raise DomainError("DATABASE_VERSION_UNSUPPORTED", "synthetic unsupported live server")

        async def reconcile_journal(self, expected=None):
            events.append("journal_reconcile")

        async def close(self):
            return None

    async def supported_tools(*args):
        return None

    real_staging = ops._staging

    def staging(selected):
        events.append("staging")
        return real_staging(selected)

    monkeypatch.setattr(ops, "Store", Authority)
    monkeypatch.setattr(ops, "DeletionJournal", lambda *args: object())
    monkeypatch.setattr(ops, "_runtime", lambda runtime: None)
    monkeypatch.setattr(ops, "_staging", staging)
    monkeypatch.setattr(ops, "_versions", unsupported_tools if unsupported == "tools" else supported_tools)
    # A recipients file that does not exist would fail differently if it were read first.
    with pytest.raises(DomainError) as denied:
        await backup(settings, tmp_path / "operator", tmp_path / "backup.age", tmp_path / "missing-recipients",
            BackupRuntime(Path("/not-invoked/age")))
    assert (denied.value.code, denied.value.effect) == ("DATABASE_VERSION_UNSUPPORTED", EffectState.NOT_STARTED)
    assert events == ([] if unsupported == "tools" else ["open"])


@pytest.mark.asyncio
@pytest.mark.parametrize("unsupported", ["tools", "archive"])
async def test_restore_refuses_unsupported_versions_before_journal_reconcile_or_fence(settings, tmp_path, monkeypatch, simulated_restore, unsupported):
    if unsupported == "tools":
        monkeypatch.setattr(ops, "_versions", unsupported_tools)
    else:
        async def old_archive(processes, runtime, selected, archive, identity, owner, *, listing):
            dump = b"PGDMPsynthetic-parser-stream"
            return metadata(settings) | {"postgres_version": "17.6"}, {
                "dump_sha256": hashlib.sha256(dump).hexdigest(), "dump_bytes": len(dump)}
        monkeypatch.setattr(ops, "_preflight", old_archive)
    with pytest.raises(DomainError) as denied:
        await restore(settings, tmp_path / "operator", tmp_path / "archive", tmp_path / "identity",
            "a" * 64, tmp_path / "prepared-operator", settings.deployment_id, BackupRuntime(Path("/not-invoked/age")))
    assert (denied.value.code, denied.value.effect) == ("DATABASE_VERSION_UNSUPPORTED", EffectState.NOT_STARTED)
    assert simulated_restore.journal_rechecks == 0 and "journal_reconcile" not in simulated_restore.events
    assert simulated_restore.pg_starts == 0
    assert not (settings.state_dir / "restore-barrier.json").exists()


@pytest.mark.asyncio
async def test_real_backup_dump_failure_preserves_primary_and_removes_staging_despite_close_failure(live_authority, binary_runtime, monkeypatch):
    store, actor, binding, settings, root = live_authority
    runtime, keygen = binary_runtime
    _, recipients = age_keys(root, keygen)
    for source_index in range(8):
        body = "\n".join("Synthetic dump row: " + hashlib.sha256(
            f"{source_index}:{row}".encode()).hexdigest() for row in range(512))
        await store.capture(actor, CaptureCommand(binding_id=binding.id,
            idempotency_key=f"dump-bound-{source_index}", origin_key=f"dump-bound-{source_index}", body=body, speaker="human"))
    directory = root / "failed-backup"
    directory.mkdir(mode=0o700)
    archive = directory / "backup.age"
    close = Store.close
    marker = "SYNTHETIC_PRIVATE_BACKUP_CLOSE_DSN"

    async def failed_close(selected):
        await close(selected)
        raise RuntimeError(marker)

    with monkeypatch.context() as patcher:
        patcher.setattr(Store, "close", failed_close)
        with pytest.raises(DomainError) as failed:
            await backup(settings, root / "operator", archive, recipients,
                replace(runtime, max_archive_bytes=65536))
    assert failed.value.code == "BACKUP_TOO_LARGE"
    assert failed.value.effect == EffectState.NOT_STARTED
    public = failed.value.public()
    assert public["cleanup"]["complete"] is False
    assert any(item["code"] == "OPERATIONS_CLOSE_FAILED" for item in public["cleanup"]["failures"])
    assert marker not in json.dumps(public)
    assert list(directory.iterdir()) == []
    assert (await store.authenticate(TOKEN)).credential_id == actor.credential_id


@pytest.mark.asyncio
async def test_real_published_backup_retains_committed_effect_and_is_restorable_after_close_failure(live_authority, binary_runtime, monkeypatch):
    store, actor, binding, settings, root = live_authority
    runtime, keygen = binary_runtime
    identity, recipients = age_keys(root, keygen)
    captured = await store.capture(actor, CaptureCommand(binding_id=binding.id,
        idempotency_key="published-cleanup-source", origin_key="published-cleanup-source",
        body="Published encrypted evidence survives a connection cleanup failure.", speaker="human"))
    archive = root / "published-cleanup.age"
    close = Store.close
    marker = "SYNTHETIC_PRIVATE_PUBLISHED_BACKUP_CLOSE_DSN"

    async def failed_close(selected):
        await close(selected)
        raise RuntimeError(marker)

    with monkeypatch.context() as patcher:
        patcher.setattr(Store, "close", failed_close)
        try:
            raise RuntimeError("Synthetic prior caller failure is not this backup's primary error")
        except RuntimeError:
            with pytest.raises(DomainError) as failed:
                await backup(settings, root / "operator", archive, recipients, runtime)
    assert failed.value.effect == EffectState.COMMITTED
    assert failed.value.public()["cleanup"]["complete"] is False
    assert marker not in json.dumps(failed.value.public())
    assert not list(root.glob(".memory-encrypted-*"))
    head = store.journal.verify()["head"]
    await store.close()
    recovered_token = root / "published-cleanup-recovered-operator"
    restored = await restore(settings, root / "operator", archive, identity, head,
        recovered_token, settings.deployment_id, runtime)
    assert restored["effect"] == "committed" and restored["tokens_rotated"] is True
    consumer = Store(settings, DeletionJournal(settings.journal_dir, settings.deployment_id))
    await consumer.open()
    await consumer.reconcile_journal()
    try:
        recovered_actor = await consumer.authenticate(recovered_token.read_text().strip())
        assert (await consumer.source(recovered_actor, binding.id, captured.source_id)).body == (
            "Published encrypted evidence survives a connection cleanup failure.")
    finally:
        await consumer.close()


@pytest.mark.asyncio
async def test_real_restore_primary_failure_and_fence_survive_multiple_private_close_failures(live_authority, binary_runtime, monkeypatch):
    store, _, _, settings, root = live_authority
    runtime, keygen = binary_runtime
    identity, recipients = age_keys(root, keygen)
    archive = root / "restore-cleanup.age"
    await backup(settings, root / "operator", archive, recipients, runtime)
    head = store.journal.verify()["head"]
    await store.close()
    authenticate, close = Store.authenticate, Store.close
    failed_stores = []
    fail_cleanup = False
    marker = "SYNTHETIC_PRIVATE_RESTORE_CLOSE_DSN"

    async def failed_verification(selected, token, roles=None):
        nonlocal fail_cleanup
        result = await authenticate(selected, token) if roles is None else await authenticate(selected, token, roles)
        if token != TOKEN:
            fail_cleanup = True
            raise DomainError("SYNTHETIC_VERIFICATION_FAILURE", "Synthetic independent final credential verification failure")
        return result

    async def failed_close(selected):
        await close(selected)
        if fail_cleanup:
            failed_stores.append(selected)
            raise RuntimeError(marker)

    with monkeypatch.context() as patcher:
        patcher.setattr(Store, "authenticate", failed_verification)
        patcher.setattr(Store, "close", failed_close)
        with pytest.raises(DomainError) as failed:
            await restore(settings, root / "operator", archive, identity, head,
                root / "restore-cleanup-recovered-operator", settings.deployment_id, runtime)
    assert failed.value.code == "RESTORE_RECOVERY_REQUIRED" and failed.value.effect == EffectState.UNKNOWN
    public = failed.value.public()
    assert public["cleanup"]["complete"] is False and len(public["cleanup"]["failures"]) == 2
    assert marker not in json.dumps(public)
    assert failed_stores and all(selected.pool is None for selected in failed_stores)
    assert (settings.state_dir / "restore-barrier.json").exists()
    with pytest.raises(DomainError) as fenced:
        with ops.authority_lock(settings):
            pytest.fail("An incomplete restore must not permit normal shared authority entry")
    assert fenced.value.code == "RESTORE_RECOVERY_REQUIRED"
