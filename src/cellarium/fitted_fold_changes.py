"""The fold changes a ParCa fit USES, from the knowledge base's two tables, merged as ParCa merges them.

`reconstruction/ecoli/simulation_data.py` loads `fold_changes.tsv` and then `fold_changes_nca.tsv` (fold changes
from network component analysis), and for a (factor, target) pair both list, the second's value replaces the first's.
Rows the curation disagrees with (`Regulation_direct` > 2) and positive autoregulation are skipped. Reading
`fold_changes.tsv` alone is a proxy for the fit, and on 2026-11-26 (BV-14) it was found wrong where it mattered: NarL
at narGHJI +2.57 to +2.80 there, +0.58 to +1.75 in the fit; BaeR at mdtA +3.39 there, +0.28 in the fit; FNR at frdABCD
absent there, +0.68 to +1.43 in the fit. Two registry records and the BV-AN eval had quoted the proxy.

This mirrors the merge; it is not ParCa. The authority is the fit's own `sim_data.tf_to_fold_change`, which the tests
pin as literals read from the corpus fit's pickle, so a drift between this mirror and ParCa fails a test.
"""
from __future__ import annotations

import csv
from pathlib import Path

TABLES = ("fold_changes.tsv", "fold_changes_nca.tsv")      # ParCa's order; a later table's row replaces an earlier one


def _rows(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader([line for line in f if not line.startswith("#")], delimiter="\t"))


def merged(flat_dir: Path) -> dict:
    """{"used": {(tf, target): log2}, "curated": {...} (fold_changes.tsv alone), "replaced_by_nca": [(tf, target)],
    "supplied_by_nca": [(tf, target)]} from a checkout's reconstruction/ecoli/flat directory."""
    used: dict = {}
    by_table: dict = {name: {} for name in TABLES}
    for name in TABLES:
        for r in _rows(Path(flat_dir) / name):
            try:
                fc = float(r["log2 FC mean"])
            except (KeyError, TypeError, ValueError):
                continue
            direct = (r.get("Regulation_direct") or "").strip()
            if direct and float(direct) > 2:          # the curation disagrees with this row
                continue
            if r["TF"] == r["Target"] and fc > 0:      # positive autoregulation is not modelled
                continue
            by_table[name][(r["TF"], r["Target"])] = fc
            used[(r["TF"], r["Target"])] = fc
    curated, nca = by_table[TABLES[0]], by_table[TABLES[1]]
    return {"used": used, "curated": curated,
            "replaced_by_nca": sorted(k for k in nca if k in curated and curated[k] != nca[k]),
            "supplied_by_nca": sorted(k for k in nca if k not in curated)}
