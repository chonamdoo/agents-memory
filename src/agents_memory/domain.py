from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Literal, Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

Handle = Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]
Key = Annotated[str, StringConstraints(min_length=1, max_length=512)]
SmallText = Annotated[str, StringConstraints(min_length=1, max_length=2048)]
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

    @field_validator("event_time")
    @classmethod
    def aware_event_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("event_time requires an explicit timezone")
        return value


class RecordCommand(TypedModel):
    binding_id: Handle | None = None
    idempotency_key: Key
    body: str = Field(min_length=1, max_length=16384, repr=False)
    kind: Literal["note", "rule_candidate"] = "note"


class FeedbackCommand(TypedModel):
    binding_id: Handle | None = None
    idempotency_key: Key
    target_ref: Handle
    kind: Literal["correct", "reject", "retract_request"]
    body: str | None = Field(default=None, min_length=1, max_length=16384, repr=False)

    @model_validator(mode="after")
    def correction_has_body(self) -> FeedbackCommand:
        if self.kind == "correct" and self.body is None:
            raise ValueError("correct requires body")
        return self


class ContextCommand(TypedModel):
    binding_id: Handle | None = None
    query: str = Field(min_length=1, max_length=4096)
    mode: Literal["recall", "reflect"] = "recall"
    idempotency_key: Key | None = None
    paths: tuple[PathText, ...] | None = Field(default=None, max_length=64)
    purpose: PurposeText | None = None
    host: Literal["claude", "codex", "omp", "generic", "agent-flow"] | None = None
    snapshot: SnapshotText | None = None
    causal_operation: Handle | None = None
    max_bytes: int = Field(default=2400, ge=256, le=6144)
    limit: int = Field(default=3, ge=1, le=5)

    @model_validator(mode="after")
    def reflection_has_key(self) -> ContextCommand:
        if self.mode == "reflect" and self.idempotency_key is None:
            raise ValueError("reflect requires idempotency_key")
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
    binding_id: Handle
    draft: ClaimDraft
    evidence: tuple[EvidenceSpan, ...]
    input_source_ids: tuple[Handle, ...]
    snapshot: str | None
    created_at: datetime
    state: Literal["active", "retracted"] = "active"


class Extraction(TypedModel):
    claims: tuple[ClaimDraft, ...] = Field(max_length=32)


class RelationDraft(TypedModel):
    left_id: Handle
    right_id: Handle
    kind: Literal[
        "duplicates", "supports", "contradicts", "supersedes", "conditional_variant", "possible_same"
    ]
    reason: SmallText


class Relation(RelationDraft):
    id: Handle


class Consolidation(TypedModel):
    relations: tuple[RelationDraft, ...] = Field(max_length=128)


class CitedSentence(TypedModel):
    text: SmallText
    claim_ids: tuple[Handle, ...] = Field(min_length=1, max_length=8)


class ReflectionDraft(TypedModel):
    sentences: tuple[CitedSentence, ...] = Field(min_length=1, max_length=8)
    limitations: tuple[SmallText, ...] = Field(default=(), max_length=4)


class RankedClaim(TypedModel):
    claim_id: Handle
    score: float = Field(allow_inf_nan=False)
    arms: tuple[str, ...] = ()


class Operation(TypedModel):
    id: Handle
    binding_id: Handle
    kind: str
    state: Literal["accepted", "semantic_ready", "pending", "blocked", "failed", "retracted"]
    source_id: Handle | None = None
    artifact_id: Handle | None = None
    successor_operation_id: Handle | None = None
    error_code: str | None = None
    epoch: int = Field(ge=0)
    effect: EffectState = EffectState.COMMITTED


class JobLease(TypedModel):
    job_id: Handle
    lease_token: Handle
    generation: int = Field(ge=1)
    deadline: datetime
    kind: Literal["extract", "consolidate", "reflect", "reindex"]
    binding_id: Handle
    operation_id: Handle
    credential_id: Handle
    source_ids: tuple[Handle, ...] = ()
    claim_ids: tuple[Handle, ...] = ()
    query_source_id: Handle | None = None
    attempts: int = Field(ge=1)


class RevisionRef(TypedModel):
    id: Handle
    revision: int = Field(ge=1)


class Admission(TypedModel):
    id: Handle
    binding_id: Handle
    credential_id: Handle
    credential_generation: int
    epoch: int
    route_revision: str
    purpose: str
    sources: tuple[RevisionRef, ...]
    claim_ids: tuple[Handle, ...]
    deadline: datetime
    job_id: Handle | None = None
    lease_token: Handle | None = None
    generation: int | None = None


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


class SemanticRuntime(Protocol):
    revision: str

    async def extract(self, source: Source) -> Extraction: ...

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...

    async def consolidate(self, claims: Sequence[Claim]) -> Consolidation: ...

    async def rerank(self, query: str, claims: Sequence[Claim]) -> list[RankedClaim]: ...

    async def reflect(self, query: str, claims: Sequence[Claim]) -> ReflectionDraft: ...

    async def close(self) -> None: ...


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
