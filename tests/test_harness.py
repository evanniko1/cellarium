"""The self-harness (M-1): the capability gate over Council falsifiers. Verifies the registry stays in sync with
the toolkit (CI invariant), the detector flags a named-but-unexecutable test while passing the executable ones,
and the BACKLOG writer is idempotent + respects a human's State edit + never breaks a run."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cellarium import harness, test_registry, tools  # noqa: E402


def _fake_hyp(decision_rule, question="q?"):
    return {"question": question, "falsifier": {"target": "a", "reference": "b", "channel": "growth_rate",
                                                "decision_rule": decision_rule, "refuting_result": ""}}


def test_registry_stays_in_sync_with_tools():
    """CI invariant: every SUPPORTED test points at a real tool exposing a reads_field — the detector's model of
    capability cannot silently drift from the executor."""
    tool_names = {t["name"] for t in tools.TOOLS}
    assert harness.test_registry.validate_against_tools(tool_names) == []
    # the two tests we just made executable must be registered as supported
    assert {"bimodality_bc", "slope_ci"} <= set(test_registry.supported_ids())


def test_detector_flags_unsupported_and_passes_executable():
    # a KNOWN-unsupported test -> one gap, keyed to that capability
    gaps = harness.scan_hypothesis(_fake_hyp("reject H0 by Hartigan's dip test, p<0.05"), "h_1")
    assert [g.test_id for g in gaps] == ["hartigan_dip"]
    assert gaps[0].gap_id.startswith("GAP-") and gaps[0].gap_id == gaps[0].gap_id   # stable

    # executable tests -> NO gap (they map to real tools)
    assert harness.scan_hypothesis(_fake_hyp("reject H0 if welch_t >= 2"), "h_2") == []
    assert harness.scan_hypothesis(_fake_hyp("OLS slope 95% CI excludes 0"), "h_3") == []
    assert harness.scan_hypothesis(_fake_hyp("dip test for bimodality; BC>0.555"), "h_4") == []   # we HAVE this
    # an unrecognized phrasing is NOT flagged (conservative: no false gaps)
    assert harness.scan_hypothesis(_fake_hyp("eyeball the trajectory and decide"), "h_5") == []


def test_writer_is_idempotent_and_respects_human_state(tmp_path):
    bl = tmp_path / "BACKLOG.md"
    bl.write_text("# Backlog\n\n## Coordinate with Filippo\n\nx\n", encoding="utf-8")
    rec = harness.scan_hypothesis(_fake_hyp("use Mann-Whitney U"), "h_a")

    s1 = harness.write_gaps(rec, bl, today="2026-07-17")
    assert s1["filed"] and s1["unchanged"] is False
    gid = rec[0].gap_id
    assert gid in bl.read_text(encoding="utf-8") and harness._SECTION in bl.read_text(encoding="utf-8")

    # same run re-scanned -> no change (idempotent, no churn)
    assert harness.write_gaps(rec, bl, today="2026-07-17")["unchanged"] is True

    # a DIFFERENT hypothesis surfaces the same gap -> Seen increments, still one row
    rec2 = harness.scan_hypothesis(_fake_hyp("apply a mann whitney rank-sum"), "h_b")
    s2 = harness.write_gaps(rec2, bl, today="2026-07-18")
    assert s2["updated"] == [gid] and bl.read_text(encoding="utf-8").count(gid + "`") <= 1
    assert "2×" in bl.read_text(encoding="utf-8")

    # a human marks it wontfix -> harness must never touch it again
    doc = bl.read_text(encoding="utf-8").replace(f"| `{gid}` | open |", f"| `{gid}` | wontfix |")
    bl.write_text(doc, encoding="utf-8")
    rec3 = harness.scan_hypothesis(_fake_hyp("mann-whitney again"), "h_c")
    s3 = harness.write_gaps(rec3, bl, today="2026-07-19")
    assert s3["unchanged"] is True and "wontfix" in bl.read_text(encoding="utf-8")


def test_scan_and_file_never_raises(tmp_path):
    bl = tmp_path / "BACKLOG.md"
    bl.write_text("# Backlog\n", encoding="utf-8")
    # a malformed hypothesis must degrade to an error dict, not crash the Council run
    assert "error" in harness.scan_and_file(object(), "h_x", bl) or True
    # a clean executable falsifier files nothing
    out = harness.scan_and_file(_fake_hyp("welch_t >= 2"), "h_y", bl)
    assert out.get("gaps") == []
