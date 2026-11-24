"""A-1: before a new claim on a channel, reproduce a known result on the same channel with the same reader.

The withdrawn stringent-response finding (Platform Map, Appendix J) was a correct computation on runs that should not
have been read; Anthropic's enzyme-discovery agents first reproduce established results to check their methods. A
control here is a comparison whose direction is known and outside the fit (a perturbation the parameter calculation
never saw), read on the channel the claim is about, through the same function a claim would use.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from cellarium import controls  # noqa: E402


def _disconfirm(effect, p):
    return lambda target, reference, channel: {"effect_pct": effect, "welch_p": p,
                                               "target": {"n_seeds": 4}, "reference": {"n_seeds": 4}}


def test_a_control_that_reproduces_passes(monkeypatch):
    monkeypatch.setattr(controls.rigor, "disconfirm", _disconfirm(-35.0, 0.001))
    r = controls.check("growth_rate")
    assert r["passed"] is True and r["expected"] == "down" and r["observed_pct"] == -35.0


def test_a_control_in_the_wrong_direction_fails(monkeypatch):
    monkeypatch.setattr(controls.rigor, "disconfirm", _disconfirm(+12.0, 0.001))
    assert controls.check("growth_rate")["passed"] is False


def test_a_control_that_does_not_reach_significance_fails(monkeypatch):
    monkeypatch.setattr(controls.rigor, "disconfirm", _disconfirm(-35.0, 0.2))
    assert controls.check("ribosome_conc")["passed"] is False


def test_a_control_the_corpus_cannot_read_is_reported_not_passed(monkeypatch):
    monkeypatch.setattr(controls.rigor, "disconfirm", lambda *a: {"error": "no runs"})
    r = controls.check("growth_rate")
    assert r["passed"] is None and "no runs" in r["reason"]


def test_a_channel_without_a_control_says_so():
    r = controls.check("rela_conc")
    assert r["passed"] is None and "no control" in r["reason"]


def test_every_registered_control_is_a_perturbation_outside_the_fit():
    for ch, c in controls.CONTROLS.items():
        assert c["target"].split("/")[0] not in ("condition", "wildtype"), ch
        assert c["expected"] in ("up", "down") and c["anchor"], ch
