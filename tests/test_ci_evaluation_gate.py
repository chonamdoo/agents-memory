from __future__ import annotations

import hashlib
import json
import os
import runpy
import zipfile
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import pytest

CI = Path(__file__).resolve().parents[1] / ".github" / "ci"


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def complete_evidence(root: Path) -> SimpleNamespace:
    module = runpy.run_path(str(CI / "aggregate.py"))
    sha, source = "a" * 40, "b" * 64
    common = {"schema": 1, "complete": True, "tested_sha": sha,
              "source_before": source, "source_after": source}
    owner = {"run_id": os.environ.get("GITHUB_RUN_ID", "123"),
             "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "1")}

    def owned(job: str) -> dict:
        return {**common, "actions": {**owner, "job_id": job}}

    def execution(ids: list[str]) -> dict:
        return {"all_nodeids": ids, "selected_nodeids": ids, "collection_issues": [], "pytest_exit_code": 0,
                "reports": {item: {phase: {"outcome": "passed", "xfail": False}
                            for phase in ("setup", "call", "teardown")} for item in ids},
                "counts": {"passed": len(ids), "failed": 0, "skipped": 0, "xfailed": 0, "xpassed": 0}}

    observed = dict.fromkeys(("python", "sqlite", "node", "uv", "postgres", "postgres_clients", "postgres_image",
                              "operations_mode", "age", "age_keygen", "age_archive_sha256"), "engineering-fixture")
    preparation = {"schema": 1, "complete": True, "tested_sha": sha, "postgres_enabled": True, "observed": observed}
    collection = sorted({*(selector if "::" in selector else selector + "::test_engineering_fixture"
                          for selector in module["WHEEL_SELECTORS"]), *module["COMPAT_SELECTORS"],
                         *("tests/engineering_fixture.py::test_" + str(index) for index in range(64))})
    selected_wheel = module["wheel_nodeids"](collection)
    paths = []
    for index in range(4):
        selected = [item for item in collection if int.from_bytes(hashlib.sha256(item.encode()).digest(), "big") % 4 == index]
        path = root / ("ci-tests-" + str(index)) / "shard.json"
        write_json(path, {**common, **execution(selected), "all_nodeids": collection, "index": index, "count": 4})
        write_json(path.parent / "prerequisites.json", preparation)
        paths.append(path)
    checks = root / "ci-checks" / "checks.json"
    write_json(checks, {**common, "checks": {name: {"command": command, "exit_code": 0, "timeout": False}
                                             for name, command in module["CHECK_COMMANDS"].items()}})
    write_json(checks.parent / "prerequisites.json", preparation)
    policy = runpy.run_path(str(CI / "comment-check.py"))
    comparison = {"base_sha": "c" * 40, "basis": "pull_request_base"}
    compared_files = [{
        "path_digest": "1" * 64, "status": "A", "old_mode": "000000", "new_mode": "100644",
        "old_oid": "0" * 40, "new_oid": "2" * 40, "old_bytes": 0, "new_bytes": 12,
    }]
    comments = checks.parent / "comment-check.json"
    write_json(comments, {**owned("checks"), "code": "CHECKED", "comparison": comparison,
                         "checker": {"commit": policy["CHECKER_COMMIT"], "sha256": policy["CHECKER_SHA256"],
                                     "url": policy["CHECKER_URL"], "bytes": policy["CHECKER_BYTES"], "license": "MIT"},
                         "coverage": {"changed_files": 1, "eligible_files": 1, "excluded_files": 0, "input_bytes": 12,
                                      "finding_count": 0, "findings": [], "coverage_complete": True, "files": compared_files,
                                      "manifest_digest": policy["digest"](policy["canonical"](compared_files))}})
    distribution = root / "distribution" / "engineering-evidence-fixture.whl"
    distribution.parent.mkdir(parents=True)
    module_names = {"cli", "config", "store", "application", "edge", "health", "health_producer", "health_code",
                    "evaluation", "evaluation_artifacts", "evaluation_runtime", "evaluation_native",
                    "evaluation_gateway", "evaluation_scoring", "evaluation_verifier",
                    "evaluation_diagnostics", "context", "evaluation_health"}
    modules = {}
    with zipfile.ZipFile(distribution, "w") as archive:
        for name in sorted(module_names):
            member = "agents_memory/" + name + ".py"
            raw = ("engineering accounting fixture, not executable product proof: " + name).encode()
            archive.writestr(member, raw)
            modules[member] = hashlib.sha256(raw).hexdigest()
    wheel_digest = hashlib.sha256(distribution.read_bytes()).hexdigest()
    wheel = checks.parent / "wheel-consumer.json"
    write_json(wheel, {**common, **execution(selected_wheel), "wheel_sha256": wheel_digest, "installed_modules": modules})
    compat = root / "ci-compatibility" / "compatibility.json"
    compat_ids = sorted(item for item in collection
                        if any(item == selector or item.startswith(selector + "[") for selector in module["COMPAT_SELECTORS"]))
    write_json(compat, {**common, **execution(compat_ids), "runtime": module["COMPAT_RUNTIME"]})
    command = {"state": "completed", "exit_code": 0, "stdout_complete": True,
               "stderr_complete": True, "helper_cleanup": True, "stdout_bytes": 100, "stderr_bytes": 0,
               "stdout_sha256": "6" * 64, "stderr_sha256": hashlib.sha256(b"").hexdigest(), "elapsed_seconds": 0.5}
    health = {"schema": 1, "complete": True, "tested_sha": sha, "source_unchanged": True, "surface": "health-api-cli",
              "original18_completed": 0, "outcomes": dict.fromkeys(module["HEALTH_CASES"], "passed"),
              "consumed": {"child_identity_matches": True, "module_tree_digest": "d" * 64,
                           "module_identity": "agents_memory", "distribution": "0.1.0",
                           "module_tree_digest_after": "d" * 64,
                           "modules": {name: {"identity": "agents_memory." + name,
                                              "sha256": modules["agents_memory/" + name + ".py"]}
                                       for name in ("cli", "config", "store", "application", "edge", "health", "health_producer", "health_code")}},
              "owned_cleanup": {"project_adapter": "removed", "child_service": "stopped", "fixture_store": "closed",
                                "private_schema": "removed", "admin_connection": "closed", "private_evidence": "retained",
                                "service_exit_clean": True, "service_exit_code": 0}}
    health_source = paths[0].parent / "health-source.json"
    health_installed = checks.parent / "health-installed.json"
    for path, surface, job in ((health_source, "source", "tests"), (health_installed, "installed", "checks")):
        write_json(path, {**owned(job), "consumption": surface, "wheel_sha256": wheel_digest if surface == "installed" else None,
                          "execution": command, "health": health})
    evaluation = root / "ci-evaluation"
    write_json(evaluation / "prerequisites.json", preparation)
    job = evaluation / "evaluation-job.json"
    evaluation_wheel = "e" * 64
    runtime_digest = "f" * 64
    measured = {"runtime_digest": runtime_digest, "runtime_spec_sha256": "7" * 64,
                "docker_sha256": "8" * 64, "tool_identity": "2" * 64, "image_id_digest": "9" * 64,
                "image_config_digest": "1" * 64, "python_executable_sha256": "0" * 64}
    write_json(job, {**owned("evaluation"), "consumption": "installed", "wheel_origin": "evaluation-job-built",
                    "wheel_sha256": evaluation_wheel, "installed_modules": modules, "image_reference": module["EVALUATION_IMAGE"],
                    "phases": dict.fromkeys(module["EVALUATION_PHASES"], command), "runtime": measured})
    write_json(evaluation / "evaluation-runtime-prepare.json",
               {**owned("evaluation"), "stage": "prepare", "code": "READY", "cleanup_complete": True,
                "runtime_digest": runtime_digest, "image_config_digest": "1" * 64, "tool_digest": "2" * 64})
    scenario = evaluation / "evaluation-scenarios.json"
    write_json(scenario, {**owned("evaluation"), **execution(module["SCENARIO_NODEIDS"]),
                          "runtime_digest": runtime_digest, "wheel_sha256": evaluation_wheel, "installed_modules": modules,
                          "observer_authority": {
                              "schema": 2, "scope": "owned_engineering_only",
                              "frozen_daemon_inventory": True, "subject_quiescence_refused": True,
                              "observer_started": False, "file_effect_refused": True,
                              "oracle_passed": False, "cleanup_complete": True,
                          }})
    mapping = {"controller": "evaluation", "artifacts": "evaluation_artifacts", "runtime_driver": "evaluation_runtime",
               "native_driver": "evaluation_native", "gateway_driver": "evaluation_gateway", "scoring": "evaluation_scoring",
               "diagnostics": "evaluation_diagnostics", "context_renderer": "context", "health_compiler": "evaluation_health",
               "verifier": "evaluation_verifier", "cli": "cli"}
    observed_modules = {name: modules["agents_memory/" + target + ".py"] for name, target in mapping.items()}
    observed_modules_digest = hashlib.sha256(json.dumps(observed_modules, ensure_ascii=False, sort_keys=True,
                                                        separators=(",", ":")).encode()).hexdigest()
    smoke = evaluation / "evaluation-smoke.json"
    write_json(smoke, {"schema": 1, "code": "COMPLETED", "complete": True, "tested_sha": sha, "scope": "engineering", "native_acceptance": False,
                       "synthetic_native_protocol_peer": True, "original18_completed": 0,
                       "outcomes": module["EVALUATION_OUTCOMES"],
                       "pair_drift": module["PAIR_DRIFT_OUTCOMES"],
                       "identity": {**measured, "consumption": "installed", "wheel_sha256": evaluation_wheel,
                                    "distribution_version": "0.1.0", "modules_digest": observed_modules_digest,
                                    "module_digests": observed_modules},
                       "manifest_digest": "3" * 64, "report_digest": "4" * 64, "evidence_inventory_digest": "5" * 64,
                       "owned_cleanup": dict.fromkeys(("complete", "verifiers_exact_absent", "product_service_stopped",
                                                       "store_closed", "schema_exact_absent", "private_evidence_retained"), True)})
    cleanup = evaluation / "evaluation-cleanup.json"
    write_json(cleanup, {**owned("evaluation"), "runtime_digest": runtime_digest,
                         **dict.fromkeys(("runtime_exact_absent", "schema_exact_absent", "prerequisites_exact_absent",
                                          "processes_reaped", "private_evidence_retained"), True)})
    runtime_cleanup = evaluation / "evaluation-runtime-cleanup.json"
    write_json(runtime_cleanup, {**owned("evaluation"), "stage": "cleanup", "code": "CLEAN", "cleanup_complete": True,
                                 "probe_cleanup": "absent", "owners": 2, "resources": 3})
    return SimpleNamespace(root=root, sha=sha, ids=collection, paths=paths, checks=checks, wheel=wheel,
                           distribution=distribution, compat=compat, job=job, scenario=scenario, smoke=smoke,
                           cleanup=cleanup, runtime_cleanup=runtime_cleanup,
                           health_source=health_source, health_installed=health_installed, comments=comments,
                           jobs={name: {"result": "success"} for name in ("tests", "checks", "compatibility", "evaluation")},
                           aggregate=partial(module["aggregate"], comparison=comparison))


@pytest.fixture
def evidence(tmp_path):
    return complete_evidence(tmp_path)


def test_complete_ci_binds_distinct_wheels_and_real_engineering_surfaces(evidence):
    result = evidence.aggregate(evidence.root, 4, evidence.sha, evidence.jobs)
    assert result["complete"] is True
    assert result["passed"] == result["collected"] == len(evidence.ids)
    assert result["health"] == {"source": True, "installed": True}
    assert result["evaluation"]["wheel_sha256"] != result["wheel_consumer"]["sha256"]
    assert result["evaluation"]["full_smoke"] is True
    assert result["evaluation"]["exact_cleanup"] is True


@pytest.mark.parametrize("name", ["job", "scenario", "smoke", "cleanup", "runtime_cleanup", "health_source", "health_installed", "comments"])
@pytest.mark.parametrize("fault", ["missing", "duplicate", "malformed"])
def test_complete_ci_requires_unique_parseable_engineering_evidence(evidence, name, fault):
    path = getattr(evidence, name)
    if fault == "missing":
        path.unlink()
    elif fault == "duplicate":
        duplicate = evidence.root / "duplicate" / path.name
        duplicate.parent.mkdir()
        duplicate.write_bytes(path.read_bytes())
    else:
        path.write_text('{"complete":')
    with pytest.raises((ValueError, OSError, TypeError)):
        evidence.aggregate(evidence.root, 4, evidence.sha, evidence.jobs)


@pytest.mark.parametrize("status", ["failure", "cancelled", "skipped", "unknown", None])
def test_complete_ci_refuses_nonpassing_evaluation_job(evidence, status):
    evidence.jobs["evaluation"]["result"] = status
    with pytest.raises(ValueError):
        evidence.aggregate(evidence.root, 4, evidence.sha, evidence.jobs)


@pytest.mark.parametrize("target,keys,replacement", [
    ("job", ("tested_sha",), "c" * 40),
    ("comments", ("checker", "sha256"), "0" * 64),
    ("comments", ("comparison", "base_sha"), "d" * 40),
    ("comments", ("coverage", "coverage_complete"), False),
    ("comments", ("coverage", "finding_count"), 1),
    ("job", ("source_after",), "c" * 64),
    ("job", ("actions", "job_id"), "checks"),
    ("job", ("actions", "run_attempt"), "999999"),
    ("job", ("wheel_origin",), "checks-job-distribution"),
    ("job", ("consumption",), "source"),
    ("job", ("installed_modules", "agents_memory/cli.py"), "0" * 64),
    ("job", ("phases", "image-acquisition", "state"), "timeout"),
    ("job", ("phases", "runtime-prepare", "helper_cleanup"), False),
    ("scenario", ("wheel_sha256",), "0" * 64),
    ("scenario", ("runtime_digest",), "0" * 64),
    ("scenario", ("collection_issues",), [{"outcome": "skipped"}]),
    ("scenario", ("counts", "skipped"), 1),
    ("scenario", ("observer_authority",), None),
    ("scenario", ("observer_authority", "subject_quiescence_refused"), False),
    ("scenario", ("observer_authority", "oracle_passed"), True),
    ("scenario", ("observer_authority", "observer_started"), True),
    ("smoke", ("complete",), None),
    ("smoke", ("identity", "runtime_digest"), "0" * 64),
    ("smoke", ("identity", "wheel_sha256"), "0" * 64),
    ("smoke", ("identity", "module_digests", "controller"), "0" * 64),
    ("smoke", ("outcomes", "valid_pairs"), 0),
    ("smoke", ("outcomes", "valid_pairs"), True),
    ("smoke", ("outcomes", "unknown_costs_preserved"), False),
    ("smoke", ("owned_cleanup", "schema_exact_absent"), None),
    ("smoke", ("native_acceptance",), True),
    ("cleanup", ("runtime_exact_absent",), False),
    ("cleanup", ("schema_exact_absent",), None),
    ("cleanup", ("prerequisites_exact_absent",), False),
    ("cleanup", ("processes_reaped",), False),
    ("cleanup", ("runtime_digest",), "0" * 64),
    ("runtime_cleanup", ("probe_cleanup",), "pending_create"),
    ("runtime_cleanup", ("resources",), 0),
    ("health_source", ("consumption",), "installed"),
    ("health_source", ("health", "outcomes", "bounded_session_assessment"), "not_run"),
    ("health_source", ("health", "source_unchanged"), None),
    ("health_installed", ("wheel_sha256",), "0" * 64),
    ("health_installed", ("health", "consumed", "child_identity_matches"), False),
    ("health_installed", ("health", "owned_cleanup", "private_schema"), "unconfirmed"),
    ("health_installed", ("health", "owned_cleanup", "service_exit_code"), True),
    ("health_installed", ("execution", "stderr_complete"), False),
])
def test_complete_ci_refuses_semantic_identity_phase_and_cleanup_drift(evidence, target, keys, replacement):
    path = getattr(evidence, target)
    value = json.loads(path.read_text())
    entry = value
    for key in keys[:-1]:
        entry = entry[key]
    entry[keys[-1]] = replacement
    write_json(path, value)
    with pytest.raises(ValueError):
        evidence.aggregate(evidence.root, 4, evidence.sha, evidence.jobs)


@pytest.mark.parametrize("fault", ["omitted", "unknown", "missing-phase", "skip", "xfail", "xpass"])
def test_complete_ci_requires_every_actual_scenario_and_runtime_phase(evidence, fault):
    value = json.loads(evidence.scenario.read_text())
    node = value["selected_nodeids"][0]
    if fault == "omitted":
        value["selected_nodeids"].remove(node)
    elif fault == "unknown":
        value["selected_nodeids"].append("tests/evaluation_docker_scenarios.py::test_unexpected")
        value["selected_nodeids"].sort()
    elif fault == "missing-phase":
        del value["reports"][node]["teardown"]
    else:
        phase = value["reports"][node]["call"]
        phase["outcome"] = "skipped" if fault in {"skip", "xfail"} else "passed"
        phase["xfail"] = fault in {"xfail", "xpass"}
    write_json(evidence.scenario, value)
    with pytest.raises(ValueError):
        evidence.aggregate(evidence.root, 4, evidence.sha, evidence.jobs)


@pytest.mark.parametrize("surface", ["health_source", "health_installed"])
def test_complete_ci_binds_health_module_bytes_to_public_wheel(evidence, surface):
    path = getattr(evidence, surface)
    value = json.loads(path.read_text())
    value["health"]["consumed"]["modules"]["health"]["sha256"] = "0" * 64
    write_json(path, value)
    with pytest.raises(ValueError):
        evidence.aggregate(evidence.root, 4, evidence.sha, evidence.jobs)


@pytest.mark.parametrize("fault", ["none", "parent-changed", "zombie", "unreaped"])
def test_orphan_reconciliation_pins_only_adopted_children_before_signalling(tmp_path, monkeypatch, fault):
    runner = runpy.run_path(str(CI / "run-evaluation.py"))
    reconcile = runner["reap_owned_descendants"]
    scope = reconcile.__globals__
    proc = tmp_path / "proc"
    children = proc / "self" / "task" / "500" / "children"
    children.parent.mkdir(parents=True)
    children.write_bytes(b"101")
    subject = proc / "101"
    subject.mkdir()
    fields = ["S", "999" if fault == "parent-changed" else "500", *(["0"] * 17), "12345"]
    (subject / "stat").write_bytes(("101 (owned fixture) " + " ".join(fields)).encode())
    (subject / "cmdline").write_bytes(b"engineering-fixture\0")
    events = []

    def save(path, value):
        events.append(("save", path.name, value))

    def send(descriptor, sig):
        assert descriptor == 42 and sig == 9
        assert events[-1][0] == "save" and events[-1][2]["start_ticks"] == 12345
        events.append(("signal", descriptor))
        if fault == "zombie":
            raise ProcessLookupError

    def reap(pid, options):
        assert (pid, options) == (101, 0)
        events.append(("reap", pid))
        children.write_bytes(b"")
        return pid, 0

    monkeypatch.setitem(scope, "Path", lambda value: proc / str(value).removeprefix("/proc/"))
    monkeypatch.setitem(scope, "os", SimpleNamespace(getpid=lambda: 500, pidfd_open=lambda pid: 42,
                                                    waitpid=reap, close=lambda descriptor: events.append(("close", descriptor))))
    monkeypatch.setitem(scope, "signal", SimpleNamespace(SIGKILL=9, pidfd_send_signal=send))
    monkeypatch.setitem(scope, "select", SimpleNamespace(select=lambda *args: ([], [], []) if fault == "unreaped" else ([42], [], [])))
    monkeypatch.setitem(scope, "private_save", save)
    monkeypatch.setitem(scope, "actions", lambda: {"run_id": "123", "run_attempt": "1", "job_id": "evaluation"})
    assert reconcile(tmp_path, "fixture") is (fault in {"none", "zombie"})
    assert events[-1][0:2] == ("save", "fixture-descendants.json")
    if fault == "parent-changed":
        assert not any(event[0] in {"signal", "reap"} for event in events)
    if fault == "unreaped":
        assert not any(event[0] == "reap" for event in events)


@pytest.mark.parametrize("constant", ['{"complete":true,"complete":true}', '{"seconds":NaN}', '{"seconds":Infinity}'])
def test_aggregate_rejects_ambiguous_or_nonfinite_receipts(tmp_path, constant):
    module = runpy.run_path(str(CI / "aggregate.py"))
    path = tmp_path / "receipt.json"
    path.write_text(constant)
    with pytest.raises(ValueError):
        module["receipt"](path)
