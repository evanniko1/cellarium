"""Build data/cache/ko_footprint.json — what a `gene_knockout` variant ACTUALLY does.

THE MECHANISM, traced through the Covert model and then verified against real simulation output.

`models/ecoli/sim/variants/gene_knockout.py` computes a `geneIndex` and calls
`sim_data.adjust_final_expression([geneIndex], [0])`. That function (`reconstruction/ecoli/simulation_data.py`)
zeroes `transcription.rna_synth_prob[i]` and `transcription.rna_expression[i]` — vectors indexed over
`rna_data`, whose rows are **transcription units**, not genes. So a "gene knockout" zeroes ONE TU.

THE RULE, and it is exact: zeroing one TU **fully silences a gene if and only if that gene has exactly one TU**
(`n_tu == 1` in the scope map). Validated at **27/27** against measured mRNA counts from existing local simOut
(`KO:flgB`, `KO:rpmJ`, `KO:rpoB` vs `wildtype/basal`) — no prediction missed. Three consequences follow, and
all three are real in the shipped corpus:

  1. **Target `n_tu == 1`** → genuinely knocked out, AND every co-member of its TU with `n_tu == 1` is silenced
     too. `KO:flgB` zeroes all nine of flgBCDEFGHIJ (measured: 0.0 vs 5.8 in WT, while flgA/flgK/flgM/fliC on
     other TUs are untouched — so it is the TU, not the flagellar regulon).
  2. **Target `n_tu > 1`** → **the target is NOT knocked out.** It is still transcribed from its other TUs.
     Measured: `KO:rpoB` leaves rpoB mRNA at 10.4 vs 8.4 in wildtype — no reduction at all.
  3. Either way, a co-member with `n_tu == 1` IS silenced — so a design can knock out a gene it is not named
     after. Measured: `KO:rpmJ` leaves rpmJ at 50.1 (WT 69.5) and silences **secY** to 0.0 (WT 15.8).

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

    def n_tu(g: str):
        return (gs.get(g) or {}).get("n_tu")

    out: dict = {}
    for gene, e in gs.items():
        rid = by_ko.get(e.get("ko_index"))
        if not rid:
            continue
        tid = str(rid).split("[")[0]
        tu = tus.get(tid)
        members = [sym.get(x, x) for x in json.loads(tu["genes"])] if tu else [gene]
        others = [m for m in members if m != gene]
        target_silenced = n_tu(gene) == 1
        collateral = sorted(m for m in others if n_tu(m) == 1)           # fully silenced, though not the target
        partial = sorted(m for m in others if n_tu(m) not in (1, None))  # reduced by one TU's share only
        if target_silenced and not collateral and not partial:
            continue                                                     # a clean single-gene KO: nothing to warn
        out[gene] = {"tu_id": tid, "tu_name": (tu["common_name"] if tu else None),
                     "n_genes_on_tu": len(members), "target_n_tu": n_tu(gene),
                     "target_silenced": target_silenced,
                     "collateral_silenced": collateral, "partially_reduced": partial}
    dest = ROOT / "data/cache/ko_footprint.json"
    dest.write_text(json.dumps(out, indent=0, sort_keys=True), encoding="utf-8")
    not_ko = sum(1 for v in out.values() if not v["target_silenced"])
    coll = sum(1 for v in out.values() if v["collateral_silenced"])
    print(f"{len(out)} of {len(gs)} genes have a NON-CLEAN knockout -> {dest}")
    print(f"  {not_ko} where the NAMED GENE IS NOT KNOCKED OUT (n_tu > 1)")
    print(f"  {coll} that additionally silence a different gene entirely")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
