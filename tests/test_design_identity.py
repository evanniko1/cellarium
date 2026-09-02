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
