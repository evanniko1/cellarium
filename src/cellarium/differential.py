"""Differential top-movers — what changed most in a design vs a reference.

The interchangeable-panel idea (esp. for KOs) solved data-drivenly: instead of a fixed species list, DISCOVER
what moved. Two levels:
  - `summary(target, reference)`  — channels + pathways ranked by |log2 fold-change|, from the manifest (instant).
  - `top_movers(result_id, ref)`  — individual proteins/mRNAs/metabolites ranked by fold-change between two runs,
    read from simOut in the container, with gene-symbol annotation for proteins.
Pairs with survey_corpus: survey the whole corpus, then diff a standout design against control.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

from . import survey

REFERENCE = "wildtype/basal"


def _design_means() -> tuple[dict, list[str]]:
    """{ 'perturbation/condition': {channel|pw: mean across seeds} }, and the channel list (incl. pathways)."""
    rows = survey._deduped_rows(survey.CHANNELS)
    if not rows or "__error__" in rows[0]:
        return {}, []
    pw_keys: set[str] = set()
    for r in rows:
        try:
            r["_pw"] = json.loads(r.get("pathways") or "{}")
        except Exception:
            r["_pw"] = {}
        pw_keys |= set(r["_pw"])
    channels = survey.CHANNELS + [f"pw:{k}" for k in sorted(pw_keys)]

    def val(r, ch):
        return r["_pw"].get(ch[3:]) if ch.startswith("pw:") else r.get(ch)

    by: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by[f'{r["perturbation"]}/{r["condition"]}'].append(r)

    def dmean(rs, ch):
        vals = [v for v in (val(r, ch) for r in rs) if v is not None]
        return sum(vals) / len(vals) if vals else None

    return {d: {ch: dmean(rs, ch) for ch in channels} for d, rs in by.items()}, channels


def summary(target: str, reference: str = REFERENCE, top: int = 15) -> dict:
    """Channels + pathways ranked by |log2 fold-change| of `target` vs `reference` — what moved most."""
    means, channels = _design_means()
    if not means:
        return {"error": "corpus empty or unreadable."}
    t, r = means.get(target), means.get(reference)
    if t is None:
        return {"error": f"no design '{target}'.", "available": sorted(means)}
    if r is None:
        return {"error": f"no reference '{reference}'.", "available": sorted(means)}
    movers = []
    for ch in channels:
        tv, rv = t.get(ch), r.get(ch)
        if tv is None or rv in (None, 0):
            continue
        log2fc = round(math.log2(tv / rv), 2) if (tv > 0 and rv > 0) else None
        movers.append({"quantity": ch, "target": round(tv, 4), "reference": round(rv, 4),
                       "pct": round(100 * (tv - rv) / rv, 1), "log2fc": log2fc})
    movers.sort(key=lambda m: abs(m["log2fc"]) if m["log2fc"] is not None else abs(m["pct"]) / 100, reverse=True)
    return {"target": target, "reference": reference, "ranked": movers[:top],
            "note": "Channels + pathways ranked by |log2 fold-change| (else |%|) vs the reference — what moved most."}


def _reverse_gene_map() -> dict[str, str]:
    p = Path("data/cache/gene_map.json")
    if not p.exists():
        return {}
    return {v: k for k, v in json.loads(p.read_text(encoding="utf-8")).items()}


def top_movers(result_id: str, reference_id: str, kind: str = "protein", top: int = 12) -> dict:
    """Individual species (default proteins) ranked by fold-change between two runs' simOut."""
    from . import reader, store

    d, r = store.simout_path(result_id), store.simout_path(reference_id)
    if not d or not Path(d).exists():
        return {"error": f"simOut not local for '{result_id}'."}
    if not r or not Path(r).exists():
        return {"error": f"simOut not local for reference '{reference_id}'."}
    out = reader.differential(Path(d), Path(r), kind, top)
    if kind == "protein" and "up" in out:  # annotate monomer IDs with gene symbols
        rev = _reverse_gene_map()
        for m in out.get("up", []) + out.get("down", []):
            m["symbol"] = rev.get(m["id"])
    return out
