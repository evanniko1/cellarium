"""Launch a first in-envelope campaign to seed the corpus (runs the public model; see docs/GENERATE.md).

Requires WCECOLI_DIR + the model env. Every design here is inside the validated envelope. KO panels (which
need per-gene variant indices from the model's sim_data) come once the index map is derived from the public
model — not from the private platform.
"""

from __future__ import annotations

import argparse

from . import manifest
from .model import Design


def default_designs() -> list[Design]:
    return [
        Design(perturbation="wildtype", condition="basal"),
        # validated dynamic shift: amino-acid downshift (minimal+AA -> minimal), a real stringent-response case
        Design(perturbation="timeline", timeline="0 minimal_plus_amino_acids, 1200 minimal"),
    ]


def main() -> None:
    ap = argparse.ArgumentParser(description="Seed the Cellarium corpus with an in-envelope campaign.")
    ap.add_argument("--seeds", type=int, default=4, help="number of stochastic replicate seeds")
    ap.add_argument("--generations", type=int, default=1)
    ap.add_argument("--parallel", type=int, default=1,
                    help="run this many sims concurrently (each loads ~1GB sim_data — size to host RAM)")
    args = ap.parse_args()

    shard = manifest.campaign(default_designs(), list(range(args.seeds)), args.generations, args.parallel)
    print(f"Wrote manifest shard: {shard}")


if __name__ == "__main__":
    main()
