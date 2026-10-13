from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath

from .domain import ActiveRule, Claim, ContextCommand, DomainError, Relation, valid_path_pattern


class Match(StrEnum):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ContextBody:
    text: str
    claim_ids: tuple[str, ...]
    rule_versions: tuple[tuple[str, int, str], ...]
    omitted: int
    byte_count: int
    relation_ids: tuple[str, ...] = ()
    unknown_rule_refs: tuple[str, ...] = ()
    unknown_rule_count: int = 0


def path_match(pattern: str, path: str) -> bool | None:
    if not valid_path_pattern(pattern):
        return None
    if not path or "\\" in path or "\0" in path or path.startswith("/") or ".." in PurePosixPath(path).parts:
        return None
    pattern = PurePosixPath(pattern).as_posix()
    path = PurePosixPath(path).as_posix()
    if path == ".":
        return None
    pieces = []
    cursor = 0
    while cursor < len(pattern):
        if pattern[cursor : cursor + 3] == "**/":
            pieces.append("(?:.*/)?")
            cursor += 3
        elif pattern[cursor : cursor + 2] == "**":
            pieces.append(".*")
            cursor += 2
        elif pattern[cursor] == "*":
            pieces.append("[^/]*")
            cursor += 1
        elif pattern[cursor] == "?":
            pieces.append("[^/]")
            cursor += 1
        else:
            pieces.append(re.escape(pattern[cursor]))
            cursor += 1
    return re.fullmatch("".join(pieces), path) is not None


def selector_match(rule: ActiveRule, command: ContextCommand) -> Match:
    selector = rule.selector
    checks: list[Match] = []
    if selector.paths:
        if command.paths is None:
            checks.append(Match.UNKNOWN)
        else:
            matches = [path_match(pattern, path) for pattern in selector.paths for path in command.paths]
            checks.append(
                Match.TRUE
                if True in matches
                else Match.UNKNOWN
                if None in matches
                else Match.FALSE
            )
    for accepted, actual in (
        (selector.purposes, command.purpose),
        (selector.hosts, command.host),
        (selector.snapshots, command.snapshot),
    ):
        if accepted:
            checks.append(
                Match.UNKNOWN if actual is None else Match.TRUE if actual in accepted else Match.FALSE
            )
    if Match.FALSE in checks:
        return Match.FALSE
    if Match.UNKNOWN in checks:
        return Match.UNKNOWN
    return Match.TRUE


def _encode(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _rule(rule: ActiveRule, applicability: Match = Match.TRUE) -> dict:
    return {
        "ref": rule.id,
        "revision": rule.revision,
        "required": rule.required,
        "applicability": applicability.value,
        "body": rule.body,
        "exceptions": list(rule.exceptions),
    }


def _claim(claim: Claim) -> dict:
    draft = claim.draft
    value = {
        "ref": claim.id,
        "interpretation_role": "model_derived_candidate",
        "statement": draft.statement,
        "polarity": draft.polarity,
        "modality": draft.modality,
        "conditions": list(draft.conditions),
        "exceptions": list(draft.exceptions),
        "evidence": [
            {"source": span.source_id, "revision": span.source_revision, "source_speaker": span.source_speaker,
             **span.model_dump(mode="json", include={"source_event_time", "source_recorded_at"}),
             "bytes": [span.byte_start, span.byte_end], "quote": span.quote}
            for span in claim.evidence
        ],
    }
    if draft.valid_from is not None or draft.valid_until is not None:
        value["valid_time"] = [
            draft.valid_from.isoformat() if draft.valid_from else None,
            draft.valid_until.isoformat() if draft.valid_until else None,
        ]
    if claim.snapshot is not None:
        value["snapshot"] = claim.snapshot
    return value


def _touching_edges(relations: Sequence[Relation], claim_ids: set[str]) -> list[dict]:
    return [
        {
            "ref": relation.id,
            "left": relation.left_id,
            "right": relation.right_id,
            "kind": relation.kind,
            "endpoints_in_context": [
                ref for ref in (relation.left_id, relation.right_id) if ref in claim_ids
            ],
        }
        for relation in relations
        if relation.left_id in claim_ids or relation.right_id in claim_ids
    ]


def compose(
    command: ContextCommand,
    rules: Sequence[ActiveRule],
    claims: Sequence[Claim],
    relations: Sequence[Relation],
    *,
    protected_action: bool = False,
) -> ContextBody:
    required: list[tuple[ActiveRule, Match]] = []
    optional: list[ActiveRule] = []
    unknown_required: list[ActiveRule] = []
    unknown_optional = 0
    for rule in rules:
        match = selector_match(rule, command)
        if rule.required:
            if protected_action and match == Match.UNKNOWN:
                raise DomainError("RULE_APPLICABILITY_UNKNOWN", "Required rule applicability is unknown")
            if match == Match.UNKNOWN:
                unknown_required.append(rule)
                continue
            if match != Match.FALSE:
                required.append((rule, match))
        elif match == Match.UNKNOWN:
            unknown_optional += 1
        elif match == Match.TRUE:
            optional.append(rule)
    required.sort(key=lambda item: (item[0].id, item[0].revision))
    optional.sort(key=lambda r: (r.id, r.revision))
    unknown_required.sort(key=lambda rule: (rule.id, rule.revision))
    value = {
        "evidence_role": "memory_candidates_not_execution_authority",
        "approved_rules": [_rule(rule, match) for rule, match in required],
        "memory_candidates": [],
        "relations": [],
    }
    text = _encode(value)
    if len(text.encode("utf-8")) > command.max_bytes:
        raise DomainError("REQUIRED_CONTEXT_OVERFLOW", "Required rules exceed the context budget")
    included_rules = [rule for rule, _ in required]
    selected_claims: list[Claim] = []
    omitted = unknown_optional + len(unknown_required)
    optional_count = 0
    for rule in optional:
        if optional_count >= command.limit:
            omitted += 1
            continue
        candidate = {**value, "approved_rules": [*value["approved_rules"], _rule(rule)]}
        if len(_encode(candidate).encode("utf-8")) <= command.max_bytes:
            value = candidate
            included_rules.append(rule)
            optional_count += 1
        else:
            omitted += 1
    claim_ids: set[str] = set()
    for claim in claims:
        if optional_count + len(selected_claims) >= command.limit:
            omitted += 1
            continue
        prospective_ids = claim_ids | {claim.id}
        candidate = {
            **value,
            "memory_candidates": [*value["memory_candidates"], _claim(claim)],
            "relations": _touching_edges(relations, prospective_ids),
        }
        if len(_encode(candidate).encode("utf-8")) <= command.max_bytes:
            value = candidate
            selected_claims.append(claim)
            claim_ids = prospective_ids
        else:
            if not selected_claims and candidate["relations"]:
                without_edges = {**candidate, "relations": []}
                if len(_encode(without_edges).encode("utf-8")) <= command.max_bytes:
                    raise DomainError(
                        "CONFLICT_CONTEXT_OVERFLOW", "Known relationship metadata exceeds the context budget",
                    )
            omitted += 1
    for relation in relations:
        if (
            command.mode == "reflect"
            and relation.kind in {"contradicts", "supersedes"}
            and {relation.left_id, relation.right_id}.intersection(claim_ids)
            and not {relation.left_id, relation.right_id} <= claim_ids
        ):
            raise DomainError("REFLECTION_CONFLICT_INPUT_INCOMPLETE", "Reflection must include both known conflict endpoints")
    for rule in unknown_required[:command.limit]:
        stub = {
            "ref": rule.id,
            "required": True,
            "applicability": Match.UNKNOWN.value,
            "body_omitted_reason": "protected_action_footprint_required",
        }
        candidate = {
            **value,
            "unknown_required_rules": [*value.get("unknown_required_rules", ()), stub],
        }
        if len(_encode(candidate).encode("utf-8")) <= command.max_bytes:
            value = candidate
            omitted -= 1
    text = _encode(value) if included_rules or selected_claims or value.get("unknown_required_rules") else ""
    return ContextBody(
        text=text,
        claim_ids=tuple(claim.id for claim in selected_claims),
        rule_versions=tuple((rule.id, rule.revision, rule.digest) for rule in included_rules),
        omitted=omitted,
        byte_count=len(text.encode("utf-8")),
        relation_ids=tuple(edge["ref"] for edge in value["relations"]),
        unknown_rule_refs=tuple(rule["ref"] for rule in value.get("unknown_required_rules", ())),
        unknown_rule_count=len(unknown_required),
    )
