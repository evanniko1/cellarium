#!/usr/bin/env python

"""
ParameterProvenance listener — how much of what this cell is doing right now rests on a parameter
that was never fitted.

WHY THIS EXISTS. ParCa infers mRNA degradation rates by non-negative least squares over the cistron x
transcription-unit matrix, under a lower bound on the rate. For a large minority of units it returns no
fitted value at all: measured on the knowledge base behind most of this corpus, 854 of 3,133 mRNA units
(27.3%) carry the rate FLOOR, the rate CEILING, or the population MEAN half-life. On disk all four classes
are the same float in the same array, so nothing downstream can tell a fit from a default.

The corpus-level number for that exposure is 12.087% of mRNA expression -- but it is computed from the BASAL
expression vector, a static property of the knowledge base. This listener reports the same quantity weighted
by the mRNA the simulation ACTUALLY HAS at each timestep. Those differ whenever the cell is doing anything
interesting: a stringent response redistributes transcription away from ribosomal operons, and the two
heaviest not-a-fit units in this knowledge base ARE ribosomal protein operons (rpmJ 1.584%,
rplNXE-rpsNH-rplFR-rpsE-rpmD-rplO 1.582%, both on the floor). A number no post-hoc analysis can reconstruct,
because the weights only exist while the simulation is running.

WHY IT READS A MOUNTED FILE INSTEAD OF A FIELD IN sim_data. The obvious design is a `deg_rate_is_fit` column
on `rna_data`. That means editing `reconstruction/`, which changes what ParCa emits, which moves `kb_sha256`
-- and `kb_sha256` is one of the three comparability keys, so every existing row in the corpus would stop
pooling with anything produced afterwards. Measured inside the container, that cost buys nothing: all 854
baseline ids match `sim_data.process.transcription.rna_data['id']` exactly, so the classification can be
carried alongside as data and joined here. A listener is not read by ParCa, so this file moves no
comparability key.

FAIL LOUD, NEVER SILENTLY CLEAN. If the index is absent or does not match this knowledge base, every output
column is NaN and `index_ok` is 0 -- never 0.0%, which would read as "nothing rests on a placeholder" and is
the exact failure this listener exists to prevent. That is the same rule the rest of this project applies to
absent data: an empty result must never be reportable as a measurement.
"""

import json
import os

import numpy as np

import wholecell.listeners.listener

# Where the frozen index is mounted. Overridable so a run can point at a re-fit baseline without an edit.
INDEX_PATH = os.environ.get(
    "CELLARIUM_DEG_BASELINE", "/wcEcoli/cellarium_provenance/deg_rate_baseline.json")


class ParameterProvenance(wholecell.listeners.listener.Listener):
    """Per-timestep share of mRNA whose degradation rate is not a fitted value."""

    _name = 'ParameterProvenance'

    def __init__(self, *args, **kwargs):
        super(ParameterProvenance, self).__init__(*args, **kwargs)

    def initialize(self, sim, sim_data):
        super(ParameterProvenance, self).initialize(sim, sim_data)

        self.uniqueMolecules = sim.internal_states['UniqueMolecules']

        # Same id space and the same index arithmetic as the RNACounts listener, deliberately: this must
        # count what that listener counts, or the two disagree about the same cell in the same output.
        rna_data = sim_data.process.transcription.rna_data
        self.all_TU_ids = rna_data['id']
        self.mRNA_indexes = np.where(rna_data['is_mRNA'])[0]
        self.rRNA_indexes = np.where(rna_data['is_rRNA'])[0]
        mRNA_TU_ids = self.all_TU_ids[self.mRNA_indexes]

        self.index_ok = 0
        self.index_kb_sha256 = ''
        self.n_units_matched = 0
        self.n_units_expected = 0
        # Per-class masks over the mRNA axis, so a reader can separate a bound from an imputed default
        # rather than being handed one lumped number.
        self._masks = {k: np.zeros(len(mRNA_TU_ids), dtype=bool)
                       for k in ('floor', 'ceiling', 'imputed')}
        self._any = np.zeros(len(mRNA_TU_ids), dtype=bool)

        doc = self._load_index()
        if doc is not None:
            units = doc.get('units_not_a_fit') or {}
            position = {uid: i for i, uid in enumerate(mRNA_TU_ids)}
            matched = 0
            expected = 0
            for cls in ('floor', 'ceiling', 'imputed'):
                for uid in (units.get(cls) or {}):
                    expected += 1
                    i = position.get(uid)
                    if i is not None:
                        self._masks[cls][i] = True
                        matched += 1
            self._any = self._masks['floor'] | self._masks['ceiling'] | self._masks['imputed']
            self.n_units_matched = matched
            self.n_units_expected = expected
            self.index_kb_sha256 = str(doc.get('kb_sha256') or '')
            # A PARTIAL match means the index was built against a different knowledge base. Reporting a
            # fraction from a partial join would understate the exposure by exactly the units that did not
            # match, silently. Refuse the whole thing instead.
            self.index_ok = int(expected > 0 and matched == expected)

    def _load_index(self):
        try:
            with open(INDEX_PATH, 'r') as fh:
                return json.load(fh)
        except Exception:
            return None

    def allocate(self):
        super(ParameterProvenance, self).allocate()

        self.n_mRNA = 0
        self.n_mRNA_not_a_fit = 0
        self.frac_counts_not_a_fit = np.nan
        self.frac_counts_on_floor = np.nan
        self.frac_counts_on_ceiling = np.nan
        self.frac_counts_imputed = np.nan

    def update(self):
        if not self.index_ok:
            return                              # every column stays NaN; index_ok says why

        RNAs = self.uniqueMolecules.container.objectsInCollection('RNA')
        TU_indexes, can_translate, is_full_transcript = RNAs.attrs(
            'TU_index', 'can_translate', 'is_full_transcript')
        if len(TU_indexes) == 0:
            # No RNA objects at all. Every fraction stays NaN: this is an undefined ratio, not 0% resting on
            # a placeholder. Handled here rather than after the bincount because an EMPTY index array is
            # float64 by default and np.bincount refuses to cast it — a listener that raised inside update()
            # would take the whole generation down with it.
            return
        is_rRNA = np.isin(TU_indexes, self.rRNA_indexes)
        all_TU_counts = np.bincount(
            TU_indexes[np.logical_or(can_translate, is_rRNA)], minlength=len(self.all_TU_ids))
        mRNA_counts = all_TU_counts[self.mRNA_indexes]

        total = float(mRNA_counts.sum())
        self.n_mRNA = int(total)
        self.n_mRNA_not_a_fit = int(mRNA_counts[self._any].sum())
        if total <= 0:
            # No mRNA at all is not "0% rests on a placeholder" — it is an undefined ratio, and a division
            # here would publish 0.0 for a cell that has nothing to divide.
            return
        self.frac_counts_not_a_fit = float(mRNA_counts[self._any].sum()) / total
        self.frac_counts_on_floor = float(mRNA_counts[self._masks['floor']].sum()) / total
        self.frac_counts_on_ceiling = float(mRNA_counts[self._masks['ceiling']].sum()) / total
        self.frac_counts_imputed = float(mRNA_counts[self._masks['imputed']].sum()) / total

    def tableCreate(self, tableWriter):
        tableWriter.writeAttributes(
            index_path=INDEX_PATH,
            index_kb_sha256=self.index_kb_sha256,
            index_ok=self.index_ok,
            n_units_matched=self.n_units_matched,
            n_units_expected=self.n_units_expected,
            note=('Fractions are of mRNA COUNTS at each timestep, not of the basal expression vector. '
                  'index_ok=0 means the index could not be joined to this knowledge base and every '
                  'fraction is NaN — that is a refusal to measure, not a measurement of zero.'),
        )

    def tableAppend(self, tableWriter):
        tableWriter.append(
            time=self.time(),
            simulationStep=self.simulationStep(),
            n_mRNA=self.n_mRNA,
            n_mRNA_not_a_fit=self.n_mRNA_not_a_fit,
            frac_counts_not_a_fit=self.frac_counts_not_a_fit,
            frac_counts_on_floor=self.frac_counts_on_floor,
            frac_counts_on_ceiling=self.frac_counts_on_ceiling,
            frac_counts_imputed=self.frac_counts_imputed,
        )
