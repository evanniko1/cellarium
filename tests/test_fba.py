"""SCI-1 — the independent FBA cross-check. Pure logic (diagnosis, concordance/MCC) and the graceful-degradation
gate run everywhere; the real cobrapy/iML1515 path runs only where the optional `fba` extra + model are present."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cellarium import fba  # noqa: E402


def test_diagnose_names_each_disagreement_direction():
    assert fba.diagnose(True, True)["class"] == "consistent_lethal"
    assert fba.diagnose(False, False)["class"] == "consistent_viable"
    assert fba.diagnose(True, False)["class"] == "fba_false_essential"    # FBA over-calls (cofactor/medium)
    assert fba.diagnose(False, True)["class"] == "fba_false_viable"       # FBA reroutes (OR-isozyme)
    assert fba.diagnose(True, None)["class"] == "no_reference"


def test_concordance_mcc_and_confusion():
    perfect = fba.concordance([(True, True), (False, False), (False, False)])
    assert perfect["mcc"] == 1.0 and perfect["confusion"]["fp_fba_false_essential"] == 0
    mixed = fba.concordance([(True, True), (False, False), (True, False), (False, True)])
    assert mixed["mcc"] == 0.0                                            # one of each cell -> MCC 0
    assert mixed["confusion"] == {"tp_both_essential": 1, "tn_both_viable": 1,
                                  "fp_fba_false_essential": 1, "fn_fba_false_viable": 1}
    assert "accuracy_do_not_use" in mixed                                # accuracy is reported but flagged


def test_gates_cleanly_without_cobra(monkeypatch):
    monkeypatch.setattr(fba, "_have_cobra", lambda: False)
    ok, msg = fba.available()
    assert ok is False and "pip install" in msg
    assert "error" in fba.fba_growth() and "error" in fba.fba_essentiality_panel()


# ---- real FBA (opt-in): needs `pip install -e '.[fba]'` + the iML1515 model on disk ----

def _fba_ready():
    try:
        import cobra  # noqa: F401
    except Exception:
        return False
    return fba.MODEL_PATH.exists()


realfba = pytest.mark.skipif(not _fba_ready(), reason="fba extra (cobra) + iML1515 model not present")


@realfba
def test_iml1515_growth_and_knockout():
    fba._reset_model()
    g = fba.fba_growth()
    assert g["status"] == "optimal" and 0.6 < g["growth_rate_per_h"] < 1.0 and g["sanity_ok"]
    ko = fba.fba_gene_knockout(["fbaA", "pfkA", "notagene"])
    by = {r["gene"]: r for r in ko["results"]}
    # fbaA is Keio-essential but FBA reroutes through its isozyme -> the classic false-viable disagreement
    assert by["fbaA"]["keio_essential"] is True and by["fbaA"]["diagnosis"] == "fba_false_viable"
    assert by["pfkA"]["diagnosis"] == "consistent_viable"                 # pfkB isozyme -> viable both ways
    assert ko["unknown_genes"] == ["notagene"]


@realfba
def test_essentiality_panel_reports_mcc_and_disagreements():
    fba._reset_model()
    p = fba.fba_essentiality_panel(max_genes=40)
    c = p["concordance_fba_vs_keio"]
    assert c["n"] > 0 and -1.0 <= c["mcc"] <= 1.0
    assert p["provenance"]["model"] == "iML1515" and p["provenance"]["model_sha256"]
    assert all(r["diagnosis"] in ("consistent_lethal", "consistent_viable",
                                  "fba_false_essential", "fba_false_viable", "no_reference") for r in p["disagreements"])
