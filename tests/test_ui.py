"""UI view-helper tests — the glass-box renderers are pure + framework-agnostic (no Streamlit needed)."""

from cellarium import ui


def test_trust_signals_extracts_rigor_and_safety_from_trace():
    trace = [
        ("survey_corpus", {}, {"channels": {}}),
        ("power_check", {"channel": "growth_rate"}, {"adequately_powered": False, "min_detectable_effect_pct_at_n": 20}),
        ("disconfirm", {}, {"verdict": "survived"}),
        ("screen_design", {}, {"flags": ["amr_efflux"]}),
        ("provenance", {}, {"provenance": "out_of_sample"}),
    ]
    sig = ui.trust_signals(trace)
    assert sig["Power"] == "under-powered"
    assert sig["Disconfirmation"] == "survived"
    assert sig["Biosecurity"] == "FLAGGED"
    assert sig["Provenance"] == "out_of_sample"


def test_trust_signals_empty_when_no_trust_tools():
    assert ui.trust_signals([("survey_corpus", {}, {"x": 1}), ("differential", {}, {})]) == {}


def test_hypothesis_view_handles_none_and_brief():
    assert ui.hypothesis_view(None) == {}

    class H:
        claim = "pfkA is non-essential"

        def brief(self):
            return "pfkA KO is viable (rerouted via pfkB)"

    v = ui.hypothesis_view(H())
    assert "viable" in v["brief"] and v["claim"] == "pfkA is non-essential"


def test_trace_view_is_json_safe_and_compact():
    tv = ui.trace_view([("viability", {"gene": "pfkA"}, {"verdict": "viable"})])
    assert tv[0]["tool"] == "viability" and tv[0]["output"]["verdict"] == "viable"


def test_design_view_from_model_and_dict():
    from cellarium.model import Design

    d = Design(perturbation="gene_knockout", condition="basal",
               params={"target_genes": ["pfkA"]}, seeds=10, generations=5)
    v = ui.design_view(d)
    assert v["perturbation"] == "gene_knockout" and v["condition"] == "basal"
    assert v["genes"] == ["pfkA"] and v["seeds"] == 10 and v["generations"] == 5

    v2 = ui.design_view({"perturbation": "wildtype", "params": {}})   # queue stores designs as dicts
    assert v2["perturbation"] == "wildtype" and v2["genes"] == [] and v2["seeds"] == 1


def test_vet_summary_clean_and_flagged():
    clean = {"runnable": True, "safety": {"flagged": False},
             "feasibility": {"in_envelope": False, "advisory": "boundary probe"},
             "provenance": {"provenance": "out_of_sample", "value": "OUT-OF-SAMPLE — run it"}}
    s = ui.vet_summary(clean)
    assert s["runnable"] and s["safety"] == "clear"
    assert "boundary" in s["feasibility"] and s["provenance"] == "out_of_sample" and "OUT-OF-SAMPLE" in s["why"]

    flagged = {"runnable": False, "safety": {"flagged": True},
               "feasibility": {"in_envelope": True}, "provenance": {}}
    f = ui.vet_summary(flagged)
    assert not f["runnable"] and "FLAGGED" in f["safety"]
    assert ui.vet_summary(None) == {}
