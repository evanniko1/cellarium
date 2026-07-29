"""Verify a ParCa rebuild ADDED media without PERTURBING the existing fit.

Adding rows to `media_recipes.tsv` is expected to be additive: `saved_media` and `exchange_dict` are lookup
tables keyed by media id, nothing there feeds an optimisation, and `condition_defs.tsv` — which carries the
doubling times ParCa actually fits against — is untouched. Expected is not measured. If the rebuild silently
moved a fitted parameter, every comparison between an old corpus run and a new dropout run would be
confounded, and the confound would be invisible because both runs would look internally consistent.

So this diffs the two fitted `simData.cPickle` objects directly. Runs inside the model image (unpickling
sim_data needs the compiled Cython extensions).

    docker run --rm -v <out>:/wcEcoli/out -e PYTHONPATH=/wcEcoli -w /wcEcoli <image> \
        python /wcEcoli/out/verify_kb_rebuild.py /wcEcoli/out/cellarium/kb /wcEcoli/out/aadrop/kb
"""

from __future__ import annotations

import pickle
import sys

import numpy as np

NEW_MEDIA = ["minimal_plus_amino_acids_minus_leu", "minimal_plus_amino_acids_minus_thr",
             "minimal_plus_amino_acids_minus_arg"]


def _load(kb_dir):
    with open(f"{kb_dir}/simData.cPickle", "rb") as f:
        return pickle.load(f)


# Curated fitted quantities rather than a reflective walk. A `dir()`-based recursion over sim_data HANGS:
# many attributes are lazily-computed properties, so merely enumerating them re-runs pieces of the fit (it ran
# >10 min without emitting a line before being killed). These paths are what ParCa actually solves for, so a
# change here is what would confound an old-corpus-vs-new-dropout comparison.
_FITTED_PATHS = [
    "process.transcription.rna_data",
    "process.transcription.rna_expression",
    "process.transcription.rna_synth_prob",
    "process.translation.monomer_data",
    "process.translation.ribosome_elongation_rate_dict",
    "process.replication.replichore_lengths",
    "mass.avg_cell_dry_mass_init",
    "mass.cell_dry_mass_fraction",
    "growth_rate_data.doubling_time",
]


def _resolve(obj, dotted):
    for part in dotted.split("."):
        obj = getattr(obj, part, None)
        if obj is None:
            return None
    return obj


def _summarise(v):
    """A comparable summary of a fitted value: shape + checksum for arrays, bounded repr otherwise."""
    if isinstance(v, np.ndarray):
        if v.dtype.names:                                    # structured (rna_data / monomer_data)
            cols = []
            for nm in v.dtype.names:
                col = v[nm]
                if col.dtype.kind in "fiub" and col.size:
                    cols.append((nm, round(float(np.nansum(col.astype(float))), 9)))
            return ("structured", v.shape, tuple(cols))
        if v.dtype.kind in "fiub" and v.size:
            a = v.astype(float)
            return ("ndarray", v.shape, round(float(np.nansum(a)), 9), round(float(np.nanmax(np.abs(a))), 9))
        return ("ndarray", v.shape, str(v.dtype))
    if isinstance(v, dict):
        # Summarise each VALUE numerically. An earlier version used str(x), and numpy abbreviates long arrays
        # to '[8.1e-07 1.5e-06 ... 2.6e-02]' — so this compared truncated prefixes and reported two arrays as
        # "CHANGED" whose visible digits were identical, with no way to tell a real difference from an elision.
        # Reporting a diff from a truncated view is how a non-finding gets published as a finding.
        return ("dict", len(v), tuple(sorted((str(k), _summarise(x)) for k, x in v.items())))
    return ("scalar", str(v))


def main(old_dir, new_dir):
    old, new = _load(old_dir), _load(new_dir)
    print(f"OLD kb: {old_dir}\nNEW kb: {new_dir}\n")

    o_media = set(old.external_state.saved_media)
    n_media = set(new.external_state.saved_media)
    added, removed = sorted(n_media - o_media), sorted(o_media - n_media)
    print(f"media: old={len(o_media)} new={len(n_media)}")
    print(f"  ADDED  : {added}")
    print(f"  REMOVED: {removed or 'none'}")
    missing = [m for m in NEW_MEDIA if m not in n_media]
    print(f"  all three dropout media present: {not missing}" + (f" MISSING {missing}" if missing else ""))
    if not missing:
        base = new.external_state.saved_media["minimal_plus_amino_acids"]
        for m, mol in zip(NEW_MEDIA, ("LEU", "THR", "ARG")):
            d = new.external_state.saved_media[m]
            ch = sorted(k for k in set(base) | set(d)
                        if abs(float(d.get(k, 0)) - float(base.get(k, 0))) > 1e-12)
            print(f"  {m}: {mol} -> {float(d[mol])} | perturbs {ch}")

    print("\ndoubling times per condition (the quantity ParCa fits against):")
    try:
        o_dt, n_dt = old.conditionToDoublingTime, new.conditionToDoublingTime
        diffs = {k: (o_dt[k], n_dt.get(k)) for k in o_dt if str(o_dt[k]) != str(n_dt.get(k))}
        print(f"  conditions old={len(o_dt)} new={len(n_dt)} | CHANGED: {diffs or 'none'}")
    except Exception as e:
        print(f"  could not compare: {type(e).__name__}: {e}")

    print("\nfitted quantities ParCa solves for:")
    changed, checked, unresolved = [], 0, []
    for path in _FITTED_PATHS:
        a, b = _resolve(old, path), _resolve(new, path)
        if a is None or b is None:
            unresolved.append(path)
            continue
        checked += 1
        sa, sb = _summarise(a), _summarise(b)
        if sa != sb:
            changed.append((path, sa, sb))
    print(f"  compared: {checked}/{len(_FITTED_PATHS)}  (absent on this sim_data: {unresolved or 'none'})")
    print(f"  CHANGED: {len(changed)}")
    for path, sa, sb in changed:
        print(f"    {path}:\n       old={str(sa)[:200]}\n       new={str(sb)[:200]}")
    print("\nVERDICT: " + ("ADDITIVE — the rebuild added media and moved no fitted array."
                           if not changed and not missing and not removed else
                           "NOT PURELY ADDITIVE — inspect the changes above before pooling old and new runs."))
    return 0 if (not changed and not missing and not removed) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
