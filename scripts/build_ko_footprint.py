"""Build data/cache/ko_footprint.json — what a `gene_knockout` variant ACTUALLY silences.

The variant does not knock out a gene. `models/ecoli/sim/variants/gene_knockout.py` computes a `geneIndex` and
calls `sim_data.adjust_final_expression([geneIndex], [0])`; that index addresses a row of `rna_data`, i.e. a
TRANSCRIPTION UNIT. For a polycistronic TU the whole operon is zeroed, so `KO:flgB` is really a nine-gene
deletion of flgBCDEFGHIJ. Over HALF the genome is affected (2,436 of 4,724 genes sit on a multi-gene TU).

Needs the wcEcoli checkout ONCE, to read the model's own flat files; the output is a committed cache so
`scope.ko_footprint()` works for everyone without it.

    WCECOLI_DIR=/path/to/wcEcoli python scripts/build_ko_footprint.py
"""
from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WC = Path(os.environ.get("WCECOLI_DIR") or "C:/dev/wcEcoli")
FLAT = WC / "reconstruction" / "ecoli" / "flat"


def _rows(p: Path) -> list[dict]:
    with p.open(encoding="utf-8") as fh:
        return list(csv.DictReader((ln for ln in fh if not ln.startswith("#")), delimiter="\t"))


def main() -> int:
    if not FLAT.exists():
        print(f"wcEcoli flat dir not found: {FLAT}\nSet WCECOLI_DIR to your checkout.", file=sys.stderr)
        return 2
    vm = json.loads((ROOT / "data/cache/variant_map.json").read_text(encoding="utf-8"))
    gs = json.loads((ROOT / "data/cache/gene_scope.json").read_text(encoding="utf-8"))
    by_ko = {e["ko_index"]: e["rna_id"] for e in vm["genes"]}
    tus = {r["id"]: r for r in _rows(FLAT / "transcription_units.tsv")}
    sym = {r["id"]: (r.get("symbol") or r.get("common_name")) for r in _rows(FLAT / "genes.tsv")}

    out: dict = {}
    for gene, e in gs.items():
        rid = by_ko.get(e.get("ko_index"))
        tu = tus.get(str(rid).split("[")[0]) if rid else None
        if not tu:
            continue
        members = [sym.get(x, x) for x in json.loads(tu["genes"])]
        if len(members) > 1:
            out[gene] = {"tu_id": str(rid).split("[")[0], "tu_name": tu["common_name"],
                         "n_genes": len(members), "co_silenced": sorted(s for s in members if s != gene)}
    dest = ROOT / "data/cache/ko_footprint.json"
    dest.write_text(json.dumps(out, indent=0, sort_keys=True), encoding="utf-8")
    print(f"{len(out)} of {len(gs)} genes have a multi-gene KO footprint -> {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
