from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import multiprocessing
import os
import shlex
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import tomllib
from pathlib import Path

import pytest
from test_spool_boundaries import capture_authority as capture_authority

from agents_memory import hosts, private_io
from agents_memory.config import Settings
from agents_memory.context import compose
from agents_memory.domain import (
    ActiveRule,
    CaptureCommand,
    ContextCommand,
    DomainError,
    EffectState,
    RuleScope,
    Selector,
    canonical_digest,
)
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

    def install(host="claude", strict=None, prompt_recall=False, recall_mode="inline", recall_trial_days=14, action_recall=None):
        strict = host == "claude" if strict is None else strict
        result = hosts.install_host(
            settings, project, "project-binding", host, agent, producer, strict=strict,
            prompt_recall=prompt_recall, recall_mode=recall_mode, recall_trial_days=recall_trial_days,
            action_recall=action_recall,
        )
        return Path(result["receipt"])

    return project, settings, agent, producer, install


@pytest.fixture
def authority(monkeypatch):
    class Endpoint:
        required = True
        stamp = {"epoch": 1, "rules": [["rule-one", 1, hashlib.sha256(b"rule-one").hexdigest()]]}
        text = '{"approved_rules":[],"memory_candidates":[],"relations":[]}'
        active_rules = None
        context_error = None
        capture_error = "SERVICE_UNAVAILABLE"
        calls = []

        def __init__(self, base_url, token_file, timeout=120, *, state_dir=None, deployment_id=None, remote_settings=None):
            self.token_file = token_file

        def request(self, path, payload):
            self.calls.append((path, self.token_file, payload))
            if path == "/api/capture":
                if self.capture_error:
                    raise DomainError(self.capture_error, "No raw request diagnostics")
                return {"effect": "committed", "id": "operation-one"}
            if self.context_error:
                raise DomainError(self.context_error, "No raw rule diagnostics")
            if self.active_rules is not None:
                composed = compose(
                    ContextCommand.model_validate(payload), self.active_rules, (), (),
                    protected_action=path == "/api/required-context",
                )
                result = {
                    "context": composed.text, "context_bytes": composed.byte_count,
                    "stamp": {"epoch": 1, "rules": [list(rule) for rule in composed.rule_versions]},
                }
                if path == "/api/required-context":
                    result["required"] = bool(composed.rule_versions)
                return result
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


@pytest.mark.parametrize("lifecycle", ["session_switch", "session_branch", "session_tree"])
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


@pytest.mark.parametrize("code", ["RULE_APPLICABILITY_UNKNOWN", "REQUIRED_CONTEXT_OVERFLOW", "CREDENTIAL_REVOKED", "SERVICE_UNAVAILABLE", "SERVICE_STOPPED"])
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
    authority.stamp = {"epoch": 2, "rules": [["rule-one", 2, hashlib.sha256(b"rule-two").hexdigest()]]}
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


@pytest.mark.parametrize("host", ["claude", "codex", "omp"])
def test_advisory_scope_outside_project_is_silent_and_never_attributed(installation, authority, host, tmp_path):
    project, _, _, _, install = installation
    receipt = install(host, strict=False)
    outside = tmp_path / "elsewhere" / "notes.md"
    events = []
    if host != "codex":
        entirely = action(project, host)
        entirely["tool_input"] = {"file_path" if host == "claude" else "path": str(outside)}
        result = hosts.handle_hook(receipt, entirely)
        assert (result["state"], result["code"], result["stdout"]) == ("outside_advisory_coverage", None, {})
        events.append(dict(entirely, cwd=str(tmp_path)))
    prompt_event = "before_agent_start" if host == "omp" else "UserPromptSubmit"
    events.append(native(project, host, prompt_event, prompt="session started outside the registered project",
                         cwd=str(tmp_path)))
    if host == "omp":
        events.append(native(project, host, "input", text="ingress outside the project", source="interactive",
                             cwd=str(tmp_path)))
    for event in events:
        outside_cwd = hosts.handle_hook(receipt, event)
        assert (outside_cwd["state"], outside_cwd["code"], outside_cwd["stdout"]) == (
            "outside_advisory_coverage", None, {})
        assert "capture" not in outside_cwd
    if host == "omp":
        explicit = hosts.handle_hook(receipt, native(project, host, "capture_finding", text="explicit finding",
                                                     cwd=str(tmp_path)))
        assert (explicit["state"], explicit["code"]) == ("outside_advisory_coverage", None)
        assert explicit["capture"] == {"state": "not_captured", "reason": "session_outside_registered_project"}
    assert authority.calls == []
    runtime = Path(hosts.load_receipt(receipt)["runtime_dir"])
    assert not list(runtime.glob("*.json")) and not list(runtime.glob("*.sqlite3"))
    missing = native(project, host, prompt_event, prompt="cwd removed", cwd=str(tmp_path / "removed"))
    assert hosts.handle_hook(receipt, missing)["code"] == "HOST_SCOPE_UNRESOLVED"


def test_overflow_is_not_truncated_into_success(installation, authority):
    project, _, _, _, install = installation
    receipt = install(prompt_recall=True)
    authority.text = "required rule body " * 300
    result = hosts.handle_hook(receipt, native(project, prompt="prepare"))
    assert result["state"] == "blocked"
    assert result["code"] == "REQUIRED_CONTEXT_OVERFLOW"
    assert "required rule body" not in json.dumps(result)


@pytest.mark.parametrize("host,event_name,strict", [
    ("claude", "PreToolUse", True), ("claude", "UserPromptSubmit", True),
    ("claude", "", True), ("codex", "", True),
    ("claude", "UserPromptSubmit", False), ("codex", "UserPromptSubmit", False),
    ("omp", "before_agent_start", False),
])
@pytest.mark.parametrize("extra_bytes", [0, 1])
def test_native_delivery_guard_bounds_every_supported_context_output(host, event_name, strict, extra_bytes):
    budget = 512
    code = "HOST_PROVIDER_INPUT_UNOBSERVABLE"
    prefix = (code + "\n" if strict else "") + hosts.BOUNDED_CONTEXT_MARKER + "\n"
    body_bytes = budget - len(prefix.encode())
    body = "가" * (body_bytes // 3) + "x" * (body_bytes % 3 + extra_bytes)
    result = hosts._native_result(host, event_name, code=code, text=body, strict=strict, max_bytes=budget)
    assert result["exit_code"] == 0
    output = result["stdout"]
    if extra_bytes:
        assert result["code"] == "REQUIRED_CONTEXT_OVERFLOW"
        assert body not in json.dumps(result, ensure_ascii=False)
        if strict:
            if event_name == "PreToolUse":
                assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
            elif host == "claude" and not event_name:
                assert output["continue"] is False
            else:
                assert output["decision"] == "block"
    else:
        if strict:
            delivered = output["hookSpecificOutput"]["permissionDecisionReason"] if event_name == "PreToolUse" else output["stopReason"] if host == "claude" and not event_name else output["reason"]
        else:
            delivered = output["additionalContext"] if host == "omp" else output["hookSpecificOutput"]["additionalContext"]
        assert delivered == prefix + body
        assert len(delivered.encode()) == budget


@pytest.mark.parametrize("budget", [512, hosts.HOST_CONTEXT_BYTES])
@pytest.mark.parametrize("stale", [False, True])
@pytest.mark.parametrize("extra_bytes", [0, 1, 3])
def test_strict_action_composes_complete_required_body_with_denial_prefix_budget(installation, authority, budget, stale, extra_bytes):
    project, _, _, _, install = installation
    receipt = install(prompt_recall=True)
    manifest = hosts.load_receipt(receipt)
    manifest["context_budget_bytes"] = budget
    hosts._write_receipt(receipt, manifest)
    rule = ActiveRule(
        id="rule-one", revision=1, digest=hashlib.sha256(b"rule-one").hexdigest(),
        body="", selector=Selector(), exceptions=(), required=True,
        scope=RuleScope.LOCAL_PROJECT, target_bindings=("project-binding",), source_ids=("source-one",),
    )
    sizing_command = ContextCommand(
        binding_id="project-binding", query="Protected action conventions",
        paths=("src/example.py",), host="claude", max_bytes=6144,
    )
    empty_size = compose(sizing_command, (rule,), (), (), protected_action=True).byte_count
    reserved_code = "HOST_PROVIDER_INPUT_UNOBSERVABLE"
    body_budget = budget - len((reserved_code + "\n" + hosts.BOUNDED_CONTEXT_MARKER + "\n").encode()) - empty_size
    body = "가" * (body_budget // 3) + "x" * (body_budget % 3 + extra_bytes)
    rule = rule.model_copy(update={"body": body, "digest": hashlib.sha256(body.encode()).hexdigest()})
    authority.active_rules = (rule,)
    prepared = hosts.handle_hook(receipt, native(project, prompt="prepare complete rules"))
    assert prepared["offered"] is True
    if stale:
        rule = rule.model_copy(update={"revision": 2})
        authority.active_rules = (rule,)
    result = hosts.handle_hook_input(receipt, json.dumps(action(project)).encode())
    assert result["exit_code"] == 0 and result["state"] == "blocked"
    native_output = result["stdout"]["hookSpecificOutput"]
    assert native_output["permissionDecision"] == "deny"
    reason = native_output["permissionDecisionReason"]
    assert len(reason.encode()) <= budget
    if extra_bytes:
        assert result["code"] == "REQUIRED_CONTEXT_OVERFLOW"
        assert reason == "REQUIRED_CONTEXT_OVERFLOW"
        assert body not in json.dumps(result, ensure_ascii=False)
    else:
        assert result["code"] == ("HOST_CONTEXT_STALE" if stale else reserved_code)
        delivered = json.loads(reason.split(hosts.BOUNDED_CONTEXT_MARKER + "\n", 1)[1])
        assert delivered["approved_rules"][0]["body"] == body
        assert delivered["approved_rules"][0]["revision"] == rule.revision
        assert len(reason.encode()) == budget - (len(reserved_code) - len(result["code"]))


def test_strict_action_rejects_service_text_that_fits_only_the_marker_budget(installation, authority):
    project, _, _, _, install = installation
    receipt = install()
    hosts.handle_hook(receipt, native(project, prompt="prepare"))
    marker_budget = hosts.HOST_CONTEXT_BYTES - len((hosts.BOUNDED_CONTEXT_MARKER + "\n").encode())
    authority.text = "가" * (marker_budget // 3) + "x" * (marker_budget % 3)
    result = hosts.handle_hook(receipt, action(project))
    assert result["exit_code"] == 0 and result["state"] == "blocked"
    output = result["stdout"]["hookSpecificOutput"]
    assert output["permissionDecision"] == "deny"
    assert output["permissionDecisionReason"] == "REQUIRED_CONTEXT_OVERFLOW"
    assert authority.text not in json.dumps(result, ensure_ascii=False)
    assert len(output["permissionDecisionReason"].encode()) <= hosts.HOST_CONTEXT_BYTES


@pytest.mark.parametrize("field,value", [
    ("generation", True), ("generation", -1), ("generation", 1.0), ("generation", 2**63),
    ("turn", []), ("turn", ""), ("turn", 7),
    ("offered", []), ("offered", {"rules": [], "body": "malformed-source-private"}),
    ("offered", {"rules": [{}], "digest": "a" * 64, "generation": 1}),
    ("offered", {"rules": [["rule-one", True, "b" * 64]], "digest": "a" * 64, "generation": 1}),
    ("offered", {"rules": [["rule-one", 1, []]], "digest": "a" * 64, "generation": 1}),
    ("offered", {"rules": [[[], 1, "b" * 64]], "digest": "a" * 64, "generation": 1}),
    ("offered", {"rules": [], "digest": [], "generation": 1}),
    ("offered", {"rules": [], "digest": "a" * 64, "generation": True}),
    ("offered", {"rules": [], "digest": "a" * 64, "generation": 0}),
    ("gaps", []), ("gaps", {"malformed-source-private": []}),
    ("gaps", {"capture": True}), ("gaps", {"capture": -1}), ("gaps", {"capture": 0.0}),
    ("gaps", {"capture": 2**63}),
    ("capture", {"key": "capture-one", "generation": True}),
    ("capture", {"key": "capture-one", "generation": 0}),
    ("capture", {"key": "", "generation": 1}),
    ("capture", {"key": "capture-one", "generation": 1, "body": "malformed-source-private"}),
])
@pytest.mark.parametrize("event_name", ["PreToolUse", "UserPromptSubmit"])
def test_malformed_durable_generation_state_returns_body_free_native_refusal(installation, authority, field, value, event_name):
    project, _, _, _, install = installation
    receipt = install(prompt_recall=True)
    hosts.handle_hook(receipt, native(project, prompt="prepare"))
    runtime = Path(hosts.load_receipt(receipt)["runtime_dir"])
    state_path = next(runtime.glob("*.json"))
    state = json.loads(state_path.read_text())
    state[field] = value
    raw = json.dumps(state).encode()
    state_path.write_bytes(raw)
    authority.calls.clear()
    event = action(project) if event_name == "PreToolUse" else native(project, prompt="source-private-do-not-leak")
    result = hosts.handle_hook(receipt, event)
    assert result["exit_code"] == 0 and result["state"] == "blocked"
    assert result["code"] == "HOST_STATE_INVALID"
    if event_name == "PreToolUse":
        output = result["stdout"]["hookSpecificOutput"]
        assert output["permissionDecision"] == "deny"
        assert output["permissionDecisionReason"] == "HOST_STATE_INVALID"
    else:
        assert result["stdout"] == {"decision": "block", "reason": "HOST_STATE_INVALID"}
    assert state_path.read_bytes() == raw
    assert authority.calls == []
    encoded = json.dumps(result)
    assert "source-private" not in encoded and authority.text not in encoded


@pytest.mark.parametrize("raw", [b"{}", b"[]", b'{"generation":0,"generation":1}', b'{"generation":'])
def test_invalid_generation_document_is_not_silently_reset(installation, authority, raw):
    project, _, _, _, install = installation
    receipt = install()
    hosts.handle_hook(receipt, native(project, prompt="prepare"))
    state_path = next(Path(hosts.load_receipt(receipt)["runtime_dir"]).glob("*.json"))
    state_path.write_bytes(raw)
    result = hosts.handle_hook(receipt, action(project))
    assert result["exit_code"] == 0 and result["code"] == "HOST_STATE_INVALID"
    assert result["stdout"]["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert state_path.read_bytes() == raw


def test_valid_generation_state_retains_gaps_and_invalidates_offers_on_lifecycle(installation, authority):
    project, _, _, _, install = installation
    receipt = install(prompt_recall=True)
    prompt = native(project, prompt="prepare")
    first = hosts.handle_hook(receipt, prompt)
    repeated = hosts.handle_hook(receipt, prompt)
    assert first["generation"] == repeated["generation"] == 1
    assert repeated["gaps"]["HOST_PROMPT_ORIGIN_UNOBSERVABLE"] == 2
    runtime = Path(hosts.load_receipt(receipt)["runtime_dir"])
    state_path = next(runtime.glob("*.json"))
    state = json.loads(state_path.read_text())
    assert state["offered"]["generation"] == 1
    transition = hosts.handle_hook(receipt, native(project, event="PreCompact"))
    assert transition["generation"] == 2
    state = json.loads(state_path.read_text())
    assert state["turn"] is None and state["offered"] is None
    assert state["gaps"] == repeated["gaps"]
    refused = hosts.handle_hook(receipt, action(project))
    assert refused["code"] == "HOST_GENERATION_UNOBSERVED"
    assert refused["stdout"]["hookSpecificOutput"]["permissionDecision"] == "deny"
    renewed = hosts.handle_hook(receipt, native(project, prompt_id="prompt-two", prompt="prepare renewed"))
    assert renewed["generation"] == 3 and renewed["offered"] is True
    assert hosts.handle_hook(receipt, action(project, prompt_id="prompt-two"))["code"] == "HOST_PROVIDER_INPUT_UNOBSERVABLE"


def test_absent_receipt_returns_native_deny_not_fail_open_exception(tmp_path):
    result = hosts.handle_hook(tmp_path / "claude.json", {"hook_event_name": "PreToolUse"})
    assert result["stdout"]["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert result["code"] == "HOST_RECEIPT_UNAVAILABLE"


@pytest.mark.parametrize("location", ["tool_path", "cwd"])
@pytest.mark.parametrize("strict", [False, True])
def test_symlink_loop_native_input_and_cli_emit_body_free_denial_or_advisory_warning(installation, location, strict):
    project, _, _, _, install = installation
    receipt = install(strict=strict)
    hosts.handle_hook(receipt, native(project, event="SessionStart"))
    hosts.handle_hook(receipt, native(project, prompt=""))
    loop = project / "loop"
    loop.symlink_to("loop")
    event = action(project)
    if location == "tool_path":
        event["tool_input"] = {"file_path": str(loop / "src/x.py"), "content": "private-native-body"}
    else:
        event["cwd"] = str(loop / "src")
    raw = json.dumps(event).encode()
    manifest = hosts.load_receipt(receipt)
    runtime = Path(manifest["runtime_dir"])
    before = {path.name: path.read_bytes() for path in runtime.glob("*.json")}

    result = hosts.handle_hook_input(receipt, raw)
    assert result["exit_code"] == 0 and result["stderr"] == ""
    assert result["state"] == ("blocked" if strict else "degraded")
    assert result["code"] == "HOST_ADAPTER_UNAVAILABLE"
    process = subprocess.run(
        [sys.executable, "-m", "agents_memory.cli", "host-hook", "--receipt", str(receipt)],
        input=raw, capture_output=True, timeout=10,
    )
    assert process.returncode == 0 and process.stderr == b""
    stdout = json.loads(process.stdout)
    assert stdout == result["stdout"]
    if strict:
        assert stdout["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert stdout["hookSpecificOutput"]["permissionDecisionReason"] == "HOST_ADAPTER_UNAVAILABLE"
    else:
        assert stdout == {"systemMessage": "agents-memory: HOST_ADAPTER_UNAVAILABLE"}
    assert "private-native-body" not in json.dumps(result) + process.stdout.decode()
    assert {path.name: path.read_bytes() for path in runtime.glob("*.json")} == before
    assert not (project / "src/x.py").exists()


@pytest.mark.parametrize("raw", [b"{", b'{"hook_event_name":"PreToolUse"}'])
def test_invalid_receipt_path_input_returns_native_refusal_without_exception(raw):
    result = hosts.handle_hook_input(None, raw)
    assert result["exit_code"] == 0 and result["stderr"] == ""
    assert result["state"] == "blocked" and result["code"] == "HOST_RECEIPT_UNAVAILABLE"
    if raw == b"{":
        assert result["stdout"] == {"continue": False, "stopReason": "HOST_RECEIPT_UNAVAILABLE"}
    else:
        assert result["stdout"]["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_unexpected_hook_state_publication_failure_denies_without_reset_or_private_error(installation, monkeypatch):
    project, _, _, _, install = installation
    receipt = install()
    event = native(project, event="SessionStart")
    hosts.handle_hook(receipt, event)
    manifest = hosts.load_receipt(receipt)
    state_path = Path(manifest["runtime_dir"]) / (hosts._identity(manifest, event)["key"] + ".json")
    before = state_path.read_bytes()

    def fail_publication(*args, **kwargs):
        raise RuntimeError("private-native-diagnostic")

    monkeypatch.setattr(hosts, "private_write", fail_publication)
    result = hosts.handle_hook_input(receipt, json.dumps(native(project, prompt="")).encode())
    assert result["stdout"]["decision"] == "block"
    assert result["code"] == "HOST_ADAPTER_UNAVAILABLE"
    assert result["exit_code"] == 0 and result["stderr"] == ""
    assert state_path.read_bytes() == before
    assert "private-native-diagnostic" not in json.dumps(result)


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
    bodies = [body["body"] for path, _, body in authority.calls if path == "/api/capture"]
    assert set(bodies) == {"a genuine ingress message"}
    sent = len(bodies)
    excluded = hosts.handle_hook(receipt, {**event, "text": hosts.BOUNDED_CONTEXT_MARKER + " retrieved memory"})
    assert excluded["capture"]["state"] == "excluded"
    assert len([call for call in authority.calls if call[0] == "/api/capture"]) == sent


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


@pytest.mark.parametrize("host,strict", [
    ("claude", False), ("claude", True), ("codex", False), ("omp", False), ("omp", True),
])
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
    ("capability", None), ("capability", "semantic"), ("capability", "lexical_entity"),
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


def _crash_host_mutation(operation, args, options, crash_path, crash_state, new_intent_except):
    writer = hosts.private_write
    unlink = hosts._unlink

    def exit_at_boundary(path, content=None):
        if new_intent_except is not None:
            if content is None or not path.name.startswith("ownership-") or path == new_intent_except:
                return
        elif path != crash_path or (
            crash_state is not None and (content is None or json.loads(content)["state"] != crash_state)
        ):
            return
        os._exit(41)

    def write_and_exit(path, content, *, replace=False, **kwargs):
        writer(path, content, replace=replace, **kwargs)
        exit_at_boundary(path, content)

    def unlink_and_exit(path, **kwargs):
        unlink(path, **kwargs)
        exit_at_boundary(path)

    hosts.private_write = write_and_exit
    hosts._unlink = unlink_and_exit
    operation(*args, **options)


def _abrupt_process(operation, *args, crash_path=None, crash_state=None, new_intent_except=None, **options):
    process = multiprocessing.get_context("spawn").Process(
        target=_crash_host_mutation,
        args=(operation, args, options, crash_path, crash_state, new_intent_except),
    )
    try:
        process.start()
        process.join(10)
        if process.is_alive():
            pytest.fail("Owned mutation never reached its deterministic crash point")
        assert process.exitcode == 41
    finally:
        if process.is_alive():
            process.kill()
            process.join()
        process.close()
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

    _abrupt_process(
        hosts.install_host, settings, project, "project-binding", host, agent, producer,
        crash_path=mcp if boundary == "first_config" else receipt_path,
        crash_state="installed" if boundary == "installed_receipt" else None,
        strict=host == "claude",
    )
    pending = hosts.load_receipt(receipt_path, active=False)
    assert pending["state"] == ("installed" if boundary == "installed_receipt" else "pending")
    expected_state = "degraded" if host == "omp" else (
        "outside_advisory_coverage" if host == "codex" and boundary == "installed_receipt" else "blocked"
    )
    assert hosts.handle_hook(receipt_path, action(project, host))["state"] == expected_state
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


@pytest.mark.parametrize("host,historical_omp_strict", [
    ("claude", False), ("codex", False), ("omp", False), ("omp", True),
])
@pytest.mark.parametrize("boundary", ["removing_receipt", "first_config", "removed_receipt"])
@pytest.mark.parametrize("historical_v4", [False, True])
def test_process_death_uninstall_resumes_removal_and_preserves_other_entries(installation, host, boundary, historical_v4, historical_omp_strict):
    project, settings, _, _, install = installation
    user = project / "AF-owned.json"
    user.write_text("preserve user and AF\n")
    receipt_path = install(host)
    if historical_omp_strict:
        _historical_omp_strict_metadata(receipt_path)
    manifest = _historical_v4_metadata(receipt_path) if historical_v4 else hosts.load_receipt(receipt_path, allow_legacy=historical_omp_strict, active=False)
    first = project / manifest["ownership"][0]["path"]

    _abrupt_process(
        hosts.uninstall_host, settings, project, host,
        crash_path=first if boundary == "first_config" else receipt_path,
        crash_state=None if boundary == "first_config" else boundary.removesuffix("_receipt"),
    )
    interrupted = hosts.load_receipt(receipt_path, allow_legacy=historical_v4 or historical_omp_strict, active=False)
    assert interrupted["state"] == ("removed" if boundary == "removed_receipt" else "removing")
    if historical_v4:
        assert "capability" not in interrupted and interrupted["capabilities"] == manifest["capabilities"]
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
    replacement = hosts.load_receipt(install(host))
    assert replacement["installation_id"] != manifest["installation_id"]
    assert replacement["capability"] == settings.capability


@pytest.mark.parametrize("boundary", ["pending_receipt", "first_config"])
@pytest.mark.parametrize("recover", ["install", "cancel"])
def test_interrupted_claude_install_preserves_unowned_updates(installation, boundary, recover):
    project, settings, agent, producer, install = installation
    native = hosts._claude_config_path()
    receipt = hosts._receipt_path(settings, project, "claude")

    _abrupt_process(
        hosts.install_host, settings, project, "project-binding", "claude", agent, producer,
        crash_path=receipt if boundary == "pending_receipt" else native, strict=True,
    )
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

    _abrupt_process(
        hosts.install_host, settings, project, "project-binding", "claude", agent, producer,
        crash_path=receipt if boundary == "pending_receipt" else native, strict=True,
    )
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

    _abrupt_process(
        hosts.uninstall_host, settings, project, "claude",
        crash_path=native if boundary == "first_config" else receipt,
        crash_state=None if boundary == "first_config" else "removing",
    )
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

    if operation == "remove":
        _abrupt_process(hosts.uninstall_host, settings, project, "claude", crash_path=receipt, crash_state="removing")
    else:
        _abrupt_process(
            hosts.install_host, settings, project, "project-binding", "claude", agent, producer,
            crash_path=receipt, crash_state="pending", strict=True,
        )
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


@pytest.mark.parametrize("change", ["receipt_replaced", "root_moved"])
def test_refused_legacy_cleanup_after_applied_removal_reports_unknown_effect(installation, monkeypatch, change):
    project, settings, _, _, install = installation
    legacy = project / ".agents-memory/hosts/codex.json"
    with monkeypatch.context() as patch:
        patch.setattr(hosts, "_receipt_path", lambda _settings, _root, _host: legacy)
        install("codex", strict=False)
    document = json.loads(legacy.read_text())
    document.pop("ownership_digest")
    document.pop("state")
    document["adapter_version"] = 1
    document["ownership_digest"] = canonical_digest(document)
    legacy.write_text(json.dumps(document))
    moved, resolved_legacy = project.parent / "moved-away", legacy.resolve()
    apply, unlink = hosts._apply, hosts._unlink

    def replace_legacy_after_apply(*args):
        apply(*args)
        legacy.unlink()
        legacy.mkdir()

    def move_root_after_legacy_cleanup(path, **options):
        unlink(path, **options)
        if path == resolved_legacy:
            project.rename(moved)

    if change == "receipt_replaced":
        monkeypatch.setattr(hosts, "_apply", replace_legacy_after_apply)
    else:
        monkeypatch.setattr(hosts, "_unlink", move_root_after_legacy_cleanup)
    with pytest.raises(DomainError) as refused:
        hosts.uninstall_host(settings, project, "codex")
    expected = "HOST_CONFIG_INVALID" if change == "receipt_replaced" else "HOST_CONFIG_DRIFT"
    assert refused.value.code == expected and refused.value.effect == EffectState.UNKNOWN
    assert not ((project if change == "receipt_replaced" else moved) / ".codex/hooks.json").exists()
    receipt_path = hosts._receipt_path(settings, project, "codex")
    assert hosts.load_receipt(receipt_path, active=False, allow_deleted_project=change == "root_moved")["state"] == "removing"


def test_refused_rollback_after_partial_removal_reports_unknown_effect(installation, monkeypatch):
    project, settings, _, _, install = installation
    receipt_path = install("codex", strict=False)
    outside = project.parent / "outside"
    outside.write_text("unowned")
    unlink, removed = hosts._unlink, []

    def fail_second_project_removal(path, **options):
        if options.get("directory") is None:
            return unlink(path, **options)
        if removed:
            removed[0].symlink_to(outside)
            raise OSError("injected removal failure")
        unlink(path, **options)
        removed.append(path)

    monkeypatch.setattr(hosts, "_unlink", fail_second_project_removal)
    with pytest.raises(DomainError) as refused:
        hosts.uninstall_host(settings, project, "codex")
    assert refused.value.code == "HOST_PATH_DENIED" and refused.value.effect == EffectState.UNKNOWN
    assert hosts.load_receipt(receipt_path, active=False)["state"] == "removing"
    assert outside.read_text() == "unowned"


def test_native_publication_with_lost_lease_reports_unknown_effect(installation, monkeypatch):
    project, settings, _, _, install = installation
    receipt_path = install("claude", strict=False)
    writer_lock = hosts._claude_writer_lock

    @contextlib.contextmanager
    def lease_lost_after_publication(path):
        with writer_lock(path) as check:
            calls = []

            def checked():
                calls.append(path)
                # _claude_apply checks twice, once more before publishing, then after it.
                if len(calls) == 4:
                    raise DomainError("HOST_CONFIG_LOCK_LOST", "The native writer lease changed; reconcile ownership")
                check()

            yield checked

    monkeypatch.setattr(hosts, "_claude_writer_lock", lease_lost_after_publication)
    with pytest.raises(DomainError) as lost:
        hosts.uninstall_host(settings, project, "claude")
    assert lost.value.code == "HOST_CONFIG_LOCK_LOST" and lost.value.effect == EffectState.UNKNOWN
    document = json.loads(hosts._claude_config_path().read_text())
    assert hosts.SERVER_NAME not in document.get("projects", {}).get(str(project), {}).get("mcpServers", {})
    assert hosts.load_receipt(receipt_path, active=False)["state"] == "removing"


@pytest.mark.parametrize("operation", ["install", "uninstall"])
def test_refused_receipt_write_after_intent_publication_reports_unknown_effect(installation, monkeypatch, operation):
    project, settings, agent, producer, install = installation
    receipt_path = hosts._receipt_path(settings, project.resolve(), "codex")
    if operation == "uninstall":
        install("codex", strict=False)
    outside = project.parent / "outside-receipt"
    outside.write_text("unowned")
    writer = hosts.private_write

    def replace_receipt_after_intent(path, content, **options):
        writer(path, content, **options)
        if path.name.startswith("ownership-"):
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            receipt_path.unlink(missing_ok=True)
            receipt_path.symlink_to(outside)

    monkeypatch.setattr(hosts, "private_write", replace_receipt_after_intent)
    with pytest.raises(DomainError) as refused:
        if operation == "install":
            hosts.install_host(settings, project, "project-binding", "codex", agent, producer, strict=False)
        else:
            hosts.uninstall_host(settings, project, "codex")
    assert refused.value.code == "PATH_DENIED" and refused.value.effect == EffectState.UNKNOWN
    assert outside.read_text() == "unowned"


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
    assert recovered["state"] == "ok"
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

    _abrupt_process(hosts.install_host, settings, project, "project-binding", "claude", agent, producer, crash_path=first)
    pending = hosts.load_receipt(receipt_path, active=False)
    original_intent = hosts._intent_path(pending)

    _abrupt_process(hosts.uninstall_host, settings, project, "claude", new_intent_except=original_intent)
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


@pytest.mark.parametrize("host,strict", [("claude", False), ("claude", True), ("codex", False), ("omp", False)])
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
    else:
        assert "HOST_ENVELOPE_INVALID" in json.dumps(result["stdout"])


@pytest.mark.parametrize("host,strict", [("claude", True), ("codex", False), ("omp", False)])
def test_oversized_native_stdin_has_no_cli_exception_path(installation, host, strict):
    _, _, _, _, install = installation
    result = hosts.handle_hook_input(install(host, strict=strict), b" " * (hosts.HOST_INPUT_BYTES + 1))
    assert result["exit_code"] == 0
    assert result["code"] == "HOST_ENVELOPE_INVALID"
    assert result["state"] == ("blocked" if strict else "degraded")


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


@pytest.mark.asyncio
async def test_claude_linked_worktree_mcp_uses_credential_binding_not_cwd(installation, capture_authority):
    from urllib.request import urlopen

    import uvicorn
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    from agents_memory.domain import Role
    from agents_memory.edge import create_app

    project, _, agent, producer, _ = installation
    store, actor, binding = capture_authority
    agent.write_text("mcp-worktree-agent-" + "a" * 32 + "\n")
    await store.issue_token(actor, Role.AGENT, (binding,), agent.read_text().strip())
    body = "The project retains CacheKey only offline."
    operation = await store.capture(actor, CaptureCommand(
        binding_id=binding, idempotency_key="cwd-source", origin_key="cwd-source",
        body=body, speaker="human",
    ))
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
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    settings = store.settings.model_copy(update={"port": listener.getsockname()[1]})
    settings.state_dir.mkdir(mode=0o700, exist_ok=True)
    settings.state_dir.chmod(0o700)
    receipt = Path(hosts.install_host(
        settings, project, binding, "claude", agent, producer, strict=False,
    )["receipt"])
    manifest = hosts.load_receipt(receipt)
    assert hosts.SERVER_NAME in mcp_servers(json.loads(local.read_text()), main)
    assert manifest["project_root"] == str(project)
    native_server = mcp_servers(json.loads(local.read_text()), main)[hosts.SERVER_NAME]
    server = uvicorn.Server(uvicorn.Config(create_app(settings), access_log=False, log_level="error"))
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        response = await asyncio.to_thread(urlopen, f"http://127.0.0.1:{settings.port}/healthz", timeout=10)
        with response:
            assert response.status == 200
        for cwd in (main, project):
            parameters = StdioServerParameters(
                command=native_server["command"],
                args=native_server["args"],
                cwd=cwd,
            )
            async with asyncio.timeout(20):
                async with stdio_client(parameters) as (reader, writer):
                    async with ClientSession(reader, writer) as session:
                        await session.initialize()
                        result = await session.call_tool("memory_inspect", {
                            "binding_id": binding, "ref": operation.source_id,
                        })
                        inspected = json.loads(result.content[0].text)
                        assert inspected["span_inventory"][0]["quote"] == body
                        denied = await session.call_tool("memory_inspect", {
                            "binding_id": "another-project", "ref": operation.source_id,
                        })
                        refusal = json.loads(denied.content[0].text)
                        assert refusal["error"]["code"] == "SCOPE_DENIED"
                        assert body not in json.dumps(refusal)
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 10)
        listener.close()
    assert not (project / ".mcp.json").exists()
    hosts.uninstall_host(settings, project, "claude")
    assert json.loads(local.read_text()) == original
    hosts.install_host(settings, project, binding, "claude", agent, producer)
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
    budget = hosts.HOST_CONTEXT_BYTES - len(hosts.BOUNDED_CONTEXT_MARKER.encode()) - 1
    authority.text = "가" * (budget // 3)
    event = native(project, host, "before_agent_start" if host == "omp" else "UserPromptSubmit", prompt="bounded recall")
    result = hosts.handle_hook(receipt, event)
    output = result["stdout"]["additionalContext"] if host == "omp" else result["stdout"]["hookSpecificOutput"]["additionalContext"]
    assert len(output.encode()) <= hosts.HOST_CONTEXT_BYTES
    assert output.endswith(authority.text)
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


@pytest.mark.parametrize("existing_installation", [False, True])
def test_codex_strict_refusal_preserves_native_files_and_advisory_installation(installation, existing_installation):
    project, settings, agent, producer, install = installation
    config = project / ".codex/config.toml"
    config.parent.mkdir()
    config.write_text('# User-owned configuration.\n[mcp_servers.foreign]\ncommand = "foreign-server"\n')
    hooks = project / ".codex/hooks.json"
    hooks.write_text('{"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"foreign-hook"}]}]}}\n')
    receipt = install("codex", strict=False) if existing_installation else None
    installation_id = hosts.load_receipt(receipt)["installation_id"] if receipt else None
    root = project.parent
    before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    with pytest.raises(DomainError) as caught:
        hosts.install_host(settings, project, "project-binding", "codex", agent, producer, strict=True)
    assert caught.value.public()["code"] == "HOST_STRICT_UNSUPPORTED"
    assert caught.value.public()["effect"] == "not_started"
    assert {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()} == before
    if receipt:
        assert install("codex", strict=False) == receipt
        assert hosts.load_receipt(receipt)["installation_id"] == installation_id
        assert hosts.uninstall_host(settings, project, "codex")["state"] == "uninstalled"
        assert tomllib.loads(config.read_text())["mcp_servers"] == {"foreign": {"command": "foreign-server"}}
        assert json.loads(hooks.read_text()) == {
            "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "foreign-hook"}]}]},
        }
    else:
        assert not settings.state_dir.exists()

def test_legacy_codex_strict_is_cleanup_only_and_advisory_reinstallable(installation, authority):
    project, settings, _, _, install = installation
    receipt_path = install("codex")
    document = json.loads(receipt_path.read_text())
    document["strict"] = True
    document["capabilities"] = hosts.capabilities("codex", strict=True, capability=settings.capability)
    hosts._write_receipt(receipt_path, document)
    before = {path.relative_to(project): path.read_bytes() for path in project.rglob("*") if path.is_file()}
    for options in ({}, {"allow_legacy": True}, {"active": False}):
        with pytest.raises(DomainError) as caught:
            hosts.load_receipt(receipt_path, **options)
        assert caught.value.code == "HOST_STRICT_UNSUPPORTED"
    passive = hosts.load_receipt(receipt_path, allow_legacy=True, active=False)
    assert passive["installation_id"] == document["installation_id"]
    assert not authority.calls
    assert {path.relative_to(project): path.read_bytes() for path in project.rglob("*") if path.is_file()} == before
    assert hosts.uninstall_host(settings, project, "codex")["state"] == "uninstalled"
    replacement = hosts.load_receipt(install("codex"))
    assert replacement["strict"] is False
    assert replacement["installation_id"] != document["installation_id"]



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
    assert not settings.state_dir.exists()
    assert {path.relative_to(project): path.read_bytes() for path in project.rglob("*") if path.is_file()} == before
    capability = hosts.capabilities("omp", strict=True)
    assert capability["strict"] == "unsupported_refused"
    assert capability["first_action"] == "refused_before_installation"
    assert capability["startup_corpus_bytes"] == 0
    assert capability["prompt_context"] == "disabled"


def _historical_omp_strict_metadata(receipt):
    document = json.loads(receipt.read_text())
    document["adapter_version"] = 4
    document["capabilities"]["scope"] = "registered_binding_plus_cwd_locator_check_not_cwd_authority"
    # Action recall postdates every historical adapter version.
    document["capabilities"].pop("action_recall", None)
    if document.get("capability") == "agent_judged":
        document["capability"] = "full_semantic"
        document["capabilities"].pop("capture_judgment")
        document["capabilities"]["capture_processing"] = "automatic_server_extraction_until_semantic_ready"
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
        assert caught.value.code == ("HOST_LEGACY_REINSTALL_REQUIRED" if options.get("allow_legacy") else "HOST_RECEIPT_INVALID")
    cleanup = hosts.load_receipt(receipt, allow_legacy=True, active=False)
    assert cleanup["installation_id"] == historical["installation_id"]
    for strict in (False, True):
        with pytest.raises(DomainError) as caught:
            install("omp", strict=strict, prompt_recall=prompt_recall)
        assert caught.value.code == "HOST_STRICT_UNSUPPORTED"
    for event in (native(project, "omp", "before_agent_start", prompt="cannot enforce"), action(project, "omp")):
        result = hosts.handle_hook(receipt, event)
        assert result["state"] == "degraded"
        assert result["code"] == "HOST_RECEIPT_UNAVAILABLE"
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

    _abrupt_process(
        hosts.install_host, settings, project, "project-binding", "omp", agent, producer,
        crash_path=receipt if boundary == "pending_receipt" else mcp, strict=False,
    )
    _historical_omp_strict_metadata(receipt)
    assert hosts.load_receipt(receipt, allow_legacy=True, active=False)["state"] == "pending"
    with pytest.raises(DomainError) as caught:
        install("omp")
    assert caught.value.code == "HOST_STRICT_UNSUPPORTED"
    assert hosts.uninstall_host(settings, project, "omp")["state"] == "uninstalled"
    assert mcp.read_bytes() == original
    assert not (project / ".omp/extensions/agents-memory.ts").exists()
    assert hosts.load_receipt(install("omp"))["strict"] is False


@pytest.mark.parametrize("host", ["claude", "codex", "omp"])
def test_deleted_project_owned_uninstall_and_fresh_install(installation, host):
    import shutil

    project, settings, agent, producer, install = installation
    receipt_path = install(host)
    runtime = Path(hosts.load_receipt(receipt_path)["runtime_dir"])
    retained = runtime / "retain-runtime"
    retained.write_bytes(b"retained")
    shutil.rmtree(project)
    result = hosts.uninstall_host(settings, project, host, project_deleted=True)
    assert result["state"] == "native_uninstalled"
    assert result["project_entries"] == "unverified_absent"
    assert not project.exists()
    assert retained.read_bytes() == b"retained"
    assert agent.exists() and producer.exists()
    assert hosts.load_receipt(receipt_path, active=False, allow_deleted_project=True)["state"] == "native_removed"
    stable = project.parent / "stable"
    stable.mkdir()
    fresh = hosts.install_host(settings, stable, "project-binding", host, agent, producer, strict=False)
    assert hosts.load_receipt(Path(fresh["receipt"]))["project_root"] == str(stable)


def test_deleted_project_uninstall_preserves_changed_native_entry(installation):
    import shutil

    project, settings, _, _, install = installation
    receipt = hosts.load_receipt(install())
    entry = next(item for item in receipt["ownership"] if item["kind"] == "local_mcp")
    native_path = Path(entry["path"])
    document = json.loads(native_path.read_text())
    document["projects"][entry["project"]]["mcpServers"][entry["key"]]["changed"] = True
    native_path.write_text(json.dumps(document))
    before = native_path.read_bytes()
    shutil.rmtree(project)
    with pytest.raises(DomainError) as drift:
        hosts.uninstall_host(settings, project, "claude", project_deleted=True)
    assert drift.value.code == "HOST_OWNERSHIP_DRIFT"
    assert native_path.read_bytes() == before
    assert not project.exists()


def test_deleted_project_uninstall_requires_modern_private_receipt(installation):
    import shutil

    project, settings, _, _, install = installation
    receipt_path = install("codex")
    shutil.rmtree(project)
    receipt_path.chmod(0o644)
    with pytest.raises(DomainError):
        hosts.uninstall_host(settings, project, "codex", project_deleted=True)
    assert not project.exists()
    receipt_path.unlink()
    with pytest.raises(DomainError) as missing:
        hosts.uninstall_host(settings, project, "codex", project_deleted=True)
    assert missing.value.code == "HOST_RECEIPT_INVALID"
    assert not project.exists()


def test_deleted_project_uninstall_refuses_symlink_alias(installation):
    import shutil

    project, settings, _, _, install = installation
    install("codex")
    alias = project.parent / "alias"
    alias.symlink_to(project)
    shutil.rmtree(project)
    with pytest.raises(DomainError) as denied:
        hosts.uninstall_host(settings, alias, "codex", project_deleted=True)
    assert denied.value.code == "HOST_PATH_DENIED"
    assert not project.exists()


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_absent_project_needs_explicit_deletion_and_reappeared_entries_stay_removable(installation, host):
    project, settings, agent, producer, install = installation
    receipt_path = install(host, strict=False)
    moved = project.parent / "moved-away"
    project.rename(moved)
    with pytest.raises(DomainError) as absent:
        hosts.uninstall_host(settings, project, host)
    assert absent.value.code == "HOST_PROJECT_ABSENT"
    assert hosts.load_receipt(receipt_path)["state"] == "installed"
    result = hosts.uninstall_host(settings, project, host, project_deleted=True)
    assert result["state"] == "native_uninstalled"
    assert result["project_entries"] == "unverified_absent"
    moved.rename(project)
    with pytest.raises(DomainError) as present:
        hosts.uninstall_host(settings, project, host, project_deleted=True)
    assert present.value.code == "HOST_PROJECT_PRESENT"
    hook = hosts.handle_hook(receipt_path, native(project, host))
    assert hook["code"] == "HOST_UNINSTALL_INCOMPLETE"
    with pytest.raises(DomainError) as incomplete:
        install(host, strict=False)
    assert incomplete.value.code == "HOST_UNINSTALL_INCOMPLETE"
    assert hosts.uninstall_host(settings, project, host)["state"] == "uninstalled"
    assert hosts.load_receipt(receipt_path, active=False)["state"] == "removed"
    assert hosts.load_receipt(install(host, strict=False))["state"] == "installed"


@pytest.mark.parametrize(("host", "change"), [
    ("claude", "hook"), ("codex", "hook"), ("claude", "moved"), ("codex", "moved"),
    ("claude", "copy"), ("codex", "copy"), ("codex", "toml"), ("codex", "toml_scalar"),
])
def test_reappeared_root_preserves_changed_owned_entries_as_drift(installation, host, change):
    project, settings, _, _, install = installation
    receipt_path = install(host, strict=False)
    moved = project.parent / "moved-away"
    project.rename(moved)
    hosts.uninstall_host(settings, project, host, project_deleted=True)
    moved.rename(project)
    if change.startswith("toml"):
        path = project / ".codex/config.toml"
        text = path.read_text().replace("\ncommand = ", "\ncommand  = ", 1) if change == "toml" else "mcp_servers = 42\n"
        path.write_text(text)
    else:
        path = project / (".claude/settings.local.json" if host == "claude" else ".codex/hooks.json")
        document = json.loads(path.read_text())
        groups = document["hooks"]["UserPromptSubmit"]
        if change == "hook":
            groups[0]["hooks"][0]["timeout"] = 14
        elif change == "moved":
            group = groups.pop(0)
            group["hooks"][0]["timeout"] = 14
            document["hooks"]["SessionEnd"].append(group)
        else:
            copy = json.loads(json.dumps(groups[0]))
            copy["hooks"][0]["timeout"] = 14
            groups.append(copy)
        path.write_text(json.dumps(document))
    before = path.read_bytes()
    with pytest.raises(DomainError) as drift:
        hosts.uninstall_host(settings, project, host)
    assert drift.value.code == "HOST_OWNERSHIP_DRIFT"
    assert path.read_bytes() == before
    assert hosts.load_receipt(receipt_path, active=False)["state"] == "native_removed"


@pytest.mark.parametrize("native_change", ["same", "same_without_hooks", "changed"])
def test_reappeared_native_key_is_removed_only_when_still_owned(installation, native_change):
    project, settings, _, _, install = installation
    receipt_path = install("claude", strict=False)
    owned = mcp_servers(json.loads(hosts._claude_config_path().read_text()), project)[hosts.SERVER_NAME]
    moved = project.parent / "moved-away"
    project.rename(moved)
    hosts.uninstall_host(settings, project, "claude", project_deleted=True)
    moved.rename(project)
    if native_change == "same_without_hooks":
        (project / ".claude" / "settings.local.json").unlink()
    native_path = hosts._claude_config_path()
    document = json.loads(native_path.read_text())
    restored = dict(owned, args=[*owned["args"], "--changed"]) if native_change == "changed" else owned
    document.setdefault("projects", {}).setdefault(str(project), {}).setdefault("mcpServers", {})[hosts.SERVER_NAME] = restored
    native_path.write_text(json.dumps(document))
    if native_change == "changed":
        with pytest.raises(DomainError) as drift:
            hosts.uninstall_host(settings, project, "claude")
        assert drift.value.code == "HOST_OWNERSHIP_DRIFT"
        assert hosts.load_receipt(receipt_path, active=False)["state"] == "native_removed"
        return
    assert hosts.uninstall_host(settings, project, "claude")["state"] == "uninstalled"
    assert hosts.load_receipt(receipt_path, active=False)["state"] == "removed"
    remaining = json.loads(native_path.read_text()).get("projects", {}).get(str(project), {}).get("mcpServers", {})
    assert hosts.SERVER_NAME not in remaining
    assert hosts.load_receipt(install("claude", strict=False))["state"] == "installed"


@pytest.mark.parametrize("with_args", [False, True, "receipt_equals"])
def test_reappeared_shell_quoted_codex_hook_is_drift(installation, tmp_path, with_args):
    project, settings, agent, producer, _ = installation
    quoted = settings.model_copy(update={"state_dir": tmp_path / "O'Brien" / "state"})
    receipt_path = Path(hosts.install_host(quoted, project, "project-binding", "codex", agent, producer, strict=False)["receipt"])
    hooks_path = project / ".codex/hooks.json"
    assert str(receipt_path) not in hooks_path.read_text()
    moved = project.parent / "moved-away"
    project.rename(moved)
    hosts.uninstall_host(quoted, project, "codex", project_deleted=True)
    moved.rename(project)
    document = json.loads(hooks_path.read_text())
    handler = document["hooks"]["UserPromptSubmit"][0]["hooks"][0]
    handler["timeout"] = 14
    if with_args is True:
        handler["args"] = []
    elif with_args == "receipt_equals":
        tokens = shlex.split(handler["command"])
        index = tokens.index("--receipt")
        tokens[index:index + 2] = ["--receipt=" + tokens[index + 1]]
        handler["command"] = shlex.join(tokens)
    hooks_path.write_text(json.dumps(document))
    with pytest.raises(DomainError) as drift:
        hosts.uninstall_host(quoted, project, "codex")
    assert drift.value.code == "HOST_OWNERSHIP_DRIFT"
    assert hosts.load_receipt(receipt_path, active=False)["state"] == "native_removed"


def test_interrupted_finishing_pass_rescans_restored_entries(installation):
    project, settings, _, _, install = installation
    receipt_path = install("codex", strict=False)
    moved = project.parent / "moved-away"
    project.rename(moved)
    hosts.uninstall_host(settings, project, "codex", project_deleted=True)
    moved.rename(project)
    hooks_path = project / ".codex/hooks.json"
    hooks_raw = hooks_path.read_bytes()
    hooks_path.unlink()

    _abrupt_process(hosts.uninstall_host, settings, project, "codex", crash_path=receipt_path, crash_state="native_finishing")
    assert hosts.load_receipt(receipt_path, active=False)["state"] == "native_finishing"
    with pytest.raises(DomainError) as incomplete:
        install("codex", strict=False)
    assert incomplete.value.code == "HOST_UNINSTALL_INCOMPLETE"
    hooks_path.write_bytes(hooks_raw)
    assert hosts.uninstall_host(settings, project, "codex")["state"] == "uninstalled"
    assert not hooks_path.exists() and not (project / ".codex/config.toml").exists()
    assert hosts.load_receipt(receipt_path, active=False)["state"] == "removed"


def test_root_vanishing_after_precheck_keeps_cleanup_incomplete(installation, monkeypatch):
    project, settings, _, _, install = installation
    receipt_path = install("codex", strict=False)
    moved = project.parent / "moved-away"
    project.rename(moved)
    hosts.uninstall_host(settings, project, "codex", project_deleted=True)
    moved.rename(project)
    lock = hosts._ownership_lock

    @contextlib.contextmanager
    def vanish_while_waiting(*args, **kwargs):
        with lock(*args, **kwargs):
            project.rename(moved)
            yield

    monkeypatch.setattr(hosts, "_ownership_lock", vanish_while_waiting)
    with pytest.raises(DomainError) as changed:
        hosts.uninstall_host(settings, project, "codex")
    assert changed.value.code == "HOST_CONFIG_DRIFT"
    assert hosts.load_receipt(receipt_path, active=False, allow_deleted_project=True)["state"] == "native_removed"


def test_root_vanishing_during_scan_keeps_cleanup_incomplete(installation, monkeypatch):
    project, settings, _, _, install = installation
    receipt_path = install("codex", strict=False)
    moved = project.parent / "moved-away"
    project.rename(moved)
    hosts.uninstall_host(settings, project, "codex", project_deleted=True)
    moved.rename(project)
    scan = hosts._removal_plan

    def vanish_during_scan(*args, **kwargs):
        project.rename(moved)
        return scan(*args, **kwargs)

    monkeypatch.setattr(hosts, "_removal_plan", vanish_during_scan)
    with pytest.raises(DomainError) as changed:
        hosts.uninstall_host(settings, project, "codex")
    assert changed.value.code == "HOST_CONFIG_DRIFT"
    assert hosts.load_receipt(receipt_path, active=False, allow_deleted_project=True)["state"] == "native_removed"


@pytest.mark.parametrize("change", ["vanished", "replaced"])
@pytest.mark.parametrize("resume", ["install", "uninstall"])
@pytest.mark.parametrize("state", ["pending", "removing"])
def test_root_changed_while_waiting_to_resume_interrupted_intent_is_refused(installation, monkeypatch, state, resume, change):
    project, settings, agent, producer, install = installation
    receipt_path = hosts._receipt_path(settings, project.resolve(), "codex")
    if state == "removing":
        install("codex", strict=False)

    if state == "pending":
        _abrupt_process(
            hosts.install_host, settings, project, "project-binding", "codex", agent, producer,
            crash_path=receipt_path, crash_state=state, strict=False,
        )
    else:
        _abrupt_process(hosts.uninstall_host, settings, project, "codex", crash_path=receipt_path, crash_state=state)
    receipt = hosts.load_receipt(receipt_path, active=False)
    assert receipt["state"] == state
    intent = hosts._intent_path(receipt)
    moved = project.parent / "moved-away"
    lock = hosts._ownership_lock

    @contextlib.contextmanager
    def change_while_waiting(*args, **kwargs):
        with lock(*args, **kwargs):
            project.rename(moved)
            if change == "replaced":
                project.mkdir()
            yield

    monkeypatch.setattr(hosts, "_ownership_lock", change_while_waiting)
    with pytest.raises(DomainError) as changed:
        if resume == "install":
            hosts.install_host(settings, project, "project-binding", "codex", agent, producer, strict=False)
        else:
            hosts.uninstall_host(settings, project, "codex")
    assert changed.value.code == "HOST_CONFIG_DRIFT" and changed.value.effect == EffectState.NOT_STARTED
    assert hosts.load_receipt(receipt_path, active=False, allow_deleted_project=change == "vanished")["state"] == state
    assert intent.exists()
    assert (list(project.iterdir()) == []) if change == "replaced" else not project.exists()
    if state == "removing":
        assert (moved / ".codex/hooks.json").exists() and (moved / ".codex/config.toml").exists()


def test_foreign_unparseable_hook_does_not_block_uninstall(installation):
    project, settings, _, _, install = installation
    receipt_path = install("codex", strict=False)
    hooks_path = project / ".codex/hooks.json"
    document = json.loads(hooks_path.read_text())
    foreign = {"hooks": [{"type": "command", "command": 'echo "$(echo "it\'s")"', "timeout": 5}]}
    document["hooks"]["UserPromptSubmit"].append(foreign)
    hooks_path.write_text(json.dumps(document))
    assert hosts.uninstall_host(settings, project, "codex")["state"] == "uninstalled"
    assert json.loads(hooks_path.read_text())["hooks"] == {"UserPromptSubmit": [foreign]}
    assert hosts.load_receipt(receipt_path, active=False)["state"] == "removed"


@pytest.mark.parametrize("quoted", [False, True])
def test_owned_hook_edited_into_unparseable_shell_is_drift(installation, tmp_path, quoted):
    project, settings, agent, producer, _ = installation
    if quoted:
        settings = settings.model_copy(update={"state_dir": tmp_path / "O'Brien" / "state"})
    receipt_path = Path(hosts.install_host(settings, project, "project-binding", "codex", agent, producer, strict=False)["receipt"])
    moved = project.parent / "moved-away"
    project.rename(moved)
    hosts.uninstall_host(settings, project, "codex", project_deleted=True)
    moved.rename(project)
    hooks_path = project / ".codex/hooks.json"
    document = json.loads(hooks_path.read_text())
    handler = document["hooks"]["UserPromptSubmit"][0]["hooks"][0]
    handler["command"] += " # it's"
    hooks_path.write_text(json.dumps(document))
    before = hooks_path.read_bytes()
    # The finishing pass skips digest mismatches, so only the reference scan can refuse.
    with pytest.raises(DomainError) as drift:
        hosts.uninstall_host(settings, project, "codex")
    assert drift.value.code == "HOST_OWNERSHIP_DRIFT"
    assert hooks_path.read_bytes() == before
    assert hosts.load_receipt(receipt_path, active=False)["state"] == "native_removed"


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_root_vanishing_during_intent_apply_keeps_recovery_intent(installation, monkeypatch, host):
    project, settings, _, _, install = installation
    receipt_path = install(host, strict=False)
    moved = project.parent / "moved-away"
    apply = hosts._apply

    def vanish_while_applying(*args):
        if project.exists():
            project.rename(moved)
        return apply(*args)

    monkeypatch.setattr(hosts, "_apply", vanish_while_applying)
    with pytest.raises(DomainError) as changed:
        hosts.uninstall_host(settings, project, host)
    assert changed.value.code == "HOST_CONFIG_DRIFT" and changed.value.effect == EffectState.UNKNOWN
    assert hosts.load_receipt(receipt_path, active=False, allow_deleted_project=True)["state"] == "removing"
    monkeypatch.setattr(hosts, "_apply", apply)
    moved.rename(project)
    assert hosts.uninstall_host(settings, project, host)["state"] == "uninstalled"
    owned = ".claude/settings.local.json" if host == "claude" else ".codex/hooks.json"
    assert not (project / owned).exists()
    assert hosts.load_receipt(receipt_path, active=False)["state"] == "removed"
    assert hosts.load_receipt(install(host, strict=False))["state"] == "installed"


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_root_moved_and_restored_during_intent_apply_removes_only_for_real(installation, monkeypatch, host):
    project, settings, _, _, install = installation
    receipt_path = install(host, strict=False)
    moved = project.parent / "moved-away"
    apply = hosts._apply

    def flicker_while_applying(*args):
        project.rename(moved)
        try:
            return apply(*args)
        finally:
            moved.rename(project)

    monkeypatch.setattr(hosts, "_apply", flicker_while_applying)
    assert hosts.uninstall_host(settings, project, host)["state"] == "uninstalled"
    owned = ".claude/settings.local.json" if host == "claude" else ".codex/hooks.json"
    assert not (project / owned).exists()
    assert hosts.load_receipt(receipt_path, active=False)["state"] == "removed"


@pytest.mark.parametrize("entry", ["directory", "socket"])
def test_non_regular_owned_config_is_refused_without_changes(installation, monkeypatch, entry):
    project, settings, _, _, install = installation
    receipt_path = install("codex", strict=False)
    hooks_path = project / ".codex/hooks.json"
    config = (project / ".codex/config.toml").read_bytes()
    hooks_path.unlink()
    with contextlib.ExitStack() as stack:
        if entry == "directory":
            hooks_path.mkdir()
        else:
            monkeypatch.chdir(hooks_path.parent)
            stack.enter_context(socket.socket(socket.AF_UNIX)).bind(hooks_path.name)
        with pytest.raises(DomainError) as invalid:
            hosts.uninstall_host(settings, project, "codex")
    assert invalid.value.code == "HOST_CONFIG_INVALID"
    assert hosts.load_receipt(receipt_path, active=False)["state"] == "installed"
    assert (project / ".codex/config.toml").read_bytes() == config


def test_pinned_project_refuses_links_and_non_regular_entries(tmp_path):
    root, outside = tmp_path / "project", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "hooks.json").write_bytes(b"{}")
    (root / "linked").symlink_to(outside)
    (root / "final.json").symlink_to(outside / "hooks.json")
    (root / "blocker").write_bytes(b"file")
    (root / "folder").mkdir()
    os.mkfifo(root / "fifo")
    (root / "large.json").write_bytes(b"x" * 11)
    with hosts._pinned_project(root) as pinned:
        for path, code in (
            (root / "linked/hooks.json", "HOST_PATH_DENIED"), (root / "final.json", "HOST_PATH_DENIED"),
            (root / "folder", "HOST_CONFIG_INVALID"), (root / "fifo", "HOST_CONFIG_INVALID"),
        ):
            with pytest.raises(DomainError) as refused:
                pinned.read(path)
            assert refused.value.code == code
        with pytest.raises(DomainError) as oversized:
            pinned.read(root / "large.json", 10)
        assert oversized.value.code == "HOST_CONFIG_INVALID"
        assert pinned.read(root / "blocker/hooks.json") is None
        for path in (root / "linked/hooks.json", root / "blocker/hooks.json"):
            with pytest.raises(DomainError) as denied:
                pinned.write(path, b"owned", replace=False)
            assert denied.value.code == "HOST_PATH_DENIED"
    assert (outside / "hooks.json").read_bytes() == b"{}"
    assert not list(root.rglob(".memory-private-*"))


@pytest.mark.parametrize("boundary", ["removing_receipt", "native_key"])
def test_older_native_only_removing_intent_finishes_project_entries(installation, boundary):
    project, settings, _, _, install = installation
    receipt = install()
    moved = project.parent / "moved-away"
    project.rename(moved)
    _crash_deleted_claude_removal(project, settings, receipt, boundary)
    manifest = hosts.load_receipt(receipt, active=False, allow_deleted_project=True)
    manifest["state"] = "removing"
    hosts._write_receipt(receipt, manifest)
    moved.rename(project)
    with pytest.raises(DomainError) as incomplete:
        install()
    assert incomplete.value.code == "HOST_UNINSTALL_INCOMPLETE" and incomplete.value.effect == EffectState.UNKNOWN
    assert hosts.uninstall_host(settings, project, "claude")["state"] == "uninstalled"
    assert not (project / ".claude" / "settings.local.json").exists()
    assert hosts.load_receipt(receipt, active=False)["state"] == "removed"
    assert hosts.load_receipt(install())["state"] == "installed"


@pytest.mark.parametrize("boundary", ["removing_receipt", "native_key"])
def test_interrupted_deleted_cleanup_finishes_project_entries_after_root_returns(installation, boundary):
    project, settings, _, _, install = installation
    receipt = install()
    moved = project.parent / "moved-away"
    project.rename(moved)
    _crash_deleted_claude_removal(project, settings, receipt, boundary)
    moved.rename(project)
    hooks_path = project / ".claude" / "settings.local.json"
    assert "hooks" in json.loads(hooks_path.read_text())
    with pytest.raises(DomainError) as incomplete:
        install()
    assert incomplete.value.code == "HOST_UNINSTALL_INCOMPLETE" and incomplete.value.effect == EffectState.NOT_STARTED
    assert hosts.handle_hook(receipt, native(project))["code"] == "HOST_UNINSTALL_INCOMPLETE"
    assert hosts.uninstall_host(settings, project, "claude")["state"] == "uninstalled"
    assert not hooks_path.exists()
    manifest = hosts.load_receipt(receipt, active=False)
    assert manifest["state"] == "removed"
    assert not hosts._intent_path(manifest).exists()
    assert hosts.load_receipt(install())["state"] == "installed"


def test_refusal_after_resumed_native_cleanup_reports_unknown_effect(installation):
    project, settings, _, _, install = installation
    receipt = install()
    moved = project.parent / "moved-away"
    project.rename(moved)
    _crash_deleted_claude_removal(project, settings, receipt, "removing_receipt")
    moved.rename(project)
    hooks_path = project / ".claude" / "settings.local.json"
    document = json.loads(hooks_path.read_text())
    next(iter(document["hooks"].values()))[0]["hooks"][0]["timeout"] = 99
    hooks_path.write_text(json.dumps(document))
    with pytest.raises(DomainError) as drift:
        hosts.uninstall_host(settings, project, "claude")
    assert drift.value.code == "HOST_OWNERSHIP_DRIFT" and drift.value.effect == EffectState.UNKNOWN
    assert hosts.load_receipt(receipt, active=False)["state"] == "native_removed"


def _crash_deleted_claude_removal(project, settings, receipt, boundary):
    native_path = hosts._claude_config_path()

    _abrupt_process(
        hosts.uninstall_host, settings, project, "claude",
        crash_path=native_path if boundary == "native_key" else receipt,
        crash_state=None if boundary == "native_key" else "native_removing", project_deleted=True,
    )
    assert hosts.load_receipt(receipt, active=False, allow_deleted_project=True)["state"] == "native_removing"
    assert not project.exists()


@pytest.mark.parametrize("boundary", ["removing_receipt", "native_key"])
def test_deleted_project_removal_crash_recovers_without_recreation_or_unowned_loss(installation, boundary):
    import shutil

    project, settings, _, _, install = installation
    receipt = install()
    shutil.rmtree(project)
    _crash_deleted_claude_removal(project, settings, receipt, boundary)
    document = update_native_unowned_state(project)
    servers = mcp_servers(document, project)
    assert (hosts.SERVER_NAME in servers) == (boundary == "removing_receipt")
    servers.pop(hosts.SERVER_NAME, None)
    for _ in range(2):
        assert hosts.uninstall_host(settings, project, "claude", project_deleted=True)["state"] == "native_uninstalled"
        assert json.loads(hosts._claude_config_path().read_text()) == document
        assert not project.exists()
    manifest = hosts.load_receipt(receipt, active=False, allow_deleted_project=True)
    assert manifest["state"] == "native_removed"
    assert not hosts._intent_path(manifest).exists()


def test_deleted_project_cleanup_uses_validated_receipt_bytes_once(installation, monkeypatch):
    import shutil

    project, settings, _, _, install = installation
    receipt = install()
    shutil.rmtree(project)
    document = update_native_unowned_state(project)
    mcp_servers(document, project).pop(hosts.SERVER_NAME)
    reader = private_io.private_read
    replaced = False

    def replace_after_read(path, *args, **kwargs):
        nonlocal replaced
        raw = reader(path, *args, **kwargs)
        if path == receipt and not replaced:
            replaced = True
            private_io.private_write(receipt, b"invalid replacement receipt\n", replace=True)
        return raw

    monkeypatch.setattr(private_io, "private_read", replace_after_read)
    assert hosts.uninstall_host(settings, project, "claude", project_deleted=True)["state"] == "native_uninstalled"
    assert hosts.load_receipt(receipt, active=False, allow_deleted_project=True)["state"] == "native_removed"
    assert json.loads(hosts._claude_config_path().read_text()) == document
    assert not project.exists()


@pytest.mark.parametrize("drift", [
    "native_value", "before_value", "after_value", "empty_before", "project_file",
    "legacy_document", "foreign_project", "foreign_deployment", "pending",
    "legacy_receipt", "tampered_intent",
])
def test_deleted_project_removal_recovery_refuses_non_deletion_foreign_or_drifted_intent(installation, drift):
    import shutil

    project, settings, _, _, install = installation
    receipt = install()
    shutil.rmtree(project)
    _crash_deleted_claude_removal(project, settings, receipt, "removing_receipt")
    manifest = hosts.load_receipt(receipt, active=False, allow_deleted_project=True)
    old_intent_path = hosts._intent_path(manifest)
    intent = json.loads(old_intent_path.read_text())
    step = intent["steps"][0]
    native_path = hosts._claude_config_path()
    if drift == "native_value":
        document = json.loads(native_path.read_text())
        mcp_servers(document, project)[hosts.SERVER_NAME] = {"command": "foreign-owner"}
        native_path.write_text(json.dumps(document))
    elif drift == "before_value":
        step["before"] = {"command": "foreign-owner"}
    elif drift == "after_value":
        step["after"] = step["before"]
    elif drift == "empty_before":
        step["before"] = None
    elif drift == "project_file":
        entry = next(item for item in manifest["ownership"] if item["kind"] == "hook")
        raw = b'{"hooks":{"UserPromptSubmit":[]}}'
        intent["steps"].append({
            "path": entry["path"], "before": None, "before_digest": None,
            "after": base64.b64encode(raw).decode(), "after_digest": hosts._digest(raw),
        })
    elif drift == "legacy_document":
        before = native_path.read_bytes()
        document = json.loads(before)
        mcp_servers(document, project).pop(hosts.SERVER_NAME)
        after = json.dumps(document).encode()
        intent["steps"][0] = {
            "path": str(native_path), "before": base64.b64encode(before).decode(),
            "before_digest": hosts._digest(before), "after": base64.b64encode(after).decode(),
            "after_digest": hosts._digest(after),
        }
    elif drift == "foreign_project":
        step["project"] = str(project.parent / "foreign")
    elif drift == "foreign_deployment":
        manifest["deployment_id"] = "foreign-deployment"
    elif drift == "pending":
        manifest["state"] = "pending"
    elif drift == "legacy_receipt":
        manifest["adapter_version"] = 2
    elif drift == "tampered_intent":
        intent["installation_id"] = "tampered-installation"
    if drift != "tampered_intent":
        manifest["intent_digest"] = hosts.canonical_digest(intent)
    intent_path = hosts._intent_path(manifest)
    intent_path.write_text(json.dumps(intent))
    hosts._write_receipt(receipt, manifest)
    snapshots = {path: path.read_bytes() for path in {receipt, native_path, old_intent_path, intent_path}}

    with pytest.raises(DomainError) as denied:
        hosts.uninstall_host(settings, project, "claude", project_deleted=True)
    assert denied.value.code in {"HOST_RECEIPT_INVALID", "HOST_RECOVERY_DRIFT", "HOST_CONFIG_DRIFT"}
    assert all(path.read_bytes() == raw for path, raw in snapshots.items())
    assert not project.exists()


@pytest.mark.parametrize("boundary", [None, "removing_receipt", "native_key"])
def test_deleted_linked_worktree_preserves_exact_native_project_cleanup(installation, boundary):
    project, settings, _, _, install = installation
    project.rmdir()
    main = project.parent / "canonical"
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    commands = [
        ["init", str(main)],
        ["-C", str(main), "commit", "--allow-empty", "-m", "isolated deleted worktree fixture"],
        ["-C", str(main), "worktree", "add", "--detach", str(project)],
    ]
    prefix = ["git", "-c", "core.hooksPath=/dev/null", "-c", "user.name=Test", "-c", "user.email=test@example.invalid"]
    for arguments in commands:
        subprocess.run(prefix + arguments, check=True, capture_output=True, timeout=10, env=environment)
    local = hosts._claude_config_path()
    original = {"projects": {str(main): {"hasTrustDialogAccepted": False, "user-field": "retained"}}}
    local.write_text(json.dumps(original))
    receipt = install()
    with pytest.raises(DomainError) as live:
        hosts.load_receipt(receipt, active=False, allow_deleted_project=True)
    assert live.value.code == "HOST_RECEIPT_INVALID"
    subprocess.run(
        prefix + ["-C", str(main), "worktree", "remove", "--force", str(project)],
        check=True, capture_output=True, timeout=10, env=environment,
    )
    with pytest.raises(DomainError) as active:
        hosts.load_receipt(receipt, allow_deleted_project=True)
    assert active.value.code == "HOST_RECEIPT_INVALID"
    if boundary is not None:
        _crash_deleted_claude_removal(project, settings, receipt, boundary)
        original = update_native_unowned_state(main)
        assert (hosts.SERVER_NAME in mcp_servers(original, main)) == (boundary == "removing_receipt")
        mcp_servers(original, main).pop(hosts.SERVER_NAME, None)
    result = hosts.uninstall_host(settings, project, "claude", project_deleted=True)
    assert result["state"] == "native_uninstalled"
    assert json.loads(local.read_text()) == original
    assert not project.exists()
    assert hosts.uninstall_host(settings, project, "claude", project_deleted=True)["state"] == "native_uninstalled"
    assert json.loads(local.read_text()) == original
    assert not project.exists()
    manifest = hosts.load_receipt(receipt, active=False, allow_deleted_project=True)
    assert manifest["state"] == "native_removed"
    assert not hosts._intent_path(manifest).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("prompt_recall", [False, True])
@pytest.mark.parametrize("host", ["codex", "omp"])
async def test_native_capture_pointer_requires_actual_commit_and_is_generation_scoped(installation, capture_authority, monkeypatch, host, prompt_recall):
    project, settings, agent, producer, _ = installation
    store, actor, binding = capture_authority
    company = settings.model_copy(update={"mode": "company"})
    receipt = Path(hosts.install_host(
        company, project, binding, host, agent, producer, strict=False, prompt_recall=prompt_recall,
    )["receipt"])
    acknowledged = {}

    class Endpoint:
        def __init__(self, base_url, token_file, timeout=120, *, state_dir=None, deployment_id=None, remote_settings=None):
            self.token_file = token_file

        def request(self, route, payload):
            if route == "/api/context":
                text = '{"approved_rules":[],"memory_candidates":[],"relations":[]}'
                return {"context": text, "context_bytes": len(text.encode()), "stamp": {"epoch": 1, "rules": []}}
            assert route == "/api/capture" and self.token_file == producer
            result = acknowledged.get(payload["idempotency_key"])
            if result is None:
                raise DomainError("SERVICE_UNAVAILABLE", "No capture acknowledgment", effect=EffectState.UNKNOWN)
            assert canonical_digest(payload) == result[0]
            return result[1].model_dump(mode="json")

    monkeypatch.setattr(hosts, "LocalClient", Endpoint)
    event = native(
        project, host, "input" if host == "omp" else "UserPromptSubmit",
        hook_instance_id="capture-operation",
        **({"text": "합성 입력: offline에서만 보관", "source": "interactive"} if host == "omp" else {"prompt": "합성 입력: offline에서만 보관"}),
    )
    first = hosts.handle_hook(receipt, event)
    assert first["capture"]["state"] == "durably_spooled"
    runtime = Path(hosts.load_receipt(receipt)["runtime_dir"])
    spool = ProducerSpool(runtime / "capture.sqlite3", settings.deployment_id, binding, settings.spool_limit_bytes)
    try:
        payload = json.loads(spool.db.execute("SELECT payload FROM outbox").fetchone()[0])
    finally:
        spool.close()
    command = CaptureCommand.model_validate(payload)
    operation = await store.capture(actor, command)
    acknowledged[command.idempotency_key] = canonical_digest(payload), operation
    assert operation.state == "captured"
    pending = await store.inspect(actor, binding, "pending")
    assert any(item["kind"] == "source_selection" and operation.source_id in item["source_ids"] for item in pending["items"])
    if host == "omp":
        child = hosts.handle_hook(receipt, native(
            project, "omp", "before_agent_start", prompt="child preparation",
            agent={"kind": "sub", "id": "child", "parentId": "main-agent", "depth": 1},
        ))
        assert "source_pointer" not in json.dumps(child["stdout"])
        prepared = native(
            project, "omp", "before_agent_start", prompt=event["text"],
            ingress_operation_id=event["hook_instance_id"],
        )
        result = hosts.handle_hook(receipt, prepared)
        reentered = hosts.handle_hook(receipt, prepared)
        assert "source_pointer" not in json.dumps(reentered["stdout"])
        hosts.handle_hook(receipt, native(project, "omp", "session_compact"))
        after = hosts.handle_hook(receipt, prepared)
        assert "source_pointer" not in json.dumps(after["stdout"])
    else:
        result = hosts.handle_hook(receipt, event)
    assert result["capture"]["source_pointer"]["source_id"] == operation.source_id
    assert result["capture"]["capture_disposition"] == "captured"
    assert result["provider_input_observed"] is False
    output = result["stdout"].get("additionalContext") if host == "omp" else result["stdout"].get("hookSpecificOutput", {}).get("additionalContext")
    if prompt_recall:
        status = json.loads(output.removeprefix(hosts.BOUNDED_CONTEXT_MARKER + "\n").split("\n", 1)[0])
        assert status["capture"]["source_pointer"]["source_id"] == operation.source_id
        assert status["selection"] and status["candidate_ready"]
        assert len(output.encode("utf-8")) <= hosts.HOST_CONTEXT_BYTES and command.body not in output
    else:
        assert output is None and operation.source_id not in json.dumps(result["stdout"])
    assert command.coverage.status == "observed_window"
    assert command.coverage.original_bytes == len(command.body.encode())
    assert "HOST_SESSION_WINDOW_UNOBSERVED" in command.coverage.gaps


@pytest.mark.parametrize("host", ["claude", "codex", "omp"])
def test_validated_v3_adapter_is_cleanup_only_and_reinstall_advances_owned_contract(installation, host):
    project, settings, _, _, install = installation
    receipt = install(host, strict=False)
    manifest = json.loads(receipt.read_text())
    manifest["adapter_version"] = 3
    manifest.pop("capability")
    manifest["capabilities"]["scope"] = "registered_binding_plus_cwd_locator_check_not_cwd_authority"
    for key in ("source_pointer", "capture_coverage", "capture_judgment", "capture_processing", "action_recall"):
        manifest["capabilities"].pop(key, None)
    hosts._write_receipt(receipt, manifest)
    with pytest.raises(DomainError):
        hosts.load_receipt(receipt)
    with pytest.raises(DomainError) as caught:
        hosts.load_receipt(receipt, allow_legacy=True)
    assert caught.value.code == "HOST_LEGACY_REINSTALL_REQUIRED"
    assert hosts.load_receipt(receipt, allow_legacy=True, active=False)["adapter_version"] == 3
    refused = hosts.handle_hook(receipt, native(project, host, "before_agent_start" if host == "omp" else "UserPromptSubmit", prompt="not executed"))
    assert "source_pointer" not in json.dumps(refused["stdout"])
    assert hosts.uninstall_host(settings, project, host)["state"] == "uninstalled"
    assert hosts.load_receipt(install(host, strict=False))["adapter_version"] == hosts.ADAPTER_VERSION


def _historical_v4_metadata(receipt):
    document = json.loads(receipt.read_text())
    document["adapter_version"] = 4
    document.pop("capability")
    document["capabilities"]["scope"] = "registered_binding_plus_cwd_locator_check_not_cwd_authority"
    document["capabilities"].pop("action_recall", None)
    document["capabilities"].pop("capture_processing", None)
    document["capabilities"]["capture_judgment"] = "separate_caller_memory_record_no_automatic_candidate_readiness"
    hosts._write_receipt(receipt, document)
    return document


@pytest.mark.parametrize("host,strict", [
    ("claude", False), ("claude", True), ("codex", False), ("codex", True),
    ("omp", False), ("omp", True),
])
@pytest.mark.parametrize("prompt_recall", [False, True])
def test_validated_pre_capability_v4_is_cleanup_only_then_reinstallable(installation, authority, host, strict, prompt_recall):
    project, settings, _, _, install = installation
    supported_strict = strict and host == "claude"
    receipt = install(host, strict=supported_strict, prompt_recall=prompt_recall)
    historical = _historical_v4_metadata(receipt)
    if host == "omp" and strict:
        historical = _historical_omp_strict_metadata(receipt)
    if host == "codex" and strict:
        historical["strict"] = True
        historical["capabilities"].update({
            "first_action": "deny_required_without_provider_input_evidence",
            "strict": "prompt_blocked_hosted_gap",
            "native_failure": "crash_timeout_or_skipped_hook_unenforceable_gap",
        })
        hosts._write_receipt(receipt, historical)
    paths = [receipt, *(Path(entry["path"]) if entry["kind"] == "local_mcp" else project / entry["path"] for entry in historical["ownership"])]
    before = {path: path.read_bytes() for path in paths}
    for options in ({}, {"active": False}):
        with pytest.raises(DomainError) as caught:
            hosts.load_receipt(receipt, **options)
        assert caught.value.code == "HOST_RECEIPT_INVALID"
    with pytest.raises(DomainError) as caught:
        hosts.load_receipt(receipt, allow_legacy=True, active=True)
    assert caught.value.code == "HOST_LEGACY_REINSTALL_REQUIRED"
    cleanup = hosts.load_receipt(receipt, allow_legacy=True, active=False)
    assert cleanup == historical and "capability" not in cleanup
    for event in (native(project, host, "before_agent_start" if host == "omp" else "UserPromptSubmit", prompt="not executed"), action(project, host)):
        refused = hosts.handle_hook(receipt, event)
        assert refused["state"] == ("degraded" if host == "omp" else "blocked")
        assert refused["code"] == "HOST_RECEIPT_UNAVAILABLE"
        assert "source_pointer" not in json.dumps(refused["stdout"])
    assert not authority.calls
    with pytest.raises(DomainError) as caught:
        install(host, strict=strict, prompt_recall=prompt_recall)
    assert caught.value.code == ("HOST_STRICT_UNSUPPORTED" if strict and host in {"codex", "omp"} else "HOST_LEGACY_REINSTALL_REQUIRED")
    assert all(path.read_bytes() == raw for path, raw in before.items())
    assert hosts.uninstall_host(settings, project, host)["state"] == "uninstalled"
    removed = hosts.load_receipt(receipt, allow_legacy=True, active=False)
    assert removed["state"] == "removed" and "capability" not in removed
    assert removed["capabilities"] == historical["capabilities"]
    assert all(not hosts._owned_entry_matches(project, entry) for entry in historical["ownership"])
    replacement = hosts.load_receipt(install(host, strict=supported_strict, prompt_recall=prompt_recall))
    assert replacement["installation_id"] != historical["installation_id"]
    assert replacement["adapter_version"] == hosts.ADAPTER_VERSION and replacement["capability"] == settings.capability
    assert replacement["capabilities"] == hosts.capabilities(
        host, strict=supported_strict, prompt_recall=prompt_recall, capability=settings.capability,
    )
    assert replacement["capabilities"]["capture_judgment"] == "unclassified_source_separate_caller_memory_record"


@pytest.mark.parametrize("host", ["claude", "codex", "omp"])
@pytest.mark.parametrize("drift", [
    "null_capability", "unknown_capability", "malformed_capability", "guessed_semantic",
    "missing_judgment", "unknown_judgment", "capture_processing", "missing_capabilities", "extra_metadata",
    "missing_ownership", "malformed_ownership_digest", "wrong_ownership_digest", "malformed_installed_digest",
    "receipt_digest", "project", "deployment", "host", "runtime", "traversal", "absolute_path", "symlink",
])
def test_pre_capability_v4_cleanup_refuses_signed_malformed_or_unrelated_receipts(installation, host, drift):
    project, settings, _, _, install = installation
    receipt = install(host, strict=False)
    historical = _historical_v4_metadata(receipt)
    entry = next(item for item in historical["ownership"] if item["kind"] != "local_mcp")
    if drift in {"null_capability", "unknown_capability", "malformed_capability", "guessed_semantic"}:
        historical["capability"] = {
            "null_capability": None, "unknown_capability": "semantic",
            "malformed_capability": [], "guessed_semantic": "full_semantic",
        }[drift]
    elif drift == "missing_judgment":
        historical["capabilities"].pop("capture_judgment")
    elif drift == "unknown_judgment":
        historical["capabilities"]["capture_judgment"] = "automatic_candidate_readiness"
    elif drift == "capture_processing":
        historical["capabilities"]["capture_processing"] = "automatic_server_extraction_until_semantic_ready"
    elif drift == "missing_capabilities":
        historical["capabilities"] = None
    elif drift == "extra_metadata":
        historical["capabilities"]["invented_capability"] = True
    elif drift == "missing_ownership":
        historical["ownership"] = [{}]
    elif drift == "malformed_ownership_digest":
        entry["digest"] = "not-a-digest"
    elif drift == "wrong_ownership_digest":
        entry["digest"] = "z" * 64
    elif drift == "malformed_installed_digest":
        historical["installed_files"][0]["digest"] = None
    elif drift == "project":
        historical["project_root"] = str(project.parent / "unrelated-project")
    elif drift == "deployment":
        historical["deployment_id"] = "unrelated-deployment"
    elif drift == "host":
        historical["host"] = "codex" if host != "codex" else "omp"
    elif drift == "runtime":
        historical["runtime_dir"] = str(project.parent / "unrelated-runtime")
    elif drift in {"traversal", "absolute_path", "symlink"}:
        outside = project.parent / "unowned"
        outside.write_text("never remove\n")
        if drift == "symlink":
            (project / "outside-link").symlink_to(outside)
        new_path = {"traversal": "../unowned", "absolute_path": str(outside), "symlink": "outside-link"}[drift]
        for installed in historical["installed_files"]:
            if installed["path"] == entry["path"]:
                installed["path"] = new_path
        entry["path"] = new_path
    hosts._write_receipt(receipt, historical)
    if drift == "receipt_digest":
        historical["ownership_digest"] = "0" * 64
        receipt.write_text(json.dumps(historical))
    paths = [receipt, hosts._claude_config_path(), *project.rglob("*"), project.parent / "unowned"]
    before = {path: path.read_bytes() for path in paths if path.is_file()}
    with pytest.raises(DomainError):
        hosts.uninstall_host(settings, project, host)
    assert all(path.read_bytes() == raw for path, raw in before.items())


def test_pointer_omission_is_explicit_and_preserves_complete_utf8_marker_budget():
    receipt = {
        "host": "omp", "strict": False, "context_budget_bytes": 512,
        "capability": "agent_judged", "capabilities": {"prompt_context": "bounded_opt_in"},
    }
    result = hosts._native_result("omp", "before_agent_start")
    capture = {"state": "committed", "source_pointer": {"snapshot": "한" * 1024}}
    offered = hosts._capture_offer(receipt, "before_agent_start", result, capture)
    text = offered["stdout"]["additionalContext"]
    assert len(text.encode("utf-8")) <= 512
    assert hosts.BOUNDED_CONTEXT_MARKER in text
    assert json.loads(text.removeprefix(hosts.BOUNDED_CONTEXT_MARKER + "\n"))["capture"]["gap"] == "HOST_CAPTURE_POINTER_OMITTED"
    assert "한" not in text


@pytest.mark.parametrize("host", ["claude", "codex", "omp"])
def test_recall_disabled_prompt_carries_capture_status_only_in_metadata(installation, authority, host):
    project, _, _, _, install = installation
    receipt = install(host)
    if host == "omp":
        hosts.handle_hook(receipt, native(
            project, "omp", "input", text="human ingress", source="interactive", hook_instance_id="ingress-operation",
        ))
    result = hosts.handle_hook(receipt, native(
        project, host, "before_agent_start" if host == "omp" else "UserPromptSubmit",
        prompt="human ingress", ingress_operation_id="ingress-operation",
    ))
    assert isinstance(result["capture"], dict)
    assert "additionalContext" not in result["stdout"] and "hookSpecificOutput" not in result["stdout"]
    assert hosts.BOUNDED_CONTEXT_MARKER not in json.dumps(result["stdout"])
    assert not any(call[0] == "/api/context" for call in authority.calls)


@pytest.mark.parametrize("host", ["claude", "codex", "omp"])
def test_personal_opt_in_recall_offers_unclassified_capture_and_caller_selection_guidance(installation, authority, host):
    project, _, _, _, install = installation
    receipt = install(host, strict=False, prompt_recall=True)
    result = hosts.handle_hook(receipt, native(project, host, "before_agent_start" if host == "omp" else "UserPromptSubmit", prompt="Use project conventions"))
    output = result["stdout"]["additionalContext"] if host == "omp" else result["stdout"]["hookSpecificOutput"]["additionalContext"]
    status = json.loads(output.removeprefix(hosts.BOUNDED_CONTEXT_MARKER + "\n").split("\n", 1)[0])
    assert "capture" in status and status["selection"] == "separate_caller_memory_record" and status["candidate_ready"] == "not_claimed"
    assert output.endswith(authority.text)


def test_personal_and_company_receipts_share_the_same_capture_judgment_contract(installation):
    project, settings, agent, producer, install = installation
    personal = hosts.load_receipt(install("codex", strict=False))
    assert personal["capability"] == "agent_judged"
    assert personal["capabilities"]["capture_judgment"] == "unclassified_source_separate_caller_memory_record"
    company = settings.model_copy(update={"mode": "company"})
    assert hosts.install_host(company, project, "project-binding", "codex", agent, producer, strict=False)["replay"] is True
    hosts.uninstall_host(settings, project, "codex")
    replacement = hosts.load_receipt(Path(hosts.install_host(company, project, "project-binding", "codex", agent, producer, strict=False)["receipt"]))
    assert replacement["capability"] == "agent_judged"
    assert replacement["capabilities"] == personal["capabilities"]


def test_omp_reentered_preparation_reuses_ingress_turn_without_new_generation(installation, authority):
    project, _, _, _, install = installation
    receipt = install("omp", prompt_recall=True)
    turn = {"hook_instance_id": "ingress-turn", "adapter_turn_id": "ingress-turn"}
    ingress = hosts.handle_hook(receipt, native(project, "omp", "input", text="human ingress", source="interactive", **turn))
    prepared = native(project, "omp", "before_agent_start", prompt="human ingress", **turn)
    first, again = hosts.handle_hook(receipt, prepared), hosts.handle_hook(receipt, prepared)
    assert first["generation"] == ingress["generation"] + 1 == again["generation"]
    assert first["capture"]["state"] == "durably_spooled" and "capture" not in again
    assert hosts.handle_hook(receipt, action(project, "omp", **turn))["code"] != "HOST_GENERATION_UNOBSERVED"


@pytest.mark.parametrize("boundary,failure", [
    ("__init__", OSError("private raw path diagnostics")),
    ("flush", sqlite3.OperationalError("private raw database diagnostics")),
    ("disposition", DomainError("SPOOL_PATH_DENIED", "private raw diagnostics")),
])
def test_capture_replay_failure_is_a_gap_that_keeps_recall_and_generation(installation, authority, monkeypatch, boundary, failure):
    project, _, _, _, install = installation
    receipt = install("omp", prompt_recall=True)
    ingress = hosts.handle_hook(receipt, native(
        project, "omp", "input", text="human ingress", source="interactive", hook_instance_id="replay-ingress",
    ))
    assert ingress["capture"]["capture_key"]

    def fail(self, *args, **kwargs):
        raise failure

    monkeypatch.setattr(ProducerSpool, boundary, fail)
    result = hosts.handle_hook(receipt, native(
        project, "omp", "before_agent_start", prompt="human ingress", ingress_operation_id="replay-ingress",
    ))
    code = "SPOOL_PATH_DENIED" if boundary == "disposition" else "HOST_SPOOL_UNAVAILABLE"
    assert result["capture"] == {**result["capture"], "state": "gap", "code": code}
    assert result["offered"] is True and result["stdout"]["additionalContext"].endswith(authority.text)
    assert result["generation"] == ingress["generation"] + 1 and result["gaps"][code] == 1
    assert "private raw" not in json.dumps(result)
    assert hosts.handle_hook(receipt, action(project, "omp"))["code"] != "HOST_GENERATION_UNOBSERVED"


@pytest.mark.parametrize("host,event_name", [("claude", "UserPromptSubmit"), ("codex", "UserPromptSubmit"), ("omp", "input")])
def test_source_secret_is_a_fixed_gap_before_origin_and_spool(installation, monkeypatch, host, event_name):
    project, _, _, _, install = installation
    receipt = hosts.load_receipt(install(host, strict=False))
    secret = "ghp_" + "a" * 36
    identity = {"root": "root-001", "path": "path-001", "native_turn": "turn-001", "instance": "instance-001"}

    def forbidden_digest(value):
        raise AssertionError("Rejected source reached origin digest")

    def forbidden_spool(*args):
        raise AssertionError("Rejected source reached the producer spool")

    monkeypatch.setattr(hosts, "canonical_digest", forbidden_digest)
    monkeypatch.setattr(hosts, "ProducerSpool", forbidden_spool)
    result = hosts._capture(
        receipt, native(project, host, event_name, prompt=secret, text=secret, source="interactive"), identity, event_name,
    )
    assert result == {"state": "gap", "code": "SOURCE_SECRET_REJECTED", "effect": "not_started"}
    assert secret not in json.dumps(result)


@pytest.mark.parametrize("existing_state", (False, True), ids=("fresh", "prior-authority"))
def test_omp_preparation_secret_refusal_survives_restart_without_permission_advance(
    installation, monkeypatch, existing_state,
):
    project, _, _, _, install = installation
    receipt_path = install("omp")
    receipt = hosts.load_receipt(receipt_path)
    runtime = Path(receipt["runtime_dir"])
    secret = "ghp_" + "a" * 36
    digest = hosts.canonical_digest

    def secret_free_digest(value):
        assert secret not in json.dumps(value), "Raw secret reached a digest"
        return digest(value)

    monkeypatch.setattr(hosts, "canonical_digest", secret_free_digest)
    event = native(project, "omp", "prepare_prompt", prompt=secret)
    identity = hosts._identity(receipt, event)
    state_path = runtime / (identity["key"] + ".json")
    before = {
        "generation": 7 if existing_state else 0,
        "turn": "prior-turn" if existing_state else None,
        "offered": {"rules": [], "digest": "b" * 64, "generation": 7} if existing_state else None,
        "capture": {"key": "prior-capture", "generation": 7} if existing_state else None,
        "gaps": {"HOST_SESSION_WINDOW_UNOBSERVED": 2} if existing_state else {},
    }
    if existing_state:
        private_io.private_write(state_path, json.dumps(before))
    result = hosts.handle_hook(receipt_path, event)
    assert result["code"] == "SOURCE_SECRET_REJECTED"
    assert result.get("gaps", {}).get("SOURCE_SECRET_REJECTED") == 1
    assert "preparation_id" not in result and secret not in json.dumps(result)
    persisted = hosts._generation_state(state_path.read_bytes())
    assert persisted == {**before, "gaps": {**before["gaps"], "SOURCE_SECRET_REJECTED": 1}}
    restarted = hosts.handle_hook(receipt_path, native(project, "omp", "session_start"))
    assert restarted["gaps"]["SOURCE_SECRET_REJECTED"] == 1
    assert all(secret.encode() not in path.read_bytes() for path in runtime.rglob("*") if path.is_file())


@pytest.mark.asyncio
async def test_host_capture_preserves_benign_utf8_provenance_through_real_authority(installation, capture_authority, monkeypatch):
    import asyncio

    project, settings, agent, producer, _ = installation
    store, actor, binding = capture_authority
    receipt_path = Path(hosts.install_host(settings, project, binding, "omp", agent, producer)["receipt"])
    loop = asyncio.get_running_loop()
    body = " \tDo not export; preserve the exception.\r\n예외와 부정을 보존합니다. "

    class Endpoint:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, route, payload):
            assert route == "/api/capture"
            command = CaptureCommand.model_validate(payload)
            operation = asyncio.run_coroutine_threadsafe(store.capture(actor, command), loop).result(timeout=30)
            return operation.model_dump(mode="json")

    monkeypatch.setattr(hosts, "LocalClient", Endpoint)
    result = await asyncio.to_thread(
        hosts.handle_hook, receipt_path, native(project, "omp", "input", text=body, source="interactive"),
    )
    assert result["capture"]["state"] == "committed"
    pointer = result["capture"]["source_pointer"]
    source = await store.inspect(actor, binding, pointer["source_id"])
    assert source["body"].encode("utf-8") == body.encode("utf-8")
    assert source["speaker"] == "human"
    assert source["coverage"]["capture"]["status"] == "observed_window"


@pytest.mark.parametrize("with_required", [False, True])
@pytest.mark.asyncio
async def test_opt_in_hook_hands_off_unjudged_candidates_without_injecting_them(installation, capture_authority, monkeypatch, with_required):
    import asyncio
    from types import SimpleNamespace

    from test_store_authority import ready_claim

    from agents_memory.application import Application
    from agents_memory.domain import RuleApproval, RuleProposal

    project, settings, agent, producer, _ = installation
    store, actor, binding = capture_authority
    _, claim = await ready_claim(SimpleNamespace(store=store, actor=actor, binding_id=binding))
    if with_required:
        proposal = await store.propose_rule(actor, RuleProposal(
            binding_id=binding, idempotency_key="hook-required", body="Keep customer records local.", required=True,
        ))
        await store.approve_rule(actor, RuleApproval(
            proposal_id=proposal["proposal_id"], expected_digest=proposal["digest"], scope=RuleScope.LOCAL_PROJECT,
            target_bindings=(binding,), target_set_revision=proposal["target_set_revision"], idempotency_key="hook-approval",
        ))
    application = Application(store.settings, store)
    loop = asyncio.get_running_loop()
    observed = []

    class Endpoint:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, route, payload):
            assert route == "/api/context"
            result = asyncio.run_coroutine_threadsafe(
                application.context(actor, ContextCommand.model_validate(payload)), loop,
            ).result(timeout=30)
            observed.append(result)
            return result

    monkeypatch.setattr(hosts, "LocalClient", Endpoint)
    receipt = Path(hosts.install_host(settings, project, binding, "omp", agent, producer, prompt_recall=True)["receipt"])
    result = await asyncio.to_thread(
        hosts.handle_hook, receipt, native(project, "omp", "before_agent_start", prompt="CacheKey"),
    )
    assert observed[0]["status"] == "judgment_required"
    assert observed[0]["candidate_manifest"][0]["claim_id"] == claim.id
    output = result["stdout"]["additionalContext"]
    lines = output.split("\n")
    handoff_line = next(line for line in lines if line.startswith('{"recall":"judgment_required"'))
    handoff = json.loads(handoff_line)
    if with_required:
        assert "Keep customer records local." in output
    # An unjudged statement is never automatic context, not even as a preview.
    assert claim.draft.statement not in output
    assert handoff["trigger"] == "prompt" and handoff["admission_id"] == observed[0]["admission_id"]
    assert handoff["candidate_ids"] == [item["claim_id"] for item in observed[0]["candidate_manifest"]]
    sent = ContextCommand.model_validate({**handoff["request"], "binding_id": binding})
    assert handoff["request"] == hosts._recall_request(sent)
    assert handoff["request"]["query"] == "CacheKey" and handoff["request"]["host"] == "omp"
    assert result["recall"] == {
        "trigger": "prompt", "state": "manifest", "admission_id": observed[0]["admission_id"],
        "candidates": len(handoff["candidate_ids"]),
    }
    assert result["recall_offers"]["offered_recall_admissions"] == 1
    assert result["recall_offers"]["recall_admission_ids"] == [observed[0]["admission_id"]]
    assert len(output.encode()) <= hosts.HOST_CONTEXT_BYTES
    judged = await application.context(actor, ContextCommand.model_validate({
        **handoff["request"], "binding_id": binding, "admission_id": handoff["admission_id"],
        "relevance": [{"claim_id": claim_id, "relevant": True, "reason": "Names the requested key."}
                      for claim_id in handoff["candidate_ids"]],
    }))
    assert judged["judgment_required"] is False and claim.id in judged["refs"]


@pytest.mark.parametrize("capability", ["full_semantic", "lexical_entity"])
@pytest.mark.parametrize("host", ["claude", "codex", "omp"])
def test_exact_capabilityful_v4_receipt_is_cleanup_only(installation, capability, host):
    project, settings, _, _, install = installation
    receipt = install(host, strict=False)
    historical = json.loads(receipt.read_text())
    historical["adapter_version"] = 4
    historical["capability"] = capability
    historical["capabilities"]["scope"] = "registered_binding_plus_cwd_locator_check_not_cwd_authority"
    historical["capabilities"].pop("action_recall")
    historical["capabilities"].pop("capture_judgment")
    if capability == "full_semantic":
        historical["capabilities"]["capture_processing"] = "automatic_server_extraction_until_semantic_ready"
    else:
        historical["capabilities"]["capture_judgment"] = "separate_caller_memory_record_no_automatic_candidate_readiness"
    hosts._write_receipt(receipt, historical)
    with pytest.raises(DomainError) as caught:
        hosts.load_receipt(receipt, allow_legacy=True)
    assert caught.value.code == "HOST_LEGACY_REINSTALL_REQUIRED"
    assert hosts.load_receipt(receipt, allow_legacy=True, active=False)["capability"] == capability
    assert hosts.uninstall_host(settings, project, host)["state"] == "uninstalled"
    assert hosts.load_receipt(install(host, strict=False))["adapter_version"] == hosts.ADAPTER_VERSION


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("prompt_recall", [False, True])
def test_claude_secret_prompt_persists_turn_generation_and_gap_without_recall_or_spool(
    installation, authority, monkeypatch, strict, prompt_recall,
):
    project, _, _, _, install = installation
    receipt_path = install(strict=strict, prompt_recall=prompt_recall)
    receipt = hosts.load_receipt(receipt_path)
    runtime = Path(receipt["runtime_dir"])
    first = hosts.handle_hook(receipt_path, native(project, prompt="ordinary prompt"))
    assert first["generation"] == 1
    assert first.get("offered", False) is prompt_recall
    assert first["capture"]["code"] == "HOST_PROMPT_ORIGIN_UNOBSERVABLE"
    calls = list(authority.calls)

    def forbidden_spool(*args):
        raise AssertionError("Claude secret prompt reached the producer spool")

    monkeypatch.setattr(hosts, "ProducerSpool", forbidden_spool)
    secret = "ghp_" + "a" * 36
    event = native(project, prompt_id="secret-prompt", prompt=secret)
    result = hosts.handle_hook(receipt_path, event)
    assert result["state"] == ("blocked" if strict else "degraded")
    assert result["code"] == "SOURCE_SECRET_REJECTED"
    assert result["capture"] == {"state": "gap", "code": "SOURCE_SECRET_REJECTED", "effect": "not_started"}
    assert result["generation"] == 2
    assert result["gaps"] == {"HOST_PROMPT_ORIGIN_UNOBSERVABLE": 1, "SOURCE_SECRET_REJECTED": 1}
    assert authority.calls == calls and secret not in json.dumps(result)
    state_path = runtime / (hosts._identity(receipt, event)["key"] + ".json")
    state = json.loads(state_path.read_text())
    assert state["turn"] == hosts._identity(receipt, event)["turn"]
    assert state["generation"] == result["generation"] and state["gaps"] == result["gaps"]
    assert state["offered"] is None and state["capture"] is None
    assert secret.encode() not in state_path.read_bytes()
    assert not (runtime / "capture.sqlite3").exists()
    resumed = hosts.handle_hook(receipt_path, action(project, prompt_id="secret-prompt"))
    assert resumed["generation"] == 2 and resumed["code"] != "HOST_GENERATION_UNOBSERVED"
    recovered = hosts.handle_hook(receipt_path, native(project, prompt_id="recovered-prompt", prompt="ordinary next prompt"))
    assert recovered["generation"] == 3
    assert recovered["capture"]["code"] == "HOST_PROMPT_ORIGIN_UNOBSERVABLE"
    assert recovered.get("offered", False) is prompt_recall
    assert recovered["gaps"]["SOURCE_SECRET_REJECTED"] == 1


@pytest.mark.parametrize("host", ["claude", "codex", "omp"])
def test_scope_capability_distinguishes_mcp_authority_and_hook_cwd_with_prior_receipt_cleanup(installation, host):
    project, settings, _, _, install = installation
    receipt_path = install(host, strict=False)
    receipt = hosts.load_receipt(receipt_path)
    assert receipt["capabilities"]["scope"] == "mcp_credential_registered_binding_authority_hook_cwd_locator_check_only"
    receipt["capabilities"]["scope"] = "registered_binding_plus_cwd_locator_check_not_cwd_authority"
    hosts._write_receipt(receipt_path, receipt)
    assert hosts.load_receipt(receipt_path, allow_legacy=True, active=False)["installation_id"] == receipt["installation_id"]
    assert hosts.uninstall_host(settings, project, host)["state"] == "uninstalled"


def test_multithreaded_spawn_crash_preserves_recovery_without_warnings(installation, recwarn):
    project, settings, agent, producer, install = installation
    receipt_path = hosts._receipt_path(settings, project, "claude")
    user = project / "user-owned.json"
    original = b'{"keep":"user-owned"}\n'
    user.write_bytes(original)
    entered, release = threading.Event(), threading.Event()

    def waiting_thread():
        entered.set()
        release.wait()

    thread = threading.Thread(target=waiting_thread)
    thread.start()
    assert entered.wait(1)
    try:
        _abrupt_process(
            hosts.install_host, settings, project, "project-binding", "claude", agent, producer,
            strict=False, crash_path=receipt_path, crash_state="pending",
        )
    finally:
        release.set()
        thread.join(1)
    assert not thread.is_alive()
    recovered = install(strict=False)
    assert hosts.load_receipt(recovered)["state"] == "installed"
    assert user.read_bytes() == original
    assert not list(recwarn)


def test_codex_child_secret_recall_persists_its_turn_without_capturing_child_evidence(
    installation, authority, monkeypatch,
):
    project, _, _, _, install = installation
    receipt_path = install("codex", strict=False, prompt_recall=True)
    receipt = hosts.load_receipt(receipt_path)
    runtime = Path(receipt["runtime_dir"])
    first = hosts.handle_hook(receipt_path, native(
        project, "codex", agent_id="child-one", prompt="ordinary child prompt",
    ))
    assert first["generation"] == 1
    calls = list(authority.calls)

    def forbidden_spool(*args):
        raise AssertionError("An unsupported child source must not reach the producer spool")

    monkeypatch.setattr(hosts, "ProducerSpool", forbidden_spool)
    secret = "ghp_" + "a" * 36
    event = native(project, "codex", agent_id="child-one", turn_id="secret-turn", prompt=secret)
    result = hosts.handle_hook(receipt_path, event)
    assert result["state"] == "degraded" and result["code"] == "SOURCE_SECRET_REJECTED"
    assert result["capture"] == {"state": "gap", "code": "SOURCE_SECRET_REJECTED", "effect": "not_started"}
    assert result["generation"] == 2 and result["gaps"]["SOURCE_SECRET_REJECTED"] == 1
    assert authority.calls == calls and secret not in json.dumps(result)
    state_path = runtime / (hosts._identity(receipt, event)["key"] + ".json")
    state = json.loads(state_path.read_text())
    assert state["turn"] == hosts._identity(receipt, event)["turn"]
    assert state["generation"] == 2 and state["gaps"] == result["gaps"]
    assert state["offered"] is None and state["capture"] is None
    assert secret.encode() not in state_path.read_bytes()
    assert not (runtime / "capture.sqlite3").exists()
    recovered = hosts.handle_hook(receipt_path, native(
        project, "codex", agent_id="child-one", turn_id="recovered-turn", prompt="ordinary next child prompt",
    ))
    assert recovered["generation"] == 3 and recovered["gaps"]["SOURCE_SECRET_REJECTED"] == 1


@pytest.mark.parametrize("host", ["claude", "codex", "omp"])
def test_fresh_install_diagnostic_root_loss_reports_the_durable_install(installation, monkeypatch, host):
    project, settings, agent, producer, _ = installation
    receipt_path = hosts._receipt_path(settings, project, host)
    moved = project.parent / "moved-after-install"
    resume = hosts._resume

    def move_after_resume(*args, **kwargs):
        result = resume(*args, **kwargs)
        project.rename(moved)
        return result

    with monkeypatch.context() as patch:
        patch.setattr(hosts, "_resume", move_after_resume)
        with pytest.raises(DomainError) as refused:
            hosts.install_host(settings, project, "project-binding", host, agent, producer, strict=False)
    assert refused.value.code == "HOST_PROJECT_INVALID"
    assert refused.value.effect == EffectState.UNKNOWN
    assert hosts.load_receipt(receipt_path, active=False, allow_deleted_project=True)["state"] == "installed"
    moved.rename(project)
    assert hosts.install_host(settings, project, "project-binding", host, agent, producer, strict=False)["replay"] is True


@pytest.mark.parametrize("host", ["claude", "codex", "omp"])
@pytest.mark.parametrize("retained_intent", [False, True])
def test_installed_replay_diagnostic_root_loss_reports_only_its_recovery_mutation(
    installation, monkeypatch, host, retained_intent,
):
    project, settings, agent, producer, install = installation
    receipt_path = hosts._receipt_path(settings, project, host)
    if retained_intent:
        _abrupt_process(
            hosts.install_host, settings, project, "project-binding", host, agent, producer,
            strict=False, crash_path=receipt_path, crash_state="installed",
        )
    else:
        assert install(host, strict=False) == receipt_path
    receipt = hosts.load_receipt(receipt_path)
    assert receipt["state"] == "installed"
    intent = hosts._intent_path(receipt)
    assert intent.exists() is retained_intent
    receipt_before = receipt_path.read_bytes()
    owned_before = {
        path: path.read_bytes()
        for path in (hosts._owned_path(project, entry["path"]) for entry in receipt["ownership"])
    }
    moved = project.parent / "moved-after-installed-replay"
    status = hosts.native_memory_status

    def move_before_status(root):
        assert not intent.exists()
        project.rename(moved)
        return status(root)

    with monkeypatch.context() as patch:
        patch.setattr(hosts, "native_memory_status", move_before_status)
        with pytest.raises(DomainError) as refused:
            hosts.install_host(settings, project, "project-binding", host, agent, producer, strict=False)
    assert refused.value.code == "HOST_PROJECT_INVALID"
    assert refused.value.effect == (EffectState.UNKNOWN if retained_intent else EffectState.NOT_STARTED)
    assert not project.exists() and moved.is_dir()
    assert not intent.exists()
    assert receipt_path.read_bytes() == receipt_before
    assert hosts.load_receipt(receipt_path, active=False, allow_deleted_project=True)["state"] == "installed"
    moved.rename(project)
    assert all(path.read_bytes() == content for path, content in owned_before.items())
    assert hosts.install_host(settings, project, "project-binding", host, agent, producer, strict=False)["replay"] is True


def test_omp_hook_service_requests_never_outlive_the_remaining_event_budget(installation, monkeypatch):
    _, _, _, _, install = installation
    receipt_path = install("omp", strict=False, prompt_recall=True)
    dispatched = []

    class DeadlineHonouringEndpoint:
        def __init__(self, base_url, token_file, timeout=120, *, state_dir=None, deployment_id=None, remote_settings=None):
            self.timeout = timeout

        def request(self, path, payload):
            dispatched.append((path, self.timeout))
            time.sleep(self.timeout)
            return {"context": "", "context_bytes": 0, "stamp": {"epoch": 1, "rules": []}}

    monkeypatch.setattr(hosts, "LocalClient", DeadlineHonouringEndpoint)
    budget = 0.4
    project = Path(hosts.load_receipt(receipt_path)["project_root"])
    started = time.monotonic()
    result = hosts.handle_hook(receipt_path, native(
        project, "omp", "before_agent_start", prompt="CacheKey",
        event_deadline_ms=int((time.time() + budget) * 1000),
    ))
    assert time.monotonic() - started < budget + 1
    assert result["code"] == "HOST_EVENT_DEADLINE" and result["state"] == "degraded"
    assert dispatched and all(0 < timeout <= budget for _, timeout in dispatched)
    client = hosts._service_client(hosts.load_receipt(receipt_path), "agent_token_file", 4, time.monotonic() + 0.1)
    client.request("/api/context", {})
    count = len(dispatched)
    with pytest.raises(DomainError) as expired:
        client.request("/api/context", {})
    assert expired.value.code == "HOST_EVENT_DEADLINE"
    assert len(dispatched) == count
