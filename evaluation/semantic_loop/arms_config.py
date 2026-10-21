"""Comparison arms measured by the semantic harness. The loop may edit this file.

kind: "lexical" (production ranking), "dense" (D), or "hybrid" (H).
expansions: an expansion-guidance version whose frozen per-query expansions are appended to the
lexical tokens (arm X / HX), or None.
"""
from __future__ import annotations

MODELS = {
    "intfloat/multilingual-e5-large": {"query_prefix": "query: ", "passage_prefix": "passage: "},
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2": {"query_prefix": "", "passage_prefix": ""},
    "minishlab/potion-multilingual-128M": {"query_prefix": "", "passage_prefix": ""},
}

ARMS = [
    {"name": "L0", "kind": "lexical", "expansions": None},
    {"name": "X-v0", "kind": "lexical", "expansions": "v0"},
    {"name": "X-v2", "kind": "lexical", "expansions": "v2"},
    {"name": "X-v3", "kind": "lexical", "expansions": "v3"},
    {"name": "X-v4", "kind": "lexical", "expansions": "v4"},
]
