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

EXPANSION_ARM_WEIGHT = 1.0

# The lexical and entity arms rank by the caller's own query tokens. Tokens that only expansions brought
# form a separate RRF arm weighted EXPANSION_ARM_WEIGHT. Without expansions that arm is empty and
# the query tokens are all the tokens, so the order is the original one.
RANKING_SQL = f""", lexical_candidates AS (
                SELECT e.id,row_number() OVER(ORDER BY cardinality(ARRAY(SELECT unnest(e.lexical_tokens) INTERSECT SELECT unnest(q.tokens))) DESC,e.id) AS rank
                FROM eligible e CROSS JOIN query_terms q WHERE e.lexical_tokens && q.tokens
                ORDER BY cardinality(ARRAY(SELECT unnest(e.lexical_tokens) INTERSECT SELECT unnest(q.tokens))) DESC,e.id LIMIT $5
            ), expansion_candidates AS (
                SELECT id,row_number() OVER(ORDER BY overlap DESC,id) AS rank FROM (
                    SELECT e.id,cardinality(ARRAY(SELECT unnest(e.lexical_tokens) INTERSECT SELECT unnest($2::text[])
                        EXCEPT SELECT unnest(q.tokens))) AS overlap
                    FROM eligible e CROSS JOIN query_terms q WHERE e.lexical_tokens && $2::text[]
                ) scored WHERE overlap>0 ORDER BY overlap DESC,id LIMIT $5
            ), entity_candidates AS (
                SELECT c.id,row_number() OVER(ORDER BY count(*) DESC,c.id) AS rank
                FROM eligible c JOIN am_entities e ON e.claim_id=c.id CROSS JOIN query_terms q WHERE e.search_name=ANY(q.search_names) AND $6::text[] IS NOT NULL
                GROUP BY c.id ORDER BY count(*) DESC,c.id LIMIT $5
            ), arms AS (
                SELECT id,rank,'lexical'::text AS arm,1.0 AS weight FROM lexical_candidates
                UNION ALL SELECT id,rank,'entity',1.0 FROM entity_candidates
                UNION ALL SELECT id,rank,'expansion',{EXPANSION_ARM_WEIGHT} FROM expansion_candidates
            ), fused AS (
                SELECT id,sum(weight/(60+rank)) AS score,array_agg(arm ORDER BY arm) AS arms
                FROM arms GROUP BY id ORDER BY score DESC,id LIMIT $5
            ) SELECT c.*,f.arms FROM fused f JOIN eligible c ON c.id=f.id ORDER BY f.score DESC,c.id"""
