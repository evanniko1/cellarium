# ROUTE1 — verification record

Methods-grade record of every check performed on the ROUTE1 model changes: what was tested, at what
sample size, against what tolerance, and what it returned. Written to be quotable in a methods
section, so each entry states its **N**, its **tolerance**, and whether the result is **measured** or
**derived**. Where a check was run twice by independent implementations, both numbers are given —
agreement between them is itself evidence, and disagreement is recorded rather than reconciled away.

Terminology used throughout:

- `θⱼ = (K_rta/cⱼ)(1 + uⱼ/K_rtf)` — dimensionless wait per unit demand for tRNA species *j*
- `D = 1 + Σⱼ fⱼθⱼ` — the charging denominator; `v_rib = k_el^max·[R]/D`
- `r = D₈₆/D₂₁` — the resolution ratio
- `Aₐ/Hₐ` — arithmetic over harmonic mean of a family's isoacceptor charged pools
- **clean window** — the leading run of evolved timesteps over which two runs are *bitwise* identical
  in `Mass/cellMass`, `Mass/dryMass`, `RibosomeData/actualElongations` and `GrowthLimits/ppgpp_conc`;
  inside it the entering state is identical, so a per-step difference is a direct effect rather than
  trajectory divergence

---

## 1. Algebraic identities underlying the occupancy form (ROUTE1-21)

The rewrite of `ribosome_conc_a_site` rests on three identities. Each was re-derived independently by
two implementations and evaluated numerically on randomly drawn states.

| # | Identity | N | Result | Tolerance |
|---|---|---|---|---|
| I1 | `1/saturated_chargedⱼ ≡ 1 + θⱼ` | two independent sets of random 21-dim states | max abs error **6.66e-16** and **8.88e-16** | exact expected |
| I2 | substituting `v_rib = k[R]/D` into the pre-change expression yields `[R]·fⱼ(1+θⱼ)/D`, i.e. `k_el^max` cancels | two independent checkers | max **relative** difference **2.22e-16** to **4.44e-16** | exact expected |
| I3 | `(1+θⱼ)·saturated_unchargedⱼ ≡ (K_rta/K_rtf)(uⱼ/cⱼ)` | two independent checkers | residual **5.4e-20** and **1.73e-18** | exact expected |
| I4 | `Σⱼ fⱼ/saturated_chargedⱼ ≡ D` (the normalisation is D, not an arbitrary sum) | two independent checkers | agreement to **~2e-16** | exact expected |

**Why I3 is the decision-relevant one.** It reduces the RelA driver to
`RBUⱼ = [R]·fⱼ·(K_rta/K_rtf)·(uⱼ/cⱼ)/D`, showing that a change of tRNA resolution can reach the
stringent-response arm through **exactly two channels**: the ratio `uⱼ/cⱼ`, and `D`.

**Invariance of `uᵢ/cᵢ` under an isoacceptor split** (measured): within-family relative standard
deviation of charged fraction ≤ **7.08e-4**, enforced by `initial_conditions.py:110`, which rounds
`charged_i = total_i · frac_charged_a`. Uncharged-block sum invariant to **4.1e-6** relative while the
charged-wait term grows **4.024×**.

**Split-invariance of the RelA driver under ppGpp@21 + occupancy form**: holding aggregate pools fixed
and varying the within-family split arbitrarily moves the driver by **0.000e+00** (exact), and the
A-site sum ratio to 1 is within **2.2e-16**.

**Structural, not conventional.** `D₈₆` has no path into the ppGpp arm once the `v_rib` term is gone:
`calculate_trna_charging` returns exactly five values and `D` is not among them, and
`ppgpp_metabolite_changes` is a module-level function called with an explicit argument list.

---

## 2. Φ — the measured cost of the occupancy form at 21-amino-acid resolution

`Φ = D · effectiveElongationRate / k_el^max` is the single scalar by which the occupancy form differs
from the previous expression at unchanged resolution.

| Quantity | operons OFF | operons ON |
|---|---|---|
| median Φ | **0.999917** | **0.999965** |
| steps below 1 | 88.3% | 100.0% |
| min / max Φ | **0.989171** / **1.002968** | — |
| across-amino-acid spread within a step | **4.44e-16** | **4.44e-16** |
| resulting change in total RelA synthesis (median) | **+0.009%** | **+0.004%** |

The 4.44e-16 within-step spread means **nothing re-ranks**: Φ acts as a scalar, not a redistribution.

> **Caveat on interpreting Φ.** On the steady-state path Φ ≈ 1 is close to a self-consistency
> property — the solver sets the tRNA state so that `v_rib = k_el·[R]/D_solver`, and `net_charged` is
> the rounding of that same state. The value is therefore trustworthy **in the measured regime** and
> weak evidence outside it. No run on disk leaves mild stress, so the starvation regime is
> **untested, not refuted**.

---

## 3. Non-vacuity of the regression tests

A test that passes both before and after a change demonstrates nothing. The load-bearing test was
therefore checked against the pre-change code:

- Method: revert the edit in place via `scripts/route1_occupancy_patch.py --revert`, re-run, restore.
- Result: `test_ppgpp_arm_is_invariant_to_max_elong_rate` **fails** against pre-change code at exactly
  the re-pin factor **1.271261**, and passes after.
- The file was restored **byte-identically** (md5 `c80940d5c08f2fad735a99a6963e9f81` before and after).

Test suite: `tests/test_ppgpp_arm_isolation.py`, **9 tests**. Before it, a repo-wide grep for
`calculate_trna_charging`, `get_charging_params`, `ppgpp_metabolite_changes` or `max_elong_rate`
returned **zero** test files anywhere in the model tree.

---

## 4. Two-image A/B of ROUTE1-21 (the controlled experiment)

**Design.** Two Docker images built from the *same* working tree, differing by exactly one expression.
The control is produced by `scripts/build_route1_control_image.py`, which reverts, builds, and
re-applies inside a `finally`, verifying the restored file against an md5 captured beforehand.

**Isolation, verified before spending the runs:**

| Check | Result |
|---|---|
| files differing between the two images | **1 of 706 `.py` files** (1290 files repo-wide) |
| ROUTE1-21 marker count, treatment / control | **2** / **0** (0 anywhere in control) |
| `v_rib == 0` guard present | in **both** |
| `simData.cPickle` | shared by NTFS hardlink ⇒ byte-identical by construction (md5 `991FEE48F5EC09C7003777355D82536F`, 90 389 857 B); **ParCa not rebuilt** |

**Sample.** 2 operon settings × 3 seeds = **6 cells**, **12 simulations**, each 121 listener rows /
0–120 s / dt = 1.0 s, minimal media, wildtype variant, SteadyState elongation + ppGpp regulation.
Row 0 is the pre-simulation listener dump and is all-zero in every run; **excluded**. 120 evolved steps.

**Results — clean-window median % change in total `rela_syn`:**

| arm | seed 0 | seed 1 | seed 2 | cross-seed spread |
|---|---|---|---|---|
| operons ON | **+0.00352%** (window 38) | **+0.00564%** (window **120**) | **+0.00661%** (window 57) | 1.88× |
| operons OFF | **+0.00272%** (window 18) | **+0.00440%** (window 73) | **+0.00400%** (window 26) | 1.61× |

**Scalar signature** — step-1 per-amino-acid ratio spread divided by effect size:

| arm | seed 0 | seed 1 | seed 2 |
|---|---|---|---|
| ON | 6.72e-6 | 6.84e-6 | 5.87e-6 |
| OFF | 1.53e-5 | 1.56e-5 | 1.38e-5 |

Rank order over nonzero amino-acid columns **preserved in all 6 cells**. The relative spread is
near-*constant* within each arm, which is a stronger consistency result than the raw spreads alone.

**Stop rule** (pre-registered: anything of order 10% on an ON run means the model of the change is
wrong): clean-window maxima **+0.0176% / +0.0141% / +0.0199%**, i.e. **250–350× below** the 5%
threshold and **~500–700× below** the 10% criterion. **Zero** steps ≥5% on any ON seed. Not triggered.

**Comparator sensitivity, verified rather than assumed.** ON seed 1 showed all four monitored series
bitwise identical across the full 120 steps. To establish that this was a real null and not a broken
read, the same uint64-view routine was applied to `rela_syn` itself: **120/120 steps differ**, first
differing step 1, max relative difference **1.4076e-4**; all series non-degenerate (row 1 ≠ row 120).

**Clean-window size is seed-dependent** (38 / 120 / 57 and 18 / 73 / 26) because divergence onset is a
`stochasticRound` coincidence. It is *not* a property of the change.

**`stochasticRound` divergence is quantised.** `ppgpp_conc` first differs by exactly
**+1.434373e-03 µM** (ON) and **−1.381216e-03 µM** (OFF), and every subsequent nonzero difference is an
**integer multiple** of that quantum (OFF first ten ratios 1, 9, 5, 3, 27, 11, 69, 35, …). These are
single-molecule count flips, i.e. the predicted mechanism, not a defect.

---

## 5. Step-2 groundwork — the isoacceptor mapping

**Source.** `sim_data.process.transcription.aa_from_trna`, a **(21, 86)** 0/1 matrix built in
`Transcription._build_charged_trna` (`transcription.py:1256`; allocated `:1300`, populated `:1317`),
keyed by `aa = trna[:3].upper()` on the **cistron** id (`:1302`) with renames at `:1303-1308` and a
hard-coded `RNA0-300..306` dict at `:1288-1296`.

| Invariant | Result |
|---|---|
| column sums | all exactly **1.0** |
| orphans / double-assignments / empty families | **0 / 0 / 0** |
| family counts nₐ | **[5,7,4,3,1,4,4,6,1,5,8,6,6,2,3,5,4,1,3,1,7]**, Σ = **86** |
| operons-ON vs operons-OFF trees | **bit-identical** |
| charging mask | 85 of 86; the single exclusion is `selC-tRNA[c]` |

**Reproduction hazard, recorded because it is silent.** Deriving the mapping from `rnas.tsv` name
prefixes plus the four documented renames yields **ILE = 4, MET = 7** — which still sums to 86 and so
appears correct — versus the authoritative **ILE = 5, MET = 6**. The whole discrepancy is one entry:
`RNA0-305[c]` maps to **ILE**, not the natural guess of MET. The flat-file route is therefore **not an
independent check** of the in-code mapping.

---

## 6. Step-2 groundwork — the shared-synthetase reduction

**Claim tested.** With `KMtf` broadcast per family (`KMtf_i := KMtf_a`), the shared-synthetase
denominator satisfies `Sₐ = Σᵢ uᵢ/KMtf_a = uₐ/KMtf_a` identically, so the family-aggregated
86-resolution charging flux equals the 21-resolution flux.

| Parameter | Value |
|---|---|
| families | **20** (charging-masked) |
| within-family splits per family | **200** random Dirichlet draws |
| state rows | **121** real logged timesteps |
| total evaluations | 20 × 200 × 121 = **484 000** |
| worst relative error | **6.9e-16** and **8.4e-16** (two independent runs) |

**Strength of the result.** The reduction holds for **arbitrary within-family splits**, not merely at
zero spread — which is stronger than the condition set as a gate. This is a direct consequence of the
shared-synthetase choice; a per-species denominator would not reduce.

---

## 7. Step-2 groundwork — resolution ratio r and family spread

| Quantity | operons ON | operons OFF |
|---|---|---|
| `r` (abundance-weighted split) | **1.2713 ± 2e-4** | **1.2423** |
| `r` (equal split) | **1.3283 ± 2e-4** | **1.3195** |
| gap between splits | **4.48–4.49%** | |
| global span of `r_abundance`, 34 simOut dirs | **1.1956 – 1.2713** | |

`r` is a **state function**, `r = 1 + [Σₐ (nₐ−1)fₐK_rta/cₐ]/D₂₁`, not a constant.

**Per-family Aₐ/Hₐ at the reference state:** SER **1.853024**, LEU **1.278956**, GLY **1.168997**.
These are identical under post-ODE, start-of-step and raw-count conventions — as they must be, since
Aₐ/Hₐ depends only on within-family *shares* and is scale-invariant in c.

**Anticodon degeneracy (measured).** The 86 tRNA **genes** carry only **41 distinct (family, anticodon)
pairs**. Anticodon-identical duplicates are not separate A-site queues. Cost to `v_rib`:

| Resolution | `v_rib` change |
|---|---|
| gene (86) | **−21.23%** |
| anticodon (41) | **−7.36%** |

Closed form `D₈₆ − D₂₁ = Σₐ (nₐ−1)fₐK_rta/cₐ` verified to **3.9e-16** elementwise, ratio of means
1.000000.

---

## 8. Corrections — figures that did not survive re-derivation

Recorded so they are not cited from earlier drafts.

| Claim | Status |
|---|---|
| `r` span high end **1.371027** | **Not reproducible** under any split, convention or timestep; nothing exceeds 1.3283 (and that is the equal split). **Dropped.** |
| `r` quoted to 7 significant digits, agreement 1.8e-5 | **Precision-inflated.** Independent re-derivation differs by 1.7e-4 (~10× the claimed agreement); the reference state was internally inconsistent. |
| Aₐ/Hₐ = SER 1.9118 / LEU 1.4105 / GLY 1.3419 | **Not reproducible.** Measured 1.8530 / 1.2790 / 1.1690. |
| A-site sum in current code = 1.084 (OFF) / 1.100 (ON) | **Refuted** — those are `activeRibosomeAllocated / UniqueMoleculeCounts.active_ribosome`, a ribosome-count ratio. True A-site sum ratio **0.99991 / 0.99996**. |
| `KD_RelA` = scalar 0.26 µM | **Corrected** — a **21-vector**, range 0.027–0.54 µM. 0.26 µM is the literature value, not what the runs use. |
| `trna_kms` spans 0.008–1.667 µM, "three orders" from `trna_to_K_T` | **Refuted** — max is **2.7** (PHE); 1.667 is merely the first element. Ranges **overlap** `K_T` (2.4374–558.475). Real separation median/median 10.4×. |
| naive-lift phantom capacity 28.6%, worst family VAL 1.710 | **Corrected** — **~20–25%**; worst families **GLY 1.529, ALA 1.511**; VAL measures 1.000–1.140. |
| `Wₐ == nₐ` and `Vₐ == 1` reported at machine precision | **Tautologies** under the abundance split, true for any data; exact 0.000e+00, not 8.88e-16. |
| the 21.27% RelA drop is unavoidable under every option | **Configuration-specific.** Exact (to 14 significant figures) for 21-aggregated pools fed 86-derived `v_rib` into an unmodified expression; **identically absent** under ppGpp@21 + occupancy form. |

---

## 9. Known limits of the evidence

1. **Generations are untested.** Every charging-enabled output on disk is **generation 0 only, 120 s**.
   Seeds are covered (n = 3); generations are not. Full-generation drift is **unmeasured**.
2. **The clean window is defined on four monitored series**, not the full state vector, so identity of
   the entering state inside the window is *inferred*. Only the **step-1** measurement is
   unambiguously a pure direct effect.
3. **The request path is untested.** `rela_syn` is written only at the evolve call; the request call
   discards `v_rela_syn`, so this design is blind to it.
4. **The OFF magnitude prediction is met in kind, not value** — measured 2.0–3.3× smaller than
   predicted on all three seeds, consistently. Candidate explanation, unverified: the OFF arm's
   `rela_syn` is ~92% TRP, and *E. coli* has a single tryptophan tRNA, so that arm is dominated by a
   family the split does not resolve.
5. **Post-divergence excursions reach 4.78% (ON) and 287% (OFF).** These are chaos and carry no causal
   reading, but they do establish that the change is **not inert once trajectories separate**.
6. **Coverage** is wildtype variant only, one medium, SteadyState + ppGpp. The kinetic-elongation arm
   is untested under ROUTE1-21.
7. **The `limit_v_rib` clamp's binding frequency is unmeasured**, so the materiality of the
   clamp/aggregation non-commutation is unestablished.
