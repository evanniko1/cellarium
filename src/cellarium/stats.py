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


# --- clustered (non-exchangeable) replicates -----------------------------------------------------------------
# A one-way random-effects decomposition for genuinely clustered replicates — observations that are nested
# within some group and therefore NOT independent, so `s/sqrt(n)` over the pooled set understates the
# uncertainty. This is the correct correction when clusters are exchangeable draws from a population.
#
# It is deliberately NOT applied to this corpus right now, and the story is worth keeping. Two candidate cluster
# variables were tried and both withdrawn — MACHINE (a correlated column: at fixed depth its ICC is 0.0) and
# GENERATION DEPTH (a FIXED effect, not random: a channel is the last generation's time-mean, so depth selects
# which generation is reported, and `survey` stratifies on it rather than correcting for it — see `survey.depth`
# and BACKLOG WELL-6x/6y/6z). The machinery stays because the corpus may yet grow genuinely exchangeable
# clusters, and because the estimator bugs found while withdrawing those attempts (WELL-6z2) are worth having
# fixed regardless. It is agnostic: it decomposes whatever cluster it is handed.

def design_effect(values: list[float], clusters: list) -> dict | None:
    """One-way random-effects decomposition of `values` grouped by `clusters` (any exchangeable grouping).

    Returns the intraclass correlation, the design effect and the EFFECTIVE sample size:
        ICC   = var_between / (var_between + var_within)
        DEFF  = 1 + (m0 - 1) * ICC          <- m0 is HARTLEY'S mean cluster size, the same one used to get ICC
        n_eff = n / DEFF
    `var_between` is clamped at 0 (a negative variance estimate means the data show no cluster effect).

    ⚠️ **`m0`, not `n/k`, and the difference is not cosmetic.** This function computed Hartley's m0 to get the
    variance component and then silently used the plain `n/k` in DEFF. On unbalanced clusters those diverge
    badly: at ICC 0.8457 with sizes [28, 4, 2], m0 gives 2.47x, `n/k` gives 6.60x and Kish's
    `sum(nᵢ²)/n` gives 28.04x — three defensible conventions, one number, and the code was picking by accident.
    A published "6.6x too narrow" came out of exactly that mismatch. One convention throughout.

    ⚠️ **`n` counts only the RETAINED clusters.** Singleton clusters carry no within-cluster information and are
    dropped; the returned `n` reflects the drop, so a caller cannot pair this DEFF with a standard error taken
    over the undropped list. That mismatch made the estimate swing 3.2x on the removal of one row out of 34.

    None when there is only one usable cluster or too few points to decompose.
    """
    groups: dict = {}
    for v, c in zip(values, clusters):
        if v is not None:
            groups.setdefault(c, []).append(float(v))
    n_all = sum(len(v) for v in groups.values())
    groups = {c: v for c, v in groups.items() if len(v) >= 2}
    k = len(groups)
    if k < 2:
        return None
    n = sum(len(v) for v in groups.values())
    grand = statistics.fmean([x for v in groups.values() for x in v])
    ss_between = sum(len(v) * (statistics.fmean(v) - grand) ** 2 for v in groups.values())
    ss_within = sum((x - statistics.fmean(v)) ** 2 for v in groups.values() for x in v)
    ms_between, ms_within = ss_between / (k - 1), ss_within / (n - k)
    m0 = (n - sum(len(v) ** 2 for v in groups.values()) / n) / (k - 1)   # Hartley's m0, not the plain mean
    var_between = max(0.0, (ms_between - ms_within) / m0)
    var_within = ms_within
    total = var_between + var_within
    icc = (var_between / total) if total > 0 else 0.0
    deff = 1.0 + (m0 - 1.0) * icc
    return {"n": n, "n_dropped_singletons": n_all - n, "n_clusters": k,
            "icc": round(icc, 4), "deff": round(deff, 3), "m0": round(m0, 3),
            "n_eff": round(n / deff, 2) if deff else float(n),
            "sd_within": var_within ** 0.5, "sd_between": var_between ** 0.5}


def t95_halfwidth_clustered(values: list[float], clusters: list | None = None) -> tuple:
    """95% half-width that accounts for cluster structure, plus the diagnostics behind it.

    Returns `(half_width, info)`. With one cluster (or none given) this is exactly `t95_halfwidth` and `info` is
    None, so a design run at a single depth is unchanged. With several, the interval is widened by sqrt(DEFF) and
    the t-quantile uses `n_eff - 1` degrees of freedom.

    ⚠️ A caveat that has to travel with the number: with only TWO clusters the between-cluster variance rests on
    one degree of freedom, so DEFF is real but its ESTIMATE is noisy. The correction is therefore better than
    pretending the seeds are independent and worse than having three or more clusters. `info["unreliable"]`
    marks that case, and a high ICC there should be read as "do not quote a pooled interval" rather than as a
    precise widening.

    ⚠️ **NOT currently applied to this corpus, on purpose.** It was, to generation depth, and that was wrong:
    depth is a recorded FIXED effect (a channel is the last generation's time-mean, so depth selects which
    generation is reported), and modelling a deterministic shift as random between-group variance widens the
    interval while leaving the MEAN biased. `survey` stratifies instead. This stays because it is the right
    tool for genuinely exchangeable clusters — which the corpus may yet have — and because the bugs found while
    withdrawing it are worth having fixed. See `survey.depth`.
    """
    n = len(values)
    if n < 2:
        return None, None
    base = t95_halfwidth(values)
    if clusters is None:
        return base, None
    de = design_effect(values, clusters)
    if not de or de["deff"] <= 1.0:
        # `unreliable`/`df` must be present on EVERY path. Omitting them here made `info.get("unreliable")`
        # return None rather than False, so a caller testing `is False` silently saw neither.
        return base, (dict(de, df=n - 1, widened_by=1.0, unreliable=de["n_clusters"] < 3) if de else None)
    # The SE must be taken over the SAME points the DEFF describes: `design_effect` drops singleton clusters, so
    # using the full list here pairs a design effect for one sample with a standard error for another. Live
    # consequence before the fix: deleting one row of 34 moved the half-width 1.2012 -> 3.878.
    used = _cluster_retained(values, clusters)
    se = statistics.stdev(used) / math.sqrt(len(used))
    # df CANNOT exceed k-1. The between-cluster variance rests on k-1 degrees of freedom no matter how many
    # observations sit inside those clusters, so `n_eff - 1` over-states it whenever n_eff > k: on this corpus
    # it claimed df=14 against k-1=2, an interval 2.0x too narrow on 8 of 9 channels.
    df = max(1, min(int(round(de["n_eff"])) - 1, de["n_clusters"] - 1))
    hw = t_critical_95(df) * se * math.sqrt(de["deff"])
    info = {**de, "df": df, "df_cap": de["n_clusters"] - 1, "widened_by": round(hw / base, 2) if base else None,
            "unreliable": de["n_clusters"] < 3,
            "note": ("Observations are nested within cluster, so the interval was widened by sqrt(DEFF) with "
                     "df capped at n_clusters-1."
                     + (" With only two clusters this estimate rests on 1 df — treat a high ICC as 'do not "
                        "quote a pooled interval', not as a precise correction." if de["n_clusters"] < 3 else ""))}
    return hw, info


def _cluster_retained(values: list[float], clusters: list) -> list[float]:
    """The values `design_effect` actually decomposed — i.e. with singleton clusters dropped."""
    groups: dict = {}
    for v, c in zip(values, clusters):
        if v is not None:
            groups.setdefault(c, []).append(float(v))
    keep = [x for v in groups.values() if len(v) >= 2 for x in v]
    return keep if len(keep) >= 2 else [float(v) for v in values if v is not None]


# --- t-distribution p-value (scipy-free) -----------------------------------------------------------------
# A slope/coefficient p-value needs the t CDF, which the t-table above can't give. This is the regularized
# incomplete beta I_x(a,b) (Numerical Recipes continued fraction) — the standard scipy-free route to the
# Student-t tail. Used by rigor.fit_relation so a growth "law" carries a slope p-value, not just R² (audit DS-1).

def _betacf(a: float, b: float, x: float) -> float:
    MAXIT, EPS, FPMIN = 200, 3.0e-12, 1.0e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < FPMIN:
        d = FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, MAXIT + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < EPS:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a, b), for x in [0, 1]."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    bt = math.exp(lbeta + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def t_two_sided_p(t: float | None, df: int) -> float | None:
    """Two-sided p-value for a Student-t statistic (scipy-free). None for df<1 or t undefined."""
    if t is None or df < 1:
        return None
    dff = float(df)
    return _betai(dff / 2.0, 0.5, dff / (dff + float(t) * float(t)))


def welch_t(a: list[float], b: list[float]) -> dict | None:
    """Two-sample Welch (unequal-variance) t-test between samples a and b — the right test for two designs' seed
    replicates, which have different spreads. Returns {t, df, p, mean_a, mean_b, n_a, n_b} with the two-sided p from
    the incomplete-beta t CDF and the Welch–Satterthwaite (fractional) df. None when either n<2 (df undefined) or
    both samples are constant (no variance to test)."""
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return None
    ma, mb = statistics.fmean(a), statistics.fmean(b)
    sa, sb = statistics.variance(a) / na, statistics.variance(b) / nb   # squared standard errors
    denom = sa + sb
    if denom <= 0:
        return None
    t = (ma - mb) / math.sqrt(denom)
    df = denom * denom / (sa * sa / (na - 1) + sb * sb / (nb - 1))       # Welch–Satterthwaite
    p = t_two_sided_p(t, max(1, int(round(df))))
    return {"t": round(t, 3), "df": round(df, 1), "p": (round(p, 4) if p is not None else None),
            "mean_a": round(ma, 4), "mean_b": round(mb, 4), "n_a": na, "n_b": nb}


# --- shape statistics + bimodality (scipy-free) ----------------------------------------------------------
# Sample skewness/kurtosis and Sarle's bimodality coefficient — the executable form of the Council's
# "test for bimodality" decision rule (audit M-1). BC is a small-n-honest heuristic; Hartigan's dip test is
# the gold standard but needs a bootstrap null, which we don't carry here.

def _central_moments(values: list[float]) -> tuple[int, float, float, float]:
    n = len(values)
    m = statistics.fmean(values)
    m2 = sum((x - m) ** 2 for x in values) / n
    m3 = sum((x - m) ** 3 for x in values) / n
    m4 = sum((x - m) ** 4 for x in values) / n
    return n, m2, m3, m4


def skewness(values: list[float]) -> float | None:
    """Bias-corrected sample skewness G1. None for n<3 or zero variance."""
    n, m2, m3, _ = _central_moments(values)
    if n < 3 or m2 == 0:
        return None
    g1 = m3 / m2 ** 1.5
    return g1 * math.sqrt(n * (n - 1)) / (n - 2)


def kurtosis_excess(values: list[float]) -> float | None:
    """Bias-corrected sample EXCESS kurtosis G2 (normal -> 0). None for n<4 or zero variance."""
    n, m2, _, m4 = _central_moments(values)
    if n < 4 or m2 == 0:
        return None
    g2 = m4 / m2 ** 2 - 3.0
    return ((n - 1) / ((n - 2) * (n - 3))) * ((n + 1) * g2 + 6)


def bimodality_coefficient(values: list[float]) -> float | None:
    """Sarle's bimodality coefficient BC = (g1^2 + 1) / (g2 + 3), from POPULATION skewness g1 and excess kurtosis
    g2 — the form the 5/9 threshold is defined against (uniform=5/9, normal=1/3, two equal modes=1). The
    bias-corrected sample version shifts the threshold at small n, so BC uses population moments here; the tool
    still reports the bias-corrected skewness/kurtosis separately. BC in (0, 1]. None for n<4 / zero variance."""
    n, m2, m3, m4 = _central_moments(values)
    if n < 4 or m2 == 0:
        return None
    g1 = m3 / m2 ** 1.5           # population skewness
    g2 = m4 / m2 ** 2 - 3.0       # population excess kurtosis (>= -2 always, so denom >= 1)
    denom = g2 + 3.0
    if denom <= 0:
        return None
    return (g1 * g1 + 1.0) / denom


BC_BIMODAL_THRESHOLD = 5.0 / 9.0  # Sarle's rule of thumb: BC above this suggests two modes


def bh_qvalues(pvals: list[float]) -> list[float]:
    """Benjamini-Hochberg adjusted q-values (same order as input) — the multiple-testing control the change-point
    scan applies across detected events (SP-2). Standard step-up: q_(i) = min over k>=i of p_(k)*n/k, clamped to 1."""
    n = len(pvals)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: pvals[i])   # ascending by p
    q = [1.0] * n
    running = 1.0
    for rank in range(n - 1, -1, -1):
        i = order[rank]
        running = min(running, pvals[i] * n / (rank + 1))
        q[i] = min(running, 1.0)
    return q
