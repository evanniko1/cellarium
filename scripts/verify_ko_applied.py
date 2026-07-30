"""Did the knockout actually knock anything out? Verify from the run's own output, before trusting the arm.

This exists because the corpus already contains two knockouts that silently did nothing — `KO:murA` is
byte-identical to a wild type across all 12 channels and 1145 files, and `KO:rpoB` shows the same signature
(WELL-NOOP-1) — and because `_variant_type` was, until this week, dropping the genotype from any design that
also carried a timeline. Both failures produce a run that is *internally consistent and completely plausible*:
provenance says knockout, the media shift works, nothing raises. The only way to tell is to look at whether the
target's gene products are actually gone.

For the SCI-TRNA-4 auxotroph arms this is load-bearing rather than hygiene: the whole experiment rests on the
biosynthetic pathway being blocked. A silent no-op would produce exactly the prototroph result we already have
(charging holds, elongation holds) and we would read it as "auxotroph starvation doesn't work either".

Usage:  python scripts/verify_ko_applied.py <run_root> <gene> [<gene> ...]
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np


def monomer_counts(simout: str):
    """(names, counts array) from the MonomerCounts listener, or (None, None)."""
    d = os.path.join(simout, "MonomerCounts")
    if not os.path.isdir(d):
        return None, None
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
    from cellarium import raw
    counts = np.asarray(raw.read_column(os.path.join(d, "monomerCounts")))
    names = None
    aj = os.path.join(d, "attributes.json")
    if os.path.exists(aj):
        attrs = json.load(open(aj))
        for v in attrs.values():
            if isinstance(v, list) and counts.ndim == 2 and len(v) == counts.shape[1]:
                names = v
                break
    return names, counts


def _variant_of(run_root: str) -> str:
    """Which variant produced this run — from `design.json`, else the variant directory in the path.

    Necessary because the multi-TU limit is a property of `gene_knockout`, not of every knockout variant."""
    try:
        with open(os.path.join(run_root, "design.json"), encoding="utf-8") as f:
            d = json.load(f)
        v = (d.get("params") or {}).get("variant") or d.get("perturbation")
        if v:
            return str(v)
    except Exception:
        pass
    # runs/<sim_path>/<variant>_<index>/<seed> — take the variant segment, dropping its numeric suffix
    for part in reversed(str(run_root).replace("\\", "/").split("/")):
        bits = part.split("_")
        if len(bits) > 1 and bits[-1].isdigit():
            return "_".join(bits[:-1])
    return "gene_knockout"


def check(run_root: str, genes: list[str]) -> dict:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
    from cellarium import raw, scope
    sos = raw.simout_dirs(run_root)
    if not sos:
        return {"ok": False, "why": f"no simOut under {run_root!r}"}
    names, counts = monomer_counts(sos[-1])
    if names is None:
        return {"ok": False, "why": "MonomerCounts has no readable name attribute — cannot verify"}

    # A knockout zeroes a TRANSCRIPTION UNIT, so the co-members on that TU go too. Check the whole footprint:
    # verifying only the named gene would call a partial knockout clean.
    # REFUSE on an unknown footprint. `ko_footprint` returns None for both "clean single-gene KO" and "not
    # cached", and reading that as the former made this script check only the named gene for six knockouts —
    # including fabI, lpxC and pgi, the WELL-6z4 cluster. An unchecked co-member is not a silenced one.
    unknown = [g for g in genes if not scope.footprint_known(g)]
    if unknown:
        return {"ok": False, "run_root": run_root, "unknown_footprint": unknown,
                "verdict": f"CANNOT VERIFY — no footprint record for {unknown}. Build it with "
                           f"scripts/build_ko_footprint.py. Refusing to report a clean knockout on the basis "
                           f"of a cache miss."}
    # And check the model-scope gate BEFORE the counts: a gene on several transcription units cannot be
    # silenced by this variant at all, so the run is not a knockout regardless of what the counts show.
    # Ask about the variant that ACTUALLY produced this run, read from its own provenance. Asking about
    # `gene_knockout` when the run used `graded_gene_knockout` refused a run that had worked: murA measured 0
    # copies and was still reported NOT A CLEAN KNOCKOUT, because the cached prediction describes a different
    # variant. A gate that cannot be satisfied by a correct run is the failure mode this file exists to catch.
    variant = _variant_of(run_root)
    cannot = {g: scope.ko_will_silence(g, variant=variant) for g in genes}
    blocked = {g: v for g, v in cannot.items() if v.get("will_silence") is False}
    gene_map = {}
    try:
        gene_map = json.load(open("data/cache/gene_map.json"))
    except Exception:
        pass

    out, verdicts = {}, []
    for g in genes:
        fp = scope.ko_footprint(g)
        targets = [g] + list((fp or {}).get("co_members") or [])
        for t in targets:
            mono = gene_map.get(t)
            if not mono:
                out[t] = {"status": "no monomer id in gene_map — not checkable"}
                continue
            if mono not in names:
                out[t] = {"status": "monomer absent from MonomerCounts — not expressed in this model"}
                continue
            col = counts[:, names.index(mono)]
            mx, mean = float(np.nanmax(col)), float(np.nanmean(col))
            silenced = mx == 0
            out[t] = {"monomer": mono, "max": mx, "mean": round(mean, 3),
                      "silenced": silenced,
                      "status": "SILENCED (count is 0 throughout)" if silenced else
                                f"STILL PRESENT — max {mx:.0f} copies. The knockout did NOT silence this gene."}
            verdicts.append(silenced)
    ok = bool(verdicts) and all(verdicts) and not blocked
    if blocked:
        out["_model_scope"] = {g: v["why"] for g, v in blocked.items()}
    return {"ok": ok, "run_root": run_root, "genes_checked": list(out), "detail": out,
            "model_scope_blocked": sorted(blocked), "variant": variant,
            "verdict": ("KNOCKOUT APPLIED — every gene on the target transcription unit is at zero copies."
                        if ok else
                        "NOT A CLEAN KNOCKOUT — at least one target gene is still expressed. Do NOT run the "
                        "arm on this configuration; a no-op knockout yields a plausible-looking null.")}


if __name__ == "__main__":
    res = check(sys.argv[1], sys.argv[2:])
    if res.get("variant"):
        print(f"  variant: {res['variant']}")
    for gene, d in (res.get("detail") or {}).items():
        # `_model_scope` is a {gene: reason} map, not a per-gene status record — printing d.get('status') on it
        # rendered the reason as a bare "None", hiding the very explanation the operator needs.
        if gene == "_model_scope":
            for g, why in (d or {}).items():
                print(f"  {g:8} MODEL SCOPE: {why}")
            continue
        print(f"  {gene:8} {d.get('status')}")
    print(f"\n{res['verdict'] if 'verdict' in res else res.get('why')}")
    sys.exit(0 if res.get("ok") else 1)
