"""SUPERSEDED by the overlay (scripts/apply_model_overlay.py). Kept for provenance, not as an install
path.

DO NOT use this to set up a wcEcoli checkout. Use:

    python scripts/apply_model_overlay.py --wcecoli /path/to/wcEcoli

The overlay ships the FINISHED condition_defs.tsv / media_recipes.tsv / variants, so there is no
append step to get wrong. It also fixes a data-integrity bug this script's ordering could not: see
gate 2 in scripts/build_model_overlay.py -- the dropout condition rows must be APPENDED, because
row order IS the condition index space that src/cellarium/generate.py hardcodes.

Install Cellarium's own model VARIANTS into a wcEcoli checkout — idempotently, and verifiably.

Cellarium is the source of truth; the wcEcoli tree is a target. This is the point the previous arrangement had
backwards: `graded_gene_knockout.py` existed only as an untracked file inside a wcEcoli checkout, which made it
a DEPENDENCY on that checkout rather than a capability of this repo — a clone of Cellarium simply did not have
it. Variants now live in `model_patches/variants/` here and are copied out, exactly as `apply_model_patches.py`
does for the dropout media.

Unlike `apply_trna_port.py`, which deliberately applies FROM an external reference because the ported code is
Covert-lab's and its redistribution licence is unresolved, these variants are OURS. They are carried in-repo,
committed, and reviewable.

Two edits per variant, and the second is the one that silently bites:

  1. Copy `model_patches/variants/<name>.py` -> `models/ecoli/sim/variants/<name>.py`
  2. Register `'<name>'` in that package's `__init__.py` `variants` list. Without registration
     `apply_variant.apply_variant` raises on an unknown name, and `nameToFunctionMapping` never sees it — the
     file is present and the variant does not exist.

Idempotent: both steps are guarded, `--check` writes nothing, and a partial install reports as partial rather
than as done.

    python scripts/apply_model_variants.py --wcecoli /path/to/wcEcoli --check
    python scripts/apply_model_variants.py --wcecoli /path/to/wcEcoli
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys

SRC_DIR = os.path.join("model_patches", "variants")
DST_DIR = os.path.join("models", "ecoli", "sim", "variants")
INIT = os.path.join(DST_DIR, "__init__.py")

# Variants Cellarium adds. Each must be importable with no Cellarium imports — it runs inside the model image,
# where only wcEcoli is on the path.
VARIANTS = ["graded_gene_knockout"]


def _read(path: str) -> tuple[str, str]:
    """(text, destination newline). The model tree is CRLF; appending LF content unnormalised mixes endings."""
    with open(path, "rb") as f:
        blob = f.read()
    nl = "\r\n" if blob.count(b"\r\n") else "\n"
    with open(path, encoding="utf-8") as f:
        return f.read(), nl


def status(wcecoli: str) -> dict:
    init_path = os.path.join(wcecoli, INIT)
    registered = set()
    if os.path.isfile(init_path):
        with open(init_path, encoding="utf-8") as f:
            text = f.read()
        registered = {v for v in VARIANTS if f"'{v}'" in text or f'"{v}"' in text}
    return {
        "installed": {v: os.path.isfile(os.path.join(wcecoli, DST_DIR, v + ".py")) for v in VARIANTS},
        "registered": {v: (v in registered) for v in VARIANTS},
        "source_present": {v: os.path.isfile(os.path.join(SRC_DIR, v + ".py")) for v in VARIANTS},
    }


def _complete(st: dict) -> bool:
    return all(st["installed"].values()) and all(st["registered"].values())


def apply_variants(wcecoli: str, check: bool = False) -> dict:
    st = status(wcecoli)
    missing_src = [v for v, ok in st["source_present"].items() if not ok]
    if missing_src:
        return {"ok": False, "status": st,
                "why": f"missing source variant(s) in {SRC_DIR}: {missing_src} — Cellarium is the source of "
                       f"truth, so this cannot be applied from anywhere else."}
    if check or _complete(st):
        return {"ok": _complete(st), "status": st, "wrote": [],
                "next": ("nothing to do — all variants installed and registered" if _complete(st) else
                         "run without --check to install")}
    if not os.path.isdir(os.path.join(wcecoli, DST_DIR)):
        return {"ok": False, "status": st, "why": f"not a wcEcoli checkout — {DST_DIR} not found under {wcecoli!r}"}

    wrote = []
    for v in VARIANTS:
        dst = os.path.join(wcecoli, DST_DIR, v + ".py")
        if not st["installed"][v]:
            shutil.copyfile(os.path.join(SRC_DIR, v + ".py"), dst)
            wrote.append(f"{DST_DIR}/{v}.py")

    # Registration. Anchored on an existing entry so the list stays sorted-ish and the edit is unambiguous;
    # refuses rather than guessing if the anchor is missing or duplicated.
    unregistered = [v for v in VARIANTS if not st["registered"][v]]
    if unregistered:
        init_path = os.path.join(wcecoli, INIT)
        text, nl = _read(init_path)
        anchor = "\t'gene_knockout',\n"
        if text.count(anchor) != 1:
            return {"ok": False, "status": status(wcecoli), "wrote": wrote,
                    "why": f"expected exactly one {anchor.strip()!r} anchor in {INIT}, found "
                           f"{text.count(anchor)} — refusing to guess where to register {unregistered}."}
        text = text.replace(anchor, anchor + "".join(f"\t'{v}',\n" for v in unregistered), 1)
        with open(init_path, "w", encoding="utf-8", newline=nl) as f:
            f.write(text)
        wrote.append(f"{INIT}: registered {unregistered}")

    st2 = status(wcecoli)
    return {"ok": _complete(st2), "status": st2, "wrote": wrote,
            "next": ("No ParCa rebuild needed — variants are applied to sim_data at SIM LAUNCH "
                     "(wholecell/fireworks/firetasks/variantSimData.py loads simData.cPickle then calls "
                     "apply_variant), not baked into the knowledge base.")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--wcecoli", default=os.environ.get("WCECOLI_DIR", "C:/dev/wcEcoli"))
    ap.add_argument("--check", action="store_true", help="report only; write nothing")
    a = ap.parse_args(argv)
    res = apply_variants(a.wcecoli, check=a.check)
    if res.get("why"):
        print(f"ERROR: {res['why']}")
    st = res.get("status") or {}
    for v in VARIANTS:
        print(f"  {v}: source={st.get('source_present', {}).get(v)} "
              f"installed={st.get('installed', {}).get(v)} registered={st.get('registered', {}).get(v)}")
    for w in res.get("wrote") or []:
        print(f"    + {w}")
    print(f"\nok={res.get('ok')}\n{res.get('next', '')}")
    return 0 if res.get("ok") else 1



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
