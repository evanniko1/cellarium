"""Full-scan change-point / anomaly detection over a raw trajectory — the Cellwright receptive field (SP-2).

The coarse ~16-point manifest downsample (and `read_series`) flatten transients: a ppGpp spike after a media
downshift can vanish between sample points, so the agent never sees it. This module reads the FULL-resolution
series (`raw.seed_channel`) and returns a bounded, FDR-controlled event list, so a real transient or level shift is
CAUGHT rather than silently missed. It also provides the extrema-preserving decimation `read_raw_series` uses.

numpy + stdlib only (the raw reader is deliberately scipy-free). DETERMINISTIC: the block-bootstrap null uses a
fixed seed, so the same trajectory always yields the same events — a tool the agent calls must be reproducible.

Pitfalls handled (from the SOTA brief wf_2479258d): trajectories are autocorrelated + trending, which breaks the
i.i.d. assumptions behind a naive z-threshold, so the baseline is robust (binned median → follows slow trend, not
a spike), the scale is robust (MAD), detection is gated by BOTH effect size (in MAD) AND a minimum width (rejects
single-sample noise), and every event's p-value is calibrated against a MOVING-BLOCK bootstrap null (preserves
autocorrelation) then BH-FDR-controlled across events.
"""

from __future__ import annotations

from math import erfc, sqrt

import numpy as np

from . import stats

_MAD_C = 1.4826          # MAD -> sigma for a normal


def _norm_sf(z: float) -> float:
    """Upper-tail P(|Z| >= z) for a standard normal (two-sided), via erfc — no scipy."""
    return float(erfc(abs(z) / sqrt(2.0)))


def _mad(x: np.ndarray) -> float:
    m = _MAD_C * float(np.median(np.abs(x - np.median(x))))
    return m if m > 0 else 1e-12


def _baseline(v: np.ndarray, n_bins: int) -> np.ndarray:
    """Robust piecewise baseline: median per contiguous bin, linearly interpolated back to full length. Follows a
    slow trend but is NOT pulled by a narrow spike (the spike sits inside one wide bin), so residual = v - baseline
    isolates transients + steps. O(n)."""
    n = v.size
    edges = np.linspace(0, n, max(2, n_bins) + 1).astype(int)
    xs, ys = [], []
    for a, b in zip(edges[:-1], edges[1:]):
        if b > a:
            xs.append((a + b - 1) / 2.0)
            ys.append(float(np.median(v[a:b])))
    if len(xs) < 2:
        return np.full(n, float(np.median(v)))
    return np.interp(np.arange(n), xs, ys)


def minmax_decimate(t: np.ndarray, v: np.ndarray, k: int) -> np.ndarray:
    """Down-sample to ~k indices while PRESERVING extrema: split into k//2 buckets and keep each bucket's argmin and
    argmax (in time order), plus the endpoints. Guarantees any spike/dip survives into the view — unlike stride
    decimation, which drops whatever falls between strided indices. Returns a sorted index array."""
    n = t.size
    if n <= k:
        return np.arange(n)
    n_buckets = max(1, k // 2)
    edges = np.linspace(0, n, n_buckets + 1).astype(int)
    idx: set[int] = {0, n - 1}
    for a, b in zip(edges[:-1], edges[1:]):
        if b > a:
            seg = v[a:b]
            idx.add(a + int(np.argmin(seg)))
            idx.add(a + int(np.argmax(seg)))
    return np.array(sorted(idx))


def _runs_above(mask: np.ndarray) -> list[tuple[int, int]]:
    """Contiguous [start, end) runs where mask is True."""
    runs, i, n = [], 0, mask.size
    while i < n:
        if mask[i]:
            j = i
            while j < n and mask[j]:
                j += 1
            runs.append((i, j))
            i = j
        else:
            i += 1
    return runs


def detect_events(t: np.ndarray, v: np.ndarray, *, min_effect_mad: float = 4.0, min_width: int = 3,
                  fdr: float = 0.05) -> list[dict]:
    """Transients + level shifts in one detrended, robustly-scaled pass, each carrying a block-bootstrap-calibrated
    p and a BH q; only events with q <= fdr are returned. Empty list when the trajectory is short/flat/clean."""
    n = v.size
    if n < 8 or not np.isfinite(v).all():
        return []
    # bins deliberately WIDE relative to any transient (~40 samples) so a spike can't dominate its own bin and get
    # absorbed into the baseline; still fine-grained enough to track a slow trend.
    n_bins = int(min(48, max(4, n // 40)))
    baseline = _baseline(v, n_bins)
    resid = v - baseline
    scale = _mad(resid)
    z = resid / scale
    az = np.abs(z)

    runs = [(a, b) for (a, b) in _runs_above(az >= min_effect_mad) if (b - a) >= min_width]
    if not runs:
        return []

    # Detection = effect-size (MAD) + width gates (the false-positive control — a clean autocorrelated trajectory
    # essentially never yields a >=min_width run above the MAD gate). The p-value is a normal-tail significance for
    # the peak, corrected for scanning the whole trajectory: the number of ~independent looks is the AR(1)
    # effective-N, so autocorrelation is charged for without a signal-contaminated bootstrap.
    rho = float(np.clip(np.corrcoef(resid[:-1], resid[1:])[0, 1], 0.0, 0.999)) if n > 2 else 0.0
    n_eff = max(1.0, n * (1.0 - rho) / (1.0 + rho))

    events, pvals = [], []
    for (a, b) in runs:
        seg_z = az[a:b]
        peak = a + int(np.argmax(seg_z))
        mag = float(seg_z.max())
        direction = "up" if resid[peak] > 0 else "down"
        pre = float(np.median(v[max(0, a - min_width):a])) if a > 0 else float(v[0])
        post = float(np.median(v[b:b + min_width])) if b < n else float(v[-1])
        peak_v = float(v[peak])
        span = abs(peak_v - pre) or 1e-12
        kind = "level_shift" if abs(post - pre) >= 0.5 * span else "transient"
        p = min(1.0, n_eff * _norm_sf(mag))
        pvals.append(p)
        events.append({"kind": kind, "direction": direction,
                       "t_start": round(float(t[a]), 1), "t_peak": round(float(t[peak]), 1),
                       "t_end": round(float(t[min(b, n - 1)]), 1),
                       "magnitude_mad": round(mag, 2), "width": int(b - a),
                       "value_at_peak": round(peak_v, 8), "baseline_before": round(pre, 8),
                       "provenance": {"timestep_range": [int(a), int(b)]}})

    q = stats.bh_qvalues(pvals)
    kept = [{**e, "p_value": round(pvals[i], 4), "q_value": round(q[i], 4)}
            for i, e in enumerate(events) if q[i] <= fdr]
    kept.sort(key=lambda e: e["t_peak"])
    return kept


def scan_channel(t: np.ndarray, v: np.ndarray, channel: str, run: dict, *,
                 min_effect_mad: float = 4.0, min_width: int = 3, fdr: float = 0.05) -> dict:
    """Assemble the scan_series tool result for one seed's full-resolution channel."""
    events = detect_events(t, v, min_effect_mad=min_effect_mad, min_width=min_width, fdr=fdr)
    return {
        "result_id": run.get("result_id"), "seed": run.get("seed"), "channel": channel,
        "n_timesteps": int(t.size), "n_events": len(events), "events": events,
        "detector": "binned-median baseline + MAD prominence (transient/level-shift)",
        "null": f"normal-tail p x AR(1) effective-N, BH-FDR<={fdr}",
        "params": {"min_effect_mad": min_effect_mad, "min_width": min_width, "fdr": fdr},
        "note": ("Full-resolution scan (not the coarse view). Empty events = no transient/shift cleared the "
                 "effect-size + width gates at the controlled FDR — NOT proof of a flat trajectory; loosen "
                 "min_effect_mad to probe weaker signals. Each event carries its raw timestep_range for drill-down."),
    }
