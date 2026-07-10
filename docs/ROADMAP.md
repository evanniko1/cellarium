# Cellarium roadmap — rigorous result-scanning + guardrails

Task tracker for the analytical harness. **Why:** Coli reads simulation results, and without structure it
anchors on the first salient run (primacy / lost-in-the-middle, Liu 2023) and confirms the conversational
trace (confirmation bias, O'Leary 2025). Anchoring is *not* fixable by prompting — chain-of-thought and
reflection are insufficient (Lou 2024); the fix is **structural**: comprehensive, computed, ranked input +
quarantined priors. The two design invariants:

1. **Move the "what's notable?" judgment out of the LLM's biased attention into deterministic computation.**
2. **Quarantine the priors** — the answer key (`CORPUS_OBSERVATIONS.md`) and prior chat are judge-only, never
   in the analyst's context.

Status: `[ ]` todo · `[~]` partial · `[x]` done.

## P1 — foundational (this pass)
- `[x]` **`survey_corpus` (anti-anchoring primitive).** Deterministic, ranked survey over ALL runs × channels:
  per-channel effect size vs a reference design, z-score across designs, notable set (|z|≥2), and coverage
  (n designs/runs/seeds, QC distribution, non-reportable list). Coli must consume it *before* any hypothesis.
  → `survey.py`, tool `survey_corpus`.
- `[x]` **Biosecurity guardrail (design-time).** `biosecurity.py`: signature registry (AMR efflux / mar-sox-rob
  regulon, toxin-antitoxin over-expression, virulence factors) + `screen(design)` with direction awareness
  (KO of an efflux gene is safe; up-regulation is concerning). Wire into `run_experiment`; expose
  `screen_design`. Flag for review or block — never auto-run a flagged design.
- `[x]` **Agent discipline (system prompt).** Survey-first; read cold (ignore prior conclusions, tools win);
  disconfirmation (name what would falsify, read exactly that); feasibility + biosecurity before any run;
  state coverage per claim.

## P2 — depth
- `[x]` **Curated species panel (D2) + pathway aggregation.** `pathway_panel.py`: 13 pathways / 199 K-12 gene
  symbols, resolved to monomer IDs via the gene map (symbol→cistron→monomer, dumped from sim_data). The reader
  records per-pathway **proteome fractions** (size-independent — ribosomal ≈ 35%, textbook) into the manifest;
  `survey_corpus` ranks them as `pw:<pathway>` channels. Panel is a committed config list, **interchangeable**:
  edit it and `python -m cellarium.pathway_panel` re-resolves. (Resolves 199/199; generated maps gitignored.)
- `[x]` **Differential top-movers.** `differential.py` + tools: `differential(target, reference)` ranks
  channels + pathways by |log2 fold-change| from the manifest (instant); `top_movers(result_id, ref_id, kind)`
  ranks individual species from simOut (3,938 proteins compared), gene-symbol-annotated. The "interchangeable
  panel" solved data-drivenly — discover what moved instead of pre-declaring it.
- `[x]` **Phenotype-grounded biosecurity.** `biosecurity.screen_result` / `screen_phenotype` tool: flags a
  design whose simulated proteome up-regulates a concerning pathway (AMR efflux, ≥2× vs control) — grounded in
  the phenotype, not keywords (DEMO Act 3), so it catches an *emergent* AMR signature the intent screen would
  miss. Logic unit-tested; no false positives on the corpus. **Demo-prep TODO — RESOLVED as a scope limitation
  (§L):** the phenotype screen cannot fire on a real run because the mar-sox-rob AMR regulon isn't modeled (not
  among the 23 TFs; efflux genes don't move ≥2× under any modeled condition; no overexpression variant). Act 3
  rests on the model-independent INTENT screen instead. Superseded line: generate one positive case (a
  marA/soxS-overexpression design) to show it firing on a real run.
- `[x]` **Coverage completeness gate.** `rigor.py` tracks designs deep-read this session (via the read tools);
  `coverage_check` reports examined-vs-full-grid so a conclusion can't quietly rest on a subset. Reset per
  agent run.
- `[x]` **Disconfirmation as a required tool step.** `disconfirm(target, reference, channel)` exposes the
  per-seed spread behind a claimed effect (is it bigger than replicate noise?), the corpus z-score, and a
  falsification checklist — turning "seek disconfirmation" into a callable step the agent must use before a
  causal claim. Verified: with_aa vs basal growth is +121%, `within_replicate_noise=False`.

## P3 — robustness (token-costly; reserve for high-stakes conclusions)
- `[ ]` **Order-randomization + self-consistency.** Shuffle survey row order; re-derive N times (Wang 2022);
  keep only conclusions stable across orderings/samples.
- `[ ]` **Heterogeneous adversarial pass.** Role-diverse debate — analyst vs verifier vs skeptic — to catch
  over-focus and overlooked data (Du 2023; role diversity, Zhou 2025).

## Guardrail summary (the "Rigor rail") — three distinct axes
- **Feasibility** (`envelope.py`): is the perturbation in the *validated* regime? (a carbon-source switch is not).
- **Provenance** (`provenance.py`): is the quantity *fitted* (in-sample = consistency) or *predicted*
  (out-of-sample = genuine test)? Tagged on every result; the H1/H2 pair proved this is the deepest axis.
- **Mechanistic scope** (`scope.py`): is the target's function actually *simulated* (metabolic enzyme / one of
  the ~23 modeled TFs) or expressed-but-inert? A non-mechanistic KO null is model scope, NOT biology.
- **Biosecurity** (`biosecurity.py`): design-time intent screen + phenotype-grounded result screen.
- **Output QC** (`qc.py`): degenerate generations are evidence-absent, never a doubling time.
- **Statistics** (`rigor.disconfirm`, `survey`): 95% CIs + Welch t; solver diagnostics excluded from ranking.

## Feasibility notes
P1 uses existing manifest data (no new sims) — cheap + deterministic. P2.1/2.2 need the species panel in the
manifest (a generation-time change + a one-time backfill of local runs). P3 is multi-pass (token cost) — gate
to final conclusions, not routine reads.

## P4 — KO/objective instrument, from the literature review (2026-07-10)
From the repo pass + Covert-lab literature scan (see `DECISIONS.md` D4/D4-lit, `CORPUS_OBSERVATIONS.md` §J +
Literature grounding). Core lesson: the model doesn't yield clean single-gene-KO phenotypes because the metabolism
FBA objective has **no growth term** (KOs reroute) and the KO variant is an **expression** knockout; the fix is to
change the **readout** (viability, not graded growth) and the **design** (graded / multi-gene), not the objective.

### P4.0 — cheap, no new sims
- `[x]` **Viability as a first-class corpus channel.** `mode_run` emits a per-lineage division aggregate
  (`division_rate`, `gens_reached`, `terminal_divided`, `n_fba_failures`, `median_division_time_sec`); flattened
  into manifest columns so viability is queryable in DuckDB (cross-seed `GROUP BY` recovers the §J verdict — a
  lineage can't see the requested depth, so 'died early' is a cross-seed signal). Standalone rollup =
  `reader.viability` / `mode_viability`. *Source: Gherman et al. 2025.* **Done** — corpus backfilled
  (`record_existing`); a GROUP BY over the KO variants reproduces §J from SQL (gltX min_divrate 0.67 / max_gens 3
  / terminal_divided False vs 1.00 / 4 / True for the metabolic KOs). Minor follow-up: the gltX run lacks a
  `KO:` condition label (shows as `?`) — a provenance gap in that run's design.json, not the channel.
- `[x]` **Ground-truth essentiality reference in `gene_scope`.** `mode_gene_scope` reads wcEcoli's own validation
  set (Baba 2006 Keio + Joyce 2006, glucose-minimal; 406 genes, 402 matched) at dump time — read from the checkout,
  NOT vendored (D3). Each gene carries `essential_reference`; `classify_gene` returns a `benchmark` comparing the
  KO prior to it. Turns the self-reported 0/5 into a benchmarked call: fabI/glmS/gltA -> `model_UNDER_predicts`
  (essential yet the model KO is viable), gltX/rpoB -> `consistent_lethal`, pfkA/tpiA/flgB -> `consistent_viable`.
  *Source: EcoCyc 2025 (via the wcEcoli validation set).*
- `[x]` **Cite the aaRS mechanism in the scope crash note** (`scope.py`): the `lethal_crash` note now appends, for
  `machinery_role == "aaRS"`, that aaRS kcats are fit ~7.6× above in vitro and perturbing aaRS activity is
  "catastrophic" — a full KO is the extreme. *Source: Choi & Covert 2023 (doi:10.1093/nar/gkad435).*
- `[x]` **Relabel `mode_fba_essentiality` as under-sensitive/deprecated** — docstrings (worker + `reader`) now lead
  with DEPRECATED and point to the `essential_reference` benchmark / graded perturbations / D4 tier-2; the result
  carries `deprecated: True` + a `warning`. *Source: D4 root-cause.*

### P4.1 — design + coverage
- `[x]` **Expose `viability` as an agent tool** (`tools.py`): cross-seed division verdict (viable/impaired/
  inviable) per design from the manifest — instant, no container. `store.viability` does the MIN/BOOL_AND rollup;
  the tool cross-links `mechanistic_scope` ('viable' is the model, not ground truth — check the benchmark). Agent
  SYSTEM prompt now tells Coli to judge KO lethality by viability, not growth. Verdict logic unit-tested (three
  regimes). (Also installed the declared `duckdb` dep — the full suite now passes 16/16.)
- `[x]` **Viability in `differential`** — `summary` now returns the target's cross-seed viability verdict, so a
  differential is read with "did the cell even divide?" in view (flat channels on a VIABLE KO = reroute; on an
  INVIABLE one the fold-changes are pre-crash garbage). *Source: §J.*
- `[x]` **Graded-first design generators** (`generate.py`): `essential_ko_designs`/`mechanistic_ko_designs`
  relabelled as KNOWN-TO-REROUTE controls (the old growth-decline predictions were disproven), pointing to graded
  perturbations for real phenotypes. *Source: §K.*
- `[x]` **Translation-factor machinery detection** — RESOLVED as a no-op: wcEcoli models elongation as rate-based,
  not explicit factor cycling, so EF-Tu/EF-G/IF/RF are *correctly* inert; flagging them as machinery would predict
  a crash that can't happen. The essentiality benchmark already surfaces the mismatch (fusA/infA/prfA/tsf ->
  `model_UNDER_predicts`; tufA correctly non-essential via its tufB paralog). *Source: Choi & Covert 2023 / P4.0.*
- `[x]` **Objective-weight design variants** (`generate.py` `objective_weight_designs`, `--objective-weight`):
  `metabolism_kinetic_objective_weight` + `metabolism_secretion_penalty` sweeps — the legitimate graded objective
  levers (indices into the model's own arrays; upstream ships analyses for both). *Source: D4/§K.*

### P4.2 — larger / research
- `[x]` **Reroute-diagnosis tool** (`reroute_diagnosis`): for a viable metabolic KO, seed-averages sum|flux|
  through the KO'd enzyme's OWN reactions in KO vs WT; if wt_flux>0 and ko_flux≈0 on a dividing cell, flags
  `reroute_is_artifact` (the model bypasses an enzyme real biology can't). Verified on fabI (27 rxns, 0 vs 0.211).
  Turns §K's fabI finding into a reusable capability; pairs with the essentiality benchmark. *Source: §K / Q3.*
- `[ ]` **Metabolic-essentiality verdict** — either `fba_essentiality` v2 (hard target-demand feasibility) or call
  **EcoCyc's steady-state flux model as the oracle** (cheaper, authoritative). *Source: EcoCyc 2025 + D4.*
- `[ ]` **Multi-gene / reduced-genome design generator** (`generate.py`): combinatorial deletions scored by
  viability. *Source: Gherman et al. 2025.*
- `[ ]` **ML surrogate for viability/division** trained on the corpus (95% compute reduction) — the
  "reason over the model at scale" primitive; artifact for "The Well for the Cell". *Source: Gherman et al. 2025.*

## P5 — harness gaps from the audit round (2026-07-10)
Stress-test (17 tools, edge cases) found no crashes and semantically-correct guardrails. These are the gaps the
recorded roadmap did NOT cover — the "close the loop to new experiments" layer + methodology/code debt.
- `[ ]` **F1 (HIGH) — design-space enumeration tool.** Coli cannot discover runnable conditions / variant types /
  valid gene-KO indices; the `variant_map` exists in cache but isn't a tool. Blocks "generate hypotheses + run
  sims" (it would guess indices). Expose `design_space()` (conditions, variant types, gene→ko_index).
- `[ ]` **F2 (MED-HIGH) — hypothesis-vetting tool.** Encode vet-before-run (feasibility + provenance + scope +
  viability-prior + biosecurity + power) as one `vet_hypothesis` go/no-go with reasons, instead of manual chaining.
- `[ ]` **F3 (MED) — model-validation summary.** Corpus-level essentiality agreement vs the 402-gene ground truth
  (a `model_UNDER_predicts` rate / confusion matrix) so Coli can calibrate trust in a KO verdict.
- `[ ]` **F4 (MED) — statistical-power guidance.** "Is this comparison powered / how many seeds needed" — no tool.
- `[ ]` **F5 (LOW) — integration polish:** add viability to `survey` CHANNELS; add `reroute_diagnosis` to the agent
  KO-guidance prompt.
- `[ ]` **M1 (MED) — calibrate the viability verdict thresholds** (0.9/0.6, set on n=1 machinery = gltX) against
  more machinery + graded-KO data; the "impaired" band is a guess.
- `[ ]` **M2 (LOW) — t-distribution CIs.** survey/rigor use normal-approx `1.96·SE`; for n=4–8 seeds this is
  ~20–60% too narrow and `|t|≥2` is slightly liberal. Use scipy t (already a dep).
- `[ ]` **C1 (LOW) — DRY the viability verdict** (duplicated, currently consistent, in `_reader_worker.py` +
  `store.py`) and add a `gene_scope` cache version/staleness guard (C3).
