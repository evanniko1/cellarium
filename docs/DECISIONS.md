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
`vmnik-compact.parquet`, 2026-08-03, via `duckdb` in `.venv`): **322 raw rows, 322 after `DEDUP_QUALIFY`** —
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
