"""Cellwright must be TOLD about the elongation axis and SHOWN it in every answer (EXT-PORT-16).

The axis was pinned at the plumbing level (Design -> CLI args -> dedup key -> manifest row) and at the
registry level (`capability.check` refuses an isoacceptor question under steady_state), and nowhere at the
level where it decides anything: the registry can be perfectly correct and the agent can still ignore it.

WHAT THIS FILE CAN AND CANNOT DO, stated up front because the distinction is the whole design. Whether the
model CHOOSES to route a question, or remembers to name the mode in prose, is model behaviour and needs a live
call; `tests/test_agent.py` mocks the client entirely and this repo has no live-gated agent-test convention, so
a live test here would be one nobody runs. What IS deterministic is everything the harness controls — the two
things that make ignoring the axis possible in the first place:

  (1) the INSTRUCTION: does `agent.SYSTEM` actually teach the axis, or was that sentence edited away;
  (2) the EVIDENCE: does every mode-sensitive tool the agent can call NAME the model it answered under, and
      does a mode refusal survive the funnel through which every tool result enters the model's context.

An agent cannot respect an axis it is never told about, and cannot report a mode that never reaches it. Those
are necessary conditions, they are testable without an API key, and neither was covered.

It caught one on the first run: `selective_charging` — the tool the agent calls for the headline selectivity
question — named the elongation model in its REFUSAL branch and not in its SUCCESS branch, i.e. everywhere
except where it returns numbers.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.cellarium import agent, capability, tools  # noqa: E402

# ---------------------------------------------------------------------------------------------------------
# (1) The instruction.
# ---------------------------------------------------------------------------------------------------------

def test_the_system_prompt_teaches_the_axis_not_just_the_trap():
    """A prompt that names the trap but not the RULE leaves the agent to infer the rule."""
    s = agent.SYSTEM
    low = s.lower()
    assert "elongation_model" in low, "the agent is never told the field exists"
    for mode in capability.ELONGATION_MODES:
        assert mode in low, f"the prompt does not name the {mode!r} model, so the agent cannot tell them apart"
    # Scoped to the ELONGATION passage, not to the whole prompt. A bare `"not pool" in low` passed for the
    # wrong reason: it matched the PARCA-3 sentence about a rebuild's runs being "not poolable with the
    # corpus", which is about ARMS. A prohibition that exists somewhere else in the prompt is not this rule.
    i = low.find("elongation_model")
    passage = low[max(0, i - 400):i + 900]
    assert any(p in passage for p in ("never pool", "must not be pooled", "do not pool")), (
        "the prompt describes the three models but never states the RULE — that they must not be pooled — "
        "in the passage that teaches the axis, which is the one instruction it exists to give")
    assert "model_capabilities" in s, "the agent is not pointed at the registry that answers 'can this be asked'"


def test_the_prompt_says_what_the_shared_column_means_under_each_model():
    """The trap is that ONE column name means three different things. Naming the modes is not enough."""
    low = agent.SYSTEM.lower()
    assert "fraction_trna_charged" in low
    i = low.find("fraction_trna_charged")
    window = low[max(0, i - 500):i + 900]
    for mode in capability.ELONGATION_MODES:
        assert mode in window, (
            f"the prompt discusses fraction_trna_charged without naming {mode!r} nearby — a reader is left to "
            f"guess which meaning applies")


# ---------------------------------------------------------------------------------------------------------
# (2) The evidence the agent actually receives.
# ---------------------------------------------------------------------------------------------------------

# Tools whose ANSWER depends on the elongation model. Each must say which model it answered under, or the
# number it returns cannot be interpreted — 86 independent measurements and one value broadcast 86 times are
# the same shape on the wire.
MODE_SENSITIVE = [
    ("model_capabilities", {"mode": "steady_state"}),
    ("trna_families", {"design": "gene_knockout/KO:argS"}),
    ("selective_charging", {"design": "gene_knockout/KO:argS"}),
]


@pytest.mark.parametrize("name,args", MODE_SENSITIVE)
def test_a_mode_sensitive_tool_names_the_model_it_answered_under(name, args):
    out = tools.dispatch(name, args)
    if out.get("error"):
        pytest.skip(f"{name}: {out['error']}")
    assert out.get("elongation_model") in capability.ELONGATION_MODES, (
        f"{name} returned an answer without naming the elongation model it came from "
        f"(got {out.get('elongation_model')!r}). Its numbers cannot be interpreted without it.")


def test_the_corpus_survey_discloses_which_arm_it_ranked():
    """`survey_corpus` is the anti-anchoring primitive the agent must consume first. Since ARM-1 it narrows to
    one arm — so it has to say which, or the agent reads a filtered corpus as the whole one."""
    out = tools.dispatch("survey_corpus", {})
    if out.get("error"):
        pytest.skip(out["error"])
    arm = out.get("arm")
    if arm is None:
        rows = out.get("coverage", {})
        assert rows, "survey_corpus returned neither an arm note nor coverage"
        return                     # single-arm corpus: nothing was narrowed, nothing to disclose
    assert arm["arm"]["elongation_model"] in capability.ELONGATION_MODES
    assert arm.get("rows_excluded", 0) >= 0 and arm.get("why"), (
        "the survey narrowed to one arm without saying what it left out")


def test_every_listed_run_carries_its_model():
    """`list_results` is how the agent finds runs to read. A row without its mode invites pooling."""
    out = tools.dispatch("list_results", {"gene": "argS"})
    if not out.get("results"):
        pytest.skip("no argS runs in this checkout")
    missing = [r["id"] for r in out["results"] if not r.get("elongation_model")]
    assert not missing, f"{len(missing)} listed run(s) carry no elongation_model: {missing[:4]}"


# ---------------------------------------------------------------------------------------------------------
# (3) The refusal has to survive the trip into the model's context.
# ---------------------------------------------------------------------------------------------------------

def test_a_mode_refusal_reaches_the_agent_through_dispatch():
    """Tested through `tools.dispatch`, the boundary the AGENT calls — not `capability.check` directly.

    A registry that refuses correctly but whose refusal never leaves the tool layer is a registry the agent
    cannot obey.
    """
    out = tools.dispatch("model_capabilities", {"mode": "steady_state"})
    iso = [c for c in out.get("cannot_represent", []) if "isoacceptor" in c["capability"]]
    assert iso, "the isoacceptor capability is not refused under steady_state at the tool boundary"
    entry = iso[0]
    assert entry.get("why_not"), "a refusal with no reason cannot be acted on"
    assert entry.get("instead") and entry.get("why_the_output_misleads"), entry


@pytest.mark.parametrize("cap", [4000, 1500, 600, 200])
def test_a_refusal_is_not_truncated_into_something_that_looks_like_a_result(cap):
    """`_truncate_tool_result` is the single funnel through which every tool result enters the model's context.

    A refusal that loses its refusal-ness on the way in is worse than one that never fired: the agent would
    see a payload about a capability with no indication it was denied. Checked at aggressive caps because the
    funnel shrinks lists first and falls back to a hard slice when the scalars alone exceed the cap.
    """
    res = capability.check("per_isoacceptor_trna_charging")
    assert res["can_answer"] is False
    s = agent._truncate_tool_result(res, cap)
    assert "can_answer" in s or "refusal" in s, (
        f"at cap={cap} the refusal was truncated past every marker of being a refusal: {s[:160]}")


def test_a_refusal_carries_no_number_at_the_agent_boundary():
    """The contract from test_capability, re-asserted where the AGENT sees it: refusals carry no numeric field,
    so nothing in a refusal can be mistaken for a measurement."""
    out = tools.dispatch("model_capabilities", {"mode": "steady_state"})
    for entry in out.get("cannot_represent", []):
        nums = [k for k, v in entry.items() if isinstance(v, (int, float)) and not isinstance(v, bool)]
        assert not nums, f"{entry['capability']} refusal carries numeric field(s) {nums}"


# ---------------------------------------------------------------------------------------------------------
# The agent must be able to ask whether a PARAMETER is a fit — and must not be told to buy a rebuild for it.
# ---------------------------------------------------------------------------------------------------------

def test_the_agent_can_ask_whether_a_half_life_is_a_fit():
    """Before this, no tool surfaced a degradation rate at all, so the agent could not answer the question
    `propose_rebuild`'s own description told it to recognise."""
    assert "deg_rate_provenance" in tools._DISPATCH
    out = tools.dispatch("deg_rate_provenance", {"unit": "rpmJ"})
    if out.get("error"):
        pytest.skip(out["error"])
    assert out["verdict"] in ("NOT A FIT", "FIT (or no such unit)")
    assert out.get("kb_summary"), "the per-unit answer arrives with no whole-fit context"


def test_a_missing_unit_is_not_reported_as_a_fit():
    """The three-way answer. Collapsing 'I could not find it' into 'it is fine' is the silent-absence failure
    this whole registry exists to prevent, and here the two share a verdict — so the caveat must say so."""
    out = tools.dispatch("deg_rate_provenance", {"unit": "zzz_no_such_unit"})
    if out.get("error"):
        pytest.skip(out["error"])
    assert out["matches"] == []
    assert "no such unit" in out["verdict"].lower() or "no such unit" in out.get("caveat", "").lower(), out


def test_propose_rebuild_no_longer_routes_a_half_life_question_to_a_rebuild():
    """The live mis-routing this closes. `propose_rebuild`'s description named 'is that 91.2-min half-life a
    fitted value or the estimator's floor?' as a REASON TO REBUILD — ~7 minutes plus comparator runs plus a
    new arm — for a question a free read now answers in seconds."""
    d = next(t["description"] for t in tools.TOOLS if t["name"] == "propose_rebuild")
    assert "91.2-min half-life a fitted value" not in d, (
        "propose_rebuild still offers a rebuild as the way to answer whether a half-life is fitted")
    assert "deg_rate_provenance" in d, "it does not point at the cheap tool that answers this instead"
