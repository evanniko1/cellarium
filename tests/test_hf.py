"""HF-availability tests — the two-alternatives surface (no network). Run: python -m pytest tests/test_hf.py"""

import tarfile

from cellarium import hf, store, tools


def test_download_raw_reports_per_archive_progress(monkeypatch):
    """A confirmed multi-archive pull streams progress (done/total) per archive through the agent's set_progress
    hook, so a multi-GB HF download shows 'downloading 2/5' instead of hanging silently. Network+extract stubbed."""
    import huggingface_hub
    plan = {"design": "x", "repo": hf.HF_REPO, "n_seeds": 3, "n_local": 0, "n_to_pull": 3, "est_gb": 14.0,
            "files": [{"result_id": f"r{i}", "hf_path": f"runs/cellarium/gk_{i}/000000.tar.gz",
                       "local": False, "on_hf": True, "seed": i} for i in range(3)]}
    monkeypatch.setattr(hf, "download_plan", lambda design: plan)
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", lambda repo, path, repo_type=None: "/tmp/x.tar.gz")

    class _FakeTar:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def extractall(self, path, filter=None): pass

    monkeypatch.setattr(tarfile, "open", lambda p, mode="r:gz": _FakeTar())

    events = []
    tools.set_progress(lambda done, total, label: events.append((done, total)))
    try:
        out = tools.download_raw("x", confirm=True)
    finally:
        tools.set_progress(None)

    assert out["downloaded"] == ["r0", "r1", "r2"]
    assert {t for _, t in events} == {3}              # total pinned at the archive count
    assert events[0][0] == 0 and events[-1][0] == 3   # first tick before any done, last after all done
    assert len(events) == 6                            # a pre-download + post-extract tick per archive


def test_hf_rel_maps_run_path_to_portable_archive_path():
    p = hf.OUT_ROOT / "cellarium" / "gene_knockout_001594" / "000000"
    assert hf._hf_rel(str(p)) == "runs/cellarium/gene_knockout_001594/000000.tar.gz"   # the packaged archive
    # PORTABLE: a foreign machine's absolute path still maps -> resolves for cloners / HF, not just this machine
    assert hf._hf_rel("/home/someone/x/runs/cellarium/gene_knockout_000058/000000") == "runs/cellarium/gene_knockout_000058/000000.tar.gz"
    assert hf._hf_rel(None) is None
    assert hf._hf_rel("/some/unrelated/path") is None      # no /cellarium/ segment -> None, never crashes


def test_data_availability_always_surfaces_both_alternatives():
    rows = store.list_results()
    if not rows:                                           # empty corpus -> skip
        return
    out = hf.data_availability(rows[0]["id"])
    alts = out["alternatives"]
    assert set(alts) == {"1_download_from_hf", "2_regenerate_locally"}   # BOTH paths, always
    assert alts["1_download_from_hf"]["repo"] == hf.HF_REPO
    assert "how" in alts["2_regenerate_locally"]           # the regenerate-locally guidance
    assert isinstance(out["raw_local"], bool)


def test_dispatch_routes_data_availability():
    rows = store.list_results()
    if not rows:
        return
    out = tools.dispatch("data_availability", {"result_id": rows[0]["id"]})
    assert out.get("error") != "unknown tool 'data_availability'"       # registered in _DISPATCH
    assert "alternatives" in out
