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


def status(wcecoli: str) -> dict:
    """Per-item state. Each has its OWN marker so a partial port reports as partial."""
    flat = os.path.join(wcecoli, "reconstruction", "ecoli", "flat")
    return {
        "relation_methods": _has(wcecoli, REL, "_build_codon_dependent_trna_charging"),
        "relation_init": _has(wcecoli, REL, "self._build_trna_charging_kinetics(raw_data, sim_data)"),
        "groups_codons": _has(wcecoli, MG, "'codons': codon_ids"),
        "groups_initiators": _has(wcecoli, MG, "'initiator_trnas'"),
        "ids_start_codon": _has(wcecoli, MI, "'start_codon'"),
        "simdata_codon_read_rate": _has(wcecoli, SD, "codon_read_rate"),
        "kb_kinetics_registered": _has(wcecoli, KB, '"trna_charging_kinetics.tsv"'),
        "kb_optimization_registered": _has(wcecoli, KB, "trna_charging_kinetics_constants.tsv"),
        "flat_files": {f: os.path.isfile(os.path.join(flat, f)) for f in FLAT_FILES},
    }


def _complete(st: dict) -> bool:
    return all(v is True for k, v in st.items() if k != "flat_files") and all(st["flat_files"].values())


def apply_port(wcecoli: str, reference: str | None, check: bool = False) -> dict:
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
    a = ap.parse_args(argv)
    res = apply_port(a.wcecoli, a.reference, check=a.check)
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
