"""Frozen harness for the expansion-weighting loop (rules: program.md).

Usage (the retrieval-loop harness starts the CI-identical PostgreSQL when PG_TEST_DSN is unset):
  uv run python evaluation/weighting_loop/weighting_harness.py neutral        # before the first candidate
  uv run python evaluation/weighting_loop/weighting_harness.py run [--label TEXT] [--record] [--repeats 3]
  uv run python evaluation/weighting_loop/weighting_harness.py promote --label TEXT
  uv run python evaluation/weighting_loop/weighting_harness.py freeze         # only before the first candidate

The loop may edit only src/agents_memory/retrieval_ranking.py. Every arm searches with the caller's
own query tokens apart from the expansion tokens, as Application.context does. Baselines are the
semantic loop's stored L0 results (original ranking, no expansions). Holdouts print aggregates only.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SEMANTIC_DIR = ROOT / "evaluation" / "semantic_loop"
sys.path.insert(0, str(SEMANTIC_DIR))
sys.path.insert(0, str(ROOT / "evaluation" / "retrieval_loop"))

import harness as base  # noqa: E402  (cached schemas, PostgreSQL, related tests)
import semantic_harness as sem  # noqa: E402  (corpora, summaries, keep rule, bootstrap)
from corpus import SCALES  # noqa: E402

from agents_memory.lexical import tokens  # noqa: E402

EDITABLE = ("src/agents_memory/retrieval_ranking.py",)
EXPANSION_SETS = {"X2c": "v2", "X4c": "v4"}
ARMS = ("L0c", *EXPANSION_SETS)
INTEGRITY_TESTS = ("tests/test_retrieval_integrity.py", "tests/test_retrieval_integrity_vector.py",
                   "tests/test_retrieval_expansion_weight.py")
FROZEN_FILES = sorted({
    *sem.FROZEN_FILES, *INTEGRITY_TESTS,
    "evaluation/weighting_loop/weighting_harness.py", "evaluation/weighting_loop/program.md",
    "evaluation/semantic_loop/semantic_harness.py", "evaluation/semantic_loop/state/baseline-dev.json",
    "evaluation/semantic_loop/state/baseline-holdout.json", "evaluation/semantic_loop/state/baseline-policy.json",
    *(f"evaluation/semantic_loop/expansions/{version}-{split}.json"
      for version in EXPANSION_SETS.values() for split in ("dev", "holdout")),
} - set(EDITABLE))
FROZEN = HERE / "frozen.json"
RESULTS = HERE / "results.tsv"
STATE = HERE / "state"
MAX_PROMOTIONS = 3


def check_frozen() -> None:
    frozen = json.loads(FROZEN.read_text())
    changed = [name for name, digest in frozen["files"].items()
               if not (ROOT / name).exists() or sem._digest(ROOT / name) != digest]
    if changed or sorted(frozen["files"]) != FROZEN_FILES:
        raise SystemExit(f"FROZEN VIOLATION: changed={changed}")


def _expansions(arm: str, split: str) -> dict[str, list[str]]:
    if arm not in EXPANSION_SETS:
        return {}
    version = EXPANSION_SETS[arm]
    if split == "policy":
        folder = os.environ.get("AM_LOOP_POLICY_EXPANSIONS")
        if not folder:
            raise SystemExit("AM_LOOP_POLICY_EXPANSIONS is required for the real-document holdout")
        path = Path(folder) / f"{version}-policy.json"
    else:
        path = SEMANTIC_DIR / "expansions" / f"{version}-{split}.json"
    if not path.exists():
        raise SystemExit(f"missing frozen expansions for {arm} on {split}")
    return json.loads(path.read_text(encoding="utf-8"))


async def _measure(split: str, scale: int | None, corpus, arms) -> dict:
    store, actor, binding, ids = await base._open(split, scale, corpus)
    decoys = {ids[c.key] for c in corpus.claims if c.key.startswith("decoy")}
    out = {}
    try:
        for arm in arms:
            expansions = _expansions(arm, split)
            rows = []
            for query in corpus.queries:
                terms = tokens(" ".join((query.text, *query.expansions, *expansions.get(query.id, ()))))[:2048]
                searched = set(terms)
                started = time.perf_counter()
                found, _ = await store.search_lexical(
                    actor, binding, terms, None, 20, request_digest=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
                    query_tokens=[term for term in tokens(query.text) if term in searched])
                elapsed = time.perf_counter() - started
                ranked = [claim.id for claim, _ in found]
                gold = {ids[key] for key in query.gold}
                ranks = [ranked.index(item) + 1 for item in gold if item in ranked]
                rows.append({"query": query.id, "group": query.group, "gold": len(gold), "hits": len(ranks),
                             "first": min(ranks) if ranks else None, "returned": len(ranked),
                             "decoys_top5": sum(item in decoys for item in ranked[:5]), "seconds": elapsed})
            out[arm] = rows
    finally:
        await store.close()
    return out


def evaluate(split: str, arms=ARMS) -> dict:
    corpus = sem._corpus(split)
    result = {arm: {"report": {}, "per_query": {}} for arm in arms}
    for scale in (SCALES if split != "policy" else (None,)):
        label = f"x{scale}" if scale else "x1"
        for arm, rows in asyncio.run(_measure(split, scale, corpus, arms)).items():
            summary = base._summary(rows)
            summary["SEMANTIC"] = sem._set_summary(rows, sem.SCORED_SEMANTIC)
            summary["KEYWORD"] = sem._set_summary(rows, sem.KEYWORD_GROUPS)
            summary["POLICY_HEADING"] = sem._set_summary(rows, sem.POLICY_HEADING)
            summary["POLICY_PARAPHRASE"] = sem._set_summary(rows, ("PS",))
            result[arm]["report"][label] = summary
            result[arm]["per_query"][label] = rows
    return result


def integrity_gate(python: str = sys.executable) -> bool:
    result = subprocess.run([python, "-m", "pytest", "-q", "-p", "no:cacheprovider", *INTEGRITY_TESTS],
                            cwd=ROOT, capture_output=True, text=True)
    print("integrity:", result.stdout.strip().splitlines()[-1] if result.stdout.strip() else result.stderr[-400:])
    return result.returncode == 0


def keep_reasons(arm: str, candidate: dict, baseline: dict) -> list[str]:
    reasons = sem.keep_decision(candidate, baseline)
    if arm == "L0c":
        reasons = [reason for reason in reasons if not reason.startswith("semantic hits")]
    return [f"{arm}: {reason}" for reason in reasons]


def _editable_digest() -> str:
    return hashlib.sha256("".join(sem._digest(ROOT / name) for name in EDITABLE).encode()).hexdigest()[:12]


def record(split: str, arm: str, report: dict, label: str, status: str, gate: bool | None) -> None:
    if not RESULTS.exists():
        RESULTS.write_text("time\tcommit\teditable\tsplit\tarm\tlabel\tstatus\tintegrity\t"
                           "sem_x1\tsem_x5\tsem_x20\tsem_gold\tkw_x1\tkw_x5\tkw_x20\t"
                           "sem_mrr_x1\tsem_mrr_x5\tsem_mrr_x20\tkw_mrr_x1\tkw_mrr_x5\tkw_mrr_x20\tp95_x20\n")
    get = lambda scale, name, key: report.get(scale, {}).get(name, {}).get(key, "")  # noqa: E731
    line = [time.strftime("%Y-%m-%dT%H:%M:%S"), sem._commit(), _editable_digest(), split, arm, label, status,
            "" if gate is None else ("pass" if gate else "FAIL"),
            *(get(s, "SEMANTIC", "hits") for s in ("x1", "x5", "x20")), get("x1", "SEMANTIC", "gold"),
            *(get(s, "KEYWORD", "hits") for s in ("x1", "x5", "x20")),
            *(get(s, "SEMANTIC", "mrr") for s in ("x1", "x5", "x20")),
            *(get(s, "KEYWORD", "mrr") for s in ("x1", "x5", "x20")),
            report.get("x20", report.get("x1", {})).get("ALL", {}).get("p95_ms", "")]
    with RESULTS.open("a") as handle:
        handle.write("\t".join(map(str, line)) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--label", default="")
    run.add_argument("--record", action="store_true")
    run.add_argument("--repeats", type=int, default=3)
    promote = sub.add_parser("promote")
    promote.add_argument("--label", required=True)
    sub.add_parser("neutral")
    sub.add_parser("freeze")
    args = parser.parse_args()
    STATE.mkdir(exist_ok=True)
    if args.command == "freeze":
        FROZEN.write_text(json.dumps({"files": {name: sem._digest(ROOT / name) for name in FROZEN_FILES},
                                      "editable": list(EDITABLE)}, indent=1) + "\n")
        print(f"froze {len(FROZEN_FILES)} files")
        return
    check_frozen()
    base.ensure_postgres()
    baseline_dev = json.loads((SEMANTIC_DIR / "state" / "baseline-dev.json").read_text())

    if args.command == "neutral":
        # The plumbing must not move any result: L0c under the original ranking equals the stored L0.
        result = evaluate("dev", ("L0c",))["L0c"]["per_query"]
        fields = ("query", "hits", "first", "returned", "decoys_top5")
        differing = [(scale, old["query"]) for scale in baseline_dev["per_query"]
                     for old, new in zip(baseline_dev["per_query"][scale], result[scale], strict=True)
                     if any(old[field] != new[field] for field in fields)]
        print("neutral:", "identical" if not differing else f"{len(differing)} rows differ: {differing[:5]}")
        return

    if args.command == "run":
        gate = integrity_gate()
        reports = {arm: [] for arm in ARMS}
        for _ in range(max(1, args.repeats)):
            for arm, data in evaluate("dev").items():
                reports[arm].append(data["report"])
        reasons = [] if gate else ["integrity gate failed"]
        for arm, runs in reports.items():
            for report in runs:
                for reason in keep_reasons(arm, report, baseline_dev["report"]):
                    if reason not in reasons:
                        reasons.append(reason)
        status = "keep" if not reasons else "discard: " + "; ".join(reasons)
        for arm, runs in reports.items():
            report = runs[0]
            print(arm, json.dumps({scale: {name: report[scale][name] for name in ("SEMANTIC", "KEYWORD")}
                                   | {"p95_ms": [run[scale]["ALL"]["p95_ms"] for run in runs]}
                                   for scale in report}, ensure_ascii=False))
            if args.record:
                record("dev", arm, report, args.label, status, gate)
        print("status:", status)
        return

    if args.command == "promote":
        attempts_path = STATE / "promotions.json"
        attempts = json.loads(attempts_path.read_text()) if attempts_path.exists() else []
        if len(attempts) >= MAX_PROMOTIONS:
            raise SystemExit("promotion budget exhausted (3 attempts)")
        python = os.environ.get("AM_LOOP_CI_PYTHON", sys.executable)
        gate = integrity_gate(python) and base.related_tests()
        verdicts = {}
        passed = gate
        for split in ("holdout", "policy"):
            baseline = json.loads((SEMANTIC_DIR / "state" / f"baseline-{split}.json").read_text())
            keyword_set = "KEYWORD" if split == "holdout" else "POLICY_HEADING"
            keyword_groups = sem.KEYWORD_GROUPS if split == "holdout" else sem.POLICY_HEADING
            semantic_groups = sem.SCORED_SEMANTIC if split == "holdout" else ("PS",)
            for arm, data in evaluate(split).items():
                checks = {}
                for scale, summary in data["report"].items():
                    old = baseline["report"][scale]
                    checks[scale] = {
                        "keyword_group_drops": [g for g in keyword_groups if g in old and summary[g]["hits"] < old[g]["hits"]],
                        "keyword_mrr_drop": round(old[keyword_set]["mrr"] - summary[keyword_set]["mrr"], 4),
                    }
                keyword_ok = all(not c["keyword_group_drops"] and c["keyword_mrr_drop"] <= 0.02 for c in checks.values())
                verdict = {"checks": checks, "keyword_ok": keyword_ok}
                if arm != "L0c":
                    mean, low, high = sem._paired_bootstrap(baseline["per_query"], data["per_query"], semantic_groups)
                    verdict |= {"semantic_delta_mean": round(mean, 4), "ci95": [round(low, 4), round(high, 4)]}
                    semantic_ok = low > 0 if split == "holdout" else mean > 0
                    passed = passed and semantic_ok
                passed = passed and keyword_ok
                verdicts[f"{split}/{arm}"] = verdict
                record(split, arm, data["report"], args.label, "promotion-eval", gate)
        attempts.append({"label": args.label, "commit": sem._commit(), "editable": _editable_digest(),
                         "passed": passed, "verdicts": verdicts})
        attempts_path.write_text(json.dumps(attempts, ensure_ascii=False, indent=1))
        print(json.dumps(verdicts, ensure_ascii=False, indent=1))
        print("PROMOTED" if passed else "NOT PROMOTED", f"(attempt {len(attempts)}/{MAX_PROMOTIONS})")


if __name__ == "__main__":
    main()
