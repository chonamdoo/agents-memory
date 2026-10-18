from __future__ import annotations

import datetime
import hashlib
import io
import json
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from pydantic import ValidationError

from agents_memory.client import LocalClient, client_from_settings
from agents_memory.connection import (
    RemoteClientSettings,
    configure_remote_client,
    https_origin,
    load_connection_settings,
    load_remote_settings,
    read_remote_credential,
    validate_remote_project,
)
from agents_memory.domain import DomainError, EffectState
from agents_memory.private_io import private_write
from agents_memory.readiness import ensure_remote_ready
from agents_memory.stdio import RelayEndpoint, StdioRelay


def capture():
    return {"binding_id": "binding-one", "idempotency_key": "capture-one", "origin_key": "origin-one",
            "speaker": "human", "body": "Synthetic remote source."}


@pytest.fixture
def tls_endpoint(tmp_path):
    state_dir = tmp_path / "pc-state"
    state_dir.mkdir(mode=0o700)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
            .sign(key, hashes.SHA256()))
    ca = state_dir / "ca.pem"
    ca.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    ca.chmod(0o600)
    key_file = tmp_path / "server.key"
    key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    key_file.chmod(0o600)
    credential = tmp_path / "agent.token"
    credential.write_text("synthetic-scoped-remote-credential\n")
    credential.chmod(0o600)
    state = {"ready": True, "db_ready": True, "deployment_id": "remote-one", "realm": "personal",
             "gets": [], "posts": [], "session": "first-session", "lost": False, "version": "2025-11-25"}

    class Handler(BaseHTTPRequestHandler):
        def respond(self, value, status=200, **headers):
            raw = json.dumps(value).encode()
            if self.command == "GET" and state.get("ready_pause") == "headers":
                state["ready_started"].set()
                state["ready_release"].wait(5)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            if self.command == "GET" and state.get("ready_pause") == "body":
                state["ready_started"].set()
                state["ready_release"].wait(5)
            if state.get("drip_post") and self.command == "POST":
                try:
                    for offset in range(0, len(raw), 4):
                        self.wfile.write(raw[offset:offset + 4])
                        self.wfile.flush()
                        time.sleep(0.08)
                except OSError:
                    pass
            else:
                self.wfile.write(raw)

        def do_GET(self):
            state["gets"].append((self.path, dict(self.headers)))
            if state.get("redirect_ready"):
                self.respond({}, 302, Location="https://localhost:9/other")
                return
            self.respond({name: state[name] for name in ("ready", "db_ready", "deployment_id", "realm")})

        def do_POST(self):
            message = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["posts"].append((self.path, message, dict(self.headers)))
            if self.headers.get("Authorization") in state.get("denied_producers", ()):
                self.respond({"error": {"code": "AUTH_DENIED", "effect": "not_started", "message": "refused"}}, 401)
                return
            if state.get("post_received") is not None:
                state["post_received"].set()
                state["post_release"].wait(5)
            if state.get("post_delay"):
                time.sleep(state["post_delay"])
            if state.get("reject_credential"):
                self.respond({"error": {"code": "TOKEN_REVOKED", "effect": "not_started", "message": "refused"}}, 401)
                return
            if state.get("disconnect"):
                self.close_connection = True
                return
            if state.get("redirect_post"):
                self.respond({}, 307, Location="https://localhost:9/other")
                return
            if self.path != "/mcp":
                self.respond({"effect": "committed", "id": "operation-one"})
                return
            if state["lost"] and self.headers.get("Mcp-Session-Id"):
                state["lost"] = False
                self.respond({"error": {"code": "SESSION_NOT_FOUND", "effect": "not_started", "message": "gone"}}, 404)
                return
            if message["method"] == "initialize":
                self.respond({"jsonrpc": "2.0", "id": message["id"], "result": {"protocolVersion": state["version"]}},
                             **{"Mcp-Session-Id": state["session"]})
            elif "id" not in message:
                self.send_response(202)
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                self.respond({"jsonrpc": "2.0", "id": message["id"], "result": {"tools": []}})

        def log_message(self, *args):
            pass

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(ca, key_file)
    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        profile = RemoteClientSettings(
            deployment_id="remote-one", realm="personal", mode="personal", auth_mode="bearer",
            base_url=f"https://localhost:{server.server_port}", state_dir=state_dir,
            ca_bundle=ca, ca_bundle_sha256=hashlib.sha256(ca.read_bytes()).hexdigest(),
        )
        try:
            yield SimpleNamespace(profile=profile, token=credential, state=state, server_key=key_file)
        finally:
            server.shutdown()
            thread.join(timeout=5)


def endpoint(profile):
    return RelayEndpoint(
        profile.base_url, state_dir=profile.state_dir, deployment_id=profile.deployment_id,
        max_http_body_bytes=profile.max_http_body_bytes, max_mcp_response_bytes=profile.max_mcp_response_bytes,
        remote_settings=profile,
    )


def initialize():
    return {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}}


@pytest.mark.parametrize("url", [
    "http://example.com", "https://user@example.com", "https://example.com/path", "https://example.com/?",
    "https://example.com/#", "https://example.com\\@other.example", "https://example.com:0",
    "https://example.com:", "https://example.com./", "https://example.com\n", "https://exa_mple.com",
])
def test_remote_origin_rejects_ambiguous_or_nonroot_destinations(url):
    with pytest.raises(DomainError) as denied:
        https_origin(url)
    assert denied.value.code == "DESTINATION_DENIED"


def test_remote_origin_is_canonical():
    assert https_origin("https://EXAMPLE.com:443/") == "https://example.com"
    assert https_origin("https://[::1]:8443/") == "https://[::1]:8443"


def test_url_alone_never_enables_remote_transport(tls_endpoint):
    with pytest.raises(DomainError):
        LocalClient(tls_endpoint.profile.base_url, tls_endpoint.token)
    with pytest.raises(DomainError):
        RelayEndpoint(tls_endpoint.profile.base_url)
    assert tls_endpoint.state["gets"] == [] and tls_endpoint.state["posts"] == []


@pytest.mark.parametrize("field,value", [("database_dsn", "secret"), ("journal_dir", "/tmp/journal"),
                                        ("operator_token", "secret"), ("jev_key_file", "/tmp/key"),
                                        ("binding_id", "binding-one"), ("token_file", "/tmp/token"),
                                        ("max_http_body_bytes", "65536"), ("version", True)])
def test_remote_profile_has_no_authority_or_implicit_binding_fields(tls_endpoint, field, value):
    with pytest.raises((DomainError, ValidationError)):
        RemoteClientSettings.model_validate({**tls_endpoint.profile.model_dump(mode="json"), field: value})


def test_profile_roundtrip_and_private_ca_digest(tls_endpoint, tmp_path):
    profile = tls_endpoint.profile
    path = tmp_path / "remote.json"
    path.write_text(profile.model_dump_json())
    path.chmod(0o600)
    assert load_remote_settings(path) == profile
    assert load_connection_settings(path) == profile
    profile.ca_bundle.write_bytes(profile.ca_bundle.read_bytes() + b"\n")
    with pytest.raises(DomainError) as denied:
        load_remote_settings(path)
    assert denied.value.code == "CONFIG_INVALID"


@pytest.mark.parametrize("change", [{"kind": "server"}, {"version": 2}, {"auth_mode": None}])
def test_profile_loader_denies_other_discriminators(tls_endpoint, tmp_path, change):
    path = tmp_path / "remote.json"
    path.write_text(json.dumps({**tls_endpoint.profile.model_dump(mode="json"), **change}))
    path.chmod(0o600)
    with pytest.raises(DomainError):
        load_connection_settings(path)


def test_failed_profile_commit_allows_corrected_ca_retry(tls_endpoint, monkeypatch):
    from agents_memory import connection

    source = tls_endpoint.profile.ca_bundle
    profile = tls_endpoint.profile.model_copy(update={"ca_bundle": None, "ca_bundle_sha256": None})
    target = profile.state_dir / "configured.json"
    destination = profile.state_dir / "remote-ca.pem"
    publish = connection.private_write

    def fail_profile(path, content, **kwargs):
        if path == target:
            raise OSError("synthetic profile publication failure")
        return publish(path, content, **kwargs)

    with monkeypatch.context() as patcher:
        patcher.setattr(connection, "private_write", fail_profile)
        with pytest.raises(OSError):
            configure_remote_client(target, profile, ca_source=source)
    assert not target.exists() and not destination.exists()
    corrected = profile.state_dir / "corrected-ca.pem"
    private_write(corrected, source.read_bytes() + b"\n")
    configure_remote_client(target, profile, ca_source=corrected)
    configured = load_remote_settings(target)
    ready = ensure_remote_ready(configured, timeout=2)
    assert ready["db_ready"] is True
    assert (ready["deployment_id"], ready["realm"]) == (profile.deployment_id, profile.realm)
    assert configured.ca_bundle == destination
    assert destination.stat().st_mode & 0o077 == 0


def test_configuration_conflict_never_publishes_an_orphan_ca(tls_endpoint):
    profile = tls_endpoint.profile
    target = profile.state_dir / "existing.json"
    private_write(target, profile.model_dump_json())
    before = target.read_bytes()
    desired = profile.model_copy(update={"ca_bundle": None, "ca_bundle_sha256": None})
    with pytest.raises(DomainError) as denied:
        configure_remote_client(target, desired, ca_source=profile.ca_bundle)
    assert denied.value.code == "CONFIG_EXISTS"
    assert target.read_bytes() == before
    assert not (profile.state_dir / "remote-ca.pem").exists()


def test_configuration_preserves_preexisting_different_ca(tls_endpoint):
    profile = tls_endpoint.profile
    target = profile.state_dir / "configured.json"
    destination = profile.state_dir / "remote-ca.pem"
    foreign = profile.ca_bundle.read_bytes() + b"\n"
    private_write(destination, foreign)
    desired = profile.model_copy(update={"ca_bundle": None, "ca_bundle_sha256": None})
    with pytest.raises(DomainError) as denied:
        configure_remote_client(target, desired, ca_source=profile.ca_bundle)
    assert denied.value.code == "CA_BUNDLE_CONFLICT"
    assert destination.read_bytes() == foreign
    assert not target.exists()


@pytest.mark.parametrize("field,value", [("base_url", "https://other.example"), ("deployment_id", "other"),
                                        ("state_dir", None)])
def test_remote_endpoint_arguments_must_match_explicit_profile(tls_endpoint, field, value):
    profile = tls_endpoint.profile
    kwargs = {"base_url": profile.base_url, "state_dir": profile.state_dir, "deployment_id": profile.deployment_id}
    kwargs[field] = value
    with pytest.raises(DomainError):
        LocalClient(token_file=tls_endpoint.token, remote_settings=profile, **kwargs)
    with pytest.raises(DomainError):
        RelayEndpoint(remote_settings=profile, **kwargs)


@pytest.mark.parametrize("field,value", [("deployment_id", "wrong-deployment"), ("realm", "wrong-realm")])
def test_remote_identity_denied_before_credential_read_or_source_dispatch(tls_endpoint, monkeypatch, field, value):
    tls_endpoint.state[field] = value

    def forbidden(*args):
        raise AssertionError("Credential must not be read before anonymous identity validation")

    monkeypatch.setattr("agents_memory.client.read_remote_credential", forbidden)
    with pytest.raises(DomainError) as denied:
        client_from_settings(tls_endpoint.profile, tls_endpoint.token, timeout=0.3).request("/api/capture", capture())
    assert denied.value.code == "SERVICE_IDENTITY_MISMATCH"
    assert denied.value.effect is EffectState.NOT_STARTED
    assert len(tls_endpoint.state["gets"]) == 1 and tls_endpoint.state["posts"] == []
    assert "Authorization" not in tls_endpoint.state["gets"][0][1]


def test_tls_hostname_denial_precedes_credentials_and_dispatch(tls_endpoint, monkeypatch):
    profile = tls_endpoint.profile.model_copy(update={"base_url": tls_endpoint.profile.base_url.replace("localhost", "127.0.0.1")})
    monkeypatch.setattr("agents_memory.client.read_remote_credential", lambda *args: pytest.fail("credential read"))
    with pytest.raises(DomainError) as denied:
        client_from_settings(profile, tls_endpoint.token, timeout=0.2).request("/api/capture", capture())
    assert denied.value.code == "TLS_VERIFICATION_FAILED" and denied.value.effect is EffectState.NOT_STARTED
    assert tls_endpoint.state["gets"] == [] and tls_endpoint.state["posts"] == []


def test_ca_change_denied_before_credentials_and_dispatch(tls_endpoint, monkeypatch):
    tls_endpoint.profile.ca_bundle.write_bytes(b"replaced certificate")
    monkeypatch.setattr("agents_memory.client.read_remote_credential", lambda *args: pytest.fail("credential read"))
    with pytest.raises(DomainError) as denied:
        client_from_settings(tls_endpoint.profile, tls_endpoint.token).request("/api/capture", capture())
    assert denied.value.code == "CA_BUNDLE_INVALID" and denied.value.effect is EffectState.NOT_STARTED
    assert tls_endpoint.state["gets"] == [] and tls_endpoint.state["posts"] == []


def test_verified_json_and_mcp_ignore_environment_proxies(tls_endpoint, monkeypatch):
    for name in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, "")
    result = client_from_settings(tls_endpoint.profile, tls_endpoint.token).request("/api/capture", capture())
    assert result["effect"] == "committed"
    relay = StdioRelay(endpoint(tls_endpoint.profile), tls_endpoint.token)
    assert relay.forward(initialize())["result"]["protocolVersion"] == "2025-11-25"
    assert [item[0] for item in tls_endpoint.state["posts"]] == ["/api/capture", "/mcp"]
    assert all(item[2]["Origin"] == tls_endpoint.profile.base_url for item in tls_endpoint.state["posts"])
    assert all("Authorization" not in item[1] for item in tls_endpoint.state["gets"])


def test_remote_readiness_redirect_never_reads_credentials(tls_endpoint, monkeypatch):
    tls_endpoint.state["redirect_ready"] = True
    monkeypatch.setattr("agents_memory.client.read_remote_credential", lambda *args: pytest.fail("credential read"))
    with pytest.raises(DomainError) as denied:
        client_from_settings(tls_endpoint.profile, tls_endpoint.token).request("/api/capture", capture())
    assert denied.value.code == "DESTINATION_DENIED" and denied.value.effect is EffectState.NOT_STARTED
    assert len(tls_endpoint.state["gets"]) == 1 and tls_endpoint.state["posts"] == []


@pytest.mark.parametrize("failure", ["redirect_post", "disconnect"])
def test_dispatched_mutation_failure_is_unknown_and_not_retried(tls_endpoint, failure):
    tls_endpoint.state[failure] = True
    with pytest.raises(DomainError) as denied:
        client_from_settings(tls_endpoint.profile, tls_endpoint.token).request("/api/capture", capture())
    assert denied.value.effect is EffectState.UNKNOWN
    assert len(tls_endpoint.state["posts"]) == 1




def test_remote_control_and_readiness_share_absolute_deadline(tls_endpoint, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("agents_memory.readiness.time", SimpleNamespace(monotonic=lambda: clock[0], sleep=lambda _: None))
    monkeypatch.setattr("agents_memory.service.require_client_enabled", lambda _, **_options: clock.__setitem__(0, 101.0))
    with pytest.raises(DomainError) as denied:
        ensure_remote_ready(tls_endpoint.profile, timeout=0.1)
    assert denied.value.code == "SERVICE_UNAVAILABLE" and tls_endpoint.state["gets"] == []


@pytest.mark.parametrize("mode,contents,accepted", [
    ("bearer", b"a" * 512 + b"\n", True), ("bearer", b"a" * 513, False),
    ("oauth", b"a" * 4096 + b".signature\r\n", True), ("oauth", b"a" * 16385, False),
    ("oauth", b"nonascii-\xff", False), ("oauth", b"white space", False),
    ("oauth", b"leading\ttab", False), ("oauth", b"\ttoken\n", False),
    ("oauth", b"not:a:jwt", False),
])
def test_remote_credential_envelope_is_explicit_and_bounded(tls_endpoint, mode, contents, accepted):
    profile = tls_endpoint.profile.model_copy(update={"auth_mode": mode})
    tls_endpoint.token.write_bytes(contents)
    if accepted:
        assert read_remote_credential(tls_endpoint.token, profile) == contents.decode("ascii").strip()
    else:
        with pytest.raises(DomainError) as denied:
            read_remote_credential(tls_endpoint.token, profile)
        assert denied.value.code == "CREDENTIAL_INVALID" and denied.value.effect is EffectState.NOT_STARTED


def test_remote_relay_resends_only_proven_not_started_missing_session(tls_endpoint):
    relay = StdioRelay(endpoint(tls_endpoint.profile), tls_endpoint.token)
    assert "result" in relay.forward(initialize())
    tls_endpoint.state["lost"] = True
    message = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    assert relay.forward(message)["result"] == {"tools": []}
    assert [item[1]["method"] for item in tls_endpoint.state["posts"]] == [
        "initialize", "tools/list", "initialize", "notifications/initialized", "tools/list",
    ]
    tls_endpoint.state["disconnect"] = True
    result = relay.forward({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "memory_capture"}})
    assert result["error"]["data"]["effect"] == "unknown"
    assert len(tls_endpoint.state["posts"]) == 6


def test_remote_relay_refuses_changed_protocol_during_session_recovery(tls_endpoint):
    relay = StdioRelay(endpoint(tls_endpoint.profile), tls_endpoint.token)
    assert "result" in relay.forward(initialize())
    tls_endpoint.state.update(lost=True, version="2026-01-01")
    result = relay.forward({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert result["error"]["message"] == "SESSION_NOT_FOUND"
    assert [item[1]["method"] for item in tls_endpoint.state["posts"]] == ["initialize", "tools/list", "initialize"]
    assert relay.session_id is None and relay.protocol_version == "2025-11-25"


def test_anonymous_readiness_never_substitutes_for_authentication(tls_endpoint):
    tls_endpoint.state["reject_credential"] = True
    with pytest.raises(DomainError) as denied:
        client_from_settings(tls_endpoint.profile, tls_endpoint.token).request("/api/capture", capture())
    assert denied.value.code == "TOKEN_REVOKED" and denied.value.effect is EffectState.NOT_STARTED
    assert len(tls_endpoint.state["gets"]) == 1 and len(tls_endpoint.state["posts"]) == 1


def test_profile_requires_private_canonical_pc_state(tls_endpoint, tmp_path):
    value = tls_endpoint.profile.model_dump(mode="json")
    with pytest.raises((DomainError, ValidationError)):
        RemoteClientSettings.model_validate({**value, "state_dir": "relative/state"})
    public_state = tmp_path / "public-state"
    public_state.mkdir(mode=0o755)
    with pytest.raises((DomainError, ValidationError)):
        RemoteClientSettings.model_validate({**value, "state_dir": public_state})
    linked_state = tmp_path / "linked-state"
    linked_state.symlink_to(tls_endpoint.profile.state_dir, target_is_directory=True)
    with pytest.raises((DomainError, ValidationError)):
        RemoteClientSettings.model_validate({**value, "state_dir": linked_state})


def test_system_trust_does_not_accept_disposable_untrusted_certificate(tls_endpoint, monkeypatch):
    profile = tls_endpoint.profile.model_copy(update={"ca_bundle": None, "ca_bundle_sha256": None})
    monkeypatch.setattr("agents_memory.client.read_remote_credential", lambda *args: pytest.fail("credential read"))
    with pytest.raises(DomainError) as denied:
        client_from_settings(profile, tls_endpoint.token, timeout=0.2).request("/api/capture", capture())
    assert denied.value.code in {"TLS_VERIFICATION_FAILED", "CA_BUNDLE_INVALID"}
    assert denied.value.effect is EffectState.NOT_STARTED and tls_endpoint.state["posts"] == []


def test_oauth_transport_accepts_bounded_ascii_without_client_side_grant_inference(tls_endpoint):
    profile = tls_endpoint.profile.model_copy(update={"auth_mode": "oauth"})
    token = "opaque-resource-token-" + "a" * 4096
    tls_endpoint.token.write_text(token + "\n")
    assert client_from_settings(profile, tls_endpoint.token).request("/api/context", {"query": "synthetic"})["effect"] == "committed"
    assert tls_endpoint.state["posts"][0][2]["Authorization"] == "Bearer " + token


def test_remote_relay_checks_realm_before_credential_or_mcp_dispatch(tls_endpoint, monkeypatch):
    relay = StdioRelay(endpoint(tls_endpoint.profile), tls_endpoint.token)
    tls_endpoint.state["realm"] = "other-realm"
    monkeypatch.setattr("agents_memory.stdio.read_remote_credential", lambda *args: pytest.fail("credential read"))
    result = relay.forward(initialize())
    assert result["error"]["message"] == "SERVICE_IDENTITY_MISMATCH"
    assert result["error"]["data"]["effect"] == "not_started" and tls_endpoint.state["posts"] == []


def test_remote_wire_bound_rejects_before_readiness_or_credentials(tls_endpoint, monkeypatch):
    monkeypatch.setattr("agents_memory.client.read_remote_credential", lambda *args: pytest.fail("credential read"))
    with pytest.raises(DomainError) as denied:
        client_from_settings(tls_endpoint.profile, tls_endpoint.token).request(
            "/api/context", {"query": "x" * tls_endpoint.profile.max_http_body_bytes},
        )
    assert denied.value.code == "INPUT_TOO_LARGE" and denied.value.effect is EffectState.NOT_STARTED
    assert tls_endpoint.state["gets"] == [] and tls_endpoint.state["posts"] == []


def test_remote_relay_requires_profile_wire_bounds(tls_endpoint):
    profile = tls_endpoint.profile
    with pytest.raises(DomainError):
        RelayEndpoint(
            profile.base_url, state_dir=profile.state_dir, deployment_id=profile.deployment_id,
            max_mcp_response_bytes=4096, remote_settings=profile,
        )


def test_pc_project_and_private_client_state_are_disjoint(tls_endpoint, tmp_path):
    profile = tls_endpoint.profile
    validate_remote_project(profile, tmp_path / "separate-pc-project")
    for project in (profile.state_dir, profile.state_dir / "nested-project", tmp_path):
        with pytest.raises(DomainError) as denied:
            validate_remote_project(profile, project)
        assert denied.value.code == "PATH_DENIED" and denied.value.effect is EffectState.NOT_STARTED


@pytest.mark.asyncio
async def test_remote_stdio_exits_cleanly_when_input_pipe_is_closed(tls_endpoint, monkeypatch):
    from agents_memory import stdio

    closed = io.BytesIO()
    closed.close()
    monkeypatch.setattr(stdio.sys, "stdin", SimpleNamespace(buffer=closed))
    await stdio.run_stdio(endpoint(tls_endpoint.profile), tls_endpoint.token)
    assert tls_endpoint.state["gets"] == [] and tls_endpoint.state["posts"] == []


def test_stdio_closed_output_pipe_does_not_raise(monkeypatch):
    from agents_memory import stdio

    closed = io.BytesIO()
    closed.close()
    monkeypatch.setattr(stdio.sys, "stdout", SimpleNamespace(buffer=closed))
    assert stdio._write_result({"jsonrpc": "2.0", "id": 1, "result": {}}) is False


@pytest.mark.parametrize("rejected", [False, True])
def test_remote_response_deadline_does_not_retry_a_dispatched_write(tls_endpoint, rejected):
    fixture = tls_endpoint
    fixture.state.update(drip_post=True, reject_credential=rejected)
    started = time.monotonic()
    with pytest.raises(DomainError) as failed:
        client_from_settings(fixture.profile, fixture.token, timeout=0.5).request("/api/capture", capture())
    assert failed.value.effect == EffectState.UNKNOWN
    assert time.monotonic() - started < 0.9
    assert len(fixture.state["posts"]) == 1
