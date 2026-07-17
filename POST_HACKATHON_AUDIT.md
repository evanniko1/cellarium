<!-- Author: audit pass 2026-07-14. -->
> ⚠️ **Deprecated as a task source — live tasks are in [BACKLOG.md](BACKLOG.md).** This file is retained as the detailed file:line **evidence-of-record** behind the backlog's `M-`/`DS-`/`LLM-`/`AG-`/`D-`/`UX-`/`H-`/`SP-` findings.

# Cellarium — post-hackathon audit (methodology · data science · LLM · agentic · design · UX)

**Scope.** Read: `src/cellarium/*` (31 modules, 6.5k LOC), `evals/*` (the benchmark suite + specs), `apps/server.py`
+ `apps/web/{app.js,style.css}` (the SPA), `tests/*` (19 files, 119 test fns), and `POST_HACKATHON_TODO.md`.
Every finding cites a file:line. Severity: **P0** correctness/safety/security that breaks a core claim · **P1** rigor
gap to close before publication/open-source · **P2** robustness/quality · **P3** polish.

**Overall.** This is a high-quality, unusually rigorous codebase — the blindness quarantine, the Popperian Council,
the no-scipy Student-t statistics, the FDR-gated differentials, and the human-approval airlock are all genuinely
well-built and, in the case of blindness, *tested at the payload level*. There are **no P0s**. The findings are
about hardening for the "publication + open-source, rigor non-negotiable" bar, not fundamental flaws. The single
biggest theme: **the methodology promises statistics and reproducibility the runtime doesn't fully deliver yet**
(a decision-rule↔tooling gap, unset temperature, lagging model defaults, and — most glaring — no CI to prove the
119 tests are green).

---

## 1. Methodology

**Strong.** The blindness quarantine is enforced at the module boundary (`instrument.py` imports no result-bearing
module — no `survey`/`differential`/`store`) *and* asserted at the payload level: `tests/test_blindness.py` captures
the actual dicts sent to each role-LLM and asserts no reference answer and no numeric reading leaks (incl. the
debate digest and the librarian). Popperian rubric with a quota-of-doubt, convergence guards, a per-objection
ledger, and best-candidate-not-last selection (`council.py:608-754`). Provenance in/out-of-sample guard
(`provenance.py`). Literature-grounded eval with verified citations (`evals/EVAL_SPEC.md`).

| ID | Sev | Finding | File | Fix |
|----|-----|---------|------|-----|
| M-1 | **P1** | **Decision-rule ↔ tooling gap.** The Council's rubric prescribes tests the grounded agent can't run: `dip test for bimodality` (`council.py:74,148`) has **no implementation anywhere** (grep finds it only in prompts), and the example `slope 95% CI excludes 0` (`council.py:73`) can't be executed — `fit_relation` returns slope/R² but **no slope CI/p** (`rigor.py:171`). A hypothesis can pass pre-registration with a decision rule Cellwright then cannot test → the pre-register→test loop silently breaks for distribution-shape and slope claims. | `council.py`, `rigor.py` | Add a bimodality tool (Hartigan dip or 2-component mixture) and a slope SE/CI/p to `fit_relation`; **or** constrain the rubric's decision-rule vocabulary to executable tests. |
| M-2 | P2 | **Council is non-reproducible.** Roles run at API-default temperature (`temperature=None`, `council.py:265`); only the sufficiency gate pins `0`. A rigor-first instrument whose outputs flip run-to-run undercuts its own claim. | `council.py:264`, `deliberate()` | Pin a default temperature (or seed) for the platform Council and record it in the `Hypothesis` provenance. |
| M-3 | P2 | **Provenance mis-tag for wildtype.** `_is_in_sample` returns `True` for `perturbation=="wildtype"` **regardless of condition** (`provenance.py:28`), so `wildtype/<non-fitted condition>` would be over-credited as in-sample. | `provenance.py:28` | Gate wildtype on `condition ∈ IN_SAMPLE_CONDITIONS` too; add a test. |
| M-4 | P3 | In-sample condition set is a hardcoded 6-item list (`provenance.py:18`), acknowledged coarse. | `provenance.py:18` | Add a test tying it to the actual ParCa fit set so it can't silently drift. |

## 2. Data science / statistics

**Strong.** scipy-free Student-t CI — exact table for df≤30, Cornish-Fisher above (`stats.py`), fixing a real prior
bug (a silent 1.96·SE fallback that understated every CI at n=4–8). Welch's t in `disconfirm` (`rigor.py:90`).
**Benjamini–Hochberg FDR (q≤0.10) over ~thousands of species** in `top_movers` (`_reader_worker.py:692`,
`tools.py:787`) — proper multiple-comparisons control. Provenance-aware OLS with an in/out-of-sample split
(`rigor.fit_relation`) — the honest predictive test. Session-level coverage tracking (`rigor.coverage`).

| ID | Sev | Finding | File | Fix |
|----|-----|---------|------|-----|
| DS-1 | **P1** | The growth-law tool `fit_relation` reports slope/intercept/R²/pearson_r with **no inference on the slope** (no SE, CI, or p) and no adjusted R²; asserting a "law" from R² alone at small n (designs, often <10 points) is optimistically biased. (Overlaps M-1.) | `rigor.py:156-182` | Add t-based slope SE/CI (`stats.py` already has the t-table) + adjusted R²; report n. |
| DS-2 | P2 | `effect_z_vs_corpus` uses the population SD of **all design means** as the noise yardstick (`rigor.py:96`), conflating between-design biological variation with replicate noise — it can mislabel a real effect "typical". It's an aid, not the test (Welch-t is), but ensure the agent prompt treats it that way. | `rigor.py:95-106` | Keep, but rename/annotate as "vs corpus spread" and never as significance. |
| DS-3 | P3 | Channel-level `differential.summary` ranks ~11 channels+pathways by \|log2fc\| with no per-channel significance (only species-level `top_movers` has FDR). Acceptable at 11, but a small channel shift can be over-read. | `differential.py:51` | Attach the `disconfirm` Welch-t (or a note) to the top channel movers. |
| DS-4 | P3 | No unit test pins `t_critical_95` values (table + the Cornish-Fisher branch claimed to hit df=60→2.000). | `stats.py:25` | Add a table + CF regression test. |

## 3. LLM engineering

**Strong.** Prompt caching across three breakpoints (system, tools, incremental conversation prefix — `agent.py`
`_system_blocks`/`_cached_tools`/`_prefix_cached`; Council caches system+schema in `_emit`). Context compaction at
turn boundaries with an LLM summary and a no-LLM fallback (`compact_history`). Streamed token deltas; extended-
thinking budget with graceful fallback; SDK retries; tool-result truncation; a forced final synthesis when the tool
budget is spent (`agent.py:393`, fixing ~1/3 truncated Arm-A sessions); an input-field whitelist that stops re-sent
assistant blocks 400-ing (`_INPUT_FIELDS`).

| ID | Sev | Finding | File | Fix |
|----|-----|---------|------|-----|
| LLM-1 | **P1** | **Model currency + claim consistency.** Runtime defaults lag a generation: `agent.py:16` and the Council default to `claude-sonnet-4-5`, while the eval harness defaults to `claude-sonnet-5` (`grade.py:15,174`) and the server default is `"auto"` (`server.py:52`). So a fresh clone reasons on Sonnet 4.5 — **not** the "Opus 4.8" the submission states, and behind the model the benchmarks were validated on. | `agent.py:16`, `council.py:258`, `server.py:45-52` | Bump runtime defaults to the current gen; audit what `"auto"` routes to (`test_routing.py`); make the external claim precise. |
| LLM-2 | P2 | **No observability.** `converse()`/`_emit()` capture no token usage, cost, or latency, and emit no request IDs or structured logs — no way to attribute spend in a cost-sensitive research setting. | `agent.py:311-411` | Log `resp.usage`, add request IDs and a cost meter. |
| LLM-3 | P2 | Agent reasoning is non-deterministic (temperature unset), same root as M-2 — a "rigorous mode" should pin it. | `agent.py:354-363` | Offer temperature=0 (or a recorded seed) for the grounded agent. |
| LLM-4 | P3 | `_estimate_tokens` is `chars//4` (`agent.py:221`) driving the 24k compaction trigger — a bulky tool_result can mis-count. | `agent.py:221` | Use last `resp.usage.input_tokens` (or `count_tokens`) for the trigger. |
| LLM-5 | P3 | Retry config differs: agent `max_retries=4`, Council `deliberate()` uses the SDK default (2). | `agent.py:341`, `council.py:621` | Standardize. |

## 4. Agentic AI

**Strong.** The human-approval airlock is real and well-modelled: `approve_and_run` is **not** an agent tool
(`launch.py:193`); safety-blocked designs refuse to run without a manual queue edit; a gene KO with no resolvable
index is **refused, not silently mis-run** (`launch._resolve_ko`); HF downloads and new sims are both gated
(`agent.py` system rules). Orphaned-job reconciliation on boot via the manifest (`launch.reconcile`). Epistemic
steps (coverage, disconfirm) are callable tools, not just prompt wishes.

| ID | Sev | Finding | File | Fix |
|----|-----|---------|------|-----|
| AG-1 | P2 | **Launch queue is a lock-free JSON read-modify-write** at a relative path (`launch.py:18`, `_load`/`_save`). `approve_and_run` runs in a server thread while the agent can `propose` concurrently → last-write-wins can drop a job or a status transition. | `launch.py:18-27` | File lock (or move the queue into the existing SQLite store); use an absolute, config-rooted path. |
| AG-2 | P2 | **38 tools + a ~4 KB policy prompt** hand-encoding tool selection (`agent.py:18-126`). Large surface → selection errors + maintenance load (the prompt is doing a router's job). | `agent.py`, `tools.py` | Consolidate overlapping tools (survey/list_results/coverage; vet/check_feasibility/screen_design) and/or add a light tool-router; track tool-selection error rate in the eval. |
| AG-3 | P3 | `dispatch(name, input)` — add an explicit unknown-tool-name guard and confirm each tool degrades gracefully on a bad design label (most already return `{"error":…}`). | `agent.py:382`, `tools.py` | Guard + a dispatch test. |
| AG-4 | P3 | `approve_and_run` runs the sim synchronously in a request thread with no cancellation — fine single-user, a blocker for multi-user. | `launch.py:193-221` | Note; move to a job runner if multi-user. |

## 5. Design (frontend)

**Strong.** A hand-built glass-box SPA (the "not bare Streamlit" bar the project set), a real CSS-variable design
system, and `prefers-reduced-motion` respected (2×). Escaping discipline in the **hot paths is correct**:
`inlineMd()` calls `esc()` before any formatting (`app.js:19-23`), so streamed model output and titles cannot inject
HTML.

| ID | Sev | Finding | File | Fix |
|----|-----|---------|------|-----|
| D-1 | P2 | **Fragile escaping invariant across 37 `innerHTML` sinks.** The two hottest paths escape correctly, but `el(tag,cls,html)` sets `innerHTML` straight from its arg (`app.js:5`) and several `innerHTML =` template strings interpolate dynamic content; correctness relies on **every caller** remembering `esc()`. Audit the dynamic sinks that carry model/corpus text (Council claims/objections `app.js:656`, corpus rows, queue `from_question`). | `apps/web/app.js` | One safe render helper + sweep the dynamic sinks; add a lint rule against raw `innerHTML =` with interpolation. |
| D-2 | P3 | No dark mode in the app (`prefers-color-scheme` = 0 in app.js/style.css) though the published report is theme-aware — inconsistent with the design bar. | `apps/web/style.css` | Add a theme, or state single-theme intent. |
| D-3 | P3 | Monolithic 1447-line `app.js` / 593-line CSS, no component structure — fine now, note for scaling. | `apps/web/*` | Split when it grows. |

## 6. User experience

**Strong.** Token-streamed answers, a glass-box tool trace, a Council drawer streaming rounds live, an approval
airlock with provenance click-back, a corpus browser, read-only backfilled sessions, and errors surfaced as JSON
rather than 500s (`server.py` wraps every endpoint in try/except).

| ID | Sev | Finding | File | Fix |
|----|-----|---------|------|-----|
| UX-1 | **P1** | **Accessibility is largely absent.** Across app.js + style.css: `role`=0, `alt`=0, `tabindex`=0, `aria-label`=0, `aria-live`=0 (`aria-` appears only 3×). No live region → a screen reader never announces the streamed answer; custom controls are unlabeled; keyboard operability and focus-visible are unaudited. For a tool aimed at publication + broad scientific use this is a real WCAG 2.2 AA gap. | `apps/web/*` | Live region for streaming, labels/roles on controls, keyboard nav, a focus-visible pass. |
| UX-2 | P2 | Loading/empty/error affordances are ad-hoc; `aria-busy`=0. Long ops (`download_raw`, sim runs) need determinate progress (the note channel helps) and a retry on failure, not a dead state. | `apps/web/app.js` | Standardize loading/empty/error/retry states. |
| UX-3 | P3 | No frontend tests — 1447 lines of app.js ship unguarded (a broken stream handler or `innerHTML` change regresses silently). | — | Add a minimal Playwright/DOM smoke test. |

## 7. Cross-cutting engineering hygiene

| ID | Sev | Finding | Evidence | Fix |
|----|-----|---------|----------|-----|
| H-1 | **P1** | **No CI.** 119 test functions exist but nothing runs them on push (no `.github/workflows`). A rigor-first, soon-to-be-open-source project can't have its methodology tests unenforced. | no `.github/workflows` | GitHub Actions: `pytest` + `ruff` + `mypy` on PR. |
| H-2 | P2 | No `[tool.ruff]`/`[tool.mypy]`/`[tool.pytest]` config in `pyproject.toml`; no static analysis. | `pyproject.toml` | Add lint/type/test config. |
| H-3 | P2 | Dependencies are `>=` floors with no lockfile — non-reproducible for a reproducibility-focused artifact. | `pyproject.toml:9-21` | Pin + lock (uv/pip-tools); record model+temp+seed per run. |
| H-4 | P3 | No hardcoded secrets (good — the one hit is a docstring example, `run_ab.py:169`). | — | Add a secret-scan to CI to keep it that way. |
| H-5 | P3 | A `package-lock.json` exists for a no-build vanilla-JS app. | repo root | Reconcile or remove. |

## 8. On the TODOs (`POST_HACKATHON_TODO.md`)

Well-scoped and honest. The **cobrapy → FBA tool-wrappers** item is correctly identified as the top scientific
unlock — an *independent* genome-scale essentiality cross-check is how "the model is wrong here" becomes grounded
rather than a hunch, and it directly serves the publication's model-limits thesis. The Council-librarian rewire and
the experimental-design DOE for falsifier panels are solid follow-ons. This audit **adds** items the TODO doesn't
cover: **M-1/DS-1** (the decision-rule↔tooling stat-execution gap), **H-1** (CI), **LLM-1** (model currency vs the
external claim), **M-2/LLM-3/H-3** (reproducibility: temperature, seed, model + dep pinning), **UX-1** (a11y),
**AG-1** (queue concurrency), and **LLM-2** (observability).

## 9. Prioritized backlog

**P1 — before publication / open-source:**
1. **SP-1** Close the Hypothesis lifecycle loop (stale suggestions + no run-status write-back) — see §10.
2. **SP-2** Prove/expand Cellwright's receptive field over large trajectories — see §10.
3. **H-1** Stand up CI (pytest + ruff + mypy) — make the 119 tests enforce the rigor they encode.
4. **M-1 / DS-1** Close the decision-rule↔tooling gap: add a bimodality test + slope CI/p, or constrain the rubric.
5. **LLM-1** Reconcile model defaults with the current generation and the "Opus 4.8" claim; audit `auto` routing.
6. **UX-1** Accessibility pass (live region for streaming, labels/roles, keyboard, focus).

**P2 — soon:** M-2/LLM-3 (pin temperature/seed), M-3 (wildtype provenance), AG-1 (queue lock), AG-2 (tool surface),
LLM-2 (observability), D-1 (innerHTML sweep), UX-2 (loading/error states), H-2/H-3 (lint + dep pinning).

**P3 — polish:** DS-2/3/4, LLM-4/5, AG-3/4, D-2/3, UX-3, H-4/5, M-4.

---

## 10. Second-pass findings (loop-closure + receptive field)

Two gaps raised in review and confirmed against the code. Both are **P1**.

### SP-1 — The Hypothesis is write-once; its test lifecycle is never reflected back **(P1, agentic + UX + provenance)**

**Confirmed.** A `Hypothesis` persists the Council's `candidate_designs` a single time (`hypothesis.py:61`). The
interface renders them as clickable "propose to the airlock" drafts, defaulting to the Council-proposed scale
(`app.js:661,711-719`), and a queue-from-hypothesis resolves the panel from the *persisted* run
(`server.py:396-403`). Queued jobs carry a **forward** provenance stamp back to the run (`launch.stamp_provenance`
with `hyp_id`, `server.py:384,403`) — but there is **no reverse write-back onto the Hypothesis**:

- When the transcript + suggestions are handed to Cellwright and it **invalidates or re-parameterizes** a design,
  that edit lives only in the chat session and the launch queue (`revise_experiment`/`propose_experiment`) — the
  Hypothesis still shows, and keeps one-click-runnable, the *original* Council suggestions.
- When a queued falsifier is **approved and runs**, `approve_and_run` flips the **queue** status to `done` and
  records the shard (`launch.py:207-221`); the Hypothesis is never told, so it can never render "tested — data
  available" or link to the resulting run.

**Consequence.** The pre-register → test → conclude loop the platform exists to make visible is not closed: a
Hypothesis shows stale, possibly-invalidated suggestions indefinitely, a user can re-queue a design the reasoning
already rejected (wasted compute on a discounted run), and a fully-tested Hypothesis looks untested.

**Address.** Make the Hypothesis a living record. (1) Give each `candidate_design` a status
(`proposed → altered_by_cellwright | invalidated | queued:req_id → running → done:shard`) plus back-references to
the queue job(s) and the session that touched it. (2) On a Cellwright `revise`/`invalidate`, write the delta back
onto the Hypothesis (the session already knows `hyp_id`). (3) Join queue status → Hypothesis at render time (the
forward `hyp_id` link already exists — add the reverse read); disable clicking a stale/invalidated suggestion and
show "tested · data available" with a link. (4) Surface the Council-vs-Cellwright design delta (what changed, and
why) in the Hypothesis view. This is the honest version of "a pre-registration that actually gets tested."

### SP-2 — Cellwright's receptive field over the raw trajectories may be too small **(P1, methodology + data science + agentic)**

**Confirmed.** Cellwright reasons over lossy projections of the simulation, not the raw state: `read_series`
returns a ~16-point coarse manifest trajectory (`agent.py` system rules), `top_movers` returns the FDR-significant
**top-N (default 12)**, and **every tool result is hard-truncated at 6000 chars** before re-entering context
(`agent.py:204` `_TOOL_CAP`, applied at `:388-389`). The raw state is ~12k species × every timestep × many seeds,
so the receptive field is a small, summary-shaped sample. Signal that lives *between* the 16 points (a transient
spike), *below* the top-N (a mid-ranked mover), or *past* the 6000-char cut is invisible — and the agent cannot
know what it did not see, so a "nothing else moved" conclusion is only as good as the projection. Grounding
fidelity is the platform's core claim, so the receptive field must be *shown* adequate, not assumed.

**Address.** (a) **Make truncation informative** — every summarizing tool reports what it dropped ("12 of N
significant; k of T timepoints; result truncated at X of Y bytes") so the agent knows its blind spot and can drill.
(b) **Add full-scan sufficient-statistic / anomaly tools** — change-point and peak detection over *all* timesteps,
a whole-proteome move-count (not just top-N) — so nothing large is silently unsampled. (c) For genuinely large
reads, **fan out to sub-agents over chunks** (seeds / species-blocks / time-windows) that each summarize, then
aggregate — a map-reduce over the trajectory — instead of truncating. (d) **Literature pass warranted before
building**: hierarchical/recursive and map-reduce summarization, retrieval over chunked large arrays, multi-agent
long-context reading (sub-agent fan-out), change-point/anomaly detection for scientific time series, and how
genomics / single-cell foundation-model agents handle comparably large state. (e) Add a **receptive-field eval**:
inject a known transient and a known mid-rank mover; verify Cellwright surfaces them. This overlaps but is distinct
from `rigor.coverage` (which tracks *which designs* were deep-read, not *how much of a design* was actually seen).
