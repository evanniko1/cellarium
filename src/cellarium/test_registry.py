"""The Test Registry — the single source of truth mapping the statistical TESTS a Council falsifier can name to
the EXECUTABLE tool that runs each one (audit M-1). It is what the self-harness (harness.py) checks a falsifier's
decision rule against: a named test with a `tool` is executable; a named test with `tool=None` is a known
capability GAP the harness files to BACKLOG.md for a developer to close (implement the tool) or rule out (tighten
the Council so it stops naming it). Kept in sync with tools.TOOLS by a CI invariant (tests/test_harness.py).

Design (from the SOTA brief, wf_f7f85832): a CONTROLLED VOCABULARY. Each TestSpec carries `aliases` — the
paraphrases the Council tends to use — so a free-text decision_rule matches DETERMINISTICALLY without an LLM
parse (Gorilla-style structural match; zero-false-positive floor). The known-UNSUPPORTED rows (tool=None) are a
curated vocabulary of recognized tests we deliberately don't have yet, so naming one is caught as a precise,
self-documenting gap rather than a vague miss. Generic terms live only on the SUPPORTED spec (e.g. "dip test"
-> bimodality_bc, which we DO have); the unsupported rows carry only distinctive terms (e.g. "Hartigan's dip"),
so "an unsupported alias matched" reliably means the Council asked for that specific missing capability.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TestSpec:
    test_id: str
    family: str
    tool: str | None                 # the executing tool in tools.TOOLS; None => a known capability GAP
    reads_field: str = ""            # the tool-output field a decision rule reads (the executability contract)
    aliases: tuple[str, ...] = ()    # phrases the Council uses for this test (matched case/punctuation-insensitively)
    precondition: str = ""           # human-readable executability precondition
    caveat: str = ""                 # e.g. "Sarle's BC, not Hartigan's dip"
    example: str = ""                # DD-TCV-1(c): a decision-rule FORM the proposer prompt shows (SUPPORTED specs)
    doc: str = ""

    @property
    def supported(self) -> bool:
        return self.tool is not None


# Supported rows first (tool set), then the curated known-UNSUPPORTED rows (tool=None). Order matters only for
# stable display; matching is by alias, not position.
TEST_REGISTRY: tuple[TestSpec, ...] = (
    TestSpec("welch_disconfirm", "two_sample_location", "disconfirm", "welch_t",
             aliases=("welch", "welch t", "welch's t", "two-sample t", "two sample t", "t-test", "t test",
                      "difference of means", "unpaired t", "student t"),
             precondition=">=2 replicates per side",
             example="Welch t of the channel, target vs reference across seeds; reject H0 if the two-sided p<0.05 at the Welch df",
             doc="Welch's t across seeds; two-sided p<0.05 at the Welch–Satterthwaite df rejects H0 (rigor.disconfirm)."),
    TestSpec("slope_ci", "linear_relation", "fit_relation", "slope_ci_excludes_0",
             aliases=("ols slope", "regression slope", "slope 95% ci", "slope ci", "slope confidence interval",
                      "slope excludes 0", "linear regression", "regression coefficient", "slope inference"),
             precondition=">=3 designs carrying both channels",
             example="OLS slope of Y on X across >=3 conditions; reject H0 if the slope 95% CI excludes 0",
             doc="OLS slope with t-based 95% CI + p (rigor.fit_relation, DS-1)."),
    TestSpec("bimodality_bc", "distribution_shape", "bimodality", "bimodal_suggested",
             aliases=("bimodality", "bimodal", "two modes", "two regimes", "sarle", "bimodality coefficient",
                      "dip test", "test for bimodality", "multimodal"),
             precondition=">=4 pooled values",
             caveat="Sarle's bimodality coefficient (BC>0.555), NOT Hartigan's exact dip test.",
             example="Sarle's bimodality coefficient over the pooled per-seed values; reject unimodal if BC>0.555",
             doc="tools.bimodality; a stdlib BC heuristic + best 2-cluster split (M-1)."),
    TestSpec("bh_fdr_movers", "multiple_testing", "top_movers", "n_significant_fdr10",
             aliases=("bh-fdr", "benjamini", "benjamini-hochberg", "false discovery rate", "fdr correction",
                      "multiple testing correction", "adjusted p-value", "q-value threshold"),
             precondition="two designs with proteome/mRNA layers",
             example="Benjamini-Hochberg FDR over per-species log2FC; a real response needs n_significant_fdr10 > 0",
             doc="Benjamini-Hochberg FDR over per-species log2FC (top_movers)."),
    TestSpec("power_mde", "power_analysis", "power_check", "min_detectable_effect",
             aliases=("power analysis", "statistical power", "minimum detectable effect", "underpowered",
                      "power calculation", "sample size calculation", "seeds needed"),
             precondition="a channel with observed replicate CV in the corpus",
             example="power_check: read a null as equivalence only if the effect exceeds the min detectable effect at n",
             doc="Corpus-CV-based min detectable effect / seeds-needed (power_check)."),

    # --- known-UNSUPPORTED: recognized tests we deliberately don't have a tool for (tool=None => GAP) ---------
    TestSpec("hartigan_dip", "distribution_shape", None,
             aliases=("hartigan", "hartigan's dip", "hartigan dip", "exact dip test", "dip statistic",
                      "dip test p-value", "bootstrap dip"),
             caveat="We have Sarle's BC (bimodality_bc), not Hartigan's exact dip + bootstrap unimodal null.",
             doc="Hartigan & Hartigan dip test with a bootstrap null — not implemented."),
    TestSpec("mann_whitney", "two_sample_location", None,
             aliases=("mann-whitney", "mann whitney", "wilcoxon rank-sum", "wilcoxon rank sum", "rank-sum test",
                      "u test", "nonparametric two-sample"),
             caveat="We have Welch's t (welch_disconfirm), not a rank-based nonparametric test.",
             doc="Mann-Whitney U / Wilcoxon rank-sum — not implemented."),
    TestSpec("ks_test", "distribution_compare", None,
             aliases=("kolmogorov", "kolmogorov-smirnov", "ks test", "k-s test", "empirical cdf test",
                      "distribution comparison test"),
             caveat="No CDF-comparison test; disconfirm compares means only.",
             doc="Kolmogorov-Smirnov two-sample distribution test — not implemented."),
    TestSpec("anova_f", "multi_group_location", None,
             aliases=("anova", "analysis of variance", "one-way anova", "omnibus f-test", "f test across groups"),
             caveat="No omnibus multi-group test; disconfirm is pairwise.",
             doc="One-way ANOVA / omnibus F across >2 designs — not implemented."),
    TestSpec("mixture_model", "distribution_shape", None,
             aliases=("gaussian mixture", "mixture model", "two-component fit", "em clustering", "latent class"),
             caveat="bimodality gives a best 2-cluster split, not a fitted mixture with component weights.",
             doc="Gaussian-mixture / EM latent-component fit — not implemented."),
    TestSpec("rank_correlation", "association", None,
             aliases=("spearman", "spearman's rho", "kendall", "kendall's tau", "rank correlation"),
             caveat="fit_relation gives Pearson r; no rank-based correlation.",
             doc="Spearman rho / Kendall tau rank correlation — not implemented."),
)


# --- tool ACCOUNTING: the reverse invariant (every tool is classified, so Council-visibility can't drift) --------
# The Council's operationalization vocabulary is exactly the SUPPORTED TestSpecs above (a falsifier may NAME one; the
# proposer prompt + the falsifier schema enum are both built from supported_ids(), so a new TestSpec auto-exposes to
# the Council). Every OTHER tool in tools.TOOLS is a Cellwright-side analysis / read / action tool the Council never
# names — and MUST NOT, because the Council is BLIND to grounded results: tools that operate on real per-seed
# evidence (disconfirm-family verification like robustness_check, the viability_surrogate prediction, the
# generate_designs enumeration) are things Cellwright runs AFTER the Council, not vocabulary the blind Council picks.
#
# forward invariant (validate_against_tools): every named test points at a real tool — catches a TestSpec drifting.
# REVERSE invariant (unclassified_tools): every real tool is accounted for — either a TestSpec's `tool`, or listed
# here. A newly-added tool that is NEITHER trips the CI exhaustiveness check (tests/test_harness.py), forcing a
# conscious one-line classification at add-time: "is this a new falsifier test the Council should NAME (-> a
# TestSpec), or a Cellwright analysis tool (-> here)?" So Council-visibility is settled when a tool lands, not when
# someone remembers to ask.
ANALYSIS_ONLY_TOOLS: frozenset[str] = frozenset({
    # corpus survey / read / drill-down
    "survey_corpus", "differential", "list_results", "design_space", "read_series", "read_raw_series",
    "scan_series", "scan_overview", "variance_band", "raw_available", "download_raw", "list_species", "read_species",
    "exchange_flux", "regulon_response", "data_availability", "chart",
    # grounded verdicts / diagnostics / verification (operate on real evidence -> Cellwright-side, Council is blind)
    "viability", "mechanistic_scope", "metabolic_essentiality", "model_validation", "reroute_diagnosis",
    "provenance", "coverage_check", "corpus_audit", "prune_candidates", "robustness_check", "viability_surrogate",
    # independent FBA cross-check family
    "fba_growth", "fba_gene_knockout", "fba_flux", "fba_essentiality_panel", "fba_synthetic_lethal",
    "fba_gene_deletion", "fba_sensitivity", "fba_qc", "rnaseq_concordance",
    # design / experiment proposal + guardrails (act on the world, not falsifier tests)
    "design_panel", "generate_designs", "check_feasibility", "vet_hypothesis", "screen_design", "screen_phenotype",
    "run_experiment", "propose_experiment", "propose_experiments", "revise_experiment",
    # literature / publication skills bridge
    "use_skill", "web_get",
})


def registered_tool_names() -> set[str]:
    """The tools a SUPPORTED TestSpec executes — the Council-nameable set."""
    return {t.tool for t in TEST_REGISTRY if t.tool}


def unclassified_tools(tool_names) -> list[str]:
    """CI exhaustiveness invariant (reverse of validate_against_tools): every tool must be either a Council-nameable
    test (a TestSpec's tool) or explicitly ANALYSIS_ONLY. Returns tools that are NEITHER — a non-empty result means a
    new tool was added without deciding whether the Council should see it. Empty = ok."""
    known = registered_tool_names() | ANALYSIS_ONLY_TOOLS
    return sorted(n for n in set(tool_names) if n not in known)


def by_id(test_id: str) -> TestSpec | None:
    return next((t for t in TEST_REGISTRY if t.test_id == test_id), None)


def supported_ids() -> list[str]:
    """The controlled vocabulary the Council is ALLOWED to name (executable tests) — used to build the enum a
    future structured falsifier field selects from (brief step 2)."""
    return [t.test_id for t in TEST_REGISTRY if t.supported]


def proposer_guidance() -> str:
    """DD-TCV-1(c): the proposer prompt's decision-rule EXAMPLES + 'not available' note, GENERATED from this registry
    so the prompt can't drift from the enum (the hardcoded prose used to encode thresholds + which tests are absent
    as a second, un-synced copy — e.g. it kept coaching '|t|>=2' after disconfirm went df-aware). Example forms come
    from each SUPPORTED spec's `example`; the avoid-note is the caveat on each recognized-but-UNSUPPORTED (tool=None)
    spec, which already names the supported alternative."""
    examples = [t.example for t in TEST_REGISTRY if t.supported and t.example]
    caveats = [t.caveat for t in TEST_REGISTRY if not t.supported and t.caveat]
    parts = []
    if examples:
        parts.append("Example decision-rule FORMS (bind one to your channels): "
                     + "; or ".join(f"'{e}'" for e in examples) + ".")
    if caveats:
        parts.append("Name ONLY a test the platform provides; recognized but NOT available (do not name these): "
                     + " ".join(caveats))
    return " ".join(parts)


def _norm(s: str) -> str:
    """Lowercase, punctuation -> spaces, space-padded — so alias matching is word-bounded and robust to
    hyphens/apostrophes/casing ('Welch's t-test' -> ' welch s t test ')."""
    return " " + re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip() + " "


def match(text: str) -> list[TestSpec]:
    """Every TestSpec whose alias appears in `text` (deterministic, case/punctuation-insensitive, word-bounded)."""
    nt = _norm(text)
    hits = []
    for spec in TEST_REGISTRY:
        if any(_norm(a) in nt for a in spec.aliases):
            hits.append(spec)
    return hits


def validate_against_tools(tool_names: set[str]) -> list[str]:
    """CI invariant: every SUPPORTED TestSpec must point at a tool that actually exists in tools.TOOLS, so the
    detector's model of capability can't silently drift from the executor. Returns a list of problems (empty=ok)."""
    problems = []
    for t in TEST_REGISTRY:
        if t.supported and t.tool not in tool_names:
            problems.append(f"{t.test_id}: tool '{t.tool}' not in TOOLS")
        if t.supported and not t.reads_field:
            problems.append(f"{t.test_id}: supported test has no reads_field (executability contract)")
    return problems
