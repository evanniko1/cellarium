"""Feasibility guardrail — is a proposed experiment inside the model's *validated* envelope?

The whole-cell E. coli model validates a specific set of perturbations. The sharpest failure it does NOT
support is a mid-simulation **carbon-source switch** (glucose -> acetate/succinate/fumarate/malate): those
alternative carbon sources exist only as *static* fitted conditions upstream, never as a dynamic shift
target. Forcing one desynchronises the replication-division cycle and returns mechanistically invalid
generations. We catch that here, before running, and point to the in-envelope alternative.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import Design

# Variant types the model supports (models/ecoli/sim/variants/).
VALIDATED_PERTURBATIONS = {
    "wildtype", "gene_knockout", "multi_gene_knockout", "condition", "tf_activity",
    "ppgpp_conc", "timeline", "amino_acid_shift", "rrna_operon_knockout", "new_gene",
    # Cellarium's own variant (model_patches/variants/, installed by scripts/apply_model_variants.py). It
    # suppresses a gene across ALL of its transcription units and at a chosen strength, which `gene_knockout`
    # cannot do: that variant zeroes ONE unit, so a multi-TU gene keeps being expressed from the others
    # (murA 1789 copies -> 0 once both of its units are suppressed).
    "graded_gene_knockout",
}

# Alternative carbon sources the model validates ONLY as static conditions.
STATIC_ONLY_CARBON = {"acetate", "succinate", "fumarate", "malate"}


@dataclass
class EnvelopeVerdict:
    in_envelope: bool
    reason: str
    suggestion: str | None = None


def carbon_source(media: str) -> str:
    """Classify a media id by its primary carbon source."""
    m = (media or "").lower()
    for alt in STATIC_ONLY_CARBON:
        # A `minus_<X>` medium REMOVES X — it is not fed by it. Plain substring matching read
        # `minimal_minus_malate` as malate-fed and would have refused a glucose-medium shift as an
        # out-of-envelope carbon switch, or worse, mis-attributed a run's carbon source in provenance.
        # Latent until the SCI-TRNA-3 dropout media established `minus_<molecule>` as a naming pattern.
        if alt in m.replace(f"minus_{alt}", ""):
            return alt
    return "glucose"  # minimal / minimal_glc_* / minimal_plus_* are all glucose-based


def _parse_timeline(events: str) -> list[tuple[float, str]]:
    """'0 minimal, 1200 minimal_acetate' -> [(0, 'minimal'), (1200, 'minimal_acetate')]."""
    out: list[tuple[float, str]] = []
    for part in (events or "").split(","):
        toks = part.strip().split(None, 1)
        if len(toks) == 2:
            try:
                out.append((float(toks[0]), toks[1].strip()))
            except ValueError:
                continue
    return out


def check(design: Design) -> EnvelopeVerdict:
    """Return whether the design is inside the model's validated envelope."""
    if design.perturbation not in VALIDATED_PERTURBATIONS:
        return EnvelopeVerdict(
            False,
            f"Perturbation '{design.perturbation}' is not a validated model variant.",
            "Use one of: " + ", ".join(sorted(VALIDATED_PERTURBATIONS)) + ".",
        )

    # The load-bearing check: a timeline that switches carbon source.
    if design.timeline:
        steps = _parse_timeline(design.timeline)
        sources = [carbon_source(m) for _, m in steps]
        switched_to_alt = any(
            sources[i] != sources[i - 1] and sources[i] in STATIC_ONLY_CARBON
            for i in range(1, len(sources))
        )
        if switched_to_alt:
            alt = next(s for s in sources if s in STATIC_ONLY_CARBON)
            return EnvelopeVerdict(
                False,
                f"This timeline switches the carbon source to {alt} mid-simulation. The model validates "
                f"glucose cut/ramp and amino-acid/ion/oxygen shifts, but {alt} exists only as a *static* "
                f"condition — a dynamic carbon-source switch desynchronises the replication-division cycle "
                f"and yields degenerate generations.",
                f"Run the static '{alt}' condition (fitted growth) with replicate seeds instead of a "
                f"glucose->{alt} shift.",
            )

    return EnvelopeVerdict(True, "Inside the model's validated perturbation envelope.")
