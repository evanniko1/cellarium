"""EXT-PORT — apply the kinetic tRNA charging port (per-isoacceptor) to a wcEcoli checkout.

Source: CovertLab/WholeCellEcoliRelease **v3.0.1** — Choi & Covert 2023, *NAR* 51(12):5911,
doi:10.1093/nar/gkad435. Applied with permission from Prof. Covert.

**This applies FROM A REFERENCE TREE.** The reference is carried in-repo at `vendor/v301/` — Prof. Covert
has given permission to use and redistribute this code, so it is committed rather than gitignored, and
EXT-PORT-9 (the port not being reproducible from a clone) dissolves with it. Applying from a reference
rather than inlining ~1275 lines into this script is now purely a readability choice: the script records
the ADAPTATIONS, which are ours and are the part worth reading, while the ported code stays diffable
against upstream.

Attribution: Choi & Covert 2023, *NAR* 51(12):5911, doi:10.1093/nar/gkad435; code from
`CovertLab/WholeCellEcoliRelease` v3.0.1.

Five files change, and the fifth is the one that bites. `raw_data` does **not** scan `flat/` — it reads an
explicit `LIST_OF_DICT_FILENAMES`, so a file that is copied but not registered is SILENTLY INVISIBLE. The first
pass of this port copied all the flat files, every edit parsed, nothing raised, and `raw_data.optimization` did
not exist. That would have surfaced as an `AttributeError` minutes into a ParCa rebuild, blaming `relation.py`.
Registration is part of the port, not an afterthought.

Two further traps, both handled here:
  * **Line endings.** The destination tree is 100% CRLF and the v3.0.1 tree is 100% LF. Appending one to the
    other unnormalised produces a mixed-ending file. Every write preserves the DESTINATION's convention.
  * **UGA.** The codon set skips `UAA`/`UAG` but KEEPS `UGA`, which encodes selenocysteine. Reading "skip stop
    codons" literally yields 61 codons instead of 62 and shifts every downstream index — a model that runs and
    is quietly wrong.

Idempotent: every edit is guarded by its own marker, and `--check` writes nothing. A PARTIAL application is
reported as partial rather than as done, so a half-finished port cannot be mistaken for a finished one.

Two later rounds are DELEGATED to their own modules rather than inlined here, because duplicating their
anchors is how two copies of one recipe drift apart. Both are idempotent and marker-guarded on exactly
these terms, and both are applied from this script:
  * `scripts/ext_port_10_patch.py` -- the four items blocking the codon-aware path. One of its edits is
    NOT additive: it types phnE1 'pseudo', which changes the DEFAULT path too.
  * `scripts/ext_port_11_patch.py` -- the tRNA charging OPTIMISER and the charged-fraction ANCHOR. It
    supplies the missing `codon_read_rate` producer (without which the fit KeyErrors on its first
    synthetase), the Parca step and CLI flag the optimiser never had, and a fifth objective term whose
    target is a PARAMETER with a documented default of "no anchor". It is additive to sim_data but it
    does move kb_sha256.

    python scripts/apply_trna_port.py --wcecoli /path/to/wcEcoli --reference vendor/v301 --check
    python scripts/apply_trna_port.py --wcecoli /path/to/wcEcoli --reference vendor/v301
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys

REL = os.path.join("reconstruction", "ecoli", "dataclasses", "relation.py")
MG = os.path.join("reconstruction", "ecoli", "dataclasses", "molecule_groups.py")
MI = os.path.join("reconstruction", "ecoli", "dataclasses", "molecule_ids.py")
SD = os.path.join("reconstruction", "ecoli", "simulation_data.py")
KB = os.path.join("reconstruction", "ecoli", "knowledge_base_raw.py")
# EXT-PORT-11 touches three more files than the original port did.
FSD = os.path.join("reconstruction", "ecoli", "fit_sim_data_1.py")
PARCA_TASK = os.path.join("wholecell", "fireworks", "firetasks", "parca.py")
FITSIMDATA_TASK = os.path.join("wholecell", "fireworks", "firetasks", "fitSimData.py")

# The seven imports the appended relation.py methods need. Ours had ONLY `import numpy as np`. Every one of
# these is used inside the ported methods, and they fail LATE: `warnings` is referenced only on an mRNA/protein
# sequence mismatch, so ParCa ran for minutes and then died with `NameError: name 'warnings' is not defined`
# from inside _build_codon_sequences. Appending methods without appending their imports is the same
# silent-absence class as copying a flat file without registering it in LIST_OF_DICT_FILENAMES.
REL_IMPORT_ANCHOR = "import numpy as np\n"
REL_IMPORTS = (
    "\n# EXT-PORT-1: required by the ported relation methods (v3.0.1). `warnings` in particular is reached\n"
    "# only on a sequence-mismatch branch, so its absence surfaces minutes into a ParCa rebuild, not at import.\n"
    "import copy\n"
    "import json\n"
    "import warnings\n"
    "from Bio.Seq import Seq\n"
    "from scipy.optimize import minimize\n"
    "from wholecell.utils import units\n"
    "from wholecell.utils.polymerize import polymerize\n")

# The Cython extension `polypeptide_elongation.py` imports (`get_initiations`, `get_elongation_rate`,
# `reconcile_via_ribosome_positions`, ...). 644 lines of .pyx, built exactly the way Covert's own setup.py does
# — `cythonize()`. NO DOCKER IMAGE REBUILD IS NEEDED: the model image already carries Cython 0.29.35 and gcc
# (it compiled mc_complexation / _build_sequences at image build time), so the extension compiles IN the
# existing image. Verified: returncode 0, and the built .so imports with all seven expected symbols.
#
# I first reported this as requiring a native image rebuild "a different order of work". That was wrong, and it
# came from checking the IMPORT FAILURE instead of checking whether the image could BUILD it.
# The one place the two trees genuinely disagree on SEMANTICS rather than on presence. v3.0.1 looked each
# monomer's mRNA up in `rna_data`; here that array is transcription units, the index is in cistron space,
# and the getter has no key for a polycistronic gene's own RNA id. Three ParCa runs walked this down
# (IndexError -> KeyError 'EG10001_' -> KeyError 'EG10001_RNA'), and the first of those raised only
# because n_cistrons happens to exceed n_TU — had it been the other way round, every protein would have
# received the WRONG mRNA and the port would have looked finished.
#
# The replacement parses each cistron from its own gene's genome coordinates. The obvious alternative —
# slicing the cistron out of a transcription unit with `cistron_start_end_pos_in_tu` — was implemented,
# measured, and REJECTED: it agrees for 4535 of 4539 cistrons but is wrong for the four that overhang
# their TU's 5' end (wza/G7107, holC/EG11413, ytiC/G0-16686, dinG/EG11357), because the assert at
# transcription.py:823 guards only the 3' end. Head to head through scripts/probe_relation.py the TU
# route leaves 3 monomers whose mRNA does not translate to their protein and this route leaves 1.
# It also disposes of a problem rather than solving it: 694 cistrons sit in more than one TU, and for
# two of them the TUs disagree on the sequence — with the lowest TU index right for EG11413_RNA and
# WRONG for G7107_RNA. A cistron has exactly one gene, so on this route there is nothing to pick.
#
# Known cost, recorded as EXT-PORT-7(b): the runtime places ribosomes with cistron_start_end_pos_in_tu
# (initialization.py:1164), so for those same four cistrons the codon sequence and the ribosome position
# disagree. They disagree because the stored offsets are wrong, which is a pre-existing defect in this
# tree; matching it deliberately would mean shipping a sequence we have measured to be wrong.
REL_CISTRON_OLD = ("\t\trna_sequences = sim_data.getter.get_sequences(\n"
                   "\t\t\t[rna_id[:-3] for rna_id\n"
                   "\t\t\tin sim_data.process.transcription.rna_data['id']])\n")
REL_CISTRON_NEW = '\t\t# EXT-PORT-1C adaptation. Each cistron\'s mRNA is parsed from ITS OWN GENE\'s genome coordinates.\n\t\t#\n\t\t# v3.0.1 read each monomer\'s mRNA out of `rna_data`, whose rows were one-per-cistron in that tree\n\t\t# because it ran with operons OFF. Here `rna_data` is TRANSCRIPTION UNITS while\n\t\t# `cistron_to_monomer_mapping` indexes CISTRONS, and `getter._sequences` is keyed by TU ids plus only\n\t\t# the RNA ids of genes belonging to no TU — so most cistron ids are not keys at all.\n\t\t#\n\t\t# Slicing the cistron out of a transcription unit with `cistron_start_end_pos_in_tu` reproduces this\n\t\t# sequence for 4535 of 4539 cistrons, but it is NOT equivalent. Four cistrons overhang their TU\'s 5\'\n\t\t# end — wza/G7107, holC/EG11413, ytiC/G0-16686, dinG/EG11357 — and the assert at\n\t\t# transcription.py:823 only guards the 3\' end, so for those four the stored offsets are silently\n\t\t# wrong. Measured head to head with scripts/probe_relation.py: the TU route leaves 3 monomers whose\n\t\t# mRNA does not translate to their protein, this route leaves 1.\n\t\t#\n\t\t# A cistron maps to exactly one gene, so there is no transcription unit to choose here and no\n\t\t# ambiguity to resolve — the 694 cistrons that sit in more than one TU simply stop being a question.\n\t\t# The parse is the same construction getter_functions.py:187-200 uses for monocistronic RNAs.\n\t\tgenome_sequence = raw_data.genome_sequence\n\n\t\tdef parse_cistron_sequence(cistron_id, left_end_pos, right_end_pos, direction):\n\t\t\t"""Genome slice for one cistron. Behaviourally identical to\n\t\t\tGetterFunctions._build_rna_sequences.parse_sequence: coordinates are 1-indexed and inclusive, and\n\t\t\tthe \'-\' strand is reverse complemented over the SAME window before transcription, so left/right\n\t\t\tstay genome coordinates rather than 5\'/3\' order."""\n\t\t\tif direction == \'+\':\n\t\t\t\treturn genome_sequence[left_end_pos - 1:right_end_pos].transcribe()\n\t\t\telif direction == \'-\':\n\t\t\t\treturn genome_sequence[\n\t\t\t\t\tleft_end_pos - 1:right_end_pos].reverse_complement().transcribe()\n\t\t\telse:\n\t\t\t\traise ValueError(\n\t\t\t\t\t\'Unidentified transcription direction {} given for {}\'.format(\n\t\t\t\t\t\tdirection, cistron_id))\n\n\t\tcistron_id_to_gene_id = {\n\t\t\tgene[\'rna_ids\'][0]: gene[\'id\'] for gene in raw_data.genes}\n\t\tgene_id_to_left_end_pos = {\n\t\t\tgene[\'id\']: gene[\'left_end_pos\'] for gene in raw_data.genes}\n\t\tgene_id_to_right_end_pos = {\n\t\t\tgene[\'id\']: gene[\'right_end_pos\'] for gene in raw_data.genes}\n\t\tgene_id_to_direction = {\n\t\t\tgene[\'id\']: gene[\'direction\'] for gene in raw_data.genes}\n\n\t\t# Built by iterating cistron_data[\'id\'] itself, so the list is in cistron_data index space by\n\t\t# construction — the space cistron_to_monomer_mapping addresses.\n\t\tcistron_ids = sim_data.process.transcription.cistron_data[\'id\']\n\t\trna_sequences = []\n\t\tfor cistron_id in cistron_ids:\n\t\t\tgene_id = cistron_id_to_gene_id[cistron_id]\n\t\t\trna_sequences.append(parse_cistron_sequence(\n\t\t\t\tcistron_id,\n\t\t\t\tgene_id_to_left_end_pos[gene_id],\n\t\t\t\tgene_id_to_right_end_pos[gene_id],\n\t\t\t\tgene_id_to_direction[gene_id]))\n\n\t\t# This port indexed an array with the wrong index space once already, and it raised IndexError only\n\t\t# because the two arrays happened to differ in length. Assert the invariant instead of relying on\n\t\t# that luck: the row read for monomer i must be monomer i\'s own cistron.\n\t\tmonomer_cistron_ids = sim_data.process.translation.monomer_data[\'cistron_id\']\n\t\tassert len(rna_sequences) == len(cistron_ids)\n\t\tassert all(\n\t\t\tcistron_ids[self.cistron_to_monomer_mapping[i]] == monomer_cistron_ids[i]\n\t\t\tfor i in range(len(monomer_cistron_ids))), (\n\t\t\t\'cistron_to_monomer_mapping does not address cistron_data index space\')\n'

# v3.0.1 predates the removal of `np.bool` (deprecated in NumPy 1.20, REMOVED in 1.24; the image runs
# 1.26.3). Two uses come in with the port. The one in relation.py surfaces during ParCa; the one in
# KineticTrnaChargingModel.__init__ does NOT - ParCa never executes it and neither does a default
# simulation, so it would have fired only at the start of the first --kinetic-trna-charging campaign.
# `np.bool_` is valid both before and after the break.
NP_ALIAS_OLD = "np.bool)"
NP_ALIAS_NEW = "np.bool_)"

REL_SKIP_OLD = "\t\t\tif rna_sequence_translated != protein_sequence:\n\t\t\t\twarnings.warn('mRNA sequence does not match the protein '\n\t\t\t\t\t'sequence for {}'.format(protein_id))\n\t\t\t\tcontinue\n"
REL_SKIP_NEW = "\t\t\tif rna_sequence_translated != protein_sequence:\n\t\t\t\t# EXT-PORT-1C adaptation: RECORD instead of `continue`.\n\t\t\t\t#\n\t\t\t\t# Upstream drops the monomer here, which is not survivable: the very next method,\n\t\t\t\t# _build_codon_based_translation, subscripts _codon_sequences for EVERY monomer, so one warning\n\t\t\t\t# becomes a KeyError seconds later and ParCa cannot finish at all.\n\t\t\t\t#\n\t\t\t\t# Three of 4310 monomers land here, and the data is IDENTICAL in v3.0.1 — same protein\n\t\t\t\t# sequences, same gene coordinates, same empty coding_segments (checked against\n\t\t\t\t# WholeCellEcoliRelease v3.0.1 rnas.tsv / genes.tsv / proteins.tsv). So this is a pre-existing\n\t\t\t\t# annotation limitation, not something the port introduced:\n\t\t\t\t#   PHNE-MONOMER     phnE1, the MG1655 8-bp insertion. v3.0.1 sidesteps it by typing\n\t\t\t\t#                    EG11283_RNA as 'pseudo', which EXCLUDED_RNA_TYPES then drops; this tree\n\t\t\t\t#                    types it 'mRNA', so it stays in scope. The only row whose type differs.\n\t\t\t\t#   EG11357-MONOMER  dinG. In-frame stop 2 residues early; no offset in the TU reproduces the\n\t\t\t\t#                    curated 716-mer (searched +/-300 nt).\n\t\t\t\t#   MONOMER0-4391    ytiC. Stop at the second codon.\n\t\t\t\t#\n\t\t\t\t# Keeping the mRNA-derived sequence makes those three differ from their curated protein by a\n\t\t\t\t# few residues. Dropping them instead would leave them with NO codon sequence, i.e. a protein\n\t\t\t\t# the kinetic model can never elongate. Wrong by two residues beats never synthesised, and\n\t\t\t\t# neither is silent: the warning fires and the list is on sim_data.relation.\n\t\t\t\twarnings.warn('mRNA sequence does not match the protein '\n\t\t\t\t\t'sequence for {}'.format(protein_id))\n\t\t\t\tself.codon_sequence_mismatches.append(protein_id)\n"
REL_INIT_OLD = '\t\tself._codon_sequences = {}\n'
REL_INIT_NEW = '\t\tself._codon_sequences = {}\n\t\t# EXT-PORT-1C: monomers whose mRNA does not translate to their curated protein. Empty is the\n\t\t# expected state; anything in here is a knowledge-base limitation worth naming, not hiding.\n\t\tself.codon_sequence_mismatches = []\n'

REL_ACC_OLD = '\t\t\t# Record codon to amino acid interactions\n\t\t\tfor codon, amino_acid in zip(codon_sequence, protein_sequence):\n'
REL_ACC_NEW = '\t\t\t# Record codon to amino acid interactions\n\t\t\t# EXT-PORT-1C: the recorded mismatches are excluded from THIS accumulation, though their codon\n\t\t\t# sequence is kept above. Their mRNA and protein disagree by construction, so their\n\t\t\t# codon->amino-acid pairs are not evidence of anything — and feeding them in trips the\n\t\t\t# overloaded-codon assert below with a mapping that is genuinely inconsistent.\n\t\t\tif protein_id in self.codon_sequence_mismatches:\n\t\t\t\tcontinue\n\t\t\tfor codon, amino_acid in zip(codon_sequence, protein_sequence):\n'

REL_TRNA_OLD = "\t\t# Map tRNAs to their anticodons\n\t\trna_data = sim_data.process.transcription.rna_data\n\t\tfree_trnas = rna_data['id'][rna_data['is_tRNA']]\n\t\tanticodons = rna_data['anticodon'][rna_data['is_tRNA']]\n\t\ttrna_to_anticodon = dict(zip(free_trnas, anticodons))\n"
REL_TRNA_NEW = "\t\t# Map tRNAs to their anticodons\n\t\t# EXT-PORT-1C adaptation, and the one that unblocks the whole tRNA half of the port at once.\n\t\t# v3.0.1 took the tRNA list from `rna_data`, which is correct only when operons are OFF and\n\t\t# rna_data degenerates to one row per cistron. Here rna_data is TRANSCRIPTION UNITS, so that\n\t\t# list comes out ~42 long instead of 86 — and `dict(zip(free_trnas, charged_trnas))` would have\n\t\t# TRUNCATED to the shorter of the two without raising, quietly pairing the wrong tRNAs.\n\t\t#\n\t\t# `transcription.uncharged_trna_names` is the canonical list: cistron ids with a '[c]' tag\n\t\t# (transcription.py:1265). Everything the ported code needs is already aligned to it —\n\t\t# `charged_trna_names` one-for-one (asserted at transcription.py:1285), the 86 columns of\n\t\t# `aa_from_trna`, `molecule_groups.initiator_trnas`, the six hard-coded wobble tRNAs below, and\n\t\t# the K_M keys in flat/optimization/trna_charging_kinetics_solutions.tsv.\n\t\t#\n\t\t# The anticodon has to come from raw_data: it is a column of rnas.tsv but is propagated into\n\t\t# neither cistron_data nor rna_data, which is why `rna_data['anticodon']` raised KeyError.\n\t\tfree_trnas = np.array(sim_data.process.transcription.uncharged_trna_names)\n\t\tanticodon_by_rna_id = {rna['id']: rna['anticodon'] for rna in raw_data.rnas}\n\t\tanticodons = [anticodon_by_rna_id[trna[:-3]] for trna in free_trnas]\n\t\ttrna_to_anticodon = dict(zip(free_trnas, anticodons))\n\t\tassert len(trna_to_anticodon) == len(free_trnas)\n"

# EXT-PORT-5 / EXT-PORT-8 — the RUNTIME half, which ParCa never executes and therefore never checks.
#
# The same operons-OFF assumption that broke relation.py also sits in the ported process and listener:
# `rna_data['id'][rna_data['is_tRNA']]` gives 51 transcription-unit ids where everything else uses the 86
# cistron ids of `uncharged_trna_names` (intersection: 9). What makes this the worst defect in the port is
# that it does NOT crash first — `relation.trna_to_K_T.get(trna, 1*units.umol/units.L)` would have
# silently defaulted 42 of 51 lookups, and a .get with a default cannot fail loudly.
#
# The gate is the other half. The elongation MODELS are ported and their knowledge base builds, but the
# HOST PolypeptideElongation process is not: it still calls them with the steady-state arity
# (elongation_rate 0 args vs 3, request 1 vs 4, evolve 5 vs 8) and never calls seven of their methods.
# Ungated, `--kinetic-trna-charging` fails with a TypeError deep inside a simulation that has already run
# ParCa. Gated, it fails at construction with a sentence saying what is missing.
PE_TRNA_OLD = "\t\trna_data = transcription.rna_data\n\t\tfree_trnas = rna_data['id'][rna_data['is_tRNA']].tolist()\n"
PE_TRNA_NEW = "\t\t# EXT-PORT-5: `rna_data['id'][rna_data['is_tRNA']]` is the v3.0.1 idiom and it is wrong here for\n\t\t# the same reason it was wrong in relation.py — with operons ON, rna_data is TRANSCRIPTION\n\t\t# UNITS. Measured: it yields 51 TU ids against the 86 cistron ids everything else uses, an\n\t\t# intersection of 9. `relation.trna_to_K_T.get(trna, 1*units.umol/units.L)` would then have\n\t\t# silently defaulted 42 of 51 lookups — a .get with a default CANNOT fail loudly — and the\n\t\t# 51-vs-86 width disagreement crashes this constructor a few lines below.\n\t\t# SteadyStateElongationModel already uses uncharged_trna_names in this same file.\n\t\tfree_trnas = list(transcription.uncharged_trna_names)\n"
GATE_OLD = '\t\tif kinetic_trna_charging:\n'
GATE_NEW = "\t\t# EXT-PORT-8 GATE. The two kinetic elongation models are ported and their knowledge base is built\n\t\t# (ParCa is green), but the HOST process around them is not: v3.0.1's codon-aware\n\t\t# calculateRequest/evolveState were never brought across, so this class still calls the elongation\n\t\t# model with the steady-state arity. Measured mismatches:\n\t\t#     elongation_rate()          0 args   vs KineticTrnaChargingModel's 3\n\t\t#     request(aasInSequences)    1 arg    vs 4\n\t\t#     evolve(...)                5 args   vs 8\n\t\t# and seven further methods of the kinetic model (run_model, reconcile, protein_maturation,\n\t\t# record_mass, sequences, codon_sequences_width, monomer_limit) are never called at all.\n\t\t# Also missing: monomer_data has no 'cleavage_of_initial_methionine' column, which the kinetic\n\t\t# constructor reads.\n\t\t#\n\t\t# Without this gate the flag is reachable and fails with a TypeError deep inside a simulation that\n\t\t# has already run ParCa and started elongating. Fail here instead, and say what is missing.\n\t\tif kinetic_trna_charging or coarse_kinetic_elongation:\n\t\t\traise NotImplementedError(\n\t\t\t\t'kinetic_trna_charging / coarse_kinetic_elongation are NOT runnable yet. The elongation '\n\t\t\t\t'models and their knowledge base are ported (EXT-PORT-1), but the host PolypeptideElongation '\n\t\t\t\t'process still uses the steady-state calling convention, so the kinetic models would be '\n\t\t\t\t'called with the wrong arity. See BACKLOG EXT-PORT-8. Run without these flags to use '\n\t\t\t\t'SteadyStateElongationModel, which is unchanged by the port.')\n\t\tif kinetic_trna_charging:\n"
LIS_TRNA_OLD = "\t\trna_data = sim_data.process.transcription.rna_data\n\t\ttrnas = rna_data['id'][rna_data['is_tRNA']]\n"
LIS_TRNA_NEW = '\t\t# EXT-PORT-5: cistron space, not transcription-unit space — see the note in\n\t\t# polypeptide_elongation.py:KineticTrnaChargingModel.__init__. Sizing these columns from\n\t\t# rna_data gives 51 where the relation arrays are 86, so every logged column would be the\n\t\t# wrong width against data that is 86 wide.\n\t\ttrnas = sim_data.process.transcription.uncharged_trna_names\n'


# The Fireworks firetasks keep their OWN allow-list of simulation kwargs, separate from scriptBase's two
# lists. Fireworks RAISES on an unknown kwarg, so adding a flag to scriptBase alone does not merely fail to
# reach the sim — it breaks EVERY run, including the default one, with
#   RuntimeError: Invalid keyword argument specified for SimulationTask. You specified:
#   kinetic_trna_charging.
# Found by actually running `runscripts/manual/runSim.py`. It was invisible to a check that constructs
# EcoliSimulation directly, because that path never goes through Fireworks. Both task classes need it: the
# first generation goes through SimulationTask, every later one through SimulationDaughterTask.
FIRETASKS = (os.path.join("wholecell", "fireworks", "firetasks", "simulation.py"),
             os.path.join("wholecell", "fireworks", "firetasks", "simulationDaughter.py"))
FT_LIST_OLD = '\t\t"trna_charging",\n'
FT_LIST_NEW = ('\t\t"trna_charging",\n'
               '\t\t# EXT-PORT-3: this allow-list is separate from scriptBase.SIM_KEYS, and Fireworks raises\n'
               '\t\t# on an unknown kwarg, so the two must stay in step or every run fails.\n'
               '\t\t"kinetic_trna_charging",\n'
               '\t\t"coarse_kinetic_elongation",\n')
FT_OPT_OLD = '\t\toptions["trna_charging"] = self._get_default("trna_charging")\n'
FT_OPT_NEW = ('\t\toptions["trna_charging"] = self._get_default("trna_charging")\n'
              '\t\toptions["kinetic_trna_charging"] = self._get_default("kinetic_trna_charging")\n'
              '\t\toptions["coarse_kinetic_elongation"] = self._get_default("coarse_kinetic_elongation")\n')


# EXT-PORT-7: two silent-wrong conditions the ported code's own asserts leave open. Both were found by
# a content audit of the built structures rather than by anything crashing — which is the point.
REL_OVERLOAD_OLD = '\t\t# Check for overloaded codons\n\t\tassert np.all(np.array(\n\t\t\t[len(amino_acids) for amino_acids in codon_to_amino_acid.values()]\n\t\t\t) <= 1)\n'
REL_OVERLOAD_NEW = "\t\t# Check for overloaded codons\n\t\tassert np.all(np.array(\n\t\t\t[len(amino_acids) for amino_acids in codon_to_amino_acid.values()]\n\t\t\t) <= 1)\n\n\t\t# EXT-PORT-7: ...and for UNASSIGNED ones, which the check above does not cover. This mapping is\n\t\t# derived empirically by observing (codon, amino acid) pairs across the proteome, so a codon that no\n\t\t# protein happens to use gets an EMPTY list rather than an error. That becomes an all-zero column in\n\t\t# codons_to_amino_acids, and the residue-weight loop below then does `np.where(col)[0][0]` on it and\n\t\t# raises IndexError from a line that has nothing to do with the cause. Measured on this build: all 63\n\t\t# columns sum to exactly 1, so this holds today and the assert is here to catch drift.\n\t\tunassigned = [codon for codon, amino_acids in codon_to_amino_acid.items() if len(amino_acids) == 0]\n\t\tassert not unassigned, (\n\t\t\t'no amino acid was observed for codon(s) {} anywhere in the proteome, so their columns of '\n\t\t\t'codons_to_amino_acids would be all-zero'.format(unassigned))\n"
REL_WEIGHTS_OLD = '\t\t# Describe residue masses\n\t\tresidue_weights_by_codon = []\n'
REL_WEIGHTS_NEW = "\t\t# Describe residue masses\n\t\t# EXT-PORT-7: the loop below crosses TWO amino-acid orderings. `i` is a row index into\n\t\t# codons_to_amino_acids, which is ordered by molecule_groups.amino_acids (see\n\t\t# _build_codon_sequences), and it indexes translation_monomer_weights, which is ordered by\n\t\t# amino_acid_code_to_id_ordered.values() (translation.py). They are element-for-element equal in this\n\t\t# build, which is why this works — but nothing enforces it, and if they ever diverged every residue\n\t\t# weight would be silently PERMUTED with no error anywhere. Assert the coupling the code relies on.\n\t\tassert (list(sim_data.molecule_groups.amino_acids)\n\t\t\t\t== list(sim_data.amino_acid_code_to_id_ordered.values())), (\n\t\t\t'molecule_groups.amino_acids and amino_acid_code_to_id_ordered disagree, so the row index of '\n\t\t\t'codons_to_amino_acids can no longer be used to index translation_monomer_weights')\n\t\tresidue_weights_by_codon = []\n"


# EXT-PORT-8 prerequisites. Both additive, and both needed before the codon-aware host path can run.
#   * monomer_data gains a `cleavage_of_initial_methionine` bool column. It is already on
#     raw_data.proteins in this tree and already read for the N-end rule; it simply never reached
#     monomer_data, and KineticTrnaChargingModel reads it per monomer. Note the field_units entry is
#     not optional: UnitStructArray raises on a field missing from field_units, so adding the dtype
#     entry alone fails at construction.
#   * BaseElongationModel gains `protein_lengths` and `next_amino_acids`. v3.0.1 carries both on ITS
#     base class; ours predates them, and KineticTrnaChargingModel inherits from ours.
TRL_EDITS = [('\t\tmonomer_data = np.zeros(\n', "\t\t# EXT-PORT-8: needed by KineticTrnaChargingModel, which reads it per monomer. Already present on\n\t\t# raw_data.proteins and already used above for the N-end rule; it just never reached monomer_data.\n\t\tcleavage_of_initial_methionine = np.zeros(len(all_proteins), dtype=bool)\n\t\tfor i, protein in enumerate(all_proteins):\n\t\t\tcleavage_of_initial_methionine[i] = protein['cleavage_of_initial_methionine']\n\n\t\tmonomer_data = np.zeros(\n"), ("\t\t\t\t('mw', 'f8'),\n\t\t\t\t]\n", "\t\t\t\t('mw', 'f8'),\n\t\t\t\t('cleavage_of_initial_methionine', 'bool'),\n\t\t\t\t]\n"), ("\t\tmonomer_data['mw'] = mws\n", "\t\tmonomer_data['mw'] = mws\n\t\tmonomer_data['cleavage_of_initial_methionine'] = cleavage_of_initial_methionine\n"), ("\t\t\t'mw': units.g / units.mol,\n", "\t\t\t'mw': units.g / units.mol,\n\t\t\t# None, not a unit: UnitStructArray raises on a field absent from field_units, so a new column\n\t\t\t# added to the dtype alone would fail at construction rather than being quietly unitless.\n\t\t\t'cleavage_of_initial_methionine': None,\n")]
PE_BASE_EDITS = [('\t\tself.water = self.process.bulkMoleculeView(sim_data.molecule_ids.water)\n', "\t\tself.water = self.process.bulkMoleculeView(sim_data.molecule_ids.water)\n\t\t# EXT-PORT-8: v3.0.1 carries this on its BaseElongationModel and our base predates it.\n\t\t# KineticTrnaChargingModel inherits from THIS class, so without it the codon-aware host path\n\t\t# raises AttributeError on its first step. Additive: nothing on the steady-state path reads it.\n\t\tself.protein_lengths = sim_data.process.translation.monomer_data['length'].asNumber()\n")]
PE_METHOD_ANCHOR = "\tdef elongation_rate(self):\n\t\tcurrent_media_id = self.process._external_states['Environment'].current_media_id\n"
PE_METHOD_NEW = '\tdef next_amino_acids(self, all_sequences, sequence_elongations):\n\t\t"""EXT-PORT-8: v3.0.1 BaseElongationModel\'s own implementation, verbatim. Only the codon-aware\n\t\tpath calls it; KineticTrnaChargingModel overrides it where it means something."""\n\t\treturn 0\n\n\tdef elongation_rate(self):\n\t\tcurrent_media_id = self.process._external_states[\'Environment\'].current_media_id\n'


# EXT-PORT-8: the elongation models are ALTERNATIVES, not modifiers, and leaving the flags independent
# is a silent-wrongness generator. v3.0.1 resolves them together (its simulation.py:164-180 sets
# _steady_state_trna_charging and _translationSupply False whenever _kinetic_trna_charging goes True).
# This belongs at the simulation level rather than in PolypeptideElongation because `trna_charging` is
# read elsewhere in the model: left True alongside a kinetic elongation model, metabolism goes on holding
# amino acid targets that nothing updates any more. Nothing raises; the numbers are simply wrong.
WSIM_RESOLVE_ANCHOR = '\t\tunknownKeywords = kwargs.keys() - DEFAULT_SIMULATION_KWARGS.keys()\n'
WSIM_RESOLVE = "\t\t# EXT-PORT-8: the elongation flags are MUTUALLY EXCLUSIVE, and saying so here rather than leaving\n\t\t# them independent closes a whole class of silent inconsistency. v3.0.1 resolves them exactly this\n\t\t# way (wholecell/sim/simulation.py:164-180 there): selecting the kinetic model sets\n\t\t# _steady_state_trna_charging and _translationSupply False in the same breath.\n\t\t#\n\t\t# It matters beyond the elongation process, which is why it belongs here and not in\n\t\t# PolypeptideElongation.initialize. `trna_charging` is read elsewhere in the model -- with it left\n\t\t# True alongside a kinetic model, metabolism keeps holding amino acid targets that nothing is\n\t\t# updating any more. Nothing raises; the numbers are just wrong.\n\t\tif self._kinetic_trna_charging or self._coarse_kinetic_elongation:\n\t\t\tif self._trna_charging or self._translationSupply:\n\t\t\t\tprint('EXT-PORT-8: a kinetic elongation model was selected, so trna_charging and'\n\t\t\t\t\t' translation_supply are being forced False (they are alternative elongation'\n\t\t\t\t\t' models, not modifiers).')\n\t\t\tself._trna_charging = False\n\t\t\tself._translationSupply = False\n\n"


PYX_SOURCE = os.path.join("wholecell", "utils", "_trna_charging.pyx")

# Run INSIDE the model image by `build_extension`. Deliberately mirrors what Covert's own top-level setup.py
# does — `cythonize(...)` with numpy's headers — rather than hand-rolling a compiler invocation.
BUILD_SCRIPT = r'''
import glob, os, shutil, subprocess, sys
import numpy as np
w = "/tmp/trna_build"
os.makedirs(w, exist_ok=True)
shutil.copy("/mnt/utils/_trna_charging.pyx", w)
with open(os.path.join(w, "setup.py"), "w") as f:
    f.write("import numpy as np\n"
            "from distutils.core import setup\n"
            "from Cython.Build import cythonize\n"
            "setup(ext_modules=cythonize('_trna_charging.pyx'), include_dirs=[np.get_include()])\n")
r = subprocess.run([sys.executable, "setup.py", "build_ext", "--inplace"],
                   cwd=w, capture_output=True, text=True)
so = glob.glob(os.path.join(w, "_trna_charging*.so"))
print("cythonize rc=%d so=%s" % (r.returncode, so or "NONE"))
if not so:
    sys.stdout.write(r.stdout[-2000:] + r.stderr[-2000:])
    sys.exit(1)
for x in so:
    shutil.copy(x, "/mnt/utils/")
'''

PE = os.path.join("models", "ecoli", "processes", "polypeptide_elongation.py")
LIS = os.path.join("models", "ecoli", "listeners", "trna_charging.py")
MSIM = os.path.join("models", "ecoli", "sim", "simulation.py")
WSIM = os.path.join("wholecell", "sim", "simulation.py")
SB = os.path.join("wholecell", "utils", "scriptBase.py")
TRL = os.path.join("reconstruction", "ecoli", "dataclasses", "process", "translation.py")
SETUP = "setup.py"
NP_ALIAS_FILES = (REL, PE)   # defined here because PE is not bound until this block

# `setup.py` names every .pyx EXPLICITLY — it does not glob `wholecell/utils/*.pyx`. So `make compile`, which
# is what the Dockerfile runs, would not build `_trna_charging` no matter that the source is present. This is
# the difference between the extension existing on a developer's host and existing in the image the
# simulations actually run in.
SETUP_ANCHOR = "complexation_module = cythonize("
SETUP_ADD = """trna_charging_module = cythonize(
	os.path.join("wholecell", "utils", "_trna_charging.pyx"),
	)

setup(
	name = "Kinetic tRNA charging",
	ext_modules = trna_charging_module,
	include_dirs = [np.get_include()],
	)

"""

# --- the elongation-model phase -------------------------------------------------------------------------------
# `polypeptide_elongation.py` cannot be copied wholesale: ours is 1212 lines and v3.0.1's is 2073, and they have
# diverged independently (ours carries `numba`/`dcdt_jit`, which v3.0.1 does not). What IS separable is the tail
# — `class KineticTrnaChargingModel` through EOF is exactly the two kinetic classes and nothing else, and every
# `self.process.*` attribute they reach for already exists on our PolypeptideElongation. So the port is: two
# imports, the class tail, and the selector.
PE_IMPORT_ANCHOR = "from wholecell.utils import units\n"
PE_IMPORT = (
    "\n# EXT-PORT-1 (WholeCellEcoliRelease v3.0.1, Choi & Covert 2023). Compiled by\n"
    "# scripts/apply_trna_port.py:build_extension inside the model image — see that module's header.\n"
    "# This is a MODULE-LEVEL import, so a missing .so is an ImportError at process construction,\n"
    "# not a quiet fallback to the steady-state model.\n"
    "from wholecell.utils._trna_charging import (get_initiations,\n"
    "\treconcile_via_ribosome_positions, reconcile_via_trna_pools,\n"
    "\tget_elongation_rate, get_codons_read)\n"
    "import copy\n")

# The flag read. We deliberately do NOT rename our `trna_charging` to v3.0.1's `steady_state_trna_charging`:
# that name is on the CLI (`--trna-charging`), in scriptBase's option lists, and in the provenance of every
# simulation already in the corpus. Renaming it would silently invalidate comparisons against existing runs for
# no scientific gain. Ours keeps its name in the steady-state slot; the two new flags are additive.
PE_FLAGS_ANCHOR = "\t\ttrna_charging = sim._trna_charging\n"
PE_FLAGS = ("\t\t# EXT-PORT-1: additive. `trna_charging` remains the steady-state flag it has always been.\n"
            "\t\tkinetic_trna_charging = getattr(sim, '_kinetic_trna_charging', False)\n"
            "\t\tcoarse_kinetic_elongation = getattr(sim, '_coarse_kinetic_elongation', False)\n")

PE_SELECT_OLD = ("\t\tif trna_charging:\n"
                 "\t\t\tself.elongation_model = SteadyStateElongationModel(sim_data, self)\n")
PE_SELECT_NEW = ("\t\tif kinetic_trna_charging:\n"
                 "\t\t\tself.elongation_model = KineticTrnaChargingModel(sim_data, self)\n"
                 "\t\telif coarse_kinetic_elongation:\n"
                 "\t\t\tself.elongation_model = CoarseKineticTrnaChargingModel(sim_data, self)\n"
                 "\t\telif trna_charging:\n"
                 "\t\t\tself.elongation_model = SteadyStateElongationModel(sim_data, self)\n")

# The guard that skips charged/uncharged tRNA views when no charging model is active. v3.0.1 widens it to
# `not (steady_state or kinetic)`. Missing this leaves the kinetic model without its views — a crash at step 1,
# not at construction.
PE_GUARD_OLD = "\t\tif not trna_charging:\n"
PE_GUARD_NEW = "\t\tif not (trna_charging or kinetic_trna_charging):\n"

# --- the listener phase ---------------------------------------------------------------------------------------
# A listener that is present but unregistered is invisible: `writeToListener('TrnaCharging', ...)` raises. The
# file copy and the registration are one step, never two.
LIS_IMPORT_ANCHOR = "from models.ecoli.listeners.ribosome_data import RibosomeData\n"
LIS_IMPORT = "from models.ecoli.listeners.trna_charging import TrnaCharging\n"
LIS_LIST_ANCHOR = "\t\tRibosomeData,\n"
LIS_LIST = "\t\tTrnaCharging,\n"

# --- the flag phase ---------------------------------------------------------------------------------------
WSIM_ANCHOR = "\ttrna_charging = True,\n"
WSIM_ADD = ("\t# EXT-PORT-3: per-isoacceptor kinetic charging (v3.0.1). Default OFF — turning it on changes the\n"
            "\t# elongation model, so it is a different model, not a different setting of the same one.\n"
            "\tkinetic_trna_charging = False,\n"
            "\tcoarse_kinetic_elongation = False,\n")

SB_LIST_ANCHOR = "\t'trna_charging',\n"
SB_LIST_ADD = "\t'kinetic_trna_charging',\n\t'coarse_kinetic_elongation',\n"
SB_OPT_ANCHOR = ("\t\t\thelp='if true, tRNA charging reactions are modeled and the ribosome'\n"
                 "\t\t\t\t ' elongation rate is set by the amount of charged tRNA\tpresent.'\n"
                 "\t\t\t\t ' This option will override TRANSLATION_SUPPLY in the simulation.')\n")
SB_OPT_ADD = ("\t\tadd_bool_option('kinetic_trna_charging', 'kinetic_trna_charging',\n"
              "\t\t\thelp='if true, tRNA charging is modeled per isoacceptor with explicit codon reading'\n"
              "\t\t\t\t ' (Choi & Covert 2023). Overrides --trna-charging.')\n"
              "\t\tadd_bool_option('coarse_kinetic_elongation', 'coarse_kinetic_elongation',\n"
              "\t\t\thelp='if true, use the coarse-grained kinetic elongation model (Choi & Covert 2023).')\n")


FLAT_FILES = [
    os.path.join("optimization", "trna_charging_kinetics_constants.tsv"),
    os.path.join("optimization", "trna_charging_kinetics_solutions.tsv"),
    os.path.join("optimization", "trna_synthetase_dynamic_range.tsv"),
    "trna_charging_kinetics.tsv",
    "trna_charging_kinetics_curated.tsv",
    "trna_charging_reactions.tsv",
]

# (anchor line, lines to insert BEFORE it) in knowledge_base_raw.LIST_OF_DICT_FILENAMES
REGISTRATIONS = [
    ('"trna_charging_reactions.tsv",',
     ['"trna_charging_kinetics.tsv",', '"trna_charging_kinetics_curated.tsv",']),
    ('os.path.join("trna_data", "trna_ratio_to_16SrRNA_0p4.tsv"),',
     ['os.path.join("optimization", "trna_charging_kinetics_constants.tsv"),',
      'os.path.join("optimization", "trna_charging_kinetics_solutions.tsv"),',
      'os.path.join("optimization", "trna_synthetase_dynamic_range.tsv"),']),
]

ATTRIBUTION = (
    "\n\t\t# Relate tRNAs, codons, and translation. Ported from CovertLab/WholeCellEcoliRelease v3.0.1\n"
    "\t\t# (Choi & Covert 2023, NAR 51(12):5911, doi:10.1093/nar/gkad435) with permission from\n"
    "\t\t# Prof. Covert. Consumed only by the kinetic-tRNA-charging elongation model; the default\n"
    "\t\t# SteadyStateElongationModel path is unchanged. See docs/MODEL_EXTENSION.md EXT-PORT.\n")

INIT_CALLS = ("codon_sequences", "codon_based_translation",
              "codon_dependent_trna_charging", "trna_charging_kinetics")

# The codon construction inserted into molecule_groups.py. Verbatim in behaviour from v3.0.1; UGA retained.
CODON_BUILD = (
    "\t\t# EXT-PORT (WholeCellEcoliRelease v3.0.1, Choi & Covert 2023): codon ids for kinetic tRNA charging.\n"
    "\t\t# UGA is deliberately KEPT as a sense codon because it encodes selenocysteine. Treating\n"
    "\t\t# 'skip stop codons' literally would give 61 codons instead of 62 and shift every downstream index.\n"
    "\t\tcodon_ids = []\n"
    "\t\tntp_abbreviations = [ntp[0] for ntp in ntp_ids]\n"
    "\t\tfor nucleotide_0 in ntp_abbreviations:\n"
    "\t\t\tfor nucleotide_1 in ntp_abbreviations:\n"
    "\t\t\t\tfor nucleotide_2 in ntp_abbreviations:\n"
    "\t\t\t\t\tcodon = nucleotide_0 + nucleotide_1 + nucleotide_2\n"
    "\t\t\t\t\tif codon in ['UAA', 'UAG']:\n"
    "\t\t\t\t\t\tcontinue\n"
    "\t\t\t\t\tcodon_ids.append(codon)\n\n")

GROUP_ENTRIES = (
    "\n\t\t\t'codons': codon_ids,\n"
    "\t\t\t'initiator_trnas': ['RNA0-306[c]', 'metY-tRNA[c]', 'metZ-tRNA[c]', 'metW-tRNA[c]'],\n"
    "\t\t\t'elongator_trnas': ['metT-tRNA[c]', 'metU-tRNA[c]'],\n")


def _read(path: str) -> tuple[str, str]:
    """(text, destination newline). Preserves CRLF vs LF — see the module docstring."""
    with open(path, "rb") as f:
        blob = f.read()
    nl = "\r\n" if blob.count(b"\r\n") else "\n"
    with open(path, encoding="utf-8") as f:
        return f.read(), nl


def _write(path: str, text: str, nl: str) -> None:
    with open(path, "w", encoding="utf-8", newline=nl) as f:
        f.write(text)


def _has(root: str, rel: str, marker: str):
    path = os.path.join(root, rel)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return marker in f.read()


def build_extension(wcecoli: str, image: str | None = None) -> dict:
    """Compile `_trna_charging.pyx` in the model image, leaving the .so beside the .pyx in the checkout.

    Runs Covert's own build (`cythonize`) rather than reimplementing it. Idempotent: skips when a matching .so
    already exists."""
    import glob
    import subprocess
    pyx = os.path.join(wcecoli, PYX_SOURCE)
    if not os.path.isfile(pyx):
        return {"ok": False, "why": f"{PYX_SOURCE} not installed yet — run the file-copy phase first"}
    existing = glob.glob(os.path.join(wcecoli, "wholecell", "utils", "_trna_charging*.so"))
    if existing:
        return {"ok": True, "built": False, "so": existing[0], "note": "already compiled"}
    image = image or os.environ.get("WCECOLI_DOCKER")
    if not image:
        return {"ok": False, "why": "set WCECOLI_DOCKER to the model image; the extension is compiled inside "
                                    "it (Cython + gcc are present there, so no image rebuild is required)"}
    # Build in a scratch dir INSIDE the container and copy only the .so back. Building in place would leave
    # `build/` and the generated `_trna_charging.c` in the checkout owned by the container's uid.
    utils = os.path.join(os.path.abspath(wcecoli), "wholecell", "utils").replace("\\", "/")
    cmd = ["docker", "run", "--rm", "-v", f"{utils}:/mnt/utils", image, "python", "-c", BUILD_SCRIPT]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    built = glob.glob(os.path.join(wcecoli, "wholecell", "utils", "_trna_charging*.so"))
    return {"ok": bool(built), "built": bool(built), "so": (built[0] if built else None),
            "returncode": r.returncode, "tail": (r.stdout or r.stderr or "")[-400:]}


def status(wcecoli: str) -> dict:
    """Per-item state. Each has its OWN marker so a partial port reports as partial."""
    flat = os.path.join(wcecoli, "reconstruction", "ecoli", "flat")
    return {
        "relation_methods": _has(wcecoli, REL, "_build_codon_dependent_trna_charging"),
        "relation_imports": _has(wcecoli, REL, "import warnings"),
        "relation_cistron_fix": _has(wcecoli, REL, "parsed from ITS OWN GENE"),
        "relation_keeps_mismatches": _has(wcecoli, REL, "codon_sequence_mismatches"),
        "relation_trna_space": _has(wcecoli, REL, "uncharged_trna_names)"),
        "relation_guards": _has(wcecoli, REL, "EXT-PORT-7"),
        "monomer_cleavage_column": _has(wcecoli, TRL, "'cleavage_of_initial_methionine', 'bool'"),
        "base_model_members": _has(wcecoli, PE, "def next_amino_acids"),
        "relation_init": _has(wcecoli, REL, "self._build_trna_charging_kinetics(raw_data, sim_data)"),
        "groups_codons": _has(wcecoli, MG, "'codons': codon_ids"),
        "groups_initiators": _has(wcecoli, MG, "'initiator_trnas'"),
        "ids_start_codon": _has(wcecoli, MI, "'start_codon'"),
        "simdata_codon_read_rate": _has(wcecoli, SD, "codon_read_rate"),
        "kb_kinetics_registered": _has(wcecoli, KB, '"trna_charging_kinetics.tsv"'),
        "kb_optimization_registered": _has(wcecoli, KB, "trna_charging_kinetics_constants.tsv"),
        "pyx_installed": os.path.isfile(os.path.join(wcecoli, PYX_SOURCE)),
        "extension_compiled": bool(__import__("glob").glob(
            os.path.join(wcecoli, "wholecell", "utils", "_trna_charging*.so"))),
        "pe_import": _has(wcecoli, PE, "wholecell.utils._trna_charging"),
        "pe_classes": _has(wcecoli, PE, "class KineticTrnaChargingModel"),
        "pe_selector": _has(wcecoli, PE, "kinetic_trna_charging = getattr"),
        "pe_guard": _has(wcecoli, PE, "if not (trna_charging or kinetic_trna_charging):"),
        "listener_installed": os.path.isfile(os.path.join(wcecoli, LIS)),
        "listener_registered": _has(wcecoli, MSIM, "TrnaCharging"),
        "runtime_trna_space": (_has(wcecoli, PE, "free_trnas = list(transcription.uncharged")
                               and _has(wcecoli, LIS, "transcription.uncharged_trna_names")),
        # NOTE: the EXT-PORT-8 GATE (a NotImplementedError refusing --kinetic-trna-charging) is
        # RETIRED, not missing. EXT-PORT-10 made the codon-aware path actually run, so the gate
        # would now refuse a working model. It is no longer applied and no longer checked; the
        # anchor GATE_OLD/GATE_NEW pair is kept below only as the record of what it was.
        "sim_flags": _has(wcecoli, WSIM, "kinetic_trna_charging = False"),
        "flags_mutually_exclusive": _has(wcecoli, WSIM, "elongation flags are MUTUALLY EXCLUSIVE"),
        "cli_flags": _has(wcecoli, SB, "'kinetic_trna_charging'"),
        "firetasks_wired": all(_has(wcecoli, f, "kinetic_trna_charging") for f in FIRETASKS),
        "setup_registered": _has(wcecoli, SETUP, "_trna_charging.pyx"),
        # True only when NEITHER ported file still carries the removed alias.
        "numpy_aliases_modernised": (_has(wcecoli, REL, "class Relation") is not None and not any(
            _has(wcecoli, f, NP_ALIAS_OLD) for f in NP_ALIAS_FILES)),
        # EXT-PORT-10, applied by scripts/ext_port_10_patch.py. Four markers, one per item, so a partial
        # application of THAT script reports as partial here too rather than as done.
        "ext_port_10": all([
            # (1) phnE1 typed 'pseudo' -- changes the DEFAULT path, see that module's docstring
            bool(_has(wcecoli, os.path.join("reconstruction", "ecoli", "flat", "rnas.tsv"),
                      "EXT-PORT-10: EG11283_RNA (phnE1) typed 'pseudo'")),
            # (2) codon_sequences padded for the wider window, buffer constant shared with the process
            bool(_has(wcecoli, REL, "KINETIC_TRNA_CHARGING_WIDTH_BUFFER")),
            bool(_has(wcecoli, PE, "EXT-PORT-10 tripwire")),
            # (3) next_amino_acids implemented on both codon-aware models
            bool(_has(wcecoli, PE, "EXT-PORT-10: the codon-space implementation")),
            bool(_has(wcecoli, PE, "EXT-PORT-10: amino-acid space here")),
            # (4) listener columns with no writer, and the turnover divide
            bool(_has(wcecoli, LIS, "EXT-PORT-10: NO WRITER EXISTS")),
            bool(_has(wcecoli, PE, "EXT-PORT-10: turnover is UNDEFINED")),
            ]),
        # EXT-PORT-11, applied by scripts/ext_port_11_patch.py. Six markers, one per file, so a
        # partial application of THAT script reports as partial here rather than as done.
        "ext_port_11": all([
            # the anchor: a named registry with provenance, and the objective lifted out of its
            # closure so it can be regression-tested
            bool(_has(wcecoli, REL, "TRNA_CHARGED_FRACTION_TARGETS")),
            bool(_has(wcecoli, REL, "def trna_charging_objective")),
            bool(_has(wcecoli, REL, "print_optimization = False")),
            # the blocker: sim_data.codon_read_rate finally has a producer
            bool(_has(wcecoli, FSD, "codon_read_rate = np.log(2) / doubling_time * c_codons")),
            # the Parca step and its flag
            bool(_has(wcecoli, FSD, "def optimize_trna_charging_kinetics(sim_data, cell_specs")),
            bool(_has(wcecoli, SB, "'trna_charged_fraction_target',")),
            bool(_has(wcecoli, SD, "EXT-PORT-11: now POPULATED")),
            # both Firetasks -- Fireworks RAISES on an unknown kwarg, so a half-wired pair breaks
            # every Parca, not only the refitting one
            bool(_has(wcecoli, PARCA_TASK, "trna_charged_fraction_target")),
            bool(_has(wcecoli, FITSIMDATA_TASK, "trna_charged_fraction_target")),
            ]),
        "flat_files": {f: os.path.isfile(os.path.join(flat, f)) for f in FLAT_FILES},
    }


def _complete(st: dict) -> bool:
    return all(v is True for k, v in st.items() if k != "flat_files") and all(st["flat_files"].values())


def apply_port(wcecoli: str, reference: str | None, check: bool = False,
               image: str | None = None) -> dict:
    st = status(wcecoli)
    if check or _complete(st):
        return {"ok": _complete(st), "status": st, "wrote": [],
                "next": ("nothing to do — fully applied" if _complete(st) else
                         "run without --check, with --reference <v3.0.1 tree>")}
    if not reference or not os.path.isfile(os.path.join(reference, REL)):
        return {"ok": False, "status": st, "wrote": [],
                "why": f"need --reference pointing at a v3.0.1 tree containing {REL}. Obtain it from "
                       f"https://zenodo.org/records/7859480 — this repo deliberately does not vendor it."}
    wrote: list[str] = []

    # 1) relation.py: append the 7 methods, then extend __init__
    ref, _ = _read(os.path.join(reference, REL))
    txt, nl = _read(os.path.join(wcecoli, REL))
    if not st["relation_methods"]:
        marker = "\tdef _build_codon_sequences"
        if marker not in ref:
            return {"ok": False, "why": f"reference {REL} has no {marker!r} — wrong version?"}
        txt = txt.rstrip("\n") + "\n\n" + ref[ref.index(marker):]
        wrote.append("relation.py: 7 methods")
    if not st["relation_init"]:
        anchor = "\t\tself._build_tf_to_RNA_mapping(raw_data, sim_data)\n"
        if txt.count(anchor) != 1:
            return {"ok": False, "why": f"expected exactly 1 __init__ anchor in {REL}, found "
                                        f"{txt.count(anchor)} — refusing to guess placement"}
        # Carry the attribution into the model source itself, not only into this script — someone reading
        # relation.py should see where these four calls came from without having to go looking.
        txt = txt.replace(anchor, anchor + ATTRIBUTION + "".join(
            f"\t\tself._build_{m}(raw_data, sim_data)\n" for m in INIT_CALLS), 1)
        wrote.append("relation.py: __init__ calls")
    if not st["relation_imports"]:
        if txt.count(REL_IMPORT_ANCHOR) != 1:
            return {"ok": False, "why": f"{REL}: expected exactly one {REL_IMPORT_ANCHOR.strip()!r} to anchor "
                                        f"the ported methods' imports on"}
        txt = txt.replace(REL_IMPORT_ANCHOR, REL_IMPORT_ANCHOR + REL_IMPORTS, 1)
        wrote.append("relation.py: 7 imports the ported methods need")
    if not st["relation_keeps_mismatches"]:
        for old, new in ((REL_INIT_OLD, REL_INIT_NEW), (REL_SKIP_OLD, REL_SKIP_NEW),
                         (REL_ACC_OLD, REL_ACC_NEW)):
            if txt.count(old) != 1:
                return {"ok": False, "why": f"{REL}: expected exactly one {old.strip()[:40]!r}, "
                                            f"found {txt.count(old)}"}
            txt = txt.replace(old, new, 1)
        wrote.append("relation.py: record mRNA/protein mismatches instead of dropping the monomer")
    if not st["relation_guards"]:
        for old, new in ((REL_OVERLOAD_OLD, REL_OVERLOAD_NEW), (REL_WEIGHTS_OLD, REL_WEIGHTS_NEW)):
            if txt.count(old) != 1:
                return {"ok": False, "why": f"{REL}: expected exactly one {old.strip()[:44]!r}, "
                                            f"found {txt.count(old)}"}
            txt = txt.replace(old, new, 1)
        wrote.append("relation.py: guards for unassigned codons and the amino-acid ordering cross")
    if not st["relation_trna_space"]:
        if txt.count(REL_TRNA_OLD) != 1:
            return {"ok": False, "why": f"{REL}: expected exactly one TU-space tRNA block to redirect at "
                                        f"uncharged_trna_names, found {txt.count(REL_TRNA_OLD)}"}
        txt = txt.replace(REL_TRNA_OLD, REL_TRNA_NEW, 1)
        wrote.append("relation.py: tRNAs addressed in cistron space (uncharged_trna_names)")
    if not st["relation_cistron_fix"]:
        if txt.count(REL_CISTRON_OLD) != 1:
            return {"ok": False, "why": f"{REL}: expected exactly one TU-indexed rna_sequences lookup to "
                                        f"redirect at cistron_data, found {txt.count(REL_CISTRON_OLD)}"}
        txt = txt.replace(REL_CISTRON_OLD, REL_CISTRON_NEW, 1)
        wrote.append("relation.py: rna_data -> cistron_data in _build_codon_sequences")
    if wrote:
        _write(os.path.join(wcecoli, REL), txt, nl)

    # 2) molecule_groups.py: the codon loop + three group entries
    if not st["groups_codons"] or not st["groups_initiators"]:
        t, n2 = _read(os.path.join(wcecoli, MG))
        a_dict = "\t\tmolecule_groups = {\n"
        a_aa = "\t\t\t'amino_acids': aa_ids,\n"
        if t.count(a_dict) != 1 or t.count(a_aa) != 1:
            return {"ok": False, "why": f"{MG}: expected one molecule_groups dict and one 'amino_acids' entry"}
        if "codon_ids = []" not in t:
            t = t.replace(a_dict, CODON_BUILD + a_dict, 1)
        if "'codons': codon_ids" not in t:
            t = t.replace(a_aa, a_aa + GROUP_ENTRIES, 1)
        _write(os.path.join(wcecoli, MG), t, n2)
        wrote.append("molecule_groups.py: codons + initiator/elongator tRNAs")

    # 3) molecule_ids.py
    if not st["ids_start_codon"]:
        t, n2 = _read(os.path.join(wcecoli, MI))
        m = re.search(r"\n(\t\t\t'[a-z_0-9]+': [^\n]+,\n)", t)
        if not m:
            return {"ok": False, "why": f"{MI}: no dict-entry pattern to anchor on"}
        _write(os.path.join(wcecoli, MI),
               t[:m.end(1)] + "\t\t\t'start_codon': 'start',\n" + t[m.end(1):], n2)
        wrote.append("molecule_ids.py: start_codon")

    # 4) simulation_data.py
    if not st["simdata_codon_read_rate"]:
        t, n2 = _read(os.path.join(wcecoli, SD))
        a = "\t\tself.translation_supply_rate = {}\n"
        if t.count(a) != 1:
            return {"ok": False, "why": f"{SD}: expected one translation_supply_rate anchor"}
        _write(os.path.join(wcecoli, SD), t.replace(
            a, a + "\t\t# Populated by the kinetic tRNA charging model; empty under the default\n"
                   "\t\t# SteadyStateElongationModel, which never reads it.\n"
                   "\t\tself.codon_read_rate = {}\n", 1), n2)
        wrote.append("simulation_data.py: codon_read_rate")

    # 5) knowledge_base_raw.py — WITHOUT this the flat files are invisible
    if not st["kb_kinetics_registered"] or not st["kb_optimization_registered"]:
        t, n2 = _read(os.path.join(wcecoli, KB))
        for anchor, lines in REGISTRATIONS:
            a = "\t" + anchor + "\n"
            if a in t and lines[0] not in t:
                t = t.replace(a, "".join("\t" + ln + "\n" for ln in lines) + a, 1)
        _write(os.path.join(wcecoli, KB), t, n2)
        wrote.append("knowledge_base_raw.py: registered the flat files")

    # 6) the flat files themselves
    dst_flat = os.path.join(wcecoli, "reconstruction", "ecoli", "flat")
    src_flat = os.path.join(reference, "reconstruction", "ecoli", "flat")
    for f in FLAT_FILES:
        d = os.path.join(dst_flat, f)
        if os.path.isfile(d):
            continue
        s = os.path.join(src_flat, f)
        if not os.path.isfile(s):
            return {"ok": False, "why": f"reference is missing flat file {f}"}
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copyfile(s, d)
        wrote.append(f"flat/{f}")

    # 7) the Cython source, and 8) its compiled extension. `polypeptide_elongation.py` imports from
    #    `wholecell.utils._trna_charging` at MODULE level, so without the .so the kinetic model is an
    #    ImportError at sim start — after ParCa, after the container is up, minutes into a run.
    if not st["pyx_installed"]:
        s = os.path.join(reference, PYX_SOURCE)
        if not os.path.isfile(s):
            return {"ok": False, "why": f"reference is missing {PYX_SOURCE}"}
        shutil.copyfile(s, os.path.join(wcecoli, PYX_SOURCE))
        wrote.append(PYX_SOURCE)
    # EXT-PORT-12 (BACKLOG UNIFY-2 gate): the reference .pyx seeds the C stdlib RNG from the WALL
    # CLOCK -- `cdef time_t t = time(NULL); srand(t)` at the head of reconcile_via_ribosome_positions
    # and reconcile_via_trna_pools. Copied verbatim, it makes every kinetic simulation
    # NON-REPRODUCIBLE: measured, two runs with identical --seed 0 on the same knowledge base matched
    # in only 82 of 254 comparable listener columns and were 0.51% apart on Mass/cellMass at
    # division. With the fix (an explicit `seed` argument drawn from the process RandomState) the
    # same pair is bit-identical in all 224 comparable columns.
    #
    # This check is here because the guard above is `os.path.isfile`, so the copy is skipped on an
    # already-ported tree and the fix survives -- but on a FRESH tree the vendor file lands unpatched
    # and nothing downstream would notice. A non-reproducible tree that runs is precisely the failure
    # this project keeps being bitten by, so it gets announced rather than discovered later.
    _pyx_text, _ = _read(os.path.join(wcecoli, PYX_SOURCE))
    if "srand(t)" in _pyx_text or "time(NULL)" in _pyx_text:
        msg = (f"EXT-PORT-12 NOT APPLIED: {PYX_SOURCE} still seeds the C RNG from the wall clock"
               " (srand(time(NULL))). The kinetic elongation path in this tree is NOT reproducible"
               " across runs with the same --seed, and no ppGpp / isoacceptor comparison built on it"
               " is interpretable. Apply the EXT-PORT-12 edits (see BACKLOG UNIFY-2) before running"
               " any comparison.")
        print("\n!! " + msg + "\n")
        wrote.append("WARNING: " + msg)
    if not st["extension_compiled"]:
        b = build_extension(wcecoli, image=image)
        wrote.append(f"cython extension: {b}")

    # 9) polypeptide_elongation.py — the two kinetic elongation models plus their wiring
    if not (st["pe_import"] and st["pe_classes"] and st["pe_selector"] and st["pe_guard"]):
        pref, _ = _read(os.path.join(reference, PE))
        t, n2 = _read(os.path.join(wcecoli, PE))
        if not st["pe_import"]:
            if t.count(PE_IMPORT_ANCHOR) != 1:
                return {"ok": False, "why": f"{PE}: expected one {PE_IMPORT_ANCHOR.strip()!r} import anchor"}
            t = t.replace(PE_IMPORT_ANCHOR, PE_IMPORT_ANCHOR + PE_IMPORT, 1)
        if not st["pe_classes"]:
            head = "class KineticTrnaChargingModel"
            if head not in pref:
                return {"ok": False, "why": f"reference {PE} has no {head!r} — wrong version?"}
            t = t.rstrip("\n") + "\n\n\n" + pref[pref.index(head):]
        if not st["pe_selector"]:
            for old, new in ((PE_FLAGS_ANCHOR, PE_FLAGS_ANCHOR + PE_FLAGS),
                             (PE_SELECT_OLD, PE_SELECT_NEW)):
                if t.count(old) != 1:
                    return {"ok": False, "why": f"{PE}: expected exactly one {old.strip()[:48]!r}, "
                                                f"found {t.count(old)} — refusing to guess"}
                t = t.replace(old, new, 1)
        if not st["pe_guard"]:
            if t.count(PE_GUARD_OLD) != 1:
                return {"ok": False, "why": f"{PE}: expected exactly one charging guard to widen"}
            t = t.replace(PE_GUARD_OLD, PE_GUARD_NEW, 1)
        _write(os.path.join(wcecoli, PE), t, n2)
        wrote.append("polypeptide_elongation.py: import + 2 kinetic models + selector + guard")

    # 9c) the EXT-PORT-8 prerequisites
    if not st["monomer_cleavage_column"]:
        t, n2 = _read(os.path.join(wcecoli, TRL))
        for old, new in TRL_EDITS:
            o, n = old.replace("\n", n2), new.replace("\n", n2)
            if t.count(o) != 1:
                return {"ok": False, "why": f"{TRL}: expected exactly one {old.strip()[:44]!r}, "
                                            f"found {t.count(o)}"}
            t = t.replace(o, n, 1)
        _write(os.path.join(wcecoli, TRL), t, n2)
        wrote.append("translation.py: monomer_data['cleavage_of_initial_methionine']")
    if not st["base_model_members"]:
        t, n2 = _read(os.path.join(wcecoli, PE))
        for old, new in list(PE_BASE_EDITS) + [(PE_METHOD_ANCHOR, PE_METHOD_NEW)]:
            o, n = old.replace("\n", n2), new.replace("\n", n2)
            if t.count(o) != 1:
                return {"ok": False, "why": f"{PE}: expected exactly one {old.strip()[:44]!r}, "
                                            f"found {t.count(o)}"}
            t = t.replace(o, n, 1)
        _write(os.path.join(wcecoli, PE), t, n2)
        wrote.append("polypeptide_elongation.py: BaseElongationModel protein_lengths + next_amino_acids")

    # 9b) the runtime tRNA id space, in BOTH the process and the listener.
    #
    # The EXT-PORT-8 gate that used to be applied here is deliberately NOT applied any more. It
    # raised NotImplementedError for --kinetic-trna-charging while the host process still used the
    # steady-state calling convention; EXT-PORT-10 fixed that, so re-inserting the gate would now
    # refuse a model that works. Running this script against an EXT-PORT-10 tree used to do exactly
    # that, silently, because `status()` reported the (correctly absent) gate as a missing item.
    if not st["runtime_trna_space"]:
        t, n2 = _read(os.path.join(wcecoli, PE))
        for old, new, want in ((PE_TRNA_OLD, PE_TRNA_NEW, st["runtime_trna_space"]),):
            if want:
                continue
            o = old.replace("\n", n2)
            if t.count(o) != 1:
                return {"ok": False, "why": f"{PE}: expected exactly one {old.strip()[:44]!r}, "
                                            f"found {t.count(o)}"}
            t = t.replace(o, new.replace("\n", n2), 1)
        _write(os.path.join(wcecoli, PE), t, n2)
        wrote.append("polypeptide_elongation.py: tRNA cistron space")
        if not st["runtime_trna_space"] and os.path.isfile(os.path.join(wcecoli, LIS)):
            t, n2 = _read(os.path.join(wcecoli, LIS))
            o = LIS_TRNA_OLD.replace("\n", n2)
            if t.count(o) == 1:
                _write(os.path.join(wcecoli, LIS), t.replace(o, LIS_TRNA_NEW.replace("\n", n2), 1), n2)
                wrote.append("listeners/trna_charging.py: tRNA cistron space")

    # 10) the TrnaCharging listener — copied AND registered in one step
    if not st["listener_installed"]:
        s_lis = os.path.join(reference, LIS)
        if not os.path.isfile(s_lis):
            return {"ok": False, "why": f"reference is missing {LIS}"}
        shutil.copyfile(s_lis, os.path.join(wcecoli, LIS))
        wrote.append(LIS)
    if not st["listener_registered"]:
        t, n2 = _read(os.path.join(wcecoli, MSIM))
        if t.count(LIS_IMPORT_ANCHOR) != 1 or t.count(LIS_LIST_ANCHOR) != 1:
            return {"ok": False, "why": f"{MSIM}: expected one RibosomeData import and one list entry to "
                                        f"anchor the TrnaCharging registration on"}
        t = t.replace(LIS_IMPORT_ANCHOR, LIS_IMPORT_ANCHOR + LIS_IMPORT, 1)
        t = t.replace(LIS_LIST_ANCHOR, LIS_LIST_ANCHOR + LIS_LIST, 1)
        _write(os.path.join(wcecoli, MSIM), t, n2)
        wrote.append(f"{MSIM}: registered TrnaCharging")

    # 11) the flags — sim kwargs and the CLI that sets them
    if not st["sim_flags"]:
        t, n2 = _read(os.path.join(wcecoli, WSIM))
        if t.count(WSIM_ANCHOR) != 1:
            return {"ok": False, "why": f"{WSIM}: expected exactly one trna_charging kwarg to anchor on"}
        _write(os.path.join(wcecoli, WSIM), t.replace(WSIM_ANCHOR, WSIM_ANCHOR + WSIM_ADD, 1), n2)
        wrote.append(f"{WSIM}: kinetic_trna_charging / coarse_kinetic_elongation kwargs")
    if not st["flags_mutually_exclusive"]:
        t, n2 = _read(os.path.join(wcecoli, WSIM))
        o = WSIM_RESOLVE_ANCHOR.replace("\n", n2)
        if t.count(o) != 1:
            return {"ok": False, "why": f"{WSIM}: expected exactly one kwargs-unpacking anchor to place the "
                                        f"flag resolution before, found {t.count(o)}"}
        _write(os.path.join(wcecoli, WSIM), t.replace(o, WSIM_RESOLVE.replace("\n", n2) + o, 1), n2)
        wrote.append(f"{WSIM}: kinetic flags force trna_charging / translation_supply False")
    if not st["cli_flags"]:
        t, n2 = _read(os.path.join(wcecoli, SB))
        # Two option LISTS carry every sim flag; both must gain the new names or the CLI value is parsed and
        # then dropped on the way to the sim.
        if t.count(SB_LIST_ANCHOR) != 2 or t.count(SB_OPT_ANCHOR) != 1:
            return {"ok": False, "why": f"{SB}: expected two 'trna_charging' list entries and one option "
                                        f"definition, found {t.count(SB_LIST_ANCHOR)} and "
                                        f"{t.count(SB_OPT_ANCHOR)}"}
        t = t.replace(SB_LIST_ANCHOR, SB_LIST_ANCHOR + SB_LIST_ADD)
        t = t.replace(SB_OPT_ANCHOR, SB_OPT_ANCHOR + SB_OPT_ADD, 1)
        _write(os.path.join(wcecoli, SB), t, n2)
        wrote.append(f"{SB}: --kinetic-trna-charging / --coarse-kinetic-elongation")

    # 11b) the Fireworks firetasks — without this, EVERY run fails, not just the kinetic one
    if not st["firetasks_wired"]:
        for f in FIRETASKS:
            t, n2 = _read(os.path.join(wcecoli, f))
            for old, new in ((FT_LIST_OLD, FT_LIST_NEW), (FT_OPT_OLD, FT_OPT_NEW)):
                o = old.replace("\n", n2)
                if t.count(o) != 1:
                    return {"ok": False, "why": f"{f}: expected exactly one {old.strip()[:40]!r}, "
                                                f"found {t.count(o)}"}
                t = t.replace(o, new.replace("\n", n2), 1)
            _write(os.path.join(wcecoli, f), t, n2)
            wrote.append(f"{f}: kinetic flags added to the firetask allow-list")

    # 12) setup.py — so `make compile` (and therefore any image build) produces the extension
    if not st["setup_registered"]:
        t, n2 = _read(os.path.join(wcecoli, SETUP))
        if t.count(SETUP_ANCHOR) != 1:
            return {"ok": False, "why": f"{SETUP}: expected exactly one {SETUP_ANCHOR!r} anchor"}
        _write(os.path.join(wcecoli, SETUP), t.replace(SETUP_ANCHOR, SETUP_ADD + SETUP_ANCHOR, 1), n2)
        wrote.append("setup.py: registered _trna_charging.pyx with cythonize")

    # 13) removed NumPy aliases in the ported code
    if not st["numpy_aliases_modernised"]:
        for f in NP_ALIAS_FILES:
            t, n2 = _read(os.path.join(wcecoli, f))
            if NP_ALIAS_OLD not in t:
                continue
            n_hits = t.count(NP_ALIAS_OLD)
            _write(os.path.join(wcecoli, f), t.replace(NP_ALIAS_OLD, NP_ALIAS_NEW), n2)
            wrote.append(f"{f}: np.bool -> np.bool_ ({n_hits})")

    # 14) EXT-PORT-10 — the four items that were blocking the codon-aware path.
    #
    # DELEGATED rather than inlined. Those edits are defined ONCE, in scripts/ext_port_10_patch.py, and
    # that module is the only place they live; duplicating ~200 lines of anchors here is how two copies
    # of the same recipe drift apart. It is idempotent and marker-guarded on exactly the same terms as
    # everything above, so calling it from a fully-applied tree is a no-op.
    #
    # ONE OF ITS EDITS IS NOT ADDITIVE. It types EG11283_RNA (phnE1) 'pseudo' in rnas.tsv, which removes
    # one cistron and one monomer from the DEFAULT path as well — a deliberate re-baseline, not a
    # no-op. See that module's docstring for the measured blast radius.
    if not st["ext_port_10"]:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from ext_port_10_patch import run as _ext_port_10_run
        r10 = _ext_port_10_run(wcecoli, os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               check=False)
        if not r10["complete"]:
            return {"ok": False, "status": status(wcecoli), "wrote": wrote,
                    "why": f"EXT-PORT-10 edits did not fully apply: {r10['files']}"}
        wrote.extend(f"EXT-PORT-10 {f}" for f in r10["wrote"])

    # 15) EXT-PORT-11 -- the tRNA charging OPTIMISER, and the charged-fraction anchor.
    #
    # DELEGATED for the same reason EXT-PORT-10 is: those edits are defined ONCE, in
    # scripts/ext_port_11_patch.py, and duplicating ~300 lines of anchors here is how two copies of
    # the same recipe drift apart. That module's anchors were EXTRACTED from a tree that had already
    # been built and verified, and re-applying them to the pre-edit tree reproduces the verified
    # files byte for byte -- so the recipe and the thing that was tested are the same thing.
    #
    # THIS IS THE ONLY PART OF THE PORT THAT CHANGES sim_data ON THE DEFAULT PATH -- and it changes
    # it ADDITIVELY: sim_data.codon_read_rate goes from {} to 25 media x 63 codons, and
    # relation.conditions is set. Measured: rebuilding the knowledge base and diffing 20 fitted
    # structures (rna_expression, rna_synth_prob, monomer_data, trna_to_K_T, codon_sequences, ...)
    # gives 0 changed. But simData.cPickle is NOT byte-identical, so kb_sha256 moves and anything
    # built after this is a new campaign.
    if not st["ext_port_11"]:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from ext_port_11_patch import run as _ext_port_11_run
        r11 = _ext_port_11_run(wcecoli, check=False)
        if not r11["complete"]:
            return {"ok": False, "status": status(wcecoli), "wrote": wrote,
                    "why": f"EXT-PORT-11 edits did not fully apply: {r11['files']}"}
        wrote.extend(f"EXT-PORT-11 {f}" for f in r11["wrote"])

    st2 = status(wcecoli)
    return {"ok": _complete(st2), "status": st2, "wrote": wrote,
            "next": "REBUILD ParCa (`runscripts/manual/runParca.py <newdir> --cpus 4 "
                    "--save-intermediates`), then verify with scripts/verify_trna_objective.py that the "
                    "ported objective still reproduces all 5533 shipped solution rows. This changes "
                    "kb_sha256, so anything it produces is a NEW campaign and is not comparable to the "
                    "existing corpus. The tRNA charging REFIT itself is opt-in and is NOT run by a "
                    "default Parca -- see --optimize-trna-charging-kinetics."}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--wcecoli", default=os.environ.get("WCECOLI_DIR", "C:/dev/wcEcoli"))
    ap.add_argument("--reference", default=os.environ.get("WCECOLI_V301", "vendor/v301"))
    ap.add_argument("--check", action="store_true", help="report only; write nothing")
    ap.add_argument("--image", default=os.environ.get("WCECOLI_DOCKER"),
                    help="model image used to COMPILE the Cython extension. No image rebuild is needed — the "
                         "existing image already carries Cython and gcc.")
    a = ap.parse_args(argv)
    res = apply_port(a.wcecoli, a.reference, check=a.check, image=a.image)
    if res.get("why"):
        print(f"ERROR: {res['why']}")
    for k, v in (res.get("status") or {}).items():
        if k == "flat_files":
            miss = [f for f, present in v.items() if not present]
            print(f"  flat_files: {len(v) - len(miss)}/{len(v)} present" + (f"; missing {miss}" if miss else ""))
        else:
            print(f"  {k}: {v}")
    if res.get("wrote"):
        print("applied:")
        for w in res["wrote"]:
            print(f"    + {w}")
    print(f"\nok={res.get('ok')}\n{res.get('next', '')}")
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
