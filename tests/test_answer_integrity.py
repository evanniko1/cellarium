"""S2-2: an integrity audit of a Cellwright answer, after the fact, with a planted fault for each check.

PLAT-1 (reconcile.py) asks whether an answer names runs the turn never read. This asks three more questions of the
same answer: is each number in a field of the run it is credited to; did a turn the gate stopped run any tool; was
each cited paper among what the turn read. Each check is shown a planted fault and must catch it, and shown the
clean answer and must pass it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from cellarium import integrity as I  # noqa: E402

WT, KO = "wildtype/basal", "gene_knockout/KO:argS"
SEPARATE = [json.dumps({"design": WT, "growth_rate": 0.01231}), json.dumps({"design": KO, "growth_rate": 0.00978})]
TOGETHER = [json.dumps({"reference": WT, "target": KO, "ref_mean": 0.01231, "target_mean": 0.00978,
                        "log2fc": -0.332})]
ANSWER = f"In {WT} growth was 0.0123 per minute. In {KO} it reached 0.00978 per minute."
SWAPPED = f"In {KO} growth was 0.0123 per minute. In {WT} it reached 0.00978 per minute."


# ---- numbers ---------------------------------------------------------------------------------------------------

def test_a_number_in_its_own_runs_field_passes():
    for tools in (SEPARATE, TOGETHER):
        r = I.audit_numbers(ANSWER, tools)
        assert [c["status"] for c in r["claims"]] == ["own_run", "own_run"], tools
        assert r["misattributed"] == []


def test_a_number_credited_to_the_wrong_run_is_caught():
    for tools in (SEPARATE, TOGETHER):
        r = I.audit_numbers(SWAPPED, tools)
        assert [c["status"] for c in r["claims"]] == ["other_run_only", "other_run_only"], tools
        assert [(c["label"], c["number"]) for c in r["misattributed"]] == [(KO, "0.0123"), (WT, "0.00978")]


def test_a_swap_inside_a_sentence_naming_two_runs_is_counted_but_not_named():
    # which number goes with which run is ambiguous when a sentence names both, so the finding stays a count
    both = f"In {KO} growth was 0.0123 per minute, while {WT} reached 0.00978 per minute."
    r = I.audit_numbers(both, SEPARATE)
    assert r["counts"]["other_run_only"] == 2 and r["misattributed"] == []


def test_table_rows_short_numbers_and_unrecognised_designs_are_never_named():
    # all three gave false findings on recorded answers: a table's columns, a two-digit number that matched another
    # run's field by rounding, and a graded knockdown the label pattern reads as the full knockout
    table = f"| | {KO} | {WT} |\n|---|---|---|\n| growth | 0.00978 | 0.0123 |"
    assert I.actionable_claims(table) == []
    assert I.actionable_claims(f"In {WT} growth fell 27%.") == []
    graded = f"The knockdown (graded_gene_knockout/KO:argS#expr:0.1) raised ppGpp by 335% in {KO}."
    assert I.actionable_claims(graded) == []
    assert I.actionable_claims(f"In {WT} growth was 0.0123 per minute.") == [(WT, "0.0123")]


def test_a_comparisons_own_statistic_is_shared_not_misattributed():
    # the log2 fold change belongs to the pair, so crediting it to either run is not a swap
    r = I.audit_numbers(f"Against {WT}, {KO} changed by -0.332 in log2.", TOGETHER)
    assert [c["status"] for c in r["claims"]] == ["shared"]


def test_a_computed_number_is_unrouted_and_never_flagged():
    # 0.79 = 0.00978 / 0.01231: in no field at all; counted, never called a misattribution
    r = I.audit_numbers(f"So {KO} grew at 0.79 of the rate of the reference.", SEPARATE)
    assert [c["status"] for c in r["claims"]] == ["unrouted"] and r["misattributed"] == []


# ---- the gate's verdict ----------------------------------------------------------------------------------------

REFUSAL = "This model cannot represent what the question asks.\n\nRequirement: trna_charging at per_isoacceptor."


def test_a_gated_turn_that_ran_no_tool_respects_the_verdict():
    assert I.audit_verdict(REFUSAL, tool_calls=0) == {"gated": True, "respected": True}
    assert I.audit_verdict("growth was 0.0123", tool_calls=3) == {"gated": False, "respected": None}


def test_a_gated_turn_that_ran_a_tool_is_caught():
    assert I.audit_verdict(REFUSAL, tool_calls=1) == {"gated": True, "respected": False}
    proposal = "This model can represent what the question asks, but no run exists to read."
    assert I.audit_verdict(proposal, tool_calls=2)["respected"] is False


# ---- citations -------------------------------------------------------------------------------------------------

LIT = [json.dumps({"results": [{"doi": "10.1016/j.cell.2026.02.009", "pmid": "38123456", "title": "t"}]})]


def test_a_citation_the_turn_read_passes_and_support_is_never_claimed():
    r = I.audit_citations("As shown (doi:10.1016/j.cell.2026.02.009; PMID 38123456).", LIT)
    assert r["unread"] == [] and r["cited"] == ["10.1016/j.cell.2026.02.009", "PMID:38123456"]
    assert r["supporting"] == "not checked"


def test_a_doi_the_tool_returned_json_escaped_counts_as_read():
    # a recorded Crossref result holds the slash escaped twice over ("10.1126\\\\/science.1070919")
    escaped = [json.dumps(json.dumps({"DOI": "10.1126/science.1070919"}).replace("/", "\\/"))]
    assert "10.1126/science" not in escaped[0]
    assert I.audit_citations("DOI 10.1126/science.1070919 shows it.", escaped)["unread"] == []


def test_an_invented_citation_is_caught():
    r = I.audit_citations("As shown (doi:10.1038/s41586-099-0000-0; PMID: 99999999).", LIT)
    assert r["unread"] == ["10.1038/s41586-099-0000-0", "PMID:99999999"]


def test_a_doi_ending_a_sentence_keeps_no_trailing_punctuation():
    assert I.audit_citations("See 10.1016/j.cell.2026.02.009.", LIT)["unread"] == []
    # markdown around a parenthesised DOI: three recorded answers end one with ")**"
    assert I.audit_citations("**(doi:10.1016/j.cell.2026.02.009)**", LIT)["cited"] == ["10.1016/j.cell.2026.02.009"]
    # a DOI that itself holds parentheses keeps them
    assert I._doi("10.1002/(SICI)1097-0258(19980430)17:8.") == "10.1002/(SICI)1097-0258(19980430)17:8"


# ---- together --------------------------------------------------------------------------------------------------

def test_the_annotation_names_only_what_is_precise_enough_to_act_on():
    clean = I.audit(ANSWER, SEPARATE, tool_calls=2)
    assert I.annotation(clean) == ""
    bad = I.audit(SWAPPED + " (doi:10.1038/s41586-099-0000-0)", SEPARATE, tool_calls=2)
    note = I.annotation(bad)
    assert KO in note and "0.0123" in note and "10.1038/s41586-099-0000-0" in note
    # an unrouted (computed) number is counted in the audit and never named in the note
    assert "0.79" not in I.annotation(I.audit(f"So {KO} grew at 0.79 of the rate.", SEPARATE, tool_calls=2))


def test_an_audit_that_could_not_read_the_turn_says_so():
    # fail closed, as PLAT-1 does: no tool output is "could not verify", never a clean pass, and the note says so
    r = I.audit(ANSWER, None, tool_calls=None)
    assert r["verdict"] == "could_not_verify" and "could not run" in I.annotation(r)


def test_the_gate_render_is_recognised_from_the_gates_own_output():
    # the check reads the rendered text, so it must recognise what gate.render actually writes, not a copy of it
    from cellarium import gate
    req = gate.Requirement(observable="trna_charging", granularity="per_isoacceptor")
    for verdict in ("refuse", "propose"):
        d = gate.Decision(verdict=verdict, requirement=req, mode="steady_state")
        assert I.audit_verdict(gate.render(d), tool_calls=1) == {"gated": True, "respected": False}, verdict


# ---- the stored measurement ------------------------------------------------------------------------------------

def _stored():
    return json.loads((REPO / "evals" / "results" / "answer_integrity.json").read_text(encoding="utf-8"))


def test_the_stored_counts_are_the_ones_that_were_read_by_hand():
    # literal: the findings on the 60 recorded answers were adjudicated one by one at exactly these counts
    d = _stored()
    assert d["claim_status"] == {"own_run": 64, "shared": 11, "other_run_only": 13, "unrouted": 52}
    assert d["named"] == {"actionable_claims": 11, "named_misattributions": 0}
    assert (d["citations"]["cited"], d["citations"]["unread"]) == (22, 2)
    adj = d["adjudicated"]
    assert adj["other_run_only_among_all_claims"]["n"] == d["claim_status"]["other_run_only"]
    assert sum(adj["other_run_only_among_all_claims"]["the_pairings_error"].values()) == 13
    assert adj["unread_citations"]["n"] == d["citations"]["unread"]


def test_the_planted_swaps_are_caught_where_the_rule_reaches():
    p = _stored()["planted_swap"]
    assert (p["all_claims"]["own_run_before"], p["all_claims"]["found_in_the_other_run_after"]) == (30, 28)
    assert (p["actionable_claims"]["own_run_before"], p["actionable_claims"]["found_in_the_other_run_after"]) == (5, 4)


def test_the_recorded_answers_reproduce_the_stored_counts():
    db = REPO / "data" / "sessions.db"
    if not db.is_file():
        import pytest
        pytest.skip("data/sessions.db is not on this machine: the stored counts cannot be recomputed here")
    sys.path.insert(0, str(REPO / "evals"))
    import answer_integrity as A
    want = set(json.loads((REPO / "evals" / "results" / "attribution_swap.json").read_text(encoding="utf-8"))
               ["session_ids"])
    got = A.measure([s for s in A.load() if s["sid"] in want])
    stored = _stored()
    for key in ("answers", "claim_status", "named", "citations", "gate", "planted_swap"):
        assert got[key] == stored[key], key


# ---- the wiring: both exits of the agent loop hand the conversation's tool output to the check -----------------

def test_check_and_annotate_adds_the_integrity_note_when_handed_the_tool_output():
    from cellarium import reconcile
    out = reconcile.check_and_annotate(SWAPPED, tool_texts=SEPARATE)
    assert out.startswith(SWAPPED) and "Integrity check" in out and "0.0123" in out
    assert "Integrity check" not in reconcile.check_and_annotate(ANSWER, tool_texts=SEPARATE)


class _B:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def model_dump(self):
        return dict(self.__dict__)


class _R:
    def __init__(self, content, stop_reason):
        self.content, self.stop_reason, self.model = content, stop_reason, "fake"
        self.usage = _B(input_tokens=0, output_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=0)


class _S:
    def __init__(self, r):
        self.r = r

    def __enter__(self):
        return self

    def __exit__(self, *e):
        return False

    @property
    def text_stream(self):
        return iter(getattr(b, "text", "") for b in self.r.content if b.type == "text")

    def until_done(self):
        return None

    def get_final_message(self):
        return self.r


class _Queue:
    def __init__(self, responses):
        self.responses = list(responses)

    def stream(self, **kw):
        return _S(self.responses.pop(0))

    def create(self, **kw):
        return self.responses.pop(0)


def _run(monkeypatch, responses, max_turns):
    from cellarium import agent, llm, tools
    client = _B(messages=_Queue(responses))
    monkeypatch.setattr(llm, "client", lambda *a, **k: client)
    outputs = iter([{"design": WT, "growth_rate": 0.01231}, {"design": KO, "growth_rate": 0.00978}])
    monkeypatch.setattr(tools, "dispatch", lambda name, inp: next(outputs))
    return agent.converse([{"role": "user", "content": "How fast do they grow?"}], max_turns=max_turns)


def _tool_round(i):
    return _R([_B(type="tool_use", id=f"t{i}", name="read_series", input={"i": i})], "tool_use")


def test_the_normal_exit_checks_the_answer_against_the_conversations_tool_output(monkeypatch):
    out = _run(monkeypatch, [_tool_round(1), _tool_round(2), _R([_B(type="text", text=SWAPPED)], "end_turn")],
               max_turns=4)
    assert out.startswith(SWAPPED) and "Integrity check" in out and "`gene_knockout/KO:argS`" in out


def test_the_forced_synthesis_exit_checks_it_too(monkeypatch):
    # two tool rounds spend a two-turn budget; the third response is the forced synthesis with tools disabled
    out = _run(monkeypatch, [_tool_round(1), _tool_round(2), _R([_B(type="text", text=SWAPPED)], "end_turn")],
               max_turns=2)
    assert out.startswith(SWAPPED) and "Integrity check" in out
