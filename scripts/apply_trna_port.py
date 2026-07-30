"""EXT-PORT — apply the kinetic tRNA charging port (per-isoacceptor) to a wcEcoli checkout.

Source: CovertLab/WholeCellEcoliRelease **v3.0.1** — Choi & Covert 2023, *NAR* 51(12):5911,
doi:10.1093/nar/gkad435. Applied with permission from Prof. Covert.

**This applies FROM A REFERENCE TREE and deliberately does not embed the ported code.** Two reasons.
Practically, it is ~1155 lines of `relation.py` plus four smaller edits; inlining that would make the script
unreadable and would drift from upstream invisibly. Legally, the licence position is unresolved — the Zenodo
record states CC-BY-NC-4.0 while the in-repo `LICENSE.md` at tag v3.0.1 is the Stanford Academic Software
License S18-475, which grants a NONTRANSFERABLE licence and says nothing permitting redistribution. Recording
the PROCEDURE keeps Covert-lab code out of this public repo while leaving the port fully reproducible by anyone
who obtains v3.0.1 themselves.

Get the reference, then point `--reference` at it:

    https://zenodo.org/records/7859480
    # or: git clone --branch v3.0.1 https://github.com/CovertLab/WholeCellEcoliRelease

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
        "sim_flags": _has(wcecoli, WSIM, "kinetic_trna_charging = False"),
        "cli_flags": _has(wcecoli, SB, "'kinetic_trna_charging'"),
        "setup_registered": _has(wcecoli, SETUP, "_trna_charging.pyx"),
        # True only when NEITHER ported file still carries the removed alias.
        "numpy_aliases_modernised": (_has(wcecoli, REL, "class Relation") is not None and not any(
            _has(wcecoli, f, NP_ALIAS_OLD) for f in NP_ALIAS_FILES)),
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

    st2 = status(wcecoli)
    return {"ok": _complete(st2), "status": st2, "wrote": wrote,
            "next": "REBUILD ParCa, then compare the relation structures against the v3.0.1 reference by shape "
                    "AND content before wiring anything to the ODE. This changes kb_sha256, so anything it "
                    "produces is a NEW campaign and is not comparable to the existing corpus."}


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
