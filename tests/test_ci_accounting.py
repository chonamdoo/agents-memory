from __future__ import annotations

import errno
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




@pytest.fixture
def evidence(tmp_path):
    module = runpy.run_path(str(Path(__file__).with_name("test_ci_evaluation_gate.py")))
    return module["complete_evidence"](tmp_path)


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
def test_timed_out_check_kills_descendant_after_parent_exits_successfully(
    monkeypatch, owned_descendants,
):
    check = runpy.run_path(str(CI / "run-checks.py"))["check"]
    lifetime = owned_descendants.lifetime
    observer = owned_descendants.observer
    command = [sys.executable, "-c", textwrap.dedent(f"""
        import os
        import signal

        signal.signal(signal.SIGTERM, lambda *_: os._exit(0))
        if os.fork() == 0:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            release = os.open({str(owned_descendants.control)!r}, os.O_RDONLY | os.O_NONBLOCK)
            os.set_blocking(release, True)
            lifetime = os.open({str(lifetime)!r}, os.O_WRONLY | os.O_NONBLOCK)
            os.write(lifetime, b"R")
            os.read(release, 1)
            os._exit(0)
        while True:
            signal.pause()
    """)]
    real_popen = subprocess.Popen
    processes = owned_descendants.processes

    def start(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        owned_descendants.track(process)
        assert select.select([observer], [], [], 5)[0] == [observer]
        return process

    monkeypatch.setattr(subprocess, "Popen", start)
    result = check(command, timeout=1)
    assert result["timeout"] is True
    assert result["exit_code"] == 0
    assert "error" not in result
    assert processes[0][0].returncode == 0
    assert os.read(observer, 1) == b"R"
    assert select.select([observer], [], [], 2)[0] == [observer]
    assert os.read(observer, 1) == b""


@pytest.mark.skipif(os.name != "posix", reason="Owned descendant cleanup requires POSIX")
def test_owned_cleanup_releases_child_after_leader_is_reaped(owned_descendants):
    observer = owned_descendants.observer
    command = [sys.executable, "-c", textwrap.dedent(f"""
        import os
        import signal

        ready_read, ready_write = os.pipe()
        if os.fork() == 0:
            os.close(ready_read)
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            release = os.open({str(owned_descendants.control)!r}, os.O_RDONLY | os.O_NONBLOCK)
            os.set_blocking(release, True)
            lifetime = os.open({str(owned_descendants.lifetime)!r}, os.O_WRONLY | os.O_NONBLOCK)
            os.write(lifetime, b"R")
            os.write(ready_write, b"R")
            os.close(ready_write)
            os.read(release, 1)
            os._exit(0)
        os.close(ready_write)
        os.read(ready_read, 1)
        os._exit(0)
    """)]
    process = subprocess.Popen(
        command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    owned_descendants.track(process)
    assert select.select([observer], [], [], 2)[0] == [observer]
    assert os.read(observer, 1) == b"R"
    assert process.wait(timeout=2) == 0
    assert select.select([observer], [], [], 0)[0] == []


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
def unreaped_leader(request):
    live_member = getattr(request, "param", False)
    control_read, control_write = os.pipe()
    process = None
    observer = None
    program = "import sys; sys.stdin.buffer.read(1)"
    if live_member:
        program = textwrap.dedent(f"""\
            import subprocess, sys
            member = subprocess.Popen(
                [sys.executable, "-I", "-S", "-c",
                 "import os; print('ready', flush=True); os.read({control_read}, 1)"],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, pass_fds=({control_read},),
            )
            if member.stdout.readline() != b"ready\\n":
                raise RuntimeError("member did not start")
            member.stdout.close()
            print("member-ready", flush=True)
            sys.stdin.buffer.read(1)
            """)
    try:
        process = subprocess.Popen(
            [sys.executable, "-I", "-S", "-c", program],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, pass_fds=(control_read,),
            start_new_session=True,
        )
        os.close(control_read)
        control_read = None
        if live_member:
            assert select.select([process.stdout], [], [], 5)[0] == [process.stdout]
            assert process.stdout.readline() == b"member-ready\n"
        deadline = time.monotonic() + 5
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
        # EOF releases the controlled descendant even if cleanup incorrectly skips it.
        os.close(control_write)
        if control_read is not None:
            os.close(control_read)
        if observer is not None:
            observer.close()
        if process is not None:
            process.stdin.close()
            if process.returncode is None:
                with suppress(ProcessLookupError):
                    process.kill()
            process.wait(timeout=5)
            process.stdout.close()


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


@pytest.mark.skipif(os.name != "posix", reason="Process-group supervision requires POSIX")
@pytest.mark.parametrize("target", ["native", "ci"])
def test_real_exited_group_cleanup_keeps_other_owned_process(unreaped_leader, owned_survivor, target):
    cleanup = (native_status._stop_process_group if target == "native"
               else runpy.run_path(str(CI / "run-checks.py"))["_stop_process_group"])
    cleanup(unreaped_leader)
    assert unreaped_leader.returncode == 0
    output, error = owned_survivor.communicate(b"ping\n", timeout=5)
    assert (owned_survivor.returncode, output, error) == (0, b"survived:ping\n", b"")


@pytest.mark.skipif(os.name != "posix", reason="Process-group supervision requires POSIX")
@pytest.mark.parametrize("target", ["native", "ci"])
def test_live_group_permission_error_is_not_terminal(monkeypatch, target):
    process = subprocess.Popen(
        [sys.executable, "-I", "-S", "-c",
         "import time; print('ready', flush=True); time.sleep(30)"],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True,
    )
    cleanup = (native_status._stop_process_group if target == "native"
               else runpy.run_path(str(CI / "run-checks.py"))["_stop_process_group"])
    real_killpg = os.killpg

    def deny_term(pid, sig):
        if pid == process.pid and sig == signal.SIGTERM:
            raise PermissionError(errno.EPERM, "test-only signal permission denial")
        return real_killpg(pid, sig)

    try:
        assert select.select([process.stdout], [], [], 5)[0] == [process.stdout]
        assert process.stdout.readline() == b"ready\n"
        monkeypatch.setattr(os, "killpg", deny_term)
        with pytest.raises(PermissionError):
            cleanup(process)
        assert process.returncode == -signal.SIGKILL
    finally:
        if process.returncode is None:
            process.kill()
        process.wait(timeout=5)
        for stream in (process.stdout, process.stderr):
            stream.close()


@pytest.mark.skipif(os.name != "posix", reason="Process-group supervision requires POSIX")
@pytest.mark.parametrize("target", ["native", "ci"])
@pytest.mark.parametrize("unreaped_leader", [True], indirect=True, ids=["with-member"])
def test_exited_leader_permission_error_with_live_member(unreaped_leader, monkeypatch, target):
    cleanup = (native_status._stop_process_group if target == "native"
               else runpy.run_path(str(CI / "run-checks.py"))["_stop_process_group"])
    real_killpg = os.killpg

    def deny_term(pid, sig):
        if pid == unreaped_leader.pid and sig == signal.SIGTERM:
            raise PermissionError(errno.EPERM, "test-only signal permission denial")
        return real_killpg(pid, sig)

    monkeypatch.setattr(os, "killpg", deny_term)
    with pytest.raises(PermissionError):
        cleanup(unreaped_leader)
    assert unreaped_leader.returncode == 0


@pytest.fixture
def changed_evidence(evidence):
    selectors = ["tests/test_health_backend.py", "tests/test_health_inference.py"]
    scope = {"kind": "changes", "selectors": selectors}
    selected = sorted(node for node in evidence.ids if node.split("::")[0] in selectors)
    reports = {}
    for path in evidence.paths:
        reports.update(json.loads(path.read_text())["reports"])
    source = json.loads(evidence.paths[0].read_text())
    source.update(scope=scope, index=0, count=1, all_nodeids=selected, selected_nodeids=selected,
        reports={node: reports[node] for node in selected},
        counts={"passed": len(selected), "failed": 0, "skipped": 0, "xfailed": 0, "xpassed": 0})
    evidence.paths[0].write_text(json.dumps(source))
    for path in evidence.paths[1:]:
        path.unlink()
        (path.parent / "prerequisites.json").unlink()
    for path in evidence.job.parent.iterdir():
        path.unlink()
    evidence.compat.unlink()
    cases = runpy.run_path(str(CI / "aggregate.py"))["CHANGED_HEALTH_CASES"]
    for path in (evidence.health_source, evidence.health_installed):
        health = json.loads(path.read_text())
        health["health"]["outcomes"] = dict.fromkeys(cases, "passed")
        health["health"]["scope"] = "changed_health_consumers_not_full_acceptance"
        health["health"]["owned_cleanup"]["worker_provider_listener"] = "stopped"
        health["health"]["worker_transport"] = {
            "provider": "owned_loopback_http_fixture", "real_provider_or_native_approval": False,
            "withdrawn_source_requests": 1, "running_service_provider_unchanged": True,
        }
        path.write_text(json.dumps(health))
    lint_paths = ["src/agents_memory/store.py"]
    checks = json.loads(evidence.checks.read_text())
    checks.update(scope=scope, lint_paths=lint_paths)
    checks["checks"]["lint"]["command"] = ["uv", "run", "ruff", "check", *lint_paths]
    checks["checks"]["wheel-consumer"]["command"].extend([
        "--test-paths-json", json.dumps(selectors, separators=(",", ":")),
    ])
    evidence.checks.write_text(json.dumps(checks))
    wheel = json.loads(evidence.wheel.read_text())
    wheel.update(scope=scope, all_nodeids=selected, selected_nodeids=selected,
        reports={node: reports[node] for node in selected}, counts=source["counts"])
    evidence.wheel.write_text(json.dumps(wheel))
    evidence.jobs["compatibility"]["result"] = "skipped"
    evidence.jobs["evaluation"]["result"] = "skipped"
    return SimpleNamespace(evidence=evidence, selectors=selectors, lint_paths=lint_paths)


def test_changed_ci_reports_only_exercised_scope_and_cannot_claim_the_full_suite(changed_evidence):
    data = changed_evidence
    evidence = data.evidence
    result = evidence.aggregate(evidence.root, 1, evidence.sha, evidence.jobs,
        selectors=data.selectors, lint_paths=data.lint_paths)
    assert result["complete"] is True and result["full_suite"] is False
    assert result["scope"] == {"kind": "changes", "selectors": data.selectors}
    assert result["passed"] == result["collected"] == result["wheel_consumer"]["passed"] == 2
    assert "macos_ownership_compatibility" in result["not_executed"]
    assert "docker_evaluation" in result["not_executed"]
    with pytest.raises(ValueError):
        evidence.aggregate(evidence.root, 1, evidence.sha, evidence.jobs)


@pytest.mark.parametrize("fault", [
    "source_scope", "installed_scope", "source_omission", "installed_omission",
    "source_teardown", "installed_call", "wrong_source", "wrong_wheel", "broad_lint", "unrelated_job",
])
def test_changed_ci_refuses_missing_failed_or_misrepresented_selected_work(changed_evidence, fault):
    data = changed_evidence
    evidence = data.evidence
    path = evidence.wheel if fault.startswith("installed") or fault == "wrong_wheel" else evidence.paths[0]
    value = json.loads(path.read_text())
    if fault in {"source_scope", "installed_scope"}:
        del value["scope"]
    elif fault in {"source_omission", "installed_omission"}:
        value["selected_nodeids"].pop()
    elif fault in {"source_teardown", "installed_call"}:
        phase = "teardown" if fault == "source_teardown" else "call"
        value["reports"][value["selected_nodeids"][0]][phase]["outcome"] = "failed"
    elif fault == "wrong_source":
        value["source_after"] = "c" * 64
    elif fault == "wrong_wheel":
        value["wheel_sha256"] = "c" * 64
    elif fault == "broad_lint":
        checks = json.loads(evidence.checks.read_text())
        checks["checks"]["lint"]["command"] = ["uv", "run", "ruff", "check", "src", "tests"]
        evidence.checks.write_text(json.dumps(checks))
    else:
        evidence.jobs["compatibility"]["result"] = "success"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        evidence.aggregate(evidence.root, 1, evidence.sha, evidence.jobs,
            selectors=data.selectors, lint_paths=data.lint_paths)


@pytest.mark.parametrize("fault", [
    "missing", "wrong_scope", "failed_case", "cleanup_incomplete", "wrong_wheel",
    "worker_cleanup", "missing_worker_transport", "native_provider_claim", "withdrawn_retry",
])
def test_changed_ci_requires_actual_related_health_consumption_and_cleanup(changed_evidence, fault):
    data = changed_evidence
    evidence = data.evidence
    path = evidence.health_installed
    health = json.loads(path.read_text())
    if fault == "missing":
        path.unlink()
    else:
        if fault == "wrong_scope":
            health["health"]["scope"] = "full_acceptance"
        elif fault == "failed_case":
            health["health"]["outcomes"]["retracted_session_does_not_block_queued_capture"] = "failed"
        elif fault == "cleanup_incomplete":
            health["health"]["owned_cleanup"]["child_service"] = "unconfirmed"
        elif fault == "worker_cleanup":
            health["health"]["owned_cleanup"]["worker_provider_listener"] = "unconfirmed"
        elif fault == "missing_worker_transport":
            health["health"].pop("worker_transport")
        elif fault == "native_provider_claim":
            health["health"]["worker_transport"]["real_provider_or_native_approval"] = True
        elif fault == "withdrawn_retry":
            health["health"]["worker_transport"]["withdrawn_source_requests"] = 2
        else:
            health["wheel_sha256"] = "c" * 64
        path.write_text(json.dumps(health))
    with pytest.raises((OSError, ValueError)):
        evidence.aggregate(evidence.root, 1, evidence.sha, evidence.jobs,
            selectors=data.selectors, lint_paths=data.lint_paths)


@pytest.mark.parametrize("selection", [
    [], None, {}, ["--collect-only"], ["../tests/test_health_backend.py"],
    ["src/agents_memory/store.py"], ["tests/test_missing_scope.py"],
    ["tests/test_health_backend.py", "tests/test_health_backend.py"],
    ["tests/test_health_backend.py", "tests/test_health_backend.py::test_exact_reject_blocks_recall_and_inflight_delivery_but_not_inspection"],
    ["tests/test_health_backend.py::"], ["tests/test_health_backend.py\n--collect-only"],
])
def test_changed_test_selection_refuses_empty_escaping_or_overlapping_execution(selection):
    parse = runpy.run_path(str(CI / "run-tests.py"))["parse_paths"]
    with pytest.raises(ValueError):
        parse(json.dumps(selection), tests=True)


@pytest.mark.parametrize("component", ["directory", "file"])
def test_changed_selection_never_executes_a_symlinked_source_tree(tmp_path, monkeypatch, component):
    parse = runpy.run_path(str(CI / "run-tests.py"))["parse_paths"]
    root = tmp_path / "checkout"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "test_behavior.py").write_text("raise AssertionError('not checked-out source')\n")
    if component == "directory":
        (root / "tests").symlink_to(outside, target_is_directory=True)
    else:
        (root / "tests").mkdir()
        (root / "tests/test_behavior.py").symlink_to(outside / "test_behavior.py")
    monkeypatch.setitem(parse.__globals__, "ROOT", root)
    with pytest.raises(ValueError):
        parse('["tests/test_behavior.py"]', tests=True)


def test_invalid_changed_selection_refuses_before_any_full_test_fallback(tmp_path, monkeypatch):
    main = runpy.run_path(str(CI / "run-tests.py"))["main"]
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("CI_TESTED_SHA", "a" * 40)
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    monkeypatch.setattr(sys, "argv", ["run-tests.py", "--index", "0", "--count", "1",
        "--result-dir", str(tmp_path / "refused"), "--test-paths-json", "[]"])

    def unapproved_full_collection(*args, **kwargs):
        raise AssertionError("Invalid scope must not invoke pytest")

    monkeypatch.setattr(pytest, "main", unapproved_full_collection)
    with pytest.raises(SystemExit) as refused:
        main()
    assert refused.value.code == 2
    assert not (tmp_path / "refused").exists()
