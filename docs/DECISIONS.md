# Deferred decisions

Design choices intentionally postponed. Revisit when noted.

## D1 — HuggingFace-mediated sharing of full `simOut` (deferred)
**Context.** The shared corpus manifest (Parquet shards + DuckDB) aggregates *summary + QC + a curated
species panel* across contributors (Evangelos, and possibly Filippo). But **full `simOut`** (all ~12,000
count series + ~9,600 fluxes per trajectory) lives on the machine that generated it — too large to sync
between laptops via git. So `read_species` gives full time-series depth only for **locally-available**
trajectories.

**Deferred decision.** How to mediate cross-contributor access to full `simOut` — most likely a
**HuggingFace dataset** (or object store) holding full tensors for a curated subset of trajectories, so
either contributor can deep-query the other's runs. Decide: which subset, tensor format, upload cadence.

**Why it matters beyond this repo.** This is the sharding + full-tensor packaging problem any large
public simulation dataset has to solve, so whatever we choose here should carry: reproducible shards,
checksummed manifests, leakage-free splits.

## D3 — Model licensing & data distribution (constraint, not deferred)
The whole-cell *E. coli* model is under the **Stanford Academic Software License (Docket S18-475)** —
**not** open source: non-commercial academic use only; the Software and its derivatives may not be
redistributed without Stanford's written permission (§§5, 6, 8, 11). Consequences for Cellarium:
- **Do** use it for non-commercial academic research (running sims locally) and **do** publish results
  (papers/figures + the data behind them) *with acknowledgment* (§12 anticipates this) — low risk.
- **Do NOT** bundle/vendor/redistribute the model. Cellarium points at a user-obtained checkout; any Docker
  image is built locally from that checkout and **never published**.
- **Distributing a large standalone simulation dataset publicly** is the one
  action that **requires Stanford's written permission** — the license's own mechanism. This is a
  grant/dataset-level action, **not a hackathon blocker** (the hackathon submits code + a local demo; the
  corpus stays local). Track alongside D1. (Not legal advice.)

## D2 — Curated species panel for the manifest (deferred)
The manifest stores summary stats for a curated panel of high-interest species (TFs, key enzymes,
ribosomes, ppGpp, stress/AMR set). **Contents deferred until we have real simulation results** to see which
species carry signal. For now the manifest records the standard channels + provenance + QC only; the panel
is a config list, initially minimal.

## D4 — Gene-specific essentiality axis (deferred; the KO/objective problem)
**The full problem we uncovered.** The whole-cell model does not yield a clean single-gene-KO phenotype, and
we traced *why* to the objective, not to any bug. In order of depth:
- The `gene_knockout` variant is an **expression** knockout (`sim_data.adjust_final_expression([i], [0])`) —
  it zeroes transcription. Since initial counts derive from expression, the enzyme is **0 from gen-0** (verified
  empirically: fabI/glmS/gltX monomers read 0 at the first timestep), so there is **no protein-dilution confound**
  — metabolic KO viability is the pure reroute. What *does* carry over is inherited downstream state: daughters
  `loadSnapshot` the parent's partitioned pools (they don't re-init at full value), so metabolite/charged-tRNA
  buffers halve per division — which is what lets gltX limp ~3 generations before its charged-Glu-tRNA depletes.
- The metabolism FBA runs `objectiveType = "homeostatic_kinetics_mixed"`: minimize *deviation* from metabolite
  concentration target *ranges* + kinetic flux targets (both soft). **There is no growth/biomass-maximization
  term** — the biomass reaction in `modular_fba.py` is only wired for `objectiveType == "standard"`, which the
  whole-cell metabolism never uses. So a KO **has nothing to degrade**: the solver only needs to keep pools in
  range, and rerouting achieves that. This is the root cause of both the empirical reroute (metabolism 5/5: no
  effect) *and* the 0/35 under-sensitivity of the FBA single-deletion screen (it read `obj0 − obj` on a
  deviation objective that stays ≈satisfiable by construction). Even a *hard* reaction bound (a true
  stoichiometric deletion, which the screen did apply) reroutes — so the perturbation was never the problem;
  **the objective + readout is.**
- Essential **machinery** (ribosome/RNAP/replisome/aaRS) is outside metabolism; its KO doesn't degrade
  gracefully — the sim **crashes** (gltX 4/4: ribosome_conc 21→2.15, NegativeCountsError in
  PolypeptideElongation). No metabolic FBA can speak to machinery essentiality.
- **The only clean, measurable phenotypes come from GRADED capacity perturbations** (`rrna_operon_knockout`,
  `ppgpp_conc`) — which is what the model, and the Covert team's own variant-analysis tooling, are built for.

**Can we change the objective?** In the running sim: mechanically yes (six objective types exist), but the
homeostatic objective is the load-bearing whole-cell design choice — metabolite demand is set dynamically by
the other submodels each timestep, so a fixed biomass vector would *decouple* metabolism from the cell and
invalidate the ParCa fit + tuned `kinetic_objective_weight`. **Don't.** The only legitimately exposed objective
levers are the *weights* (`kinetic_objective_weight`, `secretion_penalty_coeff`).

**Deferred instrument — `fba_essentiality` v2 (tier-2).** The correct place to change the objective is a
*separate, offline* screen, never the sim. Build a biomass/feasibility FBA on `sim_data`'s metabolic
stoichiometry: promote the ~173 homeostatic concentration targets from soft "minimize deviation" to **hard
production demands**, remove a gene's reactions, and test **feasibility** (infeasible ⇒ essential). This is the
corrected form of `mode_fba_essentiality` — the deletion loop already exists; what changes is hard-demand
constraints + a feasibility test instead of reading the soft objective delta. Calibrate against a Keio/Joyce-
style benchmark. **Scope caveat:** covers *metabolic* essentiality only; machinery essentiality (gltX-type) is
invisible to any metabolic FBA and remains a crash, not a verdict.

### D4-lit — what the literature says (2026-07-10 pass of the Covert-lab publications + adjacent WCM work)
The literature both **validates our characterization** and **redirects the instrument** — three findings change the plan:

- **The aaRS/machinery crash is documented model behavior, with a mechanism.** Choi & Covert 2023 (NAR,
  doi:10.1093/nar/gkad435) added a mechanistic aaRS-charging/elongation model to wcEcoli and found in vitro aaRS
  kcats are *insufficient to sustain the proteome* — they had to fit aaRS kcats **7.6× above** in vitro to grow,
  and perturbing aaRS activity gives *"catastrophic impacts on cellular phenotypes"* (e.g. insufficient ArgRS
  collapses arginine biosynthesis via a CGG-codon feedback). So aaRS charging runs near a cliff by construction:
  a full aaRS KO (gltX) is the extreme of that perturbation → the ribosome-collapse crash we saw is the *expected*
  all-or-nothing failure of translation machinery, not an artifact. This is the published backing for the
  `lethal_crash` regime.
- **The right KO readout is VIABILITY (does the cell divide?), not graded growth.** Gherman et al. 2025 (Cell
  Systems, doi:10.1016/j.cels.2025.101392) design *reduced E. coli genomes* with a WCM by asking whether each
  deletion set still permits **cell division** — a binary viability call — and train an **ML surrogate** on WCM
  runs to predict division at **95% less compute**, removing 40% of modeled genes in silico. Lesson for us: stop
  reading graded growth-rate (which reroutes to no-effect); read **division/viability**, which is where a lethal
  KO actually shows up. And a surrogate-for-viability is exactly the "reason over the model at scale" primitive.
- **A metabolic-essentiality oracle already exists — don't rebuild it.** The EcoCyc 2025 release (EcoSal Plus,
  doi:10.1128/ecosalplus.esp-0019-2024; co-authored by the wcEcoli team) ships a steady-state metabolic flux
  model that **predicts growth rates for gene knockouts** plus curated **gene-essentiality** annotations. So the
  D4 tier-2 tool should *benchmark against / defer to EcoCyc* for metabolic essentiality rather than reimplement a
  biomass FBA, and reserve the WCM for the dynamic/viability phenotypes it is uniquely good at. (Objective lineage:
  the homeostatic/dynamic objective descends from Birch, Udell & Covert 2014, "Incorporation of flexible objectives
  and time-linked simulation with FBA," doi:10.1016/j.jtbi.2013.11.028 — a deliberate research choice, not a default.)

**Revised direction for a "valuable set of simulations":** (1) switch the KO/perturbation readout to **viability +
division success**, not growth-rate deltas; (2) prefer **graded-capacity** (rRNA operons, ppGpp, kinetic-weight)
and **multi-gene reduced-genome** designs over single metabolic KOs; (3) treat aaRS/ribosome/RNAP KOs as
**crash-predicted** (scope.py already warns); (4) for a metabolic essentiality *verdict*, call EcoCyc's flux model
as the oracle; (5) longer term, an **ML surrogate** trained on our corpus to predict division = scale primitive.

## D5 — Two entrypoints into one agent; the Council never reads (orchestrate.py)
Cellarium exposes ONE grounded agent behind TWO entrypoints — `src/cellarium/orchestrate.py::investigate`, the
single seam the CLI and the hackathon interface both call:
- **Top (council-first, `use_council=True`):** the Socratic Council operationalizes an open question into a
  falsifiable Hypothesis, then hands that brief to the agent.
- **Direct (Cellarium-first, `use_council=False`):** the raw question goes straight to the agent — for targeted
  read/analysis and the bottom-up, tool-refinement loop where you already know what to measure.

**Invariant — reads are NEVER routed through the Council, by construction (not policy).** `instrument.py` (the
only view the Council sees) is quarantined from every result-bearing surface — `test_council.py`'s
`test_instrument_imports_no_result_bearing_modules` forbids importing survey/differential/scope/store. So the
Council can only shape the QUESTION; the agent always does the reading, in every flow. "Does analysis have to go
through the Council?" is therefore answered **No** — it is architecturally impossible for it to.

**Launching sims is a SEPARATE action with downstream, orthogonal gating.** Two paths coexist over the same
capability; which one is used is independent of the entrypoint:
- **Gated (agent-facing; default for the interface):** `launch.propose` (the `propose_experiment` tool) queues a
  vetted design PENDING; a human calls `launch.approve_and_run` (NOT an agent tool). Coli can never launch
  autonomously — the queue is the airlock.
- **Ungated (operator/eval; `model.run_live` + `evals/loop_live`):** runs a design immediately for tool-refinement
  and live eval loops. Still enforces envelope + biosecurity feasibility via `runner.run_one`, but skips the human
  approval step — appropriate because a developer invokes it directly.

The gate is thus a policy on the launch action, not on the question entrypoint. Reads are never gated; launches
may be. (Open reconciliation for a later pass: whether `loop_live` should optionally route through the gate.)

## D6 — Exposing the corpus to third-party agents: MCP surface shape (DECIDED — sub-agent behind a single tool)

*Extended 2026-08-03 with **D6a** (Surface A — Cellarium-as-is, assessed against the blindness invariant) and
**D6b** (Surface B — a data-only MCP over the HF corpus). The 2026-07 decision below is unchanged.*

**Decision: one MCP tool that runs Cellwright locally, BYOK.** Superseded an earlier three-tier draft whose
Tier-1 write-up quietly assumed a hosted, always-on server. It should not have — **a central always-on session
is not in this project's deliverables**, and assuming one produced a design that answered the wrong question
(*"whose API key pays?"*) instead of the right one (*"how does a user point their own agent at their own
corpus?"*).

**The actual shape.** The corpus ships on HuggingFace; the `cellarium` package ships alongside it. A user
downloads all or part of the corpus, installs the package, and then reaches it three ways over the *same*
local seam (`orchestrate.investigate`, see **D5**): the web UI, the CLI, or **their own agent(s) over MCP**.
The MCP server is spawned by the user's client over **stdio** — a local subprocess, not a network service.
Consequences that fall out of that and simplify everything:

- **BYOK by construction.** The key is the user's, already handled by the local credential vault
  (`docs/CREDENTIALS.md`) — OS keychain, never leaves the machine, never enters the model's context. The
  earlier draft reached for **MCP sampling** to solve "whose key pays"; with a local server that problem does
  not exist. Sampling stays *optional*, for a client that would rather supply the model itself.
- **No auth, no multi-tenancy, no hosting.** stdio has no network surface, so the loopback/CSRF machinery the
  web app needs has no analogue here and none is required.
- **Multiple agents, one corpus.** Several clients can each spawn their own server against the same local
  corpus; the manifest is read-only, so concurrency is not a concern.

**What is exposed: one listed tool.** `ask_cellwright(question)` runs the full loop — Cellwright's system
prompt, its tool discipline, its trust strip — and returns the grounded answer plus the run ids behind it. The
caller's agent sees ONE tool, not fifty-seven. The reason is not tidiness: **the rigor lives in the system
prompt, not in the tools** (survey-first; do not anchor; viability not growth rate; a benchmark note is not a
measurement; `raw_available=0` ≠ absent). Expose the raw menu and a naive caller reads the first design it
thinks of and emits a number with none of the scope caveats — the instrument without the discipline.
Independent support: codegraph's measured finding that one strong tool steers agents better than a menu of
narrow ones, and our own AG-2 tool-selection error rate, which exists because this failure is real.

Also worth exposing, and *easier* than Cellwright: **`convene_council(question)`**. The Council is **blind by
construction** — it reads no corpus — so it needs no download at all. A user with the package and no corpus
can still get a falsifiable, operationalized hypothesis, and the blindness invariant is *simpler* to hold
across an MCP boundary than in-process. Packaging Cellwright without the Council is possible but loses the
pairing the paper is about; treat "Cellwright-only" as a deployment option, not the default.

**The rest stays available but unlisted** — the same pattern codegraph uses: the other tools remain callable
and are re-enabled by an env var for power users, but they are not advertised to the model. This dissolves the
earlier "Tier 2", which on inspection was a *demo of limited capabilities* — a shape that only makes sense for
a hosted preview, which we are not building. In a local BYOK install the user already has everything; a
crippled read-only subset would be strictly worse than the package they installed.

**On the earlier "Tier 3" (never over MCP) — that framing was wrong.** This is open source: anyone can clone,
add tools, or strip Cellwright entirely, so "never" is not an enforceable architectural boundary and calling
it one was a category error. The accurate statement is narrower and still worth holding:

> The launch airlock protects **the user from their own agent**, not the project from the user. A human who
> forks and removes it is making a decision about their own machine, which is legitimate. What the default must
> guarantee is that **a third-party agent connected over MCP cannot launch a simulation, write to the corpus, or
> reach the credential vault** without that human approving it.

So it is a *shipped default and a safety property of the agent boundary*, not a wall. Biosecurity screening
stays server-side for the same reason: it protects the operator, and a fork that removes it has assumed that
responsibility knowingly.

**Lock-in.** Low where it matters, and the risk is not where it looks:
- `ask_cellwright` is a thin adapter over the same `orchestrate` seam the CLI and web server already call
  (**D5**). MCP is a wire protocol, not a framework; removing it later costs one module.
- The earlier draft's Tier 2 was the real lock-in — publishing granular tool signatures is a **public-API**
  commitment, and our signatures change when the science demands it (`design_key` changed the week this was
  written). Keeping the menu unlisted keeps that freedom.
- **The genuinely irreversible decision is the SCHEMA, not the protocol.** Whatever design identity and factor
  columns we publish become what other people join against (**WELL-1**, **WELL-9**). Settle those before
  shipping any agent-facing surface; the transport is comparatively disposable.

**Sequence:** HF dataset + `pip install cellarium` first (an agent that can run code needs no protocol at all),
then the MCP server as a thin wrapper. **Blocked on WELL-1 + WELL-9** — do not publish a surface built on a
keying scheme still in motion.

### D6a — Surface A (Cellarium-as-is): the split survives, but the blindness argument does NOT carry over unchanged

> ### ⚠️ SUPERSEDED IN PART — 2026-08-03, by **D10** (below). Read this banner before the section.
>
> **What is withdrawn:** the **blindness stamp** — the `corpus_touched` process ledger, the
> `blindness: blind|unblinded` field, the stamping of that field into `council_runs`, the hard prohibition on a
> Cellwright-then-Council composite, and the "P1-before-ship" framing that rested on all of it. Those are the
> three blocks marked **⛔ WITHDRAWN** inline below.
>
> **Why.** The stamp was defending a claim that does not depend on it. D6a argued that without the stamp
> `council_runs` "becomes a mixture with no column that separates them, which retroactively contaminates the
> evidence base." **It does not:** the A/B cohort is designated **at creation** — `evals/run_ab.py:167-168`
> mints the run id and `:208`/`:323` write it into `evals/results/ab_ledger.json`, which is what
> `evals/aggregate_ab.py:24-36` actually reads — so the powered comparison never touches the table at all
> (**D10.1**, CODE-READ and independently re-verified 2026-08-03). Pre-registration at creation makes the
> stamping question moot.
>
> **And the framing was wrong, not just the mechanism.** D6a treated an *informed* Council — one whose question
> carries findings from a prior Cellwright investigation — as **contamination to be detected**. That is the
> working method of research, not a leak: broad hypotheses → check against simulation results → re-convene with
> a sharper question. Cellarium should **represent** the loop, not police it. The project already learned this
> lesson once, in the same shape: a **blocking** Council sufficiency gate parked ~23 of 25 canonical questions
> and was made advisory (`apps/hypotheses.py:138-143`; M-7).
>
> **What replaces it:** a **typed lineage**, not a boolean — `thread_id` / `round_index` / `informed_by` on
> `council_runs`, so blindness becomes a *query over the chain* rather than a stamp on a row. Full design:
> **D10** below and [`docs/INVESTIGATION_LOOP.md`](INVESTIGATION_LOOP.md); build thread `SP-3`/`SP-3a…e` in
> BACKLOG.
>
> **What SURVIVES from D6a, unchanged and still binding:** (i) the three-way call split; (ii) the composition
> analysis — no single tool is wrong, the leak is by composition; (iii) *"a text screen on the question does not
> fix it"* (a reading arrives as a paraphrase; a string search is not a dependency proof); (iv) provenance
> metadata on a legitimate artifact is the right idea — D10 keeps it and only changes its **data structure**;
> (v) the additional-calls table at the end of the section.
>
> **One real defect the stamp would NOT have fixed**, found while assessing this: `scripts/ab_score.py:67` reads
> `council_runs`, selects the "Arm B" row by **substring match on the question text** (`:74`) and then prints
> `"PRE-REGISTERED (0 corpus reads, blind)"` from `status == "done"` alone (`:86`) — a status that only means the
> deliberation finished. Reachable today by any user typing a matching question; no MCP involved. Filed as
> **`M-10`** (P1). *Nothing below is deleted — the reasoning chain is kept visible on purpose.*

**Proposal assessed.** Three agent calls — Council only, Cellwright only, both — plus readers for the recorded
Investigations (Cellwright chats) and Hypotheses (Council chats).

**Verdict: the split is sound; the *justification* for calling the Council blind is not, once the caller is an
agent instead of a human.** The quarantine we rely on is a property of what the **server composes into the
payload**, not of what the **caller supplies**:

- `instrument.py` is import-quarantined from every result-bearing module (`src/cellarium/instrument.py:9-12`;
  `tests/test_council.py::test_instrument_imports_no_result_bearing_modules`, cited in **D5** above), and
  `dial_labels()` is asserted to carry no numeric reading and no run reference
  (`tests/test_blindness.py:153-168`).
- But `tests/test_blindness.py:19-24` lists `"question"` in `_ALLOWED_KEYS` **unconditionally**. The test checks
  that no *unexpected key* appears and that the dial labels are structure-not-data; it asserts **nothing about
  the contents of the question**. `council.deliberate(question: str, ...)` (`src/cellarium/council.py:735`)
  takes free text and hands it to the proposer.

In-process that gap is closed by who is typing: the question comes from a human via `cli.py` or the SPA, and the
only composed path is Council → Cellwright (`src/cellarium/orchestrate.py:50-57`) — the safe direction. **MCP
removes both protections at once.** The caller is an LLM, which pastes context by default, and two of the
proposed calls make it corpus-aware before it ever calls the Council:

1. `ask_cellwright` returns grounded numbers plus the run ids behind them (that is its whole point);
2. `read_investigation` returns a stored Cellwright transcript, which by construction is *"the model's full
   context (every tool input and result)"* (`apps/sessions.py:66-68`).

Then `convene_council(question=<that text>)` is a perfectly legal call. **The leak is by composition, not by
any single tool being wrong**, and the transcript reader is the high-density version of it.

**What does NOT prevent it.** Screening the question text for readings. A reading can arrive as a paraphrase —
"the knockout looked much worse once you go deeper in generations" — carrying no number, no channel name and no
run id. A substring/regex screen would return clean and we would have bought a false assurance; a string search
is not a dependency proof.

**What does prevent it — provenance of the question, not inspection of it.** A per-server-process blindness
ledger:

> ⛔ **WITHDRAWN 2026-08-03 (D10).** The instinct — *provenance of the question, not inspection of it* — is
> right and is kept. The **mechanism below is not**: a per-process `corpus_touched` flag collapsing to a
> `blind|unblinded` boolean is the wrong data structure. It (a) records a property of the *server session*
> rather than of the *chain* (which investigation, which runs, which prior Council); (b) is **lossier than what
> the codebase already encodes** — blindness here is typed by input class, *literature-informed, corpus-blind*
> (`docs/HYPOTHESIS_MODE_PLAN.md:32-34`; `tests/test_blindness.py:19-24` admits `library_brief` at `:23` for
> exactly that reason), and a boolean cannot express it; and (c) answers only the question we thought to stamp,
> where a stored lineage can be re-queried later with a different one. Replaced by `informed_by` (typed) +
> `thread_id` + `round_index`, with `blindness_of(run_id)` computed over the chain — **D10.3**.

- The server marks itself `corpus_touched` the first time it serves **any** corpus-reading call
  (`ask_cellwright`, `read_investigation`, or any of the available-but-unlisted read tools).
- Every `convene_council` result carries a **`blindness`** field: `blind` only when no corpus-reading call has
  been served in this session *and* the question was not derived from a returned investigation id; `unblinded`
  otherwise. Investigation/Hypothesis reads return `contains_readings: true` so the derivation is mechanical
  rather than guessed.
- The field is stamped into the persisted `council_runs` row (`apps/hypotheses.py:36-38` already carries a
  `meta` column), so an unblinded run cannot be laundered into the record as blind afterwards.
- **It stamps; it never blocks.** Refusing would break the legitimate read-then-re-ask loop, and the project's
  own precedent is that this class of gate must stay advisory (`council.missing_axes` / `sharpening_hint` —
  M-7, "deterministic, blind, non-blocking").

**One hard rule.** The server may expose a **`both`** call only in the server-ordered direction, Council →
Cellwright. A single tool that runs Cellwright first and the Council second must not exist: that would make the
leak the advertised behaviour rather than an accident of composition.

> ⛔ **CONVERTED, not kept — 2026-08-03 (D10.3).** A prohibition became a **representation requirement**. A
> Cellwright-then-Council composite is *legitimate and desirable* — it is the second half of the research loop.
> What must not ship is an **opaque** one: the composite must be recorded as **two rounds with an edge between
> them** (`informed_by=[{"kind":"investigation","id":…}]`), never as one call whose inputs cannot be recovered.
> **Auditability is the deliverable, not prohibition.**

**Why this is P1-before-ship and not polish.** The paper's methodological claim (`COUNCIL_AB_METHODOLOGY.md`)
rests on the Council being blind. If the MCP surface ships without the stamp, `council_runs` becomes a mixture
of blind and unblinded deliberations **with no column that separates them** — which retroactively contaminates
the evidence base for the central claim, not just future runs.

> ⛔ **WITHDRAWN 2026-08-03 (D10.1) — this paragraph is factually wrong about its own evidence base.** The
> paper's A/B claim does **not** read `council_runs`. `evals/run_ab.py:167` mints the run id with
> `hstore.new_id()`, `:168` inserts the row, `:183` deliberates on a question from the committed
> `evals/cases.py`, `:208` returns `{"run_id": run_id, …}` and `:323` persists it via `_save_ledger` into
> `evals/results/ab_ledger.json`; `evals/aggregate_ab.py:_flatten` (`:24-36`) walks **that ledger dict**, and
> the string `council_runs` does not appear anywhere in that file. **Cohort membership is the ledger's key set —
> by construction, not by inspection**, the same pre-registration discipline
> `evals/preregister/PREREGISTRATION.md` already applies to the endpoints. A later informed round accumulating
> in `council_runs` therefore cannot contaminate it. Two changes make that robust rather than merely lucky:
> `M-10` (select by ledger `run_id`, not substring) and `run_ab.py` writing `round_index=0` + `informed_by=[]`
> at creation — a *record* of the designation, not a *recovery* of it (**D10.3**). This item is consequently
> **no longer P1-before-ship**; `M-10` is, and `SP-3` is P2.

**Additional calls worth adding — each with what it is FOR.**

| Call | What it is FOR | Why it belongs on the surface |
|---|---|---|
| `corpus_coverage(design_or_id)` → `support.coverage` (`src/cellarium/support.py:36`) | Answer "can the corpus support a claim about this at all?" in one cheap call — `n_seeds` / `n_generations` against `MIN_SEEDS = 2` / `MIN_GENERATIONS = 2` (`support.py:32-33`) | Lets a caller refuse *before* spending a full Cellwright loop, and it is the refusal primitive **PLAT-2** needs anyway |
| `evidence_for(run_ids \| claim)` → the append-only evidence ledger (`src/cellarium/evidence.py`) | The reviewer question the ledger was built for: *"Figure 3 says the argS knockout lowers ppGpp — show me the runs"* (`evidence.py:7`) | Makes a claim written in **someone else's** document traceable without re-running the agent |
| `list_investigations` / `read_investigation` (owner's proposal) | Re-reading recorded work | Keep — but these are the calls that set `corpus_touched`, and their results must carry `contains_readings: true` |
| — *not* proposed — | launch / write / vault access | Already answered above: the shipped default is that a third-party agent cannot launch, write, or reach the vault without its human |

`convene_council` is also the one call that works with **no dataset downloaded at all** (the Council reads
nothing). The tool description should say so, and the server must not fail it on a missing manifest.

### D6b — Surface B (a data-only MCP over the HF corpus): what it needs to be honest

For users who want the **data** without the agents. The generic advice ("expose a read-only SQL tool over the
Parquet") is actively wrong here, and the reasons are all in how this corpus is actually shaped.

**B1 — Schema discovery cannot return a static schema.** The corpus is the union of per-contributor Parquet
shards read with `union_by_name=true` (`src/cellarium/manifest.py:236`, `:449`, `:712`), so columns are
*partially populated* — `manifest.py:874` and `:892` exist precisely to find rows where `kb_sha256 IS NULL` and
`elongation_model IS NULL`. `describe_corpus` must therefore report, per column, the non-null fraction of the
deduped rows **and which shards supply it**. Without that, a caller joins on a column present for a third of the
corpus and reports the subset as the whole.

**B2 — The dedup rule is not the caller's to skip.** `DEDUP_QUALIFY` (`manifest.py:72`) partitions on the
**pair** `(id, normalised simout_path)` because *neither half is unique* (`manifest.py:37-49`). The recorded
damage from getting this wrong: nine duplicate rows inflated `wildtype/basal` — the reference for **every**
comparison — from 26 seeds to 34, and every interval on it. **Consequence: no raw `read_parquet`, no arbitrary
SQL over the shard glob.** Every query runs over the deduped view and the result states that it did, plus how
many raw rows collapsed. A read-only SQL passthrough is the tool that looks most honest and is the easiest way
to make this corpus lie.

**B3 — Tombstones are a third population, not a second.** `dropped_keys()` (`manifest.py:88`): a dropped run is
**excluded from ranking and comparison but kept in coverage** — the DB never forgets it existed or why. So every
count declares which population it counted (deduped-live · deduped-live + tombstoned · raw rows), and "how many
runs are there" returns all three. **WELL-9** is the standing evidence for what happens otherwise: three tools,
three different design counts (49 / 60 / 37).

**B4 — Per-run provenance rides on every row.** `provenance.classify` (`src/cellarium/provenance.py:46`) tags
`in_sample` vs `out_of_sample`; the H1/H2 pair is the recorded reason (`provenance.py:3-6`) — reading an
in-sample agreement as predictive validation is the specific error a bare manifest row invites. A data-only
consumer has no Cellwright system prompt to supply that caveat, so it must be **in the payload**, not in a
lookup the caller may not make.

**B5 — Refusal has three distinct forms and conflating them is the failure.**
1. *Not in the corpus* — no such design / species / condition.
2. *In the corpus but not readable here* — the shard answers panel-species, summary channels, viability and a
   coarse trajectory; arbitrary species, full-resolution trajectories and FBA fluxes need raw `simOut`
   (`src/cellarium/hf.py:23-24`), which is either on HF or regenerable. `_full_simout_local` (`hf.py:27`) is the
   honest check: a run directory that exists but has no `simOut/MonomerCounts` is **not** readable. The refusal
   must name the recovery route (HF pull vs regenerate). `raw_available = 0` ≠ absent.
3. *Answerable, but below the evidential floor* — under `support.MIN_SEEDS` / `MIN_GENERATIONS`
   (`support.py:32-33`). That is a **refusal at that scope**, not a footnote (see **PLAT-2**).

**B6 — Truncation with named omissions is a requirement of the data surface too**, not only of the agent: any
list result names which seeds / generations / conditions were dropped, inside the tool's declared output schema.
Full spec in **PLAT-2**.

**B7 — Mapping onto MCP mechanics** (design guidance, not verified against a spec file in this repo): expose the
dataset card and the per-shard schema report as MCP **resources** with stable URIs; expose queries as **tools**
with a declared `outputSchema` so the structured result is machine-checkable; mark every tool `readOnlyHint` —
this surface has no write path at all; use **cursor-based pagination** for list results, with the B6 omission
stamp for the cases where a cursor is not offered; and return **resource links** to the HF files backing a row
so the caller can pull raw itself. The one place the standard playbook must be overridden is B2.

**Sequencing.** Surface B is *less* blocked than Surface A on the agent side but *more* blocked on **WELL-1 +
WELL-9**: a data-only MCP is nothing but published schema, so it commits the keying scheme completely. Ship it
after those land, and after **PLAT-2**, whose omission stamp it depends on.

### D6b-1 — Surface B: the concrete tool architecture (DESIGNED 2026-08-03, not yet built)

*D6b argued that a raw-SQL / `read_parquet` passthrough is the wrong surface for this corpus. **That argument
only earns its keep if it is converted into requirements**: every invariant raw SQL would let a caller skip has
to come back as a **tool that enforces it**. This section is that conversion. It is a build spec, not a
prohibition — the refusal in D6b is the negative image of the twelve tools below.*

**Scoping (owner, 2026-08-03).** The production HF dataset will be a properly-run set of **unique** simulations
with a proper schema. **Do not design around dedup artifacts.** Design around invariants that are *semantic* —
true of any corpus of whole-cell runs — and therefore survive a clean corpus.

That distinction is now MEASURED rather than assumed. Against `data/manifest` (one shard,
the contributor's compacted shard, then named after the contributor, 2026-08-03, via `duckdb` in `.venv`): **322 raw rows, 322 after `DEDUP_QUALIFY`** —
i.e. on the compacted shard the dedup rule is currently a **no-op**, and 0 tombstones exist
(`manifest.dropped_keys()`, `manifest.py:88`). Dedup and tombstones are therefore correctly classified as
*dev-corpus hygiene*, not as the load-bearing invariants of the surface. The nine remaining invariants below all
survive.

#### The invariant table — what a caller with raw SQL could skip, and the tool that stops them

| # | Invariant | What SQL lets you skip | Enforcing tool | Evidence it is real |
|---|---|---|---|---|
| **I1** | **Identity is stored, never re-derived** | keying a design on `label` / `condition` string-parsing | every tool takes an opaque `design_key` token; none accepts a `WHERE` on `label` | `manifest._flat_row` `:386-390` — `condition` is NULL for timelines and `'basal'` for propose-path KOs; two opposite nutrient shifts once merged, a gltX KO was filed as a control |
| **I2** | **Comparability partition** — `(kb_sha256, operons, elongation_model, medium)` | pooling runs from two knowledge bases into one mean | `check_comparability` (T3), enforced as a **refusal** inside `contrast` (T6) | MEASURED below — `wildtype/basal` currently pools two `kb_sha256` values |
| **I3** | **Independence** — seeds exchangeable, generations **not** | `COUNT(*)` as *n* over a (seed × generation) grid | `get_measurements` (T5) has no cross-generation aggregate; `contrast` (T6) reports `n_seeds` and has no `n_observations` field | **D7**, *The three axes* (this file, D7 §axes); `stats.py:119-124` records that depth is a **fixed** effect and `survey` stratifies instead of pooling |
| **I4** | **Three populations** — reportable · non-reportable-but-real · tombstoned | `WHERE reportable` silently deleting the lethality phenotype | every count declares its population; `viability` (T7) is the only route to collapsed runs | `survey.lethality` `:244-258` — a run that divides then collapses is correctly non-reportable, and the collapse **is the data** |
| **I5** | **Evidential floor** | quoting a mean from one seed / one generation | `support.coverage` block on every numeric return; `refused: below_evidential_floor` | `support.py:32-33` (`MIN_SEEDS=2`, `MIN_GENERATIONS=2`) and the three incidents in `support.py:6-14` |
| **I6** | **Representability** — a missing mechanism must refuse, not return a number | `SELECT stddev(fraction_trna_charged)` returning `0.0` as a finding | `model_capabilities` (T8), called **inline** by T5/T6 for mode-dependent channels | `capability.py:1-13` — within-family charging spread of exactly `0.00e+00` was reported as a result and was an **algebraic identity** |
| **I7** | **In-sample vs out-of-sample** | reading a fitted condition's agreement as predictive validation | `provenance.classify` tag rides on every returned row | `provenance.py:1-7` — the H1/H2 pair |
| **I8** | **Projection / granularity** — channels are last-generation time-means; the species panel is last-generation **only** | "species X at generation 3" answered from data the manifest never stored | `species` (T9) refuses any non-terminal generation | `_reader_worker.py:213,219-220` (`gs[-1]` for dynamics, pathways **and** `species_panel`); **D7** decision item 3 (curated panel is last-generation only) |
| **I9** | **Declared ≠ executed** | trusting the `timeline` column as what ran | `experiment_integrity` (T11), which separates `recorder_truncation` from `violation` | `miase.py:14-24` — `media_id` is fixed-width `<U7`, and `'minimal_plus_amino_acids'[:7] == 'minimal'`, so an upshift vanishes from the record while the run is fine |
| **I10** | **Not-readable ≠ absent** | `raw_available = 0` read as "this run does not exist" | `raw_access` (T10), tri-state | `hf.py:28-42` (`_full_simout_local` — a run dir with no `simOut/MonomerCounts` is **not** readable) and `hf.py:193-201` (`hf_exists` is `True`/`False`/`None`, and `None` never emits a download command) |

**The new one: I2 is currently unenforced, and it bites the reference design.** MEASURED 2026-08-03 over
`data/manifest` with `DEDUP_QUALIFY` applied: the corpus carries **two distinct `kb_sha256` values** —
`3b2f8ebd…` (279 rows) and `0d861f80…` (43 rows) — while `operons='on'` and
`elongation_model='steady_state'` are uniform at 322/322. Restricting to `reportable` rows and keying by
`survey.design_key`, **2 of 44 design keys mix the two knowledge bases**: `wildtype/basal`
(`3b2f8ebd`: 26 seeds, `0d861f80`: 4) and `condition/with_aa` (`3b2f8ebd`: 8, `0d861f80`: 4). `wildtype/basal`
is the reference for **every** comparison (`differential.REFERENCE`, `differential.py:20`). No analysis path
partitions on it: `survey._deduped_rows` (`survey.py:129-162`) does not even select `kb_sha256`, and
`survey.analysis_rows` (`survey.py:178-205`) — *the* row source for every comparison tool — filters only on
`reportable` and `_dropped`. `operons.py:295` and `capability.py:294-295` state the rule in **prose**
("different knowledge bases … MUST NOT be pooled"; a mode switch "changes `kb_sha256`" so the campaign "is not
poolable"); nothing checks it. This is the same shape as the dedup incident D6b cites (26 → 34 seeds on the same
reference) and it is a **semantic** partition, so unlike dedup it does not go away in a clean corpus — any corpus
built from more than one ParCa pass will have several hashes. Filed as **M-11** (BACKLOG class A).
*(This
paragraph read "Filed as M-10" when written; `M-10` had been taken the same day by the A/B cohort-selection
defect recorded in D10.1. Corrected here so the pointer resolves.)*

#### The tools

Common contract, on every tool: `readOnlyHint` (this surface has no write path at all), a declared
`outputSchema`, a `population` block naming which of {deduped-live, +tombstoned, raw} was counted (B3), a
`partition` block `{kb_sha256, operons, elongation_model, medium}` (I2), and — on anything numeric — a `support`
block from `support.coverage` (`support.py:36`) and a `projection` block naming what was collapsed (I8).
Truncation follows PLAT-2/B6: **named** omissions (which seeds, which generations, which designs — by id), and
if truncation drops the surviving set below `MIN_SEEDS`/`MIN_GENERATIONS` the tool **refuses at that scope**
rather than answering with a footnote.

**The tool table** — the index. Each row's full contract is the spec below it; **a tool with no invariant does
not ship**, which is why the last column is never empty.

| # | Tool | Args | Returns | Refuses — and why | Enforces |
|---|---|---|---|---|---|
| **T0** | ~~`query(sql)`~~ | — | — | **Does not exist.** A server-side SQL passthrough lets a skipped invariant come back wearing this project's name on the answer. Its absence is reported *in `describe_corpus`* so a caller is told why, not left to assume immaturity | — |
| **T1** | `describe_corpus` | `include_columns` | build id; the three population counts; **per-column non-null fraction** + supplying shards; the partition inventory; channel dictionary; projection semantics; floor constants; the T0 note | a **static** schema (shards union `union_by_name=true`, so columns are partial: MEASURED `species_panel` 240/322, `growth_rate` 253/322, `design_key` 51/322, `crash_type` 11/322); and an **empty** schema when the manifest is unreadable — returns `readable:false` + reason | B1, I4 |
| **T2** | `list_designs` | `perturbation?`, `gene?`, `condition?`, `medium?`, `contains?`, `population`, `cursor?`, `limit` | per design: opaque `design_key`, `n_seeds`, the **list** of generation depths, `reportable_seeds`, `collapse_seeds`, `tombstoned_seeds`, `partition`, `provenance`, `raw_available` | a design row without its **population split** — "how many runs are there" has three answers, and returning one is how WELL-9 got 49/60/37 from three tools; filtering on a partially-populated column without a `filter_coverage` block | I1, I4, I7 |
| **T3** | `check_comparability` | `design_keys[]` | `poolable`, each key's partition tuple, the **named** differing axes, and a poolable subset if not | nothing — it is a predicate. Its value is that **T6 refuses on its verdict** | I2 |
| **T4** | `controls_for` | `design_key` | designs differing in **exactly one factor**, in dose order (`factors.one_factor_neighbours`) | to fall back to **response similarity** — SQL is exact 7/7 here, similarity ~5/7 and its clusters are lethality-confounded (D8). "Most similar run" as a control is the error this tool pre-empts | control selection |
| **T5** | `get_measurements` | `design_key`, `channel`, `generation`, `seeds?`, `include_nonreportable`, `cursor?` | **per-seed, per-depth rows** `{run_id, seed, generation_depth, value, qc, reportable}`; `n_seeds` and `n_generations` as separate fields; `support`; `projection`; `partition`; `provenance` | **(a)** any cross-generation pooled number — *unrepresentable in the signature*; **(b)** below `MIN_SEEDS`/`MIN_GENERATIONS` → `refused: below_evidential_floor` naming a scope that would qualify; **(c)** a mode-dependent channel → `capability.check`'s refusal **inline instead of the value** | I3, I5, I6, I7, I8 |
| **T6** | `contrast` | `target`, `reference`, `channel`, `at_generation` | per-seed values **both sides** at matched depth, effect, Welch *t* with a **t-distribution** CI (not 1.96 — wrong at n=4–8), `n_seeds` per side, depth note + reference drift | **(a)** different comparability partitions, **naming the axis** — this is what makes the measured `wildtype/basal` kb-pooling impossible over the wire; **(b)** unmatched depths, offering the common depth; **(c)** it has **no `n_observations` field at all**. The depth note stays a soft, quantified signal — **never a gate** | I2, I3 |
| **T7** | `viability` / `lethality_landscape` | `design_key` (or a reference) | the **pre-collapse** signature only: per-generation QC verdicts + the growth/ppGpp trajectory read at the collapse generation | channel means from a collapsed generation. *Why it must be a tool:* `WHERE reportable` deletes the lethality phenotype — `is_reportable` needs **every** generation ok (`qc.py:62-65`), and MEASURED 101/322 rows are non-reportable (crashed 63 · no_division 14 · implausible_channel 11 · noop_knockout 7 · over_replicated 4 · empty 2). Some of those are **results, not failures** | I4 |
| **T8** | `model_capabilities` | `mechanism?`, `elongation_model?` | `can_answer`; when false, the gap, what the model does **instead**, what a naive read would wrongly conclude, and the `switch` route — all mode-keyed | to answer unconditionally on the elongation axis; and to treat an **undeclared** mechanism as evidence of absence — `can_answer` is `None`, never `False` | I6 |
| **T9** | `species` | `design_key`, `species_id`\|`search`, `kind`, `generation?` | panel membership, per-seed terminal value, and whether the species needs raw | any `generation` other than terminal — panel, pathways and dynamics are all read from `gs[-1]`, so per-generation species values **were never stored**. A non-panel species is refusal form **2** (not readable *here*, recovery route named), never form 1 | I8 |
| **T10** | `raw_access` | `design_key`\|`run_id` | per run: `readable_here` (an honest `simOut/MonomerCounts` check), `hf_path`, `hf_verified: true\|false\|null`, size, `recovery`, + resource links | to emit a download command for an **unverified** archive. `hf_exists = None` means *could not verify*, never *absent* — precedent `hf.py:78-85`, where a stale OAuth token made a **public** dataset report unavailable and the wrong diagnosis was filed | I10 |
| **T11** | `experiment_integrity` | `design_key?` | per design: declared media events vs recovered, classified `ok` · `recorder_truncation` · `violation` · `undetermined` | to conflate a bad **record** with a bad **experiment**; and to report per-segment means for a truncation-affected design without the stamp (those means average pre- and post-shift timesteps together) | I9 |
| **T12** | `run_environment` | `run_id` | `kb_sha256`, `kb_bytes`, `operons` **with its evidence string**, `elongation_model`, python version, git commit, pinned versions | to assert the operon mode without the evidence that settled it — "operons on" was previously filesystem inference, not provenance a reviewer could check | reproducibility; supplies the I2 partition key |

---

**T0 — the tool that does not exist: `query(sql)`.** Deliberately absent, and the absence is documented in
`describe_corpus`'s output so a caller is told *why* rather than left to assume the surface is immature. The
replacement for "I want to write my own SQL" is: the resources (below) publish the full schema and the dedup
rule, and the HF files are linked from every row — a caller who wants raw SQL can pull the Parquet and run it
locally, having been shown the invariants first. **What is refused is a *server-side* SQL tool that would let a
skipped invariant come back wearing this project's name on the answer.**

---

**T1 `describe_corpus()`** · *enforces B1 + I4*
`args:` `include_columns: bool = true`
`returns:` corpus build id; the three population counts (raw / deduped-live / +tombstoned); **per column**, the
non-null fraction over deduped rows and which shards supply it; the partition inventory (distinct
`kb_sha256` × `operons` × `elongation_model`, with row counts); the channel dictionary with each channel's
`(listener, column)` origin (`raw.CHANNELS`, `raw.py:31-42`); the declared projection semantics; the floor
constants; and the `query(sql)` non-existence note.
`refuses:` to return a **static** schema — the corpus is a `union_by_name=true` union of per-contributor shards
(`manifest.py:185-186`), so columns are partially populated. MEASURED today: `species_panel` 240/322,
`growth_rate` 253/322, `design_key` 51/322, `crash_type` 11/322. Also refuses to return an **empty** schema when
the manifest is unreadable — it returns `readable: false` with the reason, mirroring `manifest.manifest_columns`
(`manifest.py:189`), which deliberately does not cache an unreadable read. *Why a caller could not do this
themselves:* `DESCRIBE` over the glob reports the union as if every column were populated.

**T2 `list_designs(...)`** · *enforces I1, I4, I7*
`args:` `perturbation?`, `gene?`, `condition?`, `medium?`, `contains?`, `population = "live" | "live+tombstoned" | "all"`, `cursor?`, `limit = 50`
`returns:` per design: the opaque `design_key`, `n_seeds`, the **list** of generation depths present (not a
mean), `reportable_seeds`, `collapse_seeds`, `tombstoned_seeds`, the `partition` block, the
`provenance` tag from `provenance.classify` (`provenance.py:45`), and `raw_available`.
`refuses:` to return a design row without its population split — "how many runs are there" has three answers and
returning one is how WELL-9 produced three different design counts (49/60/37) from three tools. Refuses to
filter on a column whose coverage is partial without returning a `filter_coverage` block stating what fraction
of rows could even be evaluated.

**T3 `check_comparability(design_keys: list[str])`** · *enforces I2 — the tool that replaces the SQL join*
`args:` two or more design keys
`returns:` `poolable: bool`; each key's partition tuple; the **named** differing axes; and, when not poolable,
what a poolable subset would be.
`refuses:` nothing — it is a predicate. Its value is that T6 calls it and refuses on its verdict. *Why a caller
could not do this themselves:* they can, with a `GROUP BY` — but only if they know `kb_sha256` is a partition
key, which is stated today in prose in two modules and enforced in none (see M-10).

**T4 `controls_for(design_key)`** · *enforces "the control is a factor neighbour, not a nearest neighbour"*
`args:` `design_key`
`returns:` designs differing in **exactly one factor**, in dose order (`factors.one_factor_neighbours`,
`factors.py:233`; wrapped today as `tools.comparable_designs`, `tools.py:116-136`).
`refuses:` to fall back to response similarity. Recorded reason, `tools.py:133-136` and D8
(**D8**, the measured bake-off table): SQL is exact 7/7 on this question, response similarity measured ~5/7 and its
mechanistic clusters are confounded with lethality. A data-only caller reaching for "most similar run" as a
control is the error this tool exists to pre-empt.

**T5 `get_measurements(design_key, channel, generation, ...)`** · *enforces I3, I5, I6, I7, I8 — the core read*
`args:` `design_key`, `channel`, `generation: int | "terminal" | "all"`, `seeds?`,
`include_nonreportable = false`, `cursor?`
`returns:` **per-seed, per-generation-depth rows** `{run_id, seed, generation_depth, value, qc, reportable}`;
`n_seeds` and `n_generations` as separate fields; `support`; `projection` (timesteps → mean, which generation);
`partition`; `provenance`.
`refuses:` **(a)** there is no argument that returns one number pooled across generation depths — the
cross-generation aggregate is *unrepresentable in the signature*, because generations are ordered and
autocorrelated (**D7**, *Generations — a trajectory, NOT exchangeable*). Aggregation over **seeds within one depth** is offered; aggregation
across depths is not. **(b)** below `MIN_SEEDS`/`MIN_GENERATIONS` it returns `refused: below_evidential_floor`
naming the scope it refused and a narrower or deeper scope that would qualify — a refusal at that scope, not a
footnote (B5.3). **(c)** for a channel whose meaning is elongation-model-dependent it returns
`capability.check`'s refusal **inline instead of the value** (`capability.py:536`). `fraction_trna_charged` is
the worked case: 86 columns wide under all three models, a broadcast scalar under `steady_state`, genuinely
independent under `kinetic`, exact zeros under `coarse_kinetic` (`capability.py:76-83`).

**T6 `contrast(target, reference, channel, at_generation)`** · *enforces I2 + I3 — the tool that makes the kb-pooling bug impossible*
`args:` `target: design_key`, `reference: design_key`, `channel`, `at_generation: int | "matched"`
`returns:` the per-seed values on **both** sides at the matched depth, the effect, Welch *t* with a
*t*-distribution CI (`stats.welch_t`, `stats.py:227`; `stats.t_critical_95`, `stats.py:25` — not 1.96, which is
wrong at n = 4–8 seeds), `n_seeds` per side, the depth note and the reference's own drift across the depth gap
(`differential._depth_note`, `differential.py:98`; `_reference_drift_pct`, `:86`).
`refuses:` **(a)** if `check_comparability` says the two sides sit in different partitions — naming the axis.
**(b)** if the depths cannot be matched — offering the common depth, per D7's *1-to-1 generation* operation
(**D7** decision item 1, the *1-to-1 generation* operation). **(c)** it has **no `n_observations` field at all**: the count is seeds, and the
signature makes counting a (seed × generation) grid as *n* impossible to express. The depth note is a **soft,
quantified** signal and never a gate — same never-block invariant as the Council gate
(**D7** decision item 2 — *never a gate, never a "finding"*).

**T7 `viability(design_key)` / `lethality_landscape(reference)`** · *enforces I4*
`args:` `design_key` (or a reference for the landscape)
`returns:` the **pre-collapse** signature only — per-generation QC verdicts and the per-generation
growth/ppGpp trajectory read at the generation the collapse occurred (`survey.lethality`, `survey.py:244-258`).
`refuses:` to return channel means from a collapsed generation. *Why this must be a tool:* a caller writing
`WHERE reportable` deletes exactly the designs whose phenotype is lethality — `is_reportable` requires **every**
generation to be ok (`qc.py:62-65`), so an essential-gene KO that divides on inherited enzyme, mounts a
stringent response and then collapses is invisible. MEASURED today: 101 of 322 rows are non-reportable, spread
over `crashed` 63 · `no_division` 14 · `implausible_channel` 11 · `noop_knockout` 7 · `over_replicated` 4 ·
`empty` 2. A `WHERE reportable` filter discards all 101 as if they were failures; some of them are results.

**T8 `model_capabilities(mechanism?, elongation_model?)`** · *enforces I6*
`args:` `mechanism?` (a capability key), `elongation_model? = "steady_state"`
`returns:` `can_answer`, and when false a `refusal` naming the gap, what the model does **instead**, what a
naive read would wrongly conclude, and the `switch` route — all mode-keyed so a refusal never quotes another
model's prose (`capability.py:151-170`, `:252-295`).
`refuses:` to answer unconditionally on the elongation axis, and to treat an **undeclared** mechanism or mode as
evidence of absence — `can_answer` is `None`, never `False`, for anything undeclared (`capability.py:547-559`).

**T9 `species(design_key, species_id | search, kind, generation?)`** · *enforces I8*
`args:` `design_key`, `species_id` or `search`, `kind: "protein" | "mrna"`, `generation? = "terminal"`
`returns:` panel membership, per-seed terminal value, and whether the species is in the curated panel or needs
raw.
`refuses:` any `generation` other than terminal. The panel, the pathway fractions and the dynamics are all read
from `gs[-1]` (`_reader_worker.py:213,219-220`), so per-generation species values **were never stored**;
answering would be **D7** decision item 3's named failure. A non-panel species is refusal form 2,
not form 1 — it exists, it is not readable *here*, and the recovery route is named (T10).

**T10 `raw_access(design_key | run_id)`** · *enforces I10 — the three refusal forms*
`args:` a design key or run id
`returns:` per run: `readable_here: bool` (an honest `simOut/MonomerCounts` check, `hf.py:28-42`), `hf_path`,
`hf_verified: true | false | null`, size, and `recovery: "hf_pull" | "regenerate" | "unavailable"`, plus MCP
**resource links** to the backing HF files.
`refuses:` to emit a download command for an archive whose presence was not confirmed. `hf_exists = None` means
*could not verify* and is rendered as such, never as absent — the precedent is recorded at `hf.py:78-85`, where
a stale OAuth token made a **public** dataset report unavailable and the wrong diagnosis was filed in BACKLOG.

**T11 `experiment_integrity(design_key?)`** · *enforces I9*
`args:` `design_key?` (all designs when omitted)
`returns:` per design, the declared media events vs the recovered ones, classified as `ok` ·
`recorder_truncation` · `violation` · `undetermined` (`miase.py`).
`refuses:` to conflate a bad **record** with a bad **experiment** — the distinction is the module's reason for
existing (`miase.py:14-24`), and collapsing it would condemn usable runs and misattribute an upstream defect.
Also refuses to report per-segment means for a truncation-affected design without the stamp, since those means
average pre- and post-shift timesteps together.

**T12 `run_environment(run_id)`** · *enforces reproducibility + supplies the partition key*
`args:` `run_id`
`returns:` `kb_sha256`, `kb_bytes`, `operons` **with its evidence string**, `elongation_model`, python version,
git commit, and the pinned versions of the load-bearing packages (`provenance.run_environment`,
`provenance.py:123-138`; `kb_provenance`, `:71-120`).
`refuses:` to assert the operon mode without the evidence that settled it — `operons_evidence` records *how* it
was determined (TU-shaped `rna_id`s in the variant map), because "operons on" was previously filesystem
inference and not provenance a reviewer could check (`provenance.py:74-81`).

#### Resources (not tools)

Stable URIs, per B7: the dataset card; the **per-shard** schema report (the live output of T1, so it can never
drift from the data); the channel dictionary; the capability registry (`capability.CAPABILITIES`) as published
JSON, so a consumer can see what the model cannot represent **before** querying; the tombstone ledger
(`data/manifest/dropped.json` + `docs/CORPUS_LEDGER.md`); and `docs/KNOCKOUT_SEMANTICS.md`, without which
`gene_knockout` is systematically misread under operons-ON.

#### What this deliberately does not include

No launch, no write, no vault access — D6's shipped default already answers that
(**D6**, *the shipped default and the agent boundary*). No `query(sql)` (T0). No response-similarity retrieval as a *control* query (T4).

## D7 — The reporting & comparison contract (Cellwright's statistical manual) — ACCEPTED 2026-07-27
**Status:** Accepted · **Deciders:** Evangelos · **Supersedes:** the ad-hoc depth handling in WELL-6x/6y/6z.

**Context.** Every number Cellwright reports is a projection of a 4-D object, and conflating any two of its axes
is what produced this session's repeated errors. The contract fixes the vocabulary so a suggestion Cellwright
makes back to a user is auditable against a stated definition.

**The three axes (canonical definitions).** A simulation result is `value[species, seed, generation, timestep]`.
- **Seeds** — independent stochastic realizations at a *fixed* depth. **Exchangeable** (measured ICC ≈ 0 at
  matched depth). This is the *variance* axis: average them, put a CI on them.
- **Generations** — position in the lineage (mother→daughter→…). **A trajectory, NOT exchangeable** — ordered
  and autocorrelated. This is the *depth* axis; never average across it.
- **Timesteps** — the ~40 min within one cell cycle. A sub-trajectory, currently collapsed to a time-mean.
- **Species** — the *value* read at each grid cell, not a fourth axis.

Every "channel" today is a projection that collapses timesteps (mean) and takes the last generation. That is a
choice, now stated, not an accident.

**Decision.**
1. **Three comparison operations, each declaring what it collapses:** *same-depth summary* (last gen of two
   equal-depth runs — what `survey_corpus` does now), *1-to-1 generation* (gen k of A vs gen k of B — measured
   ICC→0), *trajectory* (the whole gen-0…N curve). Cellwright picks by the question; the tool names which.
2. **Depth mismatch is a SOFT, QUANTIFIED exploration signal — never a gate, never a "finding."** It states how
   far apart the two sides are, quantifies how much the reference's *own* growth drifts across that span
   (measured live from its per-generation trajectory — e.g. ~12.7% over gens 0→6), and suggests deepening the
   shallower case. It must never call a comparison "invalid" or frame the gap as overturning anything. This is
   the same never-gate invariant as the Council gate (D-nudge). *Shipped:* `differential._depth_note`,
   `_reference_drift_pct`.
3. **The fast layer holds a CURATED species panel per (gen, seed); "all species" is a raw drill-down.** The
   199-species panel is last-generation only today — generation-resolved species retrieval requires either raw
   simOut or a per-generation panel expansion (WELL-1x). Tool output must state this boundary, or Cellwright
   will answer "species X at generation 3" from data the manifest never stored.
4. **This corpus is the DEV/BENCHMARK corpus, not the publication corpus.** Underpowered or purpose-served runs
   may be pruned to free disk for more informative ones — but **pruning tombstones, never deletes**: the raw
   simOut goes, the manifest row stays with `dropped` + reason + timestamp, and a decision ledger records what
   ran, what was found, and why. Rationale: silent absence (the invisible `valS`, the phantom rows) was the top
   failure mode this session; "dropped" must be a state the DB remembers. Alternative to local retention:
   export to a distinct HF `benchmark` config, separate from the `publication` config (D1).

**Consequences.** Easier: every comparison is like-for-like or explicitly flagged; pruning is safe and
auditable. Harder: generation-resolved species queries need new plumbing (WELL-1x). Revisit: the curated panel's
membership (199 monomers) once per-generation expansion lands.

**Action items** → BACKLOG **WELL-1x** (per-generation panel + the three comparison ops), **WELL-1y** (prune =
tombstone + ledger + HF benchmark split).

## D8 — Retrieval at the species granularity: SQL vs similarity vs graph (MEASURED) — ACCEPTED 2026-07-27
**Status:** Accepted · **Deciders:** Evangelos · **Extends:** WELL-6c/6d/6d2 (which settled the *design*-level
question; item 1 reopened it at the species level).

**Context.** WELL-6d2 partitioned the retrieval tools over 60 *designs*. D7's axes push the target to the
(design × generation × seed × species) tensor, at which the earlier verdicts do not automatically transfer. A
measured bake-off was run on the 199-species curated panel (in every reportable row, 41 designs) rather than
argued — the same discipline that killed the design-level embedding.

**Measured results (bake-off, `scratchpad/bakeoff*.py`, reproduced in WELL-6z3):**
| method | question | result on the 199-species panel |
|---|---|---|
| **SQL structured** | "which designs are COMPARABLE?" | exact, 7/7 by construction — unchanged, primary |
| **Vector similarity** | "which CAME OUT similar?" | dose-neighbour recovery **~5/7** (ppGpp 3/4, rRNA 2/3) — better than WELL-6b's 3/5; non-lethal **envelope-biosynthesis KOs cluster (+0.397 vs −0.010 overall)** = mechanism; **but `corr(growth, cos-to-WT)=+0.608`**, so severity is a *partial* driver (reduced from WELL-6a, not gone) and the aaRS cluster (+0.855) is **confounded with lethality** — no severe non-aaRS control exists in this corpus |
| **Graph distance** | "which are mechanistically NEAR?" | **does not apply** — 178/199 panel nodes are protein *monomers*; iML1515 is metabolic (metabolites+reactions). WELL-6c's graph-distance win was over metabolites and does **not** transfer to a protein panel |

**Decision.** Keep all three; they answer different questions and are **not peers**.
- **SQL stays primary and exact** for "comparable" — similarity's ~5/7 on the same task confirms you never use
  it to answer SQL's question.
- **Similarity over the curated panel is a HYPOTHESIS GENERATOR, not ground truth** — usable for "these hit the
  same subsystem," but the severity component (PC1) must be removed before shipping, and mechanistic clusters
  must be validated against a non-severity control the corpus currently lacks.
- **Graph distance is DEFERRED at the species level** — it needs a *protein/regulatory* graph (PPI, TF-regulon,
  or enzyme→reaction bipartite), which is new infra; the metabolic graph is the wrong object here. Graph
  *embeddings* remain rejected (WELL-6c).
- **The generation axis is the real gap** — the panel is last-gen only, so generation-resolved similarity is
  untestable from the manifest and blocks on WELL-1x.

**Consequences.** Easier: an honest, measured basis for what similarity can and can't be sold as. Harder:
mechanistic retrieval needs both PC1 removal and a protein graph before it ships. Revisit: rerun the bake-off
after the per-generation panel lands, and once a severe non-aaRS design exists to break the lethality confound.

**Action items** → BACKLOG **WELL-6z3** (record the bake-off), **WELL-6z4** (PC1-removed similarity + the
severity-control gap), **WELL-6z5** (a protein/regulatory graph, or an explicit "not now").

## D9 — The response-similarity metric: DOUBLE-CENTERING, not PC1 removal (MEASURED + adjudicated) — ACCEPTED 2026-07-27
**Status:** Accepted (metric settled; index deferred per WELL-6) · **Deciders:** Evangelos · **Refines:** D8.

**Context.** D8 kept response-profile similarity as a hypothesis generator but flagged that severity ("distance
from wildtype") still partly drives it (`corr(growth, cos-to-WT)=+0.608` on the 199-species panel). WELL-6z4
proposed removing PC1 to de-confound. Before implementing, a 32-agent audit/test/adversarial/literature pass
(`wfv2tiipg`) tested it, with every load-bearing number independently reproduced (and re-reproduced by hand).

**Decision.** When the similarity metric ships, de-confound severity by **DOUBLE-CENTERING** the z-scored
design×species matrix — `Z2 = Z − rowmean(Z) − colmean(Z) + grandmean(Z)` — then cosine. NOT blind PC1 removal.
- Measured: severity confound `corr(growth, cos-to-WT)` **+0.608 → −0.010** (vs +0.117 for PC1-removal), envelope
  mechanism cluster preserved (NN **4/4**, Δ +0.358).
- Why not PC1: PC1 is the *growth* axis (`corr +0.829`); the compositional severity WELL-6a flagged is on PC2
  (`corr +0.908`), so PC1-removal leaves it intact — and PC1 wobbles ~27° across half-splits at n=41 (overfit).
  Double-centering is parameter-free (no fitted direction, no K), and the literature warns against blind top-PC
  subtraction (Goldinger 2013) while endorsing parameter-free/supervised removal (O'Duibhir 2014; SVA/RUV).
- **Two mandatory ship-guards:** (a) always surface growth ALONGSIDE the de-confounded similarity — the axis is
  partly real biology (Klumpp/Hwa growth laws), so a reader must discount it, not have it silently erased;
  (b) label the aaRS cluster as SEVERITY-CONFOUNDED (no transform separates aaRS-mechanism from aaRS-lethality).

**Graph distance (WELL-6z5): NOT NOW, and DROP the enzyme→reaction graph.** The only offline-buildable graph
(iML1515 metabolic) covers 46% of the protein panel, separates modules at near-chance, and WELL-6c already
measured it adding ~zero over exact response similarity. A protein/PPI graph is not evaluable until (a) a severe
non-aaRS control exists and (b) a full-panel graph is acquired; it must then beat PC1-removed cosine with a CI
excluding 0. The phenotype vector already recovers the clusters a graph would claim to add.

**Consequences.** The metric is settled and cheap; building it is deferred (WELL-6 builds the index late). The
`pgi` KO (D-run in progress) is the clean severity control that closes 6z4's residual confound gap.

**Action items** → build `species_similarity()` with double-centering + the two guards + the WELL-6z4 acceptance
test WHEN the similarity feature is scheduled; re-run the bake-off once pgi lands.

## D11 — The retrieval boundary: an exhaustive summary IN CONTEXT, everything after it BY HANDLE — ACCEPTED 2026-09-11
**Status:** Accepted (architecture settled; the compression work is not built) · **Deciders:** Evangelos ·
**Refines:** D8 (which questions retrieval answers) and **WELL-6d/6e** (the three-layer stack and the
context cliff).

**The question, put sharply by the owner.** `survey_corpus` serialises ~11k tokens of ranked rows straight
into the investigator's context on every investigation. Why depend on that at all — why not hand the agent
the database as an object and let it query?

**What the arithmetic says, and it is not what the earlier framing implied.** 11,134 tokens is roughly five
or six cents per investigation at Opus input rates, read once and then at cache-read rates, and about 5% of
a 200k window. **Neither is binding, and cost was the wrong reason to give.** If cost were the argument the
handle would simply win.

**The actual argument is about WHO CHOOSES.** `survey_corpus` is not a data-delivery mechanism; it is an
anti-anchoring device *whose mechanism is exhaustiveness*. It hands over every design ranked by arithmetic
so that what the agent finds interesting is not what decides what it sees. A query handle makes retrieval
**agent-directed**, and a selection made by a language model is precisely the attention-driven filter the
tool exists to replace. That is the methodological invariant D8 and WELL-6d2 recorded, and WELL-6e's fix
exists because eleven designs had quietly slipped outside it.

The second argument is narrower and equally load-bearing: **a raw handle re-opens every invariant the read
boundary closes.** `SELECT AVG(growth_rate) … WHERE design='X'` pools across arms, admits non-reportable
rows, and skips the de-duplication rule — and skipping that rule once inflated the wildtype reference, the
baseline for every comparison, from 26 seeds to 34. The survey's payload carries `z_scope`, `depth_note`,
`true_label` and `label_integrity` *per row*; those guardrails travel only if the rows do.

**And the handle already exists.** D6b-1's refusal of `query(sql)` was never "no queries" — it was *every
invariant raw SQL would let a caller skip comes back as a tool that supplies it*. The ~70 read tools are
that handle. What cannot be delegated is the **first** look.

**DECIDED — the boundary sits at the first look, not at all of it:**
1. **The mandatory first read stays exhaustive and stays in context.** Every ranked design is named, by
   arithmetic, before the agent forms a view. This is an invariant, not a default.
2. **It gets compressed hard.** Most of today's 11k is per-row scaffolding repeated across 24 channels;
   the exhaustiveness claim costs far less than the current encoding of it.
3. **Everything after the first look is by handle** — the existing tool surface, each call carrying the
   invariants a raw query would let a caller skip.

**Consequences.** (a) The compression is a build item, and it must not be allowed to reintroduce the
WELL-6e cliff — any sampled survey reports its sampling fraction, and `tests/test_survey_exhaustive.py`
is phrased over the payload rather than over today's roster so it survives a re-encoding. (b) WELL-6e's own
prediction is recorded as wrong about timing: it expected the cliff at ~10⁴ runs and it arrived at 369,
because the mechanism is **channel count**, not payload size. (c) No new query primitive is added; the
handle is the tool surface that already exists.

## D10 — The investigation LOOP as a first-class feature (supersedes D6a's blindness *stamp*)

**Status:** DESIGNED 2026-08-03, **not built.** · **Supersedes:** D6a's blindness stamp (see the banner and the
three ⛔ blocks in D6a above — nothing there was deleted). · **Build spec, migration, API and acceptance tests:**
[`docs/INVESTIGATION_LOOP.md`](INVESTIGATION_LOOP.md). · **Backlog:** `SP-3` → `SP-3a…SP-3f` (class D, `D-LOOP`).
This section is the *decision and its reasoning*; the build detail lives in the spec so the two do not drift.

**Origin.** D6a (above) treated a Council run whose question carries findings from a prior Cellwright
investigation as *contamination* — something to detect and stamp. That framing is **withdrawn**. Looping
(broad hypotheses → check against simulation results → re-convene with a targeted question) is not a leak; it
is the working method the whole system exists to support, and Cellarium should represent it, not police it.
This decision replaces the stamp with a **lineage**, and states what that lets a user ask.

The project has made this correction once before: the Council sufficiency gate was made **advisory** after a
blocking version parked ~23 of 25 canonical questions (`apps/hypotheses.py:138-143`; the gate diagnostic is
still reported by `evals/run_ab.py:354-368`). The same rule governs here — **the loop is never blocked, and
lineage is displayed, never enforced.**

### D10.1 — Does pre-registering the blind cohort at creation make the stamping question moot? **Yes.**

Assessed against what the A/B evidence base actually reads. **CODE-READ, all of it:**

- **The A/B cohort is designated at creation.** `evals/run_ab.py:167-168` mints the run id itself
  (`hstore.new_id()`), inserts the row, then calls `council.deliberate` at `:183` with the case question from
  the committed `evals/cases.py` and nothing corpus-derived. The returned row carries `"run_id": run_id`
  (`:208`) and is written into `evals/results/ab_ledger.json` (`_save_ledger`, `:323`). **Cohort membership is
  the ledger's key set** — it is by construction, not by inspection.
- **The powered comparison never touches the table.** `evals/aggregate_ab.py:_flatten` (`:24-36`) walks the
  ledger dict; `council_runs` does not appear in that file. The paper's headline A/B number is therefore
  computed entirely from a cohort frozen at creation — exactly the discipline
  `evals/preregister/PREREGISTRATION.md` already applies to the endpoints.

So D6a's stated reason for the stamp — *"`council_runs` becomes a mixture with no column that separates them,
which retroactively contaminates the evidence base"* — **does not hold for the claim it was defending.** The
evidence base is the ledger, not the table.

**One script is the exception, and it is a live defect, not a future MCP risk.** `scripts/ab_score.py:67`
reads `SELECT id, question, status FROM council_runs`, selects the "Arm B" row by **substring match on the
question text** (`:74`), and then prints `"PRE-REGISTERED (0 corpus reads, blind)"` from `status == "done"`
alone (`:86`). `status` only means the deliberation finished. Any user who types a question containing
`"args knockout raise or lower"` into the Hypotheses surface today lands in that selector — no MCP required.
The fix is not a new column: **`ab_score` should take the ledger's `run_id` set**, the cohort that already
exists. (Filed as `M-10` in BACKLOG.)

**A boolean would also collapse a distinction this codebase already makes.** Blindness here is already
*typed by input class*, not binary: `docs/HYPOTHESIS_MODE_PLAN.md:32-34` scopes the invariant as
**literature-informed, corpus-blind**, and `tests/test_blindness.py:19-24` admits `library_brief` into
`_ALLOWED_KEYS` (`:23`) for exactly that reason. A `blind | unblinded` field would be a lossier record than
the one the tests already encode.

**What survives from D6a is (c) only:** provenance metadata on a legitimate artifact. That is D10.2.

### D10.2 — What exists today: two of the four edges are stored, and the one loop primitive is destructive

The chain the owner describes is *prior Council → investigation → runs → next Council*. **MEASURED by reading
the writers:**

| Edge | Stored? | Where |
|---|---|---|
| Council run → queued falsifier run | **Yes** | `launch.stamp_provenance(request_id, session_id, question, hyp_id)` writes `hyp_id` / `session_id` / `from_question` onto the queue row (`src/cellarium/launch.py:163-178`); the SPA supplies it via `state._hypSource = {hyp_id, question}` (`apps/web/app.js:1154`, used `:802`, `:870`); `apps/server.py:304-328` reflects the lifecycle back onto the hypothesis |
| Investigation → runs it read | **Yes** (opt-in) | `src/cellarium/evidence.py` — append-only JSONL, one line per tool call, **ids not values**, field names mapped to W3C PROV `activity`/`entity`/`wasGeneratedBy` (`:20-22`); off unless `CELLARIUM_EVIDENCE=1` (`:25-26`) |
| **Council run → investigation** | **No** | `openInCellwright` has `run.id` in hand (`apps/web/app.js:1173`) but `send()` posts only `{session_id, question, use_council, model, reasoning}` (`:320`), and `sessions` has columns `sid, model, used_council, title, messages, updated` (`apps/sessions.py:35-37`) — **there is nowhere to put it.** The edge survives as an English sentence at the head of the transcript (`app.js:1180`), which `scripts/ab_score.py:42,73` then substring-matches to exclude Arm A |
| **Council run → prior Council run** | **No, and worse** | see below |

**The one loop primitive that exists is destructive.** `run_council(..., reuse_id=X)` sets
`run_id = reuse_id` (`apps/hypotheses.py:163`) and calls `store.create`, which is an `INSERT OR REPLACE`
resetting `rounds="[]"`, `hypothesis="{}"`, `designs="[]"`, `meta="{}"` (`apps/hypotheses.py:69-74`). **A
re-convene overwrites the deliberation it was refining.** M-7's progressive narrowing
(`tests/test_narrowing.py:73-78`) therefore leaves no record of what was narrowed *from*.

So the gap is not a missing flag. It is **two missing edges and one destructive write.**

### D10.3 — The design: Thread · Round · typed `informed_by`

Additive columns on the two existing tables. No new object graph, no new store; the `ALTER TABLE … ADD COLUMN`
migration idiom is already in place at `apps/hypotheses.py:40-43`.

**`council_runs`** gains:
- `thread_id TEXT` — the investigation thread. A fresh question mints one; a re-convene inherits it.
- `round_index INTEGER` — 0, 1, 2 … within the thread.
- `informed_by TEXT` (JSON) — the **typed** list of inputs beyond the question:
  `[{"kind":"investigation","id":"s_…"}, {"kind":"council_run","id":"h_…"}, {"kind":"literature","source":"…"}]`.
  Typed, because a boolean cannot distinguish *corpus-blind but literature-informed* — the distinction
  `tests/test_blindness.py:23` already encodes.

**`sessions`** gains `thread_id TEXT` and `from_hyp_id TEXT` — closing the Council→investigation edge. Three
touch points: the POST body (`apps/web/app.js:320`), the handler (`apps/server.py:169-256`), the INSERT
(`apps/sessions.py:75-78`).

**A re-convene stops being a re-write.** It becomes `round_index + 1` in the same thread with
`informed_by=[{"kind":"council_run","id":<prior>}]`, and the prior row is preserved. That change alone is
strictly better than today even if nothing else in D10 is built.

**Lineage is derived, never stored twice.** The chain walks the edges — `council_run → informed_by →
session → evidence.jsonl lines for that sid → run ids → manifest rows`. No node caches its ancestors'
contents; ids only, which is `evidence.py`'s own stated rule (`:14-16`).

**Blindness becomes a query, not a stamp.** `blindness_of(run_id)` returns the transitive **set of input
classes** — `{"literature"}` for a corpus-blind round, `{"literature","corpus"}` for an informed one. This
keeps D6a's point (c) (provenance metadata on a legitimate artifact) while dropping the boolean, and it lets a
later reader ask a *different* question of the same record than the one we thought to stamp — e.g. *was this
round informed by an investigation that only ever read designs below `MIN_SEEDS`/`MIN_GENERATIONS`
(`src/cellarium/support.py:32-33`)?*

**Surface.**
- `GET /api/thread?id=` — the ordered chain; a new route beside the hypothesis/session routes at
  `apps/server.py:606-617`.
- `GET /api/hypothesis_get` carries `thread_id`, `round_index`, `informed_by`; the detail pane already renders
  per-design lifecycle there (`apps/server.py:304-328`), so the review pane has a home.
- The run list (`HypothesisStore.list`, `apps/hypotheses.py:111-117`) groups by thread — *round 2 of 3*.
- **The feature is one button: "Re-convene the Council with what Cellwright found"**, on an investigation. It
  mints round N+1 with `informed_by` pre-filled. Today that loop is reachable only by copy-paste — and
  copy-paste is precisely the route that leaves no lineage.

**Ordering rule, converted.** D6a's *"a Cellwright-then-Council composite must not ship"* becomes a
**representation requirement**: that composite is legitimate and desirable, but it must be recorded as **two
rounds with an edge between them**, never one opaque call. Auditability is the deliverable, not prohibition.

**How the A/B evidence base stays measurable alongside it.** Because the cohort is designated at creation
(D10.1), informed rounds accumulating in `council_runs` do not touch it. Two changes make that robust rather
than merely lucky: (i) `scripts/ab_score.py` selects by ledger `run_id` (`M-10`); (ii) `run_ab.py` writes
`thread_id` + `round_index=0` + `informed_by=[]` at creation, so the pre-registered set is explicit in the
table too — a *record* of the designation, not a *recovery* of it. Round-0 rows then remain a superset of the
A/B cohort and can serve as an observational replication.

### D10.4 — What a user can ask that they cannot ask today

1. **"Show me the chain behind this claim."** Today the chain breaks at the Council→investigation edge — the
   evidence ledger has run ids and the launch queue has `hyp_id`, but nothing links a Cellwright answer to the
   Council run that framed it (`apps/sessions.py:35-37`).
2. **"Which of my hypotheses were refined *after* seeing data, and what did they see?"** Unanswerable today:
   `reuse_id` deleted the predecessor (`apps/hypotheses.py:163` + `:71-74`).
3. **"Did this conclusion ever leave the runs it started from?"** — i.e. was round 3 informed by an
   investigation that only read below the evidential floor (`support.py:32-33`)? A graph query under D10; a
   manual transcript read today.
4. **"Round 0 vs round 3, side by side."** The honest exhibit for what the loop bought — the uninformed
   hypothesis next to the informed one. Today round 0 is gone.
5. **"Which threads converged and which oscillated?"** Rounds-to-convergence *across a thread*, distinct from
   `meta.converged` (`apps/hypotheses.py:185`), which is convergence of one debate.

(1)–(4) follow directly from the two missing edges and the destructive write. (5) is **ARGUED** — a
thread-level convergence metric is proposed here, not measured.

## phnE1 typed `pseudo` — and the fur/tnaC degradation swap that came with it

`EG11283_RNA` (phnE1) is now typed `pseudo` in `reconstruction/ecoli/flat/rnas.tsv`, matching v3.0.1.
The reason is not a judgement call: the curated "protein sequence" for `PHNE-MONOMER` **contains stop
codons**, and the naive translation of the gene matches it 278/278 positions including the asterisks. It is
the conceptual translation of a pseudogene, not a protein. In K-12 MG1655 the phosphonate operon is cryptic
because phnE carries an 8-bp insertion that breaks the frame; the gene record still shows the scar (one
gene, synonyms b4103/b4104/b4583/ECK4096/ECK4097). Carrying it as an mRNA made the codon-aware elongation
path read past the end of its codon array into a Cython kernel compiled `wraparound(False)`.

Effect on the knowledge base: 4539 -> 4538 cistrons, 4310 -> 4309 monomers, `rna_data` unchanged at 3276
rows with identical ids (phnE1 has no TU of its own; it sits inside `TU00201[c]`), so no `ko_index` moves.
phnE1's own expression is negligible — 1.9735e-08 after fitting, rank 4197/4539 — so the direct
renormalisation of every other cistron is ~1.7e-6.

**THE PART THAT IS NOT ABOUT PHOSPHONATE, AND MUST NOT BE READ AS BIOLOGY.** `transcription.py:728`
estimates unmeasured transcription-unit degradation rates with a GLOBAL `fast_nnls` over the whole
cistron x TU matrix. That solve is **degenerate**, and removing one row flips a tie in it. Measured, the
largest movers are nowhere near the phn operon:

| TU | gene | before | after | change |
|---|---|---|---|---|
| `TU0-1283[c]` | **fur** | 2.888e-02 /s (t½ 24 s) | 1.267e-04 /s (t½ 91 min) | **228x slower** |
| `TU0-42514[c]` | **tnaC** | 1.267e-04 /s | 2.888e-02 /s | the two literally SWAP |
| `TU0-1281[c]` | uof-fur | 1.267e-04 /s | 2.610e-03 /s | 20x faster |
| `TU00085[c]` | tnaCAB | | | -7.1% |

1135 of 3276 TUs move at all; 7 move by more than 1%. mRNA *abundances* are essentially preserved (9 TUs,
1.96e-07 total absolute) — what changes is modelled *turnover*. `fur` is the global iron regulator and
`tnaCAB` is tryptophanase, for which the corpus carries a `plus_indole` condition. **A 228x change in fur
mRNA half-life arriving as a side effect of a phosphonate pseudogene is exactly the kind of thing that gets
misread as a finding later.** It is a degenerate-NNLS tie-break, it is real, and it is in the DEFAULT path.

Consequence for the corpus: any run produced after this change is on a new baseline and is not poolable
with earlier rows without checking `kb_sha256`. The degeneracy itself is a pre-existing fragility of the
ParCa fit that this change merely exposed, and it deserves its own investigation.

### MEASURED END TO END, 2026-08-03 (item 7) — the phenotype cost, the causal proof, and a hole in the mitigation

The paragraphs above were written from the knowledge base. Reproducing the corpus's multi-gene knockouts on
the Cellarium-native tree measured what they cost a *simulation*, and closed the causal chain by reversion.

**1. The phenotype cost.** `gltX+relA+spoT`, seed 0, 1 generation, steady-state, operons on, everything else
held fixed:

| arm | ppGpp mean | cellMass mean | vs fork |
|---|---|---|---|
| fork code + fork kb (`3b2f8ebd…`) | 372.0503 | 1413.5835 | — |
| **native code + fork kb** | **372.0503** | **1413.5835** | **2529/2529 timesteps bitwise identical** |
| native code + native kb, ParCa fit 1 | 267.5788 | 1421.6972 | **−28.08%** |
| native code + native kb, ParCa fit 2 | 267.5788 | 1421.6972 | −28.08% |

So **the ported CODE is inert** — on the wildtype control, 212 of 212 comparable biological columns are
bitwise identical, the only 17 that differ being `EvaluationTime/*` wall-clock instrumentation. **100% of the
observed difference is this one row of `rnas.tsv`.** The ppGpp gap is *systematic, not chaotic*: it grows
monotonically (−0.5% → −30.5%) while cellMass never diverges more than **0.925%**, unlike a genuine chaotic
split (the wildtype control's ppGpp sign-flips −15 → −1 → +10 → +25% and only opens *after* the masses
separate at step 1395).

**2. The causal proof.** Reverting `EG11283_RNA` to `mRNA` — one row, nothing else — and refitting:

| `exp_ppgpp` | fork (mRNA) | native (pseudo) | native + REVERTED |
|---|---|---|---|
| `gatZABC[c]` | 3.514768e-05 | **0.000000e+00** | **3.514768e-05** |
| `TU874[c]` | 2.351765e-06 | **0.000000e+00** | **2.351765e-06** |
| `TU0-1281[c]` (uof-fur) | 1.460350e-05 | 1.057383e-05 | 1.460350e-05 |
| cistrons | 4539 | 4538 | 4539 |
| entries differing vs fork | — | 2905/3276 (max 316.56%) | **0/3276 (max 0.00%)** |

**And it closes output-side, bitwise.** Running the same knockout on the reverted knowledge base reproduces
the fork EXACTLY: ppGpp mean **372.0503**, cellMass mean **1413.5835**, and **2529/2529 timesteps bitwise
identical on BOTH channels** (leading identical run = 2529 — the whole generation). One row of a TSV accounts
for **100%** of the difference between the fork tree and the Cellarium-native tree.

Note `gatZABC` and `TU874` are driven to **EXACTLY ZERO** in the ppGpp expression basis. The table above this
section lists the *degradation-rate* movers (fur/tnaC); these are *expression-basis* movers, and they are a
distinct consequence of the same degenerate solve. `TU0-1281` appears in both.

**3. The hole in the mitigation.** The paragraph above says to check `kb_sha256`. **`kb_sha256` cannot carry
that weight as written.** Two ParCa runs of the SAME image, same inputs, same `--cpus 14`, minutes apart:

    fit 1  94325a1e547f4ec631d1c9b1…      fit 2  9881c39e4528e74d7eb58be1…

Different hashes — but their `exp_ppgpp` is **bit-identical (0/3276)** and their simulations are **bitwise
identical over all 2530 timesteps** on both ppGpp and cellMass. So ParCa's *behaviour* is deterministic and
only its *serialisation* is not. `kb_sha256` is therefore sound as "same hash ⇒ same kb" but **UNSOUND as
"different hash ⇒ different experiment"**: it reports FALSE partitions. A comparability guard built on it
will refuse legitimate pooling and will silently inflate the count of distinct baselines. Invariant 2 in
`BACKLOG.md` (`F-HYG`) and the open `M-11` enforcement item both need this qualifier.

**4. Support standing — this is a SINGLE POINT, by Cellarium's own bar.** `support.coverage` on the design
the numbers come from (`multi_gene_knockout_0_8567d1a0`) returns `sufficient: false`, `n_seeds: 1`,
`max_generations: 1`, with its own warning: *"a value measured inside one generation is a TRANSIENT, not a
steady state, and adding seeds will not fix that."* The companion design
(`multi_gene_knockout_0_8dacc4fb`, pfkA+pfkB) returns `n_seeds: 0` — its raw is HF-only — *"This is an
ABSENCE, not a finding of zero."* Classify accordingly:

* **Identities, where n=1 is sufficient by construction** (a bitwise match cannot be seed-dependent): the
  code's inertness (2529/2529; 212/212 columns), `exp_ppgpp` 0/3276 after reversion, the cistron counts, and
  fit1≡fit2 (2530/2530).
* **Quantities that do NOT clear the bar and must be reported as one point**: the **−28.08% ppGpp
  magnitude** (1 seed × 1 generation × 1 genotype, on a cell with zero elongation for 100% of timesteps),
  and the graded dose values below. **Owed: ≥2 seeds × ≥2 generations, and at least one live-cell genotype,
  before this magnitude is quoted anywhere.**

**DECISION: phnE1 stays `pseudo`.** Reverting would put a stop-codon-bearing pseudogene back into
translation, which is worse biology than a shifted ppGpp basis, and the correction matches v3.0.1. It is
retained as the worked example of a *model correction whose blast radius exceeded its subject* — a
phosphonate pseudogene that moves the stringent response — alongside the tRNA charging port.

## D12 — Every simulated number carries its source (S2-2) — ACCEPTED 2026-11-25, code only

**Problem.** The integrity check (`integrity.audit`) could pair a number in Cellwright's prose with a run only when
the sentence named exactly one run: 11 of 140 claims in the stored answers. A sentence comparing basal (0.0123)
with KO:argS (0.0098) passed with the two numbers swapped.

**Decision.** Cellwright writes each number it takes from a tool result with its source, in brackets, where it
writes the number:

| kind | format | resolved by |
|---|---|---|
| a reading | `0.0098 [gene_knockout/KO:argS · growth_rate · 4 seeds]` | the named design's own run fields (`classify`): `matches`, `mismatched` (found only in another run: a swap), `unresolved` |
| a comparison's statistic | `-20.3% [gene_knockout/KO:argS vs wildtype/basal · growth_rate · effect_pct]` | a tool output naming both designs that contains the number; matched on magnitude, because the direction is usually written in words |
| a computed number | `0.797 [computed: 0.0098 / 0.0123]` | recorded as computed; its inputs are themselves cited |

Counts, seeds and generations need no citation; literature values cite their paper. In a table, each cell cites,
or the sources are listed under it. Implementation: `integrity.CITE`, `citations`, `_cited_status`,
`audit_cited` (in `audit` as "cited"); the rule is the first in `agent.SYSTEM`; the interface renders a citation
as a chip (`apps/web/app.js` inlineMd, `.cite`). Tests: `tests/test_cited_numbers.py` (including that the
prompt's own examples parse and resolve).

**Why this format.** The source is attached to the number, not to the sentence, so a swap is caught whatever the
prose says; the bracket names a design key and a channel, which are exactly what the run fields are keyed by, so
resolution is a lookup, not an inference. **Alternatives rejected:** footnotes (the number and its source drift
apart in editing); a structured JSON answer (unreadable as prose, and the interface and every eval that parses
answers would change twice); checking prose with an LLM (a model judging a model's numbers is the failure this
check exists to catch).

**Limits, stated.** Whether a comparison's word ("slower") agrees with its sign is not checked. An answer that
does not use the format is reported as `format_used: false`, not flagged number by number. Up to six plain words
may sit between a number and its bracket.

**Not yet validated (S2-2b, paid, your approval).** Whether both models actually comply, and whether answer quality
holds with 10-20% more output tokens. It rides along with K-2 at the freeze (D13), on the grounded arm's answers.

## D13 — Decisions of 2026-11-25: what is in sample, what MCP answers, what a new user gets, when K-2 runs

**Y10, in sample.** A condition the knowledge base's table holds is fitted by ParCa (growth and composition for
every row; expression of the active factors' targets), so those quantities are in sample; everything else in that
condition is emergent; perturbations are out of sample. Who decided to fit it is recorded
(`data/parca/condition_fits.json`, `scripts/condition_fits.py`): acetate and succinate were fitted by the base
simulator (upstream CovertLab commit 03b327f7, PR #895, 2020-06-08), so they were in sample before the campaign
existed; the campaign's own conditions (glc_* 2026-03-20, the 13 media 2026-04-15, starvation and anaerobic
nitrate committed publicly 2026-11-25) are attributed to the campaign and are out of sample for any run before
their fit date. *Why:* the old tag called acetate and succinate predictions, which inflated the growth law's
out-of-sample fit from the seven perturbations to nine. Implementation: `provenance.classify/tag(quantity, gene,
run_date)`; `rigor.fit_relation` counts a point in sample only if both channels are.

**Y11, MCP answers what Cellwright knows.** A client connecting over MCP must not get a different answer from the one
Cellwright gives. For a design the registry marks note-only (an operon-specific rRNA knockout), the raw tools
return the reading with the registry's note on how to read it, rather than refusing (`mcp._PERTURBATION_NOTE_ONLY`,
`how_to_read_this_design`). *Why:* Cellwright reads these designs with the note; refusing them over MCP made the two
surfaces disagree. Replay of the stored calls: refused 24 -> 2 (`evals/results/raw_gate_replay.json`).

**Y12, what a new user gets.** Cellarium's own parts of the campaign branch were pushed (8e7dd6c5: the graded
knockout variant, the starvation and anaerobic-nitrate conditions, the Docker fixes); the kinetic charging port is
held, because its licence is pending. A fresh anonymous clone resolves 27 of 33 unique registry dependencies (the six missing are all the held port's; first reported as 26 of 33, a unique count over the total); the three
records resting on the held port are named in `capability.BUILD`
(`evals/results/dependency_audit_public.json`).

**K-2 runs once, at the freeze.** K-2 measures what grounding changes, and the grounded arm is Cellarium itself
(registry, gate, tools, instructions, corpus, reader), which changed today in five places. A number measured now
would describe a system that will not exist at submission. Everything is built now (items, keys, freeze manifest,
a stubbed dry run, the cost estimate) and the paid run happens once against a recorded freeze (one tagged commit,
the registry hash, the corpus snapshot, model IDs and temperatures, the judge's prompt hash). Full spec: Platform Map v68,
Appendix M (K-2).

**Issue 3, the smaller results.** (a) *True labels:* one function, `labels.describe`, names every design on every
surface with its medium and a hazard class where the name misleads (`plus_nitrate` is aerobic glucose with nitrate,
not nitrate respiration); *why one function:* three surfaces had three phrasings, and the dataset's labels must say
the same. Publishing the relabelled dataset is a release decision, prepared locally. (b) *Falsifier designs:*
Council's falsifiers are checked against the hypothesis's own candidate designs when proposed, never against the
corpus, so the Council stays blind; a placeholder knockout tag is repaired only when exactly one candidate names a
gene, otherwise sent back. *Why so narrow:* a wider repair turned `condition/rich_amino_acids` into acetate. (c)
*Two-component sensors:* the reader adds back the sensor monomers wcEcoli's listener drops from phosphorylated
complexes, and says how much it added; *why in the reader, not the model:* the corpus already exists, and the fix
must apply to every run ever made.

**The BV-14 refit.** A knowledge-base edit is a new fit, recorded as one: `data/parca/fits.json` lists every fit
with its inputs (file SHA-256), why, whose decision, and its difference from the public branch; runs on it carry
its `kb_sha256` and are never pooled with the corpus fit.

**The transit-dir refusal.** `runner._evacuate` now refuses a design whose transit dir is another design's run
root (a plain knockout's), where it used to let the run proceed and wcEcoli delete the occupant. Found by the
BV-12 batch before any run was lost; the batch waits for the occupant's deposit instead.

## D14 — BV-14's validity gate, amended after its first evaluation — KEPT 2026-11-26

**What happened.** BV-14 runs on a refit (kb `9055ee3b`) that adds the anaerobic-nitrate condition. Its validity
controls were gated on the corpus fit's own runs (basal [1.86e-4, 3.06e-4], anaerobic [1.13e-4, 1.80e-4] per second).
The anaerobic control grew at 1.07e-4/s and closed its group.

**Why the gate was wrong, not the refit.** The refit is a fresh ParCa from the current tree, and a fresh build is a
different model from the corpus fit beyond the added condition ([KB_DIVERGENCE.md](KB_DIVERGENCE.md): amino-acid
kinetics moved up to 52%). The gate compared it with the wrong model.

**The amendment.** Each control must grow within 1.5-fold of its own fit's fitted growth (the condition's doubling
time): a sanity check that catches a broken refit, not a different one. The controls sit at 1.02x (basal) and 0.93x
(anaerobic); the corpus fit's own anaerobic runs sit at 1.22x theirs.

**Decision.** Changed after seeing the result, so recorded as such (the plan's `gates_amended`, the ledger) and put to
the user, who kept it on 2026-11-26. **Consequence, stated wherever BV-14 is reported:** BV-14 measures the fresh
build's nitrate response, not the corpus fit's; its rows sit in their own arm and are never pooled with the corpus.

## D15 — BV-14's result, and three defects it exposed — 2026-11-26

**In one line.** Under anaerobiosis the model's nitrate response at *nar* and *frd* is right-signed in transcription
and a tenth of the organism's in log<sub>2</sub>, unresolved in protein, and wrong-signed at *frd* once FNR is also
active; scoring it exposed a scorer bug, two registry records quoting the wrong fold-change table, and a comparison
path that pooled fitted models.

**The result (`evals/results/bv14_nitrate.json`).** Pre-registered readout, protein log<sub>2</sub> fold changes on
the refit, last generation, four nitrate against four anaerobic seeds: *narGHJI* &minus;0.69 to &minus;1.02, *frdABCD*
+0.82 to +1.02, against PRECISE-1K's +3.2 to +3.7 and &minus;4.5 to &minus;4.9; the all-gene correlation is null
(r = &minus;0.02, 2,698 genes). Opposite in sign, and not resolved: per seed, Welch p 0.36 to 0.48 (*nar*) and 0.12 to
0.18 (*frd*). Nitrate-anaerobic against aerobic, the model raises *frdABCD* (+2.78 to +3.04, p 0.03 to 0.05) where the
organism lowers it (&minus;1.06 to &minus;1.62).

**The diagnostic, post hoc, beside the readout (not instead of it).** The model transcribes *narGHJI* rarely: narG
protein rose at all in 4 of 12 generations per arm, so a four-seed protein mean records when bursts fell. Each run's
synthesis probability (RnaSynthProb, the function of the TF-bound state the bursts sample) answers the same question
with far less noise: nitrate raises *narGHJI* synthesis +0.25 (p 0.057) and lowers *frdABCD* &minus;0.47 (p 0.026),
where the fit asked for +1.29 and &minus;1.07 and the organism shows about +3.3 and &minus;4.7; *nirBDC* and *narK*
do not move (fit +1.97 and +1.16). Nitrate-anaerobic against aerobic, *frdABCD* synthesis rises +2.15 (p 0.001): FNR's
activation outweighs NarL's repression. The simulation's promoter occupancies are not the fit's: FNR 0.99 bound
against the fit's 0.78, CRP 0.22 and 0.07 against 0.38, ArcA 0.18 and 0.13 against 0.07. Which of these, or the
growth-dependent normalisation of synthesis probabilities (the nitrate arm grows at 0.58 per hour against its fitted
0.51), shrinks NarL's effect is not separated. Why post hoc: the readout returned the opposite sign; a reading of the
synthesis probability was added to see whether the model or the readout was wrong, and it is labelled as added after
the result everywhere it appears. The pre-registered readout's verdict stands as measured.

**Literature.** According to PubMed, NarL stimulates *nar* transcription in an *fnr* mutant as well as in the wild
type, so it does not act through FNR (Walker and DeMoss 1992, doi:10.1128/jb.174.4.1119-1123.1992); nitrate represses
*frdABCD* through NarL (Kalman and Gunsalus 1989, doi:10.1128/jb.171.7.3810-3816.1989); NarL acts at *nar* from about
200 bp upstream through an IHF-dependent DNA loop (Stewart 1993, doi:10.1111/j.1365-2958.1993.tb01704.x).

**Defect 1, the scorer (fixed).** The first scoring read the refit's runs with `reader.gene_lfc` directly (the
design-label wrapper would not reach them) and so skipped the wrapper's gene-symbol annotation: monomer ids joined no
b-number and the concordance reported INDETERMINATE for every contrast, a verdict word rather than an error. Now
`differential.annotate_lfc` is shared, the scorer refuses a join that matched no gene, and it checks that the reader
read every run it was given.

**Defect 2, the fold-change table (corrected).** ParCa loads `fold_changes.tsv` and then `fold_changes_nca.tsv`, and
the second's value replaces the first's for a pair both list. Two registry records and the BV-AN eval quoted
`fold_changes.tsv` alone: NarL at *narGHJI* +2.57 to +2.80 where the fit uses +0.58 to +1.75; BaeR at *mdtA* +3.39
where it uses +0.28; FNR at *nar* +0.80 to +1.54 where it uses +0.52 to +0.80, and "frdA has no FNR entry" where NCA
supplies +0.68 to +1.43 across *frdABCD* (read from the corpus fit's `sim_data.tf_to_fold_change`). The arabinose
record (AraC, no NCA entry) and DcuR at *dcuB* were right. The BV-2 figure's panel b had drawn the proxy as the
fitted inputs (narG +2.75 and +1.54, frdA 0); redrawn with the fit's +1.75, +0.53 and +1.12, the model still sits
near its input, so the figure's message stands. The records now state the fit's values; the guard test
reads both tables with ParCa's merge (`cellarium.fitted_fold_changes`) and pins the pickle's values as literals; both
records depend on `fold_changes_nca.tsv` (a new user's clone resolves 29 of 35 unique references, was 27 of 33).

**Defect 3, pooled fits in the comparison path (fixed).** `differential._design_run_roots` read
`store.list_results`, which carries no arm (knowledge base, operon build, elongation model), so every comparison that
resolved runs by design label pooled whatever fits held that label. `wildtype/basal` resolved 4 runs of fit `5f19d040`
beside the corpus fit's 17, but they sit in `runs_seed_aars`, an output tree the reader container does not mount, so
the reader dropped them and every artefact disclosed them as unreachable: never read. What was read is BV-14's refit
runs, under `runs/` and so reachable once indexed: BV-5 (computed 2026-11-25 17:59, 44 minutes after the refit's basal
control was indexed) took 18 basal runs, one of them that control; from 2026-11-26 `condition/no_oxygen` also took the
refit's 5 beside the corpus fit's 8, for any tool call. The mount boundary hid the older pooling by accident, not by design. Now a design
resolves within one arm (the default `analysis_rows` takes, crashed rows still included), and a comparison
(`_pair_run_roots`) pins the arm its two designs share. Only those two designs have runs in more than one arm on this
machine. The artefacts that compared against them were regenerated and diffed, every leaf:

| Artefact | Computed | After the fix |
|---|---|---|
| `regulation_scope.json` | 2026-11-25 16:14, before any refit run | every number identical; the 4 unreachable runs are no longer resolved at all. Stored file kept: a rewrite would also carry an unrelated corpus-growth change (the growth law's r 0.779 to 0.780) and lose two hand-added notes |
| `anaerobic_response.json` (BV-AN) | 2026-11-25 16:13, before any refit run | every protein, run count and PRECISE-1K value identical; its fold changes now the fit's (above), and a depth-1 synthesis readout added |
| `bv4_expression.json` (BV-4) | 2026-11-25 12:50 | 0 leaves differ |
| `bv5_proteome.json` (BV-5) | 2026-11-25 17:59, refit control in its reference | basal reference 18 runs to 17; every statistic moved by 0.008 or less (acetate's fitted-gene Pearson 0.271 to 0.263; absolute Spearman 0.727 unchanged, n 2,124 to 2,121); the conclusion stands |
| `data/sci2_count_floor_sweep.json` | 2026-09-11 | not regenerated: pydeseq2's worker pool broke on the re-run, and its run list was never stored, so whether its reference held a foreign run cannot be settled; it predates BV-14, so the only candidates are the 4 runs the Docker reader cannot reach |

**BV-AN re-measured on the corpus fit (depth 1, 8 anaerobic against 12 basal runs).** Synthesis: *narGHJI* +1.84,
*frdABCD* +1.95 log<sub>2</sub> (the fit asked +1.46 and +1.86; the simulation again binds FNR at 0.99 against the
fit's 0.78), against PRECISE-1K's +3.98 and +3.21. So the model's nitrate-reductase transcription rises about
fourfold where the organism's rises sixteen-fold: the record's refusal of the magnitude stands, and its text now gives
the transcription figure beside the protein one (its protein, few copies per cell, reads under twofold within a
generation).

## D16 — BV-14d pre-registered: occupancy-clamped runs, and why the fit's NarL effect shrinks — 2026-11-26

**In one line.** Before running anything, the model's own equations put most of BV-14's attenuation in how the
simulation combines factors at one promoter, not in occupancy; BV-14d tests both, with every run checked before it
counts.

**Decided by the user** (2026-11-26): "Go for the BV-14d occupancy-clamped runs. Make sure that test failures and
defective runs are discarded."

**The pre-analysis (analytic, from the model's code; scratch, numbers in the plan).** With ppGpp regulation on, a
promoter's synthesis probability is `basal(ppGpp) x (1 + sum(delta x bound))`, renormalised over every transcription
unit (`transcript_initiation.py`). Evaluated with expected occupancies:

| Scenario | nar, nitrate against anaerobic (log2) | frd |
|---|---|---|
| the fit's own target (`rna_synth_prob`) | +1.29 | &minus;1.07 |
| the fit's occupancies and ppGpp, the simulation's equations | +0.48 | &minus;0.23 |
| the runs' occupancies and ppGpp (BV-14 as run; observed +0.25, &minus;0.47) | +0.45 | &minus;0.30 |
| FNR and NarL held at the fit's occupancy (BV-14d, F arms) | +0.55 | &minus;0.32 |
| FNR held off, NarL at the fit's (BV-14d, O arms) | +1.45 | &minus;1.13 |

So the fit's targets are out of reach of the simulation's equations even under the fit's own assumptions. The
encoded effects at narGHJI are FNR +3.24 and NarL +1.81 inside one multiplier: NarL's was fitted on aerobic nitrate,
where FNR is off and it gives the full 2.6-fold; under anaerobiosis FNR's term dilutes it to 1.45-fold, while ParCa
built the combined condition's target by multiplying fold changes (2.45-fold). Occupancy (FNR 0.99 in the runs
against the fit's 0.78) is worth about +0.1, and the runs' ppGpp (anaerobic 62, nitrate 40 uM, where the fit assumed
105 and 93) about +0.16.

**The experiment** (`evals/plans/bv14d.json`, design_sha256 f3144ef9..., committed before any run): on the BV-14
refit, FNR at the fit's 0.781 or held off (the fnr-mutant state Walker and DeMoss 1992 measured), by NarL off
(anaerobic) or at the fit's 0.877 (nitrate); 3 seeds x 3 generations per cell, and two 1-generation controls that
gate their groups on growth and on the clamp holding. The clamp is a patched `tf_binding.py`
(`model_patches/processes/tf_binding.py`: the model's own file plus an override read from the environment, inert
without it), mounted only for a design carrying `params.tf_occupancy_clamp`, which is an identity axis (its own label
`#occ:`, run directory and launch key), so clamped runs can never pool with BV-14's.

**Which runs count.** A run is discarded, listed with its reasons and never averaged, when it fails QC or leaves a
generation undivided, when a clamped factor's achieved bound fraction is more than 0.05 off its target (any binding
at all for a factor held off), or, in the fit arms, when it grows outside 1.5-fold of the fitted rate. Binding is
capped by a factor's free active molecules, so a clamp can be in force and still not hold; the achieved fraction,
not the set probability, decides.

**Decision rules.** D1: phi, the share of BV-14's nar attenuation the fit clamp restores; predicted about 0.1, and
phi >= 0.5 would make occupancy the main cause. D2: NarL's nar effect with FNR off minus with FNR at the fit;
predicted about +0.9, supported at >= 0.5 with z >= 2, rejected below 0.25.

## D17 — The envelope refuses a shift that moves the replication threshold (CRIT) — 2026-11-26

**In one line.** The model reads its replication threshold from the current medium at every step, so a shift between
media with different doubling times makes the cell initiate and divide early. Cellarium now refuses to launch, read or
answer such a shift unless the cell starts fitted to the medium it runs in.

**Decided by the user** (2026-11-26): "Close the envelope gap for now."

**The defect.** `chromosome_replication.py` reads the critical initiation mass twice. At startup it uses the doubling
time of the condition the cell was fitted for. At every step it uses the doubling time of the current medium
(`nutrient_to_doubling_time[current_media_id]`), which replaces the startup value before it is used. The threshold is
975 fg at 25 or 44 minutes, 734.6 at 82, 590.0 at 100 and 423.4 at 136, the same in all five knowledge bases on disk.
A diagnostic run shows the mechanism:

- **The run.** Corpus fit, seed 0, oxygen removed at 600 s.
- **At the shift.** The threshold drops from 975 to 590 fg in that step. The cell's mass per origin goes from 0.73 to 1.21 times the threshold, and both origins fire at once.
- **The control.** The same cell had not reached the threshold even by 1,500 s.

In well4cell rc2:

- Glucose-fitted cells moved into acetate mid-run divide at a median 2,251 s, 17% within 10 minutes, against 4,343 s for cells fitted to acetate.
- Moved into no oxygen, they divide at 2,238 s against 4,627 s.
- Both are faster than unshifted glucose cells (2,879 s).

Real cells hold their pre-shift division rate for about an hour after a downshift and pause initiation through ppGpp.
The code is byte-identical in Covert lab wcEcoli master and the same in vEcoli master, and it has been there since the
media-timeline feature of April 2019. The existing carbon-switch refusal was this defect seen from one side.

**What changed.**

- `envelope.threshold_step` refuses any timeline event that moves the threshold, upshifts included.
  - Two doubling times share a threshold exactly when they are equal or both at most 44 minutes.
  - A tf_activity variant with a timeline is refused, because its fitted condition cannot be read from the design.
- The registry record `replication_initiation_after_a_nutrient_shift` holds in no mode. Its question is refused through
  a new gate dependency, `cell_cycle_after_a_shift`. The read-side gate refuses reading a design whose tag carries a
  crossing timeline.
- The dependency audit gains three references, and its public half now reads the branch through the GitHub API. That
  reading reproduced the 2026-11-25 clone's 29 of 35 before the references were added, and gives 32 of 38 now.

**Rationale.** Refusing is free and local, and reversible once the model is fixed. Leaving the gap open lets the
Council, Cellwright or any public user produce a run that completes normally and is wrong, which is this project's
worst failure mode.

**Intuition.** The threshold should belong to the cell, but it belongs to the medium's label. So the label can change
faster than any cell could.

**Limitations.**

- **One table, five fits.** The envelope reads the overlay's condition table, but runs read their arm's knowledge base.
  The five on disk were measured, and they differ only for phosphate starvation (44 minutes in the three older fits,
  100 in the others). The rule judges every view, but a sixth fit would need measuring again; a test pins the overlay
  table so a change is caught.
- **Hashed timelines.** A knockout's label carries its timeline as a hash, so the read-side gate cannot check it. The
  corpus holds no such crossing design.
- **Known-fault scripts.** The E2 glucose-removal arm and the phosphate-removal arm of the known-fault scripts are now
  refused at launch, as the E1 arm already was. Their recorded results stand.

**Checked.**

- **Every mutation fails tests.** Breaking the threshold comparison fails 8 tests, dropping the older-fit view 2, and
  breaking the read gate or the tf_activity refusal 1 each.
- **Committed plans.** Every design in the four committed plans (154 runs) passes.
- **Corpus timelines.** Every corpus timeline passes. Fixed on the way: the corpus-timeline test now reads the fitted
  condition from a run's label when its argv is not indexed, which is how BV-12's three dead knockouts had failed it.

## D18 — BV-14d's result: the attenuation is how factors combine, not occupancy — 2026-11-27

**In one line.** Holding FNR and NarL at the fit's occupancies restores under a third of BV-14's lost nitrate effect
at nar (phi 0.30), while holding FNR off raises NarL's effect from +0.56 to +1.44 log2 (1.5-fold to 2.7-fold). The simulation adds
co-activators' effects inside one multiplier, so FNR's large term dilutes NarL's, and the model's own equations
predicted both clamped effects to within 0.02 log2.

**Decided by the user** (2026-11-26): "Go for the BV-14d occupancy-clamped runs. Make sure that test failures and
defective runs are discarded." Pre-registered in D16 (plan design_sha256 f3144ef9).

**Which runs counted.** Of 14 planned runs, 13 finished. The pre-registered rules discarded 3, listed and never
averaged:

| run | why discarded |
|---|---|
| O1-s331 (FNR off, no oxygen) | Crashed in generation 2. FBA refused a negative biotin target: the RNA/protein ratio fell to 0.1355, where the biomass splines (fitted on 0.2 to 0.469, extrapolated below) turn negative. Named in `failures.KNOWN` (bf41701). |
| F1-s301 (fit, no oxygen) | Grew at 1.51x the fitted rate; the limit is 1.5x. |
| F2-s301 (fit, nitrate) | The NarL clamp did not hold: 0.877 in generation 0, then 0.62 and 0.51. A clamp sets the probability of binding but cannot create the factor: the free phospho-NarL pool ran short. |

That left valid seeds F1 300, 302; F2 300, 302; O1 330, 332; O2 330, 331, 332. Every arm had the two seeds a
contrast needs.

The batch had also skipped O1-s332, under a rule broader than its docstring: it blocked on any seed's failure, not
only on the first run's. The rule was fixed (bf41701), and the registered seed ran unchanged from a one-run plan
(`evals/plans/bv14d_o1s332.json`). O2-s331 and O2-s332 also ran from one-run plans at a 30 GB disk floor, to use a
machine that was otherwise idle. No run was ever owned by two processes.

**The result** (`evals/results/bv14d_clamp.json`; nitrate against anaerobic, log2, last generation):

| operon | NarL's effect, FNR at the fit | NarL's effect, FNR off | interaction (z) | predicted (D16) |
|---|---|---|---|---|
| narGHJI | +0.563 | +1.439 | +0.871 (4.75) | +0.55, +1.45 |
| nirBDC | +0.651 | +2.070 | +1.421 (4.71) | — |
| narK | +0.305 | +1.286 | +0.977 (5.33) | — |
| frdABCD (NarL represses) | &minus;0.032 | &minus;0.852 | &minus;0.815 (&minus;2.74) | &minus;0.32, &minus;1.13 |

- **D1, occupancy: "occupancy restores a minor share" (phi 0.297, against 0.5 for occupancy to be the main cause).**
  - The registered prediction was about 0.1. It subtracted the 0.20 by which the algebra had over-predicted
    BV-14's unclamped runs.
  - Under the clamp that offset did not appear: the uncorrected algebra (+0.549, phi 0.28) is what the runs show (+0.563, phi 0.30).
  - Why the unclamped runs fell 0.20 short is not established. One candidate is their step-to-step variation in
    binding, which an expected-value calculation averages away.
- **D2, additive dilution: "supported" (I +0.871, z 4.75, against I >= 0.5 with z >= 2).**
  - The two other NarL-activated operons agree, and frd shows the mirror image: NarL's repression also grows when
    FNR is off.
  - The frd interaction (&minus;0.815) matches the predicted difference (&minus;0.80). Its absolute values sit about
    0.28 above the algebra in both arms (BV-14's unclamped runs sat 0.17 below it). The rules used differences, which
    such an offset cancels.

**Robustness** (`evals/results/bv14d_robustness.json`, post hoc, NOT pre-registered; no decision changes):
- **Every generation.**
  - nar interaction: +0.85, +0.94 and +0.87 (z 6.1, 5.4, 4.8) in generations 0, 1 and 2.
  - phi: 0.42, 0.20 and 0.30, all under 0.5.
- **Without the discards.** Adding F1-s301 and F2-s301 back moves phi to 0.29-0.31 and I to 0.86-0.87.
- **Composition.**
  - Every run starts at an RNA/protein ratio of 0.165-0.172, below the splines' fitted range, and generation 0
    spends 42-100% of its steps there.
  - By the last generation every valid run is in range except F1-s302.
  - Generation 0 (extrapolated) and generation 2 (in range) give the same interaction, so the extrapolation does not
    drive the effect. It is a limitation of every anaerobic run on this refit, and of most acetate runs in the corpus
    (BACKLOG RP).

**Rationale.**
- BV-14 found nitrate raising nar synthesis +0.25 log2 where the fit asked +1.29, with FNR bound at 0.99 where the
  fit assumed 0.78. Two explanations predict different things:
  - Occupancy: if the cause were occupancy, clamping both factors at the fit's values would restore the effect.
  - Combination: if the cause is how the simulation combines factors, it would not, and removing FNR would enlarge
    NarL's effect.
- The 2 x 2 separates the two in one experiment, on the refit where BV-14 ran, with the clamp verified per run (the
  achieved bound fraction, not the set probability).

**Intuition.**
- At narGHJI the encoded effects are FNR +3.24 and NarL +1.81, and the simulation computes
  `basal(ppGpp) x (1 + 3.24 x 0.78 + 1.81 x 0.88)`.
- With FNR's term present, adding NarL's raises the multiplier from about 3.5 to 5.1, which is 1.45-fold. With FNR off
  it raises it from 1 to 2.6, which is 2.6-fold.
- The fit built the nitrate condition's target by multiplying the factors' fold changes, which no setting of
  occupancy can reach under an additive rule.

**What it says about the biology, and what it does not.**
- According to PubMed, Walker and DeMoss 1992 ([DOI](https://doi.org/10.1128/jb.174.4.1119-1123.1992)) found two things:
  - nitrate stimulation of nar persists in an fnr mutant;
  - NarL stimulates both the FNR-dependent and the FNR-independent mode of transcription, acting on RNA polymerase
    directly rather than through FNR.
- That is qualitatively what a multiplicative action would look like. The abstract gives no fold changes, and PMC has
  no full text, so whether the real fold induction is the same with and without FNR is not established here.
- The discriminating quantity is nitrate's fold induction of nar in an fnr mutant against wild type:
  - the model's additive rule makes it about 1.8-fold larger in the mutant (2^0.87);
  - a multiplicative rule makes the two equal.
- **Checkable in the lab: yes.** The quantity is that fold-induction ratio. Cellarium names the quantity; it does not
  write the protocol.
- **The FNR-off arms are the model's fnr null for transcription.** Read that way, they can be set beside measured fnr
  mutants (post hoc, from abstracts; qualitative).
  - In the model, removing FNR cuts nar synthesis 3.2-fold without nitrate and 1.7-fold with it, and narK 5.2-fold
    and 2.6-fold.
  - According to PubMed, an fnr mutation "prevented enzyme induction under any conditions" for nitrate reductase
    ([Stewart 1982](https://doi.org/10.1128/jb.151.3.1320-1325.1982)).
  - narK expression was "fully dependent on narL+ and fnr+"
    ([Stewart and Parales 1988](https://doi.org/10.1128/jb.170.4.1589-1597.1988)).
  - The nar transcript was "greatly reduced in an Fnr- mutant"
    ([Li and DeMoss 1987](https://doi.org/10.1128/jb.169.10.4614-4620.1987)).
- So the organism behaves close to an AND gate: a multiplicative rule with a very low FNR-independent base. The model's
  additive rule gets both halves wrong in the same direction:
  - FNR matters less than measured;
  - NarL matters more without FNR, where in the organism it barely acts.
- One structure explains BV-14's attenuation, this weak FNR dependence, and the frd sign error BV-14 found where two
  fitted factors meet. That is the case for a registry record (COMB-REG).

**Limitations.**
- **Seeds and statistics.** Seeds are not biological replicates. Three arms had two valid seeds, and the z treats the
  standard error as known, which is generous at that n. The closer evidence is that the effects matched the
  pre-registered algebra to within 0.02 log2, in every generation.
- **Readout.** The readout is synthesis probability, not protein. nar is transcribed about once a generation in the
  model.
- **What the clamp holds.** The clamp fixes binding, not the factors' other effects on the cell. FNR-off arms ran at
  higher ppGpp (62-88 uM against 42-60 uM in the valid fit-arm runs), within-arm contrasts throughout.

**Checks.**
- `tests/test_bv14d_clamp.py` (the validity rules and the interaction).
- `tests/test_bv14d_robustness.py` (the robustness arithmetic). Its recomputation on the registered seeds must equal
  the registered interaction, or it refuses to write.

**Follow-ups (proposed, not done).**
- **A registry record.** A factor's fold effect at a promoter that another factor also activates is attenuated in the
  model, so questions about fold induction at multi-factor promoters get the caveat.
- **Shared with BV-14's write-up.** The finding goes into BV-14's write-up and the Platform Map.

## D19 — A registry record for activators that combine at one promoter (COMB-REG) — 2026-11-27

**In one line.** Where two or more activators are bound at one promoter, the simulation adds their effects inside one
multiplier while the fit built the combined target by multiplying their fold changes. A reading there is now answered
with a caveat that says which way it errs and by how much; it is never refused.

**Decided by the user** (2026-11-27): "Add the co-activator registry record."

**What changed.**

- **The record.** `capability.combined_activation_at_a_promoter` holds in every elongation mode and carries the new
  field `caveat`.
  - The caveat names the rule (`basal(ppGpp) x (1 + sum of effect x bound)`, `transcript_initiation.py`) and the
    fit's contrary rule (`fit_sim_data_1.py::buildCombinedConditionCellSpecifications`). Upstream's own docstring
    there says multiplying "might not be appropriate".
  - It quotes BV-14d's measured dilution: NarL's nitrate effect at narGHJI is +0.56 log2 with FNR bound and +1.44
    with FNR held off. The algebra predicts +0.55 and +1.45.
  - It says how the organism differs (post hoc, abstracts): fnr mutants lose nitrate induction (Stewart 1982), and
    narK needs both fnr and narL (Stewart and Parales 1988).
  - It says what a reader must do: name the co-activators, and do not read one activator's effect without the other
    as the organism's.
- **The question gate.** A new dependency, `combined_activation`, is named in the parser's vocabulary and its
  instructions. An answered question that needs the record carries the caveat in its notes, as G-1's "calibrated,
  not predicted" label does.
- **The read path.** A design whose tag puts FNR and NarL on the same promoters at once carries the caveat in the
  result's `capability.caveats`, and the call is never refused. That means `oxygen_plus_nitrate` (the
  no_oxygen_plus_nitrate condition, or a timeline into that medium) and any occupancy-clamped design (`#occ:`).
- **The dependency audit.** It gains three references, two of them new symbols (`promoter_init_probs`,
  `get_delta_prob_matrix`), both resolving at the commit. The totals are now 47 references, 40 unique, 33 at the
  commit. A new user's clone resolves 34 of 40 (was 32 of 38); the same 6 held-port references are missing.

**Rationale.** BV-14d separated the cause from occupancy (D18), and the rule biases every reading at such a promoter
in a known direction by a computable amount.
- A refusal, the treatment BV-AN got, would withhold a reading whose direction is right and whose bias the registry
  can state.
- Silence would let "nitrate induces nar +0.56 log2 anaerobically" travel as the model's prediction.

**Limitations.**

- **One instance, not a list.** The registry names one instance and does not enumerate every promoter with several
  fitted activators.
  - Enumerating them needs the fit's per-gene factor tables, which are model-derived data under the held README
    sentence (P3).
  - A fold change read at another such promoter carries the caveat only when the question names the combination,
    through the gate. The read path cannot see it from the design alone.
- **Abstracts only.** The organism's AND-gate behaviour is from abstracts (D18). The fold values that would size it
  are COMB-LIT.

**Tests.** `tests/test_combined_activation.py` (9). Each new piece was mutated in turn, and a test failed each time.

## D20 — Cellwright's tool list was refused by the API from 2026-10-28; the copy sent no longer carries a top-level anyOf — 2026-11-27

**In one line.** The free token counter, run before the first paid discovery run, refused Cellwright's tool list. The
`chart` tool's schema carried a top-level `anyOf`, and the Messages API refuses that with a 400, confirmed with a live
one-tool call. Every live Cellwright turn sends the whole list, so every live Cellwright call had failed since
2026-10-28.

**How it got in, and why nothing saw it.**
- ENUM-4 (261b946, 2026-10-28) declared `chart`'s one-of-three run argument (`result_id`, `results` or `design`) as
  `anyOf` branches. That is standard JSON Schema; it is also not what the API accepts.
- Every test client is a fake that does not validate schemas.
- No live Cellwright session ran between that commit and today. The A/B's live sessions are from September, the
  27-item grounding pilot from 24 August, and the app's session store holds none saved after 8 September.

**What changed.**
- `agent._api_tool` builds the copy sent to the API without top-level combinators, and states the requirement in the
  description: "Give at least one of: result_id, results, design".
- Cellarium's own table (`tools.TOOLS`) keeps the branches, because the conformance and trajectory checks read them.
- The full list (74 tools) is now accepted by the token counter, at 39,394 input tokens for a first call, and the
  `chart` copy by a live call.
- `tests/test_api_tool_schemas.py` applies the API's rule to the agent's list and to every forced tool in the package.
  It was watched failing on `chart` first.

**Limitation.** The test encodes the one rule the API enforced here. It is not the API's validator, so a different
schema rejection would still be found only by a live call. The paid-run recipe's free count before each new kind of
run is that live check.

## D21 — S2's comparison arm: a graded knockdown with ppGpp held at basal — 2026-11-27

**In one line.** `params.ppgpp_clamp = "basal"` on a graded knockdown holds ppGpp at the fitted basal concentration,
so the stringent response cannot raise it. This is the comparator the discovery campaign's S2 needs: does the
stringent response soften the growth cost of a synthetase shortfall, as it does in B. subtilis (Parker et al. 2020)?

**Decided by the user** (2026-11-27): "proceed with ... the stringent-response question's comparison arm".

**What changed.**
- **The variant.** Cellarium's own graded variant (`model_patches/variants/graded_gene_knockout.py`) reads
  `GRADED_KO_PPGPP_CLAMP=basal`.
  - It sets what upstream's `ppgpp_conc` variant sets for a factor of 1: no RelA or SpoT synthesis or degradation,
    and `force_constant_ppgpp`.
  - It applies the clamp at index 0 too, which is the clamped control.
  - Without the variable, nothing changes.
- **Identity.** The clamp is an identity axis: label `#ppgpp:basal`, run directory `__ppbasal`, and the launch queue's
  key.
- **The runner.** It mounts Cellarium's copy of the variant for a clamped design only, replacing the checkout's copy at
  the same container path.
- **Refusal before launch.** The runner refuses a clamp on any other variant or in a kinetic mode: either would run
  unclamped under a clamped label.

**A confound, recorded.**
- `force_constant_ppgpp` also moves metabolism's biomass targets from the RNA/protein path to the doubling-time path
  (RP, re-verified the same day). So the clamped arm differs from the free arm in two respects.
- The S2 contrast is an interaction: the knockdown's effect with ppGpp free against held. That cancels what the two
  paths share at basal growth, but not how they diverge under the knockdown.
- The read must report the free arm's RNA/protein ratio beside the result.

**What exists and what must run.**
- The corpus holds argS at 5%, 10%, 25% and 50% expression, 4 seeds each, with ppGpp free.
- It holds ppGpp clamps at 0.2x, 0.6x, 1.6x and 2.0x, but no 1x control.
- The clamped arm and its control are new runs. The S2 Council and Cellwright session propose them.

## D22 — CRIT tier 1: the replication threshold relaxes instead of jumping, without copying model code — 2026-11-27

**In one line.** `params.initiation_threshold = "relaxed"` makes the critical initiation mass relax towards a new
medium's value over about one doubling time, as a closed-form function of the run's timeline and absolute time. A run
in which no event moves the threshold calls the model's own function unchanged.

**Decided by the user** (2026-11-27): "proceed with ... the first-tier fix for the replication threshold".

**How, and why this way.**
- **The spec's plan (CRIT_FIX_SPEC s.6, local)** was a patch to `chromosome_replication.py` on the campaign branch.
  That file is Stanford-licensed, the checkout is read-only here, and the licence bars redistributing its code.
- **What was built instead.** A hook, `model_patches/hooks/initiation_threshold.py`, which is Cellarium's own code.
  - It runs in place of the model's `runSim.py`.
  - After the model's own `ChromosomeReplication.initialize` has run, it replaces the process's threshold function with
    `RelaxedThreshold`, then runs `runSim.py` as `__main__`.
  - Every generation of a manual run happens in that one process.
  - Absolute time crosses division, so a daughter needs no inherited state.
- **The formula:**
  - on [t_k, t_k+1): M(t) = M*_k + (M(t_k) - M*_k) exp(-(t - t_k)/T_k), with T_k = tau_k / ln 2.
  - M(t_0) is the model's own startup value.
- **Identity, launch and the envelope.**
  - An identity axis: label `#it:relaxed`, directory `__itrelaxed`, the launch key.
  - `"medium"` names the model's own rule and labels like no setting.
  - The hook is mounted at `/cellarium/initiation_threshold.py`, and the command is prefixed with it.
  - The envelope now admits a threshold-moving shift under `relaxed`, with tier 1's limits in its reason.
  - Reading such a run stays refused: the registry record does not move until the shift panel passes.

**Validation, pre-registered** (`evals/crit_t1.py`, plan `evals/plans/crit_t1.json`, 20 runs).
- **V1, static identity.** Basal; acetate and no oxygen started fitted; an amino-acid upshift, both sides at the cap.
  The model's rule against the relaxed rule must give identical listener tables, all but the wall-clock table.
- **V3, shift panel.** Oxygen removed, and oxygen restored, 3 seeds x 3 generations under both rules.
  - The model's rule is the negative control.
  - Acceptance: no step above 5 fg in the relaxed threshold; no generation shorter than 600 s; and the median
    post-shift generation at least the unshifted glucose 2,879 s.
- **Left out: acetate mid-run.** The envelope refuses it for a second, independent reason, the carbon switch, so it
  would confound. A3 is therefore decided on one downshift.
- **Offline tests.** `tests/test_initiation_threshold_hook.py` covers V2, the closed form; it was run against a
  stand-in for the model's units. `tests/test_initiation_threshold_design.py` covers the wiring.

**Limitations (tier 1).**
- T is phenomenological, tied to a quantity the model already uses.
- After a downshift the threshold still falls over the next generation, so initiation comes somewhat early. There is
  no ppGpp pause; that is tier 2.
- A sinusoidal medium is refused.
- Upstream reporting (vEcoli) was not part of the decision and is not done.

## D23 — The launch queue refuses a parameter nothing reads, and resolves a graded design — 2026-11-27

**In one line.** The first live discovery run (S1) queued five proposals "none blocked" although four could not run as
proposed. Two gaps let that happen, and both are now closed before anything reaches the queue.

**The two gaps.**
- **Graded designs went unresolved.** `launch.propose` resolved the gene and index for plain and multi-gene knockouts
  only. Three graded designs with condition "basal", no gene and an unread `knockdown_level` went to the queue, to fail
  at launch at best.
- **Unread parameters passed silently.** A relA knockout carrying `co_knockdown: {leuS: 0.5}` would have run as a plain
  relA knockout while the queue, and the person approving it, saw a double perturbation. What is approved and what runs
  must not differ, and this is the shape in which they do.

**What changed.**
- **Accepted parameters.** `launch.propose` accepts a parameter only if the manifest declares it
  (`IDENTITY_AXES` / `NOT_IDENTITY_AXES`). The refusal lists what is accepted.
- **Graded designs.** A graded design is resolved to one gene and a level, with the condition set to `KO:<gene>` and
  `variant_index = ko_index * 10 + level`. Its refusal names the level-to-expression table.
- **The five proposals.** All five were rejected, the wild-type control with them so the panel is re-proposed whole.
  Cellwright is told why in a follow-up turn of the same session, recorded verbatim.
- **Tests.** `tests/test_launch_proposal_vocabulary.py`. The identity-axis census
  (`test_every_params_key_in_use_is_classified`) independently flagged the two unread keys in the real queue; it now
  skips rejected requests, which never run.

## D24 — The queue resolves every index a variant reads, and a label keeps a condition design's timeline — 2026-11-27

**In one line.** The discovery runs' second round of proposals found D23 incomplete. A variant that reads its index as
a meaning now gets the index its design names, or the proposal is refused. A label now keeps the timeline that a
condition design carries.

**What the second round found.**
- **rRNA knockouts got a random dose.** S4b's `rrna_operon_knockout` proposals carried `num_operons_to_delete` and no
  index. The runner falls back to a content hash, and the variant knocks out `index % 6` operons, which is a random dose
  under the requested label. Indices 7 to 18 also set the variant's own medium and timeline, which override the run's
  `--timeline`, so a shift asked of them never happens.
- **The ppGpp control had no index.** S2's ppGpp-clamped control can only be named by its multiplier, and nothing
  resolved that to the variant's index.
- **The level table invited a misreading.** S2 proposed its "clamped control" as graded level 1. Level 1 is expression
  0, a full argS knockout. The table the queue printed read "1: 0", which reads as "no knockdown". The request was
  rejected before it ran.
- **A shifted design shared a label with a static one.** A non-knockout design with a condition and a timeline lost the
  timeline from its label unless it also set an initial condition. A shifted rRNA knockout would have pooled with the
  static ones.

**What changed.**
- **The queue's resolvers** (`launch.propose`).
  - `rrna_operon_knockout`: the index is the operon count (1 to 6) and the condition is `minimal|rRNA_KO:<n>op`. A
    timeline on indices 7 to 18 is refused.
  - `ppgpp_conc`: the index is resolved from the condition (basal or with_aa) and a multiplier in the variant's table
    (0.2 to 2.0 in steps of 0.2). The condition becomes `<group>|ppGpp:<m>x`.
  - Every other family that reads its index (`condition`, `tf_activity`) must carry one.
  - The condition is derived from the index even when the index is given. S4b's re-proposal passed `variant_index`
    with condition "basal", and its 2-, 4- and 6-operon arms would have shared one label. An index that disagrees with
    `num_operons_to_delete` or `multiplier` is refused. The three arms were re-queued unchanged through the corrected
    resolver, linked to their originals, which were rejected.
- **The level table** now says "1: 0 (a full knockout)".
- **The label.** `manifest._design_tag` adds the timeline's tag to a condition design that has a timeline and no
  initial condition. No existing label changes: the corpus's 14 timeline-perturbation rows are labelled by their
  timeline, and the 6 BV-12 rows carry an initial condition.

**Tests.** `tests/test_launch_index_resolution.py`, watched failing first.

## D25 — A kept run goes after the sibling that writes through its home — 2026-11-27

**What happened.** CRIT tier 1's V1 plan pairs each design's medium arm (no threshold parameter) with its relaxed arm.
The model writes every design of one variant index and seed into one directory, the transit dir. A plain design's run
root IS that directory, and a suffixed design's output moves out of it when its run finishes. V1 keeps its raw output
until it is scored (`keep_raw`), so a medium arm that finishes first is never deposited and never leaves. Its relaxed
sibling then waits for a reclaim that cannot come, and is skipped after `max_wait_s` (6 h).

Two of V1's four pairs had this shape: basal and the amino-acid upshift. The acetate and anaerobic pairs carry an
initial condition, so both of their arms are suffixed. Their relaxed arms launched straight after their medium arms.
The batch already running was unblocked by hand. The two finished medium runs were renamed aside on the same drive,
and they go back when the relaxed arms have moved out. V3 has three more pairs of this shape, the oxygen-off seeds.

**What changed** (`scripts/bv_batch.py`, `Batch._transit_sibling`).
- **Order.** In a `keep_raw` plan, a run waits while a sibling whose transit dir is its home is still pending or
  running. The ledger records this once, as `deferred`.
- **A failed sibling.** If the sibling failed and this run's home is on disk, this run is skipped with that reason.
  The sibling's partial output may be there: running would delete it, and a run complete on disk there would be
  adopted under the wrong design.
- **Scope.** A sibling in a later stage is ignored, because it may be gated on this very run. A plan that deposits is
  unchanged: the deposit reclaims the plain run, which frees the transit dir.

**Tests.** Five in `tests/test_bv_batch.py`. The deadlock was reproduced first: the relaxed arm was skipped with "waited
2.5 h: its transit dir /runs/w/900 holds basal-medium". The stage guard was removed once to confirm its test fails;
without it, the scheduler spins.

## D26 — CRIT tier 1 V1: the scorer compared wall-clock time; amended post hoc, V1 passes — 2026-11-27

**What happened.** V1's first score failed all four pairs. Each generation of each pair differed in exactly 2 of
291 files.
- **`Main/attributes.json`.** Only `startTime` and `endTime` differ: the wall-clock start and end of the process.
- **`shell.log`.** Only the line " - Runtime: H:MM:SS" differs: the wall-clock duration. The simulated length and
  end time, and every line of the step-by-step printout, match.

The other 289 files, every listener column among them, are byte-identical in all 8 generation pairs.

The hook was installed in every relaxed run: its marker line is in each run's log. Under a shift it changes the
threshold (the smoke test: the model's rule jumps 975 → 590 fg at the shift, the relaxed rule holds 975 fg), so
identity on static runs is not vacuous.

**Why the scorer, not the hook.** The registered rule compares "every column of every table but EvaluationTime". The
scorer hashed every file under simOut except EvaluationTime. That is broader than the rule, and the extra breadth
reached two more files that carry wall-clock time.

**What changed.** The change was made post hoc, after seeing the first score.
- `evals/crit_t1.py` removes exactly those three fields before comparing: the two attributes and the Runtime line.
- The all-bytes verdict is still reported beside the amended one (`identical_all_bytes`, false for every pair).
- The first score is kept (`evals/results/crit_t1_v1_first_score.json`).
- The amendment is recorded in the V1 plan and its ledger, and carried into the V3 plan.
- The amended scorer is still stricter than the registered rule: it also compares the remaining attributes and every
  other line of the log.

**Tests.** Three, in `tests/test_crit_t1_score.py`:
- the wall-clock fields pass;
- any other attribute fails;
- any other log line fails, including one that starts " - Runtime:" without a clock.

Each exclusion was widened once, to confirm its test fails.

**Consequence.** V1 passes: 4 of 4 pairs identical, 0 of 291 files differing in every generation. V3 (12 runs) was
built and launched on that pass. It goes to the user to keep or veto. A veto leaves V1 failed on wall-clock bytes
alone, and V3's result is withdrawn.

## D27 — A design key's tag fragments are all identity; three of today's designs had merged — 2026-11-27

**What happened.** After today's runs were indexed, the integrity checks flagged CRIT V1's medium and relaxed acetate
arms as "the same experiment under different names". The cause was in `factors.parse`.

The tag writer (`manifest._design_tag`) appends fragments in a fixed order: `#expr`, `#tl`, `#ic`, `#tf`, `#occ`,
`#ppgpp`, `#it`, `#elong`. The reader lifted `#tl:` and `#expr:` by partitioning at them, as if each were the last
fragment, so every fragment written after them was swallowed.
- **After `#tl:`.** The fragments went into the timeline id (`175649#ic:acetate`, 47 corpus keys). A non-knockout's
  canonical id dropped the timeline and everything after it. The result:
  - V1's medium and relaxed arms of the acetate- and anaerobic-fitted designs shared one id.
  - S4b's wildtype control, fitted to rich medium and then downshifted, took the id of static wildtype basal.
  - S4b's shifted rRNA knockouts took the ids of the corpus's static ones.

  S4b's rows had not landed yet; its analysis would have pooled them with static runs as replicates.
- **After `#expr:`.** The fragments went into the dose, which then failed to parse. S2's three ppGpp-clamped argS
  doses (0.1, 0.25, 0.5) shared one canonical id, with neither the dose nor the clamp. Cellwright's S2 read-back would
  have seen the clamped dose series as replicates of one experiment.

**What changed.**
- A fragment's value now ends at the next `#` (`factors._lift`).
- Fragments written after a timeline or a dose go to `trailing` and are appended to the canonical id. An unknown
  fragment therefore separates experiments rather than merging them.
- `parse` also reports every non-lifted fragment (`extras`) and the fitted start (`initial_condition`).
- `base` and `level_raw` keep their old values, so no existing comparison moves.
- `corpus_schema.medium_of` keeps the initial condition in the medium key. It used to carry it by accident, inside the
  swallowed timeline id; it now carries it on purpose, with the same value.

**Measured over all 153 corpus keys** (plus four of S4b's), old against new:
- Every existing canonical id, `base` and medium key is unchanged.
- 47 timeline ids are now pure.
- 10 canonical ids split, all of them designs that had wrongly merged.
- The corpus has no duplicate experiments.

**Tests.** `tests/test_identity_fragments.py`, seven, with literal expectations. The five that split merged designs
failed first; the two that pin existing ids passed before and after.

**Also checked, for S2 (`evals/results/disc_s2_repro.json`).** S2 reads its clamped arm, run today under model source
`a4497e17+eb4fbe6`, against the corpus's free argS arm. That arm was run on 2026-08-06, and its model source is
unrecorded. One free-arm run (expression 0.25, seed 0) was rerun under today's source on the byte-identical fit.
- Every listener column the corpus kept is byte-identical over 2,529 steps: Mass, ppGpp, RelA and SpoT synthesis and
  degradation, charging, synthetase and ribosome concentrations, MonomerCounts and RibosomeData.
- Both daughters' inherited state is byte-identical too.
- The only other difference is two documentation keys the current GrowthLimits listener adds to its attributes.

The source change does not move this design, so S2's comparison is not confounded by it.

## D28 — A refused design runs only under a named, recorded override: CRIT V3's negative control — 2026-11-27

**What happened.** CRIT tier 1's V3 plan pre-registered the model's own threshold rule under a threshold-moving shift
as its negative control: the defect itself, run to show that the panel can tell the two rules apart. The plan said
these runs go "through the batch, which calls the runner directly". But `runner.run_one` checks the envelope, and the
envelope refuses exactly this defect (CRIT, D17). The first medium-rule run was refused at launch. The batch then
blocked its design, so every medium arm would have been skipped and A3 left undecided. The relaxed arms are not
affected. The false sentence in the plan was mine.

**What changed.**
- `run_one(..., envelope_override=reason)` runs a refused design only when the reason is non-blank. It writes
  `envelope_override.json` beside the run before the run starts: the override and the envelope's refusal.
- A blank or absent override is refused exactly as before.
- An in-envelope design ignores the override and records nothing.
- `bv_batch` carries a plan run's `envelope_override` to the runner.

Reading such runs stays where it was: the question gate refuses questions about division timing after a shift, and
only `evals/crit_t1.py` reads these runs.

**V3's medium arms.** The six runs go in `evals/plans/crit_t1_v3_ctl.json`, each with the override reason. That batch
starts only after the running V3 process has finished every relaxed arm. Each medium arm's run root is its relaxed
sibling's transit dir, so a medium run started first would hold it (D25). A refused attempt left a manifest row marked
"crashed" with 0 generations, which does not count as indexed. It will be set aside once the real run lands, because
a refusal is not a crash.

**Tests.** Six in `tests/test_envelope_override.py`. They cover:
- refused without an override, with nothing written;
- a blank override, which is none;
- an override that runs the design and records why;
- an in-envelope design, which records nothing;
- the batch passing the plan's override through.

The guard was mutated twice, to "None only" and to "never refuse", and each mutation failed a test.

## D29 — The label writers keep every identity axis, and a refusal is not a crash — 2026-11-27

**What happened.** The suite run after D27 found four more ways a row could sit under the wrong design. Each was found
through a row written today.
- **The writer dropped a dose.** A graded knockout written the generate.py way (`condition='KO:argS'`, no
  `target_genes`) and with no timeline took `_design_tag`'s plain-condition branch, which has no dose. The S2
  reproduction (expression 0.25; its design was copied from the August run's `design.json`) was labelled
  `graded_gene_knockout/KO:argS`. That key reads as an undosed graded design.
- **Crash labels lost identity.** `_label`, the crash row's label, used `condition or timeline` alone. A crash of a
  fitted-start, graded, clamped or relaxed-threshold design was therefore filed under another design. V3's refused
  anaerobic-start control landed on the same timeline with no initial condition, which the envelope refuses.
- **A refusal became a crash.** A run refused before the model started was indexed as a crash, with no knowledge base
  and a NULL condition. That tripped kb provenance (D6), the NULL-filter invariant and the guardrail timeline check.
- **`arms()` crashed on missing dates.** Two such rows alone in an arm made `corpus_schema.arms()` compare None with
  None.

**What changed.**
- `_design_tag` reads a knockout's genes from its condition with or without a timeline.
- `_label` is `perturbation/_design_tag seedN`.
- `runner.RunRefused` (still a ValueError) marks a refusal before the model started. `bv_batch` records it as a
  terminal `run_failed` marked `refused`, blocks the design, and writes no crash row.
- `arms()` keeps a missing timestamp out of `min` and `max`.

**Measured.** Old against new over 123 distinct designs (every local `design.json` and every plan):
- `_design_tag` changed for 5. All are argS graded designs written the August way, and each now carries the dose its
  stored, backfilled label already had.
- `_label` changed for 69. That only affects future crash rows; stored rows keep their labels. It also corrects
  `failures.sibling_identities`, which matched siblings by this label and so looked for a target-gene knockout under
  `gene_knockout/basal`.

**Data.**
- The reproduction row's identity columns were corrected in place. Its recorded model source is kept, which a re-index
  from disk could not have claimed. The original shard is kept aside.
- The two refusal "crash" rows were moved out of the manifest and noted in the V3 ledger.

**Tests.** `tests/test_identity_writers.py`, seven. Four failed first, as expected. One test was itself wrong: it gave
two runs one design, so the first failure blocked the second. It was fixed before the fix it tests.

## D30 — A control run past the envelope says so on its row; a repair that could not be tried says why — 2026-11-27

**Override rows.** A run that went past an envelope refusal under a named override (D28) is a pre-registered control.
Only the scorer that registered it reads it. Before D30 nothing on its manifest row distinguished it from an ordinary
run.
- `manifest._flat_row` adds an `envelope_override` column: the reason, or a marker if the file cannot be read.
- Such a row is never `reportable`, so no analysis path reports it as a result. The CRIT scorer reads raw output by
  path and is unaffected.
- `store.list_results` projects the column. It goes through the optional-column helper, so shards written before it
  read NULL, which is honest: no override was possible then.
- `test_guardrails`' timeline check now rebuilds each corpus run with its threshold rule (`#it:`) as well as its
  initial condition. It used to check V3's relaxed oxygen-off runs as if they used the model's rule, and so failed on
  runs the envelope admits.
- That check skips only rows carrying an override. Two new forced assertions check that the same shift is refused
  under the model's rule and admitted under the relaxed one.

**A repair that could not be attempted.** `experiment_integrity` repairs a truncated upshift record from the run's raw
output when that output is on this machine. When it was not, the run fell back to `recorder_truncation` with no reason
given. The corpus answer's `n_designs_repaired` fell by one with nothing naming the omission. Today's V1 upshift runs
were the first local runs of that shape, and the conformance sweep's absence check caught it. It fails identically on
the parent commit, so it is not a regression from D28 or D29.
- The run now carries `repair_unavailable` (why).
- The corpus answer lists the runs, but only when there are some. A key that is always present would excuse every
  count that falls; a mutation making it always present fails the new test.

**Tests.**
- `tests/test_override_rows.py`, three tests.
- One test added to `tests/test_miase.py`. It built the wrong record shape at first and skipped. It now asserts the
  truncation verdict, so it cannot skip.
- The `test_guardrails` change above.
