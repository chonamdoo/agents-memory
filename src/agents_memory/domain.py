from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from .capture_guard import contains_source_secret

Handle = Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]
Key = Annotated[str, StringConstraints(min_length=1, max_length=512)]
SmallText = Annotated[str, StringConstraints(min_length=1, max_length=2048)]
ReasonText = Annotated[str, StringConstraints(min_length=1, max_length=2048, pattern=r"\S")]
EntityText = Annotated[str, StringConstraints(min_length=1, max_length=256)]
PurposeText = Annotated[str, StringConstraints(min_length=1, max_length=128)]
SnapshotText = Annotated[str, StringConstraints(min_length=1, max_length=512)]
PathText = Annotated[str, StringConstraints(min_length=1, max_length=4096)]


class TypedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Role(StrEnum):
    AGENT = "agent"
    PRODUCER = "producer"
    OPERATOR = "operator"
    APPROVER = "approver"


class RuleScope(StrEnum):
    LOCAL_PROJECT = "local_project"
    MY_PROJECTS = "my_projects"
    SHARED = "shared"


class EffectState(StrEnum):
    NOT_STARTED = "not_started"
    NOT_COMMITTED = "not_committed"
    COMMITTED = "committed"
    UNKNOWN = "unknown"


class DomainError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int = 409,
        effect: EffectState = EffectState.NOT_STARTED,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.effect = effect

    def public(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message, "effect": self.effect.value}


def reject_source_secrets(text: str) -> None:
    if contains_source_secret(text):
        raise DomainError(
            "SOURCE_SECRET_REJECTED", "High-confidence secret source was refused before persistence", status=422,
        )


class Principal(TypedModel):
    id: Handle
    credential_id: Handle
    realm: Handle
    role: Role
    bindings: tuple[Handle, ...]
    generation: int = Field(ge=0)


class Binding(TypedModel):
    id: Handle
    realm: Handle
    owner_id: Handle
    label: str = Field(min_length=1, max_length=256)
    locator: str | None = Field(default=None, min_length=1, max_length=4096)
    revision: int = Field(ge=1)


class BindingRelocation(TypedModel):
    binding_id: Handle
    expected_revision: int = Field(ge=1)
    expected_locator: PathText
    locator: PathText
    idempotency_key: Key

    @field_validator("expected_locator", "locator")
    @classmethod
    def absolute_locator(cls, value: str) -> str:
        path = PurePosixPath(value)
        if not path.is_absolute() or ".." in path.parts or "\x00" in value or str(path) != value:
            raise ValueError("A normalized absolute locator is required")
        return value


class CaptureCoverage(TypedModel):
    status: Literal["observed_window", "truncated", "unknown"] = "unknown"
    gaps: tuple[Handle, ...] = Field(default=(), max_length=16)
    original_bytes: int | None = Field(default=None, ge=0)
    provenance: Literal["producer_reported"] = "producer_reported"


class CaptureCommand(TypedModel):
    binding_id: Handle
    idempotency_key: Key
    origin_key: Key
    body: str = Field(min_length=1, max_length=131072, repr=False)
    speaker: Literal["human", "assistant", "tool", "document", "agent_note", "memory"]
    root_run_id: Key | None = None
    agent_path: str | None = Field(default=None, min_length=1, max_length=1024)
    event_time: datetime | None = None
    snapshot: SnapshotText | None = None
    injected: bool = False
    kind: Literal["conversation", "document", "finding", "correction", "query"] = "conversation"
    coverage: CaptureCoverage = CaptureCoverage()

    @field_validator("body", "origin_key", "idempotency_key", "root_run_id", "agent_path", "snapshot")
    @classmethod
    def secret_free_source(cls, value: str | None) -> str | None:
        if value is not None:
            reject_source_secrets(value)
        return value

    @field_validator("coverage")
    @classmethod
    def secret_free_coverage(cls, value: CaptureCoverage) -> CaptureCoverage:
        for gap in value.gaps:
            reject_source_secrets(gap)
        return value

    @field_validator("event_time")
    @classmethod
    def aware_event_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("event_time requires an explicit timezone")
        return value

    def digest_payload(self, *exclude: str) -> dict:
        # Pre-coverage receipts, origins and correction intents were digested without this field.
        omitted = {*exclude, "coverage"} if self.coverage == CaptureCoverage() else set(exclude)
        return self.model_dump(mode="json", exclude=omitted)

    def contradicts_coverage(self) -> bool:
        size = len(self.body.encode())
        original = self.coverage.original_bytes
        return original is not None and (original < size or (self.coverage.status == "observed_window" and original != size))


class CorrectCommand(TypedModel):
    target_ref: Handle
    source: CaptureCommand


class RecordCommand(TypedModel):
    binding_id: Handle | None = None
    idempotency_key: Key
    body: str = Field(min_length=1, max_length=16384, repr=False)
    kind: Literal["note", "rule_candidate"] = "note"

    @field_validator("body", "idempotency_key")
    @classmethod
    def secret_free_record(cls, value: str) -> str:
        reject_source_secrets(value)
        return value


class FeedbackCommand(TypedModel):
    binding_id: Handle | None = None
    idempotency_key: Key
    target_ref: Handle
    kind: Literal["correct", "reject", "retract_request"]
    body: str | None = Field(default=None, min_length=1, max_length=16384, repr=False)

    @field_validator("body", "idempotency_key")
    @classmethod
    def secret_free_feedback(cls, value: str | None) -> str | None:
        if value is not None:
            reject_source_secrets(value)
        return value

    @model_validator(mode="after")
    def feedback_has_body(self) -> FeedbackCommand:
        if self.kind in {"correct", "reject"} and self.body is None:
            raise ValueError(f"{self.kind} requires body")
        if self.kind == "reject" and (self.body is None or self.body.isspace() or len(self.body) > 2048):
            raise ValueError("reject requires a nonblank reason of at most 2048 characters")
        return self


class RelevanceJudgment(TypedModel):
    claim_id: Handle
    relevant: bool = Field(strict=True)
    reason: ReasonText

    @field_validator("reason")
    @classmethod
    def secret_free_reason(cls, value: str) -> str:
        reject_source_secrets(value)
        return value


class ContextCommand(TypedModel):
    binding_id: Handle | None = None
    query: str = Field(min_length=1, max_length=4096)
    query_expansions: tuple[str, ...] = Field(default=(), max_length=8)
    admission_id: Handle | None = None
    relevance: tuple[RelevanceJudgment, ...] | None = Field(default=None, max_length=20)
    paths: tuple[PathText, ...] | None = Field(default=None, max_length=64)
    purpose: PurposeText | None = None
    host: Literal["claude", "codex", "omp", "generic", "agent-flow"] | None = None
    snapshot: SnapshotText | None = None
    causal_operation: Handle | None = None
    max_bytes: int = Field(default=2400, ge=256, le=6144)
    limit: int = Field(default=3, ge=1, le=5)

    @field_validator("query", "purpose", "snapshot")
    @classmethod
    def secret_free_query(cls, value: str | None) -> str | None:
        if value is not None:
            reject_source_secrets(value)
        return value

    @field_validator("paths")
    @classmethod
    def secret_free_paths(cls, values: tuple[str, ...] | None) -> tuple[str, ...] | None:
        for value in values or ():
            reject_source_secrets(value)
        return values

    @field_validator("query_expansions")
    @classmethod
    def bounded_expansions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            reject_source_secrets(value)
        if any(not value.strip() or len(value.encode()) > 512 for value in values) or sum(len(value.encode()) for value in values) > 4096:
            raise ValueError("Query expansions exceed their UTF-8 bound")
        return values

    @model_validator(mode="after")
    def complete_relevance(self) -> ContextCommand:
        if (self.admission_id is None) != (self.relevance is None):
            raise ValueError("admission_id and relevance must be supplied together")
        if self.relevance is not None and len({item.claim_id for item in self.relevance}) != len(self.relevance):
            raise ValueError("Relevance decisions must have unique claim IDs")
        return self


class Source(TypedModel):
    id: Handle
    binding_id: Handle
    realm: Handle
    revision: int = Field(ge=1)
    body: str = Field(repr=False)
    speaker: str
    origin_key: Key
    root_run_id: Key | None
    snapshot: str | None
    event_time: datetime | None
    recorded_at: datetime
    state: Literal["active", "retracted", "purged"] = "active"
    coverage: CaptureCoverage = CaptureCoverage()


class Quote(TypedModel):
    source_id: Handle
    quote: str = Field(min_length=1, max_length=4096)
    byte_start: int | None = Field(default=None, ge=0)


class ClaimDraft(TypedModel):
    statement: SmallText
    kind: Literal["fact", "preference", "procedure", "finding", "rule_candidate"]
    subject: str = Field(min_length=1, max_length=256)
    predicate: str = Field(min_length=1, max_length=256)
    object: str = Field(min_length=1, max_length=1024)
    polarity: Literal["positive", "negative"]
    modality: Literal["asserted", "uncertain", "planned", "hypothetical"]
    conditions: tuple[SmallText, ...] = Field(default=(), max_length=12)
    exceptions: tuple[SmallText, ...] = Field(default=(), max_length=12)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    entities: tuple[EntityText, ...] = Field(default=(), max_length=16)
    evidence: tuple[Quote, ...] = Field(min_length=1, max_length=8)

    @field_validator("valid_from", "valid_until")
    @classmethod
    def aware_valid_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("valid time requires an explicit timezone")
        return value

    @model_validator(mode="after")
    def valid_interval(self) -> ClaimDraft:
        if self.valid_from and self.valid_until and self.valid_from >= self.valid_until:
            raise ValueError("valid_until must follow valid_from")
        return self


class EvidenceSpan(TypedModel):
    source_id: Handle
    source_revision: int
    source_speaker: str
    source_event_time: datetime | None
    source_recorded_at: datetime
    byte_start: int = Field(ge=0)
    byte_end: int = Field(gt=0)
    quote: str


class Claim(TypedModel):
    id: Handle
    revision: int = Field(default=1, ge=1)
    binding_id: Handle
    draft: ClaimDraft
    evidence: tuple[EvidenceSpan, ...]
    input_source_ids: tuple[Handle, ...]
    snapshot: str | None
    created_at: datetime
    state: Literal["active", "retracted"] = "active"
    interpretation_role: Literal["model_derived_candidate", "caller_grounded_candidate"] = "model_derived_candidate"
    selection_id: Handle | None = None
    policy_revision: str | None = None
    awaiting_revalidation: bool = False


class Extraction(TypedModel):
    claims: tuple[ClaimDraft, ...] = Field(max_length=32)


class RelationDraft(TypedModel):
    left_id: Handle
    right_id: Handle
    kind: Literal[
        "duplicates", "supports", "contradicts", "supersedes", "conditional_variant", "possible_same"
    ]
    reason: SmallText


class Relation(TypedModel):
    id: Handle
    left_id: Handle
    right_id: Handle
    kind: Literal[
        "duplicate", "supports", "contradicts", "supersedes",
        "conditional_variant", "possible_same",
    ]
    reason: SmallText


class Consolidation(TypedModel):
    relations: tuple[RelationDraft, ...] = Field(max_length=128)


class CitedSentence(TypedModel):
    text: SmallText
    claim_ids: tuple[Handle, ...] = Field(min_length=1, max_length=8)


class ReflectionDraft(TypedModel):
    sentences: tuple[CitedSentence, ...] = Field(min_length=1, max_length=8)
    limitations: tuple[SmallText, ...] = Field(default=(), max_length=4)



class SourcePointer(TypedModel):
    source_id: Handle
    source_revision: int = Field(ge=1)
    binding_id: Handle
    binding_revision: int = Field(ge=1)
    snapshot: SnapshotText | None = None
    source_speaker: Literal["human", "assistant", "tool", "document", "agent_note", "memory"]
    source_event_time: datetime | None
    source_recorded_at: datetime
    byte_length: int = Field(ge=1)
    coverage: CaptureCoverage


class Operation(TypedModel):
    id: Handle
    binding_id: Handle
    kind: str
    state: Literal["accepted", "semantic_ready", "captured", "selection_recorded", "candidate_ready", "pending", "blocked", "failed", "retracted"]
    source_id: Handle | None = None
    artifact_id: Handle | None = None
    successor_operation_id: Handle | None = None
    error_code: str | None = None
    epoch: int = Field(ge=0)
    source_pointer: SourcePointer | None = None
    capture_disposition: Literal["captured", "ignored", "retracted", "unresolved"] | None = None
    selection_label: Literal["remember", "discard", "review"] | None = None
    effect: EffectState = EffectState.COMMITTED


class RevisionRef(TypedModel):
    id: Handle
    revision: int = Field(ge=1, strict=True)



class NonmodelAdmission(TypedModel):
    id: Handle
    binding_id: Handle
    binding_revision: int = Field(ge=1)
    credential_id: Handle
    credential_generation: int = Field(ge=1)
    realm: Handle
    epoch: int = Field(ge=0)
    deletion_generation: int = Field(ge=0)
    policy_revision: str
    policy_epoch: int = Field(ge=0)
    sources: tuple[RevisionRef, ...] = Field(max_length=128)
    claim_ids: tuple[Handle, ...] = Field(max_length=64)
    relation_ids: tuple[Handle, ...] = Field(max_length=128)
    snapshot: SnapshotText | None
    deadline: datetime
    request_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    rejection_ids: tuple[Handle, ...] = Field(default=(), max_length=8)
    pending_id: Handle | None = None


def valid_path_pattern(pattern: str) -> bool:
    return (
        isinstance(pattern, str)
        and bool(pattern)
        and len(pattern.encode("utf-8")) <= 512
        and pattern != "."
        and not pattern.startswith("/")
        and ".." not in PurePosixPath(pattern).parts
        and not any(character in pattern for character in "[]{}\\\x00\r\n")
    )


class Selector(TypedModel):
    paths: tuple[PathText, ...] = Field(default=(), max_length=32)
    purposes: tuple[PurposeText, ...] = Field(default=(), max_length=16)
    hosts: tuple[Literal["claude", "codex", "omp", "generic", "agent-flow"], ...] = ()
    snapshots: tuple[SnapshotText, ...] = Field(default=(), max_length=16)

    @field_validator("paths")
    @classmethod
    def valid_patterns(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not valid_path_pattern(pattern) for pattern in value):
            raise ValueError("Selector paths require bounded supported relative glob patterns")
        return value


class RuleProposal(TypedModel):
    binding_id: Handle
    idempotency_key: Key
    body: str = Field(min_length=1, max_length=16384, repr=False)
    selector: Selector = Selector()
    exceptions: tuple[SmallText, ...] = ()
    required: bool = False
    source_ids: tuple[Handle, ...] = ()

    @field_validator("body", "idempotency_key")
    @classmethod
    def secret_free_proposal(cls, value: str) -> str:
        reject_source_secrets(value)
        return value

    @field_validator("exceptions")
    @classmethod
    def secret_free_exceptions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            reject_source_secrets(value)
        return values


class RuleApproval(TypedModel):
    proposal_id: Handle
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    scope: RuleScope
    target_bindings: tuple[Handle, ...] = Field(min_length=1, max_length=128)
    target_set_revision: int = Field(ge=1)
    idempotency_key: Key
    approver_signature: str | None = Field(default=None, min_length=1, max_length=256, repr=False)


class ActiveRule(TypedModel):
    id: Handle
    revision: int
    digest: str
    body: str = Field(repr=False)
    selector: Selector
    exceptions: tuple[str, ...]
    required: bool
    scope: RuleScope
    target_bindings: tuple[Handle, ...]
    source_ids: tuple[Handle, ...]



def utc_now() -> datetime:
    return datetime.now(UTC)


def canonical_digest(value: BaseModel | dict | list) -> str:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def approval_signing_payload(
    deployment_id: str, realm: str, actor_id: str, command: RuleApproval
) -> bytes:
    payload = {
        "deployment_id": deployment_id,
        "realm": realm,
        "actor_id": actor_id,
        "approval": command.model_dump(mode="json", exclude={"approver_signature"}),
    }
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
