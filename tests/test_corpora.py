"""The corpus registry: what Cellarium can read, and the refusals that keep two corpora from being pooled.

WHY THESE CASES AND NOT OTHERS. The registry replaces five independent hard-codings of one fact
(`manifest.MANIFEST_DIR`, `store.MANIFEST_DIR`/`MANIFEST_GLOB`, `survey.MANIFEST_GLOB`,
`audit.MANIFEST_GLOB`, `evidence.py`'s `CELLARIUM_MANIFEST`), so the thing worth pinning is not that it
can list three names — it is the three refusals, each of which corresponds to a defect this project has
already shipped somewhere:

  * a corpus registered with no declared row unit is refused, because `mcp.describe_cellarium` told
    third-party agents "one row is one generation of one seed of one design" while 369 rows carried 825
    generations;
  * a registry file that EXISTS but cannot be parsed raises instead of reporting an empty registry,
    because "could not read" reported as "nothing there" is this project's named silent-absence class;
  * two corpora whose row units differ are refused for pooling rather than silently summed.

Expectations are LITERALS throughout. `MB` is not imported to compute an expected size: a test that said
`== round(n / corpora.MB, 2)` would hold at every value of the constant, which is the self-referential trap
recorded in `tests/test_threshold_boundaries.py`.
"""

from __future__ import annotations

import json
import os
import socket
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cellarium import corpora  # noqa: E402


def _online(host: str = "huggingface.co", port: int = 443, timeout: float = 4.0) -> bool:
    try:
        socket.create_connection((host, port), timeout=timeout).close()
        return True
    except OSError:
        return False


# --- the three refusals -------------------------------------------------------------------------

def test_a_corpus_without_a_declared_row_unit_is_refused():
    """The one required field beyond identity. A corpus whose row unit is unstated cannot be counted or
    compared, and a default would let the omission through — which is how a wrong statement of the unit
    reached the third-party agent interface and stayed there."""
    with pytest.raises(ValueError, match="row_unit is required"):
        corpora.Corpus(key="x", title="X", kind="local", locator=".", row_unit="")
    with pytest.raises(ValueError, match="row_unit is required"):
        corpora.Corpus(key="x", title="X", kind="local", locator=".", row_unit="   ")
    # and the positive control: the same record with a unit is accepted
    ok = corpora.Corpus(key="x", title="X", kind="local", locator=".", row_unit="one run")
    assert ok.row_unit == "one run"


def test_an_unreadable_registry_file_raises_instead_of_reporting_an_empty_registry(tmp_path, monkeypatch):
    """ABSENT and UNREADABLE are different answers. A missing file is legitimately an empty user registry;
    a file that is present and malformed is a fault, and reporting [] for it would mean a corpus the user
    plugged in silently disappears with no error anywhere."""
    missing = tmp_path / "nope.json"
    monkeypatch.setattr(corpora, "REGISTRY_FILE", missing)
    assert corpora._user_records() == []                      # absent: empty, no error

    bad = tmp_path / "registered.json"
    bad.write_text("{not json at all", encoding="utf-8")
    monkeypatch.setattr(corpora, "REGISTRY_FILE", bad)
    with pytest.raises(ValueError, match="is not readable JSON"):
        corpora._user_records()

    # a well-formed file of the wrong SHAPE is also a fault, not an empty registry
    bad.write_text('{"key": "x"}', encoding="utf-8")
    with pytest.raises(ValueError, match="JSON list"):
        corpora._user_records()


def test_two_corpora_with_different_row_units_are_not_poolable():
    """Literal, and both directions. The same corpus against itself pools; the local Cellarium index
    against well4cell does not, because one row is a seed of a design and the other is a trajectory."""
    same = corpora.row_unit_differs(["cellarium-local", "cellarium-local"])
    assert same["poolable"] is True

    differ = corpora.row_unit_differs(["cellarium-local", "well4cell"])
    assert differ["poolable"] is False
    assert "row units differ" in differ["why"]
    assert set(differ["units"]) == {"cellarium-local", "well4cell"}

    assert "not registered" in corpora.row_unit_differs(["cellarium-local", "no-such-corpus"])["error"]


# --- the registry itself ------------------------------------------------------------------------

def test_the_three_declared_corpora_are_present_and_distinct():
    """Three records, not two. The local working copy and the published deposit are neither a superset nor
    a subset of each other — designs uploaded there were pruned here, runs never uploaded exist only here —
    so collapsing them into one "cellarium" entry would assert something false."""
    keys = [c.key for c in corpora.DECLARED]
    assert keys == ["cellarium-local", "cellarium-hf", "well4cell"]
    assert len({c.locator for c in corpora.DECLARED}) == 3


def test_an_unknown_field_in_a_user_record_is_refused(tmp_path, monkeypatch):
    """A typo in a plugged-in record must fail loudly. Silently ignoring an unknown key is how a corpus
    ends up registered with its caveats dropped."""
    f = tmp_path / "registered.json"
    f.write_text(json.dumps([{"key": "k", "title": "T", "kind": "local", "locator": ".",
                              "row_unit": "one row", "ceveats": ["typo"]}]), encoding="utf-8")
    monkeypatch.setattr(corpora, "REGISTRY_FILE", f)
    with pytest.raises(ValueError, match="unknown field"):
        corpora.registered()


def test_an_unknown_kind_is_refused():
    with pytest.raises(ValueError, match="kind must be one of"):
        corpora.Corpus(key="x", title="X", kind="ftp", locator=".", row_unit="one row")


def test_a_user_record_can_redirect_a_built_in_and_says_that_it_did(tmp_path, monkeypatch):
    """The replacement for `CELLARIUM_MANIFEST`: point `cellarium-local` elsewhere without editing the
    package. The override must be visible, because a redirected built-in that looks built-in is a trap."""
    f = tmp_path / "registered.json"
    f.write_text(json.dumps([{"key": "cellarium-local", "title": "elsewhere", "kind": "local",
                              "locator": str(tmp_path / "other"), "row_unit": "one seed of one design"}]),
                 encoding="utf-8")
    monkeypatch.setattr(corpora, "REGISTRY_FILE", f)
    c = corpora.get("cellarium-local")
    assert c.locator == str(tmp_path / "other")
    assert c.declared_in == "user"
    assert len(corpora.registered()) == 3, "an override must replace, not append"


def test_a_code_declared_corpus_cannot_be_unregistered_and_says_so(tmp_path, monkeypatch):
    """Returning success for a no-op is the failure here: the caller would believe the corpus was removed."""
    f = tmp_path / "registered.json"
    monkeypatch.setattr(corpora, "REGISTRY_FILE", f)
    out = corpora.unregister("well4cell")
    assert "declared in code" in out["error"]
    assert corpora.get("well4cell") is not None

    assert "no user-registered corpus" in corpora.unregister("never-existed")["error"]


def test_register_then_unregister_round_trips(tmp_path, monkeypatch):
    f = tmp_path / "registered.json"
    monkeypatch.setattr(corpora, "REGISTRY_FILE", f)
    monkeypatch.setattr(corpora, "CACHE_ROOT", tmp_path / "cache")
    r = corpora.register(key="mine", title="My runs", kind="local", locator=str(tmp_path / "runs"),
                         row_unit="one seed of one design")
    assert r["registered"] == "mine"
    assert [c.key for c in corpora.registered()][-1] == "mine"
    assert corpora.status("mine")["state"] == "locator_missing", "the directory does not exist yet"

    (tmp_path / "runs").mkdir()
    assert corpora.status("mine")["state"] == "metadata_absent", "directory present, no index files"

    assert corpora.unregister("mine")["unregistered"] == "mine"
    assert corpora.get("mine") is None


def test_status_names_the_known_keys_when_asked_for_one_that_is_not_registered():
    out = corpora.status("well-4-cell")
    assert "no corpus registered" in out["error"]
    assert "well4cell" in out["error"], "the error must name what IS available, not just what is not"


def test_an_offline_status_call_never_claims_a_remote_corpus_is_unreachable():
    """`status()` makes no network call, so it reports `metadata_absent` — never 'unreachable'. This is the
    misattribution BACKLOG M-13 records (a Docker engine that is down reported as our worker producing no
    JSON) and that `hf._repo_sizes` records for a stale token on a public repo."""
    st = corpora.status("well4cell")
    assert st["network_checked"] is False
    assert st["state"] in ("ready", "metadata_absent")
    assert "unreachable" not in json.dumps(st).lower()


def test_a_local_corpus_has_no_metadata_to_fetch_and_needs_no_network():
    plan = corpora.metadata_plan("cellarium-local")
    assert plan["nothing_to_fetch"] is True
    assert "read in place" in plan["why"]
    assert "network_checked" not in plan, "a local plan must not have touched the network"


# --- the scientific finding, pinned so an edit cannot quietly drop it -----------------------------

def test_well4cell_is_recorded_as_unable_to_answer_a_per_isoacceptor_question():
    """MEASURED 2026-11-14. well4cell's own column map for the charging channel carries 21 ids — the 20
    canonical amino acids plus L-SELENOCYSTEINE[c] — not 86 indexed by tRNA gene, so a per-isoacceptor
    question cannot be answered from it. (An earlier docstring called this independent corroboration of
    Cellarium's capability record; that was withdrawn on 2026-11-21 -- see the next test.)

    This test pins the CLAIM in the registry, not the file: the file is a 12 MB fetch that CI does not
    have. The claim is what a reader of the registry is told, and dropping it would let a per-isoacceptor
    question be routed at well4cell.
    """
    w = corpora.get("well4cell")
    assert any("PER-ISOACCEPTOR" in s for s in w.does_not_answer)
    assert any("21" in s and "SELENOCYSTEINE" in s for s in w.answers)
    assert any("F18" in s for s in w.caveats), "the superseded audit finding must stay recorded"
    assert any("F1" in s and "train/test" in s for s in w.caveats)


def test_the_registry_names_the_release_each_finding_belongs_to():
    """MEASURED 2026-11-21 against the live Hub: the release is 1.0.0-rc2 (built 2026-11-04), and the
    project's audit is of 1.0.0-rc1. Three statements this entry used to make were wrong for rc2, and each is
    pinned so it cannot come back:
      - F1: the twin-leaking train/test splits were FIXED in rc2 (rebuilt per design, `split_by_tu` added --
        the audit's own proposal), not removed. On the rc2 index 0 of 25,187 twin groups cross either split.
      - F18: charging exists for 21,865 of 139,039 trajectories, not for the release; the 117,174 carried over
        from rc1 still have none.
      - The 21-column charging layout is NOT independent corroboration of Cellarium's capability record: a
        per-amino-acid summary is written whether or not the 86 per-tRNA values are broadcasts, and the rc2
        card is built on Cellarium's own definitions.
    """
    w = corpora.get("well4cell")
    text = " ".join((w.row_unit, *w.answers, *w.does_not_answer, *w.caveats))
    assert "1.0.0-rc1" in text and "1.0.0-rc2" in text
    assert w.extra["release_measured"] == "1.0.0-rc2"
    assert any("F1" in s and "split_by_tu" in s and "FIXED" in s for s in w.caveats)
    assert any("21,865" in s and "139,039" in s for s in w.answers)
    assert any("117,174" in s and "F18" in s for s in w.does_not_answer)
    assert not any("no train/test column at all" in s for s in w.caveats)
    assert not any("is independent corroboration" in s for s in w.caveats)


def test_the_audit_is_recorded_as_describing_a_different_release():
    """The project holds a 445-line audit of 1.0.0-rc1 (763 files, configs core plus four matrix). The live
    release has 978 files and seven configs. Citing the audit as current would be wrong, so the record says
    so and this fails if that warning is removed."""
    w = corpora.get("well4cell")
    assert any("DIFFERENT RELEASE" in s.upper() for s in w.caveats)
    assert w.extra["files_measured_2026_11_14"] == 978
    assert sorted(w.extra["configs_measured_2026_11_14"]) == [
        "charging", "core", "expression", "expression_1s", "metabolism", "metabolism_1s", "summary"]


# --- sizes are reported in ONE convention --------------------------------------------------------

def test_sizes_are_binary_so_the_ui_and_the_paper_agree(tmp_path, monkeypatch):
    """The shipped index is 7,847,841 bytes, which is 7.48 MiB and 7.85 decimal MB. The Platform Map and
    `scripts/reconcile_corpus_counts.py` (`GB = 1024 ** 3`) use the binary convention, so this one does
    too — otherwise one file carries two numbers across the project's own surfaces.

    LITERAL on both sides: a 2,097,152-byte file is exactly 2.0 MiB and 2.1 decimal MB, so the assertion
    distinguishes the conventions instead of restating whichever constant is in use.
    """
    f = tmp_path / "manifest"
    f.mkdir()
    (f / "a.parquet").write_bytes(b"\0" * 2_097_152)
    monkeypatch.setattr(corpora, "REGISTRY_FILE", tmp_path / "none.json")
    monkeypatch.setattr(corpora, "CACHE_ROOT", tmp_path / "cache")
    c = corpora.Corpus(key="t", title="T", kind="local", locator=str(f), index="*.parquet",
                       row_unit="one row")
    monkeypatch.setattr(corpora, "DECLARED", (c,))
    st = corpora.status("t")
    assert st["state"] == "ready"
    assert st["index_mb"] == 2.0, "binary (1024^2); decimal would give 2.1"


# --- the live tree, when there is a network ------------------------------------------------------

@pytest.mark.skipif(not _online(), reason="no network: cannot check the live well4cell file tree")
def test_every_declared_metadata_pattern_matches_something_on_the_live_release():
    """A pattern that matches nothing is a silent hole: the tier would fetch fewer files than intended and
    report success. Measured 2026-11-14: all eight patterns matched, 24 files, 12.03 MB.

    A HOST fault skips (the rule `tests/test_gse2065.py::_environment_fault` establishes — an environment
    fault must not be scored as a result), but a pattern matching nothing FAILS, because that is a fact
    about our record rather than about the network.
    """
    plan = corpora.metadata_plan("well4cell")
    if plan.get("error"):
        pytest.skip(f"the hub did not answer: {plan['error'][:160]}")
    assert plan["patterns_matching_nothing"] == [], (
        f"these declared patterns match no file on the live release: {plan['patterns_matching_nothing']}")
    assert plan["n_matched"] >= 20
    assert plan["total_tier_mb"] < 100, (
        "the metadata tier must stay a cheap fetch; if it has grown past 100 MB the tier split needs "
        "re-thinking rather than silently costing the user a large download")
