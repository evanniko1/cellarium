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

try:  # shared viability verdict (same rule store uses); this script's dir is on sys.path[0] in the container
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from viability_rules import verdict as _viability_verdict
except Exception:  # fallback keeps the worker self-contained if the sibling module is unreachable
    def _viability_verdict(min_dr, all_term, any_term, n_fba_fail, crashed=False, truncated=False):
        if crashed or truncated:
            return "inviable"
        if min_dr is None:
            return "unknown"
        if n_fba_fail and n_fba_fail > 0:
            return "inviable"
        if min_dr >= 0.9 and all_term:
            return "viable"
        return "inviable" if (min_dr < 0.6 or not any_term) else "impaired"

# H-6: the pure numeric aggregation lives host-side in _reader_agg (numpy-only, no wholecell) so it's unit-testable
# off the sim; here it's a sibling import (the worker dir is on sys.path, set above). Runs only in the container —
# the host never imports this module (the wholecell import above fails first).
from _reader_agg import gene_lfc_map  # noqa: E402

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
    # deep-dive: the WHOLE-CELL components beyond the bulk layer — active ribosomes/RNAP, full chromosomes,
    # replication forks, active DnaA boxes, etc. (translation/transcription/replication machinery, not metabolism).
    "unique": ("UniqueMoleculeCounts", "uniqueMoleculeCounts", "uniqueMoleculeIds"),
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
    # t_start/t_end are what let qc.check_result see END-TRUNCATION: a generation whose data stops before the
    # division that ended it still satisfies `fc == 2 and n > 10`, so `divided` is True and division_time_sec
    # is silently the last RECORDED step rather than the real division. Only the NEXT generation's start time
    # reveals the gap, so the times have to travel with the generation. MEASURED 2026-08-03:
    # wildtype_374656/000000 gen 0 stops at 2047 s while gen 1 starts at 2530 s (19% of the generation
    # missing) and was recorded qc='ok', reportable=True.
    return {"index": i, "n_steps": n, "full_chromosome_end": fc, "fba_ok": fba_ok,
            "t_start": (float(t[0]) if n else None), "t_end": (float(t[-1]) if n else None),
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
    # `Environment/media_id` FIRST. `FBAResults/media_id` is a fixed-width column sized from its first value, so
    # a run starting in `minimal` (7 chars) gets <U7 and silently truncates a later `minimal_plus_amino_acids`
    # to exactly `minimal` — the shift vanishes and the segment means average pre- and post-shift together
    # (measured: a stored fba_objective of 7.88 for a quantity that goes 0.81 -> 14.05). The Environment
    # listener writes <U25 and is not truncated; values are space-padded, so strip. Falls back to the old
    # column for runs recorded before that listener existed.
    media = []
    for table, column in (("Environment", "media_id"), ("FBAResults", "media_id")):
        try:
            media = [str(x).rstrip() for x in np.asarray(_col(so, table, column)).ravel()]
        except Exception:
            continue
        if media:
            break
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


def _lineage_viability(gens):
    """Viability of ONE lineage (a per-seed run_root's generations): does each cell divide? Facts only — no
    verdict label at this level (a lineage can't see the REQUESTED depth, so 'died early' is a cross-seed
    signal; roll up with mode_viability or a manifest GROUP BY). See CORPUS_OBSERVATIONS.md §J."""
    n = len(gens)
    nd = sum(1 for g in gens if g.get("divided"))
    nfail = sum(1 for g in gens if not g.get("fba_ok", True))
    dts = [g.get("division_time_sec") for g in gens if g.get("division_time_sec") is not None]
    return {"n_cells": n, "n_divided": nd, "division_rate": round(nd / n, 3) if n else 0.0,
            "gens_reached": n, "terminal_divided": bool(gens[-1].get("divided")) if gens else False,
            "n_fba_failures": nfail,
            "median_division_time_sec": (round(float(np.median(dts)), 1) if dts else None)}


def mode_run(run_root):
    gs = _gens(run_root)
    if not gs:
        return {"generations": [], "channels": {}, "channel_stats": {}, "series": {}, "media_segments": [],
                "viability": _lineage_viability([])}
    panel = _load_panel()
    # headline channels/dynamics from the LAST generation (most-adapted steady state); per-gen trajectory below
    stats, series, segments = _dynamics(gs[-1])
    generations = [_generation(so, i) for i, so in enumerate(gs)]
    return {"generations": generations,
            "channels": {n: s["mean"] for n, s in stats.items()},  # flat means (compat + easy SQL)
            "channel_stats": stats, "series": series, "media_segments": segments,
            "viability": _lineage_viability(generations),  # per-lineage division facts (first-class channel, §J)
            "pathways": _pathways(gs[-1], panel),            # per-pathway proteome fractions (P2.1 depth)
            "species_panel": _species_panel(gs[-1], panel)}  # per-species terminal + coarse trajectory (scope A)


def _cell_viability(so):
    """Per-cell viability from the canonical wcEcoli division signal: a cell that replicated its chromosome
    (full_chromosome == 2) over a real trajectory (n_steps > 10) reached DIVISION. Also flag FBA-solver failure
    (the numerical breakdown mode). This is the readout Gherman et al. 2025 use — viable == the cell divides —
    which does NOT reroute away like a graded growth channel does."""
    try:
        n = int(_col(so, "Main", "time").ravel().size)
    except Exception:
        return {"n_steps": 0, "divided": False, "fba_ok": False, "division_time_sec": None,
                "full_chromosome_end": -1, "readable": False}
    fc = _full_chrom(so)
    try:
        fo = _col(so, "FBAResults", "objectiveValue").ravel()
        fba_ok = bool(np.isfinite(fo[-1]) and fo[-1] > 0)
    except Exception:
        fba_ok = True
    t = _col(so, "Main", "time").ravel()
    divided = bool(fc == 2 and n > 10)
    return {"n_steps": n, "divided": divided, "fba_ok": fba_ok,
            "division_time_sec": (float(t[-1]) if divided else None),
            "t_start": (float(t[0]) if n else None), "t_end": (float(t[-1]) if n else None),
            "full_chromosome_end": int(fc), "readable": True}


def _parse_lineage(so):
    parts = so.replace("\\", "/").split("/")
    for i, p in enumerate(parts):
        if p.startswith("generation_"):
            try:
                return (parts[i - 1] if i > 0 else None), int(p.split("_")[-1])
            except Exception:
                return (parts[i - 1] if i > 0 else None), None
    return None, None


def mode_viability(run_root):
    """Re-score a run by VIABILITY: does each cell in the lineage divide? Aggregates the per-cell division signal
    over seeds x generations into a run-level verdict. A metabolic KO that 'reroutes' is VIABLE (divides normally);
    a machinery KO (gltX) is INVIABLE (its terminal cell fails to divide / the FBA solver breaks)."""
    gs = _gens(run_root)
    if not gs:
        return {"error": "no simOut under " + run_root}
    seeds = {}
    for so in gs:
        seed, gen = _parse_lineage(so)
        v = _cell_viability(so)
        v["gen"] = gen
        seeds.setdefault(seed, []).append(v)
    per_seed, n_cells, n_div, n_fba_fail, div_times = {}, 0, 0, 0, []
    for seed, cells in seeds.items():
        cells.sort(key=lambda c: (c["gen"] if c["gen"] is not None else 0))
        nd = sum(1 for c in cells if c["divided"])
        n_cells += len(cells); n_div += nd
        n_fba_fail += sum(1 for c in cells if not c["fba_ok"])
        div_times += [c["division_time_sec"] for c in cells if c["division_time_sec"] is not None]
        per_seed[seed] = {"gens_reached": len(cells),
                          "max_gen": max((c["gen"] for c in cells if c["gen"] is not None), default=None),
                          "n_divided": nd, "all_divided": nd == len(cells),
                          "terminal_divided": bool(cells[-1]["divided"]),
                          "terminal_fba_ok": bool(cells[-1]["fba_ok"])}
    gens = [s["gens_reached"] for s in per_seed.values()] or [0]
    rate = (n_div / n_cells) if n_cells else 0.0
    all_terminal = bool(per_seed) and all(s["terminal_divided"] for s in per_seed.values())
    any_terminal = any(s["terminal_divided"] for s in per_seed.values())
    # verdict on MIN per-seed rate (one collapsing seed flags the design), via the shared rule store also uses
    min_dr = min((s["n_divided"] / s["gens_reached"] for s in per_seed.values() if s["gens_reached"]), default=None)
    verdict = _viability_verdict(min_dr, all_terminal, any_terminal, n_fba_fail)
    return {"n_seeds": len(per_seed), "n_cells": n_cells, "n_divided": n_div,
            "division_rate": round(rate, 3), "min_division_rate": (round(min_dr, 3) if min_dr is not None else None),
            "n_fba_failures": n_fba_fail,
            "gens_reached": {"min": min(gens), "max": max(gens), "mean": round(sum(gens) / len(gens), 2)},
            "median_division_time_sec": (round(float(np.median(div_times)), 1) if div_times else None),
            "terminal_division_all_seeds": all_terminal, "verdict": verdict, "seeds": per_seed}


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


def _species_panel(so, panel):
    """Per-SPECIES (monomer) mean, terminal count, and a coarse k=16 trajectory for the curated panel proteins
    (the union of monomers across pathways) — scope-A depth at the species level, so read_species/differential
    answer for panel members straight from the shard (no raw read). Non-panel species stay HF-only. Mirrors
    mode_species, but batched over the panel from the LAST generation."""
    monomers = sorted({m for ms in panel.values() for m in ms})
    if not monomers:
        return {}
    try:
        counts = np.asarray(_col(so, "MonomerCounts", "monomerCounts"), dtype=float)  # (T, nMonomers)
        ids = _attr(so, "MonomerCounts", "monomerIds")
        t = _col(so, "Main", "time").ravel()
    except Exception:
        return {}
    idx = {m: i for i, m in enumerate(ids)}
    out = {}
    for m in monomers:
        j = idx.get(m)
        if j is None:
            continue
        s = counts[:, j]
        out[m] = {"mean": _finite(np.nanmean(s)), "last": _finite(s[-1]), "series": _downsample(t, s)}
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
    cistron_symbols = {}          # cistron_id -> symbol: the id space the mrna reader returns (SCI-2c annotation)
    for k in range(len(gd)):
        sym, cis = str(gd["symbol"][k]), str(gd["cistron_id"][k])
        cistron_symbols[cis] = sym
        m = c2m.get(cis)
        if m:
            symbols[sym] = m
    return {"symbols": symbols, "cistron_symbols": cistron_symbols, "n": len(symbols)}


def _load_essential_genes():
    """Ground-truth essential-gene SYMBOLS from wcEcoli's own validation set (Baba 2006 Keio + Joyce 2006,
    glucose-minimal; 406 genes). Read from the checkout at dump time — NOT vendored into Cellarium (D3 license).
    Columns: FrameID, rnaID, proteinID, proteinLoc, gene. Returns a set (empty if the file isn't present)."""
    for p in ("validation/ecoli/flat/essential_genes.tsv",
              os.path.join(os.environ.get("WCECOLI_DIR", ""), "validation/ecoli/flat/essential_genes.tsv")):
        try:
            syms = set()
            with open(p) as f:
                for line in f:
                    if line.startswith("#") or line.startswith("FrameID"):
                        continue
                    parts = [x.strip().strip('"') for x in line.rstrip().split("\t")]
                    if len(parts) >= 5 and parts[4]:
                        syms.add(parts[4])
            if syms:
                return syms
        except Exception:
            continue
    return set()


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

    def cat_roots(cat):  # a catalyst (monomer or complex) -> its constituent monomer roots
        roots = {str(cat).split("[")[0]}
        for m in _cplx_monomers(comp, str(cat)):
            roots.add(str(m).split("[")[0])
        return roots

    metabolic_roots, sole_roots = set(), set()   # sole = subunit of the ONLY catalyst of some reaction
    for _rxn, cats in sd.process.metabolism.reaction_catalysts.items():
        cats = [str(c) for c in cats]
        rxn_roots = set().union(*[cat_roots(c) for c in cats]) if cats else set()
        metabolic_roots |= rxn_roots
        if len(cats) == 1:
            sole_roots |= rxn_roots
    # kinetic-constraint enzymes: the ONLY enzymes whose count actually bounds a reaction flux in the
    # kinetics-constrained FBA. A KO of one of these forces its reaction toward 0; a KO of any OTHER metabolic
    # enzyme leaves the flux unconstrained (why fabI/glmS/gltA KOs had no growth effect).
    kin_roots = set()
    for e in sd.process.metabolism.kinetic_constraint_enzymes:
        kin_roots |= cat_roots(str(e))
    tf_syms = {str(v) for v in sd.process.transcription_regulation.tf_to_gene_id.values()}
    # central-dogma machinery: ribosome / RNAP / replisome / aminoacyl-tRNA synthetases. Maximally mechanistic,
    # currently mislabeled 'inert'. Calibration: a full KO of essential machinery CRASHES the sim (gltX 4/4).
    machinery = {}  # monomer root -> role
    mg = sd.molecule_groups

    def add_machinery(ids, role):
        for i in ids:
            for rt in cat_roots(str(i)):
                machinery.setdefault(rt, role)

    add_machinery(getattr(mg, "ribosomal_proteins", []), "ribosomal")
    add_machinery(getattr(mg, "RNAP_subunits", []), "rnap")
    add_machinery(list(getattr(mg, "replisome_trimer_subunits", [])) +
                  list(getattr(mg, "replisome_monomer_subunits", [])), "replisome")
    add_machinery(getattr(sd.process.transcription, "synthetase_names", []), "aaRS")
    essential_ref = _load_essential_genes()  # GROUND TRUTH: Baba 2006 (Keio) + Joyce 2006, glucose-minimal
    genes = {}
    for k in range(len(gd)):
        sym, cis = str(gd["symbol"][k]), str(gd["cistron_id"][k])
        mono = cis2mono.get(cis)
        root = mono.split("[")[0] if mono else None
        try:
            idx = [int(i) for i in tr.cistron_id_to_rna_indexes(cis)]
        except Exception:
            idx = []
        genes[sym] = {"monomer_id": mono, "ko_index": (idx[0] + 1 if idx else None), "n_tu": len(idx),
                      "is_metabolic": bool(root and root in metabolic_roots),
                      "is_sole_catalyst": bool(root and root in sole_roots),
                      "is_kinetically_constraining": bool(root and root in kin_roots),  # KO can bind a flux
                      "is_machinery": bool(root and root in machinery),  # central-dogma machinery subunit
                      "machinery_role": (machinery.get(root) if root else None),
                      # ground-truth essentiality (external benchmark, NOT a model output) — lets classify_gene
                      # compare the model's KO prior against reality. None = not in the reference list at all.
                      "essential_ref": (sym in essential_ref) if essential_ref else None,
                      "is_tf": sym in tf_syms}
    return {"n": len(genes), "n_metabolic": sum(1 for v in genes.values() if v["is_metabolic"]),
            "n_sole_catalyst": sum(1 for v in genes.values() if v["is_sole_catalyst"]),
            "n_kinetically_constraining": sum(1 for v in genes.values() if v["is_kinetically_constraining"]),
            "n_machinery": sum(1 for v in genes.values() if v["is_machinery"]),
            "n_essential_ref": (sum(1 for v in genes.values() if v["essential_ref"]) if essential_ref else 0),
            "essential_ref_source": ("Baba 2006 (Keio) + Joyce 2006, glucose-minimal (wcEcoli validation set)"
                                     if essential_ref else None),
            "n_tf": len(tf_syms), "genes": genes}


def mode_fba_essentiality(root, genes_csv):
    """DEPRECATED — under-sensitive; NOT an essentiality oracle. Do not use this to decide essentiality. Use the
    ground-truth `essential_reference` flag in gene_scope (Baba/Joyce) for the verdict, a GRADED-capacity
    perturbation for a measurable in-silico effect, or the D4 tier-2 hard-demand/feasibility FBA once built.

    (Mechanism, kept as a finding.) FBA single-deletion (Joyce 2006 style) on the model's OWN network: instantiate
    the homeostatic FBA, solve baseline (objective = # of biomass-metabolite concentration targets met), then for
    each gene disable the reactions it SOLELY catalyses (upper bound -> 0) and re-solve; a dropped objective would
    mean a biomass target became unproducible.

    WHY IT'S UNDER-SENSITIVE (the D4 root cause): the objective is deviation-minimizing over concentration targets
    with NO growth term, so with unconstrained enzyme bounds the 9,612-reaction network reroutes to satisfy all 173
    targets for EVERY single sole-catalyst deletion tested (0/35 essential, incl. known-essential lpxC/coaA/kdsB/
    dapA/murC). A sensitive version needs enzyme-CONSTRAINED dynamic bounds (the running sim) or hard target demands
    + a feasibility test (D4 tier-2)."""
    import pickle
    from collections import defaultdict
    kb = os.path.join(root, "kb", "simData.cPickle")
    if not os.path.exists(kb):
        return {"error": f"no sim_data at {kb}"}
    with open(kb, "rb") as f:
        sd = pickle.load(f)
    from models.ecoli.processes.metabolism import FluxBalanceAnalysisModel
    comp = sd.process.complexation
    fba = FluxBalanceAnalysisModel(sd).fba
    rxn_ids = set(fba.getReactionIDs())

    def cat_roots(cat):
        return {str(cat).split("[")[0]} | {str(m).split("[")[0] for m in _cplx_monomers(comp, str(cat))}

    sole_rxns = defaultdict(list)   # monomer root -> reactions it is the SOLE catalyst of (present in the FBA)
    for rxn, cats in sd.process.metabolism.reaction_catalysts.items():
        cats = [str(c) for c in cats]
        if len(cats) == 1 and rxn in rxn_ids:
            for rt in cat_roots(cats[0]):
                sole_rxns[rt].append(rxn)
    md, gd = sd.process.translation.monomer_data, sd.process.replication.gene_data
    cis2mono = dict(zip((str(x) for x in md["cistron_id"]), (str(x) for x in md["id"])))
    sym2root = {}
    for k in range(len(gd)):
        mono = cis2mono.get(str(gd["cistron_id"][k]))
        if mono:
            sym2root[str(gd["symbol"][k])] = mono.split("[")[0]

    fba.solve(3)
    obj0 = float(fba.getObjectiveValue())
    out = {}
    for sym in genes_csv.split(","):
        root = sym2root.get(sym)
        rxns = sole_rxns.get(root, []) if root else []
        if not rxns:
            out[sym] = {"n_rxn": 0, "essential": False, "reason": "no sole-catalyst reactions in the FBA network"}
            continue
        fba.setReactionFluxBounds(rxns, upperBounds=[0.0] * len(rxns), raiseForReversible=False)  # disable
        try:
            fba.solve(3)
            obj = float(fba.getObjectiveValue())
        except Exception:
            obj = None
        fba.setReactionFluxBounds(rxns, upperBounds=[np.inf] * len(rxns), raiseForReversible=False)  # restore
        out[sym] = {"n_rxn": len(rxns), "obj_baseline": round(obj0, 2),
                    "obj_ko": (round(obj, 2) if obj is not None else None),
                    "targets_lost": (round(obj0 - obj, 2) if obj is not None else None),
                    "essential": (obj is None or obj < obj0 - 0.5)}
    return {"deprecated": True,
            "warning": ("under-sensitive (0/35 essential incl. known-essential genes) — the homeostatic objective "
                        "has no growth term, so the network reroutes around every single deletion. Use the "
                        "gene_scope `essential_reference` (Baba/Joyce) benchmark for the verdict."),
            "obj_baseline": round(obj0, 2), "n_reactions": len(rxn_ids), "genes": out}


def mode_reroute_diagnosis(gene, ko_csv, wt_csv):
    """Diagnose a VIABLE metabolic KO: did the KO actually zero the enzyme's FBA flux, yet the cell stayed viable?
    If so the 'reroute' is a MATHEMATICAL ARTIFACT — the model bypasses an enzyme real biology can't (the soft
    homeostatic objective never hard-requires that flux). Maps gene -> monomer -> complex -> reactions, then
    seed+generation-averages sum|flux| through those reactions in the KO runs vs the WT runs (robust: the enzyme's
    own reactions going to 0 is deterministic, unlike a whole-network compensating-flux diff which is seed-noisy)."""
    import pickle
    ko_roots = [r for r in ko_csv.split(",") if r]
    wt_roots = [r for r in wt_csv.split(",") if r]
    if not ko_roots or not wt_roots:
        return {"error": "need at least one KO run root and one WT run root"}
    def find_kb(start):  # kb lives at the sim_path root (cellarium/kb); run roots are <root>/<variant>/<seed>
        d = start.rstrip("/\\")
        for _ in range(6):
            cand = os.path.join(d, "kb", "simData.cPickle")
            if os.path.exists(cand):
                return cand
            d = os.path.dirname(d)
        return None

    kb = find_kb(ko_roots[0])
    if not kb:
        return {"error": f"no sim_data (kb) found above {ko_roots[0]}"}
    with open(kb, "rb") as f:
        sd = pickle.load(f)
    comp = sd.process.complexation
    md, gd = sd.process.translation.monomer_data, sd.process.replication.gene_data
    cis2mono = dict(zip((str(x) for x in md["cistron_id"]), (str(x) for x in md["id"])))
    sym2mono = {}
    for k in range(len(gd)):
        m = cis2mono.get(str(gd["cistron_id"][k]))
        if m:
            sym2mono[str(gd["symbol"][k])] = m.split("[")[0]
    mono = sym2mono.get(gene)
    if not mono:
        return {"error": f"gene '{gene}' has no monomer in the model"}

    def subunits(cid):
        try:
            return [str(m).split("[")[0] for m in comp.get_monomers(cid)["subunitIds"]]
        except Exception:
            return [str(cid).split("[")[0]]

    rxns = sorted({r for r, cats in sd.process.metabolism.reaction_catalysts.items()
                   for c in cats if mono in subunits(str(c)) or mono == str(c).split("[")[0]})
    if not rxns:
        return {"gene": gene, "monomer": mono, "n_reactions": 0,
                "note": "gene catalyses no FBA reaction (non-metabolic or absent from the network) — not a reroute case."}

    def mean_flux(roots):
        vals = []
        for root in roots:
            for so in _gens(root):
                try:
                    r = TableReader(os.path.join(so, "FBAResults"))
                    ids = list(r.readAttribute("reactionIDs"))
                    f = np.nanmean(np.asarray(r.readColumn("reactionFluxes"), dtype=float), axis=0)
                    r.close()
                    d = {i: f[j] for j, i in enumerate(ids)}
                    vals.append(sum(abs(d.get(x, 0.0)) for x in rxns))
                except Exception:
                    continue
        return (float(np.mean(vals)), len(vals)) if vals else (None, 0)

    kf, nk = mean_flux(ko_roots)
    wf, nw = mean_flux(wt_roots)
    disabled = kf is not None and kf < 1e-6
    artifact = bool(disabled and wf and wf > 1e-6)
    return {"gene": gene, "monomer": mono, "n_reactions": len(rxns),
            "ko_flux": (round(kf, 5) if kf is not None else None), "ko_cells": nk,
            "wt_flux": (round(wf, 5) if wf is not None else None), "wt_cells": nw,
            "enzyme_flux_disabled_in_ko": disabled, "reroute_is_artifact": artifact,
            "note": ("ARTIFACT: the enzyme carries flux in WT but 0 in the viable KO — the model bypasses it via a "
                     "feasible-but-unreal flux. Real biology with 0 flux here would die if the enzyme is uniquely "
                     "essential; cross-check mechanistic_scope's essentiality benchmark (`model_UNDER_predicts`)."
                     if artifact else
                     "No artifact signature: the enzyme carried no WT flux, or the KO did not zero it.")}


def mode_kb_content_hash(root):
    """A hash of what a SIMULATION reads out of sim_data, not of the pickle's bytes.

    Why this exists. `provenance.kb_provenance` hashes `simData.cPickle` byte-for-byte, and the corpus uses
    that `kb_sha256` to decide which runs are comparable. MEASURED 2026-08-03: two ParCa runs of the SAME
    image, same inputs, same `--cpus 14`, minutes apart, produced DIFFERENT file hashes
    (`94325a1e…` / `9881c39e…`) whose `exp_ppgpp` was bit-identical (0 of 3276 entries differing) and whose
    simulations were bitwise identical over all 2530 timesteps on both ppGpp and cellMass. So ParCa's
    behaviour is deterministic and only its serialisation is not: the file hash is sound as
    "same hash => same kb" but UNSOUND as "different hash => different experiment". Left uncorrected it
    refuses legitimate pooling and overcounts distinct baselines.

    The hash walks the object graph rather than naming fields, because any hand-picked field list is a guess
    about what matters and would silently miss whatever it omitted. Ordering is by attribute/key name so it
    does not depend on dict insertion order; numpy arrays contribute dtype, shape and raw bytes. Callables,
    modules and anything that raises on access are skipped and COUNTED — a hash that quietly skipped half the
    object would compare equal for the wrong reason, so the counts are returned and must be checked.

    VERIFIED 2026-08-03, both directions:
      * the two ParCa fits above, with DIFFERENT file hashes, hash IDENTICALLY here (`99ab9368…`) — the false
        difference the file hash reports is gone;
      * a knowledge base that genuinely differs (native tree with phnE1 reverted to `mRNA`) hashes
        differently (`624d5a9f…`) — the real difference is preserved.
      * coverage on a real sim_data: 415,137 nodes walked, 17,714 arrays, 311,048 scalars, 20 skipped,
        0 hit the depth cap.

    KNOWN LIMIT, also measured: this answers "same knowledge base", NOT "same simulation output". The fork kb
    (`c1bd1018…`) and the phnE1-reverted native kb (`624d5a9f…`) hash differently yet give bitwise identical
    simulations for `gltX+relA+spoT`, because they differ only in fields that design never reads. Same hash
    implies same output; different hash does not imply different output.
    """
    import hashlib
    import pickle
    kb = os.path.join(root, "kb", "simData.cPickle")
    if not os.path.exists(kb):
        return {"error": f"no sim_data at {kb} (run ParCa first)"}
    with open(kb, "rb") as f:
        sim_data = pickle.load(f)

    h = hashlib.sha256()
    stats = {"arrays": 0, "scalars": 0, "skipped": 0, "max_depth_hit": 0, "nodes": 0}
    seen: set[int] = set()
    MAX_DEPTH = 12

    def walk(obj, depth: int) -> None:
        stats["nodes"] += 1
        if depth > MAX_DEPTH:
            stats["max_depth_hit"] += 1
            h.update(b"<depth>")
            return
        if obj is None or isinstance(obj, (bool, int, float, complex, str, bytes)):
            h.update(repr(obj).encode("utf-8", "replace"))
            stats["scalars"] += 1
            return
        if isinstance(obj, np.ndarray):
            a = np.ascontiguousarray(obj)
            h.update(f"ndarray|{a.dtype.str}|{a.shape}|".encode())
            h.update(a.tobytes() if a.dtype.kind != "O" else repr(a.tolist()).encode("utf-8", "replace"))
            stats["arrays"] += 1
            return
        if isinstance(obj, np.generic):
            h.update(f"npscalar|{obj.dtype.str}|{obj!r}".encode("utf-8", "replace"))
            stats["scalars"] += 1
            return
        if callable(obj) or isinstance(obj, type(os)):        # bound methods, functions, modules
            stats["skipped"] += 1
            return
        if id(obj) in seen:                                    # cycles, and shared sub-objects counted once
            h.update(b"<seen>")
            return
        seen.add(id(obj))
        try:
            if isinstance(obj, dict):
                h.update(b"{")
                for k in sorted(obj, key=repr):
                    h.update(repr(k).encode("utf-8", "replace"))
                    walk(obj[k], depth + 1)
                h.update(b"}")
                return
            if isinstance(obj, (list, tuple, set, frozenset)):
                items = sorted(obj, key=repr) if isinstance(obj, (set, frozenset)) else obj
                h.update(b"[")
                for v in items:
                    walk(v, depth + 1)
                h.update(b"]")
                return
            d = getattr(obj, "__dict__", None)
            if isinstance(d, dict):
                h.update(f"<{type(obj).__name__}>".encode())
                for k in sorted(d):
                    if k.startswith("__"):
                        continue
                    h.update(k.encode())
                    walk(d[k], depth + 1)
                return
            h.update(repr(obj).encode("utf-8", "replace"))     # units, Decimal, anything with a stable repr
            stats["scalars"] += 1
        except Exception:
            stats["skipped"] += 1

    walk(sim_data, 0)
    return {"kb_content_sha256": h.hexdigest(), "kb_path": kb, "max_depth": MAX_DEPTH, "stats": stats}


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

    up = [clean(r) for r in sig if r["log2fc"] > 0][:top]
    down = [clean(r) for r in sig if r["log2fc"] < 0][:top]
    # SP-2b informative truncation: a stratified sample of the SIGNIFICANT movers dropped below the top cut, so a
    # real mid-rank mover is at least visible (the agent can raise `top` to see the rest). Evenly spaced by rank.
    shown_ids = {m["id"] for m in up + down}
    dropped = [r for r in sig if r["id"] not in shown_ids]
    if len(dropped) <= 3:
        mid = dropped
    else:
        picks = sorted({round(i * (len(dropped) - 1) / 2) for i in range(3)})   # ~first / middle / last dropped
        mid = [dropped[i] for i in picks]

    return {"kind": kind, "n_compared": len(recs), "n_significant_fdr10": len(sig), "count_floor": floor,
            "n_target_runs": len(t_runs), "up": up, "down": down,
            "mid_rank_sample": [clean(r) for r in mid]}


def mode_gene_lfc(target_csv, ref_csv, kind, floor):
    """All-gene seed-mean log2fc (SCI-2c) — the UNBIASED full-distribution reader for the sim-vs-RNA-seq concordance.
    Unlike mode_differential it applies NO significance filter (that range-restricts the correlation); it returns the
    seed-mean log2fc for every gene above the count floor. Concordance uses the seed-mean (seeds are not replicates),
    so no per-gene test — the across-seed spread rides along as n_target/n_reference for an optional weight."""
    table, column, idattr = SPECIES_SOURCES[kind]
    t_runs = _run_species_means(target_csv.split(","), table, column, idattr)
    r_runs = _run_species_means(ref_csv.split(","), table, column, idattr)
    if not t_runs or not r_runs:
        return {"error": "missing simOut (target or reference)"}
    lfc = gene_lfc_map(t_runs, r_runs, floor)   # H-6: pure aggregation lives host-side in _reader_agg (testable)
    return {"kind": kind, "n_genes": len(lfc), "count_floor": floor,
            "n_target_runs": len(t_runs), "n_reference_runs": len(r_runs), "lfc": lfc}


def mode_list_species(run_root, kind, search=""):
    gs = _gens(run_root)
    if not gs:
        return {"error": "no simOut"}
    table, _column, idattr = SPECIES_SOURCES[kind]
    ids = _attr(gs[-1], table, idattr)
    s = search.lower()
    hits = [i for i in ids if s in i.lower()] if s else ids
    return {"kind": kind, "matches": hits[:40]}


def mode_deg_rate_provenance(root, per_unit="0"):
    """For every mRNA transcription unit: is its degradation rate a FIT, a CONSTRAINT, or a DEFAULT (PARCA-4)?

    Three situations collapse into indistinguishable floats in `sim_data`, and the difference is the whole
    point:

      * DETERMINED   — inferred from measurements (or measured directly).
      * ON A BOUND   — the NNLS solution hit a wall. `min_deg_rates[is_mRNA] = mRNA_cistron_deg_rates.min()`
                       is a global rate floor taken from the single slowest measured cistron, with a symmetric
                       clip at the fastest. What is reported is the wall's value, not an inference.
      * IMPUTED      — the unit's cistrons had NO measurement, so they were assigned
                       `average_mRNA_cistron_half_life`, the MEAN of the reported mRNA cistron half-lives
                       (`transcription.py:339`). Nothing measured this unit at all.

    THIS FUNCTION REPLACES `mode_deg_rate_bounds`, WHICH UNDER-REPORTED BY ~3x. That version asked "which
    units sit on a bound", because the floor was what PARCA-4 recorded — and answered reassuringly: 245 units,
    4.59% of mRNA expression. Measured here, the IMPUTED class is larger: 602 units and 7.48%, for a combined
    847 of 3,133 units (27%) carrying 12.07% of transcription on a value that is not a fit. A number that
    looks complete and is a third of the truth is worse than no number, because nobody checks it twice.

    The imputation constant is read from `sim_data` (`average_mRNA_cistron_half_life`), never hardcoded and
    never inferred from the value — so it stays correct when the fit changes.

    WHAT IS DELIBERATELY *NOT* COUNTED AS A DEFECT: repeated values from ROUNDING. The flat file stores
    half-lives to one decimal (`ROUND_N_DECIMALS = 1`), so ~40 units sharing 1.5 min is a genuine measured
    value shared after rounding, not an imputation — verified against `rna_half_lives.tsv`. A naive
    "point mass" detector flags those and would report the table as far worse than it is. `resolution` below
    is therefore reported as CONTEXT, not as a defect measure.
    """
    import pickle
    kb = os.path.join(root, "kb", "simData.cPickle")
    if not os.path.exists(kb):
        return {"error": f"no sim_data at {kb} (run ParCa first)"}
    import numpy as np
    with open(kb, "rb") as f:
        sd = pickle.load(f)
    t = sd.process.transcription
    rna = t.rna_data
    dr = rna["deg_rate"]
    dr = np.asarray(dr.asNumber() if hasattr(dr, "asNumber") else dr, dtype=float)
    is_m = np.asarray(rna["is_mRNA"], dtype=bool)
    with np.errstate(divide="ignore", invalid="ignore"):
        half_life = np.log(2) / dr / 60.0

    avg = t.average_mRNA_cistron_half_life
    try:
        import wholecell.utils.units as _u
        avg_min = float(avg.asNumber(_u.min))
    except Exception:
        avg_min = float(avg.asNumber() if hasattr(avg, "asNumber") else avg)

    hl_m = half_life[is_m]
    slowest, fastest = float(np.nanmax(hl_m)), float(np.nanmin(hl_m))
    on_floor = is_m & (np.abs(half_life - slowest) < 1e-9)
    on_ceiling = is_m & (np.abs(half_life - fastest) < 1e-9)
    imputed = is_m & (np.abs(half_life - avg_min) < 1e-9) & ~on_floor & ~on_ceiling
    not_a_fit = on_floor | on_ceiling | imputed

    exp = np.asarray(t.rna_expression["basal"], dtype=float)
    tot = float(exp[is_m].sum()) or 1.0
    ids = [str(x) for x in rna["id"]]

    def cls(mask):
        return {"n_units": int(mask.sum()),
                "pct_units": round(100.0 * int(mask.sum()) / max(int(is_m.sum()), 1), 2),
                "pct_expression": round(100.0 * float(exp[mask].sum()) / tot, 3)}

    top = sorted(((float(exp[i]), ids[i]) for i in np.where(not_a_fit)[0]), reverse=True)[:8]
    distinct = int(len(np.unique(np.round(hl_m, 9))))

    # EVERY expression figure above is for ONE condition. `rna_expression` is a dict of 67 regulatory
    # conditions and the not-a-fit share moves with them — 11.165% under PHOSPHO-ARCA__active, 15.491% under
    # PHOSPHO-ARCA__inactive. Quoting `basal` alone is under-specified rather than wrong (it is 12.087%
    # against a 12.081% median), but a reader weighing whether 12% matters should see that a regulatory state
    # can put it at 15%. Carried WITH the number so the caveat cannot be separated from it.
    spread = []
    try:
        for cond, vec in t.rna_expression.items():
            v = np.asarray(vec, dtype=float)
            denom = float(v[is_m].sum())
            if denom > 0:
                spread.append((100.0 * float(v[not_a_fit].sum()) / denom, str(cond)))
    except Exception:
        spread = []
    spread.sort()
    across = {}
    if spread:
        mid = spread[len(spread) // 2][0]
        across = {"n_conditions": len(spread), "condition_used": "basal",
                  "min_pct": round(spread[0][0], 3), "min_condition": spread[0][1],
                  "max_pct": round(spread[-1][0], 3), "max_condition": spread[-1][1],
                  "median_pct": round(mid, 3)}

    # PER-UNIT, opt-in. Aggregate counts cannot SCORE a variant: "did the units that were not fits improve"
    # needs to know WHICH units those were, so a later fit can be intersected against this one. Only the three
    # not-a-fit classes are listed — DETERMINED is their complement, which keeps the payload ~854 ids instead
    # of 3,133 and makes the set operations the scoring actually needs direct. Off by default because the
    # summary above is what a human reads and a thousand ids buried in it is not a summary.
    units = {}
    if str(per_unit) in ("1", "true", "True"):
        # {id: pct_of_mrna_expression}, not a bare id list. A delta over ids alone counts UNITS, and the
        # acceptance criteria are written in EXPRESSION terms — measured, the coverage filter regresses 45
        # units and +3.295 percentage points, and from ids alone you cannot tell whether that was 45 trivial
        # units or three heavily-transcribed ones. A dict gives the set operations AND the weights.
        def _w(mask):
            return {ids[i]: round(100.0 * float(exp[i]) / tot, 6) for i in np.where(mask)[0]}
        units = {"floor": _w(on_floor), "ceiling": _w(on_ceiling), "imputed": _w(imputed),
                 "determined_is_the_complement": int(is_m.sum()) - int(not_a_fit.sum())}
    return {
        "n_mrna_units": int(is_m.sum()),
        "rate_floor_as_half_life_min": round(slowest, 4),
        "rate_ceiling_as_half_life_min": round(fastest, 4),
        "imputation_constant_min": round(avg_min, 6),
        "on_floor": cls(on_floor), "on_ceiling": cls(on_ceiling), "imputed_average": cls(imputed),
        "not_a_fit": cls(not_a_fit),
        "most_expressed_not_a_fit": [{"id": i, "pct_of_mrna_expression": round(100.0 * e / tot, 4)}
                                     for e, i in top],
        **({"not_a_fit_across_conditions": across} if across else {}),
        "resolution": {"distinct_half_lives": distinct,
                       "pct_distinct": round(100.0 * distinct / max(int(is_m.sum()), 1), 1),
                       "caveat": ("CONTEXT, not a defect measure: the flat file rounds half-lives to one "
                                  "decimal, so genuinely measured units share values. Only the three classes "
                                  "above are 'not a fit'.")},
        **({"units_not_a_fit": units} if units else {}),
        "note": ("A unit that is on a bound or imputed did not get a fitted half-life. sim_data stores all "
                 "three classes as the same kind of float, so any claim resting on one of these transcripts "
                 "rests on a constraint or a population mean, not on a measurement of that transcript."),
    }


# =============================================================================================================
# PARCA-4 Stage 2 — re-solve the degradation-rate estimator OFFLINE.
#
# The estimator (wcEcoli `transcription.py:701-737`) solves ONE nonnegative least-squares problem: the
# cistron x transcription-unit relative-abundancy matrix A times the per-TU degradation rates x should
# reproduce the per-cistron rates b. Every input to that solve is either IN `sim_data` or recomputable from
# it, so the whole thing can be re-run against a knowledge base in seconds — no ParCa, no container rebuild,
# no new arm. That is what makes evaluating candidate estimators affordable at all; a rebuild per variant
# would be ~7 minutes plus a comparability arm each.
#
# THE ONE INPUT THAT IS NOT PRESERVED, stated up front because every number below inherits it. The abundancy
# matrix is built from `expression, _ = fit_rna_expression(cistron_expression['basal'])` at build time, and
# ParCa OVERWRITES `cistron_expression['basal']` afterwards (`fit_sim_data_1.py:964`). The re-solve therefore
# reconstructs A from the POST-fit cistron expression, which is close but not identical. Measured: the
# baseline re-solve reproduces the shipped fit on 3,270 of 3,276 units to <1e-12. All 6 that differ are
# UNMEASURED units whose relative-abundance weights moved when that vector was overwritten; one (TU0-6626)
# has no information at all in the reconstructed system. `fidelity` reports this every time rather than
# leaving it to a footnote, and the comparison that matters is always variant vs BASELINE-RE-SOLVE
# (identical inputs), never variant vs shipped vector.
#
# WHAT THE BLOCK CENSUS FOUND, and it revises PARCA-4's own diagnosis. The rank deficiency of 214 columns is
# real, but it is not 214 ambiguous co-transcription splits: 209 of the 214 are columns that are ENTIRELY
# ZERO — transcription units whose fitted expression is 0, so every cistron gives them relative abundance 0
# and they appear in no equation whatsoever. Only 5 are genuine within-block dependencies. This matters for
# the remedy: a per-unit bound cannot touch a unit that is in no equation, while a soft prior sets it to the
# prior by construction and says so.
# =============================================================================================================

# Flat import: this file is always RUN as a script (`python /cellarium_reader/_reader_worker.py ...`),
# in the container and in native mode alike, so its own directory is on sys.path. It is never imported
# as part of the package -- `from wholecell...` at module scope makes that impossible off the image.
from deg_estimator import (  # noqa: E402, I001
    DEG_VARIANTS as _DEG_VARIANTS,
    nnls_blocks as _nnls_blocks,
    per_unit_floor as _per_unit_floor,
    pooled_cistron_rates as _pooled_cistron_rates,
    cv_metrics as _cv_metrics,
    fold_of as _fold_of,
    paired_delta as _paired_delta,
    solve_nnls as _solve_nnls,
)


def _deg_rate_inputs(sd):
    """Rebuild every input the estimator consumed, from sim_data alone."""
    import numpy as np
    from scipy.sparse import csr_matrix
    from wholecell.utils import units as _u

    t = sd.process.transcription
    rna = t.rna_data
    n = len(rna["id"])
    ids = [str(x) for x in rna["id"]]
    is_mRNA = np.asarray(rna["is_mRNA"], dtype=bool)
    is_rtRNA = np.asarray(rna["is_rRNA"], dtype=bool) | np.asarray(rna["is_tRNA"], dtype=bool)
    measured = np.asarray(rna["deg_rate_is_measured"], dtype=bool)
    shipped = np.asarray(rna["deg_rate"].asNumber(1 / _u.s), dtype=float)

    expression, _res = t.fit_rna_expression(t.cistron_expression["basal"])
    ci, ri, v = [], [], []
    for c_idx, c_id in enumerate(t.cistron_data["id"]):
        tus = t.cistron_id_to_rna_indexes(c_id)
        w = np.zeros(len(tus))
        for i, tu in enumerate(tus):
            ci.append(c_idx)
            ri.append(tu)
            w[i] = expression[tu]
        # wcEcoli's own rule: a cistron with no expression splits uniformly across its TUs.
        w = np.full(len(w), 1.0 / len(w)) if w.sum() == 0 else w / w.sum()
        v.extend(w)
    ci, ri, v = np.array(ci), np.array(ri), np.array(v)
    A = csr_matrix((v, (ci, ri)), shape=(ci.max() + 1, ri.max() + 1))
    # A cistron that maps to two TUs, one of which has zero expression, stores an EXPLICIT 0.0. `fast_nnls`
    # partitions on `A.nonzero()`, which drops those, so a block census that keeps them sees edges the solver
    # does not and reports a unit as constrained when nothing constrains it. Drop them here so the structural
    # analysis and the solver are looking at the same matrix.
    A.eliminate_zeros()

    b = np.asarray(t.cistron_data["deg_rate"].asNumber(1 / _u.s), dtype=float)
    c_is_mRNA = np.asarray(t.cistron_data["is_mRNA"], dtype=bool)
    imputed_rate = float(np.log(2) / t.average_mRNA_cistron_half_life.asNumber(_u.s))
    # A cistron was MEASURED iff its rate is not bit-exactly the imputation constant. Value-matching is
    # exact here rather than heuristic: the constant is a 64-bit mean of the reported set, and a measured
    # half-life colliding with it to the last bit does not happen (checked: the nearest measured value is
    # 6 ULP away).
    c_measured = c_is_mRNA & (np.abs(b - imputed_rate) > 1e-18)
    return {"t": t, "n": n, "ids": ids, "A": A, "b": b, "expression": expression,
            "is_mRNA": is_mRNA, "is_rtRNA": is_rtRNA, "measured": measured, "shipped": shipped,
            "c_is_mRNA": c_is_mRNA, "c_measured": c_measured, "imputed_rate": imputed_rate,
            "mRNA_cistron_rates": b[c_is_mRNA],
            "stable_rate": float(np.log(2) / sd.constants.stable_RNA_half_life.asNumber(_u.s))}


def mode_deg_rate_resolve(root, variant="baseline", param=""):
    """Re-solve the degradation-rate estimator offline and report what the result looks like (PARCA-4 Stage 2).

    Variants:
      * `baseline`       — the shipped procedure, re-run here. The reference every other variant is compared
                           against, because it shares their inputs exactly.
      * `ridge`          — no floor and no clip; a Tikhonov pull toward the population prior instead
                           (`param` = lambda, default 0.1). A wall creates a point mass of units sitting
                           exactly on it; a penalty does not, and the per-unit pull IS the provenance measure.
      * `per_unit_bound` — the floor is taken from each TU's own measured cistrons rather than from the single
                           slowest transcript in the organism.
      * `hierarchical`   — unmeasured cistrons are imputed from their OPERON's measured cistrons, shrunk
                           toward the global mean (`param` = kappa, default 5).

    THIS REPORTS, IT DOES NOT SCORE. Distinctness is trivially manufacturable — add noise and every point mass
    disappears — so nothing here says a variant is better. Held-out predictive accuracy on measurements the
    fit never saw is the criterion, it is Stage 3, and its protocol is pre-registered in BACKLOG.md before any
    variant runs.
    """
    import pickle

    import numpy as np

    if variant not in _DEG_VARIANTS:
        return {"error": "unknown variant %r; expected one of %s" % (variant, list(_DEG_VARIANTS))}
    kb = os.path.join(root, "kb", "simData.cPickle")
    if not os.path.exists(kb):
        return {"error": "no sim_data at %s (run ParCa first)" % kb}
    with open(kb, "rb") as f:
        sd = pickle.load(f)

    inp = _deg_rate_inputs(sd)
    A, n, ids = inp["A"], inp["n"], inp["ids"]
    is_mRNA, is_rtRNA, measured = inp["is_mRNA"], inp["is_rtRNA"], inp["measured"]
    shipped, mrna_rates = inp["shipped"], inp["mRNA_cistron_rates"]
    b = inp["b"]
    notes = []

    # ---- the floor / prior each variant shifts by, and the b vector it targets --------------------------
    if variant == "hierarchical":
        b, n_pooled = _pooled_cistron_rates(
            inp["t"].operons, b, inp["c_is_mRNA"], inp["c_measured"], inp["imputed_rate"],
            kappa=float(param or 5.0))
        notes.append("%d unmeasured mRNA cistrons imputed from their operon instead of the global mean"
                     % n_pooled)
    n_no_bound = None
    if variant == "per_unit_bound":
        floor_full, n_no_bound = _per_unit_floor(
            A, is_mRNA, b, inp["c_measured"], float(mrna_rates.min()))
        notes.append("%d mRNA units have NO measured cistron anywhere in them, so no per-unit bound exists "
                     "for them and they keep the global floor" % n_no_bound)
    else:
        floor_full = np.zeros(n)
        floor_full[is_mRNA] = float(mrna_rates.min())

    if variant == "ridge":
        lam = float(param or 0.1)
        prior = np.zeros(n)
        prior[is_mRNA] = inp["imputed_rate"]
        A_no = A[:, ~measured]
        rhs = b - A[:, measured].dot(shipped[measured])
        x = _solve_nnls(A_no, rhs, prior=prior[~measured], lam=lam)
        est = np.zeros(n)
        est[measured] = shipped[measured]
        est[~measured] = x
        notes.append("no floor and no clip: lambda=%g pulls each unit toward the population prior" % lam)
    else:
        floor = floor_full[~measured]
        A_no, A_with = A[:, ~measured], A[:, measured]
        rhs = b - A_with.dot(shipped[measured]) - A_no.dot(floor)
        x = _solve_nnls(A_no, rhs)
        est = np.zeros(n)
        est[measured] = shipped[measured]
        est[~measured] = x + floor
        mx = float(mrna_rates.max())
        est[np.logical_and(is_mRNA, est > mx)] = mx
    est[is_rtRNA] = inp["stable_rate"]

    # ---- structure: which units are UNDETERMINED, from the block ranks ---------------------------------
    A_un = A[:, ~measured]
    blocks = _nnls_blocks(A_un)
    unmeasured_idx = np.where(~measured)[0]
    deficiency = 0
    undetermined = np.zeros(n, dtype=bool)
    zero_info = np.zeros(n, dtype=bool)
    passthrough = np.zeros(n, dtype=bool)
    c_measured = inp["c_measured"]
    for rows, cols in blocks:
        if len(rows) == 0:
            # No equation touches this column. Not "poorly determined" — the system is silent about it.
            zero_info[unmeasured_idx[cols]] = True
            undetermined[unmeasured_idx[cols]] = True
            passthrough[unmeasured_idx[cols]] = True
            deficiency += len(cols)
            continue
        if not c_measured[rows].any():
            # Every cistron in this block was itself imputed, so the whole right-hand side IS the imputation
            # constant. Any solver — bounded, ridged, anything — returns that constant. This class is not an
            # estimator problem at all; it is the cistron-level imputation passing through.
            passthrough[unmeasured_idx[cols]] = True
        sub = np.asarray(A_un[rows][:, cols].todense())
        r = int(np.linalg.matrix_rank(sub)) if sub.size else 0
        if r < len(cols):
            deficiency += len(cols) - r
            undetermined[unmeasured_idx[cols]] = True

    # ---- what the answer looks like --------------------------------------------------------------------
    exp = np.asarray(inp["t"].rna_expression["basal"], dtype=float)
    tot = float(exp[is_mRNA].sum()) or 1.0
    with np.errstate(divide="ignore", invalid="ignore"):
        hl = np.log(2) / est / 60.0
    # Grouped at 9 decimals (60 ns), NOT by exact float equality. Two units given the same imputation
    # constant can land on floats a few ULP apart after the floor shift and the division, and exact-equality
    # grouping then reports the same point mass twice at half its size — which reads as the defect being
    # smaller than it is.
    hl_r = np.round(hl, 9)
    finite_m = is_mRNA & np.isfinite(hl_r)
    on_floor = finite_m & (hl_r == np.round(float(np.nanmax(hl[finite_m])), 9))
    vals, counts = np.unique(hl_r[is_mRNA][np.isfinite(hl_r[is_mRNA])], return_counts=True)
    order = np.argsort(-counts)[:6]
    masses = []
    for k in order:
        m = is_mRNA & (hl_r == vals[k])
        masses.append({"half_life_min": round(float(vals[k]), 9), "n_units": int(counts[k]),
                       "pct_units": round(100.0 * int(counts[k]) / int(is_mRNA.sum()), 3),
                       "pct_mrna_expression": round(100.0 * float(exp[m].sum()) / tot, 4)})

    out = {
        "variant": variant, "param": param or None, "root": root,
        "inputs": {"n_units": n, "n_mrna_units": int(is_mRNA.sum()),
                   "n_measured_units": int(measured.sum()),
                   "n_mrna_cistrons": int(inp["c_is_mRNA"].sum()),
                   "n_measured_mrna_cistrons": int(inp["c_measured"].sum()),
                   "imputed_half_life_min": round(float(np.log(2) / inp["imputed_rate"] / 60.0), 6)},
        "structure": {"n_unmeasured_columns": int((~measured).sum()), "n_blocks": len(blocks),
                      "rank_deficiency": deficiency,
                      "units_undetermined": int(undetermined.sum()),
                      "units_with_zero_information": int(zero_info.sum()),
                      "zero_information_units_on_the_floor": int((zero_info & on_floor).sum()),
                      "pct_mrna_expression_zero_information": round(
                          100.0 * float(exp[zero_info & is_mRNA].sum()) / tot, 4),
                      "units_imputation_passthrough": int((passthrough & is_mRNA).sum()),
                      "pct_mrna_expression_passthrough": round(
                          100.0 * float(exp[passthrough & is_mRNA].sum()) / tot, 4),
                      "note": ("A unit inside a rank-deficient block has NO unique solution — the estimator "
                               "returns one arbitrary point of a null space. Curating the input cannot fix "
                               "that, which is why the coverage filter relocated the floor without reducing "
                               "the count. `units_with_zero_information` is the sharper sub-class: those "
                               "columns are ENTIRELY ZERO because the unit's fitted expression is 0, so no "
                               "equation mentions them and the value returned is whatever the default is.")},
        "point_masses": masses,
        "largest_point_mass_pct_units": masses[0]["pct_units"] if masses else None,
        "distinct_half_lives": int(len(vals)),
        "notes": notes,
        "not_scored": ("Descriptive only. Any scheme can manufacture distinct values, so the disappearance "
                       "of a point mass is NOT evidence of a better estimator. Stage 3 scores held-out "
                       "predictive accuracy on measurements the fit never saw."),
    }

    # ---- fidelity: how close is the offline re-solve to what ParCa actually shipped? --------------------
    d = np.abs(est - shipped)
    diff = np.where(d > 1e-12)[0]
    out["fidelity"] = {
        "n_units_matching_shipped": int(n - len(diff)),
        "n_units_differing": int(len(diff)),
        "max_abs_difference": float(d.max()),
        "differing_units": [{"id": ids[i], "shipped": float(shipped[i]), "resolved": float(est[i]),
                             "undetermined": bool(undetermined[i])} for i in np.argsort(-d)[:10]
                            if d[i] > 1e-12],
        "all_differing_are_undetermined": bool(len(diff) == 0 or undetermined[diff].all()),
        "why": ("The abundancy matrix is built from `fit_rna_expression(cistron_expression['basal'])`, and "
                "ParCa OVERWRITES `cistron_expression['basal']` after the estimator has run "
                "(fit_sim_data_1.py:964), so the estimator's own input is not preserved in the artifact. The "
                "re-solve reconstructs it from the post-fit vector. Where the shipped answer was determined "
                "by the data the two agree; where it was not, both are arbitrary picks in a null space."),
        "read_this_way": ("Compare a variant against the BASELINE RE-SOLVE, never against the shipped "
                          "vector — only the former shares its inputs."),
    }
    if variant != "baseline":
        out["fidelity"]["caveat"] = ("For a non-baseline variant these differences are the VARIANT's effect "
                                     "and the input gap combined, and cannot be separated. Use the baseline "
                                     "run's fidelity block to size the input gap.")
    if n_no_bound is not None:
        out["units_without_a_per_unit_bound"] = n_no_bound
    return out


def _resolve_once(inp, variant, param, b, measured_cistrons):
    """One full estimator run for a given variant, given a b vector and which cistrons count as measured.

    Factored out of `mode_deg_rate_resolve` so cross-validation runs the SAME code path a full-data solve
    does. A CV harness that reimplements the estimator scores its own reimplementation.
    """
    import numpy as np

    n, A, is_mRNA = inp["n"], inp["A"], inp["is_mRNA"]
    measured, shipped = inp["measured"], inp["shipped"]
    c_is_mRNA = inp["c_is_mRNA"]
    mrna_rates = b[c_is_mRNA]
    # The floor and the clip are derived from the b vector IN PLAY, exactly as the shipped code derives them
    # from `cistron_deg_rates` — so holding a measurement out removes it from the floor too, which is the
    # difference between a held-out fold and a leaked one.
    global_floor = float(mrna_rates.min())

    if variant == "per_unit_bound":
        floor_full, n_no_bound = _per_unit_floor(A, is_mRNA, b, measured_cistrons, global_floor)
    else:
        floor_full, n_no_bound = np.zeros(n), None
        floor_full[is_mRNA] = global_floor

    if variant == "ridge":
        prior = np.zeros(n)
        prior[is_mRNA] = float(np.log(2) / (np.log(2) / mrna_rates).mean())
        x = _solve_nnls(A[:, ~measured], b - A[:, measured].dot(shipped[measured]),
                        prior=prior[~measured], lam=float(param or 0.1))
        est = np.zeros(n)
        est[measured] = shipped[measured]
        est[~measured] = x
    else:
        floor = floor_full[~measured]
        A_no = A[:, ~measured]
        rhs = b - A[:, measured].dot(shipped[measured]) - A_no.dot(floor)
        est = np.zeros(n)
        est[measured] = shipped[measured]
        est[~measured] = _solve_nnls(A_no, rhs) + floor
        mx = float(mrna_rates.max())
        est[np.logical_and(is_mRNA, est > mx)] = mx
    est[inp["is_rtRNA"]] = inp["stable_rate"]
    return est, n_no_bound


def _impute_b(inp, variant, param, held_out):
    """The b vector a variant would build when `held_out` cistrons are unknown.

    Every quantity derived from the measured set is rebuilt from the TRAINING measurements only — including
    `average_mRNA_cistron_half_life`, which is the mean of the REPORTED half-lives and moves when a fold is
    removed. Leaving it at its full-data value would leak the held-out measurements into the imputation that
    is being scored.
    """
    import numpy as np

    b = np.array(inp["b"], dtype=float, copy=True)
    c_is_mRNA, c_measured = inp["c_is_mRNA"], inp["c_measured"]
    train = c_measured & ~held_out
    hl_train = np.log(2) / b[train]                      # the mean is over HALF-LIVES, not over rates
    imputed_rate = float(np.log(2) / hl_train.mean())
    b[held_out] = imputed_rate
    n_pooled = 0
    if variant == "hierarchical":
        b, n_pooled = _pooled_cistron_rates(inp["t"].operons, b, c_is_mRNA, train, imputed_rate,
                                            kappa=float(param or 5.0))
    return b, train, imputed_rate, n_pooled


def mode_deg_rate_cv(root, variant="baseline", k="10", param=""):
    """Score a candidate estimator on measurements it never saw (PARCA-4 Stage 3).

    The protocol is pre-registered in BACKLOG.md and was committed BEFORE this ran. In short: hold out a
    tenth of the 3,246 measured mRNA cistrons by a stable hash of their id, treat them as unmeasured
    everywhere (including in the global floor and in the imputation constant), re-solve, then predict each
    held-out cistron as `(A x)_i` — the abundance-weighted mixture of the rates of the units carrying it,
    which is exactly what the estimator's objective fits. Score on log2(predicted/measured).

    Why held-out prediction and not resolution: any scheme can manufacture distinct values. Add noise and
    the point masses vanish and the fit gets worse. Only predicting a measurement the fit never saw
    separates "more informative" from "more decorated".

    Also scored on the same folds: the CURRENT IMPUTATION alone — what the global mean would have predicted.
    That is the error the 1,100 genuinely unmeasured cistrons are silently carrying, and it has never been
    measured. It is a property of the data, so it is the same for every variant.
    """
    import pickle

    import numpy as np

    if variant not in _DEG_VARIANTS:
        return {"error": "unknown variant %r; expected one of %s" % (variant, list(_DEG_VARIANTS))}
    kb = os.path.join(root, "kb", "simData.cPickle")
    if not os.path.exists(kb):
        return {"error": "no sim_data at %s (run ParCa first)" % kb}
    with open(kb, "rb") as f:
        sd = pickle.load(f)

    inp = _deg_rate_inputs(sd)
    A, is_mRNA = inp["A"], inp["is_mRNA"]
    c_measured = inp["c_measured"]
    b_true = inp["b"]
    k = int(k or 10)

    # --- strata, fixed by the FULL-DATA BASELINE fit so they are identical for every variant -------------
    base_est, _ = _resolve_once(inp, "baseline", "", b_true, c_measured)
    with np.errstate(divide="ignore", invalid="ignore"):
        hl = np.log(2) / base_est / 60.0
    finite_m = is_mRNA & np.isfinite(hl)
    tu_on_floor = finite_m & (np.round(hl, 9) == np.round(float(np.nanmax(hl[finite_m])), 9))
    inc = (A > 0).tocsr()
    n_tus_per_cistron = np.asarray(inc.sum(axis=1)).ravel()
    on_floor_cistron = np.asarray(inc[:, tu_on_floor].sum(axis=1)).ravel() > 0

    folds = np.full(len(b_true), -1, dtype=int)
    idx = np.where(c_measured)[0]
    folds[idx] = _fold_of([str(x) for x in np.asarray(inp["t"].cistron_data["id"])[idx]], k)

    err_var, err_imp, err_base, keep, n_zero = [], [], [], [], 0
    imputed_per_fold = []
    for f in range(k):
        held = c_measured & (folds == f)
        if not held.any():
            continue
        train = c_measured & ~held
        b, _tr, imputed_rate, _np_ = _impute_b(inp, variant, param, held)
        est, _ = _resolve_once(inp, variant, param, b, train)
        pred = np.asarray(A.dot(est), dtype=float)
        # The BASELINE on the identical fold, so the comparison is paired rather than two summaries put
        # side by side. Free: the expensive part of this loop is unpickling sim_data, which happened once.
        if variant == "baseline":
            pred_b = pred
        else:
            bb, _tr2, _ir2, _np2 = _impute_b(inp, "baseline", "", held)
            est_b, _ = _resolve_once(inp, "baseline", "", bb, train)
            pred_b = np.asarray(A.dot(est_b), dtype=float)
        h = np.where(held)[0]
        p, t, pb = pred[h], b_true[h], pred_b[h]
        ok = (p > 0) & (t > 0) & (pb > 0)
        n_zero += int((~ok).sum())
        err_var.extend(np.log2(p[ok] / t[ok]))
        err_base.extend(np.log2(pb[ok] / t[ok]))
        err_imp.extend(np.log2(imputed_rate / t[ok]))
        keep.extend(h[ok])
        imputed_per_fold.append(float(np.log(2) / imputed_rate / 60.0))

    keep = np.array(keep, dtype=int)
    err_var, err_imp = np.array(err_var), np.array(err_imp)
    err_base = np.array(err_base)
    multi = n_tus_per_cistron[keep] > 1
    floor_s = on_floor_cistron[keep]

    def strat(e):
        return {"overall": _cv_metrics(e),
                "on_floor_stratum": _cv_metrics(e[floor_s]),
                "not_on_floor": _cv_metrics(e[~floor_s]),
                "multi_tu_operon": _cv_metrics(e[multi]),
                "single_tu": _cv_metrics(e[~multi])}

    return {
        "variant": variant, "param": param or None, "k_folds": k, "root": root,
        "n_held_out_scored": int(len(err_var)),
        "n_dropped_zero_prediction": n_zero,
        # OBSERVABLE PROOF that the derived quantities are rebuilt per fold. The imputation
        # constant is the MEAN of the reported half-lives, so it MUST move when a tenth of the
        # measurements is removed. If these are all identical to the full-data constant, the folds
        # leak through the imputation even though `b` looks correctly masked -- a leak an
        # end-to-end score check cannot see, because removing a tenth moves the mean by under 1%.
        "imputed_half_life_min_per_fold": [round(v, 6) for v in imputed_per_fold],
        "protocol": ("Pre-registered in BACKLOG.md before this ran. Folds by sha1(cistron_id) %% %d; a "
                     "held-out cistron is unmeasured EVERYWHERE, including in the global floor and in the "
                     "imputation constant; prediction is (A x)_i; metric is log2(predicted/measured)." % k),
        "variant_scores": strat(err_var),
        "baseline_scores_same_folds": strat(err_base),
        "paired_vs_baseline": {"overall": _paired_delta(err_var, err_base),
                               "on_floor_stratum": _paired_delta(err_var[floor_s], err_base[floor_s]),
                               "multi_tu_operon": _paired_delta(err_var[multi], err_base[multi]),
                               "note": ("Same held-out cistrons scored by both estimators, so the comparison "
                                        "is paired. A negative median delta means the variant is closer to "
                                        "the measurement. SUPPLEMENTS the pre-registered rule below; it does "
                                        "not replace it.")},
        "paired_vs_imputation": {"overall": _paired_delta(err_var, err_imp)},
        "imputation_only_scores": strat(err_imp),
        "imputation_note": ("`imputation_only_scores` is what the global mean alone would have predicted for "
                            "the same held-out cistrons — the error the 1,100 genuinely unmeasured cistrons "
                            "carry with nothing marking it. It is a property of the data, identical for every "
                            "variant, and it is the evidence for how large an explicit unknown class needs "
                            "to be."),
        "decision_rule": ("Pre-registered: a variant beats the baseline only if median_abs_log2 is lower "
                          "BOTH overall AND on the floor stratum. Winning overall while losing on the floor "
                          "improves the units that were already fine, which is not the defect. Differences "
                          "below 0.01 are ties."),
        "cannot_decide": ("The 209 units in no equation and the 783 in imputation-passthrough blocks have no "
                          "held-out measurement to predict. Cross-validation is silent about them by "
                          "construction and no ranking here applies to them."),
    }


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
    elif mode == "kb_content_hash":
        out = mode_kb_content_hash(run_root)
    elif mode == "gene_map":
        out = mode_gene_map(run_root)
    elif mode == "gene_scope":
        out = mode_gene_scope(run_root)
    elif mode == "viability":
        out = mode_viability(run_root)
    elif mode == "fba_essentiality":
        out = mode_fba_essentiality(run_root, sys.argv[3])
    elif mode == "reroute_diagnosis":
        out = mode_reroute_diagnosis(sys.argv[2], sys.argv[3], sys.argv[4])
    elif mode == "differential":
        out = mode_differential(sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]), float(sys.argv[6]))
    elif mode == "gene_lfc":
        out = mode_gene_lfc(sys.argv[2], sys.argv[3], sys.argv[4], float(sys.argv[5]))
    elif mode == "deg_rate_provenance":
        out = mode_deg_rate_provenance(run_root, sys.argv[3] if len(sys.argv) > 3 else "0")
    elif mode == "deg_rate_cv":
        out = mode_deg_rate_cv(run_root, sys.argv[3] if len(sys.argv) > 3 else "baseline",
                               sys.argv[4] if len(sys.argv) > 4 else "10",
                               sys.argv[5] if len(sys.argv) > 5 else "")
    elif mode == "deg_rate_resolve":
        out = mode_deg_rate_resolve(run_root, sys.argv[3] if len(sys.argv) > 3 else "baseline",
                                    sys.argv[4] if len(sys.argv) > 4 else "")
    else:
        out = {"error": f"unknown mode '{mode}'"}
    print("CELLARIUM_JSON:" + json.dumps(out))
