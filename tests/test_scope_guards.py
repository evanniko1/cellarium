"""H-6 C3/C4: host-testable guards on the gene_scope cache — staleness (cache_status) and benchmark presence
(benchmark_available + the essentiality tool's 'benchmark disabled' warning). No sim_data needed; _scope is mocked."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cellarium import scope, tools  # noqa: E402


def _reset_caches():
    for fn in (scope._scope, scope.benchmark_available):
        clear = getattr(fn, "cache_clear", None)   # monkeypatched lambdas have none — skip
        if clear:
            clear()


def test_benchmark_available_true_when_any_gene_has_a_reference(monkeypatch):
    _reset_caches()
    monkeypatch.setattr(scope, "_scope", lambda: {
        "pfkA": {"essential_ref": None}, "fabI": {"essential_ref": True}})
    assert scope.benchmark_available() is True
    _reset_caches()


def test_benchmark_available_false_when_validation_file_absent(monkeypatch):
    _reset_caches()
    # every gene None -> the benchmark was not built into the cache
    monkeypatch.setattr(scope, "_scope", lambda: {"pfkA": {"essential_ref": None}, "gltA": {"essential_ref": None}})
    assert scope.benchmark_available() is False
    _reset_caches()


def test_metabolic_essentiality_warns_when_benchmark_disabled(monkeypatch):
    _reset_caches()
    # classify_gene reports a known metabolic enzyme not in the reference set, and the corpus has NO benchmark at all
    monkeypatch.setattr(scope, "classify_gene", lambda g: {
        "known": True, "role": "metabolic_enzyme", "benchmark": {"essential_reference": None}, "ko_effect_prior": "x"})
    monkeypatch.setattr(scope, "benchmark_available", lambda: False)
    monkeypatch.setattr("cellarium.reader.fba_essentiality", lambda genes: {"genes": {}})
    out = tools.metabolic_essentiality("pfkA")
    assert out["verdict"] == "benchmark unavailable"
    assert out["benchmark_available"] is False
    assert "not loaded" in out["warning"].lower() or "disabled" in out["scope"].lower()
    _reset_caches()


def test_metabolic_essentiality_normal_when_benchmark_present(monkeypatch):
    _reset_caches()
    monkeypatch.setattr(scope, "classify_gene", lambda g: {
        "known": True, "role": "metabolic_enzyme",
        "benchmark": {"essential_reference": True, "agreement": "model_UNDER_predicts"}, "ko_effect_prior": "x"})
    monkeypatch.setattr(scope, "benchmark_available", lambda: True)
    monkeypatch.setattr("cellarium.reader.fba_essentiality", lambda genes: {"genes": {}})
    out = tools.metabolic_essentiality("fabI")
    assert out["verdict"] == "ESSENTIAL (benchmark)"
    assert out["benchmark_available"] is True
    _reset_caches()


def test_cache_status_reports_missing_cache(monkeypatch, tmp_path):
    _reset_caches()
    monkeypatch.setattr(scope, "SCOPE_CACHE", tmp_path / "does_not_exist.json")
    st = scope.cache_status()
    assert st["cached"] is False and st["stale"] is True
    _reset_caches()


def test_cache_status_flags_stale_when_kb_newer(monkeypatch, tmp_path):
    _reset_caches()
    cache = tmp_path / "gene_scope.json"
    cache.write_text("{}", encoding="utf-8")
    kb = tmp_path / "cellarium" / "kb" / "simData.cPickle"
    kb.parent.mkdir(parents=True)
    kb.write_text("x", encoding="utf-8")
    # make the kb strictly newer than the cache
    import os as _os
    st_cache = cache.stat()
    _os.utime(kb, (st_cache.st_atime + 100, st_cache.st_mtime + 100))
    monkeypatch.setattr(scope, "SCOPE_CACHE", cache)
    monkeypatch.setenv("CELLARIUM_OUT", str(tmp_path))
    assert scope.cache_status()["stale"] is True
    _reset_caches()
