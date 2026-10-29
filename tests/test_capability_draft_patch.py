"""The DRAFT-PATCH route out of a mode gap.

`capability.check` knew exactly two routes out of the ppGpp and amino-acid-uptake gaps: "no elongation model
represents it" and "switch to steady_state". A third route exists and the registry could not name it — the
kinetic port's patch 2 (`--kinetic-aa-supply`, EXT-PORT-A) and patch 3 (`--kinetic-ppgpp`, EXT-PORT-P), which
add the missing mechanism TO the kinetic model instead of abandoning it. An agent asked for per-isoacceptor
charging AND the stringent response in one cell was therefore told the combination is impossible, when what is
true is that it is drafted, unapplied, and uncosted.

The danger of fixing this is the mirror image: a registry that names a patch as if it were available turns a
"not yet" into a "yes", which is the silent-absence shape pointed the other way. So every assertion below
pins BOTH halves — the route is named, and it is marked unapplied, absent from the corpus, and non-answering.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cellarium import capability  # noqa: E402

# --- the registry of drafted patches ------------------------------------------------------------------

def test_draft_patch_registry_declares_both_kinetic_patches():
    reg = capability.DRAFT_PATCHES
    assert set(reg) == {"EXT-PORT-A", "EXT-PORT-P"}, "both kinetic-port patches must be declared"
    a, p = reg["EXT-PORT-A"], reg["EXT-PORT-P"]
    assert a.flag == "--kinetic-aa-supply" and p.flag == "--kinetic-ppgpp"
    # Neither is a standalone switch: resolve_elongation_flags requires the kinetic model underneath.
    assert "--kinetic-trna-charging" in a.requires and "--kinetic-trna-charging" in p.requires
    # The one claim that must never drift: these are DRAFTS, not features of the checkout Cellarium reads.
    assert a.applied is False and p.applied is False


def test_draft_patches_compose_into_the_named_hybrid():
    """Patch 2 alone is Option A; patch 2 + patch 3 is the hybrid (ppGpp AND per-isoacceptor charging)."""
    a, p = capability.DRAFT_PATCHES["EXT-PORT-A"], capability.DRAFT_PATCHES["EXT-PORT-P"]
    assert "EXT-PORT-P" in a.composes_with and "EXT-PORT-A" in p.composes_with
    combo = capability.draft_patch_combination(("EXT-PORT-A", "EXT-PORT-P"))
    assert combo is not None and combo["arm"] == "KINAP"
    assert combo["applied"] is False and combo["in_corpus"] is False
    assert "--kinetic-aa-supply" in combo["flags"] and "--kinetic-ppgpp" in combo["flags"]
    # A single patch is NOT the hybrid — Option A on its own is one axis of two.
    assert capability.draft_patch_combination(("EXT-PORT-A",)) is None


# --- per-capability routing ---------------------------------------------------------------------------

def test_ppgpp_gap_names_patch_3_under_kinetic_only():
    c = capability.get("ppgpp_stringent_response")
    patch = c.draft_patch_in("kinetic")
    assert patch is not None and patch.patch_id == "EXT-PORT-P"
    # coarse_kinetic does NOT solve charging at all, so a ppGpp patch fed by charged tRNA cannot apply there.
    # A tuple key spanning both kinetic models would have claimed a route that does not exist.
    assert c.draft_patch_in("coarse_kinetic") is None
    # steady_state already represents it. Offering a patch where there is no gap is a different lie.
    assert c.draft_patch_in("steady_state") is None


def test_amino_acid_uptake_gap_names_patch_2_under_kinetic_only():
    c = capability.get("amino_acid_uptake_from_the_medium")
    patch = c.draft_patch_in("kinetic")
    assert patch is not None and patch.patch_id == "EXT-PORT-A"
    assert c.draft_patch_in("coarse_kinetic") is None
    assert c.draft_patch_in("steady_state") is None


def test_capability_without_a_patch_offers_none():
    """per_isoacceptor_charging under steady_state has no patch — the gap is the model's design, not a port."""
    c = capability.get("per_isoacceptor_trna_charging")
    assert c.draft_patch_in("steady_state") is None
    assert c.draft_patch_in("coarse_kinetic") is None


# --- what check() hands the agent ---------------------------------------------------------------------

def test_check_offers_the_patch_without_turning_the_refusal_into_a_yes():
    out = capability.check("ppgpp_stringent_response", "kinetic")
    assert out["can_answer"] is False and out["report_a_number"] is False
    assert out["why_not"] == "another_mode_represents_it"
    assert out["switch"]["mode"] == "steady_state"          # the existing route is untouched
    dp = out["draft_patch"]
    assert dp["patch_id"] == "EXT-PORT-P" and dp["flag"] == "--kinetic-ppgpp"
    # The three facts that keep this from reading as availability.
    assert dp["applied"] is False and dp["in_corpus"] is False
    # MEASURED in kinetic_patch3_ppgpp.patch: resolve_elongation_flags raises on --kinetic-ppgpp without
    # --kinetic-trna-charging AND raises again without ppgpp_regulation. Both prerequisites, or the run dies
    # at argument resolution — a one-item `requires` would have sent Alexey a command that cannot start.
    assert "--kinetic-trna-charging" in dp["requires"]
    assert any("ppgpp_regulation" in r for r in dp["requires"])
    assert "EXT-PORT-A" in dp["composes_with"]


def test_check_omits_the_patch_where_none_exists():
    assert "draft_patch" not in capability.check("ppgpp_stringent_response", "coarse_kinetic")
    assert "draft_patch" not in capability.check("per_isoacceptor_trna_charging", "steady_state")


def test_refusal_prose_names_the_patch_and_its_unapplied_status():
    text = capability.get("amino_acid_uptake_from_the_medium").refusal("kinetic")
    assert "--kinetic-aa-supply" in text and "EXT-PORT-A" in text
    # Naming a flag without its status is how "drafted" becomes "supported" in an agent's next sentence.
    low = text.lower()
    assert "not applied" in low or "drafted" in low
    assert "steady_state" in text          # the switch route must survive alongside the patch route


def test_steady_state_refusals_never_mention_a_kinetic_patch():
    """The oldest defect in this module: one mode's sentence rendered inside another mode's refusal."""
    for key in ("per_isoacceptor_trna_charging",):
        text = capability.get(key).refusal("steady_state")
        assert "--kinetic-ppgpp" not in text and "--kinetic-aa-supply" not in text


# --- audit: force the declaration to be wrong ---------------------------------------------------------

def test_audit_catches_a_patch_keyed_by_a_mode_that_does_not_exist(monkeypatch):
    """A typo'd mode key makes the route unreachable in every mode, silently. Same shape as a stale flag."""
    broken = capability.Capability(
        key="synthetic_broken_patch_mode", question="q", present=True, holds_in=("steady_state",),
        draft_patch={"kinnetic": "EXT-PORT-P"})
    monkeypatch.setattr(capability, "CAPABILITIES", capability.CAPABILITIES + (broken,))
    bad = capability.audit()["undeclared_prose_modes"]
    assert any("draft_patch" in b and "kinnetic" in b for b in bad)


def test_audit_catches_a_patch_id_that_is_not_declared(monkeypatch):
    broken = capability.Capability(
        key="synthetic_unknown_patch", question="q", present=True, holds_in=("steady_state",),
        draft_patch={"kinetic": "EXT-PORT-ZZ"})
    monkeypatch.setattr(capability, "CAPABILITIES", capability.CAPABILITIES + (broken,))
    out = capability.audit()
    assert any("EXT-PORT-ZZ" in b for b in out["broken_patch_routes"])
    assert out["ok"] is False


def test_audit_catches_a_patch_offered_where_the_capability_already_holds(monkeypatch):
    """Patching a mode that already represents the mechanism is an offer to fix something that works."""
    broken = capability.Capability(
        key="synthetic_patch_without_a_gap", question="q", present=True, holds_in=("kinetic",),
        draft_patch={"kinetic": "EXT-PORT-P"})
    monkeypatch.setattr(capability, "CAPABILITIES", capability.CAPABILITIES + (broken,))
    out = capability.audit()
    assert any("synthetic_patch_without_a_gap" in b for b in out["broken_patch_routes"])
    assert out["ok"] is False


def test_audit_is_clean_on_the_real_registry():
    out = capability.audit()
    assert out["broken_patch_routes"] == [], out["broken_patch_routes"]
    assert not [b for b in out["undeclared_prose_modes"] if "draft_patch" in b]
