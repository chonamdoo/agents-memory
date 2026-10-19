from __future__ import annotations

import copy
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest
from test_host_boundaries import installation as installation

from agents_memory import cli, hosts
from agents_memory.config import Settings
from agents_memory.domain import ContextCommand, DomainError
from agents_memory.fork_recall import (
    RECALL_INPUT_BYTES,
    read_recall_document,
    validate_fork_recall,
)
from agents_memory.hosts import RECALL_SKILL_PATHS
from agents_memory.wire import validate_wire


@pytest.fixture
def recall_evidence():
    request = {
        "binding_id": "project-binding", "query": "Preserve cache-key conditions and conflicts",
        "query_expansions": ["CacheKey", "cache expiry"], "paths": ["src/cache.py"],
        "purpose": "implement", "host": "claude", "snapshot": "snapshot-one",
        "code_workspace_id": "workspace-one", "causal_operation": "operation-one",
        "max_bytes": 4096, "limit": 5,
    }
    candidates = {
        "admission_id": "admission-one", "judgment_required": True,
        "context": "Required rules stay in the parent even if the fork fails.",
        "candidate_manifest": [
            {"claim_id": "claim-one", "inspection_ref": "claim-one", "partial": True},
            {"claim_id": "claim-two", "inspection_ref": "claim-two", "partial": False,
             "preview": "An unjudged preview", "polarity": "positive", "modality": "asserted",
             "arms": ["lexical"], "evidence_role": "unjudged_candidate_not_execution_authority"},
        ],
    }
    result = {
        "admission_id": "admission-one", "status": "complete", "relevance": [
            {"claim_id": "claim-two", "relevant": False, "reason": "Different task scope."},
            {"claim_id": "claim-one", "relevant": True, "reason": "Applies to the current cache change."},
        ],
    }
    return request, candidates, result


def validate(evidence, *, current=None, task="task-one", current_task="task-one"):
    request, candidates, result = evidence
    return validate_fork_recall(
        request, copy.deepcopy(request) if current is None else current, candidates, result,
        task_id=task, current_task_id=current_task,
    )


def test_complete_return_emits_only_unchanged_second_context_arguments(recall_evidence):
    before = copy.deepcopy(recall_evidence)
    second = validate(recall_evidence)
    request, _, result = recall_evidence
    assert second == {**request, "admission_id": result["admission_id"], "relevance": result["relevance"]}
    assert validate_wire(ContextCommand, second).relevance[0].claim_id == "claim-two"
    assert recall_evidence == before
    assert "Required rules" not in json.dumps(second)
    assert "status" not in second and "candidate_manifest" not in second


@pytest.mark.parametrize("status", ["partial", "cancelled", "failed"])
def test_noncomplete_forks_never_supply_second_call(recall_evidence, status):
    recall_evidence[2]["status"] = status
    with pytest.raises(DomainError) as error:
        validate(recall_evidence)
    assert error.value.code == "HOST_RECALL_INCOMPLETE"
    assert recall_evidence[1]["context"].startswith("Required rules")


@pytest.mark.parametrize("mutation", [
    "admission", "missing", "foreign", "duplicate", "extra", "body", "summary", "item-body",
    "string-bool", "int-bool", "empty-reason", "long-reason", "missing-status", "unknown-status",
    "null-relevance", "wrong-admission-type", "manifest-duplicate", "manifest-ref", "manifest-body",
    "manifest-missing", "manifest-type", "manifest-flag", "admission-missing",
])
def test_child_and_manifest_mismatches_are_rejected(recall_evidence, mutation):
    _, candidates, result = recall_evidence
    decisions = result["relevance"]
    if mutation == "admission":
        result["admission_id"] = "foreign-admission"
    elif mutation == "missing":
        decisions.pop()
    elif mutation == "foreign":
        decisions[0]["claim_id"] = "foreign-claim"
    elif mutation == "duplicate":
        decisions[0]["claim_id"] = decisions[1]["claim_id"]
    elif mutation == "extra":
        decisions.append({"claim_id": "foreign-claim", "relevant": False, "reason": "Unlisted."})
    elif mutation in {"body", "summary"}:
        result[mutation] = "Forbidden evidence channel."
    elif mutation == "item-body":
        decisions[0]["body"] = "Forbidden evidence channel."
    elif mutation == "string-bool":
        decisions[0]["relevant"] = "true"
    elif mutation == "int-bool":
        decisions[0]["relevant"] = 1
    elif mutation == "empty-reason":
        decisions[0]["reason"] = "  "
    elif mutation == "long-reason":
        decisions[0]["reason"] = "한" * 171
    elif mutation == "missing-status":
        result.pop("status")
    elif mutation == "unknown-status":
        result["status"] = "finished"
    elif mutation == "null-relevance":
        result["relevance"] = None
    elif mutation == "wrong-admission-type":
        result["admission_id"] = 1
    elif mutation == "manifest-duplicate":
        candidates["candidate_manifest"][1] = copy.deepcopy(candidates["candidate_manifest"][0])
    elif mutation == "manifest-ref":
        candidates["candidate_manifest"][0]["inspection_ref"] = "foreign-claim"
    elif mutation == "manifest-body":
        candidates["candidate_manifest"][0]["body"] = "Unknown field."
    elif mutation == "manifest-missing":
        candidates.pop("candidate_manifest")
    elif mutation == "manifest-type":
        candidates["candidate_manifest"] = {}
    elif mutation == "manifest-flag":
        candidates["judgment_required"] = False
    elif mutation == "admission-missing":
        candidates.pop("admission_id")
    with pytest.raises(DomainError) as error:
        validate(recall_evidence)
    assert error.value.code == "HOST_RECALL_INVALID"


@pytest.mark.parametrize("field,value", [
    ("query", "A changed full query"), ("query_expansions", ["new expansion"]),
    ("paths", ["src/other.py"]), ("purpose", "review"), ("host", "codex"),
    ("snapshot", "snapshot-two"), ("code_workspace_id", "workspace-two"),
    ("causal_operation", "operation-two"), ("max_bytes", 2048), ("limit", 3),
    ("binding_id", "other-binding"),
])
def test_every_frozen_request_field_is_checked(recall_evidence, field, value):
    current = {**recall_evidence[0], field: value}
    with pytest.raises(DomainError) as error:
        validate(recall_evidence, current=current)
    assert error.value.code == "HOST_RECALL_STALE"


def test_omitted_and_explicit_default_request_fields_are_not_interchangeable(recall_evidence):
    recall_evidence[0].pop("limit")
    with pytest.raises(DomainError) as error:
        validate(recall_evidence, current={**recall_evidence[0], "limit": 3})
    assert error.value.code == "HOST_RECALL_STALE"


@pytest.mark.parametrize("task,current", [("task-one", "task-two"), ("", ""), (" ", " "), (1, 1)])
def test_changed_or_missing_actual_task_assertion_is_rejected(recall_evidence, task, current):
    with pytest.raises(DomainError) as error:
        validate(recall_evidence, task=task, current_task=current)
    assert error.value.code == "HOST_RECALL_STALE"


@pytest.mark.parametrize("field,value", [("admission_id", None), ("relevance", None), ("body", "unknown"), ("limit", True)])
def test_first_request_rejects_second_call_fields_unknown_fields_and_coercion(recall_evidence, field, value):
    recall_evidence[0][field] = value
    with pytest.raises(DomainError) as error:
        validate(recall_evidence)
    assert error.value.code == "HOST_RECALL_INVALID"


@pytest.mark.parametrize("raw", [
    b'{"status":"complete","status":"complete"}', b'{"status":"complete"',
    b'{"relevance": [', b'{"x":NaN}', b'[]', b'{"x":"\\u0000"}', b'{"x":"\\ud800"}',
])
def test_local_reader_rejects_duplicate_truncated_and_invalid_json(tmp_path, raw):
    document = tmp_path / "result.json"
    document.write_bytes(raw)
    with pytest.raises((ValueError, UnicodeError)):
        read_recall_document(document, project_root=tmp_path / "project")


def test_local_reader_is_bounded_and_refuses_symlinks(tmp_path):
    document = tmp_path / "result.json"
    document.write_bytes(b" " * (RECALL_INPUT_BYTES + 1))
    with pytest.raises(DomainError):
        read_recall_document(document, project_root=tmp_path / "project")
    link = tmp_path / "linked.json"
    link.symlink_to(document)
    with pytest.raises(DomainError):
        read_recall_document(link, project_root=tmp_path / "project")
    evidence = tmp_path / "evidence"
    evidence.mkdir(mode=0o700)
    (evidence / "result.json").write_text("{}")
    linked_directory = tmp_path / "linked-evidence"
    linked_directory.symlink_to(evidence, target_is_directory=True)
    with pytest.raises(DomainError):
        read_recall_document(linked_directory / "result.json", project_root=tmp_path / "project")


def test_private_evidence_directory_outside_project_is_accepted(tmp_path):
    evidence = tmp_path / "recall"
    evidence.mkdir(mode=0o700)
    (evidence / "result.json").write_text('{"status":"complete"}')
    (evidence / "result.json").chmod(0o644)
    assert read_recall_document(evidence / "result.json", project_root=tmp_path / "project") == {"status": "complete"}


@pytest.mark.parametrize("mode", [0o750, 0o705, 0o755, 0o777])
def test_group_or_world_accessible_evidence_directory_is_refused(tmp_path, mode):
    evidence = tmp_path / "recall"
    evidence.mkdir()
    (evidence / "result.json").write_text('{"status":"complete"}')
    evidence.chmod(mode)
    with pytest.raises(DomainError) as denied:
        read_recall_document(evidence / "result.json", project_root=tmp_path / "project")
    assert denied.value.code == "PATH_DENIED"


@pytest.mark.parametrize("relative", [".", "nested/recall"])
def test_project_tree_evidence_is_refused_even_when_private(tmp_path, relative):
    project = tmp_path / "project"
    evidence = project / relative
    evidence.mkdir(parents=True, exist_ok=True)
    evidence.chmod(0o700)
    (evidence / "result.json").write_text('{"status":"complete"}')
    with pytest.raises(DomainError) as denied:
        read_recall_document(evidence / "result.json", project_root=project)
    assert denied.value.code == "PATH_DENIED"
    linked_project = tmp_path / "linked-project"
    linked_project.symlink_to(project, target_is_directory=True)
    with pytest.raises(DomainError) as aliased:
        read_recall_document(evidence / "result.json", project_root=linked_project)
    assert aliased.value.code == "PATH_DENIED"
    variant = tmp_path / "PROJECT" / relative
    if variant.exists() and os.path.samefile(variant, evidence):
        # Case-insensitive volumes accept another spelling of the same project directory.
        with pytest.raises(DomainError) as respelled:
            read_recall_document(variant / "result.json", project_root=project)
        assert respelled.value.code == "PATH_DENIED"


def test_hard_linked_evidence_is_refused(tmp_path):
    evidence = tmp_path / "recall"
    evidence.mkdir(mode=0o700)
    original = tmp_path / "elsewhere.json"
    original.write_text("{}")
    os.link(original, evidence / "result.json")
    with pytest.raises(DomainError) as denied:
        read_recall_document(evidence / "result.json", project_root=tmp_path / "project")
    assert denied.value.code == "PATH_DENIED"


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_experimental_skill_is_receipt_owned_replayed_and_removed(installation, host):
    project, settings, _, _, install = installation
    (project / "AGENTS.md").write_text("User-owned root instructions.\n")
    (project / "CLAUDE.md").write_text("User-owned Claude instructions.\n")
    receipt_path = install(host, strict=False, recall_mode="fork-experimental", recall_trial_days=7)
    receipt = hosts.load_fork_recall_receipt(receipt_path)
    asset = project / RECALL_SKILL_PATHS[host]
    original = asset.read_bytes()
    assert receipt["adapter_version"] == 6
    assert receipt["recall_mode"] == "fork-experimental"
    assert receipt["recall_trial"]["days"] == 7
    assert receipt["recall_trial"]["automatic_promotion"] is False
    assert receipt["capabilities"] == hosts.capabilities(host, recall_mode="fork-experimental", recall_trial_days=7)
    assert receipt["capabilities"]["recall"] == {
        "mode": "fork-experimental", "skill": RECALL_SKILL_PATHS[host], "trial_days": 7,
        "automatic_promotion": False,
        "judgment": "parent_context_calls_native_full_history_fork_child_relevance",
        "automatic_handoff": "workflow_instruction_only_no_admission_or_candidate_ids",
        "evidence": "per_invocation_owner_only_directory_outside_project",
        "gaps": [
            "child_inspect_only_instruction_not_enforced",
            "child_mcp_availability_unverified",
            "no_fallback_failed_fork_ends_optional_recall",
        ],
    }
    assert receipt["capabilities"]["prompt_context"] == "disabled" and "action_recall" not in receipt["capabilities"]
    assert any(entry["path"] == RECALL_SKILL_PATHS[host] and entry["kind"] == "file" for entry in receipt["ownership"])
    replay = install(host, strict=False, recall_mode="fork-experimental", recall_trial_days=7)
    assert replay == receipt_path and asset.read_bytes() == original
    assert hosts.load_receipt(replay)["installation_id"] == receipt["installation_id"]
    with pytest.raises(DomainError) as error:
        install(host, strict=False)
    assert error.value.code == "HOST_ALREADY_INSTALLED"
    with pytest.raises(DomainError):
        install(host, strict=False, recall_mode="fork-experimental", recall_trial_days=14)
    assert hosts.uninstall_host(settings, project, host)["state"] == "uninstalled"
    assert not asset.exists()
    assert (project / "AGENTS.md").read_text() == "User-owned root instructions.\n"
    assert (project / "CLAUDE.md").read_text() == "User-owned Claude instructions.\n"


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_exact_existing_adapter6_inline_receipts_stay_active_and_replayable(installation, host):
    project, settings, _, _, install = installation
    receipt_path = install(host, strict=False)
    receipt = hosts.load_receipt(receipt_path)
    original = receipt_path.read_bytes()
    assert receipt["adapter_version"] == 6
    assert "recall_mode" not in receipt and "recall_trial" not in receipt
    assert receipt["capabilities"] == hosts.capabilities(host)
    assert not any(entry["path"] in RECALL_SKILL_PATHS.values() for entry in receipt["ownership"])
    assert install(host, strict=False) == receipt_path
    assert receipt_path.read_bytes() == original
    with pytest.raises(DomainError) as error:
        hosts.load_fork_recall_receipt(receipt_path)
    assert error.value.code == "HOST_RECALL_OPT_IN_REQUIRED"
    assert hosts.uninstall_host(settings, project, host)["state"] == "uninstalled"


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_install_result_declares_experimental_recall_only_when_selected(installation, host):
    project, settings, agent, producer, _ = installation
    inline = hosts.install_host(settings, project, "project-binding", host, agent, producer, strict=False)
    assert "recall" not in inline["capabilities"] and "recall_trial" not in inline
    assert hosts.uninstall_host(settings, project, host)["state"] == "uninstalled"
    selected = {"strict": False, "recall_mode": "fork-experimental", "recall_trial_days": 9}
    fork = hosts.install_host(settings, project, "project-binding", host, agent, producer, **selected)
    receipt = hosts.load_fork_recall_receipt(Path(fork["receipt"]))
    declared = fork["capabilities"]["recall"]
    assert (declared["mode"], declared["skill"], declared["trial_days"], declared["automatic_promotion"]) == (
        "fork-experimental", RECALL_SKILL_PATHS[host], 9, False,
    )
    assert set(declared["gaps"]) == {
        "child_inspect_only_instruction_not_enforced", "child_mcp_availability_unverified",
        "no_fallback_failed_fork_ends_optional_recall",
    }
    assert fork["recall_trial"] == receipt["recall_trial"] == {
        "days": 9, "started_at": receipt["recall_trial"]["started_at"], "automatic_promotion": False,
    }
    replay = hosts.install_host(settings, project, "project-binding", host, agent, producer, **selected)
    assert replay["replay"] is True
    assert replay["capabilities"] == fork["capabilities"] and replay["recall_trial"] == fork["recall_trial"]


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_drifted_or_foreign_native_skill_is_preserved(installation, host):
    project, settings, _, _, install = installation
    asset = project / RECALL_SKILL_PATHS[host]
    asset.parent.mkdir(parents=True)
    asset.write_text("Foreign skill.\n")
    with pytest.raises(DomainError) as conflict:
        install(host, strict=False, recall_mode="fork-experimental")
    assert conflict.value.code == "HOST_ENTRY_CONFLICT"
    assert asset.read_text() == "Foreign skill.\n"
    asset.unlink()
    receipt_path = install(host, strict=False, recall_mode="fork-experimental")
    asset.write_text(asset.read_text() + "User modification.\n")
    before = {entry["path"]: (project / entry["path"]).read_bytes() for entry in hosts.load_receipt(receipt_path)["ownership"]}
    for action in (lambda: hosts.load_fork_recall_receipt(receipt_path), lambda: hosts.uninstall_host(settings, project, host)):
        with pytest.raises(DomainError):
            action()
    assert before == {path: (project / path).read_bytes() for path in before}


@pytest.mark.parametrize("mutation", [
    "mode-missing", "inline", "days", "bool-days", "promotion", "start", "extra",
    "undeclared", "declared-window", "declared-gaps",
])
def test_experimental_receipt_requires_exact_explicit_optin(installation, mutation):
    _, _, _, _, install = installation
    receipt_path = install("codex", strict=False, recall_mode="fork-experimental")
    receipt = hosts.load_receipt(receipt_path)
    if mutation == "mode-missing":
        receipt.pop("recall_mode")
    elif mutation == "inline":
        receipt["recall_mode"] = "inline"
    elif mutation == "days":
        receipt["recall_trial"]["days"] = 15
    elif mutation == "bool-days":
        receipt["recall_trial"]["days"] = True
    elif mutation == "promotion":
        receipt["recall_trial"]["automatic_promotion"] = True
    elif mutation == "start":
        receipt["recall_trial"]["started_at"] = 0
    elif mutation == "extra":
        receipt["recall_trial"]["support"] = "promoted"
    elif mutation == "undeclared":
        receipt["capabilities"].pop("recall")
    elif mutation == "declared-window":
        receipt["capabilities"]["recall"]["trial_days"] = 7
    elif mutation == "declared-gaps":
        receipt["capabilities"]["recall"]["gaps"] = []
    hosts._write_receipt(receipt_path, receipt)
    with pytest.raises(DomainError) as error:
        hosts.load_receipt(receipt_path)
    assert error.value.code == "HOST_RECEIPT_INVALID"


def test_elapsed_trial_never_promotes_or_switches_mode(installation, monkeypatch):
    _, _, _, _, install = installation
    monkeypatch.setattr(hosts.time, "time", lambda: 1)
    receipt_path = install("codex", strict=False, recall_mode="fork-experimental", recall_trial_days=7)
    monkeypatch.setattr(hosts.time, "time", lambda: 60 * 60 * 24 * 30)
    assert install("codex", strict=False, recall_mode="fork-experimental", recall_trial_days=7) == receipt_path
    receipt = hosts.load_fork_recall_receipt(receipt_path)
    assert receipt["recall_mode"] == "fork-experimental" and receipt["recall_trial"]["started_at"] == 1


@pytest.mark.parametrize("host", ["claude", "codex"])
@pytest.mark.parametrize("recover", ["install", "cancel"])
def test_experimental_asset_participates_in_pending_intent_recovery(installation, monkeypatch, host, recover):
    project, settings, _, _, install = installation

    def interrupt(*args):
        raise DomainError("SYNTHETIC_INTERRUPTION", "Interrupt after the durable ownership intent")

    with monkeypatch.context() as patch:
        patch.setattr(hosts, "_resume", interrupt)
        with pytest.raises(DomainError):
            install(host, strict=False, recall_mode="fork-experimental")
    receipt_path = hosts._receipt_path(settings, project, host)
    pending = hosts.load_receipt(receipt_path, active=False)
    assert pending["state"] == "pending"
    assert any(entry["path"] == RECALL_SKILL_PATHS[host] for entry in pending["ownership"])
    with pytest.raises(DomainError) as mismatch:
        install(host, strict=False)
    assert mismatch.value.code == "HOST_RECOVERY_SCOPE_CONFLICT"
    if recover == "install":
        assert install(host, strict=False, recall_mode="fork-experimental") == receipt_path
        assert (project / RECALL_SKILL_PATHS[host]).exists()
    assert hosts.uninstall_host(settings, project, host)["state"] == "uninstalled"
    assert not (project / RECALL_SKILL_PATHS[host]).exists()


@pytest.mark.parametrize("mode,days,host,code", [
    ("fork-experimental", 14, "omp", "HOST_RECALL_UNSUPPORTED"),
    ("unknown", 14, "codex", "HOST_RECALL_MODE_INVALID"),
    ("fork-experimental", 6, "codex", "HOST_RECALL_MODE_INVALID"),
    ("fork-experimental", 15, "codex", "HOST_RECALL_MODE_INVALID"),
    ("fork-experimental", True, "codex", "HOST_RECALL_MODE_INVALID"),
])
def test_invalid_modes_are_refused_before_configuration_writes(installation, mode, days, host, code):
    project, settings, _, _, install = installation
    with pytest.raises(DomainError) as error:
        install(host, strict=False, recall_mode=mode, recall_trial_days=days)
    assert error.value.code == code
    assert list(project.iterdir()) == [] and not settings.state_dir.exists()


@pytest.mark.parametrize("host,code", [("claude", "HOST_RECALL_UNSUPPORTED"), ("codex", "HOST_STRICT_UNSUPPORTED")])
def test_strict_fork_recall_is_refused_before_configuration_writes(installation, host, code):
    # Strict Claude denies the Agent and Bash calls the workflow needs; Codex strict is refused outright.
    project, settings, _, _, install = installation
    with pytest.raises(DomainError) as error:
        install(host, strict=True, recall_mode="fork-experimental")
    assert error.value.code == code
    assert list(project.iterdir()) == [] and not settings.state_dir.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("host", ["claude", "codex"])
async def test_validator_cli_is_local_only_and_receipt_bound(installation, recall_evidence, monkeypatch, tmp_path, host):
    _, _, _, _, install = installation
    receipt_path = install(host, strict=False, recall_mode="fork-experimental")
    request, candidates, result = recall_evidence
    request["host"] = host
    args = ["--config", str(tmp_path / "missing-config.json"), "host-recall-validate", "--receipt", str(receipt_path)]
    for option, name, value in (
        ("--request-file", "request", request), ("--current-request-file", "current", request),
        ("--candidate-file", "candidates", candidates), ("--result-file", "result", result),
    ):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(value))
        args.extend([option, str(path)])
    args.extend(["--task-id", "task-one", "--current-task-id", "task-one"])

    def forbidden(*args, **kwargs):
        pytest.fail("Local recall validation reached authority configuration or network dispatch")

    monkeypatch.setattr(cli, "load_connection_settings", forbidden)
    monkeypatch.setattr(cli, "client_from_settings", forbidden)
    monkeypatch.setattr(hosts.LocalClient, "request", forbidden)
    second = await cli.execute(cli.parser().parse_args(args))
    assert second == validate(recall_evidence)
    result_file = tmp_path / "result.json"
    result_file.write_text('{"status":"complete","status":"complete"}')
    with pytest.raises(ValueError):
        await cli.execute(cli.parser().parse_args(args))
    result_file.write_text(json.dumps(result))
    args[-1] = "other-task"
    with pytest.raises(DomainError) as stale:
        await cli.execute(cli.parser().parse_args(args))
    assert stale.value.code == "HOST_RECALL_STALE"
    args[-1] = "task-one"
    request["binding_id"] = "other-binding"
    (tmp_path / "request.json").write_text(json.dumps(request))
    with pytest.raises(DomainError) as scope:
        await cli.execute(cli.parser().parse_args(args))
    assert scope.value.code == "HOST_SCOPE_DENIED"
    request["binding_id"] = "project-binding"
    request["host"] = "codex" if host == "claude" else "claude"
    (tmp_path / "request.json").write_text(json.dumps(request))
    with pytest.raises(DomainError) as foreign_host:
        await cli.execute(cli.parser().parse_args(args))
    assert foreign_host.value.code == "HOST_SCOPE_DENIED"
    request["host"] = host
    (tmp_path / "request.json").write_text(json.dumps(request))
    project = Path(hosts.load_receipt(receipt_path)["project_root"])
    project.chmod(0o700)
    (project / "result.json").write_text(json.dumps(result))
    args[args.index("--result-file") + 1] = str(project / "result.json")
    with pytest.raises(DomainError) as in_project:
        await cli.execute(cli.parser().parse_args(args))
    assert in_project.value.code == "PATH_DENIED"


def test_cli_mode_defaults_and_trial_bounds(tmp_path):
    base = ["host-install", "--project", str(tmp_path), "--binding", "binding-one", "--host", "codex",
            "--agent-token-file", "agent.token", "--producer-token-file", "producer.token"]
    args = cli.parser().parse_args(base)
    assert args.recall_mode == "inline" and args.recall_trial_days == 14
    assert args.prompt_recall is False
    for days in ("6", "15", "true"):
        with pytest.raises(SystemExit):
            cli.parser().parse_args([*base, "--recall-trial-days", days])


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_interrupted_removal_replays_owned_skill_removal(installation, monkeypatch, host):
    project, settings, _, _, install = installation
    receipt_path = install(host, strict=False, recall_mode="fork-experimental")

    def interrupt(*args):
        raise DomainError("SYNTHETIC_INTERRUPTION", "Interrupt after the durable removal intent")

    with monkeypatch.context() as patch:
        patch.setattr(hosts, "_resume", interrupt)
        with pytest.raises(DomainError):
            hosts.uninstall_host(settings, project, host)
    assert hosts.load_receipt(receipt_path, active=False)["state"] == "removing"
    assert (project / RECALL_SKILL_PATHS[host]).exists()
    assert hosts.uninstall_host(settings, project, host)["state"] == "uninstalled"
    assert not (project / RECALL_SKILL_PATHS[host]).exists()



def test_complete_manifest_judgment_is_not_truncated_to_delivery_limit(recall_evidence):
    request, candidates, result = recall_evidence
    request["limit"] = 1
    candidates["candidate_manifest"] = [
        {"claim_id": f"claim-{index}", "inspection_ref": f"claim-{index}", "partial": True}
        for index in range(20)
    ]
    result["relevance"] = [
        {"claim_id": f"claim-{index}", "relevant": index == 19, "reason": "Task-specific judgment."}
        for index in range(20)
    ]
    assert len(validate(recall_evidence)["relevance"]) == 20
    candidates["candidate_manifest"].append(
        {"claim_id": "claim-extra", "inspection_ref": "claim-extra", "partial": False},
    )
    with pytest.raises(DomainError) as overflow:
        validate(recall_evidence)
    assert overflow.value.code == "HOST_RECALL_INVALID"


@pytest.mark.asyncio
async def test_validator_cli_refuses_inline_receipt_before_reading_supplied_evidence(installation, tmp_path):
    _, _, _, _, install = installation
    receipt = install("codex", strict=False)
    arguments = cli.parser().parse_args([
        "host-recall-validate", "--receipt", str(receipt),
        "--request-file", str(tmp_path / "absent-request.json"),
        "--current-request-file", str(tmp_path / "absent-current.json"),
        "--candidate-file", str(tmp_path / "absent-candidates.json"),
        "--result-file", str(tmp_path / "absent-result.json"),
        "--task-id", "task-one", "--current-task-id", "task-one",
    ])
    with pytest.raises(DomainError) as denied:
        await cli.execute(arguments)
    assert denied.value.code == "HOST_RECALL_OPT_IN_REQUIRED"


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_installed_workflow_commands_execute_with_shell_metacharacter_paths(
    installation, recall_evidence, monkeypatch, tmp_path, host,
):
    project, settings, agent, producer, _ = installation
    hostile = "dir with space $(touch PWNED) `touch PWNED` ; & | 'single\" \\ *"
    interpreter = tmp_path / ("python " + hostile) / "python3"
    interpreter.parent.mkdir()
    interpreter.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n')
    interpreter.chmod(0o700)
    monkeypatch.setattr(sys, "executable", str(interpreter))
    native_home = tmp_path / ("claude " + hostile)
    native_home.mkdir(mode=0o700)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(native_home))
    hostile_settings = Settings(
        deployment_id=settings.deployment_id, realm=settings.realm, mode=settings.mode,
        database_dsn=settings.database_dsn, state_dir=tmp_path / ("state " + hostile),
        journal_dir=settings.journal_dir, spool_limit_bytes=settings.spool_limit_bytes,
    )
    receipt = hosts.install_host(
        hostile_settings, project, "project-binding", host, agent, producer,
        strict=False, recall_mode="fork-experimental",
    )["receipt"]
    assert hostile in receipt
    request, candidates, result = recall_evidence
    request["host"] = host
    skill = (project / RECALL_SKILL_PATHS[host]).read_text()
    assert shlex.quote(str(interpreter)) in skill
    create, validator, remove = (dedent(block) for block in re.findall(r"```sh\n(.*?)```", skill, re.S))
    temporary = tmp_path / ("tmp " + hostile)
    temporary.mkdir(mode=0o700)
    environment = {**os.environ, "TMPDIR": str(temporary), "FROZEN_TASK_ID": "task-one", "CURRENT_TASK_ID": "task-one"}

    def run(command, **variables):
        return subprocess.run(
            ["/bin/sh", "-c", command], cwd=project, capture_output=True, text=True,
            env={**environment, **variables}, check=True, timeout=30,
        )

    recall_dir = Path(run(create).stdout.strip())
    assert recall_dir.parent == temporary and recall_dir.stat().st_mode & 0o777 == 0o700
    for name, value in (
        ("request", request), ("current-request", request),
        ("candidates", candidates), ("result", result),
    ):
        (recall_dir / f"{name}.json").write_text(json.dumps(value))
    second = json.loads(run(validator, RECALL_DIR=str(recall_dir)).stdout)
    assert second["admission_id"] == candidates["admission_id"]
    assert [(item["claim_id"], item["relevant"]) for item in second["relevance"]] == [
        (item["claim_id"], item["relevant"]) for item in result["relevance"]
    ]
    run(remove, RECALL_DIR=str(recall_dir))
    assert not recall_dir.exists()
    assert not [path for path in (project, tmp_path) if (path / "PWNED").exists()]
    assert not any((project / f"{name}.json").exists() for name in ("request", "current-request", "candidates", "result"))
