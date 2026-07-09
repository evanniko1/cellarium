"""Biosecurity guardrail — screen a proposed design for dual-use / misuse signatures BEFORE it runs.

K-12 MG1655 is harmless; the screen is about *intent expressed in the design*, not the organism. v1 is
intent/signature-based: it matches a design's declared targets against curated signature sets, with direction
awareness (knocking OUT an efflux pump lowers resistance — safe; UP-regulating it raises resistance — flag).
Phenotype-grounded screening of *results* (detecting an AMR-efflux signature in the simulated proteome) is the
stronger P2 step (see docs/ROADMAP.md) and composes with survey.py. Nothing here blocks science on K-12 — it
flags for review, and only overt virulence engineering is blocked.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .model import Design


@dataclass
class Signature:
    name: str
    genes: set[str]
    concerning: str  # "up" = only up-regulation/activation is concerning; "any" = any engineering toward it
    severity: str    # "review" (flag, gate) | "block" (refuse)
    note: str


SIGNATURES = [
    Signature("amr_efflux",
              {"acra", "acrb", "acrd", "acrf", "tolc", "mara", "marr", "soxs", "soxr", "rob",
               "emra", "emrb", "mdtk", "mdfa"},
              "up", "review",
              "multidrug efflux / mar-sox-rob regulon — up-regulation raises antibiotic resistance"),
    Signature("toxin_overexpression",
              {"rele", "relb", "mazf", "maze", "hica", "hipa", "ccdb", "yafq", "chpb", "yoeb"},
              "up", "review",
              "toxin/antitoxin over-expression — induces growth arrest / persistence (tolerance)"),
    Signature("virulence",
              {"stx", "stxa", "stxb", "eae", "hlya", "hly", "cnf", "lt", "sta", "stb"},
              "any", "block",
              "virulence factor — absent from K-12; flag any engineering toward it"),
]


@dataclass
class BiosecurityVerdict:
    flagged: bool
    signature: str | None = None
    matched: list[str] = field(default_factory=list)
    severity: str | None = None
    reason: str = "No biosecurity signature matched."


def _targets(design: Design) -> set[str]:
    """Declared targets (params) plus a tokenised backstop over the design's labels."""
    toks: set[str] = set()
    for key in ("target_genes", "target_tfs", "targets"):
        for x in (design.params.get(key) or []):
            toks.add(str(x).lower())
    for label in (design.condition, design.timeline, design.perturbation):
        for tok in re.split(r"[^a-z0-9]+", str(label or "").lower()):
            if tok:
                toks.add(tok)
    return toks


def _direction(design: Design) -> str:
    """up = activation/over-expression (concerning); down = knockout/repression (generally safe)."""
    p = design.perturbation.lower()
    if "knockout" in p or p.endswith("_ko"):
        return "down"
    d = str(design.params.get("direction", "")).lower()
    if d in ("up", "activate", "overexpress", "increase"):
        return "up"
    if d in ("down", "knockout", "ko", "decrease", "repress"):
        return "down"
    if p == "tf_activity":
        return "up"  # TF-activity designs default to activation unless declared otherwise
    return "unknown"


def screen(design: Design) -> BiosecurityVerdict:
    """Flag a design that engineers toward a misuse signature. Conservative: 'unknown' direction still flags an
    up-only signature for review (cheap to review; a knockout is exempted)."""
    toks = _targets(design)
    direction = _direction(design)
    for sig in SIGNATURES:
        matched = sorted(toks & sig.genes)
        if not matched:
            continue
        concerning = sig.concerning == "any" or direction in ("up", "unknown")
        if concerning:
            return BiosecurityVerdict(True, sig.name, matched, sig.severity,
                                      f"Design targets the {sig.name} signature ({', '.join(matched)}): {sig.note}.")
    return BiosecurityVerdict(False)


# --- phenotype-grounded screen (P2.3): flag the RESULT, not the intent ------------------------------------
# Concerning pathway signatures + the fold-change over a control at which they warrant review. This catches an
# *emergent* misuse phenotype (a design whose simulated proteome up-regulates efflux) even when the design never
# named an efflux gene — "grounded in the predicted phenotype, not keywords" (DEMO Act 3).
CONCERNING_PATHWAYS = {
    "amr_efflux": {"threshold_log2fc": 1.0, "severity": "review",
                   "note": "multidrug-efflux proteome up-regulation raises antibiotic resistance"},
}


@dataclass
class PhenotypeVerdict:
    flagged: bool
    signature: str | None = None
    log2fc: float | None = None
    severity: str | None = None
    reason: str = "No concerning phenotype elevated vs reference."


def _screen_phenotype(target_vals: dict, ref_vals: dict) -> PhenotypeVerdict:
    """Pure core: compare a design's pathway proteome fractions to a reference's; flag a concerning pathway
    elevated past its threshold. `*_vals` map 'pw:<pathway>' -> proteome fraction."""
    hits = []
    for pathway, cfg in CONCERNING_PATHWAYS.items():
        tv, rv = target_vals.get(f"pw:{pathway}"), ref_vals.get(f"pw:{pathway}")
        if tv is None or rv in (None, 0) or tv <= 0:
            continue
        log2fc = math.log2(tv / rv)
        if log2fc >= cfg["threshold_log2fc"]:
            hits.append((pathway, round(log2fc, 2), cfg))
    if not hits:
        return PhenotypeVerdict(False)
    pathway, log2fc, cfg = max(hits, key=lambda h: h[1])
    return PhenotypeVerdict(True, pathway, log2fc, cfg["severity"],
                            f"Simulated phenotype up-regulates {pathway} by {log2fc} log2FC "
                            f"(~{round((2 ** log2fc - 1) * 100)}%) vs reference — {cfg['note']}.")


def screen_result(target: str, reference: str = "wildtype/basal") -> PhenotypeVerdict:
    """Phenotype-grounded screen of a design's simulated results (by label), vs a reference design."""
    from . import differential

    means, _ = differential._design_means()
    if not means:
        return PhenotypeVerdict(False, reason="corpus empty or unreadable.")
    t, r = means.get(target), means.get(reference)
    if t is None:
        return PhenotypeVerdict(False, reason=f"no design '{target}'.")
    if r is None:
        return PhenotypeVerdict(False, reason=f"no reference '{reference}'.")
    return _screen_phenotype(t, r)
