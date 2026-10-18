from __future__ import annotations

import asyncio
import hashlib
import io
import json
from types import SimpleNamespace

import pytest
from test_jev_client import http_error
from test_judge_worker import KEY
from test_judge_worker import world as world
from test_store_authority import TOKEN, ready_claim, source_selection
from test_store_authority import authority as authority

from agents_memory import judge_worker as worker_module
from agents_memory.domain import CaptureCommand, CaptureCoverage, RevisionRef
from agents_memory.health import HealthPolicyCommand, MemoryReviewCommand, SessionObservationCommand
from agents_memory.jev import JevClient, JevResult
from agents_memory.judge import load_state, read_worker_token
from agents_memory.judge_worker import JudgeWorker


async def health_work(world, authority, *, allow=True, statement=None, correction=None):
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
    selected = await world.store.record(world.operator, await source_selection(current, captured.source_id, statement=statement))
    record = await world.store.inspect(world.operator, world.binding_id, selected.artifact_id)
    claim = await world.store.claim(world.operator, world.binding_id, record["claim_ids"][0])
    source_refs = [RevisionRef(id=captured.source_id, revision=1)]
    if correction is not None:
        changed = await world.store.capture(world.operator, CaptureCommand(
            binding_id=world.binding_id, idempotency_key="health-worker-correction", origin_key="health-worker-correction",
            body=correction, speaker="human", agent_path="observed-agent",
            coverage=CaptureCoverage(status="observed_window"),
        ))
        source_refs.append(RevisionRef(id=changed.source_id, revision=1))
    await world.application.health(world.operator, SessionObservationCommand(
        binding_id=world.binding_id, expected_binding_revision=1, idempotency_key="worker-health-close",
        stream_id="health_worker_stream", segment_id="health_worker_segment", event_id="health_worker_end",
        sequence=2, event="end", agent_path="observed-agent", source_refs=source_refs,
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


async def test_health_worker_does_not_quarantine_offline_claim_for_online_correction(world, authority):
    claim = await health_work(world, authority, statement="CacheKey is retained.",
        correction="CacheKey is not retained while online.")
    assert claim.draft.conditions == ("only offline",)
    assert "offline" not in claim.draft.statement
    original = world.jev.system_one

    def scoped_oracle(state, questions, *, before_attempt):
        if not any(key.startswith(("evidence_", "support_", "relevance_")) for key in questions):
            return original(state, questions, before_attempt=before_attempt)
        before_attempt()
        answers = {}
        for key, question in questions.items():
            if key.startswith("evidence_"):
                meaning = state["claims"][int(key.split("_")[1])]
                marker = "only offline" if meaning.get("conditions") == ["only offline"] else "not retained while online"
                index = next(index for index, window in enumerate(state["windows"]) if marker in window["text"])
                choice = f"s{index}"
            elif key.startswith("relevance_"):
                choice = "related"
            else:
                pair = state["pairs"][int(key.split("_")[1])]
                meaning = pair["claim"]
                conditioned = isinstance(meaning, dict) and meaning.get("conditions") == ["only offline"]
                if conditioned:
                    choice = "supported" if "only offline" in pair["evidence"] else "unknown"
                else:
                    choice = "contradicted" if "not retained while online" in pair["evidence"] else "unknown"
            answers[key] = {"type": "choice", "choice": choice,
                "probabilities": {name: float(name == choice) for name in question["criteria"]}}
        return JevResult(model="jev-1.13.0", answers=answers, input_tokens=None)

    world.jev.system_one = scoped_oracle
    await world.worker.cycle()
    view = await world.inspect("health:claim:" + claim.id)
    assert view["health"]["support"] == "supported"
    assert view["health"]["needs_review"] is False
    assert view["health"]["freshness"] == "unknown" and view["health"]["operator_review"] is None
    rows, _ = await world.store.search_lexical(world.operator, world.binding_id, ["CacheKey"], None,
        request_digest=hashlib.sha256(b"qualified-health-after-online-correction").hexdigest())
    assert claim.id in {row[0].id for row in rows}


async def health_backlog(world, authority, *, enabled=True, allow=False, with_claim=True):
    if with_claim:
        claim = await health_work(world, authority, allow=allow)
        [initial] = await world.rows(
            "SELECT source_ids FROM am_pending_judgments WHERE binding_id=$1 AND kind='health'",
            world.binding_id,
        )
        source_refs = [RevisionRef(id=value, revision=1) for value in initial["source_ids"]]
        claim_refs = [RevisionRef(id=claim.id, revision=claim.revision)]
        existing = 1
    else:
        await world.application.health(world.operator, HealthPolicyCommand(
            binding_id=world.binding_id, expected_binding_revision=1, idempotency_key="backlog-policy",
            expected_policy_revision=0, enabled=True, allow_jev_health=allow,
        ))
        captured = await world.store.capture(world.operator, CaptureCommand(
            binding_id=world.binding_id, idempotency_key="backlog-source", origin_key="backlog-source",
            body="Captured window without a published memory.", speaker="human", agent_path="observed-agent",
            coverage=CaptureCoverage(status="observed_window"),
        ))
        current = SimpleNamespace(store=world.store, actor=world.operator, binding_id=world.binding_id)
        await world.store.record(world.operator, await source_selection(
            current, captured.source_id, key="backlog-discard", label="discard",
        ))
        source_refs = [RevisionRef(id=captured.source_id, revision=1)]
        claim_refs = []
        existing = 0
    for index in range(existing, 33):
        await world.application.health(world.operator, SessionObservationCommand(
            binding_id=world.binding_id, expected_binding_revision=1, idempotency_key=f"backlog-close-{index}",
            stream_id="backlog_stream", segment_id=f"backlog_segment_{index}", event_id=f"backlog_end_{index}",
            sequence=1, event="end", agent_path="observed-agent", source_refs=source_refs,
            claim_refs=claim_refs, coverage="partial",
        ))
    if not enabled:
        await world.application.health(world.operator, HealthPolicyCommand(
            binding_id=world.binding_id, expected_binding_revision=1, idempotency_key="backlog-disable",
            expected_policy_revision=1, enabled=False, allow_jev_health=False,
        ))
    rows = await world.rows(
        """SELECT id,sequence,state,health_revision,snapshot FROM am_pending_judgments
            WHERE binding_id=$1 AND kind='health' ORDER BY sequence""", world.binding_id,
    )
    assert len(rows) == 33 and {row["state"] for row in rows} == {"pending"}
    assert {row["snapshot"] for row in rows} == {None}
    assert (await world.inspect("pending"))["partial"] is True
    return rows


@pytest.mark.parametrize("enabled", [False, True], ids=["health-disabled", "purpose-denied"])
@pytest.mark.parametrize("consumer", ["selection", "cleanup", "later-binding", "later-snapshot"])
async def test_disabled_health_backlog_preserves_ordinary_worker_progress(world, authority, enabled, consumer):
    target_binding = world.binding_id
    if consumer == "later-binding":
        added = await world.store.register_binding(world.operator, "Later worker binding", None, "worker-later-binding")
        world.operator = await world.store.authenticate(TOKEN)
        await world.store.grant_binding(world.operator, load_state(world.settings).credential_id, added.id)
        world.binding_id, target_binding = sorted((world.binding_id, added.id))
        agent = await world.store.authenticate(read_worker_token(world.settings))
        assert agent.bindings.index(world.binding_id) < agent.bindings.index(target_binding)
    backlog = await health_backlog(world, authority, enabled=enabled)
    health_calls = health_provider(world)
    world.jev.relation = ("supports", 0.95)
    if consumer == "cleanup":
        current = SimpleNamespace(store=world.store, actor=world.operator, binding_id=world.binding_id)
        await ready_claim(current, key="after-health-claim", body="CacheKey remains retained only offline.")
        await world.store.schedule_cleanup()
        [pending] = await world.rows(
            "SELECT id,sequence FROM am_pending_judgments WHERE binding_id=$1 AND kind='cleanup' AND state='pending'",
            world.binding_id,
        )
    else:
        captured = await world.store.capture(world.operator, CaptureCommand(
            binding_id=target_binding, idempotency_key="after-health-source", origin_key="after-health-source",
            body="ok thanks!", speaker="human", snapshot="snapshot_later" if consumer == "later-snapshot" else None,
        ))
        [pending] = await world.rows(
            "SELECT id,sequence FROM am_pending_judgments WHERE binding_id=$1 AND source_ids=$2::text[]",
            target_binding, [captured.source_id],
        )
    assert pending["sequence"] > backlog[-1]["sequence"]

    more = await world.worker.cycle()

    [finished] = await world.rows("SELECT state FROM am_pending_judgments WHERE id=$1", pending["id"])
    assert finished["state"] == "resolved"
    if consumer == "cleanup":
        judgments = await world.rows(
            "SELECT credential_id FROM am_claim_judgments WHERE binding_id=$1", world.binding_id,
        )
        assert len(judgments) == 1
        assert judgments[0]["credential_id"] == load_state(world.settings).credential_id
        relations = await world.rows(
            "SELECT kind FROM am_relations WHERE binding_id=$1 AND state='active'", world.binding_id,
        )
        assert relations == [{"kind": "supports"}]
    else:
        [selection] = await world.rows(
            "SELECT label,state,credential_id FROM am_source_selections WHERE source_id=$1", captured.source_id,
        )
        assert selection["label"] == "discard" and selection["state"] == "active"
        assert selection["credential_id"] == load_state(world.settings).credential_id
    assert more is False
    assert health_calls == [] and len(world.jev.calls) == 1
    assert await world.pending("health") == ["pending"] * 33


async def test_disabled_health_backlog_reaches_real_worker_cadence_without_status_spin(world, authority, monkeypatch):
    await health_backlog(world, authority)
    health_calls = health_provider(world)
    cadence = asyncio.Event()
    snapshots = []
    persist = worker_module.save_worker_snapshot
    wake_wait = world.worker._wake.wait

    def observed_snapshot(settings, value):
        persist(settings, value)
        snapshots.append(value)
        if len(snapshots) == 3:
            world.worker._stop.set()
            world.worker.notify()

    async def observed_wait():
        cadence.set()
        return await wake_wait()

    monkeypatch.setattr(worker_module, "save_worker_snapshot", observed_snapshot)
    monkeypatch.setattr(world.worker._wake, "wait", observed_wait)
    world.worker.start()
    try:
        await asyncio.wait_for(cadence.wait(), 5)
        assert len(snapshots) == 1
        assert snapshots[0]["phase"] == "waiting"
        assert health_calls == [] and world.jev.calls == []
        assert await world.pending("health") == ["pending"] * 33
    finally:
        drained = await world.worker.stop()
        assert drained["local_drained"] is True
        await world.worker.wait_closed()


async def test_incomplete_health_backlog_does_not_starve_a_later_source(world, authority):
    await health_backlog(world, authority, allow=True, with_claim=False)
    health_calls = health_provider(world)
    captured = await world.capture("after-incomplete-health", "ok thanks!")

    more = await world.worker.cycle()

    [selection] = await world.rows(
        "SELECT label,state FROM am_source_selections WHERE source_id=$1", captured.source_id,
    )
    assert selection == {"label": "discard", "state": "active"}
    assert more is False
    assert health_calls == [] and len(world.jev.calls) == 1
    assert await world.pending("health") == ["pending"] * 33
    assert await world.rows(
        "SELECT id FROM am_health_events WHERE binding_id=$1 AND kind='health_assessment'", world.binding_id,
    ) == []


class HealthProtocolPeer:
    def __init__(self, failure):
        self.failure = failure
        self.calls = []
        self.on_health = None

    @property
    def health_calls(self):
        return [call for call in self.calls if any(
            key.startswith(("evidence_", "relevance_", "support_")) for key in call["questions"]
        )]

    def open(self, request, timeout=None):
        payload = json.loads(request.data)
        self.calls.append(payload)
        health = any(key.startswith(("evidence_", "relevance_", "support_")) for key in payload["questions"])
        if health and self.on_health is not None:
            self.on_health()
        if health and self.failure == "request":
            raise http_error(400)
        answers = {}
        if not health or self.failure != "response":
            for key, question in payload["questions"].items():
                if question["type"] == "noul":
                    answers[key] = {"type": "noul", "noul": 0.04}
                    continue
                chosen = "s0" if key.startswith("evidence_") else (
                    "related" if key.startswith("relevance_") else "supported"
                )
                answers[key] = {"type": "choice", "choice": chosen,
                    "probabilities": {name: float(name == chosen) for name in question["criteria"]}}
        return io.BytesIO(json.dumps({"model": "jev-1.13.0", "answers": answers}).encode())


def health_protocol_worker(world, failure):
    peer = HealthProtocolPeer(failure)

    def factory(key, model):
        assert key == KEY and model == "jev-1.13.0"
        return JevClient(key, model, opener=peer)

    world.worker = JudgeWorker(world.settings, world.store, world.application, client_factory=factory)
    world.application.judge = world.worker
    return peer


@pytest.mark.parametrize("failure", ["request", "response"])
async def test_unchanged_failed_health_is_not_repaid_and_does_not_starve_source(world, authority, failure):
    claim = await health_work(world, authority)
    peer = health_protocol_worker(world, failure)
    await world.worker.cycle()
    assert len(peer.health_calls) == 1
    captured = await world.capture("after-failed-health", "ok thanks!")

    await world.worker.cycle()
    more = await world.worker.cycle()

    [selection] = await world.rows(
        "SELECT label,state FROM am_source_selections WHERE source_id=$1", captured.source_id,
    )
    assert selection == {"label": "discard", "state": "active"}
    assert len(peer.health_calls) == 1 and len(peer.calls) == 2
    assert more is False and await world.pending("health") == ["pending"]
    assert (await world.inspect("health:claim:" + claim.id))["health"]["support"] == "unknown"
    assert await world.rows(
        "SELECT id FROM am_health_events WHERE binding_id=$1 AND kind='health_assessment'", world.binding_id,
    ) == []


@pytest.mark.parametrize("malformed", ["claim", "source"])
async def test_malformed_nested_health_input_preserves_work_and_reaches_next_source(
    world, authority, monkeypatch, malformed,
):
    claim = await health_work(world, authority)
    peer = health_protocol_worker(world, None)
    original = world.application.inspect
    marker = "private-invalid-health-input"

    async def malformed_inspection(actor, ref, binding_id=None, snapshot=None, **kwargs):
        bundle = await original(actor, ref, binding_id, snapshot, **kwargs)
        if ref.startswith("health:item:"):
            bundle = json.loads(json.dumps(bundle))
            if malformed == "claim":
                bundle["claims"][0]["polarity"] = marker
            else:
                bundle["input_sources"][0]["revision"] = 0
        return bundle

    monkeypatch.setattr(world.application, "inspect", malformed_inspection)
    captured = await world.capture("after-malformed-health-" + malformed, "ok thanks!")
    more = await world.worker.cycle()
    [selection] = await world.rows(
        "SELECT label,state FROM am_source_selections WHERE source_id=$1", captured.source_id,
    )
    assert selection == {"label": "discard", "state": "active"}
    assert more is False and await world.pending("health") == ["pending"]
    assert peer.health_calls == [] and len(peer.calls) == 1
    assert marker not in (world.worker.last_error or "")
    assert (await world.inspect("health:claim:" + claim.id))["health"]["support"] == "unknown"
    assert await world.rows(
        "SELECT id FROM am_health_events WHERE binding_id=$1 AND kind='health_assessment'", world.binding_id,
    ) == []


@pytest.mark.parametrize("changed", ["health_revision", "policy_revision", "both"])
async def test_failed_health_becomes_eligible_for_changed_work_or_policy(world, authority, changed):
    claim = await health_work(world, authority)
    peer = health_protocol_worker(world, "response")
    await world.worker.cycle()
    [before] = await world.rows(
        "SELECT id,health_revision FROM am_pending_judgments WHERE binding_id=$1 AND kind='health'", world.binding_id,
    )
    assert len(peer.health_calls) == 1 and await world.pending("health") == ["pending"]
    if changed in {"health_revision", "both"}:
        await world.application.health(world.operator, SessionObservationCommand(
            binding_id=world.binding_id, expected_binding_revision=1, idempotency_key="worker-health-checkpoint",
            stream_id="health_worker_stream", segment_id="health_worker_segment", event_id="health_worker_checkpoint",
            sequence=3, event="checkpoint", agent_path="observed-agent", coverage="observed_segment",
        ))
    if changed in {"policy_revision", "both"}:
        await world.application.health(world.operator, HealthPolicyCommand(
            binding_id=world.binding_id, expected_binding_revision=1, idempotency_key="worker-health-new-policy",
            expected_policy_revision=1, enabled=True, allow_jev_health=True,
        ))
    [after] = await world.rows(
        "SELECT id,health_revision FROM am_pending_judgments WHERE binding_id=$1 AND kind='health'", world.binding_id,
    )
    assert after["id"] == before["id"]
    assert (after["health_revision"] > before["health_revision"]) is (changed != "policy_revision")
    assert (await world.store.health_policy(world.operator, world.binding_id))["revision"] == (
        1 if changed == "health_revision" else 2
    )
    peer.failure = None

    more = await world.worker.cycle()

    assert await world.pending("health") == ["resolved"]
    assert len(peer.health_calls) == 3 and more is False
    view = await world.inspect("health:claim:" + claim.id)
    assert view["health"]["support"] == "supported" and view["health"]["freshness"] == "unknown"
    [event] = await world.rows(
        """SELECT credential_id FROM am_health_events
            WHERE binding_id=$1 AND target_ref=$2 AND kind='health_assessment'""", world.binding_id, claim.id,
    )
    assert event["credential_id"] == load_state(world.settings).credential_id
    assert world.worker.counts.health_assessments_recorded == 1


async def test_health_admission_failure_is_not_repaid_until_observed_work_changes(world, authority):
    claim = await health_work(world, authority)
    peer = health_protocol_worker(world, None)
    loop = asyncio.get_running_loop()

    async def reject_inspected_claim():
        view = await world.inspect("health:claim:" + claim.id)
        await world.application.health(world.operator, MemoryReviewCommand(
            binding_id=world.binding_id, expected_binding_revision=1, idempotency_key="health-inflight-reject",
            admission_id=view["admission"]["id"], claim_ref=RevisionRef(id=claim.id, revision=claim.revision),
            expected_health_version=view["health"]["version"], decision="reject",
            reason="Operator rejects this exact memory while the old health admission is in flight.",
        ))

    def invalidate_admission():
        peer.on_health = None
        asyncio.run_coroutine_threadsafe(reject_inspected_claim(), loop).result()

    peer.on_health = invalidate_admission
    await world.worker.cycle()
    first_requests = len(peer.health_calls)
    assert await world.pending("health") == ["pending"]
    assert world.worker.last_error == "HEALTH_PENDING_REVIEW"
    assert (await world.inspect("health:claim:" + claim.id))["health"]["operator_review"] == "reject"
    captured = await world.capture("after-stale-health-admission", "ok thanks!")

    more = await world.worker.cycle()

    [selection] = await world.rows(
        "SELECT label,state FROM am_source_selections WHERE source_id=$1", captured.source_id,
    )
    assert selection == {"label": "discard", "state": "active"}
    assert len(peer.health_calls) == first_requests and more is False
    assert await world.pending("health") == ["pending"]
    assert await world.rows(
        "SELECT id FROM am_health_events WHERE binding_id=$1 AND kind='health_assessment'", world.binding_id,
    ) == []

    await world.application.health(world.operator, SessionObservationCommand(
        binding_id=world.binding_id, expected_binding_revision=1, idempotency_key="health-after-review-checkpoint",
        stream_id="health_worker_stream", segment_id="health_worker_segment", event_id="health_after_review",
        sequence=3, event="checkpoint", agent_path="observed-agent", coverage="observed_segment",
    ))
    await world.worker.cycle()

    assert await world.pending("health") == ["resolved"]
    view = await world.inspect("health:claim:" + claim.id)
    assert view["health"]["operator_review"] == "reject"
    assert world.worker.counts.health_assessments_recorded == 1


@pytest.mark.parametrize("allow_health", [True, False])
async def test_next_worker_judgment_uses_authorized_exact_reject_without_blacklisting_source(
    world, authority, allow_health,
):
    claim = await health_work(world, authority, allow=allow_health)
    reason = "CacheKey retention is disputed; do not confidently repeat thirty days."
    view = await world.inspect("health:claim:" + claim.id)
    await world.application.health(world.operator, MemoryReviewCommand(
        binding_id=world.binding_id, expected_binding_revision=1, idempotency_key="worker-next-review",
        admission_id=view["admission"]["id"], claim_ref=RevisionRef(id=claim.id, revision=claim.revision),
        expected_health_version=view["health"]["version"], decision="reject", reason=reason,
    ))
    world.jev.remember_default = 0.95
    original = world.jev.system_one

    def reasoned_judgment(state, questions, *, before_attempt):
        result = original(state, questions, before_attempt=before_attempt)
        advice = state.get("health_dispositions", [])
        if not any(item.get("decision") == "reject" and item.get("reason") == reason for item in advice):
            return result
        spans = {span["id"]: span["text"] for span in state.get("spans", [])}
        answers = dict(result.answers)
        for key in questions:
            if key.startswith("remember_") and "thirty days" in spans.get(key.removeprefix("remember_"), ""):
                answers[key] = {"type": "noul", "noul": 0.5}
        return JevResult(result.model, answers, result.input_tokens)

    world.jev.system_one = reasoned_judgment
    health_provider(world)
    disputed = await world.capture("worker-disputed-successor", "CacheKey keeps offline responses for thirty days.")
    independent = await world.capture("worker-independent-successor", "AuditKey has a separate retention owner.")

    await world.worker.cycle()

    selected = await world.rows("SELECT label FROM am_source_selections WHERE source_id=$1", disputed.source_id)
    assert selected == ([] if allow_health else [{"label": "remember"}])
    assert await world.rows(
        "SELECT label FROM am_source_selections WHERE source_id=$1", independent.source_id,
    ) == [{"label": "remember"}]
    if not allow_health:
        assert reason not in json.dumps(world.jev.calls)


def withdrawing_provider(world, withdraw, boundary):
    loop = asyncio.get_running_loop()
    calls = []
    changed = False

    def change():
        nonlocal changed
        if not changed:
            asyncio.run_coroutine_threadsafe(withdraw(), loop).result()
            changed = True

    class Peer:
        def open(self, request, timeout=None):
            payload = json.loads(request.data)
            calls.append(payload)
            if boundary in {"retry", "support"}:
                change()
            if boundary == "retry" and len(calls) == 1:
                raise http_error(503, {"Retry-After": "0"})
            answers = {}
            for key, question in payload["questions"].items():
                if question["type"] == "noul":
                    answers[key] = {"type": "noul", "noul": 0.95}
                    continue
                chosen = "s0" if key.startswith("evidence_") else (
                    "related" if key.startswith("relevance_") else (
                        "supported" if key.startswith("support_") else next(iter(question["criteria"]))
                    )
                )
                answers[key] = {"type": "choice", "choice": chosen,
                    "probabilities": {name: float(name == chosen) for name in question["criteria"]}}
            return io.BytesIO(json.dumps({"model": "jev-1.13.0", "answers": answers}).encode())

    client = JevClient(KEY, "jev-1.13.0", opener=Peer(), sleep=lambda _: None)

    def system_one(state, questions, *, before_attempt):
        if boundary == "first":
            change()
        return client.system_one(state, questions, before_attempt=before_attempt)

    world.jev.system_one = system_one
    return calls


@pytest.mark.parametrize("boundary", ["first", "retry", "support"])
async def test_health_withdrawal_blocks_new_actual_jev_dispatches(world, authority, boundary):
    claim = await health_work(world, authority)
    [source] = await world.rows("SELECT source_id FROM am_claim_sources WHERE claim_id=$1", claim.id)

    async def withdraw():
        await world.store.retract(world.operator, world.binding_id, source["source_id"], "worker-health-withdraw")

    calls = withdrawing_provider(world, withdraw, boundary)

    await world.worker.cycle()

    assert len(calls) == (0 if boundary == "first" else 1)
    assert await world.pending("health") == ["retracted"]
    assert await world.rows(
        "SELECT id FROM am_health_events WHERE binding_id=$1 AND kind='health_assessment'", world.binding_id,
    ) == []
    assert world.worker.counts.health_assessments_recorded == 0


async def test_source_withdrawal_blocks_first_actual_jev_dispatch(world):
    source = await world.capture("worker-source-withdraw", "AuditKey has a separate retention owner.")

    async def withdraw():
        await world.store.retract(world.operator, world.binding_id, source.source_id, "worker-source-withdraw")

    calls = withdrawing_provider(world, withdraw, "first")

    await world.worker.cycle()

    assert calls == []
    assert await world.rows("SELECT id FROM am_source_selections WHERE source_id=$1", source.source_id) == []


async def test_authorized_health_advice_cannot_expand_source_past_operator_input_budget(world, authority):
    claim = await health_work(world, authority)
    await world.application.health(world.operator, HealthPolicyCommand(
        binding_id=world.binding_id, expected_binding_revision=1, idempotency_key="worker-small-health-budget",
        expected_policy_revision=1, enabled=True, allow_jev_health=True, max_audit_bytes=1024,
    ))
    view = await world.inspect("health:claim:" + claim.id)
    await world.application.health(world.operator, MemoryReviewCommand(
        binding_id=world.binding_id, expected_binding_revision=1, idempotency_key="worker-budget-review",
        admission_id=view["admission"]["id"], claim_ref=RevisionRef(id=claim.id, revision=claim.revision),
        expected_health_version=view["health"]["version"], decision="reject",
        reason="This exact retention memory is disputed.",
    ))
    world.jev.remember_default = 0.95
    health_provider(world)
    oversized = await world.capture(
        "worker-over-health-budget", "PrivateBudgetBoundary has an owned synthetic retention constraint. " * 24,
    )
    independent = await world.capture("worker-within-health-budget", "AuditKey has a separate retention owner.")

    await world.worker.cycle()

    assert not any("PrivateBudgetBoundary" in span["text"]
                   for state, _ in world.jev.calls for span in state.get("spans", []))
    assert await world.rows("SELECT id FROM am_source_selections WHERE source_id=$1", oversized.source_id) == []
    assert await world.rows(
        "SELECT label FROM am_source_selections WHERE source_id=$1", independent.source_id,
    ) == [{"label": "remember"}]
