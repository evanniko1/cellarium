"""SCI-DIL-1 — the inherited-pool DILUTION CLOCK: fit the known law, report the RESIDUAL.

The mechanism is published and named. A knockout stops SYNTHESIS but not possession: the existing protein pool
is split between daughters at each division, so per-cell abundance decays as **n(g) = n₀·2⁻ᵍ** and the phenotype
arrives generations after the genotype. That is *phenotypic delay via dilution of sensitive molecules* —
**Carballo-Pacheco, Nicol, Bergmiller, Guet & Tkačik 2020, PLoS Comput Biol 16(5):e1007930, PMID 32469859**.
Presenting it as our discovery would be refuted on sight, so this module does not claim it.

What IS ours is the measurement. Given the law, each design's deviation FROM it is informative:

  * decay ≈ 2⁻ᵍ  → the phenotype is dilution-limited; the collapse generation is predictable from the initial
    pool alone, and nothing else needs invoking;
  * decay FASTER than 2⁻ᵍ → something removes the protein beyond dilution (active degradation, or the target is
    consumed), so dilution alone under-predicts when the cell fails;
  * decay SLOWER than 2⁻ᵍ → residual synthesis, an unaccounted source, or an incomplete knockout — which is a QC
    signal about the design as much as about the biology.

So the tool fits log2(n) against generation, reports the slope with its interval, and compares it to the
predicted −1. The citation carries the law; the residual is the measurement. That distinction is the whole point
of the module.

Uses the per-generation series the corpus already stores; local raw only where a per-species trace is needed.
"""

from __future__ import annotations

import json
import math
import statistics

from . import survey

PREDICTED_SLOPE = -1.0          # log2(n) per generation under pure halving


def _ols(xs: list[float], ys: list[float]) -> dict | None:
    """Slope + intercept + t-based 95% CI on the slope. Stdlib only; None when under-determined."""
    n = len(xs)
    if n < 3:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    icpt = my - slope * mx
    resid = [y - (icpt + slope * x) for x, y in zip(xs, ys)]
    dof = n - 2
    if dof <= 0:
        return {"slope": slope, "intercept": icpt, "ci95": None, "r2": None, "n": n}
    se = math.sqrt(sum(r * r for r in resid) / dof / sxx)
    from . import stats
    hw = stats.t_critical_95(dof) * se
    sst = sum((y - my) ** 2 for y in ys)
    return {"slope": slope, "intercept": icpt, "ci95": [slope - hw, slope + hw],
            "r2": (1 - sum(r * r for r in resid) / sst) if sst > 0 else None, "n": n}


def _as_list(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return []
    return v or []


def dilution_clock(design: str, channel: str = "growth_rate") -> dict:
    """Fit the per-generation decay of `channel` against the dilution law n(g)=n₀·2⁻ᵍ and report the RESIDUAL.

    The channel is a proxy for the inherited pool: as the diluting protein runs out, the channel it supports
    falls. A slope near −1 in log2 space is the dilution clock; a slope steeper or shallower is the finding.

    Uses only QC-ok generations, so a collapsed generation's garbage cannot bend the fit — which matters here
    more than usual, because the collapse is exactly what we are timing."""
    rows = survey._leth_rows()
    if not rows or "__error__" in rows[0]:
        return {"error": rows[0].get("__error__") if rows else "corpus unreadable"}
    key = {"growth_rate": "growth", "growth": "growth", "ppgpp_conc": "ppgpp", "ppgpp": "ppgpp"}.get(channel)
    if not key:
        return {"error": f"'{channel}' is not stored per generation — only growth_rate/ppgpp_conc are"}
    xs, ys, per_gen = [], [], []
    n_seeds = 0
    for r in rows:
        if survey.design_key(r) != design or r.get("_dropped"):
            continue
        n_seeds += 1
        gq = _as_list(r.get("generation_qc"))
        for p in _as_list(r.get("per_generation")):
            if not isinstance(p, dict) or p.get("i") is None or p.get(key) is None:
                continue
            i = int(p["i"])
            if i < len(gq) and gq[i] != "ok":
                continue                       # a collapsed generation's value is garbage, not a data point
            v = float(p[key])
            if v <= 0:
                continue                       # log2 undefined; a zero is a collapse, handled as a gap not a fit
            xs.append(float(i))
            ys.append(math.log2(v))
            per_gen.append({"generation": i, "value": round(v, 8)})
    if not n_seeds:
        return {"error": f"'{design}' is not a design in the corpus"}
    fit = _ols(xs, ys)
    if not fit:
        return {"design": design, "channel": channel, "n_points": len(xs), "n_seeds": n_seeds,
                "error": "need >=3 QC-ok generations with a positive value to fit a decay",
                "note": "a design that collapses at generation 1-2 cannot be fitted — that is itself the finding"}
    slope = fit["slope"]
    ci = fit["ci95"]
    consistent = bool(ci and ci[0] <= PREDICTED_SLOPE <= ci[1])
    if consistent:
        verdict, reading = "dilution_limited", (
            "the decay is statistically consistent with pure halving — the phenotype timing follows from the "
            "initial pool alone, and no additional mechanism need be invoked")
    elif slope < PREDICTED_SLOPE:
        verdict, reading = "faster_than_dilution", (
            "the channel falls FASTER than halving — something removes or consumes the pool beyond division, so "
            "dilution alone UNDER-predicts when the cell fails")
    else:
        verdict, reading = "slower_than_dilution", (
            "the channel falls SLOWER than halving — residual synthesis, an unaccounted source, or an incomplete "
            "knockout; treat this as a QC signal about the design as much as a claim about the biology")
    return {
        "design": design, "channel": channel, "n_seeds": n_seeds, "n_points": fit["n"],
        "observed_slope_log2_per_generation": round(slope, 3),
        "slope_ci95": ([round(c, 3) for c in ci] if ci else None),
        "predicted_slope": PREDICTED_SLOPE,
        "residual_vs_dilution": round(slope - PREDICTED_SLOPE, 3),
        "r2": (round(fit["r2"], 3) if fit.get("r2") is not None else None),
        "verdict": verdict, "reading": reading,
        "per_generation": per_gen,
        "law": ("n(g) = n0 * 2^-g — phenotypic delay via dilution of sensitive molecules. PUBLISHED AND NAMED: "
                "Carballo-Pacheco et al. 2020, PLoS Comput Biol 16(5):e1007930, PMID 32469859. This tool does "
                "NOT claim the law; it fits it and reports the DEVIATION, which is the measurement."),
        "note": ("Slope is log2(channel) regressed on generation index, over QC-ok generations only. A slope "
                 "whose 95% CI contains -1 is consistent with pure dilution. The residual is the finding: it "
                 "says whether this design's collapse needs a mechanism BEYOND halving."),
    }


def protein_clock(design: str, gene: str | None = None) -> dict:
    """The REAL dilution clock: the knocked-out protein's own per-generation abundance, fitted against 2⁻ᵍ.

    `dilution_clock` above fits a downstream channel (growth), which is a PROXY — and a poor one, because growth
    is supported by the whole proteome and does not halve when one protein does. Every design there reads
    `slower_than_dilution` for exactly that reason. The law is about the POOL, so this reads the pool: the
    target monomer's count per generation from `MonomerCounts` in local raw simOut.

    This is the measurement the citation cannot supply: whether THIS knockout's protein actually follows the
    published halving, or departs from it (degradation, consumption, or residual synthesis)."""
    import numpy as np

    from . import raw, scope
    gene = gene or (design.split("KO:")[-1].split("+")[0] if "KO:" in design else None)
    if not gene:
        return {"error": f"could not infer the target gene from '{design}' — pass `gene=` explicitly"}
    runs = raw.seed_runs(design)
    if not runs:
        return {"error": f"no local raw simOut for '{design}' — the protein clock needs per-generation counts"}
    # resolve the gene -> monomer id via the committed scope cache (same map the KO footprint uses)
    entry = (scope._gene_scope() if hasattr(scope, "_gene_scope") else {}).get(gene) if gene else None
    monomer = (entry or {}).get("monomer_id") if isinstance(entry, dict) else None
    series, used = [], []
    for r in runs:
        sos = raw.simout_dirs(r["root"])
        if len(sos) < 3:
            continue
        for gi, so in enumerate(sos):
            try:
                counts = np.asarray(raw.read_column(f"{so}/MonomerCounts/monomerCounts"), dtype=float)
                import json as _json
                ids = _json.load(open(f"{so}/MonomerCounts/attributes.json", encoding="utf-8"))["monomerIds"]
            except Exception:
                continue
            idx = None
            if monomer and monomer in ids:
                idx = ids.index(monomer)
            else:                                   # fall back to a case-insensitive gene-name match
                low = gene.lower()
                cand = [i for i, m in enumerate(ids) if low in str(m).lower()]
                idx = cand[0] if cand else None
            if idx is None:
                continue
            series.append((gi, float(np.mean(counts[:, idx]))))
            if r.get("seed") not in used:
                used.append(r.get("seed"))
    if len({g for g, _v in series}) < 3:
        return {"error": f"need >=3 generations of local raw for '{design}' (found "
                         f"{len({g for g, _v in series})}) — the protein clock needs depth",
                "design": design, "gene": gene}
    xs = [float(g) for g, v in series if v > 0]
    ys = [math.log2(v) for _g, v in series if v > 0]
    fit = _ols(xs, ys)
    if not fit:
        return {"error": "could not fit", "design": design, "gene": gene}
    slope, ci = fit["slope"], fit["ci95"]
    consistent = bool(ci and ci[0] <= PREDICTED_SLOPE <= ci[1])
    return {
        "design": design, "gene": gene, "monomer": monomer, "seeds": used, "n_points": fit["n"],
        "observed_slope_log2_per_generation": round(slope, 3),
        "slope_ci95": ([round(c, 3) for c in ci] if ci else None),
        "predicted_slope": PREDICTED_SLOPE, "residual_vs_dilution": round(slope - PREDICTED_SLOPE, 3),
        "r2": (round(fit["r2"], 3) if fit.get("r2") is not None else None),
        "verdict": ("dilution_limited" if consistent else
                    ("faster_than_dilution" if slope < PREDICTED_SLOPE else "slower_than_dilution")),
        "per_generation": [{"generation": g, "count": round(v, 2)} for g, v in sorted(series)],
        "law": ("n(g)=n0*2^-g — Carballo-Pacheco et al. 2020, PMID 32469859. Cited, not claimed; the RESIDUAL "
                "is the measurement."),
        "note": ("The TARGET protein's own abundance per generation, which is what the dilution law describes — "
                 "unlike `dilution_clock`, which fits a downstream channel and therefore reads "
                 "'slower_than_dilution' for everything by construction."),
    }


def clock_across_corpus(channel: str = "growth_rate", min_generations: int = 3) -> dict:
    """The dilution clock for every design with enough depth — which designs follow the law, and which deviate.

    The comparative view is where it earns its place: a KO that decays faster than its peers is doing something
    the others are not, and that is visible only against the shared baseline of the law."""
    rows = survey._leth_rows()
    if not rows or "__error__" in rows[0]:
        return {"error": rows[0].get("__error__") if rows else "corpus unreadable"}
    designs = sorted({survey.design_key(r) for r in rows if not r.get("_dropped")})
    out, skipped = [], 0
    for d in designs:
        r = dilution_clock(d, channel)
        if "error" in r or r.get("n_points", 0) < min_generations:
            skipped += 1
            continue
        out.append({k: r[k] for k in ("design", "observed_slope_log2_per_generation", "slope_ci95",
                                      "residual_vs_dilution", "r2", "verdict", "n_seeds", "n_points")})
    out.sort(key=lambda e: e["observed_slope_log2_per_generation"])
    return {"channel": channel, "n_designs": len(out), "n_skipped_too_shallow": skipped,
            "designs": out,
            "law": "n(g)=n0*2^-g (Carballo-Pacheco et al. 2020, PMID 32469859) — cited, not claimed",
            "note": ("Sorted steepest-decay first. `verdict=faster_than_dilution` marks designs whose collapse "
                     "needs a mechanism beyond halving; `slower_than_dilution` can indicate an incomplete "
                     "knockout and is a QC signal. Most designs in this corpus are too shallow to fit — that is "
                     "reported as `n_skipped_too_shallow`, never hidden.")}
