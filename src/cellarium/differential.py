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
    # ONE shared row source, asked for BY PURPOSE (H-17b). This used to be a private copy that, unlike
    # survey_corpus's, never filtered on `reportable`, so every Welch test here silently averaged in crashed
    # runs. Going through `hygiene.rows("analysis")` rather than calling the primitive directly is what makes
    # that impossible to reintroduce: the purpose names the filters, and `ctx["NOT_for"]` says out loud that
    # this set cannot be used to count lethality.
    from . import hygiene
    rows, _ctx = hygiene.rows("analysis")
    channels = _ctx["channels"]
    if not rows:
        return {}, []
    val = survey.channel_value

    out: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        d = out[survey.design_key(r)]
        # A run's GENERATION DEPTH is part of WHAT WAS MEASURED, not noise: a channel is the LAST generation's
        # time-mean, so a 1-generation run reports generation 0 and a 7-generation run reports generation 6.
        # Recorded per seed so a comparison can check the two sides measured the same generation.
        d["_depths"].append(survey.depth(r))
        for ch in channels:
            v = val(r, ch)
            if v is not None:
                d[ch].append(float(v))
    return {d: dict(chv) for d, chv in out.items()}, channels


def _depths_of(design: str) -> list:
    """The distinct generation depths a design's seeds ran to."""
    vals, _ = _design_seed_values()
    return sorted({d for d in ((vals.get(design) or {}).get("_depths") or []) if d is not None})


_REF_TRAJ_CACHE: dict | None = None


def _reference_trajectory() -> dict:
    """Mean growth per GENERATION INDEX for the reference design — the model's own drift curve, measured, so the
    depth note can quote how much the reference moves over a given gap instead of asserting it. Growth is the
    representative channel because it is one of the two stored per-generation (with ppGpp) and it is monotone.

    {gen_index: mean_growth_at_that_index}. Cached; empty if per_generation is unavailable."""
    global _REF_TRAJ_CACHE
    if _REF_TRAJ_CACHE is not None:
        return _REF_TRAJ_CACHE
    import json
    import statistics
    from collections import defaultdict
    by_i: dict = defaultdict(list)
    for r in survey._deduped_rows(["per_generation"]):
        if survey.design_key(r) != REFERENCE or not r.get("reportable"):
            continue
        pg = r.get("per_generation")
        if isinstance(pg, str):
            try:
                pg = json.loads(pg)
            except Exception:
                pg = None
        for p in pg or []:
            if isinstance(p, dict) and p.get("growth") is not None and p.get("i") is not None:
                by_i[int(p["i"])].append(float(p["growth"]))
    _REF_TRAJ_CACHE = {i: statistics.fmean(v) for i, v in by_i.items() if v}
    return _REF_TRAJ_CACHE


def _reference_drift_pct(depth_a: int, depth_b: int) -> float | None:
    """How much the reference's growth changes between the generations that depths a and b REPORT (depth d reports
    generation d-1). This is the magnitude a depth gap can inject into a comparison — a data-grounded number, not
    an assertion. None when the trajectory does not cover both generations."""
    traj = _reference_trajectory()
    ga, gb = (depth_a or 0) - 1, (depth_b or 0) - 1
    va, vb = traj.get(ga), traj.get(gb)
    if va is None or vb is None or not va:
        return None
    return round(100.0 * (vb - va) / va, 1)


def _depth_note(target: str, reference: str, dt: list, dr: list, shared: list) -> str:
    """A soft, quantified exploration signal for a depth-mismatched comparison. Never gates; never calls the
    comparison invalid or a finding. Names the gap, the reference's own drift over it, and what to run deeper."""
    deeper = reference if (max(dr) if dr else 0) >= (max(dt) if dt else 0) else target
    shallower = target if deeper == reference else reference
    # The confound is the RANGE of generations this comparison spans (shallowest vs deepest either side reports),
    # because that is the drift blended into the pooled means — not the min-to-min gap, which can be zero even
    # when one side pools much deeper runs.
    alld = (dt or []) + (dr or [])
    drift = _reference_drift_pct(min(alld), max(alld)) if alld else None
    mag = (f"across the generations this comparison spans, the wild-type reference's own growth moves ~{abs(drift)}%, "
           f"so read a difference smaller than that as possibly generation drift rather than the perturbation"
           if drift is not None else "the reference's per-generation drift over that span is not measurable here")
    return (f"exploration signal (not a verdict): target ran to generations {dt}, reference to {dr}. A channel is "
            f"the last generation's mean, so these report different generations of a lineage; {mag}. "
            + (f"For a like-for-like read, restrict to the shared depth {shared}; "
               if shared else "There is no shared depth yet; ")
            + f"consider running {shallower} deeper to match {deeper}. Not a reason to discount the comparison — "
              f"a reason to check it.")


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
        miss = survey.arm_miss(target)
        return miss if miss else {"error": f"no design '{target}'.", "available": sorted(vals)}
    if r is None:
        miss = survey.arm_miss(reference)
        return miss if miss else {"error": f"no reference '{reference}'.", "available": sorted(vals)}
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
    _dt, _dr = _depths_of(target), _depths_of(reference)
    _shared = sorted(set(_dt) & set(_dr))
    for m in ranked:   # DS-3: a two-sample Welch t-test on the seed replicates behind each shown mover (or a note)
        w = stats.welch_t(m.pop("_ta"), m.pop("_ra"))
        if w is None:
            m["significance"] = "descriptive only — <2 seeds on one side; use disconfirm / top_movers for a tested claim"
        else:
            m["welch_t"], m["p_value"], m["n_seeds"] = w["t"], w["p"], [w["n_a"], w["n_b"]]
            m["significant_p05"] = (w["p"] is not None and w["p"] < 0.05)
            # DEPTH MISMATCH — a SIGNAL FOR EXPLORATION, not a verdict (ADR-1). A channel is the last
            # generation's mean, so a target at depth d_t and a reference at depth d_r report different
            # generations of a lineage, and the model drifts between them. We do NOT gate the comparison and do
            # NOT frame the difference as a finding that overturns anything — we say how far apart they are,
            # quantify HOW MUCH the reference itself moves over that span (so a reader can tell a 1% from a 30%
            # confound), and suggest deepening the shallower case. Soft in tone, specific in magnitude.
            if _dt != _dr:
                m["depth_note"] = _depth_note(target, reference, _dt, _dr, _shared)
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
        if survey.design_key(r) == label:
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
