from __future__ import annotations

import json
import math
import os
import random
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from agents_memory.domain import canonical_digest
from agents_memory.evaluation_scoring import (
    ArmObservation,
    BudgetFeasibilityWitness,
    DeliveredClaimJudgment,
    DeliveredClaimObservation,
    GoldEligibilityWitness,
    RetrievalDiagnosticGold,
    RetrievalDiagnosticObservation,
    RetrievalDiagnosticScope,
    RetrievalObservation,
    ScoringProtocol,
    score_retrieval_diagnostics,
    score_run,
    score_run_files,
)

D = "a" * 64
OTHER = "b" * 64


def protocol(*, tasks: int = 1, cases: int = 1) -> dict:
    return {
        "schema": 1, "scope": "engineering", "manifest_digest": D,
        "source_commit": "c" * 40, "controller_digest": D, "verifier_digest": D,
        "corpus_digest": D, "gold_digest": D, "workload_digest": D,
        "required_rules_digest": D, "native_identity_digest": D,
        "seed": 24680, "resamples": 10000, "confidence": 0.95,
        "coding_tasks": [{"task_id": f"task{index}", "task_revision": "rev1", "cluster_id": f"task{index}"}
                         for index in range(tasks)],
        "retrieval_cases": [{
            "case_id": f"case{index}", "cluster_id": f"family{index}",
            "relevant_claim_ids": ["claim1", "claim2"], "irrelevant_claim_ids": ["decoy"],
            "judgment_complete": True, "grounding_refs": [span()],
        } for index in range(cases)],
    }


def span(**changes) -> dict:
    return {"source_id": "source1", "revision": 1, "byte_start": 0, "byte_end": 4,
            "quote_digest": D, **changes}


def arm(mode: str, *, task: int = 0, repeat: int = 0, attempt: int = 0, **changes) -> dict:
    return {
        "schema": 1, "manifest_digest": D, "pair_id": f"pair{task}_{repeat}",
        "pair_attempt": attempt, "task_id": f"task{task}", "task_revision": "rev1",
        "cluster_id": f"task{task}", "repeat_index": repeat, "mode": mode,
        "invocation_id": f"invoke{task}_{repeat}_{attempt}_{mode}", "status": "completed",
        "comparable": True, "comparability_reasons": [], "contaminated": False,
        "native_identity_observed": True, "corpus_before_digest": D, "corpus_after_digest": D,
        "required_rules_digest": D, "native_identity_digest": D, "structural_pass": True,
        "functional_success": True, "cleanup_complete": True, "control_receipt_digest": D,
        "verifier_receipt_digest": D, "artifact_digest": D, "cost_basis": "unknown", **changes,
    }


def pair(**changes) -> list[dict]:
    return [arm("memory_on", **changes), arm("required_only", **changes)]


def read(*, case: int = 0, mode: str = "memory_on", **changes) -> dict:
    return {
        "schema": 1, "manifest_digest": D, "case_id": f"case{case}", "cluster_id": f"family{case}",
        "attempt_id": "read0", "mode": mode, "status": "completed", "comparable": True,
        "comparability_reasons": [], "contaminated": False, "returned_claim_ids": ["claim1"],
        "manifest_complete": True, "final_context_digest": D, "grounding_refs": [span()],
        "cost_basis": "unknown", **changes,
    }


def test_models_mapping_and_json_serialization_preserve_unknowns_and_freeze_evidence():
    frozen = ScoringProtocol(**protocol())
    observation = ArmObservation(**arm("memory_on", evidence_refs={"trace": D}))
    delivered = RetrievalObservation(**read())
    assert observation.cost_usd is None
    assert observation.input_tokens is None
    assert observation.model_dump(mode="json")["evidence_refs"] == {"trace": D}
    with pytest.raises(TypeError):
        observation.evidence_refs["other"] = OTHER
    assert score_run(frozen, [observation, arm("required_only")], [delivered]) == score_run(
        protocol(), pair(evidence_refs={"trace": D}), [read()],
    )


def test_missing_arm_and_absent_scheduled_repeats_are_not_valid_pairs():
    result = score_run(protocol(), [arm("memory_on")], [])
    coding = result["coding"]
    assert coding["scheduled_pairs"] == 3
    assert coding["unobserved_slots"] == 2
    assert coding["missing_arms"] == 1
    assert coding["valid_pair_attempts"] == 0
    assert coding["success_difference"]["estimate"] is None
    assert coding["exclusion_counts"] == {"MISSING_ARM": 1}
    assert result["original_targets"] == {
        "gold_cases": 120, "independent_tasks": 60, "repeats": 3, "valid_pairs": 180,
    }
    assert result["independence"] == "provided_unattested"
    assert result["original_acceptance"] is False
    assert result["original18_completed"] == 0


@pytest.mark.parametrize("change,reason", [
    ({"corpus_before_digest": OTHER}, "CORPUS_BEFORE_DIGEST_MISMATCH_OR_UNKNOWN"),
    ({"corpus_after_digest": OTHER}, "CORPUS_AFTER_DIGEST_MISMATCH_OR_UNKNOWN"),
    ({"native_identity_digest": OTHER}, "NATIVE_IDENTITY_DIGEST_MISMATCH_OR_UNKNOWN"),
    ({"required_rules_digest": OTHER}, "REQUIRED_RULES_DIGEST_MISMATCH_OR_UNKNOWN"),
    ({"native_identity_observed": False}, "NATIVE_IDENTITY_UNOBSERVED"),
    ({"contaminated": True}, "CONTAMINATED"),
    ({"comparable": False}, "INCOMPARABLE"),
    ({"comparability_reasons": ["RESIDUAL_MEMORY_UNKNOWN"]}, "INCOMPARABLE"),
    ({"functional_success": None}, "VERIFICATION_UNKNOWN"),
    ({"structural_pass": None}, "VERIFICATION_UNKNOWN"),
    ({"cleanup_complete": None}, "CLEANUP_INCOMPLETE_OR_UNKNOWN"),
    ({"control_receipt_digest": None}, "VERIFICATION_EVIDENCE_MISSING"),
    ({"verifier_receipt_digest": None}, "VERIFICATION_EVIDENCE_MISSING"),
    ({"artifact_digest": None}, "VERIFICATION_EVIDENCE_MISSING"),
    ({"status": "timeout"}, "NATIVE_NOT_COMPLETED"),
])
def test_incomparable_or_unverified_pair_is_retained_but_excluded(change, reason):
    result = score_run(protocol(), [arm("memory_on", **change), arm("required_only")], [])
    assert result["coding"]["valid_pair_attempts"] == 0
    assert result["coding"]["exclusion_counts"][reason] == 1
    assert result["accounting"]["attempts"] == 2


def test_control_identity_must_match_between_arms():
    coding = score_run(protocol(), [arm("memory_on", control_receipt_digest=OTHER), arm("required_only")], [])["coding"]
    assert coding["exclusion_counts"] == {"CONTROL_IDENTITY_MISMATCH": 1}


@pytest.mark.parametrize("field", ["functional_success", "structural_pass"])
def test_whole_task_failure_is_a_valid_binary_zero_not_partial_credit(field):
    coding = score_run(protocol(), [arm("memory_on", **{field: False}), arm("required_only")], [])["coding"]
    assert coding["valid_pair_attempts"] == 1
    assert coding["success"]["memory_on"]["estimate"] == 0
    assert coding["success"]["required_only"]["estimate"] == 1
    assert coding["success_difference"]["estimate"] == -1
    assert coding["success_difference"]["lower"] == -1
    assert coding["arms"]["memory_on"]["verification_failures"] == 1
    assert coding["arms"]["memory_on"]["successful_whole_task_latency"]["observed"] == 0


def test_observed_structural_rejection_is_zero_without_inventing_a_functional_result():
    coding = score_run(protocol(), [
        arm("memory_on", structural_pass=False, functional_success=None), arm("required_only"),
    ], [])["coding"]
    assert coding["valid_pair_attempts"] == 1
    assert coding["success"]["memory_on"]["estimate"] == 0
    assert coding["success_difference"]["estimate"] == -1
    on = coding["pairs"][0]["arms"]["memory_on"]
    assert on["structural_pass"] is False
    assert on["functional_success"] is None


def test_retry_does_not_erase_failed_attempt_or_combine_arms_across_attempts():
    rows = [arm("memory_on", status="failed", latency_seconds=2.0),
            arm("required_only", attempt=1, latency_seconds=5.0), *pair(attempt=2, latency_seconds=7.0)]
    result = score_run(protocol(), rows, [])
    coding = result["coding"]
    assert coding["pair_attempts"] == 3
    assert coding["retry_pair_attempts"] == 2
    assert coding["valid_pair_attempts"] == 1
    assert coding["excluded_pair_attempts"] == 2
    assert coding["valid_scheduled_slots"] == 1
    assert result["accounting"]["statuses"] == {"completed": 3, "failed": 1}
    assert result["accounting"]["measurements"]["latency_seconds"]["known_partial_total"] == 21
    assert result["accounting"]["measurements"]["cost_usd"]["unknown"] == 4


def test_valid_failed_retry_is_not_replaced_by_later_success():
    rows = [arm("memory_on", functional_success=False), arm("required_only"), *pair(attempt=1)]
    coding = score_run(protocol(), rows, [])["coding"]
    assert coding["valid_pair_attempts"] == 2
    assert coding["valid_scheduled_slots"] == 1
    assert coding["success"]["memory_on"]["estimate"] == 0.5
    assert coding["success_difference"]["estimate"] == -0.5


@pytest.mark.parametrize("rows", [
    [arm("memory_on"), arm("memory_on")],
    [arm("memory_on"), arm("required_only", invocation_id="invoke0_0_0_memory_on")],
    [arm("memory_on"), arm("required_only", pair_id="otherpair")],
    [arm("memory_on"), arm("required_only", repeat_index=1)],
    [arm("memory_on", task_revision="rev2")],
    [arm("memory_on", task_id="missing")],
    [arm("memory_on", cluster_id="different")],
])
def test_duplicate_or_identity_mismatched_arms_are_rejected(rows):
    with pytest.raises(ValueError, match="SCORING_"):
        score_run(protocol(), rows, [])


@pytest.mark.parametrize("observation", [arm("memory_on", manifest_digest=OTHER), read(manifest_digest=OTHER)])
def test_mixed_manifest_is_rejected_not_pooled(observation):
    with pytest.raises(ValueError, match="SCORING_MANIFEST_MISMATCH"):
        score_run(protocol(), [observation] if "pair_id" in observation else [],
                  [] if "pair_id" in observation else [observation])


def test_task_cluster_bootstrap_keeps_three_repeats_and_paired_arms_together():
    rows = []
    for task in range(2):
        for repeat in range(3):
            rows.extend([arm("memory_on", task=task, repeat=repeat, functional_success=task == 0),
                         arm("required_only", task=task, repeat=repeat, functional_success=task == 1)])
    interval = score_run(protocol(tasks=2), rows, [])["coding"]["success_difference"]
    assert interval == {
        "estimate": 0.0, "lower": -1.0, "upper": 1.0, "denominator": 6,
        "clusters": 2, "seed": 24680, "resamples": 10000, "confidence": 0.95,
        "method": "paired_task_cluster_percentile_linear", "rng": "python_random_MT19937_randrange",
    }
    rng = random.Random(24680)
    naive = sorted(sum(rng.choice([-1, -1, -1, 1, 1, 1]) for _ in range(6)) / 6 for _ in range(10000))
    assert naive[249] > interval["lower"]
    assert naive[9749] < interval["upper"]
    shuffled = list(reversed(rows))
    assert score_run(protocol(tasks=2), shuffled, [])["coding"]["success_difference"] == interval


def test_cluster_resampling_recomputes_ratio_for_unequal_cluster_sizes():
    rows = pair(task=0)
    for repeat in range(3):
        rows.extend([arm("memory_on", task=1, repeat=repeat, functional_success=False),
                     arm("required_only", task=1, repeat=repeat)])
    interval = score_run(protocol(tasks=2), rows, [])["coding"]["success_difference"]
    assert interval["estimate"] == -0.75
    assert interval["lower"] == -1
    assert interval["upper"] == 0
    assert interval["denominator"] == 4
    assert interval["clusters"] == 2


@pytest.mark.parametrize("seed", [41, 987654321])
def test_seeded_interval_matches_raw_task_cluster_resampling_reference(seed):
    spec = protocol(tasks=6)
    spec["seed"] = seed
    rows = []
    raw_clusters = []
    for task in range(6):
        values = []
        for repeat in range(task % 3 + 1):
            on_latency = (task + 1) ** 2 + repeat / 7
            off_latency = task / 3 + 0.125
            values.append(on_latency - off_latency)
            rows.extend([
                arm("memory_on", task=task, repeat=repeat, latency_seconds=on_latency),
                arm("required_only", task=task, repeat=repeat, latency_seconds=off_latency),
            ])
        raw_clusters.append(values)
    rng = random.Random(seed)
    samples = []
    for _ in range(10000):
        sampled_values = []
        for _ in raw_clusters:
            sampled_values.extend(raw_clusters[rng.randrange(len(raw_clusters))])
        samples.append(sum(sampled_values) / len(sampled_values))
    samples.sort()
    expected = []
    for probability in (0.025, 0.975):
        index = (len(samples) - 1) * probability
        lower = math.floor(index)
        expected.append(samples[lower] + (samples[math.ceil(index)] - samples[lower]) * (index - lower))
    interval = score_run(spec, rows, [])["coding"]["paired_measurement_differences"]["latency_seconds"]
    assert interval["lower"] == pytest.approx(expected[0])
    assert interval["upper"] == pytest.approx(expected[1])
    assert interval["denominator"] == 12
    assert interval["clusters"] == 6


def test_costs_are_partial_estimates_and_resources_are_observations_not_limits():
    rows = [arm("memory_on", latency_seconds=1.0, cost_usd=0.25, cost_basis="native_client_estimate",
                input_tokens=10, total_tokens=15, cpu_seconds=0.3, peak_rss_bytes=4096),
            arm("required_only", latency_seconds=9.0)]
    result = score_run(protocol(), rows, [])
    metrics = result["accounting"]["measurements"]
    assert metrics["cost_usd"]["known_partial_total"] == 0.25
    assert metrics["cost_usd"]["total"] is None
    assert metrics["cost_usd"]["unknown"] == 1
    assert metrics["latency_seconds"]["p50"] == 5
    assert metrics["latency_seconds"]["p95"] == pytest.approx(8.6)
    assert metrics["output_tokens"]["total"] is None
    paired = result["coding"]["paired_measurement_differences"]
    assert paired["latency_seconds"]["estimate"] == -8
    assert paired["cost_usd"]["estimate"] is None
    assert paired["cost_usd"]["unknown_pairs"] == 1
    resources = result["coding"]["arms"]["memory_on"]["resources"]
    assert resources["cpu_seconds"]["total"] == 0.3
    assert resources["peak_rss_bytes"]["maximum"] == 4096
    assert resources["peak_rss_bytes"]["total"] is None
    assert resources["disk_bytes"]["observed"] == 0


def test_fast_failure_is_not_successful_terminal_latency():
    rows = [*pair(status="failed", latency_seconds=0.01), *pair(attempt=1, latency_seconds=10.0)]
    result = score_run(protocol(), rows, [])
    assert result["accounting"]["measurements"]["latency_seconds"]["observed"] == 4
    assert result["accounting"]["completed_latency"]["observed"] == 2
    assert result["coding"]["arms"]["memory_on"]["successful_whole_task_latency"]["p50"] == 10


def test_relevance_and_exact_grounding_are_independent():
    observation = read(returned_claim_ids=["claim1", "decoy"], grounding_refs=[span(revision=2)])
    result = score_run(protocol(), [], [observation])["retrieval"]["observations"][0]
    assert result["precision"] == 0.5
    assert result["recall"] == 0.5
    assert result["grounding_precision"] == 0
    assert result["grounding_recall"] == 0
    assert result["grounding_errors"] == 1
    assert result["grounding_missing"] == 1
    assert result["grounding_exact"] is False


@pytest.mark.parametrize("changed_span", [
    span(source_id="other"), span(revision=2), span(byte_start=1),
    span(byte_end=5), span(quote_digest=OTHER),
])
def test_grounding_match_requires_all_five_exact_fields(changed_span):
    row = score_run(protocol(), [], [read(grounding_refs=[changed_span])])["retrieval"]["observations"][0]
    assert row["grounding_hits"] == 0
    assert row["precision"] == 1


def test_unjudged_returned_claims_are_unknown_not_false_positives():
    observation = read(returned_claim_ids=["claim1", "unjudged"])
    report = score_run(protocol(), [], [observation])["retrieval"]
    result = report["observations"][0]
    assert result["unjudged_returned"] == 1
    assert result["precision"] is None
    assert result["judged_precision"] == 1
    assert result["recall"] == 0.5
    assert report["modes"]["memory_on"]["metrics"]["precision"]["denominator"] == 0


def test_partial_gold_labels_do_not_claim_complete_recall():
    spec = protocol()
    spec["retrieval_cases"][0]["judgment_complete"] = False
    result = score_run(spec, [], [read()])["retrieval"]["observations"][0]
    assert result["precision"] == 1
    assert result["recall"] is None
    assert result["no_match"] is False


def test_positive_empty_final_read_scores_zero_but_missing_final_data_is_unknown():
    empty = read(returned_claim_ids=[], grounding_refs=[])
    missing = read(attempt_id="missing", returned_claim_ids=None, grounding_refs=None)
    report = score_run(protocol(), [], [empty, missing])["retrieval"]
    assert report["valid_final_reads"] == 1
    assert report["invalid_or_unknown_final_reads"] == 1
    by_attempt = {item["attempt_id"]: item for item in report["observations"]}
    assert by_attempt["read0"]["precision"] == 0
    assert by_attempt["read0"]["recall"] == 0
    assert by_attempt["read0"]["grounding_recall"] == 0
    assert "recall" not in by_attempt["missing"]


def test_gold_empty_abstention_is_no_match_not_perfect_positive_recall():
    spec = protocol()
    spec["retrieval_cases"][0]["relevant_claim_ids"] = []
    spec["retrieval_cases"][0]["grounding_refs"] = []
    result = score_run(spec, [], [read(returned_claim_ids=[], grounding_refs=[])])["retrieval"]["observations"][0]
    assert result["no_match"] is True
    assert result["abstained"] is True
    assert result["recall"] is None
    assert result["precision"] is None
    assert result["grounding_exact"] is True


@pytest.mark.parametrize("change", [
    {"manifest_complete": False}, {"manifest_complete": None}, {"final_context_digest": None},
    {"status": "incomplete"}, {"contaminated": True}, {"comparable": False},
])
def test_incomplete_retrieval_is_retained_without_semantic_scores(change):
    report = score_run(protocol(), [], [read(**change)])["retrieval"]
    assert report["attempts"] == 1
    assert report["valid_final_reads"] == 0
    assert report["modes"]["memory_on"]["accounting"]["measurements"]["cost_usd"]["unknown"] == 1


@pytest.mark.parametrize("observations", [
    [read(), read()], [read(cluster_id="wrong")], [read(case_id="absent")],
])
def test_duplicate_or_wrong_retrieval_identity_is_rejected(observations):
    with pytest.raises(ValueError, match="SCORING_"):
        score_run(protocol(), [], observations)


@pytest.mark.parametrize("changes", [
    {"schema": True}, {"schema": 1.0}, {"manifest_digest": "A" * 64},
    {"seed": True}, {"seed": "123"}, {"seed": -1}, {"resamples": 9999},
    {"confidence": 0.9}, {"source_commit": "not-a-commit"}, {"unexpected": "body"},
])
def test_protocol_rejects_coercion_and_unfrozen_statistics(changes):
    with pytest.raises(ValidationError):
        ScoringProtocol(**{**protocol(), **changes})


@pytest.mark.parametrize("changes", [
    {"cost_usd": 0.0}, {"cost_basis": "native_client_estimate"},
    {"latency_seconds": -1.0}, {"cost_usd": math.nan}, {"cpu_seconds": math.inf},
    {"input_tokens": True}, {"input_tokens": 1.5}, {"input_tokens": 5, "total_tokens": 4},
    {"repeat_index": 3}, {"pair_attempt": -1}, {"functional_success": 1},
    {"evidence_refs": {"private_path": "/private/secret"}},
    {"comparability_reasons": ["secret body with spaces"]},
])
def test_arm_strict_bounds_and_body_free_evidence(changes):
    with pytest.raises(ValidationError):
        ArmObservation(**arm("memory_on", **changes))


@pytest.mark.parametrize("mutation", ["duplicate_task", "duplicate_cluster", "duplicate_case", "conflicting_labels", "duplicate_span"])
def test_protocol_duplicate_and_label_validation(mutation):
    spec = protocol(tasks=2)
    if mutation == "duplicate_task":
        spec["coding_tasks"][1]["task_id"] = "task0"
    elif mutation == "duplicate_cluster":
        spec["coding_tasks"][1]["cluster_id"] = "task0"
    elif mutation == "duplicate_case":
        spec["retrieval_cases"] *= 2
    elif mutation == "conflicting_labels":
        spec["retrieval_cases"][0]["irrelevant_claim_ids"] = ["claim1"]
    else:
        spec["retrieval_cases"][0]["grounding_refs"] *= 2
    with pytest.raises(ValidationError):
        ScoringProtocol(**spec)


@pytest.mark.parametrize("changes", [
    {"returned_claim_ids": ["claim1", "claim1"]}, {"grounding_refs": [span(), span()]},
    {"grounding_refs": [span(byte_end=0)]}, {"grounding_refs": [span(revision=0)]},
])
def test_retrieval_duplicate_and_span_boundaries(changes):
    with pytest.raises(ValidationError):
        RetrievalObservation(**read(**changes))


def test_model_copy_cannot_bypass_projection_revalidation():
    unsafe = ArmObservation(**arm("memory_on")).model_copy(update={"functional_success": "true"})
    with pytest.raises(ValidationError):
        score_run(protocol(), [unsafe], [])


def test_public_report_never_exports_private_evidence_or_source_bodies():
    spec = protocol()
    spec_before = deepcopy(spec)
    observation = arm("memory_on", evidence_refs={"private_trace_reference": OTHER})
    report = score_run(spec, [observation], [read()])
    public = json.dumps(report, allow_nan=False)
    assert "private_trace_reference" not in public
    assert OTHER not in public
    assert "source1" not in public
    assert spec == spec_before
    assert report["retrieval"]["unavailable_metrics"] == [
        "candidate_recall_at_20", "feasible_coverage", "condition_omission", "false_promotion",
    ]


def private_json(path: Path, value) -> Path:
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    return path


def inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path.resolve()
    return (private_json(root / "protocol.json", protocol()),
            private_json(root / "arms.json", pair()), private_json(root / "reads.json", [read()]))


def test_private_file_api_matches_pure_mapping_api(tmp_path):
    files = inputs(tmp_path)
    assert score_run_files(*files) == score_run(protocol(), pair(), [read()])


@pytest.mark.parametrize("kind", ["duplicate", "nonfinite", "nul", "depth", "nonarray"])
def test_private_files_reject_nonliteral_wire_json(tmp_path, kind):
    files = inputs(tmp_path)
    raw = {"duplicate": b'[{"schema":1,"schema":1}]', "nonfinite": b'[NaN]',
           "nul": b'["\\u0000"]', "depth": b'[' * 30 + b']' * 30, "nonarray": b'{}'}[kind]
    files[1].write_bytes(raw)
    with pytest.raises(ValueError):
        score_run_files(*files)


@pytest.mark.parametrize("kind", ["final_symlink", "ancestor_symlink", "hardlink", "nonprivate", "missing", "directory", "oversize"])
def test_private_file_api_refuses_unsafe_or_unbounded_inputs(tmp_path, kind, monkeypatch):
    files = list(inputs(tmp_path))
    root = tmp_path.resolve()
    if kind == "final_symlink":
        link = root / "linked.json"
        link.symlink_to(files[1])
        files[1] = link
    elif kind == "ancestor_symlink":
        directory = root / "linked"
        directory.symlink_to(root, target_is_directory=True)
        files[1] = directory / "arms.json"
    elif kind == "hardlink":
        os.link(files[1], root / "another.json")
    elif kind == "nonprivate":
        files[1].chmod(0o644)
    elif kind == "missing":
        files[1] = root / "absent.json"
    elif kind == "directory":
        files[1] = root
    else:
        monkeypatch.setattr("agents_memory.evaluation_scoring.MAX_OBSERVATIONS_BYTES", 1)
    with pytest.raises(ValueError):
        score_run_files(*files)


def test_private_file_api_refuses_foreign_owner(tmp_path, monkeypatch):
    files = inputs(tmp_path)
    monkeypatch.setattr("agents_memory.evaluation_scoring.os.getuid", lambda: -1)
    with pytest.raises(ValueError, match="SCORING_PRIVATE_INPUT_DENIED"):
        score_run_files(*files)


def test_private_file_api_refuses_mutation_during_read(tmp_path, monkeypatch):
    files = inputs(tmp_path)
    original_read = os.read
    changed = False

    def mutate(fd, size):
        nonlocal changed
        raw = original_read(fd, size)
        if raw.startswith(b"[") and not changed:
            changed = True
            files[1].write_bytes(files[1].read_bytes() + b" ")
        return raw

    monkeypatch.setattr("agents_memory.evaluation_scoring.os.read", mutate)
    with pytest.raises(ValueError, match="SCORING_INPUT_CHANGED"):
        score_run_files(*files)


def test_bounded_direct_observation_iterables_are_not_silently_truncated(monkeypatch):
    monkeypatch.setattr("agents_memory.evaluation_scoring.MAX_ROWS", 1)
    with pytest.raises(ValueError, match="SCORING_ROW_LIMIT"):
        score_run(protocol(), iter(pair()), [])


def test_evaluation_scope_never_reduces_original_targets_or_attests_independence():
    spec = protocol(tasks=60, cases=120)
    spec["scope"] = "evaluation"
    result = score_run(spec, [], [])
    assert result["coding"]["scheduled_pairs"] == 180
    assert result["retrieval"]["cases"] == 120
    assert result["coding"]["valid_pair_attempts"] == 0
    assert result["sample_counts_meet_original_targets"] is False
    assert result["original_acceptance"] is False
    assert result["independence"] == "provided_unattested"


def test_empty_run_remains_unknown_nonacceptance():
    result = score_run(protocol(), [], [])
    assert result["coding"]["unobserved_slots"] == 3
    assert result["retrieval"]["unobserved_case_modes"] == 2
    assert result["accounting"]["measurements"]["latency_seconds"]["p95"] is None
    assert result["accounting"]["measurements"]["cost_usd"]["total"] is None
    assert result["sample_counts_meet_original_targets"] is False
    assert result["engineering_nonacceptance"] is True


def diagnostic_scope(**changes) -> dict:
    return {
        "manifest_digest": D, "corpus_digest": D, "gold_digest": D,
        "required_rules_digest": D, "request_digest": D, "budget_digest": D,
        "source_scope_digest": D, **changes,
    }


def diagnostic_gold(*, eligible=("claim1", "claim2"), ineligible=(), maximum=2, **changes) -> dict:
    scope = diagnostic_scope()
    eligibility = {
        "scope": scope, "independent_reference": "engineering_eligibility_not_human_gold",
        "evidence_digest": D, "complete": True, "eligible_claim_ids": list(eligible),
        "ineligible_claim_ids": list(ineligible),
    }
    return {
        "schema": 1, "case_id": "case0", "cluster_id": "family0", "scope": scope,
        "quality_definition_digest": D, "eligibility": eligibility,
        "feasibility": {
            "scope": scope, "independent_reference": "engineering_packing_not_human_gold",
            "evidence_digest": D, "eligibility_digest": canonical_digest(eligibility),
            "basis": "complete_independent_context_item_packing", "complete": True,
            "maximum_relevant": maximum, "maximizing_claim_ids": list(eligible[:maximum]),
        },
        "judgments": [{
            "scope": scope, "claim_id": claim, "expected_claim_digest": D,
            "definition_digest": D, "independent_reference": "engineering_quality_not_human_gold",
            "evidence_digest": D, "phase": "post_run_adjudication",
            "expected_final_context_digest": D, "gold_assertion_preserved": True,
            "condition_omission": False, "false_promotion": False,
        } for claim in (*eligible, *ineligible, "decoy")],
        **changes,
    }


def diagnostic_observation(*, returned=("claim1",), candidates=("claim1", "claim2"), **changes) -> dict:
    retrieval = changes.get("retrieval", read(returned_claim_ids=list(returned)))
    return {
        "schema": 1, "scope": diagnostic_scope(),
        "retrieval": retrieval,
        "candidate_status": "completed", "candidate_claim_ids": list(candidates),
        "candidate_comparable": retrieval["comparable"],
        "candidate_comparability_reasons": retrieval["comparability_reasons"],
        "candidate_manifest_digest": D, "candidates_complete": True,
        "final_claims": [{"claim_id": claim, "claim_digest": D, "complete": True} for claim in returned],
        **changes,
    }


def diagnostics(gold=None, observation=None, spec=None) -> dict:
    return score_retrieval_diagnostics(
        spec or protocol(), [diagnostic_gold() if gold is None else gold],
        [diagnostic_observation() if observation is None else observation],
    )


def test_diagnostic_models_are_strict_frozen_revalidated_and_preserve_original_scoring():
    witness = GoldEligibilityWitness(**diagnostic_gold()["eligibility"])
    feasible = BudgetFeasibilityWitness(**diagnostic_gold()["feasibility"])
    quality = DeliveredClaimJudgment(**diagnostic_gold()["judgments"][0])
    scope = RetrievalDiagnosticScope(**diagnostic_scope())
    final = DeliveredClaimObservation(claim_id="claim1", claim_digest=D, complete=True)
    frozen = RetrievalDiagnosticGold(**diagnostic_gold())
    actual = RetrievalDiagnosticObservation(**diagnostic_observation())
    before = score_run(protocol(), pair(), [read()])
    assert score_retrieval_diagnostics(ScoringProtocol(**protocol()), [frozen], [actual]) == diagnostics()
    assert witness.scope == scope == feasible.scope == quality.scope
    assert actual.final_claims == (final,)
    assert isinstance(frozen.judgments, tuple)
    with pytest.raises(ValidationError):
        witness.complete = False
    with pytest.raises(ValueError):
        score_retrieval_diagnostics(protocol(), [frozen.model_copy(update={"case_id": "../raw"})], [actual])
    assert score_run(protocol(), pair(), [read()]) == before


def test_diagnostic_four_gold_three_delivered_keeps_raw_and_feasible_denominators_separate():
    spec = protocol()
    ids = ("claim1", "claim2", "claim3", "claim4")
    spec["retrieval_cases"][0]["relevant_claim_ids"] = list(ids)
    report = diagnostics(diagnostic_gold(eligible=ids, maximum=3),
                         diagnostic_observation(returned=ids[:3], candidates=ids), spec)
    result = report["observations"][0]
    assert result["candidate_recall_at_20"] == 1
    assert result["raw_gold_recall"] == 0.75
    assert result["eligible_recall"] == 0.75
    assert result["feasible_coverage"] == 1
    assert result["feasible_maximum"] == 3
    assert result["complete_gold_hits"] == 3
    assert result["condition_omission"] == result["false_promotion"] == 0
    assert report["original_acceptance"] is False
    assert report["original18_completed"] == 0
    assert report["independence"] == "provided_unattested"


def test_diagnostic_current_eligibility_is_not_raw_relevance_and_ineligible_delivery_is_separate():
    gold = diagnostic_gold(eligible=("claim1",), ineligible=("claim2",), maximum=1)
    result = diagnostics(gold, diagnostic_observation(returned=("claim1", "claim2")))["observations"][0]
    assert result["raw_gold"] == 2 and result["eligible_gold"] == result["ineligible_gold"] == 1
    assert result["candidate_recall_at_20"] == 1
    assert result["candidate_raw_gold_recall_at_20"] == 0.5
    assert result["raw_gold_recall"] == 0.5
    assert result["eligible_recall"] == result["feasible_coverage"] == 1
    assert result["ineligible_gold_delivered"] == 1


def test_diagnostic_candidates_are_actual_first_stage_not_final_selection():
    result = diagnostics(observation=diagnostic_observation(candidates=("decoy",)))["observations"][0]
    assert result["candidate_hits"] == result["candidate_recall_at_20"] == 0
    assert result["eligible_delivered_hits"] == 1
    assert result["eligible_recall"] == result["feasible_coverage"] == 0.5


@pytest.mark.parametrize("change", [
    {"candidate_claim_ids": None}, {"candidates_complete": None}, {"candidates_complete": False},
    {"candidate_status": None}, {"candidate_status": "incomplete"}, {"candidate_manifest_digest": None},
    {"candidate_comparable": None}, {"candidate_comparable": False},
    {"candidate_comparability_reasons": ["STAGE_SCOPE_UNKNOWN"]},
])
def test_diagnostic_unknown_candidate_evidence_is_not_empty_success(change):
    result = diagnostics(observation=diagnostic_observation(**change))["observations"][0]
    assert result["candidate_recall_at_20"] is None
    assert result["valid_candidates"] is False
    assert result["feasible_coverage"] == 0.5


def test_diagnostic_explicit_complete_empty_candidates_are_zero_for_positive_gold():
    result = diagnostics(observation=diagnostic_observation(candidates=()))["observations"][0]
    assert result["candidate_recall_at_20"] == 0
    assert result["valid_candidates"] is True


@pytest.mark.parametrize("kind", ["duplicate_candidate", "unbounded_candidates", "duplicate_final",
                                  "bad_integer", "extra_field", "duplicate_judgment", "context_required",
                                  "contradictory_quality", "bad_maximum", "overlapping_eligibility"])
def test_diagnostic_strict_boundary_rejections(kind):
    gold, observation = diagnostic_gold(), diagnostic_observation()
    if kind == "duplicate_candidate":
        observation["candidate_claim_ids"] = ["claim1", "claim1"]
    elif kind == "unbounded_candidates":
        observation["candidate_claim_ids"] = [f"claim{index}" for index in range(21)]
    elif kind == "duplicate_final":
        observation["final_claims"] *= 2
    elif kind == "bad_integer":
        gold["feasibility"]["maximum_relevant"] = True
    elif kind == "extra_field":
        gold["human_approved"] = True
    elif kind == "duplicate_judgment":
        gold["judgments"].append(deepcopy(gold["judgments"][0]))
    elif kind == "context_required":
        gold["judgments"][0]["expected_final_context_digest"] = None
    elif kind == "contradictory_quality":
        gold["judgments"][0]["condition_omission"] = True
    elif kind == "bad_maximum":
        gold["feasibility"]["maximum_relevant"] = 1
    else:
        gold["eligibility"]["ineligible_claim_ids"] = ["claim1"]
    with pytest.raises(ValueError):
        diagnostics(gold, observation)


@pytest.mark.parametrize("kind,reason", [
    ("missing", "ELIGIBILITY_INCOMPLETE_OR_MISSING"),
    ("incomplete", "ELIGIBILITY_INCOMPLETE_OR_MISSING"),
    ("scope", "ELIGIBILITY_SCOPE_MISMATCH"),
    ("partition", "ELIGIBILITY_PARTITION_MISMATCH"),
    ("raw_partial", "RAW_GOLD_INCOMPLETE"),
])
def test_diagnostic_eligibility_requires_complete_independent_witness(kind, reason):
    spec, gold = protocol(), diagnostic_gold()
    if kind == "missing":
        gold["eligibility"] = None
    elif kind == "incomplete":
        gold["eligibility"]["complete"] = False
    elif kind == "scope":
        gold["eligibility"]["scope"] = diagnostic_scope(request_digest=OTHER)
    elif kind == "partition":
        gold["eligibility"]["eligible_claim_ids"] = ["claim1"]
    else:
        spec["retrieval_cases"][0]["judgment_complete"] = False
    result = diagnostics(gold, spec=spec)["observations"][0]
    assert result["eligible_gold"] is result["feasible_maximum"] is None
    assert result["candidate_recall_at_20"] is result["feasible_coverage"] is None
    assert reason in result["reasons"]


@pytest.mark.parametrize("kind,reason", [
    ("missing", "FEASIBILITY_INCOMPLETE_OR_MISSING"),
    ("incomplete", "FEASIBILITY_INCOMPLETE_OR_MISSING"),
    ("scope", "FEASIBILITY_SCOPE_MISMATCH"),
    ("eligibility", "FEASIBILITY_ELIGIBILITY_MISMATCH"),
    ("set", "FEASIBILITY_ELIGIBLE_SET_MISMATCH"),
])
def test_diagnostic_feasible_maximum_is_not_inferred_from_successful_output(kind, reason):
    gold = diagnostic_gold()
    if kind == "missing":
        gold["feasibility"] = None
    elif kind == "incomplete":
        gold["feasibility"]["complete"] = False
    elif kind == "scope":
        gold["feasibility"]["scope"] = diagnostic_scope(budget_digest=OTHER)
    elif kind == "eligibility":
        gold["feasibility"]["eligibility_digest"] = OTHER
    else:
        gold["feasibility"]["maximizing_claim_ids"] = ["claim1", "decoy"]
    result = diagnostics(gold)["observations"][0]
    assert result["feasible_coverage"] is result["feasible_maximum"] is None
    assert result["eligible_recall"] == 0.5
    assert reason in result["reasons"]


def test_diagnostic_budget_impossible_is_undefined_not_perfect_and_contradiction_invalidates_witness():
    gold = diagnostic_gold(maximum=0)
    empty = diagnostics(gold, diagnostic_observation(returned=()))["observations"][0]
    assert empty["budget_impossible"] is True
    assert empty["feasible_coverage"] is None
    assert empty["eligible_recall"] == empty["raw_gold_recall"] == 0
    contradictory = diagnostics(gold)["observations"][0]
    assert contradictory["feasible_coverage"] is contradictory["feasible_maximum"] is None
    assert contradictory["budget_impossible"] is None
    assert "FEASIBILITY_CONTRADICTS_DELIVERY" in contradictory["reasons"]


def test_diagnostic_no_match_and_unknown_gold_are_not_zero_or_perfect_positive_scores():
    spec = protocol()
    spec["retrieval_cases"][0]["relevant_claim_ids"] = []
    gold = diagnostic_gold(eligible=(), maximum=0)
    result = diagnostics(gold, diagnostic_observation(returned=(), candidates=()), spec)["observations"][0]
    assert result["no_match"] is True
    assert result["budget_impossible"] is False
    assert result["candidate_recall_at_20"] is result["eligible_recall"] is result["feasible_coverage"] is None
    assert result["condition_omission"] is result["false_promotion"] is None
    false_return = diagnostics(gold, diagnostic_observation(returned=("decoy",)), spec)["observations"][0]
    assert false_return["no_match_false_return"] is True
    missing = score_retrieval_diagnostics(protocol(), [], [diagnostic_observation()])["observations"][0]
    assert missing["feasible_maximum"] is missing["candidate_recall_at_20"] is None


@pytest.mark.parametrize("change", [
    {"final_claims": None},
    {"final_claims": [{"claim_id": "claim2", "claim_digest": D, "complete": True}]},
    {"final_claims": [{"claim_id": "claim1", "claim_digest": D, "complete": False}]},
    {"retrieval": read(manifest_complete=None)},
    {"retrieval": read(final_context_digest=None)},
    {"retrieval": read(grounding_refs=None)},
    {"retrieval": read(status="failed")},
])
def test_diagnostic_final_must_be_actual_complete_and_comparable(change):
    result = diagnostics(observation=diagnostic_observation(**change))["observations"][0]
    assert result["valid_final_claims"] is False
    assert result["feasible_coverage"] is result["condition_omission"] is result["false_promotion"] is None
    assert result["candidate_recall_at_20"] == 1


@pytest.mark.parametrize("change", [
    {"comparable": False}, {"contaminated": True}, {"comparability_reasons": ["UNKNOWN_SCOPE"]},
])
def test_diagnostic_incomparability_excludes_candidate_and_final_scores(change):
    result = diagnostics(observation=diagnostic_observation(retrieval=read(**change)))["observations"][0]
    assert result["valid_candidates"] is result["valid_final_claims"] is False
    assert result["candidate_recall_at_20"] is result["feasible_coverage"] is None


def test_diagnostic_condition_drop_and_false_promotion_are_not_relevance_accuracy_inference():
    gold = diagnostic_gold()
    gold["judgments"][0].update(gold_assertion_preserved=False, condition_omission=True,
                                false_promotion=True)
    result = diagnostics(gold)["observations"][0]
    assert result["eligible_delivered_hits"] == 1
    assert result["complete_gold_hits"] == 0
    assert result["feasible_coverage"] == 0
    assert result["condition_omission"] == result["false_promotion"] == 1
    assert score_run(protocol(), [], [read()])["retrieval"]["observations"][0]["precision"] == 1


@pytest.mark.parametrize("kind", ["claim_digest", "context_digest", "source_scope", "definition",
                                  "missing", "null_judgment", "ambiguous"])
def test_diagnostic_mismatching_or_unjudged_actual_content_remains_unknown(kind):
    gold = diagnostic_gold()
    if kind == "claim_digest":
        gold["judgments"][0]["expected_claim_digest"] = OTHER
    elif kind == "context_digest":
        gold["judgments"][0]["expected_final_context_digest"] = OTHER
    elif kind == "source_scope":
        gold["judgments"][0]["scope"] = diagnostic_scope(source_scope_digest=OTHER)
    elif kind == "definition":
        gold["judgments"][0]["definition_digest"] = OTHER
    elif kind == "missing":
        gold["judgments"] = []
    elif kind == "null_judgment":
        gold["judgments"][0].update(gold_assertion_preserved=None, condition_omission=None,
                                    false_promotion=None)
    else:
        second = deepcopy(gold["judgments"][0])
        second.update(phase="frozen_claim", expected_final_context_digest=None, false_promotion=None)
        gold["judgments"].append(second)
    result = diagnostics(gold)["observations"][0]
    assert result["condition_omission"] is result["false_promotion"] is result["feasible_coverage"] is None
    assert result["condition_omission_unknown"] == result["false_promotion_unknown"] == 1


def test_diagnostic_quality_partial_labels_do_not_become_wholly_observed_zero():
    gold = diagnostic_gold()
    gold["judgments"] = gold["judgments"][:1]
    result = diagnostics(gold, diagnostic_observation(returned=("claim1", "claim2")))["observations"][0]
    assert result["condition_omission_judged"] == result["false_promotion_judged"] == 1
    assert result["condition_omission_unknown"] == result["false_promotion_unknown"] == 1
    assert result["condition_omission"] is result["false_promotion"] is None
    assert result["feasible_coverage"] is None


@pytest.mark.parametrize("field", ["request_digest", "budget_digest", "source_scope_digest"])
def test_diagnostic_request_budget_and_original_source_scope_cannot_mix(field):
    gold = diagnostic_gold(scope=diagnostic_scope(**{field: OTHER}))
    result = diagnostics(gold)["observations"][0]
    assert result["candidate_recall_at_20"] is result["feasible_coverage"] is None
    assert result["condition_omission"] is result["false_promotion"] is None
    assert "DIAGNOSTIC_SCOPE_MISMATCH" in result["reasons"]


def test_diagnostic_protocol_identity_duplicates_and_unchecked_models_are_rejected():
    for field in ("manifest_digest", "corpus_digest", "gold_digest", "required_rules_digest"):
        with pytest.raises(ValueError, match="SCORING_DIAGNOSTIC_PROTOCOL_MISMATCH"):
            diagnostics(diagnostic_gold(scope=diagnostic_scope(**{field: OTHER})))
    for golds, actual in (([diagnostic_gold()] * 2, [diagnostic_observation()]),
                         ([diagnostic_gold()], [diagnostic_observation()] * 2)):
        with pytest.raises(ValueError, match="SCORING_DUPLICATE_DIAGNOSTIC"):
            score_retrieval_diagnostics(protocol(), golds, actual)


def test_diagnostic_all_attempts_unknown_costs_and_actual_failures_survive():
    failed = diagnostic_observation(retrieval=read(status="failed", latency_seconds=1.0))
    later = diagnostic_observation(retrieval=read(attempt_id="retry1", latency_seconds=3.0))
    report = score_retrieval_diagnostics(protocol(), [diagnostic_gold()], [failed, later])
    assert report["attempts"] == len(report["observations"]) == 2
    assert report["accounting"]["statuses"] == {"completed": 1, "failed": 1}
    assert report["accounting"]["measurements"]["cost_usd"]["unknown"] == 2
    assert report["accounting"]["measurements"]["cost_usd"]["total"] is None
    assert report["modes"]["memory_on"]["metrics"]["feasible_coverage"]["denominator"] == 1
    assert report["modes"]["memory_on"]["metrics"]["feasible_coverage"]["unknown_attempts"] == 1
    assert report["modes"]["memory_on"]["metrics"]["candidate_recall_at_20"]["denominator"] == 2


def test_diagnostic_exact_seeded_source_family_cluster_intervals_and_body_free_report():
    spec = protocol(cases=3)
    spec["retrieval_cases"][1]["cluster_id"] = "family0"
    golds, observations = [], []
    for index, candidates in enumerate((("claim1", "claim2"), (), ("claim1", "claim2"))):
        cluster = spec["retrieval_cases"][index]["cluster_id"]
        golds.append(diagnostic_gold(case_id=f"case{index}", cluster_id=cluster))
        observations.append(diagnostic_observation(
            candidates=candidates, retrieval=read(case=index, cluster_id=cluster),
        ))
    original = deepcopy((spec, golds, observations))
    report = score_retrieval_diagnostics(spec, golds, observations)
    metric = report["modes"]["memory_on"]["metrics"]["candidate_recall_at_20"]
    rng = random.Random(spec["seed"])
    clusters = ((1.0, 2), (1.0, 1))
    samples = []
    for _ in range(10000):
        drawn = [clusters[rng.randrange(2)] for _ in range(2)]
        samples.append(sum(item[0] for item in drawn) / sum(item[1] for item in drawn))
    samples.sort()
    assert metric["estimate"] == 2 / 3
    assert metric["denominator"] == 3 and metric["clusters"] == 2
    expected = []
    for probability in (0.025, 0.975):
        position = (len(samples) - 1) * probability
        lo, hi = math.floor(position), math.ceil(position)
        expected.append(samples[lo] + (samples[hi] - samples[lo]) * (position - lo))
    assert metric["lower"] == expected[0]
    assert metric["upper"] == expected[1]
    assert metric["lower"] == 0.5 and metric["upper"] == 1
    assert metric["resamples"] == 10000 and metric["confidence"] == 0.95
    assert metric["method"] == "retrieval_source_family_cluster_percentile_linear"
    assert (spec, golds, observations) == original
    public = json.dumps(report, allow_nan=False)
    assert "engineering_quality_not_human_gold" not in public


@pytest.mark.parametrize("count", [1, 3])
def test_diagnostic_single_and_three_gold_full_delivery_boundaries(count):
    ids = tuple(f"claim{index + 1}" for index in range(count))
    spec = protocol()
    spec["retrieval_cases"][0]["relevant_claim_ids"] = list(ids)
    result = diagnostics(diagnostic_gold(eligible=ids, maximum=count),
                         diagnostic_observation(returned=ids, candidates=ids), spec)["observations"][0]
    assert result["candidate_recall_at_20"] == result["raw_gold_recall"] == 1
    assert result["eligible_recall"] == result["feasible_coverage"] == 1


def test_diagnostic_more_than_three_final_claims_cannot_use_frozen_top_three_budget():
    ids = ("claim1", "claim2", "claim3", "claim4")
    spec = protocol()
    spec["retrieval_cases"][0]["relevant_claim_ids"] = list(ids)
    result = diagnostics(diagnostic_gold(eligible=ids, maximum=3),
                         diagnostic_observation(returned=ids, candidates=ids), spec)["observations"][0]
    assert result["valid_candidates"] is True
    assert result["valid_final_claims"] is False
    assert result["feasible_coverage"] is None


def test_diagnostic_frozen_claim_condition_labels_need_no_invented_post_run_context():
    gold = diagnostic_gold()
    gold["judgments"][0].update(
        phase="frozen_claim", expected_final_context_digest=None, false_promotion=None,
    )
    result = diagnostics(gold)["observations"][0]
    assert result["condition_omission"] == 0
    assert result["feasible_coverage"] == 0.5
    assert result["false_promotion"] is None


def test_diagnostic_observed_candidates_survive_independently_incomplete_final_delivery():
    observation = diagnostic_observation(
        retrieval=read(status="failed", comparable=False, comparability_reasons=["FINAL_UNKNOWN"],
                       returned_claim_ids=None, manifest_complete=None, final_context_digest=None),
        final_claims=None, candidate_comparable=True, candidate_comparability_reasons=[],
    )
    result = diagnostics(observation=observation)["observations"][0]
    assert result["candidate_recall_at_20"] == 1
    assert result["valid_final_claims"] is False
    assert result["feasible_coverage"] is None


def test_diagnostic_quality_rates_use_all_actual_judgments_not_only_relevant_hits():
    gold = diagnostic_gold()
    gold["judgments"][-1]["false_promotion"] = True
    gold["judgments"][0].update(gold_assertion_preserved=False, condition_omission=True)
    result = diagnostics(gold, diagnostic_observation(returned=("claim1", "decoy")))["observations"][0]
    assert result["condition_omission_count"] == result["false_promotion_count"] == 1
    assert result["condition_omission_judged"] == result["false_promotion_judged"] == 2
    assert result["condition_omission"] == result["false_promotion"] == 0.5
    assert result["feasible_coverage"] == 0


def test_diagnostic_unknown_eligibility_cannot_publish_observed_zero_safety_violations():
    report = diagnostics(diagnostic_gold(eligibility=None))
    summary = report["modes"]["memory_on"]["summary"]
    assert summary["ineligible_gold_delivered"] is None
    assert summary["known_ineligible_gold_delivered"] == 0
    assert summary["ineligible_delivery_unknown_attempts"] == summary["eligibility_unknown"] == 1
