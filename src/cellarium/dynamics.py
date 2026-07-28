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

import os
import statistics

from . import miase, raw, scan, survey

# channels that are a dry-mass quantity or a rate derived from one — for these an excursion at a nutrient shift
# can be pure metabolite-pool re-equilibration, so the mass decomposition is attached automatically.
_MASS_DERIVED = {"growth_rate", "cell_mass", "dry_mass"}

# how far after the declared shift to look for the peak, and how much pre-shift window defines the baseline
_WINDOW_S = 900.0        # 15 min — long enough for a stringent-response transient, short enough to stay local
_BASELINE_S = 600.0
_DESPIKE_K = 5           # samples (~5 s) — kills 1-2 sample noise excursions, far shorter than any adaptation


def _rolling_median(a, k: int):
    """Centred rolling median, edges held. Makes the extremum a PERSISTENT feature rather than one bad sample."""
    import numpy as np
    a = np.asarray(a, dtype=float)
    if k < 3 or a.size < k:
        return a
    h = k // 2
    padded = np.pad(a, h, mode="edge")
    return np.median(np.lib.stride_tricks.sliding_window_view(padded, k), axis=-1)


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
    # DE-SPIKE before taking an extremum. A raw argmax over a noisy channel reports NOISE as a transient:
    # measured on `growth_rate`, whose baseline is ~4e-4 with occasional single-sample excursions — the raw
    # extremum claimed a -173% crash (one sample at -2.9e-4) on the downshift and a +1181% surge on the
    # upshift, neither near a generation boundary, both gone after a 5-sample median. A real adaptation lasts
    # hundreds of seconds (the ppGpp response peaks at ~434s), so a 5s rolling median cannot erase biology; it
    # only removes excursions too brief to be one.
    post_win = _rolling_median(v[post_mask], _DESPIKE_K)
    # the extremum in the response window is the transient's peak (or nadir) — direction taken from the data
    i_max, i_min = int(np.argmax(post_win)), int(np.argmin(post_win))
    up = abs(float(post_win[i_max]) - pre) >= abs(float(post_win[i_min]) - pre)
    i_pk = i_max if up else i_min
    peak = float(post_win[i_pk])
    t_peak = float(t[post_mask][i_pk])
    settled = float(np.median(v[tail_mask])) if tail_mask.sum() >= 5 else None
    denom = abs(pre) or 1e-12
    # If the extremum lands on the LAST sample of the response window, the response had not finished inside it:
    # the "peak" is the window edge, not a turning point, and any overshoot computed from it is meaningless.
    # Measured on the downshift, whose ppGpp is still climbing at t_shift+900 and reports a NEGATIVE overshoot
    # purely as an artifact of the cut. Reporting that as a real undershoot would be a fabricated dynamic.
    edge = bool(i_pk >= len(post_win) - 1)
    # The MIRROR case: the extremum is the FIRST post-shift sample. The response was already complete within one
    # timestep, so `time_to_peak_s` is an upper bound set by the sampling interval, not a measured latency.
    # Measured on `growth_rate`, which jumps 11x at exactly t=1200 on the upshift and goes NEGATIVE on the
    # downshift — both sustained for hundreds of samples and reproducible across seeds, so this is a genuinely
    # instantaneous response, not an artifact. Reporting "time to peak = 0 s" without this flag would invite the
    # reader to treat a resolution limit as a kinetic measurement.
    immediate = bool(i_pk == 0)
    # OVERSHOOT: how far past the eventual steady state the peak went. This is the number a segment mean erases:
    # if the trajectory rises to a peak and then relaxes, |peak-pre| > |settled-pre| and the mean sees neither.
    overshoot = None
    if settled is not None and not edge:
        step = abs(settled - pre)
        overshoot = round((abs(peak - pre) - step) / denom * 100.0, 1)
    return {
        "pre_shift": round(pre, 6), "peak": round(peak, 6), "t_peak_s": round(t_peak, 1),
        "time_to_peak_s": round(t_peak - t_shift, 1), "direction": "up" if up else "down",
        "peak_pct_vs_pre": round(100.0 * (peak - pre) / denom, 1),
        "settled": (round(settled, 6) if settled is not None else None),
        "settled_pct_vs_pre": (round(100.0 * (settled - pre) / denom, 1) if settled is not None else None),
        "overshoot_pct_of_pre": overshoot,
        "peak_at_window_edge": edge, "peak_at_first_sample": immediate,
        **({"latency_is_a_bound": (
            "the extremum is the FIRST post-shift sample: the response completed inside one timestep, so "
            "`time_to_peak_s` is bounded by the sampling interval and is not a measured latency.")}
           if immediate else {}),
        **({"overshoot_withheld": (
            f"the extremum is the LAST sample of the {_WINDOW_S:.0f}s response window, so the response had not "
            f"turned over inside it: this is a monotonic rise/fall still in progress, not a peak. Overshoot is "
            f"undefined here and is withheld rather than reported as a number that would read as an undershoot.")}
           if edge else {}),
    }


def mass_decomposition(seed_root: str, t_shift: float, window_s: float = 200.0) -> dict:
    """What the dry-mass jump at a shift is actually MADE OF — protein, RNA, DNA, or the metabolite pool.

    This exists because `growth_rate` is not a growth rate in the sense the name implies. Verified on disk:
    `Mass/instantaneous_growth_rate` equals d ln(dryMass)/dt to within 6e-06 (against a baseline of 2.7e-04),
    and `dryMass` INCLUDES `smallMoleculeMass`. So when amino acids appear in the medium and the cell fills its
    metabolite pool, the channel spikes — with no change in biosynthetic rate.

    Measured on the amino-acid upshift: 94.6-95.2% of the first post-shift dry-mass increment is small
    molecules and only 3-4% is protein, while d ln(protein)/dt goes 1.19x and keeps RISING (1.30x later) —
    a monotonic approach to a new rate, NOT the 12x spike-and-decay the channel shows. The mirror holds on the
    downshift: `growth_rate` goes NEGATIVE while d ln(protein)/dt is 1.04-1.07x of pre-shift, i.e. protein
    synthesis continues unchanged and the pool drains. "Growth halts and reverses" is true of the channel and
    false of the cell.

    Any shift claim resting on `growth_rate` must be read next to this."""
    import numpy as np

    from . import raw
    sos = raw.simout_dirs(seed_root)
    if not sos:
        return {}
    so = sos[0]

    def col(table, name):
        return np.asarray(raw.read_column(os.path.join(so, table, name)), dtype=float).ravel()

    try:
        t = col("Main", "time")
        dry = col("Mass", "dryMass")
        parts = {k: col("Mass", c) for k, c in
                 (("protein", "proteinMass"), ("rna", "rnaMass"), ("dna", "dnaMass"),
                  ("small_molecules", "smallMoleculeMass"))}
    except Exception:
        return {}
    i = int(np.searchsorted(t, t_shift))
    if i < 1 or i >= t.size:
        return {}
    d_dry = float(dry[i] - dry[i - 1])
    share = ({k: round(100.0 * float(v[i] - v[i - 1]) / d_dry, 1) for k, v in parts.items()}
             if d_dry else {})

    def rate(x, a, b):
        m = (t >= a) & (t <= b)
        return float(np.polyfit(t[m], np.log(x[m]), 1)[0]) if m.sum() >= 5 and (x[m] > 0).all() else float("nan")

    rates = {}
    for k, v in parts.items():
        pre = rate(v, max(t[0], t_shift - _BASELINE_S), t_shift - 1)
        post = rate(v, t_shift, t_shift + window_s)
        rates[k] = {"pre_per_s": None if np.isnan(pre) else float(f"{pre:.4e}"),
                    "post_per_s": None if np.isnan(post) else float(f"{post:.4e}"),
                    "fold": None if (np.isnan(pre) or np.isnan(post) or pre == 0) else round(post / pre, 2)}
    return {
        "first_step_d_dry_mass_fg": round(d_dry, 4),
        "first_step_share_pct": share,
        "log_rate_fold_change": rates,
        "warning": ("`growth_rate` is d ln(dryMass)/dt and dryMass INCLUDES the metabolite pool. Read "
                    "`first_step_share_pct`: if small_molecules dominates, the channel's excursion is pool "
                    "re-equilibration, not a change in biosynthetic rate. `log_rate_fold_change` for protein "
                    "and rna is the biosynthetic answer."),
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
    # A `growth_rate` excursion at a nutrient shift is dominated by the metabolite pool, so the decomposition
    # is attached automatically — the reader must not have to know to ask for it. Computed on EVERY seed, not
    # the first: a composition claim read off one run is exactly the kind of n=1 result this project keeps
    # having to withdraw. The across-seed spread is reported so the reader can see whether it is one run's
    # quirk (measured: 94.6/95.2/96.4% small molecules on the three upshift seeds — a sub-2% spread).
    decomp = {}
    if channel in _MASS_DERIVED:
        per = [(r.get("seed"), mass_decomposition(r["root"], t_shift)) for r in runs]
        per = [(s, d) for s, d in per if d]
        if per:
            shares = {}
            for key in ("protein", "rna", "dna", "small_molecules"):
                vals = [d["first_step_share_pct"].get(key) for _s, d in per
                        if isinstance(d.get("first_step_share_pct"), dict)
                        and d["first_step_share_pct"].get(key) is not None]
                if vals:
                    shares[key] = {"median": round(statistics.median(vals), 1),
                                   "min": round(min(vals), 1), "max": round(max(vals), 1),
                                   "n_seeds": len(vals)}
            decomp = {**per[0][1], "n_seeds": len(per), "seeds": [s for s, _d in per],
                      "share_pct_across_seeds": shares,
                      "per_seed": [{"seed": s, "share_pct": d.get("first_step_share_pct"),
                                    "protein_fold": (d.get("log_rate_fold_change") or {}).get("protein", {}
                                                                                              ).get("fold")}
                                   for s, d in per]}
    return {
        "design": design, "channel": channel, "declared_shift_s": t_shift, "seeds": used,
        **({"mass_decomposition": decomp} if decomp else {}),
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
