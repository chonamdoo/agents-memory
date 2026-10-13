from __future__ import annotations

import asyncio
import hashlib
import json

import pytest
from pydantic import ValidationError
from test_store_authority import TOKEN
from test_store_authority import authority as authority

from agents_memory import cli
from agents_memory.config import load_settings
from agents_memory.domain import DomainError, EffectState, Role
from agents_memory.models import LocalSemanticRuntime
from agents_memory.private_io import private_write
from agents_memory.store import Store


async def test_invalid_model_approval_preserves_existing_deployment_config(authority, tmp_path, monkeypatch):
    settings = authority.store.settings
    config = tmp_path / "private-deployment.json"
    token = tmp_path / "operator.token"
    private_write(config, settings.model_dump_json(indent=2) + "\n")
    private_write(token, TOKEN + "\n")
    original = config.read_bytes()
    args = cli.parser().parse_args([
        "--config", str(config), "--token-file", str(token), "model", "approve",
        "--manifest", str(settings.models.manifest_path),
        "--gguf", str(tmp_path / "local-generation.gguf"),
        "--embedding", str(tmp_path / "embedding"),
        "--reranker", str(tmp_path / "reranker"),
        "--generation-key-file", str(tmp_path / "generation.token"),
        "--generation-url", "http://127.0.0.1:9877",
        "--purpose", "embedding", "--purpose", "embedding",
    ])
    monkeypatch.setattr(LocalSemanticRuntime, "validate_artifacts", lambda self: None)
    async with authority.store.pool.acquire() as connection:
        routes = await connection.fetch("SELECT purpose,revision,epoch FROM am_routes ORDER BY purpose")

    with pytest.raises(ValidationError, match="duplicate purpose"):
        await cli.execute(args)

    assert config.read_bytes() == original
    assert load_settings(config) == settings
    assert not (settings.state_dir / "model-approval-intent.json").exists()
    async with authority.store.pool.acquire() as connection:
        assert await connection.fetch("SELECT purpose,revision,epoch FROM am_routes ORDER BY purpose") == routes


def approval_request(authority, tmp_path):
    settings = authority.store.settings
    config = tmp_path / "private-deployment.json"
    token = tmp_path / "operator.token"
    manifest = tmp_path / "approval-manifest.json"
    value = json.loads(settings.models.manifest_path.read_bytes())
    value["storage_boundary_fixture"] += "-approved"
    manifest.write_text(json.dumps(value))
    private_write(config, settings.model_dump_json(indent=2) + "\n")
    private_write(token, TOKEN + "\n")
    return cli.parser().parse_args([
        "--config", str(config), "--token-file", str(token), "model", "approve",
        "--manifest", str(manifest),
        "--gguf", str(tmp_path / "local-generation.gguf"),
        "--embedding", str(tmp_path / "embedding"),
        "--reranker", str(tmp_path / "reranker"),
        "--generation-key-file", str(tmp_path / "generation.token"),
        "--generation-url", "http://127.0.0.1:9877",
    ])


async def assert_consumer_admission(args, binding_id, revision):
    async with cli.authority(args) as (_, store, actor):
        admission = await store.admit_read(actor, binding_id, (), revision, "embedding")
        assert admission.route_revision == revision
        assert await store.admitted_claims(admission) == []


@pytest.mark.parametrize("concurrent_policy_change", (False, True))
async def test_post_publication_authority_barrier_compensates_and_exact_retry_adopts(
    authority, tmp_path, monkeypatch, concurrent_policy_change,
):
    args = approval_request(authority, tmp_path)
    baseline = authority.store.settings
    monkeypatch.setattr(LocalSemanticRuntime, "validate_artifacts", lambda self: None)
    monkeypatch.setattr(LocalSemanticRuntime, "_check_descriptors", lambda self: None)
    head_path = baseline.journal_dir / "head"
    head_raw = head_path.read_bytes()
    injected = False

    def corrupt_journal_after_publication(path, content, **kwargs):
        nonlocal injected
        private_write(path, content, **kwargs)
        if path == args.config and not injected:
            injected = True
            published = load_settings(args.config)
            assert published.models.manifest_path == args.manifest
            if concurrent_policy_change:
                private_write(args.config, published.model_copy(update={"queue_limit": baseline.queue_limit + 1}).model_dump_json() + "\n", replace=True)
            private_write(head_path, b"invalid isolated journal head\n", replace=True)

    monkeypatch.setattr(cli, "private_write", corrupt_journal_after_publication)
    with pytest.raises(DomainError) as failed:
        await cli.execute(args)
    assert failed.value.code == "DELETION_BARRIER"
    assert failed.value.effect == EffectState.NOT_COMMITTED
    compensated = load_settings(args.config)
    assert compensated.models == baseline.models
    assert compensated.allowed_model_purposes == baseline.allowed_model_purposes
    assert compensated.queue_limit == baseline.queue_limit + int(concurrent_policy_change)
    intent = baseline.state_dir / "model-approval-intent.json"
    assert not intent.exists()
    monkeypatch.setattr(cli, "private_write", private_write)
    pending_config = args.config.read_bytes()
    with pytest.raises(DomainError) as blocked_retry:
        await cli.execute(args)
    assert blocked_retry.value.code == "DELETION_BARRIER"
    assert blocked_retry.value.effect == EffectState.NOT_STARTED
    assert args.config.read_bytes() == pending_config and not intent.exists()
    private_write(head_path, head_raw, replace=True)
    await assert_consumer_admission(args, authority.binding_id, authority.revision)

    result = await cli.execute(args)
    assert result["approved"] is True
    assert not intent.exists()
    assert load_settings(args.config).queue_limit == compensated.queue_limit
    await assert_consumer_admission(args, authority.binding_id, result["route_revision"])


async def test_initial_authority_close_failure_cannot_publish_model_approval(authority, tmp_path, monkeypatch):
    args = approval_request(authority, tmp_path)
    baseline = authority.store.settings
    original = args.config.read_bytes()
    monkeypatch.setattr(LocalSemanticRuntime, "validate_artifacts", lambda self: None)
    monkeypatch.setattr(LocalSemanticRuntime, "_check_descriptors", lambda self: None)
    close = Store.close
    failed = False
    async with authority.store.pool.acquire() as connection:
        routes = await connection.fetch("SELECT purpose,revision,epoch FROM am_routes ORDER BY purpose")

    async def fail_initial_close(self):
        nonlocal failed
        await close(self)
        if not failed and self.settings.models == baseline.models:
            failed = True
            raise DomainError("DATABASE_UNAVAILABLE", "Synthetic initial authority close failure", status=503, effect=EffectState.UNKNOWN)

    monkeypatch.setattr(Store, "close", fail_initial_close)
    with pytest.raises(DomainError) as denied:
        await cli.execute(args)
    assert denied.value.code == "DATABASE_UNAVAILABLE"
    assert args.config.read_bytes() == original
    assert not (baseline.state_dir / "model-approval-intent.json").exists()
    async with authority.store.pool.acquire() as connection:
        assert await connection.fetch("SELECT purpose,revision,epoch FROM am_routes ORDER BY purpose") == routes


async def test_failed_compensation_keeps_exact_retry_recoverable_without_overwriting_conflict(authority, tmp_path, monkeypatch):
    args = approval_request(authority, tmp_path)
    baseline = authority.store.settings
    monkeypatch.setattr(LocalSemanticRuntime, "validate_artifacts", lambda self: None)
    monkeypatch.setattr(LocalSemanticRuntime, "_check_descriptors", lambda self: None)
    reconcile = Store.reconcile_journal
    calls = 0

    async def fail_second_authority(self, *values, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise DomainError("DELETION_BARRIER", "Synthetic independent journal barrier", status=503)
        return await reconcile(self, *values, **kwargs)

    def fail_compensation(path, content, **kwargs):
        if path == args.config and json.loads(content)["models"]["manifest_path"] == str(baseline.models.manifest_path):
            raise OSError("Synthetic compensation publication failure")
        return private_write(path, content, **kwargs)

    monkeypatch.setattr(Store, "reconcile_journal", fail_second_authority)
    monkeypatch.setattr(cli, "private_write", fail_compensation)
    with pytest.raises(DomainError) as failed:
        await cli.execute(args)
    assert failed.value.effect == EffectState.UNKNOWN
    published = load_settings(args.config)
    assert published.models.manifest_path == args.manifest
    intent = baseline.state_dir / "model-approval-intent.json"
    assert TOKEN not in intent.read_text() and baseline.database_dsn not in intent.read_text()
    head = baseline.journal_dir / "head"
    head_before = head.read_bytes()
    pending = intent.read_bytes()
    private_write(head, "invalid pending-approval journal head\n", replace=True)
    with pytest.raises(DomainError) as barred:
        await cli.execute(args)
    assert barred.value.code == "DELETION_BARRIER" and barred.value.effect == EffectState.UNKNOWN
    assert intent.read_bytes() == pending and load_settings(args.config) == published
    private_write(head, head_before, replace=True)
    monkeypatch.setattr(Store, "reconcile_journal", reconcile)
    monkeypatch.setattr(cli, "private_write", private_write)
    conflicting = published.model_copy(update={"models": published.models.model_copy(update={"cpu_threads": 9})})
    private_write(args.config, conflicting.model_dump_json() + "\n", replace=True)
    conflict_raw = args.config.read_bytes()
    with pytest.raises(DomainError) as conflict:
        await cli.execute(args)
    assert conflict.value.code == "MODEL_APPROVAL_CONFLICT"
    assert conflict.value.effect == EffectState.UNKNOWN
    assert args.config.read_bytes() == conflict_raw
    async with authority.store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT revision FROM am_routes WHERE purpose='embedding'") == authority.revision

    private_write(args.config, published.model_dump_json() + "\n", replace=True)
    result = await cli.execute(args)
    await assert_consumer_admission(args, authority.binding_id, result["route_revision"])
    assert not (baseline.state_dir / "model-approval-intent.json").exists()


async def test_unknown_route_commit_retains_published_config_and_reconciles_exact_retry(authority, tmp_path, monkeypatch):
    args = approval_request(authority, tmp_path)
    monkeypatch.setattr(LocalSemanticRuntime, "validate_artifacts", lambda self: None)
    monkeypatch.setattr(LocalSemanticRuntime, "_check_descriptors", lambda self: None)
    configure = Store.configure_route

    async def lose_commit_response(self, actor, revision, purposes, enabled):
        await configure(self, actor, revision, purposes, enabled)
        raise DomainError("DATABASE_UNAVAILABLE", "Synthetic lost commit response", status=503, effect=EffectState.UNKNOWN)

    monkeypatch.setattr(Store, "configure_route", lose_commit_response)
    with pytest.raises(DomainError) as failed:
        await cli.execute(args)
    assert failed.value.effect == EffectState.UNKNOWN
    published = load_settings(args.config)
    assert published.models.manifest_path == args.manifest
    await assert_consumer_admission(args, authority.binding_id, published.models.revision())
    async with cli.authority(args) as (_, store, actor):
        admission = await store.admit_read(actor, authority.binding_id, (), published.models.revision(), "embedding")
    private_write(args.config, published.model_copy(update={"queue_limit": published.queue_limit + 1}).model_dump_json() + "\n", replace=True)
    monkeypatch.setattr(Store, "configure_route", configure)
    result = await cli.execute(args)
    assert load_settings(args.config).queue_limit == published.queue_limit + 1
    await assert_consumer_admission(args, authority.binding_id, result["route_revision"])
    assert not (published.state_dir / "model-approval-intent.json").exists()
    async with cli.authority(args) as (_, store, _):
        with pytest.raises(DomainError) as stale:
            await store.admitted_claims(admission)
    assert stale.value.code == "ADMISSION_STALE"


async def test_unauthorized_model_approval_has_no_config_route_or_intent_effect(authority, tmp_path):
    args = approval_request(authority, tmp_path)
    secret = "denied-model-approval-" + "x" * 32
    await authority.store.issue_token(authority.actor, Role.AGENT, (authority.binding_id,), secret)
    private_write(args.token_file, secret + "\n", replace=True)
    original = args.config.read_bytes()
    async with authority.store.pool.acquire() as connection:
        routes = await connection.fetch("SELECT purpose,revision,epoch FROM am_routes ORDER BY purpose")
    with pytest.raises(DomainError) as denied:
        await cli.execute(args)
    assert denied.value.code == "ROLE_DENIED"
    assert denied.value.effect == EffectState.NOT_STARTED
    assert args.config.read_bytes() == original
    assert not (authority.store.settings.state_dir / "model-approval-intent.json").exists()
    async with authority.store.pool.acquire() as connection:
        assert await connection.fetch("SELECT purpose,revision,epoch FROM am_routes ORDER BY purpose") == routes


@pytest.mark.parametrize("change", ["operator", "agent", "generation", "revoke"])
async def test_model_approval_cannot_adopt_under_a_changed_credential(authority, tmp_path, monkeypatch, change):
    args = approval_request(authority, tmp_path)
    baseline = authority.store.settings
    replacement = "replacement-model-approval-" + "x" * 32
    role = Role.AGENT if change == "agent" else Role.OPERATOR
    await authority.store.issue_token(authority.actor, role, (authority.binding_id,), replacement)
    monkeypatch.setattr(LocalSemanticRuntime, "validate_artifacts", lambda self: None)
    monkeypatch.setattr(LocalSemanticRuntime, "_check_descriptors", lambda self: None)
    reconcile = Store.reconcile_journal
    calls = 0
    async with authority.store.pool.acquire() as connection:
        routes = await connection.fetch("SELECT purpose,revision,epoch FROM am_routes ORDER BY purpose")

    async def change_after_publication(self, *values, **kwargs):
        nonlocal calls
        calls += 1
        result = await reconcile(self, *values, **kwargs)
        if calls == 2:
            current = load_settings(args.config)
            private_write(args.config, current.model_copy(update={"queue_limit": baseline.queue_limit + 1}).model_dump_json() + "\n", replace=True)
            if change in {"operator", "agent"}:
                private_write(args.token_file, replacement + "\n", replace=True)
            elif change == "generation":
                async with self.pool.acquire() as connection:
                    await connection.execute("UPDATE am_credentials SET generation=generation+1 WHERE id=$1", authority.actor.credential_id)
            else:
                await self.revoke_token(authority.actor, authority.actor.credential_id)
        return result

    monkeypatch.setattr(Store, "reconcile_journal", change_after_publication)
    with pytest.raises(DomainError) as denied:
        await cli.execute(args)
    assert denied.value.code == "AUTH_DENIED"
    assert denied.value.effect == EffectState.NOT_COMMITTED
    restored = load_settings(args.config)
    assert restored.models == baseline.models
    assert restored.allowed_model_purposes == baseline.allowed_model_purposes
    assert restored.queue_limit == baseline.queue_limit + 1
    assert not (baseline.state_dir / "model-approval-intent.json").exists()
    async with authority.store.pool.acquire() as connection:
        assert await connection.fetch("SELECT purpose,revision,epoch FROM am_routes ORDER BY purpose") == routes
    if change != "agent":
        monkeypatch.setattr(Store, "reconcile_journal", reconcile)
        private_write(args.token_file, replacement + "\n", replace=True)
        result = await cli.execute(args)
        await assert_consumer_admission(args, authority.binding_id, result["route_revision"])


@pytest.mark.parametrize("change", ("revoke", "restore"))
async def test_pending_approval_requires_explicit_current_operator_supersession(authority, tmp_path, monkeypatch, change):
    args = approval_request(authority, tmp_path)
    monkeypatch.setattr(LocalSemanticRuntime, "validate_artifacts", lambda self: None)
    monkeypatch.setattr(LocalSemanticRuntime, "_check_descriptors", lambda self: None)
    configure = Store.configure_route

    async def lose_commit_response(self, actor, revision, purposes, enabled):
        await configure(self, actor, revision, purposes, enabled)
        raise DomainError("DATABASE_UNAVAILABLE", "Lost adoption response", status=503, effect=EffectState.UNKNOWN)

    monkeypatch.setattr(Store, "configure_route", lose_commit_response)
    with pytest.raises(DomainError) as lost:
        await cli.execute(args)
    assert lost.value.effect == EffectState.UNKNOWN
    intent = authority.store.settings.state_dir / "model-approval-intent.json"
    pending = intent.read_bytes()
    config_before = args.config.read_bytes()
    fresh_token = "fresh-pending-approval-operator-" + "n" * 32
    store = authority.store
    if change == "restore":
        store.settings = store.settings.model_copy(update={"migrator_dsn": store.settings.database_dsn})
        await store.recover_after_restore(authority.actor.id, fresh_token, store.journal.verify()["head"])
        async with store.pool.acquire() as connection:
            assert not await connection.fetchval("SELECT bool_or(enabled) FROM am_routes")
    else:
        await store.issue_token(authority.actor, Role.OPERATOR, (authority.binding_id,), fresh_token)
        await store.revoke_token(authority.actor, authority.actor.credential_id)
    with pytest.raises(DomainError) as revoked:
        await store.authenticate(TOKEN)
    assert revoked.value.code == "AUTH_DENIED"
    private_write(args.token_file, fresh_token + "\n", replace=True)
    monkeypatch.setattr(Store, "configure_route", configure)
    with pytest.raises(DomainError) as implicit:
        await cli.execute(args)
    assert implicit.value.code == "MODEL_APPROVAL_CONFLICT" and implicit.value.effect == EffectState.UNKNOWN
    assert intent.read_bytes() == pending and args.config.read_bytes() == config_before
    args.supersede_pending_intent = "0" * 64
    with pytest.raises(DomainError) as wrong:
        await cli.execute(args)
    assert wrong.value.code == "MODEL_APPROVAL_CONFLICT"
    assert intent.read_bytes() == pending and args.config.read_bytes() == config_before
    args.supersede_pending_intent = hashlib.sha256(pending).hexdigest()
    approved = await cli.execute(args)
    assert not intent.exists()
    await assert_consumer_admission(args, authority.binding_id, approved["route_revision"])


@pytest.mark.parametrize("failure", ("replacement", "barrier"))
async def test_failed_supersession_keeps_the_earlier_unknown_intent(authority, tmp_path, monkeypatch, failure):
    args = approval_request(authority, tmp_path)
    monkeypatch.setattr(LocalSemanticRuntime, "validate_artifacts", lambda self: None)
    monkeypatch.setattr(LocalSemanticRuntime, "_check_descriptors", lambda self: None)
    configure = Store.configure_route

    async def lose_commit_response(self, actor, revision, purposes, enabled):
        await configure(self, actor, revision, purposes, enabled)
        raise DomainError("DATABASE_UNAVAILABLE", "Lost adoption response", status=503, effect=EffectState.UNKNOWN)

    monkeypatch.setattr(Store, "configure_route", lose_commit_response)
    with pytest.raises(DomainError) as lost:
        await cli.execute(args)
    assert lost.value.effect == EffectState.UNKNOWN
    intent = authority.store.settings.state_dir / "model-approval-intent.json"
    pending, config_before = intent.read_bytes(), args.config.read_bytes()
    fresh_token = "fresh-supersede-failure-operator-" + "f" * 32
    await authority.store.issue_token(authority.actor, Role.OPERATOR, (authority.binding_id,), fresh_token)
    await authority.store.revoke_token(authority.actor, authority.actor.credential_id)
    private_write(args.token_file, fresh_token + "\n", replace=True)
    monkeypatch.setattr(Store, "configure_route", configure)
    args.supersede_pending_intent = hashlib.sha256(pending).hexdigest()
    if failure == "replacement":
        def refuse_intent_replacement(path, content, **kwargs):
            if path == intent:
                raise OSError("Synthetic intent replacement failure")
            return private_write(path, content, **kwargs)

        monkeypatch.setattr(cli, "private_write", refuse_intent_replacement)
        expected = ("MODEL_APPROVAL_RECOVERY_REQUIRED", EffectState.UNKNOWN)
    else:
        head_path = authority.store.settings.journal_dir / "head"
        head_raw = head_path.read_bytes()

        def corrupt_journal_after_replacement(path, content, **kwargs):
            private_write(path, content, **kwargs)
            if path == intent and content != pending:
                private_write(head_path, b"invalid isolated journal head\n", replace=True)

        monkeypatch.setattr(cli, "private_write", corrupt_journal_after_replacement)
        expected = ("DELETION_BARRIER", EffectState.NOT_COMMITTED)
    with pytest.raises(DomainError) as failed:
        await cli.execute(args)
    assert (failed.value.code, failed.value.effect) == expected
    assert intent.read_bytes() == pending and args.config.read_bytes() == config_before
    monkeypatch.setattr(cli, "private_write", private_write)
    if failure == "barrier":
        private_write(head_path, head_raw, replace=True)
    approved = await cli.execute(args)
    assert not intent.exists()
    await assert_consumer_admission(args, authority.binding_id, approved["route_revision"])


async def test_same_revision_purpose_narrowing_fences_the_running_old_service(authority, tmp_path, monkeypatch):
    args = approval_request(authority, tmp_path)
    args.manifest = authority.store.settings.models.manifest_path
    args.purpose = ["embedding"]
    monkeypatch.setattr(LocalSemanticRuntime, "validate_artifacts", lambda self: None)
    monkeypatch.setattr(LocalSemanticRuntime, "_check_descriptors", lambda self: None)
    store, actor = authority.store, authority.actor
    omitted = await store.admit_read(actor, authority.binding_id, (), authority.revision, "rerank")
    retained = await store.admit_read(actor, authority.binding_id, (), authority.revision, "embedding")
    approved = await cli.execute(args)
    assert approved["route_revision"] == authority.revision
    with pytest.raises(DomainError) as new_omitted:
        await store.admit_read(actor, authority.binding_id, (), authority.revision, "rerank")
    assert new_omitted.value.code == "MODEL_ROUTE_BLOCKED"
    with pytest.raises(DomainError) as old_omitted:
        await store.admitted_claims(omitted)
    assert old_omitted.value.code == "MODEL_ROUTE_BLOCKED"
    with pytest.raises(DomainError) as stale_retained:
        await store.admitted_claims(retained)
    assert stale_retained.value.code == "ADMISSION_STALE"
    await assert_consumer_admission(args, authority.binding_id, authority.revision)


async def test_invalid_model_artifacts_fail_before_config_route_or_recovery_publication(authority, tmp_path):
    args = approval_request(authority, tmp_path)
    original = args.config.read_bytes()
    async with authority.store.pool.acquire() as connection:
        routes = await connection.fetch("SELECT purpose,revision,epoch FROM am_routes ORDER BY purpose")
    with pytest.raises(DomainError) as denied:
        await cli.execute(args)
    assert denied.value.effect == EffectState.NOT_STARTED
    assert args.config.read_bytes() == original
    assert not (authority.store.settings.state_dir / "model-approval-intent.json").exists()
    async with authority.store.pool.acquire() as connection:
        assert await connection.fetch("SELECT purpose,revision,epoch FROM am_routes ORDER BY purpose") == routes


async def test_interrupted_post_publication_approval_resumes_exact_intent(authority, tmp_path, monkeypatch):
    args = approval_request(authority, tmp_path)
    monkeypatch.setattr(LocalSemanticRuntime, "validate_artifacts", lambda self: None)
    monkeypatch.setattr(LocalSemanticRuntime, "_check_descriptors", lambda self: None)
    reconcile = Store.reconcile_journal
    calls = 0

    async def interrupt_second_authority(self, *values, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise asyncio.CancelledError
        return await reconcile(self, *values, **kwargs)

    monkeypatch.setattr(Store, "reconcile_journal", interrupt_second_authority)
    with pytest.raises(asyncio.CancelledError):
        await cli.execute(args)
    published = load_settings(args.config)
    assert published.models.manifest_path == args.manifest
    assert (published.state_dir / "model-approval-intent.json").exists()
    async with authority.store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT revision FROM am_routes WHERE purpose='embedding'") == authority.revision
    monkeypatch.setattr(Store, "reconcile_journal", reconcile)
    result = await cli.execute(args)
    await assert_consumer_admission(args, authority.binding_id, result["route_revision"])
    assert not (published.state_dir / "model-approval-intent.json").exists()


async def test_config_durability_failure_after_replace_compensates_before_exact_retry(authority, tmp_path, monkeypatch):
    args = approval_request(authority, tmp_path)
    baseline = authority.store.settings
    monkeypatch.setattr(LocalSemanticRuntime, "validate_artifacts", lambda self: None)
    monkeypatch.setattr(LocalSemanticRuntime, "_check_descriptors", lambda self: None)
    injected = False

    def lose_publication_response(path, content, **kwargs):
        nonlocal injected
        private_write(path, content, **kwargs)
        if path == args.config and not injected:
            injected = True
            raise OSError("Synthetic directory durability failure after replace")

    monkeypatch.setattr(cli, "private_write", lose_publication_response)
    with pytest.raises(DomainError) as failed:
        await cli.execute(args)
    assert failed.value.effect == EffectState.NOT_COMMITTED
    assert load_settings(args.config).models == baseline.models
    await assert_consumer_admission(args, authority.binding_id, authority.revision)
    monkeypatch.setattr(cli, "private_write", private_write)
    result = await cli.execute(args)
    await assert_consumer_admission(args, authority.binding_id, result["route_revision"])
