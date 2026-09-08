# The corpus knowledge base and a fresh ParCa are not the same model

The shipped corpus was fitted against knowledge base `3b2f8ebd2d6f`. Running the ParCa from the
current tree (`python -m cellarium.runner`, `docs/DOCKER_SETUP.md` §5) produces `e6219beb26df`. This
records what actually differs between them, because "the sha changed" is not a finding — a single
reordered dict does that — and because five tests fail once a fresh build is on disk, which reads as
breakage unless the divergence is characterised.

**The short answer: it is not drift.** 97.2% of the knowledge base is bit-identical. The rest is a
newer, deliberately corrected model plus a genuine re-fit of amino-acid metabolism. Rows from the two
builds are not poolable, which is exactly why `kb_sha256` sits in the arm key.

## How this was measured

Both `simData.cPickle` objects were unpickled inside the model container and compared leaf by leaf
over `__dict__` — not `dir()`, whose computed properties recalculate on access and never terminated.
The fresh build was written to an isolated `sim_path`, never `cellarium`, which live rows depend on.

| | shipped | rebuild |
|---|---|---|
| kb_sha256 | `3b2f8ebd2d6f…` | `e6219beb26df…` |
| simData.cPickle | 69,442,337 B | 90,404,578 B |
| leaves compared | 26,982 | 27,292 |

**26,226 of 26,981 shared leaves are identical.** The 755 that are not fall into three classes.

## 1. Structural — the corpus predates two deliberate changes

| Change | Scale |
|---|---|
| phnE1 retyped as a pseudogene: **4539 → 4538 cistrons**, **4310 → 4309 monomers** | 257 arrays change shape |
| amino-acid dropout media added (`minus_arg`, `minus_leu`, `minus_thr`, `minimal_aa_minus_*`) | **311 leaves exist only in the rebuild** |
| `molecule_ids.start_codon` added | 1 leaf |
| `relation.monomer_index_to_tu_indexes[4309]` gone | 1 leaf, the removed monomer |

These are corrections and additions made after the corpus was generated. A new user's ParCa is
therefore *ahead* of the corpus, not merely different from it.

## 2. Parametric — amino-acid metabolism genuinely moved

This is the part that matters scientifically, because amino-acid supply is the mechanism the tRNA
charging work depends on.

| Parameter | Moved | Largest shifts |
|---|---|---|
| `aa_kcats_fwd` | 21/21 | CYS 25,380 → 21,730 (−14%), SER 1,958 → 1,544 (−21%) |
| `aa_kcats_rev` | 20/21 | **THR 35.7 → 17.1 (−52%)**, SER 29,290 → 24,090 (−18%) |
| `import_kcats_per_aa` | 19/21 | MET 10,650 → 8,281 (−22%), ALA −14% |
| `export_kcats_per_aa` | 19/21 | ALA 238.9 → 211.0 (−12%) |
| `specific_import_rates` | 14/21 | ALA −11%, SER +5% |
| `rnapFractionActive[minimal_minus_phosphate]` | scalar | 0.2075 → 0.17 (−18%) |

That last row is the condition Known Limitations #4 names. The kcats are not mentioned there, and
they are the larger effect.

## 3. Negligible, and one re-indexing worth knowing about

RNA decay is a non-issue despite looking alarming at first: `Km_first_order_decay` differs in
3,375/3,375 cells with a maximum *relative* change of 22,699% — but that is near-zero denominators.
The honest summary is the distribution: **p50 0.004%, p90 0.006%, p99 0.009%**.

`rna_data['deg_rate']` is the same story for 99% of transcription units (p99 relative 0.012%), with
one exception that is not a re-fit at all. Three units **exchange** values:

| TU | cistrons | shipped | rebuild |
|---|---|---|---|
| `TU0-42514` | tnaC | 0.000127 /s (t½ 91 min) | 0.0289 /s (t½ 24 s) |
| `TU0-1283` | **fur** | 0.0289 /s (t½ 24 s) | 0.000127 /s (t½ 91 min) |
| `TU0-1281` | uof, **fur** | 0.000127 /s (t½ 91 min) | 0.00261 /s (t½ 4.4 min) |

`tnaC` and the fur-only unit swap rates outright — a consequence of the cistron removal shifting an
index, not of any parameter being re-estimated.

### The sentence this section used to end with was wrong, and it was wrong in the same way the paper is

It read: *"So **fur mRNA stability differs by 228× between the two builds**"*, and offered that as a
correction to `data/claims_audit.json` entry 40 — whose only fault, it said, was writing minutes as
seconds. **REPRO-2 re-measured it on 2026-09-08 and the 228× is not a statement about fur.**

`fur` (cistron `EG10359_RNA`) sits in **three** transcription units, and the one carrying the 228× holds
none of the gene's expression:

| TU | share of fur expression | shipped t½ | rebuild t½ |
|---|---|---|---|
| `TU0-1281[c]` | 45.4935% | 91.200 min | 4.427 min |
| `TU0-1282[c]` | 54.5065% | 2.744 min | 2.700 min |
| `TU0-1283[c]` | **0.0000%** (5.06e-20) | **0.400 min (24.00 s)** | **91.200 min** |

Weighting each unit by the expression it actually carries, fur's messenger half-life moves
**4.911 min → 3.282 min**: a **1.50×** change, and a change to a *shorter* half-life, not a longer one.
So "24 → 91" is wrong in its unit, wrong in its magnitude by two orders of magnitude, and wrong in its
**sign** — and quoting it as "24 s → 91 min, a 228-fold change" would fix the unit while making the
other two worse.

Two further facts, both measured rather than reasoned:

* **91.200 min is not a fitted half-life.** It is the estimator's floor — the minimum mRNA *cistron*
  degradation rate (`G0-10634_RNA`, shoB), 2.81× slower than the next-slowest of 847 — assigned to any
  TU whose NNLS coefficient returns zero. **245 of 3133** mRNA TUs sit bit-exactly on it in the shipped
  build and **244** in the rebuild; the half-life distribution runs p90 11.0 min then p95 = p99 = max =
  91.200. A TU "moving to 91 min" means it fell onto the floor.
* **`deg_rate` is not what the simulation runs on**, and it takes three fields to say what does.
  `rna_data['deg_rate']` reaches the running model at exactly one site (`rna_degradation.py:77-79`) and is
  consumed at exactly one (`:182`), where it feeds the `DiffRelativeFirstOrderDecay` **listener** —
  a diagnostic, nothing more. `rna_decay.Km_first_order_decay` is a ParCa *intermediate*
  (`fit_sim_data_1.py:3758`, `Km = capacity/k_deg − conc`) and is likewise never read at run time.
  What degradation is actually allocated on is **`rna_data['Km_endoRNase']`**
  (`rna_degradation.py:141-143`). All three track `1/k_deg` and all three carry the same 228× for
  `TU0-1283[c]` — `deg_rate` 2.888e-02 → 1.267e-04 /s, `Km_first_order_decay` 1.223e-05 → 2.789e-03,
  `Km_endoRNase` 1.176e-05 → 2.681e-03 mol/L — so the swing is real in the parameters either way.

  **And reading that code is not enough to know which field to edit — it gives the wrong answer.** From the
  above one would conclude `deg_rate` is inert in a fitted pickle and `Km_endoRNase` is the lever. Both
  halves are false, because the variant step re-derives Km from `deg_rate` before the simulation starts.
  Measured across four seeds: an arm setting `Km_first_order_decay` and an arm setting `Km_endoRNase` both
  came back **bit-identical** to an arm setting `deg_rate` alone (their edits are overwritten), while a
  round-trip with **nothing** changed came back bit-identical to the byte copy (the re-pickle is innocent).
  So `deg_rate` is the field to edit, and it took three arms and a null to establish that.

### What the swing costs a cell: measured, and smaller than the noise it makes

A one-parameter experiment, four seeds per arm, one generation: the shipped kb with **only** `deg_rate`
for `TU0-1283[c]` swapped to the rebuild value, against the shipped kb untouched.

| quantity | ctl | treated | ratio | worst per-seed deviation |
|---|---|---|---|---|
| `TU0-1283[c]` — **the perturbed unit** | 0.1219 | **0.0000** | — | consistent in 4/4 seeds |
| fur message total | 6.050 | 6.409 | 1.065× | 0.26 |
| Fur protein `PD00365[c]` | 406.2 | 307.8 | 0.865× | 0.45 |
| instantaneous growth rate | 2.513e-04 | 2.433e-04 | 0.969× | 0.06 |
| `TU0-1281[c]` — *parameters untouched* | 2.500 | 2.610 | 1.017× | **0.40** |
| `TU0-1282[c]` — *parameters untouched* | 3.428 | 3.799 | 1.155× | **0.64** |

The last two rows are the yardstick. Their parameters were not touched; they move only because any
perturbation reseeds the stochastic draws downstream of it. **Every downstream quantity moves less than,
or about as much as, they do** — so at four seeds and one generation this design resolves no downstream
consequence at all. What it does resolve is direct and consistent: the perturbed unit's own standing pool
goes to exactly zero in all four seeds, removing a transcript that was 2.0% of the fur message.

Anyone tempted to read the Fur-protein column as a 13.5% drop should look at the 186% spread across seeds
*within the control arm alone* (217 to 622 copies). A single seed of this comparison happened to give
−0.34%, which is how a fluke gets published.

Entry 40 stays **unsupported**. What changes is the reason: not a unit slip in a true finding, but a
number belonging to a transcription unit the gene does not use.

## What this means for the five tests

Three separate causes, which is why there is no single guard:

| Test | Cause |
|---|---|
| `test_arm2_columns.py::test_parca_ts_is_stamped_only_where_the_kb_is_provably_the_rows_own` | kb on disk is not the rows' kb |
| `test_corpus_integrity.py::test_a_rows_kb_matches_the_campaign_it_ran_in` | kb on disk is not the rows' kb |
| `test_ko_footprint.py::test_no_warning_when_the_kb_matches` | the shipped cache was built against the old kb |
| `test_corpus_integrity.py::test_the_dedup_outcome_is_pinned_on_the_corpus` | locally-run rows push `wildtype/basal` past its pin of 38 |
| `test_dilution_serialization.py::test_it_flags_the_media_id_column_as_truncation_prone` | a few local runs of one design cannot show the width spread the claim is about |

Each now skips with its own condition and names this file. They are **not** weakened: on the shipped
corpus, with no local rebuild, every one of them still runs and still asserts what it always did. What
the skips say is that the property is unmeasurable against a tree that is no longer the shipped one.

## What it means for the corpus

Re-running a corpus design after a fresh ParCa will **not** reproduce that design's numbers, because
amino-acid supply parameters differ by up to 52%. Known Limitations #4 already concedes that
reproducibility of the published dataset depends on closing this; the size of the gap is now measured
rather than estimated at "1 of 67 conditions".

Closing it means either re-fitting the corpus against the current knowledge base — expensive, and it
mints a new arm — or shipping the fitted `simData.cPickle` alongside the manifest, which the Stanford
licence does not permit. Neither is a code change, which is why this is a recorded limitation and not
a bug.

Tracked as `REPRO-1` in the backlog. `REPRO-2` covers the correction this measurement forces on
`data/claims_audit.json` entry 40, which records the fur half-life shift in the wrong unit and is
therefore filed as unsupported when the mechanism is real.
