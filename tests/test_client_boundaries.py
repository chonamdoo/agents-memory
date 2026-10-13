from __future__ import annotations

import http.client
import io
import json
import urllib.error
from types import SimpleNamespace

import pytest

from agents_memory.client import LocalClient
from agents_memory.domain import DomainError, EffectState


@pytest.fixture
def local_client(tmp_path):
    token = tmp_path / "producer.token"
    token.write_text("test-only-producer-credential\n")
    return LocalClient("http://127.0.0.1:8768", token)


def reply(monkeypatch, raw):
    monkeypatch.setattr("agents_memory.client.urllib.request.build_opener", lambda *handlers: SimpleNamespace(open=lambda *args, **kwargs: io.BytesIO(raw)))


@pytest.mark.parametrize("failure", [
    http.client.IncompleteRead(b"private partial response", 12),
    http.client.BadStatusLine("private upstream diagnostic"),
    http.client.RemoteDisconnected("private socket diagnostic"),
])
@pytest.mark.parametrize("boundary", ["open", "read"])
def test_http_protocol_failure_is_sanitized_unknown_write_effect(local_client, monkeypatch, failure, boundary):
    class BrokenResponse(io.BytesIO):
        def read(self, size=-1):
            raise failure

    def open_request(*args, **kwargs):
        if boundary == "open":
            raise failure
        return BrokenResponse()

    monkeypatch.setattr("agents_memory.client.urllib.request.build_opener", lambda *handlers: SimpleNamespace(open=open_request))
    with pytest.raises(DomainError) as caught:
        local_client.request("/api/capture", {"idempotency_key": "capture-001"})
    assert caught.value.code == "SERVICE_UNAVAILABLE"
    assert caught.value.effect is EffectState.UNKNOWN
    assert "private" not in json.dumps(caught.value.public())


@pytest.mark.parametrize("body", [b"null", b"[]", b'"private diagnostic"', b'{"effect":', b'{"id":"one","id":"two"}'])
def test_malformed_success_response_cannot_claim_not_started(local_client, monkeypatch, body):
    reply(monkeypatch, body)
    with pytest.raises(DomainError) as caught:
        local_client.request("/api/capture", {})
    assert caught.value.code == "RESPONSE_INVALID"
    assert caught.value.effect is EffectState.UNKNOWN
    assert "private diagnostic" not in json.dumps(caught.value.public())


@pytest.mark.parametrize("body,code,effect", [
    ({"error": {"code": "ORIGIN_CONFLICT", "effect": "not_started", "message": "private body"}}, "ORIGIN_CONFLICT", EffectState.NOT_STARTED),
    ({"error": {"code": "RESULT_TOO_LARGE", "effect": "committed", "message": "private body"}}, "RESULT_TOO_LARGE", EffectState.COMMITTED),
    ({"error": ["private body"]}, "SERVICE_REJECTED", EffectState.UNKNOWN),
    ({"error": {"code": {"body": "private body"}, "effect": None}}, "SERVICE_REJECTED", EffectState.UNKNOWN),
    ({"error": {"code": "private path /credentials", "effect": "committed"}}, "SERVICE_REJECTED", EffectState.COMMITTED),
    (["private body"], "SERVICE_REJECTED", EffectState.UNKNOWN),
])
def test_http_rejection_preserves_only_valid_sanitized_effect(local_client, monkeypatch, body, code, effect):
    def reject(*args, **kwargs):
        raise urllib.error.HTTPError("http://127.0.0.1:8768/api/capture", 409, "private status", {}, io.BytesIO(json.dumps(body).encode()))

    monkeypatch.setattr("agents_memory.client.urllib.request.build_opener", lambda *handlers: SimpleNamespace(open=reject))
    with pytest.raises(DomainError) as caught:
        local_client.request("/api/capture", {})
    assert caught.value.code == code and caught.value.effect is effect
    assert caught.value.status == 409
    assert "private" not in json.dumps(caught.value.public())


def test_incomplete_http_error_body_is_still_public_unknown(local_client, monkeypatch):
    class BrokenBody(io.BytesIO):
        def read(self, size=-1):
            raise http.client.IncompleteRead(b"private partial error", 20)

    def reject(*args, **kwargs):
        raise urllib.error.HTTPError("http://127.0.0.1:8768/api/capture", 503, "private error", {}, BrokenBody())

    monkeypatch.setattr("agents_memory.client.urllib.request.build_opener", lambda *handlers: SimpleNamespace(open=reject))
    with pytest.raises(DomainError) as caught:
        local_client.request("/api/capture", {})
    assert caught.value.code == "SERVICE_REJECTED"
    assert caught.value.effect is EffectState.UNKNOWN
    assert "private" not in json.dumps(caught.value.public())


def test_missing_local_credential_is_sanitized_before_request_attempt(local_client, monkeypatch):
    local_client.token_file.unlink()
    attempted = []
    monkeypatch.setattr("agents_memory.client.urllib.request.build_opener", lambda *handlers: attempted.append(True))
    with pytest.raises(DomainError) as caught:
        local_client.request("/api/capture", {})
    assert caught.value.code == "CREDENTIAL_INVALID"
    assert caught.value.effect is EffectState.NOT_STARTED
    assert attempted == []
