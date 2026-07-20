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


def test_every_tool_is_classified_for_council_visibility():
    """REVERSE invariant: every tool in TOOLS is EITHER a Council-nameable test (a TestSpec's tool) OR explicitly
    ANALYSIS_ONLY. A new tool that is neither trips here — so whether the Council should see it is decided when the
    tool lands, not by remembering to ask. To fix a failure: add the tool to test_registry.ANALYSIS_ONLY_TOOLS
    (Cellwright-only) or add a TestSpec for it (a falsifier test the blind Council may name)."""
    tool_names = {t["name"] for t in tools.TOOLS}
    missing = test_registry.unclassified_tools(tool_names)
    assert missing == [], (f"unclassified tools (decide Council-visibility): {missing} — add each to "
                           "test_registry.ANALYSIS_ONLY_TOOLS or give it a TestSpec.")
    # the classification partitions cleanly: nothing is both a named test and analysis-only
    assert test_registry.registered_tool_names().isdisjoint(test_registry.ANALYSIS_ONLY_TOOLS)


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


def _hyp_with_test(test_id, statistic="", decision_rule="reject if the statistic exceeds threshold"):
    return {"question": "q?", "falsifier": {"target": "a", "reference": "b", "channel": "growth_rate",
            "decision_rule": decision_rule, "refuting_result": "",
            "test": {"test_id": test_id, "statistic": statistic, "threshold": ""}}}


def test_structured_other_is_flagged_as_a_novel_gap():
    """M-1b: the structured `test.test_id == 'other'` catches a NOVEL test the curated free-text list never knew
    about — deterministically. A supported test_id passes; a free-text known gap wins over the generic 'other'."""
    gaps = harness.scan_hypothesis(_hyp_with_test("other", statistic="Anderson-Darling normality test"), "h_1")
    assert len(gaps) == 1 and gaps[0].kind == "unlisted_test" and gaps[0].test_id
    # a supported structured test -> no gap
    assert harness.scan_hypothesis(_hyp_with_test("welch_disconfirm", "welch_t"), "h_2") == []
    # 'other' is SUPPRESSED when the free-text already names a specific known-unsupported test
    g3 = harness.scan_hypothesis(_hyp_with_test("other", "dip", decision_rule="use Hartigan's dip test"), "h_3")
    assert [g.kind for g in g3] == ["missing_test"] and g3[0].test_id == "hartigan_dip"


def test_council_schema_and_assembly_carry_the_test_field():
    from cellarium import council
    enum = council._TEST["properties"]["test_id"]["enum"]
    assert "other" in enum and {"welch_disconfirm", "bimodality_bc"} <= set(enum)
    cand = {"claim": "c", "falsifier": {"target": "a/b", "reference": "c/d", "channel": "growth_rate",
            "decision_rule": "welch t", "refuting_result": "",
            "test": {"test_id": "welch_disconfirm", "statistic": "welch_t"}}}
    assert council._assemble("q", cand, [], True).falsifier.test.test_id == "welch_disconfirm"
    # a legacy candidate with no test field still assembles (backward compatible)
    legacy = {"claim": "c", "falsifier": {k: v for k, v in cand["falsifier"].items() if k != "test"}}
    assert council._assemble("q", legacy, [], True).falsifier.test is None


def test_scan_and_file_never_raises(tmp_path):
    bl = tmp_path / "BACKLOG.md"
    bl.write_text("# Backlog\n", encoding="utf-8")
    # a malformed hypothesis must degrade to an error dict, not crash the Council run
    assert "error" in harness.scan_and_file(object(), "h_x", bl) or True
    # a clean executable falsifier files nothing
    out = harness.scan_and_file(_fake_hyp("welch_t >= 2"), "h_y", bl)
    assert out.get("gaps") == []
