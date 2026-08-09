"""Two designs that differ in WHAT WAS RUN must not share a label (IDENTITY-1).

This project has now found the same defect three times, each on a different axis, each caught only after it
had already corrupted an analysis:

  * the ELONGATION MODEL — pooled a real measurement with an algebraic identity across an 86-wide channel
  * the GRADED DOSE (GRADED-1) — pooled four argS expression levels spanning 12x in ppGpp as "seeds"
  * the MEDIA TIMELINE (DUP-1) — pooled an amino-acid downshift with a constant medium

Every instance was the same edit in the same function, `manifest._design_tag`, and every instance was found by
noticing a number that would not sit still rather than by anything failing. Three of one shape is a pattern,
so the axes are DECLARED (`manifest.IDENTITY_AXES` / `NOT_IDENTITY_AXES`) and this file turns the declaration
into guards.

THE GUARD IS STRUCTURAL, not a checklist. A new field on `Design`, or a new params key appearing in the
corpus, fails `test_every_field_is_classified` until someone puts it in one of the two dicts — the same
mechanism by which `test_registry.ANALYSIS_ONLY_TOOLS` caught `propose_rebuild` the moment it was added. It
converts "remember to update the tag" into "remember to classify the field", which is smaller to forget and
loud when forgotten.

It cannot catch an axis nobody has conceived of. It caught a FOURTH on the day it was written: `target_tfs`
was treated as identity by `launch._match_key` and by `biosecurity.screen` but not by `_design_tag`, so two TF
perturbations of different factors would have shared a label. Latent — no perturbation uses it yet — which is
the point: closed on a quiet axis instead of after a campaign.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.cellarium import manifest, survey  # noqa: E402
from src.cellarium.model import Design  # noqa: E402


def _corpus_params_keys() -> set:
    """params keys the corpus actually exercises, read from the launch queue and the design files on disk.

    The manifest has no `params` column, so the keys are gathered where they ARE recorded. A key that nothing
    has ever used cannot be classified from evidence, and demanding it would be busywork.
    """
    import json
    keys: set = set()
    for p in list(Path("runs").glob("*/*/*/design.json"))[:400]:
        try:
            keys |= set((json.loads(p.read_text(encoding="utf-8")) or {}).get("params") or {})
        except Exception:
            continue
    try:
        for r in json.loads(Path("data/launch_queue.json").read_text(encoding="utf-8")):
            # A parca_rebuild is NOT a design — it carries a `design` block only so the queue readers and the
            # interface have something to render (PARCA-3). Its params (`operons`, `retype_cistrons`, `cpus`,
            # `reason`) determine what a KNOWLEDGE BASE contains, not what a simulation ran, and `_design_tag`
            # is never asked to distinguish two rebuilds. Classifying them as design axes would be filing a
            # different kind of thing under this rule.
            if r.get("kind") == "parca_rebuild":
                continue
            keys |= set(((r.get("design") or {}).get("params")) or {})
    except Exception:
        pass
    return keys


# ---------------------------------------------------------------------------------------------------------
# (1) Nothing may be unclassified.
# ---------------------------------------------------------------------------------------------------------

def test_every_design_field_is_classified():
    """A field added to `Design` must be declared identity-bearing or explicitly not, before it can be used."""
    fields = set(Design.model_fields)
    classified = set(manifest.IDENTITY_AXES) | set(manifest.NOT_IDENTITY_AXES)
    unclassified = sorted(f for f in fields if f != "params" and f not in classified)
    assert not unclassified, (
        "these `Design` fields are neither identity-bearing nor explicitly excluded: %s. Add each to "
        "manifest.IDENTITY_AXES (with a probe in identity_probes) or NOT_IDENTITY_AXES, with the reason. "
        "Leaving one unclassified is how the elongation model, the graded dose and the media timeline each "
        "went missing from the design tag." % unclassified)


def test_every_params_key_in_use_is_classified():
    keys = _corpus_params_keys()
    if not keys:
        pytest.skip("no design.json or queue params available in this checkout")
    classified = {k.split(".", 1)[1] for k in
                  set(manifest.IDENTITY_AXES) | set(manifest.NOT_IDENTITY_AXES) if k.startswith("params.")}
    unclassified = sorted(k for k in keys if k not in classified)
    assert not unclassified, (
        "these params keys are used by real designs but classified nowhere: %s" % unclassified)


def test_the_two_classifications_do_not_overlap():
    both = set(manifest.IDENTITY_AXES) & set(manifest.NOT_IDENTITY_AXES)
    assert not both, "an axis cannot be both identity-bearing and not: %s" % sorted(both)
    for axis, why in {**manifest.IDENTITY_AXES, **manifest.NOT_IDENTITY_AXES}.items():
        assert why and len(why) > 20, f"{axis} is classified with no usable reason: {why!r}"


# ---------------------------------------------------------------------------------------------------------
# (2) Every declared identity axis must actually separate.
# ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("axis,a,b", manifest.identity_probes())
def test_each_identity_axis_produces_a_different_tag(axis, a, b):
    """THE property all three defects violated: differ on this axis, differ in identity."""
    ta, tb = manifest.design_identity(a), manifest.design_identity(b)
    assert ta != tb, (
        f"two designs differing only in {axis!r} produce the SAME identity {ta} — every analysis will average "
        f"them as seeds of one design. This is the elongation-model / graded-dose / media-timeline defect on a "
        f"{'new' if axis not in ('elongation_model',) else 'known'} axis; fix manifest._design_tag.")


def test_a_declared_axis_without_a_probe_raises():
    """The declaration must not be able to outrun what checks it."""
    real = dict(manifest.IDENTITY_AXES)
    try:
        manifest.IDENTITY_AXES["params.invented_axis"] = "an axis with no probe, added to prove this raises"
        with pytest.raises(RuntimeError, match="no probe"):
            manifest.identity_probes()
    finally:
        manifest.IDENTITY_AXES.clear()
        manifest.IDENTITY_AXES.update(real)


def test_designs_that_share_no_axis_difference_share_a_tag():
    """The inverse, so the guard cannot be satisfied by making every tag unique (a hash would pass otherwise
    and would destroy the pooling of seeds that a design IS)."""
    a = Design(perturbation="gene_knockout", condition="KO:leuB",
               params={"target_genes": ["leuB"], "variant_index": 1818})
    b = Design(perturbation="gene_knockout", condition="KO:leuB", seeds=4, generations=7,
               params={"target_genes": ["leuB"], "variant_index": 1818, "ko_indices": [1818]})
    assert manifest.design_identity(a) == manifest.design_identity(b), (
        "seeds, generations and derived indices are NOT identity — a tag that splits on them would stop seeds "
        "of one design from pooling, which is the opposite failure")


# ---------------------------------------------------------------------------------------------------------
# (3) The live corpus, on the axes it actually records.
# ---------------------------------------------------------------------------------------------------------

def test_no_two_corpus_rows_share_a_design_key_while_differing_on_a_recorded_axis():
    """The detector for what is already on disk. Limited to the axes the manifest STORES — `params` is not a
    column — which is nonetheless where two of the three defects lived (timeline, elongation model)."""
    rows, _ = survey.analysis_rows(arm="all")
    if not rows:
        pytest.skip("corpus unreadable in this environment")
    stored = ("perturbation", "condition", "timeline", "elongation_model")

    def axes_of(r):
        # NORMALISED the way `_design_tag` normalises, not compared raw. `condition=None` and
        # `condition='basal'` are the SAME experiment for a wildtype — the tag maps both to `basal` — so a raw
        # string comparison reports the corpus as split when it is not. A detector whose false positives have
        # to be explained away is a detector nobody will keep.
        return (str(r.get("perturbation")), str(r.get("condition") or r.get("timeline") or "basal"),
                str(r.get("timeline") or ""), str(r.get("elongation_model") or "steady_state"))

    by_key: dict = {}
    for r in rows:
        by_key.setdefault(survey.design_key(r), set()).add(axes_of(r))
    split = {k: sorted(v) for k, v in by_key.items() if len(v) > 1}
    assert not split, (
        "these design keys cover rows that differ on a recorded identity axis %s, so every analysis pools "
        "different experiments: %s" % (list(stored), dict(list(split.items())[:3])))
