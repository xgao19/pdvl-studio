// One bounded Codex SDK task in an isolated Git workspace.
// Input: one JSON object on stdin. Output: JSONL events on stdout.
import process from "node:process";

function emit(obj) { process.stdout.write(JSON.stringify(obj) + "\n"); }

let raw = "";
for await (const chunk of process.stdin) raw += chunk.toString();
try {
  const task = JSON.parse(raw);
  if (!task.workdir || !task.question) throw new Error("Missing workdir or question");
  const { Codex } = await import("@openai/codex-sdk");
  // Provider settings live in the Codex environment/config, not this application.
  const config = task.provider === "deepseek" ? { model_provider: "deepseek" } : {};
  const codex = new Codex({config});
  const options = {
    workingDirectory: task.workdir,
    sandboxMode: "workspace-write",
    // Network is disabled; no remote tool/HPC access is implicitly authorized.
    networkAccessEnabled: false,
    webSearchMode: "disabled",
    skipGitRepoCheck: false,
  };
  if (task.model) options.model = task.model;
  const thread = task.thread_id ? codex.resumeThread(task.thread_id, options) : codex.startThread(options);
  let finalResponse = "";
  const { events } = await thread.runStreamed(task.question);
  for await (const event of events) {
    if (event.type === "turn.failed") throw new Error(event.error?.message || "Codex turn failed");
    if (event.type === "item.completed" && event.item?.type === "agent_message") {
      finalResponse = event.item.text || finalResponse;
    }
    emit({kind:"event", event});
  }
  emit({kind:"final", text:finalResponse, thread_id:thread.id || null});
} catch (err) {
  emit({kind:"error", message:String(err?.message || err).slice(0,1000)});
  process.exitCode = 1;
}
