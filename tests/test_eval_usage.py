"""KISS-2 Stage 0: the eval runners must record what they SPENT, not only what they said.

WHY. Scaling the limits test from nine questions to a benchmark is an API-credit decision, and the cost of
the nine already run could not be recovered from their own output: `data/discrimination_test.json` and
`evals/results/ablation.json` carry `seconds` and answer text and no token counts at all. So the only way to
budget the larger run was assumption — a fixed prefix of ~20.6k tokens measured from the tool schemas plus a
GUESSED 8 turns and ~900 tokens of payload each. An estimate built on two guesses is not something to spend
a budget against.

The machinery already existed: `agent.converse` has taken an `on_usage` callback (tokens, cache reads,
estimated USD, per-model breakdown) since the observability work. What was missing was one forwarding
parameter — `agent.run`, which is what every eval runner actually calls, dropped it on the floor.

These tests are static: they assert the wiring, not a live API call, so they run in CI with no key.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def test_agent_run_forwards_on_usage():
    """The gap itself. `run` accepted no on_usage, so no caller of `run` could ever record cost."""
    from cellarium import agent

    sig = inspect.signature(agent.run)
    assert "on_usage" in sig.parameters, "agent.run cannot report usage — every eval runner goes through it"
    src = inspect.getsource(agent.run)
    assert "on_usage=on_usage" in src, "on_usage is accepted but not passed through to converse()"


def test_converse_still_offers_the_callback():
    from cellarium import agent

    assert "on_usage" in inspect.signature(agent.converse).parameters


def test_the_grounded_runner_records_usage_per_question():
    src = (REPO / "scripts" / "run_discrimination_test.py").read_text(encoding="utf-8")
    assert "on_usage=" in src, "the grounded arm does not ask for usage"
    assert "usage=usage or None" in src, "usage is collected but not written into the per-question record"
    assert src.index("on_usage=") < src.index("usage=usage or None"), (
        "the record is built before the callback could fill it")


def test_the_ungrounded_runner_records_usage_per_question():
    src = (REPO / "scripts" / "run_ablation.py").read_text(encoding="utf-8")
    assert "on_usage=" in src and "usage=usage or None" in src


def test_the_usage_summary_carries_what_a_cost_model_needs():
    """A record with only a total is not enough to project a bigger run: cache reads are billed at a tenth,
    so a benchmark dominated by a cached prefix costs very differently from one that is not."""
    from cellarium import observability

    src = inspect.getsource(observability.Meter.summary if hasattr(observability, "Meter")
                            else observability)
    for field in ("input_tokens", "output_tokens", "cache_read_tokens", "cost_usd"):
        assert field in src, f"the usage summary does not report {field}"


def test_the_default_costs_nothing_when_nobody_asks():
    """on_usage must stay optional — the CLI and the server should not pay for a meter they do not read."""
    from cellarium import agent

    assert inspect.signature(agent.run).parameters["on_usage"].default is None
    assert inspect.signature(agent.converse).parameters["on_usage"].default is None
