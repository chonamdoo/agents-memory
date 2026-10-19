from __future__ import annotations

import json
from copy import deepcopy

import pytest

from agents_memory.recall_evaluation import report_trial

DIRECT_ROUTE = "direct:sha256-of-provider-base-url"


def trial_document(host="claude"):
    observations = []

    def observation(generation):
        ref = f"engineering-{host}-{generation}"
        observations.append({"ref": ref, "host": host, "generation": generation,
                             "source": "native", "complete": True, "sha256": "a" * 64})
        return ref

    def run(strategy):
        parent_generation = strategy + "-parent"
        child_generation = "fork-child" if strategy == "fork" else None
        parent_ref = observation(parent_generation)
        child_ref = observation(child_generation) if child_generation else None
        def proof(ref):
            return {"satisfied": True, "observation_ref": ref}

        def usage(ref, cost, scale=1):
            return {"input_tokens": 100 * scale, "output_tokens": 20 * scale,
                    "cache_read_tokens": 10 * scale, "cache_creation_tokens": 5 * scale,
                    "cost_usd": cost, "observation_ref": ref}

        sizes = (100, 800, 100, 0) if strategy == "inline" else (100, 0, 100, 40)
        residual = {name: {"actual_bytes": size, "actual_tokens": size // 2,
                           "observation_ref": parent_ref, "measurement": "native_main_residual"}
                    for name, size in zip(("first", "inspect", "second", "return"), sizes)}
        return {
            "frozen": {"task_digest": "task", "corpus_digest": "corpus", "gold_digest": "gold",
                       "request_digest": "request", "required_rules_digest": "required",
                       "permissions_digest": "permissions", "host_version": "1.0", "parent_model": "main",
                       "provider_route": DIRECT_ROUTE, "attempt_id": "frozen-attempt"},
            "parent_generation": parent_generation, "child_generation": child_generation,
            "child_model": "judge" if child_generation else None,
            "observed_at": "2026-10-03T12:00:00Z", "status": "completed", "native_observation_ref": parent_ref,
            "quality": {"tp": 9, "fp": 1, "fn": 1, "condition_omissions": 0,
                        "exception_omissions": 0, "conflict_omissions": 0,
                        "independent_gold_ref": "frozen-independent-gold", "final_delivery_observation_ref": parent_ref},
            "residual": residual,
            "usage": {"parent": usage(parent_ref, .2),
                      "child": usage(child_ref, .1) if child_generation else None,
                      "pipeline": usage(parent_ref, .4, 2) if child_generation else usage(parent_ref, .2),
                      "pipeline_child_inclusion": "included" if child_generation else "not_applicable",
                      "cost_basis": "native-client-estimate"},
            "latency": {"recall_ms": 100.0, "total_ms": 200.0, "observation_ref": parent_ref},
            "contract": {"required_on_child_failure": proof(parent_ref), "final_spans": proof(parent_ref),
                         "source_revision": proof(parent_ref), "eligibility_rechecks": proof(parent_ref),
                         "unchanged_task_and_request": proof(parent_ref), "parent_final_delivery": proof(parent_ref),
                         "full_conversation_fork": proof(parent_ref) if child_generation else None,
                         "complete_manifest_inspection": proof(child_ref or parent_ref),
                         "exact_return_validation": proof(parent_ref) if child_generation else None,
                         "completed_child": proof(child_ref) if child_generation else None},
        }

    inline, fork = run("inline"), run("fork")
    return {"schema_version": 1, "window": {"started_at": "2026-10-01T00:00:00Z",
             "as_of": "2026-10-09T00:00:00Z", "duration_days": 7},
            "thresholds": {"frozen_plan_ref": "engineering-frozen-plan", "precision_margin": 0.0,
                           "recall_margin": 0.0, "max_fn_increase": 0,
                           "max_condition_omission_increase": 0, "max_exception_omission_increase": 0,
                           "max_conflict_omission_increase": 0, "max_main_bytes_ratio": .8,
                           "max_main_tokens_ratio": .8},
            "observations": observations,
            "hosts": [{"host": host, "host_version": "1.0", "parent_model": "main", "provider_route": DIRECT_ROUTE,
                       "child_model": "judge",
                       "scheduled_pair_ids": ["pair-one"], "pairs": [{"pair_id": "pair-one", "inline": inline,
                                                                      "fork": fork}]}]}


def fork(document):
    return document["hosts"][0]["pairs"][0]["fork"]


def paired_trial(first_arms, *, distinct=True):
    document = trial_document()
    host = document["hosts"][0]
    template = host["pairs"][0]
    observations = list(document["observations"])
    host["pairs"], host["scheduled_pair_ids"], document["observations"] = [], [], []
    for index, first in enumerate(first_arms):
        suffix = f"-{index}" if distinct else ""
        raw = json.dumps(template)
        for name in ("inline-parent", "fork-parent", "fork-child", "frozen-attempt"):
            raw = raw.replace(name, name + suffix)
        pair = json.loads(raw)
        pair["pair_id"] = f"pair-{index}"
        for strategy in ("inline", "fork"):
            later = first is not None and strategy != first
            pair[strategy]["observed_at"] = "2026-10-03T13:00:00Z" if later else "2026-10-03T12:00:00Z"
        host["pairs"].append(pair)
        host["scheduled_pair_ids"].append(pair["pair_id"])
        if distinct or index == 0:
            for item in observations:
                document["observations"].append({**item, "ref": item["ref"] + suffix,
                                                 "generation": item["generation"] + suffix})
    return document


def test_complete_paired_evidence_remains_experimental_and_keeps_accounting_layers():
    report = report_trial(trial_document())
    assert report["decision"] == "experimental"
    assert report["trial_status"] == "complete"
    assert report["supported"] is False and report["automatic_promotion"] is False
    host = report["hosts"][0]
    assert host["paired_valid"] == 1
    comparison = host["pairs"][0]["comparison"]
    assert comparison["quality_noninferior"] is True
    assert comparison["main_residual"]["actual_bytes"] == {
        "inline": 1000, "fork": 240, "ratio": .24, "passes": True,
    }
    assert comparison["pipeline_cost_difference_usd"] == pytest.approx(.2)
    assert host["pairs"][0]["evidence"]["fork"]["usage"]["child"]["cache_read_tokens"] == 10
    assert host["latency_all_attempts"]["fork"]["total_ms"] == {
        "count": 1, "p50": 200, "p95": None, "p95_status": "insufficient_samples",
    }
    assert {"window", "hosts", "observations", "thresholds"} <= set(report["input_schema"]["required"])


@pytest.mark.parametrize("path", [
    ("residual", "first", "actual_tokens"), ("usage", "child", "cost_usd"),
    ("usage", "parent", "cache_read_tokens"), ("latency", "total_ms"),
    ("quality", "fn"), ("contract", "source_revision", "satisfied"),
    ("contract", "required_on_child_failure", "satisfied"),
])
def test_unknown_evidence_cannot_become_supported_or_evidence_ready(path):
    document = trial_document()
    target = fork(document)
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = None
    report = report_trial(document)
    assert report["decision"] == "unsupported"
    assert report["hosts"][0]["evidence_ready"] is False
    assert report["supported"] is False


@pytest.mark.parametrize("field", ["fn", "condition_omissions", "exception_omissions", "conflict_omissions", "fp"])
def test_paired_quality_degradation_blocks_even_large_residual_savings(field):
    document = trial_document()
    fork(document)["quality"][field] += 1
    report = report_trial(document)
    pair = report["hosts"][0]["pairs"][0]
    assert pair["comparison"]["residual_improved"] is True
    assert pair["comparison"]["quality_noninferior"] is False
    assert pair["evidence_ready"] is False


def test_residual_regression_is_not_hidden_by_equal_quality():
    document = trial_document()
    fork(document)["residual"]["return"]["actual_bytes"] = 1000
    report = report_trial(document)
    pair = report["hosts"][0]["pairs"][0]
    assert pair["comparison"]["quality_noninferior"] is True
    assert pair["comparison"]["residual_improved"] is False
    assert report["decision"] == "unsupported"


@pytest.mark.parametrize("change", ["missing_ref", "incomplete_ref", "foreign_host", "child_as_parent", "unknown_inclusion"])
def test_native_reference_actor_and_pipeline_inclusion_are_explicit(change):
    document = trial_document()
    run = fork(document)
    if change == "missing_ref":
        document["observations"] = []
    elif change == "incomplete_ref":
        document["observations"][1]["complete"] = False
    elif change == "foreign_host":
        document["observations"][1]["host"] = "codex"
    elif change == "child_as_parent":
        run["usage"]["parent"]["observation_ref"] = run["usage"]["child"]["observation_ref"]
    else:
        run["usage"]["pipeline_child_inclusion"] = "unknown"
    assert report_trial(document)["hosts"][0]["evidence_ready"] is False


@pytest.mark.parametrize("strategy,metric,value", [
    ("fork", "cost_usd", 0), ("fork", "input_tokens", 0), ("fork", "cache_creation_tokens", 9),
    ("inline", "output_tokens", 19), ("inline", "cost_usd", .1),
])
def test_pipeline_usage_below_its_covered_layers_is_not_evidence(strategy, metric, value):
    document = trial_document()
    document["hosts"][0]["pairs"][0][strategy]["usage"]["pipeline"][metric] = value
    pair = report_trial(document)["hosts"][0]["pairs"][0]
    assert f"{strategy.upper()}:USAGE_ACCOUNTING_INCONSISTENT" in pair["issues"]
    assert pair["evidence_ready"] is False


def test_pipeline_cost_equal_to_its_layers_tolerates_float_rounding():
    document = trial_document()
    fork(document)["usage"]["pipeline"]["cost_usd"] = .3
    pair = report_trial(document)["hosts"][0]["pairs"][0]
    assert .2 + .1 > .3
    assert pair["issues"] == [] and pair["evidence_ready"] is True


def test_host_decisions_are_separate_and_foreign_evidence_not_pooled():
    document = trial_document()
    codex = trial_document("codex")
    codex["hosts"][0]["pairs"][0]["fork"]["usage"]["child"]["cost_usd"] = None
    document["hosts"].extend(codex["hosts"])
    document["observations"].extend(codex["observations"])
    report = report_trial(document)
    assert [(host["host"], host["decision"]) for host in report["hosts"]] == [
        ("claude", "experimental"), ("codex", "unsupported"),
    ]
    assert report["decision"] == "unsupported"


@pytest.mark.parametrize("status", ["stale", "partial", "cancelled", "failed", "unsupported"])
def test_failure_denominators_and_latency_are_retained(status):
    document = trial_document()
    fork(document)["status"] = status
    host = report_trial(document)["hosts"][0]
    assert host["scheduled_pairs"] == 1 and host["paired_valid"] == 0
    assert host["statuses"]["fork:" + status] == 1
    assert host["latency_all_attempts"]["fork"]["total_ms"]["count"] == 1
    assert host["latency_completed_attempts"]["fork"]["total_ms"]["count"] == 0


def test_missing_pair_and_foreign_frozen_task_are_rejected():
    document = trial_document()
    document["hosts"][0]["scheduled_pair_ids"].append("pair-missing")
    fork(document)["frozen"]["task_digest"] = "foreign-task"
    host = report_trial(document)["hosts"][0]
    assert "PAIR_SCHEDULE_INCOMPLETE_OR_DUPLICATE" in host["issues"]
    assert "PAIRED_FROZEN_IDENTITY_MISMATCH" in host["pairs"][0]["issues"]
    assert host["evidence_ready"] is False


def test_experimental_window_is_configurable_without_automatic_promotion():
    document = trial_document()
    document["window"]["duration_days"] = 14
    report = report_trial(document)
    assert report["trial_status"] == "ongoing" and report["decision"] == "experimental"
    assert report["supported"] is False
    for duration in (6, 15):
        invalid = deepcopy(document)
        invalid["window"]["duration_days"] = duration
        report = report_trial(invalid)
        assert report["decision"] == "unsupported" and report["evidence_errors"]


def test_empty_or_frame_only_input_returns_schema_instead_of_fabricated_native_metrics():
    report = report_trial({})
    assert report["supported"] is False and report["trial_status"] == "unavailable"
    assert report["input_schema"]["$defs"]["_Layer"]["properties"]["measurement"]["enum"] == [
        "native_main_residual", "unavailable",
    ]
    assert report["evidence_errors"]


def test_equal_parent_residual_is_not_a_reduction():
    document = trial_document()
    pair = document["hosts"][0]["pairs"][0]
    pair["fork"]["residual"] = deepcopy(pair["inline"]["residual"])
    document["thresholds"]["max_main_bytes_ratio"] = 1.0
    document["thresholds"]["max_main_tokens_ratio"] = 1.0
    report = report_trial(document)
    assert report["hosts"][0]["evidence_ready"] is False
    assert report["hosts"][0]["pairs"][0]["comparison"]["residual_improved"] is False


@pytest.mark.parametrize("metric", ["precision_margin", "recall_margin"])
def test_quality_regression_cannot_be_authorized_by_a_margin(metric):
    document = trial_document()
    document["thresholds"][metric] = 0.01
    report = report_trial(document)
    assert report["decision"] == "unsupported" and report["evidence_errors"]


def test_paired_correct_no_match_cases_keep_undefined_metrics_without_inventing_regression():
    document = trial_document()
    pair = document["hosts"][0]["pairs"][0]
    for strategy in ("inline", "fork"):
        pair[strategy]["quality"].update(tp=0, fp=0, fn=0)
    host = report_trial(document)["hosts"][0]
    comparison = host["pairs"][0]["comparison"]
    assert comparison["inline_quality"]["precision"] is None
    assert comparison["fork_quality"]["recall"] is None
    assert comparison["quality_noninferior"] is True
    assert host["evidence_ready"] is True


@pytest.mark.parametrize("change", ["fork_only", "both_arms", "missing"])
def test_intermediary_provider_route_cannot_pass_pairing(change):
    document = trial_document()
    pair = document["hosts"][0]["pairs"][0]
    for strategy in ("fork",) if change == "fork_only" else ("inline", "fork"):
        if change == "missing":
            del pair[strategy]["frozen"]["provider_route"]
        else:
            pair[strategy]["frozen"]["provider_route"] = "proxy:headroom:sha256-of-proxy-base-url"
    report = report_trial(document)
    assert report["decision"] == "unsupported"
    if change == "missing":
        assert report["evidence_errors"]
        return
    issues = report["hosts"][0]["pairs"][0]["issues"]
    assert "FORK:FROZEN_IDENTITY_OR_WINDOW_MISMATCH" in issues
    assert ("PAIRED_FROZEN_IDENTITY_MISMATCH" in issues) is (change == "fork_only")
    assert ("INLINE:FROZEN_IDENTITY_OR_WINDOW_MISMATCH" in issues) is (change == "both_arms")


@pytest.mark.parametrize(("pairs", "status"), [(19, "insufficient_samples"), (20, "computed")])
def test_p95_requires_the_stated_sample_floor(pairs, status):
    report = report_trial(paired_trial(["inline", "fork"] * (pairs // 2) + ["inline"] * (pairs % 2)))
    assert report["latency_p95_min_samples"] == 20
    host = report["hosts"][0]
    assert host["evidence_ready"] is True
    summary = host["latency_completed_attempts"]["inline"]["recall_ms"]
    assert summary["count"] == pairs and summary["p50"] == 100
    assert summary["p95_status"] == status
    assert (summary["p95"] is None) is (status == "insufficient_samples")


@pytest.mark.parametrize("first_arms", [["inline", "inline"], ["fork", "fork"], [None, None], ["inline", None]])
def test_uncounterbalanced_arm_order_blocks_host_evidence(first_arms):
    host = report_trial(paired_trial(first_arms))["hosts"][0]
    assert "ARM_ORDER_NOT_COUNTERBALANCED" in host["issues"]
    assert all(pair["evidence_ready"] for pair in host["pairs"])
    assert host["evidence_ready"] is False and host["decision"] == "unsupported"


def test_counterbalanced_arm_order_keeps_host_evidence_ready():
    report = report_trial(paired_trial(["inline", "fork"]))
    host = report["hosts"][0]
    assert host["issues"] == [] and host["paired_valid"] == 2
    assert host["evidence_ready"] is True and report["decision"] == "experimental"


def test_reused_execution_evidence_never_counts_as_independent_pairs():
    host = report_trial(paired_trial(["inline", "fork"] * 10, distinct=False))["hosts"][0]
    assert "DUPLICATE_EXECUTION_EVIDENCE" in host["issues"]
    assert host["evidence_ready"] is False and host["decision"] == "unsupported"
    summary = host["latency_completed_attempts"]["inline"]["recall_ms"]
    assert summary["count"] == 1 and summary["p95"] is None
