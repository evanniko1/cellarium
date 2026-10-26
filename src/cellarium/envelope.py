"""Feasibility guardrail — is a proposed experiment inside the model's *validated* envelope?

"Validated" here means the model RUNS the design as intended; it does not mean every parameter of it has an
effect. A glucose dose is the standing example: uptake is a binary switch above 1e-5 mM
(external_state.py, IMPORT_CONSTRAINT_THRESHOLD), so 2, 5, 11.1 and 20 mM glucose give bit-identical
simulations. A dose design runs, and answers nothing about dose.

The sharpest failure it does NOT support is a **carbon-source switch** (glucose -> acetate/succinate/fumarate/
malate), mid-simulation or at t=0: those alternative carbon sources exist only as *static* fitted conditions
upstream, never as a dynamic shift target. Forcing one desynchronises the replication-division cycle and
returns mechanistically invalid generations. We catch that here, before running, and point to the
in-envelope alternative.
"""

from __future__ import annotations

from dataclasses import dataclass

from .capability import ELONGATION_MODES, MODE_FLAGS
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

# tf_activity variants that move the cell into a medium the condition table has no doubling time for.
# Replication looks the medium up at the first step, so the run dies with a KeyError before simulating
# anything (known-fault audit E1, runs_validation/cellarium/tf_activity_000014).
TF_ACTIVITY_NO_DOUBLING_TIME = {14: ("cytR inactive", "minimal_plus_cytidine", 13)}  # 13 = cytR active, runs


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
    # The elongation model is checked FIRST and refused loudly, because this is the only feasibility gate in
    # front of `runner.run_one` and `tools.run_experiment`. An undeclared mode reaches `_variant_args`, which
    # maps modes to runSim flags — a name it does not know either dies inside a container minutes in, or
    # emits no flag at all and runs the steady-state model under another model's name. The house rule is to
    # prefer a loud failure to a default, and this is where the loud failure belongs.
    if design.elongation_model not in ELONGATION_MODES:
        return EnvelopeVerdict(
            False,
            f"Elongation model '{design.elongation_model}' is not a declared model.",
            "Use one of: " + ", ".join(f"{m} ({MODE_FLAGS[m]})" for m in ELONGATION_MODES) + ".",
        )

    if design.perturbation not in VALIDATED_PERTURBATIONS:
        return EnvelopeVerdict(
            False,
            f"Perturbation '{design.perturbation}' is not a validated model variant.",
            "Use one of: " + ", ".join(sorted(VALIDATED_PERTURBATIONS)) + ".",
        )

    if design.perturbation == "tf_activity":
        idx = design.params.get("variant_index")
        if idx is not None and int(idx) in TF_ACTIVITY_NO_DOUBLING_TIME:
            tf_state, medium, alternative = TF_ACTIVITY_NO_DOUBLING_TIME[int(idx)]
            return EnvelopeVerdict(
                False,
                f"tf_activity variant {idx} ({tf_state}) puts the cell in {medium}, which has no doubling time "
                f"in the model's condition table. The run fails at its first step without simulating.",
                f"Use variant {alternative} (the same TF in its other state). Running this one needs a doubling "
                f"time for {medium} and a ParCa rebuild, which is a new comparability arm.",
            )

    # The load-bearing check: a timeline that switches carbon source.
    if design.timeline:
        steps = _parse_timeline(design.timeline)
        # The cell's physiology is the one it was fitted for, which is glucose unless the `condition` variant
        # selected an alternative carbon source. It goes at the head of the sequence, so that a timeline whose
        # FIRST event (at t=0) moves a glucose-fitted cell into acetate is a switch too. Measured in the large
        # campaign's release: `wildtype` + "0 minimal_acetate" divides at 2,805 s, then 800 s, and birth mass
        # falls 354 -> 202 -> 146 fg, while the fitted acetate condition divides at 4,776-6,662 s.
        start = (design.condition if design.perturbation == "condition" and design.condition in STATIC_ONLY_CARBON
                 else "glucose")
        sources = [start] + [carbon_source(m) for _, m in steps]
        switch = next((i for i in range(1, len(sources))
                       if sources[i] != sources[i - 1] and sources[i] in STATIC_ONLY_CARBON), None)
        if switch is not None:
            alt = sources[switch]
            at = steps[switch - 1][0]
            when = "at t=0, from a cell fitted to glucose" if at == 0 else "mid-simulation"
            return EnvelopeVerdict(
                False,
                f"This timeline switches the carbon source to {alt} {when}. {alt} exists only as a *static* "
                f"fitted condition; a switch into it leaves the glucose-fitted expression and division cycle in "
                f"place, so the cells do not reach a steady state (they shrink generation after generation).",
                f"Run the static '{alt}' condition (perturbation='condition', condition='{alt}') with replicate "
                f"seeds instead of a glucose->{alt} shift.",
            )

    return EnvelopeVerdict(True, "Inside the model's validated perturbation envelope.")
