"""HF-availability tests — the two-alternatives surface (no network). Run: python -m pytest tests/test_hf.py"""

import tarfile

import pytest

from cellarium import hf, store, tools


def test_download_raw_reports_per_archive_progress(monkeypatch):
    """A confirmed multi-archive pull streams progress (done/total) per archive through the agent's set_progress
    hook, so a multi-GB HF download shows 'downloading 2/5' instead of hanging silently. Network+extract stubbed."""
    huggingface_hub = pytest.importorskip("huggingface_hub")  # in the optional [hf] extra; skip if absent
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


def test_full_simout_local_distinguishes_remnant_from_complete(tmp_path):
    """'local' must mean the raw simOut is actually readable, not that a run DIR merely exists. A remnant dir
    (design.json / an interrupted extract) is NOT local; a dir carrying .../simOut/MonomerCounts IS. This is what
    the gene-level reader tools (top_movers / regulon_response) require."""
    remnant = tmp_path / "cellarium" / "condition_000999" / "000000"
    (remnant / "generation_000000").mkdir(parents=True)                 # exists, but NO simOut
    (remnant / "design.json").write_text("{}", encoding="utf-8")
    assert hf._full_simout_local(str(remnant)) is False

    complete = tmp_path / "cellarium" / "condition_000998" / "000000"
    (complete / "generation_000000" / "000000" / "simOut" / "MonomerCounts").mkdir(parents=True)
    assert hf._full_simout_local(str(complete)) is True

    assert hf._full_simout_local(None) is False                         # never crashes on missing input
    assert hf._full_simout_local(str(tmp_path / "does_not_exist")) is False


def test_download_plan_counts_a_remnant_dir_as_pullable(tmp_path, monkeypatch):
    """The planner bug this fixes: a remnant run dir (no simOut) was called 'local', so download_raw returned
    n_to_pull=0 ('already local') and refused a legitimate pull while the reader tools failed. With the
    full-simOut check the remnant is correctly pull-able when on HF — and becomes 'local' only once complete."""
    remnant = tmp_path / "cellarium" / "gk_x" / "000000"
    (remnant / "generation_000000").mkdir(parents=True)                 # exists, but NO simOut
    monkeypatch.setattr(hf, "_design_seeds", lambda d: [{"id": "r0", "seed": 0}])
    monkeypatch.setattr(hf.store, "simout_path", lambda rid: str(remnant))
    monkeypatch.setattr(hf, "_repo_sizes", lambda paths: {p: 5_000_000_000 for p in paths})   # on HF, 5 GB

    plan = hf.download_plan("gk/x")
    assert plan["n_local"] == 0 and plan["n_to_pull"] == 1              # remnant is NOT local -> pull offered
    assert plan["est_gb"] == 5.0 and plan["not_on_hf"] == []

    # once the simOut is actually present, the planner correctly calls it local and offers no pull
    (remnant / "generation_000000" / "000000" / "simOut" / "MonomerCounts").mkdir(parents=True)
    plan2 = hf.download_plan("gk/x")
    assert plan2["n_local"] == 1 and plan2["n_to_pull"] == 0
