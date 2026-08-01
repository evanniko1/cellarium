"""Measure the ROUTE1 step-2 test matrix: arms x seeds x GENERATIONS.

For every simOut found it records, per the task's required list:
  * within-family spread of GrowthLimits/fraction_trna_charged -- max-min across each multi-member
    amino-acid family's isoacceptors, reported BOTH as the worst over all timesteps and as the value
    at the LAST timestep of that generation;
  * growth rate (mean Mass/instantaneous_growth_rate) and the doubling time implied by it, plus the
    observed generation duration and the cellMass ratio end/start;
  * ppgpp_conc (mean and last) and rela_syn (total over the 21 amino acids, mean);
  * NaN counts in each of those columns;
  * whether the cell actually divided (Daughter1_inherited_state.cPickle present).

MISSING CELLS ARE PRINTED AS MISSING, never as a zero. A (dir, generation) that has no non-empty
simOut is reported on its own line with status MISSING so the matrix can be audited for holes.

Emits one JSON object per line prefixed 'ROW ' so the caller can parse without re-deriving anything,
plus a human-readable table.

Run inside the model image:
    docker run --rm -v C:/dev/wcEcoli/out:/wcEcoli/out -v <scratch>:/probe -e PYTHONPATH=/wcEcoli \
        -w /wcEcoli --entrypoint python <image> /probe/mx_analyze.py <run_dir> [<run_dir> ...]
"""

import argparse
import json
import os
import pickle
import sys

import numpy as np

sys.path.insert(0, "/wcEcoli")

from wholecell.io.tablereader import TableReader  # noqa: E402

DEFAULT_KB = "/wcEcoli/out/kinetic_parca/kb/simData.cPickle"


def _nan_count(x):
    return int(np.isnan(np.asarray(x, dtype=float)).sum())


def measure_simout(so, multi, aa_names):
    """Every measurement for one finished cell. Raises nothing: read failures are returned."""
    rec = {"simOut": so}

    frac = TableReader(os.path.join(so, "GrowthLimits")).readColumn("fraction_trna_charged")
    frac = np.atleast_2d(frac)
    rec["n_steps"] = int(frac.shape[0])
    rec["n_trna_cols"] = int(frac.shape[1])
    rec["nan_fraction_trna_charged"] = _nan_count(frac)

    worst_any = 0.0
    worst_end = 0.0
    per_fam_worst = {}
    per_fam_end = {}
    for i in multi:
        cols = np.where(aa_from_trna_row(i) > 0)[0]
        sub = frac[:, cols]
        w = float(np.nanmax(sub.max(1) - sub.min(1)))
        e = float(sub[-1].max() - sub[-1].min())
        per_fam_worst[aa_names[i]] = w
        per_fam_end[aa_names[i]] = e
        worst_any = max(worst_any, w)
        worst_end = max(worst_end, e)
    rec["spread_worst_any_step"] = worst_any
    rec["spread_worst_at_end"] = worst_end
    rec["per_family_worst"] = per_fam_worst
    rec["per_family_end"] = per_fam_end

    gl = TableReader(os.path.join(so, "GrowthLimits"))
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
    # Row 0 of instantaneous_growth_rate is undefined by construction (no previous mass), so it is
    # counted separately. Only NaNs at rows >= 1 indicate a sick simulation.
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
    rec["divided"] = bool(os.path.isfile(os.path.join(so, "Daughter1_inherited_state.cPickle")))
    rec["nan_any"] = bool(
        rec["nan_fraction_trna_charged"] or rec["nan_ppgpp_conc"] or rec["nan_rela_syn"]
        or rec["nan_growth_rate"] or rec["nan_cellMass"])
    return rec


AA_FROM_TRNA = None


def aa_from_trna_row(i):
    return AA_FROM_TRNA[i]


def main(argv=None):
    global AA_FROM_TRNA
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("run_dirs", nargs="+")
    ap.add_argument("--kb", default=DEFAULT_KB)
    ap.add_argument("--generations", type=int, default=3)
    a = ap.parse_args(argv)

    with open(a.kb, "rb") as fh:
        sd = pickle.load(fh)
    AA_FROM_TRNA = sd.process.transcription.aa_from_trna
    aa_names = list(sd.molecule_groups.amino_acids)
    multi = [i for i in range(AA_FROM_TRNA.shape[0]) if AA_FROM_TRNA[i].sum() > 1]
    print("aa_from_trna {}; multi-member families {}".format(AA_FROM_TRNA.shape, len(multi)))

    missing = 0
    for run in a.run_dirs:
        base = os.path.join(run, "wildtype_000000")
        # Seed subdirectory: whatever the run wrote. runSim names it by the CLI --seed.
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
                    row.update(measure_simout(so, multi, aa_names))
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
