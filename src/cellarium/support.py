"""Every claim carries its own n — how many SEEDS and how many GENERATIONS it rests on.

This exists because the project kept shipping conclusions drawn from one seed's first generation, and each time
the error was invisible in the output: the number looked identical whether it came from 1 run or 7. Three
examples, all real and all corrected only after an adversarial re-derivation:

  * `mass_decomposition` read `runs[0]` and `simout_dirs(...)[0]` — a composition claim from one generation of
    one seed. It happened to hold across all 7 seeds (94.6-96.4%), but nothing in the result said so, and the
    reader could not tell the difference between "measured everywhere" and "measured once".
  * The tRNA "blind validation" rested on `KO:lysS` at n=1, which is also the only non-degenerate case.
  * The nutrient-shift magnitudes were pooled over seeds that were 6/7 SINGLE-GENERATION, so every number was a
    transient sampled partway through a ~900 s response. The pooled protein fold was 1.34 with CI [1.07, 1.61];
    the one steady-state value ever measured was 1.77 — OUTSIDE that interval. More seeds at one generation
    would have converged tightly on the wrong answer, which is why seed count alone is not the safeguard.

So the rule is two-dimensional and both halves are load-bearing: SEEDS bound the precision, GENERATIONS bound
whether the quantity has settled at all. A tool that reports one without the other is still misleading.

`coverage()` is deliberately cheap (it counts directories, it does not read columns) so that attaching it to
every analysis result costs nothing and there is never a reason to omit it. `attach()` is the one-liner that
tools use. `tests/test_support.py` asserts that the analysis tools actually carry it, so this cannot quietly
rot back to single-seed reporting.
"""

from __future__ import annotations

from . import raw

# Below these, a result is a case study rather than a measurement. Chosen to match the corpus's own target
# (audit.TARGET_SEEDS = 4) and the observation that the shift response takes ~900 s — longer than one
# generation of many designs — so a single generation cannot show a settled value.
MIN_SEEDS = 2
MIN_GENERATIONS = 2


def coverage(design_or_id: str) -> dict:
    """How many seeds and generations back a claim about this design, and whether that is enough to claim one.

    Counts only what is READABLE ON LOCAL DISK, because that is what an analysis can actually use — a manifest
    row without raw cannot contribute a generation to a raw-derived number."""
    runs = raw.seed_runs(design_or_id)
    if not runs:
        return {"n_seeds": 0, "n_generations_total": 0, "single_seed": False, "single_generation": False,
                "sufficient": False,
                "warning": (f"no local raw simOut for '{design_or_id}' — nothing here rests on measured data. "
                            f"This is an ABSENCE, not a finding of zero.")}
    per_seed = {r.get("seed"): r.get("n_gens", 0) for r in runs}
    gens = [g for g in per_seed.values() if g]
    n_seeds = len(runs)
    max_gens = max(gens) if gens else 0
    min_gens = min(gens) if gens else 0
    single_seed = n_seeds < MIN_SEEDS
    single_gen = max_gens < MIN_GENERATIONS
    out = {
        "n_seeds": n_seeds, "seeds": sorted(k for k in per_seed if k is not None),
        "generations_per_seed": {str(k): v for k, v in sorted(per_seed.items(), key=lambda kv: (kv[0] is None, kv[0]))},
        "n_generations_total": sum(gens), "max_generations": max_gens, "min_generations": min_gens,
        "single_seed": bool(single_seed), "single_generation": bool(single_gen),
        "sufficient": bool(not single_seed and not single_gen),
    }
    why = []
    if single_seed:
        why.append(f"only {n_seeds} seed(s) on disk — a cross-seed statement needs at least {MIN_SEEDS}, and "
                   f"the corpus target is 4")
    if single_gen:
        why.append(f"the deepest lineage is {max_gens} generation(s) — a value measured inside one generation "
                   f"is a TRANSIENT, not a steady state, and adding seeds will not fix that")
    elif min_gens < max_gens:
        why.append(f"generation depth is UNEQUAL across seeds ({min_gens}-{max_gens}); pooling them mixes "
                   f"different points of the response, so stratify by generation before comparing")
    if why:
        out["warning"] = ("READ THIS BEFORE QUOTING ANY NUMBER FROM THIS DESIGN: " + "; ".join(why) + ".")
    return out


def attach(result: dict, design_or_id: str, key: str = "support") -> dict:
    """Attach the coverage block to a tool result. Returns the same dict, mutated, for use inline.

    Never silently skips: if coverage cannot be computed the block still lands, carrying the reason. A result
    with no `support` key at all is the failure mode this guards against — it is indistinguishable from a
    well-supported one at a glance."""
    if not isinstance(result, dict):
        return result
    try:
        result[key] = coverage(design_or_id)
    except Exception as e:
        result[key] = {"n_seeds": None, "sufficient": False,
                       "warning": f"coverage could not be computed ({type(e).__name__}: {e}) — treat this "
                                  f"result as UNVERIFIED for seed/generation support."}
    return result


def compare(design_a: str, design_b: str) -> dict:
    """Coverage for a two-design comparison, plus the mismatch that makes such comparisons wrong.

    Comparing a 4-generation design against a 1-generation one compares a settled value against a transient.
    That is the single most common way a real difference gets manufactured out of depth, and it is invisible
    unless the depths are printed side by side."""
    a, b = coverage(design_a), coverage(design_b)
    common = min(a.get("max_generations") or 0, b.get("max_generations") or 0)
    out = {design_a: a, design_b: b, "common_generation_depth": common,
           "depth_mismatch": bool((a.get("max_generations") or 0) != (b.get("max_generations") or 0)),
           "sufficient": bool(a.get("sufficient") and b.get("sufficient"))}
    if out["depth_mismatch"]:
        out["warning"] = (
            f"DEPTH MISMATCH: '{design_a}' reaches {a.get('max_generations')} generation(s) and '{design_b}' "
            f"reaches {b.get('max_generations')}. Compare them at generation {common} (compare_at_generation), "
            f"not on whole-run means — otherwise the difference you measure includes the difference in how far "
            f"each lineage got, which is not a biological effect.")
    return out
