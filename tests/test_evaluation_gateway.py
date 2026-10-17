from __future__ import annotations

import asyncio
import hashlib
import json
import os
import socket
import threading
from contextlib import asynccontextmanager
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import anyio
import pytest
import uvicorn
from test_edge_boundaries import META, request
from test_store_authority import authority as authority

from agents_memory import evaluation_gateway as gateway_module
from agents_memory.domain import DomainError, Role, RuleApproval, RuleProposal, RuleScope
from agents_memory.edge import create_app
from agents_memory.evaluation_gateway import (
    EvaluationGateway,
    GatewayScope,
    GatewayUpstream,
    _ObservedRelay,
)
from agents_memory.stdio import RelayEndpoint

AGENT = "engineering-gateway-agent-" + "a" * 32
PRODUCER = "engineering-gateway-producer-" + "p" * 32


@asynccontextmanager
async def actual_upstream(authority, tmp_path):
    await authority.store.issue_token(authority.actor, Role.AGENT, (authority.binding_id,), AGENT)
    await authority.store.issue_token(authority.actor, Role.PRODUCER, (authority.binding_id,), PRODUCER)
    agent_file, producer_file = tmp_path / "agent-token", tmp_path / "producer-token"
    for path, token in ((agent_file, AGENT), (producer_file, PRODUCER)):
        path.write_text(token)
        path.chmod(0o600)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    settings = authority.store.settings.model_copy(update={"port": listener.getsockname()[1]})
    server = uvicorn.Server(uvicorn.Config(create_app(settings), access_log=False, log_level="critical"))
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                if serving.done():
                    await serving
                    raise AssertionError("Actual upstream failed before startup")
                await asyncio.sleep(0.01)
        endpoint = RelayEndpoint(settings.base_url, state_dir=settings.state_dir, deployment_id=settings.deployment_id)
        yield (
            GatewayUpstream(endpoint, agent_file, "agent", authority.binding_id, "engineering-approved-agent-route"),
            GatewayUpstream(endpoint, producer_file, "producer", authority.binding_id, "engineering-approved-producer-route"),
        )
    finally:
        server.should_exit = True
        await asyncio.wait_for(serving, 10)
        listener.close()


def scope_for(upstream, *, mode="memory_on", phase="preflight", approved_refs=()):
    return GatewayScope(
        invocation_id="engineering-invocation", route_ref="engineering-approved-route", mode=mode,
        phase=phase, binding_id=upstream.binding_id,
        approved_upstream_urls=(upstream.endpoint.base_url,), approved_refs=approved_refs,
        protocol_version="2025-11-25", max_calls=100, max_trace_bytes=4 * 1024 * 1024,
        required_request={"binding_id": upstream.binding_id, "query": "CacheKey offline", "max_bytes": 6144, "limit": 3},
    )


def payload(result):
    assert not result.get("isError", False), result
    return json.loads(result["content"][0]["text"])


async def call(gateway, name, arguments):
    return payload(await asyncio.to_thread(gateway.call_tool, name, arguments))


async def add_required_rule(authority):
    proposal = await authority.store.propose_rule(authority.actor, RuleProposal(
        binding_id=authority.binding_id, idempotency_key="engineering-required-proposal",
        body="Keep synthetic credentials offline.", required=True,
    ))
    return await authority.store.approve_rule(authority.actor, RuleApproval(
        proposal_id=proposal["proposal_id"], expected_digest=proposal["digest"], scope=RuleScope.LOCAL_PROJECT,
        target_bindings=(authority.binding_id,), target_set_revision=proposal["target_set_revision"],
        idempotency_key="engineering-required-approval",
    ))


async def full_inspect(gateway, ref):
    start = 0
    collected = bytearray()
    digest = None
    while True:
        value = await call(gateway, "memory_inspect", {"ref": ref, "byte_start": start, "max_bytes": 4096})
        window = value.get("draft_window")
        if window is None:
            return value
        assert window["byte_start"] == len(collected)
        digest = digest or window["digest"]
        assert window["digest"] == digest
        collected.extend(window["body"].encode())
        start = window["next_byte"]
        if start is None:
            assert hashlib.sha256(collected).hexdigest() == digest
            return json.loads(collected)


async def prepare_through_actual_wire(gateway, *, inspect_claims=True, second_claim=False):
    body = "CacheKey is retained only offline."
    if second_claim:
        body += "\nQueueLease expires after release."
    captured = await asyncio.to_thread(gateway.capture, {
        "binding_id": gateway.scope.binding_id, "idempotency_key": "engineering-wire-capture",
        "origin_key": "engineering-frozen-source-one", "body": body, "speaker": "document",
    })
    source = captured["source_pointer"]["source_id"]
    window = await call(gateway, "memory_inspect", {"ref": source})
    span = window["span_inventory"][0]
    claims = [{
        "assertion_id": "a0000", "assertion_span_id": span["span_id"], "statement": span["quote"],
        "kind": "fact", "subject": "CacheKey", "predicate": "retained", "object": "offline",
        "polarity": "positive", "modality": "asserted", "entities": ["CacheKey"],
    }]
    used_spans = {span["span_id"]}
    if second_claim:
        other = next(item for item in window["span_inventory"] if item["quote"].startswith("QueueLease"))
        used_spans.add(other["span_id"])
        claims.append({
            "assertion_id": "a0001", "assertion_span_id": other["span_id"], "statement": other["quote"],
            "kind": "fact", "subject": "QueueLease", "predicate": "expires", "object": "release",
            "polarity": "positive", "modality": "asserted", "entities": ["QueueLease"],
        })
    # A controlled engineering peer authors this judgment; this is not live-native semantic proof.
    selection = await call(gateway, "memory_record", {
        "kind": "source_selection", "idempotency_key": "engineering-wire-selection",
        "admission_id": window["admission_id"], "source_id": source,
        "source_revision": window["source_revision"], "binding_revision": window["binding_revision"],
        "byte_start": window["byte_start"], "byte_end": window["byte_end"], "window_digest": window["window_digest"],
        "policy_revision": window["policy_revision"], "policy_epoch": window["policy_epoch"],
        "label": "remember", "coverage": "complete_window", "reason": "Engineering peer checked exact original spans.",
        "extraction": {"claims": claims,
            "individual_qualifications": [{"assertion_id": "a0000", "kind": "condition", "phrase": "only offline", "evidence_span_id": span["span_id"]}],
            "shared_qualifications": [], "validities": [],
            "unused_span_ids": [item["span_id"] for item in window["span_inventory"] if item["span_id"] not in used_spans]},
    })
    inspected = await full_inspect(gateway, selection["artifact_id"])
    if inspect_claims:
        for claim in inspected["claim_ids"]:
            await full_inspect(gateway, claim)
    return captured, inspected["claim_ids"]


async def test_actual_producer_http_mcp_judgment_and_final_read_remain_distinct_from_native_proof(authority, tmp_path):
    await add_required_rule(authority)
    async with actual_upstream(authority, tmp_path) as (agent, producer):
        traces = []
        gateway = EvaluationGateway(scope_for(agent), agent=agent, producer=producer, trace_sink=traces.append)
        required = await call(gateway, "memory_required_context", gateway.required_request)
        assert "Keep synthetic credentials offline." in required["context"]
        captured, claims = await prepare_through_actual_wire(gateway)
        recall = {"query": "CacheKey offline", "max_bytes": 6144, "limit": 3}
        candidates = await call(gateway, "memory_context", recall)
        assert {item["claim_id"] for item in candidates["candidate_manifest"]} == set(claims)
        for item in candidates["candidate_manifest"]:
            await full_inspect(gateway, item["inspection_ref"])
        final = await call(gateway, "memory_context", {
            **recall, "admission_id": candidates["admission_id"],
            "relevance": [{"claim_id": item["claim_id"], "relevant": True, "reason": "Controlled peer selected the complete qualified evidence."}
                          for item in candidates["candidate_manifest"]],
        })
        assert final["judgment_required"] is False
        assert "only offline" in final["context"]
        observation = gateway.flow_observation()
        assert observation["pipeline_observed"]
        assert observation["semantic_correctness"] is None
        assert observation["provider_consumption"] is None
        exchanges = [row["exchange"] for row in traces if row["stage"] == "gateway_wire"]
        captures = [item for item in exchanges if item.path == "/api/capture" and item.stage == "response"]
        assert len(captures) == 1 and captures[0].http_status == 202
        assert captured["source_id"] == json.loads(captures[0].response_body)["source_id"]
        assert any(item.path == "/mcp" and item.http_status == 200 for item in exchanges)
        assert all(item.observed_ns >= item.started_ns for item in exchanges)
        gateway.close()


@pytest.mark.parametrize("mode", ["off", "required_only"])
async def test_off_is_server_enforced_and_required_rules_match_on(authority, tmp_path, mode):
    await add_required_rule(authority)
    async with actual_upstream(authority, tmp_path) as (agent, producer):
        off_traces, on_traces = [], []
        off = EvaluationGateway(scope_for(agent, mode=mode), agent=agent, producer=producer, trace_sink=off_traces.append)
        on = EvaluationGateway(scope_for(agent), agent=agent, producer=producer, trace_sink=on_traces.append)
        off_rules = await call(off, "memory_required_context", off.required_request)
        on_rules = await call(on, "memory_required_context", on.required_request)
        assert off_rules["stamp"]["rules"] == on_rules["stamp"]["rules"]
        assert off_rules["context"] == on_rules["context"]
        for name in ("memory_inspect", "memory_context", "memory_record", "memory_feedback", "memory_catalog", "memory_history", "memory_preview"):
            with pytest.raises(DomainError, match="does not authorize") as caught:
                await asyncio.to_thread(off.call_tool, name, {"ref": "anything"})
            assert caught.value.code == "OPTIONAL_TOOL_DENIED"
        with pytest.raises(DomainError) as caught:
            await asyncio.to_thread(off.capture, {})
        assert caught.value.code == "OPTIONAL_CAPTURE_DENIED"
        assert {row["exchange"].path for row in off_traces if row["stage"] == "gateway_wire"} == {"/api/required-context"}
        assert not off.flow_observation()["pipeline_observed"]
        # Exercise the official MCP SDK dispatcher, not just the Python tool method.
        app = off.server.streamable_http_app(json_response=True, stateless_http=True, max_request_body_size=65536)
        async with app.router.lifespan_context(app):
            status, raw = await request(app, {"jsonrpc":"2.0", "id":1, "method":"tools/list", "params":{"_meta":META}}, token=None)
            assert status == 200
            assert [tool["name"] for tool in json.loads(raw)["result"]["tools"]] == ["memory_required_context"]
            status, raw = await request(app, {"jsonrpc":"2.0", "id":2, "method":"tools/call", "params":{
                "name":"memory_inspect", "arguments":{"ref":"private-source"}, "_meta":META}}, token=None)
            assert status == 200
            assert json.loads(raw)["result"]["isError"] is True
            status, raw = await request(app, {"jsonrpc":"2.0", "id":3, "method":"resources/list", "params":{"_meta":META}}, token=None)
            assert "private-source" not in raw.decode()
            assert not json.loads(raw).get("result", {}).get("resources")


async def test_frozen_coding_cannot_capture_record_or_inspect_catalog(authority, tmp_path):
    async with actual_upstream(authority, tmp_path) as (agent, producer):
        traces = []
        gateway = EvaluationGateway(scope_for(agent, phase="coding"), agent=agent, producer=producer, trace_sink=traces.append)
        await call(gateway, "memory_required_context", gateway.required_request)
        with pytest.raises(DomainError) as caught:
            await asyncio.to_thread(gateway.capture, {})
        assert caught.value.code == "OPTIONAL_CAPTURE_DENIED"
        for ref in ("catalog", "history", "health", "judge", "pending"):
            with pytest.raises(DomainError) as caught:
                await asyncio.to_thread(gateway.call_tool, "memory_inspect", {"ref":ref})
            assert caught.value.code == "INSPECTION_SCOPE_DENIED"
        with pytest.raises(DomainError) as caught:
            await asyncio.to_thread(gateway.call_tool, "memory_record", {
                "kind":"note", "body":"Do not mutate a paired task corpus", "idempotency_key":"coding-mutation",
            })
        assert caught.value.code == "FROZEN_CORPUS_MUTATION_DENIED"
        assert {row["exchange"].path for row in traces if row["stage"] == "gateway_wire"} == {"/api/required-context"}


def test_unapproved_endpoint_role_and_credential_alias_are_rejected(tmp_path):
    endpoint = RelayEndpoint("http://127.0.0.1:8768")
    agent = GatewayUpstream(endpoint, tmp_path / "agent", "agent", "binding", "approved")
    scope = scope_for(agent)
    for bad in (replace(agent, role="operator"), replace(agent, approval_ref=""), replace(agent, binding_id="other")):
        with pytest.raises(ValueError, match="not approved"):
            EvaluationGateway(scope, agent=bad, producer=None, trace_sink=lambda _: None)
    with pytest.raises(ValueError, match="not approved"):
        EvaluationGateway(replace(scope, approved_upstream_urls=()), agent=agent, producer=None, trace_sink=lambda _: None)
    producer = replace(agent, role="producer")
    with pytest.raises(ValueError, match="distinct"):
        EvaluationGateway(scope, agent=agent, producer=producer, trace_sink=lambda _: None)


def test_stored_inspection_continuation_does_not_prematurely_claim_full_read(tmp_path):
    agent = GatewayUpstream(RelayEndpoint("http://127.0.0.1:8768"), tmp_path / "agent", "agent", "binding", "approved")
    gateway = EvaluationGateway(scope_for(agent, approved_refs=("claim-one",)), agent=agent, producer=None, trace_sink=lambda _: None)
    raw = json.dumps({"id":"claim-one", "claim_ids":["claim-two"]}).encode()
    digest = hashlib.sha256(raw).hexdigest()
    cut = len(raw) // 2
    for start, end in ((0, cut), (cut, len(raw))):
        gateway._observe_flow("memory_inspect", {"ref":"claim-one"}, {"draft_window": {
            "body":raw[start:end].decode(), "byte_start":start, "byte_end":end, "total_bytes":len(raw),
            "digest":digest, "next_byte":end if end < len(raw) else None,
        }})
        assert ("claim-one" in gateway._inspected_claims) == (end == len(raw))
    assert "claim-two" in gateway._allowed_refs


@pytest.fixture
def fault_upstream(tmp_path, monkeypatch):
    state = {"mode": "session_loss", "tools": 0, "initializations": 0}
    class Handler(BaseHTTPRequestHandler):
        def answer(self, status, raw, *, session=False):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            if session:
                self.send_header("Mcp-Session-Id", f"session-{state['initializations']}")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            self.answer(200, json.dumps({"ready": True, "db_ready": True, "deployment_id": "engineering-peer"}).encode())

        def do_POST(self):
            message = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if message["method"] == "initialize":
                state["initializations"] += 1
                self.answer(200, json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": {
                    "protocolVersion": "2025-11-25", "capabilities": {}, "serverInfo": {"name": "engineering-peer", "version": "1"},
                }}).encode(), session=True)
            elif message["method"] == "notifications/initialized":
                self.answer(202, b"")
            else:
                state["tools"] += 1
                if state["mode"] == "session_loss" and state["tools"] == 1:
                    self.answer(404, json.dumps({"error": {
                        "code": "SESSION_NOT_FOUND", "message": "Engineering definite-no-start session loss", "effect": "not_started",
                    }}).encode())
                elif state["mode"] == "unknown_commit":
                    self.close_connection = True
                elif state["mode"] == "malformed":
                    self.answer(200, b"{malformed")
                else:
                    self.answer(200, json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": {
                        "content": [{"type": "text", "text": "{\"effect\":\"committed\"}"}],
                    }}).encode())

        def log_message(self, *args):
            pass

    monkeypatch.setattr("agents_memory.service.ensure_started", lambda *args, **kwargs: None)
    token = tmp_path / "fault-peer-token"
    token.write_text("engineering-only-peer-token")
    token.chmod(0o600)
    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            yield GatewayUpstream(RelayEndpoint(f"http://127.0.0.1:{server.server_port}"), token, "agent", "binding", "engineering-peer"), state
        finally:
            server.shutdown()
            worker.join(timeout=5)
            assert not worker.is_alive()


def initialized_relay(upstream, observations):
    relay = _ObservedRelay(upstream, observations.append)
    initialized = relay.forward({"jsonrpc": "2.0", "id": "init", "method": "initialize", "params": {
        "protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "engineering-peer", "version": "1"},
    }})
    assert "result" in initialized
    relay.forward({"jsonrpc": "2.0", "method": "notifications/initialized"})
    return relay


def test_actual_http_replays_only_proven_not_started_session_loss(fault_upstream):
    upstream, state = fault_upstream
    observations = []
    relay = initialized_relay(upstream, observations)
    result = relay.forward({"jsonrpc": "2.0", "id": "business-call", "method": "tools/call", "params": {
        "name": "memory_record", "arguments": {"kind": "source_selection"},
    }})
    assert "result" in result
    assert state["tools"] == 2 and state["initializations"] == 2
    replies = [item for item in observations if item.stage == "response"]
    assert any(item.http_status == 404 and b"not_started" in item.response_body for item in replies)
    requests = [json.loads(item.request_body) for item in observations if item.stage == "prepared"]
    business = [item for item in requests if item.get("id") == "business-call"]
    assert business[0] == business[1]
    assert any(item.get("id") == "agents-memory-relay-reinitialize" for item in requests)


@pytest.mark.parametrize("mode", ["unknown_commit", "malformed"])
def test_actual_http_unknown_or_malformed_write_is_never_retried(fault_upstream, mode):
    upstream, state = fault_upstream
    state["mode"] = mode
    observations = []
    relay = initialized_relay(upstream, observations)
    result = relay.forward({"jsonrpc": "2.0", "id": "business-call", "method": "tools/call", "params": {
        "name": "memory_record", "arguments": {"kind": "source_selection"},
    }})
    assert result["error"]["data"]["effect"] == "unknown"
    assert state["tools"] == 1 and state["initializations"] == 1
    if mode == "malformed":
        assert any(item.response_body == b"{malformed" for item in observations)
    else:
        assert any(item.stage == "failure" for item in observations)


async def test_failed_final_observation_cannot_publish_pipeline_success(authority, tmp_path):
    async with actual_upstream(authority, tmp_path) as (agent, producer):
        traces = []
        armed = False
        failed = []
        def observe(row):
            if armed and row["stage"] == "gateway_flow" and row.get("name") == "memory_context":
                failed.append(row["stage"])
                raise OSError("Synthetic final-context observer failure")
            traces.append(row)
        gateway = EvaluationGateway(scope_for(agent), agent=agent, producer=producer, trace_sink=observe)
        await call(gateway, "memory_required_context", gateway.required_request)
        captured, claims = await prepare_through_actual_wire(gateway)
        recall = {"query": "CacheKey offline", "max_bytes": 6144, "limit": 3}
        candidates = await call(gateway, "memory_context", recall)
        assert {item["claim_id"] for item in candidates["candidate_manifest"]} == set(claims)
        for item in candidates["candidate_manifest"]:
            await full_inspect(gateway, item["inspection_ref"])
        arguments = {
            **recall, "admission_id": candidates["admission_id"],
            "relevance": [{"claim_id": item["claim_id"], "relevant": True, "reason": "Controlled complete inspection."}
                          for item in candidates["candidate_manifest"]],
        }
        app = gateway.server.streamable_http_app(json_response=True, stateless_http=True, max_request_body_size=65536)
        armed = True
        async with app.router.lifespan_context(app):
            status, raw = await request(app, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
                "name": "memory_context", "arguments": arguments, "_meta": META,
            }}, token=None)
        armed = False
        assert status == 200
        failure = json.loads(raw)["result"]
        assert failure["isError"] is True
        assert json.loads(failure["content"][0]["text"])["error"] == {
            "code": "GATEWAY_FAILURE_RECONCILE", "effect": "unknown",
        }
        assert failed == ["gateway_flow"]
        observation = gateway.flow_observation()
        assert observation["pipeline_observed"] is False
        assert observation["final_read_observed"] is False
        assert observation["final_reads"] == ()
        assert observation["captures"] == (captured,)
        assert observation["remembered_selections"]
        exchanges = [row["exchange"] for row in traces if row["stage"] == "gateway_wire"]
        final_responses = [
            exchange for exchange in exchanges if exchange.stage == "response" and exchange.path == "/mcp"
            and json.loads(exchange.request_body).get("params", {}).get("arguments", {}).get("admission_id")
            == candidates["admission_id"]
        ]
        assert len(final_responses) == 1
        upstream = payload(json.loads(final_responses[0].response_body)["result"])
        assert upstream["judgment_required"] is False
        assert set(claims) <= set(upstream["refs"])
        assert "only offline" in upstream["context"]
        await full_inspect(gateway, claims[0])
        assert gateway.flow_observation()["pipeline_observed"] is False
        gateway.close()


async def test_pipeline_requires_complete_inspection_of_every_remembered_claim(authority, tmp_path):
    async with actual_upstream(authority, tmp_path) as (agent, producer):
        gateway = EvaluationGateway(scope_for(agent), agent=agent, producer=producer, trace_sink=lambda _: None)
        await call(gateway, "memory_required_context", gateway.required_request)
        captured, claims = await prepare_through_actual_wire(gateway, inspect_claims=False, second_claim=True)
        assert len(claims) == 2
        recall = {"query": "CacheKey offline", "max_bytes": 6144, "limit": 3}
        candidates = await call(gateway, "memory_context", recall)
        manifest = candidates["candidate_manifest"]
        assert len(manifest) == 1
        selected = manifest[0]["claim_id"]
        assert selected in claims
        await full_inspect(gateway, manifest[0]["inspection_ref"])
        final = await call(gateway, "memory_context", {
            **recall, "admission_id": candidates["admission_id"],
            "relevance": [{"claim_id": selected, "relevant": True, "reason": "Only CacheKey matches this query."}],
        })
        assert final["judgment_required"] is False
        assert selected in final["refs"]
        observation = gateway.flow_observation()
        assert observation["final_read_observed"] is True
        assert observation["pipeline_observed"] is False
        remaining = next(claim for claim in claims if claim != selected)
        await full_inspect(gateway, remaining)
        observation = gateway.flow_observation()
        assert observation["pipeline_observed"] is True
        assert observation["linked_capture_source_ids"] == (captured["source_id"],)
        gateway.close()


async def test_unwritten_downstream_final_result_cannot_publish_delivery(authority, tmp_path):
    async with actual_upstream(authority, tmp_path) as (agent, producer):
        traces = []
        gateway = EvaluationGateway(scope_for(agent), agent=agent, producer=producer, trace_sink=traces.append)
        await call(gateway, "memory_required_context", gateway.required_request)
        captured, claims = await prepare_through_actual_wire(gateway)
        recall = {"query": "CacheKey offline", "max_bytes": 6144, "limit": 3}
        candidates = await call(gateway, "memory_context", recall)
        for item in candidates["candidate_manifest"]:
            await full_inspect(gateway, item["inspection_ref"])
        result = await asyncio.to_thread(gateway.call_tool, "memory_context", {
            **recall, "admission_id": candidates["admission_id"],
            "relevance": [{"claim_id": item["claim_id"], "relevant": True,
                           "reason": "Engineering fixture inspected the original evidence."}
                          for item in candidates["candidate_manifest"]],
        }, downstream_request_id="unwritten-final-response")
        final = payload(result)
        assert final["judgment_required"] is False
        assert set(claims) <= set(final["refs"])
        assert "only offline" in final["context"]
        gateway.close()
        observed = gateway.flow_observation()
        assert observed["final_read_attempts"]
        assert observed["captures"] == (captured,)
        assert observed["final_reads"] == ()
        assert observed["observation_complete"] is False
        assert observed["pipeline_observed"] is False


@asynccontextmanager
async def real_stdio_pipe(gateway, monkeypatch, variant, final_id):
    input_read, input_write = os.pipe()
    output_read, output_write = os.pipe()
    stdin = os.fdopen(input_read, "rb", buffering=0)
    stdout = os.fdopen(output_write, "wb", buffering=0)
    os.set_blocking(input_write, False)
    os.set_blocking(output_read, False)
    state = SimpleNamespace(input_fd=input_write, output_fd=output_read, pending=bytearray(),
                            transport=None, failure=None, last_raw=None)
    original_transport = gateway_module._BoundedStdio
    class PipeTransport(original_transport):
        def __init__(self, *args):
            super().__init__(*args)
            state.transport = self
        async def write(self, text):
            message = json.loads(text)
            if variant == "mismatch" and message.get("id") == final_id:
                message["result"] = {"isError": True, "content": [{
                    "type": "text", "text": json.dumps({"error": {"code": "SYNTHETIC_SERIALIZER_REPLACEMENT"}}),
                }]}
                text = json.dumps(message, ensure_ascii=False) + "\n"
            await super().write(text)
    async def send(message):
        view = memoryview(json.dumps(message, ensure_ascii=False).encode() + b"\n")
        while view:
            await anyio.wait_writable(state.input_fd)
            try:
                count = os.write(state.input_fd, view)
            except BlockingIOError:
                continue
            assert count > 0
            view = view[count:]
    async def receive():
        async with asyncio.timeout(5):
            while b"\n" not in state.pending:
                await anyio.wait_readable(state.output_fd)
                try:
                    chunk = os.read(state.output_fd, 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    raise EOFError("Owned gateway pipe closed before its response")
                state.pending.extend(chunk)
            line, _, rest = state.pending.partition(b"\n")
            state.pending[:] = rest
            state.last_raw = bytes(line) + b"\n"
            return json.loads(line)
    def close_input():
        if state.input_fd is not None:
            os.close(state.input_fd)
            state.input_fd = None
    def close_output():
        if state.output_fd is not None:
            os.close(state.output_fd)
            state.output_fd = None
    state.send, state.receive = send, receive
    state.close_input, state.close_output = close_input, close_output
    with monkeypatch.context() as patches:
        patches.setattr(gateway_module, "sys", SimpleNamespace(stdin=stdin, stdout=stdout))
        patches.setattr(gateway_module, "_BoundedStdio", PipeTransport)
        state.runner = asyncio.create_task(gateway.run_stdio(timeout_seconds=5.0))
        try:
            yield state
        finally:
            close_input()
            try:
                await asyncio.wait_for(asyncio.shield(state.runner), 10)
            except BaseException as error:
                if not state.runner.done():
                    state.runner.cancel()
                    await asyncio.gather(state.runner, return_exceptions=True)
                    raise AssertionError("Owned stdio session exceeded its cleanup bound") from error
                state.failure = error
            finally:
                close_output()
                stdin.close()
                stdout.close()


@pytest.mark.parametrize("variant", [
    "complete", "output_limit", "broken_pipe", "cancel", "timeout",
    "mismatch", "duplicate_id", "delivery_observer_failure",
])
async def test_real_stdio_write_is_only_final_delivery_boundary(authority, tmp_path, monkeypatch, variant):
    loop = asyncio.get_running_loop()
    ready, release, worker_done = threading.Event(), threading.Event(), threading.Event()
    failed_write, cancelled = asyncio.Event(), asyncio.Event()
    traces = []
    final_id = "7" if variant == "duplicate_id" else 'final-"한국어'
    def observe(row):
        traces.append(row)
        if row["stage"] in {"gateway_stdio_output_limit", "gateway_stdio_write_failed"}:
            loop.call_soon_threadsafe(failed_write.set)
        if (row["stage"] == "gateway_stdio_received"
                and json.loads(row["body"]).get("method") == "notifications/cancelled"):
            loop.call_soon_threadsafe(cancelled.set)
        if (row["stage"] == "gateway_dispatched" and row.get("downstream_request_id") == final_id
                and row.get("name") == "memory_context"):
            ready.set()
            assert release.wait(15), "Owned final-response barrier was not released"
        if (variant == "delivery_observer_failure" and row["stage"] == "gateway_delivery"
                and row.get("channel") == "stdio" and row.get("name") == "memory_context"):
            raise OSError("Synthetic completed-write receipt observer failure")
    async with actual_upstream(authority, tmp_path) as (agent, producer):
        gateway = EvaluationGateway(scope_for(agent), agent=agent, producer=producer, trace_sink=observe)
        await call(gateway, "memory_required_context", gateway.required_request)
        captured, claims = await prepare_through_actual_wire(gateway)
        recall = {"query": "CacheKey offline", "max_bytes": 6144, "limit": 3}
        candidates = await call(gateway, "memory_context", recall)
        for item in candidates["candidate_manifest"]:
            await full_inspect(gateway, item["inspection_ref"])
        arguments = {
            **recall, "admission_id": candidates["admission_id"],
            "relevance": [{"claim_id": item["claim_id"], "relevant": True,
                           "reason": "Engineering transport fixture inspected complete evidence."}
                          for item in candidates["candidate_manifest"]],
        }
        original_leave = gateway._leave
        def leave():
            original_leave()
            if ready.is_set():
                worker_done.set()
        monkeypatch.setattr(gateway, "_leave", leave)
        async with real_stdio_pipe(gateway, monkeypatch, variant, final_id) as pipe:
            try:
                await pipe.send({"jsonrpc": "2.0", "id": "init", "method": "initialize", "params": {
                    "protocolVersion": "2025-11-25", "capabilities": {},
                    "clientInfo": {"name": "engineering-pipe-not-native-approval", "version": "1"},
                }})
                assert (await pipe.receive())["id"] == "init"
                await pipe.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
                await pipe.send({"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {
                    "name": "memory_required_context", "arguments": gateway.required_request,
                }})
                assert (await pipe.receive())["id"] == 7
                await pipe.send({"jsonrpc": "2.0", "id": final_id, "method": "tools/call", "params": {
                    "name": "memory_context", "arguments": arguments,
                }})
                if variant == "duplicate_id":
                    try:
                        await asyncio.wait_for(asyncio.shield(pipe.runner), 8)
                    except BaseException:
                        assert pipe.runner.done()
                    assert not ready.is_set()
                else:
                    assert await asyncio.to_thread(ready.wait, 5)
                    if variant == "output_limit":
                        pipe.transport.max_total = pipe.transport.written_bytes + 1
                    elif variant == "broken_pipe":
                        pipe.close_output()
                    elif variant == "cancel":
                        await pipe.send({"jsonrpc": "2.0", "method": "notifications/cancelled",
                                         "params": {"requestId": final_id}})
                        await asyncio.wait_for(cancelled.wait(), 5)
                    elif variant == "timeout":
                        with pytest.raises(TimeoutError):
                            await asyncio.wait_for(asyncio.shield(pipe.runner), 8)
                        assert pipe.runner.done()
                    release.set()
                    assert await asyncio.to_thread(worker_done.wait, 5)
                    if variant == "complete":
                        response = await pipe.receive()
                        assert response["id"] == final_id
                        final = json.loads(response["result"]["content"][0]["text"])
                        assert final["judgment_required"] is False
                        assert set(final["refs"]) == set(claims)
                        assert "only offline" in final["context"]
                    elif variant not in {"cancel", "timeout"}:
                        await asyncio.wait_for(failed_write.wait(), 5)
            finally:
                release.set()
                if ready.is_set():
                    assert await asyncio.to_thread(worker_done.wait, 5)
        observed = gateway.flow_observation()
        assert observed["captures"] == (captured,)
        deliveries = [row for row in traces if row["stage"] == "gateway_delivery"
                      and row.get("name") == "memory_context" and row.get("channel") == "stdio"]
        if variant == "complete":
            assert pipe.failure is None
            assert observed["observation_complete"] is True
            assert observed["pipeline_observed"] is True
            assert len(observed["final_reads"]) == 1
            assert len(deliveries) == 1
            assert deliveries[0]["written_sha256"] == hashlib.sha256(pipe.last_raw).hexdigest()
            assert deliveries[0]["written_bytes"] == len(pipe.last_raw)
            assert deliveries[0]["provider_consumption"] is None
        else:
            assert observed["observation_complete"] is False
            assert observed["pipeline_observed"] is False
            assert observed["final_reads"] == ()
            if variant != "delivery_observer_failure":
                assert deliveries == []
