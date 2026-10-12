from __future__ import annotations

import asyncio
import http.client
import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from .domain import DomainError, EffectState
from .wire import decode_json


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise DomainError("DESTINATION_DENIED", "The local service attempted a redirect", status=502, effect=EffectState.UNKNOWN)


class LocalClient:
    def __init__(self, base_url: str, token_file: Path, timeout: float = 120) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
        ):
            raise DomainError("DESTINATION_DENIED", "Only the registered loopback service is permitted")
        self.base_url = base_url.rstrip("/")
        self.token_file = token_file
        self.timeout = timeout

    def request(self, path: str, payload: dict | None = None) -> dict:
        if not path.startswith("/") or path.startswith("//") or ".." in path.split("/"):
            raise DomainError("DESTINATION_DENIED", "The local API path is invalid")
        try:
            token = self.token_file.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            raise DomainError("CREDENTIAL_INVALID", "The local credential file is unavailable", status=401) from None
        if not token or len(token) > 512 or any(character.isspace() for character in token):
            raise DomainError("CREDENTIAL_INVALID", "The local credential file is invalid", status=401)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        request = urllib.request.Request(
            self.base_url + path,
            data=None if payload is None else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"),
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        )
        try:
            with opener.open(request, timeout=self.timeout) as response:
                raw = response.read(262145)
                if len(raw) > 262144:
                    raise DomainError("RESPONSE_TOO_LARGE", "The local API response exceeds its limit", effect=EffectState.UNKNOWN)
                try:
                    result = decode_json(raw)
                except ValueError:
                    raise DomainError("RESPONSE_INVALID", "The local API response is invalid", effect=EffectState.UNKNOWN) from None
        except urllib.error.HTTPError as error:
            try:
                raw = error.read(16385)
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

    async def call(self, path: str, payload: dict | None = None) -> dict:
        return await asyncio.to_thread(self.request, path, payload)
