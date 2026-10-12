from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager

from mcp.server.lowlevel import Server
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool
from pydantic import Field, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .application import Application
from .config import Settings
from .domain import (
    CaptureCommand,
    ContextCommand,
    DomainError,
    EffectState,
    FeedbackCommand,
    Handle,
    Principal,
    RecordCommand,
    Role,
    TypedModel,
)
from .jobs import Worker
from .journal import DeletionJournal
from .models import LocalSemanticRuntime
from .store import Store
from .wire import decode_json, validate_wire


class InspectCommand(TypedModel):
    ref: Handle
    binding_id: Handle | None = None
    snapshot: str | None = Field(default=None, min_length=1, max_length=512)


class CorrectCommand(TypedModel):
    target_ref: Handle
    source: CaptureCommand


SCHEMAS = {
    "memory_context": ContextCommand,
    "memory_inspect": InspectCommand,
    "memory_record": RecordCommand,
    "memory_feedback": FeedbackCommand,
}
DESCRIPTIONS = {
    "memory_context": "Recall bounded cited candidates; explicit reflect queues grounded reasoning. Not execution authority.",
    "memory_inspect": "Inspect the current scoped item or durable operation. Retracted text is unavailable.",
    "memory_record": "Durably record an agent note or inactive rule candidate with an explicit retry key.",
    "memory_feedback": "Record correction, rejection or retract-request candidates. Never approve or purge.",
}


def command_from_wire[Model: TypedModel](model: type[Model], value: object) -> Model:
    try:
        return validate_wire(model, value)
    except (ValidationError, ValueError, TypeError):
        raise DomainError("INPUT_INVALID", "Arguments do not match the complete strict schema", status=400) from None


async def actor_from_scope(application: Application, scope: dict, roles: tuple[Role, ...]) -> Principal:
    token = scope.get("agents_memory_token")
    if not isinstance(token, str):
        raise DomainError("UNAUTHORIZED", "A current credential is required", status=401)
    return await application.store.authenticate(token, roles)


def error_response(error: DomainError) -> JSONResponse:
    return JSONResponse({"error": error.public()}, status_code=error.status)


def tool_error(error: DomainError) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps({"error": error.public()}, separators=(",", ":")))],
        isError=True,
    )


class SecurityEdge:
    def __init__(self, inner, application: Application, settings: Settings) -> None:
        self.inner = inner
        self.application = application
        self.settings = settings
        self.sessions: dict[str, tuple[str, float]] = {}

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.inner(scope, receive, send)
            return
        headers: dict[bytes, bytes] = {}
        for key, value in scope.get("headers", ()):
            key = key.lower()
            if key in headers and key in {
                b"authorization", b"host", b"origin", b"content-length", b"mcp-session-id",
                b"mcp-protocol-version", b"mcp-method", b"mcp-name",
            }:
                await error_response(DomainError("HEADERS_INVALID", "Duplicate security header", status=400))(scope, receive, send)
                return
            headers[key] = value
        hosts = {f"127.0.0.1:{self.settings.port}".encode(), f"localhost:{self.settings.port}".encode()}
        origins = {b"http://" + host for host in hosts}
        if headers.get(b"host") not in hosts or (b"origin" in headers and headers[b"origin"] not in origins):
            await error_response(DomainError("HOST_ORIGIN_DENIED", "Host or Origin is not permitted", status=403))(scope, receive, send)
            return
        path = scope.get("path", "")
        if path == "/healthz":
            await JSONResponse({"alive": True})(scope, receive, send)
            return
        auth = headers.get(b"authorization", b"")
        try:
            if not auth.startswith(b"Bearer "):
                raise DomainError("UNAUTHORIZED", "Bearer authentication is required", status=401)
            token = auth[7:].decode("ascii")
            if not token or len(token) > 512 or any(character.isspace() for character in token):
                raise DomainError("UNAUTHORIZED", "The bearer credential is invalid", status=401)
            actor = await self.application.store.authenticate(token)
            if path == "/mcp" and actor.role != Role.AGENT:
                raise DomainError("ROLE_DENIED", "Only the agent credential can use MCP", status=403)
            session = headers.get(b"mcp-session-id", b"").decode("ascii")
            now = time.monotonic()
            self.sessions = {sid: entry for sid, entry in self.sessions.items() if now - entry[1] <= 600}
            if session:
                entry = self.sessions.get(session)
                if entry is None or entry[0] != actor.credential_id:
                    raise DomainError("SESSION_CREDENTIAL_DENIED", "The protocol session is not bound to this credential", status=403)
                self.sessions[session] = (actor.credential_id, now)
            if scope["method"] == "POST":
                body = bytearray()
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    body.extend(message.get("body", b""))
                    if len(body) > self.settings.max_http_body_bytes:
                        raise DomainError("INPUT_TOO_LARGE", "The HTTP body exceeds its limit", status=413)
                    if not message.get("more_body", False):
                        break
                try:
                    decoded = decode_json(bytes(body))
                except (ValueError, UnicodeError, RecursionError):
                    raise DomainError("INPUT_INVALID", "The request is not bounded valid UTF-8 JSON", status=400) from None
                scope["agents_memory_json"] = decoded
                if path == "/mcp":
                    request_id = decoded.get("id")
                    if request_id is not None and (
                        isinstance(request_id, bool)
                        or not isinstance(request_id, (str, int))
                        or (isinstance(request_id, str) and len(request_id.encode("utf-8")) > 256)
                        or (isinstance(request_id, int) and abs(request_id) > 2**53 - 1)
                    ):
                        raise DomainError("INPUT_INVALID", "The JSON-RPC request id exceeds its safe bound", status=400)
                original_receive = receive
                delivered = False

                async def replay():
                    nonlocal delivered
                    if not delivered:
                        delivered = True
                        return {"type": "http.request", "body": bytes(body), "more_body": False}
                    return await original_receive()

                receive = replay
            scope["agents_memory_token"] = token
        except DomainError as error:
            await error_response(error)(scope, receive, send)
            return
        except (UnicodeError, ValueError):
            await error_response(DomainError("INPUT_INVALID", "The security envelope is invalid", status=400))(scope, receive, send)
            return
        except Exception:
            await error_response(DomainError("AUTHORITY_UNAVAILABLE", "The authority is unavailable", status=503))(scope, receive, send)
            return

        response_start = None
        response_body = bytearray()
        overflow = False
        bounded_response = path == "/mcp" and scope["method"] == "POST"

        async def forward_start(message):
            response_headers = dict(message.get("headers", ()))
            sid = response_headers.get(b"mcp-session-id")
            if sid is not None and message["status"] < 400:
                if sid.decode("ascii") not in self.sessions and len(self.sessions) >= 64:
                    self.sessions.pop(min(self.sessions, key=lambda key: self.sessions[key][1]))
                self.sessions[sid.decode("ascii")] = (actor.credential_id, time.monotonic())
            if session and scope["method"] == "DELETE" and message["status"] < 400:
                self.sessions.pop(session, None)
            await send(message)

        async def bound_send(message):
            nonlocal response_start, overflow
            if not bounded_response:
                if message["type"] == "http.response.start":
                    await forward_start(message)
                else:
                    await send(message)
                return
            if message["type"] == "http.response.start":
                response_start = message
                return
            if message["type"] != "http.response.body" or overflow:
                return
            chunk = message.get("body", b"")
            if len(response_body) + len(chunk) > self.settings.max_mcp_response_bytes:
                overflow = True
                request = scope.get("agents_memory_json", {})
                params = request.get("params")
                mutating = isinstance(params, dict) and (
                    params.get("name") in {"memory_record", "memory_feedback"}
                    or (isinstance(params.get("arguments"), dict) and params["arguments"].get("mode") == "reflect")
                )
                effect = scope.get(
                    "agents_memory_effect", EffectState.UNKNOWN if mutating else EffectState.NOT_STARTED
                )
                payload = json.dumps({
                    "jsonrpc": "2.0", "id": request.get("id"),
                    "error": {"code": -32000, "message": "RESULT_TOO_LARGE", "data": {"effect": str(effect)}},
                }, separators=(",", ":")).encode("utf-8")
                await send({
                    "type": "http.response.start", "status": 502,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode())],
                })
                await send({"type": "http.response.body", "body": payload, "more_body": False})
                response_body.clear()
                return
            response_body.extend(chunk)
            if not message.get("more_body", False):
                await forward_start(response_start)
                await send({"type": "http.response.body", "body": bytes(response_body), "more_body": False})

        self.application.inflight += 1
        try:
            await self.inner(scope, receive, bound_send)
        finally:
            self.application.inflight -= 1


def create_app(settings: Settings):
    journal = DeletionJournal(settings.journal_dir, settings.deployment_id)
    store = Store(settings, journal)
    runtime = None
    model_error = "MODEL_ROUTE_BLOCKED"
    if settings.allowed_model_purposes:
        try:
            runtime = LocalSemanticRuntime(settings.models)
            model_error = None
        except DomainError as error:
            model_error = error.code
    application = Application(settings, store, runtime)
    worker = Worker(application)

    async def list_tools(context, params):
        if context.request is None:
            raise DomainError("UNAUTHORIZED", "HTTP request authentication is required", status=401)
        await actor_from_scope(application, context.request.scope, (Role.AGENT,))
        return ListToolsResult(tools=[
            Tool(name=name, description=DESCRIPTIONS[name], inputSchema=model.model_json_schema())
            for name, model in SCHEMAS.items()
        ])

    async def call_tool(context, params):
        mutating = params.name in {"memory_record", "memory_feedback"} or (params.arguments or {}).get("mode") == "reflect"
        try:
            if context.request is None:
                raise DomainError("UNAUTHORIZED", "HTTP request authentication is required", status=401)
            actor = await actor_from_scope(application, context.request.scope, (Role.AGENT,))
            model = SCHEMAS.get(params.name)
            if model is None:
                raise DomainError("TOOL_UNKNOWN", "The requested tool is not available", status=404)
            command = command_from_wire(model, params.arguments or {})
            if params.name == "memory_context":
                result = await application.context(actor, command)
            elif params.name == "memory_inspect":
                result = await application.inspect(actor, command.ref, command.binding_id, command.snapshot)
            elif params.name == "memory_record":
                result = await application.record(actor, command)
            else:
                result = await application.feedback(actor, command)
            if mutating:
                context.request.scope["agents_memory_effect"] = EffectState.COMMITTED
            result = dict(result)
            stamp = result.pop("stamp", None)
            text = json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            response = CallToolResult(content=[TextContent(type="text", text=text)], meta={"agents-memory/stamp": stamp} if stamp else None)
            return response
        except DomainError as error:
            return tool_error(error)
        except Exception:
            return tool_error(DomainError(
                "INTERNAL_ERROR", "The tool failed; reconcile durable mutations", status=500,
                effect=context.request.scope.get("agents_memory_effect", EffectState.UNKNOWN)
                if mutating and context.request is not None else EffectState.NOT_STARTED,
            ))

    async def api(request: Request):
        name = request.path_params["action"]
        try:
            roles = (Role.PRODUCER, Role.OPERATOR) if name in {"capture", "correct"} else (Role.AGENT, Role.OPERATOR)
            actor = await actor_from_scope(application, request.scope, roles)
            data = request.scope.get("agents_memory_json", {})
            if name == "context":
                return JSONResponse(await application.context(actor, command_from_wire(ContextCommand, data)))
            if name == "required-context":
                return JSONResponse(await application.required_context(actor, command_from_wire(ContextCommand, data)))
            if name == "inspect":
                command = command_from_wire(InspectCommand, data)
                return JSONResponse(await application.inspect(actor, command.ref, command.binding_id, command.snapshot))
            if name == "record":
                return JSONResponse(await application.record(actor, command_from_wire(RecordCommand, data)))
            if name == "feedback":
                return JSONResponse(await application.feedback(actor, command_from_wire(FeedbackCommand, data)))
            if name == "capture":
                application.require_accepting()
                operation = await store.capture(actor, command_from_wire(CaptureCommand, data))
                return JSONResponse(operation.model_dump(mode="json"), status_code=202)
            if name == "correct":
                application.require_accepting()
                command = command_from_wire(CorrectCommand, data)
                operation = await store.correct(actor, command.source.binding_id, command.target_ref, command.source)
                return JSONResponse(operation.model_dump(mode="json"), status_code=202)
            raise DomainError("ACTION_UNKNOWN", "The producer action is not available", status=404)
        except DomainError as error:
            return error_response(error)
        except Exception:
            return error_response(DomainError("INTERNAL_ERROR", "The action failed; reconcile durable mutations", status=500, effect=EffectState.UNKNOWN))

    async def readiness(request):
        try:
            await actor_from_scope(application, request.scope, (Role.OPERATOR,))
        except DomainError as error:
            return error_response(error)
        return JSONResponse({
            "authority": "connected",
            "models": "artifacts_verified" if application.runtime is not None else "blocked",
            "model_error": model_error,
            "worker": worker.status,
            "accepting": application.accepting,
            "native_hook_trust": "not_attested_by_service",
        })

    server = Server(
        "agents-memory",
        version="0.1.0",
        instructions="",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
        get_tool_input_schema=lambda name: SCHEMAS[name].model_json_schema() if name in SCHEMAS else None,
    )
    inner = server.streamable_http_app(
        json_response=True,
        stateless_http=False,
        max_request_body_size=settings.max_http_body_bytes,
        session_idle_timeout=300,
        max_sessions=64,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[f"127.0.0.1:{settings.port}", f"localhost:{settings.port}"],
            allowed_origins=[settings.base_url, f"http://localhost:{settings.port}"],
        ),
        custom_starlette_routes=[
            Route("/api/{action}", api, methods=["POST"]),
            Route("/readyz", readiness, methods=["GET"]),
        ],
    )
    sdk_lifespan = inner.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app):
        from .ops import authority_lock

        nonlocal model_error
        with authority_lock(settings):
            await store.open()
            try:
                await store.reconcile_journal()
                if runtime is not None:
                    try:
                        await asyncio.to_thread(runtime.validate_artifacts)
                    except DomainError as error:
                        model_error = error.code
                        application.runtime = None
                async with sdk_lifespan(app) as state:
                    worker.start()
                    try:
                        yield state
                    finally:
                        application.accepting = False
                        await worker.stop()
                        await application.drain()
            finally:
                await store.close()

    inner.router.lifespan_context = lifespan
    edge = SecurityEdge(inner, application, settings)
    edge.application = application
    edge.worker = worker
    return edge
