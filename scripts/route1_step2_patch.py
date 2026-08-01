"""ROUTE1 step 2 — isoacceptor-resolution tRNA charging. Applied incrementally; this is the recipe.

Step 2 resolves the charging ODE to 85 tRNA species (86 minus selC) while the ppGpp arm STAYS at
21-amino-acid resolution. Unlike step 1 it is not one expression, so it lands in stages and this
module grows with it. Every stage is marker-guarded and idempotent on the same terms as
`route1_occupancy_patch.py`, so re-applying a fully-applied tree is a no-op.

DESIGN DECISIONS ALREADY FIXED (do not re-open here; see docs/ROUTE1_VERIFICATION.md for evidence):

  * ppGpp arm stays at 21. `ppgpp_metabolite_changes` keeps its `aa_from_trna`-aggregated interface,
    so `KD_RelA` is NOT refitted.
  * SHARED SYNTHETASE PER FAMILY. All isoacceptors of an amino acid compete for one synthetase pool,
    so the 85-resolution denominator carries a SUM over the family. This is the biology (one
    aminoacyl-tRNA synthetase per amino acid), and it is also what makes the reduction exact: with
    KMtf broadcast per family the family-aggregated 85-form charging flux equals the 21-form for
    ARBITRARY within-family splits, worst relative error 6.9e-16 / 8.4e-16 over 20 families x 200
    Dirichlet splits x 121 real timesteps.
  * ABUNDANCE-WEIGHTED within-family demand split, exposed as a switch and recorded in metadata,
    never as a buried constant.
  * NO PIN. The A-site / v_rib arm stays at 21 by aggregating inside the RHS, making r == 1 by
    construction.

STAGES APPLIED SO FAR:

  1. PRE-WORK — the ROUTE1 resolution comment block above `get_charging_params`. Records the two
     split options with their MEASURED r values, states that r is a state function rather than a
     constant, explains why no pin is required, and carries the provenance caveat that every
     charging run on disk is generation 0 only. No behaviour change.

STAGES NOT YET APPLIED: switch plumbing (simulation.py defaults + scriptBase CLI/METADATA_KEYS/
SIM_KEYS), the params-dict additions (T2A/A2T/KMtf_trna/trna_charging_mask), the 85-resolution RHS
with the aggregate-then-rescale clamp, and the listener widening.

    python scripts/route1_step2_patch.py --wcecoli C:/dev/wcEcoli [--check] [--revert]
"""

from __future__ import annotations

import argparse
import io
import os
import sys

REL = "models/ecoli/processes/polypeptide_elongation.py"

# Marker for stage 1. Distinct from ROUTE1-21 so the two stages report independently.
MARKER_BLOCK = "ROUTE1 -- tRNA charging resolution, and the measured cost of the within-family demand split"

ANCHOR = "def get_charging_params(\n"

BLOCK = '''

# =====================================================================================================
# ROUTE1 -- tRNA charging resolution, and the measured cost of the within-family demand split
# =====================================================================================================
#
# The charging ODE can run at AMINO-ACID resolution (21 families, the default and the only behaviour
# before ROUTE1) or at ISOACCEPTOR resolution (85 charging-masked tRNA species of 86; selC excluded).
# At isoacceptor resolution the per-amino-acid elongation demand f_a has to be divided among a
# family's isoacceptors, and that division is NOT determined by anything in the knowledge base:
# TrnaCharging/reading_events, which would carry measured codon-to-tRNA demand, sums to exactly 0.0
# on every run on disk because the model that populates it did not run in those arms.
#
# So it is an explicit modelling choice, exposed as --trna-demand-split and RECORDED in metadata.json
# rather than buried here. The two options and their MEASURED consequence for the resolution ratio
# r = D_86/D_21, quoted only to the precision the measurements support:
#
#     split        operons ON        operons OFF      gap
#     abundance    1.2713 +/- 2e-4   1.2423           4.48-4.49%
#     equal        1.3283 +/- 2e-4   1.3195
#
# 'abundance' is the default: in the absence of codon-resolved demand data, an isoacceptor's share of
# its family's demand is taken as its share of the family's tRNA pool.
#
# r IS A STATE FUNCTION, NOT A CONSTANT. In closed form
#
#     r = 1 + [ sum_a (n_a - 1) * f_a * krta / c_a ] / D_21
#
# whose measured span across all 34 simOut directories on disk is 1.1956..1.2713 under the abundance
# split. It also drifts within a single generation. A previously circulated high end of 1.371027 is
# NOT reproducible under any split, convention or timestep -- nothing measured exceeds 1.3283, and
# that is the equal split -- and must not be carried forward.
#
# WHY NONE OF THIS REQUIRES A PIN. The A-site / v_rib arm stays at 21-amino-acid resolution: u_i and
# c_i are aggregated back to families INSIDE the right-hand side before the ribosome denominator is
# formed. That makes r == 1 by construction, so there is nothing to re-pin and no rate constant
# acquires a second meaning. Letting the ribosome denominator follow charging to 86 would instead
# inflate it by D_86 - D_21 and drop v_rib by ~21% -- and about two thirds of THAT is spurious, since
# the 86 tRNA genes carry only 41 distinct (family, anticodon) pairs and anticodon-identical
# duplicates are not separate A-site queues (measured: gene resolution -21.23%, anticodon resolution
# -7.36%).
#
# EVIDENCE. docs/ROUTE1_VERIFICATION.md in the Cellarium repo records every check with its sample
# size and tolerance. The load-bearing one for the family/isoacceptor equivalence: with KMtf
# broadcast per family the shared-synthetase denominator collapses identically, so the
# family-aggregated 86-form charging flux equals the 21-form for ARBITRARY within-family splits, not
# merely at zero spread -- worst relative error 6.9e-16 and 8.4e-16 over 20 families x 200 random
# Dirichlet splits x 121 real timesteps, in two independent runs.
#
# CAVEAT ON PROVENANCE. Only 3 of the 8 ParCa trees on disk have charging-enabled output, and every
# charging run is 121 rows / 120 s of GENERATION 0 ONLY. Full-generation drift in r is UNMEASURED.
'''


def _read(path: str) -> tuple[str, str]:
    with io.open(path, encoding="utf-8", newline="") as fh:
        txt = fh.read()
    return txt, ("\r\n" if "\r\n" in txt else "\n")


def _write(path: str, txt: str) -> None:
    with io.open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(txt)


def _norm(s: str, nl: str) -> str:
    return s.replace("\n", nl) if nl != "\n" else s


def status(wcecoli: str) -> dict:
    path = os.path.join(wcecoli, REL)
    if not os.path.isfile(path):
        return {"present": False, "resolution_block": False}
    txt, _ = _read(path)
    return {"present": True, "resolution_block": MARKER_BLOCK in txt}


def run(wcecoli: str, check: bool = False) -> dict:
    st = status(wcecoli)
    if not st["present"]:
        return {"complete": False, "wrote": [], "why": f"{REL} not found under {wcecoli}"}
    if all(st.values()):
        return {"complete": True, "wrote": [], "status": st, "why": "already applied"}
    if check:
        return {"complete": False, "wrote": [], "status": st, "why": "not applied; run without --check"}

    path = os.path.join(wcecoli, REL)
    txt, nl = _read(path)
    anchor = _norm(ANCHOR, nl)
    if txt.count(anchor) != 1:
        return {"complete": False, "wrote": [], "status": st,
                "why": f"expected exactly 1 {ANCHOR.strip()!r} in {REL}, found {txt.count(anchor)} "
                       f"— refusing to guess placement"}
    txt = txt.replace(anchor, _norm(BLOCK, nl).lstrip(nl) + anchor, 1)
    _write(path, txt)
    st2 = status(wcecoli)
    return {"complete": all(st2.values()), "status": st2,
            "wrote": [f"{REL}: ROUTE1 resolution/demand-split comment block above get_charging_params"]}


def revert(wcecoli: str) -> dict:
    """Exact inverse of run(), so a CONTROL image can be built from the same tree.

    Callers must re-apply and VERIFY; leaving the tree reverted loses the record of why the split is
    a choice rather than a constant. See build_route1_control_image.py for the atomic pattern.
    """
    path = os.path.join(wcecoli, REL)
    if not os.path.isfile(path):
        return {"complete": False, "wrote": [], "why": f"{REL} not found under {wcecoli}"}
    txt, nl = _read(path)
    block = _norm(BLOCK, nl).lstrip(nl)
    if block not in txt:
        return {"complete": True, "wrote": [], "status": status(wcecoli), "why": "already reverted"}
    if txt.count(block) != 1:
        return {"complete": False, "wrote": [], "why": f"expected exactly 1 block, found {txt.count(block)}"}
    _write(path, txt.replace(block, "", 1))
    st = status(wcecoli)
    return {"complete": not st["resolution_block"], "wrote": [f"{REL}: resolution block reverted"],
            "status": st}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--wcecoli", default=os.environ.get("WCECOLI", "C:/dev/wcEcoli"))
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args(argv)
    r = revert(a.wcecoli) if a.revert else run(a.wcecoli, check=a.check)
    for w in r.get("wrote", []):
        print(f"  {w}")
    if r.get("why"):
        print(f"  {r['why']}")
    print(f"status: {r.get('status')}")
    print("COMPLETE" if r["complete"] else "NOT COMPLETE")
    return 0 if r["complete"] else 1


if __name__ == "__main__":
    sys.exit(main())
