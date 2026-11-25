"""The condition table is append-only, because the `condition` variant's index is a POSITION in it.

`sim_data.ordered_conditions` is built by walking condition_defs.tsv in file order (simulation_data.py), and the
condition variant picks `ordered_conditions[index]`. A row inserted mid-table shifts every later index: found on
2026-11-25, the campaign checkout had minus_leu/minus_thr/minus_arg inserted after with_aa, so a knowledge base fitted
from it would have run `condition` index 5 as minus_leu instead of acetate, under acetate's label. The image and this
overlay keep them at the end; this pins that order literally."""
from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
OVERLAY = REPO / "model_overlay" / "files" / "reconstruction" / "ecoli" / "flat" / "condition" / "condition_defs.tsv"

# The order every corpus knowledge base was fitted with, then the BV-14 row appended (2026-11-25).
ORDER = ["basal", "glc_20mM", "glc_5mM", "glc_2mM", "with_aa", "acetate", "succinate", "no_oxygen", "fumarate",
         "malate", "minus_calcium", "minus_magnesium", "minus_phosphate", "no_glucose", "plus_arabinose",
         "plus_gallate", "plus_indole", "plus_nitrate", "plus_nitrite", "plus_quercetin", "plus_tungstate",
         "minus_leu", "minus_thr", "minus_arg", "no_oxygen_plus_nitrate"]


def _conditions() -> list[str]:
    lines = [ln for ln in OVERLAY.read_text(encoding="utf-8").splitlines() if not ln.lstrip().startswith("#")]
    return [r["condition"] for r in csv.DictReader(io.StringIO("\n".join(lines)), delimiter="\t")]


def test_the_condition_table_keeps_every_existing_position():
    assert _conditions() == ORDER


def test_every_condition_design_the_launcher_builds_points_at_its_own_row():
    from cellarium import generate
    conds = _conditions()
    designs = []
    for fn in ("default_designs", "panel_designs", "power_designs", "stress_designs", "confounded_designs"):
        designs += getattr(generate, fn)()
    checked = [(d.condition, d.params["variant_index"]) for d in designs
               if d.perturbation == "condition" and "variant_index" in d.params]
    assert checked, "no condition design found: the guard would be vacuous"
    for name, idx in checked:
        assert conds[idx] == name, (name, idx, conds[idx])
