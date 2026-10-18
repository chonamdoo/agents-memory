from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from itertools import accumulate
from typing import Annotated, Literal

from pydantic import Discriminator, Field, Tag, TypeAdapter, model_validator

from .constants import BOUNDED_CONTEXT_MARKER
from .domain import (
    DomainError,
    Extraction,
    Handle,
    Key,
    Quote,
    ReasonText,
    RecordCommand,
    RevisionRef,
    SnapshotText,
    Source,
    TypedModel,
    canonical_digest,
    reject_source_secrets,
)
from .health import CodeLinkCommand, HealthAssessmentCommand
from .representation import serialized_json_bytes
from .semantic import original_spans, resolve_extraction, validate_extraction
from .semantic_contract import GeneratedExtraction

Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
WINDOW_BYTES = 4096


def _reject_judgment_secrets(value: object) -> None:
    if isinstance(value, str):
        reject_source_secrets(value)
    elif isinstance(value, TypedModel):
        for field in type(value).model_fields:
            _reject_judgment_secrets(getattr(value, field))
    elif isinstance(value, dict):
        for item in value.values():
            _reject_judgment_secrets(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_judgment_secrets(item)


class RejectionComparison(TypedModel):
    rejection_id: Handle
    decision: Literal["unrelated", "reopen"]
    reason: ReasonText


class SourceSelectionCommand(TypedModel):
    kind: Literal["source_selection"]
    binding_id: Handle | None = None
    idempotency_key: Key
    admission_id: Handle
    source_id: Handle
    source_revision: int = Field(ge=1, strict=True)
    binding_revision: int = Field(ge=1, strict=True)
    snapshot: SnapshotText | None = None
    byte_start: int = Field(ge=0, strict=True)
    byte_end: int = Field(gt=0, strict=True)
    window_digest: Digest
    policy_revision: Digest
    policy_epoch: Annotated[int, Field(ge=0, strict=True)]
    label: Literal["remember", "discard", "review"]
    coverage: Literal["complete_window", "incomplete_window"]
    extraction: GeneratedExtraction | None = None
    reason: ReasonText
    prior_rejection_ids: tuple[Handle, ...] = Field(default=(), max_length=8)
    rejection_comparisons: tuple[RejectionComparison, ...] = Field(default=(), max_length=16)
    rejection_review_ids: tuple[Handle, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def bounded_judgment(self) -> SourceSelectionCommand:
        if not 0 < self.byte_end - self.byte_start <= WINDOW_BYTES:
            raise ValueError("A bounded nonempty UTF-8 source window is required")
        if self.label != "remember" and self.extraction is not None:
            raise ValueError("Only remember may publish grounded drafts")
        if len({item.rejection_id for item in self.rejection_comparisons}) != len(self.rejection_comparisons):
            raise ValueError("Rejection comparisons must have distinct rejection IDs")
        if len(set(self.prior_rejection_ids)) != len(self.prior_rejection_ids):
            raise ValueError("Prior rejection IDs must be distinct")
        if len(set(self.rejection_review_ids)) != len(self.rejection_review_ids):
            raise ValueError("Rejection review IDs must be distinct")
        _reject_judgment_secrets(self)
        return self


class ClaimRelationJudgment(TypedModel):
    left_id: Handle
    right_id: Handle
    relation: Literal["duplicate", "supports", "contradicts", "supersedes"]
    reason: ReasonText


class ClaimJudgmentCommand(TypedModel):
    kind: Literal["claim_judgment"]
    binding_id: Handle | None = None
    idempotency_key: Key
    admission_id: Handle
    manifest_digest: Digest
    claims: tuple[RevisionRef, ...] = Field(min_length=1, max_length=20)
    sources: tuple[RevisionRef, ...] = Field(min_length=1, max_length=128)
    relations: tuple[ClaimRelationJudgment, ...] = Field(max_length=16)
    reason: ReasonText

    @model_validator(mode="after")
    def exact_manifest(self) -> ClaimJudgmentCommand:
        ids = {item.id for item in self.claims}
        if len(ids) != len(self.claims) or len({item.id for item in self.sources}) != len(self.sources):
            raise ValueError("Judgment manifests must have unique IDs")
        pairs = set()
        for item in self.relations:
            pair = tuple(sorted((item.left_id, item.right_id)))
            if item.left_id == item.right_id or not {item.left_id, item.right_id}.issubset(ids) or pair in pairs:
                raise ValueError("Relations require distinct, in-manifest pairs")
            pairs.add(pair)
        _reject_judgment_secrets(self)
        return self


def _record_tag(value: object) -> str:
    kind = value.get("kind") if isinstance(value, dict) else getattr(value, "kind", None)
    return kind if isinstance(kind, str) and kind in {
        "source_selection", "claim_judgment", "code_link", "health_assessment",
    } else "record"


RecordInput = Annotated[
    Annotated[RecordCommand, Tag("record")]
    | Annotated[SourceSelectionCommand, Tag("source_selection")]
    | Annotated[ClaimJudgmentCommand, Tag("claim_judgment")]
    | Annotated[CodeLinkCommand, Tag("code_link")]
    | Annotated[HealthAssessmentCommand, Tag("health_assessment")],
    Discriminator(_record_tag),
]
RECORD_ADAPTER = TypeAdapter(RecordInput)


SELECTION_CONTRACT_VERSION = "common-caller-grounded-original-window-v4"
_POLICY_REVISION = canonical_digest({"contract": SELECTION_CONTRACT_VERSION})


def selection_contract_revision() -> str:
    return _POLICY_REVISION


def _window(source: Source, start: int, end: int) -> Source:
    original = source.body.encode("utf-8")
    if not 0 <= start < end <= len(original) or end - start > WINDOW_BYTES:
        raise DomainError("SOURCE_WINDOW_INVALID", "Choose a bounded original source window")
    try:
        original[:start].decode("utf-8")
        body = original[start:end].decode("utf-8")
    except UnicodeDecodeError:
        raise DomainError("SOURCE_WINDOW_INVALID", "Source window offsets must align to UTF-8") from None
    return source.model_copy(update={"body": body})


def window_digest(
    source: Source, start: int, end: int, binding_revision: int,
    policy_revision: str | None, policy_epoch: int | None,
) -> str:
    view = _window(source, start, end)
    return canonical_digest({
        "source_id": source.id, "source_revision": source.revision,
        "binding_id": source.binding_id, "binding_revision": binding_revision,
        "realm": source.realm, "snapshot": source.snapshot,
        "source_speaker": source.speaker,
        "source_event_time": source.event_time.isoformat() if source.event_time else None,
        "source_recorded_at": source.recorded_at.isoformat(),
        "capture_coverage": source.coverage.model_dump(mode="json"),
        "bytes": [start, end], "body_sha256": hashlib.sha256(view.body.encode()).hexdigest(),
        "policy_revision": policy_revision, "policy_epoch": policy_epoch,
    })




def _too_large() -> DomainError:
    return DomainError(
        "SOURCE_WINDOW_TOO_LARGE", "No original source window fits the span and response bounds", status=413,
    )


def source_window(
    source: Source, start: int, max_bytes: int, binding_revision: int,
    policy_revision: str | None, policy_epoch: int | None,
    *, representation_bytes: int = 8192, metadata: Mapping[str, object] | None = None,
    request_snapshot: str | None = None,
    measure_json: Callable[[dict], int] = serialized_json_bytes,
) -> dict:
    original = source.body.encode("utf-8")
    if (
        isinstance(start, bool) or not isinstance(start, int)
        or isinstance(max_bytes, bool) or not isinstance(max_bytes, int)
        or not 0 <= start < len(original) or not 1 <= max_bytes <= WINDOW_BYTES
    ):
        raise DomainError("SOURCE_WINDOW_INVALID", "Choose a bounded original source window")
    end = min(len(original), start + max_bytes)
    while end > start:
        try:
            original[start:end].decode("utf-8")
            break
        except UnicodeDecodeError as error:
            if error.start == 0 and error.reason != "unexpected end of data":
                raise DomainError("SOURCE_WINDOW_INVALID", "The cursor must align to UTF-8") from None
            end -= 1
    coverage = source.coverage
    complete = coverage.status == "observed_window" and not coverage.gaps and (
        coverage.original_bytes is None or coverage.original_bytes == len(original)
    )

    def bounded(stop: int) -> dict | None:
        view = _window(source, start, stop)
        try:
            spans = original_spans(view)
        except DomainError as error:
            if error.code != "SOURCE_INPUT_TOO_LARGE":
                raise
            return None
        window = {
            "source_id": source.id, "source_revision": source.revision,
            "binding_id": source.binding_id, "binding_revision": binding_revision,
            "snapshot": request_snapshot, "source_snapshot": source.snapshot, "source_speaker": source.speaker,
            "source_event_time": source.event_time.isoformat() if source.event_time else None,
            "source_recorded_at": source.recorded_at.isoformat(),
            "body": view.body, "byte_start": start, "byte_end": stop,
            "total_bytes": len(original), "next_byte": stop if stop < len(original) else None,
            "partial": start != 0 or stop != len(original) or not complete,
            "coverage": {"scope": "captured_source_not_session", "capture": coverage.model_dump(mode="json"),
                         "omitted_prefix_bytes": start, "omitted_suffix_bytes": len(original) - stop,
                         "caller_consumption": "unobserved"},
            "span_inventory": [{**span.model_dump(), "byte_start": span.byte_start + start} for span in spans],
            "window_digest": window_digest(source, start, stop, binding_revision, policy_revision, policy_epoch),
            "policy_revision": policy_revision, "policy_epoch": policy_epoch,
        }
        fits = measure_json({**(metadata or {}), **window}) <= representation_bytes
        return window if fits else None

    window = bounded(end)
    if window is not None:
        return window
    stops = [start + offset for offset in accumulate(
        len(character.encode("utf-8")) for character in original[start:end].decode("utf-8")
    )]
    low, high = -1, len(stops) - 1
    while high - low > 1:
        middle = (low + high) // 2
        candidate = bounded(stops[middle])
        if candidate is None:
            high = middle
        else:
            low, window = middle, candidate
    if window is None:
        raise _too_large()
    spans = window["span_inventory"]
    # Ending before the possibly cut last span keeps every sentence whole in some window.
    if len(spans) > 1:
        return bounded(spans[-1]["byte_start"]) or window
    return window


def resolve_selection(
    command: SourceSelectionCommand, source: Source, binding_revision: int,
    policy_revision: str, policy_epoch: int,
) -> Extraction:
    if (
        source.state != "active" or source.speaker == "memory"
        or any(marker in source.body for marker in (
            "<agents-memory-context", "[agents-memory:injected]", BOUNDED_CONTEXT_MARKER,
        ))
    ):
        raise DomainError("SOURCE_INELIGIBLE", "Retrieved memory or inactive evidence cannot publish new candidates")
    if (
        source.id != command.source_id or source.revision != command.source_revision
        or (source.snapshot is not None and source.snapshot != command.snapshot)
        or binding_revision != command.binding_revision
        or policy_revision != command.policy_revision or policy_epoch != command.policy_epoch
        or policy_revision != selection_contract_revision()
    ):
        raise DomainError("SELECTION_STALE", "The source window or common selection contract changed")
    view = _window(source, command.byte_start, command.byte_end)
    if command.window_digest != window_digest(source, command.byte_start, command.byte_end, binding_revision, policy_revision, policy_epoch):
        raise DomainError("SELECTION_STALE", "The judgment does not match the original source window")
    if command.label == "remember" and source.speaker == "agent_note":
        raise DomainError("SOURCE_INELIGIBLE", "Agent notes are not independent grounding evidence")
    if command.extraction is None:
        return Extraction(claims=())
    try:
        resolved = resolve_extraction(command.extraction, view)
        claims = []
        for draft in resolved.claims:
            evidence = []
            for quote in draft.evidence:
                if quote.byte_start is None:
                    raise DomainError("EVIDENCE_INVALID", "Resolved original evidence requires a byte offset")
                evidence.append(Quote(
                    source_id=source.id, quote=quote.quote,
                    byte_start=quote.byte_start + command.byte_start,
                ))
            claims.append(draft.model_copy(update={"evidence": tuple(evidence)}))
        result = Extraction(claims=tuple(claims))
        validate_extraction(result, source)
    except DomainError as error:
        if error.code == "SOURCE_INPUT_TOO_LARGE":
            raise _too_large() from None
        if error.code != "GROUNDING_INVALID":
            raise
        raise DomainError(
            "SELECTION_GROUNDING_INVALID", "The judgment is not grounded in the original source window",
        ) from None
    return result
