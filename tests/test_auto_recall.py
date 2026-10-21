from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from test_host_boundaries import installation as installation
from test_host_boundaries import native

from agents_memory import hosts
from agents_memory.cli import parser
from agents_memory.constants import BOUNDED_CONTEXT_MARKER
from agents_memory.domain import ContextCommand, DomainError

CLAIMS = [f"claim_{index:032x}" for index in range(20)]
REQUIRED = "Keep the alpha module offline."
RULE = ["rule-alpha", 1, hashlib.sha256(REQUIRED.encode()).hexdigest()]
REQUEST = {
    "query": "alpha.py", "query_expansions": [], "paths": ["src/alpha.py"], "purpose": None,
    "host": "omp", "snapshot": None, "code_workspace_id": None,
}
TEXT_BUDGET = hosts.HOST_CONTEXT_BYTES - len((BOUNDED_CONTEXT_MARKER + "\n").encode())


def first_call(ids, admission="admission_one"):
    return {
        "admission_id": admission, "judgment_required": bool(ids),
        "status": "judgment_required" if ids else "empty",
        "candidate_manifest": [
            {"claim_id": claim, "inspection_ref": claim, "preview": f"Unjudged preview {index}", "partial": False}
            for index, claim in enumerate(ids)
        ],
    }


@pytest.fixture
def recall_authority(monkeypatch):
    class Endpoint:
        calls = []
        candidates = list(CLAIMS[:3])
        required = True
        required_text = REQUIRED
        recall_error = None

        def __init__(self, *args, **kwargs):
            pass

        def request(self, path, payload):
            type(self).calls.append((path, payload))
            if path == "/api/capture":
                raise DomainError("SERVICE_UNAVAILABLE", "No capture in this scenario")
            if path == "/api/required-context":
                text = self.required_text if self.required else ""
                return {
                    "context": text, "context_bytes": len(text.encode()), "required": self.required,
                    "stamp": {"epoch": 1, "rules": [RULE] if self.required else []},
                }
            assert path == "/api/hook-context"
            if isinstance(self.recall_error, str):
                raise DomainError(self.recall_error, "Optional recall refused")
            if self.recall_error is not None:
                raise self.recall_error
            admission = "admission_" + hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
            return {"context": "", "context_bytes": 0, "stamp": {"epoch": 1, "rules": []}, **first_call(self.candidates, admission)}

        @classmethod
        def routes(cls):
            return [path for path, _ in cls.calls]

    monkeypatch.setattr(hosts, "LocalClient", Endpoint)
    return Endpoint


def omp_read(project, path="src/alpha.py", **fields):
    return native(project, "omp", "tool_call", tool_name="read", tool_input={"path": path}, **fields)


def handoff_of(result):
    context = result["stdout"].get("additionalContext") or result["stdout"].get("hookSpecificOutput", {}).get("additionalContext")
    lines = context.split("\n")
    assert lines[0] == BOUNDED_CONTEXT_MARKER
    return lines, json.loads(lines[-1])


def test_handoff_carries_the_complete_ids_and_exact_request():
    text, state = hosts._relevance_handoff(first_call(CLAIMS), REQUEST, "pre_action_paths", TEXT_BUDGET)
    handoff = json.loads(text)
    assert state == "manifest" and len(text.encode()) <= TEXT_BUDGET
    assert handoff["candidate_ids"] == CLAIMS
    assert handoff["request"] == REQUEST and handoff["admission_id"] == "admission_one"
    assert handoff["next"] == hosts.RELEVANCE_NEXT
    # Unjudged candidate text never reaches the model automatically, however much budget remains.
    assert all("Unjudged preview" not in value for value in (text, json.dumps(handoff)))
    assert set(handoff) == {"recall", "trigger", "admission_id", "request", "candidate_ids", "next"}


def test_overflow_delivers_an_explicit_gap_never_partial_ids():
    text, state = hosts._relevance_handoff(first_call(CLAIMS), REQUEST, "pre_action_paths", 600)
    assert state == "overflow_gap" and len(text.encode()) <= 600
    gap = json.loads(text)
    assert gap["gap"] == "HOST_RELEVANCE_MANIFEST_OVERFLOW" and gap["candidates"] == len(CLAIMS)
    assert not any(claim in text for claim in CLAIMS) and "admission_one" not in text
    assert hosts._relevance_handoff(first_call(CLAIMS), REQUEST, "pre_action_paths", 40) == (None, "not_delivered")


def test_empty_manifest_has_no_handoff_and_invalid_manifests_are_refused():
    assert hosts._relevance_handoff(first_call([]), REQUEST, "prompt", TEXT_BUDGET) == (None, "empty")
    duplicated = first_call(CLAIMS[:2])
    duplicated["candidate_manifest"][1]["claim_id"] = CLAIMS[0]
    for invalid in (duplicated, {**first_call(CLAIMS[:1]), "admission_id": None}, {"candidate_manifest": None}):
        with pytest.raises(DomainError) as refused:
            hosts._relevance_handoff(invalid, REQUEST, "prompt", TEXT_BUDGET)
        assert refused.value.code == "HOST_CONTEXT_INVALID"


def test_action_query_is_deterministic_and_bounded_to_whole_names():
    assert hosts._action_recall_query(("src/alpha.py", "test/alpha.py", "docs/beta.md")) == "alpha.py beta.md"
    assert hosts._action_recall_query((".",)) is None
    names = tuple(f"dir/{'n' * 200}{index}.py" for index in range(4))
    query = hosts._action_recall_query(names)
    assert len(query.encode()) <= 512 and query.split(" ") == [name.split("/")[1] for name in names[:2]]


def test_omp_action_recall_follows_required_context_and_deduplicates_per_submission(installation, recall_authority):
    project, _, _, _, install = installation
    receipt = install("omp")
    assert hosts.load_receipt(receipt)["capabilities"]["action_recall"]["trigger"] == "pre_action_paths"
    hosts.handle_hook(receipt, native(project, "omp", "before_agent_start", prompt="Review the module."))
    assert recall_authority.routes() == []

    first = hosts.handle_hook(receipt, omp_read(project))
    assert recall_authority.routes() == ["/api/required-context", "/api/hook-context"]
    lines, handoff = handoff_of(first)
    assert lines[1] == REQUIRED, "required context is delivered first and stays intact"
    sent = recall_authority.calls[-1][1]
    assert handoff["request"] == hosts._recall_request(ContextCommand.model_validate(sent))
    assert handoff["request"]["paths"] == ["src/alpha.py"] and handoff["request"]["query"] == "alpha.py"
    assert handoff["candidate_ids"] == CLAIMS[:3]
    assert first["code"] == "HOST_PROVIDER_INPUT_UNOBSERVABLE" and first["provider_input_observed"] is False
    assert first["recall"] == {
        "trigger": "pre_action_paths", "state": "manifest", "candidates": 3, "admission_id": handoff["admission_id"],
    }
    assert first["recall_offers"] == {
        "offered_recall_admissions": 1, "recall_admission_ids": [handoff["admission_id"]],
        "unjudged_admissions": "unobserved",
    }

    repeated = hosts.handle_hook(receipt, omp_read(project))
    assert recall_authority.routes()[2:] == ["/api/required-context"]
    assert repeated["recall"] == {"trigger": "pre_action_paths", "state": "deduplicated"}
    assert repeated["stdout"]["additionalContext"] == BOUNDED_CONTEXT_MARKER + "\n" + REQUIRED
    assert repeated["recall_offers"]["offered_recall_admissions"] == 1

    other = hosts.handle_hook(receipt, omp_read(project, "src/beta.py"))
    assert handoff_of(other)[1]["request"]["paths"] == ["src/beta.py"]
    assert other["recall_offers"]["offered_recall_admissions"] == 2

    hosts.handle_hook(receipt, native(project, "omp", "before_agent_start", prompt="Next task.", adapter_turn_id="adapter-turn-two"))
    renewed = hosts.handle_hook(receipt, omp_read(project, adapter_turn_id="adapter-turn-two"))
    assert renewed["recall"]["state"] == "manifest"
    assert handoff_of(renewed)[1]["request"] == handoff["request"]
    assert renewed["recall_offers"]["offered_recall_admissions"] == 1


def test_omp_selector_paths_reach_required_rules_and_unknown_stays_unknown(installation, recall_authority):
    project, _, _, _, install = installation
    (project / "src").mkdir()
    (project / "src" / "alpha.py").write_text("ALPHA = 1\n")
    (project / "data.json").write_text("{}\n")
    receipt = install("omp")
    hosts.handle_hook(receipt, native(project, "omp", "before_agent_start", prompt="Review the module."))

    def required_paths():
        return [payload["paths"] for route, payload in recall_authority.calls if route == "/api/required-context"]

    ranged = hosts.handle_hook(receipt, omp_read(project, "src/alpha.py:1-20"))
    assert required_paths() == [["src/alpha.py"]], "a line range selects a view of the file, not another file"
    assert handoff_of(ranged)[0][1] == REQUIRED
    other_range = hosts.handle_hook(receipt, omp_read(project, "src/alpha.py:30-40"))
    assert other_range["recall"] == {"trigger": "pre_action_paths", "state": "deduplicated"}
    hosts.handle_hook(receipt, omp_read(project, "data.json?q=.items"))
    assert required_paths()[-1] == ["data.json"]

    missing = hosts.handle_hook(receipt, omp_read(project, "src/missing.py:1-5"))
    assert missing["code"] == "HOST_FOOTPRINT_UNKNOWN", "a missing path with a selector-like suffix is unknown, not unmatched"
    climbing = hosts.handle_hook(receipt, omp_read(project, "src/alpha.py:x/../../data.json"))
    assert climbing["code"] == "HOST_FOOTPRINT_UNKNOWN", "a `..` after the selector leaves the target ambiguous"
    created = hosts.handle_hook(receipt, native(
        project, "omp", "tool_call", tool_name="write", tool_input={"path": "src/new_module.py", "content": "NEW = 1\n"},
    ))
    assert created["code"] != "HOST_FOOTPRINT_UNKNOWN" and required_paths()[-1] == ["src/new_module.py"]
    hosts.handle_hook(receipt, native(
        project, "omp", "tool_call", tool_name="write", tool_input={"path": "src/alpha.py:bak", "content": "OLD = 1\n"},
    ))
    assert required_paths()[-1] == ["src/alpha.py:bak"], "a write names the file it creates; there is no view to set aside"
    nested = hosts.handle_hook(receipt, omp_read(project, "notes:2026/todo.md"))
    assert nested["code"] != "HOST_FOOTPRINT_UNKNOWN" and required_paths()[-1] == ["notes:2026/todo.md"]


def test_empty_manifest_adds_nothing_and_is_not_reoffered(installation, recall_authority):
    project, _, _, _, install = installation
    recall_authority.candidates = []
    receipt = install("omp")
    hosts.handle_hook(receipt, native(project, "omp", "before_agent_start", prompt="Review the module."))
    result = hosts.handle_hook(receipt, omp_read(project))
    assert result["stdout"]["additionalContext"] == BOUNDED_CONTEXT_MARKER + "\n" + REQUIRED
    assert result["recall"] == {"trigger": "pre_action_paths", "state": "empty", "candidates": 0}
    assert result["recall_offers"]["offered_recall_admissions"] == 0
    hosts.handle_hook(receipt, omp_read(project))
    assert recall_authority.routes().count("/api/hook-context") == 1


def test_overflow_at_action_time_keeps_required_rules_and_omits_every_id(installation, recall_authority):
    project, _, _, _, install = installation
    recall_authority.candidates = CLAIMS
    recall_authority.required_text = "R" * 1300
    receipt = install("omp")
    hosts.handle_hook(receipt, native(project, "omp", "before_agent_start", prompt="Review the module."))
    result = hosts.handle_hook(receipt, omp_read(project))
    lines, gap = handoff_of(result)
    assert lines[1] == "R" * 1300 and gap["gap"] == "HOST_RELEVANCE_MANIFEST_OVERFLOW"
    assert not any(claim in result["stdout"]["additionalContext"] for claim in CLAIMS)
    assert len(result["stdout"]["additionalContext"].encode()) <= hosts.HOST_CONTEXT_BYTES
    assert result["recall"]["state"] == "overflow_gap" and result["recall_offers"]["offered_recall_admissions"] == 0


@pytest.mark.parametrize("failure,code", [
    ("SERVICE_UNAVAILABLE", "SERVICE_UNAVAILABLE"), (RuntimeError("socket torn down"), "HOST_RECALL_UNAVAILABLE"),
])
def test_optional_recall_failure_keeps_required_context_and_the_action(installation, recall_authority, failure, code):
    project, _, _, _, install = installation
    recall_authority.recall_error = failure
    receipt = install("omp")
    hosts.handle_hook(receipt, native(project, "omp", "before_agent_start", prompt="Review the module."))
    result = hosts.handle_hook(receipt, omp_read(project))
    assert result["code"] == "HOST_PROVIDER_INPUT_UNOBSERVABLE"
    assert result["stdout"]["additionalContext"] == BOUNDED_CONTEXT_MARKER + "\n" + REQUIRED
    assert result["recall"]["state"] == "failed" and result["recall"]["code"] == code
    assert ("exception_type" in result["recall"]) is isinstance(failure, Exception)
    assert result["recall_offers"]["offered_recall_admissions"] == 0
    # A failed recall is not remembered, so the same footprint may be retried after recovery.
    recall_authority.recall_error = None
    retried = hosts.handle_hook(receipt, omp_read(project))
    assert retried["recall"]["state"] == "manifest"


def test_claude_advisory_pre_tool_use_carries_handoff_without_permission_decision(installation, recall_authority):
    project, _, _, _, install = installation
    recall_authority.required = False
    receipt = install("claude", strict=False)
    hosts.handle_hook(receipt, native(project, "claude", "UserPromptSubmit", prompt="Review the module."))
    result = hosts.handle_hook(receipt, native(
        project, "claude", "PreToolUse", tool_name="Read", tool_input={"file_path": str(project / "src/alpha.py")},
    ))
    output = result["stdout"]["hookSpecificOutput"]
    # No permissionDecision: an allow would bypass the user's permission prompt and defer drops the context.
    assert set(output) == {"hookEventName", "additionalContext"} and output["hookEventName"] == "PreToolUse"
    assert set(result["stdout"]) == {"hookSpecificOutput"} and result["state"] == "ok"
    lines, handoff = handoff_of(result)
    assert len(lines) == 2 and handoff["request"]["host"] == "claude"
    assert handoff["candidate_ids"] == CLAIMS[:3]


def test_strict_claude_keeps_deny_semantics_without_action_recall(installation, recall_authority):
    project, _, _, _, install = installation
    receipt = install("claude", strict=True)
    assert "action_recall" not in hosts.load_receipt(receipt)["capabilities"]
    with pytest.raises(DomainError) as refused:
        hosts.capabilities("claude", strict=True, action_recall=True)
    assert refused.value.code == "HOST_ACTION_RECALL_UNSUPPORTED"
    with pytest.raises(DomainError) as explicit:
        install("claude", strict=True, action_recall=True)
    assert explicit.value.code == "HOST_ACTION_RECALL_UNSUPPORTED"
    hosts.handle_hook(receipt, native(project, "claude", "UserPromptSubmit", prompt="Review the module."))
    recall_authority.calls.clear()
    result = hosts.handle_hook(receipt, native(
        project, "claude", "PreToolUse", tool_name="Write", tool_input={"file_path": str(project / "src/alpha.py")},
    ))
    assert result["stdout"]["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "/api/hook-context" not in recall_authority.routes() and "recall" not in result


def test_codex_declares_prompt_time_only_and_registers_no_advisory_action_hook(installation):
    project, _, _, _, install = installation
    receipt = install("codex", strict=False)
    declared = hosts.load_receipt(receipt)["capabilities"]["action_recall"]
    assert declared == {
        "trigger": "unsupported_native_tools_expose_no_path_footprint",
        "delivery": "prompt_recall_only_when_enabled",
    }
    assert "PreToolUse" not in json.loads((project / ".codex/hooks.json").read_text())["hooks"]


def test_pre_action_recall_receipts_stay_active_and_reinstall_is_explicit(installation, recall_authority):
    project, _, _, _, install = installation
    receipt = install("omp", action_recall=False)
    original = receipt.read_bytes()
    loaded = hosts.load_receipt(receipt)
    assert "action_recall" not in loaded["capabilities"] and loaded["adapter_version"] == hosts.ADAPTER_VERSION
    hosts.handle_hook(receipt, native(project, "omp", "before_agent_start", prompt="Review the module."))
    result = hosts.handle_hook(receipt, omp_read(project))
    assert "/api/hook-context" not in recall_authority.routes() and "recall" not in result
    with pytest.raises(DomainError) as changed:
        install("omp")
    assert changed.value.code == "HOST_ALREADY_INSTALLED"
    assert install("omp", action_recall=False) == receipt and receipt.read_bytes() == original


def test_cli_install_leaves_action_recall_to_the_mode_default_with_explicit_opt_out():
    base = ["host-install", "--project", "p", "--binding", "b", "--host", "omp",
            "--agent-token-file", "a", "--producer-token-file", "c"]
    assert parser().parse_args(base).action_recall is None
    assert parser().parse_args([*base, "--no-action-recall"]).action_recall is False


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_fork_installations_exclude_action_recall(installation, recall_authority, host):
    project, settings, _, _, install = installation
    with pytest.raises(DomainError) as declared:
        hosts.capabilities(host, recall_mode="fork-experimental", recall_trial_days=14, action_recall=True)
    assert declared.value.code == "HOST_ACTION_RECALL_UNSUPPORTED"
    with pytest.raises(DomainError) as explicit:
        install(host, strict=False, recall_mode="fork-experimental", action_recall=True)
    assert explicit.value.code == "HOST_ACTION_RECALL_UNSUPPORTED"
    assert list(project.iterdir()) == [] and not settings.state_dir.exists()
    receipt = install(host, strict=False, recall_mode="fork-experimental")
    capabilities = hosts.load_receipt(receipt)["capabilities"]
    assert "action_recall" not in capabilities
    assert capabilities["recall"]["automatic_handoff"] == "workflow_instruction_only_no_admission_or_candidate_ids"
    if host == "claude":
        recall_authority.required = False
        hosts.handle_hook(receipt, native(project, "claude", "UserPromptSubmit", prompt="Review the module."))
        result = hosts.handle_hook(receipt, native(
            project, "claude", "PreToolUse", tool_name="Read", tool_input={"file_path": str(project / "src/alpha.py")},
        ))
        assert "/api/hook-context" not in recall_authority.routes() and "recall" not in result


def test_fork_receipt_carrying_action_recall_is_invalid(installation):
    _, _, _, _, install = installation
    receipt = install("claude", strict=False, recall_mode="fork-experimental")
    document = json.loads(receipt.read_text())
    document["capabilities"]["action_recall"] = hosts.capabilities("claude")["action_recall"]
    hosts._write_receipt(receipt, document)
    with pytest.raises(DomainError) as error:
        hosts.load_receipt(receipt)
    assert error.value.code == "HOST_RECEIPT_INVALID"


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_fork_prompt_recall_hands_off_the_workflow_without_ids(installation, recall_authority, host):
    project, _, _, _, install = installation
    recall_authority.required = False
    receipt = install(host, strict=False, prompt_recall=True, recall_mode="fork-experimental")
    result = hosts.handle_hook(receipt, native(project, host, "UserPromptSubmit", prompt="Review the module."))
    context = result["stdout"].get("additionalContext") or result["stdout"].get("hookSpecificOutput", {}).get("additionalContext")
    assert "/api/hook-context" in recall_authority.routes()
    # Every first-call admission this endpoint issues starts with "admission_".
    assert not any(claim in context for claim in CLAIMS) and "admission_" not in context
    assert "candidate_ids" not in context and "admission_id" not in context
    handoff = next(json.loads(line) for line in context.split("\n") if line.startswith('{"recall"'))
    assert handoff == {
        "recall": "workflow_required", "trigger": "prompt", "workflow": "agents-memory-recall",
        "skill": hosts.RECALL_SKILL_PATHS[host], "candidates": 3, "next": hosts.RECALL_WORKFLOW_NEXT,
    }
    assert result["recall"] == {"trigger": "prompt", "state": "workflow", "candidates": 3}
    runtime = Path(hosts.load_receipt(receipt)["runtime_dir"])
    assert all(b"admission_" not in path.read_bytes() for path in runtime.glob("*.json"))
