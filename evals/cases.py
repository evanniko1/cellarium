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
]


def by_id(ids: list[str] | None) -> list[dict]:
    if not ids:
        return CASES
    keep = set(ids)
    return [c for c in CASES if c["id"] in keep]
