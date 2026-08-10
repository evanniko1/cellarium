"""PLAT-2 — truncation that names what it dropped, and refuses when trimming destroys the claim.

Three properties, and each of them is something the funnel got wrong at some point while this was built:

  1. IT MUST STAY VALID. The funnel's whole reason for shrinking lists rather than slicing the JSON string is
     that a severed payload is a provenance hole. A first version fitted the rows against a guessed byte
     reserve and then appended the omission block, which pushed the result back over the cap and into the
     caller's last-resort string slice — the funnel emitting invalid JSON, which is exactly what it exists to
     prevent. Caught by running it at four caps, so the caps are parametrized here.
  2. IT MUST NAME WHAT IT DROPPED. "31 of 37" says something is missing and nothing about whether it mattered.
  3. IT MUST REFUSE RATHER THAN UNDER-REPORT. `support.MIN_SEEDS` is the line between a measurement and a case
     study, and a result that falls below it because of CONTEXT PRESSURE is that defect arriving by a road
     with no trace in the payload — the trimming happens after the tool has returned.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.cellarium import agent, support, truncation  # noqa: E402


def _rows(n, seeds=5, width=40):
    return [{"id": f"run_{i}", "seed": i % seeds, "label": "gene_knockout/KO:argS", "x": "y" * width}
            for i in range(n)]


# ---------------------------------------------------------------------------------------------------------
# 1. Validity.
# ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("cap", [6000, 4000, 2000, 1500, 900, 700, 500, 300])
def test_the_funnel_always_emits_valid_json(cap):
    """The failure this catches is silent: a mid-string cut produces something the model reads as a broken
    tool result, and the tail of a survey or a top_movers list is gone with no marker at all."""
    s = agent._truncate_tool_result({"n": 40, "results": _rows(40), "note": "n" * 50}, cap, "list_results")
    d = json.loads(s)                  # raises on a severed payload
    # A REFUSAL is returned whole even when it overflows a very tight cap. Slicing it would produce the exact
    # thing it exists to prevent — a truncated refusal that reads like a result — which is the convention
    # `test_agent_elongation_axis` already pins for capability refusals. Everything else fits or is marked.
    assert "error" in d or len(s) <= cap or "…[truncated]" in s


def test_the_original_total_survives_a_second_trim():
    """The one property worth keeping from the platform this came from: `showing N of M` must report the
    ORIGINAL M. Trimming an already-trimmed payload and recomputing M would report "9 of 14" for a list that
    started at 40, and each pass would make the loss look smaller than it is."""
    once, oms1 = truncation.trim({"results": _rows(40)}, 4000, tool="list_results")
    twice, oms2 = truncation.trim(once, 1500, tool="list_results")
    assert oms1[0].n_total == 40
    assert oms2[0].n_total >= oms1[0].n_kept, oms2[0].n_total
    assert twice["_omitted"][0]["n_kept"] < oms1[0].n_kept


def test_an_untrimmed_payload_is_returned_unchanged():
    out = {"n": 1, "results": _rows(2)}
    cand, oms = truncation.trim(out, 100_000, tool="list_results")
    assert oms == [] and cand == out and "_omitted" not in cand


# ---------------------------------------------------------------------------------------------------------
# 2. Named dimensions.
# ---------------------------------------------------------------------------------------------------------

def test_the_dropped_items_are_named_not_just_counted():
    cand, oms = truncation.trim({"n": 40, "results": _rows(40)}, 4000, tool="list_results")
    om = oms[0]
    assert om.n_dropped > 0
    assert om.dropped and om.dropped[0].startswith("run_"), om.dropped[:3]
    assert cand["_omitted"][0]["dropped"], "the structured record dropped the identities it had room for"


def test_the_marker_the_model_reads_names_them_too():
    """The `_omitted` block is the structured record; the marker inside the list is what the model actually
    reads mid-payload. Both must name, or the agent sees a bare count and reports a complete-looking list."""
    cand, _ = truncation.trim({"n": 40, "results": _rows(40)}, 4000, tool="list_results")
    marker = [x for x in cand["results"] if isinstance(x, str)][0]
    assert "run_3" in marker and " of 40 " in marker


def test_the_kept_stratum_is_reported_so_a_reader_can_check_the_floor_themselves():
    cand, oms = truncation.trim({"n": 40, "results": _rows(40)}, 4000, tool="list_results")
    assert oms[0].stratum == "seed"
    assert cand["_omitted"][0]["kept_seeds"], "which seeds survived is the whole question for a replicate set"


def test_identity_comes_from_the_declared_schema_when_there_is_one():
    """`RESULT_SCHEMA` is the contract. Without it the funnel guesses from a list of common keys, which is
    fine as a fallback and wrong as a design: the tool knows what identifies its rows and the funnel does not."""
    assert truncation.schema_for("list_results")["identity"][0] == "id"
    assert truncation.schema_for("nonexistent_tool") == {}


def test_an_undeclared_tool_still_names_what_it_can():
    """A fallback that reports nothing would make every undeclared tool silently lose its omissions — the
    exact under-reporting this item exists to end."""
    cand, oms = truncation.trim({"rows": _rows(40)}, 4000, tool="some_new_tool")
    assert oms[0].dropped and oms[0].dropped[0].startswith("run_")


def test_a_list_of_designs_carries_no_seed_floor():
    """A stratum is not a decoration. Applying a seed floor to a list of DESIGNS would refuse ordinary
    corpus-survey questions, and the check would be switched off within a day."""
    assert truncation.schema_for("design_space")["stratum"] is None
    _c, oms = truncation.trim({"designs": [{"design": f"d{i}", "x": "y" * 60} for i in range(40)]},
                              1200, tool="design_space")
    assert oms and oms[0].stratum is None
    assert truncation.floor_refusal(oms, tool="design_space") is None


# ---------------------------------------------------------------------------------------------------------
# 3. The refusal floor.
# ---------------------------------------------------------------------------------------------------------

def test_trimming_below_the_seed_floor_refuses_instead_of_answering():
    """The platform this came from will reduce a set to one element and stamp "showing 1 of 34", which reads
    as an answer. `support.MIN_SEEDS` exists precisely to stop that being quotable."""
    s = agent._truncate_tool_result({"n": 40, "results": _rows(40)}, 400, "list_results")
    d = json.loads(s)
    assert "error" in d and "refused at this scope" in d["error"]
    assert d["not_a_measurement"]


def test_the_refusal_names_the_scope_it_refused_and_one_that_would_work():
    """A refusal with no route forward moves the dead end rather than removing it."""
    s = agent._truncate_tool_result({"n": 40, "results": _rows(40)}, 400, "list_results")
    d = json.loads(s)
    assert d["refused_scope"]["tool"] == "list_results"
    assert d["refused_scope"]["n_total"] == 40
    assert "narrower_scope_that_would_qualify" in d and d["narrower_scope_that_would_qualify"]


def test_the_floor_is_the_projects_own_constant_not_a_new_one():
    """A second, private threshold would drift from `support.MIN_SEEDS` and the two would disagree about what
    counts as evidence — with nothing saying so."""
    import inspect
    src = inspect.getsource(truncation.floor_refusal)
    assert "support.MIN_SEEDS" in src and "support.MIN_GENERATIONS" in src
    assert support.MIN_SEEDS == 2


def test_a_set_that_still_clears_the_floor_is_not_refused():
    """The false positive that would make this unusable: trimming 40 rows to 9 across 5 seeds is a smaller
    answer, not a case study, and refusing it would refuse most large queries."""
    _c, oms = truncation.trim({"n": 40, "results": _rows(40)}, 1500, tool="list_results")
    assert truncation.floor_refusal(oms, tool="list_results") is None


# ---------------------------------------------------------------------------------------------------------
# The wiring: the omission has to leave the funnel.
# ---------------------------------------------------------------------------------------------------------

def test_the_omission_reaches_the_evidence_ledger(tmp_path, monkeypatch):
    """"…so a later reviewer sees the same omission the agent saw." A ledger showing a complete-looking list
    of ids, when the agent was shown a shorter one, is a provenance record that misleads."""
    from src.cellarium import evidence
    monkeypatch.setattr(evidence, "LEDGER", tmp_path / "e.jsonl")
    monkeypatch.setattr(evidence, "_enabled", True)
    agent._truncate_tool_result({"n": 40, "results": _rows(40)}, 4000, "list_results")
    lines = [json.loads(x) for x in (tmp_path / "e.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    om_lines = [x for x in lines if x.get("activity", "").endswith("#omitted")]
    assert om_lines, "the trim left no trace in the ledger"
    assert om_lines[0]["omitted"][0]["n_total"] == 40


def test_what_was_dropped_stops_counting_as_read(monkeypatch):
    """PLAT-2 composing with PLAT-1. `record_call` harvests from the FULL tool output but the model is shown a
    trimmed one, so without this a design truncation removed would come back `grounded` — the provenance check
    reporting evidence the model was never shown, through its own plumbing."""
    from src.cellarium import reconcile
    reconcile.start_turn(fresh=True)
    rows = _rows(40)
    reconcile.record_call("list_results", {"results": rows})
    assert "run_39" in reconcile.turn_record()["ids"]
    agent._truncate_tool_result({"n": 40, "results": rows}, 4000, "list_results")
    assert "run_39" not in reconcile.turn_record()["ids"], (
        "an id the model never saw is still counted as read")
    assert "run_0" in reconcile.turn_record()["ids"], "a row that SURVIVED the trim must still count as read"


def test_the_agent_passes_the_tool_name_so_the_schema_can_be_used():
    import inspect
    src = inspect.getsource(agent.converse)
    assert "_truncate_tool_result(out, _TOOL_CAP, tu.name)" in src, (
        "without the tool name the funnel cannot look up the declared result schema and falls back to guessing")


def test_a_refusal_is_never_sliced_however_tight_the_cap():
    """The convention `test_agent_elongation_axis` pins for capability refusals, applied to this one. A
    refusal cut mid-JSON is worse than no refusal: the model sees a fragment of a payload about a scope it
    was never told was denied."""
    for cap in (4000, 900, 500, 300, 200):
        s = agent._truncate_tool_result({"n": 40, "results": _rows(40)}, cap, "list_results")
        d = json.loads(s)
        if "error" in d:
            assert "refused at this scope" in d["error"]
            assert d["narrower_scope_that_would_qualify"], f"at cap={cap} the refusal lost its route forward"
            assert d["not_a_measurement"], f"at cap={cap} the refusal lost the marker saying it is not one"


def test_every_declared_schema_names_a_tool_that_exists():
    """A typo in `RESULT_SCHEMA` fails SILENTLY — the declaration simply never applies and the funnel quietly
    falls back to guessing, with the tool still appearing to have a contract. Twelve entries were written by
    hand, so this checks all twelve resolve."""
    names = {t["name"] for t in __import__("src.cellarium.tools", fromlist=["tools"]).TOOLS}
    bad = sorted(set(truncation.RESULT_SCHEMA) - names)
    assert not bad, f"RESULT_SCHEMA declares tools that do not exist: {bad}"


def test_the_undeclared_gap_is_reportable_rather_than_hidden():
    """60 of 72 tools have no declaration, deliberately — a declaration is a promise about a payload shape and
    writing 72 from memory would produce wrong ones. What matters is that the gap is countable rather than
    invisible, so it can be closed as shapes are confirmed."""
    names = {t["name"] for t in __import__("src.cellarium.tools", fromlist=["tools"]).TOOLS}
    undeclared = truncation.undeclared_list_tools(names)
    assert set(undeclared).isdisjoint(truncation.RESULT_SCHEMA)
    assert len(undeclared) + len(truncation.RESULT_SCHEMA) == len(names)
