from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from test_readiness import endpoint as endpoint
from test_remote_client import tls_endpoint as tls_endpoint

from agents_memory import hosts
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
    clock = SimpleNamespace(now=0.0)
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
