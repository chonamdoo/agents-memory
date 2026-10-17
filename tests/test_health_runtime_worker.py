from __future__ import annotations

import asyncio
from types import SimpleNamespace

from test_judge_worker import world as world
from test_store_authority import authority as authority
from test_store_authority import source_selection

from agents_memory.domain import CaptureCommand, CaptureCoverage, RevisionRef
from agents_memory.health import HealthPolicyCommand, SessionObservationCommand
from agents_memory.jev import JevResult


async def health_work(world, authority, *, allow=True):
    current = SimpleNamespace(store=world.store, actor=world.operator, binding_id=world.binding_id)
    await world.application.health(world.operator, HealthPolicyCommand(
        binding_id=world.binding_id, expected_binding_revision=1, idempotency_key="worker-health-policy",
        expected_policy_revision=0, enabled=True, allow_jev_health=allow,
    ))
    await world.application.health(world.operator, SessionObservationCommand(
        binding_id=world.binding_id, expected_binding_revision=1, idempotency_key="worker-health-start",
        stream_id="health_worker_stream", segment_id="health_worker_segment", event_id="health_worker_start",
        sequence=1, event="start", agent_path="observed-agent", coverage="observed_segment",
    ))
    captured = await world.store.capture(world.operator, CaptureCommand(
        binding_id=world.binding_id, idempotency_key="health-worker-claim", origin_key="health-worker-claim",
        body="CacheKey is retained only offline.", speaker="human", agent_path="observed-agent",
        coverage=CaptureCoverage(status="observed_window"),
    ))
    selected = await world.store.record(world.operator, await source_selection(current, captured.source_id))
    record = await world.store.inspect(world.operator, world.binding_id, selected.artifact_id)
    claim = await world.store.claim(world.operator, world.binding_id, record["claim_ids"][0])
    await world.application.health(world.operator, SessionObservationCommand(
        binding_id=world.binding_id, expected_binding_revision=1, idempotency_key="worker-health-close",
        stream_id="health_worker_stream", segment_id="health_worker_segment", event_id="health_worker_end",
        sequence=2, event="end", agent_path="observed-agent", source_refs=[RevisionRef(id=captured.source_id, revision=1)],
        claim_refs=[RevisionRef(id=claim.id, revision=claim.revision)], coverage="observed_segment",
    ))
    return claim


def health_provider(world, *, revoke=None, no_evidence=False):
    original = world.jev.system_one
    calls = []

    def system_one(state, questions, *, before_attempt):
        if not any(key.startswith(("evidence_", "support_", "relevance_")) for key in questions):
            return original(state, questions, before_attempt=before_attempt)
        before_attempt()
        calls.append((state, questions))
        if revoke is not None and len(calls) == 1:
            revoke()
            before_attempt()
        answers = {}
        for key, question in questions.items():
            choice = "none" if key.startswith("evidence_") and no_evidence else (
                "s0" if key.startswith("evidence_") else "related" if key.startswith("relevance_") else "supported"
            )
            answers[key] = {"type": "choice", "choice": choice,
                            "probabilities": {name: float(name == choice) for name in question["criteria"]}}
        return JevResult(model="jev-1.13.0", answers=answers, input_tokens=None)

    world.jev.system_one = system_one
    return calls


async def test_existing_jev_permission_does_not_send_health_without_extra_purpose_consent(world, authority):
    await health_work(world, authority, allow=False)
    calls = health_provider(world)
    await world.worker.cycle()
    assert calls == []
    assert "pending" in await world.pending("health")


async def test_health_worker_publishes_exact_evidence_but_does_not_invent_freshness_or_usage(world, authority):
    claim = await health_work(world, authority)
    calls = health_provider(world)
    await world.worker.cycle()
    assert calls
    view = await world.inspect("health:claim:" + claim.id)
    assert view["health"]["support"] == "supported"
    assert view["health"]["freshness"] == "unknown"
    assert view["health"]["operator_review"] != "accept"
    assert world.worker.counts.unknown_usage_requests == len(calls)


async def test_no_selected_correction_evidence_is_unknown_not_healthy(world, authority):
    claim = await health_work(world, authority)
    health_provider(world, no_evidence=True)
    await world.worker.cycle()
    view = await world.inspect("health:claim:" + claim.id)
    assert view["health"]["support"] == "unknown"
    assert view["health"]["freshness"] == "unknown"


async def test_health_consent_rechecked_inside_each_actual_provider_attempt(world, authority):
    claim = await health_work(world, authority)
    loop = asyncio.get_running_loop()

    async def revoke_policy():
        await world.application.health(world.operator, HealthPolicyCommand(
            binding_id=world.binding_id, expected_binding_revision=1, idempotency_key="worker-health-revoke",
            expected_policy_revision=1, enabled=True, allow_jev_health=False,
        ))

    def revoke():
        asyncio.run_coroutine_threadsafe(revoke_policy(), loop).result()

    calls = health_provider(world, revoke=revoke)
    await world.worker.cycle()
    assert len(calls) == 1
    assert "pending" in await world.pending("health")
    view = await world.inspect("health:claim:" + claim.id)
    assert view["health"]["support"] == "unknown"
    assert world.worker.last_error == "HEALTH_EGRESS_DENIED"
