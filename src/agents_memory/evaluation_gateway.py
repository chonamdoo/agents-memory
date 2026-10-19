from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import sys
import threading
import time
import urllib.error
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, replace
from http.client import HTTPException
from pathlib import Path
from uuid import uuid4

import anyio
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.shared.dispatcher import coerce_request_id
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool

from .client import HttpExchange, LocalClient
from .connection import read_http_body
from .domain import CaptureCommand, ContextCommand, DomainError, EffectState, Operation
from .edge import DESCRIPTIONS, SCHEMAS, _compact_schema, input_schema, record_schema
from .stdio import RelayEndpoint, StdioRelay
from .wire import decode_json, validate_wire


def _tool_payload(result: dict) -> dict:
    content = result.get("content")
    if (not isinstance(content, list) or len(content) != 1 or not isinstance(content[0], dict)
            or not isinstance(content[0].get("text"), str)):
        raise DomainError("UPSTREAM_RESULT_INVALID", "The bounded tool data is unavailable", effect=EffectState.UNKNOWN)
    payload = decode_json(content[0]["text"].encode())
    metadata = result.get("_meta")
    if metadata is not None:
        if not isinstance(metadata, dict):
            raise DomainError("UPSTREAM_METADATA_INVALID", "The tool metadata is unavailable", effect=EffectState.UNKNOWN)
        stamp = metadata.get("agents-memory/stamp")
        if stamp is not None:
            if not isinstance(stamp, dict) or "stamp" in payload and payload["stamp"] != stamp:
                raise DomainError("UPSTREAM_STAMP_INVALID", "The tool stamp is inconsistent", effect=EffectState.UNKNOWN)
            payload["stamp"] = stamp
    return payload


class _BoundedStdio:
    def __init__(self, max_record: int, max_total: int, observer: Callable[[str, bytes], None]) -> None:
        self.max_record, self.max_total, self.observer = max_record, max_total, observer
        self.pending = bytearray()
        self.read_bytes = 0
        self.retained_read_bytes = 0
        self.written_bytes = 0

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        while b"\n" not in self.pending:
            await anyio.wait_readable(sys.stdin.fileno())
            try:
                chunk = os.read(sys.stdin.fileno(), min(65536, self.max_record + 1))
            except BlockingIOError:
                continue
            if not chunk:
                if self.pending:
                    self.observer("gateway_stdio_partial", bytes(self.pending))
                    raise ValueError("Partial gateway protocol record")
                raise StopAsyncIteration
            self.read_bytes += len(chunk)
            if self.read_bytes > self.max_total:
                remaining = max(0, self.max_total - self.retained_read_bytes)
                self.observer("gateway_stdio_input_limit", bytes(self.pending + chunk)[:remaining])
                raise ValueError("Gateway input total exceeded")
            self.pending.extend(chunk)
            if len(self.pending) > self.max_record and b"\n" not in self.pending:
                self.observer("gateway_stdio_input_limit", bytes(self.pending[:self.max_record]))
                raise ValueError("Gateway input record exceeded")
        line, _, rest = self.pending.partition(b"\n")
        self.pending[:] = rest
        if len(line) > self.max_record:
            self.observer("gateway_stdio_input_limit", bytes(line[:self.max_record]))
            raise ValueError("Gateway input record exceeded")
        self.observer("gateway_stdio_received", bytes(line) + b"\n")
        self.retained_read_bytes += len(line) + 1
        decode_json(bytes(line))
        return line.decode("utf-8") + "\n"

    async def write(self, text: str) -> None:
        raw = text.encode("utf-8")
        remaining = max(0, self.max_total - self.written_bytes)
        if len(raw) > remaining:
            self.observer("gateway_stdio_output_limit", raw[:remaining])
            self.written_bytes = self.max_total
            raise ValueError("Gateway output total exceeded")
        self.written_bytes += len(raw)
        sent = 0
        try:
            self.observer("gateway_stdio_prepared", raw)
            view = memoryview(raw)
            while view:
                await anyio.wait_writable(sys.stdout.fileno())
                try:
                    count = os.write(sys.stdout.fileno(), view)
                except BlockingIOError:
                    continue
                if count <= 0:
                    raise OSError("Gateway output made no progress")
                sent += count
                view = view[count:]
            self.observer("gateway_stdio_written", raw)
        except BaseException as error:
            try:
                self.observer("gateway_stdio_write_failed", raw[:sent])
            except BaseException as observation_error:
                raise BaseExceptionGroup("Private gateway output and observation failures",
                                         [error, observation_error]) from None
            raise


    async def flush(self) -> None:
        # os.write above is unbuffered; there is no Python stream buffer to flush.
        return None


@dataclass(frozen=True, slots=True)
class GatewayUpstream:
    endpoint: RelayEndpoint
    token_file: Path
    role: str
    binding_id: str
    approval_ref: str


@dataclass(frozen=True, slots=True)
class GatewayScope:
    invocation_id: str
    route_ref: str
    mode: str
    phase: str
    binding_id: str
    approved_upstream_urls: tuple[str, ...]
    approved_refs: tuple[str, ...]
    protocol_version: str
    max_calls: int
    max_trace_bytes: int
    required_request: dict
    exclusive_route_observation_ref: str | None = None
    residual_memory_observation_ref: str | None = None

    def __post_init__(self) -> None:
        if self.mode not in {"off", "required_only", "memory_on"}:
            raise ValueError("Choose required_only/off or memory_on")
        if self.phase not in {"preflight", "coding"}:
            raise ValueError("Choose preflight or coding")
        if not all((self.invocation_id, self.route_ref, self.binding_id, self.protocol_version)):
            raise ValueError("A gateway needs an explicit invocation and approved route")
        if type(self.max_calls) is not int or self.max_calls <= 0:
            raise ValueError("Calls require an explicit positive bound")
        if type(self.max_trace_bytes) is not int or self.max_trace_bytes <= 0:
            raise ValueError("Wire observations require an explicit positive bound")


class _ObservedOpener:
    def __init__(self, delegate, relay: _ObservedRelay) -> None:
        self.delegate, self.relay = delegate, relay

    def open(self, request, *, timeout):
        self.relay.exchange_id = uuid4().hex
        self.relay.started_ns = time.monotonic_ns()
        self.relay.request_body = request.data
        self.relay.method = request.get_method()
        self.relay.observe("prepared")
        try:
            return self.delegate.open(request, timeout=timeout)
        except urllib.error.HTTPError:
            # StdioRelay reads and validates the actual error body before deciding on replay.
            raise
        except Exception:
            self.relay.observe("failure", error_code="TRANSPORT_FAILED", effect=EffectState.UNKNOWN)
            raise


class _ObservedRelay(StdioRelay):
    def __init__(self, upstream: GatewayUpstream, observer: Callable[[HttpExchange], None]) -> None:
        self.observer = observer
        self.exchange_id = ""
        self.started_ns = 0
        self.request_body: bytes | None = None
        self.method = "POST"
        super().__init__(upstream.endpoint, upstream.token_file)

    @property
    def opener(self):
        return self._observed_opener

    @opener.setter
    def opener(self, value) -> None:
        self._observed_opener = _ObservedOpener(value, self)

    def observe(
        self, stage, *, body=None, status=None, complete=False, error_code=None, effect=None,
    ) -> None:
        try:
            self.observer(HttpExchange(
                self.exchange_id, stage, self.method, "/mcp", self.started_ns,
                time.monotonic_ns(), self.request_body, body, status, complete, error_code, effect,
            ))
        except Exception:
            raise DomainError("OBSERVATION_FAILED", "Private wire observation failed", status=503,
                              effect=EffectState.NOT_STARTED if stage == "prepared" else EffectState.UNKNOWN) from None

    def read_response(self, response, *, deadline=None):
        status = getattr(response, "status", None)
        status = status if type(status) is int else getattr(response, "code", None)
        try:
            raw = read_http_body(
                response, maximum=self.settings.max_mcp_response_bytes,
                deadline=deadline if deadline is not None else time.monotonic() + 120,
            )
        except (OSError, ValueError, DomainError, HTTPException):
            self.observe("failure", status=status, error_code="RESPONSE_READ_FAILED", effect=EffectState.UNKNOWN)
            raise
        complete = len(raw) <= self.settings.max_mcp_response_bytes
        self.observe("response" if complete else "failure", body=raw, status=status,
                     complete=complete, error_code=None if complete else "RPC_RESPONSE_INVALID",
                     effect=None if complete else EffectState.UNKNOWN)
        if not complete:
            raise DomainError("RPC_RESPONSE_INVALID", "The upstream result is incomplete", effect=EffectState.UNKNOWN)
        try:
            return decode_json(raw) if raw else None
        except (ValueError, UnicodeError):
            raise DomainError("RPC_RESPONSE_INVALID", "The upstream result is invalid", effect=EffectState.UNKNOWN) from None


@contextmanager
def _locked(*gateways: EvaluationGateway) -> Iterator[None]:
    # Address order gives every caller the same acquisition order across gateway pairs.
    with ExitStack() as stack:
        for gateway in sorted(set(gateways), key=id):
            stack.enter_context(gateway._lock)
        yield


class EvaluationGateway:
    def __init__(
        self, scope: GatewayScope, *, agent: GatewayUpstream,
        producer: GatewayUpstream | None, trace_sink: Callable[[dict], None],
    ) -> None:
        self.scope, self.trace_sink = scope, trace_sink
        for upstream, role in ((agent, "agent"), (producer, "producer")):
            if upstream is None:
                continue
            if (upstream.role != role or upstream.binding_id != scope.binding_id
                    or not upstream.approval_ref
                    or upstream.endpoint.base_url not in scope.approved_upstream_urls):
                raise ValueError("The gateway upstream is not approved for this invocation and role")
        if producer is not None and producer.token_file == agent.token_file:
            raise ValueError("Producer and agent credentials must remain distinct")
        if producer is not None and producer.endpoint.base_url != agent.endpoint.base_url:
            raise ValueError("Producer and agent must use one approved memory authority")
        required = validate_wire(ContextCommand, scope.required_request)
        if required.binding_id != scope.binding_id or required.admission_id is not None:
            raise ValueError("Required context needs the frozen binding/selectors without relevance")
        self.required_request = required.model_dump(mode="json", exclude_none=True)
        self._lock = threading.Lock()
        self._wire_lock = threading.Lock()
        self._trace_bytes = 0
        self._calls = 0
        self._active = False
        self._closed = False
        self._allowed_refs = set(scope.approved_refs)
        self._sequence = 0
        self._current_call: str | None = None
        self._source_windows: dict[str, list[tuple[int, int]]] = {}
        self._source_revisions: dict[str, set[tuple[int, int]]] = {}
        self._selections: set[str] = set()
        self._selection_sources: dict[str, str] = {}
        self._selection_claims: dict[str, set[str]] = {}
        self._inspected_selections: set[str] = set()
        self._inspected_claims: set[str] = set()
        self._delivered_inspections: set[str] = set()
        self._delivered_admissions: set[str] = set()
        self._admission_payloads: dict[str, dict] = {}
        self._fork_child: dict | None = None
        self._fork_links: dict[str, dict] = {}
        self._fork_admissions: set[str] = set()
        self._admissions: dict[str, tuple[dict, set[str]]] = {}
        self._captures: list[dict] = []
        self._capture_http_status: int | None = None
        self._final_reads: list[dict] = []
        self._final_read_attempts: list[dict] = []
        self._observation_failed = False
        self._required_stamps: list[dict] = []
        self._record_windows: dict[str, tuple[str, int, bytearray]] = {}
        self._pending_delivery: dict[str | int, dict] = {}
        self._received_ids: set[str | int] = set()
        self._received_tools: dict[str | int, dict] = {}
        self._answered_ids: set[str | int] = set()
        self._cancelled_ids: set[str | int] = set()
        self._relay = _ObservedRelay(agent, self._wire)
        self._agent = self._client(agent)
        self._producer = self._client(producer) if producer is not None else None
        self._schemas = {"memory_required_context": _compact_schema(input_schema(ContextCommand))}
        if scope.mode == "memory_on":
            self._schemas.update({
                name: _compact_schema(record_schema() if name == "memory_record" else input_schema(model))
                for name, model in SCHEMAS.items()
            })
        self.server = Server(
            "agents-memory-evaluation", version="1", instructions="",
            on_list_tools=self._list_tools, on_call_tool=self._call_tool,
            get_tool_input_schema=self._schemas.get,
        )

    def _client(self, upstream: GatewayUpstream) -> LocalClient:
        endpoint = upstream.endpoint
        return LocalClient(
            endpoint.base_url, upstream.token_file, state_dir=endpoint.state_dir,
            deployment_id=endpoint.deployment_id, remote_settings=endpoint.remote_settings,
            wire_observer=self._wire,
        )

    def _trace(self, stage: str, **fields) -> None:
        try:
            self.trace_sink({"stage": stage, "invocation_id": self.scope.invocation_id,
                             "route_ref": self.scope.route_ref, "observed_ns": time.monotonic_ns(), **fields})
        except Exception:
            self._observation_failed = True
            raise

    def _wire(self, exchange: HttpExchange) -> None:
        size = len(exchange.request_body or b"") + len(exchange.response_body or b"")
        with self._wire_lock:
            if exchange.path == "/api/capture" and exchange.stage == "response":
                self._capture_http_status = exchange.http_status
            remaining = max(0, self.scope.max_trace_bytes - self._trace_bytes)
            if size > remaining:
                request = (exchange.request_body or b"")[:remaining]
                remaining -= len(request)
                response = (exchange.response_body or b"")[:remaining]
                bounded = replace(exchange, request_body=request, response_body=response,
                                  response_complete=False)
                self._trace_bytes = self.scope.max_trace_bytes
                self._observation_failed = True
                self._closed = True
                self._trace("gateway_wire", call_id=self._current_call, exchange=bounded,
                            truncated=True, original_request_bytes=len(exchange.request_body or b""),
                            original_response_bytes=len(exchange.response_body or b""))
                raise ValueError("Wire observation bound exceeded")
            self._trace_bytes += size
            self._trace("gateway_wire", call_id=self._current_call, exchange=exchange, truncated=False)

    def _enter(self, name: str, downstream_request_id: str | int | None = None) -> str:
        refusal = None
        with self._lock:
            self._sequence += 1
            call_id = f"{self.scope.invocation_id}:{self._sequence}"
            if self._closed:
                refusal = "GATEWAY_CLOSED"
            elif self._active:
                refusal = "GATEWAY_BUSY"
            elif self._calls >= self.scope.max_calls:
                refusal = "GATEWAY_CALL_LIMIT"
                self._closed = True
            else:
                self._calls += 1
                self._active = True
                self._current_call = call_id
        if refusal is not None:
            self._trace("gateway_denial", call_id=call_id, name=name, code=refusal,
                        downstream_request_id=downstream_request_id, effect="not_started")
            raise DomainError(refusal, "This invocation cannot admit this call", status=503)
        try:
            self._trace("gateway_intent", call_id=self._current_call, name=name,
                        downstream_request_id=downstream_request_id)
        except Exception:
            self._leave()
            raise
        return self._current_call

    def _leave(self) -> None:
        with self._lock:
            self._active = False
            self._current_call = None

    def close(self) -> None:
        with self._lock:
            self._closed = True
            if self._active:
                self._observation_failed = True
                raise DomainError("GATEWAY_BUSY", "An upstream operation still needs reconciliation",
                                  effect=EffectState.UNKNOWN)
            if self._pending_delivery:
                self._observation_failed = True
        self._trace("gateway_closed")


    def _deny(self, code: str) -> None:
        self._trace("gateway_denial", call_id=self._current_call, code=code, effect="not_started")
        raise DomainError(code, "The invocation route does not authorize this request", status=403)

    async def _list_tools(self, context, params):
        return ListToolsResult(tools=[
            Tool(name=name, description=("Read the identical frozen required rules, without optional memory."
                 if name == "memory_required_context" else DESCRIPTIONS[name]), inputSchema=schema)
            for name, schema in self._schemas.items()
        ])

    async def _call_tool(self, context, params):
        try:
            result = await asyncio.to_thread(
                self.call_tool, params.name, params.arguments or {}, downstream_request_id=context.request_id,
            )
            return CallToolResult.model_validate(result)
        except DomainError as error:
            return CallToolResult(isError=True, content=[TextContent(type="text", text=json.dumps({
                "error": {"code": error.code, "effect": error.effect.value},
            }))])
        except Exception:
            return CallToolResult(isError=True, content=[TextContent(type="text", text=json.dumps({
                "error": {"code": "GATEWAY_FAILURE_RECONCILE", "effect": "unknown"},
            }))])

    def capture(self, command: CaptureCommand | dict) -> dict:
        self._enter("producer_capture")
        try:
            if self.scope.mode != "memory_on" or self.scope.phase != "preflight" or self._producer is None:
                self._deny("OPTIONAL_CAPTURE_DENIED")
            payload = command.model_dump(mode="json") if isinstance(command, CaptureCommand) else command
            parsed = validate_wire(CaptureCommand, payload)
            if parsed.binding_id != self.scope.binding_id or parsed.injected:
                self._deny("CAPTURE_SCOPE_DENIED")
            self._capture_http_status = None
            response = self._producer.request("/api/capture", payload)
            validate_wire(Operation, response)
            pointer = response.get("source_pointer")
            if (self._capture_http_status != 202 or response.get("effect") != "committed"
                    or response.get("capture_disposition") != "captured"
                    or not isinstance(pointer, dict) or pointer.get("binding_id") != self.scope.binding_id
                    or not isinstance(pointer.get("source_id"), str)
                    or pointer.get("source_id") != response.get("source_id")):
                raise DomainError("CAPTURE_ACK_INVALID", "A matching committed source pointer is required", effect=EffectState.UNKNOWN)
            self._allowed_refs.add(pointer["source_id"])
            self._captures.append(response)
            self._trace("capture_ack", operation_id=response.get("id"), source_pointer=pointer)
            return response
        finally:
            self._leave()

    def _initialize_relay(self) -> None:
        if self._relay.protocol_version is not None:
            return
        result = self._relay.forward({"jsonrpc": "2.0", "id": "gateway-initialize", "method": "initialize",
                                      "params": {"protocolVersion": self.scope.protocol_version,
                                                 "capabilities": {}, "clientInfo": {
                                                     "name": "agents_memory_evaluation", "version": "1"}}})
        if not isinstance(result, dict) or "error" in result:
            raise DomainError("MCP_INITIALIZE_FAILED", "The approved upstream MCP route is unavailable")
        if self._relay.protocol_version != self.scope.protocol_version:
            raise DomainError("MCP_VERSION_CHANGED", "The upstream protocol does not match the frozen version")
        self._relay.forward({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _complete_delivery(self, item: dict, channel: str, raw: bytes | None = None) -> None:
        self._trace(
            "gateway_delivery", name=item["name"], call_id=item["call_id"],
            downstream_request_id=item["downstream_request_id"], channel=channel,
            is_error=item["is_error"], stdout_write_complete=channel == "stdio",
            written_sha256=hashlib.sha256(raw).hexdigest() if raw is not None else None,
            written_bytes=len(raw) if raw is not None else None,
            payload_sha256=hashlib.sha256(item["text"].encode()).hexdigest(),
            provider_consumption=None,
        )
        with self._lock:
            if self._closed:
                self._observation_failed = True
                raise DomainError("DELIVERY_AFTER_CLOSE", "Reconcile the completed upstream operation",
                                  effect=EffectState.UNKNOWN)
            if not item["is_error"]:
                if item["stamp"] is not None:
                    self._required_stamps.append(item["stamp"])
                if item["name"] == "memory_inspect" and channel == "stdio":
                    ref = item["arguments"].get("ref")
                    if ref in self._inspected_claims and ref not in self._record_windows:
                        self._delivered_inspections.add(ref)
                if (item["name"] == "memory_context" and channel == "stdio"
                        and not item["arguments"].get("admission_id")):
                    admission = (item["payload"] or {}).get("admission_id")
                    if admission in self._admissions:
                        self._delivered_admissions.add(admission)
                if item["final_read"] is not None:
                    self._final_reads.append(item["final_read"])
            if channel == "stdio":
                key = coerce_request_id(item["downstream_request_id"])
                self._pending_delivery.pop(key)
                self._answered_ids.add(key)

    def _result_ready(
        self, name: str, arguments: dict, result: dict, downstream_request_id,
        *, payload=None, stamp=None, final_read=None,
    ) -> dict:
        content, is_error = result.get("content"), result.get("isError", False)
        if (type(is_error) is not bool or not isinstance(content, list) or len(content) != 1
                or not isinstance(content[0], dict) or not isinstance(content[0].get("text"), str)):
            raise DomainError("UPSTREAM_RESULT_INVALID", "The bounded result is unavailable",
                              effect=EffectState.UNKNOWN)
        item = {
            "call_id": self._current_call, "name": name, "arguments": arguments,
            "downstream_request_id": downstream_request_id, "is_error": is_error,
            "text": content[0]["text"], "payload": payload, "stamp": stamp, "final_read": final_read,
            "metadata_stamp": (result.get("_meta") or {}).get("agents-memory/stamp"),
        }
        if downstream_request_id is None:
            self._complete_delivery(item, "direct")
        else:
            if type(downstream_request_id) not in {str, int}:
                self._observation_failed = True
                raise DomainError("DOWNSTREAM_ID_INVALID", "The response identity is unavailable",
                                  effect=EffectState.UNKNOWN)
            key = coerce_request_id(downstream_request_id)
            with self._lock:
                if (self._closed or key in self._pending_delivery or key in self._answered_ids
                        or key in self._cancelled_ids):
                    self._observation_failed = True
                    raise DomainError("DOWNSTREAM_DELIVERY_AMBIGUOUS", "Reconcile the downstream response",
                                      effect=EffectState.UNKNOWN)
                self._pending_delivery[key] = item
            self._trace("gateway_dispatched", name=name, call_id=item["call_id"],
                        downstream_request_id=downstream_request_id, stdout_write_complete=False)
        return result

    def _stdio_observe(self, stage: str, raw: bytes) -> None:
        if stage in {
            "gateway_stdio_partial", "gateway_stdio_input_limit",
            "gateway_stdio_output_limit", "gateway_stdio_write_failed",
        }:
            self._observation_failed = True
        self._trace(stage, body=raw)
        if stage not in {"gateway_stdio_received", "gateway_stdio_written"}:
            return
        try:
            if not raw.endswith(b"\n") or raw.count(b"\n") != 1:
                raise ValueError("Gateway protocol record is not one complete line")
            message = decode_json(raw)
            if not isinstance(message, dict):
                raise ValueError("Gateway protocol record is not an object")
            if stage == "gateway_stdio_received":
                if message.get("method") == "notifications/cancelled":
                    identifier = message.get("params", {}).get("requestId")
                    if type(identifier) in {str, int}:
                        key = coerce_request_id(identifier)
                        with self._lock:
                            if key in self._received_tools and key not in self._answered_ids:
                                self._cancelled_ids.add(key)
                                self._observation_failed = True
                elif "id" in message and isinstance(message.get("method"), str):
                    identifier = message["id"]
                    if type(identifier) not in {str, int}:
                        raise ValueError("Gateway request identity is invalid")
                    key = coerce_request_id(identifier)
                    with self._lock:
                        if key in self._received_ids:
                            raise ValueError("Gateway request identity was reused")
                        self._received_ids.add(key)
                        if message["method"] == "tools/call":
                            self._received_tools[key] = message
                return
            identifier = message.get("id")
            if type(identifier) not in {str, int}:
                return
            key = coerce_request_id(identifier)
            with self._lock:
                item = self._pending_delivery.get(key)
                request = self._received_tools.get(key)
                cancelled = key in self._cancelled_ids
            if item is None:
                if request is not None:
                    if (type(identifier) is not type(request["id"]) or identifier != request["id"]
                            or message.get("result", {}).get("isError") is not True):
                        raise ValueError("Gateway tool response has no dispatched result")
                    with self._lock:
                        self._answered_ids.add(key)
                return
            result = message.get("result")
            content = result.get("content") if isinstance(result, dict) else None
            params = request.get("params", {}) if request is not None else {}
            metadata = result.get("_meta") if isinstance(result, dict) else None
            metadata = {} if metadata is None else metadata
            if (cancelled or request is None
                    or type(identifier) is not type(item["downstream_request_id"])
                    or identifier != item["downstream_request_id"]
                    or type(identifier) is not type(request["id"]) or identifier != request["id"]
                    or params.get("name") != item["name"]
                    or (params.get("arguments") or {}) != item["arguments"]
                    or not isinstance(result, dict) or result.get("isError", False) is not item["is_error"]
                    or not isinstance(metadata, dict) or metadata.get("agents-memory/stamp") != item["metadata_stamp"]
                    or not isinstance(content, list) or len(content) != 1
                    or not isinstance(content[0], dict) or content[0].get("text") != item["text"]):
                raise ValueError("Gateway dispatched result was not the completed response")
            self._complete_delivery(item, "stdio", raw)
        except BaseException:
            self._observation_failed = True
            raise

    def call_tool(self, name: str, arguments: dict, *, downstream_request_id: str | int | None = None) -> dict:
        if not isinstance(arguments, dict):
            raise DomainError("INPUT_INVALID", "Tool arguments must be an object")
        self._enter(name, downstream_request_id)
        original_arguments = arguments
        context_identity = None
        try:
            if self._fork_child is not None and name != "memory_inspect":
                self._deny("FORK_CHILD_TOOL_DENIED")
            if self._fork_child is not None and self._fork_child.get("completed"):
                self._deny("FORK_CHILD_ALREADY_COMPLETED")
            if name not in self._schemas:
                self._deny("OPTIONAL_TOOL_DENIED" if self.scope.mode != "memory_on" else "TOOL_SCOPE_DENIED")
            if name == "memory_required_context":
                parsed = validate_wire(ContextCommand, arguments)
                normalized = parsed.model_dump(mode="json", exclude_none=True)
                if normalized != self.required_request:
                    self._deny("REQUIRED_SELECTORS_CHANGED")
                result = self._agent.request("/api/required-context", self.required_request)
                stamp = result.get("stamp")
                if not isinstance(stamp, dict):
                    raise DomainError("REQUIRED_STAMP_MISSING", "Required rule identity is unavailable", effect=EffectState.UNKNOWN)
                response = {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}
                return self._result_ready(name, original_arguments, response, downstream_request_id,
                                          payload=result, stamp=stamp)
            if not self._required_stamps and self._fork_child is None:
                self._deny("REQUIRED_CONTEXT_READ_REQUIRED")
            if arguments.get("binding_id", self.scope.binding_id) != self.scope.binding_id:
                self._deny("BINDING_SCOPE_DENIED")
            arguments = {**arguments, "binding_id": self.scope.binding_id}
            model = SCHEMAS[name]
            parsed = validate_wire(model, arguments)
            if name == "memory_context":
                normalized = parsed.model_dump(mode="json", exclude_none=True)
                for key in ("paths", "purpose", "host", "snapshot", "code_workspace_id", "limit", "max_bytes"):
                    if normalized.get(key) != self.required_request.get(key):
                        self._deny("REQUIRED_SELECTORS_CHANGED")
                context_identity = {
                    key: value for key, value in normalized.items() if key not in {"admission_id", "relevance"}
                }
                admission = normalized.get("admission_id")
                if admission in self._fork_admissions:
                    delegated = self._fork_links.get(admission)
                    if (delegated is None or delegated["request"] != context_identity
                            or delegated["relevance"] != normalized.get("relevance")):
                        self._deny("FORK_PARENT_VALIDATION_REQUIRED")
            if name == "memory_inspect":
                ref = arguments.get("ref")
                if ref not in self._allowed_refs and not (
                    ref == "judgment" and self.scope.phase == "preflight"
                    and set(arguments.get("claim_ids") or ()) <= self._allowed_refs
                    and arguments.get("claim_ids")
                ):
                    self._deny("INSPECTION_SCOPE_DENIED")
            if self.scope.phase == "coding" and name in {"memory_record", "memory_feedback"}:
                self._deny("FROZEN_CORPUS_MUTATION_DENIED")
            if name == "memory_record":
                if arguments.get("kind") not in {"source_selection", "claim_judgment"}:
                    self._deny("RECORD_KIND_DENIED")
                if arguments.get("kind") == "source_selection" and arguments.get("source_id") not in self._source_windows:
                    self._deny("SOURCE_INSPECTION_REQUIRED")
            self._initialize_relay()
            rpc = {"jsonrpc": "2.0", "id": self._current_call, "method": "tools/call",
                   "params": {"name": name, "arguments": arguments}}
            response = self._relay.forward(rpc)
            if not isinstance(response, dict) or "result" not in response:
                error = response.get("error", {}) if isinstance(response, dict) else {}
                data = error.get("data", {}) if isinstance(error, dict) else {}
                verified = self._relay._verified(error.get("message"), data.get("effect")) if isinstance(data, dict) else None
                effect = verified[1] if verified is not None else EffectState.UNKNOWN
                self._trace("gateway_rpc_error", response=response, effect=effect.value)
                raise DomainError("UPSTREAM_RPC_FAILED", "Reconcile the upstream request", effect=effect)
            result = response["result"]
            if not isinstance(result, dict):
                raise DomainError("UPSTREAM_RESULT_INVALID", "The MCP result is invalid", effect=EffectState.UNKNOWN)
            final_read = None
            payload = None
            if not result.get("isError", False):
                content = result.get("content")
                if not isinstance(content, list) or len(content) != 1 or not isinstance(content[0].get("text"), str):
                    raise DomainError("UPSTREAM_RESULT_INVALID", "The MCP result has no bounded data plane", effect=EffectState.UNKNOWN)
                payload = _tool_payload(result)
                final_read = self._observe_flow(name, arguments, payload, context_identity=context_identity)
            return self._result_ready(name, original_arguments, result, downstream_request_id,
                                      payload=payload, final_read=final_read)
        except BaseException as error:
            if not isinstance(error, DomainError) or error.effect == EffectState.UNKNOWN:
                self._observation_failed = True
            raise
        finally:
            self._leave()

    def _observe_flow(
        self, name: str, arguments: dict, payload: dict, *, context_identity: dict | None = None,
    ) -> dict | None:
        final_read = None
        if name == "memory_inspect" and isinstance(payload.get("draft_window"), dict):
            window = payload["draft_window"]
            ref = arguments["ref"]
            body = window.get("body")
            start, end, total = (window.get(key) for key in ("byte_start", "byte_end", "total_bytes"))
            digest = window.get("digest")
            if (not isinstance(body, str) or not isinstance(digest, str)
                    or any(type(value) is not int for value in (start, end, total))
                    or not 0 <= start < end <= total <= self.scope.max_trace_bytes
                    or len(body.encode()) != end - start):
                raise DomainError("INSPECTION_WINDOW_INVALID", "Invalid stored-record window", effect=EffectState.UNKNOWN)
            prior_digest, prior_total, collected = self._record_windows.get(ref, (digest, total, bytearray()))
            if start == 0:
                collected = bytearray()
            if digest != prior_digest or total != prior_total or start != len(collected):
                raise DomainError("INSPECTION_WINDOW_CHANGED", "Reassemble the same contiguous stored record", effect=EffectState.UNKNOWN)
            collected.extend(body.encode())
            self._record_windows[ref] = (digest, total, collected)
            if window.get("next_byte") is not None:
                if window["next_byte"] != end:
                    raise DomainError("INSPECTION_CURSOR_INVALID", "Invalid inspection continuation", effect=EffectState.UNKNOWN)
                return
            if end != total or hashlib.sha256(collected).hexdigest() != digest:
                raise DomainError("INSPECTION_DIGEST_INVALID", "Stored-record identity mismatch", effect=EffectState.UNKNOWN)
            payload = decode_json(bytes(collected))
            del self._record_windows[ref]
        refs = payload.get("refs", [])
        for ref in refs if isinstance(refs, list) else ():
            if isinstance(ref, str):
                self._allowed_refs.add(ref)
        for key in ("artifact_id", "source_id", "claim_id", "ref"):
            value = payload.get(key)
            if isinstance(value, str):
                self._allowed_refs.add(value)
        for key in ("claim_ids", "judgment_context_refs"):
            for ref in payload.get(key, []) if isinstance(payload.get(key), list) else ():
                if isinstance(ref, str):
                    self._allowed_refs.add(ref)
                elif isinstance(ref, dict) and isinstance(ref.get("ref"), str):
                    self._allowed_refs.add(ref["ref"])
        if name == "memory_inspect":
            ref = arguments["ref"]
            if payload.get("source_id") == ref and "window_digest" in payload:
                self._source_windows.setdefault(ref, []).append((payload["byte_start"], payload["byte_end"]))
                self._source_revisions.setdefault(ref, set()).add((
                    payload["source_revision"], payload["binding_revision"],
                ))
            if ref in self._selections:
                self._inspected_selections.add(ref)
                self._selection_claims[ref] = set(payload.get("claim_ids", []))
            self._inspected_claims.add(ref)
        elif name == "memory_record" and arguments.get("kind") == "source_selection":
            if arguments.get("label") == "remember" and isinstance(arguments.get("extraction"), dict):
                extraction = arguments["extraction"]
                if all(isinstance(extraction.get(key), list) for key in (
                    "claims", "individual_qualifications", "shared_qualifications", "validities", "unused_span_ids",
                )) and isinstance(payload.get("artifact_id"), str) and payload.get("state") == "candidate_ready":
                    self._selections.add(payload["artifact_id"])
                    self._selection_sources[payload["artifact_id"]] = arguments["source_id"]
        elif name == "memory_context":
            if context_identity is None:
                raise DomainError("CONTEXT_IDENTITY_UNOBSERVED", "The normalized context identity is unavailable",
                                  effect=EffectState.UNKNOWN)
            admission = payload.get("admission_id") or arguments.get("admission_id")
            if not arguments.get("admission_id"):
                manifest = payload.get("candidate_manifest")
                if isinstance(admission, str) and isinstance(manifest, list):
                    ids = {item["claim_id"] for item in manifest if isinstance(item, dict) and isinstance(item.get("claim_id"), str)}
                    self._allowed_refs.update(ids)
                    self._admissions[admission] = (context_identity, ids)
                    self._admission_payloads[admission] = json.loads(json.dumps(payload))
                    for item in manifest:
                        if isinstance(item, dict) and isinstance(item.get("inspection_ref"), str):
                            self._allowed_refs.add(item["inspection_ref"])
            elif admission in self._admissions and payload.get("judgment_required") is False:
                original, ids = self._admissions[admission]
                decisions = arguments.get("relevance", [])
                selected_ids = [item.get("claim_id") for item in decisions]
                delegated = self._fork_links.get(admission)
                delegated_valid = (
                    delegated is not None and delegated["request"] == context_identity
                    and delegated["relevance"] == decisions
                )
                if (context_identity == original and len(selected_ids) == len(ids) and set(selected_ids) == ids
                        and (delegated_valid or (
                            admission not in self._fork_admissions and ids <= self._inspected_claims
                        ))):
                    final_read = {"admission_id": admission, "refs": payload.get("refs"),
                                  "observed_ns": time.monotonic_ns(), "context": payload.get("context")}
                    if delegated_valid:
                        final_read["fork_link"] = {
                            key: value for key, value in delegated.items()
                            if key not in {"request", "relevance"}
                        }
                    self._final_read_attempts.append(final_read)
        self._trace("gateway_flow", name=name, operation_id=payload.get("id"),
                    source_id=payload.get("source_id"), admission_id=payload.get("admission_id"),
                    artifact_id=payload.get("artifact_id"), refs=payload.get("refs"))
        return final_read

    def observe_host_fork(
        self, child: EvaluationGateway, *, host: str, parent_generation: str,
        child_generation: str, task_id: str, admission_id: str,
        native_fork_ref: str, inherited_context_ref: str,
    ) -> None:
        """Register a host-observed conversation fork, not a model's delegation claim.

        The native evaluation harness must call this when the host itself observes the fork;
        `flow_observation` fork links and context gating depend on it. Registration is atomic
        with respect to both gateways, so a concurrent parent call either finishes before the
        fork (and the fork is refused as busy) or starts after it and sees the delegation.
        """
        with _locked(self, child):
            if (host not in {"claude", "codex"} or child is self
                    or self.required_request.get("host") not in {None, "generic", "agent-flow", host}
                    or not all(isinstance(value, str) and value for value in (
                        parent_generation, child_generation, task_id, native_fork_ref, inherited_context_ref,
                    ))
                    or parent_generation == child_generation
                    or child.scope.invocation_id == self.scope.invocation_id
                    or child.scope.binding_id != self.scope.binding_id
                    or child.scope.route_ref != self.scope.route_ref
                    or child.scope.required_request != self.scope.required_request
                    or child.scope.mode != "memory_on" or self.scope.mode != "memory_on"
                    or admission_id not in self._delivered_admissions
                    or admission_id in self._fork_admissions
                    or child._calls or child._fork_child is not None
                    or self._active or child._active or self._closed or child._closed):
                raise ValueError("A distinct, idle child needs the delivered parent admission and native fork lineage")
            request, ids = self._admissions[admission_id]
            record = {
                "host": host, "parent_invocation_id": self.scope.invocation_id,
                "child_invocation_id": child.scope.invocation_id,
                "parent_generation": parent_generation, "child_generation": child_generation,
                "task_id": task_id, "admission_id": admission_id,
                "native_fork_ref": native_fork_ref, "inherited_context_ref": inherited_context_ref,
            }
            child._fork_child = {**record, "parent": self, "request": request}
            child._allowed_refs = set(ids)
            for item in self._admission_payloads[admission_id]["candidate_manifest"]:
                if isinstance(item.get("inspection_ref"), str):
                    child._allowed_refs.add(item["inspection_ref"])
            inspection_schema = child._schemas["memory_inspect"]
            child._schemas.clear()
            child._schemas["memory_inspect"] = inspection_schema
            self._fork_admissions.add(admission_id)
            # Traced under the locks so no parent call can be recorded between registration and its trace.
            self._trace("gateway_host_fork", **record)

    def observe_child_completion(
        self, child: EvaluationGateway, *, child_return: dict, current_request: dict,
        current_task_id: str, native_completion_ref: str, parent_validation_ref: str,
    ) -> dict:
        """Credit delegated inspection only after completed child delivery and exact parent validation.

        The native evaluation harness must call this when the host observes the child's completion;
        without it the parent's fork admission can never earn final-read credit. Both gateways are
        locked so the child's delivered state and the parent link are read and written atomically.
        """
        from .fork_recall import validate_fork_recall

        with _locked(self, child):
            link = child._fork_child
            if (link is None or link["parent"] is not self or link.get("completed")
                    or not all(isinstance(value, str) and value for value in (
                        native_completion_ref, parent_validation_ref,
                    )) or self._active or child._active
                    or child._observation_failed or child._pending_delivery
                    or child._cancelled_ids or child._record_windows):
                raise ValueError("A completed, independently linked child delivery is required")
            admission = link["admission_id"]
            request, ids = self._admissions[admission]
            if not ids <= child._delivered_inspections:
                raise ValueError("The child did not receive the complete candidate manifest inspections")
            second = validate_fork_recall(
                request, current_request, self._admission_payloads[admission], child_return,
                task_id=link["task_id"], current_task_id=current_task_id,
            )
            if second.get("admission_id") != admission:
                raise ValueError("The validated child return changed the parent admission")
            record = {
                key: value for key, value in link.items() if key not in {"parent", "request"}
            }
            record.update(
                native_completion_ref=native_completion_ref, parent_validation_ref=parent_validation_ref,
                child_inspection_complete=True, child_result_contract_valid=True,
                parent_validation_observed=True, parent_understanding=None, provider_consumption=None,
                child_inspected_claims=tuple(sorted(child._inspected_claims)),
                child_return_sha256=hashlib.sha256(
                    json.dumps(child_return, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
            )
            self._fork_links[admission] = {
                **record, "request": request, "relevance": json.loads(json.dumps(second["relevance"])),
            }
            child._fork_child["completed"] = True
            self._trace("gateway_child_completion", **record)
            return second

    def flow_observation(self) -> dict:
        with self._lock:
            if self._active:
                return {
                    "invocation_id": self.scope.invocation_id, "mode": self.scope.mode,
                    "observation_complete": False, "pipeline_observed": False,
                    "outstanding_upstream": True, "partial_flow_unavailable": True,
                    "required_stamps": tuple(self._required_stamps), "final_reads": tuple(self._final_reads),
                    "captures": (), "source_windows": {}, "remembered_selections": (),
                    "inspected_selections": (), "final_read_attempts": (), "linked_capture_source_ids": (),
                    "final_read_observed": bool(self._final_reads),
                    "semantic_correctness": None, "provider_consumption": None,
                }
            complete = not self._observation_failed and not self._pending_delivery
            linked_sources = []
            delivered = {ref for read in self._final_reads for ref in (read.get("refs") or []) if isinstance(ref, str)}
            # Only links written by observe_child_completion exist here, so every entry is a completed,
            # parent-validated child; its inspections count toward linkage without joining parent claims.
            child_claims = {ref for link in self._fork_links.values() for ref in link["child_inspected_claims"]}
            inspected = self._inspected_claims | child_claims
            for capture in self._captures:
                pointer = capture["source_pointer"]
                source = pointer["source_id"]
                if self._source_revisions.get(source) != {(pointer["source_revision"], pointer["binding_revision"])}:
                    continue
                covered = 0
                for start, end in sorted(self._source_windows.get(source, [])):
                    if start > covered:
                        break
                    covered = max(covered, end)
                if covered != pointer["byte_length"]:
                    continue
                for selection in self._inspected_selections:
                    if (self._selection_sources.get(selection) == source
                            and self._selection_claims.get(selection, set()) <= inspected
                            and self._selection_claims.get(selection, set()) & delivered):
                        linked_sources.append(source)
                        break
            return {
                "invocation_id": self.scope.invocation_id, "mode": self.scope.mode,
                "captures": tuple(self._captures), "source_windows": dict(self._source_windows),
                "remembered_selections": tuple(sorted(self._selections)),
                "inspected_selections": tuple(sorted(self._inspected_selections)),
                "final_reads": tuple(self._final_reads), "required_stamps": tuple(self._required_stamps),
                "final_read_attempts": tuple(self._final_read_attempts),
                "fork_links": tuple(
                    {key: value for key, value in link.items() if key not in {"request", "relevance"}}
                    for link in self._fork_links.values()
                ),
                "parent_inspected_claims": tuple(sorted(self._inspected_claims)),
                "observation_complete": complete,
                "pipeline_observed": bool(linked_sources) and complete,
                "linked_capture_source_ids": tuple(linked_sources),
                "final_read_observed": bool(self._final_reads),
                "semantic_correctness": None, "provider_consumption": None,
                "comparable_route_evidence_present": bool(self.scope.exclusive_route_observation_ref
                                                           and self.scope.residual_memory_observation_ref),
            }


    async def run_stdio(self, *, timeout_seconds: float) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("The gateway lifetime must be explicitly bounded")
        if os.name != "posix":
            raise ValueError("Bounded gateway stdio requires the approved POSIX native context")
        transport = _BoundedStdio(
            self._relay.settings.max_http_body_bytes, self.scope.max_trace_bytes,
            self._stdio_observe,
        )
        descriptors = (sys.stdin.fileno(), sys.stdout.fileno())
        blocking = tuple(os.get_blocking(fd) for fd in descriptors)
        try:
            for fd in descriptors:
                os.set_blocking(fd, False)
            async with asyncio.timeout(timeout_seconds):
                async with stdio_server(stdin=transport, stdout=transport) as (read_stream, write_stream):
                    await self.server.run(read_stream, write_stream, self.server.create_initialization_options())
        except BaseException:
            self._observation_failed = True
            raise
        finally:
            with self._lock:
                self._closed = True
                if self._active or self._pending_delivery:
                    self._observation_failed = True
            for fd, was_blocking in zip(descriptors, blocking, strict=True):
                os.set_blocking(fd, was_blocking)

    def preflight_prompt(self, source_pointer: dict, recall_request: dict) -> str:
        if self.scope.mode != "memory_on" or self.scope.phase != "preflight":
            raise ValueError("Preflight is separate from frozen paired coding")
        if source_pointer.get("source_id") not in self._allowed_refs:
            raise ValueError("Preflight needs an actual captured approved source pointer")
        return (
            "Use this invocation's already approved agents-memory-evaluation MCP route. "
            "Read memory_required_context with the frozen request first. Inspect the source and all "
            "continuations; make your own grounded source_selection judgment. To remember, submit "
            "extraction atomically with all five arrays using the exact returned spans, admission, "
            "revisions, policy and digest. Inspect the returned selection and all claims and required "
            "judgment context; judge relationships where required. Call memory_context with the recall "
            "request, inspect every candidate completely, then submit your own relevance for every "
            "manifest claim with the identical request/admission. Read the actual final context. "
            "Do not claim completion based on a capture ACK or your final narrative.\n"
            + json.dumps({"source_pointer": source_pointer, "recall_request": recall_request,
                          "required_request": self.required_request}, ensure_ascii=False)
        )
