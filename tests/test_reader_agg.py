"""H-6: the reader worker's pure aggregation, extracted host-side (numpy-only, no wholecell) so it's unit-testable
off the sim — the exact seam the SCI-2c review flagged as untestable (a mock stood in for it and hid a real bug).

M-11a (2026-11-14) added the two cases at the bottom. The count-floor case belongs here because the floor is
applied in `_reader_agg.gene_lfc_map` and nowhere else, even though both docstrings that DESCRIBE it live in
`differential.py` and `sci2.py`. The dead-threshold case lives here beside it because it is the other half of
the same finding — `sci2.MIN_COUNT = 10.0` declared a "both sides" floor that no code ever read, while the
floor that actually runs is this module's EITHER-arm `max(tm, rm) < floor` — and keeping the pair in one file
means a reader who finds one finds the other.
"""

import ast
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cellarium import _reader_agg  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "cellarium"


def test_gene_lfc_map_full_distribution_floor_and_counts():
    t = [{"g1": 200, "g2": 100, "lowg": 3}, {"g1": 220, "g2": 90, "lowg": 4}]
    r = [{"g1": 100, "g2": 100, "lowg": 5}, {"g1": 100, "g2": 110, "lowg": 3}]
    out = _reader_agg.gene_lfc_map(t, r, floor=20)
    assert set(out) == {"g1", "g2"}                          # lowg (mean < 20) dropped by the count floor
    assert 0.9 < out["g1"]["log2fc"] < 1.1                    # ~2x up -> ~+1 log2
    assert abs(out["g2"]["log2fc"]) < 0.2                     # ~flat
    assert out["g1"]["n_target"] == 2 and out["g1"]["n_reference"] == 2


def test_gene_lfc_map_requires_both_sides_and_handles_empty():
    assert _reader_agg.gene_lfc_map([], [{"g": 100}], floor=1) == {}     # no target runs -> empty, no crash
    out = _reader_agg.gene_lfc_map([{"g1": 100, "tonly": 100}], [{"g1": 100, "ronly": 100}], floor=1)
    assert set(out) == {"g1"}                                # a gene present on only one side has no ratio -> excluded


def test_the_count_floor_is_applied_to_the_pair_and_not_per_arm():
    """The count floor is an EITHER-arm rule, and that is a decision — this test is where it is recorded.

    `gene_lfc_map` drops a gene only when `max(tm, rm) < floor`, so a gene survives when the HIGHER of its
    two arm means clears the floor. Until 2026-11-14 both docstrings that describe this filter said BOTH
    arms (`differential.all_gene_lfc`) or `either` arm in the AND sense (`sci2.sim_lfc_detail`) — i.e.
    `min(tm, rm) < floor` — which is not what runs, and the mismatch is what let a results document
    attribute floor-20 statistics to a floor-10 constant. The inputs below are chosen so the two readings
    DISAGREE: target mean 100, reference mean 1, floor 20. Under the implemented OR rule the gene is
    returned; under the AND rule the whole result is empty. Asserted against the AND reading on the
    unmodified tree this test fails with `{'g': {'log2fc': 5.6582, ...}} == {}`, which is the measurement
    that the prose, not the code, was wrong.

    The semantics is deliberate rather than an accident of `max` vs `min`: the floor's job inside
    `gene_lfc_map` is ratio stability, and `log2((tm + 1) / (rm + 1))` is already defined and stable when one
    arm is zero because of the +1 pseudocount it applies. A per-arm floor would therefore
    discard exactly the genes a knockout contrast is about — the ones whose one arm has collapsed. Swap
    `max` for `min` in `gene_lfc_map` and the straddling cases below go red; the shared case does not,
    which is why it is kept separately.
    """
    up = _reader_agg.gene_lfc_map([{"g": 100.0}], [{"g": 1.0}], floor=20.0)
    assert set(up) == {"g"}                     # max(100, 1) >= 20 -> returned; min(100, 1) < 20 would drop it
    assert up["g"]["target"] == 100.0 and up["g"]["reference"] == 1.0
    assert up["g"]["log2fc"] == 5.6582          # log2(101 / 2) = 5.65821..., literal: it must not track the floor

    # Symmetric in the arms: a collapsed TARGET (the knockout shape) is kept for the same reason.
    down = _reader_agg.gene_lfc_map([{"g": 1.0}], [{"g": 100.0}], floor=20.0)
    assert set(down) == {"g"} and down["g"]["log2fc"] == -5.6582

    # The case both rules agree on, and the one that must stay green through any change to the rule:
    # neither arm reaches the floor, so max(5, 1) < 20 drops it too.
    assert _reader_agg.gene_lfc_map([{"g": 5.0}], [{"g": 1.0}], floor=20.0) == {}


def _harness():
    """`scripts/mutate_thresholds.py`, imported for `thresholds()` and `_referenced_names` -- the single
    definition of what a declared threshold is and of what counts as a reference to one."""
    import importlib.util
    path = REPO / "scripts" / "mutate_thresholds.py"
    spec = importlib.util.spec_from_file_location("_mutate_thresholds_for_reader_agg", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _executably_referenced(mt, name: str, assign_line: int) -> bool:
    """True when any module under src/cellarium names `name` in CODE, with the declaration itself removed."""
    for f in sorted(SRC.glob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        body = [s for s in tree.body
                if not (f.name == "sci2.py" and getattr(s, "lineno", None) == assign_line)]
        if name in mt._referenced_names(ast.Module(body=body, type_ignores=[])):
            return True
    return False


def test_no_threshold_in_sci2_is_declared_without_an_executable_reference():
    """A declared threshold nobody reads is a claim the tree makes and cannot keep.

    `sci2.MIN_COUNT = 10.0` carried the comment "independent-filter floor before correlating (both sides)"
    and had ZERO executable references: `concordance` takes a `min_count_genes` set and its only caller,
    `rnaseq_concordance`, never passes one. Tier 0 classified it `no_covering_tests`, which is UNMEASURED and
    never a pass, so nothing in the suite could notice. Worse, the floor that does run is 20.0 and an
    EITHER-arm rule, so a results document attributed floor-20 statistics to this floor-10 constant.

    "A reference" is `mutate_thresholds._referenced_names`, imported rather than re-implemented, for the
    reason that function records: it reads identifiers out of the AST with docstrings excluded, so PROSE
    about a threshold does not count as a use of it. That rule exists because the prose-matching version
    promoted a dead constant out of `no_covering_tests` on the strength of a docstring that said it was
    dead. The declaration's own assignment statement is dropped before the walk, or every constant would
    reference itself.

    FORCED RED: with `MIN_COUNT = 10.0` still at sci2.py:43 this fails with
    `assert ['MIN_COUNT (sci2.py:43)'] == []` — observed before the deletion, not assumed. Re-adding any
    unread ALL-CAPS numeric constant to sci2.py (e.g. `DEAD_FLOOR = 7.0`) reproduces it. The membership
    assertion above the loop is the positive control: without it an enumerator that silently returned no
    thresholds would pass, which is the silent-absence failure this suite keeps re-learning.
    """
    mt = _harness()
    declared = [t for t in mt.thresholds(names_only=True) if t["module"] == "sci2.py"]
    assert {t["name"] for t in declared} >= {"PADJ_SIG", "DEG_SIG", "NULL_PERMUTATIONS"}
    dead = sorted(f"{t['name']} (sci2.py:{t['assign_line']})" for t in declared
                  if not _executably_referenced(mt, t["name"], t["assign_line"]))
    assert dead == []


def test_named_time_means_reads_named_columns_and_names_what_it_could_not_find():
    """BV-14's synthesis reader: the time-mean of named columns of a (time x id) listener matrix. FORCED: an id the
    listener never had is named in `missing`, never returned as a 0.0 mean (the silent-absence class)."""
    ids = ["TU00044[c]", "TU0-45225[c]", "TU00046[c]"]
    m = [[1e-6, 2e-5, 3e-6], [3e-6, 4e-5, 5e-6]]
    out = _reader_agg.named_time_means(ids, m, ["TU0-45225[c]", "TU00044[c]", "TU_NOT_THERE"])
    import pytest
    assert out["means"] == pytest.approx({"TU0-45225[c]": 3e-5, "TU00044[c]": 2e-6}, rel=1e-12)
    assert out["missing"] == ["TU_NOT_THERE"]
    none = _reader_agg.named_time_means(ids, m, ["X", "Y"])
    assert none == {"means": {}, "missing": ["X", "Y"]}
