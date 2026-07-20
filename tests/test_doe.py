"""M-5: the design-of-experiments primitives for falsifier panels — factorial / subsample / randomize / block /
power — pure and scipy-free, plus the `design_panel` tool wiring (power grounded in the corpus replicate CV,
mocked here so the test is offline)."""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cellarium import doe  # noqa: E402


def test_full_factorial_crosses_all_levels():
    cells = doe.full_factorial({"gene": ["pfkA", "pfkB"], "condition": ["basal", "acetate"]})
    assert len(cells) == 4 and {"gene": "pfkA", "condition": "acetate"} in cells
    assert doe.full_factorial({"gene": []}) == []          # an empty level list -> no cells to cross
    assert doe.full_factorial({}) == []


def test_screening_subsample_caps_deterministically():
    cells = doe.full_factorial({"g": list("abcd"), "c": list("wxyz")})   # 16 cells
    sub = doe.screening_subsample(cells, cap=6, seed=0)
    assert len(sub) == 6 and all(c in cells for c in sub)                # a real subset
    assert sub == doe.screening_subsample(cells, cap=6, seed=0)          # deterministic
    assert len(doe.screening_subsample(cells, cap=99)) == 16            # under the cap -> no-op


def test_randomize_is_a_deterministic_permutation():
    cells = doe.full_factorial({"g": list("abcdef")})
    r = doe.randomize(cells, seed=3)
    assert sorted(map(str, r)) == sorted(map(str, cells))               # still a permutation of the cells
    assert r == doe.randomize(cells, seed=3)                            # deterministic (seeded)


def test_block_partitions_by_nuisance_factor():
    cells = doe.full_factorial({"gene": ["a", "b"], "gen": [1, 3]})
    blocks = doe.block(cells, "gen")
    assert set(blocks) == {1, 3} and len(blocks[1]) == 2 and len(blocks[3]) == 2


def test_power_math_matches_power_check_shape():
    need = doe.seeds_needed(0.05, 10.0)
    assert need == math.ceil(doe._K * (0.05 / 0.10) ** 2)
    assert doe.mde_pct(0.05, 4) == round(0.05 * math.sqrt(doe._K / 4) * 100, 2)
    assert doe.power_annotation(0.05, 10.0, need)["adequately_powered"] is True        # n == seeds_needed
    assert doe.power_annotation(0.05, 10.0, need - 1)["adequately_powered"] is False
    assert doe.seeds_needed(None, 10.0) is None and doe.mde_pct(None, 4) is None        # unknown CV -> None


def test_panel_orchestrates_layout_power_and_blocks():
    out = doe.panel({"gene": ["pfkA", "pfkB", "tpiA"], "condition": ["basal", "acetate"]},
                    seeds=4, generations=3, cv=0.05, effect_pct=10.0, block_by="condition", seed=1)
    assert out["n_full_factorial"] == 6 and out["n_cells"] == 6 and out["subsampled"] is False
    assert out["total_sims"] == 24                                       # 6 cells × 4 seeds
    assert sorted(map(str, out["run_order"])) == sorted(map(str, doe.full_factorial(out["factors"])))
    assert out["power"]["target_effect_pct"] == 10.0 and set(out["blocks"]) == {"basal", "acetate"}

    big = doe.panel({"g": list("abcdefgh"), "c": list("12345678")}, cv=0.05, cap=10)   # 64 -> 10
    assert big["subsampled"] is True and big["n_cells"] == 10 and "Screening subsample" in big["note"]

    assert doe.panel({"g": ["a", "b"]}, cv=None)["power"] is None        # no CV -> power unestimated


def test_design_panel_tool_grounds_power_in_corpus_cv(monkeypatch):
    from cellarium import tools

    assert "error" in tools.design_panel(factors={})                    # bad input -> clear error

    monkeypatch.setattr(tools, "power_check", lambda **kw: {"observed_replicate_cv": 0.04})
    out = tools.design_panel(factors={"gene": ["pfkA", "pfkB"]}, channel="growth_rate", seeds=4, effect_pct=10.0)
    assert out["n_cells"] == 2 and out["power_channel"] == "growth_rate" and out["total_sims"] == 8
    assert out["power"]["observed_replicate_cv"] == 0.04                 # power grounded in the corpus CV

    monkeypatch.setattr(tools, "power_check", lambda **kw: {"error": "no replicated design"})
    out = tools.design_panel(factors={"gene": ["pfkA"]})
    assert out["power"] is None and "power_note" in out                  # no CV -> unestimated, with a note, no crash
