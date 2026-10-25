"""Ask the Socratic Council for simulation proposals that use the kinetic tRNA-charging model.

The campaign that will run them has cluster-scale compute, so the Council is asked for designs, not for a budget;
`council._to_design` still clamps seeds and generations to a runnable proposal and the campaign scales them up.
The Council is corpus-blind by construction; these questions state only what each elongation model represents
(capability registry), never a simulated result. Writes evals/results/council_kinetic_proposals.json.

    python scripts/run_council_kinetic.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from cellarium import council, credentials  # noqa: E402

CONTEXT = (" Two elongation models are available: steady_state (charging solved per amino acid; ppGpp is regulated) "
           "and kinetic (each tRNA isoacceptor charged separately, codons read explicitly; ppGpp is held "
           "constant). Phosphate or glucose removal cannot be represented in either.")
QUESTIONS = [
    "Under starvation for a single amino acid, do the tRNA isoacceptors of that amino acid lose their charge "
    "selectively, in the way Elf et al. (2003) reported, and does that selectivity follow the codon usage of the "
    "genes being translated?" + CONTEXT,
    "When one aminoacyl-tRNA synthetase is limiting, does a gene's codon composition decide how much its "
    "translation slows, so that genes rich in the affected codons lose expression first?" + CONTEXT,
    "How far do the steady-state and kinetic tRNA-charging models disagree about the growth defect of a "
    "knockout, and for which classes of gene (synthetases, amino-acid biosynthesis, ribosomal proteins, tRNA "
    "modification) is the disagreement largest?" + CONTEXT,
    "After a shift from a medium with amino acids to one without, how do per-isoacceptor charging and ribosome "
    "elongation recover, and does the recovery differ between amino acids whose synthesis pathways differ in "
    "length?" + CONTEXT,
]


def main() -> int:
    credentials.load_into_env()
    out_path = REPO / "evals" / "results" / "council_kinetic_proposals.json"
    results = []
    for q in QUESTIONS:
        t0 = time.time()
        try:
            h = council.deliberate(q, verbose=False)
            rec = {"question": q, "seconds": round(time.time() - t0), "hypothesis": h.model_dump(mode="json")}
        except Exception as e:  # noqa: BLE001 -- one failed deliberation must not lose the others
            rec = {"question": q, "seconds": round(time.time() - t0), "error": f"{type(e).__name__}: {e}"[:500]}
        results.append(rec)
        out_path.write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
        print(f"[{len(results)}/{len(QUESTIONS)}] {rec['seconds']} s  {'ERROR ' + rec['error'] if 'error' in rec else 'ok'}",
              flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
