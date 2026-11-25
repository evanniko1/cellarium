"""BV-10: the cell mass per origin at replication initiation, against Si et al. 2017.

Si et al. 2017 (Current Biology 27:1278, doi:10.1016/j.cub.2017.03.022) found the initiation mass per origin
invariant across growth conditions. wcEcoli builds the invariance in, with an exception: a cell initiates when its
mass per origin reaches a critical mass, `min(1.2 x the condition's average cell mass, 975 fg)`
(reconstruction/ecoli/dataclasses/growth_rate_dependent_parameters.py::get_dna_critical_mass), so the threshold is
975 fg wherever cells are big enough and is LOWERED for slow-growing conditions, whose cells would otherwise never
reach it. The test reads every initiation in every run (ReplicationData/numberOfOric rising; Mass/cellMass just
before) and reports, per design, the realised mass per origin and the threshold the model used.

    WCECOLI_DOCKER=<code image> python evals/bv10_initiation.py      # writes evals/results/bv10_initiation.json
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
OUT = REPO / "evals" / "results" / "bv10_initiation.json"

import bv6_overflow as B6  # noqa: E402


def main() -> int:
    from cellarium import provenance, reader
    runs = B6._runs(B6.FIXED_MEDIUM + B6.OTHER_MEDIA)
    roots = [r["root"] for rs in runs.values() for r in rs]
    got = reader.initiation_mass(roots)
    if "error" in got:
        print(json.dumps(got)[:500])
        return 2
    rows = {}
    for design, rs in runs.items():
        ev, gr = [], []
        for r in rs:
            e = (got.get(reader._container_path(r["root"])) or {}).get("events") or []
            ev += [x for x in e if x.get("mass_per_origin_fg") is not None]
            gr.append(r["growth_per_h"])
        if not ev:
            rows[design] = {"n_runs": len(rs), "n_initiations": 0}
            continue
        mpo = [x["mass_per_origin_fg"] for x in ev]
        crit = sorted({round(x["critical_mass_fg"], 1) for x in ev if x.get("critical_mass_fg") is not None})
        rows[design] = {"n_runs": len(rs), "n_initiations": len(ev),
                        "growth_per_h": round(statistics.fmean(gr), 4) if gr else None,
                        "mass_per_origin_fg_median": round(statistics.median(mpo), 1),
                        "mass_per_origin_fg_cv": round(statistics.stdev(mpo) / statistics.fmean(mpo), 3)
                        if len(mpo) > 1 else None,
                        "critical_mass_fg_used": crit}
    med = [v["mass_per_origin_fg_median"] for v in rows.values() if v.get("n_initiations")]
    fast = [v["mass_per_origin_fg_median"] for v in rows.values()
            if v.get("n_initiations") and v.get("critical_mass_fg_used") == [975.0]]
    slow = {d: v for d, v in rows.items() if v.get("n_initiations") and v.get("critical_mass_fg_used")
            and max(v["critical_mass_fg_used"]) < 975.0}
    out = {"spec": "BV-10", "knowledge_base": f"{B6.KB} (the corpus fit), steady state",
           "organism": ("Si et al. 2017 (doi:10.1016/j.cub.2017.03.022): initiation mass per origin is invariant "
                        "across growth conditions"),
           "in_sample": "built in: the threshold is a parameter (975 fg), lowered by rule for slow-growing conditions",
           "across_designs": {"n_designs": len(med),
                              "cv_of_design_medians": round(statistics.stdev(med) / statistics.fmean(med), 3)
                              if len(med) > 1 else None,
                              "designs_at_975_fg": len(fast),
                              "designs_with_a_lowered_threshold": sorted(slow),
                              "lowered_threshold_fg": {d: v["critical_mass_fg_used"] for d, v in slow.items()}},
           "designs": rows, "unreachable": got.get("_unreachable"),
           "computed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "environment": provenance.code_environment()}
    OUT.write_text(json.dumps(out, indent=1, default=float) + "\n", encoding="utf-8")
    for d, a in rows.items():
        print(f"{d:48s} {a}")
    print(json.dumps(out["across_designs"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
