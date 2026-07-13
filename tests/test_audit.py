"""Corpus-audit smoke tests — the read-only inventory + the compaction guardrail. Run: python -m pytest tests/test_audit.py"""

from cellarium import audit, manifest, tools


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
    assert set(r) >= {"summary", "coverage", "redundancy", "gaps", "housekeeping", "disclaimer"}
    s = r["summary"]
    assert s["n_designs"] >= 0 and s["n_runs"] >= 0
    assert r["redundancy"]["est_gb_prunable_safe"] >= 0
    assert r["gaps"]["feasible_8gen_lineages"] >= 0 and r["gaps"]["free_disk_gb"] >= 0


def test_redundancy_verdict_is_power_grounded():
    """Redundancy is a grounded TOOL decision, not the agent's opinion: prune-safe iff target-seed MDE clears the
    reference effect, given the design's own replicate CV."""
    red = audit.redundancy()
    if "error" in red:
        return
    assert red["channel"] and "ref_effect_pct" in red
    for info in red["designs"].values():
        assert info["verdict"] in ("prune-safe", "keep-for-power")
        assert info["mde_pct_at_target"] >= info["mde_pct_at_current"]     # fewer seeds -> larger MDE
        assert (info["verdict"] == "prune-safe") == (info["mde_pct_at_target"] <= red["ref_effect_pct"])


def test_crashed_runs_are_never_flagged_as_prunable():
    """keep-all-models: a crashed KO is a valid inviable datapoint, not dead weight to delete."""
    sup = audit.supersession()
    if "error" in sup:
        return
    assert "n_inviable_by_crash" in sup                 # reported as a coverage fact...
    assert "kept on purpose" in sup["note"]             # ...explicitly kept, not pruned
    assert not any("crash" in k.lower() and "prun" in k.lower() for k in sup)


def test_compact_dry_run_is_read_only():
    """Supersession is deterministic housekeeping, not a decision — compact() dedups without judgment or side effects."""
    r = manifest.compact(dry_run=True)
    if "error" in r:                                    # no shards -> graceful error
        return
    assert r["dry_run"] is True
    assert r["rows_after"] <= r["rows_before"]          # dedup never adds rows
    assert r["superseded_dropped"] == r["rows_before"] - r["rows_after"]
    assert "files_after" not in r                       # dry run touches no files


def test_prune_candidates_lists_only_prune_safe_excess_and_deletes_nothing():
    """The resolver is deterministic and safe: it only lists excess seeds of PRUNE-SAFE designs, and deletes nothing."""
    pc = audit.prune_candidates()
    if "error" in pc:
        return
    red = audit.redundancy()
    safe = {d for d, i in red.get("designs", {}).items() if i["verdict"] == "prune-safe"}
    keep = {d for d, i in red.get("designs", {}).items() if i["verdict"] == "keep-for-power"}
    for c in pc["candidates"]:
        assert c["design"] in safe and c["design"] not in keep     # only prune-safe, never keep-for-power
        assert "run_root" in c and isinstance(c["raw_on_disk"], bool)
    assert pc["est_gb_on_disk"] >= 0
    assert "DELETES NOTHING" in pc["note"]                         # read-only resolver


def test_dispatch_routes_corpus_audit():
    out = tools.dispatch("corpus_audit", {})
    assert out.get("error") != "unknown tool 'corpus_audit'"   # registered in _DISPATCH
    assert "summary" in out or "error" in out
