from __future__ import annotations

import base64
import binascii
import dataclasses
import math
import os
import re
import stat
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any

from mcp.shared.dispatcher import coerce_request_id

from . import context as context_module
from . import evaluation_diagnostics as diagnostics_module
from . import evaluation_gateway as gateway_module
from . import evaluation_native as native_module
from . import evaluation_scoring as scoring_module
from . import evaluation_verifier as verifier_module
from .domain import CaptureCommand, ContextCommand, DomainError, EffectState
from .evaluation_artifacts import (
    ArtifactBundle,
    ArtifactEntry,
    ArtifactLimits,
    ByteEdit,
    EditableSpan,
    EditPolicy,
    EditWitness,
    ModePermission,
    canonical_bytes,
    digest_bytes,
    load_submission,
    materialize_snapshot,
    open_private_directory,
    safe_path,
    verify_allowed_edits,
)
from .evaluation_gateway import EvaluationGateway, GatewayScope, GatewayUpstream
from .evaluation_native import NativeDriverSpec, run_native_arm
from .evaluation_runtime import (
    DockerRuntime,
    EvaluationOwner,
    RuntimeLimits,
    RuntimeSpec,
    publish_or_reconcile,
    read_publication_bytes,
)
from .evaluation_scoring import ArmObservation, RetrievalObservation, ScoringProtocol
from .evaluation_verifier import (
    ControlArtifact,
    FileExpectation,
    IndependentControlApproval,
    OracleCase,
    OracleTask,
    VerifierExecutor,
    VerifierSpec,
    controls_digest,
    verifier_source_digest,
)
from .stdio import RelayEndpoint
from .wire import decode_json, validate_wire

_HEX = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_MANIFEST_BYTES = 4 * 1024 * 1024
_FILE_BYTES = 64 * 1024 * 1024
_TOTAL_BYTES = 256 * 1024 * 1024
_MAX_FILES = 4096
_STATUSES = {"blocked", "unsupported", "busy", "failed", "timeout", "aborted", "unknown", "completed", "not_started", "incomplete"}
_MODES = ("memory_on", "required_only")


class EvaluationError(ValueError):
    pass


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise EvaluationError(code)


def _keys(value: object, required: set[str], optional: set[str] | None = None) -> dict:
    _require(isinstance(value, dict), "OBJECT_REQUIRED")
    _require(required <= value.keys() <= required | (optional or set()), "EXACT_SCHEMA_REQUIRED")
    return value


def _integer(value: object, minimum: int, maximum: int, code: str = "INTEGER_BOUND") -> int:
    _require(type(value) is int and minimum <= value <= maximum, code)
    return value


def _text(value: object, maximum: int = 4096) -> str:
    _require(isinstance(value, str) and bool(value) and len(value.encode()) <= maximum and "\x00" not in value, "TEXT_BOUND")
    return value


def _identifier(value: object) -> str:
    _require(isinstance(value, str) and _ID.fullmatch(value) is not None, "IDENTIFIER_REQUIRED")
    return value


def _digest(value: object) -> str:
    _require(isinstance(value, str) and _HEX.fullmatch(value) is not None, "SHA256_REQUIRED")
    return value


def _boolean(value: object) -> bool:
    _require(type(value) is bool, "BOOLEAN_REQUIRED")
    return value


def _array(value: object, maximum: int) -> list:
    _require(isinstance(value, list) and len(value) <= maximum, "ARRAY_BOUND")
    return value


def _binary(value: object, maximum: int) -> bytes:
    _require(isinstance(value, str) and len(value) <= ((maximum + 2) // 3) * 4, "BASE64_BOUND")
    try:
        result = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise EvaluationError("BASE64_INVALID") from None
    _require(len(result) <= maximum and base64.b64encode(result).decode("ascii") == value, "BASE64_NONCANONICAL")
    return result


def _read(path: Path, maximum: int, *, private: bool = False) -> bytes:
    _require(path.is_absolute() and ".." not in path.parts, "ABSOLUTE_NOFOLLOW_PATH_REQUIRED")
    parent = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    finally:
        os.close(parent)
    try:
        before = os.fstat(fd)
        owners = {os.getuid()} if private else {0, os.getuid()}
        _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_uid in owners, "OWNED_SINGLE_REGULAR_FILE_REQUIRED")
        _require(not before.st_mode & 0o022 and (not private or not before.st_mode & 0o077), "INPUT_PERMISSIONS")
        _require(before.st_size <= maximum, "FILE_BOUND")
        chunks = bytearray()
        while len(chunks) <= maximum:
            block = os.read(fd, min(65536, maximum + 1 - len(chunks)))
            if not block:
                break
            chunks.extend(block)
        after = os.fstat(fd)
        def identity(info):
            return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns

        _require(len(chunks) <= maximum and identity(before) == identity(after), "INPUT_UNSTABLE_OR_BOUND")
        return bytes(chunks)
    finally:
        os.close(fd)


def _mkdir(path: Path) -> None:
    parent = open_private_directory(path.parent)
    try:
        try:
            os.mkdir(path.name, 0o700, dir_fd=parent)
            os.fsync(parent)
        except FileExistsError:
            pass
    finally:
        os.close(parent)
    fd = open_private_directory(path)
    os.close(fd)


def _publish(directory: Path, name: str, value: object, maximum: int) -> str:
    raw = value if isinstance(value, bytes) else canonical_bytes(value)
    _require(len(raw) <= maximum, "RECORD_BOUND")
    fd = open_private_directory(directory)
    try:
        outcome = publish_or_reconcile(fd, name, raw)
        _require(outcome.state in {"durable", "reconciled_durable"}, "PUBLICATION_UNCERTAIN")
    finally:
        os.close(fd)
    return digest_bytes(raw)


def _existing(directory: Path, name: str, maximum: int) -> dict | None:
    descriptor = open_private_directory(directory)
    try:
        try:
            return decode_json(read_publication_bytes(descriptor, name, maximum))
        except FileNotFoundError:
            return None
    finally:
        os.close(descriptor)


def _bounded_names(fd: int, maximum: int) -> list[str]:
    result = []
    with os.scandir(fd) as entries:
        for entry in entries:
            _require(len(result) < maximum, "DIRECTORY_ENTRY_BOUND")
            result.append(entry.name)
    return result


def _gateway_config(manifest: EvaluationManifest, invocation: dict) -> dict:
    return manifest.config["preflight_gateway" if invocation["phase"] == "preflight" else "gateway"]


def _dc(cls, value: dict, transforms: dict | None = None):
    fields = dataclasses.fields(cls)
    required = {field.name for field in fields if field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING}
    parsed = dict(_keys(value, required, {field.name for field in fields} - required))
    for key, transform in (transforms or {}).items():
        if key in parsed:
            parsed[key] = transform(parsed[key])
    return cls(**parsed)


def _native(value: dict) -> NativeDriverSpec:
    result = _dc(NativeDriverSpec, value, {key: Path for key in ("executable", "cwd", "submission_path")})
    for key in ("approved_context", "exclusive_optional_route_observed", "residual_memory_absence_observed", "fresh_generation_observed", "strict_protection_required", "strict_protection_supported"):
        _boolean(getattr(result, key))
    for key in ("authorization_ref", "context_observation_ref", "gateway_invocation_id", "gateway_route_ref"):
        _text(getattr(result, key))
    _require(all(".." not in path.parts for path in (result.executable, result.cwd, result.submission_path)), "NATIVE_PATH_TRAVERSAL")
    return result


def _runtime(value: dict) -> RuntimeSpec:
    return _dc(RuntimeSpec, value, {"docker_executable": Path, "docker_config": Path, "image_environment": tuple, "limits": lambda item: _dc(RuntimeLimits, item)})


def _policy(value: dict) -> EditPolicy:
    return _dc(EditPolicy, value, {
        "spans": lambda items: tuple(_dc(EditableSpan, item) for item in items),
        "modes": lambda items: tuple(_dc(ModePermission, item) for item in items),
        "creates": tuple, "deletes": tuple,
    })


def _entry(value: dict, limits: ArtifactLimits) -> ArtifactEntry:
    _keys(value, {"path", "kind", "mode", "content", "sha256"})
    return ArtifactEntry(value["path"], value["kind"], value["mode"], _binary(value["content"], limits.file_bytes), value["sha256"])


def _witness(value: dict, limits: ArtifactLimits) -> EditWitness:
    _keys(value, {"baseline_digest", "final_digest", "edits", "creates", "deletes", "modes"})
    edits = _array(value["edits"], limits.edits)
    creates = _array(value["creates"], limits.edits)
    modes = _array(value["modes"], limits.edits)
    deletes = _array(value["deletes"], limits.edits)
    parsed = []
    for item in edits:
        _keys(item, {"path", "start", "end", "replacement"})
        parsed.append(ByteEdit(item["path"], item["start"], item["end"], _binary(item["replacement"], limits.replacement_bytes)))
    return EditWitness(_digest(value["baseline_digest"]), _digest(value["final_digest"]), tuple(parsed), tuple(_entry(item, limits) for item in creates), tuple(deletes), tuple(_dc(ModePermission, item) for item in modes))


def _case(value: dict, maximum: int) -> OracleCase:
    return _dc(OracleCase, value, {
        "argv": tuple, "stdin": lambda item: _binary(item, maximum),
        "expected_stdout": lambda item: _binary(item, maximum),
        "expected_stderr": lambda item: _binary(item, maximum),
        "effects": lambda items: tuple(_dc(FileExpectation, item, {"expected": lambda data: _binary(data, maximum)}) for item in items),
    })


@dataclass(frozen=True)
class FrozenFile:
    name: str
    path: Path
    sha256: str
    maximum_bytes: int
    raw: bytes = dataclasses.field(repr=False)


@dataclass(frozen=True)
class EvaluationManifest:
    path: Path
    digest: str
    raw: bytes = dataclasses.field(repr=False)
    files: tuple[FrozenFile, ...] = dataclasses.field(repr=False)

    @property
    def config(self) -> dict:
        value = decode_json(self.raw)
        value.setdefault("max_pair_retries", 0)
        value.setdefault("retry_statuses", [])
        return value

    def file(self, name: str) -> FrozenFile:
        for item in self.files:
            if item.name == name:
                return item
        raise EvaluationError("FROZEN_FILE_MISSING")

    def document(self, name: str) -> dict:
        return decode_json(self.file(name).raw)

    @property
    def workload(self) -> dict:
        return self.document("workload")


@dataclass(frozen=True)
class RunState:
    manifest_digest: str
    run_dir: Path
    schedule: tuple[tuple[str, int, tuple[str, str]], ...]


def _schedule(manifest: EvaluationManifest) -> tuple[tuple[str, int, tuple[str, str]], ...]:
    config, workload = manifest.config, manifest.workload
    ordered = sorted(workload["tasks"], key=lambda task: digest_bytes(canonical_bytes([config["seed"], task["task_id"]])))
    result = []
    for repeat in range(config["repeats"]):
        for index, task in enumerate(ordered):
            modes = _MODES if (index + repeat) % 2 == 0 else tuple(reversed(_MODES))
            result.append((task["task_id"], repeat, modes))
    return tuple(result)


def _pair_id(manifest: EvaluationManifest, task_id: str, repeat: int) -> str:
    return digest_bytes(canonical_bytes([manifest.digest, task_id, repeat]))


def _invocation(manifest: EvaluationManifest, invocation_id: str) -> dict:
    for item in manifest.workload["invocations"]:
        if item["invocation_id"] == invocation_id:
            return item
    raise EvaluationError("INVOCATION_NOT_FROZEN")


def _task(manifest: EvaluationManifest, task_id: str) -> dict:
    return next(item for item in manifest.workload["tasks"] if item["task_id"] == task_id)


def _bundle(manifest: EvaluationManifest, name: str) -> ArtifactBundle:
    frozen = manifest.file(name)
    limits = _dc(ArtifactLimits, manifest.config["artifact_limits"])
    _require(digest_bytes(_read(frozen.path, frozen.maximum_bytes)) == frozen.sha256, "INPUT_DRIFT")
    return load_submission(frozen.path, limits=limits)


def _task_inputs(manifest: EvaluationManifest, task: dict):
    limits = _dc(ArtifactLimits, manifest.config["artifact_limits"])
    baseline = _bundle(manifest, task["baseline_file"])
    policy = _policy(manifest.document(task["policy_file"]))
    oracle = manifest.document(task["oracle_file"])
    _keys(oracle, {"schema", "cases"})
    _require(type(oracle["schema"]) is int and oracle["schema"] == 1, "ORACLE_SCHEMA")
    cases = tuple(_case(item, manifest.config["record_bytes"]) for item in _array(oracle["cases"], manifest.config["verifier_limits"]["max_cases"]))
    controls = []
    for item in task["controls"]:
        _keys(item, {"role", "bundle_file", "witness_file"})
        controls.append(ControlArtifact(item["role"], _bundle(manifest, item["bundle_file"]), _witness(manifest.document(item["witness_file"]), limits)))
    _require(tuple(item.role for item in controls) == ("correct", "noop", "plausible_wrong"), "ORDERED_CONTROLS_REQUIRED")
    empty = EditWitness(baseline.digest, baseline.digest, (), (), (), ())
    result = OracleTask(task["task_id"], task["task_revision"], task["independent_reference"], baseline.digest, policy, empty, cases)
    _require(controls[1].bundle.digest == baseline.digest and len({item.bundle.digest for item in controls}) == 3, "CONTROL_IDENTITIES")
    for control in controls:
        _require(verify_allowed_edits(baseline, control.bundle, policy, control.witness).passed, "CONTROL_STRUCTURE_INVALID")
    _require(_digest(task["approved_task_digest"]) == result.digest and _digest(task["approved_controls_digest"]) == controls_digest(tuple(controls)), "SUPPLIED_CONTROL_APPROVAL_IDENTITY_MISMATCH")
    return baseline, result, tuple(controls)


def _validate_documents(manifest: EvaluationManifest) -> None:
    config, workload = manifest.config, manifest.workload
    _keys(workload, {"schema", "tasks", "retrieval", "preflight", "invocations"})
    _require(type(workload["schema"]) is int and workload["schema"] == 1, "WORKLOAD_SCHEMA")
    tasks = _array(workload["tasks"], 600)
    retrieval = _array(workload["retrieval"], 12000)
    _require(bool(tasks), "CODING_TASKS_REQUIRED")
    ids, clusters = set(), set()
    for task in tasks:
        _keys(task, {"task_id", "task_revision", "cluster_id", "prompt_file", "baseline_file", "policy_file", "oracle_file", "controls", "approval_reference", "approved_task_digest", "approved_controls_digest", "independent_reference", "witness_name"})
        identity = _identifier(task["task_id"])
        _require(identity not in ids, "DUPLICATE_TASK")
        ids.add(identity)
        clusters.add(_identifier(task["cluster_id"]))
        _text(task["task_revision"])
        _text(task["approval_reference"])
        _text(task["independent_reference"])
        safe_path(task["witness_name"], depth=1, path_bytes=255, component_bytes=255)
        manifest.file(task["prompt_file"]).raw.decode("utf-8")
        _task_inputs(manifest, task)
    gold = manifest.document("gold")
    _keys(gold, {"schema", "independence", "cases"})
    _require(gold["schema"] == 1 and type(gold["schema"]) is int and gold["independence"] == "provided_unattested", "GOLD_PROVENANCE")
    corpus = manifest.document("corpus")
    _keys(corpus, {"schema", "sources", "claims", "relations"})
    _require(type(corpus["schema"]) is int and corpus["schema"] == 2, "CORPUS_SCHEMA")
    sources = {}
    for source in _array(corpus["sources"], 12000):
        _keys(source, {"source_id", "revision", "body", "sha256", "inspection_windows"})
        _text(source["source_id"])
        _integer(source["revision"], 1, 2**63 - 1)
        body = _binary(source["body"], _FILE_BYTES)
        body.decode("utf-8")
        _require(source["source_id"] not in sources and digest_bytes(body) == _digest(source["sha256"]), "SOURCE_IDENTITY")
        sources[source["source_id"]] = (source["revision"], body)
        windows = _array(source["inspection_windows"], 32768)
        _require(bool(windows), "COMPLETE_SOURCE_WINDOWS_REQUIRED")
        cursor = 0
        for window in windows:
            _keys(window, {"byte_start", "byte_end", "window_digest"})
            _require(_integer(window["byte_start"], 0, len(body)) == cursor, "SOURCE_WINDOW_GAP")
            end = _integer(window["byte_end"], cursor, len(body))
            _require(end > cursor or len(body) == 0 and len(windows) == 1, "SOURCE_WINDOW_PROGRESS")
            body[cursor:end].decode("utf-8")
            _digest(window["window_digest"])
            cursor = end
        _require(cursor == len(body), "COMPLETE_SOURCE_WINDOWS_REQUIRED")
    claim_ids = set()
    for claim in _array(corpus["claims"], 12000):
        _keys(claim, {"ref", "projection", "health_dependency_digest"})
        _text(claim["ref"])
        _require(claim["ref"] not in claim_ids, "DUPLICATE_CLAIM")
        claim_ids.add(claim["ref"])
        _digest(claim["health_dependency_digest"])
        projection = _keys(claim["projection"], {"id", "kind", "state", "statement", "evidence", "input_source_ids", "snapshot", "interpretation_role", "selection_id", "policy_revision", "revision", "awaiting_revalidation", "draft", "judgment_context_refs"})
        _require(projection["id"] == claim["ref"] and projection["kind"] == "claim" and projection["state"] == "active", "CLAIM_IDENTITY")
        for span in _array(projection["evidence"], 1024):
            _require(isinstance(span, dict) and span.get("source_id") in sources, "CLAIM_SOURCE_MISSING")
            revision, body = sources[span["source_id"]]
            start = _integer(span.get("byte_start"), 0, len(body))
            end = _integer(span.get("byte_end"), start + 1, len(body))
            _require(type(span.get("source_revision")) is int and span["source_revision"] == revision and isinstance(span.get("quote"), str) and body[start:end] == span["quote"].encode(), "CLAIM_GROUNDING_MISMATCH")
        diagnostics_module.render_frozen_claim(claim)
    relation_ids, relation_keys = set(), set()
    for edge in _array(corpus["relations"], 12000):
        _keys(edge, {"ref", "projection"})
        _text(edge["ref"])
        projection = _keys(edge["projection"], {
            "id", "kind", "state", "left_id", "right_id", "relation_kind",
            "interpretation_role", "awaiting_revalidation",
        })
        _require(projection["id"] == edge["ref"] and projection["kind"] == "relation"
                 and projection["state"] == "active"
                 and projection["left_id"] in claim_ids and projection["right_id"] in claim_ids
                 and projection["interpretation_role"] == "caller_judged_relation"
                 and projection["awaiting_revalidation"] is False,
                 "FROZEN_RELATION_IDENTITY_OR_SCOPE")
        _text(projection["relation_kind"], 128)
        key = (projection["left_id"], projection["right_id"], projection["relation_kind"])
        _require(edge["ref"] not in relation_ids and key not in relation_keys,
                 "DUPLICATE_FROZEN_RELATION")
        relation_ids.add(edge["ref"])
        relation_keys.add(key)
    _require([edge["ref"] for edge in corpus["relations"]] == sorted(relation_ids),
             "FROZEN_RELATION_ORDER")
    approved_corpus_refs = ({source["source_id"] for source in corpus["sources"]}
                            | claim_ids | relation_ids | {"health:claim:" + ref for ref in claim_ids})
    _require(approved_corpus_refs <= set(config["gateway"]["approved_refs"]),
             "EXPLICIT_CORPUS_AND_HEALTH_INSPECTION_SCOPE_REQUIRED")
    cases, groups = {}, {}
    for case in _array(gold["cases"], 12000):
        _keys(case, {"case_id", "cluster_id", "group", "relevant_claim_ids", "irrelevant_claim_ids", "judgment_complete", "grounding_refs"})
        identity = _identifier(case["case_id"])
        _require(identity not in cases, "DUPLICATE_GOLD_CASE")
        _identifier(case["cluster_id"])
        groups[case["group"]] = groups.get(case["group"], 0) + 1
        relevant, irrelevant = case["relevant_claim_ids"], case["irrelevant_claim_ids"]
        _array(relevant, 12000)
        _array(irrelevant, 12000)
        _require(len(set(relevant)) == len(relevant) and len(set(irrelevant)) == len(irrelevant) and not set(relevant) & set(irrelevant) and set(relevant + irrelevant) <= claim_ids, "GOLD_CLAIM_MAPPING")
        _boolean(case["judgment_complete"])
        for anchor in _array(case["grounding_refs"], 12000):
            _keys(anchor, {"source_id", "revision", "byte_start", "byte_end", "quote_digest"})
            _require(anchor["source_id"] in sources, "GOLD_SOURCE_MISSING")
            revision, body = sources[anchor["source_id"]]
            start = _integer(anchor["byte_start"], 0, len(body))
            end = _integer(anchor["byte_end"], start + 1, len(body))
            _require(type(anchor["revision"]) is int and anchor["revision"] == revision and digest_bytes(body[start:end]) == _digest(anchor["quote_digest"]), "GOLD_ANCHOR_MISMATCH")
            body[:start].decode("utf-8")
            body[start:end].decode("utf-8")
        cases[identity] = case
    retrieval_ids = set()
    for case in retrieval:
        _keys(case, {"case_id", "prompt_file", "request"})
        _require(case["case_id"] in cases and case["case_id"] not in retrieval_ids, "RETRIEVAL_GOLD_IDENTITY")
        retrieval_ids.add(case["case_id"])
        manifest.file(case["prompt_file"]).raw.decode("utf-8")
        request = validate_wire(ContextCommand, case["request"])
        _require(request.admission_id is None and request.limit == 3 and "max_bytes" in case["request"] and "limit" in case["request"], "FROZEN_RECALL_BUDGET_REQUIRED")
        _require(request.binding_id == config["gateway"]["binding_id"], "RETRIEVAL_BINDING_IDENTITY")
        _require(all(case["request"].get(key) == config["gateway"]["required_request"].get(key) for key in ("paths", "purpose", "host", "snapshot")), "RETRIEVAL_REQUIRED_SELECTORS")
    _require(retrieval_ids == set(cases), "EXACT_GOLD_WORKLOAD_REQUIRED")
    preflight = _keys(workload["preflight"], {"invocation_id", "capture", "recall_request", "prompt_file", "baseline_file"})
    capture = validate_wire(CaptureCommand, preflight["capture"])
    _require(not capture.injected and capture.binding_id == config["preflight_gateway"]["binding_id"], "PREFLIGHT_SOURCE_SCOPE")
    validate_wire(ContextCommand, preflight["recall_request"])
    manifest.file(preflight["prompt_file"]).raw.decode("utf-8")
    _bundle(manifest, preflight["baseline_file"])
    invocations = _array(workload["invocations"], 50000)
    observed, directories, mappings = set(), set(), set()
    expected = {("preflight", preflight["invocation_id"], None, None, None, "memory_on")}
    expected.update(("retrieval", case["case_id"], None, None, None, mode) for case in retrieval for mode in _MODES)
    expected.update(("coding", task["task_id"], repeat, attempt, None, mode) for task in tasks for repeat in range(config["repeats"]) for attempt in range(config["max_pair_retries"] + 1) for mode in _MODES)
    for invocation in invocations:
        _keys(invocation, {"invocation_id", "phase", "target_id", "repeat_index", "pair_attempt", "mode", "native", "context_file"})
        identity = _identifier(invocation["invocation_id"])
        _require(identity not in observed and invocation["mode"] in _MODES, "INVOCATION_IDENTITY")
        observed.add(identity)
        spec = _native(invocation["native"])
        _require(spec.gateway_invocation_id == identity and spec.gateway_route_ref == _gateway_config(manifest, invocation)["route_ref"], "GATEWAY_NATIVE_IDENTITY")
        _require(str(spec.cwd) not in directories, "FRESH_WORKSPACE_REQUIRED")
        directories.add(str(spec.cwd))
        context = manifest.document(invocation["context_file"])
        _keys(context, {"schema", "independence", "settings_digest", "permissions_digest", "route_ref", "ownership_boundary_ref", "exclusive_optional_route_observed", "residual_memory_absence_observed", "fresh_generation_observed"})
        _require(type(context["schema"]) is int and context["schema"] == 1 and context["independence"] == "provided_unattested", "CONTEXT_PROVENANCE")
        _require(context["settings_digest"] == config["settings_digest"] and context["permissions_digest"] == config["permissions_digest"] and context["route_ref"] == spec.gateway_route_ref, "FROZEN_CONTEXT_MISMATCH")
        _text(context["ownership_boundary_ref"])
        for key in ("exclusive_optional_route_observed", "residual_memory_absence_observed", "fresh_generation_observed"):
            _require(_boolean(context[key]) == getattr(spec, key), "CONTEXT_OBSERVATION_MISMATCH")
        phase = invocation["phase"]
        _require(phase in {"coding", "retrieval", "preflight"}, "INVOCATION_PHASE")
        if phase == "coding":
            _integer(invocation["repeat_index"], 0, config["repeats"] - 1)
            _integer(invocation["pair_attempt"], 0, config["max_pair_retries"])
        else:
            _require(invocation["repeat_index"] is None and invocation["pair_attempt"] is None, "NONCODING_PAIR_FIELDS")
        key = (phase, invocation["target_id"], invocation["repeat_index"], invocation["pair_attempt"], None, invocation["mode"])
        _require(key in expected and key not in mappings, "EXACT_INVOCATION_SCHEDULE_REQUIRED")
        mappings.add(key)
        if phase == "preflight":
            _require(identity == preflight["invocation_id"], "PREFLIGHT_INVOCATION")
        if phase == "coding":
            task = _task(manifest, invocation["target_id"])
            _require(spec.submission_path.name != task["witness_name"], "WITNESS_SUBMISSION_COLLISION")
    _require(mappings == expected, "MISSING_FROZEN_INVOCATION")
    for task_id, repeat, _ in _schedule(manifest):
        for attempt in range(config["max_pair_retries"] + 1):
            specs = [_native(_select(manifest, "coding", task_id, mode, repeat, attempt)["native"]) for mode in _MODES]
            varying = {"cwd", "submission_path", "gateway_invocation_id", "context_observation_ref", "authorization_ref"}
            _require({key: value for key, value in dataclasses.asdict(specs[0]).items() if key not in varying} == {key: value for key, value in dataclasses.asdict(specs[1]).items() if key not in varying}, "PAIRED_NATIVE_BUDGET_OR_CONTEXT_MISMATCH")
    paths = sorted(Path(value) for value in directories)
    _require(not any(right.is_relative_to(left) for index, left in enumerate(paths) for right in paths[index + 1:]), "OVERLAPPING_NATIVE_WORKSPACES")
    _validate_rule_snapshot(manifest.document("rules"))
    _require(config["gateway"]["rules_file"] == "rules", "MEASURED_RULE_FILE_IDENTITY")
    preflight_rules = manifest.document(config["preflight_gateway"]["rules_file"])
    _keys(preflight_rules, {"schema", "rules"})
    _require(type(preflight_rules["schema"]) is int and preflight_rules["schema"] == 1 and isinstance(preflight_rules["rules"], list), "PREFLIGHT_RULE_SCHEMA")
    _require(preflight_rules["rules"] == sorted(preflight_rules["rules"]), "PREFLIGHT_RULE_ORDER")
    for rule in preflight_rules["rules"]:
        _require(isinstance(rule, list) and len(rule) == 3, "PREFLIGHT_RULE_IDENTITY")
        _text(rule[0])
        _integer(rule[1], 1, 2**63 - 1)
        _digest(rule[2])
    native_identity = manifest.document("native_identity")
    _keys(native_identity, {"schema", "backend", "fields", "executable_sha256"}, {"mode_fields"})
    _digest(native_identity["executable_sha256"])
    _require(type(native_identity["schema"]) is int and native_identity["schema"] == 1 and native_identity["backend"] in {"claude", "codex"}, "NATIVE_IDENTITY_SCHEMA")
    fields = native_identity["fields"]
    _require(isinstance(fields, dict) and bool(fields) and all(value is not None for value in fields.values()), "NATIVE_IDENTITY_FIELDS")
    mandatory = {"model", "claude_code_version", "permissionMode"} if native_identity["backend"] == "claude" else {"initialize.userAgent", "resolved.model", "resolved.approvalPolicy", "resolved.sandbox"}
    _require(mandatory <= fields.keys(), "MODEL_VERSION_PERMISSION_IDENTITY_REQUIRED")
    variants = native_identity.get("mode_fields", {"memory_on": {}, "required_only": {}})
    _keys(variants, set(_MODES))
    for mode in _MODES:
        variant = variants[mode]
        _require(isinstance(variant, dict) and variant.keys() <= {"tools", "mcp_servers"} and not variant.keys() & fields.keys() and all(value is not None for value in variant.values()), "NATIVE_TREATMENT_FIELDS")
        if native_identity["backend"] == "claude":
            _require({"tools", "mcp_servers"} <= fields.keys() | variant.keys(), "NATIVE_TOOL_ROUTE_IDENTITY_REQUIRED")
    _require(all(_native(item["native"]).backend == native_identity["backend"] for item in invocations), "MIXED_NATIVE_BACKENDS")
    _native_tool_routes(manifest)
    if config["scope"] == "evaluation":
        _require(len(tasks) == 60 and len(clusters) == 60 and config["repeats"] == 3 and len(cases) >= 120 and len(groups) == 10 and min(groups.values()) >= 12, "ORIGINAL_EVALUATION_TARGETS_REQUIRED")


def load_manifest(path: Path, *, expected_sha256: str | None = None) -> EvaluationManifest:
    path = path.absolute()
    raw = _read(path, _MANIFEST_BYTES)
    digest = digest_bytes(raw)
    if expected_sha256 is not None:
        _require(digest == _digest(expected_sha256), "MANIFEST_DIGEST_MISMATCH")
    value = decode_json(raw)
    _keys(value, {"schema", "scope", "source_commit", "controller_digest", "verifier_digest", "settings_digest", "permissions_digest", "seed", "repeats", "resamples", "confidence", "concurrency", "record_bytes", "trace_bytes", "trace_events", "artifact_limits", "verifier_limits", "owner", "gateway", "preflight_gateway", "usage_budgets", "files", "independence"}, {"max_pair_retries", "retry_statuses"})
    value.setdefault("max_pair_retries", 0)
    value.setdefault("retry_statuses", [])
    _require(type(value["schema"]) is int and value["schema"] == 1 and value["scope"] in {"engineering", "evaluation"}, "MANIFEST_SCHEMA")
    _require(value["independence"] == "provided_unattested", "INDEPENDENCE_NOT_ATTESTED")
    _require(isinstance(value["source_commit"], str) and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value["source_commit"]) is not None, "SOURCE_COMMIT_REQUIRED")
    for key in ("controller_digest", "verifier_digest", "settings_digest", "permissions_digest"):
        _digest(value[key])
    _integer(value["seed"], 0, 2**63 - 1)
    _integer(value["repeats"], 1, 3)
    _require(type(value["resamples"]) is int and value["resamples"] == 10000 and type(value["confidence"]) is float and value["confidence"] == 0.95, "FROZEN_BOOTSTRAP_REQUIRED")
    _integer(value["max_pair_retries"], 0, 20)
    statuses = _array(value["retry_statuses"], len(_STATUSES))
    _require(len(set(statuses)) == len(statuses) and set(statuses) <= _STATUSES, "RETRY_ELIGIBILITY")
    _require(value["max_pair_retries"] > 0 or not statuses, "DEFAULT_RETRY_ZERO")
    _integer(value["concurrency"], 1, 32)
    _integer(value["record_bytes"], 1024, _FILE_BYTES)
    _integer(value["trace_bytes"], 1024, _TOTAL_BYTES)
    _integer(value["trace_events"], 1, 100000)
    _keys(value["usage_budgets"], {"input_tokens", "output_tokens", "total_tokens", "cost_usd"})
    for key, limit in value["usage_budgets"].items():
        if limit is not None:
            if key == "cost_usd":
                _require(type(limit) in {int, float} and math.isfinite(limit) and limit > 0, "COST_BUDGET")
            else:
                _integer(limit, 1, 2**63 - 1)
    _dc(ArtifactLimits, value["artifact_limits"])
    _keys(value["verifier_limits"], {"max_cases", "max_effects", "private_receipt_bytes"})
    for number in value["verifier_limits"].values():
        _integer(number, 1, _FILE_BYTES)
    _keys(value["owner"], {"run_id", "run_attempt", "job_id"})
    for item in value["owner"].values():
        _text(item, 128)
    for name in ("gateway", "preflight_gateway"):
        _validate_gateway(value[name])
    _require(value["gateway"]["binding_id"] != value["preflight_gateway"]["binding_id"], "PREFLIGHT_MUST_NOT_MUTATE_FROZEN_CORPUS_BINDING")
    files, names, total = [], set(), 0
    for item in _array(value["files"], _MAX_FILES):
        _keys(item, {"name", "path", "sha256", "maximum_bytes"})
        name = _identifier(item["name"])
        _require(name not in names, "DUPLICATE_FROZEN_FILE")
        names.add(name)
        maximum = _integer(item["maximum_bytes"], 1, _FILE_BYTES)
        source = Path(_text(item["path"]))
        source = source if source.is_absolute() else path.parent / source
        content = _read(source, maximum)
        _require(digest_bytes(content) == _digest(item["sha256"]), "FROZEN_FILE_DIGEST_MISMATCH")
        total += len(content)
        _require(total <= _TOTAL_BYTES, "FROZEN_INPUT_TOTAL_BOUND")
        files.append(FrozenFile(name, source, item["sha256"], maximum, content))
    _require({"wheel", "controller", "verifier", "native_driver", "gateway_driver", "scoring", "diagnostics", "context_renderer",
              "corpus", "gold", "workload", "rules", "native_identity", "native_tool_mapping", "runtime"} <= names,
             "REQUIRED_FROZEN_INPUTS")
    result = EvaluationManifest(path, digest, raw, tuple(files))
    _require(result.file("controller").sha256 == value["controller_digest"], "CONTROLLER_FILE_IDENTITY")
    _runtime(result.document("runtime"))
    _validate_documents(result)
    _protocol(result)
    return result


def _endpoint(value: dict) -> RelayEndpoint:
    return _dc(RelayEndpoint, value, {"state_dir": lambda item: Path(item) if item is not None else None, "health_receipt": lambda item: Path(item) if item is not None else None, "remote_settings": _remote_settings})


def _remote_settings(value: dict | None):
    if value is None:
        return None
    from .connection import RemoteClientSettings
    return validate_wire(RemoteClientSettings, value)


def _validate_gateway(gateway: dict) -> None:
    _keys(gateway, {"route_ref", "binding_id", "agent", "producer", "approved_upstream_urls", "approved_refs", "protocol_version", "max_calls", "max_trace_bytes", "required_request", "lifetime_seconds", "rules_file"})
    _identifier(gateway["rules_file"])
    for key in ("route_ref", "binding_id", "protocol_version"):
        _text(gateway[key])
    request = validate_wire(ContextCommand, gateway["required_request"])
    _require(request.binding_id == gateway["binding_id"] and request.admission_id is None and "max_bytes" in gateway["required_request"] and "limit" in gateway["required_request"], "EXPLICIT_REQUIRED_CONTEXT_BUDGET")
    urls = _array(gateway["approved_upstream_urls"], 32)
    for ref in _array(gateway["approved_refs"], 24000):
        _text(ref)
    for role in ("agent", "producer"):
        upstream = _keys(gateway[role], {"endpoint", "token_file", "approval_ref"})
        endpoint = _endpoint(upstream["endpoint"])
        _require(endpoint.base_url in urls, "APPROVED_UPSTREAM_REQUIRED")
        _require(Path(upstream["token_file"]).is_absolute(), "ABSOLUTE_CREDENTIAL_REFERENCE")
        _text(upstream["approval_ref"])
    _require(gateway["agent"]["token_file"] != gateway["producer"]["token_file"], "DISTINCT_CREDENTIALS_REQUIRED")
    _require(gateway["agent"]["endpoint"] == gateway["producer"]["endpoint"], "ONE_AUTHORITY_REQUIRED")
    _integer(gateway["max_calls"], 1, 100000)
    _integer(gateway["max_trace_bytes"], 1024, _TOTAL_BYTES)
    lifetime = gateway["lifetime_seconds"]
    _require(type(lifetime) in {int, float} and math.isfinite(lifetime) and lifetime > 0, "GATEWAY_LIFETIME")


def prepare_run(manifest: EvaluationManifest, run_dir: Path) -> RunState:
    _require(run_dir.is_absolute(), "ABSOLUTE_RUN_DIRECTORY")
    _mkdir(run_dir)
    config = manifest.config
    for invocation in manifest.workload["invocations"]:
        cwd = _native(invocation["native"]).cwd
        _require(not run_dir.is_relative_to(cwd) and not cwd.is_relative_to(run_dir), "CONTROLLER_NATIVE_OWNERSHIP_SEPARATION")
    for child in ("inputs", "ledger", "traces", "artifacts", "verifiers"):
        _mkdir(run_dir / child)
    _publish(run_dir, "manifest.json", manifest.raw, _MANIFEST_BYTES)
    identity = {"schema": 1, "manifest_digest": manifest.digest, "files": [{"name": item.name, "sha256": item.sha256, "bytes": len(item.raw)} for item in manifest.files], "owner": config["owner"]}
    _publish(run_dir, "run.json", identity, config["record_bytes"])
    for item in manifest.files:
        _publish(run_dir / "inputs", item.name + ".frozen", item.raw, item.maximum_bytes)
    schedule = _schedule(manifest)
    _publish(run_dir, "schedule.json", [{"pair_id": _pair_id(manifest, task, repeat), "task_id": task, "repeat_index": repeat, "modes": modes} for task, repeat, modes in schedule], config["record_bytes"])
    return RunState(manifest.digest, run_dir, schedule)


def _private_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"$bytes": base64.b64encode(value).decode("ascii"), "size": len(value), "sha256": digest_bytes(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {field.name: _private_value(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, dict):
        _require(all(isinstance(key, str) for key in value), "TRACE_STRING_KEYS_REQUIRED")
        return {key: _private_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_private_value(item) for item in value]
    _require(value is None or type(value) in {str, int, float, bool}, "TRACE_VALUE_UNSUPPORTED")
    return value


class PrivateTrace:
    def __init__(self, manifest: EvaluationManifest, run_dir: Path, invocation_id: str, channel: str):
        _identifier(invocation_id)
        _identifier(channel)
        self.maximum = manifest.config["trace_bytes"]
        self.event_limit = manifest.config["trace_events"]
        self.record_limit = manifest.config["record_bytes"]
        self.directory = run_dir / "traces" / invocation_id
        _mkdir(self.directory)
        self.directory /= channel
        _mkdir(self.directory)
        self.lock = threading.Lock()
        self.sequence = self.total = 0
        self.previous = manifest.digest
        claim = self.directory / "claim.json"
        fd = open_private_directory(self.directory)
        try:
            from .private_io import private_write
            private_write(claim, canonical_bytes({"manifest_digest": manifest.digest, "invocation_id": invocation_id, "channel": channel}), directory=fd)
        finally:
            os.close(fd)

    def __call__(self, event: dict) -> None:
        with self.lock:
            encoded = _private_value(event)
            raw = canonical_bytes({"schema": 1, "sequence": self.sequence, "previous_digest": self.previous, "event": encoded})
            if self.sequence >= self.event_limit or self.total + len(raw) > self.maximum or len(raw) > self.record_limit:
                _publish(self.directory, "overflow.json", {"schema": 1, "sequence": self.sequence, "previous_digest": self.previous, "code": "PRIVATE_TRACE_BOUND"}, self.record_limit)
                raise EvaluationError("PRIVATE_TRACE_BOUND")
            self.previous = _publish(self.directory, f"{self.sequence:08d}.json", raw, self.record_limit)
            self.sequence += 1
            self.total += len(raw)


def _key(invocation_id: str) -> str:
    return digest_bytes(invocation_id.encode())


def _claim_generation(manifest: EvaluationManifest, run_dir: Path, invocation_id: str, generation: str) -> str:
    _text(generation, 512)
    name = "generation-" + digest_bytes(generation.encode()) + ".json"
    value = {"manifest_digest": manifest.digest, "invocation_id": invocation_id, "generation_digest": digest_bytes(generation.encode())}
    directory = open_private_directory(run_dir / "ledger")
    try:
        from .private_io import private_write
        try:
            private_write(run_dir / "ledger" / name, canonical_bytes(value), directory=directory)
        except FileExistsError:
            _require(_existing(run_dir / "ledger", name, manifest.config["record_bytes"]) == value, "NATIVE_GENERATION_REUSED")
    finally:
        os.close(directory)
    return digest_bytes(canonical_bytes(value))


def _intent(manifest: EvaluationManifest, run_dir: Path, invocation: dict) -> bool:
    name = _key(invocation["invocation_id"]) + ".intent.json"
    value = {"schema": 1, "manifest_digest": manifest.digest, "invocation": invocation}
    fd = open_private_directory(run_dir / "ledger")
    try:
        from .private_io import private_write
        try:
            private_write(run_dir / "ledger" / name, canonical_bytes(value), directory=fd)
        except FileExistsError:
            publication = publish_or_reconcile(fd, name, canonical_bytes(value))
            _require(publication.state in {"durable", "reconciled_durable"}, "ATTEMPT_INTENT_CONFLICT")
            return False
    finally:
        os.close(fd)
    return True


def _terminal(manifest: EvaluationManifest, run_dir: Path, invocation: dict, result: dict) -> None:
    _publish(run_dir / "ledger", _key(invocation["invocation_id"]) + ".terminal.json", {"schema": 1, "manifest_digest": manifest.digest, "invocation_id": invocation["invocation_id"], **result}, manifest.config["record_bytes"])


def _read_terminal(manifest: EvaluationManifest, run_dir: Path, invocation: dict) -> dict | None:
    return _checked_terminal(manifest, invocation, _existing(
        run_dir / "ledger", _key(invocation["invocation_id"]) + ".terminal.json", manifest.config["record_bytes"]))


def _checked_terminal(manifest: EvaluationManifest, invocation: dict, result: dict | None) -> dict | None:
    if result is not None:
        _keys(result, set(_initial_result()) | {"schema", "manifest_digest", "invocation_id"}, set())
        _require(type(result["schema"]) is int and result["schema"] == 1 and result["manifest_digest"] == manifest.digest and result["invocation_id"] == invocation["invocation_id"], "TERMINAL_IDENTITY_DRIFT")
    return result


def _scope(manifest: EvaluationManifest, invocation: dict, extra_refs: tuple[str, ...] = ()) -> GatewayScope:
    config, spec = _gateway_config(manifest, invocation), _native(invocation["native"])
    return GatewayScope(invocation_id=invocation["invocation_id"], route_ref=config["route_ref"], mode=invocation["mode"], phase="preflight" if invocation["phase"] == "preflight" else "coding", binding_id=config["binding_id"], approved_upstream_urls=tuple(config["approved_upstream_urls"]), approved_refs=tuple(config["approved_refs"]) + extra_refs, protocol_version=config["protocol_version"], max_calls=config["max_calls"], max_trace_bytes=config["max_trace_bytes"], required_request=config["required_request"], exclusive_route_observation_ref=spec.context_observation_ref if spec.exclusive_optional_route_observed else None, residual_memory_observation_ref=spec.context_observation_ref if spec.residual_memory_absence_observed else None)


def _upstream(manifest: EvaluationManifest, role: str, invocation: dict) -> GatewayUpstream:
    config = _gateway_config(manifest, invocation)
    value = config[role]
    return GatewayUpstream(_endpoint(value["endpoint"]), Path(value["token_file"]), role, config["binding_id"], value["approval_ref"])


class _RunGateway(EvaluationGateway):
    def __init__(self, *args, manifest: EvaluationManifest, run_dir: Path, **kwargs):
        self.manifest, self.run_dir = manifest, run_dir
        self.required_reads = []
        self.context_calls = []
        super().__init__(*args, **kwargs)

    def call_tool(self, name: str, arguments: dict, *, downstream_request_id=None) -> dict:
        if downstream_request_id is None:
            raise DomainError("NATIVE_STDIO_DELIVERY_REQUIRED", "Use the native invocation's MCP stdio route")
        return super().call_tool(name, arguments, downstream_request_id=downstream_request_id)

    def _complete_delivery(self, item: dict, channel: str, raw: bytes | None = None) -> None:
        if channel != "stdio" or raw is None:
            raise DomainError("NATIVE_STDIO_DELIVERY_REQUIRED", "A completed native stdio response is required",
                              effect=EffectState.UNKNOWN)
        if not item["is_error"] and item["name"] in {"memory_required_context", "memory_context"}:
            record = {"request": item["arguments"], "result": item["payload"]}
            self._trace("controller_context_delivery", name=item["name"], call_id=item["call_id"],
                        downstream_request_id=item["downstream_request_id"],
                        written_sha256=digest_bytes(raw), **record)
            (self.required_reads if item["name"] == "memory_required_context" else self.context_calls).append(record)
        super()._complete_delivery(item, channel, raw)


    def close(self) -> None:
        failures = []
        try:
            super().close()
        except BaseException as error:
            failures.append(error)
        try:
            flow = {**self.flow_observation(), "required_reads": self.required_reads, "context_calls": self.context_calls}
            _publish(self.run_dir / "ledger", _key(self.scope.invocation_id) + ".gateway.json",
                     _private_value(flow), self.manifest.config["record_bytes"])
        except BaseException as error:
            failures.append(error)
        if failures:
            raise DomainError("GATEWAY_CLOSE_INCOMPLETE", "Private gateway cleanup or receipt needs reconciliation",
                              effect=EffectState.UNKNOWN) from BaseExceptionGroup("Private gateway close failures", failures)


    async def run_stdio(self, *, timeout_seconds: float) -> None:
        _require(timeout_seconds == _gateway_config(self.manifest, _invocation(self.manifest, self.scope.invocation_id))["lifetime_seconds"], "FROZEN_GATEWAY_LIFETIME_REQUIRED")
        failures = []
        try:
            await super().run_stdio(timeout_seconds=timeout_seconds)
        except BaseException as error:
            failures.append(error)
        try:
            self.close()
        except BaseException as error:
            failures.append(error)
        if failures:
            raise DomainError("GATEWAY_SESSION_INCOMPLETE", "The native gateway session is incomplete",
                              effect=EffectState.UNKNOWN) from BaseExceptionGroup("Private gateway session failures", failures)



def _running_sources(manifest: EvaluationManifest) -> None:
    for name, source in (("controller", __file__), ("verifier", verifier_module.__file__),
                         ("native_driver", native_module.__file__), ("gateway_driver", gateway_module.__file__),
                         ("scoring", scoring_module.__file__), ("diagnostics", diagnostics_module.__file__),
                         ("context_renderer", context_module.__file__)):
        _require(digest_bytes(_read(Path(source).absolute(), _FILE_BYTES)) == manifest.file(name).sha256, "RUNNING_SOURCE_IDENTITY_DRIFT")
    _require(verifier_source_digest() == manifest.config["verifier_digest"], "RUNNING_VERIFIER_IDENTITY_DRIFT")


def build_gateway(manifest: EvaluationManifest, invocation_id: str, run_dir: Path) -> EvaluationGateway:
    invocation = _invocation(manifest, invocation_id)
    _running_sources(manifest)
    frozen = _read(run_dir / "manifest.json", _MANIFEST_BYTES, private=True)
    _require(digest_bytes(frozen) == manifest.digest, "RUN_GATEWAY_MANIFEST_MISMATCH")
    intent = _existing(run_dir / "ledger", _key(invocation_id) + ".intent.json", manifest.config["record_bytes"])
    _require(intent is not None and intent["manifest_digest"] == manifest.digest and intent["invocation"] == invocation, "LIVE_INVOCATION_INTENT_REQUIRED")
    _require(_read_terminal(manifest, run_dir, invocation) is None, "INVOCATION_ALREADY_TERMINAL")
    refs = ()
    if invocation["phase"] == "preflight":
        captured = _existing(run_dir / "ledger", _key(invocation_id) + ".capture.json", manifest.config["record_bytes"])
        _require(captured is not None, "PREFLIGHT_CAPTURE_REQUIRED")
        refs = (captured["source_pointer"]["source_id"],)
    trace = PrivateTrace(manifest, run_dir, invocation_id, "gateway")
    return _RunGateway(_scope(manifest, invocation, refs), agent=_upstream(manifest, "agent", invocation), producer=_upstream(manifest, "producer", invocation) if invocation["phase"] == "preflight" else None, trace_sink=trace, manifest=manifest, run_dir=run_dir)


def _payload(result: dict) -> dict:
    _require(not result.get("isError") and isinstance(result.get("content"), list) and len(result["content"]) == 1, "MCP_TOOL_FAILURE")
    return gateway_module._tool_payload(result)


def _inspect(gateway: EvaluationGateway, ref: str, maximum: int, *, claim_ids: tuple[str, ...] | None = None) -> dict:
    offset, chunks, expected = 0, bytearray(), None
    while True:
        payload = _payload(gateway.call_tool("memory_inspect", {"ref": ref, "binding_id": gateway.scope.binding_id, "byte_start": offset, "max_bytes": 4096, **({"claim_ids": list(claim_ids)} if claim_ids is not None else {}), **{key: value for key, value in gateway.required_request.items() if key == "snapshot"}}))
        window = payload.get("draft_window")
        if not isinstance(window, dict):
            _require(offset == 0, "INSPECTION_REPRESENTATION_CHANGED")
            return payload
        body = window.get("body")
        _require(isinstance(body, str) and window.get("byte_start") == offset and type(window.get("total_bytes")) is int and window["total_bytes"] <= maximum, "INSPECTION_WINDOW")
        identity = (window.get("digest"), window["total_bytes"])
        _require(expected is None or expected == identity, "INSPECTION_CHANGED")
        expected = identity
        chunks.extend(body.encode())
        _require(len(chunks) <= maximum and window.get("byte_end") == len(chunks) and len(chunks) > offset, "INSPECTION_BOUND_OR_GAP")
        if window.get("next_byte") is None:
            _require(len(chunks) == identity[1] and digest_bytes(chunks) == identity[0], "INSPECTION_DIGEST")
            return decode_json(bytes(chunks))
        offset = window["next_byte"]
        _require(type(offset) is int and offset == len(chunks), "INSPECTION_CURSOR")


def _validate_rule_snapshot(snapshot: dict) -> None:
    _keys(snapshot, {"schema", "rules", "probe", "applicable"})
    _require(type(snapshot["schema"]) is int and snapshot["schema"] == 2,
             "RULE_SNAPSHOT_SCHEMA")
    for identity in _array(snapshot["rules"], 4096):
        _require(isinstance(identity, list) and len(identity) == 3, "RULE_IDENTITY")
        _text(identity[0])
        _integer(identity[1], 1, 2**63 - 1)
        _digest(identity[2])
    probe = _keys(snapshot["probe"], {"query", "max_bytes", "limit"})
    _text(probe["query"])
    _require(type(probe["max_bytes"]) is int and probe["max_bytes"] == 6144
             and type(probe["limit"]) is int and probe["limit"] == 5, "RULE_PROBE_BOUND")
    applicable = [diagnostics_module.PackingRule.model_validate(rule)
                  for rule in _array(snapshot["applicable"], 4096)]
    _require(all(rule.applicability == "true" for rule in applicable)
             and len({rule.ref for rule in applicable}) == len(applicable)
             and sum(not rule.required for rule in applicable) <= 5, "RULE_SNAPSHOT_INCOMPLETE")
    ordered = sorted(applicable, key=lambda rule: (not rule.required, rule.ref, rule.revision))
    _require([rule.model_dump(mode="json") for rule in ordered] == snapshot["applicable"],
             "RULE_SNAPSHOT_ORDER")
    required = sorted([[rule.ref, rule.revision, rule.digest]
                       for rule in applicable if rule.required])
    _require(snapshot["rules"] == required, "RULE_REQUIRED_SNAPSHOT_IDENTITY")


def _rules_probe_request(manifest: EvaluationManifest) -> dict:
    return {
        **{key: value for key, value in manifest.config["gateway"]["required_request"].items()
           if key not in {"query", "query_expansions", "max_bytes", "limit"}},
        **manifest.document("rules")["probe"],
    }


def _rule_snapshot(payload: dict) -> list[dict]:
    _require(type(payload.get("omitted")) is int and payload["omitted"] == 0
             and type(payload.get("unresolved_required_rule_count")) is int
             and payload["unresolved_required_rule_count"] == 0
             and payload.get("refs") == [] and payload.get("candidate_manifest") == []
             and payload.get("judgment_required") is False, "COMPLETE_APPLICABLE_RULE_SET_UNAVAILABLE")
    text = payload.get("context")
    _require(isinstance(text, str), "RULE_PROBE_CONTEXT_UNAVAILABLE")
    context = decode_json(text.encode()) if text else {"approved_rules": []}
    _require(isinstance(context, dict) and isinstance(context.get("approved_rules"), list),
             "RULE_PROBE_CONTEXT_UNAVAILABLE")
    versions = payload.get("stamp", {}).get("rules")
    _require(isinstance(versions, list) and len(versions) == len(context["approved_rules"]),
             "RULE_PROBE_IDENTITY_UNAVAILABLE")
    result = []
    for rule, identity in zip(context["approved_rules"], versions, strict=True):
        _require(isinstance(rule, dict) and isinstance(identity, list) and len(identity) == 3
                 and identity[:2] == [rule.get("ref"), rule.get("revision")],
                 "RULE_PROBE_CONTENT_IDENTITY_MISMATCH")
        parsed = diagnostics_module.PackingRule.model_validate({**rule, "digest": identity[2]})
        _require(parsed.applicability == "true", "RULE_PROBE_APPLICABILITY_UNKNOWN")
        result.append(parsed.model_dump(mode="json"))
    return result


def _relation_manifest_ids(manifest: EvaluationManifest, payload: dict, claim_ids: tuple[str, ...]) -> set[str]:
    claims = payload.get("claims")
    _require(isinstance(claims, list) and len(claims) == len(claim_ids)
             and all(isinstance(row, dict) for row in claims)
             and {row.get("id") for row in claims} == set(claim_ids),
             "COMPLETE_RELATION_CLAIM_SCOPE_UNAVAILABLE")
    expected = {row["ref"]: row for row in manifest.document("corpus")["claims"]}
    for row in claims:
        _keys(row, {"id", "revision"})
        _require(type(row["revision"]) is int
                 and row["revision"] == expected[row["id"]]["projection"]["revision"],
                 "RELATION_MANIFEST_CLAIM_DRIFT")
    refs = payload.get("relation_ids")
    _require(isinstance(refs, list) and len(refs) <= 128
             and all(isinstance(ref, str) and bool(ref) for ref in refs)
             and len(set(refs)) == len(refs), "COMPLETE_RELATION_SET_UNAVAILABLE")
    return set(refs)


def _fence(manifest: EvaluationManifest, run_dir: Path, invocation: dict, stage: str) -> dict:
    trace = PrivateTrace(manifest, run_dir, invocation["invocation_id"], stage)
    corpus = manifest.document("corpus")
    relation_refs = tuple(edge["ref"] for edge in corpus["relations"])
    scope = replace(_scope(manifest, invocation, ("judgment", *relation_refs)), mode="memory_on", phase="coding",
                    required_request=_rules_probe_request(manifest))
    gateway = EvaluationGateway(scope, agent=_upstream(manifest, "agent", invocation), producer=None, trace_sink=trace)
    try:
        required = _payload(gateway.call_tool("memory_required_context", scope.required_request))
        rules = sorted(required["stamp"]["rules"])
        _require(rules == manifest.document("rules")["rules"], "REQUIRED_RULE_IDENTITY_DRIFT")
        probe = _payload(gateway.call_tool("memory_context", scope.required_request))
        _require(_rule_snapshot(probe) == manifest.document("rules")["applicable"],
                 "APPLICABLE_RULE_SET_OR_CONTENT_DRIFT")
        for source in corpus["sources"]:
            expected = _binary(source["body"], _FILE_BYTES)
            offset, collected = 0, bytearray()
            observed_windows = []
            while True:
                payload = _payload(gateway.call_tool("memory_inspect", {"ref": source["source_id"], "binding_id": scope.binding_id, "byte_start": offset, "max_bytes": 4096, **{key: value for key, value in scope.required_request.items() if key == "snapshot"}}))
                _require(payload.get("source_id") == source["source_id"] and payload.get("source_revision") == source["revision"] and payload.get("byte_start") == offset and payload.get("total_bytes") == len(expected), "CORPUS_SOURCE_DRIFT")
                body = payload.get("body")
                _require(isinstance(body, str), "CORPUS_SOURCE_UNAVAILABLE")
                collected.extend(body.encode())
                _require(len(collected) <= len(expected) and payload.get("byte_end") == len(collected), "CORPUS_SOURCE_BOUND")
                observed_windows.append({key: payload.get(key)
                                         for key in ("byte_start", "byte_end", "window_digest")})
                following = payload.get("next_byte")
                if following is None:
                    break
                _require(type(following) is int and following == len(collected) and following > offset, "CORPUS_SOURCE_CURSOR")
                offset = following
            _require(bytes(collected) == expected, "CORPUS_SOURCE_BYTES_DRIFT")
            _require(observed_windows == source["inspection_windows"],
                     "CORPUS_SOURCE_AUTHORITY_POLICY_OR_SNAPSHOT_DRIFT")
        for claim in corpus["claims"]:
            actual = _inspect(gateway, claim["ref"], manifest.config["record_bytes"])
            _require({key: actual.get(key) for key in claim["projection"]} == claim["projection"], "CORPUS_CLAIM_DRIFT")
            health = _inspect(gateway, "health:claim:" + claim["ref"], manifest.config["record_bytes"])
            _require(health.get("partial") is not True
                     and health.get("dependency_digest") == claim["health_dependency_digest"],
                     "CORPUS_HEALTH_AUTHORITY_OR_CODE_DEPENDENCY_DRIFT")
        refs = tuple(claim["ref"] for claim in corpus["claims"])
        observed_relations = set()
        for start in range(0, len(refs), 20):
            batch = refs[start:start + 20]
            judgment = _inspect(gateway, "judgment", manifest.config["record_bytes"], claim_ids=batch)
            observed_relations.update(_relation_manifest_ids(manifest, judgment, batch))
        _require(observed_relations == set(relation_refs), "ELIGIBLE_RELATION_SET_DRIFT")
        for edge in corpus["relations"]:
            actual = _inspect(gateway, edge["ref"], manifest.config["record_bytes"])
            _require({key: actual.get(key) for key in edge["projection"]} == edge["projection"],
                     "ELIGIBLE_RELATION_CONTENT_DRIFT")
        return {"corpus_digest": manifest.file("corpus").sha256, "required_rules_digest": manifest.file("rules").sha256}
    finally:
        gateway.close()


def _native_identity(manifest: EvaluationManifest, native: dict, mode: str) -> bool:
    identity = manifest.document("native_identity")
    if native_module.observed_model_identity(native, backend=identity["backend"]).matched_model is None:
        return False
    observed = native["identity"]
    fields = {**identity["fields"], **identity.get("mode_fields", {}).get(mode, {})}
    for path, expected in fields.items():
        value = observed
        for component in path.split("."):
            if not isinstance(value, dict) or component not in value:
                return False
            value = value[component]
        if value != expected:
            return False
    return True


def _native_tool_routes(manifest: EvaluationManifest) -> list[dict]:
    mapping = manifest.document("native_tool_mapping")
    _keys(mapping, {"schema", "backend", "routes"})
    _require(type(mapping["schema"]) is int and mapping["schema"] == 1
             and mapping["backend"] == manifest.document("native_identity")["backend"], "NATIVE_TOOL_MAPPING_SCHEMA")
    expected = {manifest.config[name]["route_ref"] for name in ("gateway", "preflight_gateway")}
    routes = _array(mapping["routes"], 2)
    _require(len(routes) == len(expected) and {route.get("route_ref") for route in routes} == expected,
             "NATIVE_TOOL_MAPPING_ROUTES")
    for route in routes:
        _keys(route, {"route_ref", "server", "tools"})
        server = _text(route["server"], 128)
        tools = route["tools"]
        _require(isinstance(tools, dict) and tools.keys() == {"memory_required_context", *gateway_module.SCHEMAS},
                 "NATIVE_TOOL_MAPPING_TOOLS")
        names = [_text(value, 512) for value in tools.values()]
        _require(len(set(names)) == len(names), "NATIVE_TOOL_MAPPING_AMBIGUOUS")
        if mapping["backend"] == "claude":
            _require(all(name.startswith("mcp__" + server + "__") for name in names),
                     "NATIVE_TOOL_MAPPING_SERVER_PREFIX")
    return routes


def _native_content_digest(content: object) -> str:
    if isinstance(content, list):
        _require(len(content) == 1 and isinstance(content[0], dict) and content[0].get("type") == "text",
                 "NATIVE_TOOL_RESULT_CONTENT_UNKNOWN")
        content = content[0].get("text")
    _require(isinstance(content, str), "NATIVE_TOOL_RESULT_CONTENT_UNKNOWN")
    try:
        value = decode_json(content.encode())
    except (ValueError, UnicodeError):
        raise EvaluationError("NATIVE_TOOL_RESULT_CONTENT_UNKNOWN") from None
    _require(isinstance(value, dict), "NATIVE_TOOL_RESULT_CONTENT_UNKNOWN")
    return digest_bytes(canonical_bytes(value))


def _native_tool_link(manifest: EvaluationManifest, invocation: dict, native: dict, receipt: dict, deliveries: dict) -> dict:
    route_ref = _gateway_config(manifest, invocation)["route_ref"]
    mapping = next(route for route in _native_tool_routes(manifest) if route["route_ref"] == route_ref)
    _require(native.get("invocation_id") == invocation["invocation_id"], "NATIVE_TOOL_INVOCATION_MISMATCH")
    backend = manifest.document("native_identity")["backend"]
    try:
        calls = native_module.observe_native_tool_calls(
            native, backend=backend, server=mapping["server"], tools=mapping["tools"],
        )
    except ValueError as error:
        raise EvaluationError(str(error)) from None
    indexed, wire = {}, {}
    for call in calls:
        signature = (call["name"], digest_bytes(canonical_bytes(call["arguments"])), _native_content_digest(call["content"]))
        key = call["action_id"] if backend == "codex" else signature
        indexed.setdefault(key, []).append((call, signature))
    for call_id, delivery in deliveries.items():
        event, request = delivery["event"], delivery["request"]
        _require(event.get("invocation_id") == invocation["invocation_id"] and event.get("route_ref") == route_ref,
                 "NATIVE_TOOL_GATEWAY_SCOPE_MISMATCH")
        _require(event["is_error"] is False, "NATIVE_TOOL_DELIVERY_UNOBSERVED")
        arguments = request["params"].get("arguments") or {}
        signature = (event["name"], digest_bytes(canonical_bytes(arguments)), _native_content_digest(delivery["content"]))
        if backend == "codex":
            lineage = request["params"].get("_meta")
            _require(isinstance(lineage, dict) and isinstance(lineage.get("callId"), str)
                     and lineage.get("threadId") == native["identity"].get("thread_id"),
                     "NATIVE_TOOL_LINEAGE_UNOBSERVED_OR_FOREIGN")
            key = lineage["callId"]
        else:
            key = signature
        wire.setdefault(key, []).append((call_id, delivery, signature))
    _require(indexed and indexed.keys() == wire.keys(), "NATIVE_TOOL_DELIVERY_UNOBSERVED")
    links = []
    for key, native_calls in indexed.items():
        native_calls.sort(key=lambda item: item[0]["start_event_index"])
        wire_calls = sorted(wire[key], key=lambda item: item[1]["request_index"])
        _require(len(native_calls) == len(wire_calls), "NATIVE_TOOL_MAPPING_AMBIGUOUS")
        for previous, current in zip(native_calls, native_calls[1:]):
            _require(previous[0]["result_event_index"] < current[0]["start_event_index"],
                     "NATIVE_TOOL_MAPPING_AMBIGUOUS")
        for previous, current in zip(wire_calls, wire_calls[1:]):
            _require(previous[1]["written_index"] < current[1]["request_index"], "NATIVE_TOOL_MAPPING_AMBIGUOUS")
        for (call, signature), (call_id, delivery, dispatched) in zip(native_calls, wire_calls, strict=True):
            _require(signature == dispatched, "NATIVE_TOOL_REQUEST_OR_RESULT_MISMATCH")
            event = delivery["event"]
            links.append({
                "native_action_id": call["action_id"], "native_tool": mapping["tools"][event["name"]],
                "native_start_event_digest": call["start_event_digest"], "native_result_event_digest": call["result_event_digest"],
                "native_start_observed_ns": call["start_observed_ns"], "native_result_observed_ns": call["result_observed_ns"],
                "native_start_event_index": call["start_event_index"], "native_result_event_index": call["result_event_index"],
                "gateway_call_id": call_id, "downstream_request_id": event["downstream_request_id"],
                "gateway_request_index": delivery["request_index"], "gateway_written_index": delivery["written_index"],
                "gateway_written_sha256": event["written_sha256"], "arguments_digest": signature[1], "content_digest": signature[2],
                "mapping_basis": "native_metadata" if backend == "codex" else ("exact_serial" if len(native_calls) > 1 else "exact_unique"),
            })
    return {"schema": 1, "manifest_digest": manifest.digest, "invocation_id": invocation["invocation_id"],
            "backend": backend, "route_ref": route_ref, "server": mapping["server"],
            "mapping_digest": manifest.file("native_tool_mapping").sha256,
            "native_receipt_digest": digest_bytes(canonical_bytes(native)),
            "gateway_receipt_digest": digest_bytes(canonical_bytes(receipt)),
            "links": links, "provider_consumption": None}


def _owner(manifest: EvaluationManifest, invocation_id: str, nonce: str) -> EvaluationOwner:
    return EvaluationOwner(**manifest.config["owner"], attempt_id=invocation_id, nonce=nonce)


def _verifier_spec(manifest: EvaluationManifest) -> VerifierSpec:
    config = manifest.config
    return VerifierSpec(_runtime(manifest.document("runtime")), config["controller_digest"], config["verifier_digest"], **config["verifier_limits"])


def _reconcile(manifest: EvaluationManifest, run_dir: Path, invocation: dict) -> None:
    verifier_id = _pair_verifier_id(manifest, invocation) if invocation["phase"] == "coding" else invocation["invocation_id"]
    directory = run_dir / "verifiers" / verifier_id
    try:
        fd = open_private_directory(directory)
    except FileNotFoundError:
        return
    try:
        names = _bounded_names(fd, manifest.config["trace_events"])
        owners = [name for name in names if re.fullmatch(r"[0-9a-f]{64}\.owner\.json", name)]
        for name in owners:
            record = decode_json(_read(directory / name, manifest.config["record_bytes"], private=True))
            owner = EvaluationOwner(**record["owner"])
            _require(owner.identity + ".owner.json" == name and owner.attempt_id == verifier_id, "RECOVERY_OWNER_MISMATCH")
            runtime = DockerRuntime(_runtime(manifest.document("runtime")), owner, directory)
            try:
                outcomes = runtime.reconcile_all(maximum_entries=manifest.config["trace_events"], maximum_intents=manifest.config["trace_events"])
                recovery = _private_value(outcomes)
                suffix = digest_bytes(canonical_bytes(recovery))
                _publish(run_dir / "ledger", _key(invocation["invocation_id"]) + ".recovery." + suffix + ".json", recovery, manifest.config["record_bytes"])
            finally:
                runtime.close()
    finally:
        os.close(fd)


def _initial_result() -> dict:
    return {"status": "not_started", "comparable": False, "comparability_reasons": [], "contaminated": False, "native_identity_observed": False, "corpus_before_digest": None, "corpus_after_digest": None, "required_rules_digest": None, "native_identity_digest": None, "structural_pass": None, "functional_success": None, "cleanup_complete": None, "control_receipt_digest": None, "verifier_receipt_digest": None, "artifact_digest": None, "latency_seconds": None, "input_tokens": None, "output_tokens": None, "total_tokens": None, "cost_usd": None, "cost_basis": "unknown", "cpu_seconds": None, "peak_rss_bytes": None, "disk_bytes": None, "evidence_refs": {}, "code": None}


def _usage(result: dict, native) -> None:
    counters = native.usage.get("counters") or {}
    for field, alternatives in {"input_tokens": ("input_tokens", "inputTokens"), "output_tokens": ("output_tokens", "outputTokens"), "total_tokens": ("total_tokens", "totalTokens")}.items():
        result[field] = next((counters[key] for key in alternatives if key in counters), None)
    for key in ("cpu_seconds", "peak_rss_bytes", "disk_bytes", "cost_usd"):
        result[key] = native.usage.get(key)
    basis = native.usage.get("cost_basis")
    result["cost_basis"] = "native_client_estimate" if result["cost_usd"] is not None and basis == "native_client_estimate_not_bill" else "unknown"
    result["latency_seconds"] = (native.finished_ns - native.started_ns) / 1_000_000_000


def _validate_context_call(manifest: EvaluationManifest, record: dict) -> None:
    request, payload = record["request"], record["result"]
    command = validate_wire(ContextCommand, request)
    corpus = manifest.document("corpus")
    claims = {claim["ref"]: claim for claim in corpus["claims"]}
    candidates = payload.get("candidate_manifest", [])
    _require(isinstance(candidates, list) and all(
        isinstance(item, dict) and item.get("claim_id") in claims for item in candidates
    ), "UNFROZEN_CORPUS_CANDIDATE")
    text = payload.get("context")
    _require(isinstance(text, str), "FROZEN_CONTEXT_UNAVAILABLE")
    value = {"evidence_role": "memory_candidates_not_execution_authority",
             "approved_rules": [], "memory_candidates": [], "relations": []}
    context = decode_json(text.encode()) if text else value
    _require(isinstance(context, dict), "FROZEN_CONTEXT_UNAVAILABLE")
    rules = [diagnostics_module.PackingRule.model_validate(rule)
             for rule in manifest.document("rules")["applicable"]]
    included = [rule for rule in rules if rule.required]
    value = {**value, "approved_rules": [rule.rendered() for rule in included]}
    if payload.get("judgment_required") is not True:
        optional_count = 0
        for rule in rules:
            if rule.required or optional_count == command.limit:
                continue
            prospective = {**value, "approved_rules": [*value["approved_rules"], rule.rendered()]}
            if len(canonical_bytes(prospective)) <= command.max_bytes:
                value = prospective
                included.append(rule)
                optional_count += 1
    _require(context.get("approved_rules") == value["approved_rules"]
             and payload.get("stamp", {}).get("rules")
             == [[rule.ref, rule.revision, rule.digest] for rule in included],
             "DELIVERED_APPLICABLE_RULE_CONTENT_OR_IDENTITY_DRIFT")
    actual = context.get("memory_candidates")
    _require(isinstance(actual, list) and all(isinstance(item, dict) for item in actual),
             "FROZEN_CONTEXT_CLAIMS_UNAVAILABLE")
    refs = [item.get("ref") for item in actual]
    _require(all(isinstance(ref, str) and ref in claims for ref in refs)
             and len(refs) == len(set(refs)) and payload.get("refs") == refs,
             "UNFROZEN_CORPUS_DELIVERY")
    _require(actual == [diagnostics_module.render_frozen_claim(claims[ref]) for ref in refs],
             "DELIVERED_FROZEN_CLAIM_CONTENT_DRIFT")
    selected = set(refs)
    edges = [edge for edge in corpus["relations"]
             if edge["projection"]["left_id"] in selected or edge["projection"]["right_id"] in selected]
    expected_edges = [{
        "ref": edge["ref"], "left": edge["projection"]["left_id"],
        "right": edge["projection"]["right_id"], "kind": edge["projection"]["relation_kind"],
        "endpoints_in_context": [ref for ref in (edge["projection"]["left_id"], edge["projection"]["right_id"])
                                 if ref in selected],
    } for edge in edges]
    _require(context.get("relations") == expected_edges, "DELIVERED_ELIGIBLE_RELATION_DRIFT")


def _native_deliveries(events: list[dict]) -> dict[str, dict]:
    requests, writes, intents, request_ids = {}, {}, {}, set()
    for event_index, event in enumerate(events):
        if event.get("stage") in {"gateway_stdio_received", "gateway_stdio_written"}:
            raw = _unbytes(event["body"])
            _require(raw.endswith(b"\n") and raw.count(b"\n") == 1, "NATIVE_STDIO_RECORD_INCOMPLETE")
            message = decode_json(raw)
            _require(isinstance(message, dict), "NATIVE_STDIO_RECORD_INVALID")
            if event["stage"] == "gateway_stdio_written":
                if type(message.get("id")) not in {str, int}:
                    continue
                digest = digest_bytes(raw)
                _require(digest not in writes, "NATIVE_STDIO_RESPONSE_REUSED")
                writes[digest] = (raw, message, event_index)
            elif "id" in message and isinstance(message.get("method"), str):
                identifier = message["id"]
                _require(type(identifier) in {str, int}, "NATIVE_STDIO_ID_INVALID")
                key, correlated = (type(identifier), identifier), coerce_request_id(identifier)
                _require(correlated not in request_ids, "NATIVE_STDIO_REQUEST_REUSED")
                request_ids.add(correlated)
                requests[key] = (message, event_index)
        elif event.get("stage") == "gateway_intent":
            _require(event.get("call_id") not in intents, "NATIVE_GATEWAY_INTENT_REUSED")
            intents[event["call_id"]] = event
    deliveries = {}
    for event in events:
        if event.get("stage") != "gateway_delivery" or event.get("channel") != "stdio":
            continue
        identifier, call_id = event.get("downstream_request_id"), event.get("call_id")
        _require(type(identifier) in {str, int} and call_id not in deliveries,
                 "NATIVE_STDIO_DELIVERY_ID_INVALID")
        requested = requests.get((type(identifier), identifier))
        intent = intents.get(call_id)
        written = writes.get(event.get("written_sha256"))
        _require(requested is not None and intent is not None and written is not None
                 and intent.get("name") == event.get("name")
                 and type(intent.get("downstream_request_id")) is type(identifier)
                 and intent["downstream_request_id"] == identifier, "NATIVE_STDIO_DELIVERY_INTENT_UNKNOWN")
        request, request_index = requested
        raw, response, written_index = written
        params, result = request.get("params", {}), response.get("result")
        content = result.get("content") if isinstance(result, dict) else None
        _require(request.get("method") == "tools/call" and params.get("name") == event.get("name")
                 and type(response.get("id")) is type(identifier) and response["id"] == identifier
                 and event.get("stdout_write_complete") is True and event.get("written_bytes") == len(raw)
                 and isinstance(result, dict) and type(event.get("is_error")) is bool
                 and result.get("isError", False) is event["is_error"]
                 and isinstance(content, list) and len(content) == 1 and isinstance(content[0], dict)
                 and isinstance(content[0].get("text"), str)
                 and digest_bytes(content[0]["text"].encode()) == event.get("payload_sha256"),
                 "NATIVE_STDIO_DELIVERY_FRAME_MISMATCH")
        deliveries[call_id] = {"event": event, "request": request,
                               "payload": gateway_module._tool_payload(result), "content": content,
                               "request_index": request_index, "written_index": written_index}
    return deliveries


def _validate_delivery_receipt(manifest: EvaluationManifest, invocation: dict, receipt: dict, events: list[dict]) -> dict:
    _require(receipt.get("invocation_id") == invocation["invocation_id"]
             and receipt.get("mode") == invocation["mode"]
             and receipt.get("observation_complete") is True, "GATEWAY_DELIVERY_UNOBSERVED")
    native = _native_deliveries(events)
    required_reads, context_calls = [], []
    context_ids = set()
    for event in events:
        if event.get("stage") != "controller_context_delivery":
            continue
        delivery = native.get(event.get("call_id"))
        _require(delivery is not None and not delivery["event"]["is_error"]
                 and event.get("call_id") not in context_ids
                 and delivery["event"]["invocation_id"] == invocation["invocation_id"]
                 and delivery["event"]["route_ref"] == _gateway_config(manifest, invocation)["route_ref"]
                 and event.get("written_sha256") == delivery["event"]["written_sha256"]
                 and event.get("name") == delivery["event"]["name"]
                 and event.get("request") == (delivery["request"].get("params", {}).get("arguments") or {})
                 and event.get("result") == delivery["payload"], "NATIVE_CONTEXT_DELIVERY_FRAME_UNKNOWN")
        context_ids.add(event["call_id"])
        record = {"request": event["request"], "result": event["result"]}
        _require(event["name"] in {"memory_required_context", "memory_context"},
                 "NATIVE_CONTEXT_DELIVERY_KIND_INVALID")
        (required_reads if event["name"] == "memory_required_context" else context_calls).append(record)
    _require(required_reads and receipt.get("required_reads") == required_reads
             and receipt.get("context_calls") == context_calls, "NATIVE_CONTEXT_RECEIPT_DRIFT")
    stamps = [record["result"]["stamp"] for record in required_reads]
    expected = manifest.document(_gateway_config(manifest, invocation)["rules_file"])["rules"]
    _require(receipt.get("required_stamps") == stamps
             and all(sorted(stamp.get("rules", [])) == expected for stamp in stamps),
             "NATIVE_REQUIRED_RULE_DELIVERY_UNKNOWN_OR_DRIFT")
    for final in receipt.get("final_reads", []):
        _require(any(
            call["request"].get("admission_id") == final.get("admission_id")
            and call["result"].get("judgment_required") is False
            and all(call["result"].get(key) == final.get(key) for key in ("refs", "context"))
            for call in context_calls
        ), "NATIVE_FINAL_CONTEXT_DELIVERY_UNOBSERVED")
    if invocation["mode"] == "required_only":
        _require(not receipt.get("final_reads") and not receipt.get("captures"), "OFF_OPTIONAL_EXPOSURE")
    if invocation["phase"] != "preflight":
        for call in context_calls:
            _validate_context_call(manifest, call)
    return native


def _gateway_receipt(manifest: EvaluationManifest, run_dir: Path, invocation: dict) -> tuple[dict, dict]:
    receipt = _existing(run_dir / "ledger", _key(invocation["invocation_id"]) + ".gateway.json", manifest.config["record_bytes"])
    _require(receipt is not None, "GATEWAY_DELIVERY_UNOBSERVED")
    deliveries = _validate_delivery_receipt(
        manifest, invocation, receipt,
        _trace_events(manifest, run_dir, invocation["invocation_id"], "gateway"),
    )
    return receipt, deliveries


def _functional_observation(receipt, task: OracleTask) -> bool | None:
    _require(receipt.error_code is None and receipt.state in {"passed", "rejected"}
             and receipt.publication.state in {"durable", "reconciled_durable"}
             and receipt.structural is not None and receipt.cleanup_complete,
             "EXTERNAL_VERIFIER_INCOMPLETE")
    if not receipt.structural.passed:
        _require(all(case.observation is None for case in receipt.cases),
                 "EXTERNAL_VERIFIER_SCOPE_INCONSISTENT")
        return None
    _require(tuple(case.case_id for case in receipt.cases) == tuple(case.case_id for case in task.cases),
             "EXTERNAL_VERIFIER_CASE_SCOPE_INCOMPLETE")
    _require(all(case.observation is not None and case.observation.execution is not None
                 and case.observation.state == "completed"
                 and case.observation.execution.state == "completed"
                 and case.observation.execution.stdout_complete
                 and case.observation.execution.stderr_complete
                 and case.observation.execution.helper_cleanup
                 for case in receipt.cases), "EXTERNAL_VERIFIER_INCOMPLETE")
    passed = all(case.passed for case in receipt.cases)
    _require(receipt.success == passed, "EXTERNAL_VERIFIER_SCOPE_INCONSISTENT")
    return passed


def _run_one(
    manifest: EvaluationManifest, run_dir: Path, invocation: dict, *, enabled: bool,
    stop_event=None, pair_controls: _PairControls | None = None,
) -> dict:
    prior = _read_terminal(manifest, run_dir, invocation)
    if prior is not None:
        if prior.get("cleanup_complete") is not True:
            _reconcile(manifest, run_dir, invocation)
        return prior
    if not _intent(manifest, run_dir, invocation):
        unknown = _initial_result()
        unknown.update(status="unknown", code="CRASH_INTENT_NO_REPLAY", comparability_reasons=["CRASH_INTENT_NO_REPLAY"])
        try:
            _reconcile(manifest, run_dir, invocation)
        except Exception:
            unknown["comparability_reasons"].append("OWNED_RECOVERY_UNRESOLVED")
        _terminal(manifest, run_dir, invocation, unknown)
        return unknown
    result = _initial_result()
    native = None
    before = False
    started_ns = time.monotonic_ns()
    try:
        _require(enabled, "PREFLIGHT_NOT_ESTABLISHED")
        _require(stop_event is None or not stop_event.is_set(), "STOP_REQUESTED")
        _running_sources(manifest)
        for frozen in manifest.files:
            _require(digest_bytes(_read(frozen.path, frozen.maximum_bytes)) == frozen.sha256, "FROZEN_INPUT_DRIFT")
        config, phase = manifest.config, invocation["phase"]
        spec = _native(invocation["native"])
        _require(spec.approved_context, "NATIVE_CONTEXT_NOT_APPROVED")
        if spec.strict_protection_required and not spec.strict_protection_supported:
            result["status"] = "unsupported"
            raise EvaluationError("STRICT_NATIVE_CAPABILITY_UNSUPPORTED")
        _require(digest_bytes(_read(spec.executable, _FILE_BYTES)) == manifest.document("native_identity")["executable_sha256"], "NATIVE_EXECUTABLE_IDENTITY_DRIFT")
        if config["scope"] == "evaluation":
            _owner(manifest, invocation["invocation_id"], os.urandom(16).hex()).require_actions()
        if phase != "preflight":
            fence = _fence(manifest, run_dir, invocation, "fence_before")
            result.update(corpus_before_digest=fence["corpus_digest"], required_rules_digest=fence["required_rules_digest"])
            before = True
        task = _task(manifest, invocation["target_id"]) if phase == "coding" else None
        verifier, oracle = None, None
        if task is not None:
            _require(pair_controls is not None, "PAIR_CONTROL_PRECHECK_UNAVAILABLE")
            baseline, oracle, verifier = pair_controls.baseline, pair_controls.oracle, pair_controls.verifier
            _require(oracle.digest == task["approved_task_digest"],
                     "PAIR_CONTROL_TASK_IDENTITY")
            result["control_receipt_digest"] = _publish(
                run_dir / "ledger", _key(invocation["invocation_id"]) + ".controls.json",
                pair_controls.receipt, config["record_bytes"])
            _require(stop_event is None or not stop_event.is_set(), "STOP_REQUESTED")
            prompt = manifest.file(task["prompt_file"]).raw.decode("utf-8")
        elif phase == "preflight":
            preflight = manifest.workload["preflight"]
            baseline = _bundle(manifest, preflight["baseline_file"])
            gateway = EvaluationGateway(_scope(manifest, invocation), agent=_upstream(manifest, "agent", invocation), producer=_upstream(manifest, "producer", invocation), trace_sink=PrivateTrace(manifest, run_dir, invocation["invocation_id"], "producer"))
            try:
                capture = gateway.capture(preflight["capture"])
                _publish(run_dir / "ledger", _key(invocation["invocation_id"]) + ".capture.json", capture, config["record_bytes"])
                prompt = manifest.file(preflight["prompt_file"]).raw.decode("utf-8") + "\n" + gateway.preflight_prompt(capture["source_pointer"], preflight["recall_request"])
            finally:
                gateway.close()
        else:
            case = next(item for item in manifest.workload["retrieval"] if item["case_id"] == invocation["target_id"])
            baseline = _bundle(manifest, manifest.workload["preflight"]["baseline_file"])
            prompt = manifest.file(case["prompt_file"]).raw.decode("utf-8") + "\n" + canonical_bytes({"recall_request": case["request"]}).decode()
        _require(not spec.cwd.exists(), "FRESH_APPROVED_WORKSPACE_NOT_EMPTY")
        materialize_snapshot(baseline, spec.cwd)
        prompt += "\n" + canonical_bytes({"invocation_id": invocation["invocation_id"], "route_ref": spec.gateway_route_ref, "mode": invocation["mode"], "required_request": _gateway_config(manifest, invocation)["required_request"], "submission_path": str(spec.submission_path), "submission_format": "ArtifactBundle.to_bytes schema 1; all paths and unchanged bytes/modes required", "witness_path": str(spec.cwd / task["witness_name"]) if task else None, "witness_format": "baseline_digest,final_digest,edits[{path,start,end,replacement:canonical_base64}],creates[{path,kind,mode,content:canonical_base64,sha256}],deletes,modes[{path,before,after}]"}).decode()
        output = run_dir / "artifacts" / (invocation["invocation_id"] + ".submission.json")
        native = run_native_arm(spec, prompt, invocation_id=invocation["invocation_id"], artifact_output=output, trace_sink=PrivateTrace(manifest, run_dir, invocation["invocation_id"], "native"), stop_event=stop_event)
        result.update(status=native.status, code=native.code)
        native_record = _private_value(native)
        result["evidence_refs"]["native"] = _publish(run_dir / "ledger", _key(invocation["invocation_id"]) + ".native.json", native_record, config["trace_bytes"])
        _usage(result, native)
        identity_matches = _native_identity(manifest, native_record, invocation["mode"])
        result["native_identity_observed"] = identity_matches
        result["native_identity_digest"] = manifest.file("native_identity").sha256 if identity_matches else None
        reasons = list(native.incomparability_reasons)
        if not identity_matches:
            reasons.append("FROZEN_NATIVE_IDENTITY_MISMATCH_OR_UNKNOWN")
        result["comparability_reasons"] = reasons
        for measurement, limit in config["usage_budgets"].items():
            if limit is not None:
                if result[measurement] is None:
                    reasons.append("USAGE_BUDGET_UNOBSERVED")
                elif result[measurement] > limit:
                    reasons.append("USAGE_BUDGET_EXCEEDED")
        result["comparability_reasons"] = sorted(set(reasons))
        generation = native.identity.get("thread_id") or native.identity.get("session_id")
        if generation is not None:
            result["evidence_refs"]["generation"] = _claim_generation(manifest, run_dir, invocation["invocation_id"], generation)
        elif native.status == "completed":
            raise EvaluationError("NATIVE_GENERATION_UNOBSERVED")
        _require(native.status == "completed", "NATIVE_NOT_COMPLETED")
        delivery, deliveries = _gateway_receipt(manifest, run_dir, invocation)
        native_link = _native_tool_link(manifest, invocation, native_record, delivery, deliveries)
        result["evidence_refs"]["native_tool_link"] = _publish(
            run_dir / "ledger", _key(invocation["invocation_id"]) + ".native-tool-link.json", native_link, config["record_bytes"],
        )
        result["evidence_refs"]["gateway"] = digest_bytes(canonical_bytes(delivery))
        _require(native.artifact_bundle is not None, "IMMUTABLE_SUBMISSION_MISSING")
        _require(native.artifact_bundle["sha256"] == digest_bytes(_read(output, config["artifact_limits"]["bundle_bytes"], private=True)), "SUBMISSION_REFERENCE_MISMATCH")
        final = load_submission(output, limits=_dc(ArtifactLimits, config["artifact_limits"]))
        result["artifact_digest"] = final.digest
        if task is not None:
            raw = _read(spec.cwd / task["witness_name"], config["record_bytes"])
            _publish(run_dir / "artifacts", invocation["invocation_id"] + ".witness.json", raw, config["record_bytes"])
            witness = _witness(decode_json(raw), final.limits)
            verified = verifier.verify(baseline, final, replace(oracle, witness=witness),
                                       stop_event=stop_event, invocation_id=invocation["invocation_id"])
            result["verifier_receipt_digest"] = _publish(run_dir / "ledger", _key(invocation["invocation_id"]) + ".verifier.json", _private_value(verified), config["record_bytes"])
            result.update(structural_pass=verified.structural.passed if verified.structural else None,
                          cleanup_complete=verified.cleanup_complete)
            result["functional_success"] = _functional_observation(verified, oracle)
        elif phase == "preflight":
            _require(_preflight_link(manifest, run_dir, invocation, delivery), "PRODUCER_NATIVE_MCP_PIPELINE_INCOMPLETE")
        result["comparable"] = native.comparable and identity_matches and not reasons
    except Exception as error:
        code = str(error) if isinstance(error, EvaluationError) and re.fullmatch(r"[A-Z0-9_]{1,128}", str(error)) else "CONTROLLER_STAGE_FAILED"
        if native is None:
            status = "aborted" if stop_event is not None and stop_event.is_set() else ("unsupported" if result["status"] == "unsupported" else "blocked")
            result.update(status=status, code=code)
        elif native.status == "completed":
            result.update(status="incomplete", code=code)
        result["comparable"] = False
        result["comparability_reasons"] = sorted(set(result["comparability_reasons"] + [code]))
    except BaseException:
        result.update(status="aborted", code="CONTROLLER_INTERRUPTED", comparable=False)
        result["comparability_reasons"] = sorted(set(result["comparability_reasons"] + ["CONTROLLER_INTERRUPTED"]))
        if stop_event is not None:
            stop_event.set()
    finally:
        if before:
            try:
                after = _fence(manifest, run_dir, invocation, "fence_after")
                result["corpus_after_digest"] = after["corpus_digest"]
                _require(after["required_rules_digest"] == result["required_rules_digest"], "REQUIRED_RULE_IDENTITY_DRIFT")
            except Exception:
                result["comparable"] = False
                result["contaminated"] = True
                result["comparability_reasons"] = sorted(set(result["comparability_reasons"] + ["CORPUS_OR_RULE_AFTER_FENCE_UNAVAILABLE_OR_DRIFT"]))
        result["latency_seconds"] = (time.monotonic_ns() - started_ns) / 1_000_000_000
        _terminal(manifest, run_dir, invocation, result)
    return result


def _trace_events(manifest: EvaluationManifest, run_dir: Path, invocation_id: str, channel: str) -> list[dict]:
    directory = run_dir / "traces" / invocation_id / channel
    fd = open_private_directory(directory)
    try:
        names = _bounded_names(fd, manifest.config["trace_events"] + 2)
        _require("overflow.json" not in names, "TRACE_INCOMPLETE_OR_BOUND")
    finally:
        os.close(fd)
    event_names = sorted(name for name in names if re.fullmatch(r"[0-9]{8}\.json", name))
    _require(set(names) == set(event_names) | {"claim.json"}, "TRACE_UNEXPECTED_RECORD")
    previous, total, result = manifest.digest, 0, []
    for sequence, name in enumerate(event_names):
        _require(name == f"{sequence:08d}.json", "TRACE_SEQUENCE_GAP")
        raw = _read(directory / name, manifest.config["record_bytes"], private=True)
        total += len(raw)
        _require(total <= manifest.config["trace_bytes"], "TRACE_TOTAL_BOUND")
        value = decode_json(raw)
        _require(value["sequence"] == sequence and value["previous_digest"] == previous, "TRACE_HASH_CHAIN")
        previous = digest_bytes(raw)
        result.append(value["event"])
    return result


def _unbytes(value: dict) -> bytes:
    _keys(value, {"$bytes", "size", "sha256"})
    raw = _binary(value["$bytes"], _TOTAL_BYTES)
    _require(len(raw) == value["size"] and digest_bytes(raw) == value["sha256"], "TRACE_BYTES_IDENTITY")
    return raw


def _preflight_link(manifest: EvaluationManifest, run_dir: Path, invocation: dict, delivery: dict) -> bool:
    capture = _existing(run_dir / "ledger", _key(invocation["invocation_id"]) + ".capture.json", manifest.config["record_bytes"])
    return _preflight_link_data(
        manifest, capture, _trace_events(manifest, run_dir, invocation["invocation_id"], "gateway"), delivery)


def _preflight_link_data(manifest: EvaluationManifest, capture: dict, events: list[dict], delivery: dict) -> bool:
    pointer = capture["source_pointer"]
    source = pointer["source_id"]
    recorded, inspected, windows = set(), {}, {}
    coverage = []
    delivered_calls = {call_id for call_id, value in _native_deliveries(events).items()
                       if not value["event"]["is_error"]}
    for event in events:
        if event.get("stage") != "gateway_wire":
            continue
        exchange = event.get("exchange", {})
        if (exchange.get("stage") != "response" or exchange.get("response_complete") is not True
                or exchange.get("response_body") is None or exchange.get("request_body") is None):
            continue
        request_bytes = _unbytes(exchange["request_body"])
        response_bytes = _unbytes(exchange["response_body"])
        if not request_bytes or not response_bytes:
            continue
        request = decode_json(request_bytes)
        params = request.get("params", {})
        arguments = params.get("arguments", {})
        if request.get("method") != "tools/call" or params.get("name") not in {"memory_inspect", "memory_record"}:
            continue
        if event.get("call_id") not in delivered_calls:
            continue
        response = decode_json(response_bytes)
        if "result" not in response or response["result"].get("isError"):
            continue
        payload = _payload(response["result"])
        if params["name"] == "memory_record":
            extraction = arguments.get("extraction", {})
            if (arguments.get("kind") == "source_selection" and arguments.get("source_id") == source
                    and arguments.get("source_revision") == pointer["source_revision"]
                    and arguments.get("binding_revision") == pointer["binding_revision"]
                    and arguments.get("label") == "remember" and payload.get("state") == "candidate_ready"
                    and all(isinstance(extraction.get(key), list) for key in ("claims", "individual_qualifications", "shared_qualifications", "validities", "unused_span_ids"))):
                recorded.add(payload["artifact_id"])
            continue
        ref = arguments.get("ref")
        if ref == source:
            if payload.get("source_revision") != pointer["source_revision"] or payload.get("binding_revision") != pointer["binding_revision"] or payload.get("total_bytes") != pointer["byte_length"]:
                return False
            coverage.append((payload["byte_start"], payload["byte_end"]))
        window = payload.get("draft_window")
        if isinstance(window, dict):
            digest, total = window["digest"], window["total_bytes"]
            start, end = window["byte_start"], window["byte_end"]
            previous_digest, previous_total, collected = windows.get(ref, (digest, total, bytearray()))
            if start == 0:
                collected = bytearray()
            if digest != previous_digest or total != previous_total or start != len(collected) or total > manifest.config["record_bytes"]:
                return False
            collected.extend(window["body"].encode())
            if end != len(collected) or len(collected) > total:
                return False
            windows[ref] = (digest, total, collected)
            if window.get("next_byte") is not None:
                continue
            if end != total or digest_bytes(collected) != digest:
                return False
            payload = decode_json(bytes(collected))
        inspected[ref] = payload
    covered = 0
    for start, end in sorted(coverage):
        if start > covered:
            return False
        covered = max(covered, end)
    if covered != pointer["byte_length"]:
        return False
    delivered = {ref for read in delivery.get("final_reads", []) for ref in (read.get("refs") or [])}
    remembered = set()
    for selection in recorded:
        payload = inspected.get(selection, {})
        claims = set(payload.get("claim_ids", []))
        if (not claims or not claims <= inspected.keys() or payload.get("source_id") != source
                or payload.get("source_revision") != pointer["source_revision"]
                or payload.get("binding_revision") != pointer["binding_revision"]):
            return False
        for identifier in claims:
            claim = inspected[identifier]
            if source not in claim.get("input_source_ids", []) or not any(
                    span.get("source_id") == source and span.get("source_revision") == pointer["source_revision"]
                    for span in claim.get("evidence", [])):
                return False
        remembered.update(claims)
    return bool(remembered) and bool(remembered & delivered)


def _select(manifest: EvaluationManifest, phase: str, target: str, mode: str, repeat=None, attempt=None) -> dict:
    return next(item for item in manifest.workload["invocations"] if (item["phase"], item["target_id"], item["mode"], item["repeat_index"], item["pair_attempt"]) == (phase, target, mode, repeat, attempt))


def _run_pair(manifest: EvaluationManifest, run_dir: Path, item, enabled: bool, stop_event) -> None:
    task_id, repeat, modes = item
    config = manifest.config
    for attempt in range(config["max_pair_retries"] + 1):
        invocations = [_select(manifest, "coding", task_id, mode, repeat, attempt) for mode in modes]
        controls = None
        if enabled and not (stop_event is not None and stop_event.is_set()):
            try:
                controls = _prepare_pair_controls(manifest, run_dir, invocations, stop_event=stop_event)
            except Exception as error:
                code = str(error) if isinstance(error, EvaluationError) and re.fullmatch(
                    r"[A-Z0-9_]{1,128}", str(error)) else "PAIR_CONTROL_PREPARATION_FAILED"
                _publish(run_dir / "ledger", _pair_verifier_id(manifest, invocations[0]) + ".failed.json",
                         {"stage": "pair_controls", "code": code, "type": type(error).__name__},
                         manifest.config["record_bytes"])
        results = [_run_one(manifest, run_dir, invocation, enabled=enabled, stop_event=stop_event,
                            pair_controls=controls) for invocation in invocations]
        if not any(result["status"] in config["retry_statuses"] for result in results) or (stop_event is not None and stop_event.is_set()):
            break


def run_evaluation(manifest: EvaluationManifest, run_dir: Path, *, stop_event=None) -> dict:
    import fcntl
    if stop_event is None:
        stop_event = threading.Event()
    state = prepare_run(manifest, run_dir)
    directory = open_private_directory(run_dir)
    try:
        lock = os.open("controller.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=directory)
    finally:
        os.close(directory)
    try:
        info = os.fstat(lock)
        _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1 and not info.st_mode & 0o077, "CONTROLLER_LOCK_IDENTITY")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise EvaluationError("RUN_CONTROLLER_BUSY") from None
        return _execute_run(manifest, state, stop_event)
    finally:
        os.close(lock)


def _execute_run(manifest: EvaluationManifest, state: RunState, stop_event) -> dict:
    run_dir = state.run_dir
    invocation = _invocation(manifest, manifest.workload["preflight"]["invocation_id"])
    preflight = _run_one(manifest, run_dir, invocation, enabled=True, stop_event=stop_event)
    enabled = preflight["status"] == "completed" and preflight["comparable"]
    for case in sorted(manifest.workload["retrieval"], key=lambda item: digest_bytes(canonical_bytes([manifest.config["seed"], item["case_id"]]))):
        for mode in _MODES:
            _run_one(manifest, run_dir, _select(manifest, "retrieval", case["case_id"], mode), enabled=enabled, stop_event=stop_event)
    with ThreadPoolExecutor(max_workers=manifest.config["concurrency"]) as pool:
        futures = [pool.submit(_run_pair, manifest, run_dir, item, enabled, stop_event) for item in state.schedule]
        try:
            for future in futures:
                future.result()
        except KeyboardInterrupt:
            stop_event.set()
            for future in futures:
                future.result()
    return report_evaluation(run_dir)


def _protocol(manifest: EvaluationManifest) -> ScoringProtocol:
    config = manifest.config
    return ScoringProtocol(schema=1, scope=config["scope"], manifest_digest=manifest.digest, source_commit=config["source_commit"], controller_digest=config["controller_digest"], verifier_digest=config["verifier_digest"], corpus_digest=manifest.file("corpus").sha256, gold_digest=manifest.file("gold").sha256, workload_digest=manifest.file("workload").sha256, required_rules_digest=manifest.file("rules").sha256, native_identity_digest=manifest.file("native_identity").sha256, seed=config["seed"], resamples=10000, confidence=0.95, coding_tasks=[{key: task[key] for key in ("task_id", "task_revision", "cluster_id")} for task in manifest.workload["tasks"]], retrieval_cases=[{key: case[key] for key in ("case_id", "cluster_id", "relevant_claim_ids", "irrelevant_claim_ids", "judgment_complete", "grounding_refs")} for case in manifest.document("gold")["cases"]])


def _load_frozen_run(run_dir: Path) -> EvaluationManifest:
    raw = _read(run_dir / "manifest.json", _MANIFEST_BYTES, private=True)
    config = decode_json(raw)
    files = []
    for item in config["files"]:
        data = _read(run_dir / "inputs" / (item["name"] + ".frozen"), item["maximum_bytes"], private=True)
        _require(digest_bytes(data) == item["sha256"], "RUN_INPUT_IDENTITY_DRIFT")
        files.append(FrozenFile(item["name"], run_dir / "inputs" / (item["name"] + ".frozen"), item["sha256"], item["maximum_bytes"], data))
    manifest = EvaluationManifest(run_dir / "manifest.json", digest_bytes(raw), raw, tuple(files))
    identity = _existing(run_dir, "run.json", config["record_bytes"])
    _require(identity is not None and identity["manifest_digest"] == manifest.digest and identity["owner"] == config["owner"], "RUN_IDENTITY_DRIFT")
    return manifest


def _grounding(context: dict) -> list[dict]:
    refs = []
    seen = set()
    for claim in context.get("memory_candidates", []):
        for span in claim.get("evidence", []):
            ref = {"source_id": span["source"], "revision": span["revision"], "byte_start": span["bytes"][0], "byte_end": span["bytes"][1], "quote_digest": digest_bytes(span["quote"].encode())}
            identity = canonical_bytes(ref)
            if identity not in seen:
                refs.append(ref)
                seen.add(identity)
    return refs


def _normalized_retrieval_request(manifest: EvaluationManifest, request: dict) -> dict:
    _require(request.get("binding_id") is None or request.get("binding_id") == manifest.config["gateway"]["binding_id"],
             "RETRIEVAL_REQUEST_BINDING_MISMATCH")
    return validate_wire(ContextCommand, {
        **request, "binding_id": manifest.config["gateway"]["binding_id"],
    }).model_dump(mode="json", exclude={"admission_id", "relevance"})


def _resolved_retrieval_context(manifest: EvaluationManifest, invocation: dict, delivery: dict) -> tuple[object, bool]:
    reads = delivery.get("final_reads") or []
    final = reads[0] if len(reads) == 1 else None
    context = final.get("context") if final else None
    matched = False
    if invocation["mode"] == "required_only":
        required = delivery.get("required_reads") or []
        if len(required) == 1:
            call = required[0]
            context = call["result"].get("context")
            matched = (_normalized_retrieval_request(manifest, call["request"])
                       == _normalized_retrieval_request(manifest, manifest.config["gateway"]["required_request"]))
    else:
        case = next(item for item in manifest.workload["retrieval"] if item["case_id"] == invocation["target_id"])
        expected = _normalized_retrieval_request(manifest, case["request"])
        calls = [call for call in delivery.get("context_calls", [])
                 if call["result"].get("judgment_required") is False
                 and (call["request"].get("admission_id") or call["result"].get("candidate_manifest") == [])]
        if len(calls) == 1:
            call = calls[0]
            confirmed = (final is not None and call["result"].get("context") == final.get("context")
                         if call["request"].get("admission_id")
                         else call["result"].get("candidate_manifest") == [])
            matched = _normalized_retrieval_request(manifest, call["request"]) == expected and confirmed
            context = call["result"].get("context")
    if isinstance(context, str) and context != "":
        context = decode_json(context.encode())
    known_context = context == "" or isinstance(context, dict) and isinstance(context.get("memory_candidates"), list)
    return context, known_context and delivery.get("observation_complete") is True and matched


def _bound_gateway_record(invocation: dict, terminal: dict | None, records: dict) -> dict:
    if terminal is None or terminal["evidence_refs"].get("gateway") is None:
        return {}
    receipt = records.get("ledger/" + _key(invocation["invocation_id"]) + ".gateway.json")
    _require(isinstance(receipt, dict)
             and digest_bytes(canonical_bytes(receipt)) == terminal["evidence_refs"]["gateway"],
             "GATEWAY_RECEIPT_IDENTITY_DRIFT")
    return receipt


def _report_ledger(manifest: EvaluationManifest, run_dir: Path) -> dict:
    records = {}
    for invocation in manifest.workload["invocations"]:
        prefix = _key(invocation["invocation_id"])
        for suffix in ("intent", "terminal", "gateway"):
            name = prefix + "." + suffix + ".json"
            value = _existing(run_dir / "ledger", name, manifest.config["record_bytes"])
            if value is not None:
                records["ledger/" + name] = value
    return records


def load_report_inputs(run_dir: Path) -> tuple[ScoringProtocol, list[ArmObservation], list[RetrievalObservation]]:
    manifest = _load_frozen_run(run_dir)
    return _report_inputs_from_records(manifest, _report_ledger(manifest, run_dir))


def _report_inputs_from_records(manifest: EvaluationManifest, records: dict) -> tuple:
    protocol, arms, retrieval = _protocol(manifest), [], []
    nullable = {key: value for key, value in _initial_result().items() if key not in {"code", "status", "comparable", "comparability_reasons", "contaminated", "native_identity_observed"}}
    for invocation in manifest.workload["invocations"]:
        prefix = "ledger/" + _key(invocation["invocation_id"])
        terminal = _checked_terminal(manifest, invocation, records.get(prefix + ".terminal.json"))
        intent = records.get(prefix + ".intent.json")
        if intent is not None:
            _require(intent == {"schema": 1, "manifest_digest": manifest.digest, "invocation": invocation}, "ATTEMPT_INTENT_CONFLICT")
        _require(terminal is None or intent is not None, "TERMINAL_WITHOUT_PRIOR_INTENT")
        delivery = _bound_gateway_record(invocation, terminal, records)
        if invocation["phase"] == "preflight" or (intent is None and invocation["phase"] == "coding" and invocation["pair_attempt"] > 0):
            continue
        row = terminal or {**_initial_result(), "status": "unknown" if intent else "not_started", "comparability_reasons": ["CRASH_INTENT_NO_TERMINAL" if intent else "NOT_STARTED"]}
        if terminal is not None:
            _require(terminal["manifest_digest"] == manifest.digest and terminal["invocation_id"] == invocation["invocation_id"], "TERMINAL_IDENTITY_DRIFT")
        common = {"schema": 1, "manifest_digest": manifest.digest, "mode": invocation["mode"], "status": row["status"], "comparable": row["comparable"], "comparability_reasons": row["comparability_reasons"], "contaminated": row["contaminated"]}
        if invocation["phase"] == "coding":
            task = _task(manifest, invocation["target_id"])
            arms.append(ArmObservation(**common, pair_id=_pair_id(manifest, task["task_id"], invocation["repeat_index"]), pair_attempt=invocation["pair_attempt"], task_id=task["task_id"], task_revision=task["task_revision"], cluster_id=task["cluster_id"], repeat_index=invocation["repeat_index"], invocation_id=invocation["invocation_id"], native_identity_observed=row["native_identity_observed"], **{key: row.get(key) for key in nullable}))
        else:
            case = next(item for item in manifest.document("gold")["cases"] if item["case_id"] == invocation["target_id"])
            context, complete = _resolved_retrieval_context(manifest, invocation, delivery)
            ids = ([] if context == "" else [claim["ref"] for claim in context["memory_candidates"]]) if complete else None
            comparable = common["comparable"] and complete
            reasons = list(common["comparability_reasons"])
            if not complete:
                reasons.append("FINAL_CONTEXT_UNOBSERVED_OR_AMBIGUOUS")
            common.update(comparable=comparable, comparability_reasons=sorted(set(reasons)))
            retrieval.append(RetrievalObservation(**common, case_id=case["case_id"], cluster_id=case["cluster_id"],
                attempt_id=invocation["invocation_id"], returned_claim_ids=ids,
                manifest_complete=True if complete else None,
                final_context_digest=digest_bytes(canonical_bytes(context)) if complete else None,
                grounding_refs=([] if context == "" else _grounding(context)) if complete else None,
                **{key: row.get(key) for key in ("latency_seconds", "input_tokens", "output_tokens",
                                               "total_tokens", "cost_usd", "cost_basis")}))
    return protocol, arms, retrieval


def _diagnostic_observations_from_records(
    manifest: EvaluationManifest, protocol: ScoringProtocol,
    retrieval: list[RetrievalObservation], records: dict,
) -> list:
    from .evaluation_scoring import DeliveredClaimObservation, RetrievalDiagnosticObservation

    observations = []
    corpus_ids = {claim["ref"] for claim in manifest.document("corpus")["claims"]}
    for row in retrieval:
        invocation = _invocation(manifest, row.attempt_id)
        prefix = "ledger/" + _key(row.attempt_id)
        terminal = _checked_terminal(manifest, invocation, records.get(prefix + ".terminal.json")) or _initial_result()
        delivery = _bound_gateway_record(invocation, terminal, records)
        scope = diagnostics_module.diagnostic_scope(manifest, protocol, row.case_id)
        context, complete = _resolved_retrieval_context(manifest, invocation, delivery)
        final_claims = None
        if complete:
            final_claims = tuple(DeliveredClaimObservation(
                claim_id=item["ref"], claim_digest=digest_bytes(canonical_bytes(item)), complete=True,
            ) for item in (context["memory_candidates"] if isinstance(context, dict) else ()))
        candidate = {}
        if invocation["mode"] == "memory_on":
            case = next(item for item in manifest.workload["retrieval"] if item["case_id"] == row.case_id)
            initial = [call for call in delivery.get("context_calls", [])
                       if not call["request"].get("admission_id")]
            reasons = []
            matching = (len(initial) == 1
                        and _normalized_retrieval_request(manifest, initial[0]["request"])
                        == _normalized_retrieval_request(manifest, case["request"]))
            items = initial[0]["result"].get("candidate_manifest") if matching else None
            ids = [item.get("claim_id") for item in items] if isinstance(items, list) else None
            stage_complete = (ids is not None and len(ids) <= 20 and len(set(ids)) == len(ids)
                              and all(isinstance(ref, str) and ref in corpus_ids for ref in ids)
                              and delivery.get("invocation_id") == row.attempt_id
                              and delivery.get("mode") == row.mode
                              and delivery.get("observation_complete") is True)
            if not stage_complete:
                reasons.append("CANDIDATE_STAGE_UNOBSERVED_OR_AMBIGUOUS")
            if (terminal.get("corpus_before_digest") != protocol.corpus_digest
                    or terminal.get("corpus_after_digest") != protocol.corpus_digest
                    or terminal.get("required_rules_digest") != protocol.required_rules_digest
                    or terminal.get("native_identity_digest") != protocol.native_identity_digest
                    or terminal.get("native_identity_observed") is not True
                    or terminal.get("contaminated") is not False):
                reasons.append("CANDIDATE_SCOPE_OR_NATIVE_IDENTITY_UNKNOWN")
            candidate = dict(
                candidate_status="completed" if stage_complete else "unknown",
                candidate_comparable=stage_complete and not reasons,
                candidate_comparability_reasons=reasons,
                candidate_claim_ids=ids if stage_complete else None,
                candidate_manifest_digest=digest_bytes(canonical_bytes(items)) if stage_complete else None,
                candidates_complete=stage_complete,
            )
        observations.append(RetrievalDiagnosticObservation(schema=1, scope=scope, retrieval=row, final_claims=final_claims, **candidate))
    return observations


def report_evaluation(run_dir: Path, *, adjudication: bytes | None = None) -> dict:
    manifest = _load_frozen_run(run_dir)
    _running_sources(manifest)
    return _report_from_records(manifest, _report_ledger(manifest, run_dir), adjudication=adjudication)


def _report_from_records(manifest: EvaluationManifest, records: dict, *, adjudication: bytes | None = None) -> dict:
    protocol, attempts, retrieval = _report_inputs_from_records(manifest, records)
    from .evaluation_scoring import score_run

    report = score_run(protocol, attempts, retrieval)
    supplements = diagnostics_module.load_diagnostic_gold(manifest, protocol, adjudication=adjudication)
    report["retrieval_diagnostics"] = scoring_module.score_retrieval_diagnostics(
        protocol, supplements.gold, _diagnostic_observations_from_records(manifest, protocol, retrieval, records))
    report["retrieval_diagnostics"]["evidence_provenance"] = supplements.provenance()
    invocation = _invocation(manifest, manifest.workload["preflight"]["invocation_id"])
    prefix = "ledger/" + _key(invocation["invocation_id"])
    intent = records.get(prefix + ".intent.json")
    _require(intent is None or intent == {"schema": 1, "manifest_digest": manifest.digest,
                                         "invocation": invocation}, "ATTEMPT_INTENT_CONFLICT")
    preflight = _checked_terminal(manifest, invocation, records.get(prefix + ".terminal.json"))
    _require(preflight is None or intent is not None, "TERMINAL_WITHOUT_PRIOR_INTENT")
    if preflight is not None:
        _require(preflight["manifest_digest"] == manifest.digest
                 and preflight["invocation_id"] == invocation["invocation_id"], "TERMINAL_IDENTITY_DRIFT")
    else:
        preflight = {**_initial_result(), "status": "unknown" if intent else "not_started",
                     "code": "CRASH_INTENT_NO_TERMINAL" if intent else "NOT_STARTED",
                     "comparability_reasons": ["CRASH_INTENT_NO_TERMINAL" if intent else "NOT_STARTED"]}
    report["controller"] = {
        "scope": manifest.config["scope"], "independence": "provided_unattested", "original18_completed": 0,
        "preflight": {key: preflight[key] for key in (
            "status", "code", "comparable", "comparability_reasons", "latency_seconds",
            "input_tokens", "output_tokens", "total_tokens", "cost_usd", "cost_basis", "evidence_refs")},
    }
    return report



@dataclass(frozen=True)
class _PairControls:
    verifier: VerifierExecutor
    baseline: ArtifactBundle
    oracle: OracleTask
    receipt: bytes


def _pair_verifier_id(manifest: EvaluationManifest, invocation: dict) -> str:
    return "pair-" + digest_bytes(canonical_bytes([
        manifest.digest, invocation["target_id"], invocation["repeat_index"], invocation["pair_attempt"],
    ]))


def _prepare_pair_controls(
    manifest: EvaluationManifest, run_dir: Path, invocations: list[dict], *, stop_event=None,
) -> _PairControls | None:
    from .private_io import private_write

    config = manifest.config
    _running_sources(manifest)
    for frozen in manifest.files:
        _require(digest_bytes(_read(frozen.path, frozen.maximum_bytes)) == frozen.sha256, "FROZEN_INPUT_DRIFT")
    for invocation in invocations:
        spec = _native(invocation["native"])
        _require(spec.approved_context, "NATIVE_CONTEXT_NOT_APPROVED")
        _require(not spec.strict_protection_required or spec.strict_protection_supported,
                 "STRICT_NATIVE_CAPABILITY_UNSUPPORTED")
        _require(digest_bytes(_read(spec.executable, _FILE_BYTES)) ==
                 manifest.document("native_identity")["executable_sha256"], "NATIVE_EXECUTABLE_IDENTITY_DRIFT")
    identifier = _pair_verifier_id(manifest, invocations[0])
    _require(all(_pair_verifier_id(manifest, invocation) == identifier for invocation in invocations),
             "PAIR_CONTROL_TASK_IDENTITY")
    task = _task(manifest, invocations[0]["target_id"])
    baseline, oracle, controls = _task_inputs(manifest, task)
    owner = _owner(manifest, identifier, os.urandom(16).hex())
    if config["scope"] == "evaluation":
        owner.require_actions()
    intent = {"schema": 1, "manifest_digest": manifest.digest, "pair_verifier_id": identifier,
              "invocation_ids": [invocation["invocation_id"] for invocation in invocations],
              "task_digest": oracle.digest, "controls_digest": controls_digest(controls),
              "owner": _private_value(owner)}
    directory = open_private_directory(run_dir / "ledger")
    try:
        try:
            private_write(Path(identifier + ".intent.json"), canonical_bytes(intent), directory=directory)
        except FileExistsError:
            prior = _existing(run_dir / "ledger", identifier + ".intent.json", config["record_bytes"])
            _require(prior is not None and all(prior[key] == intent[key] for key in intent if key != "owner"),
                     "PAIR_CONTROL_INTENT_CONFLICT")
            _reconcile(manifest, run_dir, invocations[0])
            return None
    finally:
        os.close(directory)
    verifier_directory = run_dir / "verifiers" / identifier
    _mkdir(verifier_directory)
    verifier = VerifierExecutor(_verifier_spec(manifest), owner, verifier_directory)
    approval = IndependentControlApproval(task["approved_task_digest"], task["approved_controls_digest"],
                                         task["approval_reference"])
    control = verifier.precheck(baseline, oracle, controls, approval, stop_event=stop_event)
    raw = canonical_bytes(_private_value(control))
    _publish(run_dir / "ledger", identifier + ".controls.json", raw, config["record_bytes"])
    _require(control.eligible, "SAME_EXECUTOR_CONTROL_PRECHECK_FAILED")
    return _PairControls(verifier, baseline, oracle, raw)
