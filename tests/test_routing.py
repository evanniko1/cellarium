"""Auto model-routing — the up-front Haiku classifier (stubbed here; no network) with the keyword heuristic as
fallback. Explicit model choice bypasses routing entirely (handled at the server layer)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import server


# --- the fallback keyword heuristic (deterministic, no API) ---
def test_heuristic_reasoning_heavy_to_opus():
    assert server._route_heuristic("Is pfkA essential in E. coli?", False) == server._OPUS
    assert server._route_heuristic("Why does the pfkA knockout stay viable?", False) == server._OPUS
    assert server._route_heuristic("Compare rpoB and lysS and explain the difference", False) == server._OPUS


def test_heuristic_lookups_and_short_to_haiku():
    assert server._route_heuristic("list the knockouts", False) == server._HAIKU
    assert server._route_heuristic("Tell me about the platform", False) == server._HAIKU
    assert server._route_heuristic("pfkB", False) == server._HAIKU


def test_heuristic_middle_to_sonnet():
    assert server._route_heuristic("the argS knockout proteome response across generations", False) == server._SONNET


# --- route_model: classifier drives it; council short-circuits; falls back when classifier is unavailable ---
def test_route_model_uses_classifier(monkeypatch):
    monkeypatch.setattr(server, "_classify", lambda q: "hard")
    assert server.route_model("a generic question with no keywords", False) == server._OPUS
    monkeypatch.setattr(server, "_classify", lambda q: "lookup")
    assert server.route_model("a generic question with no keywords", False) == server._HAIKU
    monkeypatch.setattr(server, "_classify", lambda q: "moderate")
    assert server.route_model("a generic question with no keywords", False) == server._SONNET


def test_route_model_falls_back_to_heuristic_when_classifier_unavailable(monkeypatch):
    monkeypatch.setattr(server, "_classify", lambda q: None)
    assert server.route_model("Why does pfkA reroute glycolysis?", False) == server._OPUS   # heuristic: hard
    assert server.route_model("list the runs", False) == server._HAIKU                       # heuristic: lookup


def test_route_model_council_short_circuits_without_classifying(monkeypatch):
    def boom(q):
        raise AssertionError("classifier should not be called for a Council-framed turn")
    monkeypatch.setattr(server, "_classify", boom)
    assert server.route_model("pfkB", True) == server._OPUS
