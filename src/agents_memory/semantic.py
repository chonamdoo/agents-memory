from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime

from pydantic import Field, ValidationError

from .domain import (
    Claim,
    ClaimDraft,
    Consolidation,
    DomainError,
    Extraction,
    Quote,
    Source,
    TypedModel,
)
from .semantic_contract import (
    AnchoredQualification,
    GeneratedExtraction,
)

_NUMBER = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d+(?:[.,:/-]\d+)*(?:%|％)?(?![A-Za-z0-9_])")
_IDENTIFIER = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*(?:[.:/\\-][A-Za-z0-9_$]+)*")
_INLINE_CODE = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
_FENCED_CODE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
_EXPLICIT_TIME = re.compile(
    r"(?<![\dA-Za-z])\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})(?![\dA-Za-z:+-])"
)


class OriginalSpan(TypedModel):
    span_id: str
    quote: str = Field(min_length=1, max_length=4096)
    byte_start: int = Field(ge=0)


def original_spans(source: Source) -> tuple[OriginalSpan, ...]:
    result = []
    cursor = 0
    byte_cursor = 0
    boundaries = [match.end() for match in re.finditer(r"[.!?。！？](?=\s|$)|\n", source.body)]
    if not boundaries or boundaries[-1] != len(source.body):
        boundaries.append(len(source.body))
    for end in boundaries:
        raw = source.body[cursor:end]
        leading = len(raw) - len(raw.lstrip())
        text = raw.strip()
        offset = byte_cursor + len(raw[:leading].encode("utf-8"))
        for start in range(0, len(text), 2048):
            quote = text[start:start + 2048]
            if len(result) >= 128:
                raise DomainError("SOURCE_INPUT_TOO_LARGE", "The original span manifest exceeds its bound")
            result.append(OriginalSpan(
                span_id=f"s{len(result):04d}", quote=quote, byte_start=offset,
            ))
            offset += len(quote.encode("utf-8"))
        byte_cursor += len(raw.encode("utf-8"))
        cursor = end
    return tuple(result)


def _validate_temporal_bounds(claim: ClaimDraft, evidence: Sequence[str]) -> None:
    dates = set()
    for quote in evidence:
        for literal in _EXPLICIT_TIME.findall(quote):
            try:
                dates.add(datetime.fromisoformat(literal))
            except ValueError:
                continue
    for bound in (claim.valid_from, claim.valid_until):
        if bound is not None and bound not in dates:
            raise DomainError(
                "GROUNDING_INVALID", "Valid time lacks explicit original temporal evidence",
            )


def _covers_qualifications(left: ClaimDraft, right: ClaimDraft) -> bool:
    return (
        set(left.conditions).issubset(right.conditions)
        and set(left.exceptions).issubset(right.exceptions)
        and (left.valid_from is None
             or (right.valid_from is not None and left.valid_from <= right.valid_from))
        and (left.valid_until is None
             or (right.valid_until is not None and left.valid_until >= right.valid_until))
    )


def _require_references(references: Sequence[str], manifest: Mapping[str, object], label: str) -> None:
    if len(set(references)) != len(references) or any(ref not in manifest for ref in references):
        raise DomainError("GROUNDING_INVALID", f"Extraction selected invalid {label}")


def _qualification_span(qualification: AnchoredQualification, manifest: dict[str, OriginalSpan]) -> str:
    if qualification.evidence_span_id is not None:
        _require_references((qualification.evidence_span_id,), manifest, "span IDs")
        selected = manifest[qualification.evidence_span_id]
        if qualification.phrase not in selected.quote:
            raise DomainError("GROUNDING_INVALID", "A qualification is not an original evidence phrase")
        return selected.span_id
    matches = [ref for ref, span in manifest.items() if qualification.phrase in span.quote]
    if len(matches) != 1:
        raise DomainError("GROUNDING_INVALID", "A qualification has missing or ambiguous original evidence")
    return matches[0]


def resolve_extraction(result: GeneratedExtraction, source: Source) -> Extraction:
    manifest = {span.span_id: span for span in original_spans(source)}
    claims = {claim.assertion_id: claim for claim in result.claims}
    if len(claims) != len(result.claims):
        raise DomainError("GROUNDING_INVALID", "Extraction repeated an assertion ID")
    evidence_ids = {ref: [claim.assertion_span_id] for ref, claim in claims.items()}
    qualifications = {ref: [] for ref in claims}
    validities = {}
    used = set()
    for claim in result.claims:
        _require_references((claim.assertion_span_id,), manifest, "span IDs")
        used.add(claim.assertion_span_id)
    grouped_qualifications = (
        *((item, (item.assertion_id,)) for item in result.individual_qualifications),
        *((item, item.assertion_ids) for item in result.shared_qualifications),
    )
    for qualification, targets in grouped_qualifications:
        _require_references(targets, claims, "assertion IDs")
        span_id = _qualification_span(qualification, manifest)
        used.add(span_id)
        for ref in targets:
            if any((previous.kind, previous.phrase) == (qualification.kind, qualification.phrase)
                   for previous in qualifications[ref]):
                raise DomainError("GROUNDING_INVALID", "Extraction repeated a qualification")
            qualifications[ref].append(qualification)
            evidence_ids[ref].append(span_id)
    for validity in result.validities:
        _require_references(validity.assertion_ids, claims, "assertion IDs")
        _require_references(validity.evidence_span_ids, manifest, "span IDs")
        if validity.valid_from is None and validity.valid_until is None:
            raise DomainError("GROUNDING_INVALID", "Temporal evidence has no validity bound")
        used.update(validity.evidence_span_ids)
        for ref in validity.assertion_ids:
            if ref in validities:
                raise DomainError("GROUNDING_INVALID", "An assertion has ambiguous validity periods")
            validities[ref] = validity
            evidence_ids[ref].extend(validity.evidence_span_ids)
    _require_references(result.unused_span_ids, manifest, "span IDs")
    if used.intersection(result.unused_span_ids) or used.union(result.unused_span_ids) != set(manifest):
        raise DomainError("GROUNDING_INVALID", "Extraction did not account for the original span manifest")
    drafts = []
    assertions: dict[tuple[str, str, str, str, str], list[ClaimDraft]] = {}
    for claim in result.claims:
        ref = claim.assertion_id
        ids = tuple(dict.fromkeys(evidence_ids[ref]))
        validity = validities.get(ref)
        try:
            draft = ClaimDraft.model_validate({
                **claim.model_dump(exclude={"assertion_id", "assertion_span_id"}),
                "conditions": tuple(item.phrase for item in qualifications[ref] if item.kind == "condition"),
                "exceptions": tuple(item.phrase for item in qualifications[ref] if item.kind == "exception"),
                "valid_from": validity.valid_from if validity else None,
                "valid_until": validity.valid_until if validity else None,
                "evidence": tuple(Quote(
                    source_id=source.id, quote=manifest[identifier].quote,
                    byte_start=manifest[identifier].byte_start,
                ) for identifier in ids),
            })
        except ValidationError:
            raise DomainError("GROUNDING_INVALID", "Extraction returned invalid claim fields") from None
        temporal_ids = validity.evidence_span_ids if validity else ()
        _validate_temporal_bounds(draft, [manifest[identifier].quote for identifier in temporal_ids])
        identity = (
            claim.assertion_span_id, draft.subject, draft.predicate, draft.object, draft.polarity,
        )
        previous = assertions.setdefault(identity, [])
        if any(
            _covers_qualifications(existing, draft) or _covers_qualifications(draft, existing)
            for existing in previous
        ):
            raise DomainError(
                "GROUNDING_INVALID", "Extraction repeated an assertion or broadened its qualifications",
            )
        previous.append(draft)
        drafts.append(draft)
    extraction = Extraction(claims=tuple(drafts))
    validate_extraction(extraction, source)
    return extraction


def _identifiers(text: str) -> set[str]:
    values = set()
    for match in _IDENTIFIER.finditer(text):
        value = match.group()
        if (
            any(character in value for character in "_.$:\\")
            or re.search(r"[a-z][A-Z]|[A-Z]{2,}|[A-Za-z]\d", value)
            or text[match.end() :].startswith("(")
        ):
            values.add(value)
    for match in _INLINE_CODE.finditer(text):
        values.update(_IDENTIFIER.findall(match.group(1)))
    for match in _FENCED_CODE.finditer(text):
        values.update(_IDENTIFIER.findall(match.group(1)))
    return values


def _contains_identifier(text: str, identifier: str) -> bool:
    return identifier in set(_IDENTIFIER.findall(text))


def grounded_identifiers(text: str) -> tuple[str, ...]:
    """Code identifiers in ``text`` that the literal grounding check accepts against the same text."""
    return tuple(sorted(value for value in _identifiers(text) if _contains_identifier(text, value)))


def _timestamp_tokens(text: str) -> set[datetime | str]:
    values: set[datetime | str] = set()
    for literal in _EXPLICIT_TIME.findall(text):
        try:
            values.add(datetime.fromisoformat(literal))
        except ValueError:
            values.add(literal)
    return values


def _validate_literals(text: str, evidence: str) -> None:
    if not _timestamp_tokens(text).issubset(_timestamp_tokens(evidence)):
        raise DomainError("GROUNDING_INVALID", "The judgment introduced an unsupported timestamp")
    # Dates are checked as complete instants, never as truncated numbers or code identifiers.
    text = _EXPLICIT_TIME.sub(" ", text)
    evidence = _EXPLICIT_TIME.sub(" ", evidence)
    if not set(_NUMBER.findall(text)).issubset(set(_NUMBER.findall(evidence))):
        raise DomainError("GROUNDING_INVALID", "The judgment introduced an unsupported number")
    if any(not _contains_identifier(evidence, value) for value in _identifiers(text)):
        raise DomainError("GROUNDING_INVALID", "The judgment introduced an unsupported identifier")


def validate_extraction(result: Extraction, source: Source) -> None:
    original = source.body.encode("utf-8")
    for claim in result.claims:
        evidence = []
        for quote in claim.evidence:
            if quote.source_id != source.id:
                raise DomainError("GROUNDING_INVALID", "Extraction cites a foreign source")
            encoded = quote.quote.encode("utf-8")
            if quote.byte_start is None:
                present = encoded in original
            else:
                present = original[quote.byte_start : quote.byte_start + len(encoded)] == encoded
            if not present:
                raise DomainError("GROUNDING_INVALID", "Extraction quote is not an original span")
            evidence.append(quote.quote)
        for qualification in claim.conditions + claim.exceptions:
            if not any(qualification in quote for quote in evidence):
                raise DomainError("GROUNDING_INVALID", "A qualification is not an original evidence phrase")
        _validate_temporal_bounds(claim, evidence)
        _validate_literals(
            "\n".join(
                (claim.statement, claim.subject, claim.predicate, claim.object)
                + claim.conditions
                + claim.exceptions
                + claim.entities
            ),
            "\n".join(evidence),
        )




def validate_consolidation(result: Consolidation, claims: Sequence[Claim]) -> None:
    manifest = {claim.id: claim for claim in claims}
    if len(manifest) != len(claims):
        raise DomainError("JUDGMENT_MANIFEST_INVALID", "The input manifest repeats a claim")
    pairs = set()
    for relation in result.relations:
        if (
            relation.left_id not in manifest
            or relation.right_id not in manifest
            or relation.left_id == relation.right_id
        ):
            raise DomainError("GROUNDING_INVALID", "Consolidation cites an invalid pair")
        pair = tuple(sorted((relation.left_id, relation.right_id)))
        if pair in pairs:
            raise DomainError("GROUNDING_INVALID", "Consolidation repeats a pair")
        pairs.add(pair)
        left, right = manifest[relation.left_id], manifest[relation.right_id]
        if left.binding_id != right.binding_id:
            raise DomainError("GROUNDING_INVALID", "Consolidation crossed a project boundary")
        a, b = left.draft, right.draft
        scope_equal = (
            left.snapshot == right.snapshot
            and a.kind == b.kind
            and a.modality == b.modality
            and a.conditions == b.conditions
            and a.exceptions == b.exceptions
        )
        time_equal = a.valid_from == b.valid_from and a.valid_until == b.valid_until
        if relation.kind in {"duplicates", "supports", "contradicts", "supersedes"}:
            if not scope_equal:
                raise DomainError("GROUNDING_INVALID", "Consolidation lost conditions or scope")
        if relation.kind == "duplicates" and not time_equal:
            raise DomainError("GROUNDING_INVALID", "Consolidation erased valid time")
        if relation.kind in {"supports", "contradicts"}:
            disjoint = (
                a.valid_until is not None and b.valid_from is not None
                and a.valid_until <= b.valid_from
            ) or (
                b.valid_until is not None and a.valid_from is not None
                and b.valid_until <= a.valid_from
            )
            if disjoint:
                raise DomainError("GROUNDING_INVALID", "Consolidation compared disjoint valid times")
        if relation.kind in {"duplicates", "supports"} and a.polarity != b.polarity:
            raise DomainError("GROUNDING_INVALID", "Consolidation erased negation")
