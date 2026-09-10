# Three validation plans: RNA-seq, ¹³C flux, conditional essentiality

Written 2026-09-10 on request. Each section says what the test *is*, what already exists, what has to be
built, **what result would count against the model**, and the trap specific to that test. A validation you
cannot fail is not a validation, so each plan states its own failure condition before its method.

A note that applies to all three: **none of these methods is novel.** Comparing simulation to RNA-seq, to
¹³C-inferred fluxes, or to a knockout screen are all standard. The defensible contribution in each case is
the *object* — a mechanistic whole-cell model whose internal state is an emergent consequence of simulated
machinery rather than the output of an optimisation. Write them as "a standard check, applied to something
it has not been applied to", and let the method be boring on purpose. Overclaiming novelty here invites the
one objection any referee in the field will make immediately.

---

## 1. RNA-seq concordance — does the simulated transcriptome look like a real one?

### The question
The model predicts an mRNA copy number for every gene. Real experiments measure the same thing. If you
change a condition — say, acid stress vs standard glucose — both should shift the same genes in the same
direction. **Do they?**

### What already exists (more than you might expect)
`src/cellarium/sci2.py` is built and the data side is done: PRECISE-1K is fetched and SHA-pinned (~17 MB of
raw counts plus metadata, gitignored, Zenodo `10.5281/zenodo.8284223`), a **real DESeq2 run is validated**
(`wt_ph5` vs `wt_glc`, MG1655-filtered to 4,345 genes, genuine acid-stress differential expression at
padj ≈ 0), the symbol→b-number map (4,675 genes) is committed and wired into `sim_lfc`, and there is a
strain-fidelity filter. `rnaseq_concordance` is exposed as a tool.

### What is missing
**The simulation side of the same contrast.** The reference is built; nothing has yet run the matched
condition pair *in the model* and compared the two fold-change vectors.

### The plan
1. **Pick contrasts the model can actually represent.** Not every PRECISE-1K condition has a model
   counterpart. Start with one where it clearly does and the biology is unambiguous; the acid-stress pair is
   already validated on the measurement side, so if the model supports a low-pH condition that is the
   cheapest first pass. Where it does not, the honest move is to say the contrast is out of scope rather
   than approximate it.
2. **Run both arms with enough seeds.** This is a per-gene comparison over thousands of genes, and
   single-seed noise at low copy numbers is large. Use the project's own coverage rule — never one seed, and
   report `n` beside the correlation.
3. **Compute the comparison the way the tool already frames it:** per-gene log2 fold change, sim vs measured,
   reported as Pearson *and* Spearman *and* a Deming slope (which, unlike ordinary regression, does not
   assume the x-axis is error-free — both axes here are noisy), plus sign concordance, **always against a
   null baseline** (shuffle the gene labels and recompute).
4. **Report the divergent genes, not just the summary statistic.** A correlation of 0.4 with a named set of
   systematically-wrong genes is a far more useful result than a correlation of 0.4 alone. Each divergent
   gene is a model-limit hypothesis.

### What would count against the model
Sign concordance indistinguishable from the shuffled null. That would mean the simulated transcriptome
carries no condition-specific information — a much stronger negative than a weak correlation, which is
expected and fine.

### The trap
**Absolute expression levels will correlate well for a boring reason** — both are dominated by ribosomal and
other highly-expressed genes, so a scatter of sim-vs-measured *levels* looks impressive and says almost
nothing. The informative comparison is the **fold change between conditions**, where that shared baseline
cancels. Report levels only as a sanity check, never as the result.

---

## 2. ¹³C flux validation — do the internal metabolic flows match?

### The question
Feed the cell glucose whose carbon atoms are the heavy isotope ¹³C. Those atoms end up distributed through
the metabolic network in a pattern that depends on which routes carried the flow. Measure the labelling
pattern in downstream metabolites, and you can infer the actual internal flux map — how much carbon went
through glycolysis versus the pentose-phosphate pathway, how much through the TCA cycle, how much was
excreted as acetate. Compare that to what the simulation does internally.

### Why this is a strong test, and why the framing matters
Constraint-based models have been ¹³C-validated for ~20 years (Schuetz et al. 2007), so **the method is not
the contribution.** But those models *optimise* toward a flux distribution — you are largely testing whether
the objective function was well chosen. A whole-cell model's fluxes are not optimised; they fall out of
simulated enzyme amounts, kinetics and demand. Matching ¹³C data is therefore a much stronger claim, and it
appears not to have been done for an object of this kind.

### Reference data
**Gerosa et al. 2015** (*Cell Systems* 1:270, PMID 27136056) — ¹³C-resolved fluxes for *E. coli* across
several carbon sources, which is the right shape because it gives multiple conditions rather than one.

### What already exists
`src/cellarium/fba.py` loads and pins iML1515 (the genome-scale metabolic model), with knockout growth, MOMA
and a Keio benchmark join. **That is the constraint-based side.** It is useful here as a *comparator*, not as
the thing being tested.

### What has to be built
1. **Extract the simulation's own central-carbon fluxes.** The model tracks metabolic reaction rates; they
   need pulling out of the raw output for the ~20-30 reactions ¹³C-MFA actually resolves (upper and lower
   glycolysis, the PP pathway branch point, TCA entry, anaplerotic reactions, acetate overflow).
2. **Map reaction identities.** The three namespaces — wcEcoli's reactions, iML1515's, and Gerosa's reported
   flux names — do not agree. This mapping is the bulk of the work and it must be committed as data, not
   inferred at runtime, so a reader can check it.
3. **Normalise to a common basis.** ¹³C fluxes are reported relative to glucose uptake. The simulation's are
   absolute. Compare *ratios*, never raw magnitudes.
4. **Compare on the split points that carry information** — the glycolysis/PP branch, TCA vs anaplerotic
   entry, acetate overflow fraction — rather than reporting a correlation across all reactions, which is
   again dominated by a few large fluxes.

### What would count against the model
Getting the **glycolysis versus pentose-phosphate split** badly wrong, or predicting no acetate overflow on
glucose when the measurement shows substantial overflow. Both are load-bearing, well-measured features of
*E. coli* central carbon metabolism.

### The trap
**Three namespaces and a normalisation choice give many degrees of freedom to make the answer look good.**
Fix the mapping and the normalisation *before* looking at the comparison, commit them, and say in the paper
that they were fixed in advance. Otherwise this becomes an exercise in finding the alignment that fits.

---

## 3. Conditional essentiality — genes that matter only sometimes

### The question
Some genes are essential only in certain environments. Knock out an amino-acid biosynthesis gene and the
cell dies on minimal medium — but shrugs on medium containing that amino acid, because the food supplies
what the missing enzyme used to make. The model should reproduce that pattern: **gene × environment**, not
gene alone.

### What is honestly novel, and what is not
**The old justification was wrong and would have been refuted.** It claimed Keio/Nichols cannot measure
conditional essentiality. They can and did — Nichols et al. 2011 (*Cell* 144:143) is a phenotypic-landscape
screen of ~4,000 mutants across hundreds of conditions, which is exactly this, measured. Baba 2006
(PMID 16738554) supplies the deletion collection.

The narrower, defensible claims are:
- **(a)** an in-silico screen is not limited to conditions someone plated — it can score gene × environment
  cells that were never assayed, including media the model supports but no screen used;
- **(b)** it returns a **mechanism** alongside the verdict — which pathway carries the load, what the cell
  reroutes to — where a growth screen returns only growth or no-growth;
- **(c)** it is **checkable against Nichols as a benchmark**, not offered as a replacement.

Frame it as *"compute what was not assayed, and explain what was."*

### The plan
1. **Choose the gene × environment grid deliberately.** Amino-acid biosynthesis genes crossed with
   minimal / minimal+AA is the clean core, because the mechanism is unambiguous and the expected answer is
   known — which is what makes it a *test* rather than an exploration.
2. **Establish the benchmark cells first.** Score the pairs Nichols measured, before scoring any that were
   not. Agreement there is what licenses the unassayed predictions; without it the extrapolation is
   unsupported.
3. **Use the project's own viability semantics, not a growth threshold invented here.** "Divided" is
   chromosome count and nothing else — `KO:rpmE` divided with translation stopped dead. Any essentiality
   call must go through the existing QC verdicts and the elongation floor, or it will repeat exactly the
   error CAPBENCH's seed case exists to catch.
4. **Report the mechanism per cell**, since that is claim (b): which reactions carry flux in the viable
   condition and not the lethal one.

### What would count against the model
A gene whose conditional pattern **inverts** — lethal on rich, viable on minimal, where the measurement says
the opposite. That is a mechanism error, not a calibration one, and it would be the most informative
possible outcome.

### The trap
**Cost.** This is a grid, and grids multiply: 20 genes × 5 media × 3 seeds is 300 simulations, which at
roughly 10 minutes a generation is days of compute. Two mitigations, both already in the repo: the
`viability_surrogate` triages which knockouts are worth simulating from cheap a-priori gene properties, and
FBA can pre-screen the whole grid in seconds to identify the cells where the answer is *interesting* rather
than obvious. Simulate the interesting cells; report the rest as FBA-screened.

---

## 4. The tRNA charging thread — why there is no plan here

You asked for extra thinking on this one rather than a plan, and that is the right instinct, because the
problem is not "what experiment do we run" but **"what can this model legitimately say?"** Three facts are
already measured and they pull against each other:

- The within-family charged-fraction spreads the model produces (GLY 0.372, LEU 0.241) are **roughly twice
  the widest published measurement** — Dittmar 2005 gives five leucine isoacceptors spanning 0.16, and
  Avcilar-Kucukgoze 2016 reports within-family spread as essentially **zero**.
- The kinetic constants were fitted in **2022 against tRNA abundances this knowledge base no longer has**
  (trpT at 3.68 µM assumed, versus 1.10 µM now). So the magnitudes are not calibrated to the current model.
- The aggregate charged fraction is **0.830** against Choi & Covert's published 0.788 and a
  condition-matched measurement of 0.50–0.60.

What is *not* in doubt: the Dittmar observable is a **within-family ratio**, so per-family synthetase level
cancels out of it, and tRNA abundances are provably untouched by the degradation estimator (all 58 rRNA/tRNA
transcription units carry the stable-RNA constant, so PARCA-1 cannot reach them). **The bound is testable
today; the magnitudes are not.**

So the thinking that has to happen before a plan is worth writing is a scope decision, and it is yours:

- **Option A — claim the bound only.** Report the within-family *ordering* and the fact that the model
  produces a spread at all, explicitly declining to quantify it. Cheap, defensible, and modest.
- **Option B — recalibrate first.** Re-fit the kinetic constants against the tRNA abundances the current
  knowledge base actually holds, then claim magnitudes. Expensive, mints a new arm, and it is a fitting
  exercise whose result may still disagree with Avcilar-Kucukgoze.
- **Option C — treat the disagreement as the finding.** Two published measurements disagree with each other
  about whether within-family spread exists at all; a mechanistic model that produces a spread is a third
  data point in that argument. This is the most interesting framing and the most exposed one, because it
  requires defending the model's spread as informative rather than as a calibration artefact — and right
  now, with 2022 constants and changed abundances, that defence is not available.

My reading is that **A is the only option currently supported by what has been measured**, and that C
becomes available only after B. But which of those the paper wants is a scientific-scope call, not a
technical one.
