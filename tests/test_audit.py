"""Corpus-audit smoke tests — the read-only inventory. Run: python -m pytest tests/test_audit.py"""

from cellarium import audit, tools


def test_gb_estimate_scales_with_generations_and_seeds():
    assert audit._gb(8, 1) == round(8 * audit.GB_PER_GENERATION, 2)
    assert audit._gb(4, 3) == round(4 * audit.GB_PER_GENERATION * 3, 2)
    assert audit._gb(0, 5) == 0.0
    assert audit._gb(None, 2) == 0.0        # missing generation count is treated as 0, never crashes


def test_latest_per_run_keeps_newest_ts():
    rows = [{"run_key": "a", "ts": 1}, {"run_key": "a", "ts": 5}, {"run_key": "b", "ts": 2}]
    live = {r["run_key"]: r for r in audit._latest_per_run(rows)}
    assert live["a"]["ts"] == 5            # newest wins — matches store's read-time dedup
    assert len(live) == 2


def test_design_label():
    assert audit._design({"perturbation": "gene_knockout", "condition": "KO:pfkA"}) == "gene_knockout/KO:pfkA"
    assert audit._design({"perturbation": "wildtype", "condition": None, "timeline": None}) == "wildtype/basal"


def test_audit_report_is_well_formed():
    r = audit.audit_report()
    if "error" in r:                        # empty/absent corpus is a graceful error, not a crash
        return
    assert set(r) >= {"summary", "coverage", "redundancy", "supersession", "gaps", "disclaimer"}
    s = r["summary"]
    assert s["n_designs"] >= 0 and s["n_runs"] >= 0
    assert r["redundancy"]["est_gb_prunable"] >= 0
    assert r["gaps"]["feasible_8gen_lineages"] >= 0
    assert r["gaps"]["free_disk_gb"] >= 0


def test_crashed_runs_are_never_flagged_as_prunable():
    """keep-all-models: a crashed KO is a valid inviable datapoint, not dead weight to delete."""
    sup = audit.supersession()
    if "error" in sup:
        return
    assert "n_inviable_by_crash" in sup                 # reported as a coverage fact...
    assert "NOT prune targets" in sup["note"]           # ...explicitly not a prune target
    assert not any("crash" in k.lower() and "prun" in k.lower() for k in sup)


def test_dispatch_routes_corpus_audit():
    out = tools.dispatch("corpus_audit", {})
    assert out.get("error") != "unknown tool 'corpus_audit'"   # registered in _DISPATCH
    assert "summary" in out or "error" in out
