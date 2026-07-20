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


# --- DD-SCI-4a: FBA synthetic-lethal epistasis fold-in --------------------------------------------------------
def _patch_sl(monkeypatch, synthetic_lethal_pairs=None, error=None):
    """Monkeypatch tools.fba_synthetic_lethal so the epistasis fold-in is deterministic (no real iML1515 LP)."""
    from cellarium import tools
    if error is not None:
        monkeypatch.setattr(tools, "fba_synthetic_lethal", lambda genes, medium=None: {"error": error})
        return
    sl = [{"pair": list(p), "synthetic_lethal": True} for p in (synthetic_lethal_pairs or [])]
    monkeypatch.setattr(tools, "fba_synthetic_lethal",
                        lambda genes, medium=None: {"wt_growth": 0.87, "n_synthetic_lethal": len(sl),
                                                    "synthetic_lethals": sl, "pairs": None})


def test_synthetic_lethal_check_detects_and_degrades_gracefully(monkeypatch):
    _patch_sl(monkeypatch, synthetic_lethal_pairs=[["pfkA", "tpiA"]])
    hit = dg.synthetic_lethal_check(["pfkA", "tpiA"])
    assert hit["available"] is True and hit["synthetic_lethal"] is True and hit["pairs"] == [["pfkA", "tpiA"]]
    _patch_sl(monkeypatch, synthetic_lethal_pairs=[])                 # available, none
    assert dg.synthetic_lethal_check(["aaa", "bbb"])["synthetic_lethal"] is False
    _patch_sl(monkeypatch, error="need >=2 resolvable iML1515 genes")  # non-metabolic / no cobra -> graceful
    assert dg.synthetic_lethal_check(["flgB", "ymgD"])["available"] is False


def test_score_set_use_fba_demotes_a_synthetic_lethal_pair(monkeypatch):
    _patch(monkeypatch, surrogate_probs={"aaa": 0.9, "bbb": 0.8})     # prior says propose...
    _patch_sl(monkeypatch, synthetic_lethal_pairs=[["aaa", "bbb"]])   # ...but FBA says synthetic-lethal
    s = dg.score_set(["aaa", "bbb"], use_fba=True)
    assert s["recommend"] == "flag" and "SYNTHETIC LETHALITY" in s["epistasis"]
    assert s["synthetic_lethal_check"]["synthetic_lethal"] is True
    # without the fold-in it would have stayed propose
    _patch_sl(monkeypatch, synthetic_lethal_pairs=[])
    assert dg.score_set(["aaa", "bbb"], use_fba=True)["recommend"] == "propose"


def test_generate_folds_epistasis_into_the_top_candidates(monkeypatch):
    from cellarium import store
    monkeypatch.setattr(store, "viability", lambda p, c: {"designs": [
        {"condition": "KO:aaa", "verdict": "viable"}, {"condition": "KO:bbb", "verdict": "viable"}]})
    _patch(monkeypatch, surrogate_probs={"aaa": 0.9, "bbb": 0.8})
    _patch_sl(monkeypatch, synthetic_lethal_pairs=[["aaa", "bbb"]])
    out = dg.generate(k=2, max_candidates=5, use_fba=True)
    assert out["fba_epistasis_checked"] is True and out["fba_available"] is True
    d = out["designs"][0]
    assert d["score"]["recommend"] == "flag" and "epistasis" in d["score"]   # the reroute-blocker is surfaced, not buried
    assert out["ranking"][0]["synthetic_lethal"] is True


def test_generate_is_graceful_when_fba_unavailable(monkeypatch):
    from cellarium import store
    monkeypatch.setattr(store, "viability", lambda p, c: {"designs": [
        {"condition": "KO:aaa", "verdict": "viable"}, {"condition": "KO:bbb", "verdict": "viable"}]})
    _patch(monkeypatch, surrogate_probs={"aaa": 0.9, "bbb": 0.8})
    _patch_sl(monkeypatch, error="cobra not installed")
    out = dg.generate(k=2, max_candidates=5, use_fba=True)
    assert out["fba_available"] is False
    assert out["designs"][0]["score"]["recommend"] == "propose"          # prior-only ranking preserved
