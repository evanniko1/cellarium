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
- `[ ]` **Coverage completeness gate.** Track examined-vs-full-grid in the loop; flag conclusions drawn from a
  subset the survey shows to be larger.
- `[ ]` **Disconfirmation as a required tool step** (not only a prompt instruction).

## P3 — robustness (token-costly; reserve for high-stakes conclusions)
- `[ ]` **Order-randomization + self-consistency.** Shuffle survey row order; re-derive N times (Wang 2022);
  keep only conclusions stable across orderings/samples.
- `[ ]` **Heterogeneous adversarial pass.** Role-diverse debate — analyst vs verifier vs skeptic — to catch
  over-focus and overlooked data (Du 2023; role diversity, Zhou 2025).

## Guardrail summary (the "Rigor rail")
- **Feasibility** (`envelope.py`, exists): out-of-envelope designs (mid-run carbon-source switch) refused
  pre-run with an in-envelope alternative.
- **Biosecurity** (`biosecurity.py`): design-time signature screen (P1) → phenotype-grounded result screen
  (P2). Flag for review / block; never auto-run a flagged design. v1 is intent/signature-based and says so.
- **Output QC** (`qc.py`, exists): degenerate generations are evidence-absent, never a doubling time.

## Feasibility notes
P1 uses existing manifest data (no new sims) — cheap + deterministic. P2.1/2.2 need the species panel in the
manifest (a generation-time change + a one-time backfill of local runs). P3 is multi-pass (token cost) — gate
to final conclusions, not routine reads.
