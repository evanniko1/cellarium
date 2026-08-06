"""Add seeds to the paper's Section 3 synthetase campaign.

Section 3 currently rests on ONE seed per design, which the paper itself flags as a caution: RelA is a
low-copy protein whose wild-type trace moves between 31 and 97 copies across generations, so a
depth-matched comparison built on n=1 is doing real work with a noisy control. These runs give every
design four seeds at the same generation depth, so the depth-matched claim can be stated with a spread
rather than a single trajectory.

Seed 0 for each design already exists in the scratch roots (runs_aars_*) but was never recorded into the
manifest. This campaign runs seeds 0-3 into one root and records all of them, so the corpus holds the
whole matrix rather than three quarters of it.

Run:  CELLARIUM_OUT=runs_seed_aars python scripts/run_paper_seeds.py
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
KO_INDEX = {"argS": 644, "alaS": 2078, "gltX": 2074, "pheS": 1340}

DESIGNS = [
    Design(perturbation="gene_knockout", condition=f"KO:{g}", generations=3,
           params={"variant_index": i}) for g, i in KO_INDEX.items()
]
# The wild-type arm already ran and is banked in the manifest at four seeds; it is not repeated here.
SEEDS = [0, 1, 2, 3]
GENERATIONS = 3
PARALLEL = 6          # the measured I/O ceiling on this host; each job also loads ~1GB of sim_data

if __name__ == "__main__":
    print(f"synthetase seed campaign: {len(DESIGNS)} designs x {len(SEEDS)} seeds x {GENERATIONS} gens "
          f"= {len(DESIGNS) * len(SEEDS)} runs, {PARALLEL} at a time", flush=True)
    shard = manifest.campaign(DESIGNS, SEEDS, generations=GENERATIONS, parallel=PARALLEL)
    print(f"shard: {shard}", flush=True)
