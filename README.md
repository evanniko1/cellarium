# Cellarium

**A glass box over whole-cell reasoning.** Ask a question about *E. coli*; a **blind Socratic Council** frames it
into a **falsifiable hypothesis — without seeing the data**; then a grounded agent, **Cellwright**, tests it against
**real whole-cell simulations** and the **published literature**, and closes the loop by proposing experiments for
your approval. Every number rides with its provenance. The agent never launches a run on its own.

> Cellarium's own code is MIT; the whole-cell model it runs on is obtained separately under Stanford's
> academic license (see [License](#license)).

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
[docs/SOCRATIC_COUNCIL_EVAL_REPORT.md](docs/SOCRATIC_COUNCIL_EVAL_REPORT.md).

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
who *works the cell*. It is the grounded half: it **asserts nothing from memory**, only through **71 tools** over
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

### A worked example — when the right answer is a refusal

Ask *"which leucine tRNA isoacceptor keeps its charge during leucine starvation?"* and the model's output looks
ready to answer. The `GrowthLimits` listener writes `fraction_trna_charged`, a column 86 entries wide, one per
tRNA gene, named down to `leuU-tRNA[c]`.

It is not ready. In the default steady-state mode those 86 entries carry at most 21 distinct values: charging is
solved once per amino-acid family and the result is broadcast across every gene in that family. The difference
between two leucine isoacceptors is therefore identically zero at every timestep and under every parameter
setting, and no amount of fitting can create it.

Cellarium checks this before anything runs. The capability registry is built from the model's source rather than
its column names, and it reports:

| elongation mode | resolves each tRNA? | couples starvation regulation? |
|---|---|---|
| `steady_state` (default) | no — 21 family values across 86 labels | yes, via RelA/SpoT ppGpp |
| `kinetic` | yes — 86 identities as 172 charged/uncharged pools | no |
| `coarse_kinetic` | does not solve charging; writes 86 zeros | no |

No mode holds both halves, so the query is refused with the missing mechanism named — instead of being answered
with a number that would look precise and mean nothing.

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
- **The showcase — a clash that led somewhere.** Cutting total rRNA synthesis capacity (to 74 / 46 / 16% of
  wild-type, by zeroing 2/4/6 of the seven operon rows) makes ribosomes and growth fall *together*
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

Either paste it into **Settings** (the gear in the top bar) — no terminal needed — or use a file:

```bash
cp .env.example .env        # add ANTHROPIC_API_KEY=sk-ant-...   (get one at https://console.anthropic.com)
python apps/server.py
```

The Settings panel stores the key in your **OS keychain** via the optional `keyring` extra
(`pip install -e ".[keyvault]"`). Precedence at startup is an exported shell variable, then a repo-root `.env`,
then the keychain. The key stays on your machine, is sent only to Anthropic's API, and **never enters the
assistant's context** — there is deliberately no tool through which Cellwright can read or change it.

Keychain persistence works on **Windows** (Credential Manager), **macOS** (Keychain), and a **Linux desktop**
with an unlocked GNOME/KDE keyring. On **headless Linux, SSH, systemd, Docker, WSL2 and BSD** there is no
reachable keychain, so the panel degrades honestly — the button reads *"Use for this session"*, a note explains
why, and the key lives in memory until you stop the server. Cellarium never writes a credential to disk in
plaintext and never silently downgrades a "saved to your keychain" promise into an unencrypted file; on those
platforms use a `.env`, which takes precedence anyway.

→ **[docs/CREDENTIALS.md](docs/CREDENTIALS.md)** is the full specification: the per-OS matrix (CI-enforced), the
four invariants, the three-layer guard on the credential endpoints, and the known per-platform quirks.

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
part **not spawnable from the repo alone**: you clone the model yourself and accept its licence.
Deeper guide (tuning, deep-dive reads, native fallback): **[docs/DOCKER_SETUP.md](docs/DOCKER_SETUP.md)**.

Stock wcEcoli is **not sufficient** — Cellarium needs the v3.0.1 kinetic tRNA-charging port, a 21-row condition
table, the `multi_gene_knockout` variant, and two fixes without which upstream's own image build fails today.
Those finished files live in **[`model_overlay/`](model_overlay/)** (45 files) and are copied onto a clean
checkout by `apply_model_overlay.py`, which verifies each target against a pinned upstream SHA256 first and
**stops rather than overwrite** a file upstream has since changed. See **[docs/OVERLAY.md](docs/OVERLAY.md)**.

Every command below was run end-to-end, in this order, against a **fresh `git clone` of the public repo** on
Windows 11 + Docker 29.4.2. Where a step has a trap, the trap is named — each one was hit for real.

**1. Install Docker** — <https://docs.docker.com/get-started/>. Budget ~30 GB disk and 8 GB RAM for Docker.

**2. Clone the model at the pinned commit — onto a BRANCH, not a detached HEAD.**

```bash
git clone https://github.com/CovertLab/wcEcoli        # Stanford academic, non-commercial licence
cd wcEcoli
git checkout -b cellarium-pin a4497e17                # a BRANCH at the pinned commit — see below
```

> **Why `-b`.** The plain `git checkout a4497e17` leaves a detached HEAD, and wcEcoli's own
> `cloud/locally-build-wcm.sh` runs `GIT_BRANCH=$(git symbolic-ref --short HEAD)` under `set -eu` — which exits
> 128 on a detached HEAD and aborts the build. Creating a branch at the same commit costs nothing and removes it.

**3. Apply the overlay** — from the **Cellarium** repo root:

```bash
python scripts/apply_model_overlay.py --wcecoli ../wcEcoli --check   # verify, writes nothing
python scripts/apply_model_overlay.py --wcecoli ../wcEcoli
```

Expected on a clean `a4497e17`: `45 shipped, 0 blocked` then `31 to replace, 14 to create, 0 problems`. Re-running
is idempotent (`0 to replace, 0 to create, 45 already applied, 0 problems`). If it refuses with `!! STALE`, upstream changed a file the
overlay ships — read [docs/OVERLAY.md](docs/OVERLAY.md) before reaching for `--force`.

**4. Build the image** — from the **wcEcoli** root. First build is slow (~15–30 min; it compiles OpenBLAS-free
numpy/scipy wheels, the Cython extensions and the model):

```bash
export USER=${USER:-$USERNAME}             # Git Bash on Windows leaves $USER EMPTY — see below
cloud/build-containers-locally.sh          # builds ${USER}-wcm-runtime, then ${USER}-wcm-code
docker image inspect "${USER}-wcm-code" > /dev/null && echo "image OK"
```

> **Why `export USER`.** Both build scripts name their images `${USER}-wcm-runtime` / `${USER}-wcm-code`. In Git
> Bash on Windows `$USER` is unset (`$USERNAME` holds the login name), so the tag degenerates to `-wcm-runtime`
> and `docker build -t` reads the leading dash as a flag.
>
> **Apply the overlay BEFORE building.** The image bakes the model in at `/wcEcoli` and compiles
> `_trna_charging.pyx` during the build via the `setup.py` the overlay installs. Build first and you get an image
> running stock code that *looks* fine.
>
> **Two upstream dependencies have bit-rotted, and the overlay fixes both.** Measured on a clean `a4497e17`:
> `Equation==1.2.1`'s sdist downloads a setuptools from a `pypi.python.org` path that now returns HTML
> (`zipfile.BadZipFile`), and `stochastic-arrow==1.0.0` imports numpy at build time with no build-requires, so
> PEP 517 isolation hides it (`ModuleNotFoundError: No module named 'numpy'`). Either one stops the build dead.
> The overlay ships `cloud/docker/runtime/Dockerfile` with four added `pip` lines and no other change; the
> reasoning is in the file's own banner.

**5. Verify the overlaid checkout before you trust a run** — from the **Cellarium** root:

```bash
python scripts/verify_overlay_route1.py  --tree ../wcEcoli   # kinetic model present, isoacceptor code gone
python scripts/verify_overlay_variants.py --tree ../wcEcoli   # single / graded / multi KO ship AND register
```

Both must exit `0`. The second one runs the shipped `multi_gene_knockout` against a recording stub, replays
Cellarium's own launch argv through runSim's real parser, and checks that the multi-KO gene set survives all four
files it has to cross. Both have working negative controls: run either against a bare, un-overlaid checkout and
they exit `1` (24 named failures for the variants check).

Then confirm the *image* — this is the check that the Cython extension compiled and that eager variant
registration did not blow up:

```bash
docker run --rm "${USER}-wcm-code" bash -lc 'cd /wcEcoli
  python -c "import wholecell.utils._trna_charging; print(\"cython OK\")"
  python -c "import models.ecoli.sim.variants as V; print([n for n in (\"gene_knockout\",\"graded_gene_knockout\",\"multi_gene_knockout\") if n in V.nameToFunctionMapping])"
  python -c "from wholecell.sim.simulation import resolve_elongation_flags as r; print(r(False,False,True,False,True)[\"elongation_model\"])"
  python runscripts/manual/runSim.py --help | grep -E "multi-ko-indices|kinetic-trna-charging"'
```

Expected: `cython OK`, all three knockout variants listed, `KineticTrnaChargingModel`, and the two flags present.
`import models.ecoli.sim.variants` is the strict test — registration is eager, so a registered variant with a
missing module raises there rather than at run time.

**6. Point Cellarium at it.**

```bash
export WCECOLI_DOCKER=${USER}-wcm-code:latest    # name the BUILD; see .env.example if you set it there instead
python apps/server.py
```

Then calibrate once with ParCa and run the smoke test — [docs/DOCKER_SETUP.md](docs/DOCKER_SETUP.md) §5–§6.

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
   gate · Proposer→Skeptic→Judge                    71 corpus + literature tools    approval + biosecurity;
   sees dial_labels, never readings                 propose_experiments             the agent never launches
                                                    propose_rebuild (ParCa)         — sims OR the fit

② SUBSTRATE (data + model)
   Whole-cell E. coli (wcEcoli, Docker: FBA + txn + translation + replication + regulation)
        │ simOut indexed
   Corpus / manifest (DuckDB · Parquet: viability, channels, pathways, QC)  ⇄  Hugging Face dataset (raw simOut)
   Literature APIs (PubMed · OpenAlex · bioRxiv, via allow-listed web_get)
   SQLite (data/sessions.db): sessions (Cellwright) + council_runs (Council) — durable, seed-bootstrapped
```

Key modules: `src/cellarium/council.py` (the Council + blindness invariant), `agent.py` (Cellwright), `tools.py`
(the 71 grounded tools), `skills.py` + `skills/vendor/k-dense/` (literature skills, MIT), `manifest.py` / `store.py`
(corpus), `instrument.py` (the capability view the Council sees), `launch.py` (the airlock). `apps/server.py` serves
the SPA; `apps/sessions.py` + `apps/hypotheses.py` persist Cellwright + Council runs.

## Reading the corpus

Every row carries a `qc` value and an ARM. Two reference pages before you interpret any number:

- **[docs/QC_STATUSES.md](docs/QC_STATUSES.md)** — what each `qc` value means, and the rule that decides how
  to read one: for a continuous reading anything but `ok` is evidence-ABSENT, but for a viability question a
  failure IS the readout.
- **[docs/CORPUS_ARMS.md](docs/CORPUS_ARMS.md)** — the arms (`kb_sha256` + `operons` + `elongation_model`) and
  the three elongation models. Rows from different arms are not poolable. Generated, never hand-edited.

## Known limitations

Reported here because a user should meet them before a result does, not after. Each row points at the backlog
entry that carries the evidence and the next action — the numbers are not restated twice.

**1. The steady-state charging LEVEL is outside every measurement, and the kinetic spread is unvalidated.**
Like-for-like at identical state, the two elongation models give aggregate tRNA charging **0.9795 (steady-state)
vs 0.8295 (kinetic)**. Avcilar-Kucukgoze et al. 2016 (*NAR* 44(17):8324) measure 50–60% in essentially our basal
condition, and Choi & Covert's own published aggregate is **78.8%** — so the steady-state figure is outside the
measured band entirely and the kinetic one sits four points high. Separately, our kinetic within-family spread
(**LEU 0.25, GLY 0.32**) is about twice the widest published spread (0.16, Dittmar et al. 2005). *The capability
is real; the magnitudes are not validated.* → [`BACKLOG.md` EXT-PORT-12](BACKLOG.md) (open).

**2. The kinetic model's parameters are not identified against this knowledge base.** The shipped `K_T` values
were optimised against tRNA abundances this KB no longer carries — `trpT` was assumed at 3.68 µM and this KB has
1.10 µM, a **3.3× shortfall** — and because `K_T` (8.75 µM) already exceeds the pool, charging is first-order in
abundance and the error passes straight through to the output. No ppGpp refit should be attempted before that is
closed. → [`BACKLOG.md` EXT-PORT-13](BACKLOG.md) (open, next action), and EXT-4 behind it.

**3. Codon identity does not reach the elongation rate in any run that exists.** The codon × anticodon reading
matrix and its consumer are both in the checkout, but only the **kinetic** path elongates by codon; under
**steady_state** and **coarse_kinetic** elongation draws from per-amino-acid pools and codon identity has no
effect on rate. Every row in the shipped corpus is `steady_state`. The same asymmetry governs charging: under
steady_state one per-amino-acid scalar is broadcast across all 86 isoacceptor columns, so within-family spread is
**0.00 by construction, not by measurement**; under coarse_kinetic those columns are **exact zeros**, which is the
absence of a model rather than total de-acylation. Any codon-usage or codon-bias claim from a corpus row would be
inferred from sequence, not simulated. `model_capabilities` refuses these rather than returning a number — that
refusal machinery exists *because* we once published the 0.00 as a result.
→ [`src/cellarium/capability.py`](src/cellarium/capability.py) (`codon_level_elongation`,
`per_isoacceptor_trna_charging`) and [`BACKLOG.md` SCI-TRNA-1 / SCI-TRNA-5](BACKLOG.md).

**4. Some corpus rows are not reproducible from a fresh build, and some are thinner than the manifest suggests.**
The corpus's cached knowledge base does **not** rebuild bit-identically from the current model image: exactly 1 of
67 conditions differs (`minus_phosphate`), and a run added to the corpus today would silently use a different fit
for it. The blast radius is bounded and stated — all four `minus_phosphate` runs are `qc=crashed`, **0 reportable**
— so no published result rests on it, but *reproducibility of the published dataset depends on closing it*.
Separately, the aaRS panel lists 4 seeds each for argS/pheS/alaS/lysS/gltX and only seed 0 is on disk, so
`KO:lysS` is **n=1**. → [`BACKLOG.md` WELL-KBDRIFT-1](BACKLOG.md) (open) and
[`BACKLOG.md` SCI-TRNA-2](BACKLOG.md) (open).

**5. A `gene_knockout` is an operon knockout.** Under operons-ON — the model's default and the configuration all
322 corpus rows were built in — `gene_knockout` zeroes one *transcription unit*. Measured: `KO:rpoB` leaves rpoB
expressed, `KO:rpmJ` silences `secY`, `KO:flgB` deletes nine flagellar genes. Cellarium's `graded_gene_knockout`
variant fixes the first two classes; nothing fixes the third short of a different knowledge base. The agent tool
`operon_mode_advice` returns this decision with its citations and its gaps.
→ [`docs/KNOCKOUT_SEMANTICS.md`](docs/KNOCKOUT_SEMANTICS.md), [`BACKLOG.md` OPERONS-1 / OPERONS-3](BACKLOG.md).

**6. Upstream's own container build is broken today, and the overlay is what fixes it.** Two dependencies pinned
in wcEcoli's `requirements.txt` have bit-rotted (`Equation`, `stochastic-arrow`); a clean `a4497e17` checkout
cannot build its image without the overlay's `cloud/docker/runtime/Dockerfile`. That means **the model half of
this project is only reproducible through Cellarium's overlay right now**, which is a dependency worth stating
plainly rather than discovering. → [`docs/OVERLAY.md`](docs/OVERLAY.md).

## Scope, honesty & biosecurity

Cellarium's users are **hypothesis generators, not decision-makers**: the model's predictions are hypotheses, and
the tool prioritizes and explains experiments rather than certifying outcomes. It removes *computational* expertise,
not scientific judgement. Every new experiment is human-approved and biosecurity-screened; the agent cannot run a
simulation. Organism: *E. coli* K-12 MG1655 (a lab strain).

## License

**Cellarium's own code is MIT** — see [LICENSE](LICENSE). The whole-cell model it depends on is **not** MIT: it is
the [Covert-lab wcEcoli model](https://github.com/CovertLab/wcEcoli) under Stanford's academic (non-commercial)
license, obtained and run separately by the user (see [docs/DECISIONS.md](docs/DECISIONS.md) D3). Cellarium ships
**no model image and no model-derived data**, but it does redistribute 45 **model source files** under
[`model_overlay/`](model_overlay/) — the changes without which its designs cannot run. Most derive from
CovertLab/WholeCellEcoliRelease **v3.0.1** (Choi & Covert 2023, *NAR* 51(12):5911, doi:10.1093/nar/gkad435),
redistributed **with Prof. Covert's permission** under the same non-commercial terms; the rest are Cellarium's own
condition/media/variant definitions. Provenance and per-file licence: `model_overlay/MANIFEST.json`.
Vendored literature skills under `skills/vendor/k-dense/` are MIT, from
[K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills) (attribution + license
retained).

## References

Philosophy-of-science and key empirical works cited above (author–date). The interactive report carries its own
11 verified, DOI-linked sources for the results.

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
