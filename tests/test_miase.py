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
        # the upshift is a RECORDER-TRUNCATION case, never a fabricated-experiment violation
        assert summary[up]["violation"] == 0, "the upshift must not be reported as a missing experiment"
        assert summary[up]["recorder_truncation"] > 0, "the truncation signature must be detected"


def test_a_dropped_run_is_not_reported_as_a_violation():
    """Tombstoned runs (WELL-1y) are curated out of every analysis — including this one."""
    _corpus()
    from cellarium import manifest, miase
    if manifest.dropped_keys():
        r = miase.check_corpus()
        assert "error" not in r
    import inspect
    assert "_dropped" in inspect.getsource(miase.check_corpus)
