from __future__ import annotations

import http.client
import io
import json
import os
import subprocess
import sys
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from types import SimpleNamespace

import pytest

from agents_memory.client import LocalClient
from agents_memory.domain import DomainError, EffectState


def source_payload(**changes):
    return {
        "binding_id": "binding-001", "idempotency_key": "capture-001", "origin_key": "origin-001",
        "speaker": "human", "body": "Keep customer records local.", **changes,
    }


@pytest.fixture
def local_client(tmp_path):
    token = tmp_path / "producer.token"
    token.write_text("test-only-producer-credential\n")
    token.chmod(0o600)
    return LocalClient("http://127.0.0.1:8768", token)


def reply(monkeypatch, raw):
    monkeypatch.setattr("agents_memory.client.urllib.request.build_opener", lambda *handlers: SimpleNamespace(open=lambda *args, **kwargs: io.BytesIO(raw)))


@pytest.mark.parametrize("failure", [
    http.client.IncompleteRead(b"private partial response", 12),
    http.client.BadStatusLine("private upstream diagnostic"),
    http.client.RemoteDisconnected("private socket diagnostic"),
    urllib.error.URLError("private network diagnostic"),
    TimeoutError("private timeout diagnostic"),
    OSError("private operating-system diagnostic"),
])
@pytest.mark.parametrize("boundary", ["open", "read"])
def test_transport_failure_is_sanitized_unknown_write_effect(local_client, monkeypatch, failure, boundary):
    class BrokenResponse(io.BytesIO):
        def read(self, size=-1):
            raise failure

    def open_request(*args, **kwargs):
        if boundary == "open":
            raise failure
        return BrokenResponse()

    monkeypatch.setattr("agents_memory.client.urllib.request.build_opener", lambda *handlers: SimpleNamespace(open=open_request))
    with pytest.raises(DomainError) as caught:
        local_client.request("/api/capture", source_payload())
    assert caught.value.code == "SERVICE_UNAVAILABLE"
    assert caught.value.effect is EffectState.UNKNOWN
    assert "private" not in json.dumps(caught.value.public())


@pytest.mark.parametrize("body", [b"null", b"[]", b'"private diagnostic"', b'{"effect":', b'{"id":"one","id":"two"}'])
def test_malformed_success_response_cannot_claim_not_started(local_client, monkeypatch, body):
    reply(monkeypatch, body)
    with pytest.raises(DomainError) as caught:
        local_client.request("/api/capture", source_payload())
    assert caught.value.code == "RESPONSE_INVALID"
    assert caught.value.effect is EffectState.UNKNOWN
    assert "private diagnostic" not in json.dumps(caught.value.public())


@pytest.mark.parametrize("body,code,effect", [
    ({"error": {"code": "ORIGIN_CONFLICT", "effect": "not_started", "message": "private body"}}, "ORIGIN_CONFLICT", EffectState.NOT_STARTED),
    ({"error": {"code": "RESULT_TOO_LARGE", "effect": "committed", "message": "private body"}}, "RESULT_TOO_LARGE", EffectState.COMMITTED),
    ({"error": ["private body"]}, "SERVICE_REJECTED", EffectState.UNKNOWN),
    ({"error": {"code": {"body": "private body"}, "effect": None}}, "SERVICE_REJECTED", EffectState.UNKNOWN),
    ({"error": {"code": "private path /credentials", "effect": "committed"}}, "SERVICE_REJECTED", EffectState.COMMITTED),
    (["private body"], "SERVICE_REJECTED", EffectState.UNKNOWN),
])
def test_http_rejection_preserves_only_valid_sanitized_effect(local_client, monkeypatch, body, code, effect):
    def reject(*args, **kwargs):
        raise urllib.error.HTTPError("http://127.0.0.1:8768/api/capture", 409, "private status", {}, io.BytesIO(json.dumps(body).encode()))

    monkeypatch.setattr("agents_memory.client.urllib.request.build_opener", lambda *handlers: SimpleNamespace(open=reject))
    with pytest.raises(DomainError) as caught:
        local_client.request("/api/capture", source_payload())
    assert caught.value.code == code and caught.value.effect is effect
    assert caught.value.status == 409
    assert "private" not in json.dumps(caught.value.public())


def test_incomplete_http_error_body_is_still_public_unknown(local_client, monkeypatch):
    class BrokenBody(io.BytesIO):
        def read(self, size=-1):
            raise http.client.IncompleteRead(b"private partial error", 20)

    def reject(*args, **kwargs):
        raise urllib.error.HTTPError("http://127.0.0.1:8768/api/capture", 503, "private error", {}, BrokenBody())

    monkeypatch.setattr("agents_memory.client.urllib.request.build_opener", lambda *handlers: SimpleNamespace(open=reject))
    with pytest.raises(DomainError) as caught:
        local_client.request("/api/capture", source_payload())
    assert caught.value.code == "SERVICE_REJECTED"
    assert caught.value.effect is EffectState.UNKNOWN
    assert "private" not in json.dumps(caught.value.public())


def test_missing_local_credential_is_sanitized_before_request_attempt(local_client, monkeypatch):
    local_client.token_file.unlink()
    attempted = []
    monkeypatch.setattr("agents_memory.client.urllib.request.build_opener", lambda *handlers: attempted.append(True))
    with pytest.raises(DomainError) as caught:
        local_client.request("/api/capture", source_payload())
    assert caught.value.code == "CREDENTIAL_INVALID"
    assert caught.value.effect is EffectState.NOT_STARTED
    assert attempted == []


@pytest.mark.parametrize("contents", [
    b"",
    b"\xffprivate-credential",
    b"private credential\n",
    b"private\tcredential\n",
    b"private\ncredential\n",
    "private\u2003credential\n".encode("utf-8"),
    b"x" * 513 + b"\n",
    b"x" * 2051,
    b" " * 2051,
])
def test_invalid_credential_content_is_sanitized_before_opener(local_client, monkeypatch, contents):
    local_client.token_file.write_bytes(contents)
    attempted = []
    monkeypatch.setattr("agents_memory.client.urllib.request.build_opener", lambda *handlers: attempted.append(True))
    with pytest.raises(DomainError) as caught:
        local_client.request("/api/capture", source_payload(idempotency_key="private-write-key"))
    assert caught.value.code == "CREDENTIAL_INVALID"
    assert caught.value.status == 401
    assert caught.value.effect is EffectState.NOT_STARTED
    assert attempted == []
    public = json.dumps(caught.value.public())
    assert "private" not in public
    assert str(local_client.token_file) not in public


@pytest.mark.parametrize("contents", [b"x", b" "])
def test_oversized_credential_is_rejected_without_reading_file(local_client, monkeypatch, contents):
    local_client.token_file.write_bytes(contents * 1048576)

    def forbidden_read(*args, **kwargs):
        raise AssertionError("An oversized credential must be rejected before reading its contents")

    monkeypatch.setattr("agents_memory.private_io.os.fdopen", forbidden_read)
    attempted = []
    monkeypatch.setattr("agents_memory.client.urllib.request.build_opener", lambda *handlers: attempted.append(True))
    with pytest.raises(DomainError) as caught:
        local_client.request("/api/capture", source_payload(idempotency_key="private-write-key"))
    assert caught.value.code == "CREDENTIAL_INVALID"
    assert caught.value.status == 401
    assert caught.value.effect is EffectState.NOT_STARTED
    assert attempted == []
    assert "private" not in json.dumps(caught.value.public())
    assert str(local_client.token_file) not in json.dumps(caught.value.public())


@pytest.mark.parametrize("kind", ["symlink", "directory", "nonprivate", "unowned"])
def test_insecure_credential_file_is_rejected_before_opener(local_client, monkeypatch, kind):
    token = local_client.token_file
    if kind == "symlink":
        target = token.with_suffix(".target")
        token.rename(target)
        token.symlink_to(target)
    elif kind == "directory":
        token.unlink()
        token.mkdir(mode=0o700)
    elif kind == "nonprivate":
        token.chmod(0o644)
    else:
        owner = token.stat().st_uid
        monkeypatch.setattr("agents_memory.private_io.os.getuid", lambda: owner + 1)
    attempted = []
    monkeypatch.setattr("agents_memory.client.urllib.request.build_opener", lambda *handlers: attempted.append(True))
    with pytest.raises(DomainError) as caught:
        local_client.request("/api/capture", source_payload(idempotency_key="private-write-key"))
    assert caught.value.code == "CREDENTIAL_INVALID"
    assert caught.value.status == 401
    assert caught.value.effect is EffectState.NOT_STARTED
    assert attempted == []
    public = json.dumps(caught.value.public())
    assert "private" not in public
    assert str(token) not in public


def test_fifo_credential_without_writer_is_rejected_with_finite_deadline(tmp_path):
    token = tmp_path / "private-credential-fifo"
    os.mkfifo(token, 0o600)
    script = """
import json
import sys
import urllib.request
from pathlib import Path
from agents_memory.client import LocalClient
from agents_memory.domain import DomainError

def forbidden_opener(*handlers):
    raise AssertionError("A credential failure must not construct an opener")

urllib.request.build_opener = forbidden_opener
try:
    LocalClient("http://127.0.0.1:8768", Path(sys.argv[1])).request(
        "/api/capture", {"binding_id": "binding-001", "origin_key": "origin-001", "speaker": "human", "body": "Keep records local.", "idempotency_key": "private-write-key"}
    )
except DomainError as error:
    print(json.dumps({"status": error.status, **error.public()}))
else:
    raise AssertionError("The FIFO credential was accepted")
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(token)],
        capture_output=True, text=True, timeout=5,
    )
    assert result.returncode == 0, result.stderr
    public = json.loads(result.stdout)
    assert public["status"] == 401
    assert public["code"] == "CREDENTIAL_INVALID"
    assert public["effect"] == "not_started"
    assert "private" not in result.stdout
    assert str(token) not in result.stdout


@pytest.mark.parametrize("credential,newline", [
    ("test-only-producer-credential", "\n"),
    ("test-only-producer-credential", "\r\n"),
    ("x" * 512, "\n"),
])
def test_private_credential_newline_reaches_loopback_transport(local_client, credential, newline):
    local_client.token_file.write_text(credential + newline)
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(self.headers.get("Authorization"))
            self.rfile.read(int(self.headers["Content-Length"]))
            raw = b'{"receipt":"capture-001"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format, *args):
            pass

    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        server.timeout = 2
        worker = Thread(target=server.handle_request, daemon=True)
        worker.start()
        try:
            client = LocalClient(
                f"http://127.0.0.1:{server.server_port}", local_client.token_file, timeout=2,
            )
            client.request("/api/capture", source_payload())
        finally:
            worker.join(timeout=5)
        assert not worker.is_alive()
    assert received == ["Bearer " + credential]


@pytest.mark.parametrize("route,payload", [
    ("/api/capture", source_payload(body="ghp_" + "a" * 36)),
    ("/api/record", {"idempotency_key": "record-001", "kind": "note", "body": "ghp_" + "a" * 36}),
    ("/api/feedback", {"idempotency_key": "feedback-001", "target_ref": "claim-001", "kind": "correct", "body": "ghp_" + "a" * 36}),
    ("/api/correct", {"target_ref": "source-001", "source": source_payload(body="ghp_" + "a" * 36)}),
])
def test_source_secret_refusal_precedes_credentials_and_transport(local_client, monkeypatch, route, payload):
    local_client.token_file.unlink()
    attempts = []
    monkeypatch.setattr("agents_memory.client.urllib.request.build_opener", lambda *handlers: attempts.append(True))
    with pytest.raises(DomainError) as caught:
        local_client.request(route, payload)
    assert caught.value.code == "SOURCE_SECRET_REJECTED"
    assert caught.value.effect == EffectState.NOT_STARTED
    assert caught.value.status == 422 and not attempts
    public = json.dumps(caught.value.public())
    assert "ghp_" not in public and "capture-001" not in public and "origin-001" not in public


def test_claim_json_windows_preserve_utf8_escaping_and_snapshot_at_minimum_wire_budget():
    import hashlib

    from agents_memory.representation import stored_record_window
    from agents_memory.wire import tool_result_bytes

    payload = {
        "id": "claim-001", "kind": "claim", "epoch": 9, "state": "active", "revision": 2,
        "snapshot": "가" * 512,
        "draft": {"conditions": ["Do not export. " + '가😀"\\\n' * 500]},
        "evidence": [{"source_id": "source-001", "source_revision": 3, "quote": '가😀"\\\n' * 500}],
    }
    cursor, fragments, digest = 0, [], None
    while cursor is not None:
        result = stored_record_window(payload, cursor, 4096, 1024)
        assert tool_result_bytes(result) <= 4096
        chunk = result["draft_window"]
        assert chunk["byte_start"] == cursor < chunk["byte_end"]
        fragment = chunk["body"].encode("utf-8")
        assert 0 < len(fragment) <= 4096
        assert chunk["byte_end"] - cursor == len(fragment)
        digest = digest or chunk["digest"]
        assert chunk["digest"] == digest
        fragments.append(fragment)
        cursor = chunk["next_byte"]
    raw = b"".join(fragments)
    assert len(fragments) > 1 and hashlib.sha256(raw).hexdigest() == digest
    assert json.loads(raw) == {key: value for key, value in payload.items() if key != "epoch"}


@pytest.mark.parametrize("kind", ("judgment", "selection"))
def test_stored_judgment_windows_preserve_complete_reasons_without_claim_revision(kind):
    import hashlib

    from agents_memory.representation import stored_record_window
    from agents_memory.wire import tool_result_bytes

    payload = {
        "id": f"{kind}-001", "kind": kind, "epoch": 11, "state": "active",
        "reason": '원본 이유😀"\\\n' * 200,
        "snapshot": "scope-001",
        "relations" if kind == "judgment" else "rejection_comparisons": [
            {"reason": f"Comparison {index}: " + '가😀"\\\n' * 200, "ref": f"ref-{index}"}
            for index in range(16)
        ],
    }
    cursor, fragments, digest, total = 0, [], None, None
    while cursor is not None:
        inspected = stored_record_window(payload, cursor, 4096, 1024)
        assert tool_result_bytes(inspected) <= 4096
        chunk = inspected["draft_window"]
        fragment = chunk["body"].encode("utf-8")
        assert chunk["byte_start"] == cursor
        assert chunk["byte_end"] - cursor == len(fragment)
        assert 0 < len(fragment) <= 4096
        digest, total = digest or chunk["digest"], total or chunk["total_bytes"]
        assert chunk["digest"] == digest and chunk["total_bytes"] == total
        fragments.append(fragment)
        cursor = chunk["next_byte"]
    raw = b"".join(fragments)
    assert len(fragments) > 1 and len(raw) == total
    assert hashlib.sha256(raw).hexdigest() == digest
    assert json.loads(raw) == {key: value for key, value in payload.items() if key != "epoch"}


@pytest.mark.parametrize("start,max_bytes", ((-1, 4096), (1, 4097), (1, True)))
def test_stored_json_windows_refuse_invalid_bounds(start, max_bytes):
    from agents_memory.representation import stored_record_window

    with pytest.raises(DomainError) as refused:
        stored_record_window({"id": "selection-001", "kind": "selection"}, start, max_bytes, 4096)
    assert refused.value.code == "CLAIM_WINDOW_INVALID"


def test_stored_json_windows_refuse_unaligned_utf8_and_past_end_cursors():
    from agents_memory.representation import stored_record_window

    payload = {"id": "judgment-001", "kind": "judgment", "reason": "가😀"}
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    for cursor in (raw.index("가".encode()) + 1, len(raw)):
        with pytest.raises(DomainError) as refused:
            stored_record_window(payload, cursor, 4096, 4096)
        assert refused.value.code == "CLAIM_WINDOW_INVALID"
