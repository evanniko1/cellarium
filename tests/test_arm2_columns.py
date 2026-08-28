"""The five provenance columns ARM-2 added, and the one thing they must not do (ARM-2).

`kb_sha256` pins the PARAMETERS a row was produced under. Nothing pinned the CODE, the CONTAINER, the
reconstruction INPUTS, when the fit was built, or the FLAGS — so two rows could agree on every recorded column
and still be different experiments. The phnE1 investigation had to rule that out by hand, by reproducing a run
bitwise over 2,529 timesteps.

The trap these tests mostly guard is the opposite of the obvious one. A column that is NULL on all 366 existing
rows cannot partition anything, and `arm_of` coalesces None to '?', so a NULL on both sides compares EQUAL.
Promoting one of these into ARM_KEYS today would manufacture a single enormous "unknown" arm that silently
claims agreement — the exact failure ARM-1 exists to prevent, reached from the other direction.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.cellarium import corpus_schema, manifest, provenance, runner  # noqa: E402


def test_model_sha_is_not_a_bare_commit():
    """A git sha alone would compare EQUAL across two different overlay states.

    This tree is public wcEcoli plus the 45 files in model_overlay/. Storing only the upstream commit would say
    "same code" when the code differs, which is worse than storing nothing.
    """
    m = provenance.model_provenance()
    if not m.get("model_sha256"):
        pytest.skip("model_overlay/MANIFEST.json unreadable in this environment")
    assert m["model_upstream_commit"], "the upstream commit is half the identity and must be recorded"
    assert m["model_sha256"].startswith(m["model_upstream_commit"] + "+"), (
        "model_sha256 must carry the upstream commit AND an overlay digest, not one of the two")
    assert m["model_sha256"] != m["model_upstream_commit"]
    assert m["model_overlay_files"] and m["model_overlay_files"] > 0


def test_model_sha_moves_when_the_overlay_moves():
    """The point of the composite: change one overlay file's hash and the identity must change."""
    import hashlib
    import json
    real = json.loads(Path("model_overlay/MANIFEST.json").read_text(encoding="utf-8"))
    shipped = sorted((str(f.get("path")), str(f.get("overlay_sha256") or ""))
                     for f in (real.get("files") or []) if f.get("status") == "ship")
    if len(shipped) < 2:
        pytest.skip("overlay manifest has too few shipped files to perturb")
    def digest(pairs):
        return hashlib.sha256("\n".join(f"{p}:{s}" for p, s in pairs).encode()).hexdigest()[:16]

    moved = sorted([(shipped[0][0], "0" * 64)] + shipped[1:])
    assert digest(shipped) != digest(moved), "one changed overlay file left the model identity unchanged"


def test_unknown_is_recorded_as_unknown():
    """A row built without launching anything has genuinely unknown flags; it must not read as 'no flags'."""
    runner._EXEC_LOCAL.argv = None
    assert runner.last_argv() is None
    runner._EXEC_LOCAL.argv = ["runscripts/manual/runSim.py", "cellarium", "--seed", "0"]
    assert runner.last_argv() == "runscripts/manual/runSim.py cellarium --seed 0"
    runner._EXEC_LOCAL.argv = None


def test_a_flat_row_carries_all_five():
    from src.cellarium.model import Design, SimResult
    rec = SimResult(id="probe_0", label="probe·basal·s0",
                    design=Design(perturbation="gene_knockout", condition="basal"))
    row = manifest._flat_row(rec, 0, Path("runs/cellarium/probe_0/000000"), sim_path="cellarium")
    for col in corpus_schema.ARM2_COLUMNS + ("model_upstream_commit",):
        assert col in row, "ARM-2 column %r is not written to the manifest row" % col


def test_a_reindexed_row_does_not_claim_todays_code_image_or_flat_files():
    """`record_existing` indexes runs ALREADY ON DISK. Stamping there would date a July run to today.

    `model_sha256`, `image_digest` and `reconstruction_sha` describe WHAT RAN A SIMULATION, and a re-index runs
    nothing. The guard is `runner.last_argv()`, so a row carries the whole "what executed this" set or none of
    it — a row half-described by the current process is worse than one that says nothing.
    """
    from src.cellarium.model import Design, SimResult
    rec = SimResult(id="probe_0", label="probe·basal·s0",
                    design=Design(perturbation="gene_knockout", condition="basal"))

    def build(argv):
        runner._EXEC_LOCAL.argv = argv
        manifest._RUN_PROV_CACHE.clear()
        return manifest._flat_row(rec, 0, Path("runs/cellarium/probe_0/000000"), sim_path="cellarium")

    try:
        reindexed = build(None)
        for col in ("model_sha256", "image_digest", "reconstruction_sha", "runsim_argv"):
            assert reindexed.get(col) is None, (
                "%r was stamped on a row whose run this process never executed — that asserts the run used "
                "today's code/container, which is false provenance, not a missing value" % col)

        ran = build(["runscripts/manual/runSim.py", "cellarium", "--seed", "0"])
        assert ran.get("runsim_argv"), "a row from an actual run must record its flags"
        # Each column is then populated iff it is KNOWABLE, which is not the same as all-or-nothing:
        # `model_sha256` reads the overlay manifest and is known in native mode too, while `image_digest` and
        # `reconstruction_sha` need a container and are honestly None without one. What must never happen is
        # a value appearing on the re-index path above.
        if runner.WCECOLI_DOCKER:      # the constant the run itself used, not the environment behind it
            assert ran.get("image_digest"), "a Dockered run must record which image it executed"
        else:
            assert ran.get("image_digest") is None, "no container ran, so no digest may be claimed"
    finally:
        runner._EXEC_LOCAL.argv = None
        manifest._RUN_PROV_CACHE.clear()


def test_append_shard_keeps_a_column_that_is_absent_from_the_first_row():
    """`pa.Table.from_pylist` infers its schema from the FIRST ROW ONLY and silently drops later keys.

    Found while backfilling `parca_ts`: the backfill stamps only rows whose kb is provably their own, so the
    first row did not carry the key, the column never reached the parquet, and the write still reported 279
    rows backfilled. A write that loses a column and returns success is the worst shape a data bug can take.

    Existing callers survived by accident — DuckDB's `union_by_name` returns every key on every row, so the
    first row's schema was already complete. This pins the property so the accident is not load-bearing.
    """
    import shutil
    import tempfile

    import duckdb
    d = Path(tempfile.mkdtemp())
    try:
        p = manifest.append_shard([{"a": 1}, {"a": 2, "b": 99}, {"c": "x"}], name="probe", directory=d)
        # `.df()` requires PANDAS, which is deliberately NOT a dependency here — the core stays pandas- and
        # scipy-free and they arrive only through the opt-in `fba`/`rnaseq` extras. It passed locally because
        # this developer's venv has cobra installed, and failed in CI on every commit for days with
        # "'pandas' is required for this operation but it was not installed". Arrow needs no extra.
        tbl = duckdb.connect().execute("SELECT * FROM read_parquet('%s')" % p.as_posix()).fetch_arrow_table()
        cols, got = tbl.column_names, tbl.to_pylist()
        assert sorted(cols) == ["a", "b", "c"], (
            "append_shard dropped %s — a key present on a later row did not survive the write"
            % sorted({"a", "b", "c"} - set(cols)))
        assert len(got) == 3
        assert got[1]["b"] == 99, "the value was lost even though the column survived"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_parca_ts_is_stamped_only_where_the_kb_is_provably_the_rows_own():
    """A campaign path is reused across rebuilds, so 'the kb at this path' is not 'the kb this row used'."""
    from src.cellarium import survey
    rows, _ = survey.analysis_rows(arm="all")
    if not rows:
        pytest.skip("corpus unreadable in this environment")
    stamped = [r for r in rows if r.get("parca_ts")]
    if not stamped:
        pytest.skip("parca_ts not backfilled in this checkout")
    # The invariant is about LOCAL consistency: a stamped row must agree with the kb that is on disk NOW.
    # Where there is no run tree at all — CI clones the repo, and `runs/` is gitignored — there is no kb to
    # be consistent with, and `kb_sha_for_run` returns None for every row. That is an ABSENCE, not a
    # violation, and asserting through it failed CI on every commit for days with "the row would assert a
    # build time for a knowledge base that is no longer there". Skipping is the honest reading; the check
    # still runs wherever a run tree exists.
    if not any(manifest.kb_sha_for_run(r.get("simout_path")) for r in stamped):
        pytest.skip("no local run tree — no kb on disk for a stamped row to be consistent with")
    # Resolved ROOT-AWARE, matching the backfill: `_sim_path_of` drops the output root and would compare a
    # `runs_seed_aars/cellarium/` row against `runs/cellarium/kb` (KB-ROOT-1).
    for r in stamped:
        assert manifest.kb_sha_for_run(r.get("simout_path")) == r.get("kb_sha256"), (
            "row %s carries parca_ts but its kb_sha256 (%s) is not the kb now at %s (%s) — the row would "
            "assert a build time for a knowledge base that is no longer there"
            % (r.get("id"), str(r.get("kb_sha256"))[:8], manifest.campaign_root_of(r.get("simout_path")),
               str(manifest.kb_sha_for_run(r.get("simout_path")))[:8]))


# ---------------------------------------------------------------------------------------------------------
# The NULL hazard.
# ---------------------------------------------------------------------------------------------------------

def test_the_new_columns_are_not_arm_keys_yet():
    """Promoting a NULL-everywhere column would manufacture one 'unknown' arm that claims agreement."""
    for col in corpus_schema.ARM2_COLUMNS:
        assert col not in corpus_schema.ARM_KEYS, (
            "%r joined ARM_KEYS while the existing corpus is NULL on it. arm_of coalesces None to '?', so "
            "every historical row would compare EQUAL on this key — that is manufactured agreement, not a "
            "partition. Promote it once the rows being compared actually carry it." % col)


def test_a_conflict_is_detected_only_between_two_KNOWN_values():
    base = {"kb_sha256": "k", "operons": "on", "elongation_model": "steady_state"}
    same_arm_diff_code = [{**base, "model_sha256": "a4497e17+AAA"}, {**base, "model_sha256": "a4497e17+BBB"}]
    hits = corpus_schema.arm_conflicts(same_arm_diff_code)
    assert len(hits) == 1 and hits[0]["column"] == "model_sha256" and hits[0]["n_distinct"] == 2, (
        "two rows sharing an arm under different model source were not flagged — nothing else in the "
        "repository would say they are incomparable")

    # A NULL is UNKNOWN. Neither agreement nor difference.
    assert corpus_schema.arm_conflicts([{**base, "model_sha256": None},
                                        {**base, "model_sha256": None}]) == []
    assert corpus_schema.arm_conflicts([{**base, "model_sha256": "a4497e17+AAA"},
                                        {**base, "model_sha256": None}]) == [], (
        "a missing value was read as a mismatch — that flags the whole pre-ARM-2 corpus against every new row")

    # Different arms are already separated by ARM_KEYS; this check is only about arms the keys MISS.
    assert corpus_schema.arm_conflicts([{**base, "model_sha256": "a4497e17+AAA"},
                                        {**base, "kb_sha256": "other", "model_sha256": "a4497e17+BBB"}]) == []


def test_the_read_layer_projects_the_new_columns():
    """Without this the conflict check reports "no conflicts" whatever the data says.

    A detector that never receives the column is indistinguishable from a clean corpus, and the test below
    would pass for the wrong reason. That is exactly how this was nearly shipped: the columns were written to
    the manifest and left out of `survey._deduped_rows`' projection, so `arm_conflicts` saw None on every row.
    """
    from src.cellarium import survey
    rows, _ = survey.analysis_rows(arm="all")
    if not rows:
        pytest.skip("corpus unreadable in this environment")
    for col in corpus_schema.ARM2_COLUMNS:
        assert col in rows[0], (
            "%r is not projected by the read layer, so arm_conflicts can never see it and reports a clean "
            "corpus unconditionally" % col)


def test_the_live_corpus_has_no_conflict_yet():
    """Pre-migration every ARM-2 column is NULL, so this must be empty — and say so if it ever is not."""
    from src.cellarium import survey
    rows, _ = survey.analysis_rows(arm="all")
    if not rows:
        pytest.skip("corpus unreadable in this environment")
    hits = corpus_schema.arm_conflicts(rows)
    assert not hits, ("rows sharing an arm disagree on %s — the arm keys no longer separate this corpus"
                      % ", ".join(sorted({h["column"] for h in hits})))


def test_the_detector_fires_on_real_projected_rows():
    """End-to-end: stamp two live rows in one arm with different model source and confirm it is caught."""
    from src.cellarium import survey
    rows, _ = survey.analysis_rows()          # a single arm by construction
    if len(rows) < 2:
        pytest.skip("corpus unreadable in this environment")
    a, b = dict(rows[0]), dict(rows[1])
    a["model_sha256"], b["model_sha256"] = "a4497e17+AAA", "a4497e17+BBB"
    hits = corpus_schema.arm_conflicts([a, b])
    assert len(hits) == 1 and hits[0]["column"] == "model_sha256", (
        "two rows of the SAME arm under different model source were not flagged on real corpus rows")
    assert corpus_schema.arm_conflicts([dict(rows[0]), dict(rows[1])]) == []


# ---------------------------------------------------------------------------------------------------------
# The detector has to be CALLED. A check nobody runs is the failure TOMB-1 was about, one level up:
# `arm_conflicts` had no caller when it was written, so it would have reported nothing forever while
# looking like a safeguard.
# ---------------------------------------------------------------------------------------------------------

def test_the_read_boundary_actually_calls_the_detector():
    """Not "arm_conflicts works" — "analysis_rows runs it and surfaces what it found"."""
    from src.cellarium import survey
    rows, _ = survey.analysis_rows()
    if not rows:
        pytest.skip("corpus unreadable in this environment")
    assert "arm_incomplete" not in survey.last_arm_note(), (
        "the live corpus reports an incomplete arm; four of the five columns are NULL everywhere, so this "
        "should be empty until two runs from different model source land in one arm")

    fake = [{"column": "model_sha256", "n_distinct": 2, "arm": {}, "values": ["a", "b"], "why": "probe"}]
    orig = corpus_schema.arm_conflicts
    corpus_schema.arm_conflicts = lambda rows, columns=None: fake
    try:
        survey.analysis_rows()
        note = survey.last_arm_note()
    finally:
        corpus_schema.arm_conflicts = orig
    assert note.get("arm_incomplete") == fake, (
        "analysis_rows did not surface a conflict — the detector is wired but its result is discarded, which "
        "is indistinguishable from not calling it")
    assert "model_sha256" in note.get("why_incomplete", "")
    assert note.get("arm"), "a conflict was reported without naming the arm it is in"


def test_the_arms_artefact_is_generated_and_separates_the_two_dates():
    """`kb built` (parca_ts) and `first run` are different facts; the second is only a lower bound on the first."""
    import re
    from pathlib import Path

    from src.cellarium import corpus_schema as cs
    body = cs.report()
    assert "| kb built | first run |" in body, "the arms table lost the causal-ordering column"
    assert "## Provenance coverage (ARM-2)" in body
    for col in cs.ARM2_COLUMNS:
        assert "`%s`" % col in body, "%s is not reported in the generated artefact" % col
    p = Path(cs.REPORT_PATH)
    if p.exists():
        on_disk = p.read_text(encoding="utf-8")
        assert on_disk.splitlines()[0] == body.splitlines()[0]
        stale = [ln for ln in on_disk.splitlines() if re.match(r"^\| `[0-9a-f]{8}` \|", ln)]
        assert stale, "the generated artefact carries no arm rows — regenerate with `--write`"


# --------------------------------------------------------------------- argv is not arm-invariant, found by P1

_ARM = {"kb_sha256": "k", "operons": "on", "elongation_model": "kinetic"}


def _argv_conflicts(a, b):
    return corpus_schema.arm_conflicts([{**_ARM, "runsim_argv": a}, {**_ARM, "runsim_argv": b}])


def test_seeds_and_depth_do_not_split_an_arm():
    """An arm is one code + one fit across MANY seeds -- that is what makes seeds buy power instead of
    splitting the corpus. CORPUS-REBUILD-1 P1 wrote the first rows carrying argv and the detector reported 6
    distinct values for 6 correct rows, differing only by `--seed 0/1/2/3`."""
    assert not _argv_conflicts(
        "runSim.py c --variant wildtype 1 1 --seed 0 --generations 3 --kinetic-trna-charging",
        "runSim.py c --variant wildtype 1 1 --seed 9 --generations 7 --kinetic-trna-charging")


def test_two_designs_in_one_arm_do_not_conflict():
    """`wildtype/basal` and `gene_knockout/KO:argS` share kb + operons + elongation. Comparing them IS the
    corpus's purpose, so `--variant` cannot be arm-invariant."""
    assert not _argv_conflicts(
        "runSim.py c --variant wildtype 184115 184115 --seed 0 --kinetic-trna-charging",
        "runSim.py c --variant gene_knockout 644 644 --seed 0 --kinetic-trna-charging")


def test_a_multi_ko_gene_set_is_a_design_not_an_arm():
    assert not _argv_conflicts(
        "runSim.py c --variant multi_gene_knockout 0 0 --multi-ko-indices 12 44 --seed 0",
        "runSim.py c --variant multi_gene_knockout 0 0 --multi-ko-indices 7 --seed 1")


def test_a_GLOBAL_flag_added_to_half_a_campaign_still_fires():
    """The reason the column exists: a flag added later would split an arm invisibly, and nothing else records
    the flags. Normalising the per-row and per-design parts must not cost this."""
    hits = _argv_conflicts(
        "runSim.py c --variant wildtype 1 1 --seed 0 --kinetic-trna-charging",
        "runSim.py c --variant wildtype 1 1 --seed 1 --kinetic-trna-charging --no-ppgpp-regulation")
    assert len(hits) == 1 and hits[0]["column"] == "runsim_argv"
