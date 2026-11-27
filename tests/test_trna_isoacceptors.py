"""The isoacceptor table, reached by result id, in the mode the run actually used (D31, 2026-11-27).

S1's read-back (Cellwright, paid) could not read one number of the per-isoacceptor charging its hypothesis turns on,
and said so rather than invent a table:
- `trna_families(<result id>)` took the elongation model from the argument STRING, so a bare id read as steady_state
  while `raw.seed_runs` resolved the id to its kinetic run, and the mismatch guard refused;
- with `#elong:kinetic` appended the string was no longer an id, so there was "no local raw";
- `selective_charging` indexed `families` on a refusal and raised KeyError;
- and even when it worked, `per_family` averaged isoacceptors into one number per amino acid, so the within-family
  axis the kinetic model exists to resolve was never shown.
These tests use stand-ins for the raw reads: a kinetic row reached by id, with three leucine species and two arginine.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cellarium import raw, store, support, trna  # noqa: E402

IDS = ["leuT-tRNA[c]", "leuU-tRNA[c]", "leuW-tRNA[c]", "argQ-tRNA[c]", "argU-tRNA[c]"]
ROWS = {
    "wt_k0": {"id": "wt_k0", "label": "wildtype·basal#elong:kinetic·s0", "perturbation": "wildtype",
              "condition": "basal", "elongation_model": "kinetic", "seed": 0},
    "wt_k1": {"id": "wt_k1", "label": "wildtype·basal#elong:kinetic·s1", "perturbation": "wildtype",
              "condition": "basal", "elongation_model": "kinetic", "seed": 1},
    "ko_k0": {"id": "ko_k0", "label": "graded_gene_knockout·KO:leuS#expr:0.25#elong:kinetic·s0",
              "perturbation": "graded_gene_knockout", "condition": "KO:leuS", "elongation_model": "kinetic", "seed": 0},
    "wt_s0": {"id": "wt_s0", "label": "wildtype·basal·s0", "perturbation": "wildtype", "condition": "basal",
              "elongation_model": "steady_state", "seed": 0},
}
MEANS = {"wt_k0": [0.80, 0.70, 0.75, 0.90, 0.88], "wt_k1": [0.82, 0.68, 0.77, 0.90, 0.86],
         "ko_k0": [0.60, 0.20, 0.45, 0.89, 0.87], "wt_s0": [0.85, 0.85, 0.85, 0.90, 0.90]}


@pytest.fixture
def standins(monkeypatch):
    monkeypatch.setattr(store, "list_results", lambda include_dropped=False: list(ROWS.values()))

    def seed_runs(design_or_id):
        if design_or_id in ROWS:
            r = ROWS[design_or_id]
            return [{"result_id": r["id"], "seed": r["seed"], "root": r["id"], "elongation_model": r["elongation_model"]}]
        if design_or_id == "wildtype/basal#elong:kinetic":
            return [{"result_id": i, "seed": ROWS[i]["seed"], "root": i, "elongation_model": "kinetic"}
                    for i in ("wt_k0", "wt_k1")]
        return []
    monkeypatch.setattr(raw, "seed_runs", seed_runs)
    monkeypatch.setattr(trna, "_read", lambda root: (np.tile(np.array(MEANS[root]), (5, 1)), IDS, np.arange(5.0)))
    monkeypatch.setattr(trna, "_arrest_evidence", lambda root: {})
    monkeypatch.setattr(trna, "wildtype_null", lambda: {})
    monkeypatch.setattr(support, "attach", lambda out, design: None)


def _fam(out, name):
    return next(f for f in out["families"] if f["family"] == name)


def test_a_result_id_is_read_in_its_own_runs_mode(standins):
    out = trna.per_family("wt_k0")
    assert "refused" not in out and out["elongation_model"] == "kinetic"
    assert out["design_key"] == "wildtype/basal#elong:kinetic"


def test_the_kinetic_table_shows_each_isoacceptor_ascending_with_every_seed(standins):
    out = trna.per_family("wildtype/basal#elong:kinetic")
    leu = _fam(out, "leu")
    assert [i["trna"] for i in leu["isoacceptors"]] == ["leuU-tRNA[c]", "leuW-tRNA[c]", "leuT-tRNA[c]"]
    u = leu["isoacceptors"][0]
    assert u["charged_fraction"] == 0.69 and u["per_seed"] == {0: 0.7, 1: 0.68}
    assert leu["within_family_spread"] == 0.12                  # 0.81 - 0.69


def test_the_steady_state_table_shows_no_isoacceptors(standins):
    """Under steady_state the 86 values are one number per amino acid broadcast; an isoacceptor list there would
    present the broadcast as 86 measurements."""
    out = trna.per_family("wt_s0")
    assert out["elongation_model"] == "steady_state"
    assert all("isoacceptors" not in f for f in out["families"])


def test_selective_charging_between_two_kinetic_ids_reports_isoacceptor_drops(standins):
    out = trna.selective_charging("ko_k0", reference="wt_k0")
    assert "refused" not in out and out["elongation_model"] == out["reference_elongation_model"] == "kinetic"
    drops = {d["trna"]: d["drop_pct"] for d in out["isoacceptor_drops"]}
    assert drops["leuU-tRNA[c]"] == -71.4 and drops["leuT-tRNA[c]"] == -25.0
    assert out["isoacceptor_drops"][0]["trna"] == "leuU-tRNA[c]"           # the steepest first


def test_selective_charging_refuses_a_kinetic_id_against_the_steady_state_default(standins):
    out = trna.selective_charging("ko_k0")
    assert out["refused"] and "kinetic" in out["refused"] and "steady_state" in out["refused"]


def test_a_refused_table_is_passed_on_not_indexed(standins, monkeypatch):
    monkeypatch.setattr(trna, "per_family", lambda design, seed=None: {"design": design, "refused": "ARRESTED",
                                                                      "most_starved": None})
    out = trna.selective_charging("ko_k0", reference="wt_k0")
    assert out.get("refused") == "ARRESTED"
