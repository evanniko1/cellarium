"""BV-9: cell-to-cell protein noise, against Taniguchi et al. 2010.

According to PubMed, Taniguchi et al. 2010 (Science 329:533, doi:10.1126/science.1188308) measured protein copy
numbers in single cells for a YFP-fusion library: almost all distributions are gamma-shaped, set at low expression by
transcription rate and burst size (noise falls with the mean, CV2 ~ 1/mean), while at high expression they are
dominated by extrinsic noise (a floor that does not fall with the mean).

The model's "cells" are snapshots: every generation of every wildtype/basal run with raw output is sampled at k
evenly spaced phases (reader.protein_noise), as a microscope sees an asynchronous population; a time-averaged mean
would remove the noise being measured. Seeds share every parameter, so the cell-to-cell parameter variation behind
extrinsic noise is absent unless the model generates it: the question is whether a floor appears at all, and at
what level. Compared as a scaling law, not gene by gene.

    WCECOLI_DOCKER=<code image> python evals/bv9_noise.py      # writes evals/results/bv9_noise.json
"""
from __future__ import annotations

import json
import math
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "evals"))
OUT = REPO / "evals" / "results" / "bv9_noise.json"

import bv6_overflow as B6  # noqa: E402

DESIGN = "wildtype/basal"
K = 5
BINS = [(1, 10), (10, 100), (100, 1000), (1000, 10000), (10000, 1e9)]


def scaling(mean: list[float], cv2: list[float]) -> dict:
    pts = [(m, c) for m, c in zip(mean, cv2) if m and c and m > 0 and c > 0 and math.isfinite(c)]
    bins = []
    for lo, hi in BINS:
        sel = [c for m, c in pts if lo <= m < hi]
        if sel:
            bins.append({"mean_range": [lo, hi if hi < 1e9 else None], "n_proteins": len(sel),
                         "median_cv2": round(statistics.median(sel), 5),
                         "median_cv2_times_mean": round(statistics.median(c * m for m, c in pts if lo <= m < hi), 3)})
    low = [(math.log10(m), math.log10(c)) for m, c in pts if 1 <= m < 100]
    high = [(math.log10(m), math.log10(c)) for m, c in pts if m >= 1000]

    def slope(xy):
        if len(xy) < 3:
            return None
        f = B6._ols([x for x, _ in xy], [y for _, y in xy])
        return round(f["slope"], 3) if f else None
    return {"n_proteins": len(pts), "bins": bins,
            "loglog_slope_low_1_to_100": slope(low), "loglog_slope_high_above_1000": slope(high),
            "floor_median_cv2_above_1000": round(statistics.median(c for m, c in pts if m >= 1000), 5)
            if any(m >= 1000 for m, _ in pts) else None}


def main() -> int:
    from cellarium import provenance, reader
    runs = B6._runs([DESIGN])[DESIGN]
    got = reader.protein_noise([r["root"] for r in runs], K)
    if "error" in got:
        print(json.dumps(got)[:500])
        return 2
    res = scaling(got["mean"], got["cv2"])
    out = {"spec": "BV-9", "design": DESIGN, "knowledge_base": f"{B6.KB} (the corpus fit), steady state",
           "n_runs": len(runs), "n_snapshots": got["n_snapshots"], "k_per_generation": got["k_per_generation"],
           "organism": ("Taniguchi et al. 2010 (doi:10.1126/science.1188308): gamma-distributed protein numbers; noise "
                        "falls with the mean at low expression (CV2 ~ 1/mean, slope -1 in log-log) and is dominated "
                        "by extrinsic noise at high expression (a floor)"),
           "in_sample": "emergent; seeds share every parameter, so cell-to-cell parameter variation is absent",
           "reader_note": ("protein counts as MonomerCounts records them; the five two-component sensors (BV-R1) are "
                           "not corrected here, which does not move a scaling law over about 4,000 proteins"),
           **res, "unreachable": got.get("_unreachable"),
           "computed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "environment": provenance.code_environment()}
    OUT.write_text(json.dumps(out, indent=1, default=float) + "\n", encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("n_runs", "n_snapshots", "n_proteins", "bins", "loglog_slope_low_1_to_100",
                                          "loglog_slope_high_above_1000", "floor_median_cv2_above_1000")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
