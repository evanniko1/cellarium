"""The CORPUS-REBUILD-1 audit must not quietly propose destroying evidence.

The one way this script could do real harm is by recommending retirement of rows that carry information no
sibling row has. `reportable` is NOT that test: a crashed knockout is the evidence the knockout is lethal
(`hygiene.rows("lethality")` reads all 363 rows for exactly that), `noop_knockout` is a finding about a
perturbation that does not do what its name says, and `no_division` separates "arrested" from "never
measured". These pin the parts of the audit a careless edit would break.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

import corpus_audit as A  # noqa: E402


@pytest.fixture(scope="module")
def audit():
    try:
        return A.audit()
    except Exception as exc:                     # no manifest in a CI checkout
        pytest.skip(f"no readable corpus here: {type(exc).__name__}")


def test_a_crashed_knockout_is_never_proposed_for_retirement(audit):
    """The load-bearing safety property. Crashed KO rows ARE the lethality result."""
    for d in audit["designs"]:
        if d["qc"].get("crashed") and d["n_evidence"]:
            assert d["verdict"] == "RERUN", (d["perturbation"], d["condition"], d["verdict"])


def test_only_corpus_flagged_surplus_is_ever_retirable(audit):
    """Retirement is limited to rows the corpus itself labelled `over_replicated` or `empty`, and only where
    a sibling row of the same design already carries the information."""
    for d in audit["designs"]:
        assert d["n_retirable"] <= d["qc"].get("over_replicated", 0) + d["qc"].get("empty", 0)


def test_designs_are_distinguished_by_timeline_and_arm_not_just_name(audit):
    """Three `gene_knockout/KO:leuB` entries exist and are DIFFERENT experiments — different timelines, two
    different knowledge bases. Collapsing them by name would merge a starvation arm into a plain knockout."""
    leub = [d for d in audit["designs"]
            if d["perturbation"] == "gene_knockout" and d["condition"] == "KO:leuB"]
    assert len(leub) >= 2
    assert len({(d["timeline"], d["arm"]) for d in leub}) == len(leub)


def test_the_cost_estimate_does_not_flatter_the_plan():
    """13 min/generation is the UPPER end of 11 measured runs (9m13s-13m03s). An estimate that flatters the
    plan is worse than one that over-books."""
    assert A.MIN_PER_GENERATION >= 13.0


def test_raw_availability_is_three_way_not_a_boolean(audit):
    """A row whose raw is gone locally is not lost if HF holds it, and either way the DESIGN is recorded so it
    can be re-run. Collapsing this to present/absent would overstate what has actually been lost."""
    t = audit["totals"]
    for k in ("raw_local", "raw_hf", "raw_gone", "raw_gone_reportable"):
        assert k in t
    assert t["raw_local"] + t["raw_gone"] <= t["n_rows"] + t["raw_hf"]
