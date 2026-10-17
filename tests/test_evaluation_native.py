from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
from dataclasses import replace

import pytest

from agents_memory.evaluation_native import (
    NativeDriverSpec,
    _Protocol,
    _ProtocolError,
    run_native_arm,
)

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Owned native protocol peers require POSIX")


def spec_for(tmp_path, backend="codex", peer=""):
    work = tmp_path / "task"
    work.mkdir()
    output = tmp_path / "controller"
    output.mkdir(mode=0o700)
    executable = tmp_path / "protocol-peer"
    executable.write_text("#!" + sys.executable + "\n" + peer)
    executable.chmod(0o700)
    return NativeDriverSpec(
        backend=backend, executable=executable, cwd=work, submission_path=work / "submission.json",
        authorization_ref="engineering-peer-not-native-approval", context_observation_ref="synthetic-peer-context",
        approved_context=True, gateway_invocation_id="invocation", gateway_route_ref="synthetic-route",
        exclusive_optional_route_observed=False, residual_memory_absence_observed=False,
        fresh_generation_observed=True, timeout_seconds=3, cleanup_seconds=0.3,
        max_input_bytes=8192, max_stdout_bytes=65536, max_stderr_bytes=4096,
        max_record_bytes=8192, max_events=100, max_submission_bytes=65536,
    ), output / "artifact.json"


def codex_peer(body, *, before_started=""):
    return '''import json, pathlib, sys
assert sys.argv[1:] == ['app-server']
def read():
    return json.loads(sys.stdin.readline())
def emit(value):
    print(json.dumps(value), flush=True)
def reply(request, result):
    emit({'id': request['id'], 'result': result})
request = read()
assert request['method'] == 'initialize'
reply(request, {'userAgent': 'engineering-protocol-peer'})
assert read()['method'] == 'initialized'
request = read()
assert request['method'] == 'thread/start'
assert set(request['params']) == {'cwd'}
reply(request, {'thread': {'id': 'thread-one'}, 'model': 'peer-model', 'approvalPolicy': 'on-request'})
request = read()
assert request['method'] == 'turn/start'
assert set(request['params']) == {'threadId', 'input', 'outputSchema'}
reply(request, {'turn': {'id': 'turn-one'}})
''' + before_started + '''
emit({'method': 'turn/started', 'params': {'threadId': 'thread-one', 'turn': {'id': 'turn-one'}}})
''' + body


def test_codex_actual_stdio_peer_cumulative_usage_and_immutable_submission(tmp_path):
    peer = codex_peer('''
for count in [10, 10, 20]:
    emit({'method': 'thread/tokenUsage/updated', 'params': {
        'threadId': 'thread-one', 'tokenUsage': {'total': {'inputTokens': count, 'outputTokens': 2}, 'last': {}}}})
path = pathlib.Path.cwd() / 'submission.json'
path.write_bytes(b'{"explicit":"submitted-bundle-bytes"}')
emit({'method': 'item/completed', 'params': {'threadId': 'thread-one', 'turnId': 'turn-one',
    'item': {'type': 'agentMessage', 'id': 'message-one', 'text': json.dumps({'submission_path': str(path)})}}})
emit({'method': 'turn/completed', 'params': {'threadId': 'thread-one', 'turn': {'id': 'turn-one', 'status': 'completed'}}})
sys.stdin.read()
''')
    spec, output = spec_for(tmp_path, peer=peer)
    traces = []
    result = run_native_arm(spec, "Engineering peer, not a live native model", invocation_id="invocation",
                            artifact_output=output, trace_sink=traces.append)
    assert result.status == "completed"
    assert result.usage["counters"] == {"inputTokens": 20, "outputTokens": 2}
    assert result.usage["cost_usd"] is None
    assert result.artifact_bundle["sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert result.cleanup["leader_reaped"] is True
    assert result.cleanup["escaped_descendants_absent"] is None
    assert not result.comparable
    assert "NATIVE_MEMORY_RESIDUAL_UNRESOLVED" in result.incomparability_reasons
    assert traces[0]["stage"] == "native_intent"
    assert b"thread-one" in result.stdout
    assert "message-one" in result.action_ids
    assert not hasattr(result, "task_success")


def test_server_permission_request_is_not_answered_and_uses_turn_interrupt(tmp_path):
    peer = codex_peer('''
emit({'id': 'approval-one', 'method': 'item/commandExecution/requestApproval', 'params': {
    'threadId': 'thread-one', 'turnId': 'turn-one', 'itemId': 'action-one', 'command': 'synthetic-private-command'}})
request = read()
assert request.get('method') == 'turn/interrupt'
assert request['params'] == {'threadId': 'thread-one', 'turnId': 'turn-one'}
reply(request, {})
emit({'method': 'turn/completed', 'params': {'threadId': 'thread-one', 'turn': {'id': 'turn-one', 'status': 'interrupted'}}})
sys.stdin.read()
''')
    spec, output = spec_for(tmp_path, peer=peer)
    result = run_native_arm(spec, "approval fixture", invocation_id="invocation", artifact_output=output, trace_sink=lambda _: None)
    assert result.status == "blocked"
    assert result.approval_requests[0]["id"] == "approval-one"
    assert result.stop["interrupt_sent"] is True
    assert result.stop["interrupted_terminal"] is True
    assert result.effect == "unknown"
    assert result.artifact_bundle is None
    assert "synthetic-private-command" not in repr(result)


@pytest.mark.parametrize("body,code", [
    ("sys.stdout.write('{');sys.stdout.flush()\n", "PARTIAL_PROTOCOL_RECORD"),
    ("print('{bad-json}',flush=True)\n", "PROTOCOL_INVALID"),
    ("emit({'method':'item/started','params':{'threadId':'old-thread','item':{'id':'old-action'}}})\n", "STALE_GENERATION"),
])
def test_actual_peer_partial_malformed_and_stale_generation(tmp_path, body, code):
    spec, output = spec_for(tmp_path, peer=codex_peer(body))
    result = run_native_arm(spec, "fault fixture", invocation_id="invocation", artifact_output=output, trace_sink=lambda _: None)
    assert result.status == "unknown"
    assert result.code == code
    assert result.effect == "unknown"
    assert result.cleanup["leader_reaped"] is True
    assert result.artifact_bundle is None


def test_stdout_and_stderr_are_concurrently_bounded(tmp_path):
    peer = codex_peer("sys.stderr.write('private-error'*10000);sys.stderr.flush()\nsys.stdin.read()\n")
    spec, output = spec_for(tmp_path, peer=peer)
    result = run_native_arm(spec, "output fixture", invocation_id="invocation", artifact_output=output, trace_sink=lambda _: None)
    assert result.code == "OUTPUT_LIMIT"
    assert result.output_truncated
    assert len(result.stderr) == spec.max_stderr_bytes
    assert b"private-error" in result.stderr
    assert "private-error" not in repr(result)


def test_stop_before_spawned_turn_preserves_aborted_not_task_success(tmp_path):
    spec, output = spec_for(tmp_path, peer=codex_peer("sys.stdin.read()\n"))
    stop = threading.Event()
    stop.set()
    result = run_native_arm(spec, "stop fixture", invocation_id="invocation", artifact_output=output,
                            trace_sink=lambda _: None, stop_event=stop)
    assert result.status == "aborted"
    assert result.artifact_bundle is None
    assert result.cleanup["leader_reaped"] is False
    assert result.effect == "not_started"


def test_claude_uses_normal_flags_and_records_permission_denial(tmp_path):
    peer = '''import json, sys
assert sys.argv[1:5] == ['-p', '--output-format', 'stream-json', '--verbose']
assert sys.argv[5] == '--json-schema'
assert not any(flag in sys.argv for flag in ('--allowedTools', '--permission-mode', '--mcp-config'))
sys.stdin.read()
for event in [
    {'type':'system','subtype':'init','session_id':'session-one','model':'peer-model','permissionMode':'default'},
    {'type':'result','session_id':'session-one','subtype':'error_during_execution','is_error':True,
     'permission_denials':[{'tool_use_id':'denied-action','tool_name':'Write'}],
     'usage':{'input_tokens':3,'output_tokens':1}},
]:
    print(json.dumps(event),flush=True)
'''
    spec, output = spec_for(tmp_path, backend="claude", peer=peer)
    result = run_native_arm(spec, "denial fixture", invocation_id="invocation", artifact_output=output, trace_sink=lambda _: None)
    assert result.status == "blocked"
    assert result.usage["cost_usd"] is None
    assert result.usage["basis"] == "terminal_main_loop_only"
    assert result.approval_requests[0]["tool_use_id"] == "denied-action"
    assert result.identity["permissionMode"] == "default"


def test_normal_approval_is_required_even_for_claude_print(tmp_path):
    spec, output = spec_for(tmp_path, backend="claude", peer="raise AssertionError('must not execute')\n")
    spec = replace(spec, approved_context=False)
    result = run_native_arm(spec, "blocked", invocation_id="invocation", artifact_output=output, trace_sink=lambda _: None)
    assert result.status == "blocked"
    assert result.code == "APPROVED_NORMAL_CONTEXT_REQUIRED"
    assert result.effect == "not_started"
    assert not result.stdout


def test_strict_unsupported_is_not_claimed_as_protection(tmp_path):
    spec, output = spec_for(tmp_path, peer="raise AssertionError('must not execute')\n")
    result = run_native_arm(replace(spec, strict_protection_required=True), "unsupported",
                            invocation_id="invocation", artifact_output=output, trace_sink=lambda _: None)
    assert result.status == "unsupported"
    assert result.code == "STRICT_NATIVE_CAPABILITY_UNSUPPORTED"


def test_protocol_usage_regression_is_not_summed_or_hidden(tmp_path):
    spec, _ = spec_for(tmp_path)
    protocol = _Protocol(spec, "fixture")
    protocol.thread = "thread"
    for count in (10, 10):
        protocol.consume(json.dumps({"method":"thread/tokenUsage/updated", "params": {
            "threadId":"thread", "tokenUsage":{"total":{"inputTokens":count}}}}).encode())
    assert protocol.usage["counters"]["inputTokens"] == 10
    with pytest.raises(_ProtocolError, match="USAGE_REGRESSION"):
        protocol.consume(json.dumps({"method":"thread/tokenUsage/updated", "params": {
            "threadId":"thread", "tokenUsage":{"total":{"inputTokens":9}}}}).encode())


def test_timeout_retains_all_partial_protocol_and_no_fake_usage(tmp_path):
    spec, output = spec_for(tmp_path, peer=codex_peer("sys.stderr.write('partial-private-output');sys.stderr.flush()\nsys.stdin.read()\n"))
    spec = replace(spec, timeout_seconds=0.2)
    result = run_native_arm(spec, "timeout fixture", invocation_id="invocation", artifact_output=output, trace_sink=lambda _: None)
    assert result.status == "timeout"
    assert result.effect == "unknown"
    assert result.usage["counters"] is None
    assert result.usage["cost_usd"] is None
    assert b"partial-private-output" in result.stderr
    assert result.cleanup["leader_reaped"] is True


def test_observer_failure_still_stops_owned_native_and_returns_private_output(tmp_path):
    spec, output = spec_for(tmp_path, peer=codex_peer("sys.stdin.read()\n"))
    def failing_trace(row):
        if row["stage"] == "native_event":
            raise OSError("synthetic private observer failure")
    result = run_native_arm(spec, "observer fixture", invocation_id="invocation", artifact_output=output, trace_sink=failing_trace)
    assert result.status == "unknown"
    assert result.cleanup["leader_reaped"] is True
    assert b"engineering-protocol-peer" in result.stdout
    assert "synthetic private observer failure" not in repr(result)


def test_claude_terminal_pipeline_usage_deduplicates_partial_messages(tmp_path):
    peer = '''import json, pathlib, sys
sys.stdin.read()
path = pathlib.Path.cwd() / 'submission.json'
path.write_bytes(b'{"explicit":"claude-submitted-bytes"}')
events = [
    {'type':'system','subtype':'init','session_id':'session-one','model':'peer-model',
     'claude_code_version':'engineering-peer','permissionMode':'default'},
    {'type':'assistant','session_id':'session-one','message':{
        'id':'shared-message','content':[],'usage':{'input_tokens':1,'output_tokens':1}}},
    {'type':'assistant','session_id':'session-one','message':{
        'id':'shared-message','content':[],'usage':{'input_tokens':1,'output_tokens':1}}},
    {'type':'result','session_id':'session-one','subtype':'success','is_error':False,
     'modelUsage':{'peer-model':{'inputTokens':17,'outputTokens':4,'contextWindow':100000}},
     'total_cost_usd':0.125,'structured_output':{'submission_path':str(path)}},
]
for event in events:
    print(json.dumps(event),flush=True)
'''
    spec, output = spec_for(tmp_path, backend="claude", peer=peer)
    result = run_native_arm(spec, "usage fixture", invocation_id="invocation", artifact_output=output, trace_sink=lambda _: None)
    assert result.status == "completed"
    assert result.usage["counters"] == {"inputTokens": 17, "outputTokens": 4}
    assert result.usage["cost_usd"] == 0.125
    assert result.usage["cost_basis"] == "native_client_estimate_not_bill"
    assert len(result.usage["observations"]) == 2
    assert result.artifact_bundle["bytes"] == len(output.read_bytes())


def test_immutable_submission_publication_reconciles_exact_visible_bytes(tmp_path, monkeypatch):
    from agents_memory import evaluation_native

    spec, output = spec_for(tmp_path)
    spec.submission_path.write_bytes(b'{"explicit":"submitted-bytes"}')
    protocol = _Protocol(spec, "publication fixture")
    protocol.structured = {"submission_path": str(spec.submission_path)}
    original = evaluation_native.private_write
    publications = []
    def visible_then_failed(path, raw, **kwargs):
        original(path, raw, **kwargs)
        publications.append(path)
        raise OSError("Synthetic directory sync failure after publication")
    monkeypatch.setattr(evaluation_native, "private_write", visible_then_failed)
    directory = os.open(spec.cwd, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        bundle = evaluation_native._publish_submission(spec, output, protocol, directory)
    finally:
        os.close(directory)
    assert publications == [output]
    assert bundle["sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert output.read_bytes() == spec.submission_path.read_bytes()


def test_cancellation_discards_unsent_turn_start(tmp_path):
    peer = codex_peer("sys.stdin.read()\n").replace(
        "request = read()\nassert request['method'] == 'turn/start'",
        "request = read()\npathlib.Path('received-turn.json').write_text(json.dumps(request))\n"
        "assert request['method'] == 'turn/start'",
    )
    spec, output = spec_for(tmp_path, peer=peer)
    stop = threading.Event()
    def cancel_on_thread_response(row):
        if row["stage"] == "native_event" and row["event_index"] == 1:
            stop.set()
    result = run_native_arm(spec, "cancel queued startup", invocation_id="invocation",
                            artifact_output=output, trace_sink=cancel_on_thread_response, stop_event=stop)
    assert result.status == "aborted"
    assert b"thread-one" in result.stdout
    assert not (spec.cwd / "received-turn.json").exists()
    assert result.artifact_bundle is None
    assert result.cleanup["leader_reaped"] is True


def test_cancellation_terminates_partial_turn_start_without_finishing_frame(tmp_path, monkeypatch):
    from agents_memory import evaluation_native

    spec, output = spec_for(tmp_path, peer=codex_peer("sys.stdin.read()\n"))
    stop = threading.Event()
    original_write = evaluation_native.os.write
    startup_writes = []
    def write_partial_start(fd, raw):
        if b'"method":"turn/start"' in raw and not startup_writes:
            count = original_write(fd, raw[:16])
            startup_writes.append(bytes(raw[:count]))
            stop.set()
            return count
        count = original_write(fd, raw)
        if stop.is_set():
            startup_writes.append(bytes(raw[:count]))
        return count
    monkeypatch.setattr(evaluation_native.os, "write", write_partial_start)
    result = run_native_arm(spec, "cancel partial startup", invocation_id="invocation",
                            artifact_output=output, trace_sink=lambda _: None, stop_event=stop)
    assert startup_writes and len(startup_writes[0]) == 16
    assert len(startup_writes) == 1
    assert b"\n" not in startup_writes[0]
    assert result.status == "aborted"
    assert result.stop["interrupt_sent"] is False
    assert result.cleanup["leader_reaped"] is True
    assert result.artifact_bundle is None


def test_completed_turn_with_unterminated_trailing_record_cannot_publish(tmp_path):
    peer = codex_peer('''
import signal
path = pathlib.Path.cwd() / 'submission.json'
path.write_bytes(b'{"explicit":"unpublished-submission"}')
events = [
    {'method': 'item/completed', 'params': {'threadId': 'thread-one', 'turnId': 'turn-one',
        'item': {'type': 'agentMessage', 'id': 'message-one', 'text': json.dumps({'submission_path': str(path)})}}},
    {'method': 'turn/completed', 'params': {'threadId': 'thread-one',
        'turn': {'id': 'turn-one', 'status': 'completed'}}},
]
sys.stdout.write(''.join(json.dumps(event) + '\\n' for event in events) + '{')
sys.stdout.flush()
signal.pause()
''')
    spec, output = spec_for(tmp_path, peer=peer)
    result = run_native_arm(spec, "trailing partial fixture", invocation_id="invocation",
                            artifact_output=output, trace_sink=lambda _: None)
    assert b'"status": "completed"' in result.stdout
    assert result.stdout.endswith(b"{")
    assert result.status == "unknown"
    assert result.code == "PARTIAL_PROTOCOL_RECORD"
    assert result.effect == "unknown"
    assert result.artifact_bundle is None
    assert not output.exists()
    assert spec.submission_path.read_bytes() == b'{"explicit":"unpublished-submission"}'
    assert result.cleanup["leader_reaped"] is True


def test_closed_native_stdin_does_not_claim_interrupt_transmission(tmp_path):
    peer = codex_peer("import signal\nsignal.pause()\n", before_started="import os\nos.close(0)\n")
    spec, output = spec_for(tmp_path, peer=peer)
    stop = threading.Event()
    def cancel_on_started_turn(row):
        if row["stage"] == "native_event" and row["event_index"] == 3:
            stop.set()
    result = run_native_arm(spec, "closed interrupt pipe", invocation_id="invocation",
                            artifact_output=output, trace_sink=cancel_on_started_turn, stop_event=stop)
    assert result.stop["requested"] is True
    assert result.stop["interrupt_sent"] is False
    assert result.status != "completed"
    assert result.effect == "unknown"
    assert result.cleanup["leader_reaped"] is True
    assert result.artifact_bundle is None


@pytest.mark.parametrize("variant", ["nested", "intermediate-symlink", "root-symlink", "root-replaced", "hardlink"])
def test_native_submission_stays_in_the_original_approved_root(tmp_path, variant):
    peer = codex_peer(f'''
root = pathlib.Path.cwd()
outside = root.parent / 'outside'
outside.mkdir()
outside_file = outside / 'submission.json'
outside_file.write_bytes(b'{{"scope":"outside-approved-root"}}')
path = root / 'nested' / 'submission.json'
variant = {variant!r}
if variant in ('root-symlink', 'root-replaced'):
    root.rename(root.parent / 'moved-task')
    if variant == 'root-symlink':
        (outside / 'nested').mkdir()
        (outside / 'nested' / 'submission.json').write_bytes(outside_file.read_bytes())
        root.symlink_to(outside, target_is_directory=True)
    else:
        root.mkdir()
        path.parent.mkdir()
        path.write_bytes(outside_file.read_bytes())
elif variant == 'intermediate-symlink':
    path.parent.symlink_to(outside, target_is_directory=True)
else:
    path.parent.mkdir()
    if variant == 'hardlink':
        import os
        os.link(outside_file, path)
    else:
        path.write_bytes(b'{{"scope":"approved-nested-submission"}}')
emit({{'method':'item/completed','params':{{'threadId':'thread-one','turnId':'turn-one',
    'item':{{'type':'agentMessage','id':'nested-message','text':json.dumps({{'submission_path':str(path)}})}}}}}})
emit({{'method':'turn/completed','params':{{'threadId':'thread-one','turn':{{'id':'turn-one','status':'completed'}}}}}})
sys.stdin.read()
''')
    spec, output = spec_for(tmp_path, peer=peer)
    spec = replace(spec, submission_path=spec.cwd / "nested" / "submission.json")
    result = run_native_arm(spec, "Engineering handoff path fixture, not native approval",
        invocation_id="invocation", artifact_output=output, trace_sink=lambda _: None)
    assert result.cleanup["leader_reaped"] is True
    if variant == "nested":
        assert result.status == "completed"
        assert output.read_bytes() == b'{"scope":"approved-nested-submission"}'
    else:
        assert result.status == "unknown" and not result.comparable
        assert result.artifact_bundle is None and not output.exists()
        assert (tmp_path / "outside" / "submission.json").read_bytes() == b'{"scope":"outside-approved-root"}'


def test_native_submission_parent_backtracking_is_not_an_approved_task_path(tmp_path):
    spec, _ = spec_for(tmp_path)
    with pytest.raises(ValueError):
        replace(spec, submission_path=spec.cwd / ".." / "outside" / "submission.json")
