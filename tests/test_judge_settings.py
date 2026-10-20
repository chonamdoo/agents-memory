from __future__ import annotations

import asyncio
import json
import os
import stat
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Barrier, Event
from types import SimpleNamespace

import pytest
import pytest_asyncio
from pydantic import ValidationError
from test_store_authority import TOKEN
from test_store_authority import authority as authority

from agents_memory import judge as judge_module
from agents_memory.config import Settings
from agents_memory.domain import DomainError, EffectState, Principal, Role
from agents_memory.judge import (
    EGRESS_POLICY_FILE,
    ISSUING_TOKEN_FILE,
    KEY_FILE,
    PROVIDER_FILE,
    TOKEN_FILE,
    EgressPolicy,
    JudgeState,
    describe,
    grant_new_binding,
    judge_dir,
    key_fingerprint,
    load_egress_policy,
    load_state,
    read_supplied_key,
    read_worker_token,
    require_route_allowed,
    set_agent,
    set_egress_policy,
    set_jev,
    set_subscription,
    validate_key,
)

KEY = "sk-jev-TEST-qwrtyuiopZXCVNMLKJH"
OTHER_KEY = "sk-jev-SECOND-mnbvcxzPOIUYTRWQ"


def verified(key, model):
    return "jev-1.14.0"


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



@pytest.mark.parametrize(("field", "value"), [
    ("format", True), ("format", 1.0), ("format", "1"),
    ("revision", True), ("revision", False), ("revision", "2"), ("revision", 2.0),
    ("forget_key_pending", "true"), ("forget_key_pending", "false"),
    ("forget_key_pending", 1), ("forget_key_pending", 0),
])
def test_private_provider_scalar_coercions_are_refused(tmp_path, field, value):
    settings = personal(tmp_path)
    private_file(judge_dir(settings) / PROVIDER_FILE, json.dumps({field: value}))
    with pytest.raises(DomainError) as caught:
        load_state(settings)
    assert caught.value.code == "JUDGE_STATE_INVALID"


@pytest.mark.parametrize(("field", "value"), [
    ("format", True), ("format", 1.0), ("format", "1"),
    ("revision", True), ("revision", False), ("revision", "2"), ("revision", 2.0),
    ("jev_allowed", "true"), ("jev_allowed", "false"), ("jev_allowed", 1), ("jev_allowed", 0),
])
def test_private_policy_scalar_coercions_fail_closed(tmp_path, field, value):
    settings = personal(tmp_path)
    private_file(judge_dir(settings) / EGRESS_POLICY_FILE, json.dumps({field: value}))
    with pytest.raises(DomainError) as caught:
        require_route_allowed(settings, "jev")
    assert caught.value.code == "JUDGE_EGRESS_POLICY_INVALID"


def test_private_judge_scalars_accept_exact_json_types(tmp_path):
    settings = personal(tmp_path)
    private_file(judge_dir(settings) / PROVIDER_FILE,
                 json.dumps({"format": 1, "revision": 2, "forget_key_pending": False}))
    private_file(judge_dir(settings) / EGRESS_POLICY_FILE,
                 json.dumps({"format": 1, "revision": 3, "jev_allowed": True}))
    assert load_state(settings).revision == 2
    assert load_state(settings).forget_key_pending is False
    assert load_egress_policy(settings).revision == 3
    require_route_allowed(settings, "jev")

def test_jev_state_requires_model_key_fingerprint_and_credential():
    with pytest.raises(ValidationError):
        JudgeState(provider="jev")
    with pytest.raises(ValidationError):
        JudgeState(provider="jev", model="jev-1.14.0", key_fingerprint="hmac-sha256:0123456789ab")


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
    private_file(judge_dir(settings) / EGRESS_POLICY_FILE, EgressPolicy(jev_allowed=True).model_dump_json())
    fingerprint = key_fingerprint(settings, KEY)
    state = JudgeState(provider="jev", revision=2, model="jev-1.14.0", key_fingerprint=fingerprint,
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
        pytest.fail(f"Denied Jev egress touched store.{name}")


@pytest.mark.parametrize("mode", ["company", "personal"])
@pytest.mark.parametrize("policy", ["absent", "denied"])
async def test_set_jev_without_authorization_refuses_before_store_verify_or_files(tmp_path, mode, policy):
    settings = personal(tmp_path, mode=mode)
    if policy == "denied":
        private_file(judge_dir(settings) / EGRESS_POLICY_FILE, EgressPolicy(jev_allowed=False).model_dump_json())

    def unexpected_verify(key, model):
        pytest.fail("Denied Jev egress verified the key")

    with pytest.raises(DomainError) as caught:
        await set_jev(settings, Tripwire(), operator_principal(), KEY, verify=unexpected_verify)
    assert caught.value.code == "JUDGE_PROVIDER_FORBIDDEN"
    assert load_state(settings).provider == "agent"
    assert not (judge_dir(settings) / KEY_FILE).exists()
    assert not (judge_dir(settings) / TOKEN_FILE).exists()
    if policy == "absent":
        assert not judge_dir(settings).exists()


@pytest.mark.parametrize("mode", ["company", "personal"])
async def test_allowing_egress_is_independent_of_mode_and_does_not_select_or_contact_jev(tmp_path, mode):
    settings = personal(tmp_path, mode=mode)
    assert load_egress_policy(settings).jev_allowed is False
    result = await set_egress_policy(settings, MemoryJudgeStore(), operator_principal(), jev_allowed=True)
    assert load_egress_policy(settings).jev_allowed is True
    require_route_allowed(settings, "jev")
    assert result["provider"] == "agent"
    assert result["source_judgment"] == "current_coding_agent_via_mcp"
    assert result["egress_policy"]["jev_allowed"] is True
    assert mode_of(judge_dir(settings) / EGRESS_POLICY_FILE) == 0o600
    assert not (judge_dir(settings) / PROVIDER_FILE).exists()
    assert not (judge_dir(settings) / KEY_FILE).exists()
    assert not (judge_dir(settings) / TOKEN_FILE).exists()


@pytest.mark.parametrize(("content", "permissions"), [
    ("{bad json", 0o600),
    ('{"jev_allowed": "true"}', 0o600),
    (EgressPolicy(jev_allowed=True).model_dump_json(), 0o644),
])
def test_egress_policy_invalid_or_exposed_fails_closed(tmp_path, content, permissions):
    settings = personal(tmp_path)
    private_file(judge_dir(settings) / EGRESS_POLICY_FILE, content, permissions)
    with pytest.raises(DomainError) as caught:
        require_route_allowed(settings, "jev")
    assert caught.value.code == "JUDGE_EGRESS_POLICY_INVALID"


async def test_only_operator_can_change_egress_policy(tmp_path):
    settings = personal(tmp_path)
    agent = operator_principal().model_copy(update={"role": Role.AGENT})
    for allowed in (True, False):
        with pytest.raises(DomainError) as caught:
            await set_egress_policy(settings, Tripwire(), agent, jev_allowed=allowed)
        assert caught.value.code == "ROLE_DENIED"
    assert not judge_dir(settings).exists()


@pytest_asyncio.fixture
async def judged(authority):
    state = authority.store.settings.state_dir
    state.mkdir(parents=True, exist_ok=True)
    state.chmod(0o700)
    await set_egress_policy(authority.store.settings, authority.store, authority.actor, jev_allowed=True)
    return authority


@pytest.mark.parametrize("mutation", ["allow", "deny", "agent", "jev"])
@pytest.mark.parametrize("authority_change", ["revoke", "generation", "current"])
async def test_waiting_judge_mutations_recheck_live_operator_authority(
    authority, monkeypatch, mutation, authority_change,
):
    store, settings, actor = authority.store, authority.store.settings, authority.actor
    settings.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    settings.state_dir.chmod(0o700)
    if mutation == "jev":
        await set_egress_policy(settings, store, actor, jev_allowed=True)
    previous_policy, previous_state = load_egress_policy(settings), load_state(settings)
    attempted = asyncio.Event()
    original_guard = judge_module.judge_guard

    @asynccontextmanager
    async def observed_guard(selected):
        attempted.set()
        async with original_guard(selected):
            yield

    async def mutate():
        if mutation in {"allow", "deny"}:
            return await set_egress_policy(settings, store, actor, jev_allowed=mutation == "allow")
        if mutation == "agent":
            return await set_agent(settings, store, actor, forget_key=True)
        return await set_jev(settings, store, actor, KEY, verify=verified)

    waiter = None
    try:
        async with original_guard(settings):
            with monkeypatch.context() as patcher:
                patcher.setattr(judge_module, "judge_guard", observed_guard)
                waiter = asyncio.create_task(mutate())
                await asyncio.wait_for(attempted.wait(), 5)
                assert not waiter.done()
                if authority_change == "revoke":
                    await store.revoke_token(actor, actor.credential_id)
                elif authority_change == "generation":
                    async with store._tx() as (connection, _):
                        await connection.execute(
                            "UPDATE am_credentials SET generation=generation+1 WHERE id=$1", actor.credential_id,
                        )
        [outcome] = await asyncio.wait_for(asyncio.gather(waiter, return_exceptions=True), 5)
    finally:
        if waiter is not None and not waiter.done():
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)
    if authority_change == "current":
        assert isinstance(outcome, dict) and outcome["effect"] == EffectState.COMMITTED
        if mutation == "jev":
            assert load_state(settings).provider == "jev"
            worker = await store.authenticate(read_worker_token(settings))
            assert worker.credential_id == load_state(settings).credential_id
        elif mutation == "allow":
            require_route_allowed(settings, "jev")
        else:
            assert load_state(settings).provider == "agent"
            assert not load_egress_policy(settings).jev_allowed
        return
    assert isinstance(outcome, DomainError)
    assert outcome.code == ("AUTH_DENIED" if authority_change == "revoke" else "SCOPE_DENIED")
    assert outcome.public()["effect"] == "not_started"
    assert load_egress_policy(settings) == previous_policy
    assert load_state(settings) == previous_state
    assert not (judge_dir(settings) / KEY_FILE).exists()
    assert not (judge_dir(settings) / TOKEN_FILE).exists()
    assert not (judge_dir(settings) / ISSUING_TOKEN_FILE).exists()

    if authority_change == "generation":
        actor = await store.authenticate(TOKEN)
        result = await mutate()
        assert result["effect"] == EffectState.COMMITTED


async def test_operator_revoked_during_verification_cannot_publish_a_transition_fence(judged):
    store, settings, actor = judged.store, judged.store.settings, judged.actor
    previous_state = load_state(settings)
    entered, released = Event(), Event()

    def blocked_verify(key, model):
        entered.set()
        assert released.wait(5), "Verification was not released"
        return "jev-1.14.0"

    setup = asyncio.create_task(set_jev(settings, store, actor, KEY, verify=blocked_verify))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        await store.revoke_token(actor, actor.credential_id)
    finally:
        released.set()
        [outcome] = await asyncio.gather(setup, return_exceptions=True)
    assert isinstance(outcome, DomainError) and outcome.code == "AUTH_DENIED"
    assert outcome.public()["effect"] == "not_started"
    assert load_state(settings) == previous_state
    assert not (judge_dir(settings) / PROVIDER_FILE).exists()
    assert not (judge_dir(settings) / ISSUING_TOKEN_FILE).exists()
    assert not (judge_dir(settings) / TOKEN_FILE).exists()
    assert not (judge_dir(settings) / KEY_FILE).exists()


def mode_of(path):
    return stat.S_IMODE(os.lstat(path).st_mode)


async def operator_again(store):
    return await store.authenticate(TOKEN)


@pytest.mark.parametrize("deployment_mode", ["personal", "company"])
async def test_set_jev_publishes_private_files_and_rotates_the_worker_credential(judged, deployment_mode):
    store = judged.store
    settings = store.settings.model_copy(update={"mode": deployment_mode})
    second = await store.register_binding(judged.actor, "Second project", None, "second-binding")
    actor = await operator_again(store)

    result = await set_jev(settings, store, actor, KEY, verify=verified)
    directory = judge_dir(settings)
    assert mode_of(directory) == 0o700
    for name in (PROVIDER_FILE, KEY_FILE, TOKEN_FILE):
        assert mode_of(directory / name) == 0o600
    assert KEY not in json.dumps(result, default=str)
    assert result["provider"] == "jev"
    first_token = read_worker_token(settings)
    worker = await store.authenticate(first_token, (Role.AGENT,))
    assert worker.role == Role.AGENT and worker.id == actor.id
    assert set(worker.bindings) == {judged.binding_id, second.id}
    assert worker.credential_id == load_state(settings).credential_id != actor.credential_id

    rotated = await set_jev(settings, store, actor, OTHER_KEY, verify=verified)
    assert rotated["retired_credential"] == worker.credential_id
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
    assert state.provider == "agent" and state.credential_id is None
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
    assert state.provider == "agent" and state.key_fingerprint is None
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


async def test_deny_policy_selects_current_agent_and_retires_worker_without_forgetting_key(judged):
    store, settings, actor = judged.store, judged.store.settings, judged.actor
    await set_jev(settings, store, actor, KEY, verify=verified)
    worker_state = load_state(settings)
    token = read_worker_token(settings)

    result = await set_egress_policy(settings, store, actor, jev_allowed=False)

    assert load_egress_policy(settings).jev_allowed is False
    state = load_state(settings)
    assert state.provider == "agent" and state.revision > worker_state.revision
    assert state.credential_id is None
    assert not (judge_dir(settings) / TOKEN_FILE).exists()
    assert (judge_dir(settings) / KEY_FILE).exists()
    assert result["retired_credential"] == worker_state.credential_id
    assert result["source_judgment"] == "current_coding_agent_via_mcp"
    assert KEY not in json.dumps(result, default=str)
    with pytest.raises(DomainError) as caught:
        await store.authenticate(token)
    assert caught.value.code == "AUTH_DENIED"
    with pytest.raises(DomainError) as caught:
        await set_jev(settings, Tripwire(), actor, KEY, verify=lambda *_: pytest.fail("Denied key verification"))
    assert caught.value.code == "JUDGE_PROVIDER_FORBIDDEN"


async def test_revocation_during_key_verification_does_not_publish_provider_or_credentials(judged):
    settings, actor = judged.store.settings, judged.actor

    def revoke_during_verify(key, model):
        policy = load_egress_policy(settings)
        private_file(judge_dir(settings) / EGRESS_POLICY_FILE,
            EgressPolicy(jev_allowed=False, revision=policy.revision + 1).model_dump_json())
        return "jev-1.14.0"

    with pytest.raises(DomainError) as caught:
        await set_jev(settings, judged.store, actor, KEY, verify=revoke_during_verify)
    assert caught.value.code == "JUDGE_PROVIDER_FORBIDDEN"
    assert load_state(settings).provider == "agent"
    assert not (judge_dir(settings) / KEY_FILE).exists()
    assert not (judge_dir(settings) / TOKEN_FILE).exists()


async def test_completed_deny_then_allow_cannot_resurrect_inflight_setup(judged):
    store, settings, actor = judged.store, judged.store.settings, judged.actor
    entered, released = Event(), Event()

    def blocked_verify(key, model):
        entered.set()
        assert released.wait(5), "Verification was not released"
        return "jev-1.14.0"

    setup = asyncio.create_task(set_jev(settings, store, actor, KEY, verify=blocked_verify))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        await set_egress_policy(settings, store, actor, jev_allowed=False)
        await set_egress_policy(settings, store, actor, jev_allowed=True)
    finally:
        released.set()
        [outcome] = await asyncio.gather(setup, return_exceptions=True)
    assert isinstance(outcome, DomainError)
    assert outcome.code == "JUDGE_EGRESS_POLICY_CHANGED"
    assert load_egress_policy(settings).jev_allowed
    assert load_state(settings).provider == "agent"
    assert not (judge_dir(settings) / TOKEN_FILE).exists()


async def test_concurrent_verified_setups_do_not_overwrite_a_new_selection(judged):
    store, settings, actor = judged.store, judged.store.settings, judged.actor
    entered, released = Barrier(3), Event()

    def blocked_verify(key, model):
        entered.wait(5)
        assert released.wait(5), "Concurrent verification was not released"
        return "jev-1.14.0"

    setups = [asyncio.create_task(set_jev(settings, store, actor, key, verify=blocked_verify))
              for key in (KEY, OTHER_KEY)]
    try:
        await asyncio.to_thread(entered.wait, 5)
    finally:
        released.set()
        outcomes = await asyncio.gather(*setups, return_exceptions=True)
    successful = [value for value in outcomes if isinstance(value, dict)]
    refused = [value for value in outcomes if isinstance(value, DomainError)]
    assert len(successful) == len(refused) == 1
    assert refused[0].code == "JUDGE_PROVIDER_CHANGED"
    state = load_state(settings)
    assert state.credential_id == successful[0]["credential_id"]
    worker = await store.authenticate(read_worker_token(settings), (Role.AGENT,))
    assert worker.credential_id == state.credential_id


@pytest.mark.parametrize("lost_response", [False, True])
async def test_retirement_retry_preserves_exact_authority_and_forget_intent(judged, monkeypatch, lost_response):
    store, settings, actor = judged.store, judged.store.settings, judged.actor
    await set_jev(settings, store, actor, KEY, verify=verified)
    previous = load_state(settings)
    token = read_worker_token(settings)
    revoke = store.revoke_token

    async def interrupted_retirement(principal, credential_id):
        if lost_response:
            await revoke(principal, credential_id)
        raise DomainError("AUTHORITY_UNAVAILABLE", "Synthetic retirement response loss", status=503)

    with monkeypatch.context() as patcher:
        patcher.setattr(store, "revoke_token", interrupted_retirement)
        with pytest.raises(DomainError) as caught:
            await set_agent(settings, store, actor, forget_key=True)
    assert caught.value.code == "AUTHORITY_UNAVAILABLE"
    assert caught.value.public()["effect"] == "unknown"
    pending = load_state(settings)
    assert pending.provider == "agent" and pending.retiring_credential_ids == (previous.credential_id,)
    assert pending.forget_key_pending
    assert not (judge_dir(settings) / TOKEN_FILE).exists()
    assert (judge_dir(settings) / KEY_FILE).exists()
    result = await set_agent(settings, store, actor, forget_key=False)
    assert result["retirement_pending"] is False
    assert load_state(settings).retiring_credential_ids == ()
    assert not (judge_dir(settings) / KEY_FILE).exists()
    with pytest.raises(DomainError) as denied:
        await store.authenticate(token)
    assert denied.value.code == "AUTH_DENIED"
    await set_egress_policy(settings, store, actor, jev_allowed=True)
    assert load_state(settings).provider == "agent"


async def test_reallow_completes_deny_interrupted_before_provider_transition(judged, monkeypatch):
    store, settings, actor = judged.store, judged.store.settings, judged.actor
    await set_jev(settings, store, actor, KEY, verify=verified)
    token = read_worker_token(settings)

    async def interrupted(*args, **kwargs):
        raise OSError("Synthetic process exit after the durable deny")

    with monkeypatch.context() as patcher:
        patcher.setattr(judge_module, "_set_agent", interrupted)
        with pytest.raises(OSError):
            await set_egress_policy(settings, store, actor, jev_allowed=False)
    assert not load_egress_policy(settings).jev_allowed
    assert load_state(settings).provider == "jev"
    result = await set_egress_policy(settings, store, actor, jev_allowed=True)
    assert result["provider"] == "agent"
    assert load_state(settings).provider == "agent"
    with pytest.raises(DomainError) as retired:
        await store.authenticate(token)
    assert retired.value.code == "AUTH_DENIED"


@pytest.mark.parametrize("fault", ["lost_response", "token_write", "key_write", "provider_publish", "after_publication"])
async def test_interrupted_issuance_is_retired_or_adopted_only_after_publication(judged, monkeypatch, fault):
    store, settings, actor = judged.store, judged.store.settings, judged.actor
    issued_tokens = []
    issue, write, save = store.issue_token, judge_module.private_write, judge_module._save_state

    async def tracked_issue(principal, role, bindings, token):
        issued = await issue(principal, role, bindings, token)
        issued_tokens.append(token)
        if fault == "lost_response":
            raise DomainError("DATABASE_UNAVAILABLE", "Synthetic committed issuance with lost response", status=503)
        return issued

    def failed_write(path, *args, **kwargs):
        if (fault == "token_write" and path.name == TOKEN_FILE) or (fault == "key_write" and path.name == KEY_FILE):
            raise OSError("Synthetic private publication failure")
        return write(path, *args, **kwargs)

    def failed_save(deployment, state):
        if state.provider == "jev" and fault == "provider_publish":
            raise OSError("Synthetic failure before provider publication")
        save(deployment, state)
        if state.provider == "jev" and fault == "after_publication":
            raise OSError("Synthetic failure after provider publication")

    with monkeypatch.context() as patcher:
        patcher.setattr(store, "issue_token", tracked_issue)
        patcher.setattr(judge_module, "private_write", failed_write)
        patcher.setattr(judge_module, "_save_state", failed_save)
        with pytest.raises((OSError, DomainError)):
            await set_jev(settings, store, actor, KEY, verify=verified)
    [token] = issued_tokens
    result = await set_egress_policy(settings, store, actor, jev_allowed=True)
    if fault == "after_publication":
        active = await store.authenticate(token, (Role.AGENT,))
        assert result["provider"] == "jev"
        assert active.credential_id == load_state(settings).credential_id
    else:
        assert result["provider"] == "agent"
        with pytest.raises(DomainError) as retired:
            await store.authenticate(token)
        assert retired.value.code == "AUTH_DENIED"
    assert not (judge_dir(settings) / ISSUING_TOKEN_FILE).exists()


async def test_uncertain_issuance_recovery_waits_for_its_database_commit(judged, monkeypatch):
    store, settings, actor = judged.store, judged.store.settings, judged.actor
    before_commit, finish_commit = asyncio.Event(), asyncio.Event()
    original_tx, original_issue = store._tx, store.issue_token
    issue_task = recovery = None
    token_value = []

    @asynccontextmanager
    async def held_transaction(*args, **kwargs):
        async with original_tx(*args, **kwargs) as value:
            yield value
            if asyncio.current_task() is issue_task:
                before_commit.set()
                await finish_commit.wait()

    async def uncertain_issue(principal, role, bindings, token):
        nonlocal issue_task
        token_value.append(token)
        issue_task = asyncio.create_task(original_issue(principal, role, bindings, token))
        await before_commit.wait()
        raise DomainError("DATABASE_UNAVAILABLE", "Synthetic issuance still committing", status=503)

    try:
        with monkeypatch.context() as patcher:
            patcher.setattr(store, "_tx", held_transaction)
            patcher.setattr(store, "issue_token", uncertain_issue)
            with pytest.raises(DomainError):
                await set_jev(settings, store, actor, KEY, verify=verified)
            recovery = asyncio.create_task(set_agent(settings, store, actor, forget_key=True))
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(asyncio.shield(recovery), 0.03)
            finish_commit.set()
            await issue_task
            await recovery
    finally:
        finish_commit.set()
        await asyncio.gather(*(task for task in (issue_task, recovery) if task is not None), return_exceptions=True)
    [token] = token_value
    with pytest.raises(DomainError) as retired:
        await store.authenticate(token)
    assert retired.value.code == "AUTH_DENIED"
    assert load_state(settings).provider == "agent"


async def test_invalid_provider_requires_explicit_agent_repair_before_key_verification(judged):
    store, settings, actor = judged.store, judged.store.settings, judged.actor
    private_file(judge_dir(settings) / PROVIDER_FILE, "{not valid JSON")

    def unexpected_verification(*args):
        pytest.fail("Invalid provider state reached network verification")

    with pytest.raises(DomainError) as blocked:
        await set_jev(settings, Tripwire(), actor, KEY, verify=unexpected_verification)
    assert blocked.value.code == "JUDGE_STATE_INVALID"
    await set_agent(settings, store, actor, forget_key=True)
    selected = await set_jev(settings, store, actor, KEY, verify=verified)
    assert selected["provider"] == "jev"
    assert (await store.authenticate(read_worker_token(settings))).credential_id == selected["credential_id"]


@pytest.mark.parametrize("mode", ["personal", "company"])
@pytest.mark.parametrize("policy", ["absent", "denied", "invalid"])
def test_describe_never_claims_jev_egress_without_effective_permission(tmp_path, mode, policy):
    settings = personal(tmp_path, mode=mode)
    state = JudgeState(provider="jev", model="jev-1.14.0", key_fingerprint=key_fingerprint(settings, KEY),
                       credential_id="credential_worker")
    if policy != "absent":
        private_file(judge_dir(settings) / EGRESS_POLICY_FILE,
                     "{invalid" if policy == "invalid" else EgressPolicy(jev_allowed=False).model_dump_json())
    view = describe(settings, state, operator=False)
    assert view["provider"] == "agent" and view["configured_provider"] == "jev"
    assert view["source_judgment"] == "current_coding_agent_via_mcp" and view["egress"] is None
    assert view["egress_policy"]["jev_allowed"] is False


class MemoryJudgeStore:
    def __init__(self):
        self.credentials = {}
        self.issued = 0
        self.operator = operator_principal()
        self.authority_lock = asyncio.Lock()

    @asynccontextmanager
    async def operator_authority(self, actor):
        async with self.authority_lock:
            if actor != self.operator:
                raise DomainError("AUTH_DENIED", "Synthetic operator authority is unavailable", status=401)
            yield self.operator

    async def list_bindings(self, actor):
        return [SimpleNamespace(id="binding_test")]

    async def issue_token(self, actor, role, bindings, token):
        self.issued += 1
        principal = actor.model_copy(update={
            "credential_id": f"credential_worker_{self.issued}", "role": role, "bindings": bindings,
        })
        self.credentials[token] = principal
        return principal

    async def resolve_issued_credential(self, actor, token, *, role):
        principal = self.credentials.get(token)
        return principal.credential_id if principal is not None else None

    async def revoke_token(self, actor, credential_id):
        for token, principal in tuple(self.credentials.items()):
            if principal.credential_id == credential_id:
                del self.credentials[token]
                return
        raise DomainError("NOT_FOUND", "Synthetic credential is inactive")

    async def authenticate(self, token):
        if token not in self.credentials:
            raise DomainError("AUTH_DENIED", "Synthetic credential is inactive")
        return self.credentials[token]


async def selected_memory_judge(tmp_path):
    settings, store, actor = personal(tmp_path), MemoryJudgeStore(), operator_principal()
    await set_egress_policy(settings, store, actor, jev_allowed=True)
    await set_jev(settings, store, actor, KEY, verify=verified)
    return settings, store, actor


@pytest.mark.parametrize("fault", [
    "list_bindings", "issue_before_commit", "issue_lost_response", "token_write", "key_write",
    "provider_publish", "after_publication", "retirement_before_issue", "retirement_after_publication",
    "fence_crash",
])
async def test_failed_jev_replacement_preserves_selection_and_requires_explicit_recovery(tmp_path, monkeypatch, fault):
    settings, store, actor = await selected_memory_judge(tmp_path)
    previous, old_token = load_state(settings), read_worker_token(settings)
    issue, revoke = store.issue_token, store.revoke_token
    write, save = judge_module.private_write, judge_module._save_state
    replacement_tokens = []

    async def failed_lookup(principal):
        raise DomainError("DATABASE_BUSY", "Synthetic binding lookup failure", status=503)

    async def interrupted_issue(principal, role, bindings, token):
        replacement_tokens.append(token)
        if fault == "issue_before_commit":
            raise DomainError("DATABASE_BUSY", "Synthetic issuance refusal", status=503)
        result = await issue(principal, role, bindings, token)
        if fault == "issue_lost_response":
            raise DomainError("DATABASE_BUSY", "Synthetic lost issuance response", status=503)
        return result

    async def interrupted_retirement(principal, credential_id):
        published = load_state(settings).credential_id != previous.credential_id
        if fault == ("retirement_after_publication" if published else "retirement_before_issue"):
            raise DomainError("DATABASE_BUSY", "Synthetic retirement failure", status=503)
        return await revoke(principal, credential_id)

    def interrupted_write(path, *args, **kwargs):
        if (fault == "token_write" and path.name == TOKEN_FILE) or (fault == "key_write" and path.name == KEY_FILE):
            raise OSError("Synthetic file publication failure")
        return write(path, *args, **kwargs)

    def interrupted_save(deployment, state):
        publishing = state.credential_id != previous.credential_id
        if fault == "provider_publish" and publishing:
            raise OSError("Synthetic provider publication failure")
        save(deployment, state)
        if fault == ("after_publication" if publishing else "fence_crash"):
            raise OSError("Synthetic crash after durable provider write")

    with monkeypatch.context() as patcher:
        if fault == "list_bindings":
            patcher.setattr(store, "list_bindings", failed_lookup)
        patcher.setattr(store, "issue_token", interrupted_issue)
        patcher.setattr(store, "revoke_token", interrupted_retirement)
        patcher.setattr(judge_module, "private_write", interrupted_write)
        patcher.setattr(judge_module, "_save_state", interrupted_save)
        with pytest.raises(DomainError) as caught:
            await set_jev(settings, store, actor, OTHER_KEY, verify=verified)

    state = load_state(settings)
    view = describe(settings, state, operator=True)
    assert state.provider == view["provider"] == view["configured_provider"] == "jev"
    assert state.revision > previous.revision
    published = fault in {"after_publication", "retirement_after_publication"}
    if published:
        assert (await store.authenticate(read_worker_token(settings))).credential_id == state.credential_id
        assert state.key_fingerprint == key_fingerprint(settings, OTHER_KEY)
    else:
        assert state.credential_id == previous.credential_id
        assert state.credential_id in state.retiring_credential_ids
        assert view["retirement_pending"]
        assert view["source_judgment"] == "jev_unavailable_explicit_reselection_required"
        with pytest.raises(DomainError) as unavailable:
            read_worker_token(settings)
        assert unavailable.value.code == "JUDGE_CREDENTIAL_INVALID"
    assert caught.value.effect == (EffectState.COMMITTED if fault == "list_bindings" else EffectState.UNKNOWN)
    if fault in {"issue_before_commit", "issue_lost_response", "token_write", "key_write", "provider_publish",
                 "after_publication"}:
        assert (judge_dir(settings) / ISSUING_TOKEN_FILE).exists()
        assert view["retirement_pending"]

    recovered = await set_jev(settings, store, actor, OTHER_KEY, verify=verified)
    assert recovered["provider"] == "jev" and recovered["retirement_pending"] is False
    active_token = read_worker_token(settings)
    assert (await store.authenticate(active_token)).credential_id == load_state(settings).credential_id
    assert not (judge_dir(settings) / ISSUING_TOKEN_FILE).exists()
    for token in [old_token, *replacement_tokens]:
        with pytest.raises(DomainError) as retired:
            await store.authenticate(token)
        assert retired.value.code == "AUTH_DENIED"


@pytest.mark.parametrize("lost_response", [False, True])
async def test_durable_deny_reports_commit_and_unresolved_retirement(tmp_path, monkeypatch, lost_response):
    settings, store, actor = await selected_memory_judge(tmp_path)
    token = read_worker_token(settings)
    revoke = store.revoke_token

    async def interrupted(principal, credential_id):
        if lost_response:
            await revoke(principal, credential_id)
        raise DomainError("DATABASE_BUSY", "Synthetic retirement response loss", status=503)

    with monkeypatch.context() as patcher:
        patcher.setattr(store, "revoke_token", interrupted)
        with pytest.raises(DomainError) as caught:
            await set_egress_policy(settings, store, actor, jev_allowed=False)
    assert not load_egress_policy(settings).jev_allowed
    state = load_state(settings)
    assert state.provider == "agent" and state.retiring_credential_ids
    assert describe(settings, state, operator=True)["retirement_pending"]
    assert caught.value.code == "DATABASE_BUSY" and caught.value.status == 503
    assert caught.value.public()["effect"] == "unknown"
    assert not (judge_dir(settings) / TOKEN_FILE).exists()
    result = await set_egress_policy(settings, store, actor, jev_allowed=False)
    assert result["effect"] == EffectState.COMMITTED and not result["retirement_pending"]
    with pytest.raises(DomainError) as retired:
        await store.authenticate(token)
    assert retired.value.code == "AUTH_DENIED"


def test_diagnostics_show_unresolved_issuance_without_retirement_ids(tmp_path):
    settings = personal(tmp_path)
    private_file(judge_dir(settings) / ISSUING_TOKEN_FILE, "synthetic-unresolved-token\n")
    state = JudgeState()
    assert describe(settings, state, operator=True)["retirement_pending"]
    assert describe(settings, state, operator=False)["retirement_pending"]
    assert "synthetic-unresolved-token" not in json.dumps(describe(settings, state, operator=True))



async def test_issuance_reconciliation_failure_keeps_unknown_effect_and_visible_pending_intent(tmp_path, monkeypatch):
    settings, store, actor = await selected_memory_judge(tmp_path)
    issue = store.issue_token

    async def lost_issue(principal, role, bindings, token):
        await issue(principal, role, bindings, token)
        raise DomainError("DATABASE_BUSY", "Synthetic committed issuance response loss", status=503)

    async def unavailable_resolution(*args, **kwargs):
        raise DomainError("DATABASE_BUSY", "Synthetic reconciliation unavailable", status=503)

    with monkeypatch.context() as patcher:
        patcher.setattr(store, "issue_token", lost_issue)
        with pytest.raises(DomainError) as lost:
            await set_jev(settings, store, actor, OTHER_KEY, verify=verified)
    assert lost.value.effect == EffectState.UNKNOWN
    with monkeypatch.context() as patcher:
        patcher.setattr(store, "resolve_issued_credential", unavailable_resolution)
        with pytest.raises(DomainError) as unresolved:
            await set_egress_policy(settings, store, actor, jev_allowed=True)
    state = load_state(settings)
    assert state.provider == "jev"
    assert unresolved.value.code == "DATABASE_BUSY" and unresolved.value.effect == EffectState.UNKNOWN
    assert (judge_dir(settings) / ISSUING_TOKEN_FILE).exists()
    assert describe(settings, state, operator=True)["retirement_pending"]
    assert KEY not in unresolved.value.message and OTHER_KEY not in unresolved.value.message
    recovered = await set_agent(settings, store, actor, forget_key=True)
    assert recovered["effect"] == EffectState.COMMITTED and recovered["retirement_pending"] is False
    assert not store.credentials


async def test_deny_error_before_provider_cleanup_still_reports_durable_policy_commit(tmp_path, monkeypatch):
    settings, store, actor = await selected_memory_judge(tmp_path)
    previous = load_state(settings)

    async def unavailable_cleanup(*args, **kwargs):
        raise DomainError("DATABASE_BUSY", "Synthetic provider cleanup refusal", status=503)

    with monkeypatch.context() as patcher:
        patcher.setattr(judge_module, "_set_agent", unavailable_cleanup)
        with pytest.raises(DomainError) as caught:
            await set_egress_policy(settings, store, actor, jev_allowed=False)
    assert not load_egress_policy(settings).jev_allowed
    assert load_state(settings) == previous
    assert caught.value.code == "DATABASE_BUSY" and caught.value.effect == EffectState.UNKNOWN
    with pytest.raises(DomainError) as denied:
        require_route_allowed(settings, "jev")
    assert denied.value.code == "JUDGE_PROVIDER_FORBIDDEN"
    recovered = await set_egress_policy(settings, store, actor, jev_allowed=False)
    assert recovered["provider"] == "agent" and not recovered["retirement_pending"]
    assert not store.credentials


async def test_operator_revoked_after_issuance_leaves_fenced_recoverable_worker(judged, monkeypatch):
    store, settings, actor = judged.store, judged.store.settings, judged.actor
    await set_jev(settings, store, actor, KEY, verify=verified)
    previous = load_state(settings)
    recovery_actor = await store.issue_token(
        actor, Role.OPERATOR, actor.bindings, "judge-recovery-operator-" + "r" * 32,
    )
    issue = store.issue_token
    issued_tokens = []

    async def revoke_after_issue(principal, role, bindings, token):
        result = await issue(principal, role, bindings, token)
        issued_tokens.append(token)
        await store.revoke_token(actor, actor.credential_id)
        return result

    with monkeypatch.context() as patcher:
        patcher.setattr(store, "issue_token", revoke_after_issue)
        with pytest.raises(DomainError) as refused:
            await set_jev(settings, store, actor, OTHER_KEY, verify=verified)
    assert refused.value.code == "AUTH_DENIED"
    assert refused.value.public()["effect"] == "unknown"
    state = load_state(settings)
    assert state.credential_id == previous.credential_id
    assert state.credential_id in state.retiring_credential_ids
    assert describe(settings, state, operator=True)["source_judgment"] == "jev_unavailable_explicit_reselection_required"
    assert (judge_dir(settings) / ISSUING_TOKEN_FILE).exists()
    [issued_token] = issued_tokens
    issued = await store.authenticate(issued_token)
    assert issued.credential_id != state.credential_id
    result = await set_agent(settings, store, recovery_actor, forget_key=True)
    assert result["provider"] == "agent" and not result["retirement_pending"]
    assert not (judge_dir(settings) / ISSUING_TOKEN_FILE).exists()
    assert not (judge_dir(settings) / KEY_FILE).exists()
    with pytest.raises(DomainError) as retired:
        await store.authenticate(issued_token)
    assert retired.value.code == "AUTH_DENIED"


async def test_reallow_refusal_after_cleanup_reports_committed_cleanup_not_new_policy(judged, monkeypatch):
    store, settings, actor = judged.store, judged.store.settings, judged.actor
    await set_jev(settings, store, actor, KEY, verify=verified)
    worker_token = read_worker_token(settings)
    select_agent = judge_module._set_agent

    async def interrupted_cleanup(*args, **kwargs):
        raise DomainError("DATABASE_BUSY", "Synthetic interruption after durable deny", status=503)

    with monkeypatch.context() as patcher:
        patcher.setattr(judge_module, "_set_agent", interrupted_cleanup)
        with pytest.raises(DomainError):
            await set_egress_policy(settings, store, actor, jev_allowed=False)
    denied_policy = load_egress_policy(settings)
    assert not denied_policy.jev_allowed
    assert load_state(settings).provider == "jev"

    async def revoke_after_cleanup(*args, **kwargs):
        result = await select_agent(*args, **kwargs)
        await store.revoke_token(actor, actor.credential_id)
        return result

    with monkeypatch.context() as patcher:
        patcher.setattr(judge_module, "_set_agent", revoke_after_cleanup)
        with pytest.raises(DomainError) as refused:
            await set_egress_policy(settings, store, actor, jev_allowed=True)
    assert refused.value.code == "AUTH_DENIED"
    assert refused.value.public()["effect"] == "committed"
    assert load_egress_policy(settings) == denied_policy
    assert load_state(settings).provider == "agent"
    assert not describe(settings, load_state(settings), operator=True)["retirement_pending"]
    with pytest.raises(DomainError) as retired:
        await store.authenticate(worker_token)
    assert retired.value.code == "AUTH_DENIED"


@pytest.mark.parametrize("target", ["policy", "provider", "issuing", "token", "key", "remove_token"])
@pytest.mark.parametrize("after", [False, True], ids=["before-effect", "lost-response"])
async def test_judge_file_failures_keep_publication_identity_and_explicit_recovery(judged, monkeypatch, target, after):
    store, settings, actor = judged.store, judged.store.settings, judged.actor
    await set_jev(settings, store, actor, KEY, verify=verified)
    previous = load_state(settings)
    old_token = read_worker_token(settings)
    name = {
        "policy": EGRESS_POLICY_FILE, "provider": PROVIDER_FILE,
        "issuing": ISSUING_TOKEN_FILE, "token": TOKEN_FILE,
        "key": KEY_FILE, "remove_token": TOKEN_FILE,
    }[target]
    path = judge_dir(settings) / name
    write, unlink = judge_module.private_write, os.unlink

    def fail_write(destination, *args, **options):
        if destination.name != name:
            return write(destination, *args, **options)
        if after:
            write(destination, *args, **options)
        raise OSError("synthetic private publication failure " + OTHER_KEY)

    def fail_unlink(destination, *args, **options):
        if os.path.basename(destination) != TOKEN_FILE:
            return unlink(destination, *args, **options)
        if after:
            unlink(destination, *args, **options)
        raise OSError("synthetic private cleanup failure " + OTHER_KEY)

    async def mutate():
        if target == "policy":
            return await set_egress_policy(settings, store, actor, jev_allowed=False)
        if target == "remove_token":
            return await set_agent(settings, store, actor, forget_key=True)
        return await set_jev(settings, store, actor, OTHER_KEY, verify=verified)

    with monkeypatch.context() as patch:
        if target == "remove_token":
            patch.setattr(os, "unlink", fail_unlink)
        else:
            patch.setattr(judge_module, "private_write", fail_write)
        with pytest.raises(DomainError) as interrupted:
            await mutate()
    assert interrupted.value.code == "JUDGE_PUBLICATION_UNCONFIRMED"
    assert interrupted.value.effect == EffectState.UNKNOWN
    assert KEY not in interrupted.value.message and OTHER_KEY not in interrupted.value.message
    state = load_state(settings)
    stranded_token = None
    if target == "policy":
        assert load_egress_policy(settings).jev_allowed == (not after)
        assert state == previous
    elif target == "provider":
        if after:
            assert previous.credential_id in state.retiring_credential_ids
        else:
            assert state == previous
    elif target == "remove_token":
        assert state.provider == "agent"
        assert previous.credential_id in state.retiring_credential_ids
        assert path.exists() == (not after)
    else:
        assert state.credential_id in state.retiring_credential_ids
        if target in {"issuing", "token"}:
            assert path.exists() is after
        else:
            assert path.read_text().strip() == (OTHER_KEY if after else KEY)
        if target in {"token", "key"}:
            stranded_token = (judge_dir(settings) / ISSUING_TOKEN_FILE).read_text().strip()
            stranded = await store.authenticate(stranded_token)
            assert stranded.credential_id != previous.credential_id

    recovered = await mutate()
    assert recovered["effect"] == EffectState.COMMITTED
    assert not recovered["retirement_pending"]
    assert not (judge_dir(settings) / ISSUING_TOKEN_FILE).exists()
    if target in {"policy", "remove_token"}:
        assert recovered["provider"] == "agent"
        assert not (judge_dir(settings) / TOKEN_FILE).exists()
        if target == "remove_token":
            assert not (judge_dir(settings) / KEY_FILE).exists()
    else:
        assert recovered["provider"] == "jev"
        assert (judge_dir(settings) / KEY_FILE).read_text().strip() == OTHER_KEY
        current = await store.authenticate(read_worker_token(settings))
        assert current.role == Role.AGENT
    for token in (old_token, stranded_token):
        if token is not None:
            with pytest.raises(DomainError) as retired:
                await store.authenticate(token)
            assert retired.value.code == "AUTH_DENIED"


async def test_subscription_requires_its_own_grant_before_contacting_the_cli(tmp_path):
    settings, store, actor = personal(tmp_path), MemoryJudgeStore(), operator_principal()
    await set_egress_policy(settings, store, actor, jev_allowed=True)
    checked = []
    with pytest.raises(DomainError) as caught:
        await set_subscription(settings, store, actor, "claude", Path(sys.executable), verify=checked.append)
    assert caught.value.code == "JUDGE_PROVIDER_FORBIDDEN" and checked == [] and store.issued == 0

    await set_egress_policy(settings, store, actor, jev_allowed=False)
    await set_egress_policy(settings, store, actor, subscription_allowed=True)
    with pytest.raises(DomainError) as caught:
        require_route_allowed(settings, "jev")
    assert caught.value.code == "JUDGE_PROVIDER_FORBIDDEN"
    result = await set_subscription(settings, store, actor, "claude", Path(sys.executable), model="haiku",
                                    verify=lambda client: "claude-haiku-test")
    state = load_state(settings)
    assert (state.provider, state.host, state.model, state.executable) == ("subscription", "claude", "haiku", sys.executable)
    assert result["source_judgment"] == "subscription_cli_background_then_server_validation"
    assert result["verified_model"] == "claude-haiku-test" and result["egress"]["executable"] == sys.executable
    worker = await store.authenticate(read_worker_token(settings))
    assert worker.role == Role.AGENT and worker.credential_id == state.credential_id
    assert describe(settings, state, operator=False)["egress"]["executable"] is None


async def test_denying_one_route_never_retires_the_other_routes_worker(tmp_path):
    settings, store, actor = personal(tmp_path), MemoryJudgeStore(), operator_principal()
    await set_egress_policy(settings, store, actor, jev_allowed=True)
    await set_egress_policy(settings, store, actor, subscription_allowed=True)
    await set_subscription(settings, store, actor, "omp", Path(sys.executable), verify=lambda client: "omp-default")
    token = read_worker_token(settings)

    await set_egress_policy(settings, store, actor, jev_allowed=False)
    assert load_state(settings).provider == "subscription"
    assert (await store.authenticate(token)).role == Role.AGENT

    result = await set_egress_policy(settings, store, actor, subscription_allowed=False)
    assert result["provider"] == "agent" and load_state(settings).provider == "agent"
    with pytest.raises(DomainError) as retired:
        await store.authenticate(token)
    assert retired.value.code == "AUTH_DENIED"


async def test_subscription_is_refused_when_state_lives_inside_a_project(tmp_path):
    settings, store, actor = personal(tmp_path), MemoryJudgeStore(), operator_principal()
    (tmp_path / ".git").mkdir()
    await set_egress_policy(settings, store, actor, subscription_allowed=True)
    checked = []
    with pytest.raises(DomainError) as caught:
        await set_subscription(settings, store, actor, "claude", Path(sys.executable), verify=checked.append)
    assert caught.value.code == "JUDGE_RUN_DIR_INSIDE_PROJECT" and checked == [] and store.issued == 0
    assert load_state(settings).provider == "agent"
