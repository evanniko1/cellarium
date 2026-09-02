"""Reproduce the deposited-data result: within-family leucine tRNA charging spread from GSE2065.

WHAT THIS ESTABLISHES. The default (steady-state) elongation mode broadcasts one per-amino-acid
charged fraction across all 86 gene-indexed `fraction_trna_charged` columns, so every within-family
contrast it can report is exactly zero. That is a statement about the model. This script supplies the
other half: a measurement in which the leucine isoacceptors visibly do NOT move together, which turns
the broadcast from a curiosity into a quantified error floor no parameter fit can cross.

WHY THE RAW FILE IS NOT COMMITTED. NCBI asks that GEO records be retrieved from GEO rather than
redistributed, so this fetches `GSE2065_family.soft.gz` (115 KB) on demand and verifies it against a
pinned SHA-256 before parsing. The DERIVED tables are committed, so the assertions in
tests/test_gse2065.py run with no network at all; `--verify-download` re-runs the whole chain.

HOW THE FIVE PROBE GROUPS ARE IDENTIFIED. Not by hand, and not by matching the paper. The GPL1746
platform table gives each spot a probe name and up to six Entrez GeneIDs. Fourteen `Leu-*` probes
carry 18 spots each; five of them carry E. coli GeneIDs, and exactly one of those five (`Leu-7`)
carries four -- leuT, leuV, leuP and leuQ -- which is the pooled LeuPQVT group the assay cannot
resolve. The other four are single-locus. The GeneID -> symbol table below is transcribed from NCBI
Gene so the grouping is reproducible offline; `--verify-genes` re-checks it against Entrez.

Run:  python scripts/gse2065_reanalysis.py                  # fetch (cached), recompute, write outputs
      python scripts/gse2065_reanalysis.py --verify-download # re-fetch and re-check the input hash
      python scripts/gse2065_reanalysis.py --plot            # also regenerate figure 1b/1c
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import statistics as st
import urllib.request
from pathlib import Path

SOFT_URL = "https://ftp.ncbi.nlm.nih.gov/geo/series/GSE2nnn/GSE2065/soft/GSE2065_family.soft.gz"
SOFT_SHA256 = "038053436b2e295380f11bb6904d591013fd1cd2a634fd3c1fb0ff91915295d2"

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "gse2065" / "GSE2065_family.soft.gz"   # gitignored; fetched on demand
OUT = ROOT / "data" / "gse2065"

# Entrez Gene symbols for the E. coli leucine tRNA loci on GPL1746 (NCBI Gene, checked 2026-09-02).
# --verify-genes re-queries Entrez and fails on any disagreement.
GENE_SYMBOLS = {
    "948803": "leuX", "947505": "leuU", "945662": "leuZ", "945264": "leuW",
    "948304": "leuT", "948873": "leuV", "948875": "leuP", "948893": "leuQ",
}
TIMES = [0, 2, 7, 17, 32]


def fetch(verify_download: bool = False) -> bytes:
    """Return the SOFT bytes, fetching to the cache if absent, and fail loudly on a hash mismatch."""
    if verify_download or not CACHE.exists():
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(SOFT_URL, CACHE)   # noqa: S310 — fixed NCBI host, not user-supplied
    raw = CACHE.read_bytes()
    got = hashlib.sha256(raw).hexdigest()
    if got != SOFT_SHA256:
        raise SystemExit(
            f"GSE2065 input hash mismatch.\n  expected {SOFT_SHA256}\n  got      {got}\n"
            "GEO reprocessed the record, or the download truncated. Do not use the derived tables "
            "until this is resolved: every number downstream is conditional on this exact input."
        )
    return gzip.decompress(raw)


def parse(soft_text: str) -> tuple[dict[str, str], dict[int, dict[str, list[float]]]]:
    """Return (probe -> group label, {minute: {group: [18 log-ratio spot values]}}).

    Groups are built from the platform's GeneIDs, so a probe whose loci we cannot name is dropped
    rather than guessed at -- an unlabelled probe is not evidence.
    """
    lines = soft_text.splitlines()

    id_to_probe: dict[str, str] = {}
    probe_genes: dict[str, list[str]] = {}
    in_platform = False
    for ln in lines:
        if ln.startswith("!platform_table_begin"):
            in_platform = True
            continue
        if ln.startswith("!platform_table_end"):
            in_platform = False
            continue
        if in_platform and not ln.startswith("ID"):
            f = ln.split("\t")
            if len(f) > 2 and f[1].startswith("Leu-"):
                id_to_probe[f[0]] = f[1]
                probe_genes[f[1]] = [g.strip() for g in f[2:8] if g.strip()]

    # A probe joins the analysis only if EVERY one of its loci is a named E. coli leucine tRNA.
    probe_to_group: dict[str, str] = {}
    for probe, genes in probe_genes.items():
        symbols = [GENE_SYMBOLS.get(g) for g in genes]
        if not symbols or any(s is None for s in symbols):
            continue
        label = "Leu" + "".join(sorted(s[-1].upper() for s in symbols))
        # The pooled probe is named for its loci in the order Dittmar et al. use, so the derived
        # tables and the manuscript refer to the same group by the same name.
        probe_to_group[probe] = "LeuPQVT" if label == "LeuPQTV" else label

    by_time: dict[int, dict[str, list[float]]] = {}
    minute, in_sample = None, False
    for ln in lines:
        if ln.startswith("!Sample_title"):
            minute = int(ln.split("t=")[1].strip())
            by_time[minute] = {}
        if ln.startswith("!sample_table_begin"):
            in_sample = True
            continue
        if ln.startswith("!sample_table_end"):
            in_sample = False
            continue
        if in_sample and not ln.startswith("ID_REF"):
            f = ln.split("\t")
            group = probe_to_group.get(id_to_probe.get(f[0], ""), "")
            if group and len(f) > 1:
                try:
                    value = float(f[1])
                except ValueError:
                    continue    # a blank or flagged spot is absent, not zero
                # Appendix B states VALUE = log2(PRE_VALUE). Check it rather than trust it: if GEO
                # ever re-deposits with a different transform, every ratio below silently changes
                # meaning while still looking like a number.
                if len(f) > 2:
                    try:
                        pre = float(f[2])
                    except ValueError:
                        pre = 0.0
                    if pre > 0 and abs(value - math.log2(pre)) > 1e-4:
                        raise SystemExit(
                            f"VALUE != log2(PRE_VALUE) at spot {f[0]} (t={minute}): {value} vs "
                            f"{math.log2(pre)}. The deposited transform is not what Appendix B describes."
                        )
                by_time[minute].setdefault(group, []).append(value)
    return probe_to_group, by_time


def ratios(by_time, groups, drop: int | None = None) -> dict[int, dict[str, float]]:
    """R_g(t) = 2 ** (median VALUE_g(t) - median VALUE_g(0)), optionally excluding one spot position."""
    def med(minute, g):
        v = by_time[minute][g]
        return st.median([x for k, x in enumerate(v) if k != drop] if drop is not None else v)

    base = {g: med(0, g) for g in groups}
    return {t: {g: 2 ** (med(t, g) - base[g]) for g in groups} for t in TIMES}


def _six_inequalities(R, northern: list[float], groups: list[str]) -> dict:
    """The 2 high x 3 low comparisons, required to hold in the derived array AND the published blot.

    The two assays disagree on magnitude, so the ordering is the only thing a component test can be
    scored against. Checking it here keeps that claim falsifiable instead of asserted in prose.
    """
    idx = {g: i for i, g in enumerate(groups)}
    high, low = ("LeuX", "LeuZ"), ("LeuPQVT", "LeuU", "LeuW")
    out = {}
    for h in high:
        for lo in low:
            array_ok = all(R[t][h] > R[t][lo] for t in TIMES[1:])
            out[f"{h}>{lo}"] = {"array_all_times": array_ok,
                                "northern": northern[idx[h]] > northern[idx[lo]]}
    out["all_six_hold_in_both"] = all(v["array_all_times"] and v["northern"]
                                      for k, v in out.items() if k != "all_six_hold_in_both")
    return out


def _spot_iqr(by_time, group, minute, R) -> tuple[float, float]:
    """Quartiles of the 18 spots at `minute`, carried onto the ratio scale the figure plots.

    Each spot is exponentiated against the SAME time-zero median the point uses, so the whisker and
    the marker are on one scale. Spread across printed spots only -- one hybridisation per time point.
    """
    base = st.median(by_time[0][group])
    spots = sorted(2 ** (v - base) for v in by_time[minute][group])
    n = len(spots)
    lo = st.median(spots[: n // 2])
    hi = st.median(spots[(n + 1) // 2:])
    return lo, hi


def _ordering_under_exclusions(by_time, groups) -> dict:
    """Does LeuX/LeuZ stay above LeuPQVT/LeuU/LeuW in every leave-one-spot-out refit?

    Reported as counts rather than a bare bool so a partial failure is visible instead of collapsing
    to False with no indication of how close the separation came to inverting.
    """
    high_g, low_g = ("LeuX", "LeuZ"), ("LeuPQVT", "LeuU", "LeuW")
    total = held = 0
    margin = None
    for d in range(len(by_time[0][groups[0]])):
        R = ratios(by_time, groups, drop=d)
        for t in TIMES[1:]:
            total += 1
            gap = min(R[t][g] for g in high_g) - max(R[t][g] for g in low_g)
            held += gap > 0
            margin = gap if margin is None else min(margin, gap)
    return {"comparisons": total, "held": held, "min_margin": round(margin, 5)}


def floors(y: list[float], weights: list[float] | None = None) -> tuple[float, float]:
    """Minimum equal-weight RMSE of any family-constant prediction, and its minimum L-infinity error."""
    w = weights or [1 / len(y)] * len(y)
    mean = sum(wi * yi for wi, yi in zip(w, y))
    rmse = math.sqrt(sum(wi * (yi - mean) ** 2 for wi, yi in zip(w, y)))
    return rmse, (max(y) - min(y)) / 2


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verify-download", action="store_true", help="re-fetch and re-check the input hash")
    ap.add_argument("--verify-genes", action="store_true", help="re-check GeneID symbols against Entrez")
    ap.add_argument("--plot", action="store_true", help="regenerate figure 1b/1c")
    args = ap.parse_args()

    if args.verify_genes:
        verify_genes()

    probe_to_group, by_time = parse(fetch(args.verify_download).decode("utf-8", "replace"))
    groups = ["LeuPQVT", "LeuU", "LeuW", "LeuX", "LeuZ"]
    groups = [g for g in groups if g in by_time[0]]
    if len(groups) != 5:
        raise SystemExit(f"expected 5 probe groups, built {len(groups)}: {sorted(by_time[0])}")

    R = ratios(by_time, groups)
    n_spots = {g: len(by_time[0][g]) for g in groups}

    # Technical spot IQRs -- what the figure whiskers show. These are the spread of printed spots
    # within one hybridisation, so they are NOT confidence intervals and NOT biological variability;
    # they are reported because a median over 18 spots with no dispersion shown invites the opposite
    # reading. Carried on the ratio scale, so they sit against R_g(t).
    iqr = {t: {g: _spot_iqr(by_time, g, t, R) for g in groups} for t in TIMES}

    # The ordering claim, checked where the manuscript makes it: LeuX and LeuZ above the other three
    # in EVERY single-spot exclusion, not merely in the pooled table.
    ordering = _ordering_under_exclusions(by_time, groups)

    rows = [{"time_min": t, **{g: round(R[t][g], 5) for g in groups},
             **{f"{g}_iqr_lo": round(iqr[t][g][0], 5) for g in groups},
             **{f"{g}_iqr_hi": round(iqr[t][g][1], 5) for g in groups}} for t in TIMES]
    stats = []
    for t in TIMES[1:]:
        y = [R[t][g] for g in groups]
        rmse, linf = floors(y)
        # LeuPQTV pools four loci; weighting by locus count rather than by probe is the second check.
        loci = [4 if g.startswith("LeuPQ") else 1 for g in groups]
        w = [c / sum(loci) for c in loci]
        lo_rmse = [floors([ratios(by_time, groups, drop=d)[t][g] for g in groups])[0] for d in range(18)]
        # 6 dp, not 5: at 5 dp a value like 0.10825 re-rounds to 0.1082 when displayed at 4 dp, so a
        # reader comparing the console against the manuscript's 0.108 sees a disagreement that is not there.
        stats.append({
            "time_min": t, "rmse_floor": round(rmse, 6), "linf_floor": round(linf, 6),
            "range": round(max(y) - min(y), 6),
            "rmse_loci_weighted": round(floors(y, w)[0], 6),
            "rmse_leave_one_spot_min": round(min(lo_rmse), 6),
            "rmse_leave_one_spot_max": round(max(lo_rmse), 6),
        })

    # The six high-vs-low inequalities the two assays share. The Northern vector is TRANSCRIBED from
    # Dittmar et al. -- it is not in the GEO record and this script cannot derive it, so it is pinned
    # here as a literature constant and labelled as one. The array side IS derived, so the agreement
    # being checked is between this reanalysis and the published blot, not between two constants.
    inequalities = {
        "northern_source": "Dittmar et al. 2005, acidic Northern blot (transcribed, not derived here)",
        "northern_relative": dict(zip(groups, [0.024, 0.025, 0.017, 0.19, 0.11])),
        "northern_baseline_fractions": dict(zip(groups, [0.80, 0.77, 0.68, 0.76, 0.84])),
        "shared_high_vs_low": _six_inequalities(R, [0.024, 0.025, 0.017, 0.19, 0.11], groups),
    }

    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "table_rg.csv").open("w", newline="", encoding="utf-8") as fh:
        w_ = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w_.writeheader()
        w_.writerows(rows)
    with (OUT / "error_floors.csv").open("w", newline="", encoding="utf-8") as fh:
        w_ = csv.DictWriter(fh, fieldnames=list(stats[0]))
        w_.writeheader()
        w_.writerows(stats)
    (OUT / "summary.json").write_text(json.dumps({
        "source": SOFT_URL, "input_sha256": SOFT_SHA256,
        "probe_to_group": probe_to_group, "spots_per_group": n_spots,
        "ordering_under_spot_exclusions": ordering, "assay_agreement": inequalities,
        "note": ("Within-probe, time-zero-normalised processed ratios -- NOT absolute charged "
                 "fractions. One hybridisation per time point; the 18 spots are technical replicates, "
                 "so spot IQRs are reported and no biological p-value is."),
        "table_rg": rows, "error_floors": stats,
    }, indent=1), encoding="utf-8")

    print(f"groups: {', '.join(f'{g} (n={n_spots[g]})' for g in groups)}")
    for s in stats:
        print(f"  t={s['time_min']:2}  RMSE={s['rmse_floor']:.4f}  Linf={s['linf_floor']:.4f}  "
              f"range={s['range']:.4f}  loci-wt={s['rmse_loci_weighted']:.4f}  "
              f"LOSO={s['rmse_leave_one_spot_min']:.3f}-{s['rmse_leave_one_spot_max']:.3f}")
    o = ordering
    print(f"  ordering LeuX/LeuZ above the rest: {o['held']}/{o['comparisons']} leave-one-spot refits, min margin {o['min_margin']:.4f}")
    print(f"  six shared inequalities hold in both assays: {inequalities['shared_high_vs_low']['all_six_hold_in_both']}")
    print(f"wrote {OUT / 'table_rg.csv'}, {OUT / 'error_floors.csv'}, {OUT / 'summary.json'}")

    if args.plot:
        plot(R, stats, groups, iqr)


def verify_genes() -> None:
    """Re-query Entrez for each pinned GeneID and fail on any symbol disagreement."""
    ids = ",".join(GENE_SYMBOLS)
    url = ("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
           f"?db=gene&id={ids}&retmode=json")
    with urllib.request.urlopen(url, timeout=60) as fh:      # noqa: S310 — fixed NCBI host
        result = json.load(fh)["result"]
    bad = {g: (GENE_SYMBOLS[g], result[g]["name"]) for g in GENE_SYMBOLS
           if g in result and result[g]["name"] != GENE_SYMBOLS[g]}
    if bad:
        raise SystemExit(f"GeneID symbols disagree with Entrez: {bad}")
    print(f"verified {len(GENE_SYMBOLS)} GeneID symbols against Entrez")


def plot(R, stats, groups, iqr) -> None:
    """Figure 1b (trajectories) and 1c (error floors). Panel (a) is a schematic, drawn separately."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9, 3.4))
    styles = [("o", "-"), ("s", "--"), ("^", ":"), ("D", "-."), ("v", (0, (3, 1, 1, 1)))]
    for (marker, ls), g in zip(styles, groups):     # marker AND line style, so it survives greyscale
        y = [R[t][g] for t in TIMES]
        # Whiskers are technical spot IQRs, not confidence intervals -- said in the caption too.
        err = [[y[i] - iqr[t][g][0] for i, t in enumerate(TIMES)],
               [iqr[t][g][1] - y[i] for i, t in enumerate(TIMES)]]
        ax1.errorbar(TIMES, y, yerr=err, marker=marker, linestyle=ls, label=g, ms=4,
                     capsize=2, elinewidth=0.7, lw=1)
    ax1.set_xlabel("minutes after leucine withdrawal")
    ax1.set_ylabel("$R_g(t)$ (processed, $t{=}0{=}1$)")
    ax1.legend(fontsize=7, frameon=False)
    ax1.set_title("b  deposited trajectories", loc="left", fontsize=9)

    ts = [s["time_min"] for s in stats]
    ax2.bar([str(t) for t in ts], [s["rmse_floor"] for s in stats], color="0.4")
    ax2.set_xlabel("minutes after withdrawal")
    ax2.set_ylabel("min equal-group RMSE")
    ax2.set_title("c  floor on any family-constant prediction", loc="left", fontsize=9)
    fig.tight_layout()
    dest = OUT / "figure1_panels_bc.pdf"
    fig.savefig(dest)
    print(f"wrote {dest}")


if __name__ == "__main__":
    main()
