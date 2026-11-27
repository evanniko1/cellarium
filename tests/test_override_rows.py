"""A row produced under an envelope override says so, and is not reportable (D30, 2026-11-27).

D28 lets a pre-registered negative control run although the envelope refuses its design (CRIT V3: the model's own
threshold rule under a shift). Such a run is evidence about the DEFECT, read only by the scorer that registered it.
Its manifest row therefore carries the override, and `reportable` is False, so no analysis path reports it as a result;
before D30 nothing on the row distinguished it from an ordinary run.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cellarium import manifest, runner  # noqa: E402
from cellarium.model import Design, SimResult  # noqa: E402


def _row(run_root: Path) -> dict:
    rec = SimResult(id="probe_0", label="probe", design=Design(perturbation="timeline",
                                                                timeline="0 minimal, 1200 minimal_minus_oxygen"))
    return manifest._flat_row(rec, 900, run_root, sim_path="cellarium")


def test_an_override_row_carries_the_reason_and_is_not_reportable(tmp_path, monkeypatch):
    from cellarium import qc
    monkeypatch.setattr(qc, "is_reportable", lambda rec: True)        # would be reportable on its QC alone
    (tmp_path / runner._ENVELOPE_OVERRIDE_FILE).write_text(
        json.dumps({"override": "CRIT tier 1 negative control", "refused_because": "threshold"}), encoding="utf-8")
    row = _row(tmp_path)
    assert row["envelope_override"] == "CRIT tier 1 negative control"
    assert row["reportable"] is False


def test_an_ordinary_row_is_unchanged(tmp_path, monkeypatch):
    from cellarium import qc
    monkeypatch.setattr(qc, "is_reportable", lambda rec: True)
    row = _row(tmp_path)
    assert row["envelope_override"] is None and row["reportable"] is True


def test_an_unreadable_override_file_still_marks_the_row(tmp_path, monkeypatch):
    """A file that exists but cannot be parsed is still an override: the run went past a refusal."""
    from cellarium import qc
    monkeypatch.setattr(qc, "is_reportable", lambda rec: True)
    (tmp_path / runner._ENVELOPE_OVERRIDE_FILE).write_text("{not json", encoding="utf-8")
    row = _row(tmp_path)
    assert row["envelope_override"] and row["reportable"] is False
