"""One (arm, design, seed, depth) cell is ONE run — unless two machines ran it (DUP-1).

18 cells held more than one run. They split 9/9 into two causes that look identical in a query and are
opposite in meaning, which is why the count alone was not actionable.

CAUSE 1 — the media TIMELINE was missing from a knockout's identity (9 cells, now fixed). `_design_tag`'s
`gene_knockout` branch returned `KO:<genes>` plus media, dose and elongation model, and dropped the timeline:
the non-KO branch keys on `condition or timeline`, but a knockout carries a condition, so it took the other
branch and the timeline vanished. MEASURED: `gene_knockout·KO:leuB·s0` existed twice, once under
`0 minimal_plus_amino_acids, 1200 minimal_aa_mix` (an amino-acid downshift) and once under
`0 minimal_plus_amino_acids` (a constant medium) — two different experiments under one label, averaged as
seeds of one design. `runner._dir_discriminator` already separated them on DISK, and its docstring records the
incident where the two destroyed each other's output at parallel=6; only IDENTITY was still merged, which is
what every analysis keys on. 32 rows relabelled with the same 6-hex sha1 the directory uses.

CAUSE 2 — genuine duplicate registration (3 cells, now tombstoned). One run indexed twice: once at the bare
variant dir and again at the `__tl…` dir after the discriminator shipped. The dedup key is (id, normalised
path), the paths differ, so both survived. All 11 summary channels were BIT-IDENTICAL, which is what
identifies it as one run rather than two.

WHAT IS NOT A DEFECT — the remaining 9 cells (cross-contributor). The same design, seed and depth run on two
machines gives DIFFERENT numbers: at a fixed seed the between-contributor difference is as large as the
spread between seeds (ratio 0.96 on wildtype/basal, 0.88 on condition/acetate). That is not bias — the
contributor ICC is 0.0000, so no machine shifts the mean — it means a seed does not pin the outcome ACROSS
environments. Two such rows are therefore independent replicates, and deduplicating them would DISCARD real
replication. `survey.depth`'s ICC finding and this one are both true and are not in tension.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.cellarium import corpus_schema, factors, manifest, survey  # noqa: E402
from src.cellarium.model import Design  # noqa: E402


def _cells():
    rows, _ = survey.analysis_rows(arm="all")
    if not rows:
        pytest.skip("corpus unreadable in this environment")
    seen: dict = {}
    for r in rows:
        key = (corpus_schema.arm_of(r), survey.design_key(r), r.get("seed"), r.get("generations"))
        seen.setdefault(key, []).append(r)
    return seen


# ---------------------------------------------------------------------------------------------------------
# The invariant.
# ---------------------------------------------------------------------------------------------------------

def test_no_cell_holds_two_runs_from_the_same_machine():
    """THE duplicate test. Same arm, design, seed, depth AND contributor — the model is deterministic there,
    so two rows are one run counted twice, which inflates n and narrows every interval that includes it."""
    bad = {}
    for key, runs in _cells().items():
        if len(runs) < 2:
            continue
        by_contrib: dict = {}
        for r in runs:
            by_contrib.setdefault(str(r.get("contributor")), []).append(r.get("id"))
        for who, ids in by_contrib.items():
            if len(ids) > 1:
                bad[(key[1], key[2], key[3], who)] = ids
    assert not bad, ("these cells hold more than one run from ONE machine, so they are the same run counted "
                     "twice: %s" % dict(list(bad.items())[:4]))


def test_cross_machine_replicates_are_kept_not_deduplicated():
    """The other half, asserted so a future 'cleanup' cannot silently delete real replication.

    A seed does not pin the outcome across machines, so two contributors running the same design and seed
    produce two genuinely different measurements. They must survive.
    """
    multi = {k: v for k, v in _cells().items()
             if len(v) > 1 and len({str(r.get("contributor")) for r in v}) > 1}
    if not multi:
        pytest.skip("no cross-contributor cells in this checkout")
    for key, runs in multi.items():
        vals = [r.get("growth_rate") for r in runs if r.get("growth_rate") is not None]
        assert len(vals) == len(runs), "a cross-machine replicate lost its channel"
    # and they really do differ — if they were identical this test would be defending nothing
    spreads = [max(v) - min(v) for v in
               ([r.get("growth_rate") for r in runs if r.get("growth_rate")] for runs in multi.values())
               if len(v) > 1]
    assert any(s > 0 for s in spreads), (
        "every cross-machine pair is identical, so the model IS reproducible across machines and these are "
        "duplicates after all — re-read the DUP-1 conclusion rather than keeping this test green")


# ---------------------------------------------------------------------------------------------------------
# The timeline is part of a knockout's identity.
# ---------------------------------------------------------------------------------------------------------

_TL_DOWNSHIFT = "0 minimal_plus_amino_acids, 1200 minimal_aa_mix"
_TL_CONSTANT = "0 minimal_plus_amino_acids"


def _ko(timeline=None):
    return Design(perturbation="gene_knockout", condition="KO:leuB", timeline=timeline,
                  params={"target_genes": ["leuB"], "variant_index": 1818})


def test_two_timelines_of_one_knockout_are_two_designs():
    a, b, none = (manifest._design_tag(_ko(_TL_DOWNSHIFT)), manifest._design_tag(_ko(_TL_CONSTANT)),
                  manifest._design_tag(_ko()))
    assert a != b, "a downshift and a constant medium produced the same design tag"
    assert none == "KO:leuB", "a knockout with no timeline must keep its label byte-identical"
    assert factors.TL_TAG_PREFIX in a and factors.TL_TAG_PREFIX in b


def test_the_design_key_and_the_run_directory_agree():
    """The tag reuses `_dir_discriminator`'s hash, so a reader can map a key to the directory to go and look at."""
    from src.cellarium import runner
    d = _ko(_TL_CONSTANT)
    assert runner._dir_discriminator(d) == "__tl" + manifest._design_tag(d).split(factors.TL_TAG_PREFIX)[1]


def test_the_timeline_round_trips_and_does_not_eat_the_gene():
    f = factors.parse("gene_knockout/" + manifest._design_tag(_ko(_TL_DOWNSHIFT)))
    assert f["genes"] == ["leuB"], "the gene was lost to the timeline fragment"
    assert f["timeline_id"] and f["factor"] == "gene_KO"
    plain = factors.parse("gene_knockout/KO:leuB")
    assert plain["timeline_id"] is None and plain["genes"] == ["leuB"]


def test_the_live_corpus_separates_the_leuB_timelines():
    rows, _ = survey.analysis_rows(arm="all")
    if not rows:
        pytest.skip("corpus unreadable in this environment")
    keys = {survey.design_key(r) for r in rows
            if r.get("timeline") and "gene_knockout" in str(r.get("perturbation") or "")}
    if not keys:
        pytest.skip("no knockout-under-timeline rows in this checkout")
    assert all(factors.TL_TAG_PREFIX in k for k in keys), (
        "a knockout run under a timeline still keys as though it had none: %s" % sorted(keys)[:4])
