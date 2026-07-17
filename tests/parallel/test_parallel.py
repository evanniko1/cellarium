"""Integration test: cellarium dispatches whole-cell sims IN PARALLEL, each in its OWN docker container.

Exercises the SHIPPED path — cellarium.manifest.campaign(parallel=N) -> runner.run_one -> runner._exec ->
`docker run --rm ... wcecoli-standin python runscripts/manual/runSim.py ...`. The wcEcoli model is swapped
for a lightweight stand-in image that honors the identical invocation contract but just sleeps + writes a
simOut-shaped dir, so container concurrency is fast and directly observable. The post-sim `reader` stage
(its own container) is NOT under test, so reader.read_run is stubbed.

Hermetic: sim output AND the manifest shard are redirected to a tmp dir, so the test never touches the real
runs/ or data/manifest/. OPT-IN (it's a ~40s Docker integration test, so it stays out of the default suite):
    docker build -t wcecoli-standin tests/parallel/standin
    CELLARIUM_DOCKER_TESTS=1 pytest tests/parallel/test_parallel.py

(Salvaged from the fix-anthropic-rate-limit-handling branch and adapted to main: main now RECORDS a crashed
sim as a first-class row (§M) rather than silently dropping it, so the crash-isolation assertion checks that
the batch survives AND the crash is captured — not that the row count drops.)
"""

import os
import shutil
import subprocess
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

IMAGE = "wcecoli-standin"


def _image_present() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "image", "inspect", IMAGE],
                              capture_output=True, timeout=20).returncode == 0
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not (os.environ.get("CELLARIUM_DOCKER_TESTS") == "1" and _image_present()),
    reason=f"opt-in: set CELLARIUM_DOCKER_TESTS=1 and build the image (docker build -t {IMAGE} tests/parallel/standin)")


class _Watcher:
    """Poll `docker ps` for our stand-in containers to measure real container concurrency."""

    def __init__(self, image):
        self.image = image
        self.samples = []
        self.ids = set()
        self._stop = False

    def _poll(self):
        while not self._stop:
            try:
                out = subprocess.run(
                    ["docker", "ps", "--filter", f"ancestor={self.image}", "--format", "{{.ID}}"],
                    capture_output=True, text=True, timeout=5).stdout.split()
            except Exception:
                out = []
            self.samples.append(len(out))
            self.ids.update(out)
            time.sleep(0.3)

    def __enter__(self):
        self._t = threading.Thread(target=self._poll, daemon=True)
        self._t.start()
        return self

    def __exit__(self, *a):
        self._stop = True
        self._t.join(timeout=2)

    @property
    def max_concurrent(self):
        return max(self.samples, default=0)


def _shard_rows(shard):
    import pyarrow.parquet as pq
    return pq.read_table(shard).to_pylist()


def test_parallel_container_isolation(tmp_path, monkeypatch):
    import cellarium.manifest as manifest
    import cellarium.reader as reader
    import cellarium.runner as runner
    from cellarium.model import Design

    # hermetic: dispatch to the stand-in image; sims + shard land under tmp; reader stage (own container) stubbed
    out = tmp_path / "runs"
    out.mkdir()
    monkeypatch.setattr(runner, "WCECOLI_DOCKER", IMAGE)
    monkeypatch.setattr(runner, "OUT_ROOT", out)
    monkeypatch.setattr(manifest, "MANIFEST_DIR", tmp_path / "manifest")
    monkeypatch.setattr(reader, "read_run", lambda root: {
        "generations": [{"index": 0, "divided": True, "growth_mean": 0.35, "ppgpp_mean": 42.0}],
        "channels": {"growth_rate": 0.35}, "channel_stats": {}, "series": {}, "media_segments": []})

    wt = Design(perturbation="wildtype", condition="basal")

    def run(seeds, parallel):
        with _Watcher(IMAGE) as w:
            t0 = time.time()
            shard = manifest.campaign([wt], seeds, generations=1, parallel=parallel)
            dt = time.time() - t0
        return dt, w, shard

    par_dt, par_w, _ = run([0, 1, 2, 3], 4)
    seq_dt, seq_w, _ = run([0, 1, 2, 3], 1)

    # concurrency: 4 sims ran at once, each in its own container; sequential ran one at a time
    assert par_w.max_concurrent == 4, f"expected 4 concurrent containers, saw {par_w.max_concurrent}"
    assert len(par_w.ids) >= 4, f"expected >=4 distinct containers, saw {len(par_w.ids)}"
    assert seq_w.max_concurrent == 1, f"sequential should run 1 at a time, saw {seq_w.max_concurrent}"
    assert par_dt < seq_dt, f"parallel ({par_dt:.1f}s) should beat sequential ({seq_dt:.1f}s)"

    # isolation: 4 distinct simOut dirs on the host, no clobbering
    dirs = sorted({p.parents[2] for p in (out / "cellarium").glob("**/simOut")})
    assert len(dirs) == 4, f"expected 4 isolated output dirs, saw {len(dirs)}"

    # crash isolation: seed 4242 exits non-zero in-container; the batch SURVIVES and the crash is RECORDED (§M)
    _, _, cr_shard = run([10, 11, 4242, 13], 4)
    rows = _shard_rows(cr_shard)
    assert len(rows) == 4, f"batch should record all 4 seeds (3 ok + 1 crash), saw {len(rows)}"
    crashed = [r for r in rows if r.get("crashed")]
    assert len(crashed) == 1, f"exactly the failing seed should be marked crashed, saw {len(crashed)}"
    assert crashed[0]["seed"] == 4242


if __name__ == "__main__":  # standalone run — mirrors the original harness
    sys.exit(pytest.main([__file__, "-v", "-s"]))
