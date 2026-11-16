"""The two disk-rate constants, and the arrest rule that decides which one a run belongs to.

Two defects, one shape. `calibration.calibrated()` restated the literals 0.65 and 1.58 instead of naming
`audit`'s declarations, so each number existed twice in the tree with nothing linking them: a mutation of
audit's copy could not be detected through calibration, and vice versa. And `from_corpus_disk`'s arrest rule
was `len(gens) < int(requested_generations)`, which cannot fire when that column is NULL — 215 of 369 manifest
rows, INCLUDING all four KO:dapA rows, the very run the 1.58 GB/gen figure was measured on. So the rule meant
to find arrested runs was structurally blind to the template arrested run, which is why the arrested stratum
sat at n = 0 and `gb_per_generation_arrested` stayed `basis: 'constant'` forever.

Kept out of `tests/test_calibration.py` so the strata rule has a module whose whole subject is the
classification, rather than being appended to the estimator's own smoke tests.

Run: python -m pytest tests/test_calibration_strata.py
"""

from __future__ import annotations

import pytest

from cellarium import audit, calibration


@pytest.fixture()
def empty_store(tmp_path, monkeypatch):
    """No observations at all, so every `_summary` falls back to its constant and `calibrated()` is reporting
    the DECLARED rate rather than a measurement. That is the state this repo is actually in for the disk
    strata: 164 `gb_per_generation` rows, 0 of them `arrested: true`."""
    monkeypatch.setattr(calibration, "OBSERVATIONS_PATH", tmp_path / "obs.json")
    return tmp_path / "obs.json"


# --- the two rates are declared ONCE ---------------------------------------------------------------

def test_the_disk_rates_fall_back_to_their_declared_values(empty_store):
    """Literal expectations against the declared constants: 0.65 for a dividing lineage, 1.58 for an arrested
    one. Written as literals so a drift in either declaration fails here instead of being absorbed."""
    cal = calibration.calibrated()
    assert cal["gb_per_generation_dividing"]["basis"] == "constant"
    assert cal["gb_per_generation_dividing"]["value"] == 0.65
    assert cal["gb_per_generation_arrested"]["basis"] == "constant"
    assert cal["gb_per_generation_arrested"]["value"] == 1.58


def test_calibration_reads_audits_declaration_rather_than_restating_the_number(empty_store, monkeypatch):
    """THE de-duplication assertion. Move `audit`'s constants and `calibrated()`'s fallbacks must move with
    them; if this module keeps its own copy of 0.65/1.58 the two drift silently and a mutation of either is
    invisible through the other. The sentinels are deliberately nothing like the real rates."""
    monkeypatch.setattr(audit, "GB_PER_GENERATION", 0.11)
    monkeypatch.setattr(audit, "GB_PER_GENERATION_ARRESTED", 9.99)
    cal = calibration.calibrated()
    assert cal["gb_per_generation_dividing"]["value"] == 0.11
    assert cal["gb_per_generation_arrested"]["value"] == 9.99


# --- which signal classified the row ---------------------------------------------------------------

def test_the_template_arrested_run_is_classified_even_with_no_requested_generations():
    """KO:dapA as the manifest actually holds it: `qc='no_division'`, `terminal_divided=false`, `crashed=false`,
    `generations=4`, `gens_reached=4`, `requested_generations=NULL`. The old depth-shortfall rule had nothing
    to compare against and dropped it into `unclassified`, so the one run with a measured arrested footprint
    could not be used as evidence for the arrested stratum."""
    row = {"qc": "no_division", "terminal_divided": False, "crashed": False,
           "generations": 4, "gens_reached": 4, "requested_generations": None}
    assert calibration._arrest_signal(row, 4) == ("arrested", "qc_no_division")


def test_a_null_requested_depth_with_an_undivided_terminal_cell_is_arrested_on_weaker_evidence():
    """`terminal_divided is false` is the NULL-tolerant fallback. It is recorded under its own signal name
    rather than merged with the depth shortfall, because 'arrested because the final cell never divided' is
    weaker evidence than 'arrested because the lineage stopped short of the depth it was asked for'."""
    row = {"qc": "implausible_channel", "terminal_divided": False, "crashed": False,
           "gens_reached": 2, "requested_generations": None}
    assert calibration._arrest_signal(row, 2) == ("arrested", "terminal_not_divided")


def test_the_depth_shortfall_rule_still_fires_where_it_always_did():
    """Widening must not displace the original signal: when the requested depth IS recorded and the lineage
    did not reach it, that is the strongest arrest evidence available and must stay the reported one."""
    on_disk = {"qc": "ok", "terminal_divided": True, "crashed": False,
               "gens_reached": 8, "requested_generations": 8}
    assert calibration._arrest_signal(on_disk, 3) == ("arrested", "depth_shortfall_on_disk")
    in_manifest = {"qc": "ok", "terminal_divided": True, "crashed": False,
                   "gens_reached": 3, "requested_generations": 8}
    assert calibration._arrest_signal(in_manifest, 8) == ("arrested", "depth_shortfall_manifest")


def test_a_crashed_run_is_arrested_whether_or_not_a_requested_depth_was_recorded():
    """81 of the 369 manifest rows crashed and 0 of them lack `requested_generations`, but the signal must not
    depend on that: a crash is an arrest on its own."""
    assert calibration._arrest_signal(
        {"qc": "crashed", "crashed": True, "gens_reached": 4, "requested_generations": 4}, 4
    ) == ("arrested", "crashed")
    assert calibration._arrest_signal(
        {"qc": "crashed", "crashed": True, "gens_reached": None, "requested_generations": None}, 2
    ) == ("arrested", "crashed")


def test_a_healthy_lineage_that_reached_its_requested_depth_stays_dividing():
    """The other direction, and the one that protects the measured dividing figure (median 0.694 over 108
    rows): a wider arrest rule that swept healthy runs in would inflate the arrested stratum and deflate the
    number `resources.estimate_sim_resources` actually consumes."""
    row = {"qc": "ok", "terminal_divided": True, "crashed": False,
           "gens_reached": 4, "requested_generations": 4}
    assert calibration._arrest_signal(row, 4) == ("dividing", "reached_requested_depth")


def test_a_row_with_no_arrest_signal_at_all_is_unclassified_and_not_guessed():
    """`unclassified` is kept as a third stratum rather than folded into either label. The first version of
    `from_corpus_disk` fell back to `generations`, which made want == reached for every run and classified
    100% as dividing — folding genuine arrested runs into the dividing median."""
    row = {"qc": "ok", "terminal_divided": True, "crashed": False,
           "gens_reached": 4, "requested_generations": None}
    assert calibration._arrest_signal(row, 4) == ("unclassified", "no_arrest_signal")


# --- the mined output records WHICH signal classified each row --------------------------------------

def test_from_corpus_disk_reports_the_signal_behind_every_stratum(tmp_path, monkeypatch):
    """An 'arrested' count sourced from a NULL-tolerant fallback is weaker evidence than one sourced from a
    depth shortfall, so the mined output must say which signal produced it rather than reporting a bare n.

    Two stubbed rows over one small on-disk directory: the KO:dapA shape (NULL requested depth, never
    divided) and a healthy one that reached its requested depth."""
    from cellarium import raw, store, survey
    run = tmp_path / "run"
    run.mkdir()
    (run / "blob.bin").write_bytes(b"0" * 1024)
    rows = [{"simout_path": "x/ko_dapA", "generations": 4, "gens_reached": 4, "qc": "no_division",
             "requested_generations": None, "crashed": False, "terminal_divided": False},
            {"simout_path": "x/wt", "generations": 4, "gens_reached": 4, "qc": "ok",
             "requested_generations": 4, "crashed": False, "terminal_divided": True}]
    monkeypatch.setattr(survey, "_deduped_rows", lambda _channels: rows)
    monkeypatch.setattr(store, "_resolve_run", lambda _p: str(run))
    monkeypatch.setattr(raw, "simout_dirs", lambda _p: ["generation_000000"] * 4)

    out = calibration.from_corpus_disk(limit=10)
    assert out["arrested"]["n"] == 1
    assert out["arrested"]["classified_by"] == {"qc_no_division": 1}
    assert out["dividing"]["n"] == 1
    assert out["dividing"]["classified_by"] == {"reached_requested_depth": 1}
    assert out["unclassified"]["n"] == 0 and out["unclassified"]["classified_by"] == {}


def test_the_arrest_columns_are_actually_projected_from_the_manifest():
    """The classifier is only as wide as the projection feeding it. `crashed` and `terminal_divided` were not
    in `from_corpus_disk`'s column list, so asking for them in the rule without adding them to the query
    would have read every row's signal as absent — the silent-absence class, inside the repair for it.

    Checked against the real manifest, skipped when there is none, because the point is that the columns
    exist in the shards rather than that the names appear in the source."""
    from cellarium import survey
    rows = survey._deduped_rows(["simout_path", "generations", "gens_reached", "qc",
                                 "requested_generations", "crashed", "terminal_divided"])
    if not rows or "__error__" in rows[0]:
        pytest.skip(f"no readable manifest here: {rows[0].get('__error__') if rows else 'no rows'}")
    assert "crashed" in rows[0] and "terminal_divided" in rows[0]
