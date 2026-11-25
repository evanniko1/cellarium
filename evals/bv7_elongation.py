"""BV-7: the translation elongation rate against growth rate, against Dai et al. 2016.

According to PubMed, Dai et al. 2016 (Nature Microbiology 2:16231, doi:10.1038/nmicrobiol.2016.231) established
that the elongation rate decreases as growth slows, with a Michaelis-Menten dependence on the abundance of the
translational apparatus, that an appreciable rate is maintained even towards zero growth, and that this is
accompanied by a drastic fall in the fraction of active ribosomes. Two laws are tested on the model, read per run
from the ribosome listener (RibosomeData/effectiveElongationRate, last generation): (1) the elongation rate rises
with growth rate across designs; (2) its extrapolation to zero growth stays well above zero.

Designs: growth changed at a fixed medium (ppGpp clamps, rRNA operon removal, basal) and growth changed by the
medium (the fitted conditions with raw output on this machine).

    WCECOLI_DOCKER=<code image> python evals/bv7_elongation.py      # writes evals/results/bv7_elongation.json
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "evals"))
OUT = REPO / "evals" / "results" / "bv7_elongation.json"

import bv6_overflow as B6  # noqa: E402  (same design lists and run selection)

CHANNELS = ["effective_elongation_rate", "ribosome_conc", "growth_rate"]


def main() -> int:
    from cellarium import provenance, reader
    runs = B6._runs(B6.FIXED_MEDIUM + B6.OTHER_MEDIA)
    roots = [r["root"] for rs in runs.values() for r in rs]
    got = reader.channels_per_run(roots, CHANNELS)
    if "error" in got:
        print(json.dumps(got)[:500])
        return 2
    rows, pts = {}, {"fixed_medium": [], "by_medium": []}
    for design, rs in runs.items():
        per = []
        for r in rs:
            ch = got.get(reader._container_path(r["root"])) or {}
            e = ch.get("effective_elongation_rate")
            if e is None:
                continue
            per.append({"id": r["id"], "growth_per_h": round(r["growth_per_h"], 4), "elongation_aa_per_s": round(e, 3),
                        "ribosome_conc": ch.get("ribosome_conc")})
        if not per:
            rows[design] = {"n_runs": 0}
            continue
        rows[design] = {"n_runs": len(per),
                        "growth_per_h": round(statistics.fmean(p["growth_per_h"] for p in per), 4),
                        "elongation_aa_per_s": round(statistics.fmean(p["elongation_aa_per_s"] for p in per), 3),
                        "elongation_sd": round(statistics.stdev([p["elongation_aa_per_s"] for p in per]), 3)
                        if len(per) > 1 else None, "runs": per}
        pts["fixed_medium" if design in B6.FIXED_MEDIUM else "by_medium"] += per
    fits = {}
    for k, v in pts.items():
        f = B6._ols([p["growth_per_h"] for p in v], [p["elongation_aa_per_s"] for p in v])
        if f:
            mx = statistics.fmean(p["growth_per_h"] for p in v)
            my = statistics.fmean(p["elongation_aa_per_s"] for p in v)
            f["intercept_at_zero_growth"] = round(my - f["slope"] * mx, 3)
            f["growth_range_per_h"] = [round(min(p["growth_per_h"] for p in v), 3),
                                       round(max(p["growth_per_h"] for p in v), 3)]
        fits[k] = f
    allp = pts["fixed_medium"] + pts["by_medium"]
    fa = B6._ols([p["growth_per_h"] for p in allp], [p["elongation_aa_per_s"] for p in allp])
    if fa:
        mx = statistics.fmean(p["growth_per_h"] for p in allp)
        my = statistics.fmean(p["elongation_aa_per_s"] for p in allp)
        fa["intercept_at_zero_growth"] = round(my - fa["slope"] * mx, 3)
    fits["all"] = fa
    out = {"spec": "BV-7", "knowledge_base": f"{B6.KB} (the corpus fit), steady state",
           "organism": ("Dai et al. 2016 (doi:10.1038/nmicrobiol.2016.231): the elongation rate decreases as growth "
                        "slows (Michaelis-Menten in the translational apparatus) but an appreciable rate is "
                        "maintained towards zero growth, with a drastic fall in the active-ribosome fraction"),
           "in_sample": ("perturbations are out of sample; the conditions are fitted for growth and composition, and "
                         "the model's elongation rate per medium may itself be an input (checked separately)"),
           "fits": fits, "designs": rows, "unreachable": got.get("_unreachable"),
           "computed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "environment": provenance.code_environment()}
    OUT.write_text(json.dumps(out, indent=1, default=float) + "\n", encoding="utf-8")
    for d, a in rows.items():
        print(f"{d:48s} n={a.get('n_runs')} growth={a.get('growth_per_h')} elong={a.get('elongation_aa_per_s')} "
              f"sd={a.get('elongation_sd')}")
    print(json.dumps(fits, default=float))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
