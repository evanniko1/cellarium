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

  2. SWITCH PLUMBING — simulation.py kwargs + validation, scriptBase CLI/METADATA_KEYS/SIM_KEYS,
     both Fireworks firetask allow-lists, and the two flag reads in the Process. No behaviour
     change: the defaults reproduce today exactly, but the choice becomes recorded and validated.
  3. PARAMS DICT — T2A/A2T/KMtf_trna/n_trna_per_aa/trna_charging_mask, additive only.
  4. THE 85-RESOLUTION RHS — `dcdt_jit_iso` and `clamp_charging_shared`, plus the resolution branch
     in `calculate_trna_charging`. `dcdt_jit` is NOT touched, so the family path is bit-identical by
     inspection rather than by argument. Charging runs at 85 with one shared synthetase denominator
     per family; the clamp is aggregate-then-rescale; u_i and c_i are aggregated back to families
     inside the RHS so v_rib stays at 21 and r == 1 by construction.

  5. WIDEN THE INTERFACE -- calculate_trna_charging accepts genuine 85-vectors read from the
     per-species BulkMolecules views, returns an opt-in per-species charged fraction, and the
     request write-back and the GrowthLimits/fraction_trna_charged column consume it instead of
     broadcasting the family value. No listener column changes SHAPE; one changes MEANING. The ppGpp
     arm and every 21-wide column keep receiving aa_from_trna-aggregated pools. MEASURED before the
     stage was written: at the fixed default split ('abundance') the ODE's steady state is exactly
     proportional, so real input spread of 3.3e-4..9.5e-3 contracts to 1.1e-16..3.1e-8 and the
     widening is a numerical no-op; at 'equal' the same widening produces up to 7.2e-2 of genuine
     within-family spread against exactly 0.0 with the uniform expansion. See the stage banner.

  6. DOCUMENT THE DEGENERACY AT THE POINT OF CHOICE -- the --trna-demand-split help text and the
     ROUTE1 comment block both state plainly that at the DEFAULT split the within-family charged
     fraction is uniform BY CONSTRUCTION (worst measured 2.79e-7 at 40 s, 2.16e-7 at 20 s, over 17
     multi-member families) and that 'equal' is the configuration in which spread develops (worst
     6.18e-2 at 40 s, 6.63e-2 at 20 s). The magnitude replicates across the two runs; the per-family
     ranking does NOT, so no family order is recorded. `abundance` stays the default -- conservative,
     and it reproduces the 21-resolution answer -- and the degeneracy is reported as a FINDING rather
     than hidden behind it. No behaviour change: comments and help text only.

  7. CORRECT THE PROVENANCE CAVEAT -- stages 1 and 6 both ended the ROUTE1 block on "every charging
     run is 121 rows / 120 s of GENERATION 0 ONLY". That sentence is now FALSE: 3 arms x 3 seeds x
     3 FULL generations to natural division (27 cells, 2499-3310 timesteps each, all 9 chains exit 0,
     zero NaN, every cell divided) were run and measured. The stage replaces it with the matrix
     result AND with what the matrix did not cover -- r-drift across generations was still not
     measured, and the matrix is --trna-charging only. MEASURED, per-timestep medians pooled over
     seeds: family control exactly 0.000e+00 at all ~24800 timesteps; abundance 4.7e-8 / 1.8e-7 /
     2.7e-7 by generation with 0 of ~25500 timesteps above 1e-2; equal 5.2e-2 / 5.7e-2 / 6.6e-2 with
     ALL timesteps above 1e-2. Also records that the between-arm growth differences are CHAOS:
     abundance is bit-equal to the family control for two timesteps and departs at 2e-10 before
     amplifying to ~1e-1. No behaviour change: comments only.

STAGES NOT YET APPLIED: none.

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
MARKER_PARAMS = "ROUTE1 step 2: isoacceptor bookkeeping"
MARKER_FORWARD = "ROUTE1 step 2: forward the resolution/split switches"

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

# E8 -- get_charging_params signature.
GCP_SIG_OLD = (
    "def get_charging_params(\n"
    "\t\tsim_data,\n"
    "\t\taa_removed_from_charging: Optional[Set[str]] = None,\n"
    "\t\tvariable_elongation: bool = False,\n"
    "\t\t) -> Dict[str, Any]:\n"
)
GCP_SIG_NEW = (
    "def get_charging_params(\n"
    "\t\tsim_data,\n"
    "\t\taa_removed_from_charging: Optional[Set[str]] = None,\n"
    "\t\tvariable_elongation: bool = False,\n"
    "\t\ttrna_charging_resolution: str = 'family',\n"
    "\t\ttrna_demand_split: str = 'abundance',\n"
    "\t\t) -> Dict[str, Any]:\n"
)

# E9 -- the isoacceptor bookkeeping, built once from sim_data.
GCP_BODY_OLD = (
    "\telongation_max = (constants.ribosome_elongation_rate_max\n"
    "\t\tif variable_elongation else constants.ribosome_elongation_rate_basal)\n"
)
GCP_BODY_NEW = (
    "\telongation_max = (constants.ribosome_elongation_rate_max\n"
    "\t\tif variable_elongation else constants.ribosome_elongation_rate_basal)\n"
    "\n"
    "\t# ROUTE1 step 2: isoacceptor bookkeeping. Built HERE rather than in the right-hand side\n"
    "\t# because it is pure sim_data derivation that never changes during a simulation, and because\n"
    "\t# the RHS is @njit, where boolean fancy-indexing and matrix construction are unsupported.\n"
    "\t#\n"
    "\t# aa_from_trna is the authoritative (21, 86) 0/1 map, built in Transcription._build_charged_trna.\n"
    "\t# Do NOT re-derive it from tRNA name prefixes: that route silently yields ILE=4/MET=6 instead of\n"
    "\t# ILE=5/MET=6 -- still summing to 86, so it looks correct -- because RNA0-305[c] maps to ILE\n"
    "\t# rather than the natural guess of MET. Restricting rows to the charging mask leaves 85 species:\n"
    "\t# 86 tRNA genes minus selC, whose amino acid (SEC) is removed from charging.\n"
    "\taa_from_trna = transcription.aa_from_trna\n"
    "\ttrna_charging_mask = aa_from_trna[aa_charging_mask].sum(0) > 0\n"
    "\tif int(trna_charging_mask.sum()) != 85:\n"
    "\t\traise ValueError('expected exactly 85 charging-masked tRNA species (86 minus selC), got '\n"
    "\t\t\t'{}'.format(int(trna_charging_mask.sum())))\n"
    "\t# C-contiguous float64: dcdt_jit is @njit and numba's np.dot requires both.\n"
    "\tT2A = np.ascontiguousarray(\n"
    "\t\taa_from_trna[np.ix_(aa_charging_mask, trna_charging_mask)], dtype=np.float64)\n"
    "\tA2T = np.ascontiguousarray(T2A.T)\n"
    "\t# KMtf is BROADCAST per family, never re-fitted. That broadcast is exactly what makes the\n"
    "\t# shared-synthetase denominator collapse to the 21-form for ARBITRARY within-family splits\n"
    "\t# (worst relative error 6.9e-16 over 20 families x 200 Dirichlet splits x 121 timesteps).\n"
    "\tKMtf_trna = A2T @ transcription.trna_kms.asNumber(CONC_UNITS)[aa_charging_mask]\n"
)

# E10 -- the returned dict. Additive only: no existing key changes, so 'family' resolution is
# bit-identical to today and every existing consumer is untouched.
GCP_RET_OLD = (
    "\t\tunit_conversion=metabolism.get_amino_acid_conc_conversion(CONC_UNITS),\n"
    "\t\t)\n"
)
GCP_RET_NEW = (
    "\t\tunit_conversion=metabolism.get_amino_acid_conc_conversion(CONC_UNITS),\n"
    "\t\t# ROUTE1 step 2 -- additive. Present at BOTH resolutions so consumers need no branch to\n"
    "\t\t# read them; they are simply unused when trna_resolution == 'family'.\n"
    "\t\ttrna_resolution=trna_charging_resolution,\n"
    "\t\tdemand_split=trna_demand_split,\n"
    "\t\ttrna_charging_mask=trna_charging_mask,\n"
    "\t\tT2A=T2A,\n"
    "\t\tA2T=A2T,\n"
    "\t\tn_trna_per_aa=T2A.sum(1),\n"
    "\t\tKMtf_trna=KMtf_trna,\n"
    "\t\t)\n"
)

# E11 -- FORWARD the switches into get_charging_params. Without this the whole switch is inert: it is
# validated, recorded in metadata.json, and read onto the Process, but never reaches the function that
# acts on it, so params["trna_resolution"] is "family" in every simulation regardless of the flag.
# The smoke test could not catch it — that checks the choice is RECORDED, not that it has EFFECT.
GCP_CALL_OLD = (
    "\t\tself.charging_params = get_charging_params(sim_data,\n"
    "\t\t\tvariable_elongation=self.process.variable_elongation)\n"
)
GCP_CALL_NEW = (
    "\t\t# ROUTE1 step 2: forward the resolution/split switches. Read onto the Process in\n"
    "\t\t# PolypeptideElongation.initialize; getattr-defaulted so an older Process still works.\n"
    "\t\tself.charging_params = get_charging_params(sim_data,\n"
    "\t\t\tvariable_elongation=self.process.variable_elongation,\n"
    "\t\t\ttrna_charging_resolution=getattr(\n"
    "\t\t\t\tself.process, 'trna_charging_resolution', 'family'),\n"
    "\t\t\ttrna_demand_split=getattr(self.process, 'trna_demand_split', 'abundance'))\n"
)

PLUMBING = (
    (FW_SIM, FW_LIST_OLD, FW_LIST_NEW, 1, "firetasks/simulation.py: allow-list"),
    (REL, GCP_CALL_OLD, GCP_CALL_NEW, 1, "get_charging_params call: forward the switches"),
    (REL, GCP_SIG_OLD, GCP_SIG_NEW, 1, "get_charging_params: signature"),
    (REL, GCP_BODY_OLD, GCP_BODY_NEW, 1, "get_charging_params: isoacceptor bookkeeping"),
    (REL, GCP_RET_OLD, GCP_RET_NEW, 1, "get_charging_params: returned dict"),
    (FW_SIM, FW_DEF_OLD, FW_DEF_NEW, 1, "firetasks/simulation.py: defaults"),
    (FW_DAU, FW_LIST_OLD, FW_LIST_NEW, 1, "firetasks/simulationDaughter.py: allow-list"),
    (FW_DAU, FW_DEF_OLD, FW_DEF_NEW, 1, "firetasks/simulationDaughter.py: defaults"),
    (SIM, SIM_KW_OLD, SIM_KW_NEW, 1, "simulation.py: resolution/split kwargs"),
    (SIM, SIM_VAL_OLD, SIM_VAL_NEW, 1, "simulation.py: validation + family forcing"),
    (SB, SB_KEYS_OLD, SB_KEYS_NEW, 2, "scriptBase.py: METADATA_KEYS + SIM_KEYS"),
    (SB, SB_OPT_OLD, SB_OPT_NEW, 1, "scriptBase.py: CLI options"),
    (REL, PE_READ_OLD, PE_READ_NEW, 1, "polypeptide_elongation.py: read the two switches"),
)


# ---------------------------------------------------------------------------------------------------
# STAGE 4 -- the 85-resolution right-hand side.
#
# FOUR edits, all in polypeptide_elongation.py, plus two new @njit kernels. The shape of the stage is
# dictated by acceptance item A: the family path must be BIT-IDENTICAL, so every existing line that
# runs at family resolution is reproduced VERBATIM inside an `else:` branch rather than parameterised.
# Parameterising (`n_state_trna` in place of `n_aas_masked`, say) would be equal in value and shorter,
# but it would make bit-identity an argument instead of an inspection.
#
# WHAT RUNS AT WHICH RESOLUTION, and why:
#   * charging (v_i)               85 -- one synthetase pool per FAMILY, so the denominator carries a
#                                        SUM over the family. With KMtf broadcast per family that
#                                        collapses to the 21-form denominator identically, which is
#                                        what makes the reduction exact for arbitrary splits.
#   * the amino-acid clamp          85 -- but AGGREGATE-then-rescale, never elementwise fmin.
#   * ribosome denominator, v_rib   21 -- u_i and c_i are aggregated back to families INSIDE the RHS
#                                        before it is formed. r == 1 by construction; nothing to pin.
#   * v_charging as RETURNED        20 -- aggregated, so the closure's `daa[mask] = v_supply[mask] -
#                                        v_charging` at the call site needs no edit at all.
#   * everything after integration  21 -- the pools are aggregated straight after negative_check, so
#                                        fraction_charged, the post-integration ribosome denominator
#                                        and the second v_rib clamp are the unchanged 21 arithmetic.
#
# NUMBA ROUTE TAKEN: manual accumulation over a precomputed int64 family-index array, NOT T2A @ u.
# Measured: both kernels compile nopython under numba 0.66.0 / numpy 2.4.6. The index route was
# chosen on merit rather than as a fallback -- the map is one-hot, so accumulation is O(85) rather
# than O(20*85), it needs no C-contiguity contract inside the kernel, and it cannot silently
# mis-broadcast the way a matmul against a transposed view can.
# ---------------------------------------------------------------------------------------------------

MARKER_RHS = "ROUTE1 step 2: isoacceptor right-hand side"

# R1 -- the dcdt closure's call site. The `else` branch is the ORIGINAL four lines byte for byte,
# including the trailing space after `mask,` on the first of them.
RHS_CALL_OLD = (
    "\t\tv_charging, dtrna, daa = dcdt_jit(t, c, n_aas_masked, n_aas, mask, \n"
    "\t\t\tparams['kS'], synthetase_conc, params['KMaa'], params['KMtf'],\n"
    "\t\t\tf, params['krta'], params['krtf'], params['max_elong_rate'],\n"
    "\t\t\tribosome_conc, limit_v_rib, aa_rate_limit, v_rib_max)\n"
)
RHS_CALL_NEW = (
    "\t\tif iso:\n"
    "\t\t\t# 85-resolution kernel. It returns v_charging ALREADY AGGREGATED to the 20 charging-masked\n"
    "\t\t\t# amino acids, which is why the supply branch below needs no edit: `daa[mask] = ...` is\n"
    "\t\t\t# still a 20-vector assignment. dtrna is the only return that changes shape.\n"
    "\t\t\tv_charging, dtrna, daa = dcdt_jit_iso(t, c, n_trna, n_aas, mask,\n"
    "\t\t\t\tparams['kS'], synthetase_conc, params['KMaa'], KMtf_trna,\n"
    "\t\t\t\tf, params['krta'], params['krtf'], params['max_elong_rate'],\n"
    "\t\t\t\tribosome_conc, limit_v_rib, aa_rate_limit, v_rib_max,\n"
    "\t\t\t\ttrna_to_aa_index, n_trna_per_aa, equal_split)\n"
    "\t\telse:\n"
    "\t\t\tv_charging, dtrna, daa = dcdt_jit(t, c, n_aas_masked, n_aas, mask, \n"
    "\t\t\t\tparams['kS'], synthetase_conc, params['KMaa'], params['KMtf'],\n"
    "\t\t\t\tf, params['krta'], params['krtf'], params['max_elong_rate'],\n"
    "\t\t\t\tribosome_conc, limit_v_rib, aa_rate_limit, v_rib_max)\n"
)

# R2 -- resolution setup and the initial condition.
RHS_INIT_OLD = (
    "\tv_rib_max = max(0, ((aa_rate_limit + trna_rate_limit) / f).min())\n"
    "\n"
    "\t# Integrate rates of charging and elongation\n"
    "\tc_init = np.hstack((original_uncharged_trna_conc, original_charged_trna_conc,\n"
    "\t\taa_conc, np.zeros(n_aas), np.zeros(n_aas), np.zeros(n_aas)))\n"
)
RHS_INIT_NEW = (
    "\tv_rib_max = max(0, ((aa_rate_limit + trna_rate_limit) / f).min())\n"
    "\n"
    "\t# ROUTE1 step 2 -- resolution setup. Everything above this line is per AMINO ACID and STAYS\n"
    "\t# per amino acid: aa_rate_limit and v_rib_max are the family limits, and they are exactly what\n"
    "\t# the 85-resolution clamp is applied against. Only the tRNA pools are re-resolved.\n"
    "\tiso = params.get('trna_resolution', 'family') == 'isoacceptor'\n"
    "\tif iso:\n"
    "\t\tif use_disabled_aas:\n"
    "\t\t\t# T2A has one row per CHARGING-MASKED amino acid, so a run that re-enables the disabled\n"
    "\t\t\t# ones has no isoacceptor map to use. Raise rather than quietly fall back to family: a\n"
    "\t\t\t# silent fall back yields a run whose metadata says isoacceptor and whose numbers say\n"
    "\t\t\t# family, which is the single failure this switch exists to prevent.\n"
    "\t\t\traise ValueError('use_disabled_aas is not supported at isoacceptor resolution')\n"
    "\t\tT2A = params['T2A']\n"
    "\t\tA2T = params['A2T']\n"
    "\t\tn_trna_per_aa = params['n_trna_per_aa']\n"
    "\t\tKMtf_trna = params['KMtf_trna']\n"
    "\t\tn_trna = T2A.shape[1]\n"
    "\t\tif T2A.shape[0] != n_aas_masked:\n"
    "\t\t\traise ValueError('T2A has {} families but {} amino acids are charging-masked'.format(\n"
    "\t\t\t\tT2A.shape[0], n_aas_masked))\n"
    "\t\tif not np.array_equal(T2A.sum(0), np.ones(n_trna)):\n"
    "\t\t\traise ValueError('T2A is not one-hot by column; the family index would be wrong')\n"
    "\t\t# The family index of each isoacceptor. The @njit right-hand side accumulates over THIS\n"
    "\t\t# rather than evaluating T2A @ u: the map is one-hot, so accumulation is O(85) instead of\n"
    "\t\t# O(20*85), and the kernel then carries no C-contiguity contract for a 2D operand.\n"
    "\t\ttrna_to_aa_index = np.ascontiguousarray(T2A.argmax(0).astype(np.int64))\n"
    "\t\tequal_split = params.get('demand_split', 'abundance') == 'equal'\n"
    "\t\t# Expand the incoming FAMILY pools to isoacceptors. This function's interface is still\n"
    "\t\t# 21-vectors, so no within-family abundance reaches here and the expansion is uniform.\n"
    "\t\t# That costs nothing in the aggregate and it is not a stand-in for a missing derivation:\n"
    "\t\t# with KMtf broadcast per family the family-aggregated 85-form flux equals the 21-form for\n"
    "\t\t# ARBITRARY within-family splits, so no split can move a 21-resolution output. The\n"
    "\t\t# consequence is worth stating plainly -- until a later stage widens the CALLER to pass\n"
    "\t\t# genuinely resolved pools, the isoacceptor path reproduces the family answer to solver\n"
    "\t\t# tolerance. That is the intended, checkable intermediate state.\n"
    "\t\tiso_uncharged_trna_conc = A2T @ (original_uncharged_trna_conc / n_trna_per_aa)\n"
    "\t\tiso_charged_trna_conc = A2T @ (original_charged_trna_conc / n_trna_per_aa)\n"
    "\n"
    "\t# Integrate rates of charging and elongation\n"
    "\tif iso:\n"
    "\t\tc_init = np.hstack((iso_uncharged_trna_conc, iso_charged_trna_conc,\n"
    "\t\t\taa_conc, np.zeros(n_aas), np.zeros(n_aas), np.zeros(n_aas)))\n"
    "\telse:\n"
    "\t\tc_init = np.hstack((original_uncharged_trna_conc, original_charged_trna_conc,\n"
    "\t\t\taa_conc, np.zeros(n_aas), np.zeros(n_aas), np.zeros(n_aas)))\n"
)

# R3 -- unpacking the solution. The `else` branch is the original seven lines verbatim.
RHS_POST_OLD = (
    "\t# Determine new values from integration results\n"
    "\tfinal_uncharged_trna_conc = c_sol[-1, :n_aas_masked]\n"
    "\tfinal_charged_trna_conc = c_sol[-1, n_aas_masked:2*n_aas_masked]\n"
    "\ttotal_synthesis = c_sol[-1, 2*n_aas_masked+n_aas:2*n_aas_masked+2*n_aas]\n"
    "\ttotal_import = c_sol[-1, 2*n_aas_masked+2*n_aas:2*n_aas_masked+3*n_aas]\n"
    "\ttotal_export = c_sol[-1, 2*n_aas_masked+3*n_aas:2*n_aas_masked+4*n_aas]\n"
    "\n"
    "\tnegative_check(final_uncharged_trna_conc, final_charged_trna_conc)\n"
    "\tnegative_check(final_charged_trna_conc, final_uncharged_trna_conc)\n"
)
RHS_POST_NEW = (
    "\t# Determine new values from integration results\n"
    "\tif iso:\n"
    "\t\t# The state lives at 85, so unpack it there and run negative_check per SPECIES -- aggregating\n"
    "\t\t# first would hide a negative isoacceptor behind a positive family total, which is exactly\n"
    "\t\t# the floating-point residue negative_check exists to catch. Then aggregate the pools back to\n"
    "\t\t# 20, so every line below (fraction_charged, the ribosome denominator, the second v_rib\n"
    "\t\t# clamp) is the unchanged 21-resolution arithmetic and r == 1 by construction.\n"
    "\t\tfinal_uncharged_trna_conc = c_sol[-1, :n_trna]\n"
    "\t\tfinal_charged_trna_conc = c_sol[-1, n_trna:2*n_trna]\n"
    "\t\ttotal_synthesis = c_sol[-1, 2*n_trna+n_aas:2*n_trna+2*n_aas]\n"
    "\t\ttotal_import = c_sol[-1, 2*n_trna+2*n_aas:2*n_trna+3*n_aas]\n"
    "\t\ttotal_export = c_sol[-1, 2*n_trna+3*n_aas:2*n_trna+4*n_aas]\n"
    "\n"
    "\t\tnegative_check(final_uncharged_trna_conc, final_charged_trna_conc)\n"
    "\t\tnegative_check(final_charged_trna_conc, final_uncharged_trna_conc)\n"
    "\n"
    "\t\tfinal_uncharged_trna_conc = T2A @ final_uncharged_trna_conc\n"
    "\t\tfinal_charged_trna_conc = T2A @ final_charged_trna_conc\n"
    "\telse:\n"
    "\t\tfinal_uncharged_trna_conc = c_sol[-1, :n_aas_masked]\n"
    "\t\tfinal_charged_trna_conc = c_sol[-1, n_aas_masked:2*n_aas_masked]\n"
    "\t\ttotal_synthesis = c_sol[-1, 2*n_aas_masked+n_aas:2*n_aas_masked+2*n_aas]\n"
    "\t\ttotal_import = c_sol[-1, 2*n_aas_masked+2*n_aas:2*n_aas_masked+3*n_aas]\n"
    "\t\ttotal_export = c_sol[-1, 2*n_aas_masked+3*n_aas:2*n_aas_masked+4*n_aas]\n"
    "\n"
    "\t\tnegative_check(final_uncharged_trna_conc, final_charged_trna_conc)\n"
    "\t\tnegative_check(final_charged_trna_conc, final_uncharged_trna_conc)\n"
)

# R4 -- the two new @njit kernels, inserted between dcdt_jit and get_charging_supply_function.
# dcdt_jit itself is NOT touched: at family resolution it is still the function that runs, unedited.
RHS_KERNEL_OLD = (
    "\treturn v_charging, dtrna, daa\n"
    "\n"
    "def get_charging_supply_function(\n"
)
RHS_KERNEL_NEW = (
    "\treturn v_charging, dtrna, daa\n"
    "\n"
    "@njit(error_model='numpy')\n"
    "def clamp_charging_shared(v_trna, limit_aa, trna_to_aa_index, n_aas_masked):\n"
    "\t'''\n"
    "\tROUTE1 step 2: isoacceptor right-hand side -- the amino-acid rate clamp, at 85 resolution.\n"
    "\n"
    "\tdcdt_jit clamps the charging flux against the amino acid actually available with an elementwise\n"
    "\tnp.fmin(v_charging, aa_rate_limit), which is exact while both sides are per amino acid. At\n"
    "\tisoacceptor resolution the flux is per SPECIES and the limit stays per FAMILY, and the obvious\n"
    "\tlift -- broadcast L_a to every isoacceptor and fmin elementwise -- is wrong twice over. First,\n"
    "\tmin does not commute with the family sum,\n"
    "\n"
    "\t\tsum_i min(v_i, L_a)  !=  min(sum_i v_i, L_a),\n"
    "\n"
    "\tso it breaks the exact 85 -> 21 reduction. Second and worse, each of the family's n_a\n"
    "\tisoacceptors is independently granted the FULL family limit, so the family can draw up to\n"
    "\tn_a * L_a of an amino acid that only had L_a. MEASURED phantom capacity over 500 random binding\n"
    "\tstates: median 2.73x, max 4.84x. limit_v_rib=True is the production request path, so the naive\n"
    "\tlift would be wrong on the only path that runs.\n"
    "\n"
    "\tThe correct form, pinned by tests/test_charging_clamp_commutation.py in the Cellarium repo:\n"
    "\tclamp the family AGGREGATE, then rescale that family's isoacceptors proportionally.\n"
    "\n"
    "\t\tV_a = sum_{i in a} v_i ; V_a_clamped = min(V_a, L_a) ; v_i *= V_a_clamped / V_a\n"
    "\n"
    "\twhich restores sum_{i in a} v_i_clamped == min(sum_i v_i, L_a) identically, and preserves every\n"
    "\twithin-family share. V_a == 0 maps to exactly 0, never NaN -- not a synthetic edge case, since\n"
    "\tVALINE has seven identically zero uncharged counts at BulkMolecules row 0 in BOTH ParCa trees.\n"
    "\n"
    "\tV_a < 0 also maps to 0, matching the pinned reference. That differs from the 21-form, which\n"
    "\twould pass a negative flux through fmin unchanged; it is a deliberate match to the test, and it\n"
    "\tis reachable only from a transiently negative pool inside the solver.\n"
    "\n"
    "\tReturns a NEW array; v_trna is not modified.\n"
    "\t'''\n"
    "\ttotals = np.zeros(n_aas_masked)\n"
    "\tfor i in range(len(v_trna)):\n"
    "\t\ttotals[trna_to_aa_index[i]] += v_trna[i]\n"
    "\n"
    "\tscale = np.zeros(n_aas_masked)\n"
    "\tfor a in range(n_aas_masked):\n"
    "\t\tif totals[a] > 0:\n"
    "\t\t\t# Written as a comparison rather than min() so a NaN limit leaves the family alone,\n"
    "\t\t\t# which is the direction np.fmin takes in the 21-form.\n"
    "\t\t\tif limit_aa[a] < totals[a]:\n"
    "\t\t\t\tscale[a] = limit_aa[a] / totals[a]\n"
    "\t\t\telse:\n"
    "\t\t\t\tscale[a] = 1.0\n"
    "\t\telse:\n"
    "\t\t\tscale[a] = 0.0\n"
    "\n"
    "\tout = np.zeros(len(v_trna))\n"
    "\tfor i in range(len(v_trna)):\n"
    "\t\tout[i] = v_trna[i] * scale[trna_to_aa_index[i]]\n"
    "\treturn out\n"
    "\n"
    "@njit(error_model='numpy')\n"
    "def dcdt_jit_iso(t, c, n_trna, n_aas, mask,\n"
    "\tkS, synthetase_conc, KMaa, KMtf_trna,\n"
    "\tf, krta, krtf, max_elong_rate,\n"
    "\tribosome_conc, limit_v_rib, aa_rate_limit, v_rib_max,\n"
    "\ttrna_to_aa_index, n_trna_per_aa, equal_split\n"
    "):\n"
    "\t'''\n"
    "\tThe 85-isoacceptor form of dcdt_jit. dcdt_jit itself is untouched and is still what runs at\n"
    "\tfamily resolution, so that path is bit-identical rather than argued to be.\n"
    "\n"
    "\tSHARED SYNTHETASE. All isoacceptors of an amino acid compete for ONE synthetase pool -- there is\n"
    "\tone aminoacyl-tRNA synthetase per amino acid -- so the denominator carries a SUM over the family,\n"
    "\tnever a per-species denominator:\n"
    "\n"
    "\t\tU_a  = sum_{i in a} u_i / KMtf_i\n"
    "\t\tv_i  = kS * S_a * (A_a/KMaa_a) / (1 + U_a + A_a/KMaa_a + U_a*A_a/KMaa_a) * u_i/KMtf_i\n"
    "\n"
    "\tBecause KMtf is BROADCAST per family, U_a == u_a/KMtf_a and sum_{i in a} v_i is identically the\n"
    "\t21-form v_a -- for ARBITRARY within-family splits of u_a, not merely at zero spread. That is the\n"
    "\treduction, and it is why the split choice cannot move a 21-resolution output.\n"
    "\n"
    "\tTHE RIBOSOME ARM STAYS AT 21. u_i and c_i are aggregated back to families HERE, before the\n"
    "\tribosome denominator is formed, so numerator_ribosome and v_rib are the unchanged 21-resolution\n"
    "\tscalars and r == 1 by construction. Letting the denominator follow charging to 85 would drop\n"
    "\tv_rib by ~21%, and about two thirds of that is spurious: the 86 tRNA genes carry only 41 distinct\n"
    "\t(family, anticodon) pairs, and anticodon-identical duplicates are not separate A-site queues.\n"
    "\n"
    "\tDEMAND SPLIT. f is per amino acid; f_i divides it within the family, by pool share ('abundance',\n"
    "\tthe default) or evenly ('equal'). Either way sum_{i in a} f_i == f_a, so v_rib*f aggregates\n"
    "\texactly and dtrna reduces to the 21-form. A family with an empty pool falls back to the even\n"
    "\tsplit, which keeps that sum intact instead of producing 0/0.\n"
    "\n"
    "\tv_charging is returned AGGREGATED to the 20 charging-masked amino acids, so the caller's\n"
    "\t`daa[mask] = v_supply[mask] - v_charging` needs no edit. dtrna is the only return that changes\n"
    "\tshape, and it is the only one whose shape the state vector depends on.\n"
    "\n"
    "\tNUMBA. Family sums are manual accumulations over the int64 trna_to_aa_index rather than T2A @ u:\n"
    "\tthe map is one-hot, so this is O(85) instead of O(20*85), and no 2D operand crosses into the\n"
    "\tkernel. Both this and clamp_charging_shared compile nopython.\n"
    "\t'''\n"
    "\tn_fam = len(f)\n"
    "\tuncharged_trna_conc = c[:n_trna]\n"
    "\tcharged_trna_conc = c[n_trna:2*n_trna]\n"
    "\taa_conc = c[2*n_trna:2*n_trna+n_aas]\n"
    "\tmasked_aa_conc = aa_conc[mask]\n"
    "\tKMaa_masked = KMaa[mask]\n"
    "\n"
    "\t# Family aggregates, and u_i/KMtf_i both per species and summed over the family.\n"
    "\tu_fam = np.zeros(n_fam)\n"
    "\tc_fam = np.zeros(n_fam)\n"
    "\trel_fam = np.zeros(n_fam)\n"
    "\trel_trna = np.zeros(n_trna)\n"
    "\tfor i in range(n_trna):\n"
    "\t\ta = trna_to_aa_index[i]\n"
    "\t\tu_fam[a] += uncharged_trna_conc[i]\n"
    "\t\tc_fam[a] += charged_trna_conc[i]\n"
    "\t\tr = uncharged_trna_conc[i] / KMtf_trna[i]\n"
    "\t\trel_trna[i] = r\n"
    "\t\trel_fam[a] += r\n"
    "\n"
    "\t# Charging, with ONE shared synthetase denominator per family.\n"
    "\tfamily_rate = np.zeros(n_fam)\n"
    "\tfor a in range(n_fam):\n"
    "\t\ts_aa = masked_aa_conc[a] / KMaa_masked[a]\n"
    "\t\tdenom = 1.0 + rel_fam[a] + s_aa + rel_fam[a] * s_aa\n"
    "\t\tfamily_rate[a] = kS * synthetase_conc[a] * s_aa / denom\n"
    "\tv_charging = np.zeros(n_trna)\n"
    "\tfor i in range(n_trna):\n"
    "\t\tv_charging[i] = family_rate[trna_to_aa_index[i]] * rel_trna[i]\n"
    "\n"
    "\t# The A-site arm, at 21 resolution, from the AGGREGATED pools. Identical expression to dcdt_jit.\n"
    "\tnumerator_ribosome = 1 + np.sum(f * (krta / c_fam + u_fam / c_fam * krta / krtf))\n"
    "\tv_rib = max_elong_rate * ribosome_conc / numerator_ribosome\n"
    "\n"
    "\t# Handle case when f is 0 and charged_trna_conc is 0\n"
    "\tif not np.isfinite(v_rib):\n"
    "\t\tv_rib = 0\n"
    "\n"
    "\t# Within-family demand split. sum_{i in a} f_trna[i] == f[a] under both options.\n"
    "\tf_trna = np.zeros(n_trna)\n"
    "\tif equal_split:\n"
    "\t\tfor i in range(n_trna):\n"
    "\t\t\ta = trna_to_aa_index[i]\n"
    "\t\t\tf_trna[i] = f[a] / n_trna_per_aa[a]\n"
    "\telse:\n"
    "\t\tfor i in range(n_trna):\n"
    "\t\t\ta = trna_to_aa_index[i]\n"
    "\t\t\tpool = u_fam[a] + c_fam[a]\n"
    "\t\t\tif pool > 0:\n"
    "\t\t\t\tf_trna[i] = f[a] * (uncharged_trna_conc[i] + charged_trna_conc[i]) / pool\n"
    "\t\t\telse:\n"
    "\t\t\t\tf_trna[i] = f[a] / n_trna_per_aa[a]\n"
    "\n"
    "\t# Limit v_rib and v_charging to the amount of available amino acids\n"
    "\tif limit_v_rib:\n"
    "\t\tv_charging = clamp_charging_shared(v_charging, aa_rate_limit, trna_to_aa_index, n_fam)\n"
    "\t\tv_rib = min(v_rib, v_rib_max)\n"
    "\n"
    "\tdtrna = v_charging - v_rib*f_trna\n"
    "\n"
    "\tv_charging_aa = np.zeros(n_fam)\n"
    "\tfor i in range(n_trna):\n"
    "\t\tv_charging_aa[trna_to_aa_index[i]] += v_charging[i]\n"
    "\n"
    "\tdaa = np.zeros(n_aas)\n"
    "\n"
    "\treturn v_charging_aa, dtrna, daa\n"
    "\n"
    "def get_charging_supply_function(\n"
)

RHS_EDITS = (
    (REL, RHS_KERNEL_OLD, RHS_KERNEL_NEW, 1, "polypeptide_elongation.py: dcdt_jit_iso + clamp_charging_shared"),
    (REL, RHS_CALL_OLD, RHS_CALL_NEW, 1, "polypeptide_elongation.py: dcdt closure resolution branch"),
    (REL, RHS_INIT_OLD, RHS_INIT_NEW, 1, "polypeptide_elongation.py: resolution setup + c_init"),
    (REL, RHS_POST_OLD, RHS_POST_NEW, 1, "polypeptide_elongation.py: post-integration unpack + aggregation"),
)


# ---------------------------------------------------------------------------------------------------
# STAGE 5 -- WIDEN THE INTERFACE to genuine 85-vectors.
#
# Stage 4 built the 85-resolution kernel but left the CALLER at 21: calculate_trna_charging still took
# 21-vectors and expanded them UNIFORMLY (A2T @ (x / n_trna_per_aa)). With KMtf broadcast per family
# and one shared synthetase denominator a uniform family stays uniform, so the isoacceptor path
# reproduced the family answer BY CONSTRUCTION. This stage supplies the pools that wcEcoli already
# tracks per species, so isoacceptors of one family can differ.
#
# WHAT THIS STAGE DOES **NOT** DO, stated first because it is the honest headline and because
# discovering it later would be worse than reading it here.
#
#   MEASURED, before a line of this stage was written: under the FIXED DEFAULT demand split
#   ('abundance') widening the caller does not produce a within-family spread in the ODE OUTPUT,
#   because the 85-resolution steady state under that split is exactly proportional and one
#   production timestep is long enough to reach it. The real per-species input spread -- 3.3e-4 to
#   9.5e-3 across the 17 multi-member families, measured off BulkMolecules -- is CONTRACTED by the
#   solve to 1.1e-16..3.1e-8. Derivation, confirmed by execution: the species total T_i = u_i + c_i
#   is conserved exactly (du = -dtrna, dc = +dtrna); charging is v_i = R_a * u_i / KMtf_a with a
#   family-scalar R_a, and the abundance split makes demand v_rib * f_a * T_i / T_a; setting
#   v_i = demand gives u_i proportional to T_i, hence c_i / T_i constant within the family.
#
#   Under 'equal' the same widening produces a LARGE genuine spread -- up to 7.2e-2, i.e. 7 charged-
#   fraction points between isoacceptors of one family -- because there the steady state is u_i
#   constant within the family, so c_i / T_i = 1 - u_i / T_i varies with the genuine per-species pool
#   T_i. That pool only exists once the caller is widened: with the uniform expansion the measured
#   output spread is EXACTLY 0.0 under BOTH splits.
#
#   So the widening is the necessary and previously missing half. It is not sufficient on its own at
#   the default split, and the default is NOT changed here -- that is a fixed design decision, and
#   changing it silently is exactly the failure the switch exists to prevent.
#
# INTERFACE SHAPE, and why it is opt-in.
#   calculate_trna_charging gains three keyword-only-by-convention arguments:
#   uncharged_trna_conc_iso, charged_trna_conc_iso (85-vectors with concentration units, restricted
#   to the charging mask) and return_iso. return_iso defaults to False, so THE ARITY OF THE RETURN IS
#   UNCHANGED for every existing caller. models/ecoli/sim/initial_conditions.py:105 and
#   runscripts/debug/charging.py:312 are therefore not edited by this stage and are provably
#   unaffected -- the first because it builds its own family-resolution params and unpacks with
#   `fraction_charged, *_`, the second because it unpacks exactly five names and reads 21-wide
#   listener columns that carry no per-species information to widen with.
#
# WHAT STAYS AT 21, verified numerically rather than asserted:
#   * the ppGpp arm, both halves. The request half reads the 21-wide `fraction_charged` return and
#     the 21-wide uncharged_trna_counts/charged_trna_counts; neither is rebound by this stage. The
#     evolve half re-aggregates from counts and cannot see the change at all.
#   * synthetase_conc / uncharged_trna_conc / charged_trna_conc / aa_conc listener columns (n_aa=21).
#   * v_rib and numerator_ribosome, which the stage-4 RHS already forms from family aggregates.
#
# ORDERING. Masking the two BulkMolecules views with params['trna_charging_mask'] is only correct if
# charged_trna_names[j] is the charged form of uncharged_trna_names[j]. VERIFIED WITHOUT USING NAMES,
# on BOTH ParCa trees: charging_stoich_matrix is built independently of aa_from_trna, and column j
# carries -1 on uncharged_trna_names[j] and +1 on charged_trna_names[j] for all 86 columns, with zero
# exceptions. (A name-based check gives 10 FALSE alarms on the opaque RNA0-3xx ids.) The single
# excluded column is 58, selC-tRNA[c] / charged-selC-tRNA[c], on both trees.
#
# ZERO-POOL SPECIES. With genuine pools an empty species stops being exceptional. u_i == 0 is already
# common (7 identically zero VALINE uncharged counts at row 0 on both trees). u_i + c_i == 0 is the
# harder case: under 'equal' such a species is still assigned demand, so c_i integrates negative,
# negative_check returns it to (0, 0), and the naive c/(u+c) is 0/0. The per-species fraction is
# therefore taken with an explicit where= guard that maps an empty species to 0.0.
# ---------------------------------------------------------------------------------------------------

MARKER_WIDEN = "ROUTE1 step 2 (stage 5): genuine per-isoacceptor pools"

# W1 -- the signature. Additive keywords only; every existing positional call is unaffected.
WD_SIG_OLD = (
    "def calculate_trna_charging(synthetase_conc, uncharged_trna_conc, charged_trna_conc, aa_conc, ribosome_conc,\n"
    "\t\tf, params, supply=None, time_limit=1000, limit_v_rib=False, use_disabled_aas=False):\n"
)
WD_SIG_NEW = (
    "def calculate_trna_charging(synthetase_conc, uncharged_trna_conc, charged_trna_conc, aa_conc, ribosome_conc,\n"
    "\t\tf, params, supply=None, time_limit=1000, limit_v_rib=False, use_disabled_aas=False,\n"
    "\t\tuncharged_trna_conc_iso=None, charged_trna_conc_iso=None, return_iso=False):\n"
)

# W2 -- the docstring. The three new arguments are documented where the other eleven are, so a reader
# who never opens the patch still learns that the pools are opt-in and that the sixth return value
# only exists when asked for.
WD_DOC_OLD = (
    "\t\tuse_disabled_aas (bool) - if True, all amino acids will be used for charging calculations,\n"
    "\t\t\tif False, some will be excluded as determined in initialize\n"
    "\n"
    "\tReturns:\n"
)
WD_DOC_NEW = (
    "\t\tuse_disabled_aas (bool) - if True, all amino acids will be used for charging calculations,\n"
    "\t\t\tif False, some will be excluded as determined in initialize\n"
    "\t\tuncharged_trna_conc_iso (array of floats with concentration units, or None) - ROUTE1 step 2\n"
    "\t\t\t(stage 5): GENUINE per-isoacceptor uncharged tRNA concentrations, one entry per\n"
    "\t\t\tcharging-masked tRNA species in params['trna_charging_mask'] order (85 of 86; selC\n"
    "\t\t\texcluded). Only accepted when params['trna_resolution'] == 'isoacceptor'. If None, the\n"
    "\t\t\tincoming per-amino-acid pools are expanded uniformly across each family, which is the\n"
    "\t\t\tpre-stage-5 behaviour and reproduces the family answer by construction.\n"
    "\t\tcharged_trna_conc_iso (array of floats with concentration units, or None) - as above, for\n"
    "\t\t\tcharged tRNA. Must be supplied together with uncharged_trna_conc_iso or not at all.\n"
    "\t\treturn_iso (bool) - if True, a SIXTH value is returned (see below). Defaults to False so\n"
    "\t\t\tthat the arity of this function is unchanged for callers that predate stage 5.\n"
    "\n"
    "\tReturns:\n"
)

WD_DOC2_OLD = (
    "\t\ttotal_export (np.ndarray) - the total amount of amino acids exported during charging\n"
    "\t\t\tin units of CONC_UNITS.  Will be zeros if supply function is not given.\n"
    "\t'''\n"
)
WD_DOC2_NEW = (
    "\t\ttotal_export (np.ndarray) - the total amount of amino acids exported during charging\n"
    "\t\t\tin units of CONC_UNITS.  Will be zeros if supply function is not given.\n"
    "\t\tfraction_charged_iso (np.ndarray or None) - ONLY when return_iso is True. Fraction of total\n"
    "\t\t\ttRNA that is charged for each of the 85 charging-masked tRNA SPECIES, in\n"
    "\t\t\tparams['trna_charging_mask'] order. None at family resolution. A species with an empty\n"
    "\t\t\ttotal pool maps to 0.0, never NaN.\n"
    "\t'''\n"
)

# W3 -- accept the pools. The uniform expansion is KEPT as the fallback, so a caller that passes
# nothing gets exactly the pre-stage-5 numbers and the stage-4 verification remains valid evidence.
WD_POOL_OLD = (
    "\t\t# Expand the incoming FAMILY pools to isoacceptors. This function's interface is still\n"
    "\t\t# 21-vectors, so no within-family abundance reaches here and the expansion is uniform.\n"
    "\t\t# That costs nothing in the aggregate and it is not a stand-in for a missing derivation:\n"
    "\t\t# with KMtf broadcast per family the family-aggregated 85-form flux equals the 21-form for\n"
    "\t\t# ARBITRARY within-family splits, so no split can move a 21-resolution output. The\n"
    "\t\t# consequence is worth stating plainly -- until a later stage widens the CALLER to pass\n"
    "\t\t# genuinely resolved pools, the isoacceptor path reproduces the family answer to solver\n"
    "\t\t# tolerance. That is the intended, checkable intermediate state.\n"
    "\t\tiso_uncharged_trna_conc = A2T @ (original_uncharged_trna_conc / n_trna_per_aa)\n"
    "\t\tiso_charged_trna_conc = A2T @ (original_charged_trna_conc / n_trna_per_aa)\n"
)
WD_POOL_NEW = (
    "\t\t# ROUTE1 step 2 (stage 5): genuine per-isoacceptor pools, when the caller supplies them.\n"
    "\t\t#\n"
    "\t\t# WITHOUT them (the stage-4 state, still the fallback) the incoming FAMILY pools are\n"
    "\t\t# expanded UNIFORMLY. With KMtf broadcast per family a uniform family stays uniform, so the\n"
    "\t\t# isoacceptor path then reproduces the family answer by construction -- checkable, and\n"
    "\t\t# exactly what makes the stage-4 equivalence gates provable, but it means no within-family\n"
    "\t\t# spread can ever develop.\n"
    "\t\t#\n"
    "\t\t# WITH them the pools carry the real per-species abundances wcEcoli already tracks in\n"
    "\t\t# BulkMolecules. What that buys is split-dependent, and it was MEASURED before this branch\n"
    "\t\t# was written rather than assumed:\n"
    "\t\t#   'abundance' (the default): the steady state is u_i proportional to the species total\n"
    "\t\t#     T_i = u_i + c_i, which T_i is conserved exactly by the integration, so the charged\n"
    "\t\t#     fraction goes UNIFORM within a family no matter what came in. Input spread of\n"
    "\t\t#     3.3e-4..9.5e-3 over the 17 multi-member families contracts to 1.1e-16..3.1e-8 in one\n"
    "\t\t#     production timestep. Widening is a no-op at this split, to ~1e-7 relative.\n"
    "\t\t#   'equal': the steady state is u_i CONSTANT within a family, so the charged fraction\n"
    "\t\t#     1 - u_i/T_i tracks the genuine per-species pool. Measured output spread up to 7.2e-2,\n"
    "\t\t#     against EXACTLY 0.0 with the uniform expansion.\n"
    "\t\t# The default is not changed here; the point is that the choice now has an effect at all.\n"
    "\t\tif uncharged_trna_conc_iso is None and charged_trna_conc_iso is None:\n"
    "\t\t\tiso_uncharged_trna_conc = A2T @ (original_uncharged_trna_conc / n_trna_per_aa)\n"
    "\t\t\tiso_charged_trna_conc = A2T @ (original_charged_trna_conc / n_trna_per_aa)\n"
    "\t\telif uncharged_trna_conc_iso is None or charged_trna_conc_iso is None:\n"
    "\t\t\t# Half a pair is never a defensible state: it would silently mix a genuine pool with a\n"
    "\t\t\t# uniform one and the totals would stop being consistent with each other.\n"
    "\t\t\traise ValueError('supply both uncharged_trna_conc_iso and charged_trna_conc_iso, or neither')\n"
    "\t\telse:\n"
    "\t\t\tiso_uncharged_trna_conc = np.asarray(\n"
    "\t\t\t\tuncharged_trna_conc_iso.asNumber(CONC_UNITS), dtype=np.float64)\n"
    "\t\t\tiso_charged_trna_conc = np.asarray(\n"
    "\t\t\t\tcharged_trna_conc_iso.asNumber(CONC_UNITS), dtype=np.float64)\n"
    "\t\t\t# Shape is the ONLY thing that can silently scramble the mapping, so it is checked\n"
    "\t\t\t# rather than trusted. Ordering itself is guaranteed upstream: the caller masks the two\n"
    "\t\t\t# BulkMolecules views with params['trna_charging_mask'], whose columns index\n"
    "\t\t\t# aa_from_trna, and charged_trna_names[j] is verified to be the charged form of\n"
    "\t\t\t# uncharged_trna_names[j] for all 86 j against charging_stoich_matrix on both ParCa trees.\n"
    "\t\t\tif iso_uncharged_trna_conc.shape != (n_trna,) or iso_charged_trna_conc.shape != (n_trna,):\n"
    "\t\t\t\traise ValueError('per-isoacceptor pools must have shape ({},); got {} and {}'.format(\n"
    "\t\t\t\t\tn_trna, iso_uncharged_trna_conc.shape, iso_charged_trna_conc.shape))\n"
    "\t\t\tif not (np.all(np.isfinite(iso_uncharged_trna_conc))\n"
    "\t\t\t\t\tand np.all(np.isfinite(iso_charged_trna_conc))):\n"
    "\t\t\t\traise ValueError('per-isoacceptor pools contain non-finite values')\n"
    "\t\t\tif iso_uncharged_trna_conc.min() < 0 or iso_charged_trna_conc.min() < 0:\n"
    "\t\t\t\traise ValueError('per-isoacceptor pools contain negative concentrations')\n"
)

# W4 -- reject pools that cannot be used. Accepting and ignoring them is the silent-absence failure:
# the run would report isoacceptor resolution and quietly integrate the uniform expansion.
WD_GUARD_OLD = (
    "\tiso = params.get('trna_resolution', 'family') == 'isoacceptor'\n"
    "\tif iso:\n"
)
WD_GUARD_NEW = (
    "\tiso = params.get('trna_resolution', 'family') == 'isoacceptor'\n"
    "\t# ROUTE1 step 2 (stage 5): per-isoacceptor pools are meaningless at family resolution. Raise\n"
    "\t# rather than ignore them -- ignoring is how a run ends up reporting one resolution and\n"
    "\t# integrating another.\n"
    "\tif not iso and (uncharged_trna_conc_iso is not None or charged_trna_conc_iso is not None):\n"
    "\t\traise ValueError('per-isoacceptor pools were supplied but '\n"
    "\t\t\t\"params['trna_resolution'] is not 'isoacceptor'\")\n"
    "\tif iso:\n"
)

# W5 -- the per-species charged fraction, taken BEFORE the pools are aggregated back to families.
# It is the only quantity in this function that carries within-family information; everything after
# the aggregation is the unchanged 21-resolution arithmetic that keeps r == 1.
WD_FRAC_OLD = (
    "\t\tfinal_uncharged_trna_conc = T2A @ final_uncharged_trna_conc\n"
    "\t\tfinal_charged_trna_conc = T2A @ final_charged_trna_conc\n"
    "\telse:\n"
    "\t\tfinal_uncharged_trna_conc = c_sol[-1, :n_aas_masked]\n"
)
WD_FRAC_NEW = (
    "\t\t# ROUTE1 step 2 (stage 5): the PER-SPECIES charged fraction, taken HERE because the next two\n"
    "\t\t# lines destroy the within-family information it carries. A species whose TOTAL pool is\n"
    "\t\t# empty maps to 0.0 rather than 0/0: with genuine pools that case stops being exceptional,\n"
    "\t\t# and under the 'equal' split such a species is still assigned elongation demand, drives\n"
    "\t\t# its charged pool negative, and is returned to (0, 0) by negative_check just above.\n"
    "\t\tiso_total_trna_conc = final_uncharged_trna_conc + final_charged_trna_conc\n"
    "\t\tfraction_charged_iso = np.zeros(n_trna)\n"
    "\t\tnp.divide(final_charged_trna_conc, iso_total_trna_conc, out=fraction_charged_iso,\n"
    "\t\t\twhere=iso_total_trna_conc > 0)\n"
    "\n"
    "\t\tfinal_uncharged_trna_conc = T2A @ final_uncharged_trna_conc\n"
    "\t\tfinal_charged_trna_conc = T2A @ final_charged_trna_conc\n"
    "\telse:\n"
    "\t\tfraction_charged_iso = None\n"
    "\t\tfinal_uncharged_trna_conc = c_sol[-1, :n_aas_masked]\n"
)

# W6 -- the return. Opt-in sixth element; the five-tuple is byte-for-byte the original statement.
WD_RET_OLD = (
    "\treturn new_fraction_charged, v_rib, total_synthesis, total_import, total_export\n"
)
WD_RET_NEW = (
    "\t# ROUTE1 step 2 (stage 5): the sixth value is OPT-IN so that the arity of this function is\n"
    "\t# unchanged for callers that predate the stage. initial_conditions.py and\n"
    "\t# runscripts/debug/charging.py are untouched by stage 5 and provably unaffected: the first\n"
    "\t# builds family-resolution params of its own and unpacks with `fraction_charged, *_`, the\n"
    "\t# second unpacks exactly five names and reads 21-wide listener columns that carry no\n"
    "\t# per-species information it could widen with.\n"
    "\tif return_iso:\n"
    "\t\treturn (new_fraction_charged, v_rib, total_synthesis, total_import, total_export,\n"
    "\t\t\tfraction_charged_iso)\n"
    "\treturn new_fraction_charged, v_rib, total_synthesis, total_import, total_export\n"
)

# W6b -- A LATENT STAGE-4 DEFECT, found by running a real simulation and by nothing else.
#
# The dcdt closure slices the amino-acid block out of the state vector to feed the supply function:
#
#     aa_conc = c[2*n_aas_masked:2*n_aas_masked+n_aas]
#
# That offset is the width of the tRNA block, which stage 4 changed from 2*n_aas_masked (40) to
# 2*n_trna (170) at isoacceptor resolution -- but only in c_init and in the post-integration unpack,
# not here. So at isoacceptor resolution the supply function was handed 21 numbers taken from the
# MIDDLE OF THE tRNA STATE and called them amino acid concentrations. The integration then produced
# non-finite values and BDF raised 'array must not contain infs or NaNs' inside lu_factor.
#
# WHY EVERY STAGE-4 GATE MISSED IT: the branch is `if supply is None` -- and supply is None in the
# offline kernel drivers, in initial_conditions.py, and in every equivalence check run so far. It is
# NOT None on the production request path, which is the only path that matters. This is precisely the
# silent-absence failure mode: nothing about the code reads wrong, the family path is untouched, and
# the first evidence is a real simulation refusing to start.
#
# The fix is resolution-dependent offset arithmetic. At family resolution n_trna_state IS
# n_aas_masked, so the slice is character-for-character the same computation and the family path
# stays bit-identical -- verified by execution, not by argument.
WD_SUPPLY_OLD = (
    "\t\telse:\n"
    "\t\t\taa_conc = c[2*n_aas_masked:2*n_aas_masked+n_aas]\n"
    "\t\t\tv_synthesis, v_import, v_export = supply(unit_conversion * aa_conc)\n"
)
WD_SUPPLY_NEW = (
    "\t\telse:\n"
    "\t\t\t# ROUTE1 step 2 (stage 5): the amino-acid block starts AFTER the tRNA block, and that\n"
    "\t\t\t# block is 2*n_trna wide at isoacceptor resolution, not 2*n_aas_masked. Slicing it with\n"
    "\t\t\t# n_aas_masked unconditionally handed the supply function 21 values read out of the\n"
    "\t\t\t# MIDDLE OF THE tRNA STATE; the integration then went non-finite and BDF raised inside\n"
    "\t\t\t# lu_factor. Only reachable when supply is not None, which is the production request path\n"
    "\t\t\t# and no other -- which is why it survived every offline check.\n"
    "\t\t\t#\n"
    "\t\t\t# At family resolution n_trna_state is n_aas_masked, so the slice below is the same\n"
    "\t\t\t# computation on the same values and that path stays bit-identical.\n"
    "\t\t\tn_trna_state = n_trna if iso else n_aas_masked\n"
    "\t\t\taa_conc = c[2*n_trna_state:2*n_trna_state+n_aas]\n"
    "\t\t\tv_synthesis, v_import, v_export = supply(unit_conversion * aa_conc)\n"
)

# W7 -- read the per-species counts in the request. The two aggregating np.dot lines are KEPT
# VERBATIM: they are what the ppGpp arm and the 21-wide listener columns read, and their meaning must
# not shift by a bit.
WD_COUNTS_OLD = (
    "\t\tuncharged_trna_counts = np.dot(self.process.aa_from_trna, self.uncharged_trna.total_counts())\n"
    "\t\tcharged_trna_counts = np.dot(self.process.aa_from_trna, self.charged_trna.total_counts())\n"
)
WD_COUNTS_NEW = (
    "\t\tuncharged_trna_counts = np.dot(self.process.aa_from_trna, self.uncharged_trna.total_counts())\n"
    "\t\tcharged_trna_counts = np.dot(self.process.aa_from_trna, self.charged_trna.total_counts())\n"
    "\t\t# ROUTE1 step 2 (stage 5): genuine per-isoacceptor pools, straight off the per-species\n"
    "\t\t# BulkMolecules views. The two aggregating lines above are NOT replaced -- they are what the\n"
    "\t\t# ppGpp arm (both halves) and the 21-wide GrowthLimits columns read, and they keep their\n"
    "\t\t# meaning exactly.\n"
    "\t\t#\n"
    "\t\t# ORDERING. bulkMoleculesView(names) returns counts in names order, and trna_charging_mask\n"
    "\t\t# indexes the columns of aa_from_trna, which are indexed by uncharged_trna_names -- so the\n"
    "\t\t# uncharged side is aligned trivially. The charged side needs charged_trna_names[j] to be\n"
    "\t\t# the charged form of uncharged_trna_names[j]; that is VERIFIED WITHOUT USING NAMES against\n"
    "\t\t# charging_stoich_matrix, which is built independently of aa_from_trna and carries -1 on\n"
    "\t\t# uncharged_trna_names[j] and +1 on charged_trna_names[j] in column j, for all 86 columns on\n"
    "\t\t# both ParCa trees. A name-based check would report 10 false misalignments on the opaque\n"
    "\t\t# RNA0-3xx ids, which is why it is not the check used.\n"
    "\t\tself.trna_resolution_iso = (\n"
    "\t\t\tself.charging_params.get('trna_resolution', 'family') == 'isoacceptor')\n"
    "\t\tif self.trna_resolution_iso:\n"
    "\t\t\ttrna_charging_mask = self.charging_params['trna_charging_mask']\n"
    "\t\t\tiso_uncharged_trna_counts = self.uncharged_trna.total_counts()[trna_charging_mask]\n"
    "\t\t\tiso_charged_trna_counts = self.charged_trna.total_counts()[trna_charging_mask]\n"
)

# W8 -- the concentrations, next to the 21-wide ones they parallel.
WD_CONC_OLD = (
    "\t\tuncharged_trna_conc = self.counts_to_molar * uncharged_trna_counts\n"
    "\t\tcharged_trna_conc = self.counts_to_molar * charged_trna_counts\n"
)
WD_CONC_NEW = (
    "\t\tuncharged_trna_conc = self.counts_to_molar * uncharged_trna_counts\n"
    "\t\tcharged_trna_conc = self.counts_to_molar * charged_trna_counts\n"
    "\t\tif self.trna_resolution_iso:\n"
    "\t\t\t# ROUTE1 step 2 (stage 5): same counts_to_molar, so the 85-vectors sum to the 21-vectors\n"
    "\t\t\t# above to floating-point exactness of the summation order, not to a separate conversion.\n"
    "\t\t\tiso_uncharged_trna_conc = self.counts_to_molar * iso_uncharged_trna_counts\n"
    "\t\t\tiso_charged_trna_conc = self.counts_to_molar * iso_charged_trna_counts\n"
)

# W9 -- the call. The family branch is the ORIGINAL eleven lines byte for byte, for the same reason
# stage 4 duplicated rather than parameterised: bit-identity becomes an inspection, not an argument.
WD_CALL_OLD = (
    "\t\tfraction_charged, v_rib, synthesis_in_charging, import_in_charging, export_in_charging = calculate_trna_charging(\n"
    "\t\t\tsynthetase_conc,\n"
    "\t\t\tuncharged_trna_conc,\n"
    "\t\t\tcharged_trna_conc,\n"
    "\t\t\taa_conc,\n"
    "\t\t\tribosome_conc,\n"
    "\t\t\tf,\n"
    "\t\t\tself.charging_params,\n"
    "\t\t\tsupply=supply_function,\n"
    "\t\t\tlimit_v_rib=True,\n"
    "\t\t\ttime_limit=self.process.timeStepSec())\n"
)
WD_CALL_NEW = (
    "\t\tif self.trna_resolution_iso:\n"
    "\t\t\t# ROUTE1 step 2 (stage 5): the 21-vectors are STILL PASSED -- they set the family\n"
    "\t\t\t# aggregates, aa_rate_limit and v_rib_max, all of which stay per amino acid. The two\n"
    "\t\t\t# 85-vectors only decide how each family's pool is divided among its isoacceptors.\n"
    "\t\t\t(fraction_charged, v_rib, synthesis_in_charging, import_in_charging,\n"
    "\t\t\t\texport_in_charging, fraction_charged_iso) = calculate_trna_charging(\n"
    "\t\t\t\tsynthetase_conc,\n"
    "\t\t\t\tuncharged_trna_conc,\n"
    "\t\t\t\tcharged_trna_conc,\n"
    "\t\t\t\taa_conc,\n"
    "\t\t\t\tribosome_conc,\n"
    "\t\t\t\tf,\n"
    "\t\t\t\tself.charging_params,\n"
    "\t\t\t\tsupply=supply_function,\n"
    "\t\t\t\tlimit_v_rib=True,\n"
    "\t\t\t\ttime_limit=self.process.timeStepSec(),\n"
    "\t\t\t\tuncharged_trna_conc_iso=iso_uncharged_trna_conc,\n"
    "\t\t\t\tcharged_trna_conc_iso=iso_charged_trna_conc,\n"
    "\t\t\t\treturn_iso=True)\n"
    "\t\telse:\n"
    "\t\t\tfraction_charged_iso = None\n"
    "\t\t\tfraction_charged, v_rib, synthesis_in_charging, import_in_charging, export_in_charging = calculate_trna_charging(\n"
    "\t\t\t\tsynthetase_conc,\n"
    "\t\t\t\tuncharged_trna_conc,\n"
    "\t\t\t\tcharged_trna_conc,\n"
    "\t\t\t\taa_conc,\n"
    "\t\t\t\tribosome_conc,\n"
    "\t\t\t\tf,\n"
    "\t\t\t\tself.charging_params,\n"
    "\t\t\t\tsupply=supply_function,\n"
    "\t\t\t\tlimit_v_rib=True,\n"
    "\t\t\t\ttime_limit=self.process.timeStepSec())\n"
)

# W10 -- the WRITE-BACK. This is the line that destroyed within-family information: it took the
# 21-wide fraction and BROADCAST it across each family. At isoacceptor resolution it consumes the
# per-species fraction instead. Counts are already written back at 86 everywhere downstream of here
# (charged_trna_request, uncharged_trna_request, total_charging_reactions, and the evolve() half all
# operate per species), so this single line is the whole of "write back at the resolution read".
WD_WRITE_OLD = (
    "\t\ttotal_trna = self.charged_trna.total_counts() + self.uncharged_trna.total_counts()\n"
    "\t\tfinal_charged_trna = stochasticRound(self.process.randomState, np.dot(fraction_charged, self.process.aa_from_trna * total_trna))\n"
)
WD_WRITE_NEW = (
    "\t\ttotal_trna = self.charged_trna.total_counts() + self.uncharged_trna.total_counts()\n"
    "\t\t# ROUTE1 step 2 (stage 5): the 86-wide per-species charged fraction. At family resolution it\n"
    "\t\t# is the unchanged family BROADCAST; at isoacceptor resolution the 85 charging-masked entries\n"
    "\t\t# are replaced by the genuine per-species values and selC keeps the broadcast value it has\n"
    "\t\t# today (its amino acid is not charging-masked, so calculate_trna_charging gives it the mean\n"
    "\t\t# of the others). Stashed on the model because PolypeptideElongation.calculateRequest writes\n"
    "\t\t# GrowthLimits/fraction_trna_charged and only receives the 21-wide return.\n"
    "\t\tself.fraction_trna_charged_iso = None\n"
    "\t\tif self.trna_resolution_iso:\n"
    "\t\t\tfraction_charged_trna = np.dot(fraction_charged, self.process.aa_from_trna)\n"
    "\t\t\tfraction_charged_trna[self.charging_params['trna_charging_mask']] = fraction_charged_iso\n"
    "\t\t\tself.fraction_trna_charged_iso = fraction_charged_trna\n"
    "\t\t\tfinal_charged_trna = stochasticRound(self.process.randomState, fraction_charged_trna * total_trna)\n"
    "\t\telse:\n"
    "\t\t\tfinal_charged_trna = stochasticRound(self.process.randomState, np.dot(fraction_charged, self.process.aa_from_trna * total_trna))\n"
)

# W11 -- the listener. GrowthLimits/fraction_trna_charged is ALREADY 86 wide and subcolumned by
# uncharged_trna_ids (growth_limits.py:94-95, ids bound :30), so NO COLUMN CHANGES SHAPE. What changes
# is the meaning: the column stops being a family broadcast and starts carrying per-species values.
# Every elongation model other than the steady-state one leaves the attribute unset, so getattr
# returns None and the original expression is what runs for them, unchanged.
WD_LIST_OLD = (
    "\t\tself.writeToListener(\"GrowthLimits\", \"fraction_trna_charged\", np.dot(fraction_charged, self.aa_from_trna))\n"
)
WD_LIST_NEW = (
    "\t\t# ROUTE1 step 2 (stage 5): at isoacceptor resolution this column carries GENUINE per-species\n"
    "\t\t# charged fractions instead of a family broadcast. Same 86-wide column, same subcolumn map --\n"
    "\t\t# no listener allocation changes -- so every downstream reader keeps working; the ones that\n"
    "\t\t# re-aggregate 86 -> 21 simply compute a real family mean where they used to compute an\n"
    "\t\t# identity. Models other than the steady-state one never set the attribute, so they run the\n"
    "\t\t# original expression.\n"
    "\t\tfraction_trna_charged = getattr(self.elongation_model, 'fraction_trna_charged_iso', None)\n"
    "\t\tif fraction_trna_charged is None:\n"
    "\t\t\tfraction_trna_charged = np.dot(fraction_charged, self.aa_from_trna)\n"
    "\t\tself.writeToListener(\"GrowthLimits\", \"fraction_trna_charged\", fraction_trna_charged)\n"
)

WIDEN_EDITS = (
    (REL, WD_SIG_OLD, WD_SIG_NEW, 1, "polypeptide_elongation.py: calculate_trna_charging signature"),
    (REL, WD_DOC_OLD, WD_DOC_NEW, 1, "polypeptide_elongation.py: docstring, new arguments"),
    (REL, WD_DOC2_OLD, WD_DOC2_NEW, 1, "polypeptide_elongation.py: docstring, sixth return value"),
    (REL, WD_GUARD_OLD, WD_GUARD_NEW, 1, "polypeptide_elongation.py: reject pools at family resolution"),
    (REL, WD_POOL_OLD, WD_POOL_NEW, 1, "polypeptide_elongation.py: accept genuine per-isoacceptor pools"),
    (REL, WD_FRAC_OLD, WD_FRAC_NEW, 1, "polypeptide_elongation.py: per-species charged fraction"),
    (REL, WD_RET_OLD, WD_RET_NEW, 1, "polypeptide_elongation.py: opt-in sixth return value"),
    (REL, WD_SUPPLY_OLD, WD_SUPPLY_NEW, 1, "polypeptide_elongation.py: supply-branch state offset (stage-4 defect)"),
    (REL, WD_COUNTS_OLD, WD_COUNTS_NEW, 1, "polypeptide_elongation.py: request reads per-species counts"),
    (REL, WD_CONC_OLD, WD_CONC_NEW, 1, "polypeptide_elongation.py: request per-species concentrations"),
    (REL, WD_CALL_OLD, WD_CALL_NEW, 1, "polypeptide_elongation.py: calculate_trna_charging call branch"),
    (REL, WD_WRITE_OLD, WD_WRITE_NEW, 1, "polypeptide_elongation.py: per-species charged write-back"),
    (REL, WD_LIST_OLD, WD_LIST_NEW, 1, "polypeptide_elongation.py: fraction_trna_charged listener"),
)


# ---------------------------------------------------------------------------------------------------
# STAGE 6 -- DOCUMENT THE DEGENERACY AT THE POINT OF CHOICE. No behaviour change whatsoever: two
# comment/help-text edits. It is a stage rather than a loose edit because the thing it records is the
# single most misreadable property of the switch, and a loose edit would not survive a revert cycle.
#
# THE DECISION THIS STAGE ENCODES. `abundance` stays the DEFAULT -- it is the conservative choice and
# it is the one that reproduces the 21-resolution answer. `equal` is the SCIENCE configuration. The
# degeneracy of `abundance` is REPORTED AS A FINDING, not hidden behind the default.
#
# THE FINDING. Nothing in the KINETICS distinguishes isoacceptors of the same family:
# `KMtf_trna = A2T @ trna_kms[aa_charging_mask]` with a one-hot A2T is a per-family BROADCAST, so its
# within-family spread is exactly 0.000e+00 -- structural, not measured-to-be-small. The consequence
# is a fixed-point argument, not a numerical accident:
#
#   * The ODE assembles `np.hstack((-dtrna, dtrna, daa, ...))`, so du_i/dt = -dtrna_i and
#     dc_i/dt = +dtrna_i and T_i = u_i + c_i is conserved EXACTLY, per species.
#   * At the fixed point dtrna_i = 0, i.e. v_i = v_rib * f_i, and with KMtf broadcast
#     v_i = (family_rate_a / KMtf_a) * u_i -- proportional to u_i.
#   * Under 'abundance', f_i = f_a * T_i/T_a, so u_i is proportional to T_i; T_i is conserved, so
#     c_i = T_i - u_i is proportional to T_i too and c_i/T_i is CONSTANT within the family. Uniform
#     charged fraction BY CONSTRUCTION.
#   * Under 'equal', f_i = f_a/n_a, so u_i is CONSTANT within the family and
#     c_i/T_i = 1 - u_const/T_i inherits the T_i heterogeneity. Spread develops -- but it comes from
#     POOL SIZES, still not from kinetics.
#
# MEASURED TWICE, real simulations, worst per-family spread over the 17 multi-member families -- a
# 40 s run and an independent 20 s re-measurement from the production listener column:
#
#                      40 s       20 s
#     family control   0.0        0.000e+00   (both splits)
#     iso + abundance  2.79e-7    2.16e-7     (numerically zero)
#     iso + equal      6.18e-2    6.63e-2
#
# The MAGNITUDE replicates; the per-family RANKING does not (40 s: GLY, LEU; 20 s: LYS, GLY, ALA), so
# the stage records no family order. Kinetic-model reference at 120 s: GLY 0.372 / LEU 0.241, ~7x
# larger than 'equal' produces.
# ---------------------------------------------------------------------------------------------------

MARKER_DEGEN = "ROUTE1 step 2 (stage 6): the abundance split's within-family degeneracy"

# D1 -- the CLI help text. Anchors on the APPLIED form of stage 2's E4, which is why this stage must
# revert BEFORE stage 2 does; `reversed(...)` in revert() gives that for free as long as DEGEN_EDITS
# stays last in the concatenation.
DG_CLI_OLD = (
    "\t\tself.define_option(parser, 'trna_demand_split', str,\n"
    "\t\t\tdefault='abundance',\n"
    "\t\t\thelp=\"how per-amino-acid elongation demand is divided among a family's isoacceptors at\"\n"
    "\t\t\t\t\" isoacceptor resolution: 'abundance' (default; an isoacceptor's share of demand is\"\n"
    "\t\t\t\t\" its share of the family tRNA pool) or 'equal'. NOT determined by the knowledge\"\n"
    "\t\t\t\t\" base -- TrnaCharging/reading_events sums to exactly 0.0 on every run on disk -- so\"\n"
    "\t\t\t\t\" it is an explicit modelling choice. Measured resolution ratio r = D_86/D_21:\"\n"
    "\t\t\t\t\" abundance 1.2713 (operons on) / 1.2423 (off), equal 1.3283 / 1.3195; gap ~4.5%.\"\n"
    "\t\t\t\t\" Inert at family resolution.\")\n"
)
DG_CLI_NEW = (
    "\t\t# ROUTE1 step 2 (stage 6): the abundance split's within-family degeneracy is stated in the\n"
    "\t\t# help text itself, not only in docs/ROUTE1_VERIFICATION.md. Someone choosing a split at the\n"
    "\t\t# command line must not have to rediscover that the DEFAULT cannot produce within-family\n"
    "\t\t# spread -- that is a property of the fixed point, not a small number that might grow.\n"
    "\t\tself.define_option(parser, 'trna_demand_split', str,\n"
    "\t\t\tdefault='abundance',\n"
    "\t\t\thelp=\"how per-amino-acid elongation demand is divided among a family's isoacceptors at\"\n"
    "\t\t\t\t\" isoacceptor resolution. 'abundance' is the DEFAULT and the conservative choice (an\"\n"
    "\t\t\t\t\" isoacceptor's share of demand is its share of the family tRNA pool); 'equal' is the\"\n"
    "\t\t\t\t\" SCIENCE configuration. NOT determined by the knowledge base --\"\n"
    "\t\t\t\t\" TrnaCharging/reading_events sums to exactly 0.0 on every run on disk -- so it is an\"\n"
    "\t\t\t\t\" explicit modelling choice. READ BEFORE CHOOSING: at 'abundance' the within-family\"\n"
    "\t\t\t\t\" charged fraction is UNIFORM BY CONSTRUCTION, not merely small. KMtf_trna is\"\n"
    "\t\t\t\t\" broadcast per family (within-family spread exactly 0.000e+00), so nothing in the\"\n"
    "\t\t\t\t\" kinetics tells isoacceptors of a family apart; the fixed point then has u_i\"\n"
    "\t\t\t\t\" proportional to T_i = u_i + c_i, which the ODE conserves exactly, so c_i/T_i is\"\n"
    "\t\t\t\t\" constant inside a family. Under 'equal' u_i is constant instead and c_i/T_i\"\n"
    "\t\t\t\t\" inherits the T_i heterogeneity -- spread from POOL SIZES, still not from kinetics.\"\n"
    "\t\t\t\t\" MEASURED worst per-family spread over 17 multi-member families, real sims, twice:\"\n"
    "\t\t\t\t\" family control exactly 0.0 (both splits); abundance 2.79e-7 at 40 s / 2.16e-7 at\"\n"
    "\t\t\t\t\" 20 s (numerically zero); equal 6.18e-2 at 40 s / 6.63e-2 at 20 s. The MAGNITUDE\"\n"
    "\t\t\t\t\" replicates; the per-family RANKING does NOT (40 s: GLY 5.13e-2, LEU 3.07e-2;\"\n"
    "\t\t\t\t\" 20 s: LYS 6.63e-2, GLY 6.05e-2, ALA 4.06e-2), so do not cite a family order.\"\n"
    "\t\t\t\t\" Kinetic-model reference at 120 s: GLY 0.372 / LEU 0.241 -- about 7x larger than\"\n"
    "\t\t\t\t\" 'equal' produces. If you need within-family structure you must select 'equal';\"\n"
    "\t\t\t\t\" the default will not give it to you. Measured resolution\"\n"
    "\t\t\t\t\" ratio r = D_86/D_21: abundance 1.2713 (operons on) / 1.2423 (off), equal 1.3283 /\"\n"
    "\t\t\t\t\" 1.3195; gap ~4.5%. Inert at family resolution.\")\n"
)

# D2 -- the same statement in the ROUTE1 comment block above get_charging_params, inserted BEFORE the
# provenance caveat so the block still ends on what is unmeasured. Anchors on the last two lines of
# BLOCK, so stage 1's revert (a literal replace of BLOCK) only matches again once this stage is undone
# -- which the reverse-order revert loop guarantees.
DG_BLOCK_OLD = (
    "# CAVEAT ON PROVENANCE. Only 3 of the 8 ParCa trees on disk have charging-enabled output, and every\n"
    "# charging run is 121 rows / 120 s of GENERATION 0 ONLY. Full-generation drift in r is UNMEASURED.\n"
)
DG_BLOCK_NEW = (
    "# ROUTE1 step 2 (stage 6): the abundance split's within-family degeneracy -- REPORTED, NOT HIDDEN.\n"
    "# 'abundance' remains the DEFAULT because it is conservative and reproduces the 21-resolution\n"
    "# answer; 'equal' is the SCIENCE configuration. What the default cannot do is a structural fact:\n"
    "#\n"
    "#   Nothing in the KINETICS distinguishes isoacceptors of one family. KMtf_trna is built as\n"
    "#   `A2T @ trna_kms[aa_charging_mask]` with a ONE-HOT A2T, i.e. a per-family BROADCAST, so its\n"
    "#   within-family spread is exactly 0.000e+00 -- structural, not measured-to-be-small.\n"
    "#\n"
    "#   The ODE returns `np.hstack((-dtrna, dtrna, daa, ...))`, so du_i/dt = -dtrna_i and\n"
    "#   dc_i/dt = +dtrna_i: T_i = u_i + c_i is conserved EXACTLY, per species. At the fixed point\n"
    "#   dtrna_i = 0 gives v_i = v_rib*f_i, and with KMtf broadcast v_i = (family_rate_a/KMtf_a)*u_i,\n"
    "#   proportional to u_i.\n"
    "#\n"
    "#     abundance: f_i = f_a * T_i/T_a  =>  u_i proportional to T_i  =>  c_i = T_i - u_i also\n"
    "#       proportional to T_i  =>  c_i/T_i CONSTANT within the family. The charged fraction is\n"
    "#       uniform BY CONSTRUCTION. It is not a finding about E. coli; it is the fixed point.\n"
    "#     equal:     f_i = f_a/n_a  =>  u_i CONSTANT within the family  =>  c_i/T_i = 1 - u/T_i,\n"
    "#       which inherits the T_i heterogeneity. Spread develops -- but from POOL SIZES, not from\n"
    "#       kinetics. No configuration of this model makes kinetics discriminate isoacceptors.\n"
    "#\n"
    "# MEASURED TWICE, real simulations, worst per-family spread in GrowthLimits/fraction_trna_charged\n"
    "# over the 17 multi-member families -- 40 s, and an independent 20 s re-measurement:\n"
    "#\n"
    "#                       40 s       20 s\n"
    "#     family control    0.0        0.000e+00   (both splits: inert at family resolution)\n"
    "#     iso + abundance   2.79e-7    2.16e-7     (numerically zero -- solver residual)\n"
    "#     iso + equal       6.18e-2    6.63e-2\n"
    "#\n"
    "# THE MAGNITUDE REPLICATES; THE PER-FAMILY RANKING DOES NOT. 40 s put GLY 5.13e-2 and LEU 3.07e-2\n"
    "# on top; 20 s puts LYS 6.63e-2, GLY 6.05e-2, ALA 4.06e-2, with LEU outside the top three. Do not\n"
    "# cite a family order from this: it moves with run length, which is what a quantity driven by\n"
    "# transient POOL SIZES rather than by a fixed parameter should do.\n"
    "#\n"
    "# Kinetic-model reference at 120 s: GLY 0.372 / LEU 0.241 -- about 7x larger than 'equal'\n"
    "# produces. So 'equal' moves in the right direction and does not arrive. An earlier reading that\n"
    "# 'equal' reproduces the kinetic model's RANK ORDERING did not survive the second measurement and\n"
    "# is withdrawn; see docs/ROUTE1_VERIFICATION.md section 8.\n"
    "#\n"
    "# CAVEAT ON PROVENANCE. Only 3 of the 8 ParCa trees on disk have charging-enabled output, and every\n"
    "# charging run is 121 rows / 120 s of GENERATION 0 ONLY. Full-generation drift in r is UNMEASURED.\n"
)

DEGEN_EDITS = (
    (SB, DG_CLI_OLD, DG_CLI_NEW, 1, "scriptBase.py: --trna-demand-split help states the degeneracy"),
    (REL, DG_BLOCK_OLD, DG_BLOCK_NEW, 1, "polypeptide_elongation.py: degeneracy in the ROUTE1 block"),
)


# ---------------------------------------------------------------------------------------------------
# STAGE 7 -- the provenance caveat is now FALSE and must be corrected in place.
#
# Stages 1 and 6 both end the ROUTE1 block on "every charging run is 121 rows / 120 s of GENERATION 0
# ONLY". That was true when it was written. It is not true now: a 3 arms x 3 seeds x 3 full
# generations matrix (27 cells, real divisions, all exit 0, no NaN) exists on disk. Leaving the old
# sentence there is exactly the silent-stale-fact failure this file's discipline exists to prevent --
# a reader would re-derive a limitation that has been closed, or worse, trust it.
#
# The replacement does NOT simply claim the caveat is gone. It records what the matrix covered and,
# separately, what it did NOT: r-drift itself was never measured across generations, so that clause
# survives verbatim. Comment text only; no behaviour change.
#
# Anchors on the two caveat lines, which are the applied form of stage 6 (they are the tail of
# DG_BLOCK_NEW). Stage 7 must therefore revert BEFORE stage 6, which the reverse-order revert loop
# gives for free as long as GEN_EDITS stays last in the concatenation.
# ---------------------------------------------------------------------------------------------------

MARKER_GEN = "ROUTE1 step 2 (stage 7): seeds AND generations -- the 3x3x3 matrix"

GEN_BLOCK_OLD = DG_BLOCK_OLD
GEN_BLOCK_NEW = (
    "# ROUTE1 step 2 (stage 7): seeds AND generations -- the 3x3x3 matrix. The line that used to sit\n"
    "# here (\"every charging run is 121 rows / 120 s of GENERATION 0 ONLY\") is NO LONGER TRUE and has\n"
    "# been corrected rather than left to be re-derived.\n"
    "#\n"
    "# MEASURED: 3 arms (family control / isoacceptor+abundance / isoacceptor+equal) x 3 seeds (0,1,2)\n"
    "# x 3 FULL generations to natural division -- 27 cells, 2499-3310 timesteps each (2498-3309 s),\n"
    "# every cell wrote daughter state, mass ratio 1.70-2.53, all 9 chains exit 0, ZERO NaN in\n"
    "# fraction_trna_charged / ppgpp_conc / rela_syn / instantaneous_growth_rate / cellMass. Generations\n"
    "# 1-2 ran through SimulationDaughterTask, so they also verify the two switches survive the daughter\n"
    "# path. Distribution of the worst-family spread PER TIMESTEP (a max over ~3000 steps is not a\n"
    "# level), medians pooled over the 3 seeds of each generation:\n"
    "#\n"
    "#                       gen0       gen1       gen2      timesteps > 1e-2\n"
    "#     family control    0.000e+00  0.000e+00  0.000e+00      0 of 24807\n"
    "#     iso + abundance   4.7e-8     1.8e-7     2.7e-7         0 of 25493\n"
    "#     iso + equal       5.2e-2     5.7e-2     6.6e-2     25931 of 25931\n"
    "#\n"
    "# The family control is EXACTLY zero at every one of ~24800 timesteps -- median, p99 and max alike.\n"
    "# 'abundance' is numerically zero and never once exceeds 1e-2. 'equal' exceeds 1e-2 at EVERY\n"
    "# timestep, and its median 5.2e-2..6.6e-2 brackets the earlier 6.18e-2 (40 s) / 6.63e-2 (20 s), so\n"
    "# the magnitude claim now holds across seeds AND generations. Generation effect exists and is\n"
    "# immaterial: abundance's median rises ~6x and equal's ~27% from gen0 to gen2.\n"
    "#\n"
    "# THE PER-FAMILY RANKING IS STILL NOT ESTABLISHED -- it now moves by GENERATION as well as by run\n"
    "# length (gen0 LYS 7.27e-2, gen1 ALA 8.93e-2, gen2 LEU 7.38e-1), which strengthens the withdrawal\n"
    "# above rather than weakening it.\n"
    "#\n"
    "# BETWEEN-ARM DIFFERENCES IN GROWTH ARE CHAOS, NOT EFFECT, and this was measured rather than\n"
    "# assumed. Mean doubling times of 46.0 / 50.3 / 49.9 min invite the reading that isoacceptor\n"
    "# resolution slows the cell. Step-by-step, 'abundance' is EXACTLY equal to the family control for\n"
    "# the first two timesteps and departs at 2e-10 -- the shared-synthetase reduction holding in\n"
    "# production -- then amplifies to 3.0e-2 (seed 0) and 1.1e-1 (seed 2) over ~3000 steps. With n = 3\n"
    "# seeds those arm differences are NOT evidence of a systematic effect of the switch.\n"
    "#\n"
    "# WHAT REMAINS UNMEASURED, stated so it is not assumed closed: only 3 of the 8 ParCa trees on disk\n"
    "# have charging-enabled output; the matrix is --trna-charging (SteadyState + ppGpp) ONLY, so the\n"
    "# ROUTE1-21 occupancy A/B and the r measurements above are STILL generation-0 only; and\n"
    "# full-generation drift in r ITSELF was not measured here -- the matrix measured spread, growth,\n"
    "# ppGpp and relA, not r. See docs/ROUTE1_VERIFICATION.md section 9.5.\n"
)

GEN_EDITS = (
    (REL, GEN_BLOCK_OLD, GEN_BLOCK_NEW, 1,
     "polypeptide_elongation.py: correct the now-false generation-0-only caveat"),
)

# ALL_EDITS is the single ordered list revert() walks (in reverse), so a stage can never be applied by
# run() and forgotten by revert(). DEGEN_EDITS stays LAST: it anchors on text stages 1 and 2 wrote.
#
# EDIT_GROUPS is the same edits carved into STAGES, which run() needs and revert() does not. run()
# must be able to skip a stage WHOLESALE, because per-edit "is the applied form present?" idempotence
# is unsound across stages that rewrite each other -- stage 5 rewrites regions stage 4 introduced, so
# several stage-4 applied forms genuinely do not survive into a fully-applied tree. GROUP_STATUS_KEYS
# maps each group to the status() keys that must ALL be true for the group to count as applied; None
# means "compute it", because stages 2 and 3 share the PLUMBING tuple and stage 2's keys are per file.
EDIT_GROUPS = (
    ("plumbing", PLUMBING),
    ("rhs", RHS_EDITS),
    ("widen", WIDEN_EDITS),
    ("degeneracy", DEGEN_EDITS),
    ("generations", GEN_EDITS),
)

GROUP_STATUS_KEYS = {
    "plumbing": None,
    "rhs": ("rhs",),
    "widen": ("widen",),
    "degeneracy": ("degeneracy_cli", "degeneracy_block"),
    "generations": ("generations_block",),
}

ALL_EDITS = tuple(e for _gname, _edits in EDIT_GROUPS for e in _edits)

# The two views must not drift apart: an edit reachable by run() but not by revert() would be applied
# and never undone, which is precisely the failure the marker/revert discipline exists to prevent.
assert set(GROUP_STATUS_KEYS) == {_g for _g, _e in EDIT_GROUPS}, (
    "EDIT_GROUPS and GROUP_STATUS_KEYS disagree about which stages exist")
assert ALL_EDITS == PLUMBING + RHS_EDITS + WIDEN_EDITS + DEGEN_EDITS + GEN_EDITS, (
    "EDIT_GROUPS does not reproduce the apply order revert() reverses")

# Guard against an accidental re-indent of the constants above: wcEcoli is tab-indented throughout,
# and a stray space-indented line would apply cleanly and then fail to parse inside the model image.
for _rel, _old, _new, _n, _label in RHS_EDITS + WIDEN_EDITS + DEGEN_EDITS + GEN_EDITS:
    for _line in (_old + _new).split("\n"):
        if _line.startswith(" "):
            raise AssertionError("space-indented line in RHS constants: {!r}".format(_line))

# Every stage needs its OWN marker, and the marker must be a string this stage ALONE introduces.
# MARKER_WIDEN appears in ten of the twelve edits above; assert that it is genuinely present in the
# applied form of at least one of them, so a future rename of the marker fails here rather than
# turning status() into a permanent False and re-running the stage on an already-patched tree.
assert any(MARKER_WIDEN in _new for _rel, _old, _new, _n, _label in WIDEN_EDITS), (
    "MARKER_WIDEN does not appear in any stage-5 replacement text")
assert not any(MARKER_WIDEN in _old for _rel, _old, _new, _n, _label in WIDEN_EDITS), (
    "MARKER_WIDEN appears in stage-5 ANCHOR text; status() could never report unapplied")

# Stage 6, same discipline. It lands in TWO files, and status() reports each separately, so require
# the marker in the applied form of BOTH edits -- a marker present in only one would let a
# half-applied stage read as fully applied, the same bug the per-file plumbing keys once had.
assert all(MARKER_DEGEN in _new for _rel, _old, _new, _n, _label in DEGEN_EDITS), (
    "MARKER_DEGEN is missing from at least one stage-6 replacement text")
assert not any(MARKER_DEGEN in _old for _rel, _old, _new, _n, _label in DEGEN_EDITS), (
    "MARKER_DEGEN appears in stage-6 ANCHOR text; status() could never report unapplied")
# The stage-6 anchors are the APPLIED forms of earlier stages. Assert that relationship here rather
# than discovering it as a mid-apply "found 0 occurrences": DG_CLI_OLD must be exactly what stage 2
# writes, and DG_BLOCK_OLD must be text that BLOCK actually contains.
assert DG_CLI_OLD in SB_OPT_NEW, (
    "DG_CLI_OLD is not the applied form of stage 2's CLI edit; stage 6 could never anchor")
assert DG_BLOCK_OLD in BLOCK, (
    "DG_BLOCK_OLD is not present in BLOCK; stage 6 could never anchor")

# Stage 7, same discipline as 5 and 6.
assert all(MARKER_GEN in _new for _rel, _old, _new, _n, _label in GEN_EDITS), (
    "MARKER_GEN is missing from stage-7 replacement text")
assert not any(MARKER_GEN in _old for _rel, _old, _new, _n, _label in GEN_EDITS), (
    "MARKER_GEN appears in stage-7 ANCHOR text; status() could never report unapplied")
# Stage 7 anchors on the TAIL of stage 6's applied text. Assert that relationship here rather than
# discovering it as a mid-apply "found 0 occurrences" -- and assert it against BLOCK too, so the
# stage still anchors on a tree where stage 6 has been reverted but stage 1 has not.
assert GEN_BLOCK_OLD in DG_BLOCK_NEW, (
    "GEN_BLOCK_OLD is not the tail of stage 6's applied block; stage 7 could never anchor")
assert GEN_BLOCK_OLD in BLOCK, (
    "GEN_BLOCK_OLD is not present in BLOCK; stage 7 could never anchor on a stage-6-reverted tree")


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
    # Each STAGE needs its own marker, not just each file. Stage 3 lands in a file that stage 2
    # already marked, so a file-level check reported "already applied" and silently skipped it --
    # the same class of bug as the per-file idempotence check inside run().
    pe = os.path.join(wcecoli, REL)
    pe_txt = _read(pe)[0] if os.path.isfile(pe) else ""
    st["params_dict"] = MARKER_PARAMS in pe_txt
    # Stage 4 lands in the SAME file as stages 1-3, so it needs its own marker for exactly the
    # reason recorded above: a per-file check reports "already applied" and skips it silently.
    st["rhs"] = MARKER_RHS in pe_txt
    st["forwarding"] = MARKER_FORWARD in pe_txt
    # Stage 5 lands in the SAME file as stages 1-4 and edits regions stage 4 created, so it needs its
    # own marker for the same reason as every stage before it.
    st["widen"] = MARKER_WIDEN in pe_txt
    # Stage 6 lands in TWO files and is reported per file, for the same reason stage 2 is: a
    # half-applied documentation stage (help text updated, comment block not) must read as partial.
    sb_txt = _read(os.path.join(wcecoli, SB))[0] if os.path.isfile(os.path.join(wcecoli, SB)) else ""
    st["degeneracy_cli"] = MARKER_DEGEN in sb_txt
    st["degeneracy_block"] = MARKER_DEGEN in pe_txt
    # Stage 7 rewrites the tail of the block stage 6 wrote, in the SAME file every stage since 1 has
    # touched, so it needs its own marker for the same reason as all of them.
    st["generations_block"] = MARKER_GEN in pe_txt
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

    # STAGES 2-6. Each edit states how many occurrences it expects and refuses to proceed on any
    # other count, so a file that has drifted fails loudly instead of being patched blind or
    # silently skipped. Stages 4 and 5 ride the same loop deliberately: they get the same
    # anchor-count discipline for free, and each applies after the text it anchors on exists --
    # stage 4 after the params dict it reads, stage 5 after the RHS branch it widens.
    #
    # GROUP-LEVEL SKIP, and the bug that forced it. Per-EDIT idempotence ("is the applied form
    # present verbatim?") stops being sound the moment one stage REWRITES text an earlier stage
    # introduced -- which is exactly what stage 5 does to stage 4. On a fully stage-1..5 tree several
    # stage-4 applied forms no longer exist verbatim, so the loop hit `found 0 -- refusing to guess`
    # on RHS_INIT and could not reach a later stage at all. It stayed invisible only because
    # `all(st.values())` short-circuited above; adding stage 6 removed that mask and the defect
    # surfaced immediately. The fix is to skip a whole EDIT GROUP that status() already reports
    # applied, and to keep the per-edit content check for any group that is NOT -- so a half-applied
    # group still gets edit-by-edit anchor counting rather than a blind pass.
    for gname, edits in EDIT_GROUPS:
        keys = GROUP_STATUS_KEYS[gname]
        if keys is None:
            # Stages 2 and 3 share one edit tuple, so the group is "applied" only when every marker
            # they introduce is present -- every per-file plumbing key AND the two stage-3 markers.
            keys = tuple(k for k in st if k.startswith("plumbing_")) + ("params_dict", "forwarding")
        if keys and all(st.get(k) for k in keys):
            continue
        for rel, old, new, n_expected, label in edits:
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

    # STAGES 6, 5, 4, 3, 2 then 1 -- the reverse of the order run() applies them. The ordering stopped
    # being cosmetic at stage 5: several of its anchors are text stage 4 INTRODUCED (the uniform pool
    # expansion, the T2A aggregation, the dcdt call), so reverting stage 4 first would leave stage 5
    # unmatched and the tree half-patched. Stage 6 makes it doubly load-bearing: it rewrites stage 2's
    # CLI help text and inserts into stage 1's comment BLOCK, and stage 1's revert is a literal
    # replace of BLOCK that matches nothing until stage 6 is undone. Reverse order, not symmetry.
    for rel, old, new, n_expected, label in reversed(ALL_EDITS):
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
