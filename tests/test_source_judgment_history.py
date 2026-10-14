from __future__ import annotations

import pytest
from test_company_authority import capture
from test_company_authority import company as company

from agents_memory.domain import DomainError
from agents_memory.selection import SourceSelectionCommand
from agents_memory.semantic_contract import GeneratedExtraction


async def inspected_selection(company, source_id, key, *, label="remember", snapshot=None,
    start=0, max_bytes=4096, cursor=None, publish=True, review_ids=(), decision="unrelated"):
    window = await company.store.inspect(company.actor, company.binding_id, source_id, snapshot,
        byte_start=start, max_bytes=max_bytes, rejection_cursor=cursor)
    extraction = None
    if label == "remember" and publish:
        span = window["span_inventory"][0]
        extraction = GeneratedExtraction(claims=({"assertion_id": "a0001", "assertion_span_id": span["span_id"],
            "statement": span["quote"], "kind": "fact", "subject": span["quote"].split()[0],
            "predicate": "retained", "object": "offline", "polarity": "positive", "modality": "asserted",
            "entities": (span["quote"].split()[0],)},), individual_qualifications=(), shared_qualifications=(),
            validities=(), unused_span_ids=tuple(item["span_id"] for item in window["span_inventory"][1:]))
    rejected = window["judgment_context"]["rejections"]
    request = SourceSelectionCommand(kind="source_selection", binding_id=company.binding_id,
        idempotency_key=key, admission_id=window["admission_id"], source_id=source_id,
        source_revision=window["source_revision"], binding_revision=window["binding_revision"],
        snapshot=window["snapshot"], byte_start=window["byte_start"], byte_end=window["byte_end"],
        window_digest=window["window_digest"], policy_revision=window["policy_revision"],
        policy_epoch=window["policy_epoch"], label=label, coverage="complete_window", extraction=extraction,
        reason="Caller inspected the original bounded evidence and every displayed rejection.",
        rejection_comparisons=tuple({"rejection_id": item["id"], "decision": decision,
            "reason": "The independently captured original does not restate this rejection."} for item in rejected)
            if label != "discard" else (),
        prior_rejection_ids=tuple(item["id"] for item in rejected) if decision == "reopen" else (),
        rejection_review_ids=review_ids)
    return request, window


async def record_selection(company, request):
    operation = await company.store.record(company.actor, request)
    receipt = await company.store.inspect(company.actor, company.binding_id, operation.id)
    return receipt["artifact_id"]


async def rejection_history(company, count=10):
    ids = []
    for index in range(count):
        captured = await capture(company, key=f"history-{index}", body=f"OldKey{index} is retained offline.")
        request, _ = await inspected_selection(company, captured.source_id, f"discard-{index}", label="discard")
        ids.append(await record_selection(company, request))
    return ids


async def reviewed_history(company, source_id, *, snapshot=None, decision="unrelated"):
    cursor, ids, seen = "history", [], []
    while True:
        request, window = await inspected_selection(company, source_id, f"review-{len(ids)}",
            label="review", snapshot=snapshot, cursor=cursor, decision=decision)
        request = request.model_copy(update={"idempotency_key": f"review-{window['admission_id']}"})
        seen.extend(item["id"] for item in window["judgment_context"]["rejections"])
        ids.append(await record_selection(company, request))
        cursor = window["judgment_context"]["rejections_next_cursor"]
        if cursor is None:
            return tuple(ids), seen


async def test_same_source_discard_blocks_only_overlapping_current_window(company):
    first = "OldKey is retained offline. "
    captured = await capture(company, body=first + "CacheKey is retained offline.")
    discarded, _ = await inspected_selection(company, captured.source_id, "discard-prefix", label="discard",
        max_bytes=len(first.encode()))
    await record_selection(company, discarded)
    remember, _ = await inspected_selection(company, captured.source_id, "remember-suffix", start=len(first.encode()))
    assert (await company.store.record(company.actor, remember)).state == "candidate_ready"
    overlap, _ = await inspected_selection(company, captured.source_id, "remember-overlap", max_bytes=len(first.encode()))
    with pytest.raises(DomainError) as blocked:
        await company.store.record(company.actor, overlap)
    assert blocked.value.code == "EVIDENCE_REJECTED"


@pytest.mark.parametrize("change", ("selection_state", "source_revision", "source_state"))
async def test_obsolete_discard_does_not_reject_current_independent_evidence(company, change):
    captured = await capture(company, key="old-discard")
    discarded, _ = await inspected_selection(company, captured.source_id, "old-selection", label="discard")
    selection_id = await record_selection(company, discarded)
    async with company.store.pool.acquire() as connection:
        if change == "selection_state":
            await connection.execute("UPDATE am_source_selections SET state='retracted' WHERE id=$1", selection_id)
        elif change == "source_revision":
            await connection.execute("UPDATE am_sources SET revision=revision+1 WHERE id=$1", captured.source_id)
        else:
            await connection.execute("UPDATE am_sources SET state='retracted' WHERE id=$1", captured.source_id)
    independent = await capture(company, key="new-origin")
    request, window = await inspected_selection(company, independent.source_id, "current-selection")
    assert window["judgment_context"]["rejections"] == []
    assert (await company.store.record(company.actor, request)).state == "candidate_ready"


async def test_active_cross_source_body_copy_cannot_reopen_rejected_evidence(company):
    captured = await capture(company, key="discard-original")
    discarded, _ = await inspected_selection(company, captured.source_id, "discard-selection", label="discard")
    await record_selection(company, discarded)
    copied = await capture(company, key="copy-origin")
    request, _ = await inspected_selection(company, copied.source_id, "copy-selection", decision="reopen")
    with pytest.raises(DomainError) as blocked:
        await company.store.record(company.actor, request)
    assert blocked.value.code == "EVIDENCE_REJECTED"


async def test_scoped_request_preserves_unscoped_original_snapshot(company):
    captured = await capture(company, key="unscoped-original")
    request, window = await inspected_selection(company, captured.source_id, "scoped-selection", snapshot="request-scope")
    assert window["snapshot"] == "request-scope" and window["source_snapshot"] is None
    selection_id = await record_selection(company, request)
    async with company.store.pool.acquire() as connection:
        selection = await connection.fetchrow("SELECT snapshot,request_snapshot FROM am_source_selections WHERE id=$1", selection_id)
        assert selection["snapshot"] is None and selection["request_snapshot"] == "request-scope"
        assert await connection.fetchval("SELECT snapshot IS NULL FROM am_claims WHERE selection_id=$1", selection_id)


async def test_complete_paged_rejection_review_can_publish_independent_evidence(company):
    expected = await rejection_history(company)
    independent = await capture(company, key="new-evidence", body="CacheKey is retained offline.")
    reviews, seen = await reviewed_history(company, independent.source_id)
    assert len(reviews) == 2 and len(seen) == len(set(seen)) == 10 and set(seen) == set(expected)
    request, _ = await inspected_selection(company, independent.source_id, "complete-publication", review_ids=reviews)
    assert (await company.store.record(company.actor, request)).state == "candidate_ready"


@pytest.mark.parametrize("change", ("reason", "retracted", "source_revision"))
async def test_changed_history_invalidates_previously_completed_review(company, change):
    expected = await rejection_history(company)
    independent = await capture(company, key="new-evidence", body="CacheKey is retained offline.")
    reviews, _ = await reviewed_history(company, independent.source_id)
    request, _ = await inspected_selection(company, independent.source_id, "changed-publication", review_ids=reviews)
    async with company.store.pool.acquire() as connection:
        if change == "reason":
            await connection.execute("UPDATE am_source_selections SET reason='Changed original rejection reason.' WHERE id=$1", expected[-1])
        elif change == "retracted":
            await connection.execute("UPDATE am_source_selections SET state='retracted' WHERE id=$1", expected[-1])
        elif change == "source_revision":
            await connection.execute("UPDATE am_sources SET revision=revision+1 WHERE id=(SELECT source_id FROM am_source_selections WHERE id=$1)", expected[-1])
    with pytest.raises(DomainError) as blocked:
        await company.store.record(company.actor, request)
    assert blocked.value.code in {"ADMISSION_STALE", "REJECTION_REVIEW_STALE", "REJECTION_COMPARISON_REQUIRED"}


async def test_review_receipts_can_chain_bounded_page_comparisons(company):
    await rejection_history(company)
    independent = await capture(company, key="new-evidence")
    first, window = await inspected_selection(company, independent.source_id, "review-first", label="review", cursor="history")
    first_id = await record_selection(company, first)
    second, _ = await inspected_selection(company, independent.source_id, "review-second", label="review",
        cursor=window["judgment_context"]["rejections_next_cursor"], review_ids=(first_id,))
    second_id = await record_selection(company, second)
    request, _ = await inspected_selection(company, independent.source_id, "chained-publication", review_ids=(second_id,))
    assert (await company.store.record(company.actor, request)).state == "candidate_ready"


@pytest.mark.parametrize("change", ("credential", "binding", "deletion", "source", "realm", "policy", "window"))
async def test_saved_review_receipts_revalidate_final_authority_and_window(company, change):
    from test_company_authority import TOKEN

    await rejection_history(company, 1)
    independent = await capture(company, key="new-evidence")
    reviews, _ = await reviewed_history(company, independent.source_id)
    async with company.store.pool.acquire() as connection:
        if change == "credential":
            await connection.execute("UPDATE am_credentials SET generation=generation+1 WHERE id=$1", company.actor.credential_id)
        elif change == "binding":
            await connection.execute("UPDATE am_bindings SET revision=revision+1 WHERE id=$1", company.binding_id)
        elif change == "deletion":
            await connection.execute("UPDATE am_clock SET deletion_generation=deletion_generation+1")
        elif change == "source":
            await connection.execute("UPDATE am_sources SET revision=revision+1 WHERE id=$1", independent.source_id)
        elif change == "realm":
            await connection.execute("UPDATE am_source_selections SET realm='different_realm' WHERE id=$1", reviews[0])
        elif change == "policy":
            await connection.execute("UPDATE am_source_selections SET policy_revision=$2 WHERE id=$1", reviews[0], "0" * 64)
    if change == "credential":
        company.actor = await company.store.authenticate(TOKEN)
    request, _ = await inspected_selection(company, independent.source_id, "stale-review-publication", review_ids=reviews,
        max_bytes=5 if change == "window" else 4096, publish=change != "window")
    with pytest.raises(DomainError) as stale:
        await company.store.record(company.actor, request)
    assert stale.value.code == "REJECTION_REVIEW_STALE"


async def test_review_receipt_cannot_cross_request_snapshot(company):
    await rejection_history(company, 1)
    independent = await capture(company, key="new-evidence")
    reviews, _ = await reviewed_history(company, independent.source_id, snapshot="first-scope")
    request, _ = await inspected_selection(company, independent.source_id, "cross-scope-review",
        snapshot="other-scope", review_ids=reviews)
    with pytest.raises(DomainError) as stale:
        await company.store.record(company.actor, request)
    assert stale.value.code == "REJECTION_REVIEW_STALE"


async def test_feedback_and_discard_history_share_complete_bounded_pages(company):
    from agents_memory.domain import FeedbackCommand

    expected = await rejection_history(company, 5)
    for index in range(5):
        original = await capture(company, key=f"feedback-original-{index}", body=f"FeedbackKey{index} is retained offline.")
        operation = await company.store.feedback(company.actor, FeedbackCommand(binding_id=company.binding_id,
            idempotency_key=f"reject-feedback-{index}", target_ref=original.source_id, kind="reject",
            body="Do not remember this rejected original evidence."))
        inspected = await company.store.inspect(company.actor, company.binding_id, operation.id)
        expected.append(inspected["artifact_id"])
    independent = await capture(company, key="mixed-independent")
    reviews, seen = await reviewed_history(company, independent.source_id)
    assert len(reviews) == 2 and set(seen) == set(expected)
    request, _ = await inspected_selection(company, independent.source_id, "mixed-publication", review_ids=reviews)
    assert (await company.store.record(company.actor, request)).state == "candidate_ready"


async def test_reopened_history_can_use_reviewed_pages_without_unbounded_final_ids(company):
    await rejection_history(company)
    independent = await capture(company, key="independent-reopening")
    reviews, seen = await reviewed_history(company, independent.source_id, decision="reopen")
    assert len(seen) == 10
    request, _ = await inspected_selection(company, independent.source_id, "reopened-publication", review_ids=reviews)
    request = request.model_copy(update={"rejection_comparisons": (), "prior_rejection_ids": ()})
    assert (await company.store.record(company.actor, request)).state == "candidate_ready"


async def test_new_unrelated_history_does_not_invalidate_optional_reviews(company):
    old = await capture(company, key="isolated-old", body="Quartzamber.")
    discard, _ = await inspected_selection(
        company, old.source_id, "isolated-old-discard", label="discard",
    )
    await record_selection(company, discard)
    independent = await capture(
        company, key="isolated-new", body="CacheKey is retained offline.",
    )
    reviews, _ = await reviewed_history(company, independent.source_id)
    request, _ = await inspected_selection(
        company, independent.source_id, "isolated-publication", review_ids=reviews,
    )
    newer = await capture(company, key="isolated-later", body="Violetzephyr.")
    newer_discard, _ = await inspected_selection(
        company, newer.source_id, "isolated-later-discard", label="discard",
    )
    await record_selection(company, newer_discard)
    result = await company.store.record(company.actor, request)
    saved = await company.store.inspect(company.actor, company.binding_id, result.artifact_id)
    assert saved["reason"] == request.reason
    claim_id, = saved["claim_ids"]
    claim = await company.store.claim(company.actor, company.binding_id, claim_id)
    assert claim.input_source_ids == (independent.source_id,)
