import { spawn } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { performance } from "node:perf_hooks";
import type { ExtensionAPI, ExtensionContext } from "@oh-my-pi/pi-coding-agent";

const hookArgv: string[] = __HOOK_ARGV__;
const hookInputBytes: number = __HOST_INPUT_BYTES__;

type Observation = { state: string; code?: string };
type RecallOffers = { offered_recall_admissions: number; recall_admission_ids: string[]; unjudged_admissions: string };
type Reply = {
  state: string;
  code?: string | null;
  generation?: number;
  health?: { code_observation: Observation; session: Observation };
  preparation_id?: string;
  capture?: { state: string; capture_key?: string; source_pointer?: Record<string, unknown>; capture_disposition?: string };
  recall?: Record<string, unknown> & { state: string };
  recall_offers?: RecallOffers;
  stdout: { reason?: string; additionalContext?: string; warning?: string };
};
type Incident = {
  active: boolean; count: number; recoveries: number; codes: Record<string, number>; activeCodes: string[];
  last: Reply; lastFailure?: Reply;
  lastFailureScope?: { cwd: string; submission_observed: boolean; adapter_turn_id?: string };
};
type AgentState = {
  session: string; agent: string; instance: string; generation: number; prepared?: string; ended?: string;
  ingress: Map<string, string[]>; epoch: string; started: number; sequence: number;
  queue: Promise<unknown>; deadline: number; incidents: Map<string, Incident>; cancel?: () => void; stopping?: boolean;
  recall?: { offers: RecallOffers; generation?: number; last?: Reply["recall"] };
};

// A gap without its code could not be attributed, so it is malformed rather than a silent non-failure.
const isObservation = (value: unknown): value is Observation =>
  typeof value === "object" && value !== null && !Array.isArray(value)
  && "state" in value && typeof value.state === "string"
  && ("code" in value ? typeof value.code === "string" : value.state !== "gap");
const isHealth = (value: unknown): value is NonNullable<Reply["health"]> =>
  typeof value === "object" && value !== null && !Array.isArray(value) && Object.keys(value).length === 2
  && "code_observation" in value && isObservation(value.code_observation)
  && "session" in value && isObservation(value.session);
const isRecallOffers = (value: unknown): value is RecallOffers =>
  typeof value === "object" && value !== null && !Array.isArray(value)
  && "offered_recall_admissions" in value && Number.isSafeInteger(value.offered_recall_admissions)
  && "recall_admission_ids" in value && Array.isArray(value.recall_admission_ids) && value.recall_admission_ids.length <= 8
  && value.recall_admission_ids.every(item => typeof item === "string")
  && "unjudged_admissions" in value && typeof value.unjudged_admissions === "string";

const patchRange = "[1-9]\\d*\\.=[1-9]\\d*";
const patchBlock = "[1-9]\\d*\\*";
const patchGap = "(?:<[1-9]\\d*|>[1-9]\\d*\\*?|>\\$)";
const patchLocator = `(?:${patchRange}|${patchBlock}|${patchGap})`;
const patchBody = new RegExp(`^PUT ${patchLocator}:$`);
const patchPaste = new RegExp(`^PUT ${patchLocator} @[A-Za-z0-9_-]+$`);
const patchRestore = new RegExp(`^PUT ${patchGap}$`);
const patchCut = new RegExp(`^CUT (?:${patchRange}|${patchBlock})(?: @[A-Za-z0-9_-]+)?$`);
const patchHeader = /^\[([^#\r\n]+)#[0-9A-F]{4}\]$/;
const unresolvedPatchPath = /[:?\\\0\r\n"']/;
const unquotedPatchWhitespace = /\s/;

const hashlineFootprint = (value: unknown): string[] | undefined => {
  if (typeof value !== "string" || Buffer.byteLength(value, "utf8") > hookInputBytes) return;
  // The native edit tool accepts both the wrapped and the bare hashline form; a wrapper must still be complete.
  const beginning = "*** Begin Patch\n";
  let patch = value;
  if (patch.startsWith(beginning)) {
    const ending = patch.endsWith("*** End Patch\n") ? "*** End Patch\n" : "*** End Patch";
    if (!patch.endsWith(ending) || patch.length < beginning.length + ending.length) return;
    patch = patch.slice(beginning.length, patch.length - ending.length);
  }
  if (!patch.endsWith("\n")) patch += "\n";
  const paths = new Set<string>();
  const addPath = (path: string): boolean => {
    // Resource selectors, escapes and home shorthand require a native resolver; never guess their scope.
    if (!path || path.trim() !== path || path.startsWith("~") || unresolvedPatchPath.test(path)) return false;
    paths.add(path);
    return paths.size <= 64;
  };
  let cursor = 0;
  const end = patch.length;
  let inFile = false;
  let hasOperation = false;
  let bodyAllowed = false;
  let bodyRequired = false;
  while (cursor < end) {
    const newline = patch.indexOf("\n", cursor);
    if (newline < 0 || newline >= end) return;
    if (patch.startsWith("+", cursor)) {
      cursor = newline + 1;
      if (!bodyAllowed) return;
      bodyRequired = false;
      continue;
    }
    const line = patch.slice(cursor, newline);
    cursor = newline + 1;
    if (bodyRequired) return;
    const header = patchHeader.exec(line);
    if (header) {
      if ((inFile && !hasOperation) || !addPath(header[1])) return;
      inFile = true;
      hasOperation = false;
      bodyAllowed = false;
      continue;
    }
    if (!inFile) return;
    bodyAllowed = patchBody.test(line);
    bodyRequired = bodyAllowed;
    if (!bodyAllowed && !patchPaste.test(line) && !patchRestore.test(line) && !patchCut.test(line) && line !== "REM") {
      if (!line.startsWith("MV ")) return;
      let destination = line.slice(3);
      if (destination.startsWith("\"") || destination.startsWith("'")) {
        if (destination.length < 3 || destination.at(-1) !== destination[0]) return;
        destination = destination.slice(1, -1);
      } else if (unquotedPatchWhitespace.test(destination)) return;
      if (!addPath(destination)) return;
    }
    hasOperation = true;
  }
  if (!inFile || !hasOperation || bodyRequired) return;
  return [...paths];
};

// The factory is rebound for children. No state lives in the shared module cache.
export default function (pi: ExtensionAPI) {
  const agents = new Map<string, AgentState>();
  const establishing: Record<string, true> = { session_start: true, session_switch: true, session_branch: true, session_tree: true };
  const identity = (ctx: ExtensionContext) => JSON.stringify([ctx.sessionManager.getSessionId(), ctx.agent]);
  const state = (ctx: ExtensionContext) => {
    const key = identity(ctx);
    let current = agents.get(key);
    if (!current) {
      current = {
        session: ctx.sessionManager.getSessionId(), agent: JSON.stringify(ctx.agent), instance: randomUUID(), generation: 0,
        ingress: new Map(), epoch: randomUUID(), started: Math.floor((performance.timeOrigin + performance.now()) * 1000), sequence: 0,
        queue: Promise.resolve(), deadline: 0, incidents: new Map(),
      };
      agents.set(key, current);
    }
    return current;
  };

  const serial = async <T>(ctx: ExtensionContext, phase: string, operation: (current: AgentState) => Promise<T>): Promise<T | undefined> => {
    const current = state(ctx);
    const deadline = Date.now() + (phase === "session_shutdown" ? 1500 : 26000);
    if (phase === "session_shutdown") {
      for (const entry of agents.values()) {
        entry.stopping = true;
        entry.cancel?.();
      }
    } else if (establishing[phase]) {
      // Only the established session stays addressable: its agents keep incident history,
      // while prior sessions' agents are retired so the map cannot grow across sessions.
      for (const [key, entry] of agents) {
        if (entry.session === current.session) {
          entry.stopping = false;
        } else {
          entry.stopping = true;
          entry.cancel?.();
          agents.delete(key);
        }
      }
    }
    const previous = phase === "session_shutdown"
      ? Promise.all([...agents.values()].map(entry => entry.queue)) : current.queue;
    const task = previous.then(async () => {
      current.deadline = deadline;
      if (current.stopping && phase !== "session_shutdown") throw new Error("HOST_LIFECYCLE_STALE");
      if (Date.now() >= deadline) throw new Error("HOST_EVENT_DEADLINE");
      return await operation(current);
    });
    current.queue = task.catch(() => undefined);
    try {
      return await task;
    } catch (error) {
      if (phase === "preparation") {
        current.prepared = undefined;
        current.instance = randomUUID();
        current.generation += 1;
      }
      const code = error instanceof Error ? error.message : "HOST_ADAPTER_UNAVAILABLE";
      notify(ctx, current, {
        state: "degraded", code, stdout: { warning: code },
        ...(["input", "explicit_capture"].includes(phase)
          ? { capture: { state: "unknown", capture_disposition: "native_event_result_unobserved" } } : {}),
      }, phase);
    }
  };
  const invoke = async (ctx: ExtensionContext, current: AgentState, event: string, fields: Record<string, unknown> = {}): Promise<Reply> => {
    const envelope = JSON.stringify({
      event, cwd: ctx.cwd, session_id: ctx.sessionManager.getSessionId(), agent: ctx.agent,
      hook_instance_id: randomUUID(), adapter_turn_id: current.prepared ? current.instance : undefined,
      adapter_epoch: current.epoch, adapter_epoch_started: current.started,
      adapter_sequence: ++current.sequence, event_deadline_ms: current.deadline,
      model_api: ctx.model?.api, ...fields,
    });
    if (Buffer.byteLength(envelope) > hookInputBytes) throw new Error("HOST_ENVELOPE_INVALID");
    const remaining = current.deadline - Date.now();
    if (remaining <= 0) throw new Error("HOST_EVENT_DEADLINE");
    return await new Promise<Reply>((resolve, reject) => {
      const child = spawn(hookArgv[0], hookArgv.slice(1), {
        stdio: ["pipe", "pipe", "ignore"], shell: false, detached: process.platform !== "win32",
      });
      let bytes = 0;
      const chunks: Buffer[] = [];
      let failure: string | undefined;
      const terminate = (code: string) => {
        failure ??= code;
        if (child.pid && process.platform !== "win32") {
          try {
            process.kill(-child.pid, "SIGKILL");
          } catch {
            child.kill("SIGKILL");
          }
        } else child.kill("SIGKILL");
      };
      current.cancel = () => terminate("HOST_LIFECYCLE_STALE");
      const timer = setTimeout(() => terminate("HOST_EVENT_DEADLINE"), Math.max(1, current.deadline - Date.now()));
      child.stdout.on("data", (chunk: Buffer) => {
        bytes += chunk.length;
        if (bytes > 16384) {
          terminate("HOST_RESPONSE_TOO_LARGE");
        } else chunks.push(chunk);
      });
      child.stdin.on("error", () => { /* Child exit is handled below, without input diagnostics. */ });
      child.on("error", () => {
        clearTimeout(timer);
        current.cancel = undefined;
        reject(new Error("HOST_ADAPTER_UNAVAILABLE"));
      });
      child.on("close", (code) => {
        clearTimeout(timer);
        current.cancel = undefined;
        if (failure) return reject(new Error(failure));
        if (code !== 0) return reject(new Error("HOST_ADAPTER_UNAVAILABLE"));
        try {
          const result = JSON.parse(Buffer.concat(chunks).toString("utf8"));
          if (!result || typeof result !== "object" || Array.isArray(result)
              || typeof result.state !== "string"
              || !result.stdout || typeof result.stdout !== "object" || Array.isArray(result.stdout)
              || result.provider_input_observed !== false
              || (result.code != null && typeof result.code !== "string")
              || (result.preparation_id !== undefined && typeof result.preparation_id !== "string")
              || (result.health !== undefined && !isHealth(result.health))
              || (result.capture !== undefined && (!result.capture || typeof result.capture !== "object" || Array.isArray(result.capture)
                || typeof result.capture.state !== "string"
                || (result.capture.source_pointer !== undefined && (!result.capture.source_pointer
                  || typeof result.capture.source_pointer !== "object" || Array.isArray(result.capture.source_pointer)))
                || (result.capture.capture_disposition !== undefined && typeof result.capture.capture_disposition !== "string")))
              || (result.recall !== undefined && (!result.recall || typeof result.recall !== "object" || Array.isArray(result.recall)
                || typeof result.recall.state !== "string"))
              || (result.recall_offers !== undefined && !isRecallOffers(result.recall_offers))
              || (result.stdout.reason !== undefined && typeof result.stdout.reason !== "string")
              || (result.stdout.additionalContext !== undefined && typeof result.stdout.additionalContext !== "string")
              || (result.stdout.warning !== undefined && typeof result.stdout.warning !== "string")) {
            throw new Error("invalid response");
          }
          resolve(result as Reply);
        } catch {
          reject(new Error("HOST_RESPONSE_INVALID"));
        }
      });
      child.stdin.end(envelope);
    });
  };

  const remember = (current: AgentState, result: Reply) => {
    if (result.recall_offers) {
      current.recall = { offers: result.recall_offers, generation: result.generation, last: result.recall ?? current.recall?.last };
    }
  };

  const notify = (ctx: ExtensionContext, current: AgentState, result: Reply, phase: string) => {
    const healthGap = [result.health?.code_observation, result.health?.session].find(value => value?.state === "gap");
    const failure = !!result.stdout.warning || result.state === "degraded" || result.state === "blocked" || !!healthGap;
    let incident = current.incidents.get(phase);
    if (!incident) {
      incident = { active: false, count: 0, recoveries: 0, codes: {}, activeCodes: [], last: result };
      current.incidents.set(phase, incident);
    }
    incident.last = result;
    if (failure) {
      incident.count += 1;
      incident.lastFailure = result;
      incident.lastFailureScope = {
        cwd: ctx.cwd, submission_observed: !!current.prepared,
        adapter_turn_id: current.prepared ? current.instance : undefined,
      };
      const code = result.code || healthGap?.code || result.stdout.warning || "HOST_CAPTURE_DEGRADED";
      incident.codes[code] = (incident.codes[code] || 0) + 1;
      incident.active = true;
      // Repeats of one code aggregate; a different code is a distinct failure that an open incident must not hide.
      if (!incident.activeCodes.includes(code)) {
        incident.activeCodes.push(code);
        ctx.ui.notify(`${phase}: ${result.stdout.reason || code}; details: /memory-status`, "warning");
      }
    } else if (incident.active && result.state === "ok") {
      incident.active = false;
      incident.activeCodes = [];
      incident.recoveries += 1;
      ctx.ui.notify(`${phase}: memory adapter recovered; details: /memory-status`, "info");
    }
  };

  // OMP awaits input handlers before it queues the submission, so the capture must not be awaited
  // here or Enter waits on this agent's hooks and the service. It is enqueued synchronously, so the
  // submission's preparation still runs after it and sees its correlation locator.
  pi.on("input", (event, ctx) => void serial(ctx, "input", async (current) => {
    const operation = randomUUID();
    const result = await invoke(ctx, current, "input", { text: event.text, source: event.source, hook_instance_id: operation });
    notify(ctx, current, result, "input");
    // A correlation digest is derived only from input the backend accepted as capturable; rejected
    // secrets are never hashed or retained here.
    if (typeof result.capture?.capture_key !== "string" || result.code === "SOURCE_SECRET_REJECTED") return;
    const key = createHash("sha256").update(event.text).digest("hex");
    const pending = current.ingress.get(key) || [];
    if (pending.length < 2) pending.push(operation);
    current.ingress.set(key, pending);
    if (current.ingress.size > 16) current.ingress.delete(current.ingress.keys().next().value!);
  }).catch(() => undefined));

  pi.on("before_agent_start", async (event, ctx) => serial(ctx, "preparation", async (current) => {
    const admissionGeneration = current.generation;
    const admission = await invoke(ctx, current, "prepare_prompt", { prompt: event.prompt });
    if (agents.get(identity(ctx)) !== current || current.generation !== admissionGeneration) return;
    if (admission.state !== "ok" || typeof admission.preparation_id !== "string" || !/^[a-f0-9]{64}$/.test(admission.preparation_id)) {
      notify(ctx, current, admission, "preparation");
      // A rejected secret submission was never admitted, so it neither ends the live
      // submission nor advances capture/offer authority or generation.
      if (admission.code === "SOURCE_SECRET_REJECTED") return;
      current.prepared = undefined;
      current.instance = randomUUID();
      current.generation += 1;
      return;
    }
    const signature = admission.preparation_id;
    let ingressOperation: string | undefined;
    const key = createHash("sha256").update(event.prompt).digest("hex");
    const pending = current.ingress.get(key);
    // While the submission is live, queued input whose text equals it is indistinguishable
    // from re-entry, so its locator is dropped instead of correlated with either turn.
    current.ingress.delete(key);
    // OMP re-enters preparation for the same submission; that keeps its turn and generation.
    // A terminally ended run is never re-entered, so identical text afterwards is a new submission.
    if (current.prepared !== signature || current.ended === current.instance) {
      current.instance = randomUUID();
      if (pending?.length === 1) ingressOperation = pending[0];
      current.prepared = signature;
      current.generation += 1;
    }
    const generation = current.generation;
    const result = await invoke(ctx, current, "before_agent_start", { prompt: event.prompt, ingress_operation_id: ingressOperation });
    if (agents.get(identity(ctx)) !== current || current.generation !== generation || current.prepared !== signature) return;
    remember(current, result);
    notify(ctx, current, result, "preparation");
    if (result.stdout.additionalContext) {
      if (Buffer.byteLength(result.stdout.additionalContext, "utf8") > 1800) {
        notify(ctx, current, { state: "degraded", code: "HOST_CAPTURE_POINTER_OMITTED", stdout: { warning: "HOST_CAPTURE_POINTER_OMITTED" } }, "preparation");
        return;
      }
      return { message: { customType: "agents-memory.bounded-context", content: result.stdout.additionalContext, display: false } };
    }
  }));

  // agent_end is notification-only and carries no prompt identity. The extension payload
  // reports willContinue; isTerminal is the session/RPC field, accepted for compatibility.
  // Only a settled end (both fields absent included) closes the submission.
  pi.on("agent_end", async (event, ctx) => {
    const end = event as { willContinue?: unknown; isTerminal?: unknown };
    if (end.willContinue === true || end.isTerminal === false) return;
    return serial(ctx, "agent_end", async (current) => {
      current.ended = current.instance;
    });
  });

  pi.on("tool_call", async (event, ctx) => serial(ctx, "action", async (current) => {
    if (!["write", "edit", "read"].includes(event.toolName)) return;
    // Transmit bounded footprint fields, never patch bodies or provider traces.
    const nativeInput: unknown = event.input;
    const input = nativeInput && typeof nativeInput === "object" && !Array.isArray(nativeInput)
      ? nativeInput as Record<string, unknown> : {};
    const toolInput = event.toolName === "edit"
      && (typeof nativeInput === "string" || Object.prototype.hasOwnProperty.call(input, "input"))
      ? { paths: hashlineFootprint(typeof nativeInput === "string" ? nativeInput : input.input) }
      : { path: input.path, file_path: input.file_path, notebook_path: input.notebook_path };
    const generation = current.generation;
    const epoch = current.epoch;
    const result = await invoke(ctx, current, "tool_call", {
      tool_name: event.toolName,
      tool_input: toolInput,
      tool_use_id: event.toolCallId,
    });
    // A lifecycle reset while the hook ran invalidates its context; never hand the model a stale submission's result.
    if (agents.get(identity(ctx)) !== current || current.generation !== generation || current.epoch !== epoch) return;
    remember(current, result);
    notify(ctx, current, result, "action");
    if (!result.stdout.additionalContext) return;
    // ui.notify is user-only; required context is echoed to the user, while a recall handoff is model work only.
    if (result.code) ctx.ui.notify(result.stdout.additionalContext, "info");
    // The returned additionalContext is what reaches the model, after this batch's tool results.
    return { additionalContext: result.stdout.additionalContext };
  }));

  // before_provider_request also fires for warmup/retry and handlers chain after
  // this one. after_provider_response precedes body consumption. Neither proves
  // final input or a tool call's causal request, so neither advances permission.
  for (const event of ["session_start", "session_before_switch", "session_switch", "session_before_branch", "session_branch", "session_before_compact", "session_compact", "session_tree", "session_shutdown"] as const) {
    pi.on(event, async (_event, ctx) => serial(ctx, event, async (current) => {
      if (establishing[event]) {
        // A restarted or replaced session invalidates every retained agent's lifecycle, not
        // only the agent that observed the boundary; incident history is kept.
        const now = Math.floor((performance.timeOrigin + performance.now()) * 1000);
        for (const entry of agents.values()) {
          if (entry.session !== current.session) continue;
          entry.epoch = randomUUID();
          entry.started = Math.max(now, entry.started + 1);
          entry.sequence = 0;
          entry.instance = randomUUID();
          entry.prepared = undefined;
          entry.ended = undefined;
          entry.ingress.clear();
          entry.generation += 1;
        }
      } else {
        if (event !== "session_before_compact" && event !== "session_compact") {
          current.instance = randomUUID();
          current.prepared = undefined;
          current.ingress.clear();
        }
        current.generation += 1;
      }
      const result = await invoke(ctx, current, event);
      notify(ctx, current, result, event);
    }));
  }

  pi.registerCommand("memory-status", {
    description: "Show scoped memory adapter incidents, occurrence counts, recovery and last structured outcomes",
    handler: async (_args, ctx) => {
      const current = state(ctx);
      // An unawaited input capture may still be running; report settled outcomes, bounded so a hung
      // hook cannot also hold the diagnostic.
      const queueSettled = await Promise.race([
        current.queue.then(() => true),
        new Promise<boolean>(resolve => { setTimeout(resolve, 2000, false).unref(); }),
      ]);
      ctx.ui.notify(JSON.stringify({
        agent: ctx.agent, session_id: ctx.sessionManager.getSessionId(), cwd: ctx.cwd, queue_settled: queueSettled,
        submission_observed: !!current.prepared, provider_input_observed: false,
        coverage: current.prepared ? "advisory_submission_observed" : "limited_no_agent_preparation",
        pending_ingress_correlations: current.ingress.size,
        recall: current.recall ?? { offers: { offered_recall_admissions: 0, recall_admission_ids: [], unjudged_admissions: "unobserved" } },
        incidents: Object.fromEntries(current.incidents),
      }), "info");
    },
  });

  for (const [name, event] of [["memory-finding", "capture_finding"], ["memory-correction", "capture_correction"]] as const) {
    pi.registerCommand(name, {
      description: name === "memory-correction"
        ? "Capture a new correction-kind source; does not correct or retract an existing target"
        : "Explicitly capture the submitted finding in this project's local producer spool",
      handler: async (args, ctx) => serial(ctx, "explicit_capture", async (current) => {
        if (!args.trim()) {
          ctx.ui.notify("CAPTURE_EMPTY", "warning");
          return;
        }
        const result = await invoke(ctx, current, event, { text: args });
        notify(ctx, current, result, "explicit_capture");
        const status = result.stdout.additionalContext || (result.capture && JSON.stringify(result.capture));
        if (status) ctx.ui.notify(status, "info");
      }),
    });
  }
}
