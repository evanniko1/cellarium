"""Y10: the in-sample tag follows what ParCa actually fits, per quantity, and says who decided to fit it.

ParCa builds a cell specification for every row of the condition table: composition is fitted to the row's doubling
time and the targets of its active/inactive factors are set from their fitted fold changes
(fit_sim_data_1.buildCombinedConditionCellSpecifications, read 2026-11-25). The earlier rule tagged six conditions
in-sample and called the rest "network-derived"; that premise was wrong. Two of its pinned cases are reversed here
on purpose:

  * wildtype/acetate was called the "M-3 bug" when tagged in-sample. Acetate (136 min) and succinate (82 min) ship
    with the base simulator (CovertLab PR #895, 2020-06-08, in upstream master), fitted, with CRP active.
  * minus_magnesium was called network-derived (the H2 "Mg -> ribosome boundary"). It is a campaign row (65284c86,
    2026-04-15) fitted to 44 min copied from basal, with no factor active: its ribosome content equals basal's by
    construction, so H2's "failure" was the placeholder, not a model boundary.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cellarium import provenance  # noqa: E402


def test_growth_and_composition_are_in_sample_for_every_fitted_condition():
    for cond in ("basal", "with_aa", "acetate", "succinate", "no_oxygen", "minus_magnesium", "plus_nitrate"):
        assert provenance.tag("condition", cond) == "in_sample", cond
        assert provenance.tag("wildtype", cond, quantity="growth_rate") == "in_sample", cond
    assert provenance.tag("wildtype", None) == "in_sample"               # canonical wildtype/basal


def test_perturbations_stay_out_of_sample():
    assert provenance.tag("gene_knockout", "basal") == "out_of_sample"
    assert provenance.tag("ppgpp_conc", "basal") == "out_of_sample"
    assert provenance.tag("rrna_operon_knockout", "minimal|rRNA_KO:4op") == "out_of_sample"


def test_a_fitted_factors_targets_are_in_sample_and_other_genes_are_not():
    assert provenance.tag("condition", "plus_nitrate", quantity="expression", gene="narG") == "in_sample"
    assert provenance.tag("condition", "plus_nitrate", quantity="expression", gene="lacZ") == "out_of_sample"
    assert provenance.tag("condition", "minus_magnesium", quantity="expression", gene="narG") == "out_of_sample"


def test_an_emergent_quantity_in_a_fitted_condition_is_out_of_sample():
    assert provenance.tag("condition", "acetate", quantity="fraction_trna_charged") == "out_of_sample"


def test_the_fit_is_attributed_with_its_basis():
    ac = provenance.classify("condition", "acetate")
    assert (ac["fitted_by"], ac["fit_commit"], ac["doubling_basis"]) == ("base", "03b327f7", "base_model")
    mg = provenance.classify("condition", "minus_magnesium")
    assert (mg["fitted_by"], mg["fit_commit"], mg["doubling_basis"]) == ("campaign", "65284c86", "placeholder")
    assert "basal" in mg["doubling_source"]
    no3 = provenance.classify("condition", "plus_nitrate")
    assert no3["fitted_by"] == "campaign" and no3["n_fitted_targets"] == 29


def test_a_run_before_the_decision_to_fit_is_out_of_sample():
    # the user's rule: a condition is in-sample only from the moment someone decided to fit it
    assert provenance.tag("condition", "plus_nitrate", run_date="2026-04-01") == "out_of_sample"
    assert provenance.tag("condition", "plus_nitrate", run_date="2026-05-01") == "in_sample"
    assert provenance.tag("condition", "acetate", run_date="2026-04-01") == "in_sample"   # base: fitted since 2020


def test_a_condition_the_table_does_not_have_is_out_of_sample():
    assert provenance.tag("condition", "minimal_glycerol_made_up") == "out_of_sample"


def test_the_record_is_pinned_against_silent_drift():
    fits = provenance.condition_fits()
    base = sorted(k for k, v in fits.items() if v["fitted_by"] == "base")
    assert base == ["acetate", "basal", "no_oxygen", "succinate", "with_aa"]
    placeholders = sorted(k for k, v in fits.items() if v["doubling_basis"] == "placeholder")
    assert len(placeholders) == 19 and "plus_nitrate" in placeholders and "glc_20mM" in placeholders


def test_run_environment_reproducibility_bundle():
    """H-3: the per-run environment bundle carries the interpreter, git commit, and pinned dep versions — recorded
    so a run reproduces against the exact code + stack. Best-effort: every field degrades gracefully, never raises."""
    env = provenance.run_environment()
    assert isinstance(env["python"], str) and env["python"].count(".") >= 2
    assert set(env["packages"]) == {"anthropic", "openai", "pydantic", "numpy", "scipy", "duckdb", "pyarrow",
                                    "huggingface_hub"}   # widened 2026-11-23 to what can change an eval (T.1)
    assert all((v is None or isinstance(v, str)) for v in env["packages"].values())
    assert env["git_commit"] is None or isinstance(env["git_commit"], str)   # a short sha in a checkout, or None


def test_git_commit_is_non_fatal_when_git_absent(monkeypatch):
    """A missing git / non-checkout must not break a run — _git_commit swallows it and returns None."""
    import subprocess

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("no git")))
    assert provenance._git_commit() is None
