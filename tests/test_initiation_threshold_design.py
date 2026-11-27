"""CRIT tier 1 (2026-11-27): `params.initiation_threshold = "relaxed"` reaches the model, and the envelope admits a
shift that moves the threshold only under it.

The hook (model_patches/hooks/initiation_threshold.py, tested in test_initiation_threshold_hook.py) is Cellarium's own
code: it wraps the model's process after its own initialize and runs the model's runSim.py unchanged, so no model file
is copied. As with the other run-defining params, everything that decides what a run IS must see it: the label, the
run directory, the launch queue's key, the container's environment, its mounts and its command. The registry record
`replication_initiation_after_a_nutrient_shift` does NOT move: reading such a run stays refused until the shift panel
(V3) passes.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from cellarium import capability, envelope, launch, manifest, mcp, runner  # noqa: E402
from cellarium.model import Design  # noqa: E402

SHIFT = "0 minimal, 1200 minimal_minus_oxygen"
HOOK_IN_IMAGE = "/cellarium/initiation_threshold.py"


def _shift(mode=None):
    p = {} if mode is None else {"initiation_threshold": mode}
    return Design(perturbation="timeline", timeline=SHIFT, params=p)


def test_the_label_and_the_axis():
    assert manifest.design_identity(_shift("relaxed"))[1].endswith("#it:relaxed")
    assert "#it:" not in manifest.design_identity(_shift())[1]
    # "medium" is the model's own behaviour, so it is the SAME experiment as no setting at all
    assert manifest.design_identity(_shift("medium")) == manifest.design_identity(_shift())
    assert "params.initiation_threshold" in manifest.IDENTITY_AXES
    assert "params.initiation_threshold" in {p[0] for p in manifest.identity_probes()}


def test_a_relaxed_design_runs_in_its_own_directory():
    assert runner._dir_discriminator(_shift("relaxed")).endswith("__itrelaxed")
    assert "__it" not in runner._dir_discriminator(_shift()) + runner._dir_discriminator(_shift("medium"))


def test_the_launch_queue_tells_them_apart():
    a, b = _shift(), _shift("relaxed")
    assert launch._match_key(a.perturbation, a.condition, a.timeline, a.params) != launch._match_key(
        b.perturbation, b.condition, b.timeline, b.params)


def test_env_mount_and_command_only_for_relaxed():
    assert runner._design_env(_shift("relaxed")) == {"CELLARIUM_INITIATION_THRESHOLD": "relaxed"}
    assert runner._design_env(_shift()) is None
    m = runner._design_mounts(_shift("relaxed"))
    assert m[0] == "-v" and m[1].endswith(f"model_patches/hooks/initiation_threshold.py:{HOOK_IN_IMAGE}:ro")
    assert runner._design_mounts(_shift()) == []
    argv = ["runscripts/manual/runSim.py", "cellarium", "--seed", "0"]
    assert runner._model_command(_shift(), argv) == argv
    assert runner._model_command(_shift("relaxed"), argv, docker=True) == [HOOK_IN_IMAGE, *argv]


def test_an_unknown_mode_is_refused_before_launch():
    with pytest.raises(ValueError):
        runner._initiation_threshold(_shift("sometimes"))


def test_the_envelope_admits_a_threshold_step_only_under_relaxed():
    refused = envelope.check(_shift())
    assert not refused.in_envelope and "975 to 590 fg" in refused.reason
    admitted = envelope.check(_shift("relaxed"))
    assert admitted.in_envelope, admitted.reason
    assert "relaxes" in admitted.reason and "tier 1" in admitted.reason


def test_reading_such_a_run_stays_refused_until_the_shift_panel_passes():
    c = capability.get("replication_initiation_after_a_nutrient_shift")
    assert c.holds_in == ()
    r = mcp.capability_precheck("read_series", {"design": "timeline/" + SHIFT + "#it:relaxed", "channel": "growth_rate"})
    assert r is not None and "replication_initiation_after_a_nutrient_shift" in r["capabilities"]
