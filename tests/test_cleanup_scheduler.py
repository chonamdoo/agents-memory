from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from agents_memory.domain import DomainError
from agents_memory.jobs import CleanupScheduler


@pytest.mark.asyncio
async def test_scheduler_only_creates_pending_work_and_start_does_not_duplicate_owner():
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = []

    class PendingStore:
        async def schedule_cleanup(self):
            calls.append("pending")
            entered.set()
            await release.wait()
            return {"pending": 2}

    scheduler = CleanupScheduler(SimpleNamespace(cleanup_interval_seconds=3600), PendingStore())
    assert scheduler.status == {"running": False, "scheduling": False, "last_error": None, "last_result": None}
    scheduler.start()
    owner = scheduler._task
    scheduler.start()
    assert scheduler._task is owner
    await asyncio.wait_for(entered.wait(), 1)
    assert scheduler.status["running"] and scheduler.status["scheduling"]
    not_drained = await scheduler.stop(timeout=0)
    assert not_drained["local_drained"] is False and not_drained["durable_work_recoverable"] is True
    release.set()
    drained = await scheduler.stop()
    assert drained["local_drained"] is True and calls == ["pending"]
    assert scheduler.status == {"running": False, "scheduling": False, "last_error": None, "last_result": {"pending": 2}}


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,code", (
    (DomainError("SERVICE_DRAINING", "Authority is draining"), "SERVICE_DRAINING"),
    (RuntimeError("Private database detail"), "CLEANUP_AUTHORITY_UNAVAILABLE"),
))
async def test_scheduler_reports_failure_without_judgment_fallback(failure, code):
    entered = asyncio.Event()

    class PendingStore:
        async def schedule_cleanup(self):
            entered.set()
            raise failure

    scheduler = CleanupScheduler(SimpleNamespace(cleanup_interval_seconds=3600), PendingStore())
    scheduler.start()
    await asyncio.wait_for(entered.wait(), 1)
    result = await scheduler.stop()
    assert result["local_drained"] is True
    assert scheduler.status["last_error"] == code
    assert scheduler.status["last_result"] is None
    assert "Private database detail" not in str(scheduler.status)


@pytest.mark.asyncio
async def test_stopped_scheduler_can_restart_but_never_owns_semantic_jobs():
    entered = asyncio.Queue()

    class PendingStore:
        async def schedule_cleanup(self):
            entered.put_nowait(True)
            return {"pending": 0}

    scheduler = CleanupScheduler(SimpleNamespace(cleanup_interval_seconds=3600), PendingStore())
    for _ in range(2):
        scheduler.start()
        await asyncio.wait_for(entered.get(), 1)
        assert (await scheduler.stop())["local_drained"] is True
    assert entered.empty() and scheduler.status["running"] is False


@pytest.mark.asyncio
async def test_scheduler_continues_partial_batches_without_waiting_an_hour():
    reached_final = asyncio.Event()
    calls = []
    ordinary_ran = asyncio.Event()

    class PendingStore:
        async def schedule_cleanup(self):
            calls.append(len(calls) + 1)
            if len(calls) == 1:
                asyncio.get_running_loop().call_soon(ordinary_ran.set)
                return {"created": 0, "more": True}
            assert ordinary_ran.is_set()
            if len(calls) == 2:
                return {"created": 0, "more": True}
            reached_final.set()
            return {"created": 0, "more": False}

    scheduler = CleanupScheduler(
        SimpleNamespace(cleanup_interval_seconds=3600), PendingStore()
    )
    scheduler.start()
    try:
        await asyncio.wait_for(reached_final.wait(), 1)
    finally:
        drained = await scheduler.stop()
    assert drained["local_drained"] is True
    assert calls == [1, 2, 3]
    assert scheduler.status["last_result"] == {"created": 0, "more": False}


@pytest.mark.asyncio
async def test_continuation_failure_does_not_spin_from_previous_more_result():
    failed = asyncio.Event()
    calls = []

    class PendingStore:
        async def schedule_cleanup(self):
            calls.append(len(calls) + 1)
            if len(calls) == 1:
                return {"created": 0, "more": True}
            failed.set()
            raise DomainError("DELETION_BARRIER", "Private authority detail")

    scheduler = CleanupScheduler(
        SimpleNamespace(cleanup_interval_seconds=3600), PendingStore()
    )
    scheduler.start()
    try:
        await asyncio.wait_for(failed.wait(), 1)
        await asyncio.sleep(0)
        assert calls == [1, 2]
    finally:
        drained = await scheduler.stop()
    assert drained["local_drained"] is True
    assert scheduler.status["last_error"] == "DELETION_BARRIER"
    assert "Private authority detail" not in str(scheduler.status)
