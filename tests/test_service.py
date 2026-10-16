from __future__ import annotations

import contextlib
import json
import os
import plistlib
import stat
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents_memory import service
from agents_memory.config import Settings
from agents_memory.domain import DomainError, EffectState
from agents_memory.private_io import private_write


@pytest.fixture
def native(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(service.sys, "platform", "darwin")
    interpreter = home / "venv" / "bin" / "python"
    interpreter.parent.mkdir(parents=True, mode=0o700)
    interpreter.symlink_to(Path(service.sys.executable).resolve())
    monkeypatch.setattr(service.sys, "executable", str(interpreter))
    package = home / "source" / "agents_memory"
    package.mkdir(parents=True, mode=0o700)
    (package / "cli.py").write_text("# Trusted import-root fixture; never executed.\n")
    monkeypatch.setattr(service, "__file__", str(package / "service.py"))
    state = SimpleNamespace(home=home, interpreter=interpreter, package=package,
                            jobs={}, disabled=set(), calls=[], fail=None)

    def run(argv, **kwargs):
        assert argv[0] == "/bin/launchctl"
        assert 0 < kwargs.pop("timeout") <= 2
        args = argv[1:]
        state.calls.append(args)
        action = args[0]
        if state.fail == action:
            return subprocess.CompletedProcess(argv, 1, "", "PRIVATE launchctl output never returned")
        if action == "print":
            job = state.jobs.get(args[1])
            if job is None:
                return subprocess.CompletedProcess(argv, 113, "", "Could not find service")
            output = f"{args[1]} = {{\n path = {job['path']}\n environment = {{ SECRET = hidden }}\n"
            if job["running"]:
                output += " pid = 1234\n"
            return subprocess.CompletedProcess(argv, 0, output + "}\n", "")
        if action == "bootstrap":
            data = plistlib.loads(Path(args[2]).read_bytes())
            target = args[1] + "/" + data["Label"]
            assert target not in state.disabled
            state.jobs[target] = {"path": args[2], "running": True}
        elif action == "kickstart":
            assert "-k" not in args
            state.jobs[args[1]]["running"] = True
        elif action == "enable":
            state.disabled.discard(args[1])
        elif action == "disable":
            label = args[1].rsplit("/", 1)[1]
            data = plistlib.loads((home / "Library" / "LaunchAgents" / (label + ".plist")).read_bytes())
            receipt = json.loads((Path(data["WorkingDirectory"]) / "receipt.json").read_bytes())
            assert receipt["enabled"] is False  # Native stop must follow the durable override.
            state.disabled.add(args[1])
        elif action == "bootout":
            assert args[1] in state.disabled
            del state.jobs[args[1]]
        else:
            raise AssertionError(args)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(service.subprocess, "run", run)
    return state


@pytest.fixture
def deployment(native):
    settings = Settings(deployment_id="deployment_test", realm="realm_test", mode="company",
        database_dsn="postgresql://absent:PRIVATE_DATABASE_SECRET@127.0.0.1:1/absent",
        state_dir=native.home / "authority", journal_dir=native.home / "independent-journal", port=18768)
    config = native.home / "config.json"
    private_write(config, settings.model_dump_json())
    return settings, config


def receipt(settings):
    return json.loads((settings.state_dir / "service" / "receipt.json").read_bytes())


def mutations(native):
    return [call for call in native.calls if call[0] != "print"]


def test_install_native_identity_and_private_files(native, deployment, monkeypatch):
    settings, config = deployment
    monkeypatch.setenv("JEV_API_KEY", "PRIVATE_INHERITED_SECRET")
    result = service.install_service(settings, config)
    assert result == {"managed": True, "enabled": True, "loaded": True, "running": True,
                      "label": receipt(settings)["label"], "deployment_id": settings.deployment_id}
    owned = receipt(settings)
    plist_path = Path(owned["plist_path"])
    plist = plistlib.loads(plist_path.read_bytes())
    argv = plist["ProgramArguments"]
    assert argv[:2] == ["/usr/bin/env", "-i"]
    assert argv[-7:] == [str(native.interpreter), "-s", "-m", "agents_memory.cli", "--config", str(config), "service-run"]
    assert str(native.interpreter) in argv
    assert str(native.interpreter.resolve()) != owned["executable"]
    assert "PYTHONPATH=" + str(native.package.parent) in argv
    assert "PYTHONNOUSERSITE=1" in argv
    assert "PRIVATE" not in json.dumps(plist)
    assert plist["WorkingDirectory"] == str(settings.state_dir / "service")
    assert plist["RunAtLoad"] is True
    assert plist["KeepAlive"] == {"SuccessfulExit": False}
    assert plist["ThrottleInterval"] == 5
    assert plist["StandardOutPath"] == plist["StandardErrorPath"] == "/dev/null"
    assert stat.S_IMODE((settings.state_dir / "service").stat().st_mode) == 0o700
    for path in (plist_path, settings.state_dir / "service" / "receipt.json", settings.state_dir / "service" / "control.lock"):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    service.require_service_enabled(settings)
    assert "hidden" not in json.dumps(service.service_status(settings))
    assert "PRIVATE_DATABASE_SECRET" not in json.dumps(result)


def test_complete_lifecycle_and_stopped_override(native, deployment):
    settings, config = deployment
    installed = service.install_service(settings, config)
    label = installed["label"]
    stopped = service.stop_service(settings)
    assert stopped == {**installed, "enabled": False, "loaded": False, "running": False}
    before = list(native.calls)
    for operation in (lambda: service.ensure_started(settings.base_url, settings.state_dir, settings.deployment_id),
                      lambda: service.require_service_enabled(settings)):
        with pytest.raises(DomainError) as denied:
            operation()
        assert denied.value.code == "SERVICE_STOPPED"
        assert denied.value.effect == EffectState.NOT_STARTED
    assert native.calls == before
    assert service.install_service(settings, config)["enabled"] is False
    assert receipt(settings)["enabled"] is False
    assert not native.jobs
    started = service.start_service(settings)
    assert started["enabled"] and started["running"]
    assert started["label"] == label
    config_before = config.read_bytes()
    unrelated = settings.state_dir / "service" / "operator-notes.txt"
    unrelated.write_text("keep this")
    assert service.uninstall_service(settings)["managed"] is False
    assert config.read_bytes() == config_before
    assert unrelated.read_text() == "keep this"
    assert not (settings.state_dir / "service" / "receipt.json").exists()
    assert not (native.home / "Library" / "LaunchAgents" / (label + ".plist")).exists()
    assert not native.jobs
    assert service.service_status(settings)["managed"] is False
    assert service.uninstall_service(settings)["managed"] is False


def test_unmanaged_service_is_not_adopted_or_spawned(native, deployment):
    settings, _ = deployment
    assert service.ensure_started(settings.base_url, None) is False
    assert service.ensure_started(settings.base_url, settings.state_dir, settings.deployment_id) is False
    assert service.service_status(settings)["managed"] is False
    assert native.calls == []
    assert not settings.state_dir.exists()
    with pytest.raises(DomainError) as denied:
        service.require_service_enabled(settings)
    assert denied.value.code == "SERVICE_NOT_INSTALLED"


def test_explicit_stop_finishes_delayed_native_removal_before_an_immediate_start(native, deployment, monkeypatch):
    settings, config = deployment
    service.install_service(settings, config)
    original = service.subprocess.run
    pending = {"target": None, "reads": 0}

    def delayed(argv, **options):
        arguments = argv[1:]
        if arguments[0] == "bootout":
            pending["target"] = arguments[1]
            native.calls.append(arguments)
            return subprocess.CompletedProcess(argv, 0, "", "")
        if arguments[0] == "print" and arguments[1] == pending["target"]:
            pending["reads"] += 1
            if pending["reads"] == 3:
                del native.jobs[pending["target"]]
                pending["target"] = None
        return original(argv, **options)

    monkeypatch.setattr(service.subprocess, "run", delayed)
    stopped = service.stop_service(settings)
    assert stopped["enabled"] is False and stopped["loaded"] is False
    assert receipt(settings)["enabled"] is False
    started = service.start_service(settings)
    assert started["enabled"] is True and started["running"] is True
    assert service.service_status(settings)["running"] is True


def test_recovery_only_bootstraps_missing_or_kickstarts_nonrunning(native, deployment):
    settings, config = deployment
    service.install_service(settings, config)
    target = next(iter(native.jobs))
    native.calls.clear()
    assert service.ensure_started(settings.base_url, settings.state_dir, settings.deployment_id)
    assert mutations(native) == []  # Live process may have an unavailable DB; never restart it.
    assert len(native.calls) == 1
    native.jobs[target]["running"] = False
    assert service.ensure_started(settings.base_url, settings.state_dir, settings.deployment_id)
    assert mutations(native) == [["kickstart", target]]
    del native.jobs[target]
    native.calls.clear()
    assert service.ensure_started(settings.base_url, settings.state_dir)
    assert mutations(native) == [["bootstrap", f"gui/{os.getuid()}", receipt(settings)["plist_path"]]]


def test_stop_intent_survives_native_failure(native, deployment):
    settings, config = deployment
    service.install_service(settings, config)
    native.fail = "disable"
    with pytest.raises(DomainError) as failed:
        service.stop_service(settings)
    assert failed.value.code == "SERVICE_CONTROL_FAILED"
    assert failed.value.effect == EffectState.COMMITTED
    assert "PRIVATE" not in failed.value.message
    assert receipt(settings)["enabled"] is False
    native.fail = None
    native.calls.clear()
    with pytest.raises(DomainError) as stopped:
        service.ensure_started(settings.base_url, settings.state_dir)
    assert stopped.value.code == "SERVICE_STOPPED"
    assert native.calls == []
    assert service.install_service(settings, config)["enabled"] is False
    assert service.start_service(settings)["enabled"] is True


def test_start_intent_survives_native_failure_and_explicit_retry(native, deployment):
    settings, config = deployment
    service.install_service(settings, config)
    service.stop_service(settings)
    native.fail = "enable"
    with pytest.raises(DomainError) as failed:
        service.start_service(settings)
    assert failed.value.code == "SERVICE_CONTROL_FAILED"
    assert failed.value.effect == EffectState.COMMITTED
    assert "PRIVATE" not in failed.value.message
    assert receipt(settings)["enabled"] is True
    assert not native.jobs
    native.fail = None
    assert service.start_service(settings)["running"] is True


@pytest.mark.parametrize("drift", ["config", "plist", "receipt", "receipt_uid_float", "duplicate_receipt_key", "public_config", "public_control", "symlink_plist", "symlink_config"])
def test_owned_drift_refuses_before_native_mutation(native, deployment, drift):
    settings, config = deployment
    service.install_service(settings, config)
    owned = receipt(settings)
    plist = Path(owned["plist_path"])
    if drift == "config":
        private_write(config, config.read_bytes() + b"\n", replace=True)
    elif drift == "plist":
        private_write(plist, plist.read_bytes() + b"\n", replace=True)
    elif drift == "receipt":
        owned["state_dir"] = str(native.home / "other")
        private_write(settings.state_dir / "service" / "receipt.json", json.dumps(owned), replace=True)
    elif drift == "receipt_uid_float":
        owned["uid"] = float(owned["uid"])
        private_write(settings.state_dir / "service" / "receipt.json", json.dumps(owned), replace=True)
    elif drift == "duplicate_receipt_key":
        private_write(settings.state_dir / "service" / "receipt.json", json.dumps(owned)[:-1] + ',"enabled":true}', replace=True)
    elif drift == "public_config":
        config.chmod(0o644)
    elif drift == "public_control":
        (settings.state_dir / "service").chmod(0o755)
    else:
        path = plist if drift == "symlink_plist" else config
        saved = path.with_suffix(".owned-copy")
        path.rename(saved)
        path.symlink_to(saved)
    native.calls.clear()
    for operation in (lambda: service.ensure_started(settings.base_url, settings.state_dir, settings.deployment_id),
                      lambda: service.stop_service(settings), lambda: service.uninstall_service(settings),
                      lambda: service.install_service(settings, config)):
        with pytest.raises(DomainError):
            operation()
    assert mutations(native) == []
    assert native.jobs


@pytest.mark.parametrize("endpoint,deployment_id", [("http://127.0.0.1:19999", "deployment_test"),
                                                      ("http://127.0.0.1:18768", "deployment_other")])
def test_readiness_scope_mismatch_never_controls_job(native, deployment, endpoint, deployment_id):
    settings, config = deployment
    service.install_service(settings, config)
    native.calls.clear()
    with pytest.raises(DomainError) as denied:
        service.ensure_started(endpoint, settings.state_dir, deployment_id)
    assert denied.value.code == "SERVICE_OWNERSHIP_INVALID"
    assert native.calls == []


def test_existing_foreign_plist_is_not_overwritten(native, deployment):
    settings, config = deployment
    path = service._plist_path(settings.state_dir, settings.deployment_id)
    private_write(path, "unrelated-plist")
    with pytest.raises(DomainError):
        service.install_service(settings, config)
    assert path.read_text() == "unrelated-plist"
    assert native.calls == []


def test_loaded_label_with_foreign_path_cannot_be_stopped(native, deployment):
    settings, config = deployment
    service.install_service(settings, config)
    next(iter(native.jobs.values()))["path"] = str(native.home / "foreign.plist")
    native.calls.clear()
    with pytest.raises(DomainError) as denied:
        service.stop_service(settings)
    assert denied.value.code == "SERVICE_OWNERSHIP_INVALID"
    assert receipt(settings)["enabled"] is True
    assert mutations(native) == []


def test_deployments_are_independently_scoped_even_with_same_identifier(native, deployment):
    first, first_config = deployment
    second = first.model_copy(update={"state_dir": native.home / "second-authority", "port": 18769})
    second_config = native.home / "second-config.json"
    private_write(second_config, second.model_dump_json())
    a = service.install_service(first, first_config)
    b = service.install_service(second, second_config)
    assert a["label"] != b["label"]
    second_receipt = receipt(second)
    service.stop_service(first)
    assert service.service_status(second)["running"] is True
    assert receipt(second) == second_receipt
    service.uninstall_service(first)
    assert service.ensure_started(second.base_url, second.state_dir, second.deployment_id)
    assert Path(second_receipt["plist_path"]).exists()
    assert len(native.jobs) == 1


def test_native_timeout_is_explicit_and_body_free(native, deployment, monkeypatch):
    settings, config = deployment
    service.install_service(settings, config)

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 2, output="PRIVATE_DATABASE_SECRET")

    monkeypatch.setattr(service.subprocess, "run", timeout)
    with pytest.raises(DomainError) as failed:
        service.ensure_started(settings.base_url, settings.state_dir)
    assert failed.value.code == "SERVICE_CONTROL_FAILED"
    assert "PRIVATE" not in failed.value.message


def test_native_install_rejects_other_platform(native, deployment, monkeypatch):
    settings, config = deployment
    monkeypatch.setattr(service.sys, "platform", "linux")
    with pytest.raises(DomainError) as denied:
        service.install_service(settings, config)
    assert denied.value.code == "SERVICE_UNSUPPORTED"
    assert native.calls == []


def test_dangling_control_symlink_is_not_unmanaged(native, deployment):
    settings, _ = deployment
    settings.state_dir.mkdir(mode=0o700)
    (settings.state_dir / "service").symlink_to(native.home / "absent")
    with pytest.raises(DomainError) as denied:
        service.ensure_started(settings.base_url, settings.state_dir)
    assert denied.value.code == "SERVICE_OWNERSHIP_INVALID"
    assert native.calls == []


def test_code_writable_by_another_user_refuses_recovery(native, deployment):
    settings, config = deployment
    service.install_service(settings, config)
    (native.package / "cli.py").chmod(0o666)
    native.calls.clear()
    with pytest.raises(DomainError) as denied:
        service.ensure_started(settings.base_url, settings.state_dir)
    assert denied.value.code == "SERVICE_OWNERSHIP_INVALID"
    assert native.calls == []


def test_foreign_receipt_uid_refuses_recovery(native, deployment):
    settings, config = deployment
    service.install_service(settings, config)
    owned = receipt(settings)
    owned["uid"] = os.getuid() + 1
    private_write(settings.state_dir / "service" / "receipt.json", json.dumps(owned), replace=True)
    native.calls.clear()
    with pytest.raises(DomainError):
        service.ensure_started(settings.base_url, settings.state_dir)
    assert native.calls == []


def test_unowned_loaded_label_cannot_be_adopted(native, deployment):
    settings, config = deployment
    label = service._label(settings.state_dir, settings.deployment_id)
    target = f"gui/{os.getuid()}/{label}"
    path = service._plist_path(settings.state_dir, settings.deployment_id)
    native.jobs[target] = {"path": str(path), "running": True}
    with pytest.raises(DomainError):
        service.install_service(settings, config)
    assert mutations(native) == []
    assert not path.exists()
    assert not (settings.state_dir / "service" / "receipt.json").exists()


@pytest.mark.parametrize("running", [True, False])
def test_simultaneous_readiness_reads_share_lock_and_singleflight_recovery(native, deployment, monkeypatch, running):
    settings, config = deployment
    service.install_service(settings, config)
    next(iter(native.jobs.values()))["running"] = running
    original_run = service.subprocess.run
    entered = threading.Barrier(2)
    count_lock = threading.Lock()
    prints = 0

    def concurrent_print(argv, **kwargs):
        nonlocal prints
        synchronize = False
        if argv[1] == "print":
            with count_lock:
                prints += 1
                synchronize = prints <= 2
        # Both initial read-only observations must coexist. Exclusive locking
        # either fails the other caller or strands the first at this barrier.
        if synchronize:
            result = original_run(argv, **kwargs)
            entered.wait(timeout=2)
            return result
        return original_run(argv, **kwargs)

    monkeypatch.setattr(service.subprocess, "run", concurrent_print)
    native.calls.clear()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(service.ensure_started, settings.base_url, settings.state_dir,
                               settings.deployment_id) for _ in range(2)]
        assert [future.result(timeout=4) for future in futures] == [True, True]
    expected = [] if running else [["kickstart", next(iter(native.jobs))]]
    assert mutations(native) == expected


def test_manual_stop_waits_for_shared_read_and_remains_exclusive(native, deployment, monkeypatch):
    settings, config = deployment
    service.install_service(settings, config)
    original_run = service.subprocess.run
    original_flock = service.fcntl.flock
    reading = threading.Event()
    release_reader = threading.Event()
    writer_waiting = threading.Event()

    def held_print(argv, **kwargs):
        if threading.current_thread().name.startswith("reader") and argv[1] == "print":
            reading.set()
            assert release_reader.wait(timeout=3)
        return original_run(argv, **kwargs)

    def observed_flock(fd, operation):
        if operation & service.fcntl.LOCK_EX and reading.is_set() and not release_reader.is_set():
            writer_waiting.set()
        return original_flock(fd, operation)

    monkeypatch.setattr(service.subprocess, "run", held_print)
    monkeypatch.setattr(service.fcntl, "flock", observed_flock)
    native.calls.clear()
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="reader") as readers:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="stopper") as writers:
            read = readers.submit(service.ensure_started, settings.base_url, settings.state_dir)
            try:
                assert reading.wait(timeout=2)
                stopped = writers.submit(service.stop_service, settings)
                assert writer_waiting.wait(timeout=2)
                assert receipt(settings)["enabled"] is True
                assert mutations(native) == []
            finally:
                release_reader.set()
            assert read.result(timeout=3) is True
            assert stopped.result(timeout=3)["enabled"] is False
    with pytest.raises(DomainError) as denied:
        service.ensure_started(settings.base_url, settings.state_dir)
    assert denied.value.code == "SERVICE_STOPPED"


def test_stop_winning_shared_to_exclusive_transition_blocks_recovery(native, deployment, monkeypatch):
    settings, config = deployment
    service.install_service(settings, config)
    next(iter(native.jobs.values()))["running"] = False
    original_locked = service._locked
    stop_on_release = True

    @contextlib.contextmanager
    def stop_between_locks(*args, **kwargs):
        nonlocal stop_on_release
        with original_locked(*args, **kwargs) as control:
            yield control
        if kwargs.get("shared") and stop_on_release:
            stop_on_release = False
            service.stop_service(settings)

    monkeypatch.setattr(service, "_locked", stop_between_locks)
    native.calls.clear()
    with pytest.raises(DomainError) as stopped:
        service.ensure_started(settings.base_url, settings.state_dir)
    assert stopped.value.code == "SERVICE_STOPPED"
    assert not any(call[0] in {"kickstart", "bootstrap", "enable"} for call in native.calls)


def test_recovery_native_calls_consume_one_absolute_deadline(native, deployment, monkeypatch):
    settings, config = deployment
    service.install_service(settings, config)
    next(iter(native.jobs.values()))["running"] = False
    original_run = service.subprocess.run
    clock = SimpleNamespace(now=100.0)
    timeouts = []

    def consuming_run(argv, **kwargs):
        timeouts.append(kwargs["timeout"])
        result = original_run(argv, **kwargs)
        clock.now += 0.3
        return result

    monkeypatch.setattr(service, "time", SimpleNamespace(monotonic=lambda: clock.now, sleep=lambda seconds: None))
    monkeypatch.setattr(service.subprocess, "run", consuming_run)
    native.calls.clear()
    with pytest.raises(DomainError) as expired:
        service.ensure_started(settings.base_url, settings.state_dir, deadline=101.0)
    assert expired.value.code == "SERVICE_CONTROL_FAILED"
    assert expired.value.effect == EffectState.NOT_STARTED
    assert timeouts == pytest.approx([1.0, 0.7, 0.4, 0.1])
    # The kickstart completed once; expiration never causes a mutation retry.
    assert len([call for call in mutations(native) if call[0] == "kickstart"]) == 1


def test_expired_deadline_never_queries_or_mutates_native_job(native, deployment, monkeypatch):
    settings, config = deployment
    service.install_service(settings, config)
    monkeypatch.setattr(service, "time", SimpleNamespace(monotonic=lambda: 50.0, sleep=lambda seconds: None))
    native.calls.clear()
    with pytest.raises(DomainError) as expired:
        service.ensure_started(settings.base_url, settings.state_dir, deadline=49.0)
    assert expired.value.code == "SERVICE_CONTROL_FAILED"
    assert native.calls == []


def test_contended_lock_deadline_is_control_failure_not_ownership_drift(native, deployment, monkeypatch):
    settings, config = deployment
    service.install_service(settings, config)
    clock = SimpleNamespace(now=10.0)

    def advance(seconds):
        clock.now += seconds

    monkeypatch.setattr(service, "time", SimpleNamespace(monotonic=lambda: clock.now, sleep=advance))
    native.calls.clear()
    with service._locked(settings.state_dir):
        with pytest.raises(DomainError) as busy:
            service.ensure_started(settings.base_url, settings.state_dir, deadline=10.025)
    assert busy.value.code == "SERVICE_CONTROL_FAILED"
    assert clock.now == pytest.approx(10.025)
    assert native.calls == []


@pytest.mark.parametrize("point", [
    "before_intent", "after_intent", "before_plist", "after_plist",
    "before_seal", "after_seal", "after_bootstrap",
])
def test_interrupted_install_resumes_owned_native_identity(native, deployment, monkeypatch, point):
    settings, config = deployment
    publish = service.private_write
    run = service.subprocess.run
    armed = True

    def interrupted_write(path, content, **options):
        nonlocal armed
        stage = "plist" if path.suffix == ".plist" else None
        if path.name == "receipt.json":
            stage = "intent" if json.loads(content)["state"] == "installing" else "seal"
        targeted = armed and point in {"before_" + str(stage), "after_" + str(stage)}
        if targeted and point.startswith("before_"):
            armed = False
            raise OSError("synthetic install interruption")
        result = publish(path, content, **options)
        if targeted:
            armed = False
            raise OSError("synthetic lost publication response")
        return result

    def interrupted_native(argv, **options):
        nonlocal armed
        result = run(argv, **options)
        if armed and point == "after_bootstrap" and argv[1] == "bootstrap":
            armed = False
            raise OSError("synthetic lost native response")
        return result

    with monkeypatch.context() as patcher:
        patcher.setattr(service, "private_write", interrupted_write)
        patcher.setattr(service.subprocess, "run", interrupted_native)
        with pytest.raises(DomainError) as interrupted:
            service.install_service(settings, config)
        assert interrupted.value.effect == (
            EffectState.UNKNOWN if point in {"before_intent", "after_intent"} else EffectState.COMMITTED
        )
    installed = service.install_service(settings, config)
    assert installed["enabled"] and installed["running"]
    assert service.service_status(settings)["running"]
    owned = receipt(settings)
    assert owned["state"] == "installed"
    assert next(iter(native.jobs.values()))["path"] == owned["plist_path"]
    assert service.uninstall_service(settings)["managed"] is False
    assert not native.jobs


@pytest.mark.parametrize("point", [
    "before_intent", "after_intent", "after_disable", "after_bootout",
    "before_plist_unlink", "after_plist_unlink",
    "before_receipt_unlink", "after_receipt_unlink",
])
def test_interrupted_uninstall_finishes_without_recreating_owned_files(native, deployment, monkeypatch, point):
    settings, config = deployment
    service.install_service(settings, config)
    owned = receipt(settings)
    plist_path = Path(owned["plist_path"])
    receipt_path = settings.state_dir / "service" / "receipt.json"
    publish, unlink, run = service.private_write, Path.unlink, service.subprocess.run
    armed = True

    def interrupted_write(path, content, **options):
        nonlocal armed
        if armed and point == "before_intent" and path == receipt_path:
            armed = False
            raise OSError("synthetic removal intent failure")
        result = publish(path, content, **options)
        if armed and point == "after_intent" and path == receipt_path:
            armed = False
            raise OSError("synthetic lost removal intent response")
        return result

    def interrupted_unlink(path, **options):
        nonlocal armed
        stage = "plist_unlink" if path == plist_path else "receipt_unlink" if path == receipt_path else None
        targeted = armed and point in {"before_" + str(stage), "after_" + str(stage)}
        if targeted and point.startswith("before_"):
            armed = False
            raise OSError("synthetic removal interruption")
        result = unlink(path, **options)
        if targeted:
            armed = False
            raise OSError("synthetic lost removal response")
        return result

    def interrupted_native(argv, **options):
        nonlocal armed
        result = run(argv, **options)
        if armed and point == "after_" + argv[1]:
            armed = False
            raise OSError("synthetic lost native stop response")
        return result

    with monkeypatch.context() as patcher:
        patcher.setattr(service, "private_write", interrupted_write)
        patcher.setattr(Path, "unlink", interrupted_unlink)
        patcher.setattr(service.subprocess, "run", interrupted_native)
        with pytest.raises(DomainError) as interrupted:
            service.uninstall_service(settings)
        assert interrupted.value.effect == (
            EffectState.UNKNOWN if point in {"before_intent", "after_intent"} else EffectState.COMMITTED
        )
    assert service.uninstall_service(settings)["managed"] is False
    assert not plist_path.exists() and not receipt_path.exists() and not native.jobs
    assert config.exists()


def test_explicit_stop_of_pending_install_prevents_replay_resurrection(native, deployment, monkeypatch):
    settings, config = deployment
    publish = service.private_write

    def before_native_file(path, content, **options):
        if path.suffix == ".plist":
            raise OSError("synthetic native file failure")
        return publish(path, content, **options)

    with monkeypatch.context() as patcher:
        patcher.setattr(service, "private_write", before_native_file)
        with pytest.raises(DomainError):
            service.install_service(settings, config)
    assert service.stop_service(settings)["enabled"] is False
    assert service.install_service(settings, config)["enabled"] is False
    with pytest.raises(DomainError) as stopped:
        service.ensure_started(settings.base_url, settings.state_dir, settings.deployment_id)
    assert stopped.value.code == "SERVICE_STOPPED"
    assert not native.jobs
    assert not Path(receipt(settings)["plist_path"]).exists()
    assert service.start_service(settings)["running"] is True


def test_pending_install_never_adopts_or_deletes_replaced_native_file(native, deployment, monkeypatch):
    settings, config = deployment
    publish = service.private_write

    def before_native_file(path, content, **options):
        if path.suffix == ".plist":
            raise OSError("synthetic native file failure")
        return publish(path, content, **options)

    with monkeypatch.context() as patcher:
        patcher.setattr(service, "private_write", before_native_file)
        with pytest.raises(DomainError):
            service.install_service(settings, config)
    target = Path(receipt(settings)["plist_path"])
    private_write(target, b"foreign native content")
    for action in (lambda: service.install_service(settings, config), lambda: service.uninstall_service(settings)):
        with pytest.raises(DomainError) as denied:
            action()
        assert denied.value.code == "SERVICE_OWNERSHIP_INVALID"
        assert denied.value.effect == EffectState.NOT_STARTED
        assert target.read_bytes() == b"foreign native content"
    assert not native.jobs


def test_native_decoding_failure_stays_body_free_and_typed(native, deployment, monkeypatch):
    settings, config = deployment
    service.install_service(settings, config)

    def invalid_output(*arguments, **options):
        raise UnicodeDecodeError("utf-8", b"PRIVATE_NATIVE\xff", 14, 15, "invalid")

    monkeypatch.setattr(service.subprocess, "run", invalid_output)
    with pytest.raises(DomainError) as denied:
        service.service_status(settings)
    assert denied.value.code == "SERVICE_CONTROL_FAILED"
    assert "PRIVATE_NATIVE" not in str(denied.value)


@pytest.mark.parametrize("pending", [False, True])
def test_install_activation_refusal_reports_its_durable_intent(native, deployment, pending):
    settings, config = deployment
    native.fail = "bootstrap"
    if pending:
        with pytest.raises(DomainError):
            service.install_service(settings, config)
        assert receipt(settings)["state"] == "installing"
    with pytest.raises(DomainError) as refused:
        service.install_service(settings, config)
    assert refused.value.code == "SERVICE_CONTROL_FAILED"
    assert refused.value.effect == EffectState.COMMITTED
    owned = receipt(settings)
    assert owned["enabled"] is True and owned["state"] == "installing"
    assert Path(owned["plist_path"]).is_file()
    native.fail = None
    assert service.install_service(settings, config)["running"] is True


def test_existing_enabled_install_activation_refusal_preserves_committed_intent(native, deployment):
    settings, config = deployment
    service.install_service(settings, config)
    next(iter(native.jobs.values()))["running"] = False
    native.fail = "kickstart"
    with pytest.raises(DomainError) as refused:
        service.install_service(settings, config)
    assert refused.value.code == "SERVICE_CONTROL_FAILED"
    assert refused.value.effect == EffectState.COMMITTED
    assert receipt(settings)["enabled"] is True and receipt(settings)["state"] == "installed"
    native.fail = None
    assert service.install_service(settings, config)["running"] is True


def test_control_config_preserves_the_explicit_legacy_upgrade_refusal(native, deployment):
    settings, config = deployment
    legacy = settings.model_dump(mode="json")
    legacy["capability"] = "lexical_entity"
    private_write(config, json.dumps(legacy), replace=True)
    with pytest.raises(DomainError) as refused:
        service.load_control_settings(config)
    assert refused.value.code == "CONFIG_UPGRADE_REQUIRED"
    assert refused.value.effect == EffectState.NOT_STARTED
    assert not settings.state_dir.exists() and native.calls == []
