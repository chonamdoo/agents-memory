from __future__ import annotations

import ast
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, create_model

from .domain import (
    ClaimDraft,
    Consolidation,
    DomainError,
    Extraction,
    ReflectionDraft,
    SmallText,
    TypedModel,
    canonical_digest,
)

GeneratedAssertion = create_model(
    "GeneratedAssertion",
    __base__=TypedModel,
    assertion_id=(str, Field(..., pattern=r"^a[0-9]{4}$")),
    assertion_span_id=(str, Field(..., min_length=1, max_length=16)),
    **{
        name: (field.rebuild_annotation(), ...)
        for name, field in ClaimDraft.model_fields.items()
        if name not in {"evidence", "conditions", "exceptions", "valid_from", "valid_until"}
    },
)


class AnchoredQualification(TypedModel):
    kind: Literal["condition", "exception", "context"]
    phrase: SmallText
    evidence_span_id: str | None = Field(max_length=16)


class IndividualQualification(AnchoredQualification):
    assertion_id: str = Field(pattern=r"^a[0-9]{4}$")


class SharedQualification(AnchoredQualification):
    assertion_ids: tuple[str, ...] = Field(min_length=2, max_length=32)


class GeneratedValidity(TypedModel):
    valid_from: datetime | None
    valid_until: datetime | None
    evidence_span_ids: tuple[str, ...] = Field(min_length=1, max_length=8)
    assertion_ids: tuple[str, ...] = Field(min_length=1, max_length=32)


class GeneratedExtraction(TypedModel):
    claims: tuple[GeneratedAssertion, ...] = Field(max_length=32)
    individual_qualifications: tuple[IndividualQualification, ...] = Field(max_length=64)
    shared_qualifications: tuple[SharedQualification, ...] = Field(max_length=64)
    validities: tuple[GeneratedValidity, ...] = Field(max_length=32)
    unused_span_ids: tuple[str, ...] = Field(max_length=128)


def explicit_generation_schema(schema: type[TypedModel]) -> dict:
    value = schema.model_json_schema()

    def require_fields(node):
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["required"] = list(node["properties"])
            for child in node.values():
                require_fields(child)
        elif isinstance(node, list):
            for child in node:
                require_fields(child)

    require_fields(value)
    return value


def require_generated_fields(value: object, schema: dict) -> None:
    definitions = schema.get("$defs", {})

    def check(item, node):
        if "$ref" in node:
            node = definitions[node["$ref"].removeprefix("#/$defs/")]
        if "anyOf" in node:
            branches = [branch for branch in node["anyOf"]
                        if branch.get("type") != "null"]
            if item is not None and len(branches) == 1:
                check(item, branches[0])
        if isinstance(item, dict) and node.get("type") == "object":
            if not set(node.get("required", ())).issubset(item):
                raise ValueError("Generated artifact omitted required fields")
            for key, child in node.get("properties", {}).items():
                if key in item:
                    check(item[key], child)
        elif isinstance(item, list) and node.get("type") == "array":
            for child in item:
                check(child, node["items"])

    check(value, schema)


_SOURCE_ROOT = Path(__file__).parent
_SOURCE_NAMES = ("semantic_contract.py", "semantic.py", "prompts.py")


def _source_stamp(path: Path) -> tuple[int, int, int, int, int]:
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns



def _source_digest(path: Path) -> str:
    syntax = ast.parse(path.read_bytes(), filename=path.name)
    return hashlib.sha256(ast.dump(syntax, include_attributes=False).encode("utf-8")).hexdigest()

def _snapshot_sources() -> dict[str, tuple[str, tuple[int, int, int, int, int]]]:
    snapshots = {}
    for name in _SOURCE_NAMES:
        path = _SOURCE_ROOT / name
        before = _source_stamp(path)
        digest = _source_digest(path)
        if before != _source_stamp(path):
            raise DomainError("MODEL_ROUTE_BLOCKED", "The semantic contract changed during startup")
        snapshots[name] = digest, before
    return snapshots


_PROCESS_SOURCES = _snapshot_sources()
_PROCESS_CONTRACT_DIGEST = canonical_digest({
    "version": "original-spans-explicit-time-v1",
    "schemas": {
        schema.__name__: explicit_generation_schema(schema)
        for schema in (GeneratedExtraction, Extraction, Consolidation, ReflectionDraft)
    },
    "implementations": {name: value[0] for name, value in _PROCESS_SOURCES.items()},
})


def process_contract_digest() -> str:
    return _PROCESS_CONTRACT_DIGEST


def assert_process_contract_current() -> None:
    try:
        for name, (digest, stamp) in _PROCESS_SOURCES.items():
            path = _SOURCE_ROOT / name
            current = _source_stamp(path)
            if current == stamp:
                continue
            if _source_digest(path) != digest or _source_stamp(path) != current:
                raise DomainError(
                    "MODEL_ROUTE_BLOCKED", "The semantic implementation changed; restart before approval",
                )
            _PROCESS_SOURCES[name] = digest, current
    except (OSError, SyntaxError):
        raise DomainError("MODEL_ROUTE_BLOCKED", "The semantic implementation is unavailable") from None


def route_revision(manifest: dict) -> str:
    assert_process_contract_current()
    return canonical_digest({"manifest": manifest, "semantic_contract": process_contract_digest()})


def embedding_revision(manifest: dict) -> str:
    descriptor = manifest.get("embedding")
    if not isinstance(descriptor, dict) or (
        not isinstance(descriptor.get("repo"), str)
        or not isinstance(descriptor.get("revision"), str)
        or descriptor.get("dimensions") != 1024
        or descriptor.get("pooling") != "cls"
        or descriptor.get("normalized") is not True
        or not isinstance(descriptor.get("artifacts"), list)
        or not descriptor["artifacts"]
    ):
        raise DomainError("MODEL_ROUTE_BLOCKED", "A verified embedding compatibility manifest is required")
    artifacts = []
    for artifact in descriptor["artifacts"]:
        if (
            not isinstance(artifact, dict)
            or not isinstance(artifact.get("path"), str)
            or not isinstance(artifact.get("sha256"), str)
            or len(artifact["sha256"]) != 64
            or any(character not in "0123456789abcdef" for character in artifact["sha256"])
            or type(artifact.get("bytes")) is not int
            or artifact["bytes"] <= 0
        ):
            raise DomainError("MODEL_ROUTE_BLOCKED", "The embedding artifact compatibility evidence is invalid")
        artifacts.append({
            "name": Path(artifact["path"]).name,
            "sha256": artifact["sha256"],
            "bytes": artifact["bytes"],
        })
    return canonical_digest({
        "contract": "bge-m3-cls-normalized-8192-v1",
        "descriptor": {
            name: descriptor.get(name)
            for name in (
                "repo", "revision", "runtime", "runtime_version", "torch_version",
                "dimensions", "pooling", "normalized",
            )
        },
        "artifacts": sorted(artifacts, key=lambda item: (item["name"], item["sha256"], item["bytes"])),
    })
