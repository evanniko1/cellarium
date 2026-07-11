"""The orchestration seam: two entrypoints, one agent, reads never routed through the Council."""

from cellarium import orchestrate


class _FakeHyp:
    def brief(self) -> str:
        return "BRIEF: sharpened hypothesis"


def test_direct_entry_skips_the_council(monkeypatch):
    """use_council=False must NOT deliberate; the raw question goes straight to the agent (hypothesis=None)."""
    calls = {}

    def fake_deliberate(*a, **k):
        calls["deliberate"] = True
        return _FakeHyp()

    def fake_run(question, *, hypothesis=None, **k):
        calls["run"] = {"question": question, "hypothesis": hypothesis}
        return "ANSWER"

    monkeypatch.setattr("cellarium.council.deliberate", fake_deliberate)
    monkeypatch.setattr("cellarium.agent.run", fake_run)

    res = orchestrate.investigate("why the noise?", use_council=False)

    assert "deliberate" not in calls                    # the Council never ran
    assert calls["run"]["hypothesis"] is None           # raw-question path
    assert calls["run"]["question"] == "why the noise?"
    assert res.used_council is False
    assert res.hypothesis is None and res.brief is None
    assert res.answer == "ANSWER"


def test_council_entry_hands_the_hypothesis_to_the_agent(monkeypatch):
    """use_council=True: deliberate -> on_hypothesis -> agent.run(hypothesis=...), in that order."""
    events = []
    hyp = _FakeHyp()

    def fake_deliberate(*a, **k):
        events.append("deliberate")
        return hyp

    def fake_run(question, *, hypothesis=None, **k):
        events.append(("run", hypothesis))
        return "GROUNDED ANSWER"

    monkeypatch.setattr("cellarium.council.deliberate", fake_deliberate)
    monkeypatch.setattr("cellarium.agent.run", fake_run)

    res = orchestrate.investigate("why the noise?", use_council=True,
                                  on_hypothesis=lambda h: events.append(("hyp", h)))

    # order matters: the brief is available BEFORE the agent starts
    assert events == ["deliberate", ("hyp", hyp), ("run", hyp)]
    assert res.used_council is True
    assert res.hypothesis is hyp
    assert res.brief == "BRIEF: sharpened hypothesis"
    assert res.answer == "GROUNDED ANSWER"
