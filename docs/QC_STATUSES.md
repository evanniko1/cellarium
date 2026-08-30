# QC statuses — what every `qc` value means, and how to read one

Every row in the corpus carries a `qc` value. It is the first thing you meet and, until now, the only piece of
the vocabulary with no reference page. This is that page.

Source of truth: [`src/cellarium/qc.py`](../src/cellarium/qc.py). If this document and that module disagree,
the module is right and this page is a bug.

---

## The one rule that matters most

**`qc` has TWO meanings and they must not be conflated.**

* For a **continuous reading** — a growth rate, a doubling time, a channel mean — anything other than `ok` is
  **evidence-ABSENT**. Report the flag; never report a number derived from that row.
* For a **viability / lethality / essentiality** question, a failure **is the readout**. `no_division`, `dead`,
  `fba_infeasible`, `translation_collapse` and crashed runs are **positive evidence** that the perturbation is
  inviable. Count them. Never discard a crashed knockout as "unreportable", and never call a lethality
  hypothesis untestable *because* its knockouts crashed — the crashes are the data.

`implausible_channel` and `over_replicated` are a third case: they flag an untrustworthy **number**, not an
absent run.

`reportable` is the derived flag: **true only when every generation is `ok`** (`qc.is_reportable`).

---

## The vocabulary

| status | meaning | produced by |
|---|---|---|
| `ok` | every check passed | default when nothing else fires |
| `empty` | no readable generation data at all | `check_result` on a result with zero generations — an empty read must never launder into `ok`, which is exactly how disk-crash artifacts once slipped through as viable |
| `dead` | the model's own death flag was inherited | `gen.is_dead` |
| `degenerate` | the generation ran ≤ **10** timesteps | `DEGENERATE_MAX_STEPS` |
| `over_replicated` | chromosome count ended above 2 | `full_chromosome_end > 2` |
| `fba_infeasible` | the FBA objective was non-finite or ≤ 0 at the last step | `not gen.fba_ok` |
| `implausible_channel` | "divided" but numerically collapsed — instantaneous growth above **0.001 /s** | `IMPLAUSIBLE_GROWTH`; a ~11.5-minute doubling, faster than any real or model condition |
| **`translation_collapse`** | **ribosomes effectively stopped — mean elongation below 1.0 aa/s — while the chromosome finished anyway** | `TRANSLATION_COLLAPSE_AA_PER_S`; see below |
| `no_division` | the cell did not divide, or no division time is readable | `not gen.divided or gen.division_time_sec is None` |
| `truncated` | data stops *before* the division that ended the generation | cross-generation pass; a gap larger than `MAX_GENERATION_GAP_SEC` (5.0 s) between generation *n*'s end and *n+1*'s start |

Order matters: `check_generation` returns the **first** status that fires, and `check_result` reports the
first non-`ok` status across generations. `truncated` runs **after** the per-generation pass precisely because
truncation is invisible to a single generation and must be able to overturn an `ok`.

### One value that does not come from `qc.py`

`noop_knockout` appears in the corpus `qc` column (**7 rows**, all with a null `design_key`) but is **not** a
`QCStatus`. It is a finding from the knockout-semantics work — the perturbation did not do what its name says
— and `scripts/corpus_audit.py` treats it as lethality evidence alongside `no_division`. Do not expect
`qc.py` to produce it, and do not treat its absence from the enum as a bug.

---

## `translation_collapse`, and why the threshold is where it is

Added 2026-08-29. It closes a hole that had been open since the beginning.

`divided` is computed as `full_chromosome_end == 2 and n_steps > 10` — **chromosome count and nothing else**.
DNA replication in wcEcoli proceeds without functioning translation, so a cell whose ribosomes had stopped
scored `divided = True`, passed every remaining check, and returned `ok`. `IMPLAUSIBLE_GROWTH` is a *ceiling*
for numerically exploded runs; there was no floor.

**Measured** on `gene_knockout/KO:argS` under the kinetic elongation model — all three generations recorded
`qc=ok` before this existed:

| | mean elongation (aa/s) |
|---|---|
| generation 0 / 1 / 2 | **0.047 / 0.012 / 0.007** |
| wild type, same model | **16.72** |

ArgS protein was `0.0` at every timestep and arg-tRNA charging was exactly `0`. The cell was translationally
dead and was being reported as a clean division.

**It is invisible in the manifest.** That same knockout reports `growth_rate` **0.00025 — identical to wild
type** — while elongation is 2400× lower. No recorded column separated them, which is why the raw had to be
opened and why this needed a new channel rather than a new query.

### The threshold is anchored to measurement, not taste

*E. coli* elongation rates from the literature:

* **20–21 aa/s** above one doubling/h — Forchhammer & Lindahl 1971, *J Mol Biol* 55:563
* **17 aa/s** fast, **12 aa/s** at 0.67 doublings/h — Young & Bremer 1976, *Biochem J* 160:185
* **Dai et al. 2016**, *Nat Microbiol* 2:16231 ([PMID 27941827](https://pubmed.ncbi.nlm.nih.gov/27941827/)) —
  the rate does **not** collapse as growth slows: *"an appreciable elongation rate is maintained even towards
  zero growth, including the stationary phase"*, because a slow cell reduces its **active ribosome fraction**
  rather than its elongation rate.

So **"the cell was just growing slowly" is not an available explanation** for 0.05 aa/s — that is one residue
every 20 seconds, and a 300-residue protein would take 100 minutes.

`TRANSLATION_COLLAPSE_AA_PER_S = 1.0` sits an order of magnitude below the slowest rate ever measured and ~17×
below this model's own wild type. A genuinely slow cell at 12 aa/s — or even a hypothetical 5 — still reads
`ok`; there are tests pinning both directions.

### Absent is not healthy

The channel (`RibosomeData/effectiveElongationRate`, registered as `effective_elongation_rate`) is read by
`_reader_worker` and carried on `GenerationResult.elongation_mean`. **Rows written before 2026-08-29 have no
such reading**, and a `None` returns `ok` rather than `translation_collapse` — absence of the channel is
evidence of neither viability nor collapse. Re-classifying those rows is tracked as `QC-VIA-1` in
[BACKLOG.md](../BACKLOG.md).

---

## Reading a status in context

The elongation model matters. The corpus carries three (see [CORPUS_ARMS.md](CORPUS_ARMS.md)), and a status
means different things across them — `steady_state` couples the stringent response, so an amino-acid
limitation is sensed and the cell arrests; `kinetic` resolves individual tRNAs but does **not** couple ppGpp,
so the same limitation can leave `ppgpp_conc` at 0.0 while translation dies silently. That is precisely the
case `translation_collapse` was built to catch.

**Never pool rows across elongation models**, and never compare a status from one against a status from
another without saying which model produced it.
