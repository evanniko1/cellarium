"""AUDIT-KF-N1 — growth without a carbon source is declared unrepresentable, the gate refuses it, and the
evidence is pinned.

Known-fault audit E2 (scripts/validate_known_faults.py, steady_state): with no glucose the cell takes up no
carbon yet keeps growing at the glucose rate; with glucose removed at 1,200 s growth is unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path

from cellarium import capability as C
from cellarium import gate, mcp

ROOT = Path(__file__).resolve().parents[1]
KEY = "growth_without_a_carbon_source"


def test_absent_in_every_elongation_model_with_a_refusal_that_names_the_mechanism():
    cap = C._BY_KEY[KEY]
    assert cap.holds_in == () and not cap.present and cap.markers == ()
    for m in C.ELONGATION_MODES:
        r = C.check(KEY, m)
        assert r["can_answer"] is False and r["why_not"] == "no_elongation_model_represents_it"
        for phrase in ("no carbon", "not conserved", "neither outcome is a prediction"):
            assert phrase in r["refusal"], (m, phrase)


def _req(**kw):
    return gate.Requirement(**{"observable": "media_response", "granularity": "aggregate", **kw})


def test_the_gate_refuses_any_observable_once_carbon_removal_is_a_dependency():
    for obs in ("media_response", "gene_knockout", "trna_charging", "other"):
        for m in C.ELONGATION_MODES:
            d = gate.decide(_req(observable=obs, regulatory_dependencies=("carbon_source_removal",)), mode=m)
            assert d.verdict == "refuse" and KEY in d.blocking, (obs, m)
            assert d.route == ""


def test_the_parser_is_told_about_the_dependency_and_that_lower_glucose_is_not_removal():
    enum = gate._PARSE_TOOL["input_schema"]["properties"]["regulatory_dependencies"]["items"]["enum"]
    assert "carbon_source_removal" in enum
    assert "carbon_source_removal" in gate._PARSE_SYSTEM and "not removal" in gate._PARSE_SYSTEM


def test_raw_tool_reads_of_a_glucose_free_design_are_refused_but_a_glucose_ramp_is_not():
    for design in ("condition/no_glucose", "timeline/0 minimal, 1200 minimal_no_glucose"):
        refusal = mcp.capability_precheck("read_series", {"design": design, "channel": "growth_rate"})
        assert refusal is not None and KEY in json.dumps(refusal), design
    ramp = "timeline/0 minimal_GLC_20mM, 1800 minimal_GLC_5mM, 3600 minimal_GLC_2mM"
    assert mcp.capability_precheck("read_series", {"design": ramp, "channel": "growth_rate"}) is None


def test_the_audit_evidence_is_what_the_registry_says_it_is():
    res = json.loads((ROOT / "evals" / "results" / "known_faults_validation.json").read_text(encoding="utf-8"))
    runs = res["runs"]
    removed = {k: v for k, v in runs.items() if k.startswith("E2_glucose_removed_1200s/")}
    assert len(removed) == 4
    ids = sorted(v["identity_key"] for v in removed.values())
    assert ids.count("no_traceback") == 3
    assert ids.count("NegativeCountsError@wholecell/states/bulk_molecules.py:merge") == 1
    absent = {k: v for k, v in runs.items() if k.startswith("E2_glucose_absent/")}
    assert len(absent) == 2 and all(v["identity_key"] == "no_traceback" for v in absent.values())
