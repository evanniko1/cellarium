"""PROV-2: every new run records which image and which model class produced it.

WHY THIS EXISTS, measured 2026-08-24. `WCECOLI_DOCKER` pointed at `wcecoli-sim:latest`, a tag created
2026-05-10 and never re-pointed. It matched Cellarium's 45-file overlay on **3**, against 43 for the real
build, and was missing two variants that 24 corpus rows use. Every simulation launched from that machine ran
a 3.5-month-old model — and nothing could have reported it, because no row recorded an image at all (0 of 1
shards carry an `image_digest` column).

TWO CONTRACTS, and the second is the one that is easy to get wrong:

  1. A run LAUNCHED through `runner.run_one` leaves `executed.json` beside its output, carrying the image
     digest and the model class wcEcoli wrote for itself.
  2. A run that has NO such file reports all-NULL, permanently. The information for the 363 existing rows is
     DESTROYED, not merely unrecorded — wcEcoli keeps one `metadata.json` per sim_path and overwrites it every
     run — so filling those columns from today's environment would assert that a July run used today's image.
     That is the same fabrication `_run_prov`'s guard already refuses to make.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.cellarium import manifest, runner  # noqa: E402

# --------------------------------------------------------------------- contract 2: honest absence

def test_a_run_without_the_file_reads_as_unknown_not_as_today(tmp_path):
    """The 363-row case. All-NULL is the correct answer and must never be filled in from the environment."""
    assert runner.read_executed(tmp_path) == {}
    prov = manifest._executed_prov(tmp_path)
    assert set(prov) == set(manifest._EXECUTED_ABSENT)
    assert all(v is None for v in prov.values()), prov


def test_a_missing_directory_is_also_unknown_and_does_not_raise():
    assert runner.read_executed(Path("/no/such/run/root")) == {}
    assert all(v is None for v in manifest._executed_prov(Path("/no/such/run/root")).values())


def test_corrupt_json_reads_as_unknown_rather_than_crashing_a_reindex(tmp_path):
    (tmp_path / "executed.json").write_text("{not json", encoding="utf-8")
    assert runner.read_executed(tmp_path) == {}


# --------------------------------------------------------------------- contract 1: what a launch records

def test_the_columns_land_on_a_row_when_the_file_is_there(tmp_path):
    (tmp_path / "executed.json").write_text(json.dumps({
        "image_tag": "cellarium-wcm-code:latest",
        "image_digest": "sha256:d2d46d83a4b460d6ce0025b169f0fe02b9fe6096284e754eedd01fb07da09c94",
        "executed": {"elongation_model": "SteadyStateElongationModel",
                     "git_hash": "a4497e1756bacdc0a4a8c05be55f2cdfbdbc9115",
                     "python": "3.11.3 (main, May 23 2023, 13:25:46) [GCC 10.2.1 20210110]"},
    }), encoding="utf-8")
    p = manifest._executed_prov(tmp_path)
    assert p["executed_image_tag"] == "cellarium-wcm-code:latest"
    assert p["executed_image_digest"].startswith("sha256:d2d46d83")
    assert p["model_class"] == "SteadyStateElongationModel"
    assert p["model_git_hash"].startswith("a4497e17")
    assert p["executed_python"] == "3.11.3", "the python field keeps only the version, not the whole banner"


def test_model_class_is_the_MODELS_name_not_our_enum(tmp_path):
    """THE forward-compatibility requirement. `elongation_model` in our schema records what the CALLER
    declared, from a fixed set of three. `model_class` records what wcEcoli called the class it actually
    instantiated — so a translation model added upstream tomorrow lands under its own name with nothing in
    this repo changing. A test that only checked the three known values would enforce the opposite."""
    from src.cellarium import capability as C

    (tmp_path / "executed.json").write_text(json.dumps({
        "executed": {"elongation_model": "SomeFutureElongationModelNobodyHasWrittenYet"}}), encoding="utf-8")
    got = manifest._executed_prov(tmp_path)["model_class"]
    assert got == "SomeFutureElongationModelNobodyHasWrittenYet"
    assert got not in C.ALL_MODES, "model_class must not be constrained to today's declared enum"


def test_the_captured_field_list_covers_model_identity_and_configuration():
    f = set(runner._EXECUTED_FROM_METADATA)
    for k in ("elongation_model", "git_hash", "git_branch", "python", "seed", "variant"):
        assert k in f, k
    for k in ("kinetic_trna_charging", "coarse_kinetic_elongation", "ppgpp_regulation"):
        assert k in f, f"{k} distinguishes how the model class was configured"


# --------------------------------------------------------------------- the ordering that makes it work

def test_capture_follows_the_run_and_is_told_which_run_it_is():
    """Ordering only — deliberately NOT claiming the lock protects metadata.json, because IT DOES NOT.

    The first version of this test asserted `lock_at < cap_at` and treated that as the fix. It is not: the
    lock is keyed on `<out>/<variant>_<index>/<seed>` — PER SEED — while metadata.json is per SIM_PATH, and
    `manifest.campaign(parallel=N)` submits every seed into one sim_path. N runs therefore sit in N different
    critical sections at once. A test asserting source ORDERING while the defect is about EXCLUSION passes
    happily with the bug live — the same "guard sharing no object with what it guards" shape closed earlier
    today, recurring in my own new code. The real protection is the ownership check, tested below.
    """
    src = (REPO / "src" / "cellarium" / "runner.py").read_text(encoding="utf-8")
    body = src[src.index("def run_one("):]
    body = body[:body.index("\n    return run_root")]
    exec_at = body.index('_exec(["runscripts/manual/runSim.py"')
    cap_at = body.index("_capture_executed(run_root, sim_path")
    assert exec_at < cap_at, "capture must follow the run, not precede it"
    assert "expect_seed=seed" in body, "capture is not told which seed it is recording, so it cannot verify"


def test_the_per_run_metadata_is_preferred_over_the_shared_one(tmp_path, monkeypatch):
    """THE parallel=N fix. The overlay's runSim.py writes the same metadata into the per-SEED directory, which
    is unique per run, so concurrent runs have nothing to race over. MEASURED: parallel=3 went from 1/3 runs
    recording their own model class to 3/3, with the shared file still holding only one seed."""
    (tmp_path / "metadata.json").write_text(json.dumps({
        "seed": 0, "variant": "wildtype", "elongation_model": "SteadyStateElongationModel"}), encoding="utf-8")
    shared = tmp_path / "sp" / "metadata"
    shared.mkdir(parents=True)
    (shared / "metadata.json").write_text(json.dumps({
        "seed": 2, "variant": "wildtype", "elongation_model": "WrongOne"}), encoding="utf-8")
    monkeypatch.setattr(runner, "_out_root", lambda sp: tmp_path / sp)
    rec = runner._capture_executed(tmp_path, "sp", expect_seed=0, expect_variant="wildtype")
    assert rec["metadata_source"] == "per_run"
    assert rec["executed"]["elongation_model"] == "SteadyStateElongationModel"
    assert not any("DIFFERENT run" in m for m in rec["missing"])


def test_runsim_writes_the_per_run_copy_into_the_seed_directory():
    """The overlay half of the fix. Without this write the per-run file never exists and every campaign falls
    back to the shared, overwritten one — which is where the whole defect lives."""
    src = (REPO / "model_overlay" / "files" / "runscripts" / "manual" / "runSim.py").read_text(encoding="utf-8")
    i = src.index('seed_directory = fp.makedirs(variant_directory, "%06d" % j)')
    block = src[i:i + 1800]
    assert "constants.JSON_METADATA_FILE" in block, "no per-run metadata write follows seed_directory"
    assert "seed=j" in block, "the per-run copy must carry THIS run's seed, not the invocation's start seed"
    assert "os.path.join(seed_directory" in block, "the copy must land in the per-seed directory"


def test_a_metadata_file_belonging_to_ANOTHER_run_is_refused(tmp_path, monkeypatch):
    """THE fix for the seed:1 problem. Under parallel=N the last run to finish owns metadata.json; every other
    run must notice and omit the executed block rather than attribute a stranger's configuration to itself."""
    meta = tmp_path / "sp" / "metadata"
    meta.mkdir(parents=True)
    (meta / "metadata.json").write_text(json.dumps({
        "seed": 4, "variant": "wildtype", "elongation_model": "SteadyStateElongationModel"}), encoding="utf-8")
    monkeypatch.setattr(runner, "_out_root", lambda sp: tmp_path / sp)
    rec = runner._capture_executed(tmp_path, "sp", expect_seed=0, expect_variant="wildtype")
    assert "executed" not in rec, "a stranger's configuration was attributed to this run"
    assert any("DIFFERENT run" in m for m in rec["missing"]), rec["missing"]
    assert rec["metadata_owner"]["seed"] == 4


def test_a_matching_metadata_file_IS_used(tmp_path, monkeypatch):
    """The check must not be so strict it refuses the correct file — that trades a wrong record for none."""
    meta = tmp_path / "sp" / "metadata"
    meta.mkdir(parents=True)
    (meta / "metadata.json").write_text(json.dumps({
        "seed": 0, "variant": "wildtype", "elongation_model": "SteadyStateElongationModel"}), encoding="utf-8")
    monkeypatch.setattr(runner, "_out_root", lambda sp: tmp_path / sp)
    rec = runner._capture_executed(tmp_path, "sp", expect_seed=0, expect_variant="wildtype")
    assert rec["executed"]["elongation_model"] == "SteadyStateElongationModel"
    assert not any("DIFFERENT run" in m for m in rec["missing"])


def test_the_image_half_survives_even_when_the_metadata_is_a_strangers(tmp_path, monkeypatch):
    """The trade that makes a partial record acceptable: image and model-source come from THIS PROCESS and are
    always right, so a parallel campaign still records which image ran every row."""
    meta = tmp_path / "sp" / "metadata"
    meta.mkdir(parents=True)
    (meta / "metadata.json").write_text(json.dumps({"seed": 9, "variant": "wildtype"}), encoding="utf-8")
    monkeypatch.setattr(runner, "_out_root", lambda sp: tmp_path / sp)
    monkeypatch.setattr(runner, "WCECOLI_DOCKER", "cellarium-wcm-code:latest")
    rec = runner._capture_executed(tmp_path, "sp", expect_seed=0, expect_variant="wildtype")
    assert "executed" not in rec
    assert rec["image_tag"] == "cellarium-wcm-code:latest"


def test_capture_never_raises_and_says_what_it_could_not_read(tmp_path, monkeypatch):
    """A provenance write that kills a completed simulation would be a worse bug than the one it documents."""
    monkeypatch.setattr(runner, "WCECOLI_DOCKER", "no-such-image:nope")
    rec = runner._capture_executed(tmp_path, "no_such_sim_path")
    assert isinstance(rec, dict)
    assert rec["missing"], "a partial record must name what it could not read, not omit it silently"
    assert (tmp_path / "executed.json").is_file()


def test_a_run_root_that_cannot_be_written_still_returns_a_record():
    rec = runner._capture_executed(Path("/no/such/dir/at/all"), "x")
    assert isinstance(rec, dict) and "captured_at" in rec


# --------------------------------------------------------------------- the schema side

def test_the_new_columns_are_null_safe_for_readers():
    """Every existing shard lacks these columns entirely, so a bare reference raises a Binder Error — the
    `machine` incident this file's neighbours record. They must go through `optional_col_sql`."""
    for col in manifest._EXECUTED_ABSENT:
        sql = manifest.optional_col_sql(col)
        assert col in sql and "AS" in sql
