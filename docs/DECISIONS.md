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
  it zeroes transcription and the enzyme dilutes to ~0 over generations — **not a stoichiometric deletion**.
  Hence the defect is generation-paced (the generation-depth lesson).
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
