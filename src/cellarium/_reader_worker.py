#!/usr/bin/env python
"""Reader worker — runs INSIDE the wcEcoli model image (where `wholecell` is importable).

Cellarium's host venv has no model; the model + TableReader live only in the image. So all simOut reading
happens here, and the host consumes compact JSON (printed on a `CELLARIUM_JSON:` line). Standalone:
numpy + wholecell only (no cellarium/pydantic imports). Names below are the model's public listener schema
and get pinned from a real `schema` dump.

Usage (invoked by cellarium.reader):
    python _reader_worker.py run    <run_root>
    python _reader_worker.py schema <run_root>
    python _reader_worker.py species <run_root> <kind> <species_id>
    python _reader_worker.py list_species <run_root> <kind> <search>
"""

import glob
import json
import math
import os
import sys

import numpy as np
from wholecell.io.tablereader import TableReader

SUMMARY_CHANNELS = {
    "growth_rate": ("Mass", "instantaneous_growth_rate"),
    "cell_mass": ("Mass", "cellMass"),
    "dry_mass": ("Mass", "dryMass"),
    "protein_mass": ("Mass", "proteinMass"),
    "rna_mass": ("Mass", "rnaMass"),
    "ppgpp_conc": ("GrowthLimits", "ppgpp_conc"),
    "fba_objective": ("FBAResults", "objectiveValue"),
}
SPECIES_SOURCES = {
    "protein": ("MonomerCounts", "monomerCounts", "monomerIds"),
    "mrna": ("RNACounts", "mRNA_cistron_counts", "mRNA_cistron_ids"),
    "metabolite": ("BulkMolecules", "counts", "objectNames"),
    "reaction_flux": ("FBAResults", "reactionFluxes", "reactionIDs"),
    "exchange_flux": ("FBAResults", "externalExchangeFluxes", "externalMoleculeIDs"),
}
SCHEMA_TABLES = ["Main", "Mass", "GrowthLimits", "FBAResults", "RNACounts",
                 "MonomerCounts", "UniqueMoleculeCounts", "BulkMolecules", "RnaSynthProb"]


def _finite(x):
    """JSON-safe float: None for nan/inf (e.g. growth_rate[0] is nan) so downstream JSON stays valid."""
    x = float(x)
    return x if math.isfinite(x) else None


def _col(simout, table, column):
    r = TableReader(os.path.join(simout, table))
    try:
        return np.asarray(r.readColumn(column))
    finally:
        r.close()


def _attr(simout, table, name):
    r = TableReader(os.path.join(simout, table))
    try:
        return [str(x) for x in r.readAttribute(name)]
    finally:
        r.close()


def _gens(run_root):
    return sorted(p for p in glob.glob(os.path.join(run_root, "**", "simOut"), recursive=True) if os.path.isdir(p))


def _full_chrom(so):
    try:
        ids = _attr(so, "UniqueMoleculeCounts", "uniqueMoleculeIds")
        c = _col(so, "UniqueMoleculeCounts", "uniqueMoleculeCounts")
        return int(c[-1, ids.index("full_chromosome")]) if "full_chromosome" in ids else -1
    except Exception:
        return -1


def _generation(so, i):
    t = _col(so, "Main", "time").ravel()
    n = int(t.size)
    fc = _full_chrom(so)
    try:
        fo = _col(so, "FBAResults", "objectiveValue").ravel()
        fba_ok = bool(np.isfinite(fo[-1]) and fo[-1] > 0)
    except Exception:
        fba_ok = True
    divided = fc == 2 and n > 10
    return {"index": i, "n_steps": n, "full_chromosome_end": fc, "fba_ok": fba_ok,
            "divided": divided, "division_time_sec": (float(t[-1]) if divided else None)}


def _downsample(t, s, k=16):
    n = int(s.size)
    idx = range(n) if n <= k else (int(round(i * (n - 1) / (k - 1))) for i in range(k))
    return [[round(float(t[i]), 1), _finite(s[i])] for i in idx]


def _media_segments(t, media, cols):
    """Contiguous media windows (from FBAResults/media_id) with per-channel means — captures the transient a
    whole-trajectory mean washes out (e.g. ppGpp pre- vs post-downshift)."""
    if not media or len(media) != int(t.size):
        return []
    segs, start = [], 0
    for i in range(1, len(media) + 1):
        if i == len(media) or media[i] != media[start]:
            sl = slice(start, i)
            segs.append({"media": media[start], "t0": _finite(t[start]), "t1": _finite(t[i - 1]),
                         "n": i - start, "means": {n: _finite(np.nanmean(v[sl])) for n, v in cols.items()}})
            start = i
    return segs


def _dynamics(so):
    """Per summary channel: stats + a downsampled trajectory; plus media-segment means for the whole run."""
    t = _col(so, "Main", "time").ravel()
    try:
        media = [str(x) for x in np.asarray(_col(so, "FBAResults", "media_id")).ravel()]
    except Exception:
        media = []
    cols = {}
    for name, (table, column) in SUMMARY_CHANNELS.items():
        try:
            cols[name] = _col(so, table, column).ravel()
        except Exception:
            continue
    stats = {n: {"mean": _finite(np.nanmean(v)), "min": _finite(np.nanmin(v)), "max": _finite(np.nanmax(v)),
                 "first": _finite(v[0]), "last": _finite(v[-1])} for n, v in cols.items()}
    series = {n: _downsample(t, v) for n, v in cols.items()}
    return stats, series, _media_segments(t, media, cols)


def mode_run(run_root):
    gs = _gens(run_root)
    if not gs:
        return {"generations": [], "channels": {}, "channel_stats": {}, "series": {}, "media_segments": []}
    stats, series, segments = _dynamics(gs[0])
    return {"generations": [_generation(so, i) for i, so in enumerate(gs)],
            "channels": {n: s["mean"] for n, s in stats.items()},  # flat means (compat + easy SQL)
            "channel_stats": stats, "series": series, "media_segments": segments}


def mode_schema(run_root):
    gs = _gens(run_root)
    if not gs:
        return {"error": "no simOut under " + run_root}
    so, out = gs[0], {"simOut": gs[0]}
    for t in SCHEMA_TABLES:
        p = os.path.join(so, t)
        if os.path.isdir(p):
            r = TableReader(p)
            try:
                out[t] = {"cols": list(r.columnNames()), "attrs": list(r.attributeNames())}
            finally:
                r.close()
    return out


def _resolve(ids, species_id):
    if species_id in ids:
        return species_id
    cand = [i for i in ids if i.split("[")[0] == species_id.split("[")[0]]
    return cand[0] if cand else None


def mode_species(run_root, kind, species_id):
    gs = _gens(run_root)
    if not gs:
        return {"error": "no simOut"}
    table, column, idattr = SPECIES_SOURCES[kind]
    ids = _attr(gs[0], table, idattr)
    sid = _resolve(ids, species_id)
    if sid is None:
        return {"error": f"'{species_id}' not found in {kind}", "n_ids": len(ids)}
    s = _col(gs[0], table, column)[:, ids.index(sid)]
    t = _col(gs[0], "Main", "time").ravel()
    return {"species_id": sid, "kind": kind, "n_points": int(s.size),
            "mean": _finite(np.nanmean(s)), "min": _finite(np.nanmin(s)), "max": _finite(np.nanmax(s)),
            "first": _finite(s[0]), "last": _finite(s[-1]),
            "series": _downsample(t, s)}  # [t_sec, value] pairs (~16) for dynamics


def mode_variant_map(root):
    """Load sim_data (kb) and dump the variant index maps the model uses, so KO/condition design panels can
    be built with indices that match the model's own ordering (gene_knockout: idx = gene position + 1, 0 =
    control; condition: idx -> ordered_conditions). Opt-in: unpickling sim_data is heavy."""
    import pickle
    kb = os.path.join(root, "kb", "simData.cPickle")
    if not os.path.exists(kb):
        return {"error": f"no sim_data at {kb} (run ParCa first)"}
    with open(kb, "rb") as f:
        sim_data = pickle.load(f)
    conditions = {i: str(c) for i, c in enumerate(sim_data.ordered_conditions)}
    rna_ids = [str(x) for x in sim_data.process.transcription.rna_data["id"]]
    genes = [{"ko_index": i + 1, "rna_id": rid} for i, rid in enumerate(rna_ids)]  # idx 0 is control
    return {"conditions": conditions, "n_genes": len(rna_ids), "genes": genes}


def mode_list_species(run_root, kind, search=""):
    gs = _gens(run_root)
    if not gs:
        return {"error": "no simOut"}
    table, _column, idattr = SPECIES_SOURCES[kind]
    ids = _attr(gs[0], table, idattr)
    s = search.lower()
    hits = [i for i in ids if s in i.lower()] if s else ids
    return {"kind": kind, "matches": hits[:40]}


if __name__ == "__main__":
    mode, run_root = sys.argv[1], sys.argv[2]
    if mode == "run":
        out = mode_run(run_root)
    elif mode == "schema":
        out = mode_schema(run_root)
    elif mode == "species":
        out = mode_species(run_root, sys.argv[3], sys.argv[4])
    elif mode == "list_species":
        out = mode_list_species(run_root, sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "")
    elif mode == "variant_map":
        out = mode_variant_map(run_root)
    else:
        out = {"error": f"unknown mode '{mode}'"}
    print("CELLARIUM_JSON:" + json.dumps(out))
