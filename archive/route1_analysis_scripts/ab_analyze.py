from __future__ import absolute_import, division, print_function

import json
import os
import sys

import numpy as np

from wholecell.io.tablereader import TableReader

CTL = sys.argv[1]
TRT = sys.argv[2]

SERIES = [
    ("Mass", "cellMass"),
    ("Mass", "dryMass"),
    ("RibosomeData", "actualElongations"),
    ("GrowthLimits", "ppgpp_conc"),
]


def simout(root):
    return os.path.join(root, "wildtype_000000", "000001", "generation_000000",
                        "000000", "simOut")


def read(root, table, col):
    r = TableReader(os.path.join(simout(root), table))
    return np.asarray(r.readColumn(col))


def bitwise_eq_rows(a, b):
    """Return boolean array over rows: bitwise identical."""
    a = np.atleast_1d(a)
    b = np.atleast_1d(b)
    if a.shape != b.shape:
        return None
    a2 = a.reshape(a.shape[0], -1).astype(np.float64)
    b2 = b.reshape(b.shape[0], -1).astype(np.float64)
    ua = a2.view(np.uint64)
    ub = b2.view(np.uint64)
    return np.all(ua == ub, axis=1)


out = {}

ctl_out = simout(CTL)
trt_out = simout(TRT)
out["ctl_simout"] = ctl_out
out["trt_simout"] = trt_out
out["ctl_exists"] = os.path.isdir(ctl_out)
out["trt_exists"] = os.path.isdir(trt_out)
if not (out["ctl_exists"] and out["trt_exists"]):
    print(json.dumps(out, indent=1))
    sys.exit(2)

# ---- rela_syn ----
rs_c = read(CTL, "GrowthLimits", "rela_syn")
rs_t = read(TRT, "GrowthLimits", "rela_syn")
out["rela_syn_shape_ctl"] = list(rs_c.shape)
out["rela_syn_shape_trt"] = list(rs_t.shape)
out["rela_syn_row0_allzero_ctl"] = bool(np.all(rs_c[0] == 0))
out["rela_syn_row0_allzero_trt"] = bool(np.all(rs_t[0] == 0))
out["rela_syn_nonzero_ctl"] = bool(np.any(rs_c[1:] != 0))
out["rela_syn_nonzero_trt"] = bool(np.any(rs_t[1:] != 0))
out["rela_syn_abs_sum_ctl"] = float(np.abs(rs_c[1:]).sum())
out["rela_syn_abs_sum_trt"] = float(np.abs(rs_t[1:]).sum())

# ---- clean window ----
first_diff = {}
per_series_eq = {}
for table, col in SERIES:
    key = "%s/%s" % (table, col)
    try:
        a = read(CTL, table, col)
        b = read(TRT, table, col)
    except Exception as e:  # noqa
        first_diff[key] = "READ_FAILED: %s" % e
        continue
    eq = bitwise_eq_rows(a, b)
    if eq is None:
        first_diff[key] = "SHAPE_MISMATCH %s vs %s" % (a.shape, b.shape)
        continue
    per_series_eq[key] = eq
    # rows: index 0 = pre-sim dump; evolved step n is row n
    bad = np.where(~eq[1:])[0]
    first_diff[key] = int(bad[0] + 1) if bad.size else None  # evolved-step index
    out["n_rows_" + key] = int(a.shape[0])

out["first_differing_evolved_step"] = first_diff

fds = [v for v in first_diff.values() if isinstance(v, int)]
if fds:
    clean_window = min(fds) - 1  # last fully-identical evolved step count
else:
    clean_window = min(len(e) - 1 for e in per_series_eq.values())
out["clean_window_steps"] = int(clean_window)

# ---- % change in total rela_syn ----
tot_c = rs_c[1:].sum(axis=1)
tot_t = rs_t[1:].sum(axis=1)
n = min(len(tot_c), len(tot_t))
tot_c = tot_c[:n]
tot_t = tot_t[:n]
with np.errstate(divide="ignore", invalid="ignore"):
    pct_all = (tot_t - tot_c) / tot_c * 100.0
pct_all = np.where(tot_c == 0, np.nan, pct_all)

out["n_evolved_steps"] = int(n)
out["total_rela_syn_ctl_step1"] = float(tot_c[0])
out["total_rela_syn_trt_step1"] = float(tot_t[0])

cw = min(clean_window, n)
out["clean_window_used"] = int(cw)
if cw > 0:
    p = pct_all[:cw]
    pf = p[np.isfinite(p)]
    out["clean_pct_n"] = int(pf.size)
    out["clean_pct_median"] = float(np.median(pf)) if pf.size else None
    out["clean_pct_min"] = float(np.min(pf)) if pf.size else None
    out["clean_pct_max"] = float(np.max(pf)) if pf.size else None
    out["clean_pct_first10"] = [float(x) for x in p[:10]]
else:
    out["clean_pct_n"] = 0

out["step1_pct"] = float(pct_all[0]) if np.isfinite(pct_all[0]) else None

pa = pct_all[np.isfinite(pct_all)]
out["max_abs_pct_all_steps"] = float(np.max(np.abs(pa))) if pa.size else None
out["max_abs_pct_all_steps_at"] = int(np.argmax(np.abs(pct_all[np.isfinite(pct_all)])) + 1) if pa.size else None

# ---- per-amino-acid ratio at first evolved step ----
c1 = rs_c[1]
t1 = rs_t[1]
nz = c1 != 0
out["step1_n_nonzero_aa"] = int(nz.sum())
if nz.sum() > 0:
    ratio = t1[nz] / c1[nz]
    out["step1_ratio_min"] = float(np.min(ratio))
    out["step1_ratio_max"] = float(np.max(ratio))
    out["step1_ratio_spread"] = float(np.max(ratio) - np.min(ratio))
    out["step1_ratio_values"] = [repr(float(x)) for x in ratio]
    oc = np.argsort(c1[nz], kind="stable")
    ot = np.argsort(t1[nz], kind="stable")
    out["step1_rank_order_preserved"] = bool(np.array_equal(oc, ot))
    out["step1_ctl_values"] = [float(x) for x in c1]
    out["step1_trt_values"] = [float(x) for x in t1]
else:
    out["step1_ratio_spread"] = None

print(json.dumps(out, indent=1))
