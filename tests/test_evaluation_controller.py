from __future__ import annotations

import asyncio
import base64
import copy
import json
import os
import subprocess
import sys
import threading
from dataclasses import asdict
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from test_evaluation_gateway import actual_upstream
from test_store_authority import authority as authority
from test_store_authority import ready_claim, relation_judgment

from agents_memory import context as context_module
from agents_memory import (
    evaluation,
    evaluation_diagnostics,
    evaluation_gateway,
    evaluation_native,
    evaluation_scoring,
    evaluation_verifier,
)
from agents_memory.client import HttpExchange
from agents_memory.domain import RuleApproval, RuleProposal, RuleScope
from agents_memory.evaluation import (
    EvaluationError,
    PrivateTrace,
    build_gateway,
    load_manifest,
    load_report_inputs,
    prepare_run,
    run_evaluation,
)
from agents_memory.evaluation_artifacts import (
    ArtifactBundle,
    ArtifactEntry,
    ArtifactLimits,
    ByteEdit,
    EditableSpan,
    EditPolicy,
    EditWitness,
    canonical_bytes,
    digest_bytes,
)
from agents_memory.evaluation_runtime import OBSERVER_SOURCE, WATCHDOG_SOURCE
from agents_memory.evaluation_verifier import (
    ControlArtifact,
    OracleCase,
    OracleTask,
    controls_digest,
)


def b64(raw):
    return base64.b64encode(raw).decode("ascii")


def save(path, value):
    path.write_bytes(value if isinstance(value, bytes) else canonical_bytes(value))
    path.chmod(0o600)


def fixture_inputs(tmp_path, *, repeats=2, retries=0, gateway=None, preflight_gateway=None, peer=None, correct_code=b"print('correct')\n"):
    root = tmp_path / "inputs"
    root.mkdir(mode=0o700)
    workspaces = tmp_path / "native"
    workspaces.mkdir(mode=0o700)
    limits = ArtifactLimits(65536, 20, 8192, 16384, 8, 512, 128, 20, 16384)
    baseline_code = b"print('noop')\n"

    def bundle(code):
        entries = (ArtifactEntry("program.py", "file", 0o644, code, digest_bytes(code)), ArtifactEntry("retained.txt", "file", 0o644, b"retained\r\n", digest_bytes(b"retained\r\n")))
        return ArtifactBundle(entries, limits)

    baseline, correct, wrong = [bundle(code) for code in (baseline_code, correct_code, b"print('plausible')\n")]
    documents = {
        "controller": Path(evaluation.__file__).read_bytes(),
        "verifier": Path(evaluation_verifier.__file__).read_bytes(),
        "native_driver": Path(evaluation_native.__file__).read_bytes(),
        "gateway_driver": Path(evaluation_gateway.__file__).read_bytes(),
        "scoring": Path(evaluation_scoring.__file__).read_bytes(),
        "diagnostics": Path(evaluation_diagnostics.__file__).read_bytes(),
        "context_renderer": Path(context_module.__file__).read_bytes(),
        "wheel": b"engineering fixture identity; not an installed-wheel attestation",
        "baseline": baseline.to_bytes(), "correct": correct.to_bytes(), "wrong": wrong.to_bytes(),
        "policy": {"baseline_digest": baseline.digest, "spans": [{"path": "program.py", "start": 0, "end": len(baseline_code)}], "creates": [], "deletes": [], "modes": []},
        "oracle": {"schema": 1, "cases": [{"case_id": "stdout", "argv": ["/usr/local/bin/python3", "-I", "-S", "/artifact/program.py"], "stdin": "", "expected_stdout": b64(b"correct\n"), "expected_stderr": "", "expected_exit": 0, "effects": []}]},
        "prompt": b"Engineering fixture only. Preserve every baseline byte outside the approved program edit. This is not an actual native or independent task acceptance sample.",
        "corpus": {"schema": 2, "sources": [], "claims": [], "relations": []},
        "gold": {"schema": 1, "independence": "provided_unattested", "cases": [{"case_id": "no-match", "cluster_id": "source-family-one", "group": "no-match", "relevant_claim_ids": [], "irrelevant_claim_ids": [], "judgment_complete": True, "grounding_refs": []}]},
        "rules": {"schema": 2, "rules": [], "probe": {"query": "a" * 64, "max_bytes": 6144, "limit": 5}, "applicable": []},
        "preflight_rules": {"schema": 1, "rules": []},
        "runtime": {
            "docker_executable": "/usr/bin/docker", "docker_sha256": "a" * 64, "docker_config": str(tmp_path / "docker-config"), "docker_endpoint": "unix:///var/run/docker.sock", "image_reference": "engineering-image@sha256:" + "b" * 64, "image_id": "sha256:" + "c" * 64, "image_config_digest": "d" * 64, "image_environment": [], "python_executable": "/usr/local/bin/python3", "tool_identity": "e" * 64, "watchdog_digest": digest_bytes(WATCHDOG_SOURCE), "observer_digest": digest_bytes(OBSERVER_SOURCE),
            "limits": {"cpu_nanos": 1000000000, "memory_bytes": 134217728, "pids": 32, "file_descriptors": 64, "file_bytes": 65536, "scratch_bytes": 65536, "tmp_bytes": 65536, "shm_bytes": 65536, "wall_seconds": 2.0, "watchdog_seconds": 60.0, "operation_seconds": 2.0, "cleanup_seconds": 1.0, "stdin_bytes": 8192, "stdout_bytes": 8192, "stderr_bytes": 8192, "helper_bytes": 65536},
        },
    }
    for role, artifact in (("correct", correct), ("noop", baseline), ("plausible_wrong", wrong)):
        documents[role + "_witness"] = {"baseline_digest": baseline.digest, "final_digest": artifact.digest, "edits": [] if role == "noop" else [{"path": "program.py", "start": 0, "end": len(baseline_code), "replacement": b64(artifact.entries[0].content)}], "creates": [], "deletes": [], "modes": []}
    executable = tmp_path / "native-protocol-peer"
    executable.write_text("#!" + sys.executable + "\n" + (peer or "raise SystemExit('engineering peer must not execute')\n"))
    executable.chmod(0o700)
    documents["native_identity"] = {"schema": 1, "backend": "codex", "executable_sha256": digest_bytes(executable.read_bytes()), "fields": {"initialize.userAgent": "engineering-controller-peer", "resolved.model": "engineering-peer-model", "resolved.approvalPolicy": "on-request", "resolved.sandbox": "workspace-write"}}

    def channel(binding, route, rules):
        endpoint = {"base_url": "http://127.0.0.1:19876"}
        return {"route_ref": route, "binding_id": binding, "agent": {"endpoint": endpoint, "token_file": str(tmp_path / (binding + "-agent-token")), "approval_ref": "engineering-not-native-approval"}, "producer": {"endpoint": endpoint, "token_file": str(tmp_path / (binding + "-producer-token")), "approval_ref": "engineering-not-native-approval"}, "approved_upstream_urls": [endpoint["base_url"]], "approved_refs": [], "protocol_version": "2025-11-25", "max_calls": 200, "max_trace_bytes": 4 * 1024 * 1024, "required_request": {"binding_id": binding, "query": "CacheKey offline", "max_bytes": 6144, "limit": 3}, "lifetime_seconds": 5.0, "rules_file": rules}

    gateway = gateway or channel("engineering-coding", "engineering-coding-route", "rules")
    preflight_gateway = preflight_gateway or channel("engineering-preflight", "engineering-preflight-route", "preflight_rules")
    documents["native_tool_mapping"] = {
        "schema": 1, "backend": "codex",
        "routes": [{"route_ref": selected["route_ref"], "server": "engineering-scoped-gateway",
                    "tools": {name: name for name in ("memory_required_context", *evaluation_gateway.SCHEMAS)}}
                   for selected in (gateway, preflight_gateway)],
    }
    context = {"schema": 1, "independence": "provided_unattested", "settings_digest": "1" * 64, "permissions_digest": "2" * 64, "ownership_boundary_ref": "engineering-only-not-an-isolation-attestation", "exclusive_optional_route_observed": True, "residual_memory_absence_observed": True, "fresh_generation_observed": True}
    documents["context"] = {**context, "route_ref": gateway["route_ref"]}
    documents["preflight_context"] = {**context, "route_ref": preflight_gateway["route_ref"]}
    invocations = []

    def invocation(identity, phase, target, mode, repeat=None, attempt=None):
        cwd = workspaces / identity
        selected = preflight_gateway if phase == "preflight" else gateway
        invocations.append({"invocation_id": identity, "phase": phase, "target_id": target, "mode": mode, "repeat_index": repeat, "pair_attempt": attempt, "context_file": "preflight_context" if phase == "preflight" else "context", "native": {"backend": "codex", "executable": str(executable), "cwd": str(cwd), "submission_path": str(cwd / "submission.json"), "authorization_ref": "engineering-protocol-peer-not-native-approval", "context_observation_ref": "engineering-unattested-context", "approved_context": True, "gateway_invocation_id": identity, "gateway_route_ref": selected["route_ref"], "exclusive_optional_route_observed": True, "residual_memory_absence_observed": True, "fresh_generation_observed": True, "timeout_seconds": 5.0, "cleanup_seconds": 1.0, "max_input_bytes": 32768, "max_stdout_bytes": 65536, "max_stderr_bytes": 8192, "max_record_bytes": 16384, "max_events": 200, "max_submission_bytes": 65536, "expected_model": "engineering-peer-model", "expected_version": "engineering-controller-peer"}})

    invocation("preflight-one", "preflight", "preflight-one", "memory_on")
    for mode in ("memory_on", "required_only"):
        invocation("retrieval-" + mode, "retrieval", "no-match", mode)
    for repeat in range(repeats):
        for attempt in range(retries + 1):
            for mode in ("memory_on", "required_only"):
                invocation(f"task-{repeat}-{attempt}-{mode}", "coding", "coding-one", mode, repeat, attempt)
    documents["workload"] = {"schema": 1, "tasks": [{"task_id": "coding-one", "task_revision": "r1", "cluster_id": "coding-one", "prompt_file": "prompt", "baseline_file": "baseline", "policy_file": "policy", "oracle_file": "oracle", "controls": [{"role": "correct", "bundle_file": "correct", "witness_file": "correct_witness"}, {"role": "noop", "bundle_file": "baseline", "witness_file": "noop_witness"}, {"role": "plausible_wrong", "bundle_file": "wrong", "witness_file": "plausible_wrong_witness"}], "approval_reference": "engineering-fixture-not-independent-human-approval", "independent_reference": "engineering-fixture-not-independent-task-review", "witness_name": "edit-witness.json"}], "retrieval": [{"case_id": "no-match", "prompt_file": "prompt", "request": gateway["required_request"]}], "preflight": {"invocation_id": "preflight-one", "capture": {"binding_id": preflight_gateway["binding_id"], "idempotency_key": "engineering-controller-capture", "origin_key": "engineering-controller-source", "body": "CacheKey is retained only offline.", "speaker": "document"}, "recall_request": preflight_gateway["required_request"], "prompt_file": "prompt", "baseline_file": "baseline"}, "invocations": invocations}
    policy = EditPolicy(baseline.digest, (EditableSpan("program.py", 0, len(baseline_code)),), (), (), ())
    empty = EditWitness(baseline.digest, baseline.digest, (), (), (), ())
    oracle = OracleTask("coding-one", "r1", "engineering-fixture-not-independent-task-review", baseline.digest, policy, empty,
                        (OracleCase("stdout", ("/usr/local/bin/python3", "-I", "-S", "/artifact/program.py"), b"", b"correct\n", b"", 0, ()),))
    controls = tuple(ControlArtifact(role, artifact, empty if role == "noop" else EditWitness(
        baseline.digest, artifact.digest, (ByteEdit("program.py", 0, len(baseline_code), artifact.entries[0].content),), (), (), ()))
        for role, artifact in (("correct", correct), ("noop", baseline), ("plausible_wrong", wrong)))
    documents["workload"]["tasks"][0].update(approved_task_digest=oracle.digest, approved_controls_digest=controls_digest(controls))
    files = []
    for name, value in documents.items():
        path = root / (name + ".input")
        save(path, value)
        files.append({"name": name, "path": str(path), "sha256": digest_bytes(path.read_bytes()), "maximum_bytes": 4 * 1024 * 1024})
    config = {"schema": 1, "scope": "engineering", "source_commit": "3" * 40, "controller_digest": digest_bytes(documents["controller"]), "verifier_digest": evaluation_verifier.verifier_source_digest(), "settings_digest": "1" * 64, "permissions_digest": "2" * 64, "seed": 1234, "repeats": repeats, "resamples": 10000, "confidence": 0.95, "max_pair_retries": retries, "retry_statuses": ["blocked"] if retries else [], "concurrency": 2, "record_bytes": 4 * 1024 * 1024, "trace_bytes": 16 * 1024 * 1024, "trace_events": 1000, "artifact_limits": asdict(limits), "verifier_limits": {"max_cases": 10, "max_effects": 10, "private_receipt_bytes": 4 * 1024 * 1024}, "owner": {"run_id": "engineering-run", "run_attempt": "1", "job_id": "engineering-job"}, "gateway": gateway, "preflight_gateway": preflight_gateway, "usage_budgets": {"input_tokens": None, "output_tokens": None, "total_tokens": None, "cost_usd": None}, "files": files, "independence": "provided_unattested"}
    path = tmp_path / "manifest.json"
    save(path, config)
    return path, config, documents


def update_document(path, config, name, value):
    ref = next(item for item in config["files"] if item["name"] == name)
    save(Path(ref["path"]), value)
    ref["sha256"] = digest_bytes(Path(ref["path"]).read_bytes())
    save(path, config)


def test_strict_freeze_is_deeply_immutable_and_alternates_pairs(tmp_path):
    path, config, _ = fixture_inputs(tmp_path)
    manifest = load_manifest(path, expected_sha256=digest_bytes(path.read_bytes()))
    view = manifest.config
    view["seed"] = 999
    assert manifest.config["seed"] == 1234
    state = prepare_run(manifest, tmp_path / "run")
    assert state.schedule[0][2] == tuple(reversed(state.schedule[1][2]))
    first_bytes = (state.run_dir / "manifest.json").read_bytes()
    prepare_run(manifest, state.run_dir)
    assert (state.run_dir / "manifest.json").read_bytes() == first_bytes
    changed = copy.deepcopy(config)
    changed["seed"] += 1
    save(path, changed)
    with pytest.raises(EvaluationError, match="PUBLICATION_UNCERTAIN"):
        prepare_run(load_manifest(path), state.run_dir)
    assert (state.run_dir / "manifest.json").read_bytes() == first_bytes


@pytest.mark.parametrize("field,value", [("seed", True), ("repeats", 4), ("confidence", 0.9), ("resamples", 100), ("concurrency", 0), ("independence", "attested"), ("scope", "evaluation")])
def test_malformed_or_reduced_original_freeze_is_refused(tmp_path, field, value):
    path, config, _ = fixture_inputs(tmp_path)
    config[field] = value
    save(path, config)
    with pytest.raises((ValueError, TypeError)):
        load_manifest(path)


def test_duplicate_json_and_unfrozen_file_drift_are_refused(tmp_path):
    path, config, _ = fixture_inputs(tmp_path)
    raw = path.read_bytes()
    path.write_bytes(b'{"schema":1,' + raw[1:])
    with pytest.raises(ValueError):
        load_manifest(path)
    save(path, config)
    ref = next(item for item in config["files"] if item["name"] == "prompt")
    save(Path(ref["path"]), b"different frozen prompt")
    with pytest.raises(EvaluationError, match="FROZEN_FILE_DIGEST_MISMATCH"):
        load_manifest(path)


def test_symlink_and_hardlink_frozen_inputs_are_refused(tmp_path):
    path, config, _ = fixture_inputs(tmp_path)
    ref = next(item for item in config["files"] if item["name"] == "prompt")
    original = Path(ref["path"])
    linked = original.with_name("linked")
    linked.symlink_to(original)
    ref["path"] = str(linked)
    save(path, config)
    with pytest.raises(OSError):
        load_manifest(path)
    linked.unlink()
    os.link(original, linked)
    with pytest.raises(EvaluationError, match="SINGLE_REGULAR"):
        load_manifest(path)


def test_missing_and_mismatched_pair_contexts_are_refused(tmp_path):
    path, config, documents = fixture_inputs(tmp_path)
    workload = copy.deepcopy(documents["workload"])
    workload["invocations"].pop()
    update_document(path, config, "workload", workload)
    with pytest.raises(EvaluationError, match="MISSING_FROZEN_INVOCATION"):
        load_manifest(path)
    workload = copy.deepcopy(documents["workload"])
    workload["invocations"][-1]["native"]["max_stdout_bytes"] += 1
    update_document(path, config, "workload", workload)
    with pytest.raises(EvaluationError, match="PAIRED_NATIVE_BUDGET"):
        load_manifest(path)


def test_preflight_cannot_mutate_the_measured_corpus_binding(tmp_path):
    path, config, _ = fixture_inputs(tmp_path)
    config["preflight_gateway"] = config["gateway"]
    save(path, config)
    with pytest.raises(EvaluationError, match="PREFLIGHT_MUST_NOT_MUTATE"):
        load_manifest(path)


def test_gold_anchors_bind_original_utf8_bytes_and_revision(tmp_path):
    path, config, documents = fixture_inputs(tmp_path)
    body = "한국어 조건".encode()
    corpus = {"schema": 2, "sources": [{"source_id": "source_one", "revision": 2, "body": b64(body),
              "sha256": digest_bytes(body), "inspection_windows": [
                  {"byte_start": 0, "byte_end": len(body), "window_digest": "a" * 64}]}], "claims": [], "relations": []}
    config["gateway"]["approved_refs"] = ["source_one"]
    update_document(path, config, "corpus", corpus)
    gold = copy.deepcopy(documents["gold"])
    gold["cases"][0]["grounding_refs"] = [{"source_id": "source_one", "revision": 2, "byte_start": 0, "byte_end": 9, "quote_digest": digest_bytes(body[:9])}]
    update_document(path, config, "gold", gold)
    assert load_manifest(path).file("gold").sha256
    gold["cases"][0]["grounding_refs"][0]["revision"] = 1
    update_document(path, config, "gold", gold)
    with pytest.raises(EvaluationError, match="GOLD_ANCHOR_MISMATCH"):
        load_manifest(path)


def test_control_witness_must_preserve_retained_bytes_before_execution(tmp_path):
    path, config, documents = fixture_inputs(tmp_path)
    correct = json.loads(documents["correct"])
    correct["entries"][1]["content"] = b64(b"damaged\n")
    correct["entries"][1]["size"] = len(b"damaged\n")
    correct["entries"][1]["sha256"] = digest_bytes(b"damaged\n")
    update_document(path, config, "correct", correct)
    with pytest.raises(EvaluationError, match="CONTROL_STRUCTURE_INVALID"):
        load_manifest(path)


def test_private_trace_preserves_every_byte_and_refuses_a_second_writer(tmp_path):
    path, _, _ = fixture_inputs(tmp_path)
    manifest = load_manifest(path)
    state = prepare_run(manifest, tmp_path / "run")
    trace = PrivateTrace(manifest, state.run_dir, "preflight-one", "wire")
    body = bytes(range(256)) + b"\x00private\xff"
    exchange = HttpExchange("exchange", "prepared", "POST", "/api/capture", 10, 11, body, None, None, False, None, None)
    trace({"stage": "gateway_wire", "exchange": exchange})
    record = json.loads((state.run_dir / "traces/preflight-one/wire/00000000.json").read_bytes())
    encoded = record["event"]["exchange"]["request_body"]
    assert base64.b64decode(encoded["$bytes"], validate=True) == body
    assert encoded["sha256"] == digest_bytes(body)
    assert record["event"]["exchange"]["response_body"] is None
    assert b"private" not in canonical_bytes(encoded)
    with pytest.raises(FileExistsError):
        PrivateTrace(manifest, state.run_dir, "preflight-one", "wire")


def test_trace_overflow_is_durable_and_never_silently_truncated(tmp_path):
    path, config, _ = fixture_inputs(tmp_path)
    config["trace_bytes"] = 1024
    save(path, config)
    manifest = load_manifest(path)
    state = prepare_run(manifest, tmp_path / "run")
    trace = PrivateTrace(manifest, state.run_dir, "preflight-one", "wire")
    with pytest.raises(EvaluationError, match="PRIVATE_TRACE_BOUND"):
        trace({"body": b"x" * 2048})
    marker = json.loads((state.run_dir / "traces/preflight-one/wire/overflow.json").read_bytes())
    assert marker["code"] == "PRIVATE_TRACE_BOUND"
    assert not (state.run_dir / "traces/preflight-one/wire/00000000.json").exists()


def test_stopped_run_accounts_all_originals_and_all_explicit_pair_retries(tmp_path):
    path, _, _ = fixture_inputs(tmp_path, retries=1)
    manifest = load_manifest(path)
    stop = threading.Event()
    stop.set()
    report = run_evaluation(manifest, tmp_path / "run", stop_event=stop)
    protocol, arms, retrieval = load_report_inputs(tmp_path / "run")
    assert protocol.scope == "engineering"
    assert len(arms) == 4
    assert all(arm.functional_success is None and arm.cost_usd is None for arm in arms)
    assert len(retrieval) == 2
    assert all(row.returned_claim_ids is None and row.manifest_complete is None for row in retrieval)
    assert report["controller"]["preflight"]["status"] == "aborted"
    assert report["controller"]["original18_completed"] == 0
    assert b"engineering fixture identity" not in canonical_bytes(report)
    before = {file.name: file.read_bytes() for file in (tmp_path / "run/ledger").iterdir()}
    run_evaluation(manifest, tmp_path / "run", stop_event=stop)
    after = {file.name: file.read_bytes() for file in (tmp_path / "run/ledger").iterdir()}
    assert after == before


def test_crash_intent_is_reported_unknown_and_native_effect_is_never_replayed(tmp_path):
    path, _, _ = fixture_inputs(tmp_path)
    manifest = load_manifest(path)
    state = prepare_run(manifest, tmp_path / "run")
    invocation = manifest.workload["invocations"][0]
    assert evaluation._intent(manifest, state.run_dir, invocation)
    result = evaluation._run_one(manifest, state.run_dir, invocation, enabled=True)
    assert result["status"] == "unknown"
    assert result["code"] == "CRASH_INTENT_NO_REPLAY"
    assert not Path(invocation["native"]["cwd"]).exists()
    assert not (state.run_dir / "artifacts/preflight-one.submission.json").exists()
    protocol, arms, retrieval = load_report_inputs(state.run_dir)
    assert protocol.manifest_digest == manifest.digest
    assert all(arm.status == "not_started" for arm in arms)
    assert all(item.returned_claim_ids is None for item in retrieval)


def test_interrupted_private_writer_intent_is_readable_without_replay(tmp_path, monkeypatch):
    path, _, _ = fixture_inputs(tmp_path)
    manifest = load_manifest(path)
    state = prepare_run(manifest, tmp_path / "run")
    invocation = manifest.workload["invocations"][0]
    ledger = state.run_dir / "ledger"
    identity = ledger.stat()
    original_unlink = os.unlink

    class PowerLoss(BaseException):
        pass

    def interrupt_cleanup(name, *, dir_fd=None):
        if dir_fd is not None and str(name).startswith(".memory-private-"):
            parent = os.fstat(dir_fd)
            if (parent.st_dev, parent.st_ino) == (identity.st_dev, identity.st_ino):
                raise PowerLoss()
        return original_unlink(name, dir_fd=dir_fd)

    with monkeypatch.context() as patch:
        patch.setattr(os, "unlink", interrupt_cleanup)
        with pytest.raises(PowerLoss):
            evaluation._intent(manifest, state.run_dir, invocation)

    intent = ledger / (evaluation._key(invocation["invocation_id"]) + ".intent.json")
    temporary = next(ledger.glob(".memory-private-*"))
    assert intent.stat().st_nlink == temporary.stat().st_nlink == 2
    retained = {item.name: (item.read_bytes(), item.stat().st_nlink) for item in ledger.iterdir()}
    before = evaluation.report_evaluation(state.run_dir)
    assert before["controller"]["preflight"]["status"] == "unknown"
    assert before["controller"]["preflight"]["code"] == "CRASH_INTENT_NO_TERMINAL"
    assert retained == {item.name: (item.read_bytes(), item.stat().st_nlink) for item in ledger.iterdir()}

    resumed = run_evaluation(manifest, state.run_dir)
    assert resumed["controller"]["preflight"]["status"] == "unknown"
    assert resumed["controller"]["preflight"]["code"] == "CRASH_INTENT_NO_REPLAY"
    assert intent.stat().st_nlink == 1
    assert not temporary.exists()
    assert not Path(invocation["native"]["cwd"]).exists()
    assert not (state.run_dir / "artifacts/preflight-one.submission.json").exists()


def test_report_projection_survives_missing_original_inputs(tmp_path):
    path, config, _ = fixture_inputs(tmp_path)
    manifest = load_manifest(path)
    state = prepare_run(manifest, tmp_path / "run")
    for ref in config["files"]:
        Path(ref["path"]).unlink()
    path.unlink()
    protocol, arms, retrieval = load_report_inputs(state.run_dir)
    assert protocol.manifest_digest == manifest.digest
    assert len(arms) == 4 and len(retrieval) == 2
    assert all(arm.cost_usd is None and arm.input_tokens is None and arm.cleanup_complete is None for arm in arms)


async def test_controller_builds_real_required_only_gateway_with_wire_evidence(authority, tmp_path):
    async with actual_upstream(authority, tmp_path) as (agent, producer):
        endpoint = asdict(agent.endpoint)
        endpoint["state_dir"] = str(endpoint["state_dir"])
        endpoint["health_receipt"] = None
        config_gateway = {"route_ref": "engineering-coding-route", "binding_id": authority.binding_id, "agent": {"endpoint": endpoint, "token_file": str(agent.token_file), "approval_ref": agent.approval_ref}, "producer": {"endpoint": endpoint, "token_file": str(producer.token_file), "approval_ref": producer.approval_ref}, "approved_upstream_urls": [agent.endpoint.base_url], "approved_refs": [], "protocol_version": "2025-11-25", "max_calls": 100, "max_trace_bytes": 4 * 1024 * 1024, "required_request": {"binding_id": authority.binding_id, "query": "CacheKey offline", "max_bytes": 6144, "limit": 3}, "lifetime_seconds": 5.0, "rules_file": "rules"}
        path, _, _ = fixture_inputs(tmp_path, gateway=config_gateway)
        manifest = load_manifest(path)
        state = prepare_run(manifest, tmp_path / "run")
        invocation = evaluation._select(manifest, "retrieval", "no-match", "required_only")
        assert evaluation._intent(manifest, state.run_dir, invocation)
        params = StdioServerParameters(command=sys.executable, args=[
            "-m", "agents_memory.cli", "evaluation", "gateway", "--manifest", str(path),
            "--run-dir", str(state.run_dir), "--invocation-id", invocation["invocation_id"],
            "--expected-sha256", manifest.digest,
        ])
        with (tmp_path / "gateway-stderr.private").open("x") as errors:
            Path(errors.name).chmod(0o600)
            async with stdio_client(params, errlog=errors) as streams:
                async with ClientSession(*streams, read_timeout_seconds=5.0) as client:
                    await client.initialize()
                    result = await client.call_tool("memory_required_context", config_gateway["required_request"])
                    assert not result.is_error
                    assert json.loads(result.content[0].text)["stamp"]["rules"] == []
                    denied = await client.call_tool("memory_inspect", {"ref": "optional-secret"})
                    assert denied.is_error
                    assert json.loads(denied.content[0].text)["error"]["code"] == "OPTIONAL_TOOL_DENIED"
        events = evaluation._trace_events(manifest, state.run_dir, invocation["invocation_id"], "gateway")
        responses = [event["exchange"] for event in events if event["stage"] == "gateway_wire" and event["exchange"]["stage"] == "response"]
        assert responses and {item["path"] for item in responses} == {"/api/required-context"}
        assert all(item["http_status"] == 200 for item in responses)
        assert all(b"optional-secret" not in evaluation._unbytes(item["request_body"]) for item in responses)
        receipt, _ = evaluation._gateway_receipt(manifest, state.run_dir, invocation)
        assert receipt["required_reads"] and receipt["final_reads"] == []
        with pytest.raises(FileExistsError):
            build_gateway(manifest, invocation["invocation_id"], state.run_dir)


def test_explicit_retry_creates_new_pair_attempt_without_erasing_blocked_originals(tmp_path):
    path, _, _ = fixture_inputs(tmp_path, retries=1)
    manifest = load_manifest(path)
    state = prepare_run(manifest, tmp_path / "run")
    for item in state.schedule:
        evaluation._run_pair(manifest, state.run_dir, item, False, None)
    _, arms, _ = load_report_inputs(state.run_dir)
    assert len(arms) == 8
    assert {arm.pair_attempt for arm in arms} == {0, 1}
    assert all(arm.status == "blocked" and arm.functional_success is None for arm in arms)
    assert len({arm.invocation_id for arm in arms}) == 8
    original = {file.name: file.read_bytes() for file in (state.run_dir / "ledger").iterdir()}
    for item in state.schedule:
        evaluation._run_pair(manifest, state.run_dir, item, False, None)
    assert original == {file.name: file.read_bytes() for file in (state.run_dir / "ledger").iterdir()}


def _actual_preflight_channel(agent, producer):
    endpoint = asdict(agent.endpoint)
    endpoint["state_dir"] = str(endpoint["state_dir"])
    return {"route_ref": "engineering-preflight-route", "binding_id": agent.binding_id,
            "agent": {"endpoint": endpoint, "token_file": str(agent.token_file), "approval_ref": agent.approval_ref},
            "producer": {"endpoint": endpoint, "token_file": str(producer.token_file), "approval_ref": producer.approval_ref},
            "approved_upstream_urls": [agent.endpoint.base_url], "approved_refs": [], "protocol_version": "2025-11-25",
            "max_calls": 200, "max_trace_bytes": 4 * 1024 * 1024,
            "required_request": {"binding_id": agent.binding_id, "query": "CacheKey offline", "max_bytes": 6144, "limit": 3},
            "lifetime_seconds": 5.0, "rules_file": "preflight_rules"}


def _controller_peer(manifest_path, run_dir, complete, *, invocation_id="preflight-one", final_empty=False, event_mode="valid"):
    return f'''import asyncio, hashlib, json, os, pathlib, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from agents_memory.evaluation import load_manifest
assert sys.argv[1:] == ['app-server']
def read():
    return json.loads(sys.stdin.readline())
def emit(value):
    print(json.dumps(value), flush=True)
def reply(request, result):
    emit({{'id': request['id'], 'result': result}})
request = read()
assert request['method'] == 'initialize'
reply(request, {{'userAgent': 'engineering-controller-peer'}})
assert read()['method'] == 'initialized'
request = read()
assert request['method'] == 'thread/start' and set(request['params']) == {{'cwd'}}
reply(request, {{'thread': {{'id': 'engineering-thread'}}, 'model': 'engineering-peer-model',
                'approvalPolicy': 'on-request', 'sandbox': 'workspace-write'}})
request = read()
assert request['method'] == 'turn/start'
reply(request, {{'turn': {{'id': 'engineering-turn'}}}})
manifest_path = pathlib.Path({str(manifest_path)!r})
manifest = load_manifest(manifest_path)
run_dir = pathlib.Path({str(run_dir)!r})
identity = {invocation_id!r}
selected_invocation = next(item for item in manifest.workload['invocations'] if item['invocation_id'] == identity)
channel = manifest.config['preflight_gateway' if selected_invocation['phase'] == 'preflight' else 'gateway']
mapping = next(item for item in manifest.document('native_tool_mapping')['routes'] if item['route_ref'] == channel['route_ref'])
event_mode = {event_mode!r}
if event_mode in ('model-reroute', 'model-roundtrip'):
    emit({{'method': 'model/rerouted', 'params': {{'threadId': 'engineering-thread', 'turnId': 'engineering-turn',
          'fromModel': 'engineering-peer-model', 'toModel': 'other-model', 'reason': 'highRiskCyberActivity'}}}})
    if event_mode == 'model-roundtrip':
        emit({{'method': 'model/rerouted', 'params': {{'threadId': 'engineering-thread', 'turnId': 'engineering-turn',
              'fromModel': 'other-model', 'toModel': 'engineering-peer-model', 'reason': 'highRiskCyberActivity'}}}})
action_count = 0
async def exercise():
    params = StdioServerParameters(command=sys.executable, args=[
        '-m', 'agents_memory.cli', 'evaluation', 'gateway', '--manifest', str(manifest_path),
        '--run-dir', str(run_dir), '--invocation-id', identity, '--expected-sha256', manifest.digest,
    ], env=dict(os.environ))
    with (pathlib.Path.cwd() / 'gateway-stderr.private').open('x') as errors:
        os.chmod(errors.name, 0o600)
        async with stdio_client(params, errlog=errors) as streams:
            async with ClientSession(*streams, read_timeout_seconds=5.0) as client:
                await client.initialize()
                async def call(name, arguments):
                    global action_count
                    action_count += 1
                    action_id = 'native-action-' + str(action_count)
                    native_arguments = {{**arguments, 'query': 'not-the-dispatched-query'}} if event_mode == 'arguments' else arguments
                    server = 'unrelated-server' if event_mode == 'server' else mapping['server']
                    item = {{'type': 'mcpToolCall', 'id': action_id, 'server': server,
                            'tool': mapping['tools'][name], 'arguments': native_arguments,
                            'status': 'inProgress', 'result': None, 'error': None}}
                    scope = {{'threadId': 'engineering-thread', 'turnId': 'engineering-turn'}}
                    if event_mode != 'missing':
                        emit({{'method': 'item/started', 'params': {{**scope, 'item': item}}}})
                        if event_mode == 'duplicate':
                            emit({{'method': 'item/started', 'params': {{**scope, 'item': item}}}})
                    meta = {{'callId': 'foreign-action' if event_mode == 'call-id-meta' else action_id,
                            'threadId': 'foreign-thread' if event_mode == 'foreign-meta' else 'engineering-thread'}}
                    response = await client.call_tool(name, arguments, meta=meta)
                    assert not response.is_error
                    content = [entry.model_dump(mode='json', by_alias=True, exclude_none=True) for entry in response.content]
                    if event_mode == 'result':
                        content = [{{'type': 'text', 'text': '{{"not":"the-dispatched-result"}}'}}]
                    if event_mode != 'missing':
                        item = {{**item, 'status': 'completed', 'result': {{'content': content, 'structuredContent': None, '_meta': None}}}}
                        emit({{'method': 'item/completed', 'params': {{**scope, 'item': item}}}})
                    return json.loads(response.content[0].text)
                async def inspect(ref):
                    offset, collected = 0, bytearray()
                    while True:
                        payload = await call('memory_inspect', {{'ref': ref, 'byte_start': offset, 'max_bytes': 4096}})
                        window = payload.get('draft_window')
                        if window is None:
                            return payload
                        assert window['byte_start'] == len(collected)
                        collected.extend(window['body'].encode())
                        offset = window['next_byte']
                        if offset is None:
                            assert hashlib.sha256(collected).hexdigest() == window['digest']
                            return json.loads(collected)
                await call('memory_required_context', channel['required_request'])
                if event_mode == 'valid':
                    await call('memory_required_context', channel['required_request'])
                if {complete!r}:
                    key = hashlib.sha256(identity.encode()).hexdigest()
                    capture = json.loads((run_dir / 'ledger' / (key + '.capture.json')).read_bytes())
                    source = capture['source_pointer']['source_id']
                    window = await call('memory_inspect', {{'ref': source}})
                    span = window['span_inventory'][0]
                    selection = await call('memory_record', {{
                        'kind': 'source_selection', 'idempotency_key': 'engineering-controller-selection',
                        'admission_id': window['admission_id'], 'source_id': source,
                        'source_revision': window['source_revision'], 'binding_revision': window['binding_revision'],
                        'byte_start': window['byte_start'], 'byte_end': window['byte_end'], 'window_digest': window['window_digest'],
                        'policy_revision': window['policy_revision'], 'policy_epoch': window['policy_epoch'],
                        'label': 'remember', 'coverage': 'complete_window', 'reason': 'Deterministic engineering peer, not live-model judgment.',
                        'extraction': {{'claims': [{{'assertion_id': 'a0000', 'assertion_span_id': span['span_id'],
                            'statement': span['quote'], 'kind': 'fact', 'subject': 'CacheKey', 'predicate': 'retained',
                            'object': 'offline', 'polarity': 'positive', 'modality': 'asserted', 'entities': ['CacheKey']}}],
                            'individual_qualifications': [{{'assertion_id': 'a0000', 'kind': 'condition', 'phrase': 'only offline',
                                'evidence_span_id': span['span_id']}}], 'shared_qualifications': [], 'validities': [],
                            'unused_span_ids': [item['span_id'] for item in window['span_inventory'] if item['span_id'] != span['span_id']]}}
                    }})
                    selected = await inspect(selection['artifact_id'])
                    for claim_id in selected['claim_ids']:
                        await inspect(claim_id)
                    recall = manifest.workload['preflight']['recall_request']
                    candidates = await call('memory_context', recall)
                    for item in candidates['candidate_manifest']:
                        await inspect(item['inspection_ref'])
                    final_request = {{**recall, 'admission_id': candidates['admission_id'],
                        'relevance': [{{'claim_id': item['claim_id'], 'relevant': True,
                                       'reason': 'Engineering peer checks actual qualified final delivery.'}}
                                      for item in candidates['candidate_manifest']]}}
                    final = await call('memory_context', final_request)
                    if event_mode == 'receipt-bound':
                        for _ in range(12):
                            final = await call('memory_context', final_request)
                    assert final['judgment_required'] is False
                if {final_empty!r}:
                    await call('memory_context', manifest.workload['retrieval'][0]['request'])
asyncio.run(exercise())
submission = pathlib.Path.cwd() / 'submission.json'
submission.write_bytes(manifest.file('baseline').raw)
emit({{'method': 'thread/tokenUsage/updated', 'params': {{'threadId': 'engineering-thread',
      'tokenUsage': {{'total': {{'inputTokens': 12, 'outputTokens': 3}}, 'last': {{}}}}}}}})
emit({{'method': 'item/completed', 'params': {{'threadId': 'engineering-thread', 'turnId': 'engineering-turn',
      'item': {{'type': 'agentMessage', 'id': 'engineering-message', 'text': json.dumps({{'submission_path': str(submission)}})}}}}}})
emit({{'method': 'turn/completed', 'params': {{'threadId': 'engineering-thread',
      'turn': {{'id': 'engineering-turn', 'status': 'completed'}}}}}})
sys.stdin.read()
'''



@pytest.mark.parametrize("complete", [True, False])
async def test_actual_controller_producer_native_peer_mcp_preflight_is_not_functional_success(authority, tmp_path, complete):
    async with actual_upstream(authority, tmp_path) as (agent, producer):
        path = tmp_path / "manifest.json"
        run_dir = tmp_path / "run"
        peer = _controller_peer(path, run_dir, complete)
        path, _, _ = fixture_inputs(tmp_path, repeats=1, preflight_gateway=_actual_preflight_channel(agent, producer), peer=peer)
        manifest = load_manifest(path)
        state = prepare_run(manifest, run_dir)
        invocation = manifest.workload["invocations"][0]
        result = await asyncio.to_thread(evaluation._run_one, manifest, state.run_dir, invocation, enabled=True)
        assert result["status"] == ("completed" if complete else "incomplete")
        assert result["functional_success"] is None and result["structural_pass"] is None
        assert result["cleanup_complete"] is None
        assert result["cost_usd"] is None
        assert result["input_tokens"] == 12 and result["output_tokens"] == 3
        producer_events = evaluation._trace_events(manifest, state.run_dir, "preflight-one", "producer")
        captures = [event["exchange"] for event in producer_events if event["stage"] == "gateway_wire" and event["exchange"]["stage"] == "response"]
        assert len(captures) == 1 and captures[0]["http_status"] == 202
        assert captures[0]["path"] == "/api/capture"
        native_record = json.loads((state.run_dir / "ledger" / (digest_bytes(b"preflight-one") + ".native.json")).read_bytes())
        assert native_record["status"] == "completed"
        assert native_record["identity"]["thread_id"] == "engineering-thread"
        assert base64.b64decode(native_record["stdout"]["$bytes"])
        if complete:
            assert result["comparable"] is True
            receipt, deliveries = evaluation._gateway_receipt(manifest, state.run_dir, invocation)
            foreign = copy.deepcopy(native_record)
            foreign["invocation_id"] = "retrieval-memory_on"
            with pytest.raises(evaluation.EvaluationError, match="NATIVE_TOOL_INVOCATION_MISMATCH"):
                evaluation._native_tool_link(manifest, invocation, foreign, receipt, deliveries)
            foreign = copy.deepcopy(native_record)
            foreign["identity"]["thread_id"] = "another-native-invocation"
            with pytest.raises(evaluation.EvaluationError, match="NATIVE_TOOL_GENERATION_MISMATCH"):
                evaluation._native_tool_link(manifest, invocation, foreign, receipt, deliveries)
            foreign_deliveries = copy.deepcopy(deliveries)
            next(iter(foreign_deliveries.values()))["event"]["invocation_id"] = "retrieval-memory_on"
            with pytest.raises(evaluation.EvaluationError, match="NATIVE_TOOL_GATEWAY_SCOPE_MISMATCH"):
                evaluation._native_tool_link(manifest, invocation, native_record, receipt, foreign_deliveries)
        else:
            assert not result["comparable"]
            assert "PRODUCER_NATIVE_MCP_PIPELINE_INCOMPLETE" in result["comparability_reasons"]


@pytest.mark.parametrize("event_mode", ["model-reroute", "model-roundtrip"])
async def test_actual_controller_does_not_stamp_frozen_identity_after_model_reroute(authority, tmp_path, event_mode):
    async with actual_upstream(authority, tmp_path) as (agent, producer):
        path, run_dir = tmp_path / "manifest.json", tmp_path / "run"
        peer = _controller_peer(path, run_dir, True, event_mode=event_mode)
        path, _, _ = fixture_inputs(tmp_path, repeats=1, preflight_gateway=_actual_preflight_channel(agent, producer), peer=peer)
        manifest = load_manifest(path)
        state = prepare_run(manifest, run_dir)
        invocation = manifest.workload["invocations"][0]
        result = await asyncio.to_thread(evaluation._run_one, manifest, state.run_dir, invocation, enabled=True)
        assert result["status"] == "completed"
        assert result["comparable"] is False
        assert result["native_identity_observed"] is False
        assert result["native_identity_digest"] is None
        prefix = state.run_dir / "ledger" / digest_bytes(invocation["invocation_id"].encode())
        native = json.loads(prefix.with_suffix(".native.json").read_bytes())
        gateway = json.loads(prefix.with_suffix(".gateway.json").read_bytes())
        assert native["status"] == "completed" and native["comparable"] is False
        assert native["identity"]["resolved"]["model"] == "engineering-peer-model"
        assert native["artifact_bundle"]["sha256"] == digest_bytes(manifest.file("baseline").raw)
        assert gateway["observation_complete"] is True and gateway["final_reads"]
        assert result["input_tokens"] == 12 and result["output_tokens"] == 3
        assert result["cost_usd"] is None


async def test_actual_bounded_gateway_completion_preserves_terminal_and_later_attempts(authority, tmp_path):
    async with actual_upstream(authority, tmp_path) as (agent, producer):
        path, run_dir = tmp_path / "manifest.json", tmp_path / "run"
        peer = _controller_peer(path, run_dir, True, event_mode="receipt-bound")
        path, config, _ = fixture_inputs(
            tmp_path, repeats=1, preflight_gateway=_actual_preflight_channel(agent, producer), peer=peer,
        )
        config["record_bytes"] = 44032
        save(path, config)
        manifest = load_manifest(path)
        await asyncio.to_thread(run_evaluation, manifest, run_dir)
        invocation = manifest.workload["invocations"][0]
        terminal = evaluation._read_terminal(manifest, run_dir, invocation)
        assert terminal["status"] == "completed", {
            "code": terminal["code"], "reasons": terminal["comparability_reasons"],
            "gateway_bytes": next((item.stat().st_size for item in (run_dir / "ledger").glob("*.gateway.json")), None),
            "largest_trace_record": max(item.stat().st_size for item in (run_dir / "traces").rglob("*.json")),
        }
        receipt, _ = evaluation._gateway_receipt(manifest, run_dir, invocation)
        assert terminal["comparable"] is True
        assert terminal["native_identity_observed"] is True
        assert terminal["evidence_refs"]["gateway"] == digest_bytes(canonical_bytes(receipt))
        _, arms, retrieval = load_report_inputs(run_dir)
        assert [(row.status, row.comparable) for row in (*arms, *retrieval)] == [("blocked", False)] * 4
        gateway_path = run_dir / "ledger" / (digest_bytes(invocation["invocation_id"].encode()) + ".gateway.json")
        save(gateway_path, {**receipt, "mode": "required_only"})
        with pytest.raises(EvaluationError, match="GATEWAY_RECEIPT_IDENTITY_DRIFT"):
            load_report_inputs(run_dir)


@pytest.mark.parametrize("event_mode", ["missing", "arguments", "result", "server", "duplicate", "foreign-meta", "call-id-meta"])
async def test_actual_native_completion_cannot_credit_unlinked_gateway_delivery(authority, tmp_path, event_mode):
    async with actual_upstream(authority, tmp_path) as (agent, producer):
        path, run_dir = tmp_path / "manifest.json", tmp_path / "run"
        peer = _controller_peer(path, run_dir, True, event_mode=event_mode)
        path, _, _ = fixture_inputs(tmp_path, repeats=1, preflight_gateway=_actual_preflight_channel(agent, producer), peer=peer)
        manifest = load_manifest(path)
        state = prepare_run(manifest, run_dir)
        invocation = manifest.workload["invocations"][0]
        result = await asyncio.to_thread(evaluation._run_one, manifest, state.run_dir, invocation, enabled=True)
        prefix = state.run_dir / "ledger" / digest_bytes(invocation["invocation_id"].encode())
        native = json.loads(prefix.with_suffix(".native.json").read_bytes())
        gateway = json.loads(prefix.with_suffix(".gateway.json").read_bytes())
        assert native["status"] == "completed" and native["comparable"] is True
        assert gateway["observation_complete"] is True and gateway["final_reads"]
        assert result["status"] == "incomplete" and result["comparable"] is False
        assert any(reason.startswith("NATIVE_TOOL_") for reason in result["comparability_reasons"])
        assert "native_tool_link" not in result["evidence_refs"]


async def test_controller_uses_real_verifier_controls_and_blocks_unprepared_runtime_before_native(authority, tmp_path):
    async with actual_upstream(authority, tmp_path) as (agent, producer):
        coding = _actual_preflight_channel(agent, producer)
        coding["route_ref"] = "engineering-coding-route"
        coding["rules_file"] = "rules"
        path, _, _ = fixture_inputs(tmp_path, repeats=1, gateway=coding)
        manifest = load_manifest(path)
        state = prepare_run(manifest, tmp_path / "run")
        invocations = [evaluation._select(manifest, "coding", "coding-one", mode, 0, 0)
                       for mode in ("memory_on", "required_only")]
        await asyncio.to_thread(evaluation._run_pair, manifest, state.run_dir,
                                ("coding-one", 0, ("memory_on", "required_only")), True, threading.Event())
        results = [evaluation._read_terminal(manifest, state.run_dir, invocation) for invocation in invocations]
        for result, invocation in zip(results, invocations, strict=True):
            assert result["status"] == "blocked"
            assert result["functional_success"] is None
            assert not Path(invocation["native"]["cwd"]).exists()
        pair_id = evaluation._pair_verifier_id(manifest, invocations[0])
        controls = json.loads((state.run_dir / "ledger" / (pair_id + ".controls.json")).read_bytes())
        assert controls["eligible"] is False
        assert [item["role"] for item in controls["receipts"]] == [
            "control_correct", "control_noop", "control_plausible_wrong"]
        assert all(not item["success"] for item in controls["receipts"])
        assert results[0]["required_rules_digest"] == results[1]["required_rules_digest"] == manifest.file("rules").sha256
        assert all(result["corpus_before_digest"] == result["corpus_after_digest"] == manifest.file("corpus").sha256 for result in results)


def test_omitted_retry_policy_is_zero_and_does_not_add_attempts(tmp_path):
    path, config, _ = fixture_inputs(tmp_path)
    del config["max_pair_retries"]
    del config["retry_statuses"]
    save(path, config)
    manifest = load_manifest(path)
    assert manifest.config["max_pair_retries"] == 0
    assert manifest.config["retry_statuses"] == []
    state = prepare_run(manifest, tmp_path / "run")
    _, arms, _ = load_report_inputs(state.run_dir)
    assert len(arms) == 4 and {arm.pair_attempt for arm in arms} == {0}


def test_supplied_control_approval_digests_cannot_be_rebound_by_the_controller(tmp_path):
    path, config, documents = fixture_inputs(tmp_path)
    workload = copy.deepcopy(documents["workload"])
    workload["tasks"][0]["approved_task_digest"] = "f" * 64
    update_document(path, config, "workload", workload)
    with pytest.raises(EvaluationError, match="SUPPLIED_CONTROL_APPROVAL_IDENTITY_MISMATCH"):
        load_manifest(path)


@pytest.mark.parametrize("unsupported", [False, True])
def test_native_context_or_capability_refusal_precedes_producer_effects(tmp_path, unsupported):
    path, config, documents = fixture_inputs(tmp_path)
    workload = copy.deepcopy(documents["workload"])
    spec = workload["invocations"][0]["native"]
    if unsupported:
        spec.update(strict_protection_required=True, strict_protection_supported=False)
    else:
        spec["approved_context"] = False
    update_document(path, config, "workload", workload)
    manifest = load_manifest(path)
    state = prepare_run(manifest, tmp_path / "run")
    invocation = manifest.workload["invocations"][0]
    result = evaluation._run_one(manifest, state.run_dir, invocation, enabled=True)
    assert result["status"] == ("unsupported" if unsupported else "blocked")
    assert result["functional_success"] is None
    assert not (state.run_dir / "traces/preflight-one").exists()
    assert not Path(spec["cwd"]).exists()


def test_generation_claims_reject_cross_arm_reuse_without_overwriting_evidence(tmp_path):
    path, _, _ = fixture_inputs(tmp_path)
    manifest = load_manifest(path)
    state = prepare_run(manifest, tmp_path / "run")
    receipt = evaluation._claim_generation(manifest, state.run_dir, "first-arm", "engineering-generation")
    before = {file.name: file.read_bytes() for file in (state.run_dir / "ledger").iterdir()}
    with pytest.raises(EvaluationError, match="NATIVE_GENERATION_REUSED"):
        evaluation._claim_generation(manifest, state.run_dir, "second-arm", "engineering-generation")
    assert before == {file.name: file.read_bytes() for file in (state.run_dir / "ledger").iterdir()}
    assert len(receipt) == 64


def test_native_treatment_tool_identity_can_vary_but_model_permissions_cannot(tmp_path):
    path, config, documents = fixture_inputs(tmp_path)
    identity = copy.deepcopy(documents["native_identity"])
    identity["mode_fields"] = {"memory_on": {"resolved.model": "different-model"}, "required_only": {}}
    update_document(path, config, "native_identity", identity)
    with pytest.raises(EvaluationError, match="NATIVE_TREATMENT_FIELDS"):
        load_manifest(path)


async def test_actual_empty_candidate_response_is_a_final_read_not_missing_data(authority, tmp_path):
    async with actual_upstream(authority, tmp_path) as (agent, producer):
        coding = _actual_preflight_channel(agent, producer)
        coding["route_ref"] = "engineering-coding-route"
        coding["rules_file"] = "rules"
        path, run_dir = tmp_path / "manifest.json", tmp_path / "run"
        peer = _controller_peer(path, run_dir, False, invocation_id="retrieval-memory_on", final_empty=True)
        path, _, _ = fixture_inputs(tmp_path, repeats=1, gateway=coding, peer=peer)
        manifest = load_manifest(path)
        state = prepare_run(manifest, run_dir)
        invocation = evaluation._select(manifest, "retrieval", "no-match", "memory_on")
        result = await asyncio.to_thread(evaluation._run_one, manifest, state.run_dir, invocation, enabled=True)
        assert result["status"] == "completed"
        _, _, retrieval = load_report_inputs(state.run_dir)
        observed = next(row for row in retrieval if row.mode == "memory_on")
        missing = next(row for row in retrieval if row.mode == "required_only")
        assert observed.returned_claim_ids == ()
        assert observed.grounding_refs == ()
        assert observed.manifest_complete is True
        assert observed.final_context_digest and observed.comparable
        assert missing.returned_claim_ids is None and missing.manifest_complete is None


async def test_frozen_fence_rejects_new_applicable_optional_rule(authority, tmp_path):
    async with actual_upstream(authority, tmp_path) as (agent, producer):
        coding = _actual_preflight_channel(agent, producer)
        coding["route_ref"] = "engineering-coding-route"
        coding["rules_file"] = "rules"
        path, _, _ = fixture_inputs(tmp_path, gateway=coding)
        manifest = load_manifest(path)
        state = prepare_run(manifest, tmp_path / "run")
        invocation = evaluation._select(manifest, "retrieval", "no-match", "memory_on")
        await asyncio.to_thread(evaluation._fence, manifest, state.run_dir, invocation, "before")
        proposal = await authority.store.propose_rule(authority.actor, RuleProposal(
            binding_id=authority.binding_id, idempotency_key="frozen-optional-rule",
            body="Preserve the offline condition.", required=False,
        ))
        await authority.store.approve_rule(authority.actor, RuleApproval(
            proposal_id=proposal["proposal_id"], expected_digest=proposal["digest"],
            scope=RuleScope.LOCAL_PROJECT, target_bindings=(authority.binding_id,),
            target_set_revision=proposal["target_set_revision"],
            idempotency_key="frozen-optional-rule-approval",
        ))
        with pytest.raises(EvaluationError):
            await asyncio.to_thread(evaluation._fence, manifest, state.run_dir, invocation, "after")


async def test_frozen_fence_checks_complete_nonempty_relationship_closure(authority, tmp_path):
    async with actual_upstream(authority, tmp_path) as (agent, producer):
        captured = [
            await ready_claim(authority, f"graph-source-{index}",
                              f"CacheKey is retained only offline during audit {index}.")
            for index in range(10)
        ]
        claims = [claim for _, claim in captured]
        for index, right in enumerate(claims[1:]):
            await authority.store.record(
                authority.actor,
                await relation_judgment(authority, claims[0], right, key=f"graph-edge-{index}"),
            )
        claim_keys = (
            "id", "kind", "state", "statement", "evidence", "input_source_ids", "snapshot",
            "interpretation_role", "selection_id", "policy_revision", "revision",
            "awaiting_revalidation", "draft", "judgment_context_refs",
        )
        edge_keys = (
            "id", "kind", "state", "left_id", "right_id", "relation_kind",
            "interpretation_role", "awaiting_revalidation",
        )
        corpus = {"schema": 2, "sources": [], "claims": [], "relations": []}
        for operation, claim in captured:
            window = await authority.store.inspect(authority.actor, authority.binding_id, operation.source_id)
            raw = window["body"].encode()
            corpus["sources"].append({
                "source_id": operation.source_id, "revision": window["source_revision"],
                "body": b64(raw), "sha256": digest_bytes(raw),
                "inspection_windows": [{
                    key: window[key] for key in ("byte_start", "byte_end", "window_digest")
                }],
            })
            view = await authority.store.inspect(authority.actor, authority.binding_id, claim.id)
            health = await authority.store.inspect(authority.actor, authority.binding_id, "health:claim:" + claim.id)
            corpus["claims"].append({
                "ref": claim.id, "projection": {key: view.get(key) for key in claim_keys},
                "health_dependency_digest": health["dependency_digest"],
            })
        judgment = await authority.store.inspect(authority.actor, authority.binding_id, "judgment")
        for ref in sorted(judgment["relation_ids"]):
            view = await authority.store.inspect(authority.actor, authority.binding_id, ref)
            corpus["relations"].append({"ref": ref, "projection": {key: view.get(key) for key in edge_keys}})
        coding = _actual_preflight_channel(agent, producer)
        coding.update(
            route_ref="engineering-coding-route", rules_file="rules",
            approved_refs=sorted(
                [operation.source_id for operation, _ in captured]
                + [claim.id for claim in claims]
                + ["health:claim:" + claim.id for claim in claims]
                + [edge["ref"] for edge in corpus["relations"]]
            ),
        )
        path, config, _ = fixture_inputs(tmp_path, gateway=coding)
        update_document(path, config, "corpus", corpus)
        manifest = load_manifest(path)
        state = prepare_run(manifest, tmp_path / "run")
        invocation = evaluation._select(manifest, "retrieval", "no-match", "memory_on")
        await asyncio.to_thread(evaluation._fence, manifest, state.run_dir, invocation, "before")
        await authority.store.record(
            authority.actor,
            await relation_judgment(authority, claims[1], claims[0], key="new-reverse-edge"),
        )
        with pytest.raises(EvaluationError):
            await asyncio.to_thread(evaluation._fence, manifest, state.run_dir, invocation, "after")


@pytest.mark.parametrize("missing_model", [False, True])
async def test_actual_claude_controller_retains_retrieval_but_refuses_missing_execution_model(
    authority, tmp_path, missing_model,
):
    async with actual_upstream(authority, tmp_path) as (agent, producer):
        coding = _actual_preflight_channel(agent, producer)
        coding.update(route_ref="engineering-coding-route", rules_file="rules")
        path, run_dir = tmp_path / "manifest.json", tmp_path / "run"
        peer = ("manifest_path = " + repr(str(path)) + "\nrun_dir = " + repr(str(run_dir))
            + "\nmissing_model = " + repr(missing_model) + "\n" + '''import asyncio, json, os, pathlib, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from agents_memory.evaluation import load_manifest
sys.stdin.read()
manifest = load_manifest(pathlib.Path(manifest_path))
channel = manifest.config['gateway']
mapping = next(item for item in manifest.document('native_tool_mapping')['routes']
    if item['route_ref'] == channel['route_ref'])
session_id = 'engineering-claude-retrieval'
def emit(value):
    print(json.dumps(value), flush=True)
emit({'type':'system','subtype':'init','session_id':session_id,'model':'engineering-peer-model',
    'claude_code_version':'engineering-controller-peer','permissionMode':'default',
    'tools':sorted(mapping['tools'].values()),
    'mcp_servers':[{'name':mapping['server'],'status':'connected'}]})
async def exercise():
    params = StdioServerParameters(command=sys.executable, args=[
        '-m','agents_memory.cli','evaluation','gateway','--manifest',manifest_path,
        '--run-dir',run_dir,'--invocation-id','retrieval-memory_on','--expected-sha256',manifest.digest],
        env=dict(os.environ))
    with (pathlib.Path.cwd() / 'gateway-stderr.private').open('x') as errors:
        os.chmod(errors.name, 0o600)
        async with stdio_client(params, errlog=errors) as streams:
            async with ClientSession(*streams, read_timeout_seconds=5.0) as client:
                await client.initialize()
                for index, name in enumerate(('memory_required_context','memory_context')):
                    action = 'claude-action-' + str(index)
                    arguments = (channel['required_request'] if index == 0
                        else manifest.workload['retrieval'][0]['request'])
                    message = {'id':'message-' + str(index),'model':'engineering-peer-model',
                        'content':[{'type':'tool_use','id':action,'name':mapping['tools'][name],
                            'input':arguments}]}
                    if missing_model and index == 1:
                        message.pop('model')
                    emit({'type':'assistant','session_id':session_id,'message':message})
                    result = await client.call_tool(name, arguments)
                    assert not result.is_error
                    emit({'type':'user','session_id':session_id,'message':{'content':[{
                        'type':'tool_result','tool_use_id':action,'is_error':False,
                        'content':[entry.model_dump(mode='json',by_alias=True,exclude_none=True)
                            for entry in result.content]}]}})
asyncio.run(exercise())
submission = pathlib.Path.cwd() / 'submission.json'
submission.write_bytes(manifest.file('baseline').raw)
emit({'type':'result','session_id':session_id,'subtype':'success','is_error':False,
    'modelUsage':{'engineering-peer-model':{'inputTokens':12,'outputTokens':3}},
    'structured_output':{'submission_path':str(submission)}})
''')
        path, config, documents = fixture_inputs(tmp_path, repeats=1, gateway=coding, peer=peer)
        workload = documents["workload"]
        for invocation in workload["invocations"]:
            invocation["native"]["backend"] = "claude"
        mapping = documents["native_tool_mapping"]
        mapping["backend"] = "claude"
        for route in mapping["routes"]:
            route["tools"] = {name: "mcp__" + route["server"] + "__" + name for name in route["tools"]}
        tools = mapping["routes"][0]["tools"]
        identity = documents["native_identity"]
        identity.update(backend="claude", fields={
            "model": "engineering-peer-model", "claude_code_version": "engineering-controller-peer",
            "permissionMode": "default", "mcp_servers": [{"name": mapping["routes"][0]["server"], "status": "connected"}]},
            mode_fields={"memory_on": {"tools": sorted(tools.values())},
                "required_only": {"tools": [tools["memory_required_context"]]}})
        for name, value in (("workload", workload), ("native_tool_mapping", mapping), ("native_identity", identity)):
            update_document(path, config, name, value)
        manifest = load_manifest(path)
        state = prepare_run(manifest, run_dir)
        invocation = evaluation._select(manifest, "retrieval", "no-match", "memory_on")
        result = await asyncio.to_thread(evaluation._run_one, manifest, state.run_dir, invocation, enabled=True)
        assert result["status"] == "completed" and result["comparable"] is not missing_model
        assert result["native_identity_observed"] is not missing_model
        assert result["native_identity_digest"] == (None if missing_model else manifest.file("native_identity").sha256)
        prefix = state.run_dir / "ledger" / digest_bytes(invocation["invocation_id"].encode())
        native = json.loads(prefix.with_suffix(".native.json").read_bytes())
        gateway = json.loads(prefix.with_suffix(".gateway.json").read_bytes())
        assert native["status"] == "completed" and native["cleanup"]["leader_reaped"] is True
        assert native["incomparability_reasons"] == (["MODEL_OBSERVATION_UNKNOWN"] if missing_model else [])
        assert native["artifact_bundle"]["sha256"] == digest_bytes(manifest.file("baseline").raw)
        assert result["input_tokens"] == 12 and result["output_tokens"] == 3 and result["cost_usd"] is None
        assert gateway["observation_complete"] is True
        _, _, retrieval = load_report_inputs(state.run_dir)
        observed = next(row for row in retrieval if row.mode == "memory_on")
        assert observed.returned_claim_ids == () and observed.grounding_refs == ()
        assert observed.manifest_complete is True and observed.final_context_digest
        assert observed.comparable is not missing_model


@pytest.mark.parametrize(("action", "fault", "code"), [
    ("prepare", "source_digest", "FROZEN_FILE_DIGEST_MISMATCH"),
    ("run", "prepared_conflict", "PUBLICATION_UNCERTAIN"),
    ("report", "frozen_digest", "RUN_INPUT_IDENTITY_DRIFT"),
])
def test_real_cli_preserves_bounded_evaluation_failure_code(tmp_path, action, fault, code):
    path, config, _ = fixture_inputs(tmp_path, repeats=1)
    run_dir = tmp_path / "run"
    marker = b"synthetic_private_evaluation_input"
    retained_manifest = None
    if fault == "source_digest":
        prompt = next(row for row in config["files"] if row["name"] == "prompt")
        Path(prompt["path"]).write_bytes(marker)
    else:
        prepare_run(load_manifest(path), run_dir)
        retained_manifest = (run_dir / "manifest.json").read_bytes()
        if fault == "prepared_conflict":
            config["seed"] += 1
            save(path, config)
        else:
            (run_dir / "inputs" / "prompt.frozen").write_bytes(marker)
    arguments = ["evaluation", action, "--run-dir", str(run_dir)]
    if action != "report":
        arguments += ["--manifest", str(path), "--expected-sha256", digest_bytes(path.read_bytes())]
    result = subprocess.run(
        [sys.executable, "-I", "-m", "agents_memory.cli", *arguments],
        cwd=tmp_path, capture_output=True, timeout=10,
    )
    assert result.returncode == 1
    assert result.stdout == b""
    error = json.loads(result.stderr)["error"]
    assert error["code"] == code
    assert error["effect"] == "unknown"
    assert marker not in result.stderr and str(tmp_path).encode() not in result.stderr
    assert b"Traceback" not in result.stderr
    assert not list(run_dir.glob("ledger/*.intent.json"))
    if retained_manifest is not None:
        assert (run_dir / "manifest.json").read_bytes() == retained_manifest


def test_real_cli_private_evaluation_os_error_remains_generic(tmp_path):
    marker = "synthetic_private_manifest_location"
    result = subprocess.run(
        [sys.executable, "-I", "-m", "agents_memory.cli", "evaluation", "prepare",
            "--run-dir", str(tmp_path / "run"), "--manifest", str(tmp_path / marker),
            "--expected-sha256", "0" * 64],
        cwd=tmp_path, capture_output=True, timeout=10,
    )
    assert result.returncode == 1
    assert result.stdout == b""
    assert json.loads(result.stderr)["error"]["code"] == "LOCAL_INPUT_INVALID"
    assert marker.encode() not in result.stderr and str(tmp_path).encode() not in result.stderr
    assert b"Traceback" not in result.stderr
