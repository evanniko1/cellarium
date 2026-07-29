"""EXT-3 — audit the per-gene tRNA abundance file that every corpus run depends on.

`reconstruction/ecoli/flat/trna_data/trna_ratio_to_16SrRNA_*.tsv` gives one abundance per tRNA GENE (86 rows).
Dong, Nilsson & Kurland (1996) measured tRNA per SPECIES (~44), and a species is defined by its anticodon, not
by which of several identical genes encodes it. So the per-gene file is a disaggregation of species-level
measurements, and no rule for that disaggregation is documented anywhere in the model.

This matters twice over. For any per-isoacceptor prediction, charged fraction goes as demand/abundance, so this
file IS the prediction. And independently of that, this file sets tRNA cistron expression in every run the
corpus already contains.

**THE POOLING RULE IS DECLARED HERE, BEFORE ANY COMPARISON.**

    RULE: SUM the per-gene values of all genes sharing an anticodon.

Declared because abundance is EXTENSIVE: if four genes each transcribe the same tRNA molecule, the cell's pool
of that species is the sum of what they produce, not the average. The alternative (mean) would be right only if
the file already stored a species total replicated onto each of its genes. Which of those two the file actually
is, is exactly what this audit determines — so the rule is fixed in advance and the answer is allowed to make
it wrong. Choosing the rule after seeing which one agrees with an external dataset is the HARKing failure this
project has a whole eval suite about.

The decisive checks need no external data:

  1. WITHIN-ANTICODON CONSISTENCY. Genes encoding the same molecule either carry the same value (the file is
     species-level, replicated -> pool by MEAN) or different ones (genuinely per-gene -> pool by SUM). If they
     differ *arbitrarily*, the per-gene split carries no information.
  2. CROSS-FAMILY VALUE SHARING. If unrelated genes across different amino acids carry identical values, those
     values cannot be per-gene measurements — they are a shared bucket, and the apparent per-gene resolution is
     an artifact.
  3. DISTINCT-VALUE COUNT. 86 genes drawn from N distinct values bounds how much information the file can
     carry at all.

Usage:  python scripts/audit_trna_abundance.py [--wcecoli PATH]
"""

from __future__ import annotations

import argparse
import collections
import csv
import os
import statistics
import sys

POOLING_RULE = "sum"          # DECLARED IN ADVANCE — see module docstring. Do not change to fit a result.

RATIO_REL = os.path.join("reconstruction", "ecoli", "flat", "trna_data")
RNAS_REL = os.path.join("reconstruction", "ecoli", "flat", "rnas.tsv")


def _read_tsv(path: str) -> list[dict]:
    """wcEcoli flat files are TSV with '#' comment lines above the header."""
    with open(path, encoding="utf-8") as f:
        lines = [ln for ln in f if not ln.startswith("#")]
    return list(csv.DictReader(lines, delimiter="\t"))


def _strip(v):
    return (v or "").strip().strip('"')


def load_anticodons(wcecoli: str) -> dict[str, str]:
    """rna id -> anticodon, from rnas.tsv. Keyed to match the abundance file's `rna id` (e.g. 'leuP-tRNA')."""
    rows = _read_tsv(os.path.join(wcecoli, RNAS_REL))
    out = {}
    for r in rows:
        rid, ac = _strip(r.get("id")), _strip(r.get("anticodon"))
        if not rid or not ac or ac in ("[]", ""):
            continue
        out[rid] = ac.replace("[", "").replace("]", "").replace('"', "").strip()
    return out


def audit(wcecoli: str, growth: str = "0p4") -> dict:
    ratio_path = os.path.join(wcecoli, RATIO_REL, f"trna_ratio_to_16SrRNA_{growth}.tsv")
    rows = _read_tsv(ratio_path)
    col = next(c for c in rows[0] if "ratio" in c.lower())
    abund = {_strip(r["rna id"]): float(r[col]) for r in rows if _strip(r.get("rna id"))}
    anticodon = load_anticodons(wcecoli)

    matched = {g: a for g, a in ((g, anticodon.get(g)) for g in abund) if a}
    unmapped = sorted(g for g in abund if g not in matched)

    by_ac: dict[str, list[tuple[str, float]]] = collections.defaultdict(list)
    for g, a in matched.items():
        by_ac[a].append((g, abund[g]))

    # --- check 1: within-anticodon consistency ---
    multi = {a: v for a, v in by_ac.items() if len(v) > 1}
    identical, differing = [], []
    for a, members in sorted(multi.items()):
        vals = {round(v, 6) for _g, v in members}
        (identical if len(vals) == 1 else differing).append(
            {"anticodon": a, "genes": [g for g, _ in members], "values": sorted(v for _g, v in members)})

    # --- check 2: cross-family value sharing ---
    # An amino-acid label from the gene name prefix (leuP -> leu). Crude but sufficient: the question is only
    # whether a single value is shared across genes of DIFFERENT amino acids.
    def aa_of(gene: str) -> str:
        return gene[:3].lower()

    by_val: dict[float, list[str]] = collections.defaultdict(list)
    for g, v in abund.items():
        by_val[round(v, 6)].append(g)
    shared_across_aa = []
    for v, genes in sorted(by_val.items()):
        aas = {aa_of(g) for g in genes if not g.startswith("RNA0")}
        if len(genes) > 1 and len(aas) > 1:
            shared_across_aa.append({"value": v, "n_genes": len(genes), "amino_acids": sorted(aas),
                                     "genes": sorted(genes)})

    # --- check 3: information content ---
    distinct = len({round(v, 6) for v in abund.values()})

    # --- the declared pooling, applied ---
    pooled = {a: (sum(v for _g, v in m) if POOLING_RULE == "sum"
                  else statistics.mean(v for _g, v in m)) for a, m in by_ac.items()}

    return {
        "file": ratio_path,
        "n_genes": len(abund), "n_distinct_values": distinct,
        "n_anticodon_species": len(by_ac), "n_unmapped_genes": len(unmapped), "unmapped": unmapped[:12],
        "pooling_rule_declared": POOLING_RULE,
        "within_anticodon": {
            "n_multi_gene_species": len(multi),
            "n_identical": len(identical), "n_differing": len(differing),
            "differing_examples": differing[:6],
        },
        "cross_family_sharing": {
            "n_values_shared_across_amino_acids": len(shared_across_aa),
            "n_genes_involved": sum(x["n_genes"] for x in shared_across_aa),
            "examples": shared_across_aa[:6],
        },
        "pooled_species": dict(sorted(pooled.items())),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--wcecoli", default=os.environ.get("WCECOLI_DIR", "C:/dev/wcEcoli"))
    ap.add_argument("--growth", default="0p4")
    a = ap.parse_args(argv)
    r = audit(a.wcecoli, a.growth)

    print(f"file: {r['file']}")
    print(f"genes: {r['n_genes']}   distinct values: {r['n_distinct_values']}   "
          f"anticodon species: {r['n_anticodon_species']}   unmapped: {r['n_unmapped_genes']}")
    if r["unmapped"]:
        print(f"   unmapped examples: {r['unmapped']}")
    w = r["within_anticodon"]
    print(f"\nCHECK 1 — within-anticodon consistency ({w['n_multi_gene_species']} species have >1 gene)")
    print(f"   all genes identical : {w['n_identical']}")
    print(f"   genes DIFFER        : {w['n_differing']}")
    for d in w["differing_examples"]:
        print(f"      {d['anticodon']}: {d['genes']} -> {d['values']}")
    c = r["cross_family_sharing"]
    print("\nCHECK 2 — the same value shared across DIFFERENT amino acids")
    print(f"   values shared across amino acids: {c['n_values_shared_across_amino_acids']} "
          f"(covering {c['n_genes_involved']} genes)")
    for x in c["examples"]:
        print(f"      {x['value']}: {x['amino_acids']} -> {x['genes']}")
    print(f"\nCHECK 3 — information content: {r['n_genes']} genes drawn from "
          f"{r['n_distinct_values']} distinct values")
    return 0


if __name__ == "__main__":
    sys.exit(main())
