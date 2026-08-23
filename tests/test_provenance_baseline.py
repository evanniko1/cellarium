"""The Stage-3 reference is a COMMITTED file, not "whatever runs/cellarium holds today" (PARCA-4 Stage 1).

Stage 3 scores each candidate estimator against "the current fit". If that means the live knowledge base,
then two candidates evaluated a month apart are scored against different references with nothing saying so —
and `runs/cellarium/kb` IS rebuilt, which is why KB-ROOT-1 and the PARCA-3 destination gate both exist. This
is the comparability problem ARM-1 solved for runs, one level down at the parameters.

These tests deliberately split in two. The first group needs NO model image, so CI checks that the committed
baseline is well-formed and names the fit it describes. The second group needs the container and verifies the
baseline still matches the live fit — locally, where sim_data can actually be unpickled.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.cellarium import reader  # noqa: E402

# ---------------------------------------------------------------------------------------------------------
# No image needed — these run in CI.
# ---------------------------------------------------------------------------------------------------------

def test_the_baseline_is_committed_and_readable():
    b = reader.read_provenance_baseline()
    assert "error" not in b, b.get("error")
    assert b["n_mrna_units"] > 1000
    assert b["not_a_fit"]["pct_expression"] > 0


def test_the_baseline_names_the_fit_it_describes():
    """A baseline that cannot say WHICH fit it froze is the defect it exists to prevent."""
    b = reader.read_provenance_baseline()
    assert b.get("kb_sha256") and len(b["kb_sha256"]) == 64, (
        "the baseline does not carry a kb_sha256, so nothing can tell which parameter set it is the "
        "reference for: %r" % b.get("kb_sha256"))
    assert b.get("sim_path") and b.get("why")


def test_the_baseline_carries_what_scoring_needs():
    """Ids AND weights, or `provenance_delta` cannot be run against it."""
    b = reader.read_provenance_baseline()
    u = b["units_not_a_fit"]
    for cls in ("floor", "ceiling", "imputed"):
        assert isinstance(u[cls], dict), f"{cls} lost its weights"
    total = sum(len(u[c]) for c in ("floor", "ceiling", "imputed"))
    assert total == b["not_a_fit"]["n_units"]


def test_the_baseline_records_the_condition_spread():
    """Every expression figure is for ONE condition; the reference has to carry that or it reads as absolute."""
    b = reader.read_provenance_baseline()
    a = b["not_a_fit_across_conditions"]
    assert a["n_conditions"] > 1 and a["condition_used"] == "basal"
    assert a["min_pct"] <= b["not_a_fit"]["pct_expression"] <= a["max_pct"], (
        "the quoted basal figure sits outside the range across conditions, which cannot be right")


def test_the_ceiling_class_is_small_and_examined():
    """Item 6: 7 units, 0.016% of mRNA expression, two of them never transcribed in basal.

    Recorded rather than assumed — 'probably negligible' is what I said about the floor before it turned out
    to be a third of the story. NOTE the caveat: a unit at 0.00000% of BASAL expression is not irrelevant in
    every condition, since expression is condition-specific and a regulator can be switched on elsewhere.
    """
    b = reader.read_provenance_baseline()
    ceil = b["on_ceiling"]
    assert ceil["n_units"] > 0, "no unit on the fast bound — re-read the finding rather than deleting this"
    assert ceil["pct_expression"] < 1.0, (
        "the ceiling class is no longer negligible (%.3f%% of expression); it was 0.016%% when examined and "
        "that conclusion must be re-derived" % ceil["pct_expression"])
    assert ceil["n_units"] < b["imputed_average"]["n_units"]


# ---------------------------------------------------------------------------------------------------------
# Needs the image.
# ---------------------------------------------------------------------------------------------------------

def test_the_baseline_still_matches_the_live_fit():
    """Drift must be LOUD. If runs/cellarium is rebuilt, every Stage-3 comparison silently changes reference."""
    if not reader.WCECOLI_DOCKER:
        pytest.skip("needs the model image to unpickle sim_data")
    if not Path("runs/cellarium/kb/simData.cPickle").is_file():
        pytest.skip("no knowledge base at runs/cellarium")
    b = reader.read_provenance_baseline()
    live = reader.deg_rate_provenance("cellarium")
    if "error" in live:
        pytest.skip(live["error"])
    assert live["not_a_fit"]["n_units"] == b["not_a_fit"]["n_units"], (
        "the live fit no longer matches the committed baseline (%d vs %d not-a-fit units). Either the kb was "
        "rebuilt — in which case regenerate the baseline DELIBERATELY with reader.write_provenance_baseline "
        "and say which kb_sha256 it moved to — or something changed the estimator"
        % (live["not_a_fit"]["n_units"], b["not_a_fit"]["n_units"]))
    assert abs(live["not_a_fit"]["pct_expression"] - b["not_a_fit"]["pct_expression"]) < 1e-6
