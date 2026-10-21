"""Candidate ranking over the already-eligible claim set.

This is the only retrieval surface the offline ranking loop may edit
(research/autoresearch-eval-loop-proposal.ko.md). It runs after the `eligible`
CTE in `Store.search_lexical`, which owns every integrity filter and stays frozen.

Contract: the fragment continues a `WITH eligible AS (...)` query, may read only
`eligible`, `am_entities`, the parameters $2 (query tokens), $5 (limit) and
$6 (entity search names) and the read-only server_encoding setting, and must end
with a SELECT of `c.*` plus an `arms` text[] column from `eligible c`, ordered
best first, with at most $5 rows.
"""
from __future__ import annotations

# Lexical arm: Okapi BM25 over the eligible set (k1=1.2, b=0.75). Stored tokens are a set per claim,
# so tf is 1 and IDF plus length normalization separate claims sharing the same query tokens.
# A claim enters only by sharing a whole query token.
# Typo tolerance re-ranks the 200 best exact matches (an approximation: a claim ranked lower by exact
# evidence never receives typo evidence). A Hangul query word that occurs in no eligible claim may
# match a Hangul word of a pooled claim sharing at least two and at least half of its jamo trigrams;
# it then counts as that claim word, weighted by the similarity and by the word's IDF within the
# pool, each corrected word capped at the lowest IDF of the correctly spelled query tokens (several
# corrected words can together outweigh one exact token). It runs at query time, so stored tokens and every other tokenizer user are unchanged and no
# reindex is needed, and it is bounded: words of 2-10 syllables on both sides, the first 16 query
# words that are not bigrams cut from a longer query word, claim words within one syllable of a
# query word's length, at most 512 of those (most shared syllables first), and only on UTF8 servers
# where normalize() is available. The SQL text stays ASCII so servers with other encodings can
# still parse it. Text sets are grouped and sorted with the C collation: only equality matters, and
# locale collation is many times slower on Hangul.
# Entity arm: entities shared by more than 20 eligible claims (the default pool) cannot rank them and
# are ignored. Scores are rounded before ordering so equal evidence always falls back to the id order.
RANKING_SQL = """, query_tokens AS MATERIALIZED (
                SELECT DISTINCT token COLLATE "C" AS token FROM unnest($2::text[]) token
            ), corpus_stats AS MATERIALIZED (
                SELECT count(*)::float8 AS n, GREATEST(avg(cardinality(lexical_tokens)), 1)::float8 AS average_length FROM eligible
            ), word_matches AS MATERIALIZED (
                SELECT id, lexical_tokens, cardinality(lexical_tokens) AS length FROM eligible WHERE lexical_tokens && $2::text[]
            ), matched_tokens AS MATERIALIZED (
                SELECT m.id, claim_token.value COLLATE "C" AS token
                FROM word_matches m CROSS JOIN LATERAL unnest(m.lexical_tokens) AS claim_token(value)
                WHERE claim_token.value COLLATE "C" IN (SELECT token FROM query_tokens)
            ), token_frequency AS MATERIALIZED (
                SELECT token, count(*)::float8 AS df FROM matched_tokens GROUP BY token
            ), exact_scores AS MATERIALIZED (
                SELECT m.id, round((sum(ln(1 + (s.n - f.df + 0.5) / (f.df + 0.5)))
                    * 2.2 / (1 + 1.2 * (0.25 + 0.75 * m.length / s.average_length)))::numeric, 9) AS score
                FROM word_matches m JOIN matched_tokens t ON t.id=m.id JOIN token_frequency f ON f.token=t.token
                CROSS JOIN corpus_stats s GROUP BY m.id, m.length, s.average_length
            ), exact_floor AS MATERIALIZED (
                -- A corrected word never counts more than the least informative correctly spelled query token.
                SELECT min(ln(1 + (s.n - f.df + 0.5) / (f.df + 0.5))) AS idf FROM token_frequency f CROSS JOIN corpus_stats s
            ), rerank_pool AS MATERIALIZED (
                SELECT m.id, m.lexical_tokens, m.length, x.score FROM exact_scores x JOIN word_matches m ON m.id=x.id
                ORDER BY x.score DESC, x.id LIMIT 200
            ), query_hangul AS MATERIALIZED (
                SELECT token, min(ordinal) AS ordinal
                FROM (SELECT token COLLATE "C" AS token, ordinal FROM unnest($2::text[]) WITH ORDINALITY AS query(token, ordinal)) query
                WHERE token ~ '^[\\uAC00-\\uD7A3]{2,}$' AND current_setting('server_encoding')='UTF8' GROUP BY token
            ), query_fragments AS MATERIALIZED (
                -- The tokenizer cuts Hangul bigrams from longer words; those fragments are not query words.
                SELECT DISTINCT substr(token, position, 2) AS token
                FROM query_hangul CROSS JOIN LATERAL generate_series(1, length(token) - 1) position WHERE length(token) > 2
            ), query_words AS MATERIALIZED (
                SELECT token FROM query_hangul w
                WHERE length(token) <= 10 AND token NOT IN (SELECT token FROM query_fragments)
                AND NOT EXISTS(SELECT 1 FROM token_frequency f WHERE f.token=w.token)
                ORDER BY ordinal, token LIMIT 16
            ), query_trigrams AS MATERIALIZED (
                SELECT DISTINCT q.token AS word, substr(normalize(q.token, NFD), position, 3) AS trigram
                FROM query_words q CROSS JOIN LATERAL generate_series(1, length(normalize(q.token, NFD)) - 2) position
            ), query_trigram_counts AS MATERIALIZED (
                SELECT word, count(*)::float8 AS total FROM query_trigrams GROUP BY word
            ), query_syllables AS MATERIALIZED (
                SELECT DISTINCT substr(word, position, 1) AS syllable
                FROM query_trigram_counts CROSS JOIN LATERAL generate_series(1, length(word)) position
            ), query_lengths AS MATERIALIZED (
                SELECT DISTINCT length(token) + delta AS length FROM query_words CROSS JOIN generate_series(-1, 1) delta
            ), pool_tokens AS MATERIALIZED (
                SELECT m.id, claim_token.value COLLATE "C" AS word
                FROM rerank_pool m CROSS JOIN LATERAL unnest(m.lexical_tokens) AS claim_token(value)
                WHERE EXISTS(SELECT 1 FROM query_words) AND length(claim_token.value) IN (SELECT length FROM query_lengths)
            ), pool_words AS MATERIALIZED (
                SELECT DISTINCT word FROM pool_tokens WHERE word ~ '^[\\uAC00-\\uD7A3]{2,10}$'
            ), candidate_words AS MATERIALIZED (
                SELECT w.word FROM pool_words w CROSS JOIN LATERAL generate_series(1, length(w.word)) position
                JOIN query_syllables q ON q.syllable=substr(w.word, position, 1)
                WHERE w.word NOT IN (SELECT token FROM query_tokens)
                GROUP BY w.word ORDER BY count(*) DESC, w.word LIMIT 512
            ), claim_trigrams AS MATERIALIZED (
                SELECT DISTINCT w.word, substr(normalize(w.word, NFD), position, 3) AS trigram
                FROM candidate_words w CROSS JOIN LATERAL generate_series(1, length(normalize(w.word, NFD)) - 2) position
            ), fuzzy_pairs AS MATERIALIZED (
                SELECT q.word AS query_word, c.word AS claim_word, count(*) / max(t.total) AS similarity
                FROM query_trigrams q JOIN claim_trigrams c ON c.trigram=q.trigram JOIN query_trigram_counts t ON t.word=q.word
                GROUP BY q.word, c.word HAVING count(*) >= 2 AND count(*) / max(t.total) >= 0.5
            ), fuzzy_word_set AS MATERIALIZED (
                SELECT DISTINCT claim_word AS word FROM fuzzy_pairs
            ), claim_words AS MATERIALIZED (
                SELECT DISTINCT id, word FROM pool_tokens WHERE word IN (SELECT word FROM fuzzy_word_set)
            ), pool_stats AS MATERIALIZED (
                SELECT count(*)::float8 AS n FROM rerank_pool
            ), fuzzy_frequency AS MATERIALIZED (
                -- Typo evidence only re-ranks the pool, so its IDF is taken within the pool.
                SELECT word AS token, count(*)::float8 AS df FROM claim_words GROUP BY word
            ), fuzzy_weights AS (
                SELECT id, sum(weight) AS weight FROM (
                    SELECT w.id, p.query_word,
                        max(p.similarity * least(ln(1 + (s.n - f.df + 0.5) / (f.df + 0.5)), e.idf)) AS weight
                    FROM claim_words w JOIN fuzzy_pairs p ON p.claim_word=w.word JOIN fuzzy_frequency f ON f.token=w.word
                    JOIN rerank_pool m ON m.id=w.id CROSS JOIN pool_stats s CROSS JOIN exact_floor e
                    WHERE NOT m.lexical_tokens @> ARRAY[p.query_word::text]
                    GROUP BY w.id, p.query_word
                ) per_query_word GROUP BY id
            ), lexical_scores AS (
                SELECT m.id, round((m.score + coalesce(z.weight, 0)
                    * 2.2 / (1 + 1.2 * (0.25 + 0.75 * m.length / s.average_length)))::numeric, 9) AS score
                FROM rerank_pool m LEFT JOIN fuzzy_weights z ON z.id=m.id CROSS JOIN corpus_stats s
            ), lexical_candidates AS (
                SELECT id,row_number() OVER(ORDER BY score DESC,id) AS rank
                FROM lexical_scores ORDER BY score DESC,id LIMIT $5
            ), entity_hits AS MATERIALIZED (
                SELECT c.id, e.search_name COLLATE "C" AS search_name FROM eligible c JOIN am_entities e ON e.claim_id=c.id
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
