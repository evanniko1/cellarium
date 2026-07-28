"""SCI-DYN-1 — shift transients, plus the raw-resolution bug that hid them.

Two regressions here, and the first is the more important one: it is a SILENT-ABSENCE bug of exactly the kind
this project keeps getting burned by. `raw.seed_runs` matched on `perturbation` + `condition`, but every
`timeline` design carries `condition = NULL` (its identity lives in the label), so the match returned zero rows
for designs whose raw simOut was sitting on local disk. Every raw-reading tool — the variance band, the tRNA
families, the dilution clock, the serialization scan — then reported "no local raw data" about data that was
right there, and an agent reading that would have concluded the experiment was never run.
"""

from __future__ import annotations

import numpy as np
import pytest

from cellarium import dynamics, raw, store, survey


def _timeline_designs() -> list[str]:
    return sorted({survey.design_key(r) for r in store.list_results()
                   if (r.get("perturbation") or "") == "timeline"})


def test_seed_runs_resolves_timeline_designs_that_have_raw_on_disk():
    """The silent-absence regression: if a timeline design has runs whose simOut is on disk, `seed_runs` must
    find them. The old perturbation/condition match returned 0 for 4 on-disk runs."""
    designs = _timeline_designs()
    if not designs:
        pytest.skip("no timeline designs in the manifest")
    checked = 0
    for d in designs:
        on_disk = [r for r in store.list_results() if survey.design_key(r) == d
                   and (store.simout_path(r["id"]) or "")
                   and raw.simout_dirs(store.simout_path(r["id"]) or "")]
        if not on_disk:
            continue
        checked += 1
        found = raw.seed_runs(d)
        assert len(found) >= len(on_disk), (
            f"{d}: {len(on_disk)} run(s) have raw on disk but seed_runs returned {len(found)} — "
            f"silent absence, the failure mode this test exists to prevent")
    if not checked:
        pytest.skip("no timeline design has local raw simOut")


def test_seed_runs_still_resolves_non_timeline_designs():
    """The fix must not regress the designs the old match handled: a design key must resolve for every
    perturbation family, not just timeline."""
    by_fam: dict[str, str] = {}
    for r in store.list_results():
        fam = r.get("perturbation") or ""
        d = survey.design_key(r)
        if fam and fam not in by_fam and (store.simout_path(r["id"]) or ""):
            by_fam[fam] = d
    if not by_fam:
        pytest.skip("no runs with resolvable simout paths")
    for fam, d in by_fam.items():
        runs = raw.seed_runs(d)
        assert isinstance(runs, list), (fam, d)
        for run in runs:
            assert run["root"] and run["result_id"]


def test_rolling_median_kills_lone_spikes_but_keeps_sustained_ones():
    """The de-spike must remove a one-sample excursion and PRESERVE a sustained one — otherwise it would erase
    the real, reproducible growth-rate jump at the amino-acid upshift."""
    base = np.full(60, 1.0)
    lone = base.copy(); lone[30] = 99.0
    assert dynamics._rolling_median(lone, 5).max() == pytest.approx(1.0)
    sustained = base.copy(); sustained[30:45] = 9.0
    assert dynamics._rolling_median(sustained, 5).max() == pytest.approx(9.0)


def test_shift_response_refuses_designs_with_no_declared_shift():
    """A steady-state design has no shift to respond to. It must say so, not invent a transient at t=0."""
    steady = next((survey.design_key(r) for r in store.list_results()
                   if (r.get("perturbation") or "") != "timeline"), None)
    if not steady:
        pytest.skip("no non-timeline design")
    out = dynamics.shift_response(steady, "ppgpp_conc")
    assert "error" in out and "no nutrient shift" in out["error"]


def test_shift_response_flags_boundary_extrema_and_withholds_overshoot():
    """Honesty guards. A peak on the LAST sample means the response never turned over inside the window, so
    overshoot is undefined and must be withheld rather than reported as a negative number that reads as an
    undershoot. A peak on the FIRST sample means the response beat the sampling rate, so the latency is a
    bound. Both were observed in the corpus: ppGpp is still climbing 900 s into the downshift, and growth rate
    is already at its extremum one timestep after the upshift."""
    designs = [d for d in _timeline_designs() if raw.seed_runs(d)]
    if not designs:
        pytest.skip("no timeline design with local raw simOut")
    saw_any = False
    for d in designs:
        for ch in ("ppgpp_conc", "growth_rate", "fraction_trna_charged"):
            out = dynamics.shift_response(d, ch)
            if "error" in out:
                continue
            saw_any = True
            for p in out["per_seed"]:
                if p["peak_at_window_edge"]:
                    assert p["overshoot_pct_of_pre"] is None, (d, ch, p)
                    assert "overshoot_withheld" in p
                if p["peak_at_first_sample"]:
                    assert p["time_to_peak_s"] == pytest.approx(0.0)
                    assert "latency_is_a_bound" in p
    assert saw_any, "no channel produced a characterisable response"


def test_shift_time_comes_from_the_declaration_not_the_recorded_media():
    """The whole point of taking the shift time from the DECLARED timeline: the recorded `media_id` truncates on
    the upshift (SCI-QC-1), so a label-driven analysis would fail on exactly the design that needs it. The
    declared shift time must be a positive number matching the design label for both directions."""
    for d in _timeline_designs():
        out = dynamics.shift_response(d, "ppgpp_conc")
        if "error" in out and "no local raw" in out["error"]:
            continue
        if "error" in out:
            continue
        assert out["declared_shift_s"] > 0
        assert str(int(out["declared_shift_s"])) in d, (d, out["declared_shift_s"])
