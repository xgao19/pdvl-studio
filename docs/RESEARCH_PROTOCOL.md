# Scientific quality contract

PDVL is neither a proof assistant nor an autonomous truth machine.

1. **Free exploration first:** Ideas may be radical, unfinished or wrong. Discussions should not be reduced to engineering schedules and feasibility checklists.
2. **Specific claims next:** Define operators, renormalization conventions, physical limits, assumptions, uncertainties and the exact conclusion. A RG identity does not prove experimental observability.
3. **Evidence with provenance:** Original reference/DOI/arXiv revision and equation anchor for theory; code commit, inputs, ensemble, executable, fit range, random seed, covariance and output hashes for data.
4. **Independent checks:** Mathematical identities, physical symmetry/limits, fitting closure, alternate analysis and genuine cross-method comparisons. Check if a purported independent verification was used as an input constraint.
5. **Intellectually mature writing:** Manuscript prose starts from the physics message and supported claims, NOT a Codex engineering log. Avoid empty lists, timid hedging, novelty marketing or compulsory risk paragraphs. Do not conceal real uncertainty.
6. **No fake completion:** No claim that an API call, calculation, library search or Codex job happened when the integration was not configured and executed. `unresolved` is a valid and sometimes decisive scientific status.

In the workbench, preserve this distinction by registering an archived artifact against a specific claim with your interpretation and verdict. Cite the resulting evidence ID at the relevant manuscript passage using `[evidence:ID]`. A citation records a traceable source; it does not upgrade the claim, validate an agent derivation, or establish independence. Revisions retain their source IDs, archived bytes and run/context provenance for inspection.

## Test problem: CS kernel

Given common evolution convention and anomalous dimension, the difference `K(b1, μ) - K(b2, μ)` is RG invariant. This is a **narrow identity**; determining whether SIDIS/DY/EEC data can isolate it independently of unknown inputs requires explicit factorization and identifiability arguments. In this starter, the former is checked by SymPy, while the overstrong claim is marked *not established*. This negative example tests scientific epistemic discipline, not an all-purpose no-go theorem.
