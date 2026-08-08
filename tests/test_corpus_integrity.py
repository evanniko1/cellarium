"""Standing guard against IDENTITY DRIFT — run in CI, not once.

Every integrity bug found in this corpus was one thing wearing different clothes: **a design's recorded identity
drifting from what it actually is.**

  * an amino-acid UPSHIFT and a DOWNSHIFT merged into one cell, and were averaged as "4 seeds of one design",
    because both stored `condition = NULL` and a reader keyed on that column;
  * a `gltX` knockout was filed as a `basal` CONTROL because its provenance file was missing at index time and
    the tag silently fell back to `condition`;
  * an entire `valS` design sat readable on disk, unindexed, and was therefore invisible to every query;
  * 1,554 gene names turned out to be aliases of a design named after a different gene, so two of them requested
    as independent knockouts would have been a duplicate posing as a replicate;
  * 41 rows use a second labelling convention and resolved correctly only by luck.

None of these announce themselves. Each produces a **plausible number computed over the wrong set**, which is
the worst failure a corpus can have — and the risk grows with the corpus, because a human stops being able to
eyeball 60 designs long before 6,000.

These tests are cheap and they fail loudly. They are the reason the next such bug gets caught in CI instead of
in a manuscript.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("CELLARIUM_MANIFEST", "data/manifest/vmnik-compact.parquet")
os.environ.setdefault("CELLARIUM_OUT", "runs")

import pytest  # noqa: E402

from cellarium import manifest, survey  # noqa: E402


def _rows():
    from cellarium import store
    if not store.has_manifest():
        pytest.skip("no local manifest")
    return store.list_results()


def test_the_corpus_passes_every_drift_invariant():
    """The headline guard. `check_disk=False` because `runs/` is not committed — the disk half is meaningful
    only on a machine that holds the corpus, and is asserted separately below."""
    _rows()
    res = manifest.integrity_check(check_disk=False)
    assert res["ok"], "identity drift detected:\n" + "\n".join(
        f"  [{v['invariant']}] {v['message']} (n={v['n']}) e.g. {v['examples'][:3]} -> {v['fix']}"
        for v in res["violations"])


def test_no_design_key_is_built_from_a_nullable_field():
    """D3 in isolation, because this one caused the worst bug: `timeline` rows store `condition = NULL`, so
    keying on that column merged an upshift with a downshift and averaged opposite experiments together."""
    for r in _rows():
        k = survey.design_key(r)
        assert not k.endswith("/None"), f"{r.get('label')} keys as {k} — a null is being used as identity"
        assert survey.design_tag(r), f"{r.get('label')} has no recoverable tag"


def test_the_two_nutrient_shifts_never_merge_again():
    """The canonical over-merge, kept as its own test because it is the one that actually happened: an amino-acid
    upshift and a downshift both stored `condition = NULL`, so a reader keying on that column pooled them and
    averaged opposite experiments as "4 seeds of one design".

    Note what does NOT work as a general merge detector, since both were tried and both were wrong:
      * seed CONTIGUITY — `kin_w:1e-4` legitimately holds seeds [1,2,3] because seed 0 crashed;
      * duplicate (design, seed) — legitimate here. `wildtype/basal` seed 0 exists at generations 1, 4 and 7,
        and the channel values DIFFER — but that is because a channel is the LAST generation's mean, so those
        runs measure different generations of a lineage (see `survey.depth`), and they are genuine independent
        replicates at their respective depths, not one run counted thrice. (An EARLIER version of this comment
        attributed the difference to cross-machine non-determinism; that was WELL-6x, withdrawn.)
    What does catch the real bug is D3: a key must never be built from a nullable column."""
    rows = _rows()
    by_key: dict = {}
    for r in rows:
        by_key.setdefault(survey.design_key(r), set()).add(r.get("seed"))
    tl = sorted(k for k in by_key if k.startswith("timeline/"))
    if tl:
        assert len(tl) >= 2, f"the nutrient shifts merged again: {tl}"
        assert not any(k.endswith("/None") for k in tl)
        assert any("0 minimal," in k for k in tl) and any("0 minimal_plus" in k for k in tl), (
            f"both shift directions must be present and distinct: {tl}")


def test_alias_designs_cannot_be_counted_as_replicates():
    """D4. `KO:pheS` and `KO:thrS` are ONE run; treating them as two independent knockouts inflates n."""
    from cellarium import factors
    keys = sorted({survey.design_key(r) for r in _rows()})
    dupes = factors.dedupe(keys).get("duplicates") or {}
    assert not dupes, f"designs that are secretly the same experiment: {dupes}"


def test_a_knockout_design_always_names_a_gene():
    """D5. A `gene_knockout` tagged `basal` has no resolvable identity — that is exactly how the gltX run was
    filed as a control."""
    bad = sorted({survey.design_key(r) for r in _rows()
                  if "knockout" in str(r.get("perturbation") or "") and survey.design_tag(r) == "basal"})
    assert not bad, f"knockout designs with no gene in their identity: {bad}"


def test_every_row_can_say_which_knowledge_base_produced_it():
    """D6. Knockout semantics depend entirely on the operon mode, so a row that cannot name its kb cannot be
    interpreted — and 'operons on' was filesystem inference until this column existed."""
    import duckdb

    from cellarium import manifest
    con = duckdb.connect()
    try:
        n = con.execute(
            "SELECT count(*) FROM ("
            "  SELECT kb_sha256 FROM read_parquet('data/manifest/*.parquet', union_by_name=true)"
            f"  {manifest.DEDUP_QUALIFY}"
            ") WHERE kb_sha256 IS NULL"
        ).fetchone()[0]
    finally:
        con.close()
    assert n == 0, f"{n} rows carry no kb provenance — run manifest.backfill_kb_provenance(dry_run=False)"


def test_the_sql_and_python_normalisers_agree():
    """The dedup key normalises the run path in SQL (`manifest._NORM_PATH`); `_portable_runpath` normalises it in
    Python at WRITE time. If they disagree, a row written under one convention will not dedupe against a row
    written under the other — exactly how the 9 duplicates got in. Asserted over EVERY corpus path AND
    adversarial edge spellings, because the first regex matched `runs` as a substring (`myruns/foo` -> `runs/foo`)
    and no test caught it — the divergence was latent only because no live path happened to contain such a
    segment. This test is what the comment at manifest.py:53 promises."""
    import duckdb

    from cellarium import manifest
    con = duckdb.connect()

    def sql_norm(p):
        return con.execute(f"SELECT {manifest._NORM_PATH} FROM (SELECT ? AS simout_path)", [p]).fetchone()[0]

    try:
        live = [r[0] for r in con.execute(
            "SELECT DISTINCT simout_path FROM read_parquet('data/manifest/*.parquet', union_by_name=true) "
            "WHERE simout_path IS NOT NULL").fetchall()]
        adversarial = [
            "myruns/foo/bar", "/home/x/cellarium_runs/runs/cellarium/wt/000000", "prefix_runs2/x/000000",
            "x/runsxyz/000000", "foo/runs", "runs/foo/runs/bar", "runs_2024/cellarium/wt/000000",
            "runs/cellarium/wt/000000", "/Users/fmenol/Downloads/cellarium/runs/cellarium/wt/000000",
            r"C:\dev\anthropic_hackathon\runs\cellarium\wt\000000", "no/runs/here/deep", "justapath/000000"]
        bad = [p for p in live + adversarial if sql_norm(p) != manifest._portable_runpath(p)]
    finally:
        con.close()
    assert not bad, ("SQL and Python normalisers disagree on:\n" + "\n".join(
        f"  {p!r}: SQL {sql_norm(p)!r} != PY {manifest._portable_runpath(p)!r}" for p in bad[:8]))


def test_the_dedup_outcome_is_pinned_on_the_corpus():
    """A concrete outcome pin. QC-3: the delta pin this test used to carry is GONE, and could not be kept.

    IT USED TO ASSERT `raw - kept == 47` — that 47 superseded rows were sitting on disk awaiting dedup —
    chosen over absolute counts so the guard would survive legitimate corpus growth. That was sound until it
    collided with a guardrail: `manifest.compact()` (manifest.py:432) consolidates shards and physically drops
    exactly those superseded rows, and it is called AUTOMATICALLY at manifest.py:999 so re-indexes do not pile
    up. A compaction ran on 2026-07-31, producing data/manifest/vmnik-compact.parquet. After it,
    `raw == kept == 322` and dedup removes 0 — so the delta pin became UNSATISFIABLE BY CONSTRUCTION, and the
    test failed for a reason that was not a corpus defect. The test was wrong, not the guardrail: it pinned a
    transient on-disk condition that a maintenance operation exists to erase. Do not "fix" this by disabling
    compaction.

    WHAT REPLACES IT, and — stated plainly — what does not. The delta is a property of shard HISTORY; every
    check below is a property of the CORPUS, which is what survives compaction (compaction removes superseded
    rows but preserves the surviving key set exactly).

      * `kept == distinct keys in raw` is the compaction-invariant statement of the dedup contract: exactly
        one row per key, and no key lost. It catches a broken DEDUP_QUALIFY — one that keeps two rows per key,
        or drops keys entirely — before and after compaction alike.
      * `crash` and `wildtype/basal` are STABLE SPECIFIC-VALUE guards: unlike `kept` or `reportable` they do
        not move when an unrelated new experiment lands, so they can be pinned to a literal without breaking
        on growth. They are what now carries the wrong-MERGE / wrong-SPLIT coverage: a merge that wrongly
        collapses two wildtype/basal runs reads 29, a split reads 31.

    HONEST LIMITATION: that coverage is WEAKER than the delta was. The delta saw a wrong-merge anywhere in the
    corpus; these guards see one only if it lands inside a pinned subset. Post-compaction the evidence a
    general check would need has been consolidated away, so no stronger compaction-proof check exists on this
    data. If broader coverage is wanted, it has to come from a pre-compaction assertion at write time, not
    from a test reading the finished corpus."""
    import duckdb

    from cellarium import manifest
    con = duckdb.connect()
    src = "read_parquet('data/manifest/*.parquet', union_by_name=true)"
    ded = f"(SELECT * FROM {src} {manifest.DEDUP_QUALIFY})"
    # The dedup key, DERIVED FROM manifest.DEDUP_QUALIFY rather than hand-copied, so the two cannot drift.
    # A hand-copy is how this check would silently start testing a different key from the one production
    # dedups on — and the first attempt at it did in fact mis-place a NULLIF argument.
    key = manifest.DEDUP_QUALIFY.split("PARTITION BY", 1)[1].rsplit("ORDER BY", 1)[0].strip()
    assert key.startswith("(") and key.endswith(")"), (
        f"could not extract the PARTITION BY expression from DEDUP_QUALIFY; got {key!r}")
    try:
        raw = con.execute(f"SELECT count(*) FROM {src}").fetchone()[0]
        raw_keys = con.execute(f"SELECT count(DISTINCT {key}) FROM {src}").fetchone()[0]
        kept = con.execute(f"SELECT count(*) FROM {ded}").fetchone()[0]
        kept_keys = con.execute(f"SELECT count(DISTINCT {key}) FROM {ded}").fetchone()[0]
        crash = con.execute(f"SELECT count(*) FROM {ded} WHERE id LIKE '%_crash'").fetchone()[0]
        wt = con.execute(f"SELECT count(*) FROM {ded} WHERE perturbation='wildtype' "
                         "AND COALESCE(condition,'basal')='basal' AND reportable").fetchone()[0]
    finally:
        con.close()
    # THE DEDUP CONTRACT, in the one form that survives compaction. `raw - kept` is 47 on an uncompacted
    # corpus and 0 on a compacted one — both correct — so it cannot be pinned. What is true in BOTH states is
    # that dedup emits exactly one row per distinct key and loses none.
    assert kept == raw_keys, (
        f"dedup emitted {kept} rows for {raw_keys} distinct keys in raw (raw rows {raw}); these must be equal "
        "— fewer means dedup DROPPED a key, more means it kept multiple rows for one key. Note this is "
        "deliberately NOT the old `raw - kept == 47` pin, which manifest.compact() makes unsatisfiable.")
    assert kept_keys == kept, (
        f"{kept} surviving rows carry only {kept_keys} distinct keys — QUALIFY let a duplicate through")
    # Counts rows whose ID was MINTED by the crash path (`id LIKE '%_crash'`), which is NOT the same as
    # `qc='crashed'` — 8 rows produced a record via build_record and were only then marked crashed, so they
    # keep their real id. Both counts are valid answers to different questions; this pin is the id-minted one.
    # 41 historical + 7 from the SCI-TRNA-4 leu campaigns, whose un-starved control was lethal by construction
    # before its medium was fixed and collided with the starved arm on the model output dir.
    assert crash == 48, f"{crash} crash rows survive, expected 48 — a crash-id collision was wrongly merged"
    # The REFERENCE count, pinned because `wildtype/basal` is the denominator of every `pct_vs_ref` and a
    # silent change to it moves every percentage in the corpus. Re-pinned 30 -> 38 on 2026-08-08, with the
    # whole delta accounted for rather than the number simply updated — an unexplained re-pin is the pin
    # failing open. Composition, by campaign root:
    #     runs/cellarium            26  the original steady-state reference
    #     runs/aadrop                4  the leu arm's null, against the dropout kb
    #     runs_seed_aars/cellarium   4  control for the verified-index aaRS re-runs   (new)
    #     runs_kinetic_seeds/…       4  control for the kinetic arm                    (new)
    # Both new groups are controls for campaigns that were deliberately run, so the growth is intended. Note
    # they span three knowledge bases and two elongation models: this is a COUNT of reference rows, not a
    # poolable cell — `survey.analysis_rows` narrows to one arm before any of them is averaged (ARM-1).
    assert wt == 38, f"wildtype/basal reportable = {wt}, expected 38 — the reference count drifted"


def test_the_audit_tool_reads_the_same_corpus_as_everything_else():
    """Regression for a consumer that was NOT migrated to the shared key. `audit.py` kept its own
    `COALESCE(simout_path, id)` dedup, so `corpus_audit` and `prune_candidates` (both agent-reachable) re-exposed
    the inflated 273 / wildtype-34 counts every other tool had corrected. Every dedup consumer must agree."""
    from cellarium import audit, store, survey
    n_store = len(store.list_results())
    n_survey = survey.survey_corpus()["coverage"]["n_runs"]
    n_audit = len(audit._latest_per_run(audit._rows()))
    assert n_store == n_survey == n_audit, (
        f"consumers disagree on corpus size: store={n_store} survey={n_survey} audit={n_audit}")


def test_identity_is_stored_not_only_derived():
    """The durable fix. Deriving correctly must be OPTIONAL for a reader; getting it wrong should require
    ignoring a column that is right there."""
    import inspect
    src = inspect.getsource(manifest._flat_row)
    assert '"design_key"' in src and '"design_tag"' in src


def test_both_labelling_conventions_resolve():
    """41 rows use `perturbation/tag seed0` rather than `perturbation·tag·s0`. They resolved correctly only
    because their `condition` column happened to be right — the fall-through is now explicit, not luck."""
    alt = {"label": "metabolism_kinetic_objective_weight/minimal|kin_w:1e-8 seed0",
           "perturbation": "metabolism_kinetic_objective_weight", "condition": None}
    cur = {"label": "gene_knockout·KO:pfkA·s0", "perturbation": "gene_knockout", "condition": None}
    assert survey.design_tag(alt) == "minimal|kin_w:1e-8"
    assert survey.design_tag(cur) == "KO:pfkA"
    # and neither may fall through to the nullable column
    assert survey.design_tag({"label": "", "perturbation": "x", "condition": None}) == "basal"


@pytest.mark.skipif(not os.path.isdir("runs/cellarium"), reason="no local corpus on disk")
def test_no_run_on_disk_is_invisible_to_the_manifest():
    """D7. An orphan is readable but unindexed, so `_design_run_roots` — which resolves through the manifest —
    cannot see it. That is how a whole `valS` design stayed invisible through an entire audit."""
    rec = manifest.reconcile_disk()
    assert not rec["orphan_designs"], f"unindexed designs on disk: {rec['orphan_designs']}"
    assert not rec["orphan_seeds"], f"unindexed seeds on disk: {rec['orphan_seeds']}"


def test_a_rows_kb_matches_the_campaign_it_ran_in():
    """Provenance must not contradict itself. `_flat_row` called `_kb_prov()` with NO sim_path, so every row
    was stamped with the DEFAULT campaign's knowledge base regardless of which one produced it: all 21
    `runs/aadrop/` rows carried the corpus hash, which does not contain the dropout media those runs executed
    in. A kb_sha256 that disagrees with the run's own path is worse than a missing one — it is confidently
    wrong, and it is exactly the field a reviewer would trust to tell models apart."""
    import duckdb

    from cellarium import manifest
    con = duckdb.connect()
    try:
        rows = con.execute(
            f"SELECT simout_path, kb_sha256 FROM (SELECT * FROM "
            f"read_parquet('{manifest.MANIFEST_DIR}/*.parquet', union_by_name=true) {manifest.DEDUP_QUALIFY})"
        ).fetchall()
    finally:
        con.close()
    # RESOLVED ROOT-AWARE, 2026-08-08. This used `_sim_path_of`, which returns only the second path component
    # and therefore drops the OUTPUT ROOT. That was right while every campaign lived under `runs/`; it is not
    # now, because `CELLARIUM_OUT` moved whole campaigns to `runs_seed_aars/`, `runs_kinetic_seeds/` and
    # `runs_depleting/`, all of which use the sim_path `cellarium`. Every row in those three was therefore
    # compared against `runs/cellarium/kb` and reported as contradicting its own path — when in fact each root
    # holds its own kb, all three hashing to `5f19d040…`, exactly matching the rows.
    #
    # The test was accusing a correct corpus. Read root-aware, 297 of 297 rows whose kb is still on disk agree.
    known: dict = {}
    bad = []
    for path, kb in rows:
        if not path or not kb:
            continue
        sp = manifest.campaign_root_of(path)
        if sp not in known:
            known[sp] = manifest.kb_sha_for_run(path)
        want = known.get(sp)
        if want and kb != want:
            bad.append((sp, path, kb[:10], want[:10]))
    assert not bad, ("rows whose kb_sha256 contradicts the campaign in their own path:\n" +
                     "\n".join(f"  {sp}: {p} has {got} want {exp}" for sp, p, got, exp in bad[:8]))
