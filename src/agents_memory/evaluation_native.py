from __future__ import annotations

import errno
import hashlib
import json
import math
import os
import selectors
import signal
import stat
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .domain import DomainError
from .evaluation_artifacts import canonical_bytes, digest_bytes
from .native_status import _signal_process_group
from .private_io import private_read, private_write
from .wire import decode_json

NativeStatus = Literal[
    "blocked", "unsupported", "busy", "failed", "timeout", "aborted", "unknown", "completed"
]
TraceSink = Callable[[dict], None]


@dataclass(frozen=True, slots=True)
class NativeDriverSpec:
    backend: Literal["claude", "codex"]
    executable: Path
    cwd: Path
    submission_path: Path
    authorization_ref: str
    context_observation_ref: str
    approved_context: bool
    gateway_invocation_id: str
    gateway_route_ref: str
    exclusive_optional_route_observed: bool
    residual_memory_absence_observed: bool
    fresh_generation_observed: bool
    timeout_seconds: float
    cleanup_seconds: float
    max_input_bytes: int
    max_stdout_bytes: int
    max_stderr_bytes: int
    max_record_bytes: int
    max_events: int
    max_submission_bytes: int
    expected_model: str | None = None
    expected_version: str | None = None
    strict_protection_required: bool = False
    strict_protection_supported: bool = False

    def __post_init__(self) -> None:
        if self.backend not in {"claude", "codex"}:
            raise ValueError("Unsupported native backend")
        if not all(path.is_absolute() for path in (
            self.executable, self.cwd, self.submission_path,
        )) or not self.submission_path.is_relative_to(self.cwd):
            raise ValueError("Native paths require an absolute approved task scope")
        if ".." in self.cwd.parts or ".." in self.submission_path.parts or self.submission_path == self.cwd:
            raise ValueError("Native submission paths must stay below the normalized task root")
        for value in (self.timeout_seconds, self.cleanup_seconds):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("Native deadlines must be positive and finite")
        for value in (
            self.max_input_bytes, self.max_stdout_bytes, self.max_stderr_bytes,
            self.max_record_bytes, self.max_events, self.max_submission_bytes,
        ):
            if type(value) is not int or value <= 0:
                raise ValueError("Native bounds must be explicit positive integers")


@dataclass(frozen=True, slots=True)
class NativeArmResult:
    invocation_id: str
    status: NativeStatus
    code: str
    started_ns: int
    finished_ns: int
    exit_code: int | None
    effect: Literal["not_started", "unknown"]
    stdout: bytes = field(repr=False)
    stderr: bytes = field(repr=False)
    output_truncated: bool
    protocol_events: tuple[dict, ...] = field(repr=False)
    usage: dict = field(repr=False)
    identity: dict = field(repr=False)
    action_ids: tuple[str, ...] = field(repr=False)
    approval_requests: tuple[dict, ...] = field(repr=False)
    stop: dict
    cleanup: dict
    artifact_bundle: dict | None = field(repr=False)
    comparable: bool
    incomparability_reasons: tuple[str, ...]


class _ProtocolError(Exception):
    pass


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not value or len(value.encode()) > 512:
        raise _ProtocolError("IDENTITY_INVALID")
    return value


def observe_native_tool_calls(record: dict, *, backend: str, server: str, tools: dict[str, str]) -> list[dict]:
    names = {native: product for product, native in tools.items()}
    started, completed = {}, {}
    identity = record["identity"]
    for event_index, observed in enumerate(record["protocol_events"]):
        message = observed["message"]
        if backend == "codex":
            method, params = message.get("method"), message.get("params", {})
            item = params.get("item", {})
            if (method not in {"item/started", "item/completed"} or item.get("type") != "mcpToolCall"
                    or item.get("server") != server or item.get("tool") not in names):
                continue
            if (not identity.get("thread_id") or not identity.get("turn_id")
                    or params.get("threadId") != identity["thread_id"] or params.get("turnId") != identity["turn_id"]):
                raise ValueError("NATIVE_TOOL_GENERATION_MISMATCH")
            entries = [(item, method == "item/started")]
        else:
            if message.get("type") not in {"assistant", "user"}:
                continue
            entries = [(item, item.get("type") == "tool_use")
                       for item in message.get("message", {}).get("content", [])
                       if item.get("type") == "tool_use" and item.get("name") in names
                       or item.get("type") == "tool_result" and item.get("tool_use_id") in started]
            if entries and (not identity.get("session_id") or message.get("session_id") != identity["session_id"]):
                raise ValueError("NATIVE_TOOL_GENERATION_MISMATCH")
        if not entries:
            continue
        observed_ns = observed.get("observed_ns")
        if (type(observed_ns) is not int or not record["started_ns"] <= observed_ns <= record["finished_ns"]):
            raise ValueError("NATIVE_TOOL_OBSERVATION_SCOPE")
        event_digest = digest_bytes(canonical_bytes(message))
        for item, beginning in entries:
            action = item.get("id") if beginning or backend == "codex" else item.get("tool_use_id")
            if not isinstance(action, str) or action not in record["action_ids"]:
                raise ValueError("NATIVE_TOOL_ACTION_UNOBSERVED")
            if beginning:
                if action in started:
                    raise ValueError("NATIVE_TOOL_ACTION_REUSED")
                if backend == "claude" and message["type"] != "assistant":
                    raise ValueError("NATIVE_TOOL_ROLE_MISMATCH")
                arguments = item.get("arguments" if backend == "codex" else "input")
                if not isinstance(arguments, dict):
                    raise ValueError("NATIVE_TOOL_ARGUMENTS_UNOBSERVED")
                started[action] = {
                    "action_id": action, "name": names[item["tool" if backend == "codex" else "name"]],
                    "arguments": arguments, "start_event_digest": event_digest, "start_observed_ns": observed_ns,
                    "start_event_index": event_index,
                }
                continue
            call = started.get(action)
            if call is None or action in completed:
                raise ValueError("NATIVE_TOOL_RESULT_UNCORRELATED")
            if backend == "codex":
                if (names[item["tool"]] != call["name"]
                        or canonical_bytes(item.get("arguments")) != canonical_bytes(call["arguments"])):
                    raise ValueError("NATIVE_TOOL_COMPLETED_REQUEST_CHANGED")
                if item.get("status") not in {"completed", "failed"}:
                    raise ValueError("NATIVE_TOOL_RESULT_UNOBSERVED")
                failed = item["status"] == "failed" or item.get("error") is not None
                result = item.get("result")
                if not failed and not isinstance(result, dict):
                    raise ValueError("NATIVE_TOOL_RESULT_UNOBSERVED")
                content = result.get("content") if isinstance(result, dict) else None
            else:
                if message["type"] != "user" or type(item.get("is_error", False)) is not bool:
                    raise ValueError("NATIVE_TOOL_ROLE_MISMATCH")
                failed, content = item.get("is_error", False), item.get("content")
            completed[action] = {**call, "failed": failed, "content": content,
                                 "result_event_digest": event_digest, "result_observed_ns": observed_ns,
                                 "result_event_index": event_index}
    if started.keys() != completed.keys():
        raise ValueError("NATIVE_TOOL_RESULT_UNOBSERVED")
    return [call for call in completed.values() if not call["failed"]]


def observed_model_identity(record: dict, *, backend: Literal["claude", "codex"]) -> str | None:
    """Return a single unchanged observed model, otherwise leave its identity unknown."""
    identity = record.get("identity")
    if not isinstance(identity, dict):
        return None
    resolved = identity if backend == "claude" else identity.get("resolved")
    if not isinstance(resolved, dict):
        return None
    model = resolved.get("model")
    events = record.get("protocol_events")
    if not isinstance(model, str) or not model or not isinstance(events, (list, tuple)):
        return None
    for observed in events:
        if not isinstance(observed, dict) or not isinstance(observed.get("message"), dict):
            return None
        message = observed["message"]
        if backend == "codex":
            if message.get("method") == "model/rerouted":
                return None
        elif message.get("type") == "assistant":
            assistant = message.get("message")
            if not isinstance(assistant, dict) or ("model" in assistant and assistant["model"] != model):
                return None
        elif message.get("type") == "result":
            usage = message.get("modelUsage")
            if usage is not None and (not isinstance(usage, dict) or any(name != model for name in usage)):
                return None
    return model


def _counts(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        raise _ProtocolError("USAGE_INVALID")
    token_fields = {
        "inputTokens", "outputTokens", "cachedInputTokens", "cacheReadInputTokens",
        "cacheCreationInputTokens", "reasoningOutputTokens", "totalTokens",
        "input_tokens", "output_tokens", "cached_input_tokens", "cache_read_input_tokens",
        "cache_creation_input_tokens", "reasoning_output_tokens", "total_tokens",
    }
    result = {}
    for key in token_fields & value.keys():
        item = value[key]
        if type(item) is not int or item < 0:
            raise _ProtocolError("USAGE_INVALID")
        result[key] = item
    return result


class _Protocol:
    def __init__(self, spec: NativeDriverSpec, prompt: str) -> None:
        self.spec = spec
        self.prompt = prompt
        self.identity: dict = {}
        self.actions: dict[str, None] = {}
        self.approvals: list[dict] = []
        self.events: list[dict] = []
        self.terminal: NativeStatus | None = None
        self.code = "TERMINAL_UNOBSERVED"
        self.structured: dict | None = None
        self.usage: dict = {
            "counters": None, "cost_usd": None, "cost_basis": None,
            "coverage": "unknown", "observations": [],
            "cpu_seconds": None, "peak_rss_bytes": None, "disk_bytes": None,
            "native_internal_retries": None,
        }
        self.pending: dict[int, str] = {}
        self.responses: set[int] = set()
        self.next_id = 1
        self.thread: str | None = None
        self.turn: str | None = None
        self.initialized = False
        self.interrupt_requested = False

    def request(self, method: str, params: dict) -> bytes:
        identity = self.next_id
        self.next_id += 1
        self.pending[identity] = method
        return self.encode({"id": identity, "method": method, "params": params})

    @staticmethod
    def encode(value: dict) -> bytes:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode() + b"\n"

    def initial(self) -> bytes:
        if self.spec.backend == "claude":
            return self.prompt.encode()
        return self.request("initialize", {
            "clientInfo": {"name": "agents_memory_evaluation", "version": "1"},
            "capabilities": None,
        })

    def interrupt(self) -> bytes:
        if self.spec.backend != "codex" or not self.thread or not self.turn:
            return b""
        if self.interrupt_requested:
            return b""
        self.interrupt_requested = True
        return self.request("turn/interrupt", {"threadId": self.thread, "turnId": self.turn})

    def consume(self, raw: bytes) -> bytes:
        try:
            message = decode_json(raw)
        except (ValueError, UnicodeError, RecursionError):
            raise _ProtocolError("PROTOCOL_INVALID") from None
        if len(self.events) >= self.spec.max_events:
            raise _ProtocolError("EVENT_LIMIT")
        self.events.append({"observed_ns": time.monotonic_ns(), "message": message})
        if self.spec.backend == "claude":
            return self._claude(message)
        return self._codex(message)

    def _finish(self, status: NativeStatus, code: str) -> None:
        if self.terminal is not None:
            raise _ProtocolError("DUPLICATE_TERMINAL")
        self.terminal, self.code = status, code

    def _claude(self, message: dict) -> bytes:
        kind = message.get("type")
        session = message.get("session_id")
        if session is not None:
            session = _identifier(session)
            previous = self.identity.get("session_id")
            if previous is not None and session != previous:
                raise _ProtocolError("STALE_GENERATION")
            self.identity["session_id"] = session
        if kind == "system" and message.get("subtype") == "init":
            if self.initialized or not session:
                raise _ProtocolError("IDENTITY_INVALID")
            self.initialized = True
            for key in ("model", "claude_code_version", "permissionMode", "mcp_servers", "tools"):
                self.identity[key] = message.get(key)
        elif kind in {"assistant", "user"}:
            if not self.initialized:
                raise _ProtocolError("IDENTITY_UNOBSERVED")
            content = message.get("message", {}).get("content", [])
            if not isinstance(content, list):
                raise _ProtocolError("CONTENT_INVALID")
            for item in content:
                if not isinstance(item, dict):
                    raise _ProtocolError("CONTENT_INVALID")
                if item.get("type") == "tool_use":
                    self.actions[_identifier(item.get("id"))] = None
                if item.get("type") == "tool_result":
                    identity = _identifier(item.get("tool_use_id"))
                    if identity not in self.actions:
                        raise _ProtocolError("ACTION_UNCORRELATED")
            usage = message.get("message", {}).get("usage")
            if usage is not None:
                self.usage["observations"].append({
                    "message_id": message.get("message", {}).get("id"),
                    "usage": usage, "basis": "partial_message_not_summed",
                })
                self.usage["coverage"] = "partial"
        elif kind in {"control_request", "permission_request"}:
            self.approvals.append(message)
            self.code = "AWAITING_APPROVAL"
        elif kind == "result":
            if not self.initialized:
                raise _ProtocolError("IDENTITY_UNOBSERVED")
            denials = message.get("permission_denials")
            if denials:
                if not isinstance(denials, list):
                    raise _ProtocolError("PERMISSION_INVALID")
                self.approvals.extend(denials)
            totals = message.get("modelUsage")
            if isinstance(totals, dict) and totals:
                per_model = {model: _counts(counters) for model, counters in totals.items()}
                complete_keys = set.intersection(*(set(counters) for counters in per_model.values()))
                self.usage["model_counters"] = per_model
                self.usage["counters"] = {
                    key: sum(counters[key] for counters in per_model.values()) for key in complete_keys
                } or None
                self.usage["basis"] = "terminal_modelUsage_pipeline_totals"
            elif isinstance(message.get("usage"), dict):
                self.usage["counters"] = _counts(message["usage"]) or None
                self.usage["basis"] = "terminal_main_loop_only"
            self.usage["coverage"] = "terminal_reported_not_invoice" if self.usage["counters"] is not None else "unknown"
            cost = message.get("total_cost_usd")
            if type(cost) in {int, float} and math.isfinite(cost) and cost >= 0:
                self.usage["cost_usd"] = cost
                self.usage["cost_basis"] = "native_client_estimate_not_bill"
            structured = message.get("structured_output")
            if isinstance(structured, dict):
                self.structured = structured
            if self.approvals:
                self._finish("blocked", "AWAITING_APPROVAL")
            elif message.get("is_error") is False and message.get("subtype") == "success":
                self._finish("completed", "NATIVE_COMPLETED")
            else:
                self._finish("failed", "NATIVE_RESULT_ERROR")
        return b""

    def _scope(self, params: dict) -> None:
        thread = params.get("threadId")
        turn = params.get("turnId")
        if thread is not None and thread != self.thread:
            raise _ProtocolError("STALE_GENERATION")
        if turn is not None and self.turn is not None and turn != self.turn:
            raise _ProtocolError("STALE_GENERATION")

    def _codex(self, message: dict) -> bytes:
        method = message.get("method")
        if method is None:
            identity = message.get("id")
            if type(identity) is not int or identity not in self.pending or identity in self.responses:
                raise _ProtocolError("RESPONSE_UNCORRELATED")
            self.responses.add(identity)
            request = self.pending.pop(identity)
            if "error" in message:
                self._finish("failed", "NATIVE_RPC_ERROR")
                return b""
            result = message.get("result")
            if not isinstance(result, dict):
                raise _ProtocolError("RESPONSE_INVALID")
            if request == "initialize":
                self.initialized = True
                self.identity["initialize"] = result
                return self.encode({"method": "initialized", "params": {}}) + self.request(
                    "thread/start", {"cwd": str(self.spec.cwd)},
                )
            if request == "thread/start":
                returned = _identifier(result.get("thread", {}).get("id"))
                if self.thread is not None and self.thread != returned:
                    raise _ProtocolError("STALE_GENERATION")
                self.thread = returned
                self.identity.update({"thread_id": self.thread, "resolved": result})
                return self.request("turn/start", {
                    "threadId": self.thread,
                    "input": [{"type": "text", "text": self.prompt}],
                    "outputSchema": _SUBMISSION_SCHEMA,
                })
            if request == "turn/start":
                returned = _identifier(result.get("turn", {}).get("id"))
                if self.turn is not None and returned != self.turn:
                    raise _ProtocolError("STALE_GENERATION")
                self.turn = returned
                self.identity["turn_id"] = returned
            if request == "turn/interrupt":
                self.identity["interrupt_acknowledged"] = True
            return b""
        params = message.get("params", {})
        if not isinstance(method, str) or not isinstance(params, dict):
            raise _ProtocolError("NOTIFICATION_INVALID")
        if method == "thread/started":
            returned = _identifier(params.get("thread", {}).get("id"))
            if self.thread is not None and returned != self.thread:
                raise _ProtocolError("STALE_GENERATION")
            self.thread = returned
        self._scope(params)
        if "id" in message:
            # Server requests need a human/native responder; never send an approval response.
            self.approvals.append(message)
            self.code = "AWAITING_APPROVAL"
            return b""
        if method == "turn/started":
            returned = _identifier(params.get("turn", {}).get("id"))
            if self.turn is not None and returned != self.turn:
                raise _ProtocolError("STALE_GENERATION")
            self.turn = returned
            self.identity["turn_id"] = returned
        elif method in {"item/started", "item/completed"}:
            item = params.get("item")
            if not isinstance(item, dict):
                raise _ProtocolError("ITEM_INVALID")
            self.actions[_identifier(item.get("id"))] = None
            if method == "item/completed" and item.get("type") == "agentMessage":
                text = item.get("text")
                if isinstance(text, str):
                    try:
                        self.structured = decode_json(text.encode())
                    except (ValueError, UnicodeError):
                        pass
        elif method == "thread/tokenUsage/updated":
            usage = params.get("tokenUsage")
            if not isinstance(usage, dict):
                raise _ProtocolError("USAGE_INVALID")
            counts = _counts(usage.get("total"))
            previous = self.usage["counters"]
            if previous is not None and any(counts.get(key, -1) < value for key, value in previous.items()):
                raise _ProtocolError("USAGE_REGRESSION")
            self.usage["counters"] = counts or None
            self.usage["coverage"] = "partial"
            self.usage["basis"] = "latest_fresh_thread_cumulative_total_not_sum"
            self.usage["observations"].append(usage)
        elif method == "turn/completed":
            turn = params.get("turn")
            if not isinstance(turn, dict) or self.turn is None or turn.get("id") != self.turn:
                raise _ProtocolError("STALE_GENERATION")
            status = turn.get("status")
            if status == "completed":
                self._finish("blocked" if self.approvals else "completed",
                             "AWAITING_APPROVAL" if self.approvals else "NATIVE_COMPLETED")
            elif status == "interrupted":
                self._finish("blocked" if self.approvals else "aborted", "NATIVE_INTERRUPTED")
            elif status == "failed":
                self._finish("failed", "NATIVE_TURN_FAILED")
            else:
                raise _ProtocolError("TERMINAL_INVALID")
            if self.usage["counters"] is not None:
                self.usage["coverage"] = "last_observed_cumulative_terminal_delivery_unverified"
        return b""


_SUBMISSION_SCHEMA = {
    "type": "object", "properties": {"submission_path": {"type": "string"}},
    "required": ["submission_path"], "additionalProperties": False,
}


def _argv(spec: NativeDriverSpec) -> list[str]:
    if spec.backend == "codex":
        return [str(spec.executable), "app-server"]
    return [
        str(spec.executable), "-p", "--output-format", "stream-json", "--verbose",
        "--json-schema", json.dumps(_SUBMISSION_SCHEMA, separators=(",", ":")),
    ]


def _open_task_directory(path: Path, *, expected: int | None = None) -> int:
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        if expected is not None:
            pinned, current = os.fstat(expected), os.fstat(descriptor)
            if (pinned.st_dev, pinned.st_ino) != (current.st_dev, current.st_ino):
                raise _ProtocolError("SUBMISSION_ROOT_CHANGED")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _publish_submission(spec: NativeDriverSpec, output: Path, protocol: _Protocol, task_directory: int) -> dict:
    if protocol.structured != {"submission_path": str(spec.submission_path)}:
        raise _ProtocolError("SUBMISSION_REFERENCE_INVALID")
    # These bytes, not a recursive view of the still-untrusted workspace, define the artifact.
    parent = _open_task_directory(spec.cwd, expected=task_directory)
    try:
        parts = spec.submission_path.relative_to(spec.cwd).parts
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
        raw = private_read(Path(parts[-1]), spec.max_submission_bytes, private=False, directory=parent)
        os.close(_open_task_directory(spec.cwd, expected=task_directory))
    finally:
        os.close(parent)
    directory = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(directory)
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise _ProtocolError("CONTROLLER_OUTPUT_NOT_PRIVATE")
        try:
            private_write(output, raw, directory=directory)
        except (OSError, DomainError):
            descriptor = os.open(output.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            try:
                published = os.fstat(descriptor)
                if (not stat.S_ISREG(published.st_mode) or published.st_uid != os.getuid()
                        or published.st_mode & 0o077 or published.st_size != len(raw)):
                    raise _ProtocolError("ARTIFACT_PUBLICATION_CONFLICT")
                with os.fdopen(descriptor, "rb", closefd=False) as stream:
                    if stream.read(len(raw) + 1) != raw:
                        raise _ProtocolError("ARTIFACT_PUBLICATION_CONFLICT")
                os.fsync(directory)
            finally:
                os.close(descriptor)
    finally:
        os.close(directory)
    return {"path": str(output), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def run_native_arm(
    spec: NativeDriverSpec, task_prompt: str, *, invocation_id: str,
    artifact_output: Path, trace_sink: TraceSink, stop_event: threading.Event | None = None,
) -> NativeArmResult:
    started = time.monotonic_ns()
    protocol = _Protocol(spec, task_prompt)
    stdout, stderr, partial = bytearray(), bytearray(), bytearray()
    status: NativeStatus = "unknown"
    code = "TERMINAL_UNOBSERVED"
    effect: Literal["not_started", "unknown"] = "not_started"
    truncated = False
    cleanup = {"leader_reaped": False, "group_signals_completed": False, "escaped_descendants_absent": None}
    stop: dict = {"requested": False, "interrupt_queued": False, "interrupt_sent": False,
                  "interrupted_terminal": False}
    artifact = None
    process: subprocess.Popen[bytes] | None = None
    task_directory = None
    reasons = []
    for observed, reason in (
        (spec.exclusive_optional_route_observed, "ALTERNATIVE_OPTIONAL_ROUTE_UNRESOLVED"),
        (spec.residual_memory_absence_observed, "NATIVE_MEMORY_RESIDUAL_UNRESOLVED"),
        (spec.fresh_generation_observed, "FRESH_GENERATION_UNOBSERVED"),
    ):
        if not observed:
            reasons.append(reason)
    if not spec.authorization_ref or not spec.context_observation_ref or not spec.approved_context:
        status, code = "blocked", "APPROVED_NORMAL_CONTEXT_REQUIRED"
    elif spec.gateway_invocation_id != invocation_id or not spec.gateway_route_ref:
        status, code = "blocked", "APPROVED_INVOCATION_ROUTE_REQUIRED"
    elif spec.strict_protection_required and not spec.strict_protection_supported:
        status, code = "unsupported", "STRICT_NATIVE_CAPABILITY_UNSUPPORTED"
    elif os.name != "posix":
        status, code = "unsupported", "NATIVE_PROCESS_OWNERSHIP_UNSUPPORTED"
    elif len(task_prompt.encode()) > spec.max_input_bytes:
        status, code = "blocked", "INPUT_LIMIT"
    elif stop_event is not None and stop_event.is_set():
        status, code = "aborted", "STOP_REQUESTED_BEFORE_SPAWN"
    else:
        try:
            task_directory = _open_task_directory(spec.cwd)
            trace_sink({"stage": "native_intent", "invocation_id": invocation_id,
                        "observed_ns": started, "backend": spec.backend,
                        "authorization_ref": spec.authorization_ref})
            if not spec.executable.is_file() or not os.access(spec.executable, os.X_OK):
                raise _ProtocolError("EXECUTABLE_UNAVAILABLE")
            if spec.submission_path.exists() or spec.submission_path.is_symlink():
                raise _ProtocolError("SUBMISSION_ALREADY_EXISTS")
            if not artifact_output.is_absolute() or artifact_output.is_relative_to(spec.cwd):
                raise _ProtocolError("CONTROLLER_OUTPUT_SCOPE_REQUIRED")
            if artifact_output.exists() or artifact_output.is_symlink():
                raise _ProtocolError("ARTIFACT_OUTPUT_ALREADY_EXISTS")
            process = subprocess.Popen(
                _argv(spec), cwd=spec.cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, start_new_session=True,
            )
            effect = "unknown"
            assert process.stdin is not None and process.stdout is not None and process.stderr is not None
            deadline = time.monotonic() + spec.timeout_seconds
            pending = bytearray(protocol.initial())
            sent = 0
            frame_partial = False
            stopping = False
            group_gone = False
            terminal_deadline: float | None = None
            with selectors.DefaultSelector() as selector:
                for stream, name in ((process.stdout, "stdout"), (process.stderr, "stderr")):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ, name)
                os.set_blocking(process.stdin.fileno(), False)
                selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")

                def stop_owned() -> None:
                    nonlocal stopping, terminal_deadline, pending, code, status, group_gone
                    if stopping:
                        return
                    stopping = True
                    stop["requested"] = True
                    terminal_deadline = time.monotonic() + spec.cleanup_seconds
                    pending.clear()
                    interrupt = b"" if frame_partial or process.stdin.closed else protocol.interrupt()
                    if interrupt:
                        pending.extend(interrupt)
                        stop["interrupt_queued"] = True
                        try:
                            selector.get_key(process.stdin)
                        except KeyError:
                            selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
                    else:
                        if not process.stdin.closed:
                            try:
                                selector.unregister(process.stdin)
                            except KeyError:
                                pass
                            process.stdin.close()
                        group_gone = not _signal_process_group(process, signal.SIGTERM)

                def consume_stdout(chunk: bytes, *, dispatch: bool) -> None:
                    partial.extend(chunk)
                    while b"\n" in partial:
                        line, _, rest = partial.partition(b"\n")
                        partial[:] = rest
                        if len(line) > spec.max_record_bytes:
                            raise _ProtocolError("RECORD_LIMIT")
                        if not line:
                            continue
                        outgoing = protocol.consume(bytes(line))
                        trace_sink({"stage": "native_event", "invocation_id": invocation_id,
                                    "observed_ns": protocol.events[-1]["observed_ns"],
                                    "event_index": len(protocol.events) - 1})
                        if outgoing and dispatch and not stopping:
                            pending.extend(outgoing)
                            if len(pending) > spec.max_input_bytes + spec.max_record_bytes * 8:
                                raise _ProtocolError("PROTOCOL_INPUT_LIMIT")
                            try:
                                selector.get_key(process.stdin)
                            except KeyError:
                                selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
                    if len(partial) > spec.max_record_bytes:
                        raise _ProtocolError("RECORD_LIMIT")

                try:
                    while True:
                        now = time.monotonic()
                        if stop_event is not None and stop_event.is_set() and not stopping:
                            status, code = "aborted", "STOP_REQUESTED"
                            stop_owned()
                        if now >= deadline and not stopping and protocol.terminal is None:
                            status, code = "timeout", "NATIVE_DEADLINE"
                            stop_owned()
                        if protocol.approvals and not stopping:
                            status, code = "blocked", "AWAITING_APPROVAL"
                            stop_owned()
                        if protocol.terminal is not None and terminal_deadline is None:
                            status, code = protocol.terminal, protocol.code
                            terminal_deadline = now + spec.cleanup_seconds
                            if spec.backend == "codex":
                                try:
                                    selector.unregister(process.stdin)
                                except KeyError:
                                    pass
                                process.stdin.close()
                        if terminal_deadline is not None and now >= terminal_deadline:
                            break
                        read_names = {key.data for key in selector.get_map().values() if key.data != "stdin"}
                        if not read_names:
                            break
                        for key, _ in selector.select(min(0.05, max(0, (terminal_deadline or deadline) - now))):
                            if key.data == "stdin":
                                if stop_event is not None and stop_event.is_set() and not stopping:
                                    status, code = "aborted", "STOP_REQUESTED"
                                    stop_owned()
                                if process.stdin.closed:
                                    continue
                                if pending:
                                    count = os.write(key.fd, pending[:65536])
                                    if count:
                                        frame_partial = pending[count - 1] != ord("\n")
                                    sent += count
                                    if sent > spec.max_input_bytes + spec.max_record_bytes * 8:
                                        raise _ProtocolError("PROTOCOL_INPUT_LIMIT")
                                    del pending[:count]
                                if not pending:
                                    if stop["interrupt_queued"]:
                                        stop["interrupt_sent"] = True
                                    selector.unregister(key.fileobj)
                                    if spec.backend == "claude":
                                        process.stdin.close()
                                continue
                            chunk = os.read(key.fd, 65536)
                            if not chunk:
                                selector.unregister(key.fileobj)
                                if key.data == "stdout" and partial:
                                    raise _ProtocolError("PARTIAL_PROTOCOL_RECORD")
                                continue
                            target = stdout if key.data == "stdout" else stderr
                            maximum = spec.max_stdout_bytes if key.data == "stdout" else spec.max_stderr_bytes
                            available = max(0, maximum - len(target))
                            target.extend(chunk[:available])
                            if len(chunk) > available:
                                truncated = True
                                raise _ProtocolError("OUTPUT_LIMIT")
                            if key.data == "stdout":
                                consume_stdout(chunk, dispatch=True)
                    if protocol.terminal is not None and status == "unknown":
                        status, code = protocol.terminal, protocol.code
                    stop["interrupted_terminal"] = protocol.code == "NATIVE_INTERRUPTED"
                finally:
                    # No poll/wait before the final group signal: the unreaped leader pins identity.
                    try:
                        if not group_gone:
                            group_gone = not _signal_process_group(process, signal.SIGTERM)
                        if not group_gone:
                            _signal_process_group(process, signal.SIGKILL)
                        cleanup["group_signals_completed"] = True
                        drain_deadline = time.monotonic() + spec.cleanup_seconds
                        while time.monotonic() < drain_deadline:
                            readers = [key for key in selector.get_map().values() if key.data != "stdin"]
                            if not readers:
                                break
                            for key, _ in selector.select(min(0.05, max(0, drain_deadline - time.monotonic()))):
                                if key.data == "stdin":
                                    selector.unregister(key.fileobj)
                                    continue
                                chunk = os.read(key.fd, 65536)
                                if not chunk:
                                    selector.unregister(key.fileobj)
                                    continue
                                target = stdout if key.data == "stdout" else stderr
                                maximum = spec.max_stdout_bytes if key.data == "stdout" else spec.max_stderr_bytes
                                available = max(0, maximum - len(target))
                                target.extend(chunk[:available])
                                if len(chunk) > available:
                                    truncated = True
                                    if status == "completed":
                                        status, code = "unknown", "OUTPUT_LIMIT_DURING_CLEANUP"
                                if key.data == "stdout" and "protocol_error" not in cleanup:
                                    try:
                                        consume_stdout(chunk[:available], dispatch=False)
                                    except Exception as error:
                                        cleanup["protocol_error"] = (
                                            str(error) if isinstance(error, _ProtocolError)
                                            else "NATIVE_PROTOCOL_OR_OBSERVATION_FAILED"
                                        )
                                        if status == "completed":
                                            status, code = "unknown", cleanup["protocol_error"]
                        if partial:
                            cleanup["partial_protocol_record"] = True
                            if status == "completed":
                                status, code = "unknown", "PARTIAL_PROTOCOL_RECORD"
                    finally:
                        try:
                            process.wait(timeout=spec.cleanup_seconds)
                            cleanup["leader_reaped"] = True
                        except subprocess.TimeoutExpired:
                            cleanup["leader_reaped"] = False
                        for stream in (process.stdin, process.stdout, process.stderr):
                            if not stream.closed:
                                stream.close()
            if status == "completed" and spec.backend == "claude" and process.returncode != 0:
                status, code = "failed", "NATIVE_EXIT_NONZERO"
            if status == "completed":
                artifact = _publish_submission(spec, artifact_output, protocol, task_directory)
        except _ProtocolError as error:
            status, code = "unknown" if process is not None else "blocked", str(error)
        except OSError as error:
            if process is None and error.errno in {errno.EAGAIN, errno.EBUSY}:
                status, code = "busy", "NATIVE_SPAWN_BUSY"
            else:
                status, code = "unknown" if process is not None else "failed", "NATIVE_IO_OR_PUBLICATION_FAILED"
        except Exception:
            status, code = "unknown" if process is not None else "failed", "NATIVE_PROTOCOL_OR_OBSERVATION_FAILED"
        finally:
            try:
                if process is not None and process.returncode is None:
                    try:
                        if not cleanup["group_signals_completed"]:
                            if _signal_process_group(process, signal.SIGTERM):
                                _signal_process_group(process, signal.SIGKILL)
                            cleanup["group_signals_completed"] = True
                        process.wait(timeout=spec.cleanup_seconds)
                        cleanup["leader_reaped"] = True
                    except (OSError, subprocess.SubprocessError):
                        cleanup["leader_reaped"] = False
                    finally:
                        for stream in (process.stdin, process.stdout, process.stderr):
                            if stream is not None and not stream.closed:
                                stream.close()
            finally:
                if task_directory is not None:
                    os.close(task_directory)
    if not cleanup["leader_reaped"] and process is not None:
        status, code = "unknown", "NATIVE_CLEANUP_UNRESOLVED"
    observed_model = protocol.identity.get("model")
    observed_version = protocol.identity.get("claude_code_version")
    if spec.backend == "codex":
        observed_model = protocol.identity.get("resolved", {}).get("model")
        observed_version = protocol.identity.get("initialize", {}).get("userAgent")
    if (isinstance(observed_model, str) and observed_model
            and observed_model_identity(
                {"identity": protocol.identity, "protocol_events": protocol.events}, backend=spec.backend,
            ) is None):
        reasons.append("MODEL_IDENTITY_CHANGED_OR_UNKNOWN")
    if not isinstance(observed_model, str) or not observed_model:
        reasons.append("MODEL_IDENTITY_UNOBSERVED")
    if not isinstance(observed_version, str) or not observed_version:
        reasons.append("VERSION_IDENTITY_UNOBSERVED")
    if spec.expected_model is not None and spec.expected_model != observed_model:
        reasons.append("MODEL_IDENTITY_MISMATCH_OR_UNKNOWN")
    if spec.expected_version is not None and spec.expected_version != observed_version:
        reasons.append("VERSION_IDENTITY_MISMATCH_OR_UNKNOWN")
    finished = time.monotonic_ns()
    try:
        trace_sink({"stage": "native_terminal", "invocation_id": invocation_id, "status": status,
                    "code": code, "observed_ns": finished, "effect": effect})
    except Exception:
        status, code = "unknown" if process is not None else "failed", "NATIVE_OBSERVATION_FAILED"
    return NativeArmResult(
        invocation_id, status, code, started, finished,
        process.returncode if process is not None else None, effect, bytes(stdout), bytes(stderr),
        truncated, tuple(protocol.events), protocol.usage, protocol.identity,
        tuple(protocol.actions), tuple(protocol.approvals), stop, cleanup, artifact,
        status == "completed" and not reasons, tuple(reasons),
    )
