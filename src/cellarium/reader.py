"""Host-side bridge to the container reader worker.

The model + TableReader live only in the wcEcoli image, so simOut reading runs there (see
`_reader_worker.py`) and we consume its JSON here. Docker mode bind-mounts the output dir + the worker
script into the image; native mode runs the worker directly (requires `wholecell` importable).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

WCECOLI_DIR = os.environ.get("WCECOLI_DIR", "")
WCECOLI_DOCKER = os.environ.get("WCECOLI_DOCKER", "")
PY = os.environ.get("WCECOLI_PY", "python")
OUT_ROOT = Path(os.environ.get("CELLARIUM_OUT", "runs")).resolve()
_WORKER = Path(__file__).with_name("_reader_worker.py")


def _container_path(host_run_root: Path) -> str:
    rel = Path(host_run_root).resolve().relative_to(OUT_ROOT)
    return "/wcEcoli/out/" + ("" if str(rel) == "." else str(rel).replace("\\", "/"))


def _invoke(mode: str, host_run_root: Path, extra: list[str] | None = None) -> dict:
    extra = extra or []
    if WCECOLI_DOCKER:
        # mount the worker's dir (single-file binds are unreliable on Docker Desktop Windows) read-only
        cmd = ["docker", "run", "--rm", "-v", f"{OUT_ROOT}:/wcEcoli/out",
               "-v", f"{_WORKER.parent}:/cellarium_reader:ro",
               "-e", "PYTHONPATH=/wcEcoli", "-w", "/wcEcoli", WCECOLI_DOCKER,
               "python", f"/cellarium_reader/{_WORKER.name}", mode, _container_path(host_run_root), *extra]
        cwd = None
    else:
        cmd = [PY, str(_WORKER), mode, str(Path(host_run_root).resolve()), *extra]
        cwd = WCECOLI_DIR or None
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    for line in reversed(proc.stdout.splitlines()):
        if line.startswith("CELLARIUM_JSON:"):
            return json.loads(line[len("CELLARIUM_JSON:"):])
    return {"error": "reader worker produced no JSON", "returncode": proc.returncode,
            "stderr": (proc.stderr or "")[-600:]}


def read_run(host_run_root: Path) -> dict:
    return _invoke("run", host_run_root)


def dump_schema(host_run_root: Path) -> dict:
    return _invoke("schema", host_run_root)


def read_species(host_run_root: Path, kind: str, species_id: str) -> dict:
    return _invoke("species", host_run_root, [kind, species_id])


def list_species(host_run_root: Path, kind: str, search: str = "") -> dict:
    return _invoke("list_species", host_run_root, [kind, search])


VARIANT_MAP_CACHE = Path("data/cache/variant_map.json")


def variant_map(sim_path: str = "cellarium") -> dict:
    """Gene-KO + condition index maps from sim_data (indices match the model's ordering). Heavy; cache it."""
    return _invoke("variant_map", OUT_ROOT / sim_path)


def gene_map(sim_path: str = "cellarium") -> dict:
    """{symbol: monomer_id} from sim_data — for resolving the curated pathway panel. Heavy; cache it."""
    return _invoke("gene_map", OUT_ROOT / sim_path)


def differential(design_root: Path, ref_root: Path, kind: str = "protein", top: int = 12) -> dict:
    """Per-species fold-change between two runs (design vs reference), computed in the container."""
    return _invoke("differential", design_root, [_container_path(ref_root), kind, str(top)])


if __name__ == "__main__":  # schema dump (default) or `--variant-map` to derive + cache the KO/condition map
    import argparse

    ap = argparse.ArgumentParser(description="Inspect the model via the container reader.")
    ap.add_argument("--variant-map", action="store_true", help="dump + cache gene-KO/condition index maps")
    args = ap.parse_args()
    if args.variant_map:
        m = variant_map()
        if "error" not in m:
            VARIANT_MAP_CACHE.parent.mkdir(parents=True, exist_ok=True)
            VARIANT_MAP_CACHE.write_text(json.dumps(m), encoding="utf-8")
        preview = {k: (f"[{len(v)} genes -> cached]" if k == "genes" else v) for k, v in m.items()}
        print(json.dumps(preview, indent=2))
    else:
        print(json.dumps(dump_schema(OUT_ROOT), indent=2))
