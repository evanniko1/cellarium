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


# ---------------------------------------------------------------------------------------------------
# STAGE 2 -- switch plumbing. Four files, five edits, no behaviour change: the defaults reproduce
# today exactly. The point of the stage is that the choice becomes RECORDED (metadata.json) and
# VALIDATED (ValueError on anything unrecognised), never silently defaulted.
# ---------------------------------------------------------------------------------------------------

SIM = "wholecell/sim/simulation.py"
SB = "wholecell/utils/scriptBase.py"

MARKER_PLUMBING = "ROUTE1 step 2: tRNA charging resolution"

# E1 -- the two kwargs, placed next to the flag they qualify so they are read together.
SIM_KW_OLD = "\ttrna_charging = True,\n"
SIM_KW_NEW = (
    "\ttrna_charging = True,\n"
    "\t# ROUTE1 step 2: tRNA charging resolution, and how within-family demand is split.\n"
    "\t# Defaults reproduce the pre-ROUTE1 behaviour exactly: 'family' is 21-amino-acid\n"
    "\t# resolution, and the split is inert at that resolution. Validated in __init__ --\n"
    "\t# an unrecognised value raises rather than silently falling back.\n"
    "\ttrna_charging_resolution = 'family',\n"
    "\ttrna_demand_split = 'abundance',\n"
)

# E2 -- validation, immediately after the generic setattr loop that creates self._<kwarg>.
SIM_VAL_OLD = '\t\t\tsetattr(self, "_" + attrName, value)\n'
SIM_VAL_NEW = (
    '\t\t\tsetattr(self, "_" + attrName, value)\n'
    "\n"
    "\t\t# ROUTE1 step 2: validate the resolution/split strings HERE, at the single point where they\n"
    "\t\t# enter the simulation, rather than at each use. A typo must stop the run: silently falling\n"
    "\t\t# back to a default would produce a run whose shell history says one thing and whose\n"
    "\t\t# metadata says another, which is the exact failure this switch exists to prevent.\n"
    "\t\t_allowed_resolution = ('family', 'isoacceptor')\n"
    "\t\t_allowed_split = ('abundance', 'equal')\n"
    "\t\tif self._trna_charging_resolution not in _allowed_resolution:\n"
    "\t\t\traise ValueError('trna_charging_resolution must be one of {}, got {!r}'.format(\n"
    "\t\t\t\t_allowed_resolution, self._trna_charging_resolution))\n"
    "\t\tif self._trna_demand_split not in _allowed_split:\n"
    "\t\t\traise ValueError('trna_demand_split must be one of {}, got {!r}'.format(\n"
    "\t\t\t\t_allowed_split, self._trna_demand_split))\n"
    "\t\t# Isoacceptor resolution only means anything inside the steady-state charging ODE. Forcing\n"
    "\t\t# it back rather than ignoring it keeps metadata honest about what actually ran -- the same\n"
    "\t\t# reason the elongation flags are resolved rather than left independent just below.\n"
    "\t\tif not self._trna_charging and self._trna_charging_resolution != 'family':\n"
    "\t\t\tprint('Note: --trna-charging-resolution is only meaningful with --trna-charging;'\n"
    "\t\t\t\t' forcing it to family.')\n"
    "\t\t\tself._trna_charging_resolution = 'family'\n"
)

# E3 -- METADATA_KEYS and SIM_KEYS. BOTH lists carry "'trna_charging'," on its own line, and both
# need the two new names: METADATA_KEYS is what puts them in metadata.json (the whole point of the
# switch being recorded), and SIM_KEYS is what passes them through -- data.select_keys does
# mapping[key] with NO default, so omitting them there KeyErrors every sim invocation.
SB_KEYS_OLD = "\t'trna_charging',\n"
SB_KEYS_NEW = ("\t'trna_charging',\n"
               "\t# ROUTE1 step 2: tRNA charging resolution, recorded per run in metadata.json.\n"
               "\t'trna_charging_resolution',\n"
               "\t'trna_demand_split',\n")

# E4 -- the CLI options. Deliberately plain string parameters validated in simulation.py rather than
# argparse choices=, so there is ONE enforcement point and one error message.
SB_OPT_OLD = (
    "\t\tadd_bool_option('kinetic_trna_charging', 'kinetic_trna_charging',\n"
)
SB_OPT_NEW = (
    "\t\tself.define_option(parser, 'trna_charging_resolution', str,\n"
    "\t\t\tdefault='family',\n"
    "\t\t\thelp=\"resolution of the tRNA charging ODE: 'family' (21 amino acids, the default and\"\n"
    "\t\t\t\t\" the pre-ROUTE1 behaviour) or 'isoacceptor' (85 charging-masked tRNA species of 86;\"\n"
    "\t\t\t\t\" selC excluded). Only meaningful with --trna-charging.\")\n"
    "\t\tself.define_option(parser, 'trna_demand_split', str,\n"
    "\t\t\tdefault='abundance',\n"
    "\t\t\thelp=\"how per-amino-acid elongation demand is divided among a family's isoacceptors at\"\n"
    "\t\t\t\t\" isoacceptor resolution: 'abundance' (default; an isoacceptor's share of demand is\"\n"
    "\t\t\t\t\" its share of the family tRNA pool) or 'equal'. NOT determined by the knowledge\"\n"
    "\t\t\t\t\" base -- TrnaCharging/reading_events sums to exactly 0.0 on every run on disk -- so\"\n"
    "\t\t\t\t\" it is an explicit modelling choice. Measured resolution ratio r = D_86/D_21:\"\n"
    "\t\t\t\t\" abundance 1.2713 (operons on) / 1.2423 (off), equal 1.3283 / 1.3195; gap ~4.5%.\"\n"
    "\t\t\t\t\" Inert at family resolution.\")\n"
    "\t\tadd_bool_option('kinetic_trna_charging', 'kinetic_trna_charging',\n"
)

# E5 -- read them in the process, alongside the existing flag reads. getattr-with-default so a
# sim_data/Simulation built by older code still works.
PE_READ_OLD = "\t\tself.coarse_kinetic_elongation = coarse_kinetic_elongation\n"
PE_READ_NEW = (
    "\t\tself.coarse_kinetic_elongation = coarse_kinetic_elongation\n"
    "\t\t# ROUTE1 step 2: tRNA charging resolution and the within-family demand split. Defaults\n"
    "\t\t# match the pre-ROUTE1 behaviour, so a Simulation built by older code is unaffected.\n"
    "\t\tself.trna_charging_resolution = getattr(sim, '_trna_charging_resolution', 'family')\n"
    "\t\tself.trna_demand_split = getattr(sim, '_trna_demand_split', 'abundance')\n"
)

# E6/E7 -- the FIREWORKS FIRETASKS. Fireworks validates kwargs against a per-task allow-list and
# RAISES RuntimeError on anything unlisted, so a name that reaches SimulationTask without being
# declared there breaks EVERY simulation, not only isoacceptor ones. This was missed by the spec and
# caught only by the smoke test: static checks, ruff, the applier and a byte-identical round trip all
# passed while every variant failed. Both the allow-list and the defaults wiring are needed, in BOTH
# the mother and daughter tasks.
FW_SIM = "wholecell/fireworks/firetasks/simulation.py"
FW_DAU = "wholecell/fireworks/firetasks/simulationDaughter.py"

FW_LIST_OLD = '\t\t"trna_charging",\n'
FW_LIST_NEW = ('\t\t"trna_charging",\n'
               '\t\t# ROUTE1 step 2: tRNA charging resolution. Fireworks raises on unlisted kwargs.\n'
               '\t\t"trna_charging_resolution",\n'
               '\t\t"trna_demand_split",\n')

FW_DEF_OLD = '\t\toptions["trna_charging"] = self._get_default("trna_charging")\n'
FW_DEF_NEW = ('\t\toptions["trna_charging"] = self._get_default("trna_charging")\n'
              '\t\toptions["trna_charging_resolution"] = self._get_default("trna_charging_resolution")\n'
              '\t\toptions["trna_demand_split"] = self._get_default("trna_demand_split")\n')

PLUMBING = (
    (FW_SIM, FW_LIST_OLD, FW_LIST_NEW, 1, "firetasks/simulation.py: allow-list"),
    (FW_SIM, FW_DEF_OLD, FW_DEF_NEW, 1, "firetasks/simulation.py: defaults"),
    (FW_DAU, FW_LIST_OLD, FW_LIST_NEW, 1, "firetasks/simulationDaughter.py: allow-list"),
    (FW_DAU, FW_DEF_OLD, FW_DEF_NEW, 1, "firetasks/simulationDaughter.py: defaults"),
    (SIM, SIM_KW_OLD, SIM_KW_NEW, 1, "simulation.py: resolution/split kwargs"),
    (SIM, SIM_VAL_OLD, SIM_VAL_NEW, 1, "simulation.py: validation + family forcing"),
    (SB, SB_KEYS_OLD, SB_KEYS_NEW, 2, "scriptBase.py: METADATA_KEYS + SIM_KEYS"),
    (SB, SB_OPT_OLD, SB_OPT_NEW, 1, "scriptBase.py: CLI options"),
    (REL, PE_READ_OLD, PE_READ_NEW, 1, "polypeptide_elongation.py: read the two switches"),
)


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
    st = {"present": True, "resolution_block": MARKER_BLOCK in txt}
    # Stage 2 reports per FILE, not as one boolean, so a half-applied plumbing pass (say scriptBase
    # edited but simulation.py not) reads as partial rather than done.
    for rel in (SIM, SB, REL, FW_SIM, FW_DAU):
        p = os.path.join(wcecoli, rel)
        # Keyed by the FULL relative path, not the basename: wholecell/sim/simulation.py and
        # wholecell/fireworks/firetasks/simulation.py share a basename, and keying on it silently
        # collapsed the two into one entry — so a half-applied pair could report as fully applied.
        st["plumbing_" + rel.replace("\\", "/")] = (
            os.path.isfile(p) and MARKER_PLUMBING in _read(p)[0])
    return st


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
    wrote = []
    if not st["resolution_block"]:
        txt = txt.replace(anchor, _norm(BLOCK, nl).lstrip(nl) + anchor, 1)
        _write(path, txt)
        wrote.append(f"{REL}: ROUTE1 resolution/demand-split comment block above get_charging_params")

    # STAGE 2 -- switch plumbing. Each edit states how many occurrences it expects and refuses to
    # proceed on any other count, so a file that has drifted fails loudly instead of being patched
    # blind or silently skipped.
    for rel, old, new, n_expected, label in PLUMBING:
        p = os.path.join(wcecoli, rel)
        if not os.path.isfile(p):
            return {"complete": False, "wrote": wrote, "status": status(wcecoli),
                    "why": f"{rel} not found under {wcecoli}"}
        t, n2 = _read(p)
        # Idempotence is judged per EDIT by content, never per file by marker: two edits land in
        # simulation.py, and a file-level marker check would skip the second one the moment the
        # first applied. That bug is why this comment exists.
        o, w = _norm(old, n2), _norm(new, n2)
        if w in t:
            continue
        if t.count(o) != n_expected:
            return {"complete": False, "wrote": wrote, "status": status(wcecoli),
                    "why": f"{rel}: expected exactly {n_expected} occurrence(s) of "
                           f"{old.strip()[:60]!r}, found {t.count(o)} — refusing to guess"}
        _write(p, t.replace(o, w, n_expected))
        wrote.append(label)

    st2 = status(wcecoli)
    return {"complete": all(v for k, v in st2.items() if k != "present"), "status": st2, "wrote": wrote}


def revert(wcecoli: str) -> dict:
    """Exact inverse of run(), so a CONTROL image can be built from the same tree.

    Callers must re-apply and VERIFY; leaving the tree reverted loses the record of why the split is
    a choice rather than a constant. See build_route1_control_image.py for the atomic pattern.
    """
    path = os.path.join(wcecoli, REL)
    if not os.path.isfile(path):
        return {"complete": False, "wrote": [], "why": f"{REL} not found under {wcecoli}"}
    wrote = []

    # STAGE 2 first, then stage 1 -- the reverse of the order run() applies them. Stage 1 inserts a
    # block above get_charging_params and stage 2 edits elsewhere in the same file, so they do not
    # overlap textually; the ordering is for symmetry rather than necessity, and reverting in apply
    # order would be a latent hazard the moment a later stage anchors inside an earlier one.
    for rel, old, new, n_expected, label in reversed(PLUMBING):
        p = os.path.join(wcecoli, rel)
        if not os.path.isfile(p):
            return {"complete": False, "wrote": wrote, "why": f"{rel} not found under {wcecoli}"}
        t, n2 = _read(p)
        o, w = _norm(old, n2), _norm(new, n2)
        if w not in t:
            continue  # this edit is already reverted
        if t.count(w) != n_expected:
            return {"complete": False, "wrote": wrote,
                    "why": f"{rel}: expected exactly {n_expected} occurrence(s) of the applied form "
                           f"of {label!r}, found {t.count(w)} — refusing to guess"}
        _write(p, t.replace(w, o, n_expected))
        wrote.append(f"{label} reverted")

    txt, nl = _read(path)
    block = _norm(BLOCK, nl).lstrip(nl)
    if block in txt:
        if txt.count(block) != 1:
            return {"complete": False, "wrote": wrote,
                    "why": f"expected exactly 1 resolution block, found {txt.count(block)}"}
        _write(path, txt.replace(block, "", 1))
        wrote.append(f"{REL}: resolution block reverted")

    st = status(wcecoli)
    reverted = not any(v for k, v in st.items() if k != "present")
    return {"complete": reverted, "wrote": wrote, "status": st,
            "why": "" if reverted else "revert did not clear every marker"}


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
