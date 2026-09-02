# ROUTE1 corpus record — what the extension simulations showed, before they are deleted

**Purpose.** The ROUTE1 isoacceptor-resolution exploration produced ~80 GB of simulation output on this
machine and reached a documented dead end. The exploration's *narrative* is preserved elsewhere: the code,
the regression nets and the ROUTE1-1..101 decision log live in the extension repository
(`BACKLOG.md`, item `EXT-ISO-1`), and its three findings docs (`ROUTE1_VERIFICATION.md`,
`ROUTE1_FINDINGS.md`, `ROUTE1_WHAT_WE_LEARNED.md`) are in that repo, not this one. What is **not**
preserved anywhere is the **numbers** — they exist only as bytes in `C:/dev/wcEcoli/out`. This document
makes them citable without a re-run.

**Order of operations, non-negotiable.** Record first, verify the record is complete, delete only then.
That order was followed. Sections 1–11 were written and committed (`65137bf`) **before** anything was
deleted; the deletion was executed afterwards, against a list re-derived from scratch rather than read
back out of this document. §7 records what was deleted and what was held back; §8 the manifest impact.

> **STATUS: EXECUTED, 2026-08-03.** 127 of the 128 candidates were deleted — **72.385 GB, 43 261 files**.
> `_r1s_npz` was retained, and the 17 analysis scripts were copied into this repository before their
> originals were removed. Everything below §7 describes runs that **no longer exist on this machine**;
> the numbers in §2–§6 are now the only record of them.

**Evidential standing** is labelled on every claim: **SIMULATED** (came out of a run on disk) ·
**ALGEBRAIC** (arithmetic we did on run outputs) · **CODE-READ** (read off model source) ·
**ARGUED** (reasoning, no direct evidence).

---

## 1. How the runs were identified, and how that was verified

`C:/dev/wcEcoli/out` holds **136 top-level entries, 80.700 GB, 49 407 files** (MEASURED, `os.stat` walk).
Naming alone does not separate ROUTE1 work from reference data — `kinetic_parca` and `km_parca` differ by
three characters and belong to opposite categories. Two independent discriminators were used instead.

**Discriminator 1 — the run's own recorded options (CODE-READ from each `metadata/metadata.json`).**
ROUTE1 is the `explicit_trna_charging` axis. Exactly **103** run directories carry
`"explicit_trna_charging": true`. Every one of them also carries
`"elongation_model": "SteadyStateElongationModel"`, `kinetic_trna_charging: false`,
`coarse_kinetic_elongation: false`. The protected reference builds carry the **opposite** signature —
`kinetic_trna_charging: true` with `explicit_trna_charging` absent — which is what separates
`kinetic_parca` from `km_parca` on evidence rather than on spelling.

**Discriminator 2 — knowledge-base identity (MEASURED, md5 over every `simData.cPickle`).** Grouping all
136 entries by kb hash resolves the three directories that carry no metadata at all:

- `sk_f050`…`sk_f090` each share a kb hash with **exactly** the six `mf<rung>_{c,t}_s{0,1,2}` runs at the
  same rung (e.g. `3a58ea27…` = `sk_f060` + the six `mf060_*`). They are the throttled knowledge bases the
  `mf` ladder consumed. `sk_f100` hashes to `afb48d8c…`, the *untouched* `km_parca` kb — which is what
  `out/_aa_kcat_throttle.py` documents for factor 1.0 ("byte copy, no re-pickle"). CONFIRMED ROUTE1.
- `_a1kb_thr` shares hash `70368c7f…` with `a1t_s0`/`a1t_s1`/`a1t_s2` and nothing else. It is the
  kS-throttled kb of the A1 treatment arm. CONFIRMED ROUTE1.
- `_r1s_npz` is the extraction output of `out/_r1s_extract.py` over the `mf` ladder (36 `.npz`, 26 MB).

**A consequence worth stating (MEASURED).** All 103 ROUTE1 run directories carry a copy of their kb —
**10.545 GB** in total across only **14 distinct pickles**. Two of those 14 are the *retained* reference
kbs: `991fee48…` is `kinetic_parca`'s kb, shared by 32 ROUTE1 runs; `22cca4b7…` is
`kinetic_parca_operons_off`'s, shared by 7. Deleting the ROUTE1 directories therefore does not remove any
distinct knowledge base that is not retained elsewhere. Simulation output proper is **61.207 GB**.

**Held back, not classified (NEEDS-DECISION).** Five directories are neither confirmed ROUTE1 nor named in
the protected list, so they are **excluded from the deletion candidates** pending an explicit call:
`refit_none`, `refit2_none`, `refit_A055w3`, `refit_shipped` (all `kinetic_trna_charging: true` — the
*kinetic* model's refit axis, not the explicit/ROUTE1 one) and `kinetic_parca_operons_off` (a ParCa build,
sibling of the protected `kinetic_parca`). Together **5.665 GB**. Erring toward retention is deliberate:
misclassifying reference data as extension work is the only irreversible error available here.

**Not present.** No ROUTE1 run directory exists under `<repo>/runs`. That tree holds
`runs/cellarium` (the corpus) plus 24 loose logs and scratch scripts. This is a MEASURED absence from a
successful directory listing, not a failed read.

---

## 2. Campaign inventory (N per arm)

| campaign | design | N |
|---|---|---|
| `mx_{fam,abu,equ}_s{0,1,2}` | resolution × split, 3 generations | 3 arms × 3 seeds × 3 gens = **27 generation-runs** |
| `km3_{fam,abu,equ}_s{0,1,2}` | same, different K_M kb | 3 × 3 × 3 = **27 generation-runs** |
| `a1c_s{0,1,2}` / `a1t_s{0,1,2}` | kS capacity throttle, control vs treatment | 2 arms × 3 seeds × 1 gen = **6** |
| `mf{050…100}_{c,t}_s{0,1,2}` | `aa_kcats_fwd` ladder, two arms, 6 rungs | 6 × 2 × 3 = **36** |
| `st_f{003,010,030,050,060,070,080,090,100}` | `aa_kcats_fwd` ladder, single arm, 9 rungs | **9** (n=1 seed per rung) |
| `ab_{on,off}_s{0,1,2}_{ctl,trt}` | ppGpp arm isolation | 2 × 3 × 2 = **12** |
| `route1_ppgpp_{on,off}` | ppGpp on/off | **2** (both duplicates — §6) |
| `km_parca`, `km_s1`, `km_s2` | K_M campaign baseline | **3** |
| `s5_*`, `s7_*`, `adv_*` | staged resolution probes (21–41 steps) | **10** |
| `iso_smoke_*`, `smoke_*` | smoke tests (20–21 steps) | **5** |
| `pf_f060_{ctl,trt}` | paired probe at rung 0.60 | **2** |

Read status: **102 of 103** runs read cleanly. `smoke_bad_value` is `ALL_UNREADABLE` — it is the
deliberate bad-input smoke test (`trna_demand_split: "nonsense"`, MEASURED from its metadata), so an
unreadable output is its expected result, not a lost measurement.

**Interval convention.** Where a mean ± spread is given below, the spread is the sample standard deviation
over the **seeds** named in the row, and n is stated. No interval is reported at n < 2, and no interval
below n = 3 is used to support a claim.

---

## 3. The central ROUTE1 question: does isoacceptor resolution change the outcome?

### 3a. The degeneracy IS broken by the build (SIMULATED, decisive)

`GrowthLimits/fraction_trna_charged` is 86 columns wide in every run. Counting **distinct values in the
last timestep**, and the **maximum within-family spread** across all 86 species:

| arm | distinct values (of 86) | max within-family spread |
|---|---|---|
| `*_fam_*` (family resolution), all 6 runs | **21, exactly** | **0.0, exactly** |
| `mx_abu_*` | 80, 84, 82 | 3.4e-2 … 4.9e-2 |
| `mx_equ_*` | 85, 85, 86 | 8.5e-2 … 9.3e-2 |
| `km3_abu_*` | 73, 85, 85 | 8.1e-2 … 9.8e-2 |
| `km3_equ_*` | 84, 86, 86 | **0.537 … 0.553** (carried by `gly`) |

This reproduces, from the ROUTE1 side, the claim `src/cellarium/trna.py:18` makes about the shipped
steady-state model — that the 86-wide vector carries only 21 distinct values — and shows that the ROUTE1
build is what removes it. **The capability is real.** Whether it *matters* is 3b.

### 3b. It does not survive the seed spread — and the direction reverses (SIMULATED + ALGEBRAIC)

Growth rate, least-squares slope of ln(cellMass) vs time, per generation, 3 seeds × 3 generations = **n=9
generation-runs per arm**:

| arm | `mx` mean ± sd (n=9) | `km3` mean ± sd (n=9) |
|---|---|---|
| family / abundance | **0.9101 ± 0.0672** /hr | **0.7713 ± 0.1262** /hr |
| isoacceptor / abundance | **0.8377 ± 0.0901** /hr | **0.8327 ± 0.0697** /hr |
| isoacceptor / equal | **0.8436 ± 0.0788** /hr | **0.8246 ± 0.1285** /hr |

Two things kill the effect, and they are independent:

1. **The direction reverses between the two campaigns.** In `mx`, family resolution is **faster** than
   isoacceptor by 0.072 /hr. In `km3` — same three arms, same seeds, same generation count, only the K_M
   parameterisation differs — family is **slower** by 0.061 /hr. A sign flip under a parameter change the
   hypothesis does not mention.
2. **The within-arm spread equals or exceeds every between-arm gap.** Largest between-arm gap: 0.072 /hr
   (`mx`). Within-arm sd: 0.067–0.129. Individual generation-runs inside one arm span 0.8226–1.0215
   (`mx` family) and 0.5974–0.9615 (`km3` family) — ranges of 0.20 and 0.36, three to five times the
   effect being claimed.

   *Caveat, stated because it cuts against the tidiness of n=9:* the nine values per arm are **3 seeds ×
   3 generations of the same lineage** and are not independent. Pooling them inflates n. Restricting to
   generation 0 (3 independent seeds) does not rescue the effect — it shrinks n and leaves the sign flip
   intact.
3. **The split carries the difference, not the information in it.** `isoacceptor/equal` — a split with
   **no** abundance information — sits within 0.006 /hr (`mx`) and 0.008 /hr (`km3`) of
   `isoacceptor/abundance`. Whatever moves when resolution changes is not the abundance information the
   finer resolution is supposed to supply.

### 3c. Per family, because the aggregate hides the shape (SIMULATED)

Uncharged fraction, last-quarter mean of generation 0, mean ± sd over seeds 0–2 (**n=3**). All 21
amino-acid families, both campaigns, and the isoacceptor-minus-family difference:

| family | `mx` fam/abu | `mx` iso/abu | Δ | `km3` fam/abu | `km3` iso/abu | Δ |
|---|---|---|---|---|---|---|
| ala | 0.09396 ± 0.05413 | 0.06615 ± 0.00292 | −0.02781 | 0.08692 ± 0.01201 | 0.06394 ± 0.00360 | −0.02298 |
| arg | 0.02069 ± 0.00804 | 0.01748 ± 0.00062 | −0.00321 | 0.01720 ± 0.00135 | 0.01950 ± 0.00351 | **+0.00230** |
| asn | 0.00773 ± 0.00098 | 0.00747 ± 0.00077 | −0.00026 | 0.07812 ± 0.01960 | 0.07210 ± 0.01310 | −0.00602 |
| asp | 0.02445 ± 0.00482 | 0.02346 ± 0.00495 | −0.00099 | 0.02343 ± 0.00120 | 0.02330 ± 0.00235 | −0.00013 |
| cys | 0.01770 ± 0.00398 | 0.01584 ± 0.00298 | −0.00186 | 0.01745 ± 0.00714 | 0.01285 ± 0.00378 | −0.00459 |
| gln | 0.00210 ± 0.00051 | 0.00143 ± 0.00006 | −0.00067 | 0.00141 ± 0.00036 | 0.00180 ± 0.00058 | **+0.00039** |
| glt | 0.00085 ± 0.00020 | 0.00082 ± 0.00012 | −0.00003 | 0.00492 ± 0.00091 | 0.00531 ± 0.00022 | **+0.00038** |
| gly | 0.05934 ± 0.00683 | 0.03822 ± 0.00288 | −0.02112 | 0.43864 ± 0.03649 | 0.38547 ± 0.02159 | −0.05318 |
| his | 0.03827 ± 0.01462 | 0.03113 ± 0.00247 | −0.00714 | 0.02417 ± 0.00372 | 0.02159 ± 0.00097 | −0.00259 |
| ile | 0.02468 ± 0.00527 | 0.03194 ± 0.01162 | +0.00726 | 0.02323 ± 0.00276 | 0.02722 ± 0.00511 | +0.00399 |
| leu | 0.01630 ± 0.00228 | 0.01783 ± 0.00191 | +0.00154 | 0.01932 ± 0.00280 | 0.01877 ± 0.00124 | **−0.00055** |
| lys | 0.02802 ± 0.01003 | 0.02734 ± 0.00088 | −0.00068 | 0.02695 ± 0.00321 | 0.02761 ± 0.00402 | **+0.00065** |
| met | 0.00718 ± 0.00331 | 0.00675 ± 0.00139 | −0.00043 | 0.00525 ± 0.00128 | 0.00517 ± 0.00053 | −0.00007 |
| phe | 0.14149 ± 0.05828 | 0.13079 ± 0.02185 | −0.01070 | 0.12395 ± 0.00773 | 0.11404 ± 0.02628 | −0.00991 |
| pro | 0.02340 ± 0.00442 | 0.02125 ± 0.00375 | −0.00215 | 0.29988 ± 0.05511 | 0.27580 ± 0.02556 | −0.02408 |
| sel | 0.05346 ± 0.00741 | 0.05868 ± 0.00262 | +0.00522 | 0.08909 ± 0.01282 | 0.08865 ± 0.00760 | **−0.00044** |
| ser | 0.00609 ± 0.00099 | 0.00534 ± 0.00092 | −0.00075 | 0.00553 ± 0.00022 | 0.00528 ± 0.00033 | −0.00025 |
| thr | 0.00578 ± 0.00058 | 0.00598 ± 0.00024 | +0.00020 | 0.00414 ± 0.00044 | 0.00445 ± 0.00087 | +0.00031 |
| trp | 0.53293 ± **0.32448** | 0.70898 ± 0.06612 | +0.17606 | 0.41195 ± **0.33471** | 0.55614 ± 0.18700 | +0.14418 |
| tyr | 0.01818 ± 0.00463 | 0.01536 ± 0.00234 | −0.00282 | 0.16741 ± 0.05028 | 0.13101 ± 0.03231 | −0.03640 |
| val | 0.00009 ± 0.00003 | 0.00007 ± 0.00001 | −0.00002 | 0.00189 ± 0.00016 | 0.00163 ± 0.00027 | −0.00026 |

Reading it per family rather than in aggregate changes what can be said:

- The **largest** single Δ in both campaigns is `trp` (+0.176 `mx`, +0.144 `km3`) — and `trp`'s control
  arm has a seed sd of **0.32–0.33**, roughly **twice** the difference it is supposedly showing. The one
  family that would carry a headline is the one family whose baseline is not reproducible across seeds.
- Excluding `trp`, every remaining Δ is ≤ 0.053 and 15 of 20 (`mx`) are negative — the opposite sign to
  `trp`. An aggregate mean over families would be a tug-of-war decided by `trp`'s noise.
- Six families **flip sign between the two campaigns** (`arg`, `gln`, `glt`, `leu`, `lys`, `sel`), which
  is the per-family shadow of the growth-rate reversal in 3b.

**CONCLUSION (SIMULATED, and this is the dead end).** The ROUTE1 build demonstrably delivers per-isoacceptor
resolution (3a). At the resolutions and seeds run, that resolution does not produce an effect on growth
rate or on per-family charging that is separable from seed variation, and its apparent sign depends on a
K_M choice the hypothesis does not constrain.

---

## 4. Interventions that DID move the model

These are recorded because they are the useful residue: they show the runs were not insensitive, so §3's
null is a null about *resolution*, not about the whole setup.

### 4a. kS capacity throttle (A1), n=3 seeds, per family (SIMULATED)

The `a1t` arm divides `constants.synthetase_charging_rate` (kS) by a scalar; the `a1c` control is a byte
copy of the source kb (CODE-READ, `out/_ks_throttle.py`). Aggregate effect, per seed:

| seed | µ ctl → trt (/hr) | change | elong q4 (aa/s) | ppGpp q4 (µM) | change |
|---|---|---|---|---|---|
| 0 | 0.9067 → 0.6603 | **−27.2 %** | 16.365 → 10.953 | 65.92 → 120.93 | **+83.5 %** |
| 1 | 0.9615 → 0.6582 | **−31.5 %** | 16.668 → 12.081 | 61.56 → 106.94 | **+73.7 %** |
| 2 | 0.8096 → 0.5842 | **−27.8 %** | 15.176 → 10.247 | 74.35 → 129.81 | **+74.6 %** |

Consistent in sign and rough magnitude across all three seeds; the change is an order of magnitude larger
than the seed spread. Per family (uncharged fraction, mean ± sd over 3 seeds):

| family | ctl | trt | Δ | | family | ctl | trt | Δ |
|---|---|---|---|---|---|---|---|---|
| ala | 0.08692 ± 0.01201 | 0.15228 ± 0.01527 | +0.06537 | | lys | 0.02695 ± 0.00321 | 0.04354 ± 0.00148 | +0.01659 |
| arg | 0.01720 ± 0.00135 | 0.02558 ± 0.00661 | +0.00838 | | met | 0.00525 ± 0.00128 | 0.00563 ± 0.00056 | +0.00039 |
| asn | 0.07812 ± 0.01960 | 0.12194 ± 0.01710 | +0.04382 | | phe | 0.12395 ± 0.00773 | 0.15846 ± 0.02555 | +0.03451 |
| asp | 0.02343 ± 0.00120 | 0.04207 ± 0.01284 | +0.01863 | | pro | 0.29988 ± 0.05511 | 0.38834 ± 0.01224 | +0.08846 |
| cys | 0.01745 ± 0.00714 | 0.01899 ± 0.00400 | +0.00154 | | sel | 0.08909 ± 0.01282 | 0.10817 ± 0.00376 | +0.01909 |
| gln | 0.00141 ± 0.00036 | 0.00282 ± 0.00057 | +0.00141 | | ser | 0.00553 ± 0.00022 | 0.00931 ± 0.00035 | +0.00378 |
| glt | 0.00492 ± 0.00091 | 0.00787 ± 0.00104 | +0.00294 | | thr | 0.00414 ± 0.00044 | 0.00697 ± 0.00079 | +0.00283 |
| gly | 0.43864 ± 0.03649 | 0.78549 ± 0.02043 | **+0.34684** | | trp | 0.41195 ± **0.33471** | 0.02094 ± 0.00478 | **−0.39102** |
| his | 0.02417 ± 0.00372 | 0.03932 ± 0.00504 | +0.01515 | | tyr | 0.16741 ± 0.05028 | 0.25665 ± 0.03929 | +0.08924 |
| ile | 0.02323 ± 0.00276 | 0.04556 ± 0.00881 | +0.02233 | | val | 0.00189 ± 0.00016 | 0.00288 ± 0.00017 | +0.00099 |
| leu | 0.01932 ± 0.00280 | 0.02883 ± 0.00703 | +0.00950 | | | | | |

**20 of 21 families de-charge further under the throttle; `trp` alone moves the other way, by more than
any family moves in the expected direction.** Its control sd (0.335) is larger than its own control mean
(0.412) — the control is not reproducible across seeds, so the `trp` reversal is not usable as evidence
either way and is reported, not explained.

### 4b. The `aa_kcats_fwd` starvation ladder — the limiting family switches (SIMULATED)

`st_f<NNN>` scales the whole `aa_kcats_fwd` vector by 0.03 … 1.00 (CODE-READ, `out/_aa_kcat_throttle.py`;
the vector multiplies the synthesis rate linearly, and with `mechanistic_translation_supply` on and media
`0 minimal` it is the only amino-acid source the charging ODE sees). **n = 1 seed per rung.**

Uncharged fraction, last-quarter mean, all 21 families × 9 rungs:

| family | f0.03 | f0.10 | f0.30 | f0.50 | f0.60 | f0.70 | f0.80 | f0.90 | f1.00 |
|---|---|---|---|---|---|---|---|---|---|
| ala | **0.8129** | 0.0880 | 0.0249 | 0.0231 | 0.0263 | 0.0367 | 0.0655 | 0.0610 | 0.0586 |
| arg | 0.0067 | 0.0003 | 0.0005 | 0.0018 | 0.0028 | 0.0050 | 0.0089 | 0.0139 | 0.0162 |
| asn | 0.0016 | 0.0001 | 0.0004 | 0.0011 | 0.0017 | 0.0030 | 0.0054 | 0.0064 | 0.0080 |
| asp | **0.5615** | 0.0032 | 0.0014 | 0.0028 | 0.0040 | 0.0069 | 0.0126 | 0.0176 | 0.0232 |
| cys | 0.1776 | 0.0023 | 0.0011 | 0.0025 | 0.0038 | 0.0059 | 0.0109 | 0.0148 | 0.0151 |
| gln | 0.0003 | 0.0000 | 0.0001 | 0.0002 | 0.0003 | 0.0005 | 0.0009 | 0.0013 | 0.0016 |
| glt | 0.0003 | 0.0000 | 0.0000 | 0.0001 | 0.0002 | 0.0003 | 0.0005 | 0.0007 | 0.0008 |
| gly | **1.0000** | **0.9978** | 0.0130 | 0.0124 | 0.0154 | 0.0218 | 0.0341 | 0.0451 | 0.0434 |
| his | 0.0055 | 0.0004 | 0.0010 | 0.0032 | 0.0054 | 0.0092 | 0.0173 | 0.0244 | 0.0293 |
| ile | 0.2211 | 0.0015 | 0.0011 | 0.0034 | 0.0055 | 0.0094 | 0.0183 | 0.0222 | 0.0288 |
| leu | 0.0108 | 0.0017 | 0.0045 | **0.9824** | **0.9724** | **0.9485** | **0.8867** | 0.0140 | 0.0156 |
| lys | 0.0079 | 0.0004 | 0.0010 | 0.0032 | 0.0052 | 0.0089 | 0.0157 | 0.0224 | 0.0261 |
| met | 0.4130 | 0.0135 | **0.9978** | 0.0073 | 0.0030 | 0.0033 | 0.0086 | 0.0074 | 0.0053 |
| phe | **0.6455** | 0.0169 | 0.0156 | 0.0186 | 0.0241 | 0.0403 | 0.0707 | 0.0751 | 0.0806 |
| pro | 0.0032 | 0.0003 | 0.0008 | 0.0028 | 0.0048 | 0.0087 | 0.0182 | 0.0191 | 0.0188 |
| sel | 0.2167 | 0.0570 | 0.0534 | 0.0535 | 0.0542 | 0.0562 | 0.0601 | 0.0554 | 0.0540 |
| ser | 0.4605 | 0.0010 | 0.0005 | 0.0009 | 0.0014 | 0.0023 | 0.0039 | 0.0048 | 0.0058 |
| thr | 0.0011 | 0.0001 | 0.0002 | 0.0006 | 0.0011 | 0.0018 | 0.0032 | 0.0041 | 0.0052 |
| trp | 0.0040 | 0.0133 | 0.0036 | 0.0022 | 0.0035 | 0.0058 | 0.0120 | **0.7435** | **0.6827** |
| tyr | 0.0015 | 0.0002 | 0.0006 | 0.0017 | 0.0029 | 0.0049 | 0.0086 | 0.0101 | 0.0150 |
| val | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0001 |

**This is the single most important thing in the record, and it is invisible in aggregate.** The throttle
does not set the *depth* of one family's starvation; it selects **which family becomes the binding
constraint**, and that identity changes four times down the ladder:

- **f = 0.03** — global collapse. Six families above 0.4 simultaneously (`gly` 1.000, `ala` 0.813, `phe`
  0.646, `asp` 0.562, `ser` 0.461, `met` 0.413).
- **f = 0.10** — `gly` alone (0.998).
- **f = 0.30** — `met` alone (0.998); `gly` has fallen back to 0.013.
- **f = 0.50 – 0.80** — `leu` alone (0.982 → 0.887).
- **f = 0.90 – 1.00** — `trp` alone (0.744, 0.683), and `leu` has fallen back to 0.014.

A single "mean uncharged fraction vs throttle" curve would be a smooth-ish line through all of this and
would state, falsely, that the throttle deepens one starvation. It does not: it walks the bottleneck
across the amino acids.

**Degeneracy and stability guards (ALGEBRAIC).** Total variation of each family's series is recorded so a
pinned constant cannot be mistaken for a response. `val` is 0.0000 at every rung with TV ≈ 1.000 — pinned,
not measured. At f = 0.03 the TVs are 10–45 (`ala` 45.2, `phe` 35.6, `asp` 33.2, `ser` 30.8): that rung is
**oscillating, not settled**, and its numbers should not be read as a steady state. Its aggregate growth
rate (0.2023 /hr) is also **higher** than f = 0.10 (0.1121 /hr) — the ladder is **non-monotone at the
bottom**, which is a further reason to treat f = 0.03 as an artefact rather than the deepest starvation.

Aggregate growth rate down the ladder (n = 1 each): 0.2023 · 0.1121 · 0.1403 · 0.1953 · 0.2436 · 0.3219 ·
0.4376 · 0.6046 · 0.8457 /hr. Monotone from f = 0.10 upward.

### 4c. The two-arm `mf` ladder — no separable arm effect (SIMULATED)

Six rungs × two arms × 3 seeds. Paired treatment-minus-control growth-rate difference, and the same
difference expressed against the control's own seed spread:

| rung | µ ctl (n=3) | µ trt (n=3) | paired Δ mean ± sd | per-seed Δ | \|Δ\| / sd(ctl) |
|---|---|---|---|---|---|
| 0.50 | 0.19015 ± 0.00207 | 0.18994 ± 0.00387 | −0.00020 ± 0.00249 | +0.00263, −0.00120, −0.00205 | 0.10 |
| 0.60 | 0.24374 ± 0.00501 | 0.24257 ± 0.00293 | −0.00117 ± 0.00210 | −0.00294, −0.00172, +0.00115 | 0.23 |
| 0.70 | 0.32084 ± 0.00234 | 0.31745 ± 0.00400 | −0.00338 ± 0.00166 | −0.00207, −0.00284, −0.00525 | 1.44 |
| 0.80 | 0.44380 ± 0.00714 | 0.44122 ± 0.00852 | −0.00258 ± 0.01509 | +0.00485, +0.00735, −0.01994 | 0.36 |
| 0.90 | 0.61231 ± 0.00709 | 0.61179 ± 0.01175 | −0.00052 ± 0.01880 | +0.00665, +0.01364, −0.02184 | 0.07 |
| 1.00 | 0.76807 ± 0.01166 | 0.76562 ± 0.01599 | −0.00245 ± 0.00613 | −0.00028, +0.00231, −0.00937 | 0.21 |

The sign of the per-seed difference is **inconsistent at four of six rungs**. Only rung 0.70 has all three
seeds agreeing in sign, and even there |Δ| is 0.0034 /hr.

**What the two arms are is NOT established from disk.** MEASURED: the paired directories share a
**byte-identical knowledge base** (e.g. `mf060_c_s0` and `mf060_t_s0` both hash `3a58ea27…`) and the same
seed, yet **37 of 40 `GrowthLimits` columns differ** — so the intervention is code-side, in the model
overlay, not in the kb. The arm's identity lives in the extension repo's ROUTE1 decision log. Recording
"the two arms differ code-side" is what the disk supports; naming the switch would be ARGUED.

### 4d. ppGpp arm isolation (SIMULATED)

| run pair | Δ µ (/hr) | Δ ppGpp q4 (µM) |
|---|---|---|
| `ab_on_s0` | −2.397e−03 | +6.07e−02 |
| `ab_on_s1` | **0.000e+00 (bitwise identical)** | **0.000e+00** |
| `ab_on_s2` | −3.702e−04 | −1.08e−02 |
| `ab_off_s0` | +4.749e−03 | +4.429e+00 |
| `ab_off_s1` | −1.904e−03 | −2.17e−01 |
| `ab_off_s2` | −3.439e−04 | −2.80e−01 |

With the ppGpp arm **on**, control and treatment are indistinguishable — at seed 1 the two runs are
bitwise identical across `fraction_trna_charged`, `cellMass` and `ppgpp_conc` for the entire generation.
With the arm **off**, seed 0 shows a 4.4 µM ppGpp difference while seeds 1 and 2 show −0.22 and −0.28 —
inconsistent in sign, so n=3 does not support an off-arm effect either.

Separately, the ppGpp arm itself is a **large** effect (`route1_ppgpp_on` vs `route1_ppgpp_off`, n=1,
120 s): elongation 20.048 vs 15.730 aa/s, ppGpp 32.26 vs 70.61 µM. The arm matters; the ctl/trt switch
inside it does not.

---

## 5. Aggregate per-run table

The full 102-run table (steps, duration, growth rate, mass fold, elongation, ppGpp, distinct charged
values, per-family uncharged fraction and total variation for every family and every generation) is
reproducible from the runs while they exist, and the headline columns are:

| campaign | steps | µ (/hr) range across the campaign | elong q4 (aa/s) range | ppGpp q4 (µM) range |
|---|---|---|---|---|
| `mx_*` (9 runs, 3 gens) | 2529–3310 | 0.6714 – 1.0215 | 14.70 – 19.20 | 41.1 – 80.4 |
| `km3_*` (9 runs, 3 gens) | 2529–3310 | 0.5974 – 0.9970 | 15.18 – 16.67 | 61.6 – 74.8 |
| `a1c_*` / `a1t_*` (6) | 2529–3310 | 0.5842 – 0.9615 | 10.25 – 16.67 | 61.6 – 129.8 |
| `mf*` (36) | 601 | 0.1858 – 0.7837 | 2.49 – 18.13 | 49.0 – 361.5 |
| `st_f*` (9) | 601 | 0.1121 – 0.8457 | 0.001 – 16.33 | 64.0 – 621.1 |
| `ab_*` (12) | 121 | 0.7160 – 0.9474 | 15.73 – 20.10 | 31.7 – 70.6 |
| `s5_*`/`s7_*`/`adv_*`/smokes (15) | 21–41 | 0.2382 – 0.5928 | 18.61 – 19.07 | 41.4 – 45.5 |
| `km_parca`/`km_s*` (3) | 1801 | 0.8737 – 0.9283 | 16.43 – 17.83 | 52.1 – 65.1 |

The `s5`/`s7`/`adv`/smoke runs are 20–41 timesteps — **too short to support a growth-rate claim**; their
"µ" is a slope over less than a minute of simulated time and is recorded for completeness only.

---

## 6. Duplicates within the candidate set (MEASURED)

Grouping every run by the md5 of `GrowthLimits/fraction_trna_charged` + `Mass/cellMass` +
`GrowthLimits/ppgpp_conc` over generation 0: **94 distinct signatures across 103 runs.** The nine
collisions:

| group | members | note |
|---|---|---|
| `d609dcab…` / `4666e20c…` / `db8e1aac…` | `a1c_s{0,1,2}` ≡ `km3_fam_s{0,1,2}` | the A1 control arm reproduces the `km3` family baseline **bitwise** — which is exactly what `out/_a1_ctlcheck.sh` was written to assert, independently reproduced here |
| `8af3d89b…` | `ab_off_s0_trt` ≡ `route1_ppgpp_off` | same run, two names |
| `c30587517…` | `ab_on_s0_trt` ≡ `route1_ppgpp_on` | same run, two names |
| `ae12a936…` | `pf_f060_trt` ≡ `st_f060` | same run, two names |
| `db4c44ea…` | `s5_base_family` ≡ `s5_family_ctl` | same run, two names |
| `6a1fded…` | `smoke_defaults` ≡ `smoke_equal_split` | **the "equal split" smoke test produced output identical to the default** — at 21 timesteps the split had not yet diverged |
| `49999f8f…` | `ab_on_s1_ctl` ≡ `ab_on_s1_trt` | **a control and its treatment are bitwise identical** (see §4d) |

Effective independent runs: **94**, not 103.

---

## 7. What was deleted — exact list and size

**DELETED 2026-08-03.** All paths were under `C:/dev/wcEcoli/out/`. The table below is the candidate
list as measured *before* deletion; the reconciliation against what was actually removed follows it.

| group | entries | GB | files |
|---|---|---|---|
| `mx_*` resolution × split, gens=3 | 9 | 21.166 | 8 235 |
| `km3_*` resolution × split, gens=3 | 9 | 21.648 | 8 235 |
| `mf*` `aa_kcats_fwd` ladder, two arms | 36 | 11.650 | 11 052 |
| `a1c_*` / `a1t_*` kS capacity throttle | 6 | 5.440 | 1 866 |
| `st_f*` `aa_kcats_fwd` ladder, single arm | 9 | 2.920 | 2 763 |
| `ab_on_*` / `ab_off_*` ppGpp arm isolation | 12 | 2.636 | 3 680 |
| `s5_*` / `s7_*` / `adv_*` staged probes | 10 | 2.199 | 4 002 |
| `km_parca`, `km_s1`, `km_s2` | 3 | 1.936 | 933 |
| `iso_smoke_*` / `smoke_*` | 5 | 1.073 | 1 243 |
| `pf_f060_ctl`, `pf_f060_trt` | 2 | 0.653 | 614 |
| `route1_ppgpp_on`, `route1_ppgpp_off` | 2 | 0.431 | 614 |
| support artifacts: `sk_f050`…`sk_f100`, `_a1kb_thr`, `_r1s_npz` | 8 | 0.659 | 43 |
| loose analysis scripts at `out/` root (17 files) | 17 | 0.00008 | 17 |
| **TOTAL** | **128** | **72.411** | **43 297** |

Full run list (103): `a1c_s0 a1c_s1 a1c_s2 a1t_s0 a1t_s1 a1t_s2 ab_off_s0_ctl ab_off_s0_trt ab_off_s1_ctl
ab_off_s1_trt ab_off_s2_ctl ab_off_s2_trt ab_on_s0_ctl ab_on_s0_trt ab_on_s1_ctl ab_on_s1_trt ab_on_s2_ctl
ab_on_s2_trt adv_family_s1 adv_iso_abund_s1 adv_iso_equal_s1 iso_smoke_abundance iso_smoke_equal
km3_abu_s0 km3_abu_s1 km3_abu_s2 km3_equ_s0 km3_equ_s1 km3_equ_s2 km3_fam_s0 km3_fam_s1 km3_fam_s2
km_parca km_s1 km_s2 mf050_c_s0 mf050_c_s1 mf050_c_s2 mf050_t_s0 mf050_t_s1 mf050_t_s2 mf060_c_s0
mf060_c_s1 mf060_c_s2 mf060_t_s0 mf060_t_s1 mf060_t_s2 mf070_c_s0 mf070_c_s1 mf070_c_s2 mf070_t_s0
mf070_t_s1 mf070_t_s2 mf080_c_s0 mf080_c_s1 mf080_c_s2 mf080_t_s0 mf080_t_s1 mf080_t_s2 mf090_c_s0
mf090_c_s1 mf090_c_s2 mf090_t_s0 mf090_t_s1 mf090_t_s2 mf100_c_s0 mf100_c_s1 mf100_c_s2 mf100_t_s0
mf100_t_s1 mf100_t_s2 mx_abu_s0 mx_abu_s1 mx_abu_s2 mx_equ_s0 mx_equ_s1 mx_equ_s2 mx_fam_s0 mx_fam_s1
mx_fam_s2 pf_f060_ctl pf_f060_trt route1_ppgpp_off route1_ppgpp_on s5_base_family s5_family_ctl
s5_iso_abundance s5_iso_equal s7_abu_s0 s7_equ_s0 s7_fam_s0 smoke_bad_value smoke_defaults
smoke_equal_split st_f003 st_f010 st_f030 st_f050 st_f060 st_f070 st_f080 st_f090 st_f100`

Support artifacts (8): `sk_f050 sk_f060 sk_f070 sk_f080 sk_f090 sk_f100 _a1kb_thr _r1s_npz`

Loose scripts (17): `_a1_ctlcheck.sh _a1_readout.json _a1_readout.py _a2_kcat_check.py _aa_kcat_throttle.py
_ab_analysis.py _ab_analysis_off_s1.py _ks_throttle.py _r1s_extract.py _r1s_params.py _r1s_relaparams.npz
_starve_families.py _starve_readout.py ab_analyze.py ab_analyze_off_s2.py ab_analyze_route1.py ab_verify.py`

### Explicitly NOT candidates

- **Protected by instruction** (2.624 GB): `kinetic_parca`, `operonsON_kin_probe`, `operons_off_parca`.
  No `multi_gene_knockout_*` directory exists under `C:/dev/wcEcoli/out` (it is under
  `runs/cellarium`, untouched).
- **Held pending a decision** (5.665 GB): `refit_none`, `refit2_none`, `refit_A055w3`, `refit_shipped`,
  `kinetic_parca_operons_off` — see §1.
- Everything under `<repo>/runs`, which contains no ROUTE1 run directory.

**All nine survived, verified by name after the deletion (MEASURED).** `C:/dev/wcEcoli/out` now holds
exactly `kinetic_parca`, `operonsON_kin_probe`, `operons_off_parca`, `kinetic_parca_operons_off`,
`refit_none`, `refit2_none`, `refit_A055w3`, `refit_shipped` and `_r1s_npz` — nothing else.
`runs/cellarium` still holds its 52 entries. The five held-back directories remain **NEEDS-DECISION**:
they were not deleted and no decision about them has been made here.

### Execution, and its reconciliation (MEASURED)

**Re-verification before deleting, independent of this document.** The deletion script did not read the
list above. It re-walked `C:/dev/wcEcoli/out` and re-derived the 103 ROUTE1 directories from each run's
own `metadata/metadata.json`, and it aborted rather than deleted if that count was not exactly 103, if
the target list was not exactly 127 entries, or if any protected name appeared in it. The three
metadata-less groups were re-confirmed by kb md5 in a separate pass, reproducing §1 exactly:
`sk_f050`…`sk_f090` each hash equal to exactly their six `mf<rung>_*` runs; `sk_f100` hashes equal to the
untouched `km_parca` kb (shared with 21 ROUTE1 runs and **no** protected directory); `_a1kb_thr` hashes
equal to `a1t_s{0,1,2}` **and nothing else**. `_r1s_npz` holds exactly the 36 `mf*.npz` and no
`simData.cPickle` — the `mf`-ladder extraction, as §1 states.

**Result: 127 of 128 deleted, 0 failures.** MEASURED at deletion time: **72.385 GB, 43 261 files**.
Each entry was re-checked for existence after its own removal; an entry still present would have been
counted a failure, and none were. `C:/dev/wcEcoli/out` went from 136 entries / 80.700 GB / 49 407 files
to **9 entries / 8.315 GB / 6 146 files** — an independent confirmation of the same 72.385 GB.

The 72.385 GB deleted differs from the 72.411 GB estimated above by **0.026 GB**: that is `_r1s_npz`,
which was retained (below). The two preservation actions §7 called for were both carried out:

1. **The 17 loose scripts were copied into this repository** at `archive/route1_analysis_scripts/`
   (109 KB with its README), and **all 17 were verified byte-identical by md5 to their originals before
   the originals were deleted**. They are what make these numbers reproducible — `_aa_kcat_throttle.py`
   and `_ks_throttle.py` *define* the interventions §4a/§4b report, `_r1s_extract.py` defines the derived
   quantities. Preserved and committed (`a32c590`) *before* the deletion ran, not after.
2. **`_r1s_npz` was NOT deleted.** It survives in place at `C:/dev/wcEcoli/out/_r1s_npz` (25 MB, 36
   files) — the only per-timestep record of the `mf` ladder that still exists.

**A distinct knowledge base that did NOT survive.** §1 established that 2 of the 14 distinct kb pickles
are the retained reference kbs. The other 12 were ROUTE1-specific and went with the runs — including
`afb48d8c…`, the `km_parca` K_M-modified kb, which was present only in ROUTE1 directories. Regenerating
it requires re-running the extension repo's ParCa. Stated so a later reader does not assume every kb
referenced above is still openable.

**Free-space accounting, honestly.** Disk free on `C:` went **79.172 GB → 138.099 GB (+58.927)**, which
is **13.458 GB less than the 72.385 GB removed**. That gap is *not* explained by the usual causes: 0
files in `out/` carry `nlink > 1`, and 0 of a 200-file sample carry the NTFS `Compressed` or `SparseFile`
attribute. Volume Shadow Copy retention is the remaining candidate and **could not be checked** —
`vssadmin list shadowstorage` exits 2, "You don't have the correct permissions", and this shell is not
elevated. Concurrent writes elsewhere on `C:` during the 31 s deletion window are also possible. **The
cause is UNKNOWN**; it is recorded as unknown rather than attributed. The bytes-removed figure does not
depend on it — it is corroborated by the `out/` before/after walk above.

---

## 8. Manifest and tombstone impact: none

MEASURED, over all **322** manifest rows in `data/manifest/*.parquet` (raw rows, not the deduped view, so
this is the superset):

- Rows whose `simout_path` references any of the 128 deletion candidates: **0**.
- Rows whose `simout_path` resolves under `C:/dev/wcEcoli/out`: **0**. Every row points into
  `runs/cellarium` (279) or `runs/aadrop` (39).
- Existing tombstones: **0**. `data/manifest/dropped.json` does not exist; `docs/CORPUS_LEDGER.md` does
  not exist.

**Deleting the candidates orphans no manifest row, so `manifest.drop_run` is not required and must not be
invoked** — a tombstone for a run the manifest never indexed would create a record of a decision about
nothing. The tombstone mechanism (`src/cellarium/manifest.py:100` `drop_run`,
`tests/test_tombstone_prune.py`) stays unused here.

**Re-checked AFTER the deletion, not only before (MEASURED).** The same query over all 322 raw rows,
run once the 127 entries were gone: **0** rows resolve under `C:/dev/wcEcoli/out`, and **0** rows name
any of the 127 deleted entries in any path component. `data/manifest/dropped.json` still does not exist
and no tombstone was written. This is the check that matters — orphaning is a property of the state
*after* deletion, and predicting it beforehand is not the same as confirming it.

The only ROUTE1 trace anywhere in the manifest is textual: 12 rows carry the Docker command line in their
`note` column, which mentions `-v <repo>\runs:/wcEcoli/out`. That is the known
`note`-column path-disclosure issue, is about the *host path*, not about ROUTE1, and is unaffected by
deleting anything under `out/`.

**Pre-existing and unrelated, reported not acted on.** 165 of the 318 distinct `simout_path` values in the
manifest do not resolve to a live directory on this machine (39 under `runs/aadrop`, 126 under
`runs/cellarium`, the latter including a collaborator's `/Users/fmenol/...` paths). This condition exists
today, before any deletion, and is outside this task's scope.

---

## 9. Where the code lives

- **The extension repo** — `github.com/evanniko1/wcecoli-extension-tRNA-isoacceptors`: the `route1_*` /
  `trna_refit_*` / `km3_*` / `mx_*` scripts, the `test_ppgpp_arm_isolation` and
  `test_charging_clamp_commutation` regression nets, `docs/ROUTE1_{VERIFICATION,FINDINGS,WHAT_WE_LEARNED}.md`,
  and the full ROUTE1-1..101 decision log, with 438 commits of history. Recorded in `BACKLOG.md` under `EXT-ISO-1`.
- **In Cellarium** — the *port*, deliberately kept: `scripts/apply_trna_port.py` (plus
  `ext_port_10/11_patch.py`, `probe_relation.py`, `verify_trna_objective.py`,
  `smoke_trna_parca_step.py`), `vendor/v301/`, `tests/test_trna.py`, `tests/test_elongation_axis.py`.
  This is what makes `capability.ELONGATION_MODES`' `kinetic` and `coarse_kinetic` reproducible from a
  fresh clone.
- **In this repository, preserved** — the 17 loose analysis scripts listed in §7 now live at
  `archive/route1_analysis_scripts/` (commit `a32c590`), copied verbatim and md5-verified before their
  originals in `C:/dev/wcEcoli/out` were deleted. Whether they are *also* in the extension repo has
  **not** been checked from here — the remote is gone and no clone is present — which is exactly why
  they were treated as unique and copied.
- **The `extension` git remote has been removed** from `<repo>/.git/config`. It was the
  last live push target for the extension repo on this machine, and `git push --all` would have overwritten
  that repo with Cellarium's history. The URL survives as prose in `BACKLOG.md` (`EXT-ISO-1`),
  `docs/MODEL_EXTENSION.md:134`, `docs/OVERLAY.md:190`, `scripts/apply_trna_port.py:1007` and
  `scripts/build_model_overlay.py:19,507` — citations, not remotes. MEASURED: no branch tracked it and no
  tracked file referenced the remote *name*.

---

## 10. What this record does not capture

Stated so a later reader does not mistake this summary for the data:

- **Per-timestep dynamics.** Everything here is a last-quarter mean, a total variation, or a whole-run
  slope. Transients, oscillations and the shape of approach to steady state are lost, except for the `mf`
  ladder, which `_r1s_npz` preserves at full resolution if that file is kept.
- **Φ = v_rib(realized) / v_rib(rate law).** The quantity `_starve_readout.py` and `_r1s_extract.py` were
  built to measure, and the quantity the ROUTE1-21 claim turns on, is **not** recomputed here. It requires
  constants from `sim_data` (`K_rta`, `K_rtf`, `k_el^max`, `n_avogadro`, `cell_density`) that cannot be
  unpickled outside the model image on this host — `wholecell.utils.mc_complexation` is a compiled Cython
  module absent here. The precomputed Φ series for the 36 `mf` runs is inside `_r1s_npz`; for every other
  campaign it would need a container.
- **Anything at isoacceptor resolution below the family aggregate.** §3a reports how many distinct values
  exist and the maximum within-family spread; the per-isoacceptor trajectories themselves are not summarised.
- **The identity of the `mf` / `pf` two-arm switch** (§4c) and the `ab` ctl/trt switch — code-side, in the
  extension repo's decision log.
- **The seven EcoCyc-unnamed tRNAs** `RNA0-300[c]`…`RNA0-306[c]` carry no gene symbol. Under family
  resolution they were assigned by exact series identity against a named family (the steady-state model
  writes one value per family, so the match is bitwise or it is refused). Under **isoacceptor** resolution
  no exact match exists, so they are pooled as `UNMAPPED` and excluded from the 21 per-family rows in §3c.
  They are 7 of 86 species.

---

## 11. Method, so the numbers can be checked

- Runs read with wcEcoli's own `wholecell.io.tablereader.TableReader`, on Windows, no Docker, **no
  modification to `C:/dev/wcEcoli`**.
- Family map built from **each run's own** `GrowthLimits` attribute `uncharged_trna_ids`, collapsed by the
  three-letter tRNA gene prefix — the same convention Cellarium already uses at `src/cellarium/trna.py:69`.
  The run's `kb/simData.cPickle` was deliberately **not** used for this (see §10).
- Growth rate: least-squares slope of ln(`Mass/cellMass`) against `Main/time`, converted to /hr. Labelled
  ALGEBRAIC throughout — it is arithmetic on run output, not a channel the model writes.
- "Last quarter" = the final 25 % of timesteps of the generation.
- Total variation = Σ|Δ| of the per-timestep series, the degeneracy guard already used in
  `out/_starve_families.py` and `src/cellarium/trna.py`.
- A run whose tables could not be read is recorded as `READ_FAILED` with its exception, never as a zero and
  never as an absence. One run is in that state (`smoke_bad_value`, §2) and it is the expected outcome for
  that run.
