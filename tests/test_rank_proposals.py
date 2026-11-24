"""D-1: rank the runs that could separate competing hypotheses, against the single run each proposes today.

The rank is a heuristic and says so: a run scores the number of competing hypotheses whose falsifier can fire on it
(F-1's realisability), i.e. how many of them one run tests at once. It is not information gain, which needs a
predictive model of outcomes the platform does not have, and it is unvalidated until the runs exist.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "evals"))

import rank_proposals as R  # noqa: E402


def _h(target, channel="growth_rate", reference="wildtype/basal"):
    return {"falsifier": {"target": target, "reference": reference, "channel": channel},
            "candidate_designs": [{"elongation_model": "steady_state"}]}


HYPS = [_h("gene_knockout/KO:argS"), _h("gene_knockout/KO:argS"), _h("gene_knockout/KO:leuB"),
        _h("gene_knockout/KO:argS", channel="ppgpp_conc"),
        {"falsifier": {"target": "condition/minus_phosphate", "reference": "wildtype/basal", "channel": "growth_rate"},
         "candidate_designs": []}]


def test_a_target_run_that_tests_more_hypotheses_ranks_higher():
    r = R.rank(HYPS)
    assert r["ranked"] == [{"run": "gene_knockout/KO:argS", "hypotheses": 3, "in_corpus": True},
                           {"run": "gene_knockout/KO:leuB", "hypotheses": 1, "in_corpus": True}]


def test_the_shared_reference_is_reported_apart_not_ranked_first():
    # every falsifier compares against wildtype/basal, so ranking references would put it first every time
    assert R.rank(HYPS)["shared_references"] == {"wildtype/basal": 4}


def test_an_unrealisable_falsifier_names_no_run():
    # minus_phosphate is absent in every elongation model (F-1), so that hypothesis's falsifier cannot fire
    assert "condition/minus_phosphate" not in {x["run"] for x in R.rank(HYPS)["ranked"]}
    assert R.rank(HYPS)["n_realisable"] == 4


def test_each_hypothesis_s_own_run_is_compared_with_the_top_run():
    r = R.rank(HYPS)
    # today each hypothesis proposes its own falsifier target; the leuB one tests 1 hypothesis where argS tests 3
    assert r["own_run_scores"] == [3, 3, 1, 3]
    assert r["own_run_is_top_target"] == 3


def test_the_stored_ranking_is_pinned():
    d = json.loads((REPO / "evals" / "results" / "proposal_ranking.json").read_text(encoding="utf-8"))
    assert d["n_questions"] == 10 and d["n_hypotheses"] == 210
    assert d["totals"]["n_realisable"] + d["totals"]["n_not_realisable"] == 210
    assert "not information gain" in d["what_the_score_is"]
