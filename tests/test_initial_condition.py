"""A knockout in a fitted non-glucose condition (BV-12): `initial_condition` sets the cell's fitted physiology and the
timeline sets the medium, so `gene_knockout` + initial_condition 'acetate' + "0 minimal_acetate" is a knockout in
steady-state acetate, not a glucose-fitted cell thrown into acetate (which the envelope refuses, rightly)."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from cellarium import envelope, runner  # noqa: E402
from cellarium.generate import Design  # noqa: E402


def _ko(**params):
    return Design(perturbation="gene_knockout", condition="KO:fbp", timeline="0 minimal_acetate",
                  params={"variant_index": 2232, **params})


def test_the_initial_condition_reaches_the_simulator():
    args = runner._variant_args(_ko(initial_condition="acetate"))
    i = args.index("--initial-condition")
    assert args[i + 1] == "acetate" and args[:4] == ["--variant", "gene_knockout", "2232", "2232"]
    assert "--timeline" in args


def test_a_design_without_one_emits_no_flag():
    plain = Design(perturbation="gene_knockout", condition="KO:fbp", params={"variant_index": 2232})
    assert "--initial-condition" not in runner._variant_args(plain)
    assert runner._dir_discriminator(plain) == ""          # every existing run path stays byte-identical


def test_the_same_knockout_and_timeline_with_and_without_the_physiology_never_share_a_directory():
    a, b = _ko(initial_condition="acetate"), _ko()
    assert runner._run_subpath(a, 0, "cellarium") != runner._run_subpath(b, 0, "cellarium")
    assert runner._dir_discriminator(a).endswith("__icacetate")


def test_a_knockout_in_fitted_acetate_is_inside_the_envelope():
    v = envelope.check(_ko(initial_condition="acetate"))
    assert v.in_envelope, v.reason


def test_without_the_physiology_the_same_timeline_is_still_a_refused_switch():
    v = envelope.check(_ko())
    assert not v.in_envelope and "carbon source" in v.reason


def test_a_physiology_that_does_not_match_the_medium_is_a_switch():
    # acetate-fitted cell put into succinate at t=0 is a carbon switch like any other
    d = Design(perturbation="gene_knockout", condition="KO:fbp", timeline="0 minimal_succinate",
               params={"variant_index": 2232, "initial_condition": "acetate"})
    v = envelope.check(d)
    assert not v.in_envelope and "carbon source" in v.reason


def test_an_unknown_initial_condition_is_refused():
    v = envelope.check(_ko(initial_condition="acetate_typo"))
    assert not v.in_envelope and "initial condition" in v.reason
