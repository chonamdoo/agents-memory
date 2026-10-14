from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import secrets
import stat
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from .config import Settings, prepare_settings_upgrade
from .domain import DomainError, EffectState, Handle
from .journal import DeletionJournal
from .migrations import migrate
from .ops import _dsn, authority_lock
from .private_io import private_read, private_write
from .store import Store

_INTENT = "initialization-intent.json"
_RESULT = "initialization-result.json"
_SCOPE_FIELDS = (
    "deployment_id", "realm", "mode", "capability", "database_dsn", "migrator_dsn", "state_dir", "journal_dir", "port",
)


def _encoded(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _digest(value: dict) -> str:
    return hashlib.sha256(_encoded(value)).hexdigest()


def _signed(value: dict, token: str) -> bytes:
    key = hashlib.sha256(("deployment-initialization\0" + token).encode()).digest()
    return _encoded({**value, "mac": hmac.new(key, _encoded(value), hashlib.sha256).hexdigest()})


def _denied() -> DomainError:
    return DomainError("INIT_SCOPE_DENIED", "The initialization intent, ownership or requested outputs do not match", status=403)


def _path(path: Path) -> Path:
    path = path.expanduser().absolute()
    if ".." in path.parts or any(parent.is_symlink() for parent in (*path.parents, path)):
        raise DomainError("PATH_DENIED", "Initialization cannot traverse a symlink or parent alias")
    if any(parent.exists() and not parent.is_dir() for parent in path.parents):
        raise DomainError("PATH_DENIED", "Initialization output ancestors must be directories")
    return path


def _directory(path: Path) -> None:
    if not path.exists():
        return
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise DomainError("PATH_DENIED", "Initialization requires owned private authority and journal directories")


def _exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _output(path: Path, expected: bytes | None, *, required: bool = False) -> None:
    parent = path.parent
    while not parent.exists():
        parent = parent.parent
    info = parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or not os.access(parent, os.W_OK | os.X_OK):
        raise DomainError("PATH_DENIED", "Initialization outputs require an owned writable parent directory")
    if not _exists(path):
        if required:
            raise _denied()
        return
    if expected is None:
        raise DomainError("OUTPUT_EXISTS", "Initialization never overwrites an existing output")
    if private_read(path, 262144) != expected:
        raise _denied()


def _publish(path: Path, raw: bytes) -> None:
    if _exists(path):
        _output(path, raw)
        return
    try:
        private_write(path, raw)
    except FileExistsError:
        _output(path, raw)


def _record(path: Path, token: str | None = None) -> dict:
    try:
        value = json.loads(private_read(path, 262144))
        if not isinstance(value, dict):
            raise _denied()
        if token is None:
            token = value.get("operator_token")
        if not isinstance(token, str) or not 32 <= len(token.encode()) <= 4096:
            raise _denied()
        unsigned = {name: item for name, item in value.items() if name != "mac"}
        if not hmac.compare_digest(_signed(unsigned, token), _encoded(value)):
            raise _denied()
        return unsigned
    except (OSError, ValueError, TypeError, RecursionError):
        raise _denied() from None


def _intent(path: Path) -> dict | None:
    if not _exists(path):
        return None
    value = _record(path)
    request_fields = set(_SCOPE_FIELDS) | {"owner_id", "config_path", "operator_token_out"}
    if value.get("format") == 1:
        request_fields.remove("capability")
    if (set(value) != {"format", "intent_id", "fingerprint", "request", "operator_token", "config"}
            or type(value["format"]) is not int or value["format"] not in {1, 2}
            or not isinstance(value["request"], dict) or not isinstance(value["config"], str)
            or not isinstance(value["intent_id"], str) or len(value["intent_id"]) != 64
            or any(character not in "0123456789abcdef" for character in value["intent_id"])
            or set(value["request"]) != request_fields
            or value["fingerprint"] != _digest(value["request"])):
        raise _denied()
    return value


def _completion(path: Path, intent: dict) -> dict | None:
    if not _exists(path):
        return None
    value = _record(path, intent["operator_token"])
    if (set(value) != {"intent_id", "fingerprint", "result"}
            or value["intent_id"] != intent["intent_id"] or value["fingerprint"] != intent["fingerprint"]
            or not isinstance(value["result"], dict)):
        raise _denied()
    result = value["result"]
    request = intent["request"]
    expected = {"deployment_id": request["deployment_id"], "realm": request["realm"],
        "mode": request["mode"], "operator_id": request["owner_id"],
        "operator_token_file": request["operator_token_out"], "effect": "committed"}
    if intent["format"] == 2:
        expected["capability"] = request["capability"]
    if (set(result) != set(expected) | {"credential_id", "migration"}
            or any(result.get(name) != item for name, item in expected.items())
            or not isinstance(result["credential_id"], str) or not isinstance(result["migration"], dict)):
        raise _denied()
    return result


def _initialization_settings(raw: bytes, *, legacy: bool) -> Settings:
    try:
        if legacy:
            return prepare_settings_upgrade(raw)
        return Settings.model_validate_json(raw)
    except (DomainError, ValueError, TypeError):
        raise _denied() from None


async def initialize_deployment(*, config_path: Path, realm: str, mode: str, database_dsn: str,
        migrator_dsn: str, state_dir: Path, journal_dir: Path, port: int, owner_id: str,
        operator_token_out: Path | None, deployment_id: str | None, resume: bool = False,
        capability: str = "agent_judged") -> dict:
    """Recover only this private intent; same-UID software is not an isolation boundary."""
    schema, endpoint = _dsn(database_dsn)
    migration_schema, migration_endpoint = _dsn(migrator_dsn)
    if schema != migration_schema or any(endpoint[name] != migration_endpoint[name] for name in ("PGHOST", "PGPORT", "PGDATABASE")):
        raise DomainError("CONFIG_INVALID", "The service and migrator must address the same local authority database and schema")
    config_path = _path(config_path)
    out = _path(operator_token_out or config_path.with_suffix(".operator.token"))
    state_dir, journal_dir = _path(state_dir), _path(journal_dir)
    _directory(state_dir)
    _directory(journal_dir)
    intent_path, result_path = state_dir / _INTENT, state_dir / _RESULT
    forbidden = {state_dir / "authority.lock", state_dir / "restore-barrier.json",
        state_dir / "model-approval.lock", state_dir / "model-approval-intent.json", intent_path, result_path}
    if (config_path.is_relative_to(out) or out.is_relative_to(config_path) or config_path in forbidden or out in forbidden
            or any(path.is_relative_to(journal_dir) or journal_dir.is_relative_to(path) for path in (config_path, out))):
        raise DomainError("PATH_DENIED", "Initialization outputs cannot replace each other, the journal or authority interlocks")
    existing = _intent(intent_path)
    if existing is None:
        if resume or _exists(result_path):
            raise _denied()
        _output(config_path, None)
        _output(out, None)
    effective_id = deployment_id if deployment_id is not None else (
        existing["request"]["deployment_id"] if existing else "deployment_" + secrets.token_hex(16)
    )
    try:
        TypeAdapter(Handle).validate_python(owner_id)
        settings = Settings(deployment_id=effective_id, realm=realm, mode=mode, capability=capability,
            database_dsn=database_dsn, migrator_dsn=migrator_dsn,
            state_dir=state_dir, journal_dir=journal_dir, port=port)
    except (ValidationError, ValueError):
        raise DomainError("CONFIG_INVALID", "The requested deployment configuration is invalid") from None
    request = {"deployment_id": settings.deployment_id, "realm": realm, "mode": mode, "capability": capability,
        "database_dsn": database_dsn, "migrator_dsn": migrator_dsn, "state_dir": str(state_dir),
        "journal_dir": str(journal_dir), "port": port, "owner_id": owner_id,
        "config_path": str(config_path), "operator_token_out": str(out)}
    if existing is not None and existing["format"] == 1:
        if capability != "agent_judged":
            raise _denied()
        request.pop("capability")
    fingerprint = _digest(request)
    with authority_lock(settings, exclusive=True):
        if _exists(state_dir / "restore-barrier.json"):
            raise DomainError("RESTORE_RECOVERY_REQUIRED", "Interrupted restore recovery must finish before initialization")
        intent = _intent(intent_path)
        if (existing is None) != (intent is None) or (existing is not None and existing != intent):
            raise _denied()
        if intent is not None and (intent["request"] != request or intent["fingerprint"] != fingerprint):
            raise _denied()
        if intent is None:
            intent = {"format": 2, "intent_id": secrets.token_hex(32), "fingerprint": fingerprint,
                "request": request, "operator_token": secrets.token_urlsafe(32),
                "config": settings.model_dump_json(indent=2) + "\n"}
        completed = _completion(result_path, intent)
        if existing is not None and not resume and completed is None:
            raise DomainError("INIT_RESUME_REQUIRED", "An interrupted initialization requires explicit --resume")
        recorded_settings = _initialization_settings(
            intent["config"].encode(), legacy=intent["format"] == 1,
        )
        if any(getattr(recorded_settings, name) != getattr(settings, name) for name in _SCOPE_FIELDS):
            raise _denied()
        settings = recorded_settings
        token = intent["operator_token"]
        token_raw, config_raw = (token + "\n").encode(), intent["config"].encode()
        _output(out, token_raw if existing is not None else None, required=completed is not None)
        if completed is None:
            _output(config_path, config_raw if existing is not None else None)
        else:
            try:
                current_raw = private_read(config_path, 262144)
            except (DomainError, OSError):
                raise _denied() from None
            current_settings = _initialization_settings(current_raw, legacy=intent["format"] == 1)
            if any(getattr(current_settings, name) != getattr(settings, name) for name in _SCOPE_FIELDS):
                raise _denied()
        journal = DeletionJournal(journal_dir, settings.deployment_id)
        journal_args = {"intent_id": intent["intent_id"], "fingerprint": fingerprint, "operator_token": token}
        journal_complete = journal.preflight_initialization(**journal_args)
        if completed is not None and not journal_complete:
            raise _denied()
        actor = await Store.preflight_initialization(settings, token, owner_id, resume=existing is not None)
        if completed is not None:
            if actor is None or actor.id != owner_id or actor.credential_id != completed["credential_id"]:
                raise _denied()
            return completed
        if existing is None:
            private_write(intent_path, _signed(intent, token))
        confirmed_actor = None
        try:
            version = await asyncio.to_thread(migrate, migrator_dsn)
            await asyncio.to_thread(journal.initialize_owned, **journal_args)
            _publish(out, token_raw)
            _publish(config_path, config_raw)
            store = Store(settings, journal)
            try:
                await store.open()
                confirmed_actor = await store.bootstrap(token, owner_id, resume=existing is not None)
            finally:
                await store.close()
            result = {"deployment_id": settings.deployment_id, "realm": realm, "mode": mode,
                "operator_id": confirmed_actor.id, "credential_id": confirmed_actor.credential_id,
                "operator_token_file": str(out), "migration": version, "effect": "committed"}
            if intent["format"] == 2:
                result["capability"] = settings.capability
            record = {"intent_id": intent["intent_id"], "fingerprint": fingerprint, "result": result}
            private_write(result_path, _signed(record, token))
            return result
        except Exception:
            raise DomainError("INIT_RECOVERY_REQUIRED", "Initialization may have committed private effects; resume the exact owned intent",
                status=503, effect=EffectState.COMMITTED if confirmed_actor is not None else EffectState.UNKNOWN) from None
