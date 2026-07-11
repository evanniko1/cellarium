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
