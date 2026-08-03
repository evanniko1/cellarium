"""SUPERSEDED by the overlay (scripts/apply_model_overlay.py). Kept for provenance, not as an install
path.

DO NOT use this to set up a wcEcoli checkout. Use:

    python scripts/apply_model_overlay.py --wcecoli /path/to/wcEcoli

The overlay ships the FINISHED condition_defs.tsv / media_recipes.tsv / variants, so there is no
append step to get wrong. It also fixes a data-integrity bug this script's ordering could not: see
gate 2 in scripts/build_model_overlay.py -- the dropout condition rows must be APPENDED, because
row order IS the condition index space that src/cellarium/generate.py hardcodes.

Apply Cellarium's model-level additions to a wcEcoli checkout — idempotently, and verifiably.

Cellarium needs three media that stock wcEcoli does not define (SCI-TRNA-3: single-amino-acid dropouts). The
definition has to live HERE, not only in a working copy, or the experiment is unreproducible: the wcEcoli
checkout is a collaborator's fork (`MohammedNagdi/wcEcoli`) and the model runtime is not this half of the
project's to push to.

**Why an applier and not a .patch file.** A unified diff carries line numbers and context; it breaks the moment
upstream inserts an unrelated media row above ours, and `git apply` then fails in a way that reads like a
conflict rather than "already fine". This appends rows only if their media id is absent, so it is safe to run
any number of times, safe against upstream reordering, and it reports what it found rather than what it assumed.

Run it after cloning wcEcoli and before the ParCa rebuild:

    python scripts/apply_model_patches.py --wcecoli /path/to/wcEcoli
    python scripts/apply_model_patches.py --wcecoli /path/to/wcEcoli --check   # CI / verification, writes nothing

**Two files, and the second one is not optional.** An earlier version of this script patched only the media and
argued that `condition_defs.tsv` could be left alone, since its doubling-time column feeds ParCa's fit. That was
wrong, and a 1-seed smoke run — not a code read — proved it: the sim died at exactly t=1200 with
`KeyError: 'minimal_aa_minus_leu'` inside `chromosome_replication.py:92`.
`sim_data.nutrient_to_doubling_time` is keyed by MEDIA but BUILT from the conditions table, so a medium with no
condition row has no doubling time and the strict lookup dies. (`metabolism.py:149` uses
`.get(media, minimal)` and would have survived — the two processes disagree about unknown media, and the
strict one decides.)

**A ParCa rebuild is required after applying**, because `external_state` also bakes `saved_media` into
`sim_data`. The rebuild changes `kb_sha256`, which every existing manifest row carries. Verified for the media
change alone (`scripts/verify_kb_rebuild.py`): a stock rebuild and one carrying the media differ in 0 of 67
fitted keys, and two identical-input rebuilds are bit-identical, so ParCa is deterministic and the media are
purely additive. **Re-run that verification after the condition rows**, which touch the fitted table and so
genuinely could move something — do not assume the earlier clean result carries over.
"""

from __future__ import annotations

import argparse
import os
import sys

MEDIA_RECIPES = os.path.join("reconstruction", "ecoli", "flat", "condition", "media_recipes.tsv")
CONDITION_DEFS = os.path.join("reconstruction", "ecoli", "flat", "condition", "condition_defs.tsv")

# Each dropout is `minimal_plus_amino_acids` with ONE amino acid forced to zero. `make_media.make_recipe`
# combines base+supplement FIRST and applies `ingredients` to the RESULT (make_media.py:149-170), so
# `-Infinity` here removes the molecule from the final amino-acid-rich medium rather than from the base it was
# never in. Verified: each perturbs exactly 1 of 87 molecules, versus 30 for the AA-rich -> minimal downshift.
#
# THE NAMES MUST STAY <= 24 CHARACTERS, and that is a data-integrity constraint rather than style. wcEcoli
# writes media ids into a NumPy fixed-width unicode column sized from the FIRST value in the generation. These
# runs start in `minimal_plus_amino_acids` (24 chars), so the generation containing the shift gets a <U25
# column and every longer name is silently cut to 25 characters. The first attempt named them
# `minimal_plus_amino_acids_minus_{leu,thr,arg}` (34 chars) and all three truncated to the IDENTICAL string
# `minimal_plus_amino_acids_` — measured on a smoke run, distinct-after-truncation = 1. The record would have
# shown that *a* shift happened while making the three arms indistinguishable from each other. This is the
# SCI-QC-1 defect a second time, in the very column SCI-QC-2 adopted as its untruncated witness; short names
# fix the record itself instead of working around it. `serialization.scan_run` flags the condition if it
# recurs.
MEDIA_ROWS = [
    ('minimal_aa_minus_leu',
     '"minimal_aa_minus_leu"\t"MIX0-57"\t0.8\t"5X_supplement_EZ"\t0.2\t["LEU"]\t[-Infinity]\t[]\t[]'),
    ('minimal_aa_minus_thr',
     '"minimal_aa_minus_thr"\t"MIX0-57"\t0.8\t"5X_supplement_EZ"\t0.2\t["THR"]\t[-Infinity]\t[]\t[]'),
    ('minimal_aa_minus_arg',
     '"minimal_aa_minus_arg"\t"MIX0-57"\t0.8\t"5X_supplement_EZ"\t0.2\t["ARG"]\t[-Infinity]\t[]\t[]'),
]


# A medium is not enough. `sim_data.nutrient_to_doubling_time` is keyed by MEDIA but BUILT from the conditions
# table, and `chromosome_replication.py:92` looks the current medium up with a bare `[...]` — so a timeline
# entering a medium with no condition row raises KeyError mid-run. (`metabolism.py:149` uses `.get(media,
# minimal)` and would have survived; the two processes disagree, and the strict one wins.) Found by a 1-seed
# smoke run, not by reading: the sim died at exactly t=1200.
#
# Doubling time = 25.0, the SOURCE medium's (`with_aa`). This is the minimal-assumption choice, not a
# prediction: with ppGpp regulation on, `metabolism` drives biomass from the RNA/protein ratio rather than from
# this number, which mainly sets the DNA critical initiation mass. Matching the source medium means the shift
# introduces NO step change in the replication set-point, so any response comes from the missing amino acid
# rather than from a discontinuity we imposed. Empty TF lists follow the `minus_calcium` precedent — adding TF
# overrides would enlarge what ParCa fits.
CONDITION_ROWS = [
    ('minus_leu', '"minus_leu"	"minimal_aa_minus_leu"	{}	25.0	[]	[]'),
    ('minus_thr', '"minus_thr"	"minimal_aa_minus_thr"	{}	25.0	[]	[]'),
    ('minus_arg', '"minus_arg"	"minimal_aa_minus_arg"	{}	25.0	[]	[]'),
]


def apply_conditions(wcecoli: str, check: bool = False) -> dict:
    """Add the dropout CONDITION rows, without which the media exist but the sim dies on entering them."""
    path = os.path.join(wcecoli, CONDITION_DEFS)
    if not os.path.isfile(path):
        return {"ok": False, "why": f"{CONDITION_DEFS} not found under {wcecoli!r}"}
    with open(path, encoding="utf-8") as f:
        text = f.read()
    present = [cid for cid, _row in CONDITION_ROWS if f'"{cid}"' in text]
    missing = [(cid, row) for cid, row in CONDITION_ROWS if cid not in present]
    if check or not missing:
        return {"ok": not missing, "present": present, "missing": [c for c, _ in missing], "wrote": False}
    lines = text.splitlines()
    at = next((i for i, ln in enumerate(lines) if ln.startswith('"with_aa"')), len(lines) - 1)
    for j, (_cid, row) in enumerate(missing):
        lines.insert(at + 1 + j, row)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return {"ok": True, "present": present, "added": [c for c, _ in missing], "wrote": True,
            "next": "REBUILD ParCa — nutrient_to_doubling_time is built from this table."}


def apply_media(wcecoli: str, check: bool = False) -> dict:
    """Add any missing dropout media rows. Returns what was found, added, and what still needs doing."""
    path = os.path.join(wcecoli, MEDIA_RECIPES)
    if not os.path.isfile(path):
        return {"ok": False, "why": f"not a wcEcoli checkout — {MEDIA_RECIPES} not found under {wcecoli!r}"}
    with open(path, encoding="utf-8") as f:
        text = f.read()
    present = [mid for mid, _row in MEDIA_ROWS if f'"{mid}"' in text]
    missing = [(mid, row) for mid, row in MEDIA_ROWS if mid not in present]
    # Guard the precondition the rows depend on: they extend the AA-rich recipe, and reference a supplement
    # that must actually contain the amino acid being removed — otherwise the dropout is a silent no-op.
    if '"minimal_plus_amino_acids"' not in text:
        return {"ok": False, "why": "this checkout has no `minimal_plus_amino_acids` recipe to extend"}
    if check or not missing:
        return {"ok": not missing, "present": present, "missing": [m for m, _ in missing], "wrote": False,
                "path": path,
                "next": ("nothing to do — all three dropout media are defined" if not missing else
                         f"run without --check to add: {', '.join(m for m, _ in missing)}")}
    lines = text.splitlines()
    # insert after the recipe we extend, so the file stays readable and the relationship is obvious
    at = next((i for i, ln in enumerate(lines) if ln.startswith('"minimal_plus_amino_acids"')), len(lines) - 1)
    for j, (_mid, row) in enumerate(missing):
        lines.insert(at + 1 + j, row)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return {"ok": True, "present": present, "added": [m for m, _ in missing], "wrote": True, "path": path,
            "next": "REBUILD ParCa — the cached simData does not know these media and will KeyError on them. "
                    "Record the new kb_sha256 alongside the old one."}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--wcecoli", default=os.environ.get("WCECOLI_PATH", r"C:\dev\wcEcoli"))
    ap.add_argument("--check", action="store_true", help="report only; write nothing")
    a = ap.parse_args(argv)
    media = apply_media(a.wcecoli, check=a.check)
    conds = apply_conditions(a.wcecoli, check=a.check)
    print("media_recipes.tsv:")
    for k, v in media.items():
        print(f"  {k}: {v}")
    print("condition_defs.tsv:")
    for k, v in conds.items():
        print(f"  {k}: {v}")
    return 0 if (media.get("ok") and conds.get("ok")) else 1



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
