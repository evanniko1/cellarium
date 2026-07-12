"""Auto model-routing — the zero-cost per-turn heuristic. Explicit model choice bypasses this entirely (tested
at the server layer); here we pin down the routing decision itself."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import server


def test_reasoning_heavy_questions_route_to_opus():
    assert server.route_model("Is pfkA essential in E. coli?", False) == server._OPUS
    assert server.route_model("Why does the pfkA knockout stay viable?", False) == server._OPUS
    assert server.route_model("Compare rpoB and lysS and explain the difference", False) == server._OPUS


def test_lookups_and_short_asks_route_to_haiku():
    assert server.route_model("list the knockouts", False) == server._HAIKU
    assert server.route_model("Tell me about the platform", False) == server._HAIKU
    assert server.route_model("pfkB", False) == server._HAIKU          # very short ask


def test_council_framed_investigation_forces_opus():
    assert server.route_model("pfkB", True) == server._OPUS            # Council signal overrides the short default


def test_middle_questions_default_to_sonnet():
    assert server.route_model("the argS knockout proteome response across generations", False) == server._SONNET
