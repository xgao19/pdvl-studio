# Codex instruction: develop PDVL Studio into a full private research workbench

You are maintaining **an independent research product**, not modifying ChatGPT itself and not forking Codex. Begin by reading `README.md`, `docs/ARCHITECTURE.md`, `docs/PROVIDERS.md`, `docs/RESEARCH_PROTOCOL.md` and existing code/tests. Extend the repository directly; do not merely write another architecture plan.

## Non-negotiable product behavior

1. The user should do all research in **one PDVL Studio interface**, with four modes: DISCUSS, INVESTIGATE, VERIFY and WRITE. Scientific dialogue is natural, flexible and incisive; the output must not inherit Codex's engineering/project-management style.
2. **Model agnosticism**: OpenAI Responses, DeepSeek native Responses, compatible Chat Completions and future providers. Maintain separate adapter interfaces for inference and tool-executing harnesses (Codex SDK initially, optional OpenCode/Pi later). Do not force all vendor-specific features through a lossy compatibility wrapper.
3. **Long-lived science state** remains ours: questions, hypotheses, claims, assumptions, evidence, references, calculations, revisions, decisions and failures persist in our database/artifact store. Chat histories are never treated as the authoritative evidence layer.
4. **Scientific validity**: do not promote model statements to verified facts. Verification tools must have explicit hypotheses, input artifacts, physics assumptions, execution logs and independently evaluated results.
5. **Privacy**: local-only by default; no unconsented external data transfers; no remote CDN scripts allowed; no automatic cluster submits, deletes, repository pushes, journal submissions or costly unattended tools.
6. **Upgradability**: provider/model registry, versioned prompts, pinned SDK, canary evaluations before changing defaults, replayable research manifests. Open source adapters are treated as replaceable modules.

## Complete the product, not just scaffolding

Implement the following *as working functionality with tests*, preserving the existing endpoints and schema (migrate safely as needed):

### (a) Unified research UX
- Streamed assistant responses for OpenAI and DeepSeek; render Markdown and scientific mathematics locally without external hosted scripts.
- Research project views with searchable notebooks, browser-based evidence inspection and clear links from physical claims to source papers and program outputs.
- Rich scientific writing workspace with LaTeX export and tracked revisions; maintain independent editorial voice per project, plus claim-to-prose mapping.
- Real-time Codex task timeline, suspend/cancel/continue and permission prompts; do not require the user to read raw engineering JSON.
- A low-friction compare-model workflow for selected difficult questions, keeping model differences as hypotheses to test rather than voting.

### (b) Agent and provider adapters
- Preserve `generate()` and direct Responses adapter; add explicit capability discovery and graceful fallback for unsupported tools.
- Codex integration using the SDK/app-server with safe worktrees, persistent thread IDs, streamed events, cancellation/approval and real capability smoke tests.
- Support DeepSeek-backed Codex with documented Codex provider config; do not pass a DeepSeek model ID to a non-configured OpenAI provider and claim success.
- Define an abstract `AgentTask`/`AgentResult` schema; allow future OpenCode/Pi adapters without modifying stored science data.

### (c) Research physics and evidence
- Real original-paper lookup using arXiv/INSPIRE and source version/location anchors; no fake citations. PDF ingestion must extract equations when possible and retain source snapshots/checksums.
- Build deterministic verifiers for dimensions, RG, Ward identity, kinematic limits and explicitly stated mock-data closure cases. Allow Mathematica/FORM in optional adapters.
- Keep unknown claims `unresolved`; test circular verification (using a normalization constraint as independent confirmation), and explicitly distinguish scheme invariance from observability.
- Add file/ensemble and analysis provenance: script commit hash, lattice spacing/volume and scale conventions, input hashes, statistical bootstrap seeds, covariance treatment, numerical outputs, uncertainty components and code environment.
- Manage a durable scientific hypothesis graph using normalized relational references first; only add a full graph database with demonstrated need.

### (d) HPC tool policy
- Optional PBS/SLURM adapters, initially read-only status and job-script generation/dry-run. Consequential submit, cancel, delete and large allocations require explicit user confirmation and limits. Do not grant arbitrary remote shell access to an LLM agent.

### (e) Quality and deployment
- Expand tests to include realistic mocked OpenAI/DeepSeek tool loops, Codex SDK integration smoke tests (when authenticated), claim/evidence provenance, migration/recovery, cancellation, scientific verification and prompt quality.
- Add reproducible offline benchmark of established QCD checks and intentionally invalid inferences. Separate mechanical pass/fail metrics from expert-rated scientific insight and prose quality.
- Deliver one-command local launch, automated tests, GitHub-ready CI/Dependabot, configuration and backups. Document every live provider/agent test actually executed versus missing credentials.

## Acceptance example

The user discusses a novel CS-kernel universal-shape relation in natural language via GPT or DeepSeek. The idea is saved as an unverified hypothesis. A Codex investigation (optionally using DeepSeek through Codex) produces a derivation, original-paper references and a mock-data test in an isolated workspace. A verifier checks the precise RG identity and flags the unsupported jump to direct EEC extraction. The results return to the same integrated research timeline and evidence ledger, where the user can inspect sources and continue the physics discussion. Finally WRITE develops a compact PRL-quality physical argument **from the verified evidence**, and stores a revision with a claim-to-prose sidecar. A restart, provider change or SDK update does not lose that history.

**Do not claim an end-to-end external integration is verified if provider keys, Codex auth or HPC permissions are absent.** Complete all locally testable software and provide exact user-only setup steps for the blocked parts. Report actual tests and limits, not optimistic predictions.
