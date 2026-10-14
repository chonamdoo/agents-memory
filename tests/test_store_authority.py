from __future__ import annotations

import asyncio
import base64
import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import asyncpg
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from agents_memory.config import Settings
from agents_memory.domain import (
    CaptureCommand,
    ClaimDraft,
    ContextCommand,
    DomainError,
    Extraction,
    FeedbackCommand,
    Principal,
    Quote,
    RecordCommand,
    RelevanceJudgment,
    Role,
    RuleApproval,
    RuleProposal,
    RuleScope,
    approval_signing_payload,
    canonical_digest,
)
from agents_memory.journal import DeletionJournal
from agents_memory.lexical import tokens
from agents_memory.migrations import migrate
from agents_memory.selection import (
    ClaimJudgmentCommand,
    SourceSelectionCommand,
    selection_contract_revision,
)
from agents_memory.semantic_contract import GeneratedExtraction
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
        settings = Settings(deployment_id="deployment_test", realm="personal_test", mode="personal", database_dsn=dsn,
            state_dir=tmp_path / "restore-unit", journal_dir=tmp_path / "independent-journal")
        store = Store(settings, DeletionJournal(settings.journal_dir, settings.deployment_id))
        await store.open()
        actor = await store.bootstrap(TOKEN, "owner_test")
        binding = await store.register_binding(actor, "Isolated project", None, "binding-registration")
        actor = await store.authenticate(TOKEN)
        yield Authority(store, actor, binding.id, selection_contract_revision())
    finally:
        if store is not None:
            await store.close()
        await admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await admin.close()


async def historical_schema_fixture(store: Store, archived_index: int) -> None:
    """Build only isolated historical fixtures; the independent journal is never downgraded."""
    from agents_memory.migrations import MIGRATION, MIGRATIONS

    assert 0 <= archived_index < len(MIGRATIONS) - 1
    async with store.pool.acquire() as connection:
        async with connection.transaction():
            schema = await connection.fetchval("SELECT current_schema()")
            prefix, separator, suffix = schema.rpartition("_")
            assert separator and prefix in {"am_test", "am_ops_test", "am_host_capture"}
            assert len(suffix) == 32 and all(character in "0123456789abcdef" for character in suffix)
            assert await connection.fetchval("SELECT version_num FROM alembic_version") == MIGRATION
            await connection.execute("""
                ALTER TABLE am_claims DROP COLUMN cleanup_sequence;
                ALTER TABLE am_clock DROP COLUMN cleanup_progress;
                DROP INDEX am_rejection_history_selection;
                DROP INDEX am_rejection_history_feedback;
                DROP INDEX am_feedback_reason_source;
                DROP TABLE am_rejection_tokens;
                DROP TABLE am_rejection_evidence;
                ALTER TABLE am_relations DROP COLUMN judgment_id;
                DROP TABLE am_claim_judgments;
                UPDATE am_jobs j SET
                    state=r.original->>'state',
                    generation=(r.original->>'generation')::bigint,
                    lease_token=r.original->>'lease_token',
                    deadline=(r.original->>'deadline')::timestamptz
                FROM am_retired_jobs r WHERE r.job_id=j.id AND j.state='retired';
                DROP TABLE am_retired_jobs;
                ALTER TABLE am_admissions DROP COLUMN IF EXISTS pending_id;
                DROP TABLE am_pending_judgments;
                ALTER TABLE am_jobs DROP COLUMN retired_at;
                ALTER TABLE am_claims DROP COLUMN revision;
                ALTER TABLE am_claims DROP COLUMN awaiting_revalidation;
                ALTER TABLE am_claims DROP CONSTRAINT am_claims_capability_origin;
                ALTER TABLE am_claims DROP CONSTRAINT am_claims_capability_check;
                UPDATE am_claims SET capability='lexical_entity' WHERE capability='agent_judged';
                ALTER TABLE am_claims ADD CONSTRAINT am_claims_capability_check
                    CHECK(capability IN ('full_semantic','lexical_entity'));
                ALTER TABLE am_claims ADD CONSTRAINT am_claims_capability_origin CHECK (
                    (capability='full_semantic' AND route_revision IS NOT NULL
                     AND interpretation_role='model_derived_candidate' AND selection_id IS NULL AND policy_revision IS NULL)
                    OR (capability='lexical_entity' AND route_revision IS NULL AND embedding IS NULL AND vector_revision IS NULL
                     AND interpretation_role='caller_grounded_candidate' AND selection_id IS NOT NULL AND policy_revision IS NOT NULL)
                );
                ALTER TABLE am_source_selections DROP COLUMN reason;
                ALTER TABLE am_source_selections DROP COLUMN prior_rejection_ids;
                ALTER TABLE am_source_selections DROP COLUMN rejection_comparisons;
                ALTER TABLE am_source_selections DROP COLUMN request_snapshot;
                ALTER TABLE am_source_selections DROP COLUMN rejection_inputs;
                ALTER TABLE am_source_selections DROP COLUMN rejection_review_ids;
                ALTER TABLE am_source_selections DROP COLUMN deletion_generation;
                ALTER TABLE am_feedback DROP COLUMN reason;
                ALTER TABLE am_feedback DROP COLUMN rejected_source_ids;
                ALTER TABLE am_feedback ALTER COLUMN state SET DEFAULT 'candidate';
                ALTER TABLE am_admissions DROP COLUMN request_digest;
                ALTER TABLE am_admissions DROP COLUMN claim_revisions;
                ALTER TABLE am_admissions DROP COLUMN rejection_ids;
                ALTER TABLE am_admissions DROP COLUMN rejection_inputs;
                ALTER TABLE am_clock DROP COLUMN retired_authority;
            """)
            if archived_index < 4:
                assert not await connection.fetchval("SELECT EXISTS(SELECT 1 FROM am_claims WHERE capability<>'full_semantic')")
                assert not await connection.fetchval("SELECT EXISTS(SELECT 1 FROM am_admissions WHERE kind<>'model')")
                await connection.execute("""
                    ALTER TABLE am_claims DROP CONSTRAINT am_claims_capability_origin;
                    ALTER TABLE am_claims DROP COLUMN capability;
                    ALTER TABLE am_claims DROP COLUMN interpretation_role;
                    ALTER TABLE am_claims DROP COLUMN selection_id;
                    ALTER TABLE am_claims DROP COLUMN policy_revision;
                    ALTER TABLE am_claims ALTER COLUMN route_revision SET NOT NULL;
                    DROP TABLE am_selection_sources;
                    DROP TABLE am_source_selections;
                    DROP TABLE am_selection_policies;
                    ALTER TABLE am_sources DROP COLUMN producer_generation;
                    ALTER TABLE am_sources DROP COLUMN capture_coverage;
                    ALTER TABLE am_operations DROP COLUMN source_pointer;
                    ALTER TABLE am_operations DROP COLUMN capture_disposition;
                    ALTER TABLE am_operations DROP COLUMN selection_label;
                    ALTER TABLE am_admissions DROP CONSTRAINT am_admissions_kind_origin;
                    ALTER TABLE am_admissions DROP COLUMN kind;
                    ALTER TABLE am_admissions DROP COLUMN binding_revision;
                    ALTER TABLE am_admissions DROP COLUMN realm;
                    ALTER TABLE am_admissions DROP COLUMN policy_revision;
                    ALTER TABLE am_admissions DROP COLUMN policy_epoch;
                    ALTER TABLE am_admissions DROP COLUMN relation_ids;
                    ALTER TABLE am_admissions ALTER COLUMN route_revision SET NOT NULL;
                    DELETE FROM am_floors WHERE kind IN ('purge_source','purge_origin','purge_artifact');
                    ALTER TABLE am_floors DROP CONSTRAINT am_floors_kind_check;
                    ALTER TABLE am_floors ADD CONSTRAINT am_floors_kind_check CHECK(kind IN ('source','origin','artifact'));
                """)
            if archived_index < 3:
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
                    ALTER TABLE am_jobs ADD CONSTRAINT am_jobs_kind_check CHECK(kind IN ('extract','consolidate','reflect'));
                """)
            if archived_index == 0:
                await connection.execute("""
                    DROP TABLE am_relation_claims;
                    ALTER TABLE am_feedback DROP COLUMN state;
                    DELETE FROM am_floors WHERE kind='artifact';
                    ALTER TABLE am_floors DROP CONSTRAINT am_floors_kind_check;
                    ALTER TABLE am_floors ADD CONSTRAINT am_floors_kind_check CHECK(kind IN ('source','origin'));
                """)
            await connection.execute("UPDATE alembic_version SET version_num=$1", MIGRATIONS[archived_index])


def command(authority, key="capture", body="CacheKey is retained only offline.", origin=None, snapshot=None):
    return CaptureCommand(binding_id=authority.binding_id, idempotency_key=key, origin_key=origin or key,
        body=body, speaker="human", snapshot=snapshot)


def extraction(source_id, quote="CacheKey is retained only offline.", offset=0, statement=None):
    return Extraction(claims=(ClaimDraft(statement=statement or quote, kind="fact", subject="CacheKey", predicate="retained", object="offline",
        polarity="positive", modality="asserted", conditions=("only offline",), entities=("CacheKey",),
        evidence=(Quote(source_id=source_id, quote=quote, byte_start=offset),)),))


async def source_selection(authority, source_id, key="selection", *, snapshot=None, label="remember", statement=None, prior_rejection_ids=(), polarity="positive"):
    window = await authority.store.inspect(authority.actor, authority.binding_id, source_id, snapshot)
    generated = None
    if label == "remember":
        span = window["span_inventory"][0]
        subject = "OtherKey" if "OtherKey" in span["quote"] and "CacheKey" not in span["quote"] else "CacheKey"
        generated = GeneratedExtraction(claims=({
            "assertion_id": "a0000", "assertion_span_id": span["span_id"], "statement": statement or span["quote"],
            "kind": "fact", "subject": subject, "predicate": "retained", "object": "offline",
            "polarity": polarity, "modality": "asserted", "entities": (subject,),
        },), individual_qualifications=({"assertion_id": "a0000", "kind": "condition", "phrase": "only offline", "evidence_span_id": span["span_id"]},) if "only offline" in span["quote"] else (),
            shared_qualifications=(), validities=(), unused_span_ids=tuple(item["span_id"] for item in window["span_inventory"][1:]))
    return SourceSelectionCommand(kind="source_selection", binding_id=authority.binding_id, idempotency_key=key,
        admission_id=window["admission_id"], source_id=source_id, source_revision=window["source_revision"],
        binding_revision=window["binding_revision"], snapshot=snapshot, byte_start=window["byte_start"], byte_end=window["byte_end"],
        window_digest=window["window_digest"], policy_revision=window["policy_revision"], policy_epoch=window["policy_epoch"],
        label=label, coverage="complete_window", extraction=generated, reason="Caller checked original evidence and qualifications.",
        prior_rejection_ids=prior_rejection_ids,
        rejection_comparisons=tuple({"rejection_id": rejection_id,
            "decision": "reopen" if rejection_id in prior_rejection_ids else "unrelated",
            "reason": "Caller compared this evidence with the persisted rejection."}
            for rejection_id in dict.fromkeys([*(item["id"] for item in window["judgment_context"]["rejections"]), *prior_rejection_ids])))


async def ready_claim(authority, key="capture", body="CacheKey is retained only offline.", snapshot=None, polarity="positive"):
    operation = await authority.store.capture(authority.actor, command(authority, key, body, snapshot=snapshot))
    selected = await authority.store.record(authority.actor, await source_selection(authority, operation.source_id, key + "-selection", snapshot=snapshot, polarity=polarity))
    inspected = await authority.store.inspect(authority.actor, authority.binding_id, selected.artifact_id, snapshot)
    own = await authority.store.claim(authority.actor, authority.binding_id, inspected["claim_ids"][0], snapshot)
    return operation, own


async def recall_context(authority, snapshot=None):
    from agents_memory.application import Application
    application = Application(authority.store.settings, authority.store)
    request = ContextCommand(binding_id=authority.binding_id, query="CacheKey", snapshot=snapshot)
    pool = await application.context(authority.actor, request)
    claim_ids = tuple(item["claim_id"] for item in pool["candidate_manifest"])
    for claim_id in claim_ids:
        await authority.store.inspect(authority.actor, authority.binding_id, claim_id, snapshot)
    decisions = tuple(RelevanceJudgment(claim_id=claim_id, relevant=True, reason="Caller reviewed this candidate.") for claim_id in claim_ids)
    return await application.context(authority.actor, request.model_copy(update={"admission_id": pool["admission_id"], "relevance": decisions}))


async def relation_judgment(authority, left, right, relation="supports", key="relation"):
    manifest = await authority.store.inspect(authority.actor, authority.binding_id, "judgment", left.snapshot)
    for item in manifest["claims"]:
        await authority.store.inspect(authority.actor, authority.binding_id, item["id"], left.snapshot)
    return ClaimJudgmentCommand(kind="claim_judgment", binding_id=authority.binding_id, idempotency_key=key,
        admission_id=manifest["admission_id"], manifest_digest=manifest["manifest_digest"], claims=manifest["claims"], sources=manifest["sources"],
        relations=({"left_id": left.id, "right_id": right.id, "relation": relation, "reason": "Caller compared the independent source evidence."},),
        reason="Caller inspected every claim and source in this exact manifest.")


def without_coverage(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if key != "coverage"}



async def retracted_pair(authority):
    store, actor = authority.store, authority.actor
    first = await store.capture(actor, command(authority, "purge-first"))
    second = await store.capture(actor, command(authority, "purge-second"))
    await store.retract(actor, authority.binding_id, first.source_id, "retract-first")
    await store.retract(actor, authority.binding_id, second.source_id, "retract-second")
    return first, second


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
    assert stats["historical_jobs"] == {}



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
    assert retry.state == "captured" and retry.source_id != original.source_id



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



async def test_independent_purge_intent_scrubs_restored_personal_body_draft_and_quote(authority):
    store, actor = authority.store, authority.actor
    operation, claim = await ready_claim(authority)
    original_source = await store.source(actor, authority.binding_id, operation.source_id)
    async with store.pool.acquire() as connection:
        archived_head = await connection.fetchval("SELECT journal_head FROM am_clock WHERE singleton")
        archived_draft = await connection.fetchval("SELECT draft FROM am_claims WHERE id=$1", claim.id)
    await store.retract(actor, authority.binding_id, operation.source_id, "withdraw-before-purge")
    await store.purge(actor, authority.binding_id, operation.source_id, "durable-purge")
    retained_head = store.journal.verify()["head"]
    async with store.pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute("UPDATE am_sources SET body=$2,state='active',revision=$3 WHERE id=$1",
                operation.source_id, original_source.body, original_source.revision)
            await connection.execute("UPDATE am_claims SET draft=$2::jsonb,state='active' WHERE id=$1", claim.id, archived_draft)
            await connection.execute("UPDATE am_spans SET quote=$2 WHERE claim_id=$1", claim.id, claim.evidence[0].quote)
            await connection.execute("DELETE FROM am_floors")
            await connection.execute("UPDATE am_clock SET journal_head=$1 WHERE singleton", archived_head)
    with pytest.raises(DomainError) as barrier:
        await store.source(actor, authority.binding_id, operation.source_id)
    assert barrier.value.code == "DELETION_BARRIER"
    await store.reconcile_journal(retained_head)
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT body IS NULL AND state='purged' FROM am_sources WHERE id=$1", operation.source_id)
        assert await connection.fetchval("SELECT draft IS NULL FROM am_claims WHERE id=$1", claim.id)
        assert await connection.fetchval("SELECT bool_and(quote IS NULL) FROM am_spans WHERE claim_id=$1", claim.id)
    with pytest.raises(DomainError) as withdrawn:
        await store.claim(actor, authority.binding_id, claim.id)
    assert withdrawn.value.code == "CLAIM_INELIGIBLE"



async def test_pre_coverage_capture_and_correction_digests_keep_replaying(authority, monkeypatch):
    from agents_memory.domain import CaptureCoverage, EffectState, canonical_digest

    store, actor = authority.store, authority.actor
    request = command(authority, "legacy-capture")
    original = await store.capture(actor, request)
    async with store.pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute("UPDATE am_receipts SET digest=$3 WHERE principal_id=$1 AND kind='capture' AND request_key=$2",
                actor.id, request.idempotency_key, canonical_digest(without_coverage(request.model_dump(mode="json"))))
            await connection.execute("UPDATE am_sources SET origin_digest=$2 WHERE id=$1", original.source_id,
                canonical_digest(without_coverage(request.model_dump(mode="json", exclude={"idempotency_key"}))))
    assert (await store.capture(actor, request)).id == original.id
    assert (await store.capture(actor, request.model_copy(update={"idempotency_key": "legacy-origin-retry"}))).id == original.id
    observed = request.model_copy(update={"coverage": CaptureCoverage(status="observed_window",
        original_bytes=len(request.body.encode()))})
    with pytest.raises(DomainError) as changed_key:
        await store.capture(actor, observed)
    assert changed_key.value.code == "IDEMPOTENCY_CONFLICT"
    with pytest.raises(DomainError) as changed_origin:
        await store.capture(actor, observed.model_copy(update={"idempotency_key": "legacy-coverage"}))
    assert changed_origin.value.code == "ORIGIN_CONFLICT"

    replacement = command(authority, "legacy-correction", "CacheKey is retained after review.", origin="legacy-replacement")
    append = store._append_deletion_intent

    async def landed_then_unknown(binding_id, sources, artifacts=()):
        await append(binding_id, sources, artifacts)
        raise DomainError("DELETION_BARRIER", "The append outcome is unknown", status=503, effect=EffectState.UNKNOWN)

    monkeypatch.setattr(store, "_append_deletion_intent", landed_then_unknown)
    with pytest.raises(DomainError) as partial:
        await store.correct(actor, authority.binding_id, original.source_id, replacement)
    assert partial.value.code == "CORRECTION_PARTIAL"
    monkeypatch.setattr(store, "_append_deletion_intent", append)
    corrected = replacement.model_copy(update={"kind": "correction"})
    legacy_intent = canonical_digest({"target_ref": original.source_id, "command": without_coverage(corrected.model_dump(mode="json"))})
    legacy_origin = canonical_digest(without_coverage(corrected.model_dump(mode="json", exclude={"idempotency_key"})))
    async with store.pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute("UPDATE am_receipts SET digest=$3 WHERE principal_id=$1 AND kind='correct_intent' AND request_key=$2",
                actor.id, replacement.idempotency_key, legacy_intent)
            await connection.execute("UPDATE am_origin_reservations SET intent_digest=$2,origin_digest=$3 WHERE request_key=$1",
                replacement.idempotency_key, legacy_intent, legacy_origin)
    with pytest.raises(DomainError) as changed_correction:
        await store.correct(actor, authority.binding_id, original.source_id,
            replacement.model_copy(update={"coverage": CaptureCoverage(status="truncated")}))
    assert changed_correction.value.code == "IDEMPOTENCY_CONFLICT"
    completed = await store.correct(actor, authority.binding_id, original.source_id, replacement)
    assert completed.source_id != original.source_id
    assert (await store.source(actor, authority.binding_id, completed.source_id)).body == replacement.body



async def test_conflicting_concurrent_purge_key_never_purges_both_targets(authority):
    store, actor = authority.store, authority.actor
    first, second = await retracted_pair(authority)
    entries = len(store.journal.entries())
    results = await asyncio.gather(store.purge(actor, authority.binding_id, first.source_id, "same-purge-key"),
        store.purge(actor, authority.binding_id, second.source_id, "same-purge-key"), return_exceptions=True)
    assert sum(isinstance(result, dict) for result in results) == 1
    error = next(result for result in results if isinstance(result, DomainError))
    assert error.code == "IDEMPOTENCY_CONFLICT" and error.effect.value == "not_started"
    assert len(store.journal.entries()) == entries + 1
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT count(*) FROM am_sources WHERE id=ANY($1::text[]) AND body IS NULL",
            [first.source_id, second.source_id]) == 1



async def test_interrupted_purge_reserves_its_key_for_the_original_target(authority, monkeypatch):
    from agents_memory.domain import EffectState

    store, actor = authority.store, authority.actor
    first, second = await retracted_pair(authority)
    status = Store._deletion_status

    async def interrupted(self, *args, **kwargs):
        raise DomainError("DATABASE_UNAVAILABLE", "The purge receipt outcome is unknown", status=503, effect=EffectState.UNKNOWN)

    monkeypatch.setattr(Store, "_deletion_status", interrupted)
    with pytest.raises(DomainError) as unknown:
        await store.purge(actor, authority.binding_id, first.source_id, "interrupted-purge")
    assert unknown.value.effect == EffectState.UNKNOWN
    monkeypatch.setattr(Store, "_deletion_status", status)
    entries = len(store.journal.entries())
    with pytest.raises(DomainError) as conflict:
        await store.purge(actor, authority.binding_id, second.source_id, "interrupted-purge")
    assert conflict.value.code == "IDEMPOTENCY_CONFLICT" and conflict.value.effect == EffectState.NOT_STARTED
    assert len(store.journal.entries()) == entries
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT body IS NOT NULL FROM am_sources WHERE id=$1", second.source_id)
    retried = await store.purge(actor, authority.binding_id, first.source_id, "interrupted-purge")
    assert retried["physical_purge"] == "physically_purged"
    assert await store.purge(actor, authority.binding_id, first.source_id, "interrupted-purge") == retried



async def test_purge_floor_scrub_runs_only_when_new_purge_floors_land(authority, monkeypatch):
    store, actor = authority.store, authority.actor
    first = await store.capture(actor, command(authority, "scrub-first"))
    second = await store.capture(actor, command(authority, "scrub-second"))
    await store.retract(actor, authority.binding_id, first.source_id, "retract-scrub-first")
    scrub = Store._scrub_purge_floors
    calls = []

    async def spy(self, connection):
        calls.append(True)
        return await scrub(self, connection)

    monkeypatch.setattr(Store, "_scrub_purge_floors", spy)
    await store.purge(actor, authority.binding_id, first.source_id, "purge-scrub-first")
    assert calls
    calls.clear()
    await store.retract(actor, authority.binding_id, second.source_id, "retract-scrub-second")
    await store.reconcile_journal()
    assert calls == []



async def test_capture_is_unclassified_and_only_inspected_caller_selection_publishes(authority):
    store, actor = authority.store, authority.actor
    operation = await store.capture(actor, command(authority))
    assert operation.state == "captured" and operation.source_pointer.source_revision == 1
    assert (await store.stats(actor, authority.binding_id))["active_claims"] == 0
    pending = await store.inspect(actor, authority.binding_id, "pending")
    assert pending["items"][0]["kind"] == "source_selection"
    selected = await store.record(actor, await source_selection(authority, operation.source_id))
    replay = await store.record(actor, await source_selection(authority, operation.source_id, "different-selection"))
    assert selected.state == replay.state == "candidate_ready"
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT count(*) FROM am_jobs") == 0
    assert (await store.stats(actor, authority.binding_id))["active_claims"] == 2


@pytest.mark.parametrize("change", ("source", "binding", "credential", "grant", "deletion", "deadline", "contract"))
async def test_saved_source_selection_rejects_stale_authority(authority, change):
    store, actor = authority.store, authority.actor
    operation = await store.capture(actor, command(authority))
    selection = await source_selection(authority, operation.source_id)
    async with store.pool.acquire() as connection:
        if change == "source":
            await connection.execute("UPDATE am_sources SET revision=revision+1 WHERE id=$1", operation.source_id)
        elif change == "binding":
            await connection.execute("UPDATE am_bindings SET revision=revision+1 WHERE id=$1", authority.binding_id)
        elif change == "credential":
            await connection.execute("UPDATE am_credentials SET generation=generation+1 WHERE id=$1", actor.credential_id)
        elif change == "grant":
            await connection.execute("DELETE FROM am_grants WHERE credential_id=$1 AND binding_id=$2", actor.credential_id, authority.binding_id)
        elif change == "deletion":
            await connection.execute("UPDATE am_clock SET deletion_generation=deletion_generation+1")
        elif change == "deadline":
            await connection.execute("UPDATE am_admissions SET deadline='-infinity' WHERE id=$1", selection.admission_id)
        else:
            selection = selection.model_copy(update={"policy_revision": "0" * 64})
    with pytest.raises(DomainError):
        await store.record(actor, selection)
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT count(*) FROM am_claims") == 0


async def test_selection_receipt_replays_after_read_deadline_without_republishing(authority):
    store, actor = authority.store, authority.actor
    operation = await store.capture(actor, command(authority))
    request = await source_selection(authority, operation.source_id)
    selected = await store.record(actor, request)
    async with store.pool.acquire() as connection:
        await connection.execute("UPDATE am_admissions SET deadline='-infinity'")
    assert (await store.record(actor, request)).id == selected.id
    with pytest.raises(DomainError) as conflict:
        await store.record(actor, request.model_copy(update={"reason": "Changed judgment."}))
    assert conflict.value.code == "IDEMPOTENCY_CONFLICT"



async def test_discard_and_reject_reasons_survive_without_retraction_or_floor(authority):
    store, actor = authority.store, authority.actor
    source = await store.capture(actor, command(authority, "discard"))
    head = store.journal.verify()["head"]
    discarded = await store.record(actor, await source_selection(authority, source.source_id, label="discard"))
    assert (await store.inspect(actor, authority.binding_id, discarded.artifact_id))["reason"]
    assert (await store.source(actor, authority.binding_id, source.source_id)).state == "active"
    assert store.journal.verify()["head"] == head
    with pytest.raises(DomainError) as blocked:
        await store.record(actor, await source_selection(authority, source.source_id, "paraphrase", statement="CacheKey remains offline."))
    assert blocked.value.code == "EVIDENCE_REJECTED"
    copy = await store.capture(actor, command(authority, "new-origin-copy"))
    with pytest.raises(DomainError) as copied:
        await store.record(actor, await source_selection(authority, copy.source_id, "copy-select", prior_rejection_ids=(discarded.artifact_id,)))
    assert copied.value.code == "EVIDENCE_REJECTED"
    fresh = await store.capture(actor, command(authority, "independent-confirmation", "CacheKey stays offline after independent review."))
    opened = await store.record(actor, await source_selection(authority, fresh.source_id, "reopen", prior_rejection_ids=(discarded.artifact_id,)))
    assert opened.state == "candidate_ready"
    contextual = await store.inspect(actor, authority.binding_id, fresh.source_id)
    assert contextual["judgment_context"]["accepted_memories"]
    assert contextual["judgment_context"]["rejections"][0]["reason"]
    claimed = (await store.inspect(actor, authority.binding_id, opened.artifact_id))["claim_ids"][0]
    rejected = await store.feedback(actor, FeedbackCommand(binding_id=authority.binding_id, idempotency_key="reject-candidate", target_ref=claimed, kind="reject", body="The scope was not justified."))
    assert (await store.inspect(actor, authority.binding_id, rejected.artifact_id))["reason"] == "The scope was not justified."
    assert (await store.claim(actor, authority.binding_id, claimed)).state == "active"
    assert store.journal.verify()["head"] == head
    with pytest.raises(DomainError) as renewed:
        await store.record(actor, await source_selection(authority, fresh.source_id, "rejected-claim-copy"))
    assert renewed.value.code == "EVIDENCE_REJECTED"


@pytest.mark.parametrize("relation", ("duplicate", "supports", "contradicts", "supersedes"))
async def test_claim_judgments_preserve_every_independent_claim_and_provenance(authority, relation):
    store, actor = authority.store, authority.actor
    left_source, left = await ready_claim(authority, "left")
    right_source, right = await ready_claim(authority, "right",
        "CacheKey is not retained only offline." if relation == "contradicts" else "CacheKey is retained only offline.",
        polarity="negative" if relation == "contradicts" else "positive")
    request = await relation_judgment(authority, left, right, relation)
    written = await store.record(actor, request)
    assert (await store.record(actor, request)).id == written.id
    inspected = await store.inspect(actor, authority.binding_id, written.artifact_id)
    assert {item["id"] for item in inspected["sources"]} == {left_source.source_id, right_source.source_id}
    assert (await store.claim(actor, authority.binding_id, left.id)).evidence == left.evidence
    assert (await store.claim(actor, authority.binding_id, right.id)).evidence == right.evidence
    assert (await store.stats(actor, authority.binding_id))["active_claims"] == 2


@pytest.mark.parametrize("change", ("source", "claim", "manifest", "scope"))
async def test_relation_judgment_rejects_stale_or_mixed_manifests(authority, change):
    store, actor = authority.store, authority.actor
    source, left = await ready_claim(authority, "left")
    _, right = await ready_claim(authority, "right")
    request = await relation_judgment(authority, left, right)
    if change == "manifest":
        request = request.model_copy(update={"claims": request.claims[:1]})
    elif change == "scope":
        other = await store.register_binding(actor, "Other project", None, "other-binding")
        request = request.model_copy(update={"binding_id": other.id})
        actor = await store.authenticate(TOKEN)
    else:
        async with store.pool.acquire() as connection:
            if change == "source":
                await connection.execute("UPDATE am_sources SET revision=revision+1 WHERE id=$1", source.source_id)
            else:
                await connection.execute("UPDATE am_claims SET revision=revision+1 WHERE id=$1", left.id)
    with pytest.raises(DomainError):
        await store.record(actor, request)
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT count(*) FROM am_relations") == 0


async def test_cleanup_schedules_bounded_pending_work_without_semantic_execution(authority):
    store, actor = authority.store, authority.actor
    _, left = await ready_claim(authority, "left")
    _, right = await ready_claim(authority, "right")
    scheduled = await store.schedule_cleanup()
    assert scheduled["created"] == 1
    assert (await store.schedule_cleanup())["created"] == 0
    pending = await store.inspect(actor, authority.binding_id, "pending", max_bytes=4096)
    cleanup = next(item for item in pending["items"] if item["kind"] == "cleanup")
    inspected = await store.inspect(actor, authority.binding_id, cleanup["id"])
    assert len(inspected["judgment_manifest"]["claims"]) == 2
    await store.record(actor, await relation_judgment(authority, left, right))
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT state FROM am_pending_judgments WHERE id=$1", cleanup["id"]) == "resolved"
        assert await connection.fetchval("SELECT count(*) FROM am_jobs") == 0


async def test_recall_admission_binds_request_credential_and_final_delivery(authority):
    store, actor = authority.store, authority.actor
    operation, claim = await ready_claim(authority)
    digest = canonical_digest({"query": "CacheKey", "query_expansions": ["offline"]})
    rows, admission = await store.search_lexical(actor, authority.binding_id, tokens("CacheKey offline"), None, request_digest=digest)
    assert rows[0][0].id == claim.id
    recovered, claims = await store.recall_admission(actor, authority.binding_id, admission.id, digest, None)
    assert recovered == admission and [item.id for item in claims] == [claim.id]
    with pytest.raises(DomainError):
        await store.recall_admission(actor, authority.binding_id, admission.id, "0" * 64, None)
    await store.delivery(actor, authority.binding_id, (), (), nonmodel_admission=admission, selected_claim_ids=(claim.id,))
    await store.retract(actor, authority.binding_id, operation.source_id, "withdraw")
    with pytest.raises(DomainError) as stale:
        await store.delivery(actor, authority.binding_id, (), (), nonmodel_admission=admission, selected_claim_ids=(claim.id,))
    assert stale.value.code == "CONTEXT_STALE"


async def test_withdrawn_claim_cannot_regenerate_from_same_source_after_restore(authority):
    store, actor = authority.store, authority.actor
    operation, claim = await ready_claim(authority)
    old_head = store.journal.verify()["head"]
    outcome = await store.retract(actor, authority.binding_id, claim.id, "withdraw-derived")
    assert (await store.source(actor, authority.binding_id, operation.source_id)).state == "active"
    async with store.pool.acquire() as connection:
        await connection.execute("UPDATE am_claims SET state='active' WHERE id=$1", claim.id)
        await connection.execute("DELETE FROM am_floors WHERE kind='artifact'")
        await connection.execute("UPDATE am_clock SET journal_head=$1", old_head)
    await store.reconcile_journal(outcome["head"])
    with pytest.raises(DomainError) as blocked:
        await store.record(actor, await source_selection(authority, operation.source_id, "regeneration"))
    assert blocked.value.code == "DERIVATION_RETRACTED"


@pytest.mark.parametrize("event_time", [None, datetime(2020, 1, 2, tzinfo=UTC)])
async def test_original_source_times_survive_caller_publication_inspection_and_recall(authority, event_time):
    store, actor = authority.store, authority.actor
    request = command(authority, "source-time", "CacheKey is retained only offline; the change happened yesterday.").model_copy(update={"event_time": event_time})
    operation = await store.capture(actor, request)
    captured_at, selected_at = datetime(2026, 10, 9, tzinfo=UTC), datetime(2026, 10, 10, tzinfo=UTC)
    async with store.pool.acquire() as connection:
        await connection.execute("UPDATE am_sources SET recorded_at=$2 WHERE id=$1", operation.source_id, captured_at)
    selected = await store.record(actor, await source_selection(authority, operation.source_id))
    claim_id = (await store.inspect(actor, authority.binding_id, selected.artifact_id))["claim_ids"][0]
    async with store.pool.acquire() as connection:
        await connection.execute("UPDATE am_claims SET created_at=$2 WHERE id=$1", claim_id, selected_at)
    claimed = await store.claim(actor, authority.binding_id, claim_id)
    inspected = await store.inspect(actor, authority.binding_id, claim_id)
    recalled = json.loads((await recall_context(authority))["context"])["memory_candidates"][0]
    for span in (inspected["evidence"][0], recalled["evidence"][0]):
        if event_time is None:
            assert span["source_event_time"] is None
        else:
            assert datetime.fromisoformat(span["source_event_time"]) == event_time
        assert datetime.fromisoformat(span["source_recorded_at"]) == captured_at
        assert span["source_speaker"] == "human"
    assert claimed.created_at == selected_at
    assert claimed.draft.valid_from is None and claimed.draft.valid_until is None


async def test_new_source_requires_explicit_comparison_of_inspected_rejections(authority):
    store, actor = authority.store, authority.actor
    rejected = await store.capture(actor, command(authority, "rejected"))
    discarded = await store.record(actor, await source_selection(authority, rejected.source_id, "discard", label="discard"))
    fresh = await store.capture(actor, command(authority, "fresh", "CacheKey stays offline after independent review."))
    request = await source_selection(authority, fresh.source_id, "fresh-select")
    with pytest.raises(DomainError) as omitted:
        await store.record(actor, request.model_copy(update={"rejection_comparisons": ()}))
    assert omitted.value.code == "REJECTION_COMPARISON_REQUIRED"
    compared = request.rejection_comparisons[0].model_copy(update={"decision": "reopen"})
    with pytest.raises(DomainError) as missing_reference:
        await store.record(actor, request.model_copy(update={"rejection_comparisons": (compared,)}))
    assert missing_reference.value.code == "REJECTION_REFERENCE_INVALID"
    explicit = request.model_copy(update={"rejection_comparisons": (compared,), "prior_rejection_ids": (discarded.artifact_id,)})
    assert (await store.record(actor, explicit)).state == "candidate_ready"


async def test_pending_inspection_keyset_does_not_skip_work_when_prior_page_resolves(authority):
    store, actor = authority.store, authority.actor
    for index in range(40):
        await store.capture(actor, command(authority, f"pending-{index}"))
    first = await store.inspect(actor, authority.binding_id, "pending", max_bytes=1024)
    assert first["partial"] and first["next_cursor"] is not None
    seen = {item["id"] for item in first["items"]}
    for item in first["items"]:
        await store.record(actor, await source_selection(authority, item["source_ids"][0], item["id"], label="discard"))
    cursor = first["next_cursor"]
    while True:
        page = await store.inspect(actor, authority.binding_id, "pending", byte_start=cursor, max_bytes=1024)
        page_ids = {item["id"] for item in page["items"]}
        assert not seen & page_ids
        seen |= page_ids
        if not page["partial"]:
            break
        assert page["next_cursor"] > cursor
        cursor = page["next_cursor"]
    assert len(seen) == 40


async def test_partial_source_selection_keeps_unread_suffix_pending(authority):
    store, actor = authority.store, authority.actor
    operation = await store.capture(actor, command(authority, "multi-window", ("CacheKey stays offline.\n" * 200)))
    cursor = 0
    windows = 0
    while True:
        view = await store.inspect(actor, authority.binding_id, operation.source_id, byte_start=cursor, max_bytes=1024)
        request = SourceSelectionCommand(kind="source_selection", binding_id=authority.binding_id,
            idempotency_key=f"window-{windows}", admission_id=view["admission_id"],
            source_id=operation.source_id, source_revision=view["source_revision"],
            binding_revision=view["binding_revision"], snapshot=None, byte_start=view["byte_start"], byte_end=view["byte_end"],
            window_digest=view["window_digest"], policy_revision=view["policy_revision"], policy_epoch=view["policy_epoch"],
            label="discard", coverage="complete_window", reason="Caller inspected this original window and retained no memory.")
        await store.record(actor, request)
        windows += 1
        async with store.pool.acquire() as connection:
            state = await connection.fetchval("SELECT state FROM am_pending_judgments WHERE source_ids=ARRAY[$1]::text[]", operation.source_id)
        if view["next_byte"] is None:
            assert state == "resolved"
            break
        assert state == "pending"
        cursor = view["next_byte"]
    assert windows > 1


async def test_single_claim_cleanup_records_explicit_no_relation_judgment(authority):
    store, actor = authority.store, authority.actor
    _, claim = await ready_claim(authority)
    scheduled = await store.schedule_cleanup()
    inspected = await store.inspect(actor, authority.binding_id, scheduled["pending_ids"][0])
    manifest = inspected["judgment_manifest"]
    await store.inspect(actor, authority.binding_id, claim.id)
    request = ClaimJudgmentCommand(kind="claim_judgment", binding_id=authority.binding_id,
        idempotency_key="no-relations", admission_id=manifest["admission_id"], manifest_digest=manifest["manifest_digest"],
        claims=manifest["claims"], sources=manifest["sources"], relations=(),
        reason="Caller inspected this single claim; there is no pair to relate.")
    committed = await store.record(actor, request)
    assert (await store.record(actor, request)).id == committed.id
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT state FROM am_pending_judgments WHERE id=$1", scheduled["pending_ids"][0]) == "resolved"
        assert await connection.fetchval("SELECT count(*) FROM am_claim_judgments") == 1
        assert await connection.fetchval("SELECT count(*) FROM am_relations") == 0


async def test_recall_final_fence_rechecks_uncited_relation_claim_revision(authority):
    store, actor = authority.store, authority.actor
    _, left = await ready_claim(authority, "left")
    _, right = await ready_claim(authority, "right")
    _, third = await ready_claim(authority, "third", "OtherKey is retained only offline.")
    await store.record(actor, await relation_judgment(authority, left, right))
    candidates, admission = await store.search_lexical(actor, authority.binding_id, tokens("CacheKey"), None,
        limit=1, request_digest="b" * 64)
    assert candidates[0][0].id in {left.id, right.id} and admission.relation_ids
    async with store.pool.acquire() as connection:
        await connection.execute("UPDATE am_claims SET revision=revision+1 WHERE id=$1", third.id)
    with pytest.raises(DomainError) as stale:
        await store.delivery(actor, authority.binding_id, (), (), nonmodel_admission=admission,
            selected_claim_ids=(candidates[0][0].id,))
    assert stale.value.code == "CONTEXT_STALE"


def cleanup_command(authority, manifest, key, relations=()):
    return ClaimJudgmentCommand(kind="claim_judgment", binding_id=authority.binding_id, idempotency_key=key,
        admission_id=manifest["admission_id"], manifest_digest=manifest["manifest_digest"],
        claims=manifest["claims"], sources=manifest["sources"], relations=relations,
        reason="Caller inspected every saved input, including its qualifications.")


@pytest.mark.parametrize("expired_count", (1, 2))
@pytest.mark.parametrize("stage", ("before_schedule", "after_schedule", "after_inspection"))
async def test_cleanup_expiry_preserves_original_manifest_and_resolves_identity(authority, expired_count, stage):
    store, actor = authority.store, authority.actor
    _, left = await ready_claim(authority, "expiry-left")
    _, right = await ready_claim(authority, "expiry-right")
    expired_ids = [left.id, right.id][:expired_count]
    pending_id = None
    original = None
    manifest = None
    if stage != "before_schedule":
        scheduled = await store.schedule_cleanup()
        pending_id = scheduled["pending_ids"][0]
        async with store.pool.acquire() as connection:
            original = await connection.fetchval("SELECT claim_ids FROM am_pending_judgments WHERE id=$1", pending_id)
        if stage == "after_inspection":
            manifest = (await store.inspect(actor, authority.binding_id, pending_id))["judgment_manifest"]
    async with store.pool.acquire() as connection:
        await connection.execute("UPDATE am_claims SET valid_until=clock_timestamp()-interval '1 day' WHERE id=ANY($1::text[])", expired_ids)
    if stage == "before_schedule":
        scheduled = await store.schedule_cleanup()
        assert scheduled["created"] == (1 if expired_count == 1 else 0)
        if not scheduled["pending_ids"]:
            assert (await store.stats(actor, authority.binding_id))["pending"] == 0
            return
        pending_id = scheduled["pending_ids"][0]
        async with store.pool.acquire() as connection:
            original = await connection.fetchval("SELECT claim_ids FROM am_pending_judgments WHERE id=$1", pending_id)
        assert original == [right.id]
    if manifest is not None:
        with pytest.raises(DomainError) as stale:
            await store.record(actor, cleanup_command(authority, manifest, "expired-admission"))
        assert stale.value.code == "ADMISSION_STALE"
    inspected = await store.inspect(actor, authority.binding_id, pending_id)
    current = inspected["judgment_manifest"]
    assert {item["id"] for item in current["claims"]} == ({right.id} if expired_count == 1 else set())
    assert current["pending_id"] == pending_id
    if current["claims"]:
        async with store.pool.acquire() as connection:
            assert await connection.fetchval("SELECT pending_id FROM am_admissions WHERE id=$1", current["admission_id"]) == pending_id
        await store.record(actor, cleanup_command(authority, current, "eligible-survivors"))
    else:
        assert current["admission_id"] is None and current["judgment_required"] is False
        assert current["cleanup_disposition"] == "obsolete"
    async with store.pool.acquire() as connection:
        pending = await connection.fetchrow("SELECT * FROM am_pending_judgments WHERE id=$1", pending_id)
        assert pending["state"] == "resolved" and pending["resolved_at"] is not None
        assert pending["claim_ids"] == original
        if not current["claims"]:
            assert pending["reason"] == "Cleanup obsolete: no manifest claims remain eligible"
        await connection.execute("UPDATE am_pending_judgments SET created_at=clock_timestamp()-interval '2 days' WHERE id=$1", pending_id)
    assert (await store.schedule_cleanup())["created"] == 0
    assert (await store.stats(actor, authority.binding_id))["pending"] == 0


async def test_scheduler_terminalizes_all_expired_cleanup_without_inspection(authority):
    store = authority.store
    _, claim = await ready_claim(authority, "obsolete")
    scheduled = await store.schedule_cleanup()
    pending_id = scheduled["pending_ids"][0]
    async with store.pool.acquire() as connection:
        await connection.execute("UPDATE am_claims SET valid_until=clock_timestamp()-interval '1 day' WHERE id=$1", claim.id)
    assert (await store.schedule_cleanup())["created"] == 0
    async with store.pool.acquire() as connection:
        pending = await connection.fetchrow("SELECT * FROM am_pending_judgments WHERE id=$1", pending_id)
        assert pending["state"] == "resolved" and pending["claim_ids"] == [claim.id]
        assert pending["reason"] == "Cleanup obsolete: no manifest claims remain eligible"


async def test_twenty_one_claims_can_receive_a_cross_page_joint_judgment(authority):
    store, actor = authority.store, authority.actor
    claims = []
    for index in range(21):
        _, claim = await ready_claim(authority, f"cross-page-{index}")
        claims.append(claim)
    ids = [claim.id for claim in claims]
    first_id = (await store.schedule_cleanup())["pending_ids"][0]
    first_page = (await store.inspect(actor, authority.binding_id, first_id))["judgment_manifest"]
    assert {item["id"] for item in first_page["claims"]} == set(ids[:20])
    await store.record(actor, cleanup_command(authority, first_page, "first-cleanup-page"))
    async with store.pool.acquire() as connection:
        await connection.execute("UPDATE am_pending_judgments SET created_at=clock_timestamp()-interval '2 days' WHERE id=$1", first_id)
    second_id = (await store.schedule_cleanup())["pending_ids"][0]
    second_page = (await store.inspect(actor, authority.binding_id, second_id))["judgment_manifest"]
    assert {item["id"] for item in second_page["claims"]} == set(ids[20:])
    selected = tuple(sorted((ids[0], ids[20])))
    joint = await store.inspect(actor, authority.binding_id, "judgment", claim_ids=selected)
    assert [item["id"] for item in joint["claims"]] == list(selected)
    written = await store.record(actor, cleanup_command(authority, joint, "cross-page-joint",
        ({"left_id": selected[0], "right_id": selected[1], "relation": "supports",
            "reason": "Caller compared the claims across both cleanup pages."},)))
    assert joint["pending_id"] is None
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT state FROM am_pending_judgments WHERE id=$1", second_id) == "pending"
    second_page = (await store.inspect(actor, authority.binding_id, second_id))["judgment_manifest"]
    await store.record(actor, cleanup_command(authority, second_page, "second-cleanup-page"))
    saved = await store.inspect(actor, authority.binding_id, written.artifact_id)
    assert [item["id"] for item in saved["claims"]] == list(selected)
    relations = await store.relations(actor, authority.binding_id, selected)
    assert len(relations) == 1 and (relations[0].left_id, relations[0].right_id) == selected
    async with store.pool.acquire() as connection:
        await connection.execute("UPDATE am_claims SET revision=revision+1 WHERE id=$1", selected[1])
    assert await store.relations(actor, authority.binding_id, selected) == []


async def test_selected_judgment_cannot_hide_cross_binding_claims(authority):
    store, actor = authority.store, authority.actor
    _, own = await ready_claim(authority, "own")
    binding = await store.register_binding(actor, "Other project", None, "selected-other")
    actor = await store.authenticate(TOKEN)
    authority.actor = actor
    other = Authority(store, actor, binding.id, authority.revision)
    _, foreign = await ready_claim(other, "foreign")
    with pytest.raises(DomainError) as denied:
        await store.inspect(actor, authority.binding_id, "judgment", claim_ids=(own.id, foreign.id))
    assert denied.value.code == "CLAIM_INELIGIBLE"


@pytest.mark.parametrize("relation", ("duplicate", "supports", "supersedes"))
async def test_repeated_judgments_converge_edges_and_preserve_direction_and_audit(authority, relation):
    store, actor = authority.store, authority.actor
    _, left = await ready_claim(authority, "repeat-left")
    _, right = await ready_claim(authority, "repeat-right")
    for index in range(130):
        await store.record(actor, await relation_judgment(authority, left, right, relation, key=f"repeat-{index}"))
    manifest = await store.inspect(actor, authority.binding_id, "judgment")
    assert len(manifest["relations"]) == 1
    context = manifest["relations"][0]
    assert (context["left_id"], context["right_id"], context["relation"]) == (left.id, right.id, relation)
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT count(*) FROM am_claim_judgments") == 130
    await store.record(actor, await relation_judgment(authority, right, left, relation, key="reverse-direction"))
    relations = await store.relations(actor, authority.binding_id, (left.id, right.id))
    assert {(item.left_id, item.right_id) for item in relations} == {(left.id, right.id), (right.id, left.id)}
    _, admission = await store.search_lexical(actor, authority.binding_id, tokens("CacheKey"), None, request_digest="c" * 64)
    assert len(admission.relation_ids) == 2


async def test_cleanup_does_not_repend_an_unchanged_judged_manifest(authority):
    store, actor = authority.store, authority.actor
    _, claim = await ready_claim(authority, "unchanged")
    pending_id = (await store.schedule_cleanup())["pending_ids"][0]
    manifest = (await store.inspect(actor, authority.binding_id, pending_id))["judgment_manifest"]
    await store.record(actor, cleanup_command(authority, manifest, "unchanged-judgment"))
    async with store.pool.acquire() as connection:
        await connection.execute("UPDATE am_pending_judgments SET created_at=clock_timestamp()-interval '2 days' WHERE id=$1", pending_id)
    assert (await store.schedule_cleanup())["created"] == 0
    async with store.pool.acquire() as connection:
        await connection.execute("UPDATE am_claims SET revision=revision+1 WHERE id=$1", claim.id)
    assert (await store.schedule_cleanup())["created"] == 1


@pytest.mark.parametrize("debt", ("other_project", "legacy", "unjudgeable"))
async def test_new_project_capture_is_not_starved_by_unrelated_pending_debt(authority, debt):
    store, actor = authority.store, authority.actor
    store.settings = store.settings.model_copy(update={"queue_limit": 1})
    source = await store.capture(actor, command(authority, "debt"))
    async with store.pool.acquire() as connection:
        if debt == "legacy":
            await connection.execute("UPDATE am_pending_judgments SET kind='legacy_revalidation' WHERE $1=ANY(source_ids)", source.source_id)
        elif debt == "unjudgeable":
            await connection.execute("UPDATE am_sources SET speaker='memory' WHERE id=$1", source.source_id)
            await connection.execute("UPDATE am_pending_judgments SET state='held' WHERE $1=ANY(source_ids)", source.source_id)
    target = authority
    if debt == "other_project":
        binding = await store.register_binding(actor, "Fresh project", None, "fresh-project")
        actor = await store.authenticate(TOKEN)
        target = Authority(store, actor, binding.id, authority.revision)
    accepted = await store.capture(actor, command(target, "new-evidence"))
    assert accepted.state == "captured"
    with pytest.raises(DomainError) as full:
        await store.capture(actor, command(target, "same-project-overflow"))
    assert full.value.code == "QUEUE_FULL"


async def test_existing_relation_context_exposes_every_inspection_reference(authority):
    store, actor = authority.store, authority.actor
    claims = []
    for index in range(17):
        _, claim = await ready_claim(authority, f"context-claim-{index}")
        claims.append(claim)
    pairs = [(left.id, right.id) for index, left in enumerate(claims) for right in claims[index + 1:]][:129]
    for batch, start in enumerate(range(0, 128, 16)):
        manifest = await store.inspect(actor, authority.binding_id, "judgment")
        await store.record(actor, cleanup_command(authority, manifest, f"relation-context-{batch}",
            tuple({"left_id": left, "right_id": right, "relation": "supports",
                "reason": "Caller compared this ordered pair with all original evidence."}
                for left, right in pairs[start:start + 16])))
    current = await store.inspect(actor, authority.binding_id, "judgment")
    assert len(current["relation_ids"]) == 128 and len(current["relations"]) == 8
    assert current["relation_context_partial"] is True and current["inspect_relations_before_judgment"] is True
    inspected = [await store.inspect(actor, authority.binding_id, ref) for ref in current["relation_ids"]]
    assert {(item["left_id"], item["right_id"]) for item in inspected} == set(pairs[:128])
    _, recall = await store.search_lexical(actor, authority.binding_id, tokens("CacheKey"), None, request_digest="a" * 64)
    assert set(recall.relation_ids) == set(current["relation_ids"])
    left, right = pairs[-1]
    await store.record(actor, cleanup_command(authority, current, "relation-context-overflow", (
        {"left_id": left, "right_id": right, "relation": "supports",
         "reason": "Caller compared the additional pair with its original evidence."},
    )))
    with pytest.raises(DomainError) as overflow:
        await store.inspect(actor, authority.binding_id, "judgment")
    assert overflow.value.code == "RELATION_CONTEXT_OVERFLOW"


async def test_cleanup_and_legacy_debt_do_not_consume_new_capture_capacity(authority):
    store, actor = authority.store, authority.actor
    source, claim = await ready_claim(authority, "queue-claim")
    store.settings = store.settings.model_copy(update={"queue_limit": 1})
    async with store.pool.acquire() as connection:
        await connection.execute("""INSERT INTO am_pending_judgments(id,binding_id,kind,source_ids,claim_ids)
            VALUES('pending_legacy_debt',$1,'legacy_revalidation',$2,$3)""", authority.binding_id, [source.source_id], [claim.id])
    scheduled = await store.schedule_cleanup()
    assert scheduled["created"] == 1
    captured = await store.capture(actor, command(authority, "capture-with-cleanup"))
    assert captured.state == "captured"

async def test_accepted_judgment_context_excludes_expired_and_future_claims(authority):
    store, actor = authority.store, authority.actor
    _, current = await ready_claim(authority, "current-judgment-input")
    _, expired = await ready_claim(authority, "expired-judgment-input")
    _, future = await ready_claim(authority, "future-judgment-input")
    async with store.pool.acquire() as connection:
        await connection.execute(
            "UPDATE am_claims SET valid_until=clock_timestamp()-interval '1 day' WHERE id=$1", expired.id,
        )
        await connection.execute(
            "UPDATE am_claims SET valid_from=clock_timestamp()+interval '1 day' WHERE id=$1", future.id,
        )
    source_view = await store.inspect(actor, authority.binding_id, current.input_source_ids[0])
    assert {item["id"] for item in source_view["judgment_context"]["accepted_memories"]} == {current.id}


async def test_actual_agent_note_does_not_consume_human_capture_capacity(authority):
    store, actor = authority.store, authority.actor
    store.settings = store.settings.model_copy(update={"queue_limit": 1})
    await store.record(actor, RecordCommand(
        binding_id=authority.binding_id, idempotency_key="agent-note-backlog", kind="note",
        body="An unverified note is not independent evidence.",
    ))
    captured = await store.capture(actor, command(authority, "human-after-agent-note"))
    assert captured.state == "captured"
    with pytest.raises(DomainError) as full:
        await store.capture(actor, command(authority, "human-backlog-overflow"))
    assert full.value.code == "QUEUE_FULL"
