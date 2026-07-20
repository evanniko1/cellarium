"""Pure aggregation for the reader worker — the part that does NOT touch simOut.

`_reader_worker.py` imports `wholecell.io.tablereader` at module top, so it can only be imported inside the model
image; that made its numeric aggregation untestable on the host (the SCI-2c review caught a real bug in exactly
this seam because a mock stood in for it). This module holds the aggregation that operates on ALREADY-READ per-run
species-mean dicts — numpy + stdlib only, no wholecell — so `_reader_worker` imports it (works as a sibling in the
container and as `cellarium._reader_agg` on the host) and the logic is unit-testable off the sim.
"""

from __future__ import annotations

import math

import numpy as np


def gene_lfc_map(t_runs: list, r_runs: list, floor: float) -> dict:
    """Per-gene seed-mean log2 fold-change for EVERY gene present in >=1 target AND >=1 reference run above the
    count floor — the FULL distribution SCI-2's concordance needs (the significance-filtered `mode_differential`
    range-restricts Pearson/Deming). `t_runs`/`r_runs` are lists of {gene_id: count} per run. Returns
    {id: {log2fc, target, reference, n_target, n_reference}}."""
    if not t_runs or not r_runs:
        return {}
    ids = set().union(*[set(d) for d in t_runs + r_runs])
    out: dict = {}
    for i in ids:
        tvals = [d[i] for d in t_runs if i in d]
        rvals = [d[i] for d in r_runs if i in d]
        if not tvals or not rvals:                     # a gene must appear on BOTH sides to have a ratio
            continue
        tm, rm = float(np.mean(tvals)), float(np.mean(rvals))
        if max(tm, rm) < floor:                        # count floor — very low counts give an unstable ratio
            continue
        out[i] = {"log2fc": round(math.log2((tm + 1.0) / (rm + 1.0)), 4),
                  "target": round(tm, 1), "reference": round(rm, 1),
                  "n_target": len(tvals), "n_reference": len(rvals)}
    return out
