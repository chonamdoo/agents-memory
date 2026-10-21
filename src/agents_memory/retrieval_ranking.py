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

# Lexical arm: Okapi BM25 over the eligible set (k1=1.2, b=0.75). Stored tokens are a set per claim,
# so tf is 1 and IDF plus length normalization separate claims sharing the same query tokens.
# A claim enters only by sharing a whole query token. Within those claims, a Hangul query word the
# claim lacks may still match one of its Hangul words that shares at least half of the query word's
# jamo trigrams (one-letter typos); it then counts as that claim word, weighted by the similarity.
# Typo tolerance is computed here at query time, so stored tokens and every other tokenizer user
# are unchanged and no reindex is needed.
# Entity arm: entities shared by more claims than the default pool (20) cannot rank them and are
# ignored. Scores are rounded before ordering so equal evidence always falls back to the id order.
RANKING_SQL = """, query_tokens AS MATERIALIZED (
                SELECT DISTINCT token FROM unnest($2::text[]) token
            ), corpus_stats AS MATERIALIZED (
                SELECT count(*)::float8 AS n, GREATEST(avg(cardinality(lexical_tokens)), 1)::float8 AS average_length FROM eligible
            ), word_matches AS MATERIALIZED (
                SELECT id, lexical_tokens FROM eligible WHERE lexical_tokens && $2::text[]
            ), token_frequency AS MATERIALIZED (
                SELECT claim_token.value AS token, count(*)::float8 AS df
                FROM word_matches m CROSS JOIN LATERAL unnest(m.lexical_tokens) AS claim_token(value)
                WHERE claim_token.value IN (SELECT token FROM query_tokens) GROUP BY claim_token.value
            ), exact_weights AS (
                SELECT m.id, sum(ln(1 + (s.n - f.df + 0.5) / (f.df + 0.5))) AS weight
                FROM word_matches m CROSS JOIN LATERAL unnest(m.lexical_tokens) AS claim_token(value)
                JOIN token_frequency f ON f.token=claim_token.value CROSS JOIN corpus_stats s
                GROUP BY m.id
            ), query_trigrams AS MATERIALIZED (
                SELECT DISTINCT q.token AS word, substr(normalize(q.token, NFD), position, 3) AS trigram
                FROM query_tokens q CROSS JOIN LATERAL generate_series(1, length(normalize(q.token, NFD)) - 2) position
                WHERE q.token ~ '^[가-힣]{2,}$'
            ), query_trigram_counts AS MATERIALIZED (
                SELECT word, count(*)::float8 AS total FROM query_trigrams GROUP BY word
            ), query_syllables AS MATERIALIZED (
                SELECT DISTINCT substr(word, position, 1) AS syllable
                FROM query_trigram_counts CROSS JOIN LATERAL generate_series(1, length(word)) position
            ), candidate_words AS MATERIALIZED (
                -- A word sharing half of a query word's jamo trigrams shares at least one syllable with it,
                -- so only those words are decomposed.
                SELECT word FROM (
                    SELECT DISTINCT claim_token.value AS word
                    FROM word_matches m CROSS JOIN LATERAL unnest(m.lexical_tokens) AS claim_token(value)
                    WHERE claim_token.value ~ '^[가-힣]{2,}$' AND claim_token.value NOT IN (SELECT token FROM query_tokens)
                ) words
                WHERE EXISTS(SELECT 1 FROM query_syllables q WHERE strpos(words.word, q.syllable) > 0)
            ), claim_trigrams AS MATERIALIZED (
                SELECT DISTINCT w.word, substr(normalize(w.word, NFD), position, 3) AS trigram
                FROM candidate_words w CROSS JOIN LATERAL generate_series(1, length(normalize(w.word, NFD)) - 2) position
            ), fuzzy_pairs AS MATERIALIZED (
                SELECT q.word AS query_word, c.word AS claim_word, count(*) / max(t.total) AS similarity
                FROM query_trigrams q JOIN claim_trigrams c ON c.trigram=q.trigram JOIN query_trigram_counts t ON t.word=q.word
                GROUP BY q.word, c.word HAVING count(*) / max(t.total) >= 0.5
            ), fuzzy_words AS MATERIALIZED (
                SELECT coalesce(array_agg(DISTINCT claim_word), '{}'::text[]) AS words FROM fuzzy_pairs
            ), fuzzy_frequency AS MATERIALIZED (
                SELECT claim_token.value AS token, count(*)::float8 AS df
                FROM eligible e CROSS JOIN fuzzy_words w CROSS JOIN LATERAL unnest(e.lexical_tokens) AS claim_token(value)
                WHERE e.lexical_tokens && w.words AND claim_token.value = ANY(w.words) GROUP BY claim_token.value
            ), claim_words AS MATERIALIZED (
                SELECT DISTINCT m.id, claim_token.value AS word
                FROM word_matches m CROSS JOIN fuzzy_words w CROSS JOIN LATERAL unnest(m.lexical_tokens) AS claim_token(value)
                WHERE m.lexical_tokens && w.words AND claim_token.value = ANY(w.words)
            ), fuzzy_weights AS (
                SELECT id, sum(weight) AS weight FROM (
                    SELECT w.id, p.query_word, max(p.similarity * ln(1 + (s.n - f.df + 0.5) / (f.df + 0.5))) AS weight
                    FROM claim_words w JOIN fuzzy_pairs p ON p.claim_word=w.word JOIN fuzzy_frequency f ON f.token=w.word
                    JOIN word_matches m ON m.id=w.id CROSS JOIN corpus_stats s
                    WHERE NOT m.lexical_tokens @> ARRAY[p.query_word]
                    GROUP BY w.id, p.query_word
                ) per_query_word GROUP BY id
            ), lexical_scores AS (
                SELECT m.id, round(((coalesce(x.weight, 0) + coalesce(z.weight, 0))
                    * 2.2 / (1 + 1.2 * (0.25 + 0.75 * cardinality(m.lexical_tokens) / s.average_length)))::numeric, 9) AS score
                FROM word_matches m LEFT JOIN exact_weights x ON x.id=m.id LEFT JOIN fuzzy_weights z ON z.id=m.id
                CROSS JOIN corpus_stats s
            ), lexical_candidates AS (
                SELECT id,row_number() OVER(ORDER BY score DESC,id) AS rank
                FROM lexical_scores ORDER BY score DESC,id LIMIT $5
            ), distinctive_entities AS (
                SELECT e.search_name FROM eligible c JOIN am_entities e ON e.claim_id=c.id
                WHERE e.search_name=ANY($6::text[]) GROUP BY e.search_name HAVING count(DISTINCT c.id)<=20
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
