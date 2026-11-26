"""BV-14d: which runs count. A run is discarded, with its reasons, when it failed QC or left a generation undivided,
when a clamped factor's promoters were not bound at the set fraction, or (fit-clamp arms) when it grew outside
1.5-fold of its condition's fitted rate. Discarded runs are listed in the result and never averaged."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "evals"))

import bv14d_clamp as D  # noqa: E402

TARGETS = {"FNR-4FE-4S-CPLX": 0.781, "PHOSPHO-NARL": 0.877}
GOOD = {"qc": "ok", "divided": True, "growth_per_s": 1.3e-4,
        "bound_fraction": {"FNR-4FE-4S-CPLX": 0.779, "PHOSPHO-NARL": 0.86}}


def test_a_clean_run_whose_clamp_held_is_kept():
    assert D.validity(GOOD, TARGETS, growth_range=(9.4e-5, 2.1e-4)) == []


def test_each_defect_discards_the_run_and_says_why():
    bad = [({**GOOD, "qc": "crashed"}, "QC"),
           ({**GOOD, "divided": False}, "divide"),
           ({**GOOD, "bound_fraction": {**GOOD["bound_fraction"], "PHOSPHO-NARL": 0.70}}, "PHOSPHO-NARL"),
           ({**GOOD, "bound_fraction": {"FNR-4FE-4S-CPLX": 0.779}}, "unread"),
           ({**GOOD, "growth_per_s": 6.0e-5}, "growth"),
           ({**GOOD, "growth_per_s": None}, "growth")]
    for run, word in bad:
        why = D.validity(run, TARGETS, growth_range=(9.4e-5, 2.1e-4))
        assert why and any(word in w for w in why), (word, why)


def test_a_factor_held_off_must_bind_nothing_at_all():
    off = {"FNR-4FE-4S-CPLX": 0.0, "PHOSPHO-NARL": 0.877}
    run = {**GOOD, "bound_fraction": {"FNR-4FE-4S-CPLX": 0.0, "PHOSPHO-NARL": 0.86}}
    assert D.validity(run, off) == []                         # no growth range: a perturbation arm
    leaky = {**run, "bound_fraction": {"FNR-4FE-4S-CPLX": 0.004, "PHOSPHO-NARL": 0.86}}
    assert any("FNR-4FE-4S-CPLX" in w for w in D.validity(leaky, off))


def test_the_interaction_is_the_change_in_narls_effect_when_fnr_is_held_off():
    import math
    lg = lambda xs: [math.log2(x) for x in xs]   # noqa: E731
    # NarL doubles synthesis with FNR held off (+1.0) and raises it a quarter with FNR at the fit (+0.32)
    est = D.interaction(lg([2.0, 2.0]), lg([1.0, 1.0]), lg([1.25, 1.25]), lg([1.0, 1.0]))
    assert round(est["estimate"], 3) == round(1.0 - math.log2(1.25), 3) and est["n"] == [2, 2, 2, 2]
    # forced: an arm with fewer than two valid seeds has no spread, so no interaction is reported
    assert D.interaction(lg([2.0]), lg([1.0, 1.0]), lg([1.25, 1.25]), lg([1.0, 1.0]))["estimate"] is None
