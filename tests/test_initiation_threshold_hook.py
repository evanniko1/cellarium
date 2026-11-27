"""CRIT tier 1 (2026-11-27): the relaxed replication threshold (model_patches/hooks/initiation_threshold.py).

V2 of CRIT_FIX_SPEC's validation plan, offline: the closed form is continuous across events, monotone between them,
equals the startup value in a constant medium, and reaches half the adjustment after one doubling time in the new
medium. The model's own function is called unchanged whenever no event moves the threshold, which is what makes a
static run bit-identical (V1, a run-level check). Literals: the thresholds measured in the knowledge bases (CRIT_FIX_SPEC
s.1: 975 fg at 44 min or faster, 590.0 at 100).
"""
from __future__ import annotations

import importlib.util
import math
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture()
def hook(monkeypatch):
    # a stand-in for wholecell.utils.units, enough for the hook's three uses: tau * units.min, x.asNumber(units.fg),
    # value * units.fg
    class Q:
        def __init__(self, v, u):
            self.v, self.u = v, u

        def asNumber(self, u):
            assert u.name == self.u
            return self.v

        def __rmul__(self, k):
            return Q(k * self.v, self.u)

        def __eq__(self, o):
            return isinstance(o, Q) and (o.v, o.u) == (self.v, self.u)

    class U:
        def __init__(self, name):
            self.name = name

        def __rmul__(self, k):
            return Q(k, self.name)

    units = types.ModuleType("wholecell.utils.units")
    units.min, units.fg = U("min"), U("fg")
    for name in ("wholecell", "wholecell.utils"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "wholecell.utils.units", units)
    sys.modules["wholecell.utils"].units = units
    spec = importlib.util.spec_from_file_location("ith", REPO / "model_patches" / "hooks" / "initiation_threshold.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._units, mod._Q = units, Q
    return mod


def m_crit(tau_min: float) -> float:
    """The model's thresholds at the doubling times the tests use (CRIT_FIX_SPEC s.1)."""
    return {25.0: 975.0, 44.0: 975.0, 100.0: 590.0}[tau_min]


DOWN = [(0.0, 44.0), (600.0, 100.0)]                 # glucose, then oxygen removed at 600 s


def test_a_constant_medium_holds_the_startup_value(hook):
    assert all(hook.relaxed_mass(t, [(0.0, 44.0)], 975.0, m_crit) == 975.0 for t in (0, 1, 600, 1e5))


def test_a_downshift_does_not_jump_and_halves_its_adjustment_after_one_doubling_time(hook):
    assert hook.relaxed_mass(599.0, DOWN, 975.0, m_crit) == 975.0
    assert hook.relaxed_mass(600.0, DOWN, 975.0, m_crit) == 975.0          # the upstream code jumps to 590 here
    one_tau = 600.0 + 100 * 60
    assert hook.relaxed_mass(one_tau, DOWN, 975.0, m_crit) == pytest.approx(590 + 385 / 2, rel=1e-12)
    assert hook.relaxed_mass(1e7, DOWN, 975.0, m_crit) == pytest.approx(590.0, abs=1e-9)


def test_continuous_and_monotone_with_a_second_event(hook):
    ev = [(0.0, 44.0), (600.0, 100.0), (4000.0, 25.0)]          # down, then back up before it settled
    ts = [600 + i * 10.0 for i in range(800)]
    ms = [hook.relaxed_mass(t, ev, 975.0, m_crit) for t in ts]
    steps = [abs(b - a) for a, b in zip(ms, ms[1:])]
    assert max(steps) < 1.0                                       # no jump anywhere, the event at 4000 s included
    falling = [m for t, m in zip(ts, ms) if t <= 4000]
    rising = [m for t, m in zip(ts, ms) if t >= 4000]
    assert falling == sorted(falling, reverse=True) and rising == sorted(rising)
    at_4000 = 590 + 385 * math.exp(-3400 / (6000 / math.log(2)))
    assert hook.relaxed_mass(4000.0, ev, 975.0, m_crit) == pytest.approx(at_4000, rel=1e-12)


def test_a_daughter_reads_the_same_value_from_absolute_time(hook):
    """No inherited state: the closed form at a daughter's first step equals the mother's at the same time."""
    assert hook.relaxed_mass(3000.0, DOWN, 975.0, m_crit) == hook.relaxed_mass(3000.0, list(DOWN), 975.0, m_crit)


class _Proc:
    def __init__(self, hook, t, timeline):
        self._t, self.nutrientToDoublingTime = t, {m: tau * hook._units.min for m, tau in timeline.items()}
        self.criticalInitiationMass = 975.0 * hook._units.fg

    def time(self):
        return self._t


def _sim(events):
    return types.SimpleNamespace(external_states={"Environment": types.SimpleNamespace(current_timeline=events)})


def test_without_a_threshold_step_the_models_own_function_is_returned(hook):
    """Glucose to rich medium: 44 to 25 minutes, both at the 975 fg cap, so no event moves the threshold. The model's
    function must be what answers, so a run with the hook is bit-identical to one without it."""
    calls = []

    def original(tau):
        calls.append(tau)
        return m_crit(tau.asNumber(hook._units.min)) * hook._units.fg

    p = _Proc(hook, 900.0, {"minimal": 44.0, "minimal_plus_amino_acids": 25.0})
    r = hook.RelaxedThreshold(p, _sim([(0.0, "minimal"), (600.0, "minimal_plus_amino_acids")]), original)
    arg = 25.0 * hook._units.min
    got = r(arg)
    assert calls[-1] is arg and got == 975.0 * hook._units.fg


def test_a_threshold_step_is_relaxed_through_the_callable(hook):
    def original(tau):
        return m_crit(tau.asNumber(hook._units.min)) * hook._units.fg

    p = _Proc(hook, 600.0 + 6000.0, {"minimal": 44.0, "minimal_minus_oxygen": 100.0})
    r = hook.RelaxedThreshold(p, _sim([(0.0, "minimal"), (600.0, "minimal_minus_oxygen")]), original)
    got = r(100.0 * hook._units.min)
    assert got.asNumber(hook._units.fg) == pytest.approx(782.5, rel=1e-12)


def test_an_unknown_mode_is_refused(hook, monkeypatch):
    monkeypatch.setenv(hook.ENV, "sometimes")
    with pytest.raises(SystemExit, match="expected one of"):
        hook.main(["runscripts/manual/runSim.py"])
