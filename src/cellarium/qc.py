"""Output QC guardrail — inspect each simulated generation and withhold degenerate results.

A whole-cell simulation can run to completion yet be scientifically invalid (a cell that over-replicated,
a generation that ran two timesteps, a non-dividing lineage). The platform must NOT launder those into a
clean-looking doubling time. This module assigns a QC status per generation; the agent treats anything other
than `ok` as *evidence-absent*.

Rules are derived from real simOut signals we validated (over-replication = full_chromosome > 2; degenerate
= a handful of steps; no clean division event; FBA collapse; inherited death flag).
"""

from __future__ import annotations

from enum import Enum

from .model import GenerationResult, SimResult

DEGENERATE_MAX_STEPS = 10
# per-second instantaneous growth faster than any real/model condition (~11.5-min doubling; with_aa peaks ~0.0005)
# is numerical garbage — the signature of a crashed-but-"divided" run (gltX post-collapse read 0.0013-0.0021).
IMPLAUSIBLE_GROWTH = 0.001


class QCStatus(str, Enum):
    OK = "ok"
    EMPTY = "empty"        # no readable generation data at all — NOT ok (e.g. a crash before generation 0)
    DEAD = "dead"
    DEGENERATE = "degenerate"
    OVER_REPLICATED = "over_replicated"
    FBA_INFEASIBLE = "fba_infeasible"
    IMPLAUSIBLE = "implausible_channel"   # divided, but a core channel is physically impossible (crash garbage)
    NO_DIVISION = "no_division"


def check_generation(gen: GenerationResult) -> QCStatus:
    if gen.is_dead:
        return QCStatus.DEAD
    if gen.n_steps <= DEGENERATE_MAX_STEPS:
        return QCStatus.DEGENERATE
    if gen.full_chromosome_end > 2:
        return QCStatus.OVER_REPLICATED
    if not gen.fba_ok:
        return QCStatus.FBA_INFEASIBLE
    if gen.growth_mean is not None and gen.growth_mean > IMPLAUSIBLE_GROWTH:
        return QCStatus.IMPLAUSIBLE   # a run can "divide" yet be numerically collapsed — don't report its channels (G2)
    if not gen.divided or gen.division_time_sec is None:
        return QCStatus.NO_DIVISION
    return QCStatus.OK


def check_result(sim: SimResult) -> tuple[QCStatus, list[QCStatus]]:
    """Return (overall status, per-generation statuses). Overall is the first non-ok status, else ok. A result with
    NO readable generations is EMPTY (never ok) — an empty read must not launder into a clean 'ok' (that is exactly
    how disk-crash artifacts slipped through as viable)."""
    if not sim.generations:
        return QCStatus.EMPTY, [QCStatus.EMPTY]
    per = [check_generation(g) for g in sim.generations]
    overall = next((s for s in per if s is not QCStatus.OK), QCStatus.OK)
    return overall, per


def is_reportable(sim: SimResult) -> bool:
    """True only if every generation is ok — otherwise a metric must not be reported."""
    overall, _ = check_result(sim)
    return overall is QCStatus.OK
