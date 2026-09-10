# Cellarium

An agentic workbench over a **whole-cell simulation of *Escherichia coli*** — one where the interesting
engineering problem is not getting an answer, but knowing when there isn't one.

The simulation ([wcEcoli](https://github.com/CovertLab/wcEcoli), from the Covert Lab) models transcription,
translation, metabolism, replication and division as mechanisms rather than fitted curves. It will return a
plausible number for almost any question you put to it. Many of those numbers are not measurements: some are
bounds the parameter fit fell back on, some are algebraic identities of a modelling choice, and some come
from runs where the cell had already stopped working. **Cellarium exists to tell those apart.**

---

## Start where your question is

<div class="grid cards" markdown>

- :material-play-circle: **I want to run something**

    Set up the model container, generate corpus runs, and connect an API key.

    [Running simulations](DOCKER_SETUP.md) · [Generating the corpus](GENERATE.md) ·
    [Credentials](CREDENTIALS.md)

- :material-database-search: **I have the data and want to use it correctly**

    What one row *is*, what the QC verdicts mean, and — most importantly — what the corpus cannot support.

    [Dataset datasheet](DATASHEET.md) · [What a 'knockout' means](KNOCKOUT_SEMANTICS.md) ·
    [QC statuses](QC_STATUSES.md)

- :material-alert-circle-outline: **Can I trust this number?**

    Where the model is silent, where the parameter fit gave up, and where two builds disagree.

    [Knowledge base vs a fresh fit](KB_DIVERGENCE.md) ·
    [What 'unknown' degradation rates get](PARCA4_UNKNOWN_CLASS.md) ·
    [Model extension](MODEL_EXTENSION.md)

- :material-account-group: **How do the agents work?**

    A Council that proposes hypotheses blind to the data, and an investigator that answers only from it.

    [The Socratic Council](SOCRATIC_COUNCIL.md) · [The investigation loop](INVESTIGATION_LOOP.md) ·
    [Evaluation report](SOCRATIC_COUNCIL_EVAL_REPORT.md)

- :material-check-decagram: **How was any of this validated?**

    Cross-checks against real measurements, and the plans for the ones not yet run.

    [Three validation plans](SCIENCE_VALIDATION_PLANS.md) · [ROUTE1 corpus record](ROUTE1_CORPUS_RECORD.md) ·
    [A/B replication plan](PUB_A1_REPLICATION.md)

- :material-notebook-outline: **What was decided, and why?**

    Including the decisions that were withdrawn after they turned out to be wrong.

    [Deferred decisions](DECISIONS.md)

</div>

---

## The three ideas worth knowing before you read anything else

**1. A refusal is a result.** When the model structurally cannot represent a mechanism, the honest answer is
not a number with a caveat — it is a refusal that names *why*, and where possible an offer of the run that
*could* answer it. Under the default elongation model, for instance, the 86 per-isoacceptor charging columns
are identical by construction; a within-family spread of 0.0 there is arithmetic, not a measurement.

**2. Provenance is part of the value.** Two rows are comparable only if they came from the same *arm* —
the same fitted knowledge base, operon setting and elongation model. Those columns exist so a reader can
partition before averaging, and much of this documentation is about the ways that goes wrong quietly.

**3. Division is not viability.** A cell can finish replicating its chromosome, pass its per-generation
checks, and have synthesised no protein at all. That is not a hypothetical — it is a design in this corpus.
Data that looks clean and is not is the failure mode the whole system is built around.

---

## For reviewers

The two documents that answer "should I believe this" most directly are the
[dataset datasheet](DATASHEET.md) — specifically its *what this dataset cannot support* section — and
[the knowledge-base divergence measurement](KB_DIVERGENCE.md), which quantifies the extent to which the
published corpus does **not** regenerate from a fresh parameter fit.

Corrections to this project's own earlier claims are kept visible rather than squashed; several are recorded
in [Deferred decisions](DECISIONS.md).
