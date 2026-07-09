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

## References
[1] [The layered costs and benefits of translational redundancy](https://consensus.app/papers/details/61ecade944645e6da518ff6f0191aae1/?utm_source=claude_code) (Raval et al., 2022, eLife)
[2] [Life History Implications of rRNA Gene Copy Number in Escherichia coli](https://consensus.app/papers/details/e59ab355fc6257f3a3d5f3122bbd6ed8/?utm_source=claude_code) (Stevenson et al., 2004, Appl. Environ. Microbiol.)
[3] [Growth suppression by altered (p)ppGpp levels results from non-optimal resource allocation in E. coli](https://consensus.app/papers/details/5339e6a31d0455ada79b4e95d1c36bc3/?utm_source=claude_code) (Zhu et al., 2019, Nucleic Acids Research) — ppGpp titration; and stringent-response reviews [Irving 2020, Nat Rev Microbiol; Steinchen 2020, Front Microbiol].
