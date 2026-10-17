from __future__ import annotations

import asyncio
import json
import logging

import pytest
from test_edge_boundaries import AGENT_TOKEN, request, tool
from test_store_authority import authority as authority
from uvicorn import Config
from uvicorn.lifespan.on import LifespanOn

from agents_memory.domain import DomainError, Role
from agents_memory.edge import create_app


@pytest.mark.parametrize("owner_name", ["judge", "scheduler", "application"])
async def test_false_drain_keeps_store_open_until_owned_work_finishes(authority, monkeypatch, owner_name):
    await authority.store.issue_token(authority.actor, Role.AGENT, (authority.binding_id,), AGENT_TOKEN)
    edge = create_app(authority.store.settings)
    owner = {"judge": edge.judge, "scheduler": edge.worker, "application": edge.application}[owner_name]
    entered, release, timed_out = asyncio.Event(), asyncio.Event(), asyncio.Event()
    join_entered, close_attempted = asyncio.Event(), asyncio.Event()
    request_task = held_task = None
    original_context = edge.application.context
    original_close = edge.application.store.close
    original_join = getattr(owner, "wait_closed", None)

    async def held_context(actor, command):
        nonlocal held_task
        held_task = asyncio.current_task()
        entered.set()
        await release.wait()
        return await original_context(actor, command)

    async def held_worker():
        nonlocal held_task
        held_task = asyncio.current_task()
        entered.set()
        await release.wait()

    async def observed_join():
        join_entered.set()
        if original_join is not None:
            await original_join()
        else:
            assert held_task is not None
            await asyncio.shield(held_task)

    async def observed_close():
        close_attempted.set()
        await original_close()

    monkeypatch.setattr(owner, "wait_closed", observed_join, raising=False)
    monkeypatch.setattr(edge.application.store, "close", observed_close)
    if owner_name == "application":
        monkeypatch.setattr(edge.application, "context", held_context)
        original_stop = owner.drain
    else:
        monkeypatch.setattr(owner, "run", held_worker)
        original_stop = owner.stop

    async def bounded_stop():
        result = await original_stop(timeout=0)
        assert result["local_drained"] is False
        timed_out.set()
        return result

    monkeypatch.setattr(owner, "drain" if owner_name == "application" else "stop", bounded_stop)
    recovery_stop = edge.recovery.stop
    other_failure = RuntimeError("synthetic independent cleanup failure")

    async def failed_recovery_stop():
        await recovery_stop()
        raise other_failure

    monkeypatch.setattr(edge.recovery, "stop", failed_recovery_stop)

    async def serve():
        nonlocal request_task
        async with edge.inner.router.lifespan_context(edge.inner):
            if owner_name == "application":
                request_task = asyncio.create_task(request(edge, tool({"binding_id": authority.binding_id, "query": "held"})))
            await entered.wait()

    serving = asyncio.create_task(serve())
    waiters = []
    failure = None
    try:
        await asyncio.wait_for(timed_out.wait(), 5)
        waiters = [asyncio.create_task(join_entered.wait()), asyncio.create_task(close_attempted.wait())]
        await asyncio.wait_for(asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED), 5)
        assert join_entered.is_set(), "Outstanding ownership must be joined before authority close"
        assert not close_attempted.is_set()
        assert not serving.done()
        assert edge.application.store.pool is not None
        assert edge.application.accepting is False
        status, body = await request(edge, b"", token=None, path="/readyz", method="GET")
        assert status == 503
        assert json.loads(body)["lifecycle"]["local_drained"] is False
    finally:
        release.set()
        for waiter in waiters:
            waiter.cancel()
        await asyncio.gather(*waiters, return_exceptions=True)
        try:
            await asyncio.wait_for(serving, 5)
        except BaseExceptionGroup as error:
            failure = error
        if request_task is not None:
            await asyncio.wait_for(request_task, 5)
    assert failure is not None
    assert other_failure in failure.exceptions
    assert any(isinstance(error, DomainError) and error.code == "LOCAL_DRAIN_INCOMPLETE" for error in failure.exceptions)
    assert edge.application.store.pool is None
    with pytest.raises(DomainError) as failed:
        edge.raise_for_lifecycle_failure()
    assert failed.value.code == "SERVICE_LIFECYCLE_FAILED"


@pytest.mark.parametrize("stage", ["startup", "shutdown"])
async def test_actual_uvicorn_lifespan_logs_only_body_free_failure_and_preserves_originals(authority, monkeypatch, caplog, stage):
    edge = create_app(authority.store.settings)
    marker = "SYNTHETIC_PRIVATE_PATH_DSN_SOURCE_FRAGMENT"
    private_type = type(marker, (RuntimeError,), {})
    primary = private_type(marker)
    close_failure = RuntimeError(marker + " close")
    close = edge.application.store.close

    async def failed_close():
        await close()
        raise close_failure

    monkeypatch.setattr(edge.application.store, "close", failed_close)
    if stage == "startup":
        async def failed_reconcile():
            raise primary
        monkeypatch.setattr(edge.application.store, "reconcile_journal", failed_reconcile)
    else:
        stop = edge.judge.stop

        async def failed_stop():
            await stop()
            raise primary

        monkeypatch.setattr(edge.judge, "stop", failed_stop)
    lifespan = LifespanOn(Config(edge, lifespan="on", log_config=None, access_log=False))
    with caplog.at_level(logging.ERROR, logger="uvicorn.error"):
        await asyncio.wait_for(lifespan.startup(), 5)
        if stage == "shutdown":
            await asyncio.wait_for(lifespan.shutdown(), 5)
    assert getattr(lifespan, f"{stage}_failed") is True
    assert lifespan.should_exit is True
    assert marker not in caplog.text
    assert "Traceback" not in caplog.text
    assert "SERVICE_LIFECYCLE_FAILED" in caplog.text
    assert edge.lifecycle_failed is True
    assert primary in edge.lifecycle_failures and close_failure in edge.lifecycle_failures
    assert marker not in json.dumps(edge.lifecycle_status)
    with pytest.raises(DomainError) as failed:
        edge.raise_for_lifecycle_failure()
    assert failed.value.code == "SERVICE_LIFECYCLE_FAILED"
    assert marker not in str(failed.value)
