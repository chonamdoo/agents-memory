from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from agents_memory.capture_guard import contains_source_secret
from agents_memory.domain import (
    CaptureCommand,
    ContextCommand,
    DomainError,
    EffectState,
    FeedbackCommand,
    RecordCommand,
    RelevanceJudgment,
    RuleProposal,
    reject_source_secrets,
)
from agents_memory.jobs import CleanupScheduler


@pytest.mark.parametrize("text,secret", [
    ("ghp_" + "a" * 36, True),
    ("-----BEGIN PRIVATE KEY-----\n" + "A" * 64 + "\n-----END PRIVATE KEY-----", True),
    ("-----BEGIN PRIVATE KEY-----\n" + " " * 64 + "\n-----END PRIVATE KEY-----", False),
    ("Do not export. Preserve exceptions and negation. 예외도 보존합니다.", False),
])
def test_pure_secret_predicate_and_domain_refusal_agree_without_echo(text, secret):
    assert contains_source_secret(text) is secret
    if secret:
        with pytest.raises(DomainError) as caught:
            reject_source_secrets(text)
        assert caught.value.code == "SOURCE_SECRET_REJECTED"
        assert caught.value.status == 422 and caught.value.effect == EffectState.NOT_STARTED
        assert text not in json.dumps(caught.value.public()) and text not in str(caught.value)
    else:
        assert reject_source_secrets(text) is None
        command = CaptureCommand(binding_id="binding-001", idempotency_key="capture-001", origin_key="origin-001", body=text, speaker="human")
        assert command.body.encode() == text.encode()


@pytest.mark.parametrize("factory", [
    lambda secret: CaptureCommand(binding_id="binding-001", idempotency_key="capture-001", origin_key="origin-001", body=secret, speaker="human"),
    lambda secret: RecordCommand(idempotency_key="record-001", body=secret),
    lambda secret: FeedbackCommand(idempotency_key="feedback-001", target_ref="claim-001", kind="reject", body=secret),
    lambda secret: RelevanceJudgment(claim_id="claim-001", relevant=True, reason=secret),
    lambda secret: ContextCommand(query=secret),
    lambda secret: ContextCommand(query="ordinary", paths=(secret,)),
    lambda secret: ContextCommand(query="ordinary", query_expansions=(secret,)),
    lambda secret: RuleProposal(binding_id="binding-001", idempotency_key="proposal-001", body=secret),
    lambda secret: RuleProposal(binding_id="binding-001", idempotency_key="proposal-001", body="ordinary", exceptions=(secret,)),
])
def test_domain_callers_share_body_free_secret_refusal(factory):
    secret = "ghp_" + "a" * 36
    with pytest.raises(DomainError) as caught:
        factory(secret)
    assert caught.value.code == "SOURCE_SECRET_REJECTED" and caught.value.status == 422
    assert caught.value.effect == EffectState.NOT_STARTED
    assert secret not in json.dumps(caught.value.public())
    assert secret not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("domain_failure", [False, True])
async def test_scheduler_emits_exception_type_and_operation_without_secret_or_traceback(caplog, domain_failure):
    secret = "ghp_" + "a" * 36
    failure = DomainError("SERVICE_DRAINING", secret) if domain_failure else RuntimeError(secret)
    entered = asyncio.Event()

    class PendingStore:
        async def schedule_cleanup(self):
            entered.set()
            raise failure

    scheduler = CleanupScheduler(SimpleNamespace(cleanup_interval_seconds=3600), PendingStore())
    scheduler.start()
    await asyncio.wait_for(entered.wait(), 1)
    assert (await scheduler.stop())["local_drained"] is True
    records = [record for record in caplog.records if record.name == "agents_memory.jobs"]
    assert len(records) == 1
    record, = records
    assert type(failure).__name__ in record.getMessage() and "schedule_cleanup" in record.getMessage()
    assert record.exc_info is None and record.stack_info is None
    assert secret not in caplog.text and secret not in str(scheduler.status)
    assert scheduler.last_error == ("SERVICE_DRAINING" if domain_failure else "CLEANUP_AUTHORITY_UNAVAILABLE")
    assert scheduler.last_result is None


@pytest.mark.asyncio
async def test_scheduler_success_after_failure_clears_error_without_warning(caplog):
    calls = 0

    class PendingStore:
        async def schedule_cleanup(self):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("private database body")
            scheduler._stop.set()
            return {"pending": 0}

    scheduler = CleanupScheduler(SimpleNamespace(cleanup_interval_seconds=0), PendingStore())
    await scheduler.run()
    assert calls == 2
    assert scheduler.last_error is None and scheduler.last_result == {"pending": 0}
    records = [record for record in caplog.records if record.name == "agents_memory.jobs"]
    assert len(records) == 1
    assert "private database body" not in caplog.text
