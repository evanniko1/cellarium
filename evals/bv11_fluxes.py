"""BV-11: central-carbon fluxes against 13C metabolic flux analysis (Toya et al. 2010).

Toya et al. 2010 (Biotechnology Progress 26:975, doi:10.1002/btpr.420) measured central-carbon fluxes of E. coli
in batch glucose culture by 13C metabolic flux analysis. wcEcoli ships them as validation data keyed by its own
reaction ids (validation/ecoli/flat/toya_2010_central_carbon_fluxes.tsv, 23 reactions, mmol per g dry weight per
hour), and Macklin et al. 2020 (Science 369, doi:10.1126/science.aav3751) compared the model with them. So this is a
CONTROL: it reproduces a published validation through Cellarium's reader, on the corpus's basal runs, with the
model's fluxes converted exactly as wcEcoli's own analysis converts them (reader.base_reaction_fluxes). The
interesting reading is which fluxes the homeostatic flux balance gets wrong, beside BV-6's finding that it neither
overflows nor ferments.

    WCECOLI_DOCKER=<code image> python evals/bv11_fluxes.py --wcecoli <checkout>   # writes bv11_fluxes.json
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "evals"))
OUT = REPO / "evals" / "results" / "bv11_fluxes.json"
TOYA = "validation/ecoli/flat/toya_2010_central_carbon_fluxes.tsv"

import bv6_overflow as B6  # noqa: E402


def toya(path: Path) -> dict[str, tuple[float, float]]:
    out = {}
    with open(path, encoding="utf-8", newline="") as f:
        lines = [ln for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    for row in csv.DictReader(lines, delimiter="\t"):
        rid = row["reactionID"].strip().strip('"')
        out[rid] = (float(row["flux (units.mmol / units.g / units.h)"]),
                    float(row["flux standard deviation (units.mmol / units.g / units.h)"]))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wcecoli", required=True, type=Path)
    a = ap.parse_args(argv)
    from scipy import stats

    from cellarium import provenance, reader
    meas = toya(a.wcecoli / TOYA)
    runs = B6._runs(["wildtype/basal"])["wildtype/basal"]
    got = reader.base_reaction_fluxes([r["root"] for r in runs], list(meas))
    if "error" in got:
        print(json.dumps(got)[:500])
        return 2
    per_rxn = {rid: [] for rid in meas}
    n_runs = 0
    for r in runs:
        v = got.get(reader._container_path(r["root"])) or {}
        if "error" in v:
            continue
        n_runs += 1
        for rid in meas:
            if v.get(rid) is not None:
                per_rxn[rid].append(v[rid])
    rows, x, y = [], [], []
    for rid, (m, sd) in meas.items():
        vals = per_rxn[rid]
        if not vals:
            rows.append({"reaction": rid, "toya": m, "toya_sd": sd, "model": None, "why": "not among the model's "
                                                                                             "base reactions"})
            continue
        mod = statistics.fmean(vals)
        rows.append({"reaction": rid, "toya": m, "toya_sd": sd, "model": round(mod, 3),
                     "model_sd": round(statistics.stdev(vals), 3) if len(vals) > 1 else None,
                     "within_2sd": abs(mod - m) <= 2 * sd})
        x.append(m)
        y.append(mod)
    pear = stats.pearsonr(x, y) if len(x) > 2 else None
    out = {"spec": "BV-11", "data": f"Toya et al. 2010 via wcEcoli {TOYA}", "design": "wildtype/basal",
           "knowledge_base": f"{B6.KB} (the corpus fit), steady state", "n_runs": n_runs,
           "in_sample": ("a control: the data are the model builders' own validation set (Macklin et al. 2020), not "
                         "a fit input; fluxes are emergent from the homeostatic FBA"),
           "n_reactions_compared": len(x), "pearson_r": round(float(pear.statistic), 3) if pear else None,
           "pearson_p": float(pear.pvalue) if pear else None,
           "spearman_rho": round(float(stats.spearmanr(x, y).statistic), 3) if len(x) > 2 else None,
           "n_within_2sd": sum(1 for r in rows if r.get("within_2sd")),
           "median_abs_log2_ratio": round(statistics.median(abs(math.log2(b / a_)) for a_, b in zip(x, y)
                                                            if a_ > 0 and b > 0), 3) if x else None,
           "reactions": rows, "unreachable": got.get("_unreachable"),
           "computed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "environment": provenance.code_environment()}
    OUT.write_text(json.dumps(out, indent=1, default=float) + "\n", encoding="utf-8")
    for r in rows:
        print(f"{r['reaction']:40s} toya {r['toya']:7.2f} model {r.get('model')}")
    print({k: out[k] for k in ("n_runs", "n_reactions_compared", "pearson_r", "spearman_rho", "n_within_2sd",
                               "median_abs_log2_ratio")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
