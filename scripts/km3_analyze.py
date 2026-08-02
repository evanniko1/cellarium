"""Measure the ROUTE1 step-2 test matrix on the NEW (stage-8 KMtf) ParCa.

Superset of mx_analyze.py. For every (run, seed, generation) it records:

  * per-family within-family spread of GrowthLimits/fraction_trna_charged -- max-min across each
    multi-member amino-acid family's isoacceptors -- reported as the MEDIAN over timesteps, the MAX
    over timesteps, and the value at the LAST timestep of that generation;
  * the aggregate charged fraction re-derived from RAW BulkMolecules counts (count-weighted over the
    charged/uncharged tRNA molecules), NOT from the listener column;
  * doubling time from the mean instantaneous growth rate, plus observed generation duration and the
    cellMass end/start ratio;
  * ppgpp_conc (mean, last) and rela_syn (total over amino acids, mean);
  * NaN counts in each column, and whether daughter state was written.

MISSING CELLS ARE PRINTED AS MISSING, never as a zero. A read failure is reported as READ_FAIL with
the exception text -- never silently as an absence.

Emits one JSON object per line prefixed 'ROW '.

Run inside the model image:
    docker run --rm -v C:/dev/wcEcoli/out:/wcEcoli/out -v <scratch>:/probe -e PYTHONPATH=/wcEcoli \
        -w /wcEcoli --entrypoint python <image> /probe/km3_analyze.py <run_dir> [<run_dir> ...]
"""

import argparse
import json
import os
import pickle
import sys

import numpy as np

sys.path.insert(0, "/wcEcoli")

from wholecell.io.tablereader import TableReader  # noqa: E402

DEFAULT_KB = "/wcEcoli/out/km_parca/kb/simData.cPickle"


def _nan_count(x):
    return int(np.isnan(np.asarray(x, dtype=float)).sum())


def measure_simout(so, multi, aa_names, aa_from_trna, sd, drop):
    """Every measurement for one finished cell."""
    rec = {"simOut": so}

    gl = TableReader(os.path.join(so, "GrowthLimits"))
    frac = np.atleast_2d(gl.readColumn("fraction_trna_charged"))
    rec["n_steps"] = int(frac.shape[0])
    rec["n_trna_cols"] = int(frac.shape[1])
    rec["nan_fraction_trna_charged"] = _nan_count(frac)

    per_fam_med = {}
    per_fam_max = {}
    per_fam_end = {}
    for i in multi:
        cols = np.where(aa_from_trna[i] > 0)[0]
        sub = frac[:, cols]
        span = sub.max(1) - sub.min(1)
        per_fam_med[aa_names[i]] = float(np.nanmedian(span))
        per_fam_max[aa_names[i]] = float(np.nanmax(span))
        per_fam_end[aa_names[i]] = float(sub[-1].max() - sub[-1].min())
    rec["per_family_median"] = per_fam_med
    rec["per_family_worst"] = per_fam_max
    rec["per_family_end"] = per_fam_end
    rec["spread_median_worst_family"] = max(per_fam_med.values()) if per_fam_med else float("nan")
    rec["spread_worst_any_step"] = max(per_fam_max.values()) if per_fam_max else float("nan")
    rec["spread_worst_at_end"] = max(per_fam_end.values()) if per_fam_end else float("nan")

    # RAW re-derivation of the aggregate charged fraction: BulkMolecules counts, never the listener.
    tr = sd.process.transcription
    bm = TableReader(os.path.join(so, "BulkMolecules"))
    idx = {m: k for k, m in enumerate(bm.readAttribute("objectNames"))}
    counts = bm.readColumn("counts")
    lo = min(drop, max(counts.shape[0] - 1, 0))
    u = counts[lo:][:, np.array([idx[m] for m in tr.uncharged_trna_names])].astype(float)
    c = counts[lo:][:, np.array([idx[m] for m in tr.charged_trna_names])].astype(float)
    per_t = c.sum(axis=1) / (u + c).sum(axis=1)
    rec["charged_raw_mean"] = float(np.nanmean(per_t))
    rec["charged_raw_last"] = float(per_t[-1])
    rec["charged_raw_n_steps"] = int(per_t.size)
    rec["uncharged_counts_mean"] = float(u.sum(axis=1).mean())
    rec["charged_listener_mean"] = float(np.nanmean(frac[lo:]))

    ppgpp = np.asarray(gl.readColumn("ppgpp_conc"), dtype=float)
    rela = np.atleast_2d(np.asarray(gl.readColumn("rela_syn"), dtype=float))
    rec["ppgpp_conc_mean"] = float(np.nanmean(ppgpp))
    rec["ppgpp_conc_last"] = float(ppgpp[-1])
    rec["nan_ppgpp_conc"] = _nan_count(ppgpp)
    rec["rela_syn_total_mean"] = float(np.nanmean(rela.sum(axis=1)))
    rec["nan_rela_syn"] = _nan_count(rela)

    mass = TableReader(os.path.join(so, "Mass"))
    igr = np.asarray(mass.readColumn("instantaneous_growth_rate"), dtype=float)
    cell = np.asarray(mass.readColumn("cellMass"), dtype=float)
    rec["growth_rate_mean_per_s"] = float(np.nanmean(igr))
    rec["nan_growth_rate_row0"] = int(np.isnan(igr[0]))
    rec["nan_growth_rate"] = _nan_count(igr[1:])
    rec["nan_cellMass"] = _nan_count(cell)
    rec["cellMass_start"] = float(cell[0])
    rec["cellMass_end"] = float(cell[-1])
    rec["cellMass_ratio"] = float(cell[-1] / cell[0]) if cell[0] else float("nan")
    g = rec["growth_rate_mean_per_s"]
    rec["doubling_min_from_rate"] = float(np.log(2) / g / 60.0) if g > 0 else float("nan")

    t = np.asarray(TableReader(os.path.join(so, "Main")).readColumn("time"), dtype=float)
    rec["t_start_s"] = float(t[0])
    rec["t_end_s"] = float(t[-1])
    rec["duration_s"] = float(t[-1] - t[0])
    rec["duration_min"] = float((t[-1] - t[0]) / 60.0)
    rec["divided"] = bool(os.path.isfile(os.path.join(so, "Daughter1_inherited_state.cPickle")))
    rec["nan_any"] = bool(
        rec["nan_fraction_trna_charged"] or rec["nan_ppgpp_conc"] or rec["nan_rela_syn"]
        or rec["nan_growth_rate"] or rec["nan_cellMass"])
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("run_dirs", nargs="+")
    ap.add_argument("--kb", default=DEFAULT_KB)
    ap.add_argument("--generations", type=int, default=3)
    ap.add_argument("--drop", type=int, default=10,
                    help="timesteps dropped from the head of each generation for the raw readout")
    a = ap.parse_args(argv)

    with open(a.kb, "rb") as fh:
        sd = pickle.load(fh)
    aa_from_trna = sd.process.transcription.aa_from_trna
    aa_names = list(sd.molecule_groups.amino_acids)
    multi = [i for i in range(aa_from_trna.shape[0]) if aa_from_trna[i].sum() > 1]
    print("kb {}".format(a.kb))
    print("aa_from_trna {}; multi-member families {}".format(aa_from_trna.shape, len(multi)))

    missing = 0
    for run in a.run_dirs:
        base = os.path.join(run, "wildtype_000000")
        seeds = []
        if os.path.isdir(base):
            seeds = sorted(d for d in os.listdir(base) if d.isdigit())
        if not seeds:
            print("ROW " + json.dumps({"run": run, "status": "MISSING",
                                       "why": "no seed dir under " + base}))
            missing += 1
            continue
        for sd_name in seeds:
            for k in range(a.generations):
                so = os.path.join(base, sd_name, "generation_%06d" % k, "000000", "simOut")
                row = {"run": run, "seed_dir": sd_name, "generation": k}
                if not (os.path.isdir(so) and os.listdir(so)):
                    row["status"] = "MISSING"
                    row["why"] = "no non-empty simOut at " + so
                    missing += 1
                    print("ROW " + json.dumps(row))
                    continue
                try:
                    row.update(measure_simout(so, multi, aa_names, aa_from_trna, sd, a.drop))
                    row["status"] = "OK"
                except Exception as exc:  # a read failure is NOT a zero
                    row["status"] = "READ_FAIL"
                    row["why"] = "{}: {}".format(type(exc).__name__, exc)
                    missing += 1
                print("ROW " + json.dumps(row))

    print("MISSING_OR_FAILED {}".format(missing))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
