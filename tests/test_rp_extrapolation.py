"""RP re-verification (2026-11-27): slow-growth steady-state runs read their biomass targets off splines outside their
fitted range. The literals below were computed separately (by hand from the manifest's series and the model's table)
before this module existed, so the module is checked against them rather than against itself."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))

import rp_extrapolation as R  # noqa: E402

pytest.importorskip("pandas")


@pytest.fixture(scope="module")
def corpus():
    if not R.MANIFEST.is_file():
        pytest.skip("no corpus manifest on this machine")
    return R.corpus_exposure()


def test_every_slow_growth_run_spends_time_below_the_fitted_range(corpus):
    s = corpus["slow_media"]
    assert (s["no_oxygen"]["runs"], s["no_oxygen"]["any_sample_below"]) == (8, 8)
    assert (s["acetate"]["runs"], s["acetate"]["any_sample_below"]) == (13, 13)
    assert (s["succinate"]["runs"], s["succinate"]["any_sample_below"]) == (3, 3)
    assert s["no_oxygen"]["median_share_below"] == 1.0 and s["acetate"]["median_share_below"] == 0.875
    assert s["no_oxygen"]["min_ratio"] == 0.1377


def test_run_means_were_the_proxy_that_understated_it(corpus):
    """The first count (BACKLOG RP, 2026-11-27) used run means: 8 of 8, 9 of 13 and 1 of 3."""
    s = corpus["slow_media"]
    assert [s[c]["run_mean_below"] for c in ("no_oxygen", "acetate", "succinate")] == [8, 9, 1]


def test_corpus_wide_only_the_slow_media_and_the_arrested_rplB_knockouts(corpus):
    assert corpus["steady_state_runs_with_series"] == 289 and corpus["steady_state_any_sample_below"] == 27
    assert sorted(corpus["below_outside_the_slow_media"]) == [f"gene_knockout/KO:rplB/s{i}" for i in (1, 2, 3)]
    assert corpus["other_modes_with_series"] == 12


def test_a_stricter_threshold_counts_fewer_runs(corpus):
    """Force-fail: the count must move with the threshold, or it is not reading the series."""
    stricter = R.corpus_exposure(low=0.15)
    assert stricter["steady_state_any_sample_below"] < corpus["steady_state_any_sample_below"]


def test_the_splines_fitted_range_and_zero_point():
    flat = os.environ.get("WCECOLI_DIR")
    if not (flat and (Path(flat) / "reconstruction" / "ecoli" / "flat" / "dry_mass_composition.tsv").is_file()):
        stored = json.loads((ROOT / "evals" / "results" / "rp_extrapolation.json").read_text(encoding="utf-8"))["splines"]
    else:
        stored = R.spline_facts(Path(flat) / "reconstruction" / "ecoli" / "flat")
    assert stored["doubling_times_min"] == [100.0, 60.0, 40.0, 30.0, 24.0]
    assert stored["fitted_range"] == [0.2, 0.4689]
    assert {p["not_positive_at_or_below"] for p in stored["pools"].values()} == {0.1355}
    assert stored["pools"]["lipid"]["at_0.2"] == 0.06554 and stored["pools"]["lipid"]["at_0.15"] == 0.01676
