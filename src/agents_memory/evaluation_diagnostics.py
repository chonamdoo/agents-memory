from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from itertools import combinations
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .context import render_claim
from .domain import ClaimDraft, ContextCommand, EvidenceSpan, canonical_digest
from .evaluation_artifacts import digest_bytes
from .evaluation_scoring import (
    BudgetFeasibilityWitness,
    DeliveredClaimJudgment,
    Digest,
    GoldEligibilityWitness,
    Identity,
    RetrievalDiagnosticGold,
    RetrievalDiagnosticScope,
    ScoringProtocol,
)
from .wire import decode_json, validate_wire

if TYPE_CHECKING:
    from .evaluation import EvaluationManifest

MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_EVALUATIONS = 100_000


class DiagnosticInputError(ValueError):
    pass


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise DiagnosticInputError(code)


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)

    @field_validator("*", mode="before")
    @classmethod
    def _tuples(cls, value: Any) -> Any:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("schema", "limit", mode="before", check_fields=False)
    @classmethod
    def _literal_integer(cls, value: Any) -> Any:
        if type(value) is not int:
            raise DiagnosticInputError("DIAGNOSTIC_INTEGER_REQUIRED")
        return value


class InputReference(_Input):
    name: Identity
    sha256: Digest


class RawDiagnosticScope(_Input):
    corpus_digest: Digest
    gold_digest: Digest
    required_rules_digest: Digest
    request_digest: Digest
    budget_digest: Digest
    source_scope_digest: Digest


class RawEligibility(_Input):
    scope: RawDiagnosticScope
    independent_reference: Identity
    evidence_digest: Digest
    complete: bool
    eligible_claim_ids: tuple[Identity, ...] = Field(max_length=4096)
    ineligible_claim_ids: tuple[Identity, ...] = Field(max_length=4096)


class RawFeasibility(_Input):
    scope: RawDiagnosticScope
    independent_reference: Identity
    evidence_digest: Digest
    eligibility_input_digest: Digest
    basis: Literal["complete_independent_context_item_packing"]
    complete: bool
    maximum_relevant: Annotated[int, Field(ge=0, le=3)] | None
    maximizing_claim_ids: tuple[Identity, ...] = Field(max_length=3)


class RawClaimJudgment(_Input):
    scope: RawDiagnosticScope
    claim_id: Identity
    expected_claim_digest: Digest
    definition_digest: Digest
    independent_reference: Identity
    evidence_digest: Digest
    phase: Literal["frozen_claim"]
    gold_assertion_preserved: bool | None = None
    condition_omission: bool | None = None


class RawDiagnosticCase(_Input):
    case_id: Identity
    cluster_id: Identity
    scope: RawDiagnosticScope
    budget: InputReference
    source_scope: InputReference
    rubric: InputReference | None = None
    eligibility: RawEligibility | None = None
    feasibility: RawFeasibility | None = None
    judgments: tuple[RawClaimJudgment, ...] = Field(default=(), max_length=4096)


class FrozenDiagnostics(_Input):
    schema: Literal[1]
    independence: Literal["provided_unattested"]
    cases: tuple[RawDiagnosticCase, ...] = Field(max_length=10000)


class SourceScopeInput(_Input):
    schema: Literal[1]
    case_id: Identity
    corpus_digest: Digest
    gold_digest: Digest
    request_digest: Digest
    source_mapping_digest: Digest


class QualityRubric(_Input):
    schema: Literal[1]
    definition: Annotated[str, Field(min_length=1, max_length=65536)]


class RenderedEvidence(_Input):
    source: Identity
    revision: Annotated[int, Field(ge=1)]
    source_speaker: Annotated[str, Field(max_length=4096)]
    source_event_time: str | None
    source_recorded_at: str | None
    bytes: tuple[Annotated[int, Field(ge=0)], Annotated[int, Field(ge=0)]]
    quote: Annotated[str, Field(min_length=1, max_length=65536)]

    @model_validator(mode="after")
    def exact_quote_span(self):
        _require(self.bytes[1] > self.bytes[0] and self.bytes[1] - self.bytes[0] == len(self.quote.encode("utf-8")),
                 "PACKING_EVIDENCE_SPAN")
        return self


class RenderedClaim(_Input):
    ref: Identity
    interpretation_role: Annotated[str, Field(min_length=1, max_length=128)]
    statement: Annotated[str, Field(min_length=1, max_length=2048)]
    polarity: Annotated[str, Field(min_length=1, max_length=128)]
    modality: Annotated[str, Field(min_length=1, max_length=128)]
    conditions: tuple[Annotated[str, Field(max_length=2048)], ...] = Field(max_length=1024)
    exceptions: tuple[Annotated[str, Field(max_length=2048)], ...] = Field(max_length=1024)
    evidence: tuple[RenderedEvidence, ...] = Field(min_length=1, max_length=1024)
    valid_time: tuple[str | None, str | None] | None = None
    snapshot: str | None = None

    def rendered(self) -> dict:
        return self.model_dump(mode="json", exclude_none=True) | {
            "evidence": [span.model_dump(mode="json") for span in self.evidence],
        }


class PackingRule(_Input):
    ref: Identity
    revision: Annotated[int, Field(ge=1)]
    digest: Digest
    required: bool
    applicability: Literal["true", "false", "unknown"]
    body: Annotated[str, Field(min_length=1, max_length=65536)]
    exceptions: tuple[Annotated[str, Field(max_length=2048)], ...] = Field(max_length=1024)

    def rendered(self) -> dict:
        return self.model_dump(mode="json", exclude={"digest"})


class PackingRelation(_Input):
    ref: Identity
    left: Identity
    right: Identity
    kind: Annotated[str, Field(min_length=1, max_length=128)]


class TransportLimits(_Input):
    maximum_context_bytes: Annotated[int, Field(ge=1, le=64 * 1024 * 1024)]
    maximum_item_bytes: Annotated[int, Field(ge=1, le=64 * 1024 * 1024)]
    wire_deliverability_proven: Literal[False]


class IndependentPackingInput(_Input):
    schema: Literal[1]
    case_id: Identity
    corpus_digest: Digest
    required_rules_digest: Digest
    request_digest: Digest
    source_scope_digest: Digest
    serializer: Literal["context_json_utf8_v1"]
    independent_reference: Identity
    complete: bool
    max_bytes: Annotated[int, Field(ge=256, le=6144)]
    limit: Literal[3]
    transport_limits: TransportLimits
    rules: tuple[PackingRule, ...] = Field(max_length=4096)
    claims: tuple[RenderedClaim, ...] = Field(max_length=4096)
    relations: tuple[PackingRelation, ...] = Field(max_length=12000)


@dataclass(frozen=True)
class PackingResult:
    complete: bool
    maximum_relevant: int | None
    maximizing_claim_ids: tuple[str, ...]
    evaluations: int
    reason: str | None


def _size(value: dict) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"))


def independent_context_item_feasibility(
    problem: IndependentPackingInput | dict,
    eligible_claim_ids: tuple[str, ...],
    *,
    max_evaluations: int = MAX_EVALUATIONS,
) -> PackingResult:
    """Prove a maximum from independent complete inputs, never from retrieval output."""
    problem = IndependentPackingInput.model_validate(
        problem.model_dump(mode="json") if isinstance(problem, IndependentPackingInput) else problem,
    )
    _require(type(max_evaluations) is int and 1 <= max_evaluations <= MAX_EVALUATIONS, "PACKING_WORK_BOUND")
    _unique(eligible_claim_ids, "PACKING_DUPLICATE_ELIGIBLE")
    _unique((claim.ref for claim in problem.claims), "PACKING_DUPLICATE_CLAIM")
    _unique((rule.ref for rule in problem.rules), "PACKING_DUPLICATE_RULE")
    _unique((edge.ref for edge in problem.relations), "PACKING_DUPLICATE_RELATION")
    if not problem.complete:
        return PackingResult(False, None, (), 0, "PACKING_INPUT_INCOMPLETE")
    if any(rule.required and rule.applicability == "unknown" for rule in problem.rules):
        return PackingResult(False, None, (), 0, "REQUIRED_APPLICABILITY_UNKNOWN")
    claims = {claim.ref: claim for claim in problem.claims}
    if not set(eligible_claim_ids) <= claims.keys():
        return PackingResult(False, None, (), 0, "PACKING_GOLD_RENDERING_MISSING")
    required = sorted((r for r in problem.rules if r.required and r.applicability == "true"), key=lambda r: (r.ref, r.revision))
    value = {"evidence_role": "memory_candidates_not_execution_authority", "approved_rules": [r.rendered() for r in required], "memory_candidates": [], "relations": []}
    evaluations = 1
    if _size(value) > problem.max_bytes:
        return PackingResult(True, 0, (), evaluations, None)
    optional_count = 0
    for rule in sorted((r for r in problem.rules if not r.required and r.applicability == "true"), key=lambda r: (r.ref, r.revision)):
        if optional_count == problem.limit:
            break
        if evaluations >= max_evaluations:
            return PackingResult(False, None, (), evaluations, "PACKING_WORK_EXHAUSTED")
        candidate = {**value, "approved_rules": [*value["approved_rules"], rule.rendered()]}
        evaluations += 1
        if _size(candidate) <= problem.max_bytes:
            value = candidate
            optional_count += 1
    rendered = {ref: claims[ref].rendered() for ref in eligible_claim_ids}
    claim_sizes = {ref: _size(value) for ref, value in rendered.items()}
    base_size = _size(value)
    ordered = sorted(eligible_claim_ids)
    for count in range(min(3 - optional_count, len(ordered)), 0, -1):
        if base_size + sum(sorted(claim_sizes.values())[:count]) + count - 1 > problem.max_bytes:
            continue
        for selected in combinations(ordered, count):
            if evaluations >= max_evaluations:
                return PackingResult(False, None, (), evaluations, "PACKING_WORK_EXHAUSTED")
            evaluations += 1
            if base_size + sum(claim_sizes[ref] for ref in selected) + count - 1 > problem.max_bytes:
                continue
            selected_set = set(selected)
            edges = [edge.model_dump(mode="json") | {"endpoints_in_context": [ref for ref in (edge.left, edge.right) if ref in selected_set]} for edge in sorted(problem.relations, key=lambda edge: edge.ref) if edge.left in selected_set or edge.right in selected_set]
            candidate = {**value, "memory_candidates": [rendered[ref] for ref in selected], "relations": edges}
            if _size(candidate) <= problem.max_bytes:
                return PackingResult(True, count, selected, evaluations, None)
    return PackingResult(True, 0, (), evaluations, None)


def _unique(values: Any, code: str) -> None:
    seen = set()
    for value in values:
        _require(value not in seen, code)
        seen.add(value)


def _document(raw: bytes, model: type[_Input]) -> Any:
    _require(type(raw) is bytes and len(raw) <= MAX_INPUT_BYTES, "DIAGNOSTIC_INPUT_BOUND")
    return model.model_validate(decode_json(raw))


def _file(manifest: EvaluationManifest, name: str) -> Any:
    frozen = manifest.file(name)
    _require(len(frozen.raw) <= MAX_INPUT_BYTES and digest_bytes(frozen.raw) == frozen.sha256, "DIAGNOSTIC_FROZEN_INPUT_DRIFT")
    return frozen


def _reference(manifest: EvaluationManifest, reference: InputReference, model: type[_Input]) -> Any:
    _require(reference.name not in {"retrieval_diagnostics", "corpus", "gold", "workload", "rules"}, "DIAGNOSTIC_REFERENCE_ROLE")
    frozen = _file(manifest, reference.name)
    _require(frozen.sha256 == reference.sha256, "DIAGNOSTIC_REFERENCE_DRIFT")
    return _document(frozen.raw, model)


def _protocol(manifest: EvaluationManifest, protocol: ScoringProtocol | dict) -> ScoringProtocol:
    protocol = ScoringProtocol.model_validate(protocol.model_dump(mode="json") if isinstance(protocol, ScoringProtocol) else protocol)
    _require(digest_bytes(manifest.raw) == manifest.digest == protocol.manifest_digest, "DIAGNOSTIC_MANIFEST_SCOPE")
    for name, field in (("corpus", "corpus_digest"), ("gold", "gold_digest"), ("rules", "required_rules_digest"), ("workload", "workload_digest")):
        _require(_file(manifest, name).sha256 == getattr(protocol, field), "DIAGNOSTIC_PROTOCOL_SCOPE")
    return protocol


def _frozen(manifest: EvaluationManifest) -> FrozenDiagnostics | None:
    files = [item for item in manifest.files if item.name == "retrieval_diagnostics"]
    _require(len(files) <= 1, "DIAGNOSTIC_DUPLICATE_INPUT")
    if not files:
        return None
    document = _document(_file(manifest, "retrieval_diagnostics").raw, FrozenDiagnostics)
    _unique((case.case_id for case in document.cases), "DIAGNOSTIC_DUPLICATE_CASE")
    return document


def _case_inputs(manifest: EvaluationManifest, protocol: ScoringProtocol, case_id: str) -> tuple[Any, dict, dict]:
    cases = [case for case in protocol.retrieval_cases if case.case_id == case_id]
    requests = [case for case in manifest.workload["retrieval"] if case["case_id"] == case_id]
    gold = [case for case in manifest.document("gold")["cases"] if case["case_id"] == case_id]
    _require(len(cases) == len(requests) == len(gold) == 1, "DIAGNOSTIC_CASE_SCOPE")
    expected = cases[0].model_dump(mode="json")
    _require(all(gold[0].get(key) == value for key, value in expected.items()), "DIAGNOSTIC_GOLD_SCOPE")
    command = validate_wire(ContextCommand, requests[0]["request"])
    _require(command.limit == 3 and command.binding_id == manifest.config["gateway"]["binding_id"], "DIAGNOSTIC_REQUEST_SCOPE")
    request = command.model_dump(mode="json", exclude={"admission_id", "relevance"})
    return cases[0], request, gold[0]


def _source_mapping(manifest: EvaluationManifest, gold: dict) -> str:
    corpus = manifest.document("corpus")
    ids = set(gold["relevant_claim_ids"]) | set(gold["irrelevant_claim_ids"])
    claims = [claim for claim in corpus["claims"] if claim["ref"] in ids]
    _require(len(claims) == len(ids), "DIAGNOSTIC_SOURCE_MAPPING")
    sources = {span["source_id"] for claim in claims for span in claim["projection"]["evidence"]} | {span["source_id"] for span in gold["grounding_refs"]}
    return canonical_digest({"case": gold, "claims": claims, "sources": [source for source in corpus["sources"] if source["source_id"] in sources]})


def render_frozen_claim(claim: dict) -> dict:
    try:
        projection = claim["projection"]
        evidence = tuple(EvidenceSpan.model_validate(span) for span in projection["evidence"])
        _require(isinstance(projection["draft"], dict) and "evidence" not in projection["draft"],
                 "PACKING_FROZEN_CLAIM_INCOMPLETE")
        draft = ClaimDraft.model_validate({
            **projection["draft"],
            "evidence": [{
                "source_id": span.source_id, "quote": span.quote, "byte_start": span.byte_start,
            } for span in evidence],
        })
        _require(projection["id"] == claim["ref"] and projection["kind"] == "claim"
                 and projection["state"] == "active" and projection["statement"] == draft.statement
                 and projection["interpretation_role"] in {"caller_grounded_candidate", "model_derived_candidate"}
                 and bool(evidence), "PACKING_FROZEN_CLAIM_INCOMPLETE")
        return render_claim(
            claim["ref"], draft, evidence, snapshot=projection["snapshot"],
            interpretation_role=projection["interpretation_role"],
        )
    except (KeyError, TypeError, ValueError) as error:
        raise DiagnosticInputError("PACKING_FROZEN_CLAIM_INCOMPLETE") from error


def diagnostic_scope(manifest: EvaluationManifest, protocol: ScoringProtocol | dict, case_id: str) -> RetrievalDiagnosticScope:
    protocol = _protocol(manifest, protocol)
    case, request, gold = _case_inputs(manifest, protocol, case_id)
    frozen = _frozen(manifest)
    if frozen is not None:
        _require({row.case_id for row in frozen.cases} <= {row.case_id for row in protocol.retrieval_cases}, "DIAGNOSTIC_UNKNOWN_CASE")
    supplied = next((row for row in frozen.cases if row.case_id == case_id), None) if frozen else None
    common = {"manifest_digest": manifest.digest, "corpus_digest": protocol.corpus_digest, "gold_digest": protocol.gold_digest, "required_rules_digest": protocol.required_rules_digest, "request_digest": canonical_digest(request)}
    if supplied is None:
        return RetrievalDiagnosticScope(**common, budget_digest=canonical_digest({"complete": False, "request": request, "required_rules_digest": protocol.required_rules_digest, "basis": "no_independent_packing_input"}), source_scope_digest=canonical_digest({"complete": False, "source_mapping_digest": _source_mapping(manifest, gold)}))
    _require(supplied.cluster_id == case.cluster_id, "DIAGNOSTIC_CLUSTER_SCOPE")
    source = _reference(manifest, supplied.source_scope, SourceScopeInput)
    _require(source.case_id == case_id and source.corpus_digest == protocol.corpus_digest and source.gold_digest == protocol.gold_digest and source.request_digest == common["request_digest"] and source.source_mapping_digest == _source_mapping(manifest, gold), "DIAGNOSTIC_SOURCE_SCOPE")
    scope = RetrievalDiagnosticScope(**common, budget_digest=supplied.budget.sha256, source_scope_digest=supplied.source_scope.sha256)
    _require(supplied.scope.model_dump(mode="json") == scope.model_dump(mode="json", exclude={"manifest_digest"}), "DIAGNOSTIC_RAW_SCOPE")
    budget = _reference(manifest, supplied.budget, IndependentPackingInput)
    _require(budget.case_id == case_id and budget.corpus_digest == scope.corpus_digest and budget.required_rules_digest == scope.required_rules_digest and budget.request_digest == scope.request_digest and budget.source_scope_digest == scope.source_scope_digest and budget.max_bytes == request["max_bytes"] and budget.limit == request["limit"], "DIAGNOSTIC_BUDGET_SCOPE")
    frozen_rules = manifest.document("rules")
    _require(frozen_rules.get("schema") == 2
             and isinstance(frozen_rules.get("applicable"), list),
             "PACKING_FROZEN_RULE_SET_INCOMPLETE")
    rules = sorted(
        (rule.model_dump(mode="json") for rule in budget.rules),
        key=lambda rule: (not rule["required"], rule["ref"], rule["revision"]),
    )
    expected_rules = {rule["ref"]: rule for rule in frozen_rules["applicable"]}
    _unique((rule["ref"] for rule in rules), "PACKING_DUPLICATE_RULE")
    _require(all(rule == expected_rules.get(rule["ref"]) for rule in rules)
             and (not budget.complete or rules == frozen_rules["applicable"]),
             "PACKING_APPROVED_RULE_CONTENT_MISMATCH")
    corpus = manifest.document("corpus")
    _require(corpus.get("schema") == 2 and isinstance(corpus.get("relations"), list),
             "PACKING_FROZEN_RELATION_SET_INCOMPLETE")
    frozen_sources = {item["source_id"]: item for item in corpus["sources"]}
    frozen_claims = {item["ref"]: item for item in corpus["claims"]}
    expected_relations = [{
        "ref": edge["ref"], "left": edge["projection"]["left_id"],
        "right": edge["projection"]["right_id"], "kind": edge["projection"]["relation_kind"],
    } for edge in corpus["relations"]]
    relations = [edge.model_dump(mode="json") for edge in sorted(budget.relations, key=lambda edge: edge.ref)]
    expected_edges = {edge["ref"]: edge for edge in expected_relations}
    _unique((edge["ref"] for edge in relations), "PACKING_DUPLICATE_RELATION")
    _require(all(edge == expected_edges.get(edge["ref"]) for edge in relations)
             and (not budget.complete or relations == expected_relations),
             "PACKING_FROZEN_RELATION_CONTENT_MISMATCH")
    _unique((item.ref for item in budget.claims), "PACKING_DUPLICATE_CLAIM")
    for claim in budget.claims:
        _require(claim.ref in frozen_claims, "PACKING_CLAIM_SOURCE_SCOPE")
        _require(claim.rendered() == render_frozen_claim(frozen_claims[claim.ref]),
                 "PACKING_FROZEN_CLAIM_CONTENT_MISMATCH")
        for span in claim.evidence:
            source = frozen_sources.get(span.source)
            _require(source is not None and span.revision == source["revision"], "PACKING_EVIDENCE_SOURCE_SCOPE")
            body = base64.b64decode(source["body"], validate=True)
            _require(span.bytes[1] <= len(body) and body[span.bytes[0]:span.bytes[1]] == span.quote.encode("utf-8"),
                     "PACKING_EVIDENCE_SOURCE_SCOPE")
    if supplied.rubric is not None:
        _reference(manifest, supplied.rubric, QualityRubric)
    return scope


class AdjudicatedCase(_Input):
    case_id: Identity
    scope: RetrievalDiagnosticScope
    quality_definition_digest: Digest
    judgments: tuple[DeliveredClaimJudgment, ...] = Field(max_length=4096)


class PostRunAdjudication(_Input):
    schema: Literal[1]
    manifest_digest: Digest
    independence: Literal["provided_unattested"]
    cases: tuple[AdjudicatedCase, ...] = Field(max_length=10000)


@dataclass(frozen=True)
class DiagnosticGoldInputs:
    gold: tuple[RetrievalDiagnosticGold, ...]
    frozen_input_digest: str | None
    adjudication_digest: str | None
    independence: Literal["provided_unattested"] = "provided_unattested"
    original_acceptance: Literal[False] = False
    original18_completed: Literal[0] = 0

    def provenance(self) -> dict:
        return {"frozen_input_digest": self.frozen_input_digest, "adjudication_digest": self.adjudication_digest, "independence": self.independence, "original_acceptance": self.original_acceptance, "original18_completed": self.original18_completed}


def load_diagnostic_gold(
    manifest: EvaluationManifest,
    protocol: ScoringProtocol | dict,
    *,
    adjudication: bytes | None = None,
) -> DiagnosticGoldInputs:
    protocol = _protocol(manifest, protocol)
    frozen = _frozen(manifest)
    extra = _document(adjudication, PostRunAdjudication) if adjudication is not None else None
    if extra is not None:
        _require(extra.manifest_digest == manifest.digest, "DIAGNOSTIC_ADJUDICATION_MANIFEST")
        _unique((case.case_id for case in extra.cases), "DIAGNOSTIC_DUPLICATE_ADJUDICATION_CASE")
    raw_cases = {case.case_id: case for case in frozen.cases} if frozen else {}
    extra_cases = {case.case_id: case for case in extra.cases} if extra else {}
    _require(raw_cases.keys() | extra_cases.keys() <= {case.case_id for case in protocol.retrieval_cases}, "DIAGNOSTIC_UNKNOWN_CASE")
    result = []
    for case in protocol.retrieval_cases:
        if case.case_id not in raw_cases and case.case_id not in extra_cases:
            continue
        scope = diagnostic_scope(manifest, protocol, case.case_id)
        supplied = raw_cases.get(case.case_id)
        quality_digest = supplied.rubric.sha256 if supplied and supplied.rubric else None
        eligibility = feasibility = None
        judgments = []
        if supplied:
            for witness in (supplied.eligibility, supplied.feasibility, *supplied.judgments):
                if witness is not None:
                    _require(witness.scope == supplied.scope, "DIAGNOSTIC_WITNESS_SCOPE")
            if supplied.eligibility:
                raw = supplied.eligibility
                eligibility = GoldEligibilityWitness(**raw.model_dump(mode="json", exclude={"scope"}), scope=scope)
                if raw.complete:
                    _require(set(raw.eligible_claim_ids) | set(raw.ineligible_claim_ids) == set(case.relevant_claim_ids), "DIAGNOSTIC_ELIGIBILITY_PARTITION")
            if supplied.feasibility:
                raw = supplied.feasibility
                _require(supplied.eligibility is not None and raw.eligibility_input_digest == canonical_digest(supplied.eligibility), "DIAGNOSTIC_RAW_ELIGIBILITY_BINDING")
                feasibility = BudgetFeasibilityWitness(**raw.model_dump(mode="json", exclude={"scope", "eligibility_input_digest"}), scope=scope, eligibility_digest=canonical_digest(eligibility))
                _require(set(raw.maximizing_claim_ids) <= set(eligibility.eligible_claim_ids), "DIAGNOSTIC_FEASIBILITY_ELIGIBILITY")
            elif eligibility is not None and eligibility.complete and case.judgment_complete:
                problem = _reference(manifest, supplied.budget, IndependentPackingInput)
                packed = independent_context_item_feasibility(problem, eligibility.eligible_claim_ids)
                feasibility = BudgetFeasibilityWitness(scope=scope, independent_reference=problem.independent_reference, evidence_digest=supplied.budget.sha256, eligibility_digest=canonical_digest(eligibility), basis="complete_independent_context_item_packing", complete=packed.complete, maximum_relevant=packed.maximum_relevant, maximizing_claim_ids=packed.maximizing_claim_ids)
            for judgment in supplied.judgments:
                _require(quality_digest is not None and judgment.definition_digest == quality_digest, "DIAGNOSTIC_RUBRIC_SCOPE")
                if judgment.phase == "frozen_claim":
                    claim = next((row for row in manifest.document("corpus")["claims"]
                                  if row["ref"] == judgment.claim_id), None)
                    _require(claim is not None and judgment.expected_claim_digest
                             == canonical_digest(render_frozen_claim(claim)),
                             "DIAGNOSTIC_FROZEN_CLAIM_JUDGMENT_CONTENT_MISMATCH")
                judgments.append(DeliveredClaimJudgment(**judgment.model_dump(mode="json", exclude={"scope"}), scope=scope))
        post = extra_cases.get(case.case_id)
        if post is not None:
            _require(post.scope == scope and quality_digest is not None and post.quality_definition_digest == quality_digest, "DIAGNOSTIC_ADJUDICATION_SCOPE")
            for judgment in post.judgments:
                _require(judgment.scope == scope and judgment.phase == "post_run_adjudication" and judgment.definition_digest == quality_digest and judgment.expected_final_context_digest is not None, "DIAGNOSTIC_ADJUDICATION_JUDGMENT")
                judgments.append(judgment)
        known_ids = set(case.relevant_claim_ids) | set(case.irrelevant_claim_ids)
        _require(all(judgment.claim_id in known_ids for judgment in judgments), "DIAGNOSTIC_JUDGMENT_CLAIM_SCOPE")
        result.append(RetrievalDiagnosticGold(schema=1, case_id=case.case_id, cluster_id=case.cluster_id, scope=scope, quality_definition_digest=quality_digest, eligibility=eligibility, feasibility=feasibility, judgments=tuple(judgments)))
    return DiagnosticGoldInputs(tuple(result), _file(manifest, "retrieval_diagnostics").sha256 if frozen else None, digest_bytes(adjudication) if adjudication is not None else None)
