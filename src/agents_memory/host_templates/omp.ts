import { spawn } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import type { ExtensionAPI, ExtensionContext } from "@oh-my-pi/pi-coding-agent";

const hookArgv: string[] = __HOOK_ARGV__;
const hookInputBytes: number = __HOST_INPUT_BYTES__;

type Reply = {
  state: string;
  code?: string;
  stdout: { reason?: string; additionalContext?: string; warning?: string };
};
type AgentState = { instance: string; prepared?: string; ingress?: string };

// The factory is rebound for children. No state lives in the shared module cache.
export default function (pi: ExtensionAPI) {
  const agents = new Map<string, AgentState>();
  const state = (ctx: ExtensionContext) => {
    const identity = JSON.stringify([ctx.sessionManager.getSessionId(), ctx.agent]);
    let current = agents.get(identity);
    if (!current) {
      current = { instance: randomUUID() };
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
          if (!result || typeof result.state !== "string" || !result.stdout || result.provider_input_observed !== false) {
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
    current.ingress = current.instance;
    current.prepared = undefined;
    const result = await invoke(ctx, "input", { text: event.text, source: event.source });
    notify(ctx, result);
  });

  pi.on("before_agent_start", async (event, ctx) => {
    const current = state(ctx);
    const signature = createHash("sha256").update(event.prompt).digest("hex");
    // Re-entry prepares the same submission, not a new observed provider input.
    // In print/ACP/batched paths there is no native ingress ID: identity is limited.
    if (current.prepared !== signature) {
      current.instance = current.ingress || randomUUID();
      current.ingress = undefined;
      current.prepared = signature;
    }
    const result = await invoke(ctx, "before_agent_start", { prompt: event.prompt });
    notify(ctx, result);
    // Native pre-request errors/timeouts are swallowed and cannot cancel a
    // provider request. This adapter is advisory; strict installation is refused.
    if (result.stdout.additionalContext) {
      return { message: { customType: "agents-memory.bounded-context", content: result.stdout.additionalContext, display: false } };
    }
  });

  pi.on("tool_call", async (event, ctx) => {
    if (!["write", "edit", "read"].includes(event.toolName)) return;
    // Transmit footprint fields, not file contents, code bodies or provider traces.
    const input = event.input as Record<string, unknown>;
    const result = await invoke(ctx, "tool_call", {
      tool_name: event.toolName,
      tool_input: { path: input.path, file_path: input.file_path, notebook_path: input.notebook_path },
      tool_use_id: event.toolCallId,
    });
    notify(ctx, result);
  });

  // before_provider_request also fires for warmup/retry and handlers chain after
  // this one. after_provider_response precedes body consumption. Neither proves
  // final input or a tool call's causal request, so neither advances permission.
  for (const event of ["session_start", "session_before_switch", "session_switch", "session_before_branch", "session_branch", "session_before_compact", "session_compact", "session_tree", "session_shutdown"] as const) {
    pi.on(event, async (_event, ctx) => {
      const current = state(ctx);
      current.instance = randomUUID();
      current.prepared = undefined;
      current.ingress = undefined;
      const result = await invoke(ctx, event);
      notify(ctx, result);
    });
  }

  for (const [name, event] of [["memory-finding", "capture_finding"], ["memory-correction", "capture_correction"]] as const) {
    pi.registerCommand(name, {
      description: "Explicitly capture the submitted finding/correction in this project's local producer spool",
      handler: async (args, ctx) => {
        if (!args.trim()) {
          ctx.ui.notify("CAPTURE_EMPTY", "warning");
          return;
        }
        const result = await invoke(ctx, event, { text: args, hook_instance_id: randomUUID(), adapter_turn_id: undefined });
        notify(ctx, result);
      },
    });
  }
}
