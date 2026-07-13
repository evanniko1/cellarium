# Cellarium

**A Claude-backed copilot for reasoning over a whole-cell *E. coli* simulation — grounded, and honest about its own limits.**

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

Built for *Built with Claude: Life Sciences* (Builder track). This is a fresh, from-scratch implementation.
It runs on the [Covert-lab whole-cell *E. coli* model](https://github.com/CovertLab/wcEcoli) as an external
backend, which **you obtain separately** under its **Stanford Academic Software License** (non-commercial;
redistribution requires Stanford's written permission). **Cellarium bundles none of that model** — it is the
new agent + guardrail + interface layer, and points at your own licensed checkout. See
[docs/DECISIONS.md](docs/DECISIONS.md) D3 for the licensing/data-distribution constraints.

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

## Architecture (minimal vertical slice)

```
src/cellarium/
  council.py     the Socratic Council: proposer/skeptic/judge debate loop   (discovery stage)
  hypothesis.py  first-class Hypothesis type (H1/H0, operational defs, executable falsifier, rivals)
  instrument.py  "dial labels" adapter — the quarantine boundary (capabilities, never readings)
  envelope.py    validated-perturbation envelope check    (feasibility guardrail)
  qc.py          per-generation output QC                  (integrity guardrail)
  model.py       thin backend adapter (cached + live hook to the public wcEcoli model)
  tools.py       grounded read tools exposed to the agent
  agent.py       Claude (Anthropic Messages API) tool-using loop  (justification stage)
  cli.py         run a question end-to-end (Council -> agent)
evals/           literature-grounded Council evaluation harness + results
paper/           the Socratic Council paper (build + figures)
ui/index.html    Claude-Science-style demo interface
data/cache/      cached demo simulation results (reproducible, fast)
docs/DEMO.md     the demo script
```

## Setup

```bash
python -m venv .venv && . .venv/Scripts/activate   # (or bin/activate on unix)
pip install -e .
cp .env.example .env      # add your ANTHROPIC_API_KEY
python -m cellarium.cli "Do genetically identical E. coli cells behave differently, and why?"
```

The question runs through the **Socratic Council** first (watch the proposer/skeptic/judge debate print, then
the operationalized hypothesis brief) and then the grounded agent. Tune the debate with `--rounds` / `--quota`,
or skip it entirely with `--no-council` to pass the raw question straight to the agent. Reproduce the Council
evaluation with `python evals/grade.py` (see [evals/README.md](evals/README.md)).

Open `ui/index.html` in a browser for the interface mockup.

## Scope & honesty

Cellarium's users are **hypothesis generators, not decision-makers**: the model's predictions are hypotheses,
and the tool prioritizes and explains experiments rather than certifying outcomes. It removes
*computational* expertise, not scientific judgement. Organism: *E. coli* K-12 MG1655 (a lab strain).

## License

**Cellarium's own code is MIT** — see [LICENSE](LICENSE). The whole-cell model it depends on is **not**
MIT: it is under Stanford's academic (non-commercial) license and is obtained/run separately by the user.
Cellarium redistributes no model code or model-derived data. See [docs/DECISIONS.md](docs/DECISIONS.md) D3.

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
