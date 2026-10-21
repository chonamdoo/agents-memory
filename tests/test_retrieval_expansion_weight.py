"""Integrity of the expansion-weighted search path.

`search_lexical` receives the caller's own query tokens apart from the expansion tokens so the
ranking may weigh them apart. These cases pin what that split must never change: without
expansions the result is the same as before, and a claim reachable only through expansion words
still has to pass the frozen eligibility filter (retraction, binding, realm).
"""
from __future__ import annotations

import hashlib
import itertools

import pytest
from test_company_authority import TOKEN, candidate
from test_company_authority import company as company

from agents_memory.domain import ContextCommand, DomainError
from agents_memory.lexical import tokens

QUERY = "결제 화면 문서"
EXPANSIONS = ("재시도 정책", "최대 3회")
TARGET = "PaymentRetryPolicy 재시도 정책은 최대 3회다."
NEIGHBOR = "결제 화면 문서는 별도로 관리한다."
_digests = itertools.count()


def _digest() -> str:
    return hashlib.sha256(f"expansion-weight-{next(_digests)}".encode()).hexdigest()


async def expanded_ids(company, query=QUERY, expansions=EXPANSIONS) -> list[str]:
    terms = tokens(" ".join((query, *expansions)))
    searched = set(terms)
    rows, _ = await company.store.search_lexical(company.actor, company.binding_id, terms, None,
        request_digest=_digest(), query_tokens=[term for term in tokens(query) if term in searched])
    store_ids = [claim.id for claim, _ in rows]
    pending = await company.application.context(company.actor, ContextCommand(
        binding_id=company.binding_id, query=query, query_expansions=expansions))
    assert [item["claim_id"] for item in pending["candidate_manifest"]] == store_ids
    return store_ids


async def test_omitted_query_tokens_rank_exactly_like_explicit_ones(company):
    await candidate(company, "weight-target", body=TARGET)
    await candidate(company, "weight-neighbor", body=NEIGHBOR)
    terms = tokens(" ".join((QUERY, *EXPANSIONS)))
    implicit, _ = await company.store.search_lexical(company.actor, company.binding_id, terms, None,
        request_digest=_digest())
    explicit, _ = await company.store.search_lexical(company.actor, company.binding_id, terms, None,
        request_digest=_digest(), query_tokens=terms)
    assert [claim.id for claim, _ in implicit] == [claim.id for claim, _ in explicit]


async def test_query_tokens_outside_the_search_tokens_are_refused(company):
    with pytest.raises(DomainError) as refused:
        await company.store.search_lexical(company.actor, company.binding_id, tokens(QUERY), None,
            request_digest=_digest(), query_tokens=tokens("다른 질의"))
    assert refused.value.code == "SEARCH_LIMIT_INVALID"


async def test_a_retracted_claim_reached_only_through_expansions_never_resurfaces(company):
    source, _, target = await candidate(company, "weight-retract", body=TARGET)
    _, _, neighbor = await candidate(company, "weight-retract-neighbor", body=NEIGHBOR)
    assert target.id not in await expanded_ids(company, expansions=())
    assert {target.id, neighbor.id} <= set(await expanded_ids(company))
    await company.store.retract(company.actor, company.binding_id, source.source_id, "weight-retract-source")
    ids = await expanded_ids(company)
    assert target.id not in ids and neighbor.id in ids


async def test_a_withdrawn_claim_reached_only_through_expansions_never_resurfaces(company):
    _, _, target = await candidate(company, "weight-withdraw", body=TARGET)
    _, _, neighbor = await candidate(company, "weight-withdraw-neighbor", body=NEIGHBOR)
    assert target.id in await expanded_ids(company)
    await company.store.retract(company.actor, company.binding_id, target.id, "weight-withdraw-claim")
    ids = await expanded_ids(company)
    assert target.id not in ids and neighbor.id in ids


async def test_expansions_never_reach_a_claim_in_another_binding(company):
    other = await company.store.register_binding(company.actor, "Other synthetic project", "/synthetic/other", "weight-other")
    company.actor = await company.store.authenticate(TOKEN)
    home = company.binding_id
    company.binding_id = other.id
    _, _, foreign = await candidate(company, "weight-foreign", body=TARGET)
    assert foreign.id in await expanded_ids(company)
    company.binding_id = home
    _, _, neighbor = await candidate(company, "weight-home-neighbor", body=NEIGHBOR)
    ids = await expanded_ids(company)
    assert foreign.id not in ids and neighbor.id in ids


async def test_expansions_never_reach_a_selection_from_another_realm(company):
    _, _, target = await candidate(company, "weight-realm", body=TARGET)
    _, _, neighbor = await candidate(company, "weight-realm-neighbor", body=NEIGHBOR)
    assert target.id in await expanded_ids(company)
    async with company.store.pool.acquire() as connection:
        await connection.execute("""UPDATE am_source_selections SET realm='other_realm'
            WHERE id=(SELECT selection_id FROM am_claims WHERE id=$1)""", target.id)
    ids = await expanded_ids(company)
    assert target.id not in ids and neighbor.id in ids
