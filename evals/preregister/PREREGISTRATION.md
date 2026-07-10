# Pre-registration — Socratic Council analyses

Frozen before the confirmatory results were read. Prompts are pinned by git tag; the operationalization-quality
rubric and the loop SESOIs below are fixed here so the analyses are confirmatory, not post-hoc. Sampling: the
Council roles run at **temperature 0.7** on `claude-sonnet-4-5` (a pinned, stated sampling temperature — the
named variance source); graders run at their model defaults (reasoning graders reject an explicit temperature).
Replicates: **k = 3** per (case, config) for the ablation (extendable). Variance is the model's inherent
sampling stochasticity across replicates, reported as case-clustered CIs — we do not claim seed-level API
determinism.

## 1. Primary endpoint (mechanism, Workstream C1)
**Estimand:** the operationalization-quality score of the Council's output hypothesis (0–6; see rubric §3),
graded blind to the literature answer. **Primary comparison:** `full` (proposer+skeptic+judge) vs
`proposer_only` (single-shot), on the **case-clustered mean** (mean over replicates within a case, then across
the 10 cases). **Test:** Wilcoxon signed-rank on the 10 per-case differences (full − proposer_only).
**Direction:** one-sided, H_A: full ≥ proposer_only. **Secondary comparisons:** full vs `no_skeptic` (isolates
the elenctic critic) and full vs `generic_judge` (isolates the falsifiability rubric), same test. Reported with
the GPT cross-family grader as a robustness replication and Claude↔GPT inter-rater agreement.

## 2. Secondary endpoints
- Convergence rate and mean rounds-to-convergence per config (Wilson 95% intervals); the degenerate/round-cap
  rate; behaviour under an adversarial skeptic.
- Rounds ∈ {1,2,3,4,6} × quota ∈ {0,1,2,3,5} sweeps: convergence + quality vs the loop constants.
- Closed-loop (D1): the fraction of Council hypotheses whose falsifier executes on fresh runs and returns a
  verdict; per-case confirm/refute + severity vs SESOI (§4). In-canon cases are labelled **blinded rediscovery**
  (the model was fit to the canon), out-of-canon as **use-novel model predictions** (wet-lab deferred).
- Quarantine control (C4): leaked vs quarantined Council — whether leakage yields a **wrong** downstream
  conclusion on fresh runs (reported whichever way it lands; not merely a higher rubric score).

## 3. Operationalization-quality rubric (answer-independent; 6 binary criteria)
Each judged from the hypothesis text alone; a well-formed but biologically wrong hypothesis still scores well.
1. **falsifiable** — names a concrete result that would refute H1 (a risky prohibition that could fail).
2. **operationalized** — every construct bound to a named observable AND the falsifier names a statistical test
   + numeric threshold.
3. **discriminating** — ≥1 rival named with a distinguishing experiment/design.
4. **quantitative** — predicted effect states a direction AND a numeric magnitude.
5. **specified** — independent variable (perturbation), dependent variable (observable), predicted direction.
6. **consistent** — no internal contradiction between H1, the falsifier, and the rival predictions.
Plus a deterministic **feasible** flag (≥1 in-envelope, biosecurity-clean candidate design; not LLM-graded).

## 4. Loop SESOIs (smallest effect size of interest), per case — frozen
Severity is assessed as whether the executed effect exceeds the SESOI (NOT post-hoc power). For a
dispersion/CV test the SESOI is a CV floor above pure-numerical noise; for a mean-difference test it is a %
effect floor.
- **1.1 / 3.1 (isogenic heterogeneity)** — CV SESOI = **0.05** on the tested channel (across-seed CV must exceed
  5% to count as biological, not numerical, heterogeneity). Absolute-threshold CV test (the sim is
  seed-deterministic, so there is no same-seed technical-replicate null).
- **4.1 (growth law)** — slope test; SESOI = a positive ribosome-fraction vs growth-rate slope whose 95% CI
  excludes 0 (regression scorer, v2).
- **4.2 (stringent response)** — mean-difference on ppGpp pre/post downshift; SESOI = **50%** rise (transient
  scorer, v2).
- **5.1 (essentiality)** — mean-difference in growth_rate KO-vs-wildtype; SESOI = **15%** growth reduction to
  call a gene essential.
- **relA / rrna-operon KO (mechanism for 1.1)** — mean-difference in the target channel's across-seed CV,
  KO-vs-wildtype; SESOI = **20%** relative CV change.

## 5. Multiplicity & scope
The primary endpoint is a single pre-specified comparison. Secondary/sweep comparisons are exploratory and
reported with Benjamini–Hochberg control within each family. Cases whose falsifier is structurally underpowered
at the achievable n (e.g. persistence ~1e-5 frequencies, fine bimodality) are excluded from the headline with
the denominator stated. Every reported number regenerates from committed, snapshot-pinned result JSON.
