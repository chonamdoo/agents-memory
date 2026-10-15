from __future__ import annotations

import json
import os
import stat
import uuid

import pytest
import pytest_asyncio
from pydantic import ValidationError
from test_store_authority import TOKEN
from test_store_authority import authority as authority

from agents_memory.config import Settings
from agents_memory.domain import DomainError, Principal, Role
from agents_memory.judge import (
    KEY_FILE,
    PROVIDER_FILE,
    TOKEN_FILE,
    JudgeState,
    describe,
    grant_new_binding,
    judge_dir,
    key_fingerprint,
    load_state,
    read_supplied_key,
    read_worker_token,
    set_agent,
    set_jev,
    validate_key,
)

KEY = "sk-jev-TEST-qwrtyuiopZXCVNMLKJH"
OTHER_KEY = "sk-jev-SECOND-mnbvcxzPOIUYTRWQ"


def verified(key, model):
    return "jev-1.13.0"


def personal(tmp_path, mode="personal", deployment_id="deployment-001"):
    state = tmp_path / "state"
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    state.chmod(0o700)
    return Settings(deployment_id=deployment_id, realm="personal", mode=mode, database_dsn="postgresql://not-used",
        state_dir=state, journal_dir=tmp_path / "journal")


def private_file(path, text, mode=0o600):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(mode)
    return path


def operator_principal():
    return Principal(id="owner_test", credential_id="credential_operator", realm="personal", role=Role.OPERATOR, generation=1, bindings=())


def windows(text, size=4):
    return {text[start:start + size] for start in range(len(text) - size + 1)}


@pytest.mark.parametrize("raw", ["short-key-123", "sk-jev with-space-inside", "sk-jev-키-" + "x" * 16, "sk\tjev-tab-inside-0001"])
def test_validate_key_rejects_short_spaced_or_non_ascii_keys(raw):
    with pytest.raises(DomainError) as caught:
        validate_key(raw)
    assert caught.value.code == "JUDGE_KEY_INVALID"
    assert raw not in caught.value.message


def test_validate_key_strips_surrounding_newlines():
    assert validate_key("\n" + KEY + "\n") == KEY


def test_key_fingerprint_is_deployment_salted_and_reveals_no_key_text(tmp_path):
    first = key_fingerprint(personal(tmp_path / "a", deployment_id="deployment-001"), KEY)
    second = key_fingerprint(personal(tmp_path / "b", deployment_id="deployment-002"), KEY)
    for fingerprint in (first, second):
        assert fingerprint.startswith("hmac-sha256:")
        digest = fingerprint.removeprefix("hmac-sha256:")
        assert len(digest) == 12 and all(character in "0123456789abcdef" for character in digest)
        assert not any(window in fingerprint for window in windows(KEY))
    assert first != second
    assert key_fingerprint(personal(tmp_path / "a", deployment_id="deployment-001"), KEY) == first


def test_load_state_defaults_to_agent_when_absent(tmp_path):
    state = load_state(personal(tmp_path))
    assert state.provider == "agent" and state.revision == 0


@pytest.mark.parametrize(("content", "mode"), [
    ("{not json", 0o600),
    (JudgeState(provider="agent", revision=3).model_dump_json(), 0o640),
    (json.dumps({"format": 1, "provider": "jev", "revision": 1}), 0o600),
], ids=["corrupt", "group-readable", "incomplete-jev"])
def test_load_state_refuses_corrupt_exposed_or_incomplete_settings(tmp_path, content, mode):
    settings = personal(tmp_path)
    private_file(judge_dir(settings) / PROVIDER_FILE, content, mode)
    with pytest.raises(DomainError) as caught:
        load_state(settings)
    assert caught.value.code == "JUDGE_STATE_INVALID"


def test_jev_state_requires_model_key_fingerprint_and_credential():
    with pytest.raises(ValidationError):
        JudgeState(provider="jev")
    with pytest.raises(ValidationError):
        JudgeState(provider="jev", model="jev-1.13.0", key_fingerprint="hmac-sha256:0123456789ab")


def test_read_supplied_key_warns_on_shared_file_and_refuses_symlink(tmp_path):
    supplied = private_file(tmp_path / "jev.key", KEY + "\n", 0o644)
    key, warnings = read_supplied_key(supplied)
    assert key == KEY
    assert warnings and all(KEY not in warning for warning in warnings)
    supplied.chmod(0o600)
    assert read_supplied_key(supplied) == (KEY, [])
    link = tmp_path / "linked.key"
    link.symlink_to(supplied)
    with pytest.raises(DomainError) as caught:
        read_supplied_key(link)
    assert caught.value.code == "PATH_DENIED"


def test_describe_hides_identifiers_from_agents_and_key_from_everyone(tmp_path):
    settings = personal(tmp_path)
    private_file(judge_dir(settings) / KEY_FILE, KEY + "\n")
    fingerprint = key_fingerprint(settings, KEY)
    state = JudgeState(provider="jev", revision=2, model="jev-1.13.0", key_fingerprint=fingerprint,
        credential_id="credential_worker")
    agent_view = describe(settings, state, operator=False)
    operator_view = describe(settings, state, operator=True)
    assert agent_view["provider"] == "jev" and agent_view["egress"]["endpoint"].startswith("https://api.typesafe.ai/")
    assert {"key", "credential_id", "updated_by"}.isdisjoint(agent_view)
    agent_text = json.dumps(agent_view, default=str)
    assert fingerprint not in agent_text and "credential_worker" not in agent_text
    assert operator_view["key"] == {"stored": True, "fingerprint": fingerprint}
    for view in (agent_view, operator_view):
        assert KEY not in json.dumps(view, default=str)


class Tripwire:
    def __getattr__(self, name):
        pytest.fail(f"Company Jev refusal touched store.{name}")


async def test_set_jev_in_company_mode_refuses_before_store_verify_or_files(tmp_path):
    settings = personal(tmp_path, mode="company")

    def unexpected_verify(key, model):
        pytest.fail("Company Jev refusal verified the key")

    with pytest.raises(DomainError) as caught:
        await set_jev(settings, Tripwire(), operator_principal(), KEY, verify=unexpected_verify)
    assert caught.value.code == "JUDGE_PROVIDER_FORBIDDEN"
    assert not judge_dir(settings).exists()


@pytest_asyncio.fixture
async def judged(authority):
    state = authority.store.settings.state_dir
    state.mkdir(parents=True, exist_ok=True)
    state.chmod(0o700)
    return authority


def mode(path):
    return stat.S_IMODE(os.lstat(path).st_mode)


async def operator_again(store):
    return await store.authenticate(TOKEN)


async def test_set_jev_publishes_private_files_and_rotates_the_worker_credential(judged):
    store, settings = judged.store, judged.store.settings
    second = await store.register_binding(judged.actor, "Second project", None, "second-binding")
    actor = await operator_again(store)

    result = await set_jev(settings, store, actor, KEY, verify=verified)
    directory = judge_dir(settings)
    assert mode(directory) == 0o700
    for name in (PROVIDER_FILE, KEY_FILE, TOKEN_FILE):
        assert mode(directory / name) == 0o600
    assert KEY not in json.dumps(result, default=str)
    assert result["provider"] == "jev" and result["revision"] == 1
    first_token = read_worker_token(settings)
    worker = await store.authenticate(first_token, (Role.AGENT,))
    assert worker.role == Role.AGENT and worker.id == actor.id
    assert set(worker.bindings) == {judged.binding_id, second.id}
    assert worker.credential_id == load_state(settings).credential_id != actor.credential_id

    rotated = await set_jev(settings, store, actor, OTHER_KEY, verify=verified)
    assert rotated["revision"] == 2 and rotated["retired_credential"] == worker.credential_id
    with pytest.raises(DomainError) as caught:
        await store.authenticate(first_token, (Role.AGENT,))
    assert caught.value.code == "AUTH_DENIED"
    replacement = await store.authenticate(read_worker_token(settings), (Role.AGENT,))
    assert replacement.credential_id == load_state(settings).credential_id != worker.credential_id
    assert load_state(settings).key_fingerprint == key_fingerprint(settings, OTHER_KEY)


async def test_set_agent_retires_worker_and_optionally_forgets_key(judged):
    store, settings, actor = judged.store, judged.store.settings, judged.actor
    directory = judge_dir(settings)
    await set_jev(settings, store, actor, KEY, verify=verified)
    token = read_worker_token(settings)
    fingerprint = load_state(settings).key_fingerprint

    kept = await set_agent(settings, store, actor, forget_key=False)
    state = load_state(settings)
    assert state.provider == "agent" and state.revision == 2 and state.credential_id is None
    assert state.key_fingerprint == fingerprint and (directory / KEY_FILE).exists()
    assert not (directory / TOKEN_FILE).exists()
    assert KEY not in json.dumps(kept, default=str)
    with pytest.raises(DomainError) as caught:
        await store.authenticate(token)
    assert caught.value.code == "AUTH_DENIED"

    await set_jev(settings, store, actor, KEY, verify=verified)
    token = read_worker_token(settings)
    await set_agent(settings, store, actor, forget_key=True)
    state = load_state(settings)
    assert state.provider == "agent" and state.revision == 4 and state.key_fingerprint is None
    assert not (directory / KEY_FILE).exists() and not (directory / TOKEN_FILE).exists()
    with pytest.raises(DomainError) as caught:
        await store.authenticate(token)
    assert caught.value.code == "AUTH_DENIED"


async def test_new_project_joins_jev_worker_grant_only_while_jev_judges(judged):
    store, settings, actor = judged.store, judged.store.settings, judged.actor
    agent_project = await store.register_binding(actor, "Agent judged project", None, "agent-project")
    actor = await operator_again(store)
    assert await grant_new_binding(settings, store, actor, agent_project.id) is None

    await set_jev(settings, store, actor, KEY, verify=verified)
    added = await store.register_binding(actor, "Jev judged project", None, "jev-project")
    actor = await operator_again(store)
    granted = await grant_new_binding(settings, store, actor, added.id)
    assert granted is not None and granted["worker_grant"] == "added"
    worker = await store.authenticate(read_worker_token(settings), (Role.AGENT,))
    assert added.id in worker.bindings and agent_project.id in worker.bindings

    await set_agent(settings, store, actor, forget_key=False)
    later = await store.register_binding(actor, "Later project", None, "later-project")
    actor = await operator_again(store)
    assert await grant_new_binding(settings, store, actor, later.id) is None


async def test_grant_binding_refuses_non_agent_or_foreign_credentials(judged):
    store, actor, binding = judged.store, judged.actor, judged.binding_id
    producer = await store.issue_token(actor, Role.PRODUCER, (binding,), "producer-grant-boundary-" + "p" * 32)
    foreign = "credential_" + uuid.uuid4().hex
    async with store.pool.acquire() as connection:
        await connection.execute(
            "INSERT INTO am_credentials(id,principal_id,realm,role,token_hash) VALUES($1,$2,$3,'agent',$4)",
            foreign, "owner_other", actor.realm, store._token_hash("foreign-agent-credential-" + "f" * 32),
        )
    for credential_id in (actor.credential_id, producer.credential_id, foreign):
        with pytest.raises(DomainError) as caught:
            await store.grant_binding(actor, credential_id, binding)
        assert caught.value.code == "SCOPE_DENIED"
