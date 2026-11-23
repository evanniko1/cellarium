"""Why the gate gets 24 of 216 items wrong under EVERY wording: each wrong verdict traced to a registered defect.

FOUND 2026-11-23, from the complete error count (tests/test_gate_error_accounting.py). Three capability-by-mode
cells are wrong under all eight framings, and 24 of the stored 8-framing run's 27 wrong verdicts sit in them.
Read record by record, every one of the 27 is explained by one of two defects that BACKLOG already holds, open
since 2026-10-15:

  GATE-8b-C (25)  a DEPENDENCY-driven refusal. The parser reads a condition into the question that the answer
                  key does not name -- "starvation" in the two kinetic tRNA-charging questions, an amino-acid
                  "supply" in a nutrient shift -- and that dependency pulls in a capability the mode lacks
                  (`ppgpp_stringent_response`, `amino_acid_uptake_from_the_medium`). The key was generated from
                  the question's ONE named capability. BACKLOG calls this "mostly a KEY problem": the written
                  rule exists (`gate.IMPLIED_DEPENDENCIES`) and is deliberately NOT wired, because the four
                  GATE-8b fixes were designed with held-out set v1 in view and must wait for a frozen v2.
  GATE-8b-D (2)   `decide()` returns `propose` only when the MODE holds no runs, so a representable question
                  whose PERTURBATION no run carries is answered. `nutrient_shift_timelines` in kinetic mode is
                  keyed `propose` (kinetic runs exist; none carries a shift), and the gate cannot return
                  `propose` for it under any parse: it refuses when a dependency is read in (6, cause C) and
                  answers when none is (2, cause D). Wrong by construction until D is fixed.

What this pins is the DIAGNOSIS, so a future run cannot add a wrong verdict of a new kind without someone
reading it: an unexplained error fails here. It does not decide whether the C keys or the gate should change;
that decision belongs to the GATE-8b-HO2 sequence (freeze held-out v2 with a second labeller, then wire A, D, B,
C, then run v2 once), and re-keying the 216 now would fit the benchmark to the gate.
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from cellarium import gate  # noqa: E402

RUN = REPO / "evals" / "results" / "gate_eval_8framings.json"


def _cause(r: dict) -> str | None:
    """The registered defect a wrong verdict is explained by, from the record alone, or "unexplained"."""
    want, got = r["required"], r["got"]
    if want == got:
        return None
    if got == "refuse" and r["blocking"]:
        pulled_in = {k for d in r["dependencies"] for k in gate.DEPENDENCY_REQUIRES.get(d, ())}
        if set(r["blocking"]) <= pulled_in:
            return "GATE-8b-C"                    # refused ONLY on capabilities a parsed dependency pulled in
    if (want, got) == ("propose", "answer") and r["kind"] == "no_corpus_data":
        return "GATE-8b-D"                        # the mode has runs; none carries the perturbation
    return "unexplained"


@pytest.fixture(scope="module")
def recs() -> list[dict]:
    return json.loads(RUN.read_text(encoding="utf-8"))["records"]


def test_every_wrong_verdict_in_the_8_framing_run_has_a_registered_cause(recs):
    causes = collections.Counter(c for r in recs if (c := _cause(r)))
    assert causes == {"GATE-8b-C": 25, "GATE-8b-D": 2}            # literals; no "unexplained"
    by_cell = collections.Counter((r["id"].rsplit("__", 1)[0], _cause(r)) for r in recs if _cause(r))
    assert by_cell == {
        ("per_isoacceptor_trna_charging__kinetic", "GATE-8b-C"): 8,
        ("per_amino_acid_trna_charging__kinetic", "GATE-8b-C"): 8,
        ("nutrient_shift_timelines__kinetic", "GATE-8b-C"): 6,
        ("nutrient_shift_timelines__kinetic", "GATE-8b-D"): 2,
        ("nutrient_shift_timelines__coarse_kinetic", "GATE-8b-C"): 2,
        ("codon_level_elongation__kinetic", "GATE-8b-C"): 1,
    }
    # every C refusal is on one of the two capabilities the parsed condition pulled in, never on the
    # question's own observable
    blocked = {k for r in recs if _cause(r) == "GATE-8b-C" for k in r["blocking"]}
    assert blocked == {"ppgpp_stringent_response", "amino_acid_uptake_from_the_medium"}


def test_a_wrong_verdict_of_a_new_kind_is_reported_unexplained():
    """The forced failure: a refusal on the question's OWN capability is not a dependency refusal, and an
    answer to a `propose` item in a mode with no data gap is not D. Neither may be absorbed into a known cause."""
    own = {"required": "answer", "got": "refuse", "blocking": ["per_isoacceptor_trna_charging"],
           "dependencies": ["amino_acid_starvation"], "kind": "supported"}
    assert _cause(own) == "unexplained"
    not_d = {"required": "propose", "got": "answer", "blocking": [], "dependencies": [], "kind": "no_corpus_mode"}
    assert _cause(not_d) == "unexplained"


@pytest.mark.xfail(strict=True, reason=(
    "GATE-8b-D, open since 2026-10-15: decide() proposes only when the MODE holds no runs, so a representable "
    "question whose perturbation no run carries is answered. The fix (a per-capability coverage check in the "
    "package) is ordered after held-out set v2 is frozen (GATE-8b-HO2). When it lands this passes, and strict "
    "xfail turns that into a failure so the marker cannot outlive the defect."))
def test_gate_8b_d_a_representable_question_with_no_run_behind_it_is_proposed(monkeypatch):
    # The corpus holds kinetic runs (as the stored run's did) and none of them carries a nutrient shift.
    monkeypatch.setattr(gate, "modes_with_runs", lambda: ("steady_state", "kinetic"))
    req = gate.Requirement(observable="media_response", granularity="aggregate",
                           regulatory_dependencies=("nutrient_shift",), parser="manual")
    assert gate.decide(req, mode="kinetic").verdict == "propose"
