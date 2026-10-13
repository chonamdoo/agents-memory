from __future__ import annotations

import asyncio
import json
import threading

import pytest

from agents_memory import cli
from agents_memory.client import LocalClient
from agents_memory.config import Settings
from agents_memory.domain import DomainError
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
    from pydantic import ValidationError

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
