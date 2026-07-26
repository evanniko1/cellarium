"""Deterministic corpus survey — the anti-anchoring primitive.

Anchoring on the first salient run is not fixable by prompting (Lou 2024); the fix is to hand the agent the
WHOLE corpus, pre-computed and ranked by salience, so its (position-biased) attention isn't what decides what
matters. `survey_corpus` reads every run × channel from the manifest and returns, per channel, designs ranked
by |z| across designs (+ % change vs a reference), a cross-channel notable set, and coverage. No LLM, no
cherry-picking: the ranking is arithmetic. Cellwright must consume this before forming a hypothesis (see agent.py).
"""

from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict

from . import stats

_SEED_SUFFIX = re.compile(r"·s\d+$")   # label = "{perturbation}·{tag}·s{seed}"

MANIFEST_GLOB = "data/manifest/*.parquet"
# host-safe channel names (the worker owns the table/column mapping; we only need the names here)
CHANNELS = ["growth_rate", "ppgpp_conc", "ribosome_conc", "fraction_trna_charged", "rela_conc",
            "dry_mass", "protein_mass", "rna_mass", "cell_mass", "division_rate", "fba_objective"]
DIAGNOSTIC = {"fba_objective"}       # solver diagnostics — queryable, but excluded from the biological ranking
# division_rate (§J viability): mostly 1.0, so a low value is a strong flag — a KO/perturbation that did NOT divide
REFERENCE = ("wildtype", "basal")   # the control designs are compared against


_IDENT_CACHE: dict = {}


def _identity(design_key: str):
    """Cached factors.identity — the honest name for a design. Never raises: a missing cache must degrade to
    "no annotation", not break the survey the whole agent depends on."""
    if design_key not in _IDENT_CACHE:
        try:
            from . import factors
            _IDENT_CACHE[design_key] = factors.identity(design_key)
        except Exception:
            _IDENT_CACHE[design_key] = None
    return _IDENT_CACHE[design_key]


def design_tag(row: dict) -> str:
    """The identity of a DESIGN (the thing all its seeds are replicates of), taken from `label`, NOT from the raw
    `condition` column.

    Why this exists — it is a correctness fix, not a cosmetic one. `manifest._flat_row` persists
    `design.condition` verbatim while `label` gets `manifest._design_tag(design)`. Keying analyses on the raw
    column therefore MERGES designs that are different experiments, and two such merges are live in the current
    265-run corpus:

      * every `timeline` run stores `condition=None`, so an amino-acid UPSHIFT (`0 minimal, 1200
        minimal_plus_amino_acids`) and a DOWNSHIFT (`0 minimal_plus_amino_acids, 1200 minimal`) both key to
        `timeline/None` — and get averaged together as "4 seeds of one design". They are opposite experiments.
      * the propose path writes `condition='basal'` with the genes in `params.target_genes`, so the
        gltX+relA+spoT triple knockout keys to `multi_gene_knockout/basal`, while the generate.py path for the
        same perturbation keys correctly to `KO:pfkA+pfkB`.

    `label` already carries the correct tag, so deriving from it fixes every existing row retroactively — no
    re-index, which matters because re-indexing needs Docker and 117 of the 265 rows have no run directory left.
    """
    lab = str(row.get("label") or "")
    core = _SEED_SUFFIX.sub("", lab)
    if "·" in core:
        return core.split("·", 1)[1]
    return row.get("condition") or row.get("timeline") or "basal"   # pre-label corpora


def design_key(row: dict) -> str:
    """'perturbation/tag' — the string form used as a design's public identity across the tools."""
    return f'{row.get("perturbation")}/{design_tag(row)}'


def _deduped_rows(channels: list[str]) -> list[dict]:
    import duckdb

    con = duckdb.connect()
    last = ""
    # `label` is REQUIRED (not just nice): design identity is derived from it — see design_tag().
    # try with the pathways column (P2.1); fall back without it for pre-P2.1 corpora that lack it
    for cols in (["label", "perturbation", "condition", "timeline", "seed", "qc", "reportable", "pathways", *channels],
                 ["label", "perturbation", "condition", "timeline", "seed", "qc", "reportable", *channels]):
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
            by_design[(r["perturbation"], design_tag(r))].append(r)


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
            key = f"{d[0]}/{d[1]}"
            e = {"design": key, "mean": round(v, 6),
                 "ci95": (round(ci, 6) if ci is not None else None), "n": n,
                 "pct_vs_ref": (round(pct, 1) if pct is not None else None)}
            # A design's NAME can be wrong (KO:rpoB silences nothing; KO:flgB deletes nine genes). survey_corpus
            # is the mandatory first read, so the honest name travels with the number rather than being
            # discoverable only if the agent thinks to ask. Only attached when it differs — keeps the payload small.
            ident = _identity(key)
            if ident and ident.get("label_integrity") != "ok":
                e["true_label"] = ident["true_label"]
                e["label_integrity"] = ident["label_integrity"]
            entries.append(e)
        if len(entries) < 2:
            by_channel[ch] = {"reference": ref_v, "ranked": entries}
            continue
        vs = [e["mean"] for e in entries]
        mu, sd = statistics.fmean(vs), (statistics.pstdev(vs) or 1e-12)
        for e in entries:
            e["z"] = round((e["mean"] - mu) / sd, 2)
        entries.sort(key=lambda e: abs(e["z"]), reverse=True)
        # INFORMATIVE truncation (same convention as top_movers' "k of N significant dropped"). This tool exists
        # to stop the agent anchoring on whatever it happened to look at first — so silently showing 6 of N
        # designs and saying nothing would reintroduce the exact bias it was built to remove.
        by_channel[ch] = {"reference": (round(ref_v, 6) if ref_v is not None else None),
                          "n_designs_with_data": len(entries), "n_shown": min(top, len(entries)),
                          "n_dropped": max(0, len(entries) - top),
                          "ranked": entries[:top]}
        if ch not in DIAGNOSTIC:  # keep solver diagnostics out of the biological notable ranking
            notable += [{"channel": ch, **e} for e in entries if abs(e["z"]) >= 2.0]

    notable.sort(key=lambda e: abs(e.get("z", 0)), reverse=True)
    # What `coverage` must NOT do is let an agent read `n_designs` and believe it has seen the corpus. Three
    # things were invisible before: designs excluded from ranking entirely (n_designs counted only the survivors),
    # designs whose mean rests on FEWER seeds than were run because some crashed, and — per channel, above — how
    # many ranked designs were truncated away.
    seeds_by_design: dict[str, list] = defaultdict(list)
    for r in rows:
        seeds_by_design[design_key(r)].append(bool(r.get("reportable")))
    partial = sorted(k for k, v in seeds_by_design.items() if 0 < sum(v) < len(v))
    excluded = sorted(k for k, v in seeds_by_design.items() if not any(v))
    coverage = {
        "n_designs_ranked": len(by_design),          # what the ranking is actually computed over
        "n_designs_in_corpus": len(seeds_by_design),  # ...out of this many
        "n_designs_excluded": len(excluded),          # every seed non-reportable -> absent from every ranking
        "n_designs": len(by_design),                  # kept: existing callers read this (== n_designs_ranked)
        "n_runs": len(rows),
        "reference_present": ref is not None,
        "qc": dict(Counter(r["qc"] for r in rows)),
        "non_reportable_designs": excluded,
        # a mean over 3 of 4 seeds is not wrong, but the agent must know the replicate count shrank
        "designs_with_partial_seeds": {k: f"{sum(v)}/{len(v)} seeds usable"
                                       for k, v in seeds_by_design.items() if 0 < sum(v) < len(v)},
        "note": (f"{len(by_design)} of {len(seeds_by_design)} designs are ranked; {len(excluded)} are excluded "
                 f"(every seed non-reportable) and {len(partial)} rest on a reduced seed count. Per channel, "
                 f"`n_dropped` says how many ranked designs are not shown."),
    }
    return {
        "coverage": coverage,
        "notable": notable[:12],            # biggest effects across ALL channels, ranked by |z|
        "by_channel": by_channel,
        "note": ("Deterministic full-corpus survey ranked by computed salience (|z| across designs). "
                 "Consume this BEFORE forming a hypothesis; do not anchor on any single run or on prior "
                 "conversation. Then drill in with read_series / read_species and seek disconfirming evidence."),
    }
