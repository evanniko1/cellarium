"""Deterministic corpus survey — the anti-anchoring primitive.

Anchoring on the first salient run is not fixable by prompting (Lou 2024); the fix is to hand the agent the
WHOLE corpus, pre-computed and ranked by salience, so its (position-biased) attention isn't what decides what
matters. `survey_corpus` reads every run × channel from the manifest and returns, per channel, designs ranked
by |z| across designs (+ % change vs a reference), a cross-channel notable set, and coverage. No LLM, no
cherry-picking: the ranking is arithmetic. Cellwright must consume this before forming a hypothesis (see agent.py).
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict

from . import stats

MANIFEST_GLOB = "data/manifest/*.parquet"
# host-safe channel names (the worker owns the table/column mapping; we only need the names here)
CHANNELS = ["growth_rate", "ppgpp_conc", "ribosome_conc", "fraction_trna_charged", "rela_conc",
            "dry_mass", "protein_mass", "rna_mass", "cell_mass", "division_rate", "fba_objective"]
DIAGNOSTIC = {"fba_objective"}       # solver diagnostics — queryable, but excluded from the biological ranking
# division_rate (§J viability): mostly 1.0, so a low value is a strong flag — a KO/perturbation that did NOT divide
REFERENCE = ("wildtype", "basal")   # the control designs are compared against


def _deduped_rows(channels: list[str]) -> list[dict]:
    import duckdb

    con = duckdb.connect()
    last = ""
    # try with the pathways column (P2.1); fall back without it for pre-P2.1 corpora that lack it
    for cols in (["perturbation", "condition", "seed", "qc", "reportable", "pathways", *channels],
                 ["perturbation", "condition", "seed", "qc", "reportable", *channels]):
        sel = ", ".join(f'"{c}"' for c in cols)
        q = (f"WITH d AS (SELECT * FROM read_parquet('{MANIFEST_GLOB}', union_by_name=true) "
             f"QUALIFY row_number() OVER (PARTITION BY COALESCE(simout_path,id) ORDER BY ts DESC)=1) "
             f"SELECT {sel} FROM d")
        try:
            return con.execute(q).fetch_arrow_table().to_pylist()
        except Exception as exc:
            last = str(exc)
    con.close()
    return [{"__error__": last}]


def survey_corpus(channels: list[str] | None = None, top: int = 6) -> dict:
    import json

    base = channels or CHANNELS
    rows = _deduped_rows(base)
    if rows and "__error__" in rows[0]:
        return {"error": f"corpus query failed: {rows[0]['__error__']}"}
    if not rows:
        return {"error": "corpus is empty — generate a campaign first (see docs/GENERATE.md)."}

    # expand the per-pathway proteome fractions into first-class channels (pw:<pathway>)
    pw_keys: set[str] = set()
    for r in rows:
        try:
            r["_pw"] = json.loads(r.get("pathways") or "{}")
        except Exception:
            r["_pw"] = {}
        pw_keys |= set(r["_pw"])
    all_channels = base + [f"pw:{k}" for k in sorted(pw_keys)]

    def val(r: dict, ch: str):
        return r["_pw"].get(ch[3:]) if ch.startswith("pw:") else r.get(ch)

    # G1 (audit re-analysis): rank only REPORTABLE runs — a crashed/degenerate run's channel values are garbage
    # (e.g. gltX post-crash growth ranked z=+5.05). Non-reportable runs stay in `coverage` below, just not ranked.
    by_design: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("reportable"):
            by_design[(r["perturbation"], r["condition"])].append(r)

    import math

    def dmean_ci(rs: list[dict], ch: str):
        vals = [v for v in (val(r, ch) for r in rs) if v is not None]
        if not vals:
            return None, None, 0
        m = statistics.fmean(vals)
        ci = stats.t95_halfwidth(vals)  # 95% CI, t-distribution (right for n=4-8 seeds; normal-approx was too narrow)
        return m, ci, len(vals)

    stats_by_design = {d: {ch: dmean_ci(rs, ch) for ch in all_channels} for d, rs in by_design.items()}
    means = {d: {ch: v[0] for ch, v in chs.items()} for d, chs in stats_by_design.items()}
    ref = means.get(REFERENCE)

    by_channel: dict[str, dict] = {}
    notable: list[dict] = []
    for ch in all_channels:
        ref_v = (ref or {}).get(ch)
        entries = []
        for d, m in means.items():
            v = m.get(ch)
            if v is None:
                continue
            _mn, ci, n = stats_by_design[d][ch]
            pct = (100.0 * (v - ref_v) / ref_v) if (ref_v not in (None, 0)) else None
            entries.append({"design": f"{d[0]}/{d[1]}", "mean": round(v, 6),
                            "ci95": (round(ci, 6) if ci is not None else None), "n": n,
                            "pct_vs_ref": (round(pct, 1) if pct is not None else None)})
        if len(entries) < 2:
            by_channel[ch] = {"reference": ref_v, "ranked": entries}
            continue
        vs = [e["mean"] for e in entries]
        mu, sd = statistics.fmean(vs), (statistics.pstdev(vs) or 1e-12)
        for e in entries:
            e["z"] = round((e["mean"] - mu) / sd, 2)
        entries.sort(key=lambda e: abs(e["z"]), reverse=True)
        by_channel[ch] = {"reference": (round(ref_v, 6) if ref_v is not None else None),
                          "ranked": entries[:top]}
        if ch not in DIAGNOSTIC:  # keep solver diagnostics out of the biological notable ranking
            notable += [{"channel": ch, **e} for e in entries if abs(e["z"]) >= 2.0]

    notable.sort(key=lambda e: abs(e.get("z", 0)), reverse=True)
    coverage = {
        "n_designs": len(by_design), "n_runs": len(rows),
        "reference_present": ref is not None,
        "qc": dict(Counter(r["qc"] for r in rows)),
        "non_reportable_designs": sorted({f'{r["perturbation"]}/{r["condition"]}'
                                          for r in rows if not r.get("reportable")}),
    }
    return {
        "coverage": coverage,
        "notable": notable[:12],            # biggest effects across ALL channels, ranked by |z|
        "by_channel": by_channel,
        "note": ("Deterministic full-corpus survey ranked by computed salience (|z| across designs). "
                 "Consume this BEFORE forming a hypothesis; do not anchor on any single run or on prior "
                 "conversation. Then drill in with read_series / read_species and seek disconfirming evidence."),
    }
