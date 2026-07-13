# Cellarium

**A glass box over whole-cell reasoning.** Ask a question about *E. coli*; a Socratic Council frames it into a
**falsifiable hypothesis — blind to the data**; then a grounded agent, *Cellwright*, tests it against **real
whole-cell simulations** and the **published literature**, and closes the loop by proposing experiments for
your approval. Every number rides with its provenance. The agent never launches a run on its own.

> Built for **Built with Claude: Life Sciences** (Builder track). Cellarium's own code is MIT; the whole-cell
> model it runs on is obtained separately under Stanford's academic license (see [License](#license)).

Whole-cell models compute the *dynamic, regulatory, single-cell* behaviour of a living cell from first
principles — the regime that steady-state flux-balance analysis and human intuition can't reach. But they are
locked behind deep expertise, a heavy compute stack, and long run times. Cellarium is a small agentic
workbench that lets a scientist ask a question in plain English and get back a **grounded** answer — every
number tied to real simulation output, never fabricated.

It works in **two stages**, split along the classic philosophy-of-science line between *how you arrive at a
hypothesis* and *how you test it*:

1. **The Socratic Council** (upstream) turns a vague question into a single **falsifiable, operationalized,
   instrument-testable hypothesis** — see [the section below](#the-socratic-council--from-a-vague-question-to-a-falsifiable-hypothesis).
2. **The grounded agent** (downstream) tests that hypothesis against the simulation, with every number tied to
   real output and two guardrails that make the answer *trustworthy*:
   - **Feasibility / validation-envelope check** — refuses experiments the model was never built or validated
     to simulate (e.g. a mid-run carbon-source switch), and says why.
   - **Output QC** — inspects each simulated generation and withholds any degenerate / non-viable result
     instead of laundering it into a clean-looking number.

## What makes it more than a chatbot

- **Blind hypothesis generation (the control).** Before any data is read, a Socratic Council — *Proposer →
  Skeptic → Judge* — operationalizes the question into a falsifiable hypothesis with a single decisive test and
  its rival-excluding controls. It sees only the instrument's *capabilities*, never a corpus reading. That
  blindness is the scientific control: the test is a genuine prediction, not a story fit to the answer.
- **Grounded answers.** Cellwright answers strictly from real simulation runs via ~30 tools; it cannot state a
  number it did not read from a tool result, and it cannot launch a simulation.
- **Honest about the model's own limits.** It reconciles simulation against the literature (PubMed, OpenAlex,
  bioRxiv …) and *flags where the model is wrong* — e.g. an essential gene the metabolic solver reroutes around
  and wrongly calls viable — rather than papering over the disagreement. Finding the model's limits is the point.
- **Human-in-the-loop, biosecurity-gated.** New experiments go to an approval airlock; a misuse screen gates
  every design. The agent proposes; a human runs.

## The Socratic Council — from a vague question to a falsifiable hypothesis

*Full design and rationale: [docs/SOCRATIC_COUNCIL.md](docs/SOCRATIC_COUNCIL.md); evaluation:
[docs/SOCRATIC_COUNCIL_EVAL_REPORT.md](docs/SOCRATIC_COUNCIL_EVAL_REPORT.md) and [paper/](paper/).*

### The problem

A scientist arrives with a question like *"do genetically identical cells behave differently?"* — which names
**no observable, no baseline, no prediction, and no result that would refute it.** Turning that into a testable
claim is the step philosophy of science calls **operationalization** (Bridgman 1927; Hempel 1954), and it is exactly the step
current "AI scientist" systems skip: they treat hypothesis formulation as a single generative prompt and
optimize for *novelty*, producing ideas that sound new but were never bound to any specific instrument. Our own
grounded agent is disciplined at *testing* — it surveys the corpus, seeks disconfirmation, runs a Welch t-test
— but handing it a raw, unrefined question leaves that translation implicit, and therefore done
unsystematically, smuggling in unexamined assumptions. We wanted a **cognitive architecture that performs the
operationalization stage explicitly**, under the norms of the philosophy of science, before any simulation runs.

### How it works

The Council is an upstream dialectic of three Claude roles, each a distinct move in the *context of discovery*
(Reichenbach 1938):

- **The Maieutic Proposer** (Socratic midwifery; Plato, *Theaetetus*) — performs **abduction** (Peirce 1903/1934):
  infers the best candidate explanation worth testing and operationalizes every construct onto a **real
  instrument observable**, with a Popperian falsifier (Popper 1959), rival hypotheses (Chamberlin's *multiple
  working hypotheses*; Chamberlin 1890), a discriminating control (Platt's *strong inference*; Platt 1964), and
  the auxiliary assumptions it rides on (the Duhem–Quine belt; Duhem 1906; Quine 1951). It moves the debate
  *toward commitment*.
- **The Elenctic Skeptic** (*Socratic ignorance* — "I know that I know nothing"; Plato, *Apology*; on the
  elenchus, Vlastos 1983) — **assumes nothing** and proposes nothing; it emits typed objections (*aporiai*):
  undefined terms, hidden auxiliaries, unfalsifiable
  formulations, conflated constructs, un-excluded rivals, and claims that **outrun what the instrument can
  measure.** It moves the debate *toward doubt*.
- **The Judge** — a **gate, not a "who won" scorer**. It terminates only when **both** an adequacy rubric
  (falsifiable ∧ specified ∧ operationalized ∧ discriminating ∧ feasible) **and** a convergence signal hold,
  enforced by a code-level **quota of doubt**: a hypothesis is not even *eligible* to converge until the
  skeptic has raised, and the proposer resolved, N genuinely distinct substantive objections. This defeats the
  two failure modes of agent debate — premature agreement (sycophancy) and *aporia* forever.

The output is a first-class **`Hypothesis`** object — H1/H0, construct→observable definitions, an **executable
falsifier** (a `disconfirm(target, reference, channel)` call spec), rivals, auxiliaries, and
envelope-checked candidate designs — handed to the grounded agent, which then does all the testing itself.

A load-bearing control is the **information quarantine**: the Council sees the instrument's *dial labels* (which
channels and perturbations exist) but **never its readings** (corpus values, the literature answer key). It is
enforced at the import level in `instrument.py`, so the Council must *derive* the hypothesis, not *recall* the
answer.

### The value

Evaluated on ten literature-grounded single-cell *E. coli* questions (Elowitz noise [Elowitz et al. 2002], the
ppGpp stringent response, Scott growth laws [Scott et al. 2010], Keio essentiality [Baba et al. 2006], diauxie
[Monod 1949]…), the honest result is nuanced and holds up under
adversarial checking:

- The dialectic does **not** change how testable a hypothesis *looks* — a coarse operationalization rubric
  saturates for every configuration. What it changes is **soundness**: a fresh, configuration-blind,
  cross-family auditor finds the full Council leaves **~20% fewer substantive methodological defects** than a
  single strong prompt or a critic-free ablation (paired one-sided Wilcoxon *p* = 0.001), with the largest gains
  on the hardest-to-operationalize questions — and the **elenctic skeptic is the active ingredient.**
- Because the falsifier is *executable*, the discovery→justification loop closes: the hypothesis carries a
  decision rule we can run against fresh simulations for a confirm/refute verdict.
- We keep the caveat in view: in blinded head-to-head *preference* against a single-shot agent, the two are
  roughly a wash (a 4/4/2 human pilot), and the Council's Socratic disposition makes it *concede* readily when a
  leaner operationalization is equipotent. The value is fewer hidden defects and a disciplined, auditable
  derivation — **not** a hypothesis that merely reads as more impressive.

## Why it's interesting

The differentiator is not "the AI answers the question" — a naive tool can print a number. It is that Cellarium
**imposes the scientific rigor a mechanistic model demands across both stages**: the Council makes the question
falsifiable and operational *before* it is tested, and the grounded agent enforces the validated envelope,
replication, and grounding *while* testing — **catching the failure modes a scientist would otherwise trust.**
That rigor layer is a specialization of the reviewer-agent pattern applied to systems-biology *modelling* — a
domain a scientific AI workbench does not yet cover.

## Architecture

Two layers — reasoning agents on top, the data + model substrate below. Full diagram:
[`docs/COUNCIL_VS_KDENSE.md`](docs/COUNCIL_VS_KDENSE.md) compares the Council to off-the-shelf reasoning skills.

```
① REASONING (Claude agents)
   Socratic Council (BLIND)         →  handoff  →   Cellwright (GROUNDED)      →  Launch airlock (HUMAN)
   gate · Proposer→Skeptic→Judge                    ~30 corpus tools                approval + biosecurity;
   · librarian (general biology)                    literature (use_skill/web_get)  the agent never launches
   sees dial_labels, never readings                 propose_experiments

② SUBSTRATE (data + model)
   Whole-cell E. coli (wcEcoli, Docker: FBA + txn + translation + replication + regulation)
        │ simOut indexed
   Corpus / manifest (DuckDB · Parquet: viability, channels, pathways, QC)  ⇄  Hugging Face dataset (raw simOut)
   Literature APIs (PubMed · OpenAlex · bioRxiv, via allow-listed web_get)
   SQLite (data/sessions.db): sessions (Cellwright) + council_runs (Council) — durable persistence
```

Key modules: `src/cellarium/council.py` (the Council + blindness invariant), `agent.py` (Cellwright),
`tools.py` (grounded tools), `skills.py` + `skills/vendor/k-dense/` (literature skills, MIT), `manifest.py` /
`store.py` (corpus), `instrument.py` (the capability view the Council sees), `launch.py` (the airlock).
`apps/server.py` serves the SPA; `apps/hypotheses.py` persists Council runs.

## Setup

```bash
python -m venv .venv && . .venv/Scripts/activate   # (or bin/activate on unix)
pip install -e .
cp .env.example .env      # add your ANTHROPIC_API_KEY
```

The question runs through the **Socratic Council** first (watch the proposer/skeptic/judge debate print, then
the operationalized hypothesis brief) and then the grounded agent. Tune the debate with `--rounds` / `--quota`,
or skip it entirely with `--no-council` to pass the raw question straight to the agent. Reproduce the Council
evaluation with `python evals/grade.py` (see [evals/README.md](evals/README.md)).

### Run the web app (the glass box)

```bash
ANTHROPIC_API_KEY=...  python apps/server.py      # -> http://127.0.0.1:8000
```

Two workspaces: **Investigations** (chat with Cellwright, grounded in the corpus) and **Hypotheses** (convene
the Socratic Council, then *Open in Cellwright*). The chat, corpus browser, and manifest reasoning work with
just the API key; deep species reads and running new sims also need Docker + the wcEcoli image
(`WCECOLI_DOCKER=wcecoli-sim:multiko`) — see **[docs/DOCKER_SETUP.md](docs/DOCKER_SETUP.md)** for the full
setup (clone the model, build the image, ParCa, smoke test). Conversations and deliberations persist locally
in SQLite (a fresh clone comes up pre-populated from the committed `data/sessions.seed.db`).

Or the CLI:

```bash
python -m cellarium.cli "Is the aaRS-KO survival spread a real charged-tRNA depletion difference, or a generation-depth artifact?"
```

## The dataset — "The Well, for the cell"

The raw whole-cell simOut is published as an open Hugging Face dataset
([`evanniko1/cellarium-corpus`](https://huggingface.co/datasets/evanniko1/cellarium-corpus)). The distilled
Parquet manifest ships in-repo for fast, download-free reasoning; `download_raw` pulls full-resolution
trajectories on demand. This turns expensive, expert-only whole-cell runs into a queryable public corpus.

## Scope, honesty & biosecurity

Cellarium's users are **hypothesis generators, not decision-makers**: the model's predictions are hypotheses,
and the tool prioritizes and explains experiments rather than certifying outcomes. It removes *computational*
expertise, not scientific judgement. Every new experiment is human-approved and biosecurity-screened; the agent
cannot run a simulation. Organism: *E. coli* K-12 MG1655 (a lab strain).

## License

**Cellarium's own code is MIT** — see [LICENSE](LICENSE). The whole-cell model it depends on is **not** MIT:
it is the [Covert-lab wcEcoli model](https://github.com/CovertLab/wcEcoli) under Stanford's academic
(non-commercial) license, obtained and run separately by the user — Cellarium bundles no model code or
model-derived data (see [docs/DECISIONS.md](docs/DECISIONS.md) D3). Vendored literature skills under
`skills/vendor/k-dense/` are MIT, from
[K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills) (attribution + license retained).

## References

The philosophy-of-science and key empirical works cited above (author–date). Machine-readable entries for the
paper are in [paper/references.bib](paper/references.bib).

- Baba, T., Ara, T., Hasegawa, M., et al. (2006). Construction of *Escherichia coli* K-12 in-frame, single-gene knockout mutants: the Keio collection. *Molecular Systems Biology* 2: 2006.0008.
- Bridgman, P. W. (1927). *The Logic of Modern Physics*. Macmillan.
- Chamberlin, T. C. (1890). The method of multiple working hypotheses. *Science* 15(366): 92–96.
- Duhem, P. (1906/1954). *The Aim and Structure of Physical Theory* (P. P. Wiener, trans.). Princeton University Press.
- Elowitz, M. B., Levine, A. J., Siggia, E. D., & Swain, P. S. (2002). Stochastic gene expression in a single cell. *Science* 297(5584): 1183–1186.
- Hempel, C. G. (1954). A logical appraisal of operationism. *The Scientific Monthly* 79: 215–220.
- Macklin, D. N., Ahn-Horst, T. A., Choi, H., et al. (2020). Simultaneous cross-evaluation of heterogeneous *E. coli* datasets via mechanistic simulation. *Science* 369(6502): eaav3751.
- Monod, J. (1949). The growth of bacterial cultures. *Annual Review of Microbiology* 3: 371–394.
- Peirce, C. S. (1903/1934). *Collected Papers of Charles Sanders Peirce*, vol. 5 (C. Hartshorne & P. Weiss, eds.). Harvard University Press. [Abduction: the 1903 Harvard Lectures on Pragmatism, delivered 1903, published 1934; CP 5.180–212.]
- Plato. *Apology* and *Theaetetus*. In *Complete Works* (J. M. Cooper, ed., 1997). Hackett.
- Platt, J. R. (1964). Strong inference. *Science* 146(3642): 347–353.
- Popper, K. R. (1959). *The Logic of Scientific Discovery*. Hutchinson.
- Quine, W. V. O. (1951). Two dogmas of empiricism. *The Philosophical Review* 60(1): 20–43.
- Reichenbach, H. (1938). *Experience and Prediction*. University of Chicago Press.
- Scott, M., Gunderson, C. W., Mateescu, E. M., Zhang, Z., & Hwa, T. (2010). Interdependence of cell growth and gene expression: origins and consequences. *Science* 330(6007): 1099–1102.
- Vlastos, G. (1983). The Socratic elenchus. *Oxford Studies in Ancient Philosophy* 1: 27–58.
