# ROUTE1 — what we learned

The plain-language account. Companion to two other documents, and the one to read first:

- [`ROUTE1_VERIFICATION.md`](ROUTE1_VERIFICATION.md) — the evidence record: every check with its sample
  size and tolerance.
- [`ROUTE1_FINDINGS.md`](ROUTE1_FINDINGS.md) — the argument, with the claim-by-claim corrections table.
- This document — the causal story, for someone who wants to know what happened and why it matters.

Every claim below links to its backlog row in [`../BACKLOG.md`](../BACKLOG.md). Where a claim was made
and later withdrawn, both rows are cited.

---

## The question

Can the whole-cell model track individual tRNA isoacceptors, so we can study whether the rarest
leucine tRNA runs out first under stress? That is **selective charging**, and it matters because
ribosomes stall at *codons*, not amino acids. At 21-amino-acid resolution "leucine" is one number and
the question cannot be asked.

## What we built, and does it work

Yes, mechanically. The charging ODE runs at 85 tRNA species instead of 21, behind switches that
default to the old behaviour.

| property | result | rows |
|---|---|---|
| old path unchanged | byte-identical, **2904/2904** cases | ROUTE1-39, ROUTE1-46 |
| new maths reduces to old | **8.5e-16** over 4840 evaluations | ROUTE1-31, ROUTE1-39 |
| ppGpp arm untouched | `delta_metabolites` integer-exact | ROUTE1-39, ROUTE1-46 |
| full matrix | **27/27** cells, no crash, no NaN | ROUTE1-47 |

**It just does not show the phenomenon.** Chasing that led somewhere more interesting than the
extension.

---

## Four findings, in causal order

### 1. The model's cells are far too charged — 97% against 71–86% measured

Within-family spread scales **linearly** with the uncharged fraction. With only ~3% uncharged there is
almost nothing to differentiate. Our 5% spread against the reference's 35% is the *same 7× ratio* as
the uncharged deficit — the same number, not a coincidence.

The 97% survived five adversarial attacks including re-derivation from raw counts (0.9690 vs listener
0.9687), initialisation, ten alternative aggregations, and pool turnover.
→ ROUTE1-55, ROUTE1-65, ROUTE1-66

### 2. The cause is one constant used for the wrong job

The synthetase's tRNA binding constant is **1 µM** against tRNA pools of ~13 µM, so the enzyme sits
deep in saturation. The steady-state algebra is exact and reproduces the simulation to 4e-4:

```
u_a = KMtf_a · ρ/(1−ρ)      — the absolute uncharged pool contains no pool-size term
```

Two things make this a defect rather than a judgement call:

- **Circular provenance.** It traces through two modelling papers to a database value labelled a
  *dissociation* constant, chosen **in a model that assumed complete charging**. The constant that
  produces 97% charging was inherited from a model that presupposed it.
- **A one-sided filter.** The reconstruction discards any measurement above 5 µM as "suspiciously
  high", with no lower bound — and **70 of the 85 values this project's own fitting routine selected
  would be rejected by it**. Meanwhile valine's single 0.008 µM datum passes unchallenged and pins
  that family at 99.99% charged.

~1 µM is *correct as an in vitro constant* (N=77 primary values, median 0.60 µM). No in vivo effective
Km has ever been measured. The defect is the substitution of one for the other.
→ ROUTE1-60, ROUTE1-61, ROUTE1-62, ROUTE1-67, ROUTE1-68

### 3. The rest cannot be closed by turning any single knob — but not for the reason first given

The fix moved charging **0.9711 → 0.9331**. I then claimed the remainder was unreachable, with an
arithmetic bound. **That bound was wrong, and the test showed why.**

**The cell responds.** Cut the enzyme's capacity and ppGpp rises, elongation slows, demand falls, and
charging partially recovers.

| | assumed | measured |
|---|---|---|
| ALA charged fraction at divisor 2.20 | **0.0000** | **0.8560** (from 0.9120) |
| ρ rise | 2.200× | **1.285× median** |
| elasticity `dln(ρ)/dln(divisor)` | 1.000 | **0.318** |
| families reaching zero charge | 2 | **0** |

Tryptophan makes it vivid: **its charged fraction rose when capacity was cut**, because demand fell
faster than supply.

The conclusion survives in a better form: a uniform capacity cut is **less** effective than a static
calculation suggests — the cell absorbs it. That is a property of a regulated system, not an
arithmetic ceiling.
→ ROUTE1-74, ROUTE1-77 *(withdrawn)*, ROUTE1-95, ROUTE1-96, ROUTE1-97

### 4. The target was never measured

The reference model's fitting objective contains **no measurement at all**. The charged fraction is a
**free variable** in its own fit. Its per-isoacceptor constants are **not identified by data** —
doubling them stays feasible 21/21, rank analysis gives no information from family size, and **8 of 20
synthetases have no within-family structure by construction**. What selects the values is a
regulariser pushing them down until a box bound stops it.

Its cell does not respond to isoacceptor depletion either: elongation reads a **media lookup**, and the
one term that could react has a 5% threshold that **never fired in any run** (0 of 120 timesteps,
four runs) while charged fraction ranged 0.138–1.000.

**So there was no ground truth.** Considerable effort went into inverting toward a number measurement
never constrained.
→ ROUTE1-71, ROUTE1-72, ROUTE1-73, ROUTE1-58

---

## What was wrong with how the work was done

**Three times the same error: a quantity the model regulates was held fixed in a derivation.**

| claim | what moved | rows |
|---|---|---|
| "RelA synthesis will roughly triple" | it did not move at all | ROUTE1-75 |
| "the old expression is backwards under starvation" | `max_elong_rate` falls with ppGpp too | ROUTE1-83, ROUTE1-88 |
| "capacity cuts are bounded at 3.10×" | demand falls with capacity | ROUTE1-95 |

Each derivation was internally correct. Each was evaluated over a feedback path that was never traced.

**Aggregate reporting hid it.** 14 of 18 claims weaken or fail when all 20 families are shown. The
KMtf fix headline is carried **109% by four families** that happened to sit on the default, while
**9 of 20 had the constant fall** and **13 of 20 moved away from the reference**.

Most telling: the evidence for finding 3 was **already on disk**. The starvation ladder showed
aggregate charge *recovering* as the throttle deepened — the exact feedback signature — while a
single-family readout was being reported. A fresh campaign was run to establish something the
reporting style had been obscuring.
→ ROUTE1-80, ROUTE1-89, ROUTE1-101

**Standing rule adopted:** per-family reporting for any family-resolved quantity. Aggregate-only is
not acceptable, because the model's own per-family spread (0.618–0.998) is **wider than the band being
matched against**.

---

## What the extension is actually worth

**A working instrument for a measurement the model cannot support and the field cannot validate.**

- It **observes** selective charging: 5–7 percentage points, reproducing across seeds (Spearman
  0.94–0.99 between seed pairs), persisting and mildly growing across three generations, surviving the
  daughter-cell path. → ROUTE1-47, ROUTE1-48
- It cannot make the cell **feel** it. Our design aggregates before the ribosome arm; the reference
  does not respond either. **No model in this lineage lets codon-specific depletion affect
  elongation.** → ROUTE1-73
- **Data to close it:** per-isoacceptor charging **exists and is usable** (M9-glucose, N=40/46 tRNAs,
  all 20 families). Codon-resolved elongation, in vivo Km, and absolute uncharged tRNA
  concentration — **none exist**. → ROUTE1-81

---

## The four findings that stand on their own

None depends on the extension succeeding:

1. A widely-used whole-cell model runs ~20 percentage points over-charged, traceable to one constant
   with circular provenance admitted by an asymmetric filter.
2. Its kinetic arm's isoacceptor parameters are **unidentified** — shown by rank analysis and finite
   perturbation, not asserted.
3. Neither arm propagates codon-specific tRNA depletion to elongation.
4. **Static parameter counterfactuals in whole-cell models overstate their effect ~3×** — measured
   elasticity 0.318 against an assumed 1.0.

The fourth is methodological and applies well beyond this model.

---

## Scope limits that travel with all of it

- The capacity campaign is **one point** (divisor 2.20). Extrapolation beyond it is **inferred**.
- **No ParCa refit** in that campaign, so enzyme expression could not re-optimise.
- **3 seeds × 1 generation** there — half the standing validate-across-seeds-and-generations rule.
- The `v_rib == 0` branch is **latent, not live**: 0 of 191,171 timesteps across 97 runs; the only
  firings are in a single dead cell. → ROUTE1-98
- The demand-split robustness result holds **same-state only**; across timesteps it fails at 194%
  relative. → ROUTE1-99
- The aaRS kcat inequality holds unanimously for **six** families, not the four originally named.
  → ROUTE1-100
