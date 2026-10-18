from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from test_readiness import endpoint as endpoint
from test_remote_client import tls_endpoint as tls_endpoint

from agents_memory import hosts
from agents_memory import recovery as recovery_module
from agents_memory.config import Settings
from agents_memory.domain import CaptureCommand, DomainError
from agents_memory.private_io import private_write
from agents_memory.recovery import SpoolRecovery
from agents_memory.spool import ProducerSpool


class ProbeStore:
    def __init__(self, settings, state):
        self.settings, self.state = settings, state
        self.probes = 0

    async def readiness(self):
        self.probes += 1
        return {"ready": self.state["db_ready"]}


@pytest.fixture
def installed(tmp_path, monkeypatch, endpoint, request):
    url, state = endpoint
    project = tmp_path / "project"
    project.mkdir()
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    monkeypatch.setenv("HOME", str(home))
    host = getattr(request, "param", "omp")
    if host == "claude":
        native = tmp_path / "private-claude"
        native.mkdir(mode=0o700)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(native))
    settings = Settings(
        deployment_id="local-owned", realm="personal", mode="personal", database_dsn="postgresql://unused",
        state_dir=tmp_path / "state", journal_dir=tmp_path / "journal", port=urlsplit(url).port,
    )
    settings.state_dir.mkdir(mode=0o700)
    tokens = []
    for name in ("agent", "producer"):
        token = tmp_path / f"{name}.token"
        token.write_text(f"synthetic-{name}-credential")
        token.chmod(0o600)
        tokens.append(token)
    path = Path(hosts.install_host(settings, project, "binding-one", host, *tokens)["receipt"])
    (settings.state_dir / "host-adapters").chmod(0o755)
    receipt = hosts.load_receipt(path)
    command = CaptureCommand(binding_id="binding-one", idempotency_key="preserved-key", origin_key="preserved-origin",
                             speaker="human", body="An exact observed source preserved during service outage.")
    spool = ProducerSpool(Path(receipt["runtime_dir"]) / "capture.sqlite3", settings.deployment_id, "binding-one", settings.spool_limit_bytes)
    try:
        spool.enqueue(command)
    finally:
        spool.close()
    return settings, path, receipt, command, state


def status(settings, receipt):
    spool = ProducerSpool(Path(receipt["runtime_dir"]) / "capture.sqlite3", settings.deployment_id, "binding-one", settings.spool_limit_bytes)
    try:
        return spool.status()
    finally:
        spool.close()


async def eventually(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0.01)


async def test_preserved_capture_flushes_after_db_recovers_without_host_event(installed):
    settings, _, receipt, command, state = installed
    state.update(ready=False, db_ready=False)
    store = ProbeStore(settings, state)
    worker = SpoolRecovery(settings, store, interval=0.01)
    worker.start()
    try:
        await eventually(lambda: store.probes > 0)
        assert state["posts"] == [] and status(settings, receipt)["pending"] == 1
        state.update(ready=True, db_ready=True)
        await eventually(lambda: len(state["posts"]) == 1)
        await worker.stop()
        assert status(settings, receipt)["pending"] == 0
        assert state["posts"] == [("/api/capture", command.model_dump(mode="json"))]
    finally:
        await worker.stop()


@pytest.mark.parametrize("stage", ["readiness", "workspace"])
async def test_owner_loop_recovers_after_unexpected_failure_without_new_host_event(installed, monkeypatch, stage):
    settings, _, receipt, command, state = installed
    state.update(ready=True, db_ready=True)
    store = ProbeStore(settings, state)
    worker = SpoolRecovery(settings, store, interval=0.01)
    failed = threading.Event()
    next_probe, release = asyncio.Event(), asyncio.Event()
    readiness, observation = store.readiness, recovery_module.observe_health_workspace
    marker = "SYNTHETIC_PRIVATE_RECOVERY_PATH_DSN"

    async def controlled_readiness():
        if failed.is_set():
            next_probe.set()
            await release.wait()
        elif stage == "readiness":
            failed.set()
            raise RuntimeError(marker)
        return await readiness()

    def controlled_observation(*args, **kwargs):
        if not failed.is_set():
            failed.set()
            raise RuntimeError(marker)
        return observation(*args, **kwargs)

    monkeypatch.setattr(store, "readiness", controlled_readiness)
    if stage == "workspace":
        monkeypatch.setattr(recovery_module, "observe_health_workspace", controlled_observation)
    worker.start()
    try:
        await asyncio.wait_for(next_probe.wait(), 5)
        degraded = worker.status
        assert degraded["state"] == "delivery_blocked" and degraded["failures"] == 1
        assert degraded["last_error"] == "HOST_RECOVERY_UNAVAILABLE" and marker not in str(degraded)
        assert state["posts"] == [] and status(settings, receipt)["pending"] == 1
        release.set()
        await eventually(lambda: worker.status["committed"] == 1)
        await worker.stop()
        assert state["posts"] == [("/api/capture", command.model_dump(mode="json"))]
        assert status(settings, receipt)["pending"] == 0
    finally:
        release.set()
        await asyncio.gather(worker.stop(), return_exceptions=True)


async def test_unexpected_failure_after_committed_cycle_does_not_resend_capture(installed, monkeypatch):
    settings, _, receipt, command, state = installed
    state.update(ready=True, db_ready=True)
    store = ProbeStore(settings, state)
    worker = SpoolRecovery(settings, store, interval=0.01)
    cycle = worker.cycle
    failed = threading.Event()

    def committed_then_failed():
        cycle()
        if not failed.is_set():
            failed.set()
            raise RuntimeError("SYNTHETIC_PRIVATE_POST_COMMIT_RECOVERY_PATH")

    monkeypatch.setattr(worker, "cycle", committed_then_failed)
    worker.start()
    try:
        await eventually(lambda: store.probes >= 2 and worker.status["cycles"] >= 2)
        await worker.stop()
        assert worker.status["failures"] == 1
        assert state["posts"] == [("/api/capture", command.model_dump(mode="json"))]
        assert status(settings, receipt)["pending"] == 0
    finally:
        await asyncio.gather(worker.stop(), return_exceptions=True)


async def test_cancelled_stop_waiter_retains_join_ownership_of_active_recovery_thread(installed, monkeypatch):
    settings, _, receipt, _, state = installed
    state.update(ready=True, db_ready=True)
    worker = SpoolRecovery(settings, ProbeStore(settings, state), interval=0.01)
    entered, release = threading.Event(), threading.Event()
    observation = recovery_module.observe_health_workspace
    stopping = joining = None

    def held_observation(*args, **kwargs):
        entered.set()
        if not release.wait(5):
            raise TimeoutError("The regression must release its owned delivery thread")
        return observation(*args, **kwargs)

    monkeypatch.setattr(recovery_module, "observe_health_workspace", held_observation)
    worker.start()
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        stopping = asyncio.create_task(worker.stop())
        await asyncio.sleep(0)
        stopping.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stopping
        joining = asyncio.create_task(worker.wait_closed())
        await asyncio.sleep(0)
        assert not joining.done()
        assert worker.status["state"] != "stopped"
        release.set()
        await asyncio.wait_for(joining, 5)
        await worker.stop()
        assert worker.status["state"] == "stopped"
        assert state["posts"] == [] and status(settings, receipt)["pending"] == 1
    finally:
        release.set()
        await asyncio.gather(*(task for task in (stopping, joining) if task is not None),
            worker.stop(), return_exceptions=True)


@pytest.mark.parametrize("installed", ["claude"], indirect=True)
async def test_claude_outbox_delivers_without_the_installers_native_config_environment(installed, monkeypatch):
    settings, _, receipt, command, state = installed
    monkeypatch.delenv("CLAUDE_CONFIG_DIR")
    worker = SpoolRecovery(settings, ProbeStore(settings, state), interval=0.01)
    worker.start()
    try:
        await eventually(lambda: status(settings, receipt)["pending"] == 0)
        await worker.stop()
        assert state["posts"] == [("/api/capture", command.model_dump(mode="json"))]
    finally:
        await worker.stop()


def test_unknown_capture_receipt_reuses_original_stable_key(installed):
    settings, _, receipt, command, state = installed
    worker = SpoolRecovery(settings, ProbeStore(settings, state))
    state["disconnect"] = True
    worker.cycle()
    assert status(settings, receipt)["pending"] == 1
    state["disconnect"] = False
    worker.cycle()
    assert status(settings, receipt)["pending"] == 0
    assert state["posts"] == [("/api/capture", command.model_dump(mode="json"))] * 2


@pytest.mark.parametrize("change", ["removed", "realm", "deployment_id", "base_url", "runtime_dir", "native_drift", "receipt_drift"])
def test_removed_invalid_drifted_or_foreign_receipts_are_not_delivered(installed, change):
    settings, path, receipt, _, state = installed
    document = dict(receipt)
    if change == "removed":
        document["state"] = "removed"
    elif change == "native_drift":
        owned = next(entry for entry in receipt["ownership"] if entry["kind"] == "file")
        (Path(receipt["project_root"]) / owned["path"]).write_text("changed native extension")
    elif change == "receipt_drift":
        path.write_text(path.read_text().replace("preserved", "changed") + "invalid")
    else:
        document[change] = str(settings.state_dir / "foreign-runtime") if change == "runtime_dir" else "foreign"
    if change not in {"native_drift", "receipt_drift"}:
        hosts._write_receipt(path, document)
    worker = SpoolRecovery(settings, ProbeStore(settings, state))
    for _ in range(4):
        worker.cycle()
    assert state["posts"] == []
    assert status(settings, receipt)["pending"] == 1


def test_manual_stop_preserves_spool_even_with_healthy_db_and_old_process(installed, monkeypatch):
    settings, _, receipt, _, state = installed

    def stopped(*args, **kwargs):
        raise DomainError("SERVICE_STOPPED", "Explicit stop", status=503)

    monkeypatch.setattr("agents_memory.service.ensure_started", stopped)
    worker = SpoolRecovery(settings, ProbeStore(settings, state))
    worker.cycle()
    assert state["posts"] == [] and state["gets"] == 0
    assert status(settings, receipt)["pending"] == 1


async def test_stop_drains_delivery_and_prevents_subsequent_cycles(installed):
    settings, _, receipt, _, state = installed
    store = ProbeStore(settings, state)
    state.update(ready=False, db_ready=False)
    worker = SpoolRecovery(settings, store, interval=0.01)
    worker.start()
    await eventually(lambda: store.probes > 0)
    await worker.stop()
    state.update(ready=True, db_ready=True)
    await asyncio.sleep(0.03)
    assert state["posts"] == [] and status(settings, receipt)["pending"] == 1


def test_recovery_bounds_each_receipt_and_leaves_remaining_rows_for_next_cycle(installed):
    settings, _, receipt, command, state = installed
    spool = ProducerSpool(Path(receipt["runtime_dir"]) / "capture.sqlite3", settings.deployment_id, "binding-one", settings.spool_limit_bytes)
    try:
        for index in range(6):
            spool.enqueue(command.model_copy(update={"idempotency_key": f"key-{index}", "origin_key": f"origin-{index}"}))
    finally:
        spool.close()
    worker = SpoolRecovery(settings, ProbeStore(settings, state), flush_limit=2)
    worker.cycle()
    assert len(state["posts"]) == 2 and status(settings, receipt)["pending"] == 5
    worker.cycle()
    assert len(state["posts"]) == 4 and status(settings, receipt)["pending"] == 3


def test_invalid_receipts_do_not_starve_other_installed_hosts(installed):
    settings, path, receipt, command, state = installed
    project = Path(receipt["project_root"]).with_name("second-project")
    project.mkdir()
    second = Path(hosts.install_host(
        settings, project, "binding-one", "omp", Path(receipt["agent_token_file"]), Path(receipt["producer_token_file"]),
    )["receipt"])
    valid = hosts.load_receipt(second)
    spool = ProducerSpool(Path(valid["runtime_dir"]) / "capture.sqlite3", settings.deployment_id, "binding-one", settings.spool_limit_bytes)
    try:
        spool.enqueue(command.model_copy(update={"idempotency_key": "second-key", "origin_key": "second-origin"}))
    finally:
        spool.close()
    path.write_text("invalid owned receipt")
    worker = SpoolRecovery(settings, ProbeStore(settings, state), receipts_per_cycle=1)
    for _ in range(20):
        worker.cycle()
    assert status(settings, receipt)["pending"] == 1
    assert status(settings, valid)["pending"] == 0
    assert [payload["idempotency_key"] for _, payload in state["posts"]] == ["second-key"]


@pytest.mark.parametrize("unsafe", ["state_public", "intermediate_writable", "receipt_public", "runtime_public", "intermediate_symlink"])
def test_recovery_rejects_unsafe_ancestors_and_leaves_without_delivery(installed, unsafe):
    settings, path, receipt, _, state = installed
    root = settings.state_dir / "host-adapters"
    if unsafe == "state_public":
        settings.state_dir.chmod(0o755)
    elif unsafe == "intermediate_writable":
        root.chmod(0o777)
    elif unsafe == "receipt_public":
        path.parent.chmod(0o755)
    elif unsafe == "runtime_public":
        Path(receipt["runtime_dir"]).chmod(0o755)
    else:
        moved = settings.state_dir / "moved-adapters"
        root.rename(moved)
        root.symlink_to(moved, target_is_directory=True)
    worker = SpoolRecovery(settings, ProbeStore(settings, state))
    worker.cycle()
    assert state["posts"] == []
    assert worker.status["last_error"] == "HOST_PATH_DENIED"
    assert worker.status["failures"] >= 1
    assert receipt["project_root"] not in str(worker.status)


def test_recovery_preserves_failure_until_a_new_cycle_finishes(installed, monkeypatch):
    settings, _, receipt, _, state = installed
    root = settings.state_dir / "host-adapters"
    root.chmod(0o777)
    worker = SpoolRecovery(settings, ProbeStore(settings, state))
    worker.cycle()
    assert worker.status["state"] == "discovery_failed"
    assert worker.status["last_error"] == "HOST_PATH_DENIED"
    entered, release = threading.Event(), threading.Event()
    errors = []
    discover = worker._discover

    def blocked_discovery():
        entered.set()
        if not release.wait(5):
            raise TimeoutError("The recovery diagnostic observation was not released")
        return discover()

    def cycle():
        try:
            worker.cycle()
        except BaseException as error:
            errors.append(error)

    monkeypatch.setattr(worker, "_discover", blocked_discovery)
    thread = threading.Thread(target=cycle)
    thread.start()
    try:
        assert entered.wait(5)
        observed = worker.status
        assert observed["state"] == "discovery_failed"
        assert observed["last_error"] == "HOST_PATH_DENIED"
        assert observed["failures"] == 1
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive() and errors == []
    assert worker.status["state"] == "discovery_failed"
    assert worker.status["failures"] == 2
    root.chmod(0o755)
    state.update(ready=True, db_ready=True)
    worker.cycle()
    recovered = worker.status
    assert recovered["state"] == "idle" and recovered["last_error"] is None
    assert recovered["failures"] == 2 and recovered["committed"] == 1
    assert status(settings, receipt)["pending"] == 0


def test_absent_host_receipts_are_idle_not_recovery_failures(installed):
    settings, path, _, _, state = installed
    path.unlink()
    worker = SpoolRecovery(settings, ProbeStore(settings, state))
    worker.cycle()
    assert worker.status == {"state": "idle", "cycles": 1, "committed": 0, "failures": 0, "last_error": None}
    assert state["posts"] == []


@pytest.fixture
def remote_installed(tmp_path, monkeypatch, tls_endpoint):
    settings = tls_endpoint.profile
    project = tmp_path / "remote-project"
    project.mkdir(mode=0o700)
    home = tmp_path / "remote-home"
    home.mkdir(mode=0o700)
    monkeypatch.setenv("HOME", str(home))
    producer = tmp_path / "producer.token"
    private_write(producer, "synthetic-producer-credential\n")
    path = Path(hosts.install_host(
        settings, project, "binding-one", "omp", tls_endpoint.token, producer,
    )["receipt"])
    receipt = hosts.load_receipt(path)
    command = CaptureCommand(
        binding_id="binding-one", idempotency_key="remote-preserved", origin_key="remote-preserved",
        speaker="human", body="A remote capture must survive a slow approved TLS authority.",
    )
    spool = ProducerSpool(
        Path(receipt["runtime_dir"]) / "capture.sqlite3", settings.deployment_id,
        "binding-one", settings.spool_limit_bytes,
    )
    try:
        spool.enqueue(command)
    finally:
        spool.close()
    return settings, receipt, command, tls_endpoint.state


async def test_slow_remote_recovery_drains_without_a_new_host_event(remote_installed):
    settings, receipt, command, state = remote_installed
    state["post_delay"] = 1.2
    worker = SpoolRecovery(settings, None, interval=0.01)
    worker.start()
    try:
        await eventually(lambda: status(settings, receipt)["pending"] == 0)
    finally:
        await worker.stop()
    assert [body for route, body, _ in state["posts"] if route == "/api/capture"] == [command.model_dump(mode="json")]
    assert worker.status["committed"] == 1


async def test_remote_stop_keeps_unknown_capture_and_prevents_following_dispatch(remote_installed):
    settings, receipt, command, state = remote_installed
    state["post_delay"] = 1.2
    state["disconnect"] = True
    spool = ProducerSpool(
        Path(receipt["runtime_dir"]) / "capture.sqlite3", settings.deployment_id,
        "binding-one", settings.spool_limit_bytes,
    )
    try:
        spool.enqueue(command.model_copy(update={"idempotency_key": "following", "origin_key": "following"}))
    finally:
        spool.close()
    worker = SpoolRecovery(settings, None, interval=0.01)
    worker.start()
    try:
        await eventually(lambda: bool(state["posts"]))
        await worker.stop()
    finally:
        await worker.stop()
    assert status(settings, receipt)["pending"] == 2
    assert len(state["posts"]) == 1
    assert state["posts"][0][1]["idempotency_key"] == command.idempotency_key
    assert worker.status["state"] == "stopped"


def test_remote_receipts_share_one_finite_delivery_cycle(remote_installed, monkeypatch):
    from types import SimpleNamespace

    from agents_memory import recovery

    settings, receipt, command, state = remote_installed
    spool = ProducerSpool(
        Path(receipt["runtime_dir"]) / "capture.sqlite3", settings.deployment_id,
        "binding-one", settings.spool_limit_bytes,
    )
    try:
        for key in ("second", "third"):
            spool.enqueue(command.model_copy(update={"idempotency_key": key, "origin_key": key}))
    finally:
        spool.close()
    clock = SimpleNamespace(now=recovery.time.monotonic())
    monkeypatch.setattr(recovery, "time", SimpleNamespace(monotonic=lambda: clock.now))
    request = recovery.LocalClient.request

    def slow_delivery(self, route, payload):
        result = request(self, route, payload)
        clock.now += 11
        return result

    monkeypatch.setattr(recovery.LocalClient, "request", slow_delivery)
    worker = SpoolRecovery(settings, None)
    worker.cycle()
    assert status(settings, receipt)["pending"] == 1
    assert [body["idempotency_key"] for _, body, _ in state["posts"]] == [command.idempotency_key, "second"]
    assert worker.status["last_error"] == "SERVICE_UNAVAILABLE"


async def test_empty_remote_spool_never_probes_authority(remote_installed):
    settings, receipt, _, state = remote_installed
    worker = SpoolRecovery(settings, None)
    worker.cycle()
    assert status(settings, receipt)["pending"] == 0
    state["gets"].clear()
    delivered = list(state["posts"])
    idle = SpoolRecovery(settings, None, interval=0.01)
    idle.start()
    try:
        await eventually(lambda: idle.status["cycles"] >= 3)
    finally:
        await idle.stop()
    assert state["gets"] == []
    assert state["posts"] == delivered


@pytest.mark.parametrize("jitter,delays", [
    (0.8, [1.6, 3.2, 6.4, 12.8, 25.6, 51.2, 51.2]),
    (1.2, [2.4, 4.8, 9.6, 19.2, 38.4, 60, 60]),
])
def test_pending_remote_failures_back_off_across_cycles_and_reset_after_delivery(
    remote_installed, monkeypatch, jitter, delays,
):
    from types import SimpleNamespace

    from agents_memory import recovery

    settings, receipt, command, state = remote_installed
    path = hosts._receipt_path(settings, Path(receipt["project_root"]), receipt["host"])
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(recovery, "time", SimpleNamespace(monotonic=lambda: clock.now))
    monkeypatch.setattr(recovery.random, "uniform", lambda low, high: jitter)
    attempts = []
    available = False

    def readiness(*args, **kwargs):
        attempts.append(clock.now)
        if not available:
            raise DomainError("SERVICE_UNAVAILABLE", "Synthetic authority is offline", status=503)
        return {"ready": True}

    monkeypatch.setattr(recovery, "ensure_remote_ready", readiness)
    monkeypatch.setattr(recovery.LocalClient, "request", lambda *args: {"id": "validated-ack", "effect": "committed"})
    worker = SpoolRecovery(settings, None)
    monkeypatch.setattr(worker, "_discover", lambda: [path])
    for index, delay in enumerate(delays, start=1):
        worker.cycle()
        assert len(attempts) == index
        assert status(settings, receipt)["pending"] == 1
        clock.now += delay - 0.01
        worker.cycle()
        assert len(attempts) == index
        assert worker.status["state"] == "waiting_remote"
        assert worker.status["last_error"] == "SERVICE_UNAVAILABLE"
        clock.now += 0.02
    available = True
    worker.cycle()
    assert len(attempts) == len(delays) + 1
    assert status(settings, receipt)["pending"] == 0
    assert worker.status["committed"] == 1
    worker.cycle()
    assert len(attempts) == len(delays) + 1
    spool = ProducerSpool(
        Path(receipt["runtime_dir"]) / "capture.sqlite3", settings.deployment_id,
        "binding-one", settings.spool_limit_bytes,
    )
    try:
        spool.enqueue(command.model_copy(update={"idempotency_key": "new-pending", "origin_key": "new-pending"}))
    finally:
        spool.close()
    available = False
    worker.cycle()
    assert len(attempts) == len(delays) + 2
    clock.now += 2 * jitter - 0.01
    worker.cycle()
    assert len(attempts) == len(delays) + 2
    clock.now += 0.02
    worker.cycle()
    assert len(attempts) == len(delays) + 3
    assert status(settings, receipt)["pending"] == 1
    assert state["gets"] == [] and state["posts"] == []


def test_invalid_remote_receipt_is_not_permission_to_probe(remote_installed):
    settings, receipt, _, state = remote_installed
    owned = next(entry for entry in receipt["ownership"] if entry["kind"] == "file")
    (Path(receipt["project_root"]) / owned["path"]).write_text("changed native extension")
    worker = SpoolRecovery(settings, None)
    worker.cycle()
    assert worker.status["last_error"] == "HOST_OWNERSHIP_DRIFT"
    assert status(settings, receipt)["pending"] == 1
    assert state["gets"] == [] and state["posts"] == []


async def test_remote_stop_interrupts_dns_and_reaps_helper_without_dispatch(remote_installed, monkeypatch):
    import subprocess
    import sys
    import threading

    from agents_memory import connection

    settings, receipt, _, state = remote_installed
    started = threading.Event()
    processes = []
    spawn = subprocess.Popen

    def blocked_helper(argv, **options):
        process = spawn(
            [sys.executable, "-I", "-S", "-c", "import time; time.sleep(30)"], **options,
        )
        processes.append(process)
        started.set()
        return process

    monkeypatch.setattr(connection.subprocess, "Popen", blocked_helper)
    worker = SpoolRecovery(settings, None)
    worker.start()
    try:
        assert await asyncio.wait_for(asyncio.to_thread(started.wait, 5), timeout=6)
        await asyncio.wait_for(worker.stop(), timeout=1)
        assert processes and all(process.poll() is not None for process in processes)
    finally:
        await worker.stop()
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait()
    assert worker.status["state"] == "stopped"
    assert status(settings, receipt)["pending"] == 1
    assert state["gets"] == [] and state["posts"] == []


@pytest.mark.parametrize("interruption", [None, "budget", "readiness"])
def test_remote_bad_first_outbox_cannot_starve_retained_healthy_batch(
    remote_installed, monkeypatch, interruption,
):
    from types import SimpleNamespace

    from agents_memory import recovery

    settings, bad, command, state = remote_installed
    project = Path(bad["project_root"]).with_name("healthy-project")
    project.mkdir(mode=0o700)
    producer = project / "producer.token"
    private_write(producer, "synthetic-healthy-producer\n")
    healthy_path = Path(hosts.install_host(
        settings, project, "binding-one", "omp", Path(bad["agent_token_file"]), producer,
    )["receipt"])
    healthy = hosts.load_receipt(healthy_path)
    spool = ProducerSpool(
        Path(healthy["runtime_dir"]) / "capture.sqlite3", settings.deployment_id,
        "binding-one", settings.spool_limit_bytes,
    )
    try:
        spool.enqueue(command.model_copy(update={"idempotency_key": "healthy-key", "origin_key": "healthy-origin"}))
    finally:
        spool.close()
    state["denied_producers"] = {"Bearer synthetic-producer-credential"}
    root = settings.state_dir / "host-adapters"
    bad_directory = hosts._receipt_path(settings, Path(bad["project_root"]), bad["host"]).parent.name
    scandir = recovery.os.scandir

    def bad_first(path):
        entries = scandir(path)
        if path != root:
            return entries
        with entries:
            ordered = sorted(entries, key=lambda entry: entry.name != bad_directory)
        return (entry for entry in ordered)

    monkeypatch.setattr(recovery.os, "scandir", bad_first)
    clock = SimpleNamespace(now=recovery.time.monotonic())
    monkeypatch.setattr(recovery, "time", SimpleNamespace(monotonic=lambda: clock.now))
    worker = SpoolRecovery(settings, None)
    try:
        if interruption == "budget":
            worker.cycle(deadline=clock.now - 1)
            assert state["posts"] == []
        elif interruption == "readiness":
            with monkeypatch.context() as patch:
                def unavailable(*args, **kwargs):
                    raise DomainError("SERVICE_UNAVAILABLE", "Synthetic readiness outage", status=503)
                patch.setattr(recovery, "ensure_remote_ready", unavailable)
                worker.cycle()
            assert state["posts"] == []
            assert worker.status["last_error"] == "SERVICE_UNAVAILABLE"
            clock.now += 61
        worker.cycle()
        assert [body["idempotency_key"] for _, body, _ in state["posts"]] == [command.idempotency_key]
        assert status(settings, bad)["pending"] == status(settings, healthy)["pending"] == 1
        assert worker.status["last_error"] == "AUTH_DENIED"
        failures = worker.status["failures"]
        worker.cycle()
        assert worker.status["state"] == "waiting_remote"
        assert worker.status["last_error"] == "AUTH_DENIED"
        assert len(state["posts"]) == 1
        clock.now += 61
        worker.cycle()
        assert status(settings, bad)["pending"] == 1
        assert status(settings, bad)["quarantined"] == 0
        assert status(settings, healthy)["pending"] == 0
        assert [body["idempotency_key"] for _, body, _ in state["posts"]] == [
            command.idempotency_key, "healthy-key",
        ]
        assert worker.status["committed"] == 1
        assert worker.status["failures"] == failures
    finally:
        if worker._scan is not None:
            worker._scan.close()
