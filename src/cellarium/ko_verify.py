"""Did this knockout actually knock anything out? — a multi-level, control-anchored verification.

WHY THIS EXISTS. A `gene_knockout` design is named after a gene, but the variant zeroes a TRANSCRIPTION UNIT
(see `scope.ko_footprint`). Whether the named gene is silenced, whether its operon partners went with it, and
whether anything moved at all are three separate empirical questions — and each of them was answered WRONG at
least once during this investigation by reasoning instead of measuring:

  * first from the TU table alone ("KO:flgB silences nine genes" — true) generalised to designs where it is
    false ("KO:rpoB silences six" — rpoB is not silenced at all);
  * then from a tidy rule ("silenced iff the gene has exactly one TU", claimed 27/27) that was overfit to three
    genes and is refuted by `KO:dapA`, which fully silences `bamC` at n_tu = 2;
  * and a verdict read off mRNA alone, which cannot distinguish "not silenced" from "silenced but the transcript
    lingers".

THE METHOD, and the one part that is not obvious. A knocked-out cell grows differently, so its whole proteome
shifts — in `KO:rpoB`, rpoB protein sits at 85% of wildtype, which looks like a partial knockdown until you
notice that `rpoA`, which the design cannot touch, is at 81%. A raw ratio is therefore uninterpretable. Every
verdict here is made against a NULL DISTRIBUTION built from the genes the design does not target, so "silenced"
means *far below what happened to everything else*, not merely "lower than wildtype".

Levels are checked independently and reported separately, because they disagree informatively: a genuinely
silenced TU reads exactly 0.0 at BOTH mRNA and protein (measured for flgB/flgC), which is what rules out a
lingering-transcript explanation.

Reads local raw simOut only — no Docker (the native `WCECOLI_DIR` reader path), no API key, no new simulations.
"""

from __future__ import annotations

import statistics

# A ratio at or below this, when the untargeted null sits near 1.0, is silencing rather than a growth shift.
_SILENCED_MAX = 0.02
# How many null-distribution standard deviations below the null median counts as specific.
_SPECIFIC_Z = 3.0


def _ratio(target, reference) -> float | None:
    if reference in (None, 0) or target is None:
        return None
    return float(target) / float(reference)


def _null(ratios: dict, exclude: set) -> dict:
    """The distribution of target/reference over genes the design does NOT target — the growth-shift baseline."""
    vals = [r for g, r in ratios.items() if g not in exclude and r is not None]
    if len(vals) < 20:
        return {"n": len(vals), "median": None, "sd": None}
    med = statistics.median(vals)
    return {"n": len(vals), "median": round(med, 4),
            "sd": round(statistics.pstdev(vals) or 1e-9, 4),
            "p05": round(sorted(vals)[max(0, int(0.05 * len(vals)) - 1)], 4)}


def _classify(ratio: float | None, null: dict) -> str:
    if ratio is None:
        return "no_data"
    if ratio <= _SILENCED_MAX:
        return "silenced"
    med, sd = null.get("median"), null.get("sd")
    if med is None or not sd:
        return "expressed"                      # no null to judge against — do not over-claim
    if (med - ratio) / sd >= _SPECIFIC_Z:
        return "specifically_reduced"           # below the crowd by more than the crowd's own spread
    return "expressed"                          # indistinguishable from the global shift


def verify(gene: str, reference: str = "wildtype/basal", kinds: tuple = ("mrna", "protein")) -> dict:
    """Verify one `KO:<gene>` design against its reference, at every level, with a null-anchored verdict.

    Returns per level: the target's ratio and verdict, the same for every co-member of the zeroed TU, and the
    null distribution the verdicts were judged against. `verdict` is the cross-level summary — a design only
    counts as a real knockout of its named gene if EVERY level with data says silenced.
    """
    from . import differential, scope

    design = f"gene_knockout/KO:{gene}"
    t_roots = differential._design_run_roots(design)
    r_roots = differential._design_run_roots(reference)
    if not t_roots:
        return {"gene": gene, "error": f"no local raw for {design}"}
    if not r_roots:
        return {"gene": gene, "error": f"no local raw for reference {reference}"}

    fp = scope.ko_footprint(gene) or {}
    co = list(fp.get("co_members") or [])
    watch = [gene] + co
    out: dict = {"gene": gene, "design": design, "reference": reference,
                 "tu_id": fp.get("tu_id"), "tu_name": fp.get("tu_name"),
                 "n_target_runs": len(t_roots), "n_reference_runs": len(r_roots), "levels": {}}

    for kind in kinds:
        res = differential.all_gene_lfc(design, reference, kind)
        if not isinstance(res, dict) or "lfc" not in res:
            out["levels"][kind] = {"error": (res or {}).get("error", "no data")}
            continue
        by_symbol: dict = {}
        for _gid, v in res["lfc"].items():
            sym = v.get("symbol")
            if sym:
                by_symbol[sym] = _ratio(v.get("target"), v.get("reference"))
        null = _null(by_symbol, exclude=set(watch))
        out["levels"][kind] = {
            "null": null,
            "genes": {g: {"ratio": (round(by_symbol[g], 4) if by_symbol.get(g) is not None else None),
                          "verdict": _classify(by_symbol.get(g), null)}
                      for g in watch if g in by_symbol},
        }

    # cross-level summary for the NAMED gene: every level with data must agree it is silenced
    seen = [lv["genes"][gene]["verdict"] for lv in out["levels"].values()
            if isinstance(lv, dict) and gene in (lv.get("genes") or {})]
    if not seen:
        out["verdict"] = "unmeasurable"
    elif all(v == "silenced" for v in seen):
        out["verdict"] = "knocked_out"
    elif any(v == "silenced" for v in seen):
        out["verdict"] = "levels_disagree"      # e.g. transcript gone but protein lingering — worth a look
    elif any(v == "specifically_reduced" for v in seen):
        out["verdict"] = "partially_reduced"
    else:
        out["verdict"] = "NOT_knocked_out"
    out["levels_checked"] = sorted(k for k, v in out["levels"].items() if "error" not in v)
    # anything silenced that is NOT the named gene — the collateral, measured rather than predicted
    out["collateral_silenced"] = sorted(
        g for g in co
        if any(g in (lv.get("genes") or {}) and lv["genes"][g]["verdict"] == "silenced"
               for lv in out["levels"].values() if isinstance(lv, dict)))
    return out


def verify_corpus(reference: str = "wildtype/basal") -> dict:
    """Run `verify` over every single-gene KO design that has local raw. The standardized sweep."""
    from . import differential, survey

    rows = survey._deduped_rows(survey.CHANNELS)
    if not rows or "__error__" in rows[0]:
        return {"error": "no manifest"}
    keys = {survey.design_key(r) for r in rows}
    genes = sorted({k.split("KO:")[1] for k in keys if "/KO:" in k and "+" not in k})
    results, skipped = {}, []
    for g in genes:
        if not differential._design_run_roots(f"gene_knockout/KO:{g}"):
            skipped.append(g)
            continue
        results[g] = verify(g, reference)
    summary: dict = {}
    for g, r in results.items():
        summary.setdefault(r.get("verdict", "error"), []).append(g)
    return {"reference": reference, "n_verified": len(results), "skipped_no_local_raw": skipped,
            "summary": {k: sorted(v) for k, v in summary.items()}, "results": results,
            "note": ("Verdicts are anchored to a NULL DISTRIBUTION over untargeted genes, because a knockout "
                     "shifts the whole proteome — a raw ratio cannot distinguish silencing from that shift.")}
