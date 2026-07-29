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

## EXT-2 — Per-isoacceptor tRNA charging, for Elf et al. 2003 (DO NOT BUILD — acquire v3.0.1 instead)

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

**VERDICT REVISED — the machinery already exists, and we do not have it.** The Zenodo deposit
`10.5281/zenodo.7859480` is a snapshot of `CovertLab/WholeCellEcoliRelease` **v3.0.1** (Choi & Covert 2023,
CC-BY-NC-4.0). Checked directly, and it changes the answer:

* **The release resolves isoacceptors.** It carries a `KineticTrnaChargingModel` whose charging state is
  dimensioned `n_trnas`, not 20, plus `trnas_to_codons` / `codons_to_trnas` — the codon×anticodon reading
  matrix, including the inosine- and lysidine-modified exceptions at specific Arg and Ile codons. The paper
  states it represents "85 tRNAs (in their aminoacylated and unaminoacylated forms)" and models "61 sense
  codons" with Watson-Crick and wobble pairing.
* **Our checkout does not have it.** `MohammedNagdi/wcEcoli` exposes only `BaseElongationModel`,
  `TranslationSupplyElongationModel` and `SteadyStateElongationModel`; we run the last. `KineticTrnaCharging`,
  `trnas_to_codons` and `codons_to_trnas` return **zero matches** across `models/`, `reconstruction/` and
  `wholecell/`. So this is a fork-lineage gap, not a missing capability in the model family.
* **Nobody has run the test.** Choi & Covert cite Elf's selective-aminoacylation theory but make **no attempt
  to reproduce Elf 2003 or Dittmar 2005**. So "does the published per-isoacceptor whole-cell model reproduce
  selective charging?" is an open question in a model that already has every mechanism required.

That converts a 3-6 month build into an acquisition plus an experiment, and it is the strongest available
version of this line of work: a genuinely novel result at a fraction of the cost. The remaining risk is
integration, not capability — v3.0.1 is the RELEASE lineage while our fork descends from the dev repo, so the
realistic route is to run the comparison in the release model standalone rather than to merge it into ours.

**What still stands from the original decline:**

* EXT-3 remains blocking either way. Charged fraction goes as demand/abundance, so the abundance file is the
  prediction, and it is not trustworthy at gene resolution.
* The acceptance gate is still backwards if stated as "spread >= 5x" — this class of fixed point drives
  non-exclusive isoacceptors to EXACTLY zero (~10^12x), whereas Dittmar observes a **bounded 5-10x with every
  value nonzero**, and Elf's own theory over-predicts the retained isoacceptors 2-3x (Leu-4 predicted 0.8,
  observed 0.24). Target the bound.
* Any run in v3.0.1 carries its own `kb_sha256` and is NOT comparable to our corpus. That is a separate
  experiment, not an extension of the existing dataset.

**What NOT to do:** build per-isoacceptor charging into our fork. That was the original proposal and it is now
clearly the wrong call - it would reimplement, worse, something already published and downloadable.

**Caveat on the evidence.** The 2003 paper itself was paywalled; its internal parameterisation is reconstructed
from the abstract, the open-access companion (Elf & Ehrenberg 2005, *PLoS Comput Biol* 1:e2), and Dittmar 2005
Table 1 read verbatim. The Dittmar numbers are solid; the 2003 internals are not independently confirmed.

**Next step, in order:** (1) finish EXT-3 by obtaining Dong 1996 Table 2, since the abundance file feeds any
prediction; (2) obtain v3.0.1 and confirm the kinetic model runs; (3) run the Dittmar Table 1 comparison in it
with the bound-not-magnitude criterion declared in advance. Step 3 is the publishable one and nobody has done
it.

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

### External half COMPLETE — the mapping is misaligned, not merely undocumented

Dong 1996 obtained (J Mol Biol 260:649-663; 44 of 46 species resolved by 2D gel). **Table 3, "molar ratio of
tRNA/ribosome at different growth rates", has columns 0.4 / 0.7 / 1.07 / 1.6 / 2.5 — exactly the five column
headers in `trna_data.tsv` (`ratio to 16SrRNA at 0.4 hr^-1` ...).** 16S rRNA is 1:1 with ribosomes, so the file
is unambiguously derived from that table.

The disaggregation rule turns out to be recoverable: for **19 of the 34 distinct values**, `value x n_genes`
equals a Dong species value to three decimals. So each species value was divided by a gene count. But the
quotients were assigned to the WRONG GENES:

| file value x n | = Dong species | genes it was actually assigned to |
|---|---|---|
| `0.2225 x 4 = 0.89` | **Leu1** | glt, ile, met, pro |
| `0.154 x 5 = 0.77` | **Val1** | ala, ile, leu, phe, thr |
| `0.0633 x 6 = 0.38` | Leu4 / Lys | ala, arg, asp, met, trp, val |
| `0.095 x 4 = 0.38` | Leu4 / Lys | ala, asn, asp, ile |

Leucine-1's abundance is spread across glutamate, isoleucine, methionine and proline genes; valine-1's across
alanine, isoleucine, leucine, phenylalanine and threonine. **The species-to-gene mapping is scrambled** — the
signature of a sort-order mismatch between Dong's species list and the gene list, not of a deliberate rule.

**Caveat, stated plainly:** Dong's values are not unique (0.38 is both Leu4 and Lys; 0.13 is Val2A, Val2B and
Leu3), so individual matches could be coincidence. 19 of 34 agreeing to three decimals across varied gene
counts is far beyond chance, but the decisive evidence is not the arithmetic — it is that even where the
arithmetic matches, the amino acid does not.

**Verdict: the pre-registered criterion FAILS.** The declared SUM pooling does not reproduce Dong per species,
and cannot, because the values are attached to the wrong genes. Per-gene tRNA expression in the model — and
therefore in all ~297 existing corpus runs — does not reflect its cited source.

### Why a 1996 paper at all

Because it is the file's OWN source, and the question was provenance: does the data reproduce what it cites?
Recency is irrelevant to that check. For the SCIENCE, modern data is clearly better — mim-tRNAseq (Behrens et
al. 2021), OTTER, AQRNA-seq and nanopore-based quantification all post-date it, and there is a modern E. coli
charging-level protocol (PMC5614356). But a per-isoacceptor abundance series ACROSS GROWTH RATES (0.4-2.5
doublings/h), which is what wcEcoli's five columns need, does not appear to exist in modern form — which is
why the model still rests on 1996 measurements. Replacing them with a modern series would itself be a
contribution.

### Honest limitation

SUPERSEDED — the external half is now complete (see above). Dong 1996 Table 3 was obtained and compared. What is established is the INTERNAL contradiction, which needs no external data and is on its own
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
