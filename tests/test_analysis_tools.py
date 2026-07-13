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
    stubbed top_movers (the raw read); the tool must tally only the regulon's genes and call the direction."""
    monkeypatch.setattr(tools, "top_movers", lambda target, reference="wildtype/basal", kind="protein", top=12: {
        "movers": [{"gene": "narG", "log2fc": 2.1, "q": 0.01}, {"gene": "narH", "log2fc": 1.8, "q": 0.02},
                   {"gene": "narK", "log2fc": 1.2, "q": 0.04},
                   {"gene": "pflB", "log2fc": -0.4, "q": 0.2},           # in fnr regulon, NOT nar -> ignored
                   {"gene": "acrB", "log2fc": 3.0, "q": 0.01}]})         # not a nar gene -> ignored
    out = tools.regulon_response("nar_nitrate", "condition/plus_nitrate")
    assert out["verdict"] == "activated"
    assert out["n_significant_in_regulon"] == 3 and out["n_up"] == 3 and out["n_down"] == 0
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
