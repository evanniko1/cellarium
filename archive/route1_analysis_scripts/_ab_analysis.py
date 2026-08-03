from __future__ import print_function
import numpy as np
from wholecell.io.tablereader import TableReader
import os, json

CTL = "/wcEcoli/out/ab_off_s0_ctl/wildtype_000000/000000/generation_000000/000000/simOut"
TRT = "/wcEcoli/out/ab_off_s0_trt/wildtype_000000/000000/generation_000000/000000/simOut"

def col(base, table, column):
    return TableReader(os.path.join(base, table)).readColumn(column)

def first_diff(a, b):
    a = np.asarray(a); b = np.asarray(b)
    n = min(a.shape[0], b.shape[0])
    for i in range(n):
        x, y = a[i], b[i]
        if not np.array_equal(np.asarray(x).view(np.uint8) if False else x, y):
            return i
    return None

series = [
    ("Mass/cellMass", "Mass", "cellMass"),
    ("Mass/dryMass", "Mass", "dryMass"),
    ("RibosomeData/actualElongations", "RibosomeData", "actualElongations"),
    ("GrowthLimits/ppgpp_conc", "GrowthLimits", "ppgpp_conc"),
]

out = {}
print("shapes / first differing ROW INDEX (raw, row0 = pre-sim dump):")
fd_rows = []
for name, t, c in series:
    a = col(CTL, t, c); b = col(TRT, t, c)
    fd = first_diff(a, b)
    fd_rows.append(fd)
    print("  %-32s ctl%s trt%s  first_diff_row=%s" % (name, a.shape, b.shape, fd))

print()
# rela_syn
ra = col(CTL, "GrowthLimits", "rela_syn")
rb = col(TRT, "GrowthLimits", "rela_syn")
print("rela_syn shapes ctl%s trt%s" % (ra.shape, rb.shape))
print("row0 ctl allzero=%s  trt allzero=%s" % (not ra[0].any(), not rb[0].any()))
print("ctl nonzero total (rows1:) =", float(np.abs(ra[1:]).sum()))
print("trt nonzero total (rows1:) =", float(np.abs(rb[1:]).sum()))

# evolved steps = rows 1..N
ta = ra[1:]; tb = rb[1:]
n = min(ta.shape[0], tb.shape[0])
print("evolved steps:", n)

# clean window in EVOLVED STEP units: row index i corresponds to evolved step i
# first differing evolved step = fd_row (since row0 identical/zero) -> evolved step = fd_row
print()
print("first differing EVOLVED STEP per series (row_index maps to evolved step = row_index):")
for (name, t, c), fd in zip(series, fd_rows):
    print("  %-32s %s" % (name, fd))

clean = min([f for f in fd_rows if f is not None] + [n + 1])
# clean window length in evolved steps: steps 1..(clean-1) identical entering state.
# Number of leading evolved steps bitwise identical = clean-1 if some diff, else n
if any(f is None for f in fd_rows) and all(f is None for f in fd_rows):
    clean_steps = n
else:
    clean_steps = clean - 1
print("CLEAN WINDOW (leading evolved steps bitwise identical in all 4) =", clean_steps)

tot_a = ta.sum(axis=1)
tot_b = tb.sum(axis=1)
pct = 100.0 * (tot_b - tot_a) / tot_a

w = pct[:clean_steps] if clean_steps > 0 else np.array([])
print()
if w.size:
    print("clean-window total rela_syn %% change: median=%.10f min=%.10f max=%.10f (n=%d)" % (
        np.median(w), w.min(), w.max(), w.size))
else:
    print("clean window empty")

print("step1 pct = %.12f" % pct[0])
print("step1 totals: ctl=%.12e trt=%.12e" % (tot_a[0], tot_b[0]))

# per-AA ratio at first evolved step
a0 = ta[0]; b0 = tb[0]
nz = a0 != 0
ratios = b0[nz] / a0[nz]
print("step1 nonzero AA count:", int(nz.sum()), "of", a0.size)
print("step1 ratio min=%.15f max=%.15f spread=%.6e" % (ratios.min(), ratios.max(), ratios.max()-ratios.min()))
ra_order = np.argsort(a0[nz]); rb_order = np.argsort(b0[nz])
print("rank order preserved:", bool(np.array_equal(ra_order, rb_order)))
print("step1 ratios:", " ".join("%.15f" % r for r in ratios))

print()
print("worst |pct| over ALL %d evolved steps = %.10f (at step %d)" % (
    n, np.abs(pct).max(), int(np.argmax(np.abs(pct)))+1))
print("all-steps pct: median=%.10f min=%.10f max=%.10f" % (np.median(pct), pct.min(), pct.max()))
print()
print("first 10 clean-window pct:", " ".join("%.10f" % v for v in pct[:min(10, clean_steps if clean_steps>0 else 0)]))
