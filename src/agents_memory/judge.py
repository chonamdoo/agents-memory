"""Judge provider: who judges captured sources — the current coding agent (default) or TypeSafe Jev.

The provider lives in private files under ``state_dir/judge`` that only the operator CLI writes. The
service rereads them before every Jev request, so a switch takes effect without a restart. Keys never
enter Settings, the database, backups, MCP responses, argv or logs.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import secrets
import stat
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from .config import Settings
from .domain import DomainError, EffectState, Handle, Principal, Role, TypedModel
from .jev import JEV_DEFAULT_MODEL, JEV_ENDPOINT, JevClient, JevFailure
from .private_io import private_read, private_write

PROVIDER_FILE = "provider.json"
KEY_FILE = "jev.key"
TOKEN_FILE = "jev-agent.token"
WORKER_FILE = "worker.json"
JEV_EGRESS = {
    "endpoint": JEV_ENDPOINT,
    "hosting": "united_states",
    "sent": "captured source windows and memory statements of granted projects",
    "training": "provider_states_no_training_on_input",
    "retention": "zero_data_retention_enterprise_only",
}
ModelId = Field(default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")


class JudgeState(TypedModel):
    format: Literal[1] = 1
    provider: Literal["agent", "jev"] = "agent"
    revision: int = Field(default=0, ge=0)
    model: str | None = ModelId
    key_fingerprint: str | None = Field(default=None, pattern=r"^hmac-sha256:[0-9a-f]{12}$")
    credential_id: Handle | None = None
    updated_at: datetime | None = None
    updated_by: Handle | None = None

    @model_validator(mode="after")
    def complete_provider(self) -> JudgeState:
        if self.provider == "jev" and (self.model is None or self.key_fingerprint is None or self.credential_id is None):
            raise ValueError("Jev judgment requires a model, a stored key and its worker credential")
        if self.provider == "agent" and (self.model is not None or self.credential_id is not None):
            raise ValueError("Agent judgment keeps no Jev model or worker credential")
        return self


def judge_dir(settings: Settings) -> Path:
    return settings.state_dir / "judge"


def _invalid() -> DomainError:
    return DomainError("JUDGE_STATE_INVALID", "The private judge provider settings are invalid; rerun judge set", status=503)


def _absent(path: Path) -> bool:
    try:
        os.lstat(path)
    except FileNotFoundError:
        return True
    return False


def load_state(settings: Settings) -> JudgeState:
    path = judge_dir(settings) / PROVIDER_FILE
    if _absent(path):
        return JudgeState()
    try:
        return JudgeState.model_validate_json(private_read(path, 4096))
    except (DomainError, ValidationError, ValueError):
        raise _invalid() from None


def _save_state(settings: Settings, state: JudgeState) -> None:
    private_write(judge_dir(settings) / PROVIDER_FILE, state.model_dump_json(indent=2) + "\n", replace=True)


def validate_key(raw: str) -> str:
    key = raw.strip()
    if not 16 <= len(key) <= 512 or any(not 33 <= ord(character) <= 126 for character in key):
        raise DomainError("JUDGE_KEY_INVALID", "A Jev API key is 16 to 512 printable ASCII characters without spaces")
    return key


def key_fingerprint(settings: Settings, key: str) -> str:
    """Deployment-salted identifier for comparing keys; reveals no key characters or length."""
    return "hmac-sha256:" + hmac.new(settings.deployment_id.encode(), key.encode(), hashlib.sha256).hexdigest()[:12]


def _read_private_text(path: Path, maximum: int) -> str:
    try:
        return private_read(path, maximum).decode("ascii")
    except UnicodeError:
        raise _invalid() from None


def read_key(settings: Settings) -> str:
    path = judge_dir(settings) / KEY_FILE
    if _absent(path):
        raise DomainError("JUDGE_KEY_REQUIRED", "No Jev API key is stored; run judge set jev --key-file", status=409)
    return validate_key(_read_private_text(path, 1024))


def has_key(settings: Settings) -> bool:
    return not _absent(judge_dir(settings) / KEY_FILE)


def read_supplied_key(path: Path) -> tuple[str, list[str]]:
    """Read an operator-supplied key file once; the private copy is what the service uses."""
    raw = private_read(path, 1024, private=False)
    try:
        key = validate_key(raw.decode("ascii"))
    except UnicodeError:
        raise DomainError("JUDGE_KEY_INVALID", "A Jev API key is printable ASCII") from None
    warnings = []
    if os.stat(path).st_mode & 0o077:
        warnings.append("supplied_key_file_readable_by_others: chmod 600 or delete it; the service uses its private copy")
    return key, warnings


def read_worker_token(settings: Settings) -> str:
    path = judge_dir(settings) / TOKEN_FILE
    if _absent(path):
        raise DomainError("JUDGE_CREDENTIAL_INVALID", "The Jev worker credential is missing; rerun judge set jev", status=409)
    return _read_private_text(path, 4096).strip()


def _remove(settings: Settings, name: str) -> None:
    path = judge_dir(settings) / name
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise DomainError("PATH_DENIED", "A private judge file must be an owned regular file")
    os.unlink(path)


def require_jev_allowed(settings: Settings) -> None:
    if settings.mode != "personal":
        raise DomainError(
            "JUDGE_PROVIDER_FORBIDDEN",
            "Jev judgment sends source text off this machine and is available only in personal deployments",
            status=403,
        )


def verify_key(key: str, model: str, client_factory: Callable[[str, str], JevClient] = JevClient) -> str:
    try:
        return client_factory(key, model).verify()
    except JevFailure as failure:
        if failure.kind == "auth":
            raise DomainError("JUDGE_KEY_REJECTED", "TypeSafe rejected the Jev API key", status=401) from None
        if failure.kind == "request":
            raise DomainError("JUDGE_MODEL_REJECTED", "TypeSafe rejected the requested Jev model", status=422) from None
        raise DomainError("JUDGE_PROVIDER_UNAVAILABLE", "TypeSafe could not be reached to verify the key", status=503) from None


def worker_snapshot(settings: Settings) -> dict | None:
    path = judge_dir(settings) / WORKER_FILE
    if _absent(path):
        return None
    try:
        value = json.loads(private_read(path, 65536))
    except (DomainError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def save_worker_snapshot(settings: Settings, value: dict) -> None:
    private_write(judge_dir(settings) / WORKER_FILE, json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n", replace=True)


def describe(settings: Settings, state: JudgeState, *, operator: bool) -> dict:
    """Body- and key-free provider view; operator views add identifiers that agents do not need."""
    jev = state.provider == "jev"
    view = {
        "provider": state.provider,
        "revision": state.revision,
        "mode": settings.mode,
        "model": state.model,
        "source_judgment": "jev_background_then_server_validation" if jev else "current_coding_agent_via_mcp",
        "relevance_judgment": "current_coding_agent_via_mcp",
        "egress": JEV_EGRESS if jev else None,
        "fallback": "none: unjudged work stays pending for the coding agent",
        "change": "operator CLI only: agents-memory judge set",
    }
    if operator:
        view.update(
            key={"stored": has_key(settings), "fingerprint": state.key_fingerprint},
            credential_id=state.credential_id,
            updated_at=state.updated_at.isoformat() if state.updated_at else None,
            updated_by=state.updated_by,
        )
    return view


def _now() -> datetime:
    return datetime.now(UTC)


async def set_jev(
    settings: Settings, store, actor: Principal, key: str, *, model: str = JEV_DEFAULT_MODEL,
    verify: Callable[[str, str], str] | None = None,
) -> dict:
    """Verify first, then issue a fresh worker credential, publish files, and retire the old credential."""
    require_jev_allowed(settings)
    if actor.role != Role.OPERATOR:
        raise DomainError("ROLE_DENIED", "Only the operator can choose the judge provider", status=403)
    key = validate_key(key)
    previous, replaced = _previous(settings)
    resolved = await asyncio.to_thread(verify or verify_key, key, model)
    bindings = tuple(binding.id for binding in await store.list_bindings(actor))
    token = secrets.token_urlsafe(48)
    principal = await store.issue_token(actor, Role.AGENT, bindings, token)
    private_write(judge_dir(settings) / TOKEN_FILE, token + "\n", replace=True)
    private_write(judge_dir(settings) / KEY_FILE, key + "\n", replace=True)
    state = JudgeState(
        provider="jev", revision=previous.revision + 1, model=model,
        key_fingerprint=key_fingerprint(settings, key), credential_id=principal.credential_id,
        updated_at=_now(), updated_by=actor.id,
    )
    _save_state(settings, state)
    retired = None
    if previous.credential_id is not None and previous.credential_id != principal.credential_id:
        retired = await _retire(store, actor, previous.credential_id)
    return {
        **describe(settings, state, operator=True), "verified_model": resolved,
        "granted_bindings": list(bindings), "retired_credential": retired,
        "service": "a running service applies this before its next Jev request", "effect": EffectState.COMMITTED,
        **_replacement_note(replaced),
    }


async def set_agent(settings: Settings, store, actor: Principal, *, forget_key: bool) -> dict:
    """Stop egress first, then retire the worker credential and optionally the stored key."""
    if actor.role != Role.OPERATOR:
        raise DomainError("ROLE_DENIED", "Only the operator can choose the judge provider", status=403)
    previous, replaced = _previous(settings)
    stored = has_key(settings)
    state = JudgeState(
        provider="agent", revision=previous.revision + 1,
        key_fingerprint=None if forget_key or not stored else previous.key_fingerprint,
        updated_at=_now(), updated_by=actor.id,
    )
    _save_state(settings, state)
    _remove(settings, TOKEN_FILE)
    retired = None
    if previous.credential_id is not None:
        retired = await _retire(store, actor, previous.credential_id)
    if forget_key:
        _remove(settings, KEY_FILE)
    return {**describe(settings, state, operator=True), "retired_credential": retired, "effect": EffectState.COMMITTED,
            **_replacement_note(replaced)}


def _previous(settings: Settings) -> tuple[JudgeState, bool]:
    """The operator CLI must be able to replace unreadable settings; the revision still moves forward."""
    try:
        return load_state(settings), False
    except DomainError as error:
        if error.code != "JUDGE_STATE_INVALID":
            raise
        return JudgeState(revision=int(time.time())), True


def _replacement_note(replaced: bool) -> dict:
    if not replaced:
        return {}
    return {"replaced_invalid_state": "the previous worker credential is unknown; list and revoke stale agent credentials"}


async def _retire(store, actor: Principal, credential_id: str) -> str:
    try:
        await store.revoke_token(actor, credential_id)
    except DomainError as error:
        if error.code != "NOT_FOUND":
            raise
        return "already_inactive"
    return credential_id


async def grant_new_binding(settings: Settings, store, actor: Principal, binding_id: str) -> dict | None:
    """A project added while Jev judges joins the worker grant; agent mode leaves grants unchanged."""
    state = load_state(settings)
    if state.provider != "jev" or state.credential_id is None:
        return None
    require_jev_allowed(settings)
    await store.grant_binding(actor, state.credential_id, binding_id)
    return {"provider": "jev", "worker_grant": "added", "credential_id": state.credential_id}
