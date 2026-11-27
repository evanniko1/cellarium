"""CRIT tier 1 (Cellarium, 2026-11-27): the replication threshold relaxes towards a new medium's value instead of
jumping to it.

THE DEFECT. `ChromosomeReplication.calculateRequest` re-reads the critical initiation mass at every step from the
CURRENT medium's tabulated doubling time, so a shift between media with different doubling times moves the threshold
in one step while the cell is still the old medium's; after a downshift every origin fires at once and the cell
divides early, where the organism keeps dividing at the old rate for about an hour (Zaritsky & Helmstetter 1992).

THE FIX, SMALLEST VERSION. The threshold relaxes exponentially towards the current medium's value, on the clock of
growth in that medium, as a pure function of the run's timeline and absolute time:

    on [t_k, t_k+1), the k-th timeline event, medium m_k:
        M(t) = M*_k + (M(t_k) - M*_k) * exp(-(t - t_k) / T_k),   M*_k = M_crit(tau_k),   T_k = tau_k / ln 2
    M(t_0) = the model's own startup value (its fitted condition's threshold)

After one doubling time in the new medium, half of the adjustment remains. Absolute time crosses division, so a daughter
needs no inherited state. When every event's threshold equals the startup value (a constant medium, or a shift between
media whose thresholds are both at the 975 fg cap), the model's own function is called unchanged, so such a run is
bit-identical to one without this hook.

HOW IT IS INSTALLED. No model code is copied. This file is the container's entry point in place of the script it wraps:

    python /cellarium/initiation_threshold.py runscripts/manual/runSim.py <its arguments>

With CELLARIUM_INITIATION_THRESHOLD=relaxed it wraps `ChromosomeReplication.initialize` so that, after the model's own
initialize has run, the process's threshold function is `RelaxedThreshold`; unset or "medium", it changes nothing.
Then it runs the wrapped script as __main__. Every generation of a manual run happens in this one process.

LIMITATIONS (tier 1). T is phenomenological, tied to a quantity the model already uses. After a downshift the threshold
still falls over the next generation, so initiation comes somewhat early; there is no ppGpp pause (tier 2). A
sinusoidal medium is refused.
"""
from __future__ import annotations

import math
import os
import runpy
import sys

ENV = "CELLARIUM_INITIATION_THRESHOLD"
MODES = ("medium", "relaxed")


def relaxed_mass(t: float, events: list, start: float, target_of) -> float:
    """M(t) in fg. `events`: [(t_k in s, tau_k in min)] in time order; `start`: M(t_0) in fg; `target_of(tau)`: the
    model's threshold in fg for a doubling time in minutes."""
    m = float(start)
    for k, (tk, tauk) in enumerate(events):
        if tk > t:
            break
        end = events[k + 1][0] if k + 1 < len(events) else math.inf
        target = float(target_of(tauk))
        dt = min(t, end) - tk
        m = target + (m - target) * math.exp(-dt / (tauk * 60.0 / math.log(2.0)))
        if t < end:
            break
    return m


class RelaxedThreshold:
    """Stands in for `ChromosomeReplication.get_dna_critical_mass` (doubling time -> mass, both with units)."""

    def __init__(self, process, sim, original):
        self.process, self.sim, self.original = process, sim, original
        self.start = None
        self.events = None

    def _setup(self):
        from wholecell.utils import units
        env = self.sim.external_states["Environment"]
        if getattr(env, "sinusoidal_config", None):
            raise RuntimeError("initiation_threshold=relaxed is not defined for a sinusoidal medium")
        n2dt = self.process.nutrientToDoublingTime
        self.start = float(self.process.criticalInitiationMass.asNumber(units.fg))
        self.events = [(float(t), float(n2dt[m].asNumber(units.min))) for t, m in env.current_timeline]
        # each event's target, computed once: the model's function with units is slow, and the targets never change
        self.targets = {tau: self.target_fg(tau) for _, tau in self.events}
        self.static = all(x == self.start for x in self.targets.values())

    def target_fg(self, tau_min: float) -> float:
        from wholecell.utils import units
        return float(self.original(tau_min * units.min).asNumber(units.fg))

    def __call__(self, doubling_time):
        from wholecell.utils import units
        if self.events is None:
            self._setup()
        if self.static:
            return self.original(doubling_time)             # no threshold step anywhere: the model's own value
        return relaxed_mass(float(self.process.time()), self.events, self.start, self.targets.__getitem__) * units.fg


def install() -> None:
    from models.ecoli.processes import chromosome_replication as cr
    model_initialize = cr.ChromosomeReplication.initialize

    def initialize(self, sim, sim_data):
        model_initialize(self, sim, sim_data)
        self.get_dna_critical_mass = RelaxedThreshold(self, sim, self.get_dna_critical_mass)

    cr.ChromosomeReplication.initialize = initialize


def main(argv: list) -> None:
    mode = os.environ.get(ENV) or "medium"
    if mode not in MODES:
        raise SystemExit(f"{ENV}={mode!r}: expected one of {MODES}")
    if not argv:
        raise SystemExit("usage: initiation_threshold.py <script> [args...]")
    if mode == "relaxed":
        install()
        print(f"CELLARIUM: initiation threshold relaxed ({ENV}=relaxed)", flush=True)
    sys.argv = list(argv)
    runpy.run_path(argv[0], run_name="__main__")


if __name__ == "__main__":
    main(sys.argv[1:])
