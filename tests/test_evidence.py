"""The evidence ledger — can a claim be traced to its run ids AFTER the session ends?

`rigor.coverage()` answers "what did the agent read?" but is in-memory and cleared by reset(), so the link from
a manuscript sentence to the runs behind it dies with the process. This pins the durable replacement, and the
properties that make it evidence rather than a log: append-only, ids-not-values, and incapable of breaking a
live tool call.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("CELLARIUM_MANIFEST", "data/manifest/vmnik-compact.parquet")

import pytest  # noqa: E402

from cellarium import evidence  # noqa: E402


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    p = tmp_path / "evidence.jsonl"
    monkeypatch.setattr(evidence, "LEDGER", p)
    monkeypatch.setattr(evidence, "_enabled", True, raising=False)
    monkeypatch.setattr(evidence, "_env_cache", {"git_commit": "abc1234", "model": "test"}, raising=False)
    return p


def test_off_by_default_writes_nothing(tmp_path, monkeypatch):
    """The read-only tier, tests and evals must not accumulate a file nobody asked for."""
    p = tmp_path / "e.jsonl"
    monkeypatch.setattr(evidence, "LEDGER", p)
    monkeypatch.setattr(evidence, "_enabled", False, raising=False)
    evidence.record("survey_corpus", {}, {"id": "r1"})
    assert not p.exists()


def test_a_tool_call_records_the_run_ids_it_touched(ledger):
    evidence.record("read_series", {"design": "gene_knockout/KO:argS"},
                    {"rows": [{"id": "gene_knockout_0_ab12"}, {"id": "gene_knockout_1_cd34"}]})
    rows = evidence.read(ledger)
    assert len(rows) == 1
    assert rows[0]["activity"] == "read_series"
    assert rows[0]["entity_ids"] == ["gene_knockout_0_ab12", "gene_knockout_1_cd34"]
    assert rows[0]["env"]["git_commit"] == "abc1234"


def test_it_stores_ids_not_values(ledger):
    """The numbers must always be re-derived from the manifest. Caching them here would create a second source of
    truth that can silently drift from the corpus it claims to describe."""
    evidence.record("differential", {}, {"id": "r1", "growth_rate": 0.42, "ppgpp_conc": 1.7e-4})
    line = ledger.read_text(encoding="utf-8")
    assert "r1" in line and "0.42" not in line and "1.7e-04" not in line


def test_a_call_that_touched_no_run_is_not_recorded(ledger):
    evidence.record("estimate_sim_resources", {"n_runs": 4}, {"verdict": "ok", "warnings": []})
    assert evidence.read(ledger) == []


def test_design_keys_are_captured_but_free_text_labels_are_not(ledger):
    evidence.record("survey_corpus", {}, {"ranked": [{"design": "timeline/0 minimal, 1200 minimal_plus_amino_acids"},
                                                     {"label": "just a title with no separator"}]})
    r = evidence.read(ledger)[0]
    assert r["entity_designs"] == ["timeline/0 minimal, 1200 minimal_plus_amino_acids"]


def test_it_is_append_only(ledger):
    for i in range(3):
        evidence.record("read_series", {}, {"id": f"r{i}"})
    rows = evidence.read(ledger)
    assert [r["entity_ids"] for r in rows] == [["r0"], ["r1"], ["r2"]]     # nothing rewritten, order preserved


def test_recording_can_never_break_a_tool_call(ledger, monkeypatch):
    """An evidence sink must not be able to take down a live call — the same rule observability.emit follows."""
    def _boom(*a, **k):
        raise RuntimeError("disk full")
    monkeypatch.setattr(evidence, "_harvest", _boom)
    evidence.record("read_series", {}, {"id": "r1"})       # must not raise


def test_a_torn_final_line_does_not_make_the_ledger_unreadable(ledger):
    evidence.record("read_series", {}, {"id": "r1"})
    with ledger.open("a", encoding="utf-8") as fh:
        fh.write('{"ts": 1, "activity": "read_ser')        # a crash mid-write
    assert len(evidence.read(ledger)) == 1


def test_long_arguments_are_trimmed_not_stored_whole(ledger):
    evidence.record("chart", {"question": "x" * 500}, {"id": "r1"})
    assert len(evidence.read(ledger)[0]["args"]["question"]) <= 120


def test_trace_answers_the_reviewers_question(ledger):
    """'Figure 3 says argS lowers ppGpp — show me the runs.'"""
    evidence.record("read_series", {"design": "gene_knockout/KO:argS"},
                    {"rows": [{"id": "ko_argS_s0"}, {"id": "ko_argS_s1"}]})
    evidence.record("disconfirm", {"target": "gene_knockout/KO:argS"},
                    {"design": "gene_knockout/KO:argS", "id": "ko_argS_s2"})
    evidence.record("read_series", {"design": "wildtype/basal"}, {"id": "wt_s0"})
    t = evidence.trace("argS", ledger)
    assert t["n_activities"] == 2 and sorted(t["tools"]) == ["disconfirm", "read_series"]
    assert t["run_ids"] == ["ko_argS_s0", "ko_argS_s1", "ko_argS_s2"]
    assert "wt_s0" not in t["run_ids"]                     # the wildtype call is a different claim


def test_trace_on_an_ungrounded_claim_returns_empty_not_a_guess(ledger):
    evidence.record("read_series", {}, {"id": "r1"})
    t = evidence.trace("pfkA", ledger)
    assert t["n_activities"] == 0 and t["run_ids"] == []


def test_the_dispatch_funnel_records_every_tool(ledger, monkeypatch):
    """Wired at tools.dispatch, so a tool added later is covered without touching it."""
    from cellarium import tools
    monkeypatch.setitem(tools._DISPATCH, "_probe", lambda **k: {"id": "probe_run_1"})
    monkeypatch.setattr(tools, "_validate_args", lambda name, args: None)
    tools.dispatch("_probe", {})
    assert evidence.read(ledger)[0]["entity_ids"] == ["probe_run_1"]


def test_rigor_coverage_uses_the_fixed_design_key():
    """rigor.coverage carried the same merge bug as survey/differential — an upshift and a downshift shared one
    grid cell, so 'examined' could be reported for a design the agent never read."""
    import inspect

    from cellarium import rigor
    src = inspect.getsource(rigor.coverage)
    assert "survey.design_key" in src
    assert '{r.get("perturbation")}/{r.get("condition")}' not in src


def test_the_ledger_env_is_captured_once_not_per_line(ledger, monkeypatch):
    calls = []
    monkeypatch.setattr(evidence, "_env_cache", None, raising=False)
    monkeypatch.setattr(evidence, "_env", lambda: (calls.append(1), {"git_commit": "x"})[1])
    for i in range(3):
        evidence.record("read_series", {}, {"id": f"r{i}"})
    assert len(evidence.read(ledger)) == 3
    assert json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])["env"]["git_commit"] == "x"
