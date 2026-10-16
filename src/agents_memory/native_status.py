from __future__ import annotations

import json
import os
import selectors
import signal
import subprocess
import time
from contextlib import suppress
from pathlib import Path

from .domain import DomainError
from .wire import decode_json

_RESPONSE_BYTES = 8 * 1024 * 1024
_DEADLINE_SECONDS = 30
_CLEANUP_SECONDS = 2
_METHODS = ("initialize", "initialized", "config/read", "hooks/list")


def _failure() -> DomainError:
    return DomainError(
        "HOST_NATIVE_STATUS_UNAVAILABLE",
        "Native inventory was unavailable or invalid; activation and protection remain unverified",
    )


def _stop_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.returncode is not None:
        return
    # Keep the leader unreaped until the final group signal.
    group_missing = False
    try:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            deadline = time.monotonic() + _CLEANUP_SECONDS
            while time.monotonic() < deadline:
                os.killpg(process.pid, 0)
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        except ProcessLookupError:
            group_missing = True
    finally:
        try:
            if not group_missing:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
        finally:
            process.wait(timeout=_CLEANUP_SECONDS)


def _codex_inventory(project: Path, executable: Path) -> tuple[dict, dict]:
    if os.name != "posix":
        raise _failure()
    if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
        raise DomainError("HOST_NATIVE_EXECUTABLE_INVALID", "Choose an existing absolute Codex executable")
    try:
        process = subprocess.Popen(
            [str(executable), "--no-daemon", "-c", "check_for_update_on_startup=false", "app-server", "--stdio"],
            cwd=project, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError:
        raise _failure() from None
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    stdin = process.stdin
    selector: selectors.BaseSelector | None = None
    pending = b""
    total = 0
    results: dict[int, dict] = {}
    deadline = time.monotonic() + _DEADLINE_SECONDS

    def send(value: dict) -> None:
        stdin.write((json.dumps(value, separators=(",", ":")) + "\n").encode())
        stdin.flush()

    try:
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        send({"id": 1, "method": "initialize", "params": {
            "clientInfo": {"name": "agents_memory_native_status", "version": "1"},
            "capabilities": None,
        }})
        while len(results) < 3:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.get_map():
                raise _failure()
            for key, _ in selector.select(min(0.25, remaining)):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                total += len(chunk)
                if total > _RESPONSE_BYTES:
                    raise _failure()
                if key.data != "stdout":
                    continue
                pending += chunk
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    message = decode_json(line)
                    if not isinstance(message, dict):
                        raise _failure()
                    identity = message.get("id")
                    if identity is None:
                        # Notifications are not activation or callback evidence.
                        continue
                    if type(identity) is not int or identity not in (1, 2, 3) or identity in results:
                        raise _failure()
                    if "error" in message or not isinstance(message.get("result"), dict):
                        raise _failure()
                    if identity != 1 and 1 not in results:
                        raise _failure()
                    results[identity] = message["result"]
                    if identity == 1:
                        send({"method": "initialized", "params": {}})
                        send({"id": 2, "method": "config/read", "params": {
                            "cwd": str(project), "includeLayers": True,
                        }})
                        send({"id": 3, "method": "hooks/list", "params": {"cwds": [str(project)]}})
        return results[2], results[3]
    except (OSError, ValueError, UnicodeError):
        raise _failure() from None
    finally:
        try:
            with suppress(OSError):
                stdin.close()
            try:
                _stop_process_group(process)
            except (OSError, subprocess.TimeoutExpired):
                raise _failure() from None
        finally:
            for stream in (stdin, process.stdout, process.stderr):
                with suppress(OSError):
                    stream.close()
            if selector is not None:
                selector.close()


def _summarize(project: Path, config: dict, inventory: dict) -> dict:
    layers = config.get("layers")
    entries = inventory.get("data")
    if not isinstance(layers, list) or not isinstance(entries, list) or len(entries) != 1:
        raise _failure()
    entry = entries[0]
    if not isinstance(entry, dict) or entry.get("cwd") != str(project):
        raise _failure()
    hooks = entry.get("hooks")
    if not isinstance(hooks, list):
        raise _failure()
    projects = []
    for layer in layers:
        if not isinstance(layer, dict) or not isinstance(layer.get("name"), dict):
            raise _failure()
        name = layer["name"]
        if name.get("type") != "project":
            continue
        folder = name.get("dotCodexFolder")
        if (not isinstance(folder, str) or len(folder) > 4096 or not Path(folder).is_absolute()
                or Path(folder).name != ".codex" or any(ord(char) < 32 for char in folder)
                or not project.is_relative_to(Path(folder).parent)):
            raise _failure()
        disabled = layer.get("disabledReason")
        if "disabledReason" not in layer or (disabled is not None and not isinstance(disabled, str)):
            state = "unknown"
        else:
            state = "disabled" if disabled is not None else "active"
        projects.append({"config_folder": folder, "trust_target": str(Path(folder).parent), "state": state})
    counts = {"project": 0, "user": 0, "system": 0, "plugin": 0, "other": 0}
    enabled = trusted = 0
    for hook in hooks:
        if not isinstance(hook, dict):
            raise _failure()
        source = hook.get("source")
        source = source if isinstance(source, str) and source in counts else "other"
        counts[source] += 1
        enabled += hook.get("enabled") is True
        trusted += hook.get("trustStatus") == "trusted"
    warnings = entry.get("warnings")
    errors = entry.get("errors")
    if not isinstance(warnings, list) or not isinstance(errors, list):
        raise _failure()
    return {
        "project_layers": projects,
        "hook_counts": counts,
        "enabled_hooks": enabled,
        "trusted_hooks": trusted,
        "inventory_warning_count": len(warnings),
        "inventory_error_count": len(errors),
        "evidence": "native_read_only_inventory_not_callback_or_protection",
        "requested_methods": list(_METHODS),
        "trust_or_enablement_change_requested": False,
        "thread_or_model_start_requested": False,
    }


def native_status(project: Path, host: str, *, codex_executable: Path | None = None) -> dict:
    """Report independent installation/activation evidence without trusting hooks."""
    from .native_memory import native_memory_status

    if host not in {"claude", "codex", "omp"}:
        raise DomainError("HOST_UNSUPPORTED", "Choose claude, codex or omp")
    if codex_executable is not None and host != "codex":
        raise DomainError("INPUT_INVALID", "The explicit Codex executable is only valid for the Codex inventory")
    try:
        root = project.resolve(strict=True)
    except (OSError, ValueError, RuntimeError):
        raise DomainError("HOST_PROJECT_INVALID", "Choose an existing project directory") from None
    if not root.is_dir():
        raise DomainError("HOST_PROJECT_INVALID", "Choose an existing project directory")
    result = {
        "host": host,
        "project": str(root),
        "installation": "not_checked",
        "native_inventory": {"state": "not_requested"},
        "callback": "not_observed",
        "protected_action": "not_verified",
        "strict_installation": "unsupported_refused" if host in {"codex", "omp"} else "intercepted_actions_only",
        "native_memory": native_memory_status(root),
        "settings_change_requested": False,
    }
    if codex_executable is not None:
        config, inventory = _codex_inventory(root, codex_executable)
        result["native_inventory"] = {"state": "observed", **_summarize(root, config, inventory)}
    return result
