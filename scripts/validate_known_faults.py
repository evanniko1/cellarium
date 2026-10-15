"""Audit experiments for simulator faults reported by a large external campaign on the same model lineage.

Each experiment tests whether a fault exists in CELLARIUM'S model (upstream wcEcoli a4497e17 + the overlay),
run through Cellarium's own runner. Output goes to `runs_validation/` (gitignored), which already holds the
standard knowledge base and the two wild-type null-arm runs of the phosphate campaign; nothing is appended to
the corpus manifest.

  E1  tf_activity variant 14 (cytR inactive -> medium minimal_plus_cytidine, which has no doubling time in
      Cellarium's condition table) and variant 13 (cytR active) as the control             1 seed each
  E2  glucose removed at 1,200 s from an established minimal-medium cell                  seeds 0-3, 2 gens
      glucose absent from the start (condition variant 13, no_glucose)                     seeds 0-1, 1 gen
  E3  leucine auxotroph (variant 1818 = TU leuLABCD) in minimal medium, no leucine source   seeds 0-3, 4 gens

    python scripts/validate_known_faults.py run
    python scripts/validate_known_faults.py analyse
"""

from __future__ import annotations

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "runs_validation"
os.environ["CELLARIUM_OUT"] = str(OUT)
for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"'))
sys.path.insert(0, str(REPO / "src"))

from cellarium import failures, runner  # noqa: E402
from cellarium.model import Design  # noqa: E402

RESULT = REPO / "evals" / "results" / "known_faults_validation.json"
GLC_REMOVED_AT = 1200

ARMS = {
    "E1_tf_cytR_inactive": (Design(perturbation="tf_activity", params={"variant_index": 14}), [0], 1),
    "E1_tf_cytR_active": (Design(perturbation="tf_activity", params={"variant_index": 13}), [0], 1),
    "E2_glucose_removed_1200s": (Design(perturbation="timeline",
                                        timeline=f"0 minimal, {GLC_REMOVED_AT} minimal_no_glucose"), [0, 1, 2, 3], 2),
    "E2_glucose_absent": (Design(perturbation="condition", condition="no_glucose", params={"variant_index": 13}),
                          [0, 1], 1),
    "E3_leucine_auxotroph_minimal": (Design(perturbation="gene_knockout", condition="KO:leuB",
                                            params={"variant_index": 1818}), [0, 1, 2, 3], 4),
}
NULL = ("C_null_wildtype_minimal", Design(perturbation="wildtype", condition="basal"), [0, 1])


def run() -> int:
    jobs = [(arm, d, s, g) for arm, (d, seeds, g) in ARMS.items() for s in seeds]
    # Longest first, so the 4-generation auxotroph does not start last.
    jobs.sort(key=lambda j: -j[3])
    status = {}
    print(f"{len(jobs)} simulations, 6 at a time, into {OUT}", flush=True)
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(runner.run_one, d, s, g, "cellarium"): (arm, s) for arm, d, s, g in jobs}
        for f in as_completed(futs):
            arm, s = futs[f]
            try:
                f.result()
                status[f"{arm}/s{s}"] = "completed"
            except Exception as exc:
                status[f"{arm}/s{s}"] = f"failed: {type(exc).__name__}"
            print(f"  {arm} seed {s}: {status[f'{arm}/s{s}']}", flush=True)
    (OUT / "status_known_faults.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    return 0


_ROW = re.compile(r"^\s*(-?\d+\.\d+)" + r"\s+(-?\d+\.\d+)" * 6 + r"\s*$")


def _cells(text: str) -> list[list[dict]]:
    cells: list[list[dict]] = [[]]
    for ln in text.splitlines():
        m = _ROW.match(ln)
        if not m:
            continue
        v = [float(x) for x in m.groups()]
        row = {"t": v[0], "dry": v[1], "fold": v[2], "expected": v[6]}
        if cells[-1] and row["dry"] < 0.7 * cells[-1][-1]["dry"]:
            cells.append([])
        cells[-1].append(row)
    return [c for c in cells if c]


def _summary(arm: str, d: Design, s: int) -> dict:
    root = runner._run_subpath(d, s, "cellarium")
    text = failures.read_log(root) or ""
    ident = failures.identify(log_text=text) if text else failures.identify(run_root=None)
    cells = _cells(text)
    rec = {"identity_key": ident.key, "named": ident.named, "message": (ident.message or "")[:200],
           "ran_out": ident.detail.get("ran_out"), "n_cells": len(cells),
           "cells": [{"start_s": c[0]["t"], "end_s": c[-1]["t"], "duration_s": round(c[-1]["t"] - c[0]["t"], 1),
                      "final_fold": c[-1]["fold"], "final_expected": c[-1]["expected"]} for c in cells]}
    return rec


def analyse() -> int:
    status = {}
    p = OUT / "status_known_faults.json"
    if p.exists():
        status = json.loads(p.read_text(encoding="utf-8"))
    res = {"status": status, "runs": {}}
    for arm, (d, seeds, g) in list(ARMS.items()) + [(NULL[0], (NULL[1], NULL[2], 1))]:
        for s in seeds:
            res["runs"][f"{arm}/s{s}"] = _summary(arm, d, s)
    RESULT.write_text(json.dumps(res, indent=2), encoding="utf-8")
    for k, r in res["runs"].items():
        print(k, "|", r["identity_key"], "|", r["message"][:90], "|",
              [(c["start_s"], c["duration_s"], c["final_fold"]) for c in r["cells"]])
    return 0


if __name__ == "__main__":
    sys.exit({"run": run, "analyse": analyse}[sys.argv[1]]())
