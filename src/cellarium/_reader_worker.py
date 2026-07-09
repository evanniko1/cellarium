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
    # mechanistic channels — the ppGpp cause->effect chain, so it's testable cross-run without per-species reads
    "ribosome_conc": ("GrowthLimits", "ribosome_conc"),               # the ppGpp target (down when ppGpp high)
    "fraction_trna_charged": ("GrowthLimits", "fraction_trna_charged"),  # the stringent trigger (AA limitation)
    "rela_conc": ("GrowthLimits", "rela_conc"),                       # the sensor
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


def _chan_1d(simout, table, column):
    """A summary channel as one scalar per timestep. Some listener columns are 2-D (per-species, e.g.
    fraction_trna_charged is per-tRNA) — collapse the non-time axes to a per-timestep mean."""
    a = np.asarray(_col(simout, table, column))
    if a.ndim > 1:
        a = np.nanmean(a.reshape(a.shape[0], -1), axis=1)
    return a.ravel()


def _gens(run_root):
    return sorted(p for p in glob.glob(os.path.join(run_root, "**", "simOut"), recursive=True) if os.path.isdir(p))


def _full_chrom(so):
    try:
        ids = _attr(so, "UniqueMoleculeCounts", "uniqueMoleculeIds")
        c = _col(so, "UniqueMoleculeCounts", "uniqueMoleculeCounts")
        return int(c[-1, ids.index("full_chromosome")]) if "full_chromosome" in ids else -1
    except Exception:
        return -1


def _chan_mean(so, name):
    table, column = SUMMARY_CHANNELS[name]
    try:
        return _finite(np.nanmean(_col(so, table, column)))
    except Exception:
        return None


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
            "divided": divided, "division_time_sec": (float(t[-1]) if divided else None),
            "growth_mean": _chan_mean(so, "growth_rate"),   # per-gen trajectory -> see approach to steady state
            "ppgpp_mean": _chan_mean(so, "ppgpp_conc")}


def _downsample(t, s, k=16):
    n = min(int(t.size), int(s.size))  # guard against any length mismatch (t vs a reduced channel)
    if n == 0:
        return []
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
            cols[name] = _chan_1d(so, table, column)
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
    # headline channels/dynamics from the LAST generation (most-adapted steady state); per-gen trajectory below
    stats, series, segments = _dynamics(gs[-1])
    return {"generations": [_generation(so, i) for i, so in enumerate(gs)],
            "channels": {n: s["mean"] for n, s in stats.items()},  # flat means (compat + easy SQL)
            "channel_stats": stats, "series": series, "media_segments": segments,
            "pathways": _pathways(gs[-1], _load_panel())}  # per-pathway proteome fractions (P2.1 depth)


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
    so = gs[-1]  # last generation = most-adapted steady state (matches mode_run)
    table, column, idattr = SPECIES_SOURCES[kind]
    ids = _attr(so, table, idattr)
    sid = _resolve(ids, species_id)
    if sid is None:
        return {"error": f"'{species_id}' not found in {kind}", "n_ids": len(ids)}
    s = _col(so, table, column)[:, ids.index(sid)]
    t = _col(so, "Main", "time").ravel()
    return {"species_id": sid, "kind": kind, "n_points": int(s.size),
            "mean": _finite(np.nanmean(s)), "min": _finite(np.nanmin(s)), "max": _finite(np.nanmax(s)),
            "first": _finite(s[0]), "last": _finite(s[-1]),
            "series": _downsample(t, s)}  # [t_sec, value] pairs (~16) for dynamics


def _load_panel():
    """The resolved pathway panel {pathway: [monomer_id]}, mounted alongside this worker. Absent -> no pathways."""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_pathway_resolved.json")
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return {}


def _pathways(so, panel):
    """Per-pathway PROTEOME FRACTION (pathway monomer count / total monomer count) — size-independent, so it
    reflects allocation, not just a bigger cell. Mean over the generation."""
    if not panel:
        return {}
    try:
        counts = np.asarray(_col(so, "MonomerCounts", "monomerCounts"), dtype=float)  # (T, nMonomers)
        ids = _attr(so, "MonomerCounts", "monomerIds")
    except Exception:
        return {}
    idx = {m: i for i, m in enumerate(ids)}
    total = counts.sum(axis=1)
    total[total == 0] = np.nan
    out = {}
    for pathway, monomers in panel.items():
        cols = [idx[m] for m in monomers if m in idx]
        if cols:
            out[pathway] = _finite(np.nanmean(counts[:, cols].sum(axis=1) / total))
    return out


def mode_gene_map(root):
    """Dump {symbol: monomer_id} from sim_data (symbol -> cistron_id -> monomer_id). Opt-in; unpickles kb."""
    import pickle
    kb = os.path.join(root, "kb", "simData.cPickle")
    if not os.path.exists(kb):
        return {"error": f"no sim_data at {kb} (run ParCa first)"}
    with open(kb, "rb") as f:
        sd = pickle.load(f)
    md, gd = sd.process.translation.monomer_data, sd.process.replication.gene_data
    c2m = dict(zip((str(x) for x in md["cistron_id"]), (str(x) for x in md["id"])))
    symbols = {}
    for k in range(len(gd)):
        m = c2m.get(str(gd["cistron_id"][k]))
        if m:
            symbols[str(gd["symbol"][k])] = m
    return {"symbols": symbols, "n": len(symbols)}


def _cplx_monomers(comp, cat):
    try:
        r = comp.get_monomers(cat)
    except Exception:
        return [cat]
    if isinstance(r, dict):
        return [str(x) for x in r.get("subunitIds", [])] or [cat]
    try:
        return [str(x) for x in r]
    except Exception:
        return [cat]


def mode_gene_scope(root):
    """Classify each gene's MECHANISTIC role in the model — the basis of the mechanistic-scope guardrail.
    is_metabolic: its monomer catalyses an FBA reaction (directly or as a complex subunit). is_tf: it is one
    of the (few) mechanistically-modeled transcription factors. Also returns the gene-KO variant index."""
    import pickle
    kb = os.path.join(root, "kb", "simData.cPickle")
    if not os.path.exists(kb):
        return {"error": f"no sim_data at {kb}"}
    with open(kb, "rb") as f:
        sd = pickle.load(f)
    md, gd = sd.process.translation.monomer_data, sd.process.replication.gene_data
    tr, comp = sd.process.transcription, sd.process.complexation
    cis2mono = dict(zip((str(x) for x in md["cistron_id"]), (str(x) for x in md["id"])))
    metabolic_roots = set()
    for cat in (str(x) for x in sd.process.metabolism.catalyst_ids):
        metabolic_roots.add(cat.split("[")[0])
        for m in _cplx_monomers(comp, cat):               # expand catalyst complexes to their subunit monomers
            metabolic_roots.add(str(m).split("[")[0])
    tf_syms = {str(v) for v in sd.process.transcription_regulation.tf_to_gene_id.values()}
    genes = {}
    for k in range(len(gd)):
        sym, cis = str(gd["symbol"][k]), str(gd["cistron_id"][k])
        mono = cis2mono.get(cis)
        try:
            idx = [int(i) for i in tr.cistron_id_to_rna_indexes(cis)]
        except Exception:
            idx = []
        genes[sym] = {"monomer_id": mono, "ko_index": (idx[0] + 1 if idx else None), "n_tu": len(idx),
                      "is_metabolic": bool(mono and mono.split("[")[0] in metabolic_roots),
                      "is_tf": sym in tf_syms}
    return {"n": len(genes), "n_tf": len(tf_syms), "genes": genes}


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


def _run_species_means(run_roots, table, column, idattr):
    """Per-species mean count for each run (last generation) -> list of {id: mean_count}, one per replicate."""
    per_run = []
    for root in run_roots:
        gs = _gens(root)
        if not gs:
            continue
        ids = _attr(gs[-1], table, idattr)
        means = np.asarray(_col(gs[-1], table, column), dtype=float).mean(axis=0)
        per_run.append(dict(zip(ids, means)))
    return per_run


def mode_differential(target_csv, ref_csv, kind, top, floor):
    """Seed-aware per-species differential with a PROPER test: Welch t across replicates per species + a
    Benjamini-Hochberg FDR over the ~thousands of species tested; default output keeps only q<=0.10. This kills
    the reproducibility/count-floor noise floor (the KO experiment showed both a mechanistic and an inert KO
    produced identical spurious 'reproducible' movers). fold-change is on seed-means; count floor still drops
    the lowest-count species (unstable t)."""
    from scipy import stats  # available in the model image

    table, column, idattr = SPECIES_SOURCES[kind]
    t_runs = _run_species_means(target_csv.split(","), table, column, idattr)
    r_runs = _run_species_means(ref_csv.split(","), table, column, idattr)
    if not t_runs or not r_runs:
        return {"error": "missing simOut (target or reference)"}
    if len(t_runs) < 2 or len(r_runs) < 2:
        return {"error": f"need >=2 replicates each for FDR stats (target={len(t_runs)}, reference={len(r_runs)})"}
    ids = set().union(*[set(d) for d in t_runs + r_runs])
    recs = []
    for i in ids:
        tvals = [d[i] for d in t_runs if i in d]
        rvals = [d[i] for d in r_runs if i in d]
        if len(tvals) < 2 or len(rvals) < 2:
            continue
        tm, rm = float(np.mean(tvals)), float(np.mean(rvals))
        if max(tm, rm) < floor:                       # count floor — very low counts give unstable t
            continue
        try:
            p = float(stats.ttest_ind(tvals, rvals, equal_var=False).pvalue)
        except Exception:
            p = 1.0
        if not math.isfinite(p):
            p = 1.0
        recs.append({"id": i, "target": round(tm, 1), "reference": round(rm, 1),
                     "log2fc": round(math.log2((tm + 1.0) / (rm + 1.0)), 2), "p": p})
    if recs:
        qvals = stats.false_discovery_control([r["p"] for r in recs], method="bh")
        for r, q in zip(recs, qvals):
            r["q"] = round(float(q), 4)
    sig = sorted((r for r in recs if r.get("q", 1.0) <= 0.10), key=lambda r: abs(r["log2fc"]), reverse=True)

    def clean(r):
        return {"id": r["id"], "target": r["target"], "reference": r["reference"], "log2fc": r["log2fc"], "q": r["q"]}

    return {"kind": kind, "n_compared": len(recs), "n_significant_fdr10": len(sig), "count_floor": floor,
            "n_target_runs": len(t_runs),
            "up": [clean(r) for r in sig if r["log2fc"] > 0][:top],
            "down": [clean(r) for r in sig if r["log2fc"] < 0][:top]}


def mode_list_species(run_root, kind, search=""):
    gs = _gens(run_root)
    if not gs:
        return {"error": "no simOut"}
    table, _column, idattr = SPECIES_SOURCES[kind]
    ids = _attr(gs[-1], table, idattr)
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
    elif mode == "gene_map":
        out = mode_gene_map(run_root)
    elif mode == "gene_scope":
        out = mode_gene_scope(run_root)
    elif mode == "differential":
        out = mode_differential(sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]), float(sys.argv[6]))
    else:
        out = {"error": f"unknown mode '{mode}'"}
    print("CELLARIUM_JSON:" + json.dumps(out))
