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
    # The PRE-double-centering (column-z only) profile is kept so the transform's benefit can be MEASURED against
    # its own baseline rather than asserted from the docstring. `mat` is not mutated by the comprehension above.
    z_raw = {designs[i]: list(mat[i]) for i in range(len(designs))}
    g = {d: statistics.fmean(v) for d, v in growth.items() if v}
    return {"designs": designs, "z": z, "z_raw": z_raw, "growth": g, "n_species": len(species)}


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


def severity_confound(vecs: dict, g: dict, designs: list | None = None) -> float:
    """corr(growth, cosine-to-wildtype) over designs — the severity confound, on ANY profile dict. Exposed so the
    shipped (double-centered) profile and its own pre-transform baseline are measured by the SAME code path."""
    ds = designs if designs is not None else list(vecs)
    pairs = [(g[d], _cos(vecs[d], vecs[REFERENCE])) for d in ds if d in g and d != REFERENCE and d in vecs]
    if len(pairs) < 3:
        return 0.0
    xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    cov = sum((x - mx) * (y - my) for x, y in pairs)
    denom = (math.sqrt(sum((x - mx) ** 2 for x in xs)) or 1e-12) * (math.sqrt(sum((y - my) ** 2 for y in ys)) or 1e-12)
    return cov / denom


# The null distribution is capped so it stays computable: C(50,3)=19,600 is exhaustive, C(50,6)=15,890,700
# is not, and a safeguard that hangs is worse than none.
_NULL_CAP = 50_000

ENVELOPE_GENES = ("fabI", "lpxC", "murA", "glmS")


def envelope_cluster(designs: list[str]) -> list[str]:
    """The envelope-biosynthesis mechanism cluster: FULL knockouts of the envelope genes, matched on identity.

    Was `any(x in d for x in ENVELOPE_GENES)` — a SUBSTRING match, and substrings do not know what kind of
    experiment they are matching. It admitted `graded_gene_knockout/KO:murA#expr:0.9`, a partial knockdown that
    leaves the protein at ~90% of wild type, into a cluster whose claim is that severe lesions in one mechanism
    resemble each other. `gene_knockout/KO:murA` itself is absent from the reportable set for an unrelated and
    already-settled reason (verified no-op: murA has n_tu=2, the variant zeroes one transcription unit and the
    gene keeps being expressed), so the substring was re-admitting murA through a different perturbation type
    after it had been excluded on the merits.

    The cluster is therefore defined the way the original claim was: full knockouts of these genes. That is a
    membership rule with no threshold in it — no dose cutoff, no hyperparameter — which is the property the
    acceptance test asserts about itself.

    MEASURED 2026-08-08, and reported because this change moves the gate from FAIL to PASS and that is exactly
    when a selector edit deserves scrutiny rather than less:
        substring (6 members, 3 of them graded murA)   delta +0.105   gate > +0.30  FAIL
        full knockouts (fabI, lpxC, glmS)              delta +0.419                 PASS
        full knockouts + the STRONGEST graded murA     delta +0.133                 FAIL
    The third line is the one that matters: admitting only the 90%-knockdown dose still collapses the cluster,
    so this is not "the weak doses were dragging it down". The graded knockdowns genuinely do not sit with the
    full knockouts, which is a statement about perturbation TYPE, not about dose.
    """
    from . import factors
    out = []
    for d in designs:
        f = factors.parse(d)
        if f.get("family") == "gene_knockout" and set(f.get("genes") or ()) & set(ENVELOPE_GENES):
            out.append(d)
    return out


def cluster_null(z: dict, designs: list[str], size: int, overall: float) -> dict:
    """How often an ARBITRARY cluster of this size clears a given delta — the gate's own strength, measured.

    Exhaustive where that is affordable, and STRIDED where it is not — never random, so the answer is the same
    on every call without a seed to remember. It exists because `delta > +0.30` sounds like a strong claim and,
    for a THREE-member cluster, is not: measured on this corpus, 6.1% of arbitrary triples clear it. A gate one
    in sixteen random triples passes is weak evidence that a particular triple means something, so the honest
    report is the percentile, not the pass.

    THE CAP IS NOT COSMETIC. The subset count is C(n, size) and it explodes: 19,600 triples on a 50-design
    corpus, 230,300 quadruples, and 15,890,700 sextuples — which is what the previous version of this function
    tried to enumerate the moment a six-member cluster was passed in, hanging the test suite rather than
    failing it. A null distribution that cannot be computed is not a safeguard.
    """
    import itertools
    import math
    total = math.comb(len(designs), size)
    stride = max(1, total // _NULL_CAP)
    vals = []
    for i, combo in enumerate(itertools.combinations(designs, size)):
        if i % stride:
            continue
        pairs = [_cos(z[a], z[b]) for j, a in enumerate(combo) for b in combo[j + 1:]]
        vals.append(statistics.fmean(pairs) - overall)
    vals.sort()
    return {"n_subsets": len(vals), "population": total, "exhaustive": stride == 1, "stride": stride,
            "median": round(statistics.median(vals), 4),
            "p95": round(vals[int(0.95 * len(vals))], 4), "p99": round(vals[int(0.99 * len(vals))], 4),
            "values": vals}


def acceptance() -> dict:
    """Run the WELL-6z4 acceptance test on the live corpus, so the metric's guarantees are checkable, not
    asserted: severity confound removed (`|corr(growth, cos-to-WT)| < 0.15`), the envelope-biosynthesis
    mechanism cluster preserved (nearest-neighbour 4/4, within−overall Δ > 0.30), and zero hyperparameters."""
    m = _matrix()
    if not m:
        return {"error": "corpus unreadable"}
    z, g = m["z"], m["growth"]
    designs = m["designs"]
    confound = severity_confound(z, g, designs)
    baseline = severity_confound(m["z_raw"], g, designs)   # the pre-double-centering number, for comparison
    env = envelope_cluster(designs)
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
    # HOW MUCH EACH PASS IS WORTH, measured rather than implied. Both thresholds were set when the corpus was
    # smaller and both are weak at its current size; a boolean that does not carry its own strength invites a
    # reader to treat "passes" as settled. Reported alongside, never folded into `passes` — moving a threshold
    # to match the evidence is the HARKing this project has already had to undo once.
    strength: dict = {}
    if within is not None and len(env) >= 2:
        null = cluster_null(z, designs, len(env), overall)
        obs = within - overall
        above = sum(1 for v in null["values"] if v >= obs)
        clears_gate = sum(1 for v in null["values"] if v > 0.30)
        strength["cluster"] = {
            "observed": round(obs, 4), "n_members": len(env),
            "exhaustive_null_subsets": null["n_subsets"], "null_median": null["median"],
            "null_p95": null["p95"], "null_p99": null["p99"],
            "p_value": round(above / null["n_subsets"], 4),
            "pct_of_random_clusters_clearing_the_gate": round(100 * clears_gate / null["n_subsets"], 1),
            "reading": ("the cluster is more coherent than an arbitrary set of this size (p=%.3f), but the "
                        "+0.30 GATE is cleared by %.1f%% of arbitrary %d-design sets, so the pass is weaker "
                        "evidence than it sounds. The p-value is the claim; the gate is a tripwire."
                        % (above / null["n_subsets"], 100 * clears_gate / null["n_subsets"], len(env))),
        }
    n_growth = sum(1 for d in designs if g.get(d) is not None)
    if n_growth > 3:
        se = 1.0 / math.sqrt(n_growth - 3)
        strength["confound"] = {
            "n": n_growth, "fisher_z_se": round(se, 3), "threshold": 0.15,
            "reading": ("|r| < 0.15 asks a point estimate to be smaller than ~%.2f standard errors of itself "
                        "at n=%d, so clearing it is not strong evidence on its own. The robust claim is the "
                        "SIGNIFICANCE-level de-confounding: |r| %.3f -> %.3f."
                        % (0.15 / se, n_growth, abs(baseline), abs(confound))),
        }
    return {"corr_growth_cos_to_wt": round(confound, 3),
            "corr_growth_cos_to_wt_baseline": round(baseline, 3),   # diagnostic: the same statistic pre-transform
            "confound_abs_reduction": round(abs(baseline) - abs(confound), 3),
            "envelope_within_minus_overall": (round(within - overall, 3) if within is not None else None),
            "envelope_members": env,
            "envelope_nn_purity": f"{nn_ok}/{len(env)}",                            # diagnostic, not a gate
            "envelope_nn_off_cluster": {k.split("/")[-1]: v.split("/")[-1] for k, v in off.items()},
            "checks": checks, "passes": all(checks.values()), "strength": strength,
            "note": ("The metric's corpus-robust guarantees, recomputed live: severity removed AND the mechanism "
                     "cluster coheres above chance. `passes` gates on those two. NN purity is a diagnostic — a "
                     "metabolically-adjacent design (e.g. pgi) can legitimately take an envelope member's NN, so "
                     "`envelope_nn_off_cluster` NAMES it rather than failing. READ `strength` BEFORE quoting "
                     "`passes`: both thresholds are weak at this corpus size and it says by how much."),
            "status": ("WELL-6z4-REDO: the CLUSTER half is RE-ESTABLISHED, the CONFOUND half is OPEN, and "
                       "`passes` gates on both. CLUSTER — the selector was a SUBSTRING match that re-admitted "
                       "`graded_gene_knockout/KO:murA` after `gene_knockout/KO:murA` had been excluded on the "
                       "merits as a verified no-op; it now matches on identity. Stable across corpus changes "
                       "(+0.419 -> +0.414 when DUP-1 added three designs) and p=0.028 against an exhaustive "
                       "null. CONFOUND — NOT re-established, and a reading of mine on 2026-08-08 wrongly said "
                       "it was: I recorded that it 'cleared as the corpus grew', -0.227 -> -0.082. DUP-1 then "
                       "split three knockouts that had been merged across media timelines, n went 50 -> 53, "
                       "and |r| moved to 0.241 — a 0.16 swing from three correctly-split designs, across a "
                       "0.15 threshold whose Fisher-z SE at this n is 0.147. The -0.082 was noise read as a "
                       "result, which is what the `strength` block exists to make visible. Thresholds "
                       "deliberately UNRELAXED. The durable claims are the cluster p-value and the confound "
                       "REDUCTION (+0.639 -> -0.241), not the booleans; this gate needs a bigger corpus, not a "
                       "smaller threshold.")}
