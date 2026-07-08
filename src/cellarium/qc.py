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


class QCStatus(str, Enum):
    OK = "ok"
    DEAD = "dead"
    DEGENERATE = "degenerate"
    OVER_REPLICATED = "over_replicated"
    FBA_INFEASIBLE = "fba_infeasible"
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
    if not gen.divided or gen.division_time_sec is None:
        return QCStatus.NO_DIVISION
    return QCStatus.OK


def check_result(sim: SimResult) -> tuple[QCStatus, list[QCStatus]]:
    """Return (overall status, per-generation statuses). Overall is the first non-ok status, else ok."""
    per = [check_generation(g) for g in sim.generations] or [QCStatus.OK]
    overall = next((s for s in per if s is not QCStatus.OK), QCStatus.OK)
    return overall, per


def is_reportable(sim: SimResult) -> bool:
    """True only if every generation is ok — otherwise a metric must not be reported."""
    overall, _ = check_result(sim)
    return overall is QCStatus.OK
