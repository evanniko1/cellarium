"""SP-2c: the receptive-field benchmark — deterministic scan vs an LLM-worker fan-out. The scenario, both arms, the
recall/verdict logic, and the fan-out's metering through the LLM-2 bus are exercised with mock workers (no API); the
real `make_llm_worker` runs the live benchmark."""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cellarium import observability, receptive_field as rf  # noqa: E402


def _raw_reader_worker(channel, start, values):
    """Stand-in for the LLM worker: flags any point > 4 robust-MADs from the window median — catches a spike of ANY
    width, unlike the deterministic scan's min-width gate. Pure, no API."""
    v = np.asarray(values, float)
    med = np.median(v)
    mad = float(np.median(np.abs(v - med))) or 1e-9
    return [{"loc": start + int(i), "note": "raw deviation"}
            for i in np.where(np.abs(v - med) / (1.4826 * mad) > 4.0)[0]]


def _null_worker(channel, start, values):
    return []


def test_scenario_plants_recoverable_needles():
    channels, t, M, needles = rf.scenario()
    assert len(channels) == 6 and M.shape == (6, 320)
    assert {(n["channel"], n["difficulty"]) for n in needles} == {("ch1", "easy"), ("ch3", "hard")}
    assert M[1, 181] > 1.1 and M[3, 90] > 1.1                 # the spikes are actually in the values


def test_deterministic_arm_catches_easy_misses_hard():
    channels, t, M, needles = rf.scenario()
    events = rf.deterministic_arm(channels, t, M)
    r = rf.recall(needles, events)
    assert r["recall"] == 0.5                                  # the width-2 hard needle is below the min-width gate
    assert [n["difficulty"] for n in r["recovered"]] == ["easy"]
    assert [n["difficulty"] for n in r["missed"]] == ["hard"]


def test_fanout_recovers_the_hard_needle_the_scan_missed():
    channels, t, M, needles = rf.scenario()
    events = rf.fanout_arm(channels, t, M, worker=_raw_reader_worker)
    r = rf.recall(needles, events)
    assert r["recall"] == 1.0                                  # reading the raw window recovers BOTH needles
    assert {n["difficulty"] for n in r["recovered"]} == {"easy", "hard"}


def test_benchmark_verdict_earns_cost_only_when_it_finds_more():
    got = rf.benchmark(worker=_raw_reader_worker)
    assert got["deterministic"]["recall"] == 0.5 and got["fanout"]["recall"] == 1.0
    assert got["verdict"]["earns_its_cost"] is True
    assert [n["difficulty"] for n in got["verdict"]["extra_needles"]] == ["hard"]

    # a worker that finds nothing: the fan-out recovers nothing extra -> not worth the N× cost
    null = rf.benchmark(worker=_null_worker)
    assert null["fanout"]["recall"] == 0.0 and null["verdict"]["earns_its_cost"] is False

    # no worker -> deterministic-only, no fan-out section
    det_only = rf.benchmark()
    assert "fanout" not in det_only and det_only["deterministic"]["n_llm_calls"] == 0


def test_fanout_is_metered_through_the_llm2_bus():
    """Each worker call emits an LLM-2 record; the benchmark meters the whole fan-out, so cost/latency roll up."""
    class _U:
        input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens = 10, 5, 0, 0

    class _R:
        usage, model, _request_id = _U(), "claude-haiku-4-5", "req_x"

    def _metering_worker(channel, start, values):
        observability.emit(observability.usage_record("rf_worker", "claude-haiku-4-5", _R(), 12.0))
        return []

    got = rf.benchmark(worker=_metering_worker)
    fan = got["fanout"]
    assert fan["n_calls"] > 0 and fan["by_role"] == {"rf_worker": fan["n_calls"]}
    assert fan["input_tokens"] == 10 * fan["n_calls"] and isinstance(fan["cost_usd"], float)


def test_windows_cover_the_whole_channel():
    v = np.arange(320.0)
    wins = rf._windows(v, size=40, stride=32)
    assert wins[0][0] == 0 and wins[-1][0] + 40 == 320        # first window at 0, last reaches the tail
    covered = set()
    for start, w in wins:
        covered.update(range(start, start + len(w)))
    assert covered == set(range(320))                          # every index is in some window
