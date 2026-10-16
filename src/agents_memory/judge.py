"""Judge provider: who judges captured sources — the current coding agent (default) or TypeSafe Jev.

The provider lives in private files under ``state_dir/judge`` that only the operator CLI writes. The
service rereads them before every Jev request, so a switch takes effect without a restart. Keys never
enter Settings, the database, backups, MCP responses, argv or logs.
"""
from __future__ import annotations

import asyncio
import fcntl
import hashlib
import hmac
import json
import os
import secrets
import stat
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from .config import Settings
from .domain import DomainError, EffectState, Handle, Principal, Role, TypedModel
from .jev import JEV_DEFAULT_MODEL, JEV_ENDPOINT, JevClient, JevFailure
from .private_io import private_read, private_write

PROVIDER_FILE = "provider.json"
EGRESS_POLICY_FILE = "egress-policy.json"
KEY_FILE = "jev.key"
TOKEN_FILE = "jev-agent.token"
ISSUING_TOKEN_FILE = "issuing-agent.token"
WORKER_FILE = "worker.json"
JEV_EGRESS = {
    "endpoint": JEV_ENDPOINT,
    "hosting": "united_states",
    "sent": "captured source windows and memory statements of granted projects",
    "training": "provider_states_no_training_on_input",
    "retention": "zero_data_retention_enterprise_only",
}
ModelId = Field(default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")


class EgressPolicy(TypedModel):
    format: Literal[1] = 1
    jev_allowed: bool = Field(default=False, strict=True)
    revision: int = Field(default=0, ge=0, strict=True)
    updated_at: datetime | None = None
    updated_by: Handle | None = None

    @field_validator("format", mode="before")
    @classmethod
    def integer_format(cls, value):
        if type(value) is not int:
            raise ValueError("The egress policy format must be an integer")
        return value


class JudgeState(TypedModel):
    format: Literal[1] = 1
    provider: Literal["agent", "jev"] = "agent"
    revision: int = Field(default=0, ge=0, strict=True)
    model: str | None = ModelId
    key_fingerprint: str | None = Field(default=None, pattern=r"^hmac-sha256:[0-9a-f]{12}$")
    credential_id: Handle | None = None
    retiring_credential_ids: tuple[Handle, ...] = ()
    forget_key_pending: bool = Field(default=False, strict=True)
    updated_at: datetime | None = None
    updated_by: Handle | None = None

    @field_validator("format", mode="before")
    @classmethod
    def integer_format(cls, value):
        if type(value) is not int:
            raise ValueError("The judge state format must be an integer")
        return value

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


def load_egress_policy(settings: Settings) -> EgressPolicy:
    path = judge_dir(settings) / EGRESS_POLICY_FILE
    if _absent(path):
        return EgressPolicy()
    try:
        return EgressPolicy.model_validate_json(private_read(path, 4096))
    except (DomainError, ValidationError, ValueError):
        raise DomainError(
            "JUDGE_EGRESS_POLICY_INVALID",
            "The private egress policy is invalid; rerun judge policy deny-jev or explicitly authorize Jev",
            status=503,
        ) from None


def _save_state(settings: Settings, state: JudgeState) -> None:
    private_write(judge_dir(settings) / PROVIDER_FILE, state.model_dump_json(indent=2) + "\n", replace=True)


@asynccontextmanager
async def judge_guard(settings: Settings) -> AsyncIterator[None]:
    """Keep policy/provider changes linearizable with the entire publication commit.

    Vendor calls stay outside this guard. Nonblocking attempts let an existing
    publisher finish awaited database work without blocking its event loop.
    """
    directory = judge_dir(settings)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    descriptor = -1
    try:
        info = os.fstat(directory_fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise DomainError("PATH_DENIED", "The judge authority directory must be private and owned")
        descriptor = os.open(
            "authority.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600, dir_fd=directory_fd,
        )
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise DomainError("PATH_DENIED", "The judge authority lock must be a private owned regular file")
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                await asyncio.sleep(0.01)
        yield
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(directory_fd)


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
    state = load_state(settings)
    if state.credential_id is not None and state.credential_id in state.retiring_credential_ids:
        raise DomainError(
            "JUDGE_CREDENTIAL_INVALID", "Jev replacement is incomplete; rerun judge set jev or explicitly select agent",
            status=409,
        )
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
    if not load_egress_policy(settings).jev_allowed:
        raise DomainError(
            "JUDGE_PROVIDER_FORBIDDEN",
            "Jev egress is denied; explicitly authorize it with judge policy allow-jev --ack-egress before selecting Jev",
            status=403,
        )


def verify_key(
    key: str, model: str, client_factory: Callable[[str, str], JevClient] = JevClient, *,
    before_attempt: Callable[[], None] | None = None,
) -> str:
    try:
        return client_factory(key, model).verify(before_attempt=before_attempt)
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
    try:
        policy = load_egress_policy(settings)
        policy_status = "absent" if _absent(judge_dir(settings) / EGRESS_POLICY_FILE) else "allowed" if policy.jev_allowed else "denied"
        egress_policy = {"jev_allowed": policy.jev_allowed, "status": policy_status}
    except DomainError as error:
        egress_policy = {"jev_allowed": False, "status": "invalid", "error": error.code}
    jev = state.provider == "jev" and egress_policy["jev_allowed"]
    unavailable = jev and state.credential_id in state.retiring_credential_ids
    view = {
        "provider": "jev" if jev else "agent",
        "configured_provider": state.provider,
        "configured_model": state.model,
        "revision": state.revision,
        "mode": settings.mode,
        "egress_policy": egress_policy,
        "model": state.model if jev else None,
        "source_judgment": "jev_unavailable_explicit_reselection_required" if unavailable else "jev_background_then_server_validation" if jev else "current_coding_agent_via_mcp",
        "relevance_judgment": "current_coding_agent_via_mcp",
        "retirement_pending": bool(state.retiring_credential_ids or state.forget_key_pending or not _absent(judge_dir(settings) / ISSUING_TOKEN_FILE)),
        "egress": JEV_EGRESS if jev else None,
        "fallback": "none: unjudged work stays pending for the coding agent",
        "change": "operator CLI only: agents-memory judge set",
    }
    if operator:
        view.update(
            key={"stored": has_key(settings), "fingerprint": state.key_fingerprint},
            credential_id=state.credential_id,
            retiring_credential_ids=list(state.retiring_credential_ids),
            forget_key_pending=state.forget_key_pending,
            updated_at=state.updated_at.isoformat() if state.updated_at else None,
            updated_by=state.updated_by,
        )
    return view


def _now() -> datetime:
    return datetime.now(UTC)


async def set_egress_policy(settings: Settings, store, actor: Principal, *, jev_allowed: bool) -> dict:
    """Authorize independently of provider choice; revoke before retiring any worker authority."""
    if actor.role != Role.OPERATOR:
        raise DomainError("ROLE_DENIED", "Only the operator can authorize Jev egress", status=403)
    async with judge_guard(settings):
        try:
            previous = load_egress_policy(settings)
        except DomainError as error:
            if error.code != "JUDGE_EGRESS_POLICY_INVALID":
                raise
            previous = EgressPolicy(revision=int(time.time()))
        cleanup_committed = False
        if jev_allowed:
            state = load_state(settings)
            if not previous.jev_allowed and state.provider == "jev":
                await _set_agent(settings, store, actor, forget_key=False)
                cleanup_committed = True
            else:
                cleanup_committed = bool(
                    state.retiring_credential_ids or state.forget_key_pending
                    or not _absent(judge_dir(settings) / ISSUING_TOKEN_FILE)
                )
                await _finish_retirement(settings, store, actor, state)
        policy = EgressPolicy(
            jev_allowed=jev_allowed, revision=previous.revision + 1, updated_at=_now(), updated_by=actor.id,
        )
        try:
            async with store.operator_authority(actor):
                private_write(judge_dir(settings) / EGRESS_POLICY_FILE, policy.model_dump_json(indent=2) + "\n", replace=True)
        except DomainError as error:
            if not cleanup_committed or error.effect == EffectState.UNKNOWN:
                raise
            raise DomainError(
                error.code, "Worker cleanup is committed, but egress policy publication was refused. " + error.message,
                status=error.status, effect=EffectState.COMMITTED,
            ) from None
        if not policy.jev_allowed:
            try:
                result = await _set_agent(settings, store, actor, forget_key=False)
            except DomainError as error:
                raise DomainError(
                    error.code,
                    "Jev egress denial is committed. Provider cleanup or worker retirement is incomplete or unresolved; "
                    "inspect judge status and rerun judge policy deny-jev. " + error.message,
                    status=error.status, effect=EffectState.UNKNOWN,
                ) from None
        else:
            result = {**describe(settings, load_state(settings), operator=True), "effect": EffectState.COMMITTED}
        return {**result, "egress_policy": policy.model_dump(mode="json")}


async def set_jev(
    settings: Settings, store, actor: Principal, key: str, *, model: str = JEV_DEFAULT_MODEL,
    verify: Callable[[str, str], str] | None = None,
) -> dict:
    """Verify outside the guard; publish only a durably tracked new worker credential."""
    require_jev_allowed(settings)
    if actor.role != Role.OPERATOR:
        raise DomainError("ROLE_DENIED", "Only the operator can choose the judge provider", status=403)
    key = validate_key(key)
    async with judge_guard(settings):
        require_jev_allowed(settings)
        try:
            previous = load_state(settings)
        except DomainError as error:
            if error.code != "JUDGE_STATE_INVALID":
                raise
            raise DomainError(
                "JUDGE_STATE_INVALID", "Repair the provider with judge set agent before selecting Jev", status=503,
            ) from None
        async with store.operator_authority(actor):
            policy_revision = load_egress_policy(settings).revision
    def verify_authorized() -> str:
        _require_policy_revision(settings, policy_revision)
        if verify is not None:
            return verify(key, model)
        return verify_key(key, model, before_attempt=lambda: _require_policy_revision(settings, policy_revision))

    resolved = await asyncio.to_thread(verify_authorized)
    async with judge_guard(settings):
        _require_policy_revision(settings, policy_revision)
        current = load_state(settings)
        if current != previous:
            raise DomainError("JUDGE_PROVIDER_CHANGED", "The judge provider changed during Jev setup; retry explicitly", status=409)
        retiring = previous.retiring_credential_ids
        if previous.credential_id is not None and previous.credential_id not in retiring:
            retiring = (*retiring, previous.credential_id)
        state = previous.model_copy(update={
            "revision": previous.revision + 1, "retiring_credential_ids": retiring,
            "updated_at": _now(), "updated_by": actor.id,
        })
        async with store.operator_authority(actor):
            _save_state(settings, state)
        stage = "worker retirement"
        failure_effect = EffectState.UNKNOWN
        try:
            async with store.operator_authority(actor):
                _remove(settings, TOKEN_FILE)
            state, retired_before_issue = await _finish_retirement(settings, store, actor, state)
            stage = "binding lookup; no replacement issuance attempted"
            failure_effect = EffectState.COMMITTED
            bindings = tuple(binding.id for binding in await store.list_bindings(actor))
            token = secrets.token_urlsafe(48)
            # A committed issuance with a lost response is recoverable by this token.
            async with store.operator_authority(actor):
                private_write(judge_dir(settings) / ISSUING_TOKEN_FILE, token + "\n")
            stage = "replacement issuance or publication; issuance must be reconciled"
            failure_effect = EffectState.UNKNOWN
            principal = await store.issue_token(actor, Role.AGENT, bindings, token)
            async with store.operator_authority(actor):
                private_write(judge_dir(settings) / TOKEN_FILE, token + "\n", replace=True)
                private_write(judge_dir(settings) / KEY_FILE, key + "\n", replace=True)
                state = JudgeState(
                    provider="jev", revision=state.revision + 1, model=model,
                    key_fingerprint=key_fingerprint(settings, key), credential_id=principal.credential_id,
                    retiring_credential_ids=state.retiring_credential_ids,
                    updated_at=_now(), updated_by=actor.id,
                )
                _save_state(settings, state)
            stage = "published Jev worker retirement"
            state, retired = await _finish_retirement(settings, store, actor, state)
        except DomainError as error:
            raise DomainError(
                error.code,
                f"The provider transition fence is committed; setup failed during {stage}. "
                "Inspect judge status and rerun judge set jev, or explicitly select judge set agent. " + error.message,
                status=error.status,
                effect=EffectState.UNKNOWN if error.effect == EffectState.UNKNOWN else failure_effect,
            ) from None
        return {
            **describe(settings, state, operator=True), "verified_model": resolved,
            "granted_bindings": list(bindings), "retired_credential": retired_before_issue or retired,
            "service": "a running service applies this before its next Jev request", "effect": EffectState.COMMITTED,
        }


def _require_policy_revision(settings: Settings, revision: int) -> None:
    require_jev_allowed(settings)
    if load_egress_policy(settings).revision != revision:
        raise DomainError("JUDGE_EGRESS_POLICY_CHANGED", "The egress policy changed during Jev setup; retry explicitly", status=409)


async def set_agent(settings: Settings, store, actor: Principal, *, forget_key: bool) -> dict:
    """Stop egress first, then retire the worker credential and optionally the stored key."""
    if actor.role != Role.OPERATOR:
        raise DomainError("ROLE_DENIED", "Only the operator can choose the judge provider", status=403)
    async with judge_guard(settings):
        return await _set_agent(settings, store, actor, forget_key=forget_key)


async def _set_agent(settings: Settings, store, actor: Principal, *, forget_key: bool) -> dict:
    previous, replaced = _previous(settings)
    stored = has_key(settings)
    forget_key = forget_key or previous.forget_key_pending
    retiring = previous.retiring_credential_ids
    if previous.credential_id is not None and previous.credential_id not in retiring:
        retiring = (*retiring, previous.credential_id)
    state = JudgeState(
        provider="agent", revision=previous.revision + 1,
        key_fingerprint=None if forget_key or not stored else previous.key_fingerprint,
        retiring_credential_ids=retiring, forget_key_pending=forget_key,
        updated_at=_now(), updated_by=actor.id,
    )
    async with store.operator_authority(actor):
        _save_state(settings, state)
    try:
        async with store.operator_authority(actor):
            _remove(settings, TOKEN_FILE)
        state, retired = await _finish_retirement(settings, store, actor, state)
    except DomainError as error:
        raise DomainError(
            error.code,
            "Agent provider selection is committed. Worker retirement or key cleanup is incomplete or unresolved; "
            "inspect judge status and rerun judge set agent. " + error.message,
            status=error.status, effect=EffectState.UNKNOWN,
        ) from None
    return {**describe(settings, state, operator=True), "retired_credential": retired, "effect": EffectState.COMMITTED,
            **_replacement_note(replaced)}


async def _finish_retirement(settings: Settings, store, actor: Principal, state: JudgeState) -> tuple[JudgeState, str | None]:
    retired = None
    try:
        pending = judge_dir(settings) / ISSUING_TOKEN_FILE
        if not _absent(pending):
            token = _read_private_text(pending, 4096).strip()
            issued = await store.resolve_issued_credential(actor, token, role=Role.AGENT)
            if issued is not None and issued != state.credential_id and issued not in state.retiring_credential_ids:
                retired = await _retire(store, actor, issued)
            async with store.operator_authority(actor):
                _remove(settings, ISSUING_TOKEN_FILE)
        for credential_id in state.retiring_credential_ids:
            retired = await _retire(store, actor, credential_id)
        if state.retiring_credential_ids or state.forget_key_pending:
            async with store.operator_authority(actor):
                if state.forget_key_pending:
                    _remove(settings, KEY_FILE)
                state = state.model_copy(update={
                    "retiring_credential_ids": tuple(identifier for identifier in state.retiring_credential_ids if identifier == state.credential_id),
                    "forget_key_pending": False,
                })
                _save_state(settings, state)
    except DomainError as error:
        raise DomainError(
            error.code,
            "Durable worker cleanup intent remains pending; issuance or credential retirement is unresolved. "
            "Inspect judge status and rerun judge set jev or explicitly select judge set agent. " + error.message,
            status=error.status, effect=EffectState.UNKNOWN,
        ) from None
    return state, retired


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
    async with judge_guard(settings):
        state = load_state(settings)
        if (state.provider != "jev" or state.credential_id is None
                or state.credential_id in state.retiring_credential_ids):
            return None
        try:
            require_jev_allowed(settings)
        except DomainError as error:
            if error.code not in {"JUDGE_PROVIDER_FORBIDDEN", "JUDGE_EGRESS_POLICY_INVALID"}:
                raise
            return None
        await store.grant_binding(actor, state.credential_id, binding_id)
        return {"provider": "jev", "worker_grant": "added", "credential_id": state.credential_id}
