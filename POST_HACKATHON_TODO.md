# Post-hackathon TODO

> ⚠️ **Deprecated — folded into [BACKLOG.md](BACKLOG.md)** (classes A/G/H). Retained for history.

Deferred work — not for the Cellarium hackathon window. Kept out of git until we pick it up.

## End-goal K-Dense skills to adopt (publication + rigor)

Vendored-and-wired now: `paper-lookup`, `literature-review`, `bgpt-paper-search` (literature core, over
`web_get`); `cobrapy` + `experimental-design` are vendored but not yet executable (need FBA-tool wrappers /
DOE-script running — see "cobrapy + experimental-design integration" below). To adopt *after* the hackathon:

- **scientific-writing** — draft the manuscript (the publication end-goal).
- **research-grants** — the Claude Science / AI-for-Science application.
- **citation-management** / **pyzotero** — manage the bibliography for the paper.
- **scientific-visualization** / **scientific-schematics** / **scientific-slides** / **latex-posters** /
  **infographics** — ResearchStudio-Reel-style publication artifacts from the corpus + hypotheses.
- **peer-review** — pre-submission self-critique of the manuscript.
- **uncertainty-quantification** — formal UQ to match the t-CI / variance-band rigor already in the codebase.
- **pydeseq2** — compare the whole-cell model's simulated expression against real E. coli RNA-seq (another
  model-limits / validation angle, complementary to `cobrapy`'s FBA cross-check).

## cobrapy → FBA tool-wrappers (the model-limits superpower)

`cobrapy` is vendored but not executable — it runs the COBRApy Python library. Rather than give the agent a
sandboxed code-exec capability (bigger surface), wrap **specific FBA operations as Cellarium tools** (safest,
grounded, glass-box-traced) so Cellwright can run *independent* genome-scale FBA and cross-check the whole-cell
model's metabolic predictions. This is the biggest scientific unlock — it's how "the model is wrong here" becomes a
grounded claim rather than a hunch.

- **Model:** load a curated E. coli genome-scale model (iML1515) once; keep it in `data/`. (Add `cobra` to deps.)
- **Tools to wrap** (each returns numbers Cellwright can cite):
  - `fba_growth(condition)` — max-growth FBA objective on a medium → predicted growth rate.
  - `fba_gene_knockout(gene)` — single-gene deletion FBA → growth ratio vs WT, essential/non-essential call.
  - `fba_flux(reaction | gene)` — flux through a reaction/enzyme (WT vs KO) — pairs with `reroute_diagnosis`.
  - `fba_essentiality_panel(genes)` — batch KO essentiality across a gene set.
- **The payoff — model-limits detection:** compare genome-scale FBA essentiality against the whole-cell model's
  viability verdict AND the Baba/Joyce benchmark. Where the three disagree (esp. `model_UNDER_predicts` — homeostatic
  FBA reroutes and calls an essential gene viable) is exactly a model limit worth reporting / a wet-lab candidate.
- **Boundary:** FBA is steady-state / growth-maximizing; the whole-cell model is dynamic/homeostatic — surface both,
  never conflate. Cite which came from which. (This complements `mechanistic_scope`'s static benchmark with live FBA.)
- Follow the vendored `skills/vendor/k-dense/cobrapy/references/{api_quick_reference,workflows}.md` for the API.

## experimental-design → DOE for falsifier panels

Vendored with DOE scripts (`doe_designs.py`, `randomization.py`). Wrap as tools (or run the scripts) so the Council's
falsifier panels get real randomization/blocking/factorial design + power, beyond the current seeds×generations.

## Council librarian rewire (Phase 3a completion)

Wire the pre-round (question) + between-round (sharpened claim) library step into `deliberate()` using the vendored
literature skills over `web_get`, replacing the generic `web_search` primitive. Judge stays literature-free; ≤3
searches/deliberation; add `library_brief` to `test_blindness`'s allow-list and assert no corpus refs. (Spec agreed.)

## Sufficiency gate — progressive narrowing

Today the gate has no cross-attempt memory: on a repeated too-broad reply it returns a fixed
cached nudge (via the attempt counter), which stops the "asks the same thing again" loop but
does not *learn* across attempts. It never acknowledges what the user already specified.

**Goal:** make the gate narrow progressively — e.g. "you named the gene (pfkA) but not the
observable; give me just the observable to compare." Instead of a generic "be specific" nudge
on repeat, ask only for the *still-missing* piece.

**How:**
- Thread the prior attempt(s) — the earlier question(s) and the clarifying questions already
  asked — into `sufficiency_gate` (the `reuse_id` row already gives us the session thread to
  hang this on).
- Have the gate report, per attempt, which of {target, observable, comparison} is now supplied
  vs still missing, and ask only for the missing one(s).
- Keep it **blind**: still scope-only, never a hint at the answer — re-run `test_blindness`.

**Trade-off to weigh:** this replaces the cached (LLM-free) repeat response with another tailored
gate call per attempt, so it costs a Haiku call on each repeat instead of nothing. Decide whether
the better UX is worth that (probably yes once we're past the hackathon cost sensitivity).
