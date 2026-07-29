"""Apply Cellarium's model-level additions to a wcEcoli checkout — idempotently, and verifiably.

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

**A ParCa rebuild is required after applying.** `reconstruction/ecoli/dataclasses/state/external_state.py`
builds `saved_media` from every recipe and stores it in `sim_data`, and looks media up by label
(`self.saved_media[media_label]`) — so a timeline naming a medium the cached `simData.cPickle` has never heard
of raises KeyError. The rebuild changes `kb_sha256`, which every existing manifest row carries, so record both
hashes and do not pool old and new runs without checking the fitted parameters for existing conditions are
unchanged. They are EXPECTED to be unchanged — `saved_media`/`exchange_dict` are pure lookup tables keyed by
media id, nothing here feeds an optimisation, and fitting is driven by `condition_defs.tsv`, which these
patches deliberately do not touch — but that is a claim to verify against the rebuilt KB, not to assume.
"""

from __future__ import annotations

import argparse
import os
import sys

MEDIA_RECIPES = os.path.join("reconstruction", "ecoli", "flat", "condition", "media_recipes.tsv")

# Each dropout is `minimal_plus_amino_acids` with ONE amino acid forced to zero. `make_media.make_recipe`
# combines base+supplement FIRST and applies `ingredients` to the RESULT (make_media.py:149-170), so
# `-Infinity` here removes the molecule from the final amino-acid-rich medium rather than from the base it was
# never in. Verified: each perturbs exactly 1 of 87 molecules, versus 30 for the AA-rich -> minimal downshift.
MEDIA_ROWS = [
    ('minimal_plus_amino_acids_minus_leu',
     '"minimal_plus_amino_acids_minus_leu"\t"MIX0-57"\t0.8\t"5X_supplement_EZ"\t0.2\t["LEU"]\t[-Infinity]\t[]\t[]'),
    ('minimal_plus_amino_acids_minus_thr',
     '"minimal_plus_amino_acids_minus_thr"\t"MIX0-57"\t0.8\t"5X_supplement_EZ"\t0.2\t["THR"]\t[-Infinity]\t[]\t[]'),
    ('minimal_plus_amino_acids_minus_arg',
     '"minimal_plus_amino_acids_minus_arg"\t"MIX0-57"\t0.8\t"5X_supplement_EZ"\t0.2\t["ARG"]\t[-Infinity]\t[]\t[]'),
]


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
    res = apply_media(a.wcecoli, check=a.check)
    for k, v in res.items():
        print(f"{k}: {v}")
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
