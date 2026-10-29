"""`design_panel` checks every generated cell against the validated envelope.

Appendix G stated this as rule 1 and then as a gap: the legality predicate was a parameter of `doe.panel`
and the tool did not pass the envelope into it, because turning a factor cell into a `Design` needs a
convention that did not exist. This is that convention and its guard.

The one thing that must not happen is a VACUOUS green. `envelope.check` passes a bare
`Design(perturbation="wildtype")`, so a panel whose perturbation nobody determined would be checked as a
wild type, pass every cell, and report `envelope_checked: True`. That is a check that cannot fail — the
shape this project calls decoration — and it is worse than no check, because the output now carries a
guarantee it did not earn. So the tool refuses to check rather than checking the wrong design, and says
which.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cellarium import tools  # noqa: E402
from cellarium.model import Design  # noqa: E402


def _pc(monkeypatch):
    monkeypatch.setattr(tools, "power_check", lambda **kw: {"observed_replicate_cv": 0.04})


# --- the convention ----------------------------------------------------------------------------------

def test_the_mappable_fields_are_derived_from_the_model_not_listed_here():
    """A field added to `Design` becomes mappable without an edit to the panel, which is the point of
    deriving it. `params` is excluded because it is the destination for everything else."""
    assert tools._DESIGN_FIELDS == set(Design.model_fields) - {"params"}
    assert "perturbation" in tools._DESIGN_FIELDS and "params" not in tools._DESIGN_FIELDS


def test_a_cell_maps_onto_design_fields_by_name_and_everything_else_into_params():
    d = tools._design_from_cell({"condition": "acetate", "gene": "pfkA"},
                                {"perturbation": "gene_knockout", "generations": 3})
    assert isinstance(d, Design)
    assert d.perturbation == "gene_knockout" and d.condition == "acetate" and d.generations == 3
    assert d.params == {"gene": "pfkA"}


def test_the_panel_reports_which_factor_went_where(monkeypatch):
    _pc(monkeypatch)
    out = tools.design_panel(factors={"condition": ["basal", "acetate"], "gene": ["pfkA", "pfkB"]},
                             base={"perturbation": "gene_knockout"})
    m = out["design_mapping"]
    assert m["fields"] == {"condition": "condition"} and m["params"] == ["gene"]
    # A mis-spelled field name lands in params rather than being guessed at, and the caller can see it did.
    out2 = tools.design_panel(factors={"conditon": ["basal", "acetate"]},
                              base={"perturbation": "condition"})
    assert out2["design_mapping"]["params"] == ["conditon"]


def test_base_is_refused_when_it_names_something_the_model_has_no_field_for(monkeypatch):
    _pc(monkeypatch)
    out = tools.design_panel(factors={"condition": ["basal"]}, base={"perturbation": "condition", "gnee": "x"})
    assert "error" in out and "gnee" in out["error"]


# --- the check, where it can run ---------------------------------------------------------------------

def test_every_cell_legal_is_reported_as_checked_and_empty(monkeypatch):
    _pc(monkeypatch)
    out = tools.design_panel(factors={"condition": ["basal", "acetate"]},
                             base={"perturbation": "condition"})
    assert out["envelope_checked"] is True
    assert out["illegal_cells"] == [] and out["n_cells"] == 2


def test_a_carbon_switching_timeline_cell_is_dropped_with_the_envelope_s_own_reason(monkeypatch):
    _pc(monkeypatch)
    out = tools.design_panel(
        factors={"timeline": ["0 minimal, 1800 minimal_plus_amino_acids",
                              "0 minimal, 1800 minimal_acetate"]},
        base={"perturbation": "timeline"})
    assert out["envelope_checked"] is True
    assert out["n_cells"] == 1 and out["n_full_factorial"] == 2
    assert len(out["illegal_cells"]) == 1
    dropped = out["illegal_cells"][0]
    assert dropped["cell"]["timeline"].endswith("minimal_acetate")
    assert "carbon source" in dropped["reason"]
    assert dropped["suggestion"]                     # the envelope's route out travels with the refusal
    assert all(c != dropped["cell"] for c in out["run_order"])


def test_an_invented_medium_in_a_generated_cell_is_dropped(monkeypatch):
    """The failure this is really for: a generator picks a corner nobody looked at, and an invented medium
    reaches the simulator verbatim and dies at the shift, leaving a truncated run that looks like data."""
    _pc(monkeypatch)
    out = tools.design_panel(factors={"timeline": ["0 minimal, 1800 rich_EZ_aa"]},
                             base={"perturbation": "timeline"})
    assert out["n_cells"] == 0 and len(out["illegal_cells"]) == 1
    assert "not a medium this model has" in out["illegal_cells"][0]["reason"]
    assert "error" in out                            # a panel with nothing left says so


def test_a_cell_that_cannot_even_be_built_as_a_design_is_reported_not_raised(monkeypatch):
    """`Design` REJECTS an unknown elongation model by raising. A generated cell carrying one must come back
    as an illegal cell with that message, not as a traceback that loses the whole panel."""
    _pc(monkeypatch)
    out = tools.design_panel(factors={"elongation_model": ["steady_state", "kinnetic"]},
                             base={"perturbation": "wildtype"})
    assert out["n_cells"] == 1 and len(out["illegal_cells"]) == 1
    bad = out["illegal_cells"][0]
    assert bad["cell"]["elongation_model"] == "kinnetic"
    assert "elongation_model" in bad["reason"]


def test_the_check_composes_with_a_reduced_design(monkeypatch):
    """A fractional design is where this matters most, because its corners were chosen by the generator."""
    _pc(monkeypatch)
    out = tools.design_panel(
        factors={"condition": ["basal", "acetate"], "a": [0, 1], "b": [0, 1], "c": [0, 1], "d": [0, 1]},
        design="fractional", runs=8, base={"perturbation": "condition"})
    assert out["envelope_checked"] is True and out["n_cells"] == 8
    assert out["resolution"] == 3 and out["illegal_cells"] == []


# --- the refusal to check, which is the load-bearing half ---------------------------------------------

def test_an_undetermined_perturbation_is_NOT_checked_as_a_wildtype(monkeypatch):
    """The vacuous-green guard. A bare wildtype passes the envelope, so checking one would green-light every
    cell of a panel whose real perturbation nobody stated."""
    _pc(monkeypatch)
    out = tools.design_panel(factors={"gene": ["pfkA", "pfkB"]})
    assert out["envelope_checked"] is False
    assert "perturbation" in out["envelope_note"]
    assert out["illegal_cells"] == [] and out["n_cells"] == 2        # the panel is still returned
    # And the claim is absent rather than false: nothing in the output says these cells are in-envelope.
    assert "in_envelope" not in out


def test_a_perturbation_supplied_as_a_factor_is_enough_to_check(monkeypatch):
    _pc(monkeypatch)
    out = tools.design_panel(factors={"perturbation": ["condition", "not_a_variant"]})
    assert out["envelope_checked"] is True
    assert out["n_cells"] == 1 and len(out["illegal_cells"]) == 1
    assert "not a validated model variant" in out["illegal_cells"][0]["reason"]


def test_opting_out_says_so_rather_than_omitting_the_field(monkeypatch):
    _pc(monkeypatch)
    out = tools.design_panel(factors={"condition": ["basal"]}, base={"perturbation": "condition"},
                             check_envelope=False)
    assert out["envelope_checked"] is False and "not requested" in out["envelope_note"]
    assert out["illegal_cells"] == []


def test_the_envelope_fields_are_on_the_surface_panel_too(monkeypatch):
    """A continuous panel's points are coordinates, not design cells, so there is nothing to map them onto.
    It must say that rather than leaving the reader to assume a check happened."""
    _pc(monkeypatch)
    out = tools.surface_panel(ranges={"anchor": [0.55, 0.85]}, n=5)
    assert out["envelope_checked"] is False and out["envelope_note"]


def test_the_declared_parameters_are_described_and_the_schema_knows_them():
    props = next(t for t in tools.TOOLS if t["name"] == "design_panel")["input_schema"]["properties"]
    assert "base" in props and "check_envelope" in props
    for name, p in props.items():
        assert p.get("description"), name
