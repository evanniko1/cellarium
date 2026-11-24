"""Metering and capping what a paid evaluation spends.

Three things a paid run needs before anyone can approve an amount for it:

1. A meter that counts THIS record's calls. `observability.emit` fans every call to every open meter, which is
   right for the app (one deliberation at a time) and wrong for an evaluation that runs six records in worker
   threads: each record's meter would count its neighbours' calls too. `meter(this_thread=True)` keeps only the
   calls made from the thread that opened it.
2. A price for every call, including the cross-family judge, which is OpenAI and outside `observability`.
3. A cap that stops the run before the approved amount is passed, checked where work starts (as the outage
   breaker is), with a reserve for the records already in flight, and tripped at once by a call it cannot price.

Every call is faked; nothing leaves the machine. Expectations are literals.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "evals"))

import costs  # noqa: E402

from cellarium import observability  # noqa: E402


def _rec(cost, model="claude-sonnet-5"):
    return {"role": "proposer", "model": model, "input_tokens": 10, "output_tokens": 5, "cache_read_tokens": 0,
            "cache_creation_tokens": 0, "latency_ms": 1, "cost_usd": cost}


# --- a meter per thread --------------------------------------------------------------------------------

def test_a_thread_meter_counts_only_its_own_threads_calls():
    seen: dict = {}
    barrier = threading.Barrier(2)

    def work(name, n, cost):
        with observability.meter(this_thread=True) as m:
            barrier.wait()                              # both meters are open before either thread emits
            for _ in range(n):
                observability.emit(_rec(cost))
            barrier.wait()                              # ...and stay open until both threads have emitted
        seen[name] = m.summary()

    with observability.meter() as everything:
        ts = [threading.Thread(target=work, args=("a", 3, 0.01)), threading.Thread(target=work, args=("b", 5, 0.1))]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
    assert (seen["a"]["n_calls"], seen["b"]["n_calls"]) == (3, 5)
    assert (seen["a"]["cost_usd"], seen["b"]["cost_usd"]) == (0.03, 0.5)
    assert everything.n_calls == 8                    # a plain meter still sees every call, as the app expects


# --- prices ----------------------------------------------------------------------------------------------

def test_gpt_4o_is_priced_at_the_standard_list_rate():
    """$2.50 in and $10.00 out per 1M tokens: 2,000 in and 500 out = 0.005 + 0.005."""
    assert costs.openai_cost("gpt-4o", 2000, 500) == 0.01
    assert costs.openai_cost("gpt-4o-2024-08-06", 2000, 500) == 0.01


def test_a_different_model_that_shares_a_prefix_is_not_given_gpt_4o_s_price():
    """gpt-4o-mini costs a fifteenth as much; a prefix match would bill it as gpt-4o."""
    assert costs.openai_cost("gpt-4o-mini", 2000, 500) is None
    assert costs.price("gpt-4o-mini") is None


def test_an_openai_reply_becomes_a_record_the_meters_count():
    class R:
        id = "chatcmpl-1"
        usage = type("U", (), {"prompt_tokens": 2000, "completion_tokens": 500})()
    rec = costs.openai_record("grader_gpt", "gpt-4o", R(), 12.3)
    assert (rec["input_tokens"], rec["output_tokens"], rec["cost_usd"]) == (2000, 500, 0.01)
    with observability.meter(this_thread=True) as m:
        observability.emit(rec)
    assert m.summary()["cost_usd"] == 0.01 and m.summary()["cost_partial"] is False


# --- the cap ---------------------------------------------------------------------------------------------

def test_the_cap_trips_when_spend_reaches_the_cap_less_the_reserve():
    cap = costs.SpendCap(10.0, reserve_usd=2.0)
    assert [cap.add(3.0), cap.add(3.0), cap.add(1.9), cap.add(0.2)] == [False, False, False, True]
    assert cap.tripped and cap.tripped_at == 4
    rep = cap.report(total=50)
    assert (rep["spent_usd"], rep["after_records"], rep["of"]) == (8.1, 4, 50)


def test_the_cap_trips_on_a_call_it_cannot_price():
    cap = costs.SpendCap(100.0)
    assert cap.add(0.5, partial=True) is True
    assert "no price" in cap.report(total=3)["why"]


def test_no_cap_never_trips():
    cap = costs.SpendCap(None)
    assert not any(cap.add(1e6) for _ in range(3)) and not cap.tripped


@pytest.mark.parametrize("cap_usd,reserve", [(0.0, 0.0), (-1.0, 0.0), (5.0, 5.0), (5.0, -0.1)])
def test_a_cap_that_could_never_hold_is_refused(cap_usd, reserve):
    with pytest.raises(ValueError):
        costs.SpendCap(cap_usd, reserve_usd=reserve)


def test_the_capped_exit_code_is_four_not_the_outage_three():
    from cellarium import outage
    assert costs.EXIT_SPEND_CAP == 4 and outage.EXIT_INTERRUPTED == 3
