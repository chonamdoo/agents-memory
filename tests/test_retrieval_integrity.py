"""Metamorphic integrity gate for candidate retrieval (proposal §4 layer A, I1-I5).

Each case first proves the target claim is in the candidate pool for its query, applies one
transformation whose expected outcome is known without human labels, then requires the
target to be absent from both the store candidate pool and the MCP context manifest while an
untouched neighbor stays. The pool holds far fewer claims than its bound of twenty, so the
absence cannot come from ranking; it can only come from the eligibility filter, which a
ranking loop must not edit.
"""
from __future__ import annotations

import hashlib
import itertools

import pytest
from test_company_authority import TOKEN, archive_rows, candidate, judged_context, restore_rows
from test_company_authority import company as company
from test_health_backend import enabled, linked_claim, review

from agents_memory.domain import CaptureCommand, CaptureCoverage, ContextCommand, DomainError
from agents_memory.lexical import tokens
from agents_memory.selection import ClaimJudgmentCommand

QUERY = "PaymentRetryPolicy 결제 재시도 정책"
TARGET = "PaymentRetryPolicy 결제 재시도 정책은 최대 3회다."
NEIGHBOR = "PaymentRetryPolicy 결제 화면 문서는 별도로 관리한다."
_digests = itertools.count()


async def candidate_ids(company, query=QUERY, *, snapshot=None, workspace=None) -> list[str]:
    rows, _ = await company.store.search_lexical(company.actor, company.binding_id, tokens(query), snapshot,
        request_digest=hashlib.sha256(f"integrity-{next(_digests)}".encode()).hexdigest(),
        code_workspace_id=workspace)
    store_ids = [claim.id for claim, _ in rows]
    pending = await company.application.context(company.actor, ContextCommand(
        binding_id=company.binding_id, query=query, snapshot=snapshot, code_workspace_id=workspace))
    assert [item["claim_id"] for item in pending["candidate_manifest"]] == store_ids
    return store_ids


async def target_and_neighbor(company, key, *, snapshot=None):
    source, _, target = await candidate(company, key, snapshot=snapshot, body=TARGET)
    _, _, neighbor = await candidate(company, key + "-neighbor", snapshot=snapshot, body=NEIGHBOR)
    ids = await candidate_ids(company, snapshot=snapshot)
    assert {target.id, neighbor.id} <= set(ids)
    return source, target, neighbor


async def assert_excluded(company, target, neighbor, **scope):
    ids = await candidate_ids(company, **scope)
    assert target.id not in ids
    assert neighbor.id in ids


async def test_i1_retracted_source_never_resurfaces(company):
    source, target, neighbor = await target_and_neighbor(company, "i1-source")
    await company.store.retract(company.actor, company.binding_id, source.source_id, "i1-retract-source")
    await assert_excluded(company, target, neighbor)


async def test_i1_withdrawn_claim_never_resurfaces_while_its_source_stays(company):
    source, target, neighbor = await target_and_neighbor(company, "i1-claim")
    await company.store.retract(company.actor, company.binding_id, target.id, "i1-withdraw-claim")
    assert (await company.store.source(company.actor, company.binding_id, source.source_id)).state == "active"
    await assert_excluded(company, target, neighbor)


async def test_i1_purged_claim_never_resurfaces(company):
    _, target, neighbor = await target_and_neighbor(company, "i1-purge")
    await company.store.retract(company.actor, company.binding_id, target.id, "i1-purge-withdraw")
    await company.store.purge(company.actor, company.binding_id, target.id, "i1-purge")
    await assert_excluded(company, target, neighbor)


async def test_i1_restoring_a_pre_retraction_backup_does_not_resurrect_the_claim(company):
    await enabled(company)
    _, target, neighbor = await target_and_neighbor(company, "i1-restore")
    archived = await archive_rows(company.store)
    await company.store.retract(company.actor, company.binding_id, target.id, "i1-restore-withdraw")
    head = company.store.journal.verify()["head"]
    await restore_rows(company.store, archived)
    company.actor = await company.store.recover_after_restore(company.actor.id, "fresh-integrity-" + "t" * 48, head)
    # Restore withholds every restored claim until an operator re-accepts it, so the neighbor is
    # re-accepted first; the retracted target must stay out even then.
    assert await candidate_ids(company) == []
    neighbor = await company.store.claim(company.actor, company.binding_id, neighbor.id)
    await review(company, neighbor, "i1-restore-accept", "accept")
    await assert_excluded(company, target, neighbor)


async def test_i2_superseded_claim_is_never_offered_without_its_supersedes_edge(company):
    _, old, neighbor = await target_and_neighbor(company, "i2-old")
    _, _, new = await candidate(company, "i2-new", body="PaymentRetryPolicy 결제 재시도 정책은 최대 5회로 바뀌었다.")
    view = await company.store.inspect(company.actor, company.binding_id, "judgment", claim_ids=(new.id, old.id))
    for item in view["claims"]:
        await company.store.inspect(company.actor, company.binding_id, item["id"])
    await company.store.record(company.actor, ClaimJudgmentCommand(
        kind="claim_judgment", binding_id=company.binding_id, idempotency_key="i2-supersedes",
        admission_id=view["admission_id"], manifest_digest=view["manifest_digest"], claims=view["claims"],
        sources=view["sources"], relations=[{"left_id": new.id, "right_id": old.id, "relation": "supersedes",
            "reason": "The newer original changes the retry limit for the same policy."}],
        reason="Both originals were inspected together."))
    # Supersedes links evidence and is not a deletion (architecture A06), so the old claim may stay a
    # candidate; the gate is that it is never delivered stripped of the edge that marks it superseded.
    edges = await company.store.relations(company.actor, company.binding_id, (old.id,))
    supersedes = [edge for edge in edges if edge.kind == "supersedes"]
    assert [(edge.left_id, edge.right_id) for edge in supersedes] == [(new.id, old.id)]
    rows, admission = await company.store.search_lexical(company.actor, company.binding_id, tokens(QUERY), None,
        request_digest=hashlib.sha256(b"i2-admission").hexdigest())
    assert old.id in {claim.id for claim, _ in rows}
    assert supersedes[0].id in admission.relation_ids
    delivered = await judged_context(company, company.actor, ContextCommand(binding_id=company.binding_id, query=QUERY))
    assert old.id in delivered["refs"] and supersedes[0].id in delivered["context"]
    assert neighbor.id in await candidate_ids(company)


async def test_i3_corrected_source_revision_drops_the_claim_from_its_old_revision(company):
    source, target, neighbor = await target_and_neighbor(company, "i3-correct")
    replacement = "PaymentRetryPolicy 문서는 폐기됐다."
    await company.store.correct(company.actor, company.binding_id, source.source_id, CaptureCommand(
        binding_id=company.binding_id, idempotency_key="i3-correct", origin_key="i3-replacement",
        body=replacement, speaker="human",
        coverage=CaptureCoverage(status="observed_window", original_bytes=len(replacement.encode()))))
    await assert_excluded(company, target, neighbor)


async def test_i3_source_revision_drift_without_api_is_still_excluded(company):
    source, target, neighbor = await target_and_neighbor(company, "i3-drift")
    async with company.store.pool.acquire() as connection:
        await connection.execute("UPDATE am_sources SET revision=revision+1 WHERE id=$1", source.source_id)
    await assert_excluded(company, target, neighbor)


async def test_i4_identical_claim_in_another_binding_never_crosses(company):
    other = await company.store.register_binding(company.actor, "Other synthetic project", "/synthetic/other", "i4-other")
    company.actor = await company.store.authenticate(TOKEN)
    home = company.binding_id
    company.binding_id = other.id
    _, _, foreign = await candidate(company, "i4-foreign", body=TARGET)
    assert await candidate_ids(company) == [foreign.id]
    company.binding_id = home
    _, _, neighbor = await candidate(company, "i4-neighbor", body=NEIGHBOR)
    ids = await candidate_ids(company)
    assert foreign.id not in ids and neighbor.id in ids


async def test_i4_selection_from_another_realm_never_crosses(company):
    _, target, neighbor = await target_and_neighbor(company, "i4-realm")
    async with company.store.pool.acquire() as connection:
        await connection.execute("""UPDATE am_source_selections SET realm='other_realm'
            WHERE id=(SELECT selection_id FROM am_claims WHERE id=$1)""", target.id)
    await assert_excluded(company, target, neighbor)


async def test_i5_expired_validity_is_excluded(company):
    _, target, neighbor = await target_and_neighbor(company, "i5-expired")
    async with company.store.pool.acquire() as connection:
        await connection.execute("UPDATE am_claims SET valid_until=clock_timestamp()-interval '1 hour' WHERE id=$1", target.id)
    await assert_excluded(company, target, neighbor)


async def test_i5_other_snapshot_is_excluded(company):
    _, _, scoped = await candidate(company, "i5-snapshot", snapshot="snapshot-A", body=TARGET)
    _, _, neighbor = await candidate(company, "i5-snapshot-neighbor", body=NEIGHBOR)
    assert scoped.id in await candidate_ids(company, snapshot="snapshot-A")
    for snapshot in ("snapshot-B", None):
        ids = await candidate_ids(company, snapshot=snapshot)
        assert scoped.id not in ids and neighbor.id in ids


async def test_i5_operator_rejected_health_is_excluded(company):
    await enabled(company)
    _, target, neighbor = await target_and_neighbor(company, "i5-health")
    await review(company, target, "i5-reject", "reject")
    await assert_excluded(company, target, neighbor)


async def test_i5_code_linked_claim_stays_in_its_workspace(company):
    _, claim, _, _ = await linked_claim(company)
    _, _, neighbor = await candidate(company, "i5-workspace-neighbor", body="CacheKey 문서는 별도로 관리한다.")
    assert claim.id in await candidate_ids(company, "CacheKey offline", workspace="workspace_test")
    ids = await candidate_ids(company, "CacheKey offline")
    assert claim.id not in ids and neighbor.id in ids
    # An unregistered workspace fails closed instead of widening to the global pool.
    with pytest.raises(DomainError) as unregistered:
        await candidate_ids(company, "CacheKey offline", workspace="workspace_other")
    assert unregistered.value.code == "HEALTH_WORKSPACE_SCOPE"


@pytest.mark.parametrize("snapshot", (None, "snapshot-A"))
async def test_ineligible_exact_matches_never_displace_eligible_candidates(company, snapshot):
    """Pool pressure: twenty-one ineligible exact matches plus one eligible neighbor."""
    hidden = []
    for index in range(21):
        source, _, claim = await candidate(company, f"pool-{index}", snapshot=snapshot, body=f"PaymentRetryPolicy 결제 재시도 정책 변형 {index}번은 최대 3회다.")
        await company.store.retract(company.actor, company.binding_id, source.source_id, f"pool-retract-{index}")
        hidden.append(claim.id)
    _, _, neighbor = await candidate(company, "pool-neighbor", snapshot=snapshot, body=NEIGHBOR)
    ids = await candidate_ids(company, snapshot=snapshot)
    assert ids == [neighbor.id] and not set(hidden) & set(ids)
