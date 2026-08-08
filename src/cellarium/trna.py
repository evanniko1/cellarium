"""SCI-TRNA-1 — per-FAMILY charged-tRNA fractions, from raw simOut.

`fraction_trna_charged` is reported as a single number (~0.95). The raw listener is not one number: it is
**86 tRNA species × timesteps** (`GrowthLimits/fraction_trna_charged`, labelled by `uncharged_trna_ids`).
The reader collapses that to a per-timestep mean, and the mean is the wrong instrument for the question the
corpus keeps asking.

Why it matters, concretely. `argS` charges *arginine* tRNA. Knock it out and the arginine tRNAs go uncharged
while the other ~19 amino-acid families stay loaded — so the aggregate barely moves (19/20 still charged) and
**the one measurement that shows the mechanism is averaged away**. The relevant published axis is Dittmar,
Sørensen, Elf, Ehrenberg & Pan 2005 (*EMBO Rep* 6:151): starving a cell for one amino acid selectively
de-charges the tRNAs for **that** amino acid — the COGNATE-FAMILY axis, which is exactly what this module
measures.

**Withdrawn: the Elf et al. 2003 citation this module originally carried.** That paper's result is
*between-isoacceptor* — within one amino acid, some isoacceptors (e.g. tRNA2Leu) approach zero while others
stay high. This model cannot represent that: measured across every design on disk, the maximum within-family
spread among isoacceptors is **exactly 0.000e+00**, and the 86-species vector carries only **21 distinct
values** at every timestep (the listener's own `attributes.json` indexes the sibling columns
`charged_trna_conc` / `synthetase_conc` / `aa_conc` by `aaIds`, which has 21 entries — the per-amino-acid
resolution is the real resolution). Claiming this module "recovers Elf 2003" was not merely unsupported, it
was structurally impossible. It is 21 amino-acid rows presented as 86 species, and it is stated as such.

**The degeneracy guard exists because the original validation was invalid.** `KO:argS` was reported as a
blind success (arg -> 0.0 while the median family held). But that run is translationally ARRESTED: its
per-timestep row mean has total variation 1.2e-07 over the whole generation, against 1.5e+00 for wild-type —
seven orders of magnitude less. The charged fraction is a constant equal to (86 - n_target)/86, computable
from the knockout's isoacceptor count with no simulation at all. Reporting that as a measurement of selective
charging is reporting arithmetic as biology, so `per_family` now refuses the selectivity reading for any run
that fails the arrest test and says why.

Local-raw only (no Docker): reads the wcEcoli columns directly. Returns a structured error when the raw simOut
for a design is not on this machine, rather than a silent empty result.
"""

from __future__ import annotations

import json
import os
import re
import statistics
from collections import defaultdict

from . import support
from .capability import DEFAULT_MODE

# What the 86-wide `GrowthLimits/fraction_trna_charged` column ACTUALLY IS, per elongation model. One string
# per mode rather than one constant, because the column name and width are identical in all three and the
# meaning is not — which is the whole reason the elongation axis is recorded on every row.
_RESOLUTION = {
    "steady_state": ("21 amino-acid rows, not 86 independent species: the maximum within-family spread among "
                     "isoacceptors is exactly 0.0 in every design measured, so the 86-entry vector carries 21 "
                     "distinct values. The isoacceptor axis of Elf et al. 2003 is NOT representable here."),
    "kinetic": ("86 genuinely independent isoacceptor values: the kinetic model solves charging per "
                "isoacceptor (charged / (charged + free)) and writes tRNA space directly, so a within-family "
                "spread is a MEASUREMENT here rather than the arithmetic 0.0 the steady-state model produces. "
                "The isoacceptor axis of Elf et al. 2003 IS representable in this mode — but a value from it "
                "must never be compared against, or pooled with, a steady-state run."),
    "coarse_kinetic": ("NOT A MEASUREMENT. The coarse kinetic model does not solve charging at all: "
                       "CoarseKineticTrnaChargingModel.request and .evolve both return np.zeros(86), so this "
                       "column is IDENTICALLY 0.00 at every timestep. A table of zeros here reads as complete "
                       "de-acylation and is the ABSENCE of a charging model — the per-family reading is "
                       "withheld. Use elongation_model='steady_state' (per-amino-acid) or 'kinetic' "
                       "(per-isoacceptor) to measure charging."),
}

# tRNA ids look like 'alaT-tRNA[c]', 'argQ-tRNA[c]', 'selC-tRNA[c]'. The family is the leading 3 letters of the
# gene name, which is the amino-acid code by E. coli tRNA gene convention (alaT/alaU/alaV -> alanine).
_TRNA_ID = re.compile(r"^([a-zA-Z]{3})[A-Z0-9]*-tRNA")

# the three-letter tRNA gene prefixes that are NOT a standard amino-acid family
_SPECIAL = {"sel": "selenocysteine (selC — a special tRNA, not a standard family)"}


def family_of(trna_id: str) -> str | None:
    m = _TRNA_ID.match(str(trna_id or ""))
    return m.group(1).lower() if m else None


# Below this total variation in the per-timestep row mean, the charged-fraction vector is a CONSTANT and the
# run carries no charging dynamics. Wild-type sits at ~1.5; the arrested synthetase KOs sit at ~1.2e-07.
_ARREST_TOTVAR = 1e-6


def _arrest_evidence(seed_root: str) -> dict:
    """Is this run translationally ARRESTED? If so, its per-family table is arithmetic, not a measurement.

    Three independent columns, any of which alone is decisive: the charged-fraction row mean has essentially no
    total variation; the ribosome's own `effectiveElongationRate` is pinned at zero; protein mass does not
    grow. Read separately from the family table so the verdict can never be inferred from the table itself."""
    import numpy as np

    from . import raw
    sos = raw.simout_dirs(seed_root)
    out: dict = {}
    if not sos:
        return out
    so = sos[-1]
    try:
        v = np.asarray(raw.read_column(os.path.join(so, "GrowthLimits", "fraction_trna_charged")), dtype=float)
        rm = v[1:].mean(axis=1)                      # drop the t=0 initialisation row
        out["row_mean_total_variation"] = float(np.abs(np.diff(rm)).sum())
    except Exception:
        pass
    try:
        e = np.asarray(raw.read_column(os.path.join(so, "RibosomeData", "effectiveElongationRate")),
                       dtype=float).ravel()
        out["elongation_rate_mean_aa_per_s"] = round(float(np.nanmean(e)), 3)
        out["elongation_zero_fraction"] = round(float((e == 0).mean()), 4)
    except Exception:
        pass
    try:
        pm = np.asarray(raw.read_column(os.path.join(so, "Mass", "proteinMass")), dtype=float).ravel()
        if pm.size > 1 and pm[0]:
            out["protein_mass_end_over_start"] = round(float(pm[-1] / pm[0]), 4)
    except Exception:
        pass
    tv = out.get("row_mean_total_variation")
    zf = out.get("elongation_zero_fraction")
    out["arrested"] = bool((tv is not None and tv < _ARREST_TOTVAR) or (zf is not None and zf >= 0.999))
    return out


def _read(seed_root: str) -> tuple:
    """(matrix[timestep][species], species_ids, time) from one seed's LAST generation. Raises on unreadable."""
    import numpy as np

    from . import raw
    sos = raw.simout_dirs(seed_root)
    if not sos:
        raise FileNotFoundError(f"no simOut generations under {seed_root}")
    so = sos[-1]                      # last generation, matching how the summary channels are taken
    v = np.asarray(raw.read_column(os.path.join(so, "GrowthLimits", "fraction_trna_charged")))
    attrs = json.load(open(os.path.join(so, "GrowthLimits", "attributes.json"), encoding="utf-8"))
    ids = attrs.get("uncharged_trna_ids") or []
    t = np.asarray(raw.read_column(os.path.join(so, "Main", "time"))).ravel()
    if v.ndim != 2 or v.shape[1] != len(ids):
        raise ValueError(f"unexpected fraction_trna_charged shape {v.shape} vs {len(ids)} tRNA ids")
    return v, ids, t


def per_family(design: str, seed: int | None = None) -> dict:
    """Charged fraction per amino-acid tRNA family for one design (mean over the last generation's timesteps).

    Returns families sorted by charged fraction ASCENDING — the starved family first, which is the one the
    question is almost always about."""
    import numpy as np

    from . import factors, raw

    # WHICH ELONGATION MODEL this design ran under, read off the design key rather than assumed. The
    # `resolution` string below used to be a hard-coded constant asserting that isoacceptors cannot differ —
    # true of the steady-state corpus, and a FALSE STATEMENT returned as fact next to real data the moment a
    # kinetic run exists (measured within-family spread GLY 0.32, LEU 0.25). That is the silent-absence bug
    # inverted: a hard-coded "cannot" that has become a lie, and it would instruct the reader to discard a
    # genuine measurement.
    mode = factors.parse(design).get("elongation_model", DEFAULT_MODE)
    if mode == "coarse_kinetic":
        # Refuse rather than tabulate: under this model `CoarseKineticTrnaChargingModel.request`/`.evolve`
        # both return np.zeros(86), so every family would read 0.0000 and the table would look like total
        # de-acylation. That is the absence of a charging model, not a measurement of complete starvation.
        return {"design": design, "elongation_model": mode, "most_starved": None,
                "refused": _RESOLUTION[mode],
                "resolution": _RESOLUTION[mode]}
    runs = raw.seed_runs(design)
    if not runs:
        return {"error": f"no local raw simOut for '{design}' — this needs the run directory on this machine",
                "design": design}
    sel = [r for r in runs if seed is None or r.get("seed") == seed]
    if not sel:
        return {"error": f"seed {seed} has no local raw for '{design}'", "available_seeds":
                [r.get("seed") for r in runs]}

    # THE RUNS MUST BE THE MODEL WE ARE ABOUT TO CALL THEM (TRNA-8). `mode` above is parsed from the design
    # STRING; the runs come from `raw.seed_runs`, and nothing tied the two together. `seed_runs`' fallback
    # match (perturbation + a substring of condition) carries no elongation model, and the kinetic `KO:argS`
    # rows carry the SAME perturbation and condition as the steady-state ones — so a string that missed the
    # exact design key pooled both. MEASURED before the fix: `per_family('gene_knockout/KO:arg')` averaged
    # 4 steady-state with 4 kinetic runs, labelled the result `steady_state`, reported `arrested: False` while
    # half its seeds were arrested, and named a most-starved family. The boundary is fixed; this is the check
    # that the label is true, because the cost of it being false is a selectivity claim built from two
    # instruments, which reads exactly like a result.
    got = sorted({(r.get("elongation_model") or DEFAULT_MODE) for r in sel})
    if got != [mode]:
        return {"design": design, "elongation_model": mode, "most_starved": None,
                "refused": ("REFUSED: this design's local raw is %s but the request resolves to '%s'. The "
                            "charged-fraction channel is a broadcast identity under steady_state and 86 "
                            "independent values under kinetic, so a table built across them describes neither."
                            % ("+".join(got), mode)),
                "runs_by_model": {m: sum(1 for r in sel if (r.get("elongation_model") or DEFAULT_MODE) == m)
                                  for m in got},
                "fix": "name the design exactly, e.g. append '#elong:kinetic' for the kinetic arm."}
    per_seed_family: dict = defaultdict(list)
    used = []
    for r in sel:
        try:
            v, ids, _t = _read(r["root"])
        except Exception:
            continue
        used.append(r.get("seed"))
        col_mean = np.nanmean(v, axis=0)           # per-species mean over the generation
        byfam: dict = defaultdict(list)
        for i, tid in enumerate(ids):
            fam = family_of(tid)
            if fam:
                byfam[fam].append(float(col_mean[i]))
        for fam, vals in byfam.items():
            per_seed_family[fam].append(statistics.fmean(vals))
    if not used:
        return {"error": f"raw simOut for '{design}' could not be read (no GrowthLimits columns)"}
    fams = {f: round(statistics.fmean(v), 4) for f, v in per_seed_family.items()}
    ordered = sorted(fams.items(), key=lambda kv: kv[1])
    overall = round(statistics.fmean(list(fams.values())), 4)
    # Arrest is a per-RUN property, so it must be checked on EVERY readable seed, not just the first. Reading
    # sel[0] alone is the same n=1 defect this module was corrected for: one healthy seed among arrested ones
    # (or the reverse) would have been reported as the state of the design.
    arrests = [_arrest_evidence(r["root"]) for r in sel]
    arrests = [a for a in arrests if a]
    arrest = dict(arrests[0]) if arrests else {}
    if arrests:
        arrest["arrested"] = all(a.get("arrested") for a in arrests)
        arrest["n_seeds_checked"] = len(arrests)
        arrest["n_seeds_arrested"] = sum(1 for a in arrests if a.get("arrested"))
        if arrest["n_seeds_arrested"] not in (0, len(arrests)):
            arrest["disagreement"] = (
                f"{arrest['n_seeds_arrested']} of {len(arrests)} seeds are translationally arrested — the "
                f"design is NOT uniform, so a single per-design verdict would be wrong either way.")
    out = {
        "design": design, "seeds": used, "n_families": len(fams),
        "aggregate_mean_over_families": overall,
        "families": [{"family": f, "charged_fraction": c,
                      **({"note": _SPECIAL[f]} if f in _SPECIAL else {})} for f, c in ordered],
        "translation_state": arrest,
        "elongation_model": mode,
        "resolution": _RESOLUTION[mode],
        "note": ("Charged fraction per amino-acid tRNA family, mean over the last generation, sorted ascending "
                 "so the most-starved family is first. The corpus's single `fraction_trna_charged` is the mean "
                 "across all of these, which cannot show cognate-family de-charging (Dittmar et al. 2005, "
                 "EMBO Rep 6:151) — the axis a synthetase knockout or an amino-acid dropout acts on."),
    }
    support.attach(out, design)
    if arrest.get("arrested"):
        # An arrested run's table is (86 - n_target)/86 exactly — derivable from the knockout's isoacceptor
        # count without running anything. Naming a "most starved" family here would present arithmetic as a
        # measurement, and the ranking below row 1 is a stable-sort tie-break over families tied to 4 decimals.
        out["most_starved"] = None
        out["refused"] = (
            "TRANSLATIONALLY ARRESTED — no charging dynamics to read. The charged-fraction vector is constant "
            f"over the generation (row-mean total variation {arrest.get('row_mean_total_variation'):.2e}, "
            f"vs ~1.5 for wild-type), so the table is fixed by the knockout's isoacceptor count and contains no "
            "simulation-derived information. The selectivity reading is withheld; the table is shown only to "
            "make the degeneracy visible. Use a design where translation continues (an amino-acid dropout such "
            "as KO:dapA) to measure cognate-family de-charging.")
    else:
        out["most_starved"] = ordered[0][0] if ordered else None
    return out


_NULL_CACHE: dict = {}


def wildtype_null() -> dict:
    """The FALSE-POSITIVE floor: how big a selectivity gap appears between two genuine WILD-TYPE runs.

    Without this, `selectivity_gap_pp` is a number with no scale. Measured here it is damning — comparing
    wild-type lineages against each other, a "most starved family" is named essentially every time (trp
    dominates, then phe/leu/his) with a median gap in the double digits. Any gap a perturbation produces has to
    clear THIS, and the reason the boolean verdict was removed is that no threshold does.

    Content-hash de-duplicated: 48 wild-type units on disk are only 34 distinct files (14 byte-identical
    pairs), and counting duplicates as independent lineages would understate the null's spread."""
    import hashlib

    import numpy as np

    from . import raw, store
    if _NULL_CACHE:
        return _NULL_CACHE
    seen: dict = {}
    for r in store.list_results():
        if (r.get("perturbation") or "") != "wildtype":
            continue
        p = store.simout_path(r["id"])
        if not p:
            continue
        for so in raw.simout_dirs(p):
            f = os.path.join(so, "GrowthLimits", "fraction_trna_charged")
            if os.path.exists(f):
                with open(f, "rb") as fh:
                    seen.setdefault(hashlib.sha1(fh.read()).hexdigest(), so)
    tabs = []
    for so in seen.values():
        try:
            v = np.asarray(raw.read_column(f"{so}/GrowthLimits/fraction_trna_charged"), dtype=float)[1:]
            ids = json.load(open(os.path.join(so, "GrowthLimits", "attributes.json"), encoding="utf-8")
                            ).get("uncharged_trna_ids") or []
            byfam: dict = defaultdict(list)
            for i, tid in enumerate(ids):
                fam = family_of(tid)
                if fam:
                    byfam[fam].append(float(np.nanmean(v[:, i])))
            tabs.append({f: statistics.fmean(x) for f, x in byfam.items()})
        except Exception:
            continue
    if len(tabs) < 2:
        return {"error": "need >=2 distinct wild-type units on disk to measure the null", "n_units": len(tabs)}
    ref, gaps, names = tabs[0], [], []
    for t in tabs[1:]:
        worst = min(t, key=t.get)
        names.append(worst)
        gaps.append(100.0 * (ref[worst] - t[worst]))
    from collections import Counter
    _NULL_CACHE.update({
        "n_wildtype_units_on_disk": len(seen), "n_distinct_by_content_hash": len(tabs),
        "gap_pp": {"min": round(min(gaps), 1), "median": round(statistics.median(gaps), 1),
                   "max": round(max(gaps), 1)},
        "worst_family_named_on_pure_wildtype": Counter(names).most_common(),
        "note": ("Wild-type vs wild-type. Every one of these is a FALSE POSITIVE by construction: nothing was "
                 "perturbed. `trp` dominating the names is the tell — it is the lowest-charged family in this "
                 "model generally, so a naive 'most starved' rule reports it whatever the condition."),
    })
    return _NULL_CACHE


def selective_charging(design: str, reference: str = "wildtype/basal") -> dict:
    """Cognate-family de-charging vs a reference, reported AGAINST THE WILD-TYPE NULL — no verdict.

    An aminoacyl-tRNA synthetase lesion should hit its OWN family far harder than the rest. This reports the
    per-family drops and the selectivity gap, but deliberately returns NO boolean: measured against genuine
    wild-type-vs-wild-type comparisons the old `selective_charging: True/False` fired on unperturbed runs, and
    the wild-type maximum gap exceeds the only non-degenerate synthetase result in the corpus. A threshold
    without a null is not a detector, so the null is returned alongside every call and the reader draws the
    conclusion."""
    # REFUSE a cross-mode comparison before reading anything. The default reference is `wildtype/basal`, which
    # is steady_state, so a kinetic design compared against it would divide 86 genuinely independent values by
    # a broadcast identity and report the quotient as a per-family drop — the precise pooling the elongation
    # axis exists to prevent, in the one tool most likely to be pointed at a kinetic run. A drop_pct is a
    # ratio of two quantities, and here they would be quantities of different kinds.
    from . import factors
    m_t = factors.parse(design).get("elongation_model", DEFAULT_MODE)
    m_r = factors.parse(reference).get("elongation_model", DEFAULT_MODE)
    if m_t != m_r:
        return {"design": design, "reference": reference, "elongation_model": m_t,
                "reference_elongation_model": m_r, "worst_family": None, "selectivity_gap_pp": None,
                "refused": (f"'{design}' ran under the {m_t} elongation model and '{reference}' under {m_r}. "
                            f"`fraction_trna_charged` does not mean the same thing in the two — {_RESOLUTION[m_t]} "
                            f"vs {_RESOLUTION[m_r]} — so a per-family drop between them is a ratio of two "
                            f"different quantities, not a measurement. Compare within one elongation model.")}
    t = per_family(design)
    if "error" in t:
        return t
    ref = per_family(reference)
    if "error" in ref:
        return {**t, "reference_error": ref["error"]}
    rmap = {f["family"]: f["charged_fraction"] for f in ref["families"]}
    drops = []
    for f in t["families"]:
        base = rmap.get(f["family"])
        if base:
            drops.append({"family": f["family"], "charged": f["charged_fraction"], "reference": base,
                          "drop_pct": round(100.0 * (f["charged_fraction"] - base) / base, 1)})
    if not drops:
        return {**t, "error": "no shared families with the reference"}
    drops.sort(key=lambda d: d["drop_pct"])
    worst = drops[0]
    median_drop = statistics.median(d["drop_pct"] for d in drops)
    gap = round(median_drop - worst["drop_pct"], 1)
    null = wildtype_null()
    out = {
        "design": design, "reference": reference,
        "worst_family": worst, "median_drop_pct": round(median_drop, 1),
        "selectivity_gap_pp": gap,
        "translation_state": t.get("translation_state"),
        "wildtype_null": null,
        "per_family": drops,
        "note": ("Cognate-family de-charging (Dittmar et al. 2005, EMBO Rep 6:151). `selectivity_gap_pp` is how "
                 "many percentage points worse the worst family fares than the median family — read it against "
                 "`wildtype_null`, which is the same statistic computed between UNPERTURBED wild-type runs and "
                 "is therefore pure false-positive rate. NO verdict is returned: no threshold on this statistic "
                 "separates the corpus's perturbations from its own wild-type null."),
    }
    if t.get("refused"):
        out["refused"] = t["refused"]
    if isinstance(null.get("gap_pp"), dict) and null["gap_pp"].get("max") is not None:
        out["exceeds_wildtype_null_max"] = bool(gap > null["gap_pp"]["max"])
    return out
