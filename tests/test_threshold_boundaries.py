"""The committed catalogue promoted out of Tier 0 of the mutation job (2026-11-02).

WHAT TIER 0 MEASURED. Every declared numeric threshold in `src/cellarium` was perturbed in both
directions and its covering tests re-run: 64 thresholds, 128 mutants. 79 mutants across 43 thresholds
came back SURVIVED -- the value changed and nothing went red. `docs/MUTATION_SCORE_PLAN.md` sec.6 fixed
what to do with that before the run: use the tool for discovery, then promote every interesting survivor
into a committed catalogue, because a survivor list in a JSON file decays and a test does not.

WHY A BOUNDARY CASE AND NOT AN EQUALITY ASSERTION. The cheap way to kill a threshold mutant is
`assert MODULE.THRESHOLD == 0.001`, and it is nearly worthless: it pins the literal while saying nothing
about whether the constant is still WIRED to the decision it names. Each case here drives the real
function with inputs that STRADDLE the declared value -- one step inside, one step outside -- so the test
fails both when the number moves and when the comparison stops using it. The inputs are literals on
purpose: deriving them from the constant would move the goalposts with the mutant and pass forever, which
is the trap `tests/test_extraction.py:1272` fell into (`max_tokens <= AGENT_MAX_TOKENS_CAP` compares the
sent value against the constant itself and therefore cannot detect any change to it -- a non-vacuous
assertion about nothing in particular, which the static suite audit could not see and mutation did).

WHY THE COUNT IS 79 AND NOT 58. The first pass reported 58 survivors, 13 timeouts and 8 errors under a
FLAT 180 s per-mutant budget. With `pytest -x` a killed mutant exits at its first failure and a surviving
one runs the whole covering set, so a flat budget expires preferentially on SURVIVORS -- and it did:
re-run against each covering set's own measured baseline, all 13 timeouts resolved to SURVIVED, none to
killed, and not one already-decided verdict flipped in either direction. The 8 errors were the mutator
failing to find its own literal (`20_000` against `repr(20000)`) and are measured now too. A timeout is
therefore not a neutral verdict here; it was a survivor the budget hid.

WHICH RUN EACH NUMBER COMES FROM. The 79-across-43 above is the PRE-CATALOGUE measurement -- the
finding this module was written to answer. The recorded artefact is the run that FOLLOWED it (pass 3,
2026-11-02): the same 64 thresholds and 128 mutants, killed 75, and 43 surviving mutants across 22
thresholds. Every one of the 21 thresholds that gained a boundary case below came back killed in BOTH
directions, which is what the ratchet asserts; the 22 that remain are the dispositions that were never
a blind spot -- 19 intentionally unpinned, 1 unreachable here, 2 unresolved equivalence. Both figures
are kept because they measure different things: 79/43 is what the suite looked like before the
catalogue, 43/22 is what it looks like after, and `SURVIVORS` is sized to the FORMER so that closing a
blind spot does not quietly drop it out of scope.

ONE TIMEOUT, AND WHY IT IS NOT LEFT AS ONE. Pass 3 produced a single `timeout`: `_PER_SIM_RAM_GB`
doubled, which burned all 303 s of a budget derived from a 97 s baseline while its `half` sibling
finished the same 12 tests in 85 s -- and then finished in 84 s on a re-run with nothing changed but
the hour. A real-time virus scanner, not a hang. The harness now re-runs a timeout once at a far
larger budget before recording it, and that re-run was forced with a one-second budget rather than
waited for. The reason it matters here is narrower than cost: `timeout` is an UNRESOLVED verdict, and
`_survivor_keys()` reads the survivor column, so a stalled covering set was able to carry a threshold
out of the reach of BOTH the ratchet and the disposition completeness check without failing anything.
An unresolved verdict is never evidence that a boundary case bites.

THE DISPOSITION OF ALL 43 IS DECLARED BELOW, not just the ones with a test. Tier 0's pre-registration
allows four verdicts per survivor (blind spot / equivalent mutant / unreachable here / intentionally
unpinned) and the classification IS the result, so an undispositioned survivor is a hole in the finding
rather than a hole in the suite. A fifth, `unresolved_equivalence`, was added during the triage for two
constants that sit in one-line ternaries, where LINE coverage cannot say whether the arm was taken:
guessing either way would have been cheap and wrong, so the ledger says unresolved and names what would
settle it. `SURVIVORS` carries all 43 and the seven tests in `META_TESTS` make it fail when it drifts
-- a survivor with no disposition, a disposition for a constant the tree no longer declares, a boundary
claim naming no test, a threshold claimed as pinned that the latest run still reports as surviving, a
test naming a surviving threshold that nobody has read for self-reference, a harness that credits a
threshold to prose about it rather than code that references it, and a recorded run that left any
verdict unresolved.
"""

import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np  # noqa: E402

from cellarium import (  # noqa: E402
    adjudicate,
    audit,
    calibration,
    deg_claims,
    extraction,
    ko_verify,
    lineage,
    qc,
    raw,
    scan,
    sci2,
    skills,
    surrogate,
    trajectory,
    trna,
    viability_rules,
)
from cellarium.model import GenerationResult  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
TIER0 = REPO / "data" / "mutation" / "tier0_results.json"
MAP = REPO / "data" / "mutation" / "threshold_test_map.json"


# --- qc.py: the guardrail that decides whether a generation may be reported at all ------------------

def _healthy(**kw) -> GenerationResult:
    """A generation that passes every rule, so one field at a time can be pushed over its boundary."""
    base = dict(index=0, n_steps=2500, divided=True, division_time_sec=1000.0)
    base.update(kw)
    return GenerationResult(**base)


def test_the_degenerate_step_count_decides_AT_its_declared_boundary():
    """`DEGENERATE_MAX_STEPS = 10`, inclusive. The fixtures that cover it use 2 steps and 2,530, so both
    +-1 mutants survived: nothing in the suite stood at the edge. A run of exactly 10 steps is the case
    the rule was written for -- 'a generation that ran two timesteps' generalises to 'a handful'."""
    assert qc.check_generation(_healthy(n_steps=10)) is qc.QCStatus.DEGENERATE
    assert qc.check_generation(_healthy(n_steps=11)) is qc.QCStatus.OK


def test_the_implausible_growth_ceiling_decides_AT_its_declared_boundary():
    """`IMPLAUSIBLE_GROWTH = 0.001`, exclusive. The declared basis is measured: with_aa peaks near 0.0005
    and the gltX post-collapse garbage read 0.0013-0.0021, so the boundary sits between a real fast cell
    and crash output. Halving it would withhold real runs; doubling it would report crash garbage. Both
    mutants survived nine covering tests."""
    assert qc.check_generation(_healthy(growth_mean=0.0011)) is qc.QCStatus.IMPLAUSIBLE
    assert qc.check_generation(_healthy(growth_mean=0.0009)) is qc.QCStatus.OK


# --- ko_verify.py: whether a knockout in the corpus is actually a knockout ---------------------------

def test_the_silencing_ceiling_decides_AT_its_declared_boundary():
    """`_SILENCED_MAX = 0.02`, inclusive. This is the predicate behind every `KO:` design's claim to BE a
    knockout, and the corpus is built on it. A null far from the target keeps the z-test out of the way so
    the case isolates one threshold."""
    null = {"median": 0.5, "sd": 1.0}
    assert ko_verify._classify(0.02, null) == "silenced"
    assert ko_verify._classify(0.021, null) == "expressed"


def test_the_specificity_z_decides_AT_its_declared_boundary():
    """`_SPECIFIC_Z = 3.0`: below the crowd by more than three times the crowd's own spread. With the null
    at median 1.0 and sd 0.1, a ratio of 0.69 is 3.1 sd below and 0.75 is 2.5 -- one each side."""
    null = {"median": 1.0, "sd": 0.1}
    assert ko_verify._classify(0.69, null) == "specifically_reduced"
    assert ko_verify._classify(0.75, null) == "expressed"


# --- audit.py: the storage model behind every corpus-size figure ------------------------------------

def test_the_per_generation_storage_estimate_is_pinned_to_a_worked_case():
    """`GB_PER_GENERATION = 0.65` for a dividing lineage. Not a boundary -- a linear coefficient has none
    -- so the case is a worked arithmetic one, which is what a coefficient needs: halving or doubling it
    silently halves or doubles every GB figure the audit reports, and six covering tests noticed neither.

    Checked against the sibling constant on purpose: `GB_PER_GENERATION_ARRESTED` is referenced NOWHERE in
    the tree while the comment above it tells the reader to 'use GB_PER_GENERATION_ARRESTED and say so',
    so the arrested case is estimated with the dividing coefficient today."""
    assert audit._gb(100, 2) == 130.0
    assert audit._gb(1, 1) == 0.65
    assert audit._gb(None, 1) == 0.0


# --- trajectory.py: which argument strings count as a handle to check ------------------------------

def test_the_handle_length_floor_decides_AT_its_declared_boundary():
    """`MIN_HANDLE_LEN = 4`, inclusive. Below it a value is too short to be a meaningful id and checking it
    would flag every legitimate short argument; at it, a four-character gene name must still be checked.
    Fourteen covering tests, neither mutant noticed."""
    assert trajectory._handle_values({"gene": "argS"}) == [("gene", "argS")]
    assert trajectory._handle_values({"gene": "arg"}) == []


# --- extraction.py: how an outside document is cut into citable units -------------------------------

def _line(*segments: str) -> str:
    return "".join(segments)


def test_a_span_at_the_citable_unit_maximum_is_left_whole_and_one_over_is_split():
    """`CITABLE_UNIT_MAX = 300`, inclusive: a line this long or shorter is one citable unit, longer and it
    is cut at sentence boundaries. 56 tests cover the line and none of them has a span near 300, so both
    mutants survived -- the widest covering set in Tier 0 and still blind at the edge."""
    unit = "x" * 48 + ". "                       # 50 characters, ending in a sentence break
    exactly = unit * 6                           # 300
    one_over = unit * 6 + "y"                    # 301
    assert len(exactly) == 300 and len(one_over) == 301
    assert extraction._sentence_spans(exactly, 0, len(exactly)) == [(0, 300)]
    assert len(extraction._sentence_spans(one_over, 0, len(one_over))) > 1


def test_the_minimum_unit_length_decides_which_sentence_breaks_become_cuts():
    """`MIN_UNIT_CHARS = 40`: a sentence break closer than this to the previous cut is not a cut, so a
    citable unit is never a fragment. Only the `double` mutant was caught (by an unrelated assertion);
    halving it to 20 admitted more, smaller units and nothing noticed.

    The line carries breaks at 30, 100, 160 and 350 characters, which separates all three values: at 20
    every break cuts (5 spans), at 40 the 30 is too close (4 spans), at 80 the 160 is too (3 spans)."""
    line = _line("a" * 28 + ". ", "b" * 68 + ". ", "c" * 58 + ". ", "d" * 188 + ". ", "e" * 10)
    assert len(line) == 360                       # > CITABLE_UNIT_MAX, so it is eligible for splitting
    spans = extraction._sentence_spans(line, 0, len(line))
    assert [hi for _lo, hi in spans] == [100, 160, 350, 360]


def test_the_agent_token_cap_has_a_FLOOR_and_not_only_a_ceiling():
    """`AGENT_MAX_TOKENS_CAP = 12000`. The existing pair of assertions is one-sided: `<= 16000` caught the
    doubling, and `max_tokens <= AGENT_MAX_TOKENS_CAP` compares the sent value against the constant itself
    and so cannot catch anything. Halving the cap survived 44 covering tests.

    It is not a free parameter. The comment above it records two live failures: a single whole-document
    prompt returned no text block at moderate budgets, and a retry at a tripled budget tripped the SDK's
    ten-minute streaming guard. A silently lower cap truncates a section's records instead of erroring,
    which is the one failure mode this module is built to avoid."""
    assert extraction.AGENT_MAX_TOKENS_CAP == 12000
    assert 8000 <= extraction.AGENT_MAX_TOKENS_CAP <= 16000


# --- sci2.py: the DE call behind the reported RNA-seq concordance ------------------------------------

def test_the_log2FC_significance_cut_decides_WHICH_genes_sign_concordance_is_scored_on():
    """`DEG_SIG = 1.0`: the |log2FC| a DE call must clear. It selects the gene set that `sign_rate` -- the
    load-bearing agreement number -- is computed over, and both mutants survived three covering tests.

    Twelve genes, six at exactly the boundary with the sim agreeing in sign and six below it with the sim
    disagreeing. At 1.0 the rate is 1.0 (only the six strong genes count); at 0.5 all twelve count and it
    falls to 0.5; at 2.0 nothing counts and it is None."""
    strong = {f"b{i:04d}": 1.0 for i in range(6)}
    weak = {f"b{i:04d}": 0.6 for i in range(6, 12)}
    ref = {**strong, **weak}
    sim = {**{g: 2.0 for g in strong}, **{g: -0.6 for g in weak}}
    out = sci2.concordance(sim, ref)
    assert out["join_qc"]["n_joined"] == 12
    assert out["n_ref_significant"] == 6        # 12 at a cut of 0.5, 0 at a cut of 2.0
    assert out["sign_concordance"] == 1.0       # 0.5 and None respectively


# --- adjudicate.py: the decidability gate ------------------------------------------------------------

_KB = "a" * 64


def _arow(design, seeds=4):
    return {"design": design, "kb_sha256": _KB, "operons": "on",
            "elongation_model": "steady_state", "seeds": seeds}


def test_an_arm_holding_EXACTLY_the_minimum_replicate_seeds_is_decidable():
    """`MIN_REPLICATE_SEEDS = 2`. Lowering it to 1 is caught (a one-row arm must stay insufficient), but
    RAISING it to 3 survived: the covering tests have a one-row design and four-row designs and nothing in
    between, so a corpus holding exactly the declared minimum was never asked. That is the direction that
    silently withholds comparisons the corpus can in fact support."""
    rows = [_arow("gene_knockout/KO:pheS") for _ in range(2)] + \
           [_arow("wildtype/basal") for _ in range(4)]
    claim = adjudicate.Claim(quantity="growth rate falls", target="gene_knockout/KO:pheS",
                             reference="wildtype/basal", quote="growth rate falls by 20% in pheS",
                             section="Expected Outcomes", section_kind="claim")
    v = adjudicate.adjudicate_claim(claim, rows=rows)
    assert v["decidable"] is True and "error" not in v
    assert v["n_target_rows"] == 2 and v["n_reference_rows"] == 4


# --- calibration.py: which observations still count as calibration ----------------------------------

def test_the_staleness_cutoff_decides_AT_its_declared_boundary(tmp_path, monkeypatch):
    """`_STALE_DAYS = 180.0` -- older than this is history, not calibration, because hardware and images
    change. Seventeen covering tests and neither mutant noticed: the fixtures record observations at the
    current time, so nothing in the suite sat near six months."""
    store = tmp_path / "observations.json"
    now, day = time.time(), 86400.0
    host = calibration._host_key()
    store.write_text(json.dumps([
        {"kind": "per_sim_ram_gb", "value": 1.5, "ts": now - 179 * day, "host": host},
        {"kind": "per_sim_ram_gb", "value": 9.5, "ts": now - 181 * day, "host": host},
    ]), encoding="utf-8")
    monkeypatch.setattr(calibration, "OBSERVATIONS_PATH", store)
    assert calibration._values("per_sim_ram_gb") == [1.5]


# --- lineage.py: whether a generation's descendants may be reported at all ---------------------------

def _gens(dur: float) -> list[dict]:
    """Two generations, the first lasting `dur` seconds, so the first one HAS a successor and is classified
    rather than being the terminal generation."""
    return [{"i": 0, "t_start": 0.0, "t_end": dur, "divided": True},
            {"i": 1, "t_start": dur, "t_end": dur + 1800.0, "divided": True}]


def test_a_generation_ending_INSIDE_the_cap_tolerance_is_time_capped_and_one_second_earlier_is_not():
    """`CAP_TOLERANCE_S = 30.0` against `CAP_S = 10800`: a generation ending at or after 10770 s was stopped
    by the simulator's time cap, so every generation descending from it is suspect. Both mutants survived
    sixteen covering tests -- the fixtures use durations far from the cap, so the band was never probed.

    The literals are the band's two sides, not `CAP_S - CAP_TOLERANCE_S`: deriving them would move the
    goalposts with the mutant. Halving the tolerance moves the cutoff to 10785 and reclassifies the first
    case; doubling it moves it to 10740 and reclassifies the second."""
    assert [c["status"] for c in lineage.classify(_gens(10770.0))] == ["time_capped", "terminal"]
    assert [c["status"] for c in lineage.classify(_gens(10769.0))] == ["divided", "terminal"]


# --- viability_rules.py: the published cross-seed verdict --------------------------------------------

def test_the_viable_rate_FLOOR_decides_AT_its_declared_boundary():
    """`VIABLE_MIN_RATE = 0.9`. Doubling it is caught (no division rate reaches 1.8), but HALVING it to 0.45
    survived all twelve covering tests: nothing in the suite sits between 0.45 and 0.9, so a rule that
    called impaired lineages viable would have passed. This is the verdict shipped in the dataset.

    THIS PINS THE WIRING, NOT THE NUMBER. `M-9` records that 0.9 and 0.6 were set on n=1 machinery and are
    owed a calibration against a machinery + graded-KO panel. A boundary case is not an endorsement of the
    value: it says the constant is still the thing the verdict turns on, so that changing it is a decision
    someone takes on purpose -- editing the literal here -- instead of a number drifting unnoticed."""
    assert viability_rules.verdict(0.9, True, True, 0) == "viable"
    assert viability_rules.verdict(0.89, True, True, 0) == "impaired"


def test_the_inviable_rate_CEILING_decides_AT_its_declared_boundary():
    """`INVIABLE_MAX_RATE = 0.6`, the other side of the same three-way verdict. Same asymmetry: doubling to
    1.2 is caught because it swallows every rate, halving to 0.3 survived."""
    assert viability_rules.verdict(0.59, True, True, 0) == "inviable"
    assert viability_rules.verdict(0.6, True, True, 0) == "impaired"


# --- surrogate.py: whether the surrogate cross-validates or abstains --------------------------------

_HAS_SKLEARN = surrogate._sklearn() is not None


def _labels(n_viable: int, n_dead: int) -> dict:
    """A cleanly separable synthetic labeled set at an EXACT n. `tests/test_surrogate.py`'s own helper is
    parameterised by `n_each` and reaches 7 and 9 but never 8, which is why the boundary went unprobed."""
    from collections import Counter
    X = [[0, 1, 0, 1, 0, 0, 1.0]] * n_viable + [[1, 0, 0, 0, 0, 1, 0.5]] * n_dead
    y = [1] * n_viable + [0] * n_dead
    verdicts = ["viable"] * n_viable + ["inviable"] * n_dead
    n = n_viable + n_dead
    return {"X": X, "y": y, "genes": [f"g{i}" for i in range(n)], "verdicts": verdicts, "n": n,
            "class_balance": dict(Counter(verdicts)), "n_viable": n_viable, "n_non_viable": n_dead,
            "majority_baseline": round(max(n_viable, n_dead) / n, 3), "features": surrogate.FEATURES,
            "note": "synthetic"}


@pytest.mark.skipif(not _HAS_SKLEARN, reason="scikit-learn not installed (surrogate extra)")
def test_the_label_count_FLOOR_decides_whether_the_surrogate_cross_validates_or_abstains():
    """`MIN_LABELS = 8` -- below it the fit is reported descriptive-only, because leave-one-out CV at tiny n
    is meaningless. Both mutants survived nine covering tests, and the one test that NAMES the constant
    asserts `out["n"] < surrogate.MIN_LABELS` on a three-label set, which holds at every floor above three.

    The honest abstention is the product here: raising the floor silently withholds a fit the corpus can
    support, and lowering it publishes a cross-validated accuracy that means nothing."""
    assert surrogate.train(_labels(5, 3), n_permutations=0)["trained"] is True
    assert surrogate.train(_labels(5, 3), n_permutations=0)["cv"] == "leave-one-out"
    out = surrogate.train(_labels(4, 3), n_permutations=0)
    assert out["trained"] is False
    assert "need >=8" in out["note"]            # the floor is REPORTED to the reader, so pin that text too


# --- scan.py: the robust sigma behind every anomaly z-score -----------------------------------------

def test_the_mad_to_sigma_coefficient_is_pinned_to_a_worked_case():
    """`_MAD_C = 1.4826` converts a median absolute deviation into a normal-equivalent sigma, and it divides
    every z-score the scanner reports. A coefficient has no boundary, so this is a worked case: the first
    sample below has a MAD of exactly 2, so the estimate must be 2 x 1.4826.

    Doubling the coefficient was caught; halving it survived twenty covering tests, which means the scanner
    could have been reporting z-scores twice too large with nothing going red."""
    assert scan._mad(np.array([1.0, 3.0, 5.0, 7.0, 9.0])) == pytest.approx(2.9652)
    assert scan._mad(np.array([1.0, 2.0, 3.0, 4.0, 5.0])) == pytest.approx(1.4826)
    assert scan._mad(np.array([4.0, 4.0, 4.0])) == pytest.approx(1e-12)    # the degenerate guard


# --- deg_claims.py: the bounded walk behind "does this claim rest on a non-fit?" ---------------------

def test_the_payload_walk_reaches_its_declared_DEPTH_and_stops_one_level_deeper():
    """`_MAX_DEPTH = 8`. Eleven nested keys go in; the keys at depths 0..8 must come out and `id9` must not.

    Why this matters beyond termination: `payload_hits` returns `clear` when it finds no non-fit gene, and
    the walk drops identifiers past the bound WITHOUT saying so, so a payload deeper than the bound can be
    reported clear for a reason that is really "not looked at". The existing `test_walk_is_bounded` asserts
    `len(seen) <= _MAX_NODES`, which is true at every value of the bound."""
    node: object = {"id10": "zzz_leaf"}
    for k in range(9, -1, -1):
        node = {f"id{k}": node}
    out: set = set()
    deg_claims._walk(node, out)
    assert out == {f"id{i}" for i in range(9)}


def test_the_payload_walk_collects_its_declared_NODE_budget_and_no_more():
    """`_MAX_NODES = 4000`: one key plus 3,998 of the 5,000 list members, because the budget is spent one
    per visited node, the list itself included. The literal 3999 is the whole point -- halving the budget
    gives 1,999 and doubling it gives all 5,001."""
    out: set = set()
    deg_claims._walk({"rows": [f"g{i}_rna" for i in range(5000)]}, out)
    assert len(out) == 3999 and "rows" in out


# --- skills.py: the outbound fetch cap, and whether it admits to truncating --------------------------

def _stub_opener(monkeypatch, n_bytes: int) -> None:
    """An offline opener whose body is a LITERAL size. Returning `b"a" * n` for the requested `n` would
    track the mutant and the test could never fail -- the self-referential trap in fixture form."""
    class _Resp:
        status = 200

        def read(self, _n): return b"a" * n_bytes
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class _Opener:
        def open(self, *a, **k): return _Resp()

    monkeypatch.setattr(skills.urllib.request, "build_opener", lambda *a, **k: _Opener())


def test_the_fetch_cap_truncates_AT_its_declared_size_and_SAYS_it_did(monkeypatch):
    """`_MAX_BYTES = 200_000`. The code reads one byte past the cap precisely so `truncated` can be
    computed, and its single covering test returns a 26-byte sentinel -- so the truncation path had never
    been taken and both mutants survived. A silently truncated literature page is the silent-absence shape
    this suite exists to prevent."""
    _stub_opener(monkeypatch, 200_001)
    out = skills.web_get("https://api.openalex.org/works?search=aars")
    assert out["truncated"] is True and len(out["body"]) == 200_000
    _stub_opener(monkeypatch, 200_000)
    out = skills.web_get("https://api.openalex.org/works?search=aars")
    assert out["truncated"] is False and len(out["body"]) == 200_000


# --- trna.py: whether a run carries charging dynamics or is arithmetic -------------------------------

def test_the_arrest_total_variation_CUT_decides_AT_its_declared_boundary(monkeypatch):
    """`_ARREST_TOTVAR = 1e-6`: below this total variation in the per-timestep row mean, the charged-fraction
    vector is a constant and the run's per-family table is arithmetic rather than a measurement. Both
    mutants survived six covering tests, which read the live corpus and so never sat near the cut.

    The declaration's own comment cites the two populations it separates (wild type ~1.5, arrested
    synthetase KOs ~1.2e-07), which is why the mutants are harmless ON THIS CORPUS -- and exactly why the
    cut needs a fixture inside the gap rather than resting on that margin staying true."""
    def _series(x):
        def read_column(path):
            if path.replace("\\", "/").endswith("GrowthLimits/fraction_trna_charged"):
                return [[0.0], [0.0], [x]]
            raise FileNotFoundError(path)
        return read_column

    monkeypatch.setattr(raw, "simout_dirs", lambda root: ["/fake/simout"])

    monkeypatch.setattr(raw, "read_column", _series(5e-7))
    ev = trna._arrest_evidence("/fake/seed")
    assert ev["row_mean_total_variation"] == pytest.approx(5e-7) and ev["arrested"] is True

    monkeypatch.setattr(raw, "read_column", _series(1.5e-6))
    ev = trna._arrest_evidence("/fake/seed")
    assert ev["row_mean_total_variation"] == pytest.approx(1.5e-6) and ev["arrested"] is False


# --- the ledger: every one of the 43 survivor thresholds, and what was decided about it -------------

# kind: "boundary" a case in this file | "delegated" a named test elsewhere | "declared" no test, with the
# reason. `docs/MUTATION_SCORE_PLAN.md` sec.7's four verdicts map onto these: a blind spot earns a case, an
# equivalent or intentionally-unpinned mutant earns a declaration, and an unreachable one says so.
SURVIVORS: dict[str, tuple[str, str, str]] = {
    # --- blind spots, now pinned here ---
    "qc.py::DEGENERATE_MAX_STEPS": (
        "blind_spot", "boundary", "test_the_degenerate_step_count_decides_AT_its_declared_boundary"),
    "qc.py::IMPLAUSIBLE_GROWTH": (
        "blind_spot", "boundary", "test_the_implausible_growth_ceiling_decides_AT_its_declared_boundary"),
    "ko_verify.py::_SILENCED_MAX": (
        "blind_spot", "boundary", "test_the_silencing_ceiling_decides_AT_its_declared_boundary"),
    "ko_verify.py::_SPECIFIC_Z": (
        "blind_spot", "boundary", "test_the_specificity_z_decides_AT_its_declared_boundary"),
    "audit.py::GB_PER_GENERATION": (
        "blind_spot", "boundary", "test_the_per_generation_storage_estimate_is_pinned_to_a_worked_case"),
    "trajectory.py::MIN_HANDLE_LEN": (
        "blind_spot", "boundary", "test_the_handle_length_floor_decides_AT_its_declared_boundary"),
    "extraction.py::CITABLE_UNIT_MAX": (
        "blind_spot", "boundary",
        "test_a_span_at_the_citable_unit_maximum_is_left_whole_and_one_over_is_split"),
    "extraction.py::MIN_UNIT_CHARS": (
        "blind_spot", "boundary",
        "test_the_minimum_unit_length_decides_which_sentence_breaks_become_cuts"),
    "extraction.py::AGENT_MAX_TOKENS_CAP": (
        "blind_spot", "boundary", "test_the_agent_token_cap_has_a_FLOOR_and_not_only_a_ceiling"),
    "sci2.py::DEG_SIG": (
        "blind_spot", "boundary",
        "test_the_log2FC_significance_cut_decides_WHICH_genes_sign_concordance_is_scored_on"),
    "adjudicate.py::MIN_REPLICATE_SEEDS": (
        "blind_spot", "boundary",
        "test_an_arm_holding_EXACTLY_the_minimum_replicate_seeds_is_decidable"),
    "calibration.py::_STALE_DAYS": (
        "blind_spot", "boundary", "test_the_staleness_cutoff_decides_AT_its_declared_boundary"),

    # --- blind spots the RE-RUN exposed. Every one of these was a `timeout` or an `error` in the first
    # pass, which is why none of them is in the paragraph above. Not one was a hang. ---
    "lineage.py::CAP_TOLERANCE_S": (
        "blind_spot", "boundary",
        "test_a_generation_ending_INSIDE_the_cap_tolerance_is_time_capped_and_one_second_earlier_is_not"),
    "viability_rules.py::VIABLE_MIN_RATE": (
        "blind_spot", "boundary", "test_the_viable_rate_FLOOR_decides_AT_its_declared_boundary"),
    "viability_rules.py::INVIABLE_MAX_RATE": (
        "blind_spot", "boundary", "test_the_inviable_rate_CEILING_decides_AT_its_declared_boundary"),
    "surrogate.py::MIN_LABELS": (
        "blind_spot", "boundary",
        "test_the_label_count_FLOOR_decides_whether_the_surrogate_cross_validates_or_abstains"),
    "scan.py::_MAD_C": (
        "blind_spot", "boundary", "test_the_mad_to_sigma_coefficient_is_pinned_to_a_worked_case"),
    "deg_claims.py::_MAX_DEPTH": (
        "blind_spot", "boundary",
        "test_the_payload_walk_reaches_its_declared_DEPTH_and_stops_one_level_deeper"),
    "deg_claims.py::_MAX_NODES": (
        "blind_spot", "boundary",
        "test_the_payload_walk_collects_its_declared_NODE_budget_and_no_more"),
    "skills.py::_MAX_BYTES": (
        "blind_spot", "boundary", "test_the_fetch_cap_truncates_AT_its_declared_size_and_SAYS_it_did"),
    "trna.py::_ARREST_TOTVAR": (
        "blind_spot", "boundary", "test_the_arrest_total_variation_CUT_decides_AT_its_declared_boundary"),

    # --- a blind spot whose behavioural test is not reachable on this machine ---
    "sci2.py::PADJ_SIG": (
        "unreachable_here", "declared",
        "the padj cut selects DESeq2's confidently-resolved set inside `rnaseq_concordance`, which needs "
        "`build_reference(contrast)` and therefore the reference dataset. Its one covering test fails loud "
        "on a namespace mismatch before any significance decision is taken, so the line is executed and "
        "nothing depends on its value. Pinning it needs a committed reference fixture -- recorded as a "
        "blind spot that is UNMEASURED here, not as a pass."),

    # --- intentionally unpinned: declared operating judgements the paper does not rest on ---
    "agent.py::_ERR_CAP": (
        "intentionally_unpinned", "declared",
        "consecutive all-errored rounds before the loop calls itself stuck (DD-ENG-3). A judgement about "
        "patience; any small value is defensible and freezing one buys nothing."),
    "agent.py::_THOUGHT_OUT_EXTRA": (
        "intentionally_unpinned", "declared",
        "extra tokens granted to the single retry of a truncated reply. A tuning term, bounded by the "
        "provider's own cap, with no claim resting on its size."),
    "harness.py::_TRIAGE_THRESHOLD": (
        "intentionally_unpinned", "declared",
        "occurrences before a gap row earns a display flag. Presentation, not a decision about data."),
    "harness.py::_MAX_NEW_PER_CALL": (
        "intentionally_unpinned", "declared",
        "flood guard on new gap rows per scan. A rate limit's exact value is operational."),
    "runner.py::WALL_STARTUP_MIN": (
        "intentionally_unpinned", "declared",
        "startup term in a wall-clock ESTIMATE shown to a human before launching a sweep. Being wrong "
        "makes the estimate worse, not the corpus."),
    "resources.py::_RAM_HEADROOM_GB": (
        "intentionally_unpinned", "declared",
        "RAM kept free beyond a sweep's need. A safety margin, declared in its own comment."),
    "resources.py::_DISK_HEADROOM_GB": (
        "intentionally_unpinned", "declared",
        "disk kept free beyond a sweep's raw output. Same class as the RAM headroom."),
    "resources.py::_PER_RUN_MIN_PER_GEN": (
        "intentionally_unpinned", "declared",
        "minutes per run per generation for the time-budget estimate, and its own comment says 'rough'."),
    "resources.py::_WALL_WARN_HOURS": (
        "intentionally_unpinned", "declared",
        "warns, never blocks, past this estimated wall time. A judgement about what is too long to sit "
        "through."),
    "calibration.py::MAX_RECORDS": (
        "intentionally_unpinned", "declared",
        "keeps the observations file bounded, oldest dropped first. What matters is that trimming keeps "
        "the NEWEST records, which `test_calibration.py` covers; the cap's size is housekeeping."),
    "audit.py::TARGET_SEEDS": (
        "intentionally_unpinned", "declared",
        "the replication target four public functions default to. The number is the project's own "
        "judgement about power and the audit reports it rather than hiding it; a test pinning it would "
        "only restate the default."),
    "sci2.py::NULL_PERMUTATIONS": (
        "intentionally_unpinned", "declared",
        "draws in the shuffled-label baseline. More draws is a strictly better estimate, so no value is "
        "correct and none should be frozen. The count is reported alongside the result, which is the "
        "property that matters; what deserves a test is that the number REPORTED equals the number drawn, "
        "and a mutation of the constant cannot distinguish that."),
    "credentials.py::_MIN_LEN": (
        "intentionally_unpinned", "declared",
        "below this a pasted key is a truncated paste rather than a key. A sanity floor on a format whose "
        "real lengths are far above it; the surrounding tests cover the refusal, not the digit."),
    "dynamics.py::_WINDOW_S": (
        "intentionally_unpinned", "declared",
        "the 15-minute response window for a shift transient, declared with its reasoning and REPORTED in "
        "the finding's own text ('the extremum is the LAST sample of the 900s response window'). A reader "
        "is told the window; the value is a methods choice, not a result."),
    "dynamics.py::_BASELINE_S": (
        "intentionally_unpinned", "declared",
        "the pre-shift baseline window the response is measured against. Same class as `_WINDOW_S`: a "
        "declared methods choice, reported with the finding rather than standing behind it."),
    "dynamics.py::_DESPIKE_K": (
        "intentionally_unpinned", "declared",
        "rolling-median width that kills 1-2 sample excursions, declared as 'far shorter than any "
        "adaptation'. A filter width, not a decision boundary."),
    "doe.py::_SEARCH_BUDGET": (
        "intentionally_unpinned", "declared",
        "generator-assignment combinations evaluated before the search falls back to sampling. What it "
        "moves is the provenance LABEL, and that label reports the budget it used ('exhaustive' against "
        "`sampled(20000 of N)`), so a reader is told which search ran -- the `NULL_PERMUTATIONS` shape. "
        "Probing the switch needs a design astride the C(n,p) lattice near 20,000 and costs that many "
        "scorings, buying a test of the budget rather than of the design algebra that "
        "`test_doe_generators.py` already re-derives by brute force."),
    "similarity.py::_NULL_CAP": (
        "intentionally_unpinned", "declared",
        "subsets evaluated before the null distribution is strided instead of enumerated; its own comment "
        "records the hang it was written to stop (C(50,6) = 15,890,700). Lowering it coarsens the null's "
        "resolution and cannot change which side of the percentile a cluster falls on at this corpus "
        "size; probing the stride boundary means enumerating tens of thousands of subsets in a unit test."),
    "tools.py::SURVEY_DIGEST_CHARS": (
        "intentionally_unpinned", "declared",
        "the digest's packing budget. Its DECLARED property is the ordering -- below `agent._TOOL_CAPS` so "
        "the agent never cuts it -- and the raise-side mutant breaks that and is killed. The lower side "
        "only shows fewer rows per channel, each channel reports `n_not_shown`, and the channel LIST stays "
        "complete, so nothing goes silently unseen; that completeness is budget-independent and "
        "`test_the_survey_fits_its_budget_by_showing_fewer_rows_and_saying_so` asserts it directly."),

    # --- unresolved between equivalent and blind spot, and said so rather than guessed ---
    "resources.py::_PER_SIM_RAM_GB": (
        "unresolved_equivalence", "declared",
        "read only when no MEASURED calibration exists (`ram_cal['basis'] != 'measured'`). Whether the "
        "covering tests ever take that arm cannot be told from LINE coverage, because both arms of the "
        "ternary sit on one line. Branch coverage would settle it; until then this is recorded as "
        "possibly-equivalent rather than classified by guess."),
    "resources.py::_FALLBACK_RUN_GB": (
        "unresolved_equivalence", "declared",
        "per-run disk used only when the corpus cannot be measured, and its comment cites the observation "
        "it came from ('observed ~1.06 GB/run'). Same one-line ternary problem as `_PER_SIM_RAM_GB`."),
}

# A test that NAMES a threshold and did not notice it change is the one shape worth reading by hand, and
# the join that finds it is measured rather than guessed: `tests_naming` from the map, intersected with the
# survivors from the run. Nine tests were in it on 2026-11-02 -- five after the first pass, three more once the re-run resolved
# the timeouts, and one of this module's own cases -- and SEVEN assert the constant against itself,
# so a mutation moves the expectation along with the code and the assertion holds for every value. Both
# halves of `_Z` are reviewed below; a new member of the join with no verdict fails the suite, because the
# static vacuity audit scored all five non-vacuous -- they do assert something, just nothing about the
# number -- and only mutation separated them.
SELF_REFERENTIAL_REVIEW: dict[str, tuple[str, str]] = {
    "tests/test_audit.py::test_gb_estimate_scales_with_generations_and_seeds": (
        "self_referential",
        "`_gb(8, 1) == round(8 * audit.GB_PER_GENERATION, 2)` re-implements the function under test with "
        "the same constant, so any value of it passes. Pinned here instead by a worked case."),
    "tests/test_extraction.py::test_the_per_span_budget_stays_under_the_streaming_threshold": (
        "self_referential",
        "`max_tokens <= extraction.AGENT_MAX_TOKENS_CAP` compares the sent value against the constant that "
        "produced it. Its companion `<= 16000` is a one-sided bound: it catches raising the cap and not "
        "lowering it. Pinned here two-sidedly."),
    "tests/test_extraction.py::test_a_long_unwrapped_paragraph_is_split_into_sentence_sized_units": (
        "self_referential",
        "`max(len(u['text'])) <= extraction.CITABLE_UNIT_MAX` holds at every cap: lower it and the units "
        "shrink with it, raise it and they stay inside. Pinned here with literal lengths."),
    "tests/test_failures.py::test_the_wall_limit_scales_with_generations_and_can_be_turned_off": (
        "self_referential",
        "`wall_limit_s(4) == 60 * (runner.WALL_STARTUP_MIN + 4 * runner.WALL_MIN_PER_GEN)` restates the "
        "implementation. The constant is a declared estimate term nobody should freeze, so the finding is "
        "about the test's FORM, not the number: a test that re-derives the formula it checks asserts that "
        "the arithmetic was typed twice the same way."),
    "tests/test_deg_payload.py::test_walk_is_bounded": (
        "self_referential",
        "`len(seen) <= D._MAX_NODES` is the bound asserting itself: it holds at every value, and the only "
        "thing it can detect is the bound being REMOVED. The 200-deep case is weaker still -- that payload "
        "holds about 201 nodes, so the inequality is slack by a factor of twenty and says nothing about "
        "depth either. Pinned here by two literal counts instead."),
    "tests/test_discovery_leg_fixes.py::test_the_survey_fits_its_budget_by_showing_fewer_rows_and_saying_so": (
        "self_referential",
        "`len(json.dumps(d)) <= tools.SURVEY_DIGEST_CHARS` cannot fail: the digest is built by shrinking "
        "until it fits whatever the budget is. The chained right half, `< agent._TOOL_CAPS`, IS a real "
        "relation and is what kills the raise-side mutant -- one-sided, exactly like the "
        "`AGENT_MAX_TOKENS_CAP` pair. The budget-independent assertions around it (24 channels present, "
        "`n_not_shown` consistent with `shown`) are the properties that matter, and they are correct."),
    "tests/test_surrogate.py::test_train_reports_baseline_and_abstains_when_underpowered": (
        "self_referential",
        "`out['n'] < surrogate.MIN_LABELS` on a three-label set holds at every floor above three, so it "
        "cannot see the floor move. The abstention itself is genuinely asserted, which is why the test is "
        "worth keeping; what it does not pin is WHERE the surrogate starts trusting a fit."),
    "tests/test_threshold_boundaries.py::test_the_agent_token_cap_has_a_FLOOR_and_not_only_a_ceiling": (
        "pins_a_literal",
        "this module's own case, and it is in the join for the right reason: `AGENT_MAX_TOKENS_CAP == "
        "12000` names the constant and asserts a LITERAL against it, so the expectation does not move "
        "with the mutant. It is the shape the four self-referential entries above should have had. Listed "
        "rather than left to drop out of the join when the threshold stops surviving, because a verdict "
        "that depends on being killed is not a review."),
    "tests/test_extraction.py::test_a_long_line_with_no_sentence_boundary_stays_ONE_unit_and_is_not_truncated": (
        "correct_precondition",
        "`len(row) > extraction.CITABLE_UNIT_MAX` names the constant to keep the FIXTURE valid if the cap "
        "moves, which is the right way to write it. The property under test -- a line with no sentence "
        "boundary stays one unit -- is genuinely independent of the cap, so surviving both mutants is the "
        "correct outcome and not a defect."),
}

# A test in the join either cannot see the constant move (`self_referential`), names it for a reason
# that is correct and value-independent (`correct_precondition`), or asserts a LITERAL against it,
# which is the form this module exists to write (`pins_a_literal`). The third was added when a
# boundary case here entered the join on its own merit and neither existing label fitted it.
_REVIEW_VERDICTS = ("self_referential", "correct_precondition", "pins_a_literal")
_KINDS = ("boundary", "delegated", "declared")

# The tests in this file that are ABOUT the ledger rather than about a threshold. Declared so that a new
# test has to be one or the other and cannot arrive unaccounted for.
META_TESTS = {
    "test_every_threshold_tier0_recorded_as_a_survivor_has_a_disposition",
    "test_every_disposition_names_a_threshold_that_still_exists",
    "test_every_disposition_is_one_of_the_declared_kinds_and_delivers_what_it_claims",
    "test_the_thresholds_this_module_claims_to_pin_are_no_longer_survivors",
    "test_every_test_that_named_a_surviving_threshold_has_been_read_for_self_reference",
    "test_the_harness_credits_a_threshold_to_code_that_references_it_and_not_to_prose_about_it",
    "test_the_recorded_run_left_no_verdict_unresolved",
}
_VERDICTS = ("blind_spot", "intentionally_unpinned", "unreachable_here", "unresolved_equivalence",
             "equivalent_mutant")


def _harness():
    """`scripts/mutate_thresholds.py`, imported for its `thresholds()` -- the single definition of what
    counts as a declared threshold."""
    import importlib.util
    path = REPO / "scripts" / "mutate_thresholds.py"
    spec = importlib.util.spec_from_file_location("_mutate_thresholds", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _survivor_keys() -> set[str]:
    """Every threshold the recorded run did not settle as KILLED.

    `timeout` sits alongside `SURVIVED` here on purpose. Under `pytest -x` a stalled covering set and a
    surviving one look identical from the outside -- both spend the whole budget without a failure -- so
    reading only the `SURVIVED` column let a timed-out threshold slip past the ratchet AND the disposition
    completeness check at once. That is not hypothetical: pass 3's `_PER_SIM_RAM_GB` row would have left
    the ledger's scope on a virus scanner's timing. An unresolved verdict is never evidence of a kill.
    """
    rows = json.loads(TIER0.read_text(encoding="utf-8"))["results"]
    return {f"{r['module']}::{r['name']}" for r in rows if r["verdict"] in ("SURVIVED", "timeout")}


def _unresolved(rows: list[dict]) -> list[str]:
    """The mutants whose verdict decided nothing: `timeout` (the set stalled, or the mutant hung it) and
    `error` (the mutator could not find its own literal). A separate function so the check below can be
    forced against planted rows instead of waiting for a run to misbehave."""
    return sorted(f"{r['module']}::{r['name']} {r['mutant']} -> {r['verdict']}"
                  for r in rows if r["verdict"] in ("timeout", "error"))


def _own_test_names() -> set[str]:
    import ast
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    return {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")}


@pytest.mark.skipif(not TIER0.is_file(), reason="Tier 0 results absent; run `mutate_thresholds.py run`")
def test_every_threshold_tier0_recorded_as_a_survivor_has_a_disposition():
    """The completeness assertion. A new survivor with no entry here is a hole in the FINDING -- Tier 0's
    deliverable is the classification, not the count -- so it fails the suite rather than waiting to be
    noticed. Checking only the entries that exist today is what let 53 of 68 recorded values go undriven."""
    missing = sorted(_survivor_keys() - set(SURVIVORS))
    assert not missing, f"Tier 0 survivors with no recorded disposition: {missing}"


def test_every_disposition_names_a_threshold_that_still_exists():
    """The other direction. A renamed or deleted constant must not leave a declaration behind that reads
    as a live decision about a threshold nobody has.

    Read from the TREE, not from `threshold_test_map.json`. The map is a snapshot: checking the ledger
    against it would pass for as long as nobody rebuilt it, which is the decay this ledger exists to stop.
    The harness's `thresholds()` is the one authority for what a declared threshold is, so it is imported
    rather than re-implemented here -- a second definition of one rule is what conformance family 9 fails."""
    known = {f"{t['module']}::{t['name']}" for t in _harness().thresholds(names_only=True)}
    assert len(known) >= 60, f"only {len(known)} thresholds found; the AST rule or the tree moved"
    stale = sorted(set(SURVIVORS) - known)
    assert not stale, f"dispositions naming thresholds the tree no longer declares: {stale}"


def test_every_disposition_is_one_of_the_declared_kinds_and_delivers_what_it_claims():
    """A disposition that claims a test must name one that exists, and a declaration must carry a reason
    long enough to be one. Without this the ledger could be satisfied by the word 'declared'."""
    own = _own_test_names()
    for key, (verdict, kind, detail) in sorted(SURVIVORS.items()):
        assert verdict in _VERDICTS, f"{key}: unknown verdict {verdict!r}"
        assert kind in _KINDS, f"{key}: unknown kind {kind!r}"
        if kind == "boundary":
            assert detail in own, f"{key}: names {detail!r}, which is not a test in this module"
        elif kind == "delegated":
            assert "::" in detail or detail.startswith("test_"), f"{key}: {detail!r} is not a test id"
        else:
            assert len(detail) >= 60, f"{key}: a declaration needs a reason, got {detail!r}"
    # Every boundary case in this file must be claimed by an entry, or it is an orphan nobody tracks.
    # Every test in this file is either a boundary case the ledger claims or one of the declared meta
    # tests. A name-prefix heuristic was tried first and flagged the meta tests themselves, so the set is
    # declared: a new test that is neither fails here rather than drifting in unclaimed.
    claimed = {d for _v, k, d in SURVIVORS.values() if k == "boundary"}
    assert claimed <= own, f"ledger claims tests this module does not define: {sorted(claimed - own)}"
    unclaimed = sorted(own - claimed - META_TESTS)
    assert not unclaimed, f"tests that are neither a claimed boundary case nor a declared meta test: {unclaimed}"


@pytest.mark.skipif(not TIER0.is_file(), reason="Tier 0 results absent; run `mutate_thresholds.py run`")
def test_the_thresholds_this_module_claims_to_pin_are_no_longer_survivors():
    """The ratchet, and the one assertion here that cannot be satisfied by bookkeeping. A threshold the
    ledger says is pinned by a boundary case must come back KILLED in the recorded run. Delete a case,
    weaken it to a tautology, or let the constant drift out of the decision it names, and the next tier run
    puts that threshold back in the survivor set and this fails -- which is the difference between a
    finding that stays closed and a finding that was closed once."""
    claimed = {k for k, (_v, kind, _d) in SURVIVORS.items() if kind == "boundary"}
    still_surviving = sorted(claimed & _survivor_keys())
    assert not still_surviving, (
        f"these are claimed as pinned by a boundary case yet still SURVIVED the recorded run: "
        f"{still_surviving}. Either the case does not bite or the run predates it.")


@pytest.mark.skipif(not (TIER0.is_file() and MAP.is_file()), reason="mutation artefacts absent")
def test_every_test_that_named_a_surviving_threshold_has_been_read_for_self_reference():
    """The join is the detector, and it is measured: a test whose own source names a threshold, in the
    covering set of a mutant that SURVIVED, either asserts the constant against itself or has a reason not
    to care. Four of the five on 2026-11-02 were the former. A new member arriving with no verdict fails
    here rather than sitting in the suite looking like coverage."""
    rows = json.loads(MAP.read_text(encoding="utf-8"))
    joined = {t for key in _survivor_keys() for t in (rows.get(key, {}).get("tests_naming") or [])}
    unreviewed = sorted(joined - set(SELF_REFERENTIAL_REVIEW))
    assert not unreviewed, f"tests naming a surviving threshold, not yet read: {unreviewed}"
    for tid, (verdict, reason) in sorted(SELF_REFERENTIAL_REVIEW.items()):
        assert verdict in _REVIEW_VERDICTS, f"{tid}: unknown verdict {verdict!r}"
        assert len(reason) >= 80, f"{tid}: a review needs a reason, got {reason!r}"
        mod, _sep, name = tid.partition("::")
        src = (REPO / mod).read_text(encoding="utf-8")
        assert f"def {name}(" in src, f"{tid}: no such test any more"


# A test that NAMES a threshold enters the covering set as a second, independent source alongside
# coverage, and the rule for what counts as naming it broke three times in one sitting -- each repair
# losing something the previous version needed. So every requirement is an executable case here. The
# stakes are not cosmetic: a threshold credited with a covering test it does not have leaves
# `no_covering_tests`, the one verdict this tier insists is NEVER a pass, and arrives in `SURVIVED`,
# which reads as measured and fine.
_PLANTED = '''
LEDGER = {"zz.py::ZZZ_LABEL_ONLY": ("declared", "a ledger KEY is a label, not a reference")}
CLAIMS = {"driven": lambda: m.ZZZ_MODULE_LAMBDA == 1}
ZZZ_CAPS = {"a": 1}

def test_prose_only():
    """Mentions ZZZ_PROSE_ONLY in prose and nothing else."""
    assert True

def test_drives_the_module_lambda():
    assert all(f() for f in CLAIMS.values())

def test_dotted_string_in_body():
    assert "support.ZZZ_DOTTED" in inspect.getsource(f)

def test_setattr_by_string():
    monkeypatch.setattr(m, "ZZZ_AS_STRING", 1)

def test_plural_is_not_singular():
    assert m.ZZZ_CAPS["a"] == 1
'''

# name -> the planted tests that must be credited with it ("*" = every test in the file), and why.
_PLANT_EXPECTS = {
    "ZZZ_PROSE_ONLY": (set(), "a docstring mention asserts nothing about a value"),
    "ZZZ_LABEL_ONLY": (set(), "a module-level ledger KEY is a label, not an executable reference"),
    "ZZZ_MODULE_LAMBDA": ({"*"}, "a module-level lambda is code every test in the file may drive"),
    "ZZZ_DOTTED": ({"test_dotted_string_in_body"}, "a dotted string asserted against real source IS a reference"),
    "ZZZ_AS_STRING": ({"test_setattr_by_string"}, "setattr/getattr name a constant as a string"),
    "ZZZ_CAP": (set(), "the singular of a plural in use -- substring matching conflated these two"),
}


def test_the_harness_credits_a_threshold_to_code_that_references_it_and_not_to_prose_about_it():
    """Both directions of `_tests_naming`, on plants and on the live tree.

    The live half is the case that produced the rule: a boundary case in this very file records in its
    docstring that one of `audit.py`'s constants is referenced nowhere in the tree, and under a substring
    rule that mention made the dead constant look covered.

    THE DEAD CONSTANTS ARE FOUND, NOT NAMED. The first version of this test wrote the name as a string
    literal -- and a string literal in a test body IS a reference under this rule, so the test created
    the very join it asserts is absent and failed on itself. Asking the tree which constants it never
    references is both honest and stronger: it covers the next one too."""
    import ast
    mt = _harness()

    tree = ast.parse(_PLANTED)
    tests = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
             and n.name.startswith("test_")]
    assert len(tests) == 5, "the plant lost a case"
    shared = mt._referenced_names(
        ast.Module(body=[s for s in tree.body if s not in tests], type_ignores=[]), strings=False)
    for name, (want, why) in _PLANT_EXPECTS.items():
        got = {fn.name for fn in tests if name in shared or name in mt._referenced_names(fn)}
        expect = {fn.name for fn in tests} if want == {"*"} else want
        assert got == expect, f"{name}: credited {sorted(got)}, expected {sorted(expect)} -- {why}"

    # And on the live tree. A threshold the tree references NOWHERE -- not in its own module, not from
    # another -- must not pick up a covering test from prose about it, because that moves it out of
    # `no_covering_tests`, which is never a pass, and into `SURVIVED`, which reads as measured and fine.
    dead = [t for t in mt.thresholds(names_only=True)
            if not t["ref_lines"] and not mt._cross_module_refs(t["name"], t["module"])]
    assert dead, "the tree declares no unreferenced threshold; this half has nothing to measure"
    for t in dead:
        assert mt._tests_naming(t["name"]) == [], (
            f"{t['module']}::{t['name']} is referenced nowhere in src yet has a name-sourced covering "
            f"test: {mt._tests_naming(t['name'])}")


@pytest.mark.skipif(not TIER0.is_file(), reason="Tier 0 results absent; run `mutate_thresholds.py run`")
def test_the_recorded_run_left_no_verdict_unresolved():
    """The artefact every other test here reads must be a decided one.

    Two failures made this a test rather than a reading. The FIRST run's summary line printed
    killed/SURVIVED/UNMEASURED/errors -- 115 of 128 -- and left its own 13 timeouts out of the total, so it
    reported a partition of a population it had silently shrunk; the harness now asserts the sum, and this
    asserts it again from the committed file, because a tally computed by the thing being tallied is not
    independent of it. The THIRD run left one timeout, and that row was invisible to every ledger check in
    this module: `_survivor_keys()` read only the `SURVIVED` column, so a threshold could sit in the
    artefact undecided while the completeness assertion reported nothing missing. Both of those are the
    same defect -- an unresolved verdict counted as a resolved one -- and it is the project's named
    silent-absence class landing inside the instrument built to catch it.

    FORCED, not assumed: `_unresolved` was run against planted `timeout` and `error` rows, and the
    harness's own re-run was driven by forcing a one-second budget onto a set that passes in four seconds
    (it reported `timeout`, re-ran, and recorded `killed` with `resolved_from` and `first_timeout_s`).
    """
    art = json.loads(TIER0.read_text(encoding="utf-8"))
    rows = art["results"]
    assert len(rows) == art["n_mutants"], (
        f"the artefact says {art['n_mutants']} mutants and carries {len(rows)} rows")
    tally = {v: sum(1 for r in rows if r["verdict"] == v)
             for v in ("killed", "SURVIVED", "no_covering_tests", "error", "timeout")}
    assert sum(tally.values()) == len(rows), (
        f"the five declared verdicts {tally} do not partition {len(rows)} mutants; some row carries a "
        f"verdict nothing in the pre-registration allows")
    assert _unresolved(rows) == [], (
        f"the recorded run left verdicts undecided: {_unresolved(rows)}. A timeout is a survivor the "
        f"budget hid or a mutant that hangs, and nothing downstream can tell which; re-run those mutants "
        f"at a larger budget rather than publishing the column.")
    for r in rows:
        if r.get("resolved_from") == "timeout":
            assert r.get("first_timeout_s") and r["budget_s"] > r["first_timeout_s"], (
                f"{r['module']}::{r['name']} {r['mutant']} claims a resolved timeout without recording "
                f"the budget it first exceeded: {r}")
