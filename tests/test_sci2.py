"""SCI-2 — the simulated-transcriptome vs real RNA-seq cross-check. The pure comparison engine (concordance,
Deming, Spearman, null baseline, verdict) and the graceful-degradation gate run everywhere; the real
pydeseq2/PRECISE-1K path is opt-in (needs the `rnaseq` extra + the data)."""

import os
import sys

import numpy as np
import pytest

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
    p = sci2.provenance({"cond_B": "wt_ph5"})
    assert p["reference"] == "PRECISE-1K" and p["zenodo_doi"] == sci2.ZENODO_DOI
    assert "NOT ground truth" in p["caveat"] and p["lfc"].startswith("UNSHRUNK")


def test_bnumber_map_is_present_and_correct():
    bmap = sci2._bnumber_map()
    assert len(bmap) > 4000                                   # committed EcoCyc-derived map
    assert bmap.get("pfkA") == "b3916" and bmap.get("fbaA") == "b2925"   # match iML1515 (SCI-1)


# ---- SCI-2c: the all-gene sim-mRNA reader mode (host side; the worker runs only in the model image) ----

def test_all_gene_lfc_annotates_by_the_right_id_space_per_kind(monkeypatch):
    """Regression (the SCI-2c blocker): mRNA ids are cistron_ids ('EG10016_RNA[c]'), so they must be annotated by
    the CISTRON map — NOT the monomer-keyed `_reverse_gene_map`, which annotates every mRNA gene as None and
    collapses the b-number join. Protein ids are monomer_ids and use the monomer reverse map (parity with
    top_movers)."""
    from cellarium import differential, reader

    monkeypatch.setattr(differential, "_design_run_roots", lambda label: [])          # no local runs -> clean error
    assert "error" in differential.all_gene_lfc("d", "ref", kind="mrna")

    monkeypatch.setattr(differential, "_design_run_roots", lambda label: ["/fake/root"])
    # a MONOMER map that must NOT be used for mRNA (it can't cover cistron ids) — the bug used exactly this
    monkeypatch.setattr(differential, "_reverse_gene_map", lambda: {"6PFK-1-MONOMER[c]": "wrong"})

    monkeypatch.setattr(reader, "gene_lfc", lambda t, r, kind: {"kind": kind,
        "lfc": {"EG10016_RNA[c]": {"log2fc": 1.2}, "G6543_RNA[c]": {"log2fc": -0.4}}})
    monkeypatch.setattr(differential, "_cistron_symbol_map", lambda: {"EG10016_RNA[c]": "aceB"})
    out = differential.all_gene_lfc("d", "ref", kind="mrna")
    assert out["lfc"]["EG10016_RNA[c]"]["symbol"] == "aceB"   # mRNA annotated from the CISTRON map
    assert out["lfc"]["G6543_RNA[c]"]["symbol"] is None       # gracefully None when the cistron map misses it

    monkeypatch.setattr(reader, "gene_lfc", lambda t, r, kind: {"kind": kind,
        "lfc": {"6PFK-1-MONOMER[c]": {"log2fc": 0.5}}})
    out = differential.all_gene_lfc("d", "ref", kind="protein")
    assert out["lfc"]["6PFK-1-MONOMER[c]"]["symbol"] == "wrong"   # protein uses the monomer reverse map


def test_sim_lfc_uses_full_distribution_and_joins_bnumbers(monkeypatch):
    """SCI-2c: sim_lfc reads the ALL-GENE reader (so a NON-significant gene is still included — the fix for the
    range-restricted concordance) and keys every gene by b-number for the DESeq2 join; unmapped ids pass through."""
    from cellarium import differential

    monkeypatch.setattr(differential, "all_gene_lfc", lambda design, reference, kind="mrna": {"kind": "mrna", "lfc": {
        "EG_pfkA": {"log2fc": 2.1, "symbol": "pfkA"},
        "EG_flat": {"log2fc": 0.02, "symbol": "fbaA"},        # a NON-significant gene — must still be present
        "EG_nosym": {"log2fc": -1.0, "symbol": None}}})       # no symbol -> keyed by its raw id (graceful)
    bmap = sci2._bnumber_map()
    lfc = sci2.sim_lfc("gene_knockout/KO:acrB")
    assert lfc[bmap["pfkA"]] == 2.1 and lfc[bmap["fbaA"]] == 0.02   # full distribution, joined by b-number
    assert lfc["EG_nosym"] == -1.0 and len(lfc) == 3

    monkeypatch.setattr(differential, "all_gene_lfc", lambda *a, **k: {"error": "no local runs"})
    assert sci2.sim_lfc("x") == {}                            # no data / error -> empty, not a crash


def test_rnaseq_concordance_fails_loud_on_namespace_mismatch(monkeypatch):
    """The silent trap the review flagged: if sim ids never intersect the b-number reference (both sides sizable,
    zero joined), that's a NAMESPACE mismatch, not data scarcity — rnaseq_concordance must say so, not return a
    bare INDETERMINATE that hides a broken annotation."""
    monkeypatch.setattr(sci2, "available", lambda: (True, "ok"))
    monkeypatch.setattr(sci2, "build_reference", lambda contrast: {
        "contrast": "x", "provenance": {},
        "reference_lfc": {f"b{i:04d}": {"log2FC": 0.5, "padj": 0.01} for i in range(50)}})
    # sim ids in the WRONG namespace (raw cistron ids, not b-numbers) -> empty join despite 50 genes each side
    monkeypatch.setattr(sci2, "sim_lfc", lambda design, reference: {f"EG{i:05d}_RNA[c]": 0.5 for i in range(50)})
    out = sci2.rnaseq_concordance("d", {"cond_B": "x"})
    assert "error" in out and "namespace" in out["error"].lower()
    assert out["join_qc"]["n_joined"] == 0 and out["join_qc"]["n_sim"] == 50   # the diagnostic carries the counts


# ---- real PRECISE-1K + pydeseq2 (opt-in): needs the `rnaseq` extra + the fetched data ----

def _rnaseq_ready():
    try:
        import pydeseq2  # noqa: F401
    except Exception:
        return False
    return sci2.COUNTS.exists() and sci2.METADATA.exists()


realrnaseq = pytest.mark.skipif(not _rnaseq_ready(), reason="rnaseq extra (pydeseq2) + PRECISE-1K data not present")


@realrnaseq
def test_build_reference_on_a_real_contrast():
    """The DATA side end-to-end: a real DESeq2 run on PRECISE-1K (wt_ph5 vs wt_glc, MG1655) yields unshrunk per-gene
    log2FC keyed by b-number, with real DE at padj<0.05."""
    ref = sci2.build_reference({"column": "condition", "cond_A": "wt_glc", "cond_B": "wt_ph5"})
    assert "error" not in ref and ref["n_genes"] > 3000
    assert ref["n_replicates"]["A"] >= 4 and ref["n_replicates"]["B"] >= 4
    rl = ref["reference_lfc"]
    assert all(k.startswith("b") for k in list(rl)[:20])       # b-number keys
    assert any(v["padj"] is not None and v["padj"] < 0.05 and abs(v["log2FC"]) > 2 for v in rl.values())
    assert ref["provenance"]["counts_sha256"] and ref["provenance"]["ref_strain"] == "MG1655"
