# PDVL Studio

**Physics Discovery & Verification Loop — a standalone AI research workbench.**

One GitHub repository, one local web workspace, and independent research state. GPT-6, DeepSeek, compatible self-hosted models, and Codex are **replaceable providers**, not owners of your science. This is a research-oriented starter application with tested local core functionality, not a production multi-tenant SaaS or a completed autonomous physicist.

### At a glance

- **Discuss:** ChatGPT-like natural theoretical-physics dialogue; hypothesis-friendly, no default engineering prose.
- **Investigate:** deep reasoning chat plus optional sandboxed Codex SDK task runs.
- **Verify:** narrow executable QFT checks and immutable evidence records; explicitly distinguishes a formal identity from physical observability.
- **Write:** separate scientific-writing prompt, manuscript notebook and revision history and editable per-project **Scientific Voice**; prose does not simply rewrite Codex logs.
- **Independent state:** projects, conversations, claims, evidence, decisions, runs, manuscript revisions, stored in SQLite; provider/model and API usage metadata recorded per assistant message.
- **Multiple models:** OpenAI Responses API, DeepSeek V4 Responses API, custom Responses/Chat-Completions-compatible endpoints. For additional compatibility, extend the provider adapter or use a gateway like LiteLLM.
- **Optional MCP:** local STDIO server exposes read-only research context to outside agent clients; not required by the standalone web UI.
- **Update-friendly:** model registry; pinned SDK and Github dependabot CI. Do not silently change models for recorded research tasks.

### Quick start (macOS / Linux)

```bash
unzip pdvl-studio.zip   # if downloaded as archive
cd pdvl-studio
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[test]'
cp .env.example .env
# Set OPENAI_API_KEY and/or DEEPSEEK_API_KEY in .env
./scripts/start.sh
```

Open **http://127.0.0.1:8765**. Start from the included CS-kernel demonstration project, create a new project, and choose a model in the toolbar. No API key is needed to use the research notebook or run local deterministic checks. **Live model responses require a provider API key.** Your ChatGPT subscription is not an API key and cannot magically call an existing ChatGPT conversation.

### Codex SDK worker (optional but integrated)

```bash
cd worker/codex && npm install && cd ../..
# Install / authenticate Codex CLI according to official docs.
# Set PDVL_CODEX_ENABLED=1 in .env
./scripts/start.sh
```

The web interface now exposes **Investigate → Launch Codex research**. A separate Python worker consumes the SQLite job queue and calls the official TypeScript Codex SDK through `worker/codex/index.mjs`, which launches a task in a fresh Git workspace under `.local/runs/<run_id>/workspace`. Event traces are stored alongside the run, and the status is visible in the browser. **No automatic HPC submissions.** To use DeepSeek as Codex's *underlying model*, select it in the Codex Investigation model picker and configure Codex's own `model_providers.deepseek` according to its official guide (see `docs/PROVIDERS.md`), then pick that model for the agent task.

### Offline demonstrator

In the CS-kernel demo, use **Run scoped physical check** on two claims. The RG difference check uses SymPy to verify a shared-anomalous-dimension cancellation. The proposed automatic model-independent EEC extraction is labeled `not_established`, rather than incorrectly promoted from the RG argument. This is an educational harness test, **not a new physics discovery**.

### Trace a research result into a manuscript

1. Record a precise hypothesis. A Codex task freezes the project's claims, evidence, decisions, latest drafts and recent discussion when queued.
2. In **Investigate**, use **Refresh tasks and artifacts** after execution. Inspect the frozen context and archived files, including derivations, scripts and outputs. Archived bytes and SHA-256 hashes survive workspace edits and database backups.
3. Choose an artifact and claim, describe its relevance, and **Record as evidence**. The initial verdict is `unresolved`; recording evidence never automatically verifies a claim.
4. In **Write**, place the cursor at the relevant passage and choose **Cite in manuscript** beside an evidence record. Save a revision. Inline `[evidence:ID]` citations are checked against the project; reopening the draft restores its source links.

The implementation adds one artifact table and reuses the existing revision reference field. Archives are limited to 10 MiB per run and reject symlinks. See [Architecture](docs/ARCHITECTURE.md) for the storage contract and migration behavior. Offline tests exercise the complete chain with a local mock agent; real provider/Codex authentication still requires separate testing.

### Run tests

```bash
pytest -q
node --check worker/codex/index.mjs
node --check web/app.js
```

Testing the actual Codex runtime and real provider responses requires authorized API credentials and runtime dependencies; unit and API tests use isolated temporary databases and mocked model responses.

### Source layout

```text
pdvl-studio/
├── pdvl/             FastAPI, CLI, provider/router, evidence database, verifier, task worker
├── web/              Integrated responsive research web workbench
├── worker/codex/     Official Codex SDK adapter (Node.js)
├── configs/          Explicit model IDs and defaults; no API secrets
├── docs/             Architecture, provider setup, scientific protocol
├── tests/            TestClient API/evidence/verification cases
├── scripts/          One-command startup and optional GitHub publish helper
└── .github/          CI + Dependabot
```

### Publish as your own private GitHub repository

When you have GitHub CLI installed and authenticated (not possible automatically in this environment):

```bash
./scripts/publish_github.sh YOUR_GITHUB_USERNAME/pdvl-studio --private
```

Or create an empty GitHub repository manually and `git push`. The system runs independently of GitHub; GitHub stores *code*, while `.local/` remains a **private research datastore**, excluded from commits by default. Export/sync selected validated artifacts consciously, especially for unpublished collaboration data.

### Important scope boundaries

This release is a **working integrated foundation**, not a finished scientific search engine: no credentialed API calls or real Codex run were performed in the packaging environment; no live arXiv retrieval, file-ingestion parser, remote auth, HPC scheduler, multi-user access, PDF citation resolver or production cost dashboard is claimed complete. The independent architecture makes those clear plugin additions rather than requiring a UI rewrite. Do not expose this unauthenticated local app on a public interface.

See [Architecture](docs/ARCHITECTURE.md), [Provider details](docs/PROVIDERS.md) and [Research protocol](docs/RESEARCH_PROTOCOL.md).

### Finish the broader research platform with Codex

The bundled workbench is an integrated **working baseline**; the full scientific workflow (PDF-to-equation references, streamed Codex event approvals, production math editor, HPC dry-run adapters, etc.) is not already implemented. To develop those components in one coherent project, give Codex [`docs/CODEX_COMPLETE_BUILD_PROMPT.md`](docs/CODEX_COMPLETE_BUILD_PROMPT.md) in the cloned repository. The prompt requires implementation and executable tests, not another architecture slide deck.

For controlled model upgrades, use `python scripts/evaluate_models.py` for a no-cost dry run, then `python scripts/evaluate_models.py --models gpt-sol deepseek-pro --run` after setting keys. Review the saved outputs rather than blindly scoring them as correct physics.
