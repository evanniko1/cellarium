"""A mechanism the model cannot represent must produce a refusal, never a number.

Written because we measured a within-family tRNA charging spread of exactly 0.00e+00 and published it as a
result. It was an algebraic identity: one per-amino-acid scalar broadcast across 86 isoacceptor columns. The
model was not silent about a hard question — it was structurally incapable of the question and answered anyway,
with a value indistinguishable from a measurement. These tests pin the guarantee that replaces that.
"""

from __future__ import annotations

import os

import pytest

from cellarium import capability, tools


def test_the_capability_that_burned_us_is_declared_absent():
    c = capability.get("per_isoacceptor_trna_charging")
    assert c is not None and c.present is False
    # the refusal must name the mechanism, the substitute, AND why the output misleads
    r = c.refusal()
    assert "CANNOT" in r
    assert "aa_from_trna" in r, "the refusal must name the actual aggregation that causes it"
    assert "arithmetic" in r or "IDENTICAL BY CONSTRUCTION" in r
    assert "v3.0.1" in r, "must point at where the mechanism does exist"


def test_an_unsupported_capability_returns_a_refusal_and_forbids_a_number():
    """THE contract Cellwright depends on: can_answer False always carries a refusal and never a value."""
    for key in (c.key for c in capability.missing()):
        res = capability.check(key)
        assert res["can_answer"] is False
        assert res.get("refusal"), key
        assert res.get("report_a_number") is False, key
        # `bool` subclasses `int` in Python, so a type check alone flags the flags. Exclude bools explicitly.
        numeric = [k for k, v in res.items() if isinstance(v, (int, float)) and not isinstance(v, bool)]
        assert not numeric, \
            f"{key}: a refusal must not carry numeric field(s) {numeric} — mistakable for a result"


def test_an_undeclared_capability_is_not_treated_as_absent():
    """Absence of a declaration is not evidence of absence of the mechanism — the silent-absence rule again."""
    res = capability.check("some_mechanism_nobody_declared")
    assert res["known"] is False and res["can_answer"] is None
    assert "not evidence of absence" in res["note"]


def test_declarations_agree_with_the_model_checkout():
    """Declared AND probed. A stale `present=True` is confidently-wrong metadata, which is worse than none."""
    if not (os.environ.get("WCECOLI_DIR") and os.path.isdir(os.environ["WCECOLI_DIR"])):
        pytest.skip("no model checkout to probe")
    a = capability.audit()
    assert a["ok"], f"registry disagrees with the checkout: {a['disagreements']}"


def test_probing_without_a_checkout_says_unverified_rather_than_confirmed():
    res = capability.probe(wcecoli="/definitely/not/a/checkout")
    assert all(r.agrees for r in res)
    assert all("UNVERIFIED" in r.note for r in res), \
        "with nothing to probe, the result must read as unverified — never as confirmation"


def test_the_agent_has_the_tool_and_is_told_to_use_it():
    from cellarium import agent
    assert "model_capabilities" in tools._DISPATCH, "the tool must be dispatchable by the agent loop"
    names = {t["name"] for t in tools.TOOLS}
    assert "model_capabilities" in names
    low = agent.SYSTEM.lower()
    assert "model_capabilities" in agent.SYSTEM
    assert "cannot represent" in low and "measurement of zero" in low
    assert "isoacceptor" in low, "the prompt must name the concrete trap, not just the principle"


def test_the_tool_surface_separates_can_from_cannot():
    out = tools.model_capabilities()
    cannot = {c["capability"] for c in out["cannot_represent"]}
    can = {c["capability"] for c in out["can_represent"]}
    assert "per_isoacceptor_trna_charging" in cannot
    assert "per_amino_acid_trna_charging" in can, "what the model DOES do must be declared too"
    assert not (cannot & can)
    for c in out["cannot_represent"]:
        assert c["instead"] and c["why_the_output_misleads"], c["capability"]
