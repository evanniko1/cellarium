# Corpus observations & ground-truth expectations

Baseline for evaluating the agent (Coli). **A** is what the corpus *measured*; **B** is what we *expect* the
running exploration panel to show, grounded in literature. Coli should **recover these from the tools**
(`read_series` / `read_species` / QC), not assert them from memory — divergence is either a faithfulness
failure (Coli) or a finding (the model). Generated 2026-07-09 from the first clean corpus (see GENERATE.md).

## A. Measured — default trio (12 runs: wildtype/basal, condition/with_aa, timeline/downshift × 4 seeds)

All 12 `qc=ok` and reportable. Channel means (per-timestep `instantaneous_growth_rate`; ppGpp µM; dry mass fg):

| design | growth (mean) | ppGpp (mean) | dry mass @ div | notes |
|---|---|---|---|---|
| wildtype / basal (minimal glc) | ~0.00025 | ~57 | ~510 fg | slow, high ppGpp, small cells |
| condition / with_aa (minimal+AA) | ~0.00056 | ~22 | ~1240 fg | fast, low ppGpp, big cells |
| timeline / AA-downshift | ~0.00033 (avg) | ~34 (avg) | ~640 fg | transient — see below |

**Four signatures the corpus reproduces (each independently across all 4 seeds):**
1. **Nutrient–growth law.** Growth rises with medium richness: basal `0.00025` < downshift-avg `0.00033` < with_aa `0.00056` (~2.2× span).
2. **ppGpp inversely tracks growth.** with_aa `~22` < downshift `~34` < basal `~57` µM — rich media suppresses the alarmone; minimal induces it.
3. **Cell size scales with growth (Schaechter law).** Division mass: with_aa `~1240 fg` ≫ basal `~510 fg`.
4. **Stochastic heterogeneity.** Real seed spread (basal ppGpp 51–64); seed 2 is consistently the extreme replicate.

**Downshift transient (the dynamics — from `media_segments`, not the whole-run mean):**
- ppGpp: `minimal_plus_amino_acids` window **22.5** → `minimal` window **45.3** (doubles after the shift).
- growth: **0.00050** → **0.00017** (drops ~3×). This is the stringent response captured in-silico.

## B. Literature-grounded expectations — exploration panel (running; verify when done)

### ppGpp causal titration (`ppgpp_conc` on basal: 0.2×, 0.6×, 1.0× control, 1.6×, 2.0×)
The variant *clamps* [ppGpp] and disables its dynamics — an in-silico version of Zhu et al.'s titration.
**Prediction: growth is NON-MONOTONIC in ppGpp — it peaks near control (1.0×) and drops at BOTH extremes.**
High ppGpp limits ribosome synthesis; low ppGpp limits metabolic-protein expression — "non-optimal resource
allocation" either way [3]. So expect ribosome/rRNA proxies to fall as the clamp rises across 0.2×→2.0×,
while growth is humped. If Coli instead claims "more ppGpp = monotonically slower," that's wrong — check it
against the titration series. (Mechanism review: [1], [2].)

### rRNA-operon knockout (`rrna_operon_knockout`: KO 2, 4, 6 of 7 operons, minimal media)
**Prediction: growth decreases as more operons are removed, with the defect steepening at higher KO counts**
(notably after ~4 copies) [3], and the penalty is **milder in minimal media** than it would be in rich media
because the growth cost of losing rRNA redundancy scales with the max growth rate the niche allows [1][2].
So in minimal, expect a modest, monotone growth decline 2op→6op, not a collapse.

### Carbon / O2 sweep (`condition`: glc_20mM, glc_5mM, glc_2mM, acetate, succinate, no_oxygen)
Expect a **Monod-like growth ordering**: glucose-replete ≥ glucose-limited > poor carbon (acetate/succinate) ,
with anaerobic (`no_oxygen`) growing by fermentation (lower yield). ppGpp should **anti-correlate with growth**
across the sweep (extending signature #2). **Poor-carbon runs may not divide within the sim window** → QC
records them `no_division`/non-reportable rather than inventing a doubling time; that is the guardrail working,
not a failure. AA **up-shift** (`0 minimal, 1200 minimal_plus_amino_acids`) should be the mirror of the
downshift: ppGpp drops and growth rises after the shift.

## C. Caveats (don't let Coli over-read these)
- **`fba_objective` is a solver diagnostic** (homeostatic + kinetic terms), not a biological ranking. It runs
  high during transients (downshift ~11 vs static ~0.8–1.6) because the network is off its fitted steady state.
  Clean readouts are growth, ppGpp, mass, and molecule counts.
- **`growth_rate` is the per-timestep `instantaneous_growth_rate`**, not a doubling time. Compare designs on the
  same channel; convert to doubling time only via division events.
- Means hide transients — for any shift design, use `media_segments` / the trajectory, not the single mean.

## D. Using this with Coli
For each question, check that Coli (a) calls a tool to ground the number, (b) reports it within rounding of the
values above, and (c) respects the caveats (segments for transients; FBA objective as diagnostic; envelope
refusal for a carbon-source *switch*). A, being measured, is a hard faithfulness gate; B is the scientific
expectation the completed panel will confirm or complicate.

## E. Panel results — predictions checked (measured 2026-07-09; 42 runs, re-read with mechanistic channels)
Verdicts: **✓ confirmed · ✗ discrepant · ~ confounded (needs multi-gen)**.

- **ppGpp clamp (B.1) — ~ / ✗ partial, mechanism now verified molecularly.** The clamp works (ppGpp 9.8→98.3
  across 0.2–2.0×). Growth is **monotonic decreasing** (0.2×=0.000323 fastest → 2.0×=0.000181 slowest) — **not**
  Zhu's non-monotonic hump. High-ppGpp arm **✓** (ribosome-repression: `ribosome_conc` 21.6→19.1 as ppGpp
  rises). Low-ppGpp arm **✗ vs Zhu**: 0.2× is fastest with ribosomes plateaued (~23.8) — no metabolic-cost
  downturn at 1 gen. The ppGpp→`ribosome_conc`→growth chain is now **verified, not inferred**. Hypothesis: the
  low-side downturn is a steady-state effect → testing at `--generations 4`.
- **Carbon/O₂ sweep (B.3) — ✓ with a key refinement.** Poor carbon (acetate 0.000177, succinate 0.000193) +
  anaerobic (0.000151) → slow + small cells ✓. Glucose 2/5/20 mM identical (~0.000255) — **uptake-saturated**
  (K_m ≪ mM); this arm doesn't probe glucose *limitation* (needs µM). **Refinement: ppGpp does NOT
  anti-correlate with growth on the carbon/energy axis** (anaerobic is slow but low ppGpp 27.9) — ppGpp tracks
  **AA/translation limitation specifically**. Signature #2 holds on the AA axis only. Supports "ppGpp is
  emergent, not a fitted growth-lookup."
- **rRNA-operon KO (B.2) — ~ confounded.** Non-monotonic at 1 gen (2op 0.000251 → 4op 0.000234 → 6op 0.000274;
  6op *fastest*) — contradicts the predicted decline. The KO defect is steady-state; inherited ribosomes mask
  it in gen 0. Re-running at `--generations 4`.
- **AA up-shift — ~ confounded.** The cell divided before the t=1200 shift (only the pre-shift `minimal`
  segment exists). Needs multi-gen (later generations sit post-shift) or an earlier shift (~600 s). Downshift
  re-confirmed (rich 22.6/0.000522 → minimal 40.9/0.000150).

**Meta-finding:** three arms (low-ppGpp downturn, rRNA KO, up-shift) are **steady-state phenomena a single
generation cannot resolve** — the panel's most valuable output. The in/out-of-sample framing (§6.1 of
HACKATHON_CONCEPT) is validated: the out-of-sample arms produced genuine behavior — some matching, one honestly
disagreeing with Zhu, several needing more generations. The harness now carries `ribosome_conc`,
`fraction_trna_charged`, `rela_conc` so the mechanism is checkable cross-run in SQL, not inferred from growth.

### Multi-generation resolution — all three confounded arms confirmed (2026-07-09, `--generations 4`)
Re-running the confounded arms to steady state (reading the per-generation growth/ppGpp trajectory) **flips
every 1-gen artifact into the literature-predicted result** — a clean demonstration that single-generation
snapshots mislead for steady-state effects:
- **ppGpp clamp → ✓ Zhu non-monotonic emerges.** Low-ppGpp clamps start fast (gen0 0.2× = 0.00033) but
  **decline over generations** (→ 0.00018 by gen4); the ribosome over-investment is not sustained. Growth no
  longer peaks at the lowest ppGpp — the downturn appears, as Zhu 2019 predicts. The 1-gen "monotonic, low=fast"
  was the artifact. (Proteome view: the 0.2× clamp has the *highest* ribosomal fraction, 0.48 — over-allocated.)
- **rRNA-operon KO → ✓ monotonic dosage decline.** At gen4, growth is monotone in operon count
  (2op 0.000227 > 4op 0.000187 > 6op 0.000157; 6op −42% over 4 gens). The 1-gen "6op fastest" was masked by
  inherited ribosomes. Confirms Stevenson 2004.
- **AA up-shift → ✓ mirror of the downshift.** Post-shift generations relax: ppGpp **36 → 22** and growth
  **rises** to the +AA-adapted state (ppGpp ~22 = static `with_aa`). The 1-gen run divided before the shift.

### Pathway proteome allocation (P2.1 — surveyed, not inferred)
The curated pathway panel makes proteome *allocation* a first-class, surveyed signal: **ribosomal fraction
tracks growth** (with_aa 46% > basal 35% > no_oxygen 20% — the Scott–Hwa growth law, emergent), **acetate
reallocates to central carbon** (glycolysis/TCA ≈ 2× — gluconeogenesis/glyoxylate signature), and **anaerobic
down-regulates respiration/PPP/stringent ≈ 50%**. `amr_efflux` baseline ≈ 0.05–0.09% (the reference for a
phenotype-grounded biosecurity screen, P2.3).

## F. Powered, literature-first hypothesis tests (2026-07-09, n=8 seeds)
Formulated from literature *first*, then tested — the correct direction. Statistics across 8 replicate seeds.

- **H1 — FNR/ArcA anaerobic regulon → CONFIRMED (in-sample consistency).** no_oxygen reproducibly up-regulates
  the FNR anaerobic-activation program: cytochrome bd (`cydABCD`), `grcA` (pfl), `dcuC`, `ansB`, `moaABC` — all
  reproducible across 8 seeds — and represses aerobic respiration at the sector level (`pw:respiration_atp`
  log2FC −1.01, halved) [Spiro 1990; Unden 1991]. **Caveat: largely in-sample** (ParCa fits condition-specific
  expression), so this confirms model+pipeline self-consistency, not novel prediction. (Our hand-curated FNR
  gene set missed `cydCD`/`moaABC`/`ansB` — a panel-curation limitation, not a model error.)
- **H2 — Mg limitation → reduced ribosome/growth → FAILED (out-of-sample; a model boundary).** minus_magnesium
  is statistically indistinguishable from basal: ribosomal fraction 35.07±0.16% vs 35.12±0.25% (Welch t=−0.31),
  growth identical (t=0.07). Literature [Pontes 2016] predicts Mg limitation *reduces* ribosome content; the
  model does **not** couple media-Mg to ribosome regulation. A documented mechanistic boundary — the more
  valuable result, because it is a genuine prediction the model gets wrong.
- **Growth law (ribosomal sector) → CONFIRMED, quantitative.** 5 conditions × 8 seeds:
  `ribosome_frac = 527·growth + 0.191`, **R²=0.83** — the linear ribosomal sector with a ~19% offset
  [Hui 2015; Scott law]. Tight CIs (with_aa 46.08±0.08%, basal 35.12±0.25%, no_oxygen 20.61±0.52%).

**The in/out-of-sample control, demonstrated cleanly:** the model reproduces what it was fitted to
(H1 anaerobic regulon) and fails to predict what it was not (H2 Mg–ribosome coupling). That is the honest
boundary of its predictive power — and the reason validation must be anchored on out-of-sample tests.

## G. Gene-KO experiment — mechanistic-scope guardrail (2026-07-09, n=6) — INCONCLUSIVE, instructive
The project's first single-gene KOs: mechanistic (`pfkA`, `tpiA` — glycolysis) vs non-mechanistic (`flgB`,
`ymgD` — flagellar / y-gene). It did **not** cleanly prove the guardrail, and the failure is the lesson:
- All 24 KOs divided (qc=ok). **No significant growth change for ANY KO** (Welch |t|<1 vs basal).
- **Non-mechanistic KOs behaved as predicted** — flgB/ymgD had no significant growth or proteome effect (inert).
- **Mechanistic KOs also showed no growth effect** — because `pfkA`/`tpiA` single-KOs are **non-essential**
  (metabolic redundancy: pfkA↔pfkB; FBA reroutes). Biologically defensible (E. coli pfkA single-KO is viable).
  **Lesson: "mechanistic" ≠ "essential"** — a mechanistic gene can be dispensable; I mis-designed by picking
  redundant genes.
- Proteome: each KO'd gene's own count drops (trivial); tpiA's glycolysis-sector drop is largely its **own
  removal from the panel**, not rerouting. **No coherent compensatory network response** above noise.
- **top_movers noise floor persists at n=6**: both the mechanistic and the inert KO show ~6 spurious
  "reproducible" (repro=0.83) low-count movers — different genes each, no pattern. Confirms the audit:
  reproducibility+count-floor is insufficient; a **per-gene statistical test with FDR** is required.

**Verdict:** the guardrail's *justification* rests on the conceptual argument + the clean H2 (Mg→ribosome)
case, **not** on this KO experiment. A clean KO-contrast proof needs (i) an *essential, non-redundant*
mechanistic gene (multi-generation, for a real growth defect) vs a non-mechanistic KO, and (ii) FDR-hardened
top_movers. The experiment disciplined the claim — as intended.

## H. Essential-KO experiment — the vetting OVERPREDICTED; the model is robust to single KOs (2026-07-10, 4 gen, n=4)
Redesigned mechanistic-scope proof: three vetted essential + sole-catalyst KOs (fabI, glmS, gltA) vs a basal
control, multi-generation. The vetting's confident "PASS (strong KO-essentiality)" was **wrong 0/3**, and the
reason is mechanistically decisive:
- All 16 lineages `qc=ok` — **no arrest, no lethality**, through 4 generations.
- **No significant growth defect**: fabI −3.7% (t=−0.82), glmS −7.7% (t=−1.22), gltA −1.8% (t=−0.73) — all ns.
- **The KOs fully applied**: the knocked-out enzyme is **0 copies at gen3** (basal: fabI 10016, glmS 883,
  gltA 10190). The enzyme is *completely gone*, yet growth is normal — so this is NOT a generation-depth artifact.
- **Mechanistic insight:** in wcEcoli's *kinetics-constrained* FBA, removing an enzyme's expression reduces
  growth only if that enzyme's count sets a **binding kinetic constraint** on a biomass-required flux. For these
  three, count=0 did not bind the flux (the reaction is not enzyme-count-limited, and/or the biomass demand is met
  by an alternative flux distribution) → no phenotype.
- **Calibration verdict:** `is_sole_catalyst` captures **catalyst-annotation topology, not FBA flux constraints** —
  different things. Do NOT ship the vetting as a gate; back it with the model's *actual* KO behaviour (or its
  kinetic-constraint structure), and treat proxy outputs as hypotheses. The model's **KO-growth-predictive scope
  is narrow** — largely robust to single-gene KOs at reachable depth. This bounds which KO hypotheses it can address.
- Third empirical disproof of a confident claim (after nitrate `nrdG`, pfkA-"mechanistic") — the harness caught all three.

## I. gltX KO — the machinery axis RESPONDS, but via a crash, not a clean phenotype (2026-07-10, 4 gen)
Test of whether the translation-machinery axis responds (vs metabolism's reroute). gltX = glutamyl-tRNA synthetase.
- **All 4 gltX KO seeds CRASHED the sim** (vs 0/5 metabolic KOs and 0/4 basal controls) — a qualitatively
  different, dramatic outcome. Metabolism reroutes; the translation machinery cannot.
- Ran ~3 generations first. Reliable pre-crash signal: **ribosome_conc COLLAPSED (21 -> 2.15)**, gen-0 growth
  ~1/3 of basal. Then the numerics destabilized (the gen-2 growth 0.0013 and ppGpp 6 are garbage from the
  breakdown) and the sim crashed with **`NegativeCountsError: ATP[c] in PolypeptideElongation`** (+ FBA solver
  failure) — the crash is INSIDE the translation process.
- **Specific mechanism prediction wrong (again).** Predicted ppGpp UP (stringent); it went DOWN/erratic. The
  observable is ribosome collapse + numerical breakdown, not a stringent-mediated graceful arrest.

**The whole-cell model's single-gene-KO behaviour is now fully characterised:**
- **Metabolism → reroutes** (no effect; 5/5: fabI/glmS/gltA/pfkA/tpiA).
- **Essential machinery → crashes** (numerical breakdown; gltX 4/4).
- **The only CLEAN, measurable phenotypes come from GRADED capacity perturbations** — rRNA-operon KO (monotone
  decline) and the ppGpp clamp. No *full single-gene KO* yields a clean graceful phenotype.

**Machinery-classifier implication:** the axis is confirmed responsive, so a classifier would (a) fix the
current misclassification of machinery as "inert", and (b) serve as a WARNING ("essential-machinery KO will
likely CRASH the sim, not yield clean data"). Build it as a scope/crash-warning tool, not a clean-phenotype
predictor. And it is now the *sixth* wrong specific prediction of mine the harness has caught — the general
axis (machinery responds) held; the mechanism (stringent) did not. (Built 2026-07-10: `scope.py` now detects the
89 machinery genes from `molecule_groups` + the synthetase set and returns the three-way KO prior.)

### Root-cause refinements from the source (2026-07-10 repo pass of CovertLab + Mohammed's platform fork)
Reading the model core (stock CovertLab; the platform branch does not touch it) sharpened the *mechanism* behind
the reroute + under-sensitivity. Two refinements — neither reverses a conclusion, both make it airtight:

1. **The metabolism objective has NO growth/biomass-maximization term.** `metabolism.py` runs
   `objectiveType = "homeostatic_kinetics_mixed"`: minimize *deviation* from (a) metabolite concentration target
   *ranges* (`range_homeostatic`) + (b) kinetic flux targets (weighted, soft). The biomass-objective reaction
   exists in `wholecell/utils/modular_fba.py` but only for `objectiveType == "standard"`, which the whole-cell
   metabolism never uses. So the deepest reason single-KOs reroute is not merely "kinetic constraints are soft" —
   it is that **there is no growth term to degrade**: the solver only has to keep pools in range, and rerouting
   does that. This is *also* why the FBA single-deletion screen was 0/35: it measured `obj0 − obj` on a
   deviation-minimizing objective that stays ≈satisfiable by construction. The homeostatic objective is a
   deliberate whole-cell design choice — metabolite demand is set dynamically by the other processes each
   timestep, not by a fixed biomass vector — so it *cannot* be read as an essentiality signal.
2. **The `gene_knockout` variant is an EXPRESSION knockout, not a stoichiometric deletion.** It calls
   `sim_data.adjust_final_expression([geneIndex], [0])` — it zeroes transcription, and the enzyme then dilutes to
   ~0 over generations. This is why the defect is generation-paced (the generation-depth lesson) and why even at
   full depletion metabolism reroutes: the network re-satisfies the (soft, growthless) objective around the
   missing catalyst.

**External corroboration (not just my runs):** upstream ships a dedicated variant-analysis script for *every*
graded-capacity knob (`ppgpp_conc`, `rrna_gene_copy_numbers`, `metabolism_kinetic_objective_weight`,
`metabolism_secretion_penalty`, `cell_growth`, `growth_trajectory`) but **none for `gene_knockout`** — the Covert
team built their instrument around graded perturbations, not single-gene essentiality. Mohammed's platform exposes
KO as first-class but `knockout_available == (gene.ko_index > 0)` (a mechanical check), and separately *catches*
variant crashes after the fact ("Handle variant failures" commit) — so it knows KOs crash but never predicts it.
The `scope.py` three-way prior is exactly that missing predictive layer.

## J. Viability re-score — the KO readout that does NOT reroute (2026-07-10)
Prompted by Gherman et al. 2025 (Literature grounding, below), re-scored every KO run by **division success** —
the canonical wcEcoli viability signal (a cell that replicated its chromosome, `full_chromosome == 2` over a real
trajectory, reached DIVISION) — instead of graded growth rate. New `viability` worker mode + `reader.viability`
aggregate the per-cell division signal (+ FBA-solver health) over seeds × generations into a run-level verdict.

| run (variant idx) | class | cells | division_rate | gens reached | verdict |
|---|---|---|---|---|---|
| wildtype (control) | control | 20 | 1.00 | ≤4 | VIABLE |
| ymgD (397) | inert | 6 | 1.00 | 1 | VIABLE |
| flgB (2791) | inert | 6 | 1.00 | 1 | VIABLE |
| pfkA (1594) | metabolic | 6 | 1.00 | 1 | VIABLE |
| tpiA (1542) | metabolic | 6 | 1.00 | 1 | VIABLE |
| fabI (425) | metabolic\* | 16 | 1.00 | 4 | VIABLE |
| glmS (2795) | metabolic\* | 16 | 1.00 | 4 | VIABLE |
| gltA (2657) | metabolic\* | 16 | 1.00 | 4 | VIABLE |
| **gltX (2074)** | **machinery/aaRS** | 12 | **0.92** | **3 (of 4 requested)** | **IMPAIRED** |

(\* = essential, sole-catalyst; run 4 generations.)

- **Every metabolic KO is genuinely VIABLE** (divides every generation, rate 1.00) — including the three
  "essential" sole-catalyst enzymes run to 4 generations. This is a *stronger, cleaner* statement than the earlier
  "no growth-rate effect": the model doesn't merely fail to register the KO on our chosen channel — it produces a
  fully dividing lineage. The reroute is real, and viability confirms it without the reroute masking anything.
- **gltX (aaRS) is the lone outlier**, and viability refines §I's "crash" into a **progressive collapse**: all 4
  seeds *divide* (slower — median division time 8541 s vs ~5400 s baseline) for exactly 3 generations, then the
  lineage fails to continue (seed 1's gen-2 cell already fails to divide) while the same-batch essential KOs reach
  4. This is precisely the lethality a graded growth channel hides and a viability channel exposes.
- **Method value:** viability is the KO/design readout that does not reroute away — the primitive for future KO
  and reduced-genome screens, and the natural target for an ML surrogate (Gherman et al.).

## K. The three KO modes and the homeostatic objective (synthesis, 2026-07-10)
The one fact that explains everything: **the model's metabolism doesn't maximize growth.** Its FBA runs a
*homeostatic* objective — keep ~173 metabolite concentrations inside target ranges (plus hit soft kinetic
targets), minimizing deviation. Growth isn't optimized; it *emerges* downstream from all the processes making
mass. Hold that lens and the three KO modes fall out:

1. **Metabolic KO → reroutes → viable (no phenotype).** Disable an enzyme and the solver finds another flux path
   that still keeps the pools in range. There's nothing to degrade — the objective only asks "are the pools
   filled?", and rerouting fills them. Even genuinely essential enzymes (fabI, glmS, gltA) look viable.
2. **Machinery KO → crashes → not a clean phenotype.** Ribosomes, RNAP, aaRS, the replisome live *outside*
   metabolism — they turn metabolite pools into biomass, and there is no "reroute" for translation. Remove
   glutamyl-tRNA synthetase and charging can't keep pace with elongation; a count goes negative and the sim throws
   `NegativeCountsError`. Documented behavior: Choi & Covert 2023 fit aaRS kcats ~7.6× above in vitro just to grow
   and call aaRS perturbation "catastrophic" — a full KO is the extreme.
3. **Non-mechanistic KO → nothing → viable by construction.** Most genes are expressed and counted but do nothing
   in a modeled process; a null there is model *scope*, not biology.

**How the objective sets this — it decides where a perturbation can show up.** A biomass-maximizing objective
(classic FBA) would drop the biomass flux when a KO blocks a precursor — you'd *see* essentiality. wcEcoli
deliberately swapped that for the homeostatic objective (in a whole-cell model, demand is set dynamically by the
rest of the cell, not a fixed biomass vector). The price of that correct choice: **metabolism can no longer
register single-KO essentiality — it absorbs the KO by rerouting.** Machinery isn't in the objective at all, so
its KO isn't absorbed — it breaks the metabolism↔rest-of-cell coupling and, with no graceful failure mode,
crashes. The only clean, graded phenotypes come from **capacity** perturbations (rRNA-operon dosage, ppGpp clamp),
which tune the *rate* of biomass production continuously — emergent growth tracks that smoothly. Consequence for
measurement: "did growth change?" is the wrong KO question (it reroutes away); **"did the cell divide?"** is the
right one (§J viability). The Baba/Joyce benchmark tells us when the model's "viable" is *wrong* — fabI/glmS/gltA
are the `model_UNDER_predicts` cases.

### KO mechanism — empirically nailed down (corrects an earlier imprecision)
The `gene_knockout` variant calls `adjust_final_expression` (reconstruction/ecoli/simulation_data.py), which
zeroes **only transcription** parameters (`rna_synth_prob`, `rna_expression`, `exp_free/ppgpp`, `basal_prob`,
`delta_prob`) — it never touches counts directly. But the initial monomer count *derives from expression*, so
**the KO'd protein is 0 from gen-0 start** — verified: fabI (ENOYL-ACP-REDUCT-NADH-MONOMER), glmS, and gltX
(GLURS-MONOMER) all read `count = 0` at the first timestep of generation 0, vs ~7,900→15,600 for fabI in WT. So
the earlier "the enzyme dilutes to ~0 over generations" framing was **imprecise**: the enzyme is absent from t=0;
there is *no protein-dilution confound*. Metabolic KO viability is therefore the **pure reroute**, full stop.

What *does* carry over is the **inherited downstream state**: `setDaughterInitialConditions` loads the parent
snapshot (`loadSnapshot(inherited_state['bulk_molecules'])`) — daughters **inherit the partitioned pools, they do
NOT re-initialize at full value.** So metabolite/charged-tRNA pools halve per division. This is why gltX (aaRS,
protein 0 from t=0) still runs ~3 generations before crashing: it limps on an inherited charged-Glu-tRNA buffer
the absent synthetase can't regenerate, which depletes across generations until elongation stalls. The dilution
that matters is of the *inherited substrate pools*, not the knocked-out protein.

**Metabolic KOs are NOT buffer-limited — the reroute is genuine steady-state (verified).** Per-generation growth
for fabI/glmS/gltA is FLAT across all 4 generations (~0.00022–0.00025 /s, ≈ WT) with no gen-over-gen decline. Were
the cell running down an inherited product pool, growth would trend downward each division (the gltX signature);
it doesn't. So the FBA re-supplies the demand every generation — you would NOT see an effect at 10 generations (or
ever). Biologically this is the *unrealistic* part: fabI is the sole enoyl-ACP reductase (no bypass in reality),
yet the homeostatic network finds a feasible flux meeting the target without it — exactly the flexibility that
makes it a `model_UNDER_predicts` case. No X-zeroing or added generations fixes that; only the objective (biomass-
max would block it) or the ground-truth benchmark does.

**Flux-level confirmation it's an artifact, not biology.** fabI's monomer expands (via complexation) to 27 FBA
reactions (the enoyl-ACP reductase steps of fatty-acid elongation). In WT they carry flux (sum|flux| ≈ 0.227); in
the KO they are **exactly 0** — the enzyme is genuinely off — yet the cell divides steadily. Real E. coli with
zero enoyl-ACP-reductase flux cannot make fatty acids and dies (FabI is the sole isozyme, no bypass). So the model
is dividing cells **without the fatty-acid synthesis real division requires** — the soft homeostatic objective
never hard-requires that flux. That is the mathematical artifact behind `model_UNDER_predicts`, made concrete. The
method that exposes it — enzyme → reactions → flux-diff (KO vs WT) — is a candidate "reroute-diagnosis" tool
(needs proper seed normalization; a naive single-seed diff is dominated by reversible-transport noise).

## Literature grounding — objective, KO essentiality, viability (2026-07-10; via PubMed)
Scan of the Covert-lab publications + the user-supplied Cell Systems paper. All three both *validate* our
characterization and *redirect* the instrument (see DECISIONS.md D4-lit for the plan):
- **Choi & Covert 2023**, *Whole-cell modeling of E. coli confirms that in vitro tRNA aminoacylation measurements
  are insufficient to support cell growth…*, Nucleic Acids Research 51(12):5911–5930,
  doi:10.1093/nar/gkad435. aaRS kcats had to be fit **7.6× above** in vitro to sustain the proteome, and
  perturbing aaRS activity is *"catastrophic"*. Published backing for the `lethal_crash` / machinery-collapse
  regime — gltX is an aaRS.
- **Gherman et al. 2025**, *Accelerated design of E. coli reduced genomes using a whole-cell model and machine
  learning*, Cell Systems 16(10):101392, doi:10.1016/j.cels.2025.101392. Uses **cell division (viable/inviable)**
  as the KO readout, an **ML surrogate** (95% less compute), and **multi-gene genome reduction** (40% removed).
  Direct source of §J's viability re-score and the surrogate direction.
- **EcoCyc 2025** (Karp et al., EcoSal Plus, doi:10.1128/ecosalplus.esp-0019-2024; wcEcoli team co-authors): ships
  a steady-state flux model that **predicts KO growth rates** + curated **gene-essentiality** annotations →
  benchmark/defer to it for metabolic essentiality rather than rebuild (D4 tier-2).
- **Birch, Udell & Covert 2014**, *Incorporation of flexible objectives and time-linked simulation with FBA*, J
  Theor Biol 345:12–21, doi:10.1016/j.jtbi.2013.11.028 — lineage of the homeostatic/dynamic `flexible`
  objective in `modular_fba.py`; the "no biomass-max term" is a deliberate design choice, not a default.

## References
[1] [The layered costs and benefits of translational redundancy](https://consensus.app/papers/details/61ecade944645e6da518ff6f0191aae1/?utm_source=claude_code) (Raval et al., 2022, eLife)
[2] [Life History Implications of rRNA Gene Copy Number in Escherichia coli](https://consensus.app/papers/details/e59ab355fc6257f3a3d5f3122bbd6ed8/?utm_source=claude_code) (Stevenson et al., 2004, Appl. Environ. Microbiol.)
[3] [Growth suppression by altered (p)ppGpp levels results from non-optimal resource allocation in E. coli](https://consensus.app/papers/details/5339e6a31d0455ada79b4e95d1c36bc3/?utm_source=claude_code) (Zhu et al., 2019, Nucleic Acids Research) — ppGpp titration; and stringent-response reviews [Irving 2020, Nat Rev Microbiol; Steinchen 2020, Front Microbiol].
