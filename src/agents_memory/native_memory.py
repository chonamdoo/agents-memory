from __future__ import annotations

import os
import stat
import tomllib
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from pathlib import Path

from .domain import DomainError
from .wire import decode_json

_MAX_BYTES = 65536
_UNKNOWN = "Native metadata is unavailable or ambiguous; disabled or absent memory is not established."
_LINGERING = "Native storage remains; disabling memory does not erase it or revoke context already loaded."


def _absolute(value: str | Path, home: Path | None = None) -> Path | None:
    raw = str(value)
    if raw.startswith("~/") and home is not None:
        raw = str(home / raw[2:])
    if not raw or len(raw) > 4096 or "\x00" in raw:
        return None
    path = Path(raw)
    return path if path.is_absolute() and ".." not in path.parts and len(path.parts) <= 128 else None


@contextmanager
def _opened(path: Path, *, directory: bool = False) -> Generator[int, None, None]:
    if _absolute(path) is None:
        raise ValueError
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    descriptor = os.open(path.anchor, flags | os.O_DIRECTORY)
    try:
        for index, part in enumerate(path.parts[1:]):
            is_directory = directory or index < len(path.parts) - 2
            child = os.open(part, flags | (os.O_DIRECTORY if is_directory else 0), dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
            info = os.fstat(descriptor)
            if is_directory and (not info.st_mode & 0o444 or not info.st_mode & 0o111):
                raise ValueError
        yield descriptor
    finally:
        os.close(descriptor)


def _load(path: Path, *, toml: bool = False) -> tuple[dict, str]:
    try:
        with _opened(path) as descriptor:
            before = os.fstat(descriptor)
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_uid != os.getuid()
                    or not before.st_mode & 0o444 or before.st_size > _MAX_BYTES):
                raise ValueError
            chunks = []
            remaining = _MAX_BYTES + 1
            while remaining:
                chunk = os.read(descriptor, remaining)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            after = os.fstat(descriptor)
            if len(raw) > _MAX_BYTES or any(
                getattr(before, field) != getattr(after, field)
                for field in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_nlink", "st_mode")
            ):
                raise ValueError
        return (tomllib.loads(raw.decode("utf-8")) if toml else decode_json(raw)), "available"
    except FileNotFoundError:
        return {}, "absent"
    except (OSError, ValueError, RecursionError):
        return {}, "unknown"


def _directory(path: Path | None) -> str:
    if path is None:
        return "unknown"
    try:
        with _opened(path, directory=True):
            return "present"
    except FileNotFoundError:
        return "absent"
    except (OSError, ValueError):
        return "unknown"


def _claude_storage(root: Path | None) -> str:
    if root is None:
        return "unknown"
    present = False
    try:
        with _opened(root / "projects", directory=True) as descriptor, os.scandir(descriptor) as entries:
            for index, entry in enumerate(entries):
                if index >= 128:
                    return "unknown"
                state = _directory(root / "projects" / entry.name / "memory")
                if state == "unknown":
                    return "unknown"
                present = present or state == "present"
    except FileNotFoundError:
        return "absent"
    except (OSError, ValueError):
        return "unknown"
    return "present" if present else "absent"


def _root(environment: Mapping[str, str], variable: str, home: Path | None, default: str) -> Path | None:
    if variable in environment:
        return _absolute(environment[variable], home)
    return home / default if home is not None else None


def _selected(layers: list[tuple[str, dict, str]], key: str, kind: type) -> tuple[object, str | None]:
    for label, document, state in reversed(layers):
        if state == "unknown":
            return None, "unavailable"
        if key in document:
            value = document[key]
            return (value, label) if type(value) is kind else (None, "unavailable")
    return None, None


def _configuration(value: bool | None) -> str:
    return "unknown" if value is None else "configured_enabled" if value else "configured_disabled"


def _claude(project: Path, home: Path | None, environment: Mapping[str, str]) -> dict:
    root = _root(environment, "CLAUDE_CONFIG_DIR", home, ".claude")
    user = _load(root / "settings.json") if root is not None else ({}, "unknown")
    layers = [("user", *user), ("project", *_load(project / ".claude/settings.json")),
              ("project_local", *_load(project / ".claude/settings.local.json"))]
    enabled, source = _selected(layers, "autoMemoryEnabled", bool)
    disable = environment.get("CLAUDE_CODE_DISABLE_AUTO_MEMORY")
    if disable in ("0", "1"):
        enabled, source = disable == "0", "diagnostic_process_environment"
    elif disable not in (None, ""):
        enabled, source = None, "unavailable"
    settings_environment = any(
        "env" in document and (
            not isinstance(document["env"], dict) or "CLAUDE_CODE_DISABLE_AUTO_MEMORY" in document["env"]
        ) for _, document, _ in layers
    )
    if settings_environment:
        enabled, source = None, "settings_environment_unresolved"
    elif disable in ("0", "1") and any(state == "unknown" for _, _, state in layers):
        enabled, source = None, "unavailable"
    directory, directory_source = _selected(layers, "autoMemoryDirectory", str)
    storage = (_directory(_absolute(directory, home)) if isinstance(directory, str) else
               "unknown" if directory_source == "unavailable" else _claude_storage(root))
    warnings = [
        "Managed/session settings, native session type, workspace trust and repository/main-worktree settings are unresolved.",
        "Default storage is native-home directory metadata, not attribution to this current project.",
        "Environment observations describe this diagnostic process, not an already-running Claude process; settings env and session startup may differ.",
    ]
    if source == "unavailable" or storage == "unknown":
        warnings.append(_UNKNOWN)
    if directory_source in ("project", "project_local"):
        warnings.append("Repository-selected memory directory activation depends on native trust and outside-directory policy.")
    if enabled is False and storage == "present":
        warnings.append(_LINGERING)
    return {"configuration": _configuration(enabled if isinstance(enabled, bool) else None),
            "source": source, "storage": storage, "warnings": warnings}


def _boolean(document: dict, section: str, key: str) -> tuple[bool | None, bool]:
    values = document.get(section, {})
    if not isinstance(values, dict):
        return None, True
    if key not in values:
        return None, False
    value = values[key]
    return (value, False) if type(value) is bool else (None, True)


def _codex(project: Path, home: Path | None, environment: Mapping[str, str]) -> dict:
    root = _root(environment, "CODEX_HOME", home, ".codex")
    user, state = _load(root / "config.toml", toml=True) if root is not None else ({}, "unknown")
    local, local_state = _load(project / ".codex/config.toml", toml=True)
    feature, bad_feature = _boolean(user, "features", "memories")
    use, bad_use = _boolean(user, "memories", "use_memories")
    generate, bad_generate = _boolean(user, "memories", "generate_memories")
    local_feature, bad_local = _boolean(local, "features", "memories")
    uncertain = (state == "unknown" or local_state == "unknown" or bad_feature or bad_use or bad_generate
                 or bad_local or local_feature is not None or "memories" in local
                 or "profile" in local or "profiles" in local or "profile" in user or bool(user.get("profiles")))
    consumption = generation = None
    if not uncertain:
        consumption = False if feature is False or use is False else True if feature is True and use is True else None
        generation = False if feature is False or generate is False else True if feature is True and generate is True else None
    storage = _directory(root / "memories") if root is not None else "unknown"
    warnings = [
        "CLI/managed/profile/ancestor overrides, project trust and native runtime activation are unresolved; omitted defaults remain unknown.",
    ]
    if uncertain or storage == "unknown":
        warnings.append(_UNKNOWN)
    if generate is False:
        warnings.append("Generation disabled does not disable consumption of existing native memory.")
    if storage == "present" and (consumption is False or generation is False):
        warnings.append(_LINGERING)
    return {"configuration": _configuration(consumption), "generation": _configuration(generation),
            "controls": {"features.memories": feature, "memories.use_memories": use,
                         "memories.generate_memories": generate}, "storage": storage, "warnings": warnings}


def native_memory_status(
    project: Path, *, home: Path | None = None, environment: Mapping[str, str] | None = None,
) -> dict:
    """Observe configuration metadata; never change native settings or read memory bodies."""
    selected = os.environ if environment is None else environment
    selected_home = _absolute(home) if home is not None else _absolute(selected.get("HOME", ""))
    if selected_home is None and home is None and environment is None:
        try:
            selected_home = _absolute(Path.home())
        except (OSError, RuntimeError, ValueError):
            pass
    try:
        root = project.resolve(strict=True)
    except (OSError, ValueError, RuntimeError):
        raise DomainError("HOST_PROJECT_INVALID", "Choose an existing project directory") from None
    if not root.is_dir():
        raise DomainError("HOST_PROJECT_INVALID", "Choose an existing project directory")
    return {
        "schema_version": 1,
        "evidence": "configuration_metadata_not_runtime_activation",
        "claude": _claude(root, selected_home, selected),
        "codex": _codex(root, selected_home, selected),
        "warnings": ["Native memory is independent of agents-memory and may add duplicate or conflicting context; nothing is disabled automatically."],
        "limits": ["No memory bodies, authentication files, trust databases or native processes are inspected.",
                   "Directory presence does not prove activation, consumption or current-project identity.",
                   "Metadata reads are bounded; settings, permissions, trust and native storage are never changed."],
    }
