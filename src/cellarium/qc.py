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

# TRANSLATION COLLAPSE, in amino acids/second. `IMPLAUSIBLE_GROWTH` is a CEILING; nothing was a floor, so a
# cell whose ribosomes had effectively stopped still returned `ok` provided its chromosome finished.
#
# The threshold is anchored to measurement, not taste. In E. coli the elongation rate is 20-21 aa/s above one
# doubling/h (Forchhammer & Lindahl 1971, JMB 55:563) and 17 aa/s fast / 12 aa/s at 0.67 doublings/h (Young &
# Bremer 1976, Biochem J 160:185). Crucially, Dai et al. 2016 (Nat Microbiol 2:16231, PMID 27941827) show the
# rate does NOT collapse as growth slows: "an appreciable elongation rate is maintained even towards zero
# growth, including the stationary phase" — a slow cell reduces its ACTIVE RIBOSOME FRACTION and keeps
# elongating. So "the cell is just growing slowly" does not produce a near-zero rate in real E. coli.
#
# 1.0 aa/s sits an order of magnitude below the slowest rate ever measured and ~17x below this model's own
# wild type (16.72 aa/s, measured on wildtype/basal#elong:kinetic). MEASURED on gene_knockout/KO:argS under
# kinetic: 0.047, 0.012, 0.007 across three generations — 250-2400x below the slow-growth value, i.e. one
# residue every 20-140 s. Every one of those generations was recorded `qc=ok`.
TRANSLATION_COLLAPSE_AA_PER_S = 1.0


class QCStatus(str, Enum):
    OK = "ok"
    EMPTY = "empty"        # no readable generation data at all — NOT ok (e.g. a crash before generation 0)
    DEAD = "dead"
    DEGENERATE = "degenerate"
    OVER_REPLICATED = "over_replicated"
    FBA_INFEASIBLE = "fba_infeasible"
    IMPLAUSIBLE = "implausible_channel"   # divided, but a core channel is physically impossible (crash garbage)
    NO_DIVISION = "no_division"
    TRUNCATED = "truncated"                # data stops BEFORE the division that ended the generation
    TRANSLATION_COLLAPSE = "translation_collapse"   # ribosomes stopped; the chromosome finished anyway


# Generation n's data must reach generation n+1's first timestep. A gap larger than this (seconds) means
# timesteps are missing from the END of generation n. One timestep is ~1 s and the boundary is exclusive, so a
# healthy pair differs by ~1 s; the threshold is deliberately loose so a variable timestep cannot trip it.
MAX_GENERATION_GAP_SEC = 5.0


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
    if gen.elongation_mean is not None and gen.elongation_mean < TRANSLATION_COLLAPSE_AA_PER_S:
        # BEFORE the division test on purpose: this cell's chromosome may well have reached 2, and that is
        # exactly the case that was scoring `ok`. Absent (None) stays silent — a run predating the channel is
        # unknown, not healthy.
        return QCStatus.TRANSLATION_COLLAPSE
    if not gen.divided or gen.division_time_sec is None:
        return QCStatus.NO_DIVISION
    return QCStatus.OK


def truncated_generations(sim: SimResult) -> list[int]:
    """Indices of generations whose data stops BEFORE the division that ended them.

    Single-generation checks cannot see this, which is why it lives here rather than in `check_generation`. An
    end-truncated generation still satisfies every per-generation rule — the chromosome count ends at 2 over a
    long trajectory, so `divided` is True — and `division_time_sec` becomes the last SURVIVING timestep rather
    than the real division. The only witness is the next generation's start time.

    MEASURED 2026-08-03 over all 269 generation boundaries in the local corpus: 2 are truncated, both
    `wildtype_374656` generation 0 — seed 0 stops at 2047 s against a next-generation start of 2530 s (482
    steps, 19.1% of the generation), seed 1 stops at 478 s against 2574 s (2095 s, 81.4%). Both were recorded
    `qc='ok'`, `generation_qc` all `"ok"`, `reportable=True`. The damage was not hypothetical: the truncated
    span made a fork-era wildtype look 23.50% shorter-lived than an identical rerun whose true division times
    match to +0.00%, and inflated a seed-to-seed CV from 8.85% to 13.29%.

    Only reports a gap it can actually see: generations without `t_start`/`t_end` (every row written before
    those fields existed) are skipped, because absent is not continuous.
    """
    gens = sorted(sim.generations, key=lambda g: g.index)
    out: list[int] = []
    for a, b in zip(gens, gens[1:]):
        if a.t_end is None or b.t_start is None:
            continue
        if b.index != a.index + 1:      # a hole in the lineage is a different defect; do not guess across it
            continue
        if (b.t_start - a.t_end) > MAX_GENERATION_GAP_SEC:
            out.append(a.index)
    return out


def check_result(sim: SimResult) -> tuple[QCStatus, list[QCStatus]]:
    """Return (overall status, per-generation statuses). Overall is the first non-ok status, else ok. A result with
    NO readable generations is EMPTY (never ok) — an empty read must not launder into a clean 'ok' (that is exactly
    how disk-crash artifacts slipped through as viable)."""
    if not sim.generations:
        return QCStatus.EMPTY, [QCStatus.EMPTY]
    per = [check_generation(g) for g in sim.generations]
    # Cross-generation pass, AFTER the per-generation one: truncation is invisible to a single generation and
    # must be able to overturn an `ok`, because `ok` is exactly what it was recorded as.
    by_index = {g.index: i for i, g in enumerate(sim.generations)}
    for idx in truncated_generations(sim):
        pos = by_index.get(idx)
        if pos is not None and per[pos] is QCStatus.OK:
            per[pos] = QCStatus.TRUNCATED
    overall = next((s for s in per if s is not QCStatus.OK), QCStatus.OK)
    return overall, per


def is_reportable(sim: SimResult) -> bool:
    """True only if every generation is ok — otherwise a metric must not be reported."""
    overall, _ = check_result(sim)
    return overall is QCStatus.OK
