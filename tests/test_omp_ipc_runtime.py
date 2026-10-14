from __future__ import annotations

import json
import shutil
import subprocess
import sys
from importlib.resources import files
from textwrap import dedent

import pytest

from agents_memory.hosts import HOST_INPUT_BYTES


@pytest.fixture(scope="module")
def node_binary():
    binary = shutil.which("node")
    if binary is None:
        pytest.skip("Node 24+ required to exercise the generated TypeScript extension")
    version = subprocess.run([binary, "--version"], capture_output=True, text=True, check=True)
    if int(version.stdout.lstrip("v").split(".")[0]) < 24:
        pytest.skip("Node 24+ required to exercise the generated TypeScript extension")
    return binary


def exercise_generated_reply(
    tmp_path, node_binary, invalid_reply, *, malformed_event="before_agent_start", consumer="before_agent_start",
):
    hook = tmp_path / "reply.py"
    hook.write_text(dedent('''\
        import json
        import sys

        envelope = json.load(sys.stdin)
        reply = {"state": "ok", "stdout": {}, "provider_input_observed": False,
                 "preparation_id": "a" * 64}
        if envelope["event"] == sys.argv[2]:
            reply.update(json.loads(sys.argv[1]))
        print(json.dumps(reply))
    '''))
    template = files("agents_memory.host_templates").joinpath("omp.ts").read_text()
    extension = tmp_path / "agents-memory.mts"
    extension.write_text(template.replace(
        "__HOOK_ARGV__", json.dumps([sys.executable, str(hook), json.dumps(invalid_reply), malformed_event]),
    ).replace("__HOST_INPUT_BYTES__", str(HOST_INPUT_BYTES)))
    runner = tmp_path / "exercise.mjs"
    runner.write_text(dedent('''\
        import { pathToFileURL } from "node:url";

        const { default: extension } = await import(pathToFileURL(process.argv[2]).href);
        const handlers = new Map();
        const commands = new Map();
        const notifications = [];
        extension({
          on: (name, handler) => handlers.set(name, handler),
          registerCommand: (name, command) => commands.set(name, command),
        });
        const context = {
          cwd: process.cwd(), agent: { id: "root", kind: "main", depth: 0 },
          sessionManager: { getSessionId: () => "ipc-boundary-regression" },
          ui: { notify: (message) => notifications.push(message) },
        };
        let error = null;
        try {
          if (process.argv[3] === "before_agent_start") {
            await handlers.get("before_agent_start")({ prompt: "Review the observation." }, context);
          } else {
            await commands.get(process.argv[3]).handler("The observed finding.", context);
          }
        } catch (failure) {
          error = failure.message;
        }
        console.log(JSON.stringify({ error, notifications }));
    '''))
    result = subprocess.run(
        [node_binary, str(runner), str(extension), consumer], cwd=tmp_path,
        capture_output=True, text=True, timeout=20, check=True,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize("invalid_reply", (
    {"stdout": {"additionalContext": 42}},
    {"stdout": {"warning": True}},
    {"stdout": {"reason": [], "warning": "notice"}},
    {"stdout": []},
    {"state": "degraded", "code": 42},
), ids=("context-type", "warning-type", "reason-type", "stdout-array", "code-type"))
def test_generated_extension_rejects_invalid_consumed_reply_types(tmp_path, node_binary, invalid_reply):
    outcome = exercise_generated_reply(tmp_path, node_binary, invalid_reply)
    assert outcome["error"] == "HOST_RESPONSE_INVALID"
    assert outcome["notifications"] == []


@pytest.mark.parametrize("event,consumer,invalid_reply", (
    ("prepare_prompt", "before_agent_start", {"preparation_id": 42}),
    ("capture_finding", "memory-finding", {"capture": 42}),
    ("capture_correction", "memory-correction", {"capture": []}),
    ("capture_finding", "memory-finding", {"capture": {"state": []}}),
    ("capture_finding", "memory-finding", {"capture": {"state": "committed", "source_pointer": []}}),
    ("capture_correction", "memory-correction", {"capture": {"state": "committed", "capture_disposition": 42}}),
), ids=("preparation-type", "capture-scalar", "capture-array", "capture-state", "capture-pointer", "capture-disposition"))
def test_generated_extension_rejects_invalid_preparation_and_capture(
    tmp_path, node_binary, event, consumer, invalid_reply,
):
    outcome = exercise_generated_reply(
        tmp_path, node_binary, invalid_reply, malformed_event=event, consumer=consumer,
    )
    assert outcome["error"] == "HOST_RESPONSE_INVALID"
    assert outcome["notifications"] == []
