from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from test_store_authority import VECTOR, advance_manifest, command, extraction, ready_claim
from test_store_authority import authority as authority

import agents_memory.jobs as jobs
from agents_memory.application import Application
from agents_memory.config import ModelConfig
from agents_memory.domain import (
    Consolidation,
    ContextCommand,
    DomainError,
    EffectState,
    RuleApproval,
    RuleProposal,
    RuleScope,
)
from agents_memory.jobs import LeaseFrame, Worker


async def test_application_reflection_replay_survives_changed_corpus_route_and_drain(authority):
    store, actor = authority.store, authority.actor
    source, claim = await ready_claim(authority)
    request = ContextCommand(
        binding_id=authority.binding_id, query="Explain CacheKey", mode="reflect",
        idempotency_key="application-reflection-retry", causal_operation=source.id,
    )
    original = await store.submit_reflection(actor, request, (claim.id,))
    await store.capture(actor, command(authority, "changed-corpus", "DifferentKey is retained offline."))
    await store.configure_route(actor, authority.revision, store.settings.allowed_model_purposes, False)
    application = Application(store.settings, store, None)
    application.accepting = False
    replay = await application.context(actor, request)
    assert replay["id"] == original.id
    assert replay["source_id"] == original.source_id
    with pytest.raises(DomainError) as caught:
        await application.context(actor, request.model_copy(update={"query": "Changed caller request"}))
    assert caught.value.code == "IDEMPOTENCY_CONFLICT"


class PausedExtraction:
    def __init__(self, revision):
        self.revision = revision
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def extract(self, source):
        self.started.set()
        await self.release.wait()
        return extraction(source.id)

    async def embed(self, texts):
        return [VECTOR for _ in texts]


class ManualHeartbeatWorker(Worker):
    def __init__(self, application):
        super().__init__(application)
        self.ticks = asyncio.Queue()

    def tick(self):
        self.ticks.put_nowait(None)

    async def _pulse(self, frame, finished):
        complete = finished.set

        def finish():
            complete()
            self.tick()

        async def wait():
            await self.ticks.get()
            if not finished.is_set():
                raise TimeoutError
            return True

        finished.set = finish
        finished.wait = wait
        await super()._pulse(frame, finished)


async def final_attempt(store, operation):
    async with store.pool.acquire() as connection:
        await connection.execute("UPDATE am_jobs SET attempts=$2 WHERE operation_id=$1", operation.id, store.settings.job_attempt_limit - 1)
    lease = await store.claim_job()
    assert lease.operation_id == operation.id and lease.attempts == store.settings.job_attempt_limit
    return lease


async def test_worker_admission_captured_before_heartbeat_uses_current_owner(authority, monkeypatch):
    store, actor = authority.store, authority.actor
    operation = await store.capture(actor, command(authority, "admission-renewal-race"))
    lease = await final_attempt(store, operation)
    captured, renewed = asyncio.Event(), asyncio.Event()
    admit, heartbeat = store.admit_job, store.heartbeat

    async def delayed_admit(current, revision, purpose):
        assert current == lease
        captured.set()
        await renewed.wait()
        return await admit(current, revision, purpose)

    async def renew(current):
        result = await heartbeat(current)
        renewed.set()
        return result

    monkeypatch.setattr(store, "admit_job", delayed_admit)
    monkeypatch.setattr(store, "heartbeat", renew)
    runtime = PausedExtraction(authority.revision)
    worker = ManualHeartbeatWorker(Application(store.settings, store, runtime))
    task = asyncio.create_task(worker._process(lease))
    try:
        await asyncio.wait_for(captured.wait(), 5)
        worker.tick()
        await asyncio.wait_for(runtime.started.wait(), 5)
    finally:
        runtime.release.set()
        await asyncio.wait_for(task, 5)
    monkeypatch.setattr(store, "admit_job", admit)
    monkeypatch.setattr(store, "heartbeat", heartbeat)
    consolidation = await store.claim_job()
    admitted = await store.admit_job(consolidation, authority.revision, "consolidation")
    await store.publish_consolidation(consolidation, admitted, Consolidation(relations=()))
    final = await store.operation(actor, authority.binding_id, operation.id)
    assert final.state == "semantic_ready" and final.error_code is None
    assert worker.last_job_error is None
    assert (await store.stats(actor, authority.binding_id))["active_claims"] == 1
    with pytest.raises(DomainError) as stale:
        await heartbeat(lease)
    assert stale.value.code == "LEASE_STALE"
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT attempts FROM am_jobs WHERE id=$1", lease.job_id) == store.settings.job_attempt_limit


@pytest.mark.parametrize("failure", ("barrier", "database", "unexpected"))
async def test_worker_transient_heartbeat_preserves_final_attempt_and_healthy_result(authority, monkeypatch, failure):
    store, actor = authority.store, authority.actor
    operation = await store.capture(actor, command(authority, "healthy-worker-result"))
    lease = await final_attempt(store, operation)
    unrelated = await store.capture(actor, command(authority, "unrelated-heartbeat-withdrawal")) if failure == "barrier" else None
    unavailable, renewed = asyncio.Event(), asyncio.Event()
    heartbeat = store.heartbeat
    calls = 0

    async def pulse(current):
        nonlocal calls
        calls += 1
        try:
            if calls == 1 and failure == "database":
                raise DomainError("DATABASE_UNAVAILABLE", "Temporary heartbeat connection failure", status=503, effect=EffectState.UNKNOWN)
            if calls == 1 and failure == "unexpected":
                raise RuntimeError("Temporary heartbeat transport failure")
            result = await heartbeat(current)
        except Exception:
            unavailable.set()
            raise
        renewed.set()
        return result

    monkeypatch.setattr(store, "heartbeat", pulse)
    runtime = PausedExtraction(authority.revision)
    worker = ManualHeartbeatWorker(Application(store.settings, store, runtime))
    task = asyncio.create_task(worker._process(lease))
    try:
        await asyncio.wait_for(runtime.started.wait(), 5)
        if failure == "barrier":
            appended = await asyncio.to_thread(store.journal.append, authority.binding_id,
                (unrelated.source_id,), ("unrelated-heartbeat-withdrawal",))
        worker.tick()
        await asyncio.wait_for(unavailable.wait(), 5)
        if failure == "barrier":
            await store.reconcile_journal(appended["head"])
        worker.tick()
        await asyncio.wait_for(renewed.wait(), 5)
    finally:
        runtime.release.set()
        await asyncio.wait_for(task, 5)
    consolidation = await store.claim_job()
    admitted = await store.admit_job(consolidation, authority.revision, "consolidation")
    await store.publish_consolidation(consolidation, admitted, Consolidation(relations=()))
    final = await store.operation(actor, authority.binding_id, operation.id)
    assert final.state == "semantic_ready" and final.error_code is None
    assert worker.last_job_error is None and calls == 2
    assert (await store.stats(actor, authority.binding_id))["active_claims"] == 1
    if failure == "barrier":
        assert (await store.operation(actor, authority.binding_id, unrelated.id)).state == "retracted"
    async with store.pool.acquire() as connection:
        row = await connection.fetchrow("SELECT state,attempts FROM am_jobs WHERE id=$1", lease.job_id)
        assert row["state"] == "done" and row["attempts"] == store.settings.job_attempt_limit


async def test_lost_heartbeat_commit_does_not_relax_exact_publication_fence(authority, monkeypatch):
    store, actor = authority.store, authority.actor
    await store.capture(actor, command(authority, "lost-heartbeat-result"))
    lease = await store.claim_job()
    unavailable, stale = asyncio.Event(), asyncio.Event()
    heartbeat = store.heartbeat
    calls = 0

    async def pulse(current):
        nonlocal calls
        calls += 1
        try:
            await heartbeat(current)
        except DomainError as error:
            assert error.code == "LEASE_STALE"
            stale.set()
            raise
        unavailable.set()
        raise DomainError("DATABASE_UNAVAILABLE", "The committed renewal response was lost", status=503, effect=EffectState.UNKNOWN)

    monkeypatch.setattr(store, "heartbeat", pulse)
    runtime = PausedExtraction(authority.revision)
    worker = ManualHeartbeatWorker(Application(store.settings, store, runtime))
    task = asyncio.create_task(worker._process(lease))
    try:
        await asyncio.wait_for(runtime.started.wait(), 5)
        worker.tick()
        await asyncio.wait_for(unavailable.wait(), 5)
        worker.tick()
        await asyncio.wait_for(stale.wait(), 5)
    finally:
        runtime.release.set()
        await asyncio.wait_for(task, 5)
    assert worker.last_job_error == "LEASE_STALE" and calls == 2
    assert (await store.stats(actor, authority.binding_id))["active_claims"] == 0
    async with store.pool.acquire() as connection:
        row = await connection.fetchrow("SELECT state,attempts,deadline FROM am_jobs WHERE id=$1", lease.job_id)
        assert row["state"] == "leased" and row["attempts"] == lease.attempts and row["deadline"] > lease.deadline


@pytest.mark.parametrize("code", ("LEASE_STALE", "AUTH_DENIED", "ADMISSION_STALE", "INPUT_INELIGIBLE"))
async def test_terminal_heartbeat_errors_stop_without_retry(authority, monkeypatch, code):
    store = authority.store
    await store.capture(authority.actor, command(authority, "terminal-heartbeat"))
    lease = await store.claim_job()
    failure = DomainError(code, "Terminal worker authority change")
    calls = 0

    async def heartbeat(current):
        nonlocal calls
        calls += 1
        raise failure

    async def tick():
        raise TimeoutError

    monkeypatch.setattr(store, "heartbeat", heartbeat)
    finished = asyncio.Event()
    monkeypatch.setattr(finished, "wait", tick)
    frame = LeaseFrame(lease)
    await Worker(Application(store.settings, store, None))._pulse(frame, finished)
    assert frame.failure is failure and calls == 1 and frame.current == lease


async def test_transient_heartbeat_retries_end_at_confirmed_monotonic_deadline(authority, monkeypatch):
    store = authority.store
    operation = await store.capture(authority.actor, command(authority, "bounded-heartbeat"))
    lease = await store.claim_job()
    unrelated = await store.capture(authority.actor, command(authority, "bounded-unrelated-withdrawal"))
    await asyncio.to_thread(store.journal.append, authority.binding_id,
        (unrelated.source_id,), ("bounded-unrelated-withdrawal",))
    now = lease.deadline - timedelta(seconds=25)
    elapsed = 0
    calls = 0
    heartbeat = store.heartbeat

    class Clock:
        @staticmethod
        def now(zone):
            return now

    async def tick():
        nonlocal elapsed
        elapsed = min(25, elapsed + store.settings.heartbeat_seconds)
        raise TimeoutError

    async def pulse(current):
        nonlocal calls
        calls += 1
        return await heartbeat(current)

    monkeypatch.setattr(jobs, "datetime", Clock)
    monkeypatch.setattr(jobs, "monotonic", lambda: elapsed)
    monkeypatch.setattr(store, "heartbeat", pulse)
    finished = asyncio.Event()
    monkeypatch.setattr(finished, "wait", tick)
    frame = LeaseFrame(lease)
    await Worker(Application(store.settings, store, None))._pulse(frame, finished)
    assert frame.failure.code == "LEASE_STALE" and frame.current == lease
    assert calls == 2 and elapsed == 25
    async with store.pool.acquire() as connection:
        row = await connection.fetchrow("SELECT state,attempts FROM am_jobs WHERE operation_id=$1", operation.id)
        assert row["state"] == "leased" and row["attempts"] == lease.attempts


async def test_worker_cannot_publish_generation_completed_after_source_retraction(authority):
    store, actor = authority.store, authority.actor
    operation = await store.capture(actor, command(authority, "worker-retraction-race"))
    lease = await store.claim_job()
    runtime = PausedExtraction(authority.revision)
    application = Application(store.settings, store, runtime)
    worker = Worker(application)
    task = asyncio.create_task(worker._process(lease))
    try:
        await asyncio.wait_for(runtime.started.wait(), 5)
        await store.retract(actor, authority.binding_id, operation.source_id, "withdraw-during-generation")
    finally:
        runtime.release.set()
        await asyncio.wait_for(task, 5)
    final = await store.operation(actor, authority.binding_id, operation.id)
    assert final.state == "retracted"
    assert (await store.stats(actor, authority.binding_id))["active_claims"] == 0
    assert await store.search(actor, authority.binding_id, VECTOR, ["CacheKey"], None) == []


async def test_worker_unapproved_runtime_route_is_visible_blocked_not_empty_success(authority):
    store, actor = authority.store, authority.actor
    operation = await store.capture(actor, command(authority, "worker-route-blocked"))
    lease = await store.claim_job()
    worker = Worker(Application(store.settings, store, None))
    await worker._process(lease)
    final = await store.operation(actor, authority.binding_id, operation.id)
    assert final.state == "blocked"
    assert final.error_code == "MODEL_ROUTE_BLOCKED"
    assert (await store.stats(actor, authority.binding_id))["active_claims"] == 0


class EmbeddingOnly:
    def __init__(self, revision):
        self.revision = revision

    async def embed(self, texts):
        return [VECTOR for _ in texts]


async def test_worker_reindexes_existing_evidence_without_regenerating_semantics(authority):
    store, actor = authority.store, authority.actor
    _, claim = await ready_claim(authority)
    original_revision = authority.revision
    advance_manifest(authority, embedding=True)
    await store.configure_route(actor, authority.revision, ("embedding",), True)
    before = await store.search(actor, authority.binding_id, VECTOR, ["CacheKey"], None)
    assert "vector" not in next(arms for item, arms in before if item.id == claim.id)
    operation = await store.recover_index(actor, authority.binding_id, (claim.id,), "worker-index-upgrade")
    lease = await store.claim_job()

    await Worker(Application(store.settings, store, EmbeddingOnly(authority.revision)))._process(lease)

    assert (await store.operation(actor, authority.binding_id, operation.id)).state == "semantic_ready"
    assert await store.claim(actor, authority.binding_id, claim.id) == claim
    after = await store.search(actor, authority.binding_id, VECTOR, ["CacheKey"], None)
    assert "vector" in next(arms for item, arms in after if item.id == claim.id)
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT route_revision FROM am_claims WHERE id=$1", claim.id) == original_revision


class BusyExtraction:
    def __init__(self, revision):
        self.revision = revision

    async def extract(self, source):
        raise DomainError("MODEL_BUSY", "The local provider is serving another request", status=503)


async def test_transient_provider_contention_remains_automatically_retryable(authority):
    store, actor = authority.store, authority.actor
    operation = await store.capture(actor, command(authority, "busy-worker"))
    lease = await store.claim_job()

    await Worker(Application(store.settings, store, BusyExtraction(authority.revision)))._process(lease)

    result = await store.operation(actor, authority.binding_id, operation.id)
    assert result.state == "pending" and result.error_code == "MODEL_BUSY"
    async with store.pool.acquire() as connection:
        row = await connection.fetchrow(
            "SELECT state,available_at>clock_timestamp() AS backed_off FROM am_jobs WHERE id=$1", lease.job_id,
        )
        assert row["state"] == "pending" and row["backed_off"]
        await connection.execute("UPDATE am_jobs SET available_at=clock_timestamp()-interval '1 second' WHERE id=$1", lease.job_id)
    retry = await store.claim_job()
    assert retry.operation_id == operation.id and retry.attempts == 2
    assert retry.source_ids == lease.source_ids


async def test_required_rule_body_remains_deliverable_before_any_model_is_configured(authority):
    store, actor = authority.store, authority.actor
    store.settings = store.settings.model_copy(update={"models": ModelConfig(), "allowed_model_purposes": ()})
    proposal = await store.propose_rule(actor, RuleProposal(
        binding_id=authority.binding_id, idempotency_key="manifestless-rule", body="Keep company artifacts inside this project.", required=True,
    ))
    await store.approve_rule(actor, RuleApproval(
        proposal_id=proposal["proposal_id"], expected_digest=proposal["digest"], scope=RuleScope.LOCAL_PROJECT,
        target_bindings=(authority.binding_id,), target_set_revision=proposal["target_set_revision"],
        idempotency_key="manifestless-rule-approval",
    ))

    result = await Application(store.settings, store, None).context(
        actor, ContextCommand(binding_id=authority.binding_id, query="Project convention"),
    )

    assert "Keep company artifacts inside this project." in result["context"]
    assert result["refs"] == []
