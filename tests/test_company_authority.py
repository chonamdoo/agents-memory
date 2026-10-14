from __future__ import annotations

import asyncio
import importlib
import json
import os
import uuid
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import asyncpg
import pytest
import pytest_asyncio

from agents_memory.application import Application
from agents_memory.config import Settings
from agents_memory.domain import (
    BindingRelocation,
    CaptureCommand,
    CaptureCoverage,
    ContextCommand,
    DomainError,
    Principal,
    RelevanceJudgment,
    Role,
    RuleApproval,
    RuleProposal,
    RuleScope,
)
from agents_memory.journal import DeletionJournal
from agents_memory.lexical import tokens
from agents_memory.migrations import MIGRATIONS, migrate, restore_preparation_sql
from agents_memory.selection import SourceSelectionCommand
from agents_memory.semantic_contract import GeneratedExtraction
from agents_memory.store import Store

TOKEN = "company-authority-isolated-operator-" + "a" * 32


BODY = "CacheKey is retained offline."


@dataclass
class CompanyAuthority:
    store: Store
    actor: Principal
    binding_id: str
    application: Application


@pytest_asyncio.fixture
async def company(tmp_path):
    raw_dsn = os.environ.get("PG_TEST_DSN")
    if not raw_dsn:
        pytest.skip("PG_TEST_DSN required for isolated no-model company authority regressions")
    parts = urlsplit(raw_dsn)
    query = dict(parse_qsl(parts.query))
    query.pop("schema", None)
    admin_dsn = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    schema = "am_company_" + uuid.uuid4().hex
    admin = await asyncpg.connect(admin_dsn)
    store = None
    try:
        await admin.execute(f'CREATE SCHEMA "{schema}"')
        query["schema"] = schema
        dsn = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
        await asyncio.to_thread(migrate, dsn)
        settings = Settings(deployment_id="company_test", realm="company_test", mode="company",
            capability="agent_judged", database_dsn=dsn, migrator_dsn=dsn,
            state_dir=tmp_path / "authority", journal_dir=tmp_path / "independent-journal")
        store = Store(settings, DeletionJournal(settings.journal_dir, settings.deployment_id))
        await store.open()
        actor = await store.bootstrap(TOKEN, "company_owner")
        binding = await store.register_binding(actor, "Synthetic company", "/synthetic/company", "register")
        actor = await store.authenticate(TOKEN)
        yield CompanyAuthority(store, actor, binding.id, Application(settings, store))
    finally:
        if store is not None:
            await store.close()
        await admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await admin.close()


async def capture(company, key="capture", body=BODY, snapshot=None, coverage=None):
    return await company.store.capture(company.actor, CaptureCommand(binding_id=company.binding_id,
        idempotency_key=key, origin_key=key, body=body, speaker="human", snapshot=snapshot,
        coverage=coverage or CaptureCoverage(status="observed_window", original_bytes=len(body.encode()))))


async def judgment(company, source_id, key="select", label="remember", publish=False, start=0, max_bytes=4096, snapshot=None, actor=None):
    window = await company.store.inspect(actor or company.actor, company.binding_id, source_id, snapshot,
        byte_start=start, max_bytes=max_bytes)
    extraction = None
    if publish:
        span = window["span_inventory"][0]
        extraction = GeneratedExtraction(claims=({"assertion_id": "a0001", "assertion_span_id": span["span_id"],
            "statement": window["body"], "kind": "fact", "subject": window["body"].split()[0], "predicate": "retained",
            "object": "offline", "polarity": "positive", "modality": "asserted", "entities": (window["body"].split()[0],)},),
            individual_qualifications=(), shared_qualifications=(), validities=(),
            unused_span_ids=tuple(item["span_id"] for item in window["span_inventory"][1:]))
    return SourceSelectionCommand(kind="source_selection", binding_id=company.binding_id, idempotency_key=key,
        admission_id=window["admission_id"], reason="Caller reviewed the original source and its qualifications.",
        source_id=source_id, source_revision=window["source_revision"], binding_revision=window["binding_revision"],
        snapshot=snapshot, byte_start=window["byte_start"], byte_end=window["byte_end"],
        window_digest=window["window_digest"], policy_revision=window["policy_revision"], policy_epoch=window["policy_epoch"],
        label=label, coverage="complete_window", extraction=extraction,
        rejection_comparisons=tuple({"rejection_id": item["id"], "decision": "unrelated",
            "reason": "Caller compared this independent source with the persisted rejection."}
            for item in window["judgment_context"]["rejections"]))


async def candidate(company, key="candidate", snapshot=None, body=BODY):
    source = await capture(company, key, body=body, snapshot=snapshot)
    selected = await company.store.record(company.actor,
        await judgment(company, source.source_id, key + "-select", publish=True, snapshot=snapshot))
    inspected = await company.store.inspect(company.actor, company.binding_id, selected.artifact_id, snapshot)
    claim = await company.store.claim(company.actor, company.binding_id, inspected["claim_ids"][0], snapshot)
    return source, selected, claim


async def deliver(company, admission, selected=(), relations=(), snapshot=None):
    return await company.store.delivery(company.actor, company.binding_id, (), (), snapshot,
        relation_ids=relations, nonmodel_admission=admission, selected_claim_ids=selected)


async def archive_rows(store):
    async with store.pool.acquire() as connection:
        async with connection.transaction():
            names = await connection.fetch("""SELECT tablename FROM pg_tables WHERE schemaname=current_schema()
                ORDER BY tablename""")
            return {row["tablename"]: [dict(item) for item in await connection.fetch(f'SELECT * FROM "{row["tablename"]}"')]
                for row in names}


async def restore_rows(store, archive, historical_revision=None):
    store._ready = False
    async with store.pool.acquire() as connection:
        async with connection.transaction():
            schema = await connection.fetchval("SELECT current_schema()")
            if historical_revision is not None:
                await connection.execute(restore_preparation_sql(historical_revision, schema))
                names = await connection.fetch("SELECT tablename FROM pg_tables WHERE schemaname=current_schema()")
                for row in names:
                    await connection.execute(f'DROP TABLE IF EXISTS "{row["tablename"]}" CASCADE')
                await connection.execute("CREATE TABLE alembic_version(version_num varchar(64) NOT NULL PRIMARY KEY)")
                for revision in MIGRATIONS[:MIGRATIONS.index(historical_revision) + 1]:
                    module = importlib.import_module("agents_memory.migrations.versions." + revision)
                    for statement in module.DDL.split(";"):
                        if statement.strip():
                            await connection.execute(statement)
            present = await connection.fetch("SELECT tablename FROM pg_tables WHERE schemaname=current_schema()")
            await connection.execute("TRUNCATE " + ",".join(f'"{row["tablename"]}"' for row in present))
            order = ["am_clock", "am_credentials", "am_bindings", "am_grants", "am_receipts", "am_operations",
                "am_sources", "am_floors", "am_selection_policies", "am_source_selections", "am_selection_sources",
                "am_claims", "am_claim_sources", "am_spans", "am_entities", "am_claim_judgments", "am_relations", "am_relation_sources",
                "am_relation_claims", "am_reflections", "am_reflection_sources", "am_reflection_claims", "am_proposals",
                "am_proposal_sources", "am_rules", "am_rule_targets", "am_feedback", "am_routes", "am_jobs",
                "am_pending_judgments", "am_retired_jobs", "am_rejection_evidence", "am_rejection_tokens",
                "am_admissions", "am_origin_reservations", "alembic_version"]
            for name in order:
                columns = await connection.fetch("""SELECT column_name,udt_name FROM information_schema.columns
                    WHERE table_schema=current_schema() AND table_name=$1 ORDER BY ordinal_position""", name)
                if not columns:
                    continue
                rows = archive.get(name, [])
                if name == "alembic_version" and historical_revision is not None:
                    rows = [{"version_num": historical_revision}]
                if not rows:
                    continue
                # Binary COPY has no pgvector encoder; company rows never carry vectors, so all-NULL columns stay NULL.
                names = [item["column_name"] for item in columns if item["udt_name"] != "vector"
                    or any(row[item["column_name"]] is not None for row in rows)]
                await connection.copy_records_to_table(name, columns=names,
                    records=[tuple(row[field] for field in names) for row in rows])
    if historical_revision is not None:
        await store.close()
        await asyncio.to_thread(migrate, store.settings.database_dsn)
        await store.open()


@pytest.mark.parametrize("label", ("remember", "discard", "review"))
async def test_capture_and_body_free_judgments_are_durable_distinct_terminals(company, label):
    source = await capture(company)
    assert source.state == "captured" and source.capture_disposition == "captured"
    assert source.source_pointer.source_revision == 1
    assert source.source_pointer.source_event_time is None
    before = await company.store.stats(company.actor, company.binding_id)
    assert before["coverage"] == {"unclassified_sources": 1, "incomplete_sources": 1, "previous_policy_claims": 0}
    command = await judgment(company, source.source_id, label=label)
    selected = await company.store.record(company.actor, command)
    assert selected.state == "selection_recorded" and selected.selection_label == label
    assert await company.store.record(company.actor, command) == selected
    await company.store.close()
    await company.store.open()
    await company.store.reconcile_journal()
    inspected = await company.store.inspect(company.actor, company.binding_id, selected.artifact_id)
    assert inspected["label"] == label and inspected["claim_ids"] == []
    assert "body" not in inspected and "extraction" not in inspected
    rows, admission = await company.store.search_lexical(company.actor, company.binding_id, tokens(BODY), None, request_digest="a" * 64)
    assert rows == [] and admission.claim_ids == () and admission.sources == ()
    await deliver(company, admission)
    after = await company.store.stats(company.actor, company.binding_id)
    assert after["classification_labels"] == {label: 1}
    unresolved = int(label == "review")
    assert after["coverage"] == {"unclassified_sources": unresolved, "incomplete_sources": unresolved, "previous_policy_claims": 0}
    assert after["active_claims"] == 0


async def test_grounded_publication_recall_and_inspect_preserve_original_provenance_without_vectors(company):
    source, selected, claim = await candidate(company)
    assert selected.state == "candidate_ready" and claim.interpretation_role == "caller_grounded_candidate"
    assert claim.selection_id == selected.artifact_id and claim.input_source_ids == (source.source_id,)
    assert claim.evidence[0].quote == BODY and claim.evidence[0].byte_start == 0
    assert claim.evidence[0].source_speaker == "human" and claim.evidence[0].source_event_time is None
    rows, admission = await company.store.search_lexical(company.actor, company.binding_id, tokens("CacheKey"), None, request_digest="a" * 64)
    assert rows[0][0].id == claim.id and set(rows[0][1]) == {"lexical", "entity"}
    assert admission.claim_ids == (claim.id,) and admission.sources[0].id == source.source_id
    await deliver(company, admission, (claim.id,))
    context = await judged_context(company, company.actor, ContextCommand(query="CacheKey", binding_id=company.binding_id))
    assert context["refs"] == [claim.id] and context["status"] == "ready"
    stats = await company.store.stats(company.actor, company.binding_id)
    assert stats["active_claims"] == 1 and stats["stale_index_claims"] == 0
    async with company.store.pool.acquire() as connection:
        row = await connection.fetchrow("SELECT embedding,route_revision,vector_revision FROM am_claims WHERE id=$1", claim.id)
        assert all(value is None for value in row.values())
        assert await connection.fetchval("SELECT count(*) FROM am_jobs") == 0
        assert await connection.fetchval("SELECT count(*) FROM am_routes") == 0


async def test_judgment_digest_rejects_changed_labels_coverage_drafts_and_policy(company):
    source = await capture(company)
    command = await judgment(company, source.source_id)
    await company.store.record(company.actor, command)
    published = await judgment(company, source.source_id, publish=True)
    for altered in (command.model_copy(update={"label": "discard"}), command.model_copy(update={"coverage": "incomplete_window"}),
        published, command.model_copy(update={"policy_epoch": command.policy_epoch + 1})):
        with pytest.raises(DomainError) as error:
            await company.store.record(company.actor, altered)
        assert error.value.code == "IDEMPOTENCY_CONFLICT"


async def test_unknown_truncated_and_multiwindow_coverage_remain_truthful(company):
    unknown = await capture(company, "unknown", coverage=CaptureCoverage())
    await company.store.record(company.actor, await judgment(company, unknown.source_id, "unknown-select"))
    truncated = await capture(company, "truncated", coverage=CaptureCoverage(status="truncated", gaps=("host_gap",), original_bytes=100))
    await company.store.record(company.actor, await judgment(company, truncated.source_id, "truncated-select", label="discard"))
    body = "한글 " * 1000
    complete = await capture(company, "multi", body)
    first = await judgment(company, complete.source_id, "first", label="discard")
    await company.store.record(company.actor, first)
    before = await company.store.stats(company.actor, company.binding_id)
    assert before["coverage"]["incomplete_sources"] == 3
    cursor = first.byte_end
    while cursor < len(body.encode()):
        next_window = await judgment(company, complete.source_id, f"window-{cursor}", label="discard", start=cursor)
        await company.store.record(company.actor, next_window)
        cursor = next_window.byte_end
    after = await company.store.stats(company.actor, company.binding_id)
    assert after["coverage"] == {"unclassified_sources": 0, "incomplete_sources": 2, "previous_policy_claims": 0}
    with pytest.raises(DomainError) as invalid:
        await company.store.inspect(company.actor, company.binding_id, complete.source_id, byte_start=1)
    assert invalid.value.code == "SOURCE_WINDOW_INVALID"


@pytest.mark.parametrize("race", ("grant", "generation", "credential", "source_revision", "source_state", "binding", "contract", "deadline"))
async def test_actual_pool_delivery_rechecks_authority_races(company, race):
    source, _, claim = await candidate(company)
    reader = await company.store.issue_token(company.actor, Role.AGENT, (company.binding_id,), "company-read-race-" + "r" * 40)
    rows, admission = await company.store.search_lexical(reader, company.binding_id, tokens("CacheKey"), None, request_digest="a" * 64)
    assert rows[0][0].id == claim.id
    if race == "binding":
        await company.store.relocate_binding(company.actor, BindingRelocation(binding_id=company.binding_id,
            expected_revision=1, expected_locator="/synthetic/company", locator="/synthetic/new-location", idempotency_key="move"))
    elif race == "contract":
        async with company.store.pool.acquire() as connection:
            await connection.execute("UPDATE am_admissions SET policy_revision=$1", "0" * 64)
    else:
        async with company.store.pool.acquire() as connection:
            statements = {
                "grant": ("DELETE FROM am_grants WHERE credential_id=$1", reader.credential_id),
                "generation": ("UPDATE am_credentials SET generation=generation+1 WHERE id=$1", reader.credential_id),
                "credential": ("UPDATE am_credentials SET active=false WHERE id=$1", reader.credential_id),
                "source_revision": ("UPDATE am_sources SET revision=revision+1 WHERE id=$1", source.source_id),
                "source_state": ("UPDATE am_sources SET state='retracted' WHERE id=$1", source.source_id),
                "deadline": ("UPDATE am_admissions SET deadline=clock_timestamp()-interval '1 second' WHERE id=$1", admission.id),
            }
            await connection.execute(*statements[race])
    with pytest.raises(DomainError) as stale:
        await company.store.delivery(reader, company.binding_id, (), (), nonmodel_admission=admission, selected_claim_ids=(claim.id,))
    assert stale.value.code in {"CONTEXT_STALE", "AUTH_DENIED", "SCOPE_DENIED"}


async def test_delivery_rechecks_unselected_pool_inputs_and_rejects_unadmitted_ids(company):
    first, _, first_claim = await candidate(company, "first")
    _, _, second_claim = await candidate(company, "second")
    _, admission = await company.store.search_lexical(company.actor, company.binding_id, tokens("CacheKey"), None, request_digest="a" * 64)
    await company.store.register_binding(company.actor, "Unrelated clock change", None, "unrelated")
    await deliver(company, admission, (second_claim.id,))
    with pytest.raises(DomainError) as forged:
        await deliver(company, admission, ("claim_" + "a" * 32,))
    assert forged.value.code == "CONTEXT_STALE"
    with pytest.raises(DomainError) as bypass:
        await company.store.delivery(company.actor, company.binding_id, (), (), selected_claim_ids=(second_claim.id,))
    assert bypass.value.code == "CONTEXT_STALE"
    await company.store.retract(company.actor, company.binding_id, first.source_id, "retract-first")
    with pytest.raises(DomainError) as stale:
        await deliver(company, admission, (second_claim.id,))
    assert stale.value.code == "CONTEXT_STALE"
    assert (await company.store.claim(company.actor, company.binding_id, second_claim.id)).state == "active"
    with pytest.raises(DomainError):
        await company.store.claim(company.actor, company.binding_id, first_claim.id)


@pytest.mark.parametrize("race", ("source", "revision", "contract", "binding", "grant", "generation", "credential"))
async def test_publication_uses_live_authority_not_the_inspected_window(company, race):
    source = await capture(company)
    reader = await company.store.issue_token(company.actor, Role.AGENT, (company.binding_id,), "company-select-race-" + "s" * 40)
    command = await judgment(company, source.source_id, publish=True, actor=reader)
    if race == "source":
        await company.store.retract(company.actor, company.binding_id, source.source_id, "retract")
    elif race == "contract":
        async with company.store.pool.acquire() as connection:
            await connection.execute("UPDATE am_admissions SET policy_revision=$1", "0" * 64)
    else:
        async with company.store.pool.acquire() as connection:
            if race == "revision":
                await connection.execute("UPDATE am_sources SET revision=revision+1 WHERE id=$1", source.source_id)
            elif race == "binding":
                await connection.execute("UPDATE am_bindings SET revision=revision+1 WHERE id=$1", company.binding_id)
            elif race == "generation":
                await connection.execute("UPDATE am_credentials SET generation=generation+1 WHERE id=$1", reader.credential_id)
            elif race == "credential":
                await connection.execute("UPDATE am_credentials SET active=false WHERE id=$1", reader.credential_id)
            else:
                await connection.execute("DELETE FROM am_grants WHERE credential_id=$1", reader.credential_id)
    with pytest.raises(DomainError) as stale:
        await company.store.record(reader, command)
    assert stale.value.code in {"SOURCE_INELIGIBLE", "SELECTION_STALE", "ADMISSION_STALE", "SCOPE_DENIED", "AUTH_DENIED"}
    assert (await company.store.stats(company.actor, company.binding_id))["active_claims"] == 0


async def test_source_correction_invalidates_selection_and_next_consumer_reads_only_replacement(company):
    source, selected, claim = await candidate(company)
    replacement = await company.store.correct(company.actor, company.binding_id, source.source_id,
        CaptureCommand(binding_id=company.binding_id, idempotency_key="correct", origin_key="replacement",
            body=BODY, speaker="human", coverage=CaptureCoverage(status="observed_window")))
    assert replacement.state == "captured" and replacement.source_id != source.source_id
    assert (await company.store.operation(company.actor, company.binding_id, selected.id)).state == "retracted"
    assert (await company.store.inspect(company.actor, company.binding_id, selected.artifact_id))["state"] == "retracted"
    selected_new = await company.store.record(company.actor,
        await judgment(company, replacement.source_id, "replacement-select", publish=True))
    context = await judged_context(company, company.actor, ContextCommand(binding_id=company.binding_id, query="CacheKey"))
    assert claim.id not in context["refs"] and len(context["refs"]) == 1
    assert (await company.store.claim(company.actor, company.binding_id, context["refs"][0])).selection_id == selected_new.artifact_id


@pytest.mark.parametrize("target", ("claim", "selection", "operation"))
async def test_directional_withdrawal_preserves_upstream_and_independent_sibling(company, target):
    source, selected, claim = await candidate(company)
    sibling = await company.store.record(company.actor, await judgment(company, source.source_id, "sibling", publish=True))
    sibling_id = (await company.store.inspect(company.actor, company.binding_id, sibling.artifact_id))["claim_ids"][0]
    ref = {"claim": claim.id, "selection": selected.artifact_id, "operation": selected.id}[target]
    await company.store.retract(company.actor, company.binding_id, ref, "withdraw")
    await company.store.purge(company.actor, company.binding_id, ref, "purge")
    assert (await company.store.source(company.actor, company.binding_id, source.source_id)).body == BODY
    assert (await company.store.claim(company.actor, company.binding_id, sibling_id)).evidence[0].quote == BODY
    with pytest.raises(DomainError) as withdrawn:
        await company.store.record(company.actor, await judgment(company, source.source_id, "republish", publish=True))
    assert withdrawn.value.code == "DERIVATION_RETRACTED"
    discard = await company.store.record(company.actor, await judgment(company, source.source_id, "discard", label="discard"))
    assert discard.state == "selection_recorded"
    async with company.store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT draft IS NULL FROM am_claims WHERE id=$1", claim.id)


@pytest.mark.parametrize("historical_revision", (None, MIGRATIONS[0], MIGRATIONS[3]))
async def test_independent_purge_replays_before_read_fence_on_preselection_and_precompany_restore(company, historical_revision):
    source = await capture(company)
    archived = await archive_rows(company.store)
    await company.store.record(company.actor, await judgment(company, source.source_id, "derived", publish=True))
    await company.store.retract(company.actor, company.binding_id, source.source_id, "withdraw-source")
    await company.store.purge(company.actor, company.binding_id, source.source_id, "purge-source")
    head = company.store.journal.verify()["head"]
    await restore_rows(company.store, archived, historical_revision)
    with pytest.raises(DomainError) as fenced:
        await company.store.source(company.actor, company.binding_id, source.source_id)
    assert fenced.value.code == "DELETION_BARRIER"
    recovered = await company.store.recover_after_restore(company.actor.id,
        "fresh-company-restore-" + uuid.uuid4().hex + "x" * 32, head)
    async with company.store.pool.acquire() as connection:
        row = await connection.fetchrow("SELECT state,body FROM am_sources WHERE id=$1", source.source_id)
        assert row["state"] == "purged" and row["body"] is None
        assert await connection.fetchval("SELECT count(*) FROM am_admissions") == 0
    with pytest.raises(DomainError) as denied:
        await company.store.authenticate(TOKEN)
    assert denied.value.code == "AUTH_DENIED"
    with pytest.raises(DomainError) as missing:
        await company.store.source(recovered, company.binding_id, source.source_id)
    assert missing.value.code == "SOURCE_INELIGIBLE"
    assert (await company.store.stats(recovered, company.binding_id))["active_claims"] == 0


async def test_required_rule_snapshot_and_real_output_budget_are_preserved(company):
    _, _, claim = await candidate(company)
    _, admission = await company.store.search_lexical(company.actor, company.binding_id, tokens("CacheKey"), None, request_digest="a" * 64)
    proposal = await company.store.propose_rule(company.actor, RuleProposal(binding_id=company.binding_id,
        idempotency_key="required", body="Do not expose CacheKey in production. " * 20, required=True))
    rule = await company.store.approve_rule(company.actor, RuleApproval(proposal_id=proposal["proposal_id"],
        idempotency_key="approve", expected_digest=proposal["digest"], scope=RuleScope.LOCAL_PROJECT,
        target_bindings=(company.binding_id,), target_set_revision=proposal["target_set_revision"]))
    with pytest.raises(DomainError) as stale:
        await deliver(company, admission, (claim.id,))
    assert stale.value.code == "CONTEXT_STALE"
    context = await judged_context(company, company.actor, ContextCommand(binding_id=company.binding_id,
        query="CacheKey", max_bytes=6144))
    assert context["context_bytes"] <= 6144
    assert rule.id in {item["ref"] for item in json.loads(context["context"])["approved_rules"]}
    with pytest.raises(DomainError) as overflow:
        await judged_context(company, company.actor, ContextCommand(binding_id=company.binding_id,
            query="CacheKey", max_bytes=512))
    assert overflow.value.code == "REQUIRED_CONTEXT_OVERFLOW"


async def test_producer_capture_permission_never_becomes_source_read_or_selection_permission(company):
    producer = await company.store.issue_token(company.actor, Role.PRODUCER, (company.binding_id,), "isolated-producer-" + "p" * 48)
    source = await company.store.capture(producer, CaptureCommand(binding_id=company.binding_id,
        idempotency_key="producer", origin_key="producer", body=BODY, speaker="tool"))
    command = await judgment(company, source.source_id, publish=True)
    calls = (
        company.store.inspect(producer, company.binding_id, source.source_id),
        company.store.source(producer, company.binding_id, source.source_id),
        company.store.record(producer, command),
        company.store.search_lexical(producer, company.binding_id, tokens("CacheKey"), None, request_digest="a" * 64),
    )
    for call in calls:
        with pytest.raises(DomainError) as denied:
            await call
        assert denied.value.code == "SCOPE_DENIED"
    assert (await company.store.operation(producer, company.binding_id, source.id)).source_pointer.source_speaker == "tool"


async def test_original_window_validation_failures_do_not_record_discard_or_review(company):
    source = await capture(company)
    command = await judgment(company, source.source_id, publish=True)
    assertion = command.extraction.claims[0]
    cases = (
        command.model_copy(update={"window_digest": "0" * 64}),
        command.model_copy(update={"extraction": command.extraction.model_copy(update={
            "claims": (assertion.model_copy(update={"assertion_span_id": "fabricated"}),)})}),
        command.model_copy(update={"extraction": command.extraction.model_copy(update={
            "claims": (assertion.model_copy(update={"statement": "CacheKey expires after 900 seconds."}),)})}),
        command.model_copy(update={"byte_start": 1}),
    )
    for index, invalid in enumerate(cases):
        with pytest.raises(DomainError) as rejected:
            await company.store.record(company.actor, invalid.model_copy(update={"idempotency_key": f"invalid-{index}"}))
        assert rejected.value.code in {"SELECTION_STALE", "SELECTION_GROUNDING_INVALID", "SOURCE_WINDOW_INVALID"}
    stats = await company.store.stats(company.actor, company.binding_id)
    assert stats["classification_labels"] == {} and stats["active_claims"] == 0


async def test_snapshot_and_window_arguments_never_widen_source_or_candidate_access(company):
    source, selected, claim = await candidate(company, snapshot="snapshot-A")
    with pytest.raises(DomainError) as wrong_snapshot:
        await company.store.inspect(company.actor, company.binding_id, source.source_id)
    assert wrong_snapshot.value.code == "SNAPSHOT_INELIGIBLE"
    rows, admission = await company.store.search_lexical(company.actor, company.binding_id, tokens("CacheKey"), "snapshot-B", request_digest="a" * 64)
    assert rows == []
    await deliver(company, admission, snapshot="snapshot-B")
    bounded = await company.store.inspect(company.actor, company.binding_id, claim.id, "snapshot-A", max_bytes=512)
    assert bounded["id"] == claim.id and bounded["draft_window"]["byte_start"] == 0
    with pytest.raises(DomainError) as wrong_claim_snapshot:
        await company.store.inspect(company.actor, company.binding_id, claim.id, "snapshot-B", max_bytes=512)
    assert wrong_claim_snapshot.value.code == "CLAIM_INELIGIBLE"
    with pytest.raises(DomainError) as invalid_window:
        await company.store.inspect(company.actor, company.binding_id, selected.id, "snapshot-A", max_bytes=512)
    assert invalid_window.value.code == "SOURCE_WINDOW_INVALID"


async def test_uncited_known_relation_inputs_are_in_the_nonmodel_source_manifest(company):
    entries = [await candidate(company, "relation-left"), await candidate(company, "relation-right"),
        await candidate(company, "relation-uncited", body="OtherKey is retained offline.")]
    ids = [entry[2].id for entry in entries]
    from agents_memory.selection import ClaimJudgmentCommand
    manifest = await company.store.inspect(company.actor, company.binding_id, "judgment")
    written = await company.store.record(company.actor, ClaimJudgmentCommand(kind="claim_judgment",
        binding_id=company.binding_id, idempotency_key="relation-judgment", admission_id=manifest["admission_id"],
        manifest_digest=manifest["manifest_digest"], claims=manifest["claims"], sources=manifest["sources"],
        relations=({"left_id": ids[0], "right_id": ids[1], "relation": "contradicts",
            "reason": "Caller compared these alternatives with the full third-source input."},),
        reason="Caller inspected all three claims and independent original sources."))
    async with company.store.pool.acquire() as connection:
        relation_id = await connection.fetchval("SELECT id FROM am_relations WHERE judgment_id=$1", written.artifact_id)
    rows, admission = await company.store.search_lexical(company.actor, company.binding_id, tokens("CacheKey"), None, 1, request_digest="a" * 64)
    assert len(rows) == 1
    assert {item.id for item in admission.sources} == {entry[0].source_id for entry in entries}
    await deliver(company, admission, (rows[0][0].id,), (relation_id,))
    uncited = entries[2]
    assert uncited[2].id not in admission.claim_ids
    async with company.store.pool.acquire() as connection:
        await connection.execute("UPDATE am_sources SET revision=revision+1 WHERE id=$1", uncited[0].source_id)
    with pytest.raises(DomainError) as stale:
        await deliver(company, admission, (rows[0][0].id,), (relation_id,))
    assert stale.value.code == "CONTEXT_STALE"


async def test_preartifact_restore_preserves_source_but_cannot_regenerate_purged_derivation(company):
    source = await capture(company)
    archived = await archive_rows(company.store)
    selected = await company.store.record(company.actor, await judgment(company, source.source_id, publish=True))
    await company.store.retract(company.actor, company.binding_id, selected.artifact_id, "withdraw")
    await company.store.purge(company.actor, company.binding_id, selected.artifact_id, "purge")
    head = company.store.journal.verify()["head"]
    await restore_rows(company.store, archived)
    company.actor = await company.store.recover_after_restore(company.actor.id, "fresh-preartifact-" + "t" * 48, head)
    assert (await company.store.source(company.actor, company.binding_id, source.source_id)).body == BODY
    with pytest.raises(DomainError) as withdrawn:
        await company.store.record(company.actor, await judgment(company, source.source_id, "republish", publish=True))
    assert withdrawn.value.code == "DERIVATION_RETRACTED"
    assert (await company.store.stats(company.actor, company.binding_id))["active_claims"] == 0


async def test_selection_tables_are_matching_initialization_state_not_unrelated_schema(company):
    resumed = await Store.preflight_initialization(company.store.settings, TOKEN, company.actor.id, resume=True)
    assert resumed == company.actor


@pytest.mark.parametrize("delta", (-1, 1))
async def test_observed_window_coverage_must_match_the_body_at_capture_and_correct(company, delta):
    source = await capture(company)
    head = company.store.journal.verify()["head"]
    coverage = CaptureCoverage(status="observed_window", original_bytes=len(BODY.encode()) + delta)
    with pytest.raises(DomainError) as captured:
        await capture(company, "contradicted", coverage=coverage)
    with pytest.raises(DomainError) as corrected:
        await company.store.correct(company.actor, company.binding_id, source.source_id, CaptureCommand(
            binding_id=company.binding_id, idempotency_key="contradicted-correct", origin_key="contradicted-replacement",
            body=BODY, speaker="human", coverage=coverage))
    for error in (captured.value, corrected.value):
        assert error.code == "CAPTURE_COVERAGE_INVALID" and error.effect.value == "not_started"
    assert company.store.journal.verify()["head"] == head
    assert (await company.store.stats(company.actor, company.binding_id))["active_sources"] == 1


async def test_required_rule_delivery_needs_no_nonmodel_admission_but_keeps_rule_and_scope_fences(company):
    _, _, claim = await candidate(company)
    reader = await company.store.issue_token(company.actor, Role.AGENT, (company.binding_id,), "company-required-reader-" + "u" * 40)
    proposal = await company.store.propose_rule(company.actor, RuleProposal(binding_id=company.binding_id,
        idempotency_key="required", body="Keep CacheKey offline in every environment.", required=True))
    rule = await company.store.approve_rule(company.actor, RuleApproval(proposal_id=proposal["proposal_id"],
        idempotency_key="approve", expected_digest=proposal["digest"], scope=RuleScope.LOCAL_PROJECT,
        target_bindings=(company.binding_id,), target_set_revision=proposal["target_set_revision"]))
    required = await company.application.required_context(company.actor,
        ContextCommand(query="apply required safety rules", binding_id=company.binding_id))
    assert required["required"] is True and rule.body in required["context"]
    assert required["stamp"]["rules"] == [[rule.id, rule.revision, rule.digest]]
    async with company.store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT count(*) FROM am_admissions") == 0
    versions = ((rule.id, rule.revision, rule.digest),)
    with pytest.raises(DomainError) as stale_rules:
        await company.store.delivery(company.actor, company.binding_id, (), ())
    assert stale_rules.value.code == "CONTEXT_STALE"
    with pytest.raises(DomainError) as unadmitted:
        await company.store.delivery(company.actor, company.binding_id, (), versions, selected_claim_ids=(claim.id,))
    assert unadmitted.value.code == "CONTEXT_STALE"
    async with company.store.pool.acquire() as connection:
        await connection.execute("DELETE FROM am_grants WHERE credential_id=$1", reader.credential_id)
    with pytest.raises(DomainError) as denied:
        await company.store.delivery(reader, company.binding_id, (), versions)
    assert denied.value.code == "SCOPE_DENIED"


async def test_expired_nonmodel_admissions_are_swept_and_never_hold_local_drain(company):
    first, _, _ = await candidate(company, "first")
    second, _, _ = await candidate(company, "second")
    _, expired = await company.store.search_lexical(company.actor, company.binding_id, tokens("CacheKey"), None, request_digest="a" * 64)
    expire = "UPDATE am_admissions SET deadline=clock_timestamp()-interval '1 second' WHERE id=$1"
    async with company.store.pool.acquire() as connection:
        await connection.execute(expire, expired.id)
    _, live = await company.store.search_lexical(company.actor, company.binding_id, tokens("CacheKey"), None, request_digest="a" * 64)
    async with company.store.pool.acquire() as connection:
        assert [row["id"] for row in await connection.fetch("SELECT id FROM am_admissions")] == [live.id]
    pending = await company.store.retract(company.actor, company.binding_id, first.source_id, "retract-first")
    assert pending["local_drain"] == "local_drain_pending"
    async with company.store.pool.acquire() as connection:
        await connection.execute(expire, live.id)
    drained = await company.store.retract(company.actor, company.binding_id, second.source_id, "retract-second")
    assert drained["local_drain"] == "unknown"



async def judged_context(company, actor, command):
    pending = await company.application.context(actor, command)
    claim_ids = tuple(item["claim_id"] for item in pending["candidate_manifest"])
    for claim_id in claim_ids:
        await company.store.inspect(actor, company.binding_id, claim_id, command.snapshot)
    judgments = tuple(RelevanceJudgment(claim_id=claim_id, relevant=True,
        reason="Caller inspected the original candidate evidence.") for claim_id in claim_ids)
    return await company.application.context(actor, command.model_copy(update={"admission_id": pending["admission_id"], "relevance": judgments}))


async def test_migrated_source_admission_refuses_without_mutation_then_fresh_inspection_succeeds(company):
    from test_edge_boundaries import AGENT_TOKEN, record_request

    from agents_memory.edge import create_app

    store = company.store
    agent = await store.issue_token(company.actor, Role.AGENT, (company.binding_id,), AGENT_TOKEN)
    source = await capture(company, "migrated-admission-source")
    original = await judgment(company, source.source_id, "migrated-admission-selection", publish=True, actor=agent)
    archived = await archive_rows(store)
    await restore_rows(store, archived, "0005_company_selection")
    await store.reconcile_journal()
    async with store.pool.acquire() as connection:
        migrated = await connection.fetchrow("SELECT * FROM am_admissions WHERE id=$1", original.admission_id)
        assert migrated["kind"] == "nonmodel" and migrated["purpose"] == "source_selection"
        assert migrated["credential_id"] == agent.credential_id
        assert migrated["request_digest"] is None
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == "0006_agent_judged"

    edge = create_app(store.settings)
    async with edge.inner.router.lifespan_context(edge.inner):
        await edge.worker.stop()
        before = await archive_rows(store)
        status, refused = await record_request(edge, original.model_dump(mode="json"), "modern")
        assert status == 200
        assert refused["error"]["code"] == "ADMISSION_STALE"
        assert refused["error"]["effect"] == "not_started"
        assert await archive_rows(store) == before

        current = await judgment(company, source.source_id, original.idempotency_key, publish=True, actor=agent)
        assert current.admission_id != original.admission_id
        status, selected = await record_request(edge, current.model_dump(mode="json"), "modern", identifier=2)
        assert status == 200 and selected["state"] == "candidate_ready"
        assert selected["effect"] == "committed"
        inspected = await store.inspect(agent, company.binding_id, selected["artifact_id"])
        claim = await store.claim(agent, company.binding_id, inspected["claim_ids"][0])
        assert claim.interpretation_role == "caller_grounded_candidate"
        assert claim.evidence[0].source_id == source.source_id and claim.evidence[0].quote == BODY
        async with store.pool.acquire() as connection:
            assert await connection.fetchval("SELECT count(*) FROM am_source_selections") == 1
            assert await connection.fetchval(
                "SELECT count(*) FROM am_admissions WHERE id=$1", original.admission_id,
            ) == 1


async def test_forward_migration_retires_failed_model_work_without_erasing_evidence(company):
    from datetime import UTC, datetime
    source, _, caller_claim = await candidate(company, "legacy-source")
    archived = await archive_rows(company.store)
    legacy_claim = archived["am_claims"][0]
    legacy_claim.update(capability="full_semantic", interpretation_role="model_derived_candidate",
        route_revision="f" * 64, selection_id=None, policy_revision=None, extraction_operation_id=source.id)
    timestamp = datetime(2026, 10, 1, tzinfo=UTC)
    original_job = {
        "id": "job_legacy_failed", "binding_id": company.binding_id, "operation_id": source.id,
        "credential_id": company.actor.credential_id, "credential_generation": company.actor.generation,
        "kind": "extract", "source_ids": [source.source_id], "claim_ids": [caller_claim.id],
        "query_source_id": None, "snapshot": None, "state": "failed", "generation": 4, "attempts": 3,
        "lease_token": None, "deadline": None, "available_at": timestamp,
        "error_code": "QWEN_ENDPOINT_UNAVAILABLE", "created_at": timestamp,
    }
    archived["am_jobs"] = [original_job]
    for operation in archived["am_operations"]:
        if operation["id"] == source.id:
            operation.update(state="failed", error_code=original_job["error_code"], created_at=timestamp)
    await restore_rows(company.store, archived, MIGRATIONS[4])
    await company.store.reconcile_journal()
    async with company.store.pool.acquire() as connection:
        job = await connection.fetchrow("SELECT * FROM am_jobs WHERE id=$1", original_job["id"])
        audit = await connection.fetchrow("SELECT * FROM am_retired_jobs WHERE job_id=$1", original_job["id"])
        for field in ("attempts", "error_code", "created_at", "source_ids"):
            assert job[field] == original_job[field]
        assert job["state"] == "retired" and job["generation"] == original_job["generation"] + 1
        retained = json.loads(audit["original"]) if isinstance(audit["original"], str) else audit["original"]
        assert retained["error_code"] == original_job["error_code"] and retained["attempts"] == 3
        assert retained["state"] == original_job["state"] and retained["generation"] == original_job["generation"]
        retained_operation = json.loads(audit["original_operation"]) if isinstance(audit["original_operation"], str) else audit["original_operation"]
        assert retained_operation["state"] == "failed" and retained_operation["error_code"] == original_job["error_code"]
        assert datetime.fromisoformat(retained_operation["created_at"]) == timestamp
        assert job["lease_token"] is None and job["deadline"] is None
        assert job["retired_at"] is not None
        successor = await connection.fetchrow("SELECT * FROM am_pending_judgments WHERE id=$1", audit["successor_id"])
        assert successor["kind"] == "legacy_revalidation" and successor["state"] == "pending"
    inspected = await company.store.claim(company.actor, company.binding_id, caller_claim.id)
    assert inspected.interpretation_role == "model_derived_candidate" and inspected.awaiting_revalidation
    rows, _ = await company.store.search_lexical(company.actor, company.binding_id, tokens("CacheKey"), None, request_digest="a" * 64)
    assert rows == []
    stats = await company.store.stats(company.actor, company.binding_id)
    assert stats["failed"] == stats["dlq"] == 1 and stats["retired_jobs"] == 1
    selected = await company.store.record(company.actor, await judgment(company, source.source_id, "caller-revalidation", publish=True))
    assert selected.state == "candidate_ready"
    assert (await company.store.claim(company.actor, company.binding_id, caller_claim.id)).interpretation_role == "model_derived_candidate"
    resolved = await company.store.stats(company.actor, company.binding_id)
    assert resolved["failed"] == resolved["dlq"] == 0
    assert resolved["historical_jobs"]["failed"] == 1 and resolved["retired_jobs"] == 1
    assert resolved["recovery_jobs"][0]["caller_disposition"] == "resolved"
    assert resolved["recovery_jobs"][0]["unresolved"] is False
    async with company.store.pool.acquire() as connection:
        after = await connection.fetchrow("SELECT * FROM am_retired_jobs WHERE job_id=$1", original_job["id"])
        assert dict(after) == dict(audit)
        after_job = await connection.fetchrow("SELECT * FROM am_jobs WHERE id=$1", original_job["id"])
        assert dict(after_job) == dict(job)
        assert await connection.fetchval("SELECT state FROM am_pending_judgments WHERE id=$1", audit["successor_id"]) == "resolved"


@pytest.mark.parametrize("historical_revision", (MIGRATIONS[3], MIGRATIONS[4]))
@pytest.mark.parametrize("target_kind", ("claim", "operation"))
async def test_legacy_rejection_restore_retains_reason_and_original_source_block(
    company, target_kind, historical_revision,
):
    from agents_memory.domain import FeedbackCommand

    source, _, claim = await candidate(company, "rejected-legacy")
    target = claim.id if target_kind == "claim" else source.id
    reason = "The caller rejected reuse of this original evidence."
    rejected = await company.store.feedback(
        company.actor,
        FeedbackCommand(
            binding_id=company.binding_id,
            idempotency_key="legacy-rejection",
            target_ref=target,
            kind="reject",
            body=reason,
        ),
    )
    archived = await archive_rows(company.store)
    for row in archived["am_feedback"]:
        if row["id"] == rejected.artifact_id:
            assert row["kind"] == "reject"
            row["state"] = "candidate"
    for row in archived["am_claims"]:
        row.update(
            capability="full_semantic",
            interpretation_role="model_derived_candidate",
            route_revision="f" * 64,
            selection_id=None,
            policy_revision=None,
            extraction_operation_id=source.id,
        )
    archived["am_admissions"] = []
    archived["am_source_selections"] = []
    archived["am_selection_sources"] = []
    archived["am_selection_policies"] = []

    await restore_rows(company.store, archived, historical_revision)
    await company.store.reconcile_journal()
    async with company.store.pool.acquire() as connection:
        retained = await connection.fetchrow(
            "SELECT kind,state,reason,rejected_source_ids FROM am_feedback WHERE id=$1",
            rejected.artifact_id,
        )
        assert dict(retained) == {
            "kind": "reject",
            "state": "active",
            "reason": reason,
            "rejected_source_ids": [source.source_id],
        }
        assert await connection.fetchval("SELECT count(*) FROM am_floors") == 0
        before_claims = await connection.fetchval("SELECT count(*) FROM am_claims")
        before_selections = await connection.fetchval("SELECT count(*) FROM am_source_selections")

    disclosed = await company.store.inspect(
        company.actor, company.binding_id, rejected.artifact_id,
    )
    assert disclosed["reason"] == reason
    with pytest.raises(DomainError) as blocked:
        await company.store.record(
            company.actor,
            await judgment(
                company, source.source_id, "same-old-evidence", publish=True,
            ),
        )
    assert blocked.value.code == "EVIDENCE_REJECTED"
    async with company.store.pool.acquire() as connection:
        assert await connection.fetchval("SELECT count(*) FROM am_claims") == before_claims
        assert await connection.fetchval("SELECT count(*) FROM am_source_selections") == before_selections


@pytest.mark.parametrize("change", ("source_correction", "claim_correction", "source_withdrawal",
    "claim_withdrawal", "source_purge", "claim_purge"))
async def test_zero_relation_judgment_dependencies_gate_reason_and_survive_restore(company, change):
    from agents_memory.selection import ClaimJudgmentCommand

    store = company.store
    source, _, claim = await candidate(company, "zero-relation-primary")
    _, _, sibling = await candidate(company, "zero-relation-sibling", body="OtherKey is retained offline.")
    manifest = await store.inspect(company.actor, company.binding_id, "judgment")
    reason = "Caller read the withdrawn original: " + BODY
    written = await store.record(company.actor, ClaimJudgmentCommand(kind="claim_judgment",
        binding_id=company.binding_id, idempotency_key="zero-relation", admission_id=manifest["admission_id"],
        manifest_digest=manifest["manifest_digest"], claims=manifest["claims"], sources=manifest["sources"],
        relations=(), reason=reason))
    assert (await store.inspect(company.actor, company.binding_id, written.artifact_id))["reason"] == reason
    archived = await archive_rows(store)
    target = source.source_id if change.startswith("source") else claim.id
    if change.endswith("correction"):
        replacement = await store.correct(company.actor, company.binding_id, target,
            CaptureCommand(binding_id=company.binding_id, idempotency_key="zero-relation-correct",
                origin_key="corrected-evidence", body=BODY, speaker="human",
                coverage=CaptureCoverage(status="observed_window")))
        assert replacement.state == "captured"
    else:
        await store.retract(company.actor, company.binding_id, target, "zero-relation-withdraw")
        if change.endswith("purge"):
            await store.purge(company.actor, company.binding_id, target, "zero-relation-purge")
    inspected = await store.inspect(company.actor, company.binding_id, written.artifact_id)
    assert inspected["state"] == "retracted" and reason not in json.dumps(inspected)
    assert (await store.claim(company.actor, company.binding_id, sibling.id)).state == "active"
    assert (await store.operation(company.actor, company.binding_id, written.id)).state == "retracted"
    async with store.pool.acquire() as connection:
        row = await connection.fetchrow("SELECT * FROM am_claim_judgments WHERE id=$1", written.artifact_id)
        saved_claims, saved_sources = row["claims"], row["sources"]
        if change.endswith("purge"):
            assert row["reason"] is None and row["relations"] is None
        else:
            assert row["reason"] == reason
    head = store.journal.verify()["head"]
    await restore_rows(store, archived)
    company.actor = await store.recover_after_restore(company.actor.id, "fresh-zero-relation-" + "j" * 48, head)
    restored = await store.inspect(company.actor, company.binding_id, written.artifact_id)
    assert restored["state"] == "retracted" and reason not in json.dumps(restored)
    assert (await store.claim(company.actor, company.binding_id, sibling.id)).state == "active"
    async with store.pool.acquire() as connection:
        row = await connection.fetchrow("SELECT * FROM am_claim_judgments WHERE id=$1", written.artifact_id)
        assert row["claims"] == saved_claims and row["sources"] == saved_sources
        if change.endswith("purge"):
            assert row["reason"] is None and row["relations"] is None
