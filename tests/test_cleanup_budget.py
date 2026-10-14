from __future__ import annotations

import json

from test_store_authority import authority as authority
from test_store_authority import (
    cleanup_command,
    ready_claim,
)

import agents_memory.store as store_module


def decoded(value):
    return json.loads(value) if isinstance(value, str) else value


def assert_budget(result):
    assert result["examined_pending"] <= 32
    assert result["examined_pages"] <= 4
    assert result["examined_claims"] <= 80
    assert result["examined_bindings"] <= 32
    assert result["created"] <= 32


async def judge_ids(authority, ids, key):
    manifest = await authority.store.inspect(
        authority.actor, authority.binding_id, "judgment", claim_ids=tuple(ids)
    )
    await authority.store.record(
        authority.actor, cleanup_command(authority, manifest, key)
    )
    return manifest


async def progress(store):
    async with store.pool.acquire() as connection:
        return decoded(await connection.fetchval(
            "SELECT cleanup_progress FROM am_clock WHERE singleton"
        ))


async def test_empty_cleanup_cycle_has_no_continuation_or_semantic_work(authority):
    store = authority.store
    result = await store.schedule_cleanup()
    assert_budget(result)
    assert result["created"] == 0
    assert result["pending_ids"] == []
    assert result["more"] is False
    assert await progress(store) == {}
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT count(*) FROM am_jobs") == 0
        assert await connection.fetchval(
            "SELECT count(*) FROM am_claim_judgments"
        ) == 0


async def test_fully_judged_pages_are_bounded_and_continue_after_restart(authority):
    store = authority.store
    claims = []
    for index in range(121):
        _, claim = await ready_claim(authority, f"budget-judged-{index}")
        claims.append(claim)

    for offset in range(0, len(claims), 20):
        await judge_ids(
            authority, [claim.id for claim in claims[offset:offset + 20]],
            f"budget-page-{offset}",
        )

    first = await store.schedule_cleanup()
    assert_budget(first)
    assert first["created"] == 0
    assert first["examined_pages"] == 4
    assert first["examined_claims"] == 80
    assert first["more"] is True
    saved = await progress(store)
    assert saved["claim_after"] == 80
    assert saved["claim_high"] == 121

    # A normal authority request commits between cleanup transactions.
    _, arriving = await ready_claim(authority, "budget-arriving")
    assert arriving.id not in {claim.id for claim in claims}
    assert (await progress(store))["claim_high"] == 121

    await store.close()
    await store.open()
    await store.reconcile_journal()
    assert await progress(store) == saved

    second = await store.schedule_cleanup()
    assert_budget(second)
    assert second["created"] == 0
    assert second["examined_claims"] == 41
    # The old cycle completed; the later insertion needs a fresh cycle.
    assert second["more"] is True
    assert await progress(store) == {}

    third = await store.schedule_cleanup()
    assert_budget(third)
    assert third["created"] == 0
    assert third["more"] is True
    fourth = await store.schedule_cleanup()
    assert_budget(fourth)
    assert fourth["created"] == 1
    assert fourth["more"] is False

    manifest = (await store.inspect(
        authority.actor, authority.binding_id, fourth["pending_ids"][0]
    ))["judgment_manifest"]
    assert {item["id"] for item in manifest["claims"]} == {
        claims[-1].id, arriving.id
    }
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT count(*) FROM am_jobs") == 0
        assert await connection.fetchval(
            "SELECT count(*) FROM am_claim_judgments"
        ) == 7


async def test_new_lower_uuid_does_not_shift_previous_full_pages(authority, monkeypatch):
    store = authority.store
    claims = []
    for index in range(40):
        _, claim = await ready_claim(authority, f"stable-insertion-{index}")
        claims.append(claim)

    await judge_ids(
        authority, [claim.id for claim in claims[:20]], "stable-first-page"
    )
    await judge_ids(
        authority, [claim.id for claim in claims[20:]], "stable-second-page"
    )

    original_id = store_module._id
    lower_id = "claim_" + "0" * 32
    assert lower_id < min(claim.id for claim in claims)

    def controlled_id(kind):
        return lower_id if kind == "claim" else original_id(kind)

    # Control only identity generation; admission, publication and PG are real.
    with monkeypatch.context() as context:
        context.setattr(store_module, "_id", controlled_id)
        _, arriving = await ready_claim(authority, "stable-lower-uuid")
    assert arriving.id == lower_id

    result = await store.schedule_cleanup()
    assert result["created"] == 1
    manifest = (await store.inspect(
        authority.actor, authority.binding_id, result["pending_ids"][0]
    ))["judgment_manifest"]
    assert [item["id"] for item in manifest["claims"]] == [arriving.id]
    assert_budget(result)

    async with store.pool.acquire() as connection:
        old = await connection.fetch("""
            SELECT id,cleanup_sequence FROM am_claims
            WHERE cleanup_sequence<=40 ORDER BY cleanup_sequence
        """)
        assert [row["id"] for row in old] == [claim.id for claim in claims]
        assert await connection.fetchval(
            "SELECT count(*) FROM am_claim_judgments WHERE state='active'"
        ) == 2



async def test_pending_rechecks_terminalize_only_32_and_preserve_saved_ids(authority):
    store = authority.store
    originals = {}
    for index in range(65):
        snapshot = f"pending-budget-{index}"
        _, claim = await ready_claim(
            authority, f"pending-budget-claim-{index}", snapshot=snapshot
        )
        pending_id = f"pending_budget_{index}"
        originals[pending_id] = [claim.id]
        async with store.pool.acquire() as connection:
            await connection.execute("""
                INSERT INTO am_pending_judgments(
                    id,binding_id,kind,claim_ids,snapshot
                ) VALUES($1,$2,'cleanup',$3,$4)
            """, pending_id, authority.binding_id, [claim.id], snapshot)

    async with store.pool.acquire() as connection:
        await connection.execute("""
            UPDATE am_claims
            SET valid_until=clock_timestamp()-interval '1 day'
        """)

    first = await store.schedule_cleanup()
    assert_budget(first)
    assert first["examined_pending"] == 32
    assert first["terminalized"] == 32
    assert first["created"] == 0
    assert first["more"] is True
    async with store.pool.acquire() as connection:
        assert await connection.fetchval("""
            SELECT count(*) FROM am_pending_judgments
            WHERE kind='cleanup' AND state='resolved'
        """) == 32

    await store.close()
    await store.open()
    await store.reconcile_journal()
    second = await store.schedule_cleanup()
    assert_budget(second)
    assert second["terminalized"] == 32
    assert second["more"] is True

    third = await store.schedule_cleanup()
    assert_budget(third)
    assert third["terminalized"] == 1
    assert third["more"] is False
    assert await progress(store) == {}

    async with store.pool.acquire() as connection:
        rows = await connection.fetch("""
            SELECT id,state,claim_ids,reason,resolved_at
            FROM am_pending_judgments WHERE kind='cleanup'
        """)
        assert len(rows) == 65
        for row in rows:
            assert row["state"] == "resolved"
            assert row["claim_ids"] == originals[row["id"]]
            assert row["resolved_at"] is not None


async def test_binding_group_budget_continues_inside_a_position_page(authority):
    store = authority.store
    expected = {}
    for index in range(45):
        snapshot = f"group-budget-{index}"
        _, claim = await ready_claim(
            authority, f"group-budget-claim-{index}", snapshot=snapshot
        )
        expected[snapshot] = claim.id

    first = await store.schedule_cleanup()
    assert_budget(first)
    assert first["created"] == 32
    assert first["examined_bindings"] == 32
    assert first["examined_pages"] == 2
    assert first["more"] is True
    saved = await progress(store)
    assert saved["claim_after"] == 20
    assert saved["group_after"] is not None

    await store.close()
    await store.open()
    await store.reconcile_journal()
    second = await store.schedule_cleanup()
    assert_budget(second)
    assert second["created"] == 13
    assert second["more"] is False

    async with store.pool.acquire() as connection:
        rows = await connection.fetch("""
            SELECT snapshot,claim_ids FROM am_pending_judgments
            WHERE kind='cleanup' AND state='pending'
        """)
        assert len(rows) == 45
        assert {row["snapshot"]: row["claim_ids"] for row in rows} == {
            snapshot: [claim_id] for snapshot, claim_id in expected.items()
        }


async def test_cleanup_uses_current_eligibility_then_requeues_changed_manifest(authority):
    store = authority.store
    _, expired = await ready_claim(authority, "eligibility-expired")
    _, future = await ready_claim(authority, "eligibility-future")
    _, withdrawn = await ready_claim(authority, "eligibility-withdrawn")
    _, current = await ready_claim(authority, "eligibility-current")

    async with store.pool.acquire() as connection:
        await connection.execute("""
            UPDATE am_claims SET valid_until=clock_timestamp()-interval '1 day'
            WHERE id=$1
        """, expired.id)
        await connection.execute("""
            UPDATE am_claims SET valid_from=clock_timestamp()+interval '1 day'
            WHERE id=$1
        """, future.id)
    await store.retract(
        authority.actor, authority.binding_id, withdrawn.id, "withdraw-budget-claim"
    )

    scheduled = await store.schedule_cleanup()
    assert_budget(scheduled)
    assert scheduled["created"] == 1
    pending_id = scheduled["pending_ids"][0]
    manifest = (await store.inspect(
        authority.actor, authority.binding_id, pending_id
    ))["judgment_manifest"]
    assert [item["id"] for item in manifest["claims"]] == [current.id]
    await store.record(
        authority.actor, cleanup_command(authority, manifest, "eligibility-judged")
    )

    async with store.pool.acquire() as connection:
        await connection.execute("""
            UPDATE am_pending_judgments
            SET created_at=clock_timestamp()-interval '2 days'
            WHERE id=$1
        """, pending_id)
    unchanged = await store.schedule_cleanup()
    assert_budget(unchanged)
    assert unchanged["created"] == 0
    assert unchanged["more"] is False

    async with store.pool.acquire() as connection:
        await connection.execute(
            "UPDATE am_claims SET revision=revision+1 WHERE id=$1", current.id
        )
    changed = await store.schedule_cleanup()
    assert_budget(changed)
    assert changed["created"] == 1
    refreshed = (await store.inspect(
        authority.actor, authority.binding_id, changed["pending_ids"][0]
    ))["judgment_manifest"]
    assert [item["id"] for item in refreshed["claims"]] == [current.id]
    assert refreshed["claims"][0]["revision"] == manifest["claims"][0]["revision"] + 1




