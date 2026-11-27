"""evals/bv14d_robustness.py: the post hoc checks beside BV-14d's registered result. The arithmetic must be the
registered scorer's (the same log2 ratio of arm means, the same interaction on per-seed log2 values), applied per
generation and with discarded runs added back, so a robustness number can never disagree with the result it checks
because it was computed differently."""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))
sys.path.insert(0, str(ROOT / "src"))

import bv14d_robustness as R  # noqa: E402


def _synth(values: dict) -> dict:
    """{run name: [gen0, gen1, gen2]} of nar synthesis probabilities -> the worker's per-run shape."""
    return {name: [{"synth": {"narGHJI": v}} for v in gens] for name, gens in values.items()}


VALID = {"F1": [300, 302], "F2": [300, 302], "O1": [330, 332], "O2": [330, 331, 332]}


def test_the_contrasts_are_the_registered_scorers_arithmetic():
    # F2/F1 = 2x (log2 +1), O2/O1 = 8x (log2 +3): the interaction is +2 with no spread
    raw = _synth({"F1-s300": [1, 1, 1], "F1-s302": [1, 1, 1], "F2-s300": [2, 2, 2], "F2-s302": [2, 2, 2],
                  "O1-s330": [1, 1, 1], "O1-s332": [1, 1, 1],
                  "O2-s330": [8, 8, 8], "O2-s331": [8, 8, 8], "O2-s332": [8, 8, 8]})
    c = R.contrasts(raw, VALID, gen=2, op="narGHJI")
    assert c["NarL_effect_FNR_at_fit"] == 1.0 and c["NarL_effect_FNR_off"] == 3.0
    assert c["interaction"]["estimate"] == 2.0 and c["interaction"]["n"] == [3, 2, 2, 2]


def test_each_generation_is_read_on_its_own():
    raw = _synth({"F1-s300": [1, 1, 1], "F1-s302": [1, 1, 1], "F2-s300": [4, 2, 2], "F2-s302": [4, 2, 2],
                  "O1-s330": [1, 1, 1], "O1-s332": [1, 1, 1],
                  "O2-s330": [2, 2, 2], "O2-s331": [2, 2, 2], "O2-s332": [2, 2, 2]})
    assert R.contrasts(raw, VALID, gen=0, op="narGHJI")["NarL_effect_FNR_at_fit"] == 2.0
    assert R.contrasts(raw, VALID, gen=1, op="narGHJI")["NarL_effect_FNR_at_fit"] == 1.0


def test_adding_a_discarded_run_back_changes_its_arm_and_nothing_else():
    raw = _synth({"F1-s300": [1, 1, 1], "F1-s301": [1, 1, 4], "F1-s302": [1, 1, 1],
                  "F2-s300": [2, 2, 2], "F2-s302": [2, 2, 2], "O1-s330": [1, 1, 1], "O1-s332": [1, 1, 1],
                  "O2-s330": [2, 2, 2], "O2-s331": [2, 2, 2], "O2-s332": [2, 2, 2]})
    base = R.contrasts(raw, VALID, gen=2, op="narGHJI")
    plus = R.contrasts(raw, R.with_runs(VALID, ["F1-s301"]), gen=2, op="narGHJI")
    assert base["NarL_effect_FNR_off"] == plus["NarL_effect_FNR_off"]
    assert plus["NarL_effect_FNR_at_fit"] == round(math.log2(2 / 2), 3)       # F1 mean (1+4+1)/3 = 2
    assert R.with_runs(VALID, ["F1-s301"])["F1"] == [300, 301, 302] and VALID["F1"] == [300, 302]


def test_the_share_restored_uses_bv14s_observed_and_fitted_ratios():
    assert R.phi(0.25, r_bv14=0.25, r_fit=1.29) == 0.0
    assert R.phi(1.29, r_bv14=0.25, r_fit=1.29) == 1.0


def test_a_read_refuses_when_its_runs_are_gone_and_keeps_the_stored_read(tmp_path, monkeypatch, capsys):
    """The 13 finished runs are deposited and reclaimed, and O1-s331's partial output was deleted (2026-11-27): a re-read
    would find no simOut, record every generation as None and overwrite the stored read with it. It must refuse."""
    stored = tmp_path / "bv14d_robustness.json"
    stored.write_text('{"raw": {"kept": true}}\n', encoding="utf-8")
    monkeypatch.setattr(R, "SIM_ROOT", tmp_path / "runs")
    monkeypatch.setattr(R, "OUT", stored)
    monkeypatch.delenv("WCECOLI_DOCKER", raising=False)
    assert R.run() == 2
    assert stored.read_text(encoding="utf-8") == '{"raw": {"kept": true}}\n'
    err = capsys.readouterr().err
    assert "O1-s331" in err and "deleted" in err and "cellarium-corpus" in err
