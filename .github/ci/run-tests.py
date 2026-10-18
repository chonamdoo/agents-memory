from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def source_digest() -> str:
    paths = {ROOT / "pyproject.toml", ROOT / "uv.lock"}
    for pattern in (
        "src/**/*.py", "src/agents_memory/host_templates/*.ts",
        "tests/**/*.py", ".github/ci/*.py", ".github/workflows/*.yml",
    ):
        paths.update(ROOT.glob(pattern))
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def write_result(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def parse_paths(raw: str | None, *, tests: bool) -> list[str] | None:
    if raw is None:
        return None
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 16384:
        raise ValueError("CI selection must be bounded JSON")
    values = json.loads(raw)
    if not isinstance(values, list) or not 1 <= len(values) <= 64:
        raise ValueError("CI selection requires explicit nonempty paths")
    paths = []
    for value in values:
        if (not isinstance(value, str) or not 1 <= len(value) <= 512
                or any(ord(character) < 32 or ord(character) == 127 for character in value)):
            raise ValueError("Invalid CI selection")
        filename, separator, member = value.partition("::")
        pattern = (r"tests/(?:[A-Za-z0-9_]+/)*test_[A-Za-z0-9_]+\.py" if tests else
                   r"(?:src|tests|\.github/ci)/(?:[A-Za-z0-9_]+/)*[A-Za-z0-9_-]+\.py")
        if (re.fullmatch(pattern, filename) is None or (separator and (
                not tests or not member or re.match(r"[A-Za-z_]", member) is None))):
            raise ValueError("CI selection is outside the declared source surface")
        path = ROOT
        for part in Path(filename).parts:
            path = path / part
            if path.is_symlink():
                raise ValueError("CI selection cannot follow symlinks")
        if not path.is_file():
            raise ValueError("CI selection requires an existing file")
        paths.append(value)
    paths.sort()
    for previous, current in zip(paths, paths[1:]):
        if current == previous or current.startswith((previous + "::", previous + "[")):
            raise ValueError("CI selections must not overlap")
    return paths


class Shard:
    def __init__(self, index: int, count: int) -> None:
        self.index = index
        self.count = count
        self.collected: list[str] = []
        self.selected: list[str] = []
        self.reports: dict[str, dict[str, dict]] = {}
        self.collection_issues: list[dict[str, str]] = []

    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, config, items) -> None:
        self.collected = sorted(item.nodeid for item in items)
        if len(set(self.collected)) != len(self.collected):
            raise pytest.UsageError("CI collection contains duplicate test node IDs")
        selected, deselected = [], []
        for item in items:
            bucket = int.from_bytes(hashlib.sha256(item.nodeid.encode()).digest(), "big") % self.count
            (selected if bucket == self.index else deselected).append(item)
        self.selected = sorted(item.nodeid for item in selected)
        items[:] = selected
        config.hook.pytest_deselected(items=deselected)

    def pytest_collectreport(self, report) -> None:
        if report.outcome != "passed":
            self.collection_issues.append({"nodeid": report.nodeid, "outcome": report.outcome})

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item, call):
        outcome = yield
        report = outcome.get_result()
        code = getattr(call.excinfo.value, "ci_failure_code", None) if call.excinfo is not None else None
        if isinstance(code, str) and re.fullmatch(r"EVALUATION_SCENARIO_[A-Z0-9_]{1,40}", code):
            report.ci_failure_code = code

    def pytest_runtest_logreport(self, report) -> None:
        phases = self.reports.setdefault(report.nodeid, {})
        if report.when in phases:
            raise RuntimeError("CI does not accept retried or duplicate test reports")
        phases[report.when] = {
            "outcome": report.outcome, "xfail": hasattr(report, "wasxfail"),
            "duration": report.duration,
        }
        if hasattr(report, "ci_failure_code"):
            phases[report.when]["failure_code"] = report.ci_failure_code

    def counts(self) -> dict[str, int]:
        counts = {"passed": 0, "failed": 0, "skipped": 0, "xfailed": 0, "xpassed": 0}
        for nodeid in self.selected:
            phases = self.reports.get(nodeid, {})
            outcomes = list(phases.values())
            if any(value["outcome"] == "failed" for value in outcomes):
                name = "failed"
            elif any(value["xfail"] for value in outcomes):
                name = "xfailed" if any(value["outcome"] == "skipped" for value in outcomes) else "xpassed"
            elif any(value["outcome"] == "skipped" for value in outcomes):
                name = "skipped"
            elif (set(phases) != {"setup", "call", "teardown"}
                  or any(value["outcome"] != "passed" for value in outcomes)):
                name = "failed"
            else:
                name = "passed"
            counts[name] += 1
        return counts


def write_junit(path: Path, shard: Shard) -> None:
    suite = ET.Element("testsuite", name="agents-memory", tests=str(len(shard.selected) + len(shard.collection_issues)))
    failures = skipped = errors = 0
    for nodeid in shard.selected:
        phases = shard.reports.get(nodeid, {})
        duration = sum(phase["duration"] for phase in phases.values())
        case = ET.SubElement(suite, "testcase", name=nodeid, classname=nodeid.split("::")[0],
                             time=f"{duration:.6f}")
        outcomes = list(phases.values())
        if any(phase["outcome"] == "failed" for phase in outcomes):
            codes = sorted({phase["failure_code"] for phase in outcomes if phase.get("failure_code")})
            ET.SubElement(case, "failure", message=";".join(codes) if codes else "A runtime phase failed")
            failures += 1
        elif any(phase["outcome"] == "skipped" for phase in outcomes):
            ET.SubElement(case, "skipped", message="A runtime phase skipped or xfailed")
            skipped += 1
        elif set(phases) != {"setup", "call", "teardown"}:
            ET.SubElement(case, "error", message="Runtime phases did not complete")
            errors += 1
        elif any(phase["xfail"] for phase in outcomes):
            ET.SubElement(case, "failure", message="An expected failure unexpectedly passed")
            failures += 1
    for issue in shard.collection_issues:
        case = ET.SubElement(suite, "testcase", name=issue["nodeid"], classname="collection")
        if issue["outcome"] == "skipped":
            ET.SubElement(case, "skipped", message="A module was skipped during collection")
            skipped += 1
        else:
            ET.SubElement(case, "error", message="Collection did not complete")
            errors += 1
    suite.set("failures", str(failures))
    suite.set("skipped", str(skipped))
    suite.set("errors", str(errors))
    temporary = path.with_suffix(".tmp")
    ET.ElementTree(suite).write(temporary, encoding="utf-8", xml_declaration=True)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one disjoint shard of the complete current pytest collection")
    parser.add_argument("--index", type=int, required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--test-paths-json", help="Explicit changed-path regression selectors; omitted means full collection")
    args = parser.parse_args()
    if os.environ.get("GITHUB_ACTIONS") != "true":
        parser.error("This runner is GitHub Actions-only; do not execute tests locally")
    if not 1 <= args.count <= 32 or not 0 <= args.index < args.count:
        parser.error("A shard requires 0 <= index < count <= 32")
    tested_sha = os.environ.get("CI_TESTED_SHA", "")
    if len(tested_sha) != 40 or any(character not in "0123456789abcdef" for character in tested_sha):
        parser.error("CI_TESTED_SHA must identify the exact checked-out commit")
    if os.environ.get("PYTEST_ADDOPTS"):
        parser.error("CI requires the complete declared collection without environment selection options")
    try:
        selectors = parse_paths(args.test_paths_json, tests=True)
    except (OSError, ValueError):
        parser.error("Changed-path selectors must name bounded, nonoverlapping repository tests")
    os.chdir(ROOT)
    args.result_dir.mkdir(parents=True, exist_ok=True)
    result_file = args.result_dir / "shard.json"
    before = source_digest()
    result = {
        "schema": 1, "complete": False, "tested_sha": tested_sha, "source_before": before,
        "index": args.index, "count": args.count, "all_nodeids": [], "selected_nodeids": [],
        "collection_issues": [],
        "pytest_exit_code": None,
        **({"scope": {"kind": "changes", "selectors": selectors}} if selectors is not None else {}),
    }
    write_result(result_file, result)
    shard = Shard(args.index, args.count)
    began = time.monotonic()
    try:
        code = int(pytest.main(["-q", *(selectors or [])], plugins=[shard]))
        after = source_digest()
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
        write_result(result_file, result)
        write_junit(args.result_dir / "junit.xml", shard)


if __name__ == "__main__":
    raise SystemExit(main())
