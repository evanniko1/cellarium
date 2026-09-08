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
             "C4.1": ("rpmE",), "C4.2": ("rpmE",)}
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
    wanted = [(c["id"], c["data_defect"]["design_key"]) for c in cb.CASES if c["data_defect"]]
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
}
