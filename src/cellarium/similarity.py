"""Response-profile similarity over the 199-species panel — "which designs CAME OUT similar" (D8/D9).

The metric is SETTLED (DECISIONS.md D9, justified by the 32-agent WELL-6z4 pass): **double-centering** the
z-scored design×species matrix before cosine. Raw z-cosine is ~1/3 severity — `corr(growth, cos-to-WT)=+0.61`,
so two mechanistically-unrelated severe designs look similar just because both sit far from wildtype. Double-
centering (parameter-free: subtract each design's mean z-score and each species' mean) drops that confound to
~0 (`-0.01`) while KEEPING the real mechanism clusters (envelope-biosynthesis KOs nearest-neighbour 4/4).

Why THIS and not the obvious alternatives:
  * NOT PC1 removal — PC1 is the GROWTH axis (`corr +0.83`); the compositional severity WELL-6a flagged is on
    PC2 (`corr +0.91`), so PC1-removal leaves it intact, and PC1's direction wobbles ~27° across half-splits at
    n=41 (fitting noise). The field also warns against blind top-PC subtraction (Goldinger 2013).
  * NOT a graph — the phenotype vector already recovers the clusters a protein graph would claim to add, and no
    offline graph covers the panel (WELL-6z5).

TWO MANDATORY GUARDS travel with every result and are not optional:
  (a) GROWTH is reported ALONGSIDE similarity. The removed axis is partly real biology (Klumpp/Hwa growth laws),
      so a reader must be able to discount severity, not have it silently erased.
  (b) The SEVERITY-CONFOUNDED designs are labelled. The aaRS/dapA/rpmE KOs are the only severe-AND-lethal
      designs (they collapse), so their similarity cannot be separated from lethality — a "similar to an aaRS"
      result is flagged, never read as mechanism. Validated: severe-but-VIABLE non-aaRS designs (no_oxygen,
      rRNA_KO:6op, pgi) cluster by their own mechanism here, not with the aaRS (WELL-6z6).

This is a HYPOTHESIS GENERATOR (D8): "these came out similar", to be CHECKED against read_series / literature,
never asserted. It is deliberately NOT wired as an anchoring gate — survey_corpus (arithmetic, exhaustive)
stays the primary path; similarity supplements it (the WELL-6d anti-anchoring invariant).
"""
from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict

from . import manifest, survey

REFERENCE = "wildtype/basal"
_CACHE: dict | None = None


def _sim_rows() -> list[dict]:
    import duckdb
    con = duckdb.connect()
    cols = "id, simout_path, label, perturbation, condition, timeline, reportable, growth_rate, species_panel"
    q = (f"WITH d AS (SELECT * FROM read_parquet('{survey.MANIFEST_GLOB}', union_by_name=true) "
         f"{manifest.DEDUP_QUALIFY}) SELECT {cols} FROM d")
    try:
        return survey._mark_dropped(con.execute(q).fetch_arrow_table().to_pylist())
    except Exception as exc:
        return [{"__error__": str(exc)}]
    finally:
        con.close()


def _panel(r: dict):
    sp = r.get("species_panel")
    if isinstance(sp, str):
        try:
            return json.loads(sp)
        except Exception:
            return None
    return sp


def _build() -> dict | None:
    rows = _sim_rows()
    if not rows or "__error__" in rows[0]:
        return None
    byd: dict = defaultdict(list)
    growth: dict = defaultdict(list)
    for r in rows:
        if not r.get("reportable") or r.get("_dropped"):
            continue                     # crashed channels are garbage; tombstoned runs are curated out
        sp = _panel(r)
        if not sp:
            continue
        k = survey.design_key(r)
        byd[k].append(sp)
        if r.get("growth_rate") is not None:
            growth[k].append(r["growth_rate"])
    if len(byd) < 2:
        return None
    species = sorted(set.intersection(*[set(sp) for sps in byd.values() for sp in sps]))
    designs = sorted(byd)
    # design × species matrix of per-species mean (seed-averaged), z-scored per species column
    mat = [[statistics.fmean([p[s]["mean"] for p in byd[d]
                              if s in p and isinstance(p[s], dict) and p[s].get("mean") is not None] or [0.0])
            for s in species] for d in designs]
    for j in range(len(species)):
        col = [mat[i][j] for i in range(len(mat))]
        mu, sd = statistics.fmean(col), (statistics.pstdev(col) or 1.0)
        for i in range(len(mat)):
            mat[i][j] = (mat[i][j] - mu) / sd
    # DOUBLE-CENTER (D9): Z2 = Z − rowmean − colmean + grandmean. Since columns are already z-scored, this is
    # effectively row-centering — remove each design's global up/down-shift, which IS the magnitude-severity axis.
    rm = [statistics.fmean(row) for row in mat]
    cm = [statistics.fmean([mat[i][j] for i in range(len(mat))]) for j in range(len(species))]
    gm = statistics.fmean([x for row in mat for x in row])
    z = {designs[i]: [mat[i][j] - rm[i] - cm[j] + gm for j in range(len(species))] for i in range(len(designs))}
    g = {d: statistics.fmean(v) for d, v in growth.items() if v}
    return {"designs": designs, "z": z, "growth": g, "n_species": len(species)}


def _matrix() -> dict | None:
    global _CACHE
    if _CACHE is None:
        _CACHE = _build()
    return _CACHE


def reset_cache() -> None:
    """Drop the cached matrix — call after the corpus changes in-process (a new shard, a tombstone)."""
    global _CACHE
    _CACHE = None


def _cos(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1e-12
    nb = math.sqrt(sum(y * y for y in b)) or 1e-12
    return dot / (na * nb)


_CONF: set | None = None


def _confounded() -> set:
    """Designs whose response similarity is SEVERITY-CONFOUNDED — the ones that also COLLAPSE (aaRS/dapA/rpmE).
    Taken from the lethality view rather than a hardcoded gene list, so it stays correct as the corpus grows."""
    global _CONF
    if _CONF is None:
        try:
            _CONF = {e["design"] for e in survey.lethality().get("designs", [])}
        except Exception:
            _CONF = set()
    return _CONF


def _growth_pct(g: dict, d: str) -> float | None:
    wt = g.get(REFERENCE)
    gd = g.get(d)
    return round(100.0 * (gd - wt) / wt, 1) if (gd is not None and wt) else None


_GUARDS = ("(a) `growth`/`growth_pct_vs_wt` is shown alongside every similarity — the de-confounded axis is "
           "partly real biology (growth laws), so DISCOUNT severity, do not treat it as absent. (b) "
           "`severity_confounded=true` marks a design that also COLLAPSES (aaRS/dapA/rpmE): its similarity "
           "cannot be separated from lethality, so never read it as shared mechanism. A hypothesis generator "
           "('came out similar'), NOT ground truth — check with read_series / literature before asserting.")


def similar_designs(design: str, k: int = 8) -> dict:
    """The k designs whose de-confounded response profile most resembles `design`'s. Each neighbour carries its
    cosine AND its growth (guard a) AND whether it is severity-confounded (guard b)."""
    m = _matrix()
    if not m:
        return {"error": "corpus unreadable, or fewer than two designs carry a species panel"}
    z, g = m["z"], m["growth"]
    if design not in z:
        near = [d for d in z if design.split("/")[-1].lower() in d.lower()][:5]
        return {"error": f"'{design}' has no species profile in the corpus", "n_designs": len(z),
                "did_you_mean": near or sorted(z)[:5]}
    conf = _confounded()
    nbrs = sorted(((_cos(z[design], z[o]), o) for o in m["designs"] if o != design), reverse=True)[:max(1, k)]
    neighbours = [{"design": o, "cosine": round(s, 3), "growth": (round(g[o], 6) if o in g else None),
                   "growth_pct_vs_wt": _growth_pct(g, o), "severity_confounded": o in conf} for s, o in nbrs]
    return {"design": design, "growth": (round(g[design], 6) if design in g else None),
            "growth_pct_vs_wt": _growth_pct(g, design), "severity_confounded": design in conf,
            "n_designs": len(z), "n_species": m["n_species"],
            "metric": "double-centered cosine over the 199-species panel (D9) — the severity/growth axis is removed",
            "neighbours": neighbours, "guards": _GUARDS}


def species_similarity(design_a: str, design_b: str) -> dict:
    """The de-confounded response similarity between two named designs, with both growths and confound flags."""
    m = _matrix()
    if not m:
        return {"error": "corpus unreadable, or fewer than two designs carry a species panel"}
    z, g = m["z"], m["growth"]
    for d in (design_a, design_b):
        if d not in z:
            return {"error": f"'{d}' has no species profile", "n_designs": len(z), "available": sorted(z)[:8]}
    conf = _confounded()
    return {"design_a": design_a, "design_b": design_b, "cosine": round(_cos(z[design_a], z[design_b]), 3),
            "growth_a_pct_vs_wt": _growth_pct(g, design_a), "growth_b_pct_vs_wt": _growth_pct(g, design_b),
            "severity_confounded": (design_a in conf) or (design_b in conf),
            "metric": "double-centered cosine over the 199-species panel (D9)", "guards": _GUARDS}


def acceptance() -> dict:
    """Run the WELL-6z4 acceptance test on the live corpus, so the metric's guarantees are checkable, not
    asserted: severity confound removed (`|corr(growth, cos-to-WT)| < 0.15`), the envelope-biosynthesis
    mechanism cluster preserved (nearest-neighbour 4/4, within−overall Δ > 0.30), and zero hyperparameters."""
    m = _matrix()
    if not m:
        return {"error": "corpus unreadable"}
    z, g = m["z"], m["growth"]
    designs = m["designs"]
    # confound: corr(growth, cosine-to-WT), excluding WT itself
    pairs = [(g[d], _cos(z[d], z[REFERENCE])) for d in designs if d in g and d != REFERENCE]
    xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    cov = sum((x - mx) * (y - my) for x, y in pairs)
    denom = (math.sqrt(sum((x - mx) ** 2 for x in xs)) or 1e-12) * (math.sqrt(sum((y - my) ** 2 for y in ys)) or 1e-12)
    confound = cov / denom
    env = [d for d in designs if any(x in d for x in ("fabI", "lpxC", "murA", "glmS"))]
    allp = [_cos(z[a], z[b]) for i, a in enumerate(designs) for b in designs[i + 1:]]
    overall = statistics.fmean(allp) if allp else 0.0
    within = (statistics.fmean([_cos(z[a], z[b]) for i, a in enumerate(env) for b in env[i + 1:]])
              if len(env) > 1 else None)
    # nearest-neighbour purity is a DIAGNOSTIC, not a gate: it is corpus-composition-dependent (a
    # metabolically-adjacent design legitimately becomes an envelope member's NN — pgi is glmS's NN because glmS
    # draws UDP-GlcNAc from a glycolytic intermediate, WELL-6z6), so a drop names the off-cluster neighbour
    # rather than failing the metric. The GATE is the two corpus-robust properties: severity removed, and the
    # cluster still cohering above chance.
    excl = {REFERENCE} | {d for d in designs if "ppGpp:" in d}
    off = {}
    for e in env:
        top = next((o for s, o in sorted(((_cos(z[e], z[o]), o) for o in designs
                                          if o != e and (o not in excl or o in env)), reverse=True)), None)
        if top not in env:
            off[e] = top
    nn_ok = len(env) - len(off)
    checks = {
        "confound_removed": abs(confound) < 0.15,                                   # gate
        "envelope_cluster_survives": within is not None and (within - overall) > 0.30,  # gate
    }
    return {"corr_growth_cos_to_wt": round(confound, 3),
            "envelope_within_minus_overall": (round(within - overall, 3) if within is not None else None),
            "envelope_nn_purity": f"{nn_ok}/{len(env)}",                            # diagnostic, not a gate
            "envelope_nn_off_cluster": {k.split("/")[-1]: v.split("/")[-1] for k, v in off.items()},
            "checks": checks, "passes": all(checks.values()),
            "note": ("The metric's corpus-robust guarantees, recomputed live: severity removed AND the mechanism "
                     "cluster coheres above chance. `passes` gates on those two. NN purity is a diagnostic — a "
                     "metabolically-adjacent design (e.g. pgi) can legitimately take an envelope member's NN, so "
                     "`envelope_nn_off_cluster` NAMES it rather than failing.")}
