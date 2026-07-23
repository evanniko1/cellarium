"""System-resource awareness — so Cellwright can proactively WARN the user before a sweep would exhaust RAM or disk.

Running wcEcoli sims is heavy: each run is ~1 GB of raw output on disk and ~1-2 GB RAM, and a parallel campaign
multiplies both. This module gives the agent two grounded tools — `system_resources` (what's free right now) and
`estimate_sim_resources` (what a proposed sweep would COST, vs what's free, with a safe chunk/parallel recommendation)
— so instead of launching something that fills the disk or thrashes RAM, the agent can say "this needs ~X GB but you
have ~Y free; run it in chunks of N at parallel=M". Read-only; no dependency required (psutil is used if present).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

_RAM_HEADROOM_GB = 2.0     # keep this much RAM free beyond the sweep's need
_DISK_HEADROOM_GB = 10.0   # keep this much disk free beyond the sweep's raw output
_PER_SIM_RAM_GB = 2.0      # conservative per-parallel-worker RAM for a wcEcoli sim
_FALLBACK_RUN_GB = 1.1     # per-run raw-output disk if the corpus can't be measured (observed ~1.06 GB/run)


def _ram_gb() -> tuple[float | None, float | None]:
    """(total_gb, free_gb) best-effort with NO hard dependency: psutil if installed, else ctypes (Windows) /
    /proc/meminfo (Linux). (None, None) if it can't be read — callers must treat unknown RAM as 'do not block on it'."""
    try:
        import psutil
        vm = psutil.virtual_memory()
        return round(vm.total / 1e9, 1), round(vm.available / 1e9, 1)
    except Exception:
        pass
    try:
        if sys.platform.startswith("win"):
            import ctypes

            class _MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            ms = _MS()
            ms.dwLength = ctypes.sizeof(_MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))   # type: ignore[attr-defined]
            return round(ms.ullTotalPhys / 1e9, 1), round(ms.ullAvailPhys / 1e9, 1)
        with open("/proc/meminfo") as f:
            info = {k.strip(): v for k, _, v in (ln.partition(":") for ln in f)}
        tot = int(info["MemTotal"].split()[0]) * 1024
        free = int(info.get("MemAvailable", info.get("MemFree", "0 kB")).split()[0]) * 1024
        return round(tot / 1e9, 1), round(free / 1e9, 1)
    except Exception:
        return None, None


def _docker_running() -> bool:
    """Is the Docker daemon up? A short, non-blocking probe — a sweep needs it, so this is a hard gate."""
    try:
        r = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"],
                           capture_output=True, text=True, timeout=6)
        return r.returncode == 0 and bool(r.stdout.strip())
    except Exception:
        return False


def _out_root() -> Path:
    root = Path(os.environ.get("CELLARIUM_OUT", "runs"))
    return root if root.exists() else Path(".")


def _corpus_footprint() -> dict:
    """The corpus's disk footprint + the average raw GB per run, so the per-run disk estimate is GROUNDED in reality
    rather than a guess. Uses the manifest run count + a bounded directory scan (skipped if it would be too slow)."""
    try:
        from . import store
        n_runs = len(store.list_results())
    except Exception:
        n_runs = 0
    root = Path(os.environ.get("CELLARIUM_OUT", "runs"))
    gb = None
    if root.exists():
        try:
            total = 0
            for i, p in enumerate(root.rglob("*")):
                if p.is_file():
                    total += p.stat().st_size
                if i > 400_000:            # bound the scan on a huge corpus — the estimate needn't be exact
                    total = None
                    break
            gb = round(total / 1e9, 1) if total is not None else None
        except Exception:
            gb = None
    avg = round(gb / n_runs, 2) if (gb and n_runs) else _FALLBACK_RUN_GB
    return {"runs": n_runs, "raw_gb": gb, "avg_gb_per_run": avg}


def system_resources() -> dict:
    """What's FREE right now: RAM, disk (on the sim output drive), CPU, whether Docker is up, and the corpus footprint.
    Read-only. Call before proposing/queuing a heavy sweep so the agent can warn instead of exhausting the machine."""
    total_gb, free_gb = _ram_gb()
    du = shutil.disk_usage(_out_root())
    corpus = _corpus_footprint()
    return {
        "ram_total_gb": total_gb, "ram_free_gb": free_gb,
        "disk_free_gb": round(du.free / 1e9, 1), "disk_total_gb": round(du.total / 1e9, 1),
        "cpu_logical": os.cpu_count(), "docker_running": _docker_running(),
        "corpus": corpus,
        "note": ("Free RAM/disk right now + the corpus footprint. A wcEcoli run is ~1 GB raw on disk and ~1-2 GB RAM; "
                 "a parallel campaign multiplies both. Use estimate_sim_resources before launching a sweep."),
    }


def estimate_sim_resources(n_runs: int = 1, parallel: int = 1, generations: int = 4,
                           per_sim_ram_gb: float = _PER_SIM_RAM_GB, res: dict | None = None) -> dict:
    """Would this sweep FIT? Estimates the RAM (parallel × per-sim) and disk (n_runs × avg-run-GB, scaled by
    generations) it needs vs what's free, and returns a verdict + a SAFE `recommended_parallel` / `recommended_chunk_runs`
    so a memory- or disk-tight machine runs it in chunks instead of exhausting itself. verdict: 'block' (Docker down),
    'warn' (won't fit within headroom), or 'ok'."""
    res = res or system_resources()
    n_runs = max(1, int(n_runs))
    parallel = max(1, int(parallel))
    avg_run_gb = (res.get("corpus") or {}).get("avg_gb_per_run") or _FALLBACK_RUN_GB
    gen_scale = (generations / 4.0) if generations else 1.0
    disk_needed = round(n_runs * avg_run_gb * max(0.25, gen_scale), 1)
    ram_needed = round(parallel * per_sim_ram_gb, 1)
    free_ram, free_disk = res.get("ram_free_gb"), res.get("disk_free_gb")
    cpu = res.get("cpu_logical") or 4

    warnings: list[str] = []
    if not res.get("docker_running"):
        warnings.append("Docker daemon is NOT running — start Docker Desktop before launching any sim.")
    ram_ok = free_ram is None or ram_needed <= max(0.0, free_ram - _RAM_HEADROOM_GB)
    disk_ok = free_disk is None or disk_needed <= max(0.0, free_disk - _DISK_HEADROOM_GB)
    if free_ram is not None and not ram_ok:
        warnings.append(f"~{ram_needed} GB RAM needed at parallel={parallel}, but only ~{free_ram} GB free "
                        f"(keep {_RAM_HEADROOM_GB} GB headroom) — lower parallel.")
    if free_disk is not None and not disk_ok:
        warnings.append(f"~{disk_needed} GB raw output, but only ~{free_disk} GB disk free "
                        f"(keep {_DISK_HEADROOM_GB} GB headroom) — run fewer/chunk, or prune the corpus first.")

    rec_parallel = parallel
    if free_ram is not None:
        by_ram = int(max(0.0, free_ram - _RAM_HEADROOM_GB) // per_sim_ram_gb)
        rec_parallel = max(1, min(parallel, by_ram or 1, max(1, cpu - 2)))
    rec_chunk = n_runs
    if free_disk is not None and not disk_ok and avg_run_gb > 0:
        rec_chunk = max(1, int(max(0.0, free_disk - _DISK_HEADROOM_GB) // (avg_run_gb * max(0.25, gen_scale))))

    verdict = "block" if not res.get("docker_running") else ("warn" if warnings else "ok")
    return {
        "verdict": verdict, "warnings": warnings,
        "requested": {"n_runs": n_runs, "parallel": parallel, "generations": generations},
        "estimated_ram_gb": ram_needed, "estimated_disk_gb": disk_needed,
        "free_ram_gb": free_ram, "free_disk_gb": free_disk, "docker_running": res.get("docker_running"),
        "recommended_parallel": rec_parallel, "recommended_chunk_runs": rec_chunk,
        "recommended": (f"run in {(-(-n_runs // rec_chunk))} chunk(s) of <= {rec_chunk} runs at parallel={rec_parallel}"
                        if (rec_chunk < n_runs or rec_parallel < parallel) else
                        f"fits as one batch at parallel={rec_parallel}"),
        "note": ("Grounded in the corpus's real ~GB/run and the machine's free RAM/disk. TELL THE USER the warning "
                 "before queuing — a sweep that fills the disk or thrashes RAM is worse than a slower chunked run."),
    }
