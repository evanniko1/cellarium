"""EXT-PORT-11 -- bring the tRNA charging OPTIMISER into this tree and make the charged-fraction
target a PARAMETER.

Idempotent, marker-guarded, CRLF/TAB preserving, in the style of scripts/apply_trna_port.py and
scripts/ext_port_10_patch.py. Every anchor is asserted to match EXACTLY ONCE before anything is
written; a partial application reports as partial rather than as done.

    python ext_port_11_patch.py --wcecoli C:/dev/wcEcoli --check
    python ext_port_11_patch.py --wcecoli C:/dev/wcEcoli

PROVENANCE OF THE ANCHORS. They were not typed out. The edits were made and VERIFIED first (a
full Parca rebuild, a 5533-row objective regression, and a single-synthetase fit), and the
(old, new) pairs below were then extracted by difflib from the verified tree against the same
tree before the edits, expanding context until each anchor matched exactly once. Re-verify at
any time: take the six files at the commit before this one, apply this module, and diff against
the current ones -- they compare byte for byte, and a second application is a no-op.

WHAT IT DOES, in five parts.

(1) THE BLOCKER: sim_data.codon_read_rate had no producer. EXT-PORT-1 created the empty dict on
    SimulationDataEcoli and stopped there; the producer lives in v3.0.1 fit_sim_data_1.py, which
    is not in vendor/v301. It is v_usage -- the entire right-hand side of the steady-state
    condition the tRNA charging fit minimises against -- so `optimize_trna_charging_kinetics`
    raised KeyError on its first synthetase. calculateTranslationSupply now returns it alongside
    translation_aa_supply and fit_condition stashes it per medium, exactly as v3.0.1 does
    (fit_sim_data_1.py:1088-1097 and :287-289 there).

    The one place this could have gone silently wrong is index space: relation.codon_counts must
    be in monomer_data order to be multiplied by proteinCounts. It is (relation.py builds it by
    iterating translation.monomer_data['id']), and the port asserts it rather than assuming it.

(2) THE OPTIMISER HAD NO CALLER. The method itself was already ported and is byte-identical to
    v3.0.1 bar one numpy-2 fix, but nothing invoked it, `self.conditions` was never set, and the
    module-level `print_optimization` switch it reads at three points was never brought across
    (a NameError on the first sweep level). This adds the Parca step function, the
    --optimize-trna-charging-kinetics flag, and the pass-through in both Firetasks -- which
    Fireworks requires, because it RAISES on an unknown kwarg.

(3) THE ANCHOR. The port phase established that `f` is NOT a target and never was: it is a free
    decision variable, bounded only by a box and a 1e-9 barrier, written to disk and read by
    nothing. So this ADDS a fifth error term rather than changing an existing target. The target
    is a PARAMETER with a documented default of `none` (= no anchor, i.e. v3.0.1 behaviour), is
    expressible per condition, and every named candidate carries its medium, temperature,
    doubling time, method and DOI at its definition in relation.py.

    The nested `objective` closure is lifted to a module-level `trna_charging_objective` with the
    weights made explicit arguments. That is what makes it regression-testable: see
    scripts/verify_trna_objective.py, which re-evaluates it at all 5533 shipped solution vectors
    and reproduces the shipped `objective` column to a worst relative error of 2.9e-12.

(4) THE LAST OPERONS-ON GAP, in Relation.get_constants. v3.0.1 read each tRNA abundance with
    `bulkAverageContainer.count(trna)` on CISTRON-space ids -- correct only with operons OFF. With
    operons ON the Parca container holds RNA counts in TRANSCRIPTION-UNIT space, so 77 of the 86
    tRNA ids read as EXACTLY ZERO; only the 9 monocistronic tRNA genes survive. Measured: 18 of 20
    synthetases had a zero-abundance tRNA, 14 had all of them zero.

    It does not fail quietly but it fails badly. c_trna = 0 -> saturation_trnas = 0 -> a divide by
    zero in get_random_initial_solution -> k_cat = inf -> NaN v_charge -> every restart rejected by
    the feasibility filter. The restart loop is `while (iteration < iterations) or (viable_solution
    < viable_solutions)`, so with nothing ever accepted IT NEVER TERMINATES: observed as a 36-minute
    hang on ONE synthetase, with no error and no output.

    The conversion is not invented here -- `transcription.calculate_attenuation` already does this
    exact job on the operons-ON path, with an identical volume expression, at transcription.py
    :1518-1524. This is that code. After the fix all 20 synthetases have non-zero constants and
    trpT reads 1.358 uM basal, against 3.684 uM at 2022 fit time and 1.11-1.17 uM measured in a
    kinetic simulation -- so it corroborates the trpT shortfall by a third, independent route.

(5) DEFAULT-PATH INVARIANCE. With the flag absent the Parca runs the same fit as before: measured
    by rebuilding the knowledge base and diffing 20 fitted structures (rna_expression,
    rna_synth_prob, monomer_data, trna_to_K_T, codon_sequences, ...) -- 0 changed. sim_data does
    gain a populated codon_read_rate (25 media x 63 codons) and relation.conditions, so
    simData.cPickle is NOT byte-identical and kb_sha256 changes; no simulated quantity does.

WHAT THE ANCHOR ACTUALLY DOES, measured, before anyone spends hours on a refit. On TrpRS at sweep
level 4 (30 restarts, seed 0 -- a SCOUTING budget, not a fit), target 0.55:
    w_a = 0     -> basal charged 0.803   (the unanchored fit)
    w_a = 1e-6  -> 0.796
    w_a = 1e-5  -> 0.782
    w_a = 1e-4  -> 0.776
    w_a = 1e-3  -> 0.773     (anchor term is then 99% of the objective)
It is a soft preference, not a constraint: three orders of magnitude of weight buy 0.03 of charged
fraction and it saturates around 0.77, nowhere near 0.55. Zeroing the barrier (w_b = 0) does not
change that. On this evidence the feasible set the hard filter admits does not appear to contain a
0.55 solution for TrpRS at the current tRNA abundance -- but 30 restarts cannot distinguish "not
found" from "does not exist", and this is n=1 synthetase. Note also that `with_aa`, left unanchored
by every candidate, wanders 0.73-0.94 across those same runs, which is what a genuinely free
variable looks like.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys

REL = os.path.join('reconstruction', 'ecoli', 'dataclasses', 'relation.py')
FSD = os.path.join('reconstruction', 'ecoli', 'fit_sim_data_1.py')
SD = os.path.join('reconstruction', 'ecoli', 'simulation_data.py')
SB = os.path.join('wholecell', 'utils', 'scriptBase.py')
PT = os.path.join('wholecell', 'fireworks', 'firetasks', 'parca.py')
FT = os.path.join('wholecell', 'fireworks', 'firetasks', 'fitSimData.py')


REL_01_MARK = 'Accepts:'
REL_01_OLD = 'KINETIC_TRNA_CHARGING_WIDTH_BUFFER = 10\n\n'
REL_01_NEW = 'KINETIC_TRNA_CHARGING_WIDTH_BUFFER = 10\n\n# EXT-PORT-11: v3.0.1 module-level switch for the optimiser\'s per-iteration trace. It is READ at\n# three points inside optimize_trna_charging_kinetics (vendor relation.py:957, :1005, :1146) and was\n# never brought across with the method, so calling the optimiser in this tree raised\n# `NameError: name \'print_optimization\' is not defined` on the first sweep level. Same silent-absence\n# class as EXT-PORT-1\'s missing imports: it is invisible until the code path actually runs.\nprint_optimization = False\n\n\n# =====================================================================================================\n# EXT-PORT-11 --- the tRNA CHARGED-FRACTION ANCHOR\n# =====================================================================================================\n#\n# WHAT WAS THERE BEFORE, MEASURED. In v3.0.1 the charged fraction is neither a target nor a\n# constraint of the fit. `f` is the FREE fraction (charged = 1 - f) and it is a FREE DECISION\n# VARIABLE: one element per (condition, K_T group), plus a second copy `min_f` at the swept-down\n# minimum synthetase, unpacked from the candidate vector alongside k_cat, K_A and K_T\n# (trna_charging_objective below). Together f and min_f are the MAJORITY of the free parameters --\n# 8 of 12 for AlaRS, 16 of 22 for ArgRS, 20 of 27 for LeuRS. The only things acting on it are a box\n# bound f in (0.051, 0.949) and a barrier penalty at weight 1e-9. Nothing measured enters the\n# objective at all. The fitted value is written to flat/optimization/\n# trna_charging_kinetics_solutions.tsv (column `f_free`) and to flat/trna_charging_kinetics.tsv\n# (columns `f basal` / `f with_aa`), loaded back into `trna_condition_to_free_fraction`, and then\n# READ BY NOTHING -- in v3.0.1 as well as here. The simulation consumes only k_cat, K_A and K_T.\n#\n# WHY IT FLOATS. In the regime this model sits in, tRNA saturation is ~21%, so\n# v_charge ~= k_cat * E * sat_A * (f * c_trna / K_T). The steady-state condition therefore\n# identifies only the PRODUCT k_cat * f / K_T; f, k_cat and K_T are jointly degenerate and the\n# objective structurally cannot separate them. Anchoring f is what breaks that degeneracy and turns\n# k_cat/K_T from a gauge choice into an identified quantity.\n#\n# WHAT THIS ADDS. A fourth error term, off by default, that pulls the ABUNDANCE-WEIGHTED MEAN\n# charged fraction of one synthetase\'s tRNAs toward a per-condition target. It does NOT replace the\n# barrier -- see the note on `bounds_penalty_weight` in optimize_trna_charging_kinetics.\n#\n# SCALE, WHICH IS THE PART THAT BITES. At the shipped optima the TOTAL objective is ~1e-7 and is\n# 94-99% penalty, not error: the hard feasibility filter (max|v_charge - v_usage| <= 1e-3, applied\n# as an accept/reject after the minimisation, not inside it) drives the steady-state residual to\n# ~1e-9, so what actually SELECTS among the feasible solutions is w_r * sum(K_T). Decomposed from\n# the shipped sweep-level-4 rows (objective | w_r*sumK_T | w_b*barrier | residual):\n#     ALAS-CPLX[c]      8.122e-08 | 2.589e-08 | 5.051e-08 | 4.8e-09\n#     ARGS-MONOMER[c]   9.817e-07 | 6.497e-07 | 3.216e-07 | 1.0e-08\n#     TRPS-CPLX[c]      4.338e-08 | 8.749e-09 | 3.368e-08 | 9.5e-10\n#     LEUS-MONOMER[c]   7.060e-07 | 7.676e-08 | 6.195e-07 | 9.8e-09\n# An anchor term must be scaled against ~1e-7 or it is either invisible or totally dominant. The\n# default weight below is derived from that arithmetic and is documented at its definition.\n#\n# ---------------------------------------------------------------------------------------------------\n# THE TARGETS. Deliberately a REGISTRY of named candidates rather than a constant, because the\n# candidates conflict and the choice is scientific, not technical. NONE of them is selected by\n# default: the default is `none`, which reproduces v3.0.1 exactly. Selecting a target is an explicit\n# act on the command line and it is recorded in the output file header.\n#\n# Every entry is per condition, because the measurements are condition-specific. `None` for a\n# condition means NO CONDITION-MATCHED MEASUREMENT EXISTS and that condition\'s f is left free --\n# which is the honest state of `with_aa` for all four candidates below. Do not fill those in with\n# the basal number to make the table look complete; that is exactly how a fitted number gets\n# mistaken for a measured one.\nTRNA_CHARGED_FRACTION_TARGETS = {\n\n\t# The default. No anchor: `f` stays a free variable, bounded only by the box and the barrier,\n\t# exactly as in Choi & Covert 2023 / WholeCellEcoliRelease v3.0.1.\n\t\'none\': None,\n\n\t# (A) MEASURED, and the only one whose growth condition matches this model\'s `basal`.\n\t#     Avcilar-Kucukgoze et al. 2016, Nucleic Acids Research 44(17):8324-8334,\n\t#     doi:10.1093/nar/gkw697.\n\t#     Medium   M9 + 0.4% glucose (minimal, no amino acids)\n\t#     Temp     37 C\n\t#     Doubling 43.3 min\n\t#     Method   periodate-protection microarray, corroborated by acid-urea northern blot\n\t#     Reported "oscillates around 50-60%" aggregate charged fraction; 0.55 is the midpoint.\n\t#     KNOWN OBJECTION: Choi & Covert single this dataset out as running systematically low,\n\t#     in places exceeding 100%. That objection is not adjudicated here.\n\t\'avcilar_kucukgoze_2016\': {\'basal\': 0.55, \'with_aa\': None},\n\n\t# (B) MEASURED, but in a different medium from this model\'s `basal`.\n\t#     Dittmar et al. 2005, EMBO Reports 6(2):151-157, doi:10.1038/sj.embor.7400341.\n\t#     Medium   MOPS + glycerol\n\t#     Temp     37 C\n\t#     Doubling not condition-matched to `basal`\n\t#     Method   acid-urea northern blot\n\t#     Five Leu isoacceptors unperturbed at 0.80 / 0.77 / 0.68 / 0.76 / 0.84; 0.77 is the median.\n\t#     This is a per-isoacceptor Leu measurement being used as a proteome-wide aggregate target.\n\t\'dittmar_2005\': {\'basal\': 0.77, \'with_aa\': None},\n\n\t# (C) NOT A MEASUREMENT -- a MODEL OUTPUT. Choi & Covert 2023, NAR 51(12):5911,\n\t#     doi:10.1093/nar/gkad435, published aggregate charged fraction, which this port already\n\t#     reproduces at end-of-generation (0.7845 measured on operonsON_kin_probe, n=1 seed,\n\t#     1 generation). Anchoring here changes almost nothing and validates the port rather than\n\t#     the biology. Included so that "reproduce the paper" is an explicit, labelled choice.\n\t\'choi_covert_2023\': {\'basal\': 0.788, \'with_aa\': None},\n\n\t# (D) NOT A MEASUREMENT -- an extrapolation. The classic "80-90% charged", quoted and then\n\t#     explicitly REJECTED by Avcilar-Kucukgoze et al. 2016 as an extrapolation from three\n\t#     papers, one of which is a method paper on mutant initiator tRNAs. It is included because\n\t#     it is nearest to what the shipped constants already imply (basal 0.832 abundance-weighted\n\t#     at the default sweep level 4), so leaving it out would hide how close the status quo is\n\t#     to the weakest-evidenced candidate.\n\t\'classic_80_90\': {\'basal\': 0.85, \'with_aa\': None},\n\t}\n\n# The documented default: NO ANCHOR. Chosen so that (i) the port stays byte-faithful to v3.0.1 and\n# the shipped constants remain reproducible, and (ii) no target is adopted implicitly. Changing this\n# default is a scientific decision and must be argued in the commit that makes it.\nTRNA_CHARGED_FRACTION_TARGET_DEFAULT = \'none\'\n\n# Weight on the anchor term, w_a. Derived, not guessed, from the decomposition above:\n#   - the term that currently SELECTS the solution is w_r * sum(K_T), which lands at 8.7e-09\n#     (TRPS) to 6.5e-07 (ARGS) at the shipped optima;\n#   - the anchor\'s squared deviation is O(0.01-0.08) for a target 0.1-0.3 away from where the fit\n#     currently lands (shipped basal aggregate 0.832 vs candidate 0.55 gives 0.0795);\n#   - so w_a = 1e-6 puts the anchor at 1e-08 to 8e-08 -- the same order as the regulariser, able to\n#     move f without swamping K_T selection.\n# This is a STARTING POINT, not a fitted value. Any refit must report the four-way decomposition of\n# the objective at its optima (the optimiser prints it when `print_optimization` is True) and show\n# that the anchor is neither invisible nor dominant. Override with --trna-charged-fraction-weight.\nTRNA_CHARGED_FRACTION_WEIGHT_DEFAULT = 1e-6\n\n\ndef resolve_charged_fraction_target(spec):\n\t"""EXT-PORT-11. Normalise a charged-fraction anchor spec into {condition: target or None}.\n\n\tAccepts:\n\t  None                     -> the documented default (TRNA_CHARGED_FRACTION_TARGET_DEFAULT)\n\t  a key of TRNA_CHARGED_FRACTION_TARGETS, e.g. \'avcilar_kucukgoze_2016\' or \'none\'\n\t  an explicit spec string, e.g. \'basal=0.55,with_aa=0.6\' or \'basal=0.55,with_aa=none\'\n\t  a dict {condition: float or None}, passed through after validation\n\n\tReturns a dict; conditions mapped to None are left UNANCHORED. An unrecognised name raises\n\trather than falling back to \'none\', because a typo that silently disables the anchor would\n\tproduce a run that looks anchored in the shell history and is not.\n\t"""\n\tif spec is None:\n\t\tspec = TRNA_CHARGED_FRACTION_TARGET_DEFAULT\n\n\tif isinstance(spec, str):\n\t\tif spec in TRNA_CHARGED_FRACTION_TARGETS:\n\t\t\tspec = TRNA_CHARGED_FRACTION_TARGETS[spec]\n\t\telif \'=\' in spec:\n\t\t\tparsed = {}\n\t\t\tfor item in spec.split(\',\'):\n\t\t\t\tif not item.strip():\n\t\t\t\t\tcontinue\n\t\t\t\tcondition, _, value = item.partition(\'=\')\n\t\t\t\tvalue = value.strip()\n\t\t\t\tparsed[condition.strip()] = (\n\t\t\t\t\tNone if value.lower() in (\'\', \'none\', \'free\') else float(value))\n\t\t\tspec = parsed\n\t\telse:\n\t\t\traise ValueError(\n\t\t\t\t\'unknown charged-fraction target {!r}. Known names: {}. Or give an explicit \'\n\t\t\t\t\'per-condition spec such as "basal=0.55,with_aa=none".\'.format(\n\t\t\t\t\tspec, sorted(TRNA_CHARGED_FRACTION_TARGETS)))\n\n\tif spec is None:\n\t\treturn {}\n\n\tif not isinstance(spec, dict):\n\t\traise TypeError(\'charged-fraction target must be a name, a "cond=value" string, a dict, \'\n\t\t\t\'or None; got {!r}\'.format(type(spec)))\n\n\tresolved = {}\n\tfor condition, value in spec.items():\n\t\tif value is None:\n\t\t\tresolved[condition] = None\n\t\t\tcontinue\n\t\tvalue = float(value)\n\t\t# The box bound on f is (0.051, 0.949), so charged fraction is representable only inside\n\t\t# the same interval. A target outside it is unreachable by construction and would show up\n\t\t# as a constant offset in the anchor error rather than as an error.\n\t\tif not 0.051 < value < 0.949:\n\t\t\traise ValueError(\n\t\t\t\t\'charged-fraction target for {!r} is {}, outside the (0.051, 0.949) box that `f` \'\n\t\t\t\t\'is bounded to; it is unreachable and would silently bias the fit.\'.format(\n\t\t\t\t\tcondition, value))\n\t\tresolved[condition] = value\n\treturn resolved\n\n\ndef trna_charging_objective(x, indexes, maps, v_codons, c_synthetase, c_synthetase_min,\n\t\tc_amino_acid, c_trnas, w_r, w_b, w_a, anchor_targets, anchor_min_f):\n\t"""Objective minimised by Relation.optimize_trna_charging_kinetics.\n\n\tEXT-PORT-11 adaptation: this was a CLOSURE inside optimize_trna_charging_kinetics in v3.0.1\n\t(vendor relation.py:617-712), capturing `w_r` and `w_b` from the enclosing scope. It is lifted\n\tto module level with those two made explicit arguments, for two reasons: the anchor needs its\n\town weight and target passed in the same way, and a closure cannot be regression-tested. The\n\tarithmetic of the four v3.0.1 terms is unchanged -- verified numerically by\n\tscripts/verify_trna_objective.py, which re-evaluates this function at every shipped solution\n\tvector and reproduces the shipped `objective` column.\n\n\tTerms, in the order they are summed:\n\t  1. steady_state_error      at the mean synthetase concentration        (v3.0.1)\n\t  2. min_steady_state_error  at the swept-down minimum synthetase        (v3.0.1)\n\t  3. w_r * sum(K_T)          regulariser -- the term that actually selects among the\n\t                             (heavily underdetermined) feasible solutions               (v3.0.1)\n\t  4. w_b * bounds_penalty    barrier keeping f inside (0.05, 0.95). NOTE: it is symmetric about\n\t                             f = 0.5, so it has an accidental, un-cited preference for a 50%\n\t                             charged fraction, and it is 40-88% of the total objective at the\n\t                             shipped optima. It is a numerical bound-repeller, not evidence.\n\t                             (v3.0.1)\n\t  5. w_a * anchor_error      EXT-PORT-11. Zero and exactly inert when no condition carries a\n\t                             target, which is the default.\n\t"""\n\n\t# Pre-conditioning\n\tx = np.power(10, x)\n\n\t# Parse candidate solution\n\tk_cat = x[indexes[\'k_cat_index\']]\n\tK_A = x[indexes[\'K_A_index\']]\n\tK_T = x[indexes[\'K_T_slice\']]\n\tf = x[indexes[\'f_slice\']]\n\tmin_f = x[indexes[\'min_f_slice\']]\n\n\t############################################################\n\n\t# Calculate charging rate of each free trna\n\tsaturation_amino_acid = c_amino_acid / (K_A + c_amino_acid)\n\trelative_trnas = ((maps[\'f_to_cases\'] @ f)\n\t\t* c_trnas\n\t\t/ (maps[\'K_T_to_cases\'] @ K_T))\n\ttrna_sum = maps[\'cases_to_trna_sum\'] @ relative_trnas\n\tsaturation_trnas = relative_trnas / (1 + trna_sum)\n\tv_charge = (k_cat\n\t\t* c_synthetase\n\t\t* saturation_amino_acid\n\t\t* saturation_trnas)\n\n\t# Calculate distribution of codon reading across trnas\n\t# Note: columns of codons_to_trnas sum to 1\n\tc_trnas_charged = (1 - (maps[\'f_to_cases\'] @ f)) * c_trnas\n\ttile = np.tile(c_trnas_charged, (len(v_codons), 1)).T\n\tcodons_to_trnas = np.where(maps[\'codon_cases_to_trna_cases\'], tile, 0)\n\tdenominator = codons_to_trnas.sum(axis=0)\n\tdenominator[denominator == 0] = 1 # to prevent divide by 0\n\tcodons_to_trnas = np.divide(codons_to_trnas, denominator)\n\n\t# Calculate usage rate of each charged trna\n\tv_usage = codons_to_trnas @ v_codons\n\n\t# Steady-state cost\n\tsteady_state_error = np.sum(\n\t\tnp.square(\n\t\t\t1 - (v_charge / v_usage)\n\t\t\t)\n\t\t)\n\n\t############################################################\n\n\t# Calculate charging rate of each free trna\n\trelative_trnas = ((maps[\'f_to_cases\'] @ min_f)\n\t\t* c_trnas\n\t\t/ (maps[\'K_T_to_cases\'] @ K_T))\n\ttrna_sum = maps[\'cases_to_trna_sum\'] @ relative_trnas\n\tsaturation_trnas = relative_trnas / (1 + trna_sum)\n\tv_charge_min = (k_cat\n\t\t* c_synthetase_min\n\t\t* saturation_amino_acid\n\t\t* saturation_trnas)\n\n\t# Calculate distribution of codon reading across trnas\n\t# Note: columns of codons_to_trnas sum to 1\n\tc_trnas_charged = (1 - (maps[\'f_to_cases\'] @ min_f)) * c_trnas\n\ttile = np.tile(c_trnas_charged, (len(v_codons), 1)).T\n\tcodons_to_trnas = np.where(maps[\'codon_cases_to_trna_cases\'], tile, 0)\n\tdenominator = codons_to_trnas.sum(axis=0)\n\tdenominator[denominator == 0] = 1 # to prevent divide by 0\n\tcodons_to_trnas = np.divide(codons_to_trnas, denominator)\n\n\t# Calculate usage rate of each charged trna\n\tv_usage_min = codons_to_trnas @ v_codons\n\n\t# Steady-state cost\n\tmin_steady_state_error = np.sum(\n\t\tnp.square(\n\t\t\t1 - (v_charge_min / v_usage_min)\n\t\t\t)\n\t\t)\n\n\t############################################################\n\n\t# Bounds penalty\n\tbounds_penalty = sum((1 / (f - 0.05)) + (1 / (0.95 - f)))\n\tbounds_penalty += sum((1 / (min_f - 0.05)) + (1 / (0.95 - min_f)))\n\n\t############################################################\n\n\t# EXT-PORT-11: charged-fraction anchor.\n\t#\n\t# The target is an AGGREGATE (the published numbers are proteome-wide aggregate charged\n\t# fractions), but the optimiser solves one amino-acid system at a time, so it is applied here as\n\t# the abundance-weighted mean charged fraction of THIS synthetase\'s tRNAs, per condition. If\n\t# every system hits its target the proteome-wide aggregate equals the target; if they do not,\n\t# the residual is visible per synthetase rather than hidden in a global sum. Weighting by\n\t# c_trnas is what makes the per-system mean comparable to a bulk measurement, which is a\n\t# pool-weighted quantity, not a per-isoacceptor average.\n\t#\n\t# Applied to `f` only, NOT to `min_f`, unless anchor_min_f is set. min_f is the charged fraction\n\t# at a swept-down minimum synthetase abundance -- a robustness margin, a regime the cell is by\n\t# construction NOT in when the measurement was taken. Anchoring it to a measured value would be\n\t# a category error. The switch exists so that choice is visible rather than implicit.\n\t#\n\t# `anchor_targets` is empty by default, so anchor_error is exactly 0.0 and adding\n\t# (w_a * 0.0) to `errors` leaves the sum bit-identical to v3.0.1.\n\tif len(anchor_targets):\n\t\tcharged = 1 - (maps[\'f_to_cases\'] @ f)\n\t\tpool = maps[\'cases_to_anchored_conditions\'] @ c_trnas\n\t\tanchor_error = np.sum(np.square(\n\t\t\t((maps[\'cases_to_anchored_conditions\'] @ (charged * c_trnas)) / pool)\n\t\t\t- anchor_targets))\n\n\t\tif anchor_min_f:\n\t\t\tcharged = 1 - (maps[\'f_to_cases\'] @ min_f)\n\t\t\tanchor_error += np.sum(np.square(\n\t\t\t\t((maps[\'cases_to_anchored_conditions\'] @ (charged * c_trnas)) / pool)\n\t\t\t\t- anchor_targets))\n\telse:\n\t\tanchor_error = 0.0\n\n\t############################################################\n\n\terrors = [\n\n\t\t# Steady state errors\n\t\tsteady_state_error,\n\t\tmin_steady_state_error,\n\n\t\t# Penalties\n\t\t(w_r * sum(K_T)),\n\t\t(w_b * bounds_penalty),\n\n\t\t# EXT-PORT-11 anchor (0.0 unless a target was selected)\n\t\t(w_a * anchor_error),\n\n\t\t]\n\n\terror = sum(errors)\n\n\treturn error\n\n'

REL_02_MARK = 'iterations=100,'
REL_02_OLD = '\tdef optimize_trna_charging_kinetics(self, sim_data, cell_specs):\n'
REL_02_NEW = '\tdef optimize_trna_charging_kinetics(self, sim_data, cell_specs,\n\t\t\tcharged_fraction_target=None,\n\t\t\tcharged_fraction_weight=None,\n\t\t\tanchor_min_f=False,\n\t\t\tregularization_weight=1e-9,\n\t\t\tbounds_penalty_weight=1e-9,\n\t\t\titerations=100,\n\t\t\tviable_solutions=10):\n'

REL_03_MARK = 'keywords is the upstream fit:'
REL_03_OLD = "\t\t  exponentially and doubles at the measured doubling time.\n\t\t'''\n"
REL_03_NEW = "\t\t  exponentially and doubles at the measured doubling time.\n\n\t\tEXT-PORT-11 parameters. All five default to the v3.0.1 behaviour, so calling this with no\n\t\tkeywords is the upstream fit:\n\n\t\tcharged_fraction_target -- the anchor. A key of TRNA_CHARGED_FRACTION_TARGETS, an explicit\n\t\t\t'basal=0.55,with_aa=none' string, a dict, or None for the documented default ('none',\n\t\t\ti.e. no anchor). See the EXT-PORT-11 block at the top of this module for the candidates\n\t\t\tand their provenance. It is a PARAMETER and not a constant because the candidates\n\t\t\tconflict and the choice is scientific.\n\t\tcharged_fraction_weight -- w_a. None takes TRNA_CHARGED_FRACTION_WEIGHT_DEFAULT (1e-6),\n\t\t\twhose derivation is documented at that constant.\n\t\tanchor_min_f -- also anchor the charged fraction at the swept-down minimum synthetase.\n\t\t\tDefault False: that regime is a robustness margin, not a measured condition.\n\t\tregularization_weight -- w_r. The term that ACTUALLY selects among feasible solutions\n\t\t\t(min sum K_T), and therefore the one an anchor competes with. Exposed so a refit can\n\t\t\treport the trade rather than assert it. Default is the shipped 1e-9.\n\t\tbounds_penalty_weight -- w_b. The barrier is symmetric about f = 0.5, so it carries an\n\t\t\taccidental, un-cited pull toward a 50% charged fraction and is 40-88% of the objective\n\t\t\tat the shipped optima. When an anchor is on, two terms are then acting on f. This is\n\t\t\tNOT zeroed automatically -- doing so silently would change the numerical conditioning\n\t\t\tof a fit whose feasibility is enforced by a hard filter. Set it to 0.0 explicitly to\n\t\t\tlet the anchor act alone, and say so in the run's provenance. Default is the shipped\n\t\t\t1e-9.\n\t\titerations, viable_solutions -- the random-restart budget per (synthetase, sweep level).\n\t\t\tShipped values are 100 and 10; the loop runs `while iteration < iterations or\n\t\t\tviable_solution < viable_solutions`, so the cost of a full fit is >= 8080 Powell\n\t\t\tminimisations and order hours SERIALLY (there is no multiprocessing in this method).\n\t\t\tExposed ONLY so a scouting run is possible before committing that time -- e.g.\n\t\t\titerations=3, viable_solutions=1 finishes a single synthetase in seconds. A scouting\n\t\t\trun is NOT a fit: with 3 restarts the optimiser has not searched, and its output must\n\t\t\tnever be adopted as constants. Anything published must use the shipped budget.\n\t\t'''\n"

REL_04_MARK = 'objective = trna_charging_objective'
REL_04_OLD = "\t\tdef objective(x,\n\t\t\tindexes,\n\t\t\tmaps,\n\t\t\tv_codons,\n\t\t\tc_synthetase,\n\t\t\tc_synthetase_min,\n\t\t\tc_amino_acid,\n\t\t\tc_trnas,\n\t\t\t):\n\n\t\t\t# Pre-conditioning\n\t\t\tx = np.power(10, x)\n\n\t\t\t# Parse candidate solution\n\t\t\tk_cat = x[indexes['k_cat_index']]\n\t\t\tK_A = x[indexes['K_A_index']]\n\t\t\tK_T = x[indexes['K_T_slice']]\n\t\t\tf = x[indexes['f_slice']]\n\t\t\tmin_f = x[indexes['min_f_slice']]\n\n\t\t\t############################################################\n\n\t\t\t# Calculate charging rate of each free trna\n\t\t\tsaturation_amino_acid = c_amino_acid / (K_A + c_amino_acid)\n\t\t\trelative_trnas = ((maps['f_to_cases'] @ f)\n\t\t\t\t* c_trnas\n\t\t\t\t/ (maps['K_T_to_cases'] @ K_T))\n\t\t\ttrna_sum = maps['cases_to_trna_sum'] @ relative_trnas\n\t\t\tsaturation_trnas = relative_trnas / (1 + trna_sum)\n\t\t\tv_charge = (k_cat\n\t\t\t\t* c_synthetase\n\t\t\t\t* saturation_amino_acid\n\t\t\t\t* saturation_trnas)\n\n\t\t\t# Calculate distribution of codon reading across trnas\n\t\t\t# Note: columns of codons_to_trnas sum to 1\n\t\t\tc_trnas_charged = (1 - (maps['f_to_cases'] @ f)) * c_trnas\n\t\t\ttile = np.tile(c_trnas_charged, (len(v_codons), 1)).T\n\t\t\tcodons_to_trnas = np.where(maps['codon_cases_to_trna_cases'], tile, 0)\n\t\t\tdenominator = codons_to_trnas.sum(axis=0)\n\t\t\tdenominator[denominator == 0] = 1 # to prevent divide by 0\n\t\t\tcodons_to_trnas = np.divide(codons_to_trnas, denominator)\n\n\t\t\t# Calculate usage rate of each charged trna\n\t\t\tv_usage = codons_to_trnas @ v_codons\n\n\t\t\t# Steady-state cost\n\t\t\tsteady_state_error = np.sum(\n\t\t\t\tnp.square(\n\t\t\t\t\t1 - (v_charge / v_usage)\n\t\t\t\t\t)\n\t\t\t\t)\n\n\t\t\t############################################################\n\n\t\t\t# Calculate charging rate of each free trna\n\t\t\trelative_trnas = ((maps['f_to_cases'] @ min_f)\n\t\t\t\t* c_trnas\n\t\t\t\t/ (maps['K_T_to_cases'] @ K_T))\n\t\t\ttrna_sum = maps['cases_to_trna_sum'] @ relative_trnas\n\t\t\tsaturation_trnas = relative_trnas / (1 + trna_sum)\n\t\t\tv_charge_min = (k_cat\n\t\t\t\t* c_synthetase_min\n\t\t\t\t* saturation_amino_acid\n\t\t\t\t* saturation_trnas)\n\n\t\t\t# Calculate distribution of codon reading across trnas\n\t\t\t# Note: columns of codons_to_trnas sum to 1\n\t\t\tc_trnas_charged = (1 - (maps['f_to_cases'] @ min_f)) * c_trnas\n\t\t\ttile = np.tile(c_trnas_charged, (len(v_codons), 1)).T\n\t\t\tcodons_to_trnas = np.where(maps['codon_cases_to_trna_cases'], tile, 0)\n\t\t\tdenominator = codons_to_trnas.sum(axis=0)\n\t\t\tdenominator[denominator == 0] = 1 # to prevent divide by 0\n\t\t\tcodons_to_trnas = np.divide(codons_to_trnas, denominator)\n\n\t\t\t# Calculate usage rate of each charged trna\n\t\t\tv_usage_min = codons_to_trnas @ v_codons\n\n\t\t\t# Steady-state cost\n\t\t\tmin_steady_state_error = np.sum(\n\t\t\t\tnp.square(\n\t\t\t\t\t1 - (v_charge_min / v_usage_min)\n\t\t\t\t\t)\n\t\t\t\t)\n\n\t\t\t############################################################\n\n\t\t\t# Bounds penalty\n\t\t\tbounds_penalty = sum((1 / (f - 0.05)) + (1 / (0.95 - f)))\n\t\t\tbounds_penalty += sum((1 / (min_f - 0.05)) + (1 / (0.95 - min_f)))\n\n\t\t\t############################################################\n\n\t\t\terrors = [\n\n\t\t\t\t# Steady state errors\n\t\t\t\tsteady_state_error,\n\t\t\t\tmin_steady_state_error,\n\n\t\t\t\t# Penalties\n\t\t\t\t(w_r * sum(K_T)),\n\t\t\t\t(w_b * bounds_penalty),\n\n\t\t\t\t]\n\n\t\t\terror = sum(errors)\n\n\t\t\treturn error\n"
REL_04_NEW = '\t\tobjective = trna_charging_objective\n'

REL_05_MARK = 'if unknown_conditions:'
REL_05_OLD = '\t\tw_b = 1e-9 # bounds\n\t\tw_r = 1e-9 # regularization\n'
REL_05_NEW = "\t\t# EXT-PORT-11: these were hard-coded literals in v3.0.1. They are now the defaults of the\n\t\t# two keyword arguments, so the values are unchanged for every existing caller and a refit\n\t\t# can vary them without editing the model source.\n\t\tw_b = bounds_penalty_weight # bounds\n\t\tw_r = regularization_weight # regularization\n\n\t\t# EXT-PORT-11: the charged-fraction anchor. Resolved ONCE, here, so that an unknown target\n\t\t# name fails before any of the ~8080 minimisations start rather than hours in.\n\t\tcharged_fraction_target = resolve_charged_fraction_target(charged_fraction_target)\n\t\tw_a = (TRNA_CHARGED_FRACTION_WEIGHT_DEFAULT if charged_fraction_weight is None\n\t\t\telse float(charged_fraction_weight))\n\n\t\tunknown_conditions = sorted(set(charged_fraction_target) - set(self.conditions))\n\t\tif unknown_conditions:\n\t\t\traise ValueError(\n\t\t\t\t'charged-fraction target names condition(s) {} that this fit does not solve; it '\n\t\t\t\t'solves {}. A target for a condition that is never optimised is silently '\n\t\t\t\t'ignored, so this is an error rather than a warning.'.format(\n\t\t\t\t\tunknown_conditions, list(self.conditions)))\n\n\t\tanchored_conditions = [condition for condition in self.conditions\n\t\t\tif charged_fraction_target.get(condition) is not None]\n\t\tanchor_targets = np.array(\n\t\t\t[charged_fraction_target[condition] for condition in anchored_conditions],\n\t\t\tdtype=np.float64)\n\n\t\tprint('EXT-PORT-11 charged-fraction anchor: {}'.format(\n\t\t\t'OFF (f is a free variable, as in v3.0.1)' if not anchored_conditions\n\t\t\telse '{} (w_a={:g}, w_r={:g}, w_b={:g}, anchor_min_f={})'.format(\n\t\t\t\t{c: charged_fraction_target[c] for c in anchored_conditions},\n\t\t\t\tw_a, w_r, w_b, anchor_min_f)))\n"

REL_06_MARK = '# EXT-PORT-11: were hard-coded literals in v3.0.1; now the defaults of two keyword'
REL_06_OLD = '\t\titerations = 100\n\t\tviable_solutions = 10\n'
REL_06_NEW = '\t\t# EXT-PORT-11: were hard-coded literals in v3.0.1; now the defaults of two keyword\n\t\t# arguments, so every existing caller gets the same budget and a scouting run is possible.\n'

REL_07_MARK = 'for col, case in enumerate(cases):'
REL_07_OLD = '\n\t\t\tmaps = {\n'
REL_07_NEW = "\n\t\t\t# EXT-PORT-11: (n_anchored_conditions, n_cases) selector used by the anchor term to\n\t\t\t# form the abundance-weighted mean charged fraction of this synthetase's tRNAs, one\n\t\t\t# row per condition that carries a target. Built here rather than inside the objective\n\t\t\t# because it is constant across the ~100 restarts x 4 sweep levels of this synthetase.\n\t\t\t#\n\t\t\t# It is deliberately (0, n_cases) when nothing is anchored -- the empty case is then\n\t\t\t# the same code path, not a special case, and the anchor error is exactly 0.0.\n\t\t\t#\n\t\t\t# `case.split('__')` is safe: cases are f'{trna}__{condition}' and neither a tRNA id\n\t\t\t# nor 'with_aa' contains a double underscore. The v3.0.1 code above relies on the same\n\t\t\t# invariant (see the three loops just above).\n\t\t\tcases_to_anchored_conditions = np.zeros(\n\t\t\t\t(len(anchored_conditions), n_cases), dtype=np.int64)\n\t\t\tfor row, anchored_condition in enumerate(anchored_conditions):\n\t\t\t\tfor col, case in enumerate(cases):\n\t\t\t\t\tif case.split('__')[1] == anchored_condition:\n\t\t\t\t\t\tcases_to_anchored_conditions[row, col] = 1\n\t\t\tassert (len(anchored_conditions) == 0\n\t\t\t\tor cases_to_anchored_conditions.sum() == len(anchored_conditions) * len(trnas)), (\n\t\t\t\t'the anchor selector did not match every tRNA of every anchored condition')\n\n\t\t\tmaps = {\n"

REL_08_MARK = "'cases_to_anchored_conditions': cases_to_anchored_conditions,"
REL_08_OLD = "\t\t\t\t'codon_cases_to_trna_cases': codon_cases_to_trna_cases,\n\t\t\t\t}\n"
REL_08_NEW = "\t\t\t\t'codon_cases_to_trna_cases': codon_cases_to_trna_cases,\n\t\t\t\t'cases_to_anchored_conditions': cases_to_anchored_conditions,\n\t\t\t\t}\n"

REL_09_MARK = '# EXT-PORT-11: weights and anchor, formerly closed over / absent.'
REL_09_OLD = '\t\t\t\t\t\tc_trnas,\n\t\t\t\t\t\t),\n'
REL_09_NEW = '\t\t\t\t\t\tc_trnas,\n\t\t\t\t\t\t# EXT-PORT-11: weights and anchor, formerly closed over / absent.\n\t\t\t\t\t\tw_r,\n\t\t\t\t\t\tw_b,\n\t\t\t\t\t\tw_a,\n\t\t\t\t\t\tanchor_targets,\n\t\t\t\t\t\tanchor_min_f,\n\t\t\t\t\t\t),\n'

REL_10_MARK = 'min_objective_x = None'
REL_10_OLD = '\t\t\t\tmin_objective = np.inf\n\t\t\t\tviable_solution = 0\n'
REL_10_NEW = '\t\t\t\tmin_objective = np.inf\n\t\t\t\t# EXT-PORT-11: the argmin, kept so the objective can be DECOMPOSED after the\n\t\t\t\t# restart loop. Without it the run reports a scalar and the question the anchor\n\t\t\t\t# exists to answer -- is the anchor invisible, comparable, or dominant against\n\t\t\t\t# w_r*sum(K_T)? -- cannot be answered from the output at all.\n\t\t\t\tmin_objective_x = None\n\t\t\t\tviable_solution = 0\n'

REL_11_MARK = '# EXT-PORT-11: weights and anchor (full-AA-saturation branch).'
REL_11_OLD = "\t\t\t\t\t\t\targs=(\n\t\t\t\t\t\t\t\tindexes,\n\t\t\t\t\t\t\t\tmaps,\n\t\t\t\t\t\t\t\tv_codons,\n\t\t\t\t\t\t\t\tc_synthetase,\n\t\t\t\t\t\t\t\tc_synthetase_min,\n\t\t\t\t\t\t\t\tc_amino_acid,\n\t\t\t\t\t\t\t\tc_trnas,\n\t\t\t\t\t\t\t\t),\n\t\t\t\t\t\t\toptions={\n\t\t\t\t\t\t\t\t'maxiter': 1000,\n\t\t\t\t\t\t\t\t'ftol': 1e-5,\n\t\t\t\t\t\t\t\t},\n\t\t\t\t\t\t\t)\n\n\n"
REL_11_NEW = "\t\t\t\t\t\t\targs=(\n\t\t\t\t\t\t\t\tindexes,\n\t\t\t\t\t\t\t\tmaps,\n\t\t\t\t\t\t\t\tv_codons,\n\t\t\t\t\t\t\t\tc_synthetase,\n\t\t\t\t\t\t\t\tc_synthetase_min,\n\t\t\t\t\t\t\t\tc_amino_acid,\n\t\t\t\t\t\t\t\tc_trnas,\n\t\t\t\t\t\t\t\t# EXT-PORT-11: weights and anchor (full-AA-saturation branch).\n\t\t\t\t\t\t\t\tw_r,\n\t\t\t\t\t\t\t\tw_b,\n\t\t\t\t\t\t\t\tw_a,\n\t\t\t\t\t\t\t\tanchor_targets,\n\t\t\t\t\t\t\t\tanchor_min_f,\n\t\t\t\t\t\t\t\t),\n\t\t\t\t\t\t\toptions={\n\t\t\t\t\t\t\t\t'maxiter': 1000,\n\t\t\t\t\t\t\t\t'ftol': 1e-5,\n\t\t\t\t\t\t\t\t},\n\t\t\t\t\t\t\t)\n\n\n"

REL_12_MARK = '# EXT-PORT-11: weights and anchor (partial-AA-saturation branch).'
REL_12_OLD = "\t\t\t\t\t\t\targs=(\n\t\t\t\t\t\t\t\tindexes,\n\t\t\t\t\t\t\t\tmaps,\n\t\t\t\t\t\t\t\tv_codons,\n\t\t\t\t\t\t\t\tc_synthetase,\n\t\t\t\t\t\t\t\tc_synthetase_min,\n\t\t\t\t\t\t\t\tc_amino_acid,\n\t\t\t\t\t\t\t\tc_trnas,\n\t\t\t\t\t\t\t\t),\n\t\t\t\t\t\t\toptions={\n\t\t\t\t\t\t\t\t'maxiter': 1000,\n\t\t\t\t\t\t\t\t'ftol': 1e-5,\n\t\t\t\t\t\t\t\t},\n\t\t\t\t\t\t\t)\n\n\t\t\t\t\t# Retrieve solution\n"
REL_12_NEW = "\t\t\t\t\t\t\targs=(\n\t\t\t\t\t\t\t\tindexes,\n\t\t\t\t\t\t\t\tmaps,\n\t\t\t\t\t\t\t\tv_codons,\n\t\t\t\t\t\t\t\tc_synthetase,\n\t\t\t\t\t\t\t\tc_synthetase_min,\n\t\t\t\t\t\t\t\tc_amino_acid,\n\t\t\t\t\t\t\t\tc_trnas,\n\t\t\t\t\t\t\t\t# EXT-PORT-11: weights and anchor (partial-AA-saturation branch).\n\t\t\t\t\t\t\t\tw_r,\n\t\t\t\t\t\t\t\tw_b,\n\t\t\t\t\t\t\t\tw_a,\n\t\t\t\t\t\t\t\tanchor_targets,\n\t\t\t\t\t\t\t\tanchor_min_f,\n\t\t\t\t\t\t\t\t),\n\t\t\t\t\t\t\toptions={\n\t\t\t\t\t\t\t\t'maxiter': 1000,\n\t\t\t\t\t\t\t\t'ftol': 1e-5,\n\t\t\t\t\t\t\t\t},\n\t\t\t\t\t\t\t)\n\n\t\t\t\t\t# Retrieve solution\n"

REL_13_MARK = 'min_objective_x = np.copy(result.x)   # EXT-PORT-11, see above'
REL_13_OLD = '\t\t\t\t\t\tmin_objective = result.fun\n\n'
REL_13_NEW = '\t\t\t\t\t\tmin_objective = result.fun\n\t\t\t\t\t\tmin_objective_x = np.copy(result.x)   # EXT-PORT-11, see above\n\n'

REL_14_MARK = 'term_b, term_a,'
REL_14_OLD = '\n\t\treturn trna_charging_kinetics_solutions, trna_charging_kinetics_constants\n'
REL_14_NEW = "\n\t\t\t\t# EXT-PORT-11: decompose the best objective of this (synthetase, sweep level).\n\t\t\t\t#\n\t\t\t\t# One line per group, 80 lines for a whole fit. It is printed UNCONDITIONALLY\n\t\t\t\t# rather than under `print_optimization`, because the shipped solutions file\n\t\t\t\t# records only the scalar `objective` and the decomposition is the number that\n\t\t\t\t# decides whether an anchor is doing anything: at the shipped optima the total is\n\t\t\t\t# ~1e-7 and 94-99% of it is penalty, not error. A run whose anchor term is 1e-12\n\t\t\t\t# is unanchored in fact whatever the command line said.\n\t\t\t\t#\n\t\t\t\t# Each term is obtained by RE-EVALUATING the real objective with the other weights\n\t\t\t\t# zeroed, rather than by reimplementing the arithmetic here -- a second copy of the\n\t\t\t\t# formula is a second thing to keep in step.\n\t\t\t\tif min_objective_x is not None:\n\t\t\t\t\tcommon = (indexes, maps, v_codons, c_synthetase, c_synthetase_min,\n\t\t\t\t\t\tc_amino_acid, c_trnas)\n\t\t\t\t\tno_anchor = np.array([], dtype=np.float64)\n\t\t\t\t\tresidual = objective(min_objective_x, *common,\n\t\t\t\t\t\t0.0, 0.0, 0.0, no_anchor, anchor_min_f)\n\t\t\t\t\tterm_r = objective(min_objective_x, *common,\n\t\t\t\t\t\tw_r, 0.0, 0.0, no_anchor, anchor_min_f) - residual\n\t\t\t\t\tterm_b = objective(min_objective_x, *common,\n\t\t\t\t\t\t0.0, w_b, 0.0, no_anchor, anchor_min_f) - residual\n\t\t\t\t\tterm_a = objective(min_objective_x, *common,\n\t\t\t\t\t\t0.0, 0.0, w_a, anchor_targets, anchor_min_f) - residual\n\t\t\t\t\tx_best = np.power(10, min_objective_x)\n\t\t\t\t\tf_best = x_best[indexes['f_slice']]\n\t\t\t\t\tcharged_best = 1 - (maps['f_to_cases'] @ f_best)\n\t\t\t\t\taggregate = ((maps['cases_to_trna_sum'] @ (charged_best * c_trnas))\n\t\t\t\t\t\t/ (maps['cases_to_trna_sum'] @ c_trnas))\n\t\t\t\t\tprint('EXT-PORT-11 {} level {}: obj {:.4e} = residual {:.3e} + w_r*sumK_T '\n\t\t\t\t\t\t'{:.3e} + w_b*barrier {:.3e} + w_a*anchor {:.3e}; charged(weighted) {}'\n\t\t\t\t\t\t.format(synthetase, sweep_level, min_objective, residual, term_r,\n\t\t\t\t\t\t\tterm_b, term_a,\n\t\t\t\t\t\t\t{condition: round(float(aggregate[i * len(trnas)]), 4)\n\t\t\t\t\t\t\t\tfor i, condition in enumerate(self.conditions)}))\n\n\t\treturn trna_charging_kinetics_solutions, trna_charging_kinetics_constants\n"

REL_15_MARK = '# content are not dropped.'
REL_15_OLD = "\t\t\t# Get tRNA abundances from average container\n\t\t\tvolume = (cell_specs[condition]['avgCellDryMassInit']\n"
REL_15_NEW = "\t\t\t# Get tRNA abundances from average container\n\t\t\t# EXT-PORT-11 adaptation, and the LAST operons-ON gap in this port. It is the same\n\t\t\t# lesion as EXT-PORT-5, in a third consumer.\n\t\t\t#\n\t\t\t# v3.0.1 did `container.count(trna)` on cistron-space tRNA ids, which is correct only\n\t\t\t# with operons OFF, where rna_data degenerates to one row per cistron. Here the Parca's\n\t\t\t# bulkAverageContainer carries RNA counts in TRANSCRIPTION-UNIT space, so 77 of the 86\n\t\t\t# tRNA cistron ids read as EXACTLY ZERO -- only the 9 monocistronic tRNA genes (glyT,\n\t\t\t# glyW, leuZ, thrT, thrU, tyrT, tyrU, tyrV, cysT) are their own transcription unit and\n\t\t\t# survive. Measured on out/ep11_parca: 18 of 20 synthetases had at least one zero-\n\t\t\t# abundance tRNA and 14 had ALL of them zero.\n\t\t\t#\n\t\t\t# It does not fail quietly, but it fails badly: c_trna = 0 makes saturation_trnas = 0,\n\t\t\t# get_random_initial_solution then divides by it, k_cat comes back inf, log10(inf)\n\t\t\t# leaves the bounds, v_charge is NaN, and every restart is rejected by the feasibility\n\t\t\t# filter. The restart loop is `while (iteration < iterations) or (viable_solution <\n\t\t\t# viable_solutions)`, so with nothing ever accepted IT NEVER TERMINATES -- observed as a\n\t\t\t# 36-minute hang on a single synthetase, not as an error.\n\t\t\t#\n\t\t\t# The conversion is not invented here. `transcription.calculate_attenuation` already\n\t\t\t# does exactly this job -- per-cistron tRNA concentration out of cell_specs'\n\t\t\t# bulkAverageContainer, on the operons-ON path, with an identical volume expression --\n\t\t\t# at transcription.py:1518-1524, and this is that code:\n\t\t\t#     counts = tRNA_cistron_tu_mapping_matrix @ counts(rna_data['id'][includes_tRNA])\n\t\t\t# One transcript of a TU yields one copy of each tRNA cistron it carries, which is what\n\t\t\t# that (0/1) matrix encodes; `includes_tRNA` rather than `is_tRNA` so TUs of mixed\n\t\t\t# content are not dropped.\n\t\t\ttranscription = sim_data.process.transcription\n\t\t\tvolume = (cell_specs[condition]['avgCellDryMassInit']\n"

REL_16_MARK = 'unprocessed_counts)'
REL_16_OLD = '\n\t\t\ttrna_to_conc = {}\n'
REL_16_NEW = "\n\t\t\t# Row order of tRNA_cistron_tu_mapping_matrix is\n\t\t\t# np.where(cistron_data['is_tRNA'])[0] (transcription.py:1107-1108) and\n\t\t\t# uncharged_trna_names is that same selection with '[c]' appended\n\t\t\t# (transcription.py:1265-1267). Equal by construction -- asserted rather than assumed,\n\t\t\t# because a permutation here would silently reassign every tRNA's abundance.\n\t\t\ttrna_cistron_ids = [x + '[c]' for x\n\t\t\t\tin transcription.cistron_data['id'][transcription.cistron_data['is_tRNA']]]\n\t\t\tassert trna_cistron_ids == list(transcription.uncharged_trna_names), (\n\t\t\t\t'tRNA_cistron_tu_mapping_matrix row order no longer matches uncharged_trna_names')\n\n\t\t\tunprocessed_counts = container.counts(\n\t\t\t\ttranscription.rna_data['id'][transcription.rna_data['includes_tRNA']])\n\t\t\tcistron_counts = transcription.tRNA_cistron_tu_mapping_matrix.dot(\n\t\t\t\tunprocessed_counts)\n\t\t\ttrna_id_to_count = dict(zip(trna_cistron_ids, cistron_counts))\n\n\t\t\ttrna_to_conc = {}\n"

REL_17_MARK = 'raise KeyError('
REL_17_OLD = '\t\t\tfor trna in trnas:\n\t\t\t\tc_trna = (to_conc\n'
REL_17_NEW = "\t\t\tfor trna in trnas:\n\t\t\t\tif trna not in trna_id_to_count:\n\t\t\t\t\traise KeyError(\n\t\t\t\t\t\tf'{trna} is not a tRNA cistron of this knowledge base; '\n\t\t\t\t\t\tf'amino_acid_to_trnas and uncharged_trna_names have diverged')\n\t\t\t\tc_trna = (to_conc\n"

REL_18_MARK = '* trna_id_to_count[trna]'
REL_18_OLD = '\t\t\t\t\t* container.count(trna)\n'
REL_18_NEW = '\t\t\t\t\t* trna_id_to_count[trna]\n'

REL_19_MARK = 'if c_trna <= 0:'
REL_19_OLD = '\t\t\t\t\t).asNumber(self.conc_unit)\n\n'
REL_19_NEW = "\t\t\t\t\t).asNumber(self.conc_unit)\n\t\t\t\t# A zero here is what made the optimiser hang. Fail with the reason instead.\n\t\t\t\tif c_trna <= 0:\n\t\t\t\t\traise ValueError(\n\t\t\t\t\t\tf'{trna} has zero abundance in the {condition} bulkAverageContainer even '\n\t\t\t\t\t\tf'after the transcription-unit -> cistron conversion. The optimiser cannot '\n\t\t\t\t\t\tf'use it: saturation_trnas would be 0, k_cat would be inf, and every '\n\t\t\t\t\t\tf'restart would be rejected by the feasibility filter without the restart '\n\t\t\t\t\t\tf'loop ever terminating.')\n\n"

FSD_01_MARK = 'import io'
FSD_01_OLD = 'import functools\nimport itertools\n'
FSD_01_NEW = 'import functools\nimport io\nimport itertools\n'

FSD_02_MARK = 'import json'
FSD_02_OLD = 'import itertools\nimport os\n'
FSD_02_NEW = 'import itertools\nimport json\nimport os\n'

FSD_03_MARK = 'from reconstruction.ecoli.knowledge_base_raw import FLAT_DIR'
FSD_03_OLD = 'from reconstruction.ecoli.initialization import create_bulk_container\nfrom reconstruction.ecoli.simulation_data import SimulationDataEcoli\n'
FSD_03_NEW = 'from reconstruction.ecoli.initialization import create_bulk_container\n# EXT-PORT-11: the tRNA charging fit REWRITES flat files, so it needs the same FLAT_DIR the\n# knowledge base was loaded from, and tsv/io/json to write them in the same dialect.\nfrom reconstruction.ecoli.dataclasses import relation as relation_module\nfrom reconstruction.ecoli.knowledge_base_raw import FLAT_DIR\nfrom reconstruction.ecoli.simulation_data import SimulationDataEcoli\n'

FSD_04_MARK = 'from wholecell.io import tsv'
FSD_04_OLD = 'from wholecell.containers.bulk_objects_container import BulkObjectsContainer\nfrom wholecell.utils import filepath, parallelization, units\n'
FSD_04_NEW = 'from wholecell.containers.bulk_objects_container import BulkObjectsContainer\nfrom wholecell.io import tsv\nfrom wholecell.utils import filepath, parallelization, units\n'

FSD_05_MARK = 'documented default.'
FSD_05_OLD = '\t\t\texpression is not fit to protein synthesis demands\n\t"""\n'
FSD_05_NEW = '\t\t\texpression is not fit to protein synthesis demands\n\t\toptimize_trna_charging_kinetics (bool) - EXT-PORT-11. If True, re-fit the tRNA\n\t\t\tsynthetase kinetic parameters and REWRITE the flat files they live in. Order\n\t\t\thours, single-core. Default False, in which case that step only sets\n\t\t\tsim_data.relation.conditions and changes nothing else.\n\t\ttrna_charged_fraction_target (str or dict or None) - EXT-PORT-11. The charged-fraction\n\t\t\tANCHOR for that refit. None means the documented default \'none\', i.e. NO anchor and\n\t\t\tthe charged fraction stays a free variable of the fit, as in v3.0.1. See\n\t\t\tTRNA_CHARGED_FRACTION_TARGETS in reconstruction/ecoli/dataclasses/relation.py for\n\t\t\tthe candidates and the provenance of each.\n\t\ttrna_charged_fraction_weight (float or None) - EXT-PORT-11. w_a; None uses the\n\t\t\tdocumented default.\n\t\ttrna_charged_fraction_anchor_min_f (bool) - EXT-PORT-11. Anchor the charged fraction at\n\t\t\tthe swept-down minimum synthetase too. Default False.\n\t\ttrna_charging_kinetics_out (str or None) - EXT-PORT-11. Where to write the three\n\t\t\trefitted TSVs. None means reconstruction/ecoli/flat/, i.e. overwrite in place.\n\t"""\n'

FSD_06_MARK = '# exist after fit_condition has run.'
FSD_06_OLD = '\tsim_data, cell_specs = final_adjustments(sim_data, cell_specs, **kwargs)\n\n'
FSD_06_NEW = "\tsim_data, cell_specs = final_adjustments(sim_data, cell_specs, **kwargs)\n\t# EXT-PORT-11: LAST, and a no-op unless --optimize-trna-charging-kinetics is given.\n\t# v3.0.1 fit_sim_data_1.py:109 places it here for the same reason: it consumes\n\t# cell_specs['bulkAverageContainer'] and sim_data.codon_read_rate, both of which only\n\t# exist after fit_condition has run.\n\tsim_data, cell_specs = optimize_trna_charging_kinetics(\n\t\tsim_data, cell_specs, raw_data=raw_data, **kwargs)\n\n"

FSD_07_MARK = 'sim_data.codon_read_rate[nutrients] = ('
FSD_07_OLD = '\t\t\tsim_data.translation_supply_rate[nutrients] = cell_specs[condition_label]["translation_aa_supply"]\n\n'
FSD_07_NEW = '\t\t\tsim_data.translation_supply_rate[nutrients] = cell_specs[condition_label]["translation_aa_supply"]\n\t\t# EXT-PORT-11: the missing half of the codon_read_rate wiring. `sim_data.codon_read_rate`\n\t\t# was created empty by the port (simulation_data.py) and NOTHING filled it, in this tree or\n\t\t# in vendor/v301 -- the producer lives in v3.0.1\'s fit_sim_data_1.py, which is not vendored.\n\t\t# It is the v_usage driver, i.e. the entire right-hand side of the steady-state condition\n\t\t# the tRNA charging fit is built on, so `optimize_trna_charging_kinetics` raised KeyError on\n\t\t# its first synthetase. v3.0.1 fit_sim_data_1.py:287-289.\n\t\tif nutrients not in sim_data.codon_read_rate:\n\t\t\tsim_data.codon_read_rate[nutrients] = (\n\t\t\t\tcell_specs[condition_label]["codon_read_rate"])\n\n'

FSD_08_MARK = '\'"K_T"\','
FSD_08_OLD = '\tsim_data.process.transcription.set_ppgpp_kinetics_parameters(average_basal_container, sim_data.constants)\n\n'
FSD_08_NEW = '\tsim_data.process.transcription.set_ppgpp_kinetics_parameters(average_basal_container, sim_data.constants)\n\n\treturn sim_data, cell_specs\n\n@save_state\ndef optimize_trna_charging_kinetics(sim_data, cell_specs, raw_data=None, **kwargs):\n\t"""\n\tEXT-PORT-11. Calculates, stores, and writes tRNA synthetase kinetic parameters optimized to\n\tsupport the cell\'s protein synthesis demand. Ported from WholeCellEcoliRelease v3.0.1\n\tfit_sim_data_1.py:408-536 (Choi & Covert 2023, NAR 51(12):5911, doi:10.1093/nar/gkad435), with\n\tpermission from Prof. Covert.\n\n\tOFF BY DEFAULT. Without --optimize-trna-charging-kinetics this function does exactly one thing:\n\tit sets `sim_data.relation.conditions`, which the optimiser and `get_constants` both read and\n\twhich is otherwise undefined. That assignment is unconditional in v3.0.1 too, and it is inert --\n\tnothing on the steady-state path reads it.\n\n\tIt is LAST in the Parca for a reason: it needs `cell_specs[condition][\'bulkAverageContainer\']`\n\tand `[\'avgCellDryMassInit\']`, which only exist inside a Parca run, and `sim_data.codon_read_rate`,\n\twhich fit_condition populates. It cannot be run standalone against a finished simData.cPickle.\n\n\tCost: order hours, single core. There is no multiprocessing in the optimiser -- it is a serial\n\tloop of >= 8080 Powell minimisations (20 synthetases x 4 sweep levels x >= 100 restarts) -- so\n\t--cpus does not speed this step up.\n\n\tWRITES, DESTRUCTIVELY, into `reconstruction/ecoli/flat/` by default, exactly as v3.0.1 does:\n\t\toptimization/trna_charging_kinetics_solutions.tsv   (the file sim_data is actually built from)\n\t\toptimization/trna_charging_kinetics_constants.tsv\n\t\ttrna_charging_kinetics.tsv                          (export only; nothing reads it)\n\tPass --trna-charging-kinetics-out to write them elsewhere and leave the checkout untouched.\n\t"""\n\n\t# Note: If desired in the future, conditions can be expanded to all conditions by setting\n\t# sim_data.relation.conditions = sim_data.conditions. v3.0.1 fit_sim_data_1.py:443-444.\n\tsim_data.relation.conditions = [\'basal\', \'with_aa\']\n\n\tif not kwargs.get(\'optimize_trna_charging_kinetics\'):\n\t\treturn sim_data, cell_specs\n\n\tif raw_data is None:\n\t\traise ValueError(\n\t\t\t\'optimize_trna_charging_kinetics needs raw_data to reload the flat files it writes. \'\n\t\t\t\'Pass raw_data=raw_data from fitSimData_1.\')\n\n\t# EXT-PORT-11: the anchor. Resolved and echoed HERE as well as inside the optimiser, so the\n\t# choice appears in the Parca log next to the run it produced, not only in shell history.\n\ttarget_spec = kwargs.get(\'trna_charged_fraction_target\')\n\ttarget_weight = kwargs.get(\'trna_charged_fraction_weight\')\n\tanchor_min_f = bool(kwargs.get(\'trna_charged_fraction_anchor_min_f\', False))\n\tresolved_target = relation_module.resolve_charged_fraction_target(target_spec)\n\teffective_weight = (relation_module.TRNA_CHARGED_FRACTION_WEIGHT_DEFAULT\n\t\tif target_weight is None else target_weight)\n\toutput_dir = kwargs.get(\'trna_charging_kinetics_out\') or FLAT_DIR\n\n\t# QUOTE-FREE BY CONSTRUCTION, and asserted below. These files are written with\n\t# tsv.writer(quotechar="\'"), so a provenance string containing a single quote -- which\n\t# f\'{target_spec!r}\' and a plain dict repr both produce -- makes csv QUOTE_MINIMAL wrap the whole\n\t# field in single quotes. The line then starts with \' rather than #, spreadsheets.comment_line\n\t# stops recognising it as a comment, read_tsv parses it AS THE HEADER, and the reload three lines\n\t# below dies with KeyError: \'synthetase_id\' after the fit has already run. Observed exactly that.\n\tanchor_text = \' \'.join(\n\t\tf\'{condition}={"free" if resolved_target.get(condition) is None else resolved_target[condition]}\'\n\t\tfor condition in sim_data.relation.conditions) or \'no-anchor\'\n\tprovenance = (\n\t\tf\'charged-fraction anchor: target={target_spec or "none"} -> {anchor_text};\'\n\t\tf\' weight={effective_weight:g}; anchor_min_f={anchor_min_f}\')\n\tassert not set(provenance) & set("\'\\"\\t\\n"), (\n\t\tf\'provenance string must stay free of quote and separator characters or it stops being a \'\n\t\tf\'comment line in the TSV it is written to: {provenance!r}\')\n\n\tprint(\'=\' * 78)\n\tprint(\'EXT-PORT-11 optimize_trna_charging_kinetics\')\n\tprint(f\'  {provenance}\')\n\tprint(f\'  writing into {output_dir}\')\n\tif os.path.abspath(output_dir) == os.path.abspath(FLAT_DIR):\n\t\tprint(\'  WARNING: this OVERWRITES the three flat files in the source tree. Every future\'\n\t\t\t\' Parca in this checkout would then use the new constants, and kb_sha256 changes.\')\n\tprint(\'=\' * 78)\n\n\t# Optimize tRNA Charging kinetics\n\tsolutions, constants = sim_data.relation.optimize_trna_charging_kinetics(\n\t\tsim_data, cell_specs,\n\t\tcharged_fraction_target=target_spec,\n\t\tcharged_fraction_weight=target_weight,\n\t\tanchor_min_f=anchor_min_f,\n\t\t)\n\n\tdef write_rows(path, rows):\n\t\tfilepath.makedirs(os.path.dirname(path))\n\t\twith io.open(path, \'wb\') as f:\n\t\t\twriter = tsv.writer(f, quotechar="\'", lineterminator=\'\\n\')\n\t\t\t# EXT-PORT-11: the anchor goes in the FILE header, not only in the log. A fitted\n\t\t\t# charged fraction with no record of what it was fitted against is precisely how a\n\t\t\t# fitted number later gets mistaken for a measured one.\n\t\t\twriter.writerow([\n\t\t\t\tf\'# Created from running {os.path.basename(__file__)} with the\'\n\t\t\t\tf\' --optimize-trna-charging-kinetics option, on {time.ctime()}.\'\n\t\t\t\tf\' EXT-PORT-11 {provenance}.\'])\n\t\t\tfor row in rows:\n\t\t\t\twriter.writerow(row)\n\n\t\t# The header must still BE a comment after csv has had its say. Checked rather than assumed:\n\t\t# this is the failure that cost a completed fit above, and it is invisible until the reload.\n\t\twith io.open(path, encoding=\'utf-8\') as f:\n\t\t\tfirst = f.readline()\n\t\tassert first.lstrip().startswith(\'#\'), (\n\t\t\tf\'{path}: the provenance line was rewritten by the csv dialect and is no longer a \'\n\t\t\tf\'comment, so read_tsv would parse it as the header: {first[:120]!r}\')\n\n\tsolutions_file = os.path.join(\n\t\toutput_dir, \'optimization\', \'trna_charging_kinetics_solutions.tsv\')\n\tconstants_file = os.path.join(\n\t\toutput_dir, \'optimization\', \'trna_charging_kinetics_constants.tsv\')\n\twrite_rows(solutions_file, solutions)\n\twrite_rows(constants_file, constants)\n\n\t# Update sim_data from what was just written, so the export below and the pickled sim_data agree\n\t# with the files on disk rather than with an in-memory copy.\n\traw_data._load_tsv(output_dir, solutions_file)\n\traw_data._load_tsv(output_dir, constants_file)\n\tsim_data.relation._build_trna_charging_kinetics(raw_data, sim_data)\n\n\t# Record default solution. EXPORT ONLY: _build_trna_charging_kinetics reads the SOLUTIONS file,\n\t# never this one (nothing anywhere reads raw_data.trna_charging_kinetics). It exists so the\n\t# chosen sweep level is legible without parsing 5535 rows.\n\tkinetics_file = os.path.join(output_dir, \'trna_charging_kinetics.tsv\')\n\tfilepath.makedirs(os.path.dirname(kinetics_file))\n\twith io.open(kinetics_file, \'wb\') as f:\n\t\twriter = tsv.writer(f, quotechar="\'", lineterminator=\'\\n\')\n\t\twriter.writerow([\n\t\t\tf\'# Created from running {os.path.basename(__file__)} with the\'\n\t\t\tf\' --optimize-trna-charging-kinetics option, on {time.ctime()}.\'\n\t\t\tf\' EXT-PORT-11 {provenance}.\'])\n\n\t\t# Write header\n\t\twriter.writerow([\n\t\t\t\'"Synthetase"\',\n\t\t\t\'"k_cat (1/units.s)"\',\n\t\t\t\'"K_A (units.umol/units.L)"\',\n\t\t\t\'"K_T"\',\n\t\t\t]\n\t\t\t+ [f\'"f {condition}"\' for condition in sim_data.relation.conditions])\n\n\t\t# Write kinetic parameters\n\t\tfor amino_acid in sim_data.molecule_groups.amino_acids:\n\t\t\tif amino_acid == \'L-SELENOCYSTEINE[c]\':\n\t\t\t\tcontinue\n\n\t\t\tsynthetase = sim_data.relation.amino_acid_to_synthetase[amino_acid]\n\t\t\ttrnas = sim_data.relation.amino_acid_to_trnas[amino_acid]\n\n\t\t\tk_cat = (sim_data.relation.synthetase_to_k_cat[synthetase]\n\t\t\t\t).asNumber(1/units.s)\n\t\t\tK_A = (sim_data.relation.synthetase_to_K_A[synthetase]\n\t\t\t\t).asNumber(sim_data.relation.conc_unit)\n\t\t\tK_T_dict = {trna: sim_data.relation.trna_to_K_T[trna].asNumber(\n\t\t\t\tsim_data.relation.conc_unit) for trna in trnas}\n\t\t\t# EXT-PORT-11: v3.0.1 hard-coded `f basal` and `f with_aa` as two separate dicts. Built\n\t\t\t# from self.conditions here instead, so the header and the columns cannot drift apart\n\t\t\t# if conditions is ever widened (the header a few lines above already uses it).\n\t\t\tf_dicts = [\n\t\t\t\t{trna: sim_data.relation\n\t\t\t\t\t.trna_condition_to_free_fraction[f\'{trna}__{condition}\']\n\t\t\t\t\tfor trna in trnas}\n\t\t\t\tfor condition in sim_data.relation.conditions]\n\n\t\t\twriter.writerow([\n\t\t\t\tf\'"{synthetase}"\',\n\t\t\t\tk_cat,\n\t\t\t\tK_A,\n\t\t\t\tjson.dumps(K_T_dict),\n\t\t\t\t]\n\t\t\t\t+ [json.dumps(f_dict) for f_dict in f_dicts])\n\n'

FSD_09_MARK = '# v_usage. v3.0.1 fit_sim_data_1.py:1039.'
FSD_09_OLD = '\tspec["translation_aa_supply"] = calculateTranslationSupply(\n'
FSD_09_NEW = '\t# EXT-PORT-11: ...and the codon reading rate, which the tRNA charging fit consumes as\n\t# v_usage. v3.0.1 fit_sim_data_1.py:1039.\n\tspec["translation_aa_supply"], spec["codon_read_rate"] = calculateTranslationSupply(\n'

FSD_10_MARK = 'n_codons = np.sum('
FSD_10_OLD = '\treturn translation_aa_supply\n'
FSD_10_NEW = "\t# Calculate required codon reading rate\n\t# EXT-PORT-11: ported verbatim from v3.0.1 fit_sim_data_1.py:1088-1097. Assumes\n\t# exponential growth: dN/dt = rN, where N is the concentration of codons read to create\n\t# the initial proteome.\n\t#\n\t# INDEX SPACE, which is where this port could have gone silently wrong. codon_counts is\n\t# built in _build_codon_based_translation by iterating\n\t# translation.monomer_data['id'] (relation.py), so its rows are in monomer_data order --\n\t# the same order proteinCounts is read in on the line above. That is asserted rather than\n\t# assumed: an unnoticed permutation here would reweight every codon and the fit would\n\t# still converge, on the wrong demand.\n\tcodon_counts = sim_data.relation.codon_counts\n\tassert codon_counts.shape[0] == len(proteinCounts), (\n\t\t'relation.codon_counts has {} rows but monomer_data has {} monomers; the two are no '\n\t\t'longer in the same index space'.format(codon_counts.shape[0], len(proteinCounts)))\n\tassert codon_counts.shape[1] == len(sim_data.relation.codons), (\n\t\t'relation.codon_counts has {} columns but there are {} codons'.format(\n\t\t\tcodon_counts.shape[1], len(sim_data.relation.codons)))\n\tn_codons = np.sum(\n\t\tcodon_counts\n\t\t* np.tile(proteinCounts[:, None], (1, codon_counts.shape[1])),\n\t\taxis=0)\n\tavgCellMassInit = avgCellDryMassInit / sim_data.mass.cell_dry_mass_fraction\n\tvolume = avgCellMassInit / sim_data.constants.cell_density\n\tc_codons = 1 / nAvogadro / volume * n_codons\n\tcodon_read_rate = np.log(2) / doubling_time * c_codons\n\n\treturn translation_aa_supply, codon_read_rate\n"

SD_01_MARK = '# condition the fit minimises against. Read by'
SD_01_OLD = '\t\t# Populated by the kinetic tRNA charging model (EXT-PORT, from WholeCellEcoliRelease v3.0.1).\n\t\t# Empty under the default SteadyStateElongationModel, which never reads it.\n'
SD_01_NEW = '\t\t# {media_id: codon reading rate, uM/s per codon}. EXT-PORT (WholeCellEcoliRelease v3.0.1).\n\t\t# EXT-PORT-11: now POPULATED, by fit_sim_data_1.fit_condition, alongside\n\t\t# translation_supply_rate. It was created empty by EXT-PORT-1 and left that way, which made\n\t\t# the tRNA charging fit unrunnable: it is v_usage, the right-hand side of the steady-state\n\t\t# condition the fit minimises against. Read by\n\t\t# Relation.get_constants / optimize_trna_charging_kinetics only.\n'

SB_01_MARK = '# defined by define_parca_options() below or every Parca invocation dies with a KeyError.'
SB_01_OLD = "\t'stable_rrna',\n\t)\n"
SB_01_NEW = "\t'stable_rrna',\n\t# EXT-PORT-11: the tRNA charging refit and its charged-fraction anchor. All four are Parca-only\n\t# -- they change how sim_data is BUILT, not how a simulation runs, so they belong here and not\n\t# in SIM_KEYS. `data.select_keys` does mapping[key] with no default, so every name here must be\n\t# defined by define_parca_options() below or every Parca invocation dies with a KeyError.\n\t'optimize_trna_charging_kinetics',\n\t'trna_charged_fraction_target',\n\t'trna_charged_fraction_weight',\n\t'trna_charged_fraction_anchor_min_f',\n\t'trna_charging_kinetics_out',\n\t)\n"

SB_02_MARK = "' base no longer has.')"
SB_02_OLD = '\n\tdef define_sim_loop_options(self, parser, manual_script=False):\n'
SB_02_NEW = '\n\t\t# EXT-PORT-11: the tRNA charging refit (WholeCellEcoliRelease v3.0.1, Choi & Covert 2023)\n\t\t# and the charged-fraction anchor this tree adds to it. Default OFF: with the flag absent\n\t\t# the Parca is unchanged and produces the same simData.cPickle as before.\n\t\tself.define_parameter_bool(parser, \'optimize_trna_charging_kinetics\', False,\n\t\t\thelp=\'Re-fit the tRNA synthetase kinetic parameters (k_cat, K_A, K_T) and REPLACE the\'\n\t\t\t\t \' flat files they live in. Order HOURS, single-core (--cpus does not help). The\'\n\t\t\t\t \' shipped constants were fitted in Sep 2022 against tRNA abundances this knowledge\'\n\t\t\t\t \' base no longer has.\')\n\t\tself.define_option(parser,\n\t\t\t\'trna_charged_fraction_target\', str, default=None,\n\t\t\thelp=\'Charged-fraction ANCHOR for the tRNA charging refit. The measurements conflict,\'\n\t\t\t\t \' so this is a parameter and NOT a constant: pass one of the named candidates in\'\n\t\t\t\t \' reconstruction/ecoli/dataclasses/relation.py TRNA_CHARGED_FRACTION_TARGETS\'\n\t\t\t\t \' (none, avcilar_kucukgoze_2016, dittmar_2005, choi_covert_2023, classic_80_90),\'\n\t\t\t\t \' or an explicit per-condition spec such as "basal=0.55,with_aa=none". Default\'\n\t\t\t\t \' (None) resolves to "none", i.e. NO anchor -- the charged fraction stays a free\'\n\t\t\t\t \' variable exactly as in v3.0.1. Each candidate carries its medium, temperature,\'\n\t\t\t\t \' doubling time, method and DOI at its definition.\')\n\t\tself.define_option(parser,\n\t\t\t\'trna_charged_fraction_weight\', float, default=None,\n\t\t\thelp=\'Weight w_a on the charged-fraction anchor. Default (None) uses\'\n\t\t\t\t \' TRNA_CHARGED_FRACTION_WEIGHT_DEFAULT, whose derivation against the ~1e-7 scale\'\n\t\t\t\t \' of the rest of the objective is documented at that constant.\')\n\t\tself.define_parameter_bool(parser, \'trna_charged_fraction_anchor_min_f\', False,\n\t\t\thelp=\'Also anchor the charged fraction at the swept-down MINIMUM synthetase\'\n\t\t\t\t \' abundance. Off by default: that regime is a robustness margin, not a condition\'\n\t\t\t\t \' any measurement was taken in.\')\n\t\tself.define_option(parser,\n\t\t\t\'trna_charging_kinetics_out\', str, default=None,\n\t\t\thelp=\'Directory to write the three refitted tRNA charging TSVs into. Default (None)\'\n\t\t\t\t \' is reconstruction/ecoli/flat/, which is what v3.0.1 does and which OVERWRITES\'\n\t\t\t\t \' the checked-in files.\')\n\n\tdef define_sim_loop_options(self, parser, manual_script=False):\n'

PT_01_MARK = "'trna_charging_kinetics_out',"
PT_01_OLD = "\t\t'stable_rrna',\n\t\t]\n"
PT_01_NEW = "\t\t'stable_rrna',\n\t\t# EXT-PORT-11: the tRNA charging refit and its charged-fraction anchor. Fireworks RAISES\n\t\t# on an unknown kwarg, so this list, scriptBase.PARCA_KEYS and FitSimDataTask's\n\t\t# optional_params must stay in step or every Parca fails, not just the refitting one.\n\t\t'optimize_trna_charging_kinetics',\n\t\t'trna_charged_fraction_target',\n\t\t'trna_charged_fraction_weight',\n\t\t'trna_charged_fraction_anchor_min_f',\n\t\t'trna_charging_kinetics_out',\n\t\t]\n"

PT_02_MARK = "disable_rnapoly_capacity_fitting=not self['rnapoly_fitting'],"
PT_02_OLD = "\t\t\t\tdisable_rnapoly_capacity_fitting=not self['rnapoly_fitting']),\n"
PT_02_NEW = "\t\t\t\tdisable_rnapoly_capacity_fitting=not self['rnapoly_fitting'],\n\t\t\t\t# EXT-PORT-11\n\t\t\t\toptimize_trna_charging_kinetics=self.get('optimize_trna_charging_kinetics', False),\n\t\t\t\ttrna_charged_fraction_target=self.get('trna_charged_fraction_target'),\n\t\t\t\ttrna_charged_fraction_weight=self.get('trna_charged_fraction_weight'),\n\t\t\t\ttrna_charged_fraction_anchor_min_f=self.get('trna_charged_fraction_anchor_min_f', False),\n\t\t\t\ttrna_charging_kinetics_out=self.get('trna_charging_kinetics_out')),\n"

FT_01_MARK = "'trna_charging_kinetics_out',"
FT_01_OLD = "\t\t'variable_elongation_translation',\n\t]\n"
FT_01_NEW = "\t\t'variable_elongation_translation',\n\t\t# EXT-PORT-11: see the note in parca.py -- Fireworks raises on unknown kwargs.\n\t\t'optimize_trna_charging_kinetics',\n\t\t'trna_charged_fraction_target',\n\t\t'trna_charged_fraction_weight',\n\t\t'trna_charged_fraction_anchor_min_f',\n\t\t'trna_charging_kinetics_out',\n\t]\n"

FT_02_MARK = "trna_charging_kinetics_out=self.get('trna_charging_kinetics_out'),"
FT_02_OLD = "\t\t\tdisable_rnapoly_capacity_fitting=self['disable_rnapoly_capacity_fitting'],\n\t\t)\n"
FT_02_NEW = "\t\t\tdisable_rnapoly_capacity_fitting=self['disable_rnapoly_capacity_fitting'],\n\t\t\t# EXT-PORT-11: the tRNA charging refit. A no-op unless the first of these is True.\n\t\t\toptimize_trna_charging_kinetics=self.get('optimize_trna_charging_kinetics', False),\n\t\t\ttrna_charged_fraction_target=self.get('trna_charged_fraction_target'),\n\t\t\ttrna_charged_fraction_weight=self.get('trna_charged_fraction_weight'),\n\t\t\ttrna_charged_fraction_anchor_min_f=self.get('trna_charged_fraction_anchor_min_f', False),\n\t\t\ttrna_charging_kinetics_out=self.get('trna_charging_kinetics_out'),\n\t\t)\n"


EDITS = [
    (REL, [
        ("REL_01", REL_01_MARK, REL_01_OLD, REL_01_NEW),
        ("REL_02", REL_02_MARK, REL_02_OLD, REL_02_NEW),
        ("REL_03", REL_03_MARK, REL_03_OLD, REL_03_NEW),
        ("REL_04", REL_04_MARK, REL_04_OLD, REL_04_NEW),
        ("REL_05", REL_05_MARK, REL_05_OLD, REL_05_NEW),
        ("REL_06", REL_06_MARK, REL_06_OLD, REL_06_NEW),
        ("REL_07", REL_07_MARK, REL_07_OLD, REL_07_NEW),
        ("REL_08", REL_08_MARK, REL_08_OLD, REL_08_NEW),
        ("REL_09", REL_09_MARK, REL_09_OLD, REL_09_NEW),
        ("REL_10", REL_10_MARK, REL_10_OLD, REL_10_NEW),
        ("REL_11", REL_11_MARK, REL_11_OLD, REL_11_NEW),
        ("REL_12", REL_12_MARK, REL_12_OLD, REL_12_NEW),
        ("REL_13", REL_13_MARK, REL_13_OLD, REL_13_NEW),
        ("REL_14", REL_14_MARK, REL_14_OLD, REL_14_NEW),
        ("REL_15", REL_15_MARK, REL_15_OLD, REL_15_NEW),
        ("REL_16", REL_16_MARK, REL_16_OLD, REL_16_NEW),
        ("REL_17", REL_17_MARK, REL_17_OLD, REL_17_NEW),
        ("REL_18", REL_18_MARK, REL_18_OLD, REL_18_NEW),
        ("REL_19", REL_19_MARK, REL_19_OLD, REL_19_NEW),
        ]),
    (FSD, [
        ("FSD_01", FSD_01_MARK, FSD_01_OLD, FSD_01_NEW),
        ("FSD_02", FSD_02_MARK, FSD_02_OLD, FSD_02_NEW),
        ("FSD_03", FSD_03_MARK, FSD_03_OLD, FSD_03_NEW),
        ("FSD_04", FSD_04_MARK, FSD_04_OLD, FSD_04_NEW),
        ("FSD_05", FSD_05_MARK, FSD_05_OLD, FSD_05_NEW),
        ("FSD_06", FSD_06_MARK, FSD_06_OLD, FSD_06_NEW),
        ("FSD_07", FSD_07_MARK, FSD_07_OLD, FSD_07_NEW),
        ("FSD_08", FSD_08_MARK, FSD_08_OLD, FSD_08_NEW),
        ("FSD_09", FSD_09_MARK, FSD_09_OLD, FSD_09_NEW),
        ("FSD_10", FSD_10_MARK, FSD_10_OLD, FSD_10_NEW),
        ]),
    (SD, [
        ("SD_01", SD_01_MARK, SD_01_OLD, SD_01_NEW),
        ]),
    (SB, [
        ("SB_01", SB_01_MARK, SB_01_OLD, SB_01_NEW),
        ("SB_02", SB_02_MARK, SB_02_OLD, SB_02_NEW),
        ]),
    (PT, [
        ("PT_01", PT_01_MARK, PT_01_OLD, PT_01_NEW),
        ("PT_02", PT_02_MARK, PT_02_OLD, PT_02_NEW),
        ]),
    (FT, [
        ("FT_01", FT_01_MARK, FT_01_OLD, FT_01_NEW),
        ("FT_02", FT_02_MARK, FT_02_OLD, FT_02_NEW),
        ]),
    ]

# ------------------------------------------------------------------------------------------------

def _read(path: str) -> tuple[str, str]:
    """(text, destination newline). Preserves CRLF vs LF, per the applier's convention."""
    with open(path, "rb") as f:
        blob = f.read()
    nl = "\r\n" if blob.count(b"\r\n") else "\n"
    with io.open(path, encoding="utf-8", newline="") as f:
        return f.read().replace("\r\n", "\n"), nl


def _write(path: str, text: str, nl: str) -> None:
    with io.open(path, "w", encoding="utf-8", newline=nl) as f:
        f.write(text)


class Patcher:
    """Applies (marker, old, new) edits to one file. Asserts each anchor matches EXACTLY ONCE."""

    def __init__(self, root: str, rel: str, check: bool):
        self.path = os.path.join(root, rel)
        self.rel = rel
        self.check = check
        self.text, self.nl = _read(self.path)
        self.original = self.text
        self.results: list[dict] = []

    def edit(self, name: str, marker: str, old: str, new: str) -> None:
        if marker in self.text:
            self.results.append({"edit": name, "state": "already applied"})
            return
        n = self.text.count(old)
        if n != 1:
            self.results.append({"edit": name,
                "state": "ANCHOR MISSING" if n == 0 else f"ANCHOR AMBIGUOUS (matched {n}x)"})
            raise SystemExit(
                f"FATAL {self.rel}: edit {name!r} anchor matched {n} times, expected exactly 1.\n"
                f"  anchor starts: {old.splitlines()[0][:100]!r}\n"
                "  Nothing was written. Refusing to guess -- an anchor that no longer matches means\n"
                "  the file has moved on and the edit may no longer be correct.")
        self.text = self.text.replace(old, new, 1)
        self.results.append({"edit": name, "state": "applied"})

    def flush(self) -> bool:
        changed = self.text != self.original
        if changed and not self.check:
            _write(self.path, self.text, self.nl)
        return changed


def run(wcecoli: str, check: bool) -> dict:
    report: dict = {"check": check, "files": {}}
    wrote = []
    for const, edits in EDITS:
        p = Patcher(wcecoli, const, check)
        for name, marker, old, new in edits:
            p.edit(name, marker, old, new)
        if p.flush():
            wrote.append(const)
        report["files"][const] = p.results
    report["would_write" if check else "wrote"] = wrote
    report["complete"] = all(
        r["state"] in ("applied", "already applied")
        for results in report["files"].values() for r in results)
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--wcecoli", default=os.environ.get("WCECOLI_DIR", "C:/dev/wcEcoli"))
    ap.add_argument("--check", action="store_true", help="report only, write nothing")
    args = ap.parse_args(argv)
    report = run(args.wcecoli, args.check)
    print(json.dumps(report, indent=2))
    if not report["complete"]:
        print("\nINCOMPLETE -- see states above.", file=sys.stderr)
        return 1
    files = report.get("wrote") or report.get("would_write") or []
    if files and args.check:
        print("\nWOULD WRITE (nothing was written -- --check): " + ", ".join(files))
    elif files:
        print("\nWROTE: " + ", ".join(files))
        print("\nThe Parca is unchanged unless --optimize-trna-charging-kinetics is passed, but")
        print("sim_data now carries a populated codon_read_rate, so simData.cPickle and kb_sha256")
        print("change on the next rebuild. Verify with:")
        print("  python runscripts/manual/runParca.py <newdir> --cpus 4 --save-intermediates")
        print("  python scripts/verify_trna_objective.py --kb <newdir>/kb/simData.cPickle")
    else:
        print("\nnothing to do -- already applied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
