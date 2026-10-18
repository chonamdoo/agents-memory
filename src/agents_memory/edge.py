from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.lowlevel import Server
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool
from pydantic import Field, TypeAdapter, ValidationError, field_validator, model_validator
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .application import Application
from .config import Settings
from .domain import (
    CaptureCommand,
    ContextCommand,
    CorrectCommand,
    DomainError,
    EffectState,
    FeedbackCommand,
    Handle,
    Principal,
    Role,
    TypedModel,
    reject_source_secrets,
)
from .health import HEALTH_ADAPTER, HealthObserverRequest
from .ingress import (
    OAUTH_METADATA_PATH,
    ClientBootstrapBounds,
    ClientBootstrapRequest,
    ClientBootstrapResult,
    CloudIngressProfile,
    OAuthVerifier,
    VerifiedOAuthIdentity,
    load_ingress,
    public_request,
)
from .jobs import CleanupScheduler
from .journal import DeletionJournal
from .judge import describe, load_state
from .judge_worker import JudgeWorker
from .recovery import SpoolRecovery
from .selection import RECORD_ADAPTER
from .store import Store
from .wire import decode_json, validate_wire

HTTP_BODY_SECONDS = 15.0


class InspectCommand(TypedModel):
    ref: str = Field(min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_.:-]+$")
    binding_id: Handle | None = None
    snapshot: str | None = Field(default=None, min_length=1, max_length=512)
    byte_start: int = Field(default=0, ge=0, le=9223372036854775807)
    max_bytes: int = Field(default=4096, ge=1, le=4096)
    claim_ids: tuple[Handle, ...] | None = Field(default=None, min_length=1, max_length=20)
    rejection_cursor: Handle | None = None

    @field_validator("snapshot")
    @classmethod
    def secret_free_snapshot(cls, value: str | None) -> str | None:
        if value is not None:
            reject_source_secrets(value)
        return value

    @model_validator(mode="after")
    def selected_judgment_claims(self) -> InspectCommand:
        if self.claim_ids is not None and (
            self.ref != "judgment" or len(set(self.claim_ids)) != len(self.claim_ids)
        ):
            raise ValueError("Choose unique claim IDs only for judgment inspection")
        return self


SCHEMAS = {
    "memory_context": ContextCommand,
    "memory_inspect": InspectCommand,
    "memory_record": RECORD_ADAPTER,
    "memory_feedback": FeedbackCommand,
}
DESCRIPTIONS = {
    "memory_context": "Query candidates with expansions, inspect, then judge relevance for the complete saved manifest. Only agent-judged memory enters context; required rules are independent.",
    "memory_inspect": "Read sources, claims, judgments, records and health work; never execution authority. judgment: unique claim_ids, no byte windows. required_rejection_ids index prior decisions, not meaning verdicts; optional rejection_cursor=history follows rejections_next_cursor even on empty pages. Join draft_window.body via next_byte, verify digest then decode UTF-8; stored_record omits live epoch. judgment_context_refs identify live inputs; every page rechecks eligibility. judge: read-only agent/opt-in Jev metadata. health lists work; health:item:<pending_id> admits evidence/coverage; health:claim:<id> is history, not reuse authority. Follow continuation.",
    "memory_record": "source_selection/remember must include extraction atomically; no later extension. Preserve original spans, qualifications and validity. Judge all required_rejection_ids (unrelated/reopen); rejection_review_ids are optional. Reopen needs new independent human/tool/document evidence. Overlapping complete remember/discard has one winner (SELECTION_ALREADY_RECORDED). Unknown outcome: explicitly retry SAME judgment/admission_id to reconcile; new retry key if needed, never assume no effect. claim_judgment records relations. Notes/inactive rules are not independent evidence. code_link/health_assessment require exact inspected/admitted inputs, not human approval/deletion/policy authority or freshness proof.",
    "memory_feedback": "Record rejection reasons or correction/retract-request candidates. Reject affects evidence beyond this query, not deletion or retraction. Query-only irrelevance is memory_context.relevance. No approval/purge.",
}




def _compact_schema(schema: dict) -> dict:
    def children(node):
        for keyword in ("properties", "$defs", "patternProperties", "dependentSchemas"):
            for name, child in node.get(keyword, {}).items():
                yield node[keyword], name, child
        for keyword in ("anyOf", "oneOf", "allOf", "prefixItems"):
            for index, child in enumerate(node.get(keyword, ())):
                yield node[keyword], index, child
        for keyword in (
            "items", "if", "then", "else", "not", "additionalProperties",
            "contains", "propertyNames", "unevaluatedProperties",
        ):
            child = node.get(keyword)
            if isinstance(child, dict):
                yield node, keyword, child

    def strip_titles(node):
        node.pop("title", None)
        for _, _, child in children(node):
            if isinstance(child, dict):
                strip_titles(child)

    def encoded(node):
        return json.dumps(node, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

    strip_titles(schema)
    original_definitions = schema.get("$defs", {})
    definition_names = {name: f"d{index}" for index, name in enumerate(original_definitions)}
    references = {
        f"#/$defs/{name.replace('~', '~0').replace('/', '~1')}": f"#/$defs/{short}"
        for name, short in definition_names.items()
    }

    def shorten_references(node):
        if node.get("$ref") in references:
            node["$ref"] = references[node["$ref"]]
        discriminator = node.get("discriminator")
        if isinstance(discriminator, dict):
            mapping = discriminator.get("mapping", {})
            for tag, reference in mapping.items():
                if reference in references:
                    mapping[tag] = references[reference]
        for _, _, child in children(node):
            if isinstance(child, dict):
                shorten_references(child)

    shorten_references(schema)
    if original_definitions:
        schema["$defs"] = {
            definition_names[name]: definition for name, definition in original_definitions.items()
        }
    definitions = schema.setdefault("$defs", {})
    sequence = 0
    while True:
        counts = {}

        def count(node):
            key = encoded(node)
            counts[key] = counts.get(key, 0) + 1
            for _, _, child in children(node):
                if isinstance(child, dict):
                    count(child)

        count(schema)
        while f"s{sequence}" in definitions:
            sequence += 1
        name = f"s{sequence}"
        reference = {"$ref": f"#/$defs/{name}"}
        reference_size = len(encoded(reference))
        # Factor only schema nodes, never property maps, data defaults or enums.
        # Recount after each replacement: nested savings are not independent.
        choices = [
            ((occurrences - 1) * len(key) - occurrences * reference_size - len(name) - 4, key)
            for key, occurrences in counts.items() if occurrences > 1
        ]
        gain, selected = max(choices, default=(0, b""))
        if gain <= 0:
            break

        def replace(node):
            for parent, key, child in children(node):
                if isinstance(child, dict):
                    if encoded(child) == selected:
                        parent[key] = reference.copy()
                    else:
                        replace(child)

        replace(schema)
        definitions[name] = json.loads(selected)
        sequence += 1
    if not definitions:
        schema.pop("$defs", None)
    return schema


def input_schema(model: type[TypedModel]) -> dict:
    return {"type": "object", **model.model_json_schema()}


def record_schema() -> dict:
    union = RECORD_ADAPTER.json_schema()
    definitions = union["$defs"]
    variants = [(item["$ref"], definitions[item["$ref"].rsplit("/", 1)[-1]]) for item in union["oneOf"]]
    note_ref, note = next((ref, item) for ref, item in variants if item["properties"]["kind"].get("default") == "note")
    alternatives = {}
    kinds = []
    for _, variant in variants:
        for name, value in variant["properties"].items():
            choices = alternatives.setdefault(name, [])
            if value not in choices:
                choices.append(value)
        kind = variant["properties"]["kind"]
        kinds.extend(kind["enum"] if "enum" in kind else (kind["const"],))
    properties = {
        name: choices[0] if len(choices) == 1 else {"anyOf": choices}
        for name, choices in alternatives.items()
    }
    properties["kind"] = {**note["properties"]["kind"], "enum": kinds}
    properties["kind"].pop("const", None)
    conditional = {"$ref": note_ref}
    for ref, variant in reversed([(ref, item) for ref, item in variants if item is not note]):
        conditional = {
            "if": {"properties": {"kind": variant["properties"]["kind"]}, "required": ["kind"]},
            "then": {"$ref": ref},
            "else": conditional,
        }
    for _, variant in variants:
        # Root fields validate common types; each branch retains exact keys and refinements.
        variant["propertyNames"] = {"enum": list(variant["properties"])}
        variant["properties"] = {
            name: schema for name, schema in variant["properties"].items() if schema != properties[name]
        }
        variant.pop("additionalProperties", None)
    return {
        "type": "object", "properties": properties, "additionalProperties": False,
        "required": sorted(set.intersection(*(set(item.get("required", ())) for _, item in variants))),
        "$defs": definitions, **conditional,
    }


def command_from_wire[Model: TypedModel](model: type[Model] | TypeAdapter[Model], value: object) -> Model:
    try:
        return validate_wire(model, value)
    except (ValidationError, ValueError, TypeError):
        raise DomainError("INPUT_INVALID", "Arguments do not match the complete strict schema", status=400) from None


async def actor_from_scope(application: Application, scope: dict, roles: tuple[Role, ...]) -> Principal:
    identity = scope.get("agents_memory_oauth")
    if isinstance(identity, VerifiedOAuthIdentity):
        if identity.expires_at <= time.time():
            raise DomainError("AUTH_DENIED", "The OAuth access token expired", status=401)
        return await application.store.authenticate_external(identity.credential_id, identity.generation, roles)
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


SESSION_IDLE_SECONDS = 300


def _session_not_found() -> DomainError:
    return DomainError("SESSION_NOT_FOUND", "The protocol session expired or is unknown; initialize a new session", status=404)


class SecurityEdge:
    def __init__(
        self, inner, application: Application, settings: Settings,
        ingress: CloudIngressProfile | None = None,
    ) -> None:
        self.inner = inner
        self.application = application
        self.settings = settings
        self.ingress = ingress
        self.oauth = OAuthVerifier(ingress.oauth, application.store) if ingress is not None and ingress.oauth is not None else None
        self.sessions: dict[str, tuple[tuple, float]] = {}
        self.active = 0
        self.lifecycle_failures: list[BaseException] = []
        self.lifecycle_status = {"stage": "idle", "failed": False, "local_drained": True, "incomplete": []}

    @property
    def lifecycle_failed(self) -> bool:
        return bool(self.lifecycle_failures) or self.lifecycle_status["failed"] is True

    def raise_for_lifecycle_failure(self) -> None:
        if self.lifecycle_failed:
            raise DomainError(
                "SERVICE_LIFECYCLE_FAILED", "The service lifecycle failed; inspect bounded lifecycle status",
                status=503,
            ) from None

    async def _lifespan(self, scope, receive, send) -> None:
        stage = "startup"
        sent_failure = False

        async def safe_send(message):
            nonlocal stage, sent_failure
            kind = message["type"]
            if kind in {"lifespan.startup.failed", "lifespan.shutdown.failed"}:
                sent_failure = True
                stage = "startup" if kind == "lifespan.startup.failed" else "shutdown"
                self.lifecycle_status.update(stage=stage, failed=True)
                message = {
                    "type": kind,
                    "message": json.dumps({
                        "stage": stage, "code": "SERVICE_LIFECYCLE_FAILED", "type": "LifecycleFailure",
                    }, separators=(",", ":")),
                }
            elif kind == "lifespan.startup.complete":
                stage = "shutdown"
            await send(message)

        try:
            await self.inner(scope, receive, safe_send)
        except BaseException as error:
            if not any(error is failure for failure in self.lifecycle_failures):
                if not isinstance(error, BaseExceptionGroup) or not self.lifecycle_failures:
                    self.lifecycle_failures.append(error)
            self.lifecycle_status.update(stage=stage, failed=True)
            if not sent_failure:
                await safe_send({"type": f"lifespan.{stage}.failed"})

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "lifespan":
            await self._lifespan(scope, receive, send)
            return
        if scope["type"] != "http" or scope.get("path") == "/healthz":
            await self._handle(scope, receive, send)
            return
        # Refuse before authentication, body decoding or any handler, so the effect is not_started.
        if self.active >= self.settings.max_concurrent_requests:
            await error_response(DomainError("SERVICE_BUSY", "The service is at its request limit; retry later", status=503))(scope, receive, send)
            return
        self.active += 1
        held = True

        def release() -> None:
            nonlocal held
            if held:
                held = False
                self.active -= 1

        async def stream_send(message) -> None:
            await send(message)
            # Authentication and session checks are capped; an established idle stream is bounded by the session limit.
            if message["type"] == "http.response.start":
                release()

        stream = scope.get("method") == "GET" and scope.get("path") == "/mcp"
        self.application.inflight += 1
        try:
            await self._handle(scope, receive, stream_send if stream else send)
        finally:
            self.application.inflight -= 1
            release()

    async def _handle(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.inner(scope, receive, send)
            return
        headers: dict[bytes, bytes] = {}
        for key, value in scope.get("headers", ()):
            key = key.lower()
            if key in headers and (
                key in {
                    b"authorization", b"host", b"origin", b"content-length", b"mcp-session-id",
                    b"mcp-protocol-version", b"mcp-method", b"mcp-name", b"forwarded",
                } or key.startswith(b"x-forwarded-") or key in {b"x-real-ip", b"x-original-host", b"x-original-proto"}
            ):
                await error_response(DomainError("HEADERS_INVALID", "Duplicate security header", status=400))(scope, receive, send)
                return
            headers[key] = value
        try:
            public = public_request(self.ingress, self.settings, scope, headers)
        except DomainError as error:
            await error_response(error)(scope, receive, send)
            return
        scope["agents_memory_public"] = public
        path = scope.get("path", "")
        if path == OAUTH_METADATA_PATH:
            if not public or self.oauth is None or scope["method"] != "GET":
                await error_response(DomainError("NOT_FOUND", "No resource metadata is configured here", status=404))(scope, receive, send)
                return
            await JSONResponse({
                "resource": self.ingress.public_origin,
                "authorization_servers": [self.ingress.oauth.issuer],
                "scopes_supported": sorted({scope for mapping in self.ingress.oauth.mappings for scope in mapping.required_scopes}),
                "bearer_methods_supported": ["header"],
            })(scope, receive, send)
            return
        if path == "/healthz":
            await JSONResponse({"alive": True})(scope, receive, send)
            return
        if not self.application.accepting:
            if path == "/readyz":
                await JSONResponse({
                    "ready": False, "accepting": False, "lifecycle": self.lifecycle_status,
                }, status_code=503)(scope, receive, send)
                return
            await error_response(DomainError(
                "SERVICE_UNAVAILABLE", "The local database authority is not ready",
                status=503, effect=EffectState.NOT_STARTED,
            ))(scope, receive, send)
            return
        if path == "/readyz" and b"authorization" not in headers:
            await self.inner(scope, receive, send)
            return
        auth = headers.get(b"authorization", b"")
        try:
            if not auth.startswith(b"Bearer "):
                raise DomainError("UNAUTHORIZED", "Bearer authentication is required", status=401)
            token = auth[7:].decode("ascii")
            oauth_request = public and self.oauth is not None
            if not token or len(token) > (16384 if oauth_request else 512) or any(character.isspace() for character in token):
                raise DomainError("UNAUTHORIZED", "The bearer credential is invalid", status=401)
            identity = None
            if oauth_request:
                actor, identity = await self.oauth.authenticate(token)
                scope["agents_memory_oauth"] = identity
                scope["user"] = AuthenticatedUser(identity.access_token(token, self.ingress.public_origin))
            else:
                actor = await self.application.store.authenticate(token)
            if public and actor.role not in (Role.AGENT, Role.PRODUCER):
                raise DomainError("ROLE_DENIED", "Public ingress accepts only agent and producer credentials", status=403)
            owner = (actor.credential_id, actor.generation, actor.role,
                     *((identity.issuer, identity.subject, identity.client_id) if identity is not None else ()))
            if path == "/mcp" and actor.role != Role.AGENT:
                raise DomainError("ROLE_DENIED", "Only the agent credential can use MCP", status=403)
            session = headers.get(b"mcp-session-id", b"").decode("ascii")
            now = time.monotonic()
            self.sessions = {sid: entry for sid, entry in self.sessions.items() if now - entry[1] <= SESSION_IDLE_SECONDS}
            if session:
                entry = self.sessions.get(session)
                if entry is None:
                    raise _session_not_found()
                if entry[0] != owner:
                    raise DomainError("SESSION_CREDENTIAL_DENIED", "The protocol session is not bound to this verified identity", status=403)
                self.sessions[session] = (owner, now)
            if scope["method"] == "POST":
                body = bytearray()
                try:
                    async with asyncio.timeout(HTTP_BODY_SECONDS):
                        while True:
                            message = await receive()
                            if message["type"] == "http.disconnect":
                                return
                            body.extend(message.get("body", b""))
                            if len(body) > self.settings.max_http_body_bytes:
                                raise DomainError("INPUT_TOO_LARGE", "The HTTP body exceeds its limit", status=413)
                            if not message.get("more_body", False):
                                break
                except TimeoutError:
                    raise DomainError(
                        "REQUEST_BODY_TIMEOUT", "The complete HTTP body did not arrive within its deadline",
                        status=408, effect=EffectState.NOT_STARTED,
                    ) from None
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
            scope["agents_memory_auth_mode"] = "oauth" if oauth_request else "bearer"
        except DomainError as error:
            if error.status == 503 and error.code != "DATABASE_BUSY":
                error = DomainError(
                    "SERVICE_UNAVAILABLE", "The database authority is not ready",
                    status=503, effect=EffectState.NOT_STARTED,
                )
            response = error_response(error)
            if error.code == "REQUEST_BODY_TIMEOUT" and scope.get("http_version") in {"1.0", "1.1"}:
                response.headers["Connection"] = "close"
            if public and self.oauth is not None and error.status == 401:
                response.headers["WWW-Authenticate"] = (
                    f'Bearer resource_metadata="{self.ingress.public_origin}{OAUTH_METADATA_PATH}", error="invalid_token"'
                )
            await response(scope, receive, send)
            return
        except (UnicodeError, ValueError):
            await error_response(DomainError("INPUT_INVALID", "The security envelope is invalid", status=400))(scope, receive, send)
            return
        except Exception:
            await error_response(DomainError(
                "SERVICE_UNAVAILABLE", "The database authority is not ready",
                status=503, effect=EffectState.NOT_STARTED,
            ))(scope, receive, send)
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
                self.sessions[sid.decode("ascii")] = (owner, time.monotonic())
            if session and message["status"] == 404:
                self.sessions.pop(session, None)
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
                may_commit = isinstance(params, dict) and isinstance(params.get("name"), str) and params["name"] in SCHEMAS
                effect = scope.get(
                    "agents_memory_effect", EffectState.UNKNOWN if may_commit else EffectState.NOT_STARTED
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
                if session and response_start["status"] == 404:
                    # The SDK answers an unknown or reaped session before dispatching to any handler.
                    self.sessions.pop(session, None)
                    await error_response(_session_not_found())(scope, receive, send)
                    return
                await forward_start(response_start)
                await send({"type": "http.response.body", "body": bytes(response_body), "more_body": False})

        await self.inner(scope, receive, bound_send)


def readiness_judgment(settings: Settings) -> dict:
    """Operator readiness reports who judges sources; Jev means an opt-in external inference call."""
    try:
        judgment = describe(settings, load_state(settings), operator=False)["source_judgment"]
    except DomainError as error:
        return {"judgment": "unavailable", "server_inference": "unknown", "judge_error": error.code}
    except Exception:
        return {"judgment": "unavailable", "server_inference": "unknown", "judge_error": "JUDGE_STATE_INVALID"}
    if judgment == "jev_background_then_server_validation":
        return {"judgment": judgment, "server_inference": "typesafe_jev_explicit_egress_opt_in"}
    if judgment == "current_coding_agent_via_mcp":
        return {"judgment": judgment, "server_inference": "absent"}
    return {"judgment": judgment, "server_inference": "unavailable"}


def create_app(settings: Settings):
    ingress = load_ingress(settings)
    journal = DeletionJournal(settings.journal_dir, settings.deployment_id)
    store = Store(settings, journal)
    schemas = {
        name: _compact_schema(record_schema() if model is RECORD_ADAPTER else input_schema(model))
        for name, model in SCHEMAS.items()
    }
    application = Application(settings, store)
    worker = CleanupScheduler(settings, store)
    judge = JudgeWorker(settings, store, application)
    recovery = SpoolRecovery(settings, store)
    application.judge = judge

    async def list_tools(context, params):
        if context.request is None:
            raise DomainError("UNAUTHORIZED", "HTTP request authentication is required", status=401)
        await actor_from_scope(application, context.request.scope, (Role.AGENT,))
        return ListToolsResult(tools=[
            Tool(name=name, description=DESCRIPTIONS[name], inputSchema=schema)
            for name, schema in schemas.items()
        ])

    async def call_tool(context, params):
        may_commit = params.name in SCHEMAS
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
                result = await application.inspect(
                    actor, command.ref, command.binding_id, command.snapshot,
                    byte_start=command.byte_start, max_bytes=command.max_bytes,
                    claim_ids=command.claim_ids, rejection_cursor=command.rejection_cursor,
                )
            elif params.name == "memory_record":
                result = await application.record(actor, command)
            else:
                result = await application.feedback(actor, command)
            if may_commit:
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
                if may_commit and context.request is not None else EffectState.NOT_STARTED,
            ))

    async def api(request: Request):
        name = request.path_params["action"]
        try:
            if name == "client-bootstrap":
                actor = await actor_from_scope(application, request.scope, (Role.AGENT, Role.PRODUCER))
                command = command_from_wire(ClientBootstrapRequest, request.scope.get("agents_memory_json", {}))
                actor, revision = await store.client_bootstrap(actor, command.binding_id)
                result = ClientBootstrapResult(
                    deployment_id=settings.deployment_id, realm=settings.realm, mode=settings.mode,
                    capability=settings.capability, auth_mode=request.scope["agents_memory_auth_mode"],
                    credential_id=actor.credential_id, generation=actor.generation, role=actor.role.value,
                    bindings=actor.bindings, binding_id=command.binding_id, binding_revision=revision,
                    bounds=ClientBootstrapBounds(**{
                        name: getattr(settings, name) for name in ClientBootstrapBounds.model_fields
                    }),
                )
                return JSONResponse(result.model_dump(mode="json"))
            roles = (
                (Role.PRODUCER, Role.OPERATOR) if name in {"capture", "correct", "health-observer"}
                else (Role.AGENT, Role.PRODUCER, Role.OPERATOR) if name == "health"
                else (Role.AGENT, Role.OPERATOR)
            )
            actor = await actor_from_scope(application, request.scope, roles)
            data = request.scope.get("agents_memory_json", {})
            if name == "health":
                return JSONResponse(await application.health(actor, command_from_wire(HEALTH_ADAPTER, data)))
            if name == "health-observer":
                command = command_from_wire(HealthObserverRequest, data)
                return JSONResponse(await application.health_observer(actor, command.binding_id))
            if name == "context":
                return JSONResponse(await application.context(actor, command_from_wire(ContextCommand, data)))
            if name == "required-context":
                return JSONResponse(await application.required_context(actor, command_from_wire(ContextCommand, data)))
            if name == "inspect":
                command = command_from_wire(InspectCommand, data)
                return JSONResponse(await application.inspect(
                    actor, command.ref, command.binding_id, command.snapshot,
                    byte_start=command.byte_start, max_bytes=command.max_bytes,
                    claim_ids=command.claim_ids, rejection_cursor=command.rejection_cursor,
                ))
            if name == "record":
                return JSONResponse(await application.record(actor, command_from_wire(RECORD_ADAPTER, data)))
            if name == "feedback":
                return JSONResponse(await application.feedback(actor, command_from_wire(FeedbackCommand, data)))
            if name == "capture":
                application.require_accepting()
                operation = await store.capture(actor, command_from_wire(CaptureCommand, data))
                judge.notify()
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
        ready = await store.readiness()
        ready["ready"] = ready["ready"] and application.accepting
        if "agents_memory_token" not in request.scope:
            return JSONResponse({**ready, "accepting": application.accepting}, status_code=200 if ready["ready"] else 503)
        try:
            await actor_from_scope(application, request.scope, (Role.OPERATOR,))
        except DomainError as error:
            return error_response(error)
        judgment = readiness_judgment(settings)
        ready["ready"] = ready["ready"] and judgment["judgment"] != "unavailable"
        return JSONResponse({
            **ready,
            "authority": "connected" if ready["db_ready"] else "unavailable",
            "capability": settings.capability,
            **judgment,
            "candidate_index": "lexical_entity",
            "cleanup_scheduler": worker.status,
            "judge_worker": judge.status,
            "spool_recovery": recovery.status,
            "accepting": application.accepting,
            "native_hook_trust": "not_attested_by_service",
        }, status_code=200 if ready["ready"] else 503)

    async def health_observer_api(request: Request):
        request.path_params["action"] = "health-observer"
        return await api(request)

    server = Server(
        "agents-memory",
        version="0.1.0",
        instructions="",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
        get_tool_input_schema=schemas.get,
    )
    inner = server.streamable_http_app(
        json_response=True,
        stateless_http=False,
        max_request_body_size=settings.max_http_body_bytes,
        session_idle_timeout=SESSION_IDLE_SECONDS,
        max_sessions=64,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[
                f"127.0.0.1:{settings.port}", f"localhost:{settings.port}",
                *([urlsplit(ingress.public_origin).netloc] if ingress is not None else []),
            ],
            allowed_origins=[
                settings.base_url, f"http://localhost:{settings.port}",
                *([ingress.public_origin] if ingress is not None else []),
            ],
        ),
        custom_starlette_routes=[
            Route("/api/health/observer", health_observer_api, methods=["POST"]),
            Route("/api/{action}", api, methods=["POST"]),
            Route("/readyz", readiness, methods=["GET"]),
        ],
    )
    sdk_lifespan = inner.router.lifespan_context


    @asynccontextmanager
    async def lifespan(app):
        from .ops import authority_lock

        failures: list[BaseException] = []

        def remember(error: BaseException) -> None:
            if not any(error is existing for existing in failures):
                failures.append(error)

        async def stop(name, callback):
            try:
                result = await callback()
                if isinstance(result, dict) and result.get("local_drained") is False:
                    edge.lifecycle_status["incomplete"].append(name)
                    edge.lifecycle_status["local_drained"] = False
                    remember(DomainError(
                        "LOCAL_DRAIN_INCOMPLETE", "A local owner exceeded its drain deadline", status=503,
                    ))
            except BaseException as error:
                remember(error)

        async def join(name, owner):
            try:
                await owner.wait_closed()
            except BaseException as error:
                remember(error)
            if name in edge.lifecycle_status["incomplete"]:
                edge.lifecycle_status["incomplete"].remove(name)

        async def shutdown_owners():
            for name, callback in (
                ("recovery", recovery.stop), ("judge", judge.stop),
                ("scheduler", worker.stop), ("application", application.drain),
            ):
                await stop(name, callback)
            await asyncio.gather(*(
                join(name, owner) for name, owner in (
                    ("recovery", recovery), ("judge", judge),
                    ("scheduler", worker), ("application", application),
                )
            ))
            edge.lifecycle_status.update(local_drained=not edge.lifecycle_status["incomplete"])

        async def finish(callback):
            task = asyncio.create_task(callback())
            while True:
                try:
                    return await asyncio.shield(task)
                except asyncio.CancelledError as error:
                    remember(error)
                    if task.done():
                        return task.result()

        try:
            with authority_lock(settings):
                try:
                    await store.open()
                    await store.reconcile_journal()
                    async with sdk_lifespan(app) as state:
                        try:
                            worker.start()
                            judge.start()
                            recovery.start()
                            edge.lifecycle_status.update(stage="running")
                            yield state
                        except BaseException as error:
                            remember(error)
                        finally:
                            application.accepting = False
                            edge.lifecycle_status.update(stage="draining", local_drained=False)
                            await finish(shutdown_owners)
                except BaseException as error:
                    remember(error)
                finally:
                    try:
                        await finish(store.close)
                    except BaseException as error:
                        remember(error)
        except BaseException as error:
            remember(error)
        if failures:
            edge.lifecycle_failures.extend(failures)
            edge.lifecycle_status.update(stage="failed", failed=True)
            if len(failures) == 1:
                raise failures[0]
            raise BaseExceptionGroup("Local service lifecycle failed", failures)
        edge.lifecycle_status.update(stage="closed")

    inner.router.lifespan_context = lifespan
    edge = SecurityEdge(inner, application, settings, ingress)
    edge.application = application
    edge.worker = worker
    edge.judge = judge
    edge.recovery = recovery
    return edge
