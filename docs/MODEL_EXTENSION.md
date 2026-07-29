# Model extension — what we changed in wcEcoli, and what we deliberately did not

Cellarium runs the public Covert-lab wcEcoli model. Some experiments need the MODEL extended, not just driven
differently. This file is the record of those decisions: what was added, what was considered and declined, and
the evidence behind each call. It exists so a reviewer can see the reasoning without reading commit archaeology,
and so a future contributor does not re-open a settled question or re-build something that already exists.

Applied changes live in `scripts/apply_model_patches.py` (idempotent, verifiable, `--check` for CI). Every
change to `reconstruction/ecoli/flat/` requires a ParCa rebuild and therefore a new `kb_sha256`.

---

## EXT-1 — Single-amino-acid dropout media (APPLIED)

**What.** Three media in `reconstruction/ecoli/flat/condition/media_recipes.tsv`, each
`minimal_plus_amino_acids` with exactly one amino acid forced to zero via the `-Infinity` ingredient
convention, plus three matching rows in `condition_defs.tsv`:

```
"minimal_aa_minus_leu"  "MIX0-57"  0.8  "5X_supplement_EZ"  0.2  ["LEU"]  [-Infinity]  []  []
"minus_leu"             "minimal_aa_minus_leu"  {}  25.0  []  []
```

**Why both files.** `make_media.make_recipe` combines base+supplement FIRST and applies `ingredients` to the
RESULT, so `-Infinity` removes the molecule from the final rich medium rather than from a base it was never in.
But the media alone let a sim START and then die on ENTERING one: `sim_data.nutrient_to_doubling_time` is keyed
by MEDIA yet BUILT from the conditions table, and `chromosome_replication.py:92` looks it up with a bare
`[...]`. A 1-seed smoke run — not a code read — surfaced this as `KeyError` at exactly t=1200.
(`metabolism.py:149` uses `.get(media, minimal)` and would have survived; the two processes disagree about
unknown media and the strict one decides.)

**Doubling time = 25.0**, the SOURCE medium's. Minimal-assumption, not a prediction: with ppGpp regulation on,
`metabolism` drives biomass from the RNA/protein ratio rather than this number, which mainly sets the DNA
critical initiation mass. Matching the source medium means the shift introduces no step change in the
replication set-point, so the response comes from the missing amino acid rather than from a discontinuity we
imposed. Empty TF lists follow the `minus_calcium` precedent.

**Names must stay ≤24 characters.** A data-integrity constraint, not style. wcEcoli writes media ids into a
NumPy fixed-width unicode column sized from the FIRST value in the generation; these runs start in
`minimal_plus_amino_acids` (24 chars), so the shift generation gets `<U25`. The first attempt used
`minimal_plus_amino_acids_minus_{leu,thr,arg}` (34 chars) and all three truncated to the IDENTICAL string
`minimal_plus_amino_acids_` — distinct-after-truncation = 1. The record would have shown that *a* shift
happened while making the three arms indistinguishable. This is the SCI-QC-1 defect a second time, in the very
column SCI-QC-2 adopted as its untruncated witness.

**Verified additive.** `scripts/verify_kb_rebuild.py`, three-way: two rebuilds with identical inputs are
bit-identical (ParCa is deterministic); a stock rebuild vs one carrying the media differs in **0 of 67** fitted
keys. A separate pre-existing drift (`minus_phosphate`) between the corpus KB and the current image is
WELL-KBDRIFT-1, not caused by this.

---

## EXT-2 — Per-isoacceptor tRNA charging, for Elf et al. 2003 (DECLINED, for now)

**The question.** Can wcEcoli reproduce Elf, Nilsson, Tenson & Ehrenberg (2003, *Science* 300:1718), where
under starvation one isoacceptor of an amino acid de-charges while another of the SAME amino acid stays
charged? Validation data is Dittmar et al. 2005 (*EMBO Rep* 6:151, PMID 15678157), Table 1.

**The structural answer, verified in source.** No — and our measurement of it was an identity, not a result.
Charging is solved as a 20-state ODE indexed by AMINO ACID. Then:

```python
# models/ecoli/processes/polypeptide_elongation.py:163
self.writeToListener("GrowthLimits", "fraction_trna_charged",
                     np.dot(fraction_charged, self.aa_from_trna))
```

`fraction_charged` is a 20-vector; `aa_from_trna` is 20×86; the dot product broadcasts each family's single
scalar across its isoacceptor columns. Demand is split back across isoacceptors STRICTLY BY ABUNDANCE
(`f_trna = n_trna / aa-totals`, ~line 717). Because charged fraction depends on the mismatch between an
isoacceptor's demand share and its abundance share, allocating demand by abundance forces every family member
to the same value **algebraically, in every condition**.

So our measured within-family spread of exactly `0.00e+00` across leu(8)/arg(7)/ser(5), in starved, rich and
minimal runs alike, is that identity. It is not evidence about biology, and it should be stated as "the model
cannot express this" rather than "we did not observe it".

**Feasible but declined.** The pieces exist: anticodons already sit unused in `rnas.tsv`, per-gene abundances
in `flat/trna_data/`, codons derivable from `sequence.fasta`. Missing: a ribosome-weighted codon-demand vector
and a hand-curated, modification-aware codon×anticodon reading matrix (cmo⁵U34, lysidine, inosine). Code ~4–8
person-weeks; total realistically 3–6 months and 400–600 CPU-hours. New `sim_data` fields change `kb_sha256`,
putting all ~297 existing corpus rows across a knowledge-base boundary.

**Reasons to decline NOW, in order of weight:**

1. **Prior art.** Choi & Covert 2023 (PMC10325894) already built per-isoacceptor charging, codon elongation and
   wobble in this model family. Check the Zenodo deposit `10.5281/zenodo.7859480` first — if usable, the cost
   model changes completely and this decision should be revisited.
2. **The cheap version may be sufficient.** A mean-field steady-state solver using files already in this repo
   reportedly recovers the Dittmar ordering (Thr ρ=1.00, Arg ρ=1.00, Leu ρ=0.90 under mean-pooling) in an
   afternoon. If a months-long whole-cell extension matches Dittmar no better than an afternoon's arithmetic,
   it has bought cost and nothing else — and that cannot be known without building the cheap one first.
3. **A blocking data problem upstream** — see EXT-3. The prediction is a function of the abundance file, and
   that file is currently not trustworthy.
4. **The obvious acceptance gate is backwards.** "Within-family spread ≥ 5×" passes trivially: this class of
   self-consistent fixed point drives non-exclusive isoacceptors to EXACTLY zero (spreads ~10¹²×), whereas
   Dittmar observes a **bounded 5–10× with every value nonzero**. Elf's own theory over-predicts the retained
   isoacceptors by 2–3× (Leu-4 predicted 0.8, observed 0.24). The hard target is the BOUND, not the magnitude.

**Caveat on the evidence.** The 2003 paper itself was paywalled; its internal parameterisation is reconstructed
from the abstract, the open-access companion (Elf & Ehrenberg 2005, *PLoS Comput Biol* 1:e2), and Dittmar 2005
Table 1 read verbatim. The Dittmar numbers are solid; the 2003 internals are not independently confirmed.

**Revisit if:** the Choi & Covert deposit is usable, OR the EXT-3 audit passes and the standalone solver turns
out to disagree with Dittmar in a way only a whole-cell model could resolve.

---

## EXT-3 — tRNA abundance provenance (AUDIT DONE — the per-gene values are not measurement-backed)

`reconstruction/ecoli/flat/trna_data/trna_ratio_to_16SrRNA_*.tsv` gives one abundance per tRNA GENE (86 rows).
Dong, Nilsson & Kurland (1996) measured tRNA per SPECIES (~44), and a species is its anticodon, not which of
several identical genes encodes it. So the per-gene file is a disaggregation of species-level measurements, and
no rule for that disaggregation is documented anywhere in the model.

**Pooling rule declared BEFORE any comparison: SUM** (`scripts/audit_trna_abundance.py`, `POOLING_RULE`).
Declared because abundance is extensive — four genes transcribing the same molecule contribute additively to
the cell's pool. The alternative (MEAN) would be correct only if the file already held a species total
replicated onto each gene. Which of the two it is, is what the audit determines, so the rule was fixed in
advance and allowed to be wrong.

### Result: neither interpretation holds, so the per-gene split carries no information

| check | result |
|---|---|
| genes / distinct values | **86 genes, 34 distinct values**, 40 anticodon species, 0 unmapped |
| within-anticodon consistency (19 multi-gene species) | **0 identical, 19 differing** |
| one value shared across DIFFERENT amino acids | **18 values, covering 68 of 86 genes (79%)** |

The two findings are mutually exclusive as explanations:

* If the file were a species value replicated onto its genes, genes sharing an anticodon would carry the same
  number. **None do** — `CAG` (leuV/leuQ/leuT/leuP, all encoding the SAME molecule, tRNA-Leu(CAG)) carries
  `[0.07, 0.154, 0.2175, 0.2375]`, a 3.4× spread; `CAU` spans 6× across 8 genes.
* If the file were genuine per-gene measurement, unrelated genes would not share values. **79% of genes do** —
  `0.0633` is shared by ala/arg/asp/met/trp/val; `0.075` by asn/gln/gly/ser/val.

So the per-gene resolution is an artifact of an undocumented disaggregation, not data. **Verdict: the per-gene
values are not trustworthy at gene resolution.**

### Why it matters beyond EXT-2

The arbitrary pooling choice is not a rounding difference. **19 of 40 species change by >1%, and the largest
change by up to 8×**:

```
CAU: 8 genes  sum=1.542  mean=0.193   ratio 8.0x
UUU: 6 genes  sum=0.675  mean=0.113   ratio 6.0x
UAC: 5 genes  sum=0.820  mean=0.164   ratio 5.0x
```

For the Dittmar Leu set specifically, `CAG` has 4 genes (sum 0.679 vs mean 0.170) while `GAG`, `UAA`, `UAG`
and `CAA` have one each — so pooling changes CAG's abundance 4× **relative to the isoacceptors it is compared
against**. Since charged fraction goes as demand/abundance, that single undeclared choice moves the predicted
ordering. It is the mechanism behind the reported ρ = −0.10 → +0.90 flip, and it is why the rule had to be
declared first.

Independently of Elf: this file sets tRNA cistron expression in **every existing corpus run**.

### Honest limitation

The external half of the pre-registered criterion — reproduce Dong 1996's per-species values within stated
error for ≥90% of species — is **NOT complete**. Dong's published table was not obtainable here, and it is not
in the repo. What is established is the INTERNAL contradiction, which needs no external data and is on its own
sufficient to conclude that the gene-level numbers are not measurements. Obtaining Dong 1996 Table 2 would
additionally reveal whether the SPECIES-level totals are right, which is the question that decides whether
existing corpus runs are affected in magnitude or only in gene-level attribution.

**Actionable now:** treat tRNA abundance as species-level (anticodon-pooled) in any analysis; never cite a
per-gene tRNA abundance from this file; and state the pooling rule wherever a species abundance is used.

---

## Standing rules for any future extension

- **Two files, not one.** A medium needs a `condition_defs.tsv` row or the sim dies on entering it.
- **Smoke-run before you trust a design.** Every model change here was validated by a 1-seed run that found
  something a code read had missed.
- **Verify the rebuild is additive** (`scripts/verify_kb_rebuild.py`) rather than assuming it. Record BOTH
  `kb_sha256` values and never pool runs across a KB boundary without checking the fitted parameters.
- **Names ≤24 chars** for anything written to a fixed-width simOut column, and run
  `serialization.scan_corpus` afterwards.
- **State the acceptance criterion before the run**, and check it cannot be passed trivially.
- **Declare a pooling or aggregation rule before you look at the comparison it feeds.**
