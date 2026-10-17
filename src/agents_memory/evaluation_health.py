"""Read-only linkage of retained engineering measurements to explicit health judgments.

This is not an admission issuer, a semantic scorer, or an authenticity attestation.
The caller supplies live complete health inspections and submits the resulting command
through the existing server admission fence. No files are published by this module.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import evaluation as controller
from .domain import CaptureCommand, Claim, NonmodelAdmission
from .evaluation_artifacts import (
    ArtifactBundle,
    ArtifactEntry,
    ArtifactLimits,
    EditWitness,
    StructuralOutcome,
    canonical_bytes,
    digest_bytes,
    safe_path,
    verify_allowed_edits,
)
from .evaluation_runtime import (
    CleanupObservation,
    CommandObservation,
    EvaluationOwner,
    Publication,
    SubjectObservation,
)
from .evaluation_verifier import (
    CaseOutcome,
    ControlArtifact,
    OracleTask,
    VerifierReceipt,
    _private_observations,
    compare_case,
    controls_digest,
)
from .health import HealthAssessmentCommand
from .wire import decode_json, validate_wire

MAX_EVIDENCE_BYTES = 256 * 1024 * 1024
MAX_EVIDENCE_RECORDS = 20000
MAX_REPORT_BYTES = 16 * 1024 * 1024
MAX_HEALTH_VIEW_BYTES = 4 * 1024 * 1024


class EvaluationHealthError(ValueError):
    """A retained observation or explicit command cannot safely be linked."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise EvaluationHealthError(code)


@dataclass(frozen=True)
class EvaluationHealthEvidence:
    """In-memory snapshot, not a second authoritative manifest or signed receipt.

    Obtain this from ``load_evaluation_health_evidence``. Every compilation checks
    its immutable bytes again; caller-created snapshots have no extra authority.
    Source bodies and private observations must never be printed as provenance.
    """

    manifest: controller.EvaluationManifest = field(repr=False)
    report_bytes: bytes = field(repr=False)
    observations_bytes: bytes = field(repr=False)
    records: tuple[tuple[str, bytes], ...] = field(repr=False)


@dataclass(frozen=True)
class CompiledEvaluationHealth:
    command: HealthAssessmentCommand = field(repr=False)
    provenance: dict[str, Any]


def _record_map(evidence: EvaluationHealthEvidence) -> dict[str, bytes]:
    _require(type(evidence.records) is tuple and len(evidence.records) <= MAX_EVIDENCE_RECORDS,
             "EVALUATION_HEALTH_RECORD_BOUND")
    total = len(evidence.manifest.raw) + len(evidence.report_bytes) + len(evidence.observations_bytes)
    total += sum(len(item.raw) for item in evidence.manifest.files)
    records = {}
    for name, raw in evidence.records:
        safe_path(name, depth=8, path_bytes=4096, component_bytes=255)
        _require(name not in records and type(raw) is bytes, "EVALUATION_HEALTH_RECORD_IDENTITY")
        records[name] = raw
        total += len(raw)
    _require(total <= MAX_EVIDENCE_BYTES and len(evidence.report_bytes) <= MAX_REPORT_BYTES,
             "EVALUATION_HEALTH_BYTE_BOUND")
    return records


def _json(records: Mapping[str, bytes], name: str, digest: str | None = None) -> dict:
    _require(name in records, "EVALUATION_HEALTH_RETAINED_RECORD_MISSING")
    raw = records[name]
    _require(digest is None or digest_bytes(raw) == digest, "EVALUATION_HEALTH_RETAINED_DIGEST")
    return decode_json(raw)


def _bundle(raw: bytes, limits: ArtifactLimits) -> ArtifactBundle:
    value = decode_json(raw)
    controller._keys(value, {"schema", "entries"})
    _require(type(value["schema"]) is int and value["schema"] == 1, "EVALUATION_HEALTH_BUNDLE_SCHEMA")
    entries = []
    for item in controller._array(value["entries"], limits.entries):
        controller._keys(item, {"path", "kind", "mode", "size", "sha256", "content"})
        content = controller._binary(item["content"], limits.file_bytes)
        _require(type(item["size"]) is int and item["size"] == len(content),
                 "EVALUATION_HEALTH_BUNDLE_SIZE")
        entries.append(ArtifactEntry(item["path"], item["kind"], item["mode"], content, item["sha256"]))
    return ArtifactBundle(tuple(entries), limits)


def _task_inputs(manifest, task):
    limits = controller._dc(ArtifactLimits, manifest.config["artifact_limits"])
    baseline = _bundle(manifest.file(task["baseline_file"]).raw, limits)
    policy = controller._policy(manifest.document(task["policy_file"]))
    oracle = OracleTask(task["task_id"], task["task_revision"], task["independent_reference"],
                        baseline.digest, policy, EditWitness(baseline.digest, baseline.digest, (), (), (), ()),
                        tuple(controller._case(item, manifest.config["record_bytes"])
                              for item in manifest.document(task["oracle_file"])["cases"]))
    controls = tuple(ControlArtifact(item["role"], _bundle(manifest.file(item["bundle_file"]).raw, limits),
                                    controller._witness(manifest.document(item["witness_file"]), limits))
                     for item in task["controls"])
    _require(tuple(item.role for item in controls) == ("correct", "noop", "plausible_wrong")
             and oracle.digest == task["approved_task_digest"]
             and controls_digest(controls) == task["approved_controls_digest"],
             "EVALUATION_HEALTH_TASK_CONTROL_IDENTITY")
    return baseline, oracle, controls


def _command_observation(value):
    return controller._dc(CommandObservation, value, {"stdout": controller._unbytes, "stderr": controller._unbytes})


def _observation(value):
    return controller._dc(SubjectObservation, value, {
        "execution": lambda item: _command_observation(item) if item is not None else None,
        "effects": lambda items: tuple((path, controller._unbytes(raw) if raw is not None else None)
                                      for path, raw in items),
        "cleanup": lambda item: controller._dc(CleanupObservation, item),
        "operations": lambda items: tuple((stage, _command_observation(raw)) for stage, raw in items),
    })


def _receipt(value):
    return controller._dc(VerifierReceipt, value, {
        "structural": lambda item: controller._dc(StructuralOutcome, item) if item is not None else None,
        "cases": lambda items: tuple(controller._dc(CaseOutcome, item, {
            "observation": lambda observation: _observation(observation) if observation is not None else None,
        }) for item in items),
        "publication": lambda item: controller._dc(Publication, item),
    })


def _validate_receipt(records, directory, value, *, oracle, baseline, submission, structural, role, verifier, owner):
    receipt = _receipt(value)
    _require(type(receipt.schema) is int and receipt.schema == 1 and receipt.owner == owner
             and receipt.role == role and receipt.verifier_digest == verifier
             and receipt.task_digest == oracle.digest and receipt.baseline_digest == baseline.digest
             and receipt.submission_digest == submission.digest and receipt.structural == structural
             and receipt.error_code is None and receipt.cleanup_complete is True
             and receipt.publication.state in {"durable", "reconciled_durable"},
             "EVALUATION_HEALTH_VERIFIER_SCOPE_OR_UNKNOWN")
    if receipt.private_artifact is None or receipt.terminal_artifact is None:
        raise EvaluationHealthError("EVALUATION_HEALTH_VERIFIER_ARTIFACT_MISSING")
    for name in (receipt.private_artifact, receipt.terminal_artifact):
        safe_path(name, depth=1, path_bytes=255, component_bytes=255)
    private = records.get(directory + receipt.private_artifact)
    _require(private is not None and digest_bytes(private) == receipt.private_sha256
             and private == _private_observations(receipt.cases), "EVALUATION_HEALTH_PRIVATE_OBSERVATION")
    terminal = _json(records, directory + receipt.terminal_artifact, receipt.publication.sha256)
    _require(terminal == receipt.public(), "EVALUATION_HEALTH_VERIFIER_TERMINAL")
    # A structural rejection is measured, but an unexecuted oracle is not a
    # measured functional result. In particular, error_code=None alone is insufficient.
    if structural.passed is False and role == "evaluation":
        _require(receipt.success is False and receipt.state == "rejected"
                 and all(case.observation is None for case in receipt.cases),
                 "EVALUATION_HEALTH_STRUCTURAL_REJECTION_INCONSISTENT")
        return receipt
    _require(structural.passed is True and len(receipt.cases) == len(oracle.cases),
             "EVALUATION_HEALTH_FUNCTIONAL_OBSERVATION_UNKNOWN")
    for case, outcome in zip(oracle.cases, receipt.cases, strict=True):
        observation = outcome.observation
        if observation is None or observation.execution is None:
            raise EvaluationHealthError("EVALUATION_HEALTH_FUNCTIONAL_OBSERVATION_UNKNOWN")
        execution, cleanup = observation.execution, observation.cleanup
        _require(observation.state == "completed" and execution.state == "completed"
                 and execution.stdout_complete is True and execution.stderr_complete is True
                 and execution.helper_cleanup is True and cleanup.exact_absence is True
                 and cleanup.pending_create is False and cleanup.state in {"removed", "absent"},
                 "EVALUATION_HEALTH_FUNCTIONAL_OBSERVATION_UNKNOWN")
        _require(compare_case(case, observation) == outcome, "EVALUATION_HEALTH_ORACLE_RESULT_FORGED")
    success = all(case.passed for case in receipt.cases)
    _require(receipt.success is success and receipt.state == ("passed" if success else "rejected"),
             "EVALUATION_HEALTH_VERIFIER_RESULT_FORGED")
    return receipt


def _validate_native(manifest, records, invocation, terminal):
    prefix = "ledger/" + controller._key(invocation["invocation_id"])
    native = _json(records, prefix + ".native.json", terminal["evidence_refs"].get("native"))
    _require(terminal["evidence_refs"].get("native") is not None
             and native["invocation_id"] == invocation["invocation_id"] and native["status"] == "completed"
             and native["comparable"] is True and not native["incomparability_reasons"]
             and native["output_truncated"] is False
             and controller._native_identity(manifest, native["identity"], invocation["mode"]),
             "EVALUATION_HEALTH_NATIVE_SCOPE_OR_UNKNOWN")
    generation = native["identity"].get("thread_id") or native["identity"].get("session_id")
    _require(isinstance(generation, str) and bool(generation), "EVALUATION_HEALTH_GENERATION_UNKNOWN")
    claim = _json(records, "ledger/generation-" + digest_bytes(generation.encode()) + ".json",
                  terminal["evidence_refs"].get("generation"))
    _require(terminal["evidence_refs"].get("generation") is not None and claim == {
        "manifest_digest": manifest.digest, "invocation_id": invocation["invocation_id"],
        "generation_digest": digest_bytes(generation.encode()),
    }, "EVALUATION_HEALTH_GENERATION_SCOPE")
    gateway = _json(records, prefix + ".gateway.json", terminal["evidence_refs"].get("gateway"))
    _require(terminal["evidence_refs"].get("gateway") is not None and gateway == terminal.get("delivery"),
             "EVALUATION_HEALTH_FINAL_DELIVERY_UNKNOWN")
    controller._validate_delivery_receipt(
        manifest, invocation, gateway,
        _trace_events(records, manifest, invocation["invocation_id"], "gateway"),
    )
    return native, gateway


def _validate_terminal(manifest, records, invocation):
    prefix = "ledger/" + controller._key(invocation["invocation_id"])
    _require(_json(records, prefix + ".intent.json") == {
        "schema": 1, "manifest_digest": manifest.digest, "invocation": invocation,
    }, "EVALUATION_HEALTH_INTENT_SCOPE")
    terminal = _json(records, prefix + ".terminal.json")
    controller._keys(terminal, set(controller._initial_result()) | {"schema", "manifest_digest", "invocation_id"}, {"delivery"})
    _require(type(terminal["schema"]) is int and terminal["schema"] == 1
             and terminal["manifest_digest"] == manifest.digest
             and terminal["invocation_id"] == invocation["invocation_id"]
             and terminal["status"] == "completed" and terminal["comparable"] is True
             and terminal["contaminated"] is False and not terminal["comparability_reasons"]
             and terminal["native_identity_observed"] is True,
             "EVALUATION_HEALTH_TERMINAL_SCOPE_OR_UNKNOWN")
    return terminal


def _trace_events(records, manifest, invocation_id, channel):
    import re

    prefix = "traces/" + invocation_id + "/" + channel + "/"
    names = sorted(name.removeprefix(prefix) for name in records if name.startswith(prefix))
    events = [name for name in names if re.fullmatch(r"[0-9]{8}\.json", name)]
    _require(set(names) == set(events) | {"claim.json"}
             and len(events) <= manifest.config["trace_events"], "EVALUATION_HEALTH_TRACE_BOUND_OR_PARTIAL")
    _require(_json(records, prefix + "claim.json") == {
        "manifest_digest": manifest.digest, "invocation_id": invocation_id, "channel": channel,
    }, "EVALUATION_HEALTH_TRACE_SCOPE")
    previous, total, result = manifest.digest, 0, []
    for sequence, name in enumerate(events):
        _require(name == f"{sequence:08d}.json", "EVALUATION_HEALTH_TRACE_GAP")
        raw = records[prefix + name]
        total += len(raw)
        _require(len(raw) <= manifest.config["record_bytes"] and total <= manifest.config["trace_bytes"],
                 "EVALUATION_HEALTH_TRACE_BOUND_OR_PARTIAL")
        value = decode_json(raw)
        controller._keys(value, {"schema", "sequence", "previous_digest", "event"})
        _require(type(value["schema"]) is int and value["schema"] == 1
                 and type(value["sequence"]) is int and value["sequence"] == sequence
                 and value["previous_digest"] == previous, "EVALUATION_HEALTH_TRACE_CHAIN")
        previous = digest_bytes(raw)
        result.append(value["event"])
    return result


def _wire_responses(events):
    for event in events:
        exchange = event.get("exchange", {})
        if (event.get("stage") != "gateway_wire" or exchange.get("stage") != "response"
                or exchange.get("response_complete") is not True
                or exchange.get("request_body") is None or exchange.get("response_body") is None):
            continue
        request_body = controller._unbytes(exchange["request_body"])
        response_body = controller._unbytes(exchange["response_body"])
        if request_body and response_body:
            yield exchange, decode_json(request_body), decode_json(response_body)


def _validate_fence(records, manifest, invocation, channel):
    corpus = manifest.document("corpus")
    sources = {item["source_id"]: item for item in corpus["sources"]}
    claims = {item["ref"]: item for item in corpus["claims"]}
    relations = {item["ref"]: item for item in corpus["relations"]}
    allowed = set(sources) | set(claims) | set(relations) | {"judgment"} | {"health:claim:" + ref for ref in claims}
    source_windows = {ref: [] for ref in sources}
    source_bytes = {ref: bytearray() for ref in sources}
    inspected, windows = {}, {}
    required = probes = 0
    batches, relation_ids = set(), set()
    retries = set()
    for exchange, request, response in _wire_responses(_trace_events(
            records, manifest, invocation["invocation_id"], channel)):
        if exchange.get("path") == "/api/required-context":
            _require(exchange.get("method") == "POST" and exchange.get("http_status") == 200
                     and controller._normalized_retrieval_request(manifest, request)
                     == controller._normalized_retrieval_request(manifest, manifest.config["gateway"]["required_request"])
                     and isinstance(response.get("stamp"), dict)
                     and sorted(response["stamp"].get("rules", [])) == manifest.document("rules")["rules"],
                     "EVALUATION_HEALTH_FENCE_REQUIRED_SCOPE")
            required += 1
            continue
        if exchange.get("path") != "/mcp" or request.get("method") != "tools/call":
            continue
        params = request.get("params", {})
        if params.get("name") not in {"memory_inspect", "memory_context"}:
            continue
        arguments = params.get("arguments", {})
        request_key = canonical_bytes(request)
        error = response.get("error") or {}
        if (exchange.get("http_status") == 404 and response.get("id") == request.get("id")
                and error.get("message") == "SESSION_NOT_FOUND"
                and error.get("data", {}).get("effect") == "not_started"):
            retries.add(request_key)
            continue
        _require(exchange.get("http_status") == 200 and response.get("id") == request.get("id")
                 and "result" in response, "EVALUATION_HEALTH_FENCE_REPLY_UNKNOWN")
        retries.discard(request_key)
        payload = controller._payload(response["result"])
        if params["name"] == "memory_context":
            _require(controller._normalized_retrieval_request(manifest, arguments)
                     == controller._normalized_retrieval_request(manifest, controller._rules_probe_request(manifest))
                     and controller._rule_snapshot(payload) == manifest.document("rules")["applicable"],
                     "EVALUATION_HEALTH_FENCE_APPLICABLE_RULE_DRIFT")
            probes += 1
            continue
        ref = arguments.get("ref")
        _require(ref in allowed and arguments.get("binding_id") == manifest.config["gateway"]["binding_id"]
                 and arguments.get("snapshot") == manifest.config["gateway"]["required_request"].get("snapshot")
                 and arguments.get("max_bytes") == 4096, "EVALUATION_HEALTH_FENCE_INSPECTION_SCOPE")
        if ref in sources:
            source = sources[ref]
            expected = controller._binary(source["body"], controller._FILE_BYTES)
            start = len(source_bytes[ref])
            _require(payload.get("source_id") == ref and payload.get("source_revision") == source["revision"]
                     and payload.get("byte_start") == start and arguments.get("byte_start") == start
                     and payload.get("total_bytes") == len(expected) and isinstance(payload.get("body"), str),
                     "EVALUATION_HEALTH_FENCE_SOURCE_SCOPE")
            source_bytes[ref].extend(payload["body"].encode("utf-8"))
            _require(payload.get("byte_end") == len(source_bytes[ref])
                     and len(source_bytes[ref]) <= len(expected), "EVALUATION_HEALTH_FENCE_SOURCE_BYTES")
            source_windows[ref].append({key: payload.get(key) for key in ("byte_start", "byte_end", "window_digest")})
            continue
        batch = tuple(arguments.get("claim_ids") or ()) if ref == "judgment" else ()
        key = (ref, batch)
        window = payload.get("draft_window")
        if isinstance(window, dict):
            digest, total = window.get("digest"), window.get("total_bytes")
            previous_digest, previous_total, collected = windows.get(key, (digest, total, bytearray()))
            if type(total) is not int or not 0 < total <= manifest.config["record_bytes"]:
                raise EvaluationHealthError("EVALUATION_HEALTH_FENCE_RECORD_WINDOW")
            _require(previous_digest == digest and previous_total == total
                     and window.get("byte_start") == len(collected)
                     and arguments.get("byte_start") == len(collected)
                     and isinstance(window.get("body"), str), "EVALUATION_HEALTH_FENCE_RECORD_WINDOW")
            collected.extend(window["body"].encode("utf-8"))
            _require(len(collected) == window.get("byte_end") and len(collected) <= total,
                     "EVALUATION_HEALTH_FENCE_RECORD_WINDOW")
            windows[key] = (digest, total, collected)
            if window.get("next_byte") is not None:
                _require(window["next_byte"] == len(collected), "EVALUATION_HEALTH_FENCE_RECORD_WINDOW")
                continue
            _require(len(collected) == total and digest_bytes(collected) == digest,
                     "EVALUATION_HEALTH_FENCE_RECORD_DIGEST")
            payload = decode_json(bytes(collected))
        if ref == "judgment":
            _require(batch and batch not in batches and len(batch) <= 20
                     and set(batch) <= claims.keys(), "EVALUATION_HEALTH_FENCE_RELATION_BATCH")
            relation_ids.update(controller._relation_manifest_ids(manifest, payload, batch))
            batches.add(batch)
            windows.pop(key, None)
            continue
        _require(ref not in inspected and payload.get("partial") is not True,
                 "EVALUATION_HEALTH_FENCE_RECORD_DUPLICATE_OR_PARTIAL")
        inspected[ref] = payload
    claim_ids = tuple(claims)
    expected_batches = {claim_ids[start:start + 20] for start in range(0, len(claim_ids), 20)}
    _require(required == 1 and probes == 1 and not retries and batches == expected_batches,
             "EVALUATION_HEALTH_FENCE_REQUIRED_PROBE_RELATION_OR_RETRY_UNKNOWN")
    _require(relation_ids == relations.keys(), "EVALUATION_HEALTH_FENCE_RELATION_SET_DRIFT")
    for ref, source in sources.items():
        _require(bytes(source_bytes[ref]) == controller._binary(source["body"], controller._FILE_BYTES)
                 and source_windows[ref] == source["inspection_windows"],
                 "EVALUATION_HEALTH_FENCE_SOURCE_DRIFT")
    for ref, claim in claims.items():
        _require(ref in inspected and all(inspected[ref].get(key) == value
                                         for key, value in claim["projection"].items()),
                 "EVALUATION_HEALTH_FENCE_CLAIM_DRIFT")
        health = inspected.get("health:claim:" + ref, {})
        _require(health.get("dependency_digest") == claim["health_dependency_digest"],
                 "EVALUATION_HEALTH_FENCE_DEPENDENCY_DRIFT")
    for ref, edge in relations.items():
        _require(ref in inspected and all(inspected[ref].get(key) == value
                                         for key, value in edge["projection"].items()),
                 "EVALUATION_HEALTH_FENCE_RELATION_CONTENT_DRIFT")


def _validate_preflight_wire(records, manifest, invocation, terminal):
    identifier = invocation["invocation_id"]
    capture = _json(records, "ledger/" + controller._key(identifier) + ".capture.json")
    expected = validate_wire(CaptureCommand, manifest.workload["preflight"]["capture"]).model_dump(mode="json")
    captures = []
    for exchange, request, response in _wire_responses(_trace_events(records, manifest, identifier, "producer")):
        if exchange.get("path") == "/api/capture" and exchange.get("method") == "POST":
            _require(exchange.get("http_status") == 202 and response.get("effect") == "committed"
                     and response.get("capture_disposition") == "captured"
                     and validate_wire(CaptureCommand, request).model_dump(mode="json") == expected,
                     "EVALUATION_HEALTH_PRODUCER_WIRE_SCOPE")
            pointer = response.get("source_pointer")
            _require(isinstance(pointer, dict) and pointer == capture["source_pointer"],
                     "EVALUATION_HEALTH_PRODUCER_POINTER_SCOPE")
            captures.append(pointer)
    _require(len(captures) == 1 and controller._preflight_link_data(
        manifest, capture, _trace_events(records, manifest, identifier, "gateway"), terminal["delivery"]),
        "EVALUATION_HEALTH_PRODUCER_NATIVE_PIPELINE_UNKNOWN")


def load_evaluation_health_evidence(
    run_dir: Path, *, expected_manifest_sha256: str, adjudication: bytes | None = None,
) -> EvaluationHealthEvidence:
    """Read the actual controller report and bounded immutable retained artifacts.

    No native process, verifier, gateway, service request, or publication is run.
    Missing records fail closed; the returned snapshot is only engineering evidence.
    """
    manifest = controller._load_frozen_run(run_dir)
    _require(manifest.digest == controller._digest(expected_manifest_sha256),
             "EVALUATION_HEALTH_EXPECTED_MANIFEST")
    controller._validate_documents(manifest)
    protocol, arms, retrieval = controller.load_report_inputs(run_dir)
    report = controller.report_evaluation(run_dir, adjudication=adjudication)
    observations = canonical_bytes({"protocol": protocol.model_dump(mode="json"),
                                    "arms": [row.model_dump(mode="json") for row in arms],
                                    "retrieval": [row.model_dump(mode="json") for row in retrieval]})
    records: dict[str, bytes] = {}
    if adjudication is not None:
        records["adjudication.json"] = adjudication
    total = (len(manifest.raw) + sum(len(item.raw) for item in manifest.files)
             + len(observations) + len(canonical_bytes(report)) + len(adjudication or b""))

    def take(name, maximum=None, *, optional=False):
        nonlocal total
        safe_path(name, depth=8, path_bytes=4096, component_bytes=255)
        if name not in records:
            _require(len(records) < MAX_EVIDENCE_RECORDS, "EVALUATION_HEALTH_RECORD_BOUND")
            try:
                raw = controller._read(
                    run_dir / name, min(maximum or manifest.config["record_bytes"], MAX_EVIDENCE_BYTES),
                    private=True)
            except FileNotFoundError:
                if optional:
                    return None
                raise
            total += len(raw)
            _require(total <= MAX_EVIDENCE_BYTES, "EVALUATION_HEALTH_BYTE_BOUND")
            records[name] = raw
        # Private observation arrays must remain byte-exact until receipt validation.
        return records[name]

    def take_trace(invocation_id, channel):
        directory = "traces/" + invocation_id + "/" + channel + "/"
        descriptor = controller.open_private_directory(run_dir / directory)
        try:
            names = controller._bounded_names(descriptor, manifest.config["trace_events"] + 2)
        finally:
            controller.os.close(descriptor)
        for name in names:
            take(directory + name)
        _trace_events(records, manifest, invocation_id, channel)

    def receipt_artifacts(directory, receipt):
        for key in ("private_artifact", "terminal_artifact"):
            name = receipt.get(key)
            _require(isinstance(name, str), "EVALUATION_HEALTH_VERIFIER_ARTIFACT_MISSING")
            safe_path(name, depth=1, path_bytes=255, component_bytes=255)
            maximum = max(manifest.config["record_bytes"],
                          manifest.config["verifier_limits"]["private_receipt_bytes"])
            take(directory + name, maximum)

    valid_ids = {row["invocation_id"] for pair in report["coding"]["pairs"] if pair["valid"]
                 for row in pair["arms"].values()}
    valid_ids.add(manifest.workload["preflight"]["invocation_id"])
    valid_ids.update(row.attempt_id for row in retrieval
                     if row.status == "completed" and row.comparable and not row.contaminated)
    for invocation in manifest.workload["invocations"]:
        prefix = "ledger/" + controller._key(invocation["invocation_id"])
        for suffix in ("intent", "terminal", "gateway"):
            take(prefix + "." + suffix + ".json", optional=True)
        if invocation["invocation_id"] not in valid_ids:
            continue
        _require(prefix + ".intent.json" in records and prefix + ".terminal.json" in records,
                 "EVALUATION_HEALTH_RETAINED_RECORD_MISSING")
        native = decode_json(take(prefix + ".native.json", manifest.config["trace_bytes"]))
        take(prefix + ".gateway.json")
        generation = native["identity"].get("thread_id") or native["identity"].get("session_id")
        _require(isinstance(generation, str), "EVALUATION_HEALTH_GENERATION_UNKNOWN")
        take("ledger/generation-" + digest_bytes(generation.encode()) + ".json")
        take_trace(invocation["invocation_id"], "gateway")
        if invocation["phase"] == "preflight":
            take(prefix + ".capture.json")
            take_trace(invocation["invocation_id"], "producer")
            continue
        for channel in ("fence_before", "fence_after"):
            take_trace(invocation["invocation_id"], channel)
        if invocation["phase"] != "coding":
            continue
        take("artifacts/" + invocation["invocation_id"] + ".submission.json", manifest.config["artifact_limits"]["bundle_bytes"])
        take("artifacts/" + invocation["invocation_id"] + ".witness.json")
        control = decode_json(take(prefix + ".controls.json"))
        receipt = decode_json(take(prefix + ".verifier.json"))
        pair = controller._pair_verifier_id(manifest, invocation)
        take("ledger/" + pair + ".intent.json")
        take("ledger/" + pair + ".controls.json")
        directory = "verifiers/" + pair + "/"
        receipt_artifacts(directory, receipt)
        for item in control["receipts"]:
            receipt_artifacts(directory, item)
    evidence = EvaluationHealthEvidence(manifest, canonical_bytes(report), observations, tuple(sorted(records.items())))
    _validate_evidence(evidence, expected_manifest_sha256)
    return evidence


def _validate_evidence(evidence, expected_manifest_sha256):
    records = _record_map(evidence)
    manifest = evidence.manifest
    _require(digest_bytes(manifest.raw) == manifest.digest == controller._digest(expected_manifest_sha256),
             "EVALUATION_HEALTH_EXPECTED_MANIFEST")
    files = manifest.config["files"]
    _require(len(files) == len(manifest.files) and len({item.name for item in manifest.files}) == len(files),
             "EVALUATION_HEALTH_FROZEN_FILES")
    for ref in files:
        frozen = manifest.file(ref["name"])
        _require(frozen.sha256 == ref["sha256"] == digest_bytes(frozen.raw)
                 and len(frozen.raw) <= ref["maximum_bytes"], "EVALUATION_HEALTH_FROZEN_DIGEST")
    controller._validate_documents(manifest)
    ledger = {
        name: decode_json(raw) for name, raw in records.items()
        if name.startswith("ledger/") and name.endswith((".intent.json", ".terminal.json", ".gateway.json"))
    }
    protocol, arms, retrieval = controller._report_inputs_from_records(manifest, ledger)
    observations = canonical_bytes({
        "protocol": protocol.model_dump(mode="json"),
        "arms": [row.model_dump(mode="json") for row in arms],
        "retrieval": [row.model_dump(mode="json") for row in retrieval],
    })
    _require(evidence.observations_bytes == observations, "EVALUATION_HEALTH_OBSERVATION_TERMINAL_CONFLICT")
    report = controller._report_from_records(manifest, ledger, adjudication=records.get("adjudication.json"))
    _require(evidence.report_bytes == canonical_bytes(report), "EVALUATION_HEALTH_REPORT_CONFLICT")
    preflight = controller._invocation(manifest, manifest.workload["preflight"]["invocation_id"])
    preflight_terminal = _validate_terminal(manifest, records, preflight)
    _validate_native(manifest, records, preflight, preflight_terminal)
    _validate_preflight_wire(records, manifest, preflight, preflight_terminal)
    pairs = [pair for pair in report["coding"]["pairs"] if pair["valid"]]
    _require(bool(pairs), "EVALUATION_HEALTH_NO_OBSERVED_COMPARABLE_PAIR")
    by_id = {row.invocation_id: row for row in arms}
    preflight_native = _json(records, "ledger/" + controller._key(preflight["invocation_id"]) + ".native.json")
    generations = {preflight_native["identity"].get("thread_id") or preflight_native["identity"].get("session_id")}
    for row in retrieval:
        if row.status != "completed" or not row.comparable or row.contaminated:
            continue
        invocation = controller._invocation(manifest, row.attempt_id)
        terminal = _validate_terminal(manifest, records, invocation)
        native, _ = _validate_native(manifest, records, invocation, terminal)
        generation = native["identity"].get("thread_id") or native["identity"].get("session_id")
        _require(generation not in generations, "EVALUATION_HEALTH_GENERATION_REUSED")
        generations.add(generation)
        for channel in ("fence_before", "fence_after"):
            _validate_fence(records, manifest, invocation, channel)
    for pair in pairs:
        for public in pair["arms"].values():
            arm = by_id[public["invocation_id"]]
            invocation = controller._invocation(manifest, arm.invocation_id)
            _require(invocation["phase"] == "coding" and arm.pair_id == controller._pair_id(manifest, invocation["target_id"], invocation["repeat_index"])
                     and (arm.task_id, arm.repeat_index, arm.pair_attempt, arm.mode) == (
                         invocation["target_id"], invocation["repeat_index"], invocation["pair_attempt"], invocation["mode"]),
                     "EVALUATION_HEALTH_ARM_SCOPE")
            terminal = _validate_terminal(manifest, records, invocation)
            for key, value in arm.model_dump(mode="json").items():
                if key in terminal:
                    _require(terminal[key] == value, "EVALUATION_HEALTH_ARM_TERMINAL_CONFLICT")
            native, _ = _validate_native(manifest, records, invocation, terminal)
            for channel in ("fence_before", "fence_after"):
                _validate_fence(records, manifest, invocation, channel)
            generation = native["identity"].get("thread_id") or native["identity"].get("session_id")
            _require(generation not in generations, "EVALUATION_HEALTH_GENERATION_REUSED")
            generations.add(generation)
            task = controller._task(manifest, invocation["target_id"])
            baseline, oracle, controls = _task_inputs(manifest, task)
            prefix = "ledger/" + controller._key(arm.invocation_id)
            control = _json(records, prefix + ".controls.json", arm.control_receipt_digest)
            pair_id = controller._pair_verifier_id(manifest, invocation)
            pair_intent = _json(records, "ledger/" + pair_id + ".intent.json")
            _require(pair_intent["manifest_digest"] == manifest.digest and pair_intent["pair_verifier_id"] == pair_id
                     and set(pair_intent["invocation_ids"]) == {item["invocation_id"] for item in manifest.workload["invocations"]
                         if item["phase"] == "coding" and controller._pair_verifier_id(manifest, item) == pair_id}
                     and pair_intent["task_digest"] == oracle.digest
                     and pair_intent["controls_digest"] == task["approved_controls_digest"]
                     and _json(records, "ledger/" + pair_id + ".controls.json") == control,
                     "EVALUATION_HEALTH_PAIR_CONTROL_SCOPE")
            verifier = controller._verifier_spec(manifest).digest
            verifier_owner = controller._dc(EvaluationOwner, pair_intent["owner"]).identity
            _require(control["eligible"] is True and control["task_digest"] == oracle.digest
                     and control["verifier_digest"] == verifier
                     and control["controls_digest"] == task["approved_controls_digest"]
                     and control["approval_reference"] == task["approval_reference"]
                     and len(control["receipts"]) == 3, "EVALUATION_HEALTH_CONTROLS_FAILED_OR_UNKNOWN")
            directory = "verifiers/" + pair_id + "/"
            for artifact, raw in zip(controls, control["receipts"], strict=True):
                structural = verify_allowed_edits(baseline, artifact.bundle, oracle.policy, artifact.witness)
                receipt = _validate_receipt(records, directory, raw, oracle=oracle, baseline=baseline,
                    submission=artifact.bundle, structural=structural, role="control_" + artifact.role,
                    verifier=verifier, owner=verifier_owner)
                _require(receipt.success is (artifact.role == "correct"), "EVALUATION_HEALTH_CONTROL_RESULT")
            submission_name = "artifacts/" + arm.invocation_id + ".submission.json"
            _require(submission_name in records, "EVALUATION_HEALTH_SUBMISSION_MISSING")
            submission = _bundle(records[submission_name], baseline.limits)
            artifact = native.get("artifact_bundle") or {}
            _require(artifact.get("sha256") == digest_bytes(records[submission_name])
                     and submission.digest == arm.artifact_digest, "EVALUATION_HEALTH_SUBMISSION_IDENTITY")
            witness = controller._witness(_json(records, "artifacts/" + arm.invocation_id + ".witness.json"), baseline.limits)
            structural = verify_allowed_edits(baseline, submission, oracle.policy, witness)
            receipt = _validate_receipt(records, directory,
                _json(records, prefix + ".verifier.json", arm.verifier_receipt_digest), oracle=oracle,
                baseline=baseline, submission=submission, structural=structural, role="evaluation",
                verifier=verifier, owner=verifier_owner)
            _require(receipt.controls_digest == control["controls_digest"]
                     and receipt.structural.passed is arm.structural_pass
                     and ((receipt.success is arm.functional_success) if structural.passed
                          else arm.functional_success is None),
                     "EVALUATION_HEALTH_VERIFIER_ARM_CONFLICT")
    return manifest, report


def compile_evaluation_health_assessment(
    evidence: EvaluationHealthEvidence,
    command: HealthAssessmentCommand | Mapping[str, Any],
    *,
    current_health_views: Mapping[str, Mapping[str, Any]],
    current_health_work: Mapping[str, Any],
    expected_manifest_sha256: str,
) -> CompiledEvaluationHealth:
    """Purely revalidate an explicit judgment and attach the full report digest.

    ``current_health_views`` is keyed by claim ID and contains complete, unwindowed
    live ``memory_inspect(ref='health:claim:<id>')`` results for exactly the command
    input claims. It must be fetched in the frozen request snapshot. The compiler
    cannot attest freshness of caller-supplied data; the server must recheck admission.
    """
    manifest, report = _validate_evidence(evidence, expected_manifest_sha256)
    payload = command.model_dump(mode="json") if isinstance(command, HealthAssessmentCommand) else dict(command)
    explicit = validate_wire(HealthAssessmentCommand, payload)
    _require(explicit.binding_id == manifest.config["gateway"]["binding_id"], "EVALUATION_HEALTH_BINDING_SCOPE")
    _require(bool(explicit.input_claims), "EVALUATION_HEALTH_EMPTY_TARGETS")
    _require(current_health_work.get("kind") == "health_work"
             and "draft_window" not in current_health_work
             and current_health_work.get("pending_id") == explicit.pending_id
             and current_health_work.get("binding_id") == explicit.binding_id
             and current_health_work.get("binding_revision") == explicit.expected_binding_revision
             and current_health_work.get("health_manifest_digest") == explicit.health_manifest_digest
             and current_health_work.get("input_sources") == [ref.model_dump(mode="json") for ref in explicit.input_sources]
             and current_health_work.get("input_claims") == [ref.model_dump(mode="json") for ref in explicit.input_claims],
             "EVALUATION_HEALTH_WORK_MANIFEST_SCOPE")
    work_admission = validate_wire(NonmodelAdmission, current_health_work.get("admission"))
    # Each live inspect issues a new admission. Preserve the command's original
    # retry identity; the server must validate that original admission at publish.
    _require(work_admission.binding_id == explicit.binding_id
             and work_admission.binding_revision == explicit.expected_binding_revision
             and work_admission.pending_id in {None, explicit.pending_id}
             and work_admission.snapshot in {None, manifest.config["gateway"]["required_request"].get("snapshot")}
             and work_admission.health_manifest_digest == explicit.health_manifest_digest
             and work_admission.request_digest == explicit.health_manifest_digest
             and {(ref.id, ref.revision) for ref in work_admission.sources}
             == {(ref.id, ref.revision) for ref in explicit.input_sources}
             and set(work_admission.claim_ids) == {ref.id for ref in explicit.input_claims},
             "EVALUATION_HEALTH_WORK_ADMISSION_SCOPE")
    corpus = manifest.document("corpus")
    sources, claims = {}, {}
    for source in corpus["sources"]:
        identifier = source["source_id"]
        _require(identifier not in sources, "EVALUATION_HEALTH_DUPLICATE_SOURCE")
        body = controller._binary(source["body"], controller._FILE_BYTES)
        _require(digest_bytes(body) == source["sha256"], "EVALUATION_HEALTH_SOURCE_DIGEST")
        windows = source.get("inspection_windows")
        _require(isinstance(windows, list) and bool(windows), "EVALUATION_HEALTH_SOURCE_WINDOWS_MISSING")
        covered = 0
        for window in windows:
            controller._keys(window, {"byte_start", "byte_end", "window_digest"})
            start, end = window["byte_start"], window["byte_end"]
            _require(type(start) is int and type(end) is int and start == covered and start < end <= len(body),
                     "EVALUATION_HEALTH_SOURCE_WINDOW_COVERAGE")
            controller._digest(window["window_digest"])
            body[:start].decode("utf-8")
            body[start:end].decode("utf-8")
            covered = end
        _require(covered == len(body), "EVALUATION_HEALTH_SOURCE_WINDOW_COVERAGE")
        sources[identifier] = (source["revision"], body)
    for claim in corpus["claims"]:
        _require(claim["ref"] not in claims and claim["projection"]["id"] == claim["ref"],
                 "EVALUATION_HEALTH_CLAIM_IDENTITY")
        controller._digest(claim.get("health_dependency_digest"))
        claims[claim["ref"]] = claim
    for ref in explicit.input_sources:
        _require(ref.id in sources and sources[ref.id][0] == ref.revision, "EVALUATION_HEALTH_SOURCE_REVISION")
    target_ids = {ref.id for ref in explicit.input_claims}
    _require(set(current_health_views) == target_ids, "EVALUATION_HEALTH_VIEW_TARGETS")
    _require(len(canonical_bytes({
        "claims": dict(current_health_views), "work": dict(current_health_work),
    })) <= MAX_HEALTH_VIEW_BYTES, "EVALUATION_HEALTH_VIEW_BOUND")
    for ref in explicit.input_claims:
        _require(ref.id in claims and claims[ref.id]["projection"]["revision"] == ref.revision,
                 "EVALUATION_HEALTH_CLAIM_REVISION")
        frozen = claims[ref.id]
        view = current_health_views[ref.id]
        _require(view.get("kind") == "memory_health" and "draft_window" not in view
                 and view.get("coverage") == {"complete": True, "scope": "exact_claim_and_current_dependency_candidates"}
                 and view.get("dependency_digest") == frozen["health_dependency_digest"],
                 "EVALUATION_HEALTH_DEPENDENCY_MISMATCH_OR_PARTIAL")
        projection = frozen["projection"]
        live_claim = validate_wire(Claim, view.get("claim")).model_dump(mode="json")
        live_view = {
            **live_claim, "statement": live_claim["draft"]["statement"],
            "draft": {key: value for key, value in live_claim["draft"].items() if key != "evidence"},
        }
        _require(all(live_view[key] == value for key, value in projection.items()
                     if key in Claim.model_fields or key == "statement"),
                 "EVALUATION_HEALTH_LIVE_CLAIM_MISMATCH")
        admission = validate_wire(NonmodelAdmission, view.get("admission"))
        _require(admission.binding_id == explicit.binding_id
                 and admission.binding_revision == explicit.expected_binding_revision
                 and admission.credential_id == work_admission.credential_id
                 and admission.credential_generation == work_admission.credential_generation
                 and admission.claim_ids == (ref.id,)
                 and admission.health_manifest_digest == frozen["health_dependency_digest"]
                 and admission.request_digest == frozen["health_dependency_digest"]
                 and admission.snapshot == manifest.config["gateway"]["required_request"].get("snapshot"),
                 "EVALUATION_HEALTH_LIVE_ADMISSION_SCOPE")
        for source in admission.sources:
            _require(source.id in sources and sources[source.id][0] == source.revision,
                     "EVALUATION_HEALTH_LIVE_SOURCE_REVISION")
    admitted_sources = {(ref.id, ref.revision) for ref in explicit.input_sources}
    for assessment in explicit.assessments:
        for span in assessment.evidence:
            key = (span.source_ref.id, span.source_ref.revision)
            _require(key in admitted_sources and span.source_ref.id in sources
                     and sources[span.source_ref.id][0] == span.source_ref.revision,
                     "EVALUATION_HEALTH_EVIDENCE_SOURCE_SCOPE")
            body = sources[span.source_ref.id][1]
            _require(0 <= span.byte_start < span.byte_end <= len(body)
                     and body[span.byte_start:span.byte_end] == span.quote.encode("utf-8"),
                     "EVALUATION_HEALTH_EVIDENCE_BYTES")
    digest = digest_bytes(evidence.report_bytes)
    _require(evidence.report_bytes == canonical_bytes(report), "EVALUATION_HEALTH_NONCANONICAL_REPORT")
    _require(explicit.evaluation_receipt_digest in {None, digest}, "EVALUATION_HEALTH_REPORT_DIGEST_CONFLICT")
    compiled = validate_wire(HealthAssessmentCommand, {**explicit.model_dump(mode="json"), "evaluation_receipt_digest": digest})
    return CompiledEvaluationHealth(compiled, {
        "schema": 1, "scope": report["scope"], "evidence_kind": "retained_controller_measurements",
        "manifest_digest": manifest.digest, "report_digest": digest,
        "corpus_digest": manifest.file("corpus").sha256,
        "valid_pair_attempts": report["coding"]["valid_pair_attempts"],
        "independence": "provided_unattested", "original_acceptance": False, "original18_completed": 0,
        "engineering_nonacceptance": True, "human_approval": "not_attested",
        "semantic_judgments": "explicit_command_only", "provider_consumption": "not_attested",
        "authority": "existing_server_health_admission_fence_required",
    })
