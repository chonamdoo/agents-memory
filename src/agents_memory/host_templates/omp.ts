import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import type { ExtensionAPI, ExtensionContext } from "@oh-my-pi/pi-coding-agent";

const hookArgv: string[] = __HOOK_ARGV__;
const hookInputBytes: number = __HOST_INPUT_BYTES__;

type Reply = {
  state: string;
  code?: string | null;
  generation?: number;
  preparation_id?: string;
  capture?: { state: string; source_pointer?: Record<string, unknown>; capture_disposition?: string };
  stdout: { reason?: string; additionalContext?: string; warning?: string };
};
type AgentState = { agent: string; instance: string; generation: number; prepared?: string; ingress?: string };

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
  const beginning = "*** Begin Patch\n";
  const ending = value.endsWith("*** End Patch\n") ? "*** End Patch\n" : "*** End Patch";
  if (!value.startsWith(beginning) || !value.endsWith(ending)) return;
  const paths = new Set<string>();
  const addPath = (path: string): boolean => {
    // Resource selectors, escapes and home shorthand require a native resolver; never guess their scope.
    if (!path || path.trim() !== path || path.startsWith("~") || unresolvedPatchPath.test(path)) return false;
    paths.add(path);
    return paths.size <= 64;
  };
  let cursor = beginning.length;
  const end = value.length - ending.length;
  let inFile = false;
  let hasOperation = false;
  let bodyAllowed = false;
  let bodyRequired = false;
  while (cursor < end) {
    const newline = value.indexOf("\n", cursor);
    if (newline < 0 || newline >= end) return;
    const line = value.slice(cursor, newline);
    cursor = newline + 1;
    if (line.startsWith("+")) {
      if (!bodyAllowed) return;
      bodyRequired = false;
      continue;
    }
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
  const state = (ctx: ExtensionContext) => {
    const identity = JSON.stringify([ctx.sessionManager.getSessionId(), ctx.agent]);
    let current = agents.get(identity);
    if (!current) {
      current = { agent: JSON.stringify(ctx.agent), instance: randomUUID(), generation: 0 };
      agents.set(identity, current);
    }
    return current;
  };

  const invoke = async (ctx: ExtensionContext, event: string, fields: Record<string, unknown> = {}): Promise<Reply> => {
    const current = state(ctx);
    const envelope = JSON.stringify({
      event, cwd: ctx.cwd, session_id: ctx.sessionManager.getSessionId(), agent: ctx.agent,
      hook_instance_id: current.instance, adapter_turn_id: current.instance,
      model_api: ctx.model?.api, ...fields,
    });
    if (Buffer.byteLength(envelope) > hookInputBytes) throw new Error("HOST_ENVELOPE_INVALID");
    return await new Promise<Reply>((resolve, reject) => {
      const child = spawn(hookArgv[0], hookArgv.slice(1), { stdio: ["pipe", "pipe", "ignore"], shell: false });
      let bytes = 0;
      const chunks: Buffer[] = [];
      const timer = setTimeout(() => {
        child.kill("SIGKILL");
        reject(new Error("HOST_ADAPTER_UNAVAILABLE"));
      }, 14000);
      child.stdout.on("data", (chunk: Buffer) => {
        bytes += chunk.length;
        if (bytes > 16384) {
          child.kill("SIGKILL");
          reject(new Error("HOST_RESPONSE_TOO_LARGE"));
        } else chunks.push(chunk);
      });
      child.stdin.on("error", () => { /* Child exit is handled below, without input diagnostics. */ });
      child.on("error", () => {
        clearTimeout(timer);
        reject(new Error("HOST_ADAPTER_UNAVAILABLE"));
      });
      child.on("close", (code) => {
        clearTimeout(timer);
        if (code !== 0) return reject(new Error("HOST_ADAPTER_UNAVAILABLE"));
        try {
          const result = JSON.parse(Buffer.concat(chunks).toString("utf8"));
          if (!result || typeof result !== "object" || Array.isArray(result)
              || typeof result.state !== "string"
              || !result.stdout || typeof result.stdout !== "object" || Array.isArray(result.stdout)
              || result.provider_input_observed !== false
              || (result.code != null && typeof result.code !== "string")
              || (result.preparation_id !== undefined && typeof result.preparation_id !== "string")
              || (result.capture !== undefined && (!result.capture || typeof result.capture !== "object" || Array.isArray(result.capture)
                || typeof result.capture.state !== "string"
                || (result.capture.source_pointer !== undefined && (!result.capture.source_pointer
                  || typeof result.capture.source_pointer !== "object" || Array.isArray(result.capture.source_pointer)))
                || (result.capture.capture_disposition !== undefined && typeof result.capture.capture_disposition !== "string")))
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

  const notify = (ctx: ExtensionContext, result: Reply) => {
    if (result.stdout.warning || result.state === "degraded" || result.state === "blocked") {
      ctx.ui.notify(result.stdout.reason || result.stdout.additionalContext || result.code || result.stdout.warning || "HOST_CAPTURE_DEGRADED", "warning");
    }
  };

  pi.on("input", async (event, ctx) => {
    const current = state(ctx);
    current.instance = randomUUID();
    current.generation += 1;
    current.ingress = current.instance;
    current.prepared = undefined;
    const generation = current.generation;
    const result = await invoke(ctx, "input", { text: event.text, source: event.source });
    if (state(ctx) !== current || current.generation !== generation) return;
    notify(ctx, result);
  });

  pi.on("before_agent_start", async (event, ctx) => {
    const current = state(ctx);
    const admissionGeneration = current.generation;
    const admission = await invoke(ctx, "prepare_prompt", { prompt: event.prompt });
    if (state(ctx) !== current || current.generation !== admissionGeneration) return;
    if (admission.state !== "ok" || typeof admission.preparation_id !== "string" || !/^[a-f0-9]{64}$/.test(admission.preparation_id)) {
      notify(ctx, admission);
      return;
    }
    const signature = admission.preparation_id;
    // OMP re-enters preparation for the same submission; that keeps its turn and generation.
    if (current.prepared !== signature) {
      current.instance = current.ingress || randomUUID();
      current.ingress = undefined;
      current.prepared = signature;
      current.generation += 1;
    }
    const generation = current.generation;
    const result = await invoke(ctx, "before_agent_start", { prompt: event.prompt });
    if (state(ctx) !== current || current.generation !== generation || current.prepared !== signature) return;
    notify(ctx, result);
    if (result.stdout.additionalContext) {
      if (Buffer.byteLength(result.stdout.additionalContext, "utf8") > 1800) {
        ctx.ui.notify("HOST_CAPTURE_POINTER_OMITTED", "warning");
        return;
      }
      return { message: { customType: "agents-memory.bounded-context", content: result.stdout.additionalContext, display: false } };
    }
  });

  pi.on("tool_call", async (event, ctx) => {
    if (!["write", "edit", "read"].includes(event.toolName)) return;
    // Transmit bounded footprint fields, never patch bodies or provider traces.
    const nativeInput: unknown = event.input;
    const input = nativeInput && typeof nativeInput === "object" && !Array.isArray(nativeInput)
      ? nativeInput as Record<string, unknown> : {};
    const toolInput = event.toolName === "edit"
      && (typeof nativeInput === "string" || Object.prototype.hasOwnProperty.call(input, "input"))
      ? { paths: hashlineFootprint(typeof nativeInput === "string" ? nativeInput : input.input) }
      : { path: input.path, file_path: input.file_path, notebook_path: input.notebook_path };
    const result = await invoke(ctx, "tool_call", {
      tool_name: event.toolName,
      tool_input: toolInput,
      tool_use_id: event.toolCallId,
    });
    notify(ctx, result);
  });

  // before_provider_request also fires for warmup/retry and handlers chain after
  // this one. after_provider_response precedes body consumption. Neither proves
  // final input or a tool call's causal request, so neither advances permission.
  for (const event of ["session_start", "session_before_switch", "session_switch", "session_before_branch", "session_branch", "session_before_compact", "session_compact", "session_tree", "session_shutdown"] as const) {
    pi.on(event, async (_event, ctx) => {
      const agent = JSON.stringify(ctx.agent);
      for (const [identity, entry] of agents) if (entry.agent === agent) agents.delete(identity);
      const current = state(ctx);
      current.generation += 1;
      const result = await invoke(ctx, event);
      notify(ctx, result);
    });
  }

  for (const [name, event] of [["memory-finding", "capture_finding"], ["memory-correction", "capture_correction"]] as const) {
    pi.registerCommand(name, {
      description: name === "memory-correction"
        ? "Capture a new correction-kind source; does not correct or retract an existing target"
        : "Explicitly capture the submitted finding in this project's local producer spool",
      handler: async (args, ctx) => {
        if (!args.trim()) {
          ctx.ui.notify("CAPTURE_EMPTY", "warning");
          return;
        }
        const current = state(ctx);
        current.instance = randomUUID();
        current.generation += 1;
        current.prepared = undefined;
        current.ingress = undefined;
        const generation = current.generation;
        const result = await invoke(ctx, event, { text: args });
        if (state(ctx) !== current || current.generation !== generation) return;
        notify(ctx, result);
        const status = result.stdout.additionalContext || (result.capture && JSON.stringify(result.capture));
        if (status) ctx.ui.notify(status, "info");
      },
    });
  }
}
