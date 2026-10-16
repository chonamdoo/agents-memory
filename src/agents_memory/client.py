from __future__ import annotations

import asyncio
import http.client
import json
import math
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import ValidationError

from .connection import (
    RemoteClientSettings,
    local_opener,
    open_http,
    read_http_body,
    read_remote_credential,
    remote_opener,
    validate_remote_endpoint,
)
from .domain import CaptureCommand, CorrectCommand, DomainError, EffectState, FeedbackCommand
from .private_io import private_read
from .readiness import ensure_local_ready, ensure_remote_ready
from .wire import decode_json, validate_wire

# A 512-character UTF-8 token may use four bytes per character, plus a CRLF.
_MAX_TOKEN_FILE_BYTES = 512 * 4 + 2


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise DomainError("DESTINATION_DENIED", "The local service attempted a redirect", status=502, effect=EffectState.UNKNOWN)


class LocalClient:
    def __init__(
        self, base_url: str, token_file: Path, timeout: float = 120, *,
        state_dir: Path | None = None, deployment_id: str | None = None,
        remote_settings: RemoteClientSettings | None = None,
    ) -> None:
        parsed = urlsplit(base_url)
        if remote_settings is not None:
            validate_remote_endpoint(remote_settings, base_url, state_dir, deployment_id)
        elif (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
        ):
            raise DomainError("DESTINATION_DENIED", "Only the registered loopback service is permitted")
        if not math.isfinite(timeout) or timeout <= 0:
            raise DomainError("INPUT_INVALID", "Requests require a positive finite deadline")
        self.base_url = base_url.rstrip("/")
        self.token_file = token_file
        self.timeout = timeout
        self.state_dir = state_dir
        self.deployment_id = deployment_id
        self.remote_settings = remote_settings

    def request(self, path: str, payload: dict | None = None) -> dict:
        if not path.startswith("/") or path.startswith("//") or ".." in path.split("/"):
            raise DomainError("DESTINATION_DENIED", "The local API path is invalid")
        if path in {"/api/capture", "/api/correct", "/api/record", "/api/feedback"}:
            try:
                if path == "/api/record":
                    from .selection import RECORD_ADAPTER
                    validate_wire(RECORD_ADAPTER, payload)
                elif path == "/api/correct":
                    validate_wire(CorrectCommand, payload)
                else:
                    validate_wire(CaptureCommand if path == "/api/capture" else FeedbackCommand, payload)
            except (ValidationError, ValueError, TypeError, UnicodeError):
                raise DomainError("INPUT_INVALID", "The source command is invalid before dispatch", status=422) from None
        deadline = time.monotonic() + self.timeout
        if self.remote_settings is not None:
            try:
                body = None if payload is None else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
            except (ValueError, TypeError, UnicodeError):
                raise DomainError("INPUT_INVALID", "The API request is invalid before dispatch", status=422) from None
            if body is not None and len(body) > self.remote_settings.max_http_body_bytes:
                raise DomainError("INPUT_TOO_LARGE", "The API request exceeds the remote wire limit", status=413)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DomainError("SERVICE_UNAVAILABLE", "The HTTP deadline expired before readiness", status=503)
            ensure_remote_ready(self.remote_settings, timeout=min(remaining, 5))
            opener = remote_opener(self.remote_settings, NoRedirect())
            token = read_remote_credential(self.token_file, self.remote_settings)
        else:
            token = self._local_credential()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DomainError("SERVICE_UNAVAILABLE", "The HTTP deadline expired before readiness", status=503)
            ensure_local_ready(
                self.base_url, state_dir=self.state_dir, deployment_id=self.deployment_id,
                timeout=min(remaining, 5),
            )
            opener = local_opener(NoRedirect())
            body = None if payload is None else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
        if self.remote_settings is not None:
            headers["Origin"] = self.remote_settings.base_url
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            headers=headers,
        )
        try:
            with open_http(opener, request, deadline=deadline) as response:
                raw = read_http_body(response, maximum=262144, deadline=deadline)
                if len(raw) > 262144:
                    raise DomainError("RESPONSE_TOO_LARGE", "The local API response exceeds its limit", effect=EffectState.UNKNOWN)
                try:
                    result = decode_json(raw)
                except ValueError:
                    raise DomainError("RESPONSE_INVALID", "The local API response is invalid", effect=EffectState.UNKNOWN) from None
        except urllib.error.HTTPError as error:
            try:
                raw = read_http_body(error, maximum=16384, deadline=deadline)
                public = decode_json(raw).get("error", {}) if len(raw) <= 16384 else {}
                code = public.get("code", "SERVICE_REJECTED")
                if not isinstance(code, str) or re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", code) is None:
                    code = "SERVICE_REJECTED"
                effect = EffectState(public.get("effect", "unknown"))
            except (OSError, http.client.HTTPException, ValueError, TypeError, AttributeError):
                code, effect = "SERVICE_REJECTED", EffectState.UNKNOWN
            finally:
                error.close()
            raise DomainError(code, "The local service rejected this request", status=error.code, effect=effect) from None
        except (OSError, ValueError, urllib.error.URLError, http.client.HTTPException):
            raise DomainError(
                "SERVICE_UNAVAILABLE", "The local service is unavailable; reconcile durable writes",
                status=503, effect=EffectState.UNKNOWN,
            ) from None
        return result

    def _local_credential(self) -> str:
        try:
            token = private_read(self.token_file, _MAX_TOKEN_FILE_BYTES).decode("utf-8").strip()
        except (DomainError, OSError, UnicodeError):
            raise DomainError(
                "CREDENTIAL_INVALID", "The local credential file is unavailable",
                status=401, effect=EffectState.NOT_STARTED,
            ) from None
        if not token or len(token) > 512 or any(character.isspace() for character in token):
            raise DomainError(
                "CREDENTIAL_INVALID", "The local credential file is invalid",
                status=401, effect=EffectState.NOT_STARTED,
            )
        return token

    async def call(self, path: str, payload: dict | None = None) -> dict:
        return await asyncio.to_thread(self.request, path, payload)


def client_from_settings(settings, token_file: Path, timeout: float = 120) -> LocalClient:
    return LocalClient(
        settings.base_url, token_file, timeout, state_dir=settings.state_dir,
        deployment_id=settings.deployment_id,
        remote_settings=settings if isinstance(settings, RemoteClientSettings) else None,
    )
