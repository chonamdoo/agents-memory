from __future__ import annotations

import io
import json
import socket
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from agents_memory.client import LocalClient
from agents_memory.connection import RemoteClientSettings
from agents_memory.domain import DomainError, EffectState
from agents_memory.readiness import ensure_local_ready, ensure_remote_ready
from agents_memory.stdio import RelayEndpoint, StdioRelay


@pytest.fixture
def endpoint(monkeypatch):
    state = {"ready": True, "db_ready": True, "deployment_id": "local-owned", "realm": "personal",
             "gets": 0, "posts": [], "recoveries": [], "failures": 0, "disconnect": False}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.path == "/readyz"
            state["gets"] += 1
            if state.get("redirect"):
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1:9/not-the-owned-service")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            public = {key: state[key] for key in ("ready", "db_ready", "deployment_id", "realm")}
            if state["failures"]:
                state["failures"] -= 1
                public.update(ready=False, db_ready=False)
            raw = json.dumps(public).encode()
            self.send_response(200 if public["ready"] else 503)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):
            message = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["posts"].append((self.path, message))
            if state["disconnect"]:
                self.close_connection = True
                return
            if self.path == "/mcp":
                result = {"jsonrpc": "2.0", "id": message["id"], "result": {"protocolVersion": "2025-11-25"}}
            else:
                result = {"effect": "committed", "id": "operation-one"}
            raw = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass

    def recover(base_url, state_dir, deployment_id, *, deadline=None):
        assert deadline is not None
        state["recoveries"].append((base_url, state_dir, deployment_id))
        return True

    monkeypatch.setattr("agents_memory.service.ensure_started", recover)
    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", state
        finally:
            server.shutdown()
            worker.join()


@pytest.fixture
def credential(tmp_path):
    path = tmp_path / "producer.token"
    path.write_text("synthetic-readiness-credential")
    path.chmod(0o600)
    return path


def capture():
    return {"binding_id": "binding-one", "idempotency_key": "stable-key", "origin_key": "stable-origin",
            "speaker": "human", "body": "Retain this exact keyed source locally."}


def test_readiness_recovers_then_waits_for_database_before_dispatch(endpoint, credential, tmp_path):
    url, state = endpoint
    state["failures"] = 1
    client = LocalClient(url, credential, timeout=1, state_dir=tmp_path, deployment_id="local-owned")
    assert client.request("/api/capture", capture())["effect"] == "committed"
    assert state["gets"] == 2
    assert state["recoveries"] == [(url, tmp_path, "local-owned")]
    assert state["posts"] == [("/api/capture", capture())]


@pytest.mark.parametrize("change", [{"ready": False, "db_ready": False}, {"db_ready": False}, {"deployment_id": "other-deployment"}])
def test_client_never_dispatches_when_authority_unavailable(endpoint, credential, change):
    url, state = endpoint
    state.update(change)
    with pytest.raises(DomainError) as refused:
        LocalClient(url, credential, timeout=0.15, deployment_id="local-owned").request("/api/capture", capture())
    assert refused.value.effect is EffectState.NOT_STARTED
    assert refused.value.status == 503
    assert state["posts"] == []


def test_manual_stop_wins_over_healthy_process(endpoint, credential, monkeypatch):
    url, state = endpoint

    def stopped(*args, **kwargs):
        raise DomainError("SERVICE_STOPPED", "Explicitly stopped", status=503)

    monkeypatch.setattr("agents_memory.service.ensure_started", stopped)
    with pytest.raises(DomainError) as refused:
        LocalClient(url, credential, deployment_id="local-owned").request("/api/context", {"query": "anything"})
    assert refused.value.code == "SERVICE_STOPPED" and refused.value.effect is EffectState.NOT_STARTED
    assert state["gets"] == 0 and state["posts"] == []


def test_unknown_mutation_effect_is_never_automatically_resent(endpoint, credential):
    url, state = endpoint
    state["disconnect"] = True
    with pytest.raises(DomainError) as refused:
        LocalClient(url, credential, timeout=0.2).request("/api/capture", capture())
    assert refused.value.effect is EffectState.UNKNOWN
    assert len(state["posts"]) == 1


def test_relay_uses_same_database_and_manual_stop_gate(endpoint, credential, monkeypatch, tmp_path):
    url, state = endpoint
    relay = StdioRelay(RelayEndpoint(url, state_dir=tmp_path, deployment_id="local-owned"), credential)
    message = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}}
    assert relay.forward(message)["result"]["protocolVersion"] == "2025-11-25"
    assert state["recoveries"] == [(url, tmp_path, "local-owned")]

    def stopped(*args, **kwargs):
        raise DomainError("SERVICE_STOPPED", "Explicitly stopped", status=503)

    monkeypatch.setattr("agents_memory.service.ensure_started", stopped)
    result = relay.forward({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert result["error"]["message"] == "SERVICE_STOPPED"
    assert result["error"]["data"]["effect"] == "not_started"
    assert len(state["posts"]) == 1
    relay.recovery_pending = True
    result = relay.forward({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    assert result["error"]["message"] == "SERVICE_STOPPED"
    assert result["error"]["data"]["effect"] == "not_started"
    assert len(state["posts"]) == 1


@pytest.mark.parametrize("url", ["https://127.0.0.1:1234", "http://example.com", "http://127.0.0.1:1234/other"])
def test_readiness_refuses_nonlocal_or_noncanonical_destination(url):
    with pytest.raises(DomainError) as denied:
        ensure_local_ready(url, timeout=0.1)
    assert denied.value.code == "DESTINATION_DENIED"


def test_readiness_cannot_redirect_to_another_destination(endpoint):
    url, state = endpoint
    state["redirect"] = True
    with pytest.raises(DomainError) as denied:
        ensure_local_ready(url, deployment_id="local-owned", timeout=0.2)
    assert denied.value.code == "DESTINATION_DENIED" and denied.value.effect is EffectState.NOT_STARTED
    assert state["gets"] == 1 and state["posts"] == []


def test_readiness_never_uses_environment_proxy(endpoint, monkeypatch):
    url, state = endpoint
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setenv("no_proxy", "")
    assert ensure_local_ready(url, deployment_id="local-owned", timeout=0.2)["db_ready"] is True
    assert state["gets"] == 1


def test_native_startup_and_http_readiness_share_one_deadline(endpoint, monkeypatch):
    url, state = endpoint
    clock = [100.0]
    monkeypatch.setattr("agents_memory.readiness.time", SimpleNamespace(
        monotonic=lambda: clock[0], sleep=lambda duration: None,
    ))

    def exhaust_native_deadline(base_url, state_dir, deployment_id, *, deadline=None):
        assert deadline == 100.25
        clock[0] = deadline
        return True

    monkeypatch.setattr("agents_memory.service.ensure_started", exhaust_native_deadline)
    with pytest.raises(DomainError) as unavailable:
        ensure_local_ready(url, deployment_id="local-owned", timeout=0.25)
    assert unavailable.value.code == "SERVICE_UNAVAILABLE"
    assert unavailable.value.effect is EffectState.NOT_STARTED
    assert state["gets"] == 0 and state["posts"] == []


@pytest.fixture
def deadline_peer(monkeypatch, tmp_path):
    from agents_memory import client, connection, readiness, stdio

    state = SimpleNamespace(
        now=0.0, responses=[], sockets=[], dns_delay=0.0, connect_delays=[], tls_delay=0.0,
        tls_hosts=[], send_delays=[],
    )
    clock = SimpleNamespace(
        monotonic=lambda: state.now,
        sleep=lambda duration: setattr(state, "now", state.now + duration),
    )
    for module in (client, connection, readiness, stdio):
        monkeypatch.setattr(module, "time", clock)
    monkeypatch.setattr("agents_memory.service.ensure_started", lambda *args, **kwargs: True)
    monkeypatch.setattr("agents_memory.service.require_client_enabled", lambda *args, **kwargs: None)

    def elapse(duration, timeout):
        if duration >= timeout:
            state.now += timeout
            raise TimeoutError("synthetic deadline")
        state.now += duration

    class RawResponse(io.RawIOBase):
        def __init__(self, owner):
            self.owner = owner

        def readable(self):
            return True

        def readinto(self, buffer):
            if not self.owner.fragments:
                return 0
            data, delay = self.owner.fragments[0]
            elapse(delay, self.owner.timeout)
            count = min(len(buffer), len(data))
            buffer[:count] = data[:count]
            if count == len(data):
                self.owner.fragments.pop(0)
            else:
                self.owner.fragments[0] = (data[count:], 0)
            return count

    class PeerSocket:
        def __init__(self):
            self.fragments = list(state.responses.pop(0))
            self.timeout = None
            self.sent = bytearray()
            self.closed = False
            self.stream = None
            state.sockets.append(self)

        def settimeout(self, timeout):
            self.timeout = timeout

        def setsockopt(self, *args):
            pass

        def connect(self, address):
            if state.connect_delays:
                duration, failure = state.connect_delays.pop(0)
                elapse(duration, self.timeout)
                if failure:
                    raise OSError("synthetic connect failure")

        def sendall(self, data):
            self.sent.extend(data)
            if state.send_delays:
                elapse(state.send_delays.pop(0), self.timeout)

        def makefile(self, mode, buffering=0):
            assert mode == "rb" and buffering == 0
            self.stream = RawResponse(self)
            return self.stream

        def close(self):
            self.closed = True

    def addresses(*args):
        state.now += state.dns_delay
        count = max(1, len(state.connect_delays))
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 8768))] * count

    def wrap_socket(sock, *, server_hostname):
        state.tls_hosts.append(server_hostname)
        elapse(state.tls_delay, sock.timeout)
        return sock

    monkeypatch.setattr(connection, "_resolve_tcp", lambda host, port, deadline: addresses(host, port))
    monkeypatch.setattr(connection, "socket", SimpleNamespace(
        SOCK_STREAM=socket.SOCK_STREAM, getaddrinfo=addresses, socket=lambda *args: PeerSocket(),
    ))
    monkeypatch.setattr(connection, "remote_ssl_context", lambda profile: SimpleNamespace(
        wrap_socket=wrap_socket, check_hostname=True, verify_mode=ssl.CERT_REQUIRED,
    ))
    directory = tmp_path / "remote-state"
    directory.mkdir(mode=0o700)
    state.profile = RemoteClientSettings(
        deployment_id="local-owned", realm="personal", mode="personal", auth_mode="bearer",
        base_url="https://localhost:8768", state_dir=directory,
    )
    state.local_url = "http://127.0.0.1:8768"
    return state


def deadline_response(stage, budget, *, status=200):
    status_line = f"HTTP/1.1 {status} Synthetic\r\n".encode()
    if stage == "status":
        prefix, slow = b"", status_line + b"Content-Length: 2\r\n\r\n{}"
    elif stage == "header":
        prefix, slow = status_line, b"X-Slow: header drip\r\nContent-Length: 2\r\n\r\n{}"
    elif stage == "body":
        prefix, slow = status_line + b"Content-Length: 11\r\n\r\n", b'{"ok":true}'
    else:
        prefix = status_line + b"Transfer-Encoding: chunked\r\n\r\n"
        if stage == "chunk-size":
            slow = b"0000000001\r\nx\r\n0\r\n\r\n"
        elif stage == "chunk-crlf":
            return [(prefix + b"1\r\nx", 0), (b"\r", budget * 0.6), (b"\n0\r\n\r\n", budget * 0.6)]
        else:
            assert stage == "trailer"
            prefix += b"0\r\n"
            slow = b"X-Slow: trailer drip\r\n\r\n"
    return ([(prefix, 0)] if prefix else []) + [(bytes([byte]), budget / 4) for byte in slow]


def ready_response():
    raw = json.dumps({
        "ready": True, "db_ready": True, "deployment_id": "local-owned", "realm": "personal",
    }).encode()
    return [(b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(raw)).encode() + b"\r\n\r\n" + raw, 0)]


@pytest.mark.parametrize("remote", [False, True], ids=["local", "remote"])
@pytest.mark.parametrize("stage", ["status", "header", "body", "chunk-size", "chunk-crlf", "trailer"])
def test_readiness_total_deadline_includes_every_http_read(deadline_peer, remote, stage):
    peer = deadline_peer
    peer.responses.append(deadline_response(stage, 0.15))
    with pytest.raises(DomainError) as failed:
        if remote:
            ensure_remote_ready(peer.profile, timeout=0.15)
        else:
            ensure_local_ready(peer.local_url, deployment_id="local-owned", timeout=0.15)
    assert failed.value.code == "SERVICE_UNAVAILABLE"
    assert failed.value.effect is EffectState.NOT_STARTED
    assert peer.now == pytest.approx(0.15)
    assert len(peer.sockets) == 1
    assert bytes(peer.sockets[0].sent).startswith(b"GET /readyz ")
    assert peer.sockets[0].closed and peer.sockets[0].stream.closed


@pytest.mark.parametrize("remote", [False, True], ids=["local", "remote"])
@pytest.mark.parametrize("consumer", ["client", "relay"])
@pytest.mark.parametrize("stage", ["status", "header", "body", "chunk-size", "chunk-crlf", "trailer"])
@pytest.mark.parametrize("status", [200, 404])
def test_dispatched_mutation_deadline_is_unknown_and_never_replayed(
    deadline_peer, credential, remote, consumer, stage, status,
):
    peer = deadline_peer
    budget = 0.15 if consumer == "client" else 120
    peer.responses.extend([ready_response(), deadline_response(stage, budget, status=status)])
    profile = peer.profile
    url = profile.base_url if remote else peer.local_url
    if consumer == "client":
        client = LocalClient(
            url, credential, timeout=budget, state_dir=profile.state_dir, deployment_id=profile.deployment_id,
            remote_settings=profile if remote else None,
        )
        with pytest.raises(DomainError) as failed:
            client.request("/api/capture", capture())
        assert failed.value.effect is EffectState.UNKNOWN
    else:
        relay = StdioRelay(RelayEndpoint(
            url, state_dir=profile.state_dir, deployment_id=profile.deployment_id,
            remote_settings=profile if remote else None,
        ), credential)
        relay.session_id = "existing-session"
        result = relay.forward({
            "jsonrpc": "2.0", "id": 71, "method": "tools/call",
            "params": {"name": "memory_capture", "arguments": capture()},
        })
        assert result["error"]["data"]["effect"] == "unknown"
        assert relay.session_id == "existing-session"
    assert peer.now == pytest.approx(budget)
    assert len(peer.sockets) == 2
    assert bytes(peer.sockets[0].sent).startswith(b"GET /readyz ")
    assert bytes(peer.sockets[1].sent).startswith(b"POST ")
    assert all(sock.closed and sock.stream.closed for sock in peer.sockets)
    assert peer.responses == []


@pytest.mark.parametrize("remote", [False, True], ids=["local", "remote"])
def test_connection_attempts_share_deadline_without_late_dispatch(deadline_peer, credential, monkeypatch, remote):
    from agents_memory import client

    peer = deadline_peer
    monkeypatch.setattr(client, "ensure_local_ready", lambda *args, **kwargs: {})
    monkeypatch.setattr(client, "ensure_remote_ready", lambda *args, **kwargs: {})
    peer.responses.extend([ready_response(), ready_response()])
    peer.connect_delays = [(0.1, True), (0.1, False)]
    profile = peer.profile
    with pytest.raises(DomainError) as failed:
        LocalClient(
            profile.base_url if remote else peer.local_url, credential, timeout=0.15,
            state_dir=profile.state_dir, deployment_id=profile.deployment_id,
            remote_settings=profile if remote else None,
        ).request("/api/capture", capture())
    assert failed.value.effect is EffectState.NOT_STARTED
    assert peer.now == pytest.approx(0.15)
    assert len(peer.sockets) == 2
    assert all(sock.closed and not sock.sent and sock.stream is None for sock in peer.sockets)


def test_tls_handshake_uses_remaining_connect_budget(deadline_peer, credential, monkeypatch):
    from agents_memory import client

    peer = deadline_peer
    monkeypatch.setattr(client, "ensure_remote_ready", lambda *args, **kwargs: {})
    peer.responses.append(ready_response())
    peer.connect_delays = [(0.1, False)]
    peer.tls_delay = 0.1
    profile = peer.profile
    with pytest.raises(DomainError) as failed:
        LocalClient(
            profile.base_url, credential, timeout=0.15, state_dir=profile.state_dir,
            deployment_id=profile.deployment_id, remote_settings=profile,
        ).request("/api/capture", capture())
    assert failed.value.effect is EffectState.NOT_STARTED
    assert peer.now == pytest.approx(0.15)
    assert peer.tls_hosts == ["localhost"]
    assert len(peer.sockets) == 1 and peer.sockets[0].closed and not peer.sockets[0].sent


def test_expired_resolution_result_never_connects_or_dispatches(deadline_peer, credential, monkeypatch):
    from agents_memory import client

    peer = deadline_peer
    monkeypatch.setattr(client, "ensure_local_ready", lambda *args, **kwargs: {})
    peer.dns_delay = 0.2
    with pytest.raises(DomainError) as failed:
        LocalClient(peer.local_url, credential, timeout=0.15).request("/api/capture", capture())
    assert failed.value.effect is EffectState.NOT_STARTED
    assert peer.now == 0.2
    assert peer.sockets == []


@pytest.mark.parametrize("remote", [False, True], ids=["local", "remote"])
def test_request_headers_and_body_share_send_deadline(deadline_peer, credential, monkeypatch, remote):
    from agents_memory import client

    peer = deadline_peer
    monkeypatch.setattr(client, "ensure_local_ready", lambda *args, **kwargs: {})
    monkeypatch.setattr(client, "ensure_remote_ready", lambda *args, **kwargs: {})
    peer.responses.append(ready_response())
    peer.send_delays = [0.1, 0.1]
    profile = peer.profile
    with pytest.raises(DomainError) as failed:
        LocalClient(
            profile.base_url if remote else peer.local_url, credential, timeout=0.15,
            state_dir=profile.state_dir, deployment_id=profile.deployment_id,
            remote_settings=profile if remote else None,
        ).request("/api/capture", capture())
    assert failed.value.effect is EffectState.UNKNOWN
    assert peer.now == pytest.approx(0.15)
    assert len(peer.sockets) == 1
    assert peer.sockets[0].closed and peer.sockets[0].stream is None
    assert bytes(peer.sockets[0].sent).startswith(b"POST /api/capture ")


@pytest.mark.parametrize("remote", [False, True], ids=["local", "remote"])
@pytest.mark.parametrize("consumer", ["client", "relay"])
def test_readiness_cannot_start_business_dispatch_after_total_deadline(
    deadline_peer, credential, monkeypatch, remote, consumer,
):
    from agents_memory import client, stdio

    peer = deadline_peer
    budget = 0.15 if consumer == "client" else 120

    def late_readiness(*args, **kwargs):
        peer.now = budget
        return {"ready": True}

    for module in (client, stdio):
        monkeypatch.setattr(module, "ensure_local_ready", late_readiness)
        monkeypatch.setattr(module, "ensure_remote_ready", late_readiness)
    profile = peer.profile
    url = profile.base_url if remote else peer.local_url
    if consumer == "client":
        instance = LocalClient(
            url, credential, timeout=budget, state_dir=profile.state_dir,
            deployment_id=profile.deployment_id, remote_settings=profile if remote else None,
        )
        with pytest.raises(DomainError) as failed:
            instance.request("/api/capture", capture())
        assert failed.value.effect is EffectState.NOT_STARTED
    else:
        relay = StdioRelay(RelayEndpoint(
            url, state_dir=profile.state_dir, deployment_id=profile.deployment_id,
            remote_settings=profile if remote else None,
        ), credential)
        result = relay.forward({
            "jsonrpc": "2.0", "id": 71, "method": "tools/call",
            "params": {"name": "memory_capture", "arguments": capture()},
        })
        assert result["error"]["data"]["effect"] == "not_started"
    assert peer.sockets == []


@pytest.mark.parametrize("remote", [False, True], ids=["local", "remote"])
def test_session_reinitialization_keeps_original_relay_deadline(deadline_peer, credential, remote):
    peer = deadline_peer
    rejection = json.dumps({
        "error": {"code": "SESSION_NOT_FOUND", "message": "gone", "effect": "not_started"},
    }).encode()
    rejected_response = [(
        b"HTTP/1.1 404 Gone\r\nContent-Length: " + str(len(rejection)).encode() + b"\r\n\r\n" + rejection, 80,
    )]
    peer.responses.extend([
        ready_response(), rejected_response, ready_response(), deadline_response("header", 40),
    ])
    profile = peer.profile
    relay = StdioRelay(RelayEndpoint(
        profile.base_url if remote else peer.local_url, state_dir=profile.state_dir,
        deployment_id=profile.deployment_id, remote_settings=profile if remote else None,
    ), credential)
    relay.session_id = "existing-session"
    relay.protocol_version = "2025-11-25"
    relay.initialize_params = {"protocolVersion": relay.protocol_version}
    result = relay.forward({
        "jsonrpc": "2.0", "id": 71, "method": "tools/call",
        "params": {"name": "memory_capture", "arguments": capture()},
    })
    assert result["error"]["message"] == "SESSION_NOT_FOUND"
    assert result["error"]["data"]["effect"] == "not_started"
    assert peer.now == 120
    assert len(peer.sockets) == 4 and peer.responses == []
    posts = [bytes(sock.sent) for sock in peer.sockets if sock.sent.startswith(b"POST ")]
    assert len(posts) == 2
    assert b'"method": "tools/call"' in posts[0]
    assert b'"method": "initialize"' in posts[1]
    assert relay.session_id is None and relay.recovery_pending
    assert all(sock.closed and sock.stream.closed for sock in peer.sockets)


def test_platform_resolution_is_bounded_and_reaps_its_helper(tmp_path, monkeypatch):
    import subprocess
    import sys

    from agents_memory import connection

    state = tmp_path / "client"
    state.mkdir(mode=0o700)
    profile = RemoteClientSettings(
        deployment_id="resolution-test", realm="personal", mode="personal", auth_mode="bearer",
        base_url="https://slow-resolver.invalid", state_dir=state,
    )
    processes = []
    spawn = subprocess.Popen

    def blocked_resolution(*args, **kwargs):
        time.sleep(2)
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 443))]

    def blocked_helper(argv, **options):
        process = spawn(
            [sys.executable, "-I", "-S", "-c", "import time; time.sleep(2)"], **options,
        )
        processes.append(process)
        return process

    monkeypatch.setattr(connection.socket, "getaddrinfo", blocked_resolution)
    monkeypatch.setattr(connection.subprocess, "Popen", blocked_helper)
    began = time.monotonic()
    try:
        with pytest.raises(DomainError) as unavailable:
            ensure_remote_ready(profile, timeout=0.1)
        elapsed = time.monotonic() - began
        reaped = all(process.poll() is not None for process in processes)
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait()
    assert unavailable.value.effect is EffectState.NOT_STARTED
    assert elapsed < 0.75
    assert reaped
