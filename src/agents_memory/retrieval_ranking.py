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

# Two rankings of the same form: one by the caller's own query tokens, one by all search tokens
# (query plus expansions). Candidates are merged by their better rank in either list; a tie goes
# to the query ranking. Without expansions both lists are the same, so the order is the original one.
_LIST = """{name}_lexical AS (
                SELECT e.id,row_number() OVER(ORDER BY cardinality(ARRAY(SELECT unnest(e.lexical_tokens) INTERSECT SELECT unnest({tokens}))) DESC,e.id) AS rank
                FROM eligible e CROSS JOIN query_terms q WHERE e.lexical_tokens && {tokens}
                ORDER BY cardinality(ARRAY(SELECT unnest(e.lexical_tokens) INTERSECT SELECT unnest({tokens}))) DESC,e.id LIMIT $5
            ), {name}_entity AS (
                SELECT c.id,row_number() OVER(ORDER BY count(*) DESC,c.id) AS rank
                FROM eligible c JOIN am_entities e ON e.claim_id=c.id CROSS JOIN query_terms q WHERE e.search_name=ANY({names})
                GROUP BY c.id ORDER BY count(*) DESC,c.id LIMIT $5
            ), {name}_arms AS (
                SELECT id,rank,'lexical'::text AS arm FROM {name}_lexical UNION ALL SELECT id,rank,'entity' FROM {name}_entity
            ), {name}_list AS (
                SELECT id,row_number() OVER(ORDER BY score DESC,id) AS rank FROM (
                    SELECT id,sum(1.0/(60+rank)) AS score FROM {name}_arms GROUP BY id
                ) scored ORDER BY score DESC,id LIMIT $5
            """

RANKING_SQL = (", " + _LIST.format(name="query", tokens="q.tokens", names="q.search_names")
               + "), " + _LIST.format(name="full", tokens="$2::text[]", names="$6::text[]") + """
            ), arms AS (
                SELECT id,arm FROM query_arms UNION SELECT id,arm FROM full_arms
            ), merged AS (
                SELECT coalesce(q.id,f.id) AS id,coalesce(q.rank,1000) AS query_rank,coalesce(f.rank,1000) AS full_rank
                FROM query_list q FULL JOIN full_list f ON f.id=q.id
            ), fused AS (
                SELECT m.id,least(m.query_rank,m.full_rank) AS best,m.query_rank,m.full_rank,
                    ARRAY(SELECT a.arm FROM arms a WHERE a.id=m.id ORDER BY a.arm) AS arms
                FROM merged m ORDER BY best,query_rank,full_rank,id LIMIT $5
            ) SELECT c.*,f.arms FROM fused f JOIN eligible c ON c.id=f.id ORDER BY f.best,f.query_rank,f.full_rank,c.id""")
