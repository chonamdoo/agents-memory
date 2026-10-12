from __future__ import annotations

import base64
import hashlib
import json
import multiprocessing
import os
import sqlite3
import subprocess
import sys
import threading
import time
import tomllib
from pathlib import Path

import pytest

from agents_memory import hosts, private_io
from agents_memory.config import Settings
from agents_memory.domain import DomainError, canonical_digest
from agents_memory.spool import ProducerSpool


@pytest.fixture
def installation(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    isolated_home = tmp_path / "home"
    isolated_home.mkdir(mode=0o700)
    monkeypatch.setenv("HOME", str(isolated_home))
    native_home = tmp_path / "private-claude"
    native_home.mkdir(mode=0o700)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(native_home))
    agent, producer = tmp_path / "agent.token", tmp_path / "producer.token"
    agent.write_text("private-agent-credential\n")
    producer.write_text("private-producer-credential\n")
    agent.chmod(0o600)
    producer.chmod(0o600)
    settings = Settings(
        deployment_id="personal-local", realm="personal", mode="personal",
        database_dsn="postgresql://not-used", state_dir=tmp_path / "state",
        journal_dir=tmp_path / "journal", spool_limit_bytes=65536,
    )

    def install(host="claude", strict=None, prompt_recall=False):
        strict = host != "omp" if strict is None else strict
        result = hosts.install_host(settings, project, "project-binding", host, agent, producer, strict=strict, prompt_recall=prompt_recall)
        return Path(result["receipt"])

    return project, settings, agent, producer, install


@pytest.fixture
def authority(monkeypatch):
    class Endpoint:
        required = True
        stamp = {"epoch": 1, "rules": [["rule-one", 1, "digest-one"]]}
        text = '{"approved_rules":[],"memory_candidates":[],"relations":[]}'
        context_error = None
        capture_error = "SERVICE_UNAVAILABLE"
        calls = []

        def __init__(self, base_url, token_file, timeout=120):
            self.token_file = token_file

        def request(self, path, payload):
            self.calls.append((path, self.token_file, payload))
            if path == "/api/capture":
                if self.capture_error:
                    raise DomainError(self.capture_error, "No raw request diagnostics")
                return {"effect": "committed", "id": "operation-one"}
            if self.context_error:
                raise DomainError(self.context_error, "No raw rule diagnostics")
            result = {"context": self.text, "context_bytes": len(self.text.encode()), "stamp": dict(self.stamp)}
            if path == "/api/required-context":
                result["required"] = self.required
            return result

    monkeypatch.setattr(hosts, "LocalClient", Endpoint)
    return Endpoint


def native(project, host="claude", event="UserPromptSubmit", **fields):
    result = {"cwd": str(project), "session_id": "root-run", "hook_event_name": event}
    if host == "claude":
        result["prompt_id"] = "prompt-one"
    elif host == "codex":
        result.update(turn_id="turn-one", transcript_path="/private/native/root-thread.jsonl")
    else:
        result.pop("hook_event_name")
        result.update(event=event, agent={"kind": "main", "id": "main-agent", "depth": 0}, adapter_turn_id="adapter-turn-one", model_api="anthropic-messages")
    result.update(fields)
    return result


def action(project, host="claude", **fields):
    return native(
        project, host, "tool_call" if host == "omp" else "PreToolUse",
        tool_name="write" if host == "omp" else "Write",
        tool_input={"path" if host == "omp" else "file_path": str(project / "src/example.py")},
        **fields,
    )


def claude_document(project, servers):
    return {"projects": {str(project): {"mcpServers": servers}}}


def mcp_servers(document, project, host="claude"):
    return (document["projects"][str(project)] if host == "claude" else document)["mcpServers"]


def update_native_unowned_state(project):
    path = hosts._claude_config_path()
    document = json.loads(path.read_text()) if path.exists() else {}
    document["nativeSessionCount"] = 7
    projects = document.setdefault("projects", {})
    scope = projects.setdefault(str(project), {})
    scope["hasTrustDialogAccepted"] = True
    scope.setdefault("mcpServers", {})["af-owned"] = {"command": "user-added-after-crash"}
    projects[str(project.parent / "other-project")] = {"hasTrustDialogAccepted": False, "nativeHistory": [1, 2]}
    path.write_text(json.dumps(document))
    return document



@pytest.mark.parametrize("host", ["claude", "codex", "omp"])
def test_install_uninstall_preserves_user_and_agent_flow_entries(installation, host):
    project, settings, _, _, install = installation
    user_hook = {"hooks": [{"type": "command", "command": "af-owned-hook --do-not-rewrite"}]}
    if host == "claude":
        (project / ".claude").mkdir()
        config = project / ".claude/settings.local.json"
        config.write_text(json.dumps({"hooks": {"PreToolUse": [user_hook]}, "permissions": {"deny": ["Bash(rm *)"]}}))
        mcp = hosts._claude_config_path()
        mcp.write_text(json.dumps(claude_document(project, {"existing": {"command": "user-server"}})))
    elif host == "codex":
        (project / ".codex").mkdir()
        config = project / ".codex/hooks.json"
        config.write_text(json.dumps({"description": "AF managed entries", "hooks": {"PreToolUse": [user_hook]}}))
        mcp = project / ".codex/config.toml"
        mcp.write_text('# keep comment and formatting\nmodel = "user-model"\n[mcp_servers.existing]\ncommand = "user-server"\n')
    else:
        (project / ".omp/extensions").mkdir(parents=True)
        config = project / ".omp/settings.json"
        config.write_text('{"extensions":["/user/af-extension.ts"]}\n')
        mcp = project / ".omp/mcp.json"
        mcp.write_text(json.dumps({"mcpServers": {"existing": {"command": "user-server"}}}))
        (project / ".omp/extensions/af-owned.ts").write_text("export default function () {}\n")
    old_mcp = mcp.read_bytes()
    old_config = json.loads(config.read_text())
    receipt = install(host)
    manifest = hosts.load_receipt(receipt)
    assert manifest["capabilities"]["startup_corpus_bytes"] == 0
    assert manifest["capabilities"]["native_trust"].startswith("unverified")
    assert b"private-agent-credential" not in receipt.read_bytes()
    assert b"private-producer-credential" not in receipt.read_bytes()
    if host == "codex":
        assert tomllib.loads(mcp.read_text())["mcp_servers"][hosts.SERVER_NAME]["args"][-2:] == ["--receipt", str(receipt)]
    else:
        assert mcp_servers(json.loads(mcp.read_text()), project, host)[hosts.SERVER_NAME]["type"] == "stdio"
    result = hosts.uninstall_host(settings, project, host)
    assert result["state"] == "uninstalled"
    assert json.loads(config.read_text()) == old_config
    if host == "codex":
        assert mcp.read_bytes() == old_mcp
    else:
        assert json.loads(mcp.read_text()) == json.loads(old_mcp)
    assert not (project / "AGENTS.md").exists()
    assert not (project / "CLAUDE.md").exists()


@pytest.mark.parametrize("host", ["claude", "codex", "omp"])
def test_owned_drift_cancels_entire_uninstall(installation, host):
    project, settings, _, _, install = installation
    receipt = install(host)
    manifest = hosts.load_receipt(receipt)
    entry = next(e for e in manifest["ownership"] if e["kind"] in {"file", "toml", "mcp", "local_mcp"})
    path = project / entry["path"]
    if entry["kind"] == "file":
        path.write_text(path.read_text() + "// user changed extension\n")
    elif entry["kind"] == "toml":
        path.write_text(path.read_text().replace("host-stdio", "user-stdio"))
    else:
        doc = json.loads(path.read_text())
        mcp_servers(doc, project, host)[hosts.SERVER_NAME]["command"] = "user-stdio"
        path.write_text(json.dumps(doc))
    snapshots = {project / e["path"]: (project / e["path"]).read_bytes() for e in manifest["ownership"]}
    with pytest.raises(DomainError, match="changed"):
        hosts.uninstall_host(settings, project, host)
    assert receipt.exists()
    assert all(path.read_bytes() == raw for path, raw in snapshots.items())


def test_conflicting_mcp_entry_is_not_replaced(installation):
    project, _, _, _, install = installation
    config = hosts._claude_config_path()
    config.write_text(json.dumps(claude_document(project, {hosts.SERVER_NAME: {"command": "user-owned"}})))
    before = config.read_bytes()
    with pytest.raises(DomainError) as error:
        install()
    assert error.value.code == "HOST_ENTRY_CONFLICT"
    assert config.read_bytes() == before
    assert not (project / ".claude/settings.local.json").exists()


def test_failed_install_rolls_back_owned_key_without_erasing_unowned_updates(installation, monkeypatch):
    project, settings, _, _, install = installation
    config = hosts._claude_config_path()
    before = json.dumps(claude_document(project, {"existing": {"command": "user-owned"}}), indent=2).encode() + b"\n"
    config.write_bytes(before)
    writer = hosts.private_write

    def fail_second(path, content, *, replace=False, **options):
        if path.name == "settings.local.json":
            update_native_unowned_state(project)
            raise OSError("cancelled native install")
        writer(path, content, replace=replace, **options)

    monkeypatch.setattr(hosts, "private_write", fail_second)
    with pytest.raises(OSError):
        install()
    expected = json.loads(before)
    expected["nativeSessionCount"] = 7
    expected["projects"][str(project)]["hasTrustDialogAccepted"] = True
    expected["projects"][str(project)]["mcpServers"]["af-owned"] = {"command": "user-added-after-crash"}
    expected["projects"][str(project.parent / "other-project")] = {"hasTrustDialogAccepted": False, "nativeHistory": [1, 2]}
    assert json.loads(config.read_text()) == expected
    receipt_path = hosts._receipt_path(settings, project, "claude")
    assert hosts.load_receipt(receipt_path, active=False)["state"] == "pending"
    monkeypatch.setattr(hosts, "private_write", writer)
    assert install() == receipt_path
    assert hosts.load_receipt(receipt_path)["state"] == "installed"


def test_agent_and_producer_credentials_must_be_distinct(installation):
    project, settings, agent, producer, _ = installation
    producer.write_bytes(agent.read_bytes())
    with pytest.raises(DomainError) as error:
        hosts.install_host(settings, project, "project-binding", "claude", agent, producer)
    assert error.value.code == "HOST_CREDENTIAL_SEPARATION_REQUIRED"
    assert not (hosts._claude_config_path()).exists()


@pytest.mark.parametrize("host", ["claude"])
def test_offered_or_second_identical_action_never_proves_consumption(installation, authority, host):
    project, _, _, _, install = installation
    receipt = install(host, prompt_recall=True)
    prompt = native(project, host, "before_agent_start" if host == "omp" else "UserPromptSubmit", prompt="Use project conventions")
    offered = hosts.handle_hook(receipt, prompt)
    assert offered["offered"] is True
    first = hosts.handle_hook(receipt, action(project, host))
    for event in [
        native(project, host, "before_provider_request", payload={"reasoning": "must never capture"}),
        native(project, host, "after_provider_response", requestId="response-is-not-consumption"),
    ]:
        observed = hosts.handle_hook(receipt, event)
        assert observed["provider_input_observed"] is False
    second = hosts.handle_hook(receipt, action(project, host, provider_input_observed=True, consumed=True))
    assert first["state"] == second["state"] == "blocked"
    assert first["code"] == second["code"] == "HOST_PROVIDER_INPUT_UNOBSERVABLE"
    assert second["provider_input_observed"] is False
    assert authority.calls[-1][0] == "/api/required-context"


def test_prompt_reentry_does_not_create_another_generation(installation, authority):
    project, _, _, _, install = installation
    receipt = install("omp", prompt_recall=True)
    prompt = native(project, "omp", "before_agent_start", prompt="same native submission")
    first = hosts.handle_hook(receipt, prompt)
    again = hosts.handle_hook(receipt, prompt)
    assert first["generation"] == again["generation"]
    # OMP discards rejected preparation messages; re-entry must return context
    # again for the accepted attempt without minting another generation/proof.
    assert first["offered"] and again["offered"]
    assert len([call for call in authority.calls if call[0] == "/api/context"]) == 2


@pytest.mark.parametrize("lifecycle", ["session_before_compact", "session_compact", "session_switch", "session_branch", "session_tree"])
def test_omp_advisory_lifecycle_invalidates_generation_and_action_order(installation, authority, lifecycle):
    project, _, _, _, install = installation
    receipt = install("omp")
    prompt = native(project, "omp", "before_agent_start", prompt="before transition")
    offered = hosts.handle_hook(receipt, prompt)
    transition = hosts.handle_hook(receipt, native(project, "omp", lifecycle, reason="fork"))
    denied = hosts.handle_hook(receipt, action(project, "omp"))
    assert transition["generation"] > offered["generation"]
    assert denied["state"] == "degraded"
    assert denied["code"] == "HOST_GENERATION_UNOBSERVED"
    refreshed = hosts.handle_hook(receipt, {**prompt, "adapter_turn_id": "after-transition"})
    assert refreshed["generation"] > transition["generation"]
    assert hosts.handle_hook(receipt, action(project, "omp", adapter_turn_id="after-transition"))["state"] == "degraded"


def test_omp_child_state_never_uses_parent_generation(installation, authority):
    project, _, _, _, install = installation
    receipt = install("omp")
    root = hosts.handle_hook(receipt, native(project, "omp", "before_agent_start", prompt="root context"))
    child = {"kind": "sub", "id": "child-agent", "parentId": "main-agent", "depth": 0}
    denied = hosts.handle_hook(receipt, action(project, "omp", agent=child))
    assert denied["code"] == "HOST_GENERATION_UNOBSERVED"
    child_prompt = hosts.handle_hook(receipt, native(project, "omp", "before_agent_start", agent=child, prompt="child context"))
    assert root["generation"] == child_prompt["generation"] == 1
    hosts.handle_hook(receipt, native(project, "omp", "session_compact", agent=child))
    root_reentry = hosts.handle_hook(receipt, native(project, "omp", "before_agent_start", prompt="root context"))
    assert root_reentry["generation"] == root["generation"]


def test_codex_parent_session_is_not_thread_or_child_identity(installation, authority):
    project, _, _, _, install = installation
    receipt = install("codex", strict=False)
    root = native(project, "codex", prompt="root input", thread_id="root-thread")
    fork = native(project, "codex", prompt="fork input", thread_id="fork-thread", transcript_path="/private/native/fork.jsonl")
    child = native(project, "codex", prompt="child input", agent_id="child-agent", transcript_path="/private/native/child.jsonl")
    for event in (root, fork, child):
        assert hosts.handle_hook(receipt, event)["generation"] == 1
    hosts.handle_hook(receipt, {**fork, "hook_event_name": "SessionStart", "source": "resume"})
    assert hosts.handle_hook(receipt, root)["generation"] == 1
    assert hosts.handle_hook(receipt, child)["generation"] == 1
    assert hosts.handle_hook(receipt, fork)["generation"] == 3


def test_codex_strict_prompt_blocks_unhooked_hosted_tools(installation, authority):
    project, _, _, _, install = installation
    receipt = install("codex")
    result = hosts.handle_hook(receipt, native(project, "codex", prompt="Run hosted research"))
    assert result["state"] == "blocked"
    assert result["stdout"]["decision"] == "block"
    assert result["code"] == "HOST_HOSTED_TOOL_GUARD_UNAVAILABLE"
    assert not any(path == "/api/context" for path, _, _ in authority.calls)


@pytest.mark.parametrize("code", ["RULE_APPLICABILITY_UNKNOWN", "REQUIRED_CONTEXT_OVERFLOW", "CREDENTIAL_REVOKED", "SERVICE_UNAVAILABLE"])
def test_strict_authority_failure_is_fail_closed_and_body_free(installation, authority, code):
    project, _, _, _, install = installation
    receipt = install()
    hosts.handle_hook(receipt, native(project, prompt="prepare prompt"))
    authority.context_error = code
    result = hosts.handle_hook(receipt, action(project))
    assert result["state"] == "blocked"
    assert result["stdout"]["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert result["code"] == code
    assert "prepare prompt" not in json.dumps(result)


def test_changed_authority_stamp_does_not_reuse_offered_text(installation, authority):
    project, _, _, _, install = installation
    receipt = install(prompt_recall=True)
    hosts.handle_hook(receipt, native(project, prompt="prepare"))
    authority.stamp = {"epoch": 2, "rules": [["rule-one", 2, "digest-two"]]}
    result = hosts.handle_hook(receipt, action(project))
    assert result["state"] == "blocked"
    assert result["code"] == "HOST_CONTEXT_STALE"



@pytest.mark.parametrize("host", ["claude", "omp"])
def test_no_required_rule_allows_supported_action_without_context_warning(installation, authority, host):
    project, _, _, _, install = installation
    receipt = install(host, strict=False)
    authority.required = False
    hosts.handle_hook(receipt, native(project, host, "before_agent_start" if host == "omp" else "UserPromptSubmit", prompt="prepare"))
    result = hosts.handle_hook(receipt, action(project, host))
    assert result["state"] == "ok"
    authority.context_error = "RULE_APPLICABILITY_UNKNOWN"
    refusal = hosts.handle_hook(receipt, action(project, host))
    assert refusal["code"] == "RULE_APPLICABILITY_UNKNOWN"
    assert refusal["provider_input_observed"] is False


@pytest.mark.parametrize("host", ["claude"])
def test_strict_core_mcp_delegation_does_not_authorize_unknown_filesystem_tool(installation, authority, host):
    project, _, _, _, install = installation
    receipt = install(host)
    prefix = "mcp__agents_memory_" if host == "omp" else "mcp__agents-memory__"
    delegated = hosts.handle_hook(receipt, native(project, host, "tool_call" if host == "omp" else "PreToolUse", tool_name=prefix + "memory_context"))
    assert delegated["state"] == "delegated"
    refused = hosts.handle_hook(receipt, native(project, host, "tool_call" if host == "omp" else "PreToolUse", tool_name="shell-unknown", tool_input={}))
    assert refused["state"] == "blocked"
    assert refused["code"] == "HOST_FOOTPRINT_UNSUPPORTED"

@pytest.mark.parametrize("fields,code", [
    ({"cwd": "/outside/project"}, "HOST_SCOPE_UNRESOLVED"),
    ({"tool_input": {"file_path": "../outside.py"}}, "HOST_SCOPE_UNRESOLVED"),
    ({"tool_name": "Bash", "tool_input": {"command": "arbitrary shell"}}, "HOST_FOOTPRINT_UNSUPPORTED"),
    ({"tool_name": "hosted-tool"}, "HOST_FOOTPRINT_UNSUPPORTED"),
    ({"tool_input": {}}, "HOST_FOOTPRINT_UNKNOWN"),
])
def test_unknown_scope_or_footprint_never_allows_strict_action(installation, authority, fields, code):
    project, _, _, _, install = installation
    receipt = install()
    hosts.handle_hook(receipt, native(project, prompt="prepare"))
    event = action(project)
    event.update(fields)
    result = hosts.handle_hook(receipt, event)
    assert result["state"] == "blocked"
    assert result["code"] == code


def test_overflow_is_not_truncated_into_success(installation, authority):
    project, _, _, _, install = installation
    receipt = install(prompt_recall=True)
    authority.text = "required rule body " * 300
    result = hosts.handle_hook(receipt, native(project, prompt="prepare"))
    assert result["state"] == "blocked"
    assert result["code"] == "REQUIRED_CONTEXT_OVERFLOW"
    assert "required rule body" not in json.dumps(result)


def test_absent_receipt_returns_native_deny_not_fail_open_exception(tmp_path):
    result = hosts.handle_hook(tmp_path / "claude.json", {"hook_event_name": "PreToolUse"})
    assert result["stdout"]["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert result["code"] == "HOST_RECEIPT_UNAVAILABLE"


def test_claude_ambiguous_prompt_and_assistant_trace_are_not_captured(installation, authority):
    project, _, _, _, install = installation
    receipt = install()
    result = hosts.handle_hook(receipt, native(project, prompt="could be scheduled or a subagent report"))
    assert result["capture"]["state"] == "gap"
    assert result["capture"]["code"] == "HOST_PROMPT_ORIGIN_UNOBSERVABLE"
    hosts.handle_hook(receipt, native(project, event="Stop", last_assistant_message="not a finding", reasoning="private trace"))
    assert not any(path == "/api/capture" for path, _, _ in authority.calls)


def test_native_turn_capture_replays_exact_spool_envelope(installation, authority):
    project, _, agent, producer, install = installation
    receipt = install("codex", strict=False)
    event = native(project, "codex", prompt="actual documented user prompt")
    first = hosts.handle_hook(receipt, event)
    replay = hosts.handle_hook(receipt, event)
    assert first["capture"]["pending"] == replay["capture"]["pending"] == 1
    assert replay["capture"]["replay"] is True
    captures = [(token, body) for path, token, body in authority.calls if path == "/api/capture"]
    assert captures[0][0] == producer and captures[0][0] != agent
    assert captures[0][1] == captures[1][1]
    changed = hosts.handle_hook(receipt, {**event, "prompt": "different body same native turn"})
    assert changed["capture"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert changed["capture"]["pending"] == 1


def test_omp_ingress_only_capture_has_explicit_limited_identity(installation, authority):
    project, _, _, _, install = installation
    receipt = install("omp")
    event = native(project, "omp", "input", text="a genuine ingress message", source="interactive", hook_instance_id="ingress-one")
    first = hosts.handle_hook(receipt, event)
    assert first["capture"]["identity"] == "hook_instance_only"
    replay = hosts.handle_hook(receipt, event)
    assert replay["capture"]["pending"] == 1
    another = hosts.handle_hook(receipt, {**event, "hook_instance_id": "ingress-two"})
    assert another["capture"]["pending"] == 2
    hosts.handle_hook(receipt, native(project, "omp", "before_agent_start", prompt="transformed injected prompt"))
    assert len([call for call in authority.calls if call[0] == "/api/capture"]) == 3
    excluded = hosts.handle_hook(receipt, {**event, "text": hosts.BOUNDED_CONTEXT_MARKER + " retrieved memory"})
    assert excluded["capture"]["state"] == "excluded"
    assert len([call for call in authority.calls if call[0] == "/api/capture"]) == 3


def test_spool_overflow_is_durable_explicit_body_free_gap(installation, authority):
    project, _, _, _, install = installation
    receipt = install("omp")
    result = None
    for index in range(3):
        result = hosts.handle_hook(receipt, native(project, "omp", "input", source="interactive", text="x" * 32000, hook_instance_id=f"input-{index}"))
    assert result["capture"]["code"] == "SPOOL_FULL"
    assert result["capture"]["gaps"]["SPOOL_FULL"] == 1
    assert result["capture"]["bytes"] <= result["capture"]["limit_bytes"]
    assert result["state"] == "degraded"
    assert "x" * 64 not in json.dumps(result)
    manifest = hosts.load_receipt(receipt)
    spool_path = Path(manifest["runtime_dir"]) / "capture.sqlite3"
    spool = ProducerSpool(spool_path, manifest["deployment_id"], manifest["binding_id"], manifest["spool_limit_bytes"])
    try:
        assert spool.status()["gaps"]["SPOOL_FULL"] == 1
    finally:
        spool.close()
    assert spool_path.stat().st_mode & 0o077 == 0


def test_receipts_and_generation_state_never_mirror_context_bodies(installation, authority):
    project, _, _, _, install = installation
    receipt = install("omp", prompt_recall=True)
    authority.text = '{"approved_rules":[{"body":"private convention never mirror"}],"memory_candidates":[]}'
    result = hosts.handle_hook(receipt, native(project, "omp", "before_agent_start", prompt="private user prompt"))
    assert len(result["stdout"]["additionalContext"].encode()) <= hosts.HOST_CONTEXT_BYTES
    manifest = hosts.load_receipt(receipt)
    for path in [receipt, *Path(manifest["runtime_dir"]).glob("*.json")]:
        raw = path.read_bytes()
        assert b"private convention never mirror" not in raw
        assert b"private user prompt" not in raw
        assert b"private-agent-credential" not in raw


@pytest.mark.parametrize("host", ["claude", "codex", "omp"])
@pytest.mark.parametrize("strict", [False, True])
def test_capability_matches_actual_strict_mode(installation, authority, host, strict):
    project, _, _, _, install = installation
    if host == "omp" and strict:
        with pytest.raises(DomainError) as caught:
            install(host, strict=True)
        assert caught.value.public()["code"] == "HOST_STRICT_UNSUPPORTED"
        capability = hosts.capabilities(host, strict=True)
        assert capability["strict"] == "unsupported_refused"
        assert capability["first_action"] == "refused_before_installation"
        assert capability["native_failure"] == "pre_request_errors_and_timeouts_continue_dispatch"
        return
    receipt = install(host, strict=strict)
    capability = hosts.load_receipt(receipt)["capabilities"]
    assert capability["first_action"] == (
        "deny_required_without_provider_input_evidence" if strict else "advisory_unenforced"
    )
    provider = hosts.handle_hook(receipt, native(project, host, "before_provider_request"))
    assert provider["state"] == ("blocked" if strict else "degraded")
    assert provider["provider_input_observed"] is False
    if host == "omp":
        assert "block" not in provider["stdout"]


@pytest.mark.parametrize("host,strict", [("claude", False), ("claude", True), ("omp", False)])
def test_action_output_preserves_exact_required_rule_revision_and_body(installation, authority, host, strict):
    project, _, _, _, install = installation
    receipt = install(host, strict=strict)
    authority.text = json.dumps({
        "approved_rules": [{
            "id": "rule-one", "version": 7, "body": "고객 원문을 외부로 보내지 않는다.",
            "required": True, "applicability": "true",
        }], "memory_candidates": [], "relations": [],
    }, ensure_ascii=False, separators=(",", ":"))
    hosts.handle_hook(receipt, native(project, host, "before_agent_start" if host == "omp" else "UserPromptSubmit", prompt="prepare"))
    result = hosts.handle_hook(receipt, action(project, host))
    assert result["state"] == ("blocked" if strict else "degraded")
    if host == "omp":
        offered = result["stdout"]["reason"] if strict else result["stdout"]["additionalContext"]
    else:
        output = result["stdout"]["hookSpecificOutput"]
        offered = output["permissionDecisionReason"] if strict else output["additionalContext"]
    assert offered.endswith(hosts.BOUNDED_CONTEXT_MARKER + "\n" + authority.text)
    assert result["provider_input_observed"] is False
    assert len(authority.text.encode()) < hosts.HOST_CONTEXT_BYTES




@pytest.mark.parametrize("field,value", [
    ("strict", None), ("strict", "false"), ("host", []), ("state", []),
    ("runtime_dir", None), ("max_http_body_bytes", True), ("ownership", [{}]),
])
def test_integrity_signed_but_incomplete_receipt_fails_closed(installation, field, value):
    project, _, _, _, install = installation
    receipt = install()
    document = json.loads(receipt.read_text())
    document.pop("ownership_digest")
    if value is None:
        document.pop(field)
    else:
        document[field] = value
    document["ownership_digest"] = canonical_digest(document)
    receipt.write_text(json.dumps(document))
    result = hosts.handle_hook(receipt, action(project))
    assert result["state"] == "blocked"
    assert result["code"] == "HOST_RECEIPT_UNAVAILABLE"
    with pytest.raises(DomainError) as caught:
        hosts.load_receipt(receipt)
    assert caught.value.code == "HOST_RECEIPT_INVALID"


def test_private_receipts_never_require_changing_consumer_ignore_rules(installation):
    project, settings, _, _, install = installation
    ignore = project / ".gitignore"
    original = b"# user-owned negation and AF rules\n!.agents-memory/user.json\n.agent-flow/private/\n"
    ignore.write_bytes(original)
    receipt = install()
    assert receipt.is_relative_to(settings.state_dir)
    assert not receipt.is_relative_to(project)
    assert not (project / ".agents-memory").exists()
    assert ignore.read_bytes() == original
    hosts.uninstall_host(settings, project, "claude")
    assert ignore.read_bytes() == original


def test_private_runtime_inside_consumer_project_is_refused_before_any_config_write(installation):
    project, settings, agent, producer, _ = installation
    unsafe = settings.model_copy(update={"state_dir": project / "state"})
    with pytest.raises(DomainError) as caught:
        hosts.install_host(unsafe, project, "project-binding", "claude", agent, producer)
    assert caught.value.code == "HOST_RUNTIME_PROJECT_DENIED"
    assert list(project.iterdir()) == []


def _abrupt_process(work):
    process = multiprocessing.get_context("fork").Process(target=work)
    process.start()
    process.join(10)
    if process.is_alive():
        process.kill()
        process.join()
        pytest.fail("Owned mutation never reached its deterministic crash point")
    assert process.exitcode == 41
    # The child has exited, so its native mkdir lease is abandoned. Expire
    # that real on-disk lease without making every crash regression sleep 10s.
    lock = hosts._claude_config_path().with_name(".claude.json.lock")
    if lock.exists():
        expired = time.time() - 11
        os.utime(lock, (expired, expired))


@pytest.mark.parametrize("host", ["claude", "codex", "omp"])
@pytest.mark.parametrize("boundary", ["pending_receipt", "first_config", "installed_receipt"])
def test_process_death_install_reconciles_owned_intent_without_erasing_user_or_af(installation, host, boundary):
    project, settings, agent, producer, install = installation
    user = project / "AF-owned.json"
    user.write_text('{"command":"af-owned --do-not-change"}\n')
    mcp = hosts._claude_config_path() if host == "claude" else project / (".codex/config.toml" if host == "codex" else ".omp/mcp.json")
    mcp.parent.mkdir(parents=True, exist_ok=True)
    original = b'# user comment\nmodel = "user-model"\n[mcp_servers.existing]\ncommand = "user-server"\n' if host == "codex" else b'{"mcpServers":{"existing":{"command":"user-server"}}}\n'
    if host == "claude":
        original = json.dumps(claude_document(project, {"existing": {"command": "user-server"}})).encode()
    mcp.write_bytes(original)
    receipt_path = hosts._receipt_path(settings, project, host)

    def crash():
        writer = hosts.private_write

        def write_and_exit(path, content, *, replace=False, **options):
            writer(path, content, replace=replace, **options)
            if boundary == "installed_receipt":
                if path == receipt_path and json.loads(content)["state"] == "installed":
                    os._exit(41)
            elif path == (receipt_path if boundary == "pending_receipt" else mcp):
                os._exit(41)

        hosts.private_write = write_and_exit
        hosts.install_host(settings, project, "project-binding", host, agent, producer, strict=host != "omp")

    _abrupt_process(crash)
    pending = hosts.load_receipt(receipt_path, active=False)
    assert pending["state"] == ("installed" if boundary == "installed_receipt" else "pending")
    assert hosts.handle_hook(receipt_path, action(project, host))["state"] == ("degraded" if host == "omp" else "blocked")
    owner = pending["installation_id"]
    expected = None
    if host == "claude":
        expected = update_native_unowned_state(project)
        mcp_servers(expected, project).pop(hosts.SERVER_NAME, None)
    assert install(host) == receipt_path
    assert hosts.load_receipt(receipt_path)["installation_id"] == owner
    assert user.read_text() == '{"command":"af-owned --do-not-change"}\n'
    hosts.uninstall_host(settings, project, host)
    if host == "codex":
        assert tomllib.loads(mcp.read_text()) == tomllib.loads(original.decode())
    else:
        assert json.loads(mcp.read_text()) == (expected if host == "claude" else json.loads(original))


@pytest.mark.parametrize("host", ["claude", "codex", "omp"])
@pytest.mark.parametrize("boundary", ["removing_receipt", "first_config", "removed_receipt"])
def test_process_death_uninstall_resumes_removal_and_preserves_other_entries(installation, host, boundary):
    project, settings, _, _, install = installation
    user = project / "AF-owned.json"
    user.write_text("preserve user and AF\n")
    receipt_path = install(host)
    manifest = hosts.load_receipt(receipt_path)
    first = project / manifest["ownership"][0]["path"]

    def crash():
        unlink = hosts._unlink

        def unlink_and_exit(path):
            unlink(path)
            if boundary == "first_config" and path == first:
                os._exit(41)

        hosts._unlink = unlink_and_exit
        writer = hosts.private_write

        def write_and_exit(path, content, *, replace=False, **options):
            writer(path, content, replace=replace, **options)
            if boundary == "first_config" and path == first:
                os._exit(41)
            if path == receipt_path and json.loads(content)["state"] == boundary.removesuffix("_receipt"):
                os._exit(41)

        hosts.private_write = write_and_exit
        hosts.uninstall_host(settings, project, host)

    _abrupt_process(crash)
    assert hosts.load_receipt(receipt_path, active=False)["state"] == ("removed" if boundary == "removed_receipt" else "removing")
    expected = None
    if host == "claude":
        expected = update_native_unowned_state(project)
        mcp_servers(expected, project).pop(hosts.SERVER_NAME, None)
    assert hosts.uninstall_host(settings, project, host)["state"] == "uninstalled"
    assert hosts.uninstall_host(settings, project, host)["state"] == "uninstalled"
    assert user.read_text() == "preserve user and AF\n"
    if host == "claude":
        assert json.loads(first.read_text()) == expected
        assert not (project / ".claude/settings.local.json").exists()
    else:
        assert not first.exists()
    assert hosts.load_receipt(install(host))["installation_id"] != manifest["installation_id"]


@pytest.mark.parametrize("boundary", ["pending_receipt", "first_config"])
@pytest.mark.parametrize("recover", ["install", "cancel"])
def test_interrupted_claude_install_preserves_unowned_updates(installation, boundary, recover):
    project, settings, agent, producer, install = installation
    native = hosts._claude_config_path()
    receipt = hosts._receipt_path(settings, project, "claude")

    def crash():
        writer = hosts.private_write

        def write_and_exit(path, content, *, replace=False, **options):
            writer(path, content, replace=replace, **options)
            if path == (receipt if boundary == "pending_receipt" else native):
                os._exit(41)

        hosts.private_write = write_and_exit
        hosts.install_host(settings, project, "project-binding", "claude", agent, producer, strict=True)

    _abrupt_process(crash)
    expected = update_native_unowned_state(project)
    mcp_servers(expected, project).pop(hosts.SERVER_NAME, None)
    if recover == "install":
        assert install() == receipt
        assert hosts.load_receipt(receipt)["state"] == "installed"
    assert hosts.uninstall_host(settings, project, "claude")["state"] == "uninstalled"
    assert json.loads(native.read_text()) == expected
    assert not (project / ".claude/settings.local.json").exists()


@pytest.mark.parametrize("boundary", ["pending_receipt", "first_config"])
def test_interrupted_claude_owned_conflict_refuses_retry_and_cancellation(installation, boundary):
    project, settings, agent, producer, install = installation
    native = hosts._claude_config_path()
    receipt = hosts._receipt_path(settings, project, "claude")

    def crash():
        writer = hosts.private_write

        def write_and_exit(path, content, *, replace=False, **options):
            writer(path, content, replace=replace, **options)
            if path == (receipt if boundary == "pending_receipt" else native):
                os._exit(41)

        hosts.private_write = write_and_exit
        hosts.install_host(settings, project, "project-binding", "claude", agent, producer, strict=True)

    _abrupt_process(crash)
    document = update_native_unowned_state(project)
    mcp_servers(document, project)[hosts.SERVER_NAME] = {"command": "not-ours"}
    native.write_text(json.dumps(document))
    before = native.read_bytes()
    for recover in (install, lambda: hosts.uninstall_host(settings, project, "claude")):
        with pytest.raises(DomainError) as caught:
            recover()
        assert caught.value.code == "HOST_CONFIG_DRIFT"
        assert native.read_bytes() == before
        assert hosts.load_receipt(receipt, active=False)["state"] == "pending"
    assert not (project / ".claude/settings.local.json").exists()


@pytest.mark.parametrize("boundary", ["removing_receipt", "first_config"])
def test_interrupted_claude_removal_preserves_replacement_owned_conflict(installation, boundary):
    project, settings, _, _, install = installation
    receipt = install()
    native = hosts._claude_config_path()

    def crash():
        writer = hosts.private_write

        def write_and_exit(path, content, *, replace=False, **options):
            writer(path, content, replace=replace, **options)
            if boundary == "first_config" and path == native:
                os._exit(41)
            if boundary == "removing_receipt" and path == receipt and json.loads(content)["state"] == "removing":
                os._exit(41)

        hosts.private_write = write_and_exit
        hosts.uninstall_host(settings, project, "claude")

    _abrupt_process(crash)
    document = update_native_unowned_state(project)
    mcp_servers(document, project)[hosts.SERVER_NAME] = {"command": "replacement-not-ours"}
    native.write_text(json.dumps(document))
    snapshots = {native: native.read_bytes(), project / ".claude/settings.local.json": (project / ".claude/settings.local.json").read_bytes()}
    with pytest.raises(DomainError) as caught:
        hosts.uninstall_host(settings, project, "claude")
    assert caught.value.code == "HOST_CONFIG_DRIFT"
    assert all(path.read_bytes() == raw for path, raw in snapshots.items())
    assert hosts.load_receipt(receipt, active=False)["state"] == "removing"


@pytest.mark.parametrize("operation", ["install", "cancel", "remove"])
def test_legacy_claude_document_intent_recovers_only_its_owned_key(installation, operation):
    project, settings, agent, producer, install = installation
    native = hosts._claude_config_path()
    receipt = hosts._receipt_path(settings, project, "claude")
    before = None
    if operation == "remove":
        install()
        before = native.read_bytes()

    def crash():
        writer = hosts.private_write

        def write_and_exit(path, content, *, replace=False, **options):
            writer(path, content, replace=replace, **options)
            if path == receipt and json.loads(content)["state"] in {"pending", "removing"}:
                os._exit(41)

        hosts.private_write = write_and_exit
        if operation == "remove":
            hosts.uninstall_host(settings, project, "claude")
        else:
            hosts.install_host(settings, project, "project-binding", "claude", agent, producer, strict=True)

    _abrupt_process(crash)
    manifest = hosts.load_receipt(receipt, active=False)
    current_intent = hosts._intent_path(manifest)
    intent = json.loads(current_intent.read_text())
    index = next(index for index, step in enumerate(intent["steps"]) if step["path"] == str(native))
    key_step = intent["steps"][index]
    after = None if operation == "remove" else json.dumps(claude_document(project, {hosts.SERVER_NAME: key_step["after"]})).encode()
    intent["steps"][index] = {
        "path": str(native),
        "before": base64.b64encode(before).decode() if before is not None else None,
        "after": base64.b64encode(after).decode() if after is not None else None,
        "before_digest": hashlib.sha256(before).hexdigest() if before is not None else None,
        "after_digest": hashlib.sha256(after).hexdigest() if after is not None else None,
    }
    manifest["intent_digest"] = canonical_digest(intent)
    hosts.private_write(hosts._intent_path(manifest), json.dumps(intent))
    hosts._write_receipt(receipt, manifest)
    current_intent.unlink()
    expected = update_native_unowned_state(project)
    mcp_servers(expected, project).pop(hosts.SERVER_NAME, None)
    if operation == "install":
        assert install() == receipt
    assert hosts.uninstall_host(settings, project, "claude")["state"] == "uninstalled"
    assert json.loads(native.read_text()) == expected
    assert not (project / ".claude/settings.local.json").exists()


@pytest.mark.parametrize("lose_lease", [False, True])
def test_claude_publication_refuses_native_change_after_temp_sync(installation, monkeypatch, lose_lease):
    project, settings, _, _, install = installation
    native = hosts._claude_config_path()
    native.write_text(json.dumps(claude_document(project, {"user-owned": {"command": "other"}})))
    lock = native.with_name(native.name + ".lock")
    writer = hosts.private_write
    sync = private_io.sync_file
    armed = False
    preserved = None

    def sync_and_change(fd):
        nonlocal armed, preserved
        sync(fd)
        if armed:
            armed = False
            update_native_unowned_state(project)
            preserved = native.read_bytes()
            if lose_lease:
                lock.rmdir()
                lock.mkdir()

    def arm_native_write(path, content, *, replace=False, **options):
        nonlocal armed
        if path == native:
            armed = True
        writer(path, content, replace=replace, **options)

    with monkeypatch.context() as patch:
        patch.setattr(private_io, "sync_file", sync_and_change)
        patch.setattr(hosts, "private_write", arm_native_write)
        with pytest.raises(DomainError) as caught:
            install()
    assert caught.value.code == ("HOST_CONFIG_LOCK_LOST" if lose_lease else "HOST_CONFIG_DRIFT")
    assert preserved is not None and native.read_bytes() == preserved
    assert list(native.parent.glob(".memory-private-*")) == []
    assert not (project / ".claude/settings.local.json").exists()
    receipt = hosts._receipt_path(settings, project, "claude")
    assert hosts.load_receipt(receipt, active=False)["state"] == "pending"
    if lose_lease:
        assert lock.is_dir()
        lock.rmdir()
    assert install() == receipt
    assert hosts.uninstall_host(settings, project, "claude")["state"] == "uninstalled"
    assert json.loads(native.read_text()) == json.loads(preserved)


def test_claude_writer_lease_loss_preserves_replacement_lock_and_native_state(installation):
    project, _, _, _, _ = installation
    native = hosts._claude_config_path()
    original = json.dumps(claude_document(project, {"user-owned": {"command": "other"}})).encode()
    native.write_bytes(original)
    lock = native.with_name(native.name + ".lock")
    with hosts._claude_writer_lock(native) as check:
        lock.rmdir()
        lock.mkdir()
        with pytest.raises(DomainError) as caught:
            check()
        assert caught.value.code == "HOST_CONFIG_LOCK_LOST"
    assert lock.is_dir()
    assert native.read_bytes() == original


def test_claude_writer_lock_preserves_waiting_native_convention_update(installation, monkeypatch):
    project, _, _, _, install = installation
    native = hosts._claude_config_path()
    native.write_text(json.dumps(claude_document(project, {"user-owned": {"command": "other"}})))
    entered = threading.Event()
    released = threading.Event()
    writer_attempting = threading.Event()
    done = threading.Event()
    failures = []
    writer = hosts.private_write

    def paused_write(path, content, *, replace=False, **options):
        if path == native:
            entered.set()
            if not released.wait(5):
                raise RuntimeError("The simulated native writer did not reach contention")
        writer(path, content, replace=replace, **options)

    def install_in_thread():
        try:
            install()
        except BaseException as error:
            failures.append(error)

    def native_update():
        lock = native.with_name(native.name + ".lock")
        try:
            writer_attempting.set()
            deadline = time.monotonic() + 5
            while True:
                try:
                    lock.mkdir()
                    break
                except FileExistsError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("The native writer lock was not released")
                    time.sleep(0.01)
            try:
                update_native_unowned_state(project)
            finally:
                lock.rmdir()
        except BaseException as error:
            failures.append(error)
        finally:
            done.set()

    monkeypatch.setattr(hosts, "private_write", paused_write)
    installer = threading.Thread(target=install_in_thread)
    updater = threading.Thread(target=native_update)
    installer.start()
    try:
        assert entered.wait(5)
        updater.start()
        assert writer_attempting.wait(5)
        assert not done.wait(0.1)
    finally:
        released.set()
        installer.join(5)
        if updater.ident is not None:
            updater.join(5)
    assert not installer.is_alive() and not updater.is_alive()
    assert not failures
    document = json.loads(native.read_text())
    assert document["nativeSessionCount"] == 7
    assert mcp_servers(document, project)[hosts.SERVER_NAME]["type"] == "stdio"
    assert mcp_servers(document, project)["user-owned"] == {"command": "other"}
    assert mcp_servers(document, project)["af-owned"] == {"command": "user-added-after-crash"}


@pytest.mark.parametrize("host", ["claude", "codex", "omp"])
def test_validated_legacy_receipt_uninstall_then_private_v2_reinstall(installation, host, monkeypatch):
    project, settings, _, _, install = installation
    legacy = project / f".agents-memory/hosts/{host}.json"
    with monkeypatch.context() as patch:
        patch.setattr(hosts, "_receipt_path", lambda _settings, _root, _host: legacy)
        install(host, strict=False)
    document = json.loads(legacy.read_text())
    document.pop("ownership_digest")
    document.pop("state")
    document["adapter_version"] = 1
    document["ownership_digest"] = canonical_digest(document)
    legacy.write_text(json.dumps(document))
    with pytest.raises(DomainError) as caught:
        install(host, strict=False)
    assert caught.value.code == "HOST_LEGACY_REINSTALL_REQUIRED"
    with pytest.raises(DomainError):
        hosts.load_receipt(legacy)
    assert hosts.uninstall_host(settings, project, host)["state"] == "uninstalled"
    assert not legacy.exists()
    receipt = install(host, strict=False)
    assert not receipt.is_relative_to(project)
    assert hosts.load_receipt(receipt)["capabilities"]["first_action"] == "advisory_unenforced"


def test_recovered_hook_backlog_converges_in_order_and_exposes_remaining_gap(installation, authority):
    project, _, _, _, install = installation
    receipt = install("codex", strict=False)
    for index in range(8):
        result = hosts.handle_hook(receipt, native(project, "codex", prompt=f"human input {index}", turn_id=f"turn-{index}"))
    assert result["capture"]["pending"] == 8
    authority.calls.clear()
    authority.capture_error = None
    recovered = hosts.handle_hook(receipt, native(project, "codex", prompt="human input 8", turn_id="turn-8"))
    assert recovered["capture"]["pending"] == 5
    assert recovered["state"] == "degraded"
    recovered = hosts.handle_hook(receipt, native(project, "codex", prompt="human input 9", turn_id="turn-9"))
    assert recovered["capture"]["pending"] == 2
    recovered = hosts.handle_hook(receipt, native(project, "codex", prompt="human input 10", turn_id="turn-10"))
    assert recovered["capture"]["pending"] == 0
    delivered = [body["body"] for path, _, body in authority.calls if path == "/api/capture"]
    assert delivered == [f"human input {index}" for index in range(11)]


def test_pending_install_can_be_cancelled_even_if_removal_intent_publication_crashes(installation):
    project, settings, agent, producer, _ = installation
    first = hosts._claude_config_path()
    user = project / "AF-owned.json"
    user.write_text("unchanged AF configuration\n")
    receipt_path = hosts._receipt_path(settings, project, "claude")

    def interrupted_install():
        writer = hosts.private_write

        def write_and_exit(path, content, *, replace=False, **options):
            writer(path, content, replace=replace, **options)
            if path == first:
                os._exit(41)

        hosts.private_write = write_and_exit
        hosts.install_host(settings, project, "project-binding", "claude", agent, producer)

    _abrupt_process(interrupted_install)
    pending = hosts.load_receipt(receipt_path, active=False)
    original_intent = hosts._intent_path(pending)

    def interrupted_cancellation():
        writer = hosts.private_write

        def write_and_exit(path, content, *, replace=False, **options):
            writer(path, content, replace=replace, **options)
            if path.name.startswith("ownership-") and path != original_intent:
                os._exit(41)

        hosts.private_write = write_and_exit
        hosts.uninstall_host(settings, project, "claude")

    _abrupt_process(interrupted_cancellation)
    assert hosts.load_receipt(receipt_path, active=False)["intent_digest"] == pending["intent_digest"]
    assert original_intent.exists()
    assert hosts.uninstall_host(settings, project, "claude")["state"] == "uninstalled"
    assert json.loads(first.read_text()) == {}
    assert not (project / ".claude/settings.local.json").exists()
    assert user.read_text() == "unchanged AF configuration\n"


def test_committing_older_capture_never_claims_new_quarantined_capture_committed(installation, authority, monkeypatch):
    project, _, _, _, install = installation
    receipt = install("codex", strict=False)
    first = hosts.handle_hook(receipt, native(project, "codex", prompt="older valid source", turn_id="turn-old"))
    assert first["capture"]["state"] == "durably_spooled"
    authority.capture_error = None

    class SourceEndpoint(authority):
        def request(self, path, payload):
            if path == "/api/capture" and payload["body"] == "new rejected source":
                self.calls.append((path, self.token_file, payload))
                raise DomainError("ORIGIN_CONFLICT", "Sanitized permanent rejection")
            return super().request(path, payload)

    monkeypatch.setattr(hosts, "LocalClient", SourceEndpoint)
    rejected = hosts.handle_hook(receipt, native(project, "codex", prompt="new rejected source", turn_id="turn-rejected"))
    assert rejected["capture"]["committed"] == 1
    assert rejected["capture"]["pending"] == 0
    assert rejected["capture"]["quarantined"] == 1
    assert rejected["capture"]["state"] == "quarantined"
    assert rejected["capture"]["code"] == "ORIGIN_CONFLICT"
    recovered = hosts.handle_hook(receipt, native(project, "codex", prompt="later valid source", turn_id="turn-later"))
    assert recovered["capture"]["state"] == "committed"
    assert recovered["capture"]["quarantined"] == 1




def test_owned_reinstall_preserves_durable_producer_keys_and_pending_capture(installation):
    from agents_memory.domain import CaptureCommand

    project, settings, _, _, install = installation
    receipt = install()
    before = hosts.load_receipt(receipt)
    command = CaptureCommand(
        binding_id=before["binding_id"], idempotency_key="k" * 512, origin_key="o" * 512,
        body="Durable unchanged producer evidence.", speaker="human",
    )
    path = Path(before["runtime_dir"]) / "capture.sqlite3"
    spool = ProducerSpool(path, before["deployment_id"], before["binding_id"], before["spool_limit_bytes"])
    try:
        spool.enqueue(command)
    finally:
        spool.close()
    removed = hosts.uninstall_host(settings, project, "claude")
    assert removed["pending_spool_retained"] == str(path) and path.exists()
    after = hosts.load_receipt(install())
    assert after["runtime_dir"] == before["runtime_dir"]
    assert after["installation_id"] != before["installation_id"]
    reopened = ProducerSpool(path, after["deployment_id"], after["binding_id"], after["spool_limit_bytes"])
    try:
        assert reopened.status()["pending"] == 1
        assert reopened.enqueue(command) == {"state": "durably_spooled", "replay": True}
    finally:
        reopened.close()


@pytest.mark.parametrize("host,strict", [("claude", False), ("claude", True), ("codex", False), ("codex", True), ("omp", False)])
@pytest.mark.parametrize("raw", [
    b"{", b"[]", b'{"event":"tool_call","event":"input"}', b"\xff",
    b'{"hook_event_name":"PreToolUse","value":' + b"[" * 1500 + b"0" + b"]" * 1500 + b"}",
])
def test_malformed_native_stdin_is_a_structured_fail_safe(installation, host, strict, raw):
    _, _, _, _, install = installation
    result = hosts.handle_hook_input(install(host, strict=strict), raw)
    assert result["exit_code"] == 0 and result["stderr"] == ""
    assert result["code"] == "HOST_ENVELOPE_INVALID"
    assert result["state"] == ("blocked" if strict else "degraded")
    if strict and host == "claude":
        output = result["stdout"]
        assert output.get("continue") is False or output.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"
    elif strict:
        output = result["stdout"]
        assert output.get("decision") == "block" or output.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"
    else:
        assert "HOST_ENVELOPE_INVALID" in json.dumps(result["stdout"])


@pytest.mark.parametrize("host", ["claude", "codex", "omp"])
def test_oversized_native_stdin_has_no_cli_exception_path(installation, host):
    _, _, _, _, install = installation
    result = hosts.handle_hook_input(install(host), b" " * (hosts.HOST_INPUT_BYTES + 1))
    assert result["exit_code"] == 0
    assert result["code"] == "HOST_ENVELOPE_INVALID"
    assert result["state"] == ("degraded" if host == "omp" else "blocked")


@pytest.mark.parametrize("tool,body", [
    ("Write", {"content": "large-file\n" * 30000 + "\x00"}),
    ("Edit", {"old_string": "old\n" * 30000, "new_string": "new\n" * 30000}),
])
def test_large_native_file_body_is_not_an_authority_field(installation, authority, tool, body):
    project, _, _, _, install = installation
    receipt = install()
    hosts.handle_hook(receipt, native(project, prompt="prepare"))
    event = action(project)
    event.update(tool_name=tool, tool_input={"file_path": str(project / "src/example.py"), **body})
    raw = json.dumps(event).encode()
    assert len(raw) > 65536
    result = hosts.handle_hook_input(receipt, raw)
    assert result["state"] == "blocked"
    assert result["code"] == "HOST_PROVIDER_INPUT_UNOBSERVABLE"
    assert authority.calls[-1][2]["paths"] == ["src/example.py"]
    assert "large-file" not in json.dumps(result)


@pytest.mark.parametrize("tool,inputs,code", [
    ("Write", {"path": "src/wrong-schema.py", "content": "file body"}, "HOST_FOOTPRINT_UNKNOWN"),
    ("Edit", {"file_path": "../outside.py", "new_string": "large" * 20000}, "HOST_SCOPE_UNRESOLVED"),
    ("MultiEdit", {"file_path": "src/a.py", "edits": [{"old_string": "a", "new_string": "b"}]}, "HOST_FOOTPRINT_UNSUPPORTED"),
    ("MultiEdit", {"edits": [{"file_path": "src/a.py"}]}, "HOST_FOOTPRINT_UNSUPPORTED"),
])
def test_native_footprint_never_infers_an_unsupported_schema(installation, authority, tool, inputs, code):
    project, _, _, _, install = installation
    receipt = install()
    hosts.handle_hook(receipt, native(project, prompt="prepare"))
    event = action(project)
    event.update(tool_name=tool, tool_input=inputs)
    result = hosts.handle_hook_input(receipt, json.dumps(event).encode())
    assert result["state"] == "blocked" and result["code"] == code
    assert not any(call[0] == "/api/required-context" for call in authority.calls)


def test_oversized_authority_projection_is_not_silently_sliced(installation, authority):
    project, _, _, _, install = installation
    receipt = install()
    event = action(project)
    event["tool_input"] = {"file_path": "x" * hosts.HOST_PROJECTION_BYTES}
    result = hosts.handle_hook_input(receipt, json.dumps(event).encode())
    assert result["code"] == "HOST_ENVELOPE_INVALID"
    assert result["stdout"]["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert authority.calls == []


@pytest.mark.parametrize("host", ["claude", "codex", "omp"])
def test_current_bounded_context_marker_is_never_human_evidence(installation, authority, host):
    project, _, _, _, install = installation
    receipt = install(host, strict=False)
    event = native(project, host, "input" if host == "omp" else "UserPromptSubmit")
    event.update({
        "text" if host == "omp" else "prompt": hosts.BOUNDED_CONTEXT_MARKER + "\nretrieved rule",
        "source": "interactive",
    })
    result = hosts.handle_hook_input(receipt, json.dumps(event).encode())
    assert result["capture"]["state"] == "excluded"
    assert result["capture"]["code"] == "CAPTURE_INJECTED_REJECTED"
    assert not any(call[0] == "/api/capture" for call in authority.calls)


def test_corrupt_sqlite_capture_is_a_visible_durable_host_gap(installation, authority):
    project, _, _, _, install = installation
    receipt = install("omp")
    manifest = hosts.load_receipt(receipt)
    runtime = Path(manifest["runtime_dir"])
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = runtime / "capture.sqlite3"
    path.write_bytes(b"not a SQLite database")
    path.chmod(0o600)
    event = native(project, "omp", "input", source="interactive", text="actual ingress")
    first = hosts.handle_hook_input(receipt, json.dumps(event).encode())
    assert first["capture"]["code"] == "HOST_SPOOL_UNAVAILABLE"
    assert first["state"] == "degraded"
    assert first["gaps"]["HOST_SPOOL_UNAVAILABLE"] == 1
    again = hosts.handle_hook_input(receipt, json.dumps(event).encode())
    assert again["gaps"]["HOST_SPOOL_UNAVAILABLE"] == 2
    assert path.read_bytes() == b"not a SQLite database"
    assert not any(call[0] == "/api/capture" for call in authority.calls)


@pytest.mark.parametrize("boundary", ["enqueue", "flush", "status"])
def test_sqlite_runtime_failure_closes_capture_and_reports_gap(installation, authority, monkeypatch, boundary):
    project, _, _, _, install = installation
    receipt = install("omp")
    closed = []
    original_close = ProducerSpool.close

    def fail(self, *args, **kwargs):
        raise sqlite3.OperationalError("private raw database diagnostics")

    def close(self):
        closed.append(self.path)
        original_close(self)

    monkeypatch.setattr(ProducerSpool, boundary, fail)
    monkeypatch.setattr(ProducerSpool, "close", close)
    result = hosts.handle_hook(receipt, native(project, "omp", "input", source="interactive", text="actual ingress"))
    assert result["capture"]["code"] == "HOST_SPOOL_UNAVAILABLE"
    assert result["gaps"]["HOST_SPOOL_UNAVAILABLE"] == 1
    assert len(closed) == 1
    assert "private raw" not in json.dumps(result)


@pytest.mark.parametrize("host", ["claude", "omp"])
@pytest.mark.parametrize("other_identity", ["session", "agent"])
def test_network_wait_in_one_native_identity_does_not_lock_another(installation, authority, monkeypatch, host, other_identity):
    project, _, _, _, install = installation
    receipt = install(host, prompt_recall=True)
    waiting, release, finished = threading.Event(), threading.Event(), threading.Event()
    results = {}

    class DelayedContext(authority):
        def request(self, path, payload):
            if path == "/api/context":
                waiting.set()
                assert release.wait(5), "The test must release its bounded network wait"
            return super().request(path, payload)

    monkeypatch.setattr(hosts, "LocalClient", DelayedContext)

    def prepare():
        results["first"] = hosts.handle_hook(receipt, native(project, host, "before_agent_start" if host == "omp" else "UserPromptSubmit", prompt="waiting session"))

    def other_session():
        fields = {"session_id": "independent-session"} if other_identity == "session" else (
            {"agent": {"kind": "sub", "id": "independent-agent", "parentId": "main-agent", "depth": 1}}
            if host == "omp" else {"agent_id": "independent-agent"}
        )
        event = native(project, host, "session_start" if host == "omp" else "SessionStart", **fields)
        results["other"] = hosts.handle_hook(receipt, event)
        finished.set()

    first = threading.Thread(target=prepare)
    second = threading.Thread(target=other_session)
    first.start()
    try:
        assert waiting.wait(2)
        second.start()
        assert finished.wait(2), "An unrelated session must not wait behind a network-bound hook"
        assert results["other"]["generation"] == 1
    finally:
        release.set()
        first.join(5)
        if second.ident is not None:
            second.join(5)
    assert not first.is_alive() and not second.is_alive()
    assert results["first"]["generation"] == 1


def test_claude_local_mcp_entry_does_not_leak_into_shared_project_config(installation):
    project, settings, _, _, install = installation
    shared = project / ".mcp.json"
    shared_bytes = b'{"mcpServers":{"shared-company-server":{"command":"user-owned"}}}\n'
    shared.write_bytes(shared_bytes)
    local = hosts._claude_config_path()
    original = {
        "theme": "user-theme",
        "mcpServers": {"user-wide-server": {"command": "keep-user-server"}},
        "projects": {str(project): {"hasTrustDialogAccepted": False}, "/other/project": {"mcpServers": {"other": {"command": "keep-other"}}}},
    }
    local.write_text(json.dumps(original))
    receipt = install()
    document = json.loads(local.read_text())
    server = mcp_servers(document, project)[hosts.SERVER_NAME]
    assert server["args"][-2:] == ["--receipt", str(receipt)]
    assert document["projects"][str(project)]["hasTrustDialogAccepted"] is False
    assert shared.read_bytes() == shared_bytes
    document["user-new-field"] = {"preserve": True}
    local.write_text(json.dumps(document))
    unchanged = local.read_bytes()
    assert install() == receipt
    assert local.read_bytes() == unchanged
    hosts.uninstall_host(settings, project, "claude")
    assert json.loads(local.read_text()) == {**original, "user-new-field": {"preserve": True}}
    assert shared.read_bytes() == shared_bytes


def test_claude_linked_worktree_uses_native_project_without_widening_memory_scope(installation):
    project, settings, _, _, install = installation
    project.rmdir()
    main = project.parent / "canonical"
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    commands = [
        ["init", str(main)],
        ["-C", str(main), "commit", "--allow-empty", "-m", "isolated worktree fixture"],
        ["-C", str(main), "worktree", "add", "--detach", str(project)],
    ]
    for arguments in commands:
        subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", *arguments],
            check=True, capture_output=True, timeout=10, env=environment,
        )
    local = hosts._claude_config_path()
    original = {"projects": {str(main): {"hasTrustDialogAccepted": False}, "/unrelated": {"theme": "preserve"}}}
    local.write_text(json.dumps(original))
    receipt = install()
    manifest = hosts.load_receipt(receipt)
    assert hosts.SERVER_NAME in mcp_servers(json.loads(local.read_text()), main)
    assert manifest["project_root"] == str(project)
    relay = subprocess.run(
        [sys.executable, "-m", "agents_memory.cli", "host-stdio", "--receipt", str(receipt)],
        cwd=main, capture_output=True, text=True, timeout=10,
    )
    assert relay.returncode == 1
    assert relay.stdout == ""
    assert json.loads(relay.stderr)["error"]["code"] == "HOST_SCOPE_UNRESOLVED"
    assert not (project / ".mcp.json").exists()
    hosts.uninstall_host(settings, project, "claude")
    assert json.loads(local.read_text()) == original
    hosts.install_host(settings, project, "project-binding", "claude", installation[2], installation[3])
    assert hosts.SERVER_NAME in mcp_servers(json.loads(local.read_text()), main)
    hosts.uninstall_host(settings, project, "claude")
    assert json.loads(local.read_text()) == original


def test_claude_invalid_git_scope_does_not_register_a_guessed_native_project(installation):
    project, _, _, _, install = installation
    (project / ".git").write_text("gitdir: /missing/isolated/git-metadata\n")
    with pytest.raises(DomainError) as denied:
        install()
    assert denied.value.code == "HOST_NATIVE_SCOPE_UNRESOLVED"
    assert not hosts._claude_config_path().exists()
    assert not (project / ".mcp.json").exists()


@pytest.mark.parametrize("host", ["claude", "codex", "omp"])
def test_context_body_uses_shared_utf8_envelope_ceiling(installation, authority, host):
    project, _, _, _, install = installation
    receipt = install(host, strict=False, prompt_recall=True)
    manifest = hosts.load_receipt(receipt)
    budget = hosts.HOST_CONTEXT_BYTES - len(hosts.BOUNDED_CONTEXT_MARKER.encode()) - 1
    authority.text = "가" * (budget // 3)
    event = native(project, host, "before_agent_start" if host == "omp" else "UserPromptSubmit", prompt="bounded recall")
    result = hosts.handle_hook(receipt, event)
    output = result["stdout"]["additionalContext"] if host == "omp" else result["stdout"]["hookSpecificOutput"]["additionalContext"]
    assert len(output.encode()) <= hosts.HOST_CONTEXT_BYTES
    assert output.endswith(authority.text)
    assert manifest["context_budget_bytes"] == hosts.HOST_CONTEXT_BYTES
    if host == "codex":
        hooks = json.loads((project / ".codex/hooks.json").read_text())["hooks"]
        assert hooks["UserPromptSubmit"][0]["hooks"][0]["additionalContextLimit"] == hosts.HOST_CONTEXT_BYTES
    authority.text += "가"
    overflow = hosts.handle_hook(receipt, {**event, "prompt_id": "next-prompt", "turn_id": "next-turn", "adapter_turn_id": "next-attempt"})
    assert overflow["code"] == "REQUIRED_CONTEXT_OVERFLOW"
    assert authority.text not in json.dumps(overflow, ensure_ascii=False)




@pytest.mark.parametrize("shape", ["project", "projects", "servers"])
def test_uninstall_preserves_preexisting_empty_native_local_containers(installation, shape):
    project, settings, _, _, install = installation
    original = {"projects": {}} if shape == "projects" else {"projects": {str(project): {}}}
    if shape == "servers":
        original["projects"][str(project)]["mcpServers"] = {}
    local = hosts._claude_config_path()
    local.write_text(json.dumps(original))
    install()
    hosts.uninstall_host(settings, project, "claude")
    assert json.loads(local.read_text()) == original


def test_private_native_config_inside_project_is_rejected_before_install(installation, monkeypatch):
    project, _, _, _, install = installation
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(project / "private-native"))
    with pytest.raises(DomainError) as caught:
        install()
    assert caught.value.code == "HOST_NATIVE_CONFIG_PROJECT_DENIED"
    assert not (project / "private-native").exists()
    assert not (project / ".claude").exists()


def test_shared_private_native_config_serializes_distinct_installation_states(installation, monkeypatch):
    project, settings, agent, producer, install = installation
    second_project = project.parent / "second-project"
    second_project.mkdir()
    second_settings = settings.model_copy(update={
        "state_dir": project.parent / "second-state",
        "journal_dir": project.parent / "second-journal",
    })
    original = hosts._claude_entry
    first_planned, release, second_started, second_planned = (
        threading.Event(), threading.Event(), threading.Event(), threading.Event()
    )
    results, errors = {}, []

    def pause_first(plan, ownership, root, value):
        original(plan, ownership, root, value)
        if root == project:
            first_planned.set()
            assert release.wait(5)
        else:
            second_planned.set()

    monkeypatch.setattr(hosts, "_claude_entry", pause_first)

    def first_install():
        try:
            results["first"] = install()
        except BaseException as error:
            errors.append(error)

    def second_install():
        second_started.set()
        try:
            results["second"] = hosts.install_host(
                second_settings, second_project, "second-binding", "claude", agent, producer
            )
        except BaseException as error:
            errors.append(error)

    first = threading.Thread(target=first_install)
    second = threading.Thread(target=second_install)
    first.start()
    try:
        assert first_planned.wait(2)
        second.start()
        assert second_started.wait(2)
        assert not second_planned.wait(0.2)
    finally:
        release.set()
        first.join(5)
        if second.ident is not None:
            second.join(5)
    assert not first.is_alive() and not second.is_alive()
    assert not errors
    assert set(results) == {"first", "second"}
    document = json.loads(hosts._claude_config_path().read_text())
    assert hosts.SERVER_NAME in mcp_servers(document, project)
    assert hosts.SERVER_NAME in mcp_servers(document, second_project)


@pytest.mark.parametrize("existing_configuration", [False, True])
def test_omp_strict_refusal_precedes_every_installation_write(installation, existing_configuration):
    project, settings, agent, producer, _ = installation
    if existing_configuration:
        extension = project / ".omp/extensions/agents-memory.ts"
        extension.parent.mkdir(parents=True)
        extension.write_text("export default function () { /* user-owned */ }\n")
        (project / ".omp/mcp.json").write_text('{"mcpServers":{"existing":{"command":"user-owned"}}}\n')
    before = {path.relative_to(project): path.read_bytes() for path in project.rglob("*") if path.is_file()}
    with pytest.raises(DomainError) as caught:
        hosts.install_host(settings, project, "project-binding", "omp", agent, producer, strict=True)
    refusal = caught.value.public()
    assert refusal["code"] == "HOST_STRICT_UNSUPPORTED"
    assert "no fail-closed native pre-request gate" in refusal["message"]
    assert "before configuration writes" in refusal["message"]
    assert not settings.state_dir.exists()
    assert {path.relative_to(project): path.read_bytes() for path in project.rglob("*") if path.is_file()} == before
    capability = hosts.capabilities("omp", strict=True)
    assert capability["strict"] == "unsupported_refused"
    assert capability["first_action"] == "refused_before_installation"
    assert capability["startup_corpus_bytes"] == 0
    assert capability["prompt_context"] == "disabled"


def _historical_omp_strict_metadata(receipt):
    document = json.loads(receipt.read_text())
    document["strict"] = True
    document["capabilities"].update({
        "first_action": "deny_required_without_provider_input_evidence",
        "strict": "intercepted_actions_only",
        "native_failure": "registered_tool_hook_fail_closed",
    })
    hosts._write_receipt(receipt, document)
    return document


@pytest.mark.parametrize("prompt_recall", [False, True])
def test_historical_omp_strict_receipt_is_cleanup_only_then_advisory_reinstallable(installation, authority, prompt_recall):
    project, settings, _, _, install = installation
    mcp = project / ".omp/mcp.json"
    mcp.parent.mkdir()
    original = b'{"mcpServers":{"existing":{"command":"user-owned"}}}\n'
    mcp.write_bytes(original)
    receipt = install("omp", prompt_recall=prompt_recall)
    historical = _historical_omp_strict_metadata(receipt)
    before = {path.relative_to(project): path.read_bytes() for path in project.rglob("*") if path.is_file()}
    for options in ({}, {"allow_legacy": True}, {"active": False}):
        with pytest.raises(DomainError) as caught:
            hosts.load_receipt(receipt, **options)
        assert caught.value.code == "HOST_STRICT_UNSUPPORTED"
    cleanup = hosts.load_receipt(receipt, allow_legacy=True, active=False)
    assert cleanup["installation_id"] == historical["installation_id"]
    for strict in (False, True):
        with pytest.raises(DomainError) as caught:
            install("omp", strict=strict, prompt_recall=prompt_recall)
        assert caught.value.code == "HOST_STRICT_UNSUPPORTED"
    for event in (native(project, "omp", "before_agent_start", prompt="cannot enforce"), action(project, "omp")):
        result = hosts.handle_hook(receipt, event)
        assert result["state"] == "degraded"
        assert result["code"] == "HOST_STRICT_UNSUPPORTED"
        assert "block" not in result["stdout"]
    assert not authority.calls
    assert {path.relative_to(project): path.read_bytes() for path in project.rglob("*") if path.is_file()} == before
    assert hosts.uninstall_host(settings, project, "omp")["state"] == "uninstalled"
    assert json.loads(mcp.read_text()) == json.loads(original)
    assert not (project / ".omp/extensions/agents-memory.ts").exists()
    replacement = hosts.load_receipt(install("omp", prompt_recall=prompt_recall))
    assert replacement["strict"] is False
    assert replacement["installation_id"] != historical["installation_id"]
    assert replacement["capabilities"]["strict"] == "disabled"
    assert replacement["capabilities"]["startup_corpus_bytes"] == 0


@pytest.mark.parametrize("drift", ["capabilities", "extension"])
def test_historical_omp_strict_cleanup_preserves_unrecognized_or_drifted_ownership(installation, drift):
    project, settings, _, _, install = installation
    receipt = install("omp")
    document = _historical_omp_strict_metadata(receipt)
    extension = project / ".omp/extensions/agents-memory.ts"
    if drift == "capabilities":
        document["capabilities"]["native_failure"] = "invented_enforcement"
        hosts._write_receipt(receipt, document)
    else:
        extension.write_text("user-replaced extension\n")
    before = {path.relative_to(project): path.read_bytes() for path in project.rglob("*") if path.is_file()}
    with pytest.raises(DomainError) as caught:
        hosts.uninstall_host(settings, project, "omp")
    assert caught.value.code == ("HOST_RECEIPT_INVALID" if drift == "capabilities" else "HOST_OWNERSHIP_DRIFT")
    assert {path.relative_to(project): path.read_bytes() for path in project.rglob("*") if path.is_file()} == before


@pytest.mark.parametrize("boundary", ["pending_receipt", "first_config"])
def test_historical_omp_strict_partial_install_is_reversed_not_resumed_for_execution(installation, boundary):
    project, settings, agent, producer, install = installation
    mcp = project / ".omp/mcp.json"
    mcp.parent.mkdir()
    original = b'{"mcpServers":{"existing":{"command":"user-owned"}}}\n'
    mcp.write_bytes(original)
    receipt = hosts._receipt_path(settings, project, "omp")

    def crash():
        writer = hosts.private_write

        def write_and_exit(path, content, *, replace=False, **options):
            writer(path, content, replace=replace, **options)
            if path == (receipt if boundary == "pending_receipt" else mcp):
                os._exit(41)

        hosts.private_write = write_and_exit
        hosts.install_host(settings, project, "project-binding", "omp", agent, producer, strict=False)

    _abrupt_process(crash)
    _historical_omp_strict_metadata(receipt)
    assert hosts.load_receipt(receipt, allow_legacy=True, active=False)["state"] == "pending"
    with pytest.raises(DomainError) as caught:
        install("omp")
    assert caught.value.code == "HOST_STRICT_UNSUPPORTED"
    assert hosts.uninstall_host(settings, project, "omp")["state"] == "uninstalled"
    assert mcp.read_bytes() == original
    assert not (project / ".omp/extensions/agents-memory.ts").exists()
    assert hosts.load_receipt(install("omp"))["strict"] is False
