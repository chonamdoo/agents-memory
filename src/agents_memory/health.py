from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, TypeAdapter, field_validator, model_validator

from .domain import Handle, Key, ReasonText, RevisionRef, TypedModel, reject_source_secrets

Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
HealthVersion = Annotated[int, Field(strict=True, ge=0, le=9_223_372_036_854_775_807)]
PositiveVersion = Annotated[int, Field(strict=True, ge=1, le=9_223_372_036_854_775_807)]
RelativePath = Annotated[str, StringConstraints(min_length=1, max_length=4096)]
SymbolName = Annotated[str, StringConstraints(min_length=1, max_length=512)]
Support = Literal["supported", "contradicted", "unknown"]
Freshness = Literal["observed_current", "stale", "unknown"]
Relevance = Literal["related", "unrelated", "unknown"]


def relative_code_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or "\\" in value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or path.as_posix() != value
    ):
        raise ValueError("code path must be a normalized relative path")
    return value


def _distinct(values: list[str], label: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"duplicate {label}")


class HealthMutation(TypedModel):
    binding_id: Handle
    expected_binding_revision: PositiveVersion
    idempotency_key: Key

    @field_validator("idempotency_key")
    @classmethod
    def secret_free_key(cls, value: str) -> str:
        reject_source_secrets(value)
        return value


class HealthPolicyCommand(HealthMutation):
    kind: Literal["health_policy"] = "health_policy"
    expected_policy_revision: HealthVersion
    enabled: bool = Field(strict=True)
    allow_jev_health: bool = Field(default=False, strict=True)
    max_audit_sources: int = Field(default=16, strict=True, ge=1, le=128)
    max_audit_claims: int = Field(default=20, strict=True, ge=1, le=20)
    max_audit_bytes: int = Field(default=32768, strict=True, ge=1024, le=131072)

    @model_validator(mode="after")
    def enabled_permission(self) -> HealthPolicyCommand:
        if self.allow_jev_health and not self.enabled:
            raise ValueError("health model processing requires enabled health policy")
        return self


class HealthWorkspaceCommand(HealthMutation):
    kind: Literal["health_workspace"] = "health_workspace"
    workspace_id: Handle
    expected_workspace_revision: HealthVersion
    root_fingerprint: Digest
    producer_credential_id: Handle


class CodeSymbolObservation(TypedModel):
    qualified_name: SymbolName
    kind: Literal["function", "class", "method", "span"]
    byte_start: int = Field(strict=True, ge=0)
    byte_end: int = Field(strict=True, ge=1)
    span_digest: Digest
    resolver: Literal["python_ast", "exact_span"]

    @model_validator(mode="after")
    def nonempty_span(self) -> CodeSymbolObservation:
        if self.byte_end <= self.byte_start:
            raise ValueError("symbol span must be nonempty")
        if any(ord(char) < 32 or ord(char) == 127 for char in self.qualified_name):
            raise ValueError("symbol name must not contain control characters")
        return self


class CodeFileObservation(TypedModel):
    relative_path: RelativePath
    status: Literal["present", "missing", "unreadable", "oversized", "unstable"]
    file_digest: Digest | None = None
    byte_length: int | None = Field(default=None, strict=True, ge=0, le=1048576)
    symbol_coverage: Literal["complete", "partial", "unsupported"] = "unsupported"
    symbols: list[CodeSymbolObservation] = Field(default_factory=list, max_length=256)

    @field_validator("relative_path")
    @classmethod
    def bounded_relative_path(cls, value: str) -> str:
        return relative_code_path(value)

    @model_validator(mode="after")
    def coherent_observation(self) -> CodeFileObservation:
        if self.status == "present":
            if self.file_digest is None or self.byte_length is None:
                raise ValueError("present file requires its digest and byte length")
            if any(symbol.byte_end > self.byte_length for symbol in self.symbols):
                raise ValueError("symbol span exceeds observed file")
        elif self.file_digest is not None or self.byte_length is not None or self.symbols:
            raise ValueError("unresolved file must not claim a content witness")
        if self.symbol_coverage == "unsupported" and self.symbols:
            raise ValueError("unsupported symbol resolver must not claim symbol observations")
        identities = [
            f"{symbol.kind}:{symbol.qualified_name}:{symbol.byte_start}:{symbol.byte_end}"
            for symbol in self.symbols
        ]
        _distinct(identities, "symbol observation")
        return self


class CodeObservationCommand(HealthMutation):
    kind: Literal["code_observation"] = "code_observation"
    workspace_id: Handle
    expected_workspace_revision: PositiveVersion
    root_fingerprint: Digest
    sequence: PositiveVersion
    observed_at: datetime
    files: list[CodeFileObservation] = Field(min_length=1, max_length=32)
    coverage: Literal["linked_paths", "partial_linked_paths", "explicit_paths"]

    @field_validator("observed_at")
    @classmethod
    def aware_observation_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observation time requires an explicit timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def distinct_files(self) -> CodeObservationCommand:
        _distinct([file.relative_path for file in self.files], "file observation")
        return self


class CodeLinkCommand(HealthMutation):
    kind: Literal["code_link"] = "code_link"
    admission_id: Handle
    claim_ref: RevisionRef
    expected_health_version: HealthVersion
    observation_refs: list[Handle] = Field(min_length=1, max_length=32)
    reason: ReasonText = Field(repr=False)

    @field_validator("reason")
    @classmethod
    def secret_free_reason(cls, value: str) -> str:
        reject_source_secrets(value)
        return value

    @model_validator(mode="after")
    def distinct_dependencies(self) -> CodeLinkCommand:
        _distinct(self.observation_refs, "code dependency")
        return self


class SessionObservationCommand(HealthMutation):
    kind: Literal["session_observation"] = "session_observation"
    stream_id: Handle
    segment_id: Handle
    event_id: Handle
    sequence: PositiveVersion
    event: Literal["start", "end", "interrupted", "resume", "checkpoint"]
    root_run_id: Handle | None = None
    agent_path: str = Field(min_length=1, max_length=256)
    source_refs: list[RevisionRef] = Field(default_factory=list, max_length=128)
    origin_keys: list[Key] = Field(default_factory=list, max_length=128, repr=False)
    claim_refs: list[RevisionRef] = Field(default_factory=list, max_length=32)
    coverage: Literal["observed_segment", "partial", "unknown"] = "unknown"
    gaps: list[str] = Field(default_factory=list, max_length=16)

    @field_validator("origin_keys")
    @classmethod
    def secret_free_origins(cls, values: list[str]) -> list[str]:
        for value in values:
            reject_source_secrets(value)
        return values

    @field_validator("agent_path")
    @classmethod
    def bounded_agent_identity(cls, value: str) -> str:
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("agent identity must not contain control characters")
        reject_source_secrets(value)
        return value

    @field_validator("gaps")
    @classmethod
    def bounded_gaps(cls, values: list[str]) -> list[str]:
        if any(re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", value) is None for value in values):
            raise ValueError("coverage gaps require bounded ASCII diagnostic codes")
        _distinct(values, "coverage gap")
        return values

    @model_validator(mode="after")
    def distinct_session_manifest(self) -> SessionObservationCommand:
        _distinct([value.id for value in self.source_refs], "session source")
        _distinct([value.id for value in self.claim_refs], "session claim")
        _distinct(self.origin_keys, "capture origin")
        if self.coverage == "observed_segment" and self.gaps:
            raise ValueError("a gapped segment must be reported as partial or unknown")
        return self


class HealthEvidenceSpan(TypedModel):
    source_ref: RevisionRef
    byte_start: int = Field(strict=True, ge=0)
    byte_end: int = Field(strict=True, ge=1)
    quote: str = Field(min_length=1, max_length=16384, repr=False)

    @field_validator("quote")
    @classmethod
    def secret_free_quote(cls, value: str) -> str:
        reject_source_secrets(value)
        return value

    @model_validator(mode="after")
    def exact_quote_length(self) -> HealthEvidenceSpan:
        if self.byte_end - self.byte_start != len(self.quote.encode("utf-8")):
            raise ValueError("evidence span length must match exact UTF-8 quote bytes")
        return self


class HealthClaimAssessment(TypedModel):
    claim_ref: RevisionRef
    support: Support
    freshness: Freshness
    relevance: Relevance
    reason: ReasonText = Field(repr=False)
    evidence: list[HealthEvidenceSpan] = Field(default_factory=list, max_length=32)

    @field_validator("reason")
    @classmethod
    def secret_free_reason(cls, value: str) -> str:
        reject_source_secrets(value)
        return value

    @model_validator(mode="after")
    def grounded_support(self) -> HealthClaimAssessment:
        if self.support != "unknown" and not self.evidence:
            raise ValueError("a support or contradiction assessment requires exact source evidence")
        return self


class HealthAssessmentCommand(HealthMutation):
    kind: Literal["health_assessment"] = "health_assessment"
    admission_id: Handle
    pending_id: Handle
    health_manifest_digest: Digest
    input_sources: list[RevisionRef] = Field(max_length=128)
    input_claims: list[RevisionRef] = Field(max_length=20)
    assessments: list[HealthClaimAssessment] = Field(max_length=20)
    evaluation_receipt_digest: Digest | None = None

    @model_validator(mode="after")
    def complete_target_manifest(self) -> HealthAssessmentCommand:
        _distinct([value.id for value in self.input_sources], "assessment source")
        _distinct([value.id for value in self.input_claims], "assessment input claim")
        _distinct([value.claim_ref.id for value in self.assessments], "assessment target")
        expected = {(value.id, value.revision) for value in self.input_claims}
        observed = {(value.claim_ref.id, value.claim_ref.revision) for value in self.assessments}
        if expected != observed:
            raise ValueError("every admitted target requires exactly one assessment")
        return self


class MemoryReviewCommand(HealthMutation):
    kind: Literal["memory_review"] = "memory_review"
    admission_id: Handle
    claim_ref: RevisionRef
    expected_health_version: HealthVersion
    expected_review_event_id: Handle | None = None
    decision: Literal["accept", "reject"]
    reason: ReasonText = Field(repr=False)
    revalidated_observation_refs: list[Handle] = Field(default_factory=list, max_length=32)

    @field_validator("reason")
    @classmethod
    def secret_free_reason(cls, value: str) -> str:
        reject_source_secrets(value)
        return value

    @model_validator(mode="after")
    def explicit_positive_revalidation(self) -> MemoryReviewCommand:
        _distinct(self.revalidated_observation_refs, "revalidation observation")
        if self.decision == "reject" and self.revalidated_observation_refs:
            raise ValueError("Reject cannot rebind or affirm code dependencies")
        return self


class FeedbackResolutionCommand(HealthMutation):
    kind: Literal["feedback_resolution"] = "feedback_resolution"
    admission_id: Handle
    feedback_ref: Handle
    expected_feedback_version: HealthVersion
    decision: Literal["accept", "decline"]
    reason: ReasonText = Field(repr=False)
    successor_operation_id: Handle | None = None

    @field_validator("reason")
    @classmethod
    def secret_free_reason(cls, value: str) -> str:
        reject_source_secrets(value)
        return value

    @model_validator(mode="after")
    def explicit_successor(self) -> FeedbackResolutionCommand:
        if self.decision == "accept" and self.successor_operation_id is None:
            raise ValueError("accepting correction feedback requires its authorized successor operation")
        if self.decision == "decline" and self.successor_operation_id is not None:
            raise ValueError("declining feedback cannot claim a successor operation")
        return self


class HealthObserverRequest(TypedModel):
    binding_id: Handle


HealthCommand = Annotated[
    HealthPolicyCommand
    | HealthWorkspaceCommand
    | CodeObservationCommand
    | CodeLinkCommand
    | SessionObservationCommand
    | HealthAssessmentCommand
    | MemoryReviewCommand
    | FeedbackResolutionCommand,
    Field(discriminator="kind"),
]
HEALTH_ADAPTER = TypeAdapter(HealthCommand)
