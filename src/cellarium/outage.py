"""Stop a paid evaluation when its model calls fail in a row (Agentic Benchmark Checklist item T.3).

A run that keeps going through an API outage does two bad things. It pays for calls that cannot succeed. And
where a failed call is absorbed into a fallback, it scores the outage as if it were the system's behaviour: the
gate's parser, by design, proceeds on a blank requirement when its call fails, so an evaluation that kept going
through an outage would grade the ignorance rule on every remaining item and report it as the gate.

One failed call is a hard item or a transient fault, and the client has already retried it. Several in a row,
with nothing succeeding in between, is the signature of an interruption. So each harness feeds every completed
call to a `Breaker`; at the first run of `limit` consecutive failures it stops starting new work, writes what it
has with the reason, and exits with `EXIT_INTERRUPTED` rather than 0. A stopped run is never written over a
complete artefact.

WHAT THIS DOES NOT CATCH. A failure that does not look like one: a model that answers, wrongly, on every call.
That is a result, not an interruption, and the evaluations' own error accounting is where it shows.
"""

from __future__ import annotations

import threading

EXIT_INTERRUPTED = 3
# Five consecutive failures, each already retried by the client (max_retries 4 to 6 in the harnesses), is far
# past what a transient fault produces and well short of what an outage costs over a 216-item run.
DEFAULT_LIMIT = 5


class Breaker:
    """Counts consecutive failed calls. `observe` returns True on the call that trips it, and only that call.

    Thread-safe, because the harnesses call from worker threads. Consult `tripped` where a call STARTS, in the
    worker, not where results are collected: a collector lags its workers, and with fast calls it lags them by
    the whole run, which is how a first version of this stopped "after 8 of 36" and had made all 36.
    """

    def __init__(self, limit: int = DEFAULT_LIMIT):
        if limit < 1:
            raise ValueError(f"limit must be at least 1, not {limit}")
        self.limit = limit
        self.n_ok = 0
        self.n_failed = 0
        self.run: list[str] = []          # the reasons of the current run of consecutive failures
        self.tripped_at: int | None = None
        self.reasons_at_trip: list[str] = []
        self._lock = threading.Lock()

    def observe(self, ok: bool, why: str = "") -> bool:
        with self._lock:
            if ok:
                self.n_ok += 1
                self.run = []
                return False
            self.n_failed += 1
            self.run.append(why or "unspecified failure")
            if self.tripped_at is None and len(self.run) >= self.limit:
                self.tripped_at = self.n_ok + self.n_failed
                self.reasons_at_trip = list(self.run)
                return True
            return False

    @property
    def tripped(self) -> bool:
        return self.tripped_at is not None

    def exit_code(self) -> int:
        """What the harness exits with: 0 for a run that finished, EXIT_INTERRUPTED for one this stopped."""
        return EXIT_INTERRUPTED if self.tripped else 0

    def report(self, total: int) -> dict:
        """What a stopped run writes beside its partial records."""
        return {"stopped_early": self.tripped, "after_calls": self.tripped_at, "of": total,
                "limit": self.limit, "consecutive_failures": self.reasons_at_trip,
                "n_ok": self.n_ok, "n_failed": self.n_failed,
                "why": (f"{self.limit} consecutive model calls failed after {self.tripped_at} of {total}; "
                        f"the run stopped rather than score an interruption. Nothing here is a complete "
                        f"result." if self.tripped else "the run was not interrupted")}

    def message(self, total: int) -> str:
        kinds: dict[str, int] = {}
        for r in self.reasons_at_trip:
            kinds[r] = kinds.get(r, 0) + 1
        return (f"STOPPED after {self.tripped_at} of {total} calls: {self.limit} in a row failed ("
                + ", ".join(f"{k} x{n}" for k, n in kinds.items()) + "). Check the network, the key and the "
                "provider's status, then re-run.")
