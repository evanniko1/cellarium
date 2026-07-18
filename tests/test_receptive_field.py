"""SP-2b receptive-field eval (deterministic): the standing guarantee that a KNOWN needle the coarse view flattens
is recovered by the full-scan surface, that a clean trajectory yields nothing (null control), and that a mid-rank
mover past the top-N cut is surfaced. The agent-in-the-loop graded version (does Cellwright choose to scan) is the
deferred SP-2c piece; this locks the tool-level property in CI."""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cellarium import scan, tools  # noqa: E402

_SD = 0.02


def _traj(n=320, spike_at=180, width=4, amp_mad=8.0, seed=7):
    t = np.arange(n, dtype=float)
    v = 1.0 + np.random.default_rng(seed).normal(0, _SD, n)
    v[spike_at:spike_at + width] += amp_mad * _SD          # a spike amp_mad robust-MADs high, `width` wide
    return t, v


def test_needle_the_coarse_view_flattens_is_recovered():
    t, v = _traj()
    k = 16
    # (a) the OLD stride/coarse view (~16 points) SAMPLES PAST the spike -> it looks flat
    stride = [int(round(i * (v.size - 1) / (k - 1))) for i in range(k)]
    assert max(v[s] for s in stride) < 1.0 + 3 * _SD
    # (b) min-max decimation KEEPS the spike in the view
    idx = scan.minmax_decimate(t, v, k)
    assert v[idx].max() >= 1.0 + 6 * _SD
    # (c) the full scan RECOVERS it — right place, kind, direction
    ev = scan.detect_events(t, v, min_effect_mad=4.0, min_width=3, fdr=0.05)
    hit = [e for e in ev if abs(e["t_peak"] - 181.5) <= 6]
    assert hit and hit[0]["kind"] == "transient" and hit[0]["direction"] == "up" and hit[0]["q_value"] <= 0.05


def test_null_control_no_false_needle():
    t, v = _traj(amp_mad=0.0)                                # no needle injected
    assert scan.detect_events(t, v, min_effect_mad=4.0, min_width=3, fdr=0.05) == []


def test_mid_rank_mover_is_surfaced_not_dropped():
    # a top_movers result: 12 shown but 40 BH-significant; the worker's stratified mid-rank sample carries one
    out = {"kind": "protein", "n_significant_fdr10": 40, "down": [],
           "up": [{"id": f"U{i}", "symbol": f"g{i}", "q": 0.01} for i in range(12)],
           "mid_rank_sample": [{"id": "M1", "symbol": "midGene", "log2fc": 0.9, "q": 0.03}]}
    tb = tools._truncation_block(out, top=12)
    assert tb["n_dropped_significant"] == 28
    assert tb["mid_rank_examples"] and tb["mid_rank_examples"][0]["symbol"] == "midGene"
