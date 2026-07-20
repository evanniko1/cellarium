"""REAL test: 8 actual wcEcoli whole-cell simulations in parallel, each in its own docker container.

No stubs. Real image (wcecoli-sim), real ParCa sim_data, real runSim, real container reader + QC.
A background thread samples `docker ps` to prove 8 sim containers are alive simultaneously.
"""
import json
import subprocess
import threading
import time
from pathlib import Path

import cellarium.manifest as manifest
from cellarium.model import Design

IMAGE = "wcecoli-sim"
N = 8

class Watcher:
    def __init__(self, image):
        self.image = image; self.samples = []; self.ids = set(); self._stop = False
    def _poll(self):
        while not self._stop:
            try:
                out = subprocess.run(
                    ["docker", "ps", "--filter", f"ancestor={self.image}", "--format", "{{.ID}}"],
                    capture_output=True, text=True, timeout=5).stdout.split()
            except Exception:
                out = []
            self.samples.append((time.time(), len(out)))
            self.ids.update(out)
            time.sleep(1.0)
    def __enter__(self):
        self._t = threading.Thread(target=self._poll, daemon=True); self._t.start(); return self
    def __exit__(self, *a):
        self._stop = True; self._t.join(timeout=3)
    @property
    def max_concurrent(self):
        return max((n for _, n in self.samples), default=0)

def main():
    wt = Design(perturbation="wildtype", condition="basal")
    seeds = list(range(N))
    print(f"Launching {N} REAL wildtype sims (1 generation each), parallel={N} ...", flush=True)
    with Watcher(IMAGE) as w:
        t0 = time.time()
        shard = manifest.campaign([wt], seeds, generations=1, parallel=N)
        dt = time.time() - t0

    import pyarrow.parquet as pq
    tbl = pq.read_table(shard)
    rows = tbl.to_pylist()
    # peak concurrency: how many samples hit N, and the sustained peak
    peak = w.max_concurrent
    n_at_peak = sum(1 for _, n in w.samples if n == peak)

    print("\n" + "=" * 70)
    print(f"wall_clock            : {dt/60:.1f} min ({dt:.0f}s)")
    print(f"max concurrent sim containers : {peak}  (sampled {n_at_peak}x at peak)")
    print(f"distinct container IDs        : {len(w.ids)}")
    print(f"completed rows in shard       : {len(rows)} / {N}")
    print(f"shard                         : {shard}")
    print("=" * 70)
    for r in rows:
        print(f"  seed={r['seed']:>2}  qc={r['qc']:<12} reportable={r['reportable']}  "
              f"growth_rate={r.get('growth_rate')}  doubling≈{r.get('doubling_time')}")
    # concurrency trace summary
    trace = [n for _, n in w.samples]
    print(f"\nconcurrency trace (containers alive, 1s samples): {trace}")

    result = {"wall_s": dt, "peak_concurrent": peak, "distinct_ids": len(w.ids),
              "rows": len(rows), "N": N, "shard": str(shard)}
    Path(str(shard) + ".summary.json").write_text(json.dumps(result, indent=2))
    print("\nVERDICT:", "PASS ✅ 8 real sims ran concurrently in 8 containers"
          if peak == N and len(w.ids) >= N and len(rows) == N
          else f"REVIEW — peak={peak}, ids={len(w.ids)}, rows={len(rows)}")

if __name__ == "__main__":
    main()
