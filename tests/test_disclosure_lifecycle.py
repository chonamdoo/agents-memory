from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from test_company_authority import archive_rows, restore_rows
from test_source_judgment_history import inspected_selection, reviewed_history
from test_store_authority import authority as authority
from test_store_authority import command, ready_claim, recall_context, source_selection

from agents_memory.application import Application
from agents_memory.domain import ContextCommand, DomainError, FeedbackCommand, RuleProposal
from agents_memory.migrations import MIGRATIONS


def decoded(value):
    return json.loads(value) if isinstance(value, str) else value


def historical_claims(archive):
    for claim in archive["am_claims"]:
        if claim["capability"] == "agent_judged":
            claim["capability"] = "lexical_entity"


@pytest.mark.parametrize("withdraw_all", (False, True))
async def test_migrated_multisource_successor_keeps_survivor_reachable_and_original_audit(authority, withdraw_all):
    store, actor = authority.store, authority.actor
    first, legacy_claim = await ready_claim(authority, "legacy-first")
    survivor = await store.capture(actor, command(authority, "legacy-survivor", "CacheKey is retained after manual review."))
    archive = await archive_rows(store)
    legacy = next(row for row in archive["am_claims"] if row["id"] == legacy_claim.id)
    legacy.update(capability="full_semantic", interpretation_role="model_derived_candidate",
        route_revision="f" * 64, selection_id=None, policy_revision=None, extraction_operation_id=first.id)
    timestamp = datetime(2026, 10, 1, tzinfo=UTC)
    original_job = {"id": "job_multisource_legacy", "binding_id": authority.binding_id, "operation_id": first.id,
        "credential_id": actor.credential_id, "credential_generation": actor.generation, "kind": "consolidate",
        "source_ids": [first.source_id, survivor.source_id], "claim_ids": [legacy_claim.id], "query_source_id": None,
        "snapshot": None, "state": "failed", "generation": 4, "attempts": 3, "lease_token": None, "deadline": None,
        "available_at": timestamp, "error_code": "LEGACY_PROVIDER_UNAVAILABLE", "created_at": timestamp}
    archive["am_jobs"] = [original_job]
    next(row for row in archive["am_operations"] if row["id"] == first.id).update(
        state="failed", error_code=original_job["error_code"], created_at=timestamp)
    await restore_rows(store, archive, MIGRATIONS[4])
    await store.reconcile_journal()
    async with store.pool.acquire() as connection:
        retired = dict(await connection.fetchrow("SELECT * FROM am_jobs WHERE id=$1", original_job["id"]))
        audit = dict(await connection.fetchrow("SELECT * FROM am_retired_jobs WHERE job_id=$1", original_job["id"]))
    assert decoded(audit["original"])["source_ids"] == original_job["source_ids"]
    assert decoded(audit["original"])["attempts"] == 3
    assert decoded(audit["original_operation"])["error_code"] == original_job["error_code"]

    await store.retract(actor, authority.binding_id, first.source_id, "withdraw-first-legacy-input")
    if withdraw_all:
        await store.retract(actor, authority.binding_id, survivor.source_id, "withdraw-last-legacy-input")
    pending = await store.inspect(actor, authority.binding_id, "pending")
    stats = await store.stats(actor, authority.binding_id)
    current = await store.inspect(actor, authority.binding_id, audit["successor_id"])
    application = Application(store.settings, store)
    before = await application.context(actor, ContextCommand(binding_id=authority.binding_id, query="CacheKey"))
    assert before["candidate_manifest"] == []
    assert stats["recovery_jobs"][0]["unresolved"] is not withdraw_all
    if withdraw_all:
        assert pending["items"] == [] and current["state"] == "retracted"
        assert stats["pending"] == stats["failed"] == stats["dlq"] == 0
    else:
        assert current["state"] == "pending" and current["source_ids"] == [survivor.source_id]
        assert [item["id"] for item in pending["items"]] == [audit["successor_id"]]
        assert stats["pending"] == stats["failed"] == stats["dlq"] == 1
        inspected = await store.inspect(actor, authority.binding_id, current["source_ids"][0])
        assert inspected["body"] == "CacheKey is retained after manual review."
        await store.record(actor, await source_selection(authority, survivor.source_id, "judge-surviving-evidence"))
        assert (await store.inspect(actor, authority.binding_id, audit["successor_id"]))["state"] == "resolved"
        after = await recall_context(authority)
        assert "CacheKey is retained after manual review." in after["context"]
        assert legacy_claim.id not in json.dumps(after)
        resolved = await store.stats(actor, authority.binding_id)
        assert resolved["pending"] == resolved["failed"] == resolved["dlq"] == 0
    async with store.pool.acquire() as connection:
        assert dict(await connection.fetchrow("SELECT * FROM am_jobs WHERE id=$1", original_job["id"])) == retired
        assert dict(await connection.fetchrow("SELECT * FROM am_retired_jobs WHERE job_id=$1", original_job["id"])) == audit


@pytest.mark.parametrize("change", ("withdraw", "correct", "selection"))
async def test_selection_withholds_withdrawn_reason_on_next_read_and_restore(authority, change):
    store, actor = authority.store, authority.actor
    source = await store.capture(actor, command(authority, "selection-original"))
    request = (await source_selection(authority, source.source_id, "private-selection")).model_copy(
        update={"reason": "Private judgment explains the original offline restriction."})
    selected = await store.record(actor, request)
    before = await store.inspect(actor, authority.binding_id, selected.artifact_id)
    assert before["reason"] == request.reason
    archive = await archive_rows(store)
    if change == "withdraw":
        await store.retract(actor, authority.binding_id, source.source_id, "selection-withdraw")
    elif change == "correct":
        replacement = await store.correct(actor, authority.binding_id, source.source_id,
            command(authority, "selection-correction", "CacheKey is retained after manual review."))
        assert replacement.source_id != source.source_id
    else:
        await store.retract(actor, authority.binding_id, selected.artifact_id, "selection-only-withdraw")
        assert (await store.source(actor, authority.binding_id, source.source_id)).body == command(authority).body
    retained_head = store.journal.verify()["head"]
    withdrawn = await store.inspect(actor, authority.binding_id, selected.artifact_id)
    assert withdrawn["state"] == "retracted"
    assert withdrawn.get("reason") is None and not withdrawn.get("rejection_comparisons")
    assert request.reason not in json.dumps(withdrawn)
    await restore_rows(store, archive)
    with pytest.raises(DomainError) as barrier:
        await store.inspect(actor, authority.binding_id, selected.artifact_id)
    assert barrier.value.code == "DELETION_BARRIER"
    await store.reconcile_journal(retained_head)
    restored = await store.inspect(actor, authority.binding_id, selected.artifact_id)
    assert restored["state"] == "retracted"
    assert restored.get("reason") is None and not restored.get("rejection_comparisons")
    assert request.reason not in json.dumps(restored)


@pytest.mark.parametrize("reviewed", (False, True))
@pytest.mark.parametrize("rejection_kind", ("selection", "feedback"))
async def test_selection_comparisons_follow_saved_rejection_inputs_without_erasing_independent_evidence(authority, reviewed, rejection_kind):
    store, actor = authority.store, authority.actor
    rejected = await store.capture(actor, command(authority, "rejected-original", "OldKey is retained offline."))
    if rejection_kind == "selection":
        rejection = await store.record(actor, await source_selection(authority, rejected.source_id, "discard-original", label="discard"))
    else:
        rejection = await store.feedback(actor, FeedbackCommand(binding_id=authority.binding_id,
            idempotency_key="reject-original", target_ref=rejected.source_id, kind="reject", body="The old offline interpretation is not applicable."))
    independent = await store.capture(actor, command(authority, "independent-original", "CacheKey is retained after review."))
    review_ids = ()
    if reviewed:
        review_ids, seen = await reviewed_history(authority, independent.source_id)
        assert seen == [rejection.artifact_id]
    request, _ = await inspected_selection(authority, independent.source_id, "compared-selection", review_ids=review_ids)
    if reviewed:
        request = request.model_copy(update={"rejection_comparisons": ()})
    selected = await store.record(actor, request)
    assert (await store.inspect(actor, authority.binding_id, selected.artifact_id))["reason"] == request.reason
    archive = await archive_rows(store)
    await store.retract(actor, authority.binding_id, rejected.source_id, "withdraw-comparison-input")
    await store.purge(actor, authority.binding_id, rejected.source_id, "purge-comparison-input")
    retained_head = store.journal.verify()["head"]
    for restored in (False, True):
        if restored:
            await restore_rows(store, archive)
            await store.reconcile_journal(retained_head)
        result = await store.inspect(actor, authority.binding_id, selected.artifact_id)
        assert result["state"] == "active"
        assert result.get("reason") is None and not result.get("rejection_comparisons")
        assert request.reason not in json.dumps(result)
        assert (await store.source(actor, authority.binding_id, independent.source_id)).body == "CacheKey is retained after review."
        assert "CacheKey is retained after review." in (await recall_context(authority))["context"]


async def test_selection_snapshot_privacy_withholds_body_without_losing_metadata(authority):
    store, actor = authority.store, authority.actor
    source = await store.capture(actor, command(authority, "snapshot-original", snapshot="private-snapshot"))
    selected = await store.record(actor, await source_selection(authority, source.source_id, "snapshot-selection", snapshot="private-snapshot"))
    expected = await store.inspect(actor, authority.binding_id, selected.artifact_id, "private-snapshot")
    other = await store.inspect(actor, authority.binding_id, selected.artifact_id, "different-snapshot")
    assert expected["reason"]
    assert other["id"] == selected.artifact_id and other["snapshot"] == "private-snapshot"
    assert other.get("reason") is None and not other.get("rejection_comparisons")


@pytest.mark.parametrize("target_kind", ("source", "claim", "selection", "operation", "feedback", "feedback-source"))
async def test_feedback_source_and_explicit_descendant_are_withdrawn_purged_and_scrubbed_after_historical_restore(authority, target_kind):
    store, actor = authority.store, authority.actor
    root, claim = await ready_claim(authority, "feedback-target")
    target = {"source": root.source_id, "claim": claim.id, "selection": claim.selection_id,
        "operation": root.id, "feedback": root.source_id, "feedback-source": root.source_id}[target_kind]
    reason = "The reviewer rejects the obsolete offline-only interpretation."
    feedback = await store.feedback(actor, FeedbackCommand(binding_id=authority.binding_id,
        idempotency_key="linked-feedback", target_ref=target, kind="reject", body=reason))
    if target_kind == "feedback":
        target = feedback.artifact_id
    elif target_kind == "feedback-source":
        target = feedback.source_id
    followup = await store.feedback(actor, FeedbackCommand(binding_id=authority.binding_id,
        idempotency_key="explicit-followup-feedback", target_ref=feedback.artifact_id, kind="correct", body=reason))
    proposal = await store.propose_rule(actor, RuleProposal(binding_id=authority.binding_id,
        idempotency_key="explicit-feedback-copy", body=reason, source_ids=(followup.source_id,)))
    independent = await store.capture(actor, command(authority, "unlinked-identical-body", reason))
    assert (await store.inspect(actor, authority.binding_id, feedback.artifact_id))["body"] == reason
    archive = await archive_rows(store)
    historical_claims(archive)
    await store.retract(actor, authority.binding_id, target, "withdraw-feedback-lineage")
    for reference in (feedback.artifact_id, feedback.source_id, followup.artifact_id, followup.source_id, proposal["source_id"]):
        next_read = await store.inspect(actor, authority.binding_id, reference)
        assert next_read["state"] == "retracted"
        assert reason not in json.dumps(next_read)
    await store.purge(actor, authority.binding_id, target, "purge-feedback-lineage")
    retained_head = store.journal.verify()["head"]
    for restored in (False, True):
        if restored:
            await restore_rows(store, archive, MIGRATIONS[4])
            with pytest.raises(DomainError) as barrier:
                await store.inspect(actor, authority.binding_id, feedback.source_id)
            assert barrier.value.code == "DELETION_BARRIER"
            await store.reconcile_journal(retained_head)
        for reference in (feedback.source_id, followup.source_id, proposal["source_id"]):
            result = await store.inspect(actor, authority.binding_id, reference)
            assert result["state"] == "purged" and "body" not in result
        assert reason not in json.dumps(await store.inspect(actor, authority.binding_id, feedback.artifact_id))
        assert reason not in json.dumps(await store.inspect(actor, authority.binding_id, followup.artifact_id))
        async with store.pool.acquire() as connection:
            assert await connection.fetchval("SELECT bool_and(reason IS NULL) FROM am_feedback WHERE id=ANY($1::text[])",
                [feedback.artifact_id, followup.artifact_id])
            assert await connection.fetchval("SELECT bool_and(body IS NULL) FROM am_sources WHERE id=ANY($1::text[])",
                [feedback.source_id, followup.source_id, proposal["source_id"]])
        assert (await store.source(actor, authority.binding_id, independent.source_id)).body == reason
        if target_kind in {"claim", "selection", "feedback", "feedback-source"}:
            assert (await store.source(actor, authority.binding_id, root.source_id)).body == command(authority).body
