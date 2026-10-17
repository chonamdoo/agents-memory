from __future__ import annotations

import fcntl
import json
import os
import re
import sqlite3
import stat
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from pydantic import Field, ValidationError

from .client import LocalClient
from .domain import DomainError, Handle, RevisionRef, SourcePointer, TypedModel
from .health import (
    CodeObservationCommand, HealthObserverRequest, HealthWorkspaceCommand,
    SessionObservationCommand, relative_code_path,
)
from .health_code import RootPin, observe_file, pin_root
from .private_io import private_read, private_write
from .spool import ProducerSpool
from .wire import decode_json

_HEALTH_BYTES = 65536
_START_EVENTS = {"SessionStart", "session_start"}
_END_EVENTS = {"SessionEnd", "session_shutdown"}
_INTERRUPT_EVENTS = {"PreCompact", "session_before_compact", "session_before_switch", "session_before_branch"}
_RESUME_EVENTS = {"PostCompact", "session_compact", "session_switch", "session_branch", "session_tree"}
_BASE_GAPS = [
    "HOST_SESSION_WINDOW_UNOBSERVED", "HOST_HUMAN_PRESENCE_UNATTESTED",
    "HOST_CONSUMPTION_UNOBSERVED", "HOST_CLAIM_REVISIONS_UNOBSERVED",
]


class HealthWorkspaceConfig(TypedModel):
    version: int = Field(default=1, ge=1, le=1, strict=True)
    deployment_id: Handle
    binding_id: Handle
    installation_id: Handle
    workspace_id: Handle
    producer_credential_id: Handle
    pin: RootPin
    next_agent: bool = Field(default=False, strict=True)


class HealthWorkspacePreparation(TypedModel):
    version: int = Field(default=1, ge=1, le=1, strict=True)
    config: HealthWorkspaceConfig
    command: HealthWorkspaceCommand


def _config_path(receipt: dict) -> Path:
    return Path(receipt["runtime_dir"]) / "health-workspace.json"


def _validate_config(receipt: dict, config: HealthWorkspaceConfig) -> None:
    if (config.deployment_id != receipt["deployment_id"] or config.binding_id != receipt["binding_id"]
            or config.installation_id != receipt["installation_id"] or config.pin.root != receipt["project_root"]):
        raise DomainError("HEALTH_WORKSPACE_SCOPE", "The explicit workspace belongs to another installation")


def prepare_health_workspace(
    receipt: dict, workspace_id: str, producer_credential_id: str, *,
    expected_binding_revision: int, expected_workspace_revision: int,
    idempotency_key: str, next_agent: bool = False,
) -> tuple[HealthWorkspaceConfig, HealthWorkspaceCommand]:
    config = HealthWorkspaceConfig(
        deployment_id=receipt["deployment_id"], binding_id=receipt["binding_id"],
        installation_id=receipt["installation_id"], workspace_id=workspace_id,
        producer_credential_id=producer_credential_id,
        pin=pin_root(Path(receipt["project_root"]), uuid.uuid4().hex + uuid.uuid4().hex),
        next_agent=next_agent,
    )
    return config, HealthWorkspaceCommand(
        binding_id=config.binding_id, expected_binding_revision=expected_binding_revision,
        idempotency_key=idempotency_key, workspace_id=workspace_id,
        expected_workspace_revision=expected_workspace_revision,
        root_fingerprint=config.pin.fingerprint, producer_credential_id=producer_credential_id,
    )


def configure_health_workspace(receipt: dict, config: HealthWorkspaceConfig) -> None:
    _validate_config(receipt, config)
    current = pin_root(Path(config.pin.root), config.pin.nonce)
    if current != config.pin:
        raise DomainError("HEALTH_ROOT_CHANGED", "The root changed before workspace configuration")
    with _owner(receipt):
        private_write(_config_path(receipt), config.model_dump_json() + "\n", replace=_config_path(receipt).exists())


def prepare_health_registration(
    receipt: dict, workspace_id: str, producer_credential_id: str, *,
    expected_binding_revision: int, expected_workspace_revision: int,
    idempotency_key: str, next_agent: bool = False,
    reuse: HealthWorkspacePreparation | None = None,
) -> HealthWorkspacePreparation:
    config, command = prepare_health_workspace(
        receipt, workspace_id, producer_credential_id,
        expected_binding_revision=expected_binding_revision,
        expected_workspace_revision=expected_workspace_revision,
        idempotency_key=idempotency_key, next_agent=next_agent,
    )
    previous = reuse.config if reuse is not None else load_health_workspace(receipt)
    if previous is not None:
        _validate_config(receipt, previous)
        if reuse is not None and previous.workspace_id != workspace_id:
            raise DomainError("HEALTH_WORKSPACE_SCOPE", "A prepared identity cannot be reused for another workspace")
        if previous.workspace_id == workspace_id:
            if pin_root(Path(previous.pin.root), previous.pin.nonce) != previous.pin:
                raise DomainError("HEALTH_ROOT_CHANGED", "The prepared root identity is no longer current")
            config = config.model_copy(update={"pin": previous.pin})
            command = command.model_copy(update={"root_fingerprint": previous.pin.fingerprint})
    return HealthWorkspacePreparation(config=config, command=command)


def load_health_preparation(path: Path) -> HealthWorkspacePreparation:
    try:
        return HealthWorkspacePreparation.model_validate_json(private_read(path, 16384), strict=True)
    except (ValidationError, ValueError, UnicodeError):
        raise DomainError("HEALTH_PREPARATION_INVALID", "A complete private workspace preparation is required") from None


def register_health_workspace(receipt: dict, preparation: HealthWorkspacePreparation, client: LocalClient) -> dict:
    from .domain import EffectState, Operation
    from .wire import validate_wire

    config, command = preparation.config, preparation.command
    _validate_config(receipt, config)
    if (command.binding_id != config.binding_id or command.workspace_id != config.workspace_id
            or command.root_fingerprint != config.pin.fingerprint
            or command.producer_credential_id != config.producer_credential_id):
        raise DomainError("HEALTH_PREPARATION_INVALID", "The prepared command and root identity disagree")
    with _owner(receipt):
        if pin_root(Path(config.pin.root), config.pin.nonce) != config.pin:
            raise DomainError("HEALTH_ROOT_CHANGED", "The prepared root identity is no longer current")
        result = client.request("/api/health", command.model_dump(mode="json"))
        try:
            operation = validate_wire(Operation, result)
        except DomainError:
            raise DomainError("HEALTH_RECEIPT_INVALID", "Workspace registration completion is unconfirmed",
                              effect=EffectState.UNKNOWN) from None
        if (operation.binding_id != config.binding_id or operation.kind != command.kind
                or operation.artifact_id != config.workspace_id or operation.effect != EffectState.COMMITTED):
            raise DomainError("HEALTH_RECEIPT_INVALID", "Workspace registration completion is unconfirmed",
                              effect=EffectState.UNKNOWN)
        if operation.state != "health_recorded":
            raise DomainError("HEALTH_WORKSPACE_RETRACTED", "The registration is no longer active",
                              effect=EffectState.COMMITTED)
        try:
            observer = client.request("/api/health/observer", HealthObserverRequest(
                binding_id=config.binding_id).model_dump(mode="json"))
            if not isinstance(observer, dict) or not isinstance(observer.get("workspaces"), list):
                raise DomainError("HEALTH_OBSERVER_INVALID", "Registration requires complete current observer metadata")
            current = [row for row in observer["workspaces"]
                       if isinstance(row, dict) and row.get("workspace_id") == config.workspace_id]
            if (observer.get("kind") != "health_observer" or observer.get("binding_id") != config.binding_id
                    or type(observer.get("binding_revision")) is not int
                    or observer["binding_revision"] != command.expected_binding_revision
                    or len(current) != 1 or current[0].get("revision") != command.expected_workspace_revision + 1
                    or current[0].get("root_fingerprint") != config.pin.fingerprint
                    or current[0].get("producer_credential_id") != config.producer_credential_id):
                raise DomainError("HEALTH_WORKSPACE_STALE", "Inspect current registration before preparing a new mutation")
            if pin_root(Path(config.pin.root), config.pin.nonce) != config.pin:
                raise DomainError("HEALTH_ROOT_CHANGED", "The root changed before workspace activation")
            private_write(_config_path(receipt), config.model_dump_json() + "\n",
                          replace=_config_path(receipt).exists())
        except DomainError as error:
            error.effect = EffectState.COMMITTED
            raise
        except OSError:
            raise DomainError("HEALTH_CONFIGURATION_UNCONFIRMED",
                              "Registration committed; local activation is unconfirmed; retain and retry the prepared file",
                              effect=EffectState.COMMITTED) from None
    return {"operation": operation.model_dump(mode="json"), "workspace_configured": True}


def load_health_workspace(receipt: dict) -> HealthWorkspaceConfig | None:
    path = _config_path(receipt)
    try:
        path.lstat()
    except FileNotFoundError:
        return None
    try:
        config = HealthWorkspaceConfig.model_validate_json(private_read(path, 8192), strict=True)
    except (ValidationError, ValueError, UnicodeError):
        raise DomainError("HEALTH_WORKSPACE_INVALID", "The explicit health workspace is invalid") from None
    _validate_config(receipt, config)
    return config


@contextmanager
def _owner(receipt: dict):
    path = Path(receipt["runtime_dir"]) / "health.lock"
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise DomainError("HEALTH_STATE_DENIED", "Health metadata requires a private owned lock")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DomainError("HEALTH_OBSERVER_BUSY", "Another bounded observation owns this workspace") from None
        yield
    finally:
        os.close(descriptor)


def _spool(receipt: dict) -> ProducerSpool:
    return ProducerSpool(
        Path(receipt["runtime_dir"]) / "capture.sqlite3", receipt["deployment_id"],
        receipt["binding_id"], receipt["spool_limit_bytes"],
    )


def _client(receipt: dict) -> LocalClient:
    from .hosts import receipt_connection

    return LocalClient(
        receipt["base_url"], Path(receipt["producer_token_file"]), timeout=1,
        state_dir=Path(receipt["runtime_dir"]).parent.parent,
        deployment_id=receipt["deployment_id"], remote_settings=receipt_connection(receipt),
    )


def _observer(receipt: dict, config: HealthWorkspaceConfig, spool: ProducerSpool, client) -> tuple[dict, dict | None]:
    response = client.request("/api/health/observer", HealthObserverRequest(binding_id=config.binding_id).model_dump(mode="json"))
    if (not isinstance(response, dict) or len(json.dumps(response, ensure_ascii=False).encode()) > 262144
            or response.get("kind") != "health_observer" or response.get("binding_id") != config.binding_id
            or type(response.get("binding_revision")) is not int or response["binding_revision"] < 1):
        raise DomainError("HEALTH_OBSERVER_INVALID", "The service returned invalid scoped observer metadata")
    policy = response.get("policy")
    if not isinstance(policy, dict) or type(policy.get("enabled")) is not bool:
        raise DomainError("HEALTH_OBSERVER_INVALID", "The service returned invalid health policy metadata")
    if not policy["enabled"]:
        spool.write_health_state("authorization", {"enabled": False})
        return response, None
    workspaces = response.get("workspaces")
    if not isinstance(workspaces, list) or len(workspaces) > 128:
        raise DomainError("HEALTH_OBSERVER_INVALID", "The service returned invalid workspace metadata")
    matched = [item for item in workspaces if isinstance(item, dict) and item.get("workspace_id") == config.workspace_id]
    if len(matched) != 1:
        raise DomainError("HEALTH_WORKSPACE_UNOBSERVED", "The registered workspace was not included in this bounded observer page")
    workspace = matched[0]
    if (workspace.get("root_fingerprint") != config.pin.fingerprint
            or workspace.get("producer_credential_id") != config.producer_credential_id
            or type(workspace.get("revision")) is not int or workspace["revision"] < 1
            or type(workspace.get("last_sequence")) is not int or workspace["last_sequence"] < 0):
        raise DomainError("HEALTH_WORKSPACE_CHANGED", "The registered workspace identity changed")
    for coverage in (response.get("coverage"), workspace.get("coverage")):
        if not isinstance(coverage, dict) or type(coverage.get("complete")) is not bool:
            raise DomainError("HEALTH_OBSERVER_INVALID", "The observer omitted explicit registry coverage")
    spool.write_health_state("authorization", {
        "enabled": True, "binding_revision": response["binding_revision"],
        "workspace_id": config.workspace_id, "fingerprint": config.pin.fingerprint,
    })
    return response, workspace


def observe_health_workspace(
    receipt: dict, *, client=None, require_committed: bool = False, flush_limit: int = 4,
    explicit_paths: tuple[tuple[str, tuple[str, ...]], ...] | None = None,
) -> dict:
    config = load_health_workspace(receipt)
    if config is None:
        return {"state": "disabled", "configured": False}
    if not 1 <= flush_limit <= 128:
        raise DomainError("SPOOL_LIMIT_INVALID", "Choose a bounded flush limit")
    with _owner(receipt):
        spool = _spool(receipt)
        try:
            client = client or _client(receipt)
            response, workspace = _observer(receipt, config, spool, client)
            if workspace is None:
                return {"state": "disabled", "configured": True, "workspace_id": config.workspace_id, "freshness": "unknown"}
            # Reconcile the previous immutable observation before reserving a new sequence.
            prior = spool.read_health_state("code")
            if prior.get("key"):
                spool.flush(client, limit=flush_limit)
                try:
                    prior_disposition = spool.disposition(prior["key"])["state"]
                except DomainError as error:
                    if error.code != "SPOOL_REPLAY_EXPIRED_OR_UNKNOWN":
                        raise
                    prior_disposition = "expired_or_unknown"
                if prior_disposition not in {"committed", "expired", "discarded", "expired_or_unknown"}:
                    return _incomplete(require_committed, "HEALTH_OBSERVATION_UNCOMMITTED")
            paths = workspace.get("linked_paths") if explicit_paths is None else [
                {"relative_path": path, "symbol_names": list(names)} for path, names in explicit_paths
            ]
            if explicit_paths is not None and not 1 <= len(explicit_paths) <= 32:
                raise DomainError("HEALTH_OBSERVATION_OVERFLOW", "Choose one to 32 explicit paths")
            if not isinstance(paths, list) or len(paths) > 128:
                raise DomainError("HEALTH_OBSERVER_INVALID", "The linked-path metadata is invalid")
            complete = explicit_paths is not None or (
                len(paths) <= 32 and workspace["coverage"]["complete"] and response["coverage"]["complete"]
            )
            files = []
            budget = min(_HEALTH_BYTES, receipt["max_http_body_bytes"], max(1, spool.limit_bytes // 4))
            for item in paths[:32]:
                if not isinstance(item, dict) or not isinstance(item.get("relative_path"), str):
                    raise DomainError("HEALTH_OBSERVER_INVALID", "The linked path is invalid")
                relative_code_path(item["relative_path"])
                names = item.get("symbol_names", [])
                if (not isinstance(names, list) or any(not isinstance(name, str) or not name or len(name) > 512 for name in names)
                        or len(set(names)) != len(names)):
                    raise DomainError("HEALTH_OBSERVER_INVALID", "The linked symbols are invalid")
                if len(names) > 16:
                    complete = False
                observed = observe_file(config.pin, item["relative_path"], tuple(names[:16]))
                candidate = [*files, observed]
                if len(json.dumps([entry.model_dump(mode="json") for entry in candidate], ensure_ascii=False).encode()) > budget - 1536:
                    complete = False
                    break
                files = candidate
            if not paths:
                if not complete:
                    return _incomplete(require_committed, "HEALTH_OBSERVATION_PARTIAL")
                return {"state": "observed", "configured": True, "workspace_id": config.workspace_id, "coverage": "linked_paths", "files": 0}
            if not files:
                return _incomplete(require_committed, "HEALTH_OBSERVATION_OVERFLOW")
            sequence = max(workspace["last_sequence"], prior.get("sequence", 0)) + 1
            command = CodeObservationCommand(
                binding_id=config.binding_id, expected_binding_revision=response["binding_revision"],
                idempotency_key="code:" + uuid.uuid4().hex, workspace_id=config.workspace_id,
                expected_workspace_revision=workspace["revision"], root_fingerprint=config.pin.fingerprint,
                sequence=sequence, observed_at=datetime.now(UTC), files=files,
                coverage="explicit_paths" if explicit_paths is not None else "linked_paths" if complete else "partial_linked_paths",
            )
            if len(command.model_dump_json().encode()) > budget:
                return _incomplete(require_committed, "HEALTH_OBSERVATION_OVERFLOW")
            spool.enqueue(command, health_state=("code", {"key": command.idempotency_key, "sequence": sequence}))
            spool.flush(client, limit=flush_limit)
            disposition = spool.disposition(command.idempotency_key)
            if disposition["state"] != "committed":
                return _incomplete(require_committed, "HEALTH_OBSERVATION_UNCOMMITTED")
            if not complete:
                return _incomplete(require_committed, "HEALTH_OBSERVATION_PARTIAL")
            return {
                "state": "observed", "configured": True, "workspace_id": config.workspace_id,
                "coverage": command.coverage, "files": len(files),
                "operation_id": disposition["operation_id"], "health_reference": disposition.get("health_reference"),
                "provenance": "producer_reported", "freshness": "observed_bytes_not_continuous_truth",
            }
        finally:
            spool.close()


def _incomplete(required: bool, code: str) -> dict:
    if required:
        raise DomainError(code, "Current linked-code observation is incomplete; ordinary context was not requested")
    return {"state": "gap", "code": code, "coverage": "partial_linked_paths"}


def health_before_context(receipt: dict) -> dict:
    return observe_health_workspace(receipt, require_committed=True, flush_limit=4)


def _session_state(identity: dict, previous: dict | None = None) -> dict:
    root = identity.get("root")
    gaps = list(_BASE_GAPS)
    if root is not None and (len(root) > 128 or re.fullmatch(r"[A-Za-z0-9_.:-]+", root) is None):
        root = None
        gaps.append("HOST_ROOT_ID_UNREPRESENTABLE")
    if root is None:
        gaps.append("HOST_ROOT_LINEAGE_UNOBSERVED")
    if identity.get("limited"):
        gaps.append("HOST_LINEAGE_UNRESOLVED")
    return {
        "stream_id": (previous or {}).get("stream_id", "host-stream:" + uuid.uuid4().hex),
        "segment_id": "segment:" + uuid.uuid4().hex,
        "sequence": (previous or {}).get("sequence", 0), "root_run_id": root,
        "agent_path": identity["path"], "origin_keys": [], "source_refs": [],
        "gaps": gaps, "closed": False,
    }


def _session_command(config: HealthWorkspaceConfig, authorization: dict, state: dict, event: str) -> SessionObservationCommand:
    return SessionObservationCommand(
        binding_id=config.binding_id, expected_binding_revision=authorization["binding_revision"],
        idempotency_key="session:" + uuid.uuid4().hex,
        stream_id=state["stream_id"], segment_id=state["segment_id"],
        event_id="event:" + uuid.uuid4().hex, sequence=state["sequence"] + 1,
        event=event, root_run_id=state["root_run_id"], agent_path=state["agent_path"],
        origin_keys=state["origin_keys"], source_refs=[RevisionRef.model_validate(value) for value in state["source_refs"]],
        claim_refs=[], coverage="partial", gaps=state["gaps"],
    )


def _enqueue_session(spool: ProducerSpool, config: HealthWorkspaceConfig, authorization: dict, slot: str, state: dict, event: str) -> None:
    command = _session_command(config, authorization, state, event)
    next_state = {
        **state, "sequence": command.sequence,
        "closed": state["closed"] or event in {"end", "interrupted"},
    }
    spool.enqueue(command, health_state=(slot, next_state))
    state.update(next_state)


def observe_host_session(
    receipt: dict, identity: dict, event_name: str, *, origin_key: str | None = None,
    source_pointer: dict | None = None, gap: str | None = None, client=None,
) -> dict:
    # This boundary must not change ordinary capture's durable success/failure result.
    try:
        config = load_health_workspace(receipt)
        if config is None:
            return {"state": "disabled"}
        with _owner(receipt):
            spool = _spool(receipt)
            try:
                authorization = spool.read_health_state("authorization")
                if not authorization.get("enabled"):
                    return {"state": "disabled"}
                if (authorization.get("workspace_id") != config.workspace_id
                        or authorization.get("fingerprint") != config.pin.fingerprint):
                    raise DomainError("HEALTH_WORKSPACE_CHANGED", "Cached session scope no longer matches the explicit workspace")
                slot = "session:" + identity["key"]
                previous = spool.read_health_state(slot)
                if event_name in _END_EVENTS and previous.get("closed"):
                    return {"state": "already_closed", "coverage": "partial"}
                state = previous or _session_state(identity)
                if (event_name == "capture_origin" and origin_key is not None
                        and origin_key in state["origin_keys"] and source_pointer is None and gap is None):
                    return {"state": "already_observed", "coverage": "partial", "sequence": state["sequence"]}
                if event_name in _START_EVENTS and previous and not previous.get("closed"):
                    state["gaps"] = list(dict.fromkeys([*state["gaps"], "HOST_SEGMENT_RESTARTED"]))[:16]
                    _enqueue_session(spool, config, authorization, slot, state, "interrupted")
                late_known_capture = (
                    event_name in {"capture_committed", "capture_checkpoint", "capture_replay"}
                    and origin_key is not None and origin_key in state["origin_keys"]
                )
                if state.get("closed") and event_name not in _END_EVENTS and not late_known_capture:
                    state = _session_state(identity, state)
                    state["gaps"].append("HOST_OBSERVATION_DISCONTINUITY")
                if not previous and event_name not in _START_EVENTS:
                    state["gaps"].append("HOST_SEGMENT_START_UNOBSERVED")
                if origin_key is not None and len(state["origin_keys"]) >= 32 and origin_key not in state["origin_keys"]:
                    state["gaps"] = list(dict.fromkeys([*state["gaps"], "HOST_SEGMENT_MANIFEST_OVERFLOW"]))[:16]
                    _enqueue_session(spool, config, authorization, slot, state, "interrupted")
                    state = _session_state(identity, state)
                    state["gaps"].append("HOST_SEGMENT_MANIFEST_OVERFLOW")
                if origin_key is not None and origin_key not in state["origin_keys"]:
                    state["origin_keys"].append(origin_key)
                if source_pointer is not None:
                    pointer = SourcePointer.model_validate(source_pointer)
                    if pointer.binding_id != config.binding_id:
                        raise DomainError("HEALTH_WORKSPACE_SCOPE", "Capture pointer belongs to another binding")
                    reference = {"id": pointer.source_id, "revision": pointer.source_revision}
                    if reference not in state["source_refs"]:
                        if len(state["source_refs"]) < 32:
                            state["source_refs"].append(reference)
                        else:
                            state["gaps"].append("HOST_SOURCE_MANIFEST_OVERFLOW")
                if gap is not None:
                    if re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", gap) is None:
                        gap = "HOST_CAPTURE_DEGRADED"
                    state["gaps"].append(gap)
                state["gaps"] = list(dict.fromkeys(state["gaps"]))[:16]
                if event_name in _START_EVENTS:
                    event = "start"
                elif event_name in _END_EVENTS:
                    event = "end"
                elif event_name in _INTERRUPT_EVENTS:
                    event = "interrupted"
                elif event_name in _RESUME_EVENTS:
                    event = "resume"
                else:
                    event = "checkpoint"
                _enqueue_session(spool, config, authorization, slot, state, event)
                # Existing capture/recovery owns delivery; lifecycle observations do not spawn workers.
                if client is not None:
                    spool.flush(client, limit=4)
                return {"state": "durably_spooled", "coverage": "partial", "sequence": state["sequence"]}
            finally:
                spool.close()
    except (DomainError, OSError, sqlite3.Error, ValidationError, ValueError, UnicodeError) as error:
        return {"state": "gap", "code": error.code if isinstance(error, DomainError) else "HOST_HEALTH_UNAVAILABLE", "coverage": "unknown"}


def health_next_agent_hint(receipt: dict) -> str:
    config = load_health_workspace(receipt)
    if (config is None or not config.next_agent
            or receipt["capabilities"]["prompt_context"] == "disabled"):
        return ""
    spool = _spool(receipt)
    try:
        if not spool.read_health_state("authorization").get("enabled"):
            return ""
    finally:
        spool.close()
    return '{"health":"pending_may_exist","next":"Call memory_inspect with ref health; inspect each authorized health:item bundle before memory_record health_assessment.","coverage":"observed_segments_not_full_session","human_presence":"unattested"}'
