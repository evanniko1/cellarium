from __future__ import absolute_import, division, print_function
import os, sys, json
import numpy as np
from wholecell.io.tablereader import TableReader

CTL = sys.argv[1]
TRT = sys.argv[2]

def read(root, table, col):
    tr = TableReader(os.path.join(root, table))
    return np.asarray(tr.readColumn(col))

SERIES = [
    ('Mass', 'cellMass'),
    ('Mass', 'dryMass'),
    ('RibosomeData', 'actualElongations'),
    ('GrowthLimits', 'ppgpp_conc'),
]

def first_diff_row(a, b):
    """Return 1-indexed evolved-step of first bitwise difference (row0 excluded), or None."""
    if a.shape != b.shape:
        return ('SHAPE_MISMATCH', a.shape, b.shape)
    av = a.astype(np.float64).reshape(a.shape[0], -1)
    bv = b.astype(np.float64).reshape(b.shape[0], -1)
    ab = av.view(np.uint8)
    bb = bv.view(np.uint8)
    n = a.shape[0]
    for i in range(1, n):
        if not np.array_equal(ab[i], bb[i]):
            return i
    return None

out = {}

# --- shapes / basic ---
rs_c = read(CTL, 'GrowthLimits', 'rela_syn')
rs_t = read(TRT, 'GrowthLimits', 'rela_syn')
out['rela_syn_shape_ctl'] = list(rs_c.shape)
out['rela_syn_shape_trt'] = list(rs_t.shape)
out['rela_syn_row0_allzero_ctl'] = bool(np.all(rs_c[0] == 0))
out['rela_syn_row0_allzero_trt'] = bool(np.all(rs_t[0] == 0))
out['rela_syn_nonzero_ctl'] = bool(np.any(rs_c[1:] != 0))
out['rela_syn_nonzero_trt'] = bool(np.any(rs_t[1:] != 0))
out['rela_syn_sum_ctl'] = float(rs_c[1:].sum())
out['rela_syn_sum_trt'] = float(rs_t[1:].sum())

# --- clean window ---
fd = {}
for tbl, col in SERIES:
    a = read(CTL, tbl, col)
    b = read(TRT, tbl, col)
    fd['%s/%s' % (tbl, col)] = first_diff_row(a, b)
    out['shape_%s_%s' % (tbl, col)] = [list(a.shape), list(b.shape)]
out['first_diff'] = fd

vals = [v for v in fd.values() if isinstance(v, int)]
if vals:
    first_any = min(vals)
else:
    first_any = None
n_steps = rs_c.shape[0] - 1
clean_window = (first_any - 1) if first_any is not None else n_steps
out['clean_window_steps'] = int(clean_window)
out['n_evolved_steps'] = int(n_steps)

# --- % change in total rela_syn ---
tot_c = rs_c[1:].sum(axis=1)
tot_t = rs_t[1:].sum(axis=1)
with np.errstate(divide='ignore', invalid='ignore'):
    pct = (tot_t - tot_c) / tot_c * 100.0
out['n_zero_total_ctl_steps'] = int(np.sum(tot_c == 0))

if clean_window > 0:
    w = pct[:clean_window]
    wf = w[np.isfinite(w)]
    out['clean_pct_median'] = repr(float(np.median(wf)))
    out['clean_pct_min'] = repr(float(np.min(wf)))
    out['clean_pct_max'] = repr(float(np.max(wf)))
    out['clean_pct_n'] = int(wf.size)
    out['clean_pct_all'] = [repr(float(x)) for x in w]
else:
    out['clean_pct_median'] = None

allf = pct[np.isfinite(pct)]
out['max_abs_pct_all_steps'] = repr(float(np.max(np.abs(allf))))
out['argmax_abs_pct_step_1indexed'] = int(np.argmax(np.abs(np.where(np.isfinite(pct), pct, 0.0)))) + 1
out['step1_pct'] = repr(float(pct[0]))

# --- per-amino-acid ratio at first evolved step ---
c1 = rs_c[1]
t1 = rs_t[1]
nz = c1 != 0
out['n_nonzero_aa_step1'] = int(nz.sum())
if nz.sum() > 0:
    ratio = t1[nz] / c1[nz]
    out['step1_ratio_min'] = repr(float(ratio.min()))
    out['step1_ratio_max'] = repr(float(ratio.max()))
    out['step1_ratio_spread'] = repr(float(ratio.max() - ratio.min()))
    oc = np.argsort(np.argsort(c1[nz]))
    ot = np.argsort(np.argsort(t1[nz]))
    out['step1_rank_preserved'] = bool(np.array_equal(oc, ot))
    out['step1_ctl_vals'] = [repr(float(x)) for x in c1]
    out['step1_trt_vals'] = [repr(float(x)) for x in t1]
    out['step1_ratios'] = [repr(float(x)) for x in ratio]

print("###JSON###")
print(json.dumps(out, indent=1))
