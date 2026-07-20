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


def _gene_lfc_map(t_runs, r_runs, floor):
    """Pure: per-gene seed-mean log2fc for EVERY gene present in >=1 target AND >=1 reference run above the count
    floor — the FULL distribution SCI-2's concordance needs. mode_differential returns only the FDR-significant
    tail, which range-restricts Pearson/Deming (you can't estimate a slope from the movers alone). Returns
    {id: {log2fc, target, reference, n_target, n_reference}}. Factored out so it is unit-testable off the sim."""
    if not t_runs or not r_runs:
        return {}
    ids = set().union(*[set(d) for d in t_runs + r_runs])
    out = {}
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
    lfc = _gene_lfc_map(t_runs, r_runs, floor)
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
    else:
        out = {"error": f"unknown mode '{mode}'"}
    print("CELLARIUM_JSON:" + json.dumps(out))
