# Eval Spec: vague question → falsifiable hypothesis

Ground truth for grading the Socratic Council (`cellarium.council.deliberate`). The Council receives a *vague*
question and must emit an operationalized, falsifiable `Hypothesis`. Each case gives the canonical answer from
the seminal literature, the rivals that work had to exclude, the verified citation + a quantitative finding, the
mapping to a whole-cell *E. coli* (Covert-lab **wcEcoli**, Macklin et al. 2020 *Science*) observable, and a
two-tier rubric (minimum / stringent). The machine-readable form of these rubrics lives in `evals/cases.py`.

Citations were verified against publisher/PubMed/PMC records. Note one correction to a common mis-citation: the
2002 dual-reporter *Science* paper is **Elowitz, Levine, Siggia, Swain** — *not* "…Xie" (Xie is on Taniguchi
2010). `🔧` marks a wcEcoli scope caveat; `⚠` marks a number to treat as approximate.

## Global rubric framework

**Minimum bar (must have ALL):**
- **M1 — Named observable.** A specific measurable quantity (a count/concentration, a rate, a distribution
  statistic), not a vague "activity"/"behavior".
- **M2 — Direction + baseline.** Predicted effect *with its sign*, relative to an explicit null/control.
- **M3 — Falsifier.** A concrete result that would refute it.
- **M4 — Valid sim design.** Expressible as a runnable experiment (isogenic ensemble, a defined knockout, a
  defined media condition/shift) inside the validated envelope.

**Stringent bar (a rigorous reviewer additionally demands):**
- **S1 — Quantitative threshold.** An effect size / statistic with a number (a CV, a fold-change, a slope, a
  copy-number cutoff).
- **S2 — Named statistical test.** The estimator/test and how significance is judged.
- **S3 — Discriminating prediction.** The predicted result *distinguishes the hypothesis from ≥1 named rival*.
- **S4 — Correct decomposition/controls.** The control that isolates the claimed cause (intrinsic-vs-extrinsic;
  genetic-vs-non-genetic; ppGpp-null; resensitization; condition-dependence).

---

## Theme 1 — Intrinsic vs extrinsic noise

### Case 1.1 — "Do genetically identical cells express the same gene at the same level?"
- **Canonical (Elowitz et al. 2002).** Expression varies cell-to-cell and decomposes into **intrinsic** noise
  (stochastic transcription/translation of that gene; uncorrelated between two identically-regulated copies in a
  cell) and **extrinsic** noise (shared factors — RNAP, ribosomes, size, cycle phase — affecting both copies).
- **Measure.** Two identical reporters/cell; η²ᵢₙₜ = ⟨(c−y)²⟩/(2⟨c⟩⟨y⟩); η²ₑₓₜ = (⟨cy⟩−⟨c⟩⟨y⟩)/(⟨c⟩⟨y⟩).
- **Direction.** Both terms > 0; intrinsic ∝ 1/mean; reporters correlated across cells, scatter off-diagonal within.
- **Falsifier.** Perfect within-cell correlation → η²ᵢₙₜ≈0; zero correlation → η²ₑₓₜ≈0.
- **Rivals excluded.** (1) all measurement noise; (2) all extrinsic; (3) cryptic genetic heterogeneity.
- **Paper.** Elowitz MB, Levine AJ, Siggia ED, Swain PS, *Science* 2002, 297:1183–1186. Theory: Swain, Elowitz,
  Siggia, *PNAS* 2002, 99:12795.
- **wcEcoli.** Per-gene mRNA/protein counts across seeds; extrinsic axis = shared capacity variables (ribosomes,
  RNAP, mass, cycle phase). 🔧 no native dual reporter — instantiate two identical genes, or condition on
  ribosome/RNAP/volume as extrinsic covariates; otherwise only *total* noise is direct.

### Case 1.2 — "What makes one gene's expression noisier than another's?"
- **Canonical (Ozbudak 2002; Taniguchi 2010).** Noise set by burst kinetics: ↑translational burst size ⇒ ↑noise;
  ↑transcription at fixed mean ⇒ little effect. Genome-wide η² = a/⟨mean⟩ + b (1/mean intrinsic term + extrinsic
  floor).
- **Measure.** η² = σ²/μ² vs mean; burst size b = translation rate / mRNA decay.
- **Direction.** Noise ↑ with burst size; ↓ as ~1/mean to a floor η²≈0.1 (CV≈0.3) for copy number ≳10.
- **Falsifier.** Noise unchanged when burst size raised at fixed mean; or no floor (1/mean forever).
- **Rivals excluded.** (1) noise = f(amount only); (2) purely intrinsic (no floor); (3) mRNA predicts protein
  per cell (Taniguchi: single-cell mRNA–protein correlation ≈ 0).
- **Papers.** Ozbudak et al., *Nat Genet* 2002, 31:69 (*B. subtilis*); Taniguchi et al., *Science* 2010,
  329:533.
- **wcEcoli.** Protein/mRNA counts across seeds → η²(mean) scaling; burst size from explicit rate params.

## Theme 2 — Bistability / persistence / bet-hedging

### Case 2.1 — "Why do some bacteria survive antibiotics without becoming resistant?"
- **Canonical (Balaban et al. 2004).** A pre-existing slow/non-growing **persister** subpopulation survives;
  cells switch stochastically & reversibly; survivors regrow **sensitive** (phenotypic, not genetic).
- **Measure.** Single-cell growth rate over time; switch rates a (normal→persister), b (persister→normal);
  persister frequency; MIC of regrowth.
- **Direction.** Minority ~10⁻⁶–10⁻⁵ arrest & survive; regrowth MIC unchanged. ⚠ Type II a~10⁻⁶ h⁻¹, b~0.1 h⁻¹
  (order-of-magnitude).
- **Falsifier.** Regrowth MIC elevated (heritable) → resistance not persistence; or unimodal growth (no switch).
- **Rivals excluded.** (1) genetic resistance; (2) uniform tolerance; (3) drug-induced damage only.
- **Paper.** Balaban NQ et al., *Science* 2004, 305:1622.
- **wcEcoli.** Single-cell growth-rate/division-time distribution across seeds; bimodal/heavy-slow-tail is the
  signature. 🔧 no antibiotic killing / TA-switch / MIC — grade the *operationalization* (two-state switch,
  resensitization control, growth-rate bimodality); killing arm out-of-scope.

### Case 2.2 — "Can it help a population for some cells to grow slowly / be 'prepared'?"
- **Canonical (Kussell & Leibler 2005; Novick & Weiner 1957).** In a fluctuating environment, stochastic
  phenotype switching (bet-hedging) can raise long-term (time-averaged) growth vs sense-and-respond when the
  environment changes slowly relative to sensing cost; optimal switch rate ≈ environmental rate.
- **Measure.** Long-term growth rate Λ vs switch rate & environmental frequency; subpopulation fractions.
- **Direction.** Switching Λ > committed Λ under fluctuation + costly sensing; argmax switch ≈ env rate.
- **Falsifier.** Non-switching always ≥ any switching Λ across regimes.
- **Rivals excluded.** (1) always sense-and-respond; (2) always commit to majority-optimal; (3) diversity is
  non-adaptive noise.
- **Papers.** Kussell & Leibler, *Science* 2005, 309:2075; Novick & Weiner, *PNAS* 1957, 43:553.
- **wcEcoli.** Ensemble over media epochs; Λ = time-averaged growth over a shift schedule; phenotype e.g. lac
  induction state. 🔧 single-lineage + limited shift repertoire; needs an external harness. Novick–Weiner
  all-or-none lac bistability is a good sim target if inducer is representable.

## Theme 3 — Non-genetic individuality (chemotaxis)

### Case 3.1 — "Do genetically identical cells behave differently?"
- **Canonical (Spudich & Koshland 1976).** Isogenic cells show stable, reproducible behavioral **individuality**
  (tumbling frequency / run length), persistent over a cell's lifetime — non-genetic, from Poisson fluctuation in
  small numbers of signalling ("generator") molecules.
- **Measure.** Per-cell tumble frequency / run length / adaptation time; between-cell CV and within-cell
  temporal autocorrelation.
- **Direction.** Between-cell variance > within-cell variance and persistent; traceable to a low-copy signalling
  protein (CheR/CheB/CheY-P).
- **Falsifier.** Uniform behavior (CV≈within-cell noise); or memoryless (within=between variance).
- **Rivals excluded.** (1) genetic; (2) fast measurement noise; (3) microenvironment.
- **Paper.** Spudich JL, Koshland DE Jr, *Nature* 1976, 262:467.
- **wcEcoli.** Per-cell Che-protein copy numbers across seeds; **between-seed CV of a low-copy signalling
  protein** is the direct correlate. 🔧 no motility/run-tumble output — map to the upstream low-copy-protein
  variance, flag the motility layer out-of-scope.

## Theme 4 — Stringent response / ppGpp & growth control

### Case 4.1 — "How does a cell decide how many ribosomes to make in a given medium?"
- **Canonical (Scott et al. 2010 — growth laws).** Ribosomal proteome fraction φ_R rises **linearly with growth
  rate λ**: φ_R = φ_R,0 + λ/κ_t (nutrient modulation); φ_R rises as λ falls under translation inhibition (2nd
  law).
- **Measure.** Ribosome / RNA-protein mass fraction vs steady-state λ across media; slope κ_t.
- **Direction.** Positive linear φ_R–λ under nutrient quality; negative under translation inhibition.
- **Falsifier.** φ_R constant across media, or falls with λ under nutrient modulation.
- **Rivals excluded.** (1) nutrient-identity-specific ribosome content; (2) fixed ribosome level; (3) one-way
  ribosome→growth only.
- **Papers.** Scott et al., *Science* 2010, 330:1099; mechanism Scott et al., *MSB* 2014, 10:747.
- **wcEcoli.** ✅ best-matched: active ribosome counts / ribosomal-protein & RNA/protein fraction and growth rate
  are first-class; regress φ_R on λ across nutrient conditions.

### Case 4.2 — "What does a cell do when it suddenly runs out of amino acids?"
- **Canonical (stringent response; Cashel; Potrykus & Cashel 2008).** AA starvation → uncharged tRNA in A-site →
  RelA makes (p)ppGpp → represses rRNA/ribosome synthesis, throttles growth. A ppGpp-null (relA/spoT) strain is
  "relaxed" (keeps making rRNA).
- **Measure.** ppGpp conc; rRNA/ribosome synthesis; growth rate; charged-tRNA fraction — pre vs post downshift.
- **Direction.** Downshift → ppGpp ↑ sharply (s–min) → rRNA/ribosome synthesis & growth ↓.
- **Falsifier.** No ppGpp rise on downshift, or rRNA unchanged despite a ppGpp spike.
- **Rivals excluded.** (1) passive building-block depletion (refuted by relaxed mutant); (2) ribosome-number sets
  rate; (3) ppGpp only at stationary phase.
- **Papers.** Potrykus & Cashel, *Annu Rev Microbiol* 2008, 62:35; Cashel & Gallant, *Nature* 1969.
- **wcEcoli.** ✅ strong: ppGpp conc, RelA/SpoT, rRNA synthesis, growth rate; design = amino-acid downshift; WT
  vs relA/spoT KO for the relaxed phenotype.

## Theme 5 — Knockout dispensability / essentiality

### Case 5.1 — "Which genes can *E. coli* live without?"
- **Canonical (Baba 2006; Gerdes 2003).** Only a minority are essential (single deletion abolishes growth on
  rich medium); most are dispensable; essentiality is condition-dependent (expands on minimal medium).
- **Measure.** Post-KO growth rate/viability vs WT in a defined medium; classify essential vs dispensable.
- **Direction.** ~300–620 essential of ~4300; the vast majority of single KOs viable.
- **Falsifier.** Most single deletions lethal (essential ≫ 50%); or a literature-dispensable gene lethal in the
  matched condition (and vice versa).
- **Rivals excluded.** (1) most genes individually essential (Keio: 3985/4288 deletable); (2) context-free
  essentiality (set grows on minimal).
- **Papers.** Baba et al., *MSB* 2006, 2:2006.0008 (303 candidate essential); Gerdes et al., *J Bacteriol* 2003,
  185:5673 (620 essential / 3126 dispensable). The two disagree by method/medium — a built-in discriminator.
- **wcEcoli.** ✅ set a gene's expression to zero, read post-KO growth/viability across seeds. 🔧 known repo
  finding: FBA single-deletion screens can be **under-sensitive** — reward a stated viability threshold + medium
  and anticipation of false-negative essential calls.

## Theme 6 — Diauxie / catabolite repression

### Case 6.1 — "How do bacteria choose between two sugars in the same flask?"
- **Canonical (Monod 1949).** Preferred sugar (glucose) consumed first; second only after — **diauxic** growth
  with an inter-phase lag while the second sugar's enzymes induce (glucose represses them: catabolite
  repression).
- **Measure.** Growth rate vs time; carbon-source depletion order; induction timing of second-sugar genes (lac).
- **Direction.** Sequential use; measurable lag; second-sugar genes repressed until preferred exhausted.
- **Falsifier.** Simultaneous co-utilization, no lag, no repression.
- **Rivals excluded.** (1) co-utilization; (2) lag = starvation death (refuted: growth resumes on induction).
- **Papers.** Monod J, *Annu Rev Microbiol* 1949, 3:371; New et al., *PLoS Biol* 2014, 12:e1001764.
- **wcEcoli.** Growth over time + catabolic-enzyme counts under a two-sugar/shift condition. 🔧 limited native
  multi-sugar/lactose support; a glucose→alt-carbon shift may need an external harness; full lac diauxie may be
  out-of-scope.

### Case 6.2 — "When the preferred sugar runs out, do all cells switch at the same time?"
- **Canonical (Solopova et al. 2014).** No — at the diauxic shift the isogenic population **splits**: a
  responsive growing subpopulation + an arrested one; the responsive fraction is set by catabolite repression &
  ppGpp — a partly stochastic bet-hedge.
- **Measure.** Single-cell lag-time distribution; fraction resuming growth; dependence on CcpA/CRP & ppGpp.
- **Direction.** Bimodal lag-time distribution; responsive fraction shifts with repression strength / ppGpp.
- **Falsifier.** Unimodal single lag, no arrested subpopulation.
- **Rivals excluded.** (1) uniform adaptation; (2) genetic split; (3) arrested = dead (refuted: regulatory &
  reversible).
- **Paper.** Solopova A et al., *PNAS* 2014, 111:7427 (*L. lactis*).
- **wcEcoli.** Per-seed lag-time / growth-resumption distribution across a sugar-depletion shift; per-cell ppGpp
  as covariate. 🔧 needs a large ensemble across a shift; diauxie machinery limited — grade the design, flag
  scope.

## Appendix — wcEcoli observable cheat-sheet

| Concept | wcEcoli observable | Native? |
|---|---|---|
| Per-gene expression / noise | mRNA & protein counts across seeds | ✅ |
| Intrinsic vs extrinsic split | 2 identical synthetic genes, or condition on ribosome/RNAP/volume | 🔧 partial |
| Growth rate / division time | instantaneous growth rate, generation time | ✅ |
| Ribosome content / growth law | active ribosome count, ribosomal-protein & RNA/protein fraction vs λ | ✅ |
| ppGpp / stringent response | ppGpp conc, RelA/SpoT, rRNA synthesis | ✅ |
| Metabolic flux | FBA reaction fluxes | ✅ |
| Gene knockout viability | expression→0; post-KO growth | ✅ (FBA screen under-sensitive) |
| Persistence / killing / MIC | — | ❌ out of scope |
| Motility / run-tumble | map to low-copy Che-protein variance | ❌ output layer out of scope |
| Multi-sugar diauxie / lactose | limited; needs external media-shift harness | 🔧 partial |
| Population bimodality / bet-hedging | ensemble of seeds → distribution statistics | ✅ (needs many seeds) |

### Flags
- Citation fix: 2002 dual-reporter = Elowitz, Levine, Siggia, Swain (not "…Xie"; Xie is on Taniguchi 2010).
- Ozbudak 2002 = *B. subtilis*; Solopova 2014 = *L. lactis* — principle transfers, organism differs.
- Persistence killing (2.1), motility output (3.1), full lactose diauxie (6.1/6.2) exceed base-wcEcoli execution
  — strongest for grading *operationalization*, with the wet-lab readout flagged out-of-scope.
