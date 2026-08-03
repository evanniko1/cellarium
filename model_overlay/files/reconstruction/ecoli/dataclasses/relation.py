"""
SimulationData relation functions
"""

import numpy as np

# EXT-PORT-1: required by the ported relation methods (v3.0.1). `warnings` in particular is reached
# only on a sequence-mismatch branch, so its absence surfaces minutes into a ParCa rebuild, not at import.
import copy
import json
import warnings
from Bio.Seq import Seq
from scipy.optimize import minimize
from wholecell.utils import units
from wholecell.utils.polymerize import polymerize

# EXT-PORT-10: the reconciliation buffer of KineticTrnaChargingModel, defined HERE because this is
# the file that has to pad codon_sequences wide enough to contain it. It is imported by
# models/ecoli/processes/polypeptide_elongation.py rather than repeated as a literal.
#
# The decoupling WAS the bug. The pad lived only in the knowledge base and the buffer only in the
# process, so halving MAX_TIME_STEP (2.0 -> 1.0 in this tree) halved the pad 60 -> 30 while the
# window only fell 54 -> 32, because this term is dt-independent. Deficit in closed form:
#     ceil(m*R_basal) + B - 1 - m*R_max
#     m=1.0 (ours):   22 + 10 - 1 - 30 = +1   -> buildSequences IndexError on yeeJ at position 2338
#     m=2.0 (v3.0.1): 44 + 10 - 1 - 60 = -7   -> seven spare columns
KINETIC_TRNA_CHARGING_WIDTH_BUFFER = 10

# EXT-PORT-11: v3.0.1 module-level switch for the optimiser's per-iteration trace. It is READ at
# three points inside optimize_trna_charging_kinetics (vendor relation.py:957, :1005, :1146) and was
# never brought across with the method, so calling the optimiser in this tree raised
# `NameError: name 'print_optimization' is not defined` on the first sweep level. Same silent-absence
# class as EXT-PORT-1's missing imports: it is invisible until the code path actually runs.
print_optimization = False


# =====================================================================================================
# EXT-PORT-11 --- the tRNA CHARGED-FRACTION ANCHOR
# =====================================================================================================
#
# WHAT WAS THERE BEFORE, MEASURED. In v3.0.1 the charged fraction is neither a target nor a
# constraint of the fit. `f` is the FREE fraction (charged = 1 - f) and it is a FREE DECISION
# VARIABLE: one element per (condition, K_T group), plus a second copy `min_f` at the swept-down
# minimum synthetase, unpacked from the candidate vector alongside k_cat, K_A and K_T
# (trna_charging_objective below). Together f and min_f are the MAJORITY of the free parameters --
# 8 of 12 for AlaRS, 16 of 22 for ArgRS, 20 of 27 for LeuRS. The only things acting on it are a box
# bound f in (0.051, 0.949) and a barrier penalty at weight 1e-9. Nothing measured enters the
# objective at all. The fitted value is written to flat/optimization/
# trna_charging_kinetics_solutions.tsv (column `f_free`) and to flat/trna_charging_kinetics.tsv
# (columns `f basal` / `f with_aa`), loaded back into `trna_condition_to_free_fraction`, and then
# READ BY NOTHING -- in v3.0.1 as well as here. The simulation consumes only k_cat, K_A and K_T.
#
# WHY IT FLOATS. In the regime this model sits in, tRNA saturation is ~21%, so
# v_charge ~= k_cat * E * sat_A * (f * c_trna / K_T). The steady-state condition therefore
# identifies only the PRODUCT k_cat * f / K_T; f, k_cat and K_T are jointly degenerate and the
# objective structurally cannot separate them. Anchoring f is what breaks that degeneracy and turns
# k_cat/K_T from a gauge choice into an identified quantity.
#
# WHAT THIS ADDS. A fourth error term, off by default, that pulls the ABUNDANCE-WEIGHTED MEAN
# charged fraction of one synthetase's tRNAs toward a per-condition target. It does NOT replace the
# barrier -- see the note on `bounds_penalty_weight` in optimize_trna_charging_kinetics.
#
# SCALE, WHICH IS THE PART THAT BITES. At the shipped optima the TOTAL objective is ~1e-7 and is
# 94-99% penalty, not error: the hard feasibility filter (max|v_charge - v_usage| <= 1e-3, applied
# as an accept/reject after the minimisation, not inside it) drives the steady-state residual to
# ~1e-9, so what actually SELECTS among the feasible solutions is w_r * sum(K_T). Decomposed from
# the shipped sweep-level-4 rows (objective | w_r*sumK_T | w_b*barrier | residual):
#     ALAS-CPLX[c]      8.122e-08 | 2.589e-08 | 5.051e-08 | 4.8e-09
#     ARGS-MONOMER[c]   9.817e-07 | 6.497e-07 | 3.216e-07 | 1.0e-08
#     TRPS-CPLX[c]      4.338e-08 | 8.749e-09 | 3.368e-08 | 9.5e-10
#     LEUS-MONOMER[c]   7.060e-07 | 7.676e-08 | 6.195e-07 | 9.8e-09
# An anchor term must be scaled against ~1e-7 or it is either invisible or totally dominant. The
# default weight below is derived from that arithmetic and is documented at its definition.
#
# ---------------------------------------------------------------------------------------------------
# THE TARGETS. Deliberately a REGISTRY of named candidates rather than a constant, because the
# candidates conflict and the choice is scientific, not technical. NONE of them is selected by
# default: the default is `none`, which reproduces v3.0.1 exactly. Selecting a target is an explicit
# act on the command line and it is recorded in the output file header.
#
# Every entry is per condition, because the measurements are condition-specific. `None` for a
# condition means NO CONDITION-MATCHED MEASUREMENT EXISTS and that condition's f is left free --
# which is the honest state of `with_aa` for all four candidates below. Do not fill those in with
# the basal number to make the table look complete; that is exactly how a fitted number gets
# mistaken for a measured one.
TRNA_CHARGED_FRACTION_TARGETS = {

	# The default. No anchor: `f` stays a free variable, bounded only by the box and the barrier,
	# exactly as in Choi & Covert 2023 / WholeCellEcoliRelease v3.0.1.
	'none': None,

	# (A) MEASURED, and the only one whose growth condition matches this model's `basal`.
	#     Avcilar-Kucukgoze et al. 2016, Nucleic Acids Research 44(17):8324-8334,
	#     doi:10.1093/nar/gkw697.
	#     Medium   M9 + 0.4% glucose (minimal, no amino acids)
	#     Temp     37 C
	#     Doubling 43.3 min
	#     Method   periodate-protection microarray, corroborated by acid-urea northern blot
	#     Reported "oscillates around 50-60%" aggregate charged fraction; 0.55 is the midpoint.
	#     KNOWN OBJECTION: Choi & Covert single this dataset out as running systematically low,
	#     in places exceeding 100%. That objection is not adjudicated here.
	'avcilar_kucukgoze_2016': {'basal': 0.55, 'with_aa': None},

	# (B) MEASURED, but in a different medium from this model's `basal`.
	#     Dittmar et al. 2005, EMBO Reports 6(2):151-157, doi:10.1038/sj.embor.7400341.
	#     Medium   MOPS + glycerol
	#     Temp     37 C
	#     Doubling not condition-matched to `basal`
	#     Method   acid-urea northern blot
	#     Five Leu isoacceptors unperturbed at 0.80 / 0.77 / 0.68 / 0.76 / 0.84; 0.77 is the median.
	#     This is a per-isoacceptor Leu measurement being used as a proteome-wide aggregate target.
	'dittmar_2005': {'basal': 0.77, 'with_aa': None},

	# (C) NOT A MEASUREMENT -- a MODEL OUTPUT. Choi & Covert 2023, NAR 51(12):5911,
	#     doi:10.1093/nar/gkad435, published aggregate charged fraction, which this port already
	#     reproduces at end-of-generation (0.7845 measured on operonsON_kin_probe, n=1 seed,
	#     1 generation). Anchoring here changes almost nothing and validates the port rather than
	#     the biology. Included so that "reproduce the paper" is an explicit, labelled choice.
	'choi_covert_2023': {'basal': 0.788, 'with_aa': None},

	# (D) NOT A MEASUREMENT -- an extrapolation. The classic "80-90% charged", quoted and then
	#     explicitly REJECTED by Avcilar-Kucukgoze et al. 2016 as an extrapolation from three
	#     papers, one of which is a method paper on mutant initiator tRNAs. It is included because
	#     it is nearest to what the shipped constants already imply (basal 0.832 abundance-weighted
	#     at the default sweep level 4), so leaving it out would hide how close the status quo is
	#     to the weakest-evidenced candidate.
	'classic_80_90': {'basal': 0.85, 'with_aa': None},
	}

# The documented default: NO ANCHOR. Chosen so that (i) the port stays byte-faithful to v3.0.1 and
# the shipped constants remain reproducible, and (ii) no target is adopted implicitly. Changing this
# default is a scientific decision and must be argued in the commit that makes it.
TRNA_CHARGED_FRACTION_TARGET_DEFAULT = 'none'

# Weight on the anchor term, w_a. Derived, not guessed, from the decomposition above:
#   - the term that currently SELECTS the solution is w_r * sum(K_T), which lands at 8.7e-09
#     (TRPS) to 6.5e-07 (ARGS) at the shipped optima;
#   - the anchor's squared deviation is O(0.01-0.08) for a target 0.1-0.3 away from where the fit
#     currently lands (shipped basal aggregate 0.832 vs candidate 0.55 gives 0.0795);
#   - so w_a = 1e-6 puts the anchor at 1e-08 to 8e-08 -- the same order as the regulariser, able to
#     move f without swamping K_T selection.
# This is a STARTING POINT, not a fitted value. Any refit must report the four-way decomposition of
# the objective at its optima (the optimiser prints it when `print_optimization` is True) and show
# that the anchor is neither invisible nor dominant. Override with --trna-charged-fraction-weight.
TRNA_CHARGED_FRACTION_WEIGHT_DEFAULT = 1e-6


def resolve_charged_fraction_target(spec):
	"""EXT-PORT-11. Normalise a charged-fraction anchor spec into {condition: target or None}.

	Accepts:
	  None                     -> the documented default (TRNA_CHARGED_FRACTION_TARGET_DEFAULT)
	  a key of TRNA_CHARGED_FRACTION_TARGETS, e.g. 'avcilar_kucukgoze_2016' or 'none'
	  an explicit spec string, e.g. 'basal=0.55,with_aa=0.6' or 'basal=0.55,with_aa=none'
	  a dict {condition: float or None}, passed through after validation

	Returns a dict; conditions mapped to None are left UNANCHORED. An unrecognised name raises
	rather than falling back to 'none', because a typo that silently disables the anchor would
	produce a run that looks anchored in the shell history and is not.
	"""
	if spec is None:
		spec = TRNA_CHARGED_FRACTION_TARGET_DEFAULT

	if isinstance(spec, str):
		if spec in TRNA_CHARGED_FRACTION_TARGETS:
			spec = TRNA_CHARGED_FRACTION_TARGETS[spec]
		elif '=' in spec:
			parsed = {}
			for item in spec.split(','):
				if not item.strip():
					continue
				condition, _, value = item.partition('=')
				value = value.strip()
				parsed[condition.strip()] = (
					None if value.lower() in ('', 'none', 'free') else float(value))
			spec = parsed
		else:
			raise ValueError(
				'unknown charged-fraction target {!r}. Known names: {}. Or give an explicit '
				'per-condition spec such as "basal=0.55,with_aa=none".'.format(
					spec, sorted(TRNA_CHARGED_FRACTION_TARGETS)))

	if spec is None:
		return {}

	if not isinstance(spec, dict):
		raise TypeError('charged-fraction target must be a name, a "cond=value" string, a dict, '
			'or None; got {!r}'.format(type(spec)))

	resolved = {}
	for condition, value in spec.items():
		if value is None:
			resolved[condition] = None
			continue
		value = float(value)
		# The box bound on f is (0.051, 0.949), so charged fraction is representable only inside
		# the same interval. A target outside it is unreachable by construction and would show up
		# as a constant offset in the anchor error rather than as an error.
		if not 0.051 < value < 0.949:
			raise ValueError(
				'charged-fraction target for {!r} is {}, outside the (0.051, 0.949) box that `f` '
				'is bounded to; it is unreachable and would silently bias the fit.'.format(
					condition, value))
		resolved[condition] = value
	return resolved


def trna_charging_objective(x, indexes, maps, v_codons, c_synthetase, c_synthetase_min,
		c_amino_acid, c_trnas, w_r, w_b, w_a, anchor_targets, anchor_min_f):
	"""Objective minimised by Relation.optimize_trna_charging_kinetics.

	EXT-PORT-11 adaptation: this was a CLOSURE inside optimize_trna_charging_kinetics in v3.0.1
	(vendor relation.py:617-712), capturing `w_r` and `w_b` from the enclosing scope. It is lifted
	to module level with those two made explicit arguments, for two reasons: the anchor needs its
	own weight and target passed in the same way, and a closure cannot be regression-tested. The
	arithmetic of the four v3.0.1 terms is unchanged -- verified numerically by
	scripts/verify_trna_objective.py, which re-evaluates this function at every shipped solution
	vector and reproduces the shipped `objective` column.

	Terms, in the order they are summed:
	  1. steady_state_error      at the mean synthetase concentration        (v3.0.1)
	  2. min_steady_state_error  at the swept-down minimum synthetase        (v3.0.1)
	  3. w_r * sum(K_T)          regulariser -- the term that actually selects among the
	                             (heavily underdetermined) feasible solutions               (v3.0.1)
	  4. w_b * bounds_penalty    barrier keeping f inside (0.05, 0.95). NOTE: it is symmetric about
	                             f = 0.5, so it has an accidental, un-cited preference for a 50%
	                             charged fraction, and it is 40-88% of the total objective at the
	                             shipped optima. It is a numerical bound-repeller, not evidence.
	                             (v3.0.1)
	  5. w_a * anchor_error      EXT-PORT-11. Zero and exactly inert when no condition carries a
	                             target, which is the default.
	"""

	# Pre-conditioning
	x = np.power(10, x)

	# Parse candidate solution
	k_cat = x[indexes['k_cat_index']]
	K_A = x[indexes['K_A_index']]
	K_T = x[indexes['K_T_slice']]
	f = x[indexes['f_slice']]
	min_f = x[indexes['min_f_slice']]

	############################################################

	# Calculate charging rate of each free trna
	saturation_amino_acid = c_amino_acid / (K_A + c_amino_acid)
	relative_trnas = ((maps['f_to_cases'] @ f)
		* c_trnas
		/ (maps['K_T_to_cases'] @ K_T))
	trna_sum = maps['cases_to_trna_sum'] @ relative_trnas
	saturation_trnas = relative_trnas / (1 + trna_sum)
	v_charge = (k_cat
		* c_synthetase
		* saturation_amino_acid
		* saturation_trnas)

	# Calculate distribution of codon reading across trnas
	# Note: columns of codons_to_trnas sum to 1
	c_trnas_charged = (1 - (maps['f_to_cases'] @ f)) * c_trnas
	tile = np.tile(c_trnas_charged, (len(v_codons), 1)).T
	codons_to_trnas = np.where(maps['codon_cases_to_trna_cases'], tile, 0)
	denominator = codons_to_trnas.sum(axis=0)
	denominator[denominator == 0] = 1 # to prevent divide by 0
	codons_to_trnas = np.divide(codons_to_trnas, denominator)

	# Calculate usage rate of each charged trna
	v_usage = codons_to_trnas @ v_codons

	# Steady-state cost
	steady_state_error = np.sum(
		np.square(
			1 - (v_charge / v_usage)
			)
		)

	############################################################

	# Calculate charging rate of each free trna
	relative_trnas = ((maps['f_to_cases'] @ min_f)
		* c_trnas
		/ (maps['K_T_to_cases'] @ K_T))
	trna_sum = maps['cases_to_trna_sum'] @ relative_trnas
	saturation_trnas = relative_trnas / (1 + trna_sum)
	v_charge_min = (k_cat
		* c_synthetase_min
		* saturation_amino_acid
		* saturation_trnas)

	# Calculate distribution of codon reading across trnas
	# Note: columns of codons_to_trnas sum to 1
	c_trnas_charged = (1 - (maps['f_to_cases'] @ min_f)) * c_trnas
	tile = np.tile(c_trnas_charged, (len(v_codons), 1)).T
	codons_to_trnas = np.where(maps['codon_cases_to_trna_cases'], tile, 0)
	denominator = codons_to_trnas.sum(axis=0)
	denominator[denominator == 0] = 1 # to prevent divide by 0
	codons_to_trnas = np.divide(codons_to_trnas, denominator)

	# Calculate usage rate of each charged trna
	v_usage_min = codons_to_trnas @ v_codons

	# Steady-state cost
	min_steady_state_error = np.sum(
		np.square(
			1 - (v_charge_min / v_usage_min)
			)
		)

	############################################################

	# Bounds penalty
	bounds_penalty = sum((1 / (f - 0.05)) + (1 / (0.95 - f)))
	bounds_penalty += sum((1 / (min_f - 0.05)) + (1 / (0.95 - min_f)))

	############################################################

	# EXT-PORT-11: charged-fraction anchor.
	#
	# The target is an AGGREGATE (the published numbers are proteome-wide aggregate charged
	# fractions), but the optimiser solves one amino-acid system at a time, so it is applied here as
	# the abundance-weighted mean charged fraction of THIS synthetase's tRNAs, per condition. If
	# every system hits its target the proteome-wide aggregate equals the target; if they do not,
	# the residual is visible per synthetase rather than hidden in a global sum. Weighting by
	# c_trnas is what makes the per-system mean comparable to a bulk measurement, which is a
	# pool-weighted quantity, not a per-isoacceptor average.
	#
	# Applied to `f` only, NOT to `min_f`, unless anchor_min_f is set. min_f is the charged fraction
	# at a swept-down minimum synthetase abundance -- a robustness margin, a regime the cell is by
	# construction NOT in when the measurement was taken. Anchoring it to a measured value would be
	# a category error. The switch exists so that choice is visible rather than implicit.
	#
	# `anchor_targets` is empty by default, so anchor_error is exactly 0.0 and adding
	# (w_a * 0.0) to `errors` leaves the sum bit-identical to v3.0.1.
	if len(anchor_targets):
		charged = 1 - (maps['f_to_cases'] @ f)
		pool = maps['cases_to_anchored_conditions'] @ c_trnas
		anchor_error = np.sum(np.square(
			((maps['cases_to_anchored_conditions'] @ (charged * c_trnas)) / pool)
			- anchor_targets))

		if anchor_min_f:
			charged = 1 - (maps['f_to_cases'] @ min_f)
			anchor_error += np.sum(np.square(
				((maps['cases_to_anchored_conditions'] @ (charged * c_trnas)) / pool)
				- anchor_targets))
	else:
		anchor_error = 0.0

	############################################################

	errors = [

		# Steady state errors
		steady_state_error,
		min_steady_state_error,

		# Penalties
		(w_r * sum(K_T)),
		(w_b * bounds_penalty),

		# EXT-PORT-11 anchor (0.0 unless a target was selected)
		(w_a * anchor_error),

		]

	error = sum(errors)

	return error


class Relation(object):
	""" Relation """

	def __init__(self, raw_data, sim_data):
		self._build_cistron_to_monomer_mapping(raw_data, sim_data)
		self._build_monomer_to_mRNA_cistron_mapping(raw_data, sim_data)
		self._build_monomer_to_tu_mapping(raw_data, sim_data)
		self._build_RNA_to_tf_mapping(raw_data, sim_data)
		self._build_tf_to_RNA_mapping(raw_data, sim_data)

		# Relate tRNAs, codons, and translation. Ported from CovertLab/WholeCellEcoliRelease v3.0.1
		# (Choi & Covert 2023, NAR 51(12):5911, doi:10.1093/nar/gkad435) with permission from
		# Prof. Covert. Consumed only by the kinetic-tRNA-charging elongation model; the default
		# SteadyStateElongationModel path is unchanged. See docs/MODEL_EXTENSION.md EXT-PORT.
		self._build_codon_sequences(raw_data, sim_data)
		self._build_codon_based_translation(raw_data, sim_data)
		self._build_codon_dependent_trna_charging(raw_data, sim_data)
		self._build_trna_charging_kinetics(raw_data, sim_data)

	def _build_cistron_to_monomer_mapping(self, raw_data, sim_data):
		"""
		Build a vector that can map vectors that describe a property for RNA
		cistrons into a vector that describes the same property for the
		corresponding monomers if used as an index array. Assumes that each
		monomer maps to a single RNA cistron (A single RNA can map to multiple
		monomers).

		e.g.
		monomer_property = RNA_cistron_property[
			sim_data.relation.cistron_to_monomer_mapping]
		"""
		# Map cistron IDs to indexes given in cistron_data (rnas.tsv)
		cistron_id_to_index = {
			cistron_id: i for i, cistron_id
			in enumerate(sim_data.process.transcription.cistron_data['id'])
			}

		# List the cistron_data indexes of cistron IDs in the order of
		# corresponding cistrons given in monomer_data (proteins.tsv)
		self.cistron_to_monomer_mapping = np.array([
			cistron_id_to_index[cistron_id] for cistron_id
			in sim_data.process.translation.monomer_data['cistron_id']
			])

	def _build_monomer_to_mRNA_cistron_mapping(self, raw_data, sim_data):
		"""
		Builds a sparse matrix that can map vectors that describe a property
		for protein monomers into a vector that describes the same property for
		the corresponding mRNA cistrons if multiplied to the right of the
		original vector. The transformed property must be additive (i.e. if two
		proteins map to the same cistron, the values given for the two proteins
		are added to yield a value for the cistron).

		The full matrix can be returned by calling 
		monomer_to_mRNA_cistron_mapping().
		"""
		# Initialize sparse matrix variables
		self._monomer_to_mRNA_cistron_mapping_i = []
		self._monomer_to_mRNA_cistron_mapping_j = []
		self._monomer_to_mRNA_cistron_mapping_v = []
		self._monomer_to_mRNA_cistron_mapping_shape = (
			len(sim_data.process.translation.monomer_data),
			sim_data.process.transcription.cistron_data['is_mRNA'].sum()
		)

		# Build mapping from mRNA ID to mRNA index
		mRNA_data = sim_data.process.transcription.cistron_data[
			sim_data.process.transcription.cistron_data['is_mRNA']]
		mRNA_id_to_index = {
			mRNA['id']: j for j, mRNA in enumerate(mRNA_data)
		}

		# Build sparse matrix
		for i, monomer in enumerate(sim_data.process.translation.monomer_data):
			self._monomer_to_mRNA_cistron_mapping_i.append(i)
			self._monomer_to_mRNA_cistron_mapping_j.append(
				mRNA_id_to_index[monomer['cistron_id']])
			self._monomer_to_mRNA_cistron_mapping_v.append(1)

	def monomer_to_mRNA_cistron_mapping(self):
		"""
		Returns the full version of the sparse matrix built by
		_build_monomer_to_mRNA_cistron_mapping().

		e.g.
		mRNA_property = sim_data.relation.monomer_to_mRNA_cistron_mapping().T.dot(
			monomer_property)
		"""
		out = np.zeros(self._monomer_to_mRNA_cistron_mapping_shape, dtype=np.float64)
		out[self._monomer_to_mRNA_cistron_mapping_i, self._monomer_to_mRNA_cistron_mapping_j] = self._monomer_to_mRNA_cistron_mapping_v
		return out

	def _build_monomer_to_tu_mapping(self, raw_data, sim_data):
		"""
		Builds a dictionary that maps monomer IDs to a list of all transcription
		unit IDs that the monomer can be translated from.
		"""
		self.monomer_index_to_tu_indexes = {
			i: sim_data.process.transcription.cistron_id_to_rna_indexes(monomer['cistron_id'])
			for i, monomer in enumerate(sim_data.process.translation.monomer_data)
			}

	def _build_RNA_to_tf_mapping(self, raw_data, sim_data):
		"""
		Builds a dictionary that maps RNA IDs to a list of all transcription
		factor IDs that regulate the given RNA. All TFs that target any of the
		constituent cistrons in the RNA are added to each list.
		"""
		cistron_ids = sim_data.process.transcription.cistron_data['id']

		self.rna_id_to_regulating_tfs = {}
		for rna_id in sim_data.process.transcription.rna_data['id']:
			tf_list = []
			for cistron_index in sim_data.process.transcription.rna_id_to_cistron_indexes(rna_id):
				tf_list.extend(
					sim_data.process.transcription_regulation.target_tf.get(
						cistron_ids[cistron_index], []))

			# Remove duplicates and sort
			self.rna_id_to_regulating_tfs[rna_id] = sorted(set(tf_list))

	def _build_tf_to_RNA_mapping(self, raw_data, sim_data):
		"""
		Builds a dictionary that maps transcription factor IDs to a list of all
		RNA IDs that are targeted by the given TF. All RNA transcription units
		that contain any of the cistrons regulated by the TF are added to each
		list.
		"""
		self.tf_id_to_target_RNAs = {}
		for (rna_id, tf_list) in self.rna_id_to_regulating_tfs.items():
			for tf_id in tf_list:
				self.tf_id_to_target_RNAs.setdefault(tf_id, []).append(rna_id)

	def _build_codon_sequences(self, raw_data, sim_data):
		""" Builds the effective codon sequences. """

		def assemble_coding_segments(rna_sequence, coding_segments):
			"""
			Uses coding segments to parse the rna sequence and assemble
			the effective codon sequence.

			rna_sequence (Bio.Seq.Seq): RNA sequence
			coding_segments (List of Lists): describes the start and end
				positions of each coding segment
			"""
			sequence = ''
			for coding_segment in coding_segments:
				start, end = coding_segment
				start -= 1
				end -= 1
				sequence += rna_sequence[start:end+1]
			return sequence

		# Describe coding opal codons (UGA)
		# Note: if more coding UGA codons are discovered in the future,
		# update this dict. Or, optionally retrive this data directly
		# from EcoCyc. At the time of writing this code, it was
		# determined that coding UGA codons are rare and possibly slow
		# to discover instances, so hard-coding was decided.
		coding_opal = {
			'FDNG-MONOMER': 195,
			'FDOG-MONOMER': 195,
			'FORMATEDEHYDROGH-MONOMER': 139,
			}

		# Describe coding segments (describes ribosomal frame shifts and
		# downstream start codons).
		coding_segments = {}
		for rna in raw_data.rnas:

			if len(rna['coding_segments']) == 0:
				continue

			for monomer_id, coding_segment in zip(
					rna['monomer_ids'], rna['coding_segments']):

				if len(coding_segment) == 0:
					continue

				coding_segments[monomer_id] = coding_segment

		# Get sequences
		protein_ids = sim_data.process.translation.monomer_data['id']
		protein_sequences = sim_data.getter.get_sequences(
			[protein_id[:-3] for protein_id in protein_ids])
		# EXT-PORT-1C adaptation. Each cistron's mRNA is parsed from ITS OWN GENE's genome coordinates.
		#
		# v3.0.1 read each monomer's mRNA out of `rna_data`, whose rows were one-per-cistron in that tree
		# because it ran with operons OFF. Here `rna_data` is TRANSCRIPTION UNITS while
		# `cistron_to_monomer_mapping` indexes CISTRONS, and `getter._sequences` is keyed by TU ids plus only
		# the RNA ids of genes belonging to no TU — so most cistron ids are not keys at all.
		#
		# Slicing the cistron out of a transcription unit with `cistron_start_end_pos_in_tu` reproduces this
		# sequence for 4535 of 4539 cistrons, but it is NOT equivalent. Four cistrons overhang their TU's 5'
		# end — wza/G7107, holC/EG11413, ytiC/G0-16686, dinG/EG11357 — and the assert at
		# transcription.py:823 only guards the 3' end, so for those four the stored offsets are silently
		# wrong. Measured head to head with scripts/probe_relation.py: the TU route leaves 3 monomers whose
		# mRNA does not translate to their protein, this route leaves 1.
		#
		# A cistron maps to exactly one gene, so there is no transcription unit to choose here and no
		# ambiguity to resolve — the 694 cistrons that sit in more than one TU simply stop being a question.
		# The parse is the same construction getter_functions.py:187-200 uses for monocistronic RNAs.
		genome_sequence = raw_data.genome_sequence

		def parse_cistron_sequence(cistron_id, left_end_pos, right_end_pos, direction):
			"""Genome slice for one cistron. Behaviourally identical to
			GetterFunctions._build_rna_sequences.parse_sequence: coordinates are 1-indexed and inclusive, and
			the '-' strand is reverse complemented over the SAME window before transcription, so left/right
			stay genome coordinates rather than 5'/3' order."""
			if direction == '+':
				return genome_sequence[left_end_pos - 1:right_end_pos].transcribe()
			elif direction == '-':
				return genome_sequence[
					left_end_pos - 1:right_end_pos].reverse_complement().transcribe()
			else:
				raise ValueError(
					'Unidentified transcription direction {} given for {}'.format(
						direction, cistron_id))

		cistron_id_to_gene_id = {
			gene['rna_ids'][0]: gene['id'] for gene in raw_data.genes}
		gene_id_to_left_end_pos = {
			gene['id']: gene['left_end_pos'] for gene in raw_data.genes}
		gene_id_to_right_end_pos = {
			gene['id']: gene['right_end_pos'] for gene in raw_data.genes}
		gene_id_to_direction = {
			gene['id']: gene['direction'] for gene in raw_data.genes}

		# Built by iterating cistron_data['id'] itself, so the list is in cistron_data index space by
		# construction — the space cistron_to_monomer_mapping addresses.
		cistron_ids = sim_data.process.transcription.cistron_data['id']
		rna_sequences = []
		for cistron_id in cistron_ids:
			gene_id = cistron_id_to_gene_id[cistron_id]
			rna_sequences.append(parse_cistron_sequence(
				cistron_id,
				gene_id_to_left_end_pos[gene_id],
				gene_id_to_right_end_pos[gene_id],
				gene_id_to_direction[gene_id]))

		# This port indexed an array with the wrong index space once already, and it raised IndexError only
		# because the two arrays happened to differ in length. Assert the invariant instead of relying on
		# that luck: the row read for monomer i must be monomer i's own cistron.
		monomer_cistron_ids = sim_data.process.translation.monomer_data['cistron_id']
		assert len(rna_sequences) == len(cistron_ids)
		assert all(
			cistron_ids[self.cistron_to_monomer_mapping[i]] == monomer_cistron_ids[i]
			for i in range(len(monomer_cistron_ids))), (
			'cistron_to_monomer_mapping does not address cistron_data index space')

		# Note: Start codons are distinguished from non-starting AUGs.
		self.codons = ([sim_data.molecule_ids.start_codon]
			+ sim_data.molecule_groups.codons)
		codon_to_amino_acid = {codon: [] for codon in self.codons}

		# Build and verify codon sequences
		self._codon_sequences = {}
		# EXT-PORT-1C: monomers whose mRNA does not translate to their curated protein. Empty is the
		# expected state; anything in here is a knowledge-base limitation worth naming, not hiding.
		self.codon_sequence_mismatches = []
		for i, protein_id in enumerate(protein_ids):
			protein_id = protein_id[:-3]

			# Get mRNA sequence
			rna_sequence = rna_sequences[self.cistron_to_monomer_mapping[i]]

			# Represent ribosomal frame shifting
			if protein_id in coding_segments:
				rna_sequence = assemble_coding_segments(
					rna_sequence, coding_segments[protein_id])

			# Translate the mRNA sequence
			rna_sequence_translated = rna_sequence.translate()

			# Represent selenocysteine-coding opal codons
			if protein_id in coding_opal:
				opal = coding_opal[protein_id]
				rna_sequence_translated = (rna_sequence_translated[:opal]
					+ 'U' + rna_sequence_translated[opal+1:])

			# Remove stop codons
			stop = rna_sequence_translated.find('*')
			rna_sequence_translated = rna_sequence_translated[:stop]
			rna_sequence = str(rna_sequence[:stop*3])

			# Ensure all sequences begin with Methionine
			# Note: Translation initiation beginning on non-AUG start
			# codons also code for methionine because only initiator
			# tRNAs (charged with formylated methionine) can be
			# recognized by the inititation complex.
			rna_sequence_translated = 'M' + rna_sequence_translated[1:]

			# Get protein sequence
			protein_sequence = protein_sequences[i]

			# Verify codon sequence
			if rna_sequence_translated != protein_sequence:
				# EXT-PORT-1C adaptation: RECORD instead of `continue`.
				#
				# Upstream drops the monomer here, which is not survivable: the very next method,
				# _build_codon_based_translation, subscripts _codon_sequences for EVERY monomer, so one warning
				# becomes a KeyError seconds later and ParCa cannot finish at all.
				#
				# Three of 4310 monomers land here, and the data is IDENTICAL in v3.0.1 — same protein
				# sequences, same gene coordinates, same empty coding_segments (checked against
				# WholeCellEcoliRelease v3.0.1 rnas.tsv / genes.tsv / proteins.tsv). So this is a pre-existing
				# annotation limitation, not something the port introduced:
				#   PHNE-MONOMER     phnE1, the MG1655 8-bp insertion. v3.0.1 sidesteps it by typing
				#                    EG11283_RNA as 'pseudo', which EXCLUDED_RNA_TYPES then drops; this tree
				#                    types it 'mRNA', so it stays in scope. The only row whose type differs.
				#   EG11357-MONOMER  dinG. In-frame stop 2 residues early; no offset in the TU reproduces the
				#                    curated 716-mer (searched +/-300 nt).
				#   MONOMER0-4391    ytiC. Stop at the second codon.
				#
				# Keeping the mRNA-derived sequence makes those three differ from their curated protein by a
				# few residues. Dropping them instead would leave them with NO codon sequence, i.e. a protein
				# the kinetic model can never elongate. Wrong by two residues beats never synthesised, and
				# neither is silent: the warning fires and the list is on sim_data.relation.
				warnings.warn('mRNA sequence does not match the protein '
					'sequence for {}'.format(protein_id))
				self.codon_sequence_mismatches.append(protein_id)

			# Parse effective mRNA sequence into codons
			codon_sequence = [rna_sequence[j:j+3]
				for j in range(0, len(rna_sequence), 3)]

			# Distinguish start codons
			codon_sequence[0] = sim_data.molecule_ids.start_codon
			self._codon_sequences[protein_id] = codon_sequence

			# Record codon to amino acid interactions
			# EXT-PORT-1C: the recorded mismatches are excluded from THIS accumulation, though their codon
			# sequence is kept above. Their mRNA and protein disagree by construction, so their
			# codon->amino-acid pairs are not evidence of anything — and feeding them in trips the
			# overloaded-codon assert below with a mapping that is genuinely inconsistent.
			if protein_id in self.codon_sequence_mismatches:
				continue
			for codon, amino_acid in zip(codon_sequence, protein_sequence):
				if amino_acid not in codon_to_amino_acid[codon]:
					codon_to_amino_acid[codon].append(amino_acid)

		# Check for overloaded codons
		assert np.all(np.array(
			[len(amino_acids) for amino_acids in codon_to_amino_acid.values()]
			) <= 1)

		# EXT-PORT-7: ...and for UNASSIGNED ones, which the check above does not cover. This mapping is
		# derived empirically by observing (codon, amino acid) pairs across the proteome, so a codon that no
		# protein happens to use gets an EMPTY list rather than an error. That becomes an all-zero column in
		# codons_to_amino_acids, and the residue-weight loop below then does `np.where(col)[0][0]` on it and
		# raises IndexError from a line that has nothing to do with the cause. Measured on this build: all 63
		# columns sum to exactly 1, so this holds today and the assert is here to catch drift.
		unassigned = [codon for codon, amino_acids in codon_to_amino_acid.items() if len(amino_acids) == 0]
		assert not unassigned, (
			'no amino acid was observed for codon(s) {} anywhere in the proteome, so their columns of '
			'codons_to_amino_acids would be all-zero'.format(unassigned))

		# Map from amino acids to codons
		self.amino_acid_to_codons = {amino_acid: []
			for amino_acid in sim_data.molecule_groups.amino_acids}

		for codon, amino_acid in codon_to_amino_acid.items():
			if len(amino_acid) == 0:
				continue

			amino_acid_id = sim_data.amino_acid_code_to_id_ordered[
				amino_acid[0]]

			if codon not in self.amino_acid_to_codons[amino_acid_id]:
				self.amino_acid_to_codons[amino_acid_id].append(codon)

		# Map from codons to amino acids (matrix)
		amino_acids = sim_data.molecule_groups.amino_acids
		self.codons_to_amino_acids = np.zeros(
			(len(amino_acids), len(self.codons)), dtype=np.int8)
		for i, amino_acid in enumerate(amino_acids):
			for codon in self.amino_acid_to_codons[amino_acid]:
				j = self.codons.index(codon)
				self.codons_to_amino_acids[i, j] = 1

	def _build_codon_based_translation(self, raw_data, sim_data):
		"""
		Builds tools used during simulation of polypeptide elongation.

		Notably:
		codon_sequences (analogous to translation_sequences)
		residue_weights_by_codon (analogous to translation_monomer_weights)
		"""

		# Get sequences
		translation = sim_data.process.translation
		protein_ids = translation.monomer_data['id']
		molecule_ids = [protein_id[:-3] for protein_id in protein_ids]
		sequences = [self._codon_sequences[molecule_id]
			for molecule_id in molecule_ids]

		# Calculate the number of columns required to read beyond
		# (towards the C-terminal) the longest mRNA coding region.
		# Note: For polypeptides undergoing N-terminal cleavage of the
		# initial methionine, their sequences (built here) are the
		# pre-cleavage sequence.
		# EXT-PORT-10: pad for the WIDER of the two windows that read this array, plus next_aa_pad.
		#
		# Upstream padded by max_time_step * R_max only. TWO readers disagree with that:
		#   coarse  buildSequences(..., elongation_rates + next_aa_pad)   -> m*R_max + 1  = 31
		#   kinetic KineticTrnaChargingModel.elongation_rate / codon_sequences_width
		#           ceil(m*R_basal) + KINETIC_TRNA_CHARGING_WIDTH_BUFFER  -> 22 + 10     = 32
		# buildSequences raises iff position + width > ncol, and the maximum reachable position is
		# L_max - 1 = 2338 (a ribosome is deleted the step it reaches its terminal length; only MAP
		# substrates can sit at L, and the longest of those is 1320 aa). The old pad gave ncol 2369:
		# the coarse read passed with EXACTLY ZERO margin and the kinetic read overran by one column,
		# on one monomer, G7064-MONOMER[o] (yeeJ, 2339 aa).
		#
		# Do NOT 'restore' the upstream expression: it is correct only while max_time_step >= 1.2 s.
		# v3.0.1 ran at 2.0 s and had seven spare columns; this tree runs at 1.0 s and was short by one.
		# Cost of the fix is 3 columns = 12.9 kB (+0.127%) on a (4310, 2369) int8 array.
		coarse_window = (translation.max_time_step
			* sim_data.constants.ribosome_elongation_rate_max.asNumber(units.aa / units.s))
		kinetic_window = np.ceil(translation.max_time_step
			* sim_data.constants.ribosome_elongation_rate_basal.asNumber(units.aa / units.s)
			+ KINETIC_TRNA_CHARGING_WIDTH_BUFFER)
		max_len = np.int64(
			# Length of the open reading frame
			+ translation.monomer_data['length'].asNumber().max()

			# Max number of anticipated readings, by whichever elongation model reads widest
			+ max(coarse_window, kinetic_window)

			# ...and the extra position translation.py:317 pads for, which this expression omitted.
			# _evolveState_codon_aware indexes all_sequences at [i, sequence_elongations[i]] to find
			# the NEXT residue, one past the last one elongated.
			+ translation.next_aa_pad)

		self.codon_sequences = np.full(
			(len(sequences), max_len),
			polymerize.PAD_VALUE, dtype=np.int8)

		# Build mapping
		codon_mapping = {codon:i for i, codon in enumerate(self.codons)}

		# Build translation sequences
		codon_counts = []
		min_length = 1 + max(codon_mapping.values())
		for i, sequence in enumerate(sequences):
			for j, codon in enumerate(sequence):
				self.codon_sequences[i, j] = codon_mapping[codon]

			codon_count = np.bincount(
				self.codon_sequences[i, :j + 1], minlength=min_length)
			codon_counts.append(codon_count)
		self.codon_counts = np.array(codon_counts)

		# Describe residue masses
		# EXT-PORT-7: the loop below crosses TWO amino-acid orderings. `i` is a row index into
		# codons_to_amino_acids, which is ordered by molecule_groups.amino_acids (see
		# _build_codon_sequences), and it indexes translation_monomer_weights, which is ordered by
		# amino_acid_code_to_id_ordered.values() (translation.py). They are element-for-element equal in this
		# build, which is why this works — but nothing enforces it, and if they ever diverged every residue
		# weight would be silently PERMUTED with no error anywhere. Assert the coupling the code relies on.
		assert (list(sim_data.molecule_groups.amino_acids)
				== list(sim_data.amino_acid_code_to_id_ordered.values())), (
			'molecule_groups.amino_acids and amino_acid_code_to_id_ordered disagree, so the row index of '
			'codons_to_amino_acids can no longer be used to index translation_monomer_weights')
		residue_weights_by_codon = []
		for col, codon in enumerate(self.codons):
			i = np.where(self.codons_to_amino_acids[:, col])[0][0]
			residue_weights_by_codon.append(translation.translation_monomer_weights[i])
		self.residue_weights_by_codon = np.array(residue_weights_by_codon)

	def _build_codon_dependent_trna_charging(self, raw_data, sim_data):
		"""
		Builds tools used during simulation of tRNA charging.

		Notably:

		"""

		def is_base_pair(codon, anticodon):
			'''
			Returns True if codon and anticodon are base paired, False
			otherwise.

			Note: expects codon and anticodon in 5' to 3' direction.

			Example:
			codon 		5'-ABC-3'
			anticodon 	3'-XYZ-5'

			C and Z are the 'wobble' position
			'''
			for i, (C, A) in enumerate(zip(codon, anticodon[::-1])):

				# Wobble position
				if i == 2:
					return np.any(
						[watson_crick_base_pairing[A] == C,
						wobble_base_pairing[A] == C])

				# Non-wobble positions
				elif watson_crick_base_pairing[A] != C:
					return False

		# Base pairing rules
		watson_crick_base_pairing = {
			'A': 'U',
			'U': 'A',
			'G': 'C',
			'C': 'G'}
		wobble_base_pairing = {
			'A': '',
			'U': 'G',
			'G': 'U',
			'C': ''}

		# Map tRNAs to their anticodons
		# EXT-PORT-1C adaptation, and the one that unblocks the whole tRNA half of the port at once.
		# v3.0.1 took the tRNA list from `rna_data`, which is correct only when operons are OFF and
		# rna_data degenerates to one row per cistron. Here rna_data is TRANSCRIPTION UNITS, so that
		# list comes out ~42 long instead of 86 — and `dict(zip(free_trnas, charged_trnas))` would have
		# TRUNCATED to the shorter of the two without raising, quietly pairing the wrong tRNAs.
		#
		# `transcription.uncharged_trna_names` is the canonical list: cistron ids with a '[c]' tag
		# (transcription.py:1265). Everything the ported code needs is already aligned to it —
		# `charged_trna_names` one-for-one (asserted at transcription.py:1285), the 86 columns of
		# `aa_from_trna`, `molecule_groups.initiator_trnas`, the six hard-coded wobble tRNAs below, and
		# the K_M keys in flat/optimization/trna_charging_kinetics_solutions.tsv.
		#
		# The anticodon has to come from raw_data: it is a column of rnas.tsv but is propagated into
		# neither cistron_data nor rna_data, which is why `rna_data['anticodon']` raised KeyError.
		free_trnas = np.array(sim_data.process.transcription.uncharged_trna_names)
		anticodon_by_rna_id = {rna['id']: rna['anticodon'] for rna in raw_data.rnas}
		anticodons = [anticodon_by_rna_id[trna[:-3]] for trna in free_trnas]
		trna_to_anticodon = dict(zip(free_trnas, anticodons))
		assert len(trna_to_anticodon) == len(free_trnas)

		# Map free and charged tRNAs
		charged_trnas = sim_data.process.transcription.charged_trna_names
		free_to_charged = dict(zip(free_trnas, charged_trnas))
		self.charged_to_free = dict(zip(charged_trnas, free_trnas))

		# Describe initiator tRNAs
		free_initiators = sim_data.molecule_groups.initiator_trnas
		charged_initiators = [free_to_charged[trna] for trna in free_initiators]

		# Map codons to tRNAs
		transcription = sim_data.process.transcription
		self.codon_to_trnas = {codon: [] for codon in self.codons}
		self.amino_acid_to_trnas = {}

		for i, amino_acid in enumerate(sim_data.molecule_groups.amino_acids):

			# Get trnas
			trnas = free_trnas[np.where(transcription.aa_from_trna[i, :])[0]]
			self.amino_acid_to_trnas[amino_acid] = trnas.tolist()

			# Get codons
			codons = self.amino_acid_to_codons[amino_acid]

			for codon in codons:

				# Start codons are read by initiator trnas
				if codon == sim_data.molecule_ids.start_codon:
					self.codon_to_trnas[codon] = charged_initiators
					continue

				# Elongating AUG codons are read by elongator trnas
				elif codon == 'AUG':
					for trna in trnas:
						if trna not in free_initiators:
							self.codon_to_trnas[codon].append(
								free_to_charged[trna])
					continue

				# ARG trnas argQ, argV, argY, and argZ have inosine (a
				# derivative of adenine) at position 34 of the anticodon
				# stem loop (I34) via post-transcriptional modification,
				# which enables recognition of the cognate codon CGC and
				# wobble codons CGU and CGA.
				elif codon in ['CGA', 'CGC', 'CGU']:
					self.codon_to_trnas[codon] = [
						free_to_charged['argQ-tRNA[c]'],
						free_to_charged['argV-tRNA[c]'],
						free_to_charged['argY-tRNA[c]'],
						free_to_charged['argZ-tRNA[c]'],
						]
					continue

				# ILE trnas ileX and ileY have lysidine (a derivative
				# of cytidine) at position 34 of the anticodon stem loop
				# (L34) via post-transcriptional modification, which
				# enables recognition of the cognate codon AUA.
				elif codon == 'AUA':
					self.codon_to_trnas[codon] = [
						free_to_charged['ileX-tRNA[c]'],
						free_to_charged['RNA0-305[c]'],
						]
					continue

				for trna in trnas:
					if is_base_pair(codon, trna_to_anticodon[trna]):
						self.codon_to_trnas[codon].append(free_to_charged[trna])

				# Assign all tRNAs (that are known to deliver this
				# codon's amino acid) to this codon if no base pairing
				# rule can match this codon to a specific tRNA.
				if len(self.codon_to_trnas[codon]) == 0:
					print(f'Warning: No tRNAs were found to read codon {codon}.'
						f' Assigning all trnas for {amino_acid} to this codon.')
					self.codon_to_trnas[codon] = [free_to_charged[trna]
						for trna in trnas]

		# Map tRNAs to codons
		self.trnas_to_codons = np.zeros(
			(len(self.codons), len(free_trnas)), dtype=np.int8)
		for i, codon in enumerate(self.codons):
			for trna in self.codon_to_trnas[codon]:
				j = np.where(free_trnas == self.charged_to_free[trna])[0][0]
				self.trnas_to_codons[i, j] = 1

		# Describe tRNA-codon pairs
		self.trna_codon_pairs = []
		for col, trna in enumerate(free_trnas):
			for row in np.where(self.trnas_to_codons[:, col])[0]:
				codon = self.codons[row]
				self.trna_codon_pairs.append(f'{trna}_{codon}')

		# Remove lysU; lysU is thought to be used during elevated
		# temperatures, whereas lysS is normally used.
		row = sim_data.molecule_groups.amino_acids.index('LYS[c]')
		col = transcription.synthetase_names.index('LYSU-CPLX[c]')
		self.modified_aa_from_synthetase = np.copy(
			transcription.aa_from_synthetase)
		self.modified_aa_from_synthetase[row, col] = 0

		# Map amino acids to synthetases
		self.amino_acid_to_synthetase = {}
		for i, amino_acid in enumerate(sim_data.molecule_groups.amino_acids):
			synthetase = transcription.synthetase_names[
				np.where(self.modified_aa_from_synthetase[i, :])[0][0]]
			self.amino_acid_to_synthetase[amino_acid] = synthetase

	def _build_trna_charging_kinetics(self, raw_data, sim_data):
		'''
		Parses and stores kinetic parameters recorded in
		trna_charging_kinetics.tsv into the sim_data object.
		'''

		def update(sweep_degree, row):
			synthetase = row['synthetase_id']
			D = self.trna_charging_kinetics[sweep_degree]

			D['synthetase_to_k_cat'].update({synthetase: row['k_cat']})
			D['synthetase_to_K_A'].update({synthetase: row['K_M_amino_acid']})
			D['trna_to_K_T'].update(
				{k: self.conc_unit * v for k,v in row['K_M_trna'].items()})
			D['trna_condition_to_free_fraction'].update(row['f_free'])
			D['synthetase_to_objective'].update({synthetase: row['objective']})

			return

		# Units
		self.conc_unit = units.umol/units.L
		self.rate_unit = self.conc_unit/units.s

		# Store trna charging kinetics
		self.trna_charging_kinetics = {}
		for row in raw_data.optimization.trna_charging_kinetics_solutions:
			synthetase = row['synthetase_id']
			sweep_level = row['sweep_level']

			if sweep_level not in self.trna_charging_kinetics:
				self.trna_charging_kinetics[sweep_level] = {
					'synthetase_to_k_cat': {},
					'synthetase_to_K_A': {},
					'trna_to_K_T': {},
					'trna_condition_to_free_fraction': {},
					'synthetase_to_objective': {},
					}

			if synthetase not in self.trna_charging_kinetics\
				[sweep_level]['synthetase_to_objective']:
				update(sweep_level, row)

			elif row['objective'] < self.trna_charging_kinetics\
					[sweep_level]['synthetase_to_objective'][synthetase]:
				update(sweep_level, row)

		# Store defaults
		default_sweep_level = 4
		self.synthetase_to_k_cat = self.trna_charging_kinetics\
			[default_sweep_level]['synthetase_to_k_cat']
		self.synthetase_to_K_A = self.trna_charging_kinetics\
			[default_sweep_level]['synthetase_to_K_A']
		self.trna_to_K_T = self.trna_charging_kinetics\
			[default_sweep_level]['trna_to_K_T']
		self.trna_condition_to_free_fraction = self.trna_charging_kinetics\
			[default_sweep_level]['trna_condition_to_free_fraction']

		# Store constants
		self.trna_charging_constants = {}
		for row in raw_data.optimization.trna_charging_kinetics_constants:
			key = row['synthetase_id__condition']
			self.trna_charging_constants[key] = {}

			for k, v in row.items():
				if k == key:
					continue
				self.trna_charging_constants[key][k] = v

		# Store tRNA synthetase abundances observed from sample
		# simulations
		self.trna_synthetase_samples = {}
		for row in raw_data.optimization.trna_synthetase_dynamic_range:
			key = row['synthetase_condition']
			self.trna_synthetase_samples[key] = {}
			self.trna_synthetase_samples[key]['mean'] = row['mean']
			self.trna_synthetase_samples[key]['std'] = row['std']
			self.trna_synthetase_samples[key]['min'] = row['min']

		# Store curated kinetics
		self.synthetase_to_max_curated_k_cats = {}
		for row in raw_data.trna_charging_kinetics_curated:
			synthetase = row['Synthetase']
			k_cat_max = row['max k_cat']
			self.synthetase_to_max_curated_k_cats[synthetase] = k_cat_max

		return

	def optimize_trna_charging_kinetics(self, sim_data, cell_specs,
			charged_fraction_target=None,
			charged_fraction_weight=None,
			anchor_min_f=False,
			regularization_weight=1e-9,
			bounds_penalty_weight=1e-9,
			iterations=100,
			viable_solutions=10):
		'''
		Optimizes kinetic parameters describing tRNA charging reactions.
		- Aims to minimize differences between the rates of tRNA
		  aminoacylation and aminoacyl-tRNA utilization (by ribosomes).
		- Holds to the principle that protein content of the cell grows
		  exponentially and doubles at the measured doubling time.

		EXT-PORT-11 parameters. All five default to the v3.0.1 behaviour, so calling this with no
		keywords is the upstream fit:

		charged_fraction_target -- the anchor. A key of TRNA_CHARGED_FRACTION_TARGETS, an explicit
			'basal=0.55,with_aa=none' string, a dict, or None for the documented default ('none',
			i.e. no anchor). See the EXT-PORT-11 block at the top of this module for the candidates
			and their provenance. It is a PARAMETER and not a constant because the candidates
			conflict and the choice is scientific.
		charged_fraction_weight -- w_a. None takes TRNA_CHARGED_FRACTION_WEIGHT_DEFAULT (1e-6),
			whose derivation is documented at that constant.
		anchor_min_f -- also anchor the charged fraction at the swept-down minimum synthetase.
			Default False: that regime is a robustness margin, not a measured condition.
		regularization_weight -- w_r. The term that ACTUALLY selects among feasible solutions
			(min sum K_T), and therefore the one an anchor competes with. Exposed so a refit can
			report the trade rather than assert it. Default is the shipped 1e-9.
		bounds_penalty_weight -- w_b. The barrier is symmetric about f = 0.5, so it carries an
			accidental, un-cited pull toward a 50% charged fraction and is 40-88% of the objective
			at the shipped optima. When an anchor is on, two terms are then acting on f. This is
			NOT zeroed automatically -- doing so silently would change the numerical conditioning
			of a fit whose feasibility is enforced by a hard filter. Set it to 0.0 explicitly to
			let the anchor act alone, and say so in the run's provenance. Default is the shipped
			1e-9.
		iterations, viable_solutions -- the random-restart budget per (synthetase, sweep level).
			Shipped values are 100 and 10; the loop runs `while iteration < iterations or
			viable_solution < viable_solutions`, so the cost of a full fit is >= 8080 Powell
			minimisations and order hours SERIALLY (there is no multiprocessing in this method).
			Exposed ONLY so a scouting run is possible before committing that time -- e.g.
			iterations=3, viable_solutions=1 finishes a single synthetase in seconds. A scouting
			run is NOT a fit: with 3 restarts the optimiser has not searched, and its output must
			never be adopted as constants. Anything published must use the shipped budget.
		'''

		objective = trna_charging_objective

		def full_saturation_amino_acid(c_amino_acid, c_synthetase,
				v_codons_total):
			'''
			V_rich / V_poor = ((E_rich / E_poor)
				* (sat_A_rich / sat_A_poor)
				* (sat_T_rich / sat_T_poor))

			Assuming:
			1) sat_A_rich = 1
			2) sat_T_poor = sat_T_rich

			V_rich / V_poor = (E_rich / E_poor) * (1 / sat_A_poor)
			sat_A_poor = (E_rich / E_poor) / (V_rich / V_poor)
			           = A_poor / (K_A + A_poor)
			(K_A + A_poor) = A_poor / (E_rich / E_poor) * (V_rich / V_poor)
			K_A = A_poor * ((V_rich / V_poor) / (E_rich / E_poor)  - 1)
			'''
			A_poor, A_rich = c_amino_acid[condition_start_indexes]
			E_poor, E_rich = c_synthetase[condition_start_indexes]
			V_poor, V_rich = v_codons_total
			K_A = A_poor * ((V_rich / V_poor) / (E_rich / E_poor)  - 1)
			return np.log10(K_A)

		def get_random_initial_solution(c_synthetase, c_amino_acid,
				c_trnas, v_codons_total, maps, n_K_T, n_f, indexes,
				condition_start_indexes, K_T_range,
				assume_full_saturation):
			'''
			Random initialization
			'''

			initial_solution = np.zeros(indexes['n_parameters'], np.float64)

			# K_A
			if assume_full_saturation:
				K_A = full_saturation_amino_acid(
					c_amino_acid, c_synthetase, v_codons_total)

			else:
				K_A = np.random.uniform(
					np.min(np.log10(c_amino_acid)),
					np.max(np.log10(c_amino_acid)),
					1)[0]
			initial_solution[indexes['K_A_index']] = K_A

			# K_T
			K_T = np.random.uniform(K_T_range[0], K_T_range[1], n_K_T)
			initial_solution[indexes['K_T_slice']] = K_T

			# f
			n_f = n_conditions * n_K_T
			f = np.log10(np.random.uniform(0.1, 0.9, n_f))
			# f = np.log10(np.random.uniform(0.1, 0.15, n_f))
			initial_solution[indexes['f_slice']] = f

			# Solve for k_cat
			K_A = np.power(10, K_A)
			K_T = np.power(10, K_T)
			f = np.power(10, f)

			saturation_amino_acid = c_amino_acid / (K_A + c_amino_acid)
			relative_trnas = ((maps['f_to_cases'] @ f)
				* c_trnas
				/ (maps['K_T_to_cases'] @ K_T))
			trna_sum = maps['cases_to_trna_sum'] @ relative_trnas
			saturation_trnas = (trna_sum[condition_start_indexes]
				/ (1 + trna_sum[condition_start_indexes]))
			k_cat = np.max(v_codons_total
				/ c_synthetase[condition_start_indexes]
				/ saturation_amino_acid[condition_start_indexes]
				/ saturation_trnas)
			initial_solution[indexes['k_cat_index']] = np.log10(k_cat)

			# f (min)
			min_f = np.log10(np.random.uniform(0.1, 0.9, n_f))
			# min_f = np.log10(np.random.uniform(0.85, 0.9, n_f))
			initial_solution[indexes['min_f_slice']] = min_f

			return initial_solution

		################################################################
		# Optimize tRNA Charging Kinetics and save results

		trna_charging_kinetics_solutions = [[
			'"synthetase_id"',
			'"sweep_level"',
			'"iteration"',
			'"objective"',
			'"k_cat (1/units.s)"',
			'"K_M_amino_acid (units.umol/units.L)"',
			'"K_M_trna"',
			'"f_free"',
			'"f_free_at_min"',
			]]

		trna_charging_kinetics_constants = [[
			'"synthetase_id__condition"',
			'"synthetase (units.umol/units.L)"',
			'"amino_acid (units.umol/units.L)"',
			'"trnas"',
			'"codons"',
			]]

		# Describe weights
		# EXT-PORT-11: these were hard-coded literals in v3.0.1. They are now the defaults of the
		# two keyword arguments, so the values are unchanged for every existing caller and a refit
		# can vary them without editing the model source.
		w_b = bounds_penalty_weight # bounds
		w_r = regularization_weight # regularization

		# EXT-PORT-11: the charged-fraction anchor. Resolved ONCE, here, so that an unknown target
		# name fails before any of the ~8080 minimisations start rather than hours in.
		charged_fraction_target = resolve_charged_fraction_target(charged_fraction_target)
		w_a = (TRNA_CHARGED_FRACTION_WEIGHT_DEFAULT if charged_fraction_weight is None
			else float(charged_fraction_weight))

		unknown_conditions = sorted(set(charged_fraction_target) - set(self.conditions))
		if unknown_conditions:
			raise ValueError(
				'charged-fraction target names condition(s) {} that this fit does not solve; it '
				'solves {}. A target for a condition that is never optimised is silently '
				'ignored, so this is an error rather than a warning.'.format(
					unknown_conditions, list(self.conditions)))

		anchored_conditions = [condition for condition in self.conditions
			if charged_fraction_target.get(condition) is not None]
		anchor_targets = np.array(
			[charged_fraction_target[condition] for condition in anchored_conditions],
			dtype=np.float64)

		print('EXT-PORT-11 charged-fraction anchor: {}'.format(
			'OFF (f is a free variable, as in v3.0.1)' if not anchored_conditions
			else '{} (w_a={:g}, w_r={:g}, w_b={:g}, anchor_min_f={})'.format(
				{c: charged_fraction_target[c] for c in anchored_conditions},
				w_a, w_r, w_b, anchor_min_f)))

		# Bounds
		f_lower_bound = 0.051
		f_upper_bound = 0.949

		# Iterations
		# EXT-PORT-11: were hard-coded literals in v3.0.1; now the defaults of two keyword
		# arguments, so every existing caller gets the same budget and a scouting run is possible.

		# Other parameters used during optimization
		K_T_range = [1, 3]
		n_conditions = len(self.conditions)
		n_increments = 5
		sweep_levels = np.arange(2, n_increments + 1)
		upper_bound = 10 # log

		# Optimize each amino acid system individually
		for amino_acid in sim_data.molecule_groups.amino_acids:
			if amino_acid == 'L-SELENOCYSTEINE[c]':
				continue

			# Get molecules
			synthetase = self.amino_acid_to_synthetase[amino_acid]
			trnas = self.amino_acid_to_trnas[amino_acid]
			codons = self.amino_acid_to_codons[amino_acid]

			# Get constants
			(c_synthetase, c_amino_acid, c_trnas, v_codons, v_codons_total,
				trna_charging_kinetics_constants) = self.get_constants(
					synthetase,
					amino_acid,
					trnas,
					codons,
					sim_data,
					cell_specs,
					trna_charging_kinetics_constants,
					)

			# Build maps
			n_K_T, K_T_indexes, codons_to_trnas = self.assign_K_T(trnas, codons)

			cases = []
			for condition in self.conditions:
				for trna in trnas:
					cases.append(f'{trna}__{condition}')
			n_cases = len(cases)

			f_to_cases = np.zeros(
				(n_cases, n_K_T * n_conditions), dtype=np.int64)
			for row, case in enumerate(cases):
				trna, condition = case.split('__')
				K_T_index = K_T_indexes[trnas.index(trna)]
				col = (self.conditions.index(condition) * n_K_T) + K_T_index
				f_to_cases[row, col] = 1

			K_T_to_cases = np.zeros((n_cases, n_K_T), dtype=np.int64)
			for row, case in enumerate(cases):
				trna, condition = case.split('__')
				col = K_T_indexes[trnas.index(trna)]
				K_T_to_cases[row, col] = 1

			cases_to_trna_sum = np.zeros((n_cases, n_cases), dtype=np.int64)
			for row, case in enumerate(cases):
				trna, condition = case.split('__')
				cols = [condition in case for case in cases]
				cases_to_trna_sum[row, cols] = 1

			codon_cases_to_trna_cases = np.zeros(
				(n_cases, len(codons) * n_conditions), dtype=np.bool_)
			for i in range(n_conditions):
				rows = slice(i * len(trnas), (i+1) * len(trnas))
				cols = slice(i * len(codons), (i+1) * len(codons))
				codon_cases_to_trna_cases[rows, cols] = codons_to_trnas

			# EXT-PORT-11: (n_anchored_conditions, n_cases) selector used by the anchor term to
			# form the abundance-weighted mean charged fraction of this synthetase's tRNAs, one
			# row per condition that carries a target. Built here rather than inside the objective
			# because it is constant across the ~100 restarts x 4 sweep levels of this synthetase.
			#
			# It is deliberately (0, n_cases) when nothing is anchored -- the empty case is then
			# the same code path, not a special case, and the anchor error is exactly 0.0.
			#
			# `case.split('__')` is safe: cases are f'{trna}__{condition}' and neither a tRNA id
			# nor 'with_aa' contains a double underscore. The v3.0.1 code above relies on the same
			# invariant (see the three loops just above).
			cases_to_anchored_conditions = np.zeros(
				(len(anchored_conditions), n_cases), dtype=np.int64)
			for row, anchored_condition in enumerate(anchored_conditions):
				for col, case in enumerate(cases):
					if case.split('__')[1] == anchored_condition:
						cases_to_anchored_conditions[row, col] = 1
			assert (len(anchored_conditions) == 0
				or cases_to_anchored_conditions.sum() == len(anchored_conditions) * len(trnas)), (
				'the anchor selector did not match every tRNA of every anchored condition')

			maps = {
				'f_to_cases': f_to_cases,
				'K_T_to_cases': K_T_to_cases,
				'cases_to_trna_sum': cases_to_trna_sum,
				'codon_cases_to_trna_cases': codon_cases_to_trna_cases,
				'cases_to_anchored_conditions': cases_to_anchored_conditions,
				}

			condition_start_indexes = np.arange(0, n_cases, len(trnas))
			condition_indexes = {k: np.arange(0, n_K_T) + (k * n_K_T)
				for k in range(n_conditions)}

			# Set indexes
			n_f = n_conditions * n_K_T
			k_cat_index = 0
			K_A_index = 1
			K_T_slice = slice(2, 2 + n_K_T)
			f_slice = slice(K_T_slice.stop, K_T_slice.stop + n_f)
			min_f_slice = slice(f_slice.stop, f_slice.stop + n_f)
			n_parameters = min_f_slice.stop

			indexes = {
				'k_cat_index': k_cat_index,
				'K_A_index': K_A_index,
				'K_T_slice': K_T_slice,
				'f_slice': f_slice,
				'min_f_slice': min_f_slice,
				'condition_indexes': condition_indexes,
				'n_parameters': n_parameters,
				}

			# Bounds
			K_A = full_saturation_amino_acid(
				c_amino_acid, c_synthetase, v_codons_total)

			bounds_1 = [() for n in range(n_parameters)]
			bounds_1[k_cat_index] = (-2, upper_bound)
			bounds_1[K_A_index] = (K_A, K_A)
			bounds_1[K_T_slice] = [(-2, upper_bound)
				for n in range(n_K_T)]

			bounds_1[f_slice] = [(
				np.log10(f_lower_bound),
				np.log10(f_upper_bound),
				) for n in range(n_f)]
			bounds_1[min_f_slice] = [(
				np.log10(f_lower_bound),
				np.log10(f_upper_bound),
				) for n in range(n_f)]

			bounds_2 = bounds_1[:]
			bounds_2[K_A_index] = (-2, upper_bound)

			# Get the minimum trna synthetase concentration observed
			# from sample simulations
			synthetase_mins = []
			for condition in self.conditions:
				key = f'{synthetase}__{condition}'
				synthetase_mins.append(
					self.trna_synthetase_samples[key]['min']
					.asNumber(self.conc_unit)
					)
			synthetase_mins = np.array(synthetase_mins)

			# Sweep over the minimum tRNA synthetase value
			for sweep_level in sweep_levels:
				if print_optimization:
					print('='*20)
					print(amino_acid, sweep_level)
					print('='*20)

				# Calculate the minimum trna synthetase concentration
				# used in this sweep level
				c_synthetase_min = []
				for estimated_minimum in (sweep_level
						/ n_increments
						* synthetase_mins):
					for i in range(len(trnas)):
						c_synthetase_min.append(estimated_minimum)
				c_synthetase_min = np.array(c_synthetase_min)

				# Determine whether full amino acid saturation holds
				initial_solution = get_random_initial_solution(
					c_synthetase, c_amino_acid, c_trnas, v_codons_total,
					maps, n_K_T, n_f, indexes, condition_start_indexes,
					K_T_range, assume_full_saturation=True)

				result = minimize(
					objective,
					initial_solution,
					method='Powell',
					bounds=bounds_1,
					args=(
						indexes,
						maps,
						v_codons,
						c_synthetase,
						c_synthetase_min,
						c_amino_acid,
						c_trnas,
						# EXT-PORT-11: weights and anchor, formerly closed over / absent.
						w_r,
						w_b,
						w_a,
						anchor_targets,
						anchor_min_f,
						),
					options={
						'maxiter': 1000,
						'ftol': 1e-5,
						},
					)

				x = np.power(10, result.x)
				K_A = x[K_A_index]
				saturation_amino_acid = c_amino_acid / (K_A + c_amino_acid)
				assume_full_saturation = np.isclose(
					saturation_amino_acid[condition_start_indexes][1],
					0.99, atol=1e-2)

				if print_optimization:
					print(f'Assuming full AA saturation: {assume_full_saturation}')

				# Solve
				min_objective = np.inf
				# EXT-PORT-11: the argmin, kept so the objective can be DECOMPOSED after the
				# restart loop. Without it the run reports a scalar and the question the anchor
				# exists to answer -- is the anchor invisible, comparable, or dominant against
				# w_r*sum(K_T)? -- cannot be answered from the output at all.
				min_objective_x = None
				viable_solution = 0
				iteration = 0
				while (iteration < iterations) or (viable_solution < viable_solutions):

					# Option 1: Assume full saturation of amino acids
					if assume_full_saturation:

						# Initialize random initial solution
						initial_solution = get_random_initial_solution(
							c_synthetase, c_amino_acid, c_trnas, v_codons_total,
							maps, n_K_T, n_f, indexes, condition_start_indexes,
							K_T_range, assume_full_saturation=True)

						# Optimize
						result = minimize(
							objective,
							initial_solution,
							method='Powell',
							bounds=bounds_1,
							args=(
								indexes,
								maps,
								v_codons,
								c_synthetase,
								c_synthetase_min,
								c_amino_acid,
								c_trnas,
								# EXT-PORT-11: weights and anchor (full-AA-saturation branch).
								w_r,
								w_b,
								w_a,
								anchor_targets,
								anchor_min_f,
								),
							options={
								'maxiter': 1000,
								'ftol': 1e-5,
								},
							)


					# Option 2: Don't assume full saturation of amino acids
					else:

						# Initialize random initial solution
						initial_solution = get_random_initial_solution(
							c_synthetase, c_amino_acid, c_trnas, v_codons_total,
							maps, n_K_T, n_f, indexes, condition_start_indexes,
							K_T_range, assume_full_saturation=False)

						# Optimize
						result = minimize(
							objective,
							initial_solution,
							method='Powell',
							bounds=bounds_2,
							args=(
								indexes,
								maps,
								v_codons,
								c_synthetase,
								c_synthetase_min,
								c_amino_acid,
								c_trnas,
								# EXT-PORT-11: weights and anchor (partial-AA-saturation branch).
								w_r,
								w_b,
								w_a,
								anchor_targets,
								anchor_min_f,
								),
							options={
								'maxiter': 1000,
								'ftol': 1e-5,
								},
							)

					# Retrieve solution
					x = np.power(10, result.x)

					k_cat = x[k_cat_index]
					K_A = x[K_A_index]
					K_T = x[K_T_slice]
					f = x[f_slice]
					min_f = x[min_f_slice]

					# Calculate charging rate of each free trna
					saturation_amino_acid = c_amino_acid / (K_A + c_amino_acid)
					relative_trnas = ((maps['f_to_cases'] @ f)
						* c_trnas
						/ (maps['K_T_to_cases'] @ K_T))
					trna_sum = maps['cases_to_trna_sum'] @ relative_trnas
					saturation_trnas = relative_trnas / (1 + trna_sum)
					v_charge = (k_cat
						* c_synthetase
						* saturation_amino_acid
						* saturation_trnas)
					sat_T = trna_sum / (1 + trna_sum)

					# Calculate distribution of codon reading across trnas
					# Note: columns of codons_to_trnas sum to 1
					c_trnas_charged = (1 - (maps['f_to_cases'] @ f)) * c_trnas
					tile = np.tile(c_trnas_charged, (len(v_codons), 1)).T
					codons_to_trnas = np.where(maps['codon_cases_to_trna_cases'], tile, 0)
					denominator = codons_to_trnas.sum(axis=0)
					denominator[denominator == 0] = 1 # to prevent divide by 0
					codons_to_trnas = np.divide(codons_to_trnas, denominator)

					# Calculate usage rate of each charged trna
					v_usage = codons_to_trnas @ v_codons

					# Calculate charging rate of each free trna
					relative_trnas = ((maps['f_to_cases'] @ min_f)
						* c_trnas
						/ (maps['K_T_to_cases'] @ K_T))
					trna_sum = maps['cases_to_trna_sum'] @ relative_trnas
					saturation_trnas = relative_trnas / (1 + trna_sum)
					v_charge_min = (k_cat
						* c_synthetase_min
						* saturation_amino_acid
						* saturation_trnas)
					sat_T_min = trna_sum / (1 + trna_sum)

					# Calculate distribution of codon reading across trnas
					# Note: columns of codons_to_trnas sum to 1
					c_trnas_charged = (1 - (maps['f_to_cases'] @ min_f)) * c_trnas
					tile = np.tile(c_trnas_charged, (len(v_codons), 1)).T
					codons_to_trnas = np.where(maps['codon_cases_to_trna_cases'], tile, 0)
					denominator = codons_to_trnas.sum(axis=0)
					denominator[denominator == 0] = 1 # to prevent divide by 0
					codons_to_trnas = np.divide(codons_to_trnas, denominator)

					# Calculate usage rate of each charged trna
					v_usage_min = codons_to_trnas @ v_codons

					iteration += 1

					# Only save solutions that can maintain steady state
					if (np.max(np.abs(v_charge - v_usage)) > 1e-3
						or np.isnan(np.max(np.abs(v_charge - v_usage)))
						or np.max(np.abs(v_charge_min - v_usage_min)) > 1e-3
						or np.isnan(np.max(np.abs(v_charge_min - v_usage_min)))
						):
						continue

					if result.fun < min_objective:
						min_objective = result.fun
						min_objective_x = np.copy(result.x)   # EXT-PORT-11, see above

						if print_optimization:
							print('='*26)
							print('\nobj\t', f'{result.fun:.1e}')
							print('-'*26)
							print('k_cat\t', f'{k_cat:.2f}')
							print('K_A\t', f'{K_A:.2f}')
							print('K_T\t', np.round(K_T, 2))
							print('sat A\t',
								f'{saturation_amino_acid[0]:.2f}',
								f'\t{saturation_amino_acid[-1]:.2f}')
							print('sat T\t',
								f'{sat_T[0]:.2f}',
								f'\t{sat_T[-1]:.2f}')

							print('-'*8, 'at exp E', '-'*8)
							print('fc\t', np.round(1-f, 2))
							print('v\t',
								f'{v_charge[:len(trnas)].sum():.2f}',
								f'{v_codons[:len(codons)].sum():.2f}')

							print('-'*8, 'at min E', '-'*8)
							print('fc\t', np.round(1-min_f, 2))
							print('v\t',
								f'{v_charge_min[:len(trnas)].sum():.2f}',
								f'{v_codons[:len(codons)].sum():.2f}')

							print('v diff\t\t', f'{np.max(np.abs(v_charge - v_usage)):.2e}')
							print('v diff min\t', f'{np.max(np.abs(v_charge_min - v_usage_min)):.2e}')

					# Only save solutions that do not have nans
					if (np.isnan(result.fun)
							or np.isinf(result.fun)
							or np.any(np.isnan(np.power(10, result.x)))
							or np.any(np.isinf(np.power(10, result.x)))):
						continue

					trna_charging_kinetics_solutions.append([
						f'"{synthetase}"',
						sweep_level,
						iteration,
						result.fun,
						k_cat,
						K_A,
						json.dumps(dict(zip(trnas, K_T[K_T_indexes]))),
						json.dumps(dict(zip(cases, maps['f_to_cases'] @ f))),
						json.dumps(dict(zip(cases, maps['f_to_cases'] @ min_f))),
						])
					viable_solution += 1

				# EXT-PORT-11: decompose the best objective of this (synthetase, sweep level).
				#
				# One line per group, 80 lines for a whole fit. It is printed UNCONDITIONALLY
				# rather than under `print_optimization`, because the shipped solutions file
				# records only the scalar `objective` and the decomposition is the number that
				# decides whether an anchor is doing anything: at the shipped optima the total is
				# ~1e-7 and 94-99% of it is penalty, not error. A run whose anchor term is 1e-12
				# is unanchored in fact whatever the command line said.
				#
				# Each term is obtained by RE-EVALUATING the real objective with the other weights
				# zeroed, rather than by reimplementing the arithmetic here -- a second copy of the
				# formula is a second thing to keep in step.
				if min_objective_x is not None:
					common = (indexes, maps, v_codons, c_synthetase, c_synthetase_min,
						c_amino_acid, c_trnas)
					no_anchor = np.array([], dtype=np.float64)
					residual = objective(min_objective_x, *common,
						0.0, 0.0, 0.0, no_anchor, anchor_min_f)
					term_r = objective(min_objective_x, *common,
						w_r, 0.0, 0.0, no_anchor, anchor_min_f) - residual
					term_b = objective(min_objective_x, *common,
						0.0, w_b, 0.0, no_anchor, anchor_min_f) - residual
					term_a = objective(min_objective_x, *common,
						0.0, 0.0, w_a, anchor_targets, anchor_min_f) - residual
					x_best = np.power(10, min_objective_x)
					f_best = x_best[indexes['f_slice']]
					charged_best = 1 - (maps['f_to_cases'] @ f_best)
					aggregate = ((maps['cases_to_trna_sum'] @ (charged_best * c_trnas))
						/ (maps['cases_to_trna_sum'] @ c_trnas))
					print('EXT-PORT-11 {} level {}: obj {:.4e} = residual {:.3e} + w_r*sumK_T '
						'{:.3e} + w_b*barrier {:.3e} + w_a*anchor {:.3e}; charged(weighted) {}'
						.format(synthetase, sweep_level, min_objective, residual, term_r,
							term_b, term_a,
							{condition: round(float(aggregate[i * len(trnas)]), 4)
								for i, condition in enumerate(self.conditions)}))

		return trna_charging_kinetics_solutions, trna_charging_kinetics_constants

	def get_constants(self, synthetase, amino_acid, trnas, codons,
			sim_data, cell_specs, trna_charging_kinetics_constants,
			select_condition=None):
		'''
		Retrives constants values of the objective function, which are:
		- concentration of trna synthetase enzymes (uM)
		- concentration of amino acids (uM)
		- concentration of total trnas (uM)
		- rate of codon reading (uM/s)
		'''
		c_synthetase_array = []
		c_amino_acid_array = []
		c_trnas_array = []
		v_codons_array = []
		v_codons_total = []

		i_codons = [self.codons.index(codon) for codon in codons]

		for condition in self.conditions:

			# Get amino acid targets used in metabolism
			media_id = sim_data.conditions[condition]['nutrients']
			c_amino_acid = (sim_data
				.process
				.metabolism
				.concentration_updates
				.concentrations_based_on_nutrients(media_id=media_id)
				[amino_acid]).asNumber(self.conc_unit)

			# Get codon reading rate
			v_codons = (sim_data.codon_read_rate[media_id][i_codons]
				).asNumber(self.rate_unit)
			v_codons_array += v_codons.tolist()
			v_codons_total.append(v_codons.sum())

			# Get tRNA synthetase concentration observed from sample
			# simulations
			c_synthetase = (
				self.trna_synthetase_samples[f'{synthetase}__{condition}']['mean']
				).asNumber(self.conc_unit)

			# Get tRNA abundances from average container
			# EXT-PORT-11 adaptation, and the LAST operons-ON gap in this port. It is the same
			# lesion as EXT-PORT-5, in a third consumer.
			#
			# v3.0.1 did `container.count(trna)` on cistron-space tRNA ids, which is correct only
			# with operons OFF, where rna_data degenerates to one row per cistron. Here the Parca's
			# bulkAverageContainer carries RNA counts in TRANSCRIPTION-UNIT space, so 77 of the 86
			# tRNA cistron ids read as EXACTLY ZERO -- only the 9 monocistronic tRNA genes (glyT,
			# glyW, leuZ, thrT, thrU, tyrT, tyrU, tyrV, cysT) are their own transcription unit and
			# survive. Measured on out/ep11_parca: 18 of 20 synthetases had at least one zero-
			# abundance tRNA and 14 had ALL of them zero.
			#
			# It does not fail quietly, but it fails badly: c_trna = 0 makes saturation_trnas = 0,
			# get_random_initial_solution then divides by it, k_cat comes back inf, log10(inf)
			# leaves the bounds, v_charge is NaN, and every restart is rejected by the feasibility
			# filter. The restart loop is `while (iteration < iterations) or (viable_solution <
			# viable_solutions)`, so with nothing ever accepted IT NEVER TERMINATES -- observed as a
			# 36-minute hang on a single synthetase, not as an error.
			#
			# The conversion is not invented here. `transcription.calculate_attenuation` already
			# does exactly this job -- per-cistron tRNA concentration out of cell_specs'
			# bulkAverageContainer, on the operons-ON path, with an identical volume expression --
			# at transcription.py:1518-1524, and this is that code:
			#     counts = tRNA_cistron_tu_mapping_matrix @ counts(rna_data['id'][includes_tRNA])
			# One transcript of a TU yields one copy of each tRNA cistron it carries, which is what
			# that (0/1) matrix encodes; `includes_tRNA` rather than `is_tRNA` so TUs of mixed
			# content are not dropped.
			transcription = sim_data.process.transcription
			volume = (cell_specs[condition]['avgCellDryMassInit']
				/ sim_data.mass.cell_dry_mass_fraction
				/ sim_data.constants.cell_density)
			to_conc = 1 / sim_data.constants.n_avogadro / volume
			container = cell_specs[condition]['bulkAverageContainer']

			# Row order of tRNA_cistron_tu_mapping_matrix is
			# np.where(cistron_data['is_tRNA'])[0] (transcription.py:1107-1108) and
			# uncharged_trna_names is that same selection with '[c]' appended
			# (transcription.py:1265-1267). Equal by construction -- asserted rather than assumed,
			# because a permutation here would silently reassign every tRNA's abundance.
			trna_cistron_ids = [x + '[c]' for x
				in transcription.cistron_data['id'][transcription.cistron_data['is_tRNA']]]
			assert trna_cistron_ids == list(transcription.uncharged_trna_names), (
				'tRNA_cistron_tu_mapping_matrix row order no longer matches uncharged_trna_names')

			unprocessed_counts = container.counts(
				transcription.rna_data['id'][transcription.rna_data['includes_tRNA']])
			cistron_counts = transcription.tRNA_cistron_tu_mapping_matrix.dot(
				unprocessed_counts)
			trna_id_to_count = dict(zip(trna_cistron_ids, cistron_counts))

			trna_to_conc = {}
			for trna in trnas:
				if trna not in trna_id_to_count:
					raise KeyError(
						f'{trna} is not a tRNA cistron of this knowledge base; '
						f'amino_acid_to_trnas and uncharged_trna_names have diverged')
				c_trna = (to_conc
					* trna_id_to_count[trna]
					).asNumber(self.conc_unit)
				# A zero here is what made the optimiser hang. Fail with the reason instead.
				if c_trna <= 0:
					raise ValueError(
						f'{trna} has zero abundance in the {condition} bulkAverageContainer even '
						f'after the transcription-unit -> cistron conversion. The optimiser cannot '
						f'use it: saturation_trnas would be 0, k_cat would be inf, and every '
						f'restart would be rejected by the feasibility filter without the restart '
						f'loop ever terminating.')

				trna_to_conc[trna] = c_trna
				c_trnas_array.append(c_trna)
				c_synthetase_array.append(c_synthetase)
				c_amino_acid_array.append(c_amino_acid)

			# Record
			trna_charging_kinetics_constants.append([
				f'"{synthetase}__{condition}"',
				c_synthetase,
				c_amino_acid,
				json.dumps(trna_to_conc),
				json.dumps(dict(zip(codons, v_codons))),
				])

		c_synthetase_array = np.array(c_synthetase_array)
		c_amino_acid_array = np.array(c_amino_acid_array)
		c_trnas_array = np.array(c_trnas_array)
		v_codons_array = np.array(v_codons_array)
		v_codons_total = np.array(v_codons_total)

		return (c_synthetase_array,
			c_amino_acid_array,
			c_trnas_array,
			v_codons_array,
			v_codons_total,
			trna_charging_kinetics_constants)

	def assign_K_T(self, trnas, codons):
		'''
		Assign K_Ts (the Michaelis-Menten constant describe the affinity
		between tRNA synthetase enzymes and their tRNA substrates) tRNAs

		tRNAs that read the same set of codons are assigned the same K_T
		'''
		# Group tRNAs by the codon(s) they share
		trna_groups = list(set([tuple(self.codon_to_trnas[codon])
			for codon in codons]))

		# Sort by group size
		order = np.argsort([len(group) for group in trna_groups])
		trna_groups  = np.array(trna_groups, dtype=object)[order]

		# Assign unique K_T's according to primary group affiliation
		K_T_indexes = -1 * np.ones(len(trnas), dtype=np.int8)
		for i, group in enumerate(trna_groups):
			for trna in group:
				trna = self.charged_to_free[trna]
				if K_T_indexes[trnas.index(trna)] == -1:
					K_T_indexes[trnas.index(trna)] = i
		n_K_T = max(K_T_indexes) + 1

		# Map codons to tRNAs
		codons_to_trnas = np.zeros((len(trnas), len(codons)), dtype=np.int64)
		for col, codon in enumerate(codons):
			for trna in self.codon_to_trnas[codon]:
				row = trnas.index(self.charged_to_free[trna])
				codons_to_trnas[row, col] = 1

		return n_K_T, K_T_indexes, codons_to_trnas
