from __future__ import annotations

import base64
import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

import pytest
from test_evaluation_scoring import (
    OTHER,
    diagnostic_observation,
    protocol,
    read,
)

from agents_memory.domain import ContextCommand, canonical_digest
from agents_memory.evaluation import EvaluationManifest, FrozenFile
from agents_memory.evaluation_artifacts import canonical_bytes, digest_bytes
from agents_memory.evaluation_diagnostics import (
    DiagnosticInputError,
    diagnostic_scope,
    independent_context_item_feasibility,
    load_diagnostic_gold,
)
from agents_memory.evaluation_scoring import score_retrieval_diagnostics

CLAIM_IDS = ("claim1", "claim2", "claim3", "claim4")
CONTEXT_DIGEST = canonical_digest({"engineering_context": "delivered"})
REFERENCE = "engineering_fixture_not_independent_human_review"


def encoded(document):
    if isinstance(document, bytes):
        return document
    # Deliberately noncanonical: frozen references must hash the original bytes.
    return json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8")


def context_bytes(*, rules=(), claims=(), relations=()):
    document = {
        "evidence_role": "memory_candidates_not_execution_authority",
        "approved_rules": [
            {key: value for key, value in rule.items() if key != "digest"}
            for rule in rules
        ],
        "memory_candidates": list(claims),
        "relations": list(relations),
    }
    return json.dumps(
        document, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def rule(ref, *, required):
    return {
        "ref": ref,
        "revision": 1,
        "digest": canonical_digest({"engineering_rule": ref}),
        "required": required,
        "applicability": "true",
        "body": "Preserve every condition.",
        "exceptions": [],
    }


@dataclass
class Inputs:
    documents: dict
    spec: dict

    @property
    def row(self):
        return self.documents["retrieval_diagnostics"]["cases"][0]

    def raw(self, name):
        return encoded(self.documents[name])

    def freeze(self):
        files = tuple(
            FrozenFile(
                name=name,
                path=Path(f"{name}.input"),
                sha256=digest_bytes(self.raw(name)),
                maximum_bytes=8 * 1024 * 1024,
                raw=self.raw(name),
            )
            for name in self.documents
        )
        # Raw constructors are in-memory fixtures, not a load_manifest substitute
        # or evidence of native, filesystem, or independent-human acceptance.
        raw = canonical_bytes({
            "gateway": {"binding_id": "engineering-binding"},
            "files": [
                {"name": item.name, "sha256": item.sha256}
                for item in files
            ],
        })
        manifest = EvaluationManifest(
            path=Path("manifest.json"),
            digest=digest_bytes(raw),
            raw=raw,
            files=files,
        )
        spec = deepcopy(self.spec)
        spec["manifest_digest"] = manifest.digest
        for name, field in (
            ("corpus", "corpus_digest"),
            ("gold", "gold_digest"),
            ("rules", "required_rules_digest"),
            ("workload", "workload_digest"),
        ):
            spec[field] = manifest.file(name).sha256
        return manifest, spec

    def rehash_packing(self):
        budget_digest = digest_bytes(self.raw("packing"))
        self.row["budget"]["sha256"] = budget_digest
        for scope in (
            self.row["scope"], self.row["eligibility"]["scope"],
            *(judgment["scope"] for judgment in self.row["judgments"]),
        ):
            scope["budget_digest"] = budget_digest

    def observe(self, manifest, spec, *, returned=("claim1",)):
        scope = diagnostic_scope(manifest, spec, "case0")
        claims = {
            item["ref"]: item for item in self.documents["packing"]["claims"]
        }
        case = spec["retrieval_cases"][0]
        retrieval = read(
            manifest_digest=manifest.digest,
            returned_claim_ids=list(returned),
            final_context_digest=CONTEXT_DIGEST,
            grounding_refs=case["grounding_refs"],
        )
        return diagnostic_observation(
            returned=returned,
            candidates=tuple(case["relevant_claim_ids"]),
            retrieval=retrieval,
            scope=scope.model_dump(mode="json"),
            final_claims=[
                {
                    "claim_id": ref,
                    "claim_digest": canonical_digest(claims[ref]),
                    "complete": True,
                }
                for ref in returned
            ],
        )


def make_inputs(
    *,
    relevant=CLAIM_IDS,
    budget_complete=True,
    source_mapping_digest=None,
    include_secondary_evidence=False,
    applicable_rules=(),
    relations=(),
):
    quote = "한국어 조건을 보존한다."
    body = quote.encode("utf-8")
    span = {
        "source_id": "source1",
        "revision": 1,
        "byte_start": 0,
        "byte_end": len(body),
        "quote_digest": digest_bytes(body),
    }
    claims = [
        {
            "ref": ref,
            "interpretation_role": "model_derived_candidate",
            "statement": f"{ref}: 조건을 보존한다.",
            "polarity": "positive",
            "modality": "asserted",
            "conditions": ["오프라인인 경우"],
            "exceptions": [],
            "evidence": [{
                "source": "source1",
                "revision": 1,
                "source_speaker": "document",
                "source_event_time": None,
                "source_recorded_at": "2026-10-01T00:00:00Z",
                "bytes": [0, len(body)],
                "quote": quote,
            }],
            "snapshot": "snapshot1",
        }
        for ref in (*CLAIM_IDS, "decoy")
    ]
    if include_secondary_evidence:
        for claim in claims:
            claim["evidence"].append({
                "source": "source2",
                "revision": 7,
                "source_speaker": "user",
                "source_event_time": "2026-09-30T00:00:00Z",
                "source_recorded_at": "2026-10-01T00:00:00Z",
                "bytes": [0, len(body)],
                "quote": quote,
            })
    rules = sorted(deepcopy(list(applicable_rules)), key=lambda rule: (not rule["required"], rule["ref"], rule["revision"]))
    edges = sorted(deepcopy(list(relations)), key=lambda edge: edge["ref"])
    spec = protocol()
    case = spec["retrieval_cases"][0]
    case.update(
        relevant_claim_ids=list(relevant),
        irrelevant_claim_ids=["decoy"],
        grounding_refs=[span],
    )
    request = ContextCommand(
        binding_id="engineering-binding",
        query="한국어 조건",
        max_bytes=6144,
        limit=3,
    ).model_dump(mode="json", exclude={"admission_id", "relevance"})
    corpus = {
        "schema": 2,
        "sources": [{
            "source_id": "source1",
            "revision": 1,
            "body": base64.b64encode(body).decode("ascii"),
        }],
        "relations": [{
            "ref": edge["ref"],
            "projection": {
                "id": edge["ref"], "kind": "relation", "state": "active",
                "left_id": edge["left"], "right_id": edge["right"],
                "relation_kind": edge["kind"],
                "interpretation_role": "caller_judged_relation",
                "awaiting_revalidation": False,
            },
        } for edge in edges],
        "claims": [
            {
                "ref": claim["ref"],
                "projection": {
                    "id": claim["ref"],
                    "kind": "claim",
                    "state": "active",
                    "revision": 1,
                    "statement": claim["statement"],
                    "snapshot": claim["snapshot"],
                    "interpretation_role": claim["interpretation_role"],
                    "input_source_ids": sorted({item["source"] for item in claim["evidence"]}),
                    "selection_id": "selection1",
                    "policy_revision": 1,
                    "awaiting_revalidation": False,
                    "judgment_context_refs": [],
                    "draft": {
                        "statement": claim["statement"],
                        "kind": "fact",
                        "subject": claim["ref"],
                        "predicate": "preserves",
                        "object": "conditions",
                        "polarity": claim["polarity"],
                        "modality": claim["modality"],
                        "conditions": list(claim["conditions"]),
                        "exceptions": list(claim["exceptions"]),
                        "valid_from": None,
                        "valid_until": None,
                        "entities": [],
                    },
                    "evidence": [{
                        "source_id": item["source"],
                        "source_revision": item["revision"],
                        "source_speaker": item["source_speaker"],
                        "source_event_time": item["source_event_time"],
                        "source_recorded_at": item["source_recorded_at"],
                        "byte_start": item["bytes"][0],
                        "byte_end": item["bytes"][1],
                        "quote": item["quote"],
                    } for item in claim["evidence"]],
                },
            }
            for claim in claims
        ],
    }
    if include_secondary_evidence:
        corpus["sources"].append({
            "source_id": "source2", "revision": 7,
            "body": base64.b64encode(body).decode("ascii"),
        })
    documents = {
        "corpus": corpus,
        "gold": {
            "schema": 1,
            "independence": "provided_unattested",
            "cases": [deepcopy(case)],
        },
        "rules": {
            "schema": 2,
            "rules": [[rule["ref"], rule["revision"], rule["digest"]] for rule in rules if rule["required"]],
            "probe": {"query": "a" * 64, "max_bytes": 6144, "limit": 5},
            "applicable": deepcopy(rules),
        },
        "workload": {
            "retrieval": [{"case_id": "case0", "request": request}],
        },
        "quality_rubric": {
            "schema": 1,
            "definition": (
                "Engineering labels describe assertion preservation, condition "
                "omission, and promotion in the exact delivered context."
            ),
        },
    }
    selected_ids = set(relevant) | {"decoy"}
    mapping = {
        "case": documents["gold"]["cases"][0],
        "claims": [
            claim for claim in corpus["claims"] if claim["ref"] in selected_ids
        ],
        "sources": corpus["sources"],
    }
    documents["source_scope"] = {
        "schema": 1,
        "case_id": "case0",
        "corpus_digest": digest_bytes(encoded(documents["corpus"])),
        "gold_digest": digest_bytes(encoded(documents["gold"])),
        "request_digest": canonical_digest(request),
        "source_mapping_digest": (
            canonical_digest(mapping)
            if source_mapping_digest is None else source_mapping_digest
        ),
    }
    source_digest = digest_bytes(encoded(documents["source_scope"]))
    documents["packing"] = {
        "schema": 1,
        "case_id": "case0",
        "corpus_digest": digest_bytes(encoded(documents["corpus"])),
        "required_rules_digest": digest_bytes(encoded(documents["rules"])),
        "request_digest": canonical_digest(request),
        "source_scope_digest": source_digest,
        "serializer": "context_json_utf8_v1",
        "independent_reference": REFERENCE,
        "complete": budget_complete,
        "max_bytes": 6144,
        "limit": 3,
        "transport_limits": {
            "maximum_context_bytes": 6144,
            "maximum_item_bytes": 6144,
            "wire_deliverability_proven": False,
        },
        "rules": deepcopy(rules),
        "claims": claims,
        "relations": deepcopy(edges),
    }
    scope = {
        "corpus_digest": digest_bytes(encoded(documents["corpus"])),
        "gold_digest": digest_bytes(encoded(documents["gold"])),
        "required_rules_digest": digest_bytes(encoded(documents["rules"])),
        "request_digest": canonical_digest(request),
        "budget_digest": digest_bytes(encoded(documents["packing"])),
        "source_scope_digest": source_digest,
    }
    rubric_digest = digest_bytes(encoded(documents["quality_rubric"]))
    documents["retrieval_diagnostics"] = {
        "schema": 1,
        "independence": "provided_unattested",
        "cases": [{
            "case_id": "case0",
            "cluster_id": "family0",
            "scope": scope,
            "budget": {"name": "packing", "sha256": scope["budget_digest"]},
            "source_scope": {
                "name": "source_scope", "sha256": source_digest,
            },
            "rubric": {"name": "quality_rubric", "sha256": rubric_digest},
            "eligibility": {
                "scope": deepcopy(scope),
                "independent_reference": REFERENCE,
                "evidence_digest": canonical_digest({
                    "engineering_eligibility": list(relevant),
                }),
                "complete": True,
                "eligible_claim_ids": list(relevant),
                "ineligible_claim_ids": [],
            },
            "judgments": [
                {
                    "scope": deepcopy(scope),
                    "claim_id": ref,
                    "expected_claim_digest": canonical_digest(
                        next(claim for claim in claims if claim["ref"] == ref),
                    ),
                    "definition_digest": rubric_digest,
                    "independent_reference": REFERENCE,
                    "evidence_digest": canonical_digest({
                        "engineering_label": ref,
                    }),
                    "phase": "frozen_claim",
                    "gold_assertion_preserved": True,
                    "condition_omission": False,
                }
                for ref in relevant[:1]
            ],
        }],
    }
    return Inputs(documents, spec)


@pytest.fixture
def inputs():
    return make_inputs()


def scored(spec, supplements, observation):
    return score_retrieval_diagnostics(
        spec, supplements.gold, [observation],
    )["observations"][0]


def adjudication_for(inputs, manifest, spec):
    scope = diagnostic_scope(manifest, spec, "case0").model_dump(mode="json")
    judgment = {
        **deepcopy(inputs.row["judgments"][0]),
        "scope": deepcopy(scope),
        "phase": "post_run_adjudication",
        "expected_final_context_digest": CONTEXT_DIGEST,
        "gold_assertion_preserved": False,
        "condition_omission": True,
        "false_promotion": True,
    }
    return {
        "schema": 1,
        "manifest_digest": manifest.digest,
        "independence": "provided_unattested",
        "cases": [{
            "case_id": "case0",
            "scope": scope,
            "quality_definition_digest": inputs.row["rubric"]["sha256"],
            "judgments": [judgment],
        }],
    }


def test_required_rules_reserve_bytes_without_consuming_shared_three_slots(inputs):
    problem = deepcopy(inputs.documents["packing"])
    required = rule("required1", required=True)
    problem["rules"] = [required]
    roomy = independent_context_item_feasibility(problem, CLAIM_IDS)
    assert roomy.complete is True
    assert roomy.maximum_relevant == 3

    problem["max_bytes"] = len(context_bytes(
        rules=[required], claims=[problem["claims"][0]],
    ))
    reserved = independent_context_item_feasibility(problem, CLAIM_IDS)
    assert reserved.complete is True
    assert reserved.maximum_relevant == 1
    assert reserved.maximizing_claim_ids == ("claim1",)

    problem["rules"][0]["body"] = "x" * 6144
    problem["max_bytes"] = 6144
    impossible = independent_context_item_feasibility(problem, CLAIM_IDS)
    assert impossible.complete is True
    assert impossible.maximum_relevant == 0


@pytest.mark.parametrize("optional_count,maximum", [(0, 3), (1, 2), (3, 0)])
def test_optional_rules_compete_with_claims_for_shared_three_slots(
    inputs, optional_count, maximum,
):
    problem = deepcopy(inputs.documents["packing"])
    problem["rules"] = [
        rule(f"optional{index}", required=False)
        for index in range(optional_count)
    ]
    result = independent_context_item_feasibility(problem, CLAIM_IDS)
    assert result.complete is True
    assert result.maximum_relevant == maximum
    assert result.maximizing_claim_ids == CLAIM_IDS[:maximum]


def test_korean_context_fits_at_exact_utf8_byte_boundary_not_one_byte_below(inputs):
    problem = deepcopy(inputs.documents["packing"])
    claim = problem["claims"][0]
    exact = len(context_bytes(claims=[claim]))
    problem["max_bytes"] = exact
    fits = independent_context_item_feasibility(problem, ("claim1",))
    assert fits.complete is True
    assert fits.maximum_relevant == 1

    problem["max_bytes"] = exact - 1
    misses = independent_context_item_feasibility(problem, ("claim1",))
    assert misses.complete is True
    assert misses.maximum_relevant == 0
    assert misses.maximizing_claim_ids == ()


def test_touching_relations_include_both_directions_but_not_unrelated_edges(inputs):
    problem = deepcopy(inputs.documents["packing"])
    edges = [
        {"ref": "edge1", "left": "claim1", "right": "claim2", "kind": "supports"},
        {"ref": "edge2", "left": "claim3", "right": "claim1", "kind": "qualifies"},
        {"ref": "edge3", "left": "claim2", "right": "claim3", "kind": "supports"},
    ]
    problem["relations"] = edges
    closure = [
        {**edge, "endpoints_in_context": ["claim1"]}
        for edge in edges[:2]
    ]
    exact = len(context_bytes(
        claims=[problem["claims"][0]], relations=closure,
    ))
    problem["max_bytes"] = exact
    fits = independent_context_item_feasibility(problem, ("claim1",))
    assert fits.maximum_relevant == 1

    problem["max_bytes"] = exact - 1
    misses = independent_context_item_feasibility(problem, ("claim1",))
    assert misses.complete is True
    assert misses.maximum_relevant == 0

    problem["relations"] = []
    without_closure = independent_context_item_feasibility(problem, ("claim1",))
    assert without_closure.maximum_relevant == 1


def test_exhausted_enumeration_returns_unknown_not_a_lower_bound(inputs):
    result = independent_context_item_feasibility(
        inputs.documents["packing"], CLAIM_IDS, max_evaluations=1,
    )
    assert result.complete is False
    assert result.maximum_relevant is None
    assert result.maximizing_claim_ids == ()
    assert result.reason == "PACKING_WORK_EXHAUSTED"


def test_raw_digest_chain_is_projected_into_actual_manifest_scope(inputs):
    raw_eligibility = inputs.row["eligibility"]
    inputs.row["feasibility"] = {
        "scope": deepcopy(inputs.row["scope"]),
        "independent_reference": REFERENCE,
        "evidence_digest": canonical_digest({"engineering_packing": "supplied"}),
        "eligibility_input_digest": canonical_digest(raw_eligibility),
        "basis": "complete_independent_context_item_packing",
        "complete": True,
        "maximum_relevant": 3,
        "maximizing_claim_ids": list(CLAIM_IDS[:3]),
    }
    manifest, spec = inputs.freeze()
    scope = diagnostic_scope(manifest, spec, "case0")
    supplements = load_diagnostic_gold(manifest, spec)
    gold = supplements.gold[0]

    assert scope.model_dump(mode="json", exclude={"manifest_digest"}) == (
        inputs.row["scope"]
    )
    assert "manifest_digest" not in inputs.row["scope"]
    assert scope.manifest_digest == digest_bytes(manifest.raw)
    assert scope.budget_digest == digest_bytes(inputs.raw("packing"))
    assert scope.source_scope_digest == digest_bytes(inputs.raw("source_scope"))
    assert gold.quality_definition_digest == digest_bytes(
        inputs.raw("quality_rubric"),
    )
    assert gold.quality_definition_digest != canonical_digest(
        inputs.documents["quality_rubric"],
    )
    assert gold.scope == gold.eligibility.scope == gold.feasibility.scope == scope
    assert gold.judgments[0].scope == scope
    assert gold.feasibility.eligibility_digest == canonical_digest(
        gold.eligibility,
    )
    assert gold.feasibility.eligibility_digest != canonical_digest(
        raw_eligibility,
    )
    assert supplements.provenance() == {
        "frozen_input_digest": digest_bytes(inputs.raw("retrieval_diagnostics")),
        "adjudication_digest": None,
        "independence": "provided_unattested",
        "original_acceptance": False,
        "original18_completed": 0,
    }


def test_automatic_packing_uses_complete_inputs_not_observed_delivery(inputs):
    manifest, spec = inputs.freeze()
    supplements = load_diagnostic_gold(manifest, spec)
    result = scored(spec, supplements, inputs.observe(manifest, spec))
    assert supplements.gold[0].feasibility.maximum_relevant == 3
    assert result["delivered"] == result["complete_gold_hits"] == 1
    assert result["raw_gold_recall"] == 0.25
    assert result["feasible_coverage"] == pytest.approx(1 / 3)
    # Frozen assertion/condition labels do not invent a contextual promotion label.
    assert result["condition_omission"] == 0
    assert result["false_promotion"] is None
    assert result["false_promotion_unknown"] == 1


def test_incomplete_packing_input_remains_unknown_despite_a_delivered_hit():
    inputs = make_inputs(budget_complete=False)
    manifest, spec = inputs.freeze()
    supplements = load_diagnostic_gold(manifest, spec)
    result = scored(spec, supplements, inputs.observe(manifest, spec))
    assert supplements.gold[0].feasibility.complete is False
    assert supplements.gold[0].feasibility.maximum_relevant is None
    assert result["complete_gold_hits"] == 1
    assert result["feasible_maximum"] is result["feasible_coverage"] is None
    assert "FEASIBILITY_INCOMPLETE_OR_MISSING" in result["reasons"]


def test_complete_no_match_has_f_zero_without_becoming_perfect_coverage():
    inputs = make_inputs(relevant=())
    manifest, spec = inputs.freeze()
    supplements = load_diagnostic_gold(manifest, spec)
    result = scored(
        spec, supplements, inputs.observe(manifest, spec, returned=()),
    )
    assert supplements.gold[0].feasibility.complete is True
    assert supplements.gold[0].feasibility.maximum_relevant == 0
    assert result["no_match"] is True
    assert result["budget_impossible"] is False
    assert result["no_match_false_return"] is False
    assert result["candidate_recall_at_20"] is None
    assert result["eligible_recall"] is result["feasible_coverage"] is None


@pytest.mark.parametrize("missing", ["document", "eligibility", "quality"])
def test_missing_supplements_do_not_invent_eligibility_or_quality(inputs, missing):
    if missing == "document":
        del inputs.documents["retrieval_diagnostics"]
    elif missing == "eligibility":
        del inputs.row["eligibility"]
    else:
        inputs.row["judgments"] = []
        del inputs.row["rubric"]

    manifest, spec = inputs.freeze()
    supplements = load_diagnostic_gold(manifest, spec)
    result = scored(spec, supplements, inputs.observe(manifest, spec))

    if missing in {"document", "eligibility"}:
        assert result["eligible_gold"] is result["feasible_maximum"] is None
        assert result["candidate_recall_at_20"] is None
    else:
        assert result["eligible_gold"] == 4
        assert result["feasible_maximum"] == 3
    if missing in {"document", "quality"}:
        assert result["condition_omission"] is result["false_promotion"] is None
        assert result["complete_gold_hits"] is None
    assert result["feasible_coverage"] is None


def test_self_consistent_source_document_cannot_replace_actual_source_mapping():
    inputs = make_inputs(source_mapping_digest=OTHER)
    manifest, spec = inputs.freeze()
    with pytest.raises(DiagnosticInputError, match="DIAGNOSTIC_SOURCE_SCOPE"):
        load_diagnostic_gold(manifest, spec)


def test_rubric_reference_binds_original_bytes_not_equivalent_json(inputs):
    inputs.documents["quality_rubric"] = (
        b"\n" + inputs.raw("quality_rubric")
    )
    manifest, spec = inputs.freeze()
    with pytest.raises(DiagnosticInputError, match="DIAGNOSTIC_REFERENCE_DRIFT"):
        load_diagnostic_gold(manifest, spec)


@pytest.mark.parametrize(
    "mismatch,error",
    [
        ("witness_scope", "DIAGNOSTIC_WITNESS_SCOPE"),
        ("rubric_definition", "DIAGNOSTIC_RUBRIC_SCOPE"),
        ("eligibility_binding", "DIAGNOSTIC_RAW_ELIGIBILITY_BINDING"),
    ],
)
def test_mismatched_supplied_labels_are_rejected_not_repaired(
    inputs, mismatch, error,
):
    if mismatch == "witness_scope":
        inputs.row["eligibility"]["scope"]["request_digest"] = OTHER
    elif mismatch == "rubric_definition":
        inputs.row["judgments"][0]["definition_digest"] = OTHER
    else:
        inputs.row["feasibility"] = {
            "scope": deepcopy(inputs.row["scope"]),
            "independent_reference": REFERENCE,
            "evidence_digest": canonical_digest({"engineering_packing": "bad"}),
            "eligibility_input_digest": OTHER,
            "basis": "complete_independent_context_item_packing",
            "complete": True,
            "maximum_relevant": 3,
            "maximizing_claim_ids": list(CLAIM_IDS[:3]),
        }
    manifest, spec = inputs.freeze()
    with pytest.raises(DiagnosticInputError, match=error):
        load_diagnostic_gold(manifest, spec)


def test_supplied_postrun_labels_apply_only_with_exact_authority(inputs):
    # Build the document before removing the frozen label, so only postrun
    # adjudication can supply the observed quality result.
    inputs.row["judgments"], frozen_labels = [], inputs.row["judgments"]
    manifest, spec = inputs.freeze()
    inputs.row["judgments"] = frozen_labels
    post = adjudication_for(inputs, manifest, spec)
    inputs.row["judgments"] = []
    raw = encoded(post)

    supplements = load_diagnostic_gold(manifest, spec, adjudication=raw)
    result = scored(spec, supplements, inputs.observe(manifest, spec))
    assert supplements.adjudication_digest == digest_bytes(raw)
    assert supplements.independence == "provided_unattested"
    assert supplements.original_acceptance is False
    assert result["complete_gold_hits"] == 0
    assert result["feasible_coverage"] == 0
    assert result["condition_omission"] == result["false_promotion"] == 1


@pytest.mark.parametrize(
    "mismatch,error",
    [
        ("manifest", "DIAGNOSTIC_ADJUDICATION_MANIFEST"),
        ("case_scope", "DIAGNOSTIC_ADJUDICATION_SCOPE"),
        ("rubric", "DIAGNOSTIC_ADJUDICATION_SCOPE"),
        ("judgment_scope", "DIAGNOSTIC_ADJUDICATION_JUDGMENT"),
        ("definition", "DIAGNOSTIC_ADJUDICATION_JUDGMENT"),
        ("phase", "DIAGNOSTIC_ADJUDICATION_JUDGMENT"),
    ],
)
def test_postrun_authority_mismatch_is_refused(inputs, mismatch, error):
    manifest, spec = inputs.freeze()
    post = adjudication_for(inputs, manifest, spec)
    case = post["cases"][0]
    judgment = case["judgments"][0]
    if mismatch == "manifest":
        post["manifest_digest"] = OTHER
    elif mismatch == "case_scope":
        case["scope"]["request_digest"] = OTHER
    elif mismatch == "rubric":
        case["quality_definition_digest"] = OTHER
    elif mismatch == "judgment_scope":
        judgment["scope"]["budget_digest"] = OTHER
    elif mismatch == "definition":
        judgment["definition_digest"] = OTHER
    else:
        judgment["phase"] = "frozen_claim"

    with pytest.raises(DiagnosticInputError, match=error):
        load_diagnostic_gold(manifest, spec, adjudication=encoded(post))


@pytest.mark.parametrize("changed_actual", ["context", "claim"])
def test_late_actual_content_mismatch_leaves_postrun_quality_unknown(
    inputs, changed_actual,
):
    frozen_label = inputs.row["judgments"][0]
    inputs.row["judgments"] = []
    manifest, spec = inputs.freeze()
    # Construct supplied adjudication without adding a competing frozen judgment.
    inputs.row["judgments"] = [frozen_label]
    post = adjudication_for(inputs, manifest, spec)
    inputs.row["judgments"] = []

    supplements = load_diagnostic_gold(
        manifest, spec, adjudication=encoded(post),
    )
    observation = inputs.observe(manifest, spec)
    if changed_actual == "context":
        observation["retrieval"]["final_context_digest"] = OTHER
    else:
        observation["final_claims"][0]["claim_digest"] = OTHER

    result = scored(spec, supplements, observation)
    assert result["valid_final_claims"] is True
    assert result["eligible_delivered_hits"] == 1
    assert result["feasible_maximum"] == 3
    assert result["complete_gold_hits"] is result["feasible_coverage"] is None
    assert result["condition_omission"] is result["false_promotion"] is None
    assert result["condition_omission_unknown"] == 1
    assert result["false_promotion_unknown"] == 1
    assert "QUALITY_JUDGMENT_MISSING_OR_MISMATCH" in result["reasons"]


@pytest.mark.parametrize("field,value", [
    ("statement", "x"),
    ("polarity", "negative"),
    ("modality", "uncertain"),
    ("conditions", []),
    ("exceptions", ["Only with explicit operator permission."]),
    ("interpretation_role", "caller_grounded_candidate"),
    ("valid_time", ["2026-10-02T00:00:00+00:00", None]),
    ("source_speaker", "assistant"),
    ("source_event_time", "2026-10-02T00:00:00+00:00"),
    ("source_recorded_at", "2026-10-03T00:00:00+00:00"),
])
def test_rehashed_packing_cannot_replace_frozen_claim_meaning_or_provenance(field, value):
    inputs = make_inputs()
    manifest, spec = inputs.freeze()
    assert load_diagnostic_gold(manifest, spec).gold[0].feasibility.complete
    claim = inputs.documents["packing"]["claims"][0]
    if field.startswith("source_"):
        claim["evidence"][0][field] = value
    else:
        claim[field] = value
    inputs.rehash_packing()
    changed_manifest, changed_spec = inputs.freeze()
    with pytest.raises(DiagnosticInputError):
        load_diagnostic_gold(changed_manifest, changed_spec)


def test_rehashed_packing_cannot_drop_approved_secondary_evidence():
    inputs = make_inputs(include_secondary_evidence=True)
    manifest, spec = inputs.freeze()
    assert load_diagnostic_gold(manifest, spec).gold[0].feasibility.complete
    inputs.documents["packing"]["claims"][0]["evidence"].pop()
    inputs.rehash_packing()
    changed_manifest, changed_spec = inputs.freeze()
    with pytest.raises(DiagnosticInputError):
        load_diagnostic_gold(changed_manifest, changed_spec)


@pytest.mark.parametrize("field,value", [
    ("body", "x"),
    ("exceptions", []),
    ("applicability", "false"),
    ("required", True),
    ("omit", None),
])
def test_rehashed_optional_rule_cannot_replace_approved_semantics(field, value):
    inputs = make_inputs(applicable_rules=[{
        "ref": "optionalrule1", "revision": 1, "digest": "c" * 64,
        "required": False, "applicability": "true",
        "body": "조건과 근거를 함께 보존한다.", "exceptions": ["인간의 명시적 거절은 제외한다."],
    }])
    manifest, spec = inputs.freeze()
    assert load_diagnostic_gold(manifest, spec).gold[0].feasibility.complete
    if field == "omit":
        inputs.documents["packing"]["rules"].clear()
    else:
        inputs.documents["packing"]["rules"][0][field] = value
    inputs.rehash_packing()
    changed_manifest, changed_spec = inputs.freeze()
    with pytest.raises(DiagnosticInputError):
        load_diagnostic_gold(changed_manifest, changed_spec)


@pytest.mark.parametrize("change", ["endpoint", "kind", "omit"])
def test_rehashed_relationship_cannot_change_frozen_closure(change):
    inputs = make_inputs(relations=[{
        "ref": "relation12", "left": "claim1", "right": "claim2", "kind": "supports",
    }])
    manifest, spec = inputs.freeze()
    assert load_diagnostic_gold(manifest, spec).gold[0].feasibility.complete
    if change == "omit":
        inputs.documents["packing"]["relations"].clear()
    elif change == "endpoint":
        inputs.documents["packing"]["relations"][0]["right"] = "decoy"
    else:
        inputs.documents["packing"]["relations"][0]["kind"] = "contradicts"
    inputs.rehash_packing()
    changed_manifest, changed_spec = inputs.freeze()
    with pytest.raises(DiagnosticInputError):
        load_diagnostic_gold(changed_manifest, changed_spec)


def test_known_missing_optional_and_relationship_prefix_is_unknown_not_f():
    inputs = make_inputs(
        budget_complete=False,
        applicable_rules=[{
            "ref": "optionalrule1", "revision": 1, "digest": "c" * 64,
            "required": False, "applicability": "true",
            "body": "조건을 보존한다.", "exceptions": [],
        }],
        relations=[{
            "ref": "relation12", "left": "claim1", "right": "claim2", "kind": "supports",
        }],
    )
    inputs.documents["packing"]["rules"].clear()
    inputs.documents["packing"]["relations"].clear()
    inputs.rehash_packing()
    manifest, spec = inputs.freeze()
    supplements = load_diagnostic_gold(manifest, spec)
    result = scored(spec, supplements, inputs.observe(manifest, spec))
    assert result["complete_gold_hits"] == 1
    assert supplements.gold[0].feasibility.complete is False
    assert result["feasible_maximum"] is result["feasible_coverage"] is None
    assert "FEASIBILITY_INCOMPLETE_OR_MISSING" in result["reasons"]
