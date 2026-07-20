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

from . import stats, survey

REFERENCE = "wildtype/basal"


def _design_seed_values() -> tuple[dict, list[str]]:
    """{ 'perturbation/condition': {channel: [per-seed values]} } + the channel list (incl. pathways). Keeps the
    UN-aggregated replicates behind each design/channel, so a per-channel two-sample test (DS-3) can run on the real
    seed spread rather than a single mean. The means view (`_design_means`) is derived from this."""
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

    out: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        d = out[f'{r["perturbation"]}/{r["condition"]}']
        for ch in channels:
            v = val(r, ch)
            if v is not None:
                d[ch].append(float(v))
    return {d: dict(chv) for d, chv in out.items()}, channels


def _design_means() -> tuple[dict, list[str]]:
    """{ 'perturbation/condition': {channel|pw: mean across seeds} }, and the channel list (incl. pathways)."""
    vals, channels = _design_seed_values()
    means = {d: {ch: (sum(chv[ch]) / len(chv[ch]) if chv.get(ch) else None) for ch in channels}
             for d, chv in vals.items()}
    return means, channels


def summary(target: str, reference: str = REFERENCE, top: int = 15) -> dict:
    """Channels + pathways ranked by |log2 fold-change| of `target` vs `reference` — what moved most, each shown
    mover carrying a per-channel Welch t-test on the seed replicates (DS-3) so a fold-change isn't read as real
    without checking it clears the seed noise."""
    vals, channels = _design_seed_values()
    if not vals:
        return {"error": "corpus empty or unreadable."}
    t, r = vals.get(target), vals.get(reference)
    if t is None:
        return {"error": f"no design '{target}'.", "available": sorted(vals)}
    if r is None:
        return {"error": f"no reference '{reference}'.", "available": sorted(vals)}
    movers = []
    for ch in channels:
        ta, ra = t.get(ch), r.get(ch)
        if not ta or not ra:
            continue
        tv, rv = sum(ta) / len(ta), sum(ra) / len(ra)
        if rv == 0:
            continue
        log2fc = round(math.log2(tv / rv), 2) if (tv > 0 and rv > 0) else None
        movers.append({"quantity": ch, "target": round(tv, 4), "reference": round(rv, 4),
                       "pct": round(100 * (tv - rv) / rv, 1), "log2fc": log2fc, "_ta": ta, "_ra": ra})
    movers.sort(key=lambda m: abs(m["log2fc"]) if m["log2fc"] is not None else abs(m["pct"]) / 100, reverse=True)
    ranked = movers[:top]
    for m in ranked:   # DS-3: a two-sample Welch t-test on the seed replicates behind each shown mover (or a note)
        w = stats.welch_t(m.pop("_ta"), m.pop("_ra"))
        if w is None:
            m["significance"] = "descriptive only — <2 seeds on one side; use disconfirm / top_movers for a tested claim"
        else:
            m["welch_t"], m["p_value"], m["n_seeds"] = w["t"], w["p"], [w["n_a"], w["n_b"]]
            m["significant_p05"] = (w["p"] is not None and w["p"] < 0.05)
    return {"target": target, "reference": reference, "ranked": ranked,
            "viability": _viability_for(target),  # is the target even a dividing cell? (a KO reroutes -> flat channels + viable)
            "note": "Channels + pathways ranked by |log2 fold-change| (else |%|), each shown mover carrying a Welch "
                    "t-test on the seed replicates (`welch_t`/`p_value`/`significant_p05`) — a large fold-change with "
                    "p>0.05 is within seed noise, not a real move. Check `viability`: flat channels on a VIABLE KO = "
                    "reroute (no phenotype); on an INVIABLE one the fold-changes are pre-crash garbage."}


def _viability_for(label: str) -> dict:
    """The target design's cross-seed viability verdict (perturbation/condition label) — so a differential is read
    with 'did the cell even divide?' in view. Absent viability columns / unknown design -> a soft note, not an error."""
    from . import store

    pert, _, cond = label.partition("/")
    try:
        out = store.viability(pert, cond or None)
    except Exception:
        return {"verdict": "unknown"}
    if "error" in out or not out.get("designs"):
        return {"verdict": "unknown"}
    d = out["designs"][0] if len(out["designs"]) == 1 else next(
        (x for x in out["designs"] if x.get("condition") == cond), out["designs"][0])
    return {"verdict": d.get("verdict"), "min_division_rate": d.get("min_division_rate"),
            "max_gens_reached": d.get("max_gens_reached")}


def _reverse_gene_map() -> dict[str, str]:
    p = Path("data/cache/gene_map.json")
    if not p.exists():
        return {}
    return {v: k for k, v in json.loads(p.read_text(encoding="utf-8")).items()}


_CISTRON_MAP_CACHE = Path("data/cache/cistron_map.json")


def _cistron_symbol_map() -> dict[str, str]:
    """cistron_id -> gene symbol — the id space the mRNA reader returns (`mRNA_cistron_ids`, e.g. 'EG10016_RNA[c]').
    This is NOT the monomer-keyed `_reverse_gene_map` (monomer ids like '6PFK-1-MONOMER[c]' don't share a base with
    cistron ids, so that map annotates every mRNA gene as None). Lazily dumped from sim_data via the worker's
    gene-map mode (needs the model image); returns {} when unavailable — the concordance's namespace diagnostic then
    tells the user to regenerate it."""
    if not _CISTRON_MAP_CACHE.exists():
        try:
            from . import reader
            gm = reader.gene_map()
            if isinstance(gm, dict) and gm.get("cistron_symbols"):
                _CISTRON_MAP_CACHE.parent.mkdir(parents=True, exist_ok=True)
                _CISTRON_MAP_CACHE.write_text(json.dumps(gm["cistron_symbols"]), encoding="utf-8")
        except Exception:
            return {}
    try:
        return json.loads(_CISTRON_MAP_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _design_run_roots(label: str) -> list[Path]:
    """All local run roots for a design label 'perturbation/condition' (one per seed)."""
    from . import store

    roots = []
    for r in store.list_results():
        if f'{r.get("perturbation")}/{r.get("condition")}' == label:
            p = store.simout_path(r["id"])
            if p and Path(p).exists():
                roots.append(Path(p))
    return roots


def top_movers(target: str, reference: str = REFERENCE, kind: str = "protein", top: int = 12) -> dict:
    """Individual species (default proteins) ranked by SEED-AVERAGED fold-change of a target design vs a
    reference design — count-floored and reproducibility-flagged (hardened against single-run stochastic noise)."""
    from . import reader

    t_roots, r_roots = _design_run_roots(target), _design_run_roots(reference)
    if not t_roots:
        return {"error": f"no local runs for design '{target}'."}
    if not r_roots:
        return {"error": f"no local runs for reference '{reference}'."}
    out = reader.differential(t_roots, r_roots, kind, top)
    if kind == "protein" and "up" in out:  # annotate monomer IDs with gene symbols (incl. the mid-rank sample)
        rev = _reverse_gene_map()
        for m in out.get("up", []) + out.get("down", []) + out.get("mid_rank_sample", []):
            m["symbol"] = rev.get(m["id"])
    return out


def all_gene_lfc(target: str, reference: str = REFERENCE, kind: str = "mrna") -> dict:
    """EVERY gene's seed-averaged log2fc of target vs reference — the unbiased FULL distribution (SCI-2c), not just
    the FDR-significant movers `top_movers` returns (which range-restricts the sim-vs-RNA-seq concordance). Each
    entry is symbol-annotated via the gene map so the caller can join it to a b-number reference."""
    from . import reader

    t_roots, r_roots = _design_run_roots(target), _design_run_roots(reference)
    if not t_roots:
        return {"error": f"no local runs for design '{target}'."}
    if not r_roots:
        return {"error": f"no local runs for reference '{reference}'."}
    out = reader.gene_lfc(t_roots, r_roots, kind)
    if isinstance(out, dict) and isinstance(out.get("lfc"), dict):
        # annotate per-kind by the id space the worker returns: mRNA ids are cistron_ids (cistron->symbol map),
        # protein ids are monomer_ids (the monomer reverse map). Using the wrong one annotates every gene as None.
        annot = _cistron_symbol_map() if kind == "mrna" else _reverse_gene_map()
        out["lfc"] = {gid: {**v, "symbol": annot.get(gid)} for gid, v in out["lfc"].items()}
    return out
