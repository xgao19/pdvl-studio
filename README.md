# PDVL Studio

**Physics Discovery & Verification Loop — a standalone AI research workbench.**

One GitHub repository, one local web workspace, and independent research state. GPT-6, DeepSeek, compatible self-hosted models, and Codex are **replaceable providers**, not owners of your science. This is a research-oriented starter application with tested local core functionality, not a production multi-tenant SaaS or a completed autonomous physicist.

### At a glance

- **Discuss:** streamed theoretical-physics dialogue, live tool progress and stop control; public web search and archived webpage reading, arXiv search and project-paper full-text retrieval with source-access checks.
- **Investigate:** deep reasoning chat plus optional sandboxed Codex SDK task runs.
- **Verify:** narrow executable QFT checks and immutable evidence records; explicitly distinguishes a formal identity from physical observability.
- **Write:** separate scientific-writing prompt, manuscript notebook and revision history and editable per-project **Scientific Voice**; prose does not simply rewrite Codex logs.
- **Independent state:** projects, conversations, claims, evidence, decisions, runs, manuscript revisions, stored in SQLite; provider/model and API usage metadata recorded per assistant message.
- **Multiple models:** OpenAI Responses API, DeepSeek V4 Responses API, custom Responses/Chat-Completions-compatible endpoints. For additional compatibility, extend the provider adapter or use a gateway like LiteLLM.
- **Optional MCP:** local STDIO server exposes read-only research context to outside agent clients; not required by the standalone web UI.
- **Update-friendly:** model registry and pinned SDK. Do not silently change models for recorded research tasks.

### macOS Intel app

Download the [macOS Intel preview](https://github.com/xgao19/pdvl-studio/releases/tag/v0.2.0-intel-preview.1), drag **PDVL Studio.app** to Applications, and enter your own Ollama API key on first launch. Python, Node, Git and the pinned Codex runtime are bundled. Research data stays in `~/Library/Application Support/PDVL Studio` across app updates. The preview uses ad-hoc signing and is not Apple notarized; it was tested on macOS 26.6.2 Intel. See [installation, build and validation details](docs/MACOS_INTEL.md).

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
npm --prefix worker/codex ci
# Configure .local/codex/config.toml with the model and an env_key API provider.
# See docs/PROVIDERS.md; keep the key in .env.
# Set PDVL_CODEX_ENABLED=1 in .env
./scripts/start.sh
```

The web interface exposes **Investigate → Launch Codex research**. A separate Python worker consumes the SQLite job queue and calls the pinned TypeScript Codex SDK through `worker/codex/index.mjs`, which launches a task in a fresh Git workspace under `.local/runs/<run_id>/workspace`. The CLI uses the private `.local/codex` config/session store and an explicit Responses API provider. It can share the chat provider's environment API key without using or changing the normal ChatGPT/Codex App subscription login. The page and API lock tasks to the configured model. Event traces, progress and artifacts remain inspectable. **No automatic HPC submissions.** See [provider setup](docs/PROVIDERS.md).

### Offline demonstrator

In the CS-kernel demo, use **Run scoped physical check** on two claims. The RG difference check uses SymPy to verify a shared-anomalous-dimension cancellation. The proposed automatic model-independent EEC extraction is labeled `not_established`, rather than incorrectly promoted from the RG argument. This is an educational harness test, **not a new physics discovery**.

### Trace a research result into a manuscript

1. Record a precise hypothesis. A Codex task freezes the project's claims, evidence, decisions, latest drafts and recent discussion when queued.
2. In **Investigate**, use **Refresh tasks and artifacts** after execution. Inspect the frozen context and archived files, including derivations, scripts and outputs. Archived bytes and SHA-256 hashes survive workspace edits and database backups.
3. Choose an artifact and claim, describe its relevance, and **Record as evidence**. The initial verdict is `unresolved`; recording evidence never automatically verifies a claim.
4. In **Write**, place the cursor at the relevant passage and choose **Cite in manuscript** beside an evidence record. Save a revision. Inline `[evidence:ID]` citations are checked against the project; reopening the draft restores its source links.

In **Investigate**, task cards automatically show new progress while work is active. **取消任务** stops a queued or running task and preserves any archived partial work. Once stopped, use **继续运行** with a next question: this creates a linked task, resumes the same Codex session and restores archived files into a new workspace. The earlier task, evidence and manuscript sources remain intact. Tasks with no saved session or a different runtime profile (including historical ChatGPT tasks) must be submitted anew. Project selection and task navigation remain available in the narrow in-app browser layout.

The implementation adds one artifact table and reuses the existing revision reference field. Archives are limited to 10 MiB per run and reject symlinks. See [Architecture](docs/ARCHITECTURE.md) for the storage contract and migration behavior. Offline tests exercise the complete chain with a local mock agent; real provider/Codex authentication still requires separate testing.

### Read and compare papers (source development version)

1. Open **文献精读与对照**. Search arXiv keywords and import a result, paste an arXiv ID/abs/pdf link, or upload a text-layer PDF.
2. Select one paper and choose **精读这篇**, or select two and choose **对照这两篇**. Review the prepared question and send it in Discuss. The existing configured model, including Ollama, reads relevant original pages with tools.
3. Inspect **执行与原文读取记录** or click a checked page citation. Read by PDF page number, search keywords across the document, or continue a long page. Download the archived PDF to inspect equations and figures.
4. Save a claim, expand **登记为文献证据** on its source paper, specify the page and interpretation, then record evidence. In Write, cite that evidence and save a revision through the existing workflow.

Search results contain abstracts; importing preserves original PDF bytes and separately extracted page text with SHA-256 hashes. The reader reports partial scope and does not automatically verify claims. PDFs are limited to 8 MiB / 150 pages; scanned or encrypted files require preparation before import. No OCR or image interpretation is implemented. Publisher webpages can be read through the web workflow below; this does not import their PDF originals. The previously published Intel preview is unchanged; these features are currently validated from source.

### Search and read the public web

With a configured Ollama Cloud model at `https://ollama.com/v1`, Discuss reuses that provider's existing API key for Ollama's [web search and fetch APIs](https://docs.ollama.com/capabilities/web-search). No additional search service, SDK, key variable or model switch is needed. Other chat providers can still answer from archived sources; the web tools are advertised only when an Ollama Cloud credential is configured. Service authorization and quota errors are reported explicitly.

Ask a question requiring online sources, for example: “查阅 Ollama 官方联网搜索说明和 SQLite FTS5 官方文档，解释网页搜索与本地全文检索的区别。打开两个来源，阅读相关正文，并给出归档引用。” You can also paste a public webpage URL. The existing tool loop searches, opens relevant sources, archives the search/service responses and extracted text, reads needed sections and streams an answer with archive links. Search excerpts alone do not count as original reading; an answer that uses web tools without a checked webpage citation is flagged.

Expand **联网资料 · 搜索、阅读与归档** to reopen snapshots. Citations open the same source reader, showing URL, retrieval time, hash and section count. Web `§N` anchors refer to stored 7,000-character text segments, not website pagination. Search within a snapshot, read other sections, download the exact archived fetch response, or visit the original website. For follow-ups, ask about the sources already read: the model receives their IDs and can reread the immutable snapshots without fetching them again. Ask explicitly for fresh sources when timeliness matters. Reopening an unchanged URL/response reuses its snapshot; changed responses get new snapshots and leave earlier citations intact.

These are **Ollama-extracted webpage bodies, not raw HTML or guaranteed full-page copies**. The remote service fetches URLs; PDVL does not run website scripts, interpret images, bypass paywalls or provide OCR. Local/private addresses, credential-bearing URLs and custom ports are rejected; service responses are bounded to 2 MiB. Failure or cancellation does not archive a partial fetch. Completed snapshots survive stopping the chat. Treat webpage text as untrusted data. Source-access checks establish which snapshot/section was read, not whether a statement is true or entailed. To use a source in a manuscript, save a claim and explicitly register the relevant webpage section as evidence, then cite that evidence in Write.

### Stream, stop and search the project library

Discuss shows text as it arrives and reports actual searches, imports and page reads. **停止回答** cancels the server-side request and saves partial text as incomplete; reopening the conversation restores that state. Switching project or mode also stops the active chat. The same single chat path serves the other research modes.

In the literature panel, **检索项目全文** searches all archived papers in this project. You can also ask Discuss to find relevant passages without selecting papers: it has the same `search_project_papers` tool. Results are ranked keyword excerpts; the model must read the original pages before citing. Use English terms for English papers. Semantic/cross-language retrieval is not implemented.

On completion, page links are checked against project ownership, page bounds and actual recent read traces. Invalid links are disabled with an explanation. An existing evidence ID is checked against the project as well. A checked source is **not a guarantee that the answer is scientifically correct**; formula quality, interpretation and completeness still need review. During generation citations remain plain text until this check finishes. Neither retrieval nor chatting auto-registers evidence.

### Run tests

```bash
pytest -q
node --check worker/codex/index.mjs
node --check web/app.js
node --test tests/test_runs_ui.mjs
```

Testing the actual Codex runtime and real provider responses requires authorized API credentials and runtime dependencies; unit and API tests use isolated temporary databases and mocked model responses. Streaming cancellation tests bind temporary loopback ports; allow local socket access when running the suite in a sandbox. The fixed retrieval/citation corpus is `tests/fixtures/discuss_acceptance.json`, with no paid model calls.

Local integration validation on 2026-10-26: Codex SDK/CLI 0.164.0 with Ollama Cloud `deepseek-v4.1-flash:1017` created files, ran SymPy and checked a cancellation identity (`0`) with a negative control (`epsilon`). A foreground heartbeat task was cancelled and stopped; the same session resumed in a restored workspace and reran the symbolic checks. Archived hashes and the evidence → manuscript citation chain were checked, while the claim remained `idea`. Normal Codex config/auth hashes were unchanged and its ChatGPT login remained active. A final real command verified credential variables were absent from the shell environment; shell snapshots are disabled, and the key scan matched only the ignored `.env`. This validates the local pair and bounded tasks, not every CLI tool or model capability. Private runs remain under `.local/`. The suite includes deterministic retrieval/citation fixtures and real loopback streaming tests, plus Node tests for the actual UI handlers.

Literature validation on 2026-10-26 used the same Ollama model to search arXiv and read 2206.01105v1 (5 pages) and 2003.06063v2 (22 pages). Single-paper reading inspected PDF pages 1–3; comparison inspected both originals and continued a long page at offset 7000. Browser checks covered PDF upload/deduplication, page-link opening, evidence registration against PDF page 3, manuscript saving and source restoration after a service restart. Original PDF/text hashes were checked. The first search result exceeded the import limit and was explicitly rejected. Formula/figure interpretation still needs original-PDF review. No desktop package or release was updated.

Streaming/retrieval validation on 2026-10-26: **74 Python tests and 9 Node UI tests passed**. The same Ollama configuration performed project-wide keyword retrieval, original-page reads and checked citations. One bounded live follow-up produced 118 text delta events (first text at 2.605 seconds, completion at 2.914 seconds); this is a single smoke measurement, not a latency benchmark. Browser checks verified server-side stop, incomplete-state restoration, and successful follow-up after stopping. Source/evidence records survived service restarts without creating new evidence or promoting claims. Synthetic corpus tests validate retrieval/provenance mechanics; real-paper scientific accuracy, formula interpretation and completeness still require expert review. No package or Release was published.

Web validation on 2026-10-26: **107 Python tests and 11 Node UI tests passed**. The existing Ollama model automatically issued two searches, opened the Ollama and SQLite official documentation, read relevant archived sections and returned four checked source targets. A follow-up only reread stored snapshots, made no search/fetch calls and returned five checked targets. Browser checks opened the two-source inventory and the shared webpage reader with URL, timestamp, section navigation and response download. Mocked integration additionally checks cancellation, malformed/oversized responses, provider credential isolation, cross-project access, immutable version/deduplication behavior, evidence and manuscript references after restart. These establish source-access mechanics, not semantic correctness, search coverage or extraction fidelity. No dependency, package or Release was added.

### Evaluate Discuss with real papers

The [20-question source-pinned suite](evals/discuss_real_papers.json) uses three public CS-kernel papers and separate rubrics for source support and key limitations. The [2026-10-26 baseline](docs/evals/discuss-baseline-2026-10-26.md) records 20 completed Ollama trials: raw-question retrieval hit@8 was 14/20; labeled-page reading coverage was 88%; source audit marked 13 answers supported and 7 needing work. All mentioned the requested limitations, but most questions explicitly asked about them. These are single-run diagnostics with an agent source audit, not independent expert certification or a general physics accuracy score. At that baseline commit, the suite had 82 Python tests and 9 Node UI tests, including evaluator integrity and isolation checks.

```bash
python scripts/evaluate_discuss.py           # dry run: no downloads or model calls
set -a
source .env                                # existing private provider configuration
set +a
python scripts/evaluate_discuss.py --run     # calls the configured Discuss API
```

Each run uses a new `.local/evals/discuss_<timestamp>_<id>/research` database. It imports pinned PDFs through the existing archive path and clears only that sandbox's message history before each question. PDF/text hashes and source anchors must match. Gold rubrics are never sent to the answer model. The current research database, Codex credentials and application settings are untouched. Full answers, events, tool replay results, source archives and the generation-time suite/evaluator snapshots stay in the ignored run directory.

Edit that run's `reviews.json` to record source-audit verdicts and explanations, then regenerate the report without new model calls:

```bash
python scripts/evaluate_discuss.py --report .local/evals/discuss_<timestamp>_<id>
```

Unreviewed answers remain unreviewed, even when retrieval and citation access pass. Judgments must cover extra claims, not just the requested core fact; source access and literal anchor exposure never substitute for semantic review. Recorded timeouts/API failures remain failed trials. The evaluator replaces the previous three-question qualitative model canary; no parallel model-scoring workflow or new runtime dependency was added. The evaluator adds no application-side scoring path. The released Intel preview is unchanged.

### Source layout

```text
pdvl-studio/
├── pdvl/             FastAPI, CLI, provider/router, evidence database, verifier, task worker
├── web/              Integrated responsive research web workbench
├── worker/codex/     Official Codex SDK adapter (Node.js)
├── configs/          Explicit model IDs and defaults; no API secrets
├── docs/             Architecture, provider setup, scientific protocol
├── tests/            TestClient API/evidence/verification cases
└── scripts/          One-command startup and optional GitHub publish helper
```

### Publish as your own private GitHub repository

When you have GitHub CLI installed and authenticated (not possible automatically in this environment):

```bash
./scripts/publish_github.sh YOUR_GITHUB_USERNAME/pdvl-studio --private
```

Or create an empty GitHub repository manually and `git push`. The system runs independently of GitHub; GitHub stores *code*, while `.local/` remains a **private research datastore**, excluded from commits by default. Export/sync selected validated artifacts consciously, especially for unpublished collaboration data.

### Important scope boundaries

This is a **working integrated foundation**: public web search, extracted webpage snapshots, arXiv/PDF text ingestion and source citations are implemented in the source development version. OCR, equation/figure reconstruction, authenticated publisher access, remote auth, HPC scheduling, multi-user access and production cost accounting remain unimplemented. Live checks cover specific local models and bounded tasks. Do not expose this unauthenticated local app on a public interface.

See [Architecture](docs/ARCHITECTURE.md), [Provider details](docs/PROVIDERS.md) and [Research protocol](docs/RESEARCH_PROTOCOL.md).

### Finish the broader research platform with Codex

The bundled workbench is an integrated **working baseline**; the full scientific workflow (PDF-to-equation references, streamed Codex event approvals, production math editor, HPC dry-run adapters, etc.) is not already implemented. To develop those components in one coherent project, give Codex [`docs/CODEX_COMPLETE_BUILD_PROMPT.md`](docs/CODEX_COMPLETE_BUILD_PROMPT.md) in the cloned repository. The prompt requires implementation and executable tests, not another architecture slide deck.

For controlled Discuss changes, compare the frozen real-paper baseline with a fresh run and inspect the source audit. Add neutral, independently reviewed holdout questions before tuning repeatedly on these 20 development cases.
