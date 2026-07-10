"""Small shared statistics helpers. Kept in one place so survey + rigor use the same convention (audit M2)."""

from __future__ import annotations

import math
import statistics


def t95_halfwidth(values: list[float]) -> float | None:
    """95% CI half-width using the t-distribution — correct for the small seed counts we run (n=4-8), where the
    normal-approx `1.96*SE` is ~20-60% too narrow. Falls back to 1.96 if scipy is unavailable."""
    n = len(values)
    if n < 2:
        return None
    se = statistics.stdev(values) / math.sqrt(n)
    try:
        from scipy import stats as _s
        return float(_s.t.ppf(0.975, n - 1)) * se
    except Exception:
        return 1.96 * se
