from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import secrets
import socket
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from pydantic import ValidationError

from .client import client_from_settings
from .config import Settings, load_settings, prepare_settings_upgrade, resolve_binding
from .connection import (
    RemoteClientSettings,
    configure_remote_client,
    load_connection_settings,
    validate_remote_project,
)
from .domain import (
    BindingRelocation,
    CaptureCommand,
    ContextCommand,
    DomainError,
    EffectState,
    FeedbackCommand,
    Role,
    RuleApproval,
    RuleProposal,
    RuleScope,
    Selector,
    approval_signing_payload,
)
from .jev import JEV_DEFAULT_MODEL
from .judge import (
    PROVIDER_FILE,
    describe,
    grant_new_binding,
    has_key,
    load_state,
    read_key,
    read_supplied_key,
    read_worker_token,
    require_jev_allowed,
    set_agent,
    set_egress_policy,
    set_jev,
    validate_key,
    verify_key,
    worker_snapshot,
)
from .private_io import private_read, private_write
from .selection import RECORD_ADAPTER, RecordInput
from .wire import decode_json, decode_json_value, validate_wire


def json_file(path: Path):
    raw = private_read(path, 262144, private=False)
    if len(raw) > 262144:
        raise DomainError("INPUT_TOO_LARGE", "The JSON input exceeds its limit")
    return decode_json(raw)


def json_array_file(path: Path) -> list:
    value = decode_json_value(private_read(path, 262144, private=False))
    if not isinstance(value, list):
        raise DomainError("INPUT_INVALID", "The input file requires a complete JSON array")
    return value


def text_file(path: Path | None) -> str:
    if path is None:
        raw = sys.stdin.buffer.read(131073)
    else:
        raw = private_read(path, 131072, private=False)
    if len(raw) > 131072:
        raise DomainError("INPUT_TOO_LARGE", "The input file exceeds its text limit")
    return raw.decode("utf-8")


def record_input(args) -> RecordInput:
    values = vars(args)
    if args.judgment_file is not None:
        if any(name in values for name in ("binding", "key", "body_file", "kind")):
            raise DomainError("INPUT_INVALID", "A frozen judgment file cannot be mixed with record overrides")
        return validate_wire(RECORD_ADAPTER, json_file(args.judgment_file))
    if "key" not in values:
        raise DomainError("INPUT_INVALID", "A note or rule candidate requires an explicit retry key")
    return validate_wire(RECORD_ADAPTER, {
        "binding_id": values.get("binding"), "idempotency_key": values.get("key"),
        "body": text_file(values.get("body_file")), "kind": values.get("kind", "note"),
    })


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




def scope_choice() -> RuleScope:
    if not sys.stdin.isatty():
        raise DomainError("RULE_SCOPE_REQUIRED", "Choose exactly local_project, my_projects or shared")
    print("1) 이 로컬 PC의 해당 프로젝트\n2) 내 프로젝트들: 명시 선택한 현재 목록을 동결\n3) 팀/프로젝트 공유", file=sys.stderr)
    value = input("적용 범위 [1/2/3]: ").strip()
    choices = {"1": RuleScope.LOCAL_PROJECT, "2": RuleScope.MY_PROJECTS, "3": RuleScope.SHARED}
    if value not in choices:
        raise DomainError("RULE_SCOPE_REQUIRED", "Exactly one of the three scopes is required")
    return choices[value]


def judge_choice() -> str:
    print("기억 판단 provider를 고르세요.\n"
          "1) agent — 지금 쓰는 coding agent(Claude Code·Codex·OMP 구독)가 MCP로 판단 [기본]\n"
          "2) jev — TypeSafe Jev API가 백그라운드에서 판단 (capture 원문 window가 api.typesafe.ai(미국)로 전송, API 키 필요)",
          file=sys.stderr)
    print("선택 [1/2, 기본 1]: ", end="", file=sys.stderr, flush=True)
    value = sys.stdin.readline().strip() or "1"
    choices = {"1": "agent", "agent": "agent", "2": "jev", "jev": "jev"}
    if value not in choices:
        raise DomainError("JUDGE_PROVIDER_REQUIRED", "Choose exactly agent or jev")
    return choices[value]


def jev_key(key_file: Path | None, stored=None) -> tuple[str, list[str]]:
    """Key sources in order: an explicit file, the stored private copy, a no-echo terminal prompt."""
    if key_file is not None:
        return read_supplied_key(key_file)
    if stored is not None:
        return stored(), []
    if not sys.stdin.isatty():
        raise DomainError("JUDGE_KEY_REQUIRED", "Pass --key-file, or run in a terminal to enter the Jev API key without echo")
    import getpass

    return validate_key(getpass.getpass("Jev API 키 (화면에 표시되지 않음): ", stream=sys.stderr)), []


async def init_judge_plan(args) -> tuple | None:
    """Obtain separate egress consent and verify the choice before initialization effects."""
    if (args.state_dir.resolve() / "judge" / PROVIDER_FILE).exists():
        return None
    allowed = args.jev_policy == "allow"
    if allowed and not args.ack_jev_egress:
        raise DomainError("JUDGE_EGRESS_ACK_REQUIRED",
            "Allowing Jev requires --ack-jev-egress: source windows are sent to api.typesafe.ai in the US", status=403)
    provider = args.judge or (judge_choice() if sys.stdin.isatty() else "agent")
    if provider == "agent":
        if args.jev_key_file is not None:
            raise DomainError("INPUT_INVALID", "--jev-key-file applies only to --judge jev")
        return ("agent", None, [], None, allowed)
    if not allowed and args.jev_policy is None and sys.stdin.isatty():
        print("이 배포의 원문을 api.typesafe.ai(미국)로 전송하도록 별도로 허용합니까? [yes/기본 no]: ",
              end="", file=sys.stderr, flush=True)
        allowed = sys.stdin.readline().strip().lower() == "yes"
    if not allowed:
        raise DomainError("JUDGE_PROVIDER_FORBIDDEN",
            "Jev requires an independent egress grant: --jev-policy allow --ack-jev-egress", status=403)
    key, warnings = jev_key(args.jev_key_file)
    return ("jev", key, warnings, await asyncio.to_thread(verify_key, key, JEV_DEFAULT_MODEL), True)


async def apply_init_judge(args, result: dict, plan: tuple | None) -> dict:
    if plan is None:
        settings = load_settings(args.config)
        return {**describe(settings, load_state(settings), operator=True),
                "unchanged": "already configured; change it with agents-memory judge set"}
    provider, key, warnings, model, allowed = plan
    operator = argparse.Namespace(**{**vars(args), "token_file": Path(result["operator_token_file"])})
    try:
        async with authority(operator) as (settings, store, actor):
            await set_egress_policy(settings, store, actor, jev_allowed=allowed)
            if provider == "jev":
                outcome = await set_jev(settings, store, actor, key, verify=lambda _key, _model: model)
            else:
                outcome = await set_agent(settings, store, actor, forget_key=False)
    except DomainError as error:
        return {"error": error.public(), "next": f"agents-memory judge set {provider}"}
    if warnings:
        outcome["warnings"] = warnings
    return outcome


async def execute_judge(args, settings: Settings, store, actor) -> dict:
    if args.judge_action == "status":
        state = load_state(settings)
        projects = [binding.id for binding in await store.list_bindings(actor)]
        grants: list[str] | dict | None = None
        if state.provider == "jev":
            try:
                grants = list((await store.authenticate(read_worker_token(settings), (Role.AGENT,))).bindings)
            except DomainError as error:
                grants = {"error": error.code}
        return {
            **describe(settings, state, operator=True),
            "projects": projects,
            "worker_grants": grants,
            "projects_without_worker_grant": [item for item in projects if item not in grants] if isinstance(grants, list) else None,
            "worker": worker_snapshot(settings),
        }
    if args.judge_action == "policy":
        allowed = args.policy == "allow-jev"
        if allowed and not args.ack_egress:
            raise DomainError("JUDGE_EGRESS_ACK_REQUIRED",
                "Pass --ack-egress only after approving this deployment's source transfer to api.typesafe.ai in the US",
                status=403)
        return await set_egress_policy(settings, store, actor, jev_allowed=allowed)
    if args.provider == "agent":
        if args.key_file is not None or args.prompt_key:
            raise DomainError("INPUT_INVALID", "Key options apply only to judge set jev")
        return await set_agent(settings, store, actor, forget_key=args.forget_key)
    if args.forget_key:
        raise DomainError("INPUT_INVALID", "--forget-key applies only to judge set agent")
    require_jev_allowed(settings)
    stored = None if args.prompt_key or not has_key(settings) else (lambda: read_key(settings))
    key, warnings = jev_key(args.key_file, stored)
    result = await set_jev(settings, store, actor, key, model=args.model)
    if warnings:
        result["warnings"] = warnings
    return result


def _execute_spool(args, settings: Settings | RemoteClientSettings) -> dict:
    from .spool import ProducerSpool

    spool = ProducerSpool(args.file, settings.deployment_id, args.binding, settings.spool_limit_bytes)
    try:
        if args.spool_action == "enqueue":
            return spool.enqueue(validate_wire(CaptureCommand, json_file(args.envelope_file)))
        if args.spool_action == "flush":
            return spool.flush(client_from_settings(settings, token_path(args)), limit=args.limit)
        if args.spool_action == "inspect":
            return spool.inspect(args.key, args.limit)
        if args.spool_action in {"retry", "discard"}:
            return spool.resolve(args.key, discard=args.spool_action == "discard")
        return spool.status()
    finally:
        spool.close()


async def _install_remote_host(args, settings: RemoteClientSettings) -> dict:
    from .hosts import install_host
    from .ingress import ClientBootstrapRequest, ClientBootstrapResult

    if not args.ack_remote_storage:
        raise DomainError("REMOTE_STORAGE_ACK_REQUIRED", "Explicitly approve capture and memory storage at the configured remote authority", status=403)
    project = args.project.resolve(strict=True)
    validate_remote_project(settings, project)
    request = ClientBootstrapRequest(binding_id=args.binding).model_dump(mode="json")
    grants = []
    for path, role in ((args.agent_token_file, "agent"), (args.producer_token_file, "producer")):
        result = await client_from_settings(settings, path).call("/api/client-bootstrap", request)
        try:
            grant = validate_wire(ClientBootstrapResult, result)
        except (ValueError, TypeError):
            raise DomainError("BOOTSTRAP_INVALID", "The server did not return an exact bounded client grant", status=503) from None
        if (grant.deployment_id != settings.deployment_id or grant.realm != settings.realm
                or grant.mode != settings.mode or grant.capability != settings.capability
                or grant.auth_mode != settings.auth_mode or grant.role != role
                or grant.binding_id != args.binding or grant.bindings != (args.binding,)
                or any(getattr(grant.bounds, key) != getattr(settings, key) for key in (
                    "max_capture_bytes", "max_http_body_bytes", "max_mcp_response_bytes", "spool_limit_bytes",
                ))):
            raise DomainError("HOST_SCOPE_DENIED", "The current remote grant does not match this connection and binding", status=403)
        grants.append(grant)
    if grants[0].credential_id == grants[1].credential_id:
        raise DomainError("HOST_CREDENTIAL_SEPARATION_REQUIRED", "Agent and producer must use separate remote principals", status=403)
    if grants[0].binding_revision != grants[1].binding_revision:
        raise DomainError("HOST_SCOPE_DENIED", "The binding changed during remote installation", status=403)
    return await asyncio.to_thread(
        install_host, settings, project, args.binding, args.host,
        args.agent_token_file.resolve(), args.producer_token_file.resolve(),
        strict=args.strict, prompt_recall=args.prompt_recall,
    )


async def execute(args) -> dict | None:
    if args.command == "native-status":
        from .native_status import native_status

        return await asyncio.to_thread(
            native_status, args.project, args.host, codex_executable=args.codex_executable,
        )
    native_observation = None
    if args.command == "doctor":
        from .native_memory import native_memory_status

        native_observation = await asyncio.to_thread(native_memory_status, args.project) if args.project is not None else {
            "state": "project_not_selected", "next": "Use doctor --project or native-status with an explicit project; native memory is not disabled automatically",
        }
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
        from .hosts import load_receipt, receipt_connection
        from .stdio import RelayEndpoint, run_stdio

        receipt = load_receipt(args.receipt)
        endpoint = RelayEndpoint(
            base_url=receipt["base_url"],
            max_http_body_bytes=receipt["max_http_body_bytes"],
            max_mcp_response_bytes=receipt["max_mcp_response_bytes"],
            state_dir=Path(receipt["runtime_dir"]).parent.parent,
            deployment_id=receipt["deployment_id"],
            remote_settings=receipt_connection(receipt),
        )
        await run_stdio(endpoint, Path(receipt["agent_token_file"]))
        return None
    if args.command == "host-uninstall":
        from .hosts import uninstall_host
        from .service import load_control_settings
        return await asyncio.to_thread(uninstall_host, load_control_settings(args.config), args.project, args.host, project_deleted=args.project_deleted)
    if args.command == "client":
        if not args.ack_remote_storage:
            raise DomainError("REMOTE_STORAGE_ACK_REQUIRED", "Explicitly approve capture and memory storage at this remote authority", status=403)
        profile = validate_wire(RemoteClientSettings, decode_json(private_read(args.profile_file, 262144)))
        return await asyncio.to_thread(configure_remote_client, args.config, profile, ca_source=args.ca_file)
    if args.command == "init":
        from .initialization import initialize_deployment

        plan = await init_judge_plan(args)
        result = await initialize_deployment(
            config_path=args.config,
            realm=args.realm,
            mode=args.mode,
            capability=args.capability,
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
        return {**result, "judge": await apply_init_judge(args, result, plan)}
    if args.command == "migrate":
        from .ops import migrate_authority

        if args.upgrade_config:
            original = private_read(args.config, 262144)
            settings = prepare_settings_upgrade(original)
            return await migrate_authority(
                settings,
                token_path(args),
                args.confirm_deployment,
                config_path=args.config,
                original_config=original,
                retire_model_approval_intent=args.retire_model_approval_intent,
            )
        settings = load_settings(args.config)
        return await migrate_authority(
            settings,
            token_path(args),
            args.confirm_deployment,
            retire_model_approval_intent=args.retire_model_approval_intent,
        )
    if args.command == "service":
        from .service import load_control_settings

        settings = load_control_settings(args.config)
    else:
        settings = load_connection_settings(args.config)
    if args.command == "service":
        from .service import (
            install_service,
            service_status,
            start_service,
            stop_service,
            uninstall_service,
        )

        if args.service_action == "install":
            return await asyncio.to_thread(install_service, settings, args.config)
        action = {"start": start_service, "stop": stop_service, "status": service_status,
                  "uninstall": uninstall_service}[args.service_action]
        return await asyncio.to_thread(action, settings)
    if args.command == "client-run":
        from .recovery import run_client_recovery

        if not isinstance(settings, RemoteClientSettings):
            raise DomainError("CLIENT_PROFILE_REQUIRED", "PC recovery requires a remote client profile", status=422)
        await run_client_recovery(settings)
        return None
    if args.command in {"backup", "restore", "restore-recover"}:
        if not isinstance(settings, Settings):
            raise DomainError("REMOTE_COMMAND_UNSUPPORTED", "This operation requires a server-only authority configuration", status=403)
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
    if args.command in {"serve", "service-run"}:
        if not isinstance(settings, Settings):
            raise DomainError("REMOTE_COMMAND_UNSUPPORTED", "This operation requires a server-only authority configuration", status=403)
        import uvicorn

        from .edge import create_app

        if args.command == "service-run":
            from .service import require_service_enabled

            require_service_enabled(settings)
        app = create_app(settings)
        bind_host = "0.0.0.0" if args.command == "serve" and app.ingress is not None and app.ingress.tls_proxy == "private" else "127.0.0.1"
        config = uvicorn.Config(app, host=bind_host, port=settings.port, access_log=False, log_level="warning", timeout_graceful_shutdown=150, proxy_headers=False)
        server = uvicorn.Server(config)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            try:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.bind((bind_host, settings.port))
                listener.listen(config.backlog)
                listener.setblocking(False)
            except OSError as error:
                raise DomainError(
                    "SERVICE_BIND_FAILED", f"The configured service address cannot be bound (errno {error.errno})",
                    status=503, effect=EffectState.NOT_STARTED,
                ) from None
            await server.serve(sockets=[listener])
        if args.command == "service-run":
            try:
                require_service_enabled(settings)
            except DomainError as error:
                if error.code != "SERVICE_STOPPED":
                    raise
            else:
                raise DomainError("SERVICE_UNAVAILABLE",
                    "The managed authority exited before an explicit service stop", status=503)
        return None
    if args.command == "stdio":
        from .stdio import RelayEndpoint, run_stdio

        endpoint = RelayEndpoint(
            base_url=settings.base_url, state_dir=settings.state_dir, deployment_id=settings.deployment_id,
            max_http_body_bytes=settings.max_http_body_bytes,
            max_mcp_response_bytes=settings.max_mcp_response_bytes, remote_settings=settings,
        ) if isinstance(settings, RemoteClientSettings) else settings
        await run_stdio(endpoint, token_path(args))
        return None
    if args.command in {"context", "record", "feedback", "capture", "inspect", "correct"}:
        client = client_from_settings(settings, token_path(args))
        if args.command == "context":
            command = ContextCommand(
                binding_id=args.binding,
                query=text_file(args.query_file).strip(),
                query_expansions=json_array_file(args.expansions_file) if args.expansions_file else (),
                admission_id=args.admission_id,
                relevance=json_array_file(args.relevance_file) if args.relevance_file else None,
                paths=tuple(args.path) if args.path is not None else None,
                purpose=args.purpose,
                host=args.host,
                snapshot=args.snapshot,
                causal_operation=args.causal_operation,
                max_bytes=args.max_bytes,
                limit=args.limit,
            )
        elif args.command == "record":
            command = record_input(args)
        elif args.command == "feedback":
            command = FeedbackCommand(binding_id=args.binding, idempotency_key=args.key, target_ref=args.ref, kind=args.kind, body=text_file(args.body_file) if args.body_file else None)
        elif args.command == "inspect":
            return await client.call("/api/inspect", {
                "binding_id": args.binding, "ref": args.ref, "snapshot": args.snapshot,
                "byte_start": args.byte_start, "max_bytes": args.max_bytes, "claim_ids": args.claim_id,
                "rejection_cursor": args.rejection_cursor,
            })
        else:
            command = validate_wire(CaptureCommand, json_file(args.envelope_file))
            if args.command == "correct":
                return await client.call("/api/correct", {"target_ref": args.ref, "source": command.model_dump(mode="json")})
        return await client.call("/api/" + args.command, command.model_dump(mode="json"))
    if isinstance(settings, RemoteClientSettings):
        if args.command == "host-install":
            return await _install_remote_host(args, settings)
        if args.command == "doctor":
            from .readiness import ensure_remote_ready
            from .service import service_status

            return {
                "connection": await asyncio.to_thread(ensure_remote_ready, settings),
                "authentication_checked": False,
                "client_service": await asyncio.to_thread(service_status, settings),
                "native_memory": native_observation,
            }
        raise DomainError("REMOTE_COMMAND_UNSUPPORTED", "This operation requires a server-only authority configuration", status=403)
    async with authority(args) as (settings, store, actor):
        if args.command == "cloud":
            from .ingress import INGRESS_MAX_BYTES, CloudIngressProfile, configure_ingress

            if actor.role != Role.OPERATOR:
                raise DomainError("ROLE_DENIED", "Only the server operator can configure public ingress", status=403)
            if not args.ack_remote_storage:
                raise DomainError("REMOTE_STORAGE_ACK_REQUIRED", "Explicitly approve this authority serving authorized remote clients", status=403)
            profile = validate_wire(CloudIngressProfile, decode_json(private_read(args.ingress_file, INGRESS_MAX_BYTES)))
            if profile.oauth is not None:
                for mapping in profile.oauth.mappings:
                    await store.authenticate_external(
                        mapping.credential_id, mapping.generation, roles=(Role.AGENT, Role.PRODUCER),
                    )
            published = False
            try:
                async with store.operator_authority(actor):
                    try:
                        path = configure_ingress(settings, profile)
                    except OSError:
                        raise DomainError(
                            "INGRESS_CONFIG_INVALID",
                            "Ingress publication completion is unconfirmed; inspect the current policy before explicitly retrying",
                            status=503, effect=EffectState.UNKNOWN,
                        ) from None
                    published = True
            except DomainError as error:
                if published:
                    error.effect = EffectState.COMMITTED
                raise
            except OSError:
                raise DomainError(
                    "DATABASE_UNAVAILABLE",
                    "Authority completion is unconfirmed; inspect the published ingress policy before explicitly retrying",
                    status=503, effect=EffectState.COMMITTED if published else EffectState.UNKNOWN,
                ) from None
            return {
                "ingress_file": str(path), "public_origin": profile.public_origin,
                "auth_mode": profile.auth_mode, "tls_proxy": profile.tls_proxy,
                "deployment_id": settings.deployment_id, "realm": settings.realm,
                "activation": "next_service_start",
            }
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
                result = binding.model_dump(mode="json")
                try:
                    judge = await grant_new_binding(settings, store, actor, binding.id)
                except DomainError as error:
                    error.effect = EffectState.COMMITTED
                    raise
                if judge is not None:
                    result["judge"] = judge
                return result
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
        if args.command == "judge":
            if actor.role != Role.OPERATOR:
                raise DomainError("ROLE_DENIED", "Only the operator can inspect or choose the judge provider", status=403)
            return await execute_judge(args, settings, store, actor)
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
        if args.command == "stats":
            return await store.stats(actor, resolve_binding(actor, args.binding), args.snapshot)
        if args.command == "doctor":
            projects = await store.list_bindings(actor)
            judge_view = describe(settings, load_state(settings), operator=True)
            return {
                "deployment_id": settings.deployment_id,
                "realm": settings.realm,
                "mode": settings.mode,
                "capability": settings.capability,
                "memory_judgment": judge_view["source_judgment"],
                "judge": judge_view,
                "recall": "candidate_manifest_then_explicit_relevance",
                "projects": len(projects),
                "journal": store.journal.verify(),
                "freshness": "local_chain_only_not_external_latest_proof",
                "cleanup": "pending_work_only",
                "host_automatic_calls": "require_opt_in_adapter",
                "human_presence": "not_proven_by_local_bearer",
                "native_memory": native_observation,
            }
        if args.command == "await":
            binding = resolve_binding(actor, args.binding)
            deadline = time.monotonic() + args.deadline
            while time.monotonic() < deadline:
                operation = await store.operation(actor, binding, args.operation)
                if operation.state in {"captured", "selection_recorded", "candidate_ready", "semantic_ready", "blocked", "failed", "retracted"}:
                    return operation.model_dump(mode="json")
                await asyncio.sleep(0.25)
            raise DomainError("OPERATION_PENDING", "The durable operation has not reached a terminal state")
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


class _OperationsParser(argparse.ArgumentParser):
    def parse_args(self, args=None, namespace=None):
        parsed = super().parse_args(args, namespace)
        if parsed.command in {"backup", "restore", "restore-recover"} and parsed.runtime == "local":
            missing = [flag for flag in ("pg_dump_binary", "pg_restore_binary", "psql_binary")
                if getattr(parsed, flag) is None]
            if missing:
                self.error("local runtime requires " + ", ".join("--" + flag.replace("_", "-") for flag in missing)
                    + " with explicit absolute executable paths")
        return parsed


def parser() -> argparse.ArgumentParser:
    root = _OperationsParser(prog="agents-memory", description="Local-first shared memory authority; no implicit cloud or auto-approval")
    root.add_argument("--version", action="version", version="agents-memory 0.1.0")
    root.add_argument("--config", type=Path, default=Path.home() / ".config/agents-memory/personal.json")
    root.add_argument("--token-file", type=Path)
    commands = root.add_subparsers(dest="command", required=True)
    hook = commands.add_parser("host-hook")
    hook.add_argument("--receipt", type=Path, required=True)
    hook.add_argument("--envelope", action="store_true")
    relay = commands.add_parser("host-stdio")
    relay.add_argument("--receipt", type=Path, required=True)
    native = commands.add_parser("native-status", help="Read native activation and memory metadata; never change trust/settings or connect to the memory DB")
    native.add_argument("--project", type=Path, required=True)
    native.add_argument("--host", choices=("claude", "codex", "omp"), required=True)
    native.add_argument("--codex-executable", type=Path, help="Opt into bounded config/read and hooks/list over this explicit Codex executable")
    install = commands.add_parser("host-install")
    install.add_argument("--project", type=Path, required=True)
    install.add_argument("--binding", required=True)
    install.add_argument("--host", choices=("claude", "codex", "omp"), required=True)
    install.add_argument("--agent-token-file", type=Path, required=True)
    install.add_argument("--producer-token-file", type=Path, required=True)
    install.add_argument("--strict", action="store_true", help="Require supported native protection; Codex and OMP refuse installation, never downgrade")
    install.add_argument("--prompt-recall", action="store_true", help="Opt into bounded candidate retrieval before each native prompt")
    install.add_argument("--ack-remote-storage", action="store_true", help="Approve native capture storage at the explicit remote authority; does not enable Jev")
    uninstall = commands.add_parser("host-uninstall")
    uninstall.add_argument("--project", type=Path, required=True)
    uninstall.add_argument("--host", choices=("claude", "codex", "omp"), required=True)
    uninstall.add_argument("--project-deleted", action="store_true", help="Acknowledge the project was deleted; only native entries can be verified and removed")
    migration = commands.add_parser("migrate", help="Upgrade a stopped authority through the private operator connection")
    migration.add_argument("--confirm-deployment", required=True)
    migration.add_argument("--upgrade-config", action="store_true",
                           help="Retain the original private config and cut over to common caller judgment")
    migration.add_argument(
        "--retire-model-approval-intent",
        metavar="SHA256",
        help="Preserve and safely retire the exact pending historical approval without enabling models",
    )
    init = commands.add_parser("init")
    init.add_argument("--deployment-id", required=True)
    init.add_argument("--realm", required=True)
    init.add_argument("--mode", choices=("personal", "company"), required=True)
    init.add_argument("--capability", choices=("agent_judged",), default="agent_judged")
    init.add_argument("--dsn-file", type=Path, required=True)
    init.add_argument("--migrator-dsn-file", type=Path, required=True)
    init.add_argument("--state-dir", type=Path, required=True)
    init.add_argument("--journal-dir", type=Path, required=True)
    init.add_argument("--owner-id", required=True)
    init.add_argument("--operator-token-out", type=Path)
    init.add_argument("--port", type=int, default=8768)
    init.add_argument("--resume", action="store_true", help="Resume only an authenticated matching initialization intent")
    init.add_argument("--judge", choices=("agent", "jev"),
                      help="Source judge provider; an interactive terminal asks when omitted, otherwise agent")
    init.add_argument("--jev-key-file", type=Path, help="Jev API key file for --judge jev; read once into private state")
    init.add_argument("--jev-policy", choices=("allow", "deny"),
                      help="Independent Jev egress policy; denied unless explicitly allowed")
    init.add_argument("--ack-jev-egress", action="store_true",
                      help="Acknowledge approved source transfer to api.typesafe.ai in the US")
    for action in ("backup", "restore", "restore-recover"):
        operation = commands.add_parser(action)
        operation.add_argument("--age-binary", type=Path, required=True)
        operation.add_argument("--runtime", choices=("local", "docker"), default="local")
        operation.add_argument("--pg-dump-binary", help="Required absolute executable path for local runtime; Docker defaults to container pg_dump")
        operation.add_argument("--pg-restore-binary", help="Required absolute executable path for local runtime; Docker defaults to container pg_restore")
        operation.add_argument("--psql-binary", help="Required absolute executable path for local runtime; Docker defaults to container psql")
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
    commands.add_parser("service-run", help="Internal entrypoint for the owned login service")
    commands.add_parser("client-run", help="Run the PC-owned remote capture recovery loop")
    client = commands.add_parser("client").add_subparsers(dest="client_action", required=True)
    configure = client.add_parser("configure")
    configure.add_argument("--profile-file", type=Path, required=True)
    configure.add_argument("--ca-file", type=Path)
    configure.add_argument("--ack-remote-storage", action="store_true")
    cloud = commands.add_parser("cloud").add_subparsers(dest="cloud_action", required=True)
    ingress = cloud.add_parser("configure")
    ingress.add_argument("--ingress-file", type=Path, required=True)
    ingress.add_argument("--ack-remote-storage", action="store_true")
    service = commands.add_parser("service", help="Manage the owned macOS login service without needing a live DB").add_subparsers(
        dest="service_action", required=True)
    for action in ("install", "start", "stop", "status", "uninstall"):
        service.add_parser(action)
    commands.add_parser("stdio")
    doctor = commands.add_parser("doctor")
    doctor.add_argument("--project", type=Path, help="Include read-only native memory coexistence metadata for this explicit project")
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
    judge = commands.add_parser("judge", help="Inspect or choose who judges captured sources").add_subparsers(
        dest="judge_action", required=True)
    judge.add_parser("status")
    policy = judge.add_parser("policy", help="Grant or revoke independent Jev source-egress permission")
    policy.add_argument("policy", choices=("allow-jev", "deny-jev"))
    policy.add_argument("--ack-egress", action="store_true",
                        help="Acknowledge approved source transfer to api.typesafe.ai in the US")
    choose = judge.add_parser("set")
    choose.add_argument("provider", choices=("agent", "jev"))
    choose.add_argument("--key-file", type=Path, help="Jev API key file read once; the service keeps a private 0600 copy")
    choose.add_argument("--prompt-key", action="store_true", help="Enter a new Jev API key without echo")
    choose.add_argument("--model", default=JEV_DEFAULT_MODEL, help="Pinned Jev model ID")
    choose.add_argument("--forget-key", action="store_true", help="With agent: delete the stored Jev API key")
    credential = commands.add_parser("credential").add_subparsers(dest="credential_action", required=True)
    issue = credential.add_parser("issue")
    issue.add_argument("--role", choices=tuple(Role), required=True)
    issue.add_argument("--binding", action="append", required=True)
    issue.add_argument("--output", type=Path, required=True)
    revoke = credential.add_parser("revoke")
    revoke.add_argument("--credential-id", required=True)
    revoke.add_argument("--preview", action="store_true", help="Report body-free rule invalidation impact without revoking")
    revoke.add_argument("--ack-required-rules", action="store_true", help="Explicitly acknowledge affected mandatory rule invalidation")
    context = commands.add_parser("context")
    context.add_argument("--binding")
    context.add_argument("--query-file", type=Path)
    context.add_argument("--expansions-file", type=Path, help="Bounded JSON array of caller query expansions")
    context.add_argument("--admission-id", help="Saved admission from the candidate response")
    context.add_argument("--relevance-file", type=Path, help="Bounded JSON array covering every admitted candidate")
    context.add_argument("--path", action="append")
    context.add_argument("--purpose", default="general")
    context.add_argument("--host", choices=("generic", "claude", "codex", "omp", "agent-flow"), default="generic")
    context.add_argument("--snapshot")
    context.add_argument("--causal-operation")
    context.add_argument("--max-bytes", type=int, default=2400)
    context.add_argument("--limit", type=int, default=3)
    record = commands.add_parser("record")
    record.add_argument("--judgment-file", type=Path, help="Complete strict memory_record JSON command")
    record.add_argument("--binding", default=argparse.SUPPRESS)
    record.add_argument("--body-file", type=Path, default=argparse.SUPPRESS)
    record.add_argument("--kind", choices=("note", "rule_candidate"), default=argparse.SUPPRESS)
    record.add_argument("--key", default=argparse.SUPPRESS)
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
    inspect.add_argument("--byte-start", type=int, default=0, help="Source byte cursor, pending page cursor, or next_byte for claim/selection/judgment JSON windows")
    inspect.add_argument("--max-bytes", type=int, default=4096, help="Byte budget (1–4096); stored JSON windows must be reassembled before decoding")
    inspect.add_argument("--claim-id", action="append", help="Select claims only for ref=judgment admission, without byte-window arguments")
    inspect.add_argument("--rejection-cursor", help="Continue rejection history only for a source ref")
    for name in ("capture", "correct"):
        capture = commands.add_parser(name)
        capture.add_argument("--envelope-file", type=Path, required=True)
        if name == "correct":
            capture.add_argument("--ref", required=True)
    awaiter = commands.add_parser("await")
    awaiter.add_argument("--binding")
    awaiter.add_argument("--operation", required=True)
    awaiter.add_argument("--deadline", type=float, default=180)
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
        age_binary=args.age_binary, mode=args.runtime,
        pg_dump_binary=args.pg_dump_binary if args.runtime == "local" or args.pg_dump_binary is not None else "pg_dump",
        pg_restore_binary=args.pg_restore_binary if args.runtime == "local" or args.pg_restore_binary is not None else "pg_restore",
        psql_binary=args.psql_binary if args.runtime == "local" or args.psql_binary is not None else "psql", docker_binary=args.docker_binary,
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
