"""SCI-5: an ML surrogate for single-gene-KO viability — the "Well for the Cell" compute-reduction artifact.

Running the whole-cell sim for a candidate KO costs ~hours; this surrogate predicts the sim's own viability verdict
from CHEAP a-priori gene properties (the same scope features the deterministic tools use — machinery/metabolic role,
sole-catalyst / kinetic-constraint flags, the Baba/Joyce essentiality benchmark, TU count), so a batch of candidate
KOs can be TRIAGED before committing sim time to them.

Rigor first (the whole point of this project): the labeled corpus is small (~20 single-KO designs) and imbalanced
toward 'viable', so this is a PROOF-OF-CONCEPT TRIAGE PRIOR, not a production predictor — and it says so. Every
report leads with the majority-class BASELINE, uses leave-one-out CV (the honest estimator at this n), reports MCC
(not just accuracy, which the imbalance inflates), and surfaces which features carry the signal. It degrades
gracefully: no sklearn -> setup instructions; too few labels -> descriptive-only. As the corpus grows, the surrogate
sharpens and the compute saving compounds — that is the artifact.

Prediction target is BINARY viable(1) vs non-viable(0) — the triage question ("is this KO worth simulating / will it
survive?"); the 3-class verdict (viable/impaired/inviable) is reported descriptively. The verdict predicted is the
MODEL's behavior, NOT ground truth — an essential gene the whole-cell FBA under-predicts as viable stays viable here
too (same limitation as the sim), so for essential-gene candidates defer to the Baba/Joyce benchmark, as everywhere.
"""

from __future__ import annotations

import math

# a-priori features only — everything knowable BEFORE the sim (no division_rate/gens: those are the label's cousins).
FEATURES = ["is_machinery", "is_metabolic", "is_tf", "is_sole_catalyst",
            "is_kinetically_constraining", "essential_ref", "log_n_tu"]
MIN_LABELS = 8            # below this the fit is reported descriptive-only (LOO CV is meaningless at tiny n)


def gene_features(symbol: str) -> dict | None:
    """The a-priori feature vector for a gene, straight from scope.classify_gene (no sim). None if unknown."""
    from . import scope
    c = scope.classify_gene(symbol)
    if not c.get("known"):
        return None
    role = c.get("role")
    return {
        "is_machinery": 1 if c.get("is_machinery") else 0,
        "is_metabolic": 1 if role == "metabolic_enzyme" else 0,
        "is_tf": 1 if role == "transcription_factor" else 0,
        "is_sole_catalyst": 1 if c.get("is_sole_catalyst") else 0,
        "is_kinetically_constraining": 1 if c.get("is_kinetically_constraining") else 0,
        # essential_reference is True/False/None(=not in the benchmark) -> only a confirmed-essential is a 1
        "essential_ref": 1 if c.get("essential_reference") is True else 0,
        "log_n_tu": round(math.log1p(float(c.get("n_tu") or 0)), 4),
    }


def build_dataset(perturbation: str = "gene_knockout") -> dict:
    """Join every single-gene-KO design's viability verdict (label) to its a-priori gene features. Returns
    {X, y, genes, verdicts, n, class_balance, majority_baseline, note}. y is binary viable(1)/non-viable(0)."""
    from . import store
    out = store.viability(perturbation, None)
    if out.get("error"):
        return {"error": out["error"], "n": 0}
    X, y, genes, verdicts = [], [], [], []
    for d in out.get("designs", []):
        verdict = d.get("verdict")
        if verdict not in ("viable", "impaired", "inviable"):   # drop 'unknown'/crashed-only rows — no clean label
            continue
        gene = str(d.get("condition", "")).replace("KO:", "")
        feats = gene_features(gene)
        if feats is None:
            continue
        X.append([feats[k] for k in FEATURES])
        y.append(1 if verdict == "viable" else 0)
        genes.append(gene)
        verdicts.append(verdict)
    n = len(y)
    n_pos = sum(y)
    from collections import Counter
    balance = dict(Counter(verdicts))
    baseline = round(max(n_pos, n - n_pos) / n, 3) if n else None   # always-predict-majority accuracy
    return {"X": X, "y": y, "genes": genes, "verdicts": verdicts, "n": n,
            "class_balance": balance, "n_viable": n_pos, "n_non_viable": n - n_pos,
            "majority_baseline": baseline, "features": FEATURES,
            "note": ("Labeled single-KO designs joined to a-priori gene features. y = viable(1) vs "
                     "impaired-or-inviable(0). 'majority_baseline' is the accuracy of always guessing the majority "
                     "class — the surrogate must beat it to be worth anything.")}


def _sklearn():
    """Optional dependency, mirroring the fba/rnaseq tools — return the needed sklearn pieces or None."""
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import accuracy_score, confusion_matrix, matthews_corrcoef
        from sklearn.model_selection import LeaveOneOut
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        return {"LogisticRegression": LogisticRegression, "LeaveOneOut": LeaveOneOut,
                "make_pipeline": make_pipeline, "StandardScaler": StandardScaler,
                "matthews_corrcoef": matthews_corrcoef, "confusion_matrix": confusion_matrix,
                "accuracy_score": accuracy_score}
    except ImportError:
        return None


def _model(sk):
    # standardize + L2 logistic, class-balanced (the corpus leans 'viable'); interpretable coefficients = importance.
    return sk["make_pipeline"](sk["StandardScaler"](),
                               sk["LogisticRegression"](class_weight="balanced", max_iter=1000))


_SETUP = ("ML surrogate needs scikit-learn. Install the extra: `pip install scikit-learn` (or the project's "
          "`.[surrogate]`), then retry. The surrogate is optional — the deterministic viability/mechanistic_scope "
          "tools answer the same question per-gene without it.")


def train(dataset: dict | None = None) -> dict:
    """Fit + leave-one-out cross-validate the surrogate; report accuracy vs the majority baseline, MCC, the confusion
    matrix, and per-feature importance (standardized logistic coefficients). Honest about n and imbalance."""
    sk = _sklearn()
    if sk is None:
        return {"error": "scikit-learn not installed", "setup": _SETUP}
    ds = dataset or build_dataset()
    if ds.get("error"):
        return {"error": ds["error"]}
    n, y = ds["n"], ds["y"]
    if n < MIN_LABELS or len(set(y)) < 2:
        return {"trained": False, "n": n, "class_balance": ds.get("class_balance"),
                "majority_baseline": ds.get("majority_baseline"),
                "note": (f"Only {n} labeled designs (need >={MIN_LABELS} with both classes) — too few to cross-"
                         "validate. Reported descriptive-only; the surrogate abstains until the corpus grows.")}
    import numpy as np
    X = np.array(ds["X"], dtype=float)
    y_arr = np.array(y, dtype=int)
    model = _model(sk)

    # leave-one-out CV predictions — the honest estimator at this n (no held-out set to spare)
    loo = sk["LeaveOneOut"]()
    preds = np.empty(n, dtype=int)
    for tr, te in loo.split(X):
        if len(set(y_arr[tr])) < 2:            # degenerate fold (all one class) -> fall back to majority guess
            preds[te] = int(round(y_arr[tr].mean()))
            continue
        preds[te] = _model(sk).fit(X[tr], y_arr[tr]).predict(X[te])
    acc = round(float(sk["accuracy_score"](y_arr, preds)), 3)
    mcc = round(float(sk["matthews_corrcoef"](y_arr, preds)), 3)
    cm = sk["confusion_matrix"](y_arr, preds, labels=[0, 1]).tolist()

    model.fit(X, y_arr)                          # full-data fit for the reported coefficients
    coefs = model.named_steps["logisticregression"].coef_[0]
    importance = sorted(({"feature": f, "weight": round(float(w), 3)} for f, w in zip(ds["features"], coefs)),
                        key=lambda d: -abs(d["weight"]))
    baseline = ds["majority_baseline"]
    beats = acc > baseline
    return {
        "trained": True, "n": n, "class_balance": ds.get("class_balance"),
        "cv": "leave-one-out",
        "loo_accuracy": acc, "majority_baseline": baseline, "beats_baseline": beats,
        "mcc": mcc,                              # -1..1; 0 = no better than chance given the imbalance
        "confusion_matrix": {"labels": ["non_viable(0)", "viable(1)"], "rows_true_cols_pred": cm},
        "feature_importance": importance,
        "note": ("Leave-one-out CV. Read MCC, NOT accuracy — the class imbalance inflates accuracy (the baseline is "
                 f"already {baseline}). A proof-of-concept TRIAGE prior at this n, not a validated predictor; the "
                 "predicted verdict is the sim's behavior, not ground truth (defer to the Baba/Joyce benchmark for "
                 "essential-gene candidates). Positive weight => pushes toward 'viable'."),
    }


def predict(gene: str, dataset: dict | None = None) -> dict:
    """Predict a candidate gene's viability (probability), trained on the whole labeled corpus, with the nearest
    corpus KOs that ground it + the honest caveats. Use to TRIAGE before spending sim time on the KO."""
    feats = gene_features(gene)
    if feats is None:
        return {"gene": gene, "known": False, "note": "gene not in the scope map — cannot featurize."}
    sk = _sklearn()
    if sk is None:
        return {"gene": gene, "error": "scikit-learn not installed", "setup": _SETUP,
                "features": feats}
    ds = dataset or build_dataset()
    if ds.get("error") or ds["n"] < MIN_LABELS or len(set(ds["y"])) < 2:
        return {"gene": gene, "features": feats, "trained": False,
                "note": f"too few labeled designs ({ds.get('n')}) to train — deterministic viability/scope only."}
    import numpy as np
    X = np.array(ds["X"], dtype=float)
    y = np.array(ds["y"], dtype=int)
    model = _model(sk).fit(X, y)
    xv = np.array([[feats[k] for k in ds["features"]]], dtype=float)
    proba = float(model.predict_proba(xv)[0][1])
    pred = int(proba >= 0.5)
    # nearest corpus KOs by Hamming/Euclidean on the a-priori features — grounds the prediction in real runs
    d2 = ((X - xv) ** 2).sum(axis=1)
    order = np.argsort(d2)[:3]
    neighbors = [{"gene": ds["genes"][i], "verdict": ds["verdicts"][i], "distance": round(float(d2[i]) ** 0.5, 3)}
                 for i in order]
    return {
        "gene": gene, "known": True, "features": feats,
        "predicted": "viable" if pred else "non_viable",
        "viability_probability": round(proba, 3),
        "confidence": ("high" if abs(proba - 0.5) > 0.35 else "low — near the decision boundary"),
        "nearest_corpus_kos": neighbors,
        "trained_on": {"n": ds["n"], "class_balance": ds.get("class_balance")},
        "caveat": ("A TRIAGE prior from a small corpus — NOT a verdict. It predicts the whole-cell sim's OWN behavior "
                   "(which under-predicts essentiality for metabolic essentials), so for an essential-gene candidate "
                   "the Baba/Joyce benchmark (mechanistic_scope/metabolic_essentiality) overrides this. Run the sim to "
                   "confirm a triage that matters."),
    }


def surrogate_report(gene: str | None = None) -> dict:
    """Agent entry: the surrogate's cross-validated quality (always), plus a prediction for `gene` when given."""
    ds = build_dataset()
    report = {"dataset": {k: ds.get(k) for k in ("n", "class_balance", "majority_baseline", "n_viable",
                                                 "n_non_viable")},
              "model": train(ds)}
    if gene:
        report["prediction"] = predict(gene, ds)
    return report
