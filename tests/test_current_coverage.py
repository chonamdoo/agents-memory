from __future__ import annotations

from test_company_authority import capture, judgment
from test_company_authority import company as company
from test_source_judgment_history import inspected_selection, record_selection

from agents_memory.domain import FeedbackCommand


async def test_global_source_judged_for_a_is_unclassified_for_b(company):
    source = await capture(company, key="coverage-global")
    await company.store.record(company.actor, await judgment(
        company, source.source_id, "coverage-a", snapshot="A"))
    a = await company.store.stats(company.actor, company.binding_id, "A")
    b = await company.store.stats(company.actor, company.binding_id, "B")
    assert a["coverage"]["unclassified_sources"] == 0
    assert a["coverage"]["incomplete_sources"] == 0
    assert b["coverage"]["unclassified_sources"] == 1
    assert b["coverage"]["incomplete_sources"] == 1
    assert b["classification_labels"].get("remember", 0) == 0


async def test_previous_policy_selection_does_not_count_current_coverage(company):
    source = await capture(company, key="coverage-policy")
    selection = await company.store.record(company.actor, await judgment(
        company, source.source_id, "coverage-policy-select"))
    async with company.store.pool.acquire() as connection:
        await connection.execute(
            "UPDATE am_source_selections SET policy_revision=$2 WHERE id=$1",
            selection.artifact_id, "0" * 64)
    stats = await company.store.stats(company.actor, company.binding_id)
    assert stats["coverage"]["unclassified_sources"] == 1
    assert stats["coverage"]["incomplete_sources"] == 1
    assert stats["classification_labels"].get("remember", 0) == 0


async def test_withdrawn_comparison_dependency_removes_current_coverage(company):
    rejected = await capture(company, key="coverage-rejected", body="OldKey is retained offline.")
    feedback = await company.store.feedback(company.actor, FeedbackCommand(
        binding_id=company.binding_id, idempotency_key="coverage-reject",
        target_ref=rejected.source_id, kind="reject", body="The old assertion is not retained."))
    source = await capture(company, key="coverage-independent", body="CacheKey is retained offline.")
    request, window = await inspected_selection(company, source.source_id, "coverage-compare", publish=False)
    assert feedback.artifact_id in {item["id"] for item in window["judgment_context"]["rejections"]}
    await record_selection(company, request)
    before = await company.store.stats(company.actor, company.binding_id)
    assert before["classification_labels"].get("remember", 0) == 1
    async with company.store.pool.acquire() as connection:
        await connection.execute("UPDATE am_feedback SET state='retracted' WHERE id=$1", feedback.artifact_id)
    after = await company.store.stats(company.actor, company.binding_id)
    assert after["classification_labels"].get("remember", 0) == 0
    assert after["coverage"]["unclassified_sources"] == before["coverage"]["unclassified_sources"] + 1
    assert after["coverage"]["incomplete_sources"] == before["coverage"]["incomplete_sources"] + 1


async def test_unrelated_epoch_preserves_current_coverage(company):
    source = await capture(company, key="coverage-valid")
    await company.store.record(company.actor, await judgment(company, source.source_id, "coverage-valid-select"))
    before = await company.store.stats(company.actor, company.binding_id)
    await company.store.register_binding(company.actor, "Unrelated", "/synthetic/unrelated", "coverage-unrelated")
    after = await company.store.stats(company.actor, company.binding_id)
    assert after["epoch"] > before["epoch"]
    assert after["coverage"] == before["coverage"]
    assert after["classification_labels"] == before["classification_labels"]