from __future__ import annotations

import argparse
import asyncio
import base64
import fcntl
import hashlib
import json
import os
import secrets
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from pydantic import ValidationError

from .client import LocalClient
from .config import MODEL_PURPOSES, ModelConfig, Settings, load_settings, resolve_binding
from .domain import (
    BindingRelocation,
    CaptureCommand,
    ContextCommand,
    DomainError,
    EffectState,
    FeedbackCommand,
    RecordCommand,
    Role,
    RuleApproval,
    RuleProposal,
    RuleScope,
    Selector,
    approval_signing_payload,
    canonical_digest,
)
from .private_io import private_read, private_write
from .wire import decode_json, validate_wire


def json_file(path: Path) -> dict:
    raw = private_read(path, 262144, private=False)
    if len(raw) > 262144:
        raise DomainError("INPUT_TOO_LARGE", "The JSON input exceeds its limit")
    return decode_json(raw)


def text_file(path: Path | None) -> str:
    if path is None:
        raw = sys.stdin.buffer.read(131073)
    else:
        raw = private_read(path, 131072, private=False)
    if len(raw) > 131072:
        raise DomainError("INPUT_TOO_LARGE", "The input file exceeds its text limit")
    return raw.decode("utf-8")


def token_path(args) -> Path:
    return args.token_file or args.config.with_suffix(".operator.token")


@asynccontextmanager
async def authority(args):
    from .journal import DeletionJournal
    from .ops import authority_lock
    from .store import Store

    settings = load_settings(args.config)
    with authority_lock(settings):
        store = Store(settings, DeletionJournal(settings.journal_dir, settings.deployment_id))
        await store.open()
        try:
            await store.reconcile_journal()
            actor = await store.authenticate(private_read(token_path(args), 4096).decode("utf-8").strip())
            yield settings, store, actor
        finally:
            await store.close()


def _model_config_digest(settings: Settings) -> str:
    return canonical_digest({
        "models": settings.models.model_dump(mode="json"),
        "purposes": list(settings.allowed_model_purposes),
    })


def _model_authority_digest(settings: Settings) -> str:
    values = settings.model_dump(mode="json")
    return canonical_digest({name: values[name] for name in (
        "deployment_id", "realm", "mode", "database_dsn", "migrator_dsn", "state_dir", "journal_dir",
    )})


def _guard_model_config(path: Path, expected: bytes) -> None:
    if private_read(path, 262144) != expected:
        raise DomainError("MODEL_APPROVAL_CONFLICT", "The private configuration changed before publication")


def _finish_model_approval_intent(path: Path) -> None:
    path.unlink()
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


async def _publish_model_approval(args, settings: Settings, actor, updated: Settings, runtime) -> dict:
    from .ops import _file, _private_directory

    _private_directory(settings.state_dir)
    lock_path = settings.state_dir / "model-approval.lock"
    if args.config.resolve() == lock_path.resolve():
        raise DomainError("PATH_DENIED", "Model approval cannot replace its recovery lock")
    try:
        private_write(lock_path, b"")
    except FileExistsError:
        pass
    descriptor = _file(lock_path, maximum=0)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DomainError("MODEL_APPROVAL_BUSY", "Another model approval is still reconciling") from None
        return await _reconcile_model_approval(args, settings, actor, updated, runtime)
    finally:
        os.close(descriptor)


async def _reconcile_model_approval(args, settings: Settings, actor, updated: Settings, runtime) -> dict:
    original_raw = private_read(args.config, 262144)
    original = Settings.model_validate_json(original_raw)
    authority_digest = _model_authority_digest(settings)
    if (_model_authority_digest(original) != authority_digest
            or _model_config_digest(original) != _model_config_digest(settings)):
        raise DomainError("MODEL_APPROVAL_CONFLICT", "The authority or model configuration changed during validation")
    updated = Settings.model_validate({
        **original.model_dump(), "models": updated.models,
        "allowed_model_purposes": updated.allowed_model_purposes,
    })
    target = _model_config_digest(updated)
    request = canonical_digest({
        "config_path": os.path.abspath(args.config), "authority": authority_digest,
        "principal": actor.id, "credential": actor.credential_id, "generation": actor.generation,
        "target": target, "revision": runtime.revision,
    })
    intent_path = settings.state_dir / "model-approval-intent.json"
    if args.config.resolve() == intent_path.resolve():
        raise DomainError("PATH_DENIED", "Model approval cannot replace its recovery intent")
    recovering = intent_path.exists() or intent_path.is_symlink()
    superseded_raw = None
    if recovering:
        try:
            intent_raw = private_read(intent_path, 4096)
            intent = decode_json(intent_raw)
            if (set(intent) != {"format", "request", "before", "target"}
                    or type(intent["format"]) is not int or intent["format"] != 1
                    or any(
                        not isinstance(intent[key], str) or len(intent[key]) != 64
                        or any(character not in "0123456789abcdef" for character in intent[key])
                        for key in ("request", "before", "target")
                    )
                    or _model_config_digest(original) not in {intent["before"], intent["target"]}):
                raise ValueError
            exact_retry = intent["request"] == request and intent["target"] == target
            if not exact_retry and args.supersede_pending_intent != hashlib.sha256(intent_raw).hexdigest():
                raise ValueError
        except (DomainError, ValueError, TypeError):
            raise DomainError("MODEL_APPROVAL_CONFLICT", "Reconcile the exact pending model approval without replacing conflicting configuration",
                effect=EffectState.UNKNOWN) from None
        if not exact_retry:
            replacement = {"format": 1, "request": request, "before": _model_config_digest(original), "target": target}
            try:
                private_write(intent_path, json.dumps(replacement) + "\n", replace=True,
                    before_publish=lambda: _guard_model_config(intent_path, intent_raw))
            except (DomainError, OSError):
                raise DomainError("MODEL_APPROVAL_RECOVERY_REQUIRED", "Pending approval replacement is uncertain; reconcile the current private intent",
                    status=503, effect=EffectState.UNKNOWN) from None
            superseded_raw = intent_raw
            intent = replacement
            recovering = False
    else:
        if args.supersede_pending_intent is not None:
            raise DomainError("MODEL_APPROVAL_CONFLICT", "No pending model approval matches the explicit supersession")
        intent = {"format": 1, "request": request, "before": _model_config_digest(original), "target": target}
        try:
            private_write(intent_path, json.dumps(intent) + "\n")
        except FileExistsError:
            raise DomainError("MODEL_APPROVAL_CONFLICT", "Another model approval owns the recovery intent") from None
        except OSError:
            raise DomainError("MODEL_APPROVAL_RECOVERY_REQUIRED", "Retry the exact model approval to reconcile its private intent",
                status=503, effect=EffectState.NOT_COMMITTED) from None
    adopted = False
    adoption_attempted = False
    try:
        if _model_config_digest(original) != target:
            private_write(args.config, updated.model_dump_json(indent=2) + "\n", replace=True,
                before_publish=lambda: _guard_model_config(args.config, original_raw))
        async with authority(args) as (adoption_settings, adoption_store, adoption_actor):
            if (_model_authority_digest(adoption_settings) != authority_digest
                    or _model_config_digest(adoption_settings) != target):
                raise DomainError("MODEL_APPROVAL_CONFLICT", "The published model configuration was superseded")
            if (
                adoption_actor.id, adoption_actor.credential_id, adoption_actor.realm,
                adoption_actor.role, adoption_actor.generation,
            ) != (
                actor.id, actor.credential_id, actor.realm, actor.role, actor.generation,
            ):
                raise DomainError("AUTH_DENIED", "The approval credential changed before route adoption", status=403)
            adoption_attempted = True
            await adoption_store.configure_route(actor, runtime.revision, updated.allowed_model_purposes, True)
            adopted = True
        current = load_settings(args.config)
        if _model_authority_digest(current) != authority_digest or _model_config_digest(current) != target:
            raise DomainError("MODEL_APPROVAL_CONFLICT", "The adopted model configuration was superseded")
        _finish_model_approval_intent(intent_path)
    except Exception as error:
        effect = EffectState.COMMITTED if adopted else EffectState.UNKNOWN
        uncertain_adoption = adoption_attempted and (
            not isinstance(error, DomainError) or error.effect not in {EffectState.NOT_STARTED, EffectState.NOT_COMMITTED}
        )
        if not adopted and not uncertain_adoption and not recovering:
            try:
                current_raw = private_read(args.config, 262144)
                current = Settings.model_validate_json(current_raw)
                current_digest = _model_config_digest(current)
                if _model_authority_digest(current) == authority_digest and current_digest in {intent["before"], target}:
                    if current_digest != intent["before"]:
                        restored = Settings.model_validate({
                            **current.model_dump(), "models": original.models,
                            "allowed_model_purposes": original.allowed_model_purposes,
                        })
                        private_write(args.config, restored.model_dump_json(indent=2) + "\n", replace=True,
                            before_publish=lambda: _guard_model_config(args.config, current_raw))
                    if superseded_raw is None:
                        _finish_model_approval_intent(intent_path)
                    else:
                        private_write(intent_path, superseded_raw, replace=True,
                            before_publish=lambda: _guard_model_config(intent_path, (json.dumps(intent) + "\n").encode()))
                    effect = EffectState.NOT_COMMITTED
            except (DomainError, OSError, ValueError):
                pass
        code = error.code if isinstance(error, DomainError) else "MODEL_APPROVAL_RECOVERY_REQUIRED"
        status = error.status if isinstance(error, DomainError) else 503
        raise DomainError(code, "Model approval did not complete; retry the exact request after resolving its barrier or configuration conflict",
            status=status, effect=effect) from None
    return {"route_revision": runtime.revision, "purposes": updated.allowed_model_purposes, "approved": True,
        "service_restart_required": True, "inference_verified": False}


async def _approve_models(args, settings: Settings) -> dict:
    from .models import LocalSemanticRuntime

    try:
        async with authority(args) as (settings, _, actor):
            if actor.role != Role.OPERATOR:
                raise DomainError("ROLE_DENIED", "Only the operator can adopt a local inference route", status=403)
            model = ModelConfig(
                generation_url=args.generation_url,
                generation_key_file=args.generation_key_file,
                generation_artifact=args.gguf,
                embedding_path=args.embedding,
                reranker_path=args.reranker,
                manifest_path=args.manifest,
                cpu_threads=args.cpu_threads,
            )
            updated = Settings.model_validate({
                **settings.model_dump(), "models": model,
                "allowed_model_purposes": tuple(args.purpose or MODEL_PURPOSES),
            })
            runtime = LocalSemanticRuntime(model)
            await asyncio.to_thread(runtime.validate_artifacts)
    except DomainError as error:
        intent = settings.state_dir / "model-approval-intent.json"
        if intent.exists() or intent.is_symlink():
            raise DomainError(
                error.code, "An earlier model approval is pending; resolve the authority barrier before reconciling its exact intent",
                status=error.status, effect=EffectState.UNKNOWN,
            ) from None
        raise
    return await _publish_model_approval(args, settings, actor, updated, runtime)


def scope_choice() -> RuleScope:
    if not sys.stdin.isatty():
        raise DomainError("RULE_SCOPE_REQUIRED", "Choose exactly local_project, my_projects or shared")
    print("1) 이 로컬 PC의 해당 프로젝트\n2) 내 프로젝트들: 명시 선택한 현재 목록을 동결\n3) 팀/프로젝트 공유", file=sys.stderr)
    value = input("적용 범위 [1/2/3]: ").strip()
    choices = {"1": RuleScope.LOCAL_PROJECT, "2": RuleScope.MY_PROJECTS, "3": RuleScope.SHARED}
    if value not in choices:
        raise DomainError("RULE_SCOPE_REQUIRED", "Exactly one of the three scopes is required")
    return choices[value]


def _execute_spool(args, settings: Settings) -> dict:
    from .spool import ProducerSpool

    spool = ProducerSpool(args.file, settings.deployment_id, args.binding, settings.spool_limit_bytes)
    try:
        if args.spool_action == "enqueue":
            return spool.enqueue(validate_wire(CaptureCommand, json_file(args.envelope_file)))
        if args.spool_action == "flush":
            return spool.flush(LocalClient(settings.base_url, token_path(args)), limit=args.limit)
        if args.spool_action == "inspect":
            return spool.inspect(args.key, args.limit)
        if args.spool_action in {"retry", "discard"}:
            return spool.resolve(args.key, discard=args.spool_action == "discard")
        return spool.status()
    finally:
        spool.close()


async def execute(args) -> dict | None:
    if args.command == "host-hook":
        from .hosts import HOST_INPUT_BYTES, handle_hook_input

        raw = sys.stdin.buffer.read(HOST_INPUT_BYTES + 1)
        result = await asyncio.to_thread(handle_hook_input, args.receipt, raw)
        if args.envelope:
            return result
        if result.get("stdout"):
            sys.stdout.buffer.write(json.dumps(result["stdout"], ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
            sys.stdout.buffer.flush()
        if result.get("stderr"):
            print(result["stderr"], file=sys.stderr)
        raise SystemExit(result.get("exit_code", 0))
    if args.command == "host-stdio":
        from .hosts import _scoped_cwd, load_receipt
        from .stdio import RelayEndpoint, run_stdio

        receipt = load_receipt(args.receipt)
        _scoped_cwd(receipt, {"cwd": str(Path.cwd())})
        endpoint = RelayEndpoint(
            base_url=receipt["base_url"],
            max_http_body_bytes=receipt["max_http_body_bytes"],
            max_mcp_response_bytes=receipt["max_mcp_response_bytes"],
        )
        await run_stdio(endpoint, Path(receipt["agent_token_file"]))
        return None
    if args.command == "host-uninstall":
        from .hosts import uninstall_host

        return await asyncio.to_thread(uninstall_host, load_settings(args.config), args.project, args.host, project_deleted=args.project_deleted)
    if args.command == "init":
        from .initialization import initialize_deployment

        return await initialize_deployment(
            config_path=args.config,
            realm=args.realm,
            mode=args.mode,
            database_dsn=text_file(args.dsn_file).strip(),
            migrator_dsn=text_file(args.migrator_dsn_file).strip(),
            state_dir=args.state_dir.resolve(),
            journal_dir=args.journal_dir.resolve(),
            port=args.port,
            owner_id=args.owner_id,
            operator_token_out=args.operator_token_out,
            deployment_id=args.deployment_id,
            resume=args.resume,
        )
    settings = load_settings(args.config)
    if args.command == "migrate":
        from .ops import migrate_authority

        return await migrate_authority(settings, token_path(args), args.confirm_deployment)
    if args.command in {"backup", "restore", "restore-recover"}:
        from .ops import backup, recover_interrupted_restore, restore

        if args.command == "restore-recover":
            return await recover_interrupted_restore(
                settings, token_path(args), args.expected_head, args.operator_out, args.confirm_deployment,
                ops_runtime(args),
            )
        runtime = ops_runtime(args)
        if args.command == "backup":
            return await backup(settings, token_path(args), args.output, args.recipients_file, runtime)
        return await restore(
            settings, token_path(args), args.archive, args.identity_file, args.expected_head,
            args.operator_out, args.confirm_deployment, runtime,
        )
    if args.command == "spool":
        return await asyncio.to_thread(_execute_spool, args, settings)
    if args.command == "serve":
        import uvicorn

        from .edge import create_app

        config = uvicorn.Config(create_app(settings), host="127.0.0.1", port=settings.port, access_log=False, log_level="warning", timeout_graceful_shutdown=150)
        await uvicorn.Server(config).serve()
        return None
    if args.command == "model" and args.model_action == "fetch":
        from .model_setup import fetch_checkpoints

        async with authority(args) as (_, _, actor):
            if actor.role != Role.OPERATOR:
                raise DomainError("ROLE_DENIED", "Only an operator may download public weights", status=403)
        return await asyncio.to_thread(fetch_checkpoints, args.directory, allow_network=args.allow_network, mode=settings.mode)
    if args.command == "model" and args.model_action == "manifest":
        from .model_setup import write_model_manifest

        async with authority(args) as (_, _, actor):
            if actor.role != Role.OPERATOR:
                raise DomainError("ROLE_DENIED", "Only an operator may adopt model artifacts", status=403)
        result = await asyncio.to_thread(
            write_model_manifest, args.output, args.original, args.gguf, args.embedding, args.reranker,
            quantization="Q4_K_M", converter=args.converter,
        )
        from .domain import canonical_digest

        return {"manifest_file": str(args.output), "revision": canonical_digest(result), "provenance": "locally_converted_pinned_originals"}
    if args.command == "stdio":
        from .stdio import run_stdio

        await run_stdio(settings, token_path(args))
        return None
    if args.command == "model" and args.model_action == "approve":
        return await _approve_models(args, settings)
    if args.command in {"context", "record", "feedback", "capture", "inspect", "correct"}:
        client = LocalClient(settings.base_url, token_path(args))
        if args.command == "context":
            command = ContextCommand(
                binding_id=args.binding,
                query=text_file(args.query_file).strip(),
                mode=args.mode,
                idempotency_key=args.key,
                paths=tuple(args.path) if args.path is not None else None,
                purpose=args.purpose,
                host=args.host,
                snapshot=args.snapshot,
                causal_operation=args.causal_operation,
                max_bytes=args.max_bytes,
                limit=args.limit,
            )
        elif args.command == "record":
            command = RecordCommand(binding_id=args.binding, idempotency_key=args.key, body=text_file(args.body_file), kind=args.kind)
        elif args.command == "feedback":
            command = FeedbackCommand(binding_id=args.binding, idempotency_key=args.key, target_ref=args.ref, kind=args.kind, body=text_file(args.body_file) if args.body_file else None)
        elif args.command == "inspect":
            return await client.call("/api/inspect", {"binding_id": args.binding, "ref": args.ref, "snapshot": args.snapshot})
        else:
            command = validate_wire(CaptureCommand, json_file(args.envelope_file))
            if args.command == "correct":
                return await client.call("/api/correct", {"target_ref": args.ref, "source": command.model_dump(mode="json")})
        return await client.call("/api/" + args.command, command.model_dump(mode="json"))
    async with authority(args) as (settings, store, actor):
        if args.command == "host-install":
            from .hosts import install_host

            if actor.role != Role.OPERATOR:
                raise DomainError("ROLE_DENIED", "Only the operator can install a project adapter", status=403)
            projects = {project.id: project for project in await store.list_bindings(actor)}
            binding = projects.get(args.binding)
            project_root = args.project.resolve()
            if binding is None or binding.locator is None or Path(binding.locator).resolve() != project_root:
                raise DomainError("HOST_SCOPE_DENIED", "The explicit binding locator does not match this project", status=403)
            for path, role in ((args.agent_token_file, Role.AGENT), (args.producer_token_file, Role.PRODUCER)):
                principal = await store.authenticate(private_read(path, 4096).decode("utf-8").strip(), (role,))
                if principal.bindings != (args.binding,):
                    raise DomainError("HOST_SCOPE_DENIED", "Each adapter credential must grant exactly this project", status=403)
            return await asyncio.to_thread(
                install_host, settings, project_root, args.binding, args.host,
                args.agent_token_file.resolve(), args.producer_token_file.resolve(), strict=args.strict,
                prompt_recall=args.prompt_recall,
            )
        if args.command == "project":
            if args.project_action == "add":
                binding = await store.register_binding(actor, args.label, str(args.locator.resolve()) if args.locator else None, args.key)
                return binding.model_dump(mode="json")
            if args.project_action == "relocate":
                try:
                    locator = args.locator.resolve(strict=True)
                except (OSError, RuntimeError):
                    raise DomainError("BINDING_LOCATOR_INVALID", "The new project directory is unavailable") from None
                if not locator.is_dir():
                    raise DomainError("BINDING_LOCATOR_INVALID", "The new project locator must be a directory")
                command = BindingRelocation(
                    binding_id=args.binding, expected_revision=args.expected_revision,
                    expected_locator=os.path.abspath(args.expected_locator),
                    locator=str(locator), idempotency_key=args.key,
                )
                return (await store.relocate_binding(actor, command)).model_dump(mode="json")
            return {"projects": [item.model_dump(mode="json") for item in await store.list_bindings(actor)], "target_set_revision": await store.target_set_revision(actor)}
        if args.command == "credential":
            if actor.role != Role.OPERATOR:
                raise DomainError("ROLE_DENIED", "Only the operator can manage authority credentials", status=403)
            if args.credential_action == "revoke":
                if args.preview:
                    return await store.credential_revocation_impact(actor, args.credential_id)
                return await store.revoke_token(actor, args.credential_id, acknowledge_required=args.ack_required_rules)
            secret = secrets.token_urlsafe(32)
            private_write(args.output, secret + "\n")
            principal = await store.issue_token(actor, Role(args.role), tuple(args.binding), secret)
            return {"principal": principal.model_dump(mode="json"), "token_file": str(args.output), "strong_human_presence": False}
        if args.command == "model" and args.model_action == "disable":
            revision = args.revision or settings.models.revision()
            await store.configure_route(actor, revision, tuple(args.purpose or MODEL_PURPOSES), False)
            return {"route_revision": revision, "disabled": True, "new_admission_required_after_reenable": True}
        if args.command == "stats":
            return await store.stats(actor, resolve_binding(actor, args.binding), args.snapshot)
        if args.command == "doctor":
            projects = await store.list_bindings(actor)
            return {
                "deployment_id": settings.deployment_id,
                "realm": settings.realm,
                "mode": settings.mode,
                "projects": len(projects),
                "journal": store.journal.verify(),
                "freshness": "local_chain_only_not_external_latest_proof",
                "model_route_configured": bool(settings.allowed_model_purposes),
                "background_inference": "loopback_only",
                "host_automatic_calls": "require_opt_in_adapter",
                "human_presence": "not_proven_by_local_bearer",
            }
        if args.command == "await":
            binding = resolve_binding(actor, args.binding)
            deadline = time.monotonic() + args.deadline
            while time.monotonic() < deadline:
                operation = await store.operation(actor, binding, args.operation)
                if operation.state in {"semantic_ready", "blocked", "failed", "retracted"}:
                    return operation.model_dump(mode="json")
                await asyncio.sleep(0.25)
            raise DomainError("OPERATION_PENDING", "The durable operation has not reached a terminal semantic state")
        if args.command == "retry":
            await store.retry_job(actor, args.job)
            return {"job_id": args.job, "retry_requested": True, "semantic_ready": False}
        if args.command == "source-reprocess":
            operation = await store.reprocess(actor, resolve_binding(actor, args.binding), args.ref, args.key)
            return operation.model_dump(mode="json")
        if args.command == "index-status":
            return await store.index_status(
                actor, resolve_binding(actor, args.binding), args.snapshot, args.limit, args.after
            )
        if args.command == "index-recover":
            operation = await store.recover_index(
                actor, resolve_binding(actor, args.binding), tuple(args.claim), args.key, args.snapshot
            )
            return operation.model_dump(mode="json")
        if args.command in {"retract", "purge"}:
            action = store.retract if args.command == "retract" else store.purge
            return await action(actor, resolve_binding(actor, args.binding), args.ref, args.key)
        if args.command == "rule":
            if args.rule_action == "propose":
                selector = validate_wire(Selector, json_file(args.selector_file)) if args.selector_file else Selector()
                command = RuleProposal(
                    binding_id=resolve_binding(actor, args.binding),
                    idempotency_key=args.key,
                    body=text_file(args.body_file),
                    selector=selector,
                    exceptions=tuple(args.exception or ()),
                    required=args.required,
                    source_ids=tuple(args.source or ()),
                )
                return await store.propose_rule(actor, command)
            if args.rule_action == "withdraw":
                return await store.withdraw_rule(actor, resolve_binding(actor, args.binding), args.ref, args.key)
            command = RuleApproval(
                proposal_id=args.ref,
                expected_digest=args.digest,
                scope=RuleScope(args.scope) if args.scope else scope_choice(),
                target_bindings=tuple(args.target),
                target_set_revision=args.roster_revision,
                idempotency_key=args.key,
                approver_signature=private_read(args.signature_file, 256).decode("utf-8").strip() if args.signature_file else None,
            )
            if args.rule_action == "approval-request":
                private_write(args.output, approval_signing_payload(settings.deployment_id, settings.realm, actor.id, command))
                return {"approval_request_file": str(args.output), "active": False}
            result = await store.approve_rule(actor, command)
            return result.model_dump(mode="json")
        if args.command == "approval-sign":
            if actor.role != Role.OPERATOR:
                raise DomainError("ROLE_DENIED", "The independent signer command requires operator access", status=403)
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import load_pem_private_key

            key = load_pem_private_key(args.key_file.read_bytes(), password=None)
            if not isinstance(key, Ed25519PrivateKey):
                raise DomainError("SIGNER_KEY_INVALID", "An independently managed Ed25519 signing key is required")
            payload = args.request_file.read_bytes()
            if len(payload) > 32768:
                raise DomainError("INPUT_TOO_LARGE", "The exact approval request exceeds its limit")
            private_write(args.output, base64.b64encode(key.sign(payload)) + b"\n")
            return {"signature_file": str(args.output), "key_possession_signature": True, "human_presence": "not_proven"}
    raise DomainError("COMMAND_UNKNOWN", "The requested action is unavailable")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="agents-memory", description="Local-first shared memory authority; no implicit cloud or auto-approval")
    root.add_argument("--version", action="version", version="agents-memory 0.1.0")
    root.add_argument("--config", type=Path, default=Path.home() / ".config/agents-memory/personal.json")
    root.add_argument("--token-file", type=Path)
    commands = root.add_subparsers(dest="command", required=True)
    hook = commands.add_parser("host-hook")
    hook.add_argument("--receipt", type=Path, required=True)
    hook.add_argument("--envelope", action="store_true")
    relay = commands.add_parser("host-stdio")
    relay.add_argument("--receipt", type=Path, required=True)
    install = commands.add_parser("host-install")
    install.add_argument("--project", type=Path, required=True)
    install.add_argument("--binding", required=True)
    install.add_argument("--host", choices=("claude", "codex", "omp"), required=True)
    install.add_argument("--agent-token-file", type=Path, required=True)
    install.add_argument("--producer-token-file", type=Path, required=True)
    install.add_argument("--strict", action="store_true")
    install.add_argument("--prompt-recall", action="store_true", help="Opt into bounded semantic retrieval before each native prompt")
    uninstall = commands.add_parser("host-uninstall")
    uninstall.add_argument("--project", type=Path, required=True)
    uninstall.add_argument("--host", choices=("claude", "codex", "omp"), required=True)
    uninstall.add_argument("--project-deleted", action="store_true", help="Acknowledge the project was deleted; only native entries can be verified and removed")
    migration = commands.add_parser("migrate", help="Upgrade a stopped authority through the private operator connection")
    migration.add_argument("--confirm-deployment", required=True)
    init = commands.add_parser("init")
    init.add_argument("--deployment-id", required=True)
    init.add_argument("--realm", required=True)
    init.add_argument("--mode", choices=("personal", "company"), required=True)
    init.add_argument("--dsn-file", type=Path, required=True)
    init.add_argument("--migrator-dsn-file", type=Path, required=True)
    init.add_argument("--state-dir", type=Path, required=True)
    init.add_argument("--journal-dir", type=Path, required=True)
    init.add_argument("--owner-id", required=True)
    init.add_argument("--operator-token-out", type=Path)
    init.add_argument("--port", type=int, default=8768)
    init.add_argument("--resume", action="store_true", help="Resume only an authenticated matching initialization intent")
    for action in ("backup", "restore", "restore-recover"):
        operation = commands.add_parser(action)
        operation.add_argument("--age-binary", type=Path, required=True)
        operation.add_argument("--runtime", choices=("local", "docker"), default="local")
        operation.add_argument("--pg-dump-binary", default="pg_dump")
        operation.add_argument("--pg-restore-binary", default="pg_restore")
        operation.add_argument("--psql-binary", default="psql")
        operation.add_argument("--docker-binary", type=Path)
        operation.add_argument("--docker-config", type=Path)
        operation.add_argument("--docker-host")
        operation.add_argument("--docker-container")
        operation.add_argument("--timeout", type=float, default=3600)
        if action == "backup":
            operation.add_argument("--output", type=Path, required=True)
            operation.add_argument("--recipients-file", type=Path, required=True)
        else:
            operation.add_argument("--expected-head", required=True)
            operation.add_argument("--operator-out", type=Path, required=True)
            operation.add_argument("--confirm-deployment", required=True)
            if action == "restore":
                operation.add_argument("--archive", type=Path, required=True)
                operation.add_argument("--identity-file", type=Path, required=True)
    outbox = commands.add_parser("spool").add_subparsers(dest="spool_action", required=True)
    for action in ("enqueue", "status", "flush", "inspect", "retry", "discard"):
        operation = outbox.add_parser(action)
        operation.add_argument("--file", type=Path, required=True)
        operation.add_argument("--binding", required=True)
        if action == "enqueue":
            operation.add_argument("--envelope-file", type=Path, required=True)
        if action in {"flush", "inspect"}:
            operation.add_argument("--limit", type=int, default=32)
        if action == "inspect":
            operation.add_argument("--key")
        if action in {"retry", "discard"}:
            operation.add_argument("--key", required=True)
    commands.add_parser("serve")
    commands.add_parser("stdio")
    commands.add_parser("doctor")
    stats = commands.add_parser("stats")
    stats.add_argument("--binding")
    stats.add_argument("--snapshot")
    project = commands.add_parser("project").add_subparsers(dest="project_action", required=True)
    project.add_parser("list")
    add = project.add_parser("add")
    add.add_argument("--label", required=True)
    add.add_argument("--locator", type=Path)
    add.add_argument("--key", required=True)
    relocate = project.add_parser("relocate")
    relocate.add_argument("--binding", required=True)
    relocate.add_argument("--expected-revision", type=int, required=True)
    relocate.add_argument("--expected-locator", type=Path, required=True)
    relocate.add_argument("--locator", type=Path, required=True)
    relocate.add_argument("--key", required=True)
    credential = commands.add_parser("credential").add_subparsers(dest="credential_action", required=True)
    issue = credential.add_parser("issue")
    issue.add_argument("--role", choices=tuple(Role), required=True)
    issue.add_argument("--binding", action="append", required=True)
    issue.add_argument("--output", type=Path, required=True)
    revoke = credential.add_parser("revoke")
    revoke.add_argument("--credential-id", required=True)
    revoke.add_argument("--preview", action="store_true", help="Report body-free rule invalidation impact without revoking")
    revoke.add_argument("--ack-required-rules", action="store_true", help="Explicitly acknowledge affected mandatory rule invalidation")
    model = commands.add_parser("model").add_subparsers(dest="model_action", required=True)
    fetch = model.add_parser("fetch")
    fetch.add_argument("--directory", type=Path, required=True)
    fetch.add_argument("--allow-network", action="store_true")
    manifest = model.add_parser("manifest")
    for name in ("output", "original", "gguf", "embedding", "reranker", "converter"):
        manifest.add_argument("--" + name, type=Path, required=True)
    approve = model.add_parser("approve")
    for name in ("manifest", "gguf", "embedding", "reranker", "generation-key-file"):
        approve.add_argument("--" + name, type=Path, required=True)
    approve.add_argument("--generation-url", required=True)
    approve.add_argument("--cpu-threads", type=int, default=8)
    approve.add_argument("--supersede-pending-intent", help="Explicitly start a new authorized approval in place of this exact pending intent SHA256")
    approve.add_argument("--purpose", action="append", choices=MODEL_PURPOSES)
    disable = model.add_parser("disable")
    disable.add_argument("--revision")
    disable.add_argument("--purpose", action="append", choices=MODEL_PURPOSES)
    context = commands.add_parser("context")
    context.add_argument("--binding")
    context.add_argument("--query-file", type=Path)
    context.add_argument("--mode", choices=("recall", "reflect"), default="recall")
    context.add_argument("--key")
    context.add_argument("--path", action="append")
    context.add_argument("--purpose", default="general")
    context.add_argument("--host", choices=("generic", "claude", "codex", "omp", "agent-flow"), default="generic")
    context.add_argument("--snapshot")
    context.add_argument("--causal-operation")
    context.add_argument("--max-bytes", type=int, default=2400)
    context.add_argument("--limit", type=int, default=3)
    record = commands.add_parser("record")
    record.add_argument("--binding")
    record.add_argument("--body-file", type=Path)
    record.add_argument("--kind", choices=("note", "rule_candidate"), default="note")
    record.add_argument("--key", required=True)
    feedback = commands.add_parser("feedback")
    feedback.add_argument("--binding")
    feedback.add_argument("--body-file", type=Path)
    feedback.add_argument("--kind", choices=("correct", "reject", "retract_request"), required=True)
    feedback.add_argument("--ref", required=True)
    feedback.add_argument("--key", required=True)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("--binding")
    inspect.add_argument("--ref", required=True)
    inspect.add_argument("--snapshot")
    for name in ("capture", "correct"):
        capture = commands.add_parser(name)
        capture.add_argument("--envelope-file", type=Path, required=True)
        if name == "correct":
            capture.add_argument("--ref", required=True)
    awaiter = commands.add_parser("await")
    awaiter.add_argument("--binding")
    awaiter.add_argument("--operation", required=True)
    awaiter.add_argument("--deadline", type=float, default=180)
    retry = commands.add_parser("retry")
    retry.add_argument("--job", required=True)
    reprocess = commands.add_parser("source-reprocess")
    reprocess.add_argument("--binding", required=True)
    reprocess.add_argument("--ref", required=True)
    reprocess.add_argument("--key", required=True)
    index_status = commands.add_parser("index-status")
    index_status.add_argument("--binding", required=True)
    index_status.add_argument("--snapshot")
    index_status.add_argument("--limit", type=int, default=32)
    index_status.add_argument("--after")
    index_recover = commands.add_parser("index-recover")
    index_recover.add_argument("--binding", required=True)
    index_recover.add_argument("--snapshot")
    index_recover.add_argument("--claim", action="append", required=True)
    index_recover.add_argument("--key", required=True)
    for name in ("retract", "purge"):
        retract = commands.add_parser(name)
        retract.add_argument("--binding")
        retract.add_argument("--ref", required=True)
        retract.add_argument("--key", required=True)
    rule = commands.add_parser("rule").add_subparsers(dest="rule_action", required=True)
    propose = rule.add_parser("propose")
    propose.add_argument("--binding")
    propose.add_argument("--body-file", type=Path)
    propose.add_argument("--selector-file", type=Path)
    propose.add_argument("--source", action="append")
    propose.add_argument("--exception", action="append")
    propose.add_argument("--required", action="store_true")
    propose.add_argument("--key", required=True)
    for name in ("approve", "approval-request"):
        approve = rule.add_parser(name)
        approve.add_argument("--ref", required=True)
        approve.add_argument("--digest", required=True)
        approve.add_argument("--scope", choices=tuple(RuleScope))
        approve.add_argument("--target", action="append", required=True)
        approve.add_argument("--roster-revision", type=int, required=True)
        approve.add_argument("--key", required=True)
        approve.add_argument("--signature-file", type=Path)
        if name == "approval-request":
            approve.add_argument("--output", type=Path, required=True)
    withdraw = rule.add_parser("withdraw")
    withdraw.add_argument("--binding")
    withdraw.add_argument("--ref", required=True)
    withdraw.add_argument("--key", required=True)
    signer = commands.add_parser("approval-sign")
    signer.add_argument("--request-file", type=Path, required=True)
    signer.add_argument("--key-file", type=Path, required=True)
    signer.add_argument("--output", type=Path, required=True)
    return root


def ops_runtime(args):
    from .ops import BackupRuntime

    return BackupRuntime(
        age_binary=args.age_binary, mode=args.runtime, pg_dump_binary=args.pg_dump_binary,
        pg_restore_binary=args.pg_restore_binary, psql_binary=args.psql_binary, docker_binary=args.docker_binary,
        docker_config=args.docker_config, docker_host=args.docker_host, docker_container=args.docker_container,
        timeout_seconds=args.timeout,
    )


def main() -> None:
    args = parser().parse_args()
    try:
        result = asyncio.run(execute(args))
        if result is not None:
            sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n")
            sys.stdout.buffer.flush()
    except DomainError as error:
        print(json.dumps({"error": error.public()}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1) from None
    except (ValidationError, OSError, ValueError):
        print(json.dumps({"error": {"code": "LOCAL_INPUT_INVALID", "message": "The private input, artifact or output is invalid", "effect": "unknown"}}), file=sys.stderr)
        raise SystemExit(1) from None
    except Exception:
        print(json.dumps({"error": {"code": "LOCAL_OPERATION_FAILED", "message": "The authority operation failed; reconcile its durable state", "effect": "unknown"}}), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
