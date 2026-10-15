from __future__ import annotations

import asyncio
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.client import HTTPException
from pathlib import Path
from urllib.parse import urlsplit

from .client import NoRedirect
from .config import Settings
from .domain import DomainError, EffectState
from .wire import decode_json


@dataclass(frozen=True)
class RelayEndpoint:
    base_url: str
    max_http_body_bytes: int = 65536
    max_mcp_response_bytes: int = 16384

    def __post_init__(self) -> None:
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
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def forward(self, message: dict) -> dict | None:
        # A request without a session would be refused by the SDK, so recover before sending it.
        if self.recovery_pending and message.get("method") != "initialize" and not self._reinitialize():
            return self.error(message, "SESSION_NOT_FOUND")
        result, session_lost = self._send(message)
        # Only the edge's validated not_started SESSION_NOT_FOUND proves no handler ran, so one resend cannot duplicate a write.
        if not session_lost or not self._reinitialize():
            return result
        return self._send(message)[0]

    def _reinitialize(self) -> bool:
        params, negotiated, self.session_id = self.initialize_params, self.protocol_version, None
        if params is None:
            return False
        self.recovery_pending = True
        result, _ = self._send({"jsonrpc": "2.0", "id": _REINITIALIZE_ID, "method": "initialize", "params": params})
        # The host still speaks the version it negotiated; a restarted server offering another cannot stand in.
        if result is None or "result" not in result or self.session_id is None or self.protocol_version != negotiated:
            self.session_id, self.protocol_version, self.recovery_pending = None, negotiated, True
            return False
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return True

    def _send(self, message: dict) -> tuple[dict | None, bool]:
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
            request = urllib.request.Request(
                self.settings.base_url + "/mcp",
                data=json.dumps(message, ensure_ascii=False, allow_nan=False).encode("utf-8"),
                headers=headers,
            )
        except (ValueError, TypeError, UnicodeError):
            return self.error(message, "RPC_ENVELOPE_INVALID"), False
        sent_session = "Mcp-Session-Id" in headers
        try:
            with self.opener.open(request, timeout=120) as response:
                result = self.read_response(response)
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
                result = self.read_response(error)
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

    def read_response(self, response) -> dict | None:
        raw = response.read(self.settings.max_mcp_response_bytes + 1)
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


def _write_result(result: dict) -> None:
    sys.stdout.buffer.write(
        json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
    )
    sys.stdout.buffer.flush()


async def run_stdio(settings: Settings | RelayEndpoint, token_file: Path) -> None:
    relay = StdioRelay(settings, token_file)
    while True:
        raw = await asyncio.to_thread(sys.stdin.buffer.readline, settings.max_http_body_bytes + 2)
        if not raw:
            return
        try:
            if len(raw) > settings.max_http_body_bytes or not raw.endswith(b"\n"):
                _write_result(relay.error({"id": None}, "BOUNDED_INPUT_INVALID", rpc_code=-32700))
                return
            message = decode_json(raw)
            result = await asyncio.to_thread(relay.forward, message)
        except (DomainError, ValueError, UnicodeError):
            result = relay.error({"id": None}, "BOUNDED_INPUT_INVALID", rpc_code=-32700)
        if result is not None:
            _write_result(result)
