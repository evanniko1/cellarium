"""BV-14d robustness (post hoc, 2026-11-27): does the registered result hold in every generation and without its
discards, and does it depend on the biomass splines' extrapolated range?

The registered readout (`evals/bv14d_clamp.py`) is the last generation of each valid seed. These three checks were
NOT pre-registered. They are recorded so that every number in the write-up can be re-derived from its source:

  per_generation  NarL's effect with FNR at the fit's occupancy and with FNR held off, and their interaction, in each
                  of the three generations, on the registered valid seeds.
  sensitivity     the last-generation contrasts with the two complete runs the registered rules discarded added back:
                  F1-s301 grew 1.01x past its limit, and F2-s301's NarL clamp sagged to 0.51.
  composition     each run's RNA/protein mass ratio per generation, against the biomass splines' fitted range (0.2 to
                  0.469; below 0.1355 every pool's fraction is negative). Descriptive only: no rule uses it.

None of these changes a decision. The decisions are the registered ones.

    WCECOLI_DOCKER=<image> python evals/bv14d_robustness.py run    # reads the raw runs (before they are deposited)
    python evals/bv14d_robustness.py score                        # recomputes from the stored raw read
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "evals"))
sys.path.insert(0, str(REPO / "src"))
OUT = REPO / "evals" / "results" / "bv14d_robustness.json"
REGISTERED = REPO / "evals" / "results" / "bv14d_clamp.json"
SIM_ROOT = REPO / "runs" / "bv14_no3_anaerobic"
TUS = {"narGHJI": "TU00044[c]", "frdABCD": "TU0-45225[c]", "nirBDC": "TU00046[c]", "narK": "EG10642_RNA[c]"}
TFS = ("FNR-4FE-4S-CPLX", "PHOSPHO-NARL")
SPLINE_RANGE = (0.2, 0.469)
ALL_POOLS_NEGATIVE_BELOW = 0.1355
DISCARDED_COMPLETE = ("F1-s301", "F2-s301")
RUNS = {"ctl-fit": "condition_000024__occ4950c1/000310", "ctl-off": "condition_000024__occ9b89f1/000340",
        **{f"F1-s{s}": f"condition_000007__occ4950c1/{s:06d}" for s in (300, 301, 302)},
        **{f"F2-s{s}": f"condition_000024__occ4950c1/{s:06d}" for s in (300, 301, 302)},
        **{f"O1-s{s}": f"condition_000007__occ9b89f1/{s:06d}" for s in (330, 332)},
        "O1-s331": "condition_000007/000331",          # crashed in generation 2: its transit dir, composition only
        **{f"O2-s{s}": f"condition_000024__occ9b89f1/{s:06d}" for s in (330, 331, 332)}}


def _image() -> str:
    img = os.environ.get("WCECOLI_DOCKER")
    if not img:
        raise SystemExit("WCECOLI_DOCKER is not set to the model image; nothing can be read.")
    return img


# ---- the arithmetic: the registered scorer's, applied per generation ------------------------------------------

def with_runs(valid: dict, extra: list[str]) -> dict:
    """The valid seeds with named runs ("F1-s301") added back to their arms. Returns a new mapping."""
    out = {a: list(s) for a, s in valid.items()}
    for rid in extra:
        arm, seed = rid.split("-s")
        out[arm] = sorted(set(out[arm]) | {int(seed)})
    return out


def phi(r_f: float, *, r_bv14: float, r_fit: float) -> float:
    """The share of BV-14's nar attenuation restored: (R_F - R_BV14) / (R_fit - R_BV14), as the registered rule."""
    return round((r_f - r_bv14) / (r_fit - r_bv14), 3)


def contrasts(raw: dict, valid: dict, *, gen: int, op: str) -> dict:
    """NarL's effect (log2 ratio of arm means, nitrate against anaerobic) at the fit's FNR and with FNR off, and the
    interaction on per-seed log2 values, in generation `gen`. The same functions the registered scorer calls."""
    import bv14_nitrate as B14
    from bv14d_clamp import interaction
    vals = {a: [raw[f"{a}-s{s}"][gen]["synth"][op] for s in seeds] for a, seeds in valid.items()}
    lg = {a: [math.log2(x) for x in v] for a, v in vals.items()}
    return {"NarL_effect_FNR_at_fit": B14._compare_arms(vals["F2"], vals["F1"])["log2_ratio"],
            "NarL_effect_FNR_off": B14._compare_arms(vals["O2"], vals["O1"])["log2_ratio"],
            "interaction": interaction(lg["O2"], lg["O1"], lg["F2"], lg["F1"])}


# ---- reading the raw runs (inside the image) ------------------------------------------------------------------

def _worker() -> None:
    """Runs INSIDE the model image with the BV-14d sim path mounted at /wcEcoli/out: JSON on stdout."""
    import numpy as np
    from wholecell.io.tablereader import TableReader
    res = {}
    for name, sub in RUNS.items():
        gens = []
        for g in range(3):
            so = f"/wcEcoli/out/{sub}/generation_{g:06d}/000000/simOut"
            if not os.path.isdir(so):
                gens.append(None)
                continue
            rec = {}
            m = TableReader(os.path.join(so, "Mass"))
            rna, prot = m.readColumn("rnaMass"), m.readColumn("proteinMass")
            n = min(len(rna), len(prot))
            rp = rna[:n] / prot[:n]
            rec["rna_protein"] = {"min": round(float(rp.min()), 4), "first": round(float(rp[0]), 4),
                                  "last": round(float(rp[-1]), 4),
                                  "frac_steps_below_range": round(float((rp < SPLINE_RANGE[0]).mean()), 3)}
            try:
                r = TableReader(os.path.join(so, "RnaSynthProb"))
                rna_ids = [str(x) for x in r.readAttribute("rnaIds")]
                tf_ids = [str(x) for x in r.readAttribute("tf_ids")]
                act = np.asarray(r.readColumn("actual_rna_synth_prob", [rna_ids.index(t) for t in TUS.values()],
                                              squeeze=False), float)
                tfi = [tf_ids.index(t) for t in TFS]
                nab = np.asarray(r.readColumn("nActualBound", tfi, squeeze=False), float)
                nav = np.asarray(r.readColumn("n_available_promoters", tfi, squeeze=False), float)
                r.close()
                with np.errstate(invalid="ignore", divide="ignore"):
                    bf = np.nanmean(np.where(nav > 0, nab / nav, np.nan), axis=0)
                rec["synth"] = {op: float(act[:, i].mean()) for i, op in enumerate(TUS)}
                rec["bound_fraction"] = {tf: round(float(bf[i]), 4) for i, tf in enumerate(TFS)}
            except Exception as e:                       # noqa: BLE001  a truncated generation is named, not fatal
                rec["synth_error"] = f"{type(e).__name__}: {str(e)[:160]}"
            gens.append(rec)
        res[name] = gens
    print(json.dumps(res))


def run() -> int:
    cmd = ["docker", "run", "--rm", "-v", f"{SIM_ROOT}:/wcEcoli/out:ro", "-v", f"{Path(__file__).resolve()}:/x/r.py:ro",
           "-e", "PYTHONPATH=/wcEcoli", "-w", "/wcEcoli", _image(), "python", "/x/r.py", "worker"]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    line = next((ln for ln in reversed(r.stdout.splitlines()) if ln.startswith("{")), None)
    if line is None:
        print(f"no read: {(r.stderr or r.stdout)[-600:]}", file=sys.stderr)
        return 2
    OUT.write_text(json.dumps({"raw": json.loads(line), "read_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                              indent=1) + "\n", encoding="utf-8")
    return score()


def score() -> int:
    stored = json.loads(OUT.read_text(encoding="utf-8"))
    raw = stored["raw"]
    reg = json.loads(REGISTERED.read_text(encoding="utf-8"))
    valid = reg["valid_seeds"]
    bv14 = json.loads((REPO / "evals" / "results" / "bv14_nitrate.json").read_text(encoding="utf-8"))
    d14 = bv14["diagnostic_post_hoc"]["contrasts"]["nitrate_under_anaerobiosis"]
    r_bv14, r_fit = d14["actual_synth_prob"]["narGHJI"]["log2_ratio"], d14["fitted_log2_synth_ratio"]["narGHJI"]
    per_gen = {op: [contrasts(raw, valid, gen=g, op=op) for g in range(3)] for op in TUS}
    for g, row in enumerate(per_gen["narGHJI"]):
        row["phi"] = phi(row["NarL_effect_FNR_at_fit"], r_bv14=r_bv14, r_fit=r_fit)
    sens = {}
    for label, extra in (("registered", []), ("plus_F1-s301", ["F1-s301"]), ("plus_F2-s301", ["F2-s301"]),
                         ("plus_both", list(DISCARDED_COMPLETE))):
        c = contrasts(raw, with_runs(valid, extra), gen=2, op="narGHJI")
        c["phi"] = phi(c["NarL_effect_FNR_at_fit"], r_bv14=r_bv14, r_fit=r_fit)
        sens[label] = c
    reg_nar = reg["contrasts"]["narGHJI"]
    if abs(sens["registered"]["interaction"]["estimate"] - reg_nar["interaction"]["estimate"]) > 1e-3:
        raise SystemExit("the registered-seed recomputation disagrees with bv14d_clamp.json: not the same arithmetic")
    composition = {name: [g["rna_protein"] if g else None for g in gens] for name, gens in raw.items()}
    bound = {name: [g.get("bound_fraction") if g else None for g in gens] for name, gens in raw.items()}
    out = {"spec": "BV-14d robustness (post hoc; NOT pre-registered; no decision changes)",
           "registered_result": "evals/results/bv14d_clamp.json", "valid_seeds": valid,
           "bv14_reference": {"observed_nar_log2": r_bv14, "fitted_nar_log2": r_fit},
           "per_generation": per_gen, "sensitivity_last_generation": sens,
           "composition": {"spline_range": list(SPLINE_RANGE), "all_pools_negative_below": ALL_POOLS_NEGATIVE_BELOW,
                           "per_run": composition},
           "bound_fraction_per_generation": bound, "raw": raw, "read_utc": stored.get("read_utc"),
           "computed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    nar = per_gen["narGHJI"]
    print(json.dumps({"nar_interaction_by_generation": [r["interaction"]["estimate"] for r in nar],
                      "nar_phi_by_generation": [r["phi"] for r in nar],
                      "sensitivity_phi": {k: v["phi"] for k, v in sens.items()},
                      "sensitivity_interaction": {k: v["interaction"]["estimate"] for k, v in sens.items()}}))
    return 0


def main() -> int:
    if sys.argv[1:2] == ["worker"]:
        _worker()
        return 0
    if sys.argv[1:2] == ["run"]:
        return run()
    if sys.argv[1:2] == ["score"]:
        return score()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
