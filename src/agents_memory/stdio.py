from __future__ import annotations

import asyncio
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.client import HTTPException
from pathlib import Path
from urllib.parse import urlsplit

from .client import NoRedirect
from .config import Settings
from .connection import (
    RemoteClientSettings,
    local_opener,
    open_http,
    read_http_body,
    read_remote_credential,
    remote_opener,
    validate_remote_endpoint,
)
from .domain import DomainError, EffectState
from .readiness import ensure_local_ready, ensure_remote_ready
from .wire import decode_json


@dataclass(frozen=True)
class RelayEndpoint:
    base_url: str
    max_http_body_bytes: int = 65536
    max_mcp_response_bytes: int = 16384
    state_dir: Path | None = None
    deployment_id: str | None = None
    remote_settings: RemoteClientSettings | None = None
    health_receipt: Path | None = None

    def __post_init__(self) -> None:
        if self.remote_settings is not None:
            validate_remote_endpoint(self.remote_settings, self.base_url, self.state_dir, self.deployment_id)
            if (self.max_http_body_bytes != self.remote_settings.max_http_body_bytes
                    or self.max_mcp_response_bytes != self.remote_settings.max_mcp_response_bytes):
                raise DomainError("DESTINATION_DENIED", "The relay bounds do not match the remote profile")
            return
        url = urlsplit(self.base_url)
        if (
            url.scheme != "http" or url.hostname not in {"127.0.0.1", "::1"}
            or url.username or url.password or url.query or url.fragment or url.path not in {"", "/"}
            or not 16384 <= self.max_http_body_bytes <= 262144
            or not 4096 <= self.max_mcp_response_bytes <= 65536
        ):
            raise DomainError("DESTINATION_DENIED", "The native receipt does not describe a bounded loopback endpoint")


_REINITIALIZE_ID = "agents-memory-relay-reinitialize"


class StdioRelay:
    def __init__(self, settings: Settings | RelayEndpoint, token_file: Path) -> None:
        self.settings = settings
        self.token_file = token_file
        self.session_id: str | None = None
        self.protocol_version: str | None = None
        self.initialize_params: dict | None = None
        # Set while a lost session still needs a successful re-initialize; survives a failed handshake.
        self.recovery_pending = False
        self.remote_settings = settings.remote_settings if isinstance(settings, RelayEndpoint) else None
        self.opener = (
            remote_opener(self.remote_settings, NoRedirect()) if self.remote_settings is not None
            else local_opener(NoRedirect())
        )

    def forward(self, message: dict) -> dict | None:
        deadline = time.monotonic() + 120
        try:
            if (isinstance(self.settings, RelayEndpoint) and self.settings.health_receipt is not None
                    and message.get("method") == "tools/call"
                    and isinstance(message.get("params"), dict)
                    and message["params"].get("name") == "memory_context"):
                from .health_producer import health_before_context
                from .hosts import load_receipt

                receipt = load_receipt(self.settings.health_receipt)
                if (receipt["base_url"] != self.settings.base_url
                        or receipt["deployment_id"] != self.settings.deployment_id
                        or Path(receipt["agent_token_file"]) != self.token_file):
                    raise DomainError("HEALTH_WORKSPACE_SCOPE", "The relay receipt changed scope")
                observed = health_before_context(receipt)
                arguments = message["params"].get("arguments", {})
                if not isinstance(arguments, dict):
                    return self.error(message, "RPC_ENVELOPE_INVALID")
                workspace_id = observed.get("workspace_id")
                if (arguments.get("code_workspace_id") is not None
                        and arguments["code_workspace_id"] != workspace_id):
                    raise DomainError("HEALTH_WORKSPACE_SCOPE", "The caller selected another code workspace")
                if workspace_id is not None:
                    message = {
                        **message,
                        "params": {
                            **message["params"],
                            "arguments": {**arguments, "code_workspace_id": workspace_id},
                        },
                    }
            # A request without a session would be refused by the SDK, so recover before sending it.
            if (self.recovery_pending and message.get("method") != "initialize"
                    and not self._reinitialize(deadline=deadline)):
                return self.error(message, "SESSION_NOT_FOUND")
            result, session_lost = self._send(message, deadline=deadline)
            # Only validated not_started SESSION_NOT_FOUND proves a resend cannot duplicate a write.
            if not session_lost or not self._reinitialize(deadline=deadline):
                return result
            return self._send(message, deadline=deadline)[0]
        except DomainError as error:
            # Readiness can fail during reinitialization too; preserve its explicit unavailable/stop code.
            return self.error(message, error.code, EffectState.NOT_STARTED)

    def _reinitialize(self, *, deadline: float) -> bool:
        params, negotiated, self.session_id = self.initialize_params, self.protocol_version, None
        if params is None:
            return False
        self.recovery_pending = True
        result, _ = self._send(
            {"jsonrpc": "2.0", "id": _REINITIALIZE_ID, "method": "initialize", "params": params},
            deadline=deadline,
        )
        # The host still speaks the version it negotiated; a restarted server offering another cannot stand in.
        if result is None or "result" not in result or self.session_id is None or self.protocol_version != negotiated:
            self.session_id, self.protocol_version, self.recovery_pending = None, negotiated, True
            return False
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"}, deadline=deadline)
        return True

    def _send(self, message: dict, *, deadline: float) -> tuple[dict | None, bool]:
        params = message.get("params", {})
        if (message.get("jsonrpc") != "2.0"
                or ("id" in message and type(message["id"]) not in {str, int, type(None)})
                or not isinstance(params, dict) or not isinstance(message.get("method"), str)):
            return self.error(message, "RPC_ENVELOPE_INVALID"), False
        name = params.get("name")
        if "name" in params and not isinstance(name, str):
            return self.error(message, "RPC_ENVELOPE_INVALID"), False
        if message["method"] == "initialize" and not isinstance(params.get("protocolVersion"), str):
            return self.error(message, "RPC_ENVELOPE_INVALID"), False
        from .private_io import private_read

        if self.remote_settings is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return self.error(message, "SERVICE_UNAVAILABLE"), False
            ensure_remote_ready(self.remote_settings, timeout=min(remaining, 5))
            self.opener = remote_opener(self.remote_settings, NoRedirect())
            try:
                token = read_remote_credential(self.token_file, self.remote_settings)
            except DomainError:
                return self.error(message, "RELAY_CREDENTIAL_UNAVAILABLE"), False
        else:
            try:
                token = private_read(self.token_file, 4096).decode("utf-8").strip()
                if not token or not token.isascii() or any(character.isspace() for character in token):
                    raise ValueError
            except (DomainError, OSError, ValueError, UnicodeError):
                return self.error(message, "RELAY_CREDENTIAL_UNAVAILABLE"), False
        meta = params.get("_meta", {})
        if not isinstance(meta, dict):
            return self.error(message, "RPC_ENVELOPE_INVALID"), False
        request_version = meta.get("io.modelcontextprotocol/protocolVersion")
        if "io.modelcontextprotocol/protocolVersion" in meta and not isinstance(request_version, str):
            return self.error(message, "RPC_ENVELOPE_INVALID"), False
        headers = {
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Mcp-Method": message.get("method", ""),
        }
        if self.remote_settings is not None:
            headers["Origin"] = self.remote_settings.base_url
        if name:
            headers["Mcp-Name"] = name
        version = request_version or self.protocol_version
        if version:
            headers["MCP-Protocol-Version"] = version
        if self.session_id and request_version is None:
            headers["Mcp-Session-Id"] = self.session_id
        if any("\r" in value or "\n" in value for value in headers.values()):
            return self.error(message, "RPC_ENVELOPE_INVALID"), False
        try:
            for value in headers.values():
                value.encode("latin-1")
            raw = json.dumps(message, ensure_ascii=False, allow_nan=False).encode("utf-8")
            if len(raw) > self.settings.max_http_body_bytes:
                return self.error(message, "BOUNDED_INPUT_INVALID"), False
            request = urllib.request.Request(
                self.settings.base_url + "/mcp",
                data=raw,
                headers=headers,
            )
        except (ValueError, TypeError, UnicodeError):
            return self.error(message, "RPC_ENVELOPE_INVALID"), False
        if self.remote_settings is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return self.error(message, "SERVICE_UNAVAILABLE"), False
            ensure_local_ready(
                self.settings.base_url, state_dir=self.settings.state_dir,
                deployment_id=self.settings.deployment_id,
                timeout=min(remaining, 5),
            )
        if time.monotonic() >= deadline:
            return self.error(message, "SERVICE_UNAVAILABLE", EffectState.NOT_STARTED), False
        sent_session = "Mcp-Session-Id" in headers
        try:
            with open_http(self.opener, request, deadline=deadline) as response:
                result = self.read_response(response, deadline=deadline)
                if result is None and "id" not in message:
                    return None, False
                if not self.valid_response(message, result):
                    return self.error(message, "RPC_RESPONSE_INVALID", EffectState.UNKNOWN), False
                if "error" in result:
                    return self.public_error(message, result), False
                if response.headers.get("Mcp-Session-Id") and request_version is None:
                    self.session_id = response.headers["Mcp-Session-Id"]
                if message["method"] == "initialize" and "result" in result:
                    self.protocol_version = result["result"]["protocolVersion"]
                    self.initialize_params = params
                    self.recovery_pending = False
                return result, False
        except urllib.error.HTTPError as error:
            try:
                result = self.read_response(error, deadline=deadline)
                edge = self._edge_error(result)
                if edge is None:
                    return self.public_error(message, result), False
                lost = (sent_session and message["method"] != "initialize" and error.code == 404
                    and edge == ("SESSION_NOT_FOUND", EffectState.NOT_STARTED))
                return self.error(message, *edge), lost
            except (DomainError, OSError, ValueError, urllib.error.URLError, HTTPException):
                return self.error(message, "RPC_RESPONSE_INVALID", EffectState.UNKNOWN), False
            finally:
                error.close()
        except (OSError, ValueError, urllib.error.URLError, HTTPException):
            return self.error(message, "SERVICE_UNAVAILABLE_RECONCILE_DURABLE_WRITES", EffectState.UNKNOWN), False
        except DomainError as error:
            return self.error(message, error.code, error.effect), False

    def read_response(self, response, *, deadline: float | None = None) -> dict | None:
        raw = read_http_body(
            response, maximum=self.settings.max_mcp_response_bytes,
            deadline=deadline if deadline is not None else time.monotonic() + 120,
        )
        if len(raw) > self.settings.max_mcp_response_bytes:
            raise DomainError("RESULT_TOO_LARGE", "The relay response exceeds its wire limit", effect=EffectState.UNKNOWN)
        length = response.headers.get("Content-Length")
        if length is not None and (not length.isascii() or not length.isdecimal() or int(length) != len(raw)):
            raise DomainError("RPC_RESPONSE_INVALID", "The relay response is incomplete", effect=EffectState.UNKNOWN)
        try:
            return decode_json(raw) if raw else None
        except (ValueError, UnicodeError):
            raise DomainError("RPC_RESPONSE_INVALID", "The relay response is invalid", effect=EffectState.UNKNOWN) from None

    @staticmethod
    def _verified(code, effect) -> tuple[str, EffectState] | None:
        """Accept a public error code and effect only when both are well formed."""
        if not isinstance(code, str) or re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", code) is None:
            return None
        try:
            return code, EffectState(effect)
        except (ValueError, TypeError):
            return None

    @classmethod
    def _edge_error(cls, response: dict | None) -> tuple[str, EffectState] | None:
        """Return the edge's bounded HTTP error only when every public field is valid."""
        if not isinstance(response, dict) or set(response) != {"error"}:
            return None
        public = response["error"]
        if not isinstance(public, dict) or not isinstance(public.get("message"), str):
            return None
        return cls._verified(public.get("code"), public.get("effect"))

    def public_error(self, message: dict, response: dict | None) -> dict | None:
        if not self.valid_response(message, response) or "error" not in response:
            return self.error(message, "RPC_RESPONSE_INVALID", EffectState.UNKNOWN)
        public = response["error"]
        data = public.get("data")
        verified = self._verified(public["message"], data.get("effect")) if isinstance(data, dict) else None
        if verified is None:
            return self.error(message, "RPC_RESPONSE_INVALID", EffectState.UNKNOWN)
        return self.error(message, *verified, rpc_code=public["code"])

    @staticmethod
    def valid_response(message: dict, response: dict | None) -> bool:
        if (not isinstance(response, dict) or response.get("jsonrpc") != "2.0"
                or "id" not in message or "id" not in response
                or type(response["id"]) is not type(message["id"]) or response["id"] != message["id"]
                or ("result" in response) == ("error" in response)):
            return False
        if "error" in response:
            error = response["error"]
            return (isinstance(error, dict) and type(error.get("code")) is int
                and isinstance(error.get("message"), str))
        result = response["result"]
        if not isinstance(result, dict):
            return False
        return message["method"] != "initialize" or isinstance(result.get("protocolVersion"), str)

    def error(
        self, message: dict, code: str, effect: EffectState = EffectState.NOT_STARTED, *, rpc_code: int = -32000,
    ) -> dict | None:
        if "id" not in message:
            return None
        request_id = message["id"]
        if (type(request_id) not in {str, int, type(None)}
                or len(json.dumps(request_id, ensure_ascii=False).encode("utf-8")) > self.settings.max_mcp_response_bytes - 512):
            request_id = None
        return {"jsonrpc": "2.0", "id": request_id, "error": {
            "code": rpc_code, "message": code, "data": {"effect": effect.value},
        }}


def _write_result(result: dict) -> bool:
    try:
        sys.stdout.buffer.write(
            json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        )
        sys.stdout.buffer.flush()
        return True
    except (OSError, ValueError):
        return False


async def run_stdio(settings: Settings | RelayEndpoint, token_file: Path) -> None:
    relay = StdioRelay(settings, token_file)
    while True:
        try:
            raw = await asyncio.to_thread(sys.stdin.buffer.readline, settings.max_http_body_bytes + 2)
        except (OSError, ValueError):
            return
        if not raw:
            return
        if len(raw) > settings.max_http_body_bytes or not raw.endswith(b"\n"):
            if not _write_result(relay.error({"id": None}, "BOUNDED_INPUT_INVALID", rpc_code=-32700)):
                raise DomainError("STDIO_DELIVERY_FAILED", "The response channel is closed", status=503)
            return
        try:
            message = decode_json(raw)
            result = await asyncio.to_thread(relay.forward, message)
        except (DomainError, ValueError, UnicodeError):
            result = relay.error({"id": None}, "BOUNDED_INPUT_INVALID", rpc_code=-32700)
        if result is not None and not _write_result(result):
            raise DomainError("STDIO_DELIVERY_FAILED", "The response channel is closed; reconcile any dispatched mutation", status=503, effect=EffectState.UNKNOWN)
