from __future__ import annotations

import datetime
import hashlib
import json
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from test_service import native as native

from agents_memory import cli, hosts, service
from agents_memory.connection import RemoteClientSettings, load_remote_settings
from agents_memory.domain import CaptureCommand, DomainError, EffectState
from agents_memory.private_io import private_write
from agents_memory.spool import ProducerSpool


def ca_material(common_name: str) -> bytes:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC))
        .not_valid_after(datetime.datetime(2100, 1, 1, tzinfo=datetime.UTC))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return certificate.public_bytes(serialization.Encoding.PEM)


@pytest.fixture
def remote(tmp_path):
    state = tmp_path / "pc-state"
    state.mkdir(mode=0o700)
    ca = state / "remote-ca.pem"
    raw = ca_material("Synthetic remote control CA")
    private_write(ca, raw)
    profile = RemoteClientSettings(
        deployment_id="remote-control", realm="company", mode="company", auth_mode="bearer",
        base_url="https://memory.invalid", state_dir=state, ca_bundle=ca,
        ca_bundle_sha256=hashlib.sha256(raw).hexdigest(), spool_limit_bytes=65536,
    )
    source = tmp_path / "profile-input.json"
    private_write(source, profile.model_dump_json())
    return SimpleNamespace(profile=profile, source=source, config=tmp_path / "remote.json")


async def command(config: Path, *args: str) -> dict:
    result = await cli.execute(cli.parser().parse_args(["--config", str(config), *args]))
    assert isinstance(result, dict)
    return result


async def configure(remote) -> dict:
    return await command(
        remote.config, "client", "configure", "--profile-file", str(remote.source),
        "--ack-remote-storage",
    )


@pytest.mark.parametrize("change", [
    {"base_url": "https://other.invalid"},
    {"spool_limit_bytes": 131072},
])
async def test_remote_configure_never_replaces_a_different_existing_profile(remote, change):
    assert (await configure(remote))["replay"] is False
    original = remote.config.read_bytes()
    candidate = RemoteClientSettings.model_validate({**remote.profile.model_dump(), **change})
    private_write(remote.source, candidate.model_dump_json(), replace=True)

    with pytest.raises(DomainError) as denied:
        await configure(remote)

    assert denied.value.code == "CONFIG_EXISTS"
    assert denied.value.effect is EffectState.NOT_STARTED
    assert remote.config.read_bytes() == original
    assert remote.config.stat().st_mode & 0o077 == 0
    assert load_remote_settings(remote.config) == remote.profile
    assert not (remote.profile.state_dir / "service").exists()
    assert not (remote.profile.state_dir / "host-adapters").exists()


async def test_identical_configure_and_install_replay_preserve_durable_client_stop(native, remote):
    await configure(remote)
    installed = await command(remote.config, "service", "install")
    assert installed["component"] == "client" and installed["running"] is True
    stopped = await command(remote.config, "service", "stop")
    assert stopped["enabled"] is False and stopped["loaded"] is False
    receipt = remote.profile.state_dir / "service" / "receipt.json"
    original_receipt = receipt.read_bytes()
    original_config = remote.config.read_bytes()
    original_plist = Path(json.loads(original_receipt)["plist_path"]).read_bytes()
    native.calls.clear()

    assert (await configure(remote))["replay"] is True
    assert native.calls == []
    assert await command(remote.config, "service", "install") == stopped
    assert all(call[0] == "print" for call in native.calls)
    assert receipt.read_bytes() == original_receipt
    assert remote.config.read_bytes() == original_config
    assert Path(json.loads(original_receipt)["plist_path"]).read_bytes() == original_plist
    assert not native.jobs
    before = list(native.calls)
    with pytest.raises(DomainError) as denied:
        service.require_service_enabled(remote.profile)
    assert denied.value.code == "SERVICE_STOPPED"
    assert denied.value.effect is EffectState.NOT_STARTED
    assert native.calls == before


@pytest.mark.parametrize("action", ["stop", "uninstall"])
async def test_client_stop_and_uninstall_work_without_the_ca(native, remote, action):
    await configure(remote)
    installed = await command(remote.config, "service", "install")
    receipt_path = remote.profile.state_dir / "service" / "receipt.json"
    plist_path = Path(json.loads(receipt_path.read_bytes())["plist_path"])
    notes = receipt_path.parent / "operator-notes.txt"
    private_write(notes, "Keep unrelated private state.\n")
    original_config = remote.config.read_bytes()
    remote.profile.ca_bundle.unlink()
    native.calls.clear()

    result = await command(remote.config, "service", action)

    assert result["enabled"] is False
    assert result["loaded"] is False and result["running"] is False
    assert result["managed"] is (action == "stop")
    assert remote.config.read_bytes() == original_config
    assert notes.read_text() == "Keep unrelated private state.\n"
    assert not native.jobs
    assert any(call[0] == "disable" for call in native.calls)
    assert any(call[0] == "bootout" for call in native.calls)
    if action == "stop":
        assert result["label"] == installed["label"]
        assert json.loads(receipt_path.read_bytes())["enabled"] is False
        assert plist_path.exists()
    else:
        assert not receipt_path.exists()
        assert not plist_path.exists()
        assert await command(remote.config, "service", "uninstall") == result
    assert await command(remote.config, "service", "status") == result


@pytest.mark.parametrize("ca_state", ["missing", "changed"])
async def test_failed_explicit_client_start_cannot_reenable_stopped_intent(native, remote, ca_state):
    await configure(remote)
    await command(remote.config, "service", "install")
    stopped = await command(remote.config, "service", "stop")
    receipt = remote.profile.state_dir / "service" / "receipt.json"
    original_receipt = receipt.read_bytes()
    original_ca = remote.profile.ca_bundle.read_bytes()
    if ca_state == "missing":
        remote.profile.ca_bundle.unlink()
    else:
        private_write(
            remote.profile.ca_bundle, ca_material("Different valid synthetic CA"), replace=True,
        )
    native.calls.clear()

    with pytest.raises(DomainError) as denied:
        await command(remote.config, "service", "start")

    assert denied.value.code == "CONFIG_INVALID"
    assert denied.value.effect is EffectState.NOT_STARTED
    assert receipt.read_bytes() == original_receipt
    assert native.calls == []
    assert not native.jobs
    assert await command(remote.config, "service", "status") == stopped
    with pytest.raises(DomainError) as disabled:
        service.require_service_enabled(remote.profile)
    assert disabled.value.code == "SERVICE_STOPPED"
    private_write(remote.profile.ca_bundle, original_ca, replace=ca_state == "changed")
    started = await command(remote.config, "service", "start")
    assert started["enabled"] is True and started["running"] is True
    assert started["label"] == stopped["label"]


@pytest.mark.parametrize("host", ["claude", "codex", "omp"])
async def test_offline_remote_adapter_removal_preserves_foreign_entries_and_pending_capture(
    tmp_path, monkeypatch, remote, host,
):
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    native_home = home / "private-claude"
    native_home.mkdir(mode=0o700)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(native_home))
    project = tmp_path / "project"
    project.mkdir(mode=0o700)
    agent, producer = home / "agent.token", home / "producer.token"
    private_write(agent, "synthetic-agent-credential\n")
    private_write(producer, "synthetic-producer-credential\n")
    foreign_hook = {"hooks": [{"type": "command", "command": "foreign-hook --preserve"}]}
    foreign_server = {"command": "foreign-server"}
    if host == "claude":
        config = project / ".claude/settings.local.json"
        expected_config = {
            "hooks": {"PreToolUse": [foreign_hook]}, "permissions": {"deny": ["Bash(rm *)"]},
        }
        mcp = native_home / ".claude.json"
        expected_mcp = {
            "projects": {str(project): {
                "hasTrustDialogAccepted": False, "mcpServers": {"foreign": foreign_server},
            }}, "nativeSessionCount": 7,
        }
    elif host == "codex":
        config = project / ".codex/hooks.json"
        expected_config = {"description": "foreign hooks", "hooks": {"PreToolUse": [foreign_hook]}}
        mcp = project / ".codex/config.toml"
        expected_mcp = '# Preserve native formatting.\nmodel = "foreign-model"\n[mcp_servers.foreign]\ncommand = "foreign-server"\n'
    else:
        config = project / ".omp/settings.json"
        expected_config = {"extensions": ["/foreign/extension.ts"]}
        mcp = project / ".omp/mcp.json"
        expected_mcp = {"mcpServers": {"foreign": foreign_server}}
        private_write(project / ".omp/extensions/foreign.ts", "export default function () {}\n")
    private_write(config, json.dumps(expected_config))
    private_write(mcp, expected_mcp if host == "codex" else json.dumps(expected_mcp))
    await configure(remote)
    installed = hosts.install_host(
        remote.profile, project, "binding-control", host, agent, producer, strict=host == "claude",
    )
    receipt_path = Path(installed["receipt"])
    receipt = hosts.load_receipt(receipt_path)
    runtime = Path(receipt["runtime_dir"])
    spool_path = runtime / "capture.sqlite3"
    capture = CaptureCommand(
        binding_id="binding-control", idempotency_key="pending-control", origin_key="origin-control",
        speaker="human", body="Synthetic pending capture must survive native removal.",
    )
    spool = ProducerSpool(
        spool_path, remote.profile.deployment_id, capture.binding_id, remote.profile.spool_limit_bytes,
    )
    try:
        assert spool.enqueue(capture)["state"] == "durably_spooled"
    finally:
        spool.close()
    later_server = {"command": "foreign-added-later"}
    if host == "codex":
        addition = '\n[mcp_servers.later]\ncommand = "foreign-added-later"\n'
        private_write(mcp, mcp.read_text() + addition, replace=True)
        expected_mcp += addition
    else:
        document = json.loads(mcp.read_bytes())
        if host == "claude":
            document["projects"][str(project)]["mcpServers"]["later"] = later_server
            expected_mcp["projects"][str(project)]["mcpServers"]["later"] = later_server
        else:
            document["mcpServers"]["later"] = later_server
            expected_mcp["mcpServers"]["later"] = later_server
        private_write(mcp, json.dumps(document), replace=True)
    original_profile = remote.config.read_bytes()
    remote.profile.ca_bundle.unlink()
    agent.unlink()
    producer.unlink()

    removed = await command(remote.config, "host-uninstall", "--project", str(project), "--host", host)

    assert removed["state"] == "uninstalled"
    assert removed["native_trust"] == "not_modified"
    assert removed["pending_spool_retained"] == str(spool_path)
    assert json.loads(config.read_bytes()) == expected_config
    if host == "codex":
        assert mcp.read_text() == expected_mcp
        assert hosts.SERVER_NAME not in tomllib.loads(mcp.read_text())["mcp_servers"]
    else:
        assert json.loads(mcp.read_bytes()) == expected_mcp
    if host == "omp":
        assert not (project / ".omp/extensions/agents-memory.ts").exists()
        assert (project / ".omp/extensions/foreign.ts").read_text() == "export default function () {}\n"
    assert hosts.load_receipt(receipt_path, active=False)["state"] == "removed"
    assert remote.config.read_bytes() == original_profile
    reopened = ProducerSpool(
        spool_path, remote.profile.deployment_id, capture.binding_id, remote.profile.spool_limit_bytes,
    )
    try:
        assert reopened.status()["pending"] == 1
        assert reopened.enqueue(capture)["replay"] is True
    finally:
        reopened.close()
    assert await command(
        remote.config, "host-uninstall", "--project", str(project), "--host", host,
    ) == removed


@pytest.mark.parametrize("mismatch,code", [
    ("deployment_id", "HOST_SCOPE_DENIED"), ("realm", "HOST_SCOPE_DENIED"),
    ("mode", "HOST_SCOPE_DENIED"), ("auth_mode", "HOST_SCOPE_DENIED"),
    ("role", "HOST_SCOPE_DENIED"), ("binding", "HOST_SCOPE_DENIED"),
    ("bounds", "HOST_SCOPE_DENIED"), ("binding_revision", "HOST_SCOPE_DENIED"),
    ("same_credential", "HOST_CREDENTIAL_SEPARATION_REQUIRED"),
    ("generation", "BOOTSTRAP_INVALID"), ("extra_field", "BOOTSTRAP_INVALID"),
])
async def test_remote_install_rejects_inconsistent_current_grants_without_native_writes(remote, tmp_path, monkeypatch, mismatch, code):
    from agents_memory.ingress import ClientBootstrapBounds, ClientBootstrapResult

    project = tmp_path / "project"
    project.mkdir(mode=0o700)
    binding = "binding_requested"
    grants = []
    for role in ("agent", "producer"):
        grants.append(ClientBootstrapResult(
            deployment_id=remote.profile.deployment_id, realm=remote.profile.realm,
            mode=remote.profile.mode, capability=remote.profile.capability, auth_mode=remote.profile.auth_mode,
            credential_id="credential_" + role, generation=1, role=role,
            bindings=(binding,), binding_id=binding, binding_revision=1,
            bounds=ClientBootstrapBounds(
                max_capture_bytes=remote.profile.max_capture_bytes,
                max_http_body_bytes=remote.profile.max_http_body_bytes,
                max_mcp_response_bytes=remote.profile.max_mcp_response_bytes,
                spool_limit_bytes=remote.profile.spool_limit_bytes, max_concurrent_requests=16,
            ),
        ).model_dump(mode="json"))
    altered = grants[1]
    if mismatch in {"deployment_id", "realm"}:
        altered[mismatch] = "other_authority"
    elif mismatch == "mode":
        altered["mode"] = "personal"
    elif mismatch == "auth_mode":
        altered["auth_mode"] = "oauth"
    elif mismatch == "role":
        altered["role"] = "agent"
    elif mismatch == "binding":
        altered["binding_id"], altered["bindings"] = "binding_other", ["binding_other"]
    elif mismatch == "bounds":
        altered["bounds"]["max_capture_bytes"] += 1
    elif mismatch == "binding_revision":
        altered["binding_revision"] = 2
    elif mismatch == "same_credential":
        altered["credential_id"] = grants[0]["credential_id"]
    elif mismatch == "generation":
        altered["generation"] = 0
    else:
        altered["database_dsn"] = "forbidden_unexpected_field"

    class Response:
        def __init__(self, value):
            self.value = value

        async def call(self, route, payload):
            return self.value

    def client(settings, token):
        return Response(grants[0 if token.name == "agent.token" else 1])

    monkeypatch.setattr(cli, "client_from_settings", client)
    args = SimpleNamespace(
        ack_remote_storage=True, project=project, binding=binding,
        agent_token_file=tmp_path / "agent.token", producer_token_file=tmp_path / "producer.token",
        host="codex", strict=False, prompt_recall=False,
    )
    with pytest.raises(DomainError) as denied:
        await cli._install_remote_host(args, remote.profile)
    assert denied.value.code == code
    assert denied.value.effect is EffectState.NOT_STARTED
    assert not (project / ".codex").exists()
    assert not (remote.profile.state_dir / "host-adapters").exists()
