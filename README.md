# Cellarium

**A glass box over whole-cell reasoning.** Ask a question about *E. coli*; a **blind Socratic Council** frames it
into a **falsifiable hypothesis — without seeing the data**; then a grounded agent, **Cellwright**, tests it against
**real whole-cell simulations** and the **published literature**, and closes the loop by proposing experiments for
your approval. Every number rides with its provenance. The agent never launches a run on its own.

> Built for **Built with Claude: Life Sciences** (Builder track). Cellarium's own code is MIT; the whole-cell
> model it runs on is obtained separately under Stanford's academic license (see [License](#license)).

**Jump to:** [The problem](#the-problem) · [The two halves](#the-two-halves) · [Major results](#major-results) ·
[The interactive report](#the-interactive-report) · [The demo](#the-demo) · [Install & run](#install--run-the-three-tiers) ·
[Architecture](#architecture) · [License](#license)

---

## The problem

Whole-cell models compute the *dynamic, regulatory, single-cell* behaviour of a living cell from first
principles — the regime that steady-state flux-balance analysis and human intuition can't reach. But they are
locked behind deep expertise, a heavy compute stack, and long run times, and their output — a molecular movie of
tens of thousands of species at every timestep — is effectively a black box. Two things are hard: **framing a
question the model can actually answer**, and **trusting the answer** (grounding every number, and catching where
the model is wrong). Today's "AI scientist" systems optimize for novelty and rarely ground what they claim.
Cellarium is a small agentic workbench that imposes the scientific rigor a mechanistic model demands, across both
stages — so a scientist can ask in plain English and get back a **grounded, provenance-carrying** answer.

## The two halves

Cellarium splits the work along the classic philosophy-of-science line between *how you arrive at a hypothesis* and
*how you test it* — two named halves, each chosen for what it guards against.

### The Socratic Council — from a vague question to a falsifiable hypothesis

Named for the **Socratic method**: a *Proposer* advances a claim, a *Skeptic* attacks it, and a *Judge* distils a
single falsifiable hypothesis with a pre-registered falsifier — all **blind to the simulation data**. Framing the
test *before* seeing the numbers is the scientific control against hypothesising-after-results (HARKing). Full
design + evaluation: [docs/SOCRATIC_COUNCIL.md](docs/SOCRATIC_COUNCIL.md),
[docs/SOCRATIC_COUNCIL_EVAL_REPORT.md](docs/SOCRATIC_COUNCIL_EVAL_REPORT.md), and [paper/](paper/).

- **The Maieutic Proposer** (Socratic midwifery; Plato, *Theaetetus*) performs **abduction** (Peirce 1903/1934):
  the best candidate explanation, operationalized onto **real instrument observables**, with a Popperian falsifier
  (Popper 1959), rival hypotheses (Chamberlin 1890), a discriminating control (Platt 1964), and its auxiliary
  assumptions (the Duhem–Quine belt). It moves the debate *toward commitment*.
- **The Elenctic Skeptic** ("I know that I know nothing"; Plato, *Apology*; Vlastos 1983) assumes nothing and emits
  typed objections (*aporiai*): undefined terms, hidden auxiliaries, unfalsifiable formulations, un-excluded
  rivals, claims that outrun what the instrument can measure. It moves the debate *toward doubt*.
- **The Judge** is a **gate, not a "who won" scorer** — it converges only when an adequacy rubric *and* a
  code-level **quota of doubt** both hold (N genuinely distinct objections raised and resolved), defeating both
  premature agreement and *aporia* forever.

A load-bearing control is the **information quarantine**: the Council sees the instrument's *dial labels* (which
channels and perturbations exist) but **never its readings**, enforced at the import level in `instrument.py`, so it
must *derive* the hypothesis, not *recall* the answer. The output is a first-class **`Hypothesis`** object (H1/H0,
construct→observable definitions, an executable `disconfirm(...)` falsifier, rivals, auxiliaries) handed to
Cellwright.

### Cellwright — the grounded wright

**Cellwright** is a *wright* — a **maker, a craftsman**, as in ship-*wright*, play-*wright*, wheel-*wright* — one
who *works the cell*. It is the grounded half: it **asserts nothing from memory**, only through **38 tools** over
the corpus, the raw simulation traces, and the literature (statistics, differential expression, viability,
provenance, regulon and flux reads, PubMed/OpenAlex/bioRxiv retrieval). Two guardrails make its answers
trustworthy:

- **Feasibility / validation-envelope check** — it refuses experiments the model was never built or validated to
  simulate (e.g. a mid-run carbon-source switch) and says why.
- **Output QC + provenance** — it inspects each simulated generation, withholds degenerate/non-viable results
  instead of laundering them into a clean number, tags every design **in-sample** (fitted) vs **out-of-sample**
  (predicted), and picks the *matched* reference — so a claim can be audited, not taken on faith.

Cellwright **proposes** experiments to a human approval airlock and a biosecurity screen; **it never launches a
run**. Finding where the model is *wrong* — an "essential" gene the metabolic solver reroutes around and wrongly
calls viable — is treated as a result, not papered over.

### What makes it more than a chatbot

The differentiator is not "the AI answers the question" — a naive tool can print a number. It is that Cellarium
makes the question **falsifiable and operational *before* it is tested**, and enforces the validated envelope,
replication, and grounding *while* testing — **catching the failure modes a scientist would otherwise trust.**

## Major results

The full, citation-checked findings are in the [interactive report](#the-interactive-report). In brief, Cellarium
mapped — provenance-controlled — **where the whole-cell model predicts and where it breaks**:

- **Trust, out-of-sample.** On axes it was never fitted to, the model reproduces the physiology: the ppGpp
  *allocation optimum* (growth worst at both clamp extremes, Zhu & Dai 2019); the **nitrate respiratory hierarchy**
  — it *induces* the nitrate-respiration chain (nuo Complex I) **and** *represses* fermentation (frd/cyd), the
  full NarL switch, once the anaerobic shift is controlled (Goh 2005).
- **Boundaries, each traced to architecture.** The **stringent-response sensing is inverted** — RelA is modelled as
  expression-coupled, so amino-acid limitation *collapses* ppGpp instead of raising it (opposite of the A-site
  mechanism, Winther/Roghanian/Gerdes 2018). The TRN misses **specific inducible catabolic on-switches**
  (arabinose→araBAD, nitrate→narGHJI). The homeostatic FBA objective **under-calls essentiality** (fabI/murA/lpxC
  reroute to zero-flux viability).
- **The showcase — a clash that led somewhere.** Deleting rRNA operons makes ribosomes and growth fall *together*
  (the *numbers* axis) — the opposite of Scott's second law, where impairing ribosome *efficiency* makes a cell
  *over-build*. From that clash the agent reasoned, via a live literature search, to **growth-dependent,
  ribosome-limited antibiotic susceptibility** (Greulich–Scott 2015) and to a regime **never shown computationally
  in a whole-cell model** — one that needs a colony-scale simulator (Vivarium), opening an antibiotic-potency
  prediction. It also reproduces Condon's (1993) ppGpp-independent operon compensation.

Every finding is verified against the primary literature; the report grades honestly (some anomalies were
*not* forced into failures), and an unverifiable "Scott law" claim was pulled after checking the source.

## The interactive report

The complete write-up — the glass-box method, strengths, boundaries, the clash, a cumulative verdict ledger, and 11
verified references with DOIs — is a self-contained page at **[`docs/report/index.html`](docs/report/index.html)**.

- **View it:** open the file directly in a browser, or serve the repo (`python -m http.server` then open
  `/docs/report/index.html`).
- **Export:** it is a single self-contained HTML file (copy/share as-is); to make a **PDF**, open it in a browser
  and use *Print → Save as PDF*.

## The demo

A hands-free **~3-minute walkthrough** auto-plays for screen-recording once the app is running:

```
http://127.0.0.1:8000/?demo=1
```

It covers the problem, the Council→Cellwright loop, two worked investigations (the argS stringent-response
falsification in Council mode; the rRNA **numbers-vs-efficiency clash** in direct mode), the corpus, and the safety
airlock. Script: [docs/DEMO.md](docs/DEMO.md).

## Install & run (the three tiers)

Cellarium spawns in **tiers** — the bottom tier needs nothing but the repo. *(Verified by booting a fresh clone in
an isolated sandbox.)*

### Tier 0 — the repo alone (no credentials)

```bash
git clone https://github.com/evanniko1/cellarium && cd cellarium
python -m venv .venv && . .venv/Scripts/activate    # (or . .venv/bin/activate on macOS/Linux)
pip install -e .
python apps/server.py                                # -> http://127.0.0.1:8000
```

All runtime dependencies (Starlette, uvicorn, DuckDB, PyArrow, anthropic, numpy, pydantic) are declared in
`pyproject.toml`, so the install is self-contained (`huggingface_hub` is an optional extra used only by the
corpus-upload scripts). **With no API key at all**, the server boots and every read-only surface works: the
**corpus browser** over the committed DuckDB/Parquet manifest, and — because a fresh clone auto-bootstraps
`data/sessions.db` from the committed `data/sessions.seed.db` — the **43 recorded Cellwright investigations and 30
Socratic Council runs**, with their real reasoning and figures. So you can clone, launch, and actually *browse the
glass box* with zero credentials. Heavy imports (Council, agent, Docker) are lazy per-request, so the page never
500s on a missing key.

### Tier 1 — add an API key (the reasoning goes live)

```bash
cp .env.example .env        # add ANTHROPIC_API_KEY=sk-ant-...   (get one at https://console.anthropic.com)
python apps/server.py
```

Now **new Cellwright investigations** and **fresh Council deliberations** run live. Two workspaces: *Investigations*
(chat with Cellwright, grounded in the corpus) and *Hypotheses* (convene the Council, then *Open in Cellwright*).
Without the key the live endpoints degrade cleanly — `/api/investigate` streams a structured
`{"kind":"error","hint":"Live runs need ANTHROPIC_API_KEY set …"}` event and a normal completion, never a crash.

Or the CLI (same seam):

```bash
python -m cellarium.cli "Does an argS knockout raise or lower ppGpp versus wildtype?"   # add --no-council to skip the Council
```

### Tier 2 — add Docker + the wcEcoli model (deep reads + new simulations)

The last tier unlocks **per-species raw reads** and **running brand-new whole-cell simulations**. It is the only
part **not spawnable from the repo alone** — by design, Cellarium bundles **no model code or model-derived data**
for licensing reasons. Steps (full guide: **[docs/DOCKER_SETUP.md](docs/DOCKER_SETUP.md)**):

1. Install **Docker** — <https://docs.docker.com/get-started/>.
2. Clone the whole-cell model, **[Covert-lab wcEcoli](https://github.com/CovertLab/wcEcoli)** (Stanford academic,
   non-commercial license — you accept it by running it), and **build a local image** (`docker build -t
   wcecoli-sim -f docker/local/Dockerfile .`); calibrate once with ParCa; run the smoke test.
3. Point Cellarium at it: `WCECOLI_DOCKER=wcecoli-sim python apps/server.py`.

You usually don't need to *generate* — most deep-dive designs can be pulled from the open **Hugging Face dataset**
instead of re-run (see below); Docker/ParCa is only for designs not already in the corpus or on HF, and for the
reader backend behind gene-level tools. Deep-dive read path (pull raw + wire the reader): the
[Deep dives section of docs/DOCKER_SETUP.md](docs/DOCKER_SETUP.md).

## The dataset — "The Well, for the cell"

The raw whole-cell simOut is published as an open Hugging Face dataset
([`evanniko1/cellarium-corpus`](https://huggingface.co/datasets/evanniko1/cellarium-corpus), ~198 GB across 96 run
archives). The distilled Parquet manifest ships in-repo (~5 MB) for fast, download-free reasoning; `download_raw`
pulls full-resolution trajectories on demand — the shard for breadth, the corpus for depth. This turns expensive,
expert-only whole-cell runs into a queryable public corpus.

## Architecture

Two layers — reasoning agents on top, the data + model substrate below.
[`docs/COUNCIL_VS_KDENSE.md`](docs/COUNCIL_VS_KDENSE.md) compares the Council to off-the-shelf reasoning skills.

```
① REASONING (Claude agents)
   Socratic Council (BLIND)         →  handoff  →   Cellwright (GROUNDED)      →  Launch airlock (HUMAN)
   gate · Proposer→Skeptic→Judge                    38 corpus + literature tools    approval + biosecurity;
   sees dial_labels, never readings                 propose_experiments             the agent never launches

② SUBSTRATE (data + model)
   Whole-cell E. coli (wcEcoli, Docker: FBA + txn + translation + replication + regulation)
        │ simOut indexed
   Corpus / manifest (DuckDB · Parquet: viability, channels, pathways, QC)  ⇄  Hugging Face dataset (raw simOut)
   Literature APIs (PubMed · OpenAlex · bioRxiv, via allow-listed web_get)
   SQLite (data/sessions.db): sessions (Cellwright) + council_runs (Council) — durable, seed-bootstrapped
```

Key modules: `src/cellarium/council.py` (the Council + blindness invariant), `agent.py` (Cellwright), `tools.py`
(the 38 grounded tools), `skills.py` + `skills/vendor/k-dense/` (literature skills, MIT), `manifest.py` / `store.py`
(corpus), `instrument.py` (the capability view the Council sees), `launch.py` (the airlock). `apps/server.py` serves
the SPA; `apps/sessions.py` + `apps/hypotheses.py` persist Cellwright + Council runs.

## Scope, honesty & biosecurity

Cellarium's users are **hypothesis generators, not decision-makers**: the model's predictions are hypotheses, and
the tool prioritizes and explains experiments rather than certifying outcomes. It removes *computational* expertise,
not scientific judgement. Every new experiment is human-approved and biosecurity-screened; the agent cannot run a
simulation. Organism: *E. coli* K-12 MG1655 (a lab strain).

## License

**Cellarium's own code is MIT** — see [LICENSE](LICENSE). The whole-cell model it depends on is **not** MIT: it is
the [Covert-lab wcEcoli model](https://github.com/CovertLab/wcEcoli) under Stanford's academic (non-commercial)
license, obtained and run separately by the user — Cellarium bundles no model code or model-derived data (see
[docs/DECISIONS.md](docs/DECISIONS.md) D3). Vendored literature skills under `skills/vendor/k-dense/` are MIT, from
[K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills) (attribution + license
retained).

## References

Philosophy-of-science and key empirical works cited above (author–date); machine-readable entries for the paper are
in [paper/references.bib](paper/references.bib). The interactive report carries its own 11 verified,
DOI-linked sources for the results.

- Baba, T., Ara, T., Hasegawa, M., et al. (2006). Construction of *Escherichia coli* K-12 in-frame, single-gene knockout mutants: the Keio collection. *Molecular Systems Biology* 2: 2006.0008.
- Bridgman, P. W. (1927). *The Logic of Modern Physics*. Macmillan.
- Chamberlin, T. C. (1890). The method of multiple working hypotheses. *Science* 15(366): 92–96.
- Condon, C., French, S., Squires, C., & Squires, C. L. (1993). Depletion of functional ribosomal RNA operons in *E. coli* causes increased expression of the remaining intact copies. *EMBO J* 12(11): 4305–4315.
- Duhem, P. (1906/1954). *The Aim and Structure of Physical Theory* (P. P. Wiener, trans.). Princeton University Press.
- Elowitz, M. B., Levine, A. J., Siggia, E. D., & Swain, P. S. (2002). Stochastic gene expression in a single cell. *Science* 297(5584): 1183–1186.
- Goh, E.-B., Bledsoe, P. J., Chen, L.-L., Gyaneshwar, P., Stewart, V., & Igo, M. M. (2005). Hierarchical control of anaerobic gene expression in *Escherichia coli* K-12: the nitrate-responsive NarX-NarL system represses the fumarate-responsive DcuS-DcuR system. *Journal of Bacteriology* 187(14): 4890–4899.
- Greulich, P., Scott, M., Evans, M. R., & Allen, R. J. (2015). Growth-dependent bacterial susceptibility to ribosome-targeting antibiotics. *Molecular Systems Biology* 11(3): 796.
- Hempel, C. G. (1954). A logical appraisal of operationism. *The Scientific Monthly* 79: 215–220.
- Macklin, D. N., Ahn-Horst, T. A., Choi, H., et al. (2020). Simultaneous cross-evaluation of heterogeneous *E. coli* datasets via mechanistic simulation. *Science* 369(6502): eaav3751.
- Monod, J. (1949). The growth of bacterial cultures. *Annual Review of Microbiology* 3: 371–394.
- Peirce, C. S. (1903/1934). *Collected Papers*, vol. 5 (C. Hartshorne & P. Weiss, eds.). Harvard University Press. [Abduction: CP 5.180–212.]
- Plato. *Apology* and *Theaetetus*. In *Complete Works* (J. M. Cooper, ed., 1997). Hackett.
- Platt, J. R. (1964). Strong inference. *Science* 146(3642): 347–353.
- Popper, K. R. (1959). *The Logic of Scientific Discovery*. Hutchinson.
- Quine, W. V. O. (1951). Two dogmas of empiricism. *The Philosophical Review* 60(1): 20–43.
- Reichenbach, H. (1938). *Experience and Prediction*. University of Chicago Press.
- Scott, M., Gunderson, C. W., Mateescu, E. M., Zhang, Z., & Hwa, T. (2010). Interdependence of cell growth and gene expression: origins and consequences. *Science* 330(6007): 1099–1102.
- Vlastos, G. (1983). The Socratic elenchus. *Oxford Studies in Ancient Philosophy* 1: 27–58.
- Winther, K. S., Roghanian, M., & Gerdes, K. (2018). Activation of the stringent response by loading of RelA-tRNA complexes at the ribosomal A-site. *Molecular Cell* 70(1): 95–105.
- Zhu, M., & Dai, X. (2019). Growth suppression by altered (p)ppGpp levels results from non-optimal resource allocation in *Escherichia coli*. *Nucleic Acids Research* 47(9): 4684–4693.
