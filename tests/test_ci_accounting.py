from __future__ import annotations

import hashlib
import json
import runpy
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest

CI = Path(__file__).resolve().parents[1] / ".github" / "ci"


def preparation(tested_sha, postgres):
    observed = {"python": [3, 13, 16], "sqlite": [3, 54, 0], "node": "v24.0.0", "uv": "uv 0.13.0"}
    if postgres:
        observed.update(postgres={"server": "18.6", "vector": "0.8.7"},
                        postgres_clients={}, postgres_image="sha256:" + "d" * 64,
                        operations_mode="local", age="v1.3.2", age_keygen="v1.3.2",
                        age_archive_sha256="e" * 64)
    return {"schema": 1, "complete": True, "tested_sha": tested_sha,
            "postgres_enabled": postgres, "observed": observed}


@pytest.fixture
def evidence(tmp_path):
    module = runpy.run_path(str(CI / "aggregate.py"))
    tested_sha, source = "a" * 40, "b" * 64
    wheel_ids = sorted([
        "tests/test_host_import_isolation.py::test_shadowed_import",
        "tests/test_cli_bind.py::test_occupied_listen_address_refuses_before_database_or_journal_work",
    ])
    all_ids = sorted([*(f"tests/cases.py::test_case_{index}" for index in range(64)), *wheel_ids])
    paths = []
    for index in range(4):
        selected = [item for item in all_ids
                    if int.from_bytes(hashlib.sha256(item.encode()).digest(), "big") % 4 == index]
        value = {
            "schema": 1, "complete": True, "tested_sha": tested_sha,
            "source_before": source, "source_after": source, "index": index, "count": 4,
            "all_nodeids": all_ids, "selected_nodeids": selected, "pytest_exit_code": 0,
            "collection_issues": [], "counts": {"passed": len(selected), "failed": 0,
                "skipped": 0, "xfailed": 0, "xpassed": 0},
            "reports": {item: {phase: {"outcome": "passed", "xfail": False}
                        for phase in ("setup", "call", "teardown")} for item in selected},
        }
        path = tmp_path / str(index) / "shard.json"
        path.parent.mkdir()
        path.write_text(json.dumps(value))
        (path.parent / "prerequisites.json").write_text(json.dumps(preparation(tested_sha, True)))
        paths.append(path)
    checks = tmp_path / "checks" / "checks.json"
    checks.parent.mkdir()
    checks.write_text(json.dumps({
        "schema": 1, "complete": True, "tested_sha": tested_sha,
        "source_before": source, "source_after": source,
        "checks": {name: {"command": command, "exit_code": 0, "timeout": False}
                   for name, command in module["CHECK_COMMANDS"].items()},
    }))
    (checks.parent / "prerequisites.json").write_text(json.dumps(preparation(tested_sha, False)))
    distribution = tmp_path / "distribution" / "candidate.whl"
    distribution.parent.mkdir()
    distribution.write_bytes(b"synthetic artifact bytes for accounting regression")
    wheel = checks.parent / "wheel-consumer.json"
    wheel.write_text(json.dumps({
        "schema": 1, "complete": True, "tested_sha": tested_sha,
        "source_before": source, "source_after": source,
        "wheel_sha256": hashlib.sha256(distribution.read_bytes()).hexdigest(),
        "selected_nodeids": wheel_ids, "collection_issues": [], "pytest_exit_code": 0,
        "counts": {"passed": len(wheel_ids), "failed": 0, "skipped": 0, "xfailed": 0, "xpassed": 0},
        "reports": {item: {phase: {"outcome": "passed", "xfail": False}
                    for phase in ("setup", "call", "teardown")} for item in wheel_ids},
    }))
    return SimpleNamespace(root=tmp_path, paths=paths, checks=checks, wheel=wheel, distribution=distribution,
                           sha=tested_sha, ids=all_ids,
                           jobs={"tests": {"result": "success"}, "checks": {"result": "success"}},
                           aggregate=module["aggregate"])


def test_complete_ci_requires_exact_full_disjoint_execution(evidence):
    result = evidence.aggregate(evidence.root, 4, evidence.sha, evidence.jobs)
    assert result["complete"] is True
    assert result["collected"] == result["passed"] == len(evidence.ids)
    assert sum(shard["passed"] for shard in result["shards"]) == len(evidence.ids)


@pytest.mark.parametrize("fault", [
    "missing-shard", "duplicate-index", "wrong-sha", "source-drift", "collection-drift",
    "omitted-node", "duplicate-node", "wrong-partition", "no-report", "teardown-failure",
    "runtime-skip", "xfail", "counts-lie", "collection-skip", "pytest-error", "incomplete",
    "lint-failure", "build-timeout", "wheel-failure", "missing-wheel-proof",
    "skipped-job", "cancelled-job", "missing-checks",
    "missing-wheel-receipt", "incomplete-wheel", "wheel-distribution-mismatch",
    "missing-distribution", "missing-wheel-case", "missing-prerequisite", "wrong-prerequisite-sha",
])
def test_ci_never_approves_missing_hidden_or_failed_work(evidence, fault):
    path = evidence.paths[0]
    value = json.loads(path.read_text())
    item = value["selected_nodeids"][0]
    if fault == "missing-shard":
        path.unlink()
    elif fault == "duplicate-index":
        value["index"] = 1
    elif fault == "wrong-sha":
        value["tested_sha"] = "c" * 40
    elif fault == "source-drift":
        value["source_after"] = "c" * 64
    elif fault == "collection-drift":
        value["all_nodeids"] = value["all_nodeids"][1:]
    elif fault == "omitted-node":
        value["selected_nodeids"].remove(item)
    elif fault == "duplicate-node":
        value["selected_nodeids"].append(item)
    elif fault == "wrong-partition":
        other = next(node for node in evidence.ids if node not in value["selected_nodeids"])
        value["selected_nodeids"] = sorted([*value["selected_nodeids"], other])
    elif fault == "no-report":
        del value["reports"][item]["call"]
    elif fault == "teardown-failure":
        value["reports"][item]["teardown"]["outcome"] = "failed"
    elif fault == "runtime-skip":
        value["reports"][item]["setup"]["outcome"] = "skipped"
    elif fault == "xfail":
        value["reports"][item]["call"]["xfail"] = True
    elif fault == "counts-lie":
        value["counts"]["passed"] += 1
    elif fault == "collection-skip":
        value["collection_issues"] = [{"nodeid": "tests/hidden.py", "outcome": "skipped"}]
    elif fault == "pytest-error":
        value["pytest_exit_code"] = 2
    elif fault == "incomplete":
        value["complete"] = False
    elif fault in {"lint-failure", "build-timeout", "wheel-failure", "missing-wheel-proof"}:
        checks = json.loads(evidence.checks.read_text())
        if fault == "lint-failure":
            checks["checks"]["lint"]["exit_code"] = 1
        elif fault == "build-timeout":
            checks["checks"]["build"]["timeout"] = True
        elif fault == "wheel-failure":
            checks["checks"]["wheel-consumer"]["exit_code"] = 1
        else:
            del checks["checks"]["wheel-consumer"]
        evidence.checks.write_text(json.dumps(checks))
    elif fault == "missing-wheel-receipt":
        evidence.wheel.unlink()
    elif fault in {"incomplete-wheel", "missing-wheel-case"}:
        wheel = json.loads(evidence.wheel.read_text())
        if fault == "incomplete-wheel":
            wheel["complete"] = False
        else:
            wheel["selected_nodeids"] = wheel["selected_nodeids"][:1]
        evidence.wheel.write_text(json.dumps(wheel))
    elif fault == "wheel-distribution-mismatch":
        evidence.distribution.write_bytes(b"different published artifact")
    elif fault == "missing-distribution":
        evidence.distribution.unlink()
    elif fault == "missing-prerequisite":
        (evidence.paths[0].parent / "prerequisites.json").unlink()
    elif fault == "wrong-prerequisite-sha":
        preparation_file = evidence.paths[0].parent / "prerequisites.json"
        observed = json.loads(preparation_file.read_text())
        observed["tested_sha"] = "c" * 40
        preparation_file.write_text(json.dumps(observed))
    elif fault in {"skipped-job", "cancelled-job"}:
        evidence.jobs["tests"]["result"] = "skipped" if fault == "skipped-job" else "cancelled"
    elif fault == "missing-checks":
        evidence.checks.unlink()
    if fault != "missing-shard":
        path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        evidence.aggregate(evidence.root, 4, evidence.sha, evidence.jobs)


@pytest.mark.parametrize("phases,expected", [
    ({"setup": "passed", "call": "passed", "teardown": "passed"}, "passed"),
    ({"setup": "passed", "call": "passed", "teardown": "failed"}, "failed"),
    ({"setup": "skipped", "teardown": "passed"}, "skipped"),
    ({"setup": "failed", "teardown": "passed"}, "failed"),
    ({"setup": "passed", "call": "passed"}, "failed"),
])
def test_shard_counts_actual_terminal_phases_not_just_call(phases, expected):
    shard = runpy.run_path(str(CI / "run-tests.py"))["Shard"](0, 1)
    shard.selected = ["tests/example.py::test_behavior"]
    for phase, outcome in phases.items():
        shard.pytest_runtest_logreport(SimpleNamespace(
            nodeid=shard.selected[0], when=phase, outcome=outcome, duration=0.01,
        ))
    assert shard.counts() == {name: int(name == expected)
                              for name in ("passed", "failed", "skipped", "xfailed", "xpassed")}


def test_junit_preserves_failure_without_exporting_credentials_or_captured_output(tmp_path):
    module = runpy.run_path(str(CI / "run-tests.py"))
    shard = module["Shard"](0, 1)
    shard.selected = ["tests/example.py::test_behavior"]
    secret = "postgresql://ci:private-password@127.0.0.1/database"
    for phase in ("setup", "call", "teardown"):
        shard.pytest_runtest_logreport(SimpleNamespace(
            nodeid=shard.selected[0], when=phase, duration=0.01,
            outcome="failed" if phase == "call" else "passed",
            longrepr=secret, sections=[("Captured stdout call", secret)],
        ))
    output = tmp_path / "junit.xml"
    module["write_junit"](output, shard)
    raw = output.read_text()
    assert secret not in raw and "private-password" not in raw
    suite = ET.parse(output).getroot()
    assert suite.get("failures") == "1" and suite.get("errors") == "0"
    assert suite.find("testcase/failure") is not None
    assert suite.findall(".//system-out") == [] and suite.findall(".//system-err") == []
    assert shard.counts()["failed"] == 1
