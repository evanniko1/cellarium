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

That failure is one face of a general one (CRIT, 2026-11-26): the model reads its replication threshold from the
CURRENT medium's doubling time at every step, so ANY shift between media with different doubling times moves the
threshold at once — oxygen or glucose removal, nitrate under anaerobiosis, an upshift. `threshold_step` refuses them
all unless the cell starts fitted to the medium it runs in.
"""

from __future__ import annotations

import csv
import functools
import io
from dataclasses import dataclass
from pathlib import Path

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

# W4C-10, open since 2026-10-25, closed here. The gate above catches ONE route into a medium with no doubling
# time — the tf_activity variant. A TIMELINE naming the same medium was unguarded, and a timeline's media names
# go to the simulator verbatim (`runSim --timeline`). `chromosome_replication` looks the medium up in
# `nutrient_to_doubling_time` at the first step of the shift, so an unknown name raises KeyError INSIDE the
# container, where `runner._FAILURE_MARKERS` catches it only after the run has burned its minutes — and the
# run root still exists on disk with a simOut that stops at the shift. A truncated-but-present run is this
# project's worst failure mode: it looks like data.
#
# The Council has already produced the input that triggers it: `minimal_minus_one_aa` and `rich_EZ_aa`, both
# invented, both passed `check` (BACKLOG W4C-10).
#
# `nutrient_to_doubling_time` is keyed by the `nutrients` column of `condition_defs.tsv`
# (simulation_data.py:266-274), so the safe set is that column — NOT every row of `media_recipes.tsv`. Two
# recipes have no condition row and therefore no doubling time, `minimal_plus_cytidine` and `minimal_plus_sam`,
# which is the same hole the tf_activity gate above patches by hand for one variant index.
_MEDIA_TABLES = Path(__file__).resolve().parents[2] / "model_overlay" / "files" / "reconstruction" / "ecoli" \
    / "flat" / "condition"


def _tsv(path: Path, column: str) -> set[str] | None:
    """One column of a flat TSV, or None if it cannot be read.

    None means "not checkable", and the caller must not refuse on it. An envelope that refuses every design
    because a table moved would be the absence failure with the gate as the silent party — and this gate stands
    in front of every launch.
    """
    try:
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if not ln.lstrip().startswith("#")]
        rows = csv.DictReader(io.StringIO("\n".join(lines)), delimiter="\t")
        return {(r.get(column) or "").strip().strip('"') for r in rows} - {""}
    except Exception:                                                     # noqa: BLE001
        return None


@functools.lru_cache(maxsize=1)
def media_with_a_doubling_time() -> set[str] | None:
    """The media names a timeline may use: the `nutrients` column of `condition_defs.tsv`."""
    return _tsv(_MEDIA_TABLES / "condition_defs.tsv", "nutrients")


@functools.lru_cache(maxsize=1)
def known_conditions() -> set[str] | None:
    """The model's fitted conditions, which an `initial_condition` may name: the `condition` column of
    `condition_defs.tsv`. ParCa builds a cell specification for every row (BV-12)."""
    return _tsv(_MEDIA_TABLES / "condition_defs.tsv", "condition")


@functools.lru_cache(maxsize=1)
def media_recipes() -> set[str] | None:
    """Every composed medium the model can MAKE — a superset of the ones it can time the cell cycle in."""
    return _tsv(_MEDIA_TABLES / "media_recipes.tsv", "media id")


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


# ---- CRIT (2026-11-26): a shift may not move the replication threshold ----------------------------------------------
# `chromosome_replication.py` reads the critical initiation mass twice: at startup from the doubling time the cell was
# FITTED for (`condition_to_doubling_time[sim_data.condition]`), then at EVERY step from the doubling time of the
# CURRENT medium (`nutrient_to_doubling_time[current_media_id]`), which replaces the startup value before it is used.
# So a timeline that moves the cell into a medium with another doubling time moves the threshold at once, while the
# cell's mass and machinery are still the old medium's. After a downshift the cell suddenly sits above the new
# threshold, initiates and divides early: in well4cell rc2, glucose-fitted cells moved into acetate mid-run divide at a
# median 2,251 s (17% within 10 minutes) against 4,343 s for cells fitted to acetate, and moved into no oxygen at
# 2,238 s against 4,627 s. The organism does the opposite: a downshift pauses initiation through ppGpp. The carbon rule
# in `check` is this defect seen from one side (its cells that "shrink generation after generation" are the early
# divisions); this is the general form, so it also covers oxygen and glucose removal, nitrate under anaerobiosis, and
# upshifts, where the threshold jumps the other way and the cell must grow to it first.
#
# Measured in all five knowledge bases on disk (get_dna_critical_mass, 2026-11-26: cellarium 3b2f8ebd, refit1 e491a580,
# refit2 4965d619, BV-14 9055ee3b, kinetic port 5f19d040): 975 fg at 25 and 44 min (the cap), 734.6 fg at 82, 590.0 at
# 100 and 423.4 at 136. The threshold never rises with the doubling time and is flat at
# the cap, so two doubling times give one threshold exactly when they are equal or both at most 44 min. A future medium
# between 44 and 82 min counts as off the cap, which can only refuse a design that was fine, never admit a jump.
CAP_DOUBLING_TIME_MIN = 44.0
THRESHOLD_FG = {25.0: 975.0, 44.0: 975.0, 82.0: 734.6, 100.0: 590.0, 136.0: 423.4}

# The envelope reads ONE condition table, the overlay, but a run reads the knowledge base of its arm, and the arms do
# not all agree. Measured 2026-11-26 across the five on disk: the three fitted before Arm B's phosphate calibration
# (cellarium kb 3b2f8ebd, refit1 e491a580, refit2 4965d619) time phosphate starvation at 44 min; the overlay, the BV-14
# fit (9055ee3b) and the kinetic port's fit (5f19d040) at 100. Every medium a fit has agrees otherwise. The envelope cannot know which arm a design will run on, so a
# shift must leave the threshold where it was in EVERY view. A view overrides a condition ROW, so the condition and its
# medium move together, as they do in a knowledge base.
DOUBLING_TIME_VIEWS: dict[str, dict[str, float]] = {
    "the overlay condition table": {},
    "the fits made before the phosphate calibration (cellarium, refit1, refit2)": {"minus_phosphate": 44.0},
}


@functools.lru_cache(maxsize=1)
def condition_rows() -> tuple[tuple[str, str, float, bool], ...] | None:
    """(condition, medium, doubling time in min, has genotype perturbations) for each row of the overlay's
    `condition_defs.tsv`, or None when it cannot be read — not checkable, so never a refusal."""
    try:
        text = (_MEDIA_TABLES / "condition_defs.tsv").read_text(encoding="utf-8")
        lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
        out = []
        for r in csv.DictReader(io.StringIO("\n".join(lines)), delimiter="\t"):
            cond, medium = (r.get("condition") or "").strip(), (r.get("nutrients") or "").strip()
            perturbed = (r.get("genotype perturbations") or "").strip() not in ("", "{}")
            if cond and medium:
                out.append((cond, medium, float(r["doubling time (units.min)"]), perturbed))
        return tuple(out) or None
    except Exception:                                                     # noqa: BLE001
        return None


def _doubling_times(view: dict[str, float]) -> tuple[dict[str, float], dict[str, float]] | None:
    """(condition -> doubling time, medium -> doubling time) as the model builds them, under one view.

    The medium table takes only rows without genotype perturbations, as `simulation_data.py` does (it raises if two
    such rows give one medium different doubling times, so the first is as good as any)."""
    rows = condition_rows()
    if rows is None:
        return None
    by_condition: dict[str, float] = {}
    by_medium: dict[str, float] = {}
    for cond, medium, tau, perturbed in rows:
        tau = view.get(cond, tau)
        by_condition[cond] = tau
        if not perturbed:
            by_medium.setdefault(medium, tau)
    return by_condition, by_medium


def same_threshold(a: float, b: float) -> bool:
    """Whether two doubling times give one critical initiation mass (see CAP_DOUBLING_TIME_MIN)."""
    return a == b or (a <= CAP_DOUBLING_TIME_MIN and b <= CAP_DOUBLING_TIME_MIN)


def fitted_condition(design: Design) -> str | None:
    """The condition the cell is FITTED for, which the startup threshold is read from.

    `--initial-condition` is applied after the variant (the simulation firetask sets `sim_data.condition` from it), so it
    wins; then the `condition` variant's own condition; otherwise basal. None for a tf_activity variant: its condition is
    a TF condition, and which one depends on the knowledge base's sorted TF list, which the envelope cannot read."""
    ic = (design.params or {}).get("initial_condition")
    if ic:
        return str(ic)
    if design.perturbation == "condition" and design.condition:
        return design.condition
    if design.perturbation == "tf_activity":
        return None
    return "basal"


@dataclass
class ThresholdStep:
    """The first timeline event that moves the replication threshold."""
    view: str
    at: float           # seconds
    medium: str
    before: str         # the condition or medium the threshold was read from before the event
    tau_before: float
    tau_after: float


def threshold_step(design: Design) -> ThresholdStep | None:
    """The first timeline event that moves the replication threshold in any view, or None.

    None also when there is no timeline, when the fitted condition is unknown (refused separately, or by the variant),
    and when the condition table cannot be read (not checkable)."""
    steps = _parse_timeline(design.timeline or "")
    start = fitted_condition(design)
    if not steps or start is None:
        return None
    for name, view in DOUBLING_TIME_VIEWS.items():
        tables = _doubling_times(view)
        if tables is None:
            return None
        by_condition, by_medium = tables
        before, tau = start, by_condition.get(start)
        if tau is None:
            continue
        for at, medium in steps:
            new = by_medium.get(medium)
            if new is None:
                break            # a medium with no doubling time is refused by the media check in `check`
            if not same_threshold(tau, new):
                return ThresholdStep(name, at, medium, before, tau, new)
            before, tau = medium, new
    return None


def threshold_moves_in_tag(family: str, tag: str) -> bool:
    """Whether a design named by its label tag shifts the medium across a threshold step. For the read-side gate.

    Only a tag that CARRIES its timeline can be checked: a pure shift is labelled by its events
    (`timeline/0 minimal, 1200 minimal_minus_oxygen`, with `#ic:<condition>` when it starts fitted). A knockout's
    `#tl:` is a 6-hex hash of its timeline, which cannot be read back, so such a tag returns False. The corpus holds no
    knockout that crosses a step (2026-11-26), and the envelope refuses launching one."""
    head, *rest = (tag or "").split("#")
    if not _parse_timeline(head):
        return False
    fields = dict(p.split(":", 1) for p in rest if ":" in p)
    params = {"initial_condition": fields["ic"]} if fields.get("ic") else {}
    return threshold_step(Design(perturbation=family, timeline=head, params=params)) is not None


def _fitted_for(medium: str) -> str | None:
    """The condition whose cell is fitted to `medium` — what a design should start in to run there."""
    return next((c for c, m, _, perturbed in condition_rows() or () if m == medium and not perturbed), None)


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

    # An initial condition selects the fitted physiology the cell starts in (runSim --initial-condition; the
    # timeline still sets the medium). It must be one of the model's fitted conditions, or the firetask raises
    # inside the container before simulating.
    ic = (design.params or {}).get("initial_condition")
    if ic:
        conds = known_conditions()
        if conds is not None and ic not in conds:
            return EnvelopeVerdict(
                False,
                f"'{ic}' is not an initial condition this model has: an initial condition must be a fitted row of "
                f"condition_defs.tsv, which ParCa built a cell specification for.",
                "Use one of: " + ", ".join(sorted(conds)) + ".",
            )

    # The load-bearing check: a timeline that switches carbon source.
    if design.timeline:
        steps = _parse_timeline(design.timeline)

        # Does every medium it names exist, and can the model time a cell cycle in it? Checked BEFORE the
        # carbon-source rule, because `carbon_source()` classifies an unknown name by substring and would
        # happily call an invented medium glucose-fed and wave it through.
        known = media_with_a_doubling_time()
        if known is not None:
            recipes = media_recipes() or set()
            for _, medium in steps:
                if medium in known:
                    continue
                if medium in recipes:
                    return EnvelopeVerdict(
                        False,
                        f"'{medium}' is a medium the model can make, but no condition row gives it a doubling "
                        f"time. Replication reads the doubling time of the current medium at the first step of "
                        f"the shift, so the run raises KeyError inside the container and leaves a simOut that "
                        f"stops there.",
                        "Use a medium that has a fitted condition, or add a condition row for this one and "
                        "rebuild ParCa — which is a new comparability arm.",
                    )
                return EnvelopeVerdict(
                    False,
                    f"'{medium}' is not a medium this model has. Media names in a timeline go to the simulator "
                    f"verbatim and are looked up by name, so an invented one is not a weaker experiment — it is "
                    f"a run that dies at the shift and still leaves a run directory behind.",
                    "Media the model can time a cell cycle in: " + ", ".join(sorted(known)) + ".",
                )
        # The cell's physiology is the one it was fitted for, which is glucose unless the `condition` variant
        # selected an alternative carbon source. It goes at the head of the sequence, so that a timeline whose
        # FIRST event (at t=0) moves a glucose-fitted cell into acetate is a switch too. Measured in the large
        # campaign's release: `wildtype` + "0 minimal_acetate" divides at 2,805 s, then 800 s, and birth mass
        # falls 354 -> 202 -> 146 fg, while the fitted acetate condition divides at 4,776-6,662 s.
        # An initial condition (BV-12) fits the cell to that condition, so a timeline holding its own medium from
        # t=0 is no switch: `gene_knockout` + initial_condition 'acetate' + "0 minimal_acetate" is a knockout in
        # steady-state acetate. A medium different from the physiology's is still a switch.
        if design.perturbation == "condition" and design.condition in STATIC_ONLY_CARBON:
            start = design.condition
        elif ic:
            start = ic if ic in STATIC_ONLY_CARBON else "glucose"
        else:
            start = "glucose"
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

        # CRIT: the general form of the rule above. A tf_activity variant first, because its fitted condition, and so
        # the threshold the cell starts from, cannot be read from the design.
        if design.perturbation == "tf_activity":
            return EnvelopeVerdict(
                False,
                "A tf_activity variant fits the cell to its transcription factor's own condition, whose doubling time "
                "cannot be read from the design (the variant index runs over the knowledge base's sorted TF list). The "
                "model reads its replication threshold from that doubling time at startup and from the current medium "
                "at every step, so a timeline on top can move the threshold at its first event and make the cell "
                "initiate and divide early.",
                "Run the TF variant without a timeline, or run the shift on a fitted condition (perturbation="
                "'condition', or params.initial_condition) without the TF variant.",
            )
        step = threshold_step(design)
        rule = (design.params or {}).get("initiation_threshold") or "medium"
        if rule not in ("medium", "relaxed"):
            return EnvelopeVerdict(False, f"initiation_threshold={rule!r} is not a rule the model can run.",
                                   "Use 'relaxed' (CRIT tier 1) or leave it unset for the model's own rule.")
        if step is not None and rule == "relaxed":
            # CRIT tier 1 (2026-11-27): admitted, because the threshold no longer jumps; its limits travel with the run.
            return EnvelopeVerdict(
                True,
                f"This timeline moves the cell from {step.before} ({step.tau_before:g}-minute doubling time) into "
                f"{step.medium} ({step.tau_after:g} minutes). Under initiation_threshold='relaxed' (CRIT tier 1) the "
                f"replication threshold relaxes towards {step.medium}'s value over about one doubling time instead of "
                "jumping. Tier 1's limits apply: after a downshift initiation still comes somewhat early and there is "
                "no ppGpp pause; reading division timing from such a run stays refused until the shift panel (V3) "
                "passes.")
        if step is not None:
            when = "at t=0" if step.at == 0 else f"at {step.at:g} s"
            fg_before, fg_after = THRESHOLD_FG.get(step.tau_before), THRESHOLD_FG.get(step.tau_after)
            jump = (f" ({fg_before:g} to {fg_after:g} fg)" if fg_before and fg_after else "")
            down = step.tau_after > step.tau_before
            direction = "drops" if down else "rises"
            effect = ("After a downshift like this the cell initiates and divides early where the organism pauses "
                      "initiation (well4cell rc2: glucose-fitted cells moved into no oxygen mid-run divide at a median "
                      "2,238 s, against 4,627 s for cells fitted to it)" if down else
                      "After an upshift like this the cell must first grow to the higher threshold, so its next "
                      "initiation waits on the model's bookkeeping rather than on the cell")
            where = "" if step.view == next(iter(DOUBLING_TIME_VIEWS)) else f", as {step.view} time them"
            fitted = _fitted_for(step.medium)
            start_there = (f"Start the cell fitted to {step.medium}: perturbation='condition', condition='{fitted}' "
                           f"with replicate seeds, or, for a genotype, params.initial_condition='{fitted}' with the "
                           f"timeline '0 {step.medium}'. " if fitted else "Run in a fitted condition instead. ")
            return EnvelopeVerdict(
                False,
                f"This timeline moves the cell {when} from {step.before} ({step.tau_before:g}-minute doubling time) into "
                f"{step.medium} ({step.tau_after:g} minutes){where}. The model re-reads its replication threshold, the "
                f"critical initiation mass, from the current medium at every step, so the threshold {direction} at "
                f"once{jump} while the cell's mass and machinery are still the old medium's. {effect}, so division "
                f"timing, birth size and gene dosage after the shift are artefacts.",
                start_there + "A shift between media with different doubling times is outside the envelope until the "
                "model's threshold follows the cell rather than the medium (CRIT).",
            )

    return EnvelopeVerdict(True, "Inside the model's validated perturbation envelope.")
