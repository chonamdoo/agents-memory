"""Ranking fragments for the semantic loop's comparison arms (offline only).

Every fragment continues the frozen `WITH eligible AS (...)` of Store._lexical_recall_inputs, so
a dense candidate can only ever be an eligible claim. Vectors live in side tables of the cached
evaluation schema: `am_loop_vec_<slug>(claim_id, embedding)` for claims and a one-row
`am_loop_query_<slug>(singleton, embedding)` holding the current query vector, written before
each search. Cosine distance is exact (no approximate index), so scope filters can never make an
approximate search silently return fewer rows.
"""
from __future__ import annotations

import re

from agents_memory.retrieval_ranking import RANKING_SQL as LEXICAL_SQL

_LEXICAL_BODY = LEXICAL_SQL[:LEXICAL_SQL.index("            ), arms AS (")]


def slug(model: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", model.lower()).strip("_")[:40]


def _dense_cte(model: str) -> str:
    name = slug(model)
    return f"""dense_candidates AS (
                SELECT e.id,row_number() OVER(ORDER BY v.embedding OPERATOR(public.<=>) q.embedding, e.id) AS rank
                FROM eligible e JOIN am_loop_vec_{name} v ON v.claim_id=e.id CROSS JOIN am_loop_query_{name} q
                WHERE $2::text[] IS NOT NULL AND $6::text[] IS NOT NULL
                ORDER BY v.embedding OPERATOR(public.<=>) q.embedding, e.id LIMIT $5
            )"""


def dense(model: str) -> str:
    """D(m): dense candidates only."""
    return f""", {_dense_cte(model)} SELECT c.*,ARRAY['dense']::text[] AS arms
            FROM dense_candidates d JOIN eligible c ON c.id=d.id ORDER BY d.rank"""


def hybrid(model: str, dense_weight: float = 1.0, k: int = 60) -> str:
    """H(m): the lexical and entity arms of the production ranking plus a dense arm, fused by RRF."""
    return f"""{_LEXICAL_BODY}            ), {_dense_cte(model)}, arms AS (
                SELECT id,rank,'lexical'::text AS arm,1.0::numeric AS weight FROM lexical_candidates
                UNION ALL SELECT id,rank,'entity',1.0 FROM entity_candidates
                UNION ALL SELECT id,rank,'dense',{float(dense_weight)}::numeric FROM dense_candidates
            ), fused AS (
                SELECT id,sum(weight/({int(k)}+rank)) AS score,array_agg(arm ORDER BY arm) AS arms
                FROM arms GROUP BY id ORDER BY score DESC,id LIMIT $5
            ) SELECT c.*,f.arms FROM fused f JOIN eligible c ON c.id=f.id ORDER BY f.score DESC,c.id"""


def side_tables(model: str, dimensions: int) -> str:
    name = slug(model)
    return (f"CREATE TABLE IF NOT EXISTS am_loop_vec_{name}(claim_id text PRIMARY KEY, embedding public.vector({dimensions}));"
            f"CREATE TABLE IF NOT EXISTS am_loop_query_{name}(singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),"
            f" embedding public.vector({dimensions}))")
