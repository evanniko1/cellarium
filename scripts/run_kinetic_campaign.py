"""Execute the campaign the capability registry PROPOSES when it declines an isoacceptor question.

Asked which leucine isoacceptor de-charges first, the registry does not simply refuse. Under the default
steady-state model it says charging is solved as a 20-state ODE indexed by amino acid and broadcast across
the 86 isoacceptor columns, names `kinetic` as the model that does resolve them, gives the flag
(--kinetic-trna-charging), and states that because no corpus run used that model this is "a NEW RUN to
propose, not a query to re-issue". This script is that run.

Two arms, because one of them is the interesting one:
  * wildtype  — establishes that the within-family spread is reproducible dynamics across seeds and
                generations, not a single trajectory's wobble.
  * KO:argS   — the starvation arm. Selective charging (Elf et al. 2003) is a STARVATION phenomenon; a
                wild-type run is the wrong place to look for it. Knocking out the arginyl-tRNA synthetase
                is what should separate isoacceptors of one amino acid if the mechanism is real here.

Recording these into the manifest makes `capability.MODES_IN_CORPUS` stale: it is a hand-maintained tuple
currently reading ("steady_state",), and a registry that claims no kinetic run exists while kinetic rows
sit in the manifest is the silent-absence failure this repo has paid for before. Update it after this
campaign lands and re-score the discrimination test; do not leave the constant behind.

Run:  CELLARIUM_OUT=runs_kinetic_seeds python scripts/run_kinetic_campaign.py
"""
import os
import sys

if not os.environ.get("CELLARIUM_OUT"):
    sys.exit("refusing to run without CELLARIUM_OUT — OUT_ROOT is import-time, and a kinetic run sharing a "
             "directory with its steady-state twin is exactly the collision _dir_discriminator exists to stop")

# `python scripts/x.py` puts scripts/ on sys.path, not the repo root, so `src` is not importable
# the way it is under `python -c` from the checkout.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.cellarium.model import Design            # noqa: E402
from src.cellarium import manifest                # noqa: E402

DESIGNS = [
    Design(perturbation="wildtype", generations=3, elongation_model="kinetic"),
    Design(perturbation="gene_knockout", condition="KO:argS", generations=3, elongation_model="kinetic"),
]
SEEDS = [0, 1, 2, 3]
GENERATIONS = 3
PARALLEL = 6

if __name__ == "__main__":
    print(f"kinetic campaign: {len(DESIGNS)} designs x {len(SEEDS)} seeds x {GENERATIONS} gens "
          f"= {len(DESIGNS) * len(SEEDS)} runs, {PARALLEL} at a time", flush=True)
    shard = manifest.campaign(DESIGNS, SEEDS, generations=GENERATIONS, parallel=PARALLEL)
    print(f"shard: {shard}", flush=True)
