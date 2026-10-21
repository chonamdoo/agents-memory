"""Candidate ranking over the already-eligible claim set.

This is the only retrieval surface the offline ranking loop may edit
(research/autoresearch-eval-loop-proposal.ko.md). It runs after the `eligible`
CTE in `Store.search_lexical`, which owns every integrity filter and stays frozen.

Contract: the fragment continues a `WITH eligible AS (...), query_terms AS (...)` query,
may read only `eligible`, `am_entities`, `query_terms` and the parameters $2 (all search
tokens: query plus caller expansions), $5 (limit) and $6 (entity search names of $2), and
must end with a SELECT of `c.*` plus an `arms` text[] column from `eligible c`, ordered best
first, with at most $5 rows. `query_terms` is one row: `tokens` (the caller's own query
tokens, a subset of $2) and `search_names` (their entity search names). Without
expansions both equal $2 and $6.
"""
from __future__ import annotations

EXPANSION_WEIGHT = 0.5

# A claim's lexical score counts its overlap with the caller's query tokens fully and its overlap with
# expansion-only tokens at EXPANSION_WEIGHT; entity matches are weighed the same way. Without
# expansions every token is a query token, so the order is the plain overlap order.
RANKING_SQL = f""", lexical_candidates AS (
                SELECT id,row_number() OVER(ORDER BY score DESC,id) AS rank FROM (
                    SELECT e.id,cardinality(ARRAY(SELECT unnest(e.lexical_tokens) INTERSECT SELECT unnest(q.tokens)))
                        + {EXPANSION_WEIGHT}*cardinality(ARRAY(SELECT unnest(e.lexical_tokens) INTERSECT SELECT unnest($2::text[])
                            EXCEPT SELECT unnest(q.tokens))) AS score
                    FROM eligible e CROSS JOIN query_terms q WHERE e.lexical_tokens && $2::text[]
                ) scored ORDER BY score DESC,id LIMIT $5
            ), entity_candidates AS (
                SELECT c.id,row_number() OVER(ORDER BY sum(CASE WHEN e.search_name=ANY(q.search_names) THEN 1.0
                    ELSE {EXPANSION_WEIGHT} END) DESC,c.id) AS rank
                FROM eligible c JOIN am_entities e ON e.claim_id=c.id CROSS JOIN query_terms q WHERE e.search_name=ANY($6::text[])
                GROUP BY c.id ORDER BY sum(CASE WHEN e.search_name=ANY(q.search_names) THEN 1.0
                    ELSE {EXPANSION_WEIGHT} END) DESC,c.id LIMIT $5
            ), arms AS (
                SELECT id,rank,'lexical'::text AS arm FROM lexical_candidates
                UNION ALL SELECT id,rank,'entity' FROM entity_candidates
            ), fused AS (
                SELECT id,sum(1.0/(60+rank)) AS score,array_agg(arm ORDER BY arm) AS arms
                FROM arms GROUP BY id ORDER BY score DESC,id LIMIT $5
            ) SELECT c.*,f.arms FROM fused f JOIN eligible c ON c.id=f.id ORDER BY f.score DESC,c.id"""
