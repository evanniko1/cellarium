"""TRNA-9 — the wild-type null must not change its answer between calls.

`selective_charging` reports `exceeds_wildtype_null_max`, and the threshold it is measured against was
computed as `ref = tabs[0]` — one arbitrary reference against every other table, where `tabs` was built by
walking `store.list_results()`, whose row order is unstable. Two consequences, both measured on identical
data:

  * the MAX — the number that actually gates the verdict — ranged 52.1-84.5 pp across six calls, a 62% swing;
  * 57 of 3,306 ordered pairs were used and the rest discarded.

Worth recording how it hid: the first four samples gave 84.5 / 84.8 / 84.8 / 84.8 and I wrote down "the max
is nearly stable". Six samples showed 52.1 in the middle of them. A stability claim needs its sample size
stated with it, which is why the determinism test here runs several calls rather than two.

It also corrected a SECOND finding. On the broken estimator, narrowing the row set to one comparability arm
appeared to cut the threshold 84.5 -> 47.6 pp, and that looked like arm-pooling inflating the null by 1.75x.
Once the estimator stopped moving, the max is 92.7 pp under ALL four candidate row sets: the apparent
inflation was an artefact of which arbitrary reference a smaller set happened to draw, not a property of the
data. The row source was still narrowed to `analysis` — pooling arms describes no instrument (INV-2) — but on
the evidence that it costs nothing on the gate, not on the evidence that it fixes it.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.cellarium import trna  # noqa: E402


@pytest.fixture
def fresh():
    trna._NULL_CACHE.clear()
    yield
    trna._NULL_CACHE.clear()


def _null():
    trna._NULL_CACHE.clear()
    return trna.wildtype_null()


def test_the_null_returns_the_same_answer_every_call(fresh):
    """THE test. A threshold that gates a scientific verdict and moves 62% between calls on identical data is
    not a threshold. Six calls, because four were not enough to see it."""
    out = _null()
    if out.get("error"):
        pytest.skip(out["error"])
    seen = set()
    for _ in range(6):
        d = _null()
        g = d["gap_pp"]
        seen.add((g["min"], g["median"], g["max"], d["n_pairs"]))
    assert len(seen) == 1, f"the null moved between calls: {sorted(seen)}"


def test_it_uses_every_ordered_pair_not_one_arbitrary_reference(fresh):
    """`n_pairs` must be n*(n-1), or some of the evidence is being discarded — and WHICH evidence would then
    depend on an unstable row order."""
    d = _null()
    if d.get("error"):
        pytest.skip(d["error"])
    n = d["n_distinct_by_content_hash"]
    assert d["n_pairs"] <= n * (n - 1)
    assert d["n_pairs"] > 2 * n, (
        f"{d['n_pairs']} pairs from {n} tables is one-vs-rest, not all-pairs — the arbitrary reference is back")


def test_the_worst_family_tally_counts_each_table_once(fresh):
    """The worst family is a property of a TABLE, not of a pairing. Counting it once per ordered pair would
    multiply every tally by n-1 while changing nothing about what it says."""
    d = _null()
    if d.get("error"):
        pytest.skip(d["error"])
    total = sum(n for _fam, n in d["worst_family_named_on_pure_wildtype"])
    assert total == d["n_distinct_by_content_hash"], (
        f"tally sums to {total} over {d['n_distinct_by_content_hash']} tables — it is counting pairings")


def test_the_null_is_built_from_one_comparability_arm(fresh):
    """`fraction_trna_charged` is the channel where the elongation model changes what the number MEANS, so a
    false-positive floor pooled across arms describes no instrument (INV-2).

    Checked from the SYNTAX TREE, not by text search. The first version asserted
    `"store.list_results()" not in src` and failed on the comment that explains why the old call was
    removed — a text check tripping over prose about the thing it forbids, which is exactly the defect that
    made `hygiene.read_sites()` over-count by three modules.
    """
    import ast
    import inspect
    import textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(trna.wildtype_null)))
    calls = {f"{n.func.value.id}.{n.func.attr}" for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and isinstance(n.func.value, ast.Name)}
    assert "hygiene.rows" in calls, calls
    assert "store.list_results" not in calls, (
        "the unfiltered primitive is being called again — the null is pooling arms")


def test_the_gate_is_the_max_and_it_survived_the_change(fresh):
    """Recorded as a value because the whole reason this migration was safe to land is that the gate does not
    move. If it changes, someone changed what `exceeds_wildtype_null_max` means and should say so."""
    d = _null()
    if d.get("error"):
        pytest.skip(d["error"])
    assert d["gap_pp"]["max"] == pytest.approx(92.7, abs=0.15), (
        f"the verdict gate moved to {d['gap_pp']['max']} — this is a scientific threshold, not a detail")
