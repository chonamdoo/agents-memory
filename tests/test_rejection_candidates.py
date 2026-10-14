from __future__ import annotations

import json
from typing import Literal

import pytest
from pydantic import ValidationError
from test_company_authority import capture
from test_company_authority import company as company
from test_source_judgment_history import (
    inspected_selection,
    record_selection,
    rejection_history,
)

from agents_memory.domain import (
    CaptureCommand,
    CaptureCoverage,
    DomainError,
    FeedbackCommand,
    RecordCommand,
)
from agents_memory.selection import RECORD_ADAPTER, RejectionComparison


async def reject_source(company, key, body, *, snapshot=None, request_snapshot=None):
    source = await capture(company, key=key, body=body, snapshot=snapshot)
    command, _ = await inspected_selection(
        company, source.source_id, key + "-discard",
        label="discard", snapshot=request_snapshot or snapshot,
    )
    selection_id = await record_selection(company, command)
    return source, selection_id


async def feedback(company, key, target, *, kind: Literal["correct", "reject", "retract_request"] = "reject", body="Private rejection reason."):
    return await company.store.feedback(
        company.actor,
        FeedbackCommand(
            binding_id=company.binding_id,
            idempotency_key=key,
            target_ref=target,
            kind=kind,
            body=body,
        ),
    )


async def test_required_comparisons_are_bounded_and_do_not_require_complete_history(company):
    await rejection_history(company, 40)
    source = await capture(
        company, key="bounded-independent", body="CacheKey is retained only offline.",
    )
    command, window = await inspected_selection(
        company, source.source_id, "bounded-publication",
    )
    context = window["judgment_context"]
    assert len(context["rejections"]) <= 8
    assert context["required_rejection_ids"] == [
        item["id"] for item in context["rejections"]
    ]
    assert context["rejection_page_kind"] == "required_candidates"
    assert context["optional_history"]["required_for_publication"] is False
    assert context["required_candidate_index"]["posting_probe_bound"] == 128
    assert context["required_candidate_index"]["examined_rejection_rows"] <= 32
    assert context["required_candidate_index"]["exhaustive"] is False
    operation = await company.store.record(company.actor, command)
    selected = await company.store.inspect(
        company.actor, company.binding_id, operation.artifact_id,
    )
    claim_id, = selected["claim_ids"]
    claimed = await company.store.claim(company.actor, company.binding_id, claim_id)
    assert claimed.input_source_ids == (source.source_id,)
    assert claimed.draft.statement == "CacheKey is retained only offline."


async def test_current_required_candidate_still_requires_explicit_caller_comparison(company):
    await reject_source(company, "related-old", "CacheKey is retained offline.")
    source = await capture(
        company, key="related-new", body="CacheKey is retained only offline.",
    )
    command, window = await inspected_selection(
        company, source.source_id, "missing-comparison",
    )
    assert window["judgment_context"]["required_rejection_ids"]
    command = command.model_copy(
        update={"rejection_comparisons": (), "prior_rejection_ids": ()},
    )
    with pytest.raises(DomainError) as caught:
        await company.store.record(company.actor, command)
    assert caught.value.code == "REJECTION_COMPARISON_REQUIRED"
    async with company.store.pool.acquire() as connection:
        assert not await connection.fetchval(
            "SELECT EXISTS(SELECT 1 FROM am_source_selections WHERE source_id=$1)",
            source.source_id,
        )


async def test_optional_history_is_complete_without_becoming_required(company):
    expected = await rejection_history(company, 25)
    source = await capture(
        company, key="optional-independent", body="CacheKey is retained only offline.",
    )
    cursor = "history"
    seen = []
    while cursor is not None:
        window = await company.store.inspect(
            company.actor, company.binding_id, source.source_id,
            rejection_cursor=cursor,
        )
        context = window["judgment_context"]
        assert context["rejection_page_kind"] == "optional_history"
        assert len(context["rejections"]) <= 8
        assert context["optional_history"]["examined_rows"] <= 32
        seen.extend(item["id"] for item in context["rejections"])
        cursor = context["rejections_next_cursor"]
    assert len(seen) == len(set(seen))
    assert set(seen) == set(expected)


async def test_hidden_ineligible_history_rows_have_bounded_empty_page_progress(company):
    expected = await rejection_history(company, 40)
    async with company.store.pool.acquire() as connection:
        await connection.execute(
            """UPDATE am_source_selections SET request_snapshot='private-scope'
               WHERE id=ANY($1::text[])""",
            expected,
        )
    source = await capture(company, key="history-reader")
    first = await company.store.inspect(
        company.actor, company.binding_id, source.source_id,
        rejection_cursor="history",
    )
    context = first["judgment_context"]
    assert context["rejections"] == []
    assert context["optional_history"]["examined_rows"] == 32
    assert context["rejections_partial"] is True
    assert context["rejections_next_cursor"]
    second = await company.store.inspect(
        company.actor, company.binding_id, source.source_id,
        rejection_cursor=context["rejections_next_cursor"],
    )
    assert second["judgment_context"]["rejections"] == []
    assert second["judgment_context"]["rejections_next_cursor"] is None


@pytest.mark.parametrize("identity", ("same_source", "copied_body"))
async def test_identity_refusal_is_independent_of_candidate_index(company, identity):
    source, rejection_id = await reject_source(
        company, "identity-original", "CacheKey is retained offline.",
    )
    async with company.store.pool.acquire() as connection:
        await connection.execute(
            "DELETE FROM am_rejection_tokens WHERE rejection_id=$1",
            rejection_id,
        )
    if identity == "copied_body":
        source = await capture(company, key="identity-copy")
    command, window = await inspected_selection(
        company, source.source_id, "identity-publication",
    )
    assert window["judgment_context"]["rejections"] == []
    with pytest.raises(DomainError) as caught:
        await company.store.record(company.actor, command)
    assert caught.value.code == "EVIDENCE_REJECTED"


async def test_request_scoped_global_discard_does_not_leak_or_enforce_elsewhere(company):
    _, rejection_id = await reject_source(
        company, "global-discard", "CacheKey is retained offline.",
        request_snapshot="scope-a",
    )
    visible = await company.store.inspect(
        company.actor, company.binding_id, rejection_id, "scope-a",
    )
    hidden = await company.store.inspect(
        company.actor, company.binding_id, rejection_id, "scope-b",
    )
    assert visible["reason"]
    assert "reason" not in hidden
    copied = await capture(company, key="global-copy")
    command, window = await inspected_selection(
        company, copied.source_id, "other-scope-publication", snapshot="scope-b",
    )
    assert window["judgment_context"]["rejections"] == []
    assert (await company.store.record(company.actor, command)).state == "candidate_ready"


@pytest.mark.parametrize("indirect", ("source", "selection", "operation", "feedback", "reason_source"))
async def test_feedback_and_separate_reason_source_follow_target_scope(company, indirect):
    source = await capture(company, key="scoped-feedback-root", snapshot="scope-a")
    target = source.source_id
    if indirect in {"selection", "operation"}:
        command, _ = await inspected_selection(
            company, source.source_id, "scoped-target-selection", snapshot="scope-a",
        )
        operation = await company.store.record(company.actor, command)
        target = operation.artifact_id if indirect == "selection" else operation.id
    elif indirect in {"feedback", "reason_source"}:
        earlier = await feedback(company, "earlier-scoped-feedback", target)
        target = earlier.artifact_id if indirect == "feedback" else earlier.source_id
    operation = await feedback(company, "scoped-feedback", target)
    same_scope = await company.store.inspect(
        company.actor, company.binding_id, operation.artifact_id, "scope-a",
    )
    assert same_scope["reason"] == "Private rejection reason."
    other_scope = await company.store.inspect(
        company.actor, company.binding_id, operation.artifact_id, "scope-b",
    )
    assert "reason" not in other_scope and "body" not in other_scope
    with pytest.raises(DomainError) as caught:
        await company.store.inspect(
            company.actor, company.binding_id, operation.source_id, "scope-b",
        )
    assert caught.value.code in {"INPUT_INELIGIBLE", "SNAPSHOT_INELIGIBLE"}
    with pytest.raises(DomainError):
        await company.store.source(
            company.actor, company.binding_id, operation.source_id,
        )


async def test_feedback_of_scoped_global_selection_inherits_request_snapshot(company):
    source = await capture(company, key="global-feedback-root")
    command, _ = await inspected_selection(
        company, source.source_id, "global-scoped-target",
        label="discard", snapshot="scope-a",
    )
    selection_id = await record_selection(company, command)
    operation = await feedback(company, "global-scoped-feedback", selection_id)
    visible = await company.store.inspect(
        company.actor, company.binding_id, operation.artifact_id, "scope-a",
    )
    hidden = await company.store.inspect(
        company.actor, company.binding_id, operation.artifact_id, "scope-b",
    )
    assert visible["reason"]
    assert "reason" not in hidden and "body" not in hidden


async def test_feedback_cycle_fails_closed_on_feedback_and_reason_source_reads(company):
    root = await capture(company, key="cycle-root")
    first = await feedback(company, "cycle-first", root.source_id)
    second = await feedback(company, "cycle-second", first.artifact_id)
    async with company.store.pool.acquire() as connection:
        await connection.execute(
            "UPDATE am_feedback SET target_ref=$2 WHERE id=$1",
            first.artifact_id, second.artifact_id,
        )
    result = await company.store.inspect(
        company.actor, company.binding_id, first.artifact_id,
    )
    assert "reason" not in result and "body" not in result
    with pytest.raises(DomainError) as caught:
        await company.store.inspect(
            company.actor, company.binding_id, first.source_id,
        )
    assert caught.value.code == "INPUT_INELIGIBLE"


async def test_notes_and_feedback_reasons_do_not_create_independent_pending_work(company):
    note = await company.store.record(
        company.actor,
        RecordCommand(
            binding_id=company.binding_id,
            idempotency_key="plain-note",
            kind="note",
            body="CacheKey is retained offline.",
        ),
    )
    root = await capture(company, key="human-feedback-root")
    rejected = await feedback(company, "reason-note", root.source_id)
    async with company.store.pool.acquire() as connection:
        assert await connection.fetchval(
            """SELECT count(*) FROM am_pending_judgments
               WHERE kind='source_selection'
                 AND source_ids && $1::text[]
                 AND state IN ('pending','held')""",
            [note.source_id, rejected.source_id],
        ) == 0
    for source_id, expected in ((note.source_id, "CacheKey is retained offline."),
                                (rejected.source_id, "Private rejection reason.")):
        inspected = await company.store.inspect(
            company.actor, company.binding_id, source_id,
        )
        assert inspected["body"] == expected
        assert inspected["judgment_required"] is False
        assert inspected["admission_id"] is None


async def test_existing_note_discard_does_not_poison_identical_human_evidence(company):
    note = await company.store.record(
        company.actor,
        RecordCommand(
            binding_id=company.binding_id,
            idempotency_key="historical-note",
            body="CacheKey is retained offline.",
        ),
    )
    async with company.store.pool.acquire() as connection:
        policy = await company.store._selection_contract(
            connection, company.actor, company.binding_id,
        )
        await connection.execute(
            """INSERT INTO am_source_selections(
                   id,binding_id,operation_id,credential_id,credential_generation,
                   realm,binding_revision,source_id,source_revision,
                   byte_start,byte_end,window_digest,judgment_digest,
                   policy_revision,policy_epoch,label,coverage,reason
               )
               VALUES(
                   'selection_historical_note',$1,$2,$3,$4,$5,$6,$7,1,
                   0,29,$8,$8,$9,0,'discard','complete_window','Discarded agent note'
               )""",
            company.binding_id, note.id, company.actor.credential_id,
            company.actor.generation, company.actor.realm, policy["binding_revision"],
            note.source_id, "a" * 64, policy["revision"],
        )
        await connection.execute(
            """INSERT INTO am_selection_sources(selection_id,source_id,source_revision)
               VALUES('selection_historical_note',$1,1)""",
            note.source_id,
        )
        await company.store._index_rejection(
            connection, company.binding_id, "selection_historical_note",
        )
        assert not await connection.fetchval(
            """SELECT EXISTS(SELECT 1 FROM am_rejection_evidence
               WHERE rejection_id='selection_historical_note')""",
        )
    human = await capture(company, key="genuine-identical-human")
    command, _ = await inspected_selection(
        company, human.source_id, "genuine-identical-publication",
    )
    assert (await company.store.record(company.actor, command)).state == "candidate_ready"


@pytest.mark.parametrize("speaker", ("assistant", "human", "tool", "document"))
async def test_reopening_requires_declared_independent_speaker(company, speaker):
    await reject_source(company, "reopen-old", "OldKey is retained offline.")
    body = "CacheKey is retained only offline."
    source = await company.store.capture(
        company.actor,
        CaptureCommand(
            binding_id=company.binding_id,
            idempotency_key="reopen-new",
            origin_key="reopen-new",
            body=body,
            speaker=speaker,
            coverage=CaptureCoverage(
                status="observed_window", original_bytes=len(body.encode()),
            ),
        ),
    )
    command, window = await inspected_selection(
        company, source.source_id, "reopen-comparison",
        cursor="history", decision="reopen",
    )
    assert window["judgment_context"]["rejections"]
    if speaker == "assistant":
        with pytest.raises(DomainError) as caught:
            await company.store.record(company.actor, command)
        assert caught.value.code == "EVIDENCE_REJECTED"
    else:
        assert (await company.store.record(company.actor, command)).state == "candidate_ready"


async def test_discard_supplied_invalid_comparison_is_refused_before_publication(company):
    source = await capture(company, key="discard-invalid-root")
    command, _ = await inspected_selection(
        company, source.source_id, "discard-invalid", label="discard",
    )
    command = command.model_copy(update={
        "rejection_comparisons": (RejectionComparison(
            rejection_id="selection_not_inspected", decision="unrelated",
            reason="An uninspected persisted reference was supplied.",
        ),),
    })
    with pytest.raises(DomainError) as caught:
        await company.store.record(company.actor, command)
    assert caught.value.code == "REJECTION_COMPARISON_REQUIRED"
    async with company.store.pool.acquire() as connection:
        assert not await connection.fetchval(
            "SELECT EXISTS(SELECT 1 FROM am_source_selections WHERE source_id=$1)",
            source.source_id,
        )


async def test_discard_supplied_stale_review_is_refused_before_publication(company):
    await reject_source(company, "discard-review-old", "OldKey is retained offline.")
    source = await capture(company, key="discard-review-new")
    review, _ = await inspected_selection(
        company, source.source_id, "optional-review", label="review", cursor="history",
    )
    review_id = await record_selection(company, review)
    async with company.store.pool.acquire() as connection:
        await connection.execute(
            "UPDATE am_source_selections SET policy_revision=$2 WHERE id=$1",
            review_id, "0" * 64,
        )
    command, _ = await inspected_selection(
        company, source.source_id, "discard-stale-review",
        label="discard", review_ids=(review_id,),
    )
    with pytest.raises(DomainError) as caught:
        await company.store.record(company.actor, command)
    assert caught.value.code == "REJECTION_REVIEW_STALE"
    async with company.store.pool.acquire() as connection:
        assert not await connection.fetchval(
            """SELECT EXISTS(SELECT 1 FROM am_source_selections
               WHERE source_id=$1 AND label='discard')""",
            source.source_id,
        )


@pytest.mark.parametrize("kind", ([], {}, ["source_selection"], {"name": "source_selection"}))
def test_malformed_record_discriminator_is_typed_invalid_input(kind):
    with pytest.raises(ValidationError):
        RECORD_ADAPTER.validate_python({
            "kind": kind,
            "idempotency_key": "invalid-kind",
            "body": "ordinary body",
        })


@pytest.mark.parametrize("field", ("policy_revision", "policy_epoch"))
async def test_current_selection_policy_fields_are_nonnullable(company, field):
    source = await capture(company, key="nonnull-source")
    command, _ = await inspected_selection(company, source.source_id, "nonnull-selection")
    payload = command.model_dump()
    payload[field] = None
    with pytest.raises(ValidationError):
        type(command).model_validate(payload)
    schema = type(command).model_json_schema()
    assert "null" not in json.dumps(schema["properties"][field])


async def test_many_private_rejections_cannot_exhaust_another_snapshot_identity_check(company):
    _, private_id = await reject_source(
        company, "many-private-original", "CacheKey is retained offline.",
        request_snapshot="scope-a",
    )
    for index in range(33):
        await feedback(company, f"private-rejection-{index}", private_id)
    independent = await capture(company, key="scope-b-original")
    request, window = await inspected_selection(
        company, independent.source_id, "scope-b-publication", snapshot="scope-b",
    )
    assert window["judgment_context"]["rejections"] == []
    result = await company.store.record(company.actor, request)
    selection = await company.store.inspect(company.actor, company.binding_id, result.artifact_id, "scope-b")
    claim_id, = selection["claim_ids"]
    claim = await company.store.claim(company.actor, company.binding_id, claim_id, "scope-b")
    assert claim.input_source_ids == (independent.source_id,)


async def test_rejecting_a_global_claim_is_global_even_if_its_selection_audit_was_scoped(company):
    original = await capture(company, key="global-claim-original")
    request, _ = await inspected_selection(
        company, original.source_id, "scoped-global-remember", snapshot="scope-a",
    )
    selected = await company.store.record(company.actor, request)
    selection = await company.store.inspect(company.actor, company.binding_id, selected.artifact_id, "scope-a")
    claim_id, = selection["claim_ids"]
    rejected = await feedback(company, "global-claim-rejection", claim_id)
    visible = await company.store.inspect(
        company.actor, company.binding_id, rejected.artifact_id, "scope-b",
    )
    assert visible["body"] == "Private rejection reason."
    independent = await capture(company, key="global-claim-copy")
    request, window = await inspected_selection(
        company, independent.source_id, "global-rejection-publication", snapshot="scope-b",
    )
    assert rejected.artifact_id in window["judgment_context"]["required_rejection_ids"]
    with pytest.raises(DomainError) as caught:
        await company.store.record(company.actor, request)
    assert caught.value.code == "EVIDENCE_REJECTED"
