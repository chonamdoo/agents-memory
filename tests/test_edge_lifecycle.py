from __future__ import annotations

import asyncio
import json

import pytest
from test_edge_boundaries import AGENT_TOKEN, request, running, tool
from test_store_authority import TOKEN
from test_store_authority import authority as authority

from agents_memory.domain import Role
from agents_memory.edge import create_app


def leaves(error):
    if isinstance(error, BaseExceptionGroup):
        return [leaf for child in error.exceptions for leaf in leaves(child)]
    return [error]


@pytest.mark.parametrize("second_failure", [False, True])
async def test_shutdown_failure_still_joins_real_workers_and_drains_inflight_authority_requests(authority, monkeypatch, second_failure):
    await authority.store.issue_token(authority.actor, Role.AGENT, (authority.binding_id,), AGENT_TOKEN)
    edge = create_app(authority.store.settings)
    recovery_failure = RuntimeError("synthetic recovery stop failure")
    judge_failure = RuntimeError("synthetic judge stop failure")
    recovery_stop, judge_stop = edge.recovery.stop, edge.judge.stop

    async def failed_recovery_stop():
        await recovery_stop()
        raise recovery_failure

    async def failed_judge_stop():
        await judge_stop()
        raise judge_failure

    monkeypatch.setattr(edge.recovery, "stop", failed_recovery_stop)
    if second_failure:
        monkeypatch.setattr(edge.judge, "stop", failed_judge_stop)
    entered, release = asyncio.Event(), asyncio.Event()
    context = edge.application.context

    async def held_context(actor, command):
        entered.set()
        await release.wait()
        return await context(actor, command)

    monkeypatch.setattr(edge.application, "context", held_context)
    observations = {}

    async def release_during_shutdown():
        while edge.application.accepting:
            await asyncio.sleep(0)
        await asyncio.sleep(0.1)
        observations["authority_open_while_request_drains"] = edge.application.store.pool is not None
        release.set()

    request_task = release_task = None
    with pytest.raises(BaseException) as failed:
        async with edge.inner.router.lifespan_context(edge.inner):
            request_task = asyncio.create_task(request(edge, tool({"binding_id": authority.binding_id, "query": "held recall"})))
            await asyncio.wait_for(entered.wait(), 5)
            assert edge.application.inflight == 1
            assert edge.worker.status["running"] and edge.judge.status["running"]
            release_task = asyncio.create_task(release_during_shutdown())
    if release_task is not None:
        await asyncio.wait_for(release_task, 5)
    if request_task is not None:
        await asyncio.wait_for(request_task, 5)
    assert leaves(failed.value) == ([recovery_failure, judge_failure] if second_failure else [recovery_failure])
    assert observations["authority_open_while_request_drains"] is True
    assert edge.application.inflight == 0 and edge.application.accepting is False
    assert edge.application.store.pool is None
    assert not edge.worker.status["running"] and not edge.judge.status["running"]
    assert edge.recovery._task is None


async def test_recovery_diagnostics_are_body_free_and_operator_only(authority):
    async with running(authority) as edge:
        state = edge.application.store.settings.state_dir
        state.chmod(0o700)
        adapters = state / "host-adapters"
        adapters.mkdir(exist_ok=True)
        adapters.chmod(0o777)
        await asyncio.to_thread(edge.recovery.cycle)
        status, body = await request(edge, b"", token=TOKEN, path="/readyz", method="GET")
        recovery = json.loads(body)["spool_recovery"]
        assert status == 200 and recovery["state"] == "discovery_failed"
        assert recovery["last_error"] == "HOST_PATH_DENIED" and recovery["failures"] >= 1
        assert str(state) not in json.dumps(recovery)
        assert set(recovery) == {"state", "cycles", "committed", "failures", "last_error"}
        status, body = await request(edge, b"", token=None, path="/readyz", method="GET")
        assert status == 200 and "spool_recovery" not in json.loads(body)
        status, body = await request(edge, b"", path="/readyz", method="GET")
        assert status == 403 and "spool_recovery" not in body.decode()
