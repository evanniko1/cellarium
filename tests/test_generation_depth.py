"""Generation depth is part of WHAT WAS MEASURED — and it took three attempts to say that correctly.

A channel is the LAST generation's time-mean (`_reader_worker.py:203` is `_dynamics(gs[-1])`, and its own
comment says so). So a run to 1 generation reports generation 0 and a run to 7 reports generation 6. Depth
does not add noise to a design's mean; it decides which generation the mean is OF.

Two withdrawn attempts, both pinned below so neither can return:

  1. **"cross-machine variance."** Three `wildtype/basal` seed-0 runs disagreed, two came from different
     contributors, so the model was declared non-deterministic across environments and the seeds clustered by
     machine. Wrong: those runs also differed in `generations`, and at a fixed depth the machine ICC is 0.0.
  2. **"cluster on depth instead."** Same machinery, new variable. Also wrong, and worse — the premise
     ("a channel mean is taken over the whole trajectory") is false, and clustering widened the interval while
     leaving the MEAN pooled, so `pct_vs_ref` kept dividing by a depth-averaged reference. Six designs flip
     sign against a depth-matched one; `rRNA_KO:2op` goes -7.4% -> +2.2%.

The decisive measurement, same lineages compared at a MATCHED generation index:

    growth @ reported index   gens=1 .000247804 | gens=4 .000222002 | gens=7 .000220008   ICC 0.6795
    growth @ matched  gen 0   gens=1 .000247804 | gens=4 .000251334 | gens=7 .000254435   ICC 0.0000

Exchangeable at the same index. So the remedy is STRATIFICATION, not correction — compare like with like.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("CELLARIUM_MANIFEST", "data/manifest/vmnik-compact.parquet")
os.environ.setdefault("CELLARIUM_OUT", "runs")

import pytest  # noqa: E402

from cellarium import stats  # noqa: E402


def _corpus():
    from cellarium import store
    if not store.has_manifest():
        pytest.skip("no local manifest")


# ---------------------------------------------------------------- the premise
def test_a_channel_is_the_LAST_generations_mean_not_the_trajectorys():
    """The false premise behind attempt 2, asserted against the reader so the prose cannot drift from the code."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "cellarium", "_reader_worker.py"),
               encoding="utf-8").read()
    assert "_dynamics(gs[-1])" in src, "the reader no longer takes the last generation — revisit `survey.depth`"


def test_the_corpus_agrees_that_a_channel_is_the_last_generation():
    """...and measured, not merely read: 91/91 rows match the last generation, 0/91 the trajectory mean."""
    _corpus()
    import statistics

    from cellarium import survey
    last = mean = n = 0
    for r in survey._deduped_rows(survey.CHANNELS + ["per_generation"]):
        pg, g = r.get("per_generation"), r.get("growth_rate")
        if isinstance(pg, str):
            try:
                pg = json.loads(pg)
            except Exception:
                pg = None
        vals = [p["growth"] for p in (pg or []) if isinstance(p, dict) and p.get("growth") is not None]
        if len(vals) < 2 or g is None:
            continue
        n += 1
        last += (g == vals[-1])
        mean += abs(g - statistics.fmean(vals)) < 1e-15
    if n < 5:
        pytest.skip("no multi-generation rows here")
    assert last == n and mean == 0, f"{last}/{n} match the last generation, {mean}/{n} match the trajectory mean"


# ---------------------------------------------------------------- stratification, not correction
def test_every_design_says_which_generation_it_reports():
    """The core of the fix: a design's mean must never mix runs that measured different generations."""
    _corpus()
    from cellarium import survey
    for ch, d in survey.survey_corpus(top=100)["by_channel"].items():
        for e in d["ranked"]:
            assert "generations" in e, f"{ch}/{e['design']} does not say which generation it reports"


def test_the_reference_is_depth_matched_and_it_changes_signs():
    """`pct_vs_ref` used to divide by a wildtype mean pooled over depths 1/4/7 — a BIASED denominator, not
    merely an imprecise one. These six designs flip direction once it is matched."""
    _corpus()
    from cellarium import survey
    ranked = {e["design"]: e for e in survey.survey_corpus(top=100)["by_channel"]["growth_rate"]["ranked"]}
    # five that were reported as FASTER than wild type and are in fact slower...
    for name in ("gene_knockout/KO:flgB", "gene_knockout/KO:pfkA",
                 "gene_knockout/KO:valS", "gene_knockout/KO:ymgD", "condition/plus_nitrate"):
        e = ranked.get(name)
        if e is None or e.get("pct_vs_ref") is None:
            continue
        assert e["pct_vs_ref"] < 0, f"{name} reads {e['pct_vs_ref']}% — the pooled reference is back"
    # ...and the sixth flips the other way, which is the one with scientific consequence: an rRNA knockout
    # reported as slowing growth 7.4% in fact grows 2.2% FASTER than its depth-matched control. It ran to
    # generation 3 while the pooled reference was dominated by generation-0 runs, and the model's own drift
    # (-11% growth over four generations, wild type, in the fitted condition) was being read as the knockout.
    two = ranked.get("rrna_operon_knockout/minimal|rRNA_KO:2op")
    if two:
        assert two["generations"] == 4 and two["pct_vs_ref"] > 0, two


def test_z_is_ranked_within_the_depth_stratum():
    """Ranking a design measured at generation 0 against one measured at generation 3 on a single pooled spread
    would fold the model's generation drift into the salience score itself."""
    _corpus()
    from cellarium import survey
    for d in survey.survey_corpus(top=100)["by_channel"].values():
        for e in d["ranked"]:
            if "z" in e:
                assert "z_scope" in e and f"generations={e['generations']}" in e["z_scope"]


def test_the_strata_are_disclosed_at_corpus_level():
    """The per-entry note rides with a design's row, but the ranking truncates to the top |z| and
    `wildtype/basal` sits at z=0 BY CONSTRUCTION — the design whose stratification matters most is structurally
    unable to appear. The predecessor of this test skipped silently for exactly that reason."""
    _corpus()
    from cellarium import survey
    c = survey.survey_corpus()["coverage"]
    assert c["generation_strata"], "the corpus must say which generations it holds"
    assert "wildtype/basal" in c["designs_spanning_generation_depths"]
    assert "LAST generation" in c["note"] and "STRATIFIED" in c["note"]


def test_no_design_loses_its_reference_to_stratification():
    """Stratifying is only the right call because it costs nothing here: the reference spans every depth in use.
    If a future corpus breaks that, this fails rather than silently emitting `pct_vs_ref: null`."""
    _corpus()
    from cellarium import survey
    missing = {e["design"] for d in survey.survey_corpus(top=100)["by_channel"].values()
               for e in d["ranked"] if e.get("pct_vs_ref_note")}
    assert not missing, f"designs with no depth-matched reference: {sorted(missing)[:8]}"


# ---------------------------------------------------------------- the withdrawn attempts cannot return
def test_machine_is_not_a_variance_component():
    """Withdrawn attempt 1. At a fixed depth the contributor explains nothing."""
    _corpus()
    from cellarium import survey
    rows = [r for r in survey._deduped_rows(survey.CHANNELS)
            if survey.design_key(r) == "wildtype/basal" and r.get("reportable") and survey.depth(r) == 1]
    if len({survey._machine(r) for r in rows}) < 2 or len(rows) < 6:
        pytest.skip("no depth-matched multi-contributor subset here")
    for ch in ("growth_rate", "ppgpp_conc", "ribosome_conc"):
        v = [r[ch] for r in rows if r.get(ch) is not None]
        de = stats.design_effect(v, [survey._machine(r) for r in rows if r.get(ch) is not None])
        assert de is None or de["icc"] < 0.05, f"machine ICC on {ch} is {de['icc']}"


def test_survey_does_not_cluster_on_depth():
    """Withdrawn attempt 2. A random-effects widening is the wrong estimator for a recorded fixed effect, and it
    left the mean biased while looking like a correction."""
    _corpus()
    from cellarium import survey
    s = survey.survey_corpus(top=100)
    stale = [e["design"] for d in s["by_channel"].values() for e in d["ranked"] if "cluster" in e]
    assert not stale, f"a clustered interval is back on {stale[:5]}"
    assert "designs_mixing_generation_depth" not in s["coverage"]


# ---------------------------------------------------------------- one code path for every comparison tool
def test_disconfirm_and_survey_report_the_same_interval():
    """`disconfirm` exists to CHALLENGE a claim, and it was reporting an interval 5.5x narrower than the tool it
    checks — its own row source, no `reportable` filter, and a design key built from the nullable `condition`."""
    _corpus()
    from cellarium import rigor, survey
    d = rigor.disconfirm("condition/acetate", "wildtype/basal", "ribosome_conc")
    if "error" in d:
        pytest.skip(d["error"])
    e = next((e for e in survey.survey_corpus(top=100)["by_channel"]["ribosome_conc"]["ranked"]
              if e["design"] == "condition/acetate"), None)
    if not e:
        pytest.skip("acetate not ranked")
    assert d["target"]["n_seeds"] == e["n"], "the two tools disagree on how many seeds there are"
    assert abs(d["target"]["ci95"] - e["ci95"]) < 1e-9, "the two tools disagree on the interval"
    assert d["generations"] == e["generations"]


def test_the_comparison_tools_exclude_crashed_runs():
    """`differential` never applied the `reportable` filter, so its Welch tests averaged in dead cells."""
    _corpus()
    from cellarium import survey
    rows, _ = survey.analysis_rows()
    assert rows and all(r.get("reportable") for r in rows)


def test_differential_gives_a_soft_quantified_depth_signal_not_a_verdict():
    """ADR-1: a depth mismatch is a SIGNAL FOR EXPLORATION, not a verdict. The note must (a) never gate or call
    the comparison invalid, (b) carry a data-grounded magnitude — how much the reference itself drifts over the
    gap — so a 1% confound reads differently from a 30% one, and (c) suggest deepening the shallower case."""
    _corpus()
    from cellarium import differential
    r = differential.summary("condition/acetate", "wildtype/basal")   # acetate gen1 vs a reference spanning 1/4/7
    tested = [m for m in r["ranked"] if m.get("p_value") is not None]
    if not tested:
        pytest.skip("no tested movers")
    assert not any("clustered_caveat" in m or "depth_mismatch" in m for m in tested), "old hard framing is back"
    notes = [m["depth_note"] for m in tested if m.get("depth_note")]
    assert notes, "a depth-mismatched comparison must carry a depth_note"
    n = notes[0]
    assert "not a verdict" in n and "invalid" not in n.lower(), "the signal must not be framed as a verdict"
    assert "consider running" in n, "it must suggest deepening the shallower case"
    assert "%" in n, "it must quantify the reference's own drift over the gap, not just assert a gap"


def test_the_depth_drift_number_is_computed_from_the_reference_trajectory():
    """The magnitude must be MEASURED (the reference's per-generation growth curve), not a hardcoded constant, or
    it stops tracking the data the first time the corpus changes."""
    _corpus()
    from cellarium import differential
    traj = differential._reference_trajectory()
    if len(traj) < 2:
        pytest.skip("reference has a single generation here")
    # depth 1 reports generation 0, depth 4 reports generation 3 — a real, nonzero drift on this corpus
    d = differential._reference_drift_pct(1, 4)
    assert d is not None and abs(d) > 1.0, f"reference drift over gens 0->3 reads {d}% — expected a real move"


# ---------------------------------------------------------------- dedupe: the (id, path) PAIR
def test_the_dedup_key_drops_reindexed_duplicates_but_keeps_distinct_runs():
    """Neither half of the key is unique alone. `simout_path` repeats across contributors (a run directory is
    named from variant+seed), and `id` repeats across crash rows (measured on this corpus: 12 ids covering 48
    crash rows). The pair separates them; either half alone destroys data.

    This used to assert `deduped < raw` — i.e. that the read-time dedup still had superseded rows to remove.
    That premise died when `manifest.compact()` (manifest.py:432) became AUTOMATIC after every re-index
    (manifest.py:999): compaction writes exactly the deduped set, so a healthy corpus now holds ZERO duplicate
    keys and `deduped == raw` is the CORRECT post-condition, not a regression. Asserting on corpus dirtiness
    tested our housekeeping hygiene, not the key. So the collapsing behaviour is now proven by CONSTRUCTING a
    re-indexed duplicate, which is deterministic and independent of what the corpus happens to contain."""
    _corpus()
    import duckdb

    from cellarium import manifest, survey
    con = duckdb.connect()
    src = f"read_parquet('{survey.MANIFEST_GLOB}', union_by_name=true)"
    f = f"(SELECT * FROM {src} {manifest.DEDUP_QUALIFY})"
    # Two rows that are the SAME run re-indexed by a contributor whose run-root is absolute + backslashed —
    # exactly the spelling difference that let 9 duplicates into the corpus before _NORM_PATH existed.
    dup_q = f"(SELECT * FROM (VALUES (?,?,1.0),(?,?,2.0)) t(id, simout_path, ts) {manifest.DEDUP_QUALIFY})"
    try:
        raw = con.execute(f"SELECT count(*) FROM {src}").fetchone()[0]
        keys = con.execute(f"SELECT count(DISTINCT {manifest.DEDUP_KEY}) FROM {src}").fetchone()[0]
        n = con.execute(f"SELECT count(*) FROM {f}").fetchone()[0]
        crash = con.execute(f"SELECT count(*) FROM {f} WHERE id LIKE '%_crash'").fetchone()[0]
        by_id = con.execute(f"SELECT count(DISTINCT id) FROM {f}").fetchone()[0]
        by_path = con.execute(f"SELECT count(DISTINCT {manifest._NORM_PATH}) FROM {f}").fetchone()[0]
        rid, rpath = con.execute(
            f"SELECT id, simout_path FROM {src} WHERE id IS NOT NULL AND simout_path LIKE 'runs/%' LIMIT 1"
        ).fetchone()
        reindexed = "C:\\dev\\elsewhere\\" + rpath.replace("/", "\\")
        collapsed = con.execute(f"SELECT ts FROM {dup_q}", [rid, rpath, rid, reindexed]).fetchall()
        distinct = con.execute(f"SELECT count(*) FROM {dup_q}", [rid, rpath, rid, "runs/other/000001"]).fetchone()[0]
    finally:
        con.close()
    # The key collapses a re-indexed duplicate to one row, and the LATEST ts wins.
    assert len(collapsed) == 1, f"a re-indexed duplicate survived as {len(collapsed)} rows — the key stopped matching"
    assert collapsed[0][0] == 2.0, "the superseded (older) row won — ORDER BY ts DESC is broken"
    # ...but two genuinely different run directories under one id stay separate.
    assert distinct == 2, "two distinct runs sharing an id were collapsed — the path half of the key is dead"
    # Dedup keeps exactly one row per key, and the compacted corpus is already one-row-per-key.
    assert n == keys, f"dedup returned {n} rows for {keys} distinct keys"
    assert n == raw, f"the corpus holds {raw - n} superseded rows — compact() should have removed them"
    # Neither half of the key is unique on the real corpus: deduping by either alone would destroy runs.
    assert by_id < n, "id is unique here, so this corpus can no longer prove the pair is needed"
    assert by_path < n, "simout_path is unique here, so this corpus can no longer prove the pair is needed"
    assert crash >= 8, f"only {crash} crash rows survive"


def test_a_crash_id_names_its_design():
    """The collision's cause: `<perturbation>_<seed>_crash` carries no variant, so all ten kin_w doses at seed 1
    shared one id. Fixed at the generator; the legacy rows survive on the (id, path) pair."""
    import inspect

    from cellarium import manifest
    src = inspect.getsource(manifest._crash_row)
    assert "_design_tag(design)" in src and "_crash" in src


def test_the_sql_and_python_path_normalisers_agree():
    """`_portable_runpath` (write side) and `DEDUP_KEY` (read side) must normalise identically, or a row written
    under one convention never dedupes against one written under the other — how the 9 duplicates got in."""
    import duckdb

    from cellarium import manifest
    con = duckdb.connect()
    try:
        for p in ("/Users/fmenol/Downloads/cellarium/runs/cellarium/wildtype_199333/000013",
                  "runs/cellarium/wildtype_199333/000013",
                  r"C:\dev\anthropic_hackathon\runs\cellarium\wildtype_199333\000013"):
            got = con.execute(f"SELECT {manifest._NORM_PATH} FROM (SELECT ? AS simout_path)", [p]).fetchone()[0]
            assert got == manifest._portable_runpath(p), f"{p!r}: SQL {got!r} != Python"
    finally:
        con.close()


# ---------------------------------------------------------------- the decomposition itself (pure)
_UNBAL = ([1.0 + 0.001 * i for i in range(28)] + [5.0, 5.01, 5.0, 4.99] + [9.0, 9.01],
          ["a"] * 28 + ["b"] * 4 + ["c"] * 2)


def test_deff_uses_the_same_mean_cluster_size_as_the_icc():
    """The bug behind the published '6.6x'. Hartley's m0 was computed for the variance component and then the
    plain n/k used for DEFF — on sizes [28,4,2] the two answers differ by 2.7x."""
    de = stats.design_effect(*_UNBAL)
    assert abs(de["deff"] - (1.0 + (de["m0"] - 1.0) * de["icc"])) < 1e-9
    assert de["deff"] < 1.0 + (de["n"] / de["n_clusters"] - 1.0) * de["icc"], "n/k is back in DEFF"


def test_df_never_exceeds_the_number_of_clusters_minus_one():
    """Between-cluster variance rests on k-1 df however many observations sit inside the clusters. `n_eff - 1`
    claimed df=14 against k-1=2 on this corpus — 8 of 9 channels too narrow."""
    _hw, info = stats.t95_halfwidth_clustered(*_UNBAL)
    assert info["df"] <= info["n_clusters"] - 1 == info["df_cap"]


def test_dropping_one_row_does_not_swing_the_estimate_threefold():
    """`design_effect` drops singleton clusters; the caller took its standard error over the UNDROPPED list, so
    the DEFF described one sample and the SE another. One row in or out moved the half-width 3.2x."""
    vals = [1.0, 1.1, 0.9, 1.05, 5.0, 5.1, 4.9, 9.0, 9.1]
    clus = ["a"] * 4 + ["b"] * 3 + ["c"] * 2
    hw_full, _ = stats.t95_halfwidth_clustered(vals, clus)
    hw_drop, _ = stats.t95_halfwidth_clustered(vals[:-1], clus[:-1])   # 'c' becomes a singleton and is dropped
    assert hw_full and hw_drop, (hw_full, hw_drop)
    assert 0.4 < hw_drop / hw_full < 2.5, f"{hw_full} -> {hw_drop} is a cliff, not an estimate"


def test_the_unreliable_flag_is_present_on_every_path():
    """It was omitted from the deff<=1 return, so `info.get('unreliable')` gave None — neither True nor False."""
    # three clusters, no effect -> deff <= 1, the early-return path
    hw, info = stats.t95_halfwidth_clustered([1.0, 1.1, 0.9, 0.95, 1.05, 1.0, 1.02, 0.98, 1.0],
                                             ["a"] * 3 + ["b"] * 3 + ["c"] * 3)
    assert hw == stats.t95_halfwidth([1.0, 1.1, 0.9, 0.95, 1.05, 1.0, 1.02, 0.98, 1.0])
    assert info is not None and info["unreliable"] is False and "df" in info
    # ...and two clusters on the same path is unreliable=True, not None
    _hw2, i2 = stats.t95_halfwidth_clustered([1.0, 1.1, 0.9, 0.95, 1.05, 1.0], ["a"] * 3 + ["b"] * 3)
    assert i2["unreliable"] is True


def test_a_strong_cluster_effect_still_widens_and_shrinks_effective_n():
    """The machinery is retained and must still work — it is simply not applied to depth."""
    vals = [1.00, 1.01, 0.99, 1.00, 5.00, 5.01, 4.99, 5.00]
    clus = ["a"] * 4 + ["b"] * 4
    de = stats.design_effect(vals, clus)
    assert de["icc"] > 0.9 and de["n_eff"] < 3, de
    hw, info = stats.t95_halfwidth_clustered(vals, clus)
    assert hw > stats.t95_halfwidth(vals) and info["unreliable"] is True


def test_negative_variance_components_clamp_to_zero():
    de = stats.design_effect([1.0, 5.0, 1.0, 5.0, 1.0, 5.0], ["a", "a", "b", "b", "c", "c"])
    assert de["icc"] == 0.0 and de["sd_between"] == 0.0


def test_it_degrades_rather_than_raising():
    assert stats.design_effect([1.0], ["a"]) is None
    assert stats.design_effect([1.0, 2.0], ["a", "b"]) is None      # 1 point per cluster: undecomposable
    assert stats.t95_halfwidth_clustered([1.0], ["a"]) == (None, None)
