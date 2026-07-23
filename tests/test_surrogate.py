"""SCI-5: the ML viability-triage surrogate. Tests use a SYNTHETIC, separable labeled set (injected via a monkeypatched
build_dataset) so they're deterministic and don't need the live corpus or a specific sklearn build — they lock the
contract: honest baseline reporting, LOO CV, graceful degradation (no sklearn / too few labels), and tool wiring."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cellarium import surrogate  # noqa: E402

# The surrogate's ONLY hard dep. The model-fit tests skip without it; the wiring + graceful-degradation +
# featurization tests do NOT need it and always run (they guard the contract even where sklearn is absent).
_HAS_SKLEARN = surrogate._sklearn() is not None
needs_sklearn = pytest.mark.skipif(not _HAS_SKLEARN, reason="scikit-learn not installed (surrogate extra)")


def _separable_dataset(n_each=12):
    """A cleanly separable synthetic set: essential+machinery -> non-viable(0), else viable(1). The model should
    recover this near-perfectly, so it MUST beat the majority baseline."""
    X, y, genes, verdicts = [], [], [], []
    for i in range(n_each):
        X.append([0, 1, 0, 1, 0, 0, 1.0]); y.append(1); genes.append(f"viab{i}"); verdicts.append("viable")
    for i in range(n_each // 2):
        X.append([1, 0, 0, 0, 0, 1, 0.5]); y.append(0); genes.append(f"dead{i}"); verdicts.append("inviable")
    n = len(y); npos = sum(y)
    from collections import Counter
    return {"X": X, "y": y, "genes": genes, "verdicts": verdicts, "n": n,
            "class_balance": dict(Counter(verdicts)), "n_viable": npos, "n_non_viable": n - npos,
            "majority_baseline": round(max(npos, n - npos) / n, 3), "features": surrogate.FEATURES, "note": "synthetic"}


def test_gene_features_shape_and_binary_encoding(monkeypatch):
    from cellarium import scope
    monkeypatch.setattr(scope, "classify_gene", lambda g: {
        "known": True, "role": "metabolic_enzyme", "is_machinery": False, "is_sole_catalyst": True,
        "is_kinetically_constraining": False, "essential_reference": True, "n_tu": 1})
    f = surrogate.gene_features("fabI")
    assert set(f) == set(surrogate.FEATURES)
    assert f["is_metabolic"] == 1 and f["is_machinery"] == 0 and f["essential_ref"] == 1
    # essential_reference None (not in benchmark) must encode 0, not crash
    monkeypatch.setattr(scope, "classify_gene", lambda g: {"known": True, "role": "no_modeled_function",
                                                           "essential_reference": None, "n_tu": 0})
    assert surrogate.gene_features("ymgD")["essential_ref"] == 0


def test_gene_features_none_for_unknown(monkeypatch):
    from cellarium import scope
    monkeypatch.setattr(scope, "classify_gene", lambda g: {"known": False})
    assert surrogate.gene_features("zzz") is None


@needs_sklearn
def test_train_beats_baseline_on_separable_data():
    out = surrogate.train(_separable_dataset(), n_permutations=0)   # skip the perm test here (speed) — see below
    assert out["trained"] is True and out["cv"] == "leave-one-out"
    assert out["loo_accuracy"] >= out["majority_baseline"]     # a separable set must not lose to the baseline
    assert out["beats_baseline_point_estimate"] is True and out["mcc"] > 0.5
    assert out["feature_importance"] and "confusion_matrix" in out
    assert len(out["accuracy_ci95"]) == 2 and out["accuracy_ci95"][0] <= out["loo_accuracy"] <= out["accuracy_ci95"][1]


@needs_sklearn
def test_significance_flag_permutation_test():
    """DD-SCI-5b: the label-permutation test machine-checks significance — a genuinely separable set is significant vs
    chance; a label-shuffled (signal-free) set is NOT. This is the honesty flag that stays False on the parked n~20."""
    import random
    sig = surrogate.train(_separable_dataset(n_each=14), n_permutations=100)["significance"]
    assert sig["tested"] is True and sig["mcc_p_value"] is not None
    assert sig["significant_vs_chance"] is True                # real feature->label link -> significant

    ds = _separable_dataset(n_each=14)
    random.Random(0).shuffle(ds["y"])                          # break the link: labels now random wrt features
    noise = surrogate.train(ds, n_permutations=100)["significance"]
    assert noise["significant_vs_chance"] is False             # no signal -> not distinguishable from chance


@needs_sklearn
def test_train_reports_baseline_and_abstains_when_underpowered():
    tiny = _separable_dataset(n_each=2)                        # n=3 < MIN_LABELS -> descriptive-only
    out = surrogate.train(tiny)
    assert out["trained"] is False and out["n"] < surrogate.MIN_LABELS
    assert out["majority_baseline"] is not None                # still reports the baseline honestly


@needs_sklearn
def test_predict_returns_probability_and_neighbors(monkeypatch):
    from cellarium import scope
    monkeypatch.setattr(scope, "classify_gene", lambda g: {
        "known": True, "role": "metabolic_enzyme", "is_machinery": False, "is_sole_catalyst": True,
        "is_kinetically_constraining": False, "essential_reference": False, "n_tu": 2})
    out = surrogate.predict("newGene", _separable_dataset())
    assert out["known"] is True and 0.0 <= out["viability_probability"] <= 1.0
    assert out["predicted"] in ("viable", "non_viable")
    assert len(out["nearest_corpus_kos"]) == 3 and "caveat" in out


def test_predict_unknown_gene_is_clean(monkeypatch):
    from cellarium import scope
    monkeypatch.setattr(scope, "classify_gene", lambda g: {"known": False})
    out = surrogate.predict("zzz", _separable_dataset())
    assert out["known"] is False


def test_graceful_without_sklearn(monkeypatch):
    monkeypatch.setattr(surrogate, "_sklearn", lambda: None)
    t = surrogate.train(_separable_dataset())
    assert "error" in t and "setup" in t and "scikit-learn" in t["setup"]
    p = surrogate.predict("x", _separable_dataset())
    # predict featurizes first; with a real gene it still reports the sklearn-missing setup
    assert p.get("error") or p.get("known") is False


def test_surrogate_is_wired_as_an_agent_tool():
    from cellarium import tools
    assert "viability_surrogate" in tools._DISPATCH
    assert any(t["name"] == "viability_surrogate" for t in tools.TOOLS)
