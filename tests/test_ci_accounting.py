from __future__ import annotations

import hashlib
import json
import os
import runpy
import select
import signal
import subprocess
import sys
import textwrap
import time
import xml.etree.ElementTree as ET
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents_memory import native_status

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
        "tests/test_service.py::test_managed_readiness_preserves_the_owned_config_upgrade_refusal",
        "tests/test_inspection_stability.py::test_minimum_mcp_cap_can_inspect_a_plain_captured_source[modern]",
        "tests/test_edge_boundaries.py::test_producer_capture_authority_never_grants_memory_read_authority",
        "tests/test_judge_settings.py::test_waiting_judge_mutations_recheck_live_operator_authority[revoke-allow]",
        "tests/test_judge_settings.py::test_judge_file_failures_keep_publication_identity_and_explicit_recovery[before-effect-policy]",
        "tests/test_native_status.py::test_native_inventory_ends_descendants_and_closes_pipes_on_failure[None-malformed-parent_first]",
        "tests/test_recovery.py::test_remote_bad_first_outbox_cannot_starve_retained_healthy_batch[None]",
        "tests/test_remote_cancellation.py::test_readonly_ready_stop_cancels_real_tls_response_before_business_dispatch[headers]",
        "tests/test_remote_cancellation.py::test_already_dispatched_business_request_drains_response_without_retry",
        "tests/test_ci_accounting.py::test_cleanup_after_esrch_cannot_kill_a_reused_group[probe-native]",
        "tests/test_ci_accounting.py::test_cleanup_after_esrch_cannot_kill_a_reused_group[term-native]",
        "tests/test_ci_accounting.py::test_cleanup_retains_identity_through_the_final_group_signal[after-probe-native]",
        "tests/test_ci_accounting.py::test_cleanup_retains_identity_through_the_final_group_signal[already-reaped-native]",
    ])
    compat_ids = sorted([item for item in wheel_ids
                         if any(item.startswith(selector + "[")
                                for selector in module["COMPAT_SELECTORS"])])
    compat_ids = sorted([*compat_ids, *(item.replace("-native]", "-ci]") for item in compat_ids)])
    all_ids = sorted([*(f"tests/cases.py::test_case_{index}" for index in range(64)),
                      *wheel_ids, *(item for item in compat_ids if item not in wheel_ids)])
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
    (checks.parent / "prerequisites.json").write_text(json.dumps(preparation(tested_sha, True)))
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
    compat = tmp_path / "compatibility" / "compatibility.json"
    compat.parent.mkdir()
    compat.write_text(json.dumps({
        "schema": 1, "complete": True, "tested_sha": tested_sha,
        "source_before": source, "source_after": source, "runtime": module["COMPAT_RUNTIME"],
        "all_nodeids": compat_ids, "selected_nodeids": compat_ids,
        "collection_issues": [], "pytest_exit_code": 0,
        "counts": {"passed": len(compat_ids), "failed": 0, "skipped": 0, "xfailed": 0, "xpassed": 0},
        "reports": {item: {phase: {"outcome": "passed", "xfail": False}
                    for phase in ("setup", "call", "teardown")} for item in compat_ids},
    }))
    return SimpleNamespace(root=tmp_path, paths=paths, checks=checks, wheel=wheel, distribution=distribution,
                           sha=tested_sha, ids=all_ids, compat=compat,
                           jobs={name: {"result": "success"}
                                 for name in ("tests", "checks", "compatibility")},
                           aggregate=module["aggregate"])


@pytest.mark.parametrize("fault", ["missing", "wrong-runtime", "omitted-case"])
def test_complete_ci_refuses_incomplete_minimum_platform_proof(evidence, fault):
    if fault == "missing":
        evidence.compat.unlink()
    else:
        value = json.loads(evidence.compat.read_text())
        if fault == "wrong-runtime":
            value["runtime"]["python"] = [3, 13, 16]
        else:
            value["selected_nodeids"].pop()
        evidence.compat.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        evidence.aggregate(evidence.root, 4, evidence.sha, evidence.jobs)


def test_complete_ci_requires_exact_full_disjoint_execution(evidence):
    result = evidence.aggregate(evidence.root, 4, evidence.sha, evidence.jobs)
    assert result["complete"] is True
    assert result["collected"] == result["passed"] == len(evidence.ids)
    assert sum(shard["passed"] for shard in result["shards"]) == len(evidence.ids)


def test_complete_ci_refuses_self_consistent_import_only_wheel_execution(evidence):
    wheel = json.loads(evidence.wheel.read_text())
    limited = [item for item in wheel["selected_nodeids"]
               if item.startswith("tests/test_host_import_isolation.py::")
               or item == "tests/test_cli_bind.py::test_occupied_listen_address_refuses_before_database_or_journal_work"]
    wheel["selected_nodeids"] = limited
    wheel["reports"] = {item: wheel["reports"][item] for item in limited}
    wheel["counts"]["passed"] = len(limited)
    evidence.wheel.write_text(json.dumps(wheel))
    with pytest.raises(ValueError):
        evidence.aggregate(evidence.root, 4, evidence.sha, evidence.jobs)


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


@pytest.mark.skipif(os.name != "posix", reason="CI process supervision requires POSIX")
def test_timed_out_check_kills_descendant_after_parent_exits_successfully(tmp_path, monkeypatch):
    check = runpy.run_path(str(CI / "run-checks.py"))["check"]
    lifetime = tmp_path / "descendant-lifetime"
    os.mkfifo(lifetime, 0o600)
    observer = os.open(lifetime, os.O_RDONLY | os.O_NONBLOCK)
    command = [sys.executable, "-c", textwrap.dedent(f"""
        import os
        import signal

        signal.signal(signal.SIGTERM, lambda *_: os._exit(0))
        if os.fork() == 0:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            lifetime = os.open({str(lifetime)!r}, os.O_WRONLY)
            os.write(lifetime, b"R")
            while True:
                signal.pause()
        while True:
            signal.pause()
    """)]
    real_popen = subprocess.Popen
    processes = []

    def start(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        processes.append(process)
        assert select.select([observer], [], [], 5)[0] == [observer]
        return process

    monkeypatch.setattr(subprocess, "Popen", start)
    try:
        result = check(command, timeout=1)
        assert result["timeout"] is True
        assert result["exit_code"] == 0
        assert "error" not in result
        assert processes[0].returncode == 0
        assert os.read(observer, 1) == b"R"
        assert select.select([observer], [], [], 2)[0] == [observer]
        assert os.read(observer, 1) == b""
    finally:
        try:
            for process in processes:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=2)
        finally:
            os.close(observer)


@pytest.fixture
def digest_source(tmp_path, monkeypatch):
    digest = runpy.run_path(str(CI / "run-tests.py"))["source_digest"]
    root = CI.parents[1]
    for name in ("pyproject.toml", "uv.lock"):
        (tmp_path / name).write_bytes((root / name).read_bytes())
    relative = Path("src/agents_memory/host_templates/omp.ts")
    resource = tmp_path / relative
    resource.parent.mkdir(parents=True)
    resource.write_bytes((root / relative).read_bytes())
    monkeypatch.setitem(digest.__globals__, "ROOT", tmp_path)
    return SimpleNamespace(root=tmp_path, resource=resource, digest=digest)


def test_source_digest_changes_when_executable_host_template_changes(digest_source):
    before = digest_source.digest()
    with digest_source.resource.open("a") as resource:
        resource.write("\nthrow new Error('CI source identity changed');\n")
    assert digest_source.digest() != before


def test_source_digest_ignores_generated_bytecode(digest_source):
    before = digest_source.digest()
    generated = digest_source.root / "src/agents_memory/__pycache__/hosts.cpython-313.pyc"
    generated.parent.mkdir()
    generated.write_bytes(b"generated interpreter output")
    assert digest_source.digest() == before


@pytest.fixture
def unreaped_leader():
    process = subprocess.Popen(
        [sys.executable, "-I", "-S", "-c", "import sys; sys.stdin.buffer.read(1)"],
        stdin=subprocess.PIPE, start_new_session=True,
    )
    observer = None
    deadline = time.monotonic() + 5
    try:
        if not hasattr(os, "waitid"):
            observer = select.kqueue()
            observer.control([select.kevent(
                process.pid, filter=select.KQ_FILTER_PROC,
                flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT, fflags=select.KQ_NOTE_EXIT,
            )], 0, 0)
        # Register before releasing the child: NOTE_EXIT must not race an earlier exit.
        process.stdin.write(b"\n")
        process.stdin.close()
        if observer is None:
            while os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None:
                assert time.monotonic() < deadline
                time.sleep(0.001)
        else:
            events = observer.control(None, 1, 5)
            assert len(events) == 1 and events[0].ident == process.pid
            assert events[0].fflags & select.KQ_NOTE_EXIT
        yield process
    finally:
        if observer is not None:
            observer.close()
        process.stdin.close()
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
        process.wait(timeout=5)


@pytest.fixture
def owned_survivor():
    process = subprocess.Popen(
        [sys.executable, "-I", "-S", "-c",
         "import sys; print('ready', flush=True); "
         "line = sys.stdin.readline(); print('survived:' + line.strip(), flush=True)"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
    )
    try:
        assert select.select([process.stdout], [], [], 5)[0] == [process.stdout]
        assert process.stdout.readline() == b"ready\n"
        yield process
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()


@pytest.mark.skipif(os.name != "posix", reason="Process-group supervision requires POSIX")
@pytest.mark.parametrize("target", ["native", "ci"])
@pytest.mark.parametrize("disappeared_at", ["term", "probe"])
def test_cleanup_after_esrch_cannot_kill_a_reused_group(monkeypatch, unreaped_leader, owned_survivor,
                                                      target, disappeared_at):
    cleanup = (native_status._stop_process_group if target == "native"
               else runpy.run_path(str(CI / "run-checks.py"))["_stop_process_group"])
    expired, unrelated = unreaped_leader, owned_survivor
    real_killpg = os.killpg

    def simulate_pgid_reuse(pid, sig):
        if pid != expired.pid:
            return real_killpg(pid, sig)
        if sig == signal.SIGTERM:
            if disappeared_at == "term":
                raise ProcessLookupError
            return None
        if sig == 0:
            raise ProcessLookupError
        return real_killpg(unrelated.pid, sig)

    monkeypatch.setattr(os, "killpg", simulate_pgid_reuse)
    cleanup(expired)
    assert expired.returncode == 0
    output, error = unrelated.communicate(b"ping\n", timeout=5)
    assert (unrelated.returncode, output, error) == (0, b"survived:ping\n", b"")


@pytest.mark.skipif(os.name != "posix", reason="Process-group supervision requires POSIX")
@pytest.mark.parametrize("target", ["native", "ci"])
@pytest.mark.parametrize("interleaving", ["after-probe", "already-reaped"])
def test_cleanup_retains_identity_through_the_final_group_signal(monkeypatch, unreaped_leader,
                                                               owned_survivor, target, interleaving):
    expired, unrelated = unreaped_leader, owned_survivor
    if interleaving == "already-reaped":
        expired.wait(timeout=5)
    cleanup = (native_status._stop_process_group if target == "native"
               else runpy.run_path(str(CI / "run-checks.py"))["_stop_process_group"])
    clock = SimpleNamespace(now=0)
    probed = False
    real_killpg = os.killpg

    def simulate_pgid_reuse(pid, sig):
        nonlocal probed
        if pid != expired.pid:
            return real_killpg(pid, sig)
        if interleaving == "already-reaped":
            return real_killpg(unrelated.pid, sig)
        if sig == signal.SIGTERM:
            return None
        if sig == 0:
            probed = True
            return None
        if probed and expired.returncode is not None:
            return real_killpg(unrelated.pid, sig)
        # The owned target is simulated, like TERM/probe above. Only a released
        # identity redirects a real signal to the survivor; zombie-group signal
        # permissions differ between kernels and are not this injected fault.
        return None

    monkeypatch.setattr(os, "killpg", simulate_pgid_reuse)
    # Advance only cleanup's grace clock; subprocess readiness and waits stay real.
    monkeypatch.setitem(cleanup.__globals__, "time", SimpleNamespace(
        monotonic=lambda: clock.now, sleep=lambda _: setattr(clock, "now", clock.now + 10),
    ))
    cleanup(expired)
    if interleaving == "after-probe":
        assert probed
        assert expired.returncode == 0
    output, error = unrelated.communicate(b"ping\n", timeout=5)
    assert (unrelated.returncode, output, error) == (0, b"survived:ping\n", b"")
