from __future__ import annotations

import json
import os
import shlex
import subprocess
import tomllib
from pathlib import Path

import pytest

from agents_memory import hosts
from agents_memory.config import Settings
from agents_memory.connection import RemoteClientSettings
from agents_memory.domain import CaptureCommand, DomainError
from agents_memory.private_io import private_write
from agents_memory.spool import ProducerSpool


@pytest.fixture
def isolated_installation(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    home = root / "home"
    home.mkdir(mode=0o700)
    native = home / "private claude"
    native.mkdir(mode=0o700)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(native))
    monkeypatch.setenv("CODEX_HOME", str(home / "codex"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    project = root / "consumer project"
    project.mkdir(mode=0o700)
    state = root / "state"
    state.mkdir(mode=0o700)
    agent, producer = root / "agent.token", root / "producer.token"
    private_write(agent, "synthetic-isolation-agent\n")
    private_write(producer, "synthetic-isolation-producer\n")
    settings = Settings(
        deployment_id="import-isolation", realm="personal", mode="personal",
        database_dsn="postgresql://unused", state_dir=state,
        journal_dir=root / "journal", spool_limit_bytes=65536,
    )
    return project, settings, agent, producer, native


def generated_commands(project: Path, native: Path, host: str) -> tuple[list[str], tuple[list[str], ...]]:
    if host == "claude":
        server = json.loads((native / ".claude.json").read_text())["projects"][str(project)]["mcpServers"][hosts.SERVER_NAME]
    elif host == "codex":
        server = tomllib.loads((project / ".codex/config.toml").read_text())["mcp_servers"][hosts.SERVER_NAME]
    else:
        server = json.loads((project / ".omp/mcp.json").read_text())["mcpServers"][hosts.SERVER_NAME]
    mcp = [server["command"], *server["args"]]
    if host == "omp":
        template = (project / ".omp/extensions/agents-memory.ts").read_text()
        declaration = next(line for line in template.splitlines() if line.startswith("const hookArgv: string[] = "))
        commands = [json.loads(declaration.removeprefix("const hookArgv: string[] = ").removesuffix(";"))]
    else:
        relative = ".claude/settings.local.json" if host == "claude" else ".codex/hooks.json"
        groups = json.loads((project / relative).read_text())["hooks"]
        handlers = [group["hooks"][0] for values in groups.values() for group in values]
        commands = [
            [handler["command"], *handler["args"]] if host == "claude" else shlex.split(handler["command"])
            for handler in handlers
        ]
    return mcp, tuple(list(argv) for argv in dict.fromkeys(tuple(command) for command in commands))


@pytest.mark.parametrize("host", ["claude", "codex", "omp"])
@pytest.mark.parametrize("location", ["cwd", "pythonpath"])
@pytest.mark.parametrize("shadow", ["module", "package", "stdlib"])
def test_installed_generated_commands_ignore_project_and_pythonpath_imports(
    isolated_installation, monkeypatch, host, location, shadow,
):
    project, settings, agent, producer, native = isolated_installation
    hosts.install_host(settings, project, "binding-one", host, agent, producer)
    mcp, hook_commands = generated_commands(project, native, host)

    inherited = project.parent / "inherited imports"
    inherited.mkdir()
    shadow_root = project if location == "cwd" else inherited
    sentinel = project.parent / "malicious-import-executed"
    payload = f"open({str(sentinel)!r}, 'w').write('executed')\nraise RuntimeError('untrusted import')\n"
    if shadow == "package":
        package = shadow_root / "agents_memory"
        package.mkdir()
        (package / "__init__.py").write_text(payload)
        (package / "cli.py").write_text(payload)
    else:
        (shadow_root / ("agents_memory.py" if shadow == "module" else "json.py")).write_text(payload)
    monkeypatch.setenv("PYTHONPATH", str(inherited))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(project.parent / "wrong native config"))
    environment = os.environ.copy()

    stdio = subprocess.run(
        mcp, cwd=project, env=environment, input=b"not-json\n",
        capture_output=True, timeout=15,
    )
    assert not sentinel.exists()
    assert stdio.returncode == 0, stdio.stderr
    assert stdio.stderr == b""
    rejected = json.loads(stdio.stdout)
    assert rejected["error"]["code"] == -32700
    assert rejected["error"]["data"]["effect"] == "not_started"

    event = {
        "hook_event_name": "ImportIsolationProbe", "event": "ImportIsolationProbe",
        "cwd": str(project), "session_id": "isolation-session", "agent_id": "main",
        "agent": {"kind": "main", "id": "main"}, "hook_instance_id": "isolation-hook",
    }
    for hook in hook_commands:
        result = subprocess.run(
            hook, cwd=project, env=environment, input=json.dumps(event).encode(),
            capture_output=True, timeout=15,
        )
        assert not sentinel.exists()
        assert result.returncode == 0, result.stderr
        assert result.stderr == b""
        output = json.loads(result.stdout)
        if host == "omp":
            assert output["host"] == host and output["code"] == "HOST_EVENT_UNSUPPORTED"
            assert output["provider_input_observed"] is False
            assert "warning" in output["stdout"]
        else:
            assert "systemMessage" in output


@pytest.mark.parametrize("host", ["claude", "codex", "omp"])
@pytest.mark.parametrize("remote", [False, True])
@pytest.mark.parametrize("deleted_project", [False, True])
def test_unisolated_v5_commands_require_owned_reinstall_without_losing_spool(
    isolated_installation, monkeypatch, host, remote, deleted_project,
):
    project, settings, agent, producer, _native = isolated_installation
    if remote:
        settings = RemoteClientSettings(
            deployment_id=settings.deployment_id, realm=settings.realm, mode=settings.mode,
            base_url="https://memory.invalid", state_dir=settings.state_dir,
            auth_mode="bearer", spool_limit_bytes=settings.spool_limit_bytes,
        )
    command = hosts._command

    def historical_command(receipt, verb, selected_host):
        argv = command(receipt, verb, selected_host)
        argv.remove("-I")
        return argv

    with monkeypatch.context() as historical:
        historical.setattr(hosts, "_command", historical_command)
        receipt_path = Path(hosts.install_host(settings, project, "binding-one", host, agent, producer)["receipt"])
    receipt = hosts.load_receipt(receipt_path)
    receipt["adapter_version"] = 5
    hosts._write_receipt(receipt_path, receipt)
    spool_path = Path(receipt["runtime_dir"]) / "capture.sqlite3"
    spool = ProducerSpool(spool_path, settings.deployment_id, "binding-one", settings.spool_limit_bytes)
    try:
        spool.enqueue(CaptureCommand(
            binding_id="binding-one", idempotency_key="pending-before-upgrade",
            origin_key="pending-before-upgrade", speaker="human", body="Synthetic pending capture survives owned removal.",
        ))
    finally:
        spool.close()
    before = {
        path: path.read_bytes() for path in (
            receipt_path, *(hosts._owned_path(project, entry["path"]) for entry in receipt["ownership"]),
        )
    }
    with pytest.raises(DomainError) as denied:
        hosts.load_receipt(receipt_path)
    assert denied.value.code == "HOST_RECEIPT_INVALID"
    with pytest.raises(DomainError) as denied:
        hosts.load_receipt(receipt_path, allow_legacy=True)
    assert denied.value.code == "HOST_LEGACY_REINSTALL_REQUIRED"
    with pytest.raises(DomainError) as denied:
        hosts.install_host(settings, project, "binding-one", host, agent, producer)
    assert denied.value.code == "HOST_LEGACY_REINSTALL_REQUIRED"
    cleanup = hosts.load_receipt(receipt_path, allow_legacy=True, active=False)
    assert cleanup["adapter_version"] == 5
    assert hosts.receipt_connection(cleanup) == (settings if remote else None)
    assert all(path.read_bytes() == raw for path, raw in before.items())

    if deleted_project:
        moved = project.with_name("temporarily absent project")
        project.rename(moved)
        try:
            native_removed = hosts.uninstall_host(settings, project, host, project_deleted=True)
            assert native_removed["state"] == "native_uninstalled"
            assert Path(native_removed["pending_spool_retained"]) == spool_path
            assert hosts.load_receipt(
                receipt_path, allow_legacy=True, active=False, allow_deleted_project=True,
            )["state"] == "native_removed"
        finally:
            moved.rename(project)
    removed = hosts.uninstall_host(settings, project, host)
    assert removed["state"] == "uninstalled"
    assert Path(removed["pending_spool_retained"]) == spool_path
    spool = ProducerSpool(spool_path, settings.deployment_id, "binding-one", settings.spool_limit_bytes)
    try:
        assert spool.status()["pending"] == 1
    finally:
        spool.close()
    hosts.install_host(settings, project, "binding-one", host, agent, producer)
    replacement = hosts.load_receipt(receipt_path)
    assert replacement["adapter_version"] == hosts.ADAPTER_VERSION
    assert replacement["installation_id"] != receipt["installation_id"]
