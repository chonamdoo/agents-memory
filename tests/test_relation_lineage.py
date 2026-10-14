from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from test_company_authority import archive_rows, restore_rows
from test_store_authority import authority as authority
from test_store_authority import (
    cleanup_command,
    command,
    ready_claim,
    recall_context,
    source_selection,
)

from agents_memory.domain import DomainError, Relation
from agents_memory.lexical import tokens
from agents_memory.semantic_contract import GeneratedExtraction


async def judged_pair(authority, inputs, left, right, relation, key):
    store, actor = authority.store, authority.actor
    manifest = await store.inspect(
        actor, authority.binding_id, "judgment",
        claim_ids=tuple(claim.id for claim in inputs),
    )
    for item in manifest["claims"]:
        await store.inspect(actor, authority.binding_id, item["id"])
    for relation_id in manifest["relation_ids"]:
        await store.inspect(actor, authority.binding_id, relation_id)
    request = cleanup_command(
        authority, manifest, key,
        relations=({
            "left_id": left.id,
            "right_id": right.id,
            "relation": relation,
            "reason": f"Independent caller derivation {key}.",
        },),
    )
    return await store.record(actor, request)


async def owned_edge(authority, judgment_id):
    async with authority.store.pool.acquire() as connection:
        rows = await connection.fetch(
            "SELECT * FROM am_relations WHERE judgment_id=$1 ORDER BY id",
            judgment_id,
        )
        assert len(rows) == 1
        row = rows[0]
        sources = await connection.fetch(
            """SELECT source_id,source_revision FROM am_relation_sources
            WHERE relation_id=$1 ORDER BY source_id""",
            row["id"],
        )
        claims = await connection.fetch(
            """SELECT claim_id FROM am_relation_claims
            WHERE relation_id=$1 ORDER BY claim_id""",
            row["id"],
        )
        return row, {
            item["source_id"]: item["source_revision"] for item in sources
        }, {item["claim_id"] for item in claims}


async def assert_next_consumer(authority, left, right, relation, owner, *, retained=()):
    store, actor = authority.store, authority.actor
    edges = await store.relations(
        actor, authority.binding_id, (left.id, right.id),
    )
    assert len(edges) == 1
    edge = edges[0]
    assert (edge.left_id, edge.right_id, edge.kind) == (
        left.id, right.id, relation,
    )
    own, _, _ = await owned_edge(authority, owner.artifact_id)
    assert edge.id == own["id"]
    assert edge.reason == own["reason"]

    inspected = await store.inspect(actor, authority.binding_id, edge.id)
    assert inspected["relation_kind"] == relation
    audit = await store.inspect(actor, authority.binding_id, owner.artifact_id)
    assert audit["relations"][0]["relation"] == relation

    _, admission = await store.search_lexical(
        actor, authority.binding_id, tokens("CacheKey"), None,
        request_digest="a" * 64,
    )
    assert admission.relation_ids == (edge.id,)

    context = json.loads((await recall_context(authority))["context"])
    assert {item["ref"] for item in context["memory_candidates"]} == {
        left.id, right.id, *(claim.id for claim in retained),
    }
    assert context["relations"] == [{
        "ref": edge.id,
        "left": left.id,
        "right": right.id,
        "kind": relation,
        "endpoints_in_context": [left.id, right.id],
    }]


@pytest.mark.parametrize("relation", ("supports", "contradicts", "supersedes"))
@pytest.mark.parametrize("change", (
    "source_withdrawal",
    "claim_withdrawal",
    "judgment_withdrawal",
    "source_correction",
    "claim_correction",
    "judgment_correction",
    "expiry",
))
async def test_subset_judgment_retains_own_lineage_after_extra_input_changes(
    authority, relation, change,
):
    store, actor = authority.store, authority.actor
    left_source, left = await ready_claim(authority, "lineage-left")
    right_source, right = await ready_claim(
        authority, "lineage-right",
        "CacheKey is not retained only offline."
        if relation == "contradicts"
        else "CacheKey is retained only offline.",
        polarity="negative" if relation == "contradicts" else "positive",
    )
    third_source, third = await ready_claim(
        authority, "lineage-third", "CacheKey is retained only offline.",
    )
    first = await judged_pair(
        authority, (left, right, third), left, right, relation, "first-abc",
    )
    second = await judged_pair(
        authority, (left, right), left, right, relation, "second-ab",
    )

    first_edge, first_sources, first_claims = await owned_edge(
        authority, first.artifact_id,
    )
    second_edge, second_sources, second_claims = await owned_edge(
        authority, second.artifact_id,
    )
    assert first_edge["id"] != second_edge["id"]
    assert first_claims == {left.id, right.id, third.id}
    assert second_claims == {left.id, right.id}
    assert first_sources == {
        left_source.source_id: 1,
        right_source.source_id: 1,
        third_source.source_id: 1,
    }
    assert second_sources == {
        left_source.source_id: 1,
        right_source.source_id: 1,
    }

    if change == "expiry":
        async with store.pool.acquire() as connection:
            await connection.execute(
                """UPDATE am_claims SET valid_until=clock_timestamp()-interval '1 second'
                WHERE id=$1""",
                third.id,
            )
    else:
        target = {
            "source": third_source.source_id,
            "claim": third.id,
            "judgment": first.artifact_id,
        }[change.split("_")[0]]
        if change.endswith("withdrawal"):
            await store.retract(
                actor, authority.binding_id, target, "withdraw-first-input",
            )
        else:
            replacement = await store.correct(
                actor, authority.binding_id, target,
                command(
                    authority, "correct-first-input",
                    "OtherKey has independently corrected evidence.",
                ),
            )
            assert replacement.state == "captured"

    hidden = await store.inspect(actor, authority.binding_id, first.artifact_id)
    assert hidden["reason"] is None
    assert hidden["relations"] is None
    await assert_next_consumer(authority, left, right, relation, second,
        retained=(third,) if change.startswith("judgment_") else ())


@pytest.mark.parametrize("relation", (
    "duplicate", "supports", "contradicts", "supersedes",
))
async def test_equal_manifests_do_not_share_first_owner_lifetime(
    authority, relation,
):
    store, actor = authority.store, authority.actor
    _, left = await ready_claim(authority, "equal-left")
    _, right = await ready_claim(
        authority, "equal-right",
        "CacheKey is not retained only offline."
        if relation == "contradicts"
        else "CacheKey is retained only offline.",
        polarity="negative" if relation == "contradicts" else "positive",
    )
    first = await judged_pair(
        authority, (left, right), left, right, relation, "equal-first",
    )
    second = await judged_pair(
        authority, (left, right), left, right, relation, "equal-second",
    )
    first_audit = await store.inspect(
        actor, authority.binding_id, first.artifact_id,
    )
    second_audit = await store.inspect(
        actor, authority.binding_id, second.artifact_id,
    )
    assert first_audit["manifest_digest"] == second_audit["manifest_digest"]
    assert first_audit["relations"][0]["reason"] != (
        second_audit["relations"][0]["reason"]
    )

    first_edge, _, _ = await owned_edge(authority, first.artifact_id)
    second_edge, _, _ = await owned_edge(authority, second.artifact_id)
    assert first_edge["id"] != second_edge["id"]

    await store.retract(
        actor, authority.binding_id, first.artifact_id, "withdraw-equal-first",
    )
    await assert_next_consumer(authority, left, right, relation, second)
    assert (await store.claim(actor, authority.binding_id, left.id)).evidence == (
        left.evidence
    )
    assert (await store.claim(actor, authority.binding_id, right.id)).evidence == (
        right.evidence
    )


async def test_missing_asserted_own_edge_cannot_suppress_cleanup(authority):
    store, actor = authority.store, authority.actor
    _, left = await ready_claim(authority, "missing-left")
    _, right = await ready_claim(authority, "missing-right")
    pending_id = (await store.schedule_cleanup())["pending_ids"][0]
    manifest = (await store.inspect(
        actor, authority.binding_id, pending_id,
    ))["judgment_manifest"]
    for item in manifest["claims"]:
        await store.inspect(actor, authority.binding_id, item["id"])
    written = await store.record(
        actor,
        cleanup_command(
            authority, manifest, "missing-edge-judgment",
            relations=({
                "left_id": left.id,
                "right_id": right.id,
                "relation": "supports",
                "reason": "Caller checked both original claims.",
            },),
        ),
    )
    edge, _, _ = await owned_edge(authority, written.artifact_id)

    async with store.pool.acquire() as connection:
        await connection.execute(
            "DELETE FROM am_relation_sources WHERE relation_id=$1", edge["id"],
        )
        await connection.execute(
            "DELETE FROM am_relation_claims WHERE relation_id=$1", edge["id"],
        )
        await connection.execute(
            "DELETE FROM am_relations WHERE id=$1", edge["id"],
        )
        await connection.execute(
            """UPDATE am_pending_judgments
            SET created_at=clock_timestamp()-interval '2 days'
            WHERE id=$1""",
            pending_id,
        )

    audit = await store.inspect(actor, authority.binding_id, written.artifact_id)
    assert audit["reason"] is None
    assert audit["relations"] is None
    assert await store.relations(
        actor, authority.binding_id, (left.id, right.id),
    ) == []

    scheduled = await store.schedule_cleanup()
    assert scheduled["created"] == 1
    renewed = await store.inspect(
        actor, authority.binding_id, scheduled["pending_ids"][0],
    )
    assert renewed["judgment_manifest"]["judgment_required"]
    assert {item["id"] for item in renewed["judgment_manifest"]["claims"]} == {
        left.id, right.id,
    }


async def test_duplicate_public_output_has_one_vocabulary(authority):
    store, actor = authority.store, authority.actor
    _, left = await ready_claim(authority, "public-left")
    _, right = await ready_claim(authority, "public-right")
    written = await judged_pair(
        authority, (left, right), left, right, "duplicate", "public-duplicate",
    )
    edge, _, _ = await owned_edge(authority, written.artifact_id)
    assert edge["kind"] == "duplicates"

    manifest = await store.inspect(
        actor, authority.binding_id, "judgment",
        claim_ids=(left.id, right.id),
    )
    assert manifest["relations"][0]["relation"] == "duplicate"
    await assert_next_consumer(authority, left, right, "duplicate", written)

    with pytest.raises(ValidationError):
        Relation.model_validate({
            "id": edge["id"], "left_id": left.id, "right_id": right.id,
            "kind": "duplicates", "reason": edge["reason"],
        })


async def qualified_claim(
    authority, key, body, *, polarity="positive", conditions=(), exceptions=(),
):
    store, actor = authority.store, authority.actor
    captured = await store.capture(actor, command(authority, key, body))
    request = await source_selection(
        authority, captured.source_id, key + "-selection", polarity=polarity,
    )
    assert request.extraction is not None
    original = request.extraction.model_dump(mode="json")
    span_id = original["claims"][0]["assertion_span_id"]
    original["individual_qualifications"] = [
        {
            "assertion_id": "a0000",
            "kind": kind,
            "phrase": phrase,
            "evidence_span_id": span_id,
        }
        for kind, phrases in (
            ("condition", conditions), ("exception", exceptions),
        )
        for phrase in phrases
    ]
    selected = await store.record(actor, request.model_copy(update={
        "extraction": GeneratedExtraction.model_validate(original),
    }))
    claim_id = (await store.inspect(
        actor, authority.binding_id, selected.artifact_id,
    ))["claim_ids"][0]
    return await store.claim(actor, authority.binding_id, claim_id)


@pytest.mark.parametrize("difference,relation", (
    ("polarity", "duplicate"),
    ("polarity", "supports"),
    ("condition", "duplicate"),
    ("condition", "supports"),
    ("condition", "contradicts"),
    ("condition", "supersedes"),
    ("exception", "duplicate"),
    ("exception", "supports"),
    ("exception", "contradicts"),
    ("exception", "supersedes"),
))
async def test_invalid_relation_refusal_preserves_grounded_originals(
    authority, difference, relation,
):
    store, actor = authority.store, authority.actor
    left = await qualified_claim(
        authority, "refusal-left", "CacheKey is retained only offline.",
        conditions=("only offline",),
    )
    if difference == "polarity":
        right = await qualified_claim(
            authority, "refusal-right",
            "CacheKey is not retained only offline.",
            polarity="negative", conditions=("only offline",),
        )
    elif difference == "condition":
        right = await qualified_claim(
            authority, "refusal-right",
            "CacheKey is retained offline only when disconnected.",
            conditions=("only when disconnected",),
        )
    else:
        right = await qualified_claim(
            authority, "refusal-right",
            "CacheKey is retained only offline, except during maintenance.",
            conditions=("only offline",),
            exceptions=("except during maintenance",),
        )

    async with store.pool.acquire() as connection:
        before = [await connection.fetchval(f"SELECT count(*) FROM {table}")
            for table in ("am_claim_judgments", "am_relations", "am_operations")]

    with pytest.raises(DomainError) as refused:
        await judged_pair(
            authority, (left, right), left, right, relation, "invalid-relation",
        )
    assert refused.value.code == "JUDGMENT_RELATION_INVALID"

    async with store.pool.acquire() as connection:
        after = [await connection.fetchval(f"SELECT count(*) FROM {table}")
            for table in ("am_claim_judgments", "am_relations", "am_operations")]
    assert after == before
    assert await store.relations(
        actor, authority.binding_id, (left.id, right.id),
    ) == []

    context = json.loads((await recall_context(authority))["context"])
    recalled = {item["ref"]: item for item in context["memory_candidates"]}
    assert set(recalled) == {left.id, right.id}
    assert context["relations"] == []
    for original in (left, right):
        current = await store.claim(actor, authority.binding_id, original.id)
        assert current.draft == original.draft
        assert current.evidence == original.evidence
        candidate = recalled[original.id]
        assert candidate["statement"] == original.draft.statement
        assert candidate["polarity"] == original.draft.polarity
        assert candidate["conditions"] == list(original.draft.conditions)
        assert candidate["exceptions"] == list(original.draft.exceptions)
        assert [
            (span["source"], span["revision"], span["bytes"], span["quote"])
            for span in candidate["evidence"]
        ] == [
            (
                span.source_id, span.source_revision,
                [span.byte_start, span.byte_end], span.quote,
            )
            for span in original.evidence
        ]


@pytest.mark.parametrize("label", ("discard", "review"))
@pytest.mark.parametrize("speaker", ("human", "assistant"))
async def test_nonderiving_withdrawal_reopens_without_extraction_floor(
    authority, label, speaker,
):
    store, actor = authority.store, authority.actor
    captured = await store.capture(
        actor, command(authority, "withdraw-nonderiving").model_copy(update={"speaker": speaker}),
    )
    selected = await store.record(
        actor, await source_selection(
            authority, captured.source_id, "nonderiving-selection", label=label,
        ),
    )
    async with store.pool.acquire() as connection:
        pending_id = await connection.fetchval(
            """SELECT id FROM am_pending_judgments
            WHERE $1=ANY(source_ids) AND kind='source_selection'""",
            captured.source_id,
        )
        before_state = await connection.fetchval(
            "SELECT state FROM am_pending_judgments WHERE id=$1", pending_id,
        )
    assert before_state == ("resolved" if label == "discard" else "pending")

    await store.retract(
        actor, authority.binding_id, selected.artifact_id,
        "withdraw-nonderiving-selection",
    )
    extraction_token = store.journal.artifact_tokens((
        ("extract_source", captured.source_id),
    ))[("extract_source", captured.source_id)]
    async with store.pool.acquire() as connection:
        assert not await connection.fetchval(
            """SELECT EXISTS(SELECT 1 FROM am_floors
            WHERE kind='artifact' AND token=$1)""",
            extraction_token,
        )
        pending = await connection.fetchrow(
            "SELECT state,resolved_at FROM am_pending_judgments WHERE id=$1",
            pending_id,
        )
        assert pending["state"] == "pending"
        assert pending["resolved_at"] is None
    assert (await store.source(
        actor, authority.binding_id, captured.source_id,
    )).state == "active"

    remembered = await store.record(
        actor, await source_selection(
            authority, captured.source_id, "remember-after-withdrawal",
        ),
    )
    assert remembered.state == "candidate_ready"
    claim_id = (await store.inspect(
        actor, authority.binding_id, remembered.artifact_id,
    ))["claim_ids"][0]
    context = json.loads((await recall_context(authority))["context"])
    assert [item["ref"] for item in context["memory_candidates"]] == [claim_id]


async def test_withdrawing_review_does_not_reopen_still_covered_source(authority):
    store, actor = authority.store, authority.actor
    captured = await store.capture(actor, command(authority, "covered-source"))
    reviewed = await store.record(
        actor, await source_selection(
            authority, captured.source_id, "covered-review", label="review",
        ),
    )
    remembered = await store.record(
        actor, await source_selection(
            authority, captured.source_id, "covered-remember",
        ),
    )
    await store.retract(
        actor, authority.binding_id, reviewed.artifact_id, "withdraw-covered-review",
    )
    async with store.pool.acquire() as connection:
        assert not await connection.fetchval(
            """SELECT EXISTS(SELECT 1 FROM am_pending_judgments
            WHERE $1=ANY(source_ids) AND state IN ('pending','held'))""",
            captured.source_id,
        )
    selected = await store.inspect(actor, authority.binding_id, remembered.artifact_id)
    context = json.loads((await recall_context(authority))["context"])
    assert [item["ref"] for item in context["memory_candidates"]] == selected["claim_ids"]


async def test_restore_reconciliation_preserves_legacy_held_state(authority):
    store, actor = authority.store, authority.actor
    captured = await store.capture(actor, command(authority, "held-source"))
    reviewed = await store.record(
        actor, await source_selection(
            authority, captured.source_id, "held-review", label="review",
        ),
    )
    reason = "Retained legacy work requires explicit caller disposition."
    async with store.pool.acquire() as connection:
        pending_id = await connection.fetchval(
            """UPDATE am_pending_judgments
            SET kind='legacy_revalidation',state='held',reason=$2,resolved_at=NULL
            WHERE $1=ANY(source_ids) AND kind='source_selection'
            RETURNING id""",
            captured.source_id, reason,
        )
    archived = await archive_rows(store)
    withdrawn = await store.retract(
        actor, authority.binding_id, reviewed.artifact_id, "withdraw-held-review",
    )

    await restore_rows(store, archived)
    await store.reconcile_journal(withdrawn["head"])
    restored = await store.inspect(actor, authority.binding_id, pending_id)
    assert restored["pending_kind"] == "legacy_revalidation"
    assert restored["state"] == "held"
    assert restored["reason"] == reason
    assert restored["source_ids"] == [captured.source_id]
    async with store.pool.acquire() as connection:
        assert not await connection.fetchval(
            """SELECT EXISTS(SELECT 1 FROM am_pending_judgments
            WHERE $1=ANY(source_ids) AND id<>$2
            AND kind='source_selection' AND state IN ('pending','held'))""",
            captured.source_id, pending_id,
        )

    remembered = await store.record(
        actor, await source_selection(
            authority, captured.source_id, "explicit-held-disposition",
        ),
    )
    assert remembered.state == "candidate_ready"
    assert (await store.inspect(
        actor, authority.binding_id, pending_id,
    ))["state"] == "resolved"
