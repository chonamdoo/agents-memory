from __future__ import annotations

import io
import json
import threading
from http.client import BadStatusLine, IncompleteRead
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

import pytest

from agents_memory import stdio
from agents_memory.stdio import RelayEndpoint, StdioRelay


class Response:
    def __init__(self, body, *, headers=None, failure=None):
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.headers = headers or {}
        self.failure = failure

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, maximum):
        if self.failure is not None:
            raise self.failure
        return self.body[:maximum]


class Opener:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def open(self, request, *, timeout):
        self.requests.append(request)
        value = next(self.responses)
        if isinstance(value, Exception):
            raise value
        return value


@pytest.fixture
def relay(tmp_path):
    token = tmp_path / "synthetic-token"
    token.write_text("synthetic-local-relay-token-" + "a" * 40)
    token.chmod(0o600)
    return StdioRelay(RelayEndpoint("http://127.0.0.1:12345", max_mcp_response_bytes=4096), token)


def initialize(version="2025-11-25"):
    return {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": version}}


@pytest.mark.parametrize("name", [None, 7, True, [], {}, ["memory_context"]])
def test_nonstring_tool_name_is_rejected_without_http_dispatch(relay, name):
    relay.opener = Opener([])
    response = relay.forward({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": name}})
    assert response == {"jsonrpc": "2.0", "id": 2, "error": {
        "code": -32000, "message": "RPC_ENVELOPE_INVALID", "data": {"effect": "not_started"},
    }}
    assert relay.opener.requests == []


@pytest.mark.parametrize("version", [None, 7, True, [], {}])
def test_initialize_requires_string_protocol_version(relay, version):
    relay.opener = Opener([])
    result = relay.forward(initialize(version))
    assert result["error"]["message"] == "RPC_ENVELOPE_INVALID"
    assert result["error"]["data"]["effect"] == "not_started"
    assert relay.opener.requests == []
    assert relay.protocol_version is None


@pytest.mark.parametrize("version", [None, 7, True, [], {}])
def test_modern_request_requires_string_protocol_metadata_when_present(relay, version):
    relay.opener = Opener([])
    request = {"jsonrpc": "2.0", "id": 2, "method": "tools/list",
        "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": version}}}
    result = relay.forward(request)
    assert result["error"]["message"] == "RPC_ENVELOPE_INVALID"
    assert result["error"]["data"]["effect"] == "not_started"
    assert relay.opener.requests == []


@pytest.mark.parametrize("payload", [
    {"jsonrpc": "2.0", "id": 1, "result": None},
    {"jsonrpc": "2.0", "id": 1, "result": []},
    {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 7}},
    {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": None}},
    {"jsonrpc": "2.0", "id": 1, "result": {}},
    {"jsonrpc": "2.0", "id": 2, "result": {"protocolVersion": "2025-11-25"}},
    {"jsonrpc": "2.0", "id": True, "result": {"protocolVersion": "2025-11-25"}},
    {"jsonrpc": "2.0", "id": 1, "error": "not-an-error-envelope"},
    {"jsonrpc": "2.0", "id": 1, "error": {"code": True, "message": "bad"}},
    {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": []}},
    {"jsonrpc": "2.0", "id": 1, "result": {}, "error": {"code": -32000, "message": "bad"}},
    b'{"jsonrpc":"2.0","id":1,"result":',
    b'[]',
    b'',
])
def test_malformed_server_response_is_bounded_and_cannot_poison_session(relay, payload):
    relay.opener = Opener([Response(payload, headers={"Mcp-Session-Id": "must-not-install"})])
    result = relay.forward(initialize())
    assert result["error"]["message"] == "RPC_RESPONSE_INVALID"
    assert result["error"]["data"]["effect"] == "unknown"
    assert len(json.dumps(result).encode()) <= relay.settings.max_mcp_response_bytes
    assert relay.protocol_version is None
    assert relay.session_id is None


@pytest.mark.parametrize("failure", [IncompleteRead(b'{"result":', 100), BadStatusLine("truncated status")])
def test_http_exception_returns_unknown_write_outcome_not_process_failure(relay, failure):
    relay.opener = Opener([Response(b"", failure=failure), Response({"jsonrpc": "2.0", "id": 3, "result": {"tools": []}})])
    result = relay.forward({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "memory_capture"}})
    assert result["error"]["message"] == "SERVICE_UNAVAILABLE_RECONCILE_DURABLE_WRITES"
    assert result["error"]["data"]["effect"] == "unknown"
    assert relay.forward({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})["result"] == {"tools": []}


@pytest.mark.parametrize("modern", [False, True])
def test_legacy_session_and_modern_per_request_version_are_preserved(relay, modern):
    version = "2025-11-25"
    init_result = {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": version, "capabilities": {"tools": {}}}}
    list_result = {"jsonrpc": "2.0", "id": 2, "result": {"tools": []}}
    relay.opener = Opener([Response(init_result, headers={"Mcp-Session-Id": "legacy-session"}), Response(list_result)])
    assert relay.forward(initialize(version)) == init_result
    request = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    if modern:
        request["params"] = {"_meta": {"io.modelcontextprotocol/protocolVersion": version}}
    assert relay.forward(request) == list_result
    headers = {key.lower(): value for key, value in relay.opener.requests[-1].header_items()}
    assert headers["mcp-protocol-version"] == version
    assert ("mcp-session-id" in headers) is not modern
    if not modern:
        assert headers["mcp-session-id"] == "legacy-session"


def test_oversized_response_and_request_id_produce_bounded_error(relay):
    relay.opener = Opener([Response(b"x" * 4097)])
    request = {"jsonrpc": "2.0", "id": "x" * 8192, "method": "tools/list"}
    result = relay.forward(request)
    assert result["id"] is None
    assert result["error"]["message"] == "RESULT_TOO_LARGE"
    assert result["error"]["data"]["effect"] == "unknown"
    assert len(json.dumps(result).encode()) <= relay.settings.max_mcp_response_bytes


def test_real_truncated_http_body_returns_jsonrpc_error(relay):
    class TruncatedHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "200")
            self.end_headers()
            self.wfile.write(b'{"jsonrpc":"2.0","id":1,"result":')
            self.wfile.flush()
            self.close_connection = True

        def log_message(self, *args):
            return None

    server = HTTPServer(("127.0.0.1", 0), TruncatedHandler)
    thread = threading.Thread(target=server.handle_request)
    thread.start()
    try:
        relay.settings = RelayEndpoint(f"http://127.0.0.1:{server.server_port}", max_mcp_response_bytes=4096)
        result = relay.forward(initialize())
        assert result["error"]["message"] in {"RPC_RESPONSE_INVALID", "SERVICE_UNAVAILABLE_RECONCILE_DURABLE_WRITES"}
        assert result["error"]["data"]["effect"] == "unknown"
        assert len(json.dumps(result).encode()) <= 4096
    finally:
        server.server_close()
        thread.join(timeout=5)
    assert not thread.is_alive()


@pytest.mark.asyncio
async def test_stdio_loop_continues_after_invalid_response_and_truncated_http(relay, monkeypatch):
    requests = [initialize(), {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/list"}]
    incoming = io.BytesIO(b"".join(json.dumps(request).encode() + b"\n" for request in requests))
    outgoing = io.BytesIO()
    relay.opener = Opener([Response({"jsonrpc": "2.0", "id": 1, "result": []}),
        IncompleteRead(b"partial", 100), Response({"jsonrpc": "2.0", "id": 3, "result": {"tools": []}})])
    monkeypatch.setattr(stdio, "StdioRelay", lambda settings, token_file: relay)
    monkeypatch.setattr(stdio.sys, "stdin", SimpleNamespace(buffer=incoming))
    monkeypatch.setattr(stdio.sys, "stdout", SimpleNamespace(buffer=outgoing))
    await stdio.run_stdio(relay.settings, relay.token_file)
    responses = [json.loads(line) for line in outgoing.getvalue().splitlines()]
    assert [response["id"] for response in responses] == [1, 2, 3]
    assert responses[0]["error"]["message"] == "RPC_RESPONSE_INVALID"
    assert responses[1]["error"]["message"] == "SERVICE_UNAVAILABLE_RECONCILE_DURABLE_WRITES"
    assert all(response["error"]["data"]["effect"] == "unknown" for response in responses[:2])
    assert responses[2]["result"] == {"tools": []}


async def test_deep_input_returns_parse_error_and_utf8_next_result_under_ascii_stdout(relay, monkeypatch):
    nested = b'{"a":' + b"[" * 32000 + b"0" + b"]" * 32000 + b"}\n"
    request = {"jsonrpc": "2.0", "id": 4, "method": "tools/list"}
    incoming = io.BytesIO(nested + json.dumps(request).encode() + b"\n")
    outgoing = io.BytesIO()
    wrapper = io.TextIOWrapper(outgoing, encoding="ascii")
    relay.opener = Opener([Response({"jsonrpc": "2.0", "id": 4, "result": {"name": "회사 규칙"}})])
    monkeypatch.setattr(stdio, "StdioRelay", lambda settings, token_file: relay)
    monkeypatch.setattr(stdio.sys, "stdin", SimpleNamespace(buffer=incoming))
    monkeypatch.setattr(stdio.sys, "stdout", wrapper)
    await stdio.run_stdio(relay.settings, relay.token_file)
    responses = [json.loads(line) for line in outgoing.getvalue().splitlines()]
    assert responses[0]["error"] == {
        "code": -32700, "message": "BOUNDED_INPUT_INVALID", "data": {"effect": "not_started"},
    }
    assert responses[1]["id"] == 4 and responses[1]["result"]["name"] == "회사 규칙"
    wrapper.detach()


def test_missing_relay_credential_is_public_error_before_http_dispatch(relay):
    relay.token_file.unlink()
    relay.opener = Opener([])
    result = relay.forward({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert result["error"]["message"] == "RELAY_CREDENTIAL_UNAVAILABLE"
    assert result["error"]["data"]["effect"] == "not_started"
    assert relay.opener.requests == []


@pytest.fixture
def loopback(relay, tmp_path):
    state = SimpleNamespace(
        status=502, payload=None, commit=True, disconnect=False, length_delta=0, requests=[],
        receipt=tmp_path / "synthetic-operation-receipt.json",
        session="unverified-error-session",
    )

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state.requests.append({
                "request": request,
                "authorization": self.headers.get("Authorization"),
                "session": self.headers.get("Mcp-Session-Id"),
                "version": self.headers.get("MCP-Protocol-Version"),
            })
            if state.commit and request.get("params", {}).get("name") == "memory_record":
                state.receipt.write_text(json.dumps({
                    "business_key": request["params"]["arguments"]["business_key"],
                    "operation_id": "synthetic-operation-71",
                }))
            if state.disconnect:
                self.close_connection = True
                return
            payload = state.payload
            if payload is None:
                payload = {"jsonrpc": "2.0", "id": request.get("id"), "error": {
                    "code": -32000, "message": "RESULT_TOO_LARGE", "data": {"effect": "committed"},
                }}
            body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            self.send_response(state.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body) + state.length_delta))
            self.send_header("Mcp-Session-Id", state.session)
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
            self.close_connection = True

        def log_message(self, *args):
            return None

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    relay.settings = RelayEndpoint(f"http://127.0.0.1:{server.server_port}", max_mcp_response_bytes=4096)
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert not thread.is_alive()


def mutation():
    return {"jsonrpc": "2.0", "id": 71, "method": "tools/call", "params": {
        "name": "memory_record", "arguments": {"business_key": "synthetic-same-business-key"},
    }}


@pytest.mark.parametrize("status", [200, 502])
def test_committed_error_preserves_outcome_without_retry_or_private_data(relay, loopback, status):
    loopback.status = status
    loopback.payload = {"jsonrpc": "2.0", "id": 71, "private_diagnostic": "synthetic-private-detail", "error": {
        "code": -32000, "message": "RESULT_TOO_LARGE",
        "data": {"effect": "committed", "credential": "synthetic-secret", "body": "must-not-duplicate"},
    }}
    result = relay.forward(mutation())
    assert result == {"jsonrpc": "2.0", "id": 71, "error": {
        "code": -32000, "message": "RESULT_TOO_LARGE", "data": {"effect": "committed"},
    }}
    assert json.loads(loopback.receipt.read_text())["business_key"] == "synthetic-same-business-key"
    assert len(loopback.requests) == 1
    assert loopback.requests[0]["authorization"] == "Bearer " + relay.token_file.read_text()
    assert relay.session_id is None


@pytest.mark.parametrize("effect", ["not_started", "not_committed", "unknown"])
def test_http_rpc_error_preserves_verified_noncommit_or_unknown(relay, loopback, effect):
    loopback.commit = False
    loopback.payload = {"jsonrpc": "2.0", "id": 71, "error": {
        "code": -32602, "message": "INPUT_INVALID", "data": {"effect": effect},
    }}
    result = relay.forward(mutation())
    assert result["error"] == {"code": -32602, "message": "INPUT_INVALID", "data": {"effect": effect}}
    assert not loopback.receipt.exists()
    assert len(loopback.requests) == 1


def test_authenticated_edge_public_rejection_preserves_not_started_and_discards_diagnostics(relay, loopback):
    loopback.status = 403
    loopback.commit = False
    loopback.payload = {"error": {
        "code": "SCOPE_DENIED", "message": "synthetic private diagnostic",
        "effect": "not_started", "credential": "synthetic-secret",
    }}
    result = relay.forward(mutation())
    assert result["error"] == {"code": -32000, "message": "SCOPE_DENIED", "data": {"effect": "not_started"}}
    assert not loopback.receipt.exists()


@pytest.mark.parametrize("payload", [
    b"<html>synthetic-secret-upstream-diagnostic</html>",
    b'{"jsonrpc":"2.0","id":71,"error":',
    b'{"jsonrpc":"2.0","id":71,"id":72,"error":{"code":-32000,"message":"RESULT_TOO_LARGE","data":{"effect":"committed"}}}',
    {"jsonrpc": "2.0", "id": 72, "error": {"code": -32000, "message": "RESULT_TOO_LARGE", "data": {"effect": "committed"}}},
    {"jsonrpc": "2.0", "id": True, "error": {"code": -32000, "message": "RESULT_TOO_LARGE", "data": {"effect": "committed"}}},
    {"jsonrpc": "2.0", "id": 71, "error": {"code": True, "message": "RESULT_TOO_LARGE", "data": {"effect": "committed"}}},
    {"jsonrpc": "2.0", "id": 71, "result": {}, "error": {"code": -32000, "message": "RESULT_TOO_LARGE", "data": {"effect": "committed"}}},
    {"jsonrpc": "2.0", "id": 71, "error": {"code": -32000, "message": "synthetic-secret-diagnostic", "data": {"effect": "committed"}}},
    {"jsonrpc": "2.0", "id": 71, "error": {"code": -32000, "message": "RESULT_TOO_LARGE", "data": []}},
    {"jsonrpc": "2.0", "id": 71, "error": {"code": -32000, "message": "RESULT_TOO_LARGE", "data": {}}},
    {"jsonrpc": "2.0", "id": 71, "error": {"code": -32000, "message": "RESULT_TOO_LARGE", "data": {"effect": "rolled_back"}}},
    {"jsonrpc": "2.0", "id": 71, "error": {"code": -32000, "message": "RESULT_TOO_LARGE", "data": {"effect": True}}},
    {"error": {"code": "SCOPE_DENIED", "message": "private", "effect": "invalid"}},
    {"error": {"code": "private diagnostic", "message": "private", "effect": "not_started"}},
    {"id": 72, "error": {"code": "SCOPE_DENIED", "message": "private", "effect": "not_started"}},
    b"x" * 4097,
])
def test_unverified_http_error_is_unknown_even_after_write_and_can_be_reconciled(relay, loopback, payload):
    loopback.payload = payload
    result = relay.forward(mutation())
    assert result["error"]["data"] == {"effect": "unknown"}
    assert result["error"]["message"] == "RPC_RESPONSE_INVALID"
    assert "synthetic-secret" not in json.dumps(result)
    assert len(json.dumps(result).encode()) <= 4096
    assert len(loopback.requests) == 1
    assert relay.session_id is None
    receipt = json.loads(loopback.receipt.read_text())
    loopback.status = 200
    loopback.payload = {"jsonrpc": "2.0", "id": 72, "result": receipt}
    reconciled = relay.forward({"jsonrpc": "2.0", "id": 72, "method": "tools/call", "params": {
        "name": "memory_context", "arguments": {"business_key": "synthetic-same-business-key"},
    }})
    assert reconciled["result"]["business_key"] == "synthetic-same-business-key"
    assert reconciled["result"]["operation_id"] == "synthetic-operation-71"
    assert len(loopback.requests) == 2


@pytest.mark.parametrize("status", [200, 502])
def test_truncated_parseable_response_cannot_claim_noncommit(relay, loopback, status):
    loopback.status = status
    loopback.length_delta = 80
    loopback.payload = {"jsonrpc": "2.0", "id": 71, "error": {
        "code": -32000, "message": "INPUT_INVALID", "data": {"effect": "not_started"},
    }}
    result = relay.forward(mutation())
    assert loopback.receipt.exists()
    assert result["error"]["data"] == {"effect": "unknown"}
    assert len(loopback.requests) == 1


@pytest.mark.parametrize("disconnect", [False, True])
def test_lost_or_invalid_successful_write_response_is_unknown_without_retry(relay, loopback, disconnect):
    loopback.status = 200
    loopback.disconnect = disconnect
    loopback.payload = {"jsonrpc": "2.0", "id": 71, "result": []}
    result = relay.forward(mutation())
    assert result["error"]["data"] == {"effect": "unknown"}
    assert loopback.receipt.exists()
    assert len(loopback.requests) == 1
    assert relay.session_id is None


@pytest.mark.parametrize("status", [200, 502])
def test_notification_http_outcome_never_emits_response_or_installs_session(relay, loopback, status):
    loopback.status = status
    loopback.commit = False
    loopback.payload = b"" if status == 200 else b"private diagnostic"
    result = relay.forward({"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert result is None
    assert len(loopback.requests) == 1
    assert relay.session_id is None


@pytest.mark.parametrize("field", ["method", "name", "protocolVersion"])
@pytest.mark.parametrize("invalid_value", ["invalid\nheader", "invalid한글header"])
def test_invalid_transport_header_is_not_started_without_dispatch(relay, field, invalid_value):
    relay.opener = Opener([])
    request = mutation()
    if field == "method":
        request["method"] = invalid_value
    elif field == "name":
        request["params"]["name"] = invalid_value
    else:
        request["params"]["_meta"] = {"io.modelcontextprotocol/protocolVersion": invalid_value}
    result = relay.forward(request)
    assert result["error"]["data"] == {"effect": "not_started"}
    assert relay.opener.requests == []


@pytest.mark.parametrize("modern", [False, True])
def test_authenticated_loopback_error_keeps_legacy_or_modern_protocol_state(relay, loopback, modern):
    loopback.status = 200
    loopback.commit = False
    loopback.session = "synthetic-legacy-session"
    loopback.payload = {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-11-25"}}
    assert relay.forward(initialize())["result"]["protocolVersion"] == "2025-11-25"
    loopback.status = 502
    loopback.commit = True
    loopback.session = "must-not-poison-existing-session"
    loopback.payload = None
    request = mutation()
    if modern:
        request["params"]["_meta"] = {"io.modelcontextprotocol/protocolVersion": "2025-11-25"}
    result = relay.forward(request)
    assert result["error"]["data"] == {"effect": "committed"}
    assert relay.protocol_version == "2025-11-25"
    assert relay.session_id == "synthetic-legacy-session"
    observed = loopback.requests[-1]
    assert observed["version"] == "2025-11-25"
    assert observed["authorization"] == "Bearer " + relay.token_file.read_text()
    assert observed["session"] == (None if modern else "synthetic-legacy-session")
    assert len(loopback.requests) == 2


def test_invalid_nonascii_credential_is_not_started_without_dispatch(relay):
    relay.token_file.write_text("synthetic한글credential")
    relay.opener = Opener([])
    result = relay.forward(mutation())
    assert result["error"]["message"] == "RELAY_CREDENTIAL_UNAVAILABLE"
    assert result["error"]["data"] == {"effect": "not_started"}
    assert relay.opener.requests == []


@pytest.fixture
def scripted(relay):
    state = SimpleNamespace(responses=[], requests=[])

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state.requests.append({"request": request, "session": self.headers.get("Mcp-Session-Id")})
            status, payload, session = state.responses.pop(0)
            if callable(payload):
                payload = payload(request)
            body = b"" if payload is None else json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            if session:
                self.send_header("Mcp-Session-Id", session)
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
            self.close_connection = True

        def log_message(self, *args):
            return None

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    relay.settings = RelayEndpoint(f"http://127.0.0.1:{server.server_port}", max_mcp_response_bytes=4096)
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert not thread.is_alive()


def initialized_result(request):
    return {"jsonrpc": "2.0", "id": request["id"], "result": {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}}}}


def edge_rejection(code, effect="not_started", status=404):
    return (status, {"error": {"code": code, "message": "synthetic private edge detail", "effect": effect}}, None)


def legacy_session(relay, state):
    host_initialize = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "native-host", "version": "1"},
    }}
    state.responses.append((200, initialized_result, "first-session"))
    assert relay.forward(host_initialize)["result"]["protocolVersion"] == "2025-11-25"
    return host_initialize


def test_lost_session_reinitializes_and_resends_once_before_any_handler(relay, scripted):
    host_initialize = legacy_session(relay, scripted)
    final = {"jsonrpc": "2.0", "id": 71, "result": {"content": [{"type": "text", "text": "{}"}]}}
    scripted.responses.extend([
        edge_rejection("SESSION_NOT_FOUND"),
        (200, initialized_result, "second-session"),
        (202, None, "second-session"),
        (200, final, None),
    ])
    assert relay.forward(mutation()) == final
    methods = [item["request"]["method"] for item in scripted.requests]
    assert methods == ["initialize", "tools/call", "initialize", "notifications/initialized", "tools/call"]
    assert [item["session"] for item in scripted.requests] == [None, "first-session", None, "second-session", "second-session"]
    assert scripted.requests[2]["request"]["params"] == host_initialize["params"]
    assert scripted.requests[2]["request"]["id"] != host_initialize["id"]
    assert scripted.requests[4]["request"] == mutation()
    assert relay.session_id == "second-session"


@pytest.mark.parametrize("rejection", [
    edge_rejection("SESSION_CREDENTIAL_DENIED", status=403),
    edge_rejection("SESSION_NOT_FOUND", effect="unknown"),
    edge_rejection("SERVICE_BUSY", status=503),
])
def test_other_rejections_and_possible_commits_are_never_resent(relay, scripted, rejection):
    legacy_session(relay, scripted)
    scripted.responses.append(rejection)
    result = relay.forward(mutation())
    assert result["error"]["message"] == rejection[1]["error"]["code"]
    assert result["error"]["data"] == {"effect": rejection[1]["error"]["effect"]}
    assert len(scripted.requests) == 2
    assert relay.session_id == "first-session"


def test_session_recovery_is_attempted_at_most_once(relay, scripted):
    legacy_session(relay, scripted)
    scripted.responses.extend([
        edge_rejection("SESSION_NOT_FOUND"),
        (200, initialized_result, "second-session"),
        (202, None, "second-session"),
        edge_rejection("SESSION_NOT_FOUND"),
    ])
    result = relay.forward(mutation())
    assert result["error"]["message"] == "SESSION_NOT_FOUND"
    assert result["error"]["data"] == {"effect": "not_started"}
    assert len(scripted.requests) == 5


def test_failed_reinitialize_returns_the_original_not_started_rejection(relay, scripted):
    legacy_session(relay, scripted)
    scripted.responses.extend([
        edge_rejection("SESSION_NOT_FOUND"),
        (503, {"error": {"code": "SERVICE_DRAINING", "message": "draining", "effect": "not_started"}}, None),
    ])
    result = relay.forward(mutation())
    assert result["error"]["message"] == "SESSION_NOT_FOUND"
    assert result["error"]["data"] == {"effect": "not_started"}
    assert [item["request"]["method"] for item in scripted.requests] == ["initialize", "tools/call", "initialize"]
    assert relay.session_id is None
    # The next caller request recovers the session first instead of being sent without one.
    final = {"jsonrpc": "2.0", "id": 71, "result": {"content": [{"type": "text", "text": "{}"}]}}
    scripted.responses.extend([
        (200, initialized_result, "recovered-session"),
        (202, None, "recovered-session"),
        (200, final, None),
    ])
    assert relay.forward(mutation()) == final
    assert [item["request"]["method"] for item in scripted.requests[3:]] == ["initialize", "notifications/initialized", "tools/call"]
    assert [item["session"] for item in scripted.requests[3:]] == [None, "recovered-session", "recovered-session"]


def test_pending_recovery_that_fails_again_is_not_started_without_sending_the_request(relay, scripted):
    legacy_session(relay, scripted)
    scripted.responses.extend([
        edge_rejection("SESSION_NOT_FOUND"),
        edge_rejection("SERVICE_BUSY", status=503),
        edge_rejection("SERVICE_BUSY", status=503),
    ])
    relay.forward(mutation())
    result = relay.forward(mutation())
    assert result["error"]["message"] == "SESSION_NOT_FOUND"
    assert result["error"]["data"] == {"effect": "not_started"}
    assert [item["request"]["method"] for item in scripted.requests] == ["initialize", "tools/call", "initialize", "initialize"]


@pytest.mark.parametrize("payload", [
    {"error": {"code": "SESSION_NOT_FOUND", "effect": "not_started"}},
    {"error": {"code": "SESSION_NOT_FOUND", "message": "gone", "effect": "not_started"}, "extra": True},
    {"error": {"code": "SESSION_NOT_FOUND", "message": "gone", "effect": "maybe"}},
    {"error": "SESSION_NOT_FOUND"},
])
def test_malformed_session_rejection_is_unknown_and_never_resent(relay, scripted, payload):
    legacy_session(relay, scripted)
    scripted.responses.append((404, payload, None))
    result = relay.forward(mutation())
    assert result["error"]["message"] == "RPC_RESPONSE_INVALID"
    assert result["error"]["data"] == {"effect": "unknown"}
    assert [item["request"]["method"] for item in scripted.requests] == ["initialize", "tools/call"]


def test_recovery_refuses_a_server_that_negotiates_another_protocol_version(relay, scripted):
    legacy_session(relay, scripted)

    def other_version(request):
        return {"jsonrpc": "2.0", "id": request["id"], "result": {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}}}

    scripted.responses.extend([edge_rejection("SESSION_NOT_FOUND"), (200, other_version, "other-version-session")])
    result = relay.forward(mutation())
    assert result["error"]["message"] == "SESSION_NOT_FOUND"
    assert result["error"]["data"] == {"effect": "not_started"}
    assert [item["request"]["method"] for item in scripted.requests] == ["initialize", "tools/call", "initialize"]
    assert (relay.session_id, relay.protocol_version, relay.recovery_pending) == (None, "2025-11-25", True)
