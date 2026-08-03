"""SUPERSEDED by the overlay (scripts/apply_model_overlay.py). Kept as the GENERATOR OF RECORD, not
as an install path.

DO NOT use this to set up a wcEcoli checkout. Use:

    python scripts/apply_model_overlay.py --wcecoli /path/to/wcEcoli

MEASURED, against upstream a4497e17 on a stock checkout: this recipe aborted FOUR separate times and
therefore replayed on NO committed tree. The only place it had ever fully run was one working copy
that had been hand-patched incrementally. The four defects are recorded, and fixed, in
docs/OVERLAY.md; the recipe now completes, which is what made the overlay harvestable at all. But it
still cannot produce the full port -- EXT-PORT-12 (UNIFY-2) has no applier of any kind -- so what it
emits is a subset, not the shipped tree.

Why keep it. Deleting it would make the overlay unauditable: a reviewer could no longer see how the
v3.0.1 code was adapted, only that some bytes are vendored. The ADAPTATIONS are the part worth
reading and they are recorded here.

EXT-PORT-10 — close the four items blocking the codon-aware (kinetic tRNA charging) path.

Idempotent, marker-guarded, and CRLF/TAB preserving, in the style of scripts/apply_trna_port.py.
Every anchor is asserted to match EXACTLY ONCE before anything is written; a partial application
reports as partial rather than as done.

    python ext_port_10_patch.py --wcecoli C:/dev/wcEcoli --check
    python ext_port_10_patch.py --wcecoli C:/dev/wcEcoli [--cellarium C:/dev/anthropic_hackathon]

THE FOUR ITEMS
--------------

(1) phnE1 / PHNE-MONOMER — rnas.tsv types EG11283_RNA 'pseudo', matching v3.0.1 and the biology.
    In K-12 MG1655 the phosphonate operon is cryptic: phnE carries an 8-bp insertion that breaks the
    frame, and the curated "protein sequence" in proteins.tsv is the conceptual translation of a
    pseudogene — it CONTAINS STOP CODONS, and the naive translation of the gene matches it 278/278
    positions INCLUDING the asterisks. So the codon sequence (206 real codons, truncated at the first
    stop) is shorter than monomer_data['length'] (275), which is what the guard in
    PolypeptideElongation.initialize refuses to run against.

    THIS IS A DELIBERATE RE-BASELINE, NOT A NO-OP. It changes the DEFAULT path too:
      * cistron_data 4539 -> 4538, monomer_data 4310 -> 4309. rna_data stays 3276 with identical ids,
        so every ko_index survives — EG11283_RNA is not its own rna_data row, it lives inside
        TU00201[c] with phnC/phnD/phnF/phnG and nine more.
      * phnE1's own expression is ~2e-8 of the transcriptome, so the direct renormalisation of every
        other cistron is ~1.7e-6.
      * BUT transcription.py estimates unmeasured TU degradation rates with a GLOBAL fast_nnls over
        the whole cistron x TU abundancy matrix, and removing one row flips a degenerate tie in that
        solve. The largest movers are NOT phn: fur (TU0-1283) and tnaC (TU0-42514) swap degradation
        rates, and uof-fur (TU0-1281) moves ~20x. That is a solver tie-break, not biology, and it is
        in the default path — see the measured before/after in the run report.
      * 3291/4538 cistron row indices and 413/4309 monomer row indices shift, so any STORED POSITIONAL
        INDEX outside transcription-unit space is invalidated. ko_index_map.json, runs/_gene_scope.json
        and runs/_sym2cistron.json must be REGENERATED (phnE1 loses its key), not hand-edited.

(2) Codon-sequence width. relation.py padded codon_sequences by max_time_step * R_max (= 30) while the
    kinetic window is ceil(max_time_step * R_basal) + buffer (= 32), and — unlike translation.py — it
    omitted next_aa_pad. Closed form of the deficit:

        deficit = ceil(m*R_basal) + B - 1 - m*R_max
        ours   (m=1.0): 22 + 10 - 1 - 30 = +1   (short by exactly one column)
        v3.0.1 (m=2.0): 44 + 10 - 1 - 60 = -7   (seven spare)

    The port halved MAX_TIME_STEP (2.0 -> 1.0), which halved the pad 60 -> 30 but only shrank the
    window 54 -> 32, because 10 of that window (the reconciliation buffer) is dt-independent.
    Exposure is one monomer at one position: G7064-MONOMER[o] (yeeJ, 2339 aa) at peptide_length 2338,
    2338 + 32 = 2370 > 2369. Measured hazard ~1.5e-5/s, i.e. ~1 lost lineage per ~25 generations —
    loud, but not rare enough to file as a nuisance.

    The fix widens the pad to cover the WIDER of the two windows and restores next_aa_pad, and couples
    the two numbers that had drifted apart: KINETIC_TRNA_CHARGING_WIDTH_BUFFER now lives in relation.py
    (where the pad is computed) and is IMPORTED by polypeptide_elongation.py (where the window is
    computed). A tripwire assert in PolypeptideElongation.initialize re-derives the same inequality.

    An assert alone was rejected: to cover the hazard it must fire whenever dt > 0.954 s, and dt is
    1.0 s in every configuration this tree permits — it would refuse 100% of kinetic runs. Widening
    supplies the missing data; an assert only converts an honest crash into a refusal.

(3) next_amino_acids. BaseElongationModel returns a hard-coded 0 and nothing overrode it on either
    codon-aware model. Its only consumer is ppgpp_metabolite_changes, whose call site says the next
    amino acid must be included "otherwise f will be NaN" on a zero-elongation timestep. Harmless
    today only because ppGpp is not computed on the codon-aware path. Implemented here for both
    codon-aware models. For KineticTrnaChargingModel the sequences are CODON space (63), so a verbatim
    bincount(minlength=21) would return a 63-long array; it must count in codon space and project
    through relation.codons_to_amino_acids to 21.

(4) TrnaCharging listener columns with no writer. collision_removed_ribosomes_argA and
    ribosome_initiation_argA are allocated and appended but never written in this tree, so they log as
    zeros — which an analyst would read as "no collisions occurred". They are DOCUMENTED rather than
    dropped: the listener is registered unconditionally (models/ecoli/sim/simulation.py:103), so
    dropping the columns would change the output schema of every DEFAULT run as well, and any reader
    expecting the column would break. The note is written into the table's own attributes so it
    travels with the data instead of living only in source.
    Related: TrnaCharging/turnover divided by a possibly-empty charged pool, producing NaN/inf plus a
    RuntimeWarning. NaN is the right value (turnover is undefined with no charged tRNA) but it is now
    produced DELIBERATELY and documented, rather than as an arithmetic accident.

WHAT THIS SCRIPT DOES NOT DO
----------------------------
It does not touch the codon_sequence_mismatches guard in PolypeptideElongation.initialize. With
EG11283_RNA typed 'pseudo', PHNE-MONOMER leaves monomer_data entirely and the list is empty, so the
guard is INERT — and an inert guard is exactly the tripwire that should stay. Removing it would delete
the protection against the next monomer that acquires the same defect.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys

RNAS = os.path.join("reconstruction", "ecoli", "flat", "rnas.tsv")
REL = os.path.join("reconstruction", "ecoli", "dataclasses", "relation.py")
PE = os.path.join("models", "ecoli", "processes", "polypeptide_elongation.py")
LIS = os.path.join("models", "ecoli", "listeners", "trna_charging.py")
PROBE = os.path.join("scripts", "probe_relation.py")


# --------------------------------------------------------------------------------------------------
# (1) phnE1: type EG11283_RNA 'pseudo'
# --------------------------------------------------------------------------------------------------
# reconstruction/spreadsheets.py:comment_line filters '#' lines ANYWHERE in the stream (filterfalse
# over the whole file handle, not just a leading block), so the provenance note sits next to the row
# it explains rather than in a header far away.
E1_MARK = "EXT-PORT-10: EG11283_RNA (phnE1) typed 'pseudo'"
E1_OLD = ('"EG11283_RNA"\t"phnE1"\t["phnE1", "ECK4097", "b4103", "b4104", "b4583", "ECK4096"]\t'
          '"mRNA"\t[]\t"EG11283"\t["PHNE-MONOMER"]\tnull\t[]')
E1_NEW = (
    "# EXT-PORT-10: EG11283_RNA (phnE1) typed 'pseudo', matching WholeCellEcoliRelease v3.0.1 and the\n"
    "# biology. In K-12 MG1655 the phosphonate operon is cryptic: phnE carries an 8-bp insertion that\n"
    "# breaks the reading frame, and the gene record still shows the scar (one gene, synonyms\n"
    "# b4103/b4104/b4583/ECK4096/ECK4097). The curated PHNE-MONOMER 'seq' in proteins.tsv CONTAINS\n"
    "# STOP CODONS -- the naive translation of the gene matches it 278/278 positions INCLUDING the\n"
    "# asterisks -- so it is the conceptual translation of a pseudogene, not a protein. Typing it\n"
    "# 'mRNA' put a 275-residue monomer in translation whose real ORF is 206 codons.\n"
    "# NOT A NO-OP: this removes one cistron (4539->4538) and one monomer (4310->4309) from the\n"
    "# DEFAULT path too. rna_data is unchanged at 3276 rows with identical ids (EG11283_RNA lives\n"
    "# inside TU00201[c]), so ko_index space survives, but cistron and monomer ROW INDICES shift and\n"
    "# the global fast_nnls that estimates unmeasured TU degradation rates re-solves. See the\n"
    "# EXT-PORT-10 note in scripts/apply_trna_port.py and docs/DECISIONS.md.\n"
    + E1_OLD.replace('\t"mRNA"\t', '\t"pseudo"\t'))


# --------------------------------------------------------------------------------------------------
# (2) codon-sequence width
# --------------------------------------------------------------------------------------------------
E2_MARK = "KINETIC_TRNA_CHARGING_WIDTH_BUFFER"
E2_ANCHOR = "from wholecell.utils.polymerize import polymerize\n"
E2_NEW = (
    "from wholecell.utils.polymerize import polymerize\n"
    "\n"
    "# EXT-PORT-10: the reconciliation buffer of KineticTrnaChargingModel, defined HERE because this is\n"
    "# the file that has to pad codon_sequences wide enough to contain it. It is imported by\n"
    "# models/ecoli/processes/polypeptide_elongation.py rather than repeated as a literal.\n"
    "#\n"
    "# The decoupling WAS the bug. The pad lived only in the knowledge base and the buffer only in the\n"
    "# process, so halving MAX_TIME_STEP (2.0 -> 1.0 in this tree) halved the pad 60 -> 30 while the\n"
    "# window only fell 54 -> 32, because this term is dt-independent. Deficit in closed form:\n"
    "#     ceil(m*R_basal) + B - 1 - m*R_max\n"
    "#     m=1.0 (ours):   22 + 10 - 1 - 30 = +1   -> buildSequences IndexError on yeeJ at position 2338\n"
    "#     m=2.0 (v3.0.1): 44 + 10 - 1 - 60 = -7   -> seven spare columns\n"
    "KINETIC_TRNA_CHARGING_WIDTH_BUFFER = 10\n")

E3_MARK = "EXT-PORT-10: pad for the WIDER of the two windows"
E3_OLD = (
    "\t\tmax_len = np.int64(\n"
    "\t\t\t# Length of the open reading frame\n"
    "\t\t\t+ translation.monomer_data['length'].asNumber().max()\n"
    "\n"
    "\t\t\t# Max number of anticipated readings\n"
    "\t\t\t+ (translation.max_time_step\n"
    "\t\t\t\t* sim_data.constants.ribosome_elongation_rate_max.asNumber(\n"
    "\t\t\t\t\tunits.aa / units.s)))\n")
E3_NEW = (
    "\t\t# EXT-PORT-10: pad for the WIDER of the two windows that read this array, plus next_aa_pad.\n"
    "\t\t#\n"
    "\t\t# Upstream padded by max_time_step * R_max only. TWO readers disagree with that:\n"
    "\t\t#   coarse  buildSequences(..., elongation_rates + next_aa_pad)   -> m*R_max + 1  = 31\n"
    "\t\t#   kinetic KineticTrnaChargingModel.elongation_rate / codon_sequences_width\n"
    "\t\t#           ceil(m*R_basal) + KINETIC_TRNA_CHARGING_WIDTH_BUFFER  -> 22 + 10     = 32\n"
    "\t\t# buildSequences raises iff position + width > ncol, and the maximum reachable position is\n"
    "\t\t# L_max - 1 = 2338 (a ribosome is deleted the step it reaches its terminal length; only MAP\n"
    "\t\t# substrates can sit at L, and the longest of those is 1320 aa). The old pad gave ncol 2369:\n"
    "\t\t# the coarse read passed with EXACTLY ZERO margin and the kinetic read overran by one column,\n"
    "\t\t# on one monomer, G7064-MONOMER[o] (yeeJ, 2339 aa).\n"
    "\t\t#\n"
    "\t\t# Do NOT 'restore' the upstream expression: it is correct only while max_time_step >= 1.2 s.\n"
    "\t\t# v3.0.1 ran at 2.0 s and had seven spare columns; this tree runs at 1.0 s and was short by one.\n"
    "\t\t# Cost of the fix is 3 columns = 12.9 kB (+0.127%) on a (4310, 2369) int8 array.\n"
    "\t\tcoarse_window = (translation.max_time_step\n"
    "\t\t\t* sim_data.constants.ribosome_elongation_rate_max.asNumber(units.aa / units.s))\n"
    "\t\tkinetic_window = np.ceil(translation.max_time_step\n"
    "\t\t\t* sim_data.constants.ribosome_elongation_rate_basal.asNumber(units.aa / units.s)\n"
    "\t\t\t+ KINETIC_TRNA_CHARGING_WIDTH_BUFFER)\n"
    "\t\tmax_len = np.int64(\n"
    "\t\t\t# Length of the open reading frame\n"
    "\t\t\t+ translation.monomer_data['length'].asNumber().max()\n"
    "\n"
    "\t\t\t# Max number of anticipated readings, by whichever elongation model reads widest\n"
    "\t\t\t+ max(coarse_window, kinetic_window)\n"
    "\n"
    "\t\t\t# ...and the extra position translation.py:317 pads for, which this expression omitted.\n"
    "\t\t\t# _evolveState_codon_aware indexes all_sequences at [i, sequence_elongations[i]] to find\n"
    "\t\t\t# the NEXT residue, one past the last one elongated.\n"
    "\t\t\t+ translation.next_aa_pad)\n")


# --------------------------------------------------------------------------------------------------
# (2b) polypeptide_elongation.py: import the shared constant and stop spelling the buffer twice
# --------------------------------------------------------------------------------------------------
E4_MARK = "from reconstruction.ecoli.dataclasses.relation import"
E4_ANCHOR = "import copy\n\n\nCONC_UNITS = units.umol / units.L\n"
E4_NEW = (
    "import copy\n"
    "\n"
    "# EXT-PORT-10: the reconciliation width buffer is defined next to the knowledge-base pad that has\n"
    "# to contain it, and imported here. Before this, the pad lived in relation.py and the buffer lived\n"
    "# in KineticTrnaChargingModel as a bare literal, with nothing coupling them -- which is how the KB\n"
    "# array came to be one column narrower than the window that reads it.\n"
    "from reconstruction.ecoli.dataclasses.relation import (\n"
    "\tKINETIC_TRNA_CHARGING_WIDTH_BUFFER)\n"
    "\n"
    "\n"
    "CONC_UNITS = units.umol / units.L\n")

E5_MARK = "self.buffer = KINETIC_TRNA_CHARGING_WIDTH_BUFFER"
E5_OLD = "\t\tself.buffer = 10\n"
E5_NEW = (
    "\t\t# EXT-PORT-10: shared with reconstruction/ecoli/dataclasses/relation.py, which pads\n"
    "\t\t# codon_sequences wide enough to contain ceil(basal_rate * dt) + this buffer. Changing it in\n"
    "\t\t# one place now changes it in both; as a literal it did not.\n"
    "\t\tself.buffer = KINETIC_TRNA_CHARGING_WIDTH_BUFFER\n")

E6_MARK = "EXT-PORT-10 tripwire"
E6_OLD = (
    "\t\t# Growth associated maintenance energy requirements for elongations\n"
    "\t\tself.gtpPerElongation = constants.gtp_per_translation\n")
E6_NEW = (
    "\t\t# EXT-PORT-10 tripwire. The knowledge-base pad on relation.codon_sequences and the runtime\n"
    "\t\t# read window are computed in two different files from two different expressions. They were\n"
    "\t\t# out of step by exactly one column until EXT-PORT-10, and the symptom was an IndexError deep\n"
    "\t\t# inside buildSequences on ONE monomer at ONE position, hours into a campaign. Re-derive the\n"
    "\t\t# inequality here, once per simulation, so the pair cannot drift apart again silently.\n"
    "\t\t#\n"
    "\t\t# Bounds rather than the live width: self.elongation_model.codon_sequences_width() depends on\n"
    "\t\t# timeStepSec(), which is not final at initialize. max_time_step is the ceiling the adaptive\n"
    "\t\t# step search is gated by (PolypeptideElongation.isTimeStepShortEnough), so these ARE the\n"
    "\t\t# widest windows reachable.\n"
    "\t\tif kinetic_trna_charging or coarse_kinetic_elongation:\n"
    "\t\t\tcodon_sequences = sim_data.relation.codon_sequences\n"
    "\t\t\treal_codon_lengths = (codon_sequences != polymerize.PAD_VALUE).sum(axis=1)\n"
    "\t\t\t# A ribosome is deleted the step updated_lengths == terminal_lengths, so it tops out at\n"
    "\t\t\t# L-1 -- except for MAP substrates, whose termination protein_maturation can defer, which\n"
    "\t\t\t# leaves one sitting at exactly L.\n"
    "\t\t\tis_map_substrate = translation.monomer_data['cleavage_of_initial_methionine']\n"
    "\t\t\tmax_position = int(np.where(\n"
    "\t\t\t\tis_map_substrate, real_codon_lengths, real_codon_lengths - 1).max())\n"
    "\t\t\tmax_width = int(max(\n"
    "\t\t\t\t# _evolveState_codon_aware / _calculateRequest_codon_aware\n"
    "\t\t\t\ttranslation.max_time_step * constants.ribosome_elongation_rate_max.asNumber(\n"
    "\t\t\t\t\tunits.aa / units.s) + translation.next_aa_pad,\n"
    "\t\t\t\t# KineticTrnaChargingModel.elongation_rate / codon_sequences_width\n"
    "\t\t\t\tnp.ceil(translation.max_time_step\n"
    "\t\t\t\t\t* constants.ribosome_elongation_rate_basal.asNumber(units.aa / units.s)\n"
    "\t\t\t\t\t+ KINETIC_TRNA_CHARGING_WIDTH_BUFFER)))\n"
    "\t\t\tassert max_position + max_width <= codon_sequences.shape[1], (\n"
    "\t\t\t\t'relation.codon_sequences is {} columns wide but the codon-aware path can read to'\n"
    "\t\t\t\t' column {} ({} + a {}-wide window). Rebuild the knowledge base: the pad is computed in'\n"
    "\t\t\t\t' Relation._build_codon_based_translation and this simData predates EXT-PORT-10.'\n"
    "\t\t\t\t.format(codon_sequences.shape[1], max_position + max_width, max_position, max_width))\n"
    "\n"
    "\t\t# Growth associated maintenance energy requirements for elongations\n"
    "\t\tself.gtpPerElongation = constants.gtp_per_translation\n")


# --------------------------------------------------------------------------------------------------
# (3) next_amino_acids
# --------------------------------------------------------------------------------------------------
E7_MARK = "EXT-PORT-10: the codon-space implementation"
E7_OLD = (
    "\tdef codon_sequences_width(self, elongation_rates):\n"
    "\t\treturn self.sequences_width\n")
E7_NEW = (
    "\tdef next_amino_acids(self, all_sequences, sequence_elongations):\n"
    "\t\t\"\"\"EXT-PORT-10: the codon-space implementation of v3.0.1's SteadyStateElongationModel method.\n"
    "\n"
    "\t\tBaseElongationModel returns a hard-coded 0 and nothing overrode it here, in either tree. The\n"
    "\t\tonly consumer is ppgpp_metabolite_changes, whose call site notes the next amino acid must be\n"
    "\t\tincluded 'otherwise f will be NaN' on a zero-elongation timestep -- so the 0 is harmless only\n"
    "\t\twhile ppGpp is not computed on the codon-aware path, and it is the first thing that bites when\n"
    "\t\tppGpp is wired in.\n"
    "\n"
    "\t\tTWO things make the verbatim v3.0.1 body wrong here.\n"
    "\n"
    "\t\tSPACE. This model's sequences are CODONS (63 values), not amino acids (21), so\n"
    "\t\tnp.bincount(..., minlength=21) would return a 63-long array and the caller would hand a\n"
    "\t\tcodon-indexed vector to something expecting amino acids -- silently, since 63 >= 21. Count in\n"
    "\t\tcodon space, then project through relation.codons_to_amino_acids (21 x 63).\n"
    "\n"
    "\t\tWIDTH. sequence_elongations comes back from reconcile(), and reconcile_via_ribosome_positions\n"
    "\t\ttakes forward steps bounded by self.longer_sequences.shape[1] (the kinetic window, 32), which\n"
    "\t\tis WIDER than all_sequences (elongation_rates.max() + next_aa_pad, 23 or 31). Indexing\n"
    "\t\tall_sequences with those elongations can therefore run off the end. Read from longer_sequences\n"
    "\t\t-- the array this model's reconciliation actually operated on, row-aligned with\n"
    "\t\tsequence_elongations exactly as sequences() relies on for computeMassIncrease -- and drop the\n"
    "\t\tribosomes whose next codon falls outside even that window. Their next codon is genuinely not\n"
    "\t\tvisible this step, which is the same status as PAD.\n"
    "\t\t\"\"\"\n"
    "\t\tsequences = self.longer_sequences\n"
    "\t\tvisible = sequence_elongations < sequences.shape[1]\n"
    "\t\tnext_codons = sequences[\n"
    "\t\t\tnp.arange(len(sequence_elongations))[visible],\n"
    "\t\t\tsequence_elongations[visible]]\n"
    "\t\tnext_codons = next_codons[next_codons != polymerize.PAD_VALUE].astype(np.int64)\n"
    "\t\tcodon_counts = np.bincount(next_codons, minlength=self.n_codons)\n"
    "\t\treturn self.codons_to_amino_acids @ codon_counts\n"
    "\n"
    "\tdef codon_sequences_width(self, elongation_rates):\n"
    "\t\treturn self.sequences_width\n")

E8_MARK = "EXT-PORT-10: amino-acid space here"
E8_OLD = (
    "\tdef codon_sequences_width(self, elongation_rates):\n"
    "\t\treturn elongation_rates\n")
E8_NEW = (
    "\tdef next_amino_acids(self, all_sequences, sequence_elongations):\n"
    "\t\t\"\"\"EXT-PORT-10: amino-acid space here, so this is v3.0.1's SteadyStateElongationModel body\n"
    "\t\tverbatim. This model's protein_sequences are translation_sequences, not codon_sequences, and\n"
    "\t\tits reconcile() is a pass-through, so sequence_elongations stays within all_sequences.\n"
    "\n"
    "\t\tPorted for the same reason as the kinetic override: inheriting BaseElongationModel's 0 is a\n"
    "\t\tsilent wrong answer waiting for ppGpp to be wired into a codon-aware path.\n"
    "\t\t\"\"\"\n"
    "\t\tnext_amino_acid = all_sequences[\n"
    "\t\t\tnp.arange(len(sequence_elongations)), sequence_elongations]\n"
    "\t\treturn np.bincount(\n"
    "\t\t\tnext_amino_acid[next_amino_acid != polymerize.PAD_VALUE], minlength=21)\n"
    "\n"
    "\tdef codon_sequences_width(self, elongation_rates):\n"
    "\t\treturn elongation_rates\n")


# --------------------------------------------------------------------------------------------------
# (4) listener columns with no writer, and the turnover divide
# --------------------------------------------------------------------------------------------------
E9_MARK = "EXT-PORT-10: turnover is UNDEFINED"
E9_OLD = (
    "\t\t\t\t# Calculate turnover\n"
    "\t\t\t\tturnovers.append(\n"
    "\t\t\t\t\tincorporation\n"
    "\t\t\t\t\t/ delta_t[i]\n"
    "\t\t\t\t\t/ charged_trnas)\n")
E9_NEW = (
    "\t\t\t\t# Calculate turnover\n"
    "\t\t\t\t# EXT-PORT-10: turnover is UNDEFINED, not zero, for an amino acid whose charged pool is\n"
    "\t\t\t\t# empty at this internal solver step -- and an empty pool is exactly the interesting\n"
    "\t\t\t\t# case. The bare division produced NaN (0/0) or inf (x/0) plus a RuntimeWarning per\n"
    "\t\t\t\t# occurrence; NaN is kept as the value, because 0.0 would read as 'no turnover' rather\n"
    "\t\t\t\t# than 'no charged tRNA to turn over'. It is now produced deliberately and the warning\n"
    "\t\t\t\t# is not raised, instead of arriving as an arithmetic accident.\n"
    "\t\t\t\tturnover = np.full(charged_trnas.shape, np.nan, dtype=np.float64)\n"
    "\t\t\t\tnp.divide(\n"
    "\t\t\t\t\tincorporation / delta_t[i],\n"
    "\t\t\t\t\tcharged_trnas,\n"
    "\t\t\t\t\tout=turnover,\n"
    "\t\t\t\t\twhere=(charged_trnas != 0))\n"
    "\t\t\t\tturnovers.append(turnover)\n")

E10_MARK = "EXT-PORT-10: NO WRITER EXISTS"
E10_OLD = (
    "\t\tself.collision_removed_ribosomes_argA = np.zeros(self.argA_listener_size, np.int64)\n")
E10_NEW = (
    "\t\t# EXT-PORT-10: NO WRITER EXISTS for collision_removed_ribosomes_argA or for\n"
    "\t\t# ribosome_initiation_argA anywhere in this tree -- grep both names and the only hits are the\n"
    "\t\t# three in this file. In v3.0.1 they are produced by machinery that was not part of the\n"
    "\t\t# EXT-PORT scope. They therefore log as their allocate()-time zeros on EVERY run, including\n"
    "\t\t# kinetic ones, and a zero here means 'never written', NOT 'no collisions occurred'.\n"
    "\t\t#\n"
    "\t\t# Documented rather than removed: this listener is registered unconditionally\n"
    "\t\t# (models/ecoli/sim/simulation.py:103), so dropping the columns would change the output schema\n"
    "\t\t# of every default-path run in the corpus as well. tableCreate writes the same statement into\n"
    "\t\t# the table's attributes so it reaches an analyst reading the output, not only a reader of\n"
    "\t\t# this file.\n"
    "\t\tself.collision_removed_ribosomes_argA = np.zeros(self.argA_listener_size, np.int64)\n")

E11_MARK = "unwritten_columns"
E11_OLD = (
    "\tdef tableCreate(self, tableWriter):\n"
    "\t\ttableWriter.writeAttributes(\n"
    "\t\t\ttrna_codon_pairs = self.trna_codon_pairs,\n"
    "\t\t\t)\n")
E11_NEW = (
    "\tdef tableCreate(self, tableWriter):\n"
    "\t\ttableWriter.writeAttributes(\n"
    "\t\t\ttrna_codon_pairs = self.trna_codon_pairs,\n"
    "\t\t\t# EXT-PORT-10: columns that are allocated and appended but never written by any process in\n"
    "\t\t\t# this tree. Their zeros are absence, not measurement. Carried in the attributes so the\n"
    "\t\t\t# caveat travels with the output rather than living only in the source of the listener.\n"
    "\t\t\tunwritten_columns = [\n"
    "\t\t\t\t'collision_removed_ribosomes_argA',\n"
    "\t\t\t\t'ribosome_initiation_argA',\n"
    "\t\t\t\t],\n"
    "\t\t\t)\n")


# --------------------------------------------------------------------------------------------------
# Cellarium-side: the probe's allowlist must shrink, or it keeps excusing a mismatch that is gone
# --------------------------------------------------------------------------------------------------
E12_MARK = "EXT-PORT-10 emptied this allowlist"
E12_OLD = """KNOWN_MISMATCHES = frozenset({
    # phnE1: the MG1655 8-bp insertion, and an 839-nt cistron whose length is not a multiple of three
    # (hence the single Biopython "Partial codon" warning). v3.0.1 avoids it by typing EG11283_RNA
    # 'pseudo', which EXCLUDED_RNA_TYPES then drops — the only rnas.tsv row whose type differs between
    # the trees. Its protein sequence, gene coordinates and empty coding_segments are identical there,
    # so this is a knowledge-base limitation both trees share rather than a port defect.
    "PHNE-MONOMER",
"""
E12_NEW = """KNOWN_MISMATCHES = frozenset({
    # EXT-PORT-10 emptied this allowlist. PHNE-MONOMER was here until EG11283_RNA (phnE1) was typed
    # 'pseudo' in reconstruction/ecoli/flat/rnas.tsv, matching v3.0.1 — EXCLUDED_RNA_TYPES then drops
    # the cistron, the monomer leaves monomer_data, and the mismatch is not excused, it is gone.
    # Deliberately EMPTY rather than deleted: the next monomer whose mRNA stops disagreeing quietly
    # should fail this harness, and an empty frozenset says that on purpose.
"""


# --------------------------------------------------------------------------------------------------

def _read(path: str) -> tuple[str, str]:
    """(text, destination newline). Preserves CRLF vs LF, per the applier's convention."""
    with open(path, "rb") as f:
        blob = f.read()
    nl = "\r\n" if blob.count(b"\r\n") else "\n"
    with io.open(path, encoding="utf-8") as f:
        return f.read(), nl


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

    def edit(self, name: str, marker: str, old: str, new: str, required: bool = True) -> None:
        if marker in self.text:
            self.results.append({"edit": name, "state": "already applied"})
            return
        n = self.text.count(old)
        if n != 1:
            state = "ANCHOR MISSING" if n == 0 else f"ANCHOR AMBIGUOUS (matched {n}x)"
            self.results.append({"edit": name, "state": state, "required": required})
            if required:
                raise SystemExit(
                    f"FATAL {self.rel}: edit {name!r} anchor matched {n} times, expected exactly 1.\n"
                    f"  anchor starts: {old.splitlines()[0][:100]!r}\n"
                    "  Nothing was written. Refusing to guess -- an anchor that no longer matches means\n"
                    "  the file has moved on and the edit may no longer be correct.")
            return
        self.text = self.text.replace(old, new, 1)
        self.results.append({"edit": name, "state": "applied"})

    def flush(self) -> bool:
        changed = self.text != self.original
        if changed and not self.check:
            _write(self.path, self.text, self.nl)
        return changed


def run(wcecoli: str, cellarium: str | None, check: bool) -> dict:
    report: dict = {"check": check, "files": {}}
    wrote = []

    # (1) phnE1
    p = Patcher(wcecoli, RNAS, check)
    p.edit("phnE1_pseudo", E1_MARK, E1_OLD, E1_NEW)
    if p.flush():
        wrote.append(RNAS)
    report["files"][RNAS] = p.results

    # (2) relation.py
    p = Patcher(wcecoli, REL, check)
    p.edit("width_buffer_constant", E2_MARK, E2_ANCHOR, E2_NEW)
    p.edit("codon_pad_widened", E3_MARK, E3_OLD, E3_NEW)
    if p.flush():
        wrote.append(REL)
    report["files"][REL] = p.results

    # (2b, 3) polypeptide_elongation.py
    p = Patcher(wcecoli, PE, check)
    p.edit("import_width_buffer", E4_MARK, E4_ANCHOR, E4_NEW)
    p.edit("buffer_from_constant", E5_MARK, E5_OLD, E5_NEW)
    p.edit("width_tripwire", E6_MARK, E6_OLD, E6_NEW)
    p.edit("kinetic_next_amino_acids", E7_MARK, E7_OLD, E7_NEW)
    p.edit("coarse_next_amino_acids", E8_MARK, E8_OLD, E8_NEW)
    p.edit("turnover_divide_guard", E9_MARK, E9_OLD, E9_NEW)
    if p.flush():
        wrote.append(PE)
    report["files"][PE] = p.results

    # (4) listener
    p = Patcher(wcecoli, LIS, check)
    p.edit("unwritten_columns_note", E10_MARK, E10_OLD, E10_NEW)
    p.edit("unwritten_columns_attribute", E11_MARK, E11_OLD, E11_NEW)
    if p.flush():
        wrote.append(LIS)
    report["files"][LIS] = p.results

    # Cellarium-side probe allowlist
    if cellarium:
        p = Patcher(cellarium, PROBE, check)
        p.edit("probe_allowlist_emptied", E12_MARK, E12_OLD, E12_NEW)
        if p.flush():
            wrote.append(PROBE)
        report["files"][PROBE] = p.results

    # Named "would_write" under --check so a dry run cannot be misread as a completed one.
    report["would_write" if check else "wrote"] = wrote
    report["complete"] = all(
        r["state"] in ("applied", "already applied")
        for results in report["files"].values() for r in results)
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--wcecoli", default="C:/dev/wcEcoli")
    ap.add_argument("--cellarium", default=None,
                    help="Cellarium checkout, for scripts/probe_relation.py's allowlist")
    ap.add_argument("--check", action="store_true", help="report only, write nothing")
    args = ap.parse_args(argv)

    report = run(args.wcecoli, args.cellarium, args.check)
    print(json.dumps(report, indent=2))
    if not report["complete"]:
        print("\nINCOMPLETE -- see states above.", file=sys.stderr)
        return 1
    files = report.get("wrote") or report.get("would_write") or []
    if files and args.check:
        print("\nWOULD WRITE (nothing was written -- --check): " + ", ".join(files))
    elif files:
        print("\nWROTE: " + ", ".join(files))
        print("\nrnas.tsv changed => cistron_data and monomer_data change => ParCa MUST be re-run:")
        print("  python runscripts/manual/runParca.py kinetic_parca --cpus 4")
    else:
        print("\nnothing to do -- already applied")
    return 0



def _superseded_banner() -> None:
    """Say it on stderr, every run. A superseded tool that runs silently is a documented path."""
    sys.stderr.write(
        "\n"
        "=================================================================================\n"
        " SUPERSEDED. This is the generator of record, not the install path.\n"
        " To set up a wcEcoli checkout, use:\n"
        "     python scripts/apply_model_overlay.py --wcecoli /path/to/wcEcoli\n"
        " See docs/OVERLAY.md for why anchor-matching was retired.\n"
        "=================================================================================\n"
        "\n")

if __name__ == "__main__":
    _superseded_banner()
    sys.exit(main())
