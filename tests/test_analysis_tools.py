"""The three new analysis tools: fit_relation (shard, cross-design law), regulon_response + exchange_flux
(raw-gated). Verifies the honest in/out-of-sample split, the regulon aggregation, and clean raw-gating."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("CELLARIUM_MANIFEST", "data/manifest/vmnik-compact.parquet")

from cellarium import tools  # noqa: E402


def test_fit_relation_splits_in_and_out_of_sample():
    """The Scott/Hui ribosome-growth law across designs, with the fit SPLIT so in-sample (fitted) points can't be
    mistaken for predictive validation. Uses in-sample conditions + out-of-sample perturbations."""
    designs = ["wildtype/basal", "condition/with_aa", "condition/no_oxygen",   # in-sample (fitted)
               "condition/acetate", "condition/succinate",                      # out-of-sample media
               "ppgpp_conc/basal|ppGpp:0.2x", "ppgpp_conc/basal|ppGpp:2.0x",    # out-of-sample perturbations
               "rrna_operon_knockout/minimal|rRNA_KO:2op", "rrna_operon_knockout/minimal|rRNA_KO:6op"]
    out = tools.fit_relation(designs=designs, x_channel="growth_rate", y_channel="ribosome_conc")
    assert "fit_all" in out and "fit_out_of_sample_only" in out          # the honest split is always present
    assert out["n_out_of_sample"] >= 3 and out["n_in_sample"] >= 1
    assert out["fit_all"]["r_squared"] is not None
    # every point carries a provenance tag (so a caller can't conflate fitted with predicted)
    provs = {p["provenance"] for p in out["points"]}
    assert provs <= {"in_sample", "out_of_sample"} and "out_of_sample" in provs
    assert out["fit_out_of_sample_only"]["n"] == out["n_out_of_sample"]


def test_regulon_response_aggregates_a_named_gene_set(monkeypatch):
    """A regulon PREDICTION: how many of a named gene-set moved, and which way. Aggregation is exercised with a
    stubbed top_movers in its REAL shape (up/down lists of {id, symbol, log2fc, q}); the tool must tally only the
    regulon's genes and call the direction. (This mirrors the live output — an earlier version mocked a flat
    `movers` key that top_movers never returns, which hid a real read-the-wrong-field bug.)"""
    monkeypatch.setattr(tools, "top_movers", lambda target, reference="wildtype/basal", kind="protein", top=12: {
        "kind": "protein", "n_significant_fdr10": 5, "count_floor": 20.0, "n_target_runs": 2,
        "up": [{"id": "NARG-MONOMER[m]", "symbol": "narG", "log2fc": 2.1, "q": 0.01},
               {"id": "NARH-MONOMER[m]", "symbol": "narH", "log2fc": 1.8, "q": 0.02},
               {"id": "NARK-MONOMER[i]", "symbol": "narK", "log2fc": 1.2, "q": 0.04},
               {"id": "ACRB-MONOMER[i]", "symbol": "acrB", "log2fc": 3.0, "q": 0.01}],   # not a nar gene -> ignored
        "down": [{"id": "PFLB-MONOMER[c]", "symbol": "pflB", "log2fc": -0.4, "q": 0.09}]})  # fnr, NOT nar -> ignored
    out = tools.regulon_response("nar_nitrate", "condition/plus_nitrate")
    assert out["verdict"] == "activated"
    assert out["n_significant_in_regulon"] == 3 and out["n_up"] == 3 and out["n_down"] == 0
    assert out["n_significant_total"] == 5                                  # carries top_movers' total through
    assert {m["gene"] for m in out["movers"]} == {"narg", "narh", "nark"}   # only nar genes counted

    assert "known" in tools.regulon_response("no_such_regulon", "condition/x")   # unknown regulon lists options


def test_regulon_response_raw_gated_when_top_movers_fails(monkeypatch):
    monkeypatch.setattr(tools, "top_movers", lambda *a, **k: {"error": "reader worker produced no JSON"})
    out = tools.regulon_response("nar_nitrate", "condition/plus_nitrate")
    assert out["needs_raw"] is True and "download_raw" in out["message"]


def test_exchange_flux_raw_gated_off_shard():
    # no design has full simOut local in CI -> a clean, actionable gate, not a crash
    out = tools.exchange_flux("condition/acetate", "acetate")
    assert out.get("needs_raw") is True or "error" in out


def test_fit_relation_reports_slope_inference():
    """DS-1: a growth LAW must carry inference on the slope, not just R² — SE, t, two-sided p, a 95% CI, and
    adj R². The Scott/Hui ribosome-growth law is a strong relationship, so its slope CI should clear 0."""
    designs = ["wildtype/basal", "condition/with_aa", "condition/no_oxygen",
               "condition/acetate", "condition/succinate",
               "ppgpp_conc/basal|ppGpp:0.2x", "ppgpp_conc/basal|ppGpp:2.0x",
               "rrna_operon_knockout/minimal|rRNA_KO:2op", "rrna_operon_knockout/minimal|rRNA_KO:6op"]
    fit = tools.fit_relation(designs=designs, x_channel="growth_rate", y_channel="ribosome_conc")["fit_all"]
    for k in ("slope_se", "slope_t", "slope_p_value", "slope_ci95", "slope_ci_excludes_0", "adj_r_squared"):
        assert k in fit                                          # inference fields are always present
    assert isinstance(fit["slope_ci95"], list) and len(fit["slope_ci95"]) == 2
    assert fit["slope_ci95"][0] <= fit["slope"] <= fit["slope_ci95"][1]   # CI brackets the point estimate
    assert fit["slope_ci_excludes_0"] is True and fit["slope_p_value"] < 0.05   # strong law -> significant


def test_bimodality_runs_on_corpus_and_guards_small_n():
    """M-1: the Council's 'test for bimodality' is now executable. Whole-corpus growth_rate has enough pooled
    per-seed values to score; a single-design scope (too few points) must gate cleanly, not crash."""
    out = tools.bimodality(channel="growth_rate")
    assert out["n"] >= 4 and isinstance(out["bimodality_coefficient"], float)
    assert isinstance(out["bimodal_suggested"], bool) and out["best_split"]["separation_sd"] is not None
    assert abs(out["bc_threshold"] - 5 / 9) < 0.01
    thin = tools.bimodality(channel="growth_rate", designs=["no_such/design"])
    assert "error" in thin and thin["n"] < 4                     # too few pooled values -> clean gate, not a crash


def test_dispatch_unknown_tool_and_semantic_validation():
    """AG-3: dispatch guards unknown tools (with a nearest-name suggestion) and pre-validates a call against the
    tool's schema/signature — a clear message for a missing-required or unknown argument, not an opaque TypeError,
    and never a false rejection of a valid call."""
    out = tools.dispatch("survey_corpuss", {})                     # typo'd tool name
    assert "error" in out and "unknown tool" in out["error"] and "survey_corpus" in out["error"]   # difflib suggestion

    out = tools.dispatch("mechanistic_scope", {})                  # schema requires 'symbol'
    assert "error" in out and "missing required" in out["error"] and "symbol" in out["error"]

    out = tools.dispatch("mechanistic_scope", {"symbol": "pfkA", "bogus": 1})   # not in the signature
    assert "error" in out and "unknown argument" in out["error"] and "bogus" in out["error"]

    out = tools.dispatch("mechanistic_scope", {"symbol": "pfkA"})   # valid -> dispatches (no validation error)
    assert isinstance(out, dict)
    assert "missing required" not in str(out) and "unknown argument" not in str(out)
