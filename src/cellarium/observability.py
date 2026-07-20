"""LLM-2 — the observability seam. ONE point of truth for every Anthropic Messages call the platform makes.

Both surfaces publish here: the Socratic Council roles (`council._emit`, via `messages.create`) and the grounded
agent (`agent._run_turn`, via the streamed final message). Each call site builds a per-call RECORD — role, model,
request-id, token usage, wall-clock latency, temperature, an estimated cost — and `emit()`s it to whatever
consumers are subscribed.

The record is a plain dict (JSON-safe, SQLite-serializable). This module ships exactly ONE consumer: a cost/latency
meter (`CostMeter`) that aggregates spend + wall-time per scope (one Council deliberation, or one agent turn). A
SECOND consumer — e.g. a per-round transcript store — subscribes as another reader of the SAME records WITHOUT
touching either call site. That is the seam: the record shape and the publish point are fixed here; the consumers
are pluggable. Keep additions to the record shape backward-additive so existing consumers never break.
"""

from __future__ import annotations

import contextlib
import threading
import time

# --- pricing (estimate, not billing) -----------------------------------------------------------------------
# Anthropic list price, USD per 1M tokens, as (input, output). A cost meter is an ESTIMATE: cache reads bill
# ~0.1x the input rate, cache writes (5-minute TTL) ~1.25x. We use LIST price (ignore the temporary Sonnet-5 intro
# discount) so the number is a conservative ceiling, and match by model-id prefix so date-suffixed ids resolve.
# Source: the bundled claude-api skill pricing table (cached 2026-06-24). Update here when prices move.
_PRICING = {
    "claude-fable-5": (10.0, 50.0),
    "claude-mythos-5": (10.0, 50.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-opus-4-5": (5.0, 25.0),
    "claude-opus-4-1": (15.0, 75.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-sonnet-4": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}

_CACHE_READ_MULT = 0.1     # a cached-prefix read bills ~10% of the input rate
_CACHE_WRITE_MULT = 1.25   # a 5-minute cache write bills ~125% of the input rate


def _price(model: str | None):
    """(input, output) $/1M for a model id, matched by the LONGEST known prefix (so 'claude-haiku-4-5-20251001'
    resolves to the haiku row). None when the model isn't in the table — the caller then leaves cost unpriced
    rather than guessing a wrong number."""
    if not model:
        return None
    m = model.lower()
    best = None
    for key, price in _PRICING.items():
        if m.startswith(key) and (best is None or len(key) > len(best[0])):
            best = (key, price)
    return best[1] if best else None


def estimate_cost_usd(model: str | None, input_tokens: int, output_tokens: int,
                      cache_read_tokens: int = 0, cache_creation_tokens: int = 0) -> float | None:
    """Approximate USD for one call: uncached input + output at list price, cache reads at ~0.1x input, cache
    writes at ~1.25x input. Returns None for an unpriced model, so a consumer can show '—' instead of a wrong $."""
    price = _price(model)
    if price is None:
        return None
    p_in, p_out = price
    dollars = (
        (input_tokens or 0) * p_in
        + (cache_read_tokens or 0) * p_in * _CACHE_READ_MULT
        + (cache_creation_tokens or 0) * p_in * _CACHE_WRITE_MULT
        + (output_tokens or 0) * p_out
    ) / 1_000_000.0
    return dollars


# --- the record --------------------------------------------------------------------------------------------

def usage_record(role: str, model: str | None, resp, latency_ms: float, *,
                 temperature: float | None = None) -> dict:
    """Build the per-call record from an Anthropic response — either a `messages.create` result (Council) or a
    streamed `stream.get_final_message()` (agent); both carry `.usage`, `.model`, and `._request_id`. Every field
    degrades gracefully (missing usage -> 0, no request-id -> None) so a mock or a partial response never raises.
    This dict IS the seam's contract; additions must be backward-additive."""
    usage = getattr(resp, "usage", None)

    def _u(name: str) -> int:
        return int(getattr(usage, name, None) or 0) if usage is not None else 0

    input_tokens = _u("input_tokens")
    output_tokens = _u("output_tokens")
    cache_read = _u("cache_read_input_tokens")
    cache_creation = _u("cache_creation_input_tokens")
    resolved_model = getattr(resp, "model", None) or model
    return {
        "role": role,
        "model": resolved_model,
        "request_id": getattr(resp, "_request_id", None),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read,
        "cache_creation_tokens": cache_creation,
        "latency_ms": int(latency_ms),
        "temperature": temperature,
        "cost_usd": estimate_cost_usd(resolved_model, input_tokens, output_tokens, cache_read, cache_creation),
    }


# --- publish / subscribe: one publish point, pluggable consumers -------------------------------------------
# emit() fans each record to every registered subscriber. The publishers are council._emit (the Council roles +
# the sufficiency gate), council.web_research (the librarian web_search call), and agent._run_turn (the agent
# turns + the forced synthesis); LLM-2's CostMeter is the one shipped consumer; a transcript-persistence layer can
# be a second by calling subscribe() — no edit to the call sites. A lock keeps the subscriber list coherent (the
# agent and Council never truly run concurrently in the single-user app, but the invariant is cheap to hold).
_subscribers: list = []
_lock = threading.Lock()


def subscribe(fn) -> "callable":
    """Register a consumer `fn(record) -> None`; returns an `unsubscribe()` that drops it. A consumer must never
    raise — `emit()` isolates each so a broken sink can't break a live model call."""
    with _lock:
        _subscribers.append(fn)

    def _unsubscribe():
        with _lock:
            if fn in _subscribers:
                _subscribers.remove(fn)

    return _unsubscribe


def emit(record: dict) -> dict:
    """Publish one per-call record to every subscriber and return it unchanged. NEVER raises — observability must
    never break a real call, so a faulty consumer is swallowed. With no subscribers this is a cheap no-op, so the
    two call sites can emit unconditionally."""
    with _lock:
        subs = list(_subscribers)
    for fn in subs:
        try:
            fn(record)
        except Exception:
            pass
    return record


# --- the shipped consumer: a cost / latency meter ----------------------------------------------------------

class CostMeter:
    """The seam's own consumer: collects the per-call records of ONE scope and aggregates them — call count,
    token totals, estimated USD, wall-time, and per-role / per-model breakdowns. Subscribe it for the scope
    (see `meter()`), then read `.summary()`. Not billing: `cost_usd` is a list-price ESTIMATE and is a lower
    bound when any call used an unpriced model (`cost_partial`)."""

    def __init__(self):
        self.records: list = []

    def __call__(self, record: dict) -> None:   # the subscriber callable
        self.records.append(record)

    @property
    def n_calls(self) -> int:
        return len(self.records)

    def summary(self) -> dict:
        recs = self.records

        def _total(key: str) -> int:
            return sum(int(r.get(key) or 0) for r in recs)

        priced = [r.get("cost_usd") for r in recs if r.get("cost_usd") is not None]
        by_role: dict = {}
        by_model: dict = {}
        for r in recs:
            by_role[r.get("role")] = by_role.get(r.get("role"), 0) + 1
            by_model[r.get("model")] = by_model.get(r.get("model"), 0) + 1
        return {
            "n_calls": len(recs),
            "input_tokens": _total("input_tokens"),
            "output_tokens": _total("output_tokens"),
            "cache_read_tokens": _total("cache_read_tokens"),
            "cache_creation_tokens": _total("cache_creation_tokens"),
            "latency_ms": _total("latency_ms"),
            "cost_usd": round(sum(priced), 6) if priced else None,
            "cost_partial": len(priced) < len(recs),   # >=1 call used an unpriced model -> cost is a lower bound
            "by_role": by_role,
            "by_model": by_model,
        }


@contextlib.contextmanager
def meter():
    """Scope a `CostMeter` over a block: `with observability.meter() as m: ...; m.summary()`. Subscribes it for
    the block and unsubscribes on exit. Fan-out is by design: every meter open during a call sees that call's
    record — so a Council-run meter and a transcript sink both observe the same calls, and nested scopes are
    additive rather than isolating."""
    m = CostMeter()
    unsubscribe = subscribe(m)
    try:
        yield m
    finally:
        unsubscribe()


# `time` is re-exported so the call sites can measure wall-clock latency without a second import line.
now = time.monotonic
