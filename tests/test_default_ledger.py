"""J-1: every tool result names the defaults that shaped it, read from what was actually applied.

A TOOL default is a parameter the call left out, filled by the tool's own signature: the signature is what runs, so it
is read there rather than from the description's prose. A SIMULATOR default is what a design's label leaves unsaid:
the elongation model when it carries no tag, the medium a non-condition design runs in, and the one knowledge-base
fit every corpus row shares.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from cellarium import defaults  # noqa: E402


def _tool(design, reference="wildtype/basal", min_count=10.0, fdr=0.1, arm=None):
    return {}


def test_a_parameter_the_call_left_out_is_named_with_the_value_the_signature_gave_it():
    used = defaults.applied("t", {"design": "gene_knockout/KO:argS"}, _tool)
    assert used["tool"] == {"reference": "wildtype/basal", "min_count": 10.0, "fdr": 0.1, "arm": None}


def test_a_parameter_the_call_gave_is_not_a_default():
    used = defaults.applied("t", {"design": "gene_knockout/KO:argS", "reference": "condition/with_aa",
                                  "min_count": 5, "fdr": 0.05, "arm": "x"}, _tool)
    assert used["tool"] == {}


def test_a_label_without_an_elongation_tag_runs_under_the_default_model():
    sim = defaults.applied("t", {"design": "gene_knockout/KO:argS"}, _tool)["simulator"]
    assert sim["elongation_model"].startswith("steady_state")
    tagged = defaults.applied("t", {"design": "gene_knockout/KO:argS#elong:kinetic",
                                    "reference": "wildtype/basal#elong:kinetic"}, _tool)["simulator"]
    assert "elongation_model" not in tagged


def test_a_knockout_runs_in_the_default_medium_and_a_condition_names_its_own():
    assert "glucose" in defaults.applied("t", {"design": "gene_knockout/KO:argS"}, _tool)["simulator"]["medium"]
    cond = defaults.applied("t", {"design": "condition/acetate", "reference": "condition/succinate"}, _tool)
    assert "medium" not in cond["simulator"]


def test_every_design_shares_one_fit_and_a_call_naming_no_design_has_no_simulator_default():
    assert "fit" in defaults.applied("t", {"design": "wildtype/basal"}, _tool)["simulator"]
    assert defaults.applied("u", {}, lambda: {}) == {"tool": {}, "simulator": {}}


def test_dispatch_puts_the_ledger_on_the_result(monkeypatch):
    from cellarium import tools
    monkeypatch.setitem(tools._DISPATCH, "survey_corpus", lambda arm=None, channels=None: {"ok": True})
    monkeypatch.setattr(tools, "_validate_args", lambda name, args: None)
    out = tools.dispatch("survey_corpus", {})
    assert out["defaults_applied"] == {"tool": {"arm": None, "channels": None}, "simulator": {}}


def test_an_error_carries_no_ledger(monkeypatch):
    from cellarium import tools
    monkeypatch.setitem(tools._DISPATCH, "survey_corpus", lambda arm=None, channels=None: {"error": "no corpus"})
    monkeypatch.setattr(tools, "_validate_args", lambda name, args: None)
    assert "defaults_applied" not in tools.dispatch("survey_corpus", {})
