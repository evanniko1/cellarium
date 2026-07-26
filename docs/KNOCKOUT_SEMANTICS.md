# What a "knockout" actually means in this corpus

A design labelled `KO:rpoB` does not necessarily knock out rpoB. This document explains why, what was measured,
and what a user or reader may safely conclude. It exists because three of our own claims were wrong before we
measured, and because the underlying cause is an upstream issue nobody has documented.

Audited 2026-07-26 across three independent multi-agent passes (`wf_23626a90`, `wf_a7c5b43f`, `wf_dadd5611`),
every code anchor re-opened and confirmed, every consequence measured against real simulation output.

## The mechanism

`models/ecoli/sim/variants/gene_knockout.py` computes a positional index and calls
`sim_data.adjust_final_expression([i], [0])`. That function
(`reconstruction/ecoli/simulation_data.py:314`) zeroes `rna_synth_prob[i]`, `rna_expression[i]`, `exp_free[i]`,
`exp_ppgpp[i]` and `basal_prob[i]` — all vectors indexed over `sim_data.process.transcription.rna_data`.

**`rna_data` rows are transcription units, not genes** (`dataclasses/process/transcription.py:497-540`: TUs
first, then only those cistrons no TU covers). So a "gene knockout" zeroes **one transcription unit**: 3,276
rows for 4,724 genes.

The parameter is still named `gene_indices`. The variant's docstring still describes a gene range. Nothing in
the variant, its comments, or the repo's docs says otherwise.

### Why it is this way — an upstream oversight, with a timeline

| date | commit | what happened |
|---|---|---|
| 2021-09-13 | `69259c06` | operon support added, `DEFAULT_OPERON_OPTION = 'off'` |
| **2022-01-15** | `7dc26808` | **`gene_knockout.py` last modified** — correct in the operons-OFF world it was written for |
| **2022-10-10** | `cf3d8e50` | **default flipped to `'on'`** — the variant's meaning silently changed and it was never revisited |

**The lab knew the general hazard and solved it elsewhere.** `docs/misc/operon-structure.md` describes the fix
for the ParCa's condition path, in as many words:

> genotype perturbations … are applied to all RNAs that contain the specified cistron … to ensure that genotype
> perturbations completely knock out the expression of a certain cistron regardless of the underlying operon
> structure

That is exactly the right approach — **and the variant path does not use it.** `rrna_operon_knockout.py:77`
*does* (via `cistron_tu_mapping_matrix.T`), which shows the tooling exists.

### Other variants with the same or worse defect

Recorded because anyone building on this model needs it, and because it is worth reporting upstream:

| variant | status |
|---|---|
| `gene_knockout.py` | **TU-granularity** — the subject of this document. Cellarium uses it. |
| `multi_gene_knockout.py` | **Cellarium-added**, inherits the same index space — a k-target multi-KO can silence far more than k genes. |
| `aa_synthesis_ko.py`, `aa_synthesis_ko_shift.py` | **Worse — an index-space *mismatch*.** They build indices from `cistron_data` (~4,700 rows) and pass them to `adjust_final_expression`, which indexes `rna_data` (3,276). The result is an unrelated TU or an `IndexError`. The variable is even named `rna_index`. |
| `ppgpp_limitations.py::adjust_enzymes` | same cistron-index-into-TU-space mismatch (`adjust_ribosomes` in the same file is correct). |
| `mene_params.py` | looks up an id absent under operons-ON — the whole variant is a **silent no-op**. |
| `rrna_operon_knockout.py`, `ppgpp_limitations_ribosome.py`, `new_gene_internal_shift.py` | **correct** — checked and cleared. |

Cellarium uses only `gene_knockout`, `multi_gene_knockout`, `rrna_operon_knockout`, `ppgpp_conc`, the metabolism
weight/penalty variants, and conditions/timelines.

## What this means for a design — three outcomes, all real

Whether the named gene is silenced depends on how many TUs transcribe it, but **that is a prior, not a rule**
(see the null result below). What is certain is that the *zeroed TU* is silenced; who sits on it decides the rest.

**① A real knockout that also deletes operon partners.** `KO:flgB` zeroes `TU00273` (`flgBCDEFGHIJ`). Measured:
all nine genes at **0.0 mRNA** (wildtype 5.8) and **0.0 protein** (wildtype ~3,640), while `flgA`, `flgK`,
`flgM` and `fliC` — flagellar genes on *other* TUs — are untouched. It is the transcription unit, not the
regulon. Also in this class: `dapA`→`bamC`, `glmS`→`glmU`, `selA`→`selB`, `ymgD`→`ymgG`.

**② The named gene is not knocked out at all.** `KO:rpoB` zeroes one of rpoB's three TUs. Measured: rpoB mRNA
**10.4 vs wildtype 8.4** — no reduction — and rpoB protein at 85% of wildtype. Also `murA`.

**③ The design silences a gene it is not named after.** `KO:rpmJ` leaves rpmJ expressed (50.1 vs 69.5) and takes
**`secY` to 0.0** (wildtype 15.8).

### The measurement method, and why a raw ratio is not enough

A knocked-out cell grows differently, so its *whole proteome* shifts. In `KO:rpoB`, rpoB protein at 85% looks
like a partial knockdown until you notice that **`rpoA` — which the design cannot touch — is at 81%**. In
`KO:dapA` the run is catastrophic and the median untargeted protein sits at **0.08**, so a naive "ratio < 0.5
means silenced" rule would call the entire proteome silenced.

`src/cellarium/ko_verify.py` therefore judges every gene against a **null distribution built from the genes the
design does not target**, at mRNA and protein independently. "Silenced" means far below what happened to
everything else. A genuinely silenced TU reads exactly **0.0 at both levels**, which is what rules out
"silenced, but the transcript lingers".

### Verified status of the corpus

| verdict | designs |
|---|---|
| **knocked out** (10) | dapA, fabI, flgB, glmS, gltA, lpxC, rpmE, selA, tpiA, ymgD |
| **NOT knocked out** (2) | `murA` (0.968 vs null 0.956), `rpoB` (0.846 vs null 0.815) |
| **partially reduced** (1) | `rpmJ` (0.936 vs null 0.969; silences `secY`) |
| **unmeasurable** (1) | dnaN |
| **unverified — no local raw** (7) | argS, alaS, gltX, lysS, pfkA, pheS, rplB |

The `n_tu == 1` prior is 40/41 across these measurements, and the failure is asymmetric and important:

- `n_tu == 1` → silenced: **no counterexample**. Safe as a *sufficient* condition.
- `n_tu > 1` → survives: **false.** `KO:dapA` fully silenced `bamC` at `n_tu = 2`.

So an unmeasured co-member is **at risk**, never "safe".

## rRNA is a separate story

Two different things exist, and only one of them works.

**The rRNA rebalance ("escape hatch") is real and fires in every run.**
`transcription.py:1946` sets `prob[is_rRNA] = prob[is_rRNA].mean()` — a mean over **all seven rRNA rows,
including any that were just zeroed** — and `balanced_rRNA_prob` defaults to `True` with **no caller anywhere in
wcEcoli passing `False`**.

Because the mean is taken over the zeroed rows too, the overwrite is **sum-preserving**: the *total* rRNA
synthesis probability genuinely falls, but the *per-operon* zero is erased. Consequences:

- **A single rRNA-gene `gene_knockout` would be a null result.** Zero one row of seven, then average, and almost
  nothing changes — while the run completes and reports success. ~33 genes are exposed. **None is a shipped
  design**, and no `gene_knockout` in the corpus targets an rRNA row.
- **The shipped `rrna_operon_knockout` 2op/4op/6op designs are SAFE** — confirmed by four independent checks.
  They reduce *total* rRNA transcription-unit dosage to roughly 5/7, 3/7 and 1/7 of wildtype, and the graded
  dose-response (ribosomes and growth falling together) is real.

**But the wording must change.** They are **not** "operon deletion strains" — no specific operon is deleted, and
after the rebalance all seven rows carry the same probability. What they are is a **graded reduction of total
rRNA synthesis capacity**. That is still the growth-law lever the result claims; it is simply a different
mechanistic statement, and the paper must make the one that is true.

## What a user may safely conclude

- **"Gene X is dispensable"** — only if X is in the verified-knocked-out list *and* you attribute the phenotype
  to the whole zeroed TU, not to X alone.
- **"Gene X is essential"** — never from a design in class ②; the gene was still expressed.
- **"This operon is dispensable"** — this is the honest form of a class-① result, and it is a real biological
  question. Polycistronic structure is genuine biology, and *E. coli* single-gene knockouts have documented
  polar effects, so operon-level dispensability is a legitimate finding rather than only a defect.
- **Anything about rRNA operon identity** — no. Only total rRNA dosage.

`scope.ko_footprint()` surfaces the relevant warning through `mechanistic_scope`, distinguishing measured from
unverified, so the agent cannot report a class-② design as a knockout.

## Open

- Measure the seven unverified designs — `pheS` especially, since the aaRS crash story leans on it and its
  status is genuinely unknown (it was predicted by the half of the rule that is refuted).
- Decide whether a **true single-gene knockout** is worth adding: it *is* possible, contrary to our earlier
  note — zero **every** RNA containing the cistron, exactly as the ParCa condition path already does. That
  guarantees the named gene is silenced. It cannot avoid collateral (operon partners still go), so it fixes
  class ② and ③ but not ①.
- Relabel the affected designs, and reword the rRNA designs, before the dataset ships.
- **Provenance gap:** nothing records the kb hash or the operon option in the manifest or run metadata, so
  "operons-ON" is filesystem inference. It should be recorded.
- Consider reporting the variant defects upstream to CovertLab/wcEcoli.
