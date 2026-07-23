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

DD-SCI-5b — TARGET DECISION (recorded 2026-07-21): the target STAYS the sim's verdict; the surrogate is an EMULATOR of
the simulator (compute reduction), NOT a predictor of biology. Two alternatives were weighed and rejected on their
merits: (B) predicting the Baba/Joyce benchmark directly is redundant and weaker — FBA (`fba_gene_knockout`) predicts
metabolic essentiality with the whole stoichiometry, and making the benchmark the label forfeits `essential_ref` as
the dominant feature; (C) predicting the sim-vs-benchmark DISAGREEMENT is a category error — `model_UNDER_predicts` is
a near-deterministic function of (essential_ref, mechanism-class) that `scope.classify_gene` / `model_validation`
already compute in closed form, so there is nothing stochastic to learn (and its positive class is n~3-5). The honest
object is A + the benchmark as a feature + the override caveat. PARKED until the corpus is large enough: at n~20 the
fit is not statistically distinguishable from the majority baseline (see `train`'s `significance` field) — the
plumbing is ready so the artifact can be resumed once the labels justify it, but pursuing it now is premature.
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


def _wilson_ci(k: int, n: int, z: float = 1.96) -> list:
    """Closed-form Wilson 95% CI for a proportion k/n (no scipy) — honest at the small n where a normal approx isn't."""
    if n == 0:
        return [0.0, 1.0]
    p = k / n
    d = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = (z / d) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return [round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3)]


def _loo_preds(X, y_arr, sk):
    """Leave-one-out predictions; a degenerate single-class fold falls back to the majority guess."""
    import numpy as np
    preds = np.empty(len(y_arr), dtype=int)
    for tr, te in sk["LeaveOneOut"]().split(X):
        if len(set(y_arr[tr])) < 2:
            preds[te] = int(round(y_arr[tr].mean()))
        else:
            preds[te] = _model(sk).fit(X[tr], y_arr[tr]).predict(X[te])
    return preds


def train(dataset: dict | None = None, *, n_permutations: int = 200) -> dict:
    """Fit + leave-one-out cross-validate the surrogate; report accuracy vs the majority baseline (with a Wilson CI),
    MCC, the confusion matrix, per-feature importance, and a SIGNIFICANCE flag — a label-permutation test (DD-SCI-5b)
    that machine-checks whether the fit is distinguishable from chance. At n~20 it should say NO; that's the honest
    parked state. `n_permutations=0` skips the (reproducible, fixed-seed) permutation test."""
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

    preds = _loo_preds(X, y_arr, sk)             # leave-one-out — the honest estimator at this n (no held-out to spare)
    acc = round(float(sk["accuracy_score"](y_arr, preds)), 3)
    mcc = round(float(sk["matthews_corrcoef"](y_arr, preds)), 3)
    cm = sk["confusion_matrix"](y_arr, preds, labels=[0, 1]).tolist()
    ci = _wilson_ci(int((preds == y_arr).sum()), n)

    # SIGNIFICANCE (DD-SCI-5b): a label-permutation test — is the LOO MCC beyond what shuffled labels (no real feature
    # -> outcome link) produce? The rigorous small-n significance measure; reproducible (fixed rng). At n~20 it should
    # be NON-significant — the machine-checked statement that the surrogate is a parked proof-of-concept, not yet a
    # validated predictor. The baseline stays inside the accuracy CI here for the same reason.
    significance = {"tested": False, "note": "pass n_permutations>0 to run the permutation test."}
    if n_permutations > 0:
        rng = np.random.default_rng(0)
        null = []
        for _ in range(int(n_permutations)):
            yp = rng.permutation(y_arr)
            if len(set(yp)) < 2:
                continue
            null.append(float(sk["matthews_corrcoef"](yp, _loo_preds(X, yp, sk))))
        perm_p = round((sum(1 for m in null if m >= mcc) + 1) / (len(null) + 1), 4) if null else None
        significance = {"tested": True, "test": "label-permutation (LOO MCC)", "n_permutations": len(null),
                        "mcc_p_value": perm_p,
                        "significant_vs_chance": bool(perm_p is not None and perm_p < 0.05)}

    model = _model(sk).fit(X, y_arr)             # full-data fit for the reported coefficients
    coefs = model.named_steps["logisticregression"].coef_[0]
    importance = sorted(({"feature": f, "weight": round(float(w), 3)} for f, w in zip(ds["features"], coefs)),
                        key=lambda d: -abs(d["weight"]))
    baseline = ds["majority_baseline"]
    return {
        "trained": True, "n": n, "class_balance": ds.get("class_balance"),
        "cv": "leave-one-out",
        "loo_accuracy": acc, "accuracy_ci95": ci, "majority_baseline": baseline,
        "beats_baseline_point_estimate": acc > baseline,   # POINT estimate only — read `significance`, not this
        "baseline_inside_ci": bool(ci[0] <= baseline <= ci[1]),   # True => not distinguishable from majority-guessing
        "mcc": mcc,                              # -1..1; 0 = no better than chance given the imbalance
        "significance": significance,
        "confusion_matrix": {"labels": ["non_viable(0)", "viable(1)"], "rows_true_cols_pred": cm},
        "feature_importance": importance,
        "note": ("Leave-one-out CV. Read `significance` + MCC, NOT the raw accuracy — the imbalance inflates accuracy "
                 f"(baseline already {baseline}, and it sits inside the accuracy CI at this n). A proof-of-concept "
                 "EMULATOR of the sim (DD-SCI-5b), not a validated predictor; the predicted verdict is the sim's "
                 "behavior, not ground truth (defer to the Baba/Joyce benchmark for essential-gene candidates). "
                 "Positive weight => pushes toward 'viable'."),
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
