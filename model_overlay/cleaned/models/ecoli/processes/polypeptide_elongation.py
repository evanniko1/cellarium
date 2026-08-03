"""
PolypeptideElongation

Translation elongation sub-model.

TODO:
- see the initiation process for more TODOs
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Set, Tuple

from numba import njit
import numpy as np
from scipy.integrate import solve_ivp

import wholecell.processes.process
from wholecell.utils.polymerize import buildSequences, polymerize, computeMassIncrease
from wholecell.utils.random import stochasticRound
from wholecell.utils import units

# EXT-PORT-1 (WholeCellEcoliRelease v3.0.1, Choi & Covert 2023). Compiled by
# scripts/apply_trna_port.py:build_extension inside the model image — see that module's header.
# This is a MODULE-LEVEL import, so a missing .so is an ImportError at process construction,
# not a quiet fallback to the steady-state model.
from wholecell.utils._trna_charging import (get_initiations,
	reconcile_via_ribosome_positions, reconcile_via_trna_pools,
	get_elongation_rate, get_codons_read)
import copy

# EXT-PORT-10: the reconciliation width buffer is defined next to the knowledge-base pad that has
# to contain it, and imported here. Before this, the pad lived in relation.py and the buffer lived
# in KineticTrnaChargingModel as a bare literal, with nothing coupling them -- which is how the KB
# array came to be one column narrower than the window that reads it.
from reconstruction.ecoli.dataclasses.relation import (
	KINETIC_TRNA_CHARGING_WIDTH_BUFFER)


CONC_UNITS = units.umol / units.L
REMOVED_FROM_CHARGING = {'L-SELENOCYSTEINE[c]'}


class PolypeptideElongation(wholecell.processes.process.Process):
	""" PolypeptideElongation """

	_name = "PolypeptideElongation"

	def __init__(self):
		super(PolypeptideElongation, self).__init__()

	def initialize(self, sim, sim_data):
		super(PolypeptideElongation, self).initialize(sim, sim_data)

		# Simulation options
		self.aa_supply_in_charging = sim._aa_supply_in_charging
		self.adjust_timestep_for_charging = sim._adjust_timestep_for_charging
		self.mechanistic_translation_supply = sim._mechanistic_translation_supply
		self.mechanistic_aa_transport = sim._mechanistic_aa_transport
		self.ppgpp_regulation = sim._ppgpp_regulation
		self.disable_ppgpp_elongation_inhibition = sim._disable_ppgpp_elongation_inhibition
		self.variable_elongation = sim._variable_elongation_translation
		self.variable_polymerize = self.ppgpp_regulation or self.variable_elongation
		translation_supply = sim._translationSupply
		trna_charging = sim._trna_charging
		# EXT-PORT-1: additive. `trna_charging` remains the steady-state flag it has always been.
		kinetic_trna_charging = getattr(sim, '_kinetic_trna_charging', False)
		coarse_kinetic_elongation = getattr(sim, '_coarse_kinetic_elongation', False)
		# EXT-PORT-8: calculateRequest and evolveState dispatch on these, so they have to outlive
		# initialize. Locals were enough only while the flags were gated off.
		self.kinetic_trna_charging = kinetic_trna_charging
		self.coarse_kinetic_elongation = coarse_kinetic_elongation

		constants = sim_data.constants
		translation = sim_data.process.translation
		transcription = sim_data.process.transcription

		self.max_time_step = translation.max_time_step

		# Load parameters
		self.n_avogadro = constants.n_avogadro
		proteinIds = translation.monomer_data['id']
		self.proteinLengths = translation.monomer_data["length"].asNumber()
		self.proteinSequences = translation.translation_sequences
		self.aaWeightsIncorporated = translation.translation_monomer_weights
		self.endWeight = translation.translation_end_weight
		self.make_elongation_rates = translation.make_elongation_rates
		self.next_aa_pad = translation.next_aa_pad

		self.ribosomeElongationRate = float(sim_data.growth_rate_parameters.ribosomeElongationRate.asNumber(units.aa / units.s))

		# Amino acid supply calculations
		self.translation_aa_supply = sim_data.translation_supply_rate
		self.import_threshold = sim_data.external_state.import_constraint_threshold

		# Used for figure in publication
		self.trpAIndex = np.where(proteinIds == "TRYPSYN-APROTEIN[c]")[0][0]

		# Create view onto actively elongating 70S ribosomes
		self.active_ribosomes = self.uniqueMoleculesView('active_ribosome')

		# Create views onto 30S and 50S ribosomal subunits for termination
		self.ribosome30S = self.bulkMoleculeView(sim_data.molecule_ids.s30_full_complex)
		self.ribosome50S = self.bulkMoleculeView(sim_data.molecule_ids.s50_full_complex)

		# Create view onto all proteins
		self.bulkMonomers = self.bulkMoleculesView(proteinIds)

		# Create views onto all polymerization reaction small molecules
		self.aaNames = sim_data.molecule_groups.amino_acids
		self.aas = self.bulkMoleculesView(self.aaNames)

		self.elngRateFactor = 1.

		# Data structures for charging
		self.aa_from_trna = transcription.aa_from_trna

		# EXT-PORT-8: host state for the codon-aware path. Read ONLY by
		# _calculateRequest_codon_aware / _evolveState_codon_aware -- the steady-state
		# calculateRequest/evolveState below never touch any of it, so the default path is inert
		# with respect to this block. The flag guard also matters for LOADING: sim_data.relation
		# only exists on a knowledge base built by the ported ParCa, and an older simData.cPickle
		# has to keep running the default model rather than AttributeError here.
		if kinetic_trna_charging or coarse_kinetic_elongation:
			# v3.0.1 shipped the kinetic elongation models with ppgpp_regulation,
			# mechanistic_translation_supply and mechanistic_aa_transport all False (vendor
			# v3.0.1 wholecell/sim/simulation.py:41-49). This tree defaults all three True and
			# neither kinetic model implements any of them. trna_charging and translation_supply
			# are already forced False upstream in wholecell/sim/simulation.py; these are not,
			# and each of them fails quietly rather than loudly:
			#   ppgpp_regulation           Nothing synthesises or degrades ppGpp any more -- only
			#                              SteadyStateElongationModel runs those reactions. The
			#                              pool does not drift, because metabolism.py:52 turns
			#                              include_ppgpp back on once trna_charging is False and
			#                              then holds ppGpp at a constant target. What does
			#                              change is variable_polymerize (set above from this
			#                              flag), which v3.0.1 had False, and ppGpp-dependent
			#                              transcription regulation now reads a constant pool.
			#   mechanistic_aa_transport   Metabolism builds its amino acid uptake package from
			#                              PolypeptideElongation.aa_exchange_rates
			#                              (metabolism.py:171-176). Only SteadyStateElongationModel
			#                              ever assigns that attribute; under a kinetic model it
			#                              stays the zeros initialised at the end of this method,
			#                              so in any medium containing amino acids the FBA is told
			#                              uptake is zero. No exception, no warning.
			#   mechanistic_translation_supply / aa_supply_in_charging
			#                              Read only inside SteadyStateElongationModel.request, so
			#                              they are inert. Harmless numerically, but a provenance
			#                              record claiming mechanistic supply was active would be
			#                              false.
			# Deliberately a notice and not a gate: the arity gate this replaces is gone, and each
			# of these is switchable from the command line (--no-ppgpp-regulation,
			# --no-mechanistic-aa-transport, --no-mechanistic-translation-supply,
			# --no-aa-supply-in-charging). Silently forcing them off, which is what v3.0.1's
			# variant logic did, would write a metadata record that disagrees with the flags the
			# run was launched with.
			not_modeled = [name for name, on in [
				('ppgpp_regulation', self.ppgpp_regulation),
				('mechanistic_aa_transport', self.mechanistic_aa_transport),
				('mechanistic_translation_supply', self.mechanistic_translation_supply),
				('aa_supply_in_charging', self.aa_supply_in_charging),
				] if on]
			if not_modeled:
				print('EXT-PORT-8: a kinetic elongation model is selected. It does not model the'
					' following options, which are therefore inert or divergent from Choi &'
					' Covert 2023: {}. See the note in PolypeptideElongation.initialize.'
					.format(', '.join(not_modeled)))

			# MONOMER space, which is the space of the active_ribosome 'protein_index' attribute.
			# Not rna_data (3276 transcription units) and not cistron_data (4539). The steady-state
			# evolveState spells the same number inline as self.proteinSequences.shape[0].
			# EXT-PORT-12: measured 4309 on out/kinetic_parca/kb/simData.cPickle (md5 991fee48) --
			# translation_sequences.shape == (4309, 2370) and len(monomer_data['id']) == 4309. The
			# earlier "4310 here" in this comment was wrong; the two expressions are equal, which is
			# the load-bearing part, and KineticTrnaChargingModel.protein_maturation now uses
			# self.process.n_proteins rather than re-deriving it.
			self.n_proteins = len(proteinIds)

			# 63: the 62 sense codons plus the leading 'start' pseudo-codon. Identical derivation
			# to the one the TrnaCharging listener uses to size codons_read
			# (models/ecoli/listeners/trna_charging.py:32), so get_codons_read's output drops into
			# that column without a width fix.
			self.n_codons = len(sim_data.relation.codons)

			# (4310, 2369) int8, row-aligned with monomer_data['id'], so it is indexable by the raw
			# protein_index with no remapping. It is one column NARROWER than translation_sequences
			# (2370): never reason about codon-sequence bounds from self.proteinSequences' width.
			self.codon_sequences = sim_data.relation.codon_sequences

			# EXT-PORT-10: refuse to start if any monomer's codon sequence is shorter than its protein.
			#
			# This path terminates ribosomes on elongation_model.protein_lengths but reads codons out of
			# relation.codon_sequences, and for a mismatched monomer the second runs out before the first.
			# Today that is PHNE-MONOMER: 275 residues, 206 real codons. Past 206 the sequence returns the
			# PAD value -1, which reaches computeMassIncrease at
			# `out_view[i] += monomerMasses[sequences[i, j]]` (wholecell/utils/_build_sequences.pyx:66).
			#
			# That is NOT a wrap to the last weight. _build_sequences.pyx and _trna_charging.pyx both carry
			# @cython.boundscheck(False) AND @cython.wraparound(False), so monomerMasses[-1] is a raw
			# out-of-bounds access into whatever precedes the array. One monomer in 4310, no exception, and
			# it would surface as an unreproducible oddity hours into a campaign rather than as a failure.
			#
			# Asserting here rather than excluding the monomer, because which of the two is right is a
			# knowledge-base question (see BACKLOG EXT-PORT-10) and quietly dropping a protein from
			# translation is its own silent wrongness.
			mismatched = list(getattr(sim_data.relation, 'codon_sequence_mismatches', []))
			if mismatched:
				raise ValueError(
					'the codon-aware elongation path cannot run while any monomer has a codon sequence'
					' shorter than its protein: {}. Ribosomes terminate on protein length but read codons'
					' from relation.codon_sequences, so the pad value -1 reaches a Cython kernel compiled'
					' with wraparound(False) and reads out of bounds. See BACKLOG EXT-PORT-10.'
					.format(mismatched))

			# Ribosome profiling of a molecule of interest. _evolveState_codon_aware interpolates
			# the gene string into the listener column name, and our TrnaCharging listener
			# hard-codes ribosome_positions_argA (listeners/trna_charging.py:58), so this key/value
			# pair is not free to change: any other value names a column that does not exist, and
			# Process.writeToListener only warns on that (wholecell/processes/process.py:103-108)
			# before dropping the data.
			monomer_data = translation.monomer_data
			self.ribosome_profiling_molecules = {
				'N-ACETYLTRANSFER-MONOMER[c]': 'argA',
				}
			self.ribosome_profiling_molecule_indexes = {}
			self.ribosome_profiling_listener_sizes = {}
			for molecule in self.ribosome_profiling_molecules.keys():
				molecule_index = np.where(monomer_data['id'] == molecule)[0][0]
				# .asNumber(units.aa), not the bare .asNumber() used for proteinLengths above.
				# This has to equal the listener's own argA_listener_size
				# (listeners/trna_charging.py:43) exactly: writeToListener is a plain setattr, so
				# a disagreement would silently swap the listener's 444-wide array for a
				# differently sized one and only surface later as a failed table write.
				listener_size = int(1 + monomer_data['length'][molecule_index].asNumber(units.aa))
				self.ribosome_profiling_molecule_indexes[molecule] = molecule_index
				self.ribosome_profiling_listener_sizes[molecule] = listener_size

		# Set modeling method
		if kinetic_trna_charging:
			self.elongation_model = KineticTrnaChargingModel(sim_data, self)
		elif coarse_kinetic_elongation:
			self.elongation_model = CoarseKineticTrnaChargingModel(sim_data, self)
		elif trna_charging:
			self.elongation_model = SteadyStateElongationModel(sim_data, self)
		elif translation_supply:
			self.elongation_model = TranslationSupplyElongationModel(sim_data, self)
		else:
			self.elongation_model = BaseElongationModel(sim_data, self)

		# EXT-PORT-10 tripwire. The knowledge-base pad on relation.codon_sequences and the runtime
		# read window are computed in two different files from two different expressions. They were
		# out of step by exactly one column until EXT-PORT-10, and the symptom was an IndexError deep
		# inside buildSequences on ONE monomer at ONE position, hours into a campaign. Re-derive the
		# inequality here, once per simulation, so the pair cannot drift apart again silently.
		#
		# Bounds rather than the live width: self.elongation_model.codon_sequences_width() depends on
		# timeStepSec(), which is not final at initialize. max_time_step is the ceiling the adaptive
		# step search is gated by (PolypeptideElongation.isTimeStepShortEnough), so these ARE the
		# widest windows reachable.
		if kinetic_trna_charging or coarse_kinetic_elongation:
			codon_sequences = sim_data.relation.codon_sequences
			real_codon_lengths = (codon_sequences != polymerize.PAD_VALUE).sum(axis=1)
			# A ribosome is deleted the step updated_lengths == terminal_lengths, so it tops out at
			# L-1 -- except for MAP substrates, whose termination protein_maturation can defer, which
			# leaves one sitting at exactly L.
			is_map_substrate = translation.monomer_data['cleavage_of_initial_methionine']
			max_position = int(np.where(
				is_map_substrate, real_codon_lengths, real_codon_lengths - 1).max())
			max_width = int(max(
				# _evolveState_codon_aware / _calculateRequest_codon_aware
				translation.max_time_step * constants.ribosome_elongation_rate_max.asNumber(
					units.aa / units.s) + translation.next_aa_pad,
				# KineticTrnaChargingModel.elongation_rate / codon_sequences_width
				np.ceil(translation.max_time_step
					* constants.ribosome_elongation_rate_basal.asNumber(units.aa / units.s)
					+ KINETIC_TRNA_CHARGING_WIDTH_BUFFER)))
			assert max_position + max_width <= codon_sequences.shape[1], (
				'relation.codon_sequences is {} columns wide but the codon-aware path can read to'
				' column {} ({} + a {}-wide window). Rebuild the knowledge base: the pad is computed in'
				' Relation._build_codon_based_translation and this simData predates EXT-PORT-10.'
				.format(codon_sequences.shape[1], max_position + max_width, max_position, max_width))

		# Growth associated maintenance energy requirements for elongations
		self.gtpPerElongation = constants.gtp_per_translation
		## Need to account for ATP hydrolysis for charging that has been
		## removed from measured GAM (ATP -> AMP is 2 hydrolysis reactions)
		## if charging reactions are not explicitly modeled
		if not (trna_charging or kinetic_trna_charging):
			self.gtpPerElongation += 2
		## Variable for metabolism to read to consume required energy
		self.gtp_to_hydrolyze = 0

		self.aa_exchange_rates = CONC_UNITS / units.s * np.zeros(len(self.aaNames))

		# EXT-PORT-12 (UNIFY-2 gate): declare whether anything ever WRITES aa_exchange_rates.
		#
		# Metabolism builds its amino-acid uptake package from this attribute whenever
		# mechanistic_aa_transport is on (metabolism.py, the aa_uptake_package block). The ONLY
		# writer in the tree is SteadyStateElongationModel.request (line ~1059). Under a kinetic
		# elongation model it keeps the zeros initialised on the line above, and the FBA is told
		# amino-acid uptake is exactly zero -- no exception, no warning, a plausible number.
		#
		# MEASURED: inert in the runs done so far, because FBAResults/media_id is 'minimal' on every
		# row of both paths, so aa_in_media is all False and the uptake package is empty. It is NOT
		# inert in the experiment this gate exists for: Elf's selective-charging test runs under
		# amino-acid limitation, in a medium that CONTAINS amino acids, where the kinetic arm would
		# be told uptake is 0 for every one of them while the steady-state arm gets mechanistic
		# rates. Metabolism turns that into a hard failure at the first step where the two conditions
		# meet; see the assertion at its aa_uptake_package block.
		self.aa_exchange_rates_modelled = bool(trna_charging)

	def calculateRequest(self):
		# EXT-PORT-8 dispatch. The codon-aware path is a SEPARATE method on purpose: everything
		# below is the steady-state model that produced the existing simulation corpus and has to
		# stay byte-for-byte identical, which is the entire basis for calling these flags additive.
		# These two lines are the only edit to this method.
		if self.kinetic_trna_charging or self.coarse_kinetic_elongation:
			return self._calculateRequest_codon_aware()

		# Set ribosome elongation rate based on simulation medium environment and elongation rate factor
		# which is used to create single-cell variability in growth rate
		# The maximum number of amino acids that can be elongated in a single timestep is set to 22 intentionally as the minimum number of padding values
		# on the protein sequence matrix is set to 22. If timesteps longer than 1.0s are used, this feature will lead to errors in the effective ribosome
		# elongation rate.

		current_media_id = self._external_states['Environment'].current_media_id

		# MODEL SPECIFIC: get ribosome elongation rate
		self.ribosomeElongationRate = self.elongation_model.elongation_rate()

		# If there are no active ribosomes, return immediately
		if self.active_ribosomes.total_count() == 0:
			return

		# Build sequences to request appropriate amount of amino acids to
		# polymerize for next timestep
		proteinIndexes, peptideLengths = self.active_ribosomes.attrs(
			'protein_index', 'peptide_length'
			)

		self.elongation_rates = self.make_elongation_rates(
			self.randomState,
			self.ribosomeElongationRate,
			self.timeStepSec(),
			self.variable_elongation)

		sequences = buildSequences(
			self.proteinSequences,
			proteinIndexes,
			peptideLengths,
			self.elongation_rates)

		sequenceHasAA = (sequences != polymerize.PAD_VALUE)
		aasInSequences = np.bincount(sequences[sequenceHasAA], minlength=21)

		# Calculate AA supply for expected doubling of protein
		dryMass = (self.readFromListener("Mass", "dryMass") * units.fg)
		translation_supply_rate = self.translation_aa_supply[current_media_id] * self.elngRateFactor
		mol_aas_supplied = translation_supply_rate * dryMass * self.timeStepSec() * units.s
		self.aa_supply = units.strip_empty_units(mol_aas_supplied * self.n_avogadro)
		self.writeToListener("RibosomeData", "translationSupply", translation_supply_rate.asNumber())

		# MODEL SPECIFIC: Calculate AA request
		fraction_charged, aa_counts_for_translation = self.elongation_model.request(aasInSequences)

		# Write to listeners
		self.writeToListener("GrowthLimits", "fraction_trna_charged", np.dot(fraction_charged, self.aa_from_trna))
		self.writeToListener("GrowthLimits", "aaPoolSize", self.aas.total_counts())
		self.writeToListener("GrowthLimits", "aaRequestSize", aa_counts_for_translation)

		# Request full access to active ribosome molecules
		self.active_ribosomes.request_access(self.EDIT_DELETE_ACCESS)

	def evolveState(self):
		# EXT-PORT-8 dispatch. See calculateRequest. Only these two lines are added here.
		if self.kinetic_trna_charging or self.coarse_kinetic_elongation:
			return self._evolveState_codon_aware()

		# Set values for metabolism in case of early return
		self.gtp_to_hydrolyze = 0
		self.aa_count_diff = {}

		# Write allocation data to listener
		self.writeToListener("GrowthLimits", "aaAllocated", self.aas.counts())

		# Get number of active ribosomes
		n_active_ribosomes = self.active_ribosomes.total_count()
		self.writeToListener("GrowthLimits", "activeRibosomeAllocated", n_active_ribosomes)

		if n_active_ribosomes == 0:
			return

		# Build amino acids sequences for each ribosome to polymerize
		protein_indexes, peptide_lengths, positions_on_mRNA = self.active_ribosomes.attrs(
			'protein_index', 'peptide_length', 'pos_on_mRNA'
			)

		all_sequences = buildSequences(
			self.proteinSequences,
			protein_indexes,
			peptide_lengths,
			self.elongation_rates + self.next_aa_pad)
		sequences = all_sequences[:, :-self.next_aa_pad].copy()

		if sequences.size == 0:
			return

		# Calculate elongation resource capacity
		aaCountInSequence = np.bincount(sequences[(sequences != polymerize.PAD_VALUE)])
		total_aa_counts = self.aas.counts()

		# MODEL SPECIFIC: Get amino acid counts
		aa_counts_for_translation = self.elongation_model.final_amino_acids(total_aa_counts)

		# Using polymerization algorithm elongate each ribosome up to the limits
		# of amino acids, sequence, and GTP
		result = polymerize(
			sequences,
			aa_counts_for_translation,
			10000000, # Set to a large number, the limit is now taken care of in metabolism
			self.randomState,
			self.elongation_rates[protein_indexes],
			variable_elongation=self.variable_polymerize,
			)

		sequence_elongations = result.sequenceElongation
		aas_used = result.monomerUsages
		nElongations = result.nReactions

		next_amino_acid = all_sequences[np.arange(len(sequence_elongations)), sequence_elongations]
		next_amino_acid_count = np.bincount(next_amino_acid[next_amino_acid != polymerize.PAD_VALUE], minlength=21)

		# Update masses of ribosomes attached to polymerizing polypeptides
		added_protein_mass = computeMassIncrease(
			sequences,
			sequence_elongations,
			self.aaWeightsIncorporated
			)

		updated_lengths = peptide_lengths + sequence_elongations
		updated_positions_on_mRNA = positions_on_mRNA + 3*sequence_elongations

		didInitialize = (
			(sequence_elongations > 0) &
			(peptide_lengths == 0)
			)

		added_protein_mass[didInitialize] += self.endWeight

		# Write current average elongation to listener
		currElongRate = (sequence_elongations.sum() / n_active_ribosomes) / self.timeStepSec()
		self.writeToListener("RibosomeData", "effectiveElongationRate", currElongRate)

		# Update active ribosomes, terminating if necessary
		self.active_ribosomes.attrIs(
			peptide_length=updated_lengths,
			pos_on_mRNA=updated_positions_on_mRNA)
		self.active_ribosomes.add_submass_by_name("protein", added_protein_mass)

		# Ribosomes that reach the end of their sequences are terminated and
		# dissociated into 30S and 50S subunits. The polypeptide that they are polymerizing
		# is converted into a protein in BulkMolecules
		terminalLengths = self.proteinLengths[protein_indexes]

		didTerminate = (updated_lengths == terminalLengths)

		terminatedProteins = np.bincount(
			protein_indexes[didTerminate],
			minlength = self.proteinSequences.shape[0]
			)

		self.active_ribosomes.delByIndexes(np.where(didTerminate)[0])
		self.bulkMonomers.countsInc(terminatedProteins)

		nTerminated = didTerminate.sum()
		nInitialized = didInitialize.sum()

		self.ribosome30S.countInc(nTerminated)
		self.ribosome50S.countInc(nTerminated)

		# MODEL SPECIFIC: evolve
		# TODO: use something other than a class attribute to pass aa diff to metabolism
		net_charged, self.aa_count_diff = self.elongation_model.evolve(
			total_aa_counts, aas_used, next_amino_acid_count, nElongations, nInitialized)

		# GTP hydrolysis is carried out in Metabolism process for growth
		# associated maintenance. This is set here for metabolism to use.
		self.gtp_to_hydrolyze = self.gtpPerElongation * nElongations

		# Write data to listeners
		self.writeToListener('MonomerCounts', 'monomersElongated', terminatedProteins)

		self.writeToListener("GrowthLimits", "net_charged", net_charged)
		self.writeToListener("GrowthLimits", "aasUsed", aas_used)
		self.writeToListener("GrowthLimits", "aaCountDiff", [self.aa_count_diff.get(id_, 0) for id_ in self.aaNames])

		self.writeToListener("RibosomeData", "aaCountInSequence", aaCountInSequence)
		self.writeToListener("RibosomeData", "aaCounts", aa_counts_for_translation)

		self.writeToListener("RibosomeData", "actualElongations", sequence_elongations.sum())
		self.writeToListener("RibosomeData", "actualElongationHist", np.histogram(sequence_elongations, bins = np.arange(0,23))[0])
		self.writeToListener("RibosomeData", "elongationsNonTerminatingHist", np.histogram(sequence_elongations[~didTerminate], bins=np.arange(0,23))[0])

		self.writeToListener("RibosomeData", "didTerminate", didTerminate.sum())
		self.writeToListener("RibosomeData", "terminationLoss", (terminalLengths - peptide_lengths)[didTerminate].sum())
		self.writeToListener("RibosomeData", "numTrpATerminated", terminatedProteins[self.trpAIndex])

		self.writeToListener("RibosomeData", "processElongationRate", self.ribosomeElongationRate / self.timeStepSec())

	def _calculateRequest_codon_aware(self):
		"""
		EXT-PORT-8: v3.0.1's calculateRequest (Choi & Covert 2023), which is codon-aware and calls
		the elongation model with the 3-arg elongation_rate / 4-arg request convention that
		KineticTrnaChargingModel and CoarseKineticTrnaChargingModel implement.

		Kept as a separate method rather than branching inside calculateRequest so that the
		steady-state body stays exactly the model that produced the existing corpus.
		"""
		# If there are no active ribosomes, return immediately
		if self.active_ribosomes.total_count() == 0:
			# EXT-PORT-12 (UNIFY-2 gate): the ONE ordering difference between the two paths that is
			# forced by the mechanism, made visible instead of latent.
			#
			# The steady-state calculateRequest calls elongation_rate() BEFORE its zero-ribosome
			# guard; this method must call it after, because KineticTrnaChargingModel.elongation_rate
			# needs the ribosome attributes and is the call that builds self.longer_sequences. So on
			# a zero-ribosome step the steady-state path refreshes self.ribosomeElongationRate and
			# this path leaves it (and self.elongation_rates, and longer_sequences) at last step's
			# values.
			#
			# MEASURED: unreachable in every run to date. Across 2,184 + 121 + 121 logged steps the
			# only row with activeRibosomeAllocated == 0 is row 0, the pre-simulation listener dump
			# (UniqueMoleculeCounts active_ribosome min 12,424 over a full generation on both paths).
			# It is NOT provably unreachable in general -- a severe starvation or heavy-knockout
			# variant could empty the ribosome pool, and starvation is exactly the regime the parity
			# experiment lives in -- so this prints rather than staying silent. If it ever fires, the
			# stale-rate difference between the two paths is live and the run is not a clean control.
			if not getattr(self, '_zero_ribosome_step_warned', False):
				self._zero_ribosome_step_warned = True
				print('EXT-PORT-12: a codon-aware timestep had ZERO active ribosomes. This branch was'
					' unreachable in all runs the UNIFY-2 gate was measured on. ribosomeElongationRate,'
					' elongation_rates and longer_sequences are stale for this step, which the'
					' steady-state path would have refreshed -- the two paths are NOT ordering'
					'-equivalent on such a step. Record this before comparing the run.')
			return

		# Get active ribosome attributes
		protein_indexes, peptide_lengths = self.active_ribosomes.attrs(
			'protein_index', 'peptide_length'
			)

		# Record cell mass once here for various uses during this time step
		# (KineticTrnaChargingModel.protein_maturation reads the cached value in evolveState;
		# the base implementations are no-ops.)
		self.elongation_model.record_mass()

		# Set ribosome elongation rate based on simulation medium
		# environment and elongation rate factor, which is used to
		# create single-cell variability in growth rate.
		current_media_id = self._external_states['Environment'].current_media_id

		# Elongation Model Dependent: Get ribosome elongation rate
		# ORDER IS LOAD-BEARING and differs from the steady-state calculateRequest above, which
		# calls elongation_rate() before the zero-ribosome guard. KineticTrnaChargingModel's
		# elongation_rate needs protein_indexes/peptide_lengths, and it is the call that builds
		# self.longer_sequences -- which its request(), reconcile() and sequences() all read later
		# in the same step. Calling it first, with no ribosome attributes, is not available here.
		self.ribosomeElongationRate = self.elongation_model.elongation_rate(
			current_media_id, protein_indexes, peptide_lengths)

		self.elongation_rates = self.make_elongation_rates(
			self.randomState,
			self.ribosomeElongationRate,
			self.timeStepSec(),
			self.variable_elongation)

		# Build sequences to request the appropriate amount of monomers
		# to polymerize.
		# elongation_model.protein_sequences, not self.proteinSequences: under
		# KineticTrnaChargingModel this is relation.codon_sequences (codon space), under the coarse
		# model it is translation_sequences (amino acid space). Using the process attribute would
		# silently build amino acid sequences and hand them to a codon-space kinetics model.
		sequences = buildSequences(
			self.elongation_model.protein_sequences,
			protein_indexes,
			peptide_lengths,
			self.elongation_rates)

		# Calculate AA supply for expected doubling of protein
		# Still needed on this path: CoarseKineticTrnaChargingModel subclasses
		# TranslationSupplyElongationModel, so its amino_acid_counts reads self.aa_supply.
		dryMass = (self.readFromListener("Mass", "dryMass") * units.fg)
		translation_supply_rate = self.translation_aa_supply[current_media_id] * self.elngRateFactor
		mol_aas_supplied = translation_supply_rate * dryMass * self.timeStepSec() * units.s
		self.aa_supply = units.strip_empty_units(mol_aas_supplied * self.n_avogadro)
		self.writeToListener("RibosomeData", "translationSupply", translation_supply_rate.asNumber())

		# Elongation Model Dependent: Calculate monomer request
		# minlength is the model's monomer space -- 63 codons for KineticTrnaChargingModel, 21
		# amino acids for the coarse model. The steady-state calculateRequest hard-codes
		# minlength=21. np.bincount's minlength is only a floor, so with codon sequences that
		# would usually still return 63 entries by accident -- and would silently return fewer on
		# any step where the highest codon index present is below 62, handing the kinetics model a
		# short array. Take the width from the model, not from a constant.
		monomers_in_sequences = np.bincount(
			sequences[sequences != polymerize.PAD_VALUE],
			minlength=self.elongation_model.n_monomers)

		fraction_charged, aa_request = self.elongation_model.request(
			monomers_in_sequences, protein_indexes, current_media_id, peptide_lengths)

		# Write to listeners
		# fraction_charged is written RAW here, unlike the steady-state calculateRequest above
		# which projects it with np.dot(fraction_charged, self.aa_from_trna). That projection
		# exists there because our BaseElongationModel returns a 21-long zeros vector;
		# KineticTrnaChargingModel.request already returns tRNA space (86 entries, exactly the
		# width GrowthLimits.fraction_trna_charged is allocated at, growth_limits.py:60-61), and
		# an (86,)-by-(21, 86) dot raises ValueError. Both paths therefore land in the same
		# 86-wide column and stay comparable.
		self.writeToListener("GrowthLimits", "fraction_trna_charged", fraction_charged)
		self.writeToListener("GrowthLimits", "aaPoolSize", self.aas.total_counts())
		self.writeToListener("GrowthLimits", "aaRequestSize", aa_request)

		# Request full access to active ribosome molecules
		self.active_ribosomes.request_access(self.EDIT_DELETE_ACCESS)

	def _evolveState_codon_aware(self):
		"""
		EXT-PORT-8: v3.0.1's evolveState (Choi & Covert 2023). See _calculateRequest_codon_aware
		for why this is a separate method. Two v3.0.1 listener writes are deliberately dropped and
		one ours-only write is deliberately carried; both are commented at their sites.
		"""
		# Set values for metabolism in case of early return
		self.gtp_to_hydrolyze = 0
		self.aa_count_diff = {}

		# Write allocation data to listener
		self.writeToListener("GrowthLimits", "aaAllocated", self.aas.counts())

		# Get number of active ribosomes
		n_active_ribosomes = self.active_ribosomes.total_count()
		self.writeToListener("GrowthLimits", "activeRibosomeAllocated", n_active_ribosomes)

		if n_active_ribosomes == 0:
			return

		# Build amino acids sequences for each ribosome to polymerize
		protein_indexes, peptide_lengths, positions_on_mRNA = self.active_ribosomes.attrs(
			'protein_index', 'peptide_length', 'pos_on_mRNA'
			)

		all_sequences = buildSequences(
			self.elongation_model.protein_sequences,
			protein_indexes,
			peptide_lengths,
			self.elongation_rates + self.next_aa_pad)
		sequences = all_sequences[:, :-self.next_aa_pad].copy()

		if sequences.size == 0:
			return

		# Build codon sequences
		# Separate from `sequences` above because the two models want different widths:
		# KineticTrnaChargingModel returns its fixed ceil(basal_rate * dt) + buffer window (a
		# length-1 array, which buildSequences accepts since it only reads elongation_rates.max()),
		# while the coarse model returns the per-protein elongation_rates unchanged.
		codon_sequences_width = self.elongation_model.codon_sequences_width(
			self.elongation_rates)
		codon_sequences = buildSequences(
			self.codon_sequences,
			protein_indexes,
			peptide_lengths,
			codon_sequences_width)

		# Calculate elongation resource capacity
		# monomer_count_in_sequence is in the model's monomer space (63 codons or 21 amino acids);
		# monomer_to_aa projects it back to the 21-wide space RibosomeData.aaCountInSequence is
		# allocated at (ribosome_data.py:43). The steady-state evolveState calls np.bincount with
		# no minlength at all here, which is safe only because its sequences are already amino
		# acids.
		monomer_count_in_sequence = np.bincount(
			sequences[(sequences != polymerize.PAD_VALUE)],
			minlength=self.elongation_model.n_monomers)
		monomer_count_in_sequence_in_aas = self.elongation_model.monomer_to_aa(
			monomer_count_in_sequence)

		# Elongation Model Dependent: Get monomer counts
		# monomer_limit replaces the steady-state final_amino_acids call and returns a pair: the
		# limit in the model's monomer space (fed to polymerize, which is consuming codon
		# sequences) and the same limit projected to the 21 amino acids for RibosomeData.aaCounts.
		allocated_aas = self.aas.counts()
		monomer_limit, monomer_limit_in_aas = self.elongation_model.monomer_limit(
				allocated_aas, monomer_count_in_sequence)

		# Use the polymerize algorithm to elongate each ribosome up to
		# the limits of monomers, sequences, and GTP.
		result = polymerize(
			sequences,
			monomer_limit,
			10000000, # Set to a large number, the limit is now taken care of in metabolism
			self.randomState,
			self.elongation_rates[protein_indexes],
			variable_elongation=self.variable_polymerize,
			)

		# Elongation Model Dependent: Verify consistency
		# The kinetic model reconciles the sequence-limited polymerize result against its own
		# kinetics-limited codon reading, mutating result in place; the coarse model is a pass
		# through. net_charged returned here is superseded by the value evolve() returns below.
		result, aas_used, net_charged = self.elongation_model.reconcile(result)

		sequence_elongations = result.sequenceElongation
		n_elongations = result.nReactions

		# Elongation Model Dependent
		next_amino_acid_count = self.elongation_model.next_amino_acids(
			all_sequences, sequence_elongations)

		# Update masses of ribosomes attached to polymerizing polypeptides
		# elongation_model.sequences() swaps in the kinetic model's wider longer_sequences, which
		# is the array its reconciliation actually operated on; monomer_weights_incorporated is
		# per-codon (63) for the kinetic model and per-amino-acid (21) for the coarse one, so
		# self.aaWeightsIncorporated must NOT be used here.
		sequences = self.elongation_model.sequences(sequences)
		added_protein_mass = computeMassIncrease(
			sequences,
			sequence_elongations,
			self.elongation_model.monomer_weights_incorporated,
			)

		updated_lengths = peptide_lengths + sequence_elongations
		updated_positions_on_mRNA = positions_on_mRNA + 3*sequence_elongations

		did_initialize = (
			(sequence_elongations > 0) &
			(peptide_lengths == 0)
			)

		added_protein_mass[did_initialize] += self.endWeight

		# Write current average elongation to listener
		self.writeToListener('RibosomeData', 'effectiveElongationRate',
			(sequence_elongations.sum() / n_active_ribosomes / self.timeStepSec()))

		# Update active ribosomes, terminating if necessary
		self.active_ribosomes.attrIs(
			peptide_length=updated_lengths,
			pos_on_mRNA=updated_positions_on_mRNA)
		self.active_ribosomes.add_submass_by_name('protein', added_protein_mass)

		# Ribosomes that reach the end of their sequences are terminated and
		# dissociated into 30S and 50S subunits. The polypeptide that they are polymerizing
		# is converted into a protein in BulkMolecules
		terminal_lengths = self.elongation_model.protein_lengths[protein_indexes]

		did_terminate = (updated_lengths == terminal_lengths)

		terminated_proteins = np.bincount(
			protein_indexes[did_terminate],
			minlength=self.n_proteins,
			)

		# Mature completed polypeptides
		# The kinetic model rate-limits initial-methionine cleavage by methionine aminopeptidase
		# and can push a termination to a later step, so did_terminate and terminated_proteins are
		# both rebound here before anything downstream uses them.
		(did_terminate, terminated_proteins, initial_methionines_cleaved
			) = self.elongation_model.protein_maturation(
			did_terminate, terminated_proteins, protein_indexes)

		self.active_ribosomes.delByIndexes(np.where(did_terminate)[0])
		self.bulkMonomers.countsInc(terminated_proteins)

		n_terminated = did_terminate.sum()
		n_initialized = did_initialize.sum()

		self.ribosome30S.countInc(n_terminated)
		self.ribosome50S.countInc(n_terminated)

		# Elongation Model Dependent: evolve
		# TODO: use something other than a class attribute to pass aa diff to metabolism
		#
		# EXT-PORT-12 (UNIFY-2 gate) / BACKLOG UNIFY-1 silent-failure mode (ii). READ BEFORE WIRING
		# ppGpp INTO THIS PATH. The two arguments below look interchangeable and are not:
		#   aas_used             -- returned by elongation_model.reconcile at line ~665. On THIS path
		#                           it is amino_acids_used from run_model, i.e. amino acids consumed
		#                           by CHARGING. On the steady-state path the identically-named local
		#                           is result.monomerUsages (line ~406), i.e. residues incorporated
		#                           at the ribosome. Same shape (21), same order of magnitude,
		#                           different quantity.
		#   result.monomerUsages -- passed separately as the eighth argument precisely because of
		#                           that. In CODON space (63) on this path.
		# SteadyStateElongationModel builds RelA's f from `aa_at_ribosome = aas_used +
		# next_amino_acid_count` (line ~1195), where aas_used IS monomerUsages. A parity ppGpp block
		# that copies that line verbatim here would feed RelA charging demand instead of A-site
		# occupancy -- which is the one thing RelA exists to sense -- and would run, and would
		# produce plausible wrong numbers. Parity's f must be
		# `codons_to_amino_acids @ result.monomerUsages + next_amino_acid_count`.
		net_charged, self.aa_count_diff = self.elongation_model.evolve(
			allocated_aas, aas_used, next_amino_acid_count, n_elongations,
			n_initialized, net_charged, result.monomerUsages,
			initial_methionines_cleaved)

		# GTP hydrolysis is carried out in Metabolism process for growth
		# associated maintenance. This is set here for metabolism to use.
		self.gtp_to_hydrolyze = self.gtpPerElongation * n_elongations

		# Calculate codons read and initiations performed
		codons_read = get_codons_read(
			codon_sequences,
			sequence_elongations,
			self.n_codons)

		n_initiations = get_initiations(
			sequence_elongations,
			peptide_lengths,
			protein_indexes,
			)

		# Write data to listeners
		# OURS-ONLY, with no equivalent in v3.0.1's evolveState. This column is the per-monomer
		# synthesis flux the whole existing corpus carries (monomer_counts.py:111, :166). The
		# attribute exists, so omitting the write would NOT warn -- the column would silently hold
		# its allocate()-time zeros for the entire run and every kinetic simulation would look like
		# it synthesised no protein. Written post-maturation, which is also what makes it numerically
		# equal to v3.0.1's RibosomeData/n_terminated.
		self.writeToListener('MonomerCounts', 'monomersElongated', terminated_proteins)

		self.writeToListener("GrowthLimits", "net_charged", net_charged)
		self.writeToListener("GrowthLimits", "aasUsed", aas_used)
		self.writeToListener("GrowthLimits", "aaCountDiff", [self.aa_count_diff.get(id_, 0) for id_ in self.aaNames])

		self.writeToListener("RibosomeData", "aaCountInSequence", monomer_count_in_sequence_in_aas)
		self.writeToListener("RibosomeData", "aaCounts", monomer_limit_in_aas)
		self.writeToListener("RibosomeData", "actualElongations", sequence_elongations.sum())
		self.writeToListener("RibosomeData", "actualElongationHist", np.histogram(sequence_elongations, bins = np.arange(0,23))[0])
		self.writeToListener("RibosomeData", "elongationsNonTerminatingHist", np.histogram(sequence_elongations[~did_terminate], bins=np.arange(0,23))[0])
		self.writeToListener("RibosomeData", "didTerminate", did_terminate.sum())
		self.writeToListener("RibosomeData", "terminationLoss", (terminal_lengths - peptide_lengths)[did_terminate].sum())
		self.writeToListener("RibosomeData", "numTrpATerminated", terminated_proteins[self.trpAIndex])
		# v3.0.1 also writes RibosomeData 'n_terminated' (its line 361) and 'n_initialized' (362).
		# Both are DROPPED here. Our RibosomeData listener defines neither column
		# (models/ecoli/listeners/ribosome_data.py allocate/tableAppend), and
		# Process.writeToListener only warnings.warn on a missing attribute
		# (wholecell/processes/process.py:103-108), which Python dedupes after the first emission
		# -- so porting them verbatim would look like it worked and throw the data away.
		# n_terminated's content is already carried by the MonomerCounts write above (same
		# expression, same 4310-long monomer space). n_initialized must NOT be aliased onto our
		# existing didInitialize: that column is owned by PolypeptideInitiation
		# (polypeptide_initiation.py:282) and counts a different event, so writing it here would
		# corrupt an existing corpus column on a path that is supposed to be additive.
		self.writeToListener("RibosomeData", "processElongationRate", self.ribosomeElongationRate / self.timeStepSec())

		for molecule, gene in self.ribosome_profiling_molecules.items():
			molecule_index = self.ribosome_profiling_molecule_indexes[molecule]
			listener_size = self.ribosome_profiling_listener_sizes[molecule]

			ribosome_positions = np.zeros(listener_size, np.int64)
			ribosomes_on_MOI = protein_indexes == molecule_index
			for ribosome in np.where(ribosomes_on_MOI)[0]:
				ribosome_positions[updated_lengths[ribosome]] += 1
			self.writeToListener('TrnaCharging', f'ribosome_positions_{gene}', ribosome_positions)

		self.writeToListener('TrnaCharging', 'codons_read', codons_read)
		self.writeToListener('TrnaCharging', 'initiated', n_initiations)

	def isTimeStepShortEnough(self, inputTimeStep, timeStepSafetyFraction):
		model_specific = self.elongation_model.isTimeStepShortEnough(inputTimeStep, timeStepSafetyFraction)
		max_time_step = inputTimeStep <= self.max_time_step
		return model_specific and max_time_step


class BaseElongationModel(object):
	"""
	Base Model: Request amino acids according to upcoming sequence, assuming
	max ribosome elongation.
	"""
	def __init__(self, sim_data, process):
		self.process = process
		self.basal_elongation_rate = sim_data.constants.ribosome_elongation_rate_basal.asNumber(units.aa / units.s)
		self.ribosomeElongationRateDict = sim_data.process.translation.ribosomeElongationRateDict
		self.uncharged_trna_names = sim_data.process.transcription.uncharged_trna_names
		self.aaNames = sim_data.molecule_groups.amino_acids
		self.proton = self.process.bulkMoleculeView(sim_data.molecule_ids.proton)
		self.water = self.process.bulkMoleculeView(sim_data.molecule_ids.water)
		# EXT-PORT-8: v3.0.1 carries this on its BaseElongationModel and our base predates it.
		# KineticTrnaChargingModel inherits from THIS class, so without it the codon-aware host path
		# raises AttributeError on its first step. Additive: nothing on the steady-state path reads it.
		self.protein_lengths = sim_data.process.translation.monomer_data['length'].asNumber()

	def next_amino_acids(self, all_sequences, sequence_elongations):
		"""EXT-PORT-8: v3.0.1 BaseElongationModel's own implementation, verbatim.

		NOTHING OVERRIDES THIS. An earlier version of this docstring claimed KineticTrnaChargingModel did;
		it does not, in either tree -- `def next_amino_acids` appears exactly once here and once in
		v3.0.1, both returning 0.

		Harmless today and a live trap for the ppGpp unification. The only consumer is
		`ppgpp_metabolite_changes`, whose call site notes that the next amino acid must be included
		"otherwise f will be NaN" on a zero-elongation timestep -- and ppGpp is not computed on the
		codon-aware path at all, so the 0 is never consumed. Wiring ppGpp into the kinetic model without
		implementing this first gives NaN, not an error.

		The naive fix is also wrong: on the codon-aware path `all_sequences` is CODON space, so v3.0.1's
		steady-state `np.bincount(..., minlength=21)` returns a 63-long array there. A real implementation
		has to count in codon space and project through relation.codons_to_amino_acids."""
		return 0

	def elongation_rate(self):
		current_media_id = self.process._external_states['Environment'].current_media_id
		rate = self.process.elngRateFactor * self.ribosomeElongationRateDict[
			current_media_id].asNumber(units.aa / units.s)
		return np.min([self.basal_elongation_rate, rate])

	def amino_acid_counts(self, aasInSequences):
		return aasInSequences

	def request(self, aasInSequences):
		aa_counts_for_translation = self.amino_acid_counts(aasInSequences)

		self.process.aas.requestIs(aa_counts_for_translation)

		# Not modeling charging so set fraction charged to 0 for all tRNA
		fraction_charged = np.zeros(len(self.aaNames))

		return fraction_charged, aa_counts_for_translation

	def final_amino_acids(self, total_aa_counts):
		return total_aa_counts

	def evolve(self, total_aa_counts, aas_used, next_amino_acid_count, nElongations, nInitialized):
		# Update counts of amino acids and water to reflect polymerization reactions
		self.process.aas.countsDec(aas_used)
		self.water.countInc(nElongations - nInitialized)
		net_charged = np.zeros(len(self.uncharged_trna_names))

		return net_charged, {}

	def isTimeStepShortEnough(self, inputTimeStep, timeStepSafetyFraction):
		return True

class TranslationSupplyElongationModel(BaseElongationModel):
	"""
	Translation Supply Model: Requests minimum of 1) upcoming amino acid
	sequence assuming max ribosome elongation (ie. Base Model) and 2) estimation
	based on doubling the proteome in one cell cycle (does not use ribosome
	elongation, computed in Parca).
	"""
	def __init__(self, sim_data, process):
		super(TranslationSupplyElongationModel, self).__init__(sim_data, process)

	def elongation_rate(self):
		return self.basal_elongation_rate

	def amino_acid_counts(self, aasInSequences):
		return np.fmin(self.process.aa_supply, aasInSequences)  # Check if this is required. It is a better request but there may be fewer elongations.

class SteadyStateElongationModel(TranslationSupplyElongationModel):
	"""
	Steady State Charging Model: Requests amino acids based on the
	Michaelis-Menten competitive inhibition model.
	"""
	def __init__(self, sim_data, process):
		super(SteadyStateElongationModel, self).__init__(sim_data, process)
		constants = sim_data.constants
		transcription = sim_data.process.transcription
		metabolism = sim_data.process.metabolism
		molecule_ids = sim_data.molecule_ids
		molecule_groups = sim_data.molecule_groups

		# Cell parameters
		self.cellDensity = constants.cell_density

		# Names of molecules associated with tRNA charging
		self.charged_trna_names = transcription.charged_trna_names
		self.charging_molecule_names = transcription.charging_molecules
		self.synthetase_names = transcription.synthetase_names

		# Data structures for charging
		self.aa_from_synthetase = transcription.aa_from_synthetase
		self.charging_stoich_matrix = transcription.charging_stoich_matrix()
		self.charging_molecules_not_aa = np.array([
			mol not in set(self.aaNames)
			for mol in self.charging_molecule_names
			])

		# Create views for tRNA charging molecules
		self.uncharged_trna = self.process.bulkMoleculesView(self.uncharged_trna_names)
		self.charged_trna = self.process.bulkMoleculesView(self.charged_trna_names)
		self.charging_molecules = self.process.bulkMoleculesView(self.charging_molecule_names)
		self.synthetases = self.process.bulkMoleculesView(self.synthetase_names)

		# ppGpp synthesis
		self.ppgpp_reaction_metabolites = self.process.bulkMoleculesView(metabolism.ppgpp_reaction_metabolites)
		self.rela = self.process.bulkMoleculeView(molecule_ids.RelA)
		self.spot = self.process.bulkMoleculeView(molecule_ids.SpoT)
		self.ppgpp = self.process.bulkMoleculeView(molecule_ids.ppGpp)
		self.elong_rate_by_ppgpp = sim_data.growth_rate_parameters.get_ribosome_elongation_rate_by_ppgpp

		# Parameters for tRNA charging, ribosome elongation and ppGpp reactions
		self.charging_params = get_charging_params(sim_data,
			variable_elongation=self.process.variable_elongation)
		self.ppgpp_params = get_ppgpp_params(sim_data)

		# Amino acid supply calculations
		self.aa_supply_scaling = metabolism.aa_supply_scaling
		self.aa_environment = self.process.environmentView([aa[:-3] for aa in self.aaNames])

		# Manage unstable charging with too long time step by setting
		# time_step_short_enough to False during updates. Other variables
		# manage when to trigger an adjustment and how quickly the time step
		# increases after being reduced
		self.time_step_short_enough = True
		self.max_time_step = self.process.max_time_step
		self.time_step_increase = 1.01
		self.max_amino_acid_adjustment = 0.05

		self.aa_enzymes = self.process.bulkMoleculesView(metabolism.aa_enzymes)
		self.aa_aas = self.process.bulkMoleculesView(molecule_groups.amino_acids)
		self.amino_acid_synthesis = metabolism.amino_acid_synthesis
		self.amino_acid_import = metabolism.amino_acid_import
		self.amino_acid_export = metabolism.amino_acid_export
		self.get_pathway_enzyme_counts_per_aa = metabolism.get_pathway_enzyme_counts_per_aa

		self.aa_importers = self.process.bulkMoleculesView(metabolism.aa_importer_names)
		self.aa_exporters = self.process.bulkMoleculesView(metabolism.aa_exporter_names)

	def elongation_rate(self):
		if self.process.ppgpp_regulation and not self.process.disable_ppgpp_elongation_inhibition:
			cell_mass = self.process.readFromListener("Mass", "cellMass") * units.fg
			cell_volume = cell_mass / self.cellDensity
			counts_to_molar = 1 / (self.process.n_avogadro * cell_volume)
			ppgpp_conc = self.ppgpp.total_count() * counts_to_molar
			rate = self.elong_rate_by_ppgpp(ppgpp_conc, self.basal_elongation_rate).asNumber(units.aa / units.s)
		else:
			rate = super().elongation_rate()
		return rate

	def request(self, aasInSequences):
		self.max_time_step = min(self.process.max_time_step, self.max_time_step * self.time_step_increase)

		# Conversion from counts to molarity
		cell_mass = self.process.readFromListener("Mass", "cellMass") * units.fg
		dry_mass = self.process.readFromListener("Mass", "dryMass") * units.fg
		cell_volume = cell_mass / self.cellDensity
		self.counts_to_molar = 1 / (self.process.n_avogadro * cell_volume)

		# ppGpp related concentrations
		ppgpp_conc = self.counts_to_molar * self.ppgpp.total_count()
		rela_conc = self.counts_to_molar * self.rela.total_count()
		spot_conc = self.counts_to_molar * self.spot.total_count()

		# Get counts and convert synthetase and tRNA to a per AA basis
		synthetase_counts = np.dot(self.aa_from_synthetase, self.synthetases.total_counts())
		aa_counts = self.process.aas.total_counts()
		uncharged_trna_counts = np.dot(self.process.aa_from_trna, self.uncharged_trna.total_counts())
		charged_trna_counts = np.dot(self.process.aa_from_trna, self.charged_trna.total_counts())
		ribosome_counts = self.process.active_ribosomes.total_count()

		# Get concentration
		f = aasInSequences / aasInSequences.sum()
		synthetase_conc = self.counts_to_molar * synthetase_counts
		aa_conc = self.counts_to_molar * aa_counts
		uncharged_trna_conc = self.counts_to_molar * uncharged_trna_counts
		charged_trna_conc = self.counts_to_molar * charged_trna_counts
		ribosome_conc = self.counts_to_molar * ribosome_counts

		# Calculate amino acid supply
		aa_in_media = self.aa_environment.import_present()
		fwd_enzyme_counts, rev_enzyme_counts = self.get_pathway_enzyme_counts_per_aa(
			self.aa_enzymes.total_counts())
		importer_counts = self.aa_importers.total_counts()
		exporter_counts = self.aa_exporters.total_counts()
		synthesis, fwd_saturation, rev_saturation = self.amino_acid_synthesis(fwd_enzyme_counts, rev_enzyme_counts, aa_conc)
		import_rates = self.amino_acid_import(aa_in_media, dry_mass, aa_conc, importer_counts, self.process.mechanistic_aa_transport)
		export_rates = self.amino_acid_export(exporter_counts, aa_conc, self.process.mechanistic_aa_transport)
		exchange_rates = import_rates - export_rates

		supply_function = get_charging_supply_function(
			self.process.aa_supply_in_charging, self.process.mechanistic_translation_supply,
			self.process.mechanistic_aa_transport, self.amino_acid_synthesis,
			self.amino_acid_import, self.amino_acid_export, self.aa_supply_scaling,
			self.counts_to_molar, self.process.aa_supply, fwd_enzyme_counts, rev_enzyme_counts,
			dry_mass, importer_counts, exporter_counts, aa_in_media,
			)

		self.process.writeToListener('GrowthLimits', 'original_aa_supply', self.process.aa_supply)
		self.process.writeToListener('GrowthLimits', 'aa_in_media', aa_in_media)

		# Calculate steady state tRNA levels and resulting elongation rate
		self.charging_params['max_elong_rate'] = self.elongation_rate()
		fraction_charged, v_rib, synthesis_in_charging, import_in_charging, export_in_charging = calculate_trna_charging(
			synthetase_conc,
			uncharged_trna_conc,
			charged_trna_conc,
			aa_conc,
			ribosome_conc,
			f,
			self.charging_params,
			supply=supply_function,
			limit_v_rib=True,
			time_limit=self.process.timeStepSec())

		# Use the supply calculated from each sub timestep while solving the charging steady state
		if self.process.aa_supply_in_charging:
			conversion = 1 / self.counts_to_molar.asNumber(CONC_UNITS) / self.process.timeStepSec()
			synthesis = conversion * synthesis_in_charging
			import_rates = conversion * import_in_charging
			export_rates = conversion * export_in_charging
			self.process.aa_supply = synthesis + import_rates - export_rates
		# Use the supply calculated from the starting amino acid concentrations only
		else:
			if self.process.mechanistic_translation_supply:
				# Set supply based on mechanistic synthesis and supply
				self.process.aa_supply = self.process.timeStepSec() * (synthesis + exchange_rates)
			else:
				# Adjust aa_supply higher if amino acid concentrations are low
				# Improves stability of charging and mimics amino acid synthesis
				# inhibition and export
				self.process.aa_supply *= self.aa_supply_scaling(aa_conc, aa_in_media)
		self.process.aa_exchange_rates = self.counts_to_molar / units.s * (import_rates - export_rates)

		self.process.writeToListener('GrowthLimits', 'synthetase_conc', synthetase_conc.asNumber(CONC_UNITS))
		self.process.writeToListener('GrowthLimits', 'uncharged_trna_conc', uncharged_trna_conc.asNumber(CONC_UNITS))
		self.process.writeToListener('GrowthLimits', 'charged_trna_conc', charged_trna_conc.asNumber(CONC_UNITS))
		self.process.writeToListener('GrowthLimits', 'aa_conc', aa_conc.asNumber(CONC_UNITS))
		self.process.writeToListener('GrowthLimits', 'ribosome_conc', ribosome_conc.asNumber(CONC_UNITS))
		self.process.writeToListener('GrowthLimits', 'fraction_aa_to_elongate', f)

		aa_counts_for_translation = v_rib * f * self.process.timeStepSec() / self.counts_to_molar.asNumber(CONC_UNITS)

		total_trna = self.charged_trna.total_counts() + self.uncharged_trna.total_counts()
		final_charged_trna = stochasticRound(self.process.randomState, np.dot(fraction_charged, self.process.aa_from_trna * total_trna))

		charged_trna_request = self.charged_trna.total_counts() - final_charged_trna
		charged_trna_request[charged_trna_request < 0] = 0
		uncharged_trna_request = final_charged_trna - self.charged_trna.total_counts()
		uncharged_trna_request[uncharged_trna_request < 0] = 0

		self.aa_counts_for_translation = np.array(aa_counts_for_translation)

		fraction_trna_per_aa = total_trna / np.dot(np.dot(self.process.aa_from_trna, total_trna), self.process.aa_from_trna)
		total_charging_reactions = stochasticRound(self.process.randomState,
				np.dot(aa_counts_for_translation, self.process.aa_from_trna)
				* fraction_trna_per_aa + uncharged_trna_request)

		self.process.writeToListener('GrowthLimits', 'aa_supply', self.process.aa_supply)
		self.process.writeToListener('GrowthLimits', 'aa_synthesis', synthesis * self.process.timeStepSec())
		self.process.writeToListener('GrowthLimits', 'aa_import', import_rates * self.process.timeStepSec())
		self.process.writeToListener('GrowthLimits', 'aa_export', export_rates * self.process.timeStepSec())
		self.process.writeToListener('GrowthLimits', 'aa_supply_enzymes_fwd', fwd_enzyme_counts)
		self.process.writeToListener('GrowthLimits', 'aa_supply_enzymes_rev', rev_enzyme_counts)
		self.process.writeToListener('GrowthLimits', 'aa_importers', importer_counts)
		self.process.writeToListener('GrowthLimits', 'aa_exporters', exporter_counts)
		self.process.writeToListener('GrowthLimits', 'aa_supply_aa_conc', aa_conc.asNumber(units.mmol/units.L))
		self.process.writeToListener('GrowthLimits', 'aa_supply_fraction_fwd', fwd_saturation)
		self.process.writeToListener('GrowthLimits', 'aa_supply_fraction_rev', rev_saturation)

		# Only request molecules that will be consumed in the charging reactions
		aa_from_uncharging = -self.charging_stoich_matrix @ charged_trna_request
		aa_from_uncharging[self.charging_molecules_not_aa] = 0
		requested_molecules = -np.dot(self.charging_stoich_matrix, total_charging_reactions) - aa_from_uncharging
		requested_molecules[requested_molecules < 0] = 0
		self.charging_molecules.requestIs(requested_molecules)

		# Request charged tRNA that will become uncharged
		self.charged_trna.requestIs(charged_trna_request)
		self.uncharged_trna_to_charge = uncharged_trna_request

		# Request water for transfer of AA from tRNA for initial polypeptide.
		# This is severe overestimate assuming the worst case that every
		# elongation is initializing a polypeptide. This excess of water
		# shouldn't matter though.
		self.water.requestIs(aa_counts_for_translation.sum())

		# ppGpp reactions based on charged tRNA
		self.process.writeToListener('GrowthLimits', 'ppgpp_conc', ppgpp_conc.asNumber(CONC_UNITS))
		self.process.writeToListener('GrowthLimits', 'rela_conc', rela_conc.asNumber(CONC_UNITS))
		self.process.writeToListener('GrowthLimits', 'spot_conc', spot_conc.asNumber(CONC_UNITS))
		if self.process.ppgpp_regulation:
			total_trna_conc = self.counts_to_molar * (uncharged_trna_counts + charged_trna_counts)
			updated_charged_trna_conc = total_trna_conc * fraction_charged
			updated_uncharged_trna_conc = total_trna_conc - updated_charged_trna_conc
			delta_metabolites, *_ = ppgpp_metabolite_changes(
				updated_uncharged_trna_conc, updated_charged_trna_conc, ribosome_conc,
				f, rela_conc, spot_conc, ppgpp_conc, self.counts_to_molar, v_rib,
				self.charging_params, self.ppgpp_params, self.process.timeStepSec(),
				request=True, random_state=self.process.randomState,
			)

			request_ppgpp_metabolites = -delta_metabolites
			self.ppgpp_reaction_metabolites.requestIs(request_ppgpp_metabolites)
			self.ppgpp.requestAll()

		return fraction_charged, aa_counts_for_translation

	def final_amino_acids(self, total_aa_counts):
		charged_counts_to_uncharge = self.process.aa_from_trna @ self.charged_trna.counts()
		return np.fmin(total_aa_counts + charged_counts_to_uncharge, self.aa_counts_for_translation)

	def evolve(self, total_aa_counts, aas_used, next_amino_acid_count, nElongations, nInitialized):
		# Get tRNA counts
		uncharged_trna = self.uncharged_trna.counts()
		charged_trna = self.charged_trna.counts()
		total_trna = uncharged_trna + charged_trna

		# Adjust molecules for number of charging reactions that occurred
		## Determine limitations for charging and uncharging reactions
		charged_and_elongated_per_aa = np.fmax(0, (aas_used - self.process.aa_from_trna @ charged_trna))
		aa_for_charging = total_aa_counts - charged_and_elongated_per_aa
		n_aa_charged = np.fmin(aa_for_charging, np.dot(self.process.aa_from_trna, np.fmin(self.uncharged_trna_to_charge, uncharged_trna)))
		n_uncharged_per_aa = aas_used - charged_and_elongated_per_aa

		## Calculate changes in tRNA based on limitations
		n_trna_charged = self.distribution_from_aa(n_aa_charged, uncharged_trna, True)
		n_trna_uncharged = self.distribution_from_aa(n_uncharged_per_aa, charged_trna, True)

		## Determine reactions that are charged and elongated in same time step without changing
		## charged or uncharged counts
		charged_and_elongated = self.distribution_from_aa(charged_and_elongated_per_aa, total_trna)

		## Determine total number of reactions that occur
		total_uncharging_reactions = charged_and_elongated + n_trna_uncharged
		total_charging_reactions = charged_and_elongated + n_trna_charged
		net_charged = total_charging_reactions - total_uncharging_reactions
		self.charging_molecules.countsInc(np.dot(self.charging_stoich_matrix, total_charging_reactions))

		## Account for uncharging of tRNA during elongation
		self.charged_trna.countsDec(total_uncharging_reactions)
		self.uncharged_trna.countsInc(total_uncharging_reactions)

		# Update proton counts to reflect polymerization reactions and transfer of AA from tRNA
		# Peptide bond formation releases a water but transferring AA from tRNA consumes a OH-
		# Net production of H+ for each elongation, consume extra water for each initialization
		# since a peptide bond doesn't form
		self.proton.countInc(nElongations)
		self.water.countDec(nInitialized)

		# Create or degrade ppGpp
		# This should come after all countInc/countDec calls since it shares some molecules with
		# other views and those counts should be updated to get the proper limits on ppGpp reactions
		if self.process.ppgpp_regulation:
			v_rib = (nElongations * self.counts_to_molar).asNumber(CONC_UNITS) / self.process.timeStepSec()
			ribosome_conc = self.counts_to_molar * self.process.active_ribosomes.total_count()
			updated_uncharged_trna_counts = self.uncharged_trna.total_counts() - net_charged
			updated_charged_trna_counts = self.charged_trna.total_counts() + net_charged
			uncharged_trna_conc = self.counts_to_molar * np.dot(
				self.process.aa_from_trna, updated_uncharged_trna_counts)
			charged_trna_conc = self.counts_to_molar * np.dot(
				self.process.aa_from_trna, updated_charged_trna_counts)
			ppgpp_conc = self.counts_to_molar * self.ppgpp.total_count()
			rela_conc = self.counts_to_molar * self.rela.total_count()
			spot_conc = self.counts_to_molar * self.spot.total_count()

			# Need to include the next amino acid the ribosome sees for certain
			# cases where elongation does not occur, otherwise f will be NaN
			aa_at_ribosome = aas_used + next_amino_acid_count
			f = aa_at_ribosome / aa_at_ribosome.sum()
			limits = self.ppgpp_reaction_metabolites.counts()
			delta_metabolites, ppgpp_syn, ppgpp_deg, rela_syn, spot_syn, spot_deg, spot_deg_inhibited = ppgpp_metabolite_changes(
				uncharged_trna_conc, charged_trna_conc,	ribosome_conc, f, rela_conc,
				spot_conc, ppgpp_conc, self.counts_to_molar, v_rib,
				self.charging_params, self.ppgpp_params, self.process.timeStepSec(),
				random_state=self.process.randomState, limits=limits,
				)

			self.process.writeToListener('GrowthLimits', 'rela_syn', rela_syn)
			self.process.writeToListener('GrowthLimits', 'spot_syn', spot_syn)
			self.process.writeToListener('GrowthLimits', 'spot_deg', spot_deg)
			self.process.writeToListener('GrowthLimits', 'spot_deg_inhibited', spot_deg_inhibited)

			self.ppgpp_reaction_metabolites.countsInc(delta_metabolites)

		# Use the difference between (expected AA supply based on expected doubling time
		# and current DCW) and AA used to charge tRNA to update the concentration target
		# in metabolism during the next time step
		aa_used_trna = np.dot(self.process.aa_from_trna, total_charging_reactions)
		aa_diff = self.process.aa_supply - aa_used_trna
		if np.any(np.abs(aa_diff / self.process.aas.total_counts()) > self.max_amino_acid_adjustment):
			self.time_step_short_enough = False

		self.process.writeToListener('GrowthLimits', 'trnaCharged', aa_used_trna)
		return net_charged, {aa: diff for aa, diff in zip(self.aaNames, aa_diff)}

	def distribution_from_aa(self, n_aa, n_trna, limited=False):
		'''
		Distributes counts of amino acids to tRNAs that are associated with each amino acid.
		Uses self.process.aa_from_trna mapping to distribute from amino acids to tRNA based on the
		fraction that each tRNA species makes up for all tRNA species that code for the
		same amino acid.

		Inputs:
			n_aa (array of ints) - counts of each amino acid to distribute to each tRNA
			n_trna (array of ints) - counts of each tRNA to determine the distribution
			limited (bool) - optional, if True, limits the amino acids distributed to
				each tRNA to the number of tRNA that are available (n_trna)

		Returns:
			array of ints - distributed counts for each tRNA
		'''

		# Determine the fraction each tRNA species makes up out of all tRNA of the
		# associated amino acid
		with np.errstate(invalid='ignore'):
			f_trna = n_trna / np.dot(np.dot(self.process.aa_from_trna, n_trna), self.process.aa_from_trna)
		f_trna[~np.isfinite(f_trna)] = 0

		trna_counts = np.zeros(f_trna.shape, np.int64)
		for count, row in zip(n_aa, self.process.aa_from_trna):
			idx = (row == 1)
			frac = f_trna[idx]

			counts = np.floor(frac * count)
			diff = int(count - counts.sum())

			# Add additional counts to get up to counts to distribute
			# Prevent adding over the number of tRNA available if limited
			if diff > 0:
				if limited:
					for _ in range(diff):
						frac[(n_trna[idx] - counts) == 0] = 0
						frac /= frac.sum()  # normalize for multinomial distribution
						adjustment = self.process.randomState.multinomial(1, frac)
						counts += adjustment
				else:
					adjustment = self.process.randomState.multinomial(diff, frac)
					counts += adjustment

			trna_counts[idx] = counts

		return trna_counts

	def isTimeStepShortEnough(self, inputTimeStep, timeStepSafetyFraction):
		short_enough = True

		# Needs to be less than the max time step to prevent oscillatory behavior
		if inputTimeStep > self.max_time_step:
			short_enough = False

		# Decrease the max time step to get more stable charging
		if not self.time_step_short_enough and self.process.adjust_timestep_for_charging:
			self.max_time_step = inputTimeStep / 2
			self.time_step_short_enough = True
			short_enough = False

		return short_enough

def get_ppgpp_params(sim_data) -> Dict[str, Any]:
	"""
	Get parameters required for ppGpp reaction calulations to help
	encapsulate the function so that it does not need to be a class method.

	Args:
		sim_data: SimulationData object

	Returns:
		parameters that are used in ppgpp_metabolite_changes
	"""

	constants = sim_data.constants
	metabolism = sim_data.process.metabolism
	transcription = sim_data.process.transcription

	return dict(
		KD_RelA=transcription.KD_RelA.asNumber(CONC_UNITS),
		k_RelA=constants.k_RelA_ppGpp_synthesis.asNumber(1 / units.s),
		k_SpoT_syn=constants.k_SpoT_ppGpp_synthesis.asNumber(1 / units.s),
		k_SpoT_deg=constants.k_SpoT_ppGpp_degradation.asNumber(1 / (CONC_UNITS * units.s)),
		KI_SpoT=transcription.KI_SpoT.asNumber(CONC_UNITS),
		ppgpp_reaction_stoich=metabolism.ppgpp_reaction_stoich,
		synthesis_index=metabolism.ppgpp_reaction_names.index(metabolism.ppgpp_synthesis_reaction),
		degradation_index=metabolism.ppgpp_reaction_names.index(metabolism.ppgpp_degradation_reaction),
		)

def ppgpp_metabolite_changes(uncharged_trna_conc, charged_trna_conc,
		ribosome_conc, f, rela_conc, spot_conc, ppgpp_conc, counts_to_molar,
		v_rib, charging_params, ppgpp_params, time_step,
		request=False, limits=None, random_state=None):
	'''
	Calculates the changes in metabolite counts based on ppGpp synthesis and
	degradation reactions.

	Args:
		uncharged_trna_conc (np.array[float] with concentration units):
			concentration of uncharged tRNA associated with each amino acid
		charged_trna_conc (np.array[float] with concentration units):
			concentration of charged tRNA associated with each amino acid
		ribosome_conc (float with concentration units): concentration of active ribosomes
		f (np.array[float]): fraction of each amino acid to be incorporated
			to total amino acids incorporated
		rela_conc (float with concentration units): concentration of RelA
		spot_conc (float with concentration units): concentration of SpoT
		ppgpp_conc (float with concentration units): concentration of ppGpp
		counts_to_molar (float with concentration units): conversion factor
			from counts to molarity
		v_rib (float): rate of amino acid incorporation at the ribosome,
			in units of uM/s
		charging_params (Dict[str, Any]): parameters used in charging equations
			- this should be generated by get_charging_params
		ppgpp_params (Dict[str, Any]): parameters used in ppGpp reactions
			- this should be generated by get_ppgpp_params
		time_step (float): length of the current time step
		request (bool): if True, only considers reactant stoichiometry,
			otherwise considers reactants and products. For use in
			calculateRequest. GDP appears as both a reactant and product
			and the request can be off the actual use if not handled in this
			manner.
		limits (np.array[float]): counts of molecules that are available to prevent
			negative total counts as a result of delta_metabolites.
			If None, no limits are placed on molecule changes.
		random_state (np.random.RandomState): random state for the process

	Returns:
		delta_metabolites (np.array[int]): the change in counts of each metabolite
			involved in ppGpp reactions
		n_syn_reactions (int): the number of ppGpp synthesis reactions
		n_deg_reactions (int): the number of ppGpp degradation reactions
		v_rela_syn (np.ndarray[float]): rate of synthesis from RelA per amino
			acid tRNA species
		v_spot_syn (float): rate of synthesis from SpoT
		v_deg (float): rate of degradation from SpoT
		v_deg_inhibited (np.ndarray[float]): rate of degradation from SpoT per
			amino acid tRNA species
	'''

	if random_state is None:
		random_state = np.random.RandomState()

	uncharged_trna_conc = uncharged_trna_conc.asNumber(CONC_UNITS)
	charged_trna_conc = charged_trna_conc.asNumber(CONC_UNITS)
	ribosome_conc = ribosome_conc.asNumber(CONC_UNITS)
	rela_conc = rela_conc.asNumber(CONC_UNITS)
	spot_conc = spot_conc.asNumber(CONC_UNITS)
	ppgpp_conc = ppgpp_conc.asNumber(CONC_UNITS)
	counts_to_micromolar = counts_to_molar.asNumber(CONC_UNITS)

	numerator = 1 + charged_trna_conc / charging_params['krta'] + uncharged_trna_conc / charging_params['krtf']
	saturated_charged = charged_trna_conc / charging_params['krta'] / numerator
	saturated_uncharged = uncharged_trna_conc / charging_params['krtf'] / numerator
	if v_rib == 0:
		ribosome_conc_a_site = f * ribosome_conc
	else:
		ribosome_conc_a_site = f * v_rib / (saturated_charged * charging_params['max_elong_rate'])
	ribosomes_bound_to_uncharged = ribosome_conc_a_site * saturated_uncharged

	# Handle rare cases when tRNA concentrations are 0
	# Can result in inf and nan so assume a fraction of ribosomes
	# bind to the uncharged tRNA if any tRNA are present or 0 if not
	mask = ~np.isfinite(ribosomes_bound_to_uncharged)
	ribosomes_bound_to_uncharged[mask] = ribosome_conc * f[mask] * np.array(
		uncharged_trna_conc[mask] + charged_trna_conc[mask] > 0)

	# Calculate active fraction of RelA
	competitive_inhibition = 1 + ribosomes_bound_to_uncharged / ppgpp_params['KD_RelA']
	inhibition_product = np.prod(competitive_inhibition)
	with np.errstate(divide='ignore'):
		frac_rela = 1 / (ppgpp_params['KD_RelA'] / ribosomes_bound_to_uncharged * inhibition_product / competitive_inhibition + 1)

	# Calculate rates for synthesis and degradation
	v_rela_syn = ppgpp_params['k_RelA'] * rela_conc * frac_rela
	v_spot_syn = ppgpp_params['k_SpoT_syn'] * spot_conc
	v_syn = v_rela_syn.sum() + v_spot_syn
	max_deg = ppgpp_params['k_SpoT_deg'] * spot_conc * ppgpp_conc
	fractions = uncharged_trna_conc / ppgpp_params['KI_SpoT']
	v_deg =  max_deg / (1 + fractions.sum())
	v_deg_inhibited = (max_deg - v_deg) * fractions / fractions.sum()

	# Convert to discrete reactions
	n_syn_reactions = stochasticRound(random_state, v_syn * time_step / counts_to_micromolar)[0]
	n_deg_reactions = stochasticRound(random_state, v_deg * time_step / counts_to_micromolar)[0]

	# Only look at reactant stoichiometry if requesting molecules to use
	if request:
		ppgpp_reaction_stoich = np.zeros_like(ppgpp_params['ppgpp_reaction_stoich'])
		reactants = ppgpp_params['ppgpp_reaction_stoich'] < 0
		ppgpp_reaction_stoich[reactants] = ppgpp_params['ppgpp_reaction_stoich'][reactants]
	else:
		ppgpp_reaction_stoich = ppgpp_params['ppgpp_reaction_stoich']

	# Calculate the change in metabolites and adjust to limits if provided
	# Possible reactions are adjusted down to limits if the change in any
	# metabolites would result in negative counts
	max_iterations = int(n_deg_reactions + n_syn_reactions + 1)
	old_counts = None
	for it in range(max_iterations):
		delta_metabolites = (ppgpp_reaction_stoich[:, ppgpp_params['synthesis_index']] * n_syn_reactions
			+ ppgpp_reaction_stoich[:, ppgpp_params['degradation_index']] * n_deg_reactions)

		if limits is None:
			break
		else:
			final_counts = delta_metabolites + limits

			if np.all(final_counts >= 0) or (old_counts is not None and np.all(final_counts == old_counts)):
				break

			limited_index = np.argmin(final_counts)
			if ppgpp_reaction_stoich[limited_index, ppgpp_params['synthesis_index']] < 0:
				limited = np.ceil(final_counts[limited_index] / ppgpp_reaction_stoich[limited_index, ppgpp_params['synthesis_index']])
				n_syn_reactions -= min(limited, n_syn_reactions)
			if ppgpp_reaction_stoich[limited_index, ppgpp_params['degradation_index']] < 0:
				limited = np.ceil(final_counts[limited_index] / ppgpp_reaction_stoich[limited_index, ppgpp_params['degradation_index']])
				n_deg_reactions -= min(limited, n_deg_reactions)

			old_counts = final_counts
	else:
		raise ValueError('Failed to meet molecule limits with ppGpp reactions.')

	return delta_metabolites, n_syn_reactions, n_deg_reactions, v_rela_syn, v_spot_syn, v_deg, v_deg_inhibited

def get_charging_params(
		sim_data,
		aa_removed_from_charging: Optional[Set[str]] = None,
		variable_elongation: bool = False,
		) -> Dict[str, Any]:
	"""
	Get parameters required for tRNA charging calulations to help
	encapsulate the function so that it does not need to be a class method.

	Args:
		sim_data: SimulationData object
		aa_removed_from_charging: any amino acid IDs that should be ignored
			when calculating charging
		variable_elongation: if True, the max elongation rate is set to be
			higher

	Returns:
		parameters that are used in calculate_trna_charging
	"""

	constants = sim_data.constants
	metabolism = sim_data.process.metabolism
	transcription = sim_data.process.transcription
	if aa_removed_from_charging is None:
		aa_removed_from_charging = REMOVED_FROM_CHARGING
	aa_charging_mask = np.array([
		aa not in aa_removed_from_charging
		for aa in sim_data.molecule_groups.amino_acids
		])
	elongation_max = (constants.ribosome_elongation_rate_max
		if variable_elongation else constants.ribosome_elongation_rate_basal)

	return dict(
		kS=constants.synthetase_charging_rate.asNumber(1 / units.s),
		KMaa=transcription.aa_kms.asNumber(CONC_UNITS),
		KMtf=transcription.trna_kms.asNumber(CONC_UNITS),
		krta=constants.Kdissociation_charged_trna_ribosome.asNumber(CONC_UNITS),
		krtf=constants.Kdissociation_uncharged_trna_ribosome.asNumber(CONC_UNITS),
		max_elong_rate=float(elongation_max.asNumber(units.aa / units.s)),
		charging_mask=aa_charging_mask,
		unit_conversion=metabolism.get_amino_acid_conc_conversion(CONC_UNITS),
		)

def calculate_trna_charging(synthetase_conc, uncharged_trna_conc, charged_trna_conc, aa_conc, ribosome_conc,
		f, params, supply=None, time_limit=1000, limit_v_rib=False, use_disabled_aas=False):
	'''
	Calculates the steady state value of tRNA based on charging and incorporation through polypeptide elongation.
	The fraction of charged/uncharged is also used to determine how quickly the ribosome is elongating.

	Inputs:
		synthetase_conc (array of floats with concentration units) - concentration of synthetases associated
			with each amino acid
		uncharged_trna_conc (array of floats with concentration units) - concentration of uncharged tRNA associated
			with each amino acid
		charged_trna_conc (array of floats with concentration units) - concentration of charged tRNA associated
			with each amino acid
		aa_conc (array of floats with concentration units) - concentration of each amino acid
		ribosome_conc (float with concentration units) - concentration of active ribosomes
		f (array of floats) - fraction of each amino acid to be incorporated to total amino acids incorporated
		params (Dict[str, Any]) - parameters used in charging equations - this should be
			generated by get_charging_params
		supply (Callable) - function to get the rate of amino acid supply (synthesis and import)
			based on amino acid concentrations. If None, amino acid concentrations remain constant
			during charging
		time_limit (float) - time limit to reach steady state
		limit_v_rib (bool) - if True, v_rib is limited to the number of amino acids that are
			available
		use_disabled_aas (bool) - if True, all amino acids will be used for charging calculations,
			if False, some will be excluded as determined in initialize

	Returns:
		new_fraction_charged (array of floats) - fraction of total tRNA that is charged for each
			amino acid species
		v_rib (float) - ribosomal elongation rate in units of uM/s
		total_synthesis (np.ndarray) - the total amount of amino acids synthesized during charging
			in units of CONC_UNITS.  Will be zeros if supply function is not given.
		total_import (np.ndarray) - the total amount of amino acids imported during charging
			in units of CONC_UNITS.  Will be zeros if supply function is not given.
		total_export (np.ndarray) - the total amount of amino acids exported during charging
			in units of CONC_UNITS.  Will be zeros if supply function is not given.
	'''

	def negative_check(trna1, trna2):
		'''
		Check for floating point precision issues that can lead to small
		negative numbers instead of 0. Adjusts both species of tRNA to
		bring concentration of trna1 to 0 and keep the same total concentration.

		Args:
			trna1 (ndarray[float]): concentration of one tRNA species (charged or uncharged)
			trna2 (ndarray[float]): concentration of another tRNA species (charged or uncharged)
		'''

		mask = trna1 < 0
		trna2[mask] = trna1[mask] + trna2[mask]
		trna1[mask] = 0

	def dcdt(t, c):
		'''
		Function for solve_ivp to integrate

		Args:
			c (ndarray[float]): 1D array of concentrations of uncharged and charged tRNAs
				dims: 2 * number of amino acids (uncharged tRNA come first, then charged)
			t (float): time of integration step

		Returns:
			ndarray[float]: dc/dt for tRNA concentrations
				dims: 2 * number of amino acids (uncharged tRNA come first, then charged)
		'''
		v_charging, dtrna, daa = dcdt_jit(t, c, n_aas_masked, n_aas, mask, 
			params['kS'], synthetase_conc, params['KMaa'], params['KMtf'],
			f, params['krta'], params['krtf'], params['max_elong_rate'],
			ribosome_conc, limit_v_rib, aa_rate_limit, v_rib_max)
		if supply is None:
			v_synthesis = np.zeros(n_aas)
			v_import = np.zeros(n_aas)
			v_export = np.zeros(n_aas)
		else:
			aa_conc = c[2*n_aas_masked:2*n_aas_masked+n_aas]
			v_synthesis, v_import, v_export = supply(unit_conversion * aa_conc)
			v_supply = v_synthesis + v_import - v_export
			daa[mask] = v_supply[mask] - v_charging

		return np.hstack((-dtrna, dtrna, daa, v_synthesis, v_import, v_export))

	# Convert inputs for integration
	synthetase_conc = synthetase_conc.asNumber(CONC_UNITS)
	uncharged_trna_conc = uncharged_trna_conc.asNumber(CONC_UNITS)
	charged_trna_conc = charged_trna_conc.asNumber(CONC_UNITS)
	aa_conc = aa_conc.asNumber(CONC_UNITS)
	ribosome_conc = ribosome_conc.asNumber(CONC_UNITS)
	unit_conversion = params['unit_conversion']

	# Remove disabled amino acids from calculations
	n_total_aas = len(aa_conc)
	if use_disabled_aas:
		mask = np.ones(n_total_aas, bool)
	else:
		mask = params['charging_mask']
	synthetase_conc = synthetase_conc[mask]
	original_uncharged_trna_conc = uncharged_trna_conc[mask]
	original_charged_trna_conc = charged_trna_conc[mask]
	original_aa_conc = aa_conc[mask]
	f = f[mask]

	n_aas = len(aa_conc)
	n_aas_masked = len(original_aa_conc)

	# Limits for integration
	aa_rate_limit = original_aa_conc / time_limit
	trna_rate_limit = original_charged_trna_conc / time_limit
	v_rib_max = max(0, ((aa_rate_limit + trna_rate_limit) / f).min())

	# Integrate rates of charging and elongation
	c_init = np.hstack((original_uncharged_trna_conc, original_charged_trna_conc,
		aa_conc, np.zeros(n_aas), np.zeros(n_aas), np.zeros(n_aas)))
	sol = solve_ivp(dcdt, [0, time_limit], c_init, method='BDF')
	c_sol = sol.y.T

	# Determine new values from integration results
	final_uncharged_trna_conc = c_sol[-1, :n_aas_masked]
	final_charged_trna_conc = c_sol[-1, n_aas_masked:2*n_aas_masked]
	total_synthesis = c_sol[-1, 2*n_aas_masked+n_aas:2*n_aas_masked+2*n_aas]
	total_import = c_sol[-1, 2*n_aas_masked+2*n_aas:2*n_aas_masked+3*n_aas]
	total_export = c_sol[-1, 2*n_aas_masked+3*n_aas:2*n_aas_masked+4*n_aas]

	negative_check(final_uncharged_trna_conc, final_charged_trna_conc)
	negative_check(final_charged_trna_conc, final_uncharged_trna_conc)

	fraction_charged = final_charged_trna_conc / (final_uncharged_trna_conc + final_charged_trna_conc)
	numerator_ribosome = 1 + np.sum(f * (params['krta'] / final_charged_trna_conc + final_uncharged_trna_conc / final_charged_trna_conc * params['krta'] / params['krtf']))
	v_rib = params['max_elong_rate'] * ribosome_conc / numerator_ribosome
	if limit_v_rib:
		v_rib_max = max(0, ((original_aa_conc + (original_charged_trna_conc - final_charged_trna_conc)) / time_limit / f).min())
		v_rib = min(v_rib, v_rib_max)

	# Replace SEL fraction charged with average
	new_fraction_charged = np.zeros(n_total_aas)
	new_fraction_charged[mask] = fraction_charged
	new_fraction_charged[~mask] = fraction_charged.mean()

	return new_fraction_charged, v_rib, total_synthesis, total_import, total_export

@njit(error_model='numpy')
def dcdt_jit(t, c, n_aas_masked, n_aas, mask, 
	kS, synthetase_conc, KMaa, KMtf,
	f, krta, krtf, max_elong_rate,
	ribosome_conc, limit_v_rib, aa_rate_limit, v_rib_max
):
	uncharged_trna_conc = c[:n_aas_masked]
	charged_trna_conc = c[n_aas_masked:2*n_aas_masked]
	aa_conc = c[2*n_aas_masked:2*n_aas_masked+n_aas]
	masked_aa_conc = aa_conc[mask]

	v_charging = (kS * synthetase_conc * uncharged_trna_conc * masked_aa_conc / (KMaa[mask] * KMtf[mask])
		/ (1 + uncharged_trna_conc/KMtf[mask] + masked_aa_conc/KMaa[mask] + uncharged_trna_conc*masked_aa_conc/KMtf[mask]/KMaa[mask]))
	numerator_ribosome = 1 + np.sum(f * (krta / charged_trna_conc + uncharged_trna_conc / charged_trna_conc * krta / krtf))
	v_rib = max_elong_rate * ribosome_conc / numerator_ribosome

	# Handle case when f is 0 and charged_trna_conc is 0
	if not np.isfinite(v_rib):
		v_rib = 0

	# Limit v_rib and v_charging to the amount of available amino acids
	if limit_v_rib:
		v_charging = np.fmin(v_charging, aa_rate_limit)
		v_rib = min(v_rib, v_rib_max)

	dtrna = v_charging - v_rib*f
	daa = np.zeros(n_aas)
	
	return v_charging, dtrna, daa

def get_charging_supply_function(
		supply_in_charging: bool,
		mechanistic_supply: bool,
		mechanistic_aa_transport: bool,
		amino_acid_synthesis: Callable,
		amino_acid_import: Callable,
		amino_acid_export: Callable,
		aa_supply_scaling: Callable,
		counts_to_molar: units.Unum,
		aa_supply: np.ndarray,
		fwd_enzyme_counts: np.ndarray,
		rev_enzyme_counts: np.ndarray,
		dry_mass: units.Unum,
		importer_counts: np.ndarray,
		exporter_counts: np.ndarray,
		aa_in_media: np.ndarray,
		) -> Optional[Callable[[np.ndarray], Tuple[np.ndarray, np.ndarray, np.ndarray]]]:
	"""
	Get a function mapping internal amino acid concentrations to the amount of
	amino acid supply expected.

	Args:
		supply_in_charging: True if using the aa_supply_in_charging option
		mechanistic_supply: True if using the mechanistic_translation_supply option
		mechanistic_aa_transport: True if using the mechanistic_aa_transport option
		amino_acid_synthesis: function to provide rates of synthesis for amino
			acids based on the internal state
		amino_acid_import: function to provide import rates for amino
			acids based on the internal and external state
		amino_acid_export: function to provide export rates for amino
			acids based on the internal state
		aa_supply_scaling: function to scale the amino acid supply based
			on the internal state
		counts_to_molar: conversion factor for counts to molar in units of counts/volume
		aa_supply: rate of amino acid supply expected
		fwd_enzyme_counts: counts for enzymes in forward reactions for each amino acid
		rev_enzyme_counts: counts for enzymes in loss reactions for each amino acid
		dry_mass: dry mass of the cell with mass units
		importer_counts: counts for amino acid importers
		exporter_counts: counts for amino acid exporters
		aa_in_media: True for each amino acid that is present in the media

	Returns:
		supply_function: function that provides the amount of supply (synthesis, import, export)
			for each amino acid based on the internal state of the cell
	"""

	# Create functions that are only dependent on amino acid concentrations for more stable
	# charging and amino acid concentrations.  If supply_in_charging is not set, then
	# setting None will maintain constant amino acid concentrations throughout charging.
	supply_function = None
	if supply_in_charging:
		counts_to_molar = counts_to_molar.asNumber(CONC_UNITS)
		zeros = counts_to_molar * np.zeros_like(aa_supply)
		if mechanistic_supply:
			if mechanistic_aa_transport:
				supply_function = lambda aa_conc: (
					counts_to_molar * amino_acid_synthesis(fwd_enzyme_counts, rev_enzyme_counts, aa_conc)[0],
					counts_to_molar * amino_acid_import(aa_in_media, dry_mass, aa_conc, importer_counts, mechanistic_aa_transport),
					counts_to_molar * amino_acid_export(exporter_counts, aa_conc, mechanistic_aa_transport),
					)
			else:
				supply_function = lambda aa_conc: (
					counts_to_molar * amino_acid_synthesis(fwd_enzyme_counts, rev_enzyme_counts, aa_conc)[0],
					counts_to_molar * amino_acid_import(aa_in_media, dry_mass, aa_conc, importer_counts, mechanistic_aa_transport),
					zeros,
					)
		else:
			supply_function = lambda aa_conc: (
				counts_to_molar * aa_supply * aa_supply_scaling(aa_conc, aa_in_media),
				zeros,
				zeros,
				)

	return supply_function


class KineticTrnaChargingModel(BaseElongationModel):
	"""
	Kinetic tRNA Charging Model: Elongate polypeptides according to the
	kinetics limits of tRNA synthetases and the codon sequence.

	Note: L-SELENOCYSTEINE is modeled as unlimited incorporation into
	polypeptides (as in TranslationSupplyElongationModel) by describing
	a high kcat.
	"""
	def __init__(self, sim_data, process):
		super(KineticTrnaChargingModel, self).__init__(sim_data, process)

		# Constants
		self.cell_density = sim_data.constants.cell_density
		self.n_avogadro = sim_data.constants.n_avogadro

		# Codon sequences
		relation = sim_data.relation
		self.protein_sequences = relation.codon_sequences
		self.monomer_weights_incorporated = relation.residue_weights_by_codon
		self.n_monomers = len(relation.codons)
		self.i_start_codon = relation.codons.index(
			sim_data.molecule_ids.start_codon)

		# Molecules and their views
		amino_acids = sim_data.molecule_groups.amino_acids

		synthetases = []
		for amino_acid in amino_acids:
			synthetases.append(relation.amino_acid_to_synthetase[amino_acid])

		transcription = sim_data.process.transcription
		# EXT-PORT-5: `rna_data['id'][rna_data['is_tRNA']]` is the v3.0.1 idiom and it is wrong here for
		# the same reason it was wrong in relation.py — with operons ON, rna_data is TRANSCRIPTION
		# UNITS. Measured: it yields 51 TU ids against the 86 cistron ids everything else uses, an
		# intersection of 9. `relation.trna_to_K_T.get(trna, 1*units.umol/units.L)` would then have
		# silently defaulted 42 of 51 lookups — a .get with a default CANNOT fail loudly — and the
		# 51-vs-86 width disagreement crashes this constructor a few lines below.
		# SteadyStateElongationModel already uses uncharged_trna_names in this same file.
		free_trnas = list(transcription.uncharged_trna_names)
		charged_trnas = transcription.charged_trna_names

		self.amino_acids = self.process.bulkMoleculesView(amino_acids)
		self.free_trnas = self.process.bulkMoleculesView(free_trnas)
		self.charged_trnas = self.process.bulkMoleculesView(charged_trnas)
		self.synthetases = self.process.bulkMoleculesView(synthetases)
		self.atp = self.process.bulkMoleculeView('ATP[c]')
		self.amp = self.process.bulkMoleculeView('AMP[c]')
		self.ppi = self.process.bulkMoleculeView('PPI[c]')
		self.met = self.process.bulkMoleculeView('MET[c]')
		self.map = self.process.bulkMoleculeView('EG10570-MONOMER[c]')
		self.is_map_substrate = sim_data.process.translation\
			.monomer_data['cleavage_of_initial_methionine']

		# Tools for interacting with the ODE model
		self.n_trnas = len(free_trnas)
		self.n_codons = len(relation.codons)
		n_codon_trna_pairs = len(relation.trna_codon_pairs)
		slice_lengths = [
			self.n_trnas, # for free trnas
			self.n_trnas, # for charged trnas
			len(amino_acids), # for amino acids
			self.n_trnas, # for charging counter
			self.n_trnas, # for reading counter
			n_codon_trna_pairs,
			]
		self.molecules_input_size = sum(slice_lengths)

		slices = []
		previous = 0
		for length in slice_lengths:
			slices.append(slice(previous, previous + length))
			previous += length

		self.slice_free_trnas = slices[0]
		self.slice_charged_trnas = slices[1]
		self.slice_amino_acids = slices[2]
		self.slice_charging_counter = slices[3]
		self.slice_reading_counter = slices[4]
		self.slice_codons_to_trnas_counter = slices[5]

		self.trnas_to_amino_acids = transcription.aa_from_trna.astype(np.int64)
		self.amino_acids_to_trnas = transcription.aa_from_trna.T
		self.trnas_to_codons = relation.trnas_to_codons
		self.codons_to_trnas = relation.trnas_to_codons.T.astype(np.bool_)
		self.codons_to_amino_acids = relation.codons_to_amino_acids
		self.trnas_to_amino_acid_indexes = np.zeros(self.n_trnas, dtype=np.int8)
		for i in range(self.trnas_to_amino_acids.shape[1]):
			j = np.where(self.trnas_to_amino_acids[:, i])[0][0]
			self.trnas_to_amino_acid_indexes[i] = j
		self.max_attempts = np.byte(4)

		# Kinetic parameters
		# Set selenocysteine to a high value to represent unlimited
		# charging
		self.k_cat__per_s = np.array(
			[relation.synthetase_to_k_cat.get(
				synthetase,
				1e4 / units.s
			).asNumber(1/units.s) for synthetase in synthetases],
			dtype=np.float64)

		self.K_M_amino_acid__per_L = np.array(
			[(relation.synthetase_to_K_A.get(
				synthetase,
				1 * units.umol / units.L
			) * self.n_avogadro
			).asNumber(1/units.L) for synthetase in synthetases],
			dtype=np.float64)

		self.K_M_trna__per_L = np.array(
			[(relation.trna_to_K_T.get(
				trna,
				1 * units.umol / units.L
			) * self.n_avogadro).asNumber(1/units.L) for trna in free_trnas],
			dtype=np.float64)

		# Width buffer: The reconciliation program in this elongation
		# model uses the surrounding codon sequence (towards both the
		# N and C terminals) to reconcile disagreements between the
		# kinetics and sequence limits. This width buffer describes
		# the additional sequence positions (towards the C terminal)
		# to view during each time step.
		# EXT-PORT-10: shared with reconstruction/ecoli/dataclasses/relation.py, which pads
		# codon_sequences wide enough to contain ceil(basal_rate * dt) + this buffer. Changing it in
		# one place now changes it in both; as a literal it did not.
		self.buffer = KINETIC_TRNA_CHARGING_WIDTH_BUFFER

		# Previous rate: the previous ribosome elongation rate is
		# recorded to warm start the next time step's binary search. For
		# the first time step, the basal elongation rate (~17.3 aa/s) is
		# used.
		self.previous_rate = int(self.process.ribosomeElongationRate
			* self.process.timeStepSec())

	def record_mass(self):
		self.cell_mass = units.fg * self.process.readFromListener(
			'Mass', 'cellMass')
		return

	def elongation_rate(self, current_media_id, protein_indexes,
			peptide_lengths):

		self.sequences_width = np.array([np.ceil(
			(self.basal_elongation_rate * self.process.timeStepSec())
			+ self.buffer).astype(int)])

		self.longer_sequences = buildSequences(
			self.protein_sequences,
			protein_indexes,
			peptide_lengths,
			self.sequences_width)

		target = (self.ribosomeElongationRateDict[current_media_id]
			).asNumber(units.aa / units.s)

		rate = get_elongation_rate(
			self.longer_sequences,
			self.previous_rate,
			self.process.timeStepSec(),
			target)

		self.previous_rate = int(rate * self.process.timeStepSec())
		return rate

	def request(self, monomers_in_sequences, protein_indexes, current_media_id,
			peptide_lengths):
		'''
		Requests molecules utilized in the Kinetic tRNA Charging Model.

		Inputs:
		monomers_in_sequences (array): codons to encounter
		protein_indexes (array): protein indexes of active ribosomes

		Returns:
		f_charged (array): charged fraction of trnas
		aa_request (array): amino acids requested

		Notes:
		Requests 1% more amino acids as a buffer pool used during
		discretization and reconciliation.

		Since only net changes can be made on the tRNAs, only net
		corresponding changes are made for the metabolites participating
		in the charging reaction.
		'''

		# Initiation
		water_request = monomers_in_sequences[self.i_start_codon]

		# Simulate trna charging and codon reading
		(amino_acids_used, codons_read, free_trnas, charged_trnas, _, _
			) = self.run_model(monomers_in_sequences, 'total')
		self.first = amino_acids_used

		# Record the number of codons read for use in monomer_limit().
		self.codons_kinetics_model = codons_read

		# Request amino acids
		# Note: + 1 is to enable a non-zero buffer
		self.amino_acids.requestIs(np.ceil(1.01 * (amino_acids_used + 1)))

		# Request ATP
		# Note: Assuming all amino acids are used for charging is an
		# overestimation in this model (actual value would be the net
		# number of amino acids that end up in charged-tRNAs); but the
		# overestimation is helpful for reconciliation steps in evolve
		# so the overestimation is used here.
		self.atp.requestIs(amino_acids_used.sum())

		# Request all tRNAs
		self.free_trnas.requestAll()
		self.charged_trnas.requestAll()

		# Request all synthetase enzymes
		self.synthetases.requestAll()

		# Request methionine aminopeptidase
		self.map.requestAll()

		# Termination
		may_terminate = self.longer_sequences[:, -1] == -1
		max_to_cleave = np.sum(np.bincount(
			protein_indexes[may_terminate],
			minlength=self.protein_sequences.shape[0]
			)[self.is_map_substrate])
		water_request += max_to_cleave
		self.water.requestIs(water_request)

		# Calculate the charged fraction of trnas
		fraction_charged = charged_trnas / (free_trnas + charged_trnas)

		return fraction_charged, amino_acids_used

	def run_model(self, codons, attr):

		def ode_model(t, molecules, target_codon_rate, v_max,
				cell_amino_acid_saturation, K_M_amino_acids, K_M_trnas,
				amino_acid_limit,
				):

			# Parse molecules
			free_trnas = molecules[self.slice_free_trnas]
			charged_trnas = molecules[self.slice_charged_trnas]
			amino_acids_remaining = molecules[self.slice_amino_acids]

			# Adjust target codon reading rate, if needed
			fraction_charged = (self.trnas_to_codons @ charged_trnas
				/ (self.trnas_to_codons @ charged_trnas
					+ self.trnas_to_codons @ free_trnas))
			needs_adjustment = fraction_charged < 0.05
			adjustment = np.ones_like(target_codon_rate)
			adjustment[needs_adjustment] = np.sin(10
				* np.pi
				* fraction_charged[needs_adjustment])
			adjusted_codon_rate = np.multiply(adjustment, target_codon_rate)

			# Adjust amino acid saturation, if needed
			# amino_acid_availability may be 0
			mask = amino_acid_availability > 0
			fraction_remaining = np.zeros_like(amino_acids_remaining)
			fraction_remaining[mask] = (amino_acids_remaining[mask]
				/ amino_acid_availability[mask])
			needs_adjustment = fraction_remaining < 0.05
			adjustment = np.ones_like(cell_amino_acid_saturation)
			adjustment[needs_adjustment] = np.square(np.sin(
				10 * np.pi * fraction_remaining[needs_adjustment]))
			adjusted_amino_acid_saturation = np.multiply(
				adjustment, cell_amino_acid_saturation)

			# Charge tRNAs
			relative_trnas = free_trnas / K_M_trnas
			charging_rate = (self.amino_acids_to_trnas
				@ np.multiply(v_max, adjusted_amino_acid_saturation)
				* relative_trnas
				/ (1 + (self.amino_acids_to_trnas
					@ self.trnas_to_amino_acids
					@ relative_trnas)))

			# Describe distribution of codons to be read by each trna
			# Note: columns of codons_to_trnas sum to 1
			charged_trnas_tile = np.tile(charged_trnas, (self.n_codons, 1)).T
			codons_to_trnas = np.where(
				self.codons_to_trnas, charged_trnas_tile, 0)
			denominator = codons_to_trnas.sum(axis=0)
			denominator[denominator == 0] = 1 # to prevent divide by 0
			codons_to_trnas /= denominator

			# Read codons
			reading_rate = codons_to_trnas @ adjusted_codon_rate

			# Describe change in molecules
			dx_dt = np.zeros_like(molecules)
			dx_dt[self.slice_free_trnas] = -charging_rate + reading_rate
			dx_dt[self.slice_charged_trnas] = charging_rate - reading_rate
			dx_dt[self.slice_amino_acids] = -(
				self.trnas_to_amino_acids @ charging_rate)

			dx_dt[self.slice_charging_counter] = charging_rate
			dx_dt[self.slice_reading_counter] = reading_rate
			dx_dt[self.slice_codons_to_trnas_counter] = np.multiply(
				codons_to_trnas,
				np.tile(adjusted_codon_rate, (self.n_trnas, 1))
				)[self.codons_to_trnas]

			return dx_dt # dx/dt

		# Describe ODE model constants
		if attr == 'total':
			# First call in this time step
			self.K_M_amino_acids, self.K_M_trnas = self.get_kinetic_constants()
			cell_amino_acids = self.amino_acids.total()
			self.cell_amino_acid_saturation = (cell_amino_acids
				/ (self.K_M_amino_acids + cell_amino_acids))

		# Describe ODE model input
		free_trnas_input = getattr(self.free_trnas, attr)()
		charged_trnas_input = getattr(self.charged_trnas, attr)()
		amino_acid_availability = getattr(self.amino_acids, attr)()

		molecules_input = np.zeros(self.molecules_input_size, dtype=np.int64)
		molecules_input[self.slice_free_trnas] = free_trnas_input
		molecules_input[self.slice_charged_trnas] = charged_trnas_input
		molecules_input[self.slice_amino_acids] = amino_acid_availability

		# Run ODE model
		ode_result = solve_ivp(
			ode_model,
			[0, self.process.timeStepSec()],
			molecules_input,
			args=(
				codons / self.process.timeStepSec(),
				self.max_charging_rate(attr),
				self.cell_amino_acid_saturation,
				self.K_M_amino_acids,
				self.K_M_trnas,
				amino_acid_availability,
				),
			method='RK45',
			rtol=1e-4, # default is 1e-3
			atol=1e-7, # default is 1e-6
			)

		################################################################
		# Listening
		if attr == 'counts':

			# Get internal time steps of the RK45 solver
			delta_t = ode_result.t[1:] - ode_result.t[:-1]

			# Record average trna saturation
			relative_trnas = (ode_result.y[self.slice_free_trnas, :]
				/ self.K_M_trnas[:, None])
			trna_saturation = (relative_trnas
				/ (1 + (self.amino_acids_to_trnas
					@ self.trnas_to_amino_acids
					@ relative_trnas)))
			average_trna_saturation = np.sum(
				np.multiply(
					trna_saturation[:, 1:],
					delta_t
					),
				axis=1) / self.process.timeStepSec()

			self.process.writeToListener(
				'TrnaCharging', 'saturation_trna', average_trna_saturation)

			# Record turnover
			turnovers = []
			previous_readings = np.zeros(self.n_trnas, dtype=np.int64)
			for i in range(ode_result.t.shape[0] - 1):

				# Calculate readings
				codons_to_trnas_matrix = np.zeros(
					(self.n_trnas, self.n_codons), dtype=np.int64)
				codons_to_trnas_matrix[self.codons_to_trnas]\
					= ode_result.y[self.slice_codons_to_trnas_counter, i]
				readings = codons_to_trnas_matrix.sum(axis=1)
				delta_readings = readings - previous_readings

				# Calculate incorporation into nascent polypeptides
				incorporation = (self.trnas_to_amino_acids @ delta_readings)

				# Calculate charged trnas
				charged_trnas = (self.trnas_to_amino_acids
					@ ode_result.y[self.slice_charged_trnas, i])

				# Calculate turnover
				# EXT-PORT-10: turnover is UNDEFINED, not zero, for an amino acid whose charged pool is
				# empty at this internal solver step -- and an empty pool is exactly the interesting
				# case. The bare division produced NaN (0/0) or inf (x/0) plus a RuntimeWarning per
				# occurrence; NaN is kept as the value, because 0.0 would read as 'no turnover' rather
				# than 'no charged tRNA to turn over'. It is now produced deliberately and the warning
				# is not raised, instead of arriving as an arithmetic accident.
				turnover = np.full(charged_trnas.shape, np.nan, dtype=np.float64)
				np.divide(
					incorporation / delta_t[i],
					charged_trnas,
					out=turnover,
					where=(charged_trnas != 0))
				turnovers.append(turnover)

				# Record readings
				previous_readings = readings

			# Calculate average turnover
			turnovers = np.array(turnovers)
			average_turnover = np.sum(
				np.multiply(
					turnovers.T,
					delta_t
					),
				axis=1) / self.process.timeStepSec()
			self.process.writeToListener(
				'TrnaCharging', 'turnover', average_turnover)

		################################################################
		# Parse ODE results
		molecules_output = ode_result.y[:, -1]
		raw_charging = molecules_output[self.slice_charging_counter]
		raw_reading = molecules_output[self.slice_reading_counter]
		raw_codons_to_trnas = molecules_output[
			self.slice_codons_to_trnas_counter]

		################################################################
		# Discretize charging events

		# For estimating request: round up
		if attr == 'total':
			chargings = np.ceil(raw_charging).astype(np.int64)

		# For calculating evolve: round stochastically
		else:
			chargings = stochasticRound(
				self.process.randomState, raw_charging).astype(np.int64)

		# Check that the sum of charging events does not exceed the
		# availability of amino acids
		amino_acids_used = self.trnas_to_amino_acids @ chargings
		exceeds_availability = amino_acids_used > amino_acid_availability
		if np.any(exceeds_availability):
			for i in np.where(exceeds_availability)[0]:
				n_undo = amino_acids_used[i] - amino_acid_availability[i]
				trna_indexes = np.where(self.trnas_to_amino_acids[i])[0]

				for j in range(n_undo):
					i_undo = np.argsort(
						(chargings - raw_charging)[trna_indexes])[-1]
					chargings[trna_indexes[i_undo]] -= 1
			amino_acids_used = self.trnas_to_amino_acids @ chargings
			exceeds_availability = amino_acids_used > amino_acid_availability
			assert np.all(exceeds_availability == False)
		assert np.all(chargings >= 0)

		################################################################
		# Discretize reading events

		# For estimating request: round up
		if attr == 'total':
			codons_to_trnas = np.ceil(raw_codons_to_trnas).astype(np.int64)

		# For calculating evolve: round stochastically
		else:
			codons_to_trnas = stochasticRound(
				self.process.randomState, raw_codons_to_trnas).astype(np.int64)

		# Assemble codons-to-trnas interactions matrix
		codons_to_trnas_matrix = np.zeros(
			(self.n_trnas, self.n_codons), dtype=np.int64)
		codons_to_trnas_matrix[self.codons_to_trnas] = codons_to_trnas

		# Check that all readings are positive
		readings = codons_to_trnas_matrix.sum(axis=1)
		assert np.all(readings >= 0)

		# Calculate the number of codons read
		codons_read = codons_to_trnas_matrix.sum(axis=0)

		################################################################

		# Calculate the resulting number of trnas
		free_trnas = (free_trnas_input - chargings + readings)
		charged_trnas = (charged_trnas_input + chargings - readings)

		# Check that the availability of trnas has not been exceeded
		if np.any(free_trnas < 0):
			for i in np.where(free_trnas < 0)[0]:
				n_undo = abs(free_trnas[i])

				for j in range(n_undo):
					chargings[i] -= 1

			assert np.all(chargings >= 0)

			free_trnas = (free_trnas_input - chargings + readings)
			assert np.all(free_trnas >= 0)

			amino_acids_used = self.trnas_to_amino_acids @ chargings

		if np.any(charged_trnas < 0):
			for i in np.where(charged_trnas < 0)[0]:
				n_undo = abs(charged_trnas[i])
				codon_indexes = np.where(codons_to_trnas_matrix[i])[0]

				for j in range(n_undo):
					i_undo = np.argsort(
						codons_to_trnas_matrix[i, codon_indexes])[-1]
					codons_to_trnas_matrix[i, codon_indexes[i_undo]] -= 1

			readings = codons_to_trnas_matrix.sum(axis=1)
			assert np.all(readings >= 0)

			charged_trnas = (charged_trnas_input + chargings - readings)
			assert np.all(charged_trnas >= 0)

		# Update the resulting number of trnas
		free_trnas = (free_trnas_input - chargings + readings)
		charged_trnas = (charged_trnas_input + chargings - readings)

		net_charged = charged_trnas - charged_trnas_input

		return (amino_acids_used, codons_read, free_trnas,
			charged_trnas, chargings, codons_to_trnas_matrix)

	def max_charging_rate(self, attr):
		n_synthetases = getattr(self.synthetases, attr)()
		v_max = self.k_cat__per_s * n_synthetases
		return v_max

	def get_kinetic_constants(self):
		cell_volume = self.cell_mass / self.cell_density
		cell_volume = cell_volume.asNumber(units.L).astype(np.float64)
		K_M_amino_acids = self.K_M_amino_acid__per_L * cell_volume
		K_M_trnas = self.K_M_trna__per_L * cell_volume
		return K_M_amino_acids, K_M_trnas

	def monomer_to_aa(self, monomer):
		return self.codons_to_amino_acids @ monomer

	def monomer_limit(self, allocated_aas, monomer_count_in_sequence):
		return (
			self.codons_kinetics_model,
			self.codons_to_amino_acids @ self.codons_kinetics_model)

	def next_amino_acids(self, all_sequences, sequence_elongations):
		"""EXT-PORT-10: the codon-space implementation of v3.0.1's SteadyStateElongationModel method.

		BaseElongationModel returns a hard-coded 0 and nothing overrode it here, in either tree. The
		only consumer is ppgpp_metabolite_changes, whose call site notes the next amino acid must be
		included 'otherwise f will be NaN' on a zero-elongation timestep -- so the 0 is harmless only
		while ppGpp is not computed on the codon-aware path, and it is the first thing that bites when
		ppGpp is wired in.

		TWO things make the verbatim v3.0.1 body wrong here.

		SPACE. This model's sequences are CODONS (63 values), not amino acids (21), so
		np.bincount(..., minlength=21) would return a 63-long array and the caller would hand a
		codon-indexed vector to something expecting amino acids -- silently, since 63 >= 21. Count in
		codon space, then project through relation.codons_to_amino_acids (21 x 63).

		WIDTH. sequence_elongations comes back from reconcile(), and reconcile_via_ribosome_positions
		takes forward steps bounded by self.longer_sequences.shape[1] (the kinetic window, 32), which
		is WIDER than all_sequences (elongation_rates.max() + next_aa_pad, 23 or 31). Indexing
		all_sequences with those elongations can therefore run off the end. Read from longer_sequences
		-- the array this model's reconciliation actually operated on, row-aligned with
		sequence_elongations exactly as sequences() relies on for computeMassIncrease -- and drop the
		ribosomes whose next codon falls outside even that window. Their next codon is genuinely not
		visible this step, which is the same status as PAD.
		"""
		sequences = self.longer_sequences
		visible = sequence_elongations < sequences.shape[1]
		# EXT-PORT-12 (UNIFY-2 gate): quantify the residual instead of assuming it is small.
		#
		# The drop below is FORCED (see the WIDTH paragraph above), so this term cannot be made
		# identical to the steady-state path's, and next_amino_acid_count is a direct RelA input.
		# The audit could not bound the difference because the mask had no listener at all -- so it
		# gets one. next_aa_ribosomes_dropped is the count of ribosomes whose next codon is outside
		# even the kinetic window this step; next_aa_ribosomes_total is the denominator. Both are
		# zero on the steady-state path, where they are declared unwritten in the TrnaCharging
		# listener's attributes rather than left to read as measurements.
		self.process.writeToListener(
			'TrnaCharging', 'next_aa_ribosomes_dropped', int((~visible).sum()))
		self.process.writeToListener(
			'TrnaCharging', 'next_aa_ribosomes_total', int(visible.size))
		next_codons = sequences[
			np.arange(len(sequence_elongations))[visible],
			sequence_elongations[visible]]
		next_codons = next_codons[next_codons != polymerize.PAD_VALUE].astype(np.int64)
		codon_counts = np.bincount(next_codons, minlength=self.n_codons)
		return self.codons_to_amino_acids @ codon_counts

	def codon_sequences_width(self, elongation_rates):
		return self.sequences_width

	def _reconcile_seed(self):
		"""EXT-PORT-12 (UNIFY-2 gate): a reproducible seed for the C stdlib RNG in the two
		reconciliation kernels.

		`srand` takes an unsigned int, so the draw is bounded to 32 bits. It comes from
		self.process.randomState -- the per-process np.random.RandomState that
		wholecell/sim/simulation.py:221-222 seeds with crc32(process_name, sim_seed) -- so the C
		stream is a deterministic function of --seed, and it advances with the same call sequence
		the rest of this process already uses (stochasticRound in protein_maturation draws from
		the same generator).

		Deliberately NOT seeded from the step number or the wall clock: the step number would give
		two different simulations the same reconciliation randomness, and the wall clock is the
		defect being fixed.

		Bound is 2**31 - 1, not 2**32: np.random.RandomState.randint defaults to dtype np.int_,
		which is int32 on Windows, and a 2**32 bound would raise there while working on Linux.
		31 bits is ample for a reconciliation tie-break.
		"""
		return int(self.process.randomState.randint(0, 2**31 - 1))

	def reconcile(self, result):
		result_copy = copy.deepcopy(result)

		# Simulate trna charging and codon reading (using allocated
		# counts)
		(amino_acids_used, codons_read, free_trnas, charged_trnas,
			chargings, codons_to_trnas_matrix) = self.run_model(
			result.monomerUsages, 'counts')

		# Reconcile disagreements between the kinetics-based trna
		# charging model and sequence-based elongation model
		disagreements = codons_read - result.monomerUsages
		self.process.writeToListener(
			'TrnaCharging', 'initial_disagreements', disagreements)

		if not np.all(result.monomerUsages == codons_read):
			free_trnas_copy = copy.deepcopy(free_trnas)
			charged_trnas_copy = copy.deepcopy(charged_trnas)
			codons_read_copy = copy.deepcopy(codons_read)

			# Reconcile using ribosome positions
			# EXT-PORT-12 (UNIFY-2 gate): the kernels used to seed the C stdlib RNG from the wall
			# clock, which made every kinetic run non-reproducible (see _trna_charging.pyx). The
			# seed now comes from this process's RandomState, which simulation.py seeds from
			# --seed. Draw ONE value per kernel call, unconditionally within this branch, so the
			# number of draws is a function of the model state and not of wall-clock timing.
			reconcile_via_ribosome_positions(
				result.monomerUsages,
				result.sequenceElongation,
				codons_read,
				self.longer_sequences,
				self.max_attempts,
				self._reconcile_seed(),
				)

			# Reconcile remaining disagreements (if any) using tRNA pools
			if not np.all(result.monomerUsages == codons_read):
				result_copy2 = copy.deepcopy(result)

				reconcile_via_trna_pools(
					result.monomerUsages,
					codons_read,
					free_trnas,
					charged_trnas,
					chargings,
					amino_acids_used,
					codons_to_trnas_matrix,
					self.trnas_to_codons,
					self.trnas_to_amino_acid_indexes,
					self._reconcile_seed(),
					)

			net_charged = charged_trnas - self.charged_trnas.counts()
			result.nReactions = result.monomerUsages.sum()

		# Record the number of charging and reading events
		self.process.writeToListener('TrnaCharging', 'charging_events',
			chargings)
		self.process.writeToListener('TrnaCharging', 'reading_events',
			codons_to_trnas_matrix.sum(axis=1))
		self.process.writeToListener('TrnaCharging', 'codons_to_trnas_counter',
			codons_to_trnas_matrix[self.codons_to_trnas])

		# Calculate net change of charged trnas
		net_charged = charged_trnas - self.charged_trnas.counts()

		return result, amino_acids_used, net_charged

	def sequences(self, sequences):
		return self.longer_sequences

	def protein_maturation(self, did_terminate, terminated_proteins,
			protein_indexes):

		# Terminated proteins requiring methionine cleavage
		n_needs_cleaving = terminated_proteins[self.is_map_substrate].sum()

		# Kinetic capacity of methionine aminopeptidase
		cell_volume = self.cell_mass / self.cell_density
		v_can_cleave = (1
			/ units.s * 6 # k_cat
			/ self.n_avogadro
			/ cell_volume
			* self.map.count()
			)
		n_can_cleave = (v_can_cleave
			* (units.s * self.process.timeStepSec())
			* cell_volume
			* self.n_avogadro
			).asNumber()
		n_can_cleave = stochasticRound(
			self.process.randomState, n_can_cleave)[0]

		# Mature proteins
		if n_can_cleave >= n_needs_cleaving:
			cleaved = n_needs_cleaving
			not_cleaved = 0

		# Determine proteins that cannot terminate in this step
		else:
			cleaved = n_can_cleave
			not_cleaved = n_needs_cleaving - n_can_cleave

			# Randomly select proteins that cannot terminate in this step
			candidates = np.logical_and(
				did_terminate,
				[self.is_map_substrate[x] for x in protein_indexes])
			# EXT-PORT-12 (UNIFY-2 gate): self.process.randomState, not np.random. v3.0.1 draws from
			# the UNSEEDED global numpy generator here (its line 1957), which is a second source of
			# irreproducibility independent of the srand defect in _trna_charging.pyx. MEASURED, one
			# generation on both paths plus a kinetic replicate: TrnaCharging/not_cleaved is
			# identically zero on all 2529 steps, so this branch never fired and it was NOT the cause
			# of the observed run-to-run divergence -- it is latent, and becomes live under
			# methionine-aminopeptidase limitation or any variant that lowers EG10570-MONOMER, which
			# is exactly the starvation regime the parity experiment is aimed at.
			i_cannot_cleave = self.process.randomState.multinomial(
				not_cleaved,
				candidates / candidates.sum()).astype(bool)

			# Remove these proteins from termination
			did_terminate[i_cannot_cleave] = False
			# self.process.n_proteins, not self.process.proteinSequences.shape[0]: the host
			# _evolveState_codon_aware builds the pre-maturation bincount with minlength=n_proteins
			# (line ~715), and rebinding terminated_proteins here at a different width would
			# silently change the length of a listener column mid-step. Measured equal today
			# (translation_sequences.shape == (4309, 2370), len(monomer_data['id']) == 4309); pinned
			# to one expression so they cannot drift apart.
			terminated_proteins = np.bincount(
				protein_indexes[did_terminate],
				minlength = self.process.n_proteins
				)

		# Record
		self.process.writeToListener('TrnaCharging', 'cleaved', cleaved)
		self.process.writeToListener('TrnaCharging', 'not_cleaved', not_cleaved)

		return did_terminate, terminated_proteins, cleaved

	def evolve(self, total_aa_counts, amino_acids_used,
			next_amino_acid_count, n_elongations, n_initialized,
			net_charged, monomerUsages, initial_methionines_cleaved):

		# Initialization
		self.water.countDec(n_initialized)

		# Net changes in trnas
		self.free_trnas.countsDec(net_charged)
		self.charged_trnas.countsInc(net_charged)

		# Amino acids used
		self.amino_acids.countsDec(amino_acids_used)

		# Each net (not absolute) charging event uses an ATP molecule
		atp_used = np.maximum(net_charged, 0).sum()
		self.atp.countDec(atp_used)
		self.amp.countInc(atp_used)
		self.ppi.countInc(atp_used)

		# Each net (not aboslute) amino acid residue that is
		# incorporated by a charged trna releases a proton molecule
		residues_incorporated = abs(np.minimum(net_charged, 0)).sum()
		self.proton.countInc(residues_incorporated)

		# The remaining elongation events are modeled as direct
		# incorporations from amino acid pools, which produce a water
		# molecule per elongation
		self.water.countInc(n_elongations - residues_incorporated)

		# Initial methionine cleavage for protein maturation
		self.water.countDec(initial_methionines_cleaved)
		self.met.countInc(initial_methionines_cleaved)

		# EXT-PORT-12 (UNIFY-2 gate): supply aa_count_diff, which this method used to return as `{}`.
		#
		# Metabolism.update_amino_acid_targets reads this dict off the process every step
		# (metabolism.py:265) to move the amino-acid homeostatic targets by supply-minus-charging-use.
		# It is now reached on this path too, because Metabolism.use_trna_charging is gated on
		# _explicit_trna_charging. Returning `{}` there would NOT raise -- the update loop simply
		# iterates nothing and the targets freeze at their first-timestep counts, which is a THIRD
		# law, neither the steady-state one nor the old one. That is the silent-absence failure class,
		# so the quantity is computed rather than defaulted.
		#
		# SAME QUANTITY as the steady-state model, verified against its line 1215-1216
		# (`aa_used_trna = aa_from_trna @ total_charging_reactions; aa_diff = aa_supply -
		# aa_used_trna`): both subtract the amino acids consumed by CHARGING this step from
		# self.process.aa_supply. Here `amino_acids_used` is already that 21-vector in amino-acid
		# space -- it is the array countsDec'd off self.amino_acids nine lines above -- so no
		# projection is needed.
		#
		# DECLARED DIFFERENCE, not eliminated here: the SUPPLY term differs. On the steady-state path
		# self.process.aa_supply is overwritten inside request() by the mechanistic synthesis/import/
		# export calculation (line 1053) when mechanistic_translation_supply is on; this model
		# implements none of that, so aa_supply stays the translation-supply-rate estimate the host
		# computed at _calculateRequest_codon_aware (line ~550). The LAW is now the same on both
		# paths; the supply input to it is not. That belongs to the mechanistic_translation_supply
		# confound already declared in PolypeptideElongation.initialize, not to this line.
		aa_count_diff = self.process.aa_supply - amino_acids_used
		return net_charged, {
			aa: diff for aa, diff in zip(self.process.aaNames, aa_count_diff)}


class CoarseKineticTrnaChargingModel(TranslationSupplyElongationModel):
	"""
	Coarse Kinetic Model: Elongate polypeptides according to the kinetic
	limits described by:
	1) the max measured kcat of tRNA synthetases, or if unavailable
	2) the max velocity (vmax).
	"""
	def __init__(self, sim_data, process):
		super(TranslationSupplyElongationModel, self).__init__(sim_data, process)

		# Describe constants
		self.cell_density = sim_data.constants.cell_density
		self.n_avogadro = sim_data.constants.n_avogadro

		# Describe molecules
		amino_acid_to_synthetase = sim_data.relation.amino_acid_to_synthetase
		synthetases = []
		for amino_acid in sim_data.molecule_groups.amino_acids:
			synthetases.append(amino_acid_to_synthetase[amino_acid])
		self.synthetases = self.process.bulkMoleculesView(synthetases)

		# Describe kcats
		k_cats_dict = sim_data.relation.synthetase_to_max_curated_k_cats
		k_cats = []
		curated = []
		for synthetase in synthetases:
			if synthetase in k_cats_dict:
				k_cats.append(k_cats_dict[synthetase].asNumber(1/units.s))
				curated.append(True)
			else:
				k_cats.append(0)
				curated.append(False)

		self.k_cats = (1
			/ units.s
			* np.array(k_cats)
			)
		self.not_curated = np.logical_not(curated)

		# EXT-PORT-8: the codon-aware surface v3.0.1 keeps on BaseElongationModel. It cannot go
		# there in this tree: our BaseElongationModel still has to carry the steady-state
		# 0-arg elongation_rate / 1-arg request / 5-arg evolve that the unchanged
		# calculateRequest and evolveState call. KineticTrnaChargingModel defines all of this
		# itself; this class defined only __init__ and monomer_limit, so without the block below
		# --coarse-kinetic-elongation TypeErrors on its first step.
		#
		# The semantics are v3.0.1's Base verbatim, i.e. the identity/no-op set: for this model a
		# monomer IS an amino acid.
		translation = sim_data.process.translation
		self.protein_sequences = translation.translation_sequences
		self.monomer_weights_incorporated = translation.translation_monomer_weights
		self.n_monomers = len(sim_data.molecule_groups.amino_acids)
		# 86 entries. GrowthLimits.fraction_trna_charged and net_charged are both allocated at
		# len(uncharged_trna_names) (growth_limits.py:60-62); our Base's steady-state
		# np.zeros(len(self.aaNames)) is 21 and would be written into an 86-wide column.
		self.zero_charged_holder = np.zeros(len(self.uncharged_trna_names))

	def record_mass(self):
		return

	def elongation_rate(self, current_media_id, protein_indexes, peptide_lengths):
		"""
		EXT-PORT-8: the 3-arg convention the codon-aware host uses. Same value as the inherited
		0-arg TranslationSupplyElongationModel.elongation_rate, which stays where it is for the
		steady-state host.
		"""
		return self.basal_elongation_rate

	def request(self, monomers_in_sequences, protein_indexes, current_media_id,
			peptide_lengths):
		"""
		EXT-PORT-8: the 4-arg convention. amino_acid_counts resolves to
		TranslationSupplyElongationModel's np.fmin(process.aa_supply, ...), which is why
		_calculateRequest_codon_aware still has to compute self.aa_supply.
		"""
		aa_request = self.amino_acid_counts(monomers_in_sequences)

		self.process.aas.requestIs(aa_request)

		# Not modeling charging so set fraction charged to 0 for all tRNA
		return self.zero_charged_holder, aa_request

	def monomer_to_aa(self, monomer):
		return monomer

	def next_amino_acids(self, all_sequences, sequence_elongations):
		"""EXT-PORT-10: amino-acid space here, so this is v3.0.1's SteadyStateElongationModel body
		verbatim. This model's protein_sequences are translation_sequences, not codon_sequences, and
		its reconcile() is a pass-through, so sequence_elongations stays within all_sequences.

		Ported for the same reason as the kinetic override: inheriting BaseElongationModel's 0 is a
		silent wrong answer waiting for ppGpp to be wired into a codon-aware path.
		"""
		next_amino_acid = all_sequences[
			np.arange(len(sequence_elongations)), sequence_elongations]
		return np.bincount(
			next_amino_acid[next_amino_acid != polymerize.PAD_VALUE], minlength=21)

	def codon_sequences_width(self, elongation_rates):
		return elongation_rates

	def reconcile(self, result):
		aas_used = result.monomerUsages
		return result, aas_used, []

	def sequences(self, sequences):
		return sequences

	def protein_maturation(self, did_terminate, terminated_proteins, protein_indexes):
		return did_terminate, terminated_proteins, 0

	def evolve(self, total_aa_counts, aas_used, next_amino_acid_count,
			nElongations, nInitialized, trna_changes, monomerUsages,
			initial_methionines_cleaved):
		"""EXT-PORT-8: the 8-arg convention, v3.0.1 BaseElongationModel.evolve verbatim."""
		# Update counts of amino acids and water to reflect polymerization reactions
		self.process.aas.countsDec(aas_used)
		self.water.countInc(nElongations - nInitialized)

		return self.zero_charged_holder, {}

	# next_amino_acids (returns 0) and protein_lengths are already provided by our
	# BaseElongationModel, so they are not repeated here.

	def monomer_limit(self, allocated_aas, monomer_count_in_sequence):
		# Calculate maximum velocity
		cell_mass = units.fg * self.process.readFromListener('Mass', 'cellMass')
		cell_volume = cell_mass / self.cell_density
		c_synthetases = (1
			/ self.n_avogadro
			/ cell_volume
			* self.synthetases.total()
			)
		v_max = self.k_cats * c_synthetases
		n_max = (v_max
			* (units.s * self.process.timeStepSec())
			* cell_volume
			* self.n_avogadro
			).asNumber()
		n_max = stochasticRound(self.process.randomState, n_max)

		# Limit monomer availability by maximum velocity
		kinetics_limited_aas = np.minimum(allocated_aas, n_max)

		# Monomers without curated data are not limited
		kinetics_limited_aas[self.not_curated] = allocated_aas[self.not_curated]

		return kinetics_limited_aas, kinetics_limited_aas
