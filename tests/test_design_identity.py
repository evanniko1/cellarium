"""Design identity — the key that decides which runs are replicates OF THE SAME EXPERIMENT.

This guards a live scientific error found in the 265-run corpus: `manifest._flat_row` persists `design.condition`
verbatim while `label` gets `manifest._design_tag(design)`, so keying analyses on the raw column MERGED designs
that are different experiments. Two real merges, both confirmed against the shipped manifest before the fix:

  * every `timeline` run stores condition=None, so an amino-acid UPSHIFT and a DOWNSHIFT both keyed to
    'timeline/None' and were averaged together as "4 seeds of one design" — opposite experiments pooled;
  * the propose path writes condition='basal' with the genes in params.target_genes, so the gltX+relA+spoT
    triple knockout keyed to 'multi_gene_knockout/basal'.

`survey.design_tag` derives identity from `label` instead, which fixes every existing row retroactively.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("CELLARIUM_MANIFEST", "data/manifest/*.parquet")

from cellarium import survey  # noqa: E402


def _row(label, perturbation, condition=None, timeline=None):
    return {"label": label, "perturbation": perturbation, "condition": condition, "timeline": timeline}


def test_two_opposite_nutrient_shifts_are_not_the_same_design():
    """The bug in its purest form: an upshift and a downshift are different experiments and must never be pooled
    as replicates. Both carry condition=None, so only the label distinguishes them."""
    down = _row("timeline·0 minimal_plus_amino_acids, 1200 minimal·s0", "timeline")
    up = _row("timeline·0 minimal, 1200 minimal_plus_amino_acids·s2", "timeline")
    assert survey.design_key(down) != survey.design_key(up)
    assert survey.design_key(down) == "timeline/0 minimal_plus_amino_acids, 1200 minimal"


def test_seeds_of_the_SAME_design_still_collapse_together():
    """The other half — the key must still group true replicates, or every seed becomes its own design."""
    a = _row("timeline·0 minimal, 1200 minimal_plus_amino_acids·s0", "timeline")
    b = _row("timeline·0 minimal, 1200 minimal_plus_amino_acids·s11", "timeline")
    assert survey.design_key(a) == survey.design_key(b)


def test_a_multi_knockout_is_identified_by_its_genes_not_by_basal():
    """The propose path stores condition='basal' with the genes in params, so keying on the raw column made a
    triple knockout indistinguishable from any other multi-KO at basal."""
    r = _row("multi_gene_knockout·KO:gltX+relA+spoT·s0", "multi_gene_knockout", condition="basal")
    assert survey.design_key(r) == "multi_gene_knockout/KO:gltX+relA+spoT"


def test_the_two_creation_paths_agree_on_identity():
    """generate.py writes condition='KO:<gene>'; the propose path writes condition='basal'. Same experiment shape,
    and after the fix both are keyed the same WAY (off the label) rather than by which code path made them."""
    gen = _row("multi_gene_knockout·KO:pfkA+pfkB·s0", "multi_gene_knockout", condition="KO:pfkA+pfkB")
    prop = _row("multi_gene_knockout·KO:pfkA+pfkB·s0", "multi_gene_knockout", condition="basal")
    assert survey.design_key(gen) == survey.design_key(prop) == "multi_gene_knockout/KO:pfkA+pfkB"


def test_a_row_with_no_label_falls_back_without_crashing():
    """Pre-label corpora (and the crash-row path) must degrade, not raise."""
    assert survey.design_tag({"perturbation": "wildtype", "condition": "basal"}) == "basal"
    assert survey.design_tag({"perturbation": "timeline", "timeline": "0 minimal"}) == "0 minimal"
    assert survey.design_tag({}) == "basal"


def test_the_survey_query_selects_label():
    """design identity now DEPENDS on `label`, so dropping it from the projection would silently reintroduce the
    merge — the failure mode would be a quiet wrong average, not an error."""
    import inspect
    src = inspect.getsource(survey._deduped_rows)
    assert '"label"' in src or "'label'" in src


def test_the_live_corpus_no_longer_pools_the_timeline_designs():
    """End-to-end against the shipped manifest. Skips cleanly where the corpus isn't present (a fresh clone)."""
    import pytest
    rows = survey._deduped_rows(survey.CHANNELS)
    if not rows or "__error__" in rows[0]:
        pytest.skip("no local manifest")
    keys = {survey.design_key(r) for r in rows if r.get("perturbation") == "timeline"}
    if not keys:
        pytest.skip("no timeline runs in this corpus")
    assert "timeline/None" not in keys, "the upshift/downshift merge is back"
    assert len(keys) >= 2, f"expected the shifts to separate, got {keys}"


# =========================================================================================================
# THE SAME DEFECT, FOUND AGAIN FOUR MONTHS LATER IN THE OTHER QUERY — 2026-10-08
#
# `test_the_survey_query_selects_label` above has guarded the survey's projection since this module was
# written. Nothing guarded the AUDIT's, and the audit's `_rows` never selected `label` at all. So every row it
# read looked like a pre-label row, `design_tag`'s fallback fired on all 369, and the merges this module
# exists to prevent happened anyway, one query along: the four graded knockdowns of a gene at 5/10/25/50%
# expression became one design, two transcript-level variants became one, and the upshift and downshift this
# file's first test pins apart were pooled again.
#
# It surfaced as two agent-reachable tools reporting different corpus sizes — 68 designs against 77 — with
# nothing saying which question either was answering. The first diagnosis blamed the elongation model, from
# comparing the two key functions over the audit's own rows. That comparison was invalid: both keys were
# being run over rows already stripped of `label`, so the survey's key was judged on input it never receives.
# The elongation model was the one symptom still visible in a projection that had removed the cause.
#
# The fix is one key function (the audit delegates) and the missing column restored. These tests pin both,
# and the counts the two tools legitimately differ on are now named rather than both called `n_designs`.
# =========================================================================================================

import pytest  # noqa: E402

from cellarium import audit, tools  # noqa: E402


@pytest.fixture(scope="module")
def coverage():
    c = tools.corpus_audit().get("coverage", {})
    if "error" in c or not c.get("designs"):
        pytest.skip("no corpus in this checkout")
    return c


@pytest.fixture(scope="module")
def survey_coverage():
    s = tools.survey_corpus().get("coverage", {})
    if not s.get("n_designs_in_corpus"):
        pytest.skip("no corpus in this checkout")
    return s


def test_the_audit_query_selects_label_too():
    """The mirror of `test_the_survey_query_selects_label`, and its absence is why this was missable.
    One query was guarded and the other was not, so the identical defect lived in the unguarded one."""
    import inspect

    src = inspect.getsource(audit._rows)
    assert "label" in src, (
        "audit._rows no longer selects `label`. Without it `survey.design_tag` falls back to the raw "
        "condition column for every row and merges designs that are different experiments.")


def test_there_is_one_grouping_function():
    """The audit must not hold its own copy of the definition. Two implementations of one concept is how the
    counts came apart, and a comment asking the next person to keep them in step is not a mechanism."""
    import inspect

    src = inspect.getsource(audit._design)
    assert "design_key" in src, "audit._design no longer delegates to survey.design_key"
    assert "mode_tag_suffix" not in src, \
        "audit._design is appending the elongation model again; the label already carries it"


def test_both_tools_agree_on_what_a_design_is(coverage, survey_coverage):
    """They may count different SETS; they may not disagree about the unit."""
    assert coverage["n_designs_present"] == survey_coverage["n_designs_in_corpus"], (
        f"the inventory sees {coverage['n_designs_present']} designs and the survey sees "
        f"{survey_coverage['n_designs_in_corpus']}; one grouping function means these cannot differ")


def test_the_two_keys_produce_identical_sets_over_the_audit_rows():
    """Stronger than the counts matching, which two different keys could do by coincidence."""
    rows = audit._rows()
    if rows and "__error__" in rows[0]:
        pytest.skip("no corpus in this checkout")
    live = audit._latest_per_run(rows)
    assert {audit._design(r) for r in live} == {survey.design_key(r) for r in live}


def test_the_counts_are_named_and_the_difference_is_stated(coverage, survey_coverage):
    """The part that is not a bug. An inventory and a ranking count different things; what was wrong was that
    both called the result `n_designs` and neither said which."""
    assert "n_designs_present" in coverage and "n_designs_with_a_passing_run" in coverage
    assert coverage["n_designs_with_a_passing_run"] <= coverage["n_designs_present"]
    note = coverage.get("counts_note") or ""
    assert "inventory" in note.lower() and "rank" in note.lower(), \
        "the audit reports two counts without saying what distinguishes them from the survey's"
    for k in ("n_designs_ranked", "n_designs_in_corpus", "n_designs_excluded"):
        assert k in survey_coverage, f"the survey no longer names {k}"
    # They do NOT sum, and that is a real residual rather than an oversight here. `n_designs_in_corpus`
    # counts over every row; `n_designs_ranked` counts within ONE comparability arm, because a ranking may
    # not pool across arms. Designs that exist, have reportable seeds and sit in another arm are in neither
    # the ranked set nor the excluded one. Nothing in the survey's output says so — the same defect one level
    # along, tracked as work-plan item 3b. What is checkable today is the containment.
    assert survey_coverage["n_designs_ranked"] <= survey_coverage["n_designs_in_corpus"]
    assert survey_coverage["n_designs_excluded"] <= survey_coverage["n_designs_in_corpus"]
    assert (survey_coverage["n_designs_ranked"] + survey_coverage["n_designs_excluded"]
            <= survey_coverage["n_designs_in_corpus"]), \
        "ranked plus excluded exceeds the corpus; the two are being counted over the same set after all"


def test_a_graded_knockdown_series_is_not_collapsed_to_one_design(coverage):
    """The concrete damage the missing column did, pinned by example and in the same spirit as the timeline
    test above. Four expression levels of one gene are four designs; merging them pools a dose-response into
    a single mean."""
    graded = [d for d in coverage["designs"] if d.startswith("graded_gene_knockout/")]
    if not graded:
        pytest.skip("no graded knockdowns in this corpus")
    with_level = [d for d in graded if "#expr:" in d]
    assert with_level, (
        "no graded knockdown carries its expression level in its design key; the dose levels have been "
        f"merged again. Keys seen: {sorted(graded)[:6]}")
