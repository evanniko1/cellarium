"""
TrnaCharging
"""

from __future__ import absolute_import, division, print_function

import numpy as np

import wholecell.listeners.listener
from wholecell.utils import units

class TrnaCharging(wholecell.listeners.listener.Listener):
	""" TrnaCharging """

	_name = 'TrnaCharging'

	# Constructor
	def __init__(self, *args, **kwargs):
		super(TrnaCharging, self).__init__(*args, **kwargs)


	# Construct object graph
	def initialize(self, sim, sim_data):
		super(TrnaCharging, self).initialize(sim, sim_data)

		# EXT-PORT-12 (UNIFY-2 gate): which of this listener's columns no process will write on THIS
		# run. Recorded per-run because it is path-dependent: every column below except the two
		# permanently-unwritten ones is produced by KineticTrnaChargingModel and by nothing else, so
		# on a steady-state run they log their allocate()-time zeros for the whole simulation. A
		# corpus consumer reading `cleaved == 0` cannot otherwise tell "no methionine cleavage
		# happened" from "no code in this run was capable of writing that column".
		self._kinetic_path = bool(getattr(sim, '_kinetic_trna_charging', False))

		# EXT-PORT-5: cistron space, not transcription-unit space — see the note in
		# polypeptide_elongation.py:KineticTrnaChargingModel.__init__. Sizing these columns from
		# rna_data gives 51 where the relation arrays are 86, so every logged column would be the
		# wrong width against data that is 86 wide.
		trnas = sim_data.process.transcription.uncharged_trna_names
		self.n_trnas = len(trnas)
		self.n_codons = len(sim_data.relation.codons)
		self.trna_codon_pairs = sim_data.relation.trna_codon_pairs
		self.n_trna_codon_pairs = len(self.trna_codon_pairs)
		self.n_amino_acids = len(sim_data.molecule_groups.amino_acids)


		# Arginine biosynthesis
		monomer_data = sim_data.process.translation.monomer_data
		argA_index = np.where(monomer_data['id'] == 'N-ACETYLTRANSFER-MONOMER[c]')[0][0]

		# add 1 to represent terminated ribosomes
		self.argA_listener_size = int(1 + monomer_data['length'][argA_index].asNumber(units.aa))

	# Allocate memory
	def allocate(self):
		super(TrnaCharging, self).allocate()

		self.charging_events = np.zeros(self.n_trnas, np.int64)
		self.cleaved = 0
		self.codons_read = np.zeros(self.n_codons, np.int64)
		self.codons_to_trnas_counter = np.zeros(self.n_trna_codon_pairs, np.int64)
		# EXT-PORT-10: NO WRITER EXISTS for collision_removed_ribosomes_argA or for
		# ribosome_initiation_argA anywhere in this tree -- grep both names and the only hits are the
		# three in this file. In v3.0.1 they are produced by machinery that was not part of the
		# EXT-PORT scope. They therefore log as their allocate()-time zeros on EVERY run, including
		# kinetic ones, and a zero here means 'never written', NOT 'no collisions occurred'.
		#
		# Documented rather than removed: this listener is registered unconditionally
		# (models/ecoli/sim/simulation.py:103), so dropping the columns would change the output schema
		# of every default-path run in the corpus as well. tableCreate writes the same statement into
		# the table's attributes so it reaches an analyst reading the output, not only a reader of
		# this file.
		self.collision_removed_ribosomes_argA = np.zeros(self.argA_listener_size, np.int64)
		self.initial_disagreements = np.zeros(self.n_codons)
		self.initiated = 0
		self.not_cleaved = 0
		self.reading_events = np.zeros(self.n_trnas, np.int64)
		self.ribosome_positions_argA = np.zeros(self.argA_listener_size, np.int64)
		self.ribosome_initiation_argA = np.array([], np.int64)

		self.saturation_trna = np.zeros(self.n_trnas)
		self.turnover = np.zeros(self.n_amino_acids)

		# EXT-PORT-12 (UNIFY-2 gate): instrumentation for the one term in the ppGpp input that
		# CANNOT be made identical between the two elongation paths.
		#
		# KineticTrnaChargingModel.next_amino_acids reads the next codon out of self.longer_sequences
		# and drops any ribosome whose next position falls outside that window
		# (`visible = sequence_elongations < sequences.shape[1]`). The drop is forced -- reconcile()
		# can return elongations wider than the amino-acid `all_sequences` array the steady-state
		# path indexes -- so the two next_amino_acid_count vectors cannot be made byte-identical.
		# next_amino_acid_count is a direct RelA input (it exists so that `f` is not NaN on a
		# zero-elongation step), so the size of the residual has to be a measured number rather than
		# an assumption. Before this column it had no listener at all.
		#
		# Written only by the kinetic path; it stays at these zeros on the steady-state path, where
		# there is no window to fall outside of. See unwritten_columns in tableCreate.
		self.next_aa_ribosomes_dropped = 0
		self.next_aa_ribosomes_total = 0

	def update(self):
		pass

	def tableCreate(self, tableWriter):
		tableWriter.writeAttributes(
			trna_codon_pairs = self.trna_codon_pairs,
			# EXT-PORT-10: columns that are allocated and appended but never written by any process in
			# this tree. Their zeros are absence, not measurement. Carried in the attributes so the
			# caveat travels with the output rather than living only in the source of the listener.
			# EXT-PORT-12 (UNIFY-2 gate): the list is now RUN-DEPENDENT. On a steady-state run every
			# column in this listener is unwritten, because they are all produced by
			# KineticTrnaChargingModel. Measured, one generation each: these nine logged as
			# allocate()-time zeros on the steady-state path and non-zero on the kinetic path --
			# charging_events, cleaved, codons_read, codons_to_trnas_counter,
			# initial_disagreements, initiated, reading_events, ribosome_positions_argA,
			# saturation_trna, turnover. Recording it here means the caveat travels with the output
			# instead of having to be re-derived from the source of whichever process was selected.
			unwritten_columns = [
				'collision_removed_ribosomes_argA',
				'ribosome_initiation_argA',
				] + ([] if self._kinetic_path else [
				'charging_events',
				'cleaved',
				'codons_read',
				'codons_to_trnas_counter',
				'initial_disagreements',
				'initiated',
				'next_aa_ribosomes_dropped',
				'next_aa_ribosomes_total',
				'not_cleaved',
				'reading_events',
				'ribosome_positions_argA',
				'saturation_trna',
				'turnover',
				]),
			)
		tableWriter.set_variable_length_columns(
			'ribosome_initiation_argA',
			)

	def tableAppend(self, tableWriter):
		tableWriter.append(
			next_aa_ribosomes_dropped = self.next_aa_ribosomes_dropped,
			next_aa_ribosomes_total = self.next_aa_ribosomes_total,
			charging_events = self.charging_events,
			cleaved = self.cleaved,
			codons_read = self.codons_read,
			codons_to_trnas_counter = self.codons_to_trnas_counter,
			collision_removed_ribosomes_argA = self.collision_removed_ribosomes_argA,
			initial_disagreements = self.initial_disagreements,
			initiated = self.initiated,
			not_cleaved = self.not_cleaved,
			reading_events = self.reading_events,
			ribosome_positions_argA = self.ribosome_positions_argA,
			ribosome_initiation_argA = self.ribosome_initiation_argA,
			saturation_trna = self.saturation_trna,
			turnover = self.turnover,
			)
