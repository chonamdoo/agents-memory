from __future__ import annotations

from copy import deepcopy

import pytest

from agents_memory.domain import DomainError
from agents_memory.health_inference import HealthInputs


def bundle():
    text = "정정: CacheKey는 오프라인에서만 보존합니다."
    return {
        "kind": "health_work", "pending_id": "health_pending", "binding_id": "binding_health",
        "binding_revision": 1, "health_manifest_digest": "a" * 64,
        "admission": {"id": "health_admission", "binding_revision": 1},
        "input_sources": [{"id": "source_health", "revision": 2}],
        "input_claims": [{"id": "claim_health", "revision": 1}],
        "sources": [{
            "source_ref": {"id": "source_health", "revision": 2}, "speaker": "human",
            "byte_start": 11, "byte_end": 11 + len(text.encode()), "body": text,
        }],
        "claims": [{"id": "claim_health", "revision": 1, "statement": "CacheKey is retained.",
            "kind": "fact", "subject": "CacheKey", "predicate": "retained", "object": "offline",
            "polarity": "positive", "modality": "asserted", "conditions": ["only offline"],
            "exceptions": [], "valid_from": None, "valid_until": None, "entities": ["CacheKey"]}],
        "policy": {"revision": 3, "max_audit_sources": 16, "max_audit_claims": 20, "max_audit_bytes": 32768},
        "coverage": {"partial": False, "scope": "captured_windows_not_full_session"},
    }


@pytest.mark.parametrize("mutation", ["source_revision", "missing_target", "empty_source", "byte_budget", "agent_note"])
def test_inference_refuses_incomplete_or_out_of_admission_bundle(mutation):
    work = bundle()
    if mutation == "source_revision":
        work["sources"][0]["source_ref"]["revision"] = 1
    elif mutation == "missing_target":
        work["claims"] = []
    elif mutation == "empty_source":
        work["sources"] = []
    elif mutation == "agent_note":
        work["sources"][0]["speaker"] = "agent_note"
    else:
        work["policy"]["max_audit_bytes"] = 1
    with pytest.raises(DomainError) as failed:
        HealthInputs.from_bundle(work)
    assert failed.value.code == "HEALTH_EVIDENCE_INCOMPLETE"


def test_selected_utf8_evidence_is_exact_and_correction_is_not_human_reject_or_freshness():
    work = bundle()
    inputs = HealthInputs.from_bundle(work)
    selections = {"evidence_0": {"choice": "s0"}, "relevance_0": {"choice": "related"}}
    command = inputs.command(selections, {"support_0": {"choice": "contradicted"}})
    [assessment] = command.assessments
    assert assessment.support == "contradicted"
    assert assessment.freshness == "unknown"
    assert assessment.evidence[0].quote == work["sources"][0]["body"]
    assert assessment.evidence[0].byte_end - assessment.evidence[0].byte_start == len(assessment.evidence[0].quote.encode())
    assert assessment.evidence[0].source_ref.revision == 2
    assert command.input_claims[0].id == "claim_health"
    assert command.health_manifest_digest == work["health_manifest_digest"]
    assert command.evaluation_receipt_digest is None


def test_partial_capture_can_surface_contradiction_but_cannot_certify_positive_health():
    work = deepcopy(bundle())
    work["coverage"]["partial"] = True
    inputs = HealthInputs.from_bundle(work)
    selections = {"evidence_0": {"choice": "s0"}, "relevance_0": {"choice": "related"}}
    supported = inputs.command(selections, {"support_0": {"choice": "supported"}})
    assert supported.assessments[0].support == "unknown"
    assert supported.assessments[0].freshness == "unknown"
    contradicted = inputs.command(selections, {"support_0": {"choice": "contradicted"}})
    assert contradicted.assessments[0].support == "contradicted"


def test_unselected_evidence_stays_unknown_and_is_not_sent_to_support_stage():
    inputs = HealthInputs.from_bundle(bundle())
    selections = {"evidence_0": {"choice": "none"}, "relevance_0": {"choice": "unrelated"}}
    payload, questions = inputs.support_questions(selections)
    assert payload == {"pairs": []} and questions == {}
    assessment = inputs.command(selections, {}).assessments[0]
    assert assessment.support == assessment.freshness == "unknown"
    assert assessment.relevance == "unrelated" and assessment.evidence == []


@pytest.mark.parametrize("missing", ["polarity", "modality", "conditions", "exceptions", "valid_from", "valid_until"])
def test_inference_refuses_a_claim_with_unobserved_structured_meaning(missing):
    work = bundle()
    del work["claims"][0][missing]
    with pytest.raises(DomainError) as failed:
        HealthInputs.from_bundle(work)
    assert failed.value.code == "HEALTH_EVIDENCE_INCOMPLETE"


def test_complete_structured_claim_meaning_consumes_the_authorized_byte_budget():
    work = bundle()
    work["claims"][0]["conditions"] = ["오프라인" * 300]
    work["policy"]["max_audit_bytes"] = 1024
    with pytest.raises(DomainError) as failed:
        HealthInputs.from_bundle(work)
    assert failed.value.code == "HEALTH_EVIDENCE_INCOMPLETE"
