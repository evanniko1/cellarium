"""SP-2 receptive field: extrema-preserving decimation + full-scan transient/level-shift detection with FDR
control. These are the numeric guarantees behind read_raw_series' new view and the scan_series tool."""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cellarium import scan, stats, tools  # noqa: E402


def _noisy(n, level, sd, seed):
    return level + np.random.default_rng(seed).normal(0, sd, n)


def test_minmax_preserves_a_spike_stride_would_miss():
    """The exact SP-2 hole: a narrow transient falls between strided points but survives min-max decimation."""
    n, t = 200, np.arange(200, dtype=float)
    v = np.ones(n)
    v[97:100] = 10.0                                   # a 3-wide spike
    idx = scan.minmax_decimate(t, v, 16)               # ~16 shown points
    assert v[idx].max() == 10.0                        # the spike is in the view
    stride = [int(round(i * (n - 1) / 15)) for i in range(16)]   # old stride behaviour
    assert max(v[s] for s in stride) < 10.0            # stride would have missed it


def test_detect_transient_returns_to_baseline():
    n, t = 300, np.arange(300, dtype=float)
    v = _noisy(n, 1.0, 0.02, seed=1)
    v[148:154] += 1.0                                  # a clear up-transient, then back to baseline
    ev = scan.detect_events(t, v, min_effect_mad=4.0, min_width=3, fdr=0.05)
    hit = [e for e in ev if 140 <= e["t_peak"] <= 165]
    assert hit and hit[0]["kind"] == "transient" and hit[0]["direction"] == "up"
    assert hit[0]["q_value"] <= 0.05 and hit[0]["magnitude_mad"] >= 4.0


def test_detect_level_shift_stays_shifted():
    n, t = 300, np.arange(300, dtype=float)
    v = _noisy(n, 1.0, 0.02, seed=2)
    v[150:] += 1.0                                     # a sustained step (does not return)
    ev = scan.detect_events(t, v, min_effect_mad=4.0, min_width=3, fdr=0.05)
    assert any(e["kind"] == "level_shift" for e in ev)


def test_clean_trajectory_yields_no_false_positive():
    n, t = 300, np.arange(300, dtype=float)
    v = _noisy(n, 1.0, 0.02, seed=3)                   # pure noise — the FP-control test
    assert scan.detect_events(t, v, min_effect_mad=4.0, min_width=3, fdr=0.05) == []


def test_scan_is_deterministic():
    n, t = 300, np.arange(300, dtype=float)
    v = _noisy(n, 1.0, 0.02, seed=4)
    v[100:105] += 0.8
    a = scan.detect_events(t, v, min_effect_mad=4.0, min_width=3, fdr=0.05)
    b = scan.detect_events(t, v, min_effect_mad=4.0, min_width=3, fdr=0.05)
    assert a == b                                       # fixed bootstrap seed -> reproducible


def test_bh_qvalues_monotone_and_bounded():
    q = stats.bh_qvalues([0.01, 0.04, 0.5])
    assert all(0.0 <= x <= 1.0 for x in q) and q[0] <= q[1] <= q[2]
    assert stats.bh_qvalues([]) == []


def test_top_movers_truncation_block():
    """Host-computed 'k of N' from what the worker reports — a mid-rank significant mover stops being invisible."""
    out = {"kind": "protein", "n_significant_fdr10": 40,
           "up": [{"id": f"U{i}", "q": 0.01} for i in range(8)],
           "down": [{"id": f"D{i}", "q": 0.02} for i in range(4)]}   # 12 shown, all significant; 40 total
    tb = tools._truncation_block(out, top=12)
    assert tb["n_significant"] == 40 and tb["n_shown_significant"] == 12 and tb["n_dropped_significant"] == 28
    assert "raise `top`" in tb["hint"]
    # nothing dropped (all significant are shown) -> no block
    assert tools._truncation_block({"n_significant_fdr10": 1, "up": [{"id": "U", "q": 0.01}], "down": []}, 12) is None
    assert tools._truncation_block({"up": [], "down": []}, 12) is None   # no significance count -> None
