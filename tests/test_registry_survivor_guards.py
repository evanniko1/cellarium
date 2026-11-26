"""Guards for the registry faults the pre-registered mutation run predicted the suite would NOT catch.

The run (data/mutation/registry_plan.json, results in data/mutation/registry_results.json) wrote two predictions of
survival before anything ran, and both survived. A survivor is a statement about the suite: no test can see that
fault. Each guard below closes one, and each was made to fail by applying that mutant's exact edit before it was
accepted (the plan's `old` -> `new`, applied and restored byte for byte by scripts/mutate_registry.py).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from cellarium import capability as C  # noqa: E402

# V2. A record that silently loses its source markers becomes declaration-only: nothing in the default run checks
# it against the simulator (markers are verified only when a checkout is configured), and the existing test
# recomputes the declaration-only set, so one more member passed unnoticed. The set is now named.
DECLARATION_ONLY = {
    "growth_under_phosphate_depletion", "growth_without_a_carbon_source", "operon_specific_rrna_knockout",
    "per_gene_trna_abundance", "response_to_the_glucose_concentration",
    # G-1 (2026-11-24): what these two rest on is a fitted fold-change row in the knowledge base, not a source symbol
    # to probe; tests/test_fitted_factor_induction.py re-reads those rows wherever the checkout is present.
    "induction_by_a_fitted_transcription_factor", "arabinose_induction_of_the_ara_operon",
    # BV-G2 and BV-AN (2026-11-25): one rests on the metabolic objective's design (no single marker says "reroutes"),
    # the other on fitted fold-change rows; both cite what they rest on in capability.DEPENDS_ON (Ms-1), and their
    # numbers are re-derived by evals/bv3_essentiality.py and evals/anaerobic_response.py.
    "essentiality_of_a_metabolic_gene", "anaerobic_respiration_induction_magnitude",
    # BV-OF (2026-11-25): rests on the same objective's design as BV-G2; re-derived by evals/bv6_overflow.py.
    "overflow_and_fermentation_products",
    # BV-EL (2026-11-25): rests on the steady-state elongation model's ppGpp relation; re-derived by bv7_elongation.py.
    "elongation_rate_against_growth_rate",
    # BV-CF (2026-11-25): the same objective's design as BV-G2 and BV-OF; re-derived by evals/bv11_fluxes.py.
    "central_carbon_flux_split",
    # CRIT (2026-11-26): an ABSENT mechanism, so there is no symbol that evidences it; what the model does instead is
    # cited in capability.DEPENDS_ON, and the envelope's rule is pinned by tests/test_replication_threshold.py.
    "replication_initiation_after_a_nutrient_shift",
}


def test_the_records_with_no_source_markers_are_exactly_the_declared_ones():
    found = {c.key for c in C.CAPABILITIES if not c.markers}
    assert found == DECLARATION_ONLY, (
        f"declaration-only records changed: added {sorted(found - DECLARATION_ONLY)}, "
        f"removed {sorted(DECLARATION_ONLY - found)}. A record that loses its markers loses the only evidence "
        "tying it to the simulator's source; if that is intended, update this set and say why.")


def test_the_anthropic_dependency_keeps_its_upper_bound():
    """R1. 1.x removed `temperature` from messages.create, and council.py and agent.py pass it, so the pin's
    `<1` is load-bearing. Nothing read the pins, so loosening it passed every test."""
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'"anthropic\s*([^"]*)"', text)
    assert m, "the anthropic dependency is gone from pyproject.toml"
    spec = m.group(1).replace(" ", "")
    assert "<1" in spec.split(","), f"anthropic is pinned as {spec!r}; it needs an upper bound below 1"
