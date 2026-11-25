"""The ParCa fits available: one record per knowledge base, joined to the runs made on it by kb_sha256.

The user (2026-11-25): "For the BV-14 local ParCa refit and the knowledge-based edit on the campaign branch we need
proper metadata for the resulting runs and the different ParCa fits available."
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import parca_fits as PF  # noqa: E402


def _kb(root: Path, sim_path: str, payload: bytes) -> str:
    f = root / sim_path / "kb" / "simData.cPickle"
    f.parent.mkdir(parents=True)
    f.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def test_every_kb_on_disk_gets_a_record_with_its_hash_and_its_runs(tmp_path):
    a = _kb(tmp_path, "cellarium", b"default fit")
    b = _kb(tmp_path, "bv14_no3_anaerobic", b"refit with nitrate")
    rows = [{"kb_sha256": a, "elongation_model": "steady_state"}] * 3 + [{"kb_sha256": b,
                                                                          "elongation_model": "steady_state"}]
    fits = PF.build(tmp_path, rows, known={})
    by = {f["sim_path"]: f for f in fits["fits"]}
    assert by["cellarium"]["kb_sha256"] == a and by["cellarium"]["manifest_rows"] == 3
    assert by["bv14_no3_anaerobic"]["manifest_rows"] == 1 and by["bv14_no3_anaerobic"]["file_on_this_machine"]


def test_a_kb_known_only_from_the_manifest_is_listed_and_marked_absent(tmp_path):
    _kb(tmp_path, "cellarium", b"default fit")
    rows = [{"kb_sha256": "0d861f80" + "0" * 56, "elongation_model": "steady_state"}]
    fits = PF.build(tmp_path, rows, known={})
    gone = [f for f in fits["fits"] if f["kb_sha256"].startswith("0d861f80")]
    assert len(gone) == 1 and gone[0]["file_on_this_machine"] is False and gone[0]["sim_path"] is None
    assert gone[0]["basis"] == "not recorded"          # absence of a record is said, not filled in


def test_hand_recorded_facts_attach_by_hash_prefix_and_never_override_the_measured_hash(tmp_path):
    h = _kb(tmp_path, "bv14_no3_anaerobic", b"refit with nitrate")
    known = {h[:8]: {"basis": "refit", "kb_sha256": "f" * 64, "flat_overrides": {"condition/condition_defs.tsv": "ab"}}}
    rec = PF.build(tmp_path, [], known=known)["fits"][0]
    assert rec["basis"] == "refit" and rec["kb_sha256"] == h and rec["flat_overrides"]


def test_the_stored_registry_records_the_bv14_fit_and_its_inputs():
    d = json.loads((REPO / "data" / "parca" / "fits.json").read_text(encoding="utf-8"))
    by = {f["kb_sha256"][:8]: f for f in d["fits"]}
    bv14 = by["9055ee3b"]
    assert bv14["sim_path"] == "bv14_no3_anaerobic"
    assert set(bv14["flat_overrides"]) == {"condition/condition_defs.tsv", "condition/media_recipes.tsv"}
    assert "no_oxygen_plus_nitrate" in bv14["conditions_added"]
    assert "plus_cytidine" in bv14["differs_from_public_branch"]
    assert by["3b2f8ebd"]["sim_path"] == "cellarium"
