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
~~`H-1` CI~~ ✅ · ~~`M-1` falsifier executability~~ ✅ · ~~`DS-1` slope inference~~ ✅ · ~~`LLM-1` model currency~~ ✅ ·
~~`SP-1` loop-closure~~ ✅ · `SP-2` receptive field · ~~`UX-1` accessibility~~ ✅ · `SCI-1` FBA cross-check (science).

---

## A · Methodology & scientific rigor

| ID | P | Item | Src |
|----|---|------|-----|
| ~~**M-1**~~ | ✅ | **Falsifier executability** — made the Council's named tests executable (`bimodality` tool + `fit_relation` slope CI, DS-1) AND built a **self-harness**: `test_registry.py` + `harness.py` detect a falsifier naming a test with no tool and auto-file a dev-gated gap into class X below (deterministic, idempotent, human-State-respecting). It already caught a real one — 4 stored hypotheses name Hartigan's dip (we have Sarle's BC). **Done** — see Completed. *Pairs with Filippo's D1/D2 (decision-rule logical consistency).* | A |
| ~~**M-1b**~~ | ✅ | **Structured falsifier test field** — `Falsifier` now carries a `NamedTest{test_id (registry enum) + "other"}`; the Council schema enum + proposer prompt are generated from the registry, and the harness flags `test_id="other"` as a deterministic **novel-gap** catch (not just the curated aliases). **Done** — see Completed. | N |
| ~~**M-2**~~ | ✅ | **Reproducibility** — temperature is now PINNED (`CELLARIUM_TEMPERATURE`, default 0.0) via `agent.temperature_for` (model-aware: omitted for reasoning/opus + when extended thinking is on) and RECORDED in the Hypothesis meta + agent session. Anthropic has no seed, so temperature is the named variance source. **Done** — see Completed. | A |
| ~~**M-3**~~ | ✅ | Provenance mis-tag — `_is_in_sample` now gates `wildtype` on the condition too (`wildtype/acetate` → out_of_sample), instead of short-circuiting to in_sample. Test added (`test_provenance.py`). **Done** — see Completed. | A |
| **M-4** | P3 | Tie the in-sample condition set to the actual ParCa fit set + a test so it can't silently drift. | A |
| **M-5** | P2 | **DOE for falsifier panels** — wrap `experimental-design` (randomization/blocking/factorial + power) beyond seeds×generations. | T |
| **M-6** | P2 | **Council librarian rewire** (Phase 3a) — wire the pre-/between-round literature step into `deliberate()` over `web_get`; judge stays literature-free; add `library_brief` to `test_blindness` allow-list. | T |
| **M-7** | P3 | Sufficiency-gate progressive narrowing — thread prior attempts; ask only the still-missing of {target, observable, comparison}; stay blind. | T |
| **M-8** | P3 | Analyst robustness — order-randomization + self-consistency; heterogeneous adversarial (analyst/verifier/skeptic) pass. Token-costly; gate to high-stakes conclusions. | R |
| **M-9** | P2 | Calibrate the viability verdict thresholds (0.9/0.6, set on n=1 machinery) against a machinery + graded-KO panel. **Ours** — the panel is a sim campaign Cellarium runs itself (`manifest.campaign` / `approve_and_run`, its own Docker pipeline) and the calibration is our own logic; sequenced behind that self-run sim campaign, not blocked on another workstream. | R |

## B · Data science & statistics

| ID | P | Item | Src |
|----|---|------|-----|
| ~~**DS-1**~~ | ✅ | `fit_relation` now reports **slope inference** — t-based SE, two-sided p, 95% CI, `slope_ci_excludes_0`, and adj R² (scipy-free incomplete-beta p-value in `stats.py`). A "law" is asserted only when the slope CI clears 0, not from R² alone. **Done** — see Completed. | A |
| ~~**DS-2**~~ | ✅ | Renamed `effect_z_vs_corpus` → `z_vs_corpus_spread` (disconfirm + instrument) + a checklist line: descriptive positioning within the corpus's between-design spread, NOT a significance test. **Done** — see Completed. | A |
| **DS-3** | P3 | Channel-level `differential.summary` has no per-channel significance — attach the Welch-t (or a note) to top channel movers. | A |
| **DS-4** | P3 | Add a regression test pinning `t_critical_95` (table + Cornish-Fisher branch). | A |

## C · LLM engineering

| ID | P | Item | Src |
|----|---|------|-----|
| ~~**LLM-1**~~ | ✅ | **Model currency + selection** — bumped runtime defaults `claude-sonnet-4-5` → `claude-sonnet-5` (agent, Council, server picker, debate eval); a picked model now drives the **Council roles** too (not just the agent), which it silently ignored before; `Auto` keeps the tuned default + per-turn router. **Done** — see Completed. | A |
| ~~**LLM-2**~~ | ✅ | **Observability seam** — one shared `observability` module: every SDK call (`council._emit`, `agent._run_turn`, librarian) publishes a role-tagged per-call record (usage, request-id, wall-clock latency, temperature, list-price cost estimate) to a pub/sub bus; the shipped consumer is a `CostMeter` that aggregates per **Council run** (→ `run_council` meta `llm`) and per **agent turn** (→ `converse(on_usage=…)` → server `usage` SSE event). **Standalone seam commit** so Filippo rebases onto it and adds his per-round-transcript store as a SECOND subscriber (no edit to the call sites). **Done** — see Completed. | A |
| ~~**LLM-3**~~ | ✅ | Agent temperature — `agent.converse` now pins `temperature_for(model)` when thinking is off (skips for reasoning models / thinking), recorded per turn. Same fix as M-2. **Done** — see Completed. | A |
| ~~**LLM-4**~~ | ✅ | **Compaction trigger on real tokens** — `converse` now decides compaction from `_context_tokens` (the API's exact `count_tokens`, gated behind the char//4 estimate as a cheap pre-filter, with a safe fallback), not the `chars//4` heuristic. **Done** — see Completed. | A |
| **LLM-5** | P3 | Standardize retry config (agent `max_retries=4` vs Council SDK default 2). | A |
| ~~**LLM-6**~~ | ✅ | **A/B sweep cost/latency capture** — `evals/run_ab.py` now meters both arms via `observability.meter()`: each run's `llm` aggregate (tokens, est. USD, wall-time, per-role/model) is written into its `ab_ledger.json` row, summed per-arm into `ab_summary.json` (`_llm_rollup`, lower-bound flagged when a run is unpriced or pre-LLM-6), and shown live in the sweep log (`_cost_tag`). **Done** — see Completed. | A |

## D · Agentic systems

| ID | P | Item | Src |
|----|---|------|-----|
| ~~**SP-1**~~ | ✅ | **Hypothesis lifecycle reflection** — each falsifier design shows its live state (proposed / queued / running / available / failed), derived from the launch queue by semantic match + corpus membership; the re-run is guarded (no re-queue of an in-flight or done design). **Done** — see Completed. | A |
| **SP-1b** | P2 | **Explicit Cellwright write-back** — when the agent *revises or invalidates* a specific Council design (rather than just running it), record that delta on the Hypothesis and surface the Council-vs-Cellwright diff. Needs a session↔hypothesis link + an agent-side write; the SP-1 queue/corpus derivation already covers the "did it run?" half. | A |
| ~~**SP-2**~~ | ✅ core | **Cellwright receptive field** — shipped the host core: `read_raw_series` **extrema-preserving (min–max)** decimation + loss report, a new **`scan_series`** transient/level-shift tool (MAD-prominence + width gate + FDR), and `top_movers` **informative truncation** ("k of N significant dropped"). Verified on real 10k-step trajectories. **Done (core)** — see Completed; remaining pieces → **SP-2b**. | A |
| ~~**SP-2b**~~ | ✅ | **Receptive field — completion** — shipped the **mid-rank stratified sample** (`_reader_worker` → `top_movers.truncation.mid_rank_examples`), **`scan_overview`** (deterministic anomaly map across a design's channels — the numpy map-reduce, no LLM fan-out), and a deterministic **receptive-field eval** (needle recovered / coarse view misses it / null control / mid-rank surfaced). **Done** — see Completed. Agentic remainder → **SP-2c**. | A |
| **SP-2c** | P3 · **▶ ready** | **Receptive field — agentic** — **UNBLOCKED: its only dependency, LLM-2, landed 2026-07-20** (and **LLM-6** already wired the observability meter into the A/B sweep, so the per-call token/cost/latency records this needs are now produced by `evals/run_ab.py`). Build (1) an *agent-graded* run eval (does Cellwright choose to scan + report the needle; NoLiMa paraphrased probe) — needs an agent-tool-use harness beyond the Council-grading `evals/cases.py`; (2) the true **LLM-worker map-reduce** (sub-agents on scan-flagged segments, extractive reduce); and (3) a head-to-head **benchmark of deterministic `scan_overview` vs a full fan-out** — recall, token cost, latency (from the LLM-2 records) — as a paper artifact quantifying *when* fan-out earns its ~15× cost. | A |
| ~~**AG-1**~~ | ✅ | **Launch queue hardened** — absolute config-rooted path (env override, else repo-root — no more CWD-relative stray queue), every read-modify-write serialized through a re-entrant lock (`_txn` / `_LOCK`; `approve_and_run` releases it across the long sim), and atomic `temp + os.replace` writes (no half-written queue, even cross-process). **Done** — see Completed. | A |
| **AG-2** | P2 · *half* | **Tool-selection instrument shipped; consolidation now data-driven.** ✅ The measurement half: `evals/run_ab.py` Arm A now tracks the **tool-selection error rate** (per run + per-arm roll-up: total tool calls, error results, and a per-tool error histogram of which tools the agent mis-selects/mis-calls, via `_tool_rollup`). ⏳ Remaining: the **consolidation** of the 50-tool surface — deliberately data-gated, since the tools have no pure duplicates (7 FBA ops, several read granularities, distinct rigor tools are all genuinely distinct); merge/drop the high-error or never-selected tools **after** running the instrumented sweep, not by blind static guesswork. | A |
| **AG-3** | P3 | Dispatch: explicit unknown-tool guard + semantic input validation test. | A |
| **AG-4** | P3 | `approve_and_run` is synchronous in a request thread with no cancellation — move to a job runner for multi-user. | A |

## E · Frontend: design & UX

| ID | P | Item | Src |
|----|---|------|-----|
| ~~**UX-1**~~ | ✅ | **Accessibility** (WCAG 2.2 AA) — added a polite ARIA live region (status + completion announced during streaming), accessible names on every icon control, a `main` landmark + labeled `dialog`s + skip link, proper `tablist` roles with roving tabindex + arrow-key nav, keyboard-operable recents, a `:focus-visible` ring, and reduced-motion. Verified via the live a11y tree. **Done** — see Completed. | A |
| ~~**D-1**~~ | ✅ | `innerHTML` escaping — hardened `esc()` to also escape quotes (attribute-safe), added a `safe`-tagged auto-escaping template helper, fixed the two genuine unescaped-data sinks (design `genes`, a clear-queue error), and added a **CI lint** (`test_frontend_safety.py`) that fails on any new raw data interpolation into an HTML string. Audit confirmed the named sinks (Council falsifier, corpus rows, queue `from_question`) were already escaped. **Done** — see Completed. | A |
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
| ~~**SCI-1**~~ | ✅ core | **cobrapy → FBA cross-check over iML1515** — shipped `fba_growth`, `fba_gene_knockout`, `fba_flux` (pFBA + loopless FVA), `fba_essentiality_panel` (FBA-vs-Keio MCC + named-diagnostic disagreements). Optional `fba` extra; graceful gating; reproducibility pins (model SHA-256 + solver + medium + objective). Verified: WT growth 0.82 h⁻¹, `fbaA` → `fba_false_viable`, panel MCC 0.75. **Done (core)** — see Completed; remaining → **SCI-1b**. | T + R |
| ~~**SCI-1b**~~ | ✅ | **FBA cross-check — deepening** — shipped **linear MOMA** (GLPK-compatible pre-adaptation comparator; quadratic MOMA still needs a QP solver), the **3-way** join (wcEcoli prior beside FBA + Keio + a "which model catches each Keio-essential" tally), **`fba_synthetic_lethal`** (pairwise double-KO), **`fba_sensitivity`** (±20% medium/NGAM/GAM), and **`fba_qc`** (MEMOTE-lite: energy/biomass-from-nothing + mass balance). **Done** — see Completed. | R |
| ~~**SCI-2**~~ | ✅ core | **Sim-vs-real RNA-seq cross-check** (PRECISE-1K + pydeseq2) — shipped `sci2.py`: the log2FC **concordance engine** (Pearson/Spearman/**Deming**/sign-concordance vs a null baseline + a model-limit verdict), `build_reference` (DESeq2 **unshrunk** LFC on the DATA side only), gating + provenance, and the `rnaseq_concordance` tool. Optional `[rnaseq]` extra; grounded in `wf_eeea2f6c`. **Done (core)** — see Completed; end-to-end → **SCI-2b**. | T |
| ~~**SCI-2b**~~ | ✅ | **RNA-seq cross-check — data side** — fetched PRECISE-1K (17 MB raw counts + metadata, gitignored, SHA-pinned via `fetch_precise1k`), **validated a real DESeq2 run** (`wt_ph5` vs `wt_glc`, MG1655-filtered → 4,345 genes, real acid-stress DE at padj≈0), added the committed **symbol→b-number** map (4,675 genes) wired into `sim_lfc`, + a strain-fidelity filter. **Done** — see Completed. Sim side → **SCI-2c**. | R |
| **SCI-2c** | P3·sci · *sim-run* | **RNA-seq cross-check — live run** — **Ours.** ✅ (1) the **all-gene sim-mRNA reader mode** shipped: `_reader_worker.mode_gene_lfc` (full per-gene seed-mean log2fc, NO significance filter → no range restriction) → `reader.gene_lfc` bridge → `differential.all_gene_lfc` (symbol-annotated) → rewired `sci2.sim_lfc` to the full distribution — see Completed. ⏳ (2) the live end-to-end concordance still needs a Cellarium-matched contrast: a sim campaign we run (`manifest.campaign`) + a gap-filler RNA-seq series we fetch (PRECISE-1K is aerobic-glucose-heavy → anaerobic/N-limitation contrasts need reprocessed series). Guard the compositional trap + short-gene zeros. | R |
| **SCI-3** | future·sci | **Colony-scale via Vivarium** (Agmon 2022; the whole-colony model runs wcEcoli cells as agents) — the vehicle for the growth-dependent, ribosome-limited antibiotic-susceptibility regime the platform surfaced. **Ours** — a future Cellarium integration (a larger scope decision), not a dependency on another workstream. | S |
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

- **LLM-1 · Model currency + selection** (2026-07-14) — updated the stale `claude-sonnet-4-5` default to
  `claude-sonnet-5` across `agent.py`, `council._default_models`, the `server` model picker (label + id), and the
  debate eval. Fixed a real gap: the interface model picker reached the agent but **not** the Council —
  `run_council`/`investigate` called `deliberate()` without `models`, so a picked model was ignored by the
  proposer/skeptic/judge. Now a specific pick drives the Council's roles; `Auto` keeps the Council's tuned default
  and the agent's per-turn router (Opus for Council-framed/hard turns). pytest + ruff green.
- **DS-1 · Slope inference** (2026-07-17) — `fit_relation._ols` now carries `slope_se`, `slope_t`, two-sided
  `slope_p_value`, `slope_ci95`, `slope_ci_excludes_0`, and `adj_r_squared`; the p-value comes from a scipy-free
  regularized incomplete beta (`stats.t_two_sided_p`). A growth "law" is credited only when the slope CI clears 0.
- **M-1 · Falsifier executability + the self-harness** (2026-07-17) — two parts. (1) Made the two tests the
  Council named but couldn't run executable: the `bimodality` tool (Sarle's BC + best 2-cluster split) and the
  DS-1 slope CI. (2) Built a standing **self-harness** (grounded in the wf_f7f85832 SOTA brief: Gorilla structural
  match + LLM-Modulo external critic + gateswell/DGM dev gate): `src/cellarium/test_registry.py` (controlled
  vocabulary of tests → tools, CI-invariant-checked against `TOOLS`) + `src/cellarium/harness.py` (deterministic
  detector + idempotent, human-State-respecting writer into class X). Wired into `run_council` (non-blocking) and
  runnable as a sweep (`harness.audit_store`). On the real stored corpus it filed `GAP-7f48ca3f`: 4 hypotheses
  name Hartigan's dip, which we lack. Follow-up **M-1b** adds a structured falsifier field to catch *novel* gaps.
- **M-1b · Structured falsifier test field** (2026-07-17) — `Falsifier` gained a `NamedTest{test_id, statistic,
  threshold}` (additive; `decision_rule` stays). The Council's `_FALSIFIER` schema builds `test_id`'s enum from
  `test_registry.supported_ids() + ["other"]` and the proposer prompt lists the allowed ids, so the vocabulary
  can't drift from the tools. The harness now has two detectors: the free-text alias scan (known-unsupported,
  legacy-compatible) AND a structural check — `test_id="other"` (the Council itself declaring no listed test fits)
  files a deterministic `unlisted_test` gap, catching a NOVEL test the curated list never knew (verified with a
  Cox/Schoenfeld example). `ui.hypothesis_view` carries the field so the stored-run sweep sees it. pytest + ruff green.
- **UX-1 · Accessibility (WCAG 2.2 AA)** (2026-07-18) — an SPA a11y pass across `apps/web/`. `index.html`: a skip
  link, a polite `#srLive` live region, a `main` landmark + `role="dialog"`/`aria-modal` + labels on the corpus /
  hypothesis / queue / figures overlays, `tablist` semantics (`aria-controls`/`tabpanel`/roving tabindex), and
  accessible names on every icon-only control + the textarea, selects, and search. `app.js`: `announce()` speaks
  status + completion into the live region during streaming (deduped so per-token 'Responding…' isn't spammed), a
  `clickable()` helper makes the recents rows keyboard-operable, arrow-key + Home/End tab navigation, and focus is
  moved into overlays on open and restored to the opener on close. `style.css`: a `.sr-only` utility, a
  `:focus-visible` keyboard ring, and a global `prefers-reduced-motion` block. Verified against the live
  accessibility tree (every control named/roled, no console errors); frontend-only, so CI is unaffected.

## X · Capability gaps (auto-filed by the self-harness)

Written by `src/cellarium/harness.py` on every Council run: a falsifier that names a statistical test with no executable tool (see `test_registry.py`) is filed here for a developer to close. **The harness only creates `open` rows and bumps `Seen`; edit the `State` cell by hand — it is respected and never reopened.** Resolve a gap by either implementing the tool (add its `TestSpec`; the gap then stops recurring) or tightening the proposer so the Council stops naming it (set `State` to `wontfix`). Auto-filed at P3 until a dev triages; `Seen >= 3` earns a `⚑` ready-for-triage flag.

<!-- HARNESS-GAPS:BEGIN (managed by harness.py — edit only the State cell) -->

| ID | State | Seen | Missing capability | Suggested resolution |
|----|-------|------|--------------------|-----------------------|
| `GAP-7f48ca3f` | open | 4× ⚑ | **hartigan_dip** named, no executable tool. We have Sarle's BC (bimodality_bc), not Hartigan's exact dip + bootstrap unimodal null. | implement the tool (Hartigan & Hartigan dip test with a bootstrap null — not implemented.) OR alias to a supported test + tighten the proposer |

<!--gap GAP-7f48ca3f | test=hartigan_dip family=distribution_shape | seen=h_08a5af46a3,h_bf64f76cdb,h_b8808da134,h_f238624d7c | first=2026-07-17 | q= -->
<!-- HARNESS-GAPS:END -->

- **SP-2 (core) · Cellwright receptive field** (2026-07-18) — closed the silent-truncation holes, host-side and
  scipy-free (numpy). (1) `read_raw_series` swapped stride decimation for **min–max** decimation (a transient can
  no longer fall between shown points) + a `view` loss report (`extrema_in_view`, `max_abs_error_vs_full`,
  `detail_between_points` → nudge to scan). (2) New **`scan_series`** tool (`scan.py`) reads the full-resolution
  `raw.seed_channel` and returns an FDR-controlled transient/level-shift event list: robust binned-median baseline
  + MAD-prominence, gated by effect-size + min-width, with a normal-tail p × AR(1) effective-N correction and
  BH-FDR (`stats.bh_qvalues`) — deterministic, no signal-contaminated bootstrap. (3) `top_movers` gained a
  `truncation` block computing "k of N BH-significant movers dropped below the cut" from the worker's counts.
  Tests: `test_scan.py` (min–max preserves a stride-missed spike; transient vs level-shift classification; no
  false positive on clean noise; determinism; truncation block). Verified live on `wildtype/basal` (10,234
  timesteps). Deferred → **SP-2b**. pytest + ruff green.

- **SCI-1 (core) · Independent FBA cross-check over iML1515** (2026-07-18) — a second, genome-scale opinion beside
  the whole-cell sim, from the SOTA brief (`wf_2479258d`). New `src/cellarium/fba.py` (cobrapy over iML1515) +
  four tools: `fba_growth` (FBA), `fba_gene_knockout` (FBA single-deletion via the GPR + Keio-benchmark join +
  named diagnosis), `fba_flux` (pFBA point + loopless FVA range — never a bare internal flux), and
  `fba_essentiality_panel` (FBA-vs-Keio **confusion matrix + MCC**, not accuracy, + the disagreements as
  mechanistic hypotheses). Optional **`fba` extra** (keeps the core scipy-free); every tool degrades to a clear
  message when cobra/model absent; the 11 MB iML1515 SBML is fetched on demand from BiGG (gitignored).
  Reproducibility pinned in `provenance()` (model SHA-256, cobra + solver versions, medium, objective, cutoff).
  Verified live: WT growth 0.82 h⁻¹, `fbaA` → `fba_false_viable` (FBA reroutes through its isozyme; Keio-essential),
  40-gene panel MCC 0.75. Tests: pure logic (diagnosis, MCC) + gating everywhere; real FBA opt-in (skips without
  cobra/model, like `hf`), so CI is unaffected. Deferred → **SCI-1b**. pytest + ruff green.

- **SP-2b · Receptive field completion** (2026-07-18) — finished the deferred SP-2 pieces (host + worker). (1)
  **Mid-rank stratified sample**: `_reader_worker.mode_differential` now returns a stratified `mid_rank_sample` of
  the BH-significant movers dropped below the top-N cut; `differential.top_movers` annotates its symbols and
  `tools.top_movers` folds it into `truncation.mid_rank_examples` — so a real mid-rank mover is visible, not just
  counted. (2) **`scan_overview`** tool: the deterministic map-reduce — full-scans a design's channel panel in one
  call and ranks them by strongest event (no LLM fan-out; verified on `wildtype/basal`). (3) A deterministic
  **receptive-field eval** (`test_receptive_field.py`): a known needle the coarse stride view flattens is recovered
  by min-max decimation + `scan_series`, a clean trajectory yields nothing (null control), and a mid-rank mover is
  surfaced. The agent-in-the-loop graded run + the LLM-worker fan-out are deferred to **SP-2c**. pytest + ruff green.

- **SCI-1b · FBA cross-check deepening** (2026-07-18) — five additions to `fba.py`. (1) **Linear MOMA** (L1
  distance to WT flux) as the pre-adaptation comparator — runs on GLPK (quadratic MOMA needs a QP solver); where
  MOMA also stays viable the reroute is a real isozyme/pathway, not an FBA optimality artifact. (2) The **3-way
  join**: `fba_gene_knockout` + `fba_essentiality_panel` now carry the wcEcoli KO prior beside FBA + Keio (uniformly
  "viable" for metabolic genes — its documented under-prediction) plus a tally of which model catches each
  Keio-essential gene. (3) **`fba_synthetic_lethal`** — pairwise double-KO to find synthetic lethals single-deletion
  misses. (4) **`fba_sensitivity`** — growth (and a gene's essentiality call) under ±20% on medium/NGAM/GAM, so a
  conclusion is only credited if it survives the spread (fbaA growth swings 25.6%). (5) **`fba_qc`** — a MEMOTE-lite
  gate: no ATP/biomass producible with uptakes closed (energy-cycle check) + every internal reaction mass-balanced
  (excluding biomass/demand/sink + the generic polymer residue). All under the optional `fba` extra; real-FBA tests
  skip without cobra so CI is unaffected. pytest + ruff green.
  **Scoping decisions (SCI-1b remainder, 2026-07-18):** (1) **Quadratic (L2) MOMA is NOT pursued** — it needs a
  commercial QP solver (Gurobi/CPLEX + an academic license) for marginal value over the shipped linear (L1) MOMA,
  which agrees with it on the essential/viable call. (2) **MEMOTE is NOT in CI** — nothing MEMOTE runs in the
  pipeline; `fba_qc` is an in-house MEMOTE-*style* subset that runs as a tool + in the local (cobra-present) test
  suite and SKIPS in CI. A full MEMOTE scorecard would be a **separate, opt-in suite/job** (it needs
  cobra+scipy+the 11 MB model, which the main CI deliberately excludes to stay light + scipy-free) — not a change
  to the existing CI gate.

- **M-2 + LLM-3 + M-3 + DS-2 · Reproducibility & honesty bundle** (2026-07-18) — (M-2/LLM-3) sampling temperature
  is pinned instead of the API default: `agent.temperature_for(model, thinking)` returns `CELLARIUM_TEMPERATURE`
  (0.0) for models that accept an explicit temperature with thinking off, and None (omit) for reasoning models
  (opus) or when extended thinking is on (the API forces temp=1 there). Wired into `agent.converse` (both the
  normal + thinking-fallback paths) and `run_council` → `deliberate`, and recorded in the Hypothesis meta + the
  agent session. Anthropic exposes no seed, so temperature is the named variance source. (M-3)
  `provenance._is_in_sample` no longer short-circuits `wildtype` to in-sample — it gates on the condition, so
  `wildtype/acetate` is correctly out-of-sample. (DS-2) `effect_z_vs_corpus` → `z_vs_corpus_spread`, explicitly
  flagged as descriptive positioning, not significance. Tests: `test_provenance.py` + a `temperature_for` unit test,
  no regression across council/hypotheses. pytest + ruff green.

- **SCI-2 (core) · Sim-vs-real RNA-seq cross-check** (2026-07-18) — a second external oracle beside SCI-1, from the
  `wf_eeea2f6c` SOTA brief. New `src/cellarium/sci2.py` — the scientific core is a pure **log2FC concordance
  engine**: join the sim's per-gene log2FC to a DESeq2 reference on b-number, then score Pearson / Spearman /
  **Deming** slope (TLS — both axes noisy) / sign-concordance on the confidently-resolved genes, always against a
  **null baseline** (a high r is nearly free from the shared housekeeping backbone), ending in a model-limit
  verdict (CONCORDANT / DIVERGENT-model-limit / INDETERMINATE). `build_reference` runs **pydeseq2 on the DATA side
  only** (real replicates → NB-GLM Wald, **unshrunk** LFC to match the unshrunk seed-mean sim LFC); the sim side is
  the seed-mean log-ratio (seeds are NOT replicates — never fed to DESeq2, never a p-value). Optional **`rnaseq`
  extra** (pydeseq2); PRECISE-1K (~60 MB) fetched on demand + gitignored; `available()`/`provenance()` gates like
  `fba.py`. Verified: the pure engine on synthetic vectors (concordant → r 0.99, Deming slope ≈1, null ≈0;
  divergent → flagged). Tests: engine + Deming/Spearman + gating everywhere; real pydeseq2/data path is opt-in so
  CI is unaffected. End-to-end (fetch + all-gene sim reader + b-number map) → **SCI-2b**. pytest + ruff green.

- **D-1 · innerHTML escaping invariant** (2026-07-18) — hardened the SPA's XSS surface. `esc()` now escapes quotes
  too (`&quot;`/`&#39;`), closing an attribute-injection gap (a value in `class="…"`/`title="…"` could previously
  break out). Added a `safe`-tagged template helper that auto-escapes every interpolation (the go-forward pattern).
  An audit of the ~200 el()/innerHTML sinks found the named risky ones (the Council falsifier, corpus rows, the
  queue's `from_question`) already `esc()`'d; fixed the two genuine misses (a design's `genes` string, the
  clear-queue error message). Added `test_frontend_safety.py` — a CI lint that scans HTML template strings and
  FAILS on any new unescaped data interpolation (short reviewed allowlist + a not-vacuous meta-test), so the
  invariant is enforced automatically instead of hand-maintained. pytest + ruff green.

- **SCI-2b · RNA-seq cross-check, data side** (2026-07-18) — made the DESeq2 reference REAL. `fetch_precise1k()`
  pulls PRECISE-1K raw counts (17 MB, b-number-indexed) + metadata (gitignored, SHA-pinned); `build_reference`
  gained a strain-fidelity filter (default MG1655) and the correct `wt_glc` reference label. Validated end-to-end
  on a real contrast — `wt_ph5` vs `wt_glc` (19 + 4 MG1655 reps) → 4,345 genes with real acid-stress DE at padj≈0,
  unshrunk log2FC keyed by b-number. Added the committed **symbol→b-number** map (`data/cache/bnumber_map.json`,
  4,675 genes, EcoCyc-derived; pfkA→b3916 matches iML1515) and wired it into `sim_lfc` so the sim side joins the
  reference. Tests: a real-data `build_reference` (skips without the `rnaseq` extra + data, like `realfba`) + the
  b-number map. Remaining (**SCI-2c**): an all-gene sim-mRNA reader mode (worker) for an unbiased concordance, and
  the live run — NB PRECISE-1K's MG1655 contrasts are aerobic/stress, so a clean anaerobic/±AA sim-matched contrast
  needs gap-filler datasets. pytest + ruff green.

- **LLM-2 · Observability seam** (2026-07-20) — one shared instrumentation seam for every Anthropic Messages call
  the platform makes, landed as a **standalone commit** so Filippo's per-round-transcript store can rebase onto it
  and consume the same records. New `src/cellarium/observability.py`: `usage_record(role, model, resp, latency_ms,
  temperature)` builds a per-call dict — `{role, model, request_id, input_tokens, output_tokens, cache_read_tokens,
  cache_creation_tokens, latency_ms, temperature, cost_usd}` — degrading gracefully (no `usage`/`_request_id` → 0/None,
  so a mock never raises). Cost is a **list-price ESTIMATE** (`estimate_cost_usd`, per-model table from the claude-api
  skill, cache-read ×0.1 / cache-write ×1.25, longest-prefix match so date-suffixed ids resolve; unknown model →
  `None`, never a wrong $). A **pub/sub bus** (`subscribe`/`emit`, lock-guarded, faulty-consumer-isolated so a broken
  sink can't break a live call) is the ONE publish point; the shipped consumer is `CostMeter` (`meter()` context
  manager) aggregating tokens / est. USD / wall-time / per-role / per-model, with `cost_partial` when any call used an
  unpriced model. Wired at both real call sites: `council._emit` (role `proposer`/`skeptic`/`judge`/`gate`) + the
  librarian web call, and `agent._run_turn` (role `agent`/`summary`). Surfaced two aggregates: **per Council run** →
  `run_council` meta `llm`; **per agent turn** → `agent.converse(on_usage=…)` → server `usage` SSE event. Tests
  (`test_observability.py`, 9): record shape + graceful degradation, cost math + cache multipliers + prefix/unknown
  pricing, meter scoping/unsubscribe + `cost_partial`, faulty-subscriber isolation, and two integration checks that
  `council._emit` and `agent.converse` actually publish role-tagged records — all offline (no network). **174 passed,
  1 skipped**; ruff green. Filippo hooks his transcript store via `observability.subscribe(fn)` — no edit to the call
  sites (see *Coordinate with Filippo*).

- **SCI-2c (reader mode) · All-gene sim-mRNA reader** (2026-07-20) — the unblocked, our-code half of SCI-2c. The
  sim side of the RNA-seq cross-check previously reused `top_movers`, which returns only the FDR-significant movers
  — so the sim log2FC vector fed to the concordance was **range-restricted**, biasing Pearson/Deming (you can't
  estimate a slope from the tail alone). New **all-gene reader**: `_reader_worker.mode_gene_lfc` computes the
  seed-mean log2FC for EVERY gene above the count floor with no significance filter (pure `_gene_lfc_map` factored
  out; the worker runs only in the model image so it's validated on the opt-in real path); `reader.gene_lfc` bridges
  it (Docker + local, mirroring `differential`); `differential.all_gene_lfc` resolves the design's run roots, calls
  the bridge, and symbol-annotates each id **per kind**; `sci2.sim_lfc` now reads that FULL distribution and keys
  every gene by b-number for the DESeq2 join. **Adversarial review caught a blocker** the mocked test missed: the
  mRNA path was annotating **cistron_ids** (`EG10016_RNA[c]`) with the **monomer**-keyed `_reverse_gene_map`, so
  every symbol resolved to None → the b-number join was empty → the concordance silently returned INDETERMINATE for
  every real run. Fixed: annotate mRNA via a **cistron→symbol map** (`_cistron_symbol_map`, dumped from `gene_data`
  by the worker's gene-map mode, now emitting `cistron_symbols`) and protein via the monomer map (parity with
  `top_movers`); `rnaseq_concordance` now **fails loud** on a namespace mismatch (both sides sizable, zero joined)
  instead of a silent INDETERMINATE; regression test feeds realistic cistron ids through the per-kind annotation +
  the b-number join. Host-side tests (worker is container-only): per-kind annotation, `sim_lfc` full-distribution
  join + graceful empty, and the namespace diagnostic. **Caveat:** the mRNA join needs `data/cache/cistron_map.json`
  generated in the model image (lazily dumped via `reader.gene_map`) — bundled with the live run, and now
  surfaced loudly if absent rather than silently degrading. The live end-to-end run stays open (**SCI-2c** part 2)
  — it needs a matched-contrast sim campaign we run + a gap-filler RNA-seq series, both ours to produce. pytest +
  ruff green.

- **AG-1 · Launch-queue hardening** (2026-07-20) — the launch airlock's queue was a lock-free JSON read-modify-write
  at a CWD-relative path. Three fixes in `launch.py`: (1) the path is now **absolute + config-rooted**
  (`CELLARIUM_QUEUE` env override, else the repo root derived from `__file__`) — a job proposed from a script run in
  another directory used to write a stray queue the server never saw; (2) every mutation goes through a re-entrant
  **`_LOCK`** (`_txn` context manager for single-step mutators; `revise` holds it across its multi-step flow;
  `approve_and_run` claims the job under the lock, **releases it across the minutes-long sim**, then re-acquires to
  write the terminal status — so a long run never blocks propose/list/stamp on other server threads); (3) `_save`
  writes **atomically** (`temp + os.replace`), so a crash mid-write — or a stray second process — can never leave a
  half-written queue (worst case last-writer-wins, never corruption), and reads stay lock-free (os.replace means a
  reader always sees a complete file). Tests: absolute-path assertion, a 40-thread concurrent-append race that lands
  all 40 (a lost-update race would drop some), and the atomic-write/no-leftover-temp check. The single-writer server
  process makes an OS file-lock unnecessary — noted for the SQLite path if multi-process writing ever becomes real.
  pytest + ruff green.

- **AG-2 (measurement) · Tool-selection error rate** (2026-07-20) — shipped the instrument that makes tool
  consolidation data-driven instead of guesswork. `evals/run_ab.py` Arm A now records, per run, every tool call and
  how many returned an `{"error": ...}` result (unknown tool / bad args / tool-level failure): `tool_calls`,
  `tool_errors`, `tool_error_rate`, and `errored_tools` (a per-tool histogram). `_tool_rollup` sums these across the
  sweep into `ab_summary.json` (`arm_a_cellwright.tools`) — the ranked list of which of the 50 tools the agent
  mis-selects most — and the sweep log prints the rate + top mis-selected tools live. The **consolidation** half of
  AG-2 stays open on purpose: the surface has no pure duplicates (the FBA/reader/rigor clusters are all genuinely
  distinct), so merging should follow the instrumented sweep's data (high-error or never-selected tools), not a
  static guess made without the ability to validate. Pure `_tool_rollup` smoke-tested; ruff green; eval harness not
  in the pytest suite so CI is unaffected.

- **LLM-4 · Compaction trigger on real tokens** (2026-07-20) — the mid-conversation compaction decision no longer
  rides on the `chars//4` heuristic (which mis-sizes JSON tool results). `converse` now calls `_context_tokens`,
  which keeps `_estimate_tokens` as a **cheap pre-filter** — only when the whole-prompt estimate is within ~25% of
  `_COMPACT_TRIGGER` does it spend the API's exact `count_tokens` (system + tools + full history; cache markers add
  no tokens), and any `count_tokens` failure (offline / mock / transient) **falls back to the estimate so a turn is
  never blocked**. The pre-filter folds in the fixed **system+tools overhead** (`_prompt_overhead_est`, ~11k tokens)
  that `_estimate_tokens(messages)` omits — caught in adversarial review; without it the trigger fired ~overhead
  late (real ~29k vs nominal 24k). `_COMPACT_TRIGGER` (24k) is now compared against a real token count, so it means real tokens, not
  proxy-tokens — and `count_tokens` is only paid near the threshold, never on a short turn. Test
  (`test_context_tokens_prefilters_then_counts_exact`): below-band skips the call, above-band uses the exact count,
  and a raising client falls back. Note LLM-2's `resp.usage` already logs the real observed input per call as a free
  cross-check. pytest + ruff green.

- **LLM-6 · A/B sweep cost/latency capture** (2026-07-20) — the first consumer of the LLM-2 seam beyond the app.
  `evals/run_ab.py` runs the billable Council-vs-Cellwright sweep (~25 cases × 2 arms × many model calls) but
  recorded no spend. Now each arm's model calls are scoped in `observability.meter()` — Arm B around
  `council.deliberate`, Arm A around `agent.converse` — and the meter's `summary()` (tokens, est. USD, wall-time,
  per-role/model) is written into that run's `ab_ledger.json` row. `_llm_rollup` sums each arm's runs into
  `ab_summary.json` (`arm_b_council.llm` / `arm_a_cellwright.llm`), setting `cost_partial` when any run was
  unpriced **or** predates LLM-6 (a resumed ledger row with no telemetry), so the total reads as a lower bound not
  a false exact figure; `_cost_tag` shows per-run and per-arm spend live in the sweep log. Additive to the ledger
  schema (older rows without `llm` are handled), so a resumed sweep doesn't break. Pure helpers (`_cost_tag`,
  `_llm_rollup`) smoke-tested; ruff green. The eval harness isn't in the pytest suite (operational tooling, like the
  rest of `evals/`), so CI is unaffected. This makes the SP-2c fan-out-vs-deterministic benchmark measurable — it's
  the same per-call token/latency records that benchmark needs.

## Design notes (scouted plans)

Distilled from the SOTA+pitfalls lit briefs (`wf_2479258d`, full text in that workflow's transcript). These are
the agreed approach + guardrails for the two open P1s; edit as we build.

### SP-2 · Cellwright receptive field

**Core (this pass — host-only, scipy-free numpy):**
1. `read_raw_series`: replace stride decimation with **min–max (LTTB) decimation** so extrema/change-points always
   survive into `series`, plus a **loss report** (`peak_flattened`, `extrema_in_view`, `max_abs_error_vs_full`).
2. New `scan_series` tool over full-resolution `raw.seed_channel`: robust **MAD-prominence** transient detection +
   **level-shift** classification (returns-to-baseline test), gated by **effect-size (MAD) + min-width**, with a
   **block-bootstrap-calibrated p** (fixed seed → deterministic) and **BH-FDR** across events.
3. `top_movers` **truncation block**: host-computed from `n_significant_fdr10` + shown `q`s — "k of N significant
   shown, m below the cut" + a raise-`top`/filter hint (kills the silent drop).
4. Receptive-field **test**: inject a stride-hidden spike → assert `scan_series` + min–max catch it and the old
   stride view misses it.

**Deferred (SP-2b):** mid-rank stratified sample in `top_movers` (needs a `_reader_worker` edit); `evals/cases.py`
integration with NoLiMa-style *paraphrased* probes + a **null control**; the **gated map-reduce** — the numpy scan
pre-filters, LLM workers fan out **only** to flagged segments (cap K), reduce stays **extractive** (set-union +
dedup + provenance, never abstractive).

**Pitfalls guarded:** FP control via effect-size+width+block-bootstrap+BH-FDR (trajectories are autocorrelated →
detrend + deterministic seed); binary-seg is greedy, not "optimal"; extractive (not abstractive) reduce or the
mid-rank item dies; fan-out gated on the scan (multi-agent ≈ 15× tokens).

### SCI-1 · Independent FBA cross-check

**Build:** four cobrapy wrappers over **iML1515** — `fba_growth` (FBA), `fba_flux` (pFBA + **loopless FVA** on
demand), `fba_gene_knockout` (**FBA + MOMA** side by side), `fba_essentiality_panel` (FBA+MOMA over the 402-gene
set; essential if growth < 1–5% WT). MOMA is the honest comparator — wcEcoli's homeostatic FBA can't re-route to a
distant optimum either.

**Reproducibility (load-bearing):** BiGG iML1515 SBML (fbc2); log model **SHA-256 + cobrapy + solver + tolerance +
medium + objective**; assert `BIOMASS_Ec_iML1515_core_75p37M` + sanity growth ≈ 0.88 h⁻¹ on M9-glucose set via
`model.medium`; ship a **MEMOTE** report in CI.

**Three-way router:** wcEcoli vs FBA vs Keio → each disagreement cell → a **named diagnostic** (kinetic cap /
cofactor cross-feeding / OR-isozyme / Keio assay artifact). Report **MCC / PR-AUC + confusion matrix**, never raw
accuracy (set is ~90% non-essential).

**Compute + deps:** CPU-only LP/QP — growth ~10–50 ms, panel ~seconds (FBA) to ~1–3 min (MOMA), FVA on demand; **no
Docker/GPU**. Behind an optional **`fba` extra** (cobrapy pulls scipy/pandas/optlang + a solver) to keep the core
scipy-free.

**Pitfalls guarded:** alternate optima → FVA + pFBA (never a single internal flux); thermodynamic loops →
`add_loopless` (an FVA bound at the ±1000 cap = loops missing); biomass/GAM/NGAM/medium sensitivity (±20% test);
GPR AND/OR via `single_gene_deletion` (not hand-toggled bounds); single- vs double-deletion; solver/model-version
determinism near the essentiality cutoff; **never claim FBA as ground truth** — curation dominates method choice.

## Coordinate with Filippo (separate workstream)
Filippo's Council-defect ledger (`docs/COUNCIL_IMPROVEMENT_LEDGER.md` + `docs/council_issues.yaml`, branch
`operationalization-debate`) covers D1–D6. Touch points with this backlog, to reconcile when his branch merges:
- **M-1** (falsifier *executability*) ⟷ his **D1/D2** (falsifier *logical consistency*) — two halves of one
  falsifier-quality effort.
- **LLM-2** (observability) ⟷ his **method gap** (the Council's per-round transcript isn't persisted; `ablation.json`
  keeps only counts) — persisting transcripts enables systematic Council analysis and measuring M-1.
  **✅ LANDED on main as a standalone seam** (`src/cellarium/observability.py`): every SDK call (`council._emit`,
  `agent._run_turn`, librarian) `emit()`s a per-call record to a pub/sub bus. The record shape (the contract —
  additions must be backward-additive):
  `{role, model, request_id, input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens, latency_ms,
  temperature, cost_usd}`.
  **For Filippo:** `git rebase origin/main` (you're docs-only, zero code overlap with the seam files), then add
  your per-round transcript store as a SECOND consumer — `observability.subscribe(fn)` where `fn(record)` writes
  `{tokens, request_id, latency}` next to each round's messages. You do NOT touch `council._emit` / `agent._run_turn`
  — one publish point, two subscribers. **Join key: `request_id`** (unique per call). `role` is
  `proposer`/`skeptic`/`judge`/`gate` but REPEATS across the up-to-4 rounds, so role alone collides — match each
  record to the exact call you stored by `request_id` (records also arrive in call order within a subscription
  scope if you need sequencing). The shipped consumer is `CostMeter` (`meter()` context manager); mirror it.

  **Scope boundary (be aware):** the record is **metadata-only** — tokens/ids/latency/cost, NO message content and
  NO round index. So "no call-site edit" is fully true for the **cost/latency sidecar**, but the *transcript
  content* (your actual method gap) comes from elsewhere: cheapest is to persist what `deliberate`'s existing
  `on_round(...)` callback already emits per round (`{round, proposer:{claim,h1,h0}, skeptic:[objections],
  judge:{verdict}}` — already streamed + stored by `run_council` via `store.append_round`, zero new instrumentation);
  raw message-level transcripts (exact system+payload+tool response per call) live inside `_emit` and would need a
  small capture hook there. Also note `_emit` retries up to 2× on a degenerate emit and publishes a record EACH
  attempt — so one round's proposer can yield two records with the same `role`, distinguished only by `request_id`.

  **Two paths to attribute a record to its round** (pick per how much of `deliberate` you're already editing):
  1. **Scope-based (recommended — no id juggling):** open a nested `with observability.meter() as m:` around each
     round's calls inside `deliberate`'s loop. Fan-out means that per-round meter captures *exactly* that round's
     2–3 calls, so `m.summary()` IS the round's cost/latency directly — no `request_id` correlation needed. Cost:
     one tiny edit inside the loop (your territory, since you're editing `deliberate` for the transcript anyway).
  2. **Pure-subscribe (no edit to `deliberate`):** subscribe globally and join records to rounds by `request_id`.
     The bus doesn't tag records with a round, so you need the round↔`request_id` map from somewhere — thread
     `resp._request_id` into the `on_round` payload (one line in `deliberate`), or read `resp._request_id` at your
     own content-capture point so both sides share the id. Do NOT rely on call **ordering** to infer round
     membership: it holds only on the full-system happy path and breaks under ablations (skeptic/judge off) or a D3
     `continue` (re-propose). `request_id`, not position, is the robust correlator.

## Provenance
This backlog replaced three task docs, now **removed** (recoverable from git history at commit `55ed67f`):
`POST_HACKATHON_AUDIT.md` (the file:line audit evidence), `POST_HACKATHON_TODO.md` (deferred work), and
`docs/AUDIT.md` (the 2026-07-10 harness audit). `docs/ROADMAP.md` is **kept** as cited design-history — it is
referenced by `docs/SOCRATIC_COUNCIL.md` and the code, not a task source; its open items (M-8/M-9/H-6/SCI-1/4/5)
now live here.
