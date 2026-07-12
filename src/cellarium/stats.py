"""Small shared statistics helpers. Kept in one place so survey + rigor + raw use the same convention (audit M2).

Scipy-free BY DESIGN: the host venv has no scipy (it lives only in the model image), so the t-distribution here
is a stdlib-only implementation. The previous version tried `import scipy` and SILENTLY fell back to 1.96*SE when
it wasn't there — i.e. it always used the normal approximation the docstring warns against, understating every CI
at the n=4-8 seed counts we run. This table fixes that.
"""

from __future__ import annotations

import math
import statistics

_Z975 = 1.959963985  # standard-normal 0.975 quantile

# Two-sided 95% Student-t critical values, df = 1..30 — exactly the small-n regime our seed counts live in, where
# 1.96*SE is 4-60% too narrow (t(3)=3.18 vs 1.96 at n=4). Standard t-table.
_T95 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
    11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
    21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060, 26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
}


def t_critical_95(df: int) -> float:
    """Two-sided 95% Student-t critical value, no scipy. Exact table for df<=30; above, a Cornish-Fisher
    expansion of the inverse-t (accurate for large df, converging to 1.96)."""
    if df <= 0:
        return float("nan")
    if df in _T95:
        return _T95[df]
    z = _Z975  # df > 30: Cornish-Fisher (e.g. df=60 -> 2.000, matching the true value)
    return z + (z ** 3 + z) / (4 * df) + (5 * z ** 5 + 16 * z ** 3 + 3 * z) / (96 * df ** 2)


def t95_halfwidth(values: list[float]) -> float | None:
    """95% CI half-width using the t-distribution — correct for the small seed counts we run (n=4-8), where the
    normal-approx 1.96*SE is ~20-60% too narrow. Returns None for n<2 (CI undefined)."""
    n = len(values)
    if n < 2:
        return None
    se = statistics.stdev(values) / math.sqrt(n)
    return t_critical_95(n - 1) * se
