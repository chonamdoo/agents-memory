from __future__ import annotations

import hashlib
import json

import pytest
from test_edge_boundaries import bounded_inspection_plane, running
from test_store_authority import authority as authority
from test_store_authority import command, ready_claim

from agents_memory.domain import DomainError, FeedbackCommand


@pytest.mark.parametrize("transport", ("modern", "legacy"))
async def test_claim_continuation_keeps_stored_semantics_across_unrelated_writes(authority, transport):
    store, actor, binding = authority.store, authority.actor, authority.binding_id
    _, original = await ready_claim(authority, "original-record")
    async with running(authority) as edge:
        async with store.pool.acquire() as connection:
            await connection.execute("UPDATE am_clock SET epoch=9")
        arguments = {"binding_id": binding, "ref": original.id, "max_bytes": 128}
        first = await bounded_inspection_plane(edge, authority, arguments, transport)
        _, unrelated = await ready_claim(authority, "unrelated-record", body="CacheKey is retained offline.")
        rejected = await store.capture(actor, command(authority, "rejected-input", "RejectedKey is retained offline."))
        await store.feedback(actor, FeedbackCommand(
            binding_id=binding, idempotency_key="unrelated-rejection", target_ref=rejected.source_id,
            kind="reject", body="This unrelated original must not become a remembered preference.",
        ))
        async with store.pool.acquire() as connection:
            await connection.execute("UPDATE am_clock SET epoch=10")
        restarted = await bounded_inspection_plane(edge, authority, arguments, transport, 2)
        assert restarted["draft_window"] == first["draft_window"]
        assert first["epoch"] == 9 and restarted["epoch"] == 10
        chunk = first["draft_window"]
        digest, total, cursor = chunk["digest"], chunk["total_bytes"], chunk["next_byte"]
        fragments = [chunk["body"].encode("utf-8")]
        while cursor is not None:
            inspected = await bounded_inspection_plane(edge, authority, {
                **arguments, "byte_start": cursor,
            }, transport, 3)
            chunk = inspected["draft_window"]
            fragment = chunk["body"].encode("utf-8")
            assert chunk["digest"] == digest and chunk["total_bytes"] == total
            assert chunk["byte_start"] == cursor < chunk["byte_end"]
            assert chunk["byte_end"] - cursor == len(fragment) <= 128
            fragments.append(fragment)
            cursor = chunk["next_byte"]
        raw = b"".join(fragments)
        assert len(raw) == total and hashlib.sha256(raw).hexdigest() == digest
        stored = json.loads(raw)
        assert stored["draft"] == original.draft.model_dump(mode="json", exclude={"evidence"})
        assert stored["input_source_ids"] == list(original.input_source_ids)
        assert "epoch" not in stored and "judgment_context" not in stored
        assert stored["judgment_context_refs"] == [
            {"ref": source_id, "snapshot": None} for source_id in original.input_source_ids
        ]
        live = await bounded_inspection_plane(edge, authority, {
            "binding_id": binding, **stored["judgment_context_refs"][0],
        }, transport, 4)
        assert {item["id"] for item in live["judgment_context"]["accepted_memories"]} == {original.id, unrelated.id}


def test_budget_limited_record_offsets_reserve_live_epoch_width():
    from agents_memory.representation import serialized_json_bytes, stored_record_window

    record = {
        "id": "judgment-clock-width", "kind": "judgment", "state": "active", "epoch": 9,
        "reason": 'Keep the qualification: 가😀"\\\n' * 500,
    }
    before = stored_record_window(record, 0, 4096, 1024)
    after = stored_record_window({**record, "epoch": 10}, 0, 4096, 1024)
    assert before["draft_window"] == after["draft_window"]
    assert before["epoch"] == 9 and after["epoch"] == 10
    assert serialized_json_bytes(before) <= 1024 and serialized_json_bytes(after) <= 1024
    assert before["draft_window"]["byte_end"] < 4096




@pytest.mark.parametrize("transport", ("modern", "legacy"))
async def test_complete_feedback_reason_survives_bounded_mcp_continuation(authority, transport):
    from test_edge_boundaries import reconstruct_stored_inspection

    store, actor, binding = authority.store, authority.actor, authority.binding_id
    source = await store.capture(actor, command(authority, "feedback-original"))
    reason = '거부😀"\\\n' * 220
    rejected = await store.feedback(actor, FeedbackCommand(
        binding_id=binding, idempotency_key="full-rejection-reason", target_ref=source.source_id,
        kind="reject", body=reason,
    ))
    async with running(authority) as edge:
        stored = await reconstruct_stored_inspection(edge, authority, rejected.artifact_id, transport)
        assert stored["reason"] == reason and stored["body"] == reason
        assert stored["target_ref"] == source.source_id
        source_id = stored["source_id"]
        await store.retract(actor, binding, rejected.artifact_id, "withdraw-feedback-record")
        hidden = await bounded_inspection_plane(edge, authority, {
            "binding_id": binding, "ref": rejected.artifact_id,
        }, transport, 100)
        assert hidden["state"] == "retracted"
        assert "draft_window" not in hidden and "reason" not in hidden and "body" not in hidden
        with pytest.raises(DomainError) as withdrawn:
            await store.source(actor, binding, source_id)
        assert withdrawn.value.code == "SOURCE_INELIGIBLE"


@pytest.mark.parametrize("transport", ("modern", "legacy"))
async def test_minimum_mcp_cap_can_inspect_a_plain_captured_source(authority, transport):
    store = authority.store
    body = "CacheKey is retained offline."
    source = await store.capture(authority.actor, command(authority, "minimum-source", body))
    store.settings = store.settings.model_copy(update={"max_mcp_response_bytes": 4096})
    async with running(authority) as edge:
        result = await bounded_inspection_plane(edge, authority, {
            "binding_id": authority.binding_id, "ref": source.source_id,
        }, transport)
        first = result
        fragments = [result["body"]]
        cursor = result["next_byte"]
        while cursor is not None:
            result = await bounded_inspection_plane(edge, authority, {
                "binding_id": authority.binding_id, "ref": source.source_id, "byte_start": cursor,
            }, transport)
            assert result["byte_start"] == cursor < result["byte_end"]
            fragments.append(result["body"])
            cursor = result["next_byte"]
        assert "".join(fragments) == body
        assert result["byte_end"] == len(body.encode())
        assert result["source_id"] == source.source_id
        assert result["judgment_required"] is True
        from test_edge_boundaries import record_request

        arguments = {
            "kind": "source_selection", "binding_id": authority.binding_id,
            "idempotency_key": "minimum-grounded-source", "source_id": source.source_id,
            **{field: first[field] for field in (
                "admission_id", "source_revision", "binding_revision", "snapshot",
                "byte_start", "byte_end", "window_digest", "policy_revision", "policy_epoch",
            )},
            "label": "remember", "coverage": "complete_window",
            "reason": "The complete original states that CacheKey is retained offline.",
            "extraction": {
                "claims": [{
                    "assertion_id": "a0000", "assertion_span_id": first["span_inventory"][0]["span_id"],
                    "statement": body, "kind": "fact", "subject": "CacheKey",
                    "predicate": "retained", "object": "offline", "polarity": "positive",
                    "modality": "asserted", "entities": ["CacheKey"],
                }],
                "individual_qualifications": [], "shared_qualifications": [],
                "validities": [], "unused_span_ids": [],
            },
        }
        _, published = await record_request(edge, arguments, transport)
        assert published.get("state") == "candidate_ready", published
