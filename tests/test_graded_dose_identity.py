"""A graded knockout's DOSE is part of its identity (GRADED-1).

`_design_tag` appended the media and the elongation model but not the expression level, so every dose of a
`graded_gene_knockout` collapsed onto the full knockout's tag. MEASURED 2026-08-08: the depleting-allele
campaign's four doses of argS — expression 0.05/0.10/0.25/0.50, variant indices 6442-6445 — all produced the
label `graded_gene_knockout·KO:argS·sN`. Four rows therefore landed on the SAME (design_key, seed) cell with
ppGpp spanning 675 down to 56, a 12x range, pooled by every design-keyed tool as "four seeds of one design".

This is the failure `survey.design_tag`'s docstring already records for timelines (an upshift and a downshift
averaged together as one design) and that `mode_tag_suffix` was added to prevent for the elongation axis. It
is the same defect on a third axis.

HOW IT SURFACED, which is the part worth keeping: `lethality()` reported a DIFFERENT collapse generation
between two calls in one session — `graded_gene_knockout/KO:argS` came back as collapsing at generation 2
once and 3 another time, because whichever of the four doses won an unstable row ordering decided the answer.
A pooled cell of genuinely different experiments does not announce itself; it shows up as a number that will
not sit still.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.cellarium import factors, manifest, survey  # noqa: E402
from src.cellarium.model import Design  # noqa: E402


def _graded(level=None, index=None, gene="argS", **kw):
    p = {"target_genes": [gene]}
    if level is not None:
        p["level"] = level
    if index is not None:
        p["variant_index"] = index
    return Design(perturbation="graded_gene_knockout", condition=f"KO:{gene}", params=p, **kw)


def test_each_dose_gets_its_own_tag():
    tags = {lvl: manifest._design_tag(_graded(level=lvl)) for lvl in (2, 3, 4, 5)}
    assert len(set(tags.values())) == 4, f"doses collapsed onto the same tag: {tags}"
    assert tags[3] == "KO:argS#expr:0.1" and tags[5] == "KO:argS#expr:0.5", tags


def test_the_dose_is_recovered_from_the_variant_index_alone():
    """The index IS gene_ko_index*10 + level, which is what makes the existing rows relabellable on disk."""
    assert manifest._design_tag(_graded(index=6443)) == manifest._design_tag(_graded(level=3))
    assert manifest._design_tag(_graded(index=6445)) == "KO:argS#expr:0.5"


def test_a_non_graded_knockout_tag_is_byte_identical():
    """No existing label may move. A tag change on ~300 historical rows breaks stored-vs-derived identity."""
    plain = Design(perturbation="gene_knockout", condition="KO:argS",
                   params={"target_genes": ["argS"], "variant_index": 644})
    assert manifest._design_tag(plain) == "KO:argS"
    assert manifest._design_tag(_graded()) == "KO:argS", "a graded design with NO level must not invent one"


def test_the_tag_round_trips_through_the_factor_parser():
    """`one_factor_neighbours` selects controls from these fields; a dose it cannot see is a dose it pools."""
    f = factors.parse("graded_gene_knockout/KO:argS#expr:0.1")
    assert f["genes"] == ["argS"], "the gene was lost to the dose fragment"
    assert f["level_num"] == 0.1
    assert f["factor"] == "graded_gene_KO"
    plain = factors.parse("gene_knockout/KO:argS")
    assert plain["genes"] == ["argS"] and plain["level_num"] is None and plain["factor"] == "gene_KO"


def test_the_elongation_tag_and_the_dose_tag_compose():
    d = _graded(level=3, elongation_model="kinetic")
    tag = manifest._design_tag(d)
    assert "#expr:0.1" in tag and "#elong:kinetic" in tag, tag
    f = factors.parse("graded_gene_knockout/" + tag)
    assert f["elongation_model"] == "kinetic" and f["level_num"] == 0.1 and f["genes"] == ["argS"], f


# ---------------------------------------------------------------------------------------------------------
# The live corpus.
# ---------------------------------------------------------------------------------------------------------

def test_no_two_graded_rows_share_a_design_seed_and_depth():
    """The invariant the pooling broke, scoped to what the dose tag actually governs.

    Deliberately NOT the corpus-wide claim "(design, seed) is one run" — that is FALSE here for a legitimate
    reason. Generation depth is an analysis STRATUM, not a nuisance (see `survey.depth`), so the same design
    and seed run to 1 and to 4 generations are two different measurements and belong in one cell only after
    depth-matching. Asserting the wider invariant would fail on 18 pre-existing cells that have nothing to do
    with the dose — recorded separately in the backlog rather than absorbed into this fix.
    """
    rows, _ = survey.analysis_rows(arm="all")
    if not rows:
        pytest.skip("corpus unreadable in this environment")
    seen: dict = {}
    for r in rows:
        if r.get("perturbation") != "graded_gene_knockout":
            continue
        seen.setdefault((survey.design_key(r), r.get("seed"), r.get("generations")), []).append(r.get("id"))
    clashes = {k: v for k, v in seen.items() if len(v) > 1}
    assert not clashes, ("these graded cells hold more than one run, so every design-keyed tool averages "
                         "across different doses: %s" % clashes)


def test_the_depleting_alleles_are_four_distinct_designs():
    rows, _ = survey.analysis_rows(arm="all")
    if not rows:
        pytest.skip("corpus unreadable in this environment")
    doses = {survey.design_key(r) for r in rows
             if r.get("perturbation") == "graded_gene_knockout" and "argS" in str(r.get("label"))}
    if not doses:
        pytest.skip("no graded argS rows in this checkout")
    assert len(doses) >= 3, f"the argS dose series collapsed to {doses}"
    assert all(factors.EXPR_TAG_PREFIX in d for d in doses), doses


def test_lethality_is_deterministic_across_calls():
    """The symptom. A pooled cell shows up as a number that will not sit still, not as an error."""
    from src.cellarium import survey as s
    first = {e["design"]: (e["collapses_at_generation"], (e.get("pre_collapse") or {}).get("generation"))
             for e in s.lethality()["designs"]}
    if not first:
        pytest.skip("no collapsing designs in this checkout")
    for _ in range(3):
        again = {e["design"]: (e["collapses_at_generation"], (e.get("pre_collapse") or {}).get("generation"))
                 for e in s.lethality()["designs"]}
        assert again == first, "lethality() gave two different answers for the same corpus"
    for design, (collapse, pre) in first.items():
        assert pre == collapse - 1, f"{design}: pre-collapse {pre} is not the generation before {collapse}"
