"""Machine-readable eval cases — the ground truth from evals/EVAL_SPEC.md.

Each case is a vague question plus the literature-derived rubric the Council's Hypothesis is graded against.
`min_criteria` is the pass floor (a usable falsifiable hypothesis); `stringent_criteria` is what a rigorous
reviewer additionally demands (quantitative threshold, named test, discriminating-from-rivals, the isolating
control). `expected_observables` are the wcEcoli dial labels a good operationalization would land on;
`scope_note` flags readouts the base model cannot execute (grade the operationalization, not the run).
"""

from __future__ import annotations

CASES = [
    {
        "id": "1.1", "theme": "intrinsic vs extrinsic noise",
        "question": "Do genetically identical cells express the same gene at the same level?",
        "canonical": ("Elowitz 2002: expression varies cell-to-cell and decomposes into intrinsic noise "
                      "(stochastic transcription/translation of that gene) and extrinsic noise (shared factors: "
                      "ribosomes, RNAP, size, cycle phase)."),
        "expected_observables": ["protein_mass", "rna_mass", "ribosome_conc", "per-gene protein/mRNA counts across seeds"],
        "expected_rivals": ["all measurement noise", "all extrinsic/global state", "cryptic genetic heterogeneity"],
        "min_criteria": [
            "M1: names a specific per-cell expression observable (a protein/mRNA count or a mass channel), not 'behavior'",
            "M2: predicts cell-to-cell variance > 0 relative to an explicit isogenic baseline",
            "M3: states a concrete falsifier (e.g. variance indistinguishable from technical/replicate noise)",
            "M4: design is an isogenic replicate ensemble (wildtype, many seeds), in-envelope",
        ],
        "stringent_criteria": [
            "S1: gives a quantitative dispersion statistic with a threshold (a CV or Fano, or intrinsic ~1/mean scaling)",
            "S2: names the statistic/test and how significance is judged (e.g. variance decomposition with CIs / Welch t)",
            "S3: the predicted result discriminates intrinsic-vs-extrinsic from the pure-measurement-noise rival",
            "S4: includes the isolating control — the intrinsic/extrinsic decomposition (dual identical genes, or "
            "conditioning on shared ribosome/RNAP/mass covariates)",
        ],
        "scope_note": "no native dual reporter; the intrinsic/extrinsic split must use twin genes or covariate conditioning",
    },
    {
        "id": "3.1", "theme": "non-genetic individuality",
        "question": "Do genetically identical cells behave differently?",
        "canonical": ("Spudich & Koshland 1976: isogenic cells show stable, persistent behavioral individuality "
                      "from Poisson fluctuation in small numbers of a low-copy signalling protein."),
        "expected_observables": ["per-cell low-copy signalling protein counts across seeds (CheR/CheB/CheY)",
                                 "growth_rate", "protein_mass"],
        "expected_rivals": ["genetic differences", "fast measurement noise", "microenvironment differences"],
        "min_criteria": [
            "M1: names a specific per-cell quantity (a low-copy protein count or growth rate), not 'behavior'",
            "M2: predicts persistent between-cell variance > 0 vs an isogenic baseline",
            "M3: states a falsifier (uniform behavior, or between-cell variance == within-cell noise)",
            "M4: design is an isogenic replicate ensemble, in-envelope",
        ],
        "stringent_criteria": [
            "S1: gives a between-cell CV and/or predicts CV proportional to 1/sqrt(copy number)",
            "S2: names a variance-partition / autocorrelation test separating persistent individuality from fast noise",
            "S3: the predicted result discriminates non-genetic individuality from the genetic and measurement-noise rivals",
            "S4: ties the variance to a specific low-copy protein pool (the isolating cause)",
        ],
        "scope_note": "no motility/run-tumble output; map to the upstream low-copy-protein variance",
    },
    {
        "id": "1.2", "theme": "noise vs burst kinetics",
        "question": "What makes one gene's expression noisier than another's?",
        "canonical": ("Ozbudak 2002 / Taniguchi 2010: noise is set by translational burst size; genome-wide "
                      "noise = a/mean + extrinsic floor (~0.1)."),
        "expected_observables": ["per-gene protein counts across seeds", "protein_mass", "translation/mRNA-decay rate params"],
        "expected_rivals": ["noise is a function of expression amount only", "purely intrinsic (no floor)",
                            "mRNA level predicts protein per cell"],
        "min_criteria": [
            "M1: names protein-count noise (a dispersion statistic) and its dependence on a controllable factor",
            "M2: predicts the sign (noise up with burst size; noise down with mean) vs a mean-only null",
            "M3: states a falsifier (noise unchanged at matched mean when burst raised; or no floor)",
            "M4: design tunes translation/transcription at matched mean across an ensemble, in-envelope",
        ],
        "stringent_criteria": [
            "S1: states the eta^2 = a/mean + b form with a numeric floor (~0.1 / CV~0.3)",
            "S2: specifies fitting the noise-mean curve with CIs and a test for a nonzero asymptote",
            "S3: the prediction discriminates burst-driven from abundance-only and 1/mean-forever rivals",
            "S4: holds protein mean fixed while varying burst size (the isolating control)",
        ],
        "scope_note": "",
    },
    {
        "id": "4.1", "theme": "growth laws / ribosome allocation",
        "question": "How does a cell decide how many ribosomes to make in a given medium?",
        "canonical": ("Scott 2010 growth laws: ribosomal proteome fraction rises linearly with growth rate under "
                      "nutrient modulation; rises as growth falls under translation inhibition."),
        "expected_observables": ["ribosome_conc", "protein_mass", "rna_mass", "growth_rate"],
        "expected_rivals": ["nutrient-identity-specific ribosome content", "fixed ribosome level",
                            "one-way ribosome->growth only"],
        "min_criteria": [
            "M1: names ribosome/ribosomal fraction and growth rate as the observables",
            "M2: predicts a positive ribosome-fraction vs growth-rate relation vs a 'constant content' null",
            "M3: states a falsifier (flat or negative relation under nutrient modulation)",
            "M4: design is steady-state sims across >=2 media conditions, in-envelope",
        ],
        "stringent_criteria": [
            "S1: states the linear form with a slope/intercept and a target fit quality",
            "S2: specifies a regression with a CI on the slope across media",
            "S3: the prediction discriminates the growth-law from nutrient-specific and one-way rivals",
            "S4: includes the translation-inhibition arm to establish bidirectional coupling",
        ],
        "scope_note": "",
    },
    {
        "id": "4.2", "theme": "stringent response / ppGpp",
        "question": "What does a cell do when it suddenly runs out of amino acids?",
        "canonical": ("Stringent response: amino-acid downshift -> RelA makes ppGpp -> ppGpp spikes and represses "
                      "rRNA/ribosome synthesis and growth; a ppGpp-null (relA/spoT) strain is relaxed."),
        "expected_observables": ["ppgpp_conc", "ribosome_conc", "growth_rate", "fraction_trna_charged", "rela_conc"],
        "expected_rivals": ["passive building-block depletion", "ribosome number sets the rate",
                            "ppGpp acts only at stationary phase"],
        "min_criteria": [
            "M1: names ppGpp concentration and rRNA/ribosome or growth rate as observables",
            "M2: predicts ppGpp up and ribosome/growth down on downshift vs a steady-state baseline",
            "M3: states a falsifier (no ppGpp rise, or ribosome synthesis unchanged despite a spike)",
            "M4: design is an amino-acid downshift, in-envelope",
        ],
        "stringent_criteria": [
            "S1: gives the sign and rough magnitude/timescale of the ppGpp spike and ribosome drop",
            "S2: specifies a pre/post (time-resolved) comparison statistic",
            "S3: the prediction discriminates the active-ppGpp-signal from the passive-depletion rival",
            "S4: includes the ppGpp-null (relA/spoT knockout) relaxed-phenotype control to prove causality",
        ],
        "scope_note": "",
    },
    {
        "id": "5.1", "theme": "knockout essentiality",
        "question": "Which genes can E. coli live without?",
        "canonical": ("Baba 2006 / Gerdes 2003: only a minority of genes are essential (single deletion abolishes "
                      "growth); most are dispensable; essentiality is condition-dependent."),
        "expected_observables": ["growth_rate", "dry_mass", "post-KO viability across seeds"],
        "expected_rivals": ["most genes are individually essential", "essentiality is context-free"],
        "min_criteria": [
            "M1: names post-KO growth rate/viability vs wild-type as the observable",
            "M2: predicts most single knockouts viable, a minority lethal, vs a baseline",
            "M3: states a falsifier (a wrong essential/dispensable call vs literature in the matched medium)",
            "M4: design is a single-gene knockout (or screen) across seeds, in-envelope",
        ],
        "stringent_criteria": [
            "S1: states an essential-fraction range (~300-620 of ~4300) and a viability/growth-rate cutoff",
            "S2: specifies a per-gene test across seeds with a defined threshold",
            "S3: the prediction discriminates condition-dependent from context-free essentiality",
            "S4: specifies the medium (rich vs minimal) because essentiality is condition-dependent",
        ],
        "scope_note": "FBA single-deletion screens can be under-sensitive (false-negative essential calls)",
    },
    {
        "id": "6.1", "theme": "diauxie / catabolite repression",
        "question": "How do bacteria choose between two sugars in the same flask?",
        "canonical": ("Monod 1949 diauxie: preferred sugar consumed first; the second only after a lag while its "
                      "enzymes induce (glucose represses them: catabolite repression)."),
        "expected_observables": ["growth_rate", "per-gene catabolic enzyme counts", "protein_mass"],
        "expected_rivals": ["simultaneous co-utilization", "the lag is starvation death not regulated induction"],
        "min_criteria": [
            "M1: names sequential growth/sugar depletion or catabolic-enzyme induction timing as observables",
            "M2: predicts glucose-first, second-sugar-later with a lag vs a co-utilization null",
            "M3: states a falsifier (simultaneous use, no lag, no repression)",
            "M4: design is a two-carbon or glucose-ramp condition, in-envelope (NOT a mid-run carbon-source switch)",
        ],
        "stringent_criteria": [
            "S1: quantifies the lag duration and the repression fold-change of second-sugar genes in phase 1",
            "S2: specifies detection of two exponential phases and induction timing",
            "S3: the prediction discriminates sequential+catabolite-repression from co-utilization and starvation-death",
            "S4: names the second-sugar catabolic genes whose repression/induction is tracked",
        ],
        "scope_note": "limited native multi-sugar/lactose support; a mid-run carbon-source switch is out of envelope",
    },
    {
        "id": "6.2", "theme": "bet-hedging at the diauxic shift",
        "question": "When the preferred sugar runs out, do all cells switch to the second sugar at the same time?",
        "canonical": ("Solopova 2014: the isogenic population splits at the diauxic shift into a responsive "
                      "growing subpopulation and an arrested one; the fraction is set by catabolite repression and "
                      "ppGpp — a partly stochastic bet-hedge."),
        "expected_observables": ["growth_rate distribution across seeds", "ppgpp_conc", "single-cell lag time"],
        "expected_rivals": ["uniform metabolic adaptation", "the split is genetic", "the arrested fraction is dead"],
        "min_criteria": [
            "M1: names a single-cell lag time / fraction resuming growth as the observable",
            "M2: predicts a non-growing subpopulation vs an 'everyone adapts' null",
            "M3: states a falsifier (unimodal lag, no arrested subpopulation)",
            "M4: design is a shift across an isogenic ensemble (many seeds), in-envelope",
        ],
        "stringent_criteria": [
            "S1: quantifies the responsive fraction and its dependence on a repression/ppGpp perturbation",
            "S2: specifies a bimodality/mixture test on the lag-time distribution",
            "S3: the prediction discriminates a regulated bet-hedge from uniform adaptation and a dead subpopulation",
            "S4: includes the ppGpp/catabolite-repression perturbation arm as the isolating control",
        ],
        "scope_note": "needs a large ensemble across a shift; diauxie machinery limited",
    },
    {
        "id": "2.1", "theme": "persistence / antibiotic survival",
        "question": "Why do some bacteria survive antibiotics without becoming resistant?",
        "canonical": ("Balaban 2004: a clonal population contains a pre-existing slow/non-growing PERSISTER "
                      "subpopulation that survives antibiotic; cells switch stochastically and reversibly between "
                      "normal-growth and persister states; regrown survivors are as sensitive as the parent "
                      "(phenotypic, not genetic)."),
        "expected_observables": ["single-cell growth_rate / division-time distribution across seeds (bimodal / "
                                 "heavy slow tail)", "switching rates", "growth_rate"],
        "expected_rivals": ["acquired genetic resistance", "uniform tolerance (all cells equally survive)",
                            "drug-induced damage only (no pre-existing subpopulation)"],
        "min_criteria": [
            "M1: names a subpopulation defined by single-cell growth rate / division time as the observable",
            "M2: predicts a slow/arrested minority vs the null of a unimodal isogenic population",
            "M3: states a falsifier (unimodal growth distribution, i.e. no slow subpopulation)",
            "M4: design is an isogenic replicate ensemble (many seeds) measuring the growth-rate distribution, in-envelope",
        ],
        "stringent_criteria": [
            "S1: states the persister frequency order (~1e-5 to 1e-6) and/or two switching rates (normal<->persister)",
            "S2: specifies a bimodality/mixture test on the single-cell growth-rate distribution and a switching-rate estimator",
            "S3: the prediction discriminates a phenotypic switch from genetic resistance and from uniform tolerance",
            "S4: includes the resensitization logic (regrown survivors are sensitive) that distinguishes persistence from resistance",
        ],
        "scope_note": ("no antibiotic killing / MIC / toxin-antitoxin switch in the base model — map the claim to "
                       "the growth-rate bimodality proxy across seeds; the killing and resensitization arms are "
                       "out-of-scope and should be stated as auxiliary assumptions"),
    },
    {
        "id": "2.2", "theme": "bet-hedging in fluctuating environments",
        "question": "Can it ever help a population for some cells to grow slowly or stay 'prepared' for a change?",
        "canonical": ("Kussell & Leibler 2005 (roots in Novick & Weiner 1957): in a fluctuating environment a "
                      "clonal population can raise its long-term (time-averaged) growth rate by stochastic "
                      "phenotype switching (bet-hedging) rather than sense-and-respond, when the environment "
                      "changes infrequently relative to sensing cost; the optimal switching rate matches the "
                      "environmental statistics."),
        "expected_observables": ["long-term / time-averaged growth_rate across a media-shift schedule",
                                 "subpopulation fractions in each phenotype", "growth_rate"],
        "expected_rivals": ["always sense-and-respond", "always commit to the majority-optimal phenotype",
                            "diversity is unavoidable noise, not adaptive"],
        "min_criteria": [
            "M1: names long-term / time-averaged population growth rate as the observable",
            "M2: predicts a switching population outgrows a committed population under fluctuation, vs that null",
            "M3: states a falsifier (a non-switching/committed population always matches or beats any switching one)",
            "M4: design is repeated in-envelope media shifts across an isogenic ensemble (NOT a mid-run carbon-source switch)",
        ],
        "stringent_criteria": [
            "S1: states the 'optimal switch rate ~ environmental rate' relation quantitatively",
            "S2: computes long-term growth as a log-growth average with CIs over seeds and sweeps switch/environment rates",
            "S3: the prediction discriminates bet-hedging from sense-and-respond and from committed strategies as a function of environmental timescale / sensing cost",
            "S4: includes the fluctuation-rate (and/or sensing-cost) sweep as the isolating control",
        ],
        "scope_note": ("single-lineage model with a limited media-shift repertoire; realizing a 'fluctuating "
                       "environment x switching-rate sweep' needs an external harness — grade the design and "
                       "state the harness dependence as an auxiliary assumption"),
    },

    # ---- expansion set (v2): 16 further literature-grounded cases, broadening from noise/individuality into
    #      growth physiology, the ppGpp axis, knockout regimes, and allocation. Each maps to a real dial label or
    #      validated perturbation; scope_note flags where the base model can't execute the native readout. ----
    {
        "id": "4.3", "theme": "ppGpp sets ribosome content (clamp dose-response)",
        "question": "If a cell is forced to hold a high level of the alarmone ppGpp, what happens to its ribosomes and growth?",
        "canonical": ("Potrykus & Cashel 2008 / Zhu & Dai 2019: ppGpp is the master negative regulator of ribosome "
                      "synthesis — raising ppGpp represses rRNA/ribosomal-protein synthesis, lowering ribosome "
                      "content and growth rate; the relation is graded (dose-dependent), not all-or-none."),
        "expected_observables": ["ppgpp_conc", "ribosome_conc", "rna_mass", "growth_rate"],
        "expected_rivals": ["ppGpp acts only in stationary phase", "ribosome level is fixed regardless of ppGpp",
                            "ppGpp changes growth without changing ribosome content"],
        "min_criteria": [
            "M1: names ribosome content (ribosome_conc / rRNA) and growth rate as the observables under a set ppGpp level",
            "M2: predicts higher clamped ppGpp -> lower ribosome content and lower growth vs a basal-ppGpp baseline",
            "M3: states a falsifier (ribosome content or growth unchanged as ppGpp is clamped up)",
            "M4: design clamps ppgpp_conc to >=2 multiples of basal across an ensemble, in-envelope",
        ],
        "stringent_criteria": [
            "S1: gives a monotone dose-response (ribosome_conc / growth falling with clamp multiple) with a rough slope",
            "S2: specifies a regression / trend test across >=3 clamp levels with CIs",
            "S3: the prediction discriminates a graded ppGpp-ribosome control from fixed-ribosome and stationary-only rivals",
            "S4: includes >=3 clamp levels (the dose axis) as the isolating design, not a single on/off contrast",
        ],
        "scope_note": "ppgpp_conc clamp is a validated perturbation; ribosome_conc and growth_rate are native channels",
    },
    {
        "id": "4.4", "theme": "nutritional upshift / ribosome ramp",
        "question": "When a cell is suddenly given a richer medium, what changes first — its growth or its ribosome-making machinery?",
        "canonical": ("Kjeldgaard, Maaloe & Schaechter 1958 (shift-up) / Bremer & Dennis: on nutritional upshift the "
                      "cell ramps rRNA/ribosome synthesis rapidly, and macromolecular composition (RNA fraction) "
                      "adjusts toward the new steady state ahead of a fully re-set division rate."),
        "expected_observables": ["ribosome_conc", "rna_mass", "protein_mass", "growth_rate"],
        "expected_rivals": ["everything scales up together instantly", "growth rate resets before ribosome synthesis",
                            "composition is medium-independent"],
        "min_criteria": [
            "M1: names ribosome/RNA content and growth rate across an upshift as the observables",
            "M2: predicts ribosome/RNA synthesis rises on upshift toward the richer-medium level vs the pre-shift baseline",
            "M3: states a falsifier (no rise in ribosome/RNA content after the upshift)",
            "M4: design is an in-envelope media upshift (timeline), NOT a carbon-source switch",
        ],
        "stringent_criteria": [
            "S1: gives the sign and rough timescale of the ribosome/RNA-fraction rise relative to the growth adjustment",
            "S2: specifies a time-resolved pre/post comparison of the RNA fraction with CIs",
            "S3: the prediction discriminates a ribosome-led adjustment from instantaneous-uniform-scaling",
            "S4: tracks the RNA/protein composition ratio (not just absolute mass) as the isolating readout",
        ],
        "scope_note": "map to an in-envelope nutrient upshift; a mid-run carbon-source switch is out of envelope",
    },
    {
        "id": "4.5", "theme": "amino-acid supplementation raises growth",
        "question": "Does giving a cell its amino acids ready-made let it grow faster than making them itself?",
        "canonical": ("Schaechter, Maaloe & Kjeldgaard 1958 / Neidhardt: supplying amino acids (richer medium) "
                      "raises growth rate and shifts proteome allocation from biosynthesis toward ribosomes; growth "
                      "rate is set by the medium's nutritional quality."),
        "expected_observables": ["growth_rate", "ribosome_conc", "protein_mass"],
        "expected_rivals": ["growth rate is medium-independent", "supplementation lowers growth (repression cost)",
                            "only ribosome number, not medium, sets the rate"],
        "min_criteria": [
            "M1: names growth rate (and ideally ribosome/proteome fraction) as the observable under supplementation",
            "M2: predicts amino-acid supplementation raises growth rate vs an unsupplemented baseline",
            "M3: states a falsifier (growth unchanged or lower when amino acids are supplied)",
            "M4: design compares supplemented vs basal medium (condition / amino_acid_shift), in-envelope",
        ],
        "stringent_criteria": [
            "S1: gives a rough growth-rate fold-change and a direction for the ribosome/proteome reallocation",
            "S2: specifies a mean-difference test on growth_rate across seeds with a threshold",
            "S3: the prediction discriminates nutrient-quality control from a medium-independent or cost rival",
            "S4: pairs the growth change with the proteome-reallocation readout (ribosome fraction) as the isolating control",
        ],
        "scope_note": "amino_acid_shift / condition are in-envelope; growth_rate and ribosome_conc are native",
    },
    {
        "id": "4.6", "theme": "translation elongation vs charged-tRNA",
        "question": "Why does each ribosome add amino acids more slowly when a cell grows slowly?",
        "canonical": ("Dai et al. 2016 (Nat Microbiol): translation elongation rate declines at slow growth, tracking "
                      "a fall in the charged/aminoacylated-tRNA supply relative to demand; ppGpp and tRNA charging "
                      "co-set the elongation rate."),
        "expected_observables": ["fraction_trna_charged", "growth_rate", "ribosome_conc", "ppgpp_conc"],
        "expected_rivals": ["elongation rate is constant across growth rates", "ribosome number alone sets output",
                            "charging is always saturating"],
        "min_criteria": [
            "M1: names the charged-tRNA fraction and growth rate as the observables",
            "M2: predicts charged-tRNA fraction falls (or tracks) with slower growth vs a fast-growth baseline",
            "M3: states a falsifier (charged-tRNA fraction flat across growth rates)",
            "M4: design spans >=2 growth conditions across an ensemble, in-envelope",
        ],
        "stringent_criteria": [
            "S1: gives the sign and rough magnitude of the charging change across the growth range",
            "S2: specifies a trend/regression of fraction_trna_charged vs growth_rate with CIs",
            "S3: the prediction discriminates a charging-limited elongation from a constant-rate or ribosome-only rival",
            "S4: conditions on ribosome content so the charging effect is isolated from ribosome number",
        ],
        "scope_note": "fraction_trna_charged and growth_rate are native channels",
    },
    {
        "id": "5.2", "theme": "aminoacyl-tRNA-synthetase knockout catastrophe",
        "question": "What happens to a cell that loses an aminoacyl-tRNA synthetase entirely?",
        "canonical": ("Aminoacyl-tRNA synthetases are essential; Choi & Covert 2023 (NAR, doi:10.1093/nar/gkad435) "
                      "fit aaRS kcats ~7.6x above in-vitro and call aaRS perturbation catastrophic — a full KO "
                      "collapses tRNA charging and halts translation (not a reroute); the biological expectation is "
                      "a stringent (ppGpp-up) response before death."),
        "expected_observables": ["fraction_trna_charged", "ribosome_conc", "division_rate", "ppgpp_conc"],
        "expected_rivals": ["metabolic reroute compensates (viable)", "immediate gen-0 death",
                            "ppGpp rises and rescues growth"],
        "min_criteria": [
            "M1: names charged-tRNA / ribosome / viability (division_rate) as the observable of an aaRS KO",
            "M2: predicts translational collapse and loss of viability vs a wildtype baseline (not a neutral reroute)",
            "M3: states a falsifier (aaRS KO grows like wildtype, or charging unaffected)",
            "M4: design is a single aaRS gene_knockout across seeds at sufficient generation depth, in-envelope",
        ],
        "stringent_criteria": [
            "S1: gives the crash regime and its rough generation timing (runs on the inherited charged-tRNA buffer, then fails)",
            "S2: specifies a per-seed viability/charging test with a threshold at a stated generation depth",
            "S3: the prediction discriminates a translational-collapse from a metabolic-reroute and a rescue rival",
            "S4: names the ppGpp/stringent expectation as an auxiliary prediction whose FAILURE in-model would itself be informative",
        ],
        "scope_note": ("aaRS KO is in-envelope; the biological ppGpp-up stringent response is a documented place the base "
                       "model may DISAGREE (it can crash by translational-buffer exhaustion instead) — grade the "
                       "operationalization, and treat model-vs-literature disagreement as a finding, not a grading miss"),
    },
    {
        "id": "5.3", "theme": "metabolic knockout reroute (dispensable)",
        "question": "If you delete a single central-metabolism enzyme, does the cell die, slow down, or just reroute around it?",
        "canonical": ("Baba 2006 (Keio) / Fraenkel: most single central-metabolic-enzyme deletions are dispensable on "
                      "glucose minimal — flux reroutes through alternative pathways with little or no growth defect; "
                      "essentiality is the minority and is condition-dependent."),
        "expected_observables": ["growth_rate", "reaction_flux (rerouted pathway)", "dry_mass"],
        "expected_rivals": ["single metabolic KOs are usually lethal", "KO always slows growth proportionally",
                            "reroute is impossible without regulation change"],
        "min_criteria": [
            "M1: names post-KO growth rate (vs wildtype) as the observable for a single metabolic-enzyme deletion",
            "M2: predicts little/no growth defect (reroute) for a typical dispensable enzyme vs a wildtype baseline",
            "M3: states a falsifier (the KO abolishes growth, i.e. behaves essential)",
            "M4: design is a single-gene metabolic knockout across seeds, in-envelope",
        ],
        "stringent_criteria": [
            "S1: gives a growth-defect bound (e.g. <10-20% vs wildtype) distinguishing reroute from a real defect",
            "S2: specifies a mean-difference test on growth_rate vs wildtype with a threshold",
            "S3: the prediction discriminates FBA-style reroute from lethal and proportional-slowdown rivals",
            "S4: names the alternative flux route (or the FBA objective) whose activation is the isolating evidence",
        ],
        "scope_note": "gene_knockout is in-envelope; reaction fluxes need raw simOut (HF download or regenerate)",
    },
    {
        "id": "5.4", "theme": "essential-gene knockout (LPS biosynthesis)",
        "question": "Is lpxC one of the genes E. coli cannot live without?",
        "canonical": ("Beall & Lutkenhaus 1987 / Onishi 1996: lpxC (envA) catalyzes the first committed, "
                      "rate-limiting step of lipid A / LPS biosynthesis and is essential in E. coli — its loss "
                      "abolishes viability (an outer-membrane biogenesis defect)."),
        "expected_observables": ["division_rate", "growth_rate", "dry_mass", "post-KO viability across seeds"],
        "expected_rivals": ["lpxC is dispensable (reroute)", "the defect is a slow-growth phenotype, not lethality",
                            "essentiality is unconditional / medium-independent"],
        "min_criteria": [
            "M1: names post-KO viability (division_rate) vs wildtype as the observable",
            "M2: predicts loss of viability for the lpxC KO vs a wildtype baseline",
            "M3: states a falsifier (the lpxC KO remains viable / divides like wildtype)",
            "M4: design is a single-gene knockout (lpxC) across seeds, in-envelope",
        ],
        "stringent_criteria": [
            "S1: states a viability/division cutoff distinguishing lethal from slow-growth",
            "S2: specifies a per-seed division_rate test against wildtype with a threshold",
            "S3: the prediction discriminates essentiality from a dispensable-reroute and a mild-defect rival",
            "S4: notes that a base model without LPS-biogenesis coupling may UNDER-predict lethality — an auxiliary that the run tests",
        ],
        "scope_note": ("gene_knockout + division_rate are native; whether LPS-biogenesis lethality is mechanistically "
                       "simulated is checked downstream (mechanistic_scope) — model-vs-literature disagreement is a finding"),
    },
    {
        "id": "5.5", "theme": "core-machinery knockout, generation-dependent crash",
        "question": "If a cell loses its RNA polymerase, does it die immediately or coast for a while?",
        "canonical": ("RNA polymerase (rpoB) is essential (Baba 2006). But a freshly-made knockout inherits a large "
                      "RNAP pool, so loss of viability is generation-dependent: the lineage can divide for several "
                      "generations on the inherited reserve before collapsing (a timing effect, not immediate death)."),
        "expected_observables": ["division_rate at increasing generation depth", "ribosome_conc", "protein_mass"],
        "expected_rivals": ["immediate gen-0 death", "fully viable (dispensable)", "crash timing is depth-independent"],
        "min_criteria": [
            "M1: names viability (division_rate) as a function of generation depth for the machinery KO",
            "M2: predicts eventual loss of viability (essential) but with a depth-dependent delay vs wildtype",
            "M3: states a falsifier (viable indefinitely, or dies instantly at gen 0 regardless of depth)",
            "M4: design is the machinery gene_knockout across seeds at >=2 generation depths, in-envelope",
        ],
        "stringent_criteria": [
            "S1: gives the rough crash-depth (survives few gens on inherited pool, then fails) with a viability cutoff",
            "S2: specifies a division_rate-vs-depth comparison across seeds with a threshold",
            "S3: the prediction discriminates inherited-pool-limited timing from immediate-death and dispensable rivals",
            "S4: reads viability at a stated depth (not growth rate at shallow depth, which hides the defect) as the isolating control",
        ],
        "scope_note": "gene_knockout + division_rate are native; crash timing tracks the inherited-pool size (model characteristic)",
    },
    {
        "id": "5.6", "theme": "ppGpp-null relaxed phenotype (causal control)",
        "question": "If a cell cannot make ppGpp at all, how does it react to running out of amino acids?",
        "canonical": ("Cashel / Potrykus & Cashel 2008: a (p)ppGpp-null strain (relA spoT / 'ppGpp0') is RELAXED — on "
                      "amino-acid downshift it fails to shut down rRNA/ribosome synthesis and does not mount the "
                      "stringent response; this is the causal control proving ppGpp mediates the shutdown."),
        "expected_observables": ["ppgpp_conc", "rela_conc", "ribosome_conc", "growth_rate"],
        "expected_rivals": ["shutdown is ppGpp-independent (passive depletion)", "the null still represses rRNA",
                            "ppGpp matters only in stationary phase"],
        "min_criteria": [
            "M1: names ppGpp level and rRNA/ribosome (or growth) response on downshift as the observables",
            "M2: predicts the ppGpp-null fails to raise ppGpp and fails to repress ribosome synthesis vs a wildtype downshift",
            "M3: states a falsifier (the null still shows a ppGpp spike or still represses ribosomes)",
            "M4: design pairs a wildtype downshift with a relA/spoT-knockout downshift, in-envelope",
        ],
        "stringent_criteria": [
            "S1: gives the contrast (wildtype ppGpp-up + ribosome-down vs null flat) with rough magnitudes",
            "S2: specifies a paired pre/post comparison across both strains with CIs",
            "S3: the prediction discriminates active ppGpp signalling from passive building-block depletion",
            "S4: the ppGpp-null arm IS the isolating causal control (loss-of-function abolishes the response)",
        ],
        "scope_note": ("amino-acid downshift is in-envelope; a relA/spoT double-KO relaxed phenotype may or may not be "
                       "mechanistically reproduced — grade the operationalization and flag disagreement as a finding"),
    },
    {
        "id": "7.1", "theme": "macromolecular composition vs growth rate",
        "question": "Do fast-growing cells and slow-growing cells have the same mix of RNA and protein inside them?",
        "canonical": ("Schaechter, Maaloe & Kjeldgaard 1958 / Bremer & Dennis: at steady state the RNA/protein ratio "
                      "rises with growth rate (more ribosomes at fast growth) — a growth-rate-dependent, "
                      "medium-invariant composition law."),
        "expected_observables": ["rna_mass", "protein_mass", "ribosome_conc", "growth_rate"],
        "expected_rivals": ["composition is growth-rate-independent", "protein fraction rises with growth",
                            "composition depends on nutrient identity, not growth rate"],
        "min_criteria": [
            "M1: names the RNA/protein ratio (or ribosome fraction) and growth rate as the observables",
            "M2: predicts RNA/protein rises with growth rate vs a 'constant composition' null",
            "M3: states a falsifier (flat or inverted RNA/protein-vs-growth relation)",
            "M4: design is steady-state sims across >=2 growth conditions, in-envelope",
        ],
        "stringent_criteria": [
            "S1: states the positive relation with a rough slope/intercept over the growth range",
            "S2: specifies a regression of RNA/protein vs growth_rate with a CI on the slope",
            "S3: the prediction discriminates a growth-rate law from nutrient-identity and constant-composition rivals",
            "S4: collapses different media onto the single growth-rate axis (the isolating control that it's rate, not identity)",
        ],
        "scope_note": "rna_mass, protein_mass, growth_rate are native channels across conditions",
    },
    {
        "id": "7.2", "theme": "overflow metabolism (aerobic acetate excretion)",
        "question": "Why does a well-fed, oxygen-rich E. coli still throw away carbon as acetate?",
        "canonical": ("Basan et al. 2015 (Nature) / Holms 1996: at high glucose uptake / fast growth E. coli excretes "
                      "acetate aerobically (overflow metabolism) — a proteome-efficiency tradeoff between fermentation "
                      "and respiration, with acetate flux rising above a growth-rate threshold."),
        "expected_observables": ["exchange_flux (acetate)", "growth_rate", "fba_objective", "reaction_flux"],
        "expected_rivals": ["all carbon is respired (no overflow)", "acetate is only excreted anaerobically",
                            "acetate flux is growth-rate-independent"],
        "min_criteria": [
            "M1: names acetate exchange flux (and growth rate) as the observable",
            "M2: predicts acetate excretion rising with glucose uptake / growth rate vs a low-growth baseline",
            "M3: states a falsifier (no acetate excretion at fast aerobic growth)",
            "M4: design contrasts high vs low carbon-uptake conditions across seeds, in-envelope",
        ],
        "stringent_criteria": [
            "S1: gives a growth-rate threshold above which acetate flux turns on, with a rough slope",
            "S2: specifies a flux comparison across conditions with a threshold/CI",
            "S3: the prediction discriminates a proteome-efficiency overflow from pure-respiration and anaerobic-only rivals",
            "S4: reads the acetate exchange flux specifically (not just growth) as the isolating readout",
        ],
        "scope_note": "exchange/reaction fluxes need raw simOut (HF download or regenerate); grade the operationalization onto the flux channel",
    },
    {
        "id": "8.1", "theme": "rRNA operon dosage caps translational capacity",
        "question": "Does deleting some of the cell's ribosomal-RNA operons put a ceiling on how fast it can grow?",
        "canonical": ("Condon et al. 1995 / Asai et al. 1999 (PNAS): E. coli has seven rRNA operons; deleting some "
                      "lowers rRNA/ribosome-synthesis capacity and reduces the maximum achievable growth rate "
                      "(a translational-capacity ceiling), with partial compensation at low operon counts."),
        "expected_observables": ["ribosome_conc", "rna_mass", "growth_rate"],
        "expected_rivals": ["operon copy number doesn't matter (full compensation)", "growth is unaffected until zero operons",
                            "the effect is on protein, not ribosome capacity"],
        "min_criteria": [
            "M1: names ribosome content / max growth rate vs operon dosage as the observable",
            "M2: predicts reduced operon dosage lowers ribosome capacity and max growth vs full-complement baseline",
            "M3: states a falsifier (growth/ribosome unchanged as operons are deleted)",
            "M4: design is an rrna_operon_knockout dose series across seeds, in-envelope",
        ],
        "stringent_criteria": [
            "S1: gives a graded dose-response (growth/ribosome falling with fewer operons) with a rough slope",
            "S2: specifies a trend test across >=2 operon-dosage levels with CIs",
            "S3: the prediction discriminates a capacity ceiling from full-compensation and all-or-none rivals",
            "S4: uses >=2 dosage levels (the dose axis) as the isolating design",
        ],
        "scope_note": "rrna_operon_knockout is a validated graded perturbation; ribosome_conc and growth_rate are native",
    },
    {
        "id": "9.1", "theme": "cell-size homeostasis (adder)",
        "question": "How does a cell keep its size steady across generations without measuring how big it is?",
        "canonical": ("Taheri-Araghi et al. 2015 (Curr Biol) / Campos 2014 / Amir 2014: E. coli follows an 'adder' — "
                      "each cell adds a roughly constant size increment per division cycle regardless of birth size, "
                      "which passively corrects size deviations over generations."),
        "expected_observables": ["dry_mass / cell_mass at birth and division across seeds", "division_rate"],
        "expected_rivals": ["sizer (divide at a fixed absolute size)", "timer (divide after a fixed time)",
                            "size diverges (no homeostasis)"],
        "min_criteria": [
            "M1: names added mass per cycle (division mass minus birth mass) as the observable across cells",
            "M2: predicts a roughly constant added increment independent of birth size vs a sizer/timer null",
            "M3: states a falsifier (added mass strongly depends on birth size, i.e. sizer or timer)",
            "M4: design is an isogenic ensemble tracking per-cycle birth/division mass, in-envelope",
        ],
        "stringent_criteria": [
            "S1: predicts an added-mass-vs-birth-size slope near zero (adder), with a tolerance",
            "S2: specifies the regression of added mass on birth size with a CI on the slope",
            "S3: the prediction discriminates adder from sizer (slope -1) and timer rivals",
            "S4: conditions on birth size (the isolating variable) rather than only reporting mean size",
        ],
        "scope_note": ("size homeostasis emerges from the model's mass-triggered division; per-cycle birth/division mass "
                       "is recoverable from the trajectory — grade the operationalization onto the mass channels"),
    },
    {
        "id": "10.1", "theme": "gene dosage / replication position",
        "question": "Are genes near where DNA replication starts expressed more than genes near where it ends?",
        "canonical": ("Klumpp, Zhang & Hwa 2009 (Cell) / Bremer & Dennis: at fast growth, overlapping replication "
                      "rounds raise the copy number of origin-proximal genes relative to terminus-proximal ones, so "
                      "gene expression carries a growth-rate-dependent position (dosage) bias."),
        "expected_observables": ["per-gene mRNA/protein counts vs chromosomal position across seeds", "rna_mass", "growth_rate"],
        "expected_rivals": ["expression is position-independent", "the bias is fixed (growth-rate-independent)",
                            "differences are pure transcription regulation, not dosage"],
        "min_criteria": [
            "M1: names per-gene expression as a function of chromosomal (ori-ter) position as the observable",
            "M2: predicts origin-proximal genes higher than terminus-proximal at fast growth vs a position-flat null",
            "M3: states a falsifier (no position gradient in expression)",
            "M4: design compares expression by position across >=1 growth condition (ideally 2), in-envelope",
        ],
        "stringent_criteria": [
            "S1: predicts the gradient strengthens with growth rate, with a rough ori/ter ratio",
            "S2: specifies a regression of expression vs position (and vs growth rate) with CIs",
            "S3: the prediction discriminates a replication-dosage bias from position-flat and regulation-only rivals",
            "S4: contrasts fast vs slow growth (the isolating control that the bias is dosage, not regulation)",
        ],
        "scope_note": "requires positional gene-copy modelling; if unavailable, grade the operationalization and state the dependence as an auxiliary",
    },
    {
        "id": "11.1", "theme": "proteome allocation under carbon limitation",
        "question": "When carbon is scarce, how does a cell re-budget which proteins it makes?",
        "canonical": ("Hui et al. 2015 (Mol Syst Biol) / Scott 2010: proteome allocation obeys linear tradeoffs — "
                      "under carbon (catabolic) limitation the ribosomal sector shrinks and the catabolic/metabolic "
                      "sector grows, with growth rate tracking the ribosomal fraction."),
        "expected_observables": ["ribosome_conc", "per-sector protein counts (catabolic vs ribosomal)", "growth_rate", "protein_mass"],
        "expected_rivals": ["allocation is fixed regardless of limitation", "all sectors scale together",
                            "growth is set by total protein, not the ribosomal fraction"],
        "min_criteria": [
            "M1: names ribosomal vs catabolic proteome fraction (or ribosome_conc) and growth rate as the observables",
            "M2: predicts carbon limitation shrinks the ribosomal sector / raises catabolic proteins vs a rich baseline",
            "M3: states a falsifier (allocation unchanged under limitation)",
            "M4: design contrasts carbon-limited vs rich conditions across seeds, in-envelope",
        ],
        "stringent_criteria": [
            "S1: states the linear tradeoff (ribosomal fraction falling with limitation) with a rough slope vs growth",
            "S2: specifies a sector-fraction comparison across conditions with CIs",
            "S3: the prediction discriminates a reallocation tradeoff from fixed-allocation and uniform-scaling rivals",
            "S4: collapses conditions onto the growth-rate axis (ribosomal fraction ∝ growth) as the isolating law",
        ],
        "scope_note": "ribosome_conc + growth_rate are native; sector-resolved protein counts come from per-species reads",
    },
]


def by_id(ids: list[str] | None) -> list[dict]:
    if not ids:
        return CASES
    keep = set(ids)
    return [c for c in CASES if c["id"] in keep]
