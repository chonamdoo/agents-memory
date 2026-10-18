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


def run_scoped_edit(tmp_path, node_binary, receipt, project, tool_input):
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
    observed_envelope = tmp_path / "observed-envelope.json"
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

        class Authority:
            def __init__(self, *args, **kwargs):
                pass

            def request(self, route, payload):
                if route not in {"/api/context", "/api/required-context"}:
                    raise AssertionError("unexpected endpoint")
                result = compose(ContextCommand.model_validate(payload), rules, (), (),
                                 protected_action=route == "/api/required-context")
                reply = {"context": result.text, "context_bytes": result.byte_count,
                         "stamp": {"epoch": 1, "rules": [list(rule) for rule in result.rule_versions]}}
                if route == "/api/required-context":
                    reply["required"] = bool(result.rule_versions)
                return reply

        hosts.LocalClient = Authority
        raw = sys.stdin.buffer.read()
        Path(sys.argv[3]).write_bytes(raw)
        reply = hosts.handle_hook_input(Path(sys.argv[1]), raw)
        print(json.dumps(reply))
    '''))
    extension = tmp_path / "scoped-extension.mts"
    template = files("agents_memory.host_templates").joinpath("omp.ts").read_text()
    replacement_argv = [sys.executable, "-I", str(hook), str(receipt), str(rules_path), str(observed_envelope)]
    extension.write_text(template.replace(
        "__HOOK_ARGV__", json.dumps(replacement_argv),
    ).replace("__HOST_INPUT_BYTES__", str(hosts.HOST_INPUT_BYTES)))
    input_path = tmp_path / "tool-input.json"
    input_path.write_text(json.dumps(tool_input))
    runner = tmp_path / "scoped-runner.mjs"
    runner.write_text(dedent('''\
        import { readFileSync } from "node:fs";
        import { pathToFileURL } from "node:url";

        const { default: extension } = await import(pathToFileURL(process.argv[2]).href);
        const handlers = new Map();
        const notifications = [];
        extension({ on: (name, handler) => handlers.set(name, handler), registerCommand: () => {} });
        const context = {
          cwd: process.cwd(), agent: { id: "root", kind: "main", depth: 0 },
          model: { api: "anthropic-messages" },
          sessionManager: { getSessionId: () => "scoped-hashline-edit" },
          ui: { notify: (message) => notifications.push(message) },
        };
        await handlers.get("before_agent_start")({ prompt: "Review the scoped action." }, context);
        notifications.length = 0;
        await handlers.get("tool_call")({
          toolName: "edit", toolCallId: "native-edit-one",
          input: JSON.parse(readFileSync(process.argv[3], "utf8")),
        }, context);
        console.log(JSON.stringify({ notifications }));
    '''))
    result = subprocess.run(
        [node_binary, str(runner), str(extension), str(input_path)], cwd=project,
        capture_output=True, text=True, check=True, timeout=20,
    )
    return json.loads(result.stdout), observed_envelope.read_bytes()


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
    outcome, wire = run_scoped_edit(tmp_path, node_binary, receipt, project, {"input": patch})
    visible = "\n".join(outcome["notifications"])
    assert "Retain the alpha invariant." in visible
    assert ("Retain the destination invariant." in visible) == (case == "multiple-files-and-move")
    assert "Unrelated convention must not be delivered." not in visible
    assert "HOST_FOOTPRINT_UNKNOWN" not in visible
    assert PRIVATE_BODY not in visible
    assert PRIVATE_BODY.encode() not in wire


@pytest.mark.parametrize("case,code", (
    ("outside-header", "HOST_SCOPE_UNRESOLVED"),
    ("outside-move", "HOST_SCOPE_UNRESOLVED"),
    ("malformed-with-misleading-path", "HOST_FOOTPRINT_UNKNOWN"),
))
def test_generated_hashline_edit_never_delivers_partial_or_inferred_scope(
    tmp_path, node_binary, installation, case, code,
):
    project, _, _, _, install = installation
    receipt = install("omp")
    if case == "outside-header":
        tool_input = {"input": (
            "*** Begin Patch\n[src/alpha.py#ABCD]\nREM\n[../outside.py#1234]\nREM\n*** End Patch\n"
        )}
    elif case == "outside-move":
        tool_input = {"input": "*** Begin Patch\n[src/alpha.py#ABCD]\nMV ../outside.py\n*** End Patch\n"}
    else:
        tool_input = {"input": "not a complete native patch " + PRIVATE_BODY, "path": "src/alpha.py"}
    outcome, wire = run_scoped_edit(tmp_path, node_binary, receipt, project, tool_input)
    visible = "\n".join(outcome["notifications"])
    assert visible == code or visible == "agents-memory: " + code
    assert "Retain the alpha invariant." not in visible
    assert "Retain the destination invariant." not in visible
    assert PRIVATE_BODY.encode() not in wire
