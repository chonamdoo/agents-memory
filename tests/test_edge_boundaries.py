from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

import pytest
from test_store_authority import VECTOR, command, extraction
from test_store_authority import authority as authority

from agents_memory.application import Application
from agents_memory.context import compose
from agents_memory.domain import Consolidation, ContextCommand, EffectState, RecordCommand, Role
from agents_memory.edge import SecurityEdge, create_app

VERSION = "2026-07-28"
META = {
    "io.modelcontextprotocol/protocolVersion": VERSION,
    "io.modelcontextprotocol/clientCapabilities": {},
}
AGENT_TOKEN = "wire-boundary-agent-credential-" + "w" * 32


async def request(edge, payload, token=AGENT_TOKEN, *, path="/mcp", extra_headers=(), method="POST"):
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    headers = [
        (b"host", b"127.0.0.1:8768"),
        (b"authorization", f"Bearer {token}".encode()),
        (b"content-type", b"application/json"),
        (b"accept", b"application/json, text/event-stream"),
        (b"mcp-protocol-version", VERSION.encode()),
    ]
    if path == "/mcp" and isinstance(payload, dict):
        headers.append((b"mcp-method", payload.get("method", "tools/call").encode()))
        name = payload.get("params", {}).get("name")
        if isinstance(name, str):
            headers.append((b"mcp-name", name.encode()))
    headers.extend(extra_headers)
    messages = []
    incoming = asyncio.Queue()
    await incoming.put({"type": "http.request", "body": raw, "more_body": False})

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1", "scheme": "http", "method": method,
        "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "",
        "server": ("127.0.0.1", 8768), "client": ("127.0.0.1", 59999),
        "headers": headers, "state": {},
    }
    await asyncio.wait_for(edge(scope, incoming.get, send), 10)
    starts = [item for item in messages if item["type"] == "http.response.start"]
    body = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
    assert len(starts) == 1
    return starts[0]["status"], body


@asynccontextmanager
async def running(authority):
    settings = authority.store.settings
    await authority.store.issue_token(authority.actor, Role.AGENT, (authority.binding_id,), AGENT_TOKEN)
    edge = create_app(settings)
    async with edge.inner.router.lifespan_context(edge.inner):
        yield edge

def tool(arguments, *, name="memory_context", identifier=1):
    return {
        "jsonrpc": "2.0", "id": identifier, "method": "tools/call",
        "params": {"name": name, "arguments": arguments, "_meta": META},
    }


def tool_code(body):
    payload = json.loads(body)
    return json.loads(payload["result"]["content"][0]["text"])["error"]["code"]


@pytest.mark.asyncio
async def test_producer_capture_authority_never_grants_memory_read_authority(authority):
    producer_token = "wire-producer-only-" + "p" * 32
    await authority.store.issue_token(authority.actor, Role.PRODUCER, (authority.binding_id,), producer_token)
    async with running(authority) as edge:
        status, body = await request(edge, command(authority).model_dump(mode="json"), producer_token, path="/api/capture")
        assert status == 202
        source_id = json.loads(body)["source_id"]
        for path, payload in (
            ("/api/context", {"binding_id": authority.binding_id, "query": "private memory"}),
            ("/api/inspect", {"binding_id": authority.binding_id, "ref": source_id}),
        ):
            status, denied = await request(edge, payload, producer_token, path=path)
            assert status == 403
            assert json.loads(denied)["error"]["code"] == "SCOPE_DENIED"


@pytest.mark.parametrize("arguments", [
    {"query": "recall", "limit": "3"},
    {"query": "recall", "limit": 3.0},
    {"query": "recall", "max_bytes": "2400"},
    {"query": "recall", "max_bytes": 2400.0},
    {"query": "recall", "paths": [True]},
    {"query": "recall", "unexpected": 1},
])
async def test_actual_sdk_rejects_coercion_and_unknown_arguments(authority, arguments):
    async with running(authority) as edge:
        status, body = await request(edge, tool(arguments))
    assert status == 200
    assert tool_code(body) == "INPUT_INVALID"


@pytest.mark.parametrize("arguments", [
    {"query": "recall", "paths": [""]},
    {"query": "recall", "purpose": ""},
    {"query": "recall", "snapshot": ""},
])
async def test_empty_applicability_values_cannot_broaden_retrieval_scope(authority, arguments):
    async with running(authority) as edge:
        status, body = await request(edge, tool(arguments))
    assert status == 200
    assert tool_code(body) == "INPUT_INVALID"


async def test_internal_validation_failure_is_not_mislabeled_bad_input(authority, monkeypatch):
    async with running(authority) as edge:
        async def corrupt_context(*args):
            return ContextCommand.model_validate({"query": None})
        monkeypatch.setattr(edge.application, "context", corrupt_context)
        status, body = await request(edge, tool({"query": "valid caller query"}))
    assert status == 200
    assert tool_code(body) == "INTERNAL_ERROR"


@pytest.mark.parametrize("extra_headers,expected", [
    (((b"host", b"evil.invalid"),), "HEADERS_INVALID"),
    (((b"origin", b"https://evil.invalid"),), "HOST_ORIGIN_DENIED"),
    (((b"authorization", b"Bearer duplicate"),), "HEADERS_INVALID"),
    (((b"mcp-protocol-version", b"2025-11-25"),), "HEADERS_INVALID"),
])
async def test_authority_edge_rejects_ambiguous_security_headers(authority, extra_headers, expected):
    async with running(authority) as edge:
        status, body = await request(edge, tool({"query": "recall"}), extra_headers=extra_headers)
    assert status in {400, 403}
    assert json.loads(body)["error"]["code"] == expected


async def test_duplicate_json_key_is_rejected_before_sdk_or_mutation(authority):
    async with running(authority) as edge:
        status, body = await request(edge, b'{"jsonrpc":"2.0","id":1,"id":2,"method":"tools/list"}')
    assert status == 400
    assert json.loads(body)["error"]["code"] == "INPUT_INVALID"
    assert (await authority.store.stats(authority.actor, authority.binding_id))["active_sources"] == 0


async def test_rpc_id_cannot_expand_the_complete_response_past_wire_budget(authority):
    async with running(authority) as edge:
        status, body = await request(edge, tool({"query": "recall"}, identifier="x" * 20000))
    assert status == 400
    assert len(body) < authority.store.settings.max_mcp_response_bytes
    assert json.loads(body)["error"]["effect"] == "not_started"


@pytest.mark.parametrize("committed", [False, True])
async def test_complete_sdk_frame_limit_includes_outer_envelope_and_preserves_effect(authority, committed):
    await authority.store.issue_token(authority.actor, Role.AGENT, (authority.binding_id,), AGENT_TOKEN)
    limit = authority.store.settings.max_mcp_response_bytes
    async def downstream(scope, receive, send):
        if committed:
            scope["agents_memory_effect"] = EffectState.COMMITTED
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
        raw = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "x" * limit}]}}).encode()
        await send({"type": "http.response.body", "body": raw[:limit], "more_body": True})
        await send({"type": "http.response.body", "body": raw[limit:], "more_body": False})
    application = Application(authority.store.settings, authority.store, None)
    edge = SecurityEdge(downstream, application, authority.store.settings)
    status, body = await request(edge, tool({"idempotency_key": "bounded-mutation", "body": "evidence"}, name="memory_record"))
    assert status == 502
    assert len(body) <= limit
    payload = json.loads(body)
    assert payload["error"]["message"] == "RESULT_TOO_LARGE"
    assert payload["error"]["data"]["effect"] == ("committed" if committed else "unknown")
    assert application.inflight == 0


async def test_private_api_uses_same_strict_wire_schema(authority):
    async with running(authority) as edge:
        status, body = await request(edge, {"query": "recall", "limit": "3"}, path="/api/context")
    assert status == 400
    assert json.loads(body)["error"]["code"] == "INPUT_INVALID"


async def test_http_size_limit_precedes_json_decode_and_never_echoes_input(authority):
    async with running(authority) as edge:
        status, body = await request(edge, b"x" * (authority.store.settings.max_http_body_bytes + 1))
    assert status == 413
    assert json.loads(body)["error"]["code"] == "INPUT_TOO_LARGE"
    assert len(body) < 512


async def test_sdk_inspect_can_read_returned_snapshot_ref_but_not_another_revision(authority):
    store, actor = authority.store, authority.actor
    operation = await store.capture(actor, command(authority, snapshot="revision-A"))
    lease = await store.claim_job()
    admission = await store.admit_job(lease, authority.revision, "extraction")
    await store.publish_extraction(lease, admission, extraction(operation.source_id), [VECTOR], [["CacheKey"]])
    followup = await store.claim_job()
    manifest = await store.admit_job(followup, authority.revision, "consolidation")
    await store.publish_consolidation(followup, manifest, Consolidation(relations=()))
    ref = (await store.search(actor, authority.binding_id, VECTOR, ["CacheKey"], "revision-A"))[0][0].id
    async with running(authority) as edge:
        status, body = await request(edge, tool({"ref": ref, "snapshot": "revision-A"}, name="memory_inspect"))
        denied_status, denied_body = await request(edge, tool({"ref": ref, "snapshot": "revision-B"}, name="memory_inspect", identifier=2))
    assert status == denied_status == 200
    item = json.loads(json.loads(body)["result"]["content"][0]["text"])
    assert item["snapshot"] == "revision-A"
    assert item["statement"] == "CacheKey is retained only offline."
    denied = json.loads(denied_body)["result"]
    assert denied["isError"] is True
    assert "statement" not in json.loads(denied["content"][0]["text"])


@pytest.mark.parametrize("stored_snapshot", (None, "revision-A"))
@pytest.mark.parametrize("requested_snapshot", (None, "revision-A", "revision-B"))
@pytest.mark.parametrize("transport", ("mcp", "api"))
async def test_source_inspect_enforces_snapshot_before_body_delivery(authority, stored_snapshot, requested_snapshot, transport):
    captured = command(authority, snapshot=stored_snapshot)
    operation = await authority.store.capture(authority.actor, captured)
    arguments = {"binding_id": authority.binding_id, "ref": operation.source_id}
    if requested_snapshot is not None:
        arguments["snapshot"] = requested_snapshot
    async with running(authority) as edge:
        if transport == "mcp":
            status, body = await request(edge, tool(arguments, name="memory_inspect"))
            assert status == 200
            result = json.loads(body)["result"]
            item = json.loads(result["content"][0]["text"])
        else:
            status, body = await request(edge, arguments, path="/api/inspect")
            item = json.loads(body)
    if stored_snapshot is None or stored_snapshot == requested_snapshot:
        assert status == 200
        assert item["id"] == operation.source_id
        assert item["snapshot"] == stored_snapshot
        assert item["body"] == captured.body
    else:
        if transport == "mcp":
            assert result["isError"] is True
        else:
            assert 400 <= status < 500
        assert item["error"]["code"] == "SNAPSHOT_INELIGIBLE"
        assert "body" not in item and captured.body not in body.decode()


async def test_overflowing_json_number_is_rejected_without_nonfinite_sdk_state(authority):
    async with running(authority) as edge:
        status, body = await request(edge, b'{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{"_meta":{"untrusted":1e999}}}')
    assert status == 400
    assert json.loads(body)["error"]["code"] == "INPUT_INVALID"


@pytest.mark.parametrize("source_speaker", ("human", "agent_note"))
async def test_authoritative_source_speaker_survives_claim_read_and_recall(authority, source_speaker):
    store, actor = authority.store, authority.actor
    captured = command(authority)
    if source_speaker == "agent_note":
        operation = await store.record(actor, RecordCommand(
            binding_id=authority.binding_id, idempotency_key="agent-note", body=captured.body,
        ))
    else:
        operation = await store.capture(actor, captured)
    lease = await store.claim_job()
    admission = await store.admit_job(lease, authority.revision, "extraction")
    await store.publish_extraction(lease, admission, extraction(operation.source_id), [VECTOR], [["CacheKey"]])
    claim = (await store.search(actor, authority.binding_id, VECTOR, ["CacheKey"], None))[0][0]
    rendered = compose(ContextCommand(query="CacheKey"), (), (claim,), ())
    context = json.loads(rendered.text)
    candidate = context["memory_candidates"][0]
    assert context["approved_rules"] == []
    assert candidate["interpretation_role"] == "model_derived_candidate"
    assert {span["source_speaker"] for span in candidate["evidence"]} == {source_speaker}
    assert {span["source"] for span in candidate["evidence"]} == {operation.source_id}
    async with running(authority) as edge:
        status, raw = await request(edge, tool(
            {"binding_id": authority.binding_id, "ref": claim.id}, name="memory_inspect",
        ))
    assert status == 200
    inspected = json.loads(json.loads(raw)["result"]["content"][0]["text"])
    assert {span["source_speaker"] for span in inspected["evidence"]} == {source_speaker}
