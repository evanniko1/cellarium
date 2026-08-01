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
| at `equal`, within-family spread follows the kinetic model's **rank ordering** (GLY then LEU) | **Withdrawn.** The *magnitude* replicates (6.18e-2 at 40 s vs 6.63e-2 at 20 s) but the ranking does not: at 20 s the leader is **LYS 6.63e-2**, with GLY 6.05e-2 and ALA 4.06e-2, and LEU is not in the top three. See §9.3. |
| A-site sum in current code = 1.084 (OFF) / 1.100 (ON) | **Refuted** — those are `activeRibosomeAllocated / UniqueMoleculeCounts.active_ribosome`, a ribosome-count ratio. True A-site sum ratio **0.99991 / 0.99996**. |
| `KD_RelA` = scalar 0.26 µM | **Corrected** — a **21-vector**, range 0.027–0.54 µM. 0.26 µM is the literature value, not what the runs use. |
| `trna_kms` spans 0.008–1.667 µM, "three orders" from `trna_to_K_T` | **Refuted** — max is **2.7** (PHE); 1.667 is merely the first element. Ranges **overlap** `K_T` (2.4374–558.475). Real separation median/median 10.4×. |
| naive-lift phantom capacity 28.6%, worst family VAL 1.710 | **Corrected** — **~20–25%**; worst families **GLY 1.529, ALA 1.511**; VAL measures 1.000–1.140. |
| `Wₐ == nₐ` and `Vₐ == 1` reported at machine precision | **Tautologies** under the abundance split, true for any data; exact 0.000e+00, not 8.88e-16. |
| the 21.27% RelA drop is unavoidable under every option | **Configuration-specific.** Exact (to 14 significant figures) for 21-aggregated pools fed 86-derived `v_rib` into an unmodified expression; **identically absent** under ppGpp@21 + occupancy form. |

---

## 9. The demand split is degenerate at the default — reported, not hidden

This section exists because the finding is easy to mistake for a null result. It is not: it is a
**structural property of the fixed point**, and it fully determines what the switch can and cannot do.

**The configuration decision.** `abundance` stays the **DEFAULT** — it is the conservative choice and
it reproduces the 21-resolution answer. `equal` ships as the **SCIENCE configuration**. The degeneracy
of `abundance` is documented at the point of choice (the `--trna-demand-split` help text and the
ROUTE1 comment block above `get_charging_params`), not buried.

### 9.1 Why the kinetics cannot distinguish isoacceptors — *structural*

`KMtf_trna` is built at `models/ecoli/processes/polypeptide_elongation.py:1749` (line numbers as of
stage 6; this file has moved repeatedly — re-grep rather than trusting them) as

```
KMtf_trna = A2T @ transcription.trna_kms.asNumber(CONC_UNITS)[aa_charging_mask]
```

`A2T` is the transpose of the one-hot `(20, 85)` family map (`T2A`, built at lines 1743–1745 and
asserted one-hot by column at line 1942), so this is a **per-family broadcast**:
`KMtf_trna[i] = trna_kms[family(i)]`. Its within-family spread is therefore **exactly 0.000e+00** —
structural, not measured-to-be-small. **Nothing in the kinetics tells isoacceptors of one family
apart.** There is no setting of this model in which it does.

### 9.2 Why `abundance` forces a uniform charged fraction — *derived, from the code*

| Step | Source |
|---|---|
| `du_i/dt = −dtrna_i`, `dc_i/dt = +dtrna_i` via `np.hstack((-dtrna, dtrna, daa, ...))` — so **`T_i = u_i + c_i` is conserved exactly, per species** | `polypeptide_elongation.py:1887` |
| `v_i = family_rate[a] · u_i/KMtf_i`; with `KMtf` broadcast, `v_i = (family_rate_a/KMtf_a)·u_i` — **proportional to `u_i`** | lines 2210, 2218, 2221 |
| `dtrna_i = v_i − v_rib·f_i`; fixed point ⇒ `v_i = v_rib·f_i` | line 2251 |
| `abundance`: `f_i = f_a·(u_i+c_i)/T_a = f_a·T_i/T_a` | lines 2237–2244 |
| `equal`: `f_i = f_a/n_a` | lines 2233–2236 |

Combining:

- **`abundance`** — `u_i ∝ T_i` at the fixed point. `T_i` is conserved, so `c_i = T_i − u_i ∝ T_i`
  too, and **`c_i/T_i` is constant within the family**. The charged fraction is uniform **by
  construction**. It is not a finding about *E. coli*; it is the fixed point of the equations.
- **`equal`** — `u_i` is *constant* within the family, so `c_i/T_i = 1 − u/T_i` inherits the `T_i`
  heterogeneity. Spread develops — but it comes from **pool sizes**, still not from kinetics.

### 9.3 Measurement

Worst per-family spread in `GrowthLimits/fraction_trna_charged`, over the **17 multi-member
families**, from real simulations — not analytic; the ODE was integrated by the production code path.
Measured **twice, at two run lengths, by two implementations**. The second measurement is
reproducible via `scripts/measure_within_family_spread.py`, run inside the model image:

| Configuration | 40 s run | 20 s run (independent re-measurement) | Reading |
|---|---|---|---|
| family (control) | **exactly 0.0** | **exactly 0.000e+00** | one value per family; nothing to spread |
| isoacceptor + `abundance` | **2.79e-7** | **2.16e-7** | **numerically zero** — solver residual, not structure |
| isoacceptor + `equal` | **6.18e-2** | **6.63e-2** | genuine spread |

The 20 s re-measurement also confirms `family / equal` is **exactly 0.000e+00** — i.e. the split is
inert at family resolution, as designed, rather than merely small.

**What replicates and what does not.** The *magnitudes* replicate: worst spread 6.18e-2 vs 6.63e-2
(≈7% apart, same order), and `abundance` is numerically zero in both. The **per-family identity does
not**:

| Run | Top three families at `equal` |
|---|---|
| 40 s | GLY **5.13e-2**, LEU **3.07e-2** |
| 20 s | LYS **6.63e-2**, GLY **6.05e-2**, ALA **4.06e-2** |

GLY is large in both; **LYS leads at 20 s and LEU is not in the top three there.** So the *ranking* is
**not established** — it moves with run length, which is what one expects of a quantity driven by
transient pool sizes rather than by a fixed parameter.

Consequence for the comparison to the kinetic model (GLY **0.372**, LEU **0.241** at 120 s): the
earlier reading that `equal` reproduces the kinetic model's *rank ordering* **does not survive** the
second measurement and is **withdrawn**. What survives is the magnitude statement — `equal` produces
spread roughly **7× smaller** than the kinetic model, i.e. it moves in the right direction and does
not arrive.

### 9.4 What this means for anyone selecting a split

1. Selecting `isoacceptor` resolution **with the default split** buys per-species *bookkeeping* and
   no per-species *biology*. Every 21-resolution output is unchanged (the shared-synthetase reduction,
   §6), and the 85-wide charged-fraction column carries 17 families of identical values.
2. If within-family structure is the object of study, **`equal` must be selected explicitly.**
3. Even at `equal`, the spread is **not evidence that the model resolves isoacceptor kinetics** — by
   §9.1 it cannot be. The spread that appears is a function of **pool sizes**, and §9.3 shows its
   per-family pattern is not even stable across run length, so it must not be read as a per-family
   prediction.
4. Closing the remaining gap requires either codon-resolved demand (`TrnaCharging/reading_events`,
   which sums to exactly 0.0 on every run on disk) or per-isoacceptor `KMtf` — a knowledge-base
   change, not a switch.

**Verification of the configuration change itself** (stage 6 of `scripts/route1_step2_patch.py`,
marker `ROUTE1 step 2 (stage 6): the abundance split's within-family degeneracy`): comment/help-text
only, no behaviour change; applier reports COMPLETE; revert → re-apply is **byte-identical across all
five patched files** (md5s compared in one process, and the reverted tree verified to differ in all
five — otherwise "identical" would be evidence of nothing), and a 20 s simulation starts and records
its selection at **both** splits.

### 9.5 The full test matrix — 3 arms × 3 seeds × 3 **full generations**

This closes the standing project rule (never validate on one seed or one generation), which §10.1 and
§10.8 previously recorded as **unsatisfied for every charging run on disk**.

**What ran.** 27 cells: `family` / `isoacceptor+abundance` / `isoacceptor+equal` × seeds 0,1,2 ×
generations 0,1,2. Real full generations to natural division — **not** length-capped: 2499–3310
timesteps each (2498–3309 s), every cell wrote `Daughter1_inherited_state.cPickle`, mass ratio
1.70–2.53. Daughters were produced by `SimulationDaughterTask`, so generations 1 and 2 also verify
that the two switches survive the daughter path (`simulationDaughter.py:36-37` allow-list,
`:94-95` `_get_default`, which falls back to the default only when the key is absent). All 9 chains
exited **0**; **0 cells** with any NaN in `fraction_trna_charged`, `ppgpp_conc`, `rela_syn`,
`instantaneous_growth_rate` or `cellMass`; **0** missing cells. Image `wcecoli-sim:route1matrix`,
verified to contain all six stage markers with the five patched files byte-identical to the tree.
`kb/` hardlinked from `out/kinetic_parca/kb` (same inode), so `simData.cPickle` is identical by
construction and no baseline directory was written.

**A maximum over ~3000 timesteps is not a level.** Reported here as the *distribution* of the
worst-family spread per timestep, pooled over the 3 seeds of each generation:

| Arm | median gen0 | median gen1 | median gen2 | timesteps > 1e-2 |
|---|---|---|---|---|
| family (control) | **0.000e+00** | **0.000e+00** | **0.000e+00** | **0 of 24 807** |
| isoacceptor + `abundance` | 4.7e-8 | 1.8e-7 | 2.7e-7 | **0 of 25 493** |
| isoacceptor + `equal` | 5.2e-2 | 5.7e-2 | 6.6e-2 | **25 931 of 25 931** |

1. **The negative control is exact, not approximate.** At family resolution the spread is
   **0.000e+00 at every one of ~24 800 timesteps**, across 3 seeds and 3 generations — median, 99th
   percentile and maximum all exactly zero.
2. **`abundance` is numerically zero and stays there.** Median ~1e-7, and **not one timestep in
   ~25 500** exceeds 1e-2. It is ~5 orders of magnitude below `equal`.
3. **`equal` is sustained, not transient.** **Every** timestep in the arm exceeds 1e-2, and the
   median magnitude 5.2e-2…6.6e-2 **replicates** the earlier single-generation figures (6.18e-2 at
   40 s, 6.63e-2 at 20 s). The §9.3 magnitude claim now holds across seeds *and* generations.
4. **Generation effect: present but immaterial.** `abundance`'s median rises ~6× (4.7e-8 → 2.7e-7)
   and `equal`'s ~27% (5.2e-2 → 6.6e-2) from generation 0 to 2. Neither changes any conclusion; the
   `abundance` prediction is exact zero and it remains numerically zero.
5. **Two transient episodes, named rather than hidden.** `abundance` seed 1 gen 2 reaches a maximum
   of 1.294e-3 (p99 6.3e-4, 404 steps above 10× its median) and `equal` seed 1 gen 2 reaches 7.375e-1
   (27 steps of 2919, on a median of 6.1e-2). Both are excursions on a chaotically diverged
   trajectory; neither carries the arm's end-of-generation value, which stays 3.8e-7 and 6.6e-2.
6. **The per-family ranking is still not established, and the withdrawal in §8 stands.** The leader
   moves *by generation*: gen0 LYS 7.27e-2, gen1 ALA 8.93e-2, gen2 LEU 7.38e-1. Do not cite an order.

**Between-arm differences in growth are CHAOS, not effect — measured, not assumed.** The arm summary
shows mean doubling times of 46.0 (family) / 50.3 (`abundance`) / 49.9 (`equal`) min, which invites
the reading that isoacceptor resolution slows the cell. It does not. Comparing the `cellMass` series
step by step within generation 0:

| step | 0 | 1 | 2 | 50 | 300 | 1200 | end |
|---|---|---|---|---|---|---|---|
| `abundance` vs family, relative | **0.0** | **0.0** | 2.8e-10 | 3.5e-5 | 2.2e-3 | 1.1e-2 | 3.0e-2 (seed 0), 1.1e-1 (seed 2) |

`abundance` is **exactly equal** to the family control for the first two timesteps and departs at
**2e-10** — the shared-synthetase reduction of §6 holding in production — then amplifies over ~3000
steps. The doubling-time, ppGpp and relA differences between arms are that amplification, and with
n = 3 seeds they are **not** evidence of a systematic effect of the switch.

**Reproduce.** `scripts/mx_setup.py` (hardlinked run dirs) → `scripts/mx_run.ps1` (the 9 chains) →
`scripts/mx_analyze.py` + `scripts/mx_report.py` (the matrix table) →
`scripts/mx_transient.py` (the distribution, not the max) → `scripts/mx_diverge.py` /
`scripts/mx_diverge2.py` (the chaos check). Outputs are in `out/mx_{fam,abu,equ}_s{0,1,2}`.

**Cost.** 19.7 GB for the matrix; 136.3 → 122.9 GiB free. ~56 min wall for 9 chains at 9-way
parallelism, peak ~7.4 GiB across all containers.

---

## 10. Known limits of the evidence

1. ~~**Generations are untested.**~~ **CLOSED by §9.5.** 3 arms × 3 seeds × 3 full generations to
   natural division (27 cells, 2499–3310 timesteps each, all exit 0, no NaN) now exist for the
   §9 spread claims. What remains open is narrower and is stated as such: (a) the matrix is
   **`--trna-charging` (SteadyState + ppGpp) only** — the ROUTE1-21 occupancy A/B of §4 and the
   `r`-drift measurement of §7 are **still generation-0 only**, so *those* figures have not inherited
   this coverage; (b) 3 generations is enough to show the spread magnitude is stable and the control
   is exactly zero, not enough to characterise long-lineage drift.
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
8. ~~**The §9 spread numbers are single-seed, generation 0, 40 s.**~~ **CLOSED by §9.5.** The `equal`
   magnitude now replicates across 3 seeds × 3 full generations (median 5.2e-2…6.6e-2, bracketing the
   original 6.18e-2), the `abundance` prediction of numerically-zero holds at **0 of ~25 500
   timesteps above 1e-2**, and the family control is **exactly 0.000e+00 at every timestep**. Two
   residual limits: the *per-family ranking* remains unestablished — the leader now moves by
   generation as well as by run length (§9.5.6), which strengthens rather than weakens the §8
   withdrawal — and the generation trend itself (`abundance` median ×6, `equal` +27% over three
   generations) is measured on n = 3 seeds and is **not** characterised beyond generation 2.
