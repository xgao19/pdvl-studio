# Provider configuration — October 2026

Set API secrets only in `.env` or your OS secret manager. **Never commit API keys or research raw data to GitHub.**

## OpenAI Responses

Set `OPENAI_API_KEY`. Current model choices are configured in `configs/models.json`, e.g. `gpt-6-astra`, `gpt-6.1-sol`, `gpt-6-luna`. ChatGPT paid subscription entitlements are **not** the same as API billing or authentication. Normal ChatGPT conversation history/personalization is **not** imported into this workbench.

## DeepSeek native Responses

Set `DEEPSEEK_API_KEY`. As of 2026-10-25 the documented IDs include `deepseek-v4-pro` and `deepseek-flash`, using base URL `https://api.deepseek.com`. DeepSeek's Responses API is stateless; PDVL persists and resends the recent turns and project context. DeepSeek implements only a subset of OpenAI-specific hosted tools (its API may ignore `mcp`, `code_interpreter`, `file_search`, etc.). Accordingly, tool execution lives in PDVL or the Codex harness, not only at the model endpoint.

## Local or alternative model

Set `CUSTOM_API_BASE`, `CUSTOM_API_KEY`, `CUSTOM_MODEL` to any OpenAI-compatible service. Select **Custom OpenAI-compatible** for `/responses`, or **Custom Chat Completions** for `/chat/completions`. `CUSTOM_API_BASE` is the prefix before `/responses`. Some self-hosted vLLM/Ollama/OpenRouter services only offer Chat Completions; use the built-in `custom-chat` route, or an optional LiteLLM gateway for more protocols. **OpenAI-compatible** is a transport convention, not complete semantic parity.

If supporting many providers, consider [LiteLLM](https://docs.litellm.ai/docs/) as an optional external gateway, but preserve a native Responses path for frontier-model-specific tools and capabilities; never silently drop unsupported tool arguments.

## Isolated Codex API runtime

The pinned SDK launches its own CLI with `CODEX_HOME` and `CODEX_SQLITE_HOME` set **only in the child process** to `PDVL_HOME/codex` (normally `.local/codex`). It uses an explicit Responses provider and an environment API key. It does not use the ordinary `~/.codex` config/auth store or inherited ChatGPT credentials, API-key overrides or app session variables. No global login/logout or shell configuration change is needed. ChatGPT and the Codex App retain their own subscription login; PDVL tasks consume the chosen API provider's quota.

Install `npm --prefix worker/codex ci`. Create the private directory and `PDVL_HOME/codex/config.toml`; for the same Ollama Cloud account used by chat:

```toml
model = "deepseek-v4.1-flash:1017"
model_provider = "pdvl_ollama"
cli_auth_credentials_store = "ephemeral"

[features]
shell_snapshot = false

[shell_environment_policy]
inherit = "core"

[model_providers.pdvl_ollama]
name = "Ollama DeepSeek Flash"
base_url = "https://ollama.com/v1"
env_key = "CUSTOM_API_KEY"
wire_api = "responses"
requires_openai_auth = false
```

Keep the actual `CUSTOM_API_KEY` only in the ignored `.env`, shared with the existing custom chat adapter; keep both files private (mode `0600`). Set `PDVL_CODEX_ENABLED=1` and restart `./scripts/start.sh`. The example dated model must exist in your provider's model list. The runtime uses any explicitly configured provider ID except the CLI's reserved `openai`, `ollama`, and `lmstudio` IDs. The application never guesses a provider from a model prefix.

The page exposes only the configured Codex model. New tasks no longer accept `model_id` overrides; extra fields are rejected before queuing. Missing config/key fails explicitly, with no subscription fallback. Provider, model, base URL, key **variable name**, and isolated home are frozen in the task's context; API key values are never put in the task/archive. The SDK receives these frozen provider settings as CLI overrides. It disables shell snapshots (which can persist API-key exports) and gives executed commands only the core shell environment, excluding the API key. Model selection belongs to this config, so `PDVL_CODEX_MODEL` was removed.

Continuation requires an identical runtime profile and a saved session. Historical ChatGPT sessions and tasks from another provider cannot be resumed under Ollama. Their artifacts, evidence and manuscript citations stay available; submit a new task using those archived findings. Changing API key values for the same provider does not change the profile.

Cloud Chat Completions success alone does not prove CLI compatibility. Ollama documents stateless Responses support but excludes stateful Responses, hosted web search and custom/freeform tool-call replay. Validate commands, file edits, cancel and resume with the actual model/CLI pair. The CLI may report unknown model metadata for a third-party model; do not infer its context window or full tool compatibility from a small successful task.

References: [Codex environment isolation](https://learn.chatgpt.com/docs/config-file/environment-variables), [provider configuration](https://learn.chatgpt.com/docs/config-file/config-reference), [Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility).

## Per-role model routing

Model routing is stored under `discuss`, `investigate`, `verify`, and `write` keys in `configs/models.json`. You can change the selected model in the UI or set a new default in the registry. This is separate from Codex SDK model configuration. Record the actual model reported by providers for important research outcomes; snapshot aliases can move.

## Controlled upgrades

1. Review pinned SDK dependency changes and run the test suite before merging an update.
2. Add new model IDs in registry; keep the old ID available during evaluation.
3. Re-run the positive RG example, the overclaim example, and a small fixed set of blinded writing tasks on the candidate model.
4. Compare scientific errors, provenance quality, cost and writing style; switch the default *after* reviewing the comparison.

Official references: [OpenAI Codex SDK](https://learn.chatgpt.com/docs/codex-sdk), [OpenAI Responses](https://developers.openai.com/api/docs/guides/reasoning), [DeepSeek Responses](https://api-docs.deepseek.com/guides/responses_api/).
