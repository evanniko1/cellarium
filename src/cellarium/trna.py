"""SCI-TRNA-1 — per-FAMILY charged-tRNA fractions, from raw simOut.

`fraction_trna_charged` is reported as a single number (~0.95). The raw listener is not one number: it is
**86 tRNA species × timesteps** (`GrowthLimits/fraction_trna_charged`, labelled by `uncharged_trna_ids`).
The reader collapses that to a per-timestep mean, and the mean is the wrong instrument for the question the
corpus keeps asking.

Why it matters, concretely. `argS` charges *arginine* tRNA. Knock it out and the arginine isoacceptors go
uncharged while the other ~19 amino-acid families stay loaded — so the aggregate barely moves (19/20 still
charged) and **the one measurement that shows the mechanism is averaged away**. Elf, Nilsson, Tenson &
Ehrenberg 2003 (*Science* 300:1718, PMID 12805541) established that this is how starvation actually behaves —
"selective charging", where some isoacceptors fall to near zero while others stay full; Dittmar 2005 measured
the arginine case directly. A single mean cannot represent selective charging by construction.

This module groups the 86 species into the ~20 amino-acid families by the tRNA gene-name prefix (`alaT`,
`alaU`, ... -> `ala`) and reports each family's charged fraction, so a synthetase knockout can be checked
against the family it should starve — and, just as importantly, against the families it should NOT.

Local-raw only (no Docker): reads the wcEcoli columns directly. Returns a structured error when the raw simOut
for a design is not on this machine, rather than a silent empty result.
"""

from __future__ import annotations

import json
import os
import re
import statistics
from collections import defaultdict

# tRNA ids look like 'alaT-tRNA[c]', 'argQ-tRNA[c]', 'selC-tRNA[c]'. The family is the leading 3 letters of the
# gene name, which is the amino-acid code by E. coli tRNA gene convention (alaT/alaU/alaV -> alanine).
_TRNA_ID = re.compile(r"^([a-zA-Z]{3})[A-Z0-9]*-tRNA")

# the three-letter tRNA gene prefixes that are NOT a standard amino-acid family
_SPECIAL = {"sel": "selenocysteine (selC — a special tRNA, not a standard family)"}


def family_of(trna_id: str) -> str | None:
    m = _TRNA_ID.match(str(trna_id or ""))
    return m.group(1).lower() if m else None


def _read(seed_root: str) -> tuple:
    """(matrix[timestep][species], species_ids, time) from one seed's LAST generation. Raises on unreadable."""
    import numpy as np

    from . import raw
    sos = raw.simout_dirs(seed_root)
    if not sos:
        raise FileNotFoundError(f"no simOut generations under {seed_root}")
    so = sos[-1]                      # last generation, matching how the summary channels are taken
    v = np.asarray(raw.read_column(os.path.join(so, "GrowthLimits", "fraction_trna_charged")))
    attrs = json.load(open(os.path.join(so, "GrowthLimits", "attributes.json"), encoding="utf-8"))
    ids = attrs.get("uncharged_trna_ids") or []
    t = np.asarray(raw.read_column(os.path.join(so, "Main", "time"))).ravel()
    if v.ndim != 2 or v.shape[1] != len(ids):
        raise ValueError(f"unexpected fraction_trna_charged shape {v.shape} vs {len(ids)} tRNA ids")
    return v, ids, t


def per_family(design: str, seed: int | None = None) -> dict:
    """Charged fraction per amino-acid tRNA family for one design (mean over the last generation's timesteps).

    Returns families sorted by charged fraction ASCENDING — the starved family first, which is the one the
    question is almost always about."""
    import numpy as np

    from . import raw
    runs = raw.seed_runs(design)
    if not runs:
        return {"error": f"no local raw simOut for '{design}' — this needs the run directory on this machine",
                "design": design}
    sel = [r for r in runs if seed is None or r.get("seed") == seed]
    if not sel:
        return {"error": f"seed {seed} has no local raw for '{design}'", "available_seeds":
                [r.get("seed") for r in runs]}
    per_seed_family: dict = defaultdict(list)
    used = []
    for r in sel:
        try:
            v, ids, _t = _read(r["root"])
        except Exception:
            continue
        used.append(r.get("seed"))
        col_mean = np.nanmean(v, axis=0)           # per-species mean over the generation
        byfam: dict = defaultdict(list)
        for i, tid in enumerate(ids):
            fam = family_of(tid)
            if fam:
                byfam[fam].append(float(col_mean[i]))
        for fam, vals in byfam.items():
            per_seed_family[fam].append(statistics.fmean(vals))
    if not used:
        return {"error": f"raw simOut for '{design}' could not be read (no GrowthLimits columns)"}
    fams = {f: round(statistics.fmean(v), 4) for f, v in per_seed_family.items()}
    ordered = sorted(fams.items(), key=lambda kv: kv[1])
    overall = round(statistics.fmean(list(fams.values())), 4)
    return {
        "design": design, "seeds": used, "n_families": len(fams),
        "aggregate_mean_over_families": overall,
        "families": [{"family": f, "charged_fraction": c,
                      **({"note": _SPECIAL[f]} if f in _SPECIAL else {})} for f, c in ordered],
        "most_starved": ordered[0][0] if ordered else None,
        "note": ("Charged fraction per amino-acid tRNA family (86 tRNA species grouped by gene prefix), mean "
                 "over the last generation. Sorted ascending: the STARVED family is first. The corpus's single "
                 "`fraction_trna_charged` is the mean across all of these, which hides selective charging "
                 "(Elf et al. 2003) — the mechanism a synthetase knockout acts through."),
    }


def selective_charging(design: str, reference: str = "wildtype/basal") -> dict:
    """Is this design's tRNA starvation SELECTIVE (one family collapses) or GLOBAL (all families fall together)?

    This is the measurement the aggregate cannot make. An aminoacyl-tRNA synthetase knockout should hit its OWN
    family far harder than the rest; a general translation or energy failure should depress everything. The
    verdict is the ratio between the worst family's drop and the median family's drop."""
    t = per_family(design)
    if "error" in t:
        return t
    ref = per_family(reference)
    if "error" in ref:
        return {**t, "reference_error": ref["error"]}
    rmap = {f["family"]: f["charged_fraction"] for f in ref["families"]}
    drops = []
    for f in t["families"]:
        base = rmap.get(f["family"])
        if base:
            drops.append({"family": f["family"], "charged": f["charged_fraction"], "reference": base,
                          "drop_pct": round(100.0 * (f["charged_fraction"] - base) / base, 1)})
    if not drops:
        return {**t, "error": "no shared families with the reference"}
    drops.sort(key=lambda d: d["drop_pct"])
    worst = drops[0]
    median_drop = statistics.median(d["drop_pct"] for d in drops)
    # selective = the worst family falls much further than the typical family
    selective = bool(worst["drop_pct"] < -5 and (median_drop - worst["drop_pct"]) > 10)
    return {
        "design": design, "reference": reference,
        "worst_family": worst, "median_drop_pct": round(median_drop, 1),
        "selectivity_gap_pp": round(median_drop - worst["drop_pct"], 1),
        "selective_charging": selective,
        "per_family": drops,
        "note": ("SELECTIVE charging (one family collapses while others hold) is the signature of a specific "
                 "aminoacyl-tRNA synthetase lesion (Elf et al. 2003, PMID 12805541); a GLOBAL fall implicates "
                 "translation/energy instead. `selectivity_gap_pp` is how many percentage points worse the worst "
                 "family fares than the median family. A signal to CHECK, not a diagnosis."),
    }
