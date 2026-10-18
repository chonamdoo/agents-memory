from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import importlib.metadata
import json
import os
import re
import secrets
import socket
import stat
import sys
import threading
import traceback
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from agents_memory import cli as product_cli
from agents_memory import context as context_module
from agents_memory import (
    evaluation,
    evaluation_artifacts,
    evaluation_diagnostics,
    evaluation_gateway,
    evaluation_health,
    evaluation_native,
    evaluation_runtime,
    evaluation_scoring,
    evaluation_verifier,
)
from agents_memory.config import Settings
from agents_memory.domain import DomainError, Role, RuleApproval, RuleProposal, RuleScope
from agents_memory.edge import create_app
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
    open_private_directory,
)
from agents_memory.evaluation_gateway import EvaluationGateway, GatewayScope, GatewayUpstream
from agents_memory.evaluation_runtime import CommandLease, DockerRuntime, EvaluationOwner
from agents_memory.evaluation_verifier import (
    ControlArtifact,
    OracleCase,
    OracleTask,
    controls_digest,
)
from agents_memory.health import (
    HealthAssessmentCommand,
    HealthPolicyCommand,
    HealthWorkspaceCommand,
)
from agents_memory.health_code import pin_root
from agents_memory.journal import DeletionJournal
from agents_memory.migrations import migrate
from agents_memory.private_io import private_read, private_write
from agents_memory.stdio import RelayEndpoint
from agents_memory.store import Store
from agents_memory.wire import decode_json

BASELINE_CODE = b"print('noop')\n"
CORRECT_CODE = b"print('correct')\n"
WRONG_CODE = b"print('plausible')\n"
RETAINED = b"retained\r\n"
SOURCE_BODY = "CacheKey is retained only offline."
REVIEW_REFERENCE = "engineering-declared-fixture-r1-not-human-review"
APPROVAL_REFERENCE = "engineering-fixed-controls-r1-not-native-approval"
LIMITS = ArtifactLimits(65536, 20, 8192, 16384, 8, 512, 128, 20, 16384)
MODULES = {
    "controller": evaluation,
    "artifacts": evaluation_artifacts,
    "diagnostics": evaluation_diagnostics,
    "context_renderer": context_module,
    "gateway_driver": evaluation_gateway,
    "health_compiler": evaluation_health,
    "native_driver": evaluation_native,
    "runtime_driver": evaluation_runtime,
    "scoring": evaluation_scoring,
    "verifier": evaluation_verifier,
    "cli": product_cli,
}
PROJECTION_KEYS = (
    "id", "kind", "state", "statement", "evidence", "input_source_ids", "snapshot",
    "interpretation_role", "selection_id", "policy_revision", "revision",
    "awaiting_revalidation", "draft", "judgment_context_refs",
)


class SmokeFailure(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code if re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", code) else "CONDITION_FAILED"


def require(value: object, code: str) -> None:
    if not value:
        raise SmokeFailure(code)


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def private_directory(path: Path) -> None:
    path.mkdir(mode=0o700)
    descriptor = open_private_directory(path)
    os.close(descriptor)


def save(path: Path, value: object) -> None:
    private_write(path, value if isinstance(value, bytes) else canonical_bytes(value))


def retain_failure(root: Path, name: str, cleanup: dict) -> None:
    try:
        save(root / name, traceback.format_exc().encode())
    except (OSError, ValueError):
        cleanup["failure_evidence_publication_complete"] = False


def read_json(path: Path, maximum: int = 4 * 1024 * 1024) -> dict:
    return decode_json(private_read(path, maximum))


class PrivateLog:
    def __init__(self, stream):
        self.stream = stream
        self.count = 0

    def write(self, text: str) -> int:
        raw = text.encode("utf-8", "backslashreplace")
        require(self.count + len(raw) <= 8 * 1024 * 1024, "PRIVATE_LOG_BOUND")
        self.stream.write(raw)
        self.stream.flush()
        self.count += len(raw)
        return len(text)

    def flush(self) -> None:
        self.stream.flush()

    def isatty(self) -> bool:
        return False


def admitted_root() -> Path:
    require(sys.platform == "linux" and os.environ.get("GITHUB_ACTIONS") == "true"
            and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
            and os.uname().machine == "x86_64", "HOSTED_ACTIONS_LINUX_AMD64_REQUIRED")
    for name in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB"):
        require(re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", os.environ.get(name, "")), "ACTIONS_OWNER_REQUIRED")
    raw = os.environ.get("RUNNER_TEMP", "")
    root = Path(raw)
    require(root.is_absolute() and ".." not in root.parts, "RUNNER_TEMP_REQUIRED")
    require(root.resolve() == root, "RUNNER_TEMP_SYMLINK_REFUSED")
    state = root / "agents-memory-evaluation"
    for path in (state, state / "verifier"):
        descriptor = open_private_directory(path)
        os.close(descriptor)
    require(os.environ.get("AGENTS_MEMORY_EVALUATION_RUNTIME_SPEC") == str(state / "runtime-spec.json"),
            "PREPARED_RUNTIME_SPEC_REQUIRED")
    return state


def predeclared_approval() -> tuple[str, str]:
    # This independent literal specification never reads submitted task/control models.
    def h(raw: bytes) -> str:
        return hashlib.sha256(raw).hexdigest()

    def j(value: object) -> str:
        return h(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())

    def bundle(code: bytes) -> str:
        return j({"schema": 1, "entries": [
            {"path": "program.py", "kind": "file", "mode": 420, "size": len(code), "sha256": h(code)},
            {"path": "retained.txt", "kind": "file", "mode": 420, "size": 10, "sha256": h(b"retained\r\n")},
        ]})

    baseline = bundle(b"print('noop')\n")
    policy = j({"baseline": baseline, "spans": [{"path": "program.py", "start": 0, "end": 14}],
                "creates": [], "deletes": [], "modes": []})
    task = j({"task_id": "coding-one", "revision": "r1",
              "review": "engineering-declared-fixture-r1-not-human-review", "baseline": baseline,
              "policy": policy, "cases": [{"case_id": "stdout",
                  "argv": ["/usr/local/bin/python3", "-I", "-S", "/artifact/program.py"],
                  "stdin": h(b""), "stdout": h(b"correct\n"), "stderr": h(b""), "exit": 0, "effects": []}]})
    controls = []
    for role, code in (("correct", b"print('correct')\n"), ("noop", b"print('noop')\n"),
                       ("plausible_wrong", b"print('plausible')\n")):
        final = bundle(code)
        witness = j({"baseline": baseline, "final": final,
                     "edits": [] if role == "noop" else [{"path": "program.py", "start": 0,
                         "end": 14, "replacement": h(code)}], "creates": [], "deletes": [], "modes": []})
        controls.append({"role": role, "bundle": final, "witness": witness})
    return task, j(controls)


def task_inputs() -> tuple[dict, dict]:
    def bundle(code: bytes) -> ArtifactBundle:
        return ArtifactBundle((
            ArtifactEntry("program.py", "file", 0o644, code, digest_bytes(code)),
            ArtifactEntry("retained.txt", "file", 0o644, RETAINED, digest_bytes(RETAINED)),
        ), LIMITS)

    baseline, correct, wrong = (bundle(code) for code in (BASELINE_CODE, CORRECT_CODE, WRONG_CODE))
    policy = EditPolicy(baseline.digest, (EditableSpan("program.py", 0, len(BASELINE_CODE)),), (), (), ())
    empty = EditWitness(baseline.digest, baseline.digest, (), (), (), ())
    case = OracleCase("stdout", ("/usr/local/bin/python3", "-I", "-S", "/artifact/program.py"),
                      b"", b"correct\n", b"", 0, ())
    task = OracleTask("coding-one", "r1", REVIEW_REFERENCE, baseline.digest, policy, empty, (case,))
    controls = tuple(ControlArtifact(role, artifact, empty if role == "noop" else EditWitness(
        baseline.digest, artifact.digest, (ByteEdit("program.py", 0, len(BASELINE_CODE), artifact.entries[0].content),), (), (), ()
    )) for role, artifact in (("correct", correct), ("noop", baseline), ("plausible_wrong", wrong)))
    approved_task, approved_controls = predeclared_approval()
    require(task.digest == approved_task and controls_digest(controls) == approved_controls,
            "PREDECLARED_ENGINEERING_APPROVAL_DRIFT")
    documents = {"baseline": baseline.to_bytes(), "correct": correct.to_bytes(), "wrong": wrong.to_bytes(),
                 "policy": asdict(policy), "oracle": {"schema": 1, "cases": [{
                     "case_id": "stdout", "argv": list(case.argv), "stdin": "", "expected_stdout": b64(b"correct\n"),
                     "expected_stderr": "", "expected_exit": 0, "effects": []}]}}
    for control in controls:
        documents[control.role + "_witness"] = {
            "baseline_digest": baseline.digest, "final_digest": control.bundle.digest,
            "edits": [{"path": edit.path, "start": edit.start, "end": edit.end, "replacement": b64(edit.replacement)}
                      for edit in control.witness.edits], "creates": [], "deletes": [], "modes": [],
        }
    declaration = {
        "task_id": "coding-one", "task_revision": "r1", "cluster_id": "coding-one",
        "prompt_file": "prompt", "baseline_file": "baseline", "policy_file": "policy", "oracle_file": "oracle",
        "controls": [{"role": "correct", "bundle_file": "correct", "witness_file": "correct_witness"},
                     {"role": "noop", "bundle_file": "baseline", "witness_file": "noop_witness"},
                     {"role": "plausible_wrong", "bundle_file": "wrong", "witness_file": "plausible_wrong_witness"}],
        "approval_reference": APPROVAL_REFERENCE, "approved_task_digest": approved_task,
        "approved_controls_digest": approved_controls, "independent_reference": REVIEW_REFERENCE,
        "witness_name": "edit-witness.json",
    }
    return documents, declaration


def selection_arguments(window: dict, source: str, key: str) -> dict:
    span = window["span_inventory"][0]
    require(window["body"] == SOURCE_BODY and window["next_byte"] is None, "ENGINEERING_SOURCE_IDENTITY")
    return {
        "kind": "source_selection", "idempotency_key": key, "admission_id": window["admission_id"],
        "source_id": source, "source_revision": window["source_revision"],
        "binding_revision": window["binding_revision"], "byte_start": window["byte_start"],
        "byte_end": window["byte_end"], "window_digest": window["window_digest"],
        "policy_revision": window["policy_revision"], "policy_epoch": window["policy_epoch"],
        "label": "remember", "coverage": "complete_window",
        "reason": "Predetermined engineering-only judgment of exact fixture bytes; not model or human acceptance.",
        "extraction": {"claims": [{"assertion_id": "a0000", "assertion_span_id": span["span_id"],
            "statement": span["quote"], "kind": "fact", "subject": "CacheKey", "predicate": "retained",
            "object": "offline", "polarity": "positive", "modality": "asserted", "entities": ["CacheKey"]}],
            "individual_qualifications": [{"assertion_id": "a0000", "kind": "condition", "phrase": "only offline",
                                           "evidence_span_id": span["span_id"]}],
            "shared_qualifications": [], "validities": [],
            "unused_span_ids": [item["span_id"] for item in window["span_inventory"] if item["span_id"] != span["span_id"]]},
    }


def full_inspect(call, ref: str) -> dict:
    offset, collected, identity = 0, bytearray(), None
    for _ in range(1024):
        payload = call("memory_inspect", {"ref": ref, "byte_start": offset, "max_bytes": 4096})
        window = payload.get("draft_window")
        if window is None:
            require(offset == 0 and not payload.get("partial"), "COMPLETE_INSPECTION_REQUIRED")
            return payload
        current = (window["digest"], window["total_bytes"])
        identity = current if identity is None else identity
        chunk = window["body"].encode()
        require(current == identity and window["byte_start"] == offset and window["byte_end"] == offset + len(chunk)
                and 0 < len(chunk) <= 4096 and len(collected) + len(chunk) <= 4 * 1024 * 1024,
                "INSPECTION_WINDOW_INVALID")
        collected.extend(chunk)
        if window["next_byte"] is None:
            require(len(collected) == identity[1] and digest_bytes(collected) == identity[0], "INSPECTION_DIGEST_INVALID")
            return decode_json(bytes(collected))
        require(window["next_byte"] == len(collected), "INSPECTION_CURSOR_INVALID")
        offset = len(collected)
    raise ValueError("INSPECTION_BOUND")


PEER_SOURCE = r'''
import asyncio, hashlib, json, os, pathlib, sys, uuid
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from agents_memory.evaluation_artifacts import digest_bytes
from agents_memory.wire import decode_json

assert sys.platform == 'linux' and os.environ.get('GITHUB_ACTIONS') == 'true'
assert sys.argv[1:5] == ['-p', '--output-format', 'stream-json', '--verbose']
prompt = sys.stdin.buffer.read(1048577)
assert len(prompt) <= 1048576
manifest_path, run_dir, helper_path = map(pathlib.Path, FIXTURE_PATHS)
manifest = decode_json(manifest_path.read_bytes())
workload_ref = next(item for item in manifest['files'] if item['name'] == 'workload')
workload = decode_json(pathlib.Path(workload_ref['path']).read_bytes())
invocation = next(item for item in workload['invocations'] if item['native']['cwd'] == str(pathlib.Path.cwd()))
identity = invocation['invocation_id']
channel = manifest['preflight_gateway' if invocation['phase'] == 'preflight' else 'gateway']
assert json.loads(prompt.decode().splitlines()[-1])['invocation_id'] == identity
mapping_ref = next(item for item in manifest['files'] if item['name'] == 'native_tool_mapping')
mapping = next(item for item in decode_json(pathlib.Path(mapping_ref['path']).read_bytes())['routes']
               if item['route_ref'] == channel['route_ref'])
session_id = 'engineering-claude-protocol-' + uuid.uuid4().hex

def emit(value):
    print(json.dumps(value, ensure_ascii=False, separators=(',', ':')), flush=True)

async def exercise():
    params = StdioServerParameters(command=sys.executable, args=['-m', 'agents_memory.cli', 'evaluation', 'gateway',
        '--manifest', str(manifest_path), '--run-dir', str(run_dir), '--invocation-id', identity,
        '--expected-sha256', hashlib.sha256(manifest_path.read_bytes()).hexdigest()], env=dict(os.environ))
    with (pathlib.Path.cwd() / 'gateway-stderr.private').open('x', encoding='utf-8') as errors:
        os.chmod(errors.name, 0o600)
        async with stdio_client(params, errlog=errors) as streams:
            async with ClientSession(*streams, read_timeout_seconds=30.0) as client:
                await client.initialize()
                names = sorted(tool.name for tool in (await client.list_tools()).tools)
                expected = ['memory_required_context'] if invocation['mode'] == 'required_only' else None
                if expected is not None:
                    assert names == expected
                else:
                    assert {'memory_required_context', 'memory_inspect', 'memory_record', 'memory_context'} <= set(names)
                emit({'type':'system', 'subtype':'init', 'session_id':session_id,
                      'model':'engineering-protocol-peer-not-a-model', 'claude_code_version':'engineering-protocol-r1',
                      'permissionMode':'engineering-fixture-no-native-permission-attestation',
                      'tools':sorted(mapping['tools'][name] for name in names),
                      'mcp_servers':[{'name':mapping['server'],'status':'connected'}]})
                async def call(name, arguments):
                    action = 'native-tool-' + uuid.uuid4().hex
                    emit({'type':'assistant', 'session_id':session_id,
                          'message':{'content':[{'type':'tool_use','id':action,
                              'name':mapping['tools'][name],'input':arguments}]}})
                    result = await client.call_tool(name, arguments)
                    assert not result.is_error and len(result.content) == 1
                    emit({'type':'user', 'session_id':session_id,
                          'message':{'content':[{'type':'tool_result','tool_use_id':action,
                              'is_error':False,'content':[
                                  entry.model_dump(mode='json', by_alias=True, exclude_none=True)
                                  for entry in result.content]}]}})
                    return decode_json(result.content[0].text.encode())
                async def inspect(ref):
                    offset, data, stamp = 0, bytearray(), None
                    for _ in range(1024):
                        value = await call('memory_inspect', {'ref':ref, 'byte_start':offset, 'max_bytes':4096})
                        window = value.get('draft_window')
                        if window is None:
                            assert offset == 0 and not value.get('partial')
                            return value
                        current = (window['digest'],window['total_bytes'])
                        stamp = current if stamp is None else stamp
                        assert stamp == current and window['byte_start'] == offset
                        data.extend(window['body'].encode())
                        assert len(data) == window['byte_end'] and len(data) <= 4194304
                        if window['next_byte'] is None:
                            assert len(data) == stamp[1] and hashlib.sha256(data).hexdigest() == stamp[0]
                            return decode_json(bytes(data))
                        assert window['next_byte'] == len(data) and len(data) > offset
                        offset = len(data)
                    raise ValueError('fixture-inspection-bound')
                required = await call('memory_required_context', channel['required_request'])
                assert required['stamp']['rules']
                if invocation['mode'] == 'memory_on':
                    await call('memory_required_context', channel['required_request'])
                if invocation['mode'] == 'required_only':
                    refusal = await client.call_tool('memory_context', channel['required_request'])
                    assert refusal.is_error
                else:
                    if invocation['phase'] == 'preflight':
                        capture = decode_json((run_dir/'ledger'/(digest_bytes(identity.encode())+'.capture.json')).read_bytes())
                        source = capture['source_pointer']['source_id']
                        window = await call('memory_inspect', {'ref':source})
                        assert window['body'] == 'CacheKey is retained only offline.' and window['next_byte'] is None
                        span = window['span_inventory'][0]
                        selection = await call('memory_record', {
                            'kind':'source_selection','idempotency_key':'engineering-native-selection',
                            'admission_id':window['admission_id'],'source_id':source,
                            'source_revision':window['source_revision'],'binding_revision':window['binding_revision'],
                            'byte_start':window['byte_start'],'byte_end':window['byte_end'],
                            'window_digest':window['window_digest'],'policy_revision':window['policy_revision'],
                            'policy_epoch':window['policy_epoch'],'label':'remember','coverage':'complete_window',
                            'reason':'Explicit synthetic engineering protocol judgment, not a subscribed agent.',
                            'extraction':{'claims':[{'assertion_id':'a0000','assertion_span_id':span['span_id'],
                                'statement':span['quote'],'kind':'fact','subject':'CacheKey','predicate':'retained',
                                'object':'offline','polarity':'positive','modality':'asserted','entities':['CacheKey']}],
                                'individual_qualifications':[{'assertion_id':'a0000','kind':'condition','phrase':'only offline',
                                                              'evidence_span_id':span['span_id']}],
                                'shared_qualifications':[],'validities':[],
                                'unused_span_ids':[item['span_id'] for item in window['span_inventory'] if item['span_id'] != span['span_id']]}})
                        selected = await inspect(selection['artifact_id'])
                        assert selected['claim_ids']
                        for claim in selected['claim_ids']:
                            await inspect(claim)
                        request = workload['preflight']['recall_request']
                    else:
                        request = channel['required_request']
                    candidates = await call('memory_context', request)
                    assert candidates['candidate_manifest']
                    for item in candidates['candidate_manifest']:
                        await inspect(item['inspection_ref'])
                    final = await call('memory_context', {**request,'admission_id':candidates['admission_id'],
                        'relevance':[{'claim_id':item['claim_id'],'relevant':True,
                                      'reason':'Predetermined fixture relevance, not actual model judgment.'}
                                     for item in candidates['candidate_manifest']]})
                    assert final['judgment_required'] is False and final['refs']
                    context = final['context']
                    if isinstance(context,str):
                        context = decode_json(context.encode())
                    assert context['memory_candidates']
    def frozen(name):
        ref = next(item for item in manifest['files'] if item['name'] == name)
        raw = pathlib.Path(ref['path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == ref['sha256']
        return raw
    if invocation['phase'] == 'coding':
        artifact = frozen('correct')
        bundle = decode_json(artifact)
        import base64
        code = base64.b64decode(next(entry for entry in bundle['entries'] if entry['path']=='program.py')['content'])
        assert code == b"print('correct')\n"
        (pathlib.Path.cwd()/'program.py').write_bytes(code)
        witness = pathlib.Path.cwd()/'edit-witness.json'
        witness.write_bytes(frozen('correct_witness'))
        witness.chmod(0o600)
    else:
        artifact = frozen('baseline')
    submission = pathlib.Path(invocation['native']['submission_path'])
    with submission.open('xb') as output:
        output.write(artifact)
    submission.chmod(0o600)
    emit({'type':'result','subtype':'success','session_id':session_id,'is_error':False,
          'structured_output':{'submission_path':str(submission)}})

asyncio.run(exercise())
'''


def peer_bytes(manifest: Path, run: Path, helper: Path) -> bytes:
    return ("#!" + sys.executable + "\nFIXTURE_PATHS = " + repr((str(manifest), str(run), str(helper)))
            + "\n" + PEER_SOURCE).encode()


def source_identity(wheel: Path, expected_digest: str, consumption: str) -> tuple[dict, dict[str, str]]:
    require(re.fullmatch(r"[0-9a-f]{64}", expected_digest), "EXPECTED_WHEEL_DIGEST_REQUIRED")
    info = wheel.lstat()
    require(stat.S_ISREG(info.st_mode) and not wheel.is_symlink() and info.st_nlink == 1
            and info.st_size <= 64 * 1024 * 1024, "WHEEL_BOUNDARY_INVALID")
    raw = private_read(wheel, 64 * 1024 * 1024, private=False)
    require(digest_bytes(raw) == expected_digest, "WHEEL_IDENTITY_MISMATCH")
    identities = {}
    with zipfile.ZipFile(wheel) as archive:
        require(len(archive.namelist()) <= 4096, "WHEEL_ENTRY_BOUND")
        for name, module in MODULES.items():
            path = Path(module.__file__).absolute()
            source = private_read(path, 4 * 1024 * 1024, private=False)
            member = "agents_memory/" + path.name
            require(archive.namelist().count(member) == 1 and archive.getinfo(member).file_size <= 4 * 1024 * 1024,
                    "WHEEL_MODULE_BOUNDARY_INVALID")
            require(archive.read(member) == source, "CONSUMED_MODULE_WHEEL_MISMATCH")
            identities[name] = digest_bytes(source)
            if consumption == "installed":
                require(not path.is_relative_to(Path(os.environ["GITHUB_WORKSPACE"]).resolve()),
                        "INSTALLED_CONSUMER_RESOLVED_CHECKOUT")
    distribution = importlib.metadata.distribution("agents-memory")
    require(re.fullmatch(r"[A-Za-z0-9.+_-]{1,64}", distribution.version), "DISTRIBUTION_VERSION_INVALID")
    identity = {"wheel_sha256": expected_digest, "consumption": consumption,
                "distribution_version": distribution.version,
                "modules_digest": digest_bytes(canonical_bytes(identities)), "module_digests": identities,
                "python_executable_sha256": digest_bytes(Path(sys.executable).resolve().read_bytes())}
    return identity, identities


def channel(settings: Settings, binding: str, files: dict, phase: str, *, rules_file: str) -> dict:
    endpoint = asdict(RelayEndpoint(settings.base_url, state_dir=settings.state_dir, deployment_id=settings.deployment_id))
    endpoint["state_dir"] = str(endpoint["state_dir"])
    return {"route_ref": "engineering-" + phase + "-route", "binding_id": binding,
            "agent": {"endpoint": endpoint, "token_file": str(files["agent"]), "approval_ref": "engineering-fixture-agent-only"},
            "producer": {"endpoint": endpoint, "token_file": str(files["producer"]), "approval_ref": "engineering-fixture-producer-only"},
            "approved_upstream_urls": [settings.base_url], "approved_refs": [], "protocol_version": "2025-11-25",
            "max_calls": 200, "max_trace_bytes": 16 * 1024 * 1024,
            "required_request": {"binding_id": binding, "query": "CacheKey offline", "max_bytes": 6144, "limit": 3},
            "lifetime_seconds": 90.0, "rules_file": rules_file}


def fixture_gateway(config: dict, trace, *, invocation_id: str) -> EvaluationGateway:
    upstream = {}
    for role in ("agent", "producer"):
        item = config[role]
        endpoint = dict(item["endpoint"])
        endpoint["state_dir"] = Path(endpoint["state_dir"])
        upstream[role] = GatewayUpstream(RelayEndpoint(**endpoint), Path(item["token_file"]), role,
                                        config["binding_id"], item["approval_ref"])
    scope = GatewayScope(invocation_id, config["route_ref"], "memory_on", "preflight",
                         config["binding_id"], tuple(config["approved_upstream_urls"]), tuple(config["approved_refs"]), config["protocol_version"],
                         config["max_calls"], config["max_trace_bytes"], config["required_request"])
    return EvaluationGateway(scope, agent=upstream["agent"], producer=upstream["producer"], trace_sink=trace)


def prepare_corpus(config: dict, evidence: Path) -> tuple[dict, dict, dict]:
    sequence = 0
    def trace(value):
        nonlocal sequence
        raw = canonical_bytes(evaluation._private_value(value))
        require(len(raw) <= 4 * 1024 * 1024 and sequence < 1000, "CORPUS_TRACE_BOUND")
        save(evidence / f"corpus-{sequence:04}.json", raw)
        sequence += 1
    gateway = fixture_gateway(config, trace, invocation_id="engineering-corpus-preparation")
    def call(name, arguments):
        result = gateway.call_tool(name, arguments)
        require(not result.get("isError"), "CORPUS_REAL_MCP_FAILURE")
        return evaluation._payload(result)
    try:
        rules = call("memory_required_context", config["required_request"])["stamp"]["rules"]
        capture = gateway.capture({"binding_id": config["binding_id"], "idempotency_key": "engineering-measured-source",
                                   "origin_key": "engineering-measured-source", "speaker": "document", "body": SOURCE_BODY,
                                   "root_run_id": "engineering_measured_run", "agent_path": "engineering-source"})
        pointer = capture["source_pointer"]
        source = pointer["source_id"]
        window = call("memory_inspect", {"ref": source})
        selected = call("memory_record", selection_arguments(window, source, "engineering-measured-selection"))
        selection = full_inspect(call, selected["artifact_id"])
        claims = [full_inspect(call, claim) for claim in selection["claim_ids"]]
        require(len(claims) == 1, "EXACT_ENGINEERING_CLAIM_REQUIRED")
        segment = gateway._producer.request("/api/health", {
            "kind": "session_observation", "binding_id": config["binding_id"],
            "expected_binding_revision": 1, "idempotency_key": "engineering-segment-end",
            "stream_id": "engineering_stream", "segment_id": "engineering_segment",
            "event_id": "engineering_end", "sequence": 1, "event": "end",
            "root_run_id": "engineering_measured_run", "agent_path": "engineering-source",
            "source_refs": [{"id": source, "revision": pointer["source_revision"]}],
            "claim_refs": [{"id": item["id"], "revision": item["revision"]} for item in claims],
            "coverage": "partial", "gaps": ["HOST_HUMAN_PRESENCE_UNATTESTED"],
        })
        require(segment["state"] == "health_recorded", "EXPLICIT_OBSERVED_SEGMENT_REQUIRED")
        config["approved_refs"] = sorted({source, *(item["id"] for item in claims),
                                         *("health:claim:" + item["id"] for item in claims)})
        gateway.close()
        gateway = fixture_gateway(config, trace, invocation_id="engineering-corpus-post-publication")
        require(call("memory_required_context", config["required_request"])["stamp"]["rules"] == rules,
                "REQUIRED_RULE_IDENTITY_CHANGED")
        window = call("memory_inspect", {"ref": source, "byte_start": 0, "max_bytes": 4096})
        health_views = {item["id"]: call("memory_inspect", {"ref": "health:claim:" + item["id"]})
                        for item in claims}
        probe = {"query": digest_bytes(b"engineering bounded zero-candidate rule probe"), "max_bytes": 6144, "limit": 5}
        request = {**{key: value for key, value in config["required_request"].items()
                      if key not in {"query", "query_expansions", "max_bytes", "limit"}}, **probe}
        probe_gateway = fixture_gateway({**config, "required_request": request}, trace,
                                        invocation_id="engineering-frozen-rule-probe")
        try:
            probe_required = evaluation._payload(probe_gateway.call_tool("memory_required_context", request))
            require(probe_required["stamp"]["rules"] == rules, "PROBE_REQUIRED_RULE_IDENTITY_CHANGED")
            rules_snapshot = {
                "schema": 2, "rules": sorted(rules), "probe": probe,
                "applicable": evaluation._rule_snapshot(evaluation._payload(probe_gateway.call_tool("memory_context", request))),
            }
        finally:
            probe_gateway.close()
        evaluation._validate_rule_snapshot(rules_snapshot)
        judgment = evaluation._inspect(
            gateway, "judgment", 4 * 1024 * 1024,
            claim_ids=tuple(item["id"] for item in claims),
        )
        require(judgment.get("relation_ids") == [], "ENGINEERING_EMPTY_RELATION_CLOSURE_REQUIRED")
        corpus = {"schema": 2, "relations": [], "sources": [{"source_id": source, "revision": pointer["source_revision"],
                   "body": b64(SOURCE_BODY.encode()), "sha256": digest_bytes(SOURCE_BODY.encode()),
                   "inspection_windows": [{key: window[key]
                                           for key in ("byte_start", "byte_end", "window_digest")}]}],
                  "claims": [{"ref": item["id"], "projection": {key: item.get(key) for key in PROJECTION_KEYS},
                              "health_dependency_digest": health_views[item["id"]]["dependency_digest"]}
                             for item in claims]}
        anchors = [{"source_id": span["source_id"], "revision": span["source_revision"],
                    "byte_start": span["byte_start"], "byte_end": span["byte_end"],
                    "quote_digest": digest_bytes(span["quote"].encode())} for span in claims[0]["evidence"]]
        gold = {"schema": 1, "independence": "provided_unattested", "cases": [{"case_id": "cache-offline",
                "cluster_id": "engineering-source-family", "group": "engineering-positive",
                "relevant_claim_ids": [claims[0]["id"]], "irrelevant_claim_ids": [], "judgment_complete": True,
                "grounding_refs": anchors}]}
        return corpus, gold, rules_snapshot
    finally:
        gateway.close()


def freeze_manifest(
    root: Path, measured: dict, preflight: dict, corpus: dict, gold: dict,
    rules: dict, preflight_rules: list, args, runtime_raw: bytes,
    *, native_root: Path,
) -> tuple[Path, Path, evaluation.EvaluationManifest]:
    inputs, native = root / "inputs", native_root
    private_directory(inputs)
    private_directory(native)
    manifest_path, run = root / "manifest.json", root / "controller"
    peer = root / "engineering-claude-protocol-peer"
    save(peer, peer_bytes(manifest_path, run, Path(__file__).absolute()))
    peer.chmod(0o700)
    documents, task = task_inputs()
    documents.update({name: Path(module.__file__).read_bytes() for name, module in MODULES.items()})
    documents.update({"wheel": private_read(args.wheel, 64 * 1024 * 1024, private=False),
                      "runtime": runtime_raw, "corpus": corpus, "gold": gold,
                      "rules": rules, "preflight_rules": {"schema": 1, "rules": preflight_rules},
                      "prompt": b"Explicit synthetic engineering protocol fixture only. Preserve retained.txt exactly; change program.py to print correct. No original native/model/independent approval is claimed."})
    settings_digest = digest_bytes(canonical_bytes({"peer": digest_bytes(peer.read_bytes()), "measured": measured,
                                                    "preflight": preflight, "scope": "engineering-only"}))
    permissions_digest = digest_bytes(b"engineering-protocol-fixture-only; no subscribed native or HOME/trust changes; scoped actual product roles")
    for phase, selected in (("measured", measured), ("preflight", preflight)):
        documents[phase + "_context"] = {"schema": 1, "independence": "provided_unattested",
            "settings_digest": settings_digest, "permissions_digest": permissions_digest, "route_ref": selected["route_ref"],
            "ownership_boundary_ref": "engineering-own-processes-not-hostile-native-isolation",
            "exclusive_optional_route_observed": True, "residual_memory_absence_observed": True,
            "fresh_generation_observed": True}
    tools = {name: "mcp__engineering-scoped-gateway__" + name
             for name in ("memory_required_context", *evaluation_gateway.SCHEMAS)}
    documents["native_tool_mapping"] = {"schema": 1, "backend": "claude",
        "routes": [{"route_ref": selected["route_ref"], "server": "engineering-scoped-gateway", "tools": tools}
                   for selected in (measured, preflight)]}
    tools_on = sorted(tools.values())
    documents["native_identity"] = {"schema": 1, "backend": "claude", "executable_sha256": digest_bytes(peer.read_bytes()),
        "fields": {"model": "engineering-protocol-peer-not-a-model", "claude_code_version": "engineering-protocol-r1",
                   "permissionMode": "engineering-fixture-no-native-permission-attestation",
                   "mcp_servers": [{"name": "engineering-scoped-gateway", "status": "connected"}]},
        "mode_fields": {"memory_on": {"tools": tools_on}, "required_only": {"tools": [tools["memory_required_context"]]}}}
    invocations = []
    def invocation(identity, phase, target, mode):
        cwd = native / identity
        selected = preflight if phase == "preflight" else measured
        spec = {"backend": "claude", "executable": str(peer), "cwd": str(cwd), "submission_path": str(cwd / "submission.json"),
            "authorization_ref": "engineering-protocol-peer-not-native-approval", "context_observation_ref": "engineering-route-only",
            "approved_context": True, "gateway_invocation_id": identity, "gateway_route_ref": selected["route_ref"],
            "exclusive_optional_route_observed": True, "residual_memory_absence_observed": True, "fresh_generation_observed": True,
            "timeout_seconds": 120.0, "cleanup_seconds": 5.0, "max_input_bytes": 1048576, "max_stdout_bytes": 1048576,
            "max_stderr_bytes": 1048576, "max_record_bytes": 262144, "max_events": 1000, "max_submission_bytes": 65536,
            "expected_model": "engineering-protocol-peer-not-a-model", "expected_version": "engineering-protocol-r1"}
        invocations.append({"invocation_id": identity, "phase": phase, "target_id": target, "mode": mode,
            "repeat_index": 0 if phase == "coding" else None, "pair_attempt": 0 if phase == "coding" else None,
            "context_file": "preflight_context" if phase == "preflight" else "measured_context", "native": spec})
    invocation("preflight-one", "preflight", "preflight-one", "memory_on")
    for mode in ("memory_on", "required_only"):
        invocation("retrieval-" + mode, "retrieval", "cache-offline", mode)
        invocation("coding-" + mode, "coding", "coding-one", mode)
    documents["workload"] = {"schema": 1, "tasks": [task], "retrieval": [{"case_id": "cache-offline", "prompt_file": "prompt",
        "request": measured["required_request"]}], "preflight": {"invocation_id": "preflight-one", "capture": {
            "binding_id": preflight["binding_id"], "idempotency_key": "engineering-preflight-source",
            "origin_key": "engineering-preflight-source", "speaker": "document", "body": SOURCE_BODY},
            "recall_request": preflight["required_request"], "prompt_file": "prompt", "baseline_file": "baseline"},
        "invocations": invocations}
    files = []
    for name, value in documents.items():
        path = inputs / (name + ".input")
        save(path, value)
        files.append({"name": name, "path": str(path), "sha256": digest_bytes(path.read_bytes()),
                      "maximum_bytes": 64 * 1024 * 1024 if name == "wheel" else 4 * 1024 * 1024})
    config = {"schema": 1, "scope": "engineering", "source_commit": os.environ["CI_TESTED_SHA"],
        "controller_digest": digest_bytes(documents["controller"]), "verifier_digest": evaluation_verifier.verifier_source_digest(),
        "settings_digest": settings_digest, "permissions_digest": permissions_digest, "seed": 1234, "repeats": 1,
        "resamples": 10000, "confidence": 0.95, "concurrency": 1, "max_pair_retries": 0, "retry_statuses": [],
        "record_bytes": 8 * 1024 * 1024, "trace_bytes": 64 * 1024 * 1024, "trace_events": 4000,
        "artifact_limits": asdict(LIMITS), "verifier_limits": {"max_cases": 10, "max_effects": 10, "private_receipt_bytes": 8 * 1024 * 1024},
        "owner": {"run_id": os.environ["GITHUB_RUN_ID"], "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"], "job_id": os.environ["GITHUB_JOB"]},
        "gateway": measured, "preflight_gateway": preflight, "usage_budgets": {"input_tokens": None, "output_tokens": None,
        "total_tokens": None, "cost_usd": None}, "files": files, "independence": "provided_unattested"}
    save(manifest_path, config)
    frozen = evaluation.load_manifest(manifest_path, expected_sha256=digest_bytes(manifest_path.read_bytes()))
    return manifest_path, run, frozen


async def cli(
    root: Path, name: str, arguments: list[str], seconds: float = 1200,
    *, command: str = "evaluation", global_arguments: tuple[str, ...] = (),
) -> dict:
    argv = [sys.executable, "-m", "agents_memory.cli", *global_arguments, command, *arguments]
    save(root / (name + "-intent.json"), {"schema": 1, "argv": argv, "seconds": seconds})
    def execute():
        return CommandLease(argv, dict(os.environ), stdin=b"", seconds=seconds,
                            stdout_limit=16 * 1024 * 1024, stderr_limit=4 * 1024 * 1024).close(10)
    result = await asyncio.to_thread(execute)
    save(root / (name + "-observation.json"), {**result.public(), "stdout": b64(result.stdout), "stderr": b64(result.stderr)})
    require(result.completed, "ACTUAL_EVALUATION_CLI_FAILED")
    return decode_json(result.stdout)


def ledger_snapshot(run: Path) -> dict[str, str]:
    result = {}
    for directory in (run / "ledger", run / "artifacts"):
        entries = list(directory.iterdir())
        require(len(entries) <= 1000, "LEDGER_BOUND")
        for path in entries:
            require(path.is_file() and not path.is_symlink(), "LEDGER_BOUNDARY")
            result[str(path.relative_to(run))] = digest_bytes(private_read(path, 64 * 1024 * 1024))
    return result


def assert_results(run: Path, manifest: Path, report: dict, reported: dict) -> dict:
    protocol, arms, retrieval = evaluation.load_report_inputs(run)
    require(len(arms) == 2 and len(retrieval) == 2, "ALL_ATTEMPTS_REQUIRED")
    projected = evaluation_scoring.score_run(protocol, arms, retrieval)
    require({key: reported[key] for key in projected} == projected and report == reported,
            "CLI_SCORER_REPORT_MISMATCH")
    require(report["scope"] == "engineering" and report["original_acceptance"] is False
            and report["original18_completed"] == 0 and report["engineering_nonacceptance"] is True,
            "ENGINEERING_NONACCEPTANCE_REQUIRED")
    require(report["controller"]["preflight"]["status"] == "completed"
            and report["controller"]["preflight"]["comparable"] is True, "NATIVE_PRODUCER_PREFLIGHT_REQUIRED")
    require(report["coding"]["valid_pair_attempts"] == 1 and report["coding"]["pair_attempts"] == 1
            and report["coding"]["retry_pair_attempts"] == 0 and report["coding"]["missing_arms"] == 0,
            "EXACT_PAIRED_CONTROL_COMPARABILITY_REQUIRED")
    require(report["retrieval"]["valid_final_reads"] == 2, "EXACT_RETRIEVAL_READS_REQUIRED")
    for arm in arms:
        require(arm.status == "completed" and arm.comparable and not arm.contaminated and arm.structural_pass is True
                and arm.functional_success is True and arm.cleanup_complete is True and arm.native_identity_observed,
                "REAL_EXTERNAL_BLACKBOX_ARM_REQUIRED")
        require(arm.corpus_before_digest == arm.corpus_after_digest == protocol.corpus_digest
                and arm.required_rules_digest == protocol.required_rules_digest, "FROZEN_CORPUS_RULES_REQUIRED")
        require(arm.cost_usd is None and arm.input_tokens is None and arm.output_tokens is None
                and arm.total_tokens is None and arm.cost_basis == "unknown", "SYNTHETIC_COST_MUST_REMAIN_UNKNOWN")
        key = digest_bytes(arm.invocation_id.encode())
        controls = read_json(run / "ledger" / (key + ".controls.json"), 8 * 1024 * 1024)
        require(controls["eligible"] is True, "ACTUAL_CONTROLS_REQUIRED")
        receipts = controls["receipts"]
        require([item["role"] for item in receipts] == ["control_correct", "control_noop", "control_plausible_wrong"]
                and [item["success"] for item in receipts] == [True, False, False], "CONTROL_FUNCTIONAL_DISCRIMINATION_REQUIRED")
        for receipt in receipts:
            require(receipt["cleanup_complete"] is True and receipt["error_code"] is None
                    and receipt["structural"]["passed"] is True and len(receipt["cases"]) == 1,
                    "CONTROL_STRUCTURAL_RUNTIME_CLEANUP_REQUIRED")
            observation = receipt["cases"][0]["observation"]
            require(observation["state"] == "completed" and observation["execution"]["state"] == "completed"
                    and observation["cleanup"]["exact_absence"] is True and not observation["cleanup"]["pending_create"],
                    "CONTROL_EXECUTION_NOT_INFRASTRUCTURE_REJECTION")
        verified = read_json(run / "ledger" / (key + ".verifier.json"), 8 * 1024 * 1024)
        require(verified["success"] is True and verified["cases"][0]["passed"] is True
                and verified["controls_digest"] == controls["controls_digest"], "SAME_EXECUTOR_BLACKBOX_REQUIRED")
    expected_claim = protocol.retrieval_cases[0].relevant_claim_ids[0]
    on = next(row for row in retrieval if row.mode == "memory_on")
    off = next(row for row in retrieval if row.mode == "required_only")
    require(on.returned_claim_ids == (expected_claim,) and off.returned_claim_ids == ()
            and on.manifest_complete is True and off.manifest_complete is True,
            "ACTUAL_ON_OFF_DELIVERY_REQUIRED")
    require(tuple(on.grounding_refs) == tuple(protocol.retrieval_cases[0].grounding_refs)
            and off.grounding_refs == (), "EXACT_GROUNDING_REQUIRED")
    frozen = evaluation.load_manifest(manifest)
    generations = set()
    for invocation in frozen.workload["invocations"]:
        key = digest_bytes(invocation["invocation_id"].encode())
        require((run / "ledger" / (key + ".intent.json")).is_file(), "PRIOR_IMMUTABLE_INTENT_REQUIRED")
        terminal = read_json(run / "ledger" / (key + ".terminal.json"), 8 * 1024 * 1024)
        native = read_json(run / "ledger" / (key + ".native.json"), 64 * 1024 * 1024)
        require(terminal["status"] == native["status"] == "completed", "ALL_INVOCATIONS_COMPLETED_REQUIRED")
        generation = native["identity"]["session_id"]
        require(generation not in generations and native["stdout"]["size"] > 0
                and native["cleanup"]["leader_reaped"] is True
                and native["cleanup"]["group_signals_completed"] is True,
                "OBSERVED_FRESH_ENGINEERING_GENERATION_REQUIRED")
        generations.add(generation)
        flow = read_json(run / "ledger" / (key + ".gateway.json"), 8 * 1024 * 1024)
        require(flow["observation_complete"] and flow["required_stamps"], "ACTUAL_STDIO_GATEWAY_RECEIPT_REQUIRED")
        if invocation["mode"] == "required_only":
            require(not flow["context_calls"] and not flow["final_reads"] and not flow["captures"], "NO_OFF_OPTIONAL_EXPOSURE")
    preflight_events = evaluation._trace_events(frozen, run, "preflight-one", "producer")
    captures = [item["exchange"] for item in preflight_events if item.get("stage") == "gateway_wire"
                and item["exchange"].get("stage") == "response" and item["exchange"].get("path") == "/api/capture"]
    require(len(captures) == 1 and captures[0]["http_status"] == 202 and captures[0]["response_complete"] is True
            and captures[0]["request_body"]["size"] > 0 and captures[0]["response_body"]["size"] > 0,
            "REAL_CAPTURE_202_BYTES_REQUIRED")
    return {"producer_http_native_mcp_preflight": True, "separate_preflight_binding": True,
            "actual_gateway_stdio": True, "all_attempts": 5, "coding_arms": 2, "valid_pairs": 1,
            "retrieval_final_reads": 2, "fresh_engineering_generations": len(generations),
            "correct_noop_wrong_external_controls": True, "all_blackbox_cases": True,
            "unchanged_corpus_rules": True, "on_off_scope": True, "unknown_costs_preserved": True,
            "strict_scorer_report": True}


async def exercise_health_link(root: Path, run: Path, expected: str, store, actor, binding: str) -> dict:
    evidence = await asyncio.to_thread(
        evaluation_health.load_evaluation_health_evidence, run, expected_manifest_sha256=expected)
    pending = await store.inspect(actor, binding, "health")
    require(len(pending["items"]) == 1, "ONE_OBSERVED_HEALTH_WORK_REQUIRED")
    work = await store.inspect(actor, binding, pending["items"][0]["ref"])
    command = HealthAssessmentCommand(
        binding_id=binding, expected_binding_revision=work["binding_revision"],
        idempotency_key="engineering-explicit-evaluation-health",
        admission_id=work["admission"]["id"], pending_id=work["pending_id"],
        health_manifest_digest=work["health_manifest_digest"],
        input_sources=work["input_sources"], input_claims=work["input_claims"],
        assessments=[{"claim_ref": target, "support": "unknown", "freshness": "unknown",
                      "relevance": "unknown",
                      "reason": "Engineering task success does not establish memory truth or human approval."}
                     for target in work["input_claims"]])
    snapshot = evidence.manifest.config["gateway"]["required_request"].get("snapshot")
    views = {target.id: await store.inspect(actor, binding, "health:claim:" + target.id, snapshot=snapshot)
             for target in command.input_claims}

    def link(retained, live_views, live_work, pin=expected):
        return evaluation_health.compile_evaluation_health_assessment(
            retained, command, current_health_views=live_views, current_health_work=live_work,
            expected_manifest_sha256=pin)

    linked = await asyncio.to_thread(link, evidence, views, work)
    require(linked.command.evaluation_receipt_digest == digest_bytes(evidence.report_bytes),
            "COMPLETE_EVALUATION_REPORT_DIGEST_REQUIRED")
    altered_report = decode_json(evidence.report_bytes)
    altered_report["retrieval_diagnostics"]["evidence_provenance"]["independence"] = "independently_approved"
    partial = deepcopy(views)
    partial[command.input_claims[0].id]["coverage"]["complete"] = False
    revised = deepcopy(views)
    revised[command.input_claims[0].id]["claim"]["revision"] += 1
    wrong_work = deepcopy(work)
    wrong_work["health_manifest_digest"] = "0" * 64
    refusals = (
        (evidence, views, work, "0" * 64, "EVALUATION_HEALTH_EXPECTED_MANIFEST"),
        (replace(evidence, report_bytes=canonical_bytes(altered_report)), views, work, expected,
         "EVALUATION_HEALTH_REPORT_CONFLICT"),
        (evidence, partial, work, expected, "EVALUATION_HEALTH_DEPENDENCY_MISMATCH_OR_PARTIAL"),
        (evidence, revised, work, expected, "EVALUATION_HEALTH_LIVE_CLAIM_MISMATCH"),
        (evidence, views, wrong_work, expected, "EVALUATION_HEALTH_WORK_MANIFEST_SCOPE"),
    )
    for retained, live_views, live_work, pin, code in refusals:
        try:
            await asyncio.to_thread(link, retained, live_views, live_work, pin)
        except evaluation_health.EvaluationHealthError as error:
            require(str(error) == code, "EXACT_EVALUATION_HEALTH_REFUSAL_REQUIRED")
        else:
            raise ValueError("FORGED_EVALUATION_HEALTH_ACCEPTED")
    records = dict(evidence.records)
    preflight_id = evidence.manifest.workload["preflight"]["invocation_id"]
    prefix = "ledger/" + digest_bytes(preflight_id.encode())
    other = next(item for item in evidence.manifest.workload["invocations"] if item["phase"] == "retrieval")
    foreign = records["ledger/" + digest_bytes(other["invocation_id"].encode()) + ".native-tool-link.json"]
    altered = decode_json(records[prefix + ".native-tool-link.json"])
    altered["links"][0]["gateway_written_sha256"] = "0" * 64
    native_refusals = (foreign, canonical_bytes(altered))
    for replacement in native_refusals:
        changed = dict(records)
        changed[prefix + ".native-tool-link.json"] = replacement
        terminal = decode_json(records[prefix + ".terminal.json"])
        terminal["evidence_refs"]["native_tool_link"] = digest_bytes(replacement)
        changed[prefix + ".terminal.json"] = canonical_bytes(terminal)
        ledger = {name: decode_json(raw) for name, raw in changed.items()
                  if name.startswith("ledger/") and name.endswith((".intent.json", ".terminal.json", ".gateway.json"))}
        forged_report = evaluation._report_from_records(evidence.manifest, ledger, adjudication=changed.get("adjudication.json"))
        retained = replace(evidence, records=tuple(sorted(changed.items())), report_bytes=canonical_bytes(forged_report))
        try:
            await asyncio.to_thread(link, retained, views, work)
        except evaluation_health.EvaluationHealthError as error:
            require(str(error) == "EVALUATION_HEALTH_NATIVE_TOOL_LINK_UNKNOWN", "EXACT_NATIVE_LINK_REFUSAL_REQUIRED")
        else:
            raise ValueError("FOREIGN_OR_UNWRITTEN_NATIVE_LINK_ACCEPTED")
    path = root / "explicit-health-command.json"
    save(path, command.model_dump(mode="json"))
    result = await cli(
        root, "health-evaluation", ["apply-evaluation", "--run-dir", str(run), "--command-file", str(path),
                                  "--expected-sha256", expected], 60, command="health",
        global_arguments=("--config", str(root / "settings.private.json"),
                          "--token-file", str(root / "operator.token")))
    require(result["operation"]["state"] == "health_recorded", "ACTUAL_HEALTH_CLI_API_COMMIT_REQUIRED")
    event = await store.inspect(actor, binding, "health:event:" + result["operation"]["artifact_id"])
    require(event["payload"]["evaluation_receipt_digest"] == digest_bytes(evidence.report_bytes),
            "PERSISTED_COMPLETE_REPORT_LINK_REQUIRED")
    for target in command.input_claims:
        current = await store.inspect(actor, binding, "health:claim:" + target.id, snapshot=snapshot)
        require(current["health"]["support"] == current["health"]["freshness"] == "unknown"
                and current["health"]["operator_review"] is None,
                "TASK_SUCCESS_MUST_NOT_INVENT_MEMORY_TRUTH_OR_HUMAN_APPROVAL")
    return {"explicit_evaluation_health_link": True, "no_automatic_health_or_human_approval": True,
            "forged_evidence_refused": len(refusals), "native_tool_event_mapping": True,
            "native_link_forgeries_refused": len(native_refusals)}


def reconcile_verifiers(run: Path, frozen: evaluation.EvaluationManifest) -> bool:
    complete = True
    runtime_spec = evaluation._runtime(frozen.document("runtime"))
    invocations = frozen.workload["invocations"]
    expected = {item["invocation_id"] for item in invocations}
    expected.update(evaluation._pair_verifier_id(frozen, item) for item in invocations if item["phase"] == "coding")
    root = run / "verifiers"
    if not root.exists():
        require(not root.is_symlink(), "VERIFIER_ROOT_SCOPE")
        return True
    descriptor = open_private_directory(root)
    try:
        names = os.listdir(descriptor)
    finally:
        os.close(descriptor)
    require(len(names) <= 4096 and set(names) <= expected, "EXACT_VERIFIER_DIRECTORY_REQUIRED")
    for name in sorted(names):
        directory = root / name
        descriptor = open_private_directory(directory)
        os.close(descriptor)
        owners = list(directory.glob("*.owner.json"))
        require(0 < len(owners) <= 16, "EXACT_VERIFIER_OWNER_REQUIRED")
        for path in owners:
            raw = read_json(path)
            owner = EvaluationOwner(**raw["owner"])
            owner.require_actions()
            require(raw["runtime"] == runtime_spec.digest and path.name == owner.identity + ".owner.json",
                    "EXACT_RUNTIME_OWNER_REQUIRED")
            runtime = DockerRuntime(runtime_spec, owner, directory)
            try:
                runtime.preflight()
                observations = runtime.reconcile_all(maximum_entries=32768, maximum_intents=4096)
                require(isinstance(observations, tuple), "RECONCILE_OBSERVATION_TYPE")
                complete = complete and all(item.exact_absence and not item.pending_create for item in observations)
            finally:
                runtime.close()
    return complete


async def exercise_optional_pair_drift(args, root, measured, preflight, corpus, gold, rules, pre_rules, runtime_raw, store, actor):
    private_directory(root)
    _, run, frozen = freeze_manifest(root, measured, preflight, corpus, gold, rules, pre_rules, args, runtime_raw,
                                    native_root=admitted_root() / "pair-drift-native")
    first_done = asyncio.Event()
    release = threading.Event()
    stop = threading.Event()
    loop = asyncio.get_running_loop()
    first = {}
    errors = []
    approved = task = None
    outcome = {}
    original = evaluation._run_one

    def actual_arm(manifest, run_dir, invocation, *, enabled, stop_event=None, pair_controls=None):
        result = original(manifest, run_dir, invocation, enabled=enabled, stop_event=stop_event, pair_controls=pair_controls)
        if invocation["phase"] == "coding" and not first:
            first.update(invocation=invocation, result=result, inventory=ledger_snapshot(run_dir))
            loop.call_soon_threadsafe(first_done.set)
            require(release.wait(30), "PAIR_DRIFT_OWNED_BOUNDARY_UNRELEASED")
        return result

    evaluation._run_one = actual_arm
    boundary = asyncio.create_task(first_done.wait())
    try:
        task = asyncio.create_task(asyncio.to_thread(evaluation.run_evaluation, frozen, run, stop_event=stop))
        await asyncio.wait({boundary, task}, return_when=asyncio.FIRST_COMPLETED)
        if not first_done.is_set():
            await asyncio.shield(task)
            raise SmokeFailure("PAIR_DRIFT_REAL_FIRST_ARM_UNREACHED")
        require(first["result"]["status"] == "completed" and first["result"]["comparable"] is True
                and first["result"]["functional_success"] is True
                and first["result"]["cleanup_complete"] is True, "PAIR_DRIFT_FIRST_ARM_NOT_REAL_SUCCESS")
        proposal = await store.propose_rule(actor, RuleProposal(
            binding_id=measured["binding_id"], idempotency_key="engineering-between-arm-optional",
            body="An independently approved optional condition changed between arms.", required=False))
        approved = await store.approve_rule(actor, RuleApproval(
            proposal_id=proposal["proposal_id"], expected_digest=proposal["digest"],
            scope=RuleScope.LOCAL_PROJECT, target_bindings=(measured["binding_id"],),
            target_set_revision=proposal["target_set_revision"], idempotency_key="engineering-between-arm-approve"))
        release.set()
        report = await asyncio.shield(task)
        before_report = ledger_snapshot(run)
        reported = evaluation.report_evaluation(run)
        require(report == reported and ledger_snapshot(run) == before_report, "PAIR_DRIFT_REPORT_NOT_READONLY")
        require(all(before_report.get(name) == digest for name, digest in first["inventory"].items()),
                "PAIR_DRIFT_EXISTING_ATTEMPT_CHANGED")
        _, arms, retrieval = evaluation.load_report_inputs(run)
        invocations = frozen.workload["invocations"]
        terminals = [evaluation._read_terminal(frozen, run, invocation) for invocation in invocations]
        require(len(arms) == 2 and len(retrieval) == 2 and len(terminals) == 5
                and all(isinstance(item, dict) for item in terminals), "PAIR_DRIFT_ALL_ATTEMPTS_NOT_RETAINED")
        first_arm = next(arm for arm in arms if arm.invocation_id == first["invocation"]["invocation_id"])
        second_arm = next(arm for arm in arms if arm.invocation_id != first_arm.invocation_id)
        second = next(item for item in invocations if item["invocation_id"] == second_arm.invocation_id)
        require(first_arm.status == "completed" and first_arm.comparable and first_arm.functional_success is True
                and second_arm.status == "blocked" and not second_arm.comparable
                and "APPLICABLE_RULE_SET_OR_CONTENT_DRIFT" in second_arm.comparability_reasons
                and not Path(second["native"]["cwd"]).exists(), "PAIR_DRIFT_SECOND_ARM_WAS_ADMITTED")
        require(report["coding"]["pair_attempts"] == 1 and report["coding"]["valid_pair_attempts"] == 0
                and report["coding"]["retry_pair_attempts"] == 0 and report["coding"]["missing_arms"] == 0,
                "PAIR_DRIFT_INCOMPARABLE_PAIR_HIDDEN")
        require(report["controller"]["preflight"]["status"] == "completed"
                and report["controller"]["preflight"]["comparable"] is True
                and sum(item["status"] == "completed" for item in terminals) == 4
                and sum(item["status"] == "blocked" for item in terminals) == 1
                and report["original18_completed"] == 0, "PAIR_DRIFT_REAL_PREFLIGHT_OR_DENOMINATOR_MISSING")
        outcome = {
            "complete": True, "all_attempts": 5, "completed_attempts": 4, "blocked_attempts": 1,
            "coding_arms": 2, "pair_attempts": 1, "valid_pairs": 0, "retry_pairs": 0,
            "first_terminal_preserved": True, "second_native_spawned": False, "report_readonly": True,
            "actual_optional_approval_between_completed_arms": True,
            "synthetic_native_protocol_peer": True, "native_acceptance": False, "original18_completed": 0,
        }
    except BaseException as error:
        errors.append(error)
    finally:
        stop.set()
        release.set()
        boundary.cancel()
        await asyncio.gather(boundary, return_exceptions=True)
        if task is not None:
            try:
                await asyncio.shield(task)
            except BaseException as error:
                if all(error is not existing for existing in errors):
                    errors.append(error)
        evaluation._run_one = original
        if approved is not None:
            try:
                withdrawn = await store.withdraw_rule(actor, measured["binding_id"], approved.id, "engineering-between-arm-withdraw")
                require(withdrawn["state"] == "withdrawn", "PAIR_DRIFT_OWNED_RULE_NOT_WITHDRAWN")
                outcome["owned_rule_withdrawn_after_recording"] = True
            except BaseException as error:
                errors.append(error)
        try:
            absent = await asyncio.to_thread(reconcile_verifiers, run, frozen)
            require(absent, "PAIR_DRIFT_OWNED_VERIFIER_CLEANUP_INCOMPLETE")
            outcome["owned_verifiers_exact_absent"] = True
        except BaseException as error:
            errors.append(error)
    outcome["complete"] = not errors and outcome.get("complete") is True
    save(root / "pair-drift-result.json", outcome)
    if errors:
        raise BaseExceptionGroup("Real engineering pair drift or owned cleanup failed", errors)
    return outcome


async def smoke(args, root: Path, summary: dict) -> None:
    import asyncpg
    import uvicorn

    admin = store = server = serving = listener = None
    schema_created = False
    schema = "am_evaluation_" + secrets.token_hex(16)
    frozen = run = None
    try:
        identity, before = source_identity(args.wheel, args.expected_wheel_sha256, args.consumption)
        summary["identity"] = identity
        runtime_path = Path(os.environ["AGENTS_MEMORY_EVALUATION_RUNTIME_SPEC"])
        runtime_raw = private_read(runtime_path, 4 * 1024 * 1024)
        runtime_spec = evaluation._runtime(decode_json(runtime_raw))
        summary["identity"].update(runtime_digest=runtime_spec.digest,
            runtime_spec_sha256=digest_bytes(runtime_raw), image_id_digest=digest_bytes(runtime_spec.image_id.encode()),
            tool_identity=runtime_spec.tool_identity, docker_sha256=runtime_spec.docker_sha256)
        raw_dsn = os.environ.get("PG_TEST_DSN")
        require(raw_dsn, "PG_TEST_DSN_REQUIRED")
        parts = urlsplit(raw_dsn)
        query = dict(parse_qsl(parts.query))
        query.pop("schema", None)
        admin_dsn = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
        save(root / "schema-intent.json", {"schema": 1, "name": schema,
             "run_id": os.environ["GITHUB_RUN_ID"], "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"], "job_id": os.environ["GITHUB_JOB"]})
        admin = await asyncpg.connect(admin_dsn, timeout=10, command_timeout=30)
        require(not await admin.fetchval("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=$1)", schema),
                "OWNED_SCHEMA_COLLISION")
        schema_created = True
        try:
            await admin.execute(f'CREATE SCHEMA "{schema}"')
        except asyncpg.DuplicateSchemaError:
            schema_created = False
            raise
        save(root / "schema-created.json", {"schema": 1, "name": schema})
        query["schema"] = schema
        dsn = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
        await asyncio.to_thread(migrate, dsn)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        settings = Settings(deployment_id="evaluation_smoke", realm="engineering_smoke", mode="personal",
            database_dsn=dsn, migrator_dsn=dsn, state_dir=root / "authority", journal_dir=root / "journal",
            port=listener.getsockname()[1])
        save(root / "settings.private.json", settings.model_dump(mode="json"))
        store = Store(settings, DeletionJournal(settings.journal_dir, settings.deployment_id))
        await store.open()
        operator_token = "engineering-evaluation-operator-" + secrets.token_hex(32)
        actor = await store.bootstrap(operator_token, "evaluation_owner")
        save(root / "operator.token", operator_token.encode())
        bindings = {}
        channels = {}
        for phase, rules_file in (
            ("measured", "rules"), ("preflight", "preflight_rules"),
            ("drift_measured", "rules"), ("drift_preflight", "preflight_rules"),
        ):
            binding = await store.register_binding(actor, "Engineering " + phase, None, "engineering-" + phase)
            actor = await store.authenticate(operator_token)
            bindings[phase] = binding.id
            files = {}
            for role in (Role.AGENT, Role.PRODUCER):
                token = "engineering-" + phase + "-" + role.value + "-" + secrets.token_hex(32)
                await store.issue_token(actor, role, (binding.id,), token)
                files[role.value] = root / (phase + "-" + role.value + ".token")
                save(files[role.value], token.encode())
            channels[phase] = channel(settings, binding.id, files, phase, rules_file=rules_file)
            proposal = await store.propose_rule(actor, RuleProposal(binding_id=binding.id,
                idempotency_key="engineering-" + phase + "-proposal", body="Keep synthetic credentials offline.", required=True))
            await store.approve_rule(actor, RuleApproval(proposal_id=proposal["proposal_id"], expected_digest=proposal["digest"],
                scope=RuleScope.LOCAL_PROJECT, target_bindings=(binding.id,), target_set_revision=proposal["target_set_revision"],
                idempotency_key="engineering-" + phase + "-approval"))
        require(bindings["measured"] != bindings["preflight"], "SEPARATE_BINDINGS_REQUIRED")
        actor = await store.authenticate(operator_token)
        for phase in ("measured", "drift_measured"):
            await store.health(actor, HealthPolicyCommand(
                binding_id=bindings[phase], expected_binding_revision=1,
                idempotency_key="engineering-health-enable", expected_policy_revision=0, enabled=True))
        for phase, directory, workspace_id, intent in (
            ("measured", "health-project", "workspace_engineering_evaluation", "health-workspace-registration-intent.json"),
            ("drift_measured", "drift-health-project", "workspace_engineering_pair_drift", "drift-workspace-registration-intent.json"),
        ):
            health_project = root / directory
            private_directory(health_project)
            producer = await store.authenticate(private_read(
                Path(channels[phase]["producer"]["token_file"]), 4096).decode())
            registration = HealthWorkspaceCommand(
                binding_id=bindings[phase], expected_binding_revision=1,
                idempotency_key="engineering-workspace-register", workspace_id=workspace_id,
                expected_workspace_revision=0, root_fingerprint=pin_root(health_project, secrets.token_hex(32)).fingerprint,
                producer_credential_id=producer.credential_id)
            save(root / intent, registration.model_dump(mode="json"))
            await store.health(actor, registration)
        server = uvicorn.Server(uvicorn.Config(create_app(settings), access_log=False, log_level="critical"))
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        async with asyncio.timeout(20):
            while not server.started:
                if serving.done():
                    await serving
                    raise ValueError("ACTUAL_PRODUCT_START_FAILED")
                await asyncio.sleep(0.01)
        evidence = root / "preparation-evidence"
        private_directory(evidence)
        corpus, gold, rules = await asyncio.to_thread(prepare_corpus, channels["measured"], evidence)
        def preflight_rules(selected):
            gateway = fixture_gateway(selected, lambda value: save(evidence / ("preflight-" + secrets.token_hex(8) + ".json"),
                canonical_bytes(evaluation._private_value(value))),
                invocation_id="engineering-preflight-rules-" + selected["binding_id"])
            try:
                response = gateway.call_tool("memory_required_context", selected["required_request"])
                require(not response.get("isError"), "PREFLIGHT_REQUIRED_CONTEXT_FAILED")
                return sorted(decode_json(response["content"][0]["text"].encode())["stamp"]["rules"])
            finally:
                gateway.close()
        pre_rules = await asyncio.to_thread(preflight_rules, channels["preflight"])
        require(rules["rules"] and pre_rules, "REAL_REQUIRED_RULES_REQUIRED")
        manifest, run, frozen = freeze_manifest(root, channels["measured"], channels["preflight"], corpus, gold,
                                               rules, pre_rules, args, runtime_raw,
                                               native_root=root.parent.parent / "full-smoke-native")
        expected = digest_bytes(manifest.read_bytes())
        common = ["--manifest", str(manifest), "--run-dir", str(run), "--expected-sha256", expected]
        await cli(root, "prepare", ["prepare", *common], 60)
        report = await cli(root, "run", ["run", *common])
        immutable = ledger_snapshot(run)
        reported = await cli(root, "report", ["report", "--run-dir", str(run)], 60)
        require(ledger_snapshot(run) == immutable, "REPORT_MUTATED_IMMUTABLE_EVIDENCE")
        controller = report.get("controller")
        preflight = controller.get("preflight") if isinstance(controller, dict) else None
        if isinstance(preflight, dict):
            observed = {}
            summary["preflight_observed"] = observed
            for key in ("status", "code"):
                value = preflight.get(key)
                observed[key] = value if isinstance(value, str) and re.fullmatch(
                    r"[A-Za-z][A-Za-z0-9_]{0,79}", value) else None
            comparable = preflight.get("comparable")
            observed["comparable"] = comparable if type(comparable) is bool else None
            reasons = preflight.get("comparability_reasons")
            observed["reason_codes"] = [
                value for value in reasons[:16]
                if isinstance(value, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", value)
            ] if isinstance(reasons, list) else None
            references = preflight.get("evidence_refs")
            if isinstance(references, dict) and isinstance(references.get("native"), str):
                preflight_identity = frozen.workload["preflight"]["invocation_id"]
                raw = evaluation._read(run / "ledger" / (
                    digest_bytes(preflight_identity.encode()) + ".native.json"), frozen.config["trace_bytes"], private=True)
                require(digest_bytes(raw) == references["native"], "NATIVE_DIAGNOSTIC_DIGEST_INVALID")
                native = decode_json(raw)
                errors = base64.b64decode(native["stderr"]["$bytes"], validate=True)
                require(len(errors) == native["stderr"]["size"]
                        and digest_bytes(errors) == native["stderr"]["sha256"], "NATIVE_STDERR_DIGEST_INVALID")
                error_types = {
                    "AssertionError", "BrokenResourceError", "CancelledError", "ClosedResourceError",
                    "EndOfStream", "ExceptionGroup", "FileNotFoundError", "ImportError", "KeyError",
                    "MCPError", "ModuleNotFoundError", "RuntimeError", "TimeoutError", "TypeError",
                    "ValidationError", "ValueError",
                }
                text = errors.decode("utf-8", errors="replace")
                observed["native_exit_code"] = native["exit_code"]
                observed["native_stdout_bytes"] = native["stdout"]["size"]
                observed["native_stderr_bytes"] = len(errors)
                observed["stderr_error_types"] = sorted(kind for kind in error_types if re.search(
                    r"(?m)^[\s|+]*(?:[A-Za-z_][A-Za-z0-9_.]*\.)?" + kind + r"(?::|$)", text))
                peer_path = re.escape(str(root / "engineering-claude-protocol-peer"))
                observed["peer_frame_lines"] = [int(value) for value in re.findall(
                    r'File "' + peer_path + r'", line (\d+)', text)[:16]]
        outcomes = assert_results(run, manifest, report, reported)
        summary["outcomes"] = outcomes
        outcomes.update(await exercise_health_link(root, run, expected, store, actor, bindings["measured"]))
        require(ledger_snapshot(run) == immutable, "HEALTH_LINK_MUTATED_RETAINED_EVALUATION")
        drift_evidence = root / "pair-drift-preparation"
        private_directory(drift_evidence)
        drift_corpus, drift_gold, drift_rules = await asyncio.to_thread(prepare_corpus, channels["drift_measured"], drift_evidence)
        drift_pre_rules = await asyncio.to_thread(preflight_rules, channels["drift_preflight"])
        summary["pair_drift"] = await exercise_optional_pair_drift(
            args, root / "optional-pair-drift", channels["drift_measured"], channels["drift_preflight"],
            drift_corpus, drift_gold, drift_rules, drift_pre_rules, runtime_raw, store, actor)
        _, after = source_identity(args.wheel, args.expected_wheel_sha256, args.consumption)
        require(before == after, "CONSUMED_SOURCE_CHANGED")
        outcomes["source_unchanged"] = True
        summary["manifest_digest"] = expected
        summary["report_digest"] = digest_bytes(canonical_bytes(reported))
        summary["evidence_inventory_digest"] = digest_bytes(canonical_bytes(immutable))
        summary["complete"] = True
    except BaseException:
        retain_failure(root, "failure.private.txt", summary["owned_cleanup"])
        raise
    finally:
        cleanup = summary["owned_cleanup"]
        if frozen is not None and run is not None:
            try:
                cleanup["verifiers_exact_absent"] = await asyncio.to_thread(reconcile_verifiers, run, frozen)
            except BaseException:
                retain_failure(root, "verifier-cleanup-failure.private.txt", cleanup)
                cleanup["verifiers_exact_absent"] = False
        if server is not None:
            server.should_exit = True
        if serving is not None:
            try:
                await asyncio.wait_for(asyncio.shield(serving), 20)
                cleanup["product_service_stopped"] = serving.done() and not serving.cancelled() and serving.exception() is None
            except BaseException:
                retain_failure(root, "service-cleanup-failure.private.txt", cleanup)
                cleanup["product_service_stopped"] = False
                if not serving.done():
                    serving.cancel()
                    await asyncio.gather(serving, return_exceptions=True)
        if listener is not None:
            listener.close()
        if store is not None:
            try:
                await store.close()
                cleanup["store_closed"] = True
            except BaseException:
                retain_failure(root, "store-cleanup-failure.private.txt", cleanup)
                cleanup["store_closed"] = False
        if admin is not None:
            try:
                if schema_created:
                    save(root / "schema-drop-intent.json", {"schema": 1, "name": schema})
                    await admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
                    cleanup["schema_exact_absent"] = not await admin.fetchval("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=$1)", schema)
                    save(root / "schema-cleanup.json", {"name": schema, "exact_absence": cleanup["schema_exact_absent"]})
                await admin.close(timeout=10)
            except BaseException:
                retain_failure(root, "schema-cleanup-failure.private.txt", cleanup)
                cleanup["schema_exact_absent"] = False
        cleanup["private_evidence_retained"] = True
        cleanup["complete"] = all(cleanup.get(name) is True for name in
            ("verifiers_exact_absent", "product_service_stopped", "store_closed", "schema_exact_absent")) and cleanup.get("failure_evidence_publication_complete", True)
        summary["complete"] = summary["complete"] and cleanup["complete"]
        summary["code"] = "COMPLETED" if summary["complete"] else "INCOMPLETE"
        save(root / "smoke-terminal.json", summary)


def main() -> int:
    parser = argparse.ArgumentParser(description="Actions-only real engineering evaluation smoke; never original/native acceptance")
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--expected-wheel-sha256", required=True)
    parser.add_argument("--consumption", choices=("source", "installed"), required=True)
    parser.add_argument("--result-dir", type=Path, default=Path(".ci-results"))
    args = parser.parse_args()
    summary = {"schema": 1, "complete": False, "tested_sha": None,
               "scope": "engineering", "synthetic_native_protocol_peer": True,
               "native_acceptance": False, "original18_completed": 0,
               "outcomes": {}, "owned_cleanup": {"complete": False}, "code": "NOT_STARTED"}
    root = None
    result = None
    try:
        state = admitted_root()
        require(re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", os.environ.get("CI_TESTED_SHA", "")), "TESTED_SHA_REQUIRED")
        summary["tested_sha"] = os.environ["CI_TESTED_SHA"]
        os.umask(0o077)
        require(args.result_dir == Path(".ci-results"), "EXACT_BODY_FREE_RESULT_DIRECTORY_REQUIRED")
        result_dir = Path(__file__).resolve().parents[2] / ".ci-results"
        if not result_dir.exists():
            private_directory(result_dir)
        descriptor = os.open(result_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            information = os.fstat(descriptor)
            require(information.st_uid == os.getuid() and not information.st_mode & 0o022,
                    "PUBLIC_RESULT_DIRECTORY_DENIED")
        finally:
            os.close(descriptor)
        result = result_dir / "evaluation-smoke.json"
        require(not result.exists() and not result.is_symlink(), "RESULT_ALREADY_EXISTS")
        root = state / "verifier" / "full-smoke"
        private_directory(root)
        args.wheel = args.wheel.absolute()
        save(root / "smoke-intent.json", {"schema": 1, "run_id": os.environ["GITHUB_RUN_ID"],
            "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"], "job_id": os.environ["GITHUB_JOB"],
            "helper_sha256": digest_bytes(Path(__file__).read_bytes()), "scope": "engineering-only-not-native-acceptance"})
        with (root / "runtime-output.private").open("xb") as stream:
            log = PrivateLog(stream)
            with redirect_stdout(log), redirect_stderr(log):
                asyncio.run(smoke(args, root, summary))
        summary["code"] = "COMPLETED" if summary["complete"] else "OWNED_CLEANUP_INCOMPLETE"
    except BaseException as error:
        summary["complete"] = False
        summary["code"] = "EVALUATION_SMOKE_FAILED"
        summary["error_type"] = type(error).__name__ if type(error).__name__ in {
            "ValueError", "OSError", "TimeoutError", "RuntimeError", "DomainError", "EvaluationError",
            "RuntimeRefusal", "CancelledError", "KeyboardInterrupt", "SystemExit", "SmokeFailure", "EvaluationHealthError",
            "TypeError", "KeyError", "NameError", "AttributeError", "UnboundLocalError", "ArtifactError",
            "FileExistsError", "FileNotFoundError", "PermissionError", "NotADirectoryError",
            "ImportError", "ModuleNotFoundError", "UnsupportedOperation"} else "BoundaryError"
        summary["failure_code"] = error.code if isinstance(error, SmokeFailure) else "SMOKE_EXCEPTION"
        if isinstance(error, DomainError) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", error.code):
            summary["failure_code"] = error.code
        if isinstance(error, evaluation_health.EvaluationHealthError) and re.fullmatch(
                r"[A-Z][A-Z0-9_]{0,79}", str(error)):
            summary["failure_code"] = str(error)
        frame = error.__traceback__
        lines = []
        while frame is not None and len(lines) < 16:
            if frame.tb_frame.f_code.co_filename == __file__:
                lines.append(frame.tb_lineno)
            frame = frame.tb_next
        summary["failure_helper_lines"] = lines
    if result is not None:
        try:
            save(result, summary)
        except (OSError, ValueError):
            summary["complete"] = False
            summary["code"] = "RESULT_PUBLICATION_FAILED"
    sys.stdout.buffer.write(canonical_bytes(summary) + b"\n")
    return 0 if summary["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
