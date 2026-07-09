"""Deterministic corpus survey — the anti-anchoring primitive.

Anchoring on the first salient run is not fixable by prompting (Lou 2024); the fix is to hand the agent the
WHOLE corpus, pre-computed and ranked by salience, so its (position-biased) attention isn't what decides what
matters. `survey_corpus` reads every run × channel from the manifest and returns, per channel, designs ranked
by |z| across designs (+ % change vs a reference), a cross-channel notable set, and coverage. No LLM, no
cherry-picking: the ranking is arithmetic. Coli must consume this before forming a hypothesis (see agent.py).
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict

MANIFEST_GLOB = "data/manifest/*.parquet"
# host-safe channel names (the worker owns the table/column mapping; we only need the names here)
CHANNELS = ["growth_rate", "ppgpp_conc", "ribosome_conc", "fraction_trna_charged", "rela_conc",
            "dry_mass", "protein_mass", "rna_mass", "cell_mass", "fba_objective"]
REFERENCE = ("wildtype", "basal")   # the control designs are compared against


def _deduped_rows(channels: list[str]) -> list[dict]:
    import duckdb

    cols = ["perturbation", "condition", "seed", "qc", "reportable", *channels]
    sel = ", ".join(f'"{c}"' for c in cols)
    q = (f"WITH d AS (SELECT * FROM read_parquet('{MANIFEST_GLOB}', union_by_name=true) "
         f"QUALIFY row_number() OVER (PARTITION BY COALESCE(simout_path,id) ORDER BY ts DESC)=1) "
         f"SELECT {sel} FROM d")
    con = duckdb.connect()
    try:
        return con.execute(q).fetch_arrow_table().to_pylist()
    except Exception as exc:
        return [{"__error__": str(exc)}]
    finally:
        con.close()


def survey_corpus(channels: list[str] | None = None, top: int = 6) -> dict:
    channels = channels or CHANNELS
    rows = _deduped_rows(channels)
    if rows and "__error__" in rows[0]:
        return {"error": f"corpus query failed: {rows[0]['__error__']}"}
    if not rows:
        return {"error": "corpus is empty — generate a campaign first (see docs/GENERATE.md)."}

    by_design: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        by_design[(r["perturbation"], r["condition"])].append(r)

    def dmean(rs: list[dict], ch: str):
        vals = [r[ch] for r in rs if r.get(ch) is not None]
        return sum(vals) / len(vals) if vals else None

    means = {d: {ch: dmean(rs, ch) for ch in channels} for d, rs in by_design.items()}
    ref = means.get(REFERENCE)

    by_channel: dict[str, dict] = {}
    notable: list[dict] = []
    for ch in channels:
        ref_v = (ref or {}).get(ch)
        entries = []
        for d, m in means.items():
            v = m.get(ch)
            if v is None:
                continue
            pct = (100.0 * (v - ref_v) / ref_v) if (ref_v not in (None, 0)) else None
            entries.append({"design": f"{d[0]}/{d[1]}", "mean": round(v, 6),
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
