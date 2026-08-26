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


def test_a_crashed_KNOCKOUT_is_never_proposed_for_retirement(audit):
    """The load-bearing safety property: a crashed KO row IS the lethality result.

    Scoped to knockouts on purpose. The first version matched any crashed design with evidence, which read as
    the same rule but is not — it also covered `metabolism_kinetic_objective_weight`, a PARAMETER sweep whose
    every dose including the model's own default crashed. That is a variant that never worked, and refusing to
    retire it would have kept 24 rows of dev debris in the corpus forever on the strength of a test whose name
    says "knockout". A guard that quietly covers more than it claims is as much of a problem as one that
    covers less."""
    for d in audit["designs"]:
        if "knockout" in d["perturbation"] and d["qc"].get("crashed") and d["n_evidence"]:
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


def test_a_sweep_is_only_retired_when_its_OWN_DEFAULT_crashed(audit):
    """The discriminator is the default crashing, NOT "everything crashed" — a genuinely lethal perturbation
    SHOULD crash at every dose, and retiring on that alone would delete real lethality results."""
    for d in audit["designs"]:
        if d["verdict"] == "RETIRE" and "default value crashed" in str(d["retire_reason"]):
            assert d["perturbation"] in A.MODEL_DEFAULTS, d["perturbation"]


def test_the_default_comes_from_the_model_not_from_a_label():
    """THE fix for a discriminator that was luck rather than a rule. Matching the string "default" in a
    condition name caught metabolism_kinetic_objective_weight only because someone wrote `kin_w:1e-7_default`,
    and MISSED metabolism_secretion_penalty, which is just as broken but labels its doses as bare numbers.
    These two values were read out of sim_data (kb 3b2f8ebd) and cross-checked against the variants' own
    source: SECRETION_PENALTY[4] == 0.001 with a docstring saying "4: control"."""
    assert A.MODEL_DEFAULTS["metabolism_secretion_penalty"] == 1e-3
    assert A.MODEL_DEFAULTS["metabolism_kinetic_objective_weight"] == 1e-7
    assert A._swept_value("minimal|sec_pen:1e-3") == 1e-3, "bare-number labels must parse"
    assert A._swept_value("minimal|kin_w:1e-7_default") == 1e-7, "annotated labels must parse too"
    assert A._swept_value("basal") is None, "a non-sweep condition has no dose"


def test_an_unknown_sweep_is_never_retired_on_a_guess():
    """A sweep whose default is not in MODEL_DEFAULTS answers False, never True — it must surface for a human
    rather than be retired because it happens to be all-crashed."""
    rs = [{"condition": "minimal|foo:1", "qc": "crashed"},
          {"condition": "minimal|foo:2", "qc": "crashed"}]
    assert A._control_crashed("some_sweep_nobody_looked_up", rs) is False


def test_the_secretion_penalty_sweep_is_now_retired(audit):
    """It sat in DECIDE until its control was read from the model source on 2026-08-26. All 18 rows crashed,
    including sec_pen:1e-3, which IS the model's default — the same signature as the other sweep."""
    sp = [d for d in audit["designs"] if d["perturbation"] == "metabolism_secretion_penalty"]
    assert sp, "the sweep is gone from the corpus — re-check this test"
    assert all(d["verdict"] == "RETIRE" for d in sp), [d["verdict"] for d in sp]


def test_superseded_rows_are_only_retired_when_a_DEEPER_run_really_exists(audit):
    """The supersession claim is verified per row against the same design and the same knowledge base, not
    assumed from the date. Without that check this would retire a 1-generation run that is the only copy."""
    for d in audit["designs"]:
        if d["n_retire_rows"] and "superseded" in str(d["retire_reason"]):
            assert "deeper run(s)" in d["retire_reason"]
            assert d["n_rows"] > d["n_retire_rows"] or d["verdict"] == "RETIRE"
