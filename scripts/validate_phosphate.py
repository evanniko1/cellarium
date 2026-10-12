"""Item 4d validation — can the model represent a cell living through phosphate depletion?

Written to SEPARATE output trees (`runs_validation*/`, gitignored), each with its own copy of the fitted
knowledge base, and never appended to the corpus manifest: these runs test a claim, they are not corpus rows,
and the existing `condition/minus_phosphate` rows must not be overwritten before the full re-run (FAIL-3).

TWO CONFIGURATIONS, because the kinetic elongation model needs the rebuilt knowledge base the corpus's own
kinetic runs used (kb 5f19d040…, with codon tables); the standard knowledge base (3b2f8ebd…) raises
`'Relation' object has no attribute 'codons'` at initialisation under kinetic mode, which is a setup error
and says nothing about phosphate.

  standard  (runs_validation/, kb from runs/cellarium)
    A  phosphate absent from the start                                steady_state  seeds 0-3, 1 gen
    B  phosphate removed at 2,400 s from an established cell          steady_state  seeds 0-3, 2 gens
    C  null arm: wild type in minimal medium                          steady_state  seeds 0-1, 1 gen
  kinetic   (runs_validation_kinetic/, kb from runs_kinetic_seeds/cellarium)
    K  phosphate absent from the start                                kinetic       seeds 0-1, 1 gen
    KC null arm: wild type in minimal medium                          kinetic       seed 0,    1 gen

    python scripts/validate_phosphate.py run standard|kinetic
    python scripts/validate_phosphate.py analyse
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CONFIGS = {"standard": (REPO / "runs_validation", REPO / "runs" / "cellarium" / "kb"),
           "kinetic": (REPO / "runs_validation_kinetic", REPO / "runs_kinetic_seeds" / "cellarium" / "kb")}
for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"'))
sys.path.insert(0, str(REPO / "src"))

RESULT = REPO / "evals" / "results" / "phosphate_validation.json"
SHIFT_AT = 2400


def _arms(Design) -> dict:
    p12 = {"variant_index": 12}
    return {
        "standard": {
            "A_absent_from_start": (Design(perturbation="condition", condition="minus_phosphate", params=p12),
                                    [0, 1, 2, 3], 1),
            "B_removed_at_2400s": (Design(perturbation="timeline",
                                          timeline=f"0 minimal, {SHIFT_AT} minimal_minus_phosphate"), [0, 1, 2, 3], 2),
            "C_null_wildtype_minimal": (Design(perturbation="wildtype", condition="basal"), [0, 1], 1),
        },
        "kinetic": {
            "K_absent_kinetic": (Design(perturbation="condition", condition="minus_phosphate", params=p12,
                                        elongation_model="kinetic"), [0, 1], 1),
            "KC_null_wildtype_kinetic": (Design(perturbation="wildtype", condition="basal",
                                                elongation_model="kinetic"), [0], 1),
        },
    }


def run(config: str) -> int:
    out, kb = CONFIGS[config]
    os.environ["CELLARIUM_OUT"] = str(out)                     # before the first cellarium import
    from cellarium import runner
    from cellarium.model import Design
    dst = out / "cellarium" / "kb"
    if not dst.exists():
        shutil.copytree(kb, dst)
    arms = _arms(Design)[config]
    jobs = [(arm, d, s, g) for arm, (d, seeds, g) in arms.items() for s in seeds]
    status = {}
    print(f"{len(jobs)} simulations, 6 at a time, into {out}", flush=True)
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
    (out / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    return 0


_ROW = re.compile(r"^\s*(-?\d+\.\d+)" + r"\s+(-?\d+\.\d+)" * 6 + r"\s*$")


def _cells(text: str) -> list[list[dict]]:
    """The model's progress table split into one list per cell: a fall in dry mass of more than 30% between
    consecutive rows is a division. (Rates computed across a division read the halving of mass as shrinkage.)"""
    cells: list[list[dict]] = [[]]
    for ln in text.splitlines():
        m = _ROW.match(ln)
        if not m:
            continue
        v = [float(x) for x in m.groups()]
        row = {"t": v[0], "dry": v[1], "protein": v[3], "rna": v[4], "small": v[5], "expected": v[6], "fold": v[2]}
        if cells[-1] and row["dry"] < 0.7 * cells[-1][-1]["dry"]:
            cells.append([])
        cells[-1].append(row)
    return [c for c in cells if c]


def _rates(rows: list[dict], t0: float, t1: float) -> dict | None:
    """Per-hour log growth of dry mass and of the protein, RNA and small-molecule fold changes in [t0, t1]."""
    pts = [r for r in rows if t0 <= r["t"] <= t1]
    if len(pts) < 2 or pts[-1]["t"] <= pts[0]["t"]:
        return None
    a, b = pts[0], pts[-1]
    h = (b["t"] - a["t"]) / 3600.0
    return {"from_s": a["t"], "to_s": b["t"],
            **{k: round(math.log(b[k] / a[k]) / h, 3) for k in ("dry", "protein", "rna", "small") if a[k] > 0}}


def analyse() -> int:
    from cellarium import failures
    from cellarium.model import Design
    res = {"note": ("K arm of the first standard batch excluded: wrong knowledge base for kinetic mode "
                    "(setup error, see module docstring)."), "runs": {}}
    for config, arms in _arms(Design).items():
        out, _ = CONFIGS[config]
        os.environ["CELLARIUM_OUT"] = str(out)
        import importlib

        from cellarium import runner
        importlib.reload(runner)
        for arm, (d, seeds, g) in arms.items():
            for s in seeds:
                root = runner._run_subpath(d, s, "cellarium")
                text = failures.read_log(root) or ""
                ident = failures.identify(log_text=text) if text else failures.identify(run_root=None)
                cells = _cells(text)
                rows = [r for c in cells for r in c]
                rec = {"config": config, "identity_key": ident.key, "named": ident.named,
                       "ran_out": ident.detail.get("ran_out"), "n_cells": len(cells),
                       "last_time_s": rows[-1]["t"] if rows else None}
                if arm.startswith("B") and cells:
                    first = cells[0]
                    rec["before_removal"] = _rates(first, SHIFT_AT - 600, SHIFT_AT)
                    rec["after_removal_same_cell"] = _rates(first, SHIFT_AT, first[-1]["t"])
                    rec["divided_after_removal_at_s"] = first[-1]["t"] if len(cells) > 1 else None
                    if len(cells) > 1:
                        rec["daughter"] = _rates(cells[1], cells[1][0]["t"], cells[1][-1]["t"])
                    rec["survived_after_removal_s"] = round(rows[-1]["t"] - SHIFT_AT, 1)
                elif cells:
                    rec["whole_run"] = _rates(cells[0], cells[0][0]["t"] + 30, cells[0][-1]["t"])
                res["runs"][f"{arm}/s{s}"] = rec
    RESULT.write_text(json.dumps(res, indent=2), encoding="utf-8")
    for k, r in res["runs"].items():
        print(k, json.dumps({kk: v for kk, v in r.items() if kk != "config"}))
    return 0


if __name__ == "__main__":
    if sys.argv[1] == "run":
        sys.exit(run(sys.argv[2]))
    sys.exit(analyse())
