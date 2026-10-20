"""TypeSafe Jev System One client: typed judgments over plain HTTPS, never logging request bodies."""
from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

JEV_BASE_URL = "https://api.typesafe.ai"
JEV_ENDPOINT = JEV_BASE_URL + "/v1/systemone"
JEV_DEFAULT_MODEL = "jev-1.14.0"
_MAX_RESPONSE_BYTES = 1048576
_RETRYABLE = frozenset({"rate_limited", "overloaded", "transport"})


class ProviderFailure(Exception):
    """Classified provider failure; carries no request or response body."""

    def __init__(self, kind: str, status: int | None = None, retry_after: float | None = None) -> None:
        super().__init__(kind)
        self.kind = kind
        self.status = status
        self.retry_after = retry_after


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProviderFailure("redirect", code)


@dataclass(frozen=True)
class ProviderResult:
    model: str
    answers: dict[str, dict[str, Any]]
    input_tokens: int | None


def _retry_after(headers: Any) -> float | None:
    if headers is None:
        return None
    for name, scale in (("retry-after-ms", 0.001), ("retry-after", 1.0)):
        value = headers.get(name)
        if value is None:
            continue
        try:
            seconds = float(value) * scale
        except ValueError:
            continue
        if math.isfinite(seconds) and seconds >= 0:
            return seconds
    return None


def _classify(status: int) -> str:
    if status in {401, 403}:
        return "auth"
    if status == 429:
        return "rate_limited"
    if status in {408, 500, 502, 503, 504, 529}:
        return "overloaded"
    return "request"


def _probability(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProviderFailure("response")
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ProviderFailure("response")
    return number


def parse_answers(payload: object, questions: Mapping[str, Mapping[str, Any]]) -> ProviderResult:
    """Accept only a complete typed answer for every asked question."""
    if not isinstance(payload, dict) or not isinstance(payload.get("answers"), dict):
        raise ProviderFailure("response")
    model = payload.get("model")
    if not isinstance(model, str) or not 1 <= len(model) <= 64:
        raise ProviderFailure("response")
    raw = payload["answers"]
    if set(raw) != set(questions):
        raise ProviderFailure("response")
    answers: dict[str, dict[str, Any]] = {}
    for identifier, question in questions.items():
        answer = raw[identifier]
        if not isinstance(answer, dict) or answer.get("type") != question["type"]:
            raise ProviderFailure("response")
        if question["type"] == "noul":
            answers[identifier] = {"type": "noul", "noul": _probability(answer.get("noul"))}
            continue
        options = set(question["criteria"])
        choice = answer.get("choice")
        probabilities = answer.get("probabilities")
        if choice not in options or not isinstance(probabilities, dict) or not set(probabilities).issubset(options):
            raise ProviderFailure("response")
        answers[identifier] = {
            "type": "choice", "choice": choice,
            "probabilities": {name: _probability(probabilities.get(name, 0.0)) for name in question["criteria"]},
        }
    usage = payload.get("usage")
    tokens = usage.get("input_tokens") if isinstance(usage, dict) else None
    return ProviderResult(model=model, answers=answers, input_tokens=tokens if type(tokens) is int and tokens >= 0 else None)


class SystemOneClient(Protocol):
    def system_one(
        self, state: object, questions: Mapping[str, Mapping[str, Any]], *, before_attempt: Callable[[], None],
    ) -> ProviderResult: ...


class JevClient:
    """Synchronous client; callers run it in a worker thread so the event loop never blocks."""

    def __init__(
        self, key: str, model: str, *, base_url: str = JEV_BASE_URL, timeout: float = 20.0,
        max_retries: int = 2, opener: urllib.request.OpenerDirector | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._key = key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        self._sleep = sleep

    def __repr__(self) -> str:
        return f"JevClient(model={self.model!r}, base_url={self.base_url!r})"

    def _send(self, method: str, path: str, body: bytes | None) -> object:
        request = urllib.request.Request(
            self.base_url + path, data=body, method=method,
            headers={"Authorization": "Bearer " + self._key, "Content-Type": "application/json",
                     "Accept": "application/json", "User-Agent": "agents-memory/0.1.0"},
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            headers = error.headers
            error.close()
            raise ProviderFailure(_classify(error.code), error.code, _retry_after(headers)) from None
        except ProviderFailure:
            raise
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ProviderFailure("transport") from None
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise ProviderFailure("response")
        try:
            return json.loads(raw)
        except (ValueError, UnicodeError):
            raise ProviderFailure("response") from None

    def _with_retries(
        self, operation: Callable[[], object], *, before_attempt: Callable[[], None] | None,
    ) -> object:
        for attempt in range(self.max_retries + 1):
            if before_attempt is not None:
                before_attempt()
            try:
                return operation()
            except ProviderFailure as failure:
                if failure.kind not in _RETRYABLE or attempt == self.max_retries:
                    raise
                delay = failure.retry_after if failure.retry_after is not None else 0.5 * 2 ** attempt
                self._sleep(min(delay, 30.0))
        raise ProviderFailure("transport")

    def system_one(
        self, state: object, questions: Mapping[str, Mapping[str, Any]], *,
        before_attempt: Callable[[], None] | None = None,
    ) -> ProviderResult:
        if not questions:
            raise ValueError("At least one question is required")
        body = json.dumps({"model": self.model, "state": state, "questions": questions},
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
        payload = self._with_retries(lambda: self._send("POST", "/v1/systemone", body), before_attempt=before_attempt)
        return parse_answers(payload, questions)

    def verify(self, *, before_attempt: Callable[[], None] | None = None) -> str:
        """Check the key and model with a synthetic question; no memory content leaves the machine."""
        questions = {"check": {"type": "noul", "instructions": "Is `state` a short connectivity check message?"}}
        return self.system_one("agents-memory provider key check", questions, before_attempt=before_attempt).model
