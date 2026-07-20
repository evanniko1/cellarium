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


def _worker_cmd(mode: str, args: list[str]) -> list[str]:
    # mount the worker's dir (single-file binds are unreliable on Docker Desktop Windows) read-only
    return ["docker", "run", "--rm", "-v", f"{OUT_ROOT}:/wcEcoli/out",
            "-v", f"{_WORKER.parent}:/cellarium_reader:ro",
            "-e", "PYTHONPATH=/wcEcoli", "-w", "/wcEcoli", WCECOLI_DOCKER,
            "python", f"/cellarium_reader/{_WORKER.name}", mode, *args]


def _run_cmd(cmd: list[str], cwd: str | None) -> dict:
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    for line in reversed(proc.stdout.splitlines()):
        if line.startswith("CELLARIUM_JSON:"):
            return json.loads(line[len("CELLARIUM_JSON:"):])
    return {"error": "reader worker produced no JSON", "returncode": proc.returncode,
            "stderr": (proc.stderr or "")[-600:]}


def _invoke(mode: str, host_run_root: Path, extra: list[str] | None = None) -> dict:
    extra = extra or []
    if WCECOLI_DOCKER:
        return _run_cmd(_worker_cmd(mode, [_container_path(host_run_root), *extra]), None)
    return _run_cmd([PY, str(_WORKER), mode, str(Path(host_run_root).resolve()), *extra], WCECOLI_DIR or None)


def read_run(host_run_root: Path) -> dict:
    return _invoke("run", host_run_root)


def viability(host_run_root: Path) -> dict:
    """Re-score a run by VIABILITY (does the lineage divide?) — the KO readout that doesn't reroute away like a
    graded growth channel. Aggregates the per-cell division signal (full_chromosome==2 + FBA-solver health) over
    seeds x generations into a run-level verdict (viable / impaired / inviable)."""
    return _invoke("viability", host_run_root)


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


def gene_scope(sim_path: str = "cellarium") -> dict:
    """Per-gene mechanistic classification (is_metabolic / is_tf) + KO index from sim_data. Heavy; cache it."""
    return _invoke("gene_scope", OUT_ROOT / sim_path)


def fba_essentiality(genes: list[str], sim_path: str = "cellarium") -> dict:
    """DEPRECATED — under-sensitive (0/35 essential); NOT an essentiality oracle. The homeostatic FBA objective has
    no growth term, so it reroutes around every single-deletion. For an essentiality verdict use the ground-truth
    `essential_reference` flag in gene_scope (Baba/Joyce); for a measurable in-silico effect use a graded-capacity
    perturbation. Kept for the D4 finding; returns {"deprecated": True, "warning": ...}."""
    return _invoke("fba_essentiality", OUT_ROOT / sim_path, [",".join(genes)])


def reroute_diagnosis(gene: str, ko_roots: list[Path], wt_roots: list[Path]) -> dict:
    """Diagnose a viable metabolic KO: is its 'reroute' a mathematical artifact (enzyme FBA flux = 0 in the KO yet
    nonzero in WT, on a viable cell)? Seed-averaged over the gene's own reactions, computed in the container."""
    if WCECOLI_DOCKER:
        k = ",".join(_container_path(Path(r)) for r in ko_roots)
        w = ",".join(_container_path(Path(r)) for r in wt_roots)
        return _run_cmd(_worker_cmd("reroute_diagnosis", [gene, k, w]), None)
    k = ",".join(str(Path(r).resolve()) for r in ko_roots)
    w = ",".join(str(Path(r).resolve()) for r in wt_roots)
    return _run_cmd([PY, str(_WORKER), "reroute_diagnosis", gene, k, w], WCECOLI_DIR or None)


def differential(target_roots: list[Path], ref_roots: list[Path], kind: str = "protein",
                 top: int = 12, floor: float = 20.0) -> dict:
    """Seed-aware per-species fold-change: ALL target runs vs ALL reference runs (count-floored, reproducibility
    reported), computed in the container."""
    if WCECOLI_DOCKER:
        t = ",".join(_container_path(Path(r)) for r in target_roots)
        r = ",".join(_container_path(Path(r)) for r in ref_roots)
        return _run_cmd(_worker_cmd("differential", [t, r, kind, str(top), str(floor)]), None)
    t = ",".join(str(Path(r).resolve()) for r in target_roots)
    r = ",".join(str(Path(r).resolve()) for r in ref_roots)
    return _run_cmd([PY, str(_WORKER), "differential", t, r, kind, str(top), str(floor)], WCECOLI_DIR or None)


def gene_lfc(target_roots: list[Path], ref_roots: list[Path], kind: str = "mrna", floor: float = 20.0) -> dict:
    """All-gene seed-mean log2fc (SCI-2c): the FULL-distribution reader (every gene, not just the significant
    movers) for the sim-vs-RNA-seq concordance, computed in the container. Mirrors differential()."""
    if WCECOLI_DOCKER:
        t = ",".join(_container_path(Path(r)) for r in target_roots)
        r = ",".join(_container_path(Path(r)) for r in ref_roots)
        return _run_cmd(_worker_cmd("gene_lfc", [t, r, kind, str(floor)]), None)
    t = ",".join(str(Path(r).resolve()) for r in target_roots)
    r = ",".join(str(Path(r).resolve()) for r in ref_roots)
    return _run_cmd([PY, str(_WORKER), "gene_lfc", t, r, kind, str(floor)], WCECOLI_DIR or None)


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
