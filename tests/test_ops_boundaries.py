from __future__ import annotations

import asyncio
import hashlib
import json
import os
import struct
import subprocess
import uuid
from contextlib import asynccontextmanager
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
    ("postgres_version", "17.6"), ("vector_version", "0.8.6"),
    ("migration_version", "other_migration"),
])
def test_encrypted_metadata_cannot_select_another_authority(settings, key, value):
    envelope = metadata(settings)
    envelope[key] = value
    with pytest.raises(DomainError) as denied:
        _validate_metadata(envelope, settings, BackupRuntime(Path("/not-invoked/age")), "owner_ops")
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
        _validate_metadata(mutation(metadata(settings)), settings, BackupRuntime(Path("/not-invoked/age")), "owner_ops")
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
    admin = await asyncpg.connect(admin_dsn)
    store = None
    try:
        await admin.execute(f'CREATE SCHEMA "{schema}"')
        query["schema"] = schema
        dsn = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
        await asyncio.to_thread(migrate, dsn)
        settings = Settings(deployment_id="deployment_ops", realm="personal_ops", mode="personal",
            database_dsn=dsn, migrator_dsn=dsn, state_dir=tmp_path / "authority", journal_dir=tmp_path / "journal")
        store = Store(settings, DeletionJournal(settings.journal_dir, settings.deployment_id))
        await store.open()
        actor = await store.bootstrap(TOKEN, "owner_ops")
        binding = await store.register_binding(actor, "Synthetic ops boundary", None, "binding-ops")
        actor = await store.authenticate(TOKEN)
        private_write(tmp_path / "operator", TOKEN)
        yield store, actor, binding, settings, tmp_path
    finally:
        if store is not None:
            await store.close()
        await admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await admin.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("archived_index", (0, 1, 2))
async def test_private_operator_migrates_prior_schema_without_rotating_credentials_or_resurrecting_sources(live_authority, archived_index):
    from test_store_authority import historical_schema_fixture

    store, actor, binding, settings, root = live_authority
    selected = await store.capture(actor, CaptureCommand(binding_id=binding.id,
        idempotency_key="migration-current", origin_key="migration-current",
        body="Synthetic eligible migration evidence.", speaker="human"))
    withdrawn = await store.capture(actor, CaptureCommand(binding_id=binding.id,
        idempotency_key="migration-withdrawn", origin_key="migration-withdrawn",
        body="Synthetic withdrawn migration evidence.", speaker="human"))
    await store.retract(actor, binding.id, withdrawn.source_id, "migration-floor")
    head = store.journal.verify()["head"]
    await historical_schema_fixture(store, archived_index)
    await store.close()
    with pytest.raises(DomainError) as ordinary:
        await store.open()
    assert ordinary.value.code == "MIGRATION_REQUIRED"
    result = await ops.migrate_authority(settings, root / "operator", settings.deployment_id)
    assert result["previous_migration"] == MIGRATIONS[archived_index]
    assert result["migration"] == MIGRATION and result["application_verified"]
    await store.open()
    await store.reconcile_journal(head)
    current = await store.authenticate(TOKEN, (Role.OPERATOR,))
    assert current.credential_id == actor.credential_id
    assert (await store.source(current, binding.id, selected.source_id)).body == "Synthetic eligible migration evidence."
    retired = await store.inspect(current, binding.id, withdrawn.source_id)
    assert retired["state"] == "retracted" and retired.get("body") is None
    assert store.journal.verify()["head"] == head


@pytest.mark.asyncio
async def test_private_migration_refuses_agent_credential_before_old_schema_changes(live_authority):
    from test_store_authority import historical_schema_fixture

    store, actor, binding, settings, root = live_authority
    agent_token = "synthetic-migration-agent-" + "a" * 40
    await store.issue_token(actor, Role.AGENT, (binding.id,), agent_token)
    private_write(root / "agent", agent_token)
    await historical_schema_fixture(store, 2)
    await store.close()
    with pytest.raises(DomainError) as denied:
        await ops.migrate_authority(settings, root / "agent", settings.deployment_id)
    assert denied.value.code == "SCOPE_DENIED" and denied.value.effect == EffectState.NOT_STARTED
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


async def historical_encrypted_archive(store, actor, archive, recipients, runtime):
    from test_store_authority import historical_schema_fixture

    async with store.pool.acquire() as connection:
        value = await ops._metadata(store, connection, runtime, actor)
    value["migration_version"] = MIGRATIONS[1]
    value["migration_versions"] = list(MIGRATIONS[:2])
    await historical_schema_fixture(store, 1)
    await store.close()
    try:
        private_write(archive, b"")
        async with ops._processes() as processes:
            with archive.open("wb") as output:
                encrypt = await processes.start([str(runtime.age_binary), "--encrypt",
                    "--recipients-file", str(recipients)], stdout=output)
                args = ["--format=custom", "--no-owner", "--no-privileges", "--strict-names"]
                args.extend('--table="' + value["schema"] + '"."' + name + '"'
                    for name in sorted(ops._PRIOR_TABLES))
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
        _validate_metadata(value, settings, BackupRuntime(Path("/not-invoked/age")), "owner_ops")
    assert denied.value.code == "RESTORE_SCOPE_DENIED"
    assert denied.value.effect == EffectState.NOT_STARTED


def test_known_legacy_archive_keeps_exact_old_table_scope(settings):
    _validate_metadata(legacy_metadata(settings), settings, BackupRuntime(Path("/not-invoked/age")), "owner_ops")
    def toc(tables):
        return "\n".join(f"{number}; 0 0 {kind} memory {table} memory"
            for number, (table, kind) in enumerate(
                ((table, kind) for table in sorted(tables) for kind in ("TABLE", "TABLE DATA")), 1)).encode()
    ops._validate_toc(toc(ops._LEGACY_TABLES), "memory", ops._LEGACY_TABLES)
    ops._validate_toc(toc(ops._PRIOR_TABLES), "memory", ops._PRIOR_TABLES)
    ops._validate_toc(toc(ops._TABLES), "memory")
    with pytest.raises(DomainError):
        ops._validate_toc(toc(ops._TABLES), "memory", ops._LEGACY_TABLES)
    with pytest.raises(DomainError):
        ops._validate_toc(toc(ops._LEGACY_TABLES), "memory")
    with pytest.raises(DomainError):
        ops._validate_toc(toc(ops._TABLES), "memory", ops._PRIOR_TABLES)
    with pytest.raises(DomainError):
        ops._validate_toc(toc(ops._PRIOR_TABLES), "memory")


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
    _validate_metadata(value, settings, BackupRuntime(Path("/not-invoked/age")), "owner_ops")
    value["migration_versions"] = list(reversed(value["migration_versions"])) + ["unrecognized"]
    with pytest.raises(DomainError) as denied:
        _validate_metadata(value, settings, BackupRuntime(Path("/not-invoked/age")), "owner_ops")
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
async def test_dump_preflight_selects_exact_archived_table_shape(settings, tmp_path, monkeypatch, revision, format_version):
    value = legacy_metadata(settings) if format_version == 1 else versioned_metadata(settings, revision)
    tables = ops._LEGACY_TABLES if revision == MIGRATIONS[0] else (
        ops._PRIOR_TABLES if revision == MIGRATIONS[1] else ops._TABLES
    )
    toc = "\n".join(f"{number}; 0 0 {kind} memory {table} memory"
        for number, (table, kind) in enumerate(
            ((table, kind) for table in sorted(tables) for kind in ("TABLE", "TABLE DATA")), 1)).encode()
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
    archived, checked = await ops._preflight(object(), BackupRuntime(Path("/not-invoked/age")), settings,
        tmp_path / "archive.age", b"private-identity", "owner_ops", listing=True)
    assert archived["migration_version"] == revision
    assert checked["dump_sha256"] == hashlib.sha256(b"PGDMPvalidated-old-shape").hexdigest()


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
@pytest.mark.parametrize("psql_identity", ["psql (PostgreSQL) 18.5", "pg_dump (PostgreSQL) 18.6"])
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
