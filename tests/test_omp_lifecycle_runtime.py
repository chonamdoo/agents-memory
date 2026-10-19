from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from importlib.resources import files
from textwrap import dedent

import pytest
from test_host_boundaries import (
    installation as installation,
)
from test_omp_ipc_runtime import (
    node_binary as node_binary,
)

from agents_memory import hosts
from agents_memory.domain import ActiveRule, RuleScope, Selector

RULE_BODY = "Preserve the active submission's alpha invariant."


def prepare(prompt="Review the active task.", **context):
    return {"event": "before_agent_start", "payload": {"prompt": prompt}, **context}


def read_file(identity, **context):
    return {
        "event": "tool_call", "payload": {
            "toolName": "read", "toolCallId": identity, "input": {"path": "src/alpha.py"},
        }, **context,
    }


def run_lifecycle(tmp_path, node_binary, receipt, project, steps, *, hook_mode="normal"):
    rule = ActiveRule(
        id="active-alpha-rule", revision=1, digest=hashlib.sha256(RULE_BODY.encode()).hexdigest(),
        body=RULE_BODY, selector=Selector(paths=("src/alpha.py",)), exceptions=(), required=True,
        scope=RuleScope.LOCAL_PROJECT, target_bindings=("project-binding",), source_ids=(),
    )
    scenario_path = tmp_path / "lifecycle-scenario.json"
    scenario_path.write_text(json.dumps({"steps": steps, "rule": rule.model_dump(mode="json"), "hook_mode": hook_mode}))
    observed = tmp_path / "lifecycle-hooks.jsonl"
    pid_path = tmp_path / "owned-hook.pid"
    hook = tmp_path / "lifecycle-hook.py"
    hook.write_text(dedent('''\
        import hashlib
        import json
        import os
        import signal
        import sys
        from datetime import datetime, timezone
        from pathlib import Path

        from agents_memory import hosts
        from agents_memory.context import compose
        from agents_memory.domain import ActiveRule, ContextCommand, DomainError

        scenario = json.loads(Path(sys.argv[3]).read_text())
        envelope = json.load(sys.stdin)
        control = json.loads(Path(sys.argv[4]).read_text())
        if scenario["hook_mode"] == "stalled":
            Path(sys.argv[5]).write_text(str(os.getpid()))
            signal.pause()
        requests = []
        rule = ActiveRule.model_validate(scenario["rule"])

        class Authority:
            def __init__(self, *args, **kwargs):
                pass

            def request(self, route, payload):
                requests.append({"route": route, "payload": payload})
                if route == "/api/capture":
                    if control.get("capture_error"):
                        raise DomainError(control["capture_error"], "Capture delivery refused")
                    identity = hashlib.sha256(payload["idempotency_key"].encode()).hexdigest()
                    pointer = {
                        "source_id": "source-" + identity, "source_revision": 1,
                        "binding_id": payload["binding_id"], "binding_revision": 1,
                        "source_speaker": "human", "source_event_time": None,
                        "source_recorded_at": datetime.now(timezone.utc).isoformat(),
                        "byte_length": len(payload["body"].encode()), "coverage": payload["coverage"],
                    }
                    return {
                        "effect": "committed", "id": "capture-" + identity,
                        "binding_id": payload["binding_id"], "kind": "capture", "state": "captured",
                        "source_id": pointer["source_id"], "epoch": 1,
                        "source_pointer": pointer, "capture_disposition": "captured",
                    }
                if route not in {"/api/context", "/api/required-context"}:
                    raise AssertionError("unexpected authority endpoint: " + route)
                if control.get("context_error"):
                    raise DomainError(control["context_error"], "Context delivery refused")
                active_rules = () if control.get("no_required_rules") else (rule,)
                composed = compose(ContextCommand.model_validate(payload), active_rules, (), (),
                                   protected_action=route == "/api/required-context")
                reply = {
                    "context": composed.text, "context_bytes": composed.byte_count,
                    "stamp": {"epoch": 1, "rules": [list(item) for item in composed.rule_versions]},
                }
                if route == "/api/required-context":
                    reply["required"] = bool(composed.rule_versions)
                else:
                    candidates = control.get("candidates", [])
                    reply.update(
                        admission_id="admission-" + hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16],
                        judgment_required=bool(candidates),
                        candidate_manifest=[
                            {"claim_id": claim, "inspection_ref": claim, "preview": "Unjudged preview " + claim, "partial": False}
                            for claim in candidates
                        ],
                    )
                    if candidates:
                        reply["status"] = "judgment_required"
                return reply

        hosts.LocalClient = Authority
        result = hosts.handle_hook_input(Path(sys.argv[1]), json.dumps(envelope).encode())
        with Path(sys.argv[2]).open("a") as log:
            log.write(json.dumps({"envelope": envelope, "result": result, "requests": requests}) + "\\n")
        print(json.dumps(result))
    '''))
    control_path = tmp_path / "lifecycle-control.json"
    control_path.write_text("{}")
    argv = [sys.executable, "-I", str(hook), str(receipt), str(observed), str(scenario_path), str(control_path), str(pid_path)]
    if hook_mode == "spawn_failure":
        argv = [str(tmp_path / "missing-hook-executable")]
    template = files("agents_memory.host_templates").joinpath("omp.ts").read_text()
    extension = tmp_path / "lifecycle-extension.mts"
    extension.write_text(template.replace("__HOOK_ARGV__", json.dumps(argv)).replace(
        "__HOST_INPUT_BYTES__", str(hosts.HOST_INPUT_BYTES),
    ))
    runner = tmp_path / "lifecycle-runner.mjs"
    runner.write_text(dedent('''\
        import { existsSync, readFileSync, watch, writeFileSync } from "node:fs";
        import { dirname } from "node:path";
        import { pathToFileURL } from "node:url";

        const scenario = JSON.parse(readFileSync(process.argv[3], "utf8"));
        const pidPath = process.argv[5];
        if (scenario.hook_mode === "stalled") {
          const nativeSetTimeout = globalThis.setTimeout;
          globalThis.setTimeout = (callback, milliseconds, ...args) => {
            if (milliseconds < 100) return nativeSetTimeout(callback, milliseconds, ...args);
            let watcher;
            let done = false;
            const fire = () => {
              if (!done && existsSync(pidPath)) {
                done = true;
                watcher?.close();
                setImmediate(callback, ...args);
              }
            };
            watcher = watch(dirname(pidPath), fire);
            fire();
            return { unref() { return this; }, ref() { return this; } };
          };
        }
        const { default: extension } = await import(pathToFileURL(process.argv[2]).href);
        const handlers = new Map();
        const commands = new Map();
        const notifications = [];
        extension({
          on: (name, handler) => handlers.set(name, [...(handlers.get(name) || []), handler]),
          registerCommand: (name, command) => commands.set(name, command),
        });
        const baseContext = {
          cwd: process.cwd(), agent: { id: "root", kind: "main", depth: 0 },
          model: { api: "anthropic-messages" },
          sessionManager: { getSessionId: () => "native-lifecycle-contract" },
          ui: { notify: (message, level) => notifications.push({ message, level }) },
        };
        const actions = [];
        for (const step of scenario.steps) {
          writeFileSync(process.argv[4], JSON.stringify(step.control || {}));
          const context = {
            ...baseContext, ...(step.context || {}),
            sessionManager: { getSessionId: () => step.session || "native-lifecycle-contract" },
          };
          const start = notifications.length;
          const results = [];
          let error = null;
          try {
            if (step.command) {
              if (!commands.has(step.command)) throw new Error("missing command: " + step.command);
              results.push(await commands.get(step.command).handler(step.args || "", context));
            } else {
              for (const handler of handlers.get(step.event) || []) results.push(await handler(step.payload || {}, context));
            }
          } catch (failure) {
            error = failure.message;
          }
          let ownedProcessAlive = false;
          if (existsSync(pidPath)) {
            try { process.kill(Number(readFileSync(pidPath, "utf8")), 0); ownedProcessAlive = true; }
            catch (failure) { if (failure.code !== "ESRCH") throw failure; }
          }
          actions.push({ results, error, notifications: notifications.slice(start), ownedProcessAlive });
        }
        console.log(JSON.stringify({ actions, notifications, commands: [...commands.keys()] }));
    '''))
    completed = subprocess.run(
        [node_binary, str(runner), str(extension), str(scenario_path), str(control_path), str(pid_path)],
        cwd=project, capture_output=True, text=True, check=True, timeout=30,
    )
    outcome = json.loads(completed.stdout)
    outcome["hooks"] = [json.loads(line) for line in observed.read_text().splitlines()] if observed.exists() else []
    return outcome


def hooks_for(outcome, event):
    return [entry for entry in outcome["hooks"] if entry["envelope"]["event"] == event]


def visible(action):
    return "\n".join(item["message"] for item in action["notifications"])


def diagnostic(action):
    assert action["error"] is None
    return json.loads(action["notifications"][-1]["message"])


def assert_required_context(entry):
    assert entry["result"]["code"] != "HOST_GENERATION_UNOBSERVED"
    assert entry["result"]["state"] != "ok"
    assert entry["result"]["provider_input_observed"] is False
    requests = [request for request in entry["requests"] if request["route"] == "/api/required-context"]
    assert [request["payload"]["paths"] for request in requests] == [["src/alpha.py"]]
    assert RULE_BODY in json.dumps(entry["result"]["stdout"])


@pytest.mark.parametrize("compaction", [
    ["session_before_compact", "session_compact"], ["session_before_compact"],
], ids=["committed-pre-prompt-compaction", "cancelled-compaction"])
def test_same_submission_compaction_keeps_local_required_context(
    tmp_path, node_binary, installation, compaction,
):
    project, _, _, _, install = installation
    steps = [
        prepare(), *({"event": name} for name in compaction),
        read_file("after-compaction"), read_file("later-same-submission"),
    ]
    outcome = run_lifecycle(tmp_path, node_binary, install("omp", prompt_recall=True), project, steps)
    prompt = hooks_for(outcome, "before_agent_start")[0]
    actions = hooks_for(outcome, "tool_call")
    assert len(actions) == 2
    for entry in actions:
        assert entry["envelope"]["adapter_turn_id"] == prompt["envelope"]["adapter_turn_id"]
        assert_required_context(entry)
    for action in outcome["actions"][-2:]:
        assert RULE_BODY in visible(action)
        # Only the handler return reaches the model; UI notifications are user-only.
        assert [RULE_BODY in result["additionalContext"] for result in action["results"]] == [True]
    assert sum(item["level"] == "warning" for action in outcome["actions"][-2:]
               for item in action["notifications"]) == 1
    assert all(entry["result"]["provider_input_observed"] is False for entry in outcome["hooks"])


@pytest.mark.parametrize("transition", ["session_switch", "session_branch"])
def test_replacement_boundaries_still_require_new_native_preparation(
    tmp_path, node_binary, installation, transition,
):
    project, _, _, _, install = installation
    outcome = run_lifecycle(tmp_path, node_binary, install("omp"), project, [
        prepare(), {"event": transition}, read_file("unprepared-replacement"),
        prepare("The replacement task."), read_file("prepared-replacement"),
    ])
    denied, refreshed = hooks_for(outcome, "tool_call")
    assert denied["result"]["state"] != "ok"
    assert denied["result"]["code"] == "HOST_GENERATION_UNOBSERVED"
    assert denied["result"]["coverage"] == "limited_no_agent_preparation"
    assert [request["route"] for request in denied["requests"]] == ["/api/required-context", "/api/context"]
    assert RULE_BODY in json.dumps(denied["result"]["stdout"])
    assert_required_context(refreshed)
    prompts = hooks_for(outcome, "before_agent_start")
    assert prompts[0]["envelope"]["adapter_turn_id"] != prompts[1]["envelope"]["adapter_turn_id"]


@pytest.mark.parametrize("command,event", [
    ("memory-finding", "capture_finding"), ("memory-correction", "capture_correction"),
])
def test_explicit_capture_during_streaming_keeps_submission_and_unique_capture_operations(
    tmp_path, node_binary, installation, command, event,
):
    project, _, _, _, install = installation
    outcome = run_lifecycle(tmp_path, node_binary, install("omp"), project, [
        prepare(), {"command": command, "args": "The same independently submitted observation."},
        read_file("streaming-one"),
        {"command": command, "args": "The same independently submitted observation."},
        read_file("streaming-two"),
    ])
    active = hooks_for(outcome, "before_agent_start")[0]
    captures = hooks_for(outcome, event)
    actions = hooks_for(outcome, "tool_call")
    assert len(captures) == len(actions) == 2
    assert len({entry["result"]["capture"]["capture_key"] for entry in captures}) == 2
    assert len({entry["result"]["capture"]["source_pointer"]["source_id"] for entry in captures}) == 2
    for entry in [*captures, *actions]:
        assert entry["envelope"]["adapter_turn_id"] == active["envelope"]["adapter_turn_id"]
        assert entry["result"]["generation"] == active["result"]["generation"]
    for entry in actions:
        assert_required_context(entry)
    for index, capture in zip((1, 3), captures, strict=True):
        reported = diagnostic(outcome["actions"][index])
        assert reported["capture_disposition"] == "captured"
        assert reported["source_pointer"] == capture["result"]["capture"]["source_pointer"]


def test_rejected_secret_input_never_creates_a_correlation_key(tmp_path, node_binary, installation):
    project, _, _, _, install = installation
    secret = "ghp_" + "a" * 36
    outcome = run_lifecycle(tmp_path, node_binary, install("omp"), project, [
        prepare("The active task."),
        {"event": "input", "payload": {"text": secret, "source": "interactive"}},
        {"command": "memory-status"},
    ])
    [ingress] = hooks_for(outcome, "input")
    assert ingress["result"]["capture"]["code"] == "SOURCE_SECRET_REJECTED"
    assert diagnostic(outcome["actions"][-1])["pending_ingress_correlations"] == 0
    assert secret not in json.dumps(outcome["actions"])


def test_rejected_secret_preparation_keeps_live_submission_and_generation(tmp_path, node_binary, installation):
    project, _, _, _, install = installation
    secret = "ghp_" + "a" * 36
    outcome = run_lifecycle(tmp_path, node_binary, install("omp"), project, [
        prepare("The active task."), read_file("before-secret"),
        prepare(secret), read_file("after-secret"),
        {"command": "memory-status"},
    ])
    admitted, rejected = hooks_for(outcome, "prepare_prompt")
    assert "preparation_id" in admitted["result"]
    assert rejected["result"]["code"] == "SOURCE_SECRET_REJECTED"
    assert "preparation_id" not in rejected["result"]
    [active] = hooks_for(outcome, "before_agent_start")
    actions = hooks_for(outcome, "tool_call")
    turn = active["envelope"]["adapter_turn_id"]
    assert rejected["envelope"]["adapter_turn_id"] == turn
    assert [entry["envelope"]["adapter_turn_id"] for entry in actions] == [turn, turn]
    for entry in actions:
        assert entry["result"]["generation"] == active["result"]["generation"]
        assert_required_context(entry)
    status = diagnostic(outcome["actions"][-1])
    assert status["submission_observed"] is True
    assert status["coverage"] == "advisory_submission_observed"
    assert status["incidents"]["preparation"]["codes"] == {"SOURCE_SECRET_REJECTED": 1}
    assert secret not in json.dumps(outcome["actions"])


def test_same_session_restart_resets_every_retained_agent_lifecycle(tmp_path, node_binary, installation):
    project, _, _, _, install = installation
    child = {"context": {"agent": {"id": "child-agent", "kind": "sub", "parentId": "root", "depth": 1}}}
    outcome = run_lifecycle(tmp_path, node_binary, install("omp"), project, [
        prepare(), prepare("The delegated task.", **child), read_file("child-before-restart", **child),
        {"event": "session_shutdown"}, {"event": "session_start"},
        read_file("child-after-restart", **child),
        {"command": "memory-status", **child},
    ])
    child_prompt = hooks_for(outcome, "before_agent_start")[1]
    before, after = hooks_for(outcome, "tool_call")
    assert before["envelope"]["adapter_turn_id"] == child_prompt["envelope"]["adapter_turn_id"]
    assert_required_context(before)
    assert after["envelope"]["adapter_epoch"] != before["envelope"]["adapter_epoch"]
    assert after["envelope"]["adapter_epoch_started"] > before["envelope"]["adapter_epoch_started"]
    assert after["envelope"]["adapter_sequence"] == 1
    assert after["envelope"].get("adapter_turn_id") is None
    assert after["result"]["state"] != "ok"
    assert after["result"]["code"] == "HOST_GENERATION_UNOBSERVED"
    assert after["result"]["coverage"] == "limited_no_agent_preparation"
    assert RULE_BODY in json.dumps(after["result"]["stdout"])
    status = diagnostic(outcome["actions"][-1])
    assert status["submission_observed"] is False
    assert status["incidents"]["action"]["codes"]["HOST_GENERATION_UNOBSERVED"] == 1
    assert status["incidents"]["action"]["last"]["code"] == "HOST_GENERATION_UNOBSERVED"


def test_queued_followup_capture_is_not_promoted_until_matching_preparation(
    tmp_path, node_binary, installation,
):
    project, _, _, _, install = installation
    outcome = run_lifecycle(tmp_path, node_binary, install("omp"), project, [
        prepare("The active task."),
        {"event": "input", "payload": {"text": "The queued followup.", "source": "interactive"}},
        read_file("old-task-still-running"), prepare("The active task."),
        read_file("old-task-reentry"), prepare("The queued followup."), read_file("new-task-running"),
    ])
    prompts = hooks_for(outcome, "before_agent_start")
    ingress = hooks_for(outcome, "input")[0]
    actions = hooks_for(outcome, "tool_call")
    assert len(prompts) == len(actions) == 3
    old_turn = prompts[0]["envelope"]["adapter_turn_id"]
    assert actions[0]["envelope"]["adapter_turn_id"] == actions[1]["envelope"]["adapter_turn_id"] == old_turn
    assert prompts[1]["envelope"]["adapter_turn_id"] == old_turn
    assert ingress["result"]["generation"] == prompts[0]["result"]["generation"]
    assert prompts[2]["envelope"]["adapter_turn_id"] != old_turn
    assert actions[2]["envelope"]["adapter_turn_id"] == prompts[2]["envelope"]["adapter_turn_id"]
    pointer = ingress["result"]["capture"]["source_pointer"]
    assert pointer["source_id"] not in json.dumps(prompts[1]["result"])
    assert prompts[2]["result"]["capture"]["source_pointer"] == pointer
    for entry in actions:
        assert_required_context(entry)


def test_queued_input_matching_active_submission_keeps_turn_without_correlation(
    tmp_path, node_binary, installation,
):
    project, _, _, _, install = installation
    outcome = run_lifecycle(tmp_path, node_binary, install("omp"), project, [
        prepare("The active task."),
        {"event": "input", "payload": {"text": "The active task.", "source": "interactive"}},
        read_file("before-reentry"), prepare("The active task."), read_file("after-reentry"),
        {"command": "memory-status"},
    ])
    prompts = hooks_for(outcome, "before_agent_start")
    ingress = hooks_for(outcome, "input")[0]
    actions = hooks_for(outcome, "tool_call")
    turn = prompts[0]["envelope"]["adapter_turn_id"]
    assert [entry["envelope"]["adapter_turn_id"] for entry in [*prompts, *actions]] == [turn] * 4
    assert prompts[1]["result"]["generation"] == prompts[0]["result"]["generation"]
    assert all("ingress_operation_id" not in entry["envelope"] for entry in prompts)
    pointer = ingress["result"]["capture"]["source_pointer"]
    assert all(pointer["source_id"] not in json.dumps(entry["result"]) for entry in prompts)
    assert diagnostic(outcome["actions"][-1])["pending_ingress_correlations"] == 0
    for entry in actions:
        assert_required_context(entry)


def test_repeated_identical_queued_inputs_never_rotate_reentered_submission(
    tmp_path, node_binary, installation,
):
    project, _, _, _, install = installation
    queued = {"event": "input", "payload": {"text": "The active task.", "source": "interactive"}}
    outcome = run_lifecycle(tmp_path, node_binary, install("omp"), project, [
        prepare("The active task."), queued, queued,
        prepare("The active task."), prepare("The active task."), prepare("The active task."),
        read_file("after-reentries"), {"command": "memory-status"},
    ])
    prompts = hooks_for(outcome, "before_agent_start")
    ingress = hooks_for(outcome, "input")
    action = hooks_for(outcome, "tool_call")[0]
    assert len(prompts) == 4
    assert len(ingress) == 2
    turn = prompts[0]["envelope"]["adapter_turn_id"]
    assert [entry["envelope"]["adapter_turn_id"] for entry in [*prompts, action]] == [turn] * 5
    assert len({entry["result"]["generation"] for entry in prompts}) == 1
    assert all("ingress_operation_id" not in entry["envelope"] for entry in prompts)
    pointers = [entry["result"]["capture"]["source_pointer"]["source_id"] for entry in ingress]
    assert all(pointer not in json.dumps(entry["result"]) for entry in prompts for pointer in pointers)
    assert diagnostic(outcome["actions"][-1])["pending_ingress_correlations"] == 0
    assert_required_context(action)


@pytest.mark.parametrize("ended", [{}, {"willContinue": False}], ids=["continuation-field-absent", "settled"])
def test_terminal_agent_end_promotes_identical_followup_with_its_capture_and_recall(
    tmp_path, node_binary, installation, ended,
):
    project, _, _, _, install = installation
    recall_only = {"no_required_rules": True, "candidates": ["claim_" + "a" * 32]}
    outcome = run_lifecycle(tmp_path, node_binary, install("omp"), project, [
        prepare("Continue."), read_file("first-submission", control=recall_only),
        {"event": "agent_end", "payload": {"messages": [], **ended}},
        {"event": "input", "payload": {"text": "Continue.", "source": "interactive"}},
        prepare("Continue."), read_file("second-submission", control=recall_only),
        {"command": "memory-status"},
    ])
    first, second = hooks_for(outcome, "before_agent_start")
    [ingress] = hooks_for(outcome, "input")
    actions = hooks_for(outcome, "tool_call")
    # Completion is adapter-local: the owned hook is never spawned for agent_end.
    assert hooks_for(outcome, "agent_end") == []
    assert outcome["actions"][2] == {"results": [None], "error": None, "notifications": [], "ownedProcessAlive": False}
    assert first["envelope"]["adapter_turn_id"] != second["envelope"]["adapter_turn_id"]
    assert [entry["envelope"]["adapter_turn_id"] for entry in actions] == [
        first["envelope"]["adapter_turn_id"], second["envelope"]["adapter_turn_id"],
    ]
    assert second["result"]["generation"] == first["result"]["generation"] + 1
    assert second["envelope"]["ingress_operation_id"] == ingress["envelope"]["hook_instance_id"]
    assert second["result"]["capture"]["source_pointer"] == ingress["result"]["capture"]["source_pointer"]
    # The new submission is a new recall generation, so its first footprint is offered again.
    for entry, action in zip(actions, outcome["actions"][1:6:4], strict=True):
        assert entry["result"]["recall"]["state"] != "deduplicated"
        assert "candidate_ids" in action["results"][0]["additionalContext"]
    status = diagnostic(outcome["actions"][-1])
    assert "agent_end" not in status["incidents"]
    assert status["pending_ingress_correlations"] == 0


@pytest.mark.parametrize("ended", [
    {"willContinue": True}, {"isTerminal": False, "awaitingAsyncWork": True},
], ids=["extension-will-continue", "rpc-not-terminal"])
def test_non_terminal_agent_end_keeps_resumed_submission(tmp_path, node_binary, installation, ended):
    project, _, _, _, install = installation
    recall_only = {"no_required_rules": True, "candidates": ["claim_" + "a" * 32]}
    outcome = run_lifecycle(tmp_path, node_binary, install("omp"), project, [
        prepare("Continue."), read_file("before-resume", control=recall_only),
        {"event": "agent_end", "payload": {"messages": [], **ended}},
        prepare("Continue."), read_file("after-resume", control=recall_only),
        {"command": "memory-status"},
    ])
    prompts = hooks_for(outcome, "before_agent_start")
    actions = hooks_for(outcome, "tool_call")
    turn = prompts[0]["envelope"]["adapter_turn_id"]
    assert [entry["envelope"]["adapter_turn_id"] for entry in [*prompts, *actions]] == [turn] * 4
    assert prompts[1]["result"]["generation"] == prompts[0]["result"]["generation"]
    assert actions[1]["result"]["recall"]["state"] == "deduplicated"
    assert "agent_end" not in diagnostic(outcome["actions"][-1])["incidents"]


def test_reentry_before_terminal_agent_end_keeps_turn_until_completion(tmp_path, node_binary, installation):
    project, _, _, _, install = installation
    outcome = run_lifecycle(tmp_path, node_binary, install("omp"), project, [
        prepare("Continue."), read_file("live"), prepare("Continue."), read_file("reentered"),
        {"event": "agent_end", "payload": {"messages": [], "willContinue": False}},
        prepare("Continue."), read_file("next-submission"),
    ])
    prompts = hooks_for(outcome, "before_agent_start")
    actions = hooks_for(outcome, "tool_call")
    live, after = prompts[0]["envelope"]["adapter_turn_id"], prompts[2]["envelope"]["adapter_turn_id"]
    assert live != after
    assert [entry["envelope"]["adapter_turn_id"] for entry in [*prompts, *actions]] == [
        live, live, after, live, live, after,
    ]
    assert [entry["result"]["generation"] for entry in prompts] == [prompts[0]["result"]["generation"]] * 2 + [
        prompts[0]["result"]["generation"] + 1,
    ]
    for entry in actions:
        assert_required_context(entry)


@pytest.mark.parametrize("identity", ["child-agent", "advisor"])
def test_unprepared_native_subagent_never_borrows_parent_and_diagnostics_retain_incident(
    tmp_path, node_binary, installation, identity,
):
    project, _, _, _, install = installation
    child = {"context": {"agent": {"id": identity, "kind": "sub", "parentId": "root", "depth": 0}}}
    outcome = run_lifecycle(tmp_path, node_binary, install("omp"), project, [
        prepare(), read_file("subagent-first", **child), read_file("subagent-second", **child),
        {"command": "memory-status", **child}, read_file("parent-still-active"),
    ])
    first, second, parent = hooks_for(outcome, "tool_call")
    for entry, routes in ((first, ["/api/required-context", "/api/context"]), (second, ["/api/required-context"])):
        assert entry["result"]["state"] != "ok"
        assert entry["result"]["code"] == "HOST_GENERATION_UNOBSERVED"
        assert entry["result"]["coverage"] == "limited_no_agent_preparation"
        # The repeated footprint in the same unprepared generation is not recalled again.
        assert [request["route"] for request in entry["requests"]] == routes
        assert RULE_BODY in json.dumps(entry["result"]["stdout"])
        assert entry["result"]["provider_input_observed"] is False
    assert_required_context(parent)
    warnings = [item for action in outcome["actions"][1:3] for item in action["notifications"] if item["level"] == "warning"]
    assert len(warnings) == 1
    status = diagnostic(outcome["actions"][3])
    assert status["agent"]["id"] == identity
    assert status["submission_observed"] is False
    assert status["provider_input_observed"] is False
    incident = status["incidents"]["action"]
    assert incident["active"] is True
    assert incident["count"] == 2
    assert incident["codes"]["HOST_GENERATION_UNOBSERVED"] == 2
    assert incident["last"]["code"] == "HOST_GENERATION_UNOBSERVED"


def test_independent_genuine_failures_remain_in_status_and_recovery_is_visible(
    tmp_path, node_binary, installation,
):
    project, _, _, _, install = installation
    missing_cwd = str(tmp_path / "removed-native-working-directory")
    looping_cwd = tmp_path / "native-cwd-loop"
    looping_cwd.symlink_to(looping_cwd.name)
    outcome = run_lifecycle(tmp_path, node_binary, install("omp"), project, [
        prepare(),
        read_file("scope-first", context={"cwd": missing_cwd}),
        read_file("scope-again", context={"cwd": missing_cwd}),
        read_file("adapter-first", context={"cwd": str(looping_cwd)}),
        read_file("adapter-again", context={"cwd": str(looping_cwd)}),
        read_file("service-first", control={"context_error": "SERVICE_UNAVAILABLE"}),
        read_file("service-again", control={"context_error": "SERVICE_UNAVAILABLE"}),
        {"command": "memory-status"},
        read_file("recovered-context", control={"no_required_rules": True}), {"command": "memory-status"},
    ])
    actions = hooks_for(outcome, "tool_call")
    failures = actions[:-1]
    assert [entry["result"]["code"] for entry in failures] == [
        "HOST_SCOPE_UNRESOLVED", "HOST_SCOPE_UNRESOLVED",
        "HOST_ADAPTER_UNAVAILABLE", "HOST_ADAPTER_UNAVAILABLE",
        "SERVICE_UNAVAILABLE", "SERVICE_UNAVAILABLE",
    ]
    assert all(entry["result"]["state"] != "ok" for entry in failures)
    codes = ["HOST_SCOPE_UNRESOLVED", "HOST_ADAPTER_UNAVAILABLE", "SERVICE_UNAVAILABLE"]
    for index, action in enumerate(outcome["actions"][1:7]):
        warnings = [item["message"] for item in action["notifications"] if item["level"] == "warning"]
        if index % 2:
            assert warnings == []
        else:
            assert len(warnings) == 1
            assert codes[index // 2] in warnings[0]
    before = diagnostic(outcome["actions"][7])["incidents"]["action"]
    assert before["active"] is True
    assert before["count"] == 6
    assert before["codes"] == {
        "HOST_SCOPE_UNRESOLVED": 2, "HOST_ADAPTER_UNAVAILABLE": 2, "SERVICE_UNAVAILABLE": 2,
    }
    assert actions[-1]["result"]["state"] == "ok"
    assert actions[-1]["result"]["provider_input_observed"] is False
    assert any(request["route"] == "/api/required-context" for request in actions[-1]["requests"])
    after = diagnostic(outcome["actions"][-1])["incidents"]["action"]
    assert after["active"] is False
    assert after["count"] == before["count"]
    assert after["codes"] == before["codes"]
    assert after["recoveries"] == before["recoveries"] + 1
    assert after["last"]["state"] == "ok"
    assert after["lastFailure"]["code"] == "SERVICE_UNAVAILABLE"
    assert any(item["level"] == "info" for item in outcome["actions"][8]["notifications"])


@pytest.mark.parametrize("hook_mode,expected_code", [
    ("spawn_failure", "HOST_ADAPTER_UNAVAILABLE"), ("stalled", "HOST_EVENT_DEADLINE"),
])
def test_owned_hook_failure_never_succeeds_or_outlives_completed_callback(
    tmp_path, node_binary, installation, hook_mode, expected_code,
):
    project, _, _, _, install = installation
    outcome = run_lifecycle(tmp_path, node_binary, install("omp"), project, [
        prepare(), {"command": "memory-status"},
    ], hook_mode=hook_mode)
    preparation = outcome["actions"][0]
    assert preparation["results"] in ([], [None])
    assert preparation["ownedProcessAlive"] is False
    assert expected_code in (visible(preparation) + (preparation["error"] or ""))
    incident = diagnostic(outcome["actions"][1])["incidents"]["preparation"]
    assert incident["active"] is True
    assert incident["last"]["state"] != "ok"
    assert incident["last"]["code"] == expected_code


def test_generated_extension_returns_action_recall_handoff_to_the_model_only(tmp_path, node_binary, installation):
    project, _, _, _, install = installation
    claims = ["claim_" + "a" * 32, "claim_" + "b" * 32]
    recall_only = {"no_required_rules": True, "candidates": claims}
    outcome = run_lifecycle(tmp_path, node_binary, install("omp"), project, [
        prepare(), read_file("first", control=recall_only), read_file("repeat", control=recall_only),
        read_file("required", control={"candidates": claims}), {"command": "memory-status"},
    ])
    first, repeat, required = outcome["actions"][1:4]
    [returned] = first["results"]
    marker, handoff_line = returned["additionalContext"].split("\n")
    handoff = json.loads(handoff_line)
    assert marker == "[agents-memory:bounded-context]"
    assert handoff["candidate_ids"] == claims and handoff["trigger"] == "pre_action_paths"
    assert handoff["request"]["paths"] == ["src/alpha.py"] and handoff["request"]["host"] == "omp"
    # The handoff is model work: no user notification and no incident for an advisory recall.
    assert first["notifications"] == [] and first["error"] is None
    assert repeat["results"] == [None] and repeat["notifications"] == []
    hooks = hooks_for(outcome, "tool_call")
    assert [request["route"] for request in hooks[1]["requests"]] == ["/api/required-context"]
    assert hooks[1]["result"]["recall"]["state"] == "deduplicated"
    # Required context of the same submission still arrives; the deduplicated recall adds nothing.
    assert RULE_BODY in required["results"][0]["additionalContext"]
    assert "candidate_ids" not in required["results"][0]["additionalContext"]
    status = diagnostic(outcome["actions"][4])
    assert status["recall"]["offers"]["offered_recall_admissions"] == 1
    assert status["recall"]["offers"]["recall_admission_ids"] == [handoff["admission_id"]]
    assert status["recall"]["last"]["state"] == "deduplicated"
