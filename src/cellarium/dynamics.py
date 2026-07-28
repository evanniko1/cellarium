"""SCI-DYN-1 — nutrient shifts as TRANSIENTS, not per-segment means.

A `timeline` design is a nutrient shift, and the corpus summarises it as a mean before and a mean after. That
throws away the part that carries the biology: the ADAPTATION. A downshift does not simply move ppGpp from one
level to another — ppGpp spikes within minutes, overshoots, and then relaxes toward a new steady state. Two
runs with identical segment means can have completely different transients, and the transient is what a
stringent-response claim actually rests on.

The internal argument is the strongest one: **Ahn-Horst et al. 2022** (*npj Syst Biol Appl*) is the wcEcoli
extension whose entire purpose was dynamic shift response, and whose headline result IS a transient (a transient
rise in the mRNA:rRNA ratio, for both an upshift and a downshift). Reporting only segment means discards
precisely the quantity the model was extended to produce. External anchor: Zhu & Dai 2023 (*Nat Commun* 14:467,
PMID 36709335).

**Deliberately does not use the recorded media labels.** SCI-QC-1 found that `FBAResults/media_id` is a
fixed-width column, so the amino-acid UPSHIFT's post-shift medium truncates to a string identical to its
pre-shift medium and the shift is invisible in the record. A label-driven analysis would therefore fail exactly
on the design that most needs it. This module instead takes the shift time from the design's own DECLARED
timeline and measures the response from the full-resolution trajectory — which is correct for both directions
and survives the recorder bug.

Sits above `scan.detect_events` (SP-2), which finds transients in a raw series without being told where to look;
this layer knows WHEN the shift was declared and characterises the response around it.
"""

from __future__ import annotations

import statistics

from . import miase, raw, scan, survey

# how far after the declared shift to look for the peak, and how much pre-shift window defines the baseline
_WINDOW_S = 900.0        # 15 min — long enough for a stringent-response transient, short enough to stay local
_BASELINE_S = 600.0


def _seed_response(seed_root: str, channel: str, t_shift: float) -> dict | None:
    """Characterise one seed's response to a shift at `t_shift`, from its full-resolution trajectory."""
    import numpy as np
    t, v = raw.seed_channel(seed_root, channel)
    if t.size < 20:
        return None
    pre_mask = (t >= t_shift - _BASELINE_S) & (t < t_shift)
    post_mask = (t >= t_shift) & (t <= t_shift + _WINDOW_S)
    tail_mask = t > t_shift + _WINDOW_S
    if pre_mask.sum() < 5 or post_mask.sum() < 5:
        return None
    pre = float(np.median(v[pre_mask]))
    post_win = v[post_mask]
    # the extremum in the response window is the transient's peak (or nadir) — direction taken from the data
    i_max, i_min = int(np.argmax(post_win)), int(np.argmin(post_win))
    up = abs(float(post_win[i_max]) - pre) >= abs(float(post_win[i_min]) - pre)
    i_pk = i_max if up else i_min
    peak = float(post_win[i_pk])
    t_peak = float(t[post_mask][i_pk])
    settled = float(np.median(v[tail_mask])) if tail_mask.sum() >= 5 else None
    denom = abs(pre) or 1e-12
    # OVERSHOOT: how far past the eventual steady state the peak went. This is the number a segment mean erases:
    # if the trajectory rises to a peak and then relaxes, |peak-pre| > |settled-pre| and the mean sees neither.
    overshoot = None
    if settled is not None:
        step = abs(settled - pre)
        overshoot = round((abs(peak - pre) - step) / denom * 100.0, 1)
    return {
        "pre_shift": round(pre, 6), "peak": round(peak, 6), "t_peak_s": round(t_peak, 1),
        "time_to_peak_s": round(t_peak - t_shift, 1), "direction": "up" if up else "down",
        "peak_pct_vs_pre": round(100.0 * (peak - pre) / denom, 1),
        "settled": (round(settled, 6) if settled is not None else None),
        "settled_pct_vs_pre": (round(100.0 * (settled - pre) / denom, 1) if settled is not None else None),
        "overshoot_pct_of_pre": overshoot,
    }


def shift_response(design: str, channel: str = "ppgpp_conc") -> dict:
    """The ADAPTATION to a declared nutrient shift: baseline, peak, time-to-peak, settled level, overshoot.

    Returns per-seed detail plus the cross-seed medians. `overshoot_pct_of_pre` is the headline: how far the
    transient went BEYOND the eventual new steady state — exactly the quantity a pre/post segment mean cannot
    express, and the reason this module exists."""
    rows = [r for r in survey._deduped_rows(survey.CHANNELS) if survey.design_key(r) == design]
    if not rows:
        return {"error": f"'{design}' is not a design in the corpus"}
    declared = miase.declared_events(rows[0].get("timeline"))
    shifts = [t for t, _m in declared if t > 0]
    if not shifts:
        return {"error": f"'{design}' declares no nutrient shift (timeline={rows[0].get('timeline')!r}) — "
                         f"shift_response is for timeline designs"}
    t_shift = shifts[0]
    runs = raw.seed_runs(design)
    if not runs:
        return {"error": f"no local raw simOut for '{design}' — the transient needs full-resolution series"}
    per_seed, used = [], []
    for r in runs:
        try:
            resp = _seed_response(r["root"], channel, t_shift)
        except Exception:
            resp = None
        if resp:
            per_seed.append({"seed": r.get("seed"), **resp})
            used.append(r.get("seed"))
    if not per_seed:
        return {"error": f"could not characterise the response for '{design}' "
                         f"(channel={channel!r}, shift at t={t_shift}s) — too few timesteps around the shift"}

    def med(key):
        vals = [p[key] for p in per_seed if p.get(key) is not None]
        return round(statistics.median(vals), 4) if vals else None

    # corroboration from the blind detector: does SP-2's scan independently flag an event near the declared time?
    corroborated = None
    try:
        t, v = raw.seed_channel(runs[0]["root"], channel)
        events = scan.detect_events(t, v)
        corroborated = any(abs(e["t_peak"] - t_shift) <= _WINDOW_S for e in events)
    except Exception:
        pass
    return {
        "design": design, "channel": channel, "declared_shift_s": t_shift, "seeds": used,
        "median": {k: med(k) for k in ("time_to_peak_s", "peak_pct_vs_pre", "settled_pct_vs_pre",
                                       "overshoot_pct_of_pre")},
        "direction": statistics.mode([p["direction"] for p in per_seed]),
        "per_seed": per_seed,
        "independently_detected_by_scan": corroborated,
        "note": ("The adaptation to a declared shift, measured from the FULL-RESOLUTION trajectory. "
                 "`overshoot_pct_of_pre` is how far the transient went beyond the eventual steady state — the "
                 "quantity a pre/post segment mean discards. The shift time comes from the design's DECLARED "
                 "timeline, never from the recorded media labels, because those truncate on the upshift "
                 "(SCI-QC-1). `independently_detected_by_scan` is a blind cross-check: SP-2's detector is not "
                 "told where the shift is."),
    }
