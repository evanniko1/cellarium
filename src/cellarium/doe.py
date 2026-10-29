"""M-5: design-of-experiments for falsifier panels.

A Council/agent panel is often an ad-hoc "run these designs at N seeds × M generations". This module turns a set
of FACTORS (gene ∈ set, condition ∈ set, dose ∈ levels, …) into a PROPER experimental design: the factorial cells,
a deterministic RANDOMIZED run order (guards an order/time confound), optional BLOCKING by a nuisance factor
(compare within block), a screening subsample when the full factorial explodes, and a POWER annotation grounded in
the real replicate noise — so a panel states which factors it crosses, how it's replicated/blocked, and whether it
can actually resolve the target effect. Pure + scipy-free; the power math mirrors `tools.power_check` (two-sample,
α 0.05, power 0.8) so the two never drift.
"""

from __future__ import annotations

import itertools
import math
import random as _random

# two-sample n-per-group constant (α 0.05, power 0.8): 2·(z_{α/2}+z_β)² — the same constant tools.power_check uses.
_K = 2 * (1.96 + 0.84) ** 2


# --- power (pure; shared shape with tools.power_check) ------------------------------------------------------

def seeds_needed(cv: float | None, effect_pct: float) -> int | None:
    """Replicate seeds PER GROUP needed to detect a relative effect of `effect_pct` given a replicate CV. None when
    the CV is unknown or the target effect is non-positive."""
    if cv is None or effect_pct <= 0:
        return None
    rel = effect_pct / 100.0
    return math.ceil(_K * (cv / rel) ** 2)


def mde_pct(cv: float | None, n_seeds: int) -> float | None:
    """The minimum detectable effect (%) at `n_seeds` per group — the smallest relative effect this replication can
    resolve. A difference below it is UNDER-powered, not proven absent."""
    if cv is None or n_seeds <= 0:
        return None
    return round(cv * math.sqrt(_K / n_seeds) * 100, 2)


def power_annotation(cv: float | None, effect_pct: float, n_seeds: int) -> dict:
    need = seeds_needed(cv, effect_pct)
    return {"observed_replicate_cv": cv, "n_seeds": n_seeds, "target_effect_pct": effect_pct,
            "mde_pct_at_n": mde_pct(cv, n_seeds), "seeds_needed_for_target": need,
            "adequately_powered": (need is not None and n_seeds >= need)}


# --- factorial layout --------------------------------------------------------------------------------------

def full_factorial(factors: dict) -> list[dict]:
    """Every combination of factor levels — the cells of a full-factorial design. `factors` is {name: [levels]};
    a factor with an empty level list drops the whole design to zero cells (nothing to cross)."""
    names = [n for n in factors]
    levels = [list(factors[n]) for n in names]
    if not names or any(len(lv) == 0 for lv in levels):
        return []
    return [dict(zip(names, combo)) for combo in itertools.product(*levels)]


def screening_subsample(cells: list, cap: int, seed: int = 0) -> list[dict]:
    """When the full factorial exceeds `cap`, take a DETERMINISTIC random subsample (a screening design). This is a
    random sample, NOT a resolution-defined fractional factorial — it does not control aliasing, and says so."""
    if cap <= 0 or len(cells) <= cap:
        return cells
    rng = _random.Random(seed)
    picked = rng.sample(cells, cap)
    return sorted(picked, key=lambda c: tuple(sorted(c.items(), key=lambda kv: kv[0])))


# --- randomization + blocking ------------------------------------------------------------------------------

def randomize(cells: list, seed: int = 0) -> list[dict]:
    """A DETERMINISTIC randomized run order (seeded, so a panel reproduces) — guards a confound between run order and
    any drifting nuisance (scheduler, machine, time)."""
    out = list(cells)
    _random.Random(seed).shuffle(out)
    return out


def block(cells: list, by: str) -> dict:
    """Partition cells into blocks by a nuisance factor `by` (e.g. generation depth) so a comparison is made WITHIN a
    block, holding the nuisance fixed. Returns {block_level: [cells]}."""
    blocks: dict = {}
    for c in cells:
        blocks.setdefault(c.get(by), []).append(c)
    return blocks


# --- screening: resolution-defined two-level designs -------------------------------------------------
#
# WHY THESE EXIST. `screening_subsample` above shrinks a factorial by taking a random subset of its cells,
# and its own docstring says the problem: it "does not control aliasing". After a random subsample an effect
# cannot be attributed to a factor, because which effects are confounded with which depends on the draw and is
# never computed. The saving is real and the result is uninterpretable, which is the worse of the two
# failures — a panel that costs less and answers nothing still gets written up.
#
# A regular fractional factorial makes the confounding a DESIGN CHOICE rather than an accident: it picks the
# cells so that the alias structure is known, states it, and reports the resolution so a reader can see which
# effects are clear. Everything below therefore returns `resolution`, `defining_relation` and `aliases`
# together, and every one of those three is computed from the realized sign matrix rather than taken from the
# name of the construction. `tests/test_doe_generators.py` re-derives the defining relation by brute force
# over the matrix and asserts it equals the algebraic one, because a design that reports a resolution it does
# not have is the silent-absence shape in design form.

_SEARCH_BUDGET = 20_000      # generator-assignment combinations to evaluate before falling back to sampling


def two_level_base(m: int) -> list[list[int]]:
    """The 2^m full factorial in ±1 coding, m columns. The base the extra factors are built on top of."""
    return [[1 if (i >> j) & 1 == 0 else -1 for j in range(m)] for i in range(2 ** m)]


def _is_power_of_two(n: int) -> bool:
    return n >= 1 and (n & (n - 1)) == 0


def _defining_relation(generators: list[frozenset]) -> list[frozenset]:
    """Every word in the defining relation: the 2^p-1 products of the generator words.

    Multiplication of words is symmetric difference of index sets, because a factor squared is the identity
    column. Derived from the generator ALGEBRA rather than by scanning the matrix so this stays cheap enough
    to call inside the assignment search — 2^p-1 words instead of 2^k column products. The test brute-forces
    the matrix and asserts the two agree, which is what makes the shortcut safe to rely on."""
    out: set[frozenset] = set()
    p = len(generators)
    for mask in range(1, 2 ** p):
        acc: frozenset = frozenset()
        for j in range(p):
            if (mask >> j) & 1:
                acc = acc ^ generators[j]
        out.add(acc)
    return sorted(out, key=lambda w: (len(w), sorted(w)))


def _aberration(relation: list[frozenset]) -> tuple[int, int]:
    """(resolution, number of words at that length) — the score the assignment search maximizes then minimizes.

    Resolution alone is not enough to choose between two assignments: among equal-resolution designs the one
    with FEWER shortest words confounds fewer effect pairs. That is the standard minimum-aberration criterion,
    and without it the search returns an arbitrary member of a tie."""
    if not relation:
        return (10 ** 6, 0)                       # a full factorial: no words, nothing confounded
    res = min(len(w) for w in relation)
    return (res, sum(1 for w in relation if len(w) == res))


def _alias_groups(relation: list[frozenset], k: int, names: list[str]) -> list[list[str]]:
    """Confounded sets among effects of order <= 2 — the ones a panel actually reports on.

    Order 3 and above is left out on purpose: a resolution-IV design aliases every main effect with a
    three-factor interaction, and listing those would bury the two facts that change a decision (are the main
    effects clear, and which two-factor interactions are indistinguishable) under combinatorial noise.
    `main_effects_clear` carries the first; this list carries the second."""
    classes: dict[tuple, set[tuple]] = {}
    for size in (1, 2):
        for eff in itertools.combinations(range(k), size):
            e = frozenset(eff)
            members = [tuple(sorted(e))] + [tuple(sorted(e ^ w)) for w in relation]
            rep = min(members, key=lambda t: (len(t), t))
            classes.setdefault(rep, set()).add(tuple(sorted(e)))
    out = []
    for members in classes.values():
        if len(members) > 1:
            out.append(sorted("".join(names[i] for i in m) for m in members))
    return sorted(out)


def _word_str(word: frozenset, names: list[str]) -> str:
    return "".join(names[i] for i in sorted(word))


def _best_assignment(m: int, p: int, seed: int) -> tuple[list[frozenset], str, bool]:
    """Choose which base-factor product each extra factor is assigned to.

    Returns (generators, how_searched, minimum_aberration_guaranteed). Exhaustive when the candidate space is
    small enough, otherwise a seeded sample — and the distinction is REPORTED rather than smoothed over,
    because "this is the best design that exists" and "this is the best of 20,000 I looked at" license
    different claims. The descending-length greedy pick is always evaluated, so the sampled path can never
    return something worse than the obvious heuristic.

    The heuristic alone is not enough, which is why the search is here at all: for 6 factors in 16 runs,
    taking the two longest words (ABCD, ABC) gives generators ABCDE and ABCF whose product is DEF — a
    three-letter word, so resolution III. The resolution-IV design assigns ABC and BCD instead."""
    candidates = [frozenset(c) for size in range(m, 1, -1)
                  for c in itertools.combinations(range(m), size)]
    if p == 0:
        return [], "none", True

    def generators_for(words) -> list[frozenset]:
        return [w | {m + j} for j, w in enumerate(words)]

    def score(words) -> tuple[int, int]:
        res, n_short = _aberration(_defining_relation(generators_for(words)))
        return (res, -n_short)

    greedy = tuple(candidates[:p])
    best, best_score = greedy, score(greedy)
    total = math.comb(len(candidates), p)
    if total <= _SEARCH_BUDGET:
        for combo in itertools.combinations(candidates, p):
            s = score(combo)
            if s > best_score:
                best, best_score = combo, s
        return generators_for(best), "exhaustive", True
    rng = _random.Random(seed)
    for _ in range(_SEARCH_BUDGET):
        combo = tuple(rng.sample(candidates, p))
        s = score(combo)
        if s > best_score:
            best, best_score = combo, s
    return generators_for(best), f"sampled({_SEARCH_BUDGET} of {total})", False


def _two_level_names(factors: dict) -> tuple[list[str], dict | None]:
    """The factor names, or an error dict when any factor is not exactly two-level."""
    names = list(factors)
    if not names:
        return names, {"error": "factors must be a non-empty {name: [levels]} map"}
    bad = {n: list(factors[n]) for n in names if len(list(factors[n])) != 2}
    if bad:
        return names, {"error": f"a two-level screening design needs EXACTLY 2 levels per factor; these are "
                                f"not two-level: {bad}. A multi-level factor is either an ARM (run it as a "
                                f"separate design) or needs a space-filling design — see surface_panel."}
    return names, None


def _cells_from_matrix(matrix: list[list[int]], factors: dict, names: list[str]) -> list[dict]:
    """Map a ±1 sign matrix onto real factor levels: +1 is the first declared level, -1 the second."""
    levels = {n: list(factors[n]) for n in names}
    return [{n: levels[n][0] if row[j] == 1 else levels[n][1] for j, n in enumerate(names)} for row in matrix]


def fractional_factorial(factors: dict, runs: int, seed: int = 0) -> dict:
    """A regular 2^(k-p) fraction in `runs` runs, with its alias structure COMPUTED and reported.

    This is the screening design `screening_subsample` could not be: the cells are chosen so that the
    confounding is a stated property of the design instead of a property of the random draw. Use it when the
    full factorial is unaffordable AND an effect still has to be attributable to a factor.

    `resolution` is the length of the shortest word in the defining relation, measured from the realized
    design. III means some main effect is indistinguishable from a two-factor interaction; IV means the main
    effects are clear but two-factor interactions come in confounded pairs; V means both are clear. A full
    factorial has no words at all and reports `resolution=None` rather than a large number, because "no
    aliasing" is a different statement from "aliasing at order 7"."""
    names, err = _two_level_names(factors)
    if err:
        return err
    k = len(names)
    if not _is_power_of_two(runs) or runs < 2:
        return {"error": f"runs={runs} cannot carry a regular fraction — it must be a power of two "
                         f"(4, 8, 16, 32...). For a non-power-of-two screening budget use plackett_burman."}
    if runs < k + 1:
        return {"error": f"{k} factors need at least {k + 1} runs to estimate the main effects alone (one "
                         f"degree of freedom each, plus the mean); runs={runs} cannot resolve them under any "
                         f"design. Either drop factors or raise runs to {2 ** math.ceil(math.log2(k + 1))}."}
    m = int(round(math.log2(runs)))
    if k < m:
        return {"error": f"runs={runs} EXCEEDS the full factorial for {k} factors ({2 ** k} cells); there is "
                         f"nothing to fraction. Use design='full'."}
    p = k - m
    generators, how, guaranteed = _best_assignment(m, p, seed)
    base = two_level_base(m)
    matrix = []
    for row in base:
        extra = []
        for g in generators:
            word = [i for i in g if i < m]
            extra.append(math.prod(row[i] for i in word))
        matrix.append(list(row) + extra)
    relation = _defining_relation(generators)
    aliases = _alias_groups(relation, k, names)
    resolution = min((len(w) for w in relation), default=None)
    main_clear = not any(len(e) == 1 for g in aliases for e in g)
    note = (f"A regular 2^({k}-{p}) fractional factorial in {runs} runs "
            f"(full factorial: {2 ** k} cells). ")
    if resolution is None:
        note += ("No fraction was needed — this IS the full factorial, so nothing is aliased and resolution "
                 "does not apply.")
    else:
        note += (f"Resolution {resolution}: "
                 + ("main effects are CLEAR of two-factor interactions"
                    if main_clear else
                    "at least one MAIN EFFECT is indistinguishable from a two-factor interaction — this "
                    "design screens which factors matter and must NOT be used to estimate interactions")
                 + f". Defining relation I = {' = '.join(_word_str(w, names) for w in relation)}. "
                   f"Generator assignment found by {how}"
                 + ("" if guaranteed else " — best of a BOUNDED search, not provably minimum-aberration")
                 + ".")
    return {"design": "fractional", "fraction": f"2^({k}-{p})", "n_runs": runs,
            "n_full_factorial": 2 ** k, "factors": {n: list(factors[n]) for n in names},
            "cells": _cells_from_matrix(matrix, factors, names), "matrix": matrix,
            "resolution": resolution,
            "defining_relation": [_word_str(w, names) for w in relation],
            "aliases": aliases, "main_effects_clear": main_clear,
            "two_factor_interactions_clear": aliases == [],
            "search": how, "minimum_aberration_guaranteed": guaranteed, "note": note}


# Plackett-Burman generating rows, one cyclic row per run count that is NOT a power of two. The powers of two
# are built from a Hadamard matrix below instead, which is exact and needs no table.
#
# These rows are DATA I could have mistyped, so the test does not check them against this comment — it checks
# the constructed matrix for balance and for pairwise orthogonality, which is the property that makes a
# Plackett-Burman design one. A wrong character breaks orthogonality on some column pair and fails there.
_PB_ROWS = {
    12: "++-+++---+-",
    20: "++--++++-+-+----++-",
    24: "+++++-+-++--++--+-+----",
}


def _hadamard(n: int) -> list[list[int]]:
    """Sylvester's construction: H_1 = [1], H_2n = [[H, H], [H, -H]]. Defined for n a power of two."""
    h = [[1]]
    while len(h) < n:
        h = [row + row for row in h] + [row + [-x for x in row] for row in h]
    return h


def plackett_burman(factors: dict) -> dict:
    """A saturated resolution-III screening design: up to n-1 two-level factors in n runs, n a multiple of 4.

    The cheapest honest answer to "I have budget for a dozen runs and eleven things I might vary". Every main
    effect is estimated and every one of them is aliased with a combination of two-factor interactions, so
    this design answers WHICH FACTORS MATTER and nothing else. That is a real answer and it is also a hard
    limit: a Plackett-Burman result cannot be read as an interaction, and the note says so because this is
    the design most likely to be over-read."""
    names, err = _two_level_names(factors)
    if err:
        return err
    k = len(names)
    n = 4 * math.ceil((k + 1) / 4)
    supported = sorted(set(_PB_ROWS) | {4, 8, 16, 32})
    if n not in supported:
        return {"error": f"{k} factors need {n} runs, and no Plackett-Burman row is tabulated here for "
                         f"n={n}. Available: {supported}. Either drop to "
                         f"{max(s for s in supported if s < n) - 1} factors or use fractional_factorial at "
                         f"the next power of two."}
    if n in _PB_ROWS:
        row = [1 if ch == "+" else -1 for ch in _PB_ROWS[n]]
        matrix = []
        for i in range(n - 1):
            matrix.append([row[(j - i) % (n - 1)] for j in range(n - 1)])
        matrix.append([-1] * (n - 1))
    else:
        matrix = [r[1:] for r in _hadamard(n)]      # drop the all-ones column; n-1 orthogonal ±1 columns
    matrix = [r[:k] for r in matrix]                # keep only as many columns as there are factors
    return {"design": "plackett_burman", "n_runs": n, "n_full_factorial": 2 ** k,
            "factors": {nm: list(factors[nm]) for nm in names},
            "cells": _cells_from_matrix(matrix, factors, names), "matrix": matrix,
            "resolution": 3, "main_effects_clear": False,
            "two_factor_interactions_clear": False,
            "n_spare_columns": (n - 1) - k,
            "note": (f"Plackett-Burman: {k} two-level factors in {n} runs (full factorial: {2 ** k} cells). "
                     f"Resolution III — all {k} MAIN EFFECTS are estimated, and every one of them is aliased "
                     f"with combinations of two-factor interactions. Read this as a ranking of which factors "
                     f"matter, never as an interaction or a mechanism. {(n - 1) - k} spare orthogonal "
                     f"column(s) remain and can be assigned to a dummy factor to estimate error.")}


# --- space filling: designs for a CONTINUOUS lever ---------------------------------------------------
#
# WHY THESE EXIST. Several of the levers here are continuous, not categorical — the charged-fraction anchor
# across 0.55-0.85, a graded-knockout level across 5-99%, a ppGpp clamp. A factorial over a continuous factor
# visits its ENDPOINTS, which is the right design when the response is a line and the wrong one when it is a
# step. The response we care most about is known to be a step: the published HisRS sensitivity threshold sits
# at an interior value with near-insensitivity above it. A two-level design over such a factor reports "the
# setpoint has no effect" or "the setpoint has a large effect" depending on which side of the cliff the two
# levels fall on, and it cannot report the cliff.
#
# Latin hypercube covers the interval; the central composite adds a centre point and axial points, which is
# the smallest design that can distinguish a line from a curve at all. `center_point_curvature` is that
# distinction written out as the one subtraction it reduces to.


def latin_hypercube(ranges: dict, n: int, seed: int = 0, center: bool = False) -> dict:
    """`n` points over continuous factor ranges, exactly one in each of `n` equal bins PER FACTOR.

    That one-per-bin guarantee is the whole difference from a random sample of the same size: a random sample
    leaves gaps and clusters in every one-dimensional projection, so a threshold can sit in a gap and never
    be visited. `ranges` is {name: (lo, hi)}; `center=True` puts each point at its bin midpoint (a reproducible
    grid), otherwise a point is placed at a seeded random position inside its bin.

    What this design CANNOT do is in `refuses`, and it is not a formality: a hypercube has no replicated
    cells and no alias structure, so it supports fitting a surface and does not support testing a factor."""
    names = list(ranges)
    if not names:
        return {"error": "ranges must be a non-empty {name: (lo, hi)} map"}
    if n < 2:
        return {"error": f"n={n} is not a hypercube — stratification needs at least 2 bins per factor"}
    bad = {}
    for name in names:
        try:
            lo, hi = ranges[name]
        except (TypeError, ValueError):
            bad[name] = ranges[name]
            continue
        if not (float(hi) > float(lo)):
            bad[name] = (lo, hi)
    if bad:
        return {"error": f"each range must be a (lo, hi) pair with hi > lo; these are not: {bad}. A "
                         f"zero-width range is a CONSTANT, not a factor — drop it from the design and record "
                         f"it as a fixed setting."}
    rng = _random.Random(seed)
    cols: dict[str, list[float]] = {}
    for name in names:
        lo, hi = (float(v) for v in ranges[name])
        width = (hi - lo) / n
        bins = list(range(n))
        rng.shuffle(bins)
        cols[name] = [lo + (b + (0.5 if center else rng.random())) * width for b in bins]
    points = [{name: cols[name][i] for name in names} for i in range(n)]
    return {"design": "latin_hypercube", "n_points": n, "points": points,
            "ranges": {k: tuple(float(v) for v in ranges[k]) for k in names},
            "stratification": f"one point in each of {n} equal bins, independently per factor",
            "legal": True, "out_of_range": [],
            "refuses": [
                "which factor caused an effect — a hypercube has no alias structure and is not a factorial",
                "a two-group test on a factor level — no cell is replicated, so there is no within-cell error",
                "an interaction term — the points are not laid out to separate one",
            ],
            "note": (f"Latin hypercube: {n} points over {len(names)} continuous factor(s), stratified one per "
                     f"bin in every one-dimensional projection. This is for LOCATING where a response changes "
                     f"— a threshold, a curve — NOT for attributing an effect to a factor: it is not a "
                     f"factorial, it controls no aliasing, and it replicates no cell. Pair it with replicate "
                     f"seeds at the points that matter once the shape is known.")}


def center_point_curvature(y_low: float, y_center: float, y_high: float, tol: float = 1e-12) -> dict:
    """How far the centre point departs from the average of the two endpoints.

    This single subtraction is the entire reason a centre point is worth a run. A two-level design fits a
    straight line through the endpoints and reports its slope; the line fits a genuine linear response and a
    step function equally well, so the slope cannot tell them apart. The centre point is the first
    observation that can: on a line it falls on the midpoint and this is 0, and on a step it does not."""
    curvature = float(y_center) - (float(y_low) + float(y_high)) / 2.0
    linear = abs(curvature) <= tol
    return {"y_low": float(y_low), "y_center": float(y_center), "y_high": float(y_high),
            "curvature": curvature, "linear": linear,
            "note": ("Zero curvature: consistent with a straight line between the endpoints, so a two-level "
                     "design over this range loses nothing." if linear else
                     "NON-ZERO curvature: the response between the endpoints is not a line, so a two-level "
                     "design over this range reports a slope that describes nothing in the interior. Add "
                     "axial points (central_composite) to locate where it bends.")}


def central_composite(ranges: dict, alpha: str | float = "face", center: int = 1,
                      cube_runs: int | None = None, seed: int = 0) -> dict:
    """A response-surface design: a two-level cube, axial points on each factor, and centre point(s).

    `alpha` is the axial distance in coded units. "face" (1.0) keeps every point inside the declared ranges,
    which is the right default here because a range is usually a HARD bound — a charged fraction above 1 or a
    knockout level above 100% is not a design point, it is an invalid run. "rotatable" uses (2^k)^(1/4) > 1,
    which gives the classical equal-precision property and pushes the axial points OUTSIDE the box; when it
    does, every violation is listed in `out_of_range` and `legal` is False. Nothing is clamped: a quietly
    clamped star point turns a rotatable design into a face-centred one while still being reported as
    rotatable, and the model fitted to it would be wrong in a way nothing in the output reveals.

    `cube_runs` builds the cube as a fraction instead of all 2^k corners, and reports that fraction's
    resolution — a surface model needs the two-factor interactions, so resolution V is the bar."""
    names = list(ranges)
    if not names:
        return {"error": "ranges must be a non-empty {name: (lo, hi)} map"}
    k = len(names)
    bad = {}
    for name in names:
        try:
            lo, hi = ranges[name]
        except (TypeError, ValueError):
            bad[name] = ranges[name]
            continue
        if not (float(hi) > float(lo)):
            bad[name] = (lo, hi)
    if bad:
        return {"error": f"each range must be a (lo, hi) pair with hi > lo; these are not: {bad}"}
    if center < 1:
        return {"error": f"center={center}: a central composite design without a centre point cannot detect "
                         f"curvature, which is the only reason to run one instead of a factorial."}
    if isinstance(alpha, str):
        if alpha == "face":
            a = 1.0
        elif alpha == "rotatable":
            a = (2 ** k) ** 0.25
        else:
            return {"error": f"alpha must be 'face', 'rotatable', or a number; got {alpha!r}"}
    else:
        a = float(alpha)
        if a <= 0:
            return {"error": f"alpha must be positive; got {alpha!r}"}
    cube_info: dict | None = None
    if cube_runs is None:
        cube = two_level_base(k)
    else:
        frac = fractional_factorial({nm: [1, -1] for nm in names}, runs=cube_runs, seed=seed)
        if "error" in frac:
            return {"error": f"cube_runs={cube_runs}: {frac['error']}"}
        cube = frac["matrix"]
        cube_info = {"n_runs": frac["n_runs"], "fraction": frac["fraction"],
                     "resolution": frac["resolution"], "defining_relation": frac["defining_relation"],
                     "two_factor_interactions_clear": frac["two_factor_interactions_clear"]}
    coded: list[tuple[str, list[float]]] = [("cube", [float(v) for v in row]) for row in cube]
    for j in range(k):
        for sign in (-1.0, 1.0):
            pt = [0.0] * k
            pt[j] = sign * a
            coded.append(("axial", pt))
    coded.extend(("center", [0.0] * k) for _ in range(center))
    points, kinds, out_of_range = [], [], []
    for kind, pt in coded:
        nat = {}
        for j, name in enumerate(names):
            lo, hi = (float(v) for v in ranges[name])
            mid, half = (lo + hi) / 2.0, (hi - lo) / 2.0
            value = mid + pt[j] * half
            nat[name] = value
            if value < lo or value > hi:
                out_of_range.append({"factor": name, "kind": kind, "coded": pt[j], "value": value,
                                     "range": (lo, hi)})
        points.append(nat)
        kinds.append(kind)
    return {"design": "central_composite", "n_points": len(points), "points": points, "point_kinds": kinds,
            "alpha": a, "alpha_mode": alpha if isinstance(alpha, str) else "explicit",
            "n_center": center, "n_axial": 2 * k, "n_cube": len(cube), "cube": cube_info,
            "ranges": {nm: tuple(float(v) for v in ranges[nm]) for nm in names},
            "out_of_range": out_of_range, "legal": not out_of_range,
            "note": (f"Central composite over {k} factor(s): {len(cube)} cube point(s), {2 * k} axial at "
                     f"alpha={a:.4g}, {center} centre point(s). The centre point is what separates a curve "
                     f"from a line; the axial points are what locate it. "
                     + ("Every point lies inside the declared ranges."
                        if not out_of_range else
                        f"{len(out_of_range)} axial coordinate(s) fall OUTSIDE the declared range and are "
                        f"NOT clamped — see out_of_range. If a range is a hard bound, re-run with "
                        f"alpha='face'."))}


# --- split-plot run order ----------------------------------------------------------------------------

def whole_plot_order(cells: list, whole_plot: str, seed: int = 0) -> dict:
    """A run order for a factor that CANNOT be re-randomized per run — the split-plot layout.

    Not a refinement of `randomize`: it fixes a wrong instruction. A fitted knowledge base is built once and
    shared by many runs, so a fully randomized order over a design that crosses the kb arm with anything else
    asks the operator to rebuild the kb between consecutive runs. They will not, and what they run instead is
    this layout — undeclared, which means the analysis is then wrong about its own error structure.

    Grouping also costs something, and that cost is the reason this has to be declared rather than silently
    adopted: the whole-plot factor is replicated by PLOTS, not by runs, so it is tested against a different
    and much smaller error term. `panel` carries that into the power annotation."""
    if not cells:
        return {"error": "no cells to order"}
    missing = [c for c in cells if whole_plot not in c]
    if missing:
        return {"error": f"whole_plot={whole_plot!r} is not a factor of these cells (first offender: "
                         f"{missing[0]}). A whole-plot factor must be one of the crossed factors."}
    groups = block(cells, whole_plot)
    rng = _random.Random(seed)
    levels = list(groups)
    rng.shuffle(levels)
    order: list[dict] = []
    for lv in levels:
        g = list(groups[lv])
        rng.shuffle(g)
        order.extend(g)
    changes = sum(1 for a, b in zip(order, order[1:]) if a.get(whole_plot) != b.get(whole_plot))
    return {"order": order, "whole_plot": whole_plot,
            "whole_plots": {str(lv): len(groups[lv]) for lv in groups},
            "n_whole_plots": len(groups), "n_level_changes": changes,
            "plot_order": [str(lv) for lv in levels],
            "note": (f"Split-plot order: {len(groups)} whole plot(s) on {whole_plot!r}, the plot order and "
                     f"the runs within each plot both randomized from seed {seed}. {whole_plot!r} changes "
                     f"{changes} time(s) — the minimum, because changing it is the expensive operation. "
                     f"Its effect is replicated by PLOTS ({len(groups)}), not by runs ({len(cells)}).")}


def split_plot_power(cv: float | None, effect_pct: float, whole_plot: str, n_whole_plots: int) -> dict:
    """The power annotation for the whole-plot factor — a different, worse number than the sub-plot one."""
    return {"factor": whole_plot, "n_whole_plots": n_whole_plots,
            "mde_pct_at_n_whole_plots": mde_pct(cv, n_whole_plots),
            "seeds_needed_for_target": seeds_needed(cv, effect_pct),
            "note": (f"{whole_plot!r} is a WHOLE-PLOT factor: it is replicated {n_whole_plots} time(s), not "
                     f"once per seed. Seeds replicate everything nested inside a plot, so the panel's main "
                     f"min-detectable-effect does NOT apply to this factor — read "
                     f"mde_pct_at_n_whole_plots for it. Adding seeds sharpens the sub-plot factors and "
                     f"leaves this one where it is; only more plots move it.")}


# --- the generator-aware panel orchestrators --------------------------------------------------------

def _apply_legality(cells: list[dict], legal) -> tuple[list[dict], list[dict]]:
    """Partition cells into (kept, dropped-with-reason). A predicate returns True/False or (bool, reason)."""
    kept, dropped = [], []
    for c in cells:
        verdict = legal(c)
        ok, reason = verdict if isinstance(verdict, tuple) else (verdict, "")
        if ok:
            kept.append(c)
        else:
            dropped.append({"cell": c, "reason": reason or "not in envelope"})
    return kept, dropped


# Factors whose LEVELS are fitted parameters rather than run-time settings. Crossing one of these as an
# ordinary factor is the one design error in this module that produces a panel which looks runnable and is
# not: each level needs its own ParCa refit, so each level's rows carry a different kb_sha256 and the cells
# are not poolable with each other. A knowledge base is also built once and shared, so such a factor can at
# most be a WHOLE PLOT — never one column of a factorial.
#
# An explicit DECLARATION, not a pattern match. A substring rule over names like "target" or "anchor" would
# refuse valid panels, and a refusal resting on a proxy is the error this project has withdrawn findings for
# more than once. Names that merely LOOK like refit levers are flagged in `possible_refit_factors` and the
# panel still runs — a warning the caller can check, which is what a proxy licenses.
REFIT_FACTORS = (
    "trna_charged_fraction_target",   # ParCa's charged-fraction anchor (EXT-PORT-11) — fitted, per build
    "charged_fraction_target",        # the same lever's short spelling
    "operons",                        # a ParCa-time option; 'off' is a different fit, not a different run
    "retype_cistrons",                # changes the reconstruction INPUT, so the whole fit moves
    "kb", "kb_sha256", "sim_path",    # the knowledge base itself, named directly
    "arm",                            # the arm is kb x operons x elongation model; it is never a factor
)

# Names that are not declared refit levers but read like one. A HINT only — see the comment above.
_REFIT_HINTS = ("refit", "parca", "anchor", "_target", "target_", "knowledge_base")


def refit_factors_in(factors: dict) -> list[str]:
    """Which crossed factors are DECLARED refit levers, in the order the caller supplied them."""
    return [n for n in factors if n in REFIT_FACTORS]


def _possible_refit_factors(factors: dict) -> list[str]:
    """Which crossed factors merely resemble one. Flagged, never refused."""
    return [n for n in factors
            if n not in REFIT_FACTORS and any(h in str(n).lower() for h in _REFIT_HINTS)]


_PANEL_DESIGNS = ("full", "random_screen", "fractional", "plackett_burman")


def panel(factors: dict, *, seeds: int = 4, generations: int = 4, cv: float | None = None,
          effect_pct: float = 10.0, cap: int = 64, block_by: str | None = None, seed: int = 0,
          design: str = "full", runs: int | None = None, whole_plot: str | None = None,
          legal=None) -> dict:
    """A full DOE panel for a falsifier: the cells, a randomized run order, optional blocking, the total sim
    budget, and a power annotation from the supplied replicate `cv`. `factors` is {name: [levels]}; each cell
    is one factor-combination the caller maps onto a Design. Pure — no corpus access.

    `design` selects how the cells are chosen. "full" is the original behaviour, unchanged, including the
    random subsample past `cap`; "random_screen" is that subsample asked for by name. "fractional" (with
    `runs`) and "plackett_burman" are resolution-defined screening designs that report what they confound —
    use those whenever the saving matters, because the subsample does not support attributing an effect.

    `whole_plot` names a factor that cannot be re-randomized per run (a fitted knowledge base, a Docker
    image): the run order is then a split-plot layout and the power annotation gains the whole-plot term.

    `legal` is an optional predicate on a cell, e.g. the envelope check. A generator picks corners nobody
    looked at, so a reduced design is MORE likely than a hand-written grid to propose a run that cannot be
    launched; cells it rejects are removed and listed in `illegal_cells` with reasons, never dropped quietly.
    """
    if design not in _PANEL_DESIGNS:
        return {"error": f"unknown design {design!r}; panel() builds factorial designs over DISCRETE levels: "
                         f"{list(_PANEL_DESIGNS)}. For a continuous factor (a space-filling or "
                         f"response-surface design) use surface_panel()."}
    # Rule 4, checked BEFORE any cells are built: emitting the cells first and warning afterwards would hand
    # a caller a run order they can read past the warning.
    refit = refit_factors_in(factors)
    stray = [n for n in refit if n != whole_plot]
    if stray:
        return {"error": f"factor(s) {stray} are FITTED PARAMETERS, not run-time settings: every level needs "
                         f"its own ParCa refit, so each level's rows carry a different kb_sha256 and the "
                         f"cells are NOT poolable. Such a lever is a separate ARM with its own comparators, "
                         f"and at most a whole-plot factor — never one column of a factorial. Either run one "
                         f"panel per level and compare arms explicitly, or pass whole_plot={stray[0]!r} to "
                         f"declare the split-plot layout (only ONE refit lever can be the whole plot)."}
    gen: dict = {}
    if design in ("full", "random_screen"):
        all_cells = full_factorial(factors)
        n_full = len(all_cells)
        cells = screening_subsample(all_cells, cap, seed)
        subsampled = len(cells) < n_full
    else:
        gen = (fractional_factorial(factors, runs if runs is not None else 0, seed=seed)
               if design == "fractional" else plackett_burman(factors))
        if "error" in gen:
            return gen
        cells, n_full, subsampled = gen["cells"], gen["n_full_factorial"], True
    illegal: list[dict] = []
    if legal is not None:
        cells, illegal = _apply_legality(cells, legal)
    wp_layout = None
    if whole_plot is not None and cells:
        wp = whole_plot_order(cells, whole_plot, seed)
        if "error" in wp:
            return wp
        run_order, wp_layout = wp["order"], wp
    else:
        run_order = randomize(cells, seed)
    power = power_annotation(cv, effect_pct, seeds) if cv is not None else None
    if power is not None and wp_layout is not None:
        power["whole_plot"] = split_plot_power(cv, effect_pct, whole_plot, wp_layout["n_whole_plots"])
    note = ("A proper factorial layout with randomized run order"
            + (f", blocked by '{block_by}'" if block_by else "")
            + (f", split-plot on '{whole_plot}'" if whole_plot else ""))
    if design in ("full", "random_screen"):
        note += (". Screening subsample (random, aliasing NOT controlled) — the full factorial exceeded the "
                 "cap. An effect seen here cannot be attributed to a factor; for that use "
                 "design='fractional' or design='plackett_burman'." if subsampled else ".")
    else:
        note += ". " + gen["note"]
    if illegal:
        note += (f" {len(illegal)} cell(s) DROPPED as illegal before ordering — see illegal_cells; the "
                 f"design is {len(cells)} cells, not {n_full}.")
    arms_spanned = None
    if refit and wp_layout is not None:
        levels = list(factors[whole_plot])
        arms_spanned = {"factor": whole_plot, "n_arms": len(levels), "levels": levels}
        # Declaring the layout is not the same as making the panel poolable. It still spans arms, and the
        # across-arm comparison is a separate, explicit act — which is why this sentence is in the note and
        # not only in a field.
        note += (f" {whole_plot!r} is a FITTED-PARAMETER lever: this panel spans {len(levels)} ARMS and its "
                 f"cells are NOT poolable across it. Each level needs its own ParCa build, and comparing "
                 f"across them is an across-arm comparison with its own comparators.")
    maybe_refit = _possible_refit_factors(factors)
    if maybe_refit:
        note += (f" Factor(s) {maybe_refit} are not declared fitted-parameter levers but read like one — "
                 f"CHECK whether each level needs its own ParCa build; if it does, this is an arm, not a "
                 f"factor (see REFIT_FACTORS).")
    out = {
        "design": design,
        "factors": {k: list(v) for k, v in factors.items()},
        "n_full_factorial": n_full,
        "n_cells": len(cells),
        "subsampled": subsampled,
        "seeds_per_cell": seeds,
        "generations": generations,
        "total_sims": len(cells) * seeds,
        "run_order": run_order,
        "power": power,
        "resolution": gen.get("resolution"),
        "illegal_cells": illegal,
        "arms_spanned": arms_spanned,
        "possible_refit_factors": maybe_refit,
        "note": note,
    }
    for key in ("fraction", "defining_relation", "aliases", "main_effects_clear",
                "two_factor_interactions_clear", "search", "minimum_aberration_guaranteed",
                "n_spare_columns"):
        if key in gen:
            out[key] = gen[key]
    if wp_layout is not None:
        out["whole_plot_layout"] = {k: v for k, v in wp_layout.items() if k != "order"}
    if block_by:
        out["blocks"] = {str(k): len(v) for k, v in block(cells, block_by).items()}
    if not cells:
        out["error"] = ("no legal cells remain — every cell was rejected by the legality predicate"
                        if illegal else "the factors cross to zero cells")
    return out


_SURFACE_DESIGNS = ("latin_hypercube", "central_composite")


def surface_panel(ranges: dict, *, design: str = "latin_hypercube", n: int | None = None, seeds: int = 4,
                  generations: int = 4, cv: float | None = None, effect_pct: float = 10.0, seed: int = 0,
                  alpha: str | float = "face", center: int = 1, cube_runs: int | None = None,
                  legal=None) -> dict:
    """The panel orchestrator for CONTINUOUS factors: a space-filling or response-surface design plus budget.

    Separate from `panel` rather than another `design` value on it, because the two produce different objects.
    `panel`'s cells are factor-LEVEL combinations and its arithmetic is about crossing and confounding;
    these points are numeric coordinates, and a point has no level to block on, no alias structure, and no
    replicate within the design. Folding them together would give one function two meanings for `n_cells`."""
    if design not in _SURFACE_DESIGNS:
        return {"error": f"unknown surface design {design!r}; surface_panel builds designs over CONTINUOUS "
                         f"ranges: {list(_SURFACE_DESIGNS)}. For discrete factor levels (full, fractional, "
                         f"Plackett-Burman) use panel()."}
    if design == "latin_hypercube":
        gen = latin_hypercube(ranges, n if n is not None else 0, seed=seed)
    else:
        gen = central_composite(ranges, alpha=alpha, center=center, cube_runs=cube_runs, seed=seed)
    if "error" in gen:
        return gen
    points = gen["points"]
    illegal: list[dict] = []
    if legal is not None:
        points, illegal = _apply_legality(points, legal)
    out = dict(gen)
    out.update({
        "n_points": len(points),
        "points": points,
        "run_order": randomize(points, seed),
        "seeds_per_point": seeds,
        "generations": generations,
        "total_sims": len(points) * seeds,
        "power": power_annotation(cv, effect_pct, seeds) if cv is not None else None,
        "illegal_points": illegal,
    })
    if illegal:
        out["note"] += f" {len(illegal)} point(s) DROPPED as illegal before ordering — see illegal_points."
    return out
