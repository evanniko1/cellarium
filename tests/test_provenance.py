"""M-3: the in-sample/out-of-sample tagger must gate on the CONDITION, not short-circuit every 'wildtype' run to
in-sample. A wildtype run in an unfitted medium (wildtype/acetate) is a genuine out-of-sample prediction — tagging
it in-sample would over-credit agreement as validation."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cellarium import provenance  # noqa: E402


def test_wildtype_is_gated_on_condition():
    assert provenance.tag("wildtype", "basal") == "in_sample"
    assert provenance.tag("wildtype", None) == "in_sample"              # canonical wildtype/basal
    assert provenance.tag("wildtype", "acetate") == "out_of_sample"     # the M-3 bug: was wrongly in_sample
    assert provenance.tag("wildtype", "succinate") == "out_of_sample"


def test_condition_and_perturbations_unchanged():
    assert provenance.tag("condition", "with_aa") == "in_sample"
    assert provenance.tag("condition", "no_oxygen") == "in_sample"
    assert provenance.tag("condition", "acetate") == "out_of_sample"
    assert provenance.tag("gene_knockout", "basal") == "out_of_sample"
    assert provenance.tag("ppgpp_conc", "basal") == "out_of_sample"
    assert provenance.classify("wildtype", "acetate")["provenance"] == "out_of_sample"


def test_run_environment_reproducibility_bundle():
    """H-3: the per-run environment bundle carries the interpreter, git commit, and pinned dep versions — recorded
    so a run reproduces against the exact code + stack. Best-effort: every field degrades gracefully, never raises."""
    env = provenance.run_environment()
    assert isinstance(env["python"], str) and env["python"].count(".") >= 2
    assert set(env["packages"]) == {"anthropic", "pydantic", "numpy", "duckdb", "pyarrow"}
    assert all((v is None or isinstance(v, str)) for v in env["packages"].values())
    assert env["git_commit"] is None or isinstance(env["git_commit"], str)   # a short sha in a checkout, or None


def test_git_commit_is_non_fatal_when_git_absent(monkeypatch):
    """A missing git / non-checkout must not break a run — _git_commit swallows it and returns None."""
    import subprocess

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("no git")))
    assert provenance._git_commit() is None


def test_in_sample_set_is_pinned_against_silent_drift():
    """M-4: the in-sample condition set is the source of truth for the in/out-of-sample tag, so it's pinned here —
    a change to provenance.IN_SAMPLE_CONDITIONS trips this test, forcing a conscious update + justification instead
    of silently drifting out of sync with what ParCa actually fits."""
    assert provenance.IN_SAMPLE_CONDITIONS == {"basal", "glc_20mM", "glc_5mM", "glc_2mM", "with_aa", "no_oxygen"}
    # and the tag reflects it: a fitted condition is in-sample; a network-derived one (or any perturbation) is not
    assert provenance.tag("wildtype", "with_aa") == "in_sample"
    assert provenance.tag("wildtype", "minus_magnesium") == "out_of_sample"   # network-derived -> conservative
