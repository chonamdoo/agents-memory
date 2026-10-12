from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

from agents_memory import initialization
from agents_memory import journal as journal_module
from agents_memory.domain import DomainError, EffectState, Principal, Role
from agents_memory.initialization import initialize_deployment
from agents_memory.journal import DeletionJournal
from agents_memory.migrations import MIGRATION
from agents_memory.ops import authority_lock
from agents_memory.private_io import private_write


@pytest.fixture
def arguments(tmp_path):
    return {"config_path": tmp_path / "config.json", "realm": "personal_init", "mode": "personal",
        "database_dsn": "postgresql://memory:private-service-secret@127.0.0.1:5432/memory?schema=memory",
        "migrator_dsn": "postgresql://migrator:private-migrator-secret@127.0.0.1:5432/memory?schema=memory",
        "state_dir": tmp_path / "authority", "journal_dir": tmp_path / "independent-journal",
        "port": 8768, "owner_id": "owner_init", "operator_token_out": tmp_path / "operator.token",
        "deployment_id": None}


@pytest.fixture
def database(monkeypatch):
    state = SimpleNamespace(actor=None, token=None, settings=None, migrations=0, bootstraps=0,
        preflights=0, failure=None, events=[], unrelated=False)

    class Authority:
        def __init__(self, settings, journal):
            self.settings, self.journal = settings, journal

        @classmethod
        async def preflight_initialization(cls, settings, token, owner, *, resume):
            state.preflights += 1
            state.events.append("database_preflight")
            if state.unrelated:
                raise DomainError("INIT_SCOPE_DENIED", "An unrelated authority cannot be adopted")
            if state.actor is None:
                return None
            if (not resume or state.token != token or state.actor.id != owner
                    or state.settings.deployment_id != settings.deployment_id or state.settings.realm != settings.realm):
                raise DomainError("INIT_SCOPE_DENIED", "The credential does not own this authority")
            return state.actor

        async def open(self):
            state.events.append("open")

        async def close(self):
            state.events.append("close")

        async def bootstrap(self, token, owner, *, resume=False):
            assert self.journal.verify()["deployment_id"] == self.settings.deployment_id
            state.events.append("bootstrap")
            if state.failure == "bootstrap_before":
                state.failure = None
                raise OSError("injected bootstrap before commit")
            if state.actor is not None:
                assert resume and state.token == token and state.actor.id == owner
                return state.actor
            state.bootstraps += 1
            state.token, state.settings = token, self.settings
            state.actor = Principal(id=owner, credential_id="credential_original", realm=self.settings.realm,
                role=Role.OPERATOR, generation=1, bindings=())
            if state.failure == "bootstrap_after":
                state.failure = None
                raise OSError("injected lost bootstrap response")
            return state.actor

    def migrate(dsn):
        state.events.append("migrate")
        state.migrations += 1
        if state.failure == "migration":
            state.failure = None
            raise OSError("injected migration interruption")
        return {"migration": MIGRATION}

    monkeypatch.setattr(initialization, "Store", Authority)
    monkeypatch.setattr(initialization, "migrate", migrate)
    return state


def intent(arguments):
    return json.loads((arguments["state_dir"] / "initialization-intent.json").read_bytes())


def snapshot(arguments):
    return {str(path): path.read_bytes() for root in (arguments["state_dir"], arguments["journal_dir"])
        if root.exists() for path in root.rglob("*") if path.is_file()}


@pytest.mark.asyncio
@pytest.mark.parametrize("output", ["operator_token_out", "config_path"])
async def test_existing_output_conflict_precedes_intent_journal_and_database(arguments, database, output):
    private_write(arguments[output], "unrelated-private-credential")
    with pytest.raises(DomainError) as denied:
        await initialize_deployment(**arguments)
    assert denied.value.code == "OUTPUT_EXISTS"
    assert denied.value.effect == EffectState.NOT_STARTED
    assert arguments[output].read_text() == "unrelated-private-credential"
    assert not arguments["state_dir"].exists()
    assert not arguments["journal_dir"].exists()
    assert database.events == []


@pytest.mark.asyncio
async def test_unrelated_database_preflight_refuses_before_first_effect(arguments, database):
    database.unrelated = True
    with pytest.raises(DomainError):
        await initialize_deployment(**arguments)
    assert database.migrations == database.bootstraps == 0
    assert not (arguments["state_dir"] / "initialization-intent.json").exists()
    assert not arguments["journal_dir"].exists()
    assert not arguments["operator_token_out"].exists()
    assert not arguments["config_path"].exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("window", ["migration", "journal_plan", "key", "metadata", "entries", "head",
    "token", "config", "bootstrap_before", "bootstrap_after", "completion"])
async def test_each_interrupted_effect_resumes_original_identity_and_credential(arguments, database, monkeypatch, window):
    database.failure = window
    original_publish = initialization.private_write
    original_journal_publish = journal_module.private_write
    fired = False

    def publish(path, content, **kwargs):
        nonlocal fired
        target = arguments["operator_token_out"] if window == "token" else arguments["config_path"]
        if window == "completion" and path.name == "initialization-result.json" and not fired:
            fired = True
            raise OSError("injected post-bootstrap pre-receipt interruption")
        original_publish(path, content, **kwargs)
        if window in {"token", "config"} and path == target and not fired:
            fired = True
            raise OSError("injected post-publication interruption")

    def publish_journal(path, content, **kwargs):
        nonlocal fired
        original_journal_publish(path, content, **kwargs)
        target = "initialization" if window == "journal_plan" else window
        if path.name == target and not fired:
            fired = True
            raise OSError("injected post-journal-publication interruption")

    monkeypatch.setattr(initialization, "private_write", publish)
    monkeypatch.setattr(journal_module, "private_write", publish_journal)
    with pytest.raises(DomainError) as interrupted:
        await initialize_deployment(**arguments)
    assert interrupted.value.code == "INIT_RECOVERY_REQUIRED"
    assert interrupted.value.effect == (EffectState.COMMITTED if window == "completion" else EffectState.UNKNOWN)
    original = intent(arguments)
    assert database.events.index("database_preflight") < database.events.index("migrate")
    original_key = (arguments["journal_dir"] / "key").read_bytes() if (arguments["journal_dir"] / "key").exists() else None
    with pytest.raises(DomainError) as explicit:
        await initialize_deployment(**arguments)
    assert explicit.value.code == "INIT_RESUME_REQUIRED"
    result = await initialize_deployment(**arguments, resume=True)
    assert result["deployment_id"] == original["request"]["deployment_id"]
    assert result["credential_id"] == "credential_original"
    assert database.bootstraps == 1
    assert database.token == original["operator_token"]
    assert arguments["operator_token_out"].read_text() == original["operator_token"] + "\n"
    assert arguments["config_path"].read_text() == original["config"]
    if original_key is not None:
        assert (arguments["journal_dir"] / "key").read_bytes() == original_key
    key = (arguments["journal_dir"] / "key").read_bytes()
    assert key.hex() not in (arguments["state_dir"] / "initialization-intent.json").read_text()
    assert key.hex() in (arguments["journal_dir"] / "initialization").read_text()
    for path in (arguments["config_path"], arguments["operator_token_out"], arguments["state_dir"] / "initialization-intent.json"):
        assert path.stat().st_mode & 0o077 == 0
    before, migrations = snapshot(arguments), database.migrations
    token_inode = arguments["operator_token_out"].stat().st_ino
    assert await initialize_deployment(**arguments) == result
    assert await initialize_deployment(**arguments, resume=True) == result
    assert snapshot(arguments) == before and database.migrations == migrations
    assert arguments["operator_token_out"].stat().st_ino == token_inode
    public = json.dumps(result)
    assert original["operator_token"] not in public
    assert "private-service-secret" not in public and "private-migrator-secret" not in public


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["realm", "mode", "database_dsn", "migrator_dsn", "owner_id",
    "port", "deployment_id", "config_path", "operator_token_out", "journal_dir", "state_dir"])
async def test_resume_fingerprint_mismatch_refuses_before_another_effect(arguments, database, change):
    database.failure = "bootstrap_before"
    with pytest.raises(DomainError):
        await initialize_deployment(**arguments)
    before, migrations = snapshot(arguments), database.migrations
    changed = dict(arguments)
    if change in {"realm", "owner_id", "deployment_id"}:
        changed[change] = "different_identity"
    elif change == "mode":
        changed[change] = "company"
    elif change == "port":
        changed[change] = 9000
    elif change in {"database_dsn", "migrator_dsn"}:
        changed[change] = arguments[change].replace("secret", "different-secret")
    else:
        changed[change] = arguments[change].with_name("different-output")
    with pytest.raises(DomainError) as denied:
        await initialize_deployment(**changed, resume=True)
    assert denied.value.effect == EffectState.NOT_STARTED
    assert snapshot(arguments) == before and database.migrations == migrations
    assert database.bootstraps == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["operator_token_out", "config_path", "intent", "journal_key"])
async def test_resume_rejects_changed_credential_config_or_journal_ownership(arguments, database, target):
    database.failure = "bootstrap_before"
    with pytest.raises(DomainError):
        await initialize_deployment(**arguments)
    if target == "intent":
        path = arguments["state_dir"] / "initialization-intent.json"
        value = json.loads(path.read_bytes())
        value["operator_token"] = "unrelated-operator-" + "x" * 40
        private_write(path, json.dumps(value), replace=True)
    elif target == "journal_key":
        path = arguments["journal_dir"] / "key"
        private_write(path, b"x" * 32, replace=True)
    else:
        path = arguments[target]
        private_write(path, "unrelated-private-output", replace=True)
    before, migrations = snapshot(arguments), database.migrations
    with pytest.raises(DomainError) as denied:
        await initialize_deployment(**arguments, resume=True)
    assert denied.value.effect == EffectState.NOT_STARTED
    assert snapshot(arguments) == before and database.migrations == migrations
    assert database.bootstraps == 0


@pytest.mark.asyncio
async def test_completed_intent_requires_live_authenticated_original_operator(arguments, database):
    await initialize_deployment(**arguments)
    database.token = "unrelated-credential-" + "x" * 40
    before, migrations = snapshot(arguments), database.migrations
    with pytest.raises(DomainError):
        await initialize_deployment(**arguments, resume=True)
    assert snapshot(arguments) == before and database.migrations == migrations


@pytest.mark.asyncio
@pytest.mark.parametrize("partial", [False, True])
async def test_existing_journal_without_own_intent_is_never_adopted(arguments, database, partial):
    journal = DeletionJournal(arguments["journal_dir"], "deployment_unrelated")
    if partial:
        arguments["journal_dir"].mkdir(mode=0o700)
        private_write(arguments["journal_dir"] / "key", os.urandom(32))
    else:
        journal.initialize()
    before = snapshot(arguments)
    with pytest.raises(DomainError):
        await initialize_deployment(**arguments)
    assert database.migrations == database.bootstraps == 0
    assert snapshot(arguments).items() >= before.items()
    assert not (arguments["state_dir"] / "initialization-intent.json").exists()


@pytest.mark.asyncio
async def test_config_or_partial_journal_alone_does_not_authorize_resume(arguments, database):
    private_write(arguments["config_path"], '{"deployment_id":"self_reported"}')
    arguments["journal_dir"].mkdir(mode=0o700)
    private_write(arguments["journal_dir"] / "key", os.urandom(32))
    before = snapshot(arguments)
    with pytest.raises(DomainError):
        await initialize_deployment(**arguments, resume=True)
    assert database.events == [] and snapshot(arguments) == before


@pytest.mark.asyncio
async def test_initialization_uses_exclusive_authority_lock(arguments, database):
    from agents_memory.config import Settings

    settings = Settings(deployment_id="deployment_locked", realm=arguments["realm"], mode=arguments["mode"],
        database_dsn=arguments["database_dsn"], migrator_dsn=arguments["migrator_dsn"],
        state_dir=arguments["state_dir"], journal_dir=arguments["journal_dir"])
    with authority_lock(settings):
        with pytest.raises(DomainError) as denied:
            await initialize_deployment(**arguments)
    assert denied.value.code == "AUTHORITY_BUSY"
    assert database.events == []


@pytest.mark.asyncio
async def test_service_and_migrator_cannot_select_different_authority_databases(arguments, database):
    arguments["migrator_dsn"] = arguments["migrator_dsn"].replace("/memory?", "/unrelated?")
    with pytest.raises(DomainError) as denied:
        await initialize_deployment(**arguments)
    assert denied.value.code == "CONFIG_INVALID"
    assert database.events == [] and not arguments["state_dir"].exists()


@pytest.mark.asyncio
async def test_private_scope_intent_is_durable_before_migration_starts(arguments, database, monkeypatch):
    migrate = initialization.migrate
    def require_intent(dsn):
        owned = initialization._intent(arguments["state_dir"] / "initialization-intent.json")
        assert owned is not None and owned["request"]["migrator_dsn"] == dsn
        assert not arguments["journal_dir"].exists()
        assert not arguments["operator_token_out"].exists()
        assert not arguments["config_path"].exists()
        return migrate(dsn)
    monkeypatch.setattr(initialization, "migrate", require_intent)
    await initialize_deployment(**arguments)


@pytest.mark.asyncio
@pytest.mark.parametrize("conflict", ["symlink", "parent_file", "same_output", "journal_output"])
async def test_output_identity_conflicts_fail_before_any_database_or_journal_effect(arguments, database, tmp_path, conflict):
    if conflict == "symlink":
        private_write(tmp_path / "unrelated", "unrelated")
        arguments["operator_token_out"].symlink_to(tmp_path / "unrelated")
    elif conflict == "parent_file":
        private_write(tmp_path / "not-a-directory", "unrelated")
        arguments["operator_token_out"] = tmp_path / "not-a-directory" / "operator"
    elif conflict == "same_output":
        arguments["operator_token_out"] = arguments["config_path"]
    else:
        arguments["operator_token_out"] = arguments["journal_dir"] / "key"
    with pytest.raises(DomainError):
        await initialize_deployment(**arguments)
    assert database.events == [] and not arguments["journal_dir"].exists()


@pytest.mark.asyncio
async def test_completed_replay_preserves_advanced_owned_journal_and_original_credential(arguments, database):
    result = await initialize_deployment(**arguments)
    journal = DeletionJournal(arguments["journal_dir"], result["deployment_id"])
    journal.append("binding_owned", ("source_retracted",), ())
    database.actor = database.actor.model_copy(update={"generation": 2, "bindings": ("binding_owned",)})
    before, migrations = snapshot(arguments), database.migrations
    assert await initialize_deployment(**arguments, resume=True) == result
    assert snapshot(arguments) == before and database.migrations == migrations
    database.actor = database.actor.model_copy(update={"credential_id": "credential_replacement"})
    with pytest.raises(DomainError):
        await initialize_deployment(**arguments, resume=True)
    assert snapshot(arguments) == before and database.migrations == migrations


async def test_completed_replay_preserves_authorized_mutable_configuration(arguments, database):
    first = await initialize_deployment(**arguments)
    config_path = arguments["config_path"]
    config = json.loads(config_path.read_bytes())
    config["allowed_model_purposes"] = ["embedding"]
    config["models"]["timeout_seconds"] = 30
    config["queue_limit"] = 2048
    config_path.write_text(json.dumps(config))
    previous_bytes, previous_inode = config_path.read_bytes(), config_path.stat().st_ino

    replay = await initialize_deployment(**arguments)

    assert replay["credential_id"] == first["credential_id"]
    assert config_path.read_bytes() == previous_bytes
    assert config_path.stat().st_ino == previous_inode
    assert database.migrations == database.bootstraps == 1
