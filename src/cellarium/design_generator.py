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


def _value_of(s: dict, objective: str) -> float:
    """The scalar the SEARCH maximizes for a scored set; AVOID -> -inf so it can never be chosen."""
    if s.get("recommend") == _AVOID:
        return float("-inf")
    if objective == "information":
        return (s.get("active_learning") or {}).get("information_gain", 0.0)
    band = 1.0 if s.get("recommend") == _PROPOSE else 0.0        # propose > flag
    return band + (s.get("viability_prior") or 0.0)


def _score_candidate(genes, *, use_surrogate: bool, use_fba: bool) -> dict:
    """Fully score a set for the search: prior + (use_fba) the FBA epistasis fold-in + the active-learning score."""
    s = score_set(list(genes), use_surrogate=use_surrogate, use_fba=use_fba)
    s["active_learning"] = information_gain(s)
    return s


def _beam_search(pool: list[str], k: int, width: int, *, use_surrogate: bool, use_fba: bool,
                 objective: str) -> tuple[list[dict], int]:
    """DD-SCI-4a(c-ii): build size-`k` sets incrementally, keeping the top-`width` PARTIAL sets at each step
    (greedy = width 1; beam = width>1, which recovers from a bad greedy step). Scores only O(width·k·|pool|) sets
    instead of C(|pool|,k) — what makes the FBA-heavy objective tractable at large pools / large k. Deduped by
    gene-set (so {a,b} and {b,a} are one candidate). Returns (final size-k scored sets, n_evaluations)."""
    beam: list[tuple] = [((), None)]                            # (genes_tuple, score_dict); start from the empty set
    n_eval = 0
    for _ in range(k):
        seen: dict = {}                                         # sorted-gene-tuple -> score (dedup across the beam)
        for chosen, _sc in beam:
            for g in pool:
                if g in chosen:
                    continue
                key = tuple(sorted(chosen + (g,)))
                if key not in seen:
                    seen[key] = _score_candidate(list(key), use_surrogate=use_surrogate, use_fba=use_fba)
                    n_eval += 1
        if not seen:
            break
        ranked = sorted(seen.items(), key=lambda kv: -_value_of(kv[1], objective))
        beam = ranked[:max(1, width)]
    finals = [sc for genes, sc in beam if sc is not None and len(genes) == k]   # drop the empty-set sentinel
    finals.sort(key=lambda sc: -_value_of(sc, objective))
    return finals, n_eval


def _finalize(candidates: list[dict], *, k: int, objective: str, max_candidates: int, pool: list[str],
              n_scored: int, fba_available, use_fba: bool, search: str) -> dict:
    """Order the scored candidates by the objective, build the runnable Designs (dropping AVOID), assemble the
    result. Shared by the enumerate + search paths."""
    from . import scope
    if objective == "information":
        ordered = sorted((s for s in candidates if s["recommend"] != _AVOID),
                         key=lambda s: (-s["active_learning"]["information_gain"], _rank_key(s)))
    else:
        ordered = sorted(candidates, key=_rank_key)
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
        "k": k, "objective": objective, "search": search, "pool": pool, "n_pool": len(pool),
        "n_candidates_scored": n_scored, "n_proposed": len(designs), "designs": designs,
        "fba_epistasis_checked": bool(use_fba), "fba_available": fba_available,
        "ranking": [{"genes": s["genes"], "recommend": s["recommend"], "viability_prior": s["viability_prior"],
                     "synthetic_lethal": bool((s.get("synthetic_lethal_check") or {}).get("synthetic_lethal")),
                     "information_gain": s["active_learning"]["information_gain"],
                     "surprise_why": s["active_learning"]["why"]}
                    for s in top],
        "note": ("Ranked multi-KO candidates. objective='viability' = safest first; 'information' = active learning "
                 "(the runs that teach the most first). search='enumerate' scores every size-k subset (exact, but "
                 "C(n,k) blows up); 'greedy'/'beam' build sets incrementally (O(width·k·|pool|)) so the FBA-heavy "
                 "scoring stays tractable at large pools / k — n_candidates_scored shows how many sets were "
                 "evaluated. The FBA synthetic-lethal + k-way checks fold in the epistasis the prior can't see. "
                 "fba_available=false -> install the `fba` extra. The sim is the decisive arbiter."),
    }


def generate(pool: list[str] | None = None, k: int = 2, max_candidates: int = 12,
             *, use_surrogate: bool = True, use_fba: bool = True, objective: str = "viability",
             search: str = "enumerate", beam_width: int | None = None) -> dict:
    """Generate + rank size-`k` multi-KO candidates from the dispensable pool as runnable multi_gene_knockout Designs
    (biosecurity-clean, non-essential only). DD-SCI-4a: (a) `use_fba` folds in the FBA synthetic-lethal + (c-i) k-way
    epistasis the single-gene prior can't see; (b) `objective` = 'viability' (safest first) or 'information' (active
    learning — expected surprise first); (c-ii) `search` = 'enumerate' (score every subset — exact, but C(n,k) blows
    up), 'greedy' (build one set incrementally), or 'beam' (keep the top-`beam_width` partial sets, recovering from a
    bad greedy step). greedy/beam score only O(width·k·|pool|) sets — what makes large pools / k tractable."""
    if objective not in ("viability", "information"):
        return {"error": f"objective must be 'viability' or 'information', got {objective!r}"}
    if search not in ("enumerate", "greedy", "beam"):
        return {"error": f"search must be 'enumerate', 'greedy', or 'beam', got {search!r}"}
    if k < 2:   # a multi-KO set needs >=2 genes; also guards a k=0 crash on the greedy/beam path (empty sentinel set)
        return {"error": f"k must be >= 2 (a multi-KO set needs at least 2 genes), got {k}"}
    if pool is None:
        dp = dispensable_pool()
        if dp.get("error"):
            return {"error": dp["error"]}
        pool = dp["pool"]
    pool = sorted(set(pool))
    if len(pool) < k:
        return {"error": f"pool has {len(pool)} genes; need >= k ({k}) to form a set", "pool": pool}

    if search == "enumerate":
        # score every size-k subset with the fast prior, rank, FBA-fold the top PROPOSE candidates, then AL-score. The
        # working set is a superset of max_candidates for 'information' so the surprise re-rank can promote a buried set.
        scored = [score_set(list(combo), use_surrogate=use_surrogate) for combo in combinations(pool, k)]
        scored.sort(key=_rank_key)
        work = scored[:(max_candidates * 2 if objective == "information" else max_candidates)]
        fba_available = None
        if use_fba:
            for s in work:
                if s["recommend"] == _PROPOSE:
                    _fold_epistasis(s)
                    avail = (s.get("synthetic_lethal_check") or {}).get("available")
                    fba_available = avail if fba_available is None else (fba_available or avail)
        for s in work:
            s["active_learning"] = information_gain(s)
        candidates, n_scored = work, len(scored)
    else:
        # greedy (width 1) / beam (width beam_width|max_candidates): each candidate is FBA-scored DURING the search.
        width = 1 if search == "greedy" else (beam_width or max_candidates)
        candidates, n_scored = _beam_search(pool, k, width, use_surrogate=use_surrogate, use_fba=use_fba,
                                            objective=objective)
        # OR availability across ALL finals (not just the top one) to match the enumerate path: FBA "ran" if ANY
        # candidate was checkable — a non-metabolic top set must not make the whole run report fba_available=False.
        avails = [a for a in ((c.get("synthetic_lethal_check") or {}).get("available") for c in candidates)
                  if a is not None]
        fba_available = (any(avails) if avails else None)

    return _finalize(candidates, k=k, objective=objective, max_candidates=max_candidates, pool=pool,
                     n_scored=n_scored, fba_available=fba_available, use_fba=use_fba, search=search)
