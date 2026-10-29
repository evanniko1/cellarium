"""The agent-facing wiring of the screening and space-filling generators.

A generator that only `doe.py` can reach is a library, not a capability: Cellwright plans panels through
`design_panel`, so until the designs appear there the agent's only reduced panel is still the random
subsample. These tests pin the two halves that make the difference reachable — the tool accepts the design
names, and the schema DECLARES them, so the model is not asked to guess a member of a closed set.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cellarium import tools  # noqa: E402


def _schema(name: str) -> dict:
    return next(t for t in tools.TOOLS if t["name"] == name)["input_schema"]


# --- design_panel ------------------------------------------------------------------------------------

def test_design_panel_runs_a_fractional_design(monkeypatch):
    monkeypatch.setattr(tools, "power_check", lambda **kw: {"observed_replicate_cv": 0.04})
    out = tools.design_panel(factors={n: ["lo", "hi"] for n in "ABCDEF"}, design="fractional", runs=16,
                             seeds=4)
    assert out["n_cells"] == 16 and out["n_full_factorial"] == 64
    assert out["resolution"] == 4 and out["main_effects_clear"] is True
    assert out["total_sims"] == 64 and out["power"]["observed_replicate_cv"] == 0.04
    assert "aliases" in out and "defining_relation" in out


def test_design_panel_runs_a_plackett_burman_screen(monkeypatch):
    monkeypatch.setattr(tools, "power_check", lambda **kw: {"observed_replicate_cv": 0.04})
    out = tools.design_panel(factors={f"f{i}": [0, 1] for i in range(11)}, design="plackett_burman", seeds=2)
    assert out["n_cells"] == 12 and out["resolution"] == 3 and out["main_effects_clear"] is False


def test_design_panel_fractional_without_runs_explains_itself(monkeypatch):
    monkeypatch.setattr(tools, "power_check", lambda **kw: {"observed_replicate_cv": 0.04})
    out = tools.design_panel(factors={n: ["lo", "hi"] for n in "ABCD"}, design="fractional")
    assert "error" in out and "runs" in out["error"]


def test_design_panel_rejects_an_undeclared_design(monkeypatch):
    monkeypatch.setattr(tools, "power_check", lambda **kw: {"observed_replicate_cv": 0.04})
    out = tools.design_panel(factors={"gene": ["a", "b"]}, design="latin_hypercube")
    assert "error" in out and "surface_panel" in out["error"]


def test_design_panel_carries_the_split_plot_penalty(monkeypatch):
    monkeypatch.setattr(tools, "power_check", lambda **kw: {"observed_replicate_cv": 0.04})
    out = tools.design_panel(factors={"anchor": ["none", "0.55", "0.85"], "gene": ["argS", "hisS"]},
                             seeds=8, whole_plot="anchor")
    assert out["power"]["whole_plot"]["n_whole_plots"] == 3
    assert out["power"]["whole_plot"]["mde_pct_at_n_whole_plots"] > out["power"]["mde_pct_at_n"]


def test_design_panel_default_path_is_unchanged(monkeypatch):
    """The regression guard: the tool's old call shape must behave exactly as before."""
    monkeypatch.setattr(tools, "power_check", lambda **kw: {"observed_replicate_cv": 0.04})
    out = tools.design_panel(factors={"gene": ["pfkA", "pfkB"]}, channel="growth_rate", seeds=4,
                             effect_pct=10.0)
    assert out["n_cells"] == 2 and out["power_channel"] == "growth_rate" and out["total_sims"] == 8
    assert out["design"] == "full"


# --- surface_panel -----------------------------------------------------------------------------------

def test_surface_panel_tool_builds_a_latin_hypercube(monkeypatch):
    monkeypatch.setattr(tools, "power_check", lambda **kw: {"observed_replicate_cv": 0.04})
    out = tools.surface_panel(ranges={"anchor": [0.55, 0.85]}, design="latin_hypercube", n=10, seeds=4)
    assert out["n_points"] == 10 and out["total_sims"] == 40
    assert all(0.55 <= p["anchor"] <= 0.85 for p in out["points"])
    assert out["refuses"]


def test_surface_panel_tool_builds_a_central_composite(monkeypatch):
    monkeypatch.setattr(tools, "power_check", lambda **kw: {"observed_replicate_cv": 0.04})
    out = tools.surface_panel(ranges={"a": [0.0, 1.0], "b": [0.0, 1.0]}, design="central_composite",
                              alpha="face", center=2, seeds=2)
    assert out["n_points"] == 10 and out["legal"] is True and out["out_of_range"] == []


def test_surface_panel_tool_reports_an_out_of_range_rotatable_design(monkeypatch):
    monkeypatch.setattr(tools, "power_check", lambda **kw: {"observed_replicate_cv": 0.04})
    out = tools.surface_panel(ranges={"anchor": [0.55, 0.85]}, design="central_composite",
                              alpha="rotatable")
    assert out["legal"] is False and out["out_of_range"]


def test_surface_panel_tool_rejects_bad_input():
    assert "error" in tools.surface_panel(ranges={})
    assert "error" in tools.surface_panel(ranges={"a": [0.0, 1.0]}, design="fractional")
    assert "error" in tools.surface_panel(ranges={"a": [1.0, 1.0]})


# --- the declared surface ----------------------------------------------------------------------------

def test_both_tools_are_dispatchable():
    assert "design_panel" in tools._DISPATCH and "surface_panel" in tools._DISPATCH
    assert any(t["name"] == "surface_panel" for t in tools.TOOLS)


def test_the_design_parameter_is_declared_as_an_enum_not_a_free_string():
    """ENUM-3: the value set is closed and known in code, so the model must not be asked to guess it."""
    props = _schema("design_panel")["properties"]
    assert set(props["design"]["enum"]) == {"full", "random_screen", "fractional", "plackett_burman"}
    surface = _schema("surface_panel")["properties"]
    assert set(surface["design"]["enum"]) == {"latin_hypercube", "central_composite"}


def test_the_enum_matches_what_the_implementation_accepts():
    """An enum narrower than the implementation silently forbids valid calls; wider invites a crash."""
    from cellarium import doe
    assert set(_schema("design_panel")["properties"]["design"]["enum"]) == set(doe._PANEL_DESIGNS)
    assert set(_schema("surface_panel")["properties"]["design"]["enum"]) == set(doe._SURFACE_DESIGNS)


def test_every_new_parameter_carries_a_description():
    for name in ("design_panel", "surface_panel"):
        for pname, prop in _schema(name)["properties"].items():
            assert prop.get("description"), f"{name}.{pname} has no description"
