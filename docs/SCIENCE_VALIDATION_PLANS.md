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

**Revised 2026-09-10 (second pass).** Three things changed and are worth flagging rather than absorbing:
§1 now names the specific contrasts, measured against what PRECISE-1K actually contains — and that
measurement **withdrew this document's own first suggestion**, which was to start from the acid-stress pair
(the model has no pH). §2 answers "why is this necessary" with an argument instead of an appeal to
interest. §3 records the decision to screen the whole grid with FBA first and simulate only the cells the
screen makes interesting. §4 is parked by decision.

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

### Which contrasts actually exist — MEASURED 2026-09-10, and it narrows the plan sharply
A contrast needs a model condition on one side and same-strain samples on the other, and the intersection
is much smaller than either list. Measured by crossing the model's 23 media conditions
(`reconstruction/ecoli/flat/condition/condition_defs.tsv`) against the 420 non-evolved MG1655 samples in
PRECISE-1K:

| Model condition | PRECISE-1K arm | n measured | Reference arm | Verdict |
|---|---|---|---|---|
| `acetate` | `wt_ac` | 3 | `wt_glc` (n=19) | **Experiment 1** |
| `no_oxygen` | `wt_glc_anaero` | 2 | `wt_glc` (n=19) | **Experiment 2** |
| `with_aa` | `wt_lb` | 4 | `wt_glc` (n=19) | **Experiment 3** — approximate, see below |
| `plus_nitrate` | `no3_anaero` | 2 | `wt_glc_anaero` (n=2) | Underpowered on both sides |
| `glc_2mM` / `glc_5mM` / `glc_20mM` | glucose 2 g/L (≈11 mM) and 4 g/L (≈22 mM) | many | — | No 2 mM or 5 mM arm exists |
| `plus_arabinose` | arabinose samples are all ALE (evolved) | 6, all evolved | — | Fails the strain-fidelity filter |
| `succinate`, `fumarate`, `malate`, `plus_indole`, `plus_gallate`, `plus_quercetin`, `plus_tungstate`, `plus_nitrite`, `minus_calcium`, `minus_magnesium`, `minus_phosphate` | — | **0** | — | No reference data at all |

Two findings from that cross change the plan as it was previously written here:

**(a) The acid-stress pair cannot be simulated — and the earlier draft of this section assumed it could.**
It said the `wt_ph5` contrast was "the cheapest first pass" *if the model supports a low-pH condition*. It
does not: there is no pH among the 23 conditions, and pH is not a state variable of the model. So the one
contrast whose measurement side is already DESeq2-validated is the one contrast with no simulation side.
That is a scope statement, not a failure — but it must be stated, because the validated reference invites
exactly the mistake of reaching for it first.

**(b) The largest reference set available is one the model cannot use.** Glycerol has **111** MG1655
samples in PRECISE-1K — the biggest non-glucose block by a wide margin — and there is no glycerol condition
in the model. Fructose (8), pyruvate (8) and xylose (5) are the same story. If more carbon-source coverage
is ever wanted, adding glycerol to the model buys more reference data than any other single condition.

### The three experiments, named

**Experiment 1 — acetate versus glucose. Run this one first.**
*Simulation side:* `condition/acetate` (13 corpus runs) against `wildtype/basal` (46 runs). **Both arms are
already simulated.** What is missing is not compute but the per-gene read-out: `sim_lfc` needs the all-gene
mRNA reader, which needs raw `simOut`, and raw is not on local disk for acetate. It **is** on HuggingFace
and verified present (`runs/cellarium/condition_000005/000000.tar.gz`), so step 0 is a download, not a
simulation campaign. Both gene maps this join needs are already committed
(`data/cache/bnumber_map.json`, `data/cache/cistron_map.json`).
*Measurement side:* `wt_ac` (n=3) versus `wt_glc` (n=19), MG1655-filtered, through the existing DESeq2 path.
*Why first:* carbon source is a first-class model condition rather than something approximated; the biology
is unambiguous (gluconeogenesis and the glyoxylate shunt up, glycolysis down); and both sides are the
best-replicated pair available.

**Experiment 2 — anaerobic versus aerobic growth on glucose.**
*Simulation side:* `condition/no_oxygen` (8 corpus runs) against `wildtype/basal`. Same download-then-read
route as Experiment 1.
*Measurement side:* `wt_glc_anaero` (n=2) versus `wt_glc` (n=19).
*Why worth doing at n=2:* the aerobic→anaerobic switch is one of the largest coordinated transcriptional
responses *E. coli* has (the whole FNR/ArcA programme), so the effect size dwarfs the replication weakness.
Report the n beside the correlation and do not present this as the powered result — it is a high-signal
confirmation that the model moves the right genes, not a precise estimate of how much.

**Experiment 3 — amino-acid supplementation, scored on a restricted gene set only.**
*Simulation side:* `condition/with_aa` (12 corpus runs) against `wildtype/basal`.
*Measurement side:* `wt_lb` (n=4) versus `wt_glc` (n=19).
*The caveat that determines how it is scored:* **LB is not minimal-plus-amino-acids.** LB supplies peptides,
nucleosides and vitamins and essentially no glucose, so a transcriptome-wide correlation here measures the
mismatch between the two media as much as it measures the model. Score it on the gene set where the two
media genuinely agree — **amino-acid biosynthesis operon repression** — and report it as a directional
check on a named pathway, never as a whole-transcriptome concordance. If that reads as too weak to be worth
running, that is a fair reading; it is listed third for exactly that reason.

### RESULT — Experiment 1 ran, 2026-09-11, and the abundance floor was manufacturing the answer
`condition/acetate` (13 runs) vs `wildtype/basal` (17 reachable), against DESeq2 on `wt_ac` (n=3) vs
`wt_glc` (n=19). Two methodological defects surfaced, both fixed, and the second **reverses the first
reading of the result**.

**(a) A global shift was being read as concordance.** Every simulated gene came back negative — 75 of 75,
median log2FC −2.17. That is cell size, not expression: the simulation counts absolute molecules per cell
and an acetate cell is smaller, while DESeq2 is compositional and cancels a global shift by construction.
The two were being compared on different bases, and it produced a `sign_concordance` of **0.971** — the
shift agreeing with itself. Median-centring (the first-order equivalent of DESeq2's own median-of-ratios
size factor) now runs by default and the removed shift is reported rather than erased. 0.971 → **0.529**.

**(b) The count floor was hiding the informative genes.** A hard-coded floor of 20 molecules/cell left 75
of ~4,300 genes; the real contrast has **999** significant genes and the simulation could see **34**. The
survivors are the high-abundance head — ribosomal and translation machinery — the set most dominated by
growth rate and least informative about carbon source. `scripts/count_floor_sweep.py` measures the ladder:

| floor | genes | significant visible | Pearson r | r/SE | sign concordance | z vs coin-flip |
|---|---|---|---|---|---|---|
| 20.0 | 75 | 34 (3.4%) | 0.122 | **1.0** | 0.529 | **0.5** |
| 10.0 | 115 | 51 (5.1%) | 0.272 | 2.9 | 0.588 | 1.9 |
| 5.0 | 225 | 93 (9.3%) | 0.083 | 1.2 | 0.570 | 2.1 |
| 2.0 | 493 | 155 (15.5%) | 0.075 | 1.7 | 0.645 | 6.4 |
| 1.0 | 843 | 226 (22.6%) | 0.134 | 3.9 | 0.593 | 5.4 |
| 0.5 | 1379 | 310 (31.0%) | 0.189 | **7.0** | 0.665 | **12.3** |

**What this says, and it is not what the first run said.** At the default floor neither statistic is
distinguishable from zero (r/SE = 1.0, sign z = 0.5) — which is the "the pre-registered failure condition
was met" reading, and it was wrong. At floor 0.5 both are strongly significant (r/SE = 7.0, sign z = 12.3)
over 1,379 genes covering 31% of the real signal. **The model does carry condition-specific transcriptional
information; the default floor was excluding the genes that carry it.**

The shuffled-label null stays at ≈0 across the whole ladder (0.011 → −0.002), so the added genes are not
noise the statistic is mistaking for agreement — which was the specific worry that justified a floor.

**The peak at floor 10 is not a finding.** r = 0.272 is the largest point estimate and sits at r/SE = 2.9 on
n = 115, while the bottom of the ladder sits at 7.0 on n = 1,379. Sign concordance does not peak there
either. The trend is *lower is better, at least down to 0.5*; there is no evidence for an optimum in
between, and the correlation remains **weak** (r ≈ 0.19) even where it is most significant.

### How each is computed
Unchanged from what `sci2.py` already implements, and worth restating because the discipline is the point:
per-gene log2 fold change, sim versus measured, reported as Pearson **and** Spearman **and** a Deming slope
(which, unlike ordinary regression, does not assume the x-axis is error-free — both axes here are noisy),
plus sign concordance, **always against a shuffled-label null**. Then **report the divergent genes, not just
the summary statistic**: a correlation of 0.4 with a named set of systematically-wrong genes is far more
useful than a correlation of 0.4 alone, because each divergent gene is a model-limit hypothesis.

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

### A correction first: this model does not maximise growth
An earlier draft of this section argued that "the metabolism is a constraint-based model" is the criticism a
referee would make. **That was wrong, and the objection to it was right.** Being constraint-based is not a
flaw, and more importantly it misdescribes what wcEcoli actually does.

Read `models/ecoli/processes/metabolism.py`: the objective is `homeostatic` when the kinetic weight is zero
and `homeostatic_kinetics_mixed` otherwise. There is **no biomass-maximisation term anywhere**. What the
solver minimises is deviation from *metabolite concentration targets* — plus, when λ > 0, deviation from
*reaction-rate targets* derived from the enzyme amounts the rest of the simulation produced — under a
secretion penalty and a maintenance cost. The targets come from what transcription, translation,
replication and division are actually consuming this timestep.

So the flux map is **demand-driven, not growth-optimised**. That is a materially different object from
textbook FBA, and it changes what the ¹³C test is *for*.

### Why it is necessary — the argument, not the appeal
**1. It is the only one of the three plans that tests the model's interior.** RNA-seq tests what the cell
*intends* — transcript levels, the input side. Essentiality tests what happens to the cell *in the end* —
live or die, the output side. Neither constrains the flux map in between, and that gap is not small: a very
large family of internal flux distributions produces the same growth rate. A model can get transcription
approximately right and growth approximately right while routing carbon through the wrong pathways, and
**nothing in the other two plans would notice**.

**2. The question it answers has not been asked of an object like this.** Constraint-based models have been
¹³C-validated for twenty years (Schuetz 2007), but those tests largely ask *was the objective well chosen*.
Here there is no growth objective to validate. The question becomes **does demand-driven flux allocation
reproduce the measured routing?** — and that is a genuinely open question, not a re-run of a settled one.

**3. There is a sharper objection than the one the earlier draft invented, and ¹³C is what answers it.**
The homeostatic targets are themselves **fitted** — ParCa sets those concentrations. So a sceptic can say
"demand-driven" really means "driven by fitted targets", and agreement is circular. What defeats that is
specific: **the targets constrain concentrations, not which route delivers them.** Nothing in the fit
specifies how much carbon goes through glycolysis versus the pentose-phosphate pathway; that split is a
consequence of stoichiometry, enzyme amounts and the secretion penalty. So the split ratio is a real
out-of-sample prediction *even though the targets are fitted*, and it is the quantity ¹³C-MFA resolves best.

**4. There is already a measured failure pointing at exactly this.** `KO:pgi` knocks out phosphoglucose
isomerase, forcing carbon through the PP pathway. The literature says such a mutant is viable at roughly
**half** wild-type growth, through NADPH/redox imbalance (Canonaco 2001; Charusanti 2010). This model
reproduces the viability but **not the severity: −6.4% growth**, and a deeper run showed the gap plateaus
rather than widening — it reroutes almost for free. That was diagnosed as inheriting the FBA redox blind
spot. **A ¹³C comparison says directly whether the PP flux is also wrong in the wild type**, or only under
the knockout. That is a specific hypothesis with a specific measurement, not a fishing expedition.

**The honest limit: necessary for the claim, not for a deadline.** This is the most expensive of the three
plans — the reaction-identity mapping alone is real work — and a workshop paper does not need it. It is
necessary for *the claim that the flux map means something*, and optional for a submission. If it is cut,
say plainly that the interior is unvalidated rather than letting the other two checks imply otherwise.

### The experiments, named
Gerosa et al. 2015 measured ¹³C-resolved fluxes on eight carbon sources: acetate, fructose, galactose,
glucose, gluconate, glycerol, pyruvate and succinate. The model has 23 media conditions. **The intersection
is three**, and all three are already simulated:

| Condition | Gerosa | Corpus | Direction |
|---|---|---|---|
| Glucose | ✓ | `wildtype/basal`, 26 reportable runs | Glycolytic — the reference case |
| Acetate | ✓ | `condition/acetate`, 13 runs | Gluconeogenic — runs the network backwards |
| Succinate | ✓ | `condition/succinate`, 3 runs | Gluconeogenic, via a different entry point |

Fructose, galactose, gluconate, glycerol and pyruvate have no counterpart among the model's conditions, so
they are out of scope unless a condition is added.

**Experiment A — the glucose split ratios.** The core test. Extract the simulation's own fluxes for the
~20-30 reactions ¹³C-MFA actually resolves, normalise to glucose uptake, and compare *ratios* on the three
branch points that carry the information: **glycolysis versus pentose-phosphate at G6P**, **TCA versus
anaplerotic entry**, and the **acetate overflow fraction**. Not a correlation across all reactions — that
is dominated by a few large fluxes and says little.

**Experiment B — the two gluconeogenic conditions.** Acetate and succinate run the network in the other
direction, through the glyoxylate shunt and PEP carboxykinase. A model that matches on glucose and fails
here has learned one flux map rather than a mechanism, so this is what makes Experiment A more than a
single-point fit. Note that succinate has only **3 runs** — report the n, and treat it as a directional
check rather than a precise estimate.

**Experiment C — the λ sweep. NOT AVAILABLE, and this is worth knowing before anyone plans around it.**
The natural third experiment is to score each level of the kinetic-objective weight against the measured
flux map, turning an inherited default (λ = 1e-7) into a measured one. The corpus appears to support it:
eight λ levels and five secretion-penalty levels are indexed. **Measured 2026-09-11: all 41 runs across
both sweeps crashed — 23 of 23 for `kin_w`, 18 of 18 for `sec_pen`, zero usable rows.** The sweeps exist as
rows and not as data, which is the datasheet's limitation 2 arriving in practice. Diagnosing that crash is a
prerequisite, not a footnote, and it should be scoped as its own item before Experiment C is planned again.

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

### DECIDED 2026-09-10 — screen the whole grid cheaply, then simulate only what the screen makes interesting
This is the shape you proposed and it is the right one, for a reason worth writing down: it makes the cost
argument disappear without weakening the test. The grid is run **twice, at two resolutions**.

**Stage 1 — FBA over the entire gene × environment grid.** Seconds, not days. `fba_essentiality_panel` and
`fba_gene_knockout` score every cell against iML1515 in each medium. The output is a complete in-silico
conditional-essentiality map, and it is a deliverable in its own right: scored against Nichols 2011 it is a
benchmark result, and it is the thing claim (a) — *compute what was not assayed* — actually rests on.

**Stage 2 — whole-cell simulation of the cells the screen makes interesting.** "Interesting" has to be
defined before the screen is read, not after, or this becomes a search for cells that confirm us. Three
categories qualify:
- **Disagreements with Nichols** — FBA says essential where the screen says viable, or the reverse. These
  are where a mechanistic model can say something a stoichiometric one cannot.
- **Conditional flips** — a gene FBA calls essential in one medium and dispensable in another. The flip is
  the phenomenon; the simulation says *how* the cell reroutes.
- **Cells no screen assayed** — the media the model supports that nobody plated. This is where the
  extrapolation lives, so a handful should be simulated rather than asserted from FBA alone.

**Why this costs less than it looks: the simulations were owed anyway.** Every Stage-2 run becomes a corpus
row with the same provenance, QC and arm columns as everything else. The dataset needs to grow regardless,
and this is a principled selection rule for what to grow it with — better than picking designs by interest,
which is what has largely happened so far. The validation and the dataset expansion are the same compute.

**The limit that keeps Stage 1 honest.** FBA and the whole-cell model disagree *by construction* in places —
that is exactly what `metabolic_essentiality` versus `viability` measures — so "FBA says this cell is
boring" is not evidence the whole-cell model would agree. Stage 1 **selects**; it does not substitute. Say
so in the write-up, and report the FBA verdict for the unsimulated cells as an FBA verdict, never as a
result of the model this paper is about.

### Stage 1 is built: `scripts/conditional_essentiality_screen.py`
The grid and the selection rule are declared **at the top of that file, above the code that reads the results**, which is the whole point of writing it as a script rather than running it by hand. The grid is 17 amino-acid families crossed with three media — minimal, minimal plus all twenty amino acids, and minimal plus *only the amino acid that gene's pathway makes*, which is the sharp form of the test because a generic rescue could come from any of the twenty.

Four selection reasons are fixed in advance: a **disagreement with Keio**, a **conditional flip** (lethal on minimal, viable when supplemented), a **rescue failure** (lethal on minimal and *still* lethal with its own amino acid supplied — the firm expectation broken, so the gene does something else), and **already in the corpus**, which is a reason to look rather than a reason to simulate. The output records the **rejected** cells beside the selected ones, so the rejection set is visible rather than implied.

```bash
python scripts/conditional_essentiality_screen.py --top 14
```

### Stage 1 has been run — 2026-09-11
56 amino-acid biosynthesis genes across 17 families, three media, 168 FBA + linear-MOMA solves.
**48 selected, 8 rejected.** By reason: 34 conditional flips, 12 disagreements with Keio, 7 rescue
failures, 2 with a free whole-cell verdict. Full output in `data/sci3_stage1.json`, rejected cells included.

**The one result available at no compute cost, and the caveat that has to travel with it.**

| Gene | FBA on minimal | Keio | Whole-cell corpus |
|---|---|---|---|
| `dapA` | lethal | essential | collapses at generation 2 — growth −80% vs depth-matched WT, ppGpp +929%, stringent signature |
| `leuB` | **viable** | essential | collapses at generation 3 — growth −62%, ppGpp +406%, stringent signature |

`leuB` is the interesting row: **FBA is the outlier**, and the mechanistic model agrees with the experiment
where the stoichiometric one does not. That is exactly claim (b) — except that it is *suggestive rather than
decisive*, because both existing runs are **operon-wide**: `KO:leuB` is really `operon_KO:leuLABCD` and
`KO:dapA` is really `operon_KO:dapA-nlpB`, while the FBA arm knocks out a single gene. Different
experiments. The script now prints that caveat next to the verdict rather than leaving it to be noticed.

**It constrains Stage 2, which is the more valuable finding:** a run meant to be compared against Keio or
FBA has to be a genuine single-gene knockout, or it answers a different question. That was not obvious
before running the screen.

**Two corrections the first run forced, both recorded in the script rather than quietly fixed.**

**(a) "Already in the corpus" has four states, not two.** The first version asked only whether rows exist
with the gene in the label. For `argG` and `thrC` the answer was yes — 4 and 8 rows, **every one
`qc == "ok"`** — and the conclusion "a whole-cell verdict is free" was wrong: both carry a NULL
`kb_sha256`, so they belong to no arm and `survey.analysis_rows` correctly refuses to pool them. Rows that
are present, readable, `ok`, and that no analysis path will use. That is this project's own silent-absence
defect, committed inside a screen whose output tells someone where to spend days of compute. The states are
now named: `analysable`, `collapsed`, `unusable_arm`, `absent`.

**(b) `rescue_failure` does not detect surprises.** The rule is unchanged and selects the same seven cells;
the sentence describing it was wrong. Those seven are the five `dap` genes and `ilvC`/`ilvD`, and neither
group is unexpected: the `dap` pathway makes **diaminopimelate**, a peptidoglycan precursor as well as a
lysine precursor, so no amino acid rescues it — and DAP is not among the twenty, which is why even the
all-amino-acid arm stays lethal. `ilvC`/`ilvD` serve the valine branch too, which is why isoleucine alone
fails and the full mix succeeds. What the reason actually detects is a **shared-pathway enzyme or a
non-proteinogenic product**. Still worth simulating; not evidence the model did anything unexpected.

### The cheap analysis before any Stage 2 compute — done 2026-09-11
Sorting the 12 Keio disagreements by WHICH WAY they point costs nothing and changes what is worth
simulating. `python scripts/conditional_essentiality_screen.py --directions`.

**⚠️ First, a mismatch that had to be found before the split could be read.** Keio essentiality is defined
by failure to obtain a deletion mutant in **complex (LB) medium** — Baba 2006 reports "328 essential gene
candidates for growth in complex (LB) medium". The FBA arm here is scored on **minimal**. So the two are
not the same experiment, and the mismatch is one-directional: an amino-acid auxotroph is viable on LB and
lethal on minimal, which manufactures disagreements in exactly one of the two directions.

**`fba_false_lethal` — 3 cells: `argB`, `argC`, `dapF`.** FBA lethal on minimal, Keio viable on LB. That is
what the medium mismatch looks like, not a finding. **Do not spend compute here** without first scoring
Keio's own minimal-medium data.

**`fba_false_viable` — 9 cells: `glyA`, `ilvA`, `leuB`, `metC`, `metL`, `serA`, `serB`, `serC`, `thrA`.**
FBA calls them dispensable on minimal; Keio calls them essential **even on rich medium**. The mismatch
makes this direction *stronger*: the real cell cannot do without these genes even when fed every amino
acid, while the stoichiometric model says it does not need them even when fed none.

**And they cluster.** Three serine genes (`serA`/`serB`/`serC`), `glyA`, and two methionine genes — which
is **one-carbon metabolism**, not amino-acid supply. LB supplies amino acids; it does not supply the
one-carbon units these genes feed into purine and thymidine synthesis. That is a concrete mechanistic
hypothesis for why FBA's network permits a bypass the cell does not have, and it is what Stage 2 should
test. `leuB` already gives a partial answer at zero cost: the whole-cell model **collapses**, agreeing with
the experiment rather than with FBA.

**So the Stage 2 shortlist writes itself:** the one-carbon cluster (`serA`, `serB`, `serC`, `glyA`) plus
`metC`, `thrA` — six genes × two media. At this host's calibration (8 min/generation, 0.65 GB/generation,
parallel 3) that is **36 runs at 3 seeds ≈ 6.4 h and ~94 GB**, or 48 runs at 4 seeds ≈ 8.5 h and ~125 GB
against 171 GB free. And per the constraint above, they must be genuine **single-gene** knockouts.

### The plan, in order
1. **Fix the grid and the selection rule in writing, before Stage 1 runs.** Which genes, which media, and
   what makes a cell "interesting". Pre-registered, in the repository, like the A/B reps count.
2. **Choose the gene × environment core deliberately.** Amino-acid biosynthesis genes crossed with
   minimal / minimal+AA is the clean core, because the mechanism is unambiguous and the expected answer is
   known — which is what makes it a *test* rather than an exploration.
3. **Establish the benchmark cells first.** Score the pairs Nichols measured before scoring any that were
   not. Agreement there is what licenses the unassayed predictions; without it the extrapolation is
   unsupported.
4. **Use the project's own viability semantics, not a growth threshold invented here.** "Divided" is
   chromosome count and nothing else — `KO:rpmE` divided with translation stopped dead. Any essentiality
   call must go through the existing QC verdicts and the elongation floor, or it will repeat exactly the
   error CAPBENCH's seed case exists to catch.
5. **Report the mechanism per simulated cell**, since that is claim (b): which reactions carry flux in the
   viable condition and not the lethal one.

### What would count against the model
A gene whose conditional pattern **inverts** — lethal on rich, viable on minimal, where the measurement says
the opposite. That is a mechanism error, not a calibration one, and it would be the most informative
possible outcome.

### The trap
**Cost was the trap; the two-stage design above removes it. What replaces it is selection bias.** A grid
scored cheaply and then sampled for expensive follow-up is a selection procedure, and a selection made
after looking at the results is how a screen becomes a search for agreement. The rule that stops it is the
one in step 1: the definition of "interesting" is written down before Stage 1 is read, and the cells that
were selected but came out uninteresting are reported alongside the ones that did not.

## 4. The tRNA charging thread — why there is no plan here

> **Status 2026-09-10 — parked by decision, to be revisited.** The scope question below is still
> open and is deliberately not being answered yet. Nothing here blocks the other three plans; when it
> is picked up again, the choice among A / B / C is the first thing to settle, not the last.

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
