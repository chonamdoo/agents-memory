"""Frozen evaluation harness for the candidate-ranking loop.

Usage (PG_TEST_DSN points at an isolated PostgreSQL 18 + pgvector database):
  uv run python evaluation/retrieval_loop/harness.py run --split dev [--label TEXT] [--record]
  uv run python evaluation/retrieval_loop/harness.py promote --label TEXT
  uv run python evaluation/retrieval_loop/harness.py freeze      # only before the loop starts

The loop may edit only src/agents_memory/retrieval_ranking.py and src/agents_memory/lexical.py.
Every other file named in frozen.json must keep its digest or the harness refuses to run.
Holdout and the real-document holdout print aggregates only.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import random
import statistics
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

import asyncpg  # noqa: E402
from corpus import CORPORA, SCALES, Claim, Corpus  # noqa: E402
from policy_corpus import policy  # noqa: E402

from agents_memory.config import Settings  # noqa: E402
from agents_memory.domain import CaptureCommand  # noqa: E402
from agents_memory.journal import DeletionJournal  # noqa: E402
from agents_memory.lexical import tokens  # noqa: E402
from agents_memory.migrations import MIGRATION, migrate  # noqa: E402
from agents_memory.selection import SourceSelectionCommand  # noqa: E402
from agents_memory.semantic_contract import GeneratedExtraction  # noqa: E402
from agents_memory.store import Store  # noqa: E402

EDITABLE = ("src/agents_memory/retrieval_ranking.py", "src/agents_memory/lexical.py")
FROZEN_FILES = sorted({
    *(p.relative_to(ROOT).as_posix() for p in (ROOT / "src/agents_memory").rglob("*.py")),
    "evaluation/retrieval_loop/corpus.py", "evaluation/retrieval_loop/policy_corpus.py",
    "evaluation/retrieval_loop/harness.py", "evaluation/retrieval_loop/program.md",
    "tests/test_retrieval_integrity.py",
} - set(EDITABLE))
FROZEN = HERE / "frozen.json"
RESULTS = HERE / "results.tsv"
CACHE = HERE / ".cache"
STATE = HERE / "state"
PG_IMAGE = "mirror.gcr.io/pgvector/pgvector@sha256:ad249f9fb9572979643a47694e59b9a8cdcdf6abc6accebf49bb80ad5f20ff9b"
LOCAL_DSN = "postgresql://postgres:loop@127.0.0.1:55432/agents_memory"
TOKEN = "retrieval-loop-isolated-operator-" + "a" * 32
SCORED = ("G1", "G2", "G3", "G4", "G5", "G6", "G7", "G9")
MAX_PROMOTIONS = 3


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_frozen() -> dict:
    frozen = json.loads(FROZEN.read_text())
    changed = [name for name, digest in frozen["files"].items()
               if not (ROOT / name).exists() or _digest(ROOT / name) != digest]
    added = sorted(set(FROZEN_FILES) - set(frozen["files"]))
    if changed or added:
        raise SystemExit(f"FROZEN VIOLATION: changed={changed} added={added}")
    return frozen


def _split(name: str) -> Corpus:
    if name == "policy":
        corpus = policy()
        if corpus is None:
            raise SystemExit("AM_LOOP_POLICY_DIR is required for the real-document holdout")
        return corpus
    return CORPORA[name]()


def _schema_key(split: str, scale: int | None, corpus: Corpus) -> str:
    material = json.dumps([split, scale, MIGRATION,
                           [c.__dict__ for c in (corpus.at_scale(scale) if scale else corpus.claims)]],
                          ensure_ascii=False, default=list)
    return hashlib.sha256(material.encode()).hexdigest()[:20]


def _dsn(schema: str | None) -> str:
    raw = os.environ["PG_TEST_DSN"]
    parts = urlsplit(raw)
    query = dict(parse_qsl(parts.query))
    query.pop("schema", None)
    if schema:
        query["schema"] = schema
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


async def _publish(store: Store, actor, binding: str, claim: Claim) -> str:
    operation = await store.capture(actor, CaptureCommand(binding_id=binding, idempotency_key=claim.key,
                                                          origin_key=claim.key, body=claim.body, speaker="human"))
    window = await store.inspect(actor, binding, operation.source_id, None)
    spans = window["span_inventory"]
    extraction = GeneratedExtraction(claims=({
        "assertion_id": "a0000", "assertion_span_id": spans[0]["span_id"], "statement": spans[0]["quote"],
        "kind": "fact", "subject": claim.subject, "predicate": claim.predicate, "object": claim.object,
        "polarity": "positive", "modality": "asserted", "entities": claim.entities,
    },), individual_qualifications=(), shared_qualifications=(), validities=(),
        unused_span_ids=tuple(span["span_id"] for span in spans[1:]))
    rejections = [item["id"] for item in window["judgment_context"]["rejections"]]
    selected = await store.record(actor, SourceSelectionCommand(
        kind="source_selection", binding_id=binding, idempotency_key=claim.key + "-select",
        admission_id=window["admission_id"], source_id=operation.source_id, source_revision=window["source_revision"],
        binding_revision=window["binding_revision"], byte_start=window["byte_start"], byte_end=window["byte_end"],
        window_digest=window["window_digest"], policy_revision=window["policy_revision"],
        policy_epoch=window["policy_epoch"], label="remember", coverage="complete_window", extraction=extraction,
        reason="Synthetic evaluation corpus fact.",
        rejection_comparisons=tuple({"rejection_id": item, "decision": "unrelated",
                                     "reason": "Evaluation corpus facts are independent."} for item in rejections)))
    inspected = await store.inspect(actor, binding, selected.artifact_id, None)
    return inspected["claim_ids"][0]


async def _reindex(store: Store) -> None:
    """Recompute stored lexical tokens with the current tokenizer, as a reindex migration would.

    Mirrors the token input of Store._record_selection: statement, subject, predicate, object, entities.
    """
    async with store.pool.acquire() as connection:
        async with connection.transaction():
            for row in await connection.fetch("SELECT id,draft FROM am_claims WHERE draft IS NOT NULL"):
                draft = json.loads(row["draft"]) if isinstance(row["draft"], str) else row["draft"]
                text = " ".join((draft["statement"], draft["subject"], draft["predicate"], draft["object"],
                                 *draft.get("entities", ())))
                await connection.execute("UPDATE am_claims SET lexical_tokens=$2 WHERE id=$1", row["id"], tokens(text))


async def _open(split: str, scale: int | None, corpus: Corpus):
    """Load (or reuse) one isolated schema; ranking-only edits reuse the cached load."""
    key = _schema_key(split, scale, corpus)
    schema = f"am_loop_{split}_{scale or 0}_{key}"
    meta = CACHE / f"{schema}.json"
    admin = await asyncpg.connect(_dsn(None))
    try:
        exists = await admin.fetchval("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=$1)", schema)
        if exists and not meta.exists():
            await admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
            exists = False
        if not exists:
            await admin.execute(f'CREATE SCHEMA "{schema}"')
    finally:
        await admin.close()
    state = CACHE / schema
    settings = Settings(deployment_id="retrieval_loop", realm="retrieval_loop", mode="personal",
                        database_dsn=_dsn(schema), state_dir=state / "state", journal_dir=state / "journal")
    if not meta.exists():
        state.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(migrate, _dsn(schema))
        store = Store(settings, DeletionJournal(settings.journal_dir, settings.deployment_id))
        await store.open()
        actor = await store.bootstrap(TOKEN, "loop_owner")
        binding = (await store.register_binding(actor, f"Loop {split}", None, "loop-binding")).id
        actor = await store.authenticate(TOKEN)
        ids = {}
        started = time.monotonic()
        for claim in corpus.at_scale(scale) if scale else corpus.claims:
            ids[claim.key] = await _publish(store, actor, binding, claim)
        meta.write_text(json.dumps({"binding": binding, "ids": ids, "load_seconds": time.monotonic() - started,
                                    "lexical": _digest(ROOT / "src/agents_memory/lexical.py")}))
    else:
        store = Store(settings, DeletionJournal(settings.journal_dir, settings.deployment_id))
        await store.open()
    loaded = json.loads(meta.read_text())
    if loaded.get("lexical") != _digest(ROOT / "src/agents_memory/lexical.py"):
        await _reindex(store)
        loaded["lexical"] = _digest(ROOT / "src/agents_memory/lexical.py")
        meta.write_text(json.dumps(loaded))
    actor = await store.authenticate(TOKEN)
    return store, actor, loaded["binding"], loaded["ids"]


async def _measure(split: str, scale: int | None, corpus: Corpus) -> list[dict]:
    store, actor, binding, ids = await _open(split, scale, corpus)
    decoys = {ids[c.key] for c in corpus.claims if c.key.startswith("decoy")}
    rows = []
    try:
        for query in corpus.queries:
            terms = tokens(" ".join((query.text, *query.expansions)))
            started = time.perf_counter()
            found, _ = await store.search_lexical(actor, binding, terms, None, 20,
                                                  request_digest=hashlib.sha256(uuid.uuid4().bytes).hexdigest())
            elapsed = time.perf_counter() - started
            ranked = [claim.id for claim, _ in found]
            gold = {ids[key] for key in query.gold}
            ranks = [ranked.index(item) + 1 for item in gold if item in ranked]
            rows.append({"query": query.id, "group": query.group, "form": query.form,
                         "expanded": bool(query.expansions), "gold": len(gold), "hits": len(ranks),
                         "first": min(ranks) if ranks else None, "returned": len(ranked),
                         "decoys_top5": sum(item in decoys for item in ranked[:5]), "seconds": elapsed})
    finally:
        await store.close()
    return rows


def _summary(rows: list[dict]) -> dict:
    groups = sorted({row["group"] for row in rows})
    result = {}
    for group in groups:
        items = [row for row in rows if row["group"] == group]
        positive = [row for row in items if row["gold"]]
        result[group] = {
            "queries": len(items), "gold": sum(r["gold"] for r in positive), "hits": sum(r["hits"] for r in positive),
            "recall": round(statistics.fmean(r["hits"] / r["gold"] for r in positive), 4) if positive else None,
            "mrr": round(statistics.fmean(1 / r["first"] if r["first"] else 0 for r in positive), 4) if positive else None,
            "returned": round(statistics.fmean(r["returned"] for r in items), 2),
            "decoys_top5": sum(r["decoys_top5"] for r in items),
        }
    positive = [row for row in rows if row["gold"]]
    latencies = sorted(row["seconds"] for row in rows)
    result["ALL"] = {
        "queries": len(rows), "gold": sum(r["gold"] for r in positive), "hits": sum(r["hits"] for r in positive),
        "recall": round(statistics.fmean(r["hits"] / r["gold"] for r in positive), 4),
        "mrr": round(statistics.fmean(1 / r["first"] if r["first"] else 0 for r in positive), 4),
        "p50_ms": round(latencies[int(0.50 * (len(latencies) - 1))] * 1000, 2),
        "p95_ms": round(latencies[int(0.95 * (len(latencies) - 1))] * 1000, 2),
    }
    return result


def evaluate(split: str) -> dict:
    corpus = _split(split)
    scales = SCALES if split != "policy" else (None,)
    report, per_query = {}, {}
    for scale in scales:
        rows = asyncio.run(_measure(split, scale, corpus))
        label = f"x{scale}" if scale else "x1"
        report[label] = _summary(rows)
        per_query[label] = rows
    return {"split": split, "report": report, "per_query": per_query}


def integrity_gate() -> bool:
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                             "tests/test_retrieval_integrity.py"], cwd=ROOT, capture_output=True, text=True)
    print("integrity:", result.stdout.strip().splitlines()[-1] if result.stdout.strip() else result.stderr[-400:])
    return result.returncode == 0


RELATED_TESTS = ("tests/test_lexical_boundaries.py", "tests/test_store_authority.py", "tests/test_company_authority.py",
                 "tests/test_relation_lineage.py", "tests/test_health_backend.py", "tests/test_auto_recall.py",
                 "tests/test_recall_gateway.py")


def related_tests() -> bool:
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *RELATED_TESTS],
                            cwd=ROOT, capture_output=True, text=True)
    print("related tests:", result.stdout.strip().splitlines()[-1] if result.stdout.strip() else result.stderr[-400:])
    return result.returncode == 0


def ensure_postgres() -> None:
    """Use PG_TEST_DSN, else start the CI-identical pgvector image on loopback."""
    if os.environ.get("PG_TEST_DSN"):
        return
    os.environ["PG_TEST_DSN"] = LOCAL_DSN

    async def ready() -> bool:
        try:
            connection = await asyncpg.connect(LOCAL_DSN, timeout=3)
        except (OSError, asyncpg.PostgresError):
            return False
        await connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await connection.close()
        return True

    if asyncio.run(ready()):
        return
    running = subprocess.run(["docker", "ps", "-a", "--filter", "name=^am-loop-pg$", "-q"],
                             capture_output=True, text=True).stdout.strip()
    if running:
        subprocess.run(["docker", "start", "am-loop-pg"], check=True, capture_output=True)
    else:
        subprocess.run(["docker", "run", "-d", "--name", "am-loop-pg", "-e", "POSTGRES_PASSWORD=loop",
                        "-e", "POSTGRES_DB=agents_memory", "-p", "127.0.0.1:55432:5432", PG_IMAGE],
                       check=True, capture_output=True)
    for _ in range(90):
        if asyncio.run(ready()):
            return
        time.sleep(1)
    raise SystemExit("PostgreSQL did not become ready")


def _commit() -> str:
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def _editable_digest() -> str:
    return hashlib.sha256(b"".join(_digest(ROOT / name).encode() for name in EDITABLE)).hexdigest()[:12]


def record(result: dict, label: str, status: str, gate: bool | None) -> None:
    if not RESULTS.exists():
        RESULTS.write_text("time\tcommit\teditable\tsplit\tlabel\tstatus\tintegrity\t"
                           "x1_hits\tx5_hits\tx20_hits\tgold_per_scale\tx1_recall\tx5_recall\tx20_recall\t"
                           "x5_mrr\tx5_G8_returned\tx20_p95_ms\tgroups_x5_recall\n")
    report = result["report"]
    get = lambda scale, key: report.get(scale, {}).get("ALL", {}).get(key, "")  # noqa: E731
    groups = {g: v["recall"] for g, v in report.get("x5", report["x1"]).items() if g != "ALL"}
    line = [time.strftime("%Y-%m-%dT%H:%M:%S"), _commit(), _editable_digest(), result["split"], label, status,
            "" if gate is None else ("pass" if gate else "FAIL"),
            get("x1", "hits"), get("x5", "hits"), get("x20", "hits"), get("x1", "gold"),
            get("x1", "recall"), get("x5", "recall"), get("x20", "recall"), get("x5", "mrr"),
            report.get("x5", {}).get("G8", {}).get("returned", ""), get("x20", "p95_ms") or get("x1", "p95_ms"),
            json.dumps(groups, ensure_ascii=False)]
    with RESULTS.open("a") as handle:
        handle.write("\t".join(map(str, line)) + "\n")


def _scored_hits(report: dict) -> tuple[int, dict]:
    total, groups = 0, {}
    for scale, summary in report.items():
        for group in SCORED:
            if group in summary:
                total += summary[group]["hits"]
                groups[(scale, group)] = summary[group]["hits"]
    return total, groups


def keep_decision(candidate: dict, baseline: dict) -> tuple[bool, list[str]]:
    """Dev keep rule (proposal §4): net +2 scored hits, no group loses 2+, MRR and no-match bounded."""
    reasons = []
    new_total, new_groups = _scored_hits(candidate["report"])
    old_total, old_groups = _scored_hits(baseline["report"])
    if new_total - old_total < 2:
        reasons.append(f"scored hits {old_total}->{new_total} (< +2)")
    for key, old in old_groups.items():
        if new_groups.get(key, 0) <= old - 2:
            reasons.append(f"group {key} hits {old}->{new_groups.get(key, 0)}")
    for scale, summary in baseline["report"].items():
        old_mrr, new_mrr = summary["ALL"]["mrr"], candidate["report"][scale]["ALL"]["mrr"]
        if new_mrr < old_mrr - 0.02:
            reasons.append(f"{scale} MRR {old_mrr}->{new_mrr}")
    old_g8 = baseline["report"]["x5"].get("G8", {}).get("returned", 0)
    new_g8 = candidate["report"]["x5"].get("G8", {}).get("returned", 0)
    if new_g8 > old_g8 + 1:
        reasons.append(f"x5 no-match returned {old_g8}->{new_g8}")
    old_p95, new_p95 = baseline["report"]["x20"]["ALL"]["p95_ms"], candidate["report"]["x20"]["ALL"]["p95_ms"]
    if new_p95 > old_p95 * 1.25:
        reasons.append(f"x20 p95 {old_p95}ms->{new_p95}ms")
    return not reasons, reasons


def _paired_bootstrap(old_rows: dict, new_rows: dict, seed: int = 20261020) -> tuple[float, float, float]:
    """Per-query recall delta summed over scales; percentile 95% CI over 10000 resamples."""
    deltas = {}
    for scale in old_rows:
        old = {r["query"]: r for r in old_rows[scale] if r["gold"]}
        new = {r["query"]: r for r in new_rows[scale] if r["gold"]}
        for query, row in old.items():
            deltas[query] = deltas.get(query, 0.0) + new[query]["hits"] / row["gold"] - row["hits"] / row["gold"]
    values = list(deltas.values())
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choices(values, k=len(values))) for _ in range(10000))
    return statistics.fmean(values), means[249], means[9750]


def _baseline_path(split: str) -> Path:
    return STATE / f"baseline-{split}.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--split", choices=("dev",), default="dev")
    run.add_argument("--label", default="")
    run.add_argument("--record", action="store_true")
    run.add_argument("--baseline", action="store_true", help="store this dev result as the keep baseline")
    run.add_argument("--details", action="store_true", help="dev only: write per-query rows to .cache")
    promote = sub.add_parser("promote")
    promote.add_argument("--label", required=True)
    sub.add_parser("baseline-holdouts")
    sub.add_parser("freeze")
    args = parser.parse_args()
    CACHE.mkdir(exist_ok=True)
    STATE.mkdir(exist_ok=True)
    ensure_postgres()

    if args.command == "freeze":
        FROZEN.write_text(json.dumps({"files": {name: _digest(ROOT / name) for name in FROZEN_FILES},
                                      "editable": list(EDITABLE)}, indent=1) + "\n")
        print(f"froze {len(FROZEN_FILES)} files")
        return
    check_frozen()

    if args.command == "run":
        result = evaluate("dev")
        gate = integrity_gate()
        status = "measured"
        if args.baseline:
            _baseline_path("dev").write_text(json.dumps(result))
            status = "baseline"
        elif _baseline_path("dev").exists():
            keep, reasons = keep_decision(result, json.loads(_baseline_path("dev").read_text()))
            keep = keep and gate
            status = "keep" if keep else "discard: " + "; ".join(reasons or ["integrity gate failed"])
        print(json.dumps(result["report"], ensure_ascii=False, indent=1))
        print("status:", status)
        if args.details:
            (CACHE / "dev-details.json").write_text(json.dumps(result["per_query"], ensure_ascii=False))
        if args.record:
            record(result, args.label, status, gate)
        return

    if args.command == "baseline-holdouts":
        for split in ("holdout", "policy"):
            path = _baseline_path(split)
            if path.exists():
                raise SystemExit(f"{split} baseline already recorded; holdout baselines are taken once")
            result = evaluate(split)
            path.write_text(json.dumps(result))
            print(split, json.dumps({k: v["ALL"] for k, v in result["report"].items()}, ensure_ascii=False))
            record(result, "baseline", "holdout-baseline", None)
        return

    if args.command == "promote":
        attempts = STATE / "promotions.json"
        used = json.loads(attempts.read_text()) if attempts.exists() else []
        if len(used) >= MAX_PROMOTIONS:
            raise SystemExit("promotion budget exhausted (3 attempts)")
        gate = integrity_gate() and related_tests()
        verdicts = {}
        for split in ("holdout", "policy"):
            baseline = json.loads(_baseline_path(split).read_text())
            result = evaluate(split)
            mean, low, high = _paired_bootstrap(baseline["per_query"], result["per_query"])
            regressed = [(scale, group) for scale, summary in result["report"].items() for group, values in summary.items()
                         if group != "ALL" and values.get("hits") is not None
                         and values["hits"] < baseline["report"][scale][group]["hits"]]
            verdicts[split] = {"delta_mean": round(mean, 4), "ci95": [round(low, 4), round(high, 4)],
                               "regressed_groups": len(regressed),
                               "all": {k: v["ALL"] for k, v in result["report"].items()}}
            record(result, args.label, "promotion-eval", gate)
        passed = (gate and verdicts["holdout"]["ci95"][0] > 0 and verdicts["holdout"]["regressed_groups"] == 0
                  and verdicts["policy"]["delta_mean"] >= 0 and verdicts["policy"]["regressed_groups"] == 0)
        used.append({"label": args.label, "commit": _commit(), "passed": passed, "verdicts": verdicts})
        attempts.write_text(json.dumps(used, ensure_ascii=False, indent=1))
        print(json.dumps(verdicts, ensure_ascii=False, indent=1))
        print("PROMOTED" if passed else "NOT PROMOTED", f"(attempt {len(used)}/{MAX_PROMOTIONS})")


if __name__ == "__main__":
    main()
