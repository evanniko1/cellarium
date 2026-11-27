"""S2's comparison arm (2026-11-27): a graded synthetase knockdown with ppGpp held at its basal level.

DISCOVERY_CAMPAIGN.md's S2 asks whether the stringent response softens the growth cost of a synthetase shortfall
(in B. subtilis it does: Parker et al. 2020). The graded arm with ppGpp free exists; the comparator holds ppGpp at
the fitted basal concentration so the stringent response cannot raise it. `params.ppgpp_clamp = "basal"` reaches the
model as an environment variable read by Cellarium's own graded variant, mounted over the image's copy for a clamped
design only. As with the occupancy clamp (test_occupancy_clamp.py), everything that decides what a run IS must see it:
the label, the run directory, the launch queue's key, the container's environment and its mounts.

The clamp sets what upstream's `ppgpp_conc` variant sets for a factor of 1: no RelA or SpoT synthesis or degradation,
and metabolism holding ppGpp as a constant target (`force_constant_ppgpp`). That flag ALSO moves metabolism's biomass
targets from the RNA/protein path to the doubling-time path (RP, 2026-11-27), so the clamped arm differs from the free
arm in two respects; the S2 contrast is an interaction (knockdown effect, free against clamped), which cancels what the
two paths share at basal growth but not their difference under the knockdown. Recorded, not hidden.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from cellarium import launch, manifest, runner  # noqa: E402
from cellarium.model import Design  # noqa: E402

IN_IMAGE = "/wcEcoli/models/ecoli/sim/variants/graded_gene_knockout.py"


def _graded(level=3, clamp=None, gene="leuS"):
    p = {"target_genes": [gene], "variant_index": 1000 * 10 + level, "level": level}
    if clamp is not None:
        p["ppgpp_clamp"] = clamp
    return Design(perturbation="graded_gene_knockout", condition=f"KO:{gene}", params=p)


def _variant():
    spec = importlib.util.spec_from_file_location("ggk", REPO / "model_patches" / "variants" / "graded_gene_knockout.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fake_sim_data():
    return SimpleNamespace(constants=SimpleNamespace(k_RelA_ppGpp_synthesis=7.0, k_SpoT_ppGpp_degradation=3.0,
                                                     k_SpoT_ppGpp_synthesis=2.0),
                           process=SimpleNamespace(metabolism=SimpleNamespace()))


# ---- what the run IS ------------------------------------------------------------------------------------------------

def test_the_label_carries_the_clamp_and_the_axis_is_declared():
    assert manifest.design_identity(_graded(clamp="basal"))[1].endswith("#ppgpp:basal")
    assert "#ppgpp" not in manifest.design_identity(_graded())[1]
    assert "params.ppgpp_clamp" in manifest.IDENTITY_AXES
    assert "params.ppgpp_clamp" in {p[0] for p in manifest.identity_probes()}


def test_a_clamped_design_runs_in_its_own_directory():
    plain, clamped = (runner._dir_discriminator(d) for d in (_graded(), _graded(clamp="basal")))
    assert "__pp" not in plain and clamped.endswith("__ppbasal")


def test_the_launch_queue_tells_a_clamped_design_from_the_plain_one():
    a, b = (_graded(), _graded(clamp="basal"))
    assert (launch._match_key(a.perturbation, a.condition, a.timeline, a.params)
            != launch._match_key(b.perturbation, b.condition, b.timeline, b.params))


# ---- what reaches the container ---------------------------------------------------------------------------------------

def test_the_clamp_reaches_the_container_as_its_environment(monkeypatch):
    monkeypatch.setattr(runner, "_graded_ko_env", lambda d: {"GRADED_KO_CISTRON": "EG10532"})
    assert runner._design_env(_graded(clamp="basal")) == {"GRADED_KO_CISTRON": "EG10532",
                                                          "GRADED_KO_PPGPP_CLAMP": "basal"}
    assert "GRADED_KO_PPGPP_CLAMP" not in (runner._design_env(_graded()) or {})


def test_cellariums_variant_is_mounted_only_for_a_clamped_design():
    m = runner._design_mounts(_graded(clamp="basal"))
    assert m[0] == "-v" and m[1].endswith(f"model_patches/variants/graded_gene_knockout.py:{IN_IMAGE}:ro")
    assert runner._design_mounts(_graded()) == []


def test_a_design_mount_replaces_the_checkouts_copy_of_the_same_file():
    base = ["-v", f"C:/x/models/ecoli/sim/variants/graded_gene_knockout.py:{IN_IMAGE}:ro",
            "-v", "C:/x/flat/media_recipes.tsv:/wcEcoli/reconstruction/ecoli/flat/condition/media_recipes.tsv:ro"]
    extra = ["-v", f"C:/c/model_patches/variants/graded_gene_knockout.py:{IN_IMAGE}:ro"]
    merged = runner._merge_mounts(base, extra)
    targets = [merged[i + 1].split(":/wcEcoli/")[1] for i in range(0, len(merged), 2)]
    assert targets.count("models/ecoli/sim/variants/graded_gene_knockout.py:ro") == 1
    assert "C:/c/model_patches/variants/graded_gene_knockout.py:" + IN_IMAGE + ":ro" in merged
    assert len(merged) == 4


@pytest.mark.parametrize("bad", [
    Design(perturbation="gene_knockout", condition="KO:leuS", params={"target_genes": ["leuS"], "ppgpp_clamp": "basal"}),
    _graded(clamp="0.5x"),
    Design(perturbation="graded_gene_knockout", condition="KO:leuS", elongation_model="kinetic",
           params={"target_genes": ["leuS"], "variant_index": 10003, "level": 3, "ppgpp_clamp": "basal"}),
])
def test_a_clamp_the_variant_cannot_apply_is_refused_before_launch(bad):
    """A plain knockout's variant never reads the variable, and the kinetic modes already hold ppGpp constant: either
    would run unclamped under a clamped label."""
    with pytest.raises(ValueError):
        runner._ppgpp_clamp(bad)


# ---- what the variant does --------------------------------------------------------------------------------------------

def test_the_variant_holds_ppgpp_like_upstreams_factor_one():
    v, sd = _variant(), _fake_sim_data()
    v._clamp_ppgpp(sd, "basal")
    assert (sd.constants.k_RelA_ppGpp_synthesis, sd.constants.k_SpoT_ppGpp_degradation,
            sd.constants.k_SpoT_ppGpp_synthesis) == (0.0, 0.0, 0.0)
    assert sd.process.metabolism.force_constant_ppgpp is True
    with pytest.raises(ValueError):
        v._clamp_ppgpp(_fake_sim_data(), "zero")


def test_without_the_variable_the_variant_is_unchanged(monkeypatch):
    v, sd = _variant(), _fake_sim_data()
    monkeypatch.delenv("GRADED_KO_PPGPP_CLAMP", raising=False)
    sd.process.transcription = SimpleNamespace(rna_data={"id": ["A", "B"]})
    out, sd2 = v.graded_gene_knockout(sd, 0)
    assert out == v.CONTROL_OUTPUT and sd2.constants.k_RelA_ppGpp_synthesis == 7.0
    assert not hasattr(sd2.process.metabolism, "force_constant_ppgpp")


def test_the_clamped_control_is_index_zero_with_the_variable(monkeypatch):
    """The comparison needs a clamped control (no knockdown, ppGpp held), so the clamp applies at index 0 too."""
    v, sd = _variant(), _fake_sim_data()
    monkeypatch.setenv("GRADED_KO_PPGPP_CLAMP", "basal")
    sd.process.transcription = SimpleNamespace(rna_data={"id": ["A", "B"]})
    out, sd2 = v.graded_gene_knockout(sd, 0)
    assert sd2.process.metabolism.force_constant_ppgpp is True
    assert "ppGpp held at basal" in out["desc"]
