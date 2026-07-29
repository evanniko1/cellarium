"""The resource estimator must learn from this host's own runs — and must never pretend to.

Written because `_PER_SIM_RAM_GB = 2.0` sat 3.6x above the 0.55 GB six concurrent sims actually use. That kind
of error is invisible: a conservative constant never fails loudly, it just quietly recommends parallel=4 on a
host that runs 6 comfortably. The tests below pin BOTH halves — that measurement is used when it exists, and
that thin evidence is refused rather than dressed up.
"""

from __future__ import annotations

import json

import pytest

from cellarium import calibration


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(calibration, "OBSERVATIONS_PATH", tmp_path / "obs.json")
    return tmp_path / "obs.json"


def test_thin_evidence_falls_back_to_the_constant_and_says_why(store):
    """THE guard. A value learned from one or two runs would be more dangerous than a stale constant, because
    it arrives looking authoritative."""
    calibration.record("per_sim_ram_gb", 0.55)
    calibration.record("per_sim_ram_gb", 0.57)
    out = calibration._summary("per_sim_ram_gb", 2.0, "GB")
    assert out["basis"] == "constant" and out["value"] == 2.0
    assert out["n"] == 2 and "need 3" in out["why"]


def test_enough_evidence_is_used_and_carries_its_n(store):
    for v in (0.55, 0.57, 0.54, 0.60):
        calibration.record("per_sim_ram_gb", v)
    out = calibration._summary("per_sim_ram_gb", 2.0, "GB")
    assert out["basis"] == "measured" and out["n"] == 4
    assert 0.5 < out["value"] < 0.65
    assert out["constant_was"] == 2.0 and out["ratio_vs_constant"] < 0.5, "must expose how wrong the constant was"
    assert out["spread"] == [0.54, 0.60]


def test_the_median_not_the_mean_so_one_bad_run_cannot_move_it(store):
    """A sim that swapped, or a disk that filled, must not shift the estimate deciding whether the NEXT sweep
    fits."""
    for v in (0.55, 0.56, 0.57, 40.0):          # one pathological reading
        calibration.record("per_sim_ram_gb", v)
    out = calibration._summary("per_sim_ram_gb", 2.0, "GB")
    assert out["value"] < 1.0, "an outlier moved the calibration — use the median"
    assert out["spread"][1] == 40.0, "but the outlier must still be VISIBLE in the spread"


def test_strata_do_not_leak_into_each_other(store):
    """Arrested and dividing lineages differ ~2.4x in GB/generation. Pooling them produces a number describing
    neither — the same averaging-across-strata error the generation-depth work already cost us."""
    for v in (1.5, 1.6, 1.7):
        calibration.record("gb_per_generation", v, arrested=True)
    for v in (0.6, 0.65, 0.7):
        calibration.record("gb_per_generation", v, arrested=False)
    arr = calibration._summary("gb_per_generation", 1.58, "GB", arrested=True)
    div = calibration._summary("gb_per_generation", 0.65, "GB", arrested=False)
    assert arr["n"] == 3 and div["n"] == 3
    assert arr["value"] > div["value"] * 2


def test_a_broken_docker_command_is_not_reported_as_zero_usage():
    """`docker stats` has no `.Image` field; templating on it exits 1. The first version read that failure as
    "no running containers" — turning a broken command into an apparent measurement of an idle host."""
    res = calibration.observe_docker(image="definitely-not-an-image-xyz", record_it=False)
    assert res["ok"] is False
    assert "ABSENCE" in res["why"] or "failed" in res["why"], res["why"]


def test_junk_is_refused_rather_than_recorded(store):
    for bad in (0, -1.0, float("nan"), None):
        assert calibration.record("per_sim_ram_gb", bad)["recorded"] is False
    assert not store.exists() or json.loads(store.read_text()) == []


def test_observations_are_scoped_to_this_host(store):
    """A per-sim RAM figure from another machine is not evidence about this one."""
    calibration.record("per_sim_ram_gb", 0.55)
    recs = json.loads(store.read_text())
    assert recs[0]["host"] == calibration._host_key()
    recs[0]["host"] = "some-other-machine|Linux"
    store.write_text(json.dumps(recs))
    assert calibration._values("per_sim_ram_gb") == []


def test_the_estimator_reports_which_figures_are_measured():
    """A learned value that arrives unannounced is worse than a stale constant — nobody re-checks it."""
    from cellarium import resources
    r = resources.estimate_sim_resources(n_runs=4, parallel=2, generations=2)
    assert "calibration" in r
    for key in ("per_sim_ram_gb", "min_per_generation"):
        assert r["calibration"][key]["basis"] in ("measured", "constant")
        assert "n" in r["calibration"][key]
