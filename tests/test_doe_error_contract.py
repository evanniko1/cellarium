"""Every design-of-experiments refusal is the CALLER's fault, and must classify as one.

A design-of-experiments fault is arithmetic about a layout: too few runs for the factors, a run count that is
not a power of two, a continuous range of zero width, a fitted-parameter lever crossed as an ordinary factor.
None of it is a statement about the corpus and none of it is a statement about this machine. So every message
`doe.py` can emit must resolve to a reason whose `about` is `request`.

Two of these messages did not, and neither failed loudly. `"8 factors need at least 9 runs"` matched the
`need at least` pattern written for thin data and came back `insufficient_data` / `about: corpus`, and
`"stratification needs at least 2 bins"` did the same. `about: corpus` is the one value `errors.py` calls
evidence, so a design-arithmetic mistake was being handed to an agent as a fact about what the model contains
— the silent-absence shape, arriving through the module built to prevent it. The remaining twelve were
`unclassified`, which at least fails the conformance sweep.

This test is the instrument for that whole class: it enumerates the real refusals by CALLING the functions
rather than by reading string literals, so a message that changes wording is re-checked rather than missed.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cellarium import doe, errors  # noqa: E402

# Every refusal `doe.py` can produce, produced by calling it. A literal-scanning version of this test would
# miss `panel`'s two, which are assigned into the result dict rather than returned from a `return {...}`.
REFUSALS = [
    ("fractional_factorial: a factor that is not two-level",
     lambda: doe.fractional_factorial({"g": ["a", "b", "c"]}, runs=4)),
    ("fractional_factorial: runs not a power of two",
     lambda: doe.fractional_factorial({n: [0, 1] for n in "ABCD"}, runs=12)),
    ("fractional_factorial: fewer runs than factors+1",
     lambda: doe.fractional_factorial({n: [0, 1] for n in "ABCDEFGH"}, runs=8)),
    ("fractional_factorial: runs exceed the full factorial",
     lambda: doe.fractional_factorial({n: [0, 1] for n in "AB"}, runs=16)),
    ("fractional_factorial: no factors",
     lambda: doe.fractional_factorial({}, runs=8)),
    ("plackett_burman: no tabulated row at that size",
     lambda: doe.plackett_burman({f"f{i}": [0, 1] for i in range(40)})),
    ("plackett_burman: a factor that is not two-level",
     lambda: doe.plackett_burman({"g": ["a", "b", "c"]})),
    ("latin_hypercube: no ranges",
     lambda: doe.latin_hypercube({}, n=4)),
    ("latin_hypercube: fewer than two strata",
     lambda: doe.latin_hypercube({"x": (0.0, 1.0)}, n=1)),
    ("latin_hypercube: a zero-width range",
     lambda: doe.latin_hypercube({"x": (1.0, 1.0)}, n=4)),
    ("central_composite: no ranges",
     lambda: doe.central_composite({})),
    ("central_composite: a zero-width range",
     lambda: doe.central_composite({"x": (1.0, 1.0)})),
    ("central_composite: an unknown alpha keyword",
     lambda: doe.central_composite({"x": (0.0, 1.0)}, alpha="nonsense")),
    ("central_composite: a non-positive alpha",
     lambda: doe.central_composite({"x": (0.0, 1.0)}, alpha=-1.0)),
    ("central_composite: no centre point",
     lambda: doe.central_composite({"x": (0.0, 1.0)}, center=0)),
    ("central_composite: a cube fraction that cannot be built",
     lambda: doe.central_composite({"x": (0.0, 1.0), "y": (0.0, 1.0)}, cube_runs=12)),
    ("whole_plot_order: no cells",
     lambda: doe.whole_plot_order([], "arm")),
    ("whole_plot_order: a factor the cells do not carry",
     lambda: doe.whole_plot_order([{"gene": "a"}], "arm")),
    ("panel: an unknown layout name",
     lambda: doe.panel({"g": ["a", "b"]}, design="latin_hypercube")),
    ("panel: a fitted-parameter lever crossed as a factor",
     lambda: doe.panel({"operons": ["on", "off"], "g": ["a", "b"]})),
    ("panel: every cell rejected by the legality predicate",
     lambda: doe.panel({"g": ["a"]}, legal=lambda cell: (False, "out of envelope"))),
    ("panel: factors that cross to zero cells",
     lambda: doe.panel({"g": []})),
    ("surface_panel: an unknown layout name",
     lambda: doe.surface_panel({"a": (0.0, 1.0)}, design="fractional")),
    ("surface_panel: no ranges",
     lambda: doe.surface_panel({})),
]


@pytest.mark.parametrize("label,call", REFUSALS, ids=[r[0] for r in REFUSALS])
def test_every_doe_refusal_is_about_the_request(label, call):
    out = call()
    msg = out.get("error")
    assert msg, f"{label}: expected a refusal, got {sorted(out)[:6]}"
    reason = errors.classify(msg)
    assert reason != "unclassified", f"{label}: errors.PATTERNS cannot name {msg!r}"
    about = errors.REASONS[reason][0]
    assert about == "request", (
        f"{label}: classified {reason!r} -> about={about!r}. A layout fault is the caller's; "
        f"about='corpus' would be read as evidence about the model and about='environment' as a broken "
        f"machine. Message: {msg!r}")


def test_the_two_arithmetic_refusals_are_not_read_as_thin_data():
    """The narrow patterns must beat the broad `need at least` one, in both directions of the regression."""
    too_few = doe.fractional_factorial({n: [0, 1] for n in "ABCDEFGH"}, runs=8)["error"]
    one_bin = doe.latin_hypercube({"x": (0.0, 1.0)}, n=1)["error"]
    for msg in (too_few, one_bin):
        assert errors.classify(msg) != "insufficient_data", msg
        assert "at least" in msg, "the phrasing that collided is still present, so the guard still applies"


def test_a_doe_layout_name_is_not_a_corpus_design():
    """`design` means two things in this package and conflating them points an agent at the wrong fault.

    A bad LAYOUT name must not come back as `unknown_design`, which in this taxonomy means the corpus holds
    no such `perturbation/condition` label."""
    for msg in (doe.panel({"g": ["a", "b"]}, design="latin_hypercube")["error"],
                doe.surface_panel({"a": (0.0, 1.0)}, design="fractional")["error"]):
        assert errors.classify(msg) == "bad_argument", msg


def test_the_missing_runs_refusal_is_a_missing_argument_not_a_bad_one():
    """`design='fractional'` without `runs` is a field the contract requires and the caller omitted.

    The reason code is what tells an agent to SUPPLY a value rather than to change one it already sent."""
    from cellarium import tools
    msg = tools.design_panel(factors={n: ["lo", "hi"] for n in "ABCD"}, design="fractional")["error"]
    assert errors.classify(msg) == "missing_argument", msg
