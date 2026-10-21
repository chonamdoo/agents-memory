from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from importlib.resources import files
from textwrap import dedent

import pytest
from test_host_boundaries import installation as installation
from test_omp_ipc_runtime import node_binary as node_binary

from agents_memory import hosts
from agents_memory.domain import ActiveRule, RuleScope, Selector

PRIVATE_BODY = "synthetic_private_edit_body_not_for_hook_ipc"


def covered_requests(paths):
    """Required context first, then the default action recall for the same footprint."""
    return [{"route": "/api/required-context", "paths": paths}, {"route": "/api/hook-context", "paths": paths}]


def run_scoped_tools(
    tmp_path, node_binary, receipt, project, tool_input, *, events=None, registrations=1, raw_override=None,
):
    rules = [
        ActiveRule(
            id="rule-" + name, revision=1, digest=hashlib.sha256(body.encode()).hexdigest(),
            body=body, selector=Selector(paths=(path,)), exceptions=(), required=True,
            scope=RuleScope.LOCAL_PROJECT, target_bindings=("project-binding",), source_ids=(),
        ).model_dump(mode="json")
        for name, path, body in (
            ("alpha", "src/alpha.py", "Retain the alpha invariant."),
            ("destination", "dst/renamed file.py", "Retain the destination invariant."),
            ("unrelated", "unrelated/other.py", "Unrelated convention must not be delivered."),
        )
    ]
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(json.dumps(rules))
    observed_envelope = tmp_path / "observed-hooks.jsonl"
    hook = tmp_path / "scoped-hook.py"
    hook.write_text(dedent('''\
        import json
        import sys
        from pathlib import Path

        from agents_memory import hosts
        from agents_memory.context import compose
        from agents_memory.domain import ActiveRule, ContextCommand

        rules = tuple(ActiveRule.model_validate_json(json.dumps(item))
                      for item in json.loads(Path(sys.argv[2]).read_text()))

        requests = []

        class Authority:
            def __init__(self, *args, **kwargs):
                pass

            def request(self, route, payload):
                if route not in {"/api/hook-context", "/api/required-context"}:
                    raise AssertionError("unexpected endpoint")
                requests.append({"route": route, "paths": payload["paths"]})
                result = compose(ContextCommand.model_validate(payload), rules, (), (),
                                 protected_action=route == "/api/required-context")
                reply = {"context": result.text, "context_bytes": result.byte_count,
                         "stamp": {"epoch": 1, "rules": [list(rule) for rule in result.rule_versions]}}
                if route == "/api/required-context":
                    reply["required"] = bool(result.rule_versions)
                else:
                    reply.update(admission_id="admission-empty", candidate_manifest=[], judgment_required=False)
                return reply

        hosts.LocalClient = Authority
        raw = sys.stdin.buffer.read()
        envelope = json.loads(raw)
        scenario = json.loads(Path(sys.argv[4]).read_text())
        if envelope.get("event") == "tool_call" and scenario["raw_override"] is not None:
            raw = scenario["raw_override"].encode()
        reply = hosts.handle_hook_input(Path(sys.argv[1]), raw)
        with Path(sys.argv[3]).open("a") as observed:
            observed.write(json.dumps({"envelope": envelope, "result": reply, "requests": requests}) + "\\n")
        print(json.dumps(reply))
    '''))
    extension = tmp_path / "scoped-extension.mts"
    template = files("agents_memory.host_templates").joinpath("omp.ts").read_text()
    input_path = tmp_path / "tool-input.json"
    replacement_argv = [
        sys.executable, "-I", str(hook), str(receipt), str(rules_path), str(observed_envelope), str(input_path),
    ]
    extension.write_text(template.replace(
        "__HOOK_ARGV__", json.dumps(replacement_argv),
    ).replace("__HOST_INPUT_BYTES__", str(hosts.HOST_INPUT_BYTES)))
    input_path.write_text(json.dumps({
        "events": events if events is not None else [
            {"toolName": "edit", "toolCallId": "native-edit-one", "input": tool_input},
        ],
        "registrations": registrations, "raw_override": raw_override,
    }))
    runner = tmp_path / "scoped-runner.mjs"
    runner.write_text(dedent('''\
        import { readFileSync } from "node:fs";
        import { pathToFileURL } from "node:url";

        const { default: extension } = await import(pathToFileURL(process.argv[2]).href);
        const handlers = new Map();
        const commands = new Map();
        const notifications = [];
        const scenario = JSON.parse(readFileSync(process.argv[3], "utf8"));
        const api = {
          on: (name, handler) => handlers.set(name, [...(handlers.get(name) || []), handler]),
          registerCommand: (name, command) => commands.set(name, command),
        };
        for (let index = 0; index < scenario.registrations; index++) extension(api);
        const emit = async (name, event, context) => {
          for (const handler of handlers.get(name) || []) await handler(event, context);
        };
        const context = {
          cwd: process.cwd(), agent: { id: "root", kind: "main", depth: 0 },
          model: { api: "anthropic-messages" },
          sessionManager: { getSessionId: () => "scoped-hashline-edit" },
          ui: { notify: (message) => notifications.push(message) },
        };
        await emit("before_agent_start", { prompt: "Review the scoped action." }, context);
        notifications.length = 0;
        const actions = [];
        for (const event of scenario.events) {
          const before = notifications.length;
          await emit("tool_call", event, { ...context, cwd: event.cwd || context.cwd });
          actions.push({ notifications: notifications.slice(before) });
        }
        let status;
        await commands.get("memory-status").handler("", {
          ...context, ui: { notify: (message) => { status = JSON.parse(message); } },
        });
        console.log(JSON.stringify({ notifications, actions, status, handlers: handlers.get("tool_call").length }));
    '''))
    result = subprocess.run(
        [node_binary, str(runner), str(extension), str(input_path)], cwd=project,
        capture_output=True, text=True, check=True, timeout=20,
    )
    outcome = json.loads(result.stdout)
    wire = observed_envelope.read_bytes()
    outcome["hooks"] = [json.loads(line) for line in wire.splitlines()]
    return outcome, wire


@pytest.mark.parametrize("case", ("multiple-files-and-move", "body-looking-like-targets"))
def test_generated_hashline_edit_delivers_only_whole_applicable_conventions(
    tmp_path, node_binary, installation, case,
):
    project, _, _, _, install = installation
    receipt = install("omp")
    if case == "multiple-files-and-move":
        patch = (
            "*** Begin Patch\n[src/alpha.py#ABCD]\nPUT >1:\n+" + PRIVATE_BODY
            + "\n[src/old.py#1234]\nMV \"dst/renamed file.py\"\n*** End Patch\n"
        )
    else:
        patch = (
            "*** Begin Patch\n[src/alpha.py#ABCD]\nPUT >1:\n+" + PRIVATE_BODY
            + "\n+[../not-a-target.py#1234]\n+MV /not-a-target.py\n*** End Patch\n"
        )
    outcome, wire = run_scoped_tools(tmp_path, node_binary, receipt, project, {"input": patch})
    visible = "\n".join(outcome["notifications"])
    assert "Retain the alpha invariant." in visible
    assert ("Retain the destination invariant." in visible) == (case == "multiple-files-and-move")
    assert "Unrelated convention must not be delivered." not in visible
    assert "HOST_FOOTPRINT_UNKNOWN" not in visible
    assert PRIVATE_BODY not in visible
    assert PRIVATE_BODY.encode() not in wire


@pytest.mark.parametrize("case", ("outside-header", "outside-move"))
def test_generated_hashline_edit_delivers_only_in_project_conventions_without_scope_warning(
    tmp_path, node_binary, installation, case,
):
    project, _, _, _, install = installation
    receipt = install("omp")
    if case == "outside-header":
        tool_input = {"input": (
            "*** Begin Patch\n[src/alpha.py#ABCD]\nREM\n[../outside.py#1234]\nREM\n*** End Patch\n"
        )}
    else:
        tool_input = {"input": "*** Begin Patch\n[src/alpha.py#ABCD]\nMV ../outside.py\n*** End Patch\n"}
    outcome, wire = run_scoped_tools(tmp_path, node_binary, receipt, project, tool_input)
    visible = "\n".join(outcome["notifications"])
    assert "Retain the alpha invariant." in visible
    assert "HOST_SCOPE_UNRESOLVED" not in visible
    assert "Unrelated convention must not be delivered." not in visible
    hook = next(entry for entry in outcome["hooks"] if entry["envelope"]["event"] == "tool_call")
    assert hook["requests"] == covered_requests(["src/alpha.py"])


@pytest.mark.parametrize("patch,complete", (
    ("[src/alpha.py#ABCD]\nPUT 1.=1:\n+" + PRIVATE_BODY + "\n", True),
    ("[src/alpha.py#ABCD]\nPUT >$:\n+" + PRIVATE_BODY, True),
    ("*** Begin Patch\n[src/alpha.py#ABCD]\nPUT 1.=1:\n+" + PRIVATE_BODY + "\n", False),
), ids=("bare", "bare-without-final-newline", "unterminated-wrapper"))
def test_generated_hashline_edit_accepts_the_native_bare_form_only_when_complete(
    tmp_path, node_binary, installation, patch, complete,
):
    project, _, _, _, install = installation
    outcome, wire = run_scoped_tools(tmp_path, node_binary, install("omp"), project, {"input": patch})
    visible = "\n".join(outcome["notifications"])
    hook = next(entry for entry in outcome["hooks"] if entry["envelope"]["event"] == "tool_call")
    if complete:
        assert "Retain the alpha invariant." in visible
        assert hook["requests"] == covered_requests(["src/alpha.py"])
        assert hook["result"]["code"] != "HOST_FOOTPRINT_UNKNOWN"
    else:
        assert hook["result"]["code"] == "HOST_FOOTPRINT_UNKNOWN"
        assert hook["requests"] == []
    assert PRIVATE_BODY.encode() not in wire


def test_generated_hashline_edit_never_infers_scope_from_a_malformed_patch(tmp_path, node_binary, installation):
    project, _, _, _, install = installation
    tool_input = {"input": "not a complete native patch " + PRIVATE_BODY, "path": "src/alpha.py"}
    outcome, wire = run_scoped_tools(tmp_path, node_binary, install("omp"), project, tool_input)
    visible = "\n".join(outcome["notifications"])
    assert "Retain the alpha invariant." not in visible
    hook = next(entry for entry in outcome["hooks"] if entry["envelope"]["event"] == "tool_call")
    assert hook["result"]["code"] == "HOST_FOOTPRINT_UNKNOWN"
    assert hook["requests"] == []
    assert PRIVATE_BODY.encode() not in wire


@pytest.mark.parametrize("path_count", (64, 65))
def test_generated_hashline_edit_never_truncates_its_complete_path_boundary(
    tmp_path, node_binary, installation, path_count,
):
    project, _, _, _, install = installation
    receipt = install("omp")
    paths = ["src/alpha.py", *(f"src/extra-{index}.py" for index in range(path_count - 1))]
    patch = "*** Begin Patch\n" + "".join(f"[{path}#ABCD]\nREM\n" for path in paths) + "*** End Patch\n"
    outcome, _ = run_scoped_tools(tmp_path, node_binary, receipt, project, {"input": patch})
    visible = "\n".join(outcome["notifications"])
    if path_count == 64:
        assert "Retain the alpha invariant." in visible
        assert "HOST_FOOTPRINT_UNKNOWN" not in visible
    else:
        hook = next(entry for entry in outcome["hooks"] if entry["envelope"]["event"] == "tool_call")
        assert hook["result"]["code"] == "HOST_FOOTPRINT_UNKNOWN"
        assert hook["requests"] == []
        assert "Retain the alpha invariant." not in visible


RESOURCE_TARGETS = (
    *(("read", path) for path in (
        "issue://14", "pr://9/diff/all", "skill://architecture",
        "https://example.invalid/reference?q=read#part", "file:///private/example.txt",
        "custom+resource://entry/path:5-9", "proc://",
        "skill://architecture:5-9", "skill://architecture:raw", "artifact://182:5-9",
        "local://report draft.md:5-9", "local://[notes].md", "xd://mcp__codegraph_explore",
    )),
    ("write", "xd://mcp__codegraph_explore"), ("write", "xd://lsp"), ("write", "XD://mcp__codegraph_explore"),
)


def test_resource_reads_keep_every_callback_outside_local_advisory_coverage(tmp_path, node_binary, installation):
    # One generated-extension run per scenario keeps the installed-wheel consumer within its CI budget.
    project, _, _, _, install = installation
    events = [
        {"toolName": tool, "toolCallId": identity, "input": {"path": path}}
        for tool, path in RESOURCE_TARGETS
        for identity in ("resource-one", "resource-two", "resource-one")
    ]
    outcome, _ = run_scoped_tools(tmp_path, node_binary, install("omp"), project, {}, events=events)
    hooks = [entry for entry in outcome["hooks"] if entry["envelope"]["event"] == "tool_call"]
    assert [(entry["envelope"]["tool_name"], entry["envelope"]["tool_input"]["path"], entry["envelope"]["tool_use_id"])
            for entry in hooks] == [(event["toolName"], event["input"]["path"], event["toolCallId"]) for event in events]
    assert outcome["notifications"] == []
    for entry in hooks:
        assert entry["result"]["state"] == "outside_advisory_coverage"
        assert entry["result"]["code"] is None
        assert entry["result"]["stdout"] == {}
        assert entry["result"]["provider_input_observed"] is False
        assert entry["requests"] == []


MALFORMED_INPUTS = (
    {}, {"path": None}, {"path": 42}, {"path": ""}, {"path": ["xd://mcp__agents_memory_memory_inspect"]},
    {"path": "://14"}, {"path": "1issue://14"}, {"path": "issue://bad%escape"}, {"path": "xd://bad%escape"},
    {"path": "issue://14/\nbody"}, {"path": "xd://mcp__agents_memory_memory_inspect\n"},
    {"path": "./notes/issue://14"}, {"path": "./xd://mcp__agents_memory_memory_inspect"},
)
# Writable schemes such as conflict:// and vault:// can change project files natively.
NON_DEVICE_URI_WRITES = (
    "conflict://1", "conflict://*", "vault://notes/plan.md", "local://report.md", "file:///private/example.txt",
)


def test_malformed_resources_and_non_device_uri_writes_remain_visible_refusals(tmp_path, node_binary, installation):
    project, _, _, _, install = installation
    events = [
        *({"toolName": tool, "toolCallId": "invalid-target", "input": inputs}
          for tool in ("read", "write") for inputs in MALFORMED_INPUTS),
        *({"toolName": "write", "toolCallId": "uri-write", "input": {"path": path}} for path in NON_DEVICE_URI_WRITES),
    ]
    outcome, _ = run_scoped_tools(tmp_path, node_binary, install("omp"), project, {}, events=events)
    hooks = [entry for entry in outcome["hooks"] if entry["envelope"]["event"] == "tool_call"]
    assert len(hooks) == len(events)
    for entry in hooks:
        assert entry["result"]["code"] == "HOST_FOOTPRINT_UNKNOWN"
        assert entry["result"]["state"] == "degraded"
        assert entry["requests"] == []
    incident = outcome["status"]["incidents"]["action"]
    assert incident["active"] is True
    assert incident["codes"] == {"HOST_FOOTPRINT_UNKNOWN": len(events)}


@pytest.mark.parametrize("failure,code", (
    ("receipt", "HOST_RECEIPT_UNAVAILABLE"),
    ("envelope", "HOST_ENVELOPE_INVALID"),
    ("nul", "HOST_ENVELOPE_INVALID"),
))
def test_resource_addressing_never_skips_prior_hook_validation(
    tmp_path, node_binary, installation, failure, code,
):
    project, _, _, _, install = installation
    receipt = install("omp")
    events = [
        {"toolName": tool, "toolCallId": "refused-" + tool, "input": {"path": path}}
        for tool, path in (
            ("read", "issue://14"), ("write", "xd://mcp__codegraph_explore"),
            ("write", "xd://mcp__agents_memory_memory_inspect"),
        )
    ]
    for event in events:
        if failure == "nul":
            event["input"]["path"] += "\x00"
    if failure == "receipt":
        receipt.write_text("{}")
    raw_override = '{"event":"tool_call","event":"input"}' if failure == "envelope" else None
    outcome, _ = run_scoped_tools(
        tmp_path, node_binary, receipt, project, {}, events=events, raw_override=raw_override,
    )
    hooks = [entry for entry in outcome["hooks"] if entry["envelope"]["event"] == "tool_call"]
    assert len(hooks) == len(events)
    for entry in hooks:
        assert entry["result"]["code"] == code
        assert entry["result"]["state"] not in {"outside_advisory_coverage", "delegated"}
        assert entry["requests"] == []
    incident = outcome["status"]["incidents"]["action"]
    assert incident["active"] is True
    assert incident["codes"] == {code: len(events)}


def test_resource_reads_never_hide_local_context_or_subsequent_real_refusals(
    tmp_path, node_binary, installation,
):
    project, _, _, _, install = installation
    (project / "src").mkdir()
    (project / "src/plain.py").write_text("plain local contents\n")
    outside = tmp_path / "outside.py"
    outside.write_text("outside the registered project\n")
    events = [
        {"toolName": "read", "toolCallId": "local", "input": {"path": "src/plain.py"}},
        {"toolName": "read", "toolCallId": "required", "input": {"path": "src/alpha.py"}},
        {"toolName": "read", "toolCallId": "resource", "input": {"path": "skill://architecture"}},
        {"toolName": "edit", "toolCallId": "unknown", "input": {"input": "not a complete patch"}},
        {"toolName": "read", "toolCallId": "resource-again", "input": {"path": "issue://14"}},
        {"toolName": "read", "toolCallId": "outside", "input": {"path": str(outside)}},
    ]
    outcome, _ = run_scoped_tools(tmp_path, node_binary, install("omp"), project, {}, events=events)
    hooks = [entry for entry in outcome["hooks"] if entry["envelope"]["event"] == "tool_call"]
    assert [entry["result"]["state"] for entry in hooks] == [
        "ok", "degraded", "outside_advisory_coverage", "degraded", "outside_advisory_coverage",
        "outside_advisory_coverage",
    ]
    assert hooks[0]["requests"] == covered_requests(["src/plain.py"])
    assert outcome["actions"][0]["notifications"] == []
    assert hooks[1]["result"]["code"] == "HOST_PROVIDER_INPUT_UNOBSERVABLE"
    assert "Retain the alpha invariant." in "\n".join(outcome["actions"][1]["notifications"])
    assert outcome["actions"][2]["notifications"] == []
    assert hooks[3]["result"]["code"] == "HOST_FOOTPRINT_UNKNOWN"
    assert "HOST_FOOTPRINT_UNKNOWN" in "\n".join(outcome["actions"][3]["notifications"])
    incident = outcome["status"]["incidents"]["action"]
    assert incident["codes"] == {"HOST_PROVIDER_INPUT_UNOBSERVABLE": 1, "HOST_FOOTPRINT_UNKNOWN": 1}
    assert incident["lastFailure"]["code"] == "HOST_FOOTPRINT_UNKNOWN"
    assert outcome["actions"][4]["notifications"] == []
    assert outcome["actions"][5]["notifications"] == []
    assert hooks[5]["requests"] == []


def test_core_tool_devices_delegate_without_hiding_other_writes(tmp_path, node_binary, installation):
    project, _, _, _, install = installation
    (project / "src").mkdir()
    outside = tmp_path / "outside.py"
    core = ("memory_context", "memory_inspect", "memory_record", "memory_feedback")
    near_misses = (
        "xd://mcp__agents_memory_memory_purge",
        "xd://mcp__agents_memory_memory_inspect:raw", "xd://mcp__agents_memory_memory_inspect?ref=judge",
        "xd://mcp__agents-memory__memory_inspect",
    )
    events = [
        *({"toolName": "write", "toolCallId": tool, "input": {"path": "xd://mcp__agents_memory_" + tool}}
          for tool in core),
        {"toolName": "write", "toolCallId": "scheme-case", "input": {"path": "XD://mcp__agents_memory_memory_inspect"}},
        {"toolName": "read", "toolCallId": "core-docs", "input": {"path": "xd://mcp__agents_memory_memory_inspect"}},
        *({"toolName": "write", "toolCallId": "near-miss", "input": {"path": path}} for path in near_misses),
        {"toolName": "write", "toolCallId": "required", "input": {"path": "src/alpha.py"}},
        {"toolName": "write", "toolCallId": "outside", "input": {"path": str(outside)}},
    ]
    outcome, _ = run_scoped_tools(tmp_path, node_binary, install("omp"), project, {}, events=events)
    hooks = [entry for entry in outcome["hooks"] if entry["envelope"]["event"] == "tool_call"]
    covered = 6 + len(near_misses)
    assert [entry["result"]["state"] for entry in hooks] == [
        *["delegated"] * 5,
        *["outside_advisory_coverage"] * (1 + len(near_misses)), "degraded", "outside_advisory_coverage",
    ]
    assert all(entry["requests"] == [] for entry in hooks[:covered])
    assert [action["notifications"] for action in outcome["actions"][:covered]] == [[]] * covered
    assert hooks[covered]["requests"] == covered_requests(["src/alpha.py"])
    assert "Retain the alpha invariant." in "\n".join(outcome["actions"][covered]["notifications"])
    assert outcome["actions"][covered + 1]["notifications"] == []
    assert hooks[covered + 1]["requests"] == []


def test_additive_resource_handlers_do_not_overwrite_independent_registrations(
    tmp_path, node_binary, installation,
):
    project, _, _, _, install = installation
    events = [{"toolName": "read", "toolCallId": "one-dispatch", "input": {"path": "pr://9"}}]
    outcome, _ = run_scoped_tools(
        tmp_path, node_binary, install("omp"), project, {}, events=events, registrations=2,
    )
    hooks = [entry for entry in outcome["hooks"] if entry["envelope"]["event"] == "tool_call"]
    assert outcome["handlers"] == 2
    assert [entry["envelope"]["tool_use_id"] for entry in hooks] == ["one-dispatch", "one-dispatch"]
    assert [entry["result"]["state"] for entry in hooks] == [
        "outside_advisory_coverage", "outside_advisory_coverage",
    ]
    assert outcome["notifications"] == []
