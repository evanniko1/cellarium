"""CRIT tier 1 (2026-11-27): validate the relaxed replication threshold (params.initiation_threshold = "relaxed").

Decided by the user, 2026-11-27: "proceed with ... the first-tier fix for the replication threshold". The fix is
Cellarium's hook (model_patches/hooks/initiation_threshold.py): the threshold relaxes towards a new medium's value over
about one doubling time instead of jumping. This file writes the pre-registered plan; `score` reads the runs.

  V1  static identity. Pairs of runs that differ ONLY in the rule, where no timeline event moves the threshold: basal,
      acetate and no oxygen started fitted to their medium, and an amino-acid upshift (25 and 44 minutes are both at the
      975 fg cap). Every listener table but EvaluationTime (wall-clock) must be identical, column by column.
  V3  shift panel. Oxygen removed at 1200 s from a glucose-fitted cell (a downshift) and oxygen restored at 1200 s from
      an anaerobic-fitted cell (an upshift); 3 seeds x 3 generations, under both rules. Acetate substituted mid-run, the
      largest effect in well4cell, is left out: the envelope refuses it for a second, independent reason (a carbon switch
      leaves the glucose-fitted expression in place and the cells shrink each generation), which tier 1 does not touch,
      so it would confound the threshold with that defect. A3 is therefore decided on one downshift. The
      model's own rule is the negative control: it must reproduce the early divisions well4cell rc2 records, or the
      panel cannot tell the rules apart. Those runs are refused by the envelope (that is the defect) and run here only
      as the control, through the batch, which calls the runner directly; reading them stays refused everywhere else.

    python evals/crit_t1.py plan     # writes evals/plans/crit_t1.json
    WCECOLI_DOCKER=<image> python evals/crit_t1.py score
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLAN = REPO / "evals" / "plans" / "crit_t1.json"
SEEDS = (900, 901, 902)          # fresh seeds: no run on disk or in the corpus uses them

STATIC = {
    "basal": {"perturbation": "wildtype", "condition": "basal"},
    "acetate_fitted": {"perturbation": "wildtype", "condition": "acetate", "timeline": "0 minimal_acetate",
                       "params": {"initial_condition": "acetate"}},
    "no_oxygen_fitted": {"perturbation": "wildtype", "condition": "no_oxygen", "timeline": "0 minimal_minus_oxygen",
                         "params": {"initial_condition": "no_oxygen"}},
    "aa_upshift": {"perturbation": "timeline", "timeline": "0 minimal, 1200 minimal_plus_amino_acids"},
}
SHIFTS = {
    "oxygen_off": {"perturbation": "timeline", "timeline": "0 minimal, 1200 minimal_minus_oxygen"},
    "oxygen_restored": {"perturbation": "timeline", "timeline": "0 minimal_minus_oxygen, 1200 minimal",
                        "params": {"initial_condition": "no_oxygen"}},
}

RULES = {
    "V1_identity": "for each static design, the 'medium' and 'relaxed' runs of the same seed have identical listener "
                   "tables (every column of every table but EvaluationTime) in both generations; any difference fails "
                   "tier 1's first requirement (R1) and stops the panel",
    "A1_continuity": "relaxed: the largest step-to-step change of ReplicationData.criticalInitiationMass in any run is "
                     "below 5 fg; medium: oxygen off shows its full jump at the shift (975 to 590 fg)",
    "A2_no_premature_division": "relaxed: no generation of any downshift run lasts less than 600 s",
    "A3_rate_maintenance": "relaxed oxygen off: the median length of the generations born after the shift (1 and 2) "
                           "is at least the unshifted glucose median, 2,879 s (well4cell rc2), the organism's rate "
                           "maintenance after a downshift (Zaritsky & Helmstetter 1992)",
    "negative_control": "medium oxygen off: the same median falls below 2,879 s, reproducing the early divisions; if it "
                        "does not, the panel cannot tell the rules apart and A3 is not decided",
    "upshift": "oxygen restored: reported, not decided; the relaxed rule should reach glucose's cycle length sooner "
               "than the medium rule, whose cell must first grow to the higher threshold (Panlilio et al. 2021)",
    "decision": "the registry record replication_initiation_after_a_nutrient_shift gains holds_in for 'relaxed' only "
                "if V1, A1, A2 and A3 pass and the negative control discriminates",
    "validity": "a run counts only if it finishes every generation; a failed run is listed with its reason and never "
                "averaged; a design left with fewer than two runs reports no median",
}
PREDICTIONS = {
    "V1": "identical, by construction: with no threshold step the hook returns the model's own function",
    "A1": "pass by construction",
    "A3": "uncertain: tier 1 slows the drop but has no ppGpp pause, so the first post-shift cycle may still fall "
          "somewhat below 2,879 s; the medium control should be near well4cell's 2,238 s",
}


def _runs() -> list[dict]:
    runs = []
    for name, d in STATIC.items():
        for rule in ("medium", "relaxed"):
            p = dict(d.get("params") or {})
            if rule == "relaxed":
                p["initiation_threshold"] = "relaxed"
            runs.append({"id": f"V1-{name}-{rule}", "design": {**d, "params": p}, "seed": SEEDS[0], "generations": 2,
                         "group": f"V1_{name}", "role": "run", "stage": 1})
    for name, d in SHIFTS.items():
        for rule in ("medium", "relaxed"):
            p = dict(d.get("params") or {})
            if rule == "relaxed":
                p["initiation_threshold"] = "relaxed"
            for s in SEEDS:
                runs.append({"id": f"V3-{name}-{rule}-s{s}", "design": {**d, "params": p}, "seed": s,
                             "generations": 3, "group": f"V3_{name}_{rule}", "role": "run", "stage": 2})
    return runs


def plan() -> int:
    p = {"batch": "crit_t1", "sim_path": "cellarium", "parallel": 6, "min_free_gb": 40, "priority": -1,
         "keep_raw": True, "gates": {},
         "rules": RULES, "predictions": PREDICTIONS, "runs": _runs(),
         "decided_by": "the user, 2026-11-27: \"proceed with ... the first-tier fix for the replication threshold\"",
         "why": "CRIT (D17): the threshold follows the medium, so a shift moves it in one step; tier 1 relaxes it "
                "(CRIT_FIX_SPEC s.6, local), without copying model code"}
    p["design_sha256"] = hashlib.sha256(json.dumps({k: p[k] for k in ("runs", "rules", "predictions")},
                                                   sort_keys=True).encode()).hexdigest()
    PLAN.write_text(json.dumps(p, indent=1) + "\n", encoding="utf-8")
    print(f"{PLAN.relative_to(REPO)}: {len(p['runs'])} runs, design_sha256 {p['design_sha256'][:12]}")
    return 0


# ---- scoring --------------------------------------------------------------------------------------------------------

OUT = REPO / "evals" / "results" / "crit_t1.json"
WALL_CLOCK = ("EvaluationTime",)            # per-process wall-clock timing: differs between any two runs
# Amended post hoc (2026-11-27, D26), after V1's first score failed every pair on exactly these: two more
# files carry wall-clock time. Only these fields are removed; the all-bytes verdict is reported beside it.
WALL_CLOCK_ATTRIBUTES = {"Main/attributes.json": ("startTime", "endTime")}
WALL_CLOCK_LOG = "shell.log"
WALL_CLOCK_LOG_LINE = re.compile(rb"^ - Runtime: \d+:\d{2}:\d{2}$")
UNSHIFTED_GLUCOSE_S = 2879.0                # well4cell rc2, median birth to division, glucose fitted, no shift
SHIFT_AT = 1200.0


def _root(design: dict, seed: int) -> Path:
    import os
    os.environ.setdefault("WCECOLI_DOCKER", "score-only")      # the runner resolves run roots under runs/ in Docker mode
    sys.path.insert(0, str(REPO / "src"))
    from cellarium import runner
    from cellarium.model import Design
    return REPO / runner._run_subpath(Design(**design), seed, "cellarium")


def _sim_out(root: Path, gen: int) -> Path:
    return root / f"generation_{gen:06d}" / "000000" / "simOut"


def _without_wall_clock(rel: str, data: bytes) -> bytes:
    """The bytes compared under the amended rule: a wall-clock field removed, everything else kept."""
    if rel in WALL_CLOCK_ATTRIBUTES:
        d = json.loads(data)
        for k in WALL_CLOCK_ATTRIBUTES[rel]:
            d.pop(k, None)
        return json.dumps(d, sort_keys=True).encode()
    if rel == WALL_CLOCK_LOG:
        return b"\n".join(ln for ln in data.splitlines() if not WALL_CLOCK_LOG_LINE.match(ln))
    return data


def _digests(sim_out: Path) -> dict:
    """{relative path: (sha256 of the bytes, sha256 without wall-clock fields)} for every file under simOut except the
    wall-clock listener. One read per file: the two digests differ only for the wall-clock carriers."""
    out = {}
    for f in sorted(sim_out.rglob("*")):
        rel = f.relative_to(sim_out).as_posix()
        if f.is_file() and rel.split("/")[0] not in WALL_CLOCK:
            data = f.read_bytes()
            raw = hashlib.sha256(data).hexdigest()
            kept = _without_wall_clock(rel, data)
            out[rel] = (raw, raw if kept is data else hashlib.sha256(kept).hexdigest())
    return out


def score_v1(plan: dict) -> dict:
    """Each static pair, file by file. A missing generation is named, never counted as identical."""
    by_id = {r["id"]: r for r in plan["runs"]}
    res = {}
    for name in STATIC:
        a, b = by_id[f"V1-{name}-medium"], by_id[f"V1-{name}-relaxed"]
        gens = []
        for g in range(a["generations"]):
            sa, sb = _sim_out(_root(a["design"], a["seed"]), g), _sim_out(_root(b["design"], b["seed"]), g)
            if not (sa.is_dir() and sb.is_dir()):
                gens.append({"gen": g, "absent": [str(p) for p in (sa, sb) if not p.is_dir()]})
                continue
            da, db = _digests(sa), _digests(sb)
            keys = set(da) | set(db)
            raw = sorted(k for k in keys if (da.get(k) or (None,))[0] != (db.get(k) or (None,))[0])
            differ = sorted(k for k in keys if (da.get(k) or (None, None))[1] != (db.get(k) or (None, None))[1])
            gens.append({"gen": g, "files_compared": len(keys), "differ": differ[:40], "n_differ": len(differ),
                         "differ_all_bytes": raw[:40], "wall_clock_only": sorted(set(raw) - set(differ))})
        complete = all("absent" not in x for x in gens)
        res[name] = {"identical": complete and all(x["n_differ"] == 0 for x in gens), "complete": complete,
                     "identical_all_bytes": complete and all(not x["differ_all_bytes"] for x in gens),
                     "generations": gens}
    return res


def _steps(t, m):
    """Step-to-step changes of the threshold, from its first WRITTEN value. The listener's first row of every generation
    is 0 (written before the process runs), so a diff over all rows reports a 975 fg step at birth in every run, relaxed
    or not (seen in the smoke test, 2026-11-27). Returns (steps, the time each step lands)."""
    import numpy as np
    t, m = np.asarray(t, float), np.asarray(m, float)
    keep = m > 0
    t, m = t[keep], m[keep]
    return np.abs(np.diff(m)), t[1:]


_WORKER = r'''
import json, sys
import numpy as np
from wholecell.io.tablereader import TableReader
''' + "\n" + __import__("inspect").getsource(_steps) + r'''
out = {}
for sub in json.loads(sys.argv[1]):
    gens = []
    for g in range(3):
        so = f"/wcEcoli/out/{sub}/generation_{g:06d}/000000/simOut"
        try:
            t = TableReader(so + "/Main").readColumn("time")
            rd = TableReader(so + "/ReplicationData")
            m = rd.readColumn("criticalInitiationMass")
        except Exception as e:
            gens.append({"gen": g, "absent": type(e).__name__})
            continue
        steps, at = _steps(t, m)
        i = int(np.argmax(steps)) if len(steps) else 0
        gens.append({"gen": g, "start_s": float(t[0]), "end_s": float(t[-1]), "length_s": float(t[-1] - t[0]),
                     "max_step_fg": float(steps.max()) if len(steps) else 0.0,
                     "max_step_at_s": float(at[i]) if len(steps) else None,
                     "threshold_first_fg": float(m[m > 0][0]) if (m > 0).any() else None,
                     "threshold_last_fg": float(m[-1])})
    out[sub] = gens
print(json.dumps(out))
'''


def score_v3(plan: dict, image: str) -> dict:
    import subprocess
    import tempfile
    runs = [r for r in plan["runs"] if r["id"].startswith("V3-")]
    subs = {r["id"]: _root(r["design"], r["seed"]).relative_to(REPO / "runs").as_posix() for r in runs}
    with tempfile.TemporaryDirectory() as td:
        w = Path(td) / "w.py"
        w.write_text(_WORKER, encoding="utf-8")
        cmd = ["docker", "run", "--rm", "-v", f"{(REPO / 'runs').as_posix()}:/wcEcoli/out:ro", "-v", f"{w.as_posix()}:/x/w.py:ro",
               "-e", "PYTHONPATH=/wcEcoli", "-w", "/wcEcoli", image, "python", "/x/w.py", json.dumps(sorted(set(subs.values())))]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    line = next((ln for ln in reversed(r.stdout.splitlines()) if ln.startswith("{")), None)
    if line is None:
        raise SystemExit(f"no read: {(r.stderr or r.stdout)[-800:]}")
    raw = json.loads(line)
    per = {rid: raw[sub] for rid, sub in subs.items()}
    out = {}
    for name in SHIFTS:
        for rule in ("medium", "relaxed"):
            ids = [rid for rid in per if rid.startswith(f"V3-{name}-{rule}-")]
            valid = {rid: per[rid] for rid in ids if all("absent" not in g for g in per[rid])}
            post = sorted(g["length_s"] for rid in valid for g in per[rid] if g["gen"] in (1, 2))
            out[f"{name}_{rule}"] = {
                "runs": ids, "valid": sorted(valid), "invalid": sorted(set(ids) - set(valid)),
                "post_shift_generation_lengths_s": post,
                "median_post_shift_s": (post[len(post) // 2] if len(post) % 2 else
                                        (post[len(post) // 2 - 1] + post[len(post) // 2]) / 2) if len(valid) >= 2 else None,
                "shortest_generation_s": min((g["length_s"] for rid in valid for g in per[rid]), default=None),
                "largest_threshold_step_fg": max((g["max_step_fg"] for rid in valid for g in per[rid]), default=None)}
    return {"per_run": per, "summary": out}


def score() -> int:
    import os
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    res = {"spec": "CRIT tier 1 validation (pre-registered)", "plan_design_sha256": plan["design_sha256"],
           "rules": plan["rules"], "V1": score_v1(plan)}
    image = os.environ.get("WCECOLI_DOCKER")
    if image and image != "score-only":
        res["V3"] = score_v3(plan, image)
    else:
        res["V3"] = {"not_read": "WCECOLI_DOCKER is not set to the model image"}
    OUT.write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: (v.get("identical") if isinstance(v, dict) else v) for k, v in res["V1"].items()}))
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == ["plan"]:
        sys.exit(plan())
    if sys.argv[1:] == ["score"]:
        sys.exit(score())
    raise SystemExit("usage: crit_t1.py plan | score")
