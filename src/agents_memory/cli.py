from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import secrets
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from pydantic import ValidationError

from .client import LocalClient
from .config import Settings, load_settings, prepare_settings_upgrade, resolve_binding
from .domain import (
    BindingRelocation,
    CaptureCommand,
    ContextCommand,
    DomainError,
    FeedbackCommand,
    Role,
    RuleApproval,
    RuleProposal,
    RuleScope,
    Selector,
    approval_signing_payload,
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
        from .hosts import load_receipt
        from .stdio import RelayEndpoint, run_stdio

        receipt = load_receipt(args.receipt)
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
    settings = load_settings(args.config)
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
    if args.command == "stdio":
        from .stdio import run_stdio

        await run_stdio(settings, token_path(args))
        return None
    if args.command in {"context", "record", "feedback", "capture", "inspect", "correct"}:
        client = LocalClient(settings.base_url, token_path(args))
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
        if args.command == "stats":
            return await store.stats(actor, resolve_binding(actor, args.binding), args.snapshot)
        if args.command == "doctor":
            projects = await store.list_bindings(actor)
            return {
                "deployment_id": settings.deployment_id,
                "realm": settings.realm,
                "mode": settings.mode,
                "capability": settings.capability,
                "memory_judgment": "current_coding_agent",
                "recall": "candidate_manifest_then_explicit_relevance",
                "projects": len(projects),
                "journal": store.journal.verify(),
                "freshness": "local_chain_only_not_external_latest_proof",
                "cleanup": "pending_work_only",
                "host_automatic_calls": "require_opt_in_adapter",
                "human_presence": "not_proven_by_local_bearer",
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
    install = commands.add_parser("host-install")
    install.add_argument("--project", type=Path, required=True)
    install.add_argument("--binding", required=True)
    install.add_argument("--host", choices=("claude", "codex", "omp"), required=True)
    install.add_argument("--agent-token-file", type=Path, required=True)
    install.add_argument("--producer-token-file", type=Path, required=True)
    install.add_argument("--strict", action="store_true")
    install.add_argument("--prompt-recall", action="store_true", help="Opt into bounded candidate retrieval before each native prompt")
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
