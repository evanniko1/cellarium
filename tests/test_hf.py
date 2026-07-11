"""HF-availability tests — the two-alternatives surface (no network). Run: python -m pytest tests/test_hf.py"""

from cellarium import hf, store, tools


def test_hf_rel_maps_run_path_to_dataset_path():
    p = hf.OUT_ROOT / "cellarium" / "gene_knockout_001594" / "000000"
    assert hf._hf_rel(str(p)) == "cellarium/gene_knockout_001594/000000"
    assert hf._hf_rel(None) is None
    assert hf._hf_rel("/some/unrelated/path") is None      # outside OUT_ROOT -> None, never crashes


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
