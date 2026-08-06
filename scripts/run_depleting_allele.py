"""The depleting-allele experiment: does ppGpp fire when the synthetase runs down gradually?

Section 3 concluded that our instantaneous knockout, not the simulator, was at fault: with the enzyme at zero
copies from the first timestep, translation halts before any ribosome stalls, so RelA never sees the state it
detects. Three independent readers made the same objection -- that reattribution is not separable from "the
simulator cannot represent the depletion transient" until the graded design is run.

graded_gene_knockout multiplies synthesis probability by a factor in (0,1) rather than zeroing it, so the
inherited pool dilutes over generations instead of vanishing. argS sits on TU0-13444 alone, so the variant
resolves to the single row gene_knockout would have zeroed and needs no cistron hint.

Index is gene_ko_index * 10 + level, argS ko_index = 644; FACTORS {2: 0.05, 3: 0.10, 4: 0.25, 5: 0.50}.
Four generations, matching the Table 2 reproductions, because depletion needs depth to show.
"""
import os
import sys

if not os.environ.get("CELLARIUM_OUT"):
    sys.exit("refusing to run without CELLARIUM_OUT — it is read at import time by runner.OUT_ROOT, so an "
             "unset value would write into the default corpus root and collide with existing runs")

# `python scripts/x.py` puts scripts/ on sys.path, not the repo root, so `src` is not importable
# the way it is under `python -c` from the checkout.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.cellarium.model import Design            # noqa: E402  (import AFTER CELLARIUM_OUT is fixed)
from src.cellarium import manifest                # noqa: E402

# argS / alaS / pheS are aminoacyl-tRNA synthetases; gltX is glutamyl-tRNA synthetase. The wild type is the
# depth-matched control and must run to the SAME generation count, or the comparison the paper makes is
# between a knockout at generation n and a control at generation m.
# variant_index is MANDATORY. gene_knockout.py computes geneIndex=(index-1)%(len(rna_data)+1), so a design
# without one falls back to runner._variant_index's content hash and silences an unrelated transcription
# unit while still carrying the knockout's label — the WELL-NOOP-1 shape. Verified against the fitted KB
# 2026-08-06: 644->TU0-13444 (argS alone), 2078->TU0-6441 (alaS alone), 2074->TU0-6409 (gltX alone).
#
# pheS is kept for comparability with the original campaign, but index 1340 is TU0-14257, which carries
# EIGHT genes: ihfA, infC, pheM, pheS, pheT, rplT, rpmI and thrS — two ribosomal proteins, a translation
# initiation factor and a second synthetase. Its phenotype cannot be attributed to pheS. pheS also sits on
# TU0-6626 (index 2111, four genes), so no single index silences it cleanly. This is the paper's own
# "specification error" category landing on its own experiment, and it is reported, not quietly dropped.
# scope.graded_ko_target resolves the cistron and transcription-unit count the variant needs; passing them is
# mandatory, and the first launch failed loudly because the condition carried the dose ("KO:argS@0.05") and the
# symbol no longer resolved. The guard refused all 16 rather than suppress one unit blindly, which is correct.
from src.cellarium import scope                                              # noqa: E402

_T = scope.graded_ko_target("argS")
if not _T.get("ok"):
    raise SystemExit(_T["why"])
LEVELS = {2: 0.05, 3: 0.10, 4: 0.25, 5: 0.50}

DESIGNS = [
    Design(perturbation="graded_gene_knockout", condition="KO:argS", generations=4,
           params={"variant_index": _T["variant_index_for_level"][lvl], "level": lvl})
    for lvl in sorted(LEVELS)
]

SEEDS = [0, 1, 2, 3]
GENERATIONS = 4
PARALLEL = 6

if __name__ == "__main__":
    print(f"depleting-allele campaign: {len(DESIGNS)} designs x {len(SEEDS)} seeds x {GENERATIONS} gens "
          f"= {len(DESIGNS) * len(SEEDS)} runs, {PARALLEL} at a time", flush=True)
    shard = manifest.campaign(DESIGNS, SEEDS, generations=GENERATIONS, parallel=PARALLEL)
    print(f"shard: {shard}", flush=True)
