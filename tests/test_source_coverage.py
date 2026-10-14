from __future__ import annotations

import pytest
from test_company_authority import company as company

from agents_memory.domain import CaptureCommand, ContextCommand, FeedbackCommand, RecordCommand


@pytest.mark.parametrize("speaker", ("human", "assistant", "tool", "document"))
@pytest.mark.parametrize("with_rejection", (False, True), ids=("note", "feedback-reason"))
async def test_nonindependent_logs_do_not_poison_context_coverage(company, speaker, with_rejection):
    note = await company.store.record(company.actor, RecordCommand(
        binding_id=company.binding_id, idempotency_key="coverage-note", kind="note",
        body="The caller recorded an observation, not independent evidence.",
    ))
    if with_rejection:
        await company.store.feedback(company.actor, FeedbackCommand(
            binding_id=company.binding_id, idempotency_key="coverage-rejection",
            target_ref=note.source_id, kind="reject",
            body="Do not promote this ungrounded observation to an independent fact.",
        ))

    request = ContextCommand(binding_id=company.binding_id, query="observation")
    drained = await company.application.context(company.actor, request)
    assert drained["partial"] is False
    assert drained["coverage"]["unclassified_sources"] == 0
    assert drained["coverage"]["incomplete_sources"] == 0
    raw = await company.store.source(company.actor, company.binding_id, note.source_id)
    assert raw.body == "The caller recorded an observation, not independent evidence."

    await company.store.capture(company.actor, CaptureCommand(
        binding_id=company.binding_id, idempotency_key="unresolved-evidence",
        origin_key="independent-observation", body="The original observation remains unreviewed.",
        speaker=speaker,
    ))
    unresolved = await company.application.context(company.actor, request)
    assert unresolved["partial"] is True
    assert unresolved["coverage"]["unclassified_sources"] == 1
    assert unresolved["coverage"]["incomplete_sources"] == 1
