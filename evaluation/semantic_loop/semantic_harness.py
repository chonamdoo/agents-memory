"""Frozen harness for the semantic retrieval loop (rules: program.md).

Usage (PG_TEST_DSN optional; the retrieval-loop harness starts the CI-identical PostgreSQL):
  uv run python evaluation/semantic_loop/semantic_harness.py run [--arms L0,H-e5] [--label TEXT] [--record] [--baseline]
  uv run python evaluation/semantic_loop/semantic_harness.py baseline-holdouts
  uv run python evaluation/semantic_loop/semantic_harness.py promote --arm NAME --label TEXT
  uv run python evaluation/semantic_loop/semantic_harness.py freeze      # only before the first baseline

The loop may edit only arms_config.py and expansion_guidance.md (plus the frozen expansion files it
generates from that guidance). Embeddings run in a separate fastembed environment
(AM_LOOP_EMBED_PYTHON) and are cached by model and text digest. Holdouts print aggregates only.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import json
import os
import random
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "retrieval_loop"))

import harness as base  # noqa: E402  (the lexical loop's loader, reused for the cached schemas)
from arms import dense, hybrid, side_tables, slug  # noqa: E402
from corpus import SCALES, Corpus, Query  # noqa: E402
from semantic_corpus import SEMANTIC, SEMANTIC_GROUPS  # noqa: E402

import agents_memory.store as store_module  # noqa: E402
from agents_memory.lexical import tokens  # noqa: E402
from agents_memory.retrieval_ranking import RANKING_SQL as LEXICAL_SQL  # noqa: E402

EDITABLE = ("evaluation/semantic_loop/arms_config.py", "evaluation/semantic_loop/expansion_guidance.md")
FROZEN_FILES = sorted({
    *base.FROZEN_FILES, "src/agents_memory/retrieval_ranking.py",
    "evaluation/semantic_loop/semantic_harness.py", "evaluation/semantic_loop/semantic_corpus.py",
    "evaluation/semantic_loop/arms.py", "evaluation/semantic_loop/embed.py", "evaluation/semantic_loop/program.md",
    "tests/test_retrieval_integrity.py", "tests/test_retrieval_integrity_vector.py",
} - set(EDITABLE) - {"evaluation/retrieval_loop/program.md", "evaluation/retrieval_loop/harness.py"})
FROZEN = HERE / "frozen.json"
RESULTS = HERE / "results.tsv"
STATE = HERE / "state"
CACHE = HERE / ".cache"
KEYWORD_GROUPS = ("G1", "G2", "G3", "G4", "G5", "G6", "G7", "G9")
SCORED_SEMANTIC = tuple(group for group in SEMANTIC_GROUPS if group != "S8")
POLICY_HEADING = ("PT", "PI", "G6")
MAX_PROMOTIONS = 3


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_frozen() -> None:
    frozen = json.loads(FROZEN.read_text())
    changed = [name for name, digest in frozen["files"].items()
               if not (ROOT / name).exists() or _digest(ROOT / name) != digest]
    if changed or sorted(frozen["files"]) != FROZEN_FILES:
        raise SystemExit(f"FROZEN VIOLATION: changed={changed}")


def _config():
    return importlib.import_module("arms_config")


def _arms(names: list[str] | None) -> list[dict]:
    arms = _config().ARMS
    return [arm for arm in arms if names is None or arm["name"] in names]


def _corpus(split: str) -> Corpus:
    if split != "policy":
        return SEMANTIC[split]()
    corpus = base._split("policy")
    source = os.environ.get("AM_LOOP_POLICY_PARAPHRASES")
    if not source:
        raise SystemExit("AM_LOOP_POLICY_PARAPHRASES is required for the real-document holdout")
    for index, (key, text) in enumerate(sorted(json.loads(Path(source).read_text(encoding="utf-8")).items())):
        corpus.queries.append(Query(f"policy-PS-{index:03d}", "PS", "semantic", text, (key,)))
    return corpus


def _embed(model: str, texts: list[str], kind: str) -> tuple[list[list[float]], float]:
    prefix = _config().MODELS[model][f"{kind}_prefix"]
    key = hashlib.sha256(json.dumps([model, prefix, texts], ensure_ascii=False).encode()).hexdigest()[:24]
    target, meta = CACHE / f"embed-{key}.vectors.json", CACHE / f"embed-{key}.json"
    if not target.exists():
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
            json.dump(texts, handle, ensure_ascii=False)
        python = os.environ.get("AM_LOOP_EMBED_PYTHON", sys.executable)
        result = subprocess.run([python, str(HERE / "embed.py"), model, prefix, handle.name, str(target)],
                                capture_output=True, text=True, env=os.environ | {"HF_HUB_DISABLE_XET": "1"})
        os.unlink(handle.name)
        if result.returncode:
            raise SystemExit(f"embedding failed for {model}: {result.stderr[-800:]}")
        meta.write_text(result.stdout.strip().splitlines()[-1])
    return json.loads(target.read_text()), json.loads(meta.read_text())["ms_per_text"]


async def _ensure_vectors(store, model: str) -> None:
    name = slug(model)
    async with store.pool.acquire() as connection:
        claims = await connection.fetch("SELECT id, draft->>'statement' AS statement FROM am_claims WHERE draft IS NOT NULL ORDER BY id")
        present = await connection.fetchval(f"SELECT to_regclass('am_loop_vec_{name}') IS NOT NULL")
        if present and await connection.fetchval(f"SELECT count(*) FROM am_loop_vec_{name}") == len(claims):
            return
        vectors, _ = _embed(model, [row["statement"] for row in claims], "passage")
        await connection.execute(f"DROP TABLE IF EXISTS am_loop_vec_{name}; DROP TABLE IF EXISTS am_loop_query_{name};"
                                 + side_tables(model, len(vectors[0])))
        await connection.executemany(f"INSERT INTO am_loop_vec_{name} VALUES($1,$2::text::public.vector)",
                                     [(row["id"], json.dumps(vector)) for row, vector in zip(claims, vectors)])


def _expansions(version: str | None, split: str) -> dict[str, list[str]]:
    if version is None:
        return {}
    path = HERE / "expansions" / f"{version}-{split}.json"
    if not path.exists():
        raise SystemExit(f"missing frozen expansions {path.relative_to(ROOT)}")
    return json.loads(path.read_text(encoding="utf-8"))


def _fragment(arm: dict) -> str:
    if arm["kind"] == "lexical":
        return LEXICAL_SQL
    if arm["kind"] == "dense":
        return dense(arm["model"])
    return hybrid(arm["model"], arm.get("dense_weight", 1.0), arm.get("k", 60))


async def _measure(split: str, scale: int | None, corpus: Corpus, arms: list[dict]) -> dict:
    store, actor, binding, ids = await base._open(split, scale, corpus)
    out = {}
    try:
        for arm in arms:
            model = arm.get("model")
            query_vectors, embed_ms = None, None
            if model:
                await _ensure_vectors(store, model)
                query_vectors, embed_ms = _embed(model, [query.text for query in corpus.queries], "query")
            expansions = _expansions(arm.get("expansions"), split)
            decoys = {ids[c.key] for c in corpus.claims if c.key.startswith("decoy")}
            store_module.RANKING_SQL = _fragment(arm)
            rows = []
            for index, query in enumerate(corpus.queries):
                if model:
                    async with store.pool.acquire() as connection:
                        await connection.execute(
                            f"INSERT INTO am_loop_query_{slug(model)}(singleton, embedding) VALUES(true,$1::text::public.vector)"
                            " ON CONFLICT(singleton) DO UPDATE SET embedding=EXCLUDED.embedding",
                            json.dumps(query_vectors[index]))
                terms = tokens(" ".join((query.text, *query.expansions, *expansions.get(query.id, ()))))
                started = time.perf_counter()
                found, _ = await store.search_lexical(actor, binding, terms[:2048], None, 20,
                                                      request_digest=hashlib.sha256(uuid.uuid4().bytes).hexdigest())
                elapsed = time.perf_counter() - started
                ranked = [claim.id for claim, _ in found]
                gold = {ids[key] for key in query.gold}
                ranks = [ranked.index(item) + 1 for item in gold if item in ranked]
                rows.append({"query": query.id, "group": query.group, "gold": len(gold), "hits": len(ranks),
                             "first": min(ranks) if ranks else None, "returned": len(ranked),
                             "decoys_top5": sum(item in decoys for item in ranked[:5]), "seconds": elapsed})
            out[arm["name"]] = {"rows": rows, "embed_ms_per_query": embed_ms}
    finally:
        store_module.RANKING_SQL = LEXICAL_SQL
        await store.close()
    return out


def _set_summary(rows: list[dict], groups) -> dict:
    items = [row for row in rows if row["group"] in groups and row["gold"]]
    return {"hits": sum(row["hits"] for row in items), "gold": sum(row["gold"] for row in items),
            "recall": round(statistics.fmean(row["hits"] / row["gold"] for row in items), 4) if items else None,
            "mrr": round(statistics.fmean(1 / row["first"] if row["first"] else 0 for row in items), 4) if items else None}


def evaluate(split: str, arms: list[dict]) -> dict:
    corpus = _corpus(split)
    scales = SCALES if split != "policy" else (None,)
    result = {"split": split, "arms": {arm["name"]: {"report": {}, "per_query": {}} for arm in arms}}
    for scale in scales:
        label = f"x{scale}" if scale else "x1"
        measured = asyncio.run(_measure(split, scale, corpus, arms))
        for name, data in measured.items():
            rows = data["rows"]
            summary = base._summary(rows)
            summary["SEMANTIC"] = _set_summary(rows, SCORED_SEMANTIC)
            summary["KEYWORD"] = _set_summary(rows, KEYWORD_GROUPS)
            summary["POLICY_HEADING"] = _set_summary(rows, POLICY_HEADING)
            summary["POLICY_PARAPHRASE"] = _set_summary(rows, ("PS",))
            summary["embed_ms_per_query"] = data["embed_ms_per_query"]
            result["arms"][name]["report"][label] = summary
            result["arms"][name]["per_query"][label] = rows
    return result


def integrity_gate(python: str = sys.executable) -> bool:
    result = subprocess.run([python, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                             "tests/test_retrieval_integrity.py", "tests/test_retrieval_integrity_vector.py"],
                            cwd=ROOT, capture_output=True, text=True)
    print("integrity:", result.stdout.strip().splitlines()[-1] if result.stdout.strip() else result.stderr[-400:])
    return result.returncode == 0


def keep_decision(candidate: dict, baseline: dict) -> list[str]:
    """program.md keep rule against the stored L0 dev baseline; empty list means keep."""
    reasons = []
    gained = sum(candidate[s]["SEMANTIC"]["hits"] - baseline[s]["SEMANTIC"]["hits"] for s in baseline)
    if gained < 3:
        reasons.append(f"semantic hits {gained:+d} (< +3)")
    for scale, summary in baseline.items():
        for group in KEYWORD_GROUPS:
            if group in summary and candidate[scale][group]["hits"] <= summary[group]["hits"] - 2:
                reasons.append(f"{scale} {group} hits {summary[group]['hits']}->{candidate[scale][group]['hits']}")
        for name in ("SEMANTIC", "KEYWORD"):
            if candidate[scale][name]["mrr"] < summary[name]["mrr"] - 0.02:
                reasons.append(f"{scale} {name} MRR {summary[name]['mrr']}->{candidate[scale][name]['mrr']}")
    if candidate["x20"]["ALL"]["p95_ms"] > baseline["x20"]["ALL"]["p95_ms"] * 1.25:
        reasons.append(f"x20 p95 {baseline['x20']['ALL']['p95_ms']}->{candidate['x20']['ALL']['p95_ms']}ms")
    return reasons


def _commit() -> str:
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def _editable_digest() -> str:
    parts = [_digest(ROOT / name) for name in EDITABLE if (ROOT / name).exists()]
    parts += [_digest(path) for path in sorted((HERE / "expansions").glob("*.json"))]
    return hashlib.sha256("".join(parts).encode()).hexdigest()[:12]


def record(split: str, arm: str, report: dict, label: str, status: str, gate: bool | None) -> None:
    if not RESULTS.exists():
        RESULTS.write_text("time\tcommit\teditable\tsplit\tarm\tlabel\tstatus\tintegrity\t"
                           "sem_x1\tsem_x5\tsem_x20\tsem_gold\tkw_x1\tkw_x5\tkw_x20\tsem_mrr_x5\tkw_mrr_x5\t"
                           "S8_returned_x5\tp95_x20\tembed_ms_q\n")
    get = lambda scale, name, key: report.get(scale, {}).get(name, {}).get(key, "")  # noqa: E731
    line = [time.strftime("%Y-%m-%dT%H:%M:%S"), _commit(), _editable_digest(), split, arm, label, status,
            "" if gate is None else ("pass" if gate else "FAIL"),
            get("x1", "SEMANTIC", "hits"), get("x5", "SEMANTIC", "hits"), get("x20", "SEMANTIC", "hits"),
            get("x1", "SEMANTIC", "gold"), get("x1", "KEYWORD", "hits"), get("x5", "KEYWORD", "hits"),
            get("x20", "KEYWORD", "hits"), get("x5", "SEMANTIC", "mrr"), get("x5", "KEYWORD", "mrr"),
            report.get("x5", {}).get("S8", {}).get("returned", ""),
            report.get("x20", report.get("x1", {})).get("ALL", {}).get("p95_ms", ""),
            report.get("x1", {}).get("embed_ms_per_query", "")]
    with RESULTS.open("a") as handle:
        handle.write("\t".join(map(str, line)) + "\n")


def _paired_bootstrap(old: dict, new: dict, groups, seed: int = 20261021) -> tuple[float, float, float]:
    deltas: dict[str, float] = {}
    for scale in old:
        before = {row["query"]: row for row in old[scale] if row["gold"] and row["group"] in groups}
        after = {row["query"]: row for row in new[scale] if row["gold"] and row["group"] in groups}
        for query, row in before.items():
            deltas[query] = deltas.get(query, 0.0) + (after[query]["hits"] - row["hits"]) / row["gold"]
    values = list(deltas.values())
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choices(values, k=len(values))) for _ in range(10000))
    return statistics.fmean(values), means[249], means[9750]


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--arms")
    run.add_argument("--label", default="")
    run.add_argument("--record", action="store_true")
    run.add_argument("--baseline", action="store_true", help="store the L0 dev result as the keep baseline")
    run.add_argument("--details", action="store_true")
    promote = sub.add_parser("promote")
    promote.add_argument("--arm", required=True)
    promote.add_argument("--label", required=True)
    sub.add_parser("baseline-holdouts")
    sub.add_parser("freeze")
    args = parser.parse_args()
    CACHE.mkdir(exist_ok=True)
    STATE.mkdir(exist_ok=True)

    if args.command == "freeze":
        FROZEN.write_text(json.dumps({"files": {name: _digest(ROOT / name) for name in FROZEN_FILES},
                                      "editable": list(EDITABLE)}, indent=1) + "\n")
        print(f"froze {len(FROZEN_FILES)} files")
        return
    check_frozen()
    base.ensure_postgres()

    if args.command == "run":
        arms = _arms(args.arms.split(",") if args.arms else None)
        result = evaluate("dev", arms)
        gate = integrity_gate()
        baseline_path = STATE / "baseline-dev.json"
        for arm in arms:
            report = result["arms"][arm["name"]]["report"]
            status = "measured"
            if args.baseline and arm["name"] == "L0":
                baseline_path.write_text(json.dumps(result["arms"]["L0"]))
                status = "baseline"
            elif baseline_path.exists() and arm["name"] != "L0":
                reasons = keep_decision(report, json.loads(baseline_path.read_text())["report"])
                if not gate:
                    reasons.append("integrity gate failed")
                status = "keep" if not reasons else "discard: " + "; ".join(reasons)
            print(arm["name"], json.dumps({scale: {k: v for k, v in summary.items()
                                                   if k in ("SEMANTIC", "KEYWORD", "ALL", "S8", "embed_ms_per_query")}
                                           for scale, summary in report.items()}, ensure_ascii=False))
            print(arm["name"], "status:", status)
            if args.record:
                record("dev", arm["name"], report, args.label, status, gate)
        if args.details:
            (CACHE / "dev-details.json").write_text(json.dumps(
                {name: data["per_query"] for name, data in result["arms"].items()}, ensure_ascii=False))
        return

    if args.command == "baseline-holdouts":
        arm = [a for a in _arms(None) if a["name"] == "L0"]
        for split in ("holdout", "policy"):
            path = STATE / f"baseline-{split}.json"
            if path.exists():
                raise SystemExit(f"{split} baseline already recorded; holdout baselines are taken once")
            result = evaluate(split, arm)["arms"]["L0"]
            path.write_text(json.dumps(result))
            print(split, json.dumps({scale: {k: summary[k] for k in ("ALL", "SEMANTIC", "KEYWORD",
                                                                      "POLICY_HEADING", "POLICY_PARAPHRASE")}
                                     for scale, summary in result["report"].items()}, ensure_ascii=False))
            record(split, "L0", result["report"], "baseline", "holdout-baseline", None)
        return

    if args.command == "promote":
        attempts_path = STATE / "promotions.json"
        attempts = json.loads(attempts_path.read_text()) if attempts_path.exists() else []
        if len(attempts) >= MAX_PROMOTIONS:
            raise SystemExit("promotion budget exhausted (3 attempts)")
        arm = _arms([args.arm])
        python = os.environ.get("AM_LOOP_CI_PYTHON", sys.executable)
        gate = integrity_gate(python) and base.related_tests()
        verdicts = {}
        for split in ("holdout", "policy"):
            baseline = json.loads((STATE / f"baseline-{split}.json").read_text())
            result = evaluate(split, arm)["arms"][args.arm]
            groups = SCORED_SEMANTIC if split == "holdout" else ("PS",)
            mean, low, high = _paired_bootstrap(baseline["per_query"], result["per_query"], groups)
            checks = {}
            for scale, summary in result["report"].items():
                old = baseline["report"][scale]
                keyword = KEYWORD_GROUPS if split == "holdout" else POLICY_HEADING
                checks[scale] = {
                    "keyword_group_drops": [g for g in keyword if g in old and summary[g]["hits"] < old[g]["hits"]],
                    "keyword_mrr_drop": round(old["KEYWORD" if split == "holdout" else "POLICY_HEADING"]["mrr"]
                                              - summary["KEYWORD" if split == "holdout" else "POLICY_HEADING"]["mrr"], 4),
                }
            verdicts[split] = {"semantic_delta_mean": round(mean, 4), "ci95": [round(low, 4), round(high, 4)],
                               "checks": checks}
            record(split, args.arm, result["report"], args.label, "promotion-eval", gate)
        holdout, real = verdicts["holdout"], verdicts["policy"]
        passed = (gate and holdout["ci95"][0] > 0
                  and all(not c["keyword_group_drops"] and c["keyword_mrr_drop"] <= 0.02 for c in holdout["checks"].values())
                  and all(not c["keyword_group_drops"] and c["keyword_mrr_drop"] <= 0.02 for c in real["checks"].values())
                  and real["semantic_delta_mean"] > 0)
        attempts.append({"arm": args.arm, "label": args.label, "commit": _commit(), "passed": passed, "verdicts": verdicts})
        attempts_path.write_text(json.dumps(attempts, ensure_ascii=False, indent=1))
        print(json.dumps(verdicts, ensure_ascii=False, indent=1))
        print("PROMOTED" if passed else "NOT PROMOTED", f"(attempt {len(attempts)}/{MAX_PROMOTIONS})")


if __name__ == "__main__":
    main()
