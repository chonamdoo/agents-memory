from __future__ import annotations

import hashlib
import json
import sys
import time
import uuid
from pathlib import Path

import pytest
from test_host_boundaries import installation as installation
from test_host_boundaries import native

from agents_memory import cli, health_producer, hosts
from agents_memory.domain import DomainError, EffectState
from agents_memory.health_producer import (
    configure_health_workspace,
    health_before_context,
    observe_health_workspace,
    observe_host_session,
    prepare_health_workspace,
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
    settings.state_dir.chmod(0o700)
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


def test_recovery_preserves_unknown_observation_without_resending_in_same_cycle(health_installation, monkeypatch):
    from agents_memory import recovery

    project, settings, _, receipt, endpoint, calls = health_installation
    (project / "module.py").write_bytes(b"def answer(): return 1\n")
    settings.state_dir.chmod(0o700)
    original_request = endpoint.request
    uncertain = []

    def request(route, payload):
        if route == "/api/health" and payload["kind"] == "code_observation":
            calls.append((route, payload))
            uncertain.append(payload)
            raise DomainError("SERVICE_UNAVAILABLE", "Delivery is unconfirmed", effect=EffectState.UNKNOWN)
        return original_request(route, payload)

    monkeypatch.setattr(endpoint, "request", request)
    monkeypatch.setattr(recovery, "LocalClient", lambda *args, **kwargs: endpoint)
    worker = recovery.SpoolRecovery(settings, None)
    worker.cycle()
    assert len(uncertain) == 1
    spool = ProducerSpool(
        Path(receipt["runtime_dir"]) / "capture.sqlite3", receipt["deployment_id"],
        receipt["binding_id"], receipt["spool_limit_bytes"],
    )
    try:
        assert spool.status()["pending"] == 1
    finally:
        spool.close()
    worker.cycle()
    assert len(uncertain) == 2
    assert uncertain[0] == uncertain[1]
    assert endpoint.sequence == 0


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


@pytest.mark.parametrize("ack", [
    {"id": "unconfirmed-operation", "effect": "committed"},
    None,
])
def test_registration_malformed_ack_preserves_preparation_and_current_configuration(
    health_installation, monkeypatch, capsys, ack,
):
    from agents_memory.private_io import private_write

    project, settings, receipt_path, receipt, _, _ = health_installation
    config_path = Path(receipt["runtime_dir"]) / "health-workspace.json"
    previous = config_path.read_bytes()
    preparation = health_producer.prepare_health_registration(
        receipt, "workspace-replacement", "producer-one", expected_binding_revision=1,
        expected_workspace_revision=0, idempotency_key="registration-unconfirmed",
    )
    prepared_path = project.parent / "registration-prepared.json"
    private_write(prepared_path, preparation.model_dump_json() + "\n")
    prepared = prepared_path.read_bytes()
    settings_path = project.parent / "registration-settings.json"
    private_write(settings_path, settings.model_dump_json() + "\n")

    class Endpoint:
        def request(self, route, payload):
            return ack

    monkeypatch.setattr(cli, "client_from_settings", lambda *args, **kwargs: Endpoint())
    monkeypatch.setattr(sys, "argv", [
        "agents-memory", "--config", str(settings_path), "health", "workspace-register",
        "--receipt", str(receipt_path), "--prepared-file", str(prepared_path),
    ])
    with pytest.raises(SystemExit) as refused:
        cli.main()
    assert refused.value.code == 1
    output = capsys.readouterr()
    error = json.loads(output.err)["error"]
    assert error["code"] == "HEALTH_RECEIPT_INVALID" and error["effect"] == "unknown"
    assert output.out == ""
    assert prepared_path.read_bytes() == prepared
    assert config_path.read_bytes() == previous


def test_unchanged_code_observation_reuses_committed_identity_but_changed_bytes_do_not(health_installation):
    project, _, _, receipt, endpoint, _ = health_installation
    source = project / "module.py"
    source.write_bytes(b"def answer(): return 1\n")
    first = health_before_context(receipt)
    second = health_before_context(receipt)
    assert first["state"] == second["state"] == "observed"
    assert second["operation_id"] == first["operation_id"]
    assert endpoint.sequence == 1
    source.write_bytes(b"def answer(): return 2\n")
    changed = health_before_context(receipt)
    assert changed["operation_id"] != first["operation_id"]
    assert endpoint.sequence == 2

def test_explicit_observation_outwaits_background_owner_while_hooks_never_block(health_installation):
    import fcntl
    import os
    import threading

    project, _, _, receipt, endpoint, _ = health_installation
    (project / "module.py").write_bytes(b"def answer(): return 1\n")
    # The service's spool recovery holds this lock during its own bounded observation.
    held = os.open(Path(receipt["runtime_dir"]) / "health.lock", os.O_RDWR)
    fcntl.flock(held, fcntl.LOCK_EX)
    try:
        with pytest.raises(DomainError) as hook:
            health_before_context(receipt)
        assert hook.value.code == "HEALTH_OBSERVER_BUSY"
        with pytest.raises(DomainError) as exhausted:
            health_before_context(receipt, lock_wait=0.2)
        assert exhausted.value.code == "HEALTH_OBSERVER_BUSY"
        assert endpoint.sequence == 0
        release = threading.Timer(0.3, lambda: fcntl.flock(held, fcntl.LOCK_UN))
        release.start()
        try:
            observed = health_before_context(receipt, lock_wait=health_producer.EXPLICIT_LOCK_WAIT_SECONDS)
        finally:
            release.join()
    finally:
        os.close(held)
    assert observed["state"] == "observed"
    assert endpoint.sequence == 1



@pytest.mark.parametrize("effect", [EffectState.NOT_STARTED, EffectState.NOT_COMMITTED])
def test_proven_uncommitted_code_quarantine_allows_a_new_current_observation(
    health_installation, monkeypatch, effect,
):
    project, _, _, receipt, endpoint, calls = health_installation
    (project / "module.py").write_bytes(b"def answer(): return 1\n")
    original = endpoint.request

    def reject_observation(route, payload):
        if route == "/api/health" and payload["kind"] == "code_observation":
            calls.append((route, payload))
            raise DomainError("HEALTH_STALE", "Registration was not used", effect=effect)
        return original(route, payload)

    monkeypatch.setattr(endpoint, "request", reject_observation)
    assert observe_health_workspace(receipt)["code"] == "HEALTH_OBSERVATION_UNCOMMITTED"
    first = next(payload for route, payload in calls if route == "/api/health")
    monkeypatch.setattr(endpoint, "request", original)
    current = health_before_context(receipt)
    assert current["state"] == "observed"
    observations = [payload for route, payload in calls
                    if route == "/api/health" and payload["kind"] == "code_observation"]
    assert observations[-1]["sequence"] > first["sequence"]
    assert observations[-1]["idempotency_key"] != first["idempotency_key"]
    spool = ProducerSpool(Path(receipt["runtime_dir"]) / "capture.sqlite3",
        receipt["deployment_id"], receipt["binding_id"], receipt["spool_limit_bytes"])
    try:
        assert spool.disposition(first["idempotency_key"])["state"] == "quarantined"
        assert spool.disposition(observations[-1]["idempotency_key"])["state"] == "committed"
    finally:
        spool.close()


def test_bounded_session_metadata_cannot_starve_current_code_or_authorization(health_installation):
    project, _, _, receipt, endpoint, _ = health_installation
    endpoint.linked = []
    observe_health_workspace(receipt)
    results = [observe_host_session(receipt, {
        "key": f"{index:064x}", "root": f"omp:bounded-{index}",
        "path": f"{index + 64:064x}", "limited": False,
    }, "session_start", client=endpoint) for index in range(24)]
    assert any(result.get("code") == "HEALTH_STATE_FULL" for result in results)
    endpoint.linked = [{"relative_path": "module.py", "symbol_names": ["answer"]}]
    (project / "module.py").write_bytes(b"def answer(): return 1\n")
    assert health_before_context(receipt)["state"] == "observed"
    assert endpoint.sequence == 1
    spool = ProducerSpool(Path(receipt["runtime_dir"]) / "capture.sqlite3",
        receipt["deployment_id"], receipt["binding_id"], receipt["spool_limit_bytes"])
    try:
        assert spool.read_health_state("session:" + f"{0:064x}")["stream_id"]
        assert spool.read_health_state("authorization")["enabled"] is True
    finally:
        spool.close()


@pytest.mark.parametrize("scenario", ["expired", "receipt_pruned", "committed_ack_lost", "workspace_changed"])
def test_expired_code_delivery_recovers_current_observation_without_erasing_history(
    health_installation, monkeypatch, scenario,
):
    from agents_memory.spool import PAYLOAD_RETENTION_SECONDS, RECEIPT_RETENTION_SECONDS

    project, _, _, receipt, endpoint, calls = health_installation
    source = project / "module.py"
    source.write_bytes(b"def answer(): return 1\n")
    if scenario == "workspace_changed":
        assert health_before_context(receipt)["state"] == "observed"
    else:
        assert observe_health_workspace(receipt, defer_flush=True)["state"] == "queued"
    spool = ProducerSpool(Path(receipt["runtime_dir"]) / "capture.sqlite3",
        receipt["deployment_id"], receipt["binding_id"], receipt["spool_limit_bytes"])
    original = endpoint.request
    try:
        prior = spool.read_health_state("code")
        if scenario != "workspace_changed":
            def failed_delivery(route, payload):
                if route == "/api/health":
                    if scenario == "committed_ack_lost":
                        original(route, payload)
                    raise DomainError("SERVICE_UNAVAILABLE", "Delivery completion is unconfirmed", effect=EffectState.UNKNOWN)
                return original(route, payload)

            monkeypatch.setattr(endpoint, "request", failed_delivery)
            assert spool.flush(endpoint)["pending"] == 1
            now = time.time()
            spool.db.execute("UPDATE outbox SET created_at=?,expires_at=? WHERE key=?",
                (now - PAYLOAD_RETENTION_SECONDS - 1, now - 1, prior["key"]))
            assert spool.disposition(prior["key"])["state"] == "expired"
            assert spool.status()["gaps"]["SPOOL_PAYLOAD_EXPIRED"] == 1
            monkeypatch.setattr(endpoint, "request", original)
        if scenario in {"receipt_pruned", "workspace_changed"}:
            spool.db.execute("UPDATE receipts SET created_at=? WHERE key=?",
                (time.time() - RECEIPT_RETENTION_SECONDS - 1, prior["key"]))
            with pytest.raises(DomainError) as missing:
                spool.disposition(prior["key"])
            assert missing.value.code == "SPOOL_REPLAY_EXPIRED_OR_UNKNOWN"
    finally:
        spool.close()
    if scenario == "workspace_changed":
        config, _ = prepare_health_workspace(receipt, "workspace-replacement", "producer-one",
            expected_binding_revision=1, expected_workspace_revision=0, idempotency_key="replacement-workspace")
        configure_health_workspace(receipt, config)
        endpoint.sequence = 0

        def current_workspace(route, payload):
            result = original(route, payload)
            if route == "/api/health/observer":
                result["workspaces"][0].update(
                    workspace_id=config.workspace_id, root_fingerprint=config.pin.fingerprint,
                )
            return result

        monkeypatch.setattr(endpoint, "request", current_workspace)
    source.write_bytes(b"def answer(): return 2\n")
    current = health_before_context(receipt)
    assert current["state"] == "observed"
    observations = [payload for route, payload in calls
                    if route == "/api/health" and payload["kind"] == "code_observation"]
    latest = observations[-1]
    assert latest["sequence"] > prior["sequence"]
    assert latest["idempotency_key"] != prior["key"]
    assert latest["files"][0]["file_digest"] == hashlib.sha256(source.read_bytes()).hexdigest()
    if scenario == "workspace_changed":
        assert latest["workspace_id"] == config.workspace_id
    reopened = ProducerSpool(Path(receipt["runtime_dir"]) / "capture.sqlite3",
        receipt["deployment_id"], receipt["binding_id"], receipt["spool_limit_bytes"])
    try:
        assert reopened.disposition(latest["idempotency_key"])["state"] == "committed"
        if scenario in {"expired", "committed_ack_lost"}:
            assert reopened.disposition(prior["key"])["state"] == "expired"
        if scenario != "workspace_changed":
            assert reopened.status()["gaps"]["SPOOL_PAYLOAD_EXPIRED"] == 1
    finally:
        reopened.close()
