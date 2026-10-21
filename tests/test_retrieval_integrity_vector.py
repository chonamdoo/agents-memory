"""The retrieval integrity gate, re-run with a dense arm in the candidate ranking.

The vector side table is a view that gives every claim in the schema (retracted, purged, other
binding, other snapshot...) the query's own vector, so the dense arm sees every stored claim as a
perfect match; both are views so backup-restore cases cannot empty them. Ineligible claims can
therefore only stay out if the dense arm reads through the frozen `eligible` CTE, which is what
each case asserts. A control fragment that bypasses `eligible` must be caught.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import test_retrieval_integrity as integrity
from test_company_authority import company as company

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evaluation" / "semantic_loop"))

from arms import dense, hybrid, slug  # noqa: E402

from agents_memory.domain import DomainError  # noqa: E402

MODEL = "integrity-unit-vector"
CASES = [name for name in dir(integrity) if name.startswith("test_")]


@pytest.fixture(params=("dense", "hybrid"))
async def vector_company(request, company, monkeypatch):
    name = slug(MODEL)
    async with company.store.pool.acquire() as connection:
        await connection.execute(f"""
            CREATE VIEW am_loop_vec_{name} AS SELECT id AS claim_id, '[1,0,0,0]'::public.vector(4) AS embedding FROM am_claims;
            CREATE VIEW am_loop_query_{name} AS SELECT true AS singleton, '[1,0,0,0]'::public.vector(4) AS embedding""")
    monkeypatch.setattr("agents_memory.store.RANKING_SQL", dense(MODEL) if request.param == "dense" else hybrid(MODEL))
    return company


@pytest.mark.parametrize("case", CASES)
async def test_integrity_case_with_dense_arm(vector_company, case):
    function = getattr(integrity, case)
    arguments = {}
    marks = getattr(function, "pytestmark", ())
    for mark in marks:
        if mark.name == "parametrize":
            names, values = mark.args
            arguments[names] = values[0]
    await function(vector_company, **arguments)


BYPASS = """, dense_candidates AS (
                SELECT a.id,row_number() OVER(ORDER BY a.id) AS rank FROM am_claims a
                WHERE $2::text[] IS NOT NULL AND $6::text[] IS NOT NULL ORDER BY a.id LIMIT $5
            ) SELECT a.*,ARRAY['dense']::text[] AS arms FROM dense_candidates d JOIN am_claims a ON a.id=d.id
            CROSS JOIN (SELECT count(*) FROM eligible) used ORDER BY d.rank"""


async def test_a_dense_arm_that_bypasses_eligibility_is_caught(company, monkeypatch):
    # Either the case sees the leak, or the store's lineage recheck refuses the ineligible claim.
    monkeypatch.setattr("agents_memory.store.RANKING_SQL", BYPASS)
    with pytest.raises((AssertionError, DomainError)) as caught:
        await integrity.test_i1_retracted_source_never_resurfaces(company)
    assert not isinstance(caught.value, DomainError) or caught.value.code == "SOURCE_INELIGIBLE"
