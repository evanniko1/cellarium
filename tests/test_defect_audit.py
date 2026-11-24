"""The residual-defect auditor (`evals/audit.py`) — the endpoint the Council ablation actually reads.

Until 2026-11-24 this module had no tests, and both auditors mapped an unreadable reply to an empty defect list:
`audit_claude` returned `{"defects": []}` when no tool block came back, and read a missing `defects` key as an
empty list; `audit_gpt` caught every parse error and returned the same. Zero defects is the BEST score this
endpoint can give, so a reply nobody could read was recorded as a flawless hypothesis.

The stored artefact has the shape that failure leaves. Of the 120 Claude audits in `evals/results/audited.json`,
58 recorded zero defects and every other one recorded 7 to 10, never 1 to 6 and never more than 10, while the GPT
auditor never recorded zero. The readable Claude lists stop at about 2,700 characters, near what a 1,024-token
reply (the auditor's limit) can hold, so the likeliest reading is that a list longer than the limit was cut off
and counted as no defects at all. Confirming that needs one paid re-audit of the 58 records; until then, the
Claude column cannot rank the arms. The tests below pin the stored counts as literals and make every unreadable
reply an error. Every model call is faked; nothing leaves the machine.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in ("src", "evals"):
    sys.path.insert(0, str(REPO / p))

import ablate  # noqa: E402

import audit  # noqa: E402
from cellarium import llm  # noqa: E402

STORED_AUDIT = REPO / "evals" / "results" / "audited.json"
STORED_ABLATION = REPO / "evals" / "results" / "ablation.json"


# --- fakes ---------------------------------------------------------------------------------------------

class _Block:
    def __init__(self, data, kind="tool_use"):
        self.type = kind
        self.input = data


class _Usage:
    input_tokens = 2000
    output_tokens = 900
    cache_read_input_tokens = 0
    cache_creation_input_tokens = 0


class _Resp:
    def __init__(self, blocks, stop_reason="tool_use"):
        self.content = blocks
        self.stop_reason = stop_reason
        self.usage = _Usage()
        self.model = "claude-opus-4-8"


class _Client:
    """Replies with `resp` (or raises it) and keeps every request's keyword arguments."""

    def __init__(self, resp):
        self.resp = resp
        self.requests: list[dict] = []
        outer = self

        class _Messages:
            @staticmethod
            def create(**kw):
                outer.requests.append(kw)
                if isinstance(outer.resp, Exception):
                    raise outer.resp
                return outer.resp
        self.messages = _Messages()


def _oai(content, finish_reason="stop"):
    class _Msg:
        pass
    _Msg.content = content

    class _Choice:
        message = _Msg
    _Choice.finish_reason = finish_reason

    class _R:
        choices = [_Choice]
        usage = type("U", (), {"prompt_tokens": 2000, "completion_tokens": 500})()

    class _Oai:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    return _R
    return _Oai()


REC = {"id": "1.1", "config": "full", "rep": 0, "hypothesis": {"claim": "x"}}
TWO = {"defects": [{"type": "internal_contradiction", "issue": "a"},
                   {"type": "falsifier_cannot_fail", "issue": "b"}]}


# --- an unreadable reply is an error, never zero defects ----------------------------------------------

def test_a_claude_audit_cut_off_at_its_token_limit_is_an_error_not_zero_defects():
    """The case the stored distribution points at: a list longer than the reply limit is cut off."""
    client = _Client(_Resp([_Block({})], stop_reason="max_tokens"))
    with pytest.raises(audit.UnreadableAudit, match="max_tokens"):
        audit.audit_claude(REC, client)


def test_a_claude_audit_with_no_tool_block_is_an_error():
    with pytest.raises(audit.UnreadableAudit, match="no audit"):
        audit.audit_claude(REC, _Client(_Resp([_Block("prose", kind="text")], stop_reason="end_turn")))


def test_a_claude_audit_without_a_defect_list_is_an_error():
    with pytest.raises(audit.UnreadableAudit, match="defects"):
        audit.audit_claude(REC, _Client(_Resp([_Block({"rationale": "fine"})])))


def test_a_cut_off_list_is_an_error_even_when_part_of_it_parsed():
    """A partial list would undercount by however much was cut, so it is no better than an empty one."""
    with pytest.raises(audit.UnreadableAudit, match="max_tokens"):
        audit.audit_claude(REC, _Client(_Resp([_Block(TWO)], stop_reason="max_tokens")))


def test_a_complete_empty_list_is_still_a_real_zero():
    """The fix must not make a genuine 'no defects' unrecordable."""
    out = audit.audit_claude(REC, _Client(_Resp([_Block({"defects": []})])))
    assert out["defects"] == [] and out["stop_reason"] == "tool_use"


def test_a_complete_claude_audit_reports_its_count_stop_reason_and_reply_size():
    out = audit._one(REC, _Client(_Resp([_Block(TWO)])), None, "gpt-4o", "claude-opus-4-8")
    assert out["claude_defects"] == 2
    assert out["claude_stop_reason"] == "tool_use"
    assert out["claude_output_tokens"] == 900


def test_an_unreadable_claude_audit_leaves_no_count_on_the_record():
    """`_one` turns the exception into an error, so the record cannot be averaged as a zero."""
    out = audit._one(REC, _Client(_Resp([_Block({})], stop_reason="max_tokens")), None, "gpt-4o",
                     "claude-opus-4-8")
    assert "claude_defects" not in out
    assert out["error"].startswith("UnreadableAudit")


def test_an_unparseable_gpt_audit_is_an_error_not_zero_defects():
    with pytest.raises(audit.UnreadableAudit, match="not JSON"):
        audit.audit_gpt(REC, _oai("I cannot comply."))


def test_a_gpt_audit_without_a_defect_list_is_an_error():
    with pytest.raises(audit.UnreadableAudit, match="defects"):
        audit.audit_gpt(REC, _oai(json.dumps({"summary": "fine"})))


def test_a_gpt_audit_cut_off_at_its_length_limit_is_an_error():
    with pytest.raises(audit.UnreadableAudit, match="length"):
        audit.audit_gpt(REC, _oai(json.dumps(TWO), finish_reason="length"))


def test_the_claude_auditor_has_room_for_more_than_ten_defects():
    """1,024 tokens held at most ten defects of about 270 characters each in the stored run. Literal: 4096."""
    client = _Client(_Resp([_Block(TWO)]))
    audit.audit_claude(REC, client)
    assert client.requests[0]["max_tokens"] == 4096
    assert audit.MAX_TOKENS == 4096


# --- the stored artefact: the failure's shape, as literals ---------------------------------------------

def test_the_stored_claude_column_has_the_shape_of_failures_counted_as_zero():
    """Recomputed from the artefact, not quoted: 58 zeros, the rest 7 to 10, none in between, none above."""
    recs = json.loads(STORED_AUDIT.read_text(encoding="utf-8"))["results"]
    claude = [r["claude_defects"] for r in recs]
    gpt = [r["gpt_defects"] for r in recs]
    assert len(recs) == 120
    assert claude.count(0) == 58
    assert sorted(set(claude) - {0}) == [7, 8, 9, 10]
    assert 0 not in gpt


def test_among_readable_claude_audits_full_and_proposer_only_differ_by_a_few_hundredths():
    """The stored headline, 3.37 against 4.50, averages the zeros in. Without them: 101/12 and 135/16."""
    recs = json.loads(STORED_AUDIT.read_text(encoding="utf-8"))["results"]

    def mean(cfg, readable):
        xs = [r["claude_defects"] for r in recs if r["config"] == cfg and (r["claude_defects"] or not readable)]
        return round(sum(xs) / len(xs), 2)
    assert (mean("full", False), mean("proposer_only", False)) == (3.37, 4.5)
    assert (mean("full", True), mean("proposer_only", True)) == (8.42, 8.44)


def test_the_confirmation_reaudit_selects_exactly_the_58_zeroed_records():
    """`--only-claude-zeros` re-audits what the stored run zeroed and nothing else, so confirming costs 58 calls."""
    stored = json.loads(STORED_AUDIT.read_text(encoding="utf-8"))["results"]
    ablation = json.loads(STORED_ABLATION.read_text(encoding="utf-8"))["results"]
    picked = audit.select(ablation, only_claude_zeros=stored)
    assert len(picked) == 58
    zeroed = {(r["id"], r["config"], r["rep"]) for r in stored if r["claude_defects"] == 0}
    assert {(r["id"], r["config"], r["rep"]) for r in picked} == zeroed


# --- the run: an outage stops it, and the artefact is written once ------------------------------------

@pytest.fixture
def audit_run(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "client", lambda **kw: object())
    calls: list[tuple] = []

    def run(ok_first: int, n: int = 20):
        def fake_one(rec, client, oai, gpt_model, claude_auditor):
            calls.append((rec["id"], rec["rep"]))
            out = {"id": rec["id"], "config": rec["config"], "rep": rec["rep"]}
            if len(calls) > ok_first:
                out["error"] = "APIConnectionError: Connection error."
            else:
                out["claude_defects"] = 8
            return out
        monkeypatch.setattr(audit, "_one", fake_one)
        recs = [{"id": f"c{i}", "config": "full", "rep": 0, "hypothesis": {"claim": "x"}} for i in range(n)]
        out = tmp_path / "audited.json"
        code = audit.run(recs, str(out), client=object(), oai=None, gpt_model="gpt-4o",
                         claude_auditor="claude-opus-4-8", workers=1, source="ablation.json")
        return code, out, calls
    return run


def test_the_audit_stops_on_an_outage_without_touching_its_artefact(audit_run):
    code, out, calls = audit_run(ok_first=2)
    assert code == 3
    assert not out.exists(), "a stopped audit must not replace the stored audited.json"
    part = json.loads(out.with_name("audited.partial.json").read_text(encoding="utf-8"))
    assert (part["stopped_early"]["after_calls"], part["stopped_early"]["of"]) == (7, 20)
    assert len(part["results"]) == 7


def test_an_uninterrupted_audit_writes_its_artefact_once_with_what_produced_it(audit_run):
    code, out, calls = audit_run(ok_first=10 ** 6)
    assert code == 0 and len(calls) == 20
    art = json.loads(out.read_text(encoding="utf-8"))
    assert len(art["results"]) == 20
    assert art["claude_auditor"] == "claude-opus-4-8" and art["max_tokens"] == 4096
    assert art["source"] == "ablation.json"
    assert "python" in art["environment"]
    assert not out.with_name("audited.partial.json").exists()


# --- the ablation's own grader had the same hole --------------------------------------------------------

def _h():
    return type("H", (), {"model_dump": lambda self, **kw: {}, "brief": lambda self: ""})()


def test_a_claude_grade_cut_off_at_its_token_limit_is_an_error_not_a_zero():
    """grade_claude returned {} for a reply with no tool block, which `_score` reads as 0 of 6. The stored
    ablation has none (scores are 5 or 6 throughout), so this is preventive."""
    full = {k: True for k in ablate.Q}
    with pytest.raises(ValueError, match="max_tokens"):
        ablate.grade_claude({"question": "q"}, _h(), _Client(_Resp([_Block(full)], stop_reason="max_tokens")))


def test_a_claude_grade_missing_a_criterion_is_an_error_not_a_false():
    partial = {k: True for k in list(ablate.Q)[:5]}
    with pytest.raises(ValueError, match="q6_consistent"):
        ablate.grade_claude({"question": "q"}, _h(), _Client(_Resp([_Block(partial)])))


def test_a_complete_claude_grade_still_scores():
    full = {k: True for k in ablate.Q}
    g = ablate.grade_claude({"question": "q"}, _h(), _Client(_Resp([_Block(full)])))
    assert ablate._score(g) == 6
