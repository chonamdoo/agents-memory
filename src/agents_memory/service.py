"""Owned, per-user launchd lifecycle; control never depends on database availability."""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import plistlib
import re
import stat
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

from .config import Settings, load_settings
from .connection import RemoteClientSettings, load_remote_settings
from .domain import DomainError, EffectState
from .private_io import private_read, private_write
from .wire import decode_json

_RECEIPT = "receipt.json"
_LAUNCHCTL = "/bin/launchctl"
_MAXIMUM = 262144


def load_control_settings(path: Path) -> Settings | RemoteClientSettings:
    try:
        value = decode_json(private_read(path, _MAXIMUM))
        if value.get("kind") == "remote_client":
            if type(value.get("version")) is not int or value["version"] != 1:
                raise ValueError
            return RemoteClientSettings.model_validate(value)
        return load_settings(path)
    except (DomainError, OSError, ValueError, TypeError) as error:
        if isinstance(error, DomainError) and error.code == "CONFIG_UPGRADE_REQUIRED":
            raise
        raise DomainError("CONFIG_INVALID", "The private control configuration is invalid") from None


def _error(code: str = "SERVICE_OWNERSHIP_INVALID") -> DomainError:
    messages = {
        "SERVICE_OWNERSHIP_INVALID": "The local service's ownership, configuration or files have changed; refusing native mutation",
        "SERVICE_UNSUPPORTED": "Native local supervision requires macOS and a per-user GUI login domain",
        "SERVICE_NOT_INSTALLED": "Install this deployment's local service first",
        "SERVICE_STOPPED": "This local service was explicitly stopped; use service start to enable it",
        "SERVICE_CONTROL_FAILED": "The per-user native service operation failed",
    }
    return DomainError(code, messages[code], status=503)


def _intent_failure(error: DomainError | OSError, *, committed: bool) -> DomainError:
    code = error.code if isinstance(error, DomainError) else "SERVICE_CONTROL_FAILED"
    status = error.status if isinstance(error, DomainError) else 503
    cause = error.message if isinstance(error, DomainError) else "The service operation failed"
    intent = "was durably saved" if committed else "has an unconfirmed persistence outcome"
    return DomainError(
        code, f"{cause}. The requested service intent {intent}; native completion is unknown. Inspect service status before explicitly retrying.",
        status=status, effect=EffectState.COMMITTED if committed else EffectState.UNKNOWN,
    )


def _native() -> None:
    if sys.platform != "darwin":
        raise _error("SERVICE_UNSUPPORTED")


def _path(path: Path) -> Path:
    path = path.expanduser().absolute()
    if ".." in path.parts or any(part.is_symlink() for part in (path, *path.parents)):
        raise _error()
    for ancestor in path.parents:
        if not ancestor.exists():
            continue
        info = ancestor.stat()
        sticky_root = info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid not in {0, os.getuid()}
                or (info.st_mode & 0o022 and not sticky_root)):
            raise _error()
    return path


def _directory(path: Path, *, create: bool = False, private: bool = True) -> None:
    _path(path)
    if create and not path.exists():
        path.mkdir(mode=0o700, parents=True)
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & (0o077 if private else 0o022)):
        raise _error()


def _control(state_dir: Path) -> Path:
    return _path(_path(state_dir) / "service")


def _label(state_dir: Path, deployment_id: str) -> str:
    digest = hashlib.sha256(f"{os.getuid()}\0{state_dir}\0{deployment_id}".encode()).hexdigest()[:32]
    return "org.agents-memory.local." + digest


def _plist_path(state_dir: Path, deployment_id: str) -> Path:
    return _path(Path.home()) / "Library" / "LaunchAgents" / (_label(state_dir, deployment_id) + ".plist")


def _read(path: Path) -> bytes:
    _path(path)
    try:
        return private_read(path, _MAXIMUM)
    except (DomainError, OSError):
        raise _error() from None


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _trusted_code(path: Path, *, executable: bool = False) -> None:
    # A venv's Python commonly symlinks to a root-owned interpreter. Keep its
    # original argv identity, but validate the resolved target and both chains.
    if not path.is_absolute() or not path.exists():
        raise _error()
    for item in {path, path.resolve()}:
        for ancestor in (item, *item.parents):
            info = ancestor.stat()
            sticky_root = info.st_uid == 0 and stat.S_ISDIR(info.st_mode) and bool(info.st_mode & stat.S_ISVTX)
            if info.st_uid not in {0, os.getuid()} or (info.st_mode & 0o022 and not sticky_root):
                raise _error()
    if executable and (not path.is_file() or not os.access(path, os.X_OK)):
        raise _error()


def _environment() -> dict[str, str]:
    return {"HOME": str(_path(Path.home())), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}


def _plist(receipt: dict) -> bytes:
    env = {**_environment(), "PYTHONPATH": receipt["import_root"], "PYTHONNOUSERSITE": "1"}
    return plistlib.dumps({
        "Label": receipt["label"],
        "ProgramArguments": ["/usr/bin/env", "-i", *(f"{key}={value}" for key, value in env.items()),
            receipt["executable"], "-s", "-m", "agents_memory.cli", "--config", receipt["config_path"],
            "client-run" if receipt.get("kind") == "client" else "service-run"],
        "WorkingDirectory": receipt["control_dir"],
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 5,
        "ProcessType": "Background",
        "Umask": 0o077,
        # No service output is persisted: exception text can contain database credentials.
        "StandardOutPath": "/dev/null", "StandardErrorPath": "/dev/null",
    }, sort_keys=True)


def _save(control: Path, receipt: dict) -> None:
    private_write(control / _RECEIPT, json.dumps(receipt, sort_keys=True) + "\n", replace=True)


def _remaining(deadline: float | None) -> float:
    remaining = 2.0 if deadline is None else deadline - time.monotonic()
    if remaining <= 0:
        raise _error("SERVICE_CONTROL_FAILED")
    return remaining


@contextlib.contextmanager
def _locked(state_dir: Path, *, create: bool = False, shared: bool = False,
            deadline: float | None = None) -> Iterator[Path | None]:
    state_dir = _path(state_dir)
    control = _control(state_dir)
    if not control.exists() and not create:
        yield None
        return
    try:
        _directory(state_dir, create=create)
        _directory(control, create=create)
        lock = control / "control.lock"
        if lock.exists():
            _read(lock)
        fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise _error()
            # Readers coexist; native mutation and durable stop remain exclusive.
            # Waiting for a lock is bounded, rather than misreporting contention
            # as file-ownership drift.
            lock_deadline = min(deadline, time.monotonic() + 2) if deadline is not None else time.monotonic() + 2
            while True:
                _remaining(lock_deadline)
                try:
                    fcntl.flock(fd, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(min(0.01, _remaining(lock_deadline)))
            yield control
        finally:
            os.close(fd)
    except OSError:
        raise _error() from None


def _receipt(control: Path | None, *, settings: Settings | RemoteClientSettings | None = None,
             base_url: str | None = None, deployment_id: str | None = None) -> dict | None:
    if control is None:
        return None
    path = control / _RECEIPT
    if not path.exists() and not path.is_symlink():
        return None
    try:
        value = decode_json(_read(path))
        fields = {"format", "uid", "deployment_id", "realm", "state_dir", "base_url", "control_dir", "label",
                  "config_path", "config_sha256", "plist_path", "plist_sha256", "executable", "import_root", "enabled"}
        if isinstance(value, dict) and value.get("format") == 2:
            fields.add("kind")
        if isinstance(value, dict) and "state" in value:
            fields.add("state")
        if (not isinstance(value, dict) or set(value) != fields or type(value["format"]) is not int
                or value["format"] not in {1, 2} or type(value["uid"]) is not int or value["uid"] != os.getuid() or type(value["enabled"]) is not bool
                or any(not isinstance(value[key], str) for key in fields - {"format", "uid", "enabled"})):
            raise _error()
        if value["format"] == 2 and value["kind"] != "client":
            raise _error()
        # Before intent-first publication, a receipt could only mean installed.
        # Normalize that persisted data once; every current control path uses state.
        value.setdefault("state", "installed")
        if (value["state"] not in {"installing", "installed", "removing"}
                or (value["state"] == "removing" and value["enabled"])):
            raise _error()
        state = control.parent
        expected = {"state_dir": str(state), "control_dir": str(control),
                    "label": _label(state, value["deployment_id"]),
                    "plist_path": str(_plist_path(state, value["deployment_id"]))}
        if any(value[key] != item for key, item in expected.items()):
            raise _error()
        if base_url is not None and value["base_url"] != base_url.rstrip("/"):
            raise _error()
        if deployment_id is not None and value["deployment_id"] != deployment_id:
            raise _error()
        config_path = _path(Path(value["config_path"]))
        if _sha(_read(config_path)) != value["config_sha256"]:
            raise _error()
        configured = load_control_settings(config_path)
        if (value["format"] == 2) != isinstance(configured, RemoteClientSettings):
            raise _error()
        if (configured.deployment_id != value["deployment_id"] or configured.realm != value["realm"]
                or configured.base_url != value["base_url"] or _path(configured.state_dir) != state
                or (settings is not None and configured != settings)):
            raise _error()
        _trusted_code(Path(value["executable"]), executable=True)
        root = Path(value["import_root"])
        _trusted_code(root)
        _trusted_code(root / "agents_memory" / "cli.py")
        plist_path = Path(value["plist_path"])
        _directory(plist_path.parent, private=False)
        expected_plist = _plist(value)
        if _sha(expected_plist) != value["plist_sha256"]:
            raise _error()
        if plist_path.exists() or plist_path.is_symlink():
            if _read(plist_path) != expected_plist:
                raise _error()
        elif value["state"] not in {"installing", "removing"}:
            raise _error()
        return value
    except (OSError, ValueError, TypeError, DomainError) as error:
        if isinstance(error, DomainError) and error.code == "CONFIG_UPGRADE_REQUIRED":
            raise
        raise _error() from None


def _run(*args: str, deadline: float | None = None) -> subprocess.CompletedProcess:
    _native()
    timeout = min(2.0, _remaining(deadline))
    try:
        result = subprocess.run([_LAUNCHCTL, *args], capture_output=True, text=True,
                                encoding="utf-8", errors="strict",
                                timeout=timeout, check=False, env=_environment(), cwd="/")
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        raise _error("SERVICE_CONTROL_FAILED") from None
    _remaining(deadline)
    return result


def _target(receipt: dict) -> str:
    return f"gui/{os.getuid()}/{receipt['label']}"


def _job(receipt: dict, *, deadline: float | None = None) -> tuple[bool, bool]:
    result = _run("print", _target(receipt), deadline=deadline)
    if result.returncode:
        if result.returncode in {3, 113} or "Could not find service" in result.stderr:
            return False, False
        raise _error("SERVICE_CONTROL_FAILED")
    match = re.search(r"^\s*path = (.+)$", result.stdout, re.MULTILINE)
    if match is None or match.group(1).strip() != receipt["plist_path"]:
        raise _error()
    return True, bool(re.search(r"^\s*pid = [1-9][0-9]*\s*$", result.stdout, re.MULTILINE))


def _command(*args: str, deadline: float | None = None) -> None:
    if _run(*args, deadline=deadline).returncode:
        raise _error("SERVICE_CONTROL_FAILED")


def _state(receipt: dict | None, *, loaded: bool = False, running: bool = False) -> dict:
    result = {"managed": receipt is not None, "enabled": bool(receipt and receipt["enabled"]),
              "loaded": loaded, "running": running, "label": receipt["label"] if receipt else None,
              "deployment_id": receipt["deployment_id"] if receipt else None}
    if receipt and receipt.get("kind") == "client":
        result["component"] = "client"
    return result


def _activate(receipt: dict, *, explicit: bool = False, deadline: float | None = None) -> dict:
    loaded, running = _job(receipt, deadline=deadline)
    if not (loaded and running and not explicit):
        if explicit:
            _command("enable", _target(receipt), deadline=deadline)
        if not loaded:
            _command("bootstrap", f"gui/{os.getuid()}", receipt["plist_path"], deadline=deadline)
        elif not running:
            # No -k: a DB-unready but live authority must never be killed.
            _command("kickstart", _target(receipt), deadline=deadline)
        loaded, running = _job(receipt, deadline=deadline)
    if loaded and running and receipt["state"] == "installing":
        receipt["state"] = "installed"
        _save(Path(receipt["control_dir"]), receipt)
    return _state(receipt, loaded=loaded, running=running)


def _finish_install(control: Path, receipt: dict, *, deadline: float | None = None) -> None:
    """Publish owned files; activation seals the intent only after native confirmation."""
    if receipt["state"] != "installing":
        return
    plist_path = Path(receipt["plist_path"])
    loaded, _ = _job(receipt, deadline=deadline)
    if not plist_path.exists():
        if loaded:
            raise _error()
        private_write(plist_path, _plist(receipt))



def install_service(settings: Settings | RemoteClientSettings, config_path: Path) -> dict:
    _native()
    config_path = _path(config_path)
    raw = _read(config_path)
    if load_control_settings(config_path) != settings:
        raise _error()
    remote = isinstance(settings, RemoteClientSettings)
    if remote:
        from .spool import require_supported_sqlite

        require_supported_sqlite()
        if load_remote_settings(config_path) != settings:
            raise _error()
    state = _path(settings.state_dir)
    with _locked(state, create=True) as control:
        existing = _receipt(control, settings=settings)
        if existing is not None:
            if existing["config_path"] != str(config_path):
                raise _error()
            if existing["state"] == "removing":
                return _uninstall(control, existing, settings)
            if existing["state"] == "installing":
                if (existing["executable"] != str(Path(sys.executable).absolute())
                        or existing["import_root"] != str(Path(__file__).resolve().parent.parent)):
                    raise _error()
                if existing["enabled"]:
                    try:
                        _finish_install(control, existing)
                        return _activate(existing, explicit=True)
                    except (DomainError, OSError) as error:
                        raise _intent_failure(error, committed=True) from None
            loaded, running = _job(existing)
            if existing["enabled"] and not running:
                try:
                    return _activate(existing, explicit=True)
                except (DomainError, OSError) as error:
                    raise _intent_failure(error, committed=True) from None
            return _state(existing, loaded=loaded, running=running)
        plist_path = _plist_path(state, settings.deployment_id)
        if plist_path.exists() or plist_path.is_symlink():
            raise _error()
        _directory(plist_path.parent, create=True, private=False)
        executable = Path(sys.executable).absolute()  # Preserve the venv executable identity.
        root = Path(__file__).resolve().parent.parent
        _trusted_code(executable, executable=True)
        _trusted_code(root)
        _trusted_code(root / "agents_memory" / "cli.py")
        receipt = {"format": 2 if remote else 1, "uid": os.getuid(), "deployment_id": settings.deployment_id,
            "realm": settings.realm, "state_dir": str(state), "base_url": settings.base_url,
            "control_dir": str(control), "label": _label(state, settings.deployment_id),
            "config_path": str(config_path), "config_sha256": _sha(raw), "plist_path": str(plist_path),
            "executable": str(executable), "import_root": str(root), "enabled": True, "state": "installing"}
        if remote:
            receipt["kind"] = "client"
        plist = _plist(receipt)
        receipt["plist_sha256"] = _sha(plist)
        if _job(receipt)[0]:
            # A label without its ownership receipt is never adoptable.
            raise _error()
        try:
            _save(control, receipt)
        except (DomainError, OSError) as error:
            raise _intent_failure(error, committed=False) from None
        try:
            _finish_install(control, receipt)
            return _activate(receipt, explicit=True)
        except (DomainError, OSError) as error:
            raise _intent_failure(error, committed=True) from None


def service_status(settings: Settings | RemoteClientSettings) -> dict:
    with _locked(settings.state_dir, shared=True) as control:
        receipt = _receipt(control, settings=settings)
        if receipt is None:
            return _state(None)
        loaded, running = _job(receipt)
        return _state(receipt, loaded=loaded, running=running)


def start_service(settings: Settings | RemoteClientSettings) -> dict:
    with _locked(settings.state_dir) as control:
        receipt = _receipt(control, settings=settings)
        if receipt is None:
            raise _error("SERVICE_NOT_INSTALLED")
        if receipt["state"] == "removing":
            raise _error("SERVICE_STOPPED")
        if isinstance(settings, RemoteClientSettings):
            from .spool import require_supported_sqlite

            require_supported_sqlite()
            load_remote_settings(Path(receipt["config_path"]))
        # Validate an existing loaded job before changing durable intent.
        _job(receipt)
        receipt["enabled"] = True
        try:
            _save(control, receipt)
        except (DomainError, OSError) as error:
            raise _intent_failure(error, committed=False) from None
        try:
            _finish_install(control, receipt)
            return _activate(receipt, explicit=True)
        except (DomainError, OSError) as error:
            raise _intent_failure(error, committed=True) from None


def _stop(control: Path, receipt: dict) -> dict:
    loaded, _ = _job(receipt)
    receipt["enabled"] = False
    try:
        _save(control, receipt)  # Durable stop precedes *every* native mutation.
    except (DomainError, OSError) as error:
        raise _intent_failure(error, committed=False) from None
    try:
        if loaded or Path(receipt["plist_path"]).exists():
            _command("disable", _target(receipt))
        if loaded:
            _command("bootout", _target(receipt))
        deadline = time.monotonic() + 30
        while True:
            loaded, running = _job(receipt, deadline=min(deadline, time.monotonic() + 2))
            if not loaded:
                return _state(receipt, loaded=False, running=running)
            time.sleep(min(0.05, _remaining(deadline)))
    except (DomainError, OSError) as error:
        raise _intent_failure(error, committed=True) from None


def stop_service(settings: Settings | RemoteClientSettings) -> dict:
    with _locked(settings.state_dir) as control:
        receipt = _receipt(control, settings=settings)
        if receipt is None:
            raise _error("SERVICE_NOT_INSTALLED")
        return _stop(control, receipt)


def _unlink_synced(path: Path) -> None:
    path.unlink(missing_ok=True)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _uninstall(control: Path, receipt: dict, settings: Settings | RemoteClientSettings) -> dict:
    receipt["state"] = "removing"
    _stop(control, receipt)
    try:
        _receipt(control, settings=settings)
        _unlink_synced(Path(receipt["plist_path"]))
        _unlink_synced(control / _RECEIPT)
    except (DomainError, OSError) as error:
        raise _intent_failure(error, committed=True) from None
    return _state(None)


def uninstall_service(settings: Settings | RemoteClientSettings) -> dict:
    with _locked(settings.state_dir) as control:
        receipt = _receipt(control, settings=settings)
        if receipt is None:
            return _state(None)
        return _uninstall(control, receipt, settings)


def ensure_started(base_url: str, state_dir: Path | None, deployment_id: str | None = None,
                   *, deadline: float | None = None) -> bool:
    if state_dir is None:
        return False
    with _locked(state_dir, shared=True, deadline=deadline) as control:
        receipt = _receipt(control, base_url=base_url, deployment_id=deployment_id)
        if receipt is None:
            return False
        if not receipt["enabled"]:
            raise _error("SERVICE_STOPPED")
        loaded, running = _job(receipt, deadline=deadline)
        if loaded and running and receipt["state"] != "installing":
            return True
    # Never upgrade a held shared lock: stop may win this transition. Re-read
    # its durable intent under the exclusive mutation lock before recovery.
    with _locked(state_dir, deadline=deadline) as control:
        receipt = _receipt(control, base_url=base_url, deployment_id=deployment_id)
        if receipt is None:
            return False
        if not receipt["enabled"]:
            raise _error("SERVICE_STOPPED")
        _finish_install(control, receipt, deadline=deadline)
        _activate(receipt, deadline=deadline)
        return True


def require_service_enabled(settings: Settings | RemoteClientSettings) -> None:
    with _locked(settings.state_dir, shared=True) as control:
        receipt = _receipt(control, settings=settings)
        if receipt is None:
            raise _error("SERVICE_NOT_INSTALLED")
        if not receipt["enabled"]:
            raise _error("SERVICE_STOPPED")


def require_client_enabled(settings: RemoteClientSettings, *, deadline: float | None = None) -> None:
    if not isinstance(settings, RemoteClientSettings):
        raise _error()
    with _locked(settings.state_dir, shared=True, deadline=deadline) as control:
        receipt = _receipt(control, settings=settings)
        if receipt is not None and not receipt["enabled"]:
            raise _error("SERVICE_STOPPED")
