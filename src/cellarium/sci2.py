"""SCI-2 — the simulated-transcriptome vs real E. coli RNA-seq cross-check (PRECISE-1K + pydeseq2).

A validation / model-limits oracle: *where does the sim's mRNA disagree with measured RNA-seq for a MATCHED
condition contrast?* Like the SCI-1 FBA cross-check, real RNA-seq is a CROSS-CHECK, never ground truth — a
disagreement is a grounded model-limit finding, not a bug (RNA-seq carries its own normalization, batch, strain,
and short-gene artifacts the model does not reproduce).

The unit is **cross-condition log2 fold-change concordance** (sim log2FC vs DESeq2 log2FC), because the sim emits
absolute molecules/cell and RNA-seq emits a compositional fraction — the two are only comparable as a RATIO.

The ASYMMETRY (the crux): the DATA side has real biological replicates -> pydeseq2 (NB-GLM, Wald, UNSHRUNK LFC).
The SIM side is deterministic-with-seeds -> seeds are NOT replicates; the sim LFC is the seed-mean log-ratio
(reusing differential's machinery), with across-seed spread only as an uncertainty WEIGHT, never a p-value.

OPTIONAL by design: pydeseq2 is not core (`pip install -e '.[rnaseq]'`); PRECISE-1K (~60 MB) is fetched on demand +
pinned by SHA. Every entry point degrades to a clear message when the dep/data is absent — the core never breaks.
Grounded in the wf_eeea2f6c SOTA brief; mirrors fba.py (available()/provenance() gates) + differential.py.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import urllib.request
from pathlib import Path

import numpy as np

DATA_DIR = Path(os.environ.get("CELLARIUM_PRECISE1K_DIR") or "data/precise1k")
COUNTS = DATA_DIR / "counts.csv"                       # raw read counts (genes x samples), b-number index
METADATA = DATA_DIR / "metadata.csv"                   # sample -> condition/project columns
BMAP_PATH = Path("data/cache/bnumber_map.json")        # gene symbol -> b-number (EcoCyc-derived; committed)
PRECISE1K_URLS = {
    "counts.csv": "https://raw.githubusercontent.com/SBRG/precise1k/main/data/precise1k/counts.csv",
    "metadata.csv": "https://raw.githubusercontent.com/SBRG/precise1k/main/data/precise1k/metadata.csv"}
ZENODO_DOI = "10.5281/zenodo.8284223"                  # PRECISE-1K citable snapshot (pin this)
REF_CONDITION = "wt_glc"                               # PRECISE-1K WT M9-glucose aerobic = the model's basal control arm
REF_STRAIN = "MG1655"                                  # strain fidelity: compare only same-strain samples (the brief)
MIN_COUNT = 10.0                                        # independent-filter floor before correlating (both sides)
PADJ_SIG = 0.1                                          # DESeq2 padj threshold for "confidently resolved" genes
DEG_SIG = 1.0                                           # |log2FC| a DE call must clear


# --- availability + provenance -----------------------------------------------------------------------------

def _have_pydeseq2() -> bool:
    try:
        import pydeseq2  # noqa: F401
        return True
    except Exception:
        return False


def available() -> tuple[bool, str]:
    if not _have_pydeseq2():
        return False, "SCI-2 needs pydeseq2 — `pip install -e '.[rnaseq]'` (optional; keeps the core scipy-free)."
    if not (COUNTS.exists() and METADATA.exists()):
        return False, (f"PRECISE-1K not found in {DATA_DIR}. Fetch the raw-count matrix + metadata (Zenodo "
                       f"{ZENODO_DOI} / github SBRG/precise1k) into that dir, or set CELLARIUM_PRECISE1K_DIR.")
    return True, ""


def fetch_precise1k() -> dict:
    """One-time download of the PRECISE-1K raw counts (~17 MB) + metadata into DATA_DIR (GitHub-mirrored Zenodo
    snapshot). Explicit — not auto-run inside a tool."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for name, url in PRECISE1K_URLS.items():
        urllib.request.urlretrieve(url, DATA_DIR / name)   # noqa: S310 — fixed academic host
    return {"dir": str(DATA_DIR), "counts_sha256": _sha256(COUNTS), "metadata_bytes": METADATA.stat().st_size}


def _bnumber_map() -> dict:
    """{gene_symbol: b-number} for the sim-side join (EcoCyc/wcEcoli genes.tsv-derived; committed to data/cache)."""
    return json.loads(BMAP_PATH.read_text(encoding="utf-8")) if BMAP_PATH.exists() else {}


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()[:16]


def provenance(contrast: dict | None = None) -> dict:
    ver = None
    try:
        import pydeseq2
        ver = pydeseq2.__version__
    except Exception:
        pass
    return {"reference": "PRECISE-1K", "zenodo_doi": ZENODO_DOI, "counts_sha256": _sha256(COUNTS),
            "pydeseq2_version": ver, "ref_condition": REF_CONDITION, "ref_strain": REF_STRAIN,
            "n_bnumber_map": len(_bnumber_map()), "contrast": contrast,
            "lfc": "UNSHRUNK (MLE) — matched to the unshrunk seed-mean sim LFC",
            "caveat": ("RNA-seq is a cross-check, NOT ground truth. The sim = absolute molecules/cell, RNA-seq = "
                       "compositional fraction; compared only as log2FC of a matched contrast. Seeds are not "
                       "biological replicates.")}


# --- the pure comparison engine (numpy-only; testable without pydeseq2/data) -------------------------------

def _rank(a: np.ndarray) -> np.ndarray:
    """Average ranks (ties shared) — for Spearman via Pearson-on-ranks, no scipy."""
    order = np.argsort(a, kind="mergesort")
    r = np.empty(len(a), dtype=float)
    r[order] = np.arange(len(a), dtype=float)
    # average tied ranks
    _, inv, counts = np.unique(a, return_inverse=True, return_counts=True)
    csum = np.cumsum(counts)
    starts = csum - counts
    avg = (starts + csum - 1) / 2.0
    return avg[inv]


def _pearson(x: np.ndarray, y: np.ndarray) -> float | None:
    if len(x) < 3 or np.std(x) == 0 or np.std(y) == 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def _spearman(x: np.ndarray, y: np.ndarray) -> float | None:
    return _pearson(_rank(x), _rank(y))


def _deming(x: np.ndarray, y: np.ndarray, ratio: float = 1.0) -> tuple[float, float] | None:
    """Deming (total least squares) slope + intercept — both axes carry error, so OLS would attenuate the slope.
    `ratio` = var(y-error)/var(x-error); 1.0 is the symmetric default."""
    if len(x) < 3 or np.std(x) == 0:
        return None
    mx, my = float(np.mean(x)), float(np.mean(y))
    sxx = float(np.mean((x - mx) ** 2))
    syy = float(np.mean((y - my) ** 2))
    sxy = float(np.mean((x - mx) * (y - my)))
    if sxy == 0:
        return None
    d = syy - ratio * sxx
    slope = (d + math.sqrt(d * d + 4 * ratio * sxy * sxy)) / (2 * sxy)
    return slope, my - slope * mx


def concordance(sim_lfc: dict, ref_lfc: dict, *, min_count_genes: set | None = None,
                ref_sig: set | None = None) -> dict:
    """The scientific core (pure): join two log2FC vectors on gene id and score their agreement. `sim_lfc`/`ref_lfc`
    map gene-id -> log2FC. `min_count_genes` (optional) restricts to genes that clear the count floor on BOTH sides
    (independent filter). `ref_sig` (optional) = the genes DESeq2 confidently resolved (padj<PADJ_SIG & |LFC|>=1) —
    sign-concordance is scored on those. Returns metrics + top-divergent genes + a MODEL-LIMIT verdict."""
    keep = set(sim_lfc) & set(ref_lfc)
    if min_count_genes is not None:
        keep &= min_count_genes
    join_qc = {"n_sim": len(sim_lfc), "n_ref": len(ref_lfc), "n_joined": len(keep),
               "n_sim_only": len(set(sim_lfc) - set(ref_lfc)), "n_ref_only": len(set(ref_lfc) - set(sim_lfc))}
    genes = sorted(keep)
    if len(genes) < 10:
        return {"verdict": "INDETERMINATE", "reason": "too few jointly-measured genes to correlate", "join_qc": join_qc}
    s = np.array([sim_lfc[g] for g in genes], dtype=float)
    r = np.array([ref_lfc[g] for g in genes], dtype=float)
    pear, spear, dem = _pearson(s, r), _spearman(s, r), _deming(r, s)   # x=ref, y=sim (predict sim from data)

    # sign-concordance on the confidently-resolved DE genes (the load-bearing agreement)
    sig = (ref_sig & keep) if ref_sig else {g for g in genes if abs(ref_lfc[g]) >= DEG_SIG}
    sign_ok = sum(1 for g in sig if (sim_lfc[g] > 0) == (ref_lfc[g] > 0))
    sign_rate = round(sign_ok / len(sig), 3) if sig else None

    # null baseline: correlation of the DATA vector against a shuffled sim (a "high r is nearly free" control)
    rng = np.random.default_rng(0)
    null_r = _pearson(rng.permutation(s), r)

    resid = s - r
    order = np.argsort(-np.abs(resid))
    divergent = [{"gene": genes[i], "sim_log2fc": round(float(s[i]), 3), "ref_log2fc": round(float(r[i]), 3),
                  "delta": round(float(resid[i]), 3)} for i in order[:15]]

    slope = dem[0] if dem else None
    strong = pear is not None and pear >= 0.5 and (sign_rate is None or sign_rate >= 0.75)
    verdict = "CONCORDANT" if strong else "DIVERGENT (model-limit)"
    return {
        "n_genes": len(genes), "join_qc": join_qc,
        "pearson_r": (round(pear, 3) if pear is not None else None),
        "spearman_rho": (round(spear, 3) if spear is not None else None),
        "deming_slope": (round(slope, 3) if slope is not None else None),
        "deming_intercept": (round(dem[1], 3) if dem else None),
        "sign_concordance": sign_rate, "n_ref_significant": len(sig),
        "null_pearson_r": (round(null_r, 3) if null_r is not None else None),
        "top_divergent_genes": divergent, "verdict": verdict,
        "note": ("log2FC concordance of the sim vs a DESeq2 reference for a matched contrast. Read pearson_r AGAINST "
                 "null_pearson_r (a high r is nearly free from the shared housekeeping backbone); a Deming slope far "
                 "from 1 means the sim compresses/inflates the dynamic range. Each strong divergent gene is a "
                 "model-limit hypothesis (attribute to a named parameter), unless it is a data artifact (short-gene "
                 "zero, a total-mRNA-shift contrast needing spike-in normalization).")}


# --- the reference side (pydeseq2 on PRECISE-1K; gated) ----------------------------------------------------

def build_reference(contrast: dict) -> dict:
    """DESeq2 (pydeseq2) reference log2FC for a matched contrast over PRECISE-1K raw counts. `contrast` selects the
    B (test) and A (reference, default WT M9-glc) sample sets by a metadata column/value. Returns UNSHRUNK per-gene
    {log2FC, lfcSE, padj, baseMean} keyed by b-number, so it compares like-for-like with the unshrunk sim LFC."""
    ok, msg = available()
    if not ok:
        return {"error": msg}
    import pandas as pd
    from pydeseq2.dds import DeseqDataSet
    from pydeseq2.ds import DeseqStats

    counts = pd.read_csv(COUNTS, index_col=0)          # genes (b-number) x samples
    meta = pd.read_csv(METADATA, index_col=0, low_memory=False)
    strain = contrast.get("strain", REF_STRAIN)        # strain fidelity — same strain both arms (default MG1655)
    if strain and "Strain Description" in meta.columns:
        meta = meta[meta["Strain Description"].astype(str).str.contains(strain, na=False)]
    col = contrast.get("column", "condition")
    a, b = contrast.get("cond_A", REF_CONDITION), contrast["cond_B"]
    samples = meta.index[meta[col].isin([a, b])]
    if len(samples) < 4:
        return {"error": f"contrast {a} vs {b} (strain {strain}) has <4 replicates in PRECISE-1K — underpowered."}
    cnt = counts[samples].T.round().astype(int)        # pydeseq2 wants samples x genes, integer counts
    design = meta.loc[samples, [col]]
    dds = DeseqDataSet(counts=cnt, metadata=design, design_factors=col, quiet=True)
    dds.deseq2()
    stat = DeseqStats(dds, contrast=[col, b, a], quiet=True)
    stat.summary()                                     # UNSHRUNK Wald LFC (no lfc_shrink call)
    res = stat.results_df
    out = {g: {"log2FC": round(float(res.loc[g, "log2FoldChange"]), 4),
               "lfcSE": round(float(res.loc[g, "lfcSE"]), 4),
               "padj": (None if pd_isna(res.loc[g, "padj"]) else round(float(res.loc[g, "padj"]), 4)),
               "baseMean": round(float(res.loc[g, "baseMean"]), 2)}
           for g in res.index if not pd_isna(res.loc[g, "log2FoldChange"])}
    return {"contrast": {"cond_A": a, "cond_B": b, "column": col}, "n_genes": len(out),
            "n_replicates": {"A": int((design[col] == a).sum()), "B": int((design[col] == b).sum())},
            "reference_lfc": out, "provenance": provenance(contrast)}


def pd_isna(x) -> bool:
    try:
        return bool(x != x)   # NaN != NaN
    except Exception:
        return x is None


# --- the sim side + the end-to-end orchestrator (gated) ---------------------------------------------------

def sim_lfc(design: str, reference: str = "wildtype/basal") -> dict:
    """Sim mRNA log2FC per gene (keyed by b-number, to join PRECISE-1K) for a design vs reference, from the ALL-GENE
    reader mode (SCI-2c: `differential.all_gene_lfc`, kind='mrna'). Uses the FULL gene distribution — NOT just the
    significant movers, which range-restricts the concordance's Pearson/Deming. Empty if no local sim data."""
    from . import differential
    out = differential.all_gene_lfc(design, reference, kind="mrna")
    if not isinstance(out, dict) or not isinstance(out.get("lfc"), dict):
        return {}
    bmap = _bnumber_map()
    lfc = {}
    for gid, v in out["lfc"].items():
        sym = v.get("symbol") or gid
        val = v.get("log2fc")
        if val is not None:
            lfc[bmap.get(sym, sym)] = val              # map symbol -> b-number so it joins the DESeq2 reference
    return lfc


def rnaseq_concordance(design: str, contrast: dict, reference: str = "wildtype/basal") -> dict:
    """End-to-end SCI-2: build the DESeq2 reference log2FC for a matched PRECISE-1K contrast, get the sim log2FC for
    the corresponding design, and score their concordance (a model-limit finding). Gated — needs the `rnaseq` extra,
    the PRECISE-1K data, AND the sim-side reader; returns a clear message when any is missing."""
    ok, msg = available()
    if not ok:
        return {"error": msg}
    ref = build_reference(contrast)
    if "error" in ref:
        return ref
    sim = sim_lfc(design, reference)
    if not sim:
        return {"error": (f"no sim mRNA log2FC for '{design}' vs '{reference}' — the all-gene reader (SCI-2c) found "
                          "no local runs for the design/reference. Run or fetch the matched-contrast sims first.")}
    ref_flat = {g: v["log2FC"] for g, v in ref["reference_lfc"].items()}
    ref_sig = {g for g, v in ref["reference_lfc"].items()
               if v.get("padj") is not None and v["padj"] < PADJ_SIG and abs(v["log2FC"]) >= DEG_SIG}
    result = concordance(sim, ref_flat, ref_sig=ref_sig)
    result["contrast"] = ref["contrast"]
    result["provenance"] = ref["provenance"]
    return result
