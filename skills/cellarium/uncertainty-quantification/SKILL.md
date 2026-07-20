# uncertainty-quantification — quantify + report uncertainty with the toolkit's own executable stats

Use this skill whenever a claim needs a number-with-uncertainty: a difference, a trend/law, a "no effect", a
distribution shape, a model-vs-benchmark agreement, or a conclusion you're about to commit to. It routes each
question to the project's OWN grounded, scipy-free tools — so every interval/p-value in the manuscript is
reproducible from a tool call, not asserted. Never fabricate spread: every value comes from the real per-seed data.

## Pick the tool by the question

| Question | Tool | What you get | The honest read |
|---|---|---|---|
| Is target vs reference on a channel a real effect? | `disconfirm(target, reference, channel)` | per-seed values, Welch t, 95% CIs, corpus z | `significant` needs n≥2 both sides; CIs non-overlapping. `z_vs_corpus_spread` is positioning, NOT a p-value. |
| Two groups, means differ? | `stats.welch_t(a, b)` | Welch t, Welch–Satterthwaite df, two-sided p | unequal-variance safe; the correct default two-sample test. |
| A trend / growth law across designs? | `fit_relation(designs, x, y)` | slope, R², adj-R², slope 95% CI, `slope_ci_excludes_0`, p | assert a law ONLY if the CI clears 0; read `fit_out_of_sample_only`, not just `fit_all`. n=2 → no inference (0 residual df). |
| Is a "no effect" real or underpowered? | `power_check(channel, effect_pct, n_seeds)` | min detectable effect at n, seeds needed for a target | a null below the MDE is underpowered, not equivalence. |
| A single 95% CI on one sample? | `stats.t95_halfwidth(x)` | t-distribution half-width (small-n honest) | uses the Student-t table, not a normal approximation. |
| Is a distribution bimodal (two regimes)? | `rigor.bimodality(channel, designs)` | Sarle's BC (>0.555 ~ two modes), skew/kurtosis, best split + separation-SD | a heuristic, NOT Hartigan's dip; corroborate BC with the split separation. |
| Does the headline conclusion survive scrutiny? | `robustness_check(target, reference, channel)` | an adversarial, order-randomized juror verdict (robust / order_sensitive / refuted / underpowered / contested) | `order_sensitive` = fragile; get more data before publishing. |
| How much of the grid does the claim rest on? | `coverage_check()` | designs deep-read this session vs all | do NOT generalize beyond the examined set; scope the claim or examine the rest. |
| FBA number robustness? | `fba_sensitivity(gene, delta)` | how growth / an essentiality call move under ±delta on medium/GAM/NGAM | an FBA conclusion is only safe if it survives the lever spread. |
| Model vs the essentiality benchmark? | `model_validation()` | agreement counts, recall, `model_UNDER_predicts` | a KO "viable" verdict is unreliable for essential-gene candidates — defer to the benchmark. |

## Reporting rules

- Report an effect as **estimate + interval + test**, never a bare point ("−18%, Welch t=3.1, 95% CI [−0.22,−0.09],
  n=4"), and name the test and n.
- For a null, report the **power**: "no detected change (power_check: MDE 12% at n=4, so a <12% effect is
  undetectable here)".
- For a law, report **slope + CI + whether it excludes 0**, adj-R², and the **out-of-sample** fit separately.
- Round for the reader but keep the tool's precision in provenance. Prefer a CI to a lone p-value; prefer a
  power-qualified null to a silent one.
- Small n is the norm here — say so. LOO/descriptive-only is honest; a fabricated precision is not.

## Companion skills

- `scientific-writing` — how these numbers become honest prose.
- `peer-review` — runs several of these checks adversarially before submission.
