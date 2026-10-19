from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class _Document(BaseModel):
    model_config = ConfigDict(extra="forbid")


_Text = Annotated[str, Field(min_length=1)]
_Count = Annotated[int, Field(strict=True, ge=0)]
_Number = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
_Host = Literal["claude", "codex"]
_Boolean = Annotated[bool, Field(strict=True)]
_ProviderRoute = Annotated[str, Field(min_length=1, description=(
    "Identity of the model-provider route: the direct provider endpoint or any intermediary/proxy, "
    "e.g. a digest of the provider base URL plus the intermediary name."
))]
# Below 20 samples the nearest-rank 95th percentile is just the sample maximum.
P95_MIN_SAMPLES = 20


class _Observation(_Document):
    ref: _Text
    host: _Host
    generation: _Text
    source: Literal["native"]
    complete: _Boolean
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class _Window(_Document):
    started_at: datetime
    as_of: datetime
    duration_days: Annotated[int, Field(strict=True, ge=7, le=14)]

    @model_validator(mode="after")
    def ordered(self):
        if (self.started_at.tzinfo is None or self.as_of.tzinfo is None
                or self.as_of < self.started_at):
            raise ValueError("Trial timestamps must be timezone-aware and ordered")
        return self


class _Thresholds(_Document):
    frozen_plan_ref: _Text
    precision_margin: Annotated[float, Field(strict=True, ge=0, le=0)]
    recall_margin: Annotated[float, Field(strict=True, ge=0, le=0)]
    max_fn_increase: _Count
    max_condition_omission_increase: _Count
    max_exception_omission_increase: _Count
    max_conflict_omission_increase: _Count
    max_main_bytes_ratio: Annotated[float, Field(gt=0, le=1, allow_inf_nan=False)]
    max_main_tokens_ratio: Annotated[float, Field(gt=0, le=1, allow_inf_nan=False)]


class _Frozen(_Document):
    task_digest: _Text
    corpus_digest: _Text
    gold_digest: _Text
    request_digest: _Text
    required_rules_digest: _Text
    permissions_digest: _Text
    host_version: _Text
    parent_model: _Text
    provider_route: _ProviderRoute
    attempt_id: _Text


class _Quality(_Document):
    tp: _Count | None
    fp: _Count | None
    fn: _Count | None
    condition_omissions: _Count | None
    exception_omissions: _Count | None
    conflict_omissions: _Count | None
    independent_gold_ref: _Text | None
    final_delivery_observation_ref: _Text | None


class _Layer(_Document):
    actual_bytes: _Count | None = Field(description="Measured native main-context residual bytes, not MCP frame bytes.")
    actual_tokens: _Count | None = Field(description="Measured native tokens, never estimated from bytes.")
    observation_ref: _Text | None
    measurement: Literal["native_main_residual", "unavailable"] = Field(
        description="Each layer counts disjoint material actually retained by the parent; do not sum cumulative history snapshots.",
    )


class _Residual(_Document):
    first: _Layer
    inspect: _Layer
    second: _Layer
    returned: _Layer = Field(alias="return")


class _Usage(_Document):
    input_tokens: _Count | None
    output_tokens: _Count | None
    cache_read_tokens: _Count | None
    cache_creation_tokens: _Count | None
    cost_usd: _Number | None
    observation_ref: _Text | None


class _Accounting(_Document):
    parent: _Usage
    child: _Usage | None
    pipeline: _Usage
    pipeline_child_inclusion: Literal["included", "excluded", "not_applicable", "unknown"]
    cost_basis: _Text | None


class _Latency(_Document):
    recall_ms: _Number | None
    total_ms: _Number | None
    observation_ref: _Text | None


class _Proof(_Document):
    satisfied: _Boolean | None
    observation_ref: _Text | None


class _Contract(_Document):
    required_on_child_failure: _Proof
    final_spans: _Proof
    source_revision: _Proof
    eligibility_rechecks: _Proof
    unchanged_task_and_request: _Proof
    parent_final_delivery: _Proof
    full_conversation_fork: _Proof | None
    complete_manifest_inspection: _Proof
    exact_return_validation: _Proof | None
    completed_child: _Proof | None


class _Run(_Document):
    frozen: _Frozen
    parent_generation: _Text
    child_generation: _Text | None
    child_model: _Text | None
    observed_at: datetime
    status: Literal["completed", "stale", "partial", "cancelled", "failed", "unsupported"]
    native_observation_ref: _Text
    quality: _Quality
    residual: _Residual
    usage: _Accounting
    latency: _Latency
    contract: _Contract


class _Pair(_Document):
    pair_id: _Text
    inline: _Run | None
    fork: _Run | None


class _HostTrial(_Document):
    host: _Host
    host_version: _Text
    parent_model: _Text
    provider_route: _ProviderRoute
    child_model: _Text
    scheduled_pair_ids: Annotated[list[_Text], Field(min_length=1)]
    pairs: list[_Pair]


class _Trial(_Document):
    schema_version: Literal[1]
    window: _Window
    thresholds: _Thresholds
    observations: list[_Observation]
    hosts: Annotated[list[_HostTrial], Field(min_length=1)]


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    index = (len(values) - 1) * percentile
    lower = math.floor(index)
    return values[lower] + (values[math.ceil(index)] - values[lower]) * (index - lower)


def _quality(value: _Quality) -> dict:
    tp, fp, fn = value.tp, value.fp, value.fn
    return {
        "precision": tp / (tp + fp) if tp is not None and fp is not None and tp + fp else None,
        "recall": tp / (tp + fn) if tp is not None and fn is not None and tp + fn else None,
        **value.model_dump(exclude={"independent_gold_ref", "final_delivery_observation_ref"}),
    }


def _refs(value: object) -> list[str | None]:
    if isinstance(value, dict):
        return [ref for key, item in value.items() for ref in (
            [item] if key.endswith("observation_ref") else _refs(item)
        )]
    if isinstance(value, list):
        return [ref for item in value for ref in _refs(item)]
    return []


def _run_issues(run: _Run, host: _HostTrial, strategy: str, trial: _Trial,
                observations: dict[str, _Observation]) -> list[str]:
    issues = []
    if run.status != "completed":
        issues.append("RUN_" + run.status.upper())
    if (run.frozen.host_version != host.host_version or run.frozen.parent_model != host.parent_model
            or run.frozen.provider_route != host.provider_route
            or run.observed_at.tzinfo is None
            or not trial.window.started_at <= run.observed_at <= min(
                trial.window.as_of, trial.window.started_at + timedelta(days=trial.window.duration_days),
            )):
        issues.append("FROZEN_IDENTITY_OR_WINDOW_MISMATCH")
    generations = {run.parent_generation}
    if strategy == "fork":
        if (not run.child_generation or run.child_generation == run.parent_generation
                or run.child_model != host.child_model):
            issues.append("CHILD_IDENTITY_UNFROZEN")
        generations.add(run.child_generation)
    elif run.child_generation is not None or run.child_model is not None or run.usage.child is not None:
        issues.append("INLINE_CHILD_ATTRIBUTION")
    for ref in _refs(run.model_dump()):
        observation = observations.get(ref)
        if (observation is None or not observation.complete or observation.host != host.host
                or observation.generation not in generations):
            issues.append("NATIVE_OBSERVATION_UNAVAILABLE")
    parent_refs = [run.native_observation_ref, run.quality.final_delivery_observation_ref,
                   run.latency.observation_ref, run.usage.parent.observation_ref,
                   run.usage.pipeline.observation_ref]
    parent_refs.extend(layer.observation_ref for _, layer in run.residual)
    child_refs = []
    if run.usage.child is not None:
        child_refs.append(run.usage.child.observation_ref)
    for name, proof in run.contract:
        if proof is not None:
            target = child_refs if strategy == "fork" and name in {
                "complete_manifest_inspection", "completed_child",
            } else parent_refs
            target.append(proof.observation_ref)
    for refs, generation in ((parent_refs, run.parent_generation), (child_refs, run.child_generation)):
        if any(ref not in observations or observations[ref].generation != generation for ref in refs):
            issues.append("NATIVE_ACTOR_ATTRIBUTION_MISMATCH")
    quality = run.quality.model_dump()
    if any(value is None for value in quality.values()):
        issues.append("FINAL_GOLD_OR_QUALITY_UNAVAILABLE")
    for layer in run.residual.model_dump().values():
        if (layer["measurement"] != "native_main_residual" or layer["actual_bytes"] is None
                or layer["actual_tokens"] is None):
            issues.append("MAIN_NATIVE_RESIDUAL_UNAVAILABLE")
    accounting = run.usage
    usage = [accounting.parent, accounting.pipeline]
    if strategy == "fork":
        if accounting.child is None or accounting.pipeline_child_inclusion != "included":
            issues.append("PIPELINE_CHILD_COVERAGE_UNAVAILABLE")
        else:
            usage.append(accounting.child)
    elif accounting.pipeline_child_inclusion != "not_applicable":
        issues.append("INLINE_PIPELINE_COVERAGE_UNKNOWN")
    if not accounting.cost_basis or any(
        value is None for item in usage for value in item.model_dump().values()
    ):
        issues.append("NATIVE_USAGE_OR_COST_UNAVAILABLE")
    else:
        # The pipeline total covers the parent (and an included child), so it can never undercount them.
        parts = usage[:1] + usage[2:]
        for metric in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens", "cost_usd"):
            covered = sum(getattr(item, metric) for item in parts)
            slack = 1e-9 * max(1.0, abs(covered)) if metric == "cost_usd" else 0
            if getattr(accounting.pipeline, metric) + slack < covered:
                issues.append("USAGE_ACCOUNTING_INCONSISTENT")
                break
    if any(value is None for value in run.latency.model_dump().values()):
        issues.append("LATENCY_UNAVAILABLE")
    for name, proof in run.contract:
        optional = strategy == "inline" and name in {
            "full_conversation_fork", "exact_return_validation", "completed_child",
        }
        if not optional and (proof is None or proof.satisfied is not True):
            issues.append("CONTRACT_" + name.upper())
    return sorted(set(issues))


def _compare(inline: _Run, fork: _Run, thresholds: _Thresholds) -> dict:
    left, right = _quality(inline.quality), _quality(fork.quality)
    quality_checks = {}
    for key, margin in (("precision", thresholds.precision_margin), ("recall", thresholds.recall_margin)):
        if left[key] is not None and right[key] is not None:
            noninferior = right[key] >= left[key] - margin
        elif left[key] is None and right[key] is None:
            noninferior = all(
                left[name] is not None and left[name] == right[name] for name in ("tp", "fp", "fn")
            )
        else:
            noninferior = None
        quality_checks[key + "_noninferior"] = noninferior
    for key, margin in (
        ("fn", thresholds.max_fn_increase),
        ("condition_omissions", thresholds.max_condition_omission_increase),
        ("exception_omissions", thresholds.max_exception_omission_increase),
        ("conflict_omissions", thresholds.max_conflict_omission_increase),
    ):
        quality_checks[key + "_noninferior"] = (
            right[key] <= left[key] + margin if left[key] is not None and right[key] is not None else None
        )
    residual = {}
    for metric, threshold in (("actual_bytes", thresholds.max_main_bytes_ratio),
                              ("actual_tokens", thresholds.max_main_tokens_ratio)):
        totals = []
        for run in (inline, fork):
            values = [getattr(layer, metric) for _, layer in run.residual]
            totals.append(sum(values) if all(value is not None for value in values) else None)
        ratio = totals[1] / totals[0] if all(value is not None for value in totals) and totals[0] else None
        residual[metric] = {"inline": totals[0], "fork": totals[1], "ratio": ratio,
                            "passes": ratio < 1 and ratio <= threshold if ratio is not None else None}
    return {"inline_quality": left, "fork_quality": right, "quality_checks": quality_checks,
            "quality_noninferior": all(value is True for value in quality_checks.values()),
            "main_residual": residual,
            "residual_improved": all(value["passes"] is True for value in residual.values())}


def report_trial(document: dict) -> dict:
    """Evaluate supplied native evidence; neither elapsed time nor a passing report promotes support."""
    schema = _Trial.model_json_schema()
    result = {
        "schema_version": 1, "input_schema": schema, "supported": False,
        "automatic_promotion": False, "decision": "unsupported", "hosts": [],
        "limitations": [
            "Observation references and digests identify collector evidence; this pure report does not fetch or authenticate it.",
            "MCP frame bytes and estimated tokens are not native main-context residual measurements.",
            "Native delivery does not establish parent understanding or provider consumption.",
            "Quality margins are frozen descriptive paired gates, not a statistical noninferiority confidence claim.",
            "Completing the 7..14 day window requires a separate explicit support decision; no automatic promotion occurs.",
        ],
    }
    try:
        trial = _Trial.model_validate(document)
    except ValidationError as error:
        result["evidence_errors"] = error.errors(include_url=False, include_context=False, include_input=False)
        result["trial_status"] = "unavailable"
        return result
    observations = {item.ref: item for item in trial.observations}
    global_issues = []
    if len(observations) != len(trial.observations):
        global_issues.append("DUPLICATE_NATIVE_OBSERVATION")
    if len({host.host for host in trial.hosts}) != len(trial.hosts):
        global_issues.append("DUPLICATE_HOST")
    end = trial.window.started_at + timedelta(days=trial.window.duration_days)
    result["trial_status"] = "complete" if trial.window.as_of >= end else "ongoing"
    result["window"] = {**trial.window.model_dump(mode="json"), "ends_at": end.isoformat()}
    result["thresholds"] = trial.thresholds.model_dump()
    result["latency_p95_min_samples"] = P95_MIN_SAMPLES
    for host in trial.hosts:
        issues = list(global_issues)
        if (len(set(host.scheduled_pair_ids)) != len(host.scheduled_pair_ids)
                or len({pair.pair_id for pair in host.pairs}) != len(host.pairs)
                or set(host.scheduled_pair_ids) != {pair.pair_id for pair in host.pairs}):
            issues.append("PAIR_SCHEDULE_INCOMPLETE_OR_DUPLICATE")
        pairs, statuses, first_arms = [], Counter(), []
        # Each pair is one frozen attempt and each run one native generation; reused identities would
        # inflate the sample floor and pairing with copies of the same execution.
        attempts = [pair.inline.frozen.attempt_id for pair in host.pairs if pair.inline is not None]
        attempts += [pair.fork.frozen.attempt_id for pair in host.pairs if pair.fork is not None and pair.inline is None]
        generations = [generation for pair in host.pairs for run in (pair.inline, pair.fork) if run is not None
                       for generation in (run.parent_generation, run.child_generation) if generation is not None]
        if len(set(attempts)) != len(attempts) or len(set(generations)) != len(generations):
            issues.append("DUPLICATE_EXECUTION_EVIDENCE")
        sampled = set()
        latencies = {strategy: {stage: [] for stage in ("recall_ms", "total_ms")} for strategy in ("inline", "fork")}
        successes = {strategy: {stage: [] for stage in ("recall_ms", "total_ms")} for strategy in ("inline", "fork")}
        for pair in host.pairs:
            pair_issues = []
            evidence = {}
            for strategy in ("inline", "fork"):
                run = getattr(pair, strategy)
                if run is None:
                    statuses[strategy + ":missing"] += 1
                    pair_issues.append(strategy.upper() + "_MISSING")
                    continue
                statuses[strategy + ":" + run.status] += 1
                pair_issues.extend(strategy.upper() + ":" + issue for issue in _run_issues(
                    run, host, strategy, trial, observations,
                ))
                evidence[strategy] = run.model_dump(mode="json", by_alias=True)
                if run.parent_generation in sampled:
                    continue
                sampled.add(run.parent_generation)
                for stage in latencies[strategy]:
                    value = getattr(run.latency, stage)
                    if value is not None:
                        latencies[strategy][stage].append(value)
                        if run.status == "completed":
                            successes[strategy][stage].append(value)
            comparison = None
            if pair.inline is not None and pair.fork is not None:
                if pair.inline.observed_at.tzinfo is not None and pair.fork.observed_at.tzinfo is not None:
                    if pair.inline.observed_at != pair.fork.observed_at:
                        first_arms.append("inline" if pair.inline.observed_at < pair.fork.observed_at else "fork")
                    else:
                        first_arms.append(None)
                if pair.inline.frozen != pair.fork.frozen:
                    pair_issues.append("PAIRED_FROZEN_IDENTITY_MISMATCH")
                left, right = pair.inline.quality, pair.fork.quality
                if (left.independent_gold_ref != right.independent_gold_ref
                        or (all(value is not None for value in (left.tp, left.fn, right.tp, right.fn))
                            and left.tp + left.fn != right.tp + right.fn)):
                    pair_issues.append("PAIRED_GOLD_DENOMINATOR_MISMATCH")
                if pair.inline.usage.cost_basis != pair.fork.usage.cost_basis:
                    pair_issues.append("COST_BASIS_MISMATCH")
                comparison = _compare(pair.inline, pair.fork, trial.thresholds)
                if not comparison["quality_noninferior"]:
                    pair_issues.append("QUALITY_NONINFERIORITY_NOT_ESTABLISHED")
                if not comparison["residual_improved"]:
                    pair_issues.append("MAIN_RESIDUAL_REDUCTION_NOT_ESTABLISHED")
                costs = [run.usage.pipeline.cost_usd for run in (pair.inline, pair.fork)]
                comparison["pipeline_cost_difference_usd"] = (
                    costs[1] - costs[0] if all(cost is not None for cost in costs)
                    and pair.inline.usage.cost_basis == pair.fork.usage.cost_basis else None
                )
            pairs.append({"pair_id": pair.pair_id, "evidence_ready": not pair_issues,
                          "issues": sorted(set(pair_issues)), "comparison": comparison, "evidence": evidence})
        # A tie establishes neither order, so it cannot stand in for the missing one.
        if len(first_arms) >= 2 and not {"inline", "fork"} <= set(first_arms):
            issues.append("ARM_ORDER_NOT_COUNTERBALANCED")
        ready = not issues and bool(pairs) and all(pair["evidence_ready"] for pair in pairs)
        def latency_summary(values):
            return {strategy: {stage: {
                "count": len(items), "p50": _percentile(items, .5),
                "p95": _percentile(items, .95) if len(items) >= P95_MIN_SAMPLES else None,
                "p95_status": "computed" if len(items) >= P95_MIN_SAMPLES else "insufficient_samples",
            } for stage, items in stages.items()} for strategy, stages in values.items()}
        result["hosts"].append({
            "host": host.host, "host_version": host.host_version, "supported": False,
            "decision": "experimental" if ready else "unsupported", "evidence_ready": ready,
            "scheduled_pairs": len(host.scheduled_pair_ids), "reported_pairs": len(host.pairs),
            "paired_valid": sum(pair["evidence_ready"] for pair in pairs),
            "statuses": dict(statuses), "issues": issues, "pairs": pairs,
            "latency_all_attempts": latency_summary(latencies),
            "latency_completed_attempts": latency_summary(successes),
        })
    result["decision"] = "experimental" if all(host["evidence_ready"] for host in result["hosts"]) else "unsupported"
    return result
