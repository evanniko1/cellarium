"""Item 4d — phosphate depletion is declared unrepresentable, the gate refuses it, and the evidence is pinned.

Validated 2026-10-12 (scripts/validate_phosphate.py): phosphate absent from the start (4/4 seeds) and removed
from a growing cell (4/4) end with ATP exhausted in translation, in steady state and in kinetic mode (2/2),
while the wild-type controls in the same output trees complete. The phosphate pools never fall, PhoB is never
phosphorylated, and PhoB is not a fitted transcription factor.
"""

from __future__ import annotations

import json
from pathlib import Path

from cellarium import capability as C
from cellarium import gate, mcp

ROOT = Path(__file__).resolve().parents[1]
KEY = "growth_under_phosphate_depletion"


def test_absent_in_every_elongation_model_with_a_refusal_that_names_the_mechanism():
    cap = C._BY_KEY[KEY]
    assert cap.holds_in == () and not cap.present and cap.markers == ()
    for m in C.ELONGATION_MODES:
        r = C.check(KEY, m)
        assert r["can_answer"] is False and r["why_not"] == "no_elongation_model_represents_it"
        for phrase in ("PhoB", "ATP", "NOT a prediction that the cell dies"):
            assert phrase in r["refusal"], (m, phrase)


def test_the_audit_reports_it_as_declaration_only(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "probe_launch_surface", lambda w=None: {"ok": True, "verified": False})
    monkeypatch.setattr(C, "probe_corpus_modes", lambda: {"ok": True, "verified": False})
    root = tmp_path / "wc" / "models"
    root.mkdir(parents=True)
    (root / "s.py").write_text("\n".join(f"{m} = 1" for c in C.CAPABILITIES for m in c.markers), encoding="utf-8")
    assert KEY in C.audit(str(tmp_path / "wc"))["declaration_only"]


def _req(**kw):
    return gate.Requirement(**{"observable": "media_response", "granularity": "aggregate", **kw})


def test_the_gate_refuses_any_observable_once_phosphate_depletion_is_a_dependency():
    for obs in ("media_response", "gene_knockout", "trna_charging", "other"):
        for m in C.ELONGATION_MODES:
            d = gate.decide(_req(observable=obs, regulatory_dependencies=("phosphate_depletion",)), mode=m)
            assert d.verdict == "refuse" and KEY in d.blocking, (obs, m)
            assert d.route == "", "no elongation model represents it, so no route may be offered"


def test_a_shift_to_a_medium_that_supports_growth_is_still_answerable():
    assert gate.decide(_req(regulatory_dependencies=("nutrient_shift",)), mode="steady_state").verdict == "answer"


def test_the_parser_is_told_about_the_dependency():
    enum = gate._PARSE_TOOL["input_schema"]["properties"]["regulatory_dependencies"]["items"]["enum"]
    assert "phosphate_depletion" in enum
    assert "phosphate_depletion" in gate._PARSE_SYSTEM


def test_raw_tool_reads_of_a_phosphate_free_design_are_refused():
    for design in ("condition/minus_phosphate", "timeline/0 minimal, 2400 minimal_minus_phosphate"):
        refusal = mcp.capability_precheck("read_series", {"design": design, "channel": "growth_rate"})
        assert refusal is not None and KEY in json.dumps(refusal), design
    assert mcp.capability_precheck("read_series", {"design": "condition/minus_magnesium",
                                                   "channel": "growth_rate"}) is None


def test_the_validation_evidence_is_what_the_registry_says_it_is():
    res = json.loads((ROOT / "evals" / "results" / "phosphate_validation.json").read_text(encoding="utf-8"))["runs"]
    depleted = {k: v for k, v in res.items() if k.startswith(("A_", "B_", "K_"))}
    controls = {k: v for k, v in res.items() if k.startswith(("C_", "KC_"))}
    assert len(depleted) == 10 and len(controls) == 3
    for k, v in depleted.items():
        assert v["identity_key"] == "NegativeCountsError@wholecell/states/bulk_molecules.py:merge", k
        assert v["ran_out"][0]["molecule"] == "ATP[c]" and v["ran_out"][0]["process"] == "PolypeptideElongation"
    for k, v in controls.items():
        assert v["identity_key"] == "no_traceback", k
    assert {v["config"] for v in depleted.values()} == {"standard", "kinetic"}
