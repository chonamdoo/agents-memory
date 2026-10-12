from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import asyncpg
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from agents_memory.config import ModelConfig, Settings
from agents_memory.domain import (
    CaptureCommand,
    CitedSentence,
    ClaimDraft,
    Consolidation,
    ContextCommand,
    DomainError,
    Extraction,
    Principal,
    Quote,
    RecordCommand,
    ReflectionDraft,
    RelationDraft,
    Role,
    RuleApproval,
    RuleProposal,
    RuleScope,
    approval_signing_payload,
)
from agents_memory.journal import DeletionJournal
from agents_memory.migrations import migrate
from agents_memory.store import Store

VECTOR = [1.0, *([0.0] * 1023)]
TOKEN = "operator-storage-boundary-credential-" + "a" * 32


@dataclass
class Authority:
    store: Store
    actor: Principal
    binding_id: str
    revision: str


@pytest_asyncio.fixture
async def authority(tmp_path):
    raw_dsn = os.environ.get("PG_TEST_DSN")
    if not raw_dsn:
        pytest.skip("PG_TEST_DSN explicitly required for isolated PostgreSQL authority regressions")
    parts = urlsplit(raw_dsn)
    query = dict(parse_qsl(parts.query))
    query.pop("schema", None)
    admin_dsn = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    schema = "am_test_" + uuid.uuid4().hex
    admin = await asyncpg.connect(admin_dsn)
    store = None
    try:
        await admin.execute(f'CREATE SCHEMA "{schema}"')
        query["schema"] = schema
        dsn = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
        await asyncio.to_thread(migrate, dsn)
        manifest = tmp_path / "boundary-manifest.json"
        artifact = tmp_path / "embedding-fixture.bin"
        artifact.write_bytes(b"isolated storage compatibility fixture")
        manifest.write_text(json.dumps({"schema": 1, "storage_boundary_fixture": schema, "embedding": {
            "repo": "storage-test-embedding", "revision": "fixture-A", "dimensions": 1024,
            "pooling": "cls", "normalized": True, "runtime": "storage-test-only",
            "artifacts": [{"path": str(artifact), "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                "bytes": artifact.stat().st_size}],
        }}))
        settings = Settings(deployment_id="deployment_test", realm="personal_test", mode="personal", database_dsn=dsn,
            state_dir=tmp_path / "restore-unit", journal_dir=tmp_path / "independent-journal",
            models=ModelConfig(manifest_path=manifest), allowed_model_purposes=("extraction", "embedding", "consolidation", "rerank", "reflection"))
        store = Store(settings, DeletionJournal(settings.journal_dir, settings.deployment_id))
        await store.open()
        actor = await store.bootstrap(TOKEN, "owner_test")
        binding = await store.register_binding(actor, "Isolated project", None, "binding-registration")
        actor = await store.authenticate(TOKEN)
        revision = settings.models.revision()
        await store.configure_route(actor, revision, settings.allowed_model_purposes, True)
        yield Authority(store, actor, binding.id, revision)
    finally:
        if store is not None:
            await store.close()
        await admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await admin.close()


def command(authority, key="capture", body="CacheKey is retained only offline.", origin=None, snapshot=None):
    return CaptureCommand(binding_id=authority.binding_id, idempotency_key=key, origin_key=origin or key,
        body=body, speaker="human", snapshot=snapshot)


def extraction(source_id, quote="CacheKey is retained only offline.", offset=0, statement=None):
    return Extraction(claims=(ClaimDraft(statement=statement or quote, kind="fact", subject="CacheKey", predicate="retained", object="offline",
        polarity="positive", modality="asserted", conditions=("only offline",), entities=("CacheKey",),
        evidence=(Quote(source_id=source_id, quote=quote, byte_start=offset),)),))


async def ready_claim(authority, key="capture", body="CacheKey is retained only offline.", snapshot=None):
    store, actor = authority.store, authority.actor
    operation = await store.capture(actor, command(authority, key, body, snapshot=snapshot))
    lease = await store.claim_job()
    assert lease is not None and lease.operation_id == operation.id and lease.kind == "extract"
    admission = await store.admit_job(lease, authority.revision, "extraction")
    await store.publish_extraction(lease, admission, extraction(operation.source_id, body), [VECTOR], [["CacheKey", "offline"]])
    consolidation = await store.claim_job()
    assert consolidation is not None and consolidation.kind == "consolidate"
    consolidation_admission = await store.admit_job(consolidation, authority.revision, "consolidation")
    await store.publish_consolidation(consolidation, consolidation_admission, Consolidation(relations=()))
    claims = await store.search(actor, authority.binding_id, VECTOR, ["CacheKey"], snapshot)
    own = next(claim for claim, _ in claims if operation.source_id in claim.input_source_ids)
    return operation, own


async def recall_context(authority, snapshot=None):
    from agents_memory.application import Application
    from agents_memory.domain import RankedClaim

    class RecallFixture:
        revision = authority.revision

        async def embed(self, texts):
            return [VECTOR for _ in texts]

        async def rerank(self, query, candidates):
            return [RankedClaim(claim_id=claim.id, score=1.0) for claim in candidates]

    application = Application(authority.store.settings, authority.store, RecallFixture())
    return await application.context(authority.actor, ContextCommand(
        binding_id=authority.binding_id, query="CacheKey", snapshot=snapshot))


async def test_snapshot_statistics_include_only_eligible_indexed_memory(authority):
    store, actor = authority.store, authority.actor
    operation = await store.capture(actor, command(authority, snapshot="revision-A"))
    lease = await store.claim_job()
    admission = await store.admit_job(lease, authority.revision, "extraction")
    await store.publish_extraction(lease, admission, extraction(operation.source_id), [VECTOR], [["CacheKey"]])
    current = await store.stats(actor, authority.binding_id, "revision-A")
    other = await store.stats(actor, authority.binding_id, "revision-B")
    assert (current["active_sources"], current["active_claims"]) == (1, 1)
    assert (other["active_sources"], other["active_claims"]) == (0, 0)


async def test_duplicate_capture_and_origin_replay_do_not_duplicate_evidence(authority):
    store, actor = authority.store, authority.actor
    original = command(authority)
    results = await asyncio.gather(*(store.capture(actor, original) for _ in range(8)))
    assert len({result.id for result in results}) == 1
    lost_response_replay = await store.capture(actor, original)
    assert lost_response_replay.id == results[0].id
    origin_replay = await store.capture(actor, original.model_copy(update={"idempotency_key": "another-receipt"}))
    assert origin_replay.id == results[0].id
    with pytest.raises(DomainError) as conflict:
        await store.capture(actor, original.model_copy(update={"body": "Changed evidence"}))
    assert conflict.value.code == "IDEMPOTENCY_CONFLICT"
    with pytest.raises(DomainError) as origin_conflict:
        await store.capture(actor, original.model_copy(update={"idempotency_key": "changed-origin-receipt", "body": "Changed evidence"}))
    assert origin_conflict.value.code == "ORIGIN_CONFLICT"
    stats = await store.stats(actor, authority.binding_id)
    assert stats["active_sources"] == 1
    assert stats["historical_jobs"] == {"pending": 1}


async def test_admission_accepts_renewed_owner_without_relaxing_heartbeat_or_publication(authority):
    store, actor = authority.store, authority.actor
    operation = await store.capture(actor, command(authority))
    original = await store.claim_job()
    renewed = await store.heartbeat(original)

    admission = await store.admit_job(original, authority.revision, "extraction")
    assert admission.lease_token == renewed.lease_token and admission.generation == renewed.generation
    assert [source.id for source in await store.admitted_sources(admission)] == [operation.source_id]
    with pytest.raises(DomainError) as stale_heartbeat:
        await store.heartbeat(original)
    assert stale_heartbeat.value.code == "LEASE_STALE"
    with pytest.raises(DomainError) as stale_publication:
        await store.publish_extraction(original, admission, extraction(operation.source_id), [VECTOR], [["CacheKey"]])
    assert stale_publication.value.code == "LEASE_STALE"
    assert (await store.stats(actor, authority.binding_id))["active_claims"] == 0
    await store.publish_extraction(renewed, admission, extraction(operation.source_id), [VECTOR], [["CacheKey"]])
    consolidation = await store.claim_job()
    admitted = await store.admit_job(consolidation, authority.revision, "consolidation")
    await store.publish_consolidation(consolidation, admitted, Consolidation(relations=()))
    assert (await store.operation(actor, authority.binding_id, operation.id)).state == "semantic_ready"


@pytest.mark.parametrize("field", (
    "job_id", "lease_token", "generation", "deadline", "kind", "binding_id", "operation_id",
    "credential_id", "source_ids", "claim_ids", "query_source_id", "attempts",
))
async def test_renewed_admission_retains_complete_lease_identity(authority, field):
    store, actor = authority.store, authority.actor
    await store.capture(actor, command(authority))
    original = await store.claim_job()
    renewed = await store.heartbeat(original)
    changed = {
        "job_id": original.job_id + "_changed", "lease_token": original.lease_token + "_changed",
        "generation": original.generation + 1, "deadline": renewed.deadline + timedelta(seconds=1),
        "kind": "consolidate", "binding_id": original.binding_id + "_changed",
        "operation_id": original.operation_id + "_changed", "credential_id": original.credential_id + "_changed",
        "source_ids": (*original.source_ids, "source_changed"), "claim_ids": ("claim_changed",),
        "query_source_id": "source_changed", "attempts": original.attempts + 1,
    }
    supplied = original.model_copy(update={field: changed[field]})
    with pytest.raises(DomainError) as stale:
        await store.admit_job(supplied, authority.revision, "consolidation" if field == "kind" else "extraction")
    assert stale.value.code == "LEASE_STALE"
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT count(*) FROM am_admissions") == 0


@pytest.mark.parametrize("change", ("expiry", "reclaim", "revoke", "credential_generation", "retract"))
async def test_renewed_admission_still_rejects_expired_or_invalid_authority(authority, change):
    store, actor = authority.store, authority.actor
    producer = await store.issue_token(actor, Role.PRODUCER, (authority.binding_id,), "renewed-admission-producer-" + "b" * 32)
    operation = await store.capture(producer, command(authority))
    original = await store.claim_job()
    renewed = await store.heartbeat(original)
    admission = await store.admit_job(original, authority.revision, "extraction")
    expected = "LEASE_STALE"
    if change in {"expiry", "reclaim"}:
        async with store.pool.acquire() as connection:
            await connection.execute("UPDATE am_jobs SET deadline=clock_timestamp()-interval '1 second' WHERE id=$1", renewed.job_id)
        if change == "reclaim":
            reclaimed = await store.claim_job()
            assert reclaimed.generation > renewed.generation and reclaimed.lease_token != renewed.lease_token
    elif change == "revoke":
        await store.revoke_token(actor, producer.credential_id)
        expected = "AUTH_DENIED"
    elif change == "credential_generation":
        async with store.pool.acquire() as connection:
            await connection.execute("UPDATE am_credentials SET generation=generation+1 WHERE id=$1", producer.credential_id)
        expected = "AUTH_DENIED"
    else:
        await store.retract(actor, authority.binding_id, operation.source_id, "withdraw-renewed-input")
    with pytest.raises(DomainError) as stale:
        await store.admit_job(original, authority.revision, "extraction")
    assert stale.value.code == expected
    with pytest.raises(DomainError):
        await store.publish_extraction(renewed, admission, extraction(operation.source_id), [VECTOR], [["CacheKey"]])
    assert (await store.stats(actor, authority.binding_id))["active_claims"] == 0


async def test_expired_and_renewed_lease_cannot_publish_or_create_followups(authority):
    store, actor = authority.store, authority.actor
    operation = await store.capture(actor, command(authority))
    original = await store.claim_job()
    admission = await store.admit_job(original, authority.revision, "extraction")
    renewed = await store.heartbeat(original)
    with pytest.raises(DomainError) as old_heartbeat:
        await store.heartbeat(original)
    assert old_heartbeat.value.code == "LEASE_STALE"
    with pytest.raises(DomainError):
        await store.publish_extraction(original, admission, extraction(operation.source_id), [VECTOR], [["CacheKey"]])
    async with store.pool.acquire() as connection:
        await connection.execute("UPDATE am_jobs SET deadline=clock_timestamp()-interval '1 second' WHERE id=$1", renewed.job_id)
    reclaimed = await store.claim_job()
    assert reclaimed.job_id == original.job_id and reclaimed.generation > renewed.generation
    with pytest.raises(DomainError):
        await store.publish_extraction(renewed, admission, extraction(operation.source_id), [VECTOR], [["CacheKey"]])
    assert (await store.stats(actor, authority.binding_id))["active_claims"] == 0
    current_admission = await store.admit_job(reclaimed, authority.revision, "extraction")
    await store.publish_extraction(reclaimed, current_admission, extraction(operation.source_id), [VECTOR], [["CacheKey"]])
    assert (await store.stats(actor, authority.binding_id))["historical_jobs"] == {"done": 1, "pending": 1}


@pytest.mark.parametrize("change", ("retract", "revoke", "route_roundtrip"))
async def test_authority_change_during_inference_blocks_publication(authority, change):
    store, actor = authority.store, authority.actor
    producer = await store.issue_token(actor, Role.PRODUCER, (authority.binding_id,), "producer-boundary-token-" + "b" * 32)
    operation = await store.capture(producer, command(authority))
    lease = await store.claim_job()
    admission = await store.admit_job(lease, authority.revision, "extraction")
    if change == "retract":
        outcome = await store.retract(actor, authority.binding_id, operation.source_id, "retract-inflight")
        assert outcome["local_drain"] == "local_drain_pending"
        assert outcome["provider_completion"] == "provider_completion_unknown"
        assert outcome["physical_purge"] == "not_purged"
    elif change == "revoke":
        await store.revoke_token(actor, producer.credential_id)
    else:
        await store.configure_route(actor, authority.revision, ("extraction",), False)
        await store.configure_route(actor, authority.revision, ("extraction",), True)
    with pytest.raises(DomainError):
        await store.publish_extraction(lease, admission, extraction(operation.source_id), [VECTOR], [["CacheKey"]])
    assert (await store.stats(actor, authority.binding_id))["active_claims"] == 0


async def test_unrelated_clock_change_does_not_invalidate_actual_inputs(authority):
    store, actor = authority.store, authority.actor
    operation = await store.capture(actor, command(authority))
    lease = await store.claim_job()
    admission = await store.admit_job(lease, authority.revision, "extraction")
    await store.capture(actor, command(authority, "unrelated", "OtherKey is independent."))
    assert await store.recheck(admission) > admission.epoch
    await store.publish_extraction(lease, admission, extraction(operation.source_id), [VECTOR], [["CacheKey"]])
    assert (await store.stats(actor, authority.binding_id))["active_claims"] == 1


async def test_exact_utf8_repeated_span_never_uses_normalized_evidence(authority):
    store, actor = authority.store, authority.actor
    body = "한글 Ａ 한글 Ａ"
    operation = await store.capture(actor, command(authority, body=body))
    lease = await store.claim_job()
    admission = await store.admit_job(lease, authority.revision, "extraction")
    ambiguous = extraction(operation.source_id, "한글", None)
    with pytest.raises(DomainError) as repeated:
        await store.publish_extraction(lease, admission, ambiguous, [VECTOR], [["한글"]])
    assert repeated.value.code == "EVIDENCE_AMBIGUOUS"
    normalized = extraction(operation.source_id, "A", len("한글 ".encode()))
    with pytest.raises(DomainError) as normalization:
        await store.publish_extraction(lease, admission, normalized, [VECTOR], [["A"]])
    assert normalization.value.code == "EVIDENCE_INVALID"
    offset = body.encode().rfind("한글".encode())
    await store.publish_extraction(lease, admission, extraction(operation.source_id, "한글", offset), [VECTOR], [["한글"]])
    claims = await store.search(actor, authority.binding_id, VECTOR, ["한글"], None)
    assert claims[0][0].evidence[0].byte_start == offset
    assert claims[0][0].evidence[0].quote == "한글"


async def test_uncited_reflection_input_retraction_invalidates_entire_artifact(authority):
    store, actor = authority.store, authority.actor
    _, first = await ready_claim(authority, "first")
    second_operation, second = await ready_claim(authority, "second", "CacheKey is retained only offline after review.")
    reflection_operation = await store.submit_reflection(actor, ContextCommand(binding_id=authority.binding_id, query="Describe CacheKey", mode="reflect", idempotency_key="reflection"), (first.id, second.id))
    lease = await store.claim_job()
    admission = await store.admit_job(lease, authority.revision, "reflection")
    result = ReflectionDraft(sentences=(CitedSentence(text=first.draft.statement, claim_ids=(first.id,)),))
    published = await store.publish_reflection(lease, admission, result)
    assert published.id == reflection_operation.id
    assert (await store.inspect(actor, authority.binding_id, published.artifact_id))["state"] == "active"
    await store.retract(actor, authority.binding_id, second_operation.source_id, "uncited-input")
    hidden = await store.inspect(actor, authority.binding_id, published.artifact_id)
    assert hidden["state"] == "retracted" and "sentences" not in hidden
    assert (await store.operation(actor, authority.binding_id, published.id)).state == "retracted"
    assert (await store.claim(actor, authority.binding_id, first.id)).id == first.id


async def test_stale_restore_and_origin_replay_cannot_resurrect_deleted_source(authority):
    store, actor = authority.store, authority.actor
    operation, claim = await ready_claim(authority)
    old_head = store.journal.verify()["head"]
    result = await store.retract(actor, authority.binding_id, operation.source_id, "delete-before-restore")
    source_token = store.journal.source_token(operation.source_id)
    origin_token = store.journal.origin_token(authority.binding_id, "capture")
    async with store.pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute("UPDATE am_sources SET state='active',revision=1 WHERE id=$1", operation.source_id)
            await connection.execute("UPDATE am_claims SET state='active' WHERE id=$1", claim.id)
            await connection.execute("UPDATE am_operations SET state='semantic_ready',error_code=NULL WHERE id=$1", operation.id)
            await connection.execute("DELETE FROM am_floors WHERE token=ANY($1::text[])", [source_token, origin_token])
            await connection.execute("UPDATE am_clock SET journal_head=$1 WHERE singleton", old_head)
    with pytest.raises(DomainError) as barrier:
        await store.source(actor, authority.binding_id, operation.source_id)
    assert barrier.value.code == "DELETION_BARRIER"
    with pytest.raises(DomainError):
        await store.reconcile_journal(old_head)
    reconciliation = await store.reconcile_journal(result["head"])
    assert reconciliation["reapplied_sources"] == 1
    with pytest.raises(DomainError):
        await store.claim(actor, authority.binding_id, claim.id)
    replay = await store.capture(actor, command(authority, key="spool-replay", origin="capture"))
    assert replay.id == operation.id and replay.state == "retracted"
    metadata = await store.inspect(actor, authority.binding_id, operation.source_id)
    assert "body" not in metadata
    purged = await store.purge(actor, authority.binding_id, operation.source_id, "physical")
    assert purged["physical_purge"] == "physically_purged"
    assert purged["backup_retention"] == "unknown"
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT body IS NULL FROM am_sources WHERE id=$1", operation.source_id)
        assert await connection.fetchval("SELECT draft IS NULL AND embedding IS NULL FROM am_claims WHERE id=$1", claim.id)


async def test_conflicting_concurrent_retraction_key_never_deletes_both_targets(authority):
    store, actor = authority.store, authority.actor
    first = await store.capture(actor, command(authority, "first"))
    second = await store.capture(actor, command(authority, "second"))
    results = await asyncio.gather(store.retract(actor, authority.binding_id, first.source_id, "same-delete-key"), store.retract(actor, authority.binding_id, second.source_id, "same-delete-key"), return_exceptions=True)
    assert sum(isinstance(result, dict) for result in results) == 1
    error = next(result for result in results if isinstance(result, DomainError))
    assert error.code == "IDEMPOTENCY_CONFLICT"
    assert (await store.stats(actor, authority.binding_id))["active_sources"] == 1
    assert len(store.journal.entries()) == 1


async def test_rule_candidate_roster_digest_and_frozen_three_scopes(authority):
    store, actor = authority.store, authority.actor
    agent = await store.issue_token(actor, Role.AGENT, (authority.binding_id,), "agent-boundary-token-" + "c" * 32)
    operation = await store.record(agent, RecordCommand(binding_id=authority.binding_id, idempotency_key="candidate", body="Keep CacheKey offline.", kind="rule_candidate"))
    assert operation.artifact_id and not await store.rules(actor, authority.binding_id)
    proposal = await store.inspect(actor, authority.binding_id, operation.artifact_id)
    approval = RuleApproval(proposal_id=proposal["id"], expected_digest=proposal["digest"], scope=RuleScope.LOCAL_PROJECT, target_bindings=(authority.binding_id,), target_set_revision=proposal["target_set_revision"], idempotency_key="approval")
    with pytest.raises(DomainError):
        await store.approve_rule(agent, approval)
    local = await store.approve_rule(actor, approval)
    other = await store.register_binding(actor, "Other project", None, "another-binding")
    actor = await store.authenticate(TOKEN)
    assert (await store.rules(actor, authority.binding_id))[0].id == local.id
    assert not await store.rules(actor, other.id)
    stale = await store.propose_rule(actor, RuleProposal(binding_id=authority.binding_id, idempotency_key="stale", body="Review before writing."))
    await store.register_binding(actor, "New roster entry", None, "roster-change")
    with pytest.raises(DomainError) as roster:
        await store.approve_rule(actor, RuleApproval(proposal_id=stale["proposal_id"], expected_digest=stale["digest"], scope=RuleScope.MY_PROJECTS, target_bindings=(authority.binding_id, other.id), target_set_revision=stale["target_set_revision"], idempotency_key="stale-approval"))
    assert roster.value.code == "APPROVAL_STALE"
    for scope in (RuleScope.MY_PROJECTS, RuleScope.SHARED):
        candidate = await store.propose_rule(actor, RuleProposal(binding_id=authority.binding_id, idempotency_key=scope.value, body="Review CacheKey."))
        approved = RuleApproval(proposal_id=candidate["proposal_id"], expected_digest=candidate["digest"], scope=scope, target_bindings=(authority.binding_id, other.id), target_set_revision=candidate["target_set_revision"], idempotency_key="approve-" + scope.value)
        active = await store.approve_rule(actor, approved)
        assert set(active.target_bindings) == {authority.binding_id, other.id}
        with pytest.raises(DomainError) as changed:
            await store.approve_rule(actor, approved.model_copy(update={"target_bindings": (authority.binding_id,)}))
        assert changed.value.code == "IDEMPOTENCY_CONFLICT"
    assert {rule.scope for rule in await store.rules(actor, authority.binding_id)} == set(RuleScope)


async def test_initial_local_approval_survives_unrelated_roster_addition(authority):
    store, actor = authority.store, authority.actor
    proposal = await store.propose_rule(actor, RuleProposal(binding_id=authority.binding_id,
        idempotency_key="local-before-roster-change", body="Keep CacheKey offline."))
    unrelated = await store.register_binding(actor, "Later unrelated project", None, "initial-local-roster-addition")
    actor = await store.authenticate(TOKEN)
    approval = RuleApproval(proposal_id=proposal["proposal_id"], expected_digest=proposal["digest"],
        scope=RuleScope.LOCAL_PROJECT, target_bindings=(authority.binding_id,),
        target_set_revision=proposal["target_set_revision"], idempotency_key="local-after-roster-change")
    active = await store.approve_rule(actor, approval)
    assert active.body == "Keep CacheKey offline." and active.target_bindings == (authority.binding_id,)
    assert not await store.rules(actor, unrelated.id)


@pytest.mark.parametrize("scope", tuple(RuleScope))
async def test_frozen_reapproval_survives_roster_growth_without_widening(authority, scope):
    store, actor = authority.store, authority.actor
    other = await store.register_binding(actor, "Existing exact project", None, "frozen-existing-project")
    actor = await store.authenticate(TOKEN)
    proposal = await store.propose_rule(actor, RuleProposal(binding_id=authority.binding_id,
        idempotency_key="frozen-before-growth", body="Keep CacheKey offline."))
    targets = (authority.binding_id,) if scope == RuleScope.LOCAL_PROJECT else tuple(sorted((authority.binding_id, other.id)))
    approval = RuleApproval(proposal_id=proposal["proposal_id"], expected_digest=proposal["digest"],
        scope=scope, target_bindings=targets, target_set_revision=proposal["target_set_revision"],
        idempotency_key="first-frozen-approval")
    active = await store.approve_rule(actor, approval)
    await store.withdraw_rule(actor, authority.binding_id, active.id, "withdraw-before-roster-growth")
    async with store.pool.acquire() as connection:
        retired_revision = await connection.fetchval("SELECT revision FROM am_rules WHERE id=$1", active.id)
    later = await store.register_binding(actor, "Later project outside frozen set", None, "frozen-roster-growth")
    actor = await store.authenticate(TOKEN)
    reapproval = approval.model_copy(update={"idempotency_key": "exact-reapproval-after-growth"})
    changed_scope = RuleScope.SHARED if scope != RuleScope.SHARED else RuleScope.MY_PROJECTS
    with pytest.raises(DomainError) as changed:
        await store.approve_rule(actor, reapproval.model_copy(update={"scope": changed_scope}))
    assert changed.value.code == "APPROVAL_CONFLICT"
    with pytest.raises(DomainError) as widened:
        await store.approve_rule(actor, reapproval.model_copy(update={"target_bindings": (*targets, later.id)}))
    assert widened.value.code in {"APPROVAL_CONFLICT", "TARGET_SET_INVALID"}
    revised = await store.approve_rule(actor, reapproval)
    assert revised.id != active.id and revised.revision > retired_revision
    assert revised.body == active.body and revised.digest == active.digest and revised.target_bindings == targets
    assert await store.approve_rule(actor, reapproval) == revised
    assert not await store.rules(actor, later.id)
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT target_set_revision FROM am_rules WHERE id=$1", revised.id) == proposal["target_set_revision"]


async def test_company_shared_requires_exact_configured_signer_not_a_boolean(authority, tmp_path):
    store, actor = authority.store, authority.actor
    store.settings = store.settings.model_copy(update={"mode": "company"})
    proposal = await store.propose_rule(actor, RuleProposal(binding_id=authority.binding_id, idempotency_key="company", body="Keep data local."))
    approval = RuleApproval(proposal_id=proposal["proposal_id"], expected_digest=proposal["digest"], scope=RuleScope.SHARED,
        target_bindings=(authority.binding_id,), target_set_revision=proposal["target_set_revision"], idempotency_key="company-approval")
    with pytest.raises(DomainError) as unavailable:
        await store.approve_rule(actor, approval)
    assert unavailable.value.code == "SHARED_APPROVAL_UNAVAILABLE"
    signer = Ed25519PrivateKey.generate()
    public = tmp_path / "managed-public.pem"
    public.write_bytes(signer.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
    store.settings = store.settings.model_copy(update={"strong_shared_approval": True, "approver_public_key": public})
    with pytest.raises(DomainError) as missing:
        await store.approve_rule(actor, approval)
    assert missing.value.code == "SHARED_APPROVAL_DENIED"
    signature = base64.b64encode(signer.sign(approval_signing_payload(store.settings.deployment_id, store.settings.realm, actor.id, approval))).decode()
    signed = approval.model_copy(update={"approver_signature": signature})
    with pytest.raises(DomainError) as changed:
        await store.approve_rule(actor, signed.model_copy(update={"expected_digest": "0" * 64}))
    assert changed.value.code == "SHARED_APPROVAL_DENIED"
    assert (await store.approve_rule(actor, signed)).scope == RuleScope.SHARED
    active = (await store.rules(actor, authority.binding_id))[0]
    await store.withdraw_rule(actor, authority.binding_id, active.id, "company-withdraw")
    unrelated = await store.register_binding(actor, "Unrelated company project", None, "company-roster-addition")
    actor = await store.authenticate(TOKEN)
    reapproval = signed.model_copy(update={"idempotency_key": "company-reapproval"})
    with pytest.raises(DomainError) as stale_signature:
        await store.approve_rule(actor, reapproval)
    assert stale_signature.value.code == "SHARED_APPROVAL_DENIED"
    new_signature = base64.b64encode(signer.sign(approval_signing_payload(
        store.settings.deployment_id, store.settings.realm, actor.id, reapproval))).decode()
    revised = await store.approve_rule(actor, reapproval.model_copy(update={"approver_signature": new_signature}))
    assert revised.id != active.id and revised.revision > active.revision
    assert revised.digest == active.digest and revised.body == active.body
    assert revised.target_bindings == active.target_bindings == (authority.binding_id,)
    assert not await store.rules(actor, unrelated.id)


async def test_forged_grants_and_cross_realm_metadata_do_not_reveal_existence(authority):
    store, actor = authority.store, authority.actor
    operation = await store.capture(actor, command(authority))
    other = await store.register_binding(actor, "Other project", None, "other")
    reader = await store.issue_token(actor, Role.AGENT, (other.id,), "scope-reader-token-" + "d" * 32)
    forged = reader.model_copy(update={"bindings": (other.id, authority.binding_id)})
    for action in (store.source(forged, authority.binding_id, operation.source_id), store.inspect(forged, authority.binding_id, operation.id), store.stats(forged, authority.binding_id)):
        with pytest.raises(DomainError) as denied:
            await action
        assert denied.value.code == "SCOPE_DENIED"
    with pytest.raises(DomainError) as realm:
        await store.inspect(actor.model_copy(update={"realm": "company_customer"}), authority.binding_id, operation.id)
    assert realm.value.code == "SCOPE_DENIED"


async def test_bounded_dead_letter_recovery_is_current_and_durable(authority):
    store, actor = authority.store, authority.actor
    store.settings = store.settings.model_copy(update={"queue_limit": 1, "job_attempt_limit": 1})
    operation = await store.capture(actor, command(authority))
    with pytest.raises(DomainError) as full:
        await store.capture(actor, command(authority, "overflow"))
    assert full.value.code == "QUEUE_FULL"
    lease = await store.claim_job()
    await store.fail_job(lease, "SEMANTIC_OUTPUT_INVALID")
    assert (await store.stats(actor, authority.binding_id))["dlq"] == 1
    await store.retry_job(actor, lease.job_id)
    recovered = await store.claim_job()
    assert recovered.generation > lease.generation and recovered.attempts == 1
    with pytest.raises(DomainError):
        await store.fail_job(lease, "LATE_FAILURE")
    admission = await store.admit_job(recovered, authority.revision, "extraction")
    terminal = await store.publish_extraction(recovered, admission, Extraction(claims=()), [], [])
    assert terminal.id == operation.id and terminal.state == "semantic_ready"
    assert (await store.stats(actor, authority.binding_id))["dlq"] == 0


async def test_delivery_rechecks_all_rules_and_actual_sources_at_one_stamp(authority):
    store, actor = authority.store, authority.actor
    operation, claim = await ready_claim(authority)
    query = await store.admit_read(actor, authority.binding_id, (), authority.revision, "embedding")
    rerank = await store.admit_read(actor, authority.binding_id, (claim.id,), authority.revision, "rerank")
    proposal = await store.propose_rule(actor, RuleProposal(binding_id=authority.binding_id, idempotency_key="mandatory", body="Review CacheKey before writing.", required=True))
    active = await store.approve_rule(actor, RuleApproval(proposal_id=proposal["proposal_id"], expected_digest=proposal["digest"],
        scope=RuleScope.LOCAL_PROJECT, target_bindings=(authority.binding_id,), target_set_revision=proposal["target_set_revision"], idempotency_key="mandatory-approval"))
    with pytest.raises(DomainError) as omitted_rule:
        await store.delivery(actor, authority.binding_id, (query, rerank), ())
    assert omitted_rule.value.code == "CONTEXT_STALE"
    versions = ((active.id, active.revision, active.digest),)
    delivered = await store.delivery(actor, authority.binding_id, (query, rerank), versions)
    assert delivered["epoch"] == delivered["stats"]["epoch"]
    assert delivered["stats"]["pending"] == 0
    await store.retract(actor, authority.binding_id, operation.source_id, "stale-delivery-input")
    with pytest.raises(DomainError) as stale_source:
        await store.delivery(actor, authority.binding_id, (query, rerank), versions)
    assert stale_source.value.code == "CONTEXT_STALE"


async def test_future_claims_consolidate_without_becoming_current_recall(authority):
    from datetime import UTC, datetime

    from agents_memory.domain import RelationDraft
    store, actor = authority.store, authority.actor
    body = "CacheKey is planned offline. CacheKey is retained only after review."
    operation = await store.capture(actor, command(authority, body=body))
    lease = await store.claim_job()
    admission = await store.admit_job(lease, authority.revision, "extraction")
    first = extraction(operation.source_id, "CacheKey is planned offline.", 0).claims[0].model_copy(update={
        "modality": "planned", "conditions": ("only offline",), "valid_from": datetime(2999, 1, 1, tzinfo=UTC)})
    second = extraction(operation.source_id, "CacheKey is retained only after review.", len(b"CacheKey is planned offline. ")).claims[0].model_copy(update={"conditions": ("after review",)})
    await store.publish_extraction(lease, admission, Extraction(claims=(first, second)), [VECTOR, VECTOR], [["CacheKey"], ["CacheKey"]])
    consolidation = await store.claim_job()
    admitted = await store.admit_job(consolidation, authority.revision, "consolidation")
    claims = await store.admitted_claims(admitted)
    assert len(claims) == 2
    left, right = claims
    with pytest.raises(DomainError) as condition_loss:
        await store.publish_consolidation(consolidation, admitted, Consolidation(relations=(RelationDraft(
            left_id=left.id, right_id=right.id, kind="duplicates", reason="Same identifier"),)))
    assert condition_loss.value.code == "RELATION_INVALID"
    await store.publish_consolidation(consolidation, admitted, Consolidation(relations=(RelationDraft(
        left_id=left.id, right_id=right.id, kind="conditional_variant", reason="Conditions and valid times differ"),)))
    recall = await store.search(actor, authority.binding_id, VECTOR, ["CacheKey"], None)
    assert len(recall) == 1 and recall[0][0].draft.valid_from is None


async def test_snapshot_filter_applies_before_vector_top_k(authority):
    store, actor = authority.store, authority.actor
    operation = await store.capture(actor, command(authority, snapshot="dirty_snapshot"))
    lease = await store.claim_job()
    admission = await store.admit_job(lease, authority.revision, "extraction")
    await store.publish_extraction(lease, admission, extraction(operation.source_id), [VECTOR], [["CacheKey"]])
    consolidation = await store.claim_job()
    admitted = await store.admit_job(consolidation, authority.revision, "consolidation")
    await store.publish_consolidation(consolidation, admitted, Consolidation(relations=()))
    assert not await store.search(actor, authority.binding_id, VECTOR, ["CacheKey"], None, limit=1)
    matching = await store.search(actor, authority.binding_id, VECTOR, ["CacheKey"], "dirty_snapshot", limit=1)
    assert len(matching) == 1
    with pytest.raises(DomainError):
        await store.admit_read(actor, authority.binding_id, (matching[0][0].id,), authority.revision, "rerank")
    current = await store.admit_read(actor, authority.binding_id, (matching[0][0].id,), authority.revision, "rerank", "dirty_snapshot")
    delivered = await store.delivery(actor, authority.binding_id, (current,), (), "dirty_snapshot")
    assert delivered["stats"]["active_claims"] == 1


async def test_shared_rule_does_not_disclose_ungranted_origin_or_target_ids(authority):
    store, actor = authority.store, authority.actor
    other = await store.register_binding(actor, "Shared audience project", None, "shared-audience")
    proposal = await store.propose_rule(actor, RuleProposal(binding_id=authority.binding_id, idempotency_key="shared-proposal", body="Keep CacheKey local."))
    active = await store.approve_rule(actor, RuleApproval(proposal_id=proposal["proposal_id"], expected_digest=proposal["digest"],
        scope=RuleScope.SHARED, target_bindings=(authority.binding_id, other.id), target_set_revision=proposal["target_set_revision"], idempotency_key="shared-approval"))
    reader = await store.issue_token(actor, Role.AGENT, (other.id,), "shared-audience-reader-" + "e" * 32)
    rules = await store.rules(reader, other.id)
    assert len(rules) == 1 and rules[0].id == active.id
    assert rules[0].target_bindings == (other.id,) and not rules[0].source_ids
    metadata = await store.inspect(reader, other.id, active.id)
    assert metadata["target_bindings"] == (other.id,)
    assert authority.binding_id not in json.dumps(metadata)
    assert proposal["source_id"] not in json.dumps(metadata)
    delivered = await store.delivery(reader, other.id, (), ((active.id, active.revision, active.digest),))
    assert delivered["epoch"] == delivered["stats"]["epoch"]


async def test_correction_key_is_reserved_before_any_destructive_intent(authority):
    store, actor = authority.store, authority.actor
    first = await store.capture(actor, command(authority, "first"))
    second = await store.capture(actor, command(authority, "second"))
    results = await asyncio.gather(
        store.correct(actor, authority.binding_id, first.source_id, command(authority, "same-correction", "CacheKey is never retained online.", "new-first")),
        store.correct(actor, authority.binding_id, second.source_id, command(authority, "same-correction", "CacheKey is retained after review.", "new-second")),
        return_exceptions=True)
    successes = [result for result in results if not isinstance(result, Exception)]
    assert len(successes) == 1
    error = next(result for result in results if isinstance(result, DomainError))
    assert error.code == "IDEMPOTENCY_CONFLICT"
    stats = await store.stats(actor, authority.binding_id)
    assert stats["active_sources"] == 2
    assert len(store.journal.entries()) == 1
    corrected = await store.source(actor, authority.binding_id, successes[0].source_id)
    assert corrected.speaker == "human"
    assert corrected.body in {"CacheKey is never retained online.", "CacheKey is retained after review."}


async def test_tombstoned_dead_letters_do_not_permanently_consume_backlog(authority):
    store, actor = authority.store, authority.actor
    store.settings = store.settings.model_copy(update={"queue_limit": 1, "job_attempt_limit": 1})
    operation = await store.capture(actor, command(authority))
    lease = await store.claim_job()
    await store.fail_job(lease, "SEMANTIC_OUTPUT_INVALID")
    await store.retract(actor, authority.binding_id, operation.source_id, "discard-retracted-dead-letter")
    assert (await store.stats(actor, authority.binding_id))["dlq"] == 0
    accepted = await store.capture(actor, command(authority, "next-origin"))
    assert accepted.state == "accepted"


async def test_private_restore_recovery_cannot_revive_tokens_rules_or_worker_leases(authority):
    store, actor = authority.store, authority.actor
    agent_token = "restore-agent-boundary-token-" + "g" * 32
    agent = await store.issue_token(actor, Role.AGENT, (authority.binding_id,), agent_token)
    candidate_command = RuleProposal(binding_id=authority.binding_id, idempotency_key="restore-candidate", body="Review CacheKey.")
    proposal = await store.propose_rule(actor, candidate_command)
    approval = RuleApproval(proposal_id=proposal["proposal_id"], expected_digest=proposal["digest"], scope=RuleScope.LOCAL_PROJECT,
        target_bindings=(authority.binding_id,), target_set_revision=proposal["target_set_revision"], idempotency_key="restore-approval")
    active = await store.approve_rule(actor, approval)
    await store.revoke_token(actor, agent.credential_id)
    await store.withdraw_rule(actor, authority.binding_id, active.id, "withdraw-before-backup-restore")
    operation = await store.capture(actor, command(authority))
    lease = await store.claim_job()
    admission = await store.admit_job(lease, authority.revision, "extraction")
    async with store.pool.acquire() as connection:
        await connection.execute("UPDATE am_credentials SET active=true,generation=1 WHERE id=$1", agent.credential_id)
        await connection.execute("UPDATE am_rules SET state='active',revision=1 WHERE id=$1", active.id)
    head = store.journal.verify()["head"]
    recovery_token = "restore-fresh-operator-token-" + "h" * 32
    with pytest.raises(DomainError) as not_private:
        await store.recover_after_restore(actor.id, recovery_token, head)
    assert not_private.value.code == "PRIVATE_RECOVERY_REQUIRED"
    store.settings = store.settings.model_copy(update={"migrator_dsn": store.settings.database_dsn})
    fresh = await store.recover_after_restore(actor.id, recovery_token, head)
    assert fresh.credential_id != actor.credential_id and fresh.bindings == (authority.binding_id,)
    for old_token in (TOKEN, agent_token):
        with pytest.raises(DomainError) as revoked:
            await store.authenticate(old_token)
        assert revoked.value.code == "AUTH_DENIED"
    with pytest.raises(DomainError):
        await store.publish_extraction(lease, admission, extraction(operation.source_id), [VECTOR], [["CacheKey"]])
    assert not await store.rules(fresh, authority.binding_id)
    with pytest.raises(DomainError) as receipt_replay:
        await store.approve_rule(fresh, approval)
    assert receipt_replay.value.code == "RULE_INELIGIBLE"
    reapproved = await store.approve_rule(fresh, approval.model_copy(update={"idempotency_key": "restore-exact-reapproval"}))
    assert reapproved.id != active.id and reapproved.revision > active.revision
    assert reapproved.digest == active.digest and reapproved.body == candidate_command.body
    assert [rule.id for rule in await store.rules(fresh, authority.binding_id)] == [reapproved.id]
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT approver_credential_id FROM am_rules WHERE id=$1", reapproved.id) == fresh.credential_id
        assert await connection.fetchval("SELECT state FROM am_rules WHERE id=$1", active.id) == "retracted"
    with pytest.raises(DomainError) as disabled:
        await store.admit_read(fresh, authority.binding_id, (), authority.revision, "embedding")
    assert disabled.value.code == "MODEL_ROUTE_BLOCKED"
    await store.configure_route(fresh, authority.revision, store.settings.allowed_model_purposes, True)
    await store.retry_job(fresh, lease.job_id)
    recovered = await store.claim_job()
    assert recovered.generation > lease.generation and recovered.credential_id == fresh.credential_id


async def test_racing_derived_origin_is_floored_before_a_pre_derivation_restore(authority):
    import threading
    store, actor = authority.store, authority.actor
    root = await store.capture(actor, command(authority, "root").model_copy(update={"root_run_id": "same-root-run"}))
    independent = await store.capture(actor, command(authority, "independent", "OtherKey is independent.").model_copy(update={"root_run_id": "same-root-run"}))
    old_head = store.journal.verify()["head"]

    class PausingJournal(DeletionJournal):
        def __init__(self, directory, deployment_id):
            super().__init__(directory, deployment_id)
            self.entered = threading.Event()
            self.release = threading.Event()

        def append(self, binding_id, source_ids, origin_keys):
            self.entered.set()
            if not self.release.wait(20):
                raise TimeoutError("The controlled append barrier was not released")
            return super().append(binding_id, source_ids, origin_keys)

    journal = PausingJournal(store.settings.journal_dir, store.settings.deployment_id)
    store.journal = journal
    deleting = asyncio.create_task(store.retract(actor, authority.binding_id, root.source_id, "racing-delete"))
    try:
        assert await asyncio.to_thread(journal.entered.wait, 20)
        proposal = await store.propose_rule(actor, RuleProposal(binding_id=authority.binding_id, idempotency_key="racing-derived",
            body="Review CacheKey.", source_ids=(root.source_id,)))
        derived = await store.source(actor, authority.binding_id, proposal["source_id"])
    finally:
        journal.release.set()
        outcome = await deleting
    assert (await store.source(actor, authority.binding_id, independent.source_id)).root_run_id == "same-root-run"
    with pytest.raises(DomainError):
        await store.source(actor, authority.binding_id, derived.id)
    source_token = journal.source_token(derived.id)
    origin_token = journal.origin_token(authority.binding_id, derived.origin_key)
    entries = journal.entries()
    assert any(source_token in entry["source_tokens"] and origin_token in entry["origin_tokens"] for entry in entries)
    async with store.pool.acquire() as connection:
        async with connection.transaction():
            derived_operation = await connection.fetchval("SELECT operation_id FROM am_sources WHERE id=$1", derived.id)
            await connection.execute("DELETE FROM am_proposal_sources WHERE proposal_id=$1", proposal["proposal_id"])
            await connection.execute("DELETE FROM am_proposals WHERE id=$1", proposal["proposal_id"])
            await connection.execute("DELETE FROM am_sources WHERE id=$1", derived.id)
            await connection.execute("DELETE FROM am_operations WHERE id=$1", derived_operation)
            await connection.execute("DELETE FROM am_receipts WHERE target_id=$1", proposal["proposal_id"])
            await connection.execute("UPDATE am_sources SET state='active',revision=1 WHERE id=$1", root.source_id)
            await connection.execute("UPDATE am_operations SET state='accepted',error_code=NULL WHERE id=$1", root.id)
            await connection.execute("UPDATE am_jobs SET state='pending',generation=1,error_code=NULL WHERE operation_id=$1", root.id)
            tokens = [source_token, origin_token, journal.source_token(root.source_id), journal.origin_token(authority.binding_id, "root")]
            await connection.execute("DELETE FROM am_floors WHERE token=ANY($1::text[])", tokens)
            await connection.execute("UPDATE am_clock SET journal_head=$1 WHERE singleton", old_head)
    await store.reconcile_journal(outcome["head"])
    replay = await store.capture(actor, CaptureCommand(binding_id=authority.binding_id, idempotency_key="derived-spool-replay",
        origin_key=derived.origin_key, body=derived.body, speaker="agent_note"))
    assert replay.state == "retracted" and replay.error_code == "ORIGIN_RETRACTED" and replay.source_id is None
    assert (await store.stats(actor, authority.binding_id))["active_sources"] == 1


async def published_reflection(authority, claims, key="reflection", snapshot=None):
    store, actor = authority.store, authority.actor
    request = ContextCommand(binding_id=authority.binding_id, query="Describe CacheKey", mode="reflect", idempotency_key=key, snapshot=snapshot)
    operation = await store.submit_reflection(actor, request, tuple(claim.id for claim in claims))
    lease = await store.claim_job()
    admission = await store.admit_job(lease, authority.revision, "reflection")
    result = ReflectionDraft(sentences=(CitedSentence(text=claims[0].draft.statement, claim_ids=(claims[0].id,)),))
    return request, await store.publish_reflection(lease, admission, result), operation


@pytest.mark.parametrize("change", ("corpus", "retract", "route", "revoke"))
async def test_reflection_replays_original_request_before_changed_selection(authority, change):
    store, actor = authority.store, authority.actor
    source, claim = await ready_claim(authority)
    request, published, _ = await published_reflection(authority, (claim,))
    async with store.pool.acquire() as connection:
        manifest = dict(await connection.fetchrow("SELECT source_ids,claim_ids FROM am_jobs WHERE operation_id=$1 AND kind='reflect'", published.id))
    if change == "corpus":
        await ready_claim(authority, "new-corpus", "CacheKey is retained only offline after review.")
    elif change == "retract":
        await store.retract(actor, authority.binding_id, source.source_id, "remove-original-input")
    elif change == "route":
        await store.configure_route(actor, authority.revision, store.settings.allowed_model_purposes, False)
    else:
        reader = await store.issue_token(actor, Role.AGENT, (authority.binding_id,), "reflection-reader-" + "r" * 32)
        await store.revoke_token(actor, reader.credential_id)
        with pytest.raises(DomainError) as revoked:
            await store.reflection_receipt(reader, request)
        assert revoked.value.code == "AUTH_DENIED"
    replay = await store.reflection_receipt(actor, request.model_copy(update={"binding_id": None}))
    assert replay.id == published.id
    assert (await store.submit_reflection(actor, request, ())).id == published.id
    async with store.pool.acquire() as connection:
        assert dict(await connection.fetchrow("SELECT source_ids,claim_ids FROM am_jobs WHERE operation_id=$1 AND kind='reflect'", published.id)) == manifest
        assert await connection.fetchval("SELECT count(*) FROM am_jobs WHERE operation_id=$1 AND kind='reflect'", published.id) == 1
    with pytest.raises(DomainError) as changed:
        await store.reflection_receipt(actor, request.model_copy(update={"query": "A different request"}))
    assert changed.value.code == "IDEMPOTENCY_CONFLICT"


async def test_existing_reflection_receipt_upgrades_only_matching_original_manifest(authority):
    from agents_memory.domain import canonical_digest

    store, actor = authority.store, authority.actor
    _, claim = await ready_claim(authority)
    request, published, _ = await published_reflection(authority, (claim,))
    old_digest = canonical_digest({"command": request.model_dump(mode="json"), "claim_ids": [claim.id]})
    async with store.pool.acquire() as connection:
        await connection.execute("UPDATE am_receipts SET digest=$1 WHERE target_id=$2 AND kind='reflect'", old_digest, published.id)
    assert (await store.reflection_receipt(actor, request)).id == published.id
    with pytest.raises(DomainError):
        await store.reflection_receipt(actor, request.model_copy(update={"paths": ("src/other.py",)}))


@pytest.mark.parametrize("change", ("expiry", "snapshot"))
async def test_reflection_inspect_rechecks_uncited_claim_current_eligibility(authority, change):
    store, actor = authority.store, authority.actor
    snapshot = "current-snapshot"
    _, first = await ready_claim(authority, "first", snapshot=snapshot)
    _, second = await ready_claim(authority, "second", "CacheKey is retained only offline after review.", snapshot=snapshot)
    _, published, _ = await published_reflection(authority, (first, second), snapshot=snapshot)
    assert (await store.inspect(actor, authority.binding_id, published.artifact_id, snapshot))["sentences"]
    expected = "CLAIM_INELIGIBLE"
    if change == "expiry":
        async with store.pool.acquire() as connection:
            await connection.execute("UPDATE am_claims SET valid_until=clock_timestamp()-interval '1 second' WHERE id=$1", second.id)
    else:
        snapshot = "other-snapshot"
        expected = "INPUT_INELIGIBLE"
    with pytest.raises(DomainError) as stale:
        await store.inspect(actor, authority.binding_id, published.artifact_id, snapshot=snapshot)
    assert stale.value.code == expected


@pytest.mark.parametrize("queue_state", ("pending", "leased", "blocked", "failed"))
@pytest.mark.parametrize("target_kind", ("source", "claim"))
async def test_related_withdrawal_preserves_live_read_and_completes_original_pipeline(authority, queue_state, target_kind):
    store, actor = authority.store, authority.actor
    first_operation, first = await ready_claim(authority, "first")
    capture = command(authority, "second", "CacheKey is retained offline after approval.")
    owner = await store.capture(actor, capture)
    extraction_lease = await store.claim_job()
    admitted = await store.admit_job(extraction_lease, authority.revision, "extraction")
    await store.publish_extraction(extraction_lease, admitted, extraction(owner.source_id, capture.body), [VECTOR], [["CacheKey"]])
    lease = await store.claim_job() if queue_state != "pending" else None
    admission_lease = lease
    if lease:
        lease = await store.heartbeat(lease)
    old_inputs = await store.admit_job(admission_lease, authority.revision, "consolidation") if lease else None
    if queue_state in {"blocked", "failed"}:
        store.settings = store.settings.model_copy(update={"job_attempt_limit": 1})
        await store.fail_job(lease, "MODEL_ROUTE_BLOCKED" if queue_state == "blocked" else "MODEL_OUTPUT_INVALID", blocked=queue_state == "blocked")
    target = first_operation.source_id if target_kind == "source" else first.id
    await store.retract(actor, authority.binding_id, target, "withdraw-related-only")
    assert (await store.source(actor, authority.binding_id, owner.source_id)).body == capture.body
    live = await store.search(actor, authority.binding_id, VECTOR, ["CacheKey"], None)
    assert len(live) == 1 and live[0][0].input_source_ids == (owner.source_id,)
    assert (await store.capture(actor, capture)).state == "pending"
    assert (await store.stats(actor, authority.binding_id))["pending"] == 1
    if lease:
        with pytest.raises(DomainError) as stale_admission:
            await store.admit_job(admission_lease, authority.revision, "consolidation")
        assert stale_admission.value.code == "LEASE_STALE"
        with pytest.raises(DomainError) as stale:
            await store.publish_consolidation(lease, old_inputs, Consolidation(relations=()))
        assert stale.value.code == "LEASE_STALE"
    recovered = await store.claim_job()
    assert recovered.operation_id == owner.id and recovered.claim_ids == (live[0][0].id,)
    assert recovered.source_ids == (owner.source_id,)
    if lease:
        assert recovered.generation > lease.generation
    current_inputs = await store.admit_job(recovered, authority.revision, "consolidation")
    complete = await store.publish_consolidation(recovered, current_inputs, Consolidation(relations=()))
    assert complete.id == owner.id and complete.state == "semantic_ready"
    assert (await store.capture(actor, capture)).state == "semantic_ready"
    assert (await store.operation(actor, authority.binding_id, owner.id)).state == "semantic_ready"
    assert (await store.stats(actor, authority.binding_id))["pending"] == 0
    from agents_memory.application import Application
    from agents_memory.domain import RankedClaim

    class RecallFixture:
        revision = authority.revision

        async def embed(self, texts):
            return [VECTOR for _ in texts]

        async def rerank(self, query, candidates):
            return [RankedClaim(claim_id=claim.id, score=1.0) for claim in candidates]

    application = Application(store.settings, store, RecallFixture())
    context = await application.context(actor, ContextCommand(binding_id=authority.binding_id,
        query="CacheKey", causal_operation=owner.id))
    assert capture.body in context["context"] and live[0][0].id in context["refs"]


async def test_own_source_withdrawal_retracts_pipeline_and_fences_current_worker(authority):
    store, actor = authority.store, authority.actor
    await ready_claim(authority, "related")
    owner = await store.capture(actor, command(authority, "own"))
    extract_lease = await store.claim_job()
    inputs = await store.admit_job(extract_lease, authority.revision, "extraction")
    await store.publish_extraction(extract_lease, inputs, extraction(owner.source_id), [VECTOR], [["CacheKey"]])
    lease = await store.claim_job()
    admission = await store.admit_job(lease, authority.revision, "consolidation")
    await store.retract(actor, authority.binding_id, owner.source_id, "withdraw-own-source")
    assert (await store.operation(actor, authority.binding_id, owner.id)).state == "retracted"
    with pytest.raises(DomainError) as deleted:
        await store.source(actor, authority.binding_id, owner.source_id)
    assert deleted.value.code == "SOURCE_INELIGIBLE"
    with pytest.raises(DomainError) as stale:
        await store.publish_consolidation(lease, admission, Consolidation(relations=()))
    assert stale.value.code == "LEASE_STALE"
    assert await store.claim_job() is None


@pytest.mark.parametrize("target_kind", ("source", "claim"))
async def test_relation_delivery_rechecks_uncited_third_input_lineage(authority, target_kind):
    store, actor = authority.store, authority.actor
    _, first = await ready_claim(authority, "first")
    _, second = await ready_claim(authority, "second")
    third_operation = await store.capture(actor, command(authority, "third"))
    lease = await store.claim_job()
    admitted = await store.admit_job(lease, authority.revision, "extraction")
    await store.publish_extraction(lease, admitted, extraction(third_operation.source_id), [VECTOR], [["CacheKey"]])
    consolidation = await store.claim_job()
    inputs = await store.admit_job(consolidation, authority.revision, "consolidation")
    third = next(claim for claim in await store.admitted_claims(inputs) if third_operation.source_id in claim.input_source_ids)
    await store.publish_consolidation(consolidation, inputs, Consolidation(relations=(RelationDraft(left_id=first.id, right_id=second.id, kind="contradicts", reason="Current alternatives disagree."),)))
    relations = await store.relations(actor, authority.binding_id, (first.id,))
    assert len(relations) == 1 and relations[0].left_id == first.id and relations[0].right_id == second.id
    rerank = await store.admit_read(actor, authority.binding_id, (first.id, second.id), authority.revision, "rerank")
    relation_ids = (relations[0].id,)
    await store.delivery(actor, authority.binding_id, (rerank,), (), relation_ids=relation_ids)
    target = third_operation.source_id if target_kind == "source" else third.id
    await store.retract(actor, authority.binding_id, target, "uncited-relation-input")
    assert await store.recheck(rerank)
    assert not await store.relations(actor, authority.binding_id, (first.id, second.id))
    with pytest.raises(DomainError) as stale:
        await store.delivery(actor, authority.binding_id, (rerank,), (), relation_ids=relation_ids)
    assert stale.value.code == "CONTEXT_STALE"


@pytest.mark.parametrize("action", ("correct", "retract"))
async def test_derived_claim_deletion_preserves_upstream_sibling_and_survives_restore(authority, action):
    store, actor = authority.store, authority.actor
    body = "CacheKey is retained only offline. OtherKey is retained only offline."
    source = await store.capture(actor, command(authority, body=body))
    lease = await store.claim_job()
    admitted = await store.admit_job(lease, authority.revision, "extraction")
    first_draft = extraction(source.source_id).claims[0]
    second_draft = extraction(source.source_id, "OtherKey is retained only offline.", len(b"CacheKey is retained only offline. ")).claims[0].model_copy(update={"subject": "OtherKey", "entities": ("OtherKey",)})
    await store.publish_extraction(lease, admitted, Extraction(claims=(first_draft, second_draft)), [VECTOR, VECTOR], [["CacheKey"], ["OtherKey"]])
    consolidation = await store.claim_job()
    inputs = await store.admit_job(consolidation, authority.revision, "consolidation")
    claims = await store.admitted_claims(inputs)
    first = next(claim for claim in claims if claim.draft.subject == "CacheKey")
    sibling = next(claim for claim in claims if claim.draft.subject == "OtherKey")
    await store.publish_consolidation(consolidation, inputs, Consolidation(relations=()))
    _, reflection, _ = await published_reflection(authority, (first, sibling))
    old_head = store.journal.verify()["head"]
    if action == "correct":
        await store.correct(actor, authority.binding_id, first.id, command(authority, "correction", "CacheKey is retained only offline after review."))
        outcome = {"head": store.journal.verify()["head"]}
    else:
        outcome = await store.retract(actor, authority.binding_id, first.id, "derived-delete")
    assert (await store.source(actor, authority.binding_id, source.source_id)).body == body
    assert (await store.claim(actor, authority.binding_id, sibling.id)).id == sibling.id
    assert (await store.inspect(actor, authority.binding_id, reflection.artifact_id))["state"] == "retracted"
    async with store.pool.acquire() as connection:
        await connection.execute("UPDATE am_claims SET state='active' WHERE id=$1", first.id)
        await connection.execute("UPDATE am_reflections SET state='active' WHERE id=$1", reflection.artifact_id)
        await connection.execute("DELETE FROM am_floors WHERE kind='artifact'")
        await connection.execute("UPDATE am_clock SET journal_head=$1 WHERE singleton", old_head)
    await store.reconcile_journal(outcome["head"])
    with pytest.raises(DomainError):
        await store.claim(actor, authority.binding_id, first.id)
    assert (await store.claim(actor, authority.binding_id, sibling.id)).id == sibling.id
    await store.purge(actor, authority.binding_id, first.id, "derived-purge")
    assert (await store.source(actor, authority.binding_id, source.source_id)).body == body
    assert (await store.claim(actor, authority.binding_id, sibling.id)).evidence


@pytest.mark.parametrize("alias", ("rule", "proposal", "operation", "body_source", "body_claim"))
async def test_producer_cannot_correct_rule_authority_through_aliases(authority, alias):
    store, actor = authority.store, authority.actor
    proposal = await store.propose_rule(actor, RuleProposal(binding_id=authority.binding_id, idempotency_key="protected-proposal", body="Keep CacheKey offline.", required=True))
    active = await store.approve_rule(actor, RuleApproval(proposal_id=proposal["proposal_id"], expected_digest=proposal["digest"], scope=RuleScope.LOCAL_PROJECT, target_bindings=(authority.binding_id,), target_set_revision=proposal["target_set_revision"], idempotency_key="protected-approval"))
    producer = await store.issue_token(actor, Role.PRODUCER, (authority.binding_id,), "producer-alias-" + "p" * 32)
    async with store.pool.acquire() as connection:
        operation_id = await connection.fetchval("SELECT operation_id FROM am_sources WHERE id=$1", proposal["source_id"])
    aliases = {"rule": active.id, "proposal": proposal["proposal_id"], "operation": operation_id, "body_source": proposal["source_id"]}
    if alias == "body_claim":
        await store.reprocess(actor, authority.binding_id, proposal["source_id"], "index-rule-body")
        lease = await store.claim_job()
        admitted = await store.admit_job(lease, authority.revision, "extraction")
        await store.publish_extraction(lease, admitted, extraction(proposal["source_id"], "Keep CacheKey offline."), [VECTOR], [["CacheKey"]])
        consolidation = await store.claim_job()
        inputs = await store.admit_job(consolidation, authority.revision, "consolidation")
        aliases["body_claim"] = inputs.claim_ids[0]
        await store.publish_consolidation(consolidation, inputs, Consolidation(relations=()))
    head = store.journal.verify()["head"]
    with pytest.raises(DomainError) as denied:
        await store.correct(producer, authority.binding_id, aliases[alias], command(authority, "producer-withdrawal", "Do not review CacheKey."))
    assert denied.value.code == "SCOPE_DENIED"
    assert store.journal.verify()["head"] == head
    assert (await store.rules(actor, authority.binding_id))[0].id == active.id


async def test_rejected_correction_origin_commits_no_deletion_or_barrier(authority):
    store, actor = authority.store, authority.actor
    original = await store.capture(actor, command(authority, "original"))
    other = await store.capture(actor, command(authority, "existing-origin", "OtherKey is independent."))
    head = store.journal.verify()["head"]
    with pytest.raises(DomainError) as conflict:
        await store.correct(actor, authority.binding_id, original.source_id, command(authority, "bad-correction", "OtherKey is independent.", origin="existing-origin"))
    assert conflict.value.code == "ORIGIN_CONFLICT" and conflict.value.effect.value == "not_started"
    assert store.journal.verify()["head"] == head
    assert (await store.source(actor, authority.binding_id, original.source_id)).state == "active"
    assert (await store.source(actor, authority.binding_id, other.source_id)).state == "active"
    assert (await store.stats(actor, authority.binding_id))["active_sources"] == 2


@pytest.mark.parametrize("failure", ("capacity", "auth"))
async def test_post_append_failure_reconciles_in_process_with_truthful_effect(authority, monkeypatch, failure):
    store, actor = authority.store, authority.actor
    producer = await store.issue_token(actor, Role.PRODUCER, (authority.binding_id,), "postappend-producer-" + "u" * 32)
    original = await store.capture(producer, command(authority))
    append = store._append_deletion_intent
    queue_limit = store.settings.queue_limit
    async def change_after_append(binding_id, sources, artifacts=()):
        outcome = await append(binding_id, sources, artifacts)
        if failure == "capacity":
            store.settings = store.settings.model_copy(update={"queue_limit": 0})
        else:
            async with store.pool.acquire() as connection:
                await connection.execute("UPDATE am_credentials SET active=false,generation=generation+1 WHERE id=$1", producer.credential_id)
        return outcome
    monkeypatch.setattr(store, "_append_deletion_intent", change_after_append)
    request = command(authority, "post-append", "CacheKey is retained after review.")
    with pytest.raises(DomainError) as refused:
        await store.correct(producer, authority.binding_id, original.source_id, request)
    assert refused.value.effect.value == "unknown"
    assert refused.value.code == "CORRECTION_PARTIAL"
    pending = (await store.inspect(actor, authority.binding_id, original.source_id))["pending_corrections"]
    assert pending == [{"request_key": request.idempotency_key, "state": "partial",
        "logical_retraction": "committed", "replacement_capture": "pending_or_unknown",
        "retry_same_key": True, "error_code": "QUEUE_FULL" if failure == "capacity" else "AUTH_DENIED"}]
    with pytest.raises(DomainError) as mismatch:
        await store.correct(actor, authority.binding_id, original.source_id, request.model_copy(update={"body": "Different replacement."}))
    assert mismatch.value.code == "IDEMPOTENCY_CONFLICT"
    assert (await store.stats(actor, authority.binding_id))["active_sources"] == 0
    monkeypatch.setattr(store, "_append_deletion_intent", append)
    store.settings = store.settings.model_copy(update={"queue_limit": queue_limit})
    retry = await store.correct(actor, authority.binding_id, original.source_id, request)
    assert retry.state == "accepted" and retry.source_id != original.source_id


async def test_required_shared_rule_unreadable_signer_refuses_listing_and_delivery(authority, tmp_path):
    store, actor = authority.store, authority.actor
    signer = Ed25519PrivateKey.generate()
    public = tmp_path / "approval-public.pem"
    public.write_bytes(signer.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
    store.settings = store.settings.model_copy(update={"mode": "company", "strong_shared_approval": True, "approver_public_key": public})
    proposal = await store.propose_rule(actor, RuleProposal(binding_id=authority.binding_id, idempotency_key="required-signed", body="Keep data local.", required=True))
    approval = RuleApproval(proposal_id=proposal["proposal_id"], expected_digest=proposal["digest"], scope=RuleScope.SHARED, target_bindings=(authority.binding_id,), target_set_revision=proposal["target_set_revision"], idempotency_key="required-signed-approval")
    signature = base64.b64encode(signer.sign(approval_signing_payload(store.settings.deployment_id, store.settings.realm, actor.id, approval))).decode()
    active = await store.approve_rule(actor, approval.model_copy(update={"approver_signature": signature}))
    public.unlink()
    for action in (store.rules(actor, authority.binding_id), store.delivery(actor, authority.binding_id, (), ((active.id, active.revision, active.digest),))):
        with pytest.raises(DomainError) as refused:
            await action
        assert refused.value.code == "SHARED_APPROVAL_DENIED"


async def test_maximum_note_request_key_has_bounded_derived_origin(authority):
    store, actor = authority.store, authority.actor
    request = RecordCommand(binding_id=authority.binding_id, idempotency_key="k" * 512, body="CacheKey is retained only offline.", kind="note")
    operation = await store.record(actor, request)
    source = await store.source(actor, authority.binding_id, operation.source_id)
    assert len(source.origin_key) <= 512 and source.origin_key.startswith("agent-note:")
    assert (await store.record(actor, request)).id == operation.id


async def test_rule_delivery_without_admission_does_not_claim_host_copies_drained(authority):
    store, actor = authority.store, authority.actor
    proposal = await store.propose_rule(actor, RuleProposal(binding_id=authority.binding_id, idempotency_key="delivered-body", body="Keep CacheKey offline.", required=True))
    active = await store.approve_rule(actor, RuleApproval(proposal_id=proposal["proposal_id"], expected_digest=proposal["digest"], scope=RuleScope.LOCAL_PROJECT, target_bindings=(authority.binding_id,), target_set_revision=proposal["target_set_revision"], idempotency_key="delivered-body-approval"))
    assert (await store.rules(actor, authority.binding_id))[0].body == "Keep CacheKey offline."
    await store.delivery(actor, authority.binding_id, (), ((active.id, active.revision, active.digest),))
    outcome = await store.retract(actor, authority.binding_id, active.id, "delete-delivered-rule")
    assert outcome["local_drain"] == "unknown"
    assert outcome["delivered_context_copies"] == "unknown"
    assert outcome["provider_completion"] == "provider_completion_unknown"


async def test_reprocess_preserves_original_source_and_requires_new_route_approval(authority):
    store, actor = authority.store, authority.actor
    source, claim = await ready_claim(authority)
    original = await store.source(actor, authority.binding_id, source.source_id)
    async with store.pool.acquire() as connection:
        await connection.execute("UPDATE am_claims SET route_revision=$1 WHERE id=$2", "0" * 64, claim.id)
    assert (await store.claim(actor, authority.binding_id, claim.id)).evidence == claim.evidence
    await store.configure_route(actor, authority.revision, ("extraction",), False)
    with pytest.raises(DomainError) as unapproved:
        await store.reprocess(actor, authority.binding_id, source.source_id, "verbatim-reprocess")
    assert unapproved.value.code == "MODEL_ROUTE_BLOCKED"
    await store.configure_route(actor, authority.revision, ("extraction",), True)
    operation = await store.reprocess(actor, authority.binding_id, source.source_id, "verbatim-reprocess")
    assert operation.source_id == original.id and operation.id != source.id
    assert (await store.reprocess(actor, authority.binding_id, source.source_id, "verbatim-reprocess")).id == operation.id
    lease = await store.claim_job()
    admission = await store.admit_job(lease, authority.revision, "extraction")
    assert await store.admitted_sources(admission) == [original]
    await store.publish_extraction(lease, admission, extraction(original.id), [VECTOR], [["CacheKey"]])
    consolidation = await store.claim_job()
    inputs = await store.admit_job(consolidation, authority.revision, "consolidation")
    await store.publish_consolidation(consolidation, inputs, Consolidation(relations=()))
    assert (await store.operation(actor, authority.binding_id, operation.id)).state == "semantic_ready"
    assert (await store.source(actor, authority.binding_id, original.id)) == original
    assert (await store.stats(actor, authority.binding_id))["active_claims"] == 1
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT count(*) FROM am_claims WHERE binding_id=$1", authority.binding_id) == 1


@pytest.mark.parametrize("leased", (False, True))
async def test_claim_withdrawal_fences_future_derivation_without_deleting_source(authority, leased):
    store, actor = authority.store, authority.actor
    source, claim = await ready_claim(authority)
    future = await store.reprocess(actor, authority.binding_id, source.source_id, "queued-regeneration")
    lease = await store.claim_job() if leased else None
    admission = await store.admit_job(lease, authority.revision, "extraction") if lease else None
    await store.retract(actor, authority.binding_id, claim.id, "withdraw-assertion")
    owner = await store.operation(actor, authority.binding_id, future.id)
    assert owner.state == "retracted" and owner.error_code == "DERIVATION_RETRACTED"
    assert (await store.source(actor, authority.binding_id, source.source_id)).state == "active"
    with pytest.raises(DomainError) as refused:
        await store.reprocess(actor, authority.binding_id, source.source_id, "new-regeneration-key")
    assert refused.value.code == "DERIVATION_RETRACTED"
    if lease:
        with pytest.raises(DomainError):
            await store.publish_extraction(lease, admission, extraction(source.source_id), [VECTOR], [["CacheKey"]])
    assert await store.claim_job() is None


async def test_pre_artifact_restore_cannot_regenerate_withdrawn_claim(authority):
    store, actor = authority.store, authority.actor
    source, claim = await ready_claim(authority)
    old_head = store.journal.verify()["head"]
    outcome = await store.retract(actor, authority.binding_id, claim.id, "before-old-backup")
    async with store.pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute("DELETE FROM am_relation_claims WHERE claim_id=$1", claim.id)
            await connection.execute("DELETE FROM am_spans WHERE claim_id=$1", claim.id)
            await connection.execute("DELETE FROM am_entities WHERE claim_id=$1", claim.id)
            await connection.execute("DELETE FROM am_claim_sources WHERE claim_id=$1", claim.id)
            await connection.execute("DELETE FROM am_claims WHERE id=$1", claim.id)
            await connection.execute("DELETE FROM am_admissions WHERE job_id IN (SELECT id FROM am_jobs WHERE operation_id=$1 AND kind='consolidate')", source.id)
            await connection.execute("DELETE FROM am_jobs WHERE operation_id=$1 AND kind='consolidate'", source.id)
            await connection.execute("UPDATE am_jobs SET state='pending',generation=1,lease_token=NULL,deadline=NULL,error_code=NULL WHERE operation_id=$1 AND kind='extract'", source.id)
            await connection.execute("UPDATE am_operations SET state='accepted',error_code=NULL WHERE id=$1", source.id)
            await connection.execute("DELETE FROM am_floors WHERE kind='artifact'")
            await connection.execute("UPDATE am_clock SET journal_head=$1 WHERE singleton", old_head)
    await store.reconcile_journal(outcome["head"])
    owner = await store.operation(actor, authority.binding_id, source.id)
    assert owner.state == "retracted" and owner.error_code == "DERIVATION_RETRACTED"
    assert await store.claim_job() is None
    assert (await store.source(actor, authority.binding_id, source.source_id)).state == "active"
    with pytest.raises(DomainError) as refused:
        await store.reprocess(actor, authority.binding_id, source.source_id, "restore-regeneration")
    assert refused.value.code == "DERIVATION_RETRACTED"


@pytest.mark.parametrize("derived", ("reflection", "rule"))
async def test_derived_artifact_retraction_never_floors_its_upstream_evidence(authority, derived):
    store, actor = authority.store, authority.actor
    source, claim = await ready_claim(authority)
    if derived == "reflection":
        _, reflection, _ = await published_reflection(authority, (claim,))
        ref = reflection.artifact_id
    else:
        proposal = await store.propose_rule(actor, RuleProposal(binding_id=authority.binding_id, idempotency_key="derived-rule", body="Keep CacheKey offline.", source_ids=(source.source_id,)))
        active = await store.approve_rule(actor, RuleApproval(proposal_id=proposal["proposal_id"], expected_digest=proposal["digest"], scope=RuleScope.LOCAL_PROJECT, target_bindings=(authority.binding_id,), target_set_revision=proposal["target_set_revision"], idempotency_key="derived-rule-approval"))
        ref = active.id
    await store.retract(actor, authority.binding_id, ref, "derived-artifact-delete")
    assert (await store.source(actor, authority.binding_id, source.source_id)).state == "active"
    assert (await store.claim(actor, authority.binding_id, claim.id)).state == "active"
    assert (await store.inspect(actor, authority.binding_id, ref))["state"] == "retracted"




async def historical_schema_fixture(store, archived_index):
    """Build an isolated historical test schema, never a production restore path."""
    from agents_memory.migrations import MIGRATIONS

    assert archived_index in (0, 1, 2)
    async with store.pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute("""
                ALTER TABLE am_operations DROP COLUMN successor_operation_id;
                DROP INDEX am_rules_active_proposal;
                ALTER TABLE am_rules DROP CONSTRAINT am_rules_proposal_revision_key;
                ALTER TABLE am_rules ADD CONSTRAINT am_rules_proposal_id_key UNIQUE(proposal_id);
            """)
            if archived_index < 2:
                await connection.execute("""
                    DROP TABLE am_origin_reservations;
                    ALTER TABLE am_claims DROP COLUMN vector_revision;
                    ALTER TABLE am_claims DROP COLUMN extraction_operation_id;
                    ALTER TABLE am_claims DROP COLUMN superseded_by;
                    ALTER TABLE am_jobs DROP CONSTRAINT am_jobs_kind_check;
                    ALTER TABLE am_jobs ADD CONSTRAINT am_jobs_kind_check
                        CHECK(kind IN ('extract','consolidate','reflect')) NOT VALID;
                """)
            if archived_index == 0:
                await connection.execute("""
                    DROP TABLE am_relation_claims;
                    ALTER TABLE am_feedback DROP COLUMN state;
                    ALTER TABLE am_floors DROP CONSTRAINT am_floors_kind_check;
                    ALTER TABLE am_floors ADD CONSTRAINT am_floors_kind_check
                        CHECK(kind IN ('source','origin')) NOT VALID;
                """)
            await connection.execute("UPDATE alembic_version SET version_num=$1", MIGRATIONS[archived_index])


@pytest.mark.parametrize("archived_index", (0, 1))
async def test_historical_schema_migrates_before_normal_authority_recovery(authority, archived_index):
    from agents_memory.migrations import MIGRATION

    store, actor = authority.store, authority.actor
    source, claim = await ready_claim(authority)
    deletion = await store.retract(actor, authority.binding_id, claim.id, "migration-floor")
    dsn = store.settings.database_dsn
    await historical_schema_fixture(store, archived_index)
    await store.close()
    with pytest.raises(DomainError) as ordinary_open:
        await store.open()
    assert ordinary_open.value.code == "MIGRATION_REQUIRED"
    store.settings = store.settings.model_copy(update={"migrator_dsn": dsn})
    await store.open_restore_recovery()
    assert (await store.authenticate(TOKEN)).credential_id == actor.credential_id
    with pytest.raises(DomainError) as closed_barrier:
        await store.stats(actor, authority.binding_id)
    assert closed_barrier.value.code == "DELETION_BARRIER"
    await store.close()
    migration = await asyncio.to_thread(migrate, dsn)
    assert migration["migration"] == MIGRATION
    await store.open()
    await store.reconcile_journal(deletion["head"])
    assert (await store.source(actor, authority.binding_id, source.source_id)).state == "active"
    with pytest.raises(DomainError) as floor:
        await store.reprocess(actor, authority.binding_id, source.source_id, "postmigration-regeneration")
    assert floor.value.code == "DERIVATION_RETRACTED"


async def test_crashed_root_intent_reconcile_persists_descendant_origin_before_restore(authority):
    store, actor = authority.store, authority.actor
    root = await store.capture(actor, command(authority, "root"))
    proposal = await store.propose_rule(actor, RuleProposal(binding_id=authority.binding_id, idempotency_key="late-descendant", body="Review CacheKey.", source_ids=(root.source_id,)))
    descendant = await store.source(actor, authority.binding_id, proposal["source_id"])
    interrupted = store.journal.append(authority.binding_id, (root.source_id,), ("root",))
    recovered = await store.reconcile_journal(interrupted["head"])
    assert recovered["head"] != interrupted["head"] and recovered["sequence"] == 2
    tokens = store.journal.source_token(descendant.id), store.journal.origin_token(authority.binding_id, descendant.origin_key)
    assert any(tokens[0] in entry["source_tokens"] and tokens[1] in entry["origin_tokens"] for entry in store.journal.entries())
    async with store.pool.acquire() as connection:
        async with connection.transaction():
            operation_id = await connection.fetchval("SELECT operation_id FROM am_sources WHERE id=$1", descendant.id)
            await connection.execute("DELETE FROM am_proposal_sources WHERE proposal_id=$1", proposal["proposal_id"])
            await connection.execute("DELETE FROM am_proposals WHERE id=$1", proposal["proposal_id"])
            await connection.execute("DELETE FROM am_sources WHERE id=$1", descendant.id)
            await connection.execute("DELETE FROM am_operations WHERE id=$1", operation_id)
            await connection.execute("DELETE FROM am_receipts WHERE target_id=$1", proposal["proposal_id"])
            await connection.execute("DELETE FROM am_floors")
            await connection.execute("UPDATE am_sources SET state='active',revision=1 WHERE id=$1", root.source_id)
            await connection.execute("UPDATE am_clock SET journal_head=$1 WHERE singleton", interrupted["head"])
    await store.reconcile_journal(recovered["head"])
    replay = await store.capture(actor, CaptureCommand(binding_id=authority.binding_id, idempotency_key="old-backup-descendant", origin_key=descendant.origin_key, body=descendant.body, speaker="agent_note"))
    assert replay.state == "retracted" and replay.error_code == "ORIGIN_RETRACTED" and replay.source_id is None


async def test_reprocess_retains_failed_attempt_and_links_completed_successor_before_real_deletion(authority):
    store, actor = authority.store, authority.actor
    store.settings = store.settings.model_copy(update={"queue_limit": 1, "job_attempt_limit": 1})
    capture = command(authority)
    original = await store.capture(actor, capture)
    lease = await store.claim_job()
    await store.fail_job(lease, "MODEL_OUTPUT_INVALID")
    replacement = await store.reprocess(actor, authority.binding_id, original.source_id, "retry-exact-evidence")
    failed = await store.capture(actor, capture)
    assert failed.id == original.id and failed.state == "failed" and failed.error_code == "MODEL_OUTPUT_INVALID"
    assert failed.successor_operation_id == replacement.id
    assert (await store.source(actor, authority.binding_id, original.source_id)).body == capture.body
    pending = await store.stats(actor, authority.binding_id)
    assert pending["pending"] == 1 and pending["failed"] == pending["dlq"] == 0
    assert pending["historical_operations"]["failed"] == 1
    assert pending["historical_jobs"]["superseded"] == 1 and pending["recovery_jobs"] == []
    assert (await recall_context(authority))["status"] == "partial"
    with pytest.raises(DomainError) as retired_job:
        await store.retry_job(actor, lease.job_id)
    assert retired_job.value.code == "JOB_NOT_RETRYABLE"
    current = await store.claim_job()
    admission = await store.admit_job(current, authority.revision, "extraction")
    await store.publish_extraction(current, admission, extraction(original.source_id), [VECTOR], [["CacheKey"]])
    consolidation = await store.claim_job()
    inputs = await store.admit_job(consolidation, authority.revision, "consolidation")
    ready = await store.publish_consolidation(consolidation, inputs, Consolidation(relations=()))
    assert ready.id == replacement.id and ready.state == "semantic_ready"
    assert (await store.operation(actor, authority.binding_id, original.id)).state == "failed"
    assert len(await store.search(actor, authority.binding_id, VECTOR, ["CacheKey"], None)) == 1
    stats = await store.stats(actor, authority.binding_id)
    assert stats["pending"] == stats["blocked"] == stats["failed"] == stats["dlq"] == 0
    assert stats["historical_operations"]["failed"] == 1
    assert stats["recovery_jobs"] == [] and not stats["recovery_partial"]
    context = await recall_context(authority)
    assert context["status"] == "ready" and capture.body in context["context"]
    unrelated = await store.capture(actor, command(authority, "unrelated-current-failure"))
    unrelated_lease = await store.claim_job()
    await store.fail_job(unrelated_lease, "MODEL_OUTPUT_INVALID")
    live = await store.stats(actor, authority.binding_id)
    assert live["failed"] == live["dlq"] == 1 and live["historical_operations"]["failed"] == 2
    assert [job["operation_id"] for job in live["recovery_jobs"]] == [unrelated.id]
    assert (await recall_context(authority))["status"] == "partial"
    await store.retract(actor, authority.binding_id, original.source_id, "actual-source-deletion")
    for operation in (original, replacement):
        assert (await store.operation(actor, authority.binding_id, operation.id)).state == "retracted"


@pytest.mark.parametrize("alias", ("reflection", "operation", "query_source"))
async def test_producer_cannot_correct_reflection_authority_aliases(authority, alias):
    store, actor = authority.store, authority.actor
    _, claim = await ready_claim(authority)
    _, reflection, _ = await published_reflection(authority, (claim,))
    producer = await store.issue_token(actor, Role.PRODUCER, (authority.binding_id,), "protected-reflection-producer-" + "v" * 32)
    targets = {"reflection": reflection.artifact_id, "operation": reflection.id, "query_source": reflection.source_id}
    head = store.journal.verify()["head"]
    with pytest.raises(DomainError) as denied:
        await store.correct(producer, authority.binding_id, targets[alias], command(authority, "producer-reflection-correction", "Discard the reflection."))
    assert denied.value.code == "SCOPE_DENIED" and denied.value.effect.value == "not_started"
    assert store.journal.verify()["head"] == head
    assert (await store.inspect(actor, authority.binding_id, reflection.artifact_id))["state"] == "active"


async def test_bounded_context_marker_is_never_recaptured_or_corrective_evidence(authority):
    from agents_memory.constants import BOUNDED_CONTEXT_MARKER

    store, actor = authority.store, authority.actor
    original = await store.capture(actor, command(authority))
    injected = command(authority, "bounded-host-context", BOUNDED_CONTEXT_MARKER + "\nKeep CacheKey offline.")
    ignored = await store.capture(actor, injected)
    assert ignored.source_id is None and ignored.error_code == "CAPTURE_IGNORED"
    head = store.journal.verify()["head"]
    with pytest.raises(DomainError) as refused:
        await store.correct(actor, authority.binding_id, original.source_id, injected)
    assert refused.value.code == "CORRECTION_INVALID"
    assert store.journal.verify()["head"] == head
    assert (await store.source(actor, authority.binding_id, original.source_id)).state == "active"


async def test_correction_reservation_fences_concurrent_origin_capture_before_floor(authority, monkeypatch):
    store, actor = authority.store, authority.actor
    original = await store.capture(actor, command(authority))
    request = command(authority, "reserved-correction", "Distinct replacement body must not enter any receipt.",
        origin="replacement-origin").model_copy(update={"root_run_id": "trusted-root"})
    before = store.journal.verify()["head"]
    entered, release = asyncio.Event(), asyncio.Event()
    commit = store._commit_deletion

    async def pause(binding_id, sources, artifacts, correction_intent=None):
        entered.set()
        await release.wait()
        return await commit(binding_id, sources, artifacts, correction_intent)

    monkeypatch.setattr(store, "_commit_deletion", pause)
    correction = asyncio.create_task(store.correct(actor, authority.binding_id, original.source_id, request))
    await entered.wait()
    try:
        assert store.journal.verify()["head"] == before
        assert (await store.source(actor, authority.binding_id, original.source_id)).state == "active"
        same_origin = request.model_copy(update={"idempotency_key": "concurrent-capture", "kind": "correction"})
        with pytest.raises(DomainError) as mismatch:
            await store.capture(actor, same_origin.model_copy(update={"root_run_id": "different-root"}))
        assert mismatch.value.code == "ORIGIN_CONFLICT"
        with pytest.raises(DomainError) as reserved:
            await store.capture(actor, same_origin)
        assert reserved.value.code == "ORIGIN_RESERVED"
        async with store.pool.acquire() as connection:
            assert request.body not in str(await connection.fetch("SELECT * FROM am_origin_reservations"))
            assert request.body not in str(await connection.fetch("SELECT * FROM am_receipts WHERE kind='correct_intent'"))
            assert await connection.fetchval("SELECT count(*) FROM am_sources WHERE origin_key=$1", request.origin_key) == 0
    finally:
        release.set()
    result = await correction
    assert (await store.correct(actor, authority.binding_id, original.source_id, request)).id == result.id
    assert (await store.source(actor, authority.binding_id, result.source_id)).body == request.body
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT count(*) FROM am_origin_reservations") == 0
        assert await connection.fetchval("SELECT count(*) FROM am_sources WHERE origin_key=$1", request.origin_key) == 1


@pytest.mark.parametrize("alias", ("reflection", "operation", "query", "upstream"))
async def test_reflection_purge_removes_owned_query_and_body_free_replay_preserves_manifest(authority, alias):
    store, actor = authority.store, authority.actor
    source, claim = await ready_claim(authority)
    secret = "private reflection query: never duplicate this canonical body"
    request = ContextCommand(binding_id=authority.binding_id, query=secret, mode="reflect", idempotency_key="private-query")
    operation = await store.submit_reflection(actor, request, (claim.id,))
    lease = await store.claim_job()
    admission = await store.admit_job(lease, authority.revision, "reflection")
    published = await store.publish_reflection(lease, admission,
        ReflectionDraft(sentences=(CitedSentence(text=claim.draft.statement, claim_ids=(claim.id,)),)))
    async with store.pool.acquire() as connection:
        manifest = dict(await connection.fetchrow("SELECT source_ids,claim_ids,query_source_id FROM am_jobs WHERE id=$1", lease.job_id))
        assert secret not in await connection.fetchval("SELECT result::text FROM am_receipts WHERE kind='reflect' AND target_id=$1", operation.id)
        await connection.execute("""UPDATE am_receipts SET result=jsonb_build_object('request',$2::jsonb,'manifest','retained')
            WHERE kind='reflect' AND target_id=$1""", operation.id, json.dumps(request.model_dump(mode="json")))
    ref = {"reflection": published.artifact_id, "operation": published.id,
        "query": manifest["query_source_id"], "upstream": source.source_id}[alias]
    await store.retract(actor, authority.binding_id, ref, "retract-private-query")
    purged = await store.purge(actor, authority.binding_id, ref, "purge-private-query")
    assert purged["physical_purge"] == "physically_purged"
    assert (await store.reflection_receipt(actor, request)).id == operation.id
    assert (await store.submit_reflection(actor, request, ())).id == operation.id
    with pytest.raises(DomainError) as mismatch:
        await store.reflection_receipt(actor, request.model_copy(update={"query": secret + " changed"}))
    assert mismatch.value.code == "IDEMPOTENCY_CONFLICT"
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT body FROM am_sources WHERE id=$1", manifest["query_source_id"]) is None
        assert secret not in str(await connection.fetch("SELECT result FROM am_receipts"))
        assert dict(await connection.fetchrow("SELECT source_ids,claim_ids,query_source_id FROM am_jobs WHERE id=$1", lease.job_id)) == manifest
    if alias != "upstream":
        assert (await store.source(actor, authority.binding_id, source.source_id)).body == claim.evidence[0].quote
        assert (await store.claim(actor, authority.binding_id, claim.id)).evidence == claim.evidence


async def test_migration_sanitizes_legacy_reflection_request_without_compatible_vector_backfill(authority):
    store, actor = authority.store, authority.actor
    _, claim = await ready_claim(authority)
    request, published, _ = await published_reflection(authority, (claim,))
    async with store.pool.acquire() as connection:
        manifest = dict(await connection.fetchrow("SELECT source_ids,claim_ids FROM am_jobs WHERE operation_id=$1 AND kind='reflect'", published.id))
        digest = await connection.fetchval("SELECT digest FROM am_receipts WHERE kind='reflect' AND target_id=$1", published.id)
        await connection.execute("""UPDATE am_receipts SET result=jsonb_build_object('request',$2::jsonb,'manifest','preserved')
            WHERE kind='reflect' AND target_id=$1""", published.id, json.dumps(request.model_dump(mode="json")))
    dsn = store.settings.database_dsn
    await historical_schema_fixture(store, 1)
    await store.close()
    await asyncio.to_thread(migrate, dsn)
    await store.open()
    await store.reconcile_journal()
    assert (await store.reflection_receipt(actor, request)).id == published.id
    async with store.pool.acquire() as connection:
        receipt = await connection.fetchrow("SELECT digest,result FROM am_receipts WHERE kind='reflect' AND target_id=$1", published.id)
        assert receipt["digest"] == digest
        assert json.loads(receipt["result"]) == {"manifest": "preserved"}
        assert dict(await connection.fetchrow("SELECT source_ids,claim_ids FROM am_jobs WHERE operation_id=$1 AND kind='reflect'", published.id)) == manifest
        assert await connection.fetchval("SELECT vector_revision FROM am_claims WHERE id=$1", claim.id) is None
    found = await store.search(actor, authority.binding_id, VECTOR, ["CacheKey"], None)
    assert next(arms for item, arms in found if item.id == claim.id) == ("entity", "lexical")


def advance_manifest(authority, *, embedding=False):
    path = authority.store.settings.models.manifest_path
    manifest = json.loads(path.read_text())
    if embedding:
        manifest["embedding"]["revision"] += "-next"
        manifest["embedding"]["artifacts"][0]["sha256"] = "b" * 64
    else:
        manifest["generation"] = {"revision": "semantic-next"}
    path.write_text(json.dumps(manifest))
    authority.revision = authority.store.settings.models.revision()


async def test_semantic_upgrade_preserves_old_claims_reflections_and_embedding_only_recovery(authority):
    store, actor = authority.store, authority.actor
    source, claim = await ready_claim(authority)
    _, reflection, _ = await published_reflection(authority, (claim,))
    original_revision = authority.revision
    original_vector_revision = store.settings.models.vector_revision()
    advance_manifest(authority)
    assert authority.revision != original_revision
    assert store.settings.models.vector_revision() == original_vector_revision
    await store.configure_route(actor, authority.revision, ("embedding",), True)
    found = await store.search(actor, authority.binding_id, VECTOR, ["CacheKey"], None)
    assert next(arms for item, arms in found if item.id == claim.id) == ("entity", "lexical", "vector")
    assert (await store.stats(actor, authority.binding_id))["stale_index_claims"] == 0
    assert (await store.inspect(actor, authority.binding_id, reflection.artifact_id))["sentences"]
    advance_manifest(authority, embedding=True)
    await store.configure_route(actor, authority.revision, ("embedding",), True)
    found = await store.search(actor, authority.binding_id, VECTOR, ["CacheKey"], None)
    assert next(arms for item, arms in found if item.id == claim.id) == ("entity", "lexical")
    assert (await store.inspect(actor, authority.binding_id, claim.id))["evidence"]
    assert (await store.inspect(actor, authority.binding_id, reflection.artifact_id))["sentences"]
    status = await store.index_status(actor, authority.binding_id, limit=1)
    assert status["claims"] == [{"id": claim.id, "route_revision": original_revision, "vector_revision": original_vector_revision}]
    assert status["stats"]["active_claims"] == 1 and status["stats"]["stale_index_claims"] == 1
    operation = await store.recover_index(actor, authority.binding_id, (claim.id,), "embedding-only")
    assert (await store.recover_index(actor, authority.binding_id, (claim.id,), "embedding-only")).id == operation.id
    lease = await store.claim_job()
    assert lease.kind == "reindex" and lease.source_ids == (source.source_id,) and lease.claim_ids == (claim.id,)
    admission = await store.admit_job(lease, authority.revision, "embedding")
    assert await store.admitted_claims(admission) == [claim]
    assert [item.id for item in await store.admitted_sources(admission)] == [source.source_id]
    await store.publish_reindex(lease, admission, [VECTOR], [["CacheKey", "offline"]])
    assert (await store.claim(actor, authority.binding_id, claim.id)) == claim
    assert (await store.stats(actor, authority.binding_id))["stale_index_claims"] == 0
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT route_revision FROM am_claims WHERE id=$1", claim.id) == original_revision
        assert await connection.fetchval("SELECT count(*) FROM am_jobs WHERE operation_id=$1", operation.id) == 1
        assert await connection.fetchval("SELECT count(*) FROM am_claims WHERE binding_id=$1", authority.binding_id) == 1


@pytest.mark.parametrize("change", ("lease", "source", "claim", "credential", "route"))
async def test_reindex_publication_rechecks_lease_and_complete_authority(authority, change):
    store, actor = authority.store, authority.actor
    source, claim = await ready_claim(authority)
    advance_manifest(authority, embedding=True)
    await store.configure_route(actor, authority.revision, ("embedding",), True)
    await store.recover_index(actor, authority.binding_id, (claim.id,), "fenced-index")
    lease = await store.claim_job()
    admission = await store.admit_job(lease, authority.revision, "embedding")
    async with store.pool.acquire() as connection:
        before = dict(await connection.fetchrow("SELECT vector_revision,lexical_tokens FROM am_claims WHERE id=$1", claim.id))
    if change == "lease":
        async with store.pool.acquire() as connection:
            await connection.execute("UPDATE am_jobs SET deadline=clock_timestamp()-interval '1 second' WHERE id=$1", lease.job_id)
    elif change == "source":
        await store.retract(actor, authority.binding_id, source.source_id, "index-source-withdrawal")
    elif change == "claim":
        await store.retract(actor, authority.binding_id, claim.id, "index-claim-withdrawal")
    elif change == "credential":
        await store.revoke_token(actor, actor.credential_id)
    else:
        await store.configure_route(actor, authority.revision, ("embedding",), False)
        await store.configure_route(actor, authority.revision, ("embedding",), True)
    with pytest.raises(DomainError):
        await store.publish_reindex(lease, admission, [VECTOR], [["forbidden-new-token"]])
    async with store.pool.acquire() as connection:
        assert dict(await connection.fetchrow("SELECT vector_revision,lexical_tokens FROM am_claims WHERE id=$1", claim.id)) == before


async def test_index_status_cursor_and_recovery_ownership_are_bounded(authority):
    store, actor = authority.store, authority.actor
    claims = [(await ready_claim(authority, f"cursor-{index}"))[1] for index in range(3)]
    advance_manifest(authority, embedding=True)
    await store.configure_route(actor, authority.revision, ("embedding",), True)
    first = await store.index_status(actor, authority.binding_id, limit=2)
    second = await store.index_status(actor, authority.binding_id, limit=2, after=first["next_after"])
    assert first["partial"] and not second["partial"]
    assert [row["id"] for row in [*first["claims"], *second["claims"]]] == sorted(claim.id for claim in claims)
    with pytest.raises(DomainError) as limit:
        await store.index_status(actor, authority.binding_id, limit=65)
    assert limit.value.code == "INDEX_LIMIT_INVALID"
    operation = await store.recover_index(actor, authority.binding_id, (claims[0].id,), "owner")
    with pytest.raises(DomainError) as busy:
        await store.recover_index(actor, authority.binding_id, (claims[0].id,), "other-owner")
    assert busy.value.code == "INDEX_RECOVERY_BUSY"
    with pytest.raises(DomainError) as mismatch:
        await store.recover_index(actor, authority.binding_id, (claims[1].id,), "owner")
    assert mismatch.value.code == "IDEMPOTENCY_CONFLICT"
    lease = await store.claim_job()
    await store.fail_job(lease, "MODEL_ROUTE_BLOCKED", blocked=True)
    replacement = await store.recover_index(actor, authority.binding_id, (claims[0].id,), "new-approved-owner")
    assert replacement.id != operation.id
    original = await store.operation(actor, authority.binding_id, operation.id)
    assert original.state == "blocked" and original.error_code == "MODEL_ROUTE_BLOCKED"
    assert original.successor_operation_id == replacement.id
    assert await store.recover_index(actor, authority.binding_id, (claims[0].id,), "owner") == original
    with pytest.raises(DomainError) as retired:
        await store.retry_job(actor, lease.job_id)
    assert retired.value.code == "JOB_NOT_RETRYABLE"
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT count(*) FROM am_jobs WHERE kind='reindex' AND state IN ('pending','leased','blocked','failed')") == 1
        retired_job = await connection.fetchrow("SELECT state,generation,lease_token,deadline FROM am_jobs WHERE id=$1", lease.job_id)
        assert retired_job["state"] == "superseded" and retired_job["generation"] > lease.generation
        assert retired_job["lease_token"] is None and retired_job["deadline"] is None
    current = await store.claim_job()
    assert current.operation_id == replacement.id and current.claim_ids == (claims[0].id,)
    admission = await store.admit_job(current, authority.revision, "embedding")
    completed = await store.publish_reindex(current, admission, [VECTOR], [["CacheKey", "offline"]])
    assert completed.id == replacement.id and completed.state == "semantic_ready"
    assert await store.recover_index(actor, authority.binding_id, (claims[0].id,), "owner") == original
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT vector_revision FROM am_claims WHERE id=$1", claims[0].id) == store.settings.models.vector_revision()
    stats = await store.stats(actor, authority.binding_id)
    assert stats["blocked"] == stats["failed"] == stats["dlq"] == 0
    assert stats["historical_operations"]["blocked"] == 1 and stats["recovery_jobs"] == []


@pytest.mark.parametrize("blocked", (False, True))
@pytest.mark.parametrize("snapshot", (None, "dirty_snapshot"))
async def test_reindex_successor_restores_ready_context_without_rewriting_receipt(authority, blocked, snapshot):
    store, actor = authority.store, authority.actor
    source, claim = await ready_claim(authority, snapshot=snapshot)
    advance_manifest(authority, embedding=True)
    await store.configure_route(actor, authority.revision, store.settings.allowed_model_purposes, True)
    store.settings = store.settings.model_copy(update={"queue_limit": 1, "job_attempt_limit": 1})
    original = await store.recover_index(actor, authority.binding_id, (claim.id,), "original-index", snapshot)
    old_lease = await store.claim_job()
    old_admission = await store.admit_job(old_lease, authority.revision, "embedding")
    code = "MODEL_ROUTE_BLOCKED" if blocked else "MODEL_OUTPUT_INVALID"
    state = "blocked" if blocked else "failed"
    await store.fail_job(old_lease, code, blocked=blocked)
    failed = await store.operation(actor, authority.binding_id, original.id)
    before = await store.stats(actor, authority.binding_id, snapshot)
    assert before[state] == 1
    assert before["dlq"] == (0 if blocked else 1)
    assert [job["operation_id"] for job in before["recovery_jobs"]] == [original.id]
    assert (await recall_context(authority, snapshot))["status"] == "partial"
    successor = await store.recover_index(actor, authority.binding_id, (claim.id,), "successor-index", snapshot)
    replay = await store.recover_index(actor, authority.binding_id, (claim.id,), "original-index", snapshot)
    assert replay == failed.model_copy(update={"successor_operation_id": successor.id})
    pending = await store.stats(actor, authority.binding_id, snapshot)
    assert pending["pending"] == 1 and pending["blocked"] == pending["failed"] == pending["dlq"] == 0
    assert pending["historical_operations"][state] == 1 and pending["historical_jobs"]["superseded"] == 1
    assert pending["recovery_jobs"] == [] and not pending["recovery_partial"]
    assert (await recall_context(authority, snapshot))["status"] == "partial"
    with pytest.raises(DomainError) as stale:
        await store.publish_reindex(old_lease, old_admission, [VECTOR], [["forbidden-old-publication"]])
    assert stale.value.code == "LEASE_STALE"
    current = await store.claim_job()
    assert current.operation_id == successor.id and current.source_ids == (source.source_id,)
    admission = await store.admit_job(current, authority.revision, "embedding")
    assert await store.admitted_claims(admission) == [claim]
    assert [item.id for item in await store.admitted_sources(admission)] == [source.source_id]
    completed = await store.publish_reindex(current, admission, [VECTOR], [["CacheKey", "offline"]])
    assert completed.id == successor.id and completed.state == "semantic_ready"
    assert await store.operation(actor, authority.binding_id, original.id) == replay
    assert await store.recover_index(actor, authority.binding_id, (claim.id,), "original-index", snapshot) == replay
    ready = await store.stats(actor, authority.binding_id, snapshot)
    assert ready["pending"] == ready["blocked"] == ready["failed"] == ready["dlq"] == ready["stale_index_claims"] == 0
    assert ready["historical_operations"][state] == 1
    assert ready["recovery_jobs"] == [] and not ready["recovery_partial"]
    context = await recall_context(authority, snapshot)
    assert context["status"] == "ready" and context["refs"] == [claim.id]
    assert (await store.claim(actor, authority.binding_id, claim.id, snapshot)) == claim
    assert (await store.source(actor, authority.binding_id, source.source_id)).body == claim.evidence[0].quote


@pytest.mark.parametrize("target", ("source", "claim"))
@pytest.mark.parametrize("blocked", (False, True))
async def test_withdrawn_recovery_input_is_terminal_history_not_live_gap(authority, target, blocked):
    store, actor = authority.store, authority.actor
    source, claim = await ready_claim(authority)
    _, survivor = await ready_claim(authority, "survivor", "CacheKey remains available offline.")
    store.settings = store.settings.model_copy(update={"job_attempt_limit": 1})
    original = await store.recover_index(actor, authority.binding_id, (claim.id,), "withdrawn-index")
    lease = await store.claim_job()
    await store.fail_job(lease, "MODEL_OUTPUT_INVALID", blocked=blocked)
    assert (await store.stats(actor, authority.binding_id))["recovery_jobs"][0]["operation_id"] == original.id
    await store.retract(actor, authority.binding_id, source.source_id if target == "source" else claim.id, "withdraw-index-input")
    stats = await store.stats(actor, authority.binding_id)
    assert stats["pending"] == stats["blocked"] == stats["failed"] == stats["dlq"] == 0
    assert stats["recovery_jobs"] == [] and not stats["recovery_partial"]
    assert stats["historical_operations"]["failed"] == 1
    terminal = await store.operation(actor, authority.binding_id, original.id)
    assert terminal.state == "failed" and terminal.error_code == "INPUT_RETRACTED"
    assert await store.recover_index(actor, authority.binding_id, (claim.id,), "withdrawn-index") == terminal
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT state FROM am_jobs WHERE id=$1", lease.job_id) == "retracted"
    with pytest.raises(DomainError) as retired:
        await store.retry_job(actor, lease.job_id)
    assert retired.value.code == "JOB_NOT_RETRYABLE"
    context = await recall_context(authority)
    assert context["status"] == "ready" and context["refs"] == [survivor.id]
    if target == "claim":
        assert (await store.source(actor, authority.binding_id, source.source_id)).state == "active"


async def test_manifestless_required_approval_delivery_and_stats_remain_deterministic(authority):
    store, actor = authority.store, authority.actor
    store.settings = store.settings.model_copy(update={"models": store.settings.models.model_copy(update={"manifest_path": None})})
    proposal = await store.propose_rule(actor, RuleProposal(binding_id=authority.binding_id, idempotency_key="no-manifest",
        body="Keep private data local.", required=True))
    active = await store.approve_rule(actor, RuleApproval(proposal_id=proposal["proposal_id"], expected_digest=proposal["digest"],
        scope=RuleScope.LOCAL_PROJECT, target_bindings=(authority.binding_id,), target_set_revision=proposal["target_set_revision"],
        idempotency_key="no-manifest-approval"))
    assert (await store.rules(actor, authority.binding_id))[0].body == active.body
    stats = await store.stats(actor, authority.binding_id)
    assert stats["active_claims"] == 0 and stats["vector_revision"] is None
    assert (await store.delivery(actor, authority.binding_id, (), ((active.id, active.revision, active.digest),)))["stats"] == stats


@pytest.mark.parametrize("overflow", ("utf8", "marker"))
async def test_required_approval_rejects_impossible_utf8_envelope_without_durable_approval(authority, overflow):
    from agents_memory.constants import BOUNDED_CONTEXT_MARKER, HOST_CONTEXT_BYTES
    from agents_memory.context import compose
    from agents_memory.domain import ActiveRule, Selector

    store, actor = authority.store, authority.actor
    body = "한" * (HOST_CONTEXT_BYTES // 3)
    if overflow == "marker":
        probe = ActiveRule(id="rule_" + "a" * 32, revision=1, digest="a" * 64, body="x",
            selector=Selector(), exceptions=(), required=True, scope=RuleScope.LOCAL_PROJECT,
            target_bindings=(authority.binding_id,), source_ids=())
        command = ContextCommand(query="Required envelope boundary", max_bytes=HOST_CONTEXT_BYTES)
        overhead = compose(command, (probe,), (), (), protected_action=True).byte_count - 1
        body = "x" * (HOST_CONTEXT_BYTES - overhead - 1)
        rendered = compose(command, (probe.model_copy(update={"body": body}),), (), (), protected_action=True)
        assert rendered.byte_count <= HOST_CONTEXT_BYTES
        assert rendered.byte_count + len(BOUNDED_CONTEXT_MARKER.encode()) + 1 > HOST_CONTEXT_BYTES
    proposal = await store.propose_rule(actor, RuleProposal(binding_id=authority.binding_id, idempotency_key="oversized-required",
        body=body, required=True))
    approval = RuleApproval(proposal_id=proposal["proposal_id"], expected_digest=proposal["digest"],
        scope=RuleScope.LOCAL_PROJECT, target_bindings=(authority.binding_id,), target_set_revision=proposal["target_set_revision"],
        idempotency_key="oversized-approval")
    with pytest.raises(DomainError) as refused:
        await store.approve_rule(actor, approval)
    assert refused.value.code == "REQUIRED_RULE_TOO_LARGE"
    assert await store.rules(actor, authority.binding_id) == []
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT count(*) FROM am_receipts WHERE kind='approve_rule'") == 0


async def test_repeated_reprocess_reuses_exact_generation_without_erasing_independent_evidence(authority):
    store, actor = authority.store, authority.actor
    source, claim = await ready_claim(authority)
    independent_source, independent = await ready_claim(authority, "independent-same-statement")
    _, reflection, _ = await published_reflection(authority, (claim, independent))
    original_source = await store.source(actor, authority.binding_id, source.source_id)
    for index in range(3):
        await store.reprocess(actor, authority.binding_id, source.source_id, f"reprocess-generation-{index}")
        lease = await store.claim_job()
        admission = await store.admit_job(lease, authority.revision, "extraction")
        await store.publish_extraction(lease, admission, extraction(source.source_id), [VECTOR], [["CacheKey", "offline"]])
        consolidation = await store.claim_job()
        admitted = await store.admit_job(consolidation, authority.revision, "consolidation")
        await store.publish_consolidation(consolidation, admitted, Consolidation(relations=()))
    assert (await store.source(actor, authority.binding_id, source.source_id)) == original_source
    assert (await store.source(actor, authority.binding_id, independent_source.source_id)).state == "active"
    assert (await store.claim(actor, authority.binding_id, independent.id)) == independent
    assert (await store.inspect(actor, authority.binding_id, reflection.artifact_id))["sentences"]
    assert (await store.stats(actor, authority.binding_id))["active_claims"] == 2
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT count(*) FROM am_claims WHERE binding_id=$1", authority.binding_id) == 2
    await store.retract(actor, authority.binding_id, claim.id, "canonical-generation-withdrawal")
    with pytest.raises(DomainError) as withdrawn:
        await store.reprocess(actor, authority.binding_id, source.source_id, "must-not-regenerate")
    assert withdrawn.value.code == "DERIVATION_RETRACTED"
    assert (await store.claim(actor, authority.binding_id, independent.id)).state == "active"


async def test_initialization_store_preflight_and_bootstrap_resume_preserve_owned_identity(authority):
    store, actor = authority.store, authority.actor
    before = store.journal.verify()["head"]
    assert (await Store.preflight_initialization(store.settings, TOKEN, actor.id, resume=True)) == actor
    assert (await store.bootstrap(TOKEN, actor.id, resume=True)) == actor
    assert store.journal.verify()["head"] == before
    for settings, token, owner, resume in (
        (store.settings, TOKEN, actor.id, False),
        (store.settings, "unrelated-operator-token-" + "x" * 32, actor.id, True),
        (store.settings, TOKEN, "unrelated-owner", True),
        (store.settings.model_copy(update={"realm": "other-realm"}), TOKEN, actor.id, True),
    ):
        with pytest.raises(DomainError) as refused:
            await Store.preflight_initialization(settings, token, owner, resume=resume)
        assert refused.value.code == "INITIALIZATION_SCOPE_DENIED"
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT count(*) FROM am_credentials") == 1


async def duplicate_claim(authority, claim):
    store = authority.store
    ref = "claim_" + uuid.uuid4().hex
    async with store.pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute("""INSERT INTO am_claims(id,binding_id,draft,snapshot,route_revision,embedding,lexical_tokens,valid_from,valid_until)
                SELECT $2,binding_id,draft,snapshot,route_revision,embedding,lexical_tokens,valid_from,valid_until FROM am_claims WHERE id=$1""", claim.id, ref)
            await connection.execute("""INSERT INTO am_claim_sources(claim_id,source_id,source_revision)
                SELECT $2,source_id,source_revision FROM am_claim_sources WHERE claim_id=$1""", claim.id, ref)
            await connection.execute("""INSERT INTO am_spans(claim_id,ordinal,source_id,source_revision,byte_start,byte_end,quote)
                SELECT $2,ordinal,source_id,source_revision,byte_start,byte_end,quote FROM am_spans WHERE claim_id=$1""", claim.id, ref)
            await connection.execute("INSERT INTO am_entities(claim_id,name,search_name) SELECT $2,name,search_name FROM am_entities WHERE claim_id=$1", claim.id, ref)
    return claim.model_copy(update={"id": ref})


async def test_superseded_duplicate_keeps_old_citations_until_exact_group_withdrawal(authority):
    store, actor = authority.store, authority.actor
    source, canonical = await ready_claim(authority)
    duplicate = await duplicate_claim(authority, canonical)
    independent_source, independent = await ready_claim(authority, "independent-equivalent")
    _, reflection, _ = await published_reflection(authority, (duplicate, independent))
    _, independent_reflection, _ = await published_reflection(authority, (independent,), key="independent-retained-reflection")
    await store.reprocess(actor, authority.binding_id, source.source_id, "collapse-legacy-duplicates")
    lease = await store.claim_job()
    admission = await store.admit_job(lease, authority.revision, "extraction")
    await store.publish_extraction(lease, admission, extraction(source.source_id), [VECTOR], [["CacheKey", "offline"]])
    consolidation = await store.claim_job()
    admitted = await store.admit_job(consolidation, authority.revision, "consolidation")
    await store.publish_consolidation(consolidation, admitted, Consolidation(relations=()))
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT superseded_by FROM am_claims WHERE id=$1", duplicate.id) == canonical.id
    assert (await store.inspect(actor, authority.binding_id, duplicate.id))["evidence"]
    assert (await store.inspect(actor, authority.binding_id, reflection.artifact_id))["sentences"]
    stats = await store.stats(actor, authority.binding_id)
    assert stats["active_claims"] == 2 and stats["stale_index_claims"] == 0 and not stats["partial"]
    assert (await store.index_status(actor, authority.binding_id))["claims"] == []
    await store.retract(actor, authority.binding_id, duplicate.id, "withdraw-old-equivalent")
    with pytest.raises(DomainError):
        await store.claim(actor, authority.binding_id, canonical.id)
    with pytest.raises(DomainError):
        await store.claim(actor, authority.binding_id, duplicate.id)
    assert (await store.inspect(actor, authority.binding_id, reflection.artifact_id))["state"] == "retracted"
    assert (await store.inspect(actor, authority.binding_id, independent_reflection.artifact_id))["sentences"]
    assert (await store.source(actor, authority.binding_id, source.source_id)).state == "active"
    assert (await store.source(actor, authority.binding_id, independent_source.source_id)).state == "active"
    assert (await store.claim(actor, authority.binding_id, independent.id)).state == "active"
    with pytest.raises(DomainError) as blocked:
        await store.recover_index(actor, authority.binding_id, (duplicate.id,), "cannot-recover-withdrawn")
    assert blocked.value.code == "CLAIM_INELIGIBLE"


@pytest.mark.parametrize("withdrawn", (False, True))
async def test_migration_supersedes_only_exact_generations_and_preserves_prior_withdrawal(authority, withdrawn):
    store, actor = authority.store, authority.actor
    source, canonical = await ready_claim(authority)
    independent_source, independent = await ready_claim(authority, "independent-migration-evidence")
    if withdrawn:
        await store.retract(actor, authority.binding_id, canonical.id, "pre-duplicate-withdrawal")
    duplicate = await duplicate_claim(authority, canonical)
    dsn = store.settings.database_dsn
    await historical_schema_fixture(store, 1)
    await store.close()
    await asyncio.to_thread(migrate, dsn)
    await store.open()
    await store.reconcile_journal()
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT superseded_by FROM am_claims WHERE id=$1", duplicate.id) == canonical.id
        assert await connection.fetchval("SELECT state FROM am_claims WHERE id=$1", duplicate.id) == ("retracted" if withdrawn else "active")
        assert await connection.fetchval("SELECT vector_revision FROM am_claims WHERE id=$1", canonical.id) is None
    assert (await store.source(actor, authority.binding_id, source.source_id)).state == "active"
    assert (await store.source(actor, authority.binding_id, independent_source.source_id)).state == "active"
    assert (await store.claim(actor, authority.binding_id, independent.id)).evidence == independent.evidence
    assert (await store.stats(actor, authority.binding_id))["active_claims"] == (1 if withdrawn else 2)
    if withdrawn:
        with pytest.raises(DomainError) as floor:
            await store.reprocess(actor, authority.binding_id, source.source_id, "must-not-undo-migrated-floor")
        assert floor.value.code == "DERIVATION_RETRACTED"
    else:
        assert (await store.inspect(actor, authority.binding_id, duplicate.id))["evidence"]


@pytest.mark.parametrize("append_landed", (False, True))
async def test_uncertain_correction_append_keeps_body_free_recoverable_intent(authority, monkeypatch, append_landed):
    from agents_memory.domain import EffectState

    store, actor = authority.store, authority.actor
    original = await store.capture(actor, command(authority))
    request = command(authority, "uncertain-correction", "Private corrective source body.", origin="uncertain-origin")
    append = store._append_deletion_intent

    async def uncertain(binding_id, sources, artifacts=()):
        if append_landed:
            await append(binding_id, sources, artifacts)
        raise DomainError("DELETION_BARRIER", "The append outcome is unknown", status=503, effect=EffectState.UNKNOWN)

    monkeypatch.setattr(store, "_append_deletion_intent", uncertain)
    with pytest.raises(DomainError) as refused:
        await store.correct(actor, authority.binding_id, original.source_id, request)
    assert refused.value.effect == EffectState.UNKNOWN
    assert refused.value.code == ("CORRECTION_PARTIAL" if append_landed else "CORRECTION_UNKNOWN")
    pending = (await store.inspect(actor, authority.binding_id, original.source_id))["pending_corrections"][0]
    assert pending["logical_retraction"] == ("committed" if append_landed else "unknown")
    assert pending["replacement_capture"] == "pending_or_unknown" and pending["retry_same_key"]
    async with store.pool.acquire() as connection:
        assert request.body not in str(await connection.fetch("SELECT * FROM am_receipts WHERE kind='correct_intent'"))
        assert request.body not in str(await connection.fetch("SELECT * FROM am_origin_reservations"))
    monkeypatch.setattr(store, "_append_deletion_intent", append)
    replacement = await store.correct(actor, authority.binding_id, original.source_id, request)
    assert (await store.source(actor, authority.binding_id, replacement.source_id)).body == request.body
    assert (await store.correct(actor, authority.binding_id, original.source_id, request)).id == replacement.id


async def test_embedding_only_sibling_recovery_never_undoes_withdrawn_derivation_floor(authority):
    store, actor = authority.store, authority.actor
    first_text, second_text = "CacheKey is retained only offline.", "OtherKey is retained only offline."
    body = first_text + " " + second_text
    source = await store.capture(actor, command(authority, body=body))
    first = extraction(source.source_id, first_text).claims[0]
    second = first.model_copy(update={"statement": second_text, "subject": "OtherKey", "entities": ("OtherKey",),
        "evidence": (Quote(source_id=source.source_id, quote=second_text, byte_start=body.encode().find(second_text.encode())),)})
    lease = await store.claim_job()
    admission = await store.admit_job(lease, authority.revision, "extraction")
    await store.publish_extraction(lease, admission, Extraction(claims=(first, second)), [VECTOR, VECTOR],
        [["CacheKey", "offline"], ["OtherKey", "offline"]])
    consolidation = await store.claim_job()
    admitted = await store.admit_job(consolidation, authority.revision, "consolidation")
    await store.publish_consolidation(consolidation, admitted, Consolidation(relations=()))
    found = await store.search(actor, authority.binding_id, VECTOR, ["CacheKey", "OtherKey"], None)
    withdrawn = next(item for item, _ in found if item.draft.subject == "CacheKey")
    sibling = next(item for item, _ in found if item.draft.subject == "OtherKey")
    deletion = await store.retract(actor, authority.binding_id, withdrawn.id, "withdraw-one-derivation")
    advance_manifest(authority, embedding=True)
    await store.configure_route(actor, authority.revision, ("embedding",), True)
    await store.recover_index(actor, authority.binding_id, (sibling.id,), "recover-surviving-sibling")
    reindex = await store.claim_job()
    indexed = await store.admit_job(reindex, authority.revision, "embedding")
    await store.publish_reindex(reindex, indexed, [VECTOR], [["OtherKey", "offline"]])
    assert store.journal.verify()["head"] == deletion["head"]
    assert (await store.source(actor, authority.binding_id, source.source_id)).body == body
    assert (await store.claim(actor, authority.binding_id, sibling.id)).evidence == sibling.evidence
    with pytest.raises(DomainError):
        await store.claim(actor, authority.binding_id, withdrawn.id)
    with pytest.raises(DomainError) as floor:
        await store.reprocess(actor, authority.binding_id, source.source_id, "forbidden-full-reextraction")
    assert floor.value.code == "DERIVATION_RETRACTED"
    stats = await store.stats(actor, authority.binding_id)
    assert stats["active_claims"] == 1 and stats["stale_index_claims"] == 0


@pytest.mark.parametrize("required", (False, True))
async def test_revocation_acknowledges_required_impact_and_reapproves_exact_frozen_rule(authority, required):
    store, actor = authority.store, authority.actor
    token = "approval-rotation-token-" + "v" * 32
    approver = await store.issue_token(actor, Role.OPERATOR, (authority.binding_id,), token)
    proposal = await store.propose_rule(actor, RuleProposal(binding_id=authority.binding_id,
        idempotency_key="rotation-proposal", body="Review CacheKey before changing it.", required=required))
    approval = RuleApproval(proposal_id=proposal["proposal_id"], expected_digest=proposal["digest"],
        scope=RuleScope.LOCAL_PROJECT, target_bindings=(authority.binding_id,),
        target_set_revision=proposal["target_set_revision"], idempotency_key="rotation-approval")
    active = await store.approve_rule(approver, approval)
    impact = await store.credential_revocation_impact(actor, approver.credential_id)
    assert impact["affected_rule_ids"] == [active.id]
    assert impact["required_rule_ids"] == ([active.id] if required else [])
    if required:
        with pytest.raises(DomainError) as unacknowledged:
            await store.revoke_token(actor, approver.credential_id)
        assert unacknowledged.value.code == "REQUIRED_RULE_REVOCATION_ACK_REQUIRED"
        assert (await store.authenticate(token)).credential_id == approver.credential_id
        assert [rule.id for rule in await store.rules(actor, authority.binding_id)] == [active.id]
        assert (await store.credential_revocation_impact(actor, approver.credential_id)) == impact
    revoked = await store.revoke_token(actor, approver.credential_id, acknowledge_required=required)
    assert revoked["revoked"] and revoked["affected_rule_ids"] == [active.id]
    assert revoked["required_rule_ids"] == impact["required_rule_ids"]
    with pytest.raises(DomainError) as stale_token:
        await store.authenticate(token)
    assert stale_token.value.code == "AUTH_DENIED"
    assert await store.rules(actor, authority.binding_id) == []
    reapproval = approval.model_copy(update={"idempotency_key": "rotation-reapproval"})
    with pytest.raises(DomainError) as changed_scope:
        await store.approve_rule(actor, reapproval.model_copy(update={"scope": RuleScope.SHARED}))
    assert changed_scope.value.code == "APPROVAL_CONFLICT"
    revised = await store.approve_rule(actor, reapproval)
    assert revised.id != active.id and revised.revision > active.revision
    assert revised.digest == active.digest and revised.body == active.body and revised.required == required
    assert await store.approve_rule(actor, reapproval) == revised
    with pytest.raises(DomainError) as duplicate:
        await store.approve_rule(actor, reapproval.model_copy(update={"idempotency_key": "conflicting-active-reapproval"}))
    assert duplicate.value.code == "APPROVAL_CONFLICT"
    async with store.pool.acquire() as connection:
        original = await connection.fetchrow("SELECT * FROM am_rules WHERE id=$1", active.id)
        current = await connection.fetchrow("SELECT * FROM am_rules WHERE id=$1", revised.id)
        assert original["state"] == "retracted" and original["approver_credential_id"] == approver.credential_id
        assert current["state"] == "active" and current["approver_credential_id"] == actor.credential_id
    await store.retract(actor, authority.binding_id, proposal["source_id"], "floor-approved-body")
    with pytest.raises(DomainError) as deleted:
        await store.approve_rule(actor, reapproval.model_copy(update={"idempotency_key": "floor-cannot-reapprove"}))
    assert deleted.value.code == "APPROVAL_STALE"


async def test_logical_relation_recall_collapses_independent_derivations_without_merging_lineage(authority):
    from itertools import combinations

    store, actor = authority.store, authority.actor
    sources, claims = [], []
    for index in range(10):
        operation, claim = await ready_claim(authority, f"independent-{index}",
            f"CacheKey is retained offline after review {index}.")
        sources.append(operation.source_id)
        claims.append(claim.id)
    left, right = claims[:2]
    result = Consolidation(relations=(RelationDraft(left_id=left, right_id=right,
        kind="contradicts", reason="The independently considered alternatives disagree."),))
    manifests = [(*claims[:2], *subset) for count in range(9)
        for subset in combinations(claims[2:], count)][:130]
    for manifest in [*manifests, manifests[0]]:
        async with store._tx() as (connection, _):
            operation = await store._new_operation(connection, actor, authority.binding_id, "reprocess")
            input_sources = await connection.fetch("SELECT DISTINCT source_id FROM am_claim_sources WHERE claim_id=ANY($1::text[]) ORDER BY source_id", list(manifest))
            await store._enqueue(connection, actor, operation["id"], authority.binding_id, "consolidate",
                tuple(row["source_id"] for row in input_sources), manifest)
        lease = await store.claim_job()
        admission = await store.admit_job(lease, authority.revision, "consolidation")
        completed = await store.publish_consolidation(lease, admission, result)
        assert completed.state == "semantic_ready"
    logical = await store.relations(actor, authority.binding_id, (left, right))
    assert len(logical) == 1
    async with store.pool.acquire() as connection:
        rows = await connection.fetch("""SELECT r.id,array_agg(d.claim_id ORDER BY d.claim_id) AS claims
            FROM am_relations r JOIN am_relation_claims d ON d.relation_id=r.id GROUP BY r.id""")
        assert len(rows) == 130
        assert {tuple(row["claims"]) for row in rows} == {tuple(sorted(manifest)) for manifest in manifests}
        for row in rows:
            actual = await connection.fetch("SELECT source_id FROM am_relation_sources WHERE relation_id=$1 ORDER BY source_id", row["id"])
            expected = sorted(sources[claims.index(claim_id)] for claim_id in row["claims"])
            assert [item["source_id"] for item in actual] == expected
    reader = await store.admit_read(actor, authority.binding_id, (left, right), authority.revision, "rerank")
    await store.delivery(actor, authority.binding_id, (reader,), (), relation_ids=(logical[0].id,))
    await store.retract(actor, authority.binding_id, sources[2], "withdraw-one-independent-input")
    remaining = await store.relations(actor, authority.binding_id, (left, right))
    assert len(remaining) == 1
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT count(*) FROM am_relations WHERE state='retracted'") > 0
        assert await connection.fetchval("SELECT count(*) FROM am_relations WHERE state='active'") > 0
    await store.retract(actor, authority.binding_id, sources[0], "withdraw-common-endpoint")
    assert await store.relations(actor, authority.binding_id, (right,)) == []
