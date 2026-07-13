"""Single source of truth for the cross-seed viability verdict (§J) — imported host-side (store) AND inside the
container (the reader worker), so the two never drift. Pure Python, no deps, so it loads in both contexts.

Facts in -> verdict out. Any FBA-solver failure is inviable (a numerical crash), independent of division rate —
this is the case where the two former copies diverged (the worker's viable-branch used to match first and
mislabel a crashed-but-dividing run 'viable').
"""

from __future__ import annotations

VIABLE_MIN_RATE = 0.9
INVIABLE_MAX_RATE = 0.6


def verdict(min_division_rate, all_terminal_divided, any_terminal_divided, n_fba_failures) -> str:
    if min_division_rate is None:
        return "unknown"                       # shards predate the viability channel
    if n_fba_failures and n_fba_failures > 0:
        return "inviable"                      # a solver crash is inviable regardless of division rate
    if min_division_rate >= VIABLE_MIN_RATE and all_terminal_divided:
        return "viable"
    if min_division_rate < INVIABLE_MAX_RATE or not any_terminal_divided:
        return "inviable"
    return "impaired"
