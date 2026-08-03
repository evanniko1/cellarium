"""
Simulation

"""

import binascii
import collections
import os.path
import shutil
from time import monotonic as monotonic_seconds
from typing import Callable, Sequence, Tuple
import uuid

import numpy as np

from wholecell.listeners.evaluation_time import EvaluationTime
from wholecell.utils import filepath

import wholecell.loggers.shell
import wholecell.loggers.disk

MAX_TIME_STEP = 1.


def resolve_elongation_flags(trna_charging, translation_supply,
		kinetic_trna_charging, coarse_kinetic_elongation, ppgpp_regulation):
	"""EXT-PORT-12 (UNIFY-2 gate): the ONE definition of what the elongation flags resolve to.

	Called from Simulation.__init__ (which applies the result to itself) and from
	runscripts/manual/runSim.py (which writes the result into metadata.json). Two call sites, one
	rule -- because the alternative, which is what the tree did before, is a metadata file that
	disagrees with the simulation it describes.

	MEASURED provenance defect this closes: runSim.py builds metadata.json from vars(args) BEFORE
	the Simulation constructor overrides the flags, so a --kinetic-trna-charging run recorded
	"trna_charging": true and "translation_supply": true while its own stdout said both were being
	forced False. Every corpus row from a kinetic run therefore asserted that steady-state charging
	was on. A parity study is a claim about what was held constant; the record has to be the
	resolved state, not the requested one.

	Returns a dict of the four resolved values. `explicit_trna_charging` and
	`ppgpp_driven_by_elongation` are DERIVED, not requestable: they are the two questions the single
	`trna_charging` flag used to be asked on top of "which elongation model", and they are what
	metabolism and initial_conditions actually want. See the block in __init__ for which is which.
	"""
	if kinetic_trna_charging or coarse_kinetic_elongation:
		trna_charging = False
		translation_supply = False
	# Mirrors the selection chain in PolypeptideElongation.initialize, in the same order. Recorded
	# by name because the flags alone do not identify the model unambiguously to a corpus reader:
	# a run can carry mechanistic_translation_supply=True and aa_supply_in_charging=True while the
	# selected model reads neither of them.
	if kinetic_trna_charging:
		elongation_model = 'KineticTrnaChargingModel'
	elif coarse_kinetic_elongation:
		elongation_model = 'CoarseKineticTrnaChargingModel'
	elif trna_charging:
		elongation_model = 'SteadyStateElongationModel'
	elif translation_supply:
		elongation_model = 'TranslationSupplyElongationModel'
	else:
		elongation_model = 'BaseElongationModel'
	return {
		'trna_charging': bool(trna_charging),
		'translation_supply': bool(translation_supply),
		'explicit_trna_charging': bool(trna_charging or kinetic_trna_charging),
		'ppgpp_driven_by_elongation': bool(ppgpp_regulation and trna_charging),
		'elongation_model': elongation_model,
		}


DEFAULT_SIMULATION_KWARGS = dict(
	timeline = '0 minimal',
	boundary_reactions = [],
	seed = 0,
	lengthSec = 3*60*60, # 3 hours max
	initialTime = 0.,
	generation_index= 0,
	jit = False,
	massDistribution = True,
	dPeriodDivision = True,
	translationSupply = True,
	trna_charging = True,
	# EXT-PORT-3: per-isoacceptor kinetic charging (v3.0.1). Default OFF — turning it on changes the
	# elongation model, so it is a different model, not a different setting of the same one.
	kinetic_trna_charging = False,
	coarse_kinetic_elongation = False,
	aa_supply_in_charging = True,
	ppgpp_regulation = True,
	disable_ppgpp_elongation_inhibition = False,
	superhelical_density = False,
	recycle_stalled_elongation = False,
	mechanistic_replisome = False,
	mechanistic_translation_supply = True,
	mechanistic_aa_transport = True,
	trna_attenuation = True,
	timeStepSafetyFraction = 1.3,
	maxTimeStep = MAX_TIME_STEP,
	updateTimeStepFreq = 5,
	adjust_timestep_for_charging = False,
	logToShell = True,
	logToDisk = False,
	outputDir = None,
	logToDiskEvery = 1,
	simData = None,
	inheritedStatePath = None,
	remove_rrna_operons = False,
	remove_rrff = False,
	stable_rrna = False,
	variable_elongation_transcription=True,
	variable_elongation_translation = False,
	raise_on_time_limit = False,
	to_report = {
		# Iterable of molecule names
		'bulk_molecules': (),
		'unique_molecules': (),
		# Tuples of (listener_name, listener_attribute) such that the
		# desired value is
		# self.listeners[listener_name].listener_attribute
		'listeners': (),
	},
	cell_id = None,
)
ALTERNATE_KWARG_NAMES = {
	"length_sec": "lengthSec",
	"timestep_safety_frac": "timeStepSafetyFraction",
	"timestep_max": "maxTimeStep",
	"timestep_update_freq": "updateTimeStepFreq",
	"log_to_shell": "logToShell",
	"log_to_disk_every": "logToDiskEvery",
	"mass_distribution": "massDistribution",
	"d_period_division": "dPeriodDivision",
	"translation_supply": "translationSupply",
	}

def _orderedAbstractionReference(iterableOfClasses):
	return collections.OrderedDict(
		(cls.name(), cls())
		for cls in iterableOfClasses
		)


class SimulationException(Exception):
	pass


DEFAULT_LISTENER_CLASSES = (
	EvaluationTime,
	)

class Simulation():
	""" Simulation """

	# Attributes that must be set by a subclass
	_definedBySubclass = (
		"_internalStateClasses",
		"_externalStateClasses",
		"_processClasses",
		"_initialConditionsFunction",
		)

	# Attributes that may be optionally overwritten by a subclass
	_listenerClasses = ()  # type: Tuple[Callable, ...]
	_hookClasses = ()  # type: Sequence[Callable]
	_shellColumnHeaders = ("Time (s)",)  # type: Sequence[str]

	# Constructors
	def __init__(self, **kwargs):
		# Validate subclassing
		for attrName in self._definedBySubclass:
			if not hasattr(self, attrName):
				raise SimulationException("Simulation subclasses must define"
				+ " the {} attribute.".format(attrName))

		for listenerClass in DEFAULT_LISTENER_CLASSES:
			if listenerClass in self._listenerClasses:
				raise SimulationException("The {} listener is included by"
					" default in the Simulation class.".format(
					listenerClass.name()))

		# Set instance attributes
		for attrName, value in DEFAULT_SIMULATION_KWARGS.items():
			if attrName in kwargs:
				value = kwargs[attrName]

			setattr(self, "_" + attrName, value)

		# EXT-PORT-8: the elongation flags are MUTUALLY EXCLUSIVE, and saying so here rather than leaving
		# them independent closes a whole class of silent inconsistency. v3.0.1 resolves them exactly this
		# way (wholecell/sim/simulation.py:164-180 there): selecting the kinetic model sets
		# _steady_state_trna_charging and _translationSupply False in the same breath.
		#
		# It matters beyond the elongation process, which is why it belongs here and not in
		# PolypeptideElongation.initialize. `trna_charging` is read elsewhere in the model -- with it left
		# True alongside a kinetic model, metabolism keeps holding amino acid targets that nothing is
		# updating any more. Nothing raises; the numbers are just wrong.
		if self._kinetic_trna_charging or self._coarse_kinetic_elongation:
			if self._trna_charging or self._translationSupply:
				print('EXT-PORT-8: a kinetic elongation model was selected, so trna_charging and'
					' translation_supply are being forced False (they are alternative elongation'
					' models, not modifiers).')

		# EXT-PORT-12 (UNIFY-2 gate): ONE flag was being asked TWO questions, and the answers differ.
		#
		#   "which elongation model?"          -> self._trna_charging. Mutually exclusive with
		#                                         _kinetic_trna_charging, forced False just above.
		#   "is explicit tRNA charging         -> TRUE for the steady-state model AND for
		#    modelled at all?"                    KineticTrnaChargingModel. Both consume amino acids
		#                                         into charged tRNA; both need the cell to START with
		#                                         a charged pool and both need metabolism to track
		#                                         amino-acid targets against charging use.
		#   "is ppGpp being synthesised and    -> TRUE only where an elongation model actually runs
		#    degraded by an elongation model?"    the RelA/SpoT reactions. Today that is the
		#                                         steady-state model alone; the parity model will
		#                                         make it true for the kinetic model too, and this
		#                                         is the ONE line that changes when it does.
		#
		# Conflating the second question with the first is what produced the two measured defects the
		# UNIFY-2 gate was opened for: initialize_trna_charging skipped, so the kinetic cell opened
		# with 0 charged tRNA against the steady-state cell's 140,590; and metabolism dropping the 20
		# amino-acid concentration targets (conc_update_molecules 52 -> 32) for a model that is
		# consuming those amino acids every step.
		#
		# The THIRD question is separate on purpose. Naming it after "explicit charging" would flip
		# include_ppgpp to False for today's kinetic model, which synthesises no ppGpp at all -- the
		# pool would then be neither regulated NOR pinned, which is worse than either. Kept exact and
		# behaviour-preserving here: `not ppgpp_regulation or not trna_charging` is what
		# metabolism.py computed before this block existed.
		#
		# CoarseKineticTrnaChargingModel is deliberately NOT explicit charging: it subclasses
		# TranslationSupplyElongationModel and models no charging reactions.
		#
		# The forcing of _trna_charging / _translationSupply moved INTO resolve_elongation_flags so
		# that runSim.py's metadata writer applies the identical rule rather than a copy of it.
		resolved = resolve_elongation_flags(
			self._trna_charging, self._translationSupply, self._kinetic_trna_charging,
			self._coarse_kinetic_elongation, self._ppgpp_regulation)
		self._trna_charging = resolved['trna_charging']
		self._translationSupply = resolved['translation_supply']
		self._explicit_trna_charging = resolved['explicit_trna_charging']
		self._ppgpp_driven_by_elongation = resolved['ppgpp_driven_by_elongation']

		unknownKeywords = kwargs.keys() - DEFAULT_SIMULATION_KWARGS.keys()

		if any(unknownKeywords):
			print("Unknown keyword arguments: {}".format(unknownKeywords))

		# Set time variables
		self._timeStepSec = min(MAX_TIME_STEP, self._maxTimeStep)
		self._simulationStep = 0
		self.daughter_paths = []

		self.randomState = np.random.RandomState(seed = np.uint32(self._seed % np.iinfo(np.uint32).max))

		# Start with an empty output dir -- mixing in new output files would
		# make a mess. Also, TableWriter refuses to overwrite a Table, and
		# divide_cell will fail if _outputDir is no good (e.g. defaulted to
		# None) so catch it *before* running the simulation in case _logToDisk
		# doesn't.
		if os.path.isdir(self._outputDir):
			shutil.rmtree(self._outputDir, ignore_errors=True)
		filepath.makedirs(self._outputDir)

		sim_data = self._simData

		# Initialize simulation from fit KB
		self._initialize(sim_data)


	# Link states and processes
	def _initialize(self, sim_data):
		# Combine all levels of processes
		all_processes = set()
		for processes in self._processClasses:
			all_processes.update(processes)

		self.internal_states = _orderedAbstractionReference(self._internalStateClasses)
		self.external_states = _orderedAbstractionReference(self._externalStateClasses)
		self.processes = _orderedAbstractionReference(sorted(all_processes, key=lambda cls: cls.name()))

		self.listeners = _orderedAbstractionReference(self._listenerClasses + DEFAULT_LISTENER_CLASSES)
		self.hooks = _orderedAbstractionReference(self._hookClasses)
		self._initLoggers()
		self._cellCycleComplete = False
		self._isDead = False
		self._finalized = False

		for state_name, internal_state in self.internal_states.items():
			# initialize random streams
			internal_state.seed = self._seedFromName(state_name)
			internal_state.randomState = np.random.RandomState(seed=internal_state.seed)

			internal_state.initialize(self, sim_data)

		for external_state in self.external_states.values():
			external_state.initialize(self, sim_data, self._timeline)

		for hook in self.hooks.values():
			hook.initialize(self, sim_data)

		for internal_state in self.internal_states.values():
			internal_state.allocate()

		self._initialConditionsFunction(sim_data)

		for process_name, process in self.processes.items():
			# initialize random streams
			process.seed = self._seedFromName(process_name)
			process.randomState = np.random.RandomState(seed=process.seed)

			process.initialize(self, sim_data)

		for listener in self.listeners.values():
			listener.initialize(self, sim_data)

		for listener in self.listeners.values():
			listener.allocate()

		self._timeTotal = self.initialTime()

		for hook in self.hooks.values():
			hook.postCalcInitialConditions(self)

		# Make permanent reference to evaluation time listener
		self._eval_time = self.listeners["EvaluationTime"]

		# Perform initial mass calculations
		for state in self.internal_states.values():
			state.calculateMass()

		# Update environment state according to the current time in time series
		for external_state in self.external_states.values():
			external_state.update()

		# Perform initial listener update
		for listener in self.listeners.values():
			listener.initialUpdate()

		# Start logging
		for logger in self.loggers.values():
			logger.initialize(self)

	def _initLoggers(self):
		self.loggers = collections.OrderedDict()

		if self._logToShell:
			self.loggers["Shell"] = wholecell.loggers.shell.Shell(
				self._shellColumnHeaders,
				self._outputDir if self._logToDisk else None,
				)

		if self._logToDisk:
			self.loggers["Disk"] = wholecell.loggers.disk.Disk(
				self._outputDir,
				logEvery=self._logToDiskEvery,
				)

	# Run simulation
	def run(self):
		"""
		Run the simulation for the time period specified in `self._lengthSec`
		and then clean up.
		"""
		try:
			self.run_incremental(self._lengthSec + self.initialTime())
			if not self._raise_on_time_limit:
				self.cellCycleComplete()
		finally:
			self.finalize()

		if self._raise_on_time_limit and not self._cellCycleComplete:
			raise SimulationException('Simulation time limit reached without cell division')

	def run_incremental(self, run_until):
		"""
		Run the simulation for a given amount of time.

		Args:
		    run_until (float): absolute time to run the simulation until.
		"""

		# Simulate
		while self.time() < run_until and not self._isDead:
			if self.time() > self.initialTime() + self._lengthSec:
				self.cellCycleComplete()

			if self._cellCycleComplete:
				self.finalize()
				break

			self._simulationStep += 1

			self._timeTotal += self._timeStepSec

			self._pre_evolve_state()
			for processes in self._processClasses:
				self._evolveState(processes)
			self._post_evolve_state()

	def run_for(self, run_for):
		self.run_incremental(self.time() + run_for)

	def finalize(self):
		"""
		Clean up any details once the simulation has finished.
		Specifically, this calls `finalize` in all hooks,
		invokes the simulation's `_divideCellFunction` if the
		cell cycle has completed and then shuts down all loggers.
		"""

		if not self._finalized:
			# Run post-simulation hooks
			for hook in self.hooks.values():
				hook.finalize(self)

			# Divide mother into daughter cells
			if self._cellCycleComplete:
				self.daughter_paths = self._divideCellFunction()

			# Finish logging
			for logger in self.loggers.values():
				logger.finalize(self)

			self._finalized = True

	def _pre_evolve_state(self):
		self._adjustTimeStep()

		# Run pre-evolveState hooks
		for hook in self.hooks.values():
			hook.preEvolveState(self)

		# Reset process mass difference arrays
		for state in self.internal_states.values():
			state.reset_process_mass_diffs()

		# Reset values in evaluationTime listener
		self._eval_time.reset_evaluation_times()

	# Calculate temporal evolution
	def _evolveState(self, processes):
		# Update queries
		# TODO: context manager/function calls for this logic?
		for i, state in enumerate(self.internal_states.values()):
			t = monotonic_seconds()
			state.updateQueries()
			self._eval_time.update_queries_times[i] += monotonic_seconds() - t

		# Calculate requests
		for i, process in enumerate(self.processes.values()):
			if process.__class__ in processes:
				t = monotonic_seconds()
				process.calculateRequest()
				self._eval_time.calculate_request_times[i] += monotonic_seconds() - t

		# Partition states among processes
		for i, state in enumerate(self.internal_states.values()):
			t = monotonic_seconds()
			state.partition(processes)
			self._eval_time.partition_times[i] += monotonic_seconds() - t

		# Simulate submodels
		for i, process in enumerate(self.processes.values()):
			if process.__class__ in processes:
				t = monotonic_seconds()
				process.evolveState()
				self._eval_time.evolve_state_times[i] += monotonic_seconds() - t

		# Check that timestep length was short enough
		for process_name, process in self.processes.items():
			if process_name in processes and not process.wasTimeStepShortEnough():
				raise Exception("The timestep (%.3f) was too long at step %i, failed on process %s" % (self._timeStepSec, self.simulationStep(), str(process.name())))

		# Merge state
		for i, state in enumerate(self.internal_states.values()):
			t = monotonic_seconds()
			state.merge(processes)
			self._eval_time.merge_times[i] += monotonic_seconds() - t

		# update environment state
		for state in self.external_states.values():
			state.update()

	def _post_evolve_state(self):
		# Calculate mass of all molecules after evolution
		for i, state in enumerate(self.internal_states.values()):
			t = monotonic_seconds()
			state.calculateMass()
			self._eval_time.calculate_mass_times[i] = monotonic_seconds() - t

		# Update listeners
		for i, listener in enumerate(self.listeners.values()):
			t = monotonic_seconds()
			listener.update()
			self._eval_time.update_times[i] = monotonic_seconds() - t

		# Run post-evolveState hooks
		for hook in self.hooks.values():
			hook.postEvolveState(self)

		# Append loggers
		for i, logger in enumerate(self.loggers.values()):
			t = monotonic_seconds()
			logger.append(self)
			# Note: these values are written at the next timestep
			self._eval_time.append_times[i] = monotonic_seconds() - t


	def _seedFromName(self, name):
		return binascii.crc32(name.encode('utf-8'), self._seed) & 0xffffffff


	def initialTime(self):
		return self._initialTime


	# Save to disk
	def tableCreate(self, tableWriter):
		tableWriter.writeAttributes(
			states = list(self.internal_states.keys()),
			processes = list(self.processes.keys())
			)


	def tableAppend(self, tableWriter):
		tableWriter.append(
			time = self.time(),
			timeStepSec = self.timeStepSec()
			)


	def time(self):
		return self._timeTotal


	def simulationStep(self):
		return self._simulationStep


	def timeStepSec(self):
		return self._timeStepSec


	def lengthSec(self):
		return self._lengthSec


	def cellCycleComplete(self):
		self._cellCycleComplete = True


	def get_sim_data(self):
		return self._simData


	def _adjustTimeStep(self):
		# Adjust timestep if needed or at a frequency of updateTimeStepFreq regardless
		validTimeSteps = self._maxTimeStep * np.ones(len(self.processes))
		resetTimeStep = False
		for i, process in enumerate(self.processes.values()):
			if not process.isTimeStepShortEnough(self._timeStepSec, self._timeStepSafetyFraction) or self.simulationStep() % self._updateTimeStepFreq == 0:
				validTimeSteps[i] = self._findTimeStep(0., self._maxTimeStep, process.isTimeStepShortEnough)
				resetTimeStep = True
		if resetTimeStep:
			self._timeStepSec = validTimeSteps.min()

	def _findTimeStep(self, minTimeStep, maxTimeStep, checkerFunction):
		N = 10000
		candidateTimeStep = maxTimeStep
		for i in range(N):
			if checkerFunction(candidateTimeStep, self._timeStepSafetyFraction):
				minTimeStep = candidateTimeStep
				if (maxTimeStep - minTimeStep) / minTimeStep <= 1e-2:
					break
			else:
				if minTimeStep > 0 and (maxTimeStep - minTimeStep) / minTimeStep <= 1e-2:
					candidateTimeStep = minTimeStep
					break
				maxTimeStep = candidateTimeStep
			candidateTimeStep = minTimeStep + (maxTimeStep - minTimeStep) / 2.
		else:
			raise SimulationException("Timestep adjustment did not converge,"
				" last attempt was %f" % (candidateTimeStep,))

		return candidateTimeStep


	## Additional CellSimulation methods for embedding in an Agent

	def apply_outer_update(self, update):
		# concentrations are received as a dict
		self.external_states['Environment'].set_local_environment(update)

	def daughter_config(self):
		config = {
			'start_time': self.time(),
			'volume': self.listeners['Mass'].volume * 0.5}

		daughters = []
		for i, path in enumerate(self.daughter_paths):
			# This uses primes to calculate seeds that diverge from small
			# initial seeds and further in later generations. Like for process
			# seeds, this depends only on _seed, not on randomState so it won't
			# vary with simulation code details.
			daughters.append(dict(
				config,
				id=str(uuid.uuid1()),
				inherited_state_path=path,
				seed=37 * self._seed + 47 * i + 997))

		return daughters

	def generate_inner_update(self):
		# sends environment a dictionary with relevant state changes
		return {
			'volume': self.listeners['Mass'].volume,
			'division': self.daughter_config(),
			'exchange': self.external_states[
				'Environment'
			].get_environment_change(),
			'bulk_molecules_report': {
				mol:
				self.internal_states['BulkMolecules'].container.count(mol)
				for mol in self._to_report['bulk_molecules']
			},
			'unique_molecules_report': {
				mol:
				self.internal_states['UniqueMolecules'].container.count(mol)
				for mol in self._to_report['unique_molecules']
			},
			'listeners_report': {
				(listener, attr): getattr(self.listeners[listener], attr)
				for listener, attr in self._to_report['listeners']
			},
		}

	def divide(self):
		self.cellCycleComplete()
		self.finalize()

		return self.daughter_config()
