"""RP (2026-11-27, re-verified at the user's request): slow-growth runs read their biomass targets off splines outside
the range the splines were fitted on.

Three parts, each from its own source:

  splines   From the model's composition table (`reconstruction/ecoli/flat/dry_mass_composition.tsv`), refitted with
            the model's own calls (`growth_rate_dependent_parameters.py::_getFitParameters`: scipy `splrep` on RNA/protein,
            read back with `splev`): the fitted range, and the ratio at or below which a pool's fraction is not positive.
            Needs the checkout (WCECOLI_DIR); without it this part is reported as not computed, never as absent.
  corpus    From the corpus manifest's stored series (`data/manifest/corpus-compact.parquet`, about 16 samples per run):
            the RNA/protein ratio at each sample, per run, for every steady-state run. Run MEANS were the proxy used first
            and understate the exposure; a run counts here if any sample falls below the fitted range.
  direct    The thing itself, read once from four BV-14d runs before they were reclaimed (`worker`, inside the model
            image): metabolism's targets (FBAResults.conc_updates) against the model's own spline function at each step's
            ratio. Stored; it cannot be re-run here once the runs are gone.

Which runs it applies to: `metabolism.py` rebuilds the biomass targets from Mass.rnaMass / Mass.proteinMass only when
ppGpp drives elongation (ppgpp_regulation, the simulator's default, and tRNA charging; not a ppGpp-clamp variant). The
kinetic modes and ppGpp clamps take their targets from the doubling time instead.

    WCECOLI_DIR=<checkout> python evals/rp_extrapolation.py        # writes evals/results/rp_extrapolation.json
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "evals" / "results" / "rp_extrapolation.json"
MANIFEST = REPO / "data" / "manifest" / "corpus-compact.parquet"
POOLS = ("lipid", "lps", "murein", "glycogen", "solublePool", "inorganicIon")
SLOW = ("no_oxygen", "acetate", "succinate")


def spline_facts(flat_dir: Path) -> dict:
    """The fitted range and the non-positive point of every pool's spline, refitted from the model's own table."""
    import numpy as np
    from scipy import interpolate
    lines = [ln for ln in open(flat_dir / "dry_mass_composition.tsv", encoding="utf-8") if not ln.startswith("#")]
    rows = list(csv.DictReader(lines, delimiter="\t"))

    def col(prefix: str):
        key = next(k for k in rows[0] if k.startswith(prefix))
        return np.array([float(r[key]) for r in rows])

    rp = col("rnaMassFraction") / col("proteinMassFraction")
    grid = np.round(np.arange(0.05, 0.47, 0.0001), 4)
    pools = {}
    for name in POOLS:
        p = interpolate.splrep(rp, col(name + "MassFraction"))
        v = interpolate.splev(grid, p)
        pools[name] = {"at_0.2": round(float(interpolate.splev(0.2, p)), 5),
                       "at_0.15": round(float(interpolate.splev(0.15, p)), 5),
                       "not_positive_at_or_below": float(grid[v <= 0].max()) if (v <= 0).any() else None}
    return {"doubling_times_min": col("doublingTime").tolist(), "rna_protein_per_row": [round(float(x), 4) for x in rp],
            "fitted_range": [round(float(rp.min()), 4), round(float(rp.max()), 4)], "pools": pools}


def _ratios(series) -> list[float]:
    se = json.loads(series) if isinstance(series, str) else (series or {})
    rna = {t: v for t, v in se.get("rna_mass", []) if v is not None}
    pro = {t: v for t, v in se.get("protein_mass", []) if v is not None and v}
    return [rna[t] / pro[t] for t in sorted(set(rna) & set(pro))]


def corpus_exposure(manifest: Path = MANIFEST, low: float = 0.2) -> dict:
    """Per steady-state run, the share of its sampled time below `low`; summarised for the slow media and corpus-wide."""
    import pandas as pd
    df = pd.read_parquet(manifest)
    runs = []
    for _, r in df.iterrows():
        rp = _ratios(r["series"])
        if not rp:
            continue
        runs.append({"label": str(r["label"]).replace("·", "/"), "elongation_model": r["elongation_model"],
                     "perturbation": r["perturbation"], "condition": r["condition"], "seed": int(r["seed"]),
                     "reportable": bool(r["reportable"]), "qc": r["qc"], "n_samples": len(rp),
                     "ratio_of_run_means": round(float(r["rna_mass"] / r["protein_mass"]), 4) if r["protein_mass"] else None,
                     "min": round(min(rp), 4), "max": round(max(rp), 4),
                     "share_below": round(sum(x < low for x in rp) / len(rp), 3)})
    ss = [x for x in runs if x["elongation_model"] == "steady_state"]
    slow = {}
    for c in SLOW:
        g = [x for x in ss if x["perturbation"] == "condition" and x["condition"] == c]
        shares = sorted(x["share_below"] for x in g)
        slow[c] = {"runs": len(g), "run_mean_below": sum(1 for x in g if (x["ratio_of_run_means"] or 1) < low),
                   "any_sample_below": sum(1 for x in g if x["share_below"] > 0),
                   "median_share_below": shares[len(shares) // 2] if len(shares) % 2 else
                   round((shares[len(shares) // 2 - 1] + shares[len(shares) // 2]) / 2, 3),
                   "min_ratio": min(x["min"] for x in g)}
    below = [x for x in ss if x["share_below"] > 0]
    return {"low": low, "slow_media": slow,
            "steady_state_runs_with_series": len(ss), "steady_state_any_sample_below": len(below),
            "steady_state_mostly_below": sum(1 for x in ss if x["share_below"] > 0.5),
            "below_outside_the_slow_media": [x["label"] for x in below if x["perturbation"] != "condition"],
            "other_modes_with_series": sum(1 for x in runs if x["elongation_model"] != "steady_state"),
            "runs": below}


# The direct check, as read on 2026-11-27 (scratch worker run inside the model image on four BV-14d runs that were then
# reclaimed): target / spline(ratio of the previous step) had a coefficient of variation of exactly 0 for glycogen and
# murein in every generation read, including every step below 0.2.
DIRECT = {
    "read_utc": "2026-11-27T09:40:00Z",
    "what": "FBAResults.conc_updates for glycogen-monomer[c] and CPD-12261[p] (murein) against "
            "sim_data.mass.get_mass_fractions_from_rna_protein_ratio at each step's Mass.rnaMass / Mass.proteinMass",
    "kb": "runs/bv14_no3_anaerobic/condition_000024/kb/simData_Modified.cPickle (no_oxygen_plus_nitrate)",
    "runs": {"condition_000024__occ9b89f1/000340": {"generations": 1, "steps": 8126, "share_below": 1.0, "rp_min": 0.1425},
             "condition_000024__occ4950c1/000310": {"generations": 1, "steps": 5943, "share_below": 0.78, "rp_min": 0.1511},
             "condition_000024__occ9b89f1/000331": {"generations": 3, "steps": 14005, "share_below_gen0": 0.61,
                                                    "rp_min": 0.1495},
             "condition_000024__occ4950c1/000301": {"generations": 3, "steps": 18791, "share_below": 1.0, "rp_min": 0.1472}},
    "cv_target_over_spline_previous_step": 0.0,
    "glycogen_fraction": {"at_rp_0.1425": 0.00221, "at_0.2": 0.01762},
}


def main() -> int:
    flat = os.environ.get("WCECOLI_DIR")
    splines = (spline_facts(Path(flat) / "reconstruction" / "ecoli" / "flat") if flat else
               {"not_computed": "WCECOLI_DIR is not set; the composition table is in the model checkout"})
    out = {"spec": "RP re-verification (2026-11-27)", "splines": splines, "corpus": corpus_exposure(),
           "direct": DIRECT, "computed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    s = out["corpus"]["slow_media"]
    print("; ".join(f"{c}: {v['any_sample_below']} of {v['runs']} runs below {out['corpus']['low']} at some sample "
                    f"(run means: {v['run_mean_below']})" for c, v in s.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
