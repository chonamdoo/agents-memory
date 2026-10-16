from __future__ import annotations

import http.client
import math
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from .connection import RemoteClientSettings, local_opener, open_http, read_http_body, remote_opener
from .domain import DomainError, EffectState
from .wire import decode_json


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise DomainError("DESTINATION_DENIED", "Readiness cannot follow redirects", status=503)


def ensure_local_ready(
    base_url: str, *, state_dir: Path | None = None, deployment_id: str | None = None, timeout: float = 5,
) -> dict:
    """Recover only a registered service, then wait for bounded DB-inclusive readiness.

    This is pre-dispatch only: a failure proves no business operation was sent.
    No business request is replayed here.
    """
    parsed = urlsplit(base_url)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
        raise DomainError("DESTINATION_DENIED", "Only the registered loopback service is permitted")
    if not math.isfinite(timeout) or timeout <= 0:
        raise DomainError("INPUT_INVALID", "Readiness requires a positive finite deadline")
    from .service import ensure_started

    deadline = time.monotonic() + timeout
    # A durable manual stop wins even if an old process still answers health.
    ensure_started(base_url, state_dir, deployment_id, deadline=deadline)
    opener = local_opener(_NoRedirect())
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            request = urllib.request.Request(base_url.rstrip("/") + "/readyz", headers={"Accept": "application/json"})
            with open_http(opener, request, deadline=min(deadline, time.monotonic() + 2)) as response:
                raw = read_http_body(response, maximum=16384, deadline=deadline)
                result = decode_json(raw) if len(raw) <= 16384 else {}
                if (response.status == 200 and result.get("ready") is True and result.get("db_ready") is True
                        and isinstance(result.get("deployment_id"), str) and result["deployment_id"]
                        and (deployment_id is None or result["deployment_id"] == deployment_id)):
                    return result
                if deployment_id is not None and result.get("deployment_id") is not None and result["deployment_id"] != deployment_id:
                    raise DomainError("SERVICE_IDENTITY_MISMATCH", "The endpoint belongs to another deployment", status=503)
        except urllib.error.HTTPError as error:
            error.close()
        except DomainError as error:
            if error.code != "SERVICE_UNAVAILABLE":
                raise
        except (OSError, ValueError, urllib.error.URLError, http.client.HTTPException):
            pass
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(0.1, remaining))
    raise DomainError("SERVICE_UNAVAILABLE", "The local database authority is not ready", status=503, effect=EffectState.NOT_STARTED)


def ensure_remote_ready(
    profile: RemoteClientSettings, *, timeout: float = 5,
) -> dict:
    if not isinstance(profile, RemoteClientSettings):
        raise DomainError("DESTINATION_DENIED", "Remote readiness requires an explicit validated client profile")
    if not math.isfinite(timeout) or timeout <= 0:
        raise DomainError("INPUT_INVALID", "Readiness requires a positive finite deadline")
    deadline = time.monotonic() + timeout
    from .service import require_client_enabled

    require_client_enabled(profile, deadline=deadline)
    opener = remote_opener(profile, _NoRedirect())
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            request = urllib.request.Request(profile.base_url + "/readyz", headers={"Accept": "application/json"})
            with open_http(opener, request, deadline=min(deadline, time.monotonic() + 2)) as response:
                raw = read_http_body(response, maximum=16384, deadline=deadline)
                result = decode_json(raw) if len(raw) <= 16384 else {}
                if (result.get("deployment_id") != profile.deployment_id
                        or result.get("realm") != profile.realm):
                    raise DomainError("SERVICE_IDENTITY_MISMATCH", "The endpoint does not match the remote deployment and realm", status=503)
                if response.status == 200 and result.get("ready") is True and result.get("db_ready") is True:
                    return result
        except urllib.error.HTTPError as error:
            error.close()
        except DomainError as error:
            if error.code != "SERVICE_UNAVAILABLE":
                raise
        except urllib.error.URLError as error:
            if isinstance(error.reason, ssl.SSLCertVerificationError):
                raise DomainError("TLS_VERIFICATION_FAILED", "The remote TLS identity could not be verified", status=503) from None
        except (OSError, ValueError, urllib.error.URLError, http.client.HTTPException):
            pass
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(0.1, remaining))
    raise DomainError("SERVICE_UNAVAILABLE", "The remote database authority is not ready", status=503, effect=EffectState.NOT_STARTED)


