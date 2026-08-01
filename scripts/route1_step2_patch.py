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

STAGES NOT YET APPLIED: widening the CALLERS to pass genuinely per-isoacceptor pools (until that
lands the isoacceptor path reproduces the family answer — see the comment at the pool expansion),
and the listener widening.

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

# Guard against an accidental re-indent of the constants above: wcEcoli is tab-indented throughout,
# and a stray space-indented line would apply cleanly and then fail to parse inside the model image.
for _rel, _old, _new, _n, _label in RHS_EDITS:
    for _line in (_old + _new).split("\n"):
        if _line.startswith(" "):
            raise AssertionError("space-indented line in RHS constants: {!r}".format(_line))


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

    # STAGES 2-4. Each edit states how many occurrences it expects and refuses to proceed on any
    # other count, so a file that has drifted fails loudly instead of being patched blind or
    # silently skipped. Stage 4 (the 85-resolution RHS) rides the same loop deliberately: it gets
    # the same anchor-count discipline for free, and it applies after the params dict it reads.
    for rel, old, new, n_expected, label in PLUMBING + RHS_EDITS:
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

    # STAGES 4, 3, 2 then 1 -- the reverse of the order run() applies them. The stages do not
    # overlap textually today, so the ordering is for symmetry rather than necessity; reverting in
    # apply order would be a latent hazard the moment a later stage anchors inside an earlier one,
    # and stage 4's RHS anchors sit a few lines from stage 3's params dict in the same file.
    for rel, old, new, n_expected, label in reversed(PLUMBING + RHS_EDITS):
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
