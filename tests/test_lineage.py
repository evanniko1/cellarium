"""Item 4c — generations descended from a cell that may have been split at the time cap are not averaged.

Measured 2026-10-12 from raw simOut (scripts/check_undivided_generations.py): argS@5% seeds 0, 2 and 3 ran
generation 2 for exactly 10,800 s without dividing and were then split, so generation 3 descends from an
undivided cell; rpmE seeds 0 and 3 carry `divided: false` on generation 2 yet ran 6,998-7,078 s — they divided,
and the flag (a chromosome-count proxy) was wrong.
"""

from __future__ import annotations

import json
from pathlib import Path

from cellarium import lineage, survey

ROOT = Path(__file__).resolve().parents[1]
CAP = lineage.CAP_S


def _g(i, divided, dur=None, start=0.0):
    g = {"i": i, "divided": divided, "growth": 0.0002, "ppgpp": 50.0}
    if dur is not None:
        g.update(t_start=start, t_end=start + dur)
    return g


def test_a_generation_that_ran_to_the_cap_is_time_capped_even_if_flagged_divided():
    pg = [_g(0, True, 2500), _g(1, True, CAP), _g(2, True, 2000)]
    st = [c["status"] for c in lineage.classify(pg)]
    assert st == ["divided", "time_capped", "terminal"]
    assert lineage.is_descendant_of_undivided(pg, 2) and not lineage.is_descendant_of_undivided(pg, 1)


def test_duration_below_the_cap_overrides_a_false_divided_flag():
    pg = [_g(0, True, 2529), _g(1, True, 7436), _g(2, False, 6998), _g(3, False, 506)]   # rpmE s0, measured
    cl = lineage.classify(pg)
    assert cl[2]["status"] == "divided" and cl[2]["flag_disagrees"] is True
    assert lineage.first_suspect_parent(pg) is None


def test_without_duration_a_false_flag_is_treated_conservatively():
    pg = [_g(0, False), _g(1, True), _g(2, True)]                                        # wildtype s1 shape
    assert [c["status"] for c in lineage.classify(pg)] == ["undivided_unverified", "divided_unverified",
                                                           "terminal"]
    assert lineage.summary(pg)["excluded_generations"] == [1, 2]


def test_the_measured_argS_lineage():
    pg = [_g(0, True, 2529), _g(1, True, 5848), _g(2, False, 10800.0), _g(3, False, 10800.0)]
    s = lineage.summary(pg)
    assert s["first_suspect_parent"] == 2 and s["excluded_generations"] == [3]
    assert s["generations"][3]["time_capped"] is True


def _rows(*per_gens):
    return [{"label": f"gene_knockout/KO:x seed{k}", "perturbation": "gene_knockout", "condition": "KO:x",
             "seed": k, "generation_qc": json.dumps(["ok"] * len(pg)), "per_generation": json.dumps(pg)}
            for k, pg in enumerate(per_gens)]


def test_compare_at_generation_excludes_descendants_of_an_undivided_cell(monkeypatch):
    healthy = [_g(0, True, 2500), _g(1, True, 2600), _g(2, True, 2700)]
    capped = [_g(0, True, 2500), _g(1, False, CAP), {**_g(2, True, 2700), "growth": 0.9}]
    monkeypatch.setattr(survey, "_leth_rows", lambda: _rows(healthy, capped))
    design = survey.design_key(_rows(healthy)[0])
    out = survey.read_at_generation(design, "growth_rate", 2)
    assert out["n"] == 1 and out["mean"] == 0.0002, "the 0.9 from the capped lineage must not be averaged"
    assert out["n_seeds_excluded_undivided_ancestor"] == 1
    assert survey.read_at_generation(design, "growth_rate", 1)["n"] == 2   # the capped generation itself counts


def test_trajectory_shows_the_exclusion_without_calling_it_a_collapse(monkeypatch):
    healthy = [_g(0, True, 2500), _g(1, True, 2600), _g(2, True, 2700)]
    capped = [_g(0, True, 2500), _g(1, False, CAP), _g(2, True, 2700)]
    monkeypatch.setattr(survey, "_leth_rows", lambda: _rows(healthy, capped))
    design = survey.design_key(_rows(healthy)[0])
    t = survey.trajectory(design, "growth_rate")
    gen2 = next(a for a in t["arc"] if a["generation"] == 2)
    assert gen2["n_ok"] == 1 and gen2["qc"].get("descendant_of_undivided") == 1
    assert t["collapses_at_generation"] is None


def test_new_rows_record_the_timing_the_classifier_needs():
    src = (ROOT / "src" / "cellarium" / "manifest.py").read_text(encoding="utf-8")
    assert '"t_start": g.t_start, "t_end": g.t_end' in src
    worker = (ROOT / "src" / "cellarium" / "_reader_worker.py").read_text(encoding="utf-8")
    assert 'mode == "gen_times"' in worker and "def mode_gen_times" in worker
