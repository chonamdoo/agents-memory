from __future__ import annotations

import asyncio
import fcntl
import os
import random
import re
import signal
import sqlite3
import stat
import threading
import time
from collections import deque
from contextlib import contextmanager, suppress
from pathlib import Path

from . import hosts
from .client import LocalClient
from .connection import RemoteClientSettings, remote_connection_cycle
from .domain import DomainError, EffectState
from .health_producer import load_health_workspace, observe_health_workspace
from .private_io import private_read
from .readiness import ensure_remote_ready
from .spool import ProducerSpool, require_supported_sqlite


def _directory(path: Path, *, private: bool) -> None:
    info = path.lstat()
    forbidden = 0o077 if private else 0o022
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & forbidden:
        raise DomainError("HOST_PATH_DENIED", "Recovery requires owned safe directories and private leaves")


def _receipt(settings, path: Path) -> dict:
    # Discovery is not authority: recheck installation identity and owned native entries.
    private_read(path, 65536)
    receipt = hosts.load_receipt(path)
    root = Path(receipt["project_root"])
    if (receipt["deployment_id"] != settings.deployment_id or receipt["realm"] != settings.realm
            or receipt["base_url"] != settings.base_url
            or root.resolve(strict=True) != root or not root.is_dir()
            or path != hosts._receipt_path(settings, root, receipt["host"])
            or Path(receipt["runtime_dir"]) != hosts._runtime_dir(settings, root, receipt["binding_id"], receipt["host"])):
        raise DomainError("HOST_RECEIPT_INVALID", "Recovery does not own this deployment receipt")
    remote = hosts.receipt_connection(receipt)
    if (remote is not None and remote != settings) or (remote is None and isinstance(settings, RemoteClientSettings)):
        raise DomainError("HOST_RECEIPT_INVALID", "Recovery does not own this remote connection")
    _directory(path.parent, private=True)
    _directory(Path(receipt["runtime_dir"]), private=True)
    if not all(hosts._owned_entry_matches(root, entry) for entry in receipt["ownership"]):
        raise DomainError("HOST_OWNERSHIP_DRIFT", "The installed native entries changed")
    return receipt


class SpoolRecovery:
    """Bounded, fair delivery of installed host outboxes, independent of new events."""

    def __init__(self, settings, store, *, interval: float = 2, receipts_per_cycle: int = 8, flush_limit: int = 4):
        if interval <= 0 or not 1 <= receipts_per_cycle <= 32 or not 1 <= flush_limit <= 128:
            raise ValueError("Recovery requires bounded positive limits")
        self.settings, self.store = settings, store
        self.interval, self.receipts_per_cycle, self.flush_limit = interval, receipts_per_cycle, flush_limit
        self._stop = threading.Event()
        self._wake = asyncio.Event()
        self._task = None
        self._cycle_lock = threading.Lock()
        self._status_lock = threading.RLock()
        self._scan = None
        self._pending = deque()
        self._remote_failures = 0
        self._remote_retry_at = 0.0
        self._status = {"state": "idle", "cycles": 0, "committed": 0, "failures": 0, "last_error": None}

    @property
    def status(self) -> dict:
        with self._status_lock:
            return dict(self._status)

    def _report(self, **changes) -> None:
        with self._status_lock:
            self._status = {**self._status, **changes}

    def _failure(self, error, *, state: str = "delivery_blocked") -> None:
        code = error.code if isinstance(error, DomainError) else error if isinstance(error, str) else "HOST_RECOVERY_UNAVAILABLE"
        if re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", code) is None:
            code = "HOST_RECOVERY_UNAVAILABLE"
        with self._status_lock:
            self._report(state=state, failures=self._status["failures"] + 1, last_error=code)

    def _defer_remote(self) -> None:
        self._remote_failures += 1
        delay = min(60, 2 ** min(self._remote_failures, 6) * random.uniform(0.8, 1.2))
        self._remote_retry_at = time.monotonic() + delay

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._task is not None:
            # Do not cancel a thread while it owns a SQLite connection or HTTP request.
            try:
                await self._task
            finally:
                self._task = None
                self._report(state="stopped")

    async def wait_closed(self) -> None:
        task = self._task
        if task is not None:
            await asyncio.shield(task)

    async def _run(self) -> None:
        try:
            while not self._stop.is_set():
                if isinstance(self.settings, RemoteClientSettings):
                    await asyncio.to_thread(self.cycle)
                else:
                    ready = await self.store.readiness()
                    if ready["ready"] and not self._stop.is_set():
                        await asyncio.to_thread(self.cycle)
                    elif not ready["ready"]:
                        self._report(state="waiting_database")
                try:
                    await asyncio.wait_for(self._wake.wait(), self.interval)
                except TimeoutError:
                    pass
        finally:
            if self._scan is not None:
                self._scan.close()
                self._scan = None

    def _discover(self) -> list[Path]:
        _directory(self.settings.state_dir, private=True)
        root = self.settings.state_dir.resolve() / "host-adapters"
        # mkdir(parents=True, mode=0700) leaves intermediates at the process umask.
        # The private state parent protects an owned non-writable 0755 intermediate.
        try:
            _directory(root, private=False)
        except FileNotFoundError:
            return []
        if self._scan is None:
            self._scan = os.scandir(root)
        # Keep the directory cursor across cycles: bad or busy receipts cannot starve later ones.
        result = []
        scanned = 0
        while len(result) < self.receipts_per_cycle:
            if self._pending:
                result.append(self._pending.popleft())
                continue
            if scanned >= 64:
                break
            try:
                entry = next(self._scan)
            except StopIteration:
                self._scan.close()
                self._scan = None
                break
            scanned += 1
            if entry.is_dir(follow_symlinks=False):
                self._pending.extend(Path(entry.path) / f"{host}.json" for host in hosts.HOST_VERSIONS)
        return result

    def cycle(self, *, deadline: float | None = None) -> None:
        # Shared discovery cursors must not be advanced by overlapping cycles.
        if deadline is None:
            self._cycle_lock.acquire()
        elif not self._cycle_lock.acquire(timeout=max(0, deadline - time.monotonic())):
            return
        try:
            if isinstance(self.settings, RemoteClientSettings):
                if deadline is None:
                    deadline = time.monotonic() + 20
                with remote_connection_cycle(self.settings, deadline=deadline, stop_event=self._stop):
                    self._cycle(deadline=deadline)
            else:
                self._cycle(deadline=deadline)
        finally:
            self._cycle_lock.release()

    def _cycle(self, *, deadline: float | None) -> None:
        remote = isinstance(self.settings, RemoteClientSettings)
        if remote and time.monotonic() < self._remote_retry_at:
            self._report(state="waiting_remote", cycles=self._status["cycles"] + 1)
            return
        failures = self._status["failures"]
        self._report(cycles=self._status["cycles"] + 1)
        raised = False
        try:
            remote_ready = False
            try:
                receipts = self._discover()
            except (OSError, DomainError) as error:
                self._failure(error, state="discovery_failed")
                if self._scan is not None:
                    self._scan.close()
                    self._scan = None
                return
            for index, path in enumerate(receipts):
                if self._stop.is_set() or (deadline is not None and time.monotonic() >= deadline):
                    self._pending.extendleft(reversed(receipts[index:]))
                    return
                descriptor = None
                spool = None
                try:
                    try:
                        path.lstat()
                    except FileNotFoundError:
                        # Most discovered directories have no receipt for this host.
                        continue
                    receipt = _receipt(self.settings, path)
                    outbox = Path(receipt["runtime_dir"]) / "capture.sqlite3"
                    health_configured = load_health_workspace(receipt) is not None
                    if not outbox.exists() and not health_configured:
                        continue
                    # Share the install/uninstall lock, but never wait behind a host operation.
                    lock = hosts._install_lock(self.settings, Path(receipt["project_root"]))
                    descriptor = os.open(lock, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    current = _receipt(self.settings, path)
                    if current != receipt:
                        continue
                    spool = ProducerSpool(outbox, receipt["deployment_id"], receipt["binding_id"], receipt["spool_limit_bytes"])
                    if not health_configured and not spool.status()["pending"]:
                        continue
                    if remote and not remote_ready:
                        try:
                            ensure_remote_ready(
                                self.settings, timeout=max(deadline - time.monotonic(), 0.001),
                                stop_event=self._stop,
                            )
                        except DomainError as error:
                            if error.code == "SERVICE_STOPPED":
                                self._stop.set()
                            if not self._stop.is_set():
                                self._failure(error, state="waiting_remote")
                                self._defer_remote()
                            self._pending.extendleft(reversed(receipts[index:]))
                            return
                        remote_ready = True
                    client = LocalClient(
                        receipt["base_url"], Path(receipt["producer_token_file"]),
                        timeout=max(deadline - time.monotonic(), 0.001) if remote else 1,
                        state_dir=self.settings.state_dir, deployment_id=self.settings.deployment_id,
                        remote_settings=hosts.receipt_connection(receipt),
                    )
                    owner = self
    
                    class OwnedDelivery:
                        def request(self, route, payload):
                            if owner._stop.is_set() or _receipt(owner.settings, path) != receipt:
                                raise DomainError("SERVICE_DRAINING", "Recovery stopped before dispatch", status=503, effect=EffectState.NOT_STARTED)
                            if deadline is not None:
                                remaining = deadline - time.monotonic()
                                if remaining <= 0:
                                    raise DomainError("SERVICE_UNAVAILABLE", "The recovery cycle deadline expired", status=503, effect=EffectState.NOT_STARTED)
                                client.timeout = remaining
                            return client.request(route, payload)
                    if not self._stop.is_set():
                        try:
                            observation = observe_health_workspace(
                                receipt, client=OwnedDelivery(), flush_limit=self.flush_limit, defer_flush=True)
                            if observation.get("state") == "gap":
                                self._failure(observation["code"])
                        except (OSError, ValueError, UnicodeError, DomainError, sqlite3.Error) as error:
                            self._failure(error)
                    if self._stop.is_set():
                        return
    
    
                    result = spool.flush(OwnedDelivery(), limit=self.flush_limit)
                    self._report(committed=self._status["committed"] + result["committed"])
                    for code in result["errors"]:
                        self._failure(code)
                    if remote and result["errors"]:
                        self._defer_remote()
                        self._pending.extendleft(reversed(receipts[index + 1:]))
                        return
                except (OSError, ValueError, UnicodeError, DomainError, sqlite3.Error) as error:
                    # Invalid, removed, busy and unavailable receipts retain their outboxes.
                    self._failure(error)
                    continue
                finally:
                    if spool is not None:
                        with suppress(sqlite3.Error, OSError):
                            spool.close()
                    if descriptor is not None:
                        os.close(descriptor)
            if remote_ready:
                self._remote_failures = 0
                self._remote_retry_at = 0.0
        except BaseException:
            raised = True
            raise
        finally:
            if not raised and self._status["failures"] == failures:
                self._report(state="idle", last_error=None)


@contextmanager
def _client_owner(settings: RemoteClientSettings):
    descriptor = None
    try:
        try:
            settings.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            _directory(settings.state_dir, private=True)
            descriptor = os.open(
                settings.state_dir / "client-recovery.lock",
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600,
            )
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise DomainError("CLIENT_RECOVERY_UNAVAILABLE", "The PC recovery ownership file is unsafe", status=503)
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DomainError("CLIENT_RECOVERY_ACTIVE", "Another process owns this PC recovery queue", status=503) from None
        except OSError:
            raise DomainError("CLIENT_RECOVERY_UNAVAILABLE", "The PC recovery queue is unavailable", status=503) from None
        yield
    finally:
        if descriptor is not None:
            os.close(descriptor)


async def run_client_recovery(settings: RemoteClientSettings) -> None:
    from .service import require_client_enabled, require_service_enabled

    require_supported_sqlite()
    require_client_enabled(settings)
    with _client_owner(settings):
        loop = asyncio.get_running_loop()
        stopped = asyncio.Event()
        signals = []
        waiter = None
        worker = SpoolRecovery(settings, None)
        try:
            for value in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(value, stopped.set)
                signals.append(value)
            waiter = asyncio.create_task(stopped.wait())
            worker.start()
            assert worker._task is not None
            done, _ = await asyncio.wait({waiter, worker._task}, return_when=asyncio.FIRST_COMPLETED)
            if worker._task in done:
                await worker._task
        finally:
            if waiter is not None:
                waiter.cancel()
                with suppress(asyncio.CancelledError):
                    await waiter
            try:
                await worker.stop()
            finally:
                for value in signals:
                    loop.remove_signal_handler(value)
        try:
            require_service_enabled(settings)
        except DomainError as error:
            if error.code == "SERVICE_STOPPED" or (error.code == "SERVICE_NOT_INSTALLED" and stopped.is_set()):
                return
            raise
        raise DomainError("SERVICE_UNAVAILABLE", "The managed PC recovery process exited before an explicit stop", status=503)
