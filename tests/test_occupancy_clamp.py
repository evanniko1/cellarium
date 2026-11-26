"""BV-14d: a design can hold transcription factors' promoter occupancy at set values (`params.tf_occupancy_clamp`).

The clamp reaches the model as an environment variable read by a patched `tf_binding.py`, mounted only for a clamped
design. Everything that decides what a run IS must see the clamp, or a clamped run lands beside the unclamped runs
of the same condition, seed directory and arm and is averaged with them: the label (`manifest._design_tag`, tested in
test_identity_axes), the run directory (`runner._dir_discriminator`), the launch queue's semantic key
(`launch._match_key`), the container's environment and its mounts.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from cellarium import launch, runner  # noqa: E402
from cellarium.model import Design  # noqa: E402

FIT = {"FNR-4FE-4S-CPLX": "fit", "PHOSPHO-NARL": "fit"}
OFF = {"FNR-4FE-4S-CPLX": 0, "PHOSPHO-NARL": "fit"}


def _nitrate(clamp=None):
    p = {"variant_index": 24}
    if clamp is not None:
        p["tf_occupancy_clamp"] = clamp
    return Design(perturbation="condition", condition="no_oxygen_plus_nitrate", params=p)


def test_a_clamped_design_runs_in_its_own_directory():
    plain, fit, off = (runner._run_subpath(d, 300, "bv14_no3_anaerobic") for d in
                       (_nitrate(), _nitrate(FIT), _nitrate(OFF)))
    assert plain.parent.name == "condition_000024"                 # forced: no clamp, the path never changes
    assert fit != plain and off != plain and fit != off
    assert fit.parent.name.startswith("condition_000024__occ") and fit.name == "000300"
    # the same clamp written in another order is the same experiment, so the same directory
    assert runner._run_subpath(_nitrate(dict(reversed(list(FIT.items())))), 300, "bv14_no3_anaerobic") == fit


def test_the_clamp_reaches_the_container_as_its_environment_and_nothing_else_does():
    env = runner._design_env(_nitrate(FIT))
    assert json.loads(env["CELLARIUM_TF_OCCUPANCY_CLAMP"]) == FIT
    assert runner._design_env(_nitrate()) is None                  # forced: an unclamped run gets no variable


def test_the_patched_binding_process_is_mounted_only_for_a_clamped_design():
    m = runner._design_mounts(_nitrate(OFF))
    assert m[0] == "-v" and m[1].endswith(":/wcEcoli/models/ecoli/processes/tf_binding.py:ro")
    assert Path(m[1].rsplit(":/wcEcoli/", 1)[0]).is_file()
    assert runner._design_mounts(_nitrate()) == []                 # forced: every other run keeps the image's file


def test_the_launch_queue_tells_a_clamped_design_from_the_plain_one():
    k = lambda d: launch._match_key(d.perturbation, d.condition, d.timeline, d.params)   # noqa: E731
    assert k(_nitrate(FIT)) != k(_nitrate()) and k(_nitrate(FIT)) != k(_nitrate(OFF))


def test_the_patched_process_changes_nothing_without_the_variable():
    src = (REPO / "model_patches" / "processes" / "tf_binding.py").read_text(encoding="utf-8")
    assert "CELLARIUM_TF_OCCUPANCY_CLAMP" in src
    # the clamp is applied only to factors it names, after the model's own probability is computed
    assert "if tf_id in self.occupancy_clamp:" in src
    with pytest.raises(ValueError):
        runner._design_env(_nitrate({"FNR-4FE-4S-CPLX": 1.5}))    # an occupancy is a probability
