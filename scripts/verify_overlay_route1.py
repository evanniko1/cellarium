"""Assert that the five de-ROUTE1'd port files are clean AND still carry the kinetic model.

WHY THIS EXISTS. `scripts/build_model_overlay.py` gate 1 refuses any file containing the marker
`ROUTE1`, which is a one-sided check: a file that passes it might have had the isoacceptor work
removed correctly, or might have had the KINETIC ELONGATION MODEL removed along with it. Those two
outcomes are indistinguishable to a marker count, and the second one is silent — `--kinetic-trna-
charging` would still parse, `src/cellarium/capability.py` would still advertise mode "kinetic", and
the run would quietly select `SteadyStateElongationModel`. That is the failure this script exists to
make loud.

It checks BOTH halves, against `model_overlay/cleaned/` by default or against any checkout:

    python scripts/verify_overlay_route1.py                       # the shipped cleaned sources
    python scripts/verify_overlay_route1.py --tree C:/tmp/clone   # a checkout the overlay was applied to

Exit 0 only if every file is ROUTE1-free, parses, and still defines the kinetic model.
"""

from __future__ import annotations

import argparse
import ast
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CLEANED = os.path.join(REPO, "model_overlay", "cleaned")

# The markers the extension repo's ROUTE1 recipes left behind, verbatim from the removal brief.
MARKERS = [
    "ROUTE1", "ROUTE1-21", "ROUTE1 step 2", "ROUTE1 -- tRNA charging resolution",
    "trna_charging_resolution", "trna_demand_split", "dcdt_jit_iso", "clamp_charging_shared",
]

# Identifiers that must not survive AS WORDS. Substring matching is wrong here: `n_trna_per_aa` is a
# substring of upstream's own `fraction_trna_per_aa` (polypeptide_elongation.py, SteadyState request),
# so a naive `in` test reports a false positive on untouched upstream code.
WORD_MARKERS = [
    "T2A", "A2T", "KMtf_trna", "n_trna_per_aa", "trna_charging_mask", "trna_resolution",
    "trna_resolution_iso", "demand_split", "equal_split", "trna_to_aa_index", "fraction_charged_iso",
    "fraction_trna_charged_iso", "return_iso", "uncharged_trna_conc_iso", "charged_trna_conc_iso",
]

# What must SURVIVE, per file. This is the half a marker count cannot see.
KINETIC = {
    "models/ecoli/processes/polypeptide_elongation.py": [
        "class KineticTrnaChargingModel(",
        "class CoarseKineticTrnaChargingModel(",
        "kinetic_trna_charging",
        "coarse_kinetic_elongation",
    ],
    "wholecell/sim/simulation.py": [
        "def resolve_elongation_flags(",
        "'KineticTrnaChargingModel'",
        "'CoarseKineticTrnaChargingModel'",
        "kinetic_trna_charging",
        "coarse_kinetic_elongation",
    ],
    "wholecell/utils/scriptBase.py": ["kinetic_trna_charging", "coarse_kinetic_elongation"],
    "wholecell/fireworks/firetasks/simulation.py": [
        "kinetic_trna_charging", "coarse_kinetic_elongation"],
    "wholecell/fireworks/firetasks/simulationDaughter.py": [
        "kinetic_trna_charging", "coarse_kinetic_elongation"],
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tree", default=CLEANED,
                    help="tree to check (default: model_overlay/cleaned)")
    a = ap.parse_args(argv)

    if not os.path.isdir(a.tree):
        print("ERROR: --tree %r is not a directory" % a.tree, file=sys.stderr)
        return 2

    failures = []
    for rel, required in KINETIC.items():
        path = os.path.join(a.tree, rel.replace("/", os.sep))
        if not os.path.isfile(path):
            failures.append("%s: NOT PRESENT in %s" % (rel, a.tree))
            print("%-56s MISSING" % rel)
            continue
        text = io.open(path, encoding="utf-8").read()

        surviving = [m for m in MARKERS if m in text]
        surviving += [w for w in WORD_MARKERS if re.search(r"\b%s\b" % re.escape(w), text)]
        if surviving:
            failures.append("%s: surviving ROUTE1 markers %s" % (rel, sorted(set(surviving))))

        try:
            ast.parse(text)
            parses = True
        except SyntaxError as e:
            parses = False
            failures.append("%s: does not parse -- %s" % (rel, e))

        missing = [k for k in required if k not in text]
        if missing:
            failures.append("%s: the KINETIC MODEL was removed too -- missing %s" % (rel, missing))

        print("%-56s ROUTE1 %d  %s  kinetic %s"
              % (rel, text.count("ROUTE1"), "parses" if parses else "SYNTAX ERROR",
                 "present" if not missing else "MISSING %s" % missing))

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print("  " + f)
        return 1
    print("\nall %d files: ROUTE1-free, parse, kinetic model intact" % len(KINETIC))
    return 0


if __name__ == "__main__":
    sys.exit(main())
