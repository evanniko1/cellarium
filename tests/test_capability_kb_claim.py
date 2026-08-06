"""The case-(c) refusal must not tell an operator the knowledge base differs when it does not.

MEASURED 2026-08-06: `provenance.kb_provenance` over a steady-state run root (runs_aars_argS) and over the
kinetic root (runs_kin_A) both return kb_sha256 5f19d040944a65abf1d9e0bfb05b7def19afc653ddc598bf4b97fed2f-
228c171 over 90,404,578 bytes. The elongation model is a runSim flag, not a ParCa refit, so it cannot move
the KB hash. The refusal used to assert "because that changes kb_sha256", which is false twice over: it
sends the reader hunting a difference that is not there, and it implies a matching hash would license
pooling — when what forbids pooling is that `fraction_trna_charged` means a different thing under each
model.
"""
import re

from src.cellarium import capability as C


def _case_c_refusal() -> str:
    """The refusal for a capability the asked-for model HAS but no corpus run used."""
    cap = next(c for c in C.CAPABILITIES if c.key == "per_isoacceptor_trna_charging")
    assert "kinetic" in cap.holds_in and "kinetic" not in C.MODES_IN_CORPUS, (
        "fixture assumption broken: this test needs a capability held by a NON-corpus mode")
    return cap.refusal("kinetic")


def test_refusal_does_not_claim_the_kb_hash_changes():
    text = _case_c_refusal()
    assert not re.search(r"changes\s+kb_sha256", text), (
        "the refusal claims the elongation model changes kb_sha256; it does not — both roots hash to "
        "5f19d040... over the same 90,404,578 bytes")


def test_refusal_states_the_kb_is_the_same():
    text = _case_c_refusal()
    assert "same fitted" in text.lower() and "kb_sha256 is unchanged" in text.lower(), (
        "an operator told to run a new campaign needs to know it runs against the SAME knowledge base, or "
        "they will go looking for a rebuild that is not required")


def test_refusal_still_forbids_pooling_and_names_the_real_reason():
    """Correcting the KB claim must not weaken the warning it was attached to."""
    text = _case_c_refusal().lower()
    assert "must not be pooled" in text or "not poolable" in text, "the no-pooling warning was lost"
    assert "elongation_model" in text, "the refusal must name the column that separates the runs"
    assert "channel" in text, (
        "the real reason must be stated: the same channel means something different under each model")


def test_measured_kb_identity_still_holds():
    """If a future refit DOES change the KB, this test fails and the prose above must be revisited."""
    import os
    from src.cellarium import provenance

    hashes = {}
    for root in ("runs_aars_argS", "runs_kin_A"):
        if not os.path.isdir(os.path.join(root, "cellarium", "kb")):
            import pytest
            pytest.skip(f"{root} not present in this checkout — the measurement cannot be re-verified here")
        os.environ["CELLARIUM_OUT"] = root
        # kb_provenance reads the root through the module-level OUT_ROOT, so re-resolve it per root.
        import importlib
        importlib.reload(provenance)
        hashes[root] = provenance.kb_provenance("cellarium").get("kb_sha256")
    assert len(set(hashes.values())) == 1, (
        f"the steady-state and kinetic roots no longer share a knowledge base: {hashes}. The refusal text "
        f"asserts they do — update it before this ships.")
