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


# --- the panel orchestrator --------------------------------------------------------------------------------

def panel(factors: dict, *, seeds: int = 4, generations: int = 4, cv: float | None = None,
          effect_pct: float = 10.0, cap: int = 64, block_by: str | None = None, seed: int = 0) -> dict:
    """A full DOE panel for a falsifier: the factorial cells (subsampled past `cap`), a randomized run order,
    optional blocking, the total sim budget, and a power annotation from the supplied replicate `cv`. `factors` is
    {name: [levels]}; each cell is one factor-combination the caller maps onto a Design. Pure — no corpus access."""
    all_cells = full_factorial(factors)
    n_full = len(all_cells)
    cells = screening_subsample(all_cells, cap, seed)
    out = {
        "factors": {k: list(v) for k, v in factors.items()},
        "n_full_factorial": n_full,
        "n_cells": len(cells),
        "subsampled": len(cells) < n_full,
        "seeds_per_cell": seeds,
        "generations": generations,
        "total_sims": len(cells) * seeds,
        "run_order": randomize(cells, seed),
        "power": power_annotation(cv, effect_pct, seeds) if cv is not None else None,
        "note": ("A proper factorial layout with randomized run order"
                 + (f", blocked by '{block_by}'" if block_by else "")
                 + (". Screening subsample (random, aliasing NOT controlled) — the full factorial exceeded the cap."
                    if len(cells) < n_full else ".")),
    }
    if block_by:
        out["blocks"] = {str(k): len(v) for k, v in block(cells, block_by).items()}
    return out
