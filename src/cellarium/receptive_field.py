"""SP-2c: the receptive-field benchmark — deterministic `scan_overview` vs an LLM-worker fan-out.

Quantifies WHEN the ~N× cost of a sub-agent fan-out over a design's channels earns its keep. Two arms recover
planted needles from a multi-channel trajectory:

  * DETERMINISTIC (`scan.detect_events`, what `scan_overview` runs): a robust MAD-prominence + FDR scan of every
    channel — fast, ZERO LLM calls, but blind to a needle below its amplitude/width threshold or one that isn't a
    clean transient/level-shift.
  * FAN-OUT (the true LLM-worker map-reduce): window each channel, hand each window's RAW values to an LLM worker to
    judge "notable event? where / what", then extractively reduce the workers' claims — it reads the raw signal, so
    it can catch a sub-threshold / narrower-than-min-width / contextual needle the deterministic scan filters out,
    at N× the tokens + latency.

The benchmark plants EASY needles (both arms should catch) and HARD ones (a width-2 spike below the scan's min-width
gate — only a reader of the raw window catches it), runs both arms, and reports recall per arm plus the fan-out's
token/latency/cost from the LLM-2 observability records. The verdict is the paper's question: the fan-out only earns
its cost when it recovers a needle the deterministic scan MISSED — on easy needles the two tie and the fan-out is
pure overhead.

The deterministic arm + the needle/recall machinery are PURE and tested; the fan-out's LLM workers are gated (a
mock worker drives the tests, a real `make_llm_worker` runs the live benchmark and emits per-call records onto the
LLM-2 bus so `observability.meter()` prices it).
"""

from __future__ import annotations

import json

import numpy as np

from . import observability, scan

# the mock/real worker contract: worker(channel, start, values) -> list of {"loc": abs_index, "note": str}
# where `values` is the raw window and `start` its absolute offset, so a claimed in-window index maps to start+idx.


# --- the scenario: a multi-channel trajectory with planted needles -----------------------------------------

def scenario(*, n_channels: int = 6, n_steps: int = 320, sd: float = 0.02, seed: int = 7) -> tuple:
    """A synthetic multi-channel trajectory with planted needles of two difficulties. EASY: a tall, wide spike the
    deterministic scan catches. HARD: a width-2 spike below the scan's min-width gate — invisible to the scan but
    obvious to a reader of the raw window. Returns (channels, t, M, needles); M is [n_channels × n_steps]."""
    rng = np.random.default_rng(seed)
    t = np.arange(n_steps, dtype=float)
    channels = [f"ch{i}" for i in range(n_channels)]
    M = 1.0 + rng.normal(0, sd, size=(n_channels, n_steps))
    needles = []
    # EASY: 8-MAD, width 4 — clears min_effect_mad=4 AND min_width=3, so the scan finds it.
    M[1, 180:184] += 8 * sd
    needles.append({"channel": "ch1", "loc": 181, "difficulty": "easy"})
    # HARD: 6-MAD but only width 2 — tall enough to be unmistakable in the raw values, yet the scan's min-width gate
    # (min_width=3) filters it out as single-sample noise. Only a worker reading the raw window recovers it.
    M[3, 90:92] += 6 * sd
    needles.append({"channel": "ch3", "loc": 90, "difficulty": "hard"})
    return channels, t, M, needles


# --- recall against the planted needles --------------------------------------------------------------------

def _recovered(needle: dict, events: list, tol: int) -> bool:
    return any(e.get("channel") == needle["channel"] and abs(float(e.get("loc", -1e18)) - needle["loc"]) <= tol
               for e in events)


def recall(needles: list, events: list, *, tol: int = 8) -> dict:
    """A needle is recovered if a claimed event is on the same channel within `tol` steps of its location."""
    recovered = [n for n in needles if _recovered(n, events, tol)]
    missed = [n for n in needles if not _recovered(n, events, tol)]
    return {"recall": round(len(recovered) / len(needles), 3) if needles else None,
            "recovered": recovered, "missed": missed, "n_events": len(events)}


# --- the two arms ------------------------------------------------------------------------------------------

def deterministic_arm(channels: list, t: np.ndarray, M: np.ndarray, *, min_effect_mad: float = 4.0) -> list:
    """The deterministic scan of every channel — exactly `scan_overview`'s engine (`scan.detect_events`). No LLM."""
    events = []
    for i, ch in enumerate(channels):
        for e in scan.detect_events(t, M[i], min_effect_mad=min_effect_mad):
            events.append({"channel": ch, "loc": float(e["t_peak"]), "kind": e.get("kind"), "source": "scan"})
    return events


def _windows(v: np.ndarray, size: int, stride: int) -> list:
    """Overlapping windows over a channel's raw values; each becomes one worker's input."""
    n = len(v)
    starts = list(range(0, max(1, n - size + 1), stride))
    if starts and starts[-1] + size < n:
        starts.append(n - size)      # cover the tail
    return [(s, v[s:s + size]) for s in starts]


def fanout_arm(channels: list, t: np.ndarray, M: np.ndarray, *, worker, size: int = 40, stride: int = 32) -> list:
    """Fan `worker` over every (channel, window); each worker reads the RAW window and claims 0..many events;
    extractively reduce to the union of claims. `worker(channel, start, values) -> [{loc, note}]`."""
    events = []
    for i, ch in enumerate(channels):
        for start, win in _windows(M[i], size, stride):
            for claim in (worker(ch, int(start), win) or []):
                if claim.get("loc") is not None:
                    events.append({"channel": ch, "loc": float(claim["loc"]), "note": claim.get("note"),
                                   "source": "llm"})
    return events


# --- the benchmark -----------------------------------------------------------------------------------------

def _verdict(det: dict, fan: dict, summ: dict) -> dict:
    det_locs = {(n["channel"], n["loc"]) for n in det["recovered"]}
    extra = [n for n in fan["recovered"] if (n["channel"], n["loc"]) not in det_locs]
    return {"fanout_recovers_more": bool(extra),
            "extra_needles": extra,
            "fanout_n_llm_calls": summ.get("n_calls"),
            "fanout_cost_usd": summ.get("cost_usd"),
            "fanout_latency_ms": summ.get("latency_ms"),
            "earns_its_cost": bool(extra),
            "note": ("Fan-out earns its cost ONLY when it recovers a needle the deterministic scan missed — a "
                     "sub-threshold / narrower-than-min-width / contextual anomaly. On easy needles both arms tie "
                     "and the fan-out is pure overhead (N× tokens + latency for no extra recall).")}


def benchmark(*, worker=None, min_effect_mad: float = 4.0, tol: int = 8, scenario_kwargs: dict | None = None) -> dict:
    """Run the deterministic arm always; run the fan-out arm when a `worker` is supplied (metered through the LLM-2
    observability bus). Returns per-arm recall and, when the fan-out ran, the cost/latency and the earns-its-cost
    verdict. Pass a mock `worker` for an offline run, or `make_llm_worker(client)` for the live benchmark."""
    channels, t, M, needles = scenario(**(scenario_kwargs or {}))
    det_events = deterministic_arm(channels, t, M, min_effect_mad=min_effect_mad)
    det = recall(needles, det_events, tol=tol)
    out = {"needles": needles,
           "deterministic": {**det, "n_llm_calls": 0, "cost_usd": 0.0}}
    if worker is not None:
        with observability.meter() as m:
            fan_events = fanout_arm(channels, t, M, worker=worker)
        fan = recall(needles, fan_events, tol=tol)
        summ = m.summary()
        out["fanout"] = {**fan, **summ}
        out["verdict"] = _verdict(det, fan, summ)
    return out


# --- the real, gated LLM worker ----------------------------------------------------------------------------

_WORKER_TOOL = {
    "name": "flag_events",
    "description": "Report every notable event (a spike, step, or drift that stands out from the local baseline) in "
                   "this raw window. Give each event's index INTO THE WINDOW (0-based) and a one-phrase note. Empty "
                   "list if the window is unremarkable noise.",
    "input_schema": {"type": "object", "properties": {"events": {"type": "array", "items": {"type": "object",
        "properties": {"index_in_window": {"type": "integer"}, "note": {"type": "string"}},
        "required": ["index_in_window"]}}}, "required": ["events"]},
}


def make_llm_worker(client, model: str = "claude-haiku-4-5-20251001", max_tokens: int = 512):
    """A real fan-out worker: one forced-tool LLM call per window that flags notable events in the RAW values, and
    EMITS a per-call record onto the LLM-2 observability bus (so `observability.meter()` prices the fan-out). Gated —
    needs a live Anthropic client. Maps each in-window index back to an absolute location."""
    def worker(channel: str, start: int, values) -> list:
        payload = {"channel": channel, "window_start": start, "n": len(values),
                   "values": [round(float(x), 4) for x in values]}
        t0 = observability.now()
        resp = client.messages.create(
            model=model, max_tokens=max_tokens, tools=[_WORKER_TOOL],
            tool_choice={"type": "tool", "name": "flag_events"},
            system=("You are a receptive-field worker: read the raw numeric window and flag any point that stands out "
                    "from the local baseline (a spike, step, or drift), however brief. Report the index INTO THE "
                    "WINDOW. Do not invent events in plain noise."),
            messages=[{"role": "user", "content": json.dumps(payload)}])
        observability.emit(observability.usage_record(
            "rf_worker", model, resp, (observability.now() - t0) * 1000))
        claims = []
        for block in getattr(resp, "content", None) or []:
            if getattr(block, "type", None) == "tool_use" and isinstance(block.input, dict):
                for ev in (block.input.get("events") or []):
                    idx = ev.get("index_in_window")
                    if isinstance(idx, int) and 0 <= idx < len(values):
                        claims.append({"loc": start + idx, "note": ev.get("note")})
        return claims
    return worker


if __name__ == "__main__":   # live benchmark — needs ANTHROPIC_API_KEY (runs the real fan-out arm)
    import os
    import sys

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Set ANTHROPIC_API_KEY to run the live fan-out arm (the deterministic arm needs no key).")
        sys.exit(2)
    import anthropic

    _client = anthropic.Anthropic(max_retries=4)
    _res = benchmark(worker=make_llm_worker(_client))
    print(json.dumps(_res, indent=2, default=str))
    _d, _f, _v = _res["deterministic"], _res["fanout"], _res["verdict"]
    print(f"\nDeterministic recall {_d['recall']} (0 LLM calls)  |  Fan-out recall {_f['recall']} "
          f"({_f.get('n_calls')} calls, ${_f.get('cost_usd')}, {round((_f.get('latency_ms') or 0) / 1000, 1)}s)")
    print("Fan-out EARNED its cost." if _v["earns_its_cost"] else "Fan-out did NOT earn its cost (no extra recall).")
