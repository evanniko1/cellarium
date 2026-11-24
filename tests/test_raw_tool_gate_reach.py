"""P-2: the raw-tool gate reaches every design and channel a tool reads, and refuses only tools that read.

Until 2026-11-24 the gate looked for a design in four argument names (`design`, `design_a`, `design_or_id`,
`target`) and for a channel in one (`channel`). The same phosphate-depleted design it refused through `design` passed
through `design_b`, `reference`, a `designs` list, a `results` list or a bare `condition`, and a ppGpp reading passed
through `x_channel`, `y_channel` or `channels`. The opposite error came with it: a tool that reads no simulated
quantity at all (listing comparable designs, checking which raw files exist, designing a panel) was refused for the
design it named. Every tool now declares whether it reads simulated quantities, and the gate keys off that.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from cellarium import mcp, tools  # noqa: E402

P = "condition/minus_phosphate"
KINETIC = "wildtype/basal#elong:kinetic"

BYPASSES = [
    ("compare_at_generation", {"design_a": "wildtype/basal", "design_b": P, "channel": "growth_rate"}),
    ("differential", {"target": "wildtype/basal", "reference": P}),
    ("fit_relation", {"designs": ["wildtype/basal", P], "x_channel": "ppgpp_conc", "y_channel": "growth_rate"}),
    ("regulon_response", {"condition": "minus_phosphate", "regulon": "PhoB"}),
    ("bimodality", {"designs": [P], "channel": "growth_rate"}),
    ("chart", {"kind": "bar", "results": [P], "channel": "growth_rate"}),
]


@pytest.mark.parametrize("name,args", BYPASSES, ids=[b[0] for b in BYPASSES])
def test_a_dead_design_is_refused_whichever_argument_carries_it(name, args):
    r = mcp.capability_precheck(name, args)
    assert r is not None and "growth_under_phosphate_depletion" in r["capabilities"], (name, args)


def test_a_channel_in_any_channel_argument_carries_its_dependency():
    for name, args in [("fit_relation", {"designs": [KINETIC], "x_channel": "ppgpp_conc", "y_channel": "growth_rate"}),
                       ("scan_overview", {"design": KINETIC, "channels": ["ppgpp_conc"]})]:
        note = mcp.capability_note(name, args)
        assert note is not None and "ppgpp_stringent_response" in note["does_not_hold"], name


def test_two_designs_in_two_modes_are_each_checked():
    # ppGpp holds in steady_state only: the kinetic design in the second slot must not be read under the first's mode
    note = mcp.capability_note("compare_at_generation", {"design_a": "wildtype/basal", "design_b": KINETIC,
                                                         "channel": "ppgpp_conc"})
    assert note is not None and "ppgpp_stringent_response" in note["does_not_hold"]
    assert "kinetic" in note["elongation_model"]


NON_READERS = [
    ("comparable_designs", {"design": P}),
    ("raw_available", {"design": P}),
    ("download_raw", {"design": P}),
    ("provenance", {"condition": "minus_phosphate"}),
    ("design_panel", {"design": P, "factors": {"gene": ["pfkA"]}}),
]


@pytest.mark.parametrize("name,args", NON_READERS, ids=[n[0] for n in NON_READERS])
def test_a_tool_that_reads_no_simulated_quantity_is_not_refused_for_the_design_it_names(name, args):
    assert mcp.capability_precheck(name, args) is None, name
    # ...and still carries the registry's sentence, so the design's scope travels with whatever it returns
    note = mcp.capability_note(name, args)
    assert note is not None and "growth_under_phosphate_depletion" in note["does_not_hold"], name


def test_a_read_of_represented_designs_still_passes():
    assert mcp.capability_precheck("differential", {"target": "wildtype/basal", "reference": "condition/with_aa"}) is None
    assert mcp.capability_precheck("fit_relation", {"designs": ["wildtype/basal", "condition/acetate"],
                                                    "x_channel": "growth_rate", "y_channel": "rna_mass"}) is None


def test_every_tool_declares_whether_it_reads_simulated_quantities():
    names = {t["name"] for t in tools.TOOLS}
    reads, not_reads = set(mcp.READS_SIMULATED_QUANTITIES), set(mcp.DOES_NOT_READ)
    assert reads | not_reads == names, sorted(names - reads - not_reads)
    assert not reads & not_reads
    # literal: the classification made on 2026-11-24, tool by tool from each description
    assert (len(reads), len(not_reads)) == (32, 42)
    assert all(isinstance(r, str) and len(r) > 10 for r in mcp.DOES_NOT_READ.values())
    # every tool with a tool-level dependency is one that reads
    assert set(mcp._TOOL_CAPABILITY) <= reads


def test_a_refusal_names_the_designs_to_drop():
    # two recorded growth-law fits over eleven conditions were refused whole for one design among them
    designs = ["wildtype/basal", "condition/acetate", "condition/no_glucose", "condition/with_aa"]
    r = mcp.capability_precheck("fit_relation", {"designs": designs, "x_channel": "growth_rate",
                                                 "y_channel": "rna_mass"})
    assert r is not None and r["designs"] == ["condition/no_glucose"]
    assert "condition/no_glucose" in r["what_you_can_do"]
    # one design read through `design` is named the same way
    assert mcp.capability_precheck("read_series", {"design": P, "channel": "growth_rate"})["designs"] == [P]


# ---- what the change costs, on the calls Cellwright actually made ----------------------------------------------

def _replay():
    import json
    return json.loads((REPO / "evals" / "results" / "raw_gate_replay.json").read_text(encoding="utf-8"))


def test_the_replayed_counts_are_the_ones_that_were_read_by_hand():
    d = _replay()
    assert (d["calls"], d["calls_to_tools_that_read"]) == (734, 400)
    assert d["refused"] == {"before": 24, "after": 33}
    assert d["changed"] == {"newly_refused": 10, "no_longer_refused": 1, "newly_noted": 0, "no_longer_noted": 0}
    assert d["refused_after_by_capability"] == {"operon_specific_rrna_knockout": 31,
                                                "growth_without_a_carbon_source": 2}
    adj = d["adjudicated"]["newly_refused"]
    assert adj["n"] == d["changed"]["newly_refused"]
    assert sum(v["n"] for k, v in adj.items() if k != "n") == adj["n"]


def test_the_recorded_calls_reproduce_the_stored_replay():
    import json
    import subprocess

    db = REPO / "data" / "sessions.db"
    if not db.is_file():
        pytest.skip("data/sessions.db is not on this machine: the replay cannot be recomputed here")
    stored = _replay()
    if subprocess.run(["git", "-C", str(REPO), "cat-file", "-e", stored["before_commit"]],
                      capture_output=True).returncode != 0:
        pytest.skip(f"commit {stored['before_commit']} is not in this clone's history")
    sys.path.insert(0, str(REPO / "evals"))
    import raw_gate_replay as R
    recorded, used = R.calls(sessions=set(stored["session_ids"]))
    assert used == stored["session_ids"]
    got = R.measure(recorded, R._before_gate())
    for key in ("calls", "calls_to_tools_that_read", "refused", "noted", "changed", "refused_after_by_capability"):
        assert got[key] == stored[key], (key, json.dumps(got[key]))
