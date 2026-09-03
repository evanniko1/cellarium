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

`tnaC` and the fur-only unit swap rates outright. So **fur mRNA stability differs by 228× between the
two builds** — a consequence of the cistron removal shifting an index, not of any parameter being
re-estimated.

This confirms the mechanism behind `data/claims_audit.json` entry 40 and corrects its magnitude: that
entry reads "24 to 91 s" and is marked *unsupported*. The measured values are 24 **seconds** and 91
**minutes**.

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
