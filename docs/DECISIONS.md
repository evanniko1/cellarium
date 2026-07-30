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

**Why it matters beyond this hackathon.** This is exactly the sharding + full-tensor packaging problem
that **"The Well, for the Cell"** needs — so whatever we choose here should slot into that dataset work
(reproducible shards, checksummed manifests, leakage-free splits). Treat this as the seed of that pipeline.

## D3 — Model licensing & data distribution (constraint, not deferred)
The whole-cell *E. coli* model is under the **Stanford Academic Software License (Docket S18-475)** —
**not** open source: non-commercial academic use only; the Software and its derivatives may not be
redistributed without Stanford's written permission (§§5, 6, 8, 11). Consequences for Cellarium:
- **Do** use it for non-commercial academic research (running sims locally) and **do** publish results
  (papers/figures + the data behind them) *with acknowledgment* (§12 anticipates this) — low risk.
- **Do NOT** bundle/vendor/redistribute the model. Cellarium points at a user-obtained checkout; any Docker
  image is built locally from that checkout and **never published**.
- **Distributing a large standalone simulation dataset publicly** (e.g. "The Well, for the Cell") is the one
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
