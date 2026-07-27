"""LETHALITY surfacing — the blind spot: sims that divide then COLLAPSE at depth were invisible.

`is_reportable` requires EVERY generation to be ok, so one collapsed generation discards the whole run —
including the valid early generations before it. That is correct for the channel RANKING (a collapsed
generation's mean is numerical garbage: growth blows past the physical ceiling), but it silently buried the
lethality phenotype itself: an essential-gene KO that divides on inherited enzyme for a generation or two, then
collapses, is exactly the signal to check against literature and lab. `survey.lethality` reads it back from the
per-generation QC verdicts + the per-generation trajectory, reporting the PRE-collapse signature only.

These run against the live corpus and skip cleanly when it is absent.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("CELLARIUM_MANIFEST", "data/manifest/vmnik-compact.parquet")
os.environ.setdefault("CELLARIUM_OUT", "runs")

import pytest  # noqa: E402


def _corpus():
    from cellarium import store
    if not store.has_manifest():
        pytest.skip("no local manifest")


def test_lethality_surfaces_designs_the_ranked_survey_hides():
    """The headline: designs with zero reportable seeds (dapA, rpmE) are invisible to survey_corpus but MUST be
    visible here — a whole essential-KO phenotype was otherwise absent from every view."""
    _corpus()
    from cellarium import survey
    L = survey.lethality()
    assert L["n_designs_collapsing"] >= 1, "no collapse surfaced — the blind spot is back"
    hidden = {e["design"] for e in L["designs"] if e["fully_hidden"]}
    ranked = {e["design"] for d in survey.survey_corpus(top=100)["by_channel"].values() for e in d["ranked"]}
    assert hidden, "no fully-hidden design found — expected essential KOs with zero reportable seeds"
    assert not (hidden & ranked), f"{hidden & ranked} is both fully-hidden AND ranked — contradiction"


def test_a_collapse_reports_where_it_collapses_and_the_pre_collapse_state():
    """A collapse must name the generation it fails at and carry the LAST GOOD generation's growth/ppGpp — the
    post-collapse channel garbage must never be what is reported."""
    _corpus()
    from cellarium import survey
    for e in survey.lethality()["designs"]:
        assert e["collapses_at_generation"] is not None and e["collapses_at_generation"] >= 1, (
            f"{e['design']} collapses at generation {e['collapses_at_generation']} — a gen-0 failure is a dead "
            "run, a different category, and must not appear here")
        pc = e["pre_collapse"]
        assert pc["generation"] == e["collapses_at_generation"] - 1, "pre-collapse must be the generation BEFORE"
        assert pc["growth"] is None or pc["growth"] < 0.001, (
            f"{e['design']} reports growth {pc['growth']} >= the implausible ceiling — that is post-collapse "
            "garbage, exactly what this view must NOT surface")


def test_the_stringent_signature_is_depth_matched_and_not_over_claimed():
    """The signature (growth down + ppGpp up vs WT) must be read at the collapse generation's OWN depth, and it
    must be a FLAG to check, not an assertion. dapA shows it dramatically; the aaRS KOs, properly depth-matched,
    do NOT (their ppGpp is not elevated vs the depth-matched WT) — the tool must reflect that, not paper over it."""
    _corpus()
    from cellarium import survey
    designs = {e["design"]: e for e in survey.lethality()["designs"]}
    dapA = designs.get("gene_knockout/KO:dapA")
    if dapA and dapA["pre_collapse"]["ppgpp_pct_vs_wt"] is not None:
        # dapA's pre-collapse ppGpp is hugely elevated vs the depth-matched WT — a real stringent signature
        assert dapA["pre_collapse"]["ppgpp_pct_vs_wt"] > 100 and dapA["stringent_signature"] is True
    argS = designs.get("gene_knockout/KO:argS")
    if argS and argS["pre_collapse"]["ppgpp_pct_vs_wt"] is not None:
        # argS ppGpp is NOT elevated vs the depth-matched WT — the flag must be honest about that
        assert argS["stringent_signature"] is False, (
            "argS is flagged stringent, but its depth-matched ppGpp is not elevated — over-claiming")


def test_survey_corpus_carries_the_lethality_pointer():
    """The blind spot is only fixed if the MANDATORY first read surfaces it — an agent must not have to know to
    ask. survey_corpus must carry the compact lethality block."""
    _corpus()
    from cellarium import survey
    s = survey.survey_corpus()
    assert "lethality" in s, "survey_corpus does not surface lethality — the blind spot persists in the first read"
    lb = s["lethality"]
    assert lb["n_designs_collapsing"] >= 1 and "collapsing_designs" in lb
    assert any("lethality_landscape" in str(v) for v in (lb.get("note"), s.get("note")))


def test_the_tool_is_registered_and_dispatchable():
    from cellarium import tools
    names = {t["name"] for t in tools.TOOLS}
    assert "lethality_landscape" in names and "lethality_landscape" in tools._DISPATCH


def test_it_degrades_rather_than_raising_on_no_corpus(monkeypatch):
    """A corpus read error must return a structured empty result, not raise into the agent loop."""
    from cellarium import survey
    monkeypatch.setattr(survey, "_leth_rows", lambda: [{"__error__": "boom"}])
    out = survey.lethality()
    assert out["designs"] == [] and "error" in out
