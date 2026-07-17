# Cellarium — backlog

The single authoritative task list for Cellarium. Organized by **task class** (A–H); within each class, by
**priority**. **New tasks, findings, and bugs go here** — under the right class, with an ID, priority, and a
one-line description; do not spin up separate audit/TODO docs.

**Scope.** These are our items (Evangelos's audit + roadmap + TODO). Filippo's Council-defect ledger (D1–D6, on the
`operationalization-debate` branch) is a **separate, Filippo-owned** workstream; it is *cross-referenced* where it
touches an item here, never folded in.

**Priority.** `P1` — before publication / open-source. `P2` — soon. `P3` — polish / later.
**Source.** `A` audit · `T` TODO · `R` roadmap/old-audit open items · `N` new (surfaced in reconciliation) · `S`
AI-for-Science direction. Audit IDs (M-/DS-/LLM-/AG-/D-/UX-/H-/SP-) carry over from the 2026-07-14 audit; its full
file:line evidence lives in git history (commit `55ed67f`).

## P1 at a glance (the critical path)
~~`H-1` CI~~ ✅ · `M-1` falsifier executability · `DS-1` slope inference · `LLM-1` model currency ·
~~`SP-1` loop-closure~~ ✅ · `SP-2` receptive field · `UX-1` accessibility · `SCI-1` FBA cross-check (science).

---

## A · Methodology & scientific rigor

| ID | P | Item | Src |
|----|---|------|-----|
| **M-1** | P1 | **Falsifier executability** — the Council prescribes tests the tools can't run (`dip test` unimplemented; `slope 95% CI` not computed). Add a bimodality tool + slope SE/CI/p, or constrain the rubric to executable tests. *Pairs with Filippo's D1/D2 (decision-rule logical consistency) — coordinate: executable + negation-complete are two halves of one falsifier-quality effort.* | A |
| **M-2** | P2 | **Reproducibility** — Council + agent run at unset temperature. Pin temperature/seed and record in `Hypothesis` provenance. *(Bundle with LLM-3 + H-3.)* | A |
| **M-3** | P2 | Provenance mis-tag — `wildtype` short-circuits to in-sample regardless of condition; gate on `condition ∈ IN_SAMPLE_CONDITIONS`; add test. | A |
| **M-4** | P3 | Tie the in-sample condition set to the actual ParCa fit set + a test so it can't silently drift. | A |
| **M-5** | P2 | **DOE for falsifier panels** — wrap `experimental-design` (randomization/blocking/factorial + power) beyond seeds×generations. | T |
| **M-6** | P2 | **Council librarian rewire** (Phase 3a) — wire the pre-/between-round literature step into `deliberate()` over `web_get`; judge stays literature-free; add `library_brief` to `test_blindness` allow-list. | T |
| **M-7** | P3 | Sufficiency-gate progressive narrowing — thread prior attempts; ask only the still-missing of {target, observable, comparison}; stay blind. | T |
| **M-8** | P3 | Analyst robustness — order-randomization + self-consistency; heterogeneous adversarial (analyst/verifier/skeptic) pass. Token-costly; gate to high-stakes conclusions. | R |
| **M-9** | P2 | Calibrate the viability verdict thresholds (0.9/0.6, set on n=1 machinery) against a machinery + graded-KO panel. *Needs sims.* | R |

## B · Data science & statistics

| ID | P | Item | Src |
|----|---|------|-----|
| **DS-1** | P1 | `fit_relation` reports slope/R² but **no inference** — add t-based slope SE/CI/p + adjusted R²; report n. *(Overlaps M-1.)* | A |
| **DS-2** | P2 | `effect_z_vs_corpus` conflates between-design spread with replicate noise — rename "vs corpus spread"; never present as significance. | A |
| **DS-3** | P3 | Channel-level `differential.summary` has no per-channel significance — attach the Welch-t (or a note) to top channel movers. | A |
| **DS-4** | P3 | Add a regression test pinning `t_critical_95` (table + Cornish-Fisher branch). | A |

## C · LLM engineering

| ID | P | Item | Src |
|----|---|------|-----|
| **LLM-1** | P1 | **Model currency + claim** — runtime defaults `claude-sonnet-4-5` lag the eval (`claude-sonnet-5`) and the "Opus 4.8" claim; audit what `"auto"` routes to; bump defaults; make the external claim precise. | A |
| **LLM-2** | P2 | **Observability** — log `resp.usage`, request IDs, a cost/latency meter. *(The Council per-round-transcript slice is Filippo's method gap — coordinate.)* | A |
| **LLM-3** | P2 | Agent temperature unset (non-deterministic reasoning) — offer temperature=0 / recorded seed. *(Same root as M-2.)* | A |
| **LLM-4** | P3 | `_estimate_tokens` is `chars//4` — drive the compaction trigger from `resp.usage`/`count_tokens`. | A |
| **LLM-5** | P3 | Standardize retry config (agent `max_retries=4` vs Council SDK default 2). | A |

## D · Agentic systems

| ID | P | Item | Src |
|----|---|------|-----|
| ~~**SP-1**~~ | ✅ | **Hypothesis lifecycle reflection** — each falsifier design shows its live state (proposed / queued / running / available / failed), derived from the launch queue by semantic match + corpus membership; the re-run is guarded (no re-queue of an in-flight or done design). **Done** — see Completed. | A |
| **SP-1b** | P2 | **Explicit Cellwright write-back** — when the agent *revises or invalidates* a specific Council design (rather than just running it), record that delta on the Hypothesis and surface the Council-vs-Cellwright diff. Needs a session↔hypothesis link + an agent-side write; the SP-1 queue/corpus derivation already covers the "did it run?" half. | A |
| **SP-2** | P1 | **Cellwright receptive field** — informative truncation ("k of N dropped"); full-scan anomaly/change-point tools; sub-agent map-reduce over large trajectories; a receptive-field eval (inject a known transient + a mid-rank mover). *Lit-pass warranted first (hierarchical/map-reduce summarization, sub-agent fan-out, change-point detection).* | A |
| **AG-1** | P2 | Launch queue is a lock-free JSON read-modify-write at a relative path — file lock (or move into SQLite) + absolute config-rooted path. | A |
| **AG-2** | P2 | 38 tools + ~4 KB router prompt — consolidate overlapping tools; track tool-selection error rate in the eval. | A |
| **AG-3** | P3 | Dispatch: explicit unknown-tool guard + semantic input validation test. | A |
| **AG-4** | P3 | `approve_and_run` is synchronous in a request thread with no cancellation — move to a job runner for multi-user. | A |

## E · Frontend: design & UX

| ID | P | Item | Src |
|----|---|------|-----|
| **UX-1** | P1 | **Accessibility** (WCAG 2.2 AA) — ARIA live region for streaming, labels/roles on custom controls, keyboard nav, focus-visible. | A |
| **D-1** | P2 | `innerHTML` escaping is a fragile invariant across 37 sinks — one safe render helper + a lint rule against raw `innerHTML =` with interpolation (audit the dynamic sinks: Council claims/objections, corpus rows, queue `from_question`). | A |
| **UX-2** | P2 | Standardize loading / empty / error / retry states + `aria-busy`; long ops (download, sim) show determinate progress. | A |
| **D-2** | P3 | No dark mode in the app (`prefers-color-scheme` unused) though the report is theme-aware — add a theme or state single-theme intent. | A |
| **D-3** | P3 | Split the monolithic `app.js` (1447 ln) / `style.css` when it grows. | A |
| **UX-3** | P3 | Add a minimal Playwright/DOM smoke test for the SPA. | A |

## F · Infrastructure & hygiene

| ID | P | Item | Src |
|----|---|------|-----|
| ~~**H-1**~~ | ✅ | **CI** — GitHub Actions (`ruff` + `pytest` blocking, advisory `mypy`) on PR + push to main. Done — see Completed. | A |
| **H-2** | P2 | Add `[tool.ruff]` / `[tool.mypy]` / `[tool.pytest]` config to `pyproject.toml`. | A |
| **H-3** | P2 | Pin deps + lockfile (uv/pip-tools); record model+temp+seed per run. *(Reproducibility bundle with M-2/LLM-3.)* | A |
| **H-4** | P3 | Add a secret-scan to CI. | A |
| **H-5** | P3 | Reconcile / remove the stray `package-lock.json` (no-build vanilla-JS app). | A |
| **H-6** | P3 | Code hygiene — `gene_scope.json` staleness/hash guard (C3); warn when `essential_ref` is disabled (C4); move `_reader_worker.py` pure aggregation host-side for unit-testing (C2). | R |

## G · Scientific capability (research features)

| ID | P | Item | Src |
|----|---|------|-----|
| **SCI-1** | P1·sci | **cobrapy → FBA tool-wrappers** (`fba_growth` / `fba_gene_knockout` / `fba_flux` / `fba_essentiality_panel` over iML1515) — an *independent* genome-scale essentiality cross-check; where the whole-cell verdict, the FBA call, and the Baba/Keio benchmark disagree is a grounded model limit. The top scientific unlock. *(= roadmap P4.2 "fba_essentiality v2 / EcoCyc oracle".)* | T + R |
| **SCI-2** | P2·sci | **pydeseq2** — compare the model's simulated expression against real *E. coli* RNA-seq (a complementary model-limits / validation angle). | T |
| **SCI-3** | future·sci | **Colony-scale via Vivarium** (Agmon 2022; the whole-colony model runs wcEcoli cells as agents) — the vehicle for the growth-dependent, ribosome-limited antibiotic-susceptibility regime the platform surfaced. | S |
| **SCI-4** | P3·sci | Multi-gene / reduced-genome design generator, scored by viability. *(Deprioritized.)* | R |
| **SCI-5** | P3·sci | ML surrogate for viability/division trained on the corpus (compute reduction) — a "Well for the Cell" artifact. | R |

## H · Publication & authoring

| ID | P | Item | Src |
|----|---|------|-----|
| **PUB-1** | P3 | Adopt the publication K-Dense skills: `scientific-writing` (manuscript), `citation-management`/`pyzotero`, `scientific-visualization`/`schematics`/`slides`/`latex-posters`, `peer-review` (pre-submission self-critique), `uncertainty-quantification`. *(`research-grants` used for the AI-for-Science application.)* | T |

---

## Completed
- **H-1 · CI** (2026-07-14) — `.github/workflows/ci.yml` runs `ruff check` + `pytest` (blocking) and `mypy`
  (advisory) on every PR and push to `main`. Added `[tool.ruff]` / `[tool.pytest.ini_options]` / `[tool.mypy]`
  config + a `dev` extra to `pyproject.toml`, tuned ruff to the codebase's style (real-bug rules on; semicolon /
  long-line style off), and fixed 13 pyflakes issues (unused imports, empty f-strings, redundant in-function
  imports). Suite: **119 passed, 1 skipped**.

- **SP-1 · Hypothesis lifecycle reflection** (2026-07-14) — a recorded Hypothesis now reflects what actually
  happened to each falsifier design. `launch.lifecycle_for_designs` matches each design against the launch queue by
  *semantic identity* (perturbation/condition/gene-set/key-params, ignoring the resolved `variant_index`), so a run
  submitted from the Council surface **or** proposed by Cellwright is reflected back; `hypothesis_get` merges that
  with corpus membership into a per-design `state` (proposed/queued/running/available/failed); the frontend shows a
  status badge and **guards the re-run** (no Queue button on an in-flight or done design), and `propose_panel`
  ("Queue all") is now idempotent. Unit-tested (`test_lifecycle_reflects_queue_by_semantic_match`) + verified
  end-to-end in the browser. Remainder tracked as **SP-1b**.

## Coordinate with Filippo (separate workstream)
Filippo's Council-defect ledger (`docs/COUNCIL_IMPROVEMENT_LEDGER.md` + `docs/council_issues.yaml`, branch
`operationalization-debate`) covers D1–D6. Touch points with this backlog, to reconcile when his branch merges:
- **M-1** (falsifier *executability*) ⟷ his **D1/D2** (falsifier *logical consistency*) — two halves of one
  falsifier-quality effort.
- **LLM-2** (observability) ⟷ his **method gap** (the Council's per-round transcript isn't persisted; `ablation.json`
  keeps only counts) — persisting transcripts enables systematic Council analysis and measuring M-1.

## Provenance
This backlog replaced three task docs, now **removed** (recoverable from git history at commit `55ed67f`):
`POST_HACKATHON_AUDIT.md` (the file:line audit evidence), `POST_HACKATHON_TODO.md` (deferred work), and
`docs/AUDIT.md` (the 2026-07-10 harness audit). `docs/ROADMAP.md` is **kept** as cited design-history — it is
referenced by `docs/SOCRATIC_COUNCIL.md` and the code, not a task source; its open items (M-8/M-9/H-6/SCI-1/4/5)
now live here.
