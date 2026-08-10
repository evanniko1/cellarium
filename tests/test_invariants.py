"""H-17a — the invariant catalogue published machine-readably, and the probes that keep it from being a comment.

The rules that make a corpus number mean something lived in `support.py`, `capability.py` and tribal
knowledge — three places a stranger never opens — while a cloner reaches the same Parquet by CLI, web app,
MCP, or `duckdb` at a shell prompt. `data/INVARIANTS.json` is the one artifact all four populations can read.

What is tested here is not that the catalogue exists but that it cannot quietly become false:

  * every probe it names must be a code `integrity_check` actually emits — a catalogue that claims
    verification which is not happening is worse than no catalogue;
  * an invariant with no probe must SAY it has none, so the 8-of-17 ratio is visible rather than implied;
  * a missing catalogue must read as an ABSENCE, never as "no invariants apply";
  * the write-path fixes (B2/B4) must hold at the boundary, not just in a docstring.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.cellarium import invariants, manifest, survey  # noqa: E402

# ---------------------------------------------------------------------------------------------------------
# The catalogue.
# ---------------------------------------------------------------------------------------------------------

def test_the_catalogue_loads_and_is_structurally_sound():
    problems = invariants.validate()
    assert not problems, problems
    doc = invariants.load()
    assert doc["n_invariants"] == len(doc["invariants"]) == 17


def test_every_named_probe_is_a_code_integrity_check_actually_emits():
    """The failure this exists to prevent: a catalogue naming `D14` for an invariant, nobody noticing that
    `integrity_check` never emits D14, and the entry reading as verified forever. `capability.py` established
    the pattern — declare, then grep the source of truth rather than believing the declaration."""
    import inspect
    src = inspect.getsource(manifest.integrity_check)
    named = {(i["probe"] or {}).get("integrity_check") for i in invariants.load()["invariants"]}
    named.discard(None)
    missing = sorted(c for c in named if f'add("{c}"' not in src and f"'{c}'" not in src)
    assert not missing, f"the catalogue claims these probes exist and integrity_check never emits them: {missing}"


def test_an_invariant_without_a_probe_says_so_rather_than_leaving_it_blank():
    """"A declaration nobody verifies is a comment." An empty probe field would let an unverified rule sit in
    the catalogue looking like the verified ones."""
    for i in invariants.load()["invariants"]:
        probe = i["probe"]
        assert probe.get("how"), f"{i['id']}: no probe and no reason given"
        if not probe.get("integrity_check"):
            assert len(probe["how"]) > 20, f"{i['id']}: 'no probe because' needs an actual reason"


def test_the_enforced_fraction_is_reported_not_implied():
    """"17 invariants" and "8 enforced invariants" are very different claims about a corpus."""
    cov = invariants.coverage()
    assert cov["n_invariants"] == 17
    assert 0 < cov["n_verified"] < cov["n_invariants"], cov
    assert cov["n_verified"] + cov["n_unverified"] == cov["n_invariants"]
    assert all(u["why_no_probe"] for u in cov["unverified"])


def test_a_code_maps_back_to_the_invariant_it_verifies():
    """A violation reading `D3` is opaque; reading `D3 — INV-7, no design key from a nullable column` is not."""
    hits = invariants.probed_by("D3")
    assert hits and hits[0]["id"] == "INV-7"


def test_a_missing_catalogue_reads_as_an_absence_not_as_no_invariants(tmp_path):
    """The silent-absence bug class, in the one place it would be most damaging: a reader concluding from an
    empty file that this corpus has no rules."""
    out = invariants.load(tmp_path / "nope.json")
    assert out.get("error") and "ABSENCE" in out.get("note", "")
    assert not out.get("invariants")


def test_the_catalogue_is_valid_json_on_disk():
    """It is loaded by the HF dataset card and the MCP surface, neither of which is Python."""
    doc = json.loads(Path("data/INVARIANTS.json").read_text(encoding="utf-8"))
    assert doc["schema"] == "cellarium/invariants/1"
    assert {i["id"] for i in doc["invariants"]} == {f"INV-{n}" for n in range(1, 18)}


# ---------------------------------------------------------------------------------------------------------
# B2 — non-nullable at the write path.
# ---------------------------------------------------------------------------------------------------------

def _design(**kw):
    from src.cellarium.model import Design
    return Design(**kw)


def test_a_timeline_run_no_longer_writes_a_null_condition():
    """Invariant INV-7's incident: every `timeline` run stored `condition=NULL`, so an amino-acid UPSHIFT and
    a DOWNSHIFT both keyed to `timeline/None` and were averaged as four seeds of one design."""
    up = manifest._condition_of(_design(perturbation="timeline",
                                        timeline="0 minimal, 1200 minimal_plus_amino_acids"))
    down = manifest._condition_of(_design(perturbation="timeline",
                                          timeline="0 minimal_plus_amino_acids, 1200 minimal"))
    assert up and down and up != down, (up, down)
    assert "up" in up and "down" in down


def test_an_unparseable_timeline_says_so_instead_of_guessing():
    """A value invented to avoid a NULL is worse than the NULL. `shift:unparsed` is a statement about the
    RECORD; a made-up direction would be a statement about the experiment."""
    assert manifest._condition_of(_design(perturbation="timeline", timeline="garbage")) == "shift:unparsed"


def test_a_plain_condition_is_passed_through_untouched():
    assert manifest._condition_of(_design(perturbation="wildtype", condition="basal")) == "basal"


def test_crashed_is_coerced_to_a_real_boolean():
    """INV-4: `WHERE NOT crashed` drops a NULL row, `if not row["crashed"]` keeps it, and neither raises."""
    import inspect
    src = inspect.getsource(manifest._flat_row)
    assert '"crashed": bool(crashed)' in src, "a caller can still put None in a filter column"


# ---------------------------------------------------------------------------------------------------------
# B4 — the refusal-carrying fields as real columns.
# ---------------------------------------------------------------------------------------------------------

def test_provenance_is_written_as_a_column_not_computed_at_read_time():
    """It was Python-only: a cloner reading the parquet with duckdb got no in-sample flag at all, and could
    read agreement in a ParCa-FITTED condition as predictive validation (INV-9)."""
    import inspect
    src = inspect.getsource(manifest._flat_row)
    assert '"provenance": _prov_tag(' in src
    assert manifest._prov_tag(_design(perturbation="wildtype", condition="basal")) in (
        "in_sample", "out_of_sample")


# ---------------------------------------------------------------------------------------------------------
# The probes, and the distinction that keeps them switched on.
# ---------------------------------------------------------------------------------------------------------

def test_the_three_new_probes_are_documented_where_the_others_are():
    doc = manifest.integrity_check.__doc__ or ""
    for code in ("D10", "D11", "D12"):
        assert code in doc, f"{code} is emitted but not listed in the invariant docstring"


def test_drift_and_standing_conditions_are_not_the_same_thing():
    """D11 is a KNOWN structural fact — the design key genuinely cannot express `kb_sha256`, ARM-1 handles it
    at the read boundary, and no re-index will change it. Failing CI daily on something nobody can fix is how
    a check gets switched off, which is the same outcome as not having it. But it must still be REPORTED
    every run, not suppressed."""
    res = manifest.integrity_check(check_disk=False)
    if res.get("n_rows", 0) == 0:
        pytest.skip("no local manifest")
    assert "standing_conditions" in res and "n_drift" in res
    assert res["ok"] == (res["n_drift"] == 0)
    for v in res["standing_conditions"]:
        assert v["severity"] == "structural" and v["fix"], v


def test_the_null_filter_probe_is_clean_after_the_backfill():
    """D10 found 16 rows with a NULL `condition`; `backfill_condition` filled them and the write path stops
    new ones. If this goes red, a NULL filter column is back."""
    res = manifest.integrity_check(check_disk=False)
    if res.get("n_rows", 0) == 0:
        pytest.skip("no local manifest")
    d10 = [v for v in res["violations"] if v["invariant"] == "D10"]
    assert not d10, d10


def test_the_partition_probe_checks_all_three_keys_not_just_the_one_in_the_projection():
    """The under-check that shipped for ten minutes: `store.list_results` projects `elongation_model` but not
    `kb_sha256` or `operons`, so the first version of D11 silently checked one key of three and reported a
    clean corpus. A probe that under-checks is worse than no probe — it reads as verification."""
    res = manifest.integrity_check(check_disk=False)
    if res.get("n_rows", 0) == 0:
        pytest.skip("no local manifest")
    d11 = [v for v in res["violations"] if v["invariant"] == "D11"]
    if d11:
        assert "kb_sha256" in d11[0]["message"], d11[0]["message"]


def test_the_backfill_refuses_to_move_an_experiments_identity():
    """The precondition the backfill checks, asserted directly: for a row with no recoverable tag in its
    label, `design_tag` falls back to `condition` — so writing that column would silently re-identify the
    experiment. Fixing a NULL by renaming an experiment is a worse defect than the NULL."""
    pre_label = {"label": "oldstyle", "condition": None, "timeline": None, "perturbation": "wildtype"}
    assert survey.design_tag(pre_label) == "basal"
    assert survey.design_tag({**pre_label, "condition": "shift:up:a->b"}) == "shift:up:a->b", (
        "precondition for the refusal: setting `condition` DOES move identity on a pre-label row")


def test_the_backfill_is_idempotent():
    """Running it twice must fill nothing the second time, or a routine re-run rewrites the corpus for no
    reason and mints shard churn."""
    res = manifest.backfill_condition(dry_run=True)
    if res.get("error"):
        pytest.skip(res["error"])
    assert res["filled"] == 0, f"{res['filled']} rows still carry a NULL condition after the backfill"
