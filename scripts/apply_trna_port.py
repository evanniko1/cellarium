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
# The one place the two trees genuinely disagree on SEMANTICS rather than on presence.
# `_build_codon_sequences` looks up each monomer's mRNA with `rna_sequences[cistron_to_monomer_mapping[i]]`.
# That index is in CISTRON space — the method's own docstring says it maps "a property for RNA cistrons into
# ... the corresponding monomers". In our tree `transcription.rna_data` is TRANSCRIPTION UNITS and cistrons
# live in `transcription.cistron_data`, so indexing rna_data with a cistron index runs off the end:
#   IndexError: list index out of range   (relation.py _build_codon_sequences)
# after ParCa had already run for minutes. Note this is an INDEX error only because the arrays happen to be
# different lengths — had n_TU exceeded n_cistrons it would have silently returned the WRONG mRNA for every
# protein and the port would have "worked".
#
# The two later uses of rna_data (free_trnas / anticodons) are deliberately NOT rewritten: tRNAs are addressed
# TU-side everywhere else in our tree, including in SteadyStateElongationModel and the TrnaCharging listener.
REL_CISTRON_OLD = ("\t\trna_sequences = sim_data.getter.get_sequences(\n"
                   "\t\t\t[rna_id[:-3] for rna_id\n"
                   "\t\t\tin sim_data.process.transcription.rna_data['id']])\n")
REL_CISTRON_NEW = ("\t\t# EXT-PORT-1 adaptation: cistron_to_monomer_mapping indexes CISTRONS, and in this tree\n"
                   "\t\t# rna_data is transcription units. v3.0.1 read rna_data here; we must read cistron_data\n"
                   "\t\t# or every monomer gets the wrong mRNA (or an IndexError, which is the lucky case).\n"
                   "\t\t# ...and cistron ids carry NO [c] compartment suffix, so the [:-3] strip that is right\n"
                   "\t\t# for rna_data ids eats real characters: 'EG10001_RNA' -> 'EG10001_' -> KeyError.\n"
                   "\t\trna_sequences = sim_data.getter.get_sequences(\n"
                   "\t\t\tlist(sim_data.process.transcription.cistron_data['id']))\n")

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
        "relation_cistron_fix": _has(wcecoli, REL, "EXT-PORT-1 adaptation: cistron_to_monomer_mapping"),
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
