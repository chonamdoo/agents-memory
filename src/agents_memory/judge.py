"""Judge provider: who judges captured sources — the current coding agent (default), TypeSafe Jev, or a
signed-in subscription CLI (Claude Code, Codex or OMP) run headless by the background worker.

The provider lives in private files under ``state_dir/judge`` that only the operator CLI writes. The
service rereads them before every worker request, so a switch takes effect without a restart. Keys never
enter Settings, the database, backups, MCP responses, argv or logs. Each background route needs its own
default-deny egress grant; neither grant implies the other.
"""
from __future__ import annotations

import asyncio
import fcntl
import hashlib
import hmac
import json
import os
import re
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
from .jev import JEV_DEFAULT_MODEL, JEV_ENDPOINT, JevClient, ProviderFailure
from .private_io import private_read, private_write
from .subscription import Host, SubscriptionClient, resolve_executable

PROVIDER_FILE = "provider.json"
EGRESS_POLICY_FILE = "egress-policy.json"
KEY_FILE = "jev.key"
# The worker credential file keeps its original name so existing deployments need no migration.
TOKEN_FILE = "jev-agent.token"
ISSUING_TOKEN_FILE = "issuing-agent.token"
WORKER_FILE = "worker.json"
RUNS_DIR = "runs"
JEV_EGRESS = {
    "endpoint": JEV_ENDPOINT,
    "hosting": "united_states",
    "sent": "captured source windows and memory statements of granted projects",
    "training": "provider_states_no_training_on_input",
    "retention": "zero_data_retention_enterprise_only",
}
# A worker route needs its own grant: (egress policy field, judge policy argument, acknowledged destination).
ROUTES = {
    "jev": ("jev_allowed", "allow-jev", "api.typesafe.ai in the US"),
    "subscription": ("subscription_allowed", "allow-subscription",
                     "the vendor behind the selected Claude Code, Codex or OMP login, outside the current coding session"),
}
MODEL_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$"
ModelId = Field(default=None, min_length=1, max_length=64, pattern=MODEL_PATTERN)


def subscription_egress(host: str, executable: str | None) -> dict:
    return {
        "route": f"{host} CLI run headless by the background worker under the operator's signed-in login",
        "executable": executable,
        "sent": "captured source windows and memory statements of granted projects",
        "vendor": "the provider of that CLI login; its account plan governs training and retention",
        "isolation": "fresh private directory, no tools, MCP servers, hooks, extensions or session persistence",
    }


class EgressPolicy(TypedModel):
    format: Literal[1] = 1
    jev_allowed: bool = Field(default=False, strict=True)
    subscription_allowed: bool = Field(default=False, strict=True)
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
    provider: Literal["agent", "jev", "subscription"] = "agent"
    revision: int = Field(default=0, ge=0, strict=True)
    model: str | None = ModelId
    host: Host | None = None
    executable: str | None = Field(default=None, min_length=2, max_length=4096, pattern=r"^/[^\x00\r\n]*$")
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
        if self.provider == "subscription" and (self.host is None or self.executable is None or self.credential_id is None):
            raise ValueError("Subscription judgment requires a host, its pinned executable and a worker credential")
        if self.provider != "subscription" and (self.host is not None or self.executable is not None):
            raise ValueError("Only subscription judgment keeps a host executable")
        if self.provider == "agent" and (self.model is not None or self.credential_id is not None):
            raise ValueError("Agent judgment keeps no worker model or worker credential")
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
async def _publication_authority(store, actor: Principal) -> AsyncIterator[None]:
    """Classify file failures before the database transaction translates OSError."""
    async with store.operator_authority(actor):
        try:
            yield
        except OSError:
            raise DomainError(
                "JUDGE_PUBLICATION_UNCONFIRMED",
                "Private judge file publication or cleanup is unconfirmed; inspect judge status and "
                "rerun the same explicit command without changing retained recovery evidence",
                status=503, effect=EffectState.UNKNOWN,
            ) from None


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
            "JUDGE_CREDENTIAL_INVALID",
            f"The {state.provider} replacement is incomplete; rerun judge set {state.provider} or explicitly select agent",
            status=409,
        )
    path = judge_dir(settings) / TOKEN_FILE
    if _absent(path):
        raise DomainError("JUDGE_CREDENTIAL_INVALID",
                          f"The worker credential is missing; rerun judge set {state.provider}", status=409)
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


def route_allowed(policy: EgressPolicy, provider: str) -> bool:
    return provider in ROUTES and getattr(policy, ROUTES[provider][0]) is True


def require_route_allowed(settings: Settings, provider: str) -> None:
    if not route_allowed(load_egress_policy(settings), provider):
        argument = ROUTES[provider][1] if provider in ROUTES else "allow-jev"
        raise DomainError(
            "JUDGE_PROVIDER_FORBIDDEN",
            f"{provider} egress is denied; explicitly authorize it with judge policy {argument} --ack-egress "
            f"before selecting {provider}",
            status=403,
        )


def validate_model(value: str | None) -> str | None:
    if value is not None and (not 1 <= len(value) <= 64 or re.fullmatch(MODEL_PATTERN, value) is None):
        raise DomainError("INPUT_INVALID", "A model ID is 1 to 64 letters, digits or . _ : / - and starts alphanumerically")
    return value


def runs_dir(settings: Settings) -> Path:
    return judge_dir(settings) / RUNS_DIR


def verify_key(
    key: str, model: str, client_factory: Callable[[str, str], JevClient] = JevClient, *,
    before_attempt: Callable[[], None] | None = None,
) -> str:
    try:
        return client_factory(key, model).verify(before_attempt=before_attempt)
    except ProviderFailure as failure:
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
        absent = _absent(judge_dir(settings) / EGRESS_POLICY_FILE)
        egress_policy = {
            "jev_allowed": policy.jev_allowed, "subscription_allowed": policy.subscription_allowed,
            "status": "absent" if absent else "allowed" if policy.jev_allowed else "denied",
            "subscription_status": "absent" if absent else "allowed" if policy.subscription_allowed else "denied",
        }
    except DomainError as error:
        egress_policy = {"jev_allowed": False, "subscription_allowed": False, "status": "invalid",
                         "subscription_status": "invalid", "error": error.code}
    route = state.provider if state.provider in ROUTES and egress_policy[ROUTES[state.provider][0]] else None
    unavailable = route is not None and state.credential_id in state.retiring_credential_ids
    judgment = (f"{route}_unavailable_explicit_reselection_required" if unavailable
                else "jev_background_then_server_validation" if route == "jev"
                else "subscription_cli_background_then_server_validation" if route == "subscription"
                else "current_coding_agent_via_mcp")
    view = {
        "provider": route or "agent",
        "configured_provider": state.provider,
        "configured_model": state.model,
        "configured_host": state.host,
        "revision": state.revision,
        "mode": settings.mode,
        "egress_policy": egress_policy,
        "model": state.model if route else None,
        "host": state.host if route == "subscription" else None,
        "source_judgment": judgment,
        "relevance_judgment": "current_coding_agent_via_mcp",
        "retirement_pending": bool(state.retiring_credential_ids or state.forget_key_pending or not _absent(judge_dir(settings) / ISSUING_TOKEN_FILE)),
        "egress": (JEV_EGRESS if route == "jev"
                   else subscription_egress(state.host or "", state.executable if operator else None) if route else None),
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


async def set_egress_policy(
    settings: Settings, store, actor: Principal, *, jev_allowed: bool | None = None,
    subscription_allowed: bool | None = None,
) -> dict:
    """Authorize one route independently of provider choice; revoke before retiring any worker authority."""
    if (jev_allowed is None) == (subscription_allowed is None):
        raise DomainError("INPUT_INVALID", "Change exactly one egress route per policy update")
    route, allowed = ("jev", jev_allowed) if jev_allowed is not None else ("subscription", subscription_allowed)
    field = ROUTES[route][0]
    if actor.role != Role.OPERATOR:
        raise DomainError("ROLE_DENIED", f"Only the operator can authorize {route} egress", status=403)
    async with judge_guard(settings):
        try:
            previous = load_egress_policy(settings)
        except DomainError as error:
            if error.code != "JUDGE_EGRESS_POLICY_INVALID":
                raise
            previous = EgressPolicy(revision=int(time.time()))
        cleanup_committed = False
        if allowed:
            state = load_state(settings)
            if not getattr(previous, field) and state.provider == route:
                await _set_agent(settings, store, actor, forget_key=False)
                cleanup_committed = True
            else:
                cleanup_committed = bool(
                    state.retiring_credential_ids or state.forget_key_pending
                    or not _absent(judge_dir(settings) / ISSUING_TOKEN_FILE)
                )
                await _finish_retirement(settings, store, actor, state)
        policy = previous.model_copy(update={
            field: allowed, "revision": previous.revision + 1, "updated_at": _now(), "updated_by": actor.id,
        })
        try:
            async with _publication_authority(store, actor):
                private_write(judge_dir(settings) / EGRESS_POLICY_FILE, policy.model_dump_json(indent=2) + "\n", replace=True)
        except DomainError as error:
            if not cleanup_committed or error.effect == EffectState.UNKNOWN:
                raise
            raise DomainError(
                error.code, "Worker cleanup is committed, but egress policy publication was refused. " + error.message,
                status=error.status, effect=EffectState.COMMITTED,
            ) from None
        try:
            # Denying one route never retires the other route's selected worker.
            other_route = load_state(settings).provider not in {route, "agent"}
        except DomainError:
            other_route = False
        if not allowed and not other_route:
            try:
                result = await _set_agent(settings, store, actor, forget_key=False)
            except DomainError as error:
                raise DomainError(
                    error.code,
                    f"The {route} egress denial is committed. Provider cleanup or worker retirement is incomplete or "
                    f"unresolved; inspect judge status and rerun judge policy deny-{route}. " + error.message,
                    status=error.status, effect=EffectState.UNKNOWN,
                ) from None
        else:
            result = {**describe(settings, load_state(settings), operator=True), "effect": EffectState.COMMITTED}
        return {**result, "egress_policy": policy.model_dump(mode="json")}


async def set_jev(
    settings: Settings, store, actor: Principal, key: str, *, model: str = JEV_DEFAULT_MODEL,
    verify: Callable[[str, str], str] | None = None,
) -> dict:
    """Verify the key outside the guard; publish it only with a durably tracked new worker credential."""
    require_route_allowed(settings, "jev")
    if actor.role != Role.OPERATOR:
        raise DomainError("ROLE_DENIED", "Only the operator can choose the judge provider", status=403)
    key = validate_key(key)
    validate_model(model)

    def check(before_attempt: Callable[[], None]) -> str:
        if verify is not None:
            return verify(key, model)
        return verify_key(key, model, before_attempt=before_attempt)

    def build(state: JudgeState, credential_id: str) -> JudgeState:
        return JudgeState(
            provider="jev", revision=state.revision + 1, model=model,
            key_fingerprint=key_fingerprint(settings, key), credential_id=credential_id,
            retiring_credential_ids=state.retiring_credential_ids, updated_at=_now(), updated_by=actor.id,
        )

    return await _select_worker(settings, store, actor, "jev", check, build, {KEY_FILE: key})


async def set_subscription(
    settings: Settings, store, actor: Principal, host: Host, executable: Path | None = None, *,
    model: str | None = None, verify: Callable[[SubscriptionClient], str] | None = None,
) -> dict:
    """Pin a signed-in host CLI after a synthetic check; the worker reuses its login, never a copied credential."""
    require_route_allowed(settings, "subscription")
    if actor.role != Role.OPERATOR:
        raise DomainError("ROLE_DENIED", "Only the operator can choose the judge provider", status=403)
    executable = resolve_executable(host, executable)
    validate_model(model)
    client = SubscriptionClient(host, executable, model, workdir=runs_dir(settings))

    def check(before_attempt: Callable[[], None]) -> str:
        if verify is not None:
            return verify(client)
        try:
            return client.verify(before_attempt=before_attempt)
        except ProviderFailure as failure:
            if failure.kind == "auth":
                raise DomainError("JUDGE_LOGIN_REJECTED", f"The {host} CLI login was rejected; sign in again", status=401) from None
            if failure.kind == "request":
                raise DomainError("JUDGE_MODEL_REJECTED", f"The {host} CLI rejected the requested model", status=422) from None
            raise DomainError(
                "JUDGE_PROVIDER_UNAVAILABLE",
                f"The {host} CLI did not return a typed answer; confirm it is installed, signed in and the model exists",
                status=503,
            ) from None

    def build(state: JudgeState, credential_id: str) -> JudgeState:
        return JudgeState(
            provider="subscription", revision=state.revision + 1, model=model, host=host,
            executable=str(executable), key_fingerprint=state.key_fingerprint if has_key(settings) else None,
            credential_id=credential_id, retiring_credential_ids=state.retiring_credential_ids,
            updated_at=_now(), updated_by=actor.id,
        )

    return await _select_worker(settings, store, actor, "subscription", check, build, {})


async def _select_worker(
    settings: Settings, store, actor: Principal, provider: str,
    check: Callable[[Callable[[], None]], str], build: Callable[[JudgeState, str], JudgeState], files: dict[str, str],
) -> dict:
    """Verify outside the guard; publish only a durably tracked new worker credential."""
    async with judge_guard(settings):
        require_route_allowed(settings, provider)
        try:
            previous = load_state(settings)
        except DomainError as error:
            if error.code != "JUDGE_STATE_INVALID":
                raise
            raise DomainError(
                "JUDGE_STATE_INVALID", f"Repair the provider with judge set agent before selecting {provider}", status=503,
            ) from None
        async with store.operator_authority(actor):
            policy_revision = load_egress_policy(settings).revision

    def verify_authorized() -> str:
        _require_policy_revision(settings, provider, policy_revision)
        return check(lambda: _require_policy_revision(settings, provider, policy_revision))

    resolved = await asyncio.to_thread(verify_authorized)
    async with judge_guard(settings):
        _require_policy_revision(settings, provider, policy_revision)
        current = load_state(settings)
        if current != previous:
            raise DomainError("JUDGE_PROVIDER_CHANGED", f"The judge provider changed during {provider} setup; retry explicitly", status=409)
        retiring = previous.retiring_credential_ids
        if previous.credential_id is not None and previous.credential_id not in retiring:
            retiring = (*retiring, previous.credential_id)
        state = previous.model_copy(update={
            "revision": previous.revision + 1, "retiring_credential_ids": retiring,
            "updated_at": _now(), "updated_by": actor.id,
        })
        async with _publication_authority(store, actor):
            _save_state(settings, state)
        stage = "worker retirement"
        failure_effect = EffectState.UNKNOWN
        try:
            async with _publication_authority(store, actor):
                _remove(settings, TOKEN_FILE)
            state, retired_before_issue = await _finish_retirement(settings, store, actor, state)
            stage = "binding lookup; no replacement issuance attempted"
            failure_effect = EffectState.COMMITTED
            bindings = tuple(binding.id for binding in await store.list_bindings(actor))
            token = secrets.token_urlsafe(48)
            # A committed issuance with a lost response is recoverable by this token.
            async with _publication_authority(store, actor):
                private_write(judge_dir(settings) / ISSUING_TOKEN_FILE, token + "\n")
            stage = "replacement issuance or publication; issuance must be reconciled"
            failure_effect = EffectState.UNKNOWN
            principal = await store.issue_token(actor, Role.AGENT, bindings, token)
            async with _publication_authority(store, actor):
                private_write(judge_dir(settings) / TOKEN_FILE, token + "\n", replace=True)
                for name, content in files.items():
                    private_write(judge_dir(settings) / name, content + "\n", replace=True)
                state = build(state, principal.credential_id)
                _save_state(settings, state)
            stage = f"published {provider} worker retirement"
            state, retired = await _finish_retirement(settings, store, actor, state)
        except DomainError as error:
            raise DomainError(
                error.code,
                f"The provider transition fence is committed; setup failed during {stage}. "
                f"Inspect judge status and rerun judge set {provider}, or explicitly select judge set agent. " + error.message,
                status=error.status,
                effect=EffectState.UNKNOWN if error.effect == EffectState.UNKNOWN else failure_effect,
            ) from None
        return {
            **describe(settings, state, operator=True), "verified_model": resolved,
            "granted_bindings": list(bindings), "retired_credential": retired_before_issue or retired,
            "service": "a running service applies this before its next worker request", "effect": EffectState.COMMITTED,
        }


def _require_policy_revision(settings: Settings, provider: str, revision: int) -> None:
    require_route_allowed(settings, provider)
    if load_egress_policy(settings).revision != revision:
        raise DomainError("JUDGE_EGRESS_POLICY_CHANGED",
                          f"The egress policy changed during {provider} setup; retry explicitly", status=409)


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
    async with _publication_authority(store, actor):
        _save_state(settings, state)
    try:
        async with _publication_authority(store, actor):
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
            async with _publication_authority(store, actor):
                _remove(settings, ISSUING_TOKEN_FILE)
        for credential_id in state.retiring_credential_ids:
            retired = await _retire(store, actor, credential_id)
        if state.retiring_credential_ids or state.forget_key_pending:
            async with _publication_authority(store, actor):
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
            "Inspect judge status and rerun judge set or explicitly select judge set agent. " + error.message,
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
    """A project added while a worker judges joins its grant; agent mode leaves grants unchanged."""
    async with judge_guard(settings):
        state = load_state(settings)
        if (state.provider not in ROUTES or state.credential_id is None
                or state.credential_id in state.retiring_credential_ids):
            return None
        try:
            require_route_allowed(settings, state.provider)
        except DomainError as error:
            if error.code not in {"JUDGE_PROVIDER_FORBIDDEN", "JUDGE_EGRESS_POLICY_INVALID"}:
                raise
            return None
        await store.grant_binding(actor, state.credential_id, binding_id)
        return {"provider": state.provider, "worker_grant": "added", "credential_id": state.credential_id}
