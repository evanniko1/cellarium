"""SCI-4: a multi-gene / reduced-genome DESIGN GENERATOR, scored by predicted viability. (Deprioritized — a focused
generator, not an optimizer.)

Instead of hand-listing multi-KO sets, this enumerates candidates from a DISPENSABLE-gene pool and RANKS them by a
composite viability/risk score, so the most informative, most-likely-runnable designs surface first. It composes the
signals the toolkit already grounds — it invents no new number:
  - dispensability: the pool is genes whose single KO was viable in the corpus and/or that are non-essential in the
    Baba/Joyce benchmark and not core machinery (removing an essential or a machinery gene guarantees inviability);
  - single-gene viability prior: the SCI-5 surrogate's per-gene probability, combined weakest-link (a set is only as
    viable as its most fragile member);
  - epistasis (DD-SCI-4a, FOLDED IN): single-gene priors DO NOT capture it, so a prior-only 'viable' over-predicts.
    Two FBA checks (a second oracle over iML1515) run on the candidates the prior calls viable — where it's blind:
    (a) the PAIRWISE `fba_synthetic_lethal` scan (reroute-blocking pairs); (c) at k>=3, the FULL k-way `fba_gene_
    deletion` (knock out the whole set at once) — the direct 'does this set survive?' test that catches HIGHER-ORDER
    lethality no pair shows. A hit from either downgrades the recommendation + surfaces the informative case to
    confirm in the sim. Graceful: no FBA -> prior-only ranking;
  - biosecurity: every candidate is screened; a flagged design is dropped, never proposed.
Returns runnable `multi_gene_knockout` Designs, ranked, each with its score + why.
"""

from __future__ import annotations

from itertools import combinations

# recommendation bands
_PROPOSE, _FLAG, _AVOID = "propose", "flag", "avoid"


def dispensable_pool(max_genes: int = 12) -> dict:
    """Grounded candidate pool: genes whose SINGLE KO was viable in the corpus (we've observed them tolerate loss),
    minus any that are core machinery or benchmark-essential (a reduced-genome build must not remove those). Returns
    {pool, dropped, note}. The pool is the honest starting set — genes we have direct evidence tolerate deletion."""
    from . import scope, store
    out = store.viability("gene_knockout", None)
    if out.get("error"):
        return {"error": out["error"], "pool": []}
    pool, dropped = [], []
    for d in out.get("designs", []):
        if d.get("verdict") != "viable":            # only genes we've SEEN survive a single KO
            continue
        gene = str(d.get("condition", "")).replace("KO:", "")
        c = scope.classify_gene(gene)
        if not c.get("known"):
            continue
        if c.get("is_machinery"):
            dropped.append({"gene": gene, "reason": "core machinery — never a reduction target"})
            continue
        if c.get("essential_reference") is True:    # singly-viable in silico but essential in vivo (under-predict)
            dropped.append({"gene": gene, "reason": "benchmark-essential (model under-predicts) — unsafe to remove"})
            continue
        pool.append(gene)
    pool = sorted(set(pool))[:max_genes]
    return {"pool": pool, "n_pool": len(pool), "dropped": dropped,
            "note": ("Genes observed to tolerate a SINGLE KO in the corpus, excluding machinery + benchmark-essential "
                     "genes. Single-KO tolerance does NOT imply the combination is viable — epistasis is unmeasured "
                     "here (see fba_synthetic_lethal + the sim).")}


def synthetic_lethal_check(genes: list[str]) -> dict:
    """DD-SCI-4a: run the FBA pairwise synthetic-lethal test on a set — the epistasis the single-gene prior CANNOT
    see (a second oracle over iML1515). Returns {available, synthetic_lethal, pairs, ...}. Graceful: available=False
    when cobra/iML1515 isn't installed, or when <2 of the set's genes are metabolic (in iML1515) — then the generator
    keeps the prior-only ranking. A hit means both genes tolerate a single KO but the double abolishes growth."""
    from . import tools
    try:
        out = tools.fba_synthetic_lethal(list(genes))
    except Exception as exc:
        return {"available": False, "note": f"FBA unavailable: {type(exc).__name__}"}
    if out.get("error"):
        return {"available": False, "note": out["error"]}
    sl = out.get("synthetic_lethals") or []
    all_pairs = out.get("pairs") or sl                     # `pairs` carries every pair's double-KO growth (<=40 pairs)
    dgfs = [p.get("double_growth_frac") for p in all_pairs
            if isinstance(p, dict) and p.get("double_growth_frac") is not None]
    return {"available": True, "synthetic_lethal": bool(sl), "n_synthetic_lethal": len(sl),
            "pairs": [p["pair"] for p in sl], "detail": sl, "wt_growth": out.get("wt_growth"),
            # DD-SCI-4a(b): the weakest double-KO growth (closest to lethal) — a fragility signal for active learning
            "min_double_growth_frac": (round(min(dgfs), 4) if dgfs else None)}


def deletion_check(genes: list[str]) -> dict:
    """DD-SCI-4a(c): the FULL k-way FBA deletion — knock out the WHOLE set at once (1 LP) to catch the higher-order
    lethality the pairwise synthetic-lethal scan misses at k>=3 (a set lethal though no PAIR is). Returns
    {available, lethal, growth_frac, ...}; graceful when cobra/iML1515 is absent or no gene is metabolic."""
    from . import tools
    try:
        out = tools.fba_gene_deletion(list(genes))
    except Exception as exc:
        return {"available": False, "note": f"FBA unavailable: {type(exc).__name__}"}
    if out.get("error"):
        return {"available": False, "note": out["error"]}
    return {"available": True, "lethal": bool(out.get("lethal")),
            "growth_frac": out.get("deletion_growth_frac"), "n_deleted": out.get("n_deleted")}


def _fold_epistasis(s: dict) -> dict:
    """Fold the FBA epistasis signals into a prior-only score. Two checks: the PAIRWISE synthetic-lethal scan, and
    (at k>=3) the FULL k-way deletion — the direct 'does the whole set survive?' test the pairwise scan misses. If
    EITHER says inviable, the single-gene prior over-predicted -> downgrade propose->flag + attach the evidence.
    Mutates + returns `s`. No-op when FBA is unavailable. (At k=2 the pair IS the full deletion, so it's skipped.)"""
    genes = s["genes"]
    slc = synthetic_lethal_check(genes)
    s["synthetic_lethal_check"] = slc
    dele = None
    if len(genes) >= 3:
        dele = deletion_check(genes)
        s["deletion_check"] = dele
    sl_pair = bool(slc.get("available") and slc.get("synthetic_lethal"))
    kway_lethal = bool(dele and dele.get("available") and dele.get("lethal"))
    if sl_pair or kway_lethal:
        if s["recommend"] == _PROPOSE:
            s["recommend"] = _FLAG
        reasons = []
        if sl_pair:
            reasons.append("a synthetic-lethal PAIR (" + ", ".join("+".join(p) for p in slc["pairs"]) + ")")
        if kway_lethal:
            reasons.append(f"the FULL {len(genes)}-way deletion abolishes growth (frac {dele.get('growth_frac')})")
        s["epistasis"] = ("FBA predicts inviability via " + " and ".join(reasons) + " — the set the single-gene prior "
                          "called viable does not survive. Informative to confirm in the sim; NOT a viable "
                          "reduced-genome design.")
    return s


def score_set(genes: list[str], *, use_surrogate: bool = True, use_fba: bool = False) -> dict:
    """Score a candidate multi-KO set: per-member viability prior (surrogate, weakest-link), essentiality / machinery
    guards, and biosecurity. With `use_fba`, also folds in the FBA synthetic-lethal epistasis check (DD-SCI-4a).
    Returns the composite + a recommendation. No sim — priors + the FBA cross-check only."""
    from . import biosecurity, scope
    from .model import Design

    members, essential_hits, machinery_hits, priors = [], [], [], []
    for g in genes:
        c = scope.classify_gene(g)
        if not c.get("known"):
            continue
        members.append(g)
        if c.get("essential_reference") is True:
            essential_hits.append(g)
        if c.get("is_machinery"):
            machinery_hits.append(g)

    # per-gene viability prior from the SCI-5 surrogate (weakest-link = the set's floor); rule fallback if unavailable
    surrogate_used = False
    if use_surrogate:
        try:
            from . import surrogate
            ds = surrogate.build_dataset()
            for g in members:
                p = surrogate.predict(g, ds)
                if p.get("viability_probability") is not None:
                    priors.append(p["viability_probability"]); surrogate_used = True
        except Exception:
            priors = []
    viability_prior = round(min(priors), 3) if priors else None

    # biosecurity screen the concrete design (INTENT) — a flagged set is not proposable
    design = Design(perturbation="multi_gene_knockout", condition="KO:" + "+".join(members))
    bio = biosecurity.screen(design)
    bio_flagged = bool(getattr(bio, "flagged", False))

    if bio_flagged:
        recommend = _AVOID
    elif essential_hits or machinery_hits:
        recommend = _AVOID                          # removing an essential/machinery gene guarantees inviability
    elif viability_prior is not None and viability_prior < 0.5:
        recommend = _FLAG                           # the surrogate expects the weakest member to fail
    else:
        recommend = _PROPOSE
    result = {
        "genes": members, "n_genes": len(members),
        "viability_prior": viability_prior,          # weakest-link single-gene surrogate probability (None if no model)
        "surrogate_used": surrogate_used,
        "essential_members": essential_hits, "machinery_members": machinery_hits,
        "biosecurity_flagged": bio_flagged,
        "biosecurity_reason": (bio.reason if bio_flagged else None),
        "recommend": recommend,
        "caveat": ("Single-gene prior + (when use_fba) the FBA synthetic-lethal epistasis check. The prior alone "
                   "cannot see epistasis; the sim is the decisive arbiter."),
    }
    return _fold_epistasis(result) if use_fba else result


def _rank_key(s: dict) -> tuple:
    # propose > flag > avoid; then higher weakest-link viability prior; then fewer genes (cheaper, cleaner readout)
    band = {_PROPOSE: 0, _FLAG: 1, _AVOID: 2}[s["recommend"]]
    return (band, -(s["viability_prior"] if s["viability_prior"] is not None else -1.0), s["n_genes"])


def information_gain(s: dict) -> dict:
    """DD-SCI-4a(b): the expected-SURPRISE / active-learning score — how much would running this set TEACH, given
    what we already predicted? A set the safe-viability ranking buries can be the most informative run. Highest where
    our TWO oracles are confident but DISAGREE (the single-gene prior says viable, FBA says the double is synthetic-
    lethal — the reroute-blocker), or where either oracle sits near its decision boundary. Returns the headline +
    components (glass-box), built from signals already computed — no extra sim, no extra LP.

      * oracle_disagreement — prior-viability × (FBA says synthetic-lethal): the sharpest surprise (max when the
        surrogate is CONFIDENT the KO survives yet the second oracle says the pair is lethal);
      * prior_uncertainty — 1 - 2·|p-0.5|: the surrogate itself is unsure (peaks at p=0.5);
      * fba_fragility — the double GROWS but weakly (a reroute the whole-cell sim might break) even when not a clean
        synthetic lethal — 1 - min_double_growth_frac.
    Disagreement dominates by construction (its weight exceeds the others' maxima), so a predicted-viable-yet-FBA-
    lethal set always outranks a merely-uncertain one — 'propose the runs that teach the most'."""
    p = s.get("viability_prior")
    p = p if p is not None else 0.5
    slc = s.get("synthetic_lethal_check") or {}
    dele = s.get("deletion_check") or {}
    # the second oracle says inviable via a pairwise synthetic-lethal OR the full k-way deletion (higher-order)
    fba_lethal = bool(slc.get("synthetic_lethal")) or bool(dele.get("available") and dele.get("lethal"))
    disagreement = round(p * (1.0 if fba_lethal else 0.0), 3)
    uncertainty = round(1.0 - 2.0 * abs(p - 0.5), 3)
    # fragility: prefer the FULL k-way growth (the actual set's growth) when we have it; else the weakest pair
    kway = dele.get("growth_frac") if dele.get("available") else None
    mdgf = kway if kway is not None else slc.get("min_double_growth_frac")
    fragility = round(1.0 - mdgf, 3) if (mdgf is not None and not fba_lethal) else 0.0
    gain = round(min(1.0, 0.7 * disagreement + 0.3 * uncertainty + 0.25 * fragility), 3)
    return {"information_gain": gain, "oracle_disagreement": disagreement,
            "prior_uncertainty": uncertainty, "fba_fragility": fragility,
            "why": ("predicted viable yet FBA-lethal (reroute-blocker)" if disagreement > 0
                    else "surrogate near its decision boundary" if uncertainty >= 0.6
                    else "fragile double-KO growth" if fragility >= 0.5 else "low expected surprise")}


def generate(pool: list[str] | None = None, k: int = 2, max_candidates: int = 12,
             *, use_surrogate: bool = True, use_fba: bool = True, objective: str = "viability") -> dict:
    """Enumerate size-`k` multi-KO candidates from the dispensable pool, score each, and return the top
    `max_candidates` as runnable multi_gene_knockout Designs. Proposes only biosecurity-clean, non-essential sets.
    DD-SCI-4a: (a) with `use_fba`, the FBA synthetic-lethal check folds in the pairwise epistasis the single-gene
    prior can't see — a hit demotes propose->flag + surfaces the reroute-blocker. (b) `objective` picks the ranking
    goal: 'viability' (default — safest reduced-genome builds first) or 'information' (active learning — rank by
    EXPECTED SURPRISE, so the runs that TEACH the most surface first: a predicted-viable-yet-FBA-lethal set, or one
    the surrogate is unsure about)."""
    from . import scope
    if objective not in ("viability", "information"):
        return {"error": f"objective must be 'viability' or 'information', got {objective!r}"}
    if pool is None:
        dp = dispensable_pool()
        if dp.get("error"):
            return {"error": dp["error"]}
        pool = dp["pool"]
    pool = sorted(set(pool))
    if len(pool) < k:
        return {"error": f"pool has {len(pool)} genes; need >= k ({k}) to form a set", "pool": pool}

    # Stage 1 — the fast prior-only score over EVERY combo (no FBA), ranked by viability. The working set is a
    # SUPERSET of max_candidates for the information objective, so the surprise re-rank can promote a high-information
    # set the viability rank buried (e.g. a p=0.6 reroute-blocker).
    scored = [score_set(list(combo), use_surrogate=use_surrogate) for combo in combinations(pool, k)]
    scored.sort(key=_rank_key)
    work = scored[:(max_candidates * 2 if objective == "information" else max_candidates)]

    # Stage 2 (DD-SCI-4a a) — fold the FBA epistasis check into the working set's PROPOSE candidates (an LP per pair
    # is costly, and 'propose' is exactly where the single-gene prior is blind: it called them viable).
    fba_available = None
    if use_fba:
        for s in work:
            if s["recommend"] == _PROPOSE:
                _fold_epistasis(s)
                avail = (s.get("synthetic_lethal_check") or {}).get("available")
                fba_available = avail if fba_available is None else (fba_available or avail)

    # Stage 3 (DD-SCI-4a b) — the active-learning score for every candidate (cheap; reuses the prior + FBA signals).
    for s in work:
        s["active_learning"] = information_gain(s)

    # Stage 4 — order by the chosen objective. 'information' never proposes an AVOID set (categorically wrong
    # regardless of surprise); ties break by the viability rank.
    if objective == "information":
        ordered = sorted((s for s in work if s["recommend"] != _AVOID),
                         key=lambda s: (-s["active_learning"]["information_gain"], _rank_key(s)))
    else:
        ordered = sorted(work, key=_rank_key)
    top = ordered[:max_candidates]

    designs = []
    for s in top:
        if s["recommend"] == _AVOID:
            continue                                 # never hand back a design we'd advise against
        idxs, labels = [], []
        for g in s["genes"]:
            c = scope.classify_gene(g)
            if c.get("ko_index"):
                idxs.append(int(c["ko_index"])); labels.append(g)
        if len(idxs) >= 2:
            designs.append({"perturbation": "multi_gene_knockout", "condition": "KO:" + "+".join(labels),
                            "params": {"ko_indices": idxs}, "score": s})
    return {
        "k": k, "objective": objective, "pool": pool, "n_pool": len(pool), "n_candidates_scored": len(scored),
        "n_proposed": len(designs), "designs": designs,
        "fba_epistasis_checked": bool(use_fba), "fba_available": fba_available,
        "ranking": [{"genes": s["genes"], "recommend": s["recommend"], "viability_prior": s["viability_prior"],
                     "synthetic_lethal": bool((s.get("synthetic_lethal_check") or {}).get("synthetic_lethal")),
                     "information_gain": s["active_learning"]["information_gain"],
                     "surprise_why": s["active_learning"]["why"]}
                    for s in top],
        "note": ("Ranked multi-KO candidates. objective='viability' = safest reduced-genome builds first; "
                 "'information' = ACTIVE LEARNING, the runs that teach the most first (expected surprise: a "
                 "predicted-viable-yet-FBA-synthetic-lethal reroute-blocker, or a set the surrogate is unsure about). "
                 "The viability_prior is a single-gene prior; the FBA synthetic-lethal check (DD-SCI-4a) folds in the "
                 "pairwise epistasis it can't see. Set fba_available=false -> install the `fba` extra. Confirm in the sim."),
    }
