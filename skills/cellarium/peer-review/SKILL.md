# peer-review — pre-submission adversarial self-critique of a Cellarium claim or draft

Use this skill BEFORE submitting (or before committing to a headline claim): review the draft/claim as a hostile,
competent referee would, tuned to *this project's* specific failure modes. The goal is to find the objection a
reviewer will raise while you can still fix it. Be adversarial about your own work; concede what the evidence
doesn't support.

## How to run it

For each claim the manuscript rests on, work the checklist below and produce, per claim, a verdict:
**supported / overclaimed / underpowered / provenance-gap**, with the specific fix. For a high-stakes claim, don't
stop at reading — run the executable check named (they exist precisely so review is testable, not rhetorical). The
`robustness_check` tool automates the adversarial panel for a single grounded effect (analyst/verifier/skeptic,
order-randomized) — use it on the one or two conclusions the paper depends on.

## The project's recurring failure modes (check every one)

1. **In-sample "prediction".** Does any "predicts/validates/reproduces" describe an in-sample (ParCa-fitted)
   condition? → run `provenance`; downgrade to "consistent with", or move to an out-of-sample design.
   For a fitted law, is the claim resting on `fit_all` R² when `fit_out_of_sample_only` is weak or n_out_of_sample
   is tiny? That is consistency sold as prediction.

2. **Viable-KO as biology.** Is a "gene X is non-essential / dispensable" claim really just the homeostatic FBA
   rerouting? → `mechanistic_scope` / `metabolic_essentiality`. If `agreement == "model_UNDER_predicts"`, the gene
   is essential in vivo — the claim must defer to the benchmark and be reframed as a model limit.

3. **Underpowered null read as equivalence.** Any "no effect of X" claim without a `power_check`? At the corpus's
   real replicate CV, could the design even detect the effect size dismissed? If not → "underpowered", not "no
   effect".

4. **Effect without a test.** A fold-change / difference stated without Welch t + CI (`disconfirm`) or a slope
   without `slope_ci_excludes_0` (`fit_relation`)? An adjective is not a statistic. Also: is `z_vs_corpus_spread`
   being read as significance? It is descriptive positioning only — never a p-value.

5. **Order-/single-pass fragility.** Does the headline conclusion survive an adversarial re-examination? Run
   `robustness_check(target, reference, channel)`; if it comes back `order_sensitive` or `refuted`, the conclusion
   is fragile — soften or strengthen the data before publishing.

6. **Provenance gaps.** Any number without a traceable tool/design/n/QC/model-version? Any figure charting a value
   that was not read from a tool? → fill the route or cut the number.

7. **Multiple comparisons.** Many channels/species scanned but significance reported per-comparison without FDR?
   `top_movers` already does BH-FDR — is the manuscript honoring q-values, or cherry-picking a raw fold-change?

8. **Non-mechanistic scope.** Is a phenotype claimed for a KO of a gene whose function isn't simulated? A null there
   is model scope, not biological dispensability (`mechanistic_scope`).

9. **Biosecurity / dual-use framing.** Does any proposed design or finding read as an uplift recipe? The biosecurity
   screen gates designs; the manuscript's framing should foreground the defensive/scientific intent (see the
   project's biosecurity stance).

## Output

A ranked list of the surviving objections (most-severe first), each with: the claim, the failure mode, the
executable check run + its result, and the concrete fix (reword / re-scope / run-one-more-tool / cut). If nothing
survives, say so — but only after actually running the checks, not by assertion.

## Companion skills

- `scientific-writing` — the conventions this skill audits against.
- `uncertainty-quantification` — the CI/power/robustness tools invoked above.
