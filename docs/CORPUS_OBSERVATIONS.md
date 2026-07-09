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

## References
[1] [The layered costs and benefits of translational redundancy](https://consensus.app/papers/details/61ecade944645e6da518ff6f0191aae1/?utm_source=claude_code) (Raval et al., 2022, eLife)
[2] [Life History Implications of rRNA Gene Copy Number in Escherichia coli](https://consensus.app/papers/details/e59ab355fc6257f3a3d5f3122bbd6ed8/?utm_source=claude_code) (Stevenson et al., 2004, Appl. Environ. Microbiol.)
[3] [Growth suppression by altered (p)ppGpp levels results from non-optimal resource allocation in E. coli](https://consensus.app/papers/details/5339e6a31d0455ada79b4e95d1c36bc3/?utm_source=claude_code) (Zhu et al., 2019, Nucleic Acids Research) — ppGpp titration; and stringent-response reviews [Irving 2020, Nat Rev Microbiol; Steinchen 2020, Front Microbiol].
