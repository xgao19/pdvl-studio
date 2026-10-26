// One bounded Codex SDK task in an isolated Git workspace.
// Input: one JSON object on stdin. Output: JSONL events on stdout.
import process from "node:process";

function emit(obj) { process.stdout.write(JSON.stringify(obj) + "\n"); }

const controller = new AbortController();
process.on('SIGTERM', () => controller.abort());
process.on('SIGINT', () => controller.abort());

let raw = "";
for await (const chunk of process.stdin) raw += chunk.toString();
try {
  const task = JSON.parse(raw);
  if (!task.workdir || !task.question) throw new Error("Missing workdir or question");
  const { Codex } = await import("@openai/codex-sdk");
  const runtime = task.runtime;
  if (!runtime?.provider || process.env.CODEX_HOME !== runtime.home || process.env.CODEX_SQLITE_HOME !== runtime.home) {
    throw new Error("Missing isolated Codex runtime environment");
  }
  // Freeze the explicit provider at queue time; never infer it from a model name.
  const config = {
    model_provider: runtime.provider,
    sqlite_home: runtime.home,
    cli_auth_credentials_store: "ephemeral",
    // CLI authentication needs the API key; executed shell commands and snapshots do not.
    features: {shell_snapshot: false},
    shell_environment_policy: {inherit: "core"},
    model_providers: {[runtime.provider]: {
      name: runtime.name, base_url: runtime.base_url, env_key: runtime.env_key,
      wire_api: "responses", requires_openai_auth: false,
    }},
  };
  const codex = new Codex({config});
  const options = {
    model: runtime.model,
    workingDirectory: task.workdir,
    sandboxMode: "workspace-write",
    approvalPolicy: "never",
    // Network is disabled; no remote tool/HPC access is implicitly authorized.
    networkAccessEnabled: false,
    webSearchMode: "disabled",
    skipGitRepoCheck: false,
  };
  const thread = task.thread_id ? codex.resumeThread(task.thread_id, options) : codex.startThread(options);
  let finalResponse = "";
  const { events } = await thread.runStreamed(task.question, {signal: controller.signal});
  for await (const event of events) {
    if (event.type === "turn.failed") throw new Error(event.error?.message || "Codex turn failed");
    if (event.type === "item.completed" && event.item?.type === "agent_message") {
      finalResponse = event.item.text || finalResponse;
    }
    emit({kind:"event", event});
  }
  emit({kind:"final", text:finalResponse, thread_id:thread.id || null});
} catch (err) {
  if (controller.signal.aborted) {
    emit({kind:'cancelled'});
  } else {
    emit({kind:"error", message:String(err?.message || err).slice(0,1000)});
    process.exitCode = 1;
  }
}
