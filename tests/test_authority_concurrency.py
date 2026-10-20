from __future__ import annotations

import asyncio
from contextlib import suppress

import pytest
from test_store_authority import TOKEN, command, ready_claim, relation_judgment, source_selection
from test_store_authority import authority as authority

from agents_memory.application import Application
from agents_memory.config import Settings
from agents_memory.domain import ContextCommand, DomainError, EffectState
from agents_memory.lexical import tokens


async def count(authority, query, *args):
    async with authority.store.pool.acquire() as connection:
        return await connection.fetchval(query, *args)


async def test_second_complete_remember_of_the_same_window_loses(authority):
    store, actor = authority.store, authority.actor
    captured = await store.capture(actor, command(authority, "winner-source"))
    first = await source_selection(authority, captured.source_id, "first-session")
    second = await source_selection(authority, captured.source_id, "second-session")
    winner = await store.record(actor, first)
    with pytest.raises(DomainError) as caught:
        await store.record(actor, second)
    assert caught.value.code == "SELECTION_ALREADY_RECORDED"
    assert caught.value.effect == EffectState.NOT_STARTED
    assert winner.id in caught.value.message
    assert await count(authority, "SELECT count(*) FROM am_claim_sources WHERE source_id=$1", captured.source_id) == 1


async def test_concurrent_complete_judgments_of_one_window_have_one_winner(authority):
    store, actor = authority.store, authority.actor
    captured = await store.capture(actor, command(authority, "concurrent-source"))
    requests = [await source_selection(authority, captured.source_id, f"concurrent-{index}") for index in range(4)]
    # Separate pool connections submit at once; the clock-locked transaction serializes them.
    outcomes = await asyncio.gather(*(store.record(actor, request) for request in requests), return_exceptions=True)
    winners = [outcome for outcome in outcomes if not isinstance(outcome, BaseException)]
    losers = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
    assert len(winners) == 1
    assert {(loser.code, loser.effect) for loser in losers} == {("SELECTION_ALREADY_RECORDED", EffectState.NOT_STARTED)}
    assert await count(authority, "SELECT count(*) FROM am_source_selections WHERE source_id=$1", captured.source_id) == 1


async def test_withdrawing_the_winning_claim_releases_the_window(authority):
    store, actor = authority.store, authority.actor
    captured = await store.capture(actor, command(authority, "released-source"))
    winner = await store.record(actor, await source_selection(authority, captured.source_id, "winner"))
    blocked = await source_selection(authority, captured.source_id, "blocked", label="discard")
    with pytest.raises(DomainError) as caught:
        await store.record(actor, blocked)
    assert caught.value.code == "SELECTION_ALREADY_RECORDED"
    claim_id = (await store.inspect(actor, authority.binding_id, winner.artifact_id))["claim_ids"][0]
    await store.retract(actor, authority.binding_id, claim_id, "withdraw-winner")
    released = await store.record(actor, await source_selection(authority, captured.source_id, "released", label="discard"))
    assert released.state == "selection_recorded"


@pytest.mark.parametrize("later", ["remember", "discard"])
async def test_claimless_complete_remember_still_holds_the_window(authority, later):
    store, actor = authority.store, authority.actor
    captured = await store.capture(actor, command(authority, f"claimless-{later}-source"))
    claimless = (await source_selection(authority, captured.source_id, "claimless")).model_copy(update={"extraction": None})
    first = await store.record(actor, claimless)
    assert first.state == "selection_recorded"
    with pytest.raises(DomainError) as caught:
        await store.record(actor, await source_selection(authority, captured.source_id, "second", label=later))
    assert (caught.value.code, caught.value.effect) == ("SELECTION_ALREADY_RECORDED", EffectState.NOT_STARTED)
    assert first.id in caught.value.message


async def test_concurrent_claimless_remembers_have_one_winner(authority):
    store, actor = authority.store, authority.actor
    captured = await store.capture(actor, command(authority, "concurrent-claimless-source"))
    requests = [(await source_selection(authority, captured.source_id, f"claimless-{index}")).model_copy(update={"extraction": None})
        for index in range(3)]
    outcomes = await asyncio.gather(*(store.record(actor, request) for request in requests), return_exceptions=True)
    assert len([outcome for outcome in outcomes if not isinstance(outcome, BaseException)]) == 1
    assert {outcome.code for outcome in outcomes if isinstance(outcome, BaseException)} == {"SELECTION_ALREADY_RECORDED"}


@pytest.mark.parametrize("earlier,later,outcome", [
    ("remember", "discard", "SELECTION_ALREADY_RECORDED"),
    ("discard", "discard", "SELECTION_ALREADY_RECORDED"),
    ("discard", "remember", "EVIDENCE_REJECTED"),
    ("remember", "review", "selection_recorded"),
    ("review", "remember", "candidate_ready"),
])
async def test_only_review_accumulates_and_discard_reopen_rules_stay_in_charge(authority, earlier, later, outcome):
    store, actor = authority.store, authority.actor
    captured = await store.capture(actor, command(authority, f"{earlier}-{later}-source"))
    await store.record(actor, await source_selection(authority, captured.source_id, "earlier", label=earlier))
    request = await source_selection(authority, captured.source_id, "later", label=later)
    if outcome.isupper():
        with pytest.raises(DomainError) as caught:
            await store.record(actor, request)
        assert (caught.value.code, caught.value.effect) == (outcome, EffectState.NOT_STARTED)
    else:
        assert (await store.record(actor, request)).state == outcome


async def test_lost_selection_response_retried_with_a_new_key_returns_the_original(authority):
    store, actor = authority.store, authority.actor
    captured = await store.capture(actor, command(authority, "lost-response-source"))
    request = await source_selection(authority, captured.source_id, "lost-response")
    original = await store.record(actor, request)
    retried = request.model_copy(update={"idempotency_key": "fresh-key-after-lost-response"})
    assert (await store.record(actor, retried)).id == original.id
    assert (await store.record(actor, retried)).id == original.id
    changed = request.model_copy(update={"idempotency_key": "other-judgment", "reason": "A different judgment for the consumed admission."})
    with pytest.raises(DomainError) as caught:
        await store.record(actor, changed)
    assert (caught.value.code, caught.value.effect) == ("ADMISSION_CONSUMED", EffectState.NOT_STARTED)
    assert await count(authority, "SELECT count(*) FROM am_source_selections WHERE source_id=$1", captured.source_id) == 1


async def test_lost_response_replay_survives_a_store_restart(authority):
    store, actor = authority.store, authority.actor
    captured = await store.capture(actor, command(authority, "restart-replay-source"))
    request = await source_selection(authority, captured.source_id, "before-restart")
    original = await store.record(actor, request)
    await store.close()
    await store.open()
    await store.reconcile_journal()
    current = await store.authenticate(TOKEN)
    retried = await store.record(current, request.model_copy(update={"idempotency_key": "after-restart"}))
    assert retried.id == original.id


async def test_lost_claim_judgment_response_retried_with_a_new_key_returns_the_original(authority):
    store, actor = authority.store, authority.actor
    _, left = await ready_claim(authority, "judged-left", "CacheKey is retained only offline.")
    _, right = await ready_claim(authority, "judged-right", "CacheKey is retained only offline during audits.")
    request = await relation_judgment(authority, left, right)
    original = await store.record(actor, request)
    retried = await store.record(actor, request.model_copy(update={"idempotency_key": "judgment-after-lost-response"}))
    assert retried.id == original.id
    assert await count(authority, "SELECT count(*) FROM am_claim_judgments") == 1


async def test_authentication_does_not_wait_for_the_global_clock_lock(authority):
    store = authority.store
    async with store.pool.acquire() as holder:
        async with holder.transaction():
            await holder.execute("SELECT 1 FROM am_clock WHERE singleton FOR UPDATE")
            current = await asyncio.wait_for(store.authenticate(TOKEN), 5)
    assert current.credential_id == authority.actor.credential_id


async def test_context_delivery_does_not_wait_for_the_global_clock_lock(authority):
    # Read-only context delivery never queues behind writers holding the clock lock.
    store, actor = authority.store, authority.actor
    application = Application(store.settings, store)
    _, claim = await ready_claim(authority)
    rows, admission = await store.search_lexical(actor, authority.binding_id, tokens("CacheKey"), None, 20, request_digest="0" * 64)
    assert [row[0].id for row in rows] == [claim.id]
    request = ContextCommand(binding_id=authority.binding_id, query="Protected action conventions",
        paths=("src/app.py",), host="omp")
    async with store.pool.acquire() as holder:
        async with holder.transaction():
            await holder.execute("SELECT 1 FROM am_clock WHERE singleton FOR UPDATE")
            required = await asyncio.wait_for(application.required_context(actor, request), 5)
            delivered = await asyncio.wait_for(store.delivery(actor, authority.binding_id, (), (),
                nonmodel_admission=admission, selected_claim_ids=(claim.id,)), 5)
    assert required["required"] is False
    assert delivered["stats"]["active_claims"] == 1


async def test_context_delivery_waits_out_an_in_flight_deletion_instead_of_refusing(authority, monkeypatch):
    # A deletion appends its journal intent before committing the new head; a reader between the two
    # waits for that commit, as it did under the clock lock, rather than reporting a deletion barrier.
    store, actor = authority.store, authority.actor
    application = Application(store.settings, store)
    operation, _ = await ready_claim(authority)
    appended, proceed = asyncio.Event(), asyncio.Event()
    original = store._append_deletion_intent

    async def gated(*args, **kwargs):
        result = await original(*args, **kwargs)
        appended.set()
        await proceed.wait()
        return result

    monkeypatch.setattr(store, "_append_deletion_intent", gated)

    async def clock_waiters():
        async with store.pool.acquire() as connection:
            return await connection.fetchval("""SELECT count(*) FROM pg_stat_activity WHERE wait_event_type='Lock'
                AND query LIKE '%am_clock%FOR UPDATE%'""")

    async def until_waiters(count):
        async with asyncio.timeout(5):
            while await clock_waiters() < count:
                await asyncio.sleep(0.02)

    request = ContextCommand(binding_id=authority.binding_id, query="Protected action conventions",
        paths=("src/app.py",), host="omp")
    retraction = asyncio.create_task(store.retract(actor, authority.binding_id, operation.source_id, "in-flight-retract"))
    await asyncio.wait_for(appended.wait(), 5)
    async with store.pool.acquire() as holder:
        async with holder.transaction():
            await holder.execute("SELECT 1 FROM am_clock WHERE singleton FOR UPDATE")
            proceed.set()
            await until_waiters(1)
            reader = asyncio.create_task(application.required_context(actor, request))
            with suppress(TimeoutError):
                async with asyncio.timeout(1):
                    while not reader.done() and await clock_waiters() < 2:
                        await asyncio.sleep(0.02)
    required = await asyncio.wait_for(reader, 5)
    assert (await asyncio.wait_for(retraction, 5))["logical_retraction"] == "committed"
    assert required["required"] is False


async def test_exhausted_pool_refuses_after_its_deadline_without_starting(authority):
    store = authority.store
    store.settings = Settings.model_validate({**store.settings.model_dump(), "pool_acquire_timeout_seconds": 0.2})
    held = [await store.pool.acquire() for _ in range(store.pool.get_max_size())]
    try:
        with pytest.raises(DomainError) as caught:
            await asyncio.wait_for(store.stats(authority.actor, authority.binding_id), 5)
        assert (caught.value.code, caught.value.effect) == ("DATABASE_BUSY", EffectState.NOT_STARTED)
    finally:
        for connection in held:
            await store.pool.release(connection)
    assert (await store.stats(authority.actor, authority.binding_id))["active_sources"] == 0
