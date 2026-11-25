"""BV-6: overflow metabolism, against Basan et al. 2015.

In the organism, acetate excretion under aerobic growth on glucose rises with growth rate above a threshold (Basan
et al. 2015, Nature 528:99, doi:10.1038/nature15765): overflow is a growth-rate law, not a medium property. Here
the model's acetate exchange is read per run, with glucose uptake beside it, for designs that change growth at a
FIXED medium (ppGpp clamps and rRNA operon removal: Basan's own proteome-allocation axis) and, separately, for
other media.

Ratios (acetate excreted per glucose taken up) are reported because they do not depend on the listener's flux
units. The whole-cell model's flux balance is homeostatic, without a growth-maximising objective (Birch et al.
2014), so overflow may be absent by construction; a zero is reported as a zero, with its sign and size.

    WCECOLI_DOCKER=<code image> python evals/bv6_overflow.py        # writes evals/results/bv6_overflow.json
"""
from __future__ import annotations

import json
import math
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
OUT = REPO / "evals" / "results" / "bv6_overflow.json"

FIXED_MEDIUM = ["wildtype/basal", "ppgpp_conc/basal|ppGpp:0.6x", "ppgpp_conc/basal|ppGpp:1.6x",
                "rrna_operon_knockout/minimal|rRNA_KO:4op", "rrna_operon_knockout/minimal|rRNA_KO:6op"]
OTHER_MEDIA = ["condition/glc_5mM", "condition/glc_2mM", "condition/acetate", "condition/succinate",
               "condition/no_oxygen", "condition/minus_magnesium"]
SPECIES = ["ACET[p]", "GLC[p]", "OXYGEN-MOLECULE[p]", "ETOH[p]", "FORMATE[p]", "SUC[p]", "CARBON-DIOXIDE[p]"]
KB = "3b2f8ebd"


def _runs(designs: list[str]) -> dict[str, list[dict]]:
    """QC-clean steady-state runs of the corpus fit with raw output on this machine, per design."""
    from cellarium import survey, tools
    rows, _ = survey.analysis_rows()
    out: dict[str, list[dict]] = {d: [] for d in designs}
    for r in rows:
        d = survey.design_key(r)
        if d in out and r.get("qc") == "ok" and str(r.get("kb_sha256") or "").startswith(KB) \
                and r.get("elongation_model") == "steady_state":
            root = tools._run_root(r["id"])
            if root is not None and r.get("growth_rate") is not None:
                out[d].append({"id": r["id"], "root": Path(root), "growth_per_h": float(r["growth_rate"]) * 3600.0,
                               "generations": r.get("generations")})
    return out


def _ols(x: list[float], y: list[float]) -> dict | None:
    n = len(x)
    if n < 3 or len(set(x)) < 2:
        return None
    mx, my = statistics.fmean(x), statistics.fmean(y)
    sxx = sum((a - mx) ** 2 for a in x)
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    if not any(b != y[0] for b in y):
        # a response that never varies has no slope to test: 0.0 everywhere is a finding, not a p of 0
        return {"n": n, "slope": 0.0, "r": None, "p": None, "constant_response": y[0]}
    slope = sxy / sxx
    resid = [b - (my + slope * (a - mx)) for a, b in zip(x, y)]
    s2 = sum(e * e for e in resid) / (n - 2)
    se = math.sqrt(s2 / sxx) if s2 > 0 else 0.0
    t = slope / se if se else float("inf")
    try:
        from scipy import stats
        p = float(2 * stats.t.sf(abs(t), n - 2))
    except Exception:                                   # noqa: BLE001
        p = None
    syy = sum((b - my) ** 2 for b in y)
    return {"n": n, "slope": slope, "r": sxy / math.sqrt(sxx * syy) if syy else None, "p": p}


def refit() -> int:
    """Recompute the fixed-medium fits from the stored per-run values (no re-read)."""
    d = json.loads(OUT.read_text(encoding="utf-8"))
    fixed = [p for k in FIXED_MEDIUM for p in d["designs"].get(k, {}).get("runs", [])]
    d["fixed_medium_fit_acetate_vs_growth"] = _ols([p["growth_per_h"] for p in fixed], [p["ACET[p]"] for p in fixed])
    d["fixed_medium_fit_acetate_per_glucose_vs_growth"] = _ols(
        [p["growth_per_h"] for p in fixed], [p["acetate_per_glucose"] for p in fixed if p["acetate_per_glucose"] is not None])
    OUT.write_text(json.dumps(d, indent=1, default=float) + "\n", encoding="utf-8")
    print(d["fixed_medium_fit_acetate_vs_growth"])
    return 0


def main() -> int:
    if "--refit" in sys.argv[1:]:
        return refit()
    from cellarium import provenance, reader
    runs = _runs(FIXED_MEDIUM + OTHER_MEDIA)
    roots = [r["root"] for rs in runs.values() for r in rs]
    got = reader.species_per_run(roots, "exchange_flux", SPECIES)
    if "error" in got:
        print(json.dumps(got)[:500])
        return 2
    rows = {}
    for design, rs in runs.items():
        per = []
        for r in rs:
            vals = got.get(reader._container_path(r["root"])) or {}
            m = {s: (vals.get(s) or {}).get("mean") for s in SPECIES}
            if m["ACET[p]"] is None or m["GLC[p]"] is None:
                continue
            per.append({"id": r["id"], "growth_per_h": round(r["growth_per_h"], 4), **{s: m[s] for s in SPECIES},
                        "acetate_per_glucose": (m["ACET[p]"] / -m["GLC[p]"]) if m["GLC[p]"] else None})
        if not per:
            rows[design] = {"n_runs": 0, "why": "no run with both exchanges readable"}
            continue
        agg = {"n_runs": len(per), "growth_per_h": round(statistics.fmean(p["growth_per_h"] for p in per), 4)}
        for s in SPECIES:
            v = [p[s] for p in per if p[s] is not None]
            if v:
                agg[s] = {"mean": round(statistics.fmean(v), 6), "sd": round(statistics.stdev(v), 6) if len(v) > 1 else None}
        ratio = [p["acetate_per_glucose"] for p in per if p["acetate_per_glucose"] is not None]
        agg["acetate_per_glucose"] = round(statistics.fmean(ratio), 4) if ratio else None
        agg["direction"] = ("secreted" if agg["ACET[p]"]["mean"] > 0 else "taken up" if agg["ACET[p]"]["mean"] < 0
                            else "zero")
        agg["runs"] = per
        rows[design] = agg
    fixed = [p for d in FIXED_MEDIUM for p in rows.get(d, {}).get("runs", [])]
    fit = _ols([p["growth_per_h"] for p in fixed], [p["ACET[p]"] for p in fixed])
    fit_ratio = _ols([p["growth_per_h"] for p in fixed], [p["acetate_per_glucose"] for p in fixed
                                                          if p["acetate_per_glucose"] is not None])
    out = {"spec": "BV-6", "knowledge_base": f"{KB} (the corpus fit), steady state",
           "organism": ("Basan et al. 2015 (doi:10.1038/nature15765): aerobic acetate excretion on glucose rises "
                        "linearly with growth rate above a threshold; the model's basal growth on glucose is above "
                        "it, so the organism excretes acetate there"),
           "sign_convention": "exchange flux: secretion positive, uptake negative (tools.exchange_flux)",
           "in_sample": "perturbations are out of sample; exchange fluxes are emergent from the homeostatic FBA",
           "fixed_medium_fit_acetate_vs_growth": fit, "fixed_medium_fit_acetate_per_glucose_vs_growth": fit_ratio,
           "designs": rows, "unreachable": got.get("_unreachable"),
           "computed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "environment": provenance.code_environment()}
    OUT.write_text(json.dumps(out, indent=1, default=float) + "\n", encoding="utf-8")
    for d, a in rows.items():
        print(f"{d:48s} n={a.get('n_runs')} growth={a.get('growth_per_h')} acet={a.get('ACET[p]')} "
              f"glc={a.get('GLC[p]')} ratio={a.get('acetate_per_glucose')}")
    print("fit", fit, fit_ratio)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
