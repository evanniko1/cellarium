"""F-1: can a Council falsifier actually fire in the simulator its design runs on?

Failing to falsify (arXiv:2604.02485) shows models proposing tests that cannot refute them. The Council already
checks that a falsifier names a test the platform has (M-1, done). This checks the outcome: whether the channel the
falsifier reads is represented in the design's elongation model and condition, from the capability registry and from
two channel facts the Platform Map records. A falsifier that cannot fire is a defect the registry can catch.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in ("src", "evals"):
    sys.path.insert(0, str(REPO / p))

import falsifiers as F  # noqa: E402


def _h(channel, target="wildtype/basal", reference="wildtype/basal", mode="steady_state", condition="basal"):
    return {"falsifier": {"channel": channel, "target": target, "reference": reference},
            "candidate_designs": [{"perturbation": target.split("/")[0], "condition": condition,
                                   "elongation_model": mode}]}


def test_a_growth_falsifier_in_glucose_can_fire():
    assert F.realisability(_h("growth_rate"))["status"] == "realisable"


def test_a_ppgpp_falsifier_cannot_fire_outside_steady_state():
    r = F.realisability(_h("ppgpp_conc", mode="kinetic"))
    assert r["status"] == "unrealisable" and "ppgpp_stringent_response" in r["reason"]
    assert F.realisability(_h("rela_conc", mode="steady_state"))["status"] == "realisable"


def test_a_falsifier_in_an_unrepresented_condition_cannot_fire():
    r = F.realisability(_h("growth_rate", target="condition/minus_phosphate", condition="minus_phosphate"))
    assert r["status"] == "unrealisable" and "growth_under_phosphate_depletion" in r["reason"]
    r = F.realisability(_h("growth_rate", target="condition/glc_2mM", reference="condition/glc_20mM",
                           condition="glc_2mM"))
    assert r["status"] == "unrealisable" and "response_to_the_glucose_concentration" in r["reason"]


def test_division_rate_between_two_healthy_designs_is_insensitive():
    r = F.realisability(_h("division_rate", target="condition/acetate", condition="acetate"))
    assert r["status"] == "insensitive"


def test_a_hypothesis_without_a_falsifier_is_reported_as_such():
    assert F.realisability({"candidate_designs": []})["status"] == "no_falsifier"


def test_the_summary_counts_by_arm():
    recs = [{"config": "full", "hypothesis": _h("growth_rate")},
            {"config": "full", "hypothesis": _h("ppgpp_conc", mode="kinetic")},
            {"config": "proposer_only", "hypothesis": _h("division_rate", target="condition/acetate",
                                                         condition="acetate")}]
    s = F.summary(recs)
    assert s["full"] == {"n": 2, "realisable": 1, "unrealisable": 1, "insensitive": 0, "no_falsifier": 0}
    assert s["proposer_only"]["insensitive"] == 1
