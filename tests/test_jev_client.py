from __future__ import annotations

import io
import json
import urllib.error
from email.message import Message

import pytest

from agents_memory.jev import JevClient, JevFailure

KEY = "sk-jev-TEST-qwrtyuiopZXCVNMLKJH"
URL = "https://api.typesafe.ai/v1/systemone"
QUESTIONS = {
    "keep": {"type": "noul", "instructions": "Keep `state`?"},
    "kind": {"type": "choice", "instructions": "Kind of `state`?", "criteria": {"fact": "A fact", "finding": "A finding"}},
}


def answer_payload(**changes):
    answers = {
        "keep": {"type": "noul", "noul": 0.91},
        "kind": {"type": "choice", "choice": "finding", "probabilities": {"fact": 0.2, "finding": 0.8}},
    }
    answers.update(changes)
    return {"model": "jev-1.13.0", "answers": answers, "usage": {"input_tokens": 42}}


def http_error(code, headers=None, body=b""):
    message = Message()
    for name, value in (headers or {}).items():
        message[name] = value
    return urllib.error.HTTPError(URL, code, "provider status", message, io.BytesIO(body))


class FakeOpener:
    """Records every send and replays scripted outcomes: bytes bodies or exceptions to raise."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append((request, timeout))
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, BaseException):
            raise outcome
        return io.BytesIO(outcome if isinstance(outcome, bytes) else json.dumps(outcome).encode())


def client(opener, delays=None, **options):
    return JevClient(KEY, "jev-1.13.0", opener=opener, sleep=(delays.append if delays is not None else _no_sleep), **options)


def _no_sleep(seconds):
    pytest.fail(f"A non-retryable failure must not back off ({seconds}s)")


def test_system_one_posts_typed_questions_with_bearer_key_and_parses_answers():
    opener = FakeOpener(answer_payload())
    result = client(opener).system_one({"spans": [{"id": "s0000", "text": "Pin PostgreSQL 18."}]}, QUESTIONS)

    assert len(opener.requests) == 1
    request, timeout = opener.requests[0]
    assert request.full_url == URL and request.get_method() == "POST"
    assert request.get_header("Authorization") == "Bearer " + KEY
    assert json.loads(request.data) == {
        "model": "jev-1.13.0", "state": {"spans": [{"id": "s0000", "text": "Pin PostgreSQL 18."}]}, "questions": QUESTIONS,
    }
    assert timeout is not None and timeout > 0
    assert result.model == "jev-1.13.0" and result.input_tokens == 42
    assert result.answers["keep"] == {"type": "noul", "noul": 0.91}
    assert result.answers["kind"]["choice"] == "finding"
    assert result.answers["kind"]["probabilities"] == {"fact": 0.2, "finding": 0.8}


def test_rate_limit_honors_retry_after_then_returns_answers():
    delays = []
    opener = FakeOpener(http_error(429, {"Retry-After": "2"}), answer_payload())
    result = client(opener, delays).system_one("state", QUESTIONS)
    assert len(opener.requests) == 2
    assert delays == [2.0]
    assert result.answers["keep"]["noul"] == 0.91


@pytest.mark.parametrize(("status", "kind"), [(401, "auth"), (403, "auth"), (400, "request"), (422, "request")])
def test_rejected_key_or_request_fails_after_one_send_without_retry(status, kind):
    opener = FakeOpener(http_error(status))
    with pytest.raises(JevFailure) as caught:
        client(opener).system_one("state", QUESTIONS)
    assert caught.value.kind == kind and caught.value.status == status
    assert len(opener.requests) == 1


@pytest.mark.parametrize("status", [529, 503])
def test_overload_beyond_retry_budget_is_classified_after_every_attempt(status):
    delays = []
    opener = FakeOpener(http_error(status))
    with pytest.raises(JevFailure) as caught:
        client(opener, delays, max_retries=2).system_one("state", QUESTIONS)
    assert caught.value.kind == "overloaded"
    assert len(opener.requests) == 3
    assert len(delays) == 2


@pytest.mark.parametrize("body", [
    {"model": "jev-1.13.0", "answers": {"keep": {"type": "noul", "noul": 0.5}}},
    answer_payload(extra={"type": "noul", "noul": 0.5}),
    answer_payload(keep={"type": "noul", "noul": 1.5}),
    answer_payload(keep={"type": "noul", "noul": -0.1}),
    answer_payload(kind={"type": "choice", "choice": "rumor", "probabilities": {"fact": 1.0}}),
    b"<html>not json</html>",
], ids=["missing-id", "extra-id", "noul-above-one", "noul-below-zero", "choice-outside-criteria", "non-json"])
def test_incomplete_or_untyped_responses_are_rejected(body):
    opener = FakeOpener(body)
    with pytest.raises(JevFailure) as caught:
        client(opener).system_one("state", QUESTIONS)
    assert caught.value.kind == "response"
    assert len(opener.requests) == 1


def test_key_never_appears_in_client_repr_or_failures():
    echoed = http_error(401, body=json.dumps({"error": "bad key " + KEY}).encode())
    opener = FakeOpener(echoed)
    jev = client(opener)
    assert KEY not in repr(jev) and KEY not in str(jev)
    with pytest.raises(JevFailure) as caught:
        jev.system_one("state", QUESTIONS)
    failure = caught.value
    assert KEY not in str(failure) and KEY not in repr(failure)
    assert all(KEY not in str(argument) for argument in failure.args)
    assert failure.__cause__ is None
