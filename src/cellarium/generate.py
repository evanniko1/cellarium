"""Launch a first in-envelope campaign to seed the corpus (runs the public model; see docs/GENERATE.md).

Requires the model env (WCECOLI_DOCKER or WCECOLI_DIR). Every design here is inside the validated envelope.
Gene-KO panels need per-gene variant indices from the model's sim_data — derive them once with
`python -m cellarium.reader --variant-map`, then `--knockout <rna_id query>`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import manifest
from .model import Design

VARIANT_MAP_CACHE = Path("data/cache/variant_map.json")


def default_designs() -> list[Design]:
    """A small in-envelope trio: two nutrient steady states + one validated transient."""
    return [
        Design(perturbation="wildtype", condition="basal"),                    # minimal-glucose steady state
        Design(perturbation="condition", condition="with_aa",                  # rich (minimal+AA) steady state
               params={"variant_index": 4}),                                   # ordered_conditions[4]=with_aa (verified)
        Design(perturbation="timeline",                                        # AA downshift -> stringent response
               timeline="0 minimal_plus_amino_acids, 1200 minimal"),
    ]


def knockout_designs(query: str, limit: int = 8) -> list[Design]:
    """Gene-knockout designs whose rna_id matches `query`, using the cached variant map
    (run `python -m cellarium.reader --variant-map` first). Each -> --variant gene_knockout <idx>."""
    if not VARIANT_MAP_CACHE.exists():
        raise RuntimeError("run `python -m cellarium.reader --variant-map` first to derive gene indices")
    genes = json.loads(VARIANT_MAP_CACHE.read_text(encoding="utf-8")).get("genes", [])
    hits = [g for g in genes if query.lower() in g["rna_id"].lower()][:limit]
    if not hits:
        raise RuntimeError(f"no gene rna_id matched '{query}' in the variant map")
    return [Design(perturbation="gene_knockout", condition=f"KO:{g['rna_id']}",
                   params={"variant_index": g["ko_index"]}) for g in hits]


def main() -> None:
    ap = argparse.ArgumentParser(description="Seed the Cellarium corpus with an in-envelope campaign.")
    ap.add_argument("--seeds", type=int, default=4, help="number of stochastic replicate seeds")
    ap.add_argument("--generations", type=int, default=1)
    ap.add_argument("--parallel", type=int, default=1,
                    help="run this many sims concurrently (each loads ~1GB sim_data — size to host RAM)")
    ap.add_argument("--knockout", default=None,
                    help="run a gene-KO panel matching this rna_id query instead of the default trio "
                         "(needs the cached variant map)")
    args = ap.parse_args()

    designs = knockout_designs(args.knockout) if args.knockout else default_designs()
    shard = manifest.campaign(designs, list(range(args.seeds)), args.generations, args.parallel)
    print(f"Wrote manifest shard: {shard}")


if __name__ == "__main__":
    main()
