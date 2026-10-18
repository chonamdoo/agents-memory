from __future__ import annotations

import math
import os
import random
import stat
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from .domain import canonical_digest
from .wire import decode_json_value, validate_wire

MAX_PROTOCOL_BYTES = 8 * 1024 * 1024
MAX_OBSERVATIONS_BYTES = 64 * 1024 * 1024
MAX_ROWS = 100_000
MAX_TASKS = 10_000
MAX_CASES = 10_000
MAX_REFS = 1024
MAX_CLAIMS = 4096
MODES = ("memory_on", "required_only")
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", max_length=64)]
Identity = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$", max_length=128)]
Reason = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$", max_length=64)]
Count = Annotated[int, Field(ge=0, le=2**63 - 1)]
Measurement = Annotated[float, Field(ge=0, le=1e100, allow_inf_nan=False)]
Mode = Literal["memory_on", "required_only"]
Status = Literal[
    "native", "blocked", "unsupported", "busy", "failed", "timeout", "aborted",
    "unknown", "completed", "not_started", "incomplete",
]
CostBasis = Literal["unknown", "native_client_estimate", "frozen_price_estimate"]


class _Projection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)

    @field_validator("*", mode="before")
    @classmethod
    def _sequences(cls, value: Any) -> Any:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("schema", "resamples", mode="before", check_fields=False)
    @classmethod
    def _integer_literals(cls, value: Any) -> Any:
        if type(value) is not int:
            raise ValueError("SCORING_INTEGER_REQUIRED")
        return value


class GroundingRef(_Projection):
    source_id: Identity
    revision: Annotated[int, Field(ge=1, le=2**63 - 1)]
    byte_start: Count
    byte_end: Count
    quote_digest: Digest

    @model_validator(mode="after")
    def _span(self) -> Self:
        if self.byte_end <= self.byte_start:
            raise ValueError("SCORING_EMPTY_OR_REVERSED_SPAN")
        return self

    def key(self) -> tuple[str, int, int, int, str]:
        return (self.source_id, self.revision, self.byte_start, self.byte_end, self.quote_digest)


def _unique(values: Iterable[Any], code: str) -> None:
    seen = set()
    for value in values:
        if value in seen:
            raise ValueError(code)
        seen.add(value)


class CodingTask(_Projection):
    task_id: Identity
    task_revision: Identity
    cluster_id: Identity


class RetrievalCase(_Projection):
    case_id: Identity
    cluster_id: Identity
    relevant_claim_ids: tuple[Identity, ...] = Field(max_length=MAX_CLAIMS)
    irrelevant_claim_ids: tuple[Identity, ...] = Field(max_length=MAX_CLAIMS)
    judgment_complete: bool
    grounding_refs: tuple[GroundingRef, ...] = Field(max_length=MAX_REFS)

    @model_validator(mode="after")
    def _labels(self) -> Self:
        _unique(self.relevant_claim_ids, "SCORING_DUPLICATE_LABEL")
        _unique(self.irrelevant_claim_ids, "SCORING_DUPLICATE_LABEL")
        _unique((ref.key() for ref in self.grounding_refs), "SCORING_DUPLICATE_SPAN")
        if set(self.relevant_claim_ids) & set(self.irrelevant_claim_ids):
            raise ValueError("SCORING_CONFLICTING_LABEL")
        return self


class ScoringProtocol(_Projection):
    schema: Literal[1]
    scope: Literal["engineering", "evaluation"]
    manifest_digest: Digest
    source_commit: Annotated[str, Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$", max_length=64)]
    controller_digest: Digest
    verifier_digest: Digest
    corpus_digest: Digest
    gold_digest: Digest
    workload_digest: Digest
    required_rules_digest: Digest
    native_identity_digest: Digest
    seed: Annotated[int, Field(ge=0, le=2**64 - 1)]
    resamples: Literal[10000]
    confidence: Literal[0.95]
    coding_tasks: tuple[CodingTask, ...] = Field(max_length=MAX_TASKS)
    retrieval_cases: tuple[RetrievalCase, ...] = Field(max_length=MAX_CASES)

    @model_validator(mode="after")
    def _identities(self) -> Self:
        _unique((task.task_id for task in self.coding_tasks), "SCORING_DUPLICATE_TASK")
        _unique((task.cluster_id for task in self.coding_tasks), "SCORING_TASK_NOT_INDEPENDENT_CLUSTER")
        _unique((case.case_id for case in self.retrieval_cases), "SCORING_DUPLICATE_CASE")
        return self


class _Usage(_Projection):
    latency_seconds: Measurement | None = None
    input_tokens: Count | None = None
    output_tokens: Count | None = None
    total_tokens: Count | None = None
    cost_usd: Measurement | None = None
    cost_basis: CostBasis

    @model_validator(mode="after")
    def _usage(self) -> Self:
        if (self.cost_usd is None) != (self.cost_basis == "unknown"):
            raise ValueError("SCORING_COST_BASIS_MISMATCH")
        if self.total_tokens is not None:
            known = [value for value in (self.input_tokens, self.output_tokens) if value is not None]
            if sum(known) > self.total_tokens:
                raise ValueError("SCORING_TOKEN_TOTAL_MISMATCH")
        return self


class ArmObservation(_Usage):
    schema: Literal[1]
    manifest_digest: Digest
    pair_id: Identity
    pair_attempt: Annotated[int, Field(ge=0, le=10000)]
    task_id: Identity
    task_revision: Identity
    cluster_id: Identity
    repeat_index: Annotated[int, Field(ge=0, le=2)]
    mode: Mode
    invocation_id: Identity
    status: Status
    comparable: bool
    comparability_reasons: tuple[Reason, ...] = Field(max_length=64)
    contaminated: bool
    native_identity_observed: bool
    corpus_before_digest: Digest | None = None
    corpus_after_digest: Digest | None = None
    required_rules_digest: Digest | None = None
    native_identity_digest: Digest | None = None
    structural_pass: bool | None = None
    functional_success: bool | None = None
    cleanup_complete: bool | None = None
    control_receipt_digest: Digest | None = None
    verifier_receipt_digest: Digest | None = None
    artifact_digest: Digest | None = None
    cpu_seconds: Measurement | None = None
    peak_rss_bytes: Count | None = None
    disk_bytes: Count | None = None
    evidence_refs: Mapping[Identity, Digest] = Field(default_factory=dict, max_length=64)

    @field_validator("evidence_refs")
    @classmethod
    def _freeze_evidence(cls, value: Mapping[str, str]) -> Mapping[str, str]:
        return MappingProxyType(value)

    @field_serializer("evidence_refs")
    def _serialize_evidence(self, value: Mapping[str, str]) -> dict[str, str]:
        return dict(value)

    @model_validator(mode="after")
    def _reasons(self) -> Self:
        _unique(self.comparability_reasons, "SCORING_DUPLICATE_REASON")
        return self


class RetrievalObservation(_Usage):
    schema: Literal[1]
    manifest_digest: Digest
    case_id: Identity
    cluster_id: Identity
    attempt_id: Identity
    mode: Mode
    status: Status
    comparable: bool
    comparability_reasons: tuple[Reason, ...] = Field(max_length=64)
    contaminated: bool
    returned_claim_ids: tuple[Identity, ...] | None = Field(default=None, max_length=MAX_CLAIMS)
    manifest_complete: bool | None = None
    final_context_digest: Digest | None = None
    grounding_refs: tuple[GroundingRef, ...] | None = Field(default=None, max_length=MAX_REFS)

    @model_validator(mode="after")
    def _identities(self) -> Self:
        _unique(self.comparability_reasons, "SCORING_DUPLICATE_REASON")
        if self.returned_claim_ids is not None:
            _unique(self.returned_claim_ids, "SCORING_DUPLICATE_RETURNED_CLAIM")
        if self.grounding_refs is not None:
            _unique((ref.key() for ref in self.grounding_refs), "SCORING_DUPLICATE_SPAN")
        return self


def _model(model: type[_Projection], value: Any) -> Any:
    if isinstance(value, model):
        # Revalidate nested state too; model_copy(update=...) does not validate.
        value = value.model_dump(mode="json")
    if not isinstance(value, Mapping):
        raise ValueError("SCORING_OBJECT_REQUIRED")
    return validate_wire(model, dict(value))


def _rows(model: type[_Projection], values: Iterable[Any]) -> list[Any]:
    result = []
    for value in values:
        if len(result) >= MAX_ROWS:
            raise ValueError("SCORING_ROW_LIMIT")
        result.append(_model(model, value))
    return result


def _percentile(ordered: list[float], probability: float) -> float | None:
    if not ordered:
        return None
    position = (len(ordered) - 1) * probability
    lo = math.floor(position)
    hi = math.ceil(position)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (position - lo)


def _interval(clusters: Mapping[str, tuple[float, int]], seed: int, method: str) -> dict[str, Any]:
    ordered = [clusters[key] for key in sorted(clusters)]
    denominator = sum(count for _, count in ordered)
    estimate = sum(value for value, _ in ordered) / denominator if denominator else None
    samples = []
    rng = random.Random(seed)
    if ordered:
        for _ in range(10000):
            numerator = 0.0
            count = 0
            for _ in ordered:
                value, weight = ordered[rng.randrange(len(ordered))]
                numerator += value
                count += weight
            samples.append(numerator / count)
        samples.sort()
    return {
        "estimate": estimate, "lower": _percentile(samples, 0.025),
        "upper": _percentile(samples, 0.975), "denominator": denominator,
        "clusters": len(ordered), "seed": seed, "resamples": 10000, "confidence": 0.95,
        "method": method,
        "rng": "python_random_MT19937_randrange",
    }


def _metric(
    values: Iterable[tuple[str, float]], seed: int,
    method: str = "paired_task_cluster_percentile_linear",
) -> dict[str, Any]:
    clusters: dict[str, tuple[float, int]] = {}
    for cluster, value in values:
        total, count = clusters.get(cluster, (0.0, 0))
        clusters[cluster] = (total + value, count + 1)
    return _interval(clusters, seed, method)


def _measure(rows: list[Any], field: str, *, additive: bool = True) -> dict[str, Any]:
    values = sorted(getattr(row, field) for row in rows if getattr(row, field) is not None)
    known_total = math.fsum(values) if values and isinstance(values[0], float) else sum(values)
    return {
        "observed": len(values), "unknown": len(rows) - len(values), "attempts": len(rows),
        "coverage": len(values) / len(rows) if rows else None,
        "known_partial_total": known_total if additive else None,
        "total": known_total if additive and values and len(values) == len(rows) else None,
        "p50": _percentile(values, 0.5), "p95": _percentile(values, 0.95),
        "maximum": values[-1] if values else None,
    }


def _accounting(rows: list[Any]) -> dict[str, Any]:
    return {
        "attempts": len(rows), "statuses": dict(sorted(Counter(row.status for row in rows).items())),
        "noncompleted": sum(row.status != "completed" for row in rows),
        "contaminated": sum(row.contaminated for row in rows),
        "declared_incomparable": sum(not row.comparable or bool(row.comparability_reasons) for row in rows),
        "cost_basis": dict(sorted(Counter(row.cost_basis for row in rows).items())),
        "measurements": {field: _measure(rows, field) for field in (
            "latency_seconds", "input_tokens", "output_tokens", "total_tokens", "cost_usd",
        )},
        "completed_latency": _measure([row for row in rows if row.status == "completed"], "latency_seconds"),
    }


def _public_observation(row: ArmObservation | RetrievalObservation) -> dict[str, Any]:
    fields = (
        "status", "comparable", "comparability_reasons", "contaminated", "latency_seconds",
        "input_tokens", "output_tokens", "total_tokens", "cost_usd", "cost_basis",
    )
    result = {field: getattr(row, field) for field in fields}
    result["comparability_reasons"] = list(row.comparability_reasons)
    if isinstance(row, ArmObservation):
        result.update({field: getattr(row, field) for field in (
            "invocation_id", "structural_pass", "functional_success", "cleanup_complete",
            "cpu_seconds", "peak_rss_bytes", "disk_bytes",
        )})
    return result


def _arm_reasons(protocol: ScoringProtocol, arm: ArmObservation) -> set[str]:
    reasons = set()
    if arm.status != "completed":
        reasons.add("NATIVE_NOT_COMPLETED")
    if not arm.comparable or arm.comparability_reasons:
        reasons.add("INCOMPARABLE")
    if arm.contaminated:
        reasons.add("CONTAMINATED")
    if not arm.native_identity_observed:
        reasons.add("NATIVE_IDENTITY_UNOBSERVED")
    for field, expected in (
        ("corpus_before_digest", protocol.corpus_digest),
        ("corpus_after_digest", protocol.corpus_digest),
        ("required_rules_digest", protocol.required_rules_digest),
        ("native_identity_digest", protocol.native_identity_digest),
    ):
        if getattr(arm, field) != expected:
            reasons.add(field.upper() + "_MISMATCH_OR_UNKNOWN")
    if arm.structural_pass is None or arm.structural_pass is True and arm.functional_success is None:
        reasons.add("VERIFICATION_UNKNOWN")
    if arm.cleanup_complete is not True:
        reasons.add("CLEANUP_INCOMPLETE_OR_UNKNOWN")
    if any(getattr(arm, field) is None for field in (
        "control_receipt_digest", "verifier_receipt_digest", "artifact_digest",
    )):
        reasons.add("VERIFICATION_EVIDENCE_MISSING")
    return reasons


def _coding(protocol: ScoringProtocol, rows: list[ArmObservation]) -> dict[str, Any]:
    tasks = {task.task_id: task for task in protocol.coding_tasks}
    groups: dict[tuple[str, int], dict[str, ArmObservation]] = defaultdict(dict)
    pair_slots = {}
    slot_pairs = {}
    invocations = set()
    for row in rows:
        task = tasks.get(row.task_id)
        if task is None or (row.task_revision, row.cluster_id) != (task.task_revision, task.cluster_id):
            raise ValueError("SCORING_TASK_IDENTITY_MISMATCH")
        slot = (row.task_id, row.repeat_index)
        if pair_slots.setdefault(row.pair_id, slot) != slot or slot_pairs.setdefault(slot, row.pair_id) != row.pair_id:
            raise ValueError("SCORING_PAIR_IDENTITY_MISMATCH")
        group = groups[(row.pair_id, row.pair_attempt)]
        if row.mode in group or row.invocation_id in invocations:
            raise ValueError("SCORING_DUPLICATE_ARM")
        invocations.add(row.invocation_id)
        group[row.mode] = row
    paired = []
    excluded = Counter()
    valid_slots = set()
    valid_pairs = []
    for (pair_id, attempt), arms in sorted(groups.items()):
        reasons = set()
        if len(arms) != 2:
            reasons.add("MISSING_ARM")
        for arm in arms.values():
            reasons.update(_arm_reasons(protocol, arm))
        if len(arms) == 2 and arms[MODES[0]].control_receipt_digest != arms[MODES[1]].control_receipt_digest:
            reasons.add("CONTROL_IDENTITY_MISMATCH")
        if reasons:
            excluded.update(reasons)
        else:
            on, off = (arms[mode] for mode in MODES)
            valid_slots.add((on.task_id, on.repeat_index))
            valid_pairs.append((on, off))
        paired.append({
            "pair_id": pair_id, "pair_attempt": attempt, "valid": not reasons,
            "exclusion_reasons": sorted(reasons), "observed_arms": len(arms),
            "arms": {mode: _public_observation(arms[mode]) if mode in arms else None for mode in MODES},
            "memory_on_success": _success(arms["memory_on"]) if not reasons else None,
            "required_only_success": _success(arms["required_only"]) if not reasons else None,
        })
    success_metrics = {
        mode: _metric(((on.cluster_id, _success(on if mode == "memory_on" else off))
                       for on, off in valid_pairs), protocol.seed) for mode in MODES
    }
    difference = _metric(((on.cluster_id, _success(on) - _success(off)) for on, off in valid_pairs), protocol.seed)
    paired_measurements = {}
    for field in ("latency_seconds", "input_tokens", "output_tokens", "total_tokens", "cost_usd",
                  "cpu_seconds", "peak_rss_bytes", "disk_bytes"):
        measured = [(on.cluster_id, getattr(on, field) - getattr(off, field)) for on, off in valid_pairs
                    if getattr(on, field) is not None and getattr(off, field) is not None]
        paired_measurements[field] = _metric(measured, protocol.seed)
        paired_measurements[field]["unknown_pairs"] = len(valid_pairs) - len(measured)
    observed_slots = set(slot_pairs)
    return {
        "scheduled_pairs": len(tasks) * 3, "observed_slots": len(observed_slots),
        "unobserved_slots": len(tasks) * 3 - len(observed_slots),
        "pair_attempts": len(groups), "retry_pair_attempts": sum(attempt > 0 for _, attempt in groups),
        "missing_arms": sum(2 - len(arms) for arms in groups.values()),
        "valid_pair_attempts": len(valid_pairs), "valid_scheduled_slots": len(valid_slots),
        "valid_tasks": len({task for task, _ in valid_slots}),
        "complete_three_repeat_tasks": sum(all((task, repeat) in valid_slots for repeat in range(3)) for task in tasks),
        "excluded_pair_attempts": len(groups) - len(valid_pairs), "exclusion_counts": dict(sorted(excluded.items())),
        "pairs": paired, "success": success_metrics, "success_difference": difference,
        "paired_measurement_differences": paired_measurements,
        "arms": {mode: _arm_accounting([row for row in rows if row.mode == mode]) for mode in MODES},
        "statistics_scope": "all_valid_pair_attempts_diagnostic_not_retry_selection",
    }


def _success(arm: ArmObservation) -> int:
    return int(arm.structural_pass is True and arm.functional_success is True)


def _arm_accounting(rows: list[ArmObservation]) -> dict[str, Any]:
    result = _accounting(rows)
    result["verification_failures"] = sum(row.structural_pass is False or row.functional_success is False for row in rows)
    result["verification_unknown"] = sum(row.structural_pass is None or row.functional_success is None for row in rows)
    result["successful_whole_task_latency"] = _measure([
        row for row in rows if row.status == "completed" and row.structural_pass is True
        and row.functional_success is True and row.cleanup_complete is True
        and row.control_receipt_digest is not None and row.verifier_receipt_digest is not None
        and row.artifact_digest is not None
    ], "latency_seconds")
    result["resources"] = {field: _measure(rows, field, additive=field == "cpu_seconds")
                           for field in ("cpu_seconds", "peak_rss_bytes", "disk_bytes")}
    return result


def _retrieval(protocol: ScoringProtocol, rows: list[RetrievalObservation]) -> dict[str, Any]:
    cases = {case.case_id: case for case in protocol.retrieval_cases}
    seen = set()
    scored = []
    metrics: dict[str, dict[str, list[tuple[str, float]]]] = {
        mode: defaultdict(list) for mode in MODES
    }
    for row in sorted(rows, key=lambda row: (row.case_id, row.attempt_id, row.mode)):
        case = cases.get(row.case_id)
        if case is None or row.cluster_id != case.cluster_id:
            raise ValueError("SCORING_RETRIEVAL_IDENTITY_MISMATCH")
        key = (row.case_id, row.attempt_id, row.mode)
        if key in seen:
            raise ValueError("SCORING_DUPLICATE_RETRIEVAL")
        seen.add(key)
        valid = (row.status == "completed" and row.comparable and not row.comparability_reasons
                 and not row.contaminated and row.manifest_complete is True
                 and row.returned_claim_ids is not None and row.final_context_digest is not None
                 and row.grounding_refs is not None)
        result: dict[str, Any] = {
            "case_id": row.case_id, "attempt_id": row.attempt_id, "mode": row.mode,
            "valid_final_read": valid, "observation": _public_observation(row),
        }
        if valid:
            returned = set(row.returned_claim_ids)
            relevant, irrelevant = set(case.relevant_claim_ids), set(case.irrelevant_claim_ids)
            hits = len(returned & relevant)
            judged = len(returned & (relevant | irrelevant))
            unknown = len(returned) - judged
            precision = hits / len(returned) if returned and not unknown else None
            if not returned and relevant:
                precision = 0.0
            recall = hits / len(relevant) if relevant and case.judgment_complete else None
            expected = {ref.key() for ref in case.grounding_refs}
            delivered = {ref.key() for ref in row.grounding_refs}
            grounding_hits = len(expected & delivered)
            grounding_precision = grounding_hits / len(delivered) if delivered else None
            grounding_recall = grounding_hits / len(expected) if expected else None
            result.update({
                "returned": len(returned), "hits": hits, "judged_returned": judged,
                "unjudged_returned": unknown, "gold_relevant": len(relevant),
                "judgment_complete": case.judgment_complete, "precision": precision,
                "judged_precision": hits / judged if judged else None, "recall": recall,
                "no_match": not relevant and case.judgment_complete,
                "abstained": not returned, "grounding_precision": grounding_precision,
                "grounding_recall": grounding_recall, "grounding_hits": grounding_hits,
                "grounding_errors": len(delivered - expected),
                "grounding_missing": len(expected - delivered),
                "grounding_exact": expected == delivered,
            })
            for metric in ("precision", "recall", "grounding_precision", "grounding_recall"):
                if result[metric] is not None:
                    metrics[row.mode][metric].append((case.cluster_id, result[metric]))
        scored.append(result)
    mode_summaries = {}
    for mode in MODES:
        finals = [item for item in scored if item["mode"] == mode and item["valid_final_read"]]
        no_match = [item for item in finals if item["no_match"]]
        mode_summaries[mode] = {
            "valid_final_reads": len(finals),
            "positive_recall_denominator": sum(item["recall"] is not None for item in finals),
            "precision_denominator": sum(item["precision"] is not None for item in finals),
            "unjudged_returned": sum(item["unjudged_returned"] for item in finals),
            "no_match_cases": len(no_match),
            "no_match_false_returns": sum(not item["abstained"] for item in no_match),
            "positive_false_empty": sum(item["gold_relevant"] > 0 and item["judgment_complete"]
                                       and item["abstained"] for item in finals),
            "grounding_errors": sum(item["grounding_errors"] for item in finals),
            "grounding_missing": sum(item["grounding_missing"] for item in finals),
        }
    return {
        "cases": len(cases), "attempts": len(rows), "valid_final_reads": sum(item["valid_final_read"] for item in scored),
        "invalid_or_unknown_final_reads": sum(not item["valid_final_read"] for item in scored),
        "unobserved_case_modes": len(cases) * 2 - len({(row.case_id, row.mode) for row in rows}),
        "observations": scored,
        "modes": {mode: {
            "accounting": _accounting([row for row in rows if row.mode == mode]),
            "summary": mode_summaries[mode],
            "metrics": {name: _metric(metrics[mode][name], protocol.seed,
                                      "retrieval_case_cluster_percentile_linear") for name in (
                "precision", "recall", "grounding_precision", "grounding_recall",
            )},
        } for mode in MODES},
        "relevance_basis": "final_delivered_claim_ids_only",
        "grounding_basis": "exact_source_revision_byte_span_quote_digest_not_semantic_attestation",
        "unavailable_metrics": ["candidate_recall_at_20", "feasible_coverage", "condition_omission", "false_promotion"],
    }


def score_run(
    protocol: ScoringProtocol | Mapping[str, Any],
    attempts: Iterable[ArmObservation | Mapping[str, Any]],
    retrieval: Iterable[RetrievalObservation | Mapping[str, Any]],
) -> dict[str, Any]:
    frozen = _model(ScoringProtocol, protocol)
    arms = _rows(ArmObservation, attempts)
    reads = _rows(RetrievalObservation, retrieval)
    if any(row.manifest_digest != frozen.manifest_digest for row in (*arms, *reads)):
        raise ValueError("SCORING_MANIFEST_MISMATCH")
    coding = _coding(frozen, arms)
    retrieval_report = _retrieval(frozen, reads)
    return {
        "schema": 1, "scope": frozen.scope, "manifest_digest": frozen.manifest_digest,
        "source_commit": frozen.source_commit, "independence": "provided_unattested",
        "original_acceptance": False, "original18_completed": 0,
        "engineering_nonacceptance": frozen.scope == "engineering",
        "original_targets": {"gold_cases": 120, "independent_tasks": 60, "repeats": 3, "valid_pairs": 180},
        "sample_counts_meet_original_targets": (
            len(frozen.retrieval_cases) >= 120 and len(frozen.coding_tasks) == 60
            and coding["complete_three_repeat_tasks"] == 60
        ),
        "acceptance_not_assessed": ["independent_gold_review", "independent_task_review", "native_protection",
                                    "operational_approval", "elapsed_trial", "unprojected_quality_gates"],
        "coding": coding, "retrieval": retrieval_report,
        "accounting": _accounting([*arms, *reads]),
    }


class RetrievalDiagnosticScope(_Projection):
    manifest_digest: Digest
    corpus_digest: Digest
    gold_digest: Digest
    required_rules_digest: Digest
    request_digest: Digest
    budget_digest: Digest
    source_scope_digest: Digest


class GoldEligibilityWitness(_Projection):
    scope: RetrievalDiagnosticScope
    independent_reference: Identity
    evidence_digest: Digest
    complete: bool
    eligible_claim_ids: tuple[Identity, ...] = Field(max_length=MAX_CLAIMS)
    ineligible_claim_ids: tuple[Identity, ...] = Field(max_length=MAX_CLAIMS)

    @model_validator(mode="after")
    def _partition(self) -> Self:
        _unique(self.eligible_claim_ids, "SCORING_DUPLICATE_ELIGIBILITY")
        _unique(self.ineligible_claim_ids, "SCORING_DUPLICATE_ELIGIBILITY")
        if set(self.eligible_claim_ids) & set(self.ineligible_claim_ids):
            raise ValueError("SCORING_CONFLICTING_ELIGIBILITY")
        return self


class BudgetFeasibilityWitness(_Projection):
    scope: RetrievalDiagnosticScope
    independent_reference: Identity
    evidence_digest: Digest
    eligibility_digest: Digest
    basis: Literal["complete_independent_context_item_packing"]
    complete: bool
    maximum_relevant: Annotated[int, Field(ge=0, le=3)] | None
    maximizing_claim_ids: tuple[Identity, ...] = Field(max_length=3)

    @model_validator(mode="after")
    def _maximum(self) -> Self:
        _unique(self.maximizing_claim_ids, "SCORING_DUPLICATE_FEASIBILITY")
        if self.maximum_relevant is not None and len(self.maximizing_claim_ids) != self.maximum_relevant:
            raise ValueError("SCORING_FEASIBILITY_WITNESS_CARDINALITY")
        if self.complete and self.maximum_relevant is None:
            raise ValueError("SCORING_FEASIBILITY_MAXIMUM_REQUIRED")
        return self


class DeliveredClaimJudgment(_Projection):
    scope: RetrievalDiagnosticScope
    claim_id: Identity
    expected_claim_digest: Digest
    definition_digest: Digest
    independent_reference: Identity
    evidence_digest: Digest
    phase: Literal["frozen_claim", "post_run_adjudication"]
    expected_final_context_digest: Digest | None = None
    gold_assertion_preserved: bool | None = None
    condition_omission: bool | None = None
    false_promotion: bool | None = None

    @model_validator(mode="after")
    def _context(self) -> Self:
        if ((self.phase == "post_run_adjudication" or self.false_promotion is not None)
                and self.expected_final_context_digest is None):
            raise ValueError("SCORING_QUALITY_FINAL_CONTEXT_REQUIRED")
        if self.gold_assertion_preserved is True and self.condition_omission is True:
            raise ValueError("SCORING_CONFLICTING_QUALITY")
        return self


class RetrievalDiagnosticGold(_Projection):
    schema: Literal[1]
    case_id: Identity
    cluster_id: Identity
    scope: RetrievalDiagnosticScope
    quality_definition_digest: Digest | None = None
    eligibility: GoldEligibilityWitness | None = None
    feasibility: BudgetFeasibilityWitness | None = None
    judgments: tuple[DeliveredClaimJudgment, ...] = Field(default=(), max_length=MAX_CLAIMS)

    @model_validator(mode="after")
    def _judgments(self) -> Self:
        _unique(((item.claim_id, item.expected_claim_digest, item.expected_final_context_digest)
                 for item in self.judgments), "SCORING_DUPLICATE_QUALITY_JUDGMENT")
        return self


class DeliveredClaimObservation(_Projection):
    claim_id: Identity
    claim_digest: Digest
    complete: bool


class RetrievalDiagnosticObservation(_Projection):
    schema: Literal[1]
    scope: RetrievalDiagnosticScope
    retrieval: RetrievalObservation
    candidate_status: Status | None = None
    candidate_comparable: bool | None = None
    candidate_comparability_reasons: tuple[Reason, ...] = Field(default=(), max_length=64)
    candidate_claim_ids: tuple[Identity, ...] | None = Field(default=None, max_length=20)
    candidate_manifest_digest: Digest | None = None
    candidates_complete: bool | None = None
    final_claims: tuple[DeliveredClaimObservation, ...] | None = Field(default=None, max_length=MAX_CLAIMS)

    @model_validator(mode="after")
    def _identities(self) -> Self:
        _unique(self.candidate_comparability_reasons, "SCORING_DUPLICATE_REASON")
        if self.candidate_claim_ids is not None:
            _unique(self.candidate_claim_ids, "SCORING_DUPLICATE_CANDIDATE")
        if self.final_claims is not None:
            _unique((item.claim_id for item in self.final_claims), "SCORING_DUPLICATE_FINAL_CLAIM")
        return self


def _diagnostic_scope_matches(protocol: ScoringProtocol, scope: RetrievalDiagnosticScope) -> bool:
    return (scope.manifest_digest == protocol.manifest_digest
            and scope.corpus_digest == protocol.corpus_digest
            and scope.gold_digest == protocol.gold_digest
            and scope.required_rules_digest == protocol.required_rules_digest)


def _diagnostic_witnesses(
    case: RetrievalCase, gold: RetrievalDiagnosticGold | None, scope: RetrievalDiagnosticScope,
) -> tuple[set[str] | None, int | None, set[str]]:
    reasons: set[str] = set()
    if gold is None:
        return None, None, {"DIAGNOSTIC_GOLD_MISSING"}
    if gold.scope != scope:
        return None, None, {"DIAGNOSTIC_SCOPE_MISMATCH"}
    witness = gold.eligibility
    if not case.judgment_complete:
        return None, None, {"RAW_GOLD_INCOMPLETE"}
    if witness is None or not witness.complete:
        return None, None, {"ELIGIBILITY_INCOMPLETE_OR_MISSING"}
    if witness.scope != scope:
        return None, None, {"ELIGIBILITY_SCOPE_MISMATCH"}
    eligible = set(witness.eligible_claim_ids)
    if eligible | set(witness.ineligible_claim_ids) != set(case.relevant_claim_ids):
        return None, None, {"ELIGIBILITY_PARTITION_MISMATCH"}
    feasible = gold.feasibility
    if feasible is None or not feasible.complete or feasible.maximum_relevant is None:
        reasons.add("FEASIBILITY_INCOMPLETE_OR_MISSING")
    elif feasible.scope != scope:
        reasons.add("FEASIBILITY_SCOPE_MISMATCH")
    elif feasible.eligibility_digest != canonical_digest(witness):
        reasons.add("FEASIBILITY_ELIGIBILITY_MISMATCH")
    elif not set(feasible.maximizing_claim_ids) <= eligible or feasible.maximum_relevant > len(eligible):
        reasons.add("FEASIBILITY_ELIGIBLE_SET_MISMATCH")
    else:
        return eligible, feasible.maximum_relevant, reasons
    return eligible, None, reasons


def _diagnostic_quality(
    gold: RetrievalDiagnosticGold | None, observation: RetrievalDiagnosticObservation,
) -> tuple[dict[str, DeliveredClaimJudgment], set[str]]:
    reasons: set[str] = set()
    matched: dict[str, DeliveredClaimJudgment] = {}
    if gold is None or gold.scope != observation.scope:
        return matched, {"QUALITY_GOLD_MISSING_OR_SCOPE_MISMATCH"}
    if gold.quality_definition_digest is None:
        return matched, {"QUALITY_DEFINITION_MISSING"}
    for claim in observation.final_claims or ():
        choices = [item for item in gold.judgments
                   if item.claim_id == claim.claim_id and item.scope == observation.scope
                   and item.definition_digest == gold.quality_definition_digest
                   and item.expected_claim_digest == claim.claim_digest
                   and (item.expected_final_context_digest is None
                        or item.expected_final_context_digest == observation.retrieval.final_context_digest)]
        if len(choices) == 1:
            matched[claim.claim_id] = choices[0]
        elif choices:
            reasons.add("QUALITY_JUDGMENT_AMBIGUOUS")
        else:
            reasons.add("QUALITY_JUDGMENT_MISSING_OR_MISMATCH")
    return matched, reasons


def _diagnostic_result(
    case: RetrievalCase, gold: RetrievalDiagnosticGold | None,
    observation: RetrievalDiagnosticObservation,
) -> dict[str, Any]:
    row = observation.retrieval
    eligible, maximum, reasons = _diagnostic_witnesses(case, gold, observation.scope)
    comparable = row.comparable and not row.comparability_reasons and not row.contaminated
    candidates_valid = (observation.candidate_comparable is True
                        and not observation.candidate_comparability_reasons and not row.contaminated
                        and observation.candidate_status == "completed"
                        and observation.candidates_complete is True
                        and observation.candidate_claim_ids is not None
                        and observation.candidate_manifest_digest is not None)
    final_valid = (comparable and row.status == "completed" and row.manifest_complete is True
                   and row.returned_claim_ids is not None and row.final_context_digest is not None
                   and row.grounding_refs is not None and observation.final_claims is not None)
    if final_valid:
        final_valid = (set(row.returned_claim_ids) == {item.claim_id for item in observation.final_claims}
                       and len(observation.final_claims) <= 3
                       and all(item.complete for item in observation.final_claims))
    if not candidates_valid:
        reasons.add("CANDIDATES_INCOMPLETE_OR_INCOMPARABLE")
    if not final_valid:
        reasons.add("FINAL_CLAIMS_INCOMPLETE_OR_INCOMPARABLE")
    result: dict[str, Any] = {
        "case_id": row.case_id, "cluster_id": case.cluster_id, "attempt_id": row.attempt_id,
        "mode": row.mode, "observation": _public_observation(row),
        "valid_candidates": candidates_valid, "valid_final_claims": final_valid,
        "candidate_status": observation.candidate_status,
        "candidate_comparable": observation.candidate_comparable,
        "candidate_comparability_reasons": list(observation.candidate_comparability_reasons),
        "raw_gold": len(case.relevant_claim_ids), "raw_gold_complete": case.judgment_complete,
        "eligible_gold": len(eligible) if eligible is not None else None,
        "ineligible_gold": len(case.relevant_claim_ids) - len(eligible) if eligible is not None else None,
        "feasible_maximum": maximum,
        "budget_impossible": bool(eligible) and maximum == 0 if maximum is not None else None,
        "no_match": not eligible if eligible is not None else None,
        "candidate_hits": None, "candidate_recall_at_20": None,
        "candidate_raw_gold_recall_at_20": None,
        "delivered": len(row.returned_claim_ids) if final_valid else None,
        "eligible_delivered_hits": None, "complete_gold_hits": None,
        "raw_gold_recall": None, "eligible_recall": None, "feasible_coverage": None,
        "ineligible_gold_delivered": None, "positive_false_empty": None,
        "no_match_false_return": None, "condition_omission": None, "false_promotion": None,
        "condition_omission_count": None, "false_promotion_count": None,
        "condition_omission_judged": 0, "false_promotion_judged": 0,
        "condition_omission_unknown": len(row.returned_claim_ids) if final_valid else None,
        "false_promotion_unknown": len(row.returned_claim_ids) if final_valid else None,
    }
    if candidates_valid and eligible is not None:
        hits = len(set(observation.candidate_claim_ids) & eligible)
        result["candidate_hits"] = hits
        if eligible:
            result["candidate_recall_at_20"] = hits / len(eligible)
        if case.relevant_claim_ids:
            result["candidate_raw_gold_recall_at_20"] = hits / len(case.relevant_claim_ids)
    if final_valid:
        returned = set(row.returned_claim_ids)
        judgments, quality_reasons = _diagnostic_quality(gold, observation)
        reasons.update(quality_reasons)
        for name in ("condition_omission", "false_promotion"):
            labels = [getattr(judgments[item], name) for item in returned if item in judgments
                      and getattr(judgments[item], name) is not None]
            result[f"{name}_judged"] = len(labels)
            result[f"{name}_unknown"] = len(returned) - len(labels)
            if len(labels) == len(returned):
                result[f"{name}_count"] = sum(labels)
                if labels:
                    result[name] = sum(labels) / len(labels)
        if eligible is not None:
            relevant = returned & eligible
            result["eligible_delivered_hits"] = len(relevant)
            result["ineligible_gold_delivered"] = len(returned & (set(case.relevant_claim_ids) - eligible))
            result["positive_false_empty"] = bool(eligible) and not returned
            result["no_match_false_return"] = not eligible and bool(returned)
            preserved = [judgments[item].gold_assertion_preserved if item in judgments else None
                         for item in relevant]
            if all(value is not None for value in preserved):
                hits = sum(value is True for value in preserved)
                result["complete_gold_hits"] = hits
                if case.relevant_claim_ids:
                    result["raw_gold_recall"] = hits / len(case.relevant_claim_ids)
                if eligible:
                    result["eligible_recall"] = hits / len(eligible)
                if maximum is not None:
                    if hits > maximum:
                        reasons.add("FEASIBILITY_CONTRADICTS_DELIVERY")
                        result["budget_impossible"] = None
                        result["feasible_maximum"] = None
                    elif maximum > 0:
                        result["feasible_coverage"] = hits / maximum
            else:
                reasons.add("GOLD_PRESERVATION_UNJUDGED")
    result["reasons"] = sorted(reasons)
    return result


def score_retrieval_diagnostics(
    protocol: ScoringProtocol | Mapping[str, Any],
    gold: Iterable[RetrievalDiagnosticGold | Mapping[str, Any]],
    observations: Iterable[RetrievalDiagnosticObservation | Mapping[str, Any]],
) -> dict[str, Any]:
    frozen = _model(ScoringProtocol, protocol)
    supplements = _rows(RetrievalDiagnosticGold, gold)
    actual = _rows(RetrievalDiagnosticObservation, observations)
    cases = {case.case_id: case for case in frozen.retrieval_cases}
    _unique((item.case_id for item in supplements), "SCORING_DUPLICATE_DIAGNOSTIC_GOLD")
    by_case = {}
    for item in supplements:
        if item.case_id not in cases or item.cluster_id != cases[item.case_id].cluster_id:
            raise ValueError("SCORING_DIAGNOSTIC_GOLD_IDENTITY_MISMATCH")
        if not _diagnostic_scope_matches(frozen, item.scope):
            raise ValueError("SCORING_DIAGNOSTIC_PROTOCOL_MISMATCH")
        by_case[item.case_id] = item
    _unique(((item.retrieval.case_id, item.retrieval.attempt_id, item.retrieval.mode) for item in actual),
            "SCORING_DUPLICATE_DIAGNOSTIC_OBSERVATION")
    results = []
    for item in sorted(actual, key=lambda item: (
        item.retrieval.case_id, item.retrieval.attempt_id, item.retrieval.mode,
    )):
        row = item.retrieval
        if row.case_id not in cases or row.cluster_id != cases[row.case_id].cluster_id:
            raise ValueError("SCORING_DIAGNOSTIC_OBSERVATION_IDENTITY_MISMATCH")
        if (row.manifest_digest != frozen.manifest_digest
                or not _diagnostic_scope_matches(frozen, item.scope)):
            raise ValueError("SCORING_DIAGNOSTIC_PROTOCOL_MISMATCH")
        results.append(_diagnostic_result(cases[row.case_id], by_case.get(row.case_id), item))
    names = ("candidate_recall_at_20", "candidate_raw_gold_recall_at_20", "raw_gold_recall",
             "eligible_recall", "feasible_coverage", "condition_omission", "false_promotion")
    modes = {}
    for mode in MODES:
        selected = [item for item in results if item["mode"] == mode]
        modes[mode] = {
            "attempts": len(selected),
            "accounting": _accounting([item.retrieval for item in actual if item.retrieval.mode == mode]),
            "metrics": {name: {
                **_metric(((item["cluster_id"], item[name]) for item in selected if item[name] is not None),
                          frozen.seed, "retrieval_source_family_cluster_percentile_linear"),
                "unknown_attempts": sum(item[name] is None for item in selected),
            } for name in names},
            "summary": {
                "valid_candidates": sum(item["valid_candidates"] for item in selected),
                "valid_final_claims": sum(item["valid_final_claims"] for item in selected),
                "eligibility_unknown": sum(item["eligible_gold"] is None for item in selected),
                "feasibility_unknown": sum(item["feasible_maximum"] is None for item in selected),
                "budget_impossible": sum(item["budget_impossible"] is True for item in selected),
                "no_match": sum(item["no_match"] is True for item in selected),
                "positive_false_empty": sum(item["positive_false_empty"] is True for item in selected),
                "no_match_false_return": sum(item["no_match_false_return"] is True for item in selected),
                "ineligible_gold_delivered": (
                    sum(item["ineligible_gold_delivered"] for item in selected)
                    if selected and all(item["ineligible_gold_delivered"] is not None for item in selected)
                    else None
                ),
                "known_ineligible_gold_delivered": sum(
                    item["ineligible_gold_delivered"] or 0 for item in selected
                ),
                "ineligible_delivery_unknown_attempts": sum(
                    item["ineligible_gold_delivered"] is None for item in selected
                ),
            },
        }
    return {
        "schema": 1, "scope": frozen.scope, "manifest_digest": frozen.manifest_digest,
        "source_commit": frozen.source_commit, "independence": "provided_unattested",
        "original_acceptance": False, "original18_completed": 0,
        "engineering_nonacceptance": frozen.scope == "engineering",
        "cases": len(cases), "supplemented_cases": len(supplements), "attempts": len(actual),
        "unobserved_case_modes": len(cases) * 2 - len({
            (item.retrieval.case_id, item.retrieval.mode) for item in actual
        }),
        "observations": results, "modes": modes,
        "accounting": _accounting([item.retrieval for item in actual]),
        "candidate_basis": "complete_actual_ordered_first_stage_manifest_not_final_previews",
        "feasibility_basis": "independent_complete_context_item_maximum_not_wire_guarantee",
        "quality_basis": "independent_digest_bound_judgments_not_relevance_or_automatic_semantics",
        "acceptance_not_assessed": ["independent_human_gold_review", "witness_authenticity",
                                    "native_protection", "operational_approval", "elapsed_trial"],
    }


def _private_json(path: Path, maximum: int) -> Any:
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("SCORING_ABSOLUTE_PRIVATE_PATH_REQUIRED")
    descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in path.parts[1:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        # Pin every ancestor before applying private_io's owned regular-file policy.
        info = os.stat(path.name, dir_fd=descriptor, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("SCORING_PRIVATE_REGULAR_SINGLE_LINK_REQUIRED")
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        try:
            before = os.fstat(fd)
            if before.st_uid != os.getuid() or before.st_mode & 0o077 or before.st_size > maximum:
                raise ValueError("SCORING_PRIVATE_INPUT_DENIED")
            if (before.st_dev, before.st_ino) != (info.st_dev, info.st_ino):
                raise ValueError("SCORING_INPUT_CHANGED")
            raw = bytearray()
            while len(raw) <= maximum:
                chunk = os.read(fd, min(65536, maximum + 1 - len(raw)))
                if not chunk:
                    break
                raw.extend(chunk)
            after = os.fstat(fd)
            if len(raw) > maximum:
                raise ValueError("SCORING_INPUT_TOO_LARGE")
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_nlink) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_nlink,
            ) or len(raw) != before.st_size or after.st_nlink != 1:
                raise ValueError("SCORING_INPUT_CHANGED")
        finally:
            os.close(fd)
    except OSError:
        raise ValueError("SCORING_INPUT_UNAVAILABLE") from None
    finally:
        os.close(descriptor)
    return decode_json_value(bytes(raw))


def score_run_files(
    protocol_file: Path | str, attempts_file: Path | str, retrieval_file: Path | str,
) -> dict[str, Any]:
    protocol = _private_json(Path(protocol_file), MAX_PROTOCOL_BYTES)
    attempts = _private_json(Path(attempts_file), MAX_OBSERVATIONS_BYTES)
    retrieval = _private_json(Path(retrieval_file), MAX_OBSERVATIONS_BYTES)
    if not isinstance(attempts, list) or not isinstance(retrieval, list):
        raise ValueError("SCORING_OBSERVATION_ARRAY_REQUIRED")
    return score_run(protocol, attempts, retrieval)
