"""PARCA-6's free prerequisite — a stability claim resting on a value that is not a fit gets caught.

854 of 3,133 mRNA units (27%), carrying 12.087% of mRNA expression, hold a degradation rate that is a bound
or the population mean rather than an inference from data. `deg_rate_provenance` will tell an agent which,
but only if the agent thinks to ask, and the failure mode is exactly that nobody thinks to ask.

WHY THIS COMES BEFORE THE ARM. PARCA-6 would carry an `unknown` class into `sim_data`, costing a comparability
arm: `transcription.py` becomes the 45th overlay file, `kb_sha256` moves, and none of the 363 existing rows
pool with the result. If the claim is caught where it is MADE, that arm may not be needed. Answering costs
nothing; the arm costs comparator re-runs.

THE CONJUNCTION IS THE DESIGN, and most of these tests are about it: the check fires only when a sentence
BOTH names a not-a-fit unit AND makes a degradation claim. Naming `rpmJ` while discussing translation is not
a half-life claim, and a check that flagged it would train readers to skip the annotation — which is how the
one that matters gets skipped too.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.cellarium import deg_claims  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh():
    deg_claims._cache = None
    yield
    deg_claims._cache = None


def _has_baseline() -> bool:
    return Path("data/parca/deg_rate_baseline.json").exists()


# ---------------------------------------------------------------------------------------------------------
# The conjunction.
# ---------------------------------------------------------------------------------------------------------

def test_a_stability_claim_about_a_bound_unit_is_caught():
    """`rpmJ` sits on the rate FLOOR and carries 1.58% of mRNA expression — the single most-expressed
    not-a-fit unit in the corpus. "Unusually stable" about it is a claim about the estimator's lower bound."""
    if not _has_baseline():
        pytest.skip("no frozen baseline in this checkout")
    r = deg_claims.check("rpmJ mRNA is unusually stable, with a half-life of 91.2 min.")
    assert r["verdict"] == "claims_on_non_fits"
    assert r["hits"][0]["unit"].startswith("rpmJ") and r["hits"][0]["class"] == "floor"
    assert "FLOOR" in r["hits"][0]["means"]


def test_naming_the_same_gene_without_a_degradation_claim_is_silent():
    """THE false positive that would get this switched off. `rpmJ` appears in knockout discussions constantly
    and none of those is a half-life claim."""
    if not _has_baseline():
        pytest.skip("no frozen baseline in this checkout")
    r = deg_claims.check("The rpmJ knockout leaves rpmJ expressed and takes secY to zero.")
    assert r["verdict"] == "no_degradation_claims" and not r["hits"]


def test_a_degradation_claim_about_a_fitted_unit_is_clear_not_silent():
    """`clear` and `no_degradation_claims` are different states and the payload distinguishes them: one means
    the check looked and found nothing, the other means there was nothing to look at."""
    if not _has_baseline():
        pytest.skip("no frozen baseline in this checkout")
    r = deg_claims.check("Transcript half-lives across the panel are broadly similar.")
    assert r["verdict"] == "clear" and r["n_degradation_sentences"] == 1


def test_the_plural_of_the_key_term_is_matched():
    """A regression guard on a real false negative. The first version listed the substring "half-life" and
    missed "half-lives" — the plural shares no stem with the singular ("half-lif" vs "half-liv") — so the
    commonest form of the term this check exists for did not register as a degradation claim at all."""
    for phrase in ("half-life", "half-lives", "half life", "halflife"):
        assert deg_claims._DEG_RE.search(f"the {phrase} of this transcript"), phrase


def test_an_imputed_unit_is_caught_under_its_bare_gene_name():
    """Prose says `EG10149`; the corpus says `EG10149_RNA[c]`. A check that only matched the full unit id
    would never fire on anything an agent actually writes."""
    if not _has_baseline():
        pytest.skip("no frozen baseline in this checkout")
    r = deg_claims.check("EG10149 shows slow turnover relative to the reference.")
    assert r["verdict"] == "claims_on_non_fits"
    assert r["hits"][0]["class"] == "imputed"


# ---------------------------------------------------------------------------------------------------------
# Fail closed, and annotate rather than rewrite.
# ---------------------------------------------------------------------------------------------------------

def test_a_missing_baseline_reports_that_it_could_not_run(tmp_path):
    """The silent-absence bug class. With no baseline the check must NOT return `clear` — an unavailable
    check reported as a pass is the failure this project keeps meeting."""
    r = deg_claims.check("rpmJ is unusually stable.", path=tmp_path / "nope.json")
    assert r["verdict"] == "could_not_verify"
    assert "never that the answer passed" in r["why"]
    assert "could not run" in deg_claims.annotation(r)


def test_a_corrupt_baseline_is_an_error_not_an_empty_pass(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert deg_claims.check("rpmJ is stable.", path=bad)["verdict"] == "could_not_verify"


def test_the_annotation_is_appended_and_never_rewrites():
    """Same rule as the provenance check: the claim is left exactly as written and the note is the record."""
    if not _has_baseline():
        pytest.skip("no frozen baseline in this checkout")
    prose = "rpmJ mRNA is unusually stable."
    from src.cellarium import reconcile
    out = reconcile.check_and_annotate(prose)
    assert out.startswith(prose), "the original answer text was modified"
    assert "not fits" in out


def test_a_clear_answer_gets_no_banner():
    """A note on every answer saying "checked, fine" is a note readers learn to skip, and then the one that
    matters is skipped too."""
    if not _has_baseline():
        pytest.skip("no frozen baseline in this checkout")
    assert deg_claims.annotation(deg_claims.check("Half-lives were computed for every design.")) == ""


def test_it_names_what_the_value_actually_is_not_just_that_it_is_suspect():
    """"Not a fit" is not actionable. Which of the three — a floor, a ceiling, or the population mean — is
    what a reader needs to judge the claim, and it is the same vocabulary `deg_rate_provenance` uses."""
    if not _has_baseline():
        pytest.skip("no frozen baseline in this checkout")
    note = deg_claims.annotation(deg_claims.check("rpmJ mRNA is unusually stable."))
    assert "FLOOR" in note and "% of mRNA expression" in note
    assert "deg_rate_provenance" in note, "the note should point at the tool that gives the full picture"


# ---------------------------------------------------------------------------------------------------------
# It has to be free, or it will not survive.
# ---------------------------------------------------------------------------------------------------------

def test_the_check_needs_no_model_image():
    """The load-bearing property. A live `deg_rate_provenance` call costs ~90 s in a container; run per turn
    that would be switched off within a week. All 854 ids are already frozen in the committed baseline."""
    import inspect
    src = inspect.getsource(deg_claims)
    for forbidden in ("docker", "subprocess", "_reader_worker", "reader.deg_rate_provenance"):
        assert forbidden not in src, f"the claim path reaches for {forbidden} — it is no longer free"


def test_the_frozen_baseline_carries_every_not_a_fit_unit():
    """If the baseline stopped carrying per-unit ids this check would silently match nothing and report
    `clear` on every answer — passing by being empty."""
    if not _has_baseline():
        pytest.skip("no frozen baseline in this checkout")
    doc = json.loads(Path("data/parca/deg_rate_baseline.json").read_text(encoding="utf-8"))
    units = doc["units_not_a_fit"]
    n = sum(len(v) for k, v in units.items() if isinstance(v, dict))
    assert n == doc["not_a_fit"]["n_units"] == 854, (n, doc["not_a_fit"]["n_units"])


def test_the_note_names_the_knowledge_base_it_describes():
    """The classes are a property of ONE fit. A note that did not say which would be read as a fact about the
    model rather than about a knowledge base that can be rebuilt."""
    if not _has_baseline():
        pytest.skip("no frozen baseline in this checkout")
    r = deg_claims.check("rpmJ mRNA is unusually stable.")
    assert str(r["kb_sha256"]).startswith("3b2f8ebd")
    assert "3b2f8ebd" in deg_claims.annotation(r)
