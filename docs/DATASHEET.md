# Datasheet: the Cellarium whole-cell simulation corpus

*Following the structure of Gebru et al., **Datasheets for Datasets** (CACM 64:12). The point of a datasheet
is to answer, before anyone builds on the data, the questions they would otherwise discover the hard way —
above all **what this dataset cannot support**. That section is not an appendix here; it is the reason the
document exists.*

---

## Motivation

**What is this?** A corpus of simulation runs from **wcEcoli**, a mechanistic whole-cell model of
*Escherichia coli* — a simulation in which transcription, translation, metabolism, replication and division
are each modelled as processes with their own machinery, rather than fitted curves. Each run follows one
cell lineage through one or more generations, recording thousands of molecular quantities at every timestep.

**Why does it exist?** Whole-cell simulations are expensive to produce and are usually discarded after the
one analysis they were run for. This corpus keeps them, indexes them, and attaches enough provenance that a
later reader can tell what a number means and whether it can legitimately be compared to another. The
ambition is "The Well, for the cell": a reusable body of simulated cellular dynamics.

**Who made it?** Produced by the Cellarium project on top of the Covert Lab's wcEcoli model. The model
itself is not ours; the campaign design, provenance layer, QC and index are.

---

## Composition

**What is one row?** **One generation of one seed of one design.** Not one cell, not one experiment, not one
lineage. This is the single most misread thing in the dataset and everything below follows from it.

- A **design** is a perturbation plus a condition — e.g. `gene_knockout/KO:argS`, `condition/acetate`.
- A **seed** is one stochastic replicate of that design.
- A **generation** is one division cycle within a seed's lineage.

**How much?** 369 indexed rows at the time of writing, across ~100 designs, spanning single-gene knockouts,
graded knockdowns, multi-gene knockouts, media conditions, media shifts, ppGpp perturbations and wild-type
controls.

**What does each row carry?** Aggregate channels per generation (growth rate, ppGpp concentration, masses,
charged-tRNA fractions and many more), the QC verdict, and provenance: which knowledge base fitted it
(`kb_sha256`), which elongation model ran it, whether operons were on, which container image executed it.

**Is the raw output included?** The per-timestep raw output is far larger than the index and is distributed
separately as per-run archives. **The fitted knowledge base itself is NOT distributed** — see Licensing.

---

## What this dataset cannot support

*The rest of the datasheet is conventional. This section is the one to read.*

**1. Seeds are independent; generations within a lineage are not.** Generations 0–3 of one seed are four
rows, not four independent samples: they share a mother cell and its state. Treating them as replicates
inflates `n` and shrinks every confidence interval you compute.

**2. A row can be present, readable, and not data.** Crashed runs and QC-failed runs are in the table.
They have channel values. Those values are numerical garbage. **Always filter on `reportable`** — a mean
taken over a collapsed generation is arithmetic performed on wreckage.

**3. "Divided" is chromosome count and nothing else.** It means the cell finished replicating its
chromosome and ran more than ten steps. DNA replication proceeds when translation has stopped, so a design
can divide, pass its per-generation checks, and have had **zero protein synthesis**. This is not
hypothetical: `KO:rpmE` shows a mean effective elongation rate of exactly **0.0 aa/s** across all 15 of its
locally-readable generation directories while 8 of them recorded `generation_qc == "ok"`. Viability is not
division.

**4. Rows from different arms are not poolable.** An *arm* is `kb_sha256` × operon mode × elongation model.
Two rows from different arms were produced by different parameterisations of the model and averaging them
produces a number that describes neither. The columns are there so you can partition; use them.

**5. A missing mechanism reads as a number, not as an absence.** Under the default steady-state elongation
model the 86 per-isoacceptor charging columns are **identical by construction** — a within-family spread of
0.0 there is arithmetic, not a measurement. Under `coarse_kinetic` the same columns are exact zeros because
that model does not solve charging at all. Neither is evidence that charging is uniform.

**6. Generation depth is a stratum, not noise.** Comparing a design that reached generation 1 against one
that reached generation 4 compares different things. Depth-match, or say that you did not.

**7. Aggregate columns hide shape.** A per-generation mean cannot show a transient. A ppGpp spike that rises
and decays within a generation is invisible in that generation's mean; the raw series is where it lives.

**8. About 27% of messenger half-lives are not fitted values.** Where the estimator has no information it
assigns a bound (a floor of 91.2 min or a ceiling of 24 s) or a population mean, and those are stored as
ordinary floats indistinguishable from measurements. They hold **12.087%** of mRNA expression in the basal
condition. `parca/deg_rate_baseline.json` ships alongside the corpus and labels every one of them; consult
it before computing any statistic over transcript stability.

**9. The corpus does not regenerate from a fresh parameter fit.** Rebuilding the model's fitted parameters
today produces a knowledge base 97.2% identical to the one that made these rows — and the remainder is not
drift. Amino-acid metabolism is genuinely re-fitted, one gene is retyped, and an index shift moves one
messenger half-life by 228×. Runs produced after a rebuild are a **new arm** and are not comparable to these
without checking `kb_sha256`.

**10. "In sample" is not "out of sample".** Some conditions were used in fitting the model. A model
reproducing a condition it was fitted on is not evidence that it predicts.

---

## Collection

**How was it produced?** Each run is a wcEcoli simulation executed in a pinned container, launched through
Cellarium's runner, with its provenance recorded before the simulation starts (so a crash still leaves a
labelled row). Designs were chosen to span mechanisms of interest rather than sampled at random — this is a
**designed campaign, not a random sample of design space**, and it is not representative of anything except
itself.

**QC.** Every generation is scored. Verdicts include division failure, implausible growth, over-replication
and channel implausibility; `docs/QC_STATUSES.md` defines each. A translation-collapse floor of 1.0 aa/s was
added later, anchored to Dai et al. 2016 (PMID 27941827) — rows written before it cannot self-correct,
because the channel it judges was never recorded for them.

**Known collection defect.** Fixed-width string columns in the simulation output take their width from the
first value written, so a later longer value is silently truncated. Confirmed for a media identifier where
`minimal_plus_amino_acids` became `minimal` and a nutrient shift vanished from the record. Guarded now, but
older rows may carry it.

---

## Preprocessing and labelling

Channel aggregation per generation, QC scoring, and the provenance join. The index is append-only:
corrections **supersede** rather than mutate, and filtering must happen *after* de-duplication or a stale row
can outlive the correction that replaced it.

---

## Uses

**Suitable for:** comparing designs within an arm at matched generation depth; studying dynamics from the
raw series; benchmarking agents or tools that must reason about simulated cellular data and refuse when the
data cannot answer; methods work on provenance and refusal.

**Not suitable for:** treating simulated values as measurements of real *E. coli*; any use that pools across
arms; any use that reads a bound as a fitted parameter; training a model to predict biology without the
caveats above travelling with the predictions.

**Has it been used already?** Yes — for the agent evaluations and the scientific cross-checks described in
`docs/`, and for the validation work planned in `docs/SCIENCE_VALIDATION_PLANS.md`.

---

## Distribution and licensing

Simulation outputs and the index are distributed as a HuggingFace dataset. **The fitted knowledge base
(`simData.cPickle`) is not, and cannot be** — the Stanford licence on wcEcoli does not permit
redistributing it. This is the direct cause of limitation 9: a user cannot reproduce these rows without
re-fitting, and re-fitting produces a different arm.

Alongside the run archives the dataset ships `parca/deg_rate_baseline.json`, which carries the degradation-
rate provenance (floor / ceiling / imputed / fit counts, the share of expression each holds, and the
transcription units where it matters most), pinned to the `kb_sha256` it describes.

---

## Maintenance

Maintained in the Cellarium repository, where the invariant catalogue, QC definitions and provenance columns
live beside the code that enforces them. Errata are recorded in `docs/DECISIONS.md` and the project backlog,
including corrections to this project's *own* earlier claims — several such corrections are visible in the
git history and are deliberately not squashed.

**If you find a row that misleads you, that is a bug in this datasheet as much as in the data.**
