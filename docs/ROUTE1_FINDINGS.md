# ROUTE1 — what we know

Findings and conclusions from the isoacceptor-resolution work on the wcEcoli tRNA charging model.
The companion document [`ROUTE1_VERIFICATION.md`](ROUTE1_VERIFICATION.md) is the evidence record —
every check with its sample size and tolerance. This document is the argument.

Written to be honest about what is established, what is not, and what was claimed and then refuted.
Section 7 exists because several conclusions in this line of work were stated confidently and later
overturned by measurement; anyone citing an earlier draft should read it first.

---

## 1. What the work set out to do

*E. coli* has ~86 tRNA genes but only 20 aminoacyl-tRNA synthetases. Leucine has 5 isoacceptors,
glycine 4, serine 5 — different anticodons, different abundances, all charged by one enzyme.

The scientific target is **selective charging**: under amino acid limitation, do all isoacceptors of a
family deplete together, or does the rarest crash first? It matters because ribosomes stall at
**codons**, not amino acids. If tRNA-Leu5 empties while tRNA-Leu1 stays charged, the cell stalls only
on genes using that codon — the mechanism Elf & Ehrenberg proposed.

At 21-amino-acid resolution the model cannot represent the question: "leucine" is one number.

---

## 2. What was built

Two changes, both applied through reproducible recipes
(`scripts/route1_occupancy_patch.py`, `scripts/route1_step2_patch.py`), never committed to the
wcEcoli tree directly.

**Step 1 — the A-site occupancy rewrite.** One expression in `ppgpp_metabolite_changes`, rewritten to
the renewal-theory occupancy form `Rⱼ/[R] = fⱼ(1+θⱼ)/D` it is derived from, in which the elongation
rate constant cancels identically. Purpose: remove `max_elong_rate` from the stringent-response
calculation so that resolving tRNA cannot leak into ppGpp. It also fixes a live defect — the
`v_rib == 0` branch applied the zero-waiting limit in the one regime where waiting is maximal.

> **CORRECTION — the starvation test does not support the "sign correction" reading.**
> An earlier draft of this document described this change as fixing a *sign error* under stress: the
> argument being that the old form fed RelA the *realized* throughput, which falls when ribosomes
> stall, so it would quieten the stringent response exactly when the cell is starving.
> **That is not supported.** `max_elong_rate` is itself ppGpp-dependent, so as ppGpp rises the rate
> law falls *with* realized throughput (kmax 19.09 → 3.61 aa/s, −81%) instead of staying high —
> **the rate law contains the stall.** Measured over 36/36 cells reaching ppGpp 56.6 → 353.5 µM and
> LEU 98.2% uncharged, the systematic effect *vanishes* under starvation rather than growing: the
> fraction of steps with Φ < 1 falls from **0.782 (p = 4.5e-33) to 0.503 (p = 0.89)**, a coin flip.
> The measured direct effect is **+92.88 ppm** and does not grow with depth.
> **This change is hygiene plus a limit-behaviour correction, not a sign correction.** See
> ROUTE1-83..88; the deep-stall regime itself remains unmeasurable, because the bitwise-clean window
> collapses to 2.3 steps while ppGpp does not double until step 17–30.

*Validated:* two-image A/B, 3 seeds × 2 operon settings, images differing in exactly 1 of 706 `.py`
files. Effect is a uniform scalar of +0.004%, with the per-amino-acid ratio spread ~1e-5 of the effect
— i.e. a rescaling, not a redistribution. Stop rule never approached.

**Step 2 — isoacceptor resolution.** The charging ODE runs at 85 species (86 minus selC) behind two
switches, `--trna-charging-resolution {family,isoacceptor}` and `--trna-demand-split
{abundance,equal}`, validated at entry and recorded in `metadata.json`. The A-site and ppGpp arms
stay at 21 by aggregating inside the right-hand side.

*Validated:* family path byte-identical (2904/2904 cases); the 85-form aggregates to the 21-form at
8.5e-16 over 4840 evaluations; ppGpp `delta_metabolites` integer-exact; `r == 1` to 7.1e-15; the
amino-acid clamp uses the aggregate-then-rescale form pinned by a dedicated test with a negative
control. Full 3 arms × 3 seeds × 3 generations matrix: 27/27 cells, no crashes, no NaN.

**The machinery works.** That is not in question.

---

## 3. The chain of findings

Four levels, each discovered because the level above did not explain the result.

### 3.1 The abundance split is structurally degenerate

`KMtf` is broadcast per family, so within-family `KMtf` spread is **exactly 0**. Under an
abundance-weighted demand split the fixed point is `uᵢ ∝ Tᵢ`, and since `Tᵢ = uᵢ + cᵢ` is conserved
exactly by the ODE, `cᵢ/Tᵢ` is **constant within a family**. Charged fraction is uniform by
construction.

Measured: family control **exactly 0.000e+00** at all 24,817 timesteps; `abundance` **2.79e-7**
(solver residual); `equal` **6.18e-2**. Ratio equal/abundance: 1.4e5 to 1.1e6.

The widening itself is real, proven by a horizon sweep: at 1e-6 s integration, **99.97% of input
spread survives**, decaying monotonically to the fixed point, whereas the pre-widening uniform
expansion is **exactly 0.0 at every horizon**. That distinguishes a broken interface from a
degenerate split. It is the latter.

### 3.2 The `equal` split gives real, persistent spread — 7× too small

5–7 percentage points, reproducing across seeds in **pattern as well as magnitude** (Spearman between
seed pairs 0.94–0.99). It **persists and grows across generations** — 5.2e-2 → 5.7e-2 → 6.6e-2,
monotone in all three seeds, surviving the daughter-cell path. Not a startup transient.

But the kinetic reference showed **0.348 for glycine**. We showed 0.05.

### 3.3 Per-isoacceptor `KM` cannot close that gap

Two channels, both inverted exactly against measured pool-share movement (`‖Δw‖₁` = 0.011–0.014 per
timestep, saturating by lag 60 s — shares are **stationary, not drifting**).

- **Drift channel:** needs `D/mean(1/KM) ≥ 222`, but that quantity is bounded above by `nₐ` — **6 for
  glycine, 8 for leucine**. Mathematically impossible, not merely implausible.
- **Static channel:** needs 4.3× (GLY) to 7.5× (LEU) more within-family discrimination than a real
  synthetase shows in the reference set itself. At defensible ratios you reach 27–35% of target.

There is also a ceiling independent of `KM` entirely, `spread ≤ gₐ/w_min`, under which **3 of 9 runs
cannot reach the glycine reference at any `KM` whatsoever**.

### 3.4 The real limit was the charging level

Spread scales **linearly** with the uncharged fraction. The steady-state arm sat at **97% charged**;
the kinetic arm at 78%. That 7× deficit in uncharged tRNA *is* the 7× spread deficit — the same
number, not a coincidence.

---

## 4. Why the model sat at 97%

One constant: `KMtf`, the Michaelis constant for uncharged tRNA binding its synthetase, at **1 µM**
against per-family pools of ~13 µM. The enzyme is 12× into saturation.

**The algebra is exact.** The rate-law denominator factorises, so at steady state

```
u_a = KMtf_a · ρ/(1−ρ)          g_a = (KMtf_a/T_a) · ρ/(1−ρ)
```

The **absolute uncharged pool contains no `T_a`** — it is pinned by `KMtf` alone, so a large total
pool mechanically forces a small uncharged *fraction*. The closed form reproduces the simulation to
4e-4.

**Three independent lines converge on the constant being wrong as used:**

1. **The provenance is circular.** It traces via Bosdriesz 2015 to Elf & Ehrenberg 2005 Table 2, who
   took 1e-6 M from the BRENDA database paper and labelled it a **dissociation** constant — in a model
   that **assumed complete charging**. The constant producing 97% charging was inherited from a model
   that presupposed it.
2. **A one-sided filter admits it.** `transcription.py:1411-1413` discards any `Km > 5 µM` as
   "suspiciously high", with **no low-side counterpart**. It throws away real values at 56, 14.1 and
   13 µM — and **70 of the 85 `K_T` values this project's own optimiser selected would be rejected by
   that same filter**. Meanwhile valine's single **0.008 µM** datum, 125× below default, passes
   unchallenged and pins that family at 99.99% charged.
3. **Inversion from measurement.** Since `u` scales linearly in `KMtf` at fixed saturation, inverting
   the model's 6.94 µM uncharged pool onto the measured charged range (0.68–0.90) implies an
   **effective `KMtf` of 3.4–10.7 µM — bracketing 10, excluding 1**. A 1 µM effective constant
   requires ≥97% charging, a figure asserted only by this model.

`~1 µM is correct as the *in vitro* constant` (N=77 primary values with per-row PubMed IDs, median
0.60 µM). No **in vivo effective** Km has ever been measured. The defect is using an in vitro
dissociation constant as an in vivo effective one.

**The 97% itself survived five adversarial attacks** — raw-count re-derivation (0.9690 vs listener
0.9687), initialisation, ten alternative aggregations, and pool turnover. Two attacks backfired: the
listener defect is in the *kinetic* arm (overstating by +1.7 pp, so the gap was **understated**), and
family-resolution correlation is causal — `Spearman(KMtf, uncharged amount) = +0.686, p=8.4e-4`, while
pool size gives `+0.021, p=0.93`, with the kinetic arm exactly reversed.

---

## 5. The fix, and what it showed

Applied: drop the one-sided filter, geometric mean, add a low-side outlier rule, and raise
`Km_synthetase_uncharged_trna` 1 → 10 µM as a **declared effective constant**. ParCa rebuilt.

**Result: FIX-PARTIAL.** Charged fraction **0.9711 → 0.9331** (N=27, raw counts, paired t = −20.31),
closing **20.7%** of the gap. Zero of 27 cells reach 0.71–0.86.

**The value of the partial result is that it localises the residual.** Forcing 0.788 would require a
uniform **29 µM**, and 0.71 would require **82 µM** — above every in vitro datum *and* above the
kinetic arm's own `K_T`. **The remaining gap is the charging/A-site rate law, not this constant.**

Spread behaved as the mechanism predicted but not as hoped: the linearity is confirmed (r = 0.994
across 17 families), but the aggregate uncharged fraction rose only **2.30×**, so the large global
rise was never available. Glycine reached **0.457 against the 0.348 reference** (factor 1.31) while
**9 of 17 families fell** and the worst family changed identity. ppGpp did **not** run away — balance
unchanged, though the pool drifted to 72.7 µM, above the 25–67 µM measured band.

---

## 6. The finding that reframes the target

**The kinetic reference is not fitted to any measurement, and its cell does not respond to selective
charging.**

- `trna_charging_objective` has five terms: two self-consistency residuals, a regulariser
  `w_r·sum(K_T)`, a barrier, and our own anchor which is **zero by default**. Upstream the objective
  has **four terms and none contains a measurement**. The charged fraction is a **free decision
  variable**.
- At the shipped optima, **94–99% of the objective is penalty, not fit residual** — feasibility is a
  hard accept/reject applied *after* minimisation, so what selects the solution is `sum(K_T)` pushed
  down until a box bound on `f` stops it. The barrier is symmetric about `f = 0.5`, an un-cited pull
  toward 50% charging.
- **`K_T` is not identified by the data.** `rank(J) = 4·n_K_T` in **all 20** synthetases — family size
  contributes **zero** information, because tRNAs sharing a `K_T` group give the same equation.
  Finite perturbations confirm it: doubling any group stays feasible **21/21**, halving **31/32**,
  with residuals returning **twelve orders of magnitude** below the acceptance filter. **8 of 20
  synthetases have exactly one `K_T` group** and therefore no within-family structure by construction.
- **The kinetic model does not make the cell feel depletion.** `elongation_rate` reads a
  **media-specific target** and never consults tRNA state. The only isoacceptor-sensitive term is a
  **5% dead zone that never fired** — 0 of 120 timesteps in all four reference runs, global minimum
  charged fraction 0.1379. The isoacceptor split is **column-normalised**, so depleting one
  isoacceptor reallocates load to its siblings and the codon's total reading rate is invariant.
  Measured: elongation rate constant at **17.32 aa/s (CV 0.0015)** while per-isoacceptor charged
  fraction ranges **0.138–1.000**.

So GLY 0.348 was never ground truth. It is the output of a regulariser and a box bound, in a model
where the cell does not respond to it. **Matching it was the wrong success criterion**, and much of
the effort in §3.3 was spent inverting toward a target that measurement never constrained.

---

## 7. Claims made and later refuted

Recorded because several were stated confidently in intermediate work.

| Claim | Status |
|---|---|
| Abundance-weighted split is the principled default | **Wrong in effect.** It is the one split that makes within-family spread structurally impossible. |
| Per-isoacceptor `KM` destroys the exact reduction | **Wrong.** The family still collapses — to a share-weighted harmonic mean `1/KM_eff = Σ wᵢ/KMtfᵢ`. What is lost is *constancy*, not the collapse. |
| The growth offset is "inside the seed-noise band" | **Argument fails.** 7% per-run CV does not license it for an offset between 9-cell means; SE is ~3.6%. The conclusion survives via the degenerate arm as a positive control, which shows a *larger* spurious effect than the real arm (r = 0.969 between their per-seed offsets). |
| "Chaotic amplification" | **Mis-named.** Degenerate-arm offsets are 3/3 same-sign, indicating systematic round-off bias, not unbiased chaos. Still non-biological. |
| Generation-0 division-time equality is decisive | **Weak.** The same division step appears in trees with different configurations. |
| The fitted `f` implies 0.8181, close to the kinetic arm | **Worthless as evidence.** 0.8181 and 0.832 are `1 −` mean/median of a **fitted free variable read by nothing**; matching them to listener columns was coincidence. |
| Charged fraction 0.9729 | **0.9690** (N=27 pool-weighted). 0.9729 was a narrower slice. |
| Kinetic reference GLY 0.372 / LEU 0.241 | **0.348 ± 0.032 / 0.248 ± 0.014** (N=12). The originals were single-run, single-timepoint. |
| Tripling the uncharged pool roughly triples RelA synthesis | **Falsified by measurement.** Balance moved 1.056 → 1.067, not resolvably. |
| `r` spans up to 1.371027 | **Not reproducible** under any split or convention; nothing exceeds 1.3283. |
| `out/kinetic_parca` is a kinetic run | **No.** The name refers to the ParCa build; the simulation inside ran SteadyState. The kinetic reference is `out/operonsON_kin_probe`. |

---

## 8. What is established, and what is not

**Established:**

- The occupancy form is correct and its effect is a uniform +0.004% scalar.
- Isoacceptor resolution works, is switch-controlled, and leaves the family path byte-identical.
- The abundance split is degenerate for a structural, provable reason.
- The `equal` split produces spread that reproduces across seeds and persists across generations.
- `KMtf` at 1 µM is an in vitro dissociation constant used as an in vivo effective one, on circular
  provenance, admitted by a one-sided filter.
- The kinetic reference's `K_T` is not identified by measurement, and its cell does not respond to
  isoacceptor depletion.

**Not established:**

- Whether the steady-state arm can reach 71–86% charged at all — the residual after the `KMtf` fix
  points at the rate law, which has not been examined.
- What the in vivo effective Km actually is. No measurement exists; 3.4–10.7 µM is an inversion.
- Whether within-family spread has any physiological consequence in *either* model. Neither lets
  codon-specific depletion affect elongation.
- Whether the spread grows beyond generation 2. The trend is three points.
- Clamp binding frequency in production, which sets how material the aggregate-then-rescale fix is.

---

## 9. The open question worth stating

**No whole-cell model in this lineage — ours or the reference — lets codon-specific tRNA depletion
affect elongation rate.** Ours aggregates to 21 before the ribosome arm by design. The reference reads
a media-specific target and its one isoacceptor-sensitive term never fires.

Closing that needs the A-site arm at **anticodon resolution** — the 41 distinct (family, anticodon)
pairs, not the 86 genes, since anticodon-identical duplicates are not separate queues (measured cost
−7.36% on `v_rib` versus −21.23% at gene resolution). The codon↔tRNA mapping, codon usage and
codon-resolved sequences all already exist in the tree. What does not exist is **measured
codon-specific elongation data** (ribosome profiling) to fit or validate against, and **measured
per-isoacceptor charged fractions** beyond Dittmar's five leucine values in a non-matching medium.

That is the honest scope boundary: the machinery is largely present, the data is not.
