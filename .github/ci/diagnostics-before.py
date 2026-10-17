from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PREFIX = "tests/test_evaluation_diagnostics.py::test_rehashed_packing_cannot_replace_frozen_claim_meaning_or_provenance["


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--result-dir", type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("Actions-only baseline observation")
    baseline = args.baseline_root.resolve()
    result_dir = args.result_dir.resolve()
    before_sha = subprocess.check_output(["git", "-C", str(baseline), "rev-parse", "HEAD"], text=True).strip()
    if before_sha != args.expected_source:
        raise RuntimeError("Baseline source identity mismatch")
    source = baseline / "src" / "agents_memory" / "evaluation_diagnostics.py"
    test_source = ROOT / "tests" / "test_evaluation_diagnostics.py"
    overlaid = baseline / "tests" / test_source.name
    original_test_digest = hashlib.sha256(overlaid.read_bytes()).hexdigest()
    shutil.copyfile(test_source, overlaid)
    collector = runpy.run_path(str(ROOT / ".github" / "ci" / "run-tests.py"))["Shard"]

    class Baseline(collector):
        def __init__(self):
            super().__init__(0, 1)
            self.failure_kinds = {}

        @pytest.hookimpl(hookwrapper=True)
        def pytest_runtest_makereport(self, item, call):
            outcome = yield
            report = outcome.get_result()
            if report.when == "call" and call.excinfo is not None:
                error = call.excinfo.value
                self.failure_kinds[item.nodeid] = (
                    "expected_exception_not_raised"
                    if isinstance(error, pytest.fail.Exception) and str(error).startswith("DID NOT RAISE")
                    else "other_failure"
                )

    plugin = Baseline()
    os.chdir(baseline)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        exit_code = int(pytest.main([str(overlaid), "-q", "--tb=short"], plugins=[plugin]))
    imported_path = sys.modules["agents_memory.evaluation_diagnostics"].__file__
    if not isinstance(imported_path, str):
        raise RuntimeError("Baseline imported module has no source identity")
    imported = Path(imported_path).resolve()
    expected = {node for node in plugin.selected if node.startswith(PREFIX)}
    failed = {node for node, phases in plugin.reports.items()
              if any(phase["outcome"] == "failed" for phase in phases.values())}
    phase_complete = all(set(phases) == {"setup", "call", "teardown"}
                         and phases["setup"]["outcome"] == phases["teardown"]["outcome"] == "passed"
                         and all(not phase["xfail"] for phase in phases.values())
                         for phases in plugin.reports.values())
    counts = plugin.counts()
    complete = (
        imported == source and exit_code == 1 and len(expected) == 10 and expected == failed
        and len(plugin.reports) == len(plugin.selected) and phase_complete
        and not plugin.collection_issues and counts["skipped"] == counts["xfailed"] == counts["xpassed"] == 0
        and all(plugin.failure_kinds.get(node) == "expected_exception_not_raised" for node in expected)
        and plugin.reports.get("tests/test_evaluation_diagnostics.py::test_automatic_packing_uses_complete_inputs_not_observed_delivery", {}).get("call", {}).get("outcome") == "passed"
    )
    receipt = {
        "schema": 1, "complete": complete, "scope": "diagnostics_function_valid_fixture_before_not_native_or_whole_evaluation_acceptance",
        "code_source_sha": before_sha, "test_source_sha": os.environ["CI_TESTED_SHA"],
        "source_module_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "imported_exact_before_module": imported == source,
        "test_module_sha256": hashlib.sha256(test_source.read_bytes()).hexdigest(),
        "previous_test_module_sha256": original_test_digest,
        "overlay": "current corrected diagnostic fixtures only; before product source unchanged",
        "fixture_contract": "in-memory diagnostic API fixture; not load_manifest or native approval proof",
        "exit_code": exit_code, "counts": counts, "collection_issues": plugin.collection_issues,
        "reports": plugin.reports, "failure_kinds": plugin.failure_kinds,
        "original18_completed": 0,
    }
    result_dir.mkdir(parents=True, exist_ok=True)
    (result_dir / "diagnostics-before.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"complete": complete, "code_source_sha": before_sha, "counts": counts,
                      "expected_missing_guard_failures": len(expected), "original18_completed": 0}))
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
