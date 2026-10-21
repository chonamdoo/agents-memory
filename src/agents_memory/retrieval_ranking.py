"""Candidate ranking over the already-eligible claim set.

This is the only retrieval surface the offline ranking loop may edit
(research/autoresearch-eval-loop-proposal.ko.md). It runs after the `eligible`
CTE in `Store.search_lexical`, which owns every integrity filter and stays frozen.

Contract: the fragment continues a `WITH eligible AS (...)` query, may read only
`eligible`, `am_entities` and the parameters $2 (query tokens), $5 (limit) and
$6 (entity search names), and must end with a SELECT of `c.*` plus an `arms`
text[] column from `eligible c`, ordered best first, with at most $5 rows.
"""
from __future__ import annotations

# Okapi BM25 over the eligible set: tokens are a set per claim, so tf is 1 and only IDF and
# length normalization (k1=1.2, b=0.75) separate claims that share the same query tokens.
RANKING_SQL = """, query_tokens AS (
                SELECT DISTINCT token FROM unnest($2::text[]) token
            ), corpus_stats AS MATERIALIZED (
                SELECT count(*)::float8 AS n, GREATEST(avg(cardinality(lexical_tokens)), 1)::float8 AS average_length FROM eligible
            ), token_frequency AS MATERIALIZED (
                SELECT token, count(*)::float8 AS df FROM eligible e CROSS JOIN LATERAL unnest(e.lexical_tokens) token
                WHERE token IN (SELECT token FROM query_tokens) GROUP BY token
            ), word_tokens AS MATERIALIZED (
                SELECT coalesce(array_agg(token), '{}'::text[]) AS tokens FROM query_tokens WHERE left(token, 1) <> '~'
            ), word_matches AS (
                -- Jamo trigrams ("~" prefix) only add score: a claim enters the arm by sharing a whole token.
                SELECT e.id, e.lexical_tokens FROM eligible e CROSS JOIN word_tokens w WHERE e.lexical_tokens && w.tokens
            ), lexical_scores AS (
                SELECT e.id, sum(ln(1 + (s.n - f.df + 0.5) / (f.df + 0.5))
                    * 2.2 / (1 + 1.2 * (0.25 + 0.75 * cardinality(e.lexical_tokens) / s.average_length))) AS score
                FROM word_matches e CROSS JOIN LATERAL unnest(e.lexical_tokens) AS claim_token(value)
                JOIN token_frequency f ON f.token=claim_token.value CROSS JOIN corpus_stats s
                GROUP BY e.id
            ), lexical_candidates AS (
                SELECT id,row_number() OVER(ORDER BY score DESC,id) AS rank
                FROM lexical_scores ORDER BY score DESC,id LIMIT $5
            ), distinctive_entities AS (
                -- An entity shared by more claims than the pool holds cannot rank them, so it is not evidence.
                SELECT e.search_name FROM eligible c JOIN am_entities e ON e.claim_id=c.id
                WHERE e.search_name=ANY($6::text[]) GROUP BY e.search_name HAVING count(DISTINCT c.id)<=$5
            ), entity_candidates AS (
                SELECT c.id,row_number() OVER(ORDER BY count(*) DESC,c.id) AS rank
                FROM eligible c JOIN am_entities e ON e.claim_id=c.id
                WHERE e.search_name IN (SELECT search_name FROM distinctive_entities)
                GROUP BY c.id ORDER BY count(*) DESC,c.id LIMIT $5
            ), arms AS (
                SELECT id,rank,'lexical'::text AS arm FROM lexical_candidates
                UNION ALL SELECT id,rank,'entity' FROM entity_candidates
            ), fused AS (
                SELECT id,sum(1.0/(60+rank)) AS score,array_agg(arm ORDER BY arm) AS arms
                FROM arms GROUP BY id ORDER BY score DESC,id LIMIT $5
            ) SELECT c.*,f.arms FROM fused f JOIN eligible c ON c.id=f.id ORDER BY f.score DESC,c.id"""
