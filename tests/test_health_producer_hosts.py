from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import pytest
from test_host_boundaries import installation as installation
from test_host_boundaries import native

from agents_memory import health_producer, hosts
from agents_memory.domain import DomainError, EffectState
from agents_memory.health_producer import (
    configure_health_workspace, health_before_context, observe_health_workspace,
    observe_host_session, prepare_health_workspace,
)
from agents_memory.spool import ProducerSpool


@pytest.fixture
def health_installation(installation, monkeypatch, request):
    project, settings, _, _, install = installation
    receipt_path = install(getattr(request, "param", "claude"), strict=False, prompt_recall=True)
    receipt = hosts.load_receipt(receipt_path)
    config, registration = prepare_health_workspace(
        receipt, "workspace-one", "producer-one", expected_binding_revision=1,
        expected_workspace_revision=0, idempotency_key="workspace-registration", next_agent=True,
    )
    configure_health_workspace(receipt, config)
    calls = []

    class Endpoint:
        online = True
        enabled = True
        sequence = 0
        linked = [{"relative_path": "module.py", "symbol_names": ["answer"]}]

        def request(self, route, payload):
            calls.append((route, payload))
            if not self.online:
                raise DomainError("SERVICE_UNAVAILABLE", "No source diagnostics", effect=EffectState.UNKNOWN)
            if route == "/api/health/observer":
                return {
                    "kind": "health_observer", "binding_id": receipt["binding_id"],
                    "binding_revision": 1, "max_http_body_bytes": 65536,
                    "coverage": {"complete": True, "scope": "producer_scoped_metadata"},
                    "policy": {"revision": 1, "enabled": self.enabled, "allow_jev_health": False},
                    "workspaces": [{
                        "workspace_id": config.workspace_id, "revision": 1,
                        "root_fingerprint": registration.root_fingerprint,
                        "producer_credential_id": config.producer_credential_id,
                        "last_sequence": self.sequence, "linked_paths": self.linked,
                        "current_observations": [], "coverage": {"complete": True, "gaps": []},
                    }],
                }
            if route == "/api/health":
                if payload["kind"] == "code_observation":
                    self.sequence = payload["sequence"]
                return {
                    "id": "operation:" + uuid.uuid4().hex, "binding_id": receipt["binding_id"],
                    "kind": payload["kind"], "state": "health_recorded", "epoch": 1,
                    "artifact_id": "health:" + uuid.uuid4().hex, "effect": "committed",
                }
            if route in {"/api/context", "/api/required-context"}:
                text = '{"approved_rules":[],"memory_candidates":[],"relations":[]}'
                return {
                    "context": text, "context_bytes": len(text.encode()), "refs": [],
                    "stamp": {"epoch": 1, "rules": []}, "status": "ready",
                    **({"required": False} if route == "/api/required-context" else {}),
                }
            if route == "/api/capture":
                return {"id": "capture-operation", "effect": "committed"}
            raise AssertionError("Unexpected fixed route")

    endpoint = Endpoint()
    monkeypatch.setattr(health_producer, "_client", lambda receipt: endpoint)
    monkeypatch.setattr(hosts, "LocalClient", lambda *args, **kwargs: endpoint)
    return project, settings, receipt_path, receipt, endpoint, calls


def test_file_change_is_observed_before_actual_next_native_context(health_installation):
    project, _, path, _, endpoint, calls = health_installation
    first = b"def answer(): return 1\n"
    second = b"def answer(): return 2\n"
    (project / "module.py").write_bytes(first)
    one = hosts.handle_hook(path, native(project, prompt="Find the project convention.", prompt_id="prompt-one"))
    assert one["state"] in {"ok", "degraded"}
    (project / "module.py").write_bytes(second)
    two = hosts.handle_hook(path, native(project, prompt="Find the convention again.", prompt_id="prompt-two"))
    assert two["state"] in {"ok", "degraded"}
    observations = [(index, payload) for index, (route, payload) in enumerate(calls)
                    if route == "/api/health" and payload["kind"] == "code_observation"]
    contexts = [(index, payload) for index, (route, payload) in enumerate(calls) if route == "/api/context"]
    assert len(observations) == len(contexts) == 2
    assert observations[0][0] < contexts[0][0] < observations[1][0] < contexts[1][0]
    assert observations[0][1]["files"][0]["file_digest"] == hashlib.sha256(first).hexdigest()
    assert observations[1][1]["files"][0]["file_digest"] == hashlib.sha256(second).hexdigest()
    assert all(payload["code_workspace_id"] == "workspace-one" for _, payload in contexts)
    assert "pending_may_exist" in str(two["stdout"])
    assert "return 1" not in str(calls) and "return 2" not in str(calls)
    assert endpoint.sequence == 2


def test_offline_observation_prevents_ordinary_context_dispatch(health_installation):
    project, _, path, _, endpoint, calls = health_installation
    (project / "module.py").write_bytes(b"def answer(): return 1\n")
    endpoint.online = False
    result = hosts.handle_hook(path, native(project, prompt="Recall conventions."))
    assert result["code"] == "SERVICE_UNAVAILABLE"
    assert not any(route == "/api/context" for route, _ in calls)
    assert "return 1" not in str(result)


def test_disabled_policy_performs_no_code_egress_or_next_agent_hint(health_installation):
    project, _, path, _, endpoint, calls = health_installation
    (project / "module.py").write_bytes(b"private_code_body = True\n")
    endpoint.enabled = False
    result = hosts.handle_hook(path, native(project, prompt="Recall conventions."))
    assert not any(route == "/api/health" for route, _ in calls)
    assert "pending_may_exist" not in str(result["stdout"])
    assert "private_code_body" not in str(calls)


def test_end_manifest_keeps_offline_capture_origin_and_unknown_child_root(health_installation):
    _, _, _, receipt, endpoint, calls = health_installation
    endpoint.linked = []
    assert observe_health_workspace(receipt)["state"] == "observed"
    identity = {"key": "a" * 64, "root": None, "path": "b" * 64, "limited": False}
    assert observe_host_session(receipt, identity, "session_start")["state"] == "durably_spooled"
    assert observe_host_session(receipt, identity, "capture_origin", origin_key="offline-capture")["state"] == "durably_spooled"
    assert observe_host_session(receipt, identity, "session_shutdown")["state"] == "durably_spooled"
    assert observe_host_session(receipt, identity, "session_shutdown")["state"] == "already_closed"
    spool = ProducerSpool(Path(receipt["runtime_dir"]) / "capture.sqlite3",
                          receipt["deployment_id"], receipt["binding_id"], receipt["spool_limit_bytes"])
    try:
        assert spool.flush(endpoint)["pending"] == 0
    finally:
        spool.close()
    sessions = [payload for route, payload in calls if route == "/api/health" and payload["kind"] == "session_observation"]
    assert [event["event"] for event in sessions] == ["start", "checkpoint", "end"]
    assert [event["sequence"] for event in sessions] == [1, 2, 3]
    assert sessions[-1]["origin_keys"] == ["offline-capture"]
    assert sessions[-1]["source_refs"] == []
    assert sessions[-1]["root_run_id"] is None
    assert sessions[-1]["coverage"] == "partial"
    assert "HOST_ROOT_LINEAGE_UNOBSERVED" in sessions[-1]["gaps"]
    assert "transcript" not in str(sessions).lower()


def test_resume_rotates_segment_without_faking_uninterrupted_coverage(health_installation):
    _, _, _, receipt, endpoint, calls = health_installation
    endpoint.linked = []
    observe_health_workspace(receipt)
    identity = {"key": "a" * 64, "root": "omp:main-session", "path": "b" * 64, "limited": False}
    observe_host_session(receipt, identity, "session_start")
    observe_host_session(receipt, identity, "session_before_compact")
    observe_host_session(receipt, identity, "session_compact", client=endpoint)
    sessions = [payload for route, payload in calls if route == "/api/health" and payload["kind"] == "session_observation"]
    assert [event["event"] for event in sessions] == ["start", "interrupted", "resume"]
    assert sessions[0]["stream_id"] == sessions[2]["stream_id"]
    assert sessions[0]["segment_id"] != sessions[2]["segment_id"]
    assert "HOST_OBSERVATION_DISCONTINUITY" in sessions[2]["gaps"]


def test_observer_partial_linked_paths_is_not_current_context_proof(health_installation):
    _, _, _, receipt, endpoint, _ = health_installation
    endpoint.linked = [{"relative_path": f"missing-{index}.py", "symbol_names": []} for index in range(33)]
    with pytest.raises(DomainError) as caught:
        health_before_context(receipt)
    assert caught.value.code in {"HEALTH_OBSERVATION_PARTIAL", "HEALTH_OBSERVATION_UNCOMMITTED", "SPOOL_FULL"}


def test_recovery_observes_changed_linked_file_without_a_new_host_event(health_installation, monkeypatch):
    from agents_memory import recovery

    project, settings, _, _, endpoint, calls = health_installation
    (project / "module.py").write_bytes(b"def answer(): return 1\n")
    monkeypatch.setattr(recovery, "LocalClient", lambda *args, **kwargs: endpoint)
    worker = recovery.SpoolRecovery(settings, None)
    worker.cycle()
    before = [payload for route, payload in calls if route == "/api/health" and payload["kind"] == "code_observation"]
    assert len(before) == 1
    (project / "module.py").write_bytes(b"def answer(): return 2\n")
    worker.cycle()
    after = [payload for route, payload in calls if route == "/api/health" and payload["kind"] == "code_observation"]
    assert len(after) == 2
    assert before[0]["files"][0]["file_digest"] != after[1]["files"][0]["file_digest"]
    worker._stop.set()
    previous_calls = len(calls)
    worker.cycle()
    assert len(calls) == previous_calls


def test_actual_relay_context_is_observed_and_scoped_before_send(health_installation, monkeypatch):
    from agents_memory.stdio import RelayEndpoint, StdioRelay

    project, _, path, receipt, _, calls = health_installation
    (project / "module.py").write_bytes(b"def answer(): return 1\n")
    relay = StdioRelay(RelayEndpoint(
        receipt["base_url"], state_dir=Path(receipt["runtime_dir"]).parent.parent,
        deployment_id=receipt["deployment_id"], health_receipt=path,
    ), Path(receipt["agent_token_file"]))
    forwarded = []

    def send(message, *, deadline):
        forwarded.append(message)
        return {"jsonrpc": "2.0", "id": message["id"], "result": {}}, False

    monkeypatch.setattr(relay, "_send", send)
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": "memory_context", "arguments": {"query": "Conventions"}}}
    assert "result" in relay.forward(request)
    assert forwarded[0]["params"]["arguments"]["code_workspace_id"] == "workspace-one"
    assert any(route == "/api/health" for route, _ in calls)
    forwarded.clear()
    denied = {**request, "id": 2, "params": {**request["params"],
              "arguments": {"query": "Conventions", "code_workspace_id": "another-workspace"}}}
    assert relay.forward(denied)["error"]["message"] == "HEALTH_WORKSPACE_SCOPE"
    assert not forwarded


def test_actual_relay_never_sends_context_after_uncommitted_observation(health_installation, monkeypatch):
    from agents_memory.stdio import RelayEndpoint, StdioRelay

    project, _, path, receipt, endpoint, _ = health_installation
    (project / "module.py").write_bytes(b"def answer(): return 1\n")
    endpoint.online = False
    relay = StdioRelay(RelayEndpoint(
        receipt["base_url"], state_dir=Path(receipt["runtime_dir"]).parent.parent,
        deployment_id=receipt["deployment_id"], health_receipt=path,
    ), Path(receipt["agent_token_file"]))
    sent = []
    monkeypatch.setattr(relay, "_send", lambda *args, **kwargs: sent.append(args))
    result = relay.forward({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                            "params": {"name": "memory_context", "arguments": {"query": "Conventions"}}})
    assert result["error"]["message"] == "SERVICE_UNAVAILABLE"
    assert result["error"]["data"]["effect"] == "not_started"
    assert sent == []


@pytest.mark.parametrize("health_installation", ["omp"], indirect=True)
def test_actual_input_capture_and_close_share_body_free_origin_watermark(health_installation):
    project, _, path, receipt, endpoint, calls = health_installation
    endpoint.linked = []
    hosts.handle_hook(path, native(project, "omp", "session_start"))
    captured = hosts.handle_hook(path, native(project, "omp", "input",
                                              text="Only the authorized prompt window.", source="interactive"))
    assert captured["capture"]["state"] == "committed"
    hosts.handle_hook(path, native(project, "omp", "session_shutdown"))
    spool = ProducerSpool(Path(receipt["runtime_dir"]) / "capture.sqlite3",
                          receipt["deployment_id"], receipt["binding_id"], receipt["spool_limit_bytes"])
    try:
        spool.flush(endpoint)
    finally:
        spool.close()
    sources = [payload for route, payload in calls if route == "/api/capture"]
    ends = [payload for route, payload in calls
            if route == "/api/health" and payload["kind"] == "session_observation" and payload["event"] == "end"]
    assert len(sources) == len(ends) == 1
    assert sources[0]["origin_key"] in ends[0]["origin_keys"]
    assert ends[0]["source_refs"] == []
    assert ends[0]["coverage"] == "partial"
    assert "Only the authorized prompt window." not in str(ends)
    assert "Only the authorized prompt window." in sources[0]["body"]


def test_late_capture_pointer_updates_closed_segment_without_reopening_it(health_installation):
    from datetime import UTC, datetime

    _, _, _, receipt, endpoint, calls = health_installation
    endpoint.linked = []
    observe_health_workspace(receipt)
    identity = {"key": "a" * 64, "root": "omp:root", "path": "b" * 64, "limited": False}
    observe_host_session(receipt, identity, "session_start")
    observe_host_session(receipt, identity, "capture_origin", origin_key="late-origin")
    observe_host_session(receipt, identity, "session_shutdown")
    pointer = {
        "source_id": "late-source", "source_revision": 1, "binding_id": receipt["binding_id"],
        "binding_revision": 1, "snapshot": None, "source_speaker": "human",
        "source_event_time": None, "source_recorded_at": datetime.now(UTC).isoformat(),
        "byte_length": 8, "coverage": {"status": "observed_window", "original_bytes": 8,
                                    "gaps": ["HOST_SESSION_WINDOW_UNOBSERVED"], "provenance": "producer_reported"},
    }
    observed = observe_host_session(receipt, identity, "capture_replay", origin_key="late-origin",
                                    source_pointer=pointer, client=endpoint)
    assert observed["state"] == "durably_spooled"
    assert observe_host_session(receipt, identity, "session_shutdown")["state"] == "already_closed"
    events = [payload for route, payload in calls if route == "/api/health" and payload["kind"] == "session_observation"]
    assert [payload["event"] for payload in events] == ["start", "checkpoint", "end", "checkpoint"]
    assert len({payload["segment_id"] for payload in events}) == 1
    assert events[-1]["source_refs"] == [{"id": "late-source", "revision": 1}]
    assert events[-1]["origin_keys"] == ["late-origin"]
