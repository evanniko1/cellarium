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
             doc="Welch's t across seeds; |t|>=2 rejects H0 (rigor.disconfirm)."),
    TestSpec("slope_ci", "linear_relation", "fit_relation", "slope_ci_excludes_0",
             aliases=("ols slope", "regression slope", "slope 95% ci", "slope ci", "slope confidence interval",
                      "slope excludes 0", "linear regression", "regression coefficient", "slope inference"),
             precondition=">=3 designs carrying both channels",
             doc="OLS slope with t-based 95% CI + p (rigor.fit_relation, DS-1)."),
    TestSpec("bimodality_bc", "distribution_shape", "bimodality", "bimodal_suggested",
             aliases=("bimodality", "bimodal", "two modes", "two regimes", "sarle", "bimodality coefficient",
                      "dip test", "test for bimodality", "multimodal"),
             precondition=">=4 pooled values",
             caveat="Sarle's bimodality coefficient (BC>0.555), NOT Hartigan's exact dip test.",
             doc="tools.bimodality; a stdlib BC heuristic + best 2-cluster split (M-1)."),
    TestSpec("bh_fdr_movers", "multiple_testing", "top_movers", "n_significant_fdr10",
             aliases=("bh-fdr", "benjamini", "benjamini-hochberg", "false discovery rate", "fdr correction",
                      "multiple testing correction", "adjusted p-value", "q-value threshold"),
             precondition="two designs with proteome/mRNA layers",
             doc="Benjamini-Hochberg FDR over per-species log2FC (top_movers)."),
    TestSpec("power_mde", "power_analysis", "power_check", "min_detectable_effect",
             aliases=("power analysis", "statistical power", "minimum detectable effect", "underpowered",
                      "power calculation", "sample size calculation", "seeds needed"),
             precondition="a channel with observed replicate CV in the corpus",
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


def by_id(test_id: str) -> TestSpec | None:
    return next((t for t in TEST_REGISTRY if t.test_id == test_id), None)


def supported_ids() -> list[str]:
    """The controlled vocabulary the Council is ALLOWED to name (executable tests) — used to build the enum a
    future structured falsifier field selects from (brief step 2)."""
    return [t.test_id for t in TEST_REGISTRY if t.supported]


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
