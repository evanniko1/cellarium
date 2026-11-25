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
    """Per-gene seed-mean log2 fold-change for EVERY gene present in >=1 target AND >=1 reference run whose
    HIGHER arm mean clears the count floor — the FULL distribution SCI-2's concordance needs (the
    significance-filtered `mode_differential` range-restricts Pearson/Deming). `t_runs`/`r_runs` are lists of
    {gene_id: count} per run. Returns {id: {log2fc, target, reference, n_target, n_reference}}."""
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
        # EITHER-arm is deliberate, not an accident of `max` vs `min`: the floor guards the PAIR's ratio, and
        # the +1 pseudocount just below already makes log2((tm+1)/(rm+1)) defined and stable when one arm
        # is zero — so a per-arm floor would discard exactly the genes a knockout contrast is about. Pinned by
        # tests/test_reader_agg.py::test_the_count_floor_is_applied_to_the_pair_and_not_per_arm, whose inputs
        # are chosen so the OR and AND readings disagree.
        if max(tm, rm) < floor:                        # count floor — very low counts give an unstable ratio
            continue
        out[i] = {"log2fc": round(math.log2((tm + 1.0) / (rm + 1.0)), 4),
                  "target": round(tm, 1), "reference": round(rm, 1),
                  "n_target": len(tvals), "n_reference": len(rvals)}
    return out


# ---- BV-R1: the two-component gap in wcEcoli's MonomerCounts listener -------------------------------------------
# `two_component_system.stoich_matrix_monomers()` keeps a complex's subunits only when they are in the system's
# own molecule list, which lacks the sensor monomers. The listener therefore removes a phosphorylated sensor
# complex and adds no protein back: 7 of 18 complexes in the shipped knowledge base (DcuS, NarX, PhoQ, PhoR,
# ArcB), each in exactly the condition that activates it. The equilibrium and complexation decompositions drop
# nothing (measured 2026-11-25). These two pure functions restore the dropped subunits from the bulk counts.

def tcs_dropped_subunits(complex_to_monomer: dict, tcs_molecule_names) -> dict:
    """{complex: {monomer: stoich}} for the subunits the listener's two-component matrix leaves out."""
    names = set(tcs_molecule_names)
    out = {}
    for cplx, subunits in complex_to_monomer.items():
        lost = {m: float(v) for m, v in subunits.items() if m not in names}
        if lost:
            out[cplx] = lost
    return out


def add_tcs_correction(monomer_means: dict, bulk_means: dict, dropped: dict) -> tuple[dict, dict]:
    """Monomer means with each dropped subunit added back (bulk count of its complex x stoichiometry).
    Returns (corrected means, the amount added per monomer, only where something was added)."""
    added: dict = {}
    for cplx, subunits in dropped.items():
        n = float(bulk_means.get(cplx) or 0.0)
        if n <= 0:
            continue
        for m, v in subunits.items():
            added[m] = added.get(m, 0.0) + n * v
    corrected = dict(monomer_means)
    for m, extra in added.items():
        corrected[m] = float(corrected.get(m) or 0.0) + extra
    return corrected, added


def align_subunits(dropped: dict, monomer_ids) -> dict:
    """Rename each dropped subunit to the monomer id the listener actually carries, when only its compartment
    differs. Measured 2026-11-25: the two-component map names DCUS-MONOMER[i] while the bulk species and
    MonomerCounts carry DCUS-MONOMER[c], so an exact-id match missed every DcuS copy. An exact id is kept; a base id
    with more than one compartment present is left as it is rather than guessed."""
    ids = list(monomer_ids)
    present = set(ids)
    by_base: dict = {}
    for i in ids:
        by_base.setdefault(str(i).split("[")[0], []).append(i)
    out = {}
    for cplx, subunits in dropped.items():
        row = {}
        for m, v in subunits.items():
            cands = by_base.get(str(m).split("[")[0], [])
            row[m if m in present or len(cands) != 1 else cands[0]] = v
        out[cplx] = row
    return out
