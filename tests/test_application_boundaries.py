from __future__ import annotations

import json

import pytest
from test_store_authority import authority as authority
from test_store_authority import ready_claim

from agents_memory.application import Application
from agents_memory.domain import (
    ContextCommand,
    DomainError,
    RelevanceJudgment,
    RuleApproval,
    RuleProposal,
    RuleScope,
)


def decisions(pool, *, relevant=True):
    return tuple(
        RelevanceJudgment(claim_id=item["claim_id"], relevant=relevant, reason="Caller inspected the candidate evidence.")
        for item in pool["candidate_manifest"]
    )


async def test_candidates_never_become_injected_memory_without_agent_relevance(authority):
    _, claim = await ready_claim(authority)
    application = Application(authority.store.settings, authority.store)
    request = ContextCommand(binding_id=authority.binding_id, query="CacheKey")

    pool = await application.context(authority.actor, request)

    assert pool["status"] == "judgment_required"
    assert [item["claim_id"] for item in pool["candidate_manifest"]] == [claim.id]
    assert pool["refs"] == []
    assert claim.draft.statement not in pool["context"]
    selected = await application.context(authority.actor, request.model_copy(update={
        "admission_id": pool["admission_id"], "relevance": decisions(pool),
    }))
    assert selected["refs"] == [claim.id]
    payload = json.loads(selected["context"])
    assert payload["memory_candidates"][0]["statement"] == claim.draft.statement
    assert payload["memory_candidates"][0]["conditions"] == ["only offline"]
    assert payload["memory_candidates"][0]["evidence"][0]["source_speaker"] == "human"


async def test_caller_query_expansion_finds_candidates_without_server_semantic_guess(authority):
    _, claim = await ready_claim(authority)
    application = Application(authority.store.settings, authority.store)
    request = ContextCommand(binding_id=authority.binding_id, query="TTL")
    initial = await application.context(authority.actor, request)
    assert initial["candidate_manifest"] == []

    expanded = request.model_copy(update={"query_expansions": ("CacheKey",)})
    pool = await application.context(authority.actor, expanded)
    assert [item["claim_id"] for item in pool["candidate_manifest"]] == [claim.id]
    assert pool["refs"] == []
    selected = await application.context(authority.actor, expanded.model_copy(update={
        "admission_id": pool["admission_id"], "relevance": decisions(pool),
    }))
    assert selected["refs"] == [claim.id]


async def test_agent_may_reject_all_admitted_recall_candidates(authority):
    _, claim = await ready_claim(authority)
    application = Application(authority.store.settings, authority.store)
    request = ContextCommand(binding_id=authority.binding_id, query="CacheKey")
    pool = await application.context(authority.actor, request)
    result = await application.context(authority.actor, request.model_copy(update={
        "admission_id": pool["admission_id"], "relevance": decisions(pool, relevant=False),
    }))
    assert result["refs"] == []
    assert claim.draft.statement not in result["context"]
    assert result["judgment_required"] is False
    assert (await authority.store.claim(authority.actor, authority.binding_id, claim.id)).id == claim.id


async def test_relevance_must_cover_complete_saved_manifest(authority):
    await ready_claim(authority, "first")
    await ready_claim(authority, "second")
    application = Application(authority.store.settings, authority.store)
    request = ContextCommand(binding_id=authority.binding_id, query="CacheKey")
    pool = await application.context(authority.actor, request)
    with pytest.raises(DomainError) as caught:
        await application.context(authority.actor, request.model_copy(update={
            "admission_id": pool["admission_id"], "relevance": decisions(pool)[:1],
        }))
    assert caught.value.code == "RELEVANCE_MANIFEST_INVALID"


async def test_saved_relevance_cannot_be_reused_for_changed_query(authority):
    await ready_claim(authority)
    application = Application(authority.store.settings, authority.store)
    request = ContextCommand(binding_id=authority.binding_id, query="CacheKey")
    pool = await application.context(authority.actor, request)
    with pytest.raises(DomainError) as caught:
        await application.context(authority.actor, request.model_copy(update={
            "query": "DifferentKey", "admission_id": pool["admission_id"], "relevance": decisions(pool),
        }))
    assert caught.value.code == "ADMISSION_STALE"


async def test_retraction_between_candidate_read_and_judgment_prevents_delivery(authority):
    operation, _ = await ready_claim(authority)
    application = Application(authority.store.settings, authority.store)
    request = ContextCommand(binding_id=authority.binding_id, query="CacheKey")
    pool = await application.context(authority.actor, request)
    await authority.store.retract(authority.actor, authority.binding_id, operation.source_id, "retract-before-relevance")
    with pytest.raises(DomainError) as caught:
        await application.context(authority.actor, request.model_copy(update={
            "admission_id": pool["admission_id"], "relevance": decisions(pool),
        }))
    assert caught.value.code == "ADMISSION_STALE"


async def test_final_delivery_rechecks_retraction_after_relevance_admission(authority, monkeypatch):
    operation, _ = await ready_claim(authority)
    store, actor = authority.store, authority.actor
    application = Application(store.settings, store)
    request = ContextCommand(binding_id=authority.binding_id, query="CacheKey")
    pool = await application.context(actor, request)
    original = store.delivery

    async def retract_before_delivery(*args, **kwargs):
        await store.retract(actor, authority.binding_id, operation.source_id, "retract-at-delivery")
        return await original(*args, **kwargs)

    monkeypatch.setattr(store, "delivery", retract_before_delivery)
    with pytest.raises(DomainError):
        await application.context(actor, request.model_copy(update={
            "admission_id": pool["admission_id"], "relevance": decisions(pool),
        }))


async def test_causal_capture_is_not_claim_readiness(authority):
    operation, _ = await ready_claim(authority)
    with pytest.raises(DomainError) as caught:
        await Application(authority.store.settings, authority.store).context(
            authority.actor, ContextCommand(binding_id=authority.binding_id, query="CacheKey", causal_operation=operation.id),
        )
    assert caught.value.code == "CAUSAL_NOT_READY"


async def test_required_rules_are_deliverable_independently_of_candidate_relevance(authority):
    store, actor = authority.store, authority.actor
    proposal = await store.propose_rule(actor, RuleProposal(
        binding_id=authority.binding_id, idempotency_key="mandatory-rule", body="Keep project artifacts inside this project.", required=True,
    ))
    await store.approve_rule(actor, RuleApproval(
        proposal_id=proposal["proposal_id"], expected_digest=proposal["digest"], scope=RuleScope.LOCAL_PROJECT,
        target_bindings=(authority.binding_id,), target_set_revision=proposal["target_set_revision"],
        idempotency_key="mandatory-rule-approval",
    ))
    _, claim = await ready_claim(authority)
    result = await Application(store.settings, store).context(actor, ContextCommand(binding_id=authority.binding_id, query="CacheKey"))
    assert "Keep project artifacts inside this project." in result["context"]
    assert claim.draft.statement not in result["context"]
    assert result["refs"] == []
    assert result["status"] == "judgment_required"


async def test_optional_approved_rules_are_delivered_when_recall_has_no_memory_candidates(authority):
    store, actor = authority.store, authority.actor
    proposal = await store.propose_rule(actor, RuleProposal(
        binding_id=authority.binding_id, idempotency_key="optional-alone",
        body="Use the offline project formatter.", required=False,
    ))
    rule = await store.approve_rule(actor, RuleApproval(
        proposal_id=proposal["proposal_id"], expected_digest=proposal["digest"], scope=RuleScope.LOCAL_PROJECT,
        target_bindings=(authority.binding_id,), target_set_revision=proposal["target_set_revision"],
        idempotency_key="optional-alone-approval",
    ))
    result = await Application(store.settings, store).context(
        actor, ContextCommand(binding_id=authority.binding_id, query="No memories exist"),
    )
    assert result["candidate_manifest"] == [] and result["judgment_required"] is False
    assert result["status"] in {"ready", "partial"} and result["refs"] == []
    assert json.loads(result["context"])["approved_rules"][0]["body"] == rule.body
    assert result["stamp"]["rules"] == [[rule.id, rule.revision, rule.digest]]
