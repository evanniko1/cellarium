"""System-resource awareness — the tools Cellwright uses to WARN the user before a sweep exhausts RAM/disk.
The verdict + chunk logic is pure and mocked here (no real machine probing); wiring is checked against the registry."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cellarium import resources as R  # noqa: E402

_RES = {"ram_total_gb": 32.0, "ram_free_gb": 11.6, "disk_free_gb": 118.0, "disk_total_gb": 930.0,
        "cpu_logical": 16, "docker_running": True, "corpus": {"runs": 265, "raw_gb": 300.0, "avg_gb_per_run": 1.14}}


def test_estimate_ok_when_it_fits():
    est = R.estimate_sim_resources(n_runs=4, parallel=2, generations=4, res=dict(_RES))
    assert est["verdict"] == "ok" and est["warnings"] == []
    assert est["estimated_ram_gb"] == 4.0 and est["recommended_parallel"] == 2


def test_estimate_warns_and_recommends_lower_parallel_when_ram_tight():
    est = R.estimate_sim_resources(n_runs=24, parallel=6, generations=4, res=dict(_RES))
    assert est["verdict"] == "warn"
    assert any("RAM" in w for w in est["warnings"])                 # 6×2=12 GB > 11.6-2 headroom
    assert est["recommended_parallel"] < 6                          # backs off to what fits


def test_estimate_warns_and_chunks_when_disk_tight():
    tight = dict(_RES); tight["disk_free_gb"] = 20.0                # only 20 GB free
    est = R.estimate_sim_resources(n_runs=40, parallel=2, generations=4, res=tight)
    assert est["verdict"] == "warn" and any("disk" in w for w in est["warnings"])
    assert est["recommended_chunk_runs"] < 40 and "chunk" in est["recommended"]   # ~ (20-10)/1.14 ≈ 8 per chunk


def test_estimate_blocks_when_docker_down():
    down = dict(_RES); down["docker_running"] = False
    est = R.estimate_sim_resources(n_runs=4, parallel=2, res=down)
    assert est["verdict"] == "block" and any("Docker" in w for w in est["warnings"])


def test_estimate_does_not_block_on_unknown_ram():
    unknown = dict(_RES); unknown["ram_free_gb"] = None            # RAM couldn't be read -> don't gate on it
    est = R.estimate_sim_resources(n_runs=4, parallel=8, res=unknown)
    assert est["verdict"] == "ok" and not any("RAM" in w for w in est["warnings"])


def test_generations_scale_the_disk_estimate():
    a = R.estimate_sim_resources(n_runs=10, parallel=1, generations=4, res=dict(_RES))["estimated_disk_gb"]
    b = R.estimate_sim_resources(n_runs=10, parallel=1, generations=8, res=dict(_RES))["estimated_disk_gb"]
    assert b > a                                                    # more generations -> more raw output


def test_resource_tools_wired_and_classified():
    from cellarium import test_registry, tools
    for name in ("system_resources", "estimate_sim_resources"):
        assert name in tools._DISPATCH and any(t["name"] == name for t in tools.TOOLS)
    assert test_registry.unclassified_tools({t["name"] for t in tools.TOOLS}) == []   # reverse invariant holds


def test_effective_ram_is_capped_by_the_docker_vm(monkeypatch):
    """The lit-review bug: host free RAM over-schedules on Win/Mac because the sim runs in the Docker VM (capped well
    below host). system_resources must report the container-visible ceiling, and estimate must size against it."""
    monkeypatch.setattr(R, "_ram_gb", lambda: (32.0, 20.0))            # host says 20 GB free...
    monkeypatch.setattr(R, "_docker_info",
                        lambda: {"running": True, "vm_mem_gb": 8.0, "vm_cpu": 4, "data_root": "/var/lib/docker"})
    monkeypatch.setattr(R, "_tightest_disk_free_gb", lambda: (100.0, "output"))
    monkeypatch.setattr(R, "_corpus_footprint", lambda: {"runs": 10, "raw_gb": 11.0, "avg_gb_per_run": 1.1})
    sr = R.system_resources()
    assert sr["effective_ram_free_gb"] == 6.5                          # ...but min(20, 8-1.5) = 6.5 is what a container gets
    assert sr["docker_vm_mem_gb"] == 8.0 and sr["docker_vm_cpu"] == 4
    est = R.estimate_sim_resources(n_runs=6, parallel=6, res=sr)       # would have looked fine vs host 20 GB
    assert est["verdict"] == "warn" and any("VM" in w for w in est["warnings"])   # now correctly warns vs the VM cap
    assert est["recommended_parallel"] < 6


def test_wall_clock_warns_on_a_multi_day_sweep():
    res = {"docker_running": True, "effective_ram_free_gb": 12.0, "disk_free_gb": 500.0, "cpu_logical": 16,
           "docker_vm_cpu": 8, "corpus": {"avg_gb_per_run": 1.1}}
    est = R.estimate_sim_resources(n_runs=200, parallel=4, generations=8, res=res)
    assert est["estimated_wall_hours"] > 10 and any("wall-clock" in w for w in est["warnings"])
