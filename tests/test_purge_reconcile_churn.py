from __future__ import annotations

import pytest
from test_store_authority import authority as authority
from test_store_authority import ready_claim

from agents_memory.domain import DomainError
from agents_memory.store import Store


async def scrubbed_rows(store, source_id, claim_id):
    async with store.pool.acquire() as connection:
        source = await connection.fetchrow(
            """SELECT xmin::text,ctid::text,body,state FROM am_sources WHERE id=$1""",
            source_id,
        )
        claim = await connection.fetchrow(
            """SELECT xmin::text,ctid::text,draft,embedding,lexical_tokens,state
            FROM am_claims WHERE id=$1""",
            claim_id,
        )
        spans = await connection.fetch(
            """SELECT xmin::text,ctid::text,ordinal,quote,source_id,source_revision,byte_start,byte_end
            FROM am_spans WHERE claim_id=$1 ORDER BY ordinal""",
            claim_id,
        )
        selection = await connection.fetchrow(
            """SELECT q.xmin::text,q.ctid::text,q.reason,q.rejection_comparisons::text
            FROM am_source_selections q JOIN am_claims c ON c.selection_id=q.id
            WHERE c.id=$1""",
            claim_id,
        )
    assert source["body"] is None and source["state"] == "purged"
    assert claim["draft"] is None and claim["embedding"] is None
    assert claim["lexical_tokens"] == [] and claim["state"] == "retracted"
    assert spans and all(span["quote"] is None for span in spans)
    assert all(span["source_id"] == source_id for span in spans)
    assert selection["reason"] is None and selection["rejection_comparisons"] == "[]"
    return source, claim, tuple(spans), selection


async def pending_row(store, pending_id):
    async with store.pool.acquire() as connection:
        return await connection.fetchrow(
            """SELECT xmin::text,ctid::text,source_ids,claim_ids,state
            FROM am_pending_judgments WHERE id=$1""",
            pending_id,
        )


async def test_later_purge_and_reconcile_do_not_rewrite_scrubbed_rows(authority):
    store, actor = authority.store, authority.actor
    first, first_claim = await ready_claim(authority, "churn-first")
    second, second_claim = await ready_claim(authority, "churn-second")
    survivor, survivor_claim = await ready_claim(authority, "churn-survivor")
    async with store.pool.acquire() as connection:
        await connection.execute(
            """INSERT INTO am_pending_judgments(id,binding_id,kind,source_ids,claim_ids)
            VALUES('pending_churn_survivor',$1,'legacy_revalidation',$2,$3)""",
            authority.binding_id, [survivor.source_id], [survivor_claim.id],
        )
    await store.retract(actor, authority.binding_id, first.source_id, "retract-churn-first")
    await store.purge(actor, authority.binding_id, first.source_id, "purge-churn-first")
    original = await scrubbed_rows(store, first.source_id, first_claim.id)
    pending = await pending_row(store, "pending_churn_survivor")
    assert pending["state"] == "pending"

    await store.retract(actor, authority.binding_id, second.source_id, "retract-churn-second")
    await store.purge(actor, authority.binding_id, second.source_id, "purge-churn-second")
    await store.reconcile_journal()

    assert await scrubbed_rows(store, first.source_id, first_claim.id) == original
    assert await pending_row(store, "pending_churn_survivor") == pending
    second_scrubbed = await scrubbed_rows(store, second.source_id, second_claim.id)
    await store.reconcile_journal()
    assert await scrubbed_rows(store, first.source_id, first_claim.id) == original
    assert await scrubbed_rows(store, second.source_id, second_claim.id) == second_scrubbed
    with pytest.raises(DomainError) as withdrawn:
        await store.claim(actor, authority.binding_id, first_claim.id)
    assert withdrawn.value.code == "CLAIM_INELIGIBLE"
    assert (await store.claim(actor, authority.binding_id, survivor_claim.id)).state == "active"


async def test_private_restore_repair_rescrubs_payloads_under_surviving_purge_floors(authority):
    store, actor = authority.store, authority.actor
    source, claim = await ready_claim(authority, "restore-churn")
    original_source = await store.source(actor, authority.binding_id, source.source_id)
    async with store.pool.acquire() as connection:
        original_draft = await connection.fetchval("SELECT draft FROM am_claims WHERE id=$1", claim.id)
    await store.retract(actor, authority.binding_id, source.source_id, "retract-restore-churn")
    await store.purge(actor, authority.binding_id, source.source_id, "purge-restore-churn")
    head = store.journal.verify()["head"]
    original = await scrubbed_rows(store, source.source_id, claim.id)
    async with store.pool.acquire() as connection:
        floors = await connection.fetch("SELECT kind,token FROM am_floors ORDER BY kind,token")
        async with connection.transaction():
            await connection.execute(
                "UPDATE am_sources SET body=$2 WHERE id=$1", source.source_id, original_source.body,
            )
            await connection.execute(
                "UPDATE am_claims SET draft=$2::jsonb,lexical_tokens=$3 WHERE id=$1",
                claim.id, original_draft, ["restored"],
            )
            await connection.execute(
                "UPDATE am_spans SET quote=$2 WHERE claim_id=$1", claim.id, claim.evidence[0].quote,
            )
            await connection.execute(
                """UPDATE am_source_selections SET reason='Restored selection reason',
                rejection_comparisons='[{"restored":true}]'::jsonb
                WHERE id=(SELECT selection_id FROM am_claims WHERE id=$1)""",
                claim.id,
            )

    recovery = Store(store.settings.model_copy(update={"migrator_dsn": store.settings.database_dsn}), store.journal)
    await recovery.open()
    try:
        recovered_actor = await recovery.recover_after_restore(
            actor.id, "fresh-churn-recovery-" + "r" * 48, head,
        )
        repaired = await scrubbed_rows(recovery, source.source_id, claim.id)
        assert repaired != original
        assert [tuple(span)[4:] for span in repaired[2]] == [tuple(span)[4:] for span in original[2]]
        async with recovery.pool.acquire() as connection:
            assert await connection.fetch("SELECT kind,token FROM am_floors ORDER BY kind,token") == floors
        assert store.journal.verify()["head"] == head
        with pytest.raises(DomainError) as withdrawn:
            await recovery.claim(recovered_actor, authority.binding_id, claim.id)
        assert withdrawn.value.code == "CLAIM_INELIGIBLE"
    finally:
        await recovery.close()


@pytest.mark.parametrize("initial_state", ("pending", "held"))
async def test_legacy_revalidation_updates_only_changed_eligibility_arrays(authority, initial_state):
    store, actor = authority.store, authority.actor
    first, first_claim = await ready_claim(authority, "legacy-first")
    removed, removed_claim = await ready_claim(authority, "legacy-removed")
    third, third_claim = await ready_claim(authority, "legacy-third")
    async with store.pool.acquire() as connection:
        await connection.executemany(
            """INSERT INTO am_pending_judgments(id,binding_id,kind,source_ids,claim_ids,state)
            VALUES($1,$2,'legacy_revalidation',$3,$4,$5)""",
            [
                ("pending_legacy_stable", authority.binding_id, [first.source_id], [first_claim.id], initial_state),
                ("pending_legacy_changed", authority.binding_id,
                    [third.source_id, removed.source_id, first.source_id],
                    [third_claim.id, removed_claim.id, first_claim.id], initial_state),
            ],
        )
    stable = await pending_row(store, "pending_legacy_stable")
    before = await pending_row(store, "pending_legacy_changed")
    await store.reconcile_journal()
    assert await pending_row(store, "pending_legacy_stable") == stable
    assert await pending_row(store, "pending_legacy_changed") == before

    await store.retract(actor, authority.binding_id, removed.source_id, "remove-legacy-input")
    changed = await pending_row(store, "pending_legacy_changed")
    assert changed["source_ids"] == [third.source_id, first.source_id]
    assert changed["claim_ids"] == [third_claim.id, first_claim.id]
    assert changed["state"] == initial_state
    assert (changed["xmin"], changed["ctid"]) != (before["xmin"], before["ctid"])
    assert await pending_row(store, "pending_legacy_stable") == stable
    await store.reconcile_journal()
    assert await pending_row(store, "pending_legacy_changed") == changed
    assert await pending_row(store, "pending_legacy_stable") == stable


async def test_legacy_revalidation_state_changes_without_array_changes_and_retracts_empty_inputs(authority):
    store, actor = authority.store, authority.actor
    source, claim = await ready_claim(authority, "legacy-state")
    async with store.pool.acquire() as connection:
        await connection.execute(
            """INSERT INTO am_pending_judgments(id,binding_id,kind,source_ids,claim_ids)
            VALUES('pending_legacy_state',$1,'legacy_revalidation',$2,$3)""",
            authority.binding_id, [source.source_id], [claim.id],
        )
    before = await pending_row(store, "pending_legacy_state")
    async with store.pool.acquire() as connection:
        await connection.execute("UPDATE am_sources SET speaker='agent_note' WHERE id=$1", source.source_id)
    await store.reconcile_journal()
    held = await pending_row(store, "pending_legacy_state")
    assert held["source_ids"] == before["source_ids"] and held["claim_ids"] == before["claim_ids"]
    assert held["state"] == "held"
    assert (held["xmin"], held["ctid"]) != (before["xmin"], before["ctid"])
    await store.reconcile_journal()
    assert await pending_row(store, "pending_legacy_state") == held

    await store.retract(actor, authority.binding_id, source.source_id, "remove-last-legacy-input")
    retracted = await pending_row(store, "pending_legacy_state")
    assert retracted["source_ids"] == [] and retracted["claim_ids"] == []
    assert retracted["state"] == "retracted"
    await store.reconcile_journal()
    assert await pending_row(store, "pending_legacy_state") == retracted
