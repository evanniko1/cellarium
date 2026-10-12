"""Work-plan item 4c — a generation that did not divide must not silently parent the generations after it.

THE DEFECT. The simulator ends a generation either at division or when it reaches its time cap
(`Simulation.lengthSec`, 3 h by default; Cellarium never overrides it). A generation that reached the cap is
then split into daughters as if it had divided, so the generations after it descend from a cell that never
completed a cycle. Measured 2026-10-08: 10 lineages in the corpus have a generation marked `divided: false`
followed by further generations (dapA x4, argS@5% x3, rpmE x2, wildtype/basal s1). Run-level QC already marks
most of them non-reportable, but the per-generation readers (`compare_at_generation`, `trajectory`) admitted
any generation whose own QC was ok — including descendants of an undivided cell.

THE SECOND DEFECT, WHICH IS WHY DURATION IS NEEDED. `divided` is a PROXY: `full_chromosome_end == 2 and
n_steps > 10`. It can be False for a cell that did divide (chromosome count other than 2 at the end, e.g. a
re-initiated round) and True for a cell that hit the cap with two chromosomes. Only the generation's duration
separates "divided before the cap" from "stopped by the cap". The per-generation record therefore now carries
`t_start`/`t_end`, and this module classifies with duration when it is present and conservatively when not.

CLASSIFICATION of a generation that HAS a successor:
  * `time_capped`          duration known and within CAP_TOLERANCE_S of the cap — the successor is suspect;
  * `divided`              duration known and below the cap (the `divided` flag is ignored; when it says False
                           the record notes `flag_disagrees`);
  * `divided_unverified`   no duration, flag True — accepted, as before, but labelled;
  * `undivided_unverified` no duration, flag False — the successor is treated as suspect.
The last generation has no successor and is `terminal` (with `time_capped` noted if the duration shows it).

The generation that failed to divide is itself a real measurement of a non-dividing cell and is left to its
own QC verdict. Its DESCENDANTS are what is excluded.
"""

from __future__ import annotations

CAP_S = 3 * 60 * 60          # wcEcoli `Simulation.lengthSec` default; Cellarium passes no --length-sec
CAP_TOLERANCE_S = 30.0       # a capped generation ends within a few timesteps of the cap
SUSPECT = ("time_capped", "undivided_unverified")


def _duration(g: dict) -> float | None:
    a, b = g.get("t_start"), g.get("t_end")
    if a is None or b is None:
        return None
    try:
        return float(b) - float(a)
    except (TypeError, ValueError):
        return None


def classify(per_generation: list) -> list[dict]:
    """One status per generation, in index order. Input: the row's `per_generation` list of dicts."""
    gens = sorted((g for g in per_generation or [] if isinstance(g, dict) and g.get("i") is not None),
                  key=lambda g: int(g["i"]))
    out = []
    for k, g in enumerate(gens):
        dur = _duration(g)
        capped = dur is not None and dur >= CAP_S - CAP_TOLERANCE_S
        flag = g.get("divided")
        rec = {"i": int(g["i"]), "duration_s": round(dur, 1) if dur is not None else None, "divided_flag": flag}
        if k == len(gens) - 1:
            rec["status"] = "terminal"
            rec["time_capped"] = capped if dur is not None else None
        elif dur is not None:
            rec["status"] = "time_capped" if capped else "divided"
            if not capped and flag is False:
                rec["flag_disagrees"] = True
        else:
            rec["status"] = "divided_unverified" if flag is not False else "undivided_unverified"
        out.append(rec)
    return out


def first_suspect_parent(per_generation: list) -> int | None:
    """Index of the first generation that may not have divided yet has a successor, or None."""
    return next((c["i"] for c in classify(per_generation) if c["status"] in SUSPECT), None)


def is_descendant_of_undivided(per_generation: list, generation: int) -> bool:
    """True when `generation` descends from a generation that may have been split at the time cap."""
    k = first_suspect_parent(per_generation)
    return k is not None and generation > k


def summary(per_generation: list) -> dict:
    cl = classify(per_generation)
    k = next((c["i"] for c in cl if c["status"] in SUSPECT), None)
    return {"generations": cl, "first_suspect_parent": k,
            "excluded_generations": [c["i"] for c in cl if k is not None and c["i"] > k],
            "duration_known": all(c["duration_s"] is not None for c in cl) if cl else False}
