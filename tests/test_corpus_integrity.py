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
    """A concrete outcome pin — NOT a tautology. The earlier two invariants asserted only what QUALIFY
    guarantees by construction (survivors have unique keys), so a wrong-merge or wrong-split passed them both.

    Pinned on the dedup DELTA (`raw - kept`), NOT absolute counts, so the guard survives LEGITIMATE corpus
    growth (adding a run bumps raw and kept equally, leaving the delta) while still catching the regression
    class: a wrong-MERGE of distinct runs raises the delta, a wrong-SPLIT of a duplicate lowers it. Exactly 9
    re-indexed duplicates are removed (8 wildtype seeds 8-15 + 1 rRNA_KO:4op), and that stays 9 regardless of
    how many new runs land. `wildtype/basal` and the crash floor are stable specific-value guards."""
    import duckdb

    from cellarium import manifest
    con = duckdb.connect()
    src = "read_parquet('data/manifest/*.parquet', union_by_name=true)"
    ded = f"(SELECT * FROM {src} {manifest.DEDUP_QUALIFY})"
    try:
        raw = con.execute(f"SELECT count(*) FROM {src}").fetchone()[0]
        kept = con.execute(f"SELECT count(*) FROM {ded}").fetchone()[0]
        crash = con.execute(f"SELECT count(*) FROM {ded} WHERE id LIKE '%_crash'").fetchone()[0]
        wt = con.execute(f"SELECT count(*) FROM {ded} WHERE perturbation='wildtype' "
                         "AND COALESCE(condition,'basal')='basal' AND reportable").fetchone()[0]
    finally:
        con.close()
    # 9 re-indexed duplicates + 3 SCI-QC-2 segment repairs. The repair is append-only: each corrected row
    # supersedes its corrupt original by `ts`, so the original stays on disk and shows up here as a superseded
    # duplicate. This pin CAUGHT that write (it read 12 where 9 was pinned), which is exactly its job — the
    # number must only ever move for a change someone can name.
    assert raw - kept == 47, (f"dedup removed {raw - kept} rows (raw {raw} -> kept {kept}); expected 47 = "
                              "9 re-indexed duplicates + 3 segment repairs + 7 crash rows re-stamped with "
                              "their aadrop kb + 28 rows re-stamped when _flat_row stopped defaulting the kb "
                              "to the cellarium campaign — a different number means a wrong-merge, a "
                              "wrong-split, or an unrecorded corpus write")
    # Counts rows whose ID was MINTED by the crash path (`id LIKE '%_crash'`), which is NOT the same as
    # `qc='crashed'` — 8 rows produced a record via build_record and were only then marked crashed, so they
    # keep their real id. Both counts are valid answers to different questions; this pin is the id-minted one.
    # 41 historical + 7 from the SCI-TRNA-4 leu campaigns, whose un-starved control was lethal by construction
    # before its medium was fixed and collided with the starved arm on the model output dir.
    assert crash == 48, f"{crash} crash rows survive, expected 48 — a crash-id collision was wrongly merged"
    # 26 + the 4 wildtype/basal seeds the leu arm ran against the aadrop kb as its null.
    assert wt == 30, f"wildtype/basal reportable = {wt}, expected 30 — the reference count drifted"


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
    from cellarium import provenance
    known = {}
    bad = []
    for path, kb in rows:
        if not path or not kb:
            continue
        sp = manifest._sim_path_of(path)
        if sp not in known:
            try:
                known[sp] = (provenance.kb_provenance(sp) or {}).get("kb_sha256")
            except Exception:
                known[sp] = None
        want = known.get(sp)
        if want and kb != want:
            bad.append((sp, path, kb[:10], want[:10]))
    assert not bad, ("rows whose kb_sha256 contradicts the campaign in their own path:\n" +
                     "\n".join(f"  {sp}: {p} has {got} want {exp}" for sp, p, got, exp in bad[:8]))
