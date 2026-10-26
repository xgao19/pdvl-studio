# Provider configuration — October 2026

Set API secrets only in `.env` or your OS secret manager. **Never commit API keys or research raw data to GitHub.**

## OpenAI Responses

Set `OPENAI_API_KEY`. Current model choices are configured in `configs/models.json`, e.g. `gpt-6-astra`, `gpt-6.1-sol`, `gpt-6-luna`. ChatGPT paid subscription entitlements are **not** the same as API billing or authentication. Normal ChatGPT conversation history/personalization is **not** imported into this workbench.

## DeepSeek native Responses

Set `DEEPSEEK_API_KEY`. As of 2026-10-25 the documented IDs include `deepseek-v4-pro` and `deepseek-flash`, using base URL `https://api.deepseek.com`. DeepSeek's Responses API is stateless; PDVL persists and resends the recent turns and project context. DeepSeek implements only a subset of OpenAI-specific hosted tools (its API may ignore `mcp`, `code_interpreter`, `file_search`, etc.). Accordingly, tool execution lives in PDVL or the Codex harness, not only at the model endpoint.

**Using DeepSeek inside Codex** is a separate configuration. See the [DeepSeek official Codex integration guide](https://api-docs.deepseek.com/quick_start/agent_integrations/codex/) and configure `[model_providers.deepseek]` in Codex. Prefer an `env_key` mechanism/OS secret manager and verify the applicable Codex version instead of blindly executing a remote install script. Pick `deepseek-v4-pro` as the Codex task model in the advanced task API, or configure the Codex CLI default. Test separately, since different model capabilities can affect agent behavior.

## Local or alternative model

Set `CUSTOM_API_BASE`, `CUSTOM_API_KEY`, `CUSTOM_MODEL` to any OpenAI-compatible service. Select **Custom OpenAI-compatible** for `/responses`, or **Custom Chat Completions** for `/chat/completions`. `CUSTOM_API_BASE` is the prefix before `/responses`. Some self-hosted vLLM/Ollama/OpenRouter services only offer Chat Completions; use the built-in `custom-chat` route, or an optional LiteLLM gateway for more protocols. **OpenAI-compatible** is a transport convention, not complete semantic parity.

If supporting many providers, consider [LiteLLM](https://docs.litellm.ai/docs/) as an optional external gateway, but preserve a native Responses path for frontier-model-specific tools and capabilities; never silently drop unsupported tool arguments.

## Codex authentication is separate from chat API keys

The installed TypeScript SDK launches its pinned CLI runtime and uses the local Codex authentication store. An existing ChatGPT login was successfully used in the 2026-10-25 local smoke test; no OpenAI API key was supplied to that worker. The ordinary Discuss/Write provider calls still use the API keys described above. Do not copy Codex credentials into this repository or `.env`.

Install the locked worker dependencies with `npm --prefix worker/codex ci`, confirm `codex login status`, set `PDVL_CODEX_ENABLED=1` in the private `.env`, and restart `./scripts/start.sh`. The script starts both the API and worker. For the live smoke test, the task explicitly selected `gpt-6.1-sol`; leaving the task model empty uses the configured Codex default. A successful login check alone does not establish a successful task run.

## Per-role model routing

Model routing is stored under `discuss`, `investigate`, `verify`, and `write` keys in `configs/models.json`. You can change the selected model in the UI or set a new default in the registry. This is separate from Codex SDK model configuration. Record the actual model reported by providers for important research outcomes; snapshot aliases can move.

## Controlled upgrades

1. Dependabot raises SDK dependency update PRs; never auto-merge until CI passes.
2. Add new model IDs in registry; keep the old ID available during evaluation.
3. Re-run the positive RG example, the overclaim example, and a small fixed set of blinded writing tasks on the candidate model.
4. Compare scientific errors, provenance quality, cost and writing style; switch the default *after* reviewing the comparison.

Official references: [OpenAI Codex SDK](https://learn.chatgpt.com/docs/codex-sdk), [OpenAI Responses](https://developers.openai.com/api/docs/guides/reasoning), [DeepSeek Responses](https://api-docs.deepseek.com/guides/responses_api/).
