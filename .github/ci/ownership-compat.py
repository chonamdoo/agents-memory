from __future__ import annotations

import argparse
import os
import runpy
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description="Exercise owned process cleanup on macOS CPython 3.12")
    parser.add_argument("--result-dir", type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("GITHUB_ACTIONS") != "true":
        parser.error("This runner is GitHub Actions-only; do not execute tests locally")
    policy = runpy.run_path(str(ROOT / ".github/ci/aggregate.py"))
    tested_sha = os.environ.get("CI_TESTED_SHA", "")
    if policy["SHA"].fullmatch(tested_sha) is None:
        parser.error("CI_TESTED_SHA must identify the exact checked-out commit")
    if os.environ.get("PYTEST_ADDOPTS"):
        parser.error("Compatibility requires every declared ownership case")
    runner = runpy.run_path(str(ROOT / ".github/ci/run-tests.py"))
    os.chdir(ROOT)
    args.result_dir.mkdir(parents=True, exist_ok=True)
    result_file = args.result_dir / "compatibility.json"
    before = runner["source_digest"]()
    runtime = {"platform": sys.platform, "implementation": sys.implementation.name,
               "python": list(sys.version_info[:3])}
    result = {
        "schema": 1, "complete": False, "tested_sha": tested_sha,
        "source_before": before, "runtime": runtime, "all_nodeids": [],
        "selected_nodeids": [], "collection_issues": [], "pytest_exit_code": None,
    }
    runner["write_result"](result_file, result)
    shard = runner["Shard"](0, 1)
    began = time.monotonic()
    try:
        if runtime != policy["COMPAT_RUNTIME"]:
            result["error"] = "The declared minimum-version macOS runtime was not exercised"
            return 1
        code = int(pytest.main(["-q", *policy["COMPAT_SELECTORS"]], plugins=[shard]))
        after = runner["source_digest"]()
        counts = shard.counts()
        result.update(
            pytest_exit_code=code, source_after=after, all_nodeids=shard.collected,
            selected_nodeids=shard.selected, reports=shard.reports, counts=counts,
            collection_issues=shard.collection_issues,
            seconds=round(time.monotonic() - began, 3),
        )
        result["complete"] = (
            code == 0 and before == after and bool(shard.selected) and not shard.collection_issues
            and set(shard.reports) == set(shard.selected)
            and counts["passed"] == len(shard.selected)
        )
        return 0 if result["complete"] else code or 1
    finally:
        runner["write_result"](result_file, result)
        runner["write_junit"](args.result_dir / "junit.xml", shard)


if __name__ == "__main__":
    raise SystemExit(main())
