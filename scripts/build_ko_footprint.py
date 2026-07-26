"""Build data/cache/ko_footprint.json — what a `gene_knockout` variant ACTUALLY does.

MECHANISM, traced through the Covert model. `models/ecoli/sim/variants/gene_knockout.py` calls
`sim_data.adjust_final_expression([i], [0])`; that zeroes `rna_synth_prob[i]` and `rna_expression[i]`, vectors
indexed over `rna_data`, whose rows are **transcription units** plus orphan cistrons. So ONE TU is zeroed. This
holds only because the corpus was built operons-ON — with `--operons off` every row is a cistron and none of it
applies.

EVIDENCE, and the distinction this script exists to preserve. An earlier version asserted a clean rule — "a gene
is silenced iff it has exactly one TU", claimed 27/27 — which was OVERFIT to three genes. Across 41
measurements it is 40/41, and the failure is the informative half:

  * `n_tu == 1` -> silenced: no counterexample in 41. A safe SUFFICIENT condition.
  * `n_tu > 1`  -> survives:  **FALSE.** `KO:dapA` fully silenced `bamC` (n_tu=2), measured 0.0 vs 2.6.

So TU co-membership means AT RISK, and only a measurement settles it. This script therefore emits a PREDICTION,
then overwrites it with MEASUREMENT wherever data/cache/ko_measured.json has one, and records which is which in
`target_evidence`. Never let a prediction be read as a finding.

Emits three caches, all committed so no wcEcoli checkout is needed at query time:
  * ko_footprint.json  — per gene: the zeroed TU, its members, measured vs unverified status
  * cistron_map.json   — cistron_id -> gene symbol (see below; fixes unannotated mRNA results)

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
    # Also emit the CISTRON->SYMBOL map while the flat files are open. `differential._cistron_symbol_map()`
    # normally dumps this from sim_data via the model image, which fails without Docker — leaving it EMPTY, so
    # every mRNA result came back with `symbol: None` and no caller could ask "which genes moved" by name.
    # genes.tsv carries the same mapping, and the mRNA reader's ids are `<gene_id>_RNA`.
    cis = {f"{r['id']}_RNA": (r.get("symbol") or r.get("common_name")) for r in _rows(FLAT / "genes.tsv")}
    cis = {k: v for k, v in cis.items() if v}
    (ROOT / "data/cache/cistron_map.json").write_text(json.dumps(cis, sort_keys=True), encoding="utf-8")
    print(f"{len(cis)} cistron->symbol entries -> data/cache/cistron_map.json")

    # MEASUREMENT overrides PREDICTION. ko_measured.json holds real mRNA counts read from local simOut; where a
    # gene appears there, its status is fact and the n_tu prediction is discarded.
    meas_path = ROOT / "data/cache/ko_measured.json"
    measured = json.loads(meas_path.read_text(encoding="utf-8")) if meas_path.exists() else {}
    for gene, e in out.items():
        co = sorted(set((e.pop("collateral_silenced", []) or []) + (e.pop("partially_reduced", []) or [])))
        e["co_members"] = co
        m = {k: {"ko_mean": v["ko"], "wt_mean": v["wt"], "silenced": v["ko"] == 0.0}
             for k, v in (measured.get(gene) or {}).items()}
        e["measured"] = m
        e["measured_silenced"] = sorted(g for g in co if m.get(g, {}).get("silenced"))
        e["measured_expressed"] = sorted(g for g in co if g in m and not m[g]["silenced"])
        e["unverified"] = sorted(g for g in co if g not in m)
        if gene in m:
            e["target_silenced"] = m[gene]["silenced"]
            e["target_evidence"] = "measured"
        else:
            e["target_evidence"] = "predicted_from_n_tu"

    # Stamp the kb this cache describes. Every verdict in it is a claim about ONE knowledge base — rebuild the kb
    # with --operons off and the whole file becomes wrong in the most dangerous way: it would keep warning about
    # operon collateral that no longer exists. The reader compares this against the live kb and refuses to
    # pretend. (This is what the provenance added in provenance.kb_provenance() is FOR.)
    try:
        sys.path.insert(0, str(ROOT / "src"))
        from cellarium import provenance
        out["__kb__"] = provenance.kb_provenance()
    except Exception:
        pass

    dest = ROOT / "data/cache/ko_footprint.json"
    dest.write_text(json.dumps(out, indent=0, sort_keys=True), encoding="utf-8")
    _e = [v for k, v in out.items() if k != "__kb__"]
    n_meas = sum(1 for v in _e if v["target_evidence"] == "measured")
    not_ko = sum(1 for v in _e if not v["target_silenced"])
    coll = sum(1 for v in _e if v["measured_silenced"] or v["unverified"])
    print(f"{len(_e)} of {len(gs)} genes have a NON-CLEAN knockout -> {dest}")
    print(f"  {not_ko} where the NAMED GENE IS NOT KNOCKED OUT (n_tu > 1)")
    print(f"  {coll} that additionally silence a different gene entirely")
    print(f"  {n_meas} with a MEASURED outcome; the rest are predictions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
