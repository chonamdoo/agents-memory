from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agents_memory.domain import CaptureCoverage, DomainError, RecordCommand, Source
from agents_memory.selection import (
    RECORD_ADAPTER,
    SourceSelectionCommand,
    resolve_selection,
    selection_contract_revision,
    source_window,
    window_digest,
)
from agents_memory.semantic_contract import GeneratedExtraction


def source(body="CacheKey stays offline.", **changes):
    return Source.model_validate({
        "id": "source_company", "binding_id": "binding_company", "realm": "company_test",
        "revision": 1, "body": body, "speaker": "human", "origin_key": "synthetic-event",
        "root_run_id": None, "snapshot": None, "event_time": None,
        "recorded_at": datetime(2026, 10, 13, tzinfo=UTC),
        "coverage": CaptureCoverage(status="observed_window"), **changes,
    })


def generated(statement="CacheKey stays offline.", **changes):
    assertion = {
        "assertion_id": "a0000", "assertion_span_id": "s0000", "statement": statement,
        "kind": "fact", "subject": "CacheKey", "predicate": "stays", "object": "offline",
        "polarity": "positive", "modality": "asserted", "entities": ("CacheKey",),
    }
    assertion.update(changes.pop("assertion", {}))
    return GeneratedExtraction.model_validate({
        "claims": (assertion,), "individual_qualifications": (), "shared_qualifications": (),
        "validities": (), "unused_span_ids": (), **changes,
    })


def judgment(original, *, start=0, max_bytes=4096, **changes):
    revision = selection_contract_revision()
    window = source_window(original, start, max_bytes, 1, revision, 7)
    return SourceSelectionCommand.model_validate({
        "kind": "source_selection", "binding_id": original.binding_id,
        "idempotency_key": "synthetic-judgment", "source_id": original.id,
        "admission_id": "admission_inspected", "reason": "Caller checked the exact original window.",
        "source_revision": original.revision, "binding_revision": 1, "snapshot": original.snapshot,
        "byte_start": window["byte_start"], "byte_end": window["byte_end"],
        "window_digest": window["window_digest"], "policy_revision": revision,
        "policy_epoch": 7, "label": "remember", "coverage": "complete_window", **changes,
    })


def resolve(request, original):
    return resolve_selection(request, original, 1, selection_contract_revision(), 7)


def test_repeated_korean_window_cites_the_selected_original_occurrence():
    prefix = "한글 CacheKey stays offline. "
    original = source(prefix + "CacheKey stays offline.")
    request = judgment(original, start=len(prefix.encode()), extraction=generated())
    draft = resolve(request, original).claims[0]
    assert draft.evidence[0].byte_start == len(prefix.encode())
    assert draft.evidence[0].quote == "CacheKey stays offline."
    offset = draft.evidence[0].byte_start
    assert offset is not None
    assert original.body.encode()[offset:offset + len(draft.evidence[0].quote.encode())] == draft.evidence[0].quote.encode()


@pytest.mark.parametrize(("start", "budget"), [(1, 4096), (0, 1), (-1, 4096), (0, True), (False, 4096), (0, "1024")])
def test_invalid_utf8_window_or_untyped_bounds_are_refused(start, budget):
    with pytest.raises(DomainError) as caught:
        source_window(source("한글 CacheKey."), start, budget, 1, None, None)
    assert caught.value.code == "SOURCE_WINDOW_INVALID"


def test_window_continuation_does_not_claim_whole_source_or_caller_consumption():
    original = source("한글 CacheKey stays offline.")
    first = source_window(original, 0, 5, 1, None, None)
    assert first["body"] == "한"
    assert first["byte_end"] == first["next_byte"] == 3
    assert first["partial"] is True
    assert first["coverage"]["omitted_suffix_bytes"] == len(original.body.encode()) - 3
    assert first["coverage"]["caller_consumption"] == "unobserved"
    second = source_window(original, first["next_byte"], 4096, 1, None, None)
    assert first["body"] + second["body"] == original.body
    assert second["source_event_time"] is None
    assert second["source_recorded_at"] == original.recorded_at.isoformat()


@pytest.mark.parametrize("coverage", [CaptureCoverage(), CaptureCoverage(status="truncated", original_bytes=200), CaptureCoverage(status="observed_window", gaps=("native_prompt_unobserved",)), CaptureCoverage(status="observed_window", original_bytes=200)])
def test_complete_stored_window_does_not_erase_capture_gaps(coverage):
    window = source_window(source(coverage=coverage), 0, 4096, 1, None, None)
    assert window["next_byte"] is None
    assert window["partial"] is True
    assert window["coverage"]["capture"] == coverage.model_dump(mode="json")


@pytest.mark.parametrize("statement", ["CacheKey uses 999.", "OtherKey stays offline."])
def test_caller_draft_cannot_invent_numbers_or_identifiers(statement):
    original = source()
    with pytest.raises(DomainError) as caught:
        resolve(judgment(original, extraction=generated(statement)), original)
    assert caught.value.code == "SELECTION_GROUNDING_INVALID"


def test_caller_validity_cannot_use_an_unobserved_timestamp():
    original = source()
    extraction = generated(validities=({
        "assertion_ids": ("a0000",), "evidence_span_ids": ("s0000",),
        "valid_from": datetime(2099, 1, 1, tzinfo=UTC), "valid_until": None,
    },))
    with pytest.raises(DomainError) as caught:
        resolve(judgment(original, extraction=extraction), original)
    assert caught.value.code == "SELECTION_GROUNDING_INVALID"


def test_nearby_original_condition_and_exception_remain_grounded():
    original = source("CacheKey stays offline.\nOnly company projects. Except anonymized fixtures.")
    extraction = generated(individual_qualifications=(
        {"kind": "condition", "phrase": "Only company projects", "evidence_span_id": "s0001", "assertion_id": "a0000"},
        {"kind": "exception", "phrase": "Except anonymized fixtures", "evidence_span_id": "s0002", "assertion_id": "a0000"},
    ))
    draft = resolve(judgment(original, extraction=extraction), original).claims[0]
    assert draft.conditions == ("Only company projects",)
    assert draft.exceptions == ("Except anonymized fixtures",)
    assert {quote.quote for quote in draft.evidence} == {
        "CacheKey stays offline.", "Only company projects.", "Except anonymized fixtures.",
    }


def test_omitted_span_inventory_is_not_a_successful_caller_extraction():
    original = source("CacheKey stays offline. OtherKey remains local.")
    with pytest.raises(DomainError) as caught:
        resolve(judgment(original, extraction=generated()), original)
    assert caught.value.code == "SELECTION_GROUNDING_INVALID"


@pytest.mark.parametrize("label", ["discard", "review"])
def test_nonpublication_judgment_cannot_carry_claim_drafts(label):
    with pytest.raises(ValidationError):
        judgment(source(), label=label, extraction=generated())


@pytest.mark.parametrize("field", ["speaker", "source_recorded_at", "realm", "approved", "model_revision"])
def test_caller_union_cannot_declare_source_or_execution_authority(field):
    payload = judgment(source()).model_dump(mode="json")
    payload[field] = "caller-fabricated-authority"
    with pytest.raises(ValidationError):
        RECORD_ADAPTER.validate_json(json.dumps(payload), strict=True)


@pytest.mark.parametrize("changes", [{"revision": 2}, {"speaker": "agent_note"}, {"event_time": datetime(2020, 1, 1, tzinfo=UTC)}])
def test_original_source_revision_and_provenance_changes_invalidate_window(changes):
    original = source()
    request = judgment(original, extraction=generated())
    with pytest.raises(DomainError) as caught:
        resolve(request, original.model_copy(update=changes))
    assert caught.value.code == "SELECTION_STALE"


@pytest.mark.parametrize("changes", [{"state": "retracted"}, {"speaker": "memory"}, {"body": "[agents-memory:bounded-context] CacheKey stays offline."}])
def test_inactive_or_retrieved_memory_cannot_publish_new_caller_candidates(changes):
    original = source()
    request = judgment(original, extraction=generated())
    with pytest.raises(DomainError) as caught:
        resolve(request, original.model_copy(update=changes))
    assert caught.value.code == "SOURCE_INELIGIBLE"


DENSE_BODIES = ("a\n" * 300, "Go. " * 300, '"\\' * 2048, "가. " * 2000)


@pytest.mark.parametrize("body", DENSE_BODIES)
@pytest.mark.parametrize("response_bytes", [4096, 16384])
def test_dense_window_shrinks_within_span_and_response_bounds_with_continuation(body, response_bytes):
    original = source(body)
    windows, cursor = [], 0
    while cursor is not None and len(windows) <= len(body.encode()):
        window = source_window(original, cursor, 4096, 1, None, None, representation_bytes=(response_bytes - 2048) // 2)
        assert window["byte_start"] == cursor < window["byte_end"]
        assert 0 < len(window["span_inventory"]) <= 128
        text = json.dumps(window, ensure_ascii=False, separators=(",", ":"))
        assert len(json.dumps(text).encode("ascii")) < response_bytes
        windows.append(window)
        cursor = window["next_byte"]
    assert len(windows) > 1 and windows[-1]["next_byte"] is None
    assert "".join(window["body"] for window in windows) == body
    assert all(window["partial"] for window in windows)


def test_window_that_cannot_fit_the_response_bound_is_an_explicit_window_error():
    with pytest.raises(DomainError) as caught:
        source_window(source(), 0, 4096, 1, None, None, metadata={"pending_corrections": ["x" * 16384]})
    assert caught.value.code == "SOURCE_WINDOW_TOO_LARGE"


def test_caller_window_beyond_the_span_bound_is_a_window_error():
    original = source("CacheKey stays offline.\n" + "a\n" * 200)
    end, revision = len(original.body.encode()), selection_contract_revision()
    request = judgment(
        original, byte_end=end, window_digest=window_digest(original, 0, end, 1, revision, 7),
        extraction=generated(),
    )
    with pytest.raises(DomainError) as caught:
        resolve(request, original)
    assert caught.value.code == "SOURCE_WINDOW_TOO_LARGE"




def test_record_union_defaults_a_kindless_payload_to_the_note_command():
    command = RECORD_ADAPTER.validate_json(json.dumps({"idempotency_key": "kindless", "body": "note"}), strict=True)
    assert isinstance(command, RecordCommand) and command.kind == "note"
    payload = judgment(source()).model_dump(mode="json")
    payload.pop("kind")
    with pytest.raises(ValidationError):
        RECORD_ADAPTER.validate_json(json.dumps(payload), strict=True)


def test_scoped_request_can_select_an_unscoped_original():
    original = source()
    request = judgment(original, snapshot="request-scope", extraction=generated())
    assert resolve(request, original).claims[0].statement == "CacheKey stays offline."
    window = source_window(original, 0, 4096, 1, selection_contract_revision(), 7, request_snapshot="request-scope")
    assert window["snapshot"] == "request-scope" and window["source_snapshot"] is None


def test_scoped_original_still_requires_its_matching_request_snapshot():
    original = source(snapshot="source-scope")
    with pytest.raises(DomainError) as caught:
        resolve(judgment(original, snapshot="other-scope", extraction=generated()), original)
    assert caught.value.code == "SELECTION_STALE"


def test_rejection_review_references_are_bounded_and_distinct():
    with pytest.raises(ValidationError):
        judgment(source(), rejection_review_ids=("review_one", "review_one"))
    with pytest.raises(ValidationError):
        judgment(source(), rejection_review_ids=tuple(f"review_{index}" for index in range(17)))
    assert judgment(source(), rejection_review_ids=tuple(f"review_{index}" for index in range(16)))


@pytest.mark.parametrize("input_kind", ("capture", "record", "feedback", "origin", "judgment"))
def test_source_input_rejects_private_keys_before_authority_fingerprinting(input_kind):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

    from agents_memory.domain import CaptureCommand, FeedbackCommand
    secret = Ed25519PrivateKey.generate().private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
    with pytest.raises(DomainError) as refused:
        if input_kind == "capture":
            CaptureCommand(binding_id="binding_company", idempotency_key="secret-test", origin_key="secret-test",
                body=secret, speaker="human")
        elif input_kind == "record":
            RecordCommand(binding_id="binding_company", idempotency_key="secret-test", body=secret)
        elif input_kind == "feedback":
            FeedbackCommand(binding_id="binding_company", idempotency_key="secret-test", target_ref="source_company",
                kind="reject", body=secret)
        elif input_kind == "origin":
            CaptureCommand(binding_id="binding_company", idempotency_key="secret-test", origin_key=secret,
                body="CacheKey stays offline.", speaker="human")
        else:
            judgment(source(), extraction=generated(statement=secret))
    assert refused.value.code == "SOURCE_SECRET_REJECTED"
    assert refused.value.status == 422 and refused.value.effect.value == "not_started"
    assert secret not in json.dumps(refused.value.public())


def test_benign_credential_code_example_is_not_rewritten_as_a_source():
    from agents_memory.domain import CaptureCommand
    body = "api_key = os.environ['API_KEY']; never embed credentials in source code."
    captured = CaptureCommand(binding_id="binding_company", idempotency_key="code-example",
        origin_key="code-example", body=body, speaker="document")
    assert captured.body == body


def test_missing_rejection_reason_is_not_an_implicit_delete_or_discard():
    from agents_memory.domain import FeedbackCommand
    with pytest.raises(ValidationError):
        FeedbackCommand(binding_id="binding_company", idempotency_key="reject", target_ref="source_company", kind="reject")


@pytest.mark.parametrize("reason", ("", " ", "\n\t"))
def test_selection_reason_requires_content_without_rewriting_source(reason):
    with pytest.raises(ValidationError):
        judgment(source(), reason=reason)


@pytest.mark.parametrize("input_kind", ("query", "expansion", "relevance"))
def test_read_judgment_inputs_reject_private_keys_before_request_fingerprinting(input_kind):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

    from agents_memory.domain import ContextCommand, RelevanceJudgment
    secret = Ed25519PrivateKey.generate().private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
    with pytest.raises(DomainError) as refused:
        if input_kind == "query":
            ContextCommand(query=secret)
        elif input_kind == "expansion":
            ContextCommand(query="CacheKey", query_expansions=(secret,))
        else:
            RelevanceJudgment(claim_id="claim_example", relevant=False, reason=secret)
    assert refused.value.code == "SOURCE_SECRET_REJECTED"
    assert secret not in json.dumps(refused.value.public())


@pytest.mark.parametrize("field", ("source_revision", "binding_revision", "byte_start", "byte_end", "policy_epoch"))
@pytest.mark.parametrize("value", (True, "1", 1.0))
def test_source_judgment_fence_integers_are_not_coerced(field, value):
    with pytest.raises(ValidationError):
        judgment(source(), **{field: value})
