from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
CHECK_COMMANDS = {
    "lint": ["uv", "run", "ruff", "check", "src", "tests", ".github/ci"],
    "build": ["uv", "build"],
    "wheel-consumer": ["uv", "run", "--no-sync", "python", ".github/ci/wheel-consumer.py",
                       "--result-dir", ".ci-results"],
}
WHEEL_SELECTORS = (
    "tests/test_host_import_isolation.py",
    "tests/test_cli_bind.py::test_occupied_listen_address_refuses_before_database_or_journal_work",
    "tests/test_service.py::test_managed_readiness_preserves_the_owned_config_upgrade_refusal",
    "tests/test_inspection_stability.py::test_minimum_mcp_cap_can_inspect_a_plain_captured_source",
    "tests/test_edge_boundaries.py::test_producer_capture_authority_never_grants_memory_read_authority",
    "tests/test_judge_settings.py::test_waiting_judge_mutations_recheck_live_operator_authority",
    "tests/test_judge_settings.py::test_judge_file_failures_keep_publication_identity_and_explicit_recovery",
    "tests/test_native_status.py::test_native_inventory_ends_descendants_and_closes_pipes_on_failure",
    "tests/test_recovery.py::test_remote_bad_first_outbox_cannot_starve_retained_healthy_batch",
    "tests/test_remote_cancellation.py::test_readonly_ready_stop_cancels_real_tls_response_before_business_dispatch",
    "tests/test_remote_cancellation.py::test_already_dispatched_business_request_drains_response_without_retry",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def wheel_nodeids(collection: list[str]) -> list[str]:
    selected: set[str] = set()
    for selector in WHEEL_SELECTORS:
        prefixes = (selector + "::", selector + "[")
        matches = {item for item in collection if item == selector or item.startswith(prefixes)}
        require(bool(matches), f"No collected installed-wheel consumer for {selector}")
        require(selected.isdisjoint(matches), "Overlapping installed-wheel selectors")
        selected.update(matches)
    return sorted(selected)


def receipt(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"Invalid receipt object: {path.name}")
    return value


def nodeids(value, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"Missing {label}")
    require(all(isinstance(item, str) and item for item in value), f"Invalid {label}")
    require(value == sorted(set(value)), f"Duplicate or unordered {label}")
    return value


def identity(value: dict, tested_sha: str, source: str | None = None) -> str:
    require(type(value.get("schema")) is int and value["schema"] == 1, "Unknown receipt schema")
    require(value.get("tested_sha") == tested_sha, "Receipts do not match the tested head SHA")
    before, after = value.get("source_before"), value.get("source_after")
    if not isinstance(before, str) or DIGEST.fullmatch(before) is None:
        raise ValueError("Invalid source digest")
    require(before == after, "Source changed during verification")
    require(source is None or before == source, "Jobs verified different source trees")
    require(value.get("complete") is True, "A verification job did not complete successfully")
    return before


def execution(value: dict, selected: list[str]) -> None:
    require(type(value.get("pytest_exit_code")) is int and value["pytest_exit_code"] == 0,
            "Pytest did not exit successfully")
    reports = value.get("reports")
    if not isinstance(reports, dict) or set(reports) != set(selected):
        raise ValueError("Missing or unexpected test reports")
    for phases in reports.values():
        if not isinstance(phases, dict) or set(phases) != {"setup", "call", "teardown"}:
            raise ValueError("A selected test has incomplete runtime phases")
        require(all(isinstance(phase, dict) and phase.get("outcome") == "passed"
                    and phase.get("xfail") is False for phase in phases.values()),
                "A runtime phase failed, skipped, xfailed or xpassed")
    expected = {"passed": len(selected), "failed": 0, "skipped": 0, "xfailed": 0, "xpassed": 0}
    counts = value.get("counts")
    require(isinstance(counts, dict) and counts == expected
            and all(type(count) is int for count in counts.values()), "Inconsistent test outcome counts")


def prerequisites(path: Path, tested_sha: str, postgres: bool) -> None:
    value = receipt(path)
    require(type(value.get("schema")) is int and value["schema"] == 1, "Unknown prerequisite schema")
    require(value.get("tested_sha") == tested_sha and value.get("complete") is True,
            "Missing or mismatched prerequisite preparation")
    require(value.get("postgres_enabled") is postgres, "Wrong prerequisite role")
    observed = value.get("observed")
    required = {"python", "sqlite", "node", "uv"}
    if postgres:
        required.update({"postgres", "postgres_clients", "postgres_image", "operations_mode",
                         "age", "age_keygen", "age_archive_sha256"})
    require(isinstance(observed, dict) and required <= set(observed), "Missing actual prerequisite observations")


def aggregate(artifacts: Path, expected_shards: int, tested_sha: str, upstream_jobs: dict) -> dict:
    require(SHA.fullmatch(tested_sha) is not None, "An exact tested head SHA is required")
    require(type(expected_shards) is int and 1 <= expected_shards <= 32, "Invalid shard count")
    require(isinstance(upstream_jobs, dict) and set(upstream_jobs) == {"tests", "checks"},
            "Missing upstream job results")
    require(all(isinstance(job, dict) and job.get("result") == "success"
                for job in upstream_jobs.values()), "An upstream job failed, was skipped or was cancelled")
    paths = sorted(artifacts.rglob("shard.json"))
    require(len(paths) == expected_shards, "Missing or duplicate shard artifacts")
    checks_paths = list(artifacts.rglob("checks.json"))
    require(len(checks_paths) == 1, "Missing or duplicate lint/build artifact")
    require(len(list(artifacts.rglob("prerequisites.json"))) == expected_shards + 1,
            "Missing or duplicate prerequisite artifacts")
    source = None
    collection = None
    selected_union: set[str] = set()
    indices: set[int] = set()
    shards = []
    for path in paths:
        value = receipt(path)
        prerequisites(path.parent / "prerequisites.json", tested_sha, True)
        source = identity(value, tested_sha, source)
        index = value.get("index")
        if type(index) is not int or not 0 <= index < expected_shards:
            raise ValueError("Invalid shard index")
        require(index not in indices, "Duplicate shard index")
        indices.add(index)
        require(type(value.get("count")) is int and value["count"] == expected_shards,
                "Inconsistent shard count")
        require(value.get("collection_issues") == [], "Pytest collection failed or skipped a module")
        current = nodeids(value.get("all_nodeids"), "complete collection")
        require(collection is None or collection == current, "Shards collected different tests")
        collection = current
        selected = nodeids(value.get("selected_nodeids"), "selected tests")
        expected = [item for item in current
                    if int.from_bytes(hashlib.sha256(item.encode()).digest(), "big") % expected_shards == index]
        require(selected == expected, "Shard selection does not match its deterministic partition")
        require(selected_union.isdisjoint(selected), "Tests ran in multiple shards")
        selected_union.update(selected)
        execution(value, selected)
        shards.append({"index": index, "passed": len(selected), "seconds": value.get("seconds")})
    require(indices == set(range(expected_shards)), "A shard index is missing")
    if collection is None or selected_union != set(collection):
        raise ValueError("The full collection was not executed")
    checks = receipt(checks_paths[0])
    prerequisites(checks_paths[0].parent / "prerequisites.json", tested_sha, True)
    identity(checks, tested_sha, source)
    outcomes = checks.get("checks")
    if not isinstance(outcomes, dict) or set(outcomes) != set(CHECK_COMMANDS):
        raise ValueError("Missing lint/build/wheel outcomes")
    for name, command in CHECK_COMMANDS.items():
        outcome = outcomes[name]
        require(isinstance(outcome, dict) and outcome.get("command") == command,
                f"Unexpected {name} command")
        require(type(outcome.get("exit_code")) is int and outcome["exit_code"] == 0
                and not outcome.get("timeout") and not outcome.get("error"), f"The {name} command did not pass")
    wheel_paths = list(artifacts.rglob("wheel-consumer.json"))
    require(len(wheel_paths) == 1, "Missing or duplicate wheel-consumer artifact")
    wheel = receipt(wheel_paths[0])
    identity(wheel, tested_sha, source)
    require(wheel.get("collection_issues") == [], "Wheel consumer did not collect cleanly")
    selected = nodeids(wheel.get("selected_nodeids"), "wheel-consumer execution")
    expected_wheel = wheel_nodeids(collection)
    require(selected == expected_wheel, "The installed wheel did not exercise every declared consumer case")
    execution(wheel, selected)
    distributions = list((artifacts / "distribution").glob("*.whl"))
    require(len(distributions) == 1, "Missing or ambiguous public wheel artifact")
    with distributions[0].open("rb") as stream:
        wheel_digest = hashlib.file_digest(stream, "sha256").hexdigest()
    require(wheel.get("wheel_sha256") == wheel_digest, "The public wheel differs from the exercised artifact")
    return {
        "schema": 1, "complete": True, "tested_sha": tested_sha, "source_digest": source,
        "collected": len(collection), "passed": len(selected_union), "failed": 0,
        "skipped": 0, "xfailed": 0, "xpassed": 0,
        "shards": sorted(shards, key=lambda shard: shard["index"]), "checks": outcomes,
        "wheel_consumer": {"sha256": wheel_digest, "passed": len(selected),
                          "artifact": distributions[0].name},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Require complete parallel CI evidence for one exact source tree")
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--expected-shards", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("GITHUB_ACTIONS") != "true":
        parser.error("This gate is GitHub Actions-only")
    tested_sha = os.environ.get("CI_TESTED_SHA", "")
    try:
        jobs = json.loads(os.environ.get("CI_UPSTREAM_JOBS", "{}"))
        result = aggregate(args.artifacts, args.expected_shards, tested_sha, jobs)
    except (OSError, ValueError, TypeError) as error:
        result = {"schema": 1, "complete": False, "tested_sha": tested_sha, "error": str(error)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as stream:
            stream.write(f"## Parallel verification: {'PASS' if result['complete'] else 'FAIL'}\n\n")
            stream.write(f"Tested head: `{tested_sha}`\n\n")
            if result["complete"]:
                stream.write(f"{result['passed']} passed; 0 skipped/xfail/xpass; "
                             f"{len(result['shards'])} disjoint shards; lint/build passed.\n")
                stream.write(f"Source: `{result['source_digest']}`\n")
            else:
                stream.write("Complete, consistent passing evidence is unavailable; see summary.json.\n")
            stream.write("\nCI is not native-host protection, formal review or release approval.\n")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
