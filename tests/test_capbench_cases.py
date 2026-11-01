"""CAPBENCH-1 — the guard that keeps the capability-case corpus tied to the measurements it was derived from.

WHY THESE TESTS ARE NOT SCHEMA CHECKS. A benchmark's answer key is the one artifact in a paper that nobody
re-derives: reviewers read the cases, not the corpus underneath them, and a key that drifted from its evidence
looks exactly like a key that did not. `evals/capbench_cases.py` states 40-odd numbers — 286 generation dirs,
15 below the floor, 8 generations recorded `ok`, 240 reportable rows, 103 with local raw, 4 noop rows — and
every one of them came from a file in this repository. So every one of them is RECOMPUTED here from that file
rather than compared against a copy of itself. A test that asserted only "the corpus is non-empty and
well-formed" would pass unchanged on a corpus whose every number had rotted, which is the failure this file
exists to make impossible.

THE MOST IMPORTANT TEST IN THIS FILE is `test_the_rpme_case_still_matches_the_scan_it_was_derived_from`. C3.1
is the seed case: a run that looks like clean data and is not. Its key is entirely a restatement of
`data/qc_via_1_scan.json`, so the test opens that file, recounts it, and requires every asserted figure to
match — including the negative ones (no dir of that design is above the floor; no other design is below it).
If the scan is ever re-run over a different tree, this fails rather than letting C3.1 quietly describe a
measurement that no longer exists.

SKIPS NAME THEIR CONDITION, ALWAYS. Several checks read the shipped corpus, which a clone or a CI runner may
not have, and several read a knowledge base a local ParCa run replaces. Both are ordinary states, not
failures — but "could not read it" must never be reported as "it is not there". That exact bug class is
called out repeatedly in this repo's docs, so each guard here skips with the condition spelled out, and the
helpers below refuse to return an empty result that a caller could mistake for a measured zero.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "evals"))
sys.path.insert(0, str(REPO / "src"))
os.environ.setdefault("CELLARIUM_MANIFEST", "data/manifest/*.parquet")
os.environ.setdefault("CELLARIUM_OUT", "runs")

import capbench_cases as cb  # noqa: E402
import pytest  # noqa: E402

from cellarium import capability, qc  # noqa: E402

SCAN = REPO / "data" / "qc_via_1_scan.json"
INVARIANTS = REPO / "data" / "INVARIANTS.json"
MAIN_TEX = REPO / "paper" / "sim2science" / "main.tex"


# ------------------------------------------------------------------------------------------------------------
# Readers. Each one either returns real data or raises pytest.skip naming exactly what was missing — never an
# empty dict/list, which a downstream `assert not bad` would silently treat as a clean result.
# ------------------------------------------------------------------------------------------------------------

def _scan() -> dict:
    if not SCAN.is_file():
        pytest.skip(f"{SCAN.relative_to(REPO).as_posix()} is not in this tree — C3.1/C3.2 assert numbers "
                    "recomputed from that scan, and without it they are unmeasurable, not satisfied")
    d = json.loads(SCAN.read_text(encoding="utf-8"))
    if not d.get("rows"):
        pytest.skip(f"{SCAN.name} carries no `rows` — nothing to recompute against")
    return d


def _rows() -> list[dict]:
    """The corpus, through the same boundary every other consumer uses (`store.list_results`, post-dedup)."""
    from cellarium import store
    if not store.has_manifest():
        pytest.skip("no local manifest (data/manifest/*.parquet) — the design/gene/column existence checks "
                    "have nothing to resolve against")
    rows = store.list_results()
    if not rows:
        pytest.skip("the manifest is present but empty — an existence check over zero rows would pass "
                    "vacuously, which is the silent-absence bug this suite must not reintroduce")
    return rows


def _duck():
    """A duckdb connection plus the deduped source expression, matching tests/test_corpus_integrity.py."""
    from cellarium import store
    if not store.has_manifest():
        pytest.skip("no local manifest (data/manifest/*.parquet)")
    import duckdb

    from cellarium import manifest
    src = f"read_parquet('{manifest.MANIFEST_DIR.as_posix()}/*.parquet', union_by_name=true)"
    return duckdb.connect(), f"(SELECT * FROM {src} {manifest.DEDUP_QUALIFY})"


def _case(cid: str) -> dict:
    got = cb.by_id([cid])
    assert len(got) == 1, f"expected exactly one case with id {cid}, got {len(got)}"
    return got[0]


def _grown_locally() -> str:
    """conftest's local-rows guard, re-exported so the count pins below read the same condition as the rest of
    the suite. A locally-run sim carries the LOCAL ParCa's kb_sha256, which is the signal — not a row count."""
    from conftest import local_rows_present
    return local_rows_present()


# ------------------------------------------------------------------------------------------------------------
# 1 · The corpus is internally coherent — ids, boxes, and the vocabularies they draw on.
# ------------------------------------------------------------------------------------------------------------

def test_every_id_is_unique_and_carries_its_pair_group():
    """Ids are the join key between this file, the ledger a run writes, and the frozen labels CAPBENCH-1a
    adjudicates. A duplicate would silently merge two cases' scores; an id that disagrees with its own `pair`
    would make `pairs()` group the wrong two together, which is the one grouping the benchmark's power rests
    on."""
    ids = [c["id"] for c in cb.CASES]
    assert len(ids) == len(set(ids)), f"duplicate case ids: {sorted({i for i in ids if ids.count(i) > 1})}"
    for c in cb.CASES:
        assert c["id"].startswith("C"), f"{c['id']} does not use the CAPBENCH `C<group>.<member>` scheme"
        if c["pair"]:
            assert c["id"].split(".")[0] == c["pair"], (
                f"{c['id']} declares pair {c['pair']!r} but its id says it belongs to "
                f"{c['id'].split('.')[0]!r} — pairs() would group it with the wrong partner")


def test_every_case_fills_every_box():
    """The schema is the reason grading can be mechanical and labels can be frozen before any model sees them.
    A case missing a box is not a smaller case; it is one whose grader has to improvise, which is how a
    pre-registered key stops being pre-registered."""
    required = {"id", "theme", "question", "r", "governed_by", "requires", "mode_constraint", "represented_in",
                "admissible_modes", "action", "answer_mode", "why_not", "blocking", "data_defect",
                "storage_gap", "must_say", "must_not_say", "check", "measured", "invariants", "grounding",
                "pair", "pair_differs_in"}
    for c in cb.CASES:
        missing = required - set(c)
        extra = set(c) - required
        assert not missing, f"{c['id']} is missing {sorted(missing)}"
        assert not extra, (
            f"{c['id']} carries undeclared field(s) {sorted(extra)} — add them to `required` here so every "
            "case is required to fill them, or drop them; a field one case has and the others do not is a "
            "box the grader cannot rely on")
        assert set(c["r"]) == set(cb.R_FIELDS), (
            f"{c['id']}'s typed tuple has fields {sorted(c['r'])}, not the six of main.tex sec.3 "
            f"{sorted(cb.R_FIELDS)}")
        assert c["question"] and not c["question"].endswith(" "), f"{c['id']} has no question"
        assert c["must_say"], f"{c['id']} says nothing about what a correct answer must contain"
        assert c["must_not_say"], (
            f"{c['id']} names no wrong answer — a capability case without the near-miss it is meant to catch "
            "measures nothing, because any refusal at all would score correct")
        assert c["grounding"], f"{c['id']} records no provenance — every case must say where its key came from"
        assert c["check"], f"{c['id']} has no executable check"


def test_the_answer_key_boxes_cannot_contradict_each_other():
    """The five boxes over-determine each other on purpose, so an editing mistake shows up as a contradiction
    rather than as a plausible new label. Each clause below is one way a hand-edited case has to fail loudly:
    an `answer` with nowhere to route it, a `refuse` that also names an admissible mode, a `propose` whose mode
    is already in the corpus (in which case the honest action is `answer`, not a campaign)."""
    for c in cb.CASES:
        cid, act = c["id"], c["action"]
        assert act in cb.ACTIONS, f"{cid}: {act!r} is not one of {cb.ACTIONS}"
        assert c["governed_by"] in ("capability_registry", "corpus_storage", "data_quality"), (
            f"{cid}: unknown governor {c['governed_by']!r}")
        for m in c["represented_in"] + c["admissible_modes"] + tuple(c["mode_constraint"] or ()):
            assert m in capability.ELONGATION_MODES, f"{cid} names undeclared elongation model {m!r}"
        assert set(c["admissible_modes"]) <= set(c["represented_in"]), (
            f"{cid}: {sorted(set(c['admissible_modes']) - set(c['represented_in']))} is admissible but not "
            "represented — the corpus cannot hold runs of a mode whose model does not do the thing")

        if act in ("answer", "qualify"):
            assert c["admissible_modes"], f"{cid} is an {act} case with no admissible mode"
            assert c["answer_mode"] in c["admissible_modes"], (
                f"{cid} routes to {c['answer_mode']!r}, which is not in {c['admissible_modes']}")
            assert c["why_not"] == (), f"{cid} is answerable and still carries why_not {c['why_not']}"
        else:
            assert c["answer_mode"] is None, f"{cid} is a {act} case and still names an answer_mode"
            assert c["admissible_modes"] == (), f"{cid} is a {act} case with admissible modes"

        if act == "refuse":
            assert c["represented_in"] == (), (
                f"{cid} refuses, but {c['represented_in']} represents it — the honest action there is "
                "`propose` (run it in that mode), not a flat refusal")
        if act == "propose":
            assert c["represented_in"], f"{cid} proposes a campaign in no mode at all"
            assert not (set(c["represented_in"]) & set(capability.MODES_IN_CORPUS) & set(c["admissible_modes"])), (
                f"{cid} proposes a campaign in a mode the corpus already has — that is a query to re-issue")
        if act == "flag":
            assert c["data_defect"], f"{cid} flags nothing — a flag case must name the defect"
        assert bool(c["data_defect"]) == (act == "flag"), (
            f"{cid}: data_defect and action `flag` must appear together; a defect worth recording is worth "
            "flagging, and a flag with no defect is an unfalsifiable label")
        if c["storage_gap"]:
            assert c["governed_by"] == "corpus_storage", f"{cid} names a storage gap but is not governed by one"

        for w in c["why_not"]:
            assert w in cb.WHY_NOT_REGISTRY + cb.WHY_NOT_CORPUS, f"{cid}: unknown why_not token {w!r}"
        if c["governed_by"] == "capability_registry":
            assert all(w in cb.WHY_NOT_REGISTRY for w in c["why_not"]), (
                f"{cid} is registry-governed and uses a CAPBENCH-local token {c['why_not']}")
        else:
            assert c["requires"] == () and c["blocking"] == {}, (
                f"{cid} is governed by {c['governed_by']} and still makes a capability-registry claim "
                f"(requires={c['requires']}, blocking keys={sorted(c['blocking'])}) — filing a storage gap or "
                "a QC defect under the registry would credit the registry with a refusal it plays no part in")
            assert all(w in cb.WHY_NOT_CORPUS for w in c["why_not"]), (
                f"{cid} is not registry-governed and uses a registry token {c['why_not']}")
            assert tuple(c["represented_in"]) == tuple(capability.ELONGATION_MODES), (
                f"{cid} is not a capability case, so every elongation model represents it; "
                f"represented_in reads {c['represented_in']}")


def test_every_check_kind_has_a_runner_in_this_file():
    """Section 6 promises the key is 'executable where possible'. A `check` box nothing executes is an
    assertion wearing a check's clothes, so the declared kinds and the kinds this suite actually runs must be
    the same set — in both directions."""
    declared = set(cb.CHECK_KINDS)
    used = {c["check"]["kind"] for c in cb.CASES}
    assert used <= declared, f"cases use check kinds nothing declares: {sorted(used - declared)}"
    assert declared - used == set(), (
        f"CHECK_KINDS declares {sorted(declared - used)}, which no case uses — a kind with no case is a "
        "runner nobody exercises")
    assert declared <= RUNNERS, f"no runner in this file executes: {sorted(declared - RUNNERS)}"


def test_near_neighbour_pairs_differ_in_exactly_one_field_of_r():
    """THE measurement, per CAPBENCH-1: 'Two cases differing in EXACTLY ONE field of `r`, where the correct
    action flips.' A system doing keyword matching sees the same nouns in both members and answers identically;
    only one that reads the changed field and checks it against what the model computes splits them. If a pair
    ever drifts to differing in two fields, the split stops being attributable to either — so this test is what
    keeps the pairs a measurement rather than a pair of unrelated cases."""
    groups = cb.pairs()
    assert groups, "no near-neighbour pairs — the easy cases establish a floor; the pairs are the measurement"
    for name, members in groups.items():
        assert len(members) == 2, f"pair {name} has {len(members)} members; a near-neighbour pair is two"
        a, b = members
        differ = sorted(f for f in cb.R_FIELDS if a["r"][f] != b["r"][f])
        assert len(differ) == 1, (
            f"pair {name} ({a['id']} vs {b['id']}) differs in {differ} — exactly one field of r may move, or "
            "the flip in the label cannot be attributed to any of them")
        assert differ[0] == a["pair_differs_in"] == b["pair_differs_in"], (
            f"pair {name} declares it turns on {a['pair_differs_in']!r} but actually differs in {differ[0]!r}")
        assert a["action"] != b["action"], (
            f"pair {name} keeps action {a['action']!r} on both sides — a near-neighbour pair whose label does "
            "not flip tests nothing that the two cases do not already test separately")


def test_the_typed_tuple_is_the_one_the_paper_pre_registers():
    """`r` is the paper's object, not ours. If §3's field list is ever edited, this corpus must be edited with
    it rather than quietly encoding a different tuple under the same name."""
    if not MAIN_TEX.is_file():
        pytest.skip(f"{MAIN_TEX.relative_to(REPO).as_posix()} is not in this tree — the pin on main.tex sec.3's "
                    "field list is unmeasurable here, not satisfied")
    tex = MAIN_TEX.read_text(encoding="utf-8", errors="replace")
    sentence = ("a typed tuple: entity, intervention, observable, granularity, regulatory dependencies, and "
                "evidence coverage")
    assert sentence in tex, (
        "main.tex no longer contains the sentence that defines r's six fields; capbench_cases.R_FIELDS was "
        f"pinned to {cb.R_FIELDS} and must be re-checked against whatever replaced it")
    named = tuple(f.replace(" ", "_") for f in
                  sentence.split(":", 1)[1].replace(", and ", ", ").strip().split(", "))
    assert named == cb.R_FIELDS, f"main.tex sec.3 names {named}; R_FIELDS says {cb.R_FIELDS}"


def test_the_registry_tokens_are_the_ones_capability_check_actually_emits():
    """WHY_NOT_REGISTRY is a copy of `capability.check()`'s vocabulary, and a copy rots. Rather than grepping
    the source, this drives the registry over every (capability, mode) cell and collects the tokens it really
    produces — which is also a standing check that no fourth branch appeared without the benchmark noticing."""
    emitted = set()
    for c in capability.CAPABILITIES:
        for m in capability.ELONGATION_MODES:
            res = capability.check(c.key, m)
            if res.get("why_not"):
                emitted.add(res["why_not"])
    assert emitted == set(cb.WHY_NOT_REGISTRY), (
        f"capability.check emits {sorted(emitted)}; WHY_NOT_REGISTRY says {sorted(cb.WHY_NOT_REGISTRY)}")
    assert not (set(cb.WHY_NOT_CORPUS) & emitted), (
        "a CAPBENCH-local token collides with a registry token; the two vocabularies must stay disjoint or "
        "the benchmark cannot tell a storage gap from a capability gap")


def test_the_balance_record_is_the_corpus_it_describes():
    """`BALANCE` is where the corpus admits it does not meet CAPBENCH-1's targets. An admission that drifts
    from the thing it admits about is worse than none, because it reads as a checked statement. Recomputed
    here so adding a case without updating it fails."""
    import collections
    assert cb.BALANCE["n_cases"] == len(cb.CASES)
    assert cb.BALANCE["by_action"] == dict(collections.Counter(c["action"] for c in cb.CASES))
    assert cb.BALANCE["by_governor"] == dict(collections.Counter(c["governed_by"] for c in cb.CASES))
    assert cb.BALANCE["n_pairs"] == len(cb.pairs())
    covered = {w for c in cb.CASES for w in c["why_not"] if w in cb.WHY_NOT_REGISTRY}
    assert covered == set(cb.BALANCE["registry_why_not_covered"]) == set(cb.WHY_NOT_REGISTRY), (
        f"the corpus covers registry tokens {sorted(covered)}; CAPBENCH-1's balance requirement is that all "
        f"three of {sorted(cb.WHY_NOT_REGISTRY)} appear")
    fields = {c["pair_differs_in"] for c in cb.CASES if c["pair_differs_in"]}
    assert fields == set(cb.BALANCE["pair_fields_exercised"])


# ------------------------------------------------------------------------------------------------------------
# 2 · THE SEED CASE. Every number C3.1 asserts, recomputed from data/qc_via_1_scan.json.
# ------------------------------------------------------------------------------------------------------------

def test_the_rpme_case_still_matches_the_scan_it_was_derived_from():
    """The most important test in this file. C3.1's key is a restatement of `data/qc_via_1_scan.json`, so the
    only thing that makes it a measurement rather than a claim is that it is recomputed from the scan.

    Recomputed here, not compared: the counts are rebuilt from `rows` rather than read from the file's own
    `counts` block (which is itself checked against the recount), and the NEGATIVE halves are asserted too —
    that no dir of this design sits above the floor, and that no other design sits below it. Those two are
    what make the case's story specific. "15 dirs are below the floor" is compatible with a corpus where the
    collapse is spread thinly across many designs; "all 15 are one design, and that design has no dir above
    the floor" is the finding, and only the negative checks pin it.

    The link from a directory name to a gene is measured too, via `gene_scope.json`'s `ko_index`. Nothing in
    the scan says "rpmE" — the paths say `gene_knockout_001943` — so a case that named the gene without
    checking the index would be asserting the one step of the chain a reader is least able to verify."""
    scan, case = _scan(), _case("C3.1")
    m, defect = case["measured"], case["data_defect"]
    rows = scan["rows"]
    floor = scan["floor_aa_per_s"]

    assert floor == m["floor_aa_per_s"], f"scan floor {floor}, case says {m['floor_aa_per_s']}"
    assert floor == qc.TRANSLATION_COLLAPSE_AA_PER_S, (
        f"the scan ran against a {floor} aa/s floor and qc.check_generation now applies "
        f"{qc.TRANSLATION_COLLAPSE_AA_PER_S} — the case's story about what the floor would have caught no "
        "longer describes the code")

    assert len(rows) == scan["n_read"] == m["generation_dirs_read"], (
        f"scan holds {len(rows)} rows, declares n_read {scan['n_read']}, case says "
        f"{m['generation_dirs_read']}")

    # Recount from `rows`, then check the file's own summary against the recount. A summary block that
    # disagreed with the rows it summarises would otherwise be believed by both the case and this test.
    below = [r for r in rows if r["elongation_mean"] is not None and r["elongation_mean"] < floor]
    above = [r for r in rows if r["elongation_mean"] is not None and r["elongation_mean"] >= floor]
    unknown = [r for r in rows if r["elongation_mean"] is None]
    assert len(below) == m["below_floor"], f"recount {len(below)} below the floor, case says {m['below_floor']}"
    assert len(above) == m["above_floor"], f"recount {len(above)} above the floor, case says {m['above_floor']}"
    assert len(unknown) == m["unknown"], (
        f"recount {len(unknown)} dirs with NO readable elongation channel, case says {m['unknown']} — an "
        "unknown is never an 'ok', so this count cannot be folded into either side")
    assert scan["counts"].get("translation_collapse", 0) == len(below), "the scan's own counts disagree with its rows"
    assert scan["counts"].get("ok", 0) == len(above), "the scan's own counts disagree with its rows"

    # Which design(s) the below-floor dirs belong to. The scan path is
    # `<campaign>/<design_dir>/<seed>/generation_XXXXXX/...`, so the design dir is component 1.
    designs_below = {r["path"].split("/")[1] for r in below}
    assert designs_below == set(m["below_floor_designs"]), (
        f"the below-floor dirs belong to {sorted(designs_below)}; the case says {m['below_floor_designs']}. "
        "'15 dirs are below the floor' is compatible with the collapse being spread thinly over many "
        "designs; 'all 15 are ONE design' is the finding, and this is the assertion that carries it")
    assert designs_below == {case["check"]["design_dir"]}, (
        f"the case's check targets {case['check']['design_dir']!r}, which is not the design the scan puts "
        f"below the floor ({sorted(designs_below)})")
    assert defect["design_key"].startswith("gene_knockout/"), (
        f"C3.1's data_defect names {defect['design_key']!r}; the scan path it is derived from is a "
        "gene_knockout design, so the two are describing different things")

    # The design's own dirs: all of them, and all at exactly the asserted rate. The `>= floor` half is the
    # negative check — one healthy generation in this design would make "translationally dead throughout" false.
    dirs = [r for r in rows if r["path"].split("/")[1] == case["check"]["design_dir"]]
    assert len(dirs) == m["design_generation_dirs"], (
        f"{len(dirs)} generation dirs under {case['check']['design_dir']}, case says "
        f"{m['design_generation_dirs']}")
    assert len(dirs) == m["design_dirs_below_floor"] == len(below), (
        "the case's story is that the design's dirs and the below-floor dirs are the same set; they are not")
    assert {r["elongation_mean"] for r in dirs} == {m["design_elongation_mean_aa_per_s"]}, (
        f"the design's elongation means are {sorted({r['elongation_mean'] for r in dirs})}; the case asserts "
        f"exactly {m['design_elongation_mean_aa_per_s']} everywhere")
    assert not [r for r in dirs if r["elongation_mean"] >= floor], (
        "at least one generation of this design is above the floor — 'translationally dead throughout' is no "
        "longer what the scan says")
    assert all(r["verdict"] == "translation_collapse" for r in dirs), (
        "the scan's own per-row verdict for this design is no longer translation_collapse")

    # The directory-name-to-gene link, which nothing in the scan itself supplies.
    from cellarium import scope
    entry = scope._gene_scope().get(case["check"]["gene"])
    assert entry, (f"{case['check']['gene']!r} is not in data/cache/gene_scope.json (the complete 4724-gene "
                   "registry) — the case names a gene the model does not know")
    assert entry["ko_index"] == case["check"]["ko_index"], (
        f"gene_scope puts {case['check']['gene']} at ko_index {entry['ko_index']}; the case ties it to "
        f"{case['check']['ko_index']} and therefore to directory {case['check']['design_dir']}")
    assert case["check"]["design_dir"].endswith(f"{entry['ko_index']:06d}"), (
        f"directory {case['check']['design_dir']} does not encode ko_index {entry['ko_index']} — the link "
        "from the scan's paths to the gene name is broken")


def test_the_rpme_generation_level_claim_matches_the_manifest():
    """The half of C3.1 the scan cannot tell you: how close this came to being read as evidence.

    `divided` is `full_chromosome_end == 2 and n_steps > 10`, so the per-generation record is where the
    near-miss is visible — a generation that divided and scored `ok` at 0.0 aa/s. Recomputed from
    `per_generation` and `generation_qc` rather than asserted, because the case's most quotable numbers (9
    divided, 8 of them `ok`) are exactly the ones a reader will take on trust.

    This also pins the CORRECTION the case carries. Row-level `qc` was never `ok` here: three seeds were
    caught by `over_replicated` and one by `implausible_channel`, neither of which has anything to do with
    translation, and all four rows were already `reportable=False`. C3.1 says so in `must_not_say`, and this
    test is what keeps that statement true."""
    case = _case("C3.1")
    m = case["measured"]
    con, ded = _duck()
    try:
        rows = con.execute(
            f"SELECT label, qc, reportable, generation_qc, per_generation FROM {ded} "
            "WHERE label LIKE '%rpmE%' ORDER BY label").fetchall()
    finally:
        con.close()
    if not rows:
        pytest.skip("no KO:rpmE rows in this manifest — the row-level half of C3.1 is unmeasurable here")
    grown = _grown_locally()
    if grown and len(rows) != m["manifest_rows"]:
        pytest.skip(f"{grown} — KO:rpmE reads {len(rows)} rows and the pin of {m['manifest_rows']} counts "
                    "only the shipped ones")

    assert len(rows) == m["manifest_rows"], f"{len(rows)} KO:rpmE rows, case says {m['manifest_rows']}"
    assert sum(1 for r in rows if r[2]) == m["manifest_rows_reportable"], (
        f"{sum(1 for r in rows if r[2])} of the KO:rpmE rows are reportable; the case asserts "
        f"{m['manifest_rows_reportable']}, and its whole correction rests on that being zero")
    import collections
    assert dict(collections.Counter(r[1] for r in rows)) == m["manifest_row_qc"], (
        f"row-level qc is {dict(collections.Counter(r[1] for r in rows))}, case says {m['manifest_row_qc']}")
    assert "ok" not in {r[1] for r in rows}, (
        "a KO:rpmE row reads qc='ok' — C3.1's must_not_say states plainly that the row level was NOT the "
        "near-miss, and that statement would now be false")

    divided = ok = total = 0
    for _lbl, _qc, _rep, gqc, per_gen in rows:
        gens = json.loads(per_gen) if per_gen else []
        stats = json.loads(gqc) if gqc else []
        assert len(gens) == len(stats), "per_generation and generation_qc disagree on how many generations ran"
        total += len(gens)
        divided += sum(1 for g in gens if g.get("divided"))
        ok += sum(1 for s in stats if s == "ok")
        # The QUESTION says "the first two generations of every seed", so that has to be true too. A case
        # whose question overstates its data is no better than one whose key does, and this is the only
        # assertion that would catch it.
        assert [i for i, s in enumerate(stats) if s == "ok"] == [0, 1], (
            f"the `ok` generations of this seed are at indices {[i for i, s in enumerate(stats) if s == 'ok']}, "
            "and C3.1's question states they are the first two of every seed")
    assert total == m["design_generation_dirs"], (
        f"the manifest records {total} generations for this design; the scan read "
        f"{m['design_generation_dirs']} dirs — the two views of the same runs disagree")
    assert divided == m["generations_divided"], (
        f"{divided} generations recorded divided=True, case says {m['generations_divided']}")
    assert ok == m["generations_recorded_generation_qc_ok"], (
        f"{ok} generations recorded generation_qc='ok' at 0.0 aa/s, case says "
        f"{m['generations_recorded_generation_qc_ok']} — this is the number that makes C3.1 a case")
    assert ok <= divided, "more generations scored `ok` than divided, which check_generation cannot produce"


def test_the_unreadable_twin_is_really_unreadable_and_really_looks_clean():
    """C3.2 is the near-neighbour that makes C3.1 a measurement rather than an anecdote, and it is `qualify`
    for one reason: the channel that convicted KO:rpmE was never recorded for KO:glmS and the local raw is
    gone. Both halves of that are checked here, because the case would collapse into a different label if
    either changed — if the raw came back the honest action is to re-read it, and if the rows stopped being
    reportable there would be nothing tempting to over-answer from.

    The `looks clean` half matters as much as the `unreadable` half. All four rows are `reportable=True` with
    every generation_qc `ok`, so nothing in the corpus marks them; a system that answers "viable" from them is
    not ignoring a warning, it is reading rows that carry none. That is the whole difficulty of the case."""
    scan, case = _scan(), _case("C3.2")
    chk, m = case["check"], case["measured"]
    from cellarium import manifest
    scan_roots = {manifest._portable_runpath("runs/" + "/".join(r["path"].split("/")[:3]))
                  for r in scan["rows"]}
    assert len(scan_roots) == m["scanned_run_roots"], (
        f"the scan covers {len(scan_roots)} distinct run roots, case says {m['scanned_run_roots']}")
    in_scan = [r for r in scan["rows"] if r["path"].split("/")[1] == chk["design_dir"]]
    assert len(in_scan) == m["generation_dirs_in_the_scan"], (
        f"{len(in_scan)} generation dirs of {chk['design_dir']} are in the scan; C3.2 asserts "
        f"{m['generation_dirs_in_the_scan']}. If the raw is back, this design is now answerable the way C3.1 "
        "is and the `qualify` label has to be revisited")

    reclaim = REPO / "data" / "hf_reclaim_manifest.json"
    if not reclaim.is_file():
        pytest.skip(f"{reclaim.relative_to(REPO).as_posix()} is not in this tree — 'the raw was deleted to HF' "
                    "is unverifiable here, and an unverifiable premise must not read as a verified one")
    rec = json.loads(reclaim.read_text(encoding="utf-8"))
    rec_roots = {manifest._portable_runpath(e["run_root"]) for e in rec["deleted"]}
    assert len(rec_roots) == m["reclaimed_run_roots"], (
        f"the reclaim manifest lists {len(rec_roots)} run roots, case says {m['reclaimed_run_roots']}")

    con, ded = _duck()
    try:
        design = con.execute(f"SELECT simout_path, reportable, qc, generations, generation_qc FROM {ded} "
                             f"WHERE simout_path LIKE '%{chk['design_dir']}%'").fetchall()
        rows = con.execute(f"SELECT simout_path, reportable FROM {ded}").fetchall()
    finally:
        con.close()
    if not design:
        pytest.skip(f"no {chk['design_dir']} rows in this manifest — C3.2 is unmeasurable here, which is not "
                    "the same as the design being absent")
    import collections
    assert len(design) == m["manifest_rows"], f"{len(design)} rows, case says {m['manifest_rows']}"
    assert sum(1 for r in design if r[1]) == m["manifest_rows_reportable"], (
        "C3.2's difficulty is that every one of these rows is reportable; that is no longer true")
    assert dict(collections.Counter(r[2] for r in design)) == m["manifest_row_qc"]
    assert {r[3] for r in design} == {m["generations_per_row"]}
    ok = sum(1 for r in design for s in (json.loads(r[4]) if r[4] else []) if s == "ok")
    assert ok == m["generations_recorded_generation_qc_ok"], (
        f"{ok} generations of this design recorded generation_qc='ok'; case says "
        f"{m['generations_recorded_generation_qc_ok']}")
    # The direction that makes the pair uncomfortable: this design looks CLEANER than KO:rpmE by every stored
    # signal (16 of 16 vs 8 of 15), and it is the one nothing can be checked on.
    con2, ded2 = _duck()
    try:
        per_gen = con2.execute(f"SELECT per_generation FROM {ded2} "
                               f"WHERE simout_path LIKE '%{chk['design_dir']}%'").fetchall()
    finally:
        con2.close()
    divided = sum(1 for (blob,) in per_gen for g in (json.loads(blob) if blob else []) if g.get("divided"))
    assert divided == m["generations_divided"] == ok, (
        f"{divided} generations of this design divided and {ok} scored `ok`; C3.2's question states every one "
        f"of its {m['generations_divided']} generations did both")
    assert ok > _case("C3.1")["measured"]["generations_recorded_generation_qc_ok"], (
        "KO:glmS no longer looks cleaner than KO:rpmE by the stored signals; the pair's point is that the "
        "unverifiable design is the more inviting one, and that would no longer hold")
    present = sum(1 for r in design if r[0] and manifest._portable_runpath(r[0]) in rec_roots)
    assert (present == m["run_roots_in_the_reclaim_manifest"]) == chk["expect_in_reclaim_manifest"], (
        f"{present} of this design's run roots are in the reclaim manifest; case says "
        f"{m['run_roots_in_the_reclaim_manifest']}")

    from cellarium import scope
    entry = scope._gene_scope().get(chk["gene"])
    assert entry and entry["ko_index"] == chk["ko_index"], (
        f"gene_scope does not put {chk['gene']} at ko_index {chk['ko_index']}, so the directory-to-gene link "
        "C3.2 states is broken")

    # The load-bearing half of C3.2's first `must_say`: no shard carries an elongation channel, which is why
    # re-reading the raw is the ONLY way to settle this and why deleting the raw closed the question. Asserted
    # against the shipped schema rather than restated, because the day a shard gains such a column, C3.2 stops
    # being a `qualify` and becomes a query.
    con3, _ = _duck()
    try:
        cols = {r[0] for r in con3.execute(
            "DESCRIBE SELECT * FROM read_parquet("
            f"'{manifest.MANIFEST_DIR.as_posix()}/*.parquet', union_by_name=true)").fetchall()}
    finally:
        con3.close()
    elong = sorted(c for c in cols if "elong" in c.lower() and c != "elongation_model")
    assert not elong, (
        f"the shards now carry {elong} — C3.2 says no shard carries an elongation column, which is the whole "
        "reason its question cannot be answered from the manifest; that sentence needs re-checking")

    # The corpus-level bound the same scan puts on any answer of this shape.
    reportable = [r for r in rows if r[1]]
    with_raw = [r for r in reportable if r[0] and manifest._portable_runpath(r[0]) in scan_roots]
    grown = _grown_locally()
    if grown and len(reportable) != m["reportable_rows"]:
        pytest.skip(f"{grown} — reportable reads {len(reportable)} and the pin of {m['reportable_rows']} "
                    "counts only the shipped rows")
    assert len(reportable) == m["reportable_rows"], (
        f"{len(reportable)} reportable rows, case says {m['reportable_rows']}")
    assert len(with_raw) == m["reportable_rows_with_local_raw"], (
        f"{len(with_raw)} reportable rows have local raw in the scan, case says "
        f"{m['reportable_rows_with_local_raw']}")
    assert len(reportable) - len(with_raw) == m["reportable_rows_unread"], (
        f"{len(reportable) - len(with_raw)} reportable rows were never re-read; case says "
        f"{m['reportable_rows_unread']}. This is the number C3.2 exists to make the system state, and "
        "absence of the channel in those rows is not evidence of viability")

    # The claim that zero currently-reportable rows flip: no below-floor dir belongs to a reportable row.
    below_roots = {manifest._portable_runpath("runs/" + "/".join(r["path"].split("/")[:3]))
                   for r in scan["rows"] if r["verdict"] == "translation_collapse"}
    flipped = [r for r in reportable if r[0] and manifest._portable_runpath(r[0]) in below_roots]
    assert len(flipped) == m["reportable_rows_that_flip"], (
        f"{len(flipped)} reportable rows sit on raw that is below the translation floor; the case asserts "
        f"{m['reportable_rows_that_flip']}. If this is no longer zero, the dataset card and the reportable "
        "counts in docs/REPORT_EVIDENCE.md move with it, in the same pass")


# ------------------------------------------------------------------------------------------------------------
# 3 · Everything a case NAMES has to exist: capabilities, genes, designs, columns, invariants, QC verdicts.
# ------------------------------------------------------------------------------------------------------------

def test_every_capability_a_case_requires_is_declared():
    """An undeclared capability key silently makes `check()` return `can_answer: None` — neither a refusal nor
    an answer — so a case built on one would grade against a verdict the registry never reached."""
    declared = {c.key for c in capability.CAPABILITIES}
    for c in cb.CASES:
        unknown = [k for k in c["requires"] if k not in declared]
        assert not unknown, (
            f"{c['id']} requires {unknown}, which capability.CAPABILITIES does not declare. An undeclared "
            f"mechanism is not evidence of absence — declare it with markers so the answer is probed. "
            f"Declared: {sorted(declared)}")


def test_the_registry_reproduces_every_registry_governed_answer_key():
    """The non-drift guard for the four capability cases: derive `represented_in`, `admissible_modes`,
    `blocking` and `why_not` by driving `capability.check()`, and require the stored labels to match.

    Stored AND derived, both, is the point. Freezing the label is what makes the benchmark pre-registered;
    deriving it is what stops the frozen label describing a registry that has since changed. If someone gives
    `ppgpp_stringent_response` a `holds_in` that includes `kinetic`, C1.2 stops being a refusal — and this test
    is what forces that to be a decision rather than a silent re-labelling of the paper's fourth contribution.

    Note `mode_constraint`. C6.1 asks about the coarse-kinetic model's OWN behaviour, so the derivation must
    run over that mode alone; without the constraint it would read the question as answerable from the
    steady-state rows, which are the very thing being questioned."""
    for c in cb.CASES:
        if c["governed_by"] != "capability_registry":
            continue
        modes = tuple(c["mode_constraint"] or capability.ELONGATION_MODES)
        represented, admissible, blocking = [], [], {}
        for mode in modes:
            bad = {}
            for key in c["requires"]:
                res = capability.check(key, mode)
                if not res["can_answer"]:
                    bad[key] = res["why_not"]
            caps = [capability.get(k) for k in c["requires"]]
            if all(cap.present and mode in cap.holds_in for cap in caps):
                represented.append(mode)
            if bad:
                blocking[mode] = bad
            else:
                admissible.append(mode)
        assert tuple(represented) == tuple(c["represented_in"]), (
            f"{c['id']}: the registry represents {c['requires']} in {tuple(represented)}, the case stores "
            f"{c['represented_in']}")
        assert tuple(admissible) == tuple(c["admissible_modes"]), (
            f"{c['id']}: the registry can answer in {tuple(admissible)}, the case stores "
            f"{c['admissible_modes']}")
        assert blocking == c["blocking"], (
            f"{c['id']}: per-mode blocking is {blocking}, the case stores {c['blocking']}")
        derived_why = () if admissible else tuple(sorted({t for v in blocking.values() for t in v.values()}))
        assert derived_why == tuple(c["why_not"]), (
            f"{c['id']}: the registry's reasons are {derived_why}, the case stores {tuple(c['why_not'])}")


def test_every_gene_a_case_names_is_a_gene_the_model_knows():
    """`gene_scope.json` is the COMPLETE registry (4724 entries), so a symbol missing from it is genuinely
    unknown rather than merely un-warned-about — the distinction `scope.footprint_known` documents, and the one
    a case naming a typo'd gene would fall through."""
    from cellarium import scope
    known = scope._gene_scope()
    if not known:
        pytest.skip("data/cache/gene_scope.json is absent or empty — gene existence is unmeasurable here, "
                    "which is not the same as the genes being absent")
    named = {"C3.1": ("rpmE",), "C3.2": ("glmS",), "C2.1": ("murA",), "C2.2": ("murA",),
             "C4.1": ("rpmE",), "C4.2": ("rpmE",),
             # The second pass. cytR is the one that matters most here: C9's whole case is that a `tf_activity`
             # variant index is NOT a ko_index, so the gene has to be confirmed to exist in its own right
             # rather than through the variant number the run was launched with.
             "C9.1": ("cytR",), "C9.2": ("cytR",), "C10.1": ("leuB",), "C11.1": ("cysE", "metA")}
    for cid, genes in named.items():
        _case(cid)                                   # the case must still exist under that id
        for g in genes:
            assert g in known, f"{cid} names {g!r}, which is not among gene_scope.json's {len(known)} genes"
    # Both `check` boxes that carry a gene must agree with the registry about which index it is — that link is
    # what turns a scan path like `gene_knockout_001943` into "rpmE", and it is the step a reader is least
    # able to verify by eye.
    for cid in ("C3.1", "C3.2"):
        chk = _case(cid)["check"]
        assert known[chk["gene"]]["ko_index"] == chk["ko_index"], (
            f"{cid} ties {chk['gene']!r} to ko_index {chk['ko_index']}; gene_scope says "
            f"{known[chk['gene']]['ko_index']}")


def test_every_design_a_case_names_is_in_the_corpus():
    """A case that flags or refuses over a design must be flagging a design that is really there. The access
    idiom is `store.list_results()` + `survey.design_key`, matching tests/test_corpus_integrity.py — reading
    the parquet directly would test a different corpus from the one every consumer sees."""
    from cellarium import survey
    keys = {survey.design_key(r) for r in _rows()}
    wanted = [(c["id"], c["data_defect"]["design_key"]) for c in cb.CASES
              if c["data_defect"] and c["data_defect"]["design_key"]]
    wanted += [(c["id"], k) for c in cb.CASES for k in (c["measured"] or {}).get("design_keys", ())]
    assert wanted, "no case names a design — this check would otherwise pass over an empty set"
    for cid, key in wanted:
        assert key in keys, (
            f"{cid} names design {key!r}, which is not in the corpus. Nearby: "
            f"{sorted(k for k in keys if k.split('/')[0] == key.split('/')[0])[:6]}")
    prefixes = {c["id"]: c["check"]["design_key_prefix"] for c in cb.CASES
                if c["check"]["kind"] == "manifest_design"}
    for cid, prefix in prefixes.items():
        assert any(k.startswith(prefix) for k in keys), f"{cid} expects designs under {prefix!r}; none exist"


def test_every_flagged_defect_names_exactly_one_locus_and_that_locus_exists():
    """A `data_defect` says WHERE the defective rows are, and after C9/C10 there are two possible answers: a
    corpus design, or a run in one of the validation artifacts. Both keys are present on every defect with the
    unused one None, so this test can require exactly one — the shape being uniform is what lets a grader rely
    on it instead of inferring the locus from which keys happen to be there.

    THE DISTINCTION IS LOAD-BEARING, not tidiness. The validation runs were deliberately never appended to the
    manifest (each script's docstring says so), so a case flagging one and checked against the corpus would
    find no contradicting row and pass for want of anything to contradict it — a vacuous green on exactly the
    cases whose point is that the data looks clean. Conversely a corpus design must be resolvable through
    `store.list_results` + `survey.design_key`, the boundary every other consumer reads."""
    from cellarium import survey
    defects = [(c["id"], c["data_defect"]) for c in cb.CASES if c["data_defect"]]
    assert defects, "no case carries a data_defect — this check would pass over an empty set"
    for cid, d in defects:
        assert set(d) == {"design_key", "validation_file", "run_key", "qc_verdict", "defect", "route"}, (
            f"{cid}'s data_defect carries {sorted(d)}; the shape must be uniform across every defect")
        corpus, validation = bool(d["design_key"]), bool(d["validation_file"] and d["run_key"])
        assert corpus != validation, (
            f"{cid} names {'both' if corpus and validation else 'neither'} locus "
            f"(design_key={d['design_key']!r}, validation_file={d['validation_file']!r}, "
            f"run_key={d['run_key']!r}) — exactly one must say where the defective rows are")
        if validation:
            doc = _validation(d["validation_file"])
            assert d["run_key"] in doc["runs"], (
                f"{cid} flags run {d['run_key']!r}, which {d['validation_file']} does not record")
            # ... and it must NOT be a corpus design, or the two loci would be describing the same rows and
            # the distinction this test rests on would be cosmetic after all.
            keys = {survey.design_key(r) for r in _rows()}
            assert d["run_key"] not in keys, (
                f"{cid} flags {d['run_key']!r} as a validation run and the corpus has a design of that name")


def test_every_corpus_column_a_case_names_exists_in_the_shards():
    """`check` boxes of kind `manifest_column` name a column by string. A renamed or dropped column would make
    the check silently query nothing, so the column list is read back off the parquet itself."""
    con, _ded = _duck()
    try:
        from cellarium import manifest
        cols = {r[0] for r in con.execute(
            "DESCRIBE SELECT * FROM read_parquet("
            f"'{manifest.MANIFEST_DIR.as_posix()}/*.parquet', union_by_name=true)").fetchall()}
    finally:
        con.close()
    assert cols, "DESCRIBE returned no columns — the shard could not be read, which is not an empty schema"
    named = {(c["id"], c["check"]["column"]) for c in cb.CASES if c["check"]["kind"] == "manifest_column"}
    named |= {(c["id"], "species_panel") for c in cb.CASES if c["check"]["kind"] == "species_panel"}
    assert named, "no case names a corpus column"
    for cid, col in sorted(named):
        assert col in cols, f"{cid} names column {col!r}; the shards carry {sorted(cols)[:12]}..."


def test_every_invariant_a_case_cites_exists_in_the_catalogue():
    """`data/INVARIANTS.json` is the machine-readable corpus-hygiene catalogue a cloner is supposed to meet
    (H-17a). A case citing an id that is not in it points a reader at nothing."""
    if not INVARIANTS.is_file():
        pytest.skip(f"{INVARIANTS.relative_to(REPO).as_posix()} is not in this tree — the invariant citations "
                    "are unresolvable here, not wrong")
    ids = {i["id"] for i in json.loads(INVARIANTS.read_text(encoding="utf-8"))["invariants"]}
    assert ids, "INVARIANTS.json parsed but declares no invariants"
    for c in cb.CASES:
        assert c["invariants"], f"{c['id']} cites no invariant"
        bad = [i for i in c["invariants"] if i not in ids]
        assert not bad, f"{c['id']} cites {bad}, which INVARIANTS.json does not define (it has {len(ids)})"


def test_the_qc_verdicts_a_case_cites_are_real_and_correctly_attributed():
    """Both flag cases name a QC verdict, and the two come from DIFFERENT places: `translation_collapse` is a
    `qc.QCStatus` member emitted by `check_generation`, while `noop_knockout` is a supersede reason the
    WELL-NOOP-1 audit wrote into the manifest's `qc` column and no code path emits. Asserting that split keeps
    a reader from assuming both are enum members — and keeps a future edit from moving one without the other."""
    statuses = {s.value for s in qc.QCStatus}
    assert "translation_collapse" in statuses, "qc.QCStatus no longer carries translation_collapse"
    assert "noop_knockout" not in statuses, (
        "noop_knockout has become a QCStatus member; C2.1's grounding says it is an audit-written manifest "
        "value, and that sentence now needs re-checking")
    # The second pass's two verdicts are both real enum members, and asserting that is the whole reason they
    # were chosen over a new CAPBENCH-local token: `empty` is what check_result returns for a result with no
    # readable generation (C9.1's zero-length run) and `no_division` is what check_generation returns when
    # `divided` is False (C10.1's capped terminal generation). If either leaves the enum, the cases stop
    # citing a verdict any code path can emit, which is the state `noop_knockout` is explicitly marked as.
    for v in ("empty", "no_division"):
        assert v in statuses, (
            f"{v!r} is no longer a qc.QCStatus member; the case citing it now names a verdict nothing emits, "
            f"the way noop_knockout does — say so in its grounding or pick a verdict that exists")
    assert set(cb.QC_VERDICTS) - statuses == {"noop_knockout"}, (
        f"exactly one declared verdict may be outside the enum (noop_knockout, the audit-written manifest "
        f"value); outside it now: {sorted(set(cb.QC_VERDICTS) - statuses)}")
    for c in cb.CASES:
        if not c["data_defect"]:
            continue
        v = c["data_defect"]["qc_verdict"]
        assert v in cb.QC_VERDICTS, f"{c['id']} cites verdict {v!r}, not in QC_VERDICTS {cb.QC_VERDICTS}"
    con, ded = _duck()
    try:
        present = {r[0] for r in con.execute(f"SELECT DISTINCT qc FROM {ded}").fetchall()}
    finally:
        con.close()
    assert present, "no qc values readable from the corpus"
    for c in cb.CASES:
        if c["data_defect"] and c["data_defect"]["qc_verdict"] == "noop_knockout":
            assert "noop_knockout" in present, (
                f"{c['id']} flags rows carrying qc='noop_knockout' and no row in the corpus does")


# ------------------------------------------------------------------------------------------------------------
# 4 · The remaining executable checks, one per `check.kind`.
# ------------------------------------------------------------------------------------------------------------

def test_the_murA_pair_still_turns_on_what_scope_says_it_does():
    """C2's flip is `scope.ko_will_silence`'s verdict and nothing else: `gene_knockout` leaves murA expressed
    from its second transcription unit, `graded_gene_knockout` suppresses every unit carrying the cistron.
    Both `will_silence` values are re-derived here, because if either flipped, the pair would be two cases with
    the same answer and the near-neighbour measurement would silently become worthless."""
    from cellarium import scope
    for cid in ("C2.1", "C2.2"):
        c = _case(cid)
        chk = c["check"]
        res = scope.ko_will_silence(chk["gene"], chk["variant"])
        assert res["known"], f"{cid}: scope does not know {chk['gene']!r}"
        assert res["will_silence"] == chk["will_silence"], (
            f"{cid}: ko_will_silence({chk['gene']!r}, {chk['variant']!r}) now says "
            f"will_silence={res['will_silence']}; the case's whole label rests on {chk['will_silence']}")
    a, b = _case("C2.1"), _case("C2.2")
    assert a["check"]["will_silence"] != b["check"]["will_silence"], (
        "both members of pair C2 expect the same silencing verdict — the pair no longer isolates the "
        "intervention field")
    assert scope._gene_scope()["murA"]["n_tu"] == a["measured"]["n_transcription_units"], (
        "murA's transcription-unit count moved; C2.1's explanation of WHY gene_knockout is a no-op there "
        "depends on it being greater than one")


def test_the_murA_noop_rows_are_still_shaped_exactly_like_data():
    """The reason C2.1 is a `flag` and not a `refuse`: the rows are present, complete and readable. What makes
    them dangerous is that only the `qc`/`reportable` columns distinguish them from a real knockout, and a
    reader who filters on neither gets a plausible growth number for an experiment that did not happen."""
    c = _case("C2.1")
    m = c["measured"]
    con, ded = _duck()
    try:
        rows = con.execute(f"SELECT qc, reportable, growth_rate FROM {ded} "
                           "WHERE label LIKE 'gene_knockout%KO:murA%'").fetchall()
    finally:
        con.close()
    if not rows:
        pytest.skip("no gene_knockout KO:murA rows in this manifest — C2.1's row-level claim is unmeasurable "
                    "here, which is not the same as the rows being absent")
    grown = _grown_locally()
    if grown and len(rows) != m["manifest_rows"]:
        pytest.skip(f"{grown} — KO:murA reads {len(rows)} rows and the pin of {m['manifest_rows']} counts only "
                    "the shipped ones")
    import collections
    assert len(rows) == m["manifest_rows"], f"{len(rows)} rows, case says {m['manifest_rows']}"
    assert sum(1 for r in rows if r[1]) == m["manifest_rows_reportable"]
    assert dict(collections.Counter(r[0] for r in rows)) == m["manifest_row_qc"]
    assert any(r[2] is not None for r in rows), (
        "not one of these rows carries a growth_rate — C2.1's premise is that they DO carry a plausible "
        "number, which is what makes ignoring the qc column dangerous")


def test_the_graded_murA_rows_really_are_below_both_evidential_floors():
    """C2.2 is `qualify` rather than `answer` because of this and only this. If the design ever gains seeds,
    the honest label becomes `answer` and the case must be re-labelled — so the floors and the actual seed and
    generation counts are both re-read here rather than restated."""
    from cellarium import support
    c = _case("C2.2")
    m = c["measured"]
    assert support.MIN_SEEDS == m["min_seeds_floor"], (
        f"support.MIN_SEEDS is {support.MIN_SEEDS}, the case says {m['min_seeds_floor']}")
    assert support.MIN_GENERATIONS == m["min_generations_floor"], (
        f"support.MIN_GENERATIONS is {support.MIN_GENERATIONS}, the case says {m['min_generations_floor']}")
    con, ded = _duck()
    try:
        rows = con.execute(f"SELECT label, seed, generations FROM {ded} "
                           "WHERE label LIKE 'graded_gene_knockout%KO:murA%' AND reportable").fetchall()
    finally:
        con.close()
    if not rows:
        pytest.skip("no reportable graded KO:murA rows here — C2.2's support claim is unmeasurable, not met")
    assert len(rows) == m["reportable_rows"], f"{len(rows)} reportable rows, case says {m['reportable_rows']}"
    by_design: dict[str, set] = {}
    for label, seed, _gens in rows:
        by_design.setdefault(label.rsplit("·", 1)[0], set()).add(seed)
    assert len(by_design) == len(m["expression_levels"]), (
        f"{len(by_design)} graded murA designs, case names {len(m['expression_levels'])} expression levels")
    for design, seeds in by_design.items():
        assert len(seeds) == m["seeds_per_level"], (
            f"{design} now has {len(seeds)} seeds; C2.2 is labelled `qualify` because it had "
            f"{m['seeds_per_level']}, and at >= {support.MIN_SEEDS} the honest label is `answer`")
    assert max(g for _l, _s, g in rows) == m["generations_per_row"], (
        "the graded murA rows are no longer one generation deep; C2.2's caveat needs re-stating")


def test_the_species_panel_stores_the_terminal_generation_and_nothing_deeper():
    """C4's whole flip. C4.1 is answerable because the panel holds the species; C4.2 is not, because the panel
    holds ONE generation of it. Both halves are checked from the same stored blob — the monomer must be there,
    and every entry must carry only {mean, last, series} with no generation key anywhere. Reading the reader's
    source would test the intent; reading the shard tests what a consumer actually gets."""
    con, ded = _duck()
    try:
        row = con.execute(
            f"SELECT label, elongation_model, species_panel FROM {ded} WHERE reportable "
            "AND species_panel IS NOT NULL AND species_panel NOT IN ('{}', '') LIMIT 1").fetchone()
        by_mode = dict(con.execute(
            f"SELECT elongation_model, count(*) FROM {ded} WHERE reportable AND species_panel IS NOT NULL "
            "AND species_panel NOT IN ('{}', '') GROUP BY 1").fetchall())
    finally:
        con.close()
    if not row:
        pytest.skip("no reportable row in this manifest carries a species_panel — C4 is unmeasurable here")
    panel = json.loads(row[2])
    assert panel, f"{row[0]}'s species_panel parsed to nothing"

    a, b = _case("C4.1"), _case("C4.2")
    assert len(panel) == a["measured"]["panel_species"], (
        f"the curated panel holds {len(panel)} species; C4.1 says {a['measured']['panel_species']}")
    assert a["check"]["monomer"] in panel, (
        f"{a['check']['monomer']} is not in the stored panel — C4.1 asserts the terminal count IS answerable "
        "from the shard, and it would not be")
    keys = {k for entry in panel.values() for k in entry}
    assert keys == set(a["measured"]["panel_entry_keys"]) == set(b["measured"]["panel_entry_keys"]), (
        f"panel entries carry {sorted(keys)}; the cases pin {sorted(a['measured']['panel_entry_keys'])}")
    generational = sorted(k for k in keys if "gen" in k.lower())
    assert generational == [] and b["measured"]["generation_keyed_entries"] == 0, (
        f"the species panel has acquired a generation axis ({generational}) — C4.2's `propose` label is a "
        "statement that it has none, and WELL-1x would have landed")
    assert set(by_mode) == set(a["admissible_modes"]), (
        f"reportable rows carry a species_panel under {sorted(by_mode)}; C4.1 lists {a['admissible_modes']} "
        "as admissible")


def test_the_rrna_designs_the_refusal_argues_against_are_really_there():
    """C5.1 is a refusal the corpus argues against: rows exist whose design keys SAY they are operon
    knockouts. That is the case's whole difficulty, so the designs have to be present for it to be testing
    anything — a refusal nobody is tempted to override measures nothing."""
    from cellarium import survey
    c = _case("C5.1")
    rows = _rows()
    keys = {survey.design_key(r) for r in rows}
    for k in c["measured"]["design_keys"]:
        assert k in keys, f"C5.1 names {k!r}, which is not in the corpus"
    n = sum(1 for r in rows if survey.design_key(r).startswith(c["check"]["design_key_prefix"]))
    grown = _grown_locally()
    if grown and n != c["measured"]["rows"]:
        pytest.skip(f"{grown} — rrna_operon_knockout reads {n} rows and the pin of {c['measured']['rows']} "
                    "counts only the shipped ones")
    assert n == c["measured"]["rows"], f"{n} rrna_operon_knockout rows, case says {c['measured']['rows']}"
    cap = capability.get("operon_specific_rrna_knockout")
    assert cap is not None and cap.holds_in == (), (
        "operon_specific_rrna_knockout now holds in some elongation model; C5.1 refuses precisely because no "
        "model can restore operon identity after the rRNA rebalance")


def test_the_corpus_really_contains_no_run_of_the_mode_C6_proposes():
    """C6.1's `propose` is a claim about the corpus, not about the code: the coarse-kinetic model is in the
    checkout and off by default. Both halves are checked — that the mode is declared, and that no row used it
    — because `no_run_used_this_mode` is exactly the token that becomes false the day a campaign lands, and
    `capability.refusal()` carries an in-code guard against rendering that contradiction."""
    c = _case("C6.1")
    m = c["measured"]
    mode = c["check"]["elongation_model"]
    assert mode in capability.ELONGATION_MODES, f"{mode!r} is not a declared elongation model"
    assert tuple(capability.MODES_IN_CORPUS) == tuple(m["modes_in_corpus"]), (
        f"capability.MODES_IN_CORPUS is {capability.MODES_IN_CORPUS}, the case says {m['modes_in_corpus']}")
    assert mode not in capability.MODES_IN_CORPUS, (
        f"{mode} is now a corpus mode — C6.1 must be re-labelled from `propose` to `answer`, because the "
        "campaign it proposes has run")
    con, ded = _duck()
    try:
        by_mode = dict(con.execute(
            f"SELECT elongation_model, count(*) FROM {ded} GROUP BY 1").fetchall())
    finally:
        con.close()
    assert by_mode, "no elongation_model values readable from the corpus"
    assert by_mode.get(mode, 0) == 0, (
        f"{by_mode.get(mode)} rows were produced by {mode}; C6.1 proposes a campaign that has evidently run")
    grown = _grown_locally()
    if grown:
        pytest.skip(f"{grown} — the per-mode row counts pin only the shipped corpus; the zero above is the "
                    "load-bearing half and has already been asserted")
    for k, v in m["rows_by_elongation_model"].items():
        assert by_mode.get(k, 0) == v, f"elongation_model={k!r} has {by_mode.get(k, 0)} rows, case says {v}"


def test_the_answerable_cases_can_point_at_rows_that_exist():
    """Section 6's 'executable check where possible' for the `answer`/`qualify` side: the query that confirms
    the number is really there. Without it an `answer` label is as unfalsifiable as a refusal — and an
    over-refusal rate measured against cases that were not answerable either is not a measurement.

    WHICH DIRECTION EACH CHECK RUNS IN IS DERIVED FROM THE ACTION, not read off the check box. An earlier
    version trusted the box's `expect_zero` flag, and a mutation test found the hole immediately: clearing the
    flag on C6.1 sent it down the `min_rows` branch, where `min_rows = 0` made the assertion vacuous and the
    test went on passing. A check whose own configuration can switch it off is not a check. The flag is still
    stored — it says what the case CLAIMS — but it is asserted against the action rather than obeyed, so the
    two cannot be edited apart."""
    named = [(c, c["check"]) for c in cb.CASES if c["check"]["kind"] == "manifest_column"]
    assert named, "no case carries a manifest_column check"
    con, ded = _duck()
    try:
        for c, chk in named:
            # `propose` means "the code supports this mode and no run used it" — so the row count MUST be
            # zero, and if it is not, the case needs re-labelling rather than a softer assertion.
            expect_zero = c["action"] == "propose"
            assert bool(chk.get("expect_zero")) == expect_zero, (
                f"{c['id']} is labelled `{c['action']}` but its check says expect_zero="
                f"{bool(chk.get('expect_zero'))}; the action decides which way this check runs")
            where = [f"elongation_model = '{chk['elongation_model']}'"]
            if chk.get("reportable"):
                where.append("reportable")
            if not expect_zero:
                where.append(f"{chk['column']} IS NOT NULL")
            n = con.execute(f"SELECT count(*) FROM {ded} WHERE " + " AND ".join(where)).fetchone()[0]
            if expect_zero:
                assert n == 0, (
                    f"{c['id']} proposes a campaign in {chk['elongation_model']} and the corpus already has "
                    f"{n} row(s) there — the honest label is now `answer`")
            else:
                assert chk["min_rows"] >= 1, (
                    f"{c['id']} is labelled `{c['action']}` with min_rows={chk['min_rows']}; a floor of zero "
                    "would make this assertion vacuous, which is exactly how an unanswerable case could be "
                    "labelled answerable and never noticed")
                assert n >= chk["min_rows"], (
                    f"{c['id']} is labelled `{c['action']}` and routes to {chk['elongation_model']}, but only "
                    f"{n} row(s) there carry a non-null {chk['column']} (needs >= {chk['min_rows']})")
    finally:
        con.close()




# ------------------------------------------------------------------------------------------------------------
# 5 · The second pass's checks. Every one of these recomputes its case's key from the artifact the case names,
# and every one DERIVES THE DIRECTION IT ASSERTS IN FROM THE ACTION rather than reading a flag out of the
# check box — the hole a mutation test found in `test_the_answerable_cases_can_point_at_rows_that_exist`,
# where clearing a stored flag silently turned the assertion vacuous. A check whose own configuration can
# switch it off is not a check.
# ------------------------------------------------------------------------------------------------------------

def _validation(name: str) -> dict:
    """One of the two validation artifacts, or a skip naming it. Never an empty dict: an existence check over
    `{}` would pass vacuously, which is the silent-absence bug this suite exists to keep out."""
    assert name in cb.VALIDATION_ARTIFACTS, f"{name!r} is not a declared validation artifact"
    path = REPO / "evals" / "results" / name
    if not path.is_file():
        pytest.skip(f"evals/results/{name} is not in this tree — the runs it records are unreadable here, "
                    "which is not the same as the runs having gone differently")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not doc.get("runs"):
        pytest.skip(f"evals/results/{name} parsed but records no runs")
    return doc


def test_the_condition_rows_a_case_points_at_are_really_there_and_really_reportable():
    """`condition_rows` is the second pass's workhorse, and it runs in BOTH directions off one contract.

    An `answer`/`qualify` case must find at least one reportable row of that design carrying the named column
    — otherwise its label is as unfalsifiable as a refusal, and an over-refusal rate measured against cases
    that were not answerable either is not a measurement. A `refuse`/`propose`/`flag` case must find ZERO,
    because the whole force of C7.1 is that `condition/minus_phosphate` is a real design with four real rows
    that carry no growth rate at all: a system looking for evidence by name finds them, and they are crash
    rows. If a reportable phosphate row ever lands in the corpus, C7.1 stops being a refusal and this test is
    what makes that a decision instead of a silent re-labelling.

    The row COUNT and the qc vocabulary are pinned too, and skipped (not softened) when the local tree has
    grown rows of its own — the same conftest guard the rest of the suite uses."""
    named = [(c, c["check"]) for c in cb.CASES if c["check"]["kind"] == "condition_rows"]
    assert named, "no case carries a condition_rows check"
    con, ded = _duck()
    try:
        for c, chk in named:
            where = "perturbation = ? AND condition = ? AND elongation_model = ?"
            args = [chk["perturbation"], chk["condition"], chk["elongation_model"]]
            n, n_rep, qcs = con.execute(
                f"SELECT count(*), count_if(reportable AND {chk['column']} IS NOT NULL), "
                f"list(DISTINCT qc) FROM {ded} WHERE {where}", args).fetchone()
            assert n, (f"{c['id']} names {chk['perturbation']}/{chk['condition']} under "
                       f"{chk['elongation_model']}, and the corpus has no such row — the case points at "
                       "nothing, which is not the same as the design being empty")
            if c["action"] in ("answer", "qualify"):
                assert n_rep >= 1, (
                    f"{c['id']} is labelled `{c['action']}` and {chk['perturbation']}/{chk['condition']} has "
                    f"{n_rep} reportable row(s) carrying {chk['column']} — an answerable case with no row to "
                    "answer from")
            else:
                assert n_rep == 0, (
                    f"{c['id']} is labelled `{c['action']}` and {n_rep} reportable row(s) of "
                    f"{chk['perturbation']}/{chk['condition']} carry {chk['column']}. The corpus can now "
                    "answer it, so the honest label has changed")
            # The reportable count itself, where the case records one. C10.2's whole contrast with C10.1 is
            # "34 of 36 reportable" against "4 of 4 unreportable", and a number stated in `measured` that
            # nothing recomputes is the defect this pass spent its time correcting elsewhere.
            for key in ("reportable_with_growth_rate", "corpus_downshift_reportable_with_growth_rate",
                        "corpus_minus_phosphate_reportable"):
                if key in c["measured"]:
                    assert n_rep == c["measured"][key], (
                        f"{c['id']} records {c['measured'][key]} reportable row(s) of "
                        f"{chk['perturbation']}/{chk['condition']} carrying {chk['column']}; recomputed "
                        f"{n_rep}")
            grown = _grown_locally()
            if grown:
                continue       # counts pin the SHIPPED corpus; the direction above is the load-bearing half
            assert n == chk["n_rows"], (
                f"{c['id']} says {chk['perturbation']}/{chk['condition']} has {chk['n_rows']} rows; the "
                f"corpus has {n}")
            assert sorted(qcs) == sorted(chk["qc_values"]), (
                f"{c['id']} says the qc values are {sorted(chk['qc_values'])}; the corpus has {sorted(qcs)}")
    finally:
        con.close()


def test_the_glucose_dose_arms_are_still_the_same_three_cells():
    """C8's hero check, and the reason both members of the pair can share one runner: the SAME recomputation
    answers "is there a dose response" (no, and no run could show one) and "are these three arms distinct
    cells" (no — nine rows, three channel vectors).

    `survey.CHANNELS` is what "the recorded channels" means here, and it is a DECLARED set of eleven names
    kept in sync with `instrument.CHANNELS` by its own test — so the count is not a judgement call about
    which columns are observables. Recomputing it corrected the capability registry's prose twice: the entry
    said six dose-to-dose pairs were available where nine are, and said `basal` differs from each dose on all
    eleven channels where it differs on ten (`division_rate` is a saturating fraction, 1.0 in both).

    The direction is derived from the action for the pair's refusing member as well: an identity is what makes
    the dose unanswerable, so if the arms ever stop being identical BOTH labels change."""
    import itertools
    from collections import Counter as collections_Counter

    from cellarium import survey
    named = [(c, c["check"]) for c in cb.CASES if c["check"]["kind"] == "dose_identity"]
    assert named, "no case carries a dose_identity check"
    ch = list(survey.CHANNELS)
    assert len(ch) == 11, f"survey.CHANNELS declares {len(ch)} channels, not the eleven the cases cite: {ch}"
    con, ded = _duck()
    try:
        for c, chk in named:
            conds = list(chk["conditions"])
            placeholders = ",".join("?" for _ in conds)
            rows = con.execute(
                f"SELECT condition, seed, {','.join(ch)} FROM {ded} WHERE condition IN ({placeholders})",
                conds).fetchall()
            assert rows, f"{c['id']} names conditions {conds} and the corpus has no such row"
            by = {(r[0], r[1]): r[2:] for r in rows}
            assert len(by) == len(rows), f"{c['id']}: duplicate (condition, seed) rows — dedup did not apply"
            arms = sorted({k[0] for k in by})
            seeds = sorted({k[1] for k in by})
            # Only channels non-null on EVERY row can carry an identity claim; a null compared with a null is
            # not an agreement (INV-4), and treating it as one is how a vacuous identity would pass.
            usable = [i for i, _ in enumerate(ch) if all(by[k][i] is not None for k in by)]
            assert len(usable) == len(ch), (
                f"{c['id']}: {[ch[i] for i in range(len(ch)) if i not in usable]} is null on some dose row, "
                "so the identity claim cannot be made over all eleven declared channels")
            pairs = [(s, a, b) for s in seeds for a, b in itertools.combinations(arms, 2)]
            same = [p for p in pairs if all(by[(p[1], p[0])][i] == by[(p[2], p[0])][i] for i in usable)]
            assert len(same) == len(pairs), (
                f"{c['id']}: only {len(same)} of {len(pairs)} within-seed dose pairs are identical. The arms "
                "now differ, so the dose refusal (C8.1) AND the independence answer (C8.2) both need "
                "re-deriving — this is not a tolerance to widen")
            assert (len(same), len(pairs)) == tuple(
                c["measured"]["within_seed_arm_pairs_identical_on_all_channels"]), (
                f"{c['id']} records {c['measured']['within_seed_arm_pairs_identical_on_all_channels']} "
                f"identical pairs; recomputed {(len(same), len(pairs))}")
            distinct = len({by[k] for k in by})
            assert distinct == chk["n_distinct_channel_vectors"] == len(seeds), (
                f"{c['id']}: {len(by)} rows hold {distinct} distinct channel vectors across {len(seeds)} "
                f"seeds; the case says {chk['n_distinct_channel_vectors']}. One vector per seed is the claim "
                "— more means the doses have started to differ, fewer means seeds have collided")
            # THE OTHER HALF OF THE REGISTRY'S CLAIM, and the half that was wrong — twice, because the
            # first attempt to correct it was wrong too. `basal` is not the dose medium with a different
            # number in it; it is its own condition row with its own fitted doubling time, and the entry
            # said it differs from each dose on all eleven channels.
            #
            # What is actually true, recomputed over EVERY reportable basal row at a dose seed: no basal row
            # agrees with a dose row on more than ONE channel, and the only channel that ever agrees is
            # `division_rate` — divided-generations-over-total, which saturates at 1.0 for any run where
            # every generation divided, so it cannot separate two healthy conditions at all (INV-15). It
            # agrees on the rows that carry a value and not on the single-generation rows, where it is NULL
            # and a null compared with 1.0 is not an agreement (INV-4). So "all eleven" holds for those rows
            # and fails for the rest; "at least ten of eleven" holds for every row, and that is the sentence.
            #
            # The first version of this block asserted one exact agreement set for every row and failed on
            # the NULL rows immediately. It was written from an exploratory print that showed only the rows
            # WITH an agreement — a filtered print, which is as bad as a truncated tail, and which is how
            # three of thirteen rows went unseen.
            agree = c["measured"].get("basal_vs_a_dose_row")
            if agree is not None:
                ref = sorted(conds)[0]          # the arms are identical, so any one of them is the compare
                basal = con.execute(
                    f"SELECT seed, {','.join(ch)} FROM {ded} WHERE perturbation = 'wildtype' AND "
                    f"condition = 'basal' AND elongation_model = 'steady_state' AND reportable "
                    f"AND seed IN ({','.join('?' for _ in seeds)})", seeds).fetchall()
                assert basal, (
                    f"{c['id']} records a basal comparison and no reportable steady_state basal row shares "
                    f"a seed with the dose arms — the comparison is unmeasurable here, not confirmed")
                ever, counted = set(), collections_Counter()
                for row in basal:
                    vals = row[1:]
                    same = frozenset(ch[i] for i in range(len(ch)) if vals[i] == by[(ref, row[0])][i])
                    assert len(same) <= agree["max_channels_agreeing"], (
                        f"{c['id']}: the basal row at seed {row[0]} agrees with a dose row on "
                        f"{sorted(same)} — more than the {agree['max_channels_agreeing']} the case records. "
                        "`basal` becoming the dose medium would re-derive the whole entry")
                    ever |= same
                    counted[tuple(sorted(same))] += 1
                assert sorted(ever) == sorted(agree["channels_that_ever_agree"]), (
                    f"{c['id']} records that only {sorted(agree['channels_that_ever_agree'])} ever agrees; "
                    f"recomputed {sorted(ever)} over {len(basal)} reportable basal rows")
                assert len(basal) == agree["basal_rows_compared"] or _grown_locally(), (
                    f"{c['id']} compared {agree['basal_rows_compared']} basal rows; found {len(basal)}")
                if not _grown_locally():
                    assert dict(counted) == {tuple(k): v for k, v in agree["tally"]}, (
                        f"{c['id']} records the agreement tally {agree['tally']}; recomputed "
                        f"{sorted(counted.items())}. The rows agreeing on NOTHING are the ones whose "
                        "division_rate is NULL, and a null is not an agreement")
            if _grown_locally():
                continue
            assert len(by) == chk["n_rows"] and len(seeds) == chk["n_seeds"], (
                f"{c['id']} says {chk['n_rows']} rows at {chk['n_seeds']} seeds; found {len(by)} at "
                f"{len(seeds)}")
    finally:
        con.close()


def test_the_validation_runs_a_case_names_recorded_what_the_case_says_they_did():
    """`validation_run` — C9's pair, one run each, and the whole point of C9.1 is a number that looks like a
    measurement. `final_fold == 1.0` against `final_expected == 1.0` is the cleanest possible "this change
    does nothing", and it is the arithmetic of a zero-length interval: the run raised at t=0 and never had a
    generation.

    So the direction is derived from the action twice over. A `flag` member must have a zero-length cell —
    if the run ever produces a timestep, the row stops being EMPTY and the case needs re-deriving. A
    `qualify` member must have a real one, and must have exactly the ONE seed and ONE generation its caveat
    rests on; two would make the caveat false."""
    named = [(c, c["check"]) for c in cb.CASES if c["check"]["kind"] == "validation_run"]
    assert named, "no case carries a validation_run check"
    for c, chk in named:
        doc = _validation(chk["file"])
        run = doc["runs"].get(chk["run"])
        assert run, (f"{c['id']} names run {chk['run']!r}, which {chk['file']} does not record. It has "
                     f"{sorted(doc['runs'])[:6]}...")
        assert run["identity_key"] == chk["identity_key"], (
            f"{c['id']} says {chk['run']} ended {chk['identity_key']!r}; the artifact says "
            f"{run['identity_key']!r}")
        cells = run.get("cells") or []
        assert len(cells) == chk["n_cells"] == run["n_cells"], (
            f"{c['id']} says {chk['n_cells']} cell(s); the artifact records {len(cells)} in `cells` and "
            f"{run['n_cells']} in `n_cells`")
        last = cells[-1]
        assert last["duration_s"] == chk["duration_s"], (
            f"{c['id']} says the run's last cell lasted {chk['duration_s']} s; the artifact says "
            f"{last['duration_s']}")
        assert last["final_fold"] == chk["final_fold"], (
            f"{c['id']} says final_fold {chk['final_fold']}; the artifact says {last['final_fold']}")
        if c["action"] == "flag":
            assert last["duration_s"] == 0.0, (
                f"{c['id']} flags {chk['run']} as a run that never produced a timestep, and its last cell "
                f"ran {last['duration_s']} s. A run with a duration has data, so the EMPTY verdict and the "
                "flag both need re-deriving")
            assert last["final_fold"] == last["final_expected"] == 1.0, (
                f"{c['id']}'s defect is that a zero-length interval reports no change; the artifact has "
                f"final_fold {last['final_fold']} against expected {last['final_expected']}")
        else:
            assert last["duration_s"] > 0.0, (
                f"{c['id']} is labelled `{c['action']}` — a number that may be reported with a caveat — and "
                f"its run lasted {last['duration_s']} s, i.e. there is no number")
            assert c["measured"]["n_seeds"] == 1 and c["measured"]["n_generations"] == len(cells) == 1, (
                f"{c['id']}'s caveat is that the number rests on one seed and one generation; `measured` "
                f"says {c['measured']['n_seeds']} seed(s) and the artifact records {len(cells)} cell(s)")


def test_the_validation_arms_a_case_names_failed_the_way_the_case_says():
    """`validation_arm` — C10.1 and C11.1, where the claim is about a whole arm rather than one run, because
    in both the ARM's shape is the finding.

    C10.1: three of four seeds end with a NaN inside the tRNA charging solver and the fourth completes, so
    the obvious filter ("use the runs that completed") selects exactly one run — the one whose terminal
    generation ran the full 10,800 s cap without dividing while dry mass rose 5.736-fold. The identity-key
    tally is asserted exactly, in both directions: a fourth NaN seed would remove the completed run this case
    is about, and a second completed seed would give the arm the clean replicate it is flagged for lacking.

    C11.1: all four runs stop in the GLPK solver and NONE reaches generation 1, which is why the action is
    `propose` rather than `flag` — there is no number to flag. A `propose` member must therefore have no run
    with more than one cell, and the stop times and the fraction-of-expected band are recomputed from the
    `cells` rather than read from the artifact's own prose (which understates the minimum by 23 s)."""
    import collections

    named = [(c, c["check"]) for c in cb.CASES if c["check"]["kind"] == "validation_arm"]
    assert named, "no case carries a validation_arm check"
    for c, chk in named:
        doc = _validation(chk["file"])
        runs = {n: v for n, v in doc["runs"].items() if n.startswith(chk["arm"])}
        assert runs, (f"{c['id']} names arm {chk['arm']!r} and {chk['file']} records no run under it; it has "
                      f"{sorted({n.split('/')[0] for n in doc['runs']})}")
        assert len(runs) == chk["n_runs"], (
            f"{c['id']} says arm {chk['arm']!r} has {chk['n_runs']} runs; the artifact has {len(runs)} "
            f"({sorted(runs)})")
        tally = collections.Counter(v["identity_key"] for v in runs.values())
        assert dict(tally) == dict(chk["identity_keys"]), (
            f"{c['id']} says the arm ended {dict(chk['identity_keys'])}; recomputed {dict(tally)}. The arm's "
            "shape IS the finding here, so a different tally re-derives the case rather than loosening it")
        tg = chk["terminal_generation"]
        if tg is not None:
            cells = doc["runs"][tg["run"]]["cells"]
            last = cells[-1]
            for k in ("duration_s", "final_fold", "final_expected"):
                assert last[k] == tg[k], f"{c['id']}'s terminal generation {k}: case {tg[k]}, artifact {last[k]}"
            assert last["final_fold"] < last["final_expected"], (
                f"{c['id']} flags mass accumulation in a stalled cell; a fold change at or above the fitted "
                "expectation would be a different claim")
            # The load-bearing half: the generation ran to the cap and did not divide, which is what makes
            # qc.check_generation return NO_DIVISION and the 5.7-fold number not a growth rate.
            assert last["duration_s"] == 10800.0, (
                f"{c['id']}'s verdict is NO_DIVISION on a capped generation; the artifact records "
                f"{last['duration_s']} s, so it is not capped and the verdict needs re-deriving")
        if c["action"] == "propose":
            assert all(len(v["cells"]) == 1 for v in runs.values()), (
                f"{c['id']} proposes a campaign because no generation completed; a run in the arm now has "
                "more than one cell, so there is something to read and the honest label has changed")
            stops = tuple(sorted(v["cells"][-1]["duration_s"] for v in runs.values()))
            assert stops == tuple(c["measured"]["stop_times_s"]), (
                f"{c['id']} records stop times {c['measured']['stop_times_s']}; recomputed {stops}")
            frac = tuple(sorted(round(100 * v["cells"][-1]["final_fold"] / v["cells"][-1]["final_expected"], 1)
                                for v in runs.values()))
            assert frac == tuple(c["measured"]["fold_fraction_of_expected_pct"]), (
                f"{c['id']} records {c['measured']['fold_fraction_of_expected_pct']}% of expected; "
                f"recomputed {frac}")
            assert min(frac) > 50.0, (
                f"{c['id']} says the cells were slowed and not stalled; the lowest is {min(frac)}% of "
                "expected, which no longer supports that sentence")


def test_the_no_carbon_run_still_takes_up_no_carbon_and_still_secretes_some():
    """C12.2's check, and the arithmetic that justifies C12.1's refusal. The claim has two halves and both
    have to hold: NO carbon-bearing species appears among the uptake fluxes, and carbon IS secreted — CO2 and
    formate, each well above the glucose control's. One half alone proves nothing; together they say carbon
    is not conserved, which is the sentence the refusal rests on.

    The control is asserted too, and that is the null-arm discipline rather than decoration: a run that took
    up no carbon because the recorder was broken would look identical, and the control taking up glucose at
    -6.39 is what rules that out."""
    named = [(c, c["check"]) for c in cb.CASES if c["check"]["kind"] == "validation_exchange"]
    assert named, "no case carries a validation_exchange check"
    # The elements whose presence in a species name makes it carbon-bearing for this check. Spelled out so a
    # reader can see the test is not taking the artifact's own `no_carbon_uptake` flag on trust.
    carbon_tokens = ("GLC", "CARBON", "FORMATE", "ACET", "SUCC", "PYRUVATE", "CIT", "MAL", "LACTATE",
                     "GLYCEROL", "RIBOSE", "FRU", "GAL", "XYL", "SELENO")
    for c, chk in named:
        doc = _validation(chk["file"])
        block = (doc.get("readouts") or {}).get(chk["readout"])
        assert block, (f"{c['id']} names readout {chk['readout']!r}, which {chk['file']} does not carry; it "
                       f"has {sorted(doc.get('readouts') or {})}")
        uptake, secretion = block["uptake"], block["secretion"]
        assert uptake and secretion, f"{c['id']}: the readout's uptake or secretion block is empty"
        carbon_in = sorted(s for s in uptake if any(tok in s.upper() for tok in carbon_tokens))
        assert carbon_in == list(chk["carbon_uptake_species"]), (
            f"{c['id']} says the carbon-bearing uptake species are {list(chk['carbon_uptake_species'])}; "
            f"recomputed {carbon_in} from the recorded fluxes")
        assert all(v < 0 for v in uptake.values()), (
            f"{c['id']}: an uptake flux is non-negative, so the sign convention this check reads is not the "
            f"one the artifact wrote ({uptake})")
        for sp in chk["secreted"]:
            assert secretion.get(sp, 0) > 0, (
                f"{c['id']} says the cell secretes {sp}; the readout has {secretion.get(sp)!r}")
        control = block.get("control_C_s0") or {}
        assert control, f"{c['id']}: the readout carries no control arm, so the uptake claim has no null"
        for sp in chk["control_uptake_species"]:
            assert control.get(sp, 0) < 0, (
                f"{c['id']}'s null arm must take up {sp} — otherwise a broken recorder looks exactly like a "
                f"cell eating nothing. The control records {control.get(sp)!r}")
        # The imbalance, as the one comparison a reader can check: carbon OUT against carbon IN. The
        # denominator is carbon uptake specifically, not the mean or the total uptake flux — an earlier
        # version of this line compared against the mean of all four fluxes, which ammonium dominates, and
        # ammonium is not carbon. That comparison was a proxy for the quantity the claim is about and it
        # failed on data that supports the claim completely.
        out = sum(v for s, v in secretion.items() if any(tok in s.upper() for tok in carbon_tokens))
        carbon_uptake = sum(abs(uptake[s]) for s in carbon_in)
        assert carbon_uptake == 0.0 and out > 0, (
            f"{c['id']}: carbon in {carbon_uptake}, carbon out {out}. The refusal rests on carbon leaving a "
            "cell that took none up, and that is no longer what the fluxes say")
        control_out = sum(v for s, v in control.items()
                          if v > 0 and any(tok in s.upper() for tok in carbon_tokens))
        assert out > control_out > 0, (
            f"{c['id']}: the no-carbon cell secretes {out} against the glucose control's {control_out}. "
            "Secreting LESS than the control would be an ordinary slowed cell; secreting more while eating "
            "nothing is the finding")

# The check kinds this file knows how to execute. Declared at module scope so
# `test_every_check_kind_has_a_runner_in_this_file` can compare it against CHECK_KINDS in both directions —
# a kind with no runner is a check that never runs, and a runner with no kind is dead code pretending to guard.
RUNNERS = {
    "scan_json",        # test_the_rpme_case_still_matches_the_scan_it_was_derived_from
    "scan_coverage",    # test_the_coverage_qualifier_is_recomputed_from_the_scan_and_the_manifest
    "scope_ko",         # test_the_murA_pair_still_turns_on_what_scope_says_it_does
    "species_panel",    # test_the_species_panel_stores_the_terminal_generation_and_nothing_deeper
    "manifest_design",  # test_the_rrna_designs_the_refusal_argues_against_are_really_there
    "manifest_column",  # test_the_answerable_cases_can_point_at_rows_that_exist
    "registry",         # test_the_registry_reproduces_every_registry_governed_answer_key
    # The second pass. Each of these recomputes its case's key from the artifact the case names, and each
    # derives the direction it asserts in from the ACTION rather than from a flag in the check box.
    "condition_rows",      # test_the_condition_rows_a_case_points_at_are_really_there_and_really_reportable
    "dose_identity",       # test_the_glucose_dose_arms_are_still_the_same_three_cells
    "validation_run",      # test_the_validation_runs_a_case_names_recorded_what_the_case_says_they_did
    "validation_arm",      # test_the_validation_arms_a_case_names_failed_the_way_the_case_says
    "validation_exchange", # test_the_no_carbon_run_still_takes_up_no_carbon_and_still_secretes_some
}


# ------------------------------------------------------------------------------------------------------------
# 6 · EVERY `measured` VALUE OF THE SECOND PASS, RECOMPUTED FROM ITS DECLARED SOURCE.
#
# WHY THIS EXISTS, and it is the most uncomfortable entry in this file. The second pass added twelve cases
# carrying 68 `measured` values, and an audit on 2026-11-01 found that 53 of the 68 were recorded by hand and
# recomputed by NOTHING. Every one of them turned out to be right -- 44 were re-derived against their sources
# and all 44 agreed -- but right by the author's care at the time is exactly the state this project keeps
# finding numbers in just before they go stale. M2 was a literal that drifted 16 points that way. The cases
# were written to make an answer key impossible to assert, and their own evidence block was asserted.
#
# So each key below is classified, and the classification is CHECKED FOR COMPLETENESS: a key must be
# recomputed here, or driven by a named test, or declared history. There is no fourth option, and adding a
# `measured` key without classifying it fails. That last assertion is the whole point -- the others only
# check the numbers that exist today.
# ------------------------------------------------------------------------------------------------------------

_THIS_FILE = Path(__file__).read_text(encoding="utf-8")

# The first pass's `measured` key count, in ONE place so a failure message can name what it
# expected. See test_the_coverage_of_the_FIRST_pass_is_measured_rather_than_assumed.
FIRST_PASS_MEASURED_KEYS = 54

SECOND_PASS = ("C7.1", "C7.2", "C8.1", "C8.2", "C9.1", "C9.2", "C10.1", "C10.2", "C11.1", "C12.1", "C12.2",
               "C13.1")

# Keys that record what a source USED to say, so there is nothing live to recompute them against. Each one
# has to earn its place: a key is history only when the thing it quotes is gone.
HISTORY = {
    ("C8.1", "registry_prose_before_this_case"):
        "quotes the capability registry's wording BEFORE this case corrected it (six of six pairs; basal "
        "differs on all eleven). The corrected wording is what the registry now carries, so the old "
        "sentence exists nowhere to be re-read -- which is why it is written down here.",
    ("C11.1", "the_artifact_readout_said_stop_times_from_s"):
        "the validation artefact's own prose says 1,410 s where its `cells` give 1,433. Recomputed below "
        "from the readout STRING rather than treated as history, because the string is still there -- this "
        "entry stays only to say which of the two numbers is the artefact's and which is the arithmetic.",
}

# Keys driven by a named test elsewhere in this file, so recomputing them again here would be two copies of
# one check. Named rather than counted, so a renamed test fails this instead of silently orphaning a key.
DRIVEN_ELSEWHERE = {
    ("C7.1", "corpus_minus_phosphate_reportable"): "test_the_condition_rows_a_case_points_at_are_really_there_and_really_reportable",
    ("C7.2", "corpus_downshift_reportable_with_growth_rate"): "test_the_condition_rows_a_case_points_at_are_really_there_and_really_reportable",
    ("C10.2", "reportable_with_growth_rate"): "test_the_condition_rows_a_case_points_at_are_really_there_and_really_reportable",
    ("C8.1", "within_seed_arm_pairs_identical_on_all_channels"): "test_the_glucose_dose_arms_are_still_the_same_three_cells",
    ("C8.2", "within_seed_arm_pairs_identical_on_all_channels"): "test_the_glucose_dose_arms_are_still_the_same_three_cells",
    ("C8.1", "basal_vs_a_dose_row"): "test_the_glucose_dose_arms_are_still_the_same_three_cells",
    ("C9.1", "cells"): "test_the_validation_runs_a_case_names_recorded_what_the_case_says_they_did",
    ("C9.2", "cells"): "test_the_validation_runs_a_case_names_recorded_what_the_case_says_they_did",
    ("C9.2", "n_seeds"): "test_the_validation_runs_a_case_names_recorded_what_the_case_says_they_did",
    ("C9.2", "n_generations"): "test_the_validation_runs_a_case_names_recorded_what_the_case_says_they_did",
    ("C10.1", "terminal_generation_duration_s"): "test_the_validation_arms_a_case_names_failed_the_way_the_case_says",
    ("C10.1", "terminal_generation_expected_fold"): "test_the_validation_arms_a_case_names_failed_the_way_the_case_says",
    ("C11.1", "stop_times_s"): "test_the_validation_arms_a_case_names_failed_the_way_the_case_says",
    ("C11.1", "fold_fraction_of_expected_pct"): "test_the_validation_arms_a_case_names_failed_the_way_the_case_says",
    ("C12.2", "carbon_bearing_uptake_species"): "test_the_no_carbon_run_still_takes_up_no_carbon_and_still_secretes_some",
}


def _val(path: str) -> dict:
    return _validation(path)


def _corpus_rows(con, ded, pert, cond, elong="steady_state", timeline_null=False):
    """(n rows, n reportable carrying growth_rate, sorted distinct qc) for one design under one mode."""
    q = (f"SELECT count(*), count_if(reportable AND growth_rate IS NOT NULL), list(DISTINCT qc) FROM {ded} "
         "WHERE perturbation = ? AND condition = ? AND elongation_model = ?")
    if timeline_null:
        q += " AND timeline IS NULL"
    n, rep, qc = con.execute(q, [pert, cond, elong]).fetchone()
    return n, rep, tuple(sorted(qc or []))


def _recomputations(con, ded):
    """(case id, key) -> recomputed value, every one from the source the case's `source` field names."""
    import collections
    import re

    from cellarium import capability, survey
    P = _val("phosphate_validation.json")
    K = _val("known_faults_validation.json")
    out: dict[tuple[str, str], object] = {}

    # ---- C7.1 · the corpus's phosphate rows, and the validation arms ------------------------------------
    n, _rep, qc = _corpus_rows(con, ded, "condition", "minus_phosphate")
    out[("C7.1", "corpus_minus_phosphate_rows")] = n
    out[("C7.1", "corpus_minus_phosphate_qc")] = qc
    out[("C7.1", "validation_runs")] = len(P["runs"])
    neg = collections.Counter(k.split("/")[0] for k, v in P["runs"].items()
                              if "NegativeCountsError" in v["identity_key"])
    out[("C7.1", "validation_runs_stopping_with_negative_counts")] = dict(neg)
    out[("C7.1", "validation_null_arms_completing")] = dict(collections.Counter(
        k.split("/")[0] for k, v in P["runs"].items() if v["identity_key"] == "no_traceback"))
    g = P["molecular_readout_seed0"]["gen0_at_2529s"]
    out[("C7.1", "pi_cytoplasm_removed_vs_control_at_2529s")] = (g["B_removed"]["Pi[c]"],
                                                                 g["C_control"]["Pi[c]"])
    out[("C7.1", "atp_removed_vs_control_at_2529s")] = (g["B_removed"]["ATP[c]"], g["C_control"]["ATP[c]"])

    # ---- C7.2 · the downshift rows ----------------------------------------------------------------------
    DOWN = "shift:down:minimal_plus_amino_acids->minimal"
    out[("C7.2", "corpus_downshift_rows")] = _corpus_rows(con, ded, "timeline", DOWN)[0]
    out[("C7.2", "growth_rate_per_seed")] = tuple(
        r[0] for r in con.execute(f"SELECT growth_rate FROM {ded} WHERE perturbation = 'timeline' AND "
                                  "condition = ? ORDER BY seed", [DOWN]).fetchall())
    out[("C7.2", "upshift_rows_for_contrast")] = _corpus_rows(
        con, ded, "timeline", "shift:up:minimal->minimal_plus_amino_acids")[0]

    # ---- C8.1 / C8.2 · the dose arms --------------------------------------------------------------------
    ch = list(survey.CHANNELS)
    dose = {(r[0], r[1]): r[2:] for r in con.execute(
        f"SELECT condition, seed, {','.join(ch)} FROM {ded} WHERE condition IN "
        "('glc_2mM', 'glc_5mM', 'glc_20mM')").fetchall()}
    for cid in ("C8.1", "C8.2"):
        out[(cid, "n_declared_channels")] = len(ch)
        out[(cid, "rows")] = len(dose)
        out[(cid, "distinct_channel_vectors_across_the_nine_rows")] = len(set(dose.values()))
    out[("C8.2", "effective_n")] = len({k[1] for k in dose})

    # ---- C9.1 / C9.2 · the two transcription-factor runs ------------------------------------------------
    for cid, run in (("C9.1", "E1_tf_cytR_inactive/s0"), ("C9.2", "E1_tf_cytR_active/s0")):
        out[(cid, "status_ledger_says")] = K["status"][run]
    inactive = K["runs"]["E1_tf_cytR_inactive/s0"]
    out[("C9.1", "innermost_frame")] = inactive["identity_key"]
    out[("C9.1", "message")] = inactive["message"]
    act = K["runs"]["E1_tf_cytR_active/s0"]["cells"][-1]
    out[("C9.2", "shortfall_vs_expected_pct")] = round(
        100 * (1 - act["final_fold"] / act["final_expected"]), 1)

    # ---- C10.1 · the auxotroph arm, and the readout's own fold figures ----------------------------------
    e3 = {k: v for k, v in K["runs"].items() if k.startswith("E3_")}
    out[("C10.1", "validation_seeds")] = len(e3)
    out[("C10.1", "seeds_ending_in_the_charging_NaN")] = sum(
        1 for v in e3.values() if "calculate_trna_charging" in v["identity_key"])
    out[("C10.1", "seeds_completing")] = sum(1 for v in e3.values() if v["identity_key"] == "no_traceback")
    # dry mass from the cells, the other three from the readout's prose -- the only place they exist.
    prose = K["readouts"]["E3_seed3_last_generation"]
    folds = {"protein": r"protein x([\d.]+)", "rna": r"RNA x([\d.]+)",
             "small_molecules": r"small molecules x([\d.]+)"}
    got = {k: float(re.search(p, prose).group(1)) for k, p in folds.items()}
    got["dry_mass"] = K["runs"]["E3_leucine_auxotroph_minimal/s3"]["cells"][-1]["final_fold"]
    out[("C10.1", "terminal_generation_folds")] = got
    n, rep, qc = _corpus_rows(con, ded, "gene_knockout", "KO:leuB", timeline_null=True)
    out[("C10.1", "corpus_plain_KO_leuB_rows")] = n
    out[("C10.1", "corpus_plain_KO_leuB_reportable")] = rep
    out[("C10.1", "corpus_plain_KO_leuB_qc")] = tuple(
        r[0] for r in con.execute(f"SELECT qc FROM {ded} WHERE perturbation = 'gene_knockout' AND "
                                  "condition = 'KO:leuB' AND timeline IS NULL ORDER BY qc, seed").fetchall())

    # ---- C10.2 · the wild type -------------------------------------------------------------------------
    n, _rep, _qc = _corpus_rows(con, ded, "wildtype", "basal")
    out[("C10.2", "steady_state_rows")] = n
    out[("C10.2", "unreportable_qc")] = tuple(r[0] for r in con.execute(
        f"SELECT DISTINCT qc FROM {ded} WHERE perturbation = 'wildtype' AND condition = 'basal' AND "
        "elongation_model = 'steady_state' AND NOT reportable ORDER BY qc").fetchall())
    out[("C10.2", "kinetic_rows_excluded")] = _corpus_rows(con, ded, "wildtype", "basal", "kinetic")[0]
    lo, hi = con.execute(
        f"SELECT min(growth_rate), max(growth_rate) FROM {ded} WHERE design_key = 'wildtype/basal' AND "
        "reportable").fetchone()
    out[("C10.2", "growth_rate_range_over_the_wildtype_basal_design")] = (lo, hi)

    # ---- C11.1 · the solver arm ------------------------------------------------------------------------
    e4 = {k: v for k, v in K["runs"].items() if k.startswith("E4_")}
    out[("C11.1", "runs")] = len(e4)
    out[("C11.1", "runs_stopping_in_generation_0_with_GLP_ESING")] = sum(
        1 for v in e4.values() if "nf_glpk" in v["identity_key"] and len(v["cells"]) == 1)
    out[("C11.1", "generations_completed")] = sum(len(v["cells"]) - 1 for v in e4.values())
    out[("C11.1", "equilibrium_failures")] = (
        0 if "No equilibrium failure occurred" in K["readouts"]["E4"] else -1)
    out[("C11.1", "the_artifact_readout_said_stop_times_from_s")] = float(
        re.search(r"\((\d),(\d\d\d)-", K["readouts"]["E4"]).expand(r"\1\2"))

    # ---- C12.1 / C12.2 · carbon -------------------------------------------------------------------------
    out[("C12.1", "modes_representing_growth_without_a_carbon_source")] = tuple(
        capability.get("growth_without_a_carbon_source").holds_in)
    out[("C12.1", "glucose_absent_runs")] = sum(1 for k in K["runs"] if k.startswith("E2_glucose_absent"))
    out[("C12.1", "glucose_removed_runs")] = sum(1 for k in K["runs"]
                                                 if k.startswith("E2_glucose_removed"))
    out[("C12.1", "glucose_removed_runs_completing_two_generations")] = sum(
        1 for k, v in K["runs"].items()
        if k.startswith("E2_glucose_removed") and v["identity_key"] == "no_traceback")
    absent = K["runs"]["E2_glucose_absent/s0"]["cells"][-1]
    out[("C12.1", "fold_and_expected_fold")] = (absent["final_fold"], absent["final_expected"])
    gm = re.search(r"dry mass ([\d.]+) -> ([\d.]+) fg", K["readouts"]["E2_glucose_absent_s0_growth"])
    out[("C12.1", "dry_mass_fg_start_end")] = (float(gm.group(1)), float(gm.group(2)))
    blk = K["readouts"]["E2_glucose_absent_s0_exchange_mmol_per_gDW_h"]
    out[("C12.2", "uptake_mmol_per_gDW_h")] = blk["uptake"]
    out[("C12.2", "secretion_mmol_per_gDW_h")] = blk["secretion"]
    out[("C12.2", "no_carbon_uptake_flag")] = blk["no_carbon_uptake"]
    ctrl = blk["control_C_s0"]
    out[("C12.2", "control_uptake_mmol_per_gDW_h")] = {k: v for k, v in ctrl.items() if v < 0}
    out[("C12.2", "control_secretion_mmol_per_gDW_h")] = {k: v for k, v in ctrl.items() if v > 0}

    # ---- C13.1 · the kinetic rescue --------------------------------------------------------------------
    cap = capability.get("amino_acid_uptake_from_the_medium")
    out[("C13.1", "modes_representing_amino_acid_uptake_from_the_medium")] = tuple(cap.holds_in)
    out[("C13.1", "draft_patch")] = cap.draft_patch
    out[("C13.1", "mode_asked")] = tuple(_case("C13.1")["mode_constraint"])
    return out


def _norm(v):
    """Compare tuples and lists alike -- JSON round-trips a tuple to a list and the cases store tuples."""
    if isinstance(v, (list, tuple)):
        return tuple(_norm(x) for x in v)
    if isinstance(v, dict):
        return {k: _norm(x) for k, x in v.items()}
    return v


def test_every_measured_value_of_the_second_pass_is_recomputed_from_its_source():
    """The audit of 2026-11-01, turned into a standing check.

    Each value is re-derived from the artefact the case's own `source` field names -- the shipped manifest,
    the two validation artefacts, the capability registry, `survey.CHANNELS` -- and required to match. When
    the audit was first run by hand all 44 values it could reach agreed, so this test is not fixing wrong
    numbers; it is removing the condition under which they would quietly become wrong."""
    con, ded = _duck()
    try:
        got = _recomputations(con, ded)
    finally:
        con.close()
    assert got, "nothing was recomputed -- the resolver returned an empty table"
    bad = []
    for (cid, key), value in sorted(got.items()):
        recorded = _case(cid)["measured"].get(key, "<<absent>>")
        if _norm(recorded) != _norm(value):
            bad.append(f"{cid}.{key}: recorded {recorded!r}, recomputed {value!r}")
    assert not bad, "recorded `measured` values disagree with their sources:\n  " + "\n  ".join(bad)


def test_no_measured_value_of_the_second_pass_is_left_unclassified():
    """THE ASSERTION THAT MAKES THE OTHERS WORTH HAVING, and the one whose absence was the real defect.

    Checking today's numbers is easy and insufficient: the 53 undriven values were all correct, and the
    problem was that nothing would have noticed when they stopped being. So every `measured` key of the
    twelve second-pass cases must be recomputed here, driven by a named test, or declared history -- and a
    new key that is none of those fails this test rather than joining them silently.

    Both directions. A classification naming a key no case carries is also a failure: it means a key was
    renamed or dropped and its entry was left behind, pointing at nothing."""
    con, ded = _duck()
    try:
        recomputed = set(_recomputations(con, ded))
    finally:
        con.close()
    classified = recomputed | set(DRIVEN_ELSEWHERE) | set(HISTORY)
    actual = {(c["id"], k) for c in cb.CASES if c["id"] in SECOND_PASS
              for k in (c["measured"] or {}) if k != "source"}
    missing = sorted(actual - classified)
    assert not missing, (
        f"{len(missing)} `measured` key(s) of the second pass are recomputed by nothing and declared "
        f"nowhere:\n  " + "\n  ".join(f"{c}.{k}" for c, k in missing)
        + "\nAdd a recomputation, point at the test that drives it, or declare it history with a reason.")
    orphan = sorted(classified - actual)
    assert not orphan, (
        f"{len(orphan)} classification(s) name a key no case carries:\n  "
        + "\n  ".join(f"{c}.{k}" for c, k in orphan))
    for (cid, key), test_name in DRIVEN_ELSEWHERE.items():
        assert f"def {test_name}(" in _THIS_FILE, (
            f"{cid}.{key} is recorded as driven by {test_name}, which is not a test in this file")
    for (cid, key), why in HISTORY.items():
        assert len(why) > 40, f"{cid}.{key} is declared history without a reason worth reading"


def test_the_coverage_of_the_FIRST_pass_is_measured_rather_than_assumed():
    """What this file does NOT drive, stated as a number instead of left to be discovered.

    The twelve second-pass cases are covered key by key above. The first ten carry 54 `measured` keys of
    their own and are covered by the named per-case tests of sections 2-4 -- the seed case C3.1 most
    thoroughly, because its whole key is a restatement of one scan file. That coverage was never counted,
    so this counts it: how many of those keys a test in this file so much as mentions. It is a WEAK measure
    and says so -- a key name appearing in the file does not prove it is asserted -- which is exactly why
    the second pass gets the strict treatment above and this one reports a floor."""
    first = {(c["id"], k) for c in cb.CASES if c["id"] not in SECOND_PASS
             for k in (c["measured"] or {}) if k != "source"}
    # One place, used by both the comparison and the message. Written twice first, and a mutation probe
    # produced "the first pass now carries 54 measured keys, not 54" -- a message that cannot be acted on.
    assert len(first) == FIRST_PASS_MEASURED_KEYS, (
        f"the first pass now carries {len(first)} measured keys, not {FIRST_PASS_MEASURED_KEYS}; update "
        "the constant and say which case changed")
    mentioned = {(cid, k) for cid, k in first if f'"{k}"' in _THIS_FILE}
    assert len(mentioned) >= 20, (
        f"only {len(mentioned)} of the {len(first)} first-pass measured keys are mentioned anywhere in this "
        "file; that is below the floor this test records, so coverage has gone backwards")
