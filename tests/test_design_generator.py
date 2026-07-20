"""SCI-4: the multi-KO / reduced-genome design generator. Tests monkeypatch scope/store so they're deterministic and
corpus-independent, and lock the contract: dispensable-pool exclusions, scoring guards (essential/machinery/biosec),
weakest-link ranking, and that only proposable (biosecurity-clean, non-essential) sets are handed back."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cellarium import design_generator as dg  # noqa: E402

# a small synthetic scope: two clean dispensables, one essential, one machinery
_SCOPE = {
    "aaa": {"known": True, "is_machinery": False, "essential_reference": False, "ko_index": 11, "role": "metabolic_enzyme"},
    "bbb": {"known": True, "is_machinery": False, "essential_reference": False, "ko_index": 12, "role": "metabolic_enzyme"},
    "essG": {"known": True, "is_machinery": False, "essential_reference": True, "ko_index": 13, "role": "metabolic_enzyme"},
    "machG": {"known": True, "is_machinery": True, "essential_reference": False, "ko_index": 14, "role": "central_dogma_machinery"},
}


def _patch(monkeypatch, surrogate_probs=None):
    from cellarium import scope
    monkeypatch.setattr(scope, "classify_gene", lambda g: _SCOPE.get(g, {"known": False}))
    if surrogate_probs is not None:
        from cellarium import surrogate
        monkeypatch.setattr(surrogate, "build_dataset", lambda *a, **k: {"synthetic": True})
        monkeypatch.setattr(surrogate, "predict",
                            lambda g, ds=None: {"viability_probability": surrogate_probs.get(g)})


def test_dispensable_pool_excludes_essential_and_machinery(monkeypatch):
    from cellarium import store
    monkeypatch.setattr(store, "viability", lambda p, c: {"designs": [
        {"condition": "KO:aaa", "verdict": "viable"}, {"condition": "KO:bbb", "verdict": "viable"},
        {"condition": "KO:essG", "verdict": "viable"},          # singly viable in silico but benchmark-essential
        {"condition": "KO:machG", "verdict": "viable"},         # machinery — never a reduction target
        {"condition": "KO:xxx", "verdict": "inviable"}]})       # non-viable single KO excluded from the pool
    _patch(monkeypatch)
    out = dg.dispensable_pool()
    assert out["pool"] == ["aaa", "bbb"]
    reasons = " ".join(d["reason"] for d in out["dropped"])
    assert "machinery" in reasons and "essential" in reasons


def test_score_set_avoids_essential_and_machinery_members(monkeypatch):
    _patch(monkeypatch, surrogate_probs={"aaa": 0.9, "bbb": 0.9})
    assert dg.score_set(["aaa", "essG"])["recommend"] == "avoid"    # an essential member -> avoid
    assert dg.score_set(["aaa", "machG"])["recommend"] == "avoid"   # a machinery member -> avoid


def test_score_set_weakest_link_prior_and_flag(monkeypatch):
    _patch(monkeypatch, surrogate_probs={"aaa": 0.95, "bbb": 0.30})
    s = dg.score_set(["aaa", "bbb"])
    assert s["viability_prior"] == 0.3          # min of the members (weakest link), not the mean
    assert s["recommend"] == "flag"             # weakest member below 0.5 -> flag, don't propose
    assert s["surrogate_used"] is True


def test_score_set_proposes_clean_viable_set(monkeypatch):
    _patch(monkeypatch, surrogate_probs={"aaa": 0.9, "bbb": 0.8})
    s = dg.score_set(["aaa", "bbb"])
    assert s["recommend"] == "propose" and s["biosecurity_flagged"] is False
    assert "epistasis" in s["caveat"].lower()


def test_generate_ranks_and_returns_runnable_designs(monkeypatch):
    from cellarium import store
    monkeypatch.setattr(store, "viability", lambda p, c: {"designs": [
        {"condition": "KO:aaa", "verdict": "viable"}, {"condition": "KO:bbb", "verdict": "viable"}]})
    _patch(monkeypatch, surrogate_probs={"aaa": 0.9, "bbb": 0.8})
    out = dg.generate(k=2, max_candidates=5)
    assert out["n_pool"] == 2 and out["n_proposed"] == 1
    d = out["designs"][0]
    assert d["perturbation"] == "multi_gene_knockout" and d["condition"] == "KO:aaa+bbb"
    assert d["params"]["ko_indices"] == [11, 12]        # resolved from scope, in gene order


def test_generate_drops_avoid_designs(monkeypatch):
    # a pool where every pair contains an essential member -> nothing proposable, but it must not crash
    from cellarium import scope, store
    monkeypatch.setattr(store, "viability", lambda p, c: {"designs": [{"condition": "KO:aaa", "verdict": "viable"}]})
    monkeypatch.setattr(scope, "classify_gene", lambda g: _SCOPE.get(g, {"known": False}))
    out = dg.generate(pool=["aaa", "essG"], k=2, max_candidates=5)
    assert out["n_proposed"] == 0 and out["designs"] == []


def test_generate_is_wired_as_an_agent_tool():
    from cellarium import tools
    assert "generate_designs" in tools._DISPATCH
    assert any(t["name"] == "generate_designs" for t in tools.TOOLS)
