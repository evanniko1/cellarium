"""QC-VIA-1 step 1 — how many `ok` corpus rows are translationally dead cells?

WHAT THIS ANSWERS, and why no query can. `divided` is `full_chromosome_end == 2 and n_steps > 10` --
chromosome count and nothing else. DNA replication proceeds without functioning translation, so a cell
whose ribosomes had stopped scored divided=True and fell through to `qc=ok`. IMPLAUSIBLE_GROWTH is a
CEILING; there was no floor until `423a227`. Rows written before that cannot self-correct, because the
channel they would be judged on was never recorded -- no shard carries an elongation column, so the raw
has to be opened.

MEASUREMENT ONLY. This writes nothing to the manifest and relabels nothing. Step 2 of the backlog item
is the decision that follows from the number; conflating the two would relabel published data on the
strength of a scan nobody had reviewed.

Runs INSIDE the model container in ONE invocation -- 286 generation dirs, not 286 container starts --
because it needs exactly one channel per generation (RibosomeData/effectiveElongationRate) rather than
the full record `_reader_worker` builds.

The 1.0 aa/s floor is anchored to measurement, not chosen: 20-21 aa/s above one doubling/h (Forchhammer
& Lindahl 1971), 17 fast / 12 at 0.67 doublings/h (Young & Bremer 1976), and decisively Dai et al. 2016
(PMID 27941827) -- the rate does NOT collapse as growth slows, because a slow cell reduces its ACTIVE
RIBOSOME FRACTION instead. "It was just growing slowly" is not an available reading of 0.05 aa/s.
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

sys.path.insert(0, "/wcEcoli")
from wholecell.io.tablereader import TableReader  # noqa: E402

FLOOR = 1.0
OUT_ROOT = "/wcEcoli/out"


def elongation_mean(simout: str):
    try:
        r = TableReader(os.path.join(simout, "RibosomeData"))
        try:
            v = np.asarray(r.readColumn("effectiveElongationRate"))
        finally:
            r.close()
        m = float(np.nanmean(v))
        return m if np.isfinite(m) else None
    except Exception:
        return None          # channel absent (an older image) -- UNKNOWN, never "fine"


def n_steps(simout: str):
    try:
        r = TableReader(os.path.join(simout, "Main"))
        try:
            return int(np.asarray(r.readColumn("time")).ravel().size)
        finally:
            r.close()
    except Exception:
        return None


def main():
    rows = []
    for dirpath, dirnames, _files in os.walk(OUT_ROOT):
        if os.path.basename(dirpath) != "simOut":
            continue
        dirnames[:] = []
        rel = os.path.relpath(dirpath, OUT_ROOT).replace(os.sep, "/")
        m = elongation_mean(dirpath)
        rows.append({"path": rel, "elongation_mean": m, "n_steps": n_steps(dirpath),
                     "verdict": ("unknown" if m is None else
                                 "translation_collapse" if m < FLOOR else "ok")})
        print(f"  {rel[:88]:90} elong={('None' if m is None else f'{m:.4f}'):>10}  {rows[-1]['verdict']}",
              flush=True)

    counts = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    print("\n=== SCAN COMPLETE ===")
    print(f"generation dirs read : {len(rows)}")
    for k in sorted(counts):
        print(f"  {k:22} {counts[k]}")
    collapsed = [r for r in rows if r["verdict"] == "translation_collapse"]
    if collapsed:
        print("\nbelow the 1.0 aa/s floor (worst first):")
        for r in sorted(collapsed, key=lambda x: x["elongation_mean"])[:40]:
            print(f"  {r['elongation_mean']:9.5f}  {r['path']}")
    with open("/wcEcoli/out/qc_via_1_scan.json", "w") as fh:
        json.dump({"floor_aa_per_s": FLOOR, "n_read": len(rows), "counts": counts, "rows": rows},
                  fh, indent=1)
    print("\nwrote /wcEcoli/out/qc_via_1_scan.json")


if __name__ == "__main__":
    main()
