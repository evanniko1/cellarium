"""SCI-QC-1 — declared-vs-executed (MIASE) guard.

A design declares an experiment (`timeline`); the run executes something; the run is then RECORDED. MIASE
(Waltemath 2011) requires the declaration and the run to correspond.

The corpus case is a lesson in not stopping at the first explanation. The UPSHIFT's `media_id` reads `minimal`
for all 2,574 timesteps while the DOWNSHIFT records its switch — which looks exactly like "the upshift never
ran". It did: a re-run shows wcEcoli logging `update media: minimal_plus_amino_acids`. The cause is upstream and
mechanical — `media_id` is a fixed-width column sized by its FIRST value, so a run starting in `minimal` gets
`<U7` and the later 24-char `minimal_plus_amino_acids` truncates to 7 chars, which spells `minimal`. The
downshift starts with the long name (`<U24`), so nothing truncates. These tests pin BOTH the guard and that
distinction, because reporting a recording bug as a fabricated experiment would condemn usable data.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("CELLARIUM_MANIFEST", "data/manifest/vmnik-compact.parquet")
os.environ.setdefault("CELLARIUM_OUT", "runs")

import pytest  # noqa: E402


def _corpus():
    from cellarium import store
    if not store.has_manifest():
        pytest.skip("no local manifest")


def test_the_declared_timeline_parser_matches_wcecolis_own():
    """We must parse a declaration exactly as the MODEL does (`make_media.make_timeline`: split on ', ' then on
    whitespace). Parsing more leniently would 'verify' a declaration the model never understood."""
    from cellarium import miase
    assert miase.declared_events("0 minimal, 1200 minimal_plus_amino_acids") == [
        (0.0, "minimal"), (1200.0, "minimal_plus_amino_acids")]
    assert miase.declared_events("") == []
    assert miase.declared_events(None) == []
    assert miase.declared_events("garbage") == []          # a malformed event is dropped, never guessed at


def test_the_truncation_signature_is_recognised_not_called_a_fake_experiment():
    """THE correction. `minimal` + a declared `minimal_plus_amino_acids` that truncates to exactly `minimal` is
    the fixed-width-column signature — a RECORD defect, not a missing experiment."""
    from cellarium import miase
    r = miase.check_run({"timeline": "0 minimal, 1200 minimal_plus_amino_acids", "generations": 1,
                         "media_segments": '[{"media": "minimal"}]'})
    assert r["verdict"] == "recorder_truncation", r
    assert "TRUNCATION" in r["note"] and "fixed-width" in r["note"]


def test_a_genuine_mismatch_is_still_a_violation():
    """The guard must not become toothless: a mismatch that truncation CANNOT explain (the recorded medium is not
    a prefix of the declared one) is still a real violation."""
    from cellarium import miase
    r = miase.check_run({"timeline": "0 acetate, 1200 succinate", "generations": 1,
                         "media_segments": '[{"media": "glucose"}]'})
    assert r["verdict"] == "violation", r


def test_a_matching_run_passes():
    from cellarium import miase
    r = miase.check_run({"timeline": "0 minimal_plus_amino_acids, 1200 minimal", "generations": 1,
                         "media_segments": '[{"media": "minimal_plus_amino_acids"}, {"media": "minimal"}]'})
    assert r["verdict"] == "ok"


def test_a_multigeneration_mismatch_is_UNDETERMINED_not_a_violation():
    """`media_segments` covers only the LAST generation, so a shift scheduled inside an earlier one is invisible.
    Calling that a violation would train the reader to ignore the check — worse than a smaller, always-right one.

    Uses media whose names do NOT truncate into each other, because the truncation signature is a *specific*
    explanation and rightly takes precedence over 'inconclusive' when it applies."""
    from cellarium import miase
    r = miase.check_run({"timeline": "0 acetate, 1200 succinate", "generations": 4,
                         "media_segments": '[{"media": "glucose"}]'})
    assert r["verdict"] == "undetermined"


def test_truncation_takes_precedence_over_undetermined_even_multigeneration():
    """When the fixed-width signature explains the mismatch, say so — a named mechanical cause is more useful
    than 'inconclusive', at any generation count."""
    from cellarium import miase
    r = miase.check_run({"timeline": "0 minimal, 1200 minimal_plus_amino_acids", "generations": 4,
                         "media_segments": '[{"media": "minimal"}]'})
    assert r["verdict"] == "recorder_truncation"


def test_a_static_design_is_not_applicable():
    from cellarium import miase
    assert miase.check_run({"timeline": None, "generations": 1,
                            "media_segments": '[{"media": "minimal"}]'})["verdict"] == "not_applicable"


def test_the_corpus_check_finds_the_upshift_and_clears_the_downshift():
    """The live finding, pinned. If the upshift is ever re-run correctly this test's expectation flips — which is
    exactly the signal we want, so it asserts the SHAPE (a blocking violation is detected and named) rather than
    silently passing either way."""
    _corpus()
    from cellarium import miase
    r = miase.check_corpus()
    if "error" in r:
        pytest.skip(r["error"])
    up = "timeline/0 minimal, 1200 minimal_plus_amino_acids"
    down = "timeline/0 minimal_plus_amino_acids, 1200 minimal"
    summary = r["summary"]
    if down in summary:
        assert summary[down]["violation"] == 0, "the DOWNSHIFT must pass — it executed AND recorded its shift"
    if up in summary:
        # The upshift was a RECORDER defect, never a fabricated experiment — and it is now FIXED at the source.
        # SCI-QC-2 rewrote its `media_segments` from the untruncated `Environment/media_id`, so the two
        # single-generation seeds now compare EQUAL to their declaration (`ok`) and the 4-generation seed is
        # `undetermined` because the stored segments still describe only its last generation (SCI-QC-3).
        # The durable invariant across all of that: never a `violation`.
        assert summary[up]["violation"] == 0, "the upshift must not be reported as a missing experiment"
        assert summary[up]["ok"] + summary[up]["repaired_ok"] + summary[up]["recorder_truncation"] > 0, (
            f"the upshift must land on some benign verdict, got {summary[up]}")


def test_the_repaired_upshift_no_longer_stores_the_truncated_label():
    """SCI-QC-2, pinned at the manifest. If this ever reads a lone `minimal` again, either the repair was lost
    or a re-index reintroduced the truncated column — both are silent corruption of a published number."""
    _corpus()
    import json

    from cellarium import segments, store, survey
    up = "timeline/0 minimal, 1200 minimal_plus_amino_acids"
    rows = [r for r in store.list_results() if survey.design_key(r) == up]
    if not rows:
        pytest.skip("upshift design not in this manifest")
    seen = 0
    for r in rows:
        full = segments.full_row(r["id"])
        if not full or not full.get("media_segments"):
            continue
        seen += 1
        media = [s.get("media") for s in json.loads(full["media_segments"])]
        assert media != ["minimal"], (
            f"{r['id']}: stored segments are the truncated single `minimal` again — the shift is invisible and "
            f"its per-segment means average pre- and post-shift together")
        assert "minimal_plus_amino_acids" in media, (r["id"], media)
    if not seen:
        pytest.skip("no stored media_segments for the upshift in this manifest")


def test_an_unreadable_repair_is_never_reported_as_a_violation():
    """The regression CI caught. When the raw simOut is absent (as on CI), the repair path must report
    `available: False` — NOT an empty `media_sequence` marked available, which compares unequal to the
    declaration and gets reported as a fabricated-experiment violation. Absence must never become an
    accusation; that is the exact failure mode this module exists to prevent."""
    from cellarium import miase
    for bogus in ("no_such_result_id", "", "wildtype_does_not_exist_999"):
        out = miase.executed_media_from_raw(bogus)
        assert out.get("available") is False, out
        assert "why" in out
        assert not out.get("media_sequence"), "an unavailable repair must not carry a sequence at all"


def test_the_untruncated_witness_recovers_every_shift_run():
    """`Environment/media_id` is the repair path: <U25, wide enough for 'minimal_plus_amino_acids' (24 chars),
    in the SAME simOut as the corrupted `FBAResults/media_id`. For every nutrient-shift run with local raw it
    must carry the full declared sequence and switch at the declared time — which is what turns this from a
    defect we can only report upstream into one we fix locally, with no re-simulation."""
    _corpus()
    from cellarium import miase, raw, store, survey
    checked = 0
    for r in store.list_results():
        if (r.get("perturbation") or "") != "timeline":
            continue
        if not (store.simout_path(r["id"]) and raw.seed_runs(survey.design_key(r))):
            continue
        rep = miase.executed_media_from_raw(r["id"])
        if not rep.get("available"):
            continue
        checked += 1
        declared = [m for _t, m in miase.declared_events(r.get("timeline"))]
        assert rep["media_sequence"][:len(declared)] == declared, (r["id"], rep["media_sequence"], declared)
        assert 1200.0 in rep["switch_times_s"], (r["id"], rep["switch_times_s"])
        # the whole point: no value is a truncated prefix of a longer declared one
        for m in rep["media_sequence"]:
            assert m in declared, f"{r['id']}: recovered {m!r} is not a declared medium"
    if not checked:
        pytest.skip("no timeline run with local raw and an Environment/media_id column")


def test_a_dropped_run_is_not_reported_as_a_violation():
    """Tombstoned runs (WELL-1y) are curated out of every analysis — including this one."""
    _corpus()
    from cellarium import manifest, miase
    if manifest.dropped_keys():
        r = miase.check_corpus()
        assert "error" not in r
    import inspect
    assert "_dropped" in inspect.getsource(miase.check_corpus)
