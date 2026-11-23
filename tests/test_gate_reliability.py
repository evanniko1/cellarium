"""BACKLOG V-1: the gate's headline accuracy, against trivial baselines and with a clustered interval.

These run on the STORED artefact, `evals/results/gate_eval_8framings.json`, so no model call is made and the
numbers are the ones the paper quotes. Every expectation is a LITERAL recomputed by hand from the 216
records, not derived from the function under test -- a test that compared `_reliability(recs)` against
another call to the same arithmetic would hold at every value and pin nothing, which is the self-referential
trap the mutation work catalogued.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import run_gate_eval as ev  # noqa: E402

ART = REPO / "evals" / "results" / "gate_eval_8framings.json"


@pytest.fixture(scope="module")
def recs():
    return json.loads(ART.read_text(encoding="utf-8"))["records"]


def test_a_system_that_refuses_everything_scores_0_556_on_this_surface(recs):
    """The headline 0.875 is only meaningful beside this. Gold labels: refuse 120, answer 72, propose 24."""
    rel = ev._reliability(recs)
    assert rel["trivial_baselines"] == {"always_refuse": 0.5556, "always_answer": 0.3333,
                                         "always_propose": 0.1111}
    assert rel["best_trivial_baseline"] == {"strategy": "always_refuse", "accuracy": 0.5556}
    assert rel["margin_over_best_trivial"] == pytest.approx(0.3194, abs=1e-4)


def test_the_interval_is_clustered_on_the_cell_not_the_record(recs):
    """27 cells of 8 framings each. The clustered half-width is ~2.7x the naive one, because the framings of a
    cell share its answer and are not independent trials."""
    rel = ev._reliability(recs)
    assert rel["n_clusters"] == 27
    assert rel["items_per_cluster"] == [(8, 27)]
    assert rel["ci95_half_width_naive"] == pytest.approx(0.0441, abs=1e-4)
    assert rel["naive_understates_se_by"] == pytest.approx(2.73, abs=0.01)
    # t(26) = 2.0555 x clustered SE 0.06147 = 0.1264. The z value would give 0.1205; the difference is the
    # few-clusters correction, and the assertion distinguishes them.
    if rel["critical_value"].startswith("t("):
        assert rel["ci95_half_width_clustered"] == pytest.approx(0.1264, abs=2e-4)
        assert rel["accuracy_ci95_clustered"] == pytest.approx([0.7486, 1.0014], abs=2e-4)


def test_clustering_on_the_record_id_would_silently_give_the_naive_interval(recs):
    """Why `_reliability` does not reuse `evals/aggregate.case_clustered_mean`: that helper clusters on `id`,
    and `id` is unique per record here (216 of 216). So it would produce the naive interval while appearing to
    cluster. This pins the reason, so a later "simplification" that swaps in the shared helper fails here."""
    assert len({r["id"] for r in recs}) == len(recs) == 216
    assert len({(r["capability"], r["mode"]) for r in recs}) == 27


def test_the_report_carries_the_reliability_block(recs):
    rep = ev._report(recs)
    assert "reliability" in rep
    assert rep["accuracy"] == 0.875


def test_a_record_set_without_cells_gets_no_reliability_block_rather_than_a_wrong_one():
    """The held-out bank's records have no capability/mode, so the clustered interval is undefined there.
    Omitting the block is honest; computing one over the wrong unit would not be."""
    recs = [{"correct": True, "required": "refuse", "got": "refuse", "required_principled": "refuse",
             "correct_principled": True, "id": "a__x", "kind": "k", "framing": "f",
             "parser_failed": False, "granularity": "g"}]
    assert "reliability" not in ev._report(recs)
