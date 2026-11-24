"""`scripts/regulation_scope.py --with-reader`: the gene-level rows record what the reader returned, or why not.

Appendix J's nitrate and arabinose rows need the simulator's reader over full simOut. A row that cannot be computed
must say why rather than disappear, and a row that can must carry its run counts and the runs the reader could not
see, as counts and output-tree names only: the script's output is quoted in a public document, which records no
local paths.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("regulation_scope", ROOT / "scripts" / "regulation_scope.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_comparison_whose_raw_is_not_local_is_recorded_as_not_re_derived(monkeypatch):
    rs = _load()
    monkeypatch.setattr(rs.tools, "regulon_response",
                        lambda regulon, cond, ref: {"needs_raw": True, "message": "no local runs for reference"})
    monkeypatch.setattr(rs.differential, "all_gene_lfc", lambda *a, **k: {"error": "no local runs"})
    rows = rs.reader_rows()
    controlled = [r for r in rows if r["reference"] == "condition/no_oxygen"]
    assert len(controlled) == 2
    assert all(r["re_derived"] is False and "no local runs" in r["why_not"] for r in controlled)


def test_a_comparison_the_reader_answers_records_its_counts_and_no_paths(monkeypatch):
    rs = _load()
    monkeypatch.setattr(rs.tools, "regulon_response", lambda regulon, cond, ref: {
        "verdict": "no significant regulon response", "n_regulon_genes": 9, "n_significant_in_regulon": 0,
        "n_significant_total": 306, "movers": []})
    monkeypatch.setattr(rs.differential, "all_gene_lfc", lambda *a, **k: {
        "n_target_runs": 2, "n_reference_runs": 17,
        "lfc": {"ARABISOM-MONOMER[c]": {"symbol": "araA", "log2fc": -1.73, "target": 9.5, "reference": 33.8},
                "OTHER-MONOMER[c]": {"symbol": "zzzZ", "log2fc": 3.0, "target": 80.0, "reference": 10.0}},
        "_unreachable_runs": [{"role": "reference", "n_reachable": 17, "n_unreachable": 4,
                               "output_trees_not_mounted": ["runs_seed_aars"],
                               "runs": ["C:\\somewhere\\runs_seed_aars\\x\\000001"],
                               "why": "the reader container mounts only C:\\somewhere\\runs"}]})
    rows = rs.reader_rows()
    ara = next(r for r in rows if r["regulon"] == "ara_arabinose")
    assert ara["re_derived"] is True
    assert (ara["n_significant_in_regulon"], ara["n_significant_total"]) == (0, 306)
    assert ara["regulon_levels"] == {"araA": {"target": 9.5, "reference": 33.8, "log2fc": -1.73}}
    assert (ara["n_target_runs"], ara["n_reference_runs"]) == (2, 17)
    assert ara["unreachable"] == [{"role": "reference", "n_reachable": 17, "n_unreachable": 4,
                                   "output_trees_not_mounted": ["runs_seed_aars"]}]
    assert "somewhere" not in json.dumps(rows)


def test_the_flag_is_what_adds_the_gene_level_rows(monkeypatch):
    rs = _load()
    assert rs.wants_reader(["--with-reader"]) is True
    assert rs.wants_reader([]) is False
