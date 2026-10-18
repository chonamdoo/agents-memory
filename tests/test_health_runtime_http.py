from __future__ import annotations

import json
from datetime import UTC, datetime

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

        credential = edge.application.store._credential
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
                patcher.setattr(edge.application.store, "_credential", revoke_when_checked)
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
            patcher.setattr(edge.application.store, "_credential", producer_authority_unavailable)
            status, body = await request(edge, {"binding_id": authority.binding_id}, TOKEN, path="/api/health/observer")
        assert status == 503
        assert json.loads(body)["error"]["code"] == "DATABASE_BUSY"
        await authority.store.revoke_token(authority.actor, authority.actor.credential_id)
        status, _ = await request(edge, {"binding_id": authority.binding_id}, TOKEN, path="/api/health/observer")
        assert status == 401


@pytest.mark.parametrize("old_workspace_state", ["active", "withdrawn"])
async def test_healthy_code_link_commits_despite_revoked_foreign_producer(
    authority, monkeypatch, old_workspace_state,
):
    from test_store_authority import ready_claim

    from agents_memory.health import (
        CodeLinkCommand,
        CodeObservationCommand,
        HealthPolicyCommand,
        HealthWorkspaceCommand,
    )

    store, actor, binding = authority.store, authority.actor, authority.binding_id
    mutation = {"binding_id": binding, "expected_binding_revision": 1}
    await store.health(actor, HealthPolicyCommand(**mutation, idempotency_key="relink-policy",
        expected_policy_revision=0, enabled=True))
    producers, observations = {}, {}
    for index, name in enumerate(("old", "healthy")):
        producers[name] = await store.issue_token(actor, Role.PRODUCER, (binding,), "relink-" + name + "-" + "p" * 48)
        await store.health(actor, HealthWorkspaceCommand(
            **mutation, idempotency_key="relink-workspace-" + name, workspace_id="workspace_relink_" + name,
            expected_workspace_revision=0, root_fingerprint=("a", "b")[index] * 64,
            producer_credential_id=producers[name].credential_id))
        await store.health(producers[name], CodeObservationCommand(
            **mutation, idempotency_key="relink-observation-" + name, workspace_id="workspace_relink_" + name,
            expected_workspace_revision=1, root_fingerprint=("a", "b")[index] * 64, sequence=1,
            observed_at=datetime(2026, 10, 18, tzinfo=UTC), coverage="explicit_paths",
            files=[{"relative_path": "src/cache.py", "status": "present", "file_digest": "c" * 64,
                "byte_length": 27, "symbol_coverage": "complete", "symbols": []}]))
        view = await store.inspect(actor, binding, "health:workspace:workspace_relink_" + name)
        observations[name] = view["observations"][0]["ref"]
    _, claim = await ready_claim(authority, key="relink-claim")

    async def link_command(name, key):
        view = await store.inspect(actor, binding, "health:claim:" + claim.id + ":observation:" + observations[name])
        return CodeLinkCommand(**mutation, idempotency_key=key, admission_id=view["admission"]["id"],
            claim_ref={"id": claim.id, "revision": claim.revision},
            expected_health_version=view["health"]["version"], observation_refs=[observations[name]],
            reason="The inspected ordinary claim depends on this exact code observation.")

    await store.health(actor, await link_command("old", "relink-original-link"))
    if old_workspace_state == "withdrawn":
        await store.health(actor, HealthWorkspaceCommand(
            **mutation, idempotency_key="relink-withdraw-old-workspace", workspace_id="workspace_relink_old",
            expected_workspace_revision=1, root_fingerprint="a" * 64, state="withdrawn",
            producer_credential_id=producers["old"].credential_id))
    await store.revoke_token(actor, producers["old"].credential_id)
    command = await link_command("healthy", "relink-healthy-link")
    async with running(authority) as edge:
        status, body = await request(edge, command.model_dump(mode="json"), TOKEN, path="/api/health")
        assert status == 200, body
        linked = json.loads(body)
        assert linked["state"] == "health_recorded"
        event = await store.inspect(actor, binding, "health:event:" + linked["artifact_id"])
        assert event["payload"]["added_observation_refs"] == [observations["healthy"]]
        registry = await store.health_observer(producers["healthy"], binding)
        assert registry["workspaces"][0]["linked_paths"][0]["relative_path"] == "src/cache.py"
        current = await store.inspect(actor, binding, "health:claim:" + claim.id)
        assert not current["health"]["reusable"]
        failing = await link_command("healthy", "relink-unexpected-failure")
        credential = edge.application.store._credential

        async def unavailable_foreign_authority(connection, credential_id):
            if credential_id == producers["old"].credential_id:
                raise DomainError("DATABASE_BUSY", "The foreign authority is temporarily unavailable", status=503)
            return await credential(connection, credential_id)

        with monkeypatch.context() as patcher:
            patcher.setattr(edge.application.store, "_credential", unavailable_foreign_authority)
            status, body = await request(edge, failing.model_dump(mode="json"), TOKEN, path="/api/health")
        assert status == 503
        assert json.loads(body)["error"]["code"] == "DATABASE_BUSY"
        after = await store.inspect(actor, binding, "health:claim:" + claim.id)
        assert after["health"]["version"] == current["health"]["version"]
        await store.revoke_token(actor, actor.credential_id)
        status, body = await request(edge, failing.model_dump(mode="json"), TOKEN, path="/api/health")
        assert status == 401
        assert json.loads(body)["error"]["code"] == "AUTH_DENIED"
