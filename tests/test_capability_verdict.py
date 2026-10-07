"""CAP-V — `audit()` must not report a pass for a check it did not perform.

THE DEFECT, found 2026-10-06 while auditing this repo against its own paper. `probe()` returns
`agrees=True` for every capability when there is no wcEcoli checkout to grep, because nothing can disagree
with nothing. `audit()` then computed `bad = [r for r in res if not r.agrees]`, found it empty, and
returned `ok: True`. On a machine with no checkout the result was **9 capabilities, 0 disagreements, 0
comparisons, and a green flag**.

WHY IT MATTERED RATHER THAN BEING A CURIOSITY. `tools.model_capabilities` put that boolean into the payload
the AGENT reads as `audit: true`. wcEcoli needs a Stanford licence and is obtained separately, so on most
machines — including every machine a reviewer downloading the package would use — the model was being told
the registry had been checked against the model source when it had not been.

It is also this module's own subject matter turned on itself. `capability.py` exists because a simulator's
output labels can advertise resolution the model never computes; a summary flag advertising verification
that never happened is the same defect, one layer up. The repo had already recognised the shape once and
fixed it for a neighbour — `probe_launch_surface` carries a `verified` field with a comment saying to read
it before treating `ok` as evidence — and the probe results never got the equivalent.

THE FIX. `ProbeResult.verified` records whether a comparison was performed, separately from `agrees` which
records whether one failed. `audit()` exposes a three-valued `verdict` that cannot collapse the two:
`verified_consistent` · `unverified` · `disagreement`. `ok` is kept for existing callers and still means
"nothing disagreed".

These tests pin the distinction in both directions: an unverified audit must not read as a pass, and a
genuinely verified one must say so.
"""

from __future__ import annotations

import os

import pytest

from cellarium import capability, tools

NOT_A_CHECKOUT = "/definitely/not/a/wcecoli/checkout"


def test_probe_without_a_checkout_marks_every_result_unverified():
    """`agrees` and `verified` answer different questions and must stop sharing a representation."""
    res = capability.probe(wcecoli=NOT_A_CHECKOUT)
    assert res, "the probe must still enumerate the registry"
    assert all(r.agrees for r in res), "nothing can DISAGREE with nothing — that part was always right"
    assert not any(r.verified for r in res), "but nothing was VERIFIED either, and that must be visible"
    assert all("UNVERIFIED" in r.note for r in res)


def test_audit_reports_unverified_rather_than_a_pass():
    """The headline. A reader who checks the verdict cannot mistake 'did not check' for 'checked and fine'."""
    a = capability.audit(wcecoli=NOT_A_CHECKOUT)
    assert a["verdict"] == "unverified"
    assert a["verified"] is False
    assert a["n_verified"] == 0
    assert a["n_unverified"] == a["n_capabilities"]
    assert a["verified_against"] is None


def test_ok_is_retained_but_is_no_longer_the_field_to_read():
    """`ok` still means 'nothing disagreed', which is TRUE here and is exactly why it was misleading alone.

    This test documents the retained behaviour deliberately rather than changing it: existing callers read
    `ok`, and flipping it to False on a machine that simply has no checkout would fail CI daily on something
    nobody can fix — which is how a check gets switched off. The fix is a field that carries the missing
    distinction, not a boolean that cries wolf.
    """
    a = capability.audit(wcecoli=NOT_A_CHECKOUT)
    assert a["ok"] is True
    assert a["verdict"] != "verified_consistent", "…which is why `ok` alone must not be read as verification"
    assert "verdict" in (a.get("note") or ""), "the payload must tell a reader which field to trust"


def test_the_agent_is_not_told_the_registry_was_verified_when_it_was_not(monkeypatch):
    """The real-world consequence, pinned at the surface where it reached a model.

    `model_capabilities` is an LLM-facing tool. It used to emit `audit: true` here, which a model reading
    the payload would reasonably take as 'these declarations were checked against the simulator source'.
    """
    monkeypatch.delenv("WCECOLI_DIR", raising=False)
    out = tools.model_capabilities()
    assert out["audit"] == "unverified"
    assert out["audit"] is not True, "a bare True is what made this unreadable"


@pytest.mark.skipif(not (os.environ.get("WCECOLI_DIR") and os.path.isdir(os.environ.get("WCECOLI_DIR", ""))),
                    reason="no model checkout to probe — the verified half needs one")
def test_a_real_checkout_produces_a_verified_verdict():
    """The other direction. Without this the fix could be satisfied by always reporting `unverified`."""
    a = capability.audit()
    assert a["n_verified"] == a["n_capabilities"]
    assert a["verified"] is True
    assert a["verified_against"]
    assert a["verdict"] in ("verified_consistent", "disagreement"), \
        "with a checkout present the audit must reach a real conclusion, not abstain"
