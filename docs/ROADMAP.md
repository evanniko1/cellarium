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
  miss. Logic unit-tested; no false positives on the corpus. **Demo-prep TODO:** generate one positive case (a
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
- `[~]` **Viability as a first-class corpus channel.** `mode_run` emits a per-lineage division aggregate
  (`division_rate`, `gens_reached`, `terminal_divided`, `n_fba_failures`, `median_division_time_sec`); flattened
  into manifest columns so viability is queryable in DuckDB (cross-seed `GROUP BY` recovers the §J verdict — a
  lineage can't see the requested depth, so 'died early' is a cross-seed signal). Standalone rollup =
  `reader.viability` / `mode_viability`. *Source: Gherman et al. 2025.* **[in progress — backfilling]**
- `[ ]` **Ground-truth essentiality reference in `gene_scope`.** Join Keio/EcoCyc essential-gene flags per gene so
  `classify_gene` reports `model prior: reroutes / EcoCyc: essential` side by side — upgrades calibration from
  self-reported to benchmarked. *Source: EcoCyc 2025.*
- `[ ]` **Cite the aaRS mechanism in the scope crash note** (`scope.py`): aaRS kcats fit 7.6× above in vitro;
  perturbation "catastrophic". *Source: Choi & Covert 2023.*
- `[ ]` **Relabel `mode_fba_essentiality` as under-sensitive/deprecated** — it reads the soft growthless objective
  (0/35). Not an essentiality oracle until fixed/replaced (P4.2). *Source: D4 root-cause.*

### P4.1 — design + coverage
- `[ ]` **Expose `viability` as an agent tool** (`tools.py`), numbers-first + calibration note — *after* the P4.0
  backfill validates the verdict beyond gltX.
- `[ ]` **Viability in `differential`/screen** — report a viability delta, not only growth deltas.
- `[ ]` **Graded-first design generators** (`generate.py`): label single-metabolic-KO generators as
  known-to-reroute controls; promote graded-capacity (rRNA operons, ppGpp) as the primary phenotype path.
- `[ ]` **Translation-factor machinery detection** (`_reader_worker.py`): flag EF-Tu/`tufA`, EF-G/`fusA`, IF/RF
  (currently unflagged — no molecule group). *Source: Choi & Covert 2023 elongation model.*
- `[ ]` **Objective-weight design variants** (`generate.py`): `kinetic_objective_weight` / `secretion_penalty`
  sweeps — the legitimate objective levers (upstream ships analyses for both). *Source: D4.*

### P4.2 — larger / research
- `[ ]` **Metabolic-essentiality verdict** — either `fba_essentiality` v2 (hard target-demand feasibility) or call
  **EcoCyc's steady-state flux model as the oracle** (cheaper, authoritative). *Source: EcoCyc 2025 + D4.*
- `[ ]` **Multi-gene / reduced-genome design generator** (`generate.py`): combinatorial deletions scored by
  viability. *Source: Gherman et al. 2025.*
- `[ ]` **ML surrogate for viability/division** trained on the corpus (95% compute reduction) — the
  "reason over the model at scale" primitive; artifact for "The Well for the Cell". *Source: Gherman et al. 2025.*
