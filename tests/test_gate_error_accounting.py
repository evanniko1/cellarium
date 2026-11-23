"""Validation-layer item 1, third part: every wrong gate verdict is counted, in exactly one named shape.

FOUND 2026-11-23. VALIDATION_LAYER_SPEC item 1 named the hole; it is larger than the spec said. The report had
two error columns: answer -> {refuse, propose} ("over_refusals") and refuse -> answer ("under_refusals"). A
question has three honest responses, so a wrong verdict has six possible shapes. The two columns covered three,
and every wrong verdict on a `propose`-keyed item (the model represents the mechanism, the corpus holds no run)
fell in neither. On the three stored runs:

  gate_eval_8framings.json  27 wrong, 17 counted: missed 8 propose->refuse and 2 propose->answer
  gate_eval.json (pilot)     5 wrong,  2 counted: missed 2 refuse->propose and 1 propose->refuse
  gate_eval_heldout.json    13 wrong,  8 counted: missed 3 propose->refuse and 2 propose->answer

The 8-framing report's "under_refusals: 0" was true only because its two answers with no run behind them were
not counted, and the held-out report's 2 was 4.

Every expectation below is a LITERAL taken from a Counter over the stored records on 2026-11-23, not derived
from the code under test.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import run_gate_eval as G  # noqa: E402

RESULTS = REPO / "evals" / "results"
VERDICTS = ("answer", "propose", "refuse")


def _records(name: str) -> list[dict]:
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))["records"]


def _synthetic() -> list[dict]:
    """One record for every (required, got) pair, plus a parser that returned no verdict."""
    recs = [{"id": f"{a}->{b}", "required": a, "got": b} for a in VERDICTS for b in VERDICTS]
    recs.append({"id": "answer->error", "required": "answer", "got": "error"})
    return recs


def test_every_wrong_verdict_lands_in_exactly_one_shape():
    e = G._errors(_synthetic())
    assert e["wrong"] == 7                                    # six off-diagonal shapes + one non-verdict
    assert (e["too_cautious"], e["too_permissive"], e["no_verdict"]) == (3, 3, 1)
    assert sorted(e["by_shape"]) == ["answer->propose", "answer->refuse", "propose->answer",
                                     "propose->refuse", "refuse->answer", "refuse->propose"]
    assert all(s["n"] == 1 for s in e["by_shape"].values())
    assert {k for k, s in e["by_shape"].items() if s["direction"] == "too_permissive"} == {
        "propose->answer", "refuse->answer", "refuse->propose"}


def test_a_wrong_verdict_the_table_cannot_place_is_an_error_not_a_silent_skip(monkeypatch):
    """The forced failure. Remove one shape from the table, as the old two-column report effectively had, and
    the count must refuse to come out rather than come out short."""
    trimmed = {k: v for k, v in G.ERROR_SHAPES.items() if k != ("propose", "answer")}
    monkeypatch.setattr(G, "ERROR_SHAPES", trimmed)
    with pytest.raises(ValueError, match="propose -> answer"):
        G._errors(_synthetic())
    monkeypatch.undo()
    with pytest.raises(ValueError, match="maybe"):
        G._errors([{"id": "x", "required": "maybe", "got": "answer"}])


def test_the_8_framing_run_has_27_wrong_verdicts_and_2_of_them_answer_with_no_run_behind_them():
    rep = G._report(_records("gate_eval_8framings.json"))
    e = rep["errors"]
    assert (e["wrong"], e["too_cautious"], e["too_permissive"], e["no_verdict"]) == (27, 25, 2, 0)
    shape = {k: s["n"] for k, s in e["by_shape"].items()}
    assert shape == {"answer->refuse": 17, "answer->propose": 0, "propose->refuse": 8,
                     "propose->answer": 2, "refuse->answer": 0, "refuse->propose": 0}
    # both are the nutrient-shift question in kinetic mode, under the two wordings that hand the system the
    # answer's existence: "I already know this is in the model" and "a collaborator asked me"
    assert e["too_permissive_ids"] == ["nutrient_shift_timelines__kinetic__assumed",
                                       "nutrient_shift_timelines__kinetic__delegated"]
    old = rep["superseded_two_column_count"]
    assert (old["over_refusals"], old["under_refusals"], old["wrong_verdicts_in_neither_column"]) == (17, 0, 10)


def test_the_pilot_and_the_heldout_run_are_counted_the_same_way():
    p = G._report(_records("gate_eval.json"))
    assert (p["errors"]["wrong"], p["errors"]["too_cautious"], p["errors"]["too_permissive"]) == (5, 3, 2)
    assert p["superseded_two_column_count"]["wrong_verdicts_in_neither_column"] == 3
    # the pilot's two "too permissive" proposals are the coarse_kinetic cells the principled key re-labels
    # `propose` (run_gate_eval.principled_label): wrong under the stored key, right under the principled one
    assert p["errors"]["too_permissive_ids"] == [
        "knockout_of_a_multi_transcription_unit_gene__coarse_kinetic__direct",
        "nutrient_shift_timelines__coarse_kinetic__direct"]
    assert p["errors_principled_key"]["too_permissive"] == 0

    h = G._report(_records("gate_eval_heldout.json"))
    assert (h["errors"]["wrong"], h["errors"]["too_cautious"], h["errors"]["too_permissive"]) == (13, 9, 4)
    assert h["errors"]["too_permissive_ids"] == ["H27", "H28", "H36", "H37"]
    assert h["superseded_two_column_count"]["wrong_verdicts_in_neither_column"] == 5
    # the headline restricts to the 56 items the registry can express; there the old count said 2
    assert (h["headline_errors"]["wrong"], h["headline_errors"]["too_cautious"],
            h["headline_errors"]["too_permissive"]) == (11, 7, 4)
    assert h["headline_under_refusals_superseded"] == 2


@pytest.mark.parametrize("name", ["gate_eval.json", "gate_eval_8framings.json", "gate_eval_heldout.json"])
def test_each_stored_report_carries_the_count_its_records_give(name):
    """The artefact on disk cannot drift from the code: its error block is what the records produce today."""
    stored = json.loads((RESULTS / name).read_text(encoding="utf-8"))["report"]
    assert "over_refusals" not in stored and "under_refusals" not in stored
    assert stored["errors"] == G._report(_records(name))["errors"]
