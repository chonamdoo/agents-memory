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
# claim lacks may still match one of its Hangul words that shares at least two and at least half of
# the query word's jamo trigrams (one-letter typos); it then counts as that claim word, weighted by
# the similarity; it re-ranks the 200 best exact matches. Typo tolerance is computed here at query time, so stored tokens and every other
# tokenizer user are unchanged and no reindex is needed. It is bounded so long queries stay cheap:
# only whole Hangul query words that occur in no eligible claim (a correctly spelled word is already
# matched exactly), not the bigrams cut from longer query words, only the first 16,
# only claim words sharing a syllable with them (a heuristic prefilter), at most 512 of those, and
# only on UTF8 servers where normalize() is available.
# Entity arm: entities shared by more claims than the default pool (20) cannot rank them and are
# ignored. Scores are rounded before ordering so equal evidence always falls back to the id order.
RANKING_SQL = """, query_tokens AS MATERIALIZED (
                SELECT DISTINCT token FROM unnest($2::text[]) token
            ), corpus_stats AS MATERIALIZED (
                SELECT count(*)::float8 AS n, GREATEST(avg(cardinality(lexical_tokens)), 1)::float8 AS average_length FROM eligible
            ), word_matches AS MATERIALIZED (
                SELECT id, lexical_tokens, ARRAY(SELECT unnest(lexical_tokens) INTERSECT SELECT unnest($2::text[])) AS matched
                FROM eligible WHERE lexical_tokens && $2::text[]
            ), matched_tokens AS MATERIALIZED (
                SELECT m.id, matched_token.value AS token FROM word_matches m CROSS JOIN LATERAL unnest(m.matched) AS matched_token(value)
            ), token_frequency AS MATERIALIZED (
                SELECT token, count(*)::float8 AS df FROM matched_tokens GROUP BY token
            ), exact_scores AS MATERIALIZED (
                SELECT m.id, sum(ln(1 + (s.n - f.df + 0.5) / (f.df + 0.5)))
                    * 2.2 / (1 + 1.2 * (0.25 + 0.75 * cardinality(m.lexical_tokens) / s.average_length)) AS score
                FROM word_matches m JOIN matched_tokens t ON t.id=m.id JOIN token_frequency f ON f.token=t.token
                CROSS JOIN corpus_stats s GROUP BY m.id, m.lexical_tokens, s.average_length
            ), rerank_pool AS MATERIALIZED (
                -- Typo evidence only adds score, so the final candidates always come from the best exact matches.
                SELECT m.id, m.lexical_tokens, x.score FROM exact_scores x JOIN word_matches m ON m.id=x.id
                ORDER BY x.score DESC, x.id LIMIT 200
            ), query_hangul AS MATERIALIZED (
                SELECT token, min(ordinal) AS ordinal FROM unnest($2::text[]) WITH ORDINALITY AS query(token, ordinal)
                WHERE token ~ '^[가-힣]{2,}$' AND current_setting('server_encoding')='UTF8' GROUP BY token
            ), query_words AS MATERIALIZED (
                SELECT token FROM query_hangul w
                WHERE NOT EXISTS(SELECT 1 FROM token_frequency f WHERE f.token=w.token)
                AND NOT EXISTS(SELECT 1 FROM query_hangul longer
                    WHERE length(longer.token) > length(w.token) AND strpos(longer.token, w.token) > 0)
                ORDER BY ordinal, token LIMIT 16
            ), query_trigrams AS MATERIALIZED (
                SELECT DISTINCT q.token AS word, substr(normalize(q.token, NFD), position, 3) AS trigram
                FROM query_words q CROSS JOIN LATERAL generate_series(1, length(normalize(q.token, NFD)) - 2) position
            ), query_trigram_counts AS MATERIALIZED (
                SELECT word, count(*)::float8 AS total FROM query_trigrams GROUP BY word
            ), query_syllables AS MATERIALIZED (
                SELECT DISTINCT substr(word, position, 1) AS syllable
                FROM query_trigram_counts CROSS JOIN LATERAL generate_series(1, length(word)) position
            ), candidate_words AS MATERIALIZED (
                SELECT word FROM (
                    SELECT DISTINCT claim_token.value AS word
                    FROM rerank_pool m CROSS JOIN LATERAL unnest(m.lexical_tokens) AS claim_token(value)
                    WHERE EXISTS(SELECT 1 FROM query_words)
                ) words
                WHERE word ~ '^[가-힣]{2,}$' AND word NOT IN (SELECT token FROM query_tokens) AND EXISTS(SELECT 1 FROM query_syllables q WHERE strpos(words.word, q.syllable) > 0)
                ORDER BY word LIMIT 512
            ), claim_trigrams AS MATERIALIZED (
                SELECT DISTINCT w.word, substr(normalize(w.word, NFD), position, 3) AS trigram
                FROM candidate_words w CROSS JOIN LATERAL generate_series(1, length(normalize(w.word, NFD)) - 2) position
            ), fuzzy_pairs AS MATERIALIZED (
                SELECT q.word AS query_word, c.word AS claim_word, count(*) / max(t.total) AS similarity
                FROM query_trigrams q JOIN claim_trigrams c ON c.trigram=q.trigram JOIN query_trigram_counts t ON t.word=q.word
                GROUP BY q.word, c.word HAVING count(*) >= 2 AND count(*) / max(t.total) >= 0.5
            ), fuzzy_words AS MATERIALIZED (
                SELECT coalesce(array_agg(DISTINCT claim_word), '{}'::text[]) AS words FROM fuzzy_pairs
            ), fuzzy_frequency AS MATERIALIZED (
                SELECT claim_token.value AS token, count(*)::float8 AS df
                FROM eligible e CROSS JOIN fuzzy_words w CROSS JOIN LATERAL unnest(e.lexical_tokens) AS claim_token(value)
                WHERE e.lexical_tokens && w.words AND claim_token.value = ANY(w.words) GROUP BY claim_token.value
            ), claim_words AS MATERIALIZED (
                SELECT DISTINCT m.id, claim_token.value AS word
                FROM rerank_pool m CROSS JOIN fuzzy_words w CROSS JOIN LATERAL unnest(m.lexical_tokens) AS claim_token(value)
                WHERE m.lexical_tokens && w.words AND claim_token.value = ANY(w.words)
            ), fuzzy_weights AS (
                SELECT id, sum(weight) AS weight FROM (
                    SELECT w.id, p.query_word, max(p.similarity * ln(1 + (s.n - f.df + 0.5) / (f.df + 0.5))) AS weight
                    FROM claim_words w JOIN fuzzy_pairs p ON p.claim_word=w.word JOIN fuzzy_frequency f ON f.token=w.word
                    JOIN rerank_pool m ON m.id=w.id CROSS JOIN corpus_stats s
                    WHERE NOT m.lexical_tokens @> ARRAY[p.query_word]
                    GROUP BY w.id, p.query_word
                ) per_query_word GROUP BY id
            ), lexical_scores AS (
                SELECT m.id, round((m.score + coalesce(z.weight, 0)
                    * 2.2 / (1 + 1.2 * (0.25 + 0.75 * cardinality(m.lexical_tokens) / s.average_length)))::numeric, 9) AS score
                FROM rerank_pool m LEFT JOIN fuzzy_weights z ON z.id=m.id CROSS JOIN corpus_stats s
            ), lexical_candidates AS (
                SELECT id,row_number() OVER(ORDER BY score DESC,id) AS rank
                FROM lexical_scores ORDER BY score DESC,id LIMIT $5
            ), entity_hits AS MATERIALIZED (
                SELECT c.id, e.search_name FROM eligible c JOIN am_entities e ON e.claim_id=c.id
                WHERE e.search_name=ANY($6::text[])
            ), distinctive_entities AS (
                SELECT search_name FROM entity_hits GROUP BY search_name HAVING count(DISTINCT id)<=20
            ), entity_candidates AS (
                SELECT id,row_number() OVER(ORDER BY count(*) DESC,id) AS rank
                FROM entity_hits WHERE search_name IN (SELECT search_name FROM distinctive_entities)
                GROUP BY id ORDER BY count(*) DESC,id LIMIT $5
            ), arms AS (
                SELECT id,rank,'lexical'::text AS arm FROM lexical_candidates
                UNION ALL SELECT id,rank,'entity' FROM entity_candidates
            ), fused AS (
                SELECT id,sum(1.0/(60+rank)) AS score,array_agg(arm ORDER BY arm) AS arms
                FROM arms GROUP BY id ORDER BY score DESC,id LIMIT $5
            ) SELECT c.*,f.arms FROM fused f JOIN eligible c ON c.id=f.id ORDER BY f.score DESC,c.id"""
