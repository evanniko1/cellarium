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

## D6 — Exposing the corpus to third-party agents: MCP surface shape (OPEN — not decided)

**Status: no decision has been made.** Three tiers were designed during the codegraph audit
(`wf_c6e5b391`, 2026-07-26) and a sequence was *recommended*, but nothing is chosen and no code exists.
Recorded here so the recommendation is not mistaken for a ruling.

**The forcing question.** The corpus is the contribution, so it should be reachable by other people's
agents. But Cellwright has ~57 tools, and the obvious move — expose them all over MCP — is the wrong one,
for a reason that is easy to miss: **the rigor is not in the tools, it is in the system prompt.**
Survey-first; do not anchor; judge lethality by viability, not growth rate; a benchmark note is not a
measurement; `raw_available=0` does not mean the run is absent; check `mechanistic_scope` before
over-reading a null. Ship the tools without that and a naive caller reads the first design it thinks of,
anchors on it, and emits a number with none of the scope caveats — the instrument without the discipline,
which is the opposite of a glass box. Independent support: codegraph's own measured finding that **one
strong tool steers agents better than a menu of narrow ones** (fewer mis-picks, less context) — and we
already instrument exactly this failure as the AG-2 tool-selection error rate.

**The three tiers.**

- **Tier 1 — one thick tool, `ask_cellwright(question)`.** The server runs the full Cellwright loop
  (its own system prompt, its own tool discipline) and returns the grounded answer + trust strip + the
  run ids behind it. The caller's agent sees ONE tool. Preserves the rigor; keeps the 57-tool menu out of
  someone else's context. Whose key pays is answered by **MCP sampling** — the server asks the *client*
  to make the model call, so the user's own key/model is used and nothing is stored server-side (composes
  with the local credential vault, which never leaves the machine).
- **Tier 2 — a small read-only subset** for agents that want raw access: `search_corpus`, `read_run`,
  `data_availability`. Three or four, not fifty-seven. The manifest itself should be an MCP **Resource**,
  not a tool (that is what Resources are for, and it avoids dumping rows into a tool result). Ship the
  Council/Cellwright framings as MCP **Prompts** so the discipline is adoptable even by raw callers.
- **Tier 3 — never over MCP:** anything that launches a simulation, anything that writes, the credential
  vault. Containment and the biosecurity screen must survive the protocol boundary, server-side and
  unbypassable.

**The alternative that may beat all three.** MCP earns its place when the calling agent *cannot run code*.
If it can, the HF dataset plus `pip install cellarium` delivers most of the value with **zero protocol
surface** — and it is what actually serves the publication. Recommended sequence (not a decision):
dataset + package first, `ask_cellwright` second, raw tools possibly never.

**Lock-in assessment (why this is safe to defer).** Low, in one direction and high in the other:
- *Tier 1 is nearly lock-in-free.* `ask_cellwright` is a thin adapter over `orchestrate.investigate` —
  the same seam the CLI and the web server already call (see **D5**). Adding or removing it changes no
  internal structure. MCP is also a wire protocol, not a framework: dropping it later costs one module.
- *Tier 2 is where lock-in accrues, and it is a PUBLIC-API commitment, not a technical one.* The moment a
  third party's agent depends on `search_corpus`'s output shape, that shape is versioned surface we cannot
  refactor freely. Our tool signatures currently change whenever the science demands it (`design_key`
  changed this week). **This is the real reason to sequence Tier 1 before Tier 2** — not effort.
- *The genuinely irreversible decision is the SCHEMA*, not the protocol: whatever design identity and
  factor columns we publish become the thing other people join against (**WELL-1**, **WELL-9**). Settle
  those first; the transport is comparatively disposable.

**Revisit when:** the HF dataset ships, or someone asks to point an agent at the corpus — whichever first.
