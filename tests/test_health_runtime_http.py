from __future__ import annotations

import json

import pytest
from test_edge_boundaries import AGENT_TOKEN, request, running, tool, tool_code
from test_store_authority import TOKEN
from test_store_authority import authority as authority

from agents_memory.domain import DomainError, Role


async def test_health_policy_is_operator_only_and_observer_is_producer_safe(authority):
    producer_token = "health-wire-producer-" + "p" * 32
    producer = await authority.store.issue_token(authority.actor, Role.PRODUCER, (authority.binding_id,), producer_token)
    payload = {
        "kind": "health_policy", "binding_id": authority.binding_id, "expected_binding_revision": 1,
        "idempotency_key": "health-wire-policy", "expected_policy_revision": 0,
        "enabled": True, "allow_jev_health": False,
    }
    async with running(authority) as edge:
        status, body = await request(edge, payload, TOKEN, path="/api/health")
        assert status == 200, body
        assert json.loads(body)["state"] == "health_recorded"
        for token in (AGENT_TOKEN, producer_token):
            status, body = await request(edge, {**payload, "idempotency_key": "forbidden-policy"}, token, path="/api/health")
            assert status == 403
        disposition = {
            "kind": "health_work_disposition", "binding_id": authority.binding_id,
            "expected_binding_revision": 1, "idempotency_key": "forbidden-work-disposition",
            "pending_id": "pending_fixture", "expected_pending_revision": 1,
            "decision": "close_unknown", "reason": "Unknown work does not approve facts.",
        }
        for token in (AGENT_TOKEN, producer_token):
            status, body = await request(edge, disposition, token, path="/api/health")
            assert status == 403
        workspace = {
            "kind": "health_workspace", "binding_id": authority.binding_id, "expected_binding_revision": 1,
            "idempotency_key": "health-wire-workspace", "workspace_id": "workspace_health_wire",
            "expected_workspace_revision": 0, "root_fingerprint": "a" * 64,
            "producer_credential_id": producer.credential_id,
        }
        status, body = await request(edge, workspace, TOKEN, path="/api/health")
        assert status == 200, body
        status, body = await request(edge, {"binding_id": authority.binding_id}, producer_token, path="/api/health/observer")
        assert status == 200, body
        observed = json.loads(body)
        assert observed["kind"] == "health_observer"
        assert [row["workspace_id"] for row in observed["workspaces"]] == ["workspace_health_wire"]
        assert observed["policy"]["allow_jev_health"] is False
        assert not {"claims", "sources", "reason", "body", "catalog"}.intersection(observed)
        status, body = await request(edge, {"binding_id": authority.binding_id}, AGENT_TOKEN, path="/api/health/observer")
        assert status == 403


@pytest.mark.parametrize("payload", [
    {"kind": "health_policy", "expected_policy_revision": 0, "enabled": True},
    {"kind": "health_workspace", "workspace_id": "workspace_fixture", "expected_workspace_revision": 0,
        "root_fingerprint": "a" * 64, "producer_credential_id": "producer_fixture"},
    {"kind": "memory_review", "admission_id": "admission_fixture", "claim_ref": {"id": "claim_fixture", "revision": 1},
        "expected_health_version": 0, "decision": "reject", "reason": "Explicit operator review."},
    {"kind": "feedback_resolution", "admission_id": "admission_fixture", "feedback_ref": "feedback_fixture",
        "expected_feedback_version": 0, "decision": "decline", "reason": "Explicit candidate disposition."},
    {"kind": "health_work_disposition", "pending_id": "pending_fixture", "expected_pending_revision": 1,
        "decision": "close_unknown", "reason": "Unknown work is not an assessment."},
])
async def test_mcp_record_never_exposes_operator_health_commands(authority, payload):
    from agents_memory.health import HEALTH_ADAPTER

    command = HEALTH_ADAPTER.validate_python({"binding_id": authority.binding_id,
        "expected_binding_revision": 1, "idempotency_key": "operator-command-schema-boundary", **payload})
    async with running(authority) as edge:
        status, body = await request(edge, tool(command.model_dump(mode="json"), name="memory_record"))
        assert status == 200
        assert tool_code(body) == "INPUT_INVALID"


async def test_health_wire_decode_failure_does_not_echo_private_extra_fields(authority):
    marker = "synthetic_private_health_argument"
    async with running(authority) as edge:
        status, body = await request(edge, {
            "kind": "health_policy", "binding_id": authority.binding_id,
            "expected_binding_revision": "1", "idempotency_key": "invalid-health-wire", "private": marker,
        }, TOKEN, path="/api/health")
        assert status == 400
        assert json.loads(body)["error"]["code"] == "INPUT_INVALID"
        assert marker.encode() not in body


@pytest.mark.parametrize("revocation_timing", ["before_registry", "during_credential_check"])
async def test_operator_health_observer_retains_healthy_workspaces_after_producer_revocation(
    authority, monkeypatch, revocation_timing,
):
    tokens = {"stale": "observer-stale-" + "s" * 48, "healthy": "observer-healthy-" + "h" * 48}
    producers = {
        name: await authority.store.issue_token(authority.actor, Role.PRODUCER, (authority.binding_id,), token)
        for name, token in tokens.items()
    }
    workspace_ids = {"stale": "workspace_observer_a_stale", "healthy": "workspace_observer_b_healthy"}
    async with running(authority) as edge:
        status, body = await request(edge, {
            "kind": "health_policy", "binding_id": authority.binding_id, "expected_binding_revision": 1,
            "idempotency_key": "observer-enable-policy", "expected_policy_revision": 0,
            "enabled": True, "allow_jev_health": False,
        }, TOKEN, path="/api/health")
        assert status == 200, body
        for index, name in enumerate(producers):
            status, body = await request(edge, {
                "kind": "health_workspace", "binding_id": authority.binding_id, "expected_binding_revision": 1,
                "idempotency_key": "observer-register-" + name, "workspace_id": workspace_ids[name],
                "expected_workspace_revision": 0, "root_fingerprint": ("a", "b")[index] * 64,
                "producer_credential_id": producers[name].credential_id,
            }, TOKEN, path="/api/health")
            assert status == 200, body
        status, body = await request(edge, {"binding_id": authority.binding_id}, TOKEN, path="/api/health/observer")
        assert status == 200, body
        assert [row["workspace_id"] for row in json.loads(body)["workspaces"]] == list(workspace_ids.values())

        credential = authority.store._credential
        revoked = False

        async def revoke_when_checked(connection, credential_id):
            nonlocal revoked
            if credential_id == producers["stale"].credential_id and not revoked:
                revoked = True
                await authority.store.revoke_token(authority.actor, credential_id)
            return await credential(connection, credential_id)

        if revocation_timing == "before_registry":
            await authority.store.revoke_token(authority.actor, producers["stale"].credential_id)
        with monkeypatch.context() as patcher:
            if revocation_timing == "during_credential_check":
                patcher.setattr(authority.store, "_credential", revoke_when_checked)
            status, body = await request(edge, {"binding_id": authority.binding_id}, TOKEN, path="/api/health/observer")
        assert status == 200, body
        assert [row["workspace_id"] for row in json.loads(body)["workspaces"]] == [workspace_ids["healthy"]]
        status, body = await request(edge, {"binding_id": authority.binding_id}, tokens["healthy"],
                                     path="/api/health/observer")
        assert status == 200, body
        assert [row["workspace_id"] for row in json.loads(body)["workspaces"]] == [workspace_ids["healthy"]]
        status, _ = await request(edge, {"binding_id": authority.binding_id}, tokens["stale"],
                                  path="/api/health/observer")
        assert status == 401
        status, _ = await request(edge, {"binding_id": authority.binding_id}, AGENT_TOKEN,
                                  path="/api/health/observer")
        assert status == 403

        async def producer_authority_unavailable(connection, credential_id):
            if credential_id == producers["healthy"].credential_id:
                raise DomainError("DATABASE_BUSY", "The producer authority is temporarily unavailable", status=503)
            return await credential(connection, credential_id)

        with monkeypatch.context() as patcher:
            patcher.setattr(authority.store, "_credential", producer_authority_unavailable)
            status, body = await request(edge, {"binding_id": authority.binding_id}, TOKEN, path="/api/health/observer")
        assert status == 503
        assert json.loads(body)["error"]["code"] == "DATABASE_BUSY"
        await authority.store.revoke_token(authority.actor, authority.actor.credential_id)
        status, _ = await request(edge, {"binding_id": authority.binding_id}, TOKEN, path="/api/health/observer")
        assert status == 401
