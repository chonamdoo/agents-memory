from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import asyncpg
import pytest
import pytest_asyncio
from jsonschema import Draft202012Validator
from test_store_authority import TOKEN, command, ready_claim, source_selection
from test_store_authority import authority as authority

from agents_memory import edge as edge_module
from agents_memory.application import Application
from agents_memory.config import Settings
from agents_memory.context import compose
from agents_memory.domain import (
    CaptureCommand,
    CaptureCoverage,
    ContextCommand,
    DomainError,
    EffectState,
    Role,
)
from agents_memory.edge import SecurityEdge, create_app
from agents_memory.journal import DeletionJournal
from agents_memory.migrations import migrate
from agents_memory.store import Store

VERSION = "2026-07-28"
META = {
    "io.modelcontextprotocol/protocolVersion": VERSION,
    "io.modelcontextprotocol/clientCapabilities": {},
}
AGENT_TOKEN = "wire-boundary-agent-credential-" + "w" * 32


async def request(
    edge, payload, token=AGENT_TOKEN, *, path="/mcp", extra_headers=(), method="POST",
    protocol_version=VERSION, include_headers=False, body_receive=None,
):
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    headers = [
        (b"host", b"127.0.0.1:8768"),
        *([(b"authorization", f"Bearer {token}".encode())] if token is not None else []),
        (b"content-type", b"application/json"),
        (b"accept", b"application/json, text/event-stream"),
        (b"mcp-protocol-version", protocol_version.encode()),
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
    await asyncio.wait_for(edge(scope, body_receive or incoming.get, send), 10)
    starts = [item for item in messages if item["type"] == "http.response.start"]
    body = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
    assert len(starts) == 1
    if include_headers:
        return starts[0]["status"], body, dict(starts[0].get("headers", ()))
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
            ("/api/record", {
                "kind": "source_selection", "binding_id": authority.binding_id,
                "idempotency_key": "producer-selection", "source_id": source_id,
                "source_revision": 1, "binding_revision": 1, "byte_start": 0, "byte_end": 1,
                "window_digest": "a" * 64, "policy_revision": "b" * 64, "policy_epoch": 0,
                "label": "remember", "coverage": "incomplete_window",
            }),
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


@pytest.mark.parametrize("transport", ("modern", "legacy"))
@pytest.mark.parametrize("failure", ("exception", "overflow"))
async def test_inspect_failure_after_durable_admission_never_reports_not_started(authority, monkeypatch, transport, failure):
    source = await authority.store.capture(authority.actor, command(authority))
    async with running(authority) as edge:
        original = edge.application.inspect

        async def fail_after_admission(*args, **kwargs):
            inspected = await original(*args, **kwargs)
            if failure == "exception":
                raise RuntimeError("Synthetic post-admission boundary failure")
            return {**inspected, "oversized": "x" * authority.store.settings.max_mcp_response_bytes}

        monkeypatch.setattr(edge.application, "inspect", fail_after_admission)
        payload = tool({"binding_id": authority.binding_id, "ref": source.source_id}, name="memory_inspect")
        status, raw = await (legacy_request(edge, payload) if transport == "legacy" else request(edge, payload))
        caller = await authority.store.authenticate(AGENT_TOKEN)
        async with authority.store.pool.acquire() as connection:
            admission, = await connection.fetch(
                """SELECT binding_id,credential_id,purpose,sources FROM am_admissions
                WHERE binding_id=$1 AND credential_id=$2 AND purpose='source_selection'""",
                authority.binding_id, caller.credential_id,
            )
        assert admission["binding_id"] == authority.binding_id
        assert admission["credential_id"] == caller.credential_id and admission["purpose"] == "source_selection"
        inputs = json.loads(admission["sources"]) if isinstance(admission["sources"], str) else admission["sources"]
        assert inputs == [{"id": source.source_id, "revision": source.source_pointer.source_revision}]
    response = json.loads(raw)
    if failure == "exception":
        assert status == 200 and response["result"]["isError"] is True
        error = json.loads(response["result"]["content"][0]["text"])["error"]
        assert error["code"] == "INTERNAL_ERROR" and error["effect"] == "unknown"
    else:
        assert status == 502
        error = response["error"]
        assert error["message"] == "RESULT_TOO_LARGE" and error["data"]["effect"] == "committed"


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
    application = Application(authority.store.settings, authority.store)
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
    _, selected = await ready_claim(authority, snapshot="revision-A")
    ref = selected.id
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
        assert item["snapshot"] == requested_snapshot
        assert item["source_snapshot"] == stored_snapshot
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


async def test_source_provenance_and_independent_grounding_survive_transport(authority):
    operation, claim = await ready_claim(authority)
    rendered = compose(ContextCommand(query="CacheKey"), (), (claim,), ())
    context = json.loads(rendered.text)
    candidate = context["memory_candidates"][0]
    assert context["approved_rules"] == []
    assert candidate["interpretation_role"] == "caller_grounded_candidate"
    assert {span["source_speaker"] for span in candidate["evidence"]} == {"human"}
    assert {span["source"] for span in candidate["evidence"]} == {operation.source_id}
    async with running(authority) as edge:
        status, raw = await request(edge, tool(
            {"binding_id": authority.binding_id, "ref": claim.id}, name="memory_inspect",
        ))
    assert status == 200
    inspected = json.loads(json.loads(raw)["result"]["content"][0]["text"])
    assert {span["source_speaker"] for span in inspected["evidence"]} == {"human"}


@pytest_asyncio.fixture
async def company_authority(tmp_path):
    raw_dsn = os.environ.get("PG_TEST_DSN")
    if not raw_dsn:
        pytest.skip("PG_TEST_DSN explicitly required for isolated lexical authority regressions")
    parts = urlsplit(raw_dsn)
    query = dict(parse_qsl(parts.query))
    query.pop("schema", None)
    admin_dsn = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    schema = "am_edge_lexical_" + uuid.uuid4().hex
    admin = await asyncpg.connect(admin_dsn)
    store = None
    try:
        await admin.execute(f'CREATE SCHEMA "{schema}"')
        query["schema"] = schema
        dsn = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
        await asyncio.to_thread(migrate, dsn)
        settings = Settings(
            deployment_id="edge_lexical", realm="company_edge_test", mode="company",
            database_dsn=dsn,
            state_dir=tmp_path / "authority", journal_dir=tmp_path / "journal",
        )
        store = Store(settings, DeletionJournal(settings.journal_dir, settings.deployment_id))
        await store.open()
        token = "lexical-test-operator-" + "o" * 32
        actor = await store.bootstrap(token, "lexical_owner")
        binding = await store.register_binding(actor, "Synthetic lexical project", None, "binding-key")
        actor = await store.authenticate(token)
        yield SimpleNamespace(store=store, actor=actor, binding_id=binding.id, token=token)
    finally:
        if store is not None:
            await store.close()
        await admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await admin.close()


@pytest.fixture(params=("authority", "company_authority"))
def judgment_authority(request):
    return request.getfixturevalue(request.param)


def selection_arguments(binding_id, source_id):
    return {
        "kind": "source_selection", "binding_id": binding_id,
        "idempotency_key": "selection-boundary", "source_id": source_id,
        "admission_id": "admission-shape", "reason": "Caller inspected this original window.",
        "source_revision": 1, "binding_revision": 1,
        "byte_start": 0, "byte_end": 3,
        "window_digest": "a" * 64, "policy_revision": "b" * 64, "policy_epoch": 0,
        "label": "remember", "coverage": "complete_window",
    }


def record_rejection_cases(binding_id):
    note = {
        "binding_id": binding_id, "idempotency_key": "record-shape",
        "body": "CacheKey stays offline.",
    }
    selection = selection_arguments(binding_id, "source-001")
    judgment = {
        "kind": "claim_judgment", "binding_id": binding_id, "idempotency_key": "claim-shape",
        "admission_id": "admission-shape", "manifest_digest": "c" * 64,
        "claims": [{"id": "claim-001", "revision": 1}],
        "sources": [{"id": "source-001", "revision": 1}], "relations": [],
        "reason": "Caller inspected this exact claim and source manifest.",
    }
    for kind in ("note", "rule_candidate"):
        yield f"{kind}-missing-body", {key: value for key, value in {**note, "kind": kind}.items() if key != "body"}
        yield f"{kind}-mixed-fields", {**note, "kind": kind, "source_id": "source-001"}
        yield f"{kind}-null-policy", {**note, "kind": kind, "policy_revision": None}
    for field in (
        "source_id", "source_revision", "binding_revision", "byte_start", "byte_end",
        "window_digest", "policy_revision", "policy_epoch", "label", "coverage",
        "idempotency_key", "admission_id", "reason",
    ):
        yield f"selection-missing-{field}", {key: value for key, value in selection.items() if key != field}
    for field in (
        "kind", "idempotency_key", "admission_id", "manifest_digest", "claims", "sources", "relations", "reason",
    ):
        yield f"judgment-missing-{field}", {key: value for key, value in judgment.items() if key != field}
    for name, changes in (
        ("blank-reason", {"reason": "   "}), ("null-admission", {"admission_id": None}),
        ("extra", {"unexpected": "field"}), ("mixed-body", {"body": note["body"]}),
        ("wrong-revision", {"claims": [{"id": "claim-001", "revision": "1"}]}),
        ("boolean-revision", {"sources": [{"id": "source-001", "revision": True}]}),
        ("nested-extra", {"claims": [{"id": "claim-001", "revision": 1, "unexpected": "field"}]}),
        ("null-relations", {"relations": None}),
    ):
        yield f"judgment-{name}", {**judgment, **changes}
    yield "kindless-note-missing-body", {key: value for key, value in note.items() if key != "body"}
    yield "note-extra", {**note, "unexpected": "field"}
    yield "note-null-body", {**note, "body": None}
    yield "note-wrong-body-type", {**note, "body": 1}
    for name, changes in (
        ("extra", {"unexpected": "field"}), ("mixed-body", {"body": note["body"]}),
        ("invalid-kind", {"kind": "unsupported"}), ("note-kind", {"kind": "note"}),
        ("null-source", {"source_id": None}), ("null-admission", {"admission_id": None}),
        ("blank-reason", {"reason": "   "}), ("wrong-revision", {"source_revision": "1"}),
        ("boolean-epoch", {"policy_epoch": False}), ("wrong-offset", {"byte_start": "0"}),
    ):
        yield f"selection-{name}", {**selection, **changes}
    yield "selection-without-kind", {key: value for key, value in selection.items() if key != "kind"}


async def legacy_request(edge, payload):
    version = "2025-11-25"
    status, raw, headers = await request(edge, {
        "jsonrpc": "2.0", "id": "legacy-initialize", "method": "initialize",
        "params": {
            "protocolVersion": version, "capabilities": {},
            "clientInfo": {"name": "lexical-boundary", "version": "1"},
        },
    }, protocol_version=version, include_headers=True)
    assert status == 200 and "result" in json.loads(raw)
    session = ((b"mcp-session-id", headers[b"mcp-session-id"]),)
    await request(edge, {
        "jsonrpc": "2.0", "method": "notifications/initialized",
    }, protocol_version=version, extra_headers=session)
    payload["params"].pop("_meta", None)
    return await request(edge, payload, protocol_version=version, extra_headers=session)


async def record_request(edge, arguments, transport, identifier=1):
    if transport == "api":
        status, body = await request(edge, arguments, path="/api/record")
        return status, json.loads(body)
    payload = tool(arguments, name="memory_record", identifier=identifier)
    status, body = await (legacy_request(edge, payload) if transport == "legacy" else request(edge, payload))
    return status, json.loads(json.loads(body)["result"]["content"][0]["text"])


async def inspect_request(edge, arguments, transport, identifier=1):
    if transport == "api":
        status, body = await request(edge, arguments, path="/api/inspect")
    else:
        payload = tool(arguments, name="memory_inspect", identifier=identifier)
        status, body = await (legacy_request(edge, payload) if transport == "legacy" else request(edge, payload))
        body = json.loads(body)["result"]["content"][0]["text"]
    return status, json.loads(body)


@pytest.mark.parametrize("transport", ("modern", "legacy", "api"))
@pytest.mark.parametrize("changes", (
    {"source_revision": "1"}, {"policy_epoch": False}, {"byte_start": 0.0},
    {"byte_end": 4097}, {"label": "approve"}, {"unexpected": "authority"},
    {"kind": "note"},
    {"label": "discard", "extraction": {
        "claims": [], "individual_qualifications": [], "shared_qualifications": [],
        "validities": [], "unused_span_ids": [],
    }},
))
async def test_record_union_rejects_invalid_complete_judgments_before_capture(company_authority, transport, changes):
    arguments = {**selection_arguments(company_authority.binding_id, "foreign-source"), **changes}
    async with running(company_authority) as edge:
        status, result = await record_request(edge, arguments, transport)
    assert status == (400 if transport == "api" else 200)
    assert result["error"]["code"] == "INPUT_INVALID"
    assert result["error"]["effect"] == "not_started"
    assert (await company_authority.store.stats(company_authority.actor, company_authority.binding_id))["active_sources"] == 0


@pytest.mark.parametrize("transport", ("modern", "legacy", "api"))
@pytest.mark.parametrize("label", ("remember", "discard", "review"))
async def test_original_window_judgments_are_durable_without_claim_publication(judgment_authority, transport, label):
    store, actor = judgment_authority.store, judgment_authority.actor
    body = "원문 창만 판단한다. 원문 창만 판단한다."
    operation = await store.capture(actor, CaptureCommand(
        binding_id=judgment_authority.binding_id, idempotency_key="original-source",
        origin_key="original-source", body=body, speaker="human",
        coverage=CaptureCoverage(status="observed_window", original_bytes=len(body.encode())),
    ))
    async with running(judgment_authority) as edge:
        status, window = await inspect_request(edge, {
            "binding_id": judgment_authority.binding_id, "ref": operation.source_id,
            "byte_start": 0, "max_bytes": 4096,
        }, transport)
        assert status == 200
        arguments = {
            **selection_arguments(judgment_authority.binding_id, operation.source_id),
            "source_revision": window["source_revision"], "binding_revision": window["binding_revision"],
            "byte_start": window["byte_start"], "byte_end": window["byte_end"],
            "window_digest": window["window_digest"], "policy_revision": window["policy_revision"],
            "policy_epoch": window["policy_epoch"], "label": label, "admission_id": window["admission_id"],
        }
        schemas = await tool_schemas_request(edge, "legacy" if transport == "legacy" else "modern")
        assert Draft202012Validator(schemas["memory_record"]).is_valid(arguments)
        status, selected = await record_request(edge, arguments, transport)
        assert status == 200
        assert selected["state"] == "selection_recorded"
        assert selected["selection_label"] == label
        assert "body" not in selected and body not in json.dumps(selected, ensure_ascii=False)
        _, replay = await record_request(edge, arguments, transport, identifier=2)
        assert replay["id"] == selected["id"]
        status, inspected = await inspect_request(edge, {
            "binding_id": judgment_authority.binding_id, "ref": selected["id"],
        }, transport)
        assert status == 200 and inspected["state"] == "selection_recorded"
        assert "body" not in inspected and body not in json.dumps(inspected, ensure_ascii=False)
    assert (await store.stats(actor, judgment_authority.binding_id))["active_claims"] == 0


@pytest.mark.parametrize("transport", ("modern", "legacy", "api"))
async def test_claim_judgments_bind_inspected_manifest_and_return_body_free_receipts(judgment_authority, transport):
    deployment = judgment_authority
    source_body = "CacheKey is retained only offline."
    _, left = await ready_claim(deployment, "left-claim", body=source_body)
    _, right = await ready_claim(deployment, "right-claim", body=source_body)
    async with running(deployment) as edge:
        status, manifest = await inspect_request(edge, {
            "binding_id": deployment.binding_id, "ref": "judgment",
        }, transport)
        assert status == 200
        for identifier, claim in enumerate(manifest["claims"], 2):
            status, inspected = await inspect_request(edge, {
                "binding_id": deployment.binding_id, "ref": claim["id"],
            }, transport, identifier)
            assert status == 200 and inspected["id"] == claim["id"]
        arguments = {
            "kind": "claim_judgment", "binding_id": deployment.binding_id,
            "idempotency_key": "transport-claim-judgment", "admission_id": manifest["admission_id"],
            "manifest_digest": manifest["manifest_digest"],
            "claims": manifest["claims"], "sources": manifest["sources"],
            "relations": [{
                "left_id": left.id, "right_id": right.id, "relation": "supports",
                "reason": "Caller compared the independent original evidence.",
            }],
            "reason": "Caller inspected every claim and source in this exact manifest.",
        }
        schemas = await tool_schemas_request(edge, "legacy" if transport == "legacy" else "modern")
        assert Draft202012Validator(schemas["memory_record"]).is_valid(arguments)
        status, committed = await record_request(edge, arguments, transport)
        assert status == 200 and committed["state"] == "candidate_ready"
        assert committed["effect"] == "committed"
        assert "body" not in committed and source_body not in json.dumps(committed)
        status, replay = await record_request(edge, arguments, transport, identifier=2)
        assert status == 200 and replay["id"] == committed["id"]
        status, inspected = await inspect_request(edge, {
            "binding_id": deployment.binding_id, "ref": committed["artifact_id"],
        }, transport)
        assert status == 200 and inspected["kind"] == "judgment"
        assert inspected["claims"] == arguments["claims"] and inspected["sources"] == arguments["sources"]
        assert inspected["relations"] == arguments["relations"] and inspected["reason"] == arguments["reason"]
        assert "body" not in inspected and source_body not in json.dumps(inspected)
    assert (await deployment.store.stats(deployment.actor, deployment.binding_id))["active_claims"] == 2


@pytest.mark.parametrize("transport", ("modern", "legacy", "api"))
async def test_original_utf8_inspection_window_cannot_split_codepoints_or_expand_bounds(company_authority, transport):
    captured = await company_authority.store.capture(company_authority.actor, CaptureCommand(
        binding_id=company_authority.binding_id, idempotency_key="utf8-window",
        origin_key="utf8-window", body="가나다", speaker="human",
    ))
    async with running(company_authority) as edge:
        async def inspect(arguments):
            if transport == "api":
                status, raw = await request(edge, arguments, path="/api/inspect")
                return status, json.loads(raw)
            payload = tool(arguments, name="memory_inspect")
            status, raw = await (legacy_request(edge, payload) if transport == "legacy" else request(edge, payload))
            return status, json.loads(json.loads(raw)["result"]["content"][0]["text"])

        base = {"binding_id": company_authority.binding_id, "ref": captured.source_id}
        status, window = await inspect({**base, "byte_start": 3, "max_bytes": 4})
        assert status == 200 and window["body"] == "나"
        assert window["byte_start"] == 3 and window["byte_end"] == window["next_byte"] == 6
        _, split = await inspect({**base, "byte_start": 1, "max_bytes": 3})
        assert split["error"]["code"] == "SOURCE_WINDOW_INVALID"
        _, expanded = await inspect({**base, "max_bytes": 4097})
        assert expanded["error"]["code"] == "INPUT_INVALID"
        assert "body" not in split and "body" not in expanded




@pytest.mark.parametrize("transport", ("modern", "legacy", "api"))
@pytest.mark.parametrize("kind", (None, "note", "rule_candidate"))
async def test_record_union_preserves_original_note_role_and_inactive_rule_path(judgment_authority, transport, kind):
    body = "Never expose credentials."
    async with running(judgment_authority) as edge:
        arguments = {
            "binding_id": None if kind is None else judgment_authority.binding_id,
            "idempotency_key": "original-record-path", "body": body,
        }
        if kind is not None:
            arguments["kind"] = kind
        schemas = await tool_schemas_request(edge, "legacy" if transport == "legacy" else "modern")
        assert Draft202012Validator(schemas["memory_record"]).is_valid(arguments)
        status, operation = await record_request(edge, arguments, transport)
        assert status == 200 and operation["effect"] == "committed"
        ref = operation["artifact_id"] if kind == "rule_candidate" else operation["source_id"]
        status, item = await inspect_request(edge, {
            "binding_id": judgment_authority.binding_id, "ref": ref,
        }, transport)
        assert status == 200 and item["body"] == body
        if kind != "rule_candidate":
            assert item["speaker"] == "agent_note"
        else:
            assert item["candidate"] is True
    assert not await judgment_authority.store.rules(judgment_authority.actor, judgment_authority.binding_id)




async def tool_schemas_request(edge, transport="modern"):
    payload = {
        "jsonrpc": "2.0", "id": "\x01" * 256, "method": "tools/list", "params": {"_meta": META},
    }
    status, raw = await (legacy_request(edge, payload) if transport == "legacy" else request(edge, payload))
    assert status == 200
    assert len(raw) <= edge.application.settings.max_mcp_response_bytes
    schemas = {item["name"]: item["inputSchema"] for item in json.loads(raw)["result"]["tools"]}
    assert set(schemas) == {"memory_context", "memory_inspect", "memory_record", "memory_feedback"}
    for schema in schemas.values():
        Draft202012Validator.check_schema(schema)
        assert schema["type"] == "object" and isinstance(schema["properties"], dict)
    return schemas






@pytest.mark.parametrize("transport", ("modern", "legacy", "api"))
async def test_record_shape_rejections_reach_actual_transport_decoders(judgment_authority, transport):
    async with running(judgment_authority) as edge:
        schemas = await tool_schemas_request(edge, "legacy" if transport == "legacy" else "modern")
        validator = Draft202012Validator(schemas["memory_record"])
        for identifier, (name, arguments) in enumerate(record_rejection_cases(judgment_authority.binding_id), 2):
            assert not validator.is_valid(arguments), name
            status, result = await record_request(edge, arguments, transport, identifier)
            assert status == (400 if transport == "api" else 200), name
            assert result["error"]["code"] == "INPUT_INVALID", name
            assert result["error"]["effect"] == "not_started", name
    assert (await judgment_authority.store.stats(judgment_authority.actor, judgment_authority.binding_id))["active_sources"] == 0



DENSE_BODIES = ("a\n" * 300, "Go. " * 300, '"\\' * 2048, "가. " * 2000)


async def assert_dense_source_inspects_with_continuation(deployment, body):
    operation = await deployment.store.capture(deployment.actor, CaptureCommand(
        binding_id=deployment.binding_id, idempotency_key="dense-source", origin_key="dense-source",
        body=body, speaker="human",
    ))
    limit = deployment.store.settings.max_mcp_response_bytes
    bodies, cursor = [], 0
    async with running(deployment) as edge:
        for identifier in range(1, 65):
            status, raw = await request(edge, tool({
                "binding_id": deployment.binding_id, "ref": operation.source_id, "byte_start": cursor,
            }, name="memory_inspect", identifier=identifier))
            assert status == 200 and len(raw) <= limit
            result = json.loads(raw)["result"]
            assert result.get("isError") is not True
            window = json.loads(result["content"][0]["text"])
            assert window["byte_start"] == cursor < window["byte_end"]
            assert 0 < len(window["span_inventory"]) <= 128
            bodies.append(window["body"])
            cursor = window["next_byte"]
            if cursor is None:
                break
    assert len(bodies) > 1
    assert "".join(bodies) == body


@pytest.mark.parametrize("body", DENSE_BODIES)
async def test_personal_dense_source_inspects_in_bounded_continuation_windows(authority, body):
    await assert_dense_source_inspects_with_continuation(authority, body)


@pytest.mark.parametrize("body", DENSE_BODIES)
async def test_company_dense_source_inspects_in_bounded_continuation_windows(company_authority, body):
    await assert_dense_source_inspects_with_continuation(company_authority, body)


async def test_required_company_context_has_nonmodel_fence_even_without_selected_claims(
        company_authority, monkeypatch):
    from agents_memory.domain import RuleApproval, RuleProposal, RuleScope

    store, actor, binding = company_authority.store, company_authority.actor, company_authority.binding_id
    proposal = await store.propose_rule(actor, RuleProposal(
        binding_id=binding, idempotency_key="required-proposal", body="Keep synthetic credentials offline.",
        required=True,
    ))
    rule = await store.approve_rule(actor, RuleApproval(
        proposal_id=proposal["proposal_id"], expected_digest=proposal["digest"],
        scope=RuleScope.LOCAL_PROJECT, target_bindings=(binding,),
        target_set_revision=proposal["target_set_revision"], idempotency_key="required-approval",
    ))
    async with running(company_authority) as edge:
        payload = {"binding_id": binding, "query": "apply required safety rules"}
        status, raw = await request(edge, payload, path="/api/required-context")
        delivered = json.loads(raw)
        assert status == 200 and delivered["required"] is True
        assert rule.body in delivered["context"]
        assert delivered["stamp"]["rules"] == [[rule.id, rule.revision, rule.digest]]
        final_delivery = Store.delivery

        async def change_rules_before_delivery(self, *args, **kwargs):
            await store.withdraw_rule(actor, binding, rule.id, "required-withdraw")
            return await final_delivery(self, *args, **kwargs)

        monkeypatch.setattr(Store, "delivery", change_rules_before_delivery)
        status, raw = await request(edge, payload, path="/api/required-context")
        assert status >= 400
        assert json.loads(raw)["error"]["code"] == "CONTEXT_STALE"
        assert rule.body not in raw.decode()


async def test_large_accepted_multilingual_claim_has_complete_modern_continuation(company_authority):
    import hashlib

    from agents_memory.semantic_contract import GeneratedExtraction

    store, actor, binding = company_authority.store, company_authority.actor, company_authority.binding_id
    body = "CacheKey is retained only offline. " + "가" * 320 + "."
    source = await store.capture(actor, CaptureCommand(
        binding_id=binding, idempotency_key="large-draft-source", origin_key="large-draft-source",
        body=body, speaker="human",
    ))
    window = await store.inspect(actor, binding, source.source_id)
    assertion, qualification = window["span_inventory"]
    selected = await source_selection(company_authority, source.source_id, "large-draft-selection")
    generated = GeneratedExtraction(
        claims=selected.extraction.claims,
        individual_qualifications=(
            {"assertion_id": "a0000", "kind": "condition", "phrase": "only offline",
             "evidence_span_id": assertion["span_id"]},
            *({"assertion_id": "a0000", "kind": "condition", "phrase": "가" * (280 + index),
               "evidence_span_id": qualification["span_id"]} for index in range(11)),
            *({"assertion_id": "a0000", "kind": "exception", "phrase": "가" * (291 + index),
               "evidence_span_id": qualification["span_id"]} for index in range(12)),
        ),
        shared_qualifications=(), validities=(), unused_span_ids=(),
    )
    arguments = selected.model_copy(update={"extraction": generated}).model_dump(mode="json")
    async with running(company_authority) as edge:
        _, admitted = await inspect_request(edge, {"binding_id": binding, "ref": source.source_id}, "modern")
        arguments.update({name: admitted[name] for name in (
            "admission_id", "source_revision", "binding_revision", "snapshot", "byte_start", "byte_end",
            "window_digest", "policy_revision", "policy_epoch",
        )})
        status, receipt = await record_request(edge, arguments, "modern")
        assert status == 200 and receipt.get("effect") == "committed", receipt
        _, selection = await inspect_request(edge, {"binding_id": binding, "ref": receipt["artifact_id"]}, "modern")
        claim_id = selection["claim_ids"][0]
        claim = await store.claim(actor, binding, claim_id)
        cursor, fragments, digest, total = 0, [], None, None
        for identifier in range(1, 128):
            status, raw = await request(edge, tool(
                {"binding_id": binding, "ref": claim_id, "byte_start": cursor},
                name="memory_inspect", identifier=identifier,
            ))
            assert status == 200 and len(raw) <= store.settings.max_mcp_response_bytes
            result = json.loads(raw)["result"]
            assert result.get("isError") is not True
            inspected = json.loads(result["content"][0]["text"])
            assert inspected["partial"] is True and "draft" not in inspected
            chunk = inspected["draft_window"]
            assert chunk["encoding"] == "utf-8-json"
            assert chunk["byte_start"] == cursor < chunk["byte_end"]
            assert chunk["byte_end"] - cursor == len(chunk["body"].encode("utf-8")) <= 4096
            digest = digest or chunk["digest"]
            total = total or chunk["total_bytes"]
            assert chunk["digest"] == digest and chunk["total_bytes"] == total
            fragments.append(chunk["body"].encode("utf-8"))
            cursor = chunk["next_byte"]
            if cursor is None:
                break
        assert cursor is None and len(fragments) > 1
        complete = b"".join(fragments)
        assert len(complete) == total and hashlib.sha256(complete).hexdigest() == digest
        recovered = json.loads(complete)
        assert recovered["draft"] == claim.draft.model_dump(mode="json", exclude={"evidence"})
        assert recovered["evidence"] == [span.model_dump(mode="json") for span in claim.evidence]
        assert recovered["input_source_ids"] == list(claim.input_source_ids)
        assert len(recovered["draft"]["conditions"]) == len(recovered["draft"]["exceptions"]) == 12
        assert recovered["statement"] == claim.draft.statement


async def test_maximum_expanded_full_manifest_and_required_context_fit_modern_wire(company_authority):
    from agents_memory.domain import RelevanceJudgment, RuleApproval, RuleProposal, RuleScope

    store, actor, binding = company_authority.store, company_authority.actor, company_authority.binding_id
    claims = [(await ready_claim(company_authority, f"wire-full-{index}"))[1] for index in range(20)]
    proposal = await store.propose_rule(actor, RuleProposal(
        binding_id=binding, idempotency_key="wire-required-rule", body="오프라인 " * 40, required=True,
    ))
    rule = await store.approve_rule(actor, RuleApproval(
        proposal_id=proposal["proposal_id"], expected_digest=proposal["digest"], scope=RuleScope.LOCAL_PROJECT,
        target_bindings=(binding,), target_set_revision=proposal["target_set_revision"],
        idempotency_key="wire-required-approval",
    ))
    command = ContextCommand(binding_id=binding, query="CacheKey",
        query_expansions=tuple("가" * 170 + f"{index:02d}" for index in range(8)), max_bytes=6144)
    async with running(company_authority) as edge:
        arguments = command.model_dump(mode="json")
        payload = json.dumps(tool(arguments, identifier="\x01" * 256), ensure_ascii=False).encode("utf-8")
        status, raw = await request(edge, payload, extra_headers=(
            (b"mcp-method", b"tools/call"), (b"mcp-name", b"memory_context"),
        ))
        assert status == 200 and len(raw) <= store.settings.max_mcp_response_bytes
        response = json.loads(raw)["result"]
        assert response.get("isError") is not True
        pool = json.loads(response["content"][0]["text"])
        assert "query_expansions" not in pool
        assert {item["claim_id"] for item in pool["candidate_manifest"]} == {claim.id for claim in claims}
        assert len(pool["candidate_manifest"]) == 20 and pool["refs"] == []
        assert json.loads(pool["context"])["approved_rules"][0]["body"] == rule.body
        arguments.update(admission_id=pool["admission_id"], relevance=[
            RelevanceJudgment(claim_id=claim.id, relevant=False,
                reason="Caller inspected this complete manifest and declined recall.").model_dump(mode="json")
            for claim in claims
        ])
        status, raw = await request(edge, json.dumps(tool(arguments), ensure_ascii=False).encode("utf-8"), extra_headers=(
            (b"mcp-method", b"tools/call"), (b"mcp-name", b"memory_context"),
        ))
        assert status == 200 and len(raw) <= store.settings.max_mcp_response_bytes
        selected = json.loads(json.loads(raw)["result"]["content"][0]["text"])
        assert selected["judgment_required"] is False and selected["refs"] == []
        assert json.loads(selected["context"])["approved_rules"][0]["body"] == rule.body


@pytest.mark.parametrize("transport", ("modern", "legacy", "api"))
@pytest.mark.parametrize("changes,code", (
    ({"snapshot": "token=sk-proj-" + "s" * 48}, "SOURCE_SECRET_REJECTED"),
    ({"byte_start": 9223372036854775808}, "INPUT_INVALID"),
    ({"claim_ids": ["same", "same"]}, "INPUT_INVALID"),
    ({"claim_ids": [f"claim-{index}" for index in range(21)]}, "INPUT_INVALID"),
))
async def test_inspect_invalid_fences_never_create_admission(company_authority, transport, changes, code):
    store = company_authority.store
    async with store.pool.acquire() as connection:
        before = await connection.fetchval("SELECT count(*) FROM am_admissions")
    async with running(company_authority) as edge:
        _, result = await inspect_request(edge, {
            "binding_id": company_authority.binding_id, "ref": "judgment", **changes,
        }, transport)
        assert result["error"]["code"] == code and result["error"]["effect"] == "not_started"
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT count(*) FROM am_admissions") == before


@pytest.mark.parametrize("transport", ("modern", "legacy", "api"))
async def test_inspect_explicit_claim_selection_retains_complete_requested_manifest(company_authority, transport):
    claims = [(await ready_claim(company_authority, f"selected-{index}"))[1] for index in range(21)]
    requested = [claims[-1].id, claims[0].id]
    async with running(company_authority) as edge:
        status, manifest = await inspect_request(edge, {
            "binding_id": company_authority.binding_id, "ref": "judgment", "claim_ids": requested,
        }, transport)
        assert status == 200
        assert {item["id"] for item in manifest["claims"]} == set(requested)
        assert {item["id"] for item in manifest["sources"]} == {
            source_id for claim in (claims[-1], claims[0]) for source_id in claim.input_source_ids
        }


@pytest.mark.parametrize("changes,code", (
    ({"snapshot": "ghp_" + "s" * 36}, "SOURCE_SECRET_REJECTED"),
    ({"byte_start": 9223372036854775808}, "INPUT_INVALID"),
    ({"byte_start": True}, "INPUT_INVALID"),
    ({"claim_ids": ("same", "same")}, "JUDGMENT_MANIFEST_INVALID"),
))
async def test_direct_inspect_rejects_invalid_fences_before_persistence(company_authority, changes, code):
    store = company_authority.store
    async with store.pool.acquire() as connection:
        before = await connection.fetchval("SELECT count(*) FROM am_admissions")
    with pytest.raises(DomainError) as refused:
        await store.inspect(company_authority.actor, company_authority.binding_id, "judgment", **changes)
    assert refused.value.code == code and refused.value.effect == EffectState.NOT_STARTED
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT count(*) FROM am_admissions") == before


async def bounded_inspection_plane(edge, deployment, arguments, transport, identifier=1):
    payload = tool(arguments, name="memory_inspect", identifier=identifier)
    status, raw = await (legacy_request(edge, payload) if transport == "legacy" else request(edge, payload))
    assert status == 200 and len(raw) <= deployment.store.settings.max_mcp_response_bytes
    result = json.loads(raw)["result"]
    assert "structuredContent" not in result
    assert len(result["content"]) == 1 and result["content"][0]["type"] == "text"
    return json.loads(result["content"][0]["text"])


async def reconstruct_stored_inspection(edge, deployment, ref, transport):
    import hashlib

    cursor, fragments, digest, total = 0, [], None, None
    for identifier in range(1, 129):
        inspected = await bounded_inspection_plane(edge, deployment, {
            "binding_id": deployment.binding_id, "ref": ref, "byte_start": cursor,
        }, transport, identifier)
        assert inspected["partial"] is True
        assert not {"reason", "relations", "rejection_comparisons", "source_provenance"} & inspected.keys()
        chunk = inspected["draft_window"]
        assert chunk["encoding"] == "utf-8-json" and chunk["byte_start"] == cursor
        fragment = chunk["body"].encode("utf-8")
        assert 0 < len(fragment) <= 4096 and chunk["byte_end"] - cursor == len(fragment)
        digest, total = digest or chunk["digest"], total or chunk["total_bytes"]
        assert chunk["digest"] == digest and chunk["total_bytes"] == total
        fragments.append(fragment)
        cursor = chunk["next_byte"]
        if cursor is None:
            break
    assert cursor is None and len(fragments) > 1
    raw = b"".join(fragments)
    assert len(raw) == total and hashlib.sha256(raw).hexdigest() == digest
    return json.loads(raw)


@pytest.mark.parametrize("transport", ("modern", "legacy"))
async def test_large_persisted_claim_judgment_reconstructs_every_reason_and_ref(company_authority, transport):
    from itertools import combinations

    deployment = company_authority
    claims = [(await ready_claim(deployment, f"large-judgment-{index}"))[1] for index in range(7)]
    async with running(deployment) as edge:
        _, manifest = await inspect_request(edge, {
            "binding_id": deployment.binding_id, "ref": "judgment",
        }, transport)
        arguments = {
            "kind": "claim_judgment", "binding_id": deployment.binding_id,
            "idempotency_key": "large-persisted-judgment", "admission_id": manifest["admission_id"],
            "manifest_digest": manifest["manifest_digest"],
            "claims": manifest["claims"], "sources": manifest["sources"],
            "relations": [
                {"left_id": left.id, "right_id": right.id, "relation": "supports",
                 "reason": f"Pair {index}: " + "Evidence remains scoped. " * 40 + '가😀"\\\n' * 25}
                for index, (left, right) in enumerate(list(combinations(claims, 2))[:16])
            ],
            "reason": "All sixteen comparisons retain their independent evidence. " * 24,
        }
        status, committed = await record_request(edge, arguments, transport)
        assert status == 200 and committed["effect"] == "committed", committed
        recovered = await reconstruct_stored_inspection(edge, deployment, committed["artifact_id"], transport)
        assert recovered["kind"] == "judgment" and recovered["state"] == "active"
        for field in ("manifest_digest", "claims", "sources", "relations", "reason"):
            assert recovered[field] == arguments[field]
        first = await bounded_inspection_plane(edge, deployment, {
            "binding_id": deployment.binding_id, "ref": committed["artifact_id"], "max_bytes": 256,
        }, transport)
        assert first["draft_window"]["byte_end"] <= 256
        await deployment.store.retract(deployment.actor, deployment.binding_id, claims[0].input_source_ids[0], "withdraw-judgment-input")
        for cursor in (0, first["draft_window"]["next_byte"]):
            hidden = await bounded_inspection_plane(edge, deployment, {
                "binding_id": deployment.binding_id, "ref": committed["artifact_id"], "byte_start": cursor,
            }, transport)
            assert "draft_window" not in hidden and hidden["reason"] is None and hidden["relations"] is None


async def persist_large_selection(deployment, edge, transport, *, snapshot=None):
    store, actor, binding = deployment.store, deployment.actor, deployment.binding_id
    for index in range(8):
        captured = await store.capture(actor, command(deployment, f"rejected-{index}", f"OldKey{index} is retained offline."))
        await store.record(actor, await source_selection(
            deployment, captured.source_id, f"discarded-{index}", label="discard",
        ))
    independent = await store.capture(actor, command(
        deployment, "independent-selection", "NewKey is retained offline.", snapshot=snapshot,
    ))
    _, admitted = await inspect_request(edge, {
        "binding_id": binding, "ref": independent.source_id, "snapshot": snapshot,
        "rejection_cursor": "history",
    }, transport)
    arguments = {
        "kind": "source_selection", "binding_id": binding, "source_id": independent.source_id,
        "idempotency_key": "large-persisted-selection",
        **{field: admitted[field] for field in (
            "admission_id", "source_revision", "binding_revision", "snapshot", "byte_start", "byte_end",
            "window_digest", "policy_revision", "policy_epoch",
        )},
        "label": "review", "coverage": "complete_window", "prior_rejection_ids": [], "rejection_review_ids": [],
        "reason": "Independent original evidence requires all comparison details. " * 24,
        "rejection_comparisons": [
            {"rejection_id": item["id"], "decision": "unrelated",
             "reason": f"Rejection {index}: " + "Independent evidence is not a repetition. " * 35 + '가😀"\\\n' * 30}
            for index, item in enumerate(admitted["judgment_context"]["rejections"])
        ],
    }
    status, committed = await record_request(edge, arguments, transport)
    assert status == 200 and committed["effect"] == "committed", committed
    return independent, committed["artifact_id"], arguments


@pytest.mark.parametrize("transport", ("modern", "legacy"))
async def test_large_persisted_selection_reconstructs_all_comparisons_and_provenance(company_authority, transport):
    deployment = company_authority
    async with running(deployment) as edge:
        source, ref, arguments = await persist_large_selection(deployment, edge, transport)
        recovered = await reconstruct_stored_inspection(edge, deployment, ref, transport)
        assert recovered["kind"] == "selection" and recovered["state"] == "active"
        for field in ("source_id", "source_revision", "reason", "rejection_comparisons",
                      "prior_rejection_ids", "rejection_review_ids", "window_digest"):
            assert recovered[field] == arguments[field]
        assert [item["source_id"] for item in recovered["source_provenance"]] == [source.source_id]
        assert recovered["claim_ids"] == []


@pytest.mark.parametrize("transport", ("modern", "legacy"))
@pytest.mark.parametrize("change", ("withdraw", "correct", "restore", "source_revision", "snapshot", "rejection_withdraw"))
async def test_selection_continuations_recheck_current_disclosure(company_authority, transport, change):
    deployment = company_authority
    store, actor, binding = deployment.store, deployment.actor, deployment.binding_id
    async with running(deployment) as edge:
        source, ref, arguments = await persist_large_selection(deployment, edge, transport, snapshot="scope-001" if change == "snapshot" else None)
        first = await bounded_inspection_plane(edge, deployment, {
            "binding_id": binding, "ref": ref, "snapshot": "scope-001" if change == "snapshot" else None,
        }, transport)
        cursor = first["draft_window"]["next_byte"]
        assert cursor is not None
        if change == "correct":
            await store.correct(actor, binding, source.source_id, command(deployment, "replacement-source", "ReplacementKey is retained offline."))
        elif change == "source_revision":
            async with store.pool.acquire() as connection:
                await connection.execute("UPDATE am_sources SET revision=revision+1 WHERE id=$1", source.source_id)
        elif change == "rejection_withdraw":
            await store.retract(actor, binding, arguments["rejection_comparisons"][0]["rejection_id"], "withdraw-compared-rejection")
        elif change in {"withdraw", "restore"}:
            old_head = store.journal.verify()["head"]
            outcome = await store.retract(actor, binding, source.source_id, "withdraw-selection-input")
            if change == "restore":
                async with store.pool.acquire() as connection:
                    await connection.execute("UPDATE am_sources SET state='active' WHERE id=$1", source.source_id)
                    await connection.execute("UPDATE am_source_selections SET state='active' WHERE id=$1", ref)
                    await connection.execute("DELETE FROM am_floors")
                    await connection.execute("UPDATE am_clock SET journal_head=$1", old_head)
                await store.reconcile_journal(outcome["head"])
        for start in (0, cursor):
            hidden = await bounded_inspection_plane(edge, deployment, {
                "binding_id": binding, "ref": ref, "byte_start": start,
                "snapshot": "other-scope" if change == "snapshot" else None,
            }, transport)
            assert set(hidden) == {"id", "kind", "epoch", "state", "source_id", "source_revision", "snapshot", "label"}
            assert hidden["id"] == ref


@pytest.mark.parametrize("transport", ("modern", "legacy"))
async def test_stored_inspection_ref_window_combinations_remain_refused(company_authority, transport):
    deployment = company_authority
    source, claim = await ready_claim(deployment, "window-validation")
    async with running(deployment) as edge:
        for ref, extra, code in (
            ("judgment", {"byte_start": 1}, "JUDGMENT_MANIFEST_INVALID"),
            ("judgment", {"max_bytes": 256}, "JUDGMENT_MANIFEST_INVALID"),
            ("judgment", {"rejection_cursor": "rejection-001"}, "INPUT_INVALID"),
            (source.id, {"byte_start": 1}, "SOURCE_WINDOW_INVALID"),
            (claim.selection_id, {"rejection_cursor": "rejection-001"}, "INPUT_INVALID"),
            (claim.selection_id, {"claim_ids": [claim.id]}, "INPUT_INVALID"),
            (claim.selection_id, {"byte_start": 9223372036854775807}, "CLAIM_WINDOW_INVALID"),
        ):
            inspected = await bounded_inspection_plane(edge, deployment, {
                "binding_id": deployment.binding_id, "ref": ref, **extra,
            }, transport)
            assert inspected["error"]["code"] == code and inspected["error"]["effect"] == "not_started"
            assert "draft_window" not in inspected


async def legacy_session_id(edge, token=AGENT_TOKEN):
    status, raw, headers = await request(edge, {
        "jsonrpc": "2.0", "id": "legacy-initialize", "method": "initialize",
        "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "session", "version": "1"}},
    }, token=token, protocol_version="2025-11-25", include_headers=True)
    assert status == 200 and "result" in json.loads(raw)
    return headers[b"mcp-session-id"]


async def session_request(edge, session, token=AGENT_TOKEN):
    status, raw = await request(edge, {"jsonrpc": "2.0", "id": 7, "method": "tools/list"},
        token=token, protocol_version="2025-11-25", extra_headers=((b"mcp-session-id", session),))
    return status, json.loads(raw)


async def test_lost_protocol_session_is_distinct_from_credential_mismatch(authority):
    async with running(authority) as edge:
        session = await legacy_session_id(edge)
        other = "wire-boundary-second-agent-credential-" + "s" * 32
        await authority.store.issue_token(authority.actor, Role.AGENT, (authority.binding_id,), other)
        status, body = await session_request(edge, session, other)
        assert (status, body["error"]["code"], body["error"]["effect"]) == (403, "SESSION_CREDENTIAL_DENIED", "not_started")
        status, body = await session_request(edge, b"unknown-session")
        assert (status, body["error"]["code"], body["error"]["effect"]) == (404, "SESSION_NOT_FOUND", "not_started")
        status, body = await session_request(edge, session)
        assert status == 200 and "tools" in body["result"]


async def test_sdk_reaped_session_is_reported_as_not_found_and_forgotten(authority):
    async with running(authority) as edge:
        session = await legacy_session_id(edge)
        credential_id = edge.sessions[session.decode()][0]
        edge.sessions["sdk-reaped-session"] = (credential_id, time.monotonic())
        status, body = await session_request(edge, b"sdk-reaped-session")
        assert (status, body["error"]["code"], body["error"]["effect"]) == (404, "SESSION_NOT_FOUND", "not_started")
        assert "sdk-reaped-session" not in edge.sessions
        assert (await authority.store.stats(authority.actor, authority.binding_id))["active_sources"] == 0


async def test_request_concurrency_cap_refuses_before_authentication_or_handler(authority):
    await authority.store.issue_token(authority.actor, Role.AGENT, (authority.binding_id,), AGENT_TOKEN)
    settings = Settings.model_validate({**authority.store.settings.model_dump(), "max_concurrent_requests": 1})
    entered, release, calls = asyncio.Event(), asyncio.Event(), []

    async def downstream(scope, receive, send):
        calls.append(scope["path"])
        entered.set()
        await release.wait()
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}).encode()
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": body, "more_body": False})

    application = Application(settings, authority.store)
    edge = SecurityEdge(downstream, application, settings)
    held = asyncio.create_task(request(edge, tool({"query": "held"})))
    await asyncio.wait_for(entered.wait(), 5)
    status, body = await request(edge, tool({"query": "refused"}), token="not-even-authenticated-" + "x" * 32)
    assert (status, json.loads(body)["error"]["code"], json.loads(body)["error"]["effect"]) == (503, "SERVICE_BUSY", "not_started")
    release.set()
    assert (await held)[0] == 200
    assert (await request(edge, tool({"query": "after"})))[0] == 200
    assert calls == ["/mcp", "/mcp"]
    assert application.inflight == 0


async def test_legacy_stream_is_capped_while_opening_and_released_once_idle(authority):
    await authority.store.issue_token(authority.actor, Role.AGENT, (authority.binding_id,), AGENT_TOKEN)
    settings = Settings.model_validate({**authority.store.settings.model_dump(), "max_concurrent_requests": 1})
    opening, opened, streaming, release = asyncio.Event(), asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def downstream(scope, receive, send):
        if scope["method"] == "GET":
            opening.set()
            await opened.wait()
            await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/event-stream")]})
            streaming.set()
            await release.wait()
            await send({"type": "http.response.body", "body": b"", "more_body": False})
            return
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}).encode(), "more_body": False})

    edge = SecurityEdge(downstream, Application(settings, authority.store), settings)
    stream = asyncio.create_task(request(edge, b"", method="GET"))
    await asyncio.wait_for(opening.wait(), 5)
    status, body = await request(edge, tool({"query": "while opening"}))
    assert (status, json.loads(body)["error"]["code"]) == (503, "SERVICE_BUSY")
    opened.set()
    await asyncio.wait_for(streaming.wait(), 5)
    assert (await request(edge, tool({"query": "while streaming"})))[0] == 200
    release.set()
    assert (await stream)[0] == 200
    assert edge.active == 0


async def test_readyz_roundtrips_database_and_refuses_dispatch_on_authority_outage(authority, monkeypatch):
    async with running(authority) as edge:
        status, body = await request(edge, b"", token=None, path="/readyz", method="GET")
        ready = json.loads(body)
        assert status == 200 and ready["ready"] is True and ready["db_ready"] is True
        assert ready["deployment_id"] == authority.store.settings.deployment_id
        assert ready["realm"] == authority.store.settings.realm
        assert set(ready) == {"ready", "db_ready", "deployment_id", "realm", "accepting"}
        status, body = await request(edge, b"", path="/readyz", method="GET")
        assert status == 403
        assert "judge_worker" not in json.loads(body) and "cleanup_scheduler" not in json.loads(body)
        status, body = await request(edge, b"", token=TOKEN, path="/readyz", method="GET")
        assert status == 200 and "judge_worker" in json.loads(body)

        @asynccontextmanager
        async def disconnected(*args, **kwargs):
            raise OSError("private database outage diagnostic")
            yield

        monkeypatch.setattr(edge.application.store, "_tx", disconnected)
        status, body = await request(edge, b"", token=None, path="/readyz", method="GET")
        ready = json.loads(body)
        assert status == 503 and ready["ready"] is False and ready["db_ready"] is False
        status, body = await request(edge, tool({"binding_id": authority.binding_id, "query": "required facts"}))
        error = json.loads(body)["error"]
        assert status == 503 and error["code"] == "SERVICE_UNAVAILABLE"
        assert error["effect"] == "not_started" and "private" not in body.decode()


@pytest.mark.parametrize("behavior", ["stalled", "slow_drip"])
async def test_complete_post_deadline_releases_capacity_without_capturing_partial_memory(authority, monkeypatch, behavior):
    monkeypatch.setattr(edge_module, "HTTP_BODY_SECONDS", 0.05)
    raw = command(authority).model_dump_json().encode()
    entered = asyncio.Event()
    stalled = asyncio.Event()
    offset = 0

    async def receive():
        nonlocal offset
        entered.set()
        if behavior == "stalled":
            await stalled.wait()
        else:
            await asyncio.sleep(0.01)
        chunk = raw[offset:offset + 1]
        offset += 1
        return {"type": "http.request", "body": chunk, "more_body": offset < len(raw)}

    producer_token = "upload-boundary-producer-" + "u" * 32
    async with running(authority) as edge:
        await authority.store.issue_token(authority.actor, Role.PRODUCER, (authority.binding_id,), producer_token)
        edge.settings = edge.settings.model_copy(update={"max_concurrent_requests": 1})
        held = asyncio.create_task(request(edge, raw, producer_token, path="/api/capture", body_receive=receive, include_headers=True))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            status, body = await request(edge, raw, producer_token, path="/api/capture")
            assert (status, json.loads(body)["error"]["code"], json.loads(body)["error"]["effect"]) == (
                503, "SERVICE_BUSY", "not_started",
            )
            status, body, headers = await asyncio.wait_for(held, 2)
            assert (status, json.loads(body)["error"]["code"], json.loads(body)["error"]["effect"]) == (
                408, "REQUEST_BODY_TIMEOUT", "not_started",
            )
            assert headers[b"connection"] == b"close"
            async with authority.store.pool.acquire() as connection:
                assert await connection.fetchval("SELECT count(*) FROM am_sources") == 0
            status, body = await request(edge, raw, producer_token, path="/api/capture")
            assert status == 202
            source_id = json.loads(body)["source_id"]
            async with authority.store.pool.acquire() as connection:
                assert await connection.fetchval("SELECT id FROM am_sources") == source_id
        finally:
            if not held.done():
                held.cancel()
            await asyncio.gather(held, return_exceptions=True)


async def test_authenticated_readiness_preserves_the_committed_jev_replacement_fence(authority):
    settings = authority.store.settings
    settings.state_dir.mkdir(mode=0o700, exist_ok=True)
    worker = await authority.store.issue_token(
        authority.actor, Role.AGENT, (authority.binding_id,), "fenced-readiness-worker-" + "z" * 32,
    )
    state = edge_module.load_state(settings).model_copy(update={
        "provider": "jev", "revision": 1, "model": "synthetic-model",
        "key_fingerprint": "hmac-sha256:" + "a" * 12,
        "credential_id": worker.credential_id,
        "retiring_credential_ids": (worker.credential_id,),
    })
    directory = settings.state_dir / "judge"
    directory.mkdir(parents=True, mode=0o700)
    for name, value in (
        ("provider.json", state.model_dump_json()),
        ("egress-policy.json", json.dumps({"format": 1, "jev_allowed": True, "revision": 1})),
    ):
        path = directory / name
        path.write_text(value)
        path.chmod(0o600)
    async with running(authority) as edge:
        status, body = await request(edge, b"", token=TOKEN, path="/readyz", method="GET")
    ready = json.loads(body)
    assert status == 200 and ready["db_ready"] is True
    assert ready["judgment"] == "jev_unavailable_explicit_reselection_required"
    assert ready["server_inference"] == "unavailable"
