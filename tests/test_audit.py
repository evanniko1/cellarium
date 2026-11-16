"""Corpus-audit smoke tests — the read-only inventory + the compaction guardrail. Run: python -m pytest tests/test_audit.py"""

import pytest

from cellarium import audit, calibration, manifest, tools


def test_gb_estimate_scales_with_generations_and_seeds():
    """The expectations are LITERALS, not `round(8 * audit.GB_PER_GENERATION, 2)`.

    This test is the first entry in `tests/test_threshold_boundaries.py`'s `SELF_REFERENTIAL_REVIEW`: it used
    to re-implement `_gb` with the same constant, so every value of `GB_PER_GENERATION` satisfied it and tier
    0 recorded a surviving mutant with six covering tests. 8 x 0.65 = 5.2 and 4 x 0.65 x 3 = 7.8, recomputed
    from the declared 0.65; halve or double the constant and these fail, which is the whole point. The name
    stays because the ledger asserts the reviewed test still exists."""
    assert audit._gb(8, 1) == 5.2
    assert audit._gb(4, 3) == 7.8
    assert audit._gb(0, 5) == 0.0
    assert audit._gb(None, 2) == 0.0        # missing generation count is treated as 0, never crashes


def test_the_arrested_storage_rate_is_a_worked_case_and_not_the_dividing_one():
    """`GB_PER_GENERATION_ARRESTED = 1.58` had ZERO executable references while the comment above it told the
    reader to 'use GB_PER_GENERATION_ARRESTED and say so' — tier 0 classified it `no_covering_tests`, which is
    UNMEASURED and never a pass. `_gb` now takes the rate, so the constant is reachable and pinned.

    Literal expectations, recomputed: 8 x 1.58 = 12.64 and 8 x 0.65 = 5.2. Writing these as
    `round(8 * audit.GB_PER_GENERATION_ARRESTED, 2)` would move with the mutant and hold at every value —
    exactly the trap the test above was repaired for."""
    assert audit._gb(8, 1, rate=audit.GB_PER_GENERATION_ARRESTED) == 12.64
    assert audit._gb(8, 1) == 5.2                                          # the default is still DIVIDING
    assert audit._gb(4, 2, rate=audit.GB_PER_GENERATION_ARRESTED) == 12.64  # 4 x 1.58 x 2, seeds scale too
    # The missing-generation guard must not change when a rate is supplied.
    assert audit._gb(None, 1, rate=audit.GB_PER_GENERATION_ARRESTED) == 0.0


def test_the_rate_is_keyword_only_so_the_on_disk_call_sites_cannot_drift():
    """Three of `_gb`'s four call sites describe bytes ALREADY on disk (`coverage`, `redundancy`,
    `prune_candidates`) and must keep the dividing rate; only `gaps()` forecasts. Keyword-only is what stops a
    positional third argument silently re-rating an on-disk figure."""
    with pytest.raises(TypeError):
        audit._gb(8, 1, 1.58)       # type: ignore[misc]


@pytest.fixture()
def free_100gb(monkeypatch):
    """A 100.0 GB free volume and a stub corpus, so the forecast arithmetic is checked rather than the disk.

    `gaps()` rounds `free / 1024**3` to one decimal, so the stub reports exactly 100 GiB.
    """
    import shutil as _shutil
    monkeypatch.setattr(audit, "coverage",
                        lambda: {"n_designs": 1, "n_runs": 2,
                                 "designs": {"gene_knockout/KO:dapA": {"n_seeds": 2, "max_generations": 4,
                                                                       "qc": {"no_division": 2},
                                                                       "est_gb": 5.2}}})
    monkeypatch.setattr(_shutil, "disk_usage",
                        lambda _p: type("du", (), {"total": 0, "used": 0, "free": 100 * 1024 ** 3})())


def _calibrated(arrested: dict, dividing: dict | None = None) -> dict:
    """A `calibration.calibrated()` payload with only the two disk strata filled in."""
    return {"gb_per_generation_dividing": dividing or {"value": 0.65, "n": 0, "basis": "constant", "unit": "GB"},
            "gb_per_generation_arrested": arrested}


def test_the_disk_forecast_sizes_an_arrested_lineage_higher_and_names_its_basis(free_100gb, monkeypatch):
    """The defect WELL-PRUNE-1 recorded as fixed and left open: `gaps()` forecast every lineage at the
    DIVIDING rate, so a knockout campaign sized off `feasible_8gen_lineages` over-commits.

    Literal expectations, recomputed: 8 x 0.65 = 5.2 GB/lineage and 100.0 / 5.2 = 19.23 -> 19; 8 x 1.58 =
    12.64 and 100.0 / 12.64 = 7.91 -> 7. And the arrested stratum must say what it is: 0 observations in
    `data/calibration/resource_observations.json` carry `arrested: true`, so its basis is 'constant', n = 0."""
    monkeypatch.setattr(calibration, "calibrated",
                        lambda: _calibrated({"value": 1.58, "n": 0, "basis": "constant", "unit": "GB"}))
    g = audit.gaps()
    assert g["est_gb_per_8gen_lineage_dividing"] == 5.2
    assert g["est_gb_per_8gen_lineage_arrested"] == 12.64
    assert g["feasible_8gen_lineages_dividing"] == 19
    assert g["feasible_8gen_lineages_arrested"] == 7
    assert g["feasible_8gen_lineages"] == 19, "the old key stays an alias of the DIVIDING figure"
    assert g["forecast_basis"]["arrested"]["basis"] == "constant"
    assert g["forecast_basis"]["arrested"]["n"] == 0
    assert g["forecast_basis"]["dividing"]["basis"] == "constant"
    # Not a bare number: the unmeasured stratum is named out loud, the discipline resources.py already
    # applies as `disk_caveat`.
    assert "arrested" in g["note"] and "no MEASURED" in g["note"]


def test_the_disk_forecast_consumes_a_measured_arrested_rate_when_one_exists(free_100gb, monkeypatch):
    """The other half: the forecast must USE the measurement when there is one, not always fall back.

    Literal expectations, recomputed: a measured 1.20 GB/gen gives 8 x 1.2 = 9.6 GB/lineage and 100.0 / 9.6 =
    10.42 -> 10; the measured dividing 0.808 gives 8 x 0.808 = 6.464 -> 6.46 and 100.0 / 6.46 = 15.48 -> 15.
    Both strata measured, so the unmeasured caveat must stay silent — a caveat that fires unconditionally
    carries no information."""
    monkeypatch.setattr(calibration, "calibrated",
                        lambda: _calibrated({"value": 1.20, "n": 5, "basis": "measured", "unit": "GB"},
                                            {"value": 0.808, "n": 12, "basis": "measured", "unit": "GB"}))
    g = audit.gaps()
    assert g["est_gb_per_8gen_lineage_arrested"] == 9.6
    assert g["feasible_8gen_lineages_arrested"] == 10
    assert g["est_gb_per_8gen_lineage_dividing"] == 6.46
    assert g["feasible_8gen_lineages_dividing"] == 15
    assert g["forecast_basis"]["arrested"] == {"basis": "measured", "n": 5, "gb_per_generation": 1.2}
    assert g["forecast_basis"]["dividing"] == {"basis": "measured", "n": 12, "gb_per_generation": 0.808}
    assert "no MEASURED" not in g["note"], "nothing is unmeasured here, so the caveat must not fire"


def test_a_measured_label_with_no_observations_is_refused(free_100gb, monkeypatch):
    """`resources.py:195-199` records what happens when a label is trusted over its evidence: the unmeasured
    1.58 dominated a measured 0.808 'while the result was still labelled measured'. So `gaps()` checks n
    rather than the word — basis 'measured' with n = 0 is downgraded, and the fallback constant is used."""
    monkeypatch.setattr(calibration, "calibrated",
                        lambda: _calibrated({"value": 9.99, "n": 0, "basis": "measured", "unit": "GB"}))
    g = audit.gaps()
    assert g["forecast_basis"]["arrested"]["basis"] == "constant"
    assert g["forecast_basis"]["arrested"]["gb_per_generation"] == 1.58   # the declared constant, not the 9.99
    assert g["feasible_8gen_lineages_arrested"] == 7                      # 100.0 / 12.64 = 7.91 -> 7


def test_latest_per_run_keeps_newest_ts():
    rows = [{"run_key": "a", "ts": 1}, {"run_key": "a", "ts": 5}, {"run_key": "b", "ts": 2}]
    live = {r["run_key"]: r for r in audit._latest_per_run(rows)}
    assert live["a"]["ts"] == 5            # newest wins — matches store's read-time dedup
    assert len(live) == 2


def test_design_label():
    assert audit._design({"perturbation": "gene_knockout", "condition": "KO:pfkA"}) == "gene_knockout/KO:pfkA"
    assert audit._design({"perturbation": "wildtype", "condition": None, "timeline": None}) == "wildtype/basal"


def test_audit_report_is_well_formed():
    r = audit.audit_report()
    if "error" in r:                        # empty/absent corpus is a graceful error, not a crash
        return
    assert set(r) >= {"summary", "coverage", "redundancy", "gaps", "housekeeping", "disclaimer"}
    s = r["summary"]
    assert s["n_designs"] >= 0 and s["n_runs"] >= 0
    assert r["redundancy"]["est_gb_prunable_safe"] >= 0
    assert r["gaps"]["feasible_8gen_lineages"] >= 0 and r["gaps"]["free_disk_gb"] >= 0
    # The output-key contract, updated deliberately when gaps() became two-stratum. `feasible_8gen_lineages`
    # is KEPT as an alias of the dividing figure for one release because documents quote it; the two new keys
    # are what a knockout campaign must be sized off.
    gp = r["gaps"]
    assert set(gp) >= {"feasible_8gen_lineages_dividing", "feasible_8gen_lineages_arrested",
                       "est_gb_per_8gen_lineage_dividing", "est_gb_per_8gen_lineage_arrested",
                       "forecast_basis"}
    assert gp["feasible_8gen_lineages"] == gp["feasible_8gen_lineages_dividing"]
    # An arrested lineage writes 2-4x the timesteps, so it can never be the CHEAPER forecast.
    assert gp["est_gb_per_8gen_lineage_arrested"] >= gp["est_gb_per_8gen_lineage_dividing"]
    assert gp["feasible_8gen_lineages_arrested"] <= gp["feasible_8gen_lineages_dividing"]
    for stratum in ("dividing", "arrested"):
        row = gp["forecast_basis"][stratum]
        assert row["basis"] in ("measured", "constant") and row["n"] >= 0
        # A 'measured' basis with no observations behind it is the failure resources.py:195-199 records.
        assert not (row["basis"] == "measured" and row["n"] == 0)
    assert r["summary"]["feasible_8gen_lineages_arrested"] >= 0


def test_redundancy_verdict_is_power_grounded():
    """Redundancy is a grounded TOOL decision, not the agent's opinion: prune-safe iff target-seed MDE clears the
    reference effect, given the design's own replicate CV."""
    red = audit.redundancy()
    if "error" in red:
        return
    assert red["channel"] and "ref_effect_pct" in red
    for info in red["designs"].values():
        assert info["verdict"] in ("prune-safe", "keep-for-power")
        assert info["mde_pct_at_target"] >= info["mde_pct_at_current"]     # fewer seeds -> larger MDE
        assert (info["verdict"] == "prune-safe") == (info["mde_pct_at_target"] <= red["ref_effect_pct"])


def test_crashed_runs_are_never_flagged_as_prunable():
    """keep-all-models: a crashed KO is a valid inviable datapoint, not dead weight to delete."""
    sup = audit.supersession()
    if "error" in sup:
        return
    assert "n_inviable_by_crash" in sup                 # reported as a coverage fact...
    assert "kept on purpose" in sup["note"]             # ...explicitly kept, not pruned
    assert not any("crash" in k.lower() and "prun" in k.lower() for k in sup)


def test_compact_dry_run_is_read_only():
    """Supersession is deterministic housekeeping, not a decision — compact() dedups without judgment or side effects."""
    r = manifest.compact(dry_run=True)
    if "error" in r:                                    # no shards -> graceful error
        return
    assert r["dry_run"] is True
    assert r["rows_after"] <= r["rows_before"]          # dedup never adds rows
    assert r["superseded_dropped"] == r["rows_before"] - r["rows_after"]
    assert "files_after" not in r                       # dry run touches no files


def test_prune_candidates_lists_only_prune_safe_excess_and_deletes_nothing():
    """The resolver is deterministic and safe: it only lists excess seeds of PRUNE-SAFE designs, and deletes nothing."""
    pc = audit.prune_candidates()
    if "error" in pc:
        return
    red = audit.redundancy()
    safe = {d for d, i in red.get("designs", {}).items() if i["verdict"] == "prune-safe"}
    keep = {d for d, i in red.get("designs", {}).items() if i["verdict"] == "keep-for-power"}
    for c in pc["candidates"]:
        assert c["design"] in safe and c["design"] not in keep     # only prune-safe, never keep-for-power
        assert "run_root" in c and isinstance(c["raw_on_disk"], bool)
    assert pc["est_gb_on_disk"] >= 0
    assert "DELETES NOTHING" in pc["note"]                         # read-only resolver


def test_dispatch_routes_corpus_audit():
    out = tools.dispatch("corpus_audit", {})
    assert out.get("error") != "unknown tool 'corpus_audit'"   # registered in _DISPATCH
    assert "summary" in out or "error" in out
