"""DD-MTH-3: the temperature-sweep's pure metric layer (diversity + per-temperature summary). The live run needs
API keys, but the metric that CHOOSES the operating point is deterministic and unit-tested here."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "evals"))

import temperature_sweep as ts  # noqa: E402


def _hyp(claim, channel, observable, direction="up"):
    return {"claim": claim, "falsifier": {"channel": channel},
            "operational_defs": [{"observable": observable}], "predicted_effect": direction}


def test_diversity_zero_when_replicates_identical():
    same = [_hyp("pfkA slows growth", "growth_rate", "growth_rate") for _ in range(3)]
    d = ts.diversity(same)
    assert d["n"] == 3 and d["distinct_operationalizations"] == round(1 / 3, 3)   # 1 distinct / 3 reps
    assert d["claim_pairwise_distance"] == 0.0                                     # identical claims -> no distance


def test_diversity_high_when_replicates_differ():
    varied = [_hyp("pfkA slows growth via glycolysis", "growth_rate", "growth_rate"),
              _hyp("pfkA shifts ribosome content", "ribosome_conc", "ribosome_conc"),
              _hyp("pfkA raises ppGpp stringently", "ppgpp_conc", "ppgpp_conc")]
    d = ts.diversity(varied)
    assert d["distinct_operationalizations"] == 1.0        # every rep a distinct operationalization
    assert d["claim_pairwise_distance"] > 0.5              # claims genuinely differ


def test_diversity_needs_two():
    d = ts.diversity([_hyp("x", "growth_rate", "growth_rate")])
    assert d["n"] == 1 and d["distinct_operationalizations"] is None


def test_summarize_rolls_up_quality_convergence_and_diversity():
    results = [
        {"id": "c1", "temperature": 0.0, "converged": True, "claude": {"score": 5},
         "hypothesis": _hyp("a", "growth_rate", "growth_rate")},
        {"id": "c1", "temperature": 0.0, "converged": True, "claude": {"score": 5},
         "hypothesis": _hyp("a", "growth_rate", "growth_rate")},           # identical -> low diversity at T=0
        {"id": "c1", "temperature": 1.0, "converged": False, "claude": {"score": 4},
         "hypothesis": _hyp("a via glycolysis", "growth_rate", "growth_rate")},
        {"id": "c1", "temperature": 1.0, "converged": True, "claude": {"score": 6},
         "hypothesis": _hyp("b via ribosomes", "ribosome_conc", "ribosome_conc")},   # differs -> high diversity at T=1
        {"id": "c2", "temperature": 1.0, "error": "boom"},                 # errors excluded
    ]
    s = ts.summarize(results, [0.0, 1.0])
    assert s["0.0"]["mean_quality_6"] == 5.0 and s["0.0"]["convergence_rate"] == 1.0
    assert s["0.0"]["mean_distinct_operationalizations"] == 0.5           # 1 distinct / 2 reps
    assert s["1.0"]["n_runs"] == 2 and s["1.0"]["mean_distinct_operationalizations"] == 1.0   # both distinct
    assert s["1.0"]["mean_claim_diversity"] > 0.0
