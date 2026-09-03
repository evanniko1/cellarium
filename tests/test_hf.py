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


def test_data_availability_verifies_real_hf_existence(monkeypatch):
    """Integrity fix: data_availability must VERIFY the archive is actually on HF (the same check download_raw uses),
    never fabricate available=True from the HF_HAS_RAW flag + a string transform. hf_exists True/False/None ->
    available + a copy-paste command ONLY when presence is confirmed."""
    from cellarium import hf, store
    p = "/x/cellarium/gene_knockout/KO_pfkA/s0/simOut"
    monkeypatch.setattr(store, "simout_path", lambda rid: p)
    monkeypatch.setattr(store, "list_results",
                        lambda: [{"id": "r1", "perturbation": "gene_knockout", "condition": "KO:pfkA", "seed": 0}])
    monkeypatch.setattr(hf, "_full_simout_local", lambda path: False)
    monkeypatch.setattr(hf, "HF_HAS_RAW", True)
    # Pin the redaction branch OFF. In an anonymised copy of this repo the default repo id has its owner
    # substituted, so HF_REPO_REDACTED is True and case (3) reports the redaction rather than "could not
    # verify" -- a correct message for that tree, and not what this test is about. Without this pin the
    # suite passes from git and fails from the anonymous download, which reads as broken software.
    monkeypatch.setattr(hf, "HF_REPO_REDACTED", False)
    rel = hf._hf_rel(p)

    def _hf(rid):
        return hf.data_availability(rid)["alternatives"]["1_download_from_hf"]

    monkeypatch.setattr(hf, "_repo_sizes", lambda paths: {rel: 12345})          # (1) confirmed present
    a = _hf("r1")
    assert a["available"] is True and a["verified"] is True and a["command"]

    monkeypatch.setattr(hf, "_repo_sizes", lambda paths: {"runs/cellarium/other/s0/simOut.tar.gz": 1})  # (2) absent
    b = _hf("r1")
    assert b["available"] is False and b["verified"] is True and b["command"] is None and "NOT on HF" in b["status"]

    monkeypatch.setattr(hf, "_repo_sizes", lambda paths: {})                     # (3) API error / offline
    c = _hf("r1")
    assert c["available"] is False and c["verified"] is False and c["command"] is None and "could not verify" in c["status"]

    monkeypatch.setattr(hf, "HF_HAS_RAW", False)                                 # (4) flag off -> never available
    assert _hf("r1")["available"] is False


def test_redacted_dataset_owner_is_named_as_the_cause_not_offline(monkeypatch):
    """An anonymised copy of this repo has the HF owner redacted out of the default repo id, so every hub call
    fails and _repo_sizes comes back empty -- indistinguishable, from inside, from being offline. Reporting it as
    'offline / no hub client' would send a reviewer to debug their network for a cause that is in the artifact.
    The status has to name the redaction instead. No network: _repo_sizes is stubbed to the empty dict either way."""
    p = "/x/cellarium/gene_knockout/KO_pfkA/s0/simOut"
    monkeypatch.setattr(store, "simout_path", lambda rid: p)
    monkeypatch.setattr(store, "list_results",
                        lambda: [{"id": "r1", "perturbation": "gene_knockout", "condition": "KO:pfkA", "seed": 0}])
    monkeypatch.setattr(hf, "_full_simout_local", lambda path: False)
    monkeypatch.setattr(hf, "HF_HAS_RAW", True)
    monkeypatch.setattr(hf, "_repo_sizes", lambda paths: {})     # the ONE observable both cases share

    def _status():
        return hf.data_availability("r1")["alternatives"]["1_download_from_hf"]["status"]

    monkeypatch.setattr(hf, "HF_REPO_REDACTED", True)
    red = _status()
    assert "redacted" in red and "CELLARIUM_HF_REPO" in red
    assert "offline" not in red                                  # the wrong cause must not survive

    monkeypatch.setattr(hf, "HF_REPO_REDACTED", False)           # a real owner: unchanged behaviour
    assert "could not verify" in _status()


def test_redaction_detector_does_not_fire_on_real_owners(monkeypatch):
    """The detector keys on an owner made only of X, digits and dashes -- what 4open substitutes. A real owner
    that merely contains an X ('X-Lab', 'xyz') must not be mistaken for a redacted one, or the public repo would
    start telling users their dataset id was redacted when it was not. Exercises the module's own constant by
    reloading it under each owner, rather than restating the predicate here (which would test nothing).

    NO REAL ACCOUNT NAME APPEARS IN THE NEGATIVE LIST, deliberately. An anonymised copy of this repository
    has term substitution applied to its TEXT, tests included, so a real owner written here as an example
    of "not redacted" comes back as XXXX-N in that copy -- and the line then asserts the exact opposite of
    the line above it. MEASURED: this test failed on the anonymous download while passing from git, which
    reads to a reviewer as broken software rather than as the redaction doing its job."""
    import importlib

    def redacted(owner):
        monkeypatch.setenv("CELLARIUM_HF_REPO", owner + "/cellarium-corpus")
        return importlib.reload(hf).HF_REPO_REDACTED

    try:
        assert all(redacted(o) for o in ("XXXX-9", "XXXX", "XX-1"))
        assert not any(redacted(o) for o in ("some-lab", "X-Lab", "xyz", "openai", "0-9", "lab7"))
    finally:
        monkeypatch.delenv("CELLARIUM_HF_REPO", raising=False)
        importlib.reload(hf)          # leave the module as the rest of the suite expects it
