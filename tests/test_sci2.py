"""SCI-2 — the simulated-transcriptome vs real RNA-seq cross-check. The pure comparison engine (concordance,
Deming, Spearman, null baseline, verdict) and the graceful-degradation gate run everywhere; the real
pydeseq2/PRECISE-1K path is opt-in (needs the `rnaseq` extra + the data)."""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cellarium import sci2  # noqa: E402


def _genes(n, seed):
    rng = np.random.default_rng(seed)
    ref = {f"b{i:04d}": float(rng.normal(0, 2)) for i in range(n)}
    return ref, rng


def test_concordant_case_scores_high_with_slope_near_one():
    ref, rng = _genes(200, 1)
    sim = {g: v + rng.normal(0, 0.3) for g, v in ref.items()}      # sim ~ ref + small noise
    c = sci2.concordance(sim, ref)
    assert c["verdict"] == "CONCORDANT"
    assert c["pearson_r"] >= 0.9 and 0.8 <= c["deming_slope"] <= 1.2 and c["sign_concordance"] >= 0.9
    assert abs(c["null_pearson_r"]) < 0.2                          # the null baseline is ~0 -> the r is real signal


def test_divergent_case_is_flagged():
    ref, rng = _genes(200, 2)
    sim = {g: float(rng.normal(0, 2)) for g in ref}                # uncorrelated
    c = sci2.concordance(sim, ref)
    assert c["verdict"] == "DIVERGENT (model-limit)" and abs(c["pearson_r"]) < 0.3
    assert c["top_divergent_genes"] and "delta" in c["top_divergent_genes"][0]


def test_join_qc_and_too_few_genes():
    c = sci2.concordance({"b1": 1.0, "b2": 2.0}, {"b2": 2.0, "b3": 3.0})
    assert c["verdict"] == "INDETERMINATE" and c["join_qc"]["n_joined"] == 1


def test_deming_and_spearman_helpers():
    x = np.arange(50, dtype=float)
    y = 2.0 * x + 1.0
    slope, intercept = sci2._deming(x, y)
    assert abs(slope - 2.0) < 1e-6 and abs(intercept - 1.0) < 1e-6
    assert sci2._spearman(x, y) > 0.9999                          # perfectly monotone
    assert sci2._pearson(np.zeros(5), np.arange(5.0)) is None      # zero variance -> None


def test_gates_cleanly_without_pydeseq2(monkeypatch):
    monkeypatch.setattr(sci2, "_have_pydeseq2", lambda: False)
    ok, msg = sci2.available()
    assert ok is False and "pip install" in msg
    assert "error" in sci2.build_reference({"cond_B": "anaerobic"})
    assert "error" in sci2.rnaseq_concordance("condition/no_oxygen", {"cond_B": "anaerobic"})


def test_provenance_names_the_reference_and_caveat():
    p = sci2.provenance({"cond_B": "anaerobic"})
    assert p["reference"] == "PRECISE-1K" and p["zenodo_doi"] == sci2.ZENODO_DOI
    assert "NOT ground truth" in p["caveat"] and p["lfc"].startswith("UNSHRUNK")
