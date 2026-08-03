"""
GrowthLimits
"""

import numpy as np

import wholecell.listeners.listener

# from numpy.lib.recfunctions import merge_arrays

VERBOSE = False

class GrowthLimits(wholecell.listeners.listener.Listener):
	""" GrowthLimits """

	_name = 'GrowthLimits'

	# Constructor
	def __init__(self, *args, **kwargs):
		super(GrowthLimits, self).__init__(*args, **kwargs)


	# Construct object graph
	def initialize(self, sim, sim_data):
		super(GrowthLimits, self).initialize(sim, sim_data)

		# Computed, saved attributes
		self.aaIds = sim_data.molecule_groups.amino_acids
		self.ntpIds = sim_data.molecule_groups.ntps
		self.uncharged_trna_ids = sim_data.process.transcription.uncharged_trna_names
		self.charged_trna_ids = sim_data.process.transcription.charged_trna_names
		self.aa_importer_names = list(sim_data.process.metabolism.aa_importer_names)
		self.aa_exporter_names = list(sim_data.process.metabolism.aa_exporter_names)

		# EXT-PORT-12 (UNIFY-2 gate): record which of this listener's columns NO PROCESS in this run
		# is capable of writing. A zero in an unwritten column is absence, not measurement, and the
		# difference is invisible in the output -- which is the failure class this whole gate exists
		# to close. Measured, one generation on each path, same seed: 27 GrowthLimits columns logged
		# their allocate()-time zeros on the kinetic path and non-zero values on the steady-state
		# path, and every one of them is written inside SteadyStateElongationModel and nowhere else
		# (polypeptide_elongation.py lines ~1025-1220).
		#
		# The list is derived from the resolved simulation flags, not hard-coded, so it stays true
		# when the parity model starts writing the ppGpp channel.
		ppgpp_driven = bool(getattr(sim, '_ppgpp_driven_by_elongation', False))
		steady_state = bool(getattr(sim, '_trna_charging', False))
		unwritten = []
		if not steady_state:
			unwritten += [
				'synthetase_conc', 'uncharged_trna_conc', 'charged_trna_conc', 'aa_conc',
				'ribosome_conc', 'fraction_aa_to_elongate', 'original_aa_supply', 'aa_in_media',
				'aa_supply', 'aa_synthesis', 'aa_import', 'aa_export',
				'aa_supply_enzymes_fwd', 'aa_supply_enzymes_rev', 'aa_importers', 'aa_exporters',
				'aa_supply_aa_conc', 'aa_supply_fraction_fwd', 'aa_supply_fraction_rev',
				'trnaCharged',
				]
		if not ppgpp_driven:
			# The ppGpp diagnostic channel. On a kinetic run today these are zeros because nothing
			# synthesises or degrades ppGpp -- NOT because ppGpp activity was measured and found to
			# be zero. The real pool has to be read from BulkMolecules/counts instead. This is the
			# instrumentation the parity model must start writing, or the target experiment produces
			# a ppGpp response with no way to see it.
			unwritten += [
				'ppgpp_conc', 'rela_conc', 'spot_conc',
				'rela_syn', 'spot_syn', 'spot_deg', 'spot_deg_inhibited',
				]
		self._unwritten_columns = sorted(unwritten)

	# Allocate memory
	def allocate(self):
		super(GrowthLimits, self).allocate()

		n_aa = len(self.aaIds)
		n_importers = len(self.aa_importer_names)
		n_exporters = len(self.aa_exporter_names)

		# For translation
		self.activeRibosomeAllocated = 0

		self.aaPoolSize = np.zeros(n_aa, np.float64)
		self.aaRequestSize = np.zeros(n_aa, np.float64)
		self.aaAllocated = np.zeros(n_aa, np.float64)
		self.aasUsed = np.zeros(n_aa, np.float64)

		# For charging function
		self.synthetase_conc = np.zeros(n_aa, np.float64)
		self.uncharged_trna_conc = np.zeros(n_aa, np.float64)
		self.charged_trna_conc = np.zeros(n_aa, np.float64)
		self.aa_conc = np.zeros(n_aa, np.float64)
		self.ribosome_conc = 0.
		self.fraction_aa_to_elongate = np.zeros(n_aa, np.float64)

		# Charging results
		n_uncharged_trna = len(self.uncharged_trna_ids)
		self.fraction_trna_charged = np.zeros(n_uncharged_trna, np.float64)
		self.net_charged = np.zeros(n_uncharged_trna, int)

		# For transcription
		n_ntp = len(self.ntpIds)
		self.ntpPoolSize = np.zeros(n_ntp, np.float64)
		self.ntpRequestSize = np.zeros(n_ntp, np.float64)
		self.ntpAllocated = np.zeros(n_ntp, np.float64)
		self.ntpUsed = np.zeros(n_ntp, np.float64)

		self.ppgpp_conc = 0.
		self.rela_conc = 0.
		self.spot_conc = 0.
		self.rela_syn = np.zeros(n_aa)
		self.spot_deg_inhibited = np.zeros(n_aa)
		self.spot_deg = 0.
		self.spot_syn = 0.

		self.original_aa_supply = np.zeros(n_aa, np.float64)
		self.aa_supply = np.zeros(n_aa, np.float64)
		self.aa_synthesis = np.zeros(n_aa, np.float64)
		self.aa_import = np.zeros(n_aa, np.float64)
		self.aa_export = np.zeros(n_aa, np.float64)
		self.aa_supply_enzymes_fwd = np.zeros(n_aa, int)
		self.aa_supply_enzymes_rev = np.zeros(n_aa, int)
		self.aa_importers = np.zeros(n_importers, int)
		self.aa_exporters = np.zeros(n_exporters, int)
		self.aa_supply_aa_conc = np.zeros(n_aa, np.float64)
		self.aa_supply_fraction_fwd = np.zeros(n_aa, np.float64)
		self.aa_supply_fraction_rev = np.zeros(n_aa, np.float64)
		self.aa_in_media = np.zeros(n_aa, bool)

		self.aaCountDiff = np.zeros(n_aa, np.float64)
		self.trnaCharged = np.zeros(n_aa, np.float64)

	def update(self):
		pass

	def tableCreate(self, tableWriter):
		subcolumns = {
			'aaPoolSize': 'aaIds',
			'aaRequestSize': 'aaIds',
			'aaAllocated': 'aaIds',
			'aasUsed': 'aaIds',
			'synthetase_conc': 'aaIds',
			'uncharged_trna_conc': 'aaIds',
			'charged_trna_conc': 'aaIds',
			'aa_conc': 'aaIds',
			'fraction_aa_to_elongate': 'aaIds',
			'fraction_trna_charged': 'uncharged_trna_ids',
			'net_charged': 'uncharged_trna_ids',
			'ntpPoolSize': 'ntpIds',
			'ntpRequestSize': 'ntpIds',
			'ntpAllocated': 'ntpIds',
			'ntpUsed': 'ntpIds',
			'rela_syn': 'aa_ids',
			'spot_deg_inhibited': 'aa_ids',
			'original_aa_supply': 'aaIds',
			'aa_supply': 'aaIds',
			'aa_synthesis': 'aaIds',
			'aa_import': 'aaIds',
			'aa_export': 'aaIds',
			'aa_supply_enzymes_fwd': 'aaIds',
			'aa_supply_enzymes_rev': 'aaIds',
			'aa_importers': 'aa_importer_names',
			'aa_exporters': 'aa_exporter_names',
			'aa_supply_aa_conc': 'aaIds',
			'aa_supply_fraction_fwd': 'aaIds',
			'aa_supply_fraction_rev': 'aaIds',
			'aa_in_media': 'aaIds',
			'trnaCharged':'aaIds',
			'aaCountDiff':'aaIds'
			}

		tableWriter.writeAttributes(
			aaIds = self.aaIds,
			uncharged_trna_ids = self.uncharged_trna_ids,
			ntpIds = self.ntpIds,
			subcolumns = subcolumns,
			aa_exporter_names = self.aa_exporter_names,
			# EXT-PORT-12 (UNIFY-2 gate): see initialize(). Columns listed here are allocated and
			# appended every step but never assigned by any process in THIS run; their zeros are
			# absence, not measurement.
			unwritten_columns = self._unwritten_columns,
			# EXT-PORT-12: a known provenance hazard in the WRITTEN columns, declared rather than
			# fixed. tableAppend below passes `original_aa_supply = self.aa_supply`, so the
			# original_aa_supply COLUMN is a duplicate of aa_supply and does NOT carry the value
			# PolypeptideElongation writes to the listener attribute of that name
			# (polypeptide_elongation.py:~1025). Traced to upstream commit 9bcaa873 'Turn amino acid
			# supply in charging into a function (#1158)' -- it is not introduced by the tRNA port
			# and it is symmetric across both elongation paths, so it does not affect the UNIFY-2
			# comparison. NOT fixed here because every row of the existing simulation corpus was
			# produced with this behaviour and silently changing a column's meaning mid-corpus is
			# worse than recording it. Fix it deliberately, with a corpus rebuild, or not at all.
			known_column_hazards = {
				'original_aa_supply': 'duplicates aa_supply; the listener attribute of this name is'
					' never appended (upstream 9bcaa873)',
				},
			)

	def tableAppend(self, tableWriter):
		tableWriter.append(
			time = self.time(),
			simulationStep = self.simulationStep(),
			activeRibosomeAllocated = self.activeRibosomeAllocated,
			aaPoolSize = self.aaPoolSize,
			aaRequestSize = self.aaRequestSize,
			aaAllocated = self.aaAllocated,
			aasUsed = self.aasUsed,
			synthetase_conc = self.synthetase_conc,
			uncharged_trna_conc = self.uncharged_trna_conc,
			charged_trna_conc = self.charged_trna_conc,
			aa_conc = self.aa_conc,
			ribosome_conc = self.ribosome_conc,
			fraction_aa_to_elongate = self.fraction_aa_to_elongate,
			fraction_trna_charged = self.fraction_trna_charged,
			net_charged = self.net_charged,
			ntpPoolSize = self.ntpPoolSize,
			ntpRequestSize = self.ntpRequestSize,
			ntpAllocated = self.ntpAllocated,
			ntpUsed = self.ntpUsed,
			ppgpp_conc = self.ppgpp_conc,
			rela_conc = self.rela_conc,
			spot_conc = self.spot_conc,
			rela_syn = self.rela_syn,
			spot_syn = self.spot_syn,
			spot_deg = self.spot_deg,
			spot_deg_inhibited = self.spot_deg_inhibited,
			original_aa_supply = self.aa_supply,
			aa_supply = self.aa_supply,
			aa_synthesis = self.aa_synthesis,
			aa_import = self.aa_import,
			aa_export = self.aa_export,
			aa_supply_enzymes_fwd = self.aa_supply_enzymes_fwd,
			aa_supply_enzymes_rev = self.aa_supply_enzymes_rev,
			aa_importers = self.aa_importers,
			aa_exporters = self.aa_exporters,
			aa_supply_aa_conc = self.aa_supply_aa_conc,
			aa_supply_fraction_fwd = self.aa_supply_fraction_fwd,
			aa_supply_fraction_rev = self.aa_supply_fraction_rev,
			aa_in_media = self.aa_in_media,
			aaCountDiff = self.aaCountDiff,
			trnaCharged = self.trnaCharged,
			)
