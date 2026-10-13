from __future__ import annotations

import base64
import errno
import fcntl
import hashlib
import json
import math
import os
import re
import shlex
import sqlite3
import stat
import subprocess
import sys
import threading
import time
import tomllib
import uuid
from contextlib import ExitStack, contextmanager, nullcontext, suppress
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from .client import LocalClient
from .config import Settings
from .constants import BOUNDED_CONTEXT_MARKER, HOST_CONTEXT_BYTES
from .domain import CaptureCommand, ContextCommand, DomainError, EffectState, canonical_digest
from .private_io import private_read, private_write, sync_file
from .spool import ProducerSpool
from .wire import decode_json

HOST_VERSIONS = {"claude": "2.1.296", "codex": "0.162.1", "omp": "18.9.1"}
ADAPTER_VERSION = 3
SERVER_NAME = "agents-memory"
HOST_INPUT_BYTES = 16 * 1024 * 1024
HOST_PROJECTION_BYTES = 65536
HOST_STATE_BYTES = 16384
LIFECYCLE_EVENTS = {
    "SessionStart", "PreCompact", "PostCompact", "SubagentStart", "SessionEnd",
    "session_start", "session_before_switch", "session_switch", "session_before_branch",
    "session_branch", "session_before_compact", "session_compact", "session_tree",
    "session_shutdown",
}
PROMPT_EVENTS = {"UserPromptSubmit", "before_agent_start"}
ACTION_EVENTS = {"PreToolUse", "tool_call"}
PROVIDER_EVENTS = {"before_provider_request", "after_provider_response"}
ACTION_CONTEXT_CODES = ("HOST_PROVIDER_INPUT_UNOBSERVABLE", "HOST_CONTEXT_STALE")


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _host(host: str) -> None:
    if host not in HOST_VERSIONS:
        raise DomainError("HOST_UNSUPPORTED", "Choose claude, codex or omp")


def capabilities(host: str, *, strict: bool = False, prompt_recall: bool = False) -> dict:
    _host(host)
    return {
        "native_version": HOST_VERSIONS[host],
        "evidence": "source_contract_not_runtime_acceptance",
        "mcp": "same_loopback_core_stdio_relay",
        "prompt_context": "bounded_opt_in" if prompt_recall else "disabled",
        "provider_input": "unobservable_final_subsequent_input",
        "provider_hook_is_consumption": False,
        "first_action": "refused_before_installation" if strict and host == "omp" else "deny_required_without_provider_input_evidence" if strict else "advisory_unenforced",
        "strict": ("unsupported_refused" if host == "omp" else "prompt_blocked_hosted_gap" if host == "codex" else "intercepted_actions_only") if strict else "disabled",
        "native_failure": ("pre_request_errors_and_timeouts_continue_dispatch" if host == "omp" else "strict_onFailure_block" if host == "claude" else "crash_timeout_or_skipped_hook_unenforceable_gap") if strict else "advisory_unenforced",
        "security_boundary": False,
        "discovery": "startup_cwd_only" if host == "omp" else "native_project_scope_requires_trust",
        "unsupported_footprints": ["shell", "hosted", "unknown_tools", "out_of_project"],
        "supported_path_tools": {
            "claude": ["Write", "Edit", "NotebookEdit", "Read"],
            "codex": [], "omp": ["write", "edit", "read"],
        }[host],
        "action_dimensions": {"paths": "native_tool_schema", "purpose": "unsupported_native", "snapshot": "unsupported_native"},
        "context_envelope_bytes": HOST_CONTEXT_BYTES,
        "hook_input_bytes": HOST_INPUT_BYTES,
        "mcp_config_scope": "local_project_private" if host == "claude" else "project",
        "native_context_limit": {"unit": "approximate_tokens", "value": HOST_CONTEXT_BYTES} if host == "codex" else None,
        "installation_warnings": [
            "Native action purpose and snapshot inputs are unsupported; required unresolved applicability is refused.",
            "Provider input consumption is unobservable; offered context does not authorize strict required actions.",
            *([
                "Strict OMP installation is refused: native pre-request exceptions/timeouts do not cancel provider dispatch; uninstall any historical strict adapter before reinstalling advisory mode.",
            ] if strict and host == "omp" else []),
        ],
        "capture": "human_input_interactive_rpc_and_explicit_commands" if host == "omp" else (
            "documented_user_prompt_only" if host == "codex" else "prompt_origin_gap_no_automatic_capture"
        ),
        "capture_identity": "native_prompt_or_turn_when_available_otherwise_hook_instance_only",
        "unmarked_memory_echo_detection": "unavailable_not_claimed",
        "child_root_run": "unknown_omitted_when_native_root_not_attested",
        "cross_native_exactly_once": False,
        "lineage": "session_thread_agent_path_generation_separate",
        "human_presence": "not_proven_same_uid_G0",
        "native_trust": "unverified_requires_host_operator_review",
        "scope": "registered_binding_plus_cwd_locator_check_not_cwd_authority",
        "startup_corpus_bytes": 0,
        "convention_export": False,
        "references": [
            "https://code.claude.com/docs/en/hooks" if host == "claude" else
            "https://developers.openai.com/codex/hooks/" if host == "codex" else
            "https://github.com/can1357/oh-my-pi/tree/v18.9.1/packages/coding-agent/src/extensibility",
        ],
    }


def _safe_path(root: Path, relative: str) -> Path:
    path = root / relative
    if not path.resolve().is_relative_to(root) or any(p.is_symlink() for p in (path, *path.parents) if p != root.parent):
        raise DomainError("HOST_PATH_DENIED", "Host-owned outputs cannot cross the project or use symlinks")
    return path


def _read_bytes(path: Path, limit: int = 1048576) -> bytes | None:
    if path.is_symlink():
        raise DomainError("HOST_PATH_DENIED", "Host configuration cannot be a symlink")
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > limit:
        raise DomainError("HOST_CONFIG_INVALID", "The host configuration is not a bounded regular file")
    return path.read_bytes()


def _object(raw: bytes | None) -> dict:
    if raw is None:
        return {}
    try:
        value = decode_json(raw)
    except (ValueError, UnicodeError):
        raise DomainError("HOST_CONFIG_INVALID", "The host JSON configuration is invalid") from None
    if not isinstance(value, dict):
        raise DomainError("HOST_CONFIG_INVALID", "The host JSON configuration must be an object")
    return value


@contextmanager
def _lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)



@contextmanager
def _claude_writer_lock(path: Path):
    # Claude 2.1.296 uses an atomic mkdir at <config>.lock, a 10s stale
    # lease, and mtime heartbeats. flock on our adapter lock cannot exclude it.
    # This convention excludes cooperating native writers, not arbitrary
    # same-UID writes or a process suspended beyond the native stale lease.
    lock = path.with_name(path.name + ".lock")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    deadline = time.monotonic() + 20
    while True:
        try:
            lock.mkdir(mode=0o700)
            break
        except FileExistsError:
            try:
                info = lock.lstat()
            except FileNotFoundError:
                continue
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                raise DomainError("HOST_PATH_DENIED", "The native configuration lock is not an owned directory")
            if time.time() - info.st_mtime > 10:
                try:
                    latest = lock.lstat()
                    if (latest.st_ino, latest.st_mtime_ns) == (info.st_ino, info.st_mtime_ns):
                        lock.rmdir()
                        continue
                except FileNotFoundError:
                    continue
                except OSError:
                    raise DomainError("HOST_CONFIG_LOCKED", "The stale native configuration lock could not be recovered") from None
            if time.monotonic() >= deadline:
                raise DomainError("HOST_CONFIG_LOCKED", "The native configuration writer is busy; retry ownership recovery")
            time.sleep(0.1)
    owned = lock.lstat()
    stopped = threading.Event()
    compromised = threading.Event()
    expected_mtime = [owned.st_mtime_ns]
    heartbeat_lock = threading.RLock()

    def check():
        with heartbeat_lock:
            try:
                current = lock.lstat()
            except OSError:
                compromised.set()
            else:
                if ((current.st_dev, current.st_ino) != (owned.st_dev, owned.st_ino)
                        or current.st_mtime_ns != expected_mtime[0]
                        or time.time() - current.st_mtime >= 10):
                    compromised.set()
            if compromised.is_set():
                raise DomainError("HOST_CONFIG_LOCK_LOST", "The native writer lease changed; reconcile ownership")

    def heartbeat():
        while not stopped.wait(1):
            try:
                with heartbeat_lock:
                    check()
                    os.utime(lock, None, follow_symlinks=False)
                    expected_mtime[0] = lock.lstat().st_mtime_ns
            except (OSError, DomainError):
                compromised.set()
                return

    worker = threading.Thread(target=heartbeat, daemon=True)
    worker.start()
    try:
        yield check
    finally:
        stopped.set()
        worker.join()
        try:
            current = lock.lstat()
            if ((current.st_dev, current.st_ino) == (owned.st_dev, owned.st_ino)
                    and current.st_mtime_ns == expected_mtime[0]):
                lock.rmdir()
        except FileNotFoundError:
            pass

@contextmanager
def _ownership_lock(settings: Settings, root: Path, host: str):
    with _lock(_install_lock(settings, root)):
        if host == "claude":
            native_path = _owned_path(root, str(_claude_config_path()))
            if native_path.is_relative_to(root) or native_path.is_relative_to(Path(_claude_project_key(root))):
                raise DomainError("HOST_NATIVE_CONFIG_PROJECT_DENIED", "Private native local configuration must remain outside the consumer project")
            with _lock(_safe_path(native_path.parent, ".agents-memory-install.lock")):
                yield
        else:
            yield


def _runtime_dir(settings: Settings, root: Path, binding_id: str, host: str) -> Path:
    state_key = canonical_digest({"deployment": settings.deployment_id, "binding": binding_id, "root": str(root), "host": host})
    state = settings.state_dir.resolve()
    if state.is_relative_to(root):
        raise DomainError("HOST_RUNTIME_PROJECT_DENIED", "Private adapter receipts and runtime must be outside the consumer project")
    return _safe_path(state, f"host-adapters/{state_key}")


def _install_lock(settings: Settings, root: Path) -> Path:
    key = canonical_digest({"deployment": settings.deployment_id, "root": str(root)})
    return _safe_path(settings.state_dir.resolve(), f"host-adapters/{key}/.install.lock")


def _receipt_path(settings: Settings, root: Path, host: str) -> Path:
    if settings.state_dir.resolve().is_relative_to(root):
        raise DomainError("HOST_RUNTIME_PROJECT_DENIED", "Private adapter receipts must be outside the consumer project")
    return _install_lock(settings, root).parent / f"{host}.json"


def _legacy_receipt_path(root: Path, host: str) -> Path:
    return _safe_path(root, f".agents-memory/hosts/{host}.json")


def _validate_receipt(value: dict, *, allow_legacy: bool, allow_deleted_project: bool = False) -> None:
    version = value.get("adapter_version")
    if type(version) is not int or version not in ({1, 2, ADAPTER_VERSION} if allow_legacy else {ADAPTER_VERSION}):
        raise DomainError("HOST_RECEIPT_INVALID", "The host ownership receipt is missing or unsupported")
    if not isinstance(value.get("host"), str) or value["host"] not in HOST_VERSIONS or type(value.get("strict")) is not bool:
        raise DomainError("HOST_RECEIPT_INVALID", "The host ownership receipt is invalid")
    for key in ("installation_id", "binding_id", "deployment_id", "realm", "base_url"):
        if not isinstance(value.get(key), str) or not value[key] or len(value[key]) > 4096:
            raise DomainError("HOST_RECEIPT_INVALID", "The host ownership receipt is incomplete")
    for key in ("project_root", "runtime_dir", "agent_token_file", "producer_token_file"):
        if not isinstance(value.get(key), str) or not value[key] or not Path(value[key]).is_absolute():
            raise DomainError("HOST_RECEIPT_INVALID", "The host ownership receipt has an invalid path")
    if allow_deleted_project and Path(value["project_root"]).exists():
        raise DomainError("HOST_RECEIPT_INVALID", "Deleted-project cleanup requires an absent project")
    for key in ("spool_limit_bytes", "max_capture_bytes", "max_http_body_bytes", "max_mcp_response_bytes", "context_budget_bytes"):
        if type(value.get(key)) is not int or not 1 <= value[key] <= 1073741824:
            raise DomainError("HOST_RECEIPT_INVALID", "The host ownership receipt has an invalid bound")
    if value["max_capture_bytes"] > 32768 or not 512 <= value["context_budget_bytes"] <= (2400 if allow_legacy and version != ADAPTER_VERSION else HOST_CONTEXT_BYTES):
        raise DomainError("HOST_RECEIPT_INVALID", "The host ownership receipt has an unsupported bound")
    ownership = value.get("ownership")
    if not isinstance(ownership, list) or not ownership or len(ownership) > 32:
        raise DomainError("HOST_RECEIPT_INVALID", "The host ownership manifest is invalid")
    for entry in ownership:
        if not isinstance(entry, dict) or not isinstance(entry.get("kind"), str) or entry["kind"] not in {"mcp", "local_mcp", "hook", "file", "toml"}:
            raise DomainError("HOST_RECEIPT_INVALID", "The host ownership manifest is invalid")
        if not isinstance(entry.get("path"), str) or not entry["path"] or ".." in Path(entry["path"]).parts:
            raise DomainError("HOST_RECEIPT_INVALID", "The host ownership manifest has an invalid path")
        if entry["kind"] == "local_mcp":
            native_project = entry.get("project")
            if (value["host"] != "claude" or entry["path"] != str(_claude_config_path()) or entry.get("key") != SERVER_NAME
                    or not isinstance(native_project, str) or not Path(native_project).is_absolute()
                    or (value.get("state") not in ("removed", "native_removing", "native_finishing", "native_removed") and not allow_deleted_project
                        and native_project != _claude_project_key(Path(value["project_root"])))):
                raise DomainError("HOST_RECEIPT_INVALID", "The private MCP entry is not scoped to this native project")
            if any(type(entry.get(flag)) is not bool for flag in ("created_projects", "created_project", "created_servers")):
                raise DomainError("HOST_RECEIPT_INVALID", "The private MCP ownership flags are incomplete")
        elif Path(entry["path"]).is_absolute():
            raise DomainError("HOST_RECEIPT_INVALID", "The project ownership path must be relative")
        if type(entry.get("created")) is not bool or not isinstance(entry.get("digest"), str) or len(entry["digest"]) != 64:
            raise DomainError("HOST_RECEIPT_INVALID", "The host ownership manifest is incomplete")
        field = {"mcp": "key", "local_mcp": "key", "hook": "event", "toml": "block"}.get(entry["kind"])
        if field and (not isinstance(entry.get(field), str) or not entry[field]):
            raise DomainError("HOST_RECEIPT_INVALID", "The host ownership manifest is incomplete")
    if not isinstance(value.get("capabilities"), dict):
        raise DomainError("HOST_RECEIPT_INVALID", "The host capability receipt is incomplete")
    if version == ADAPTER_VERSION:
        prompt_recall = value["capabilities"].get("prompt_context") == "bounded_opt_in"
        expected = capabilities(value["host"], strict=value["strict"], prompt_recall=prompt_recall)
        historical_omp_strict = None
        if value["host"] == "omp" and value["strict"]:
            # Only exact historical metadata is accepted for owned cleanup.
            # It never authorizes execution or replay of the old extension.
            historical_omp_strict = {
                **expected,
                "first_action": "deny_required_without_provider_input_evidence",
                "strict": "intercepted_actions_only",
                "native_failure": "registered_tool_hook_fail_closed",
                "installation_warnings": expected["installation_warnings"][:-1],
            }
        if value["capabilities"] != expected and value["capabilities"] != historical_omp_strict:
            raise DomainError("HOST_RECEIPT_INVALID", "The host capability receipt does not match its configured modes")
        if value["host"] == "omp" and value["strict"] and not allow_legacy:
            raise DomainError("HOST_STRICT_UNSUPPORTED", "OMP has no fail-closed native pre-request gate; uninstall the historical strict adapter and reinstall without --strict")
        if not isinstance(value.get("state"), str) or value["state"] not in {"pending", "installed", "removing", "native_removing", "native_finishing", "native_removed", "removed"}:
            raise DomainError("HOST_RECEIPT_INVALID", "The host ownership state is invalid")
        if not isinstance(value.get("intent_digest"), str) or len(value["intent_digest"]) != 64:
            raise DomainError("HOST_RECEIPT_INVALID", "The host recovery intent is incomplete")
        if value["state"] == "installed":
            final_files = value.get("installed_files")
            owned_paths = {entry["path"] for entry in ownership}
            if not isinstance(final_files, list) or not 1 <= len(final_files) <= 8:
                raise DomainError("HOST_RECEIPT_INVALID", "The installed file hashes are incomplete")
            paths = set()
            for entry in final_files:
                if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or entry["path"] not in owned_paths or entry["path"] in paths:
                    raise DomainError("HOST_RECEIPT_INVALID", "The installed file manifest is invalid")
                if not isinstance(entry.get("digest"), str) or len(entry["digest"]) != 64:
                    raise DomainError("HOST_RECEIPT_INVALID", "The installed file hashes are invalid")
                paths.add(entry["path"])
            if paths != owned_paths:
                raise DomainError("HOST_RECEIPT_INVALID", "The installed file manifest is incomplete")


_RECEIPT_REFUSAL_CODES = frozenset({"HOST_STRICT_UNSUPPORTED", "HOST_UNINSTALL_INCOMPLETE"})


def load_receipt(receipt_path: Path, *, allow_legacy: bool = False, active: bool = True, allow_deleted_project: bool = False) -> dict:
    if allow_deleted_project and active:
        raise DomainError("HOST_RECEIPT_INVALID", "Deleted-project receipts are cleanup-only")
    raw = private_read(receipt_path, 65536) if allow_deleted_project else _read_bytes(receipt_path, 65536)
    value = _object(raw)
    _validate_receipt(value, allow_legacy=allow_legacy, allow_deleted_project=allow_deleted_project)
    digest = value.pop("ownership_digest", None)
    if digest != canonical_digest(value):
        raise DomainError("HOST_RECEIPT_DRIFT", "The host ownership receipt changed")
    value["ownership_digest"] = digest
    if active and value["host"] == "omp" and value["strict"]:
        raise DomainError("HOST_STRICT_UNSUPPORTED", "OMP has no fail-closed native pre-request gate; uninstall the historical strict adapter and reinstall without --strict")
    if active and value.get("state") in ("native_removing", "native_finishing", "native_removed"):
        raise DomainError("HOST_UNINSTALL_INCOMPLETE", "Project entries were not verified after deleted-project cleanup; run host-uninstall for this project")
    if active and value.get("state") != "installed":
        raise DomainError("HOST_INSTALLATION_INCOMPLETE", "Reconcile the pending host ownership intent")
    return value


def _write_receipt(path: Path, receipt: dict) -> None:
    receipt.pop("ownership_digest", None)
    receipt["ownership_digest"] = canonical_digest(receipt)
    private_write(path, _json(receipt) + "\n", replace=path.exists())


def _unlink(path: Path, *, directory: int | None = None) -> None:
    if directory is not None:
        os.unlink(path.name, dir_fd=directory)
        sync_file(directory)
        return
    path.unlink()
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        sync_file(descriptor)
    finally:
        os.close(descriptor)


def _credentials(agent: Path, producer: Path) -> tuple[Path, Path]:
    selected = []
    values = []
    for path in (agent, producer):
        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
            raise DomainError("HOST_CREDENTIAL_INVALID", "Use separate existing private credential files")
        raw = _read_bytes(path, 1024)
        value = raw.strip() if raw is not None else b""
        if not value or len(value) > 512 or any(chr(ch).isspace() for ch in value):
            raise DomainError("HOST_CREDENTIAL_INVALID", "The host credential file is invalid")
        selected.append(path.resolve())
        values.append(value)
    if selected[0] == selected[1] or values[0] == values[1]:
        raise DomainError("HOST_CREDENTIAL_SEPARATION_REQUIRED", "Agent and producer credentials must differ")
    return selected[0], selected[1]


def _command(receipt: Path, verb: str) -> list[str]:
    return [sys.executable, "-m", "agents_memory.cli", verb, "--receipt", str(receipt)]


def _claude_project_key(root: Path) -> str:
    # Native Claude keys linked worktrees by the main Git project, not their cwd.
    # This is configuration identity only; it never widens the memory binding.
    marker = None
    for directory in (root, *root.parents):
        candidate = directory / ".git"
        if candidate.exists():
            marker = candidate
            break
    if marker is None:
        return str(root)
    if marker.is_dir():
        return str(marker.parent)
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null", GIT_OPTIONAL_LOCKS="0")
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            check=True, timeout=5, env=environment,
        )
        value = result.stdout.strip()
        if not value or len(value) > 4096 or "\n" in value or not Path(value).is_absolute():
            raise ValueError
        common = Path(value).resolve(strict=True)
        if not common.is_dir():
            raise ValueError
        return str(common.parent if common.name == ".git" else marker.parent)
    except (OSError, ValueError, subprocess.SubprocessError):
        raise DomainError("HOST_NATIVE_SCOPE_UNRESOLVED", "The native Git project scope could not be resolved") from None


def _claude_config_path() -> Path:
    directory = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(os.path.abspath(Path(directory).expanduser())) / ".claude.json" if directory else Path.home() / ".claude.json"


def _owned_path(root: Path, locator: str) -> Path:
    if Path(locator).is_absolute():
        path = _claude_config_path()
        if locator != str(path) or path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
            raise DomainError("HOST_PATH_DENIED", "The private native configuration locator changed")
        return path
    return _safe_path(root, locator)


def _locator(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)


@dataclass(frozen=True)
class _ClaudeMutation:
    path: Path
    ownership: dict
    before: dict | None
    after: dict | None


def _claude_value(document: dict, entry: dict) -> dict | None:
    scope = document
    for key in ("projects", entry["project"], "mcpServers"):
        if key not in scope:
            return None
        scope = scope[key]
        if not isinstance(scope, dict):
            raise DomainError("HOST_CONFIG_DRIFT", "The owned native configuration scope changed")
    if entry["key"] not in scope:
        return None
    value = scope[entry["key"]]
    if not isinstance(value, dict):
        raise DomainError("HOST_CONFIG_DRIFT", "The owned native MCP entry changed")
    return value


def _claude_current(step: _ClaudeMutation) -> dict | None:
    return _claude_value(_object(_read_bytes(step.path)), step.ownership)


def _claude_apply(step: _ClaudeMutation, check) -> bool:
    check()
    before = _read_bytes(step.path)
    document = _object(before)
    current = _claude_value(document, step.ownership)
    if current == step.after:
        return False
    if current != step.before:
        raise DomainError("HOST_CONFIG_DRIFT", "A conflicting owned native MCP entry was preserved")
    entry = step.ownership
    if step.after is not None:
        project = document.setdefault("projects", {}).setdefault(entry["project"], {})
        project.setdefault("mcpServers", {})[entry["key"]] = step.after
    else:
        projects = document["projects"]
        project = projects[entry["project"]]
        servers = project["mcpServers"]
        del servers[entry["key"]]
        if not servers and entry["created_servers"]:
            project.pop("mcpServers")
        if not project and entry["created_project"]:
            projects.pop(entry["project"])
        if not projects and entry["created_projects"]:
            document.pop("projects")
    check()
    # The merge base is read under Claude's own writer lock. Never replay a
    # saved document or delete the whole native config, even during rollback.
    def before_publish():
        check()
        if _read_bytes(step.path) != before:
            raise DomainError("HOST_CONFIG_DRIFT", "Native configuration changed outside its writer lock; retry key recovery")

    private_write(step.path, _json(document) + "\n", replace=before is not None, before_publish=before_publish)
    check()
    return True


def _claude_entry(plan: list, ownership: list, root: Path, value: dict) -> None:
    path = _owned_path(root, str(_claude_config_path()))
    if path.is_relative_to(root):
        raise DomainError("HOST_NATIVE_CONFIG_PROJECT_DENIED", "Private native local configuration must remain outside the consumer project")
    project_key = _claude_project_key(root)
    if path.is_relative_to(Path(project_key)):
        raise DomainError("HOST_NATIVE_CONFIG_PROJECT_DENIED", "Private native configuration must remain outside the canonical Git project")
    before = _read_bytes(path)
    document = _object(before)
    created_projects = "projects" not in document
    projects = document.setdefault("projects", {})
    if not isinstance(projects, dict):
        raise DomainError("HOST_CONFIG_INVALID", "The native local project configuration is invalid")
    created_project = project_key not in projects
    project = projects.setdefault(project_key, {})
    if not isinstance(project, dict):
        raise DomainError("HOST_CONFIG_INVALID", "The native local project configuration is invalid")
    created_servers = "mcpServers" not in project
    servers = project.setdefault("mcpServers", {})
    if not isinstance(servers, dict) or SERVER_NAME in servers:
        raise DomainError("HOST_ENTRY_CONFLICT", "An existing local MCP entry is not owned")
    entry = {
        "path": str(path), "kind": "local_mcp", "project": project_key, "key": SERVER_NAME,
        "digest": canonical_digest(value), "created": before is None,
        "created_projects": created_projects, "created_project": created_project, "created_servers": created_servers,
    }
    plan.append(_ClaudeMutation(path, entry, None, value))
    ownership.append(entry)


def _json_entry(plan: list, ownership: list, root: Path, relative: str, key: str, value: dict) -> None:
    path = _safe_path(root, relative)
    before = _read_bytes(path)
    document = _object(before)
    servers = document.setdefault("mcpServers", {})
    if not isinstance(servers, dict) or key in servers:
        raise DomainError("HOST_ENTRY_CONFLICT", "An existing MCP entry is not owned by this installation")
    servers[key] = value
    after = (_json(document) + "\n").encode()
    plan.append((path, before, after))
    ownership.append({"path": relative, "kind": "mcp", "key": key, "digest": canonical_digest(value), "created": before is None})


def _owned_entry_matches(root: Path, entry: dict) -> bool:
    raw = _read_bytes(_owned_path(root, entry["path"]), HOST_INPUT_BYTES)
    if raw is None:
        return False
    if entry["kind"] == "file":
        return _digest(raw) == entry["digest"]
    if entry["kind"] == "toml":
        return raw.decode("utf-8").count(entry["block"]) == 1
    document = _object(raw)
    if entry["kind"] == "hook":
        hooks = document.get("hooks", {})
        if not isinstance(hooks, dict):
            return False
        groups = hooks.get(entry["event"], [])
        return isinstance(groups, list) and sum(canonical_digest(group) == entry["digest"] for group in groups) == 1
    if entry["kind"] == "local_mcp":
        projects = document.get("projects", {})
        if not isinstance(projects, dict):
            return False
        document = projects.get(entry["project"], {})
        if not isinstance(document, dict):
            return False
    servers = document.get("mcpServers", {})
    return isinstance(servers, dict) and canonical_digest(servers.get(entry["key"])) == entry["digest"]


def _hooks(plan: list, ownership: list, root: Path, relative: str, command: list[str], host: str, strict: bool) -> None:
    path = _safe_path(root, relative)
    before = _read_bytes(path)
    document = _object(before)
    hooks = document.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise DomainError("HOST_CONFIG_INVALID", "The native hooks configuration is invalid")
    for event in ("SessionStart", "UserPromptSubmit", "PreToolUse", "PreCompact", "PostCompact", "SubagentStart", "SessionEnd"):
        if event == "PreToolUse" and not strict and not capabilities(host)["supported_path_tools"]:
            continue
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            raise DomainError("HOST_CONFIG_INVALID", "The native hook event is invalid")
        handler = {"type": "command", "command": shlex.join(command), "timeout": 15}
        if host == "claude":
            handler = {"type": "command", "command": command[0], "args": command[1:], "timeout": 15}
            if strict:
                handler["onFailure"] = "block"
        elif event == "SessionEnd":
            handler["timeout"] = 3
        else:
            handler["additionalContextLimit"] = HOST_CONTEXT_BYTES
        group = {"hooks": [handler]}
        if event == "PreToolUse" and not strict:
            group["matcher"] = "|".join(capabilities(host)["supported_path_tools"])
        if any(existing == group for existing in groups):
            raise DomainError("HOST_ENTRY_CONFLICT", "A matching hook already exists without an owned receipt")
        groups.append(group)
        ownership.append({"path": relative, "kind": "hook", "event": event, "digest": canonical_digest(group), "created": before is None})
    plan.append((path, before, (_json(document) + "\n").encode()))


def _hook_group_references(group: object, receipt_path: Path) -> bool:
    """Whether a possibly user-edited hook group still invokes this receipt's hook.

    String commands are shell-decoded whether or not an ``args`` list is present;
    a command shlex cannot parse only counts when it contains the raw or quoted path.
    """
    target = str(receipt_path)
    quoted = shlex.quote(target)
    handlers = group.get("hooks") if isinstance(group, dict) else None
    for handler in handlers if isinstance(handlers, list) else ():
        if not isinstance(handler, dict):
            continue
        command, args = handler.get("command"), handler.get("args")
        values = [command, *(args if isinstance(args, list) else ())]
        if any(isinstance(value, str) and target in value for value in values):
            return True
        if isinstance(command, str):
            if quoted in command:
                return True
            try:
                if any(target in token for token in shlex.split(command)):
                    return True
            except ValueError:
                pass
    return False


_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


class _ProjectDir:
    """The project directory pinned by descriptor before its ownership lock is awaited.

    Project files are read, written and removed relative to the descriptor, so
    each operation reaches the directory the path named when the command began.
    A root moved, unmounted or swapped meanwhile can neither make absence read
    as an applied removal nor have a vacated path recreated. ``check`` refuses
    once the path, without following symlinks, names another directory or none.
    """

    def __init__(self, root: Path, descriptor: int) -> None:
        info = os.fstat(descriptor)
        self.root, self._descriptor, self._identity = root, descriptor, (info.st_dev, info.st_ino)

    def check(self) -> None:
        try:
            info = os.stat(self.root, follow_symlinks=False)
        except OSError:
            info = None
        if info is None or (info.st_dev, info.st_ino) != self._identity:
            raise DomainError("HOST_CONFIG_DRIFT", "The project path changed during the ownership change; restore the project and retry")

    def _parent(self, path: Path, *, create: bool = False) -> int | None:
        *parents, _ = path.relative_to(self.root).parts
        directory = os.dup(self._descriptor)
        try:
            for index, part in enumerate(parents):
                try:
                    child = os.open(part, _DIRECTORY_FLAGS, dir_fd=directory)
                except FileNotFoundError:
                    if not create:
                        os.close(directory)
                        return None
                    # Same modes as Path.mkdir(parents=True): only the immediate parent is private.
                    with suppress(FileExistsError):
                        os.mkdir(part, 0o700 if index == len(parents) - 1 else 0o777, dir_fd=directory)
                    child = os.open(part, _DIRECTORY_FLAGS, dir_fd=directory)
                os.close(directory)
                directory = child
        except OSError as error:
            try:
                if error.errno not in {errno.ELOOP, errno.ENOTDIR}:
                    raise
                linked = stat.S_ISLNK(os.stat(part, dir_fd=directory, follow_symlinks=False).st_mode)
            finally:
                os.close(directory)
            # A regular file where a directory belongs means the entry cannot exist;
            # a symlink is refused like every other host-owned path.
            if create or linked:
                raise DomainError("HOST_PATH_DENIED", "Host-owned outputs cannot cross the project or use symlinks") from None
            return None
        return directory

    def read(self, path: Path, limit: int = 1048576) -> bytes | None:
        directory = self._parent(path)
        if directory is None:
            return None
        try:
            descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        except (FileNotFoundError, NotADirectoryError):
            return None
        except OSError as error:
            if error.errno == errno.ELOOP:
                raise DomainError("HOST_PATH_DENIED", "Host configuration cannot be a symlink") from None
            if error.errno in {errno.ENXIO, errno.EOPNOTSUPP}:
                # A socket cannot be opened at all; it is non-regular configuration like a FIFO.
                raise DomainError("HOST_CONFIG_INVALID", "The host configuration is not a bounded regular file") from None
            raise
        finally:
            os.close(directory)
        try:
            regular, raw = stat.S_ISREG(os.fstat(descriptor).st_mode), b""
            if regular:
                with os.fdopen(descriptor, "rb", closefd=False) as stream:
                    raw = stream.read(limit + 1)
        finally:
            os.close(descriptor)
        if not regular or len(raw) > limit:
            raise DomainError("HOST_CONFIG_INVALID", "The host configuration is not a bounded regular file")
        return raw

    def write(self, path: Path, content: bytes, *, replace: bool) -> None:
        directory = self._parent(path, create=True)
        if directory is None:
            # Never let a descriptor write degrade into path-mode publication.
            raise DomainError("HOST_PATH_DENIED", "Host-owned outputs cannot cross the project or use symlinks")
        try:
            private_write(path, content, replace=replace, directory=directory)
        finally:
            os.close(directory)

    def unlink(self, path: Path) -> None:
        directory = self._parent(path)
        if directory is None:
            raise DomainError("HOST_CONFIG_DRIFT", "Configuration changed during ownership recovery")
        try:
            _unlink(path, directory=directory)
        finally:
            os.close(directory)


@contextmanager
def _pinned_project(root: Path):
    """Pin ``root`` before the ownership lock is awaited; ``check`` it once the lock is held."""
    try:
        descriptor = os.open(root, _DIRECTORY_FLAGS)
    except OSError as error:
        if error.errno in {errno.ENOENT, errno.ENOTDIR, errno.ELOOP}:
            raise DomainError("HOST_CONFIG_DRIFT", "The project path changed before its ownership lock; nothing was changed") from None
        raise DomainError("HOST_PROJECT_INVALID", "The project directory cannot be opened; nothing was changed") from None
    try:
        yield _ProjectDir(root, descriptor)
    finally:
        os.close(descriptor)


def _toml_entry(plan: list, ownership: list, root: Path, command: list[str], owner: str) -> None:
    relative = ".codex/config.toml"
    path = _safe_path(root, relative)
    before = _read_bytes(path)
    try:
        text = before.decode() if before is not None else ""
        document = tomllib.loads(text)
    except (ValueError, UnicodeError):
        raise DomainError("HOST_CONFIG_INVALID", "The Codex TOML configuration is invalid") from None
    servers = document.get("mcp_servers", {})
    if not isinstance(servers, dict) or SERVER_NAME in servers:
        raise DomainError("HOST_ENTRY_CONFLICT", "An existing Codex MCP entry is not owned")
    block = (
        f"\n# BEGIN agents-memory owned {owner}\n"
        f"[mcp_servers.{SERVER_NAME}]\ncommand = {_json(command[0])}\nargs = {_json(command[1:])}\n"
        f"# END agents-memory owned {owner}\n"
    )
    after = (text + block).encode()
    try:
        tomllib.loads(after.decode())
    except ValueError:
        raise DomainError("HOST_CONFIG_INVALID", "Codex config cannot accept an isolated owned MCP table") from None
    plan.append((path, before, after))
    ownership.append({"path": relative, "kind": "toml", "block": block, "digest": _digest(block.encode()), "created": before is None})


def _apply(plan: list, project: _ProjectDir | None) -> None:
    """Apply an ownership plan; ``project`` is None only for a deleted project's native-only plan."""
    with ExitStack() as locks:
        native_checks = {
            path: locks.enter_context(_claude_writer_lock(path))
            for path in {step.path for step in plan if isinstance(step, _ClaudeMutation)}
        }
        for step in plan:
            if isinstance(step, _ClaudeMutation):
                if _claude_current(step) not in (step.before, step.after):
                    raise DomainError("HOST_CONFIG_DRIFT", "A conflicting owned native MCP entry was preserved")
            else:
                path, before, after = step
                if project.read(path) not in (before, after):
                    raise DomainError("HOST_CONFIG_DRIFT", "Configuration changed outside the owned recovery intent")
        applied, attempted = [], False
        try:
            for step in plan:
                if isinstance(step, _ClaudeMutation):
                    attempted = True
                    if _claude_apply(step, native_checks[step.path]):
                        applied.append(step)
                    continue
                path, before, after = step
                current = project.read(path)
                if current == after:
                    continue
                if current != before:
                    raise DomainError("HOST_CONFIG_DRIFT", "Configuration changed during ownership recovery")
                attempted = True
                if after is None:
                    project.unlink(path)
                else:
                    project.write(path, after, replace=before is not None)
                applied.append(step)
        except Exception as failure:
            try:
                for step in reversed(applied):
                    if isinstance(step, _ClaudeMutation):
                        reverse = _ClaudeMutation(step.path, step.ownership, step.after, step.before)
                        _claude_apply(reverse, native_checks[step.path])
                        continue
                    path, before, after = step
                    if project.read(path) != after:
                        raise DomainError("HOST_ROLLBACK_DRIFT", "Changed configuration was preserved; reconcile ownership")
                    if before is None:
                        project.unlink(path)
                    else:
                        project.write(path, before, replace=after is not None)
            except DomainError as error:
                raise _after_change(error) from None
            # A native write can be published before its lease check refuses, and is
            # then absent from ``applied``: once a mutation was attempted, report unknown.
            if attempted and isinstance(failure, DomainError):
                raise _after_change(failure) from None
            raise


def _after_change(error: DomainError) -> DomainError:
    """The same refusal, reported as ``unknown`` because owned state may already have changed."""
    return DomainError(error.code, error.message, status=error.status, effect=EffectState.UNKNOWN)


class _CommandEffect:
    """Report a host command's refusals as ``unknown`` once it has changed state.

    ``not_started`` promises that nothing changed. That stops being true once an
    intent was recorded or a replay finished, even when the command then refuses.
    """

    def __init__(self) -> None:
        self.changed = False

    def __enter__(self) -> _CommandEffect:
        return self

    def __exit__(self, kind, error, traceback) -> None:
        if self.changed and isinstance(error, DomainError) and error.effect == EffectState.NOT_STARTED:
            raise _after_change(error) from None


def _intent_path(receipt: dict) -> Path:
    return _safe_path(Path(receipt["runtime_dir"]), f"ownership-{receipt['intent_digest']}.json")


def _begin_intent(receipt_path: Path, receipt: dict, project: _ProjectDir | None, plan: list, state: str) -> None:
    if project is not None:
        project.check()
    intent = {"installation_id": receipt["installation_id"], "steps": []}
    for step in plan:
        if isinstance(step, _ClaudeMutation):
            if _claude_current(step) != step.before:
                raise DomainError("HOST_CONFIG_DRIFT", "The owned native MCP entry changed before ownership intent")
            intent["steps"].append({
                "kind": "local_mcp", "path": str(step.path),
                "project": step.ownership["project"], "key": step.ownership["key"],
                "before": step.before, "after": step.after,
            })
            continue
        path, before, after = step
        if project.read(path) != before:
            raise DomainError("HOST_CONFIG_DRIFT", "Configuration changed before ownership intent")
        intent["steps"].append({
            "path": _locator(project.root, path),
            "before": base64.b64encode(before).decode() if before is not None else None,
            "after": base64.b64encode(after).decode() if after is not None else None,
            "before_digest": _digest(before) if before is not None else None,
            "after_digest": _digest(after) if after is not None else None,
        })
    previous = _intent_path(receipt) if receipt.get("intent_digest") else None
    receipt["state"], receipt["intent_digest"] = state, canonical_digest(intent)
    path = _intent_path(receipt)
    content = (_json(intent) + "\n").encode()
    published = not path.exists()
    if published:
        private_write(path, content)
    elif _read_bytes(path, 16777216) != content:
        raise DomainError("HOST_RECOVERY_DRIFT", "Existing private ownership intent was preserved")
    try:
        _write_receipt(receipt_path, receipt)
        if previous is not None and previous != path and previous.exists():
            _unlink(previous)
    except DomainError as error:
        # The intent this call published is durable even when its receipt is refused.
        if published:
            raise _after_change(error) from None
        raise


def _intent_plan(receipt: dict, root: Path, *, deleted_project: bool = False) -> list:
    intent = _object(_read_bytes(_intent_path(receipt), 16777216))
    if canonical_digest(intent) != receipt["intent_digest"] or intent.get("installation_id") != receipt["installation_id"]:
        raise DomainError("HOST_RECOVERY_DRIFT", "The durable host recovery intent changed")
    steps = intent.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 8:
        raise DomainError("HOST_RECEIPT_INVALID", "The host recovery steps are invalid")
    deleted_scope = deleted_project or receipt["state"] == "native_removing"
    if deleted_scope and (
        receipt["host"] != "claude" or receipt["state"] not in {"removing", "native_removing"} or root.is_symlink()
        or (receipt["state"] == "removing" and root.exists())
    ):
        raise DomainError("HOST_RECEIPT_INVALID", "Deleted-project recovery requires a Claude native removal intent")
    plan, seen = [], set()
    for step in steps:
        if not isinstance(step, dict) or not isinstance(step.get("path"), str) or not step["path"] or step["path"] in seen:
            raise DomainError("HOST_RECEIPT_INVALID", "The host recovery steps are incomplete")
        entries = [entry for entry in receipt["ownership"] if entry["path"] == step["path"]]
        if not entries:
            raise DomainError("HOST_RECEIPT_INVALID", "The recovery step is not receipt-owned")
        path = _owned_path(root, step["path"])
        seen.add(step["path"])
        local = next((entry for entry in entries if entry["kind"] == "local_mcp"), None)
        if step.get("kind") == "local_mcp":
            if (local is None or step.get("project") != local["project"] or step.get("key") != local["key"]
                    or "before" not in step or "after" not in step):
                raise DomainError("HOST_RECEIPT_INVALID", "The native key recovery scope is invalid")
            if deleted_scope and (
                set(step) != {"kind", "path", "project", "key", "before", "after"}
                or step["before"] is None or step["after"] is not None
                or path.is_relative_to(root) or path.is_relative_to(Path(local["project"]))
            ):
                raise DomainError("HOST_RECEIPT_INVALID", "Deleted-project recovery permits only exact external native key removal")
            values = [step["before"], step["after"]]
        else:
            if deleted_scope:
                raise DomainError("HOST_RECEIPT_INVALID", "Deleted-project recovery cannot replay project files or legacy documents")
            if "kind" in step:
                raise DomainError("HOST_RECEIPT_INVALID", "The recovery step kind is unsupported")
            values = []
            for key in ("before", "after"):
                if key not in step or key + "_digest" not in step:
                    raise DomainError("HOST_RECEIPT_INVALID", "The host recovery hashes are incomplete")
                try:
                    raw = base64.b64decode(step[key], validate=True) if step[key] is not None else None
                except (ValueError, TypeError):
                    raise DomainError("HOST_RECEIPT_INVALID", "The host recovery bytes are invalid") from None
                if (None if raw is None else _digest(raw)) != step[key + "_digest"]:
                    raise DomainError("HOST_RECOVERY_DRIFT", "The host recovery bytes changed")
                # Old durable Claude intents are authenticated and reduced to
                # their owned key; their unowned document is never replayed.
                values.append(_claude_value(_object(raw), local) if local is not None else raw)
        if local is not None:
            if any(value is not None and (not isinstance(value, dict) or canonical_digest(value) != local["digest"]) for value in values):
                raise DomainError("HOST_RECOVERY_DRIFT", "The native key recovery value is not receipt-owned")
            if ((receipt["state"] in {"pending", "installed"} and (values[0] is not None or values[1] is None))
                    or (receipt["state"] in {"removing", "native_removing", "native_finishing", "removed"} and values[1] is not None)):
                raise DomainError("HOST_RECEIPT_INVALID", "The native key recovery direction is invalid")
            plan.append(_ClaudeMutation(path, local, *values))
        else:
            plan.append((path, *values))
    return plan


def _resume(receipt_path: Path, receipt: dict, root: Path, project: _ProjectDir | None) -> None:
    """Replay the durable intent; ``project`` is None only for a deleted project."""
    plan = _intent_plan(receipt, root, deleted_project=project is None)
    _apply(plan, project)
    try:
        _publish_replay(receipt_path, receipt, root, project, plan)
    except DomainError as error:
        # Owned files may already have changed, so no refusal after the replay is not_started.
        raise _after_change(error) from None


def _publish_replay(receipt_path: Path, receipt: dict, root: Path, project: _ProjectDir | None, plan: list) -> None:
    intent_path = _intent_path(receipt)
    if project is not None:
        # A terminal state describes the pinned project itself, re-read in its replayed state.
        if any(project.read(step[0]) != step[2] for step in plan if not isinstance(step, _ClaudeMutation)):
            raise DomainError("HOST_CONFIG_DRIFT", "Owned project configuration changed during recovery; the recovery intent was preserved")
    if receipt["state"] == "pending":
        receipt["installed_files"] = [
            {"path": str(step.path), "digest": _digest(_read_bytes(step.path))}
            if isinstance(step, _ClaudeMutation) else
            {"path": _locator(root, step[0]), "digest": _digest(step[2])}
            for step in plan
        ]
    if receipt["state"] == "removing" and receipt.get("legacy_digest"):
        legacy = _legacy_receipt_path(root, receipt["host"])
        raw = project.read(legacy, 65536)
        if raw is not None:
            if _digest(raw) != receipt["legacy_digest"]:
                raise DomainError("HOST_RECEIPT_DRIFT", "The legacy ownership receipt changed; it was preserved")
            project.unlink(legacy)
    if project is not None:
        # Checked last so the path still names that directory when the state is published.
        project.check()
    # The removal scope comes from the durable receipt, not from whether the root
    # exists now: a native-only removal must never finish as a full ``removed``.
    # Older deleted-project intents were recorded as ``removing`` with only the
    # native key step, so their scope is recovered from the validated plan.
    native_only = (
        receipt["state"] == "removing" and all(isinstance(step, _ClaudeMutation) for step in plan)
        and any(entry["kind"] != "local_mcp" for entry in receipt["ownership"])
    )
    if receipt["state"] == "pending":
        receipt["state"] = "installed"
    elif receipt["state"] in ("native_removing", "native_finishing") or project is None or native_only:
        receipt["state"] = "native_removed"
    else:
        receipt["state"] = "removed"
    _write_receipt(receipt_path, receipt)
    _unlink(intent_path)


def install_host(
    settings: Settings, project_root: Path, binding_id: str, host: str,
    agent_token_file: Path, producer_token_file: Path, *, strict: bool = False, prompt_recall: bool = False,
) -> dict:
    """Install only owned per-project entries; never approve native hook trust."""
    _host(host)
    if host == "omp" and strict:
        raise DomainError("HOST_STRICT_UNSUPPORTED", "OMP has no fail-closed native pre-request gate; strict installation is refused before configuration writes. Uninstall any historical strict adapter and reinstall without --strict")
    root = Path(project_root).resolve(strict=True)
    if not root.is_dir():
        raise DomainError("HOST_PROJECT_INVALID", "The selected project is not a directory")
    ContextCommand(binding_id=binding_id, query="installation", host=host)
    agent, producer = _credentials(Path(agent_token_file), Path(producer_token_file))
    receipt_path = _receipt_path(settings, root, host)
    with _pinned_project(root) as project, _ownership_lock(settings, root, host), _CommandEffect() as effect:
        project.check()
        if _legacy_receipt_path(root, host).exists():
            raise DomainError("HOST_LEGACY_REINSTALL_REQUIRED", "Uninstall the exact owned legacy adapter before reinstalling")
        if receipt_path.exists():
            try:
                receipt = load_receipt(receipt_path, active=False)
            except DomainError as error:
                if host != "omp" or error.code != "HOST_STRICT_UNSUPPORTED":
                    raise
                receipt = load_receipt(receipt_path, allow_legacy=True, active=False)
                if receipt["state"] != "removed":
                    raise
            if receipt["state"] in {"native_removing", "native_finishing", "native_removed"}:
                raise DomainError("HOST_UNINSTALL_INCOMPLETE", "Run host-uninstall for this project to finish removing its owned entries before reinstalling")
            expected = {
                "project_root": str(root), "host": host, "deployment_id": settings.deployment_id,
                "binding_id": binding_id, "realm": settings.realm, "base_url": settings.base_url,
                "agent_token_file": str(agent), "producer_token_file": str(producer), "strict": strict,
                "capabilities": capabilities(host, strict=strict, prompt_recall=prompt_recall),
                "runtime_dir": str(_runtime_dir(settings, root, binding_id, host)),
                "spool_limit_bytes": settings.spool_limit_bytes,
                "max_capture_bytes": min(settings.max_capture_bytes, 32768),
                "max_http_body_bytes": settings.max_http_body_bytes,
                "max_mcp_response_bytes": settings.max_mcp_response_bytes,
            }
            if receipt["state"] in {"pending", "removing"}:
                if any(receipt[key] != value for key, value in expected.items()):
                    raise DomainError("HOST_RECOVERY_SCOPE_CONFLICT", "Retry ownership recovery with the original deployment and install parameters")
                _resume(receipt_path, receipt, root, project)
                effect.changed = True
                if receipt["state"] == "installed":
                    return {"state": "installed", "host": host, "receipt": str(receipt_path), "capabilities": receipt["capabilities"], "native_trust": "not_modified"}
                if receipt["state"] == "native_removed":
                    raise DomainError("HOST_UNINSTALL_INCOMPLETE", "Run host-uninstall for this project to finish removing its owned entries before reinstalling")
            elif receipt["state"] == "installed":
                if any(receipt[key] != value for key, value in expected.items()):
                    raise DomainError("HOST_ALREADY_INSTALLED", "Uninstall the existing owned installation before changing it")
                if any(not _owned_entry_matches(root, entry) for entry in receipt["ownership"]):
                    raise DomainError("HOST_CONFIG_DRIFT", "A changed owned configuration entry was preserved")
                if _intent_path(receipt).exists():
                    _intent_plan(receipt, root)
                    _unlink(_intent_path(receipt))
                return {"state": "installed", "host": host, "receipt": str(receipt_path), "capabilities": receipt["capabilities"], "native_trust": "not_modified", "replay": True}
        owner = uuid.uuid4().hex
        plan, ownership = [], []
        mcp_command = _command(receipt_path, "host-stdio")
        hook_command = _command(receipt_path, "host-hook")
        server = {"type": "stdio", "command": mcp_command[0], "args": mcp_command[1:]}
        if host == "claude":
            _claude_entry(plan, ownership, root, server)
            _hooks(plan, ownership, root, ".claude/settings.local.json", hook_command, host, strict)
        elif host == "codex":
            _toml_entry(plan, ownership, root, mcp_command, owner)
            _hooks(plan, ownership, root, ".codex/hooks.json", hook_command, host, strict)
        else:
            server["instructions"] = False
            _json_entry(plan, ownership, root, ".omp/mcp.json", SERVER_NAME, server)
            relative = ".omp/extensions/agents-memory.ts"
            target = _safe_path(root, relative)
            if target.exists():
                raise DomainError("HOST_ENTRY_CONFLICT", "The existing OMP extension is not owned")
            template = files("agents_memory.host_templates").joinpath("omp.ts").read_text()
            content = template.replace("__HOOK_ARGV__", _json([*hook_command, "--envelope"])).replace("__HOST_INPUT_BYTES__", str(HOST_INPUT_BYTES))
            raw = content.encode()
            plan.append((target, None, raw))
            ownership.append({"path": relative, "kind": "file", "digest": _digest(raw), "created": True})
        receipt = {
            "adapter_version": ADAPTER_VERSION, "installation_id": owner, "host": host,
            "project_root": str(root), "binding_id": binding_id, "deployment_id": settings.deployment_id,
            "realm": settings.realm, "base_url": settings.base_url, "strict": bool(strict),
            "agent_token_file": str(agent), "producer_token_file": str(producer),
            "runtime_dir": str(_runtime_dir(settings, root, binding_id, host)),
            "spool_limit_bytes": settings.spool_limit_bytes,
            "max_capture_bytes": min(settings.max_capture_bytes, 32768),
            "max_http_body_bytes": settings.max_http_body_bytes,
            "max_mcp_response_bytes": settings.max_mcp_response_bytes,
            "context_budget_bytes": HOST_CONTEXT_BYTES,
            "capabilities": capabilities(host, strict=strict, prompt_recall=prompt_recall), "ownership": ownership,
        }
        _begin_intent(receipt_path, receipt, project, plan, "pending")
        effect.changed = True
        _resume(receipt_path, receipt, root, project)
    return {"state": "installed", "host": host, "receipt": str(receipt_path), "capabilities": receipt["capabilities"], "native_trust": "not_modified"}


def _uninstall_result(receipt: dict, host: str, state: str) -> dict:
    result = {"state": state, "host": host, "pending_spool_retained": str(Path(receipt["runtime_dir"]) / "capture.sqlite3"), "native_trust": "not_modified"}
    if state == "native_uninstalled":
        result["project_entries"] = "unverified_absent"
    return result


def uninstall_host(settings: Settings, project_root: Path, host: str, *, project_deleted: bool = False) -> dict:
    """Remove exact owned entries only; any owned drift cancels the whole removal.

    An absent project is cleaned up only on explicit operator acknowledgement. That
    cleanup can verify native entries but not project files, so it records
    ``native_removed`` until the root reappears and a normal uninstall finishes it.
    """
    _host(host)
    requested = Path(project_root).absolute()
    absent = not requested.exists()
    if absent and not project_deleted:
        raise DomainError("HOST_PROJECT_ABSENT", "The project path is absent; restore or mount it, or pass --project-deleted only for a deleted project")
    if project_deleted and not absent:
        raise DomainError("HOST_PROJECT_PRESENT", "The project path exists; uninstall it without --project-deleted")
    if absent and any(path.is_symlink() for path in (requested, *requested.parents)):
        raise DomainError("HOST_PATH_DENIED", "Deleted project cleanup cannot use symlinks")
    root = requested.resolve(strict=not absent)
    receipt_path = _receipt_path(settings, root, host)
    with (nullcontext() if absent else _pinned_project(root)) as project, _ownership_lock(settings, root, host), _CommandEffect() as effect:
        if project is not None:
            project.check()
        legacy = _legacy_receipt_path(root, host)
        if receipt_path.exists():
            receipt = load_receipt(receipt_path, allow_legacy=True, active=False, allow_deleted_project=absent)
        else:
            if absent:
                raise DomainError("HOST_RECEIPT_INVALID", "Deleted project cleanup requires a modern external receipt")
            receipt = load_receipt(legacy, allow_legacy=True, active=False)
            receipt["legacy_digest"] = _digest(_read_bytes(legacy, 65536))
        if (
            receipt["project_root"] != str(root) or receipt["host"] != host
            or receipt["deployment_id"] != settings.deployment_id or receipt["realm"] != settings.realm
            or receipt["runtime_dir"] != str(_runtime_dir(settings, root, receipt["binding_id"], host))
        ):
            raise DomainError("HOST_RECEIPT_INVALID", "The receipt belongs to another project, deployment or host")
        if absent and (
            receipt["adapter_version"] != ADAPTER_VERSION or receipt.get("legacy_digest")
            or receipt.get("state") not in {"installed", "removing", "native_removing", "native_removed", "removed"}
            or (receipt.get("state") in {"removing", "native_removing"} and host != "claude")
        ):
            raise DomainError("HOST_RECEIPT_INVALID", "Deleted project cleanup requires a modern installation or exact native removal recovery")
        if receipt["adapter_version"] != ADAPTER_VERSION:
            receipt["adapter_version"] = ADAPTER_VERSION
            receipt["capabilities"] = capabilities(host, strict=receipt["strict"])
            receipt["context_budget_bytes"] = min(receipt["context_budget_bytes"], HOST_CONTEXT_BYTES)
        if receipt.get("state") == "pending":
            pending = _intent_plan(receipt, root)
            reverse = []
            for step in reversed(pending):
                if isinstance(step, _ClaudeMutation):
                    current = _claude_current(step)
                    if current not in (step.before, step.after):
                        raise DomainError("HOST_CONFIG_DRIFT", "A conflicting owned native MCP entry was preserved")
                    reverse.append(_ClaudeMutation(step.path, step.ownership, current, step.before))
                else:
                    path, before, after = step
                    current = project.read(path)
                    if current not in (before, after):
                        raise DomainError("HOST_CONFIG_DRIFT", "Changed configuration was preserved; reconcile ownership")
                    reverse.append((path, current, before))
            _begin_intent(receipt_path, receipt, project, reverse, "removing")
            effect.changed = True
            _resume(receipt_path, receipt, root, project)
        elif receipt.get("state") in {"removing", "native_removing", "native_finishing"}:
            _resume(receipt_path, receipt, root, project)
            effect.changed = True
        if receipt.get("state") == "removed":
            if _intent_path(receipt).exists():
                _intent_plan(receipt, root)
                _unlink(_intent_path(receipt))
            return _uninstall_result(receipt, host, "uninstalled")
        if receipt.get("state") == "native_removed" and absent:
            return _uninstall_result(receipt, host, "native_uninstalled")
        # ``removed`` is written only after a scan of the current files finds nothing
        # left; a finishing pass stays native-scoped until that verification.
        for _ in range(3):
            finishing = receipt.get("state") == "native_removed"
            plan = _removal_plan(receipt, root, project, receipt_path, finishing=finishing)
            if not plan:
                if project is not None:
                    project.check()
                elif root.exists() or root.is_symlink():
                    raise DomainError("HOST_CONFIG_DRIFT", "The deleted project reappeared; nothing was removed")
                receipt["state"] = "native_removed" if absent else "removed"
                _write_receipt(receipt_path, receipt)
                return _uninstall_result(receipt, host, "native_uninstalled" if absent else "uninstalled")
            state = "native_removing" if absent else ("native_finishing" if finishing else "removing")
            _begin_intent(receipt_path, receipt, project, plan, state)
            effect.changed = True
            _resume(receipt_path, receipt, root, project)
            if absent or receipt["state"] == "removed":
                return _uninstall_result(receipt, host, "native_uninstalled" if absent else "uninstalled")
        raise DomainError("HOST_CONFIG_DRIFT", "Owned project entries kept changing during uninstall; finish removal later")


def _removal_plan(receipt: dict, root: Path, project: _ProjectDir | None, receipt_path: Path, *, finishing: bool) -> list:
    absent = project is None
    documents, original, deletes, plan = {}, {}, [], []
    for entry in receipt["ownership"]:
        if absent:
            if root.exists() or root.is_symlink():
                raise DomainError("HOST_CONFIG_DRIFT", "The deleted project reappeared; nothing was removed")
            if entry["kind"] != "local_mcp":
                path = _owned_path(root, entry["path"])
                if path.exists() or path.is_symlink():
                    raise DomainError("HOST_OWNERSHIP_DRIFT", "A deleted project entry reappeared; nothing was removed")
                continue
        path = _owned_path(root, entry["path"])
        if entry["kind"] == "local_mcp":
            current = _claude_current(_ClaudeMutation(path, entry, None, None))
            if current is None and finishing:
                continue
            if current is None or canonical_digest(current) != entry["digest"]:
                raise DomainError("HOST_OWNERSHIP_DRIFT", "The owned native MCP entry changed; nothing was removed")
            plan.append(_ClaudeMutation(path, entry, current, None))
            continue
        if path not in original:
            original[path] = project.read(path)
        raw = original[path]
        if raw is None:
            if finishing:
                continue
            raise DomainError("HOST_OWNERSHIP_DRIFT", "An owned host entry is missing; nothing was removed")
        kind = entry["kind"]
        if kind == "file":
            if _digest(raw) != entry["digest"]:
                raise DomainError("HOST_OWNERSHIP_DRIFT", "The owned extension changed; nothing was removed")
            deletes.append(path)
        elif kind == "toml":
            block = entry["block"].encode()
            if finishing and raw.count(block) == 0:
                try:
                    remaining = tomllib.loads(raw.decode())
                except (ValueError, UnicodeError):
                    raise DomainError("HOST_OWNERSHIP_DRIFT", "The project TOML configuration is invalid; nothing was removed") from None
                servers = remaining.get("mcp_servers", {})
                if not isinstance(servers, dict):
                    raise DomainError("HOST_OWNERSHIP_DRIFT", "The project MCP table is invalid; nothing was removed")
                if SERVER_NAME not in servers:
                    continue
            if raw.count(block) != 1 or _digest(block) != entry["digest"]:
                raise DomainError("HOST_OWNERSHIP_DRIFT", "The owned MCP table changed; nothing was removed")
            updated = raw.replace(block, b"", 1)
            try:
                parsed = tomllib.loads(updated.decode())
            except (ValueError, UnicodeError):
                raise DomainError("HOST_OWNERSHIP_DRIFT", "The remaining TOML configuration is invalid") from None
            servers = parsed.get("mcp_servers", {})
            if not isinstance(servers, dict) or SERVER_NAME in servers:
                raise DomainError("HOST_OWNERSHIP_DRIFT", "Another MCP definition now owns the same name")
            documents[path] = updated
        else:
            document = documents[path] if path in documents else _object(raw)
            if kind == "mcp":
                servers = document.get("mcpServers", {})
                if finishing and isinstance(servers, dict) and entry["key"] not in servers:
                    continue
                if not isinstance(servers, dict) or canonical_digest(servers.get(entry["key"])) != entry["digest"]:
                    raise DomainError("HOST_OWNERSHIP_DRIFT", "The owned MCP entry changed; nothing was removed")
                del servers[entry["key"]]
                if not servers:
                    document.pop("mcpServers", None)
            else:
                hooks = document.get("hooks", {})
                groups = hooks.get(entry["event"], []) if isinstance(hooks, dict) else []
                if not isinstance(groups, list):
                    raise DomainError("HOST_OWNERSHIP_DRIFT", "The owned hook event changed")
                matches = [index for index, group in enumerate(groups) if canonical_digest(group) == entry["digest"]]
                if finishing and not matches:
                    continue
                if len(matches) != 1:
                    raise DomainError("HOST_OWNERSHIP_DRIFT", "The owned hook changed or duplicated; nothing was removed")
                groups.pop(matches[0])
                if not groups:
                    hooks.pop(entry["event"], None)
                if not hooks:
                    document.pop("hooks", None)
            documents[path] = document
    for path in {_owned_path(root, entry["path"]) for entry in receipt["ownership"] if entry["kind"] == "hook" and not absent}:
        document = documents.get(path)
        if document is None:
            if original.get(path) is None:
                continue
            document = _object(original[path])
        hooks = document.get("hooks", {})
        if not isinstance(hooks, dict) or any(
            isinstance(groups, list) and any(_hook_group_references(group, receipt_path) for group in groups)
            for groups in hooks.values()
        ):
            raise DomainError("HOST_OWNERSHIP_DRIFT", "A changed or moved hook for this installation remains; nothing was removed")
    for path, document in documents.items():
        after = document if isinstance(document, bytes) else (_json(document) + "\n").encode()
        if (not after.strip() or not document) and all(e.get("created") for e in receipt["ownership"] if _owned_path(root, e["path"]) == path):
            deletes.append(path)
        else:
            plan.append((path, original[path], after))
    for path, before in original.items():
        if project.read(path) != before:
            raise DomainError("HOST_CONFIG_DRIFT", "Configuration changed before uninstall; nothing was removed")
    plan.extend((path, original[path], None) for path in deletes)
    return plan


def _identity(receipt: dict, event: dict) -> dict:
    host = receipt["host"]
    session = event.get("session_id")
    agent = event.get("agent_id")
    thread = event.get("thread_id")
    transcript = event.get("transcript_path")
    turn = event.get("prompt_id") if host == "claude" else event.get("turn_id")
    native_turn = turn
    if host == "omp":
        native_agent = event.get("agent")
        if not isinstance(native_agent, dict) or native_agent.get("kind") not in {"main", "sub"} or not native_agent.get("id"):
            raise DomainError("HOST_LINEAGE_UNRESOLVED", "OMP requires ctx.agent-scoped native identity")
        agent = _json({key: native_agent.get(key) for key in ("kind", "id", "parentId", "depth")})
        thread = session
        # before_agent_start/input expose no native stable turn ID in 18.9.1.
        native_turn = None
        turn = event.get("adapter_turn_id")
    known = isinstance(session, str) and bool(session) and (host != "codex" or bool(thread or transcript or agent))
    if event.get("agent_type") and not event.get("agent_id") and host == "claude":
        known = False
    instance = event.get("hook_instance_id")
    if not isinstance(instance, str) or not instance:
        instance = uuid.uuid4().hex
    identity = {"session": session, "thread": thread, "transcript_locator": transcript, "agent": agent or "main_or_unobservable", "host": host, "installation": receipt["installation_id"]}
    if not known:
        identity["limited_hook_instance"] = instance
    root = f"{host}:{session}" if isinstance(session, str) and session else None
    if host == "omp" and event["agent"]["kind"] == "sub":
        # ctx.agent identifies the child, but does not attest its root session.
        root = None
    return {
        "key": canonical_digest(identity), "root": root,
        "path": canonical_digest({"thread": thread, "locator": transcript, "agent": agent}),
        "turn": str(turn) if isinstance(turn, (str, int)) and not isinstance(turn, bool) and str(turn) else None,
        "instance": instance, "limited": not known,
        "native_turn": str(native_turn) if isinstance(native_turn, (str, int)) and not isinstance(native_turn, bool) and str(native_turn) else None,
    }


def _scoped_cwd(receipt: dict, event: dict) -> Path:
    value = event.get("cwd")
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        raise DomainError("HOST_SCOPE_UNRESOLVED", "The native event has no scoped absolute cwd")
    root = Path(receipt["project_root"])
    cwd = Path(value).resolve()
    if not cwd.is_relative_to(root):
        raise DomainError("HOST_SCOPE_UNRESOLVED", "The native event is outside the registered project")
    return cwd


def _footprint(receipt: dict, event: dict, cwd: Path) -> tuple[str, ...]:
    name = event.get("tool_name")
    inputs = event.get("tool_input")
    host = receipt["host"]
    allowed = {"claude": {"Write", "Edit", "NotebookEdit", "Read"}, "codex": set(), "omp": {"write", "edit", "read"}}
    if name not in allowed[host] or not isinstance(inputs, dict):
        raise DomainError("HOST_FOOTPRINT_UNSUPPORTED", "Shell, hosted and unknown action footprints are not enforceable")
    paths = []
    field = "notebook_path" if name == "NotebookEdit" else "file_path" if host == "claude" else "path"
    raw_paths = [inputs.get(field)]
    root = Path(receipt["project_root"])
    for raw in raw_paths:
        if not isinstance(raw, str) or not raw or "\x00" in raw or "://" in raw:
            raise DomainError("HOST_FOOTPRINT_UNKNOWN", "The action does not expose a local path")
        path = (cwd / raw).resolve()
        if not path.is_relative_to(root):
            raise DomainError("HOST_SCOPE_UNRESOLVED", "The action leaves the registered project")
        paths.append(path.relative_to(root).as_posix())
    return tuple(sorted(set(paths)))


def _context_prefix(code: str | None = None) -> str:
    return (code + "\n" if code else "") + BOUNDED_CONTEXT_MARKER + "\n"


def _rule_stamps(value: object, code: str) -> None:
    if not isinstance(value, list) or len(value) > 128:
        raise DomainError(code, "The rule stamps are invalid")
    for rule in value:
        if (
            not isinstance(rule, list) or len(rule) != 3
            or not isinstance(rule[0], str) or re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", rule[0]) is None
            or type(rule[1]) is not int or not 1 <= rule[1] <= 9223372036854775807
            or not isinstance(rule[2], str) or re.fullmatch(r"[a-f0-9]{64}", rule[2]) is None
        ):
            raise DomainError(code, "The rule stamps are invalid")


def _validate_generation_state(state: object) -> None:
    code = "HOST_STATE_INVALID"
    if not isinstance(state, dict) or set(state) != {"generation", "turn", "offered", "gaps"}:
        raise DomainError(code, "The persisted generation state is invalid")
    generation, turn, offered, gaps = (state[key] for key in ("generation", "turn", "offered", "gaps"))
    if type(generation) is not int or not 0 <= generation <= 9223372036854775807:
        raise DomainError(code, "The persisted generation counter is invalid")
    if turn is not None and (not isinstance(turn, str) or not turn or len(turn.encode()) > HOST_STATE_BYTES):
        raise DomainError(code, "The persisted turn identity is invalid")
    if not isinstance(gaps, dict) or len(gaps) > 128 or any(
        not isinstance(key, str) or not 1 <= len(key) <= 128
        or type(count) is not int or not 0 <= count <= 9223372036854775807
        for key, count in gaps.items()
    ):
        raise DomainError(code, "The persisted capture gaps are invalid")
    if offered is not None:
        if not isinstance(offered, dict) or set(offered) != {"rules", "digest", "generation"}:
            raise DomainError(code, "The persisted context offer is invalid")
        if (
            turn is None or type(offered["generation"]) is not int or offered["generation"] != generation
            or not isinstance(offered["digest"], str) or re.fullmatch(r"[a-f0-9]{64}", offered["digest"]) is None
        ):
            raise DomainError(code, "The persisted context offer is invalid")
        _rule_stamps(offered["rules"], code)


def _generation_state(raw: bytes | None) -> dict:
    if raw is None:
        return {"generation": 0, "turn": None, "offered": None, "gaps": {}}
    try:
        state = decode_json(raw)
    except (ValueError, UnicodeError):
        raise DomainError("HOST_STATE_INVALID", "The persisted generation state is invalid") from None
    _validate_generation_state(state)
    return state


def _context(receipt: dict, query: str, paths: tuple[str, ...] | None, *, required: bool) -> dict:
    denial_code = max(ACTION_CONTEXT_CODES, key=len) if required and receipt["strict"] and receipt["host"] != "omp" else None
    budget = min(receipt["context_budget_bytes"], HOST_CONTEXT_BYTES) - len(_context_prefix(denial_code).encode())
    command = ContextCommand(
        binding_id=receipt["binding_id"], query=query, paths=paths,
        host=receipt["host"], max_bytes=budget,
    )
    result = LocalClient(receipt["base_url"], Path(receipt["agent_token_file"]), timeout=4).request(
        "/api/required-context" if required else "/api/context", command.model_dump(mode="json"),
    )
    text, stamp, rules = result.get("context"), result.get("stamp"), result.get("required")
    if not isinstance(text, str) or not isinstance(stamp, dict) or (required and not isinstance(rules, bool)):
        raise DomainError("HOST_CONTEXT_INVALID", "The service returned an invalid context receipt")
    _rule_stamps(stamp.get("rules"), "HOST_CONTEXT_INVALID")
    size = len(text.encode())
    if size > budget or type(result.get("context_bytes")) is not int or result["context_bytes"] != size:
        raise DomainError("REQUIRED_CONTEXT_OVERFLOW", "The complete context exceeds its byte budget")
    return result


def _capture(receipt: dict, event: dict, identity: dict, event_name: str) -> dict:
    host = receipt["host"]
    if event.get("injected") is True or event.get("speaker") == "memory":
        return {"state": "excluded", "code": "CAPTURE_INJECTED_REJECTED"}
    body = event.get("text") if host == "omp" else event.get("prompt")
    if isinstance(body, str) and BOUNDED_CONTEXT_MARKER in body:
        return {"state": "excluded", "code": "CAPTURE_INJECTED_REJECTED"}
    if host == "claude" and event_name == "UserPromptSubmit":
        return {"state": "gap", "code": "HOST_PROMPT_ORIGIN_UNOBSERVABLE"}
    if host == "codex" and event_name == "UserPromptSubmit" and event.get("agent_id"):
        return {"state": "gap", "code": "HOST_CHILD_PROMPT_ORIGIN_UNOBSERVABLE"}
    if (host == "omp" and event_name == "input" and event.get("source") not in {"interactive", "rpc"}):
        return {"state": "gap", "code": "HOST_INPUT_SOURCE_UNSUPPORTED"}
    if event_name not in {"input", "UserPromptSubmit", "capture_finding", "capture_correction"}:
        return {"state": "excluded", "code": "NOT_A_CAPTURE_EVENT"}
    if event_name in {"capture_finding", "capture_correction"} and host != "omp":
        return {"state": "excluded", "code": "HOST_CAPTURE_EVENT_UNSUPPORTED"}
    if not isinstance(body, str) or not body.strip():
        return {"state": "excluded", "code": "CAPTURE_EMPTY"}
    if host == "omp" and event_name == "input" and body.lstrip().split(maxsplit=1)[0] in {"/memory-finding", "/memory-correction"}:
        return {"state": "excluded", "code": "EXPLICIT_CAPTURE_COMMAND"}
    if len(body.encode()) > receipt["max_capture_bytes"]:
        return {"state": "gap", "code": "CAPTURE_TOO_LARGE"}
    native_event = identity["native_turn"] or identity["instance"]
    origin = "host:" + canonical_digest({"host": host, "root": identity["root"], "path": identity["path"], "event": event_name, "native_event": native_event})
    command = CaptureCommand(
        binding_id=receipt["binding_id"], idempotency_key=origin, origin_key=origin, body=body,
        speaker="human", root_run_id=identity["root"], agent_path=identity["path"],
        kind="finding" if event_name == "capture_finding" else "correction" if event_name == "capture_correction" else "conversation",
    )
    spool = None
    try:
        spool = ProducerSpool(Path(receipt["runtime_dir"]) / "capture.sqlite3", receipt["deployment_id"], receipt["binding_id"], receipt["spool_limit_bytes"])
        enqueue_error = None
        try:
            accepted = spool.enqueue(command)
        except DomainError as error:
            enqueue_error = error
            accepted = {"state": "gap", "code": error.code}
        result = spool.flush(LocalClient(receipt["base_url"], Path(receipt["producer_token_file"]), timeout=1), limit=4)
        delivery = {"state": "gap"} if enqueue_error else spool.disposition(command.idempotency_key)
        return {
            **accepted, **result,
            **delivery,
            "semantic_ready": "not_claimed",
            "identity": "native_event" if identity["native_turn"] else "hook_instance_only",
        }
    except (sqlite3.Error, OSError):
        return {"state": "gap", "code": "HOST_SPOOL_UNAVAILABLE", "gaps": {"HOST_SPOOL_UNAVAILABLE": 1}}
    except DomainError as error:
        return {"state": "gap", "code": error.code}
    finally:
        if spool is not None:
            spool.close()


def _native_result(host: str, event_name: str, *, code: str | None = None, text: str | None = None, strict: bool = False, max_bytes: int = HOST_CONTEXT_BYTES) -> dict:
    denied = host != "omp" and code is not None and strict and (not event_name or event_name in ACTION_EVENTS | PROMPT_EVENTS | {"input", "before_provider_request"})
    stdout = {}
    offered = _context_prefix() + text if text else None
    reason = code + "\n" + offered if code and offered else code
    if offered and len((reason if denied else offered).encode()) > min(max_bytes, HOST_CONTEXT_BYTES):
        return _native_result(host, event_name, code="REQUIRED_CONTEXT_OVERFLOW", strict=strict, max_bytes=max_bytes)
    if host == "omp":
        stdout = {}
        if offered:
            stdout["additionalContext"] = offered
    elif not event_name and denied:
        stdout = {"decision": "block", "reason": reason} if host == "codex" else {"continue": False, "stopReason": reason}
    elif event_name == "PreToolUse" and denied:
        stdout = {"hookSpecificOutput": {"hookEventName": event_name, "permissionDecision": "deny", "permissionDecisionReason": reason}}
    elif event_name == "UserPromptSubmit" and denied:
        stdout = {"decision": "block", "reason": reason}
    elif offered:
        stdout = {"hookSpecificOutput": {"hookEventName": event_name, "additionalContext": offered}}
    elif code:
        stdout = {"systemMessage": "agents-memory: " + code}
    if code and not denied:
        stdout["warning" if host == "omp" else "systemMessage"] = "agents-memory: " + code
    return {"host": host, "event": event_name, "exit_code": 0, "stdout": stdout, "stderr": "", "state": "blocked" if denied else "degraded" if code else "ok", "code": code, "provider_input_observed": False}


def _project_hook(event: object) -> dict:
    if not isinstance(event, dict):
        raise DomainError("HOST_ENVELOPE_INVALID", "The native hook input must be an object")
    pending = [(event, 0)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if depth > 24 or nodes > 65536 or len(pending) > 65536:
            raise DomainError("HOST_ENVELOPE_INVALID", "The native hook structure exceeds its bound")
        if isinstance(item, (dict, list)) and len(item) > 65536:
            raise DomainError("HOST_ENVELOPE_INVALID", "The native hook structure exceeds its bound")
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
        elif isinstance(item, float) and not math.isfinite(item):
            raise DomainError("HOST_ENVELOPE_INVALID", "Non-finite native input is invalid")
    keys = {
        "hook_event_name", "event", "cwd", "session_id", "agent_id", "thread_id",
        "transcript_path", "prompt_id", "turn_id", "agent_type", "agent",
        "hook_instance_id", "adapter_turn_id", "model_api", "tool_name", "tool_use_id",
        "prompt", "text", "source", "injected", "speaker",
    }
    projected = {key: value for key, value in event.items() if key in keys}
    if "tool_input" in event:
        inputs = event["tool_input"]
        projected["tool_input"] = {
            key: inputs[key] for key in ("file_path", "path", "notebook_path") if key in inputs
        } if isinstance(inputs, dict) else inputs
    try:
        raw = _json(projected).encode("utf-8")
        if len(raw) > HOST_PROJECTION_BYTES:
            raise ValueError("projected input exceeds bound")
        return decode_json(raw)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise DomainError("HOST_ENVELOPE_INVALID", "The complete native authority projection is invalid") from None


def handle_hook_input(receipt_path: Path, raw: bytes) -> dict:
    event = None
    try:
        if not isinstance(raw, bytes) or len(raw) > HOST_INPUT_BYTES:
            raise ValueError("native input exceeds bound")

        def unique_pairs(pairs):
            value = {}
            for key, child in pairs:
                if key in value:
                    raise ValueError("duplicate native JSON key")
                value[key] = child
            return value

        event = json.loads(raw, object_pairs_hook=unique_pairs)
    except (DomainError, ValueError, TypeError, UnicodeError, RecursionError):
        path = None
        try:
            path = Path(receipt_path)
            receipt = load_receipt(path)
        except Exception as error:
            host = path.stem if path is not None else "claude"
            host = host if host in HOST_VERSIONS else "claude"
            code = error.code if isinstance(error, DomainError) and error.code in _RECEIPT_REFUSAL_CODES else "HOST_RECEIPT_UNAVAILABLE"
            return _native_result(host, "", code=code, strict=True)
        name = event.get("hook_event_name", event.get("event", "")) if isinstance(event, dict) else ""
        name = name if isinstance(name, str) and len(name) <= 128 else ""
        return _native_result(receipt["host"], name, code="HOST_ENVELOPE_INVALID", strict=receipt["strict"])
    return handle_hook(receipt_path, event)


def handle_hook(receipt_path: Path, event: dict) -> dict:
    """Decode native stdin envelopes without transcript reads or provider-trace capture.

    Offered text, hook retries, a warmup callback and a response notification never
    authorize required actions. These native interfaces cannot attest the final
    subsequent model input. OMP callbacks are advisory; strict OMP installation
    is refused before writing native configuration.
    """
    event_name = event.get("hook_event_name", event.get("event", "")) if isinstance(event, dict) else ""
    if not isinstance(event_name, str) or len(event_name) > 128:
        event_name = ""
    try:
        receipt_path = Path(receipt_path)
        receipt = load_receipt(receipt_path)
    except Exception as error:
        host = receipt_path.stem if isinstance(receipt_path, Path) and receipt_path.stem in HOST_VERSIONS else "claude"
        code = error.code if isinstance(error, DomainError) and error.code in _RECEIPT_REFUSAL_CODES else "HOST_RECEIPT_UNAVAILABLE"
        return _native_result(host, event_name, code=code, strict=True)
    host = receipt["host"]
    strict = receipt["strict"]
    try:
        event = _project_hook(event)
        cwd = _scoped_cwd(receipt, event)
        if event_name in ACTION_EVENTS:
            tool_name = event.get("tool_name")
            core_prefix = "mcp__agents_memory_" if host == "omp" else "mcp__agents-memory__"
            core_tools = {"memory_context", "memory_inspect", "memory_record", "memory_feedback"}
            delegated = isinstance(tool_name, str) and tool_name in {core_prefix + tool for tool in core_tools}
            if delegated or (not strict and tool_name not in receipt["capabilities"]["supported_path_tools"]):
                result = _native_result(host, event_name)
                result["state"] = "delegated" if delegated else "outside_advisory_coverage"
                return result
        identity = _identity(receipt, event)
        runtime = Path(receipt["runtime_dir"])
        state_path = runtime / (identity["key"] + ".json")
        with _lock(runtime / (identity["key"] + ".lock")):
            state = _generation_state(_read_bytes(state_path, HOST_STATE_BYTES))
            if event_name in LIFECYCLE_EVENTS:
                state["generation"] += 1
                state["turn"], state["offered"] = None, None
                result = _native_result(host, event_name)
            elif event_name in PROVIDER_EVENTS:
                # No payload, headers, request IDs or provider bodies are persisted.
                result = _native_result(host, event_name, code="HOST_PROVIDER_INPUT_UNOBSERVABLE", strict=strict)
            elif event_name in ACTION_EVENTS:
                paths = _footprint(receipt, event, cwd)
                if identity["limited"] or not identity["turn"] or state["turn"] != identity["turn"]:
                    raise DomainError("HOST_GENERATION_UNOBSERVED", "The action has no current prompt generation")
                context = _context(receipt, "Protected action conventions", paths, required=True)
                if context["required"]:
                    code = "HOST_PROVIDER_INPUT_UNOBSERVABLE"
                    if state["offered"] and not {tuple(rule) for rule in context["stamp"]["rules"]}.issubset(
                        {tuple(rule) for rule in state["offered"]["rules"]}
                    ):
                        code = "HOST_CONTEXT_STALE"
                    result = _native_result(host, event_name, code=code, text=context["context"], strict=strict, max_bytes=receipt["context_budget_bytes"])
                else:
                    result = _native_result(host, event_name)
            elif event_name in PROMPT_EVENTS:
                turn = identity["turn"] or identity["instance"]
                same_turn = state["turn"] == turn
                if not same_turn:
                    state["generation"] += 1
                    state["turn"], state["offered"] = turn, None
                capture = _capture(receipt, event, identity, event_name) if event_name == "UserPromptSubmit" else None
                if strict and host == "codex":
                    result = _native_result(host, event_name, code="HOST_HOSTED_TOOL_GUARD_UNAVAILABLE", strict=True)
                elif host != "omp" and same_turn and state["offered"]:
                    result = _native_result(host, event_name)
                elif receipt["capabilities"]["prompt_context"] == "disabled":
                    result = _native_result(host, event_name)
                    result["offered"] = False
                else:
                    prompt = event.get("prompt", "")
                    if isinstance(prompt, str) and prompt.strip() and len(prompt) <= 4096:
                        context = _context(receipt, prompt, None, required=False)
                        state["offered"] = {"rules": context["stamp"]["rules"], "digest": _digest(context["context"].encode()), "generation": state["generation"]}
                        result = _native_result(host, event_name, text=context["context"], max_bytes=receipt["context_budget_bytes"])
                        result["offered"] = True
                    else:
                        result = _native_result(host, event_name)
                        result["offered"] = False
                if capture is not None:
                    result["capture"] = capture
            elif event_name in {"input", "capture_finding", "capture_correction"}:
                capture = _capture(receipt, event, identity, event_name)
                result = _native_result(host, event_name)
                result["capture"] = capture
            else:
                result = _native_result(host, event_name, code="HOST_EVENT_UNSUPPORTED", strict=strict)
            capture = result.get("capture")
            if isinstance(capture, dict) and (capture.get("state") == "gap" or capture.get("pending") or capture.get("quarantined") or capture.get("errors") or capture.get("gaps")):
                code = capture.get("code") or "HOST_CAPTURE_DEGRADED"
                state["gaps"][code] = state["gaps"].get(code, 0) + 1
                if result["state"] == "ok":
                    result["state"] = "degraded"
                result["stdout"].setdefault("systemMessage" if host != "omp" else "warning", "agents-memory: " + code)
            result["generation"] = state["generation"]
            result["identity"] = "limited_hook_instance" if identity["limited"] else "native_scoped"
            result["turn_identity"] = "native_event" if identity["native_turn"] else "adapter_hook_instance_only"
            result["gaps"] = state["gaps"]
            if event_name in ACTION_EVENTS:
                result["enforcement_dimensions"] = receipt["capabilities"]["action_dimensions"]
            _validate_generation_state(state)
            encoded_state = _json(state) + "\n"
            if len(encoded_state.encode()) > HOST_STATE_BYTES:
                raise DomainError("HOST_STATE_INVALID", "The persisted generation state exceeds its byte bound")
            private_write(state_path, encoded_state, replace=state_path.exists())
            return result
    except DomainError as error:
        result = _native_result(host, event_name, code=error.code, strict=strict)
        if event_name in ACTION_EVENTS:
            result["enforcement_dimensions"] = receipt["capabilities"]["action_dimensions"]
        return result
    except sqlite3.Error:
        return _native_result(host, event_name, code="HOST_SPOOL_UNAVAILABLE", strict=strict)
    except Exception:
        return _native_result(host, event_name, code="HOST_ADAPTER_UNAVAILABLE", strict=strict)
