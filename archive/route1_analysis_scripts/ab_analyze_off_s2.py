import os
import numpy as np
from wholecell.io.tablereader import TableReader

CTL = '/wcEcoli/out/ab_off_s2_ctl/wildtype_000000/000002/generation_000000/000000/simOut'
TRT = '/wcEcoli/out/ab_off_s2_trt/wildtype_000000/000002/generation_000000/000000/simOut'

def read(d, table, col):
    return TableReader(os.path.join(d, table)).readColumn(col)

np.set_printoptions(precision=17, suppress=False)

series = [
    ('Mass', 'cellMass'),
    ('Mass', 'dryMass'),
    ('RibosomeData', 'actualElongations'),
    ('GrowthLimits', 'ppgpp_conc'),
]

print('=== SHAPES ===')
for t, c in series:
    a = read(CTL, t, c); b = read(TRT, t, c)
    print(t + '/' + c, a.shape, b.shape)

rc = read(CTL, 'GrowthLimits', 'rela_syn')
rt = read(TRT, 'GrowthLimits', 'rela_syn')
print('rela_syn shapes', rc.shape, rt.shape)
print('row0 ctl allzero', bool(np.all(rc[0] == 0)), 'row0 trt allzero', bool(np.all(rt[0] == 0)))
print('rela_syn ctl nonzero count (excl row0)', int(np.count_nonzero(rc[1:])))
print('rela_syn trt nonzero count (excl row0)', int(np.count_nonzero(rt[1:])))
print('rela_syn ctl total sum (excl row0)', repr(float(rc[1:].sum())))
print('rela_syn trt total sum (excl row0)', repr(float(rt[1:].sum())))

print()
print('=== FIRST DIFFERING EVOLVED STEP (1-indexed evolved step; row index = step) ===')
first_diffs = {}
for t, c in series:
    a = read(CTL, t, c); b = read(TRT, t, c)
    n = min(a.shape[0], b.shape[0])
    fd = None
    for i in range(1, n):
        if not np.array_equal(a[i], b[i]):
            fd = i
            break
    first_diffs[t + '/' + c] = fd
    print('%-32s first_diff_row=%s  (evolved step %s)  nrows=%d' % (t + '/' + c, fd, fd, n))
    # also report row 0 equality
    print('    row0 identical:', bool(np.array_equal(a[0], b[0])))

vals = [v for v in first_diffs.values() if v is not None]
clean_window = (min(vals) - 1) if vals else (min(read(CTL, 'Mass', 'cellMass').shape[0], 121) - 1)
print()
print('CLEAN WINDOW (leading evolved steps bitwise identical in all 4) =', clean_window)

print()
print('=== TOTAL rela_syn per-step %% change (rows 1..120) ===')
tot_c = rc[1:].sum(axis=1)
tot_t = rt[1:].sum(axis=1)
pct = (tot_t - tot_c) / tot_c * 100.0
print('n steps', pct.shape[0])
w = clean_window
print('clean window steps used:', w)
cw = pct[:w]
print('clean median %%', repr(float(np.median(cw))))
print('clean min    %%', repr(float(np.min(cw))))
print('clean max    %%', repr(float(np.max(cw))))
print('clean mean   %%', repr(float(np.mean(cw))))
print('ALL 120 steps: worst |%%|', repr(float(np.max(np.abs(pct)))), 'at step', int(np.argmax(np.abs(pct))) + 1)
print('ALL 120 steps: min %%', repr(float(np.min(pct))), ' max %%', repr(float(np.max(pct))))
print()
print('first 10 step %%:', [float(x) for x in pct[:10]])

print()
print('=== STEP 1 PER-AMINO-ACID RATIO ===')
c1 = rc[1]
t1 = rt[1]
print('ctl step1:', [repr(float(x)) for x in c1])
print('trt step1:', [repr(float(x)) for x in t1])
nz = c1 != 0
print('nonzero AA count', int(nz.sum()), 'of', c1.shape[0])
ratio = t1[nz] / c1[nz]
print('ratios:', [repr(float(x)) for x in ratio])
print('ratio min', repr(float(ratio.min())), 'max', repr(float(ratio.max())))
print('SPREAD (max-min)', repr(float(ratio.max() - ratio.min())))
# rank order preserved?
oc = np.argsort(c1[nz], kind='stable')
ot = np.argsort(t1[nz], kind='stable')
print('rank order preserved:', bool(np.array_equal(oc, ot)))
print('trt zero where ctl nonzero:', int(np.count_nonzero(t1[nz] == 0)))
print('trt nonzero where ctl zero:', int(np.count_nonzero(t1[~nz] != 0)))
print('step1 total ctl', repr(float(c1.sum())), 'trt', repr(float(t1.sum())))
print('step1 total %%', repr(float((t1.sum() - c1.sum()) / c1.sum() * 100.0)))
