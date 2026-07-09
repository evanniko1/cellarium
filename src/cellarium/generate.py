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


def panel_designs() -> list[Design]:
    """A literature-grounded in-envelope panel extending the default trio with genuinely new science:

    - Carbon/oxygen condition sweep (static, fitted): a glucose-limitation gradient + poor carbon sources +
      anaerobic — the nutrient-growth law across substrate quality (Monod; Schaechter growth law).
    - ppGpp causal titration on minimal media (ppgpp_conc variant clamps [ppGpp] and disables its dynamics):
      turns the ppGpp<->growth *correlation* we saw into a *causal* dose-response (stringent-response biology).
    - AA up-shift (relaxation): the complement of the downshift already in the corpus.
    - rRNA-operon knockout series (1..6 of 7 operons): ribosome-synthesis-capacity limitation of growth.

    All indices verified against the model's own variant_map. basal(0)/with_aa(4)/downshift already in corpus.
    """
    conditions = {1: "glc_20mM", 2: "glc_5mM", 3: "glc_2mM", 5: "acetate", 6: "succinate", 7: "no_oxygen"}
    ppgpp = {0: "0.2x", 2: "0.6x", 7: "1.6x", 9: "2.0x"}   # ppgpp_conc on basal (idx//10==0); 4=control skipped
    rrna = {2: "2op", 4: "4op", 6: "6op"}                   # rrna_operon_knockout: KO n operons in minimal
    designs = [Design(perturbation="condition", condition=lbl, params={"variant_index": i})
               for i, lbl in conditions.items()]
    designs += [Design(perturbation="ppgpp_conc", condition=f"basal|ppGpp:{lbl}", params={"variant_index": i})
                for i, lbl in ppgpp.items()]
    designs.append(Design(perturbation="timeline", timeline="0 minimal, 1200 minimal_plus_amino_acids"))  # up-shift
    designs += [Design(perturbation="rrna_operon_knockout", condition=f"minimal|rRNA_KO:{lbl}",
                       params={"variant_index": i}) for i, lbl in rrna.items()]
    return designs


def stress_designs() -> list[Design]:
    """Nutrient / ion / electron-acceptor stress — hypotheses distinct from the ppGpp + carbon/O2 panels.
    Each engages a different pathway: phosphate starvation (pho regulon), Mg limitation (translation/ribosome),
    nitrate respiration (electron-transport rewiring), arabinose (alt sugar), indole (signalling/persistence).
    Indices verified against variant_map; all are static, in-envelope conditions."""
    conditions = {12: "minus_phosphate", 11: "minus_magnesium", 17: "plus_nitrate",
                  14: "plus_arabinose", 16: "plus_indole"}
    return [Design(perturbation="condition", condition=lbl, params={"variant_index": i})
            for i, lbl in conditions.items()]


def confounded_designs() -> list[Design]:
    """The three panel arms that were confounded at 1 generation — they are steady-state effects the inherited
    parent state masks in gen 0. Re-run these with --generations 4 to let them reach steady state: the ppGpp
    clamp (does the low-side Zhu downturn emerge once metabolic proteins dilute?), the rRNA-operon KO series,
    and the AA up-shift (later generations sit in the post-shift media)."""
    ppgpp = {0: "0.2x", 2: "0.6x", 7: "1.6x", 9: "2.0x"}
    rrna = {2: "2op", 4: "4op", 6: "6op"}
    designs = [Design(perturbation="ppgpp_conc", condition=f"basal|ppGpp:{lbl}", params={"variant_index": i})
               for i, lbl in ppgpp.items()]
    designs += [Design(perturbation="rrna_operon_knockout", condition=f"minimal|rRNA_KO:{lbl}",
                       params={"variant_index": i}) for i, lbl in rrna.items()]
    designs.append(Design(perturbation="timeline", timeline="0 minimal, 1200 minimal_plus_amino_acids"))
    return designs


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
    ap.add_argument("--panel", action="store_true",
                    help="run the extended literature-grounded panel (carbon/O2 sweep, ppGpp titration, "
                         "AA up-shift, rRNA-operon KO) instead of the default trio")
    ap.add_argument("--confounded", action="store_true",
                    help="re-run the arms that need multiple generations (ppGpp clamp, rRNA KO, up-shift); "
                         "pair with --generations 4")
    ap.add_argument("--stress", action="store_true",
                    help="run the nutrient/ion/electron-acceptor stress panel (distinct from ppGpp/carbon)")
    args = ap.parse_args()

    if args.panel:
        designs = panel_designs()
    elif args.stress:
        designs = stress_designs()
    elif args.confounded:
        designs = confounded_designs()
    elif args.knockout:
        designs = knockout_designs(args.knockout)
    else:
        designs = default_designs()
    shard = manifest.campaign(designs, list(range(args.seeds)), args.generations, args.parallel)
    print(f"Wrote manifest shard: {shard}")


if __name__ == "__main__":
    main()
