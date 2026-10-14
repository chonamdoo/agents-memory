from __future__ import annotations

import asyncio
import json
import threading

import pytest
from pydantic import ValidationError
from test_edge_boundaries import selection_arguments
from test_store_authority import TOKEN
from test_store_authority import authority as authority

from agents_memory import cli
from agents_memory.client import LocalClient
from agents_memory.config import Settings
from agents_memory.domain import CaptureCommand, DomainError
from agents_memory.spool import ProducerSpool


def deployment(tmp_path):
    settings = Settings(
        deployment_id="deployment-001", realm="personal", mode="personal",
        database_dsn="postgresql://not-used", state_dir=tmp_path / "state",
        journal_dir=tmp_path / "journal", spool_limit_bytes=65536,
    )
    config = tmp_path / "deployment.json"
    config.write_text(settings.model_dump_json())
    config.chmod(0o600)
    token = tmp_path / "producer.token"
    token.write_text("test-only-producer-credential\n")
    token.chmod(0o600)
    return settings, config, token


def test_cli_flush_creates_uses_and_closes_sqlite_in_the_same_offload_thread(tmp_path, monkeypatch):
    _, config, token = deployment(tmp_path)
    outbox = tmp_path / "capture.sqlite3"
    envelope = tmp_path / "envelope.json"
    key = "k" * 512
    origin = "o" * 512
    envelope.write_text(json.dumps({
        "binding_id": "binding-001", "idempotency_key": key, "origin_key": origin,
        "body": "An unchanged source-schema accepted capture.", "speaker": "human",
    }))
    base = ["--config", str(config), "--token-file", str(token), "spool"]
    scope = ["--file", str(outbox), "--binding", "binding-001"]
    delivered, lifecycle = [], []
    caller = threading.get_ident()

    class ObservedSpool(ProducerSpool):
        def __init__(self, *args, **kwargs):
            lifecycle.append(("create", threading.get_ident()))
            super().__init__(*args, **kwargs)

        def flush(self, *args, **kwargs):
            lifecycle.append(("flush", threading.get_ident()))
            return super().flush(*args, **kwargs)

        def close(self):
            lifecycle.append(("close", threading.get_ident()))
            super().close()

    def capture(self, path, payload):
        delivered.append((path, payload))
        return {"effect": "committed", "id": "operation-001"}

    async def exercise():
        accepted = await cli.execute(cli.parser().parse_args(base + ["enqueue"] + scope + ["--envelope-file", str(envelope)]))
        assert accepted["state"] == "durably_spooled"
        monkeypatch.setattr("agents_memory.spool.ProducerSpool", ObservedSpool)
        monkeypatch.setattr(LocalClient, "request", capture)
        result = await cli.execute(cli.parser().parse_args(base + ["flush"] + scope))
        assert result["committed"] == 1 and result["pending"] == 0
        assert [event for event, _ in lifecycle] == ["create", "flush", "close"]
        assert len({thread for _, thread in lifecycle}) == 1
        assert lifecycle[0][1] != caller
        replay = await cli.execute(cli.parser().parse_args(base + ["enqueue"] + scope + ["--envelope-file", str(envelope)]))
        assert replay == {"state": "committed", "replay": True, "operation_id": "operation-001"}

    asyncio.run(exercise())
    assert delivered[0][0] == "/api/capture"
    assert delivered[0][1]["idempotency_key"] == key
    assert delivered[0][1]["origin_key"] == origin


def test_cli_quarantine_inspect_retry_discard_without_exposing_source_body(tmp_path, monkeypatch):
    _, config, token = deployment(tmp_path)
    outbox = tmp_path / "capture.sqlite3"
    envelope = tmp_path / "envelope.json"
    envelope.write_text(json.dumps({
        "binding_id": "binding-001", "idempotency_key": "capture-001", "origin_key": "origin-001",
        "body": "Private captured evidence not an operator listing.", "speaker": "human",
    }))
    base = ["--config", str(config), "--token-file", str(token), "spool"]
    scope = ["--file", str(outbox), "--binding", "binding-001"]

    def reject(self, path, payload):
        raise DomainError("ORIGIN_CONFLICT", "Sanitized rejection", status=409)

    monkeypatch.setattr(LocalClient, "request", reject)

    async def exercise():
        await cli.execute(cli.parser().parse_args(base + ["enqueue"] + scope + ["--envelope-file", str(envelope)]))
        result = await cli.execute(cli.parser().parse_args(base + ["flush"] + scope))
        assert result["quarantined"] == 1
        inspected = await cli.execute(cli.parser().parse_args(base + ["inspect"] + scope + ["--key", "capture-001"]))
        assert inspected["entries"][0]["code"] == "ORIGIN_CONFLICT"
        assert "Private captured evidence" not in json.dumps(inspected)
        retry = await cli.execute(cli.parser().parse_args(base + ["retry"] + scope + ["--key", "capture-001"]))
        assert retry["pending"] == 1 and retry["quarantined"] == 0
        await cli.execute(cli.parser().parse_args(base + ["flush"] + scope))
        discarded = await cli.execute(cli.parser().parse_args(base + ["discard"] + scope + ["--key", "capture-001"]))
        assert discarded["bytes"] == 0 and discarded["gaps"]["SPOOL_DISCARDED"] == 1

    asyncio.run(exercise())




@pytest.mark.parametrize("command", ["host-stdio", "host-hook"])
def test_cli_incomplete_receipt_has_a_public_failure_not_key_error(tmp_path, monkeypatch, command):
    from io import BytesIO
    from types import SimpleNamespace

    from agents_memory import hosts
    from agents_memory.domain import canonical_digest

    receipt = tmp_path / "claude.json"
    document = {"adapter_version": hosts.ADAPTER_VERSION, "host": "claude"}
    document["ownership_digest"] = canonical_digest(document)
    receipt.write_text(json.dumps(document))
    args = cli.parser().parse_args([command, "--receipt", str(receipt)] + (["--envelope"] if command == "host-hook" else []))
    if command == "host-hook":
        monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(buffer=BytesIO(b'{"hook_event_name":"PreToolUse"}')))
        result = asyncio.run(cli.execute(args))
        assert result["state"] == "blocked" and result["code"] == "HOST_RECEIPT_UNAVAILABLE"
    else:
        with pytest.raises(DomainError) as caught:
            asyncio.run(cli.execute(args))
        assert caught.value.code == "HOST_RECEIPT_INVALID"


@pytest.mark.parametrize("changes", [{"injected": "yes"}, {"injected": 1}, {"unexpected_authority": True}])
def test_cli_json_capture_rejects_coercions_before_any_capture_acceptance(tmp_path, changes):
    settings, config, _ = deployment(tmp_path)
    outbox = tmp_path / "capture.sqlite3"
    envelope = tmp_path / "envelope.json"
    envelope.write_text(json.dumps({
        "binding_id": "binding-001", "idempotency_key": "capture-001", "origin_key": "origin-001",
        "body": "Unchanged valid evidence.", "speaker": "human", **changes,
    }))
    args = cli.parser().parse_args([
        "--config", str(config), "spool", "enqueue", "--file", str(outbox),
        "--binding", "binding-001", "--envelope-file", str(envelope),
    ])
    with pytest.raises(ValidationError):
        asyncio.run(cli.execute(args))
    spool = ProducerSpool(outbox, settings.deployment_id, "binding-001", settings.spool_limit_bytes)
    try:
        assert spool.status()["pending"] == spool.status()["quarantined"] == 0
    finally:
        spool.close()


@pytest.mark.parametrize("override", (
    ["--binding", "binding-override"], ["--key", "changed-key"],
    ["--kind", "note"], ["--body-file", "unread-body.txt"],
))
def test_cli_frozen_selection_rejects_every_mixed_override_before_read_or_dispatch(tmp_path, override):
    _, config, _ = deployment(tmp_path)
    args = cli.parser().parse_args([
        "--config", str(config), "record", "--judgment-file", str(tmp_path / "unread-selection.json"),
        *override,
    ])
    with pytest.raises(DomainError) as caught:
        asyncio.run(cli.execute(args))
    assert caught.value.code == "INPUT_INVALID"
    assert caught.value.effect == "not_started"


@pytest.mark.parametrize("change", (
    {"source_revision": "1"}, {"byte_end": 4097}, {"policy_epoch": False},
    {"label": "approve"}, {"unexpected": "authority"},
    {"label": "review", "extraction": {
        "claims": [], "individual_qualifications": [], "shared_qualifications": [],
        "validities": [], "unused_span_ids": [],
    }},
))
def test_cli_selection_file_rejects_invalid_judgments_before_http_dispatch(tmp_path, change):
    _, config, _ = deployment(tmp_path)
    selection = tmp_path / "selection.json"
    selection.write_text(json.dumps({**selection_arguments("binding-001", "source-001"),
                                    "reason": "Inspected original evidence.", **change}))
    args = cli.parser().parse_args(["--config", str(config), "record", "--judgment-file", str(selection)])
    with pytest.raises(ValidationError):
        asyncio.run(cli.execute(args))


@pytest.mark.parametrize("malformation", ("duplicate", "nonfinite", "deep"))
def test_cli_selection_file_rejects_ambiguous_or_unbounded_json(tmp_path, malformation):
    _, config, _ = deployment(tmp_path)
    document = {**selection_arguments("binding-001", "source-001"), "reason": "Inspected original evidence."}
    raw = json.dumps(document)
    if malformation == "duplicate":
        raw = raw.replace('"source_revision": 1', '"source_revision": 1, "source_revision": 2')
    elif malformation == "nonfinite":
        raw = '{"unbounded":1e999,' + raw[1:]
    else:
        nested = 0
        for _ in range(25):
            nested = [nested]
        document["extraction"] = {"nested": nested}
        raw = json.dumps(document)
    selection = tmp_path / "selection.json"
    selection.write_text(raw)
    args = cli.parser().parse_args(["--config", str(config), "record", "--judgment-file", str(selection)])
    with pytest.raises(ValueError):
        asyncio.run(cli.execute(args))


def cli_files(authority, tmp_path):
    config = tmp_path / "deployment.json"
    config.write_text(authority.store.settings.model_dump_json())
    config.chmod(0o600)
    token = tmp_path / "operator.token"
    token.write_text(TOKEN)
    token.chmod(0o600)
    return ["--config", str(config), "--token-file", str(token)]


@pytest.mark.parametrize("arguments", (
    ["model", "fetch"], ["model", "approve"], ["selection-policy", "approve"],
    ["context", "--mode", "reflect"], ["record", "--selection-file", "obsolete.json"],
    ["retry", "--job", "job-old"], ["index-recover", "--claim", "claim-old"],
    ["source-reprocess", "--ref", "source-old"],
    ["index-status", "--binding", "binding-old"],
))
def test_cli_removed_model_and_policy_commands_are_not_compatibility_aliases(arguments):
    with pytest.raises(SystemExit) as denied:
        cli.parser().parse_args(arguments)
    assert denied.value.code == 2




@pytest.mark.asyncio
@pytest.mark.parametrize("decisions", (
    [{"claim_id": "claim-001", "relevant": "yes", "reason": "Not a boolean."}],
    [{"claim_id": "claim-001", "relevant": True, "reason": "First."},
     {"claim_id": "claim-001", "relevant": False, "reason": "Repeated."}],
))
async def test_cli_context_refuses_invalid_relevance_before_dispatch(tmp_path, monkeypatch, decisions):
    _, config, _ = deployment(tmp_path)
    query, relevance = tmp_path / "query.txt", tmp_path / "relevance.json"
    query.write_text("CacheKey")
    relevance.write_text(json.dumps(decisions))

    async def unexpected(*args):
        pytest.fail("Invalid relevance reached HTTP dispatch")

    monkeypatch.setattr(LocalClient, "call", unexpected)
    with pytest.raises(ValidationError):
        await cli.execute(cli.parser().parse_args([
            "--config", str(config), "context", "--query-file", str(query),
            "--admission-id", "admission-001", "--relevance-file", str(relevance),
        ]))


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ("captured", "selection_recorded", "candidate_ready"))
async def test_cli_await_recognizes_actual_capture_and_selection_terminals(authority, tmp_path, terminal):
    store, actor, binding = authority.store, authority.actor, authority.binding_id
    base = cli_files(authority, tmp_path)
    captured = await store.capture(actor, CaptureCommand(
        binding_id=binding, idempotency_key="terminal-source", origin_key="terminal-source",
        body="CacheKey uses SQLite.", speaker="human",
    ))
    operation = captured
    if terminal != "captured":
        window = await store.inspect(actor, binding, captured.source_id)
        document = {
            **selection_arguments(binding, captured.source_id),
            "reason": "Inspected exact original evidence for memory selection.",
            **{name: window[name] for name in (
                "admission_id", "source_revision", "binding_revision", "byte_start", "byte_end",
                "window_digest", "policy_revision", "policy_epoch",
            )},
        }
        if terminal == "candidate_ready":
            document["extraction"] = {
                "claims": [{
                    "assertion_id": "a0000", "assertion_span_id": window["span_inventory"][0]["span_id"],
                    "statement": "CacheKey uses SQLite.", "kind": "fact", "subject": "CacheKey",
                    "predicate": "uses", "object": "SQLite", "polarity": "positive",
                    "modality": "asserted", "entities": ["CacheKey", "SQLite"],
                }],
                "individual_qualifications": [], "shared_qualifications": [],
                "validities": [], "unused_span_ids": [],
            }
        selection = tmp_path / "terminal-selection.json"
        selection.write_text(json.dumps(document))
        command = cli.record_input(cli.parser().parse_args(["record", "--judgment-file", str(selection)]))
        operation = await store.record(actor, command)
    result = await cli.execute(cli.parser().parse_args(base + [
        "await", "--binding", binding, "--operation", operation.id, "--deadline", "1",
    ]))
    assert result["state"] == terminal and result["effect"] == "committed"


def operation_arguments(command, root):
    arguments = [command, "--age-binary", "/opt/homebrew/bin/age"]
    if command == "backup":
        return arguments + ["--output", str(root / "backup.age"),
            "--recipients-file", str(root / "recipients.age")]
    arguments += ["--expected-head", "a" * 64, "--operator-out", str(root / "fresh-operator"),
        "--confirm-deployment", "deployment-001"]
    if command == "restore":
        arguments += ["--archive", str(root / "backup.age"), "--identity-file", str(root / "identity.age")]
    return arguments


@pytest.mark.parametrize("command", ["backup", "restore", "restore-recover"])
@pytest.mark.parametrize("missing", [None, "--pg-dump-binary", "--pg-restore-binary", "--psql-binary"])
def test_cli_local_operations_require_every_explicit_pg_binary(command, missing, tmp_path):
    arguments = operation_arguments(command, tmp_path)
    for flag in ("--pg-dump-binary", "--pg-restore-binary", "--psql-binary"):
        if missing is not None and flag != missing:
            arguments += [flag, "/explicit/not-invoked/pg-tool"]
    with pytest.raises(SystemExit) as rejected:
        cli.parser().parse_args(arguments)
    assert rejected.value.code == 2
    assert not (tmp_path / "backup.age").exists()
    assert not (tmp_path / "fresh-operator").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["backup", "restore", "restore-recover"])
@pytest.mark.parametrize("flag", ["--pg-dump-binary", "--pg-restore-binary", "--psql-binary"])
@pytest.mark.parametrize("invalid", ["bare", "relative", "missing", "nonexecutable"])
async def test_cli_local_invalid_pg_executables_leave_no_operational_effects(
        tmp_path, command, flag, invalid):
    from agents_memory.domain import EffectState

    settings, config, token = deployment(tmp_path)
    settings = settings.model_copy(update={"database_dsn": "postgresql://memory@127.0.0.1:5432/memory?schema=memory",
        "migrator_dsn": "postgresql://memory@127.0.0.1:5432/memory?schema=memory"})
    config.write_text(settings.model_dump_json())
    executable = tmp_path / "executable"
    executable.write_text("#!/bin/sh\nexit 99\n")
    executable.chmod(0o700)
    nonexecutable = tmp_path / "not-executable"
    nonexecutable.write_text("not executable")
    paths = {"bare": "pg_dump", "relative": "./pg_dump",
        "missing": str(tmp_path / "absent"), "nonexecutable": str(nonexecutable)}
    arguments = ["--config", str(config), "--token-file", str(token)] + operation_arguments(command, tmp_path)
    for selected in ("--pg-dump-binary", "--pg-restore-binary", "--psql-binary"):
        arguments += [selected, paths[invalid] if selected == flag else str(executable)]
    with pytest.raises(DomainError) as rejected:
        await cli.execute(cli.parser().parse_args(arguments))
    assert rejected.value.code == "BINARY_REQUIRED"
    assert rejected.value.effect == EffectState.NOT_STARTED
    assert not (tmp_path / "backup.age").exists()
    assert not (tmp_path / "fresh-operator").exists()
    assert not (settings.state_dir / "restore-barrier.json").exists()


def test_cli_selection_file_without_kind_is_not_reinterpreted_as_a_note(tmp_path):
    document = {**selection_arguments("binding-001", "source-001"), "reason": "Inspected original evidence."}
    document.pop("kind")
    selection = tmp_path / "selection.json"
    selection.write_text(json.dumps(document))
    with pytest.raises(ValidationError):
        cli.record_input(cli.parser().parse_args(["record", "--judgment-file", str(selection)]))
