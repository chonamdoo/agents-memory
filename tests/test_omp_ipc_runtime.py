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
    tmp_path, node_binary, invalid_reply, *, malformed_event="before_agent_start", consumer="before_agent_start", repeats=1,
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
          on: (name, handler) => handlers.set(name, [...(handlers.get(name) || []), handler]),
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
            for (const handler of handlers.get("before_agent_start") || []) {
              await handler({ prompt: "Review the observation." }, context);
            }
          } else if (process.argv[3] === "read") {
            for (let index = 0; index < Number(process.argv[4]); index++) {
              for (const handler of handlers.get("tool_call") || []) {
                await handler({
                  toolName: "read", toolCallId: "resource-" + index,
                  input: { path: "skill://architecture" },
                }, context);
              }
            }
          } else {
            await commands.get(process.argv[3]).handler("The observed finding.", context);
          }
        } catch (failure) {
          error = failure.message;
        }
        let status;
        await commands.get("memory-status").handler("", {
          ...context, ui: { notify: (message) => { status = JSON.parse(message); } },
        });
        console.log(JSON.stringify({ error, notifications, status }));
    '''))
    result = subprocess.run(
        [node_binary, str(runner), str(extension), consumer, str(repeats)], cwd=tmp_path,
        capture_output=True, text=True, timeout=20, check=True,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize("consumer", ("before_agent_start", "read"))
@pytest.mark.parametrize("invalid_reply", (
    {"stdout": {"additionalContext": 42}},
    {"stdout": {"warning": True}},
    {"stdout": {"reason": [], "warning": "notice"}},
    {"stdout": []},
    {"state": "degraded", "code": 42},
    {"state": []},
), ids=("context-type", "warning-type", "reason-type", "stdout-array", "code-type", "state-type"))
def test_generated_extension_rejects_invalid_consumed_reply_types(tmp_path, node_binary, invalid_reply, consumer):
    outcome = exercise_generated_reply(
        tmp_path, node_binary, invalid_reply, consumer=consumer,
        malformed_event="tool_call" if consumer == "read" else "before_agent_start",
    )
    incident = outcome["status"]["incidents"]["action" if consumer == "read" else "preparation"]
    assert incident["active"] is True
    assert incident["last"]["state"] == "degraded"
    assert incident["last"]["code"] == "HOST_RESPONSE_INVALID"
    assert incident["last"]["stdout"].get("additionalContext") is None


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
    incident = outcome["status"]["incidents"]["preparation" if consumer == "before_agent_start" else "explicit_capture"]
    assert incident["active"] is True
    assert incident["last"]["state"] == "degraded"
    assert incident["last"]["code"] == "HOST_RESPONSE_INVALID"
    assert incident["last"].get("capture", {}).get("capture_disposition") != "captured"


def exercise_generated_sequence(tmp_path, node_binary, replies, steps):
    script = tmp_path / "scripted-replies.json"
    script.write_text(json.dumps(replies))
    observed = tmp_path / "scripted-envelopes.jsonl"
    hook = tmp_path / "scripted.py"
    hook.write_text(dedent('''\
        import json
        import sys
        from pathlib import Path

        import time
        envelope = json.load(sys.stdin)
        script = Path(sys.argv[1])
        replies = json.loads(script.read_text())
        reply = {"state": "ok", "stdout": {}, "provider_input_observed": False,
                 "preparation_id": "a" * 64}
        if replies.get(envelope["event"]):
            reply.update(replies[envelope["event"]].pop(0))
            script.write_text(json.dumps(replies))
        with Path(sys.argv[2]).open("a") as log:
            log.write(json.dumps(envelope) + "\\n")
        release = reply.pop("_wait_for", None)
        deadline = time.monotonic() + 10
        while release and not Path(release).exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        print(json.dumps(reply))
    '''))
    template = files("agents_memory.host_templates").joinpath("omp.ts").read_text()
    extension = tmp_path / "scripted-extension.mts"
    extension.write_text(template.replace(
        "__HOOK_ARGV__", json.dumps([sys.executable, str(hook), str(script), str(observed)]),
    ).replace("__HOST_INPUT_BYTES__", str(HOST_INPUT_BYTES)))
    scenario = tmp_path / "scripted-steps.json"
    scenario.write_text(json.dumps(steps))
    runner = tmp_path / "scripted-runner.mjs"
    runner.write_text(dedent('''\
        import { readFileSync, writeFileSync } from "node:fs";
        import { pathToFileURL } from "node:url";

        const { default: extension } = await import(pathToFileURL(process.argv[2]).href);
        const handlers = new Map();
        const commands = new Map();
        extension({
          on: (name, handler) => handlers.set(name, [...(handlers.get(name) || []), handler]),
          registerCommand: (name, command) => commands.set(name, command),
        });
        const agents = {
          root: { id: "root", kind: "main", depth: 0 },
          child: { id: "child", kind: "sub", parentId: "root", depth: 1 },
        };
        const actions = [];
        const detached = [];
        for (const step of JSON.parse(readFileSync(process.argv[3], "utf8"))) {
          if (step.release) {
            writeFileSync(step.release, "");
            continue;
          }
          if (step.until_hook) {
            const deadline = Date.now() + 10000;
            const count = () => { try { return readFileSync(process.argv[4], "utf8").split("\\n").filter(Boolean).length; } catch { return 0; } };
            while (count() < step.until_hook && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 10));
            continue;
          }
          if (step.settle) {
            for (const item of await Promise.all(detached)) actions[item.index].results = item.results;
            continue;
          }
          const notifications = [];
          const context = {
            cwd: process.cwd(), agent: agents[step.agent || "root"],
            sessionManager: { getSessionId: () => step.session || "scripted-session" },
            ui: { notify: (message, level) => notifications.push({ message, level }) },
          };
          const action = { error: null, notifications, results: [] };
          const index = actions.push(action) - 1;
          const run = (async () => {
            const results = [];
            try {
              if (step.command) results.push(await commands.get(step.command).handler(step.args || "", context));
              else for (const handler of handlers.get(step.event) || []) results.push(await handler(step.payload || {}, context));
            } catch (failure) {
              action.error = failure.message;
            }
            return { index, results };
          })();
          if (step.detach) detached.push(run);
          else action.results = (await run).results;
        }
        console.log(JSON.stringify(actions));
    '''))
    result = subprocess.run(
        [node_binary, str(runner), str(extension), str(scenario), str(observed)], cwd=tmp_path,
        capture_output=True, text=True, timeout=30, check=True,
    )
    envelopes = [json.loads(line) for line in observed.read_text().splitlines()] if observed.exists() else []
    return json.loads(result.stdout), envelopes


def refusal(code, **extra):
    return {"state": "degraded", "code": code, "stdout": {"warning": "agents-memory: " + code}, **extra}


def levels(action, level):
    return [item["message"] for item in action["notifications"] if item["level"] == level]


def status_of(action):
    assert action["error"] is None
    return json.loads(action["notifications"][-1]["message"])


def test_generated_extension_warns_once_per_distinct_code_and_again_after_recovery(tmp_path, node_binary):
    rule = "Required alpha rule body."
    read = {"event": "tool_call", "payload": {"toolName": "read", "toolCallId": "read", "input": {"path": "src/a.py"}}}
    finding = {"command": "memory-finding", "args": "The observed finding."}
    actions, _ = exercise_generated_sequence(tmp_path, node_binary, {
        "tool_call": [
            refusal("HOST_FOOTPRINT_UNKNOWN"), refusal("SERVICE_UNAVAILABLE"),
            refusal("HOST_FOOTPRINT_UNKNOWN", stdout={"warning": "agents-memory: HOST_FOOTPRINT_UNKNOWN", "additionalContext": rule}),
            refusal("SERVICE_UNAVAILABLE"), {"state": "ok"}, refusal("HOST_FOOTPRINT_UNKNOWN"),
        ],
        "capture_finding": [
            refusal("SPOOL_FULL", capture={"state": "gap", "capture_disposition": "spool_full"}),
            refusal("SPOOL_FULL", capture={"state": "gap", "capture_disposition": "spool_full"}),
        ],
    }, [*[read] * 6, finding, finding, {"command": "memory-status"}])
    expected = ["HOST_FOOTPRINT_UNKNOWN", "SERVICE_UNAVAILABLE", None, None, None, "HOST_FOOTPRINT_UNKNOWN"]
    for action, code in zip(actions[:6], expected, strict=True):
        warnings = levels(action, "warning")
        assert len(warnings) == (code is not None)
        assert all(code in message for message in warnings)
    assert rule in "\n".join(levels(actions[2], "info"))
    assert [bool(levels(action, "info")) for action in actions[:6]] == [False, False, True, False, True, False]
    assert len(levels(actions[6], "warning")) == 1
    assert levels(actions[7], "warning") == []
    for action in actions[6:8]:
        assert any(json.loads(message).get("capture_disposition") == "spool_full"
                   for message in levels(action, "info"))
    incident = status_of(actions[8])["incidents"]["action"]
    assert incident["active"] is True
    assert incident["count"] == 5
    assert incident["recoveries"] == 1
    assert incident["codes"] == {"HOST_FOOTPRINT_UNKNOWN": 3, "SERVICE_UNAVAILABLE": 2}
    assert incident["activeCodes"] == ["HOST_FOOTPRINT_UNKNOWN"]
    assert incident["lastFailure"]["code"] == "HOST_FOOTPRINT_UNKNOWN"


GAP_HEALTH = {"code_observation": {"state": "gap", "code": "HEALTH_OBSERVATION_PARTIAL"}, "session": {"state": "disabled"}}


@pytest.mark.parametrize("health", (
    [], None, {"code_observation": {"state": "observed"}},
    {"code_observation": {"state": "observed"}, "session": {"state": "disabled"}, "extra": {"state": "ok"}},
    {"code_observation": {"state": 1}, "session": {"state": "disabled"}},
    {"code_observation": [], "session": {"state": "disabled"}},
    {"code_observation": {"state": "gap", "code": 7}, "session": {"state": "disabled"}},
    {"code_observation": {"state": "gap"}, "session": {"state": "disabled"}},
    {"code_observation": {"state": "observed", "code": None}, "session": {"state": "disabled"}},
), ids=("array", "null", "missing-session", "extra-key", "state-type", "observation-array",
        "code-type", "gap-without-code", "null-code"))
def test_generated_extension_rejects_malformed_health_without_false_recovery(tmp_path, node_binary, health):
    actions, _ = exercise_generated_sequence(tmp_path, node_binary, {
        "session_start": [{"health": GAP_HEALTH}, {"state": "ok", "health": health}],
    }, [{"event": "session_start"}, {"event": "session_start"}, {"command": "memory-status"}])
    assert any("HEALTH_OBSERVATION_PARTIAL" in message for message in levels(actions[0], "warning"))
    assert levels(actions[1], "info") == []
    assert any("HOST_RESPONSE_INVALID" in message for message in levels(actions[1], "warning"))
    incident = status_of(actions[2])["incidents"]["session_start"]
    assert incident["active"] is True
    assert incident["recoveries"] == 0
    assert incident["last"]["code"] == "HOST_RESPONSE_INVALID"
    assert incident["codes"] == {"HEALTH_OBSERVATION_PARTIAL": 1, "HOST_RESPONSE_INVALID": 1}


def test_generated_extension_accepts_backend_health_and_recovers(tmp_path, node_binary):
    observed = {
        "code_observation": {"state": "observed", "configured": True, "workspace_id": "workspace",
                             "coverage": "linked_paths", "files": 0},
        "session": {"state": "durably_spooled", "coverage": "partial", "sequence": 1},
    }
    actions, _ = exercise_generated_sequence(tmp_path, node_binary, {
        "session_start": [{"health": GAP_HEALTH}, {"health": observed}],
    }, [{"event": "session_start"}, {"event": "session_start"}, {"command": "memory-status"}])
    assert levels(actions[1], "warning") == []
    assert len(levels(actions[1], "info")) == 1
    incident = status_of(actions[2])["incidents"]["session_start"]
    assert incident["active"] is False
    assert incident["recoveries"] == 1
    assert incident["activeCodes"] == []


def test_session_restart_resumes_every_agent_and_switch_retires_prior_sessions(tmp_path, node_binary):
    read = {"event": "tool_call", "payload": {"toolName": "read", "toolCallId": "read", "input": {"path": "src/a.py"}}}
    actions, envelopes = exercise_generated_sequence(tmp_path, node_binary, {
        "tool_call": [refusal("SERVICE_UNAVAILABLE")],
    }, [
        {"event": "session_start", "session": "first"},
        {**read, "session": "first"}, {**read, "session": "first", "agent": "child"},
        {"event": "session_shutdown", "session": "first"},
        {"event": "session_start", "session": "first"},
        {**read, "session": "first", "agent": "child"},
        {"command": "memory-status", "session": "first"},
        {"event": "session_switch", "session": "second"},
        {"command": "memory-status", "session": "first"},
        {"command": "memory-status", "session": "second"},
    ])
    child_actions = [envelope for envelope in envelopes
                     if envelope["event"] == "tool_call" and envelope["agent"]["id"] == "child"]
    assert len(child_actions) == 2
    assert all("HOST_LIFECYCLE_STALE" not in item["message"] for item in actions[5]["notifications"])
    retained = status_of(actions[6])["incidents"]
    assert retained["action"]["codes"] == {"SERVICE_UNAVAILABLE": 1}
    assert status_of(actions[8])["incidents"] == {}
    assert set(status_of(actions[9])["incidents"]) == {"session_switch"}



def test_in_flight_action_reset_by_session_restart_never_reaches_the_model(tmp_path, node_binary):
    release = tmp_path / "release-child-read"
    stale = "OLD_SUBMISSION_CONTEXT"
    read = {"event": "tool_call", "payload": {"toolName": "read", "toolCallId": "read", "input": {"path": "src/a.py"}}}
    actions, envelopes = exercise_generated_sequence(tmp_path, node_binary, {
        "tool_call": [{"code": "HOST_PROVIDER_INPUT_UNOBSERVABLE", "state": "degraded",
                       "stdout": {"additionalContext": stale}, "_wait_for": str(release)},
                      {"code": "HOST_PROVIDER_INPUT_UNOBSERVABLE", "state": "degraded",
                       "stdout": {"additionalContext": "CURRENT_CONTEXT"}}],
    }, [
        {"event": "before_agent_start", "agent": "child", "payload": {"prompt": "Child task."}},
        {**read, "agent": "child", "detach": True},
        {"until_hook": 3},
        {"event": "session_start"},
        {"release": str(release)},
        {"settle": True},
        {**read, "agent": "child"},
    ])
    stale_read, fresh_read = actions[1], actions[3]
    assert stale_read["results"] == [None]
    assert all(stale not in item["message"] for item in stale_read["notifications"])
    assert fresh_read["results"] == [{"additionalContext": "CURRENT_CONTEXT"}]
    child_reads = [item for item in envelopes if item["event"] == "tool_call"]
    assert child_reads[0]["adapter_epoch"] != child_reads[1]["adapter_epoch"]
