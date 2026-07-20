# scientific-writing — drafting the Cellarium manuscript with its provenance conventions

Use this skill when drafting or revising manuscript prose (a Results paragraph, a Methods section, an abstract
claim) about Cellarium findings. It encodes the project's non-negotiable writing conventions so a draft is
publishable-honest by construction, not honest-if-you-remember. It does not fetch anything; it governs how you
write about numbers the grounded tools produced.

## The first rule: every number rides with its provenance

Cellarium's whole contribution is a *glass box* — so a manuscript number that cannot be traced to a tool call is a
defect, not prose. For each quantitative claim, the sentence (or its citation) must make recoverable:

- **which tool produced it** (`survey_corpus`, `differential`, `read_series`, `disconfirm`, `fit_relation`, an FBA
  tool, `rnaseq_concordance`, …) — the primary number is always the sim/corpus, never a recollection;
- **the design(s)** it compares (`perturbation/condition` labels) and the **reference**;
- **n** (seeds) and the **QC** state of the contributing runs;
- **the model version / environment** (the run's `provenance.run_environment()` — interpreter, git commit, pinned deps).

If you cannot fill those in, you cannot yet write the sentence — call the tool.

## In-sample vs out-of-sample: the word "predict" is earned, not free

The single most common overclaim. The model was ParCa-fitted to a set of conditions, so agreement there is
**consistency**, not prediction. Before writing "the model predicts / reproduces / validates X":

- run `provenance(perturbation, condition)` (or read `fit_relation`'s per-point `in_sample`/`out_of_sample` tags);
- **in-sample** result → write "is consistent with" / "reproduces the fitted" — never "predicts";
- **out-of-sample** perturbation → "predicts" is earned; say so explicitly and name it as the genuine test.
- A law fitted across designs: report `fit_out_of_sample_only`, not just `fit_all` — a high R² driven by in-sample
  points is consistency dressed as prediction.

## The blindness / quarantine control (Council results)

If the manuscript reports a Council-generated hypothesis, state the quarantine: the Council deliberated **blind** to
the corpus (it saw only the instrument's capabilities, never readings), so the hypothesis is a genuine prediction
the grounded Cellwright arm then tested — that separation is a *control*, and the paper must describe it as one.

## Model behavior is not ground truth

A "viable" KO is the model's behavior. For metabolic essentials the homeostatic FBA under-predicts (no growth term
→ it reroutes). When writing a viability/essentiality claim, cross-reference the Baba/Joyce benchmark
(`mechanistic_scope` / `metabolic_essentiality` / `model_validation`): if `agreement == "model_UNDER_predicts"`, the
prose must defer to the benchmark, not the sim. Frame a model–benchmark disagreement as a **model-limit hypothesis**
(the scientific payoff), never as a result.

## Nulls, effects, and hedging

- A "no effect" is only reportable as equivalence if `power_check` shows the comparison could have detected the
  effect size claimed. Otherwise write "underpowered to detect", not "no difference".
- State an effect with its test: Welch t + CI (`disconfirm`), or a slope with `slope_ci_excludes_0` + p
  (`fit_relation`). "Markedly", "substantially" without a number is not a claim.
- Prefer the honest hedge to the confident overclaim; reviewers trust a paper that states its own limits.

## Section-by-section checklist

- **Abstract**: one sentence of the quarantine design; claims scoped to in/out-of-sample; no number without a route.
- **Methods**: the model version + `requirements.lock`; the QC gate; the essentiality benchmark provenance; the
  blindness protocol; the stats used (Welch, t-CIs, BH-FDR, Sarle's BC — from `stats`/`rigor`).
- **Results**: each paragraph anchored to the tool that produced its numbers; in/out-of-sample stated; nulls
  power-qualified.
- **Discussion**: model-limit hypotheses named as such; wet-lab-worthy predictions flagged (out-of-sample + the
  literature, via the `literature-review` skill, disagrees or is silent).

## Companion skills

- `peer-review` — run it on your own draft before submission (the pre-submission self-critique).
- `uncertainty-quantification` — the executable tools for every CI / p-value / power statement here.
- `literature-review` (vendored) — cite prior work; keep the corpus as the source of primary numbers.
