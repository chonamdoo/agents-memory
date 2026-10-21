"""Embed texts with fastembed in its own environment (run by harness.py as a subprocess).

Usage: embed.py MODEL PREFIX INPUT_JSON OUTPUT_JSON
INPUT_JSON is a list of strings; OUTPUT_JSON receives L2-normalized rows (6 decimals) in input order.
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np
from fastembed import TextEmbedding


def main() -> None:
    model, prefix, source, target = sys.argv[1:5]
    texts = json.loads(open(source, encoding="utf-8").read())
    embedder = TextEmbedding(model, cache_dir=os.environ.get("FASTEMBED_CACHE_PATH"))
    started = time.perf_counter()
    rows = np.asarray(list(embedder.embed([prefix + text for text in texts], batch_size=32)), dtype=np.float32)
    elapsed = time.perf_counter() - started
    rows /= np.maximum(np.linalg.norm(rows, axis=1, keepdims=True), 1e-12)
    with open(target, "w", encoding="utf-8") as handle:
        json.dump([[round(float(value), 6) for value in row] for row in rows], handle)
    print(json.dumps({"rows": len(texts), "dimensions": int(rows.shape[1]),
                      "ms_per_text": round(elapsed * 1000 / max(len(texts), 1), 2)}))


if __name__ == "__main__":
    main()
