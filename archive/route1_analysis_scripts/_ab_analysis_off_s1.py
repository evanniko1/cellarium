from __future__ import absolute_import, division, print_function
import os, sys
import numpy as np
from wholecell.io.tablereader import TableReader

CTL = '/wcEcoli/out/ab_off_s1_ctl/wildtype_000000/000001/generation_000000/000000/simOut'
TRT = '/wcEcoli/out/ab_off_s1_trt/wildtype_000000/000001/generation_000000/000000/simOut'

def read(sd, table, col):
    return TableReader(os.path.join(sd, table)).readColumn(col)

def main():
    for sd in (CTL, TRT):
        if not os.path.isdir(sd):
            print('MISSING_SIMOUT', sd); return 1
    print('SIMOUT_OK')

    series = [('Mass', 'cellMass'), ('Mass', 'dryMass'),
              ('RibosomeData', 'actualElongations'), ('GrowthLimits', 'ppgpp_conc')]

    first_diff = {}
    for tbl, col in series:
        a = np.asarray(read(CTL, tbl, col))
        b = np.asarray(read(TRT, tbl, col))
        print('SHAPE %s/%s ctl=%s trt=%s' % (tbl, col, a.shape, b.shape))
        n = min(a.shape[0], b.shape[0])
        # row 0 = pre-sim dump; evolved steps are rows 1..n-1
        fd = None
        for i in range(1, n):
            if not np.array_equal(a[i], b[i]):
                fd = i  # evolved step index i (1-based == step i)
                break
        first_diff['%s/%s' % (tbl, col)] = fd
        print('FIRSTDIFF %s/%s step=%s' % (tbl, col, fd))

    fds = [v if v is not None else 10**9 for v in first_diff.values()]
    clean = min(fds) - 1  # number of leading evolved steps bitwise identical
    if clean > 120:
        clean = 120
    print('CLEAN_WINDOW_STEPS %d' % clean)

    rc = np.asarray(read(CTL, 'GrowthLimits', 'rela_syn'), dtype=np.float64)
    rt = np.asarray(read(TRT, 'GrowthLimits', 'rela_syn'), dtype=np.float64)
    print('RELA_SHAPE ctl=%s trt=%s' % (rc.shape, rt.shape))
    print('RELA_ROW0_ALLZERO ctl=%s trt=%s' % (bool(np.all(rc[0] == 0)), bool(np.all(rt[0] == 0))))
    print('RELA_NONZERO_ctl=%s trt=%s' % (bool(np.any(rc[1:] != 0)), bool(np.any(rt[1:] != 0))))
    print('RELA_ABSSUM ctl=%.12e trt=%.12e' % (np.abs(rc[1:]).sum(), np.abs(rt[1:]).sum()))

    tc = rc[1:].sum(axis=1)
    tt = rt[1:].sum(axis=1)
    n = min(len(tc), len(tt))
    tc, tt = tc[:n], tt[:n]
    with np.errstate(divide='ignore', invalid='ignore'):
        pct = (tt - tc) / tc * 100.0
    pct = np.where(tc == 0, np.nan, pct)

    print('N_EVOLVED_STEPS %d' % n)
    print('TOTAL_RELA_STEP1 ctl=%.17g trt=%.17g' % (tc[0], tt[0]))
    print('STEP1_PCT %.12g' % pct[0])

    if clean >= 1:
        w = pct[:clean]
        wf = w[np.isfinite(w)]
        print('CLEAN_N_FINITE %d' % wf.size)
        print('CLEAN_MEDIAN_PCT %.12g' % np.median(wf))
        print('CLEAN_MIN_PCT %.12g' % np.min(wf))
        print('CLEAN_MAX_PCT %.12g' % np.max(wf))
        print('CLEAN_PER_STEP %s' % ' '.join('%.10g' % v for v in w))
    else:
        print('CLEAN_WINDOW_EMPTY')

    allf = pct[np.isfinite(pct)]
    print('ALLSTEPS_MAXABS_PCT %.12g' % np.max(np.abs(allf)))
    print('ALLSTEPS_ARGMAXABS_STEP %d' % (int(np.argmax(np.abs(np.nan_to_num(pct, nan=0.0)))) + 1))

    # step-1 per-amino-acid ratio
    c1 = rc[1]; t1 = rt[1]
    nz = c1 != 0
    print('STEP1_NONZERO_AA %d of %d' % (int(nz.sum()), c1.size))
    ratios = t1[nz] / c1[nz]
    print('STEP1_RATIO_MIN %.17g' % ratios.min())
    print('STEP1_RATIO_MAX %.17g' % ratios.max())
    print('STEP1_RATIO_SPREAD %.6e' % (ratios.max() - ratios.min()))
    order_c = np.argsort(c1[nz], kind='stable')
    order_t = np.argsort(t1[nz], kind='stable')
    print('STEP1_RANK_PRESERVED %s' % bool(np.array_equal(order_c, order_t)))
    print('STEP1_RATIOS %s' % ' '.join('%.15g' % r for r in ratios))
    print('STEP1_CTL_VALS %s' % ' '.join('%.10g' % v for v in c1))
    print('STEP1_TRT_VALS %s' % ' '.join('%.10g' % v for v in t1))
    return 0

sys.exit(main())
