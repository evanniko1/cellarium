"""SCI-4: a multi-gene / reduced-genome DESIGN GENERATOR, scored by predicted viability. (Deprioritized — a focused
generator, not an optimizer.)

Instead of hand-listing multi-KO sets, this enumerates candidates from a DISPENSABLE-gene pool and RANKS them by a
composite viability/risk score, so the most informative, most-likely-runnable designs surface first. It composes the
signals the toolkit already grounds — it invents no new number:
  - dispensability: the pool is genes whose single KO was viable in the corpus and/or that are non-essential in the
    Baba/Joyce benchmark and not core machinery (removing an essential or a machinery gene guarantees inviability);
  - single-gene viability prior: the SCI-5 surrogate's per-gene probability, combined weakest-link (a set is only as
    viable as its most fragile member);
  - epistasis (DD-SCI-4a, now FOLDED IN): single-gene priors DO NOT capture it, so a prior-only 'viable' over-predicts.
    `fba_synthetic_lethal` (a second oracle over iML1515) is run on the candidates the prior calls viable — exactly
    where it's blind — to catch the reroute-blocking synthetic lethals that make a multi-KO interesting: both genes
    tolerate a single KO but the double abolishes growth. A hit downgrades the recommendation (predicted inviable via
    epistasis) and surfaces it as the informative case to confirm in the sim. Graceful: no FBA -> prior-only ranking;
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
    return {"available": True, "synthetic_lethal": bool(sl), "n_synthetic_lethal": len(sl),
            "pairs": [p["pair"] for p in sl], "detail": sl, "wt_growth": out.get("wt_growth")}


def _fold_epistasis(s: dict) -> dict:
    """Fold the FBA synthetic-lethal signal into a prior-only score. If the set has an FBA synthetic-lethal pair, the
    single-gene prior over-predicted viability (epistasis it can't see) -> downgrade propose->flag and attach the
    evidence + the informative-case framing. Mutates + returns `s`. No-op when FBA is unavailable/not-applicable."""
    slc = synthetic_lethal_check(s["genes"])
    s["synthetic_lethal_check"] = slc
    if slc.get("available") and slc.get("synthetic_lethal"):
        if s["recommend"] == _PROPOSE:
            s["recommend"] = _FLAG
        s["epistasis"] = ("FBA predicts SYNTHETIC LETHALITY (" + ", ".join("+".join(p) for p in slc["pairs"]) +
                          "): both genes tolerate a single KO but the double abolishes growth — the reroute-blocking "
                          "case the single-gene prior missed. Informative to confirm in the sim; NOT a viable "
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


def generate(pool: list[str] | None = None, k: int = 2, max_candidates: int = 12,
             *, use_surrogate: bool = True, use_fba: bool = True) -> dict:
    """Enumerate size-`k` multi-KO candidates from the dispensable pool, score + rank each, and return the top
    `max_candidates` as runnable multi_gene_knockout Designs. Proposes only biosecurity-clean, non-essential sets.
    DD-SCI-4a: with `use_fba`, the FBA synthetic-lethal check is run on the top candidates the prior calls VIABLE
    (exactly where it's blind) — a hit downgrades the recommendation + surfaces the reroute-blocker. Graceful if no FBA."""
    from . import scope
    if pool is None:
        dp = dispensable_pool()
        if dp.get("error"):
            return {"error": dp["error"]}
        pool = dp["pool"]
    pool = sorted(set(pool))
    if len(pool) < k:
        return {"error": f"pool has {len(pool)} genes; need >= k ({k}) to form a set", "pool": pool}

    # Stage 1 — the fast prior-only score over EVERY combo (no FBA), then rank + take the top.
    scored = [score_set(list(combo), use_surrogate=use_surrogate) for combo in combinations(pool, k)]
    scored.sort(key=_rank_key)
    top = scored[:max_candidates]

    # Stage 2 (DD-SCI-4a) — fold the FBA epistasis check into ONLY the top candidates the prior would PROPOSE (an LP
    # per pair is costly, and 'propose' is exactly where the single-gene prior is blind: it called them viable). A
    # synthetic-lethal hit demotes propose->flag. Then re-rank so the epistasis-demoted sets settle correctly.
    fba_available = None
    if use_fba:
        for s in top:
            if s["recommend"] == _PROPOSE:
                _fold_epistasis(s)
                avail = (s.get("synthetic_lethal_check") or {}).get("available")
                fba_available = avail if fba_available is None else (fba_available or avail)
        top.sort(key=_rank_key)

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
        "k": k, "pool": pool, "n_pool": len(pool), "n_candidates_scored": len(scored),
        "n_proposed": len(designs), "designs": designs,
        "fba_epistasis_checked": bool(use_fba), "fba_available": fba_available,
        "ranking": [{"genes": s["genes"], "recommend": s["recommend"], "viability_prior": s["viability_prior"],
                     "synthetic_lethal": bool((s.get("synthetic_lethal_check") or {}).get("synthetic_lethal"))}
                    for s in top],
        "note": ("Ranked reduced-genome / multi-KO candidates. 'designs' are biosecurity-clean, non-essential sets, "
                 "runnable via propose_experiments. The viability_prior is a single-gene prior; the FBA synthetic-"
                 "lethal check (DD-SCI-4a) folds in the pairwise epistasis it can't see — a 'flag' with an `epistasis` "
                 "note is a reroute-blocker FBA predicts inviable (the informative case), to CONFIRM in the sim. When "
                 "fba_available is false, install the `fba` extra to enable the epistasis check."),
    }
