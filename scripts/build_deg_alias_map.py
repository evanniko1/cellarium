"""Build the gene-space index for PARCA-6 Tier 1 — one-shot generator, output committed.

WHY THIS EXISTS. `data/parca/deg_rate_baseline.json` names the 854 mRNA units whose degradation rate is not a
fit. Its unit ids live in TRANSCRIPTION-UNIT space (`TU-8392[c]`, `EG10001_RNA[c]`). Every tool payload that a
reader actually sees names GENES: a symbol (`rplE`), a monomer id (`EG10868-MONOMER`), a cistron id
(`EG10868_RNA`). Those two id spaces do not overlap, so the "dict lookup" the Tier-1 design assumed does not
exist — measured against the baseline, a bare-symbol match reaches 6 of 854 units and 1.708% of mRNA
expression, against 12.087% for the full set. This script builds the missing join once, offline, and freezes
it, so the runtime stamp stays a dict lookup with no model image behind it.

THE JOIN. `transcription_units*.tsv` gives unit -> gene ids; `rnas.tsv` gives gene id -> cistron id, symbol
and monomer ids. Composing them gives every name a payload could plausibly carry for a unit that is not a fit.

THE FOUR TU FILES, NOT ONE — this is the part that bites. The base table is edited by
`transcription_units_{added,modified,removed}.tsv` before ParCa ever sees it, and 7 of the not-a-fit unit ids
exist ONLY in the added file. Resolving against the base table alone leaves those 7 unmatched, and the
tempting repair — prefix-matching `rplNXE-rpsNH-rplFR-rpsE-rpmD-rplO` onto the base table's
`rplNXE-rpsNH-rplFR-rpsE-rpmD-rplO-secY-rpmJ` — is WRONG: those are different units with different gene
lists, and the prefix match attributes `secY` and `rpmJ` to a floor rate that belongs to neither. Applying all
four files in ParCa's order resolves all 854 units exactly, with no prefix guessing and no residue.

WEIGHTS ARE PER GENE AND DO NOT SUM. A gene's weight is the total mRNA expression share of the not-a-fit units
it belongs to. Two genes in one operon each carry that operon's full share, so summing across genes
double-counts; the corpus total is and stays the baseline's 12.087%.

SOURCE FILES LIVE OUTSIDE THIS REPO. `transcription_units*.tsv` are read from the wcEcoli tree (WCECOLI_DIR,
default C:/dev/wcEcoli) and are NOT vendored here. Their sha256 is recorded in the output so a future mismatch
is detectable rather than silent. `rnas.tsv` is read from this repo's own pinned overlay.

    python scripts/build_deg_alias_map.py            # writes data/parca/deg_rate_aliases.json
    python scripts/build_deg_alias_map.py --check    # regenerate in memory and diff against the committed file
"""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import io
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BASELINE = REPO / "data" / "parca" / "deg_rate_baseline.json"
OUT = REPO / "data" / "parca" / "deg_rate_aliases.json"
OVERLAY_RNAS = REPO / "model_overlay" / "files" / "reconstruction" / "ecoli" / "flat" / "rnas.tsv"


def _flat_dir() -> Path:
    root = os.environ.get("WCECOLI_DIR") or os.environ.get("WCECOLI_PATH")
    if not root:
        raise SystemExit("set WCECOLI_DIR (or WCECOLI_PATH) to your wcEcoli checkout; there is "
                         "deliberately no default path.")
    root = Path(root)
    return root / "reconstruction" / "ecoli" / "flat"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _tsv(p: Path) -> list[dict]:
    """A wcEcoli flat file: tab-separated, `#` comment lines above the header."""
    lines = [ln for ln in io.open(p, encoding="utf-8") if not ln.startswith("#")]
    return list(csv.DictReader(lines, delimiter="\t"))


def _effective_tus(flat: Path) -> dict[str, dict]:
    """The transcription units ParCa actually sees: base, minus removed, with modified and added applied.

    Order matters and is not cosmetic — see the module docstring. `_removed` carries only ids and comments,
    so it is read for its ids alone.
    """
    tu = {t["id"]: t for t in _tsv(flat / "transcription_units.tsv")}
    for t in _tsv(flat / "transcription_units_removed.tsv"):
        tu.pop(t["id"], None)
    for t in _tsv(flat / "transcription_units_modified.tsv"):
        tu[t["id"]] = t
    for t in _tsv(flat / "transcription_units_added.tsv"):
        tu[t["id"]] = t
    return tu


def build() -> dict:
    flat = _flat_dir()
    missing = [str(flat / f) for f in ("transcription_units.tsv", "transcription_units_added.tsv",
                                       "transcription_units_modified.tsv", "transcription_units_removed.tsv")
               if not (flat / f).exists()]
    if missing:
        raise SystemExit("cannot build the alias map — these wcEcoli flat files are not readable:\n  "
                         + "\n  ".join(missing)
                         + "\nSet WCECOLI_DIR to the model tree. This generator is a one-shot; the RUNTIME "
                           "never needs these files, only the committed output.")

    tu = _effective_tus(flat)
    rnas = _tsv(OVERLAY_RNAS)
    rna_by_id = {r["id"]: r for r in rnas}
    rna_by_gene = {r["gene_id"]: r for r in rnas}

    doc = json.loads(BASELINE.read_text(encoding="utf-8"))
    units = doc["units_not_a_fit"]
    rows = [(uid, cls, pct) for cls in ("floor", "ceiling", "imputed")
            for uid, pct in (units.get(cls) or {}).items()]

    genes: dict[str, dict] = {}
    alias: dict[str, str] = {}
    collisions: list[str] = []
    unresolved: list[str] = []
    routes: collections.Counter = collections.Counter()

    # `rnas.tsv` writes an absent common_name as the literal string "null", which would otherwise become a
    # live alias matching any payload that carries a JSON null rendered as text. Two-character keys are
    # dropped as well: they match too much for what they would buy. Three IS kept — `fur`, `hfq`, `rmf` and
    # `pnp` are real symbols, and `rmf` alone is the 12th-heaviest gene in this set.
    _NOT_AN_ID = {"null", "none", "na", "nan", "-", ""}

    def _alias(key: str, gene_id: str) -> None:
        if not key or key.strip().lower() in _NOT_AN_ID or len(key.strip()) < 3:
            return
        k = key.lower()
        prior = alias.get(k)
        if prior is None:
            alias[k] = gene_id
        elif prior != gene_id:
            # Recorded, never silently resolved: an alias that points at two genes cannot mark a payload
            # honestly, so it is dropped from the index and named in the output.
            collisions.append(k)
            alias.pop(k, None)

    for uid, cls, pct in rows:
        bare = re.sub(r"\[[a-z]\]$", "", uid)
        if bare in tu:
            gene_ids, route = json.loads(tu[bare]["genes"]), "tu_id"
        elif bare in rna_by_id:
            gene_ids, route = [rna_by_id[bare]["gene_id"]], "cistron_id"
        else:
            unresolved.append(uid)
            continue
        routes[route] += 1
        for gid in gene_ids:
            r = rna_by_gene.get(gid)
            if r is None:            # a gene in the TU table with no RNA row — record, never invent
                unresolved.append(f"{uid}:{gid}")
                continue
            rec = genes.setdefault(gid, {"sym": r["common_name"] or None, "pct": 0.0,
                                         "cls": [], "units": []})
            rec["pct"] = round(rec["pct"] + pct, 6)
            if cls not in rec["cls"]:
                rec["cls"].append(cls)
            if uid not in rec["units"]:
                rec["units"].append(uid)
            _alias(gid, gid)
            _alias(r["id"], gid)
            _alias(r["common_name"], gid)
            for mon in json.loads(r["monomer_ids"] or "[]"):
                _alias(mon, gid)

    for k in set(collisions):        # a collision seen after the key was already claimed must still be gone
        alias.pop(k, None)

    ranked = sorted((g["pct"] for g in genes.values()), reverse=True)
    dist = {f"gt_{t}": sum(1 for v in ranked if v > t) for t in (0.0, 0.01, 0.1, 0.5, 1.0)}

    return {
        "generated_by": "scripts/build_deg_alias_map.py",
        "baseline_kb_sha256": doc.get("kb_sha256"),
        "baseline_units_not_a_fit": len(rows),
        "sources": {
            "transcription_units.tsv": _sha(flat / "transcription_units.tsv"),
            "transcription_units_added.tsv": _sha(flat / "transcription_units_added.tsv"),
            "transcription_units_modified.tsv": _sha(flat / "transcription_units_modified.tsv"),
            "transcription_units_removed.tsv": _sha(flat / "transcription_units_removed.tsv"),
            "rnas.tsv": _sha(OVERLAY_RNAS),
        },
        "resolution_routes": dict(routes),
        "unresolved": unresolved,
        "alias_collisions_dropped": sorted(set(collisions)),
        "n_genes": len(genes),
        "n_aliases": len(alias),
        "gene_weight_distribution": dist,
        "note": ("`pct` is the share of total mRNA expression carried by the not-a-fit transcription units "
                 "this gene belongs to. Per-gene weights DO NOT SUM to the corpus total: genes sharing an "
                 "operon each carry that operon's full share. The corpus total is the baseline's 12.087%."),
        "genes": genes,
        "alias": alias,
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="rebuild in memory and compare against the committed file; do not write")
    args = ap.parse_args(argv)

    built = build()
    if built["unresolved"]:
        print(f"REFUSING to write: {len(built['unresolved'])} unit(s) did not resolve to genes — "
              f"{built['unresolved'][:6]}", file=sys.stderr)
        return 2

    if args.check:
        if not OUT.exists():
            print(f"no committed map at {OUT}", file=sys.stderr)
            return 1
        have = json.loads(OUT.read_text(encoding="utf-8"))
        same = (have.get("alias") == built["alias"] and have.get("genes") == built["genes"]
                and have.get("sources") == built["sources"])
        print("MATCHES the committed map" if same else
              "DIFFERS from the committed map — the flat files or the baseline moved; regenerate deliberately")
        return 0 if same else 1

    OUT.write_text(json.dumps(built, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    print(f"  routes            {built['resolution_routes']}")
    print(f"  genes             {built['n_genes']}")
    print(f"  aliases           {built['n_aliases']}")
    print(f"  collisions droppd {len(built['alias_collisions_dropped'])}")
    print(f"  weight spread     {built['gene_weight_distribution']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
