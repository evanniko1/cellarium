"""SCI-4: a multi-gene / reduced-genome DESIGN GENERATOR, scored by predicted viability. (Deprioritized — a focused
generator, not an optimizer.)

Instead of hand-listing multi-KO sets, this enumerates candidates from a DISPENSABLE-gene pool and RANKS them by a
composite viability/risk score, so the most informative, most-likely-runnable designs surface first. It composes the
signals the toolkit already grounds — it invents no new number:
  - dispensability: the pool is genes whose single KO was viable in the corpus and/or that are non-essential in the
    Baba/Joyce benchmark and not core machinery (removing an essential or a machinery gene guarantees inviability);
  - single-gene viability prior: the SCI-5 surrogate's per-gene probability, combined weakest-link (a set is only as
    viable as its most fragile member);
  - epistasis (the honest caveat): single-gene priors DO NOT capture it, so a 'viable' composite is a WEAK prior. The
    reroute-blocking synthetic lethals that make a multi-KO interesting are exactly what the priors miss — that is
    what fba_synthetic_lethal (opt-in) checks and, ultimately, what the sim decides;
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


def score_set(genes: list[str], *, use_surrogate: bool = True) -> dict:
    """Score a candidate multi-KO set: per-member viability prior (surrogate, weakest-link), essentiality / machinery
    guards, and biosecurity. Returns the composite + a recommendation. No sim — priors only."""
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
    return {
        "genes": members, "n_genes": len(members),
        "viability_prior": viability_prior,          # weakest-link single-gene surrogate probability (None if no model)
        "surrogate_used": surrogate_used,
        "essential_members": essential_hits, "machinery_members": machinery_hits,
        "biosecurity_flagged": bio_flagged,
        "biosecurity_reason": (bio.reason if bio_flagged else None),
        "recommend": recommend,
        "caveat": ("Composite of SINGLE-gene priors — epistasis is NOT captured, so a 'propose' is a weak prior only. "
                   "Confirm reroute-blocking lethality with fba_synthetic_lethal and, decisively, the sim."),
    }


def _rank_key(s: dict) -> tuple:
    # propose > flag > avoid; then higher weakest-link viability prior; then fewer genes (cheaper, cleaner readout)
    band = {_PROPOSE: 0, _FLAG: 1, _AVOID: 2}[s["recommend"]]
    return (band, -(s["viability_prior"] if s["viability_prior"] is not None else -1.0), s["n_genes"])


def generate(pool: list[str] | None = None, k: int = 2, max_candidates: int = 12,
             *, use_surrogate: bool = True) -> dict:
    """Enumerate size-`k` multi-KO candidates from the dispensable pool, score + rank each, and return the top
    `max_candidates` as runnable multi_gene_knockout Designs. Proposes only biosecurity-clean, non-essential sets."""
    from . import scope
    if pool is None:
        dp = dispensable_pool()
        if dp.get("error"):
            return {"error": dp["error"]}
        pool = dp["pool"]
    pool = sorted(set(pool))
    if len(pool) < k:
        return {"error": f"pool has {len(pool)} genes; need >= k ({k}) to form a set", "pool": pool}

    scored = [score_set(list(combo), use_surrogate=use_surrogate) for combo in combinations(pool, k)]
    scored.sort(key=_rank_key)
    top = scored[:max_candidates]

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
        "ranking": [{"genes": s["genes"], "recommend": s["recommend"], "viability_prior": s["viability_prior"]}
                    for s in top],
        "note": ("Ranked reduced-genome / multi-KO candidates. 'designs' are biosecurity-clean, non-essential sets, "
                 "runnable via propose_experiments. The viability_prior is a WEAK single-gene prior (no epistasis) — "
                 "these are HYPOTHESES to test, most informative when a set is predicted viable yet the sim disagrees. "
                 "Vet pairwise lethality with fba_synthetic_lethal before committing sim budget."),
    }
