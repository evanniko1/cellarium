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

_RAM_HEADROOM_GB = 2.0       # keep this much RAM free beyond the sweep's need
_DISK_HEADROOM_GB = 10.0     # keep this much disk free beyond the sweep's raw output
_PER_SIM_RAM_GB = 2.0        # conservative per-parallel-worker RAM for a wcEcoli sim
_FALLBACK_RUN_GB = 1.1       # per-run raw-output disk if the corpus can't be measured (observed ~1.06 GB/run)
_DAEMON_OVERHEAD_GB = 1.5    # RAM the Docker VM daemon itself holds — subtract from the VM cap before sizing workers
_PER_RUN_MIN_PER_GEN = 8.0   # rough wall-clock minutes per run per generation (for the time-budget estimate)
_WALL_WARN_HOURS = 10.0      # warn (don't block) past this — 'too big to sit through' becomes 'chunk + queue overnight'


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


def _docker_info() -> dict:
    """Docker daemon status + the VM's ACTUAL resource ceiling in ONE probe. CRITICAL on Windows/Mac: the sim runs
    INSIDE the Docker Desktop WSL2/HyperV Linux VM, whose RAM/CPU are capped WELL BELOW the host (default ~50% RAM) —
    so sizing workers against host free RAM silently over-schedules into an OOM the host never sees. `docker info`
    reports the VM's MemTotal/NCPU (on native Linux these equal the host, so it stays correct there too)."""
    try:
        r = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}|{{.MemTotal}}|{{.NCPU}}|{{.DockerRootDir}}"],
            capture_output=True, text=True, timeout=6)
        if r.returncode != 0 or not r.stdout.strip():
            return {"running": False}
        ver, mem, ncpu, root = (r.stdout.strip().split("|") + ["", "", "", ""])[:4]
        return {"running": bool(ver.strip()),
                "vm_mem_gb": (round(int(mem) / 1e9, 1) if mem.strip().isdigit() else None),
                "vm_cpu": (int(ncpu) if ncpu.strip().isdigit() else None),
                "data_root": (root.strip() or None)}
    except Exception:
        return {"running": False}


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


def _tightest_disk_free_gb() -> tuple[float, str]:
    """Free GB on the TIGHTEST relevant volume — not just the output drive. Container image layers, the writable
    layer, and (on Win/Mac) the WSL2 ext4.vhdx live on the SYSTEM/temp drive (usually C:), a DIFFERENT volume than a
    big corpus on D: — a sweep can pass on the output drive yet wedge the daemon by filling C:. Report the smaller."""
    import tempfile
    best_gb, where = None, ""
    for label, p in (("output", _out_root()), ("system/temp", Path(tempfile.gettempdir()))):
        try:
            g = shutil.disk_usage(p).free / 1e9
        except Exception:
            continue
        if best_gb is None or g < best_gb:
            best_gb, where = g, label
    return (round(best_gb, 1) if best_gb is not None else 0.0), where


def system_resources() -> dict:
    """What's FREE right now: RAM (host + the Docker VM ceiling), disk (the tightest relevant volume), CPU, Docker
    status, and the corpus footprint. Read-only. Call before proposing/queuing a heavy sweep so the agent can warn
    instead of exhausting the machine."""
    total_gb, free_gb = _ram_gb()
    docker = _docker_info()
    disk_free, disk_where = _tightest_disk_free_gb()
    # EFFECTIVE free RAM for a container = min(host free, VM cap - daemon overhead). On native Linux vm_mem == host,
    # so this is a no-op; on Win/Mac it corrects the silent-OOM bug (host says 20 GB free, the VM is capped at 8).
    vm_mem = docker.get("vm_mem_gb")
    eff_free = free_gb
    if free_gb is not None and vm_mem:
        eff_free = round(min(free_gb, max(0.0, vm_mem - _DAEMON_OVERHEAD_GB)), 1)
    return {
        "ram_total_gb": total_gb, "ram_free_gb": free_gb,
        "docker_vm_mem_gb": vm_mem, "docker_vm_cpu": docker.get("vm_cpu"),
        "effective_ram_free_gb": eff_free,   # what a container can ACTUALLY get — size workers against THIS
        "disk_free_gb": disk_free, "disk_free_volume": disk_where,
        "cpu_logical": os.cpu_count(), "docker_running": docker.get("running", False),
        "corpus": _corpus_footprint(),
        "note": ("effective_ram_free_gb is the container-visible RAM (host free capped by the Docker VM) — the number "
                 "to size parallelism against; ram_free_gb alone over-schedules on Win/Mac. disk_free_gb is the "
                 "TIGHTEST volume (output vs the system drive where the Docker vhdx lives). Use estimate_sim_resources."),
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
    # size RAM against the CONTAINER-visible free RAM (VM-capped), not host free — the Docker-VM-ceiling fix.
    free_ram = res.get("effective_ram_free_gb", res.get("ram_free_gb"))
    free_disk = res.get("disk_free_gb")
    cpu = res.get("docker_vm_cpu") or res.get("cpu_logical") or 4   # the VM's CPU cap when known

    warnings: list[str] = []
    if not res.get("docker_running"):
        warnings.append("Docker daemon is NOT running — start Docker Desktop before launching any sim.")
    ram_ok = free_ram is None or ram_needed <= max(0.0, free_ram - _RAM_HEADROOM_GB)
    disk_ok = free_disk is None or disk_needed <= max(0.0, free_disk - _DISK_HEADROOM_GB)
    if free_ram is not None and not ram_ok:
        vm = res.get("docker_vm_mem_gb")
        cap = f" (Docker VM capped at ~{vm} GB)" if vm else ""
        warnings.append(f"~{ram_needed} GB RAM needed at parallel={parallel}, but only ~{free_ram} GB is "
                        f"container-visible{cap} — lower parallel" + (", or raise the Docker VM memory to fit."
                        if vm else "."))
    if free_disk is not None and not disk_ok:
        warnings.append(f"~{disk_needed} GB raw output, but only ~{free_disk} GB free disk on the "
                        f"{res.get('disk_free_volume', 'output')} volume (keep {_DISK_HEADROOM_GB} GB headroom) — "
                        f"run fewer/chunk, or prune the corpus first.")

    rec_parallel = parallel
    if free_ram is not None:
        by_ram = int(max(0.0, free_ram - _RAM_HEADROOM_GB) // per_sim_ram_gb)
        rec_parallel = max(1, min(parallel, by_ram or 1, max(1, cpu - 1)))
    rec_chunk = n_runs
    if free_disk is not None and not disk_ok and avg_run_gb > 0:
        rec_chunk = max(1, int(max(0.0, free_disk - _DISK_HEADROOM_GB) // (avg_run_gb * max(0.25, gen_scale))))

    # wall-clock budget: 'too big to sit through' -> 'chunk and queue overnight' (a WARN, not a block).
    est_hours = round((-(-n_runs // max(1, rec_parallel))) * _PER_RUN_MIN_PER_GEN * max(1, generations) / 60.0, 1)
    if est_hours > _WALL_WARN_HOURS:
        warnings.append(f"~{est_hours} h wall-clock at parallel={rec_parallel} — chunk it and resume across sessions "
                        f"(don't sit on a multi-hour run; check between chunks).")

    verdict = "block" if not res.get("docker_running") else ("warn" if warnings else "ok")
    return {
        "verdict": verdict, "warnings": warnings,
        "requested": {"n_runs": n_runs, "parallel": parallel, "generations": generations},
        "estimated_ram_gb": ram_needed, "estimated_disk_gb": disk_needed, "estimated_wall_hours": est_hours,
        "free_ram_gb": free_ram, "free_disk_gb": free_disk, "docker_running": res.get("docker_running"),
        "docker_vm_mem_gb": res.get("docker_vm_mem_gb"),
        "recommended_parallel": rec_parallel, "recommended_chunk_runs": rec_chunk,
        "recommended": (f"run in {(-(-n_runs // rec_chunk))} chunk(s) of <= {rec_chunk} runs at parallel={rec_parallel}"
                        if (rec_chunk < n_runs or rec_parallel < parallel) else
                        f"fits as one batch at parallel={rec_parallel}"),
        "note": ("RAM is sized against the CONTAINER-visible ceiling (host free capped by the Docker VM), disk against "
                 "the tightest volume, plus a wall-clock estimate. TELL THE USER any warning with the one-line remedy "
                 "(reduce parallel / free disk / raise the VM memory) before queuing — chunked+slow beats OOM/full-disk. "
                 "Re-check between chunks: free disk shrinks ~1 GB/run as the corpus grows."),
    }
