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
      * duplicate (design, seed) — legitimate here. `wildtype/basal` seed 0 appears three times, from three
        different `simout_path`s, and the channel values DIFFER (growth 0.000244 on one contributor's machine vs
        0.000226 on ours), so the model is not bit-deterministic across environments and those are genuine
        independent replicates rather than one run counted thrice.
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
    con = duckdb.connect()
    try:
        n = con.execute(
            "SELECT count(*) FROM ("
            "  SELECT kb_sha256 FROM read_parquet('data/manifest/*.parquet', union_by_name=true)"
            "  QUALIFY row_number() OVER (PARTITION BY COALESCE(simout_path, id) ORDER BY ts DESC) = 1"
            ") WHERE kb_sha256 IS NULL"
        ).fetchone()[0]
    finally:
        con.close()
    assert n == 0, f"{n} rows carry no kb provenance — run manifest.backfill_kb_provenance(dry_run=False)"


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
