"""Corpus audit — a read-only inventory of the simulation corpus.

Answers the four librarian questions over the manifest (no Docker, no raw reads, deletes NOTHING):
  * coverage     — what's in the corpus: designs, seeds/design, generation depth, viability spread
  * redundancy   — designs replicated beyond the target (the excess seeds are safe-to-prune, with GB freed)
  * supersession — dead-weight rows: an older run superseded by a newer one, and crashed runs still on disk
  * gaps         — power-thin designs (< target seeds) + a disk-feasibility budget for what more will FIT

`audit_report()` combines them, separating SAFE-TO-PRUNE (redundancy + supersession) from irreplaceable, so the
caller decides. The gaps + budget are the data layer the council + agent turn into feasibility-gated experiment
proposals ("what to run to strengthen / disconfirm a claim, given the disk budget"). GB figures are ESTIMATES,
not a live directory scan — and they are of two kinds, which this module now keeps apart. The three that
describe bytes ALREADY on disk (`coverage`, `redundancy`, `prune_candidates`) use the dividing-lineage rate
(the observed ~650 MB/generation footprint, see docker-sim-ops), because that is what those runs were. The one
that FORECASTS new runs (`gaps`) is stratified: it reads
`calibration.calibrated()` and reports a dividing and an arrested figure with the `basis` and `n` behind each,
because an arrested lineage writes 2-4x more and a knockout campaign sized off the dividing rate over-commits.
"""

from __future__ import annotations

import shutil
from collections import Counter, defaultdict
from pathlib import Path

MANIFEST_GLOB = "data/manifest/*.parquet"
# Observed simOut footprint per generation. This is NOT one number: a healthy dividing lineage writes ~0.65
# GB/gen, but an ARRESTED one (a lethal KO that never divides) runs its full time budget and writes 2-4x the
# timesteps — measured 1.58 GB/gen on KO:dapA (25.32 GB / 16 sim-generations). Budgeting a knockout campaign at
# 0.65 therefore under-estimates it, which is how a sweep fills a disk mid-run. Name the DENOMINATOR whenever
# you quote that ratio, because there are three of them and they are not interchangeable: 1.58 / 0.65 = 2.43x
# against this declared constant (the ~2.4x WELL-PRUNE-1 quotes); 1.58 / 0.808 = 1.96x against the measured
# figure in `resources.py:195-199`; and 1.58 / 0.645 = 2.45x against what `calibration.calibrated()` reports
# on this host today (n=12, spread 0.593-1.719). The last is host-specific and moves as runs land, so it is
# recomputed from `forecast_basis` rather than written down — never quote a ratio without saying which
# dividing figure it divided by.
#
# `_gb` DEFAULTS to the dividing rate because three of its four call sites describe what is ALREADY on disk.
# The fourth, `gaps()`, forecasts, and it passes `rate=` per stratum rather than hard-coding the arrested
# constant — see the comment there. These two are the single declaration of both rates in the tree:
# `calibration.calibrated()` imports them as its fallbacks instead of restating the literals, so a mutation of
# either is visible through both modules.
GB_PER_GENERATION = 0.65             # a dividing lineage
GB_PER_GENERATION_ARRESTED = 1.58    # a lethal/arrested KO — measured on KO:dapA, the SCI-TRNA-3 template
TARGET_SEEDS = 4           # replication target: > this = redundancy candidate, < this = power gap


def _rows() -> list[dict]:
    """Every shard row (NOT deduped — supersession needs the duplicates). union_by_name tolerates schema drift."""
    import duckdb

    from . import manifest
    con = duckdb.connect()
    try:
        # run_key MUST be the same (id, normalised-path) PAIR the rest of the corpus dedupes on
        # (manifest.DEDUP_KEY), or audit re-exposes the inflated counts every other tool corrects: the 9
        # re-indexed duplicates differ only by an absolute-vs-relative path prefix, so the old
        # `COALESCE(simout_path, id)` kept them as distinct runs and reported wildtype/basal at 34, not 26.
        # `_rows()` stays UN-deduped (supersession needs the duplicate rows); `_latest_per_run` collapses them.
        q = (f"SELECT {manifest.DEDUP_KEY} AS run_key, id, label, perturbation, condition, timeline, seed, "
             "simout_path, "   # the REAL path. run_key is `id @@ normalised-path` and is NOT a path.
             # `label` is REQUIRED, and omitting it was the whole of the design-count discrepancy:
             # `survey.design_tag` derives a design's identity from the label and falls back to the raw
             # `condition` column only for genuinely pre-label rows. Without the column every row
             # LOOKED pre-label, so the fallback fired for all 369 and silently merged designs that are
             # different experiments -- the four graded knockdowns of one gene into one design, two
             # transcript-level variants into one, the up- and down-shift timelines into one. The audit
             # reported 68 designs against the survey's 77 for four months on the strength of it.
             f"{manifest.elongation_sql()}, "   # safe before any shard carries the column (see the helper)
             "qc, reportable, crashed, ts, generations, requested_generations, gens_reached "
             f"FROM read_parquet('{MANIFEST_GLOB}', union_by_name=true)")
        return con.execute(q).to_arrow_table().to_pylist()
    except Exception as exc:
        return [{"__error__": str(exc)}]
    finally:
        con.close()


def _design(r: dict) -> str:
    """THE design key, shared with every other tool. Thin by design: `survey.design_key` is the one function.

    It used to be this file's own implementation over the raw columns, which is how two agent-reachable tools
    came to report different numbers of designs -- 68 here against 77 from the ranked survey -- with nothing
    recording which question either was answering.

    The local version was not a different definition. It was the SAME definition reading a projection that
    omitted `label`, so `design_tag`'s pre-label fallback fired on every row and merged designs that are
    different experiments. Its docstring explained at length why it had to append the elongation model by
    hand; that was a symptom of the missing column rather than a reason, because the label already carries
    the mode suffix. With `label` selected the two agree exactly: same 77 keys, no difference in either
    direction. `tests/test_design_identity.py` pins that.

    The counts the two tools report still differ, and that difference is real and is now named rather than
    silent -- see `coverage()`. An inventory and a ranking count different things; they must not disagree
    about what one design IS."""
    from .survey import design_key
    return design_key(r)


def _latest_per_run(rows: list[dict]) -> list[dict]:
    """Newest row per run_key (the (id, normalised-path) pair from manifest.DEDUP_KEY, set in `_rows`) — the same
    read-time dedup store/survey use, so audit counts the same corpus."""
    best: dict[str, dict] = {}
    for r in rows:
        k = r["run_key"]
        if k not in best or (r.get("ts") or 0) > (best[k].get("ts") or 0):
            best[k] = r
    return list(best.values())


def _gb(generations: int | None, seeds: int = 1, *, rate: float = GB_PER_GENERATION) -> float:
    """GB for `generations` x `seeds` at `rate` GB/generation, defaulting to the DIVIDING rate.

    `rate` is keyword-only on purpose. The three on-disk call sites (`coverage`, `redundancy`,
    `prune_candidates`) must keep the dividing rate and are not edited; a positional third argument would let
    one of them be silently re-rated, which turns a description of bytes already written into a forecast."""
    return round((generations or 0) * rate * seeds, 2)


def _forecast_rate(cal: dict, key: str, fallback: float) -> tuple[float, dict]:
    """One stratum's GB/generation for a FORECAST, paired with the evidence behind it.

    A `basis: 'measured'` row with n = 0 is REFUSED rather than echoed, and this is not defensive habit:
    `resources.py:195-199` records the day a stratum's unmeasured 1.58 dominated a measured 0.808 "while the
    result was still labelled measured — a 2x over-estimate wearing an empirical label". The n decides, not
    the word; with no evidence the declared constant is used and `basis` says so."""
    row = cal.get(key) or {}
    n = int(row.get("n") or 0)
    value = row.get("value")
    if row.get("basis") == "measured" and n > 0 and value:
        return float(value), {"basis": "measured", "n": n, "gb_per_generation": float(value)}
    return fallback, {"basis": "constant", "n": n, "gb_per_generation": fallback,
                      "why": row.get("why") or f"no measured {key} on this host; using the declared constant"}


def coverage() -> dict:
    """Per-design inventory: seed count, max generation depth, and the QC verdict spread."""
    rows = _rows()
    if rows and "__error__" in rows[0]:
        return {"error": rows[0]["__error__"]}
    live = _latest_per_run(rows)
    by_design: dict[str, list[dict]] = defaultdict(list)
    for r in live:
        by_design[_design(r)].append(r)
    designs = {}
    for d, rs in sorted(by_design.items()):
        max_gen = max((r.get("generations") or 0) for r in rs)
        designs[d] = {"n_seeds": len(rs), "max_generations": max_gen,
                      "qc": dict(Counter(r.get("qc") for r in rs)), "est_gb": _gb(max_gen, len(rs))}
    n_with_pass = sum(1 for v in designs.values() if v["qc"].get("ok", 0) > 0)
    return {"n_designs": len(designs), "n_runs": len(live),
            # Both counts, named. The two tools agree on what a design IS (one key function) and differ in
            # what they are counting, which is the legitimate part: this is an INVENTORY, so it counts every
            # design that exists including ones whose every run crashed; `survey_corpus` counts the designs it
            # can RANK and reports the excluded remainder separately. Naming them is what stops a document
            # quoting "designs" from inheriting whichever tool it happened to call.
            "n_designs_present": len(designs),
            "n_designs_with_a_passing_run": n_with_pass,
            "counts_note": ("this is an INVENTORY: n_designs_present counts every design on disk, crashed ones "
                            "included; "
                            "survey_corpus reports n_designs_ranked out of n_designs_in_corpus with the "
                            "remainder as n_designs_excluded. Both use survey.design_key, so they cannot "
                            "disagree about what one design is -- only about which designs they are for."),
            "n_perturbation_types": len({r["perturbation"] for r in live}), "designs": designs}


def redundancy(target_seeds: int = TARGET_SEEDS, channel: str = "growth_rate", ref_effect_pct: float = 10.0) -> dict:
    """Designs replicated beyond `target_seeds`, each with a POWER-GROUNDED verdict (not a heuristic): given the
    design's OWN replicate CV on `channel`, does dropping to target_seeds still detect a `ref_effect_pct` change?
    If yes the excess seeds are 'prune-safe'; if no they buy detection power -> 'keep-for-power'. The tool decides,
    grounded in real noise; the agent only relays it. Same two-sample math as power_check (alpha .05, power .8)."""
    import math
    import statistics as st

    from . import survey
    rows = survey._deduped_rows([channel])
    if rows and "__error__" in rows[0]:
        return {"error": rows[0]["__error__"]}
    by_design: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        v = r.get(channel)
        if v is not None:
            by_design[_design(r)].append(float(v))
    gens = {d: i["max_generations"] for d, i in coverage().get("designs", {}).items()}
    K = 2 * (1.96 + 0.84) ** 2   # two-sample n-per-group constant — matches power_check
    over, safe_gb = {}, 0.0
    for d, vals in sorted(by_design.items()):
        n, mean = len(vals), (st.fmean(vals) if vals else 0.0)
        if n <= target_seeds or not mean:
            continue
        cv = st.pstdev(vals) / abs(mean)
        mde_t = round(cv * math.sqrt(K / target_seeds) * 100, 1)
        mde_n = round(cv * math.sqrt(K / n) * 100, 1)
        prune_safe = mde_t <= ref_effect_pct
        gb = _gb(gens.get(d, 0), n - target_seeds)
        over[d] = {"n_seeds": n, "excess_seeds": n - target_seeds, "cv": round(cv, 4),
                   "mde_pct_at_target": mde_t, "mde_pct_at_current": mde_n,
                   "verdict": "prune-safe" if prune_safe else "keep-for-power", "est_gb_if_pruned": gb}
        if prune_safe:
            safe_gb += gb
    n_safe = sum(1 for v in over.values() if v["verdict"] == "prune-safe")
    return {"target_seeds": target_seeds, "channel": channel, "ref_effect_pct": ref_effect_pct,
            "n_designs_over": len(over), "n_prune_safe": n_safe, "est_gb_prunable_safe": round(safe_gb, 2),
            "designs": over,
            "note": f"prune-safe = {target_seeds} seeds still detect a {ref_effect_pct}% change on {channel} (the "
                    f"design's OWN CV); keep-for-power = the extra seeds buy detection. Two-sample a=.05 power=.8; "
                    f"GB counts only prune-safe designs."}


def supersession() -> dict:
    """Truly dead-weight manifest rows: an OLDER row for a run_key that also has a NEWER row (e.g. the enriched
    re-index superseding the pre-enrichment rows) — safe to COMPACT the shards (re-index dups free ~0 raw GB, the
    run_root being unchanged). Crashed runs are deliberately NOT flagged as prunable: a crashed KO is a first-class
    INVIABLE datapoint (keep-all-models), not garbage — only infrastructure crashes would be junk and those never
    reach the manifest (the batch stalls before writing). n_inviable_by_crash is a coverage fact, not a target."""
    rows = _rows()
    if rows and "__error__" in rows[0]:
        return {"error": rows[0]["__error__"]}
    by_key: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_key[r["run_key"]].append(r)
    stale = sum(len(rs) - 1 for rs in by_key.values() if len(rs) > 1)
    inviable = sorted({_design(r) for r in _latest_per_run(rows) if r.get("crashed")})
    return {"superseded_manifest_rows": stale, "n_inviable_by_crash": len(inviable),
            "inviable_by_crash_designs": inviable,
            "note": "superseded_manifest_rows are older duplicate rows AUTO-consolidated by manifest.compact() "
                    "(runs after each re-index) — housekeeping, NOT a user/agent decision. n_inviable_by_crash are "
                    "VALID lethal-KO results kept on purpose."}


def gaps(target_seeds: int = TARGET_SEEDS) -> dict:
    """Power-thin designs (< target_seeds) + a disk-feasibility budget: how many more full 8-gen lineages FIT in
    free disk now. This is the data layer the council + agent rank into claim-impact-ordered, feasibility-gated
    experiment proposals (the open-ended 'what should we run next?')."""
    cov = coverage()
    if "error" in cov:
        return cov
    thin = {d: {"n_seeds": info["n_seeds"], "seeds_needed": target_seeds - info["n_seeds"]}
            for d, info in cov["designs"].items() if info["n_seeds"] < target_seeds}
    free_gb = round(shutil.disk_usage(".").free / (1024 ** 3), 1)
    # THE forecast, and the only `_gb` call site that sizes runs which do not exist yet. It used to apply the
    # dividing rate to everything, so a knockout campaign planned off `feasible_8gen_lineages` over-committed:
    # on a 100 GB volume, at the two DECLARED constants, the dividing rate says 19 lineages (100 / (8 x 0.65)
    # = 19.23) and the arrested rate says 7 (100 / (8 x 1.58) = 7.91) — a 2.7x over-commitment in lineage
    # count. The arrested constant is NOT hard-coded here, because the measured rate is what should be used
    # when there is one: the evidence lives in `calibration.calibrated()`, which carries a `basis` and an `n`
    # per stratum, and this reports BOTH strata with that evidence rather than silently picking one.
    from . import calibration
    cal = calibration.calibrated()
    div_rate, div_basis = _forecast_rate(cal, "gb_per_generation_dividing", GB_PER_GENERATION)
    arr_rate, arr_basis = _forecast_rate(cal, "gb_per_generation_arrested", GB_PER_GENERATION_ARRESTED)
    per_div, per_arr = _gb(8, 1, rate=div_rate), _gb(8, 1, rate=arr_rate)   # a full 8-generation lineage
    note = ("thin_designs are power gaps; feasible_8gen_lineages_dividing / _arrested are the disk ceiling for "
            "new runs, STRATIFIED. An arrested lineage (a lethal KO that never divides) runs its full time "
            "budget and writes 2-4x the timesteps, so size a knockout campaign off the ARRESTED figure. "
            "`feasible_8gen_lineages` and `est_gb_per_8gen_lineage` are DEPRECATED aliases of the dividing "
            "figures, kept for one release because documents quote them.")
    # Say which stratum has no measurement behind it, rather than returning a bare number — the discipline
    # `resources.estimate_sim_resources` already implements as `disk_caveat`. On this tree the arrested
    # stratum is the empty one: `data/calibration/resource_observations.json` holds 164 `gb_per_generation`
    # rows and not one of them carries `arrested: true`, so its forecast is a declared estimate, not evidence.
    unmeasured = [s for s, b in (("dividing", div_basis), ("arrested", arr_basis)) if b["basis"] != "measured"]
    if unmeasured:
        note += (f" There is no MEASURED gb/generation for the {'/'.join(unmeasured)} stratum on this host, so "
                 f"that figure is the DECLARED CONSTANT and not an observation — see forecast_basis for the n.")
    return {"target_seeds": target_seeds, "n_thin_designs": len(thin), "thin_designs": thin,
            "free_disk_gb": free_gb,
            "est_gb_per_8gen_lineage_dividing": per_div, "est_gb_per_8gen_lineage_arrested": per_arr,
            "feasible_8gen_lineages_dividing": int(free_gb / per_div) if per_div else 0,
            "feasible_8gen_lineages_arrested": int(free_gb / per_arr) if per_arr else 0,
            "forecast_basis": {"dividing": div_basis, "arrested": arr_basis},
            "est_gb_per_8gen_lineage": per_div,                                      # DEPRECATED alias
            "feasible_8gen_lineages": int(free_gb / per_div) if per_div else 0,       # DEPRECATED alias
            "note": note}


def prune_candidates(target_seeds: int = TARGET_SEEDS, channel: str = "growth_rate",
                     ref_effect_pct: float = 10.0) -> dict:
    """Deterministically resolve the SPECIFIC run dirs safe to prune: the excess seeds (beyond target_seeds) of
    designs the grounded redundancy verdict marks 'prune-safe'. Keeps the lowest seed indices, lists the higher
    ones, with raw-on-disk + GB per candidate. DELETES NOTHING — the caller reviews and acts; the agent only
    relays this grounded list, it NEVER decides deletions (keep-for-power designs are never listed)."""
    from . import store
    red = redundancy(target_seeds, channel, ref_effect_pct)
    if "error" in red:
        return red
    gens = {d: i["max_generations"] for d, i in coverage().get("designs", {}).items()}
    safe = {d for d, i in red["designs"].items() if i["verdict"] == "prune-safe"}
    by_design: dict[str, list[tuple]] = defaultdict(list)
    for r in _latest_per_run(_rows()):
        d = _design(r)
        if d in safe:
            seed = r.get("seed")
            # Resolve the REAL run root. This read `run_key`, which is manifest.DEDUP_KEY —
            # `id || '@@' || normalised_path` — so `Path(run_root).exists()` was structurally always
            # False: `raw_on_disk` never fired, `est_gb_on_disk` was always 0.00, and the tool was
            # useless for the one job it has. Worse, `how_to_delete` interpolated that same non-path
            # into an `rm -rf` string. It was fail-safe only by accident (the `@@` string never
            # resolves); a deletion helper must be correct on purpose, not by luck.
            by_design[d].append((seed if seed is not None else 10 ** 9,
                                 store._resolve_run(r.get("simout_path")) or r.get("simout_path")))
    cands, gb_disk = [], 0.0
    for d in sorted(by_design):
        excess = sorted(by_design[d])[target_seeds:]        # keep the lowest target_seeds seeds; list the rest
        per_gb = _gb(gens.get(d, 0), 1)
        for seed, run_root in excess:
            on_disk = bool(run_root) and Path(run_root).exists()
            cands.append({"design": d, "seed": (None if seed == 10 ** 9 else seed), "run_root": run_root,
                          "raw_on_disk": on_disk, "est_gb": (per_gb if on_disk else 0.0)})
            if on_disk:
                gb_disk += per_gb
    return {"target_seeds": target_seeds, "n_candidates": len(cands), "est_gb_on_disk": round(gb_disk, 2),
            "candidates": cands,
            "note": "EXCESS seeds of PRUNE-SAFE designs only (the lowest seed indices are KEPT). Deterministic — the "
                    "agent relays this list, it never decides. DELETES NOTHING.",
            "how_to_delete": "review each run_root; delete only the ones you confirm (IRREVERSIBLE: rm -rf <run_root>), "
                             "then run manifest.compact() to drop their now-orphaned manifest rows."}


def audit_report(target_seeds: int = TARGET_SEEDS) -> dict:
    """Full audit: coverage + safe-to-prune (redundancy + supersession) + gaps/budget. Deletes NOTHING — the
    caller decides. 'Irreplaceable' = every run not flagged prunable."""
    cov = coverage()
    if "error" in cov:
        return cov
    red, sup, gp = redundancy(target_seeds), supersession(), gaps(target_seeds)
    return {"summary": {"n_designs": cov["n_designs"], "n_runs": cov["n_runs"],
                        "redundancy_prune_safe_designs": red.get("n_prune_safe", 0),
                        "est_gb_prunable_safe": red.get("est_gb_prunable_safe", 0.0),
                        "n_inviable_by_crash": sup.get("n_inviable_by_crash", 0),
                        "n_thin_designs": gp.get("n_thin_designs", 0),
                        # Both strata in the summary, because the summary is what gets quoted. The bare
                        # `feasible_8gen_lineages` is the DIVIDING figure and is kept only as an alias.
                        "feasible_8gen_lineages": gp.get("feasible_8gen_lineages", 0),
                        "feasible_8gen_lineages_dividing": gp.get("feasible_8gen_lineages_dividing", 0),
                        "feasible_8gen_lineages_arrested": gp.get("feasible_8gen_lineages_arrested", 0)},
            "coverage": cov, "redundancy": red, "gaps": gp,
            "housekeeping": sup,   # supersession is auto-consolidated by manifest.compact(); NOT a user decision
            "disclaimer": "read-only; nothing deleted. DECISIONS: redundancy carries a per-design power-grounded "
                          "verdict (prune-safe vs keep-for-power); gaps = thin designs + the disk budget. Superseded "
                          "rows are HOUSEKEEPING, auto-consolidated by manifest.compact() after a re-index — not a "
                          "user decision. Crashed runs are valid inviable datapoints, never pruned. GB figures are "
                          "ESTIMATES of two different kinds: coverage/redundancy/prune_candidates describe bytes "
                          "ALREADY on disk at the dividing-lineage rate (~0.65 GB/generation), while gaps() "
                          "FORECASTS new runs and is stratified — see gaps.forecast_basis for the rate, basis "
                          "('measured' with its n, or 'constant') behind each of the dividing and arrested "
                          "figures. Size a knockout campaign off the arrested one."}
