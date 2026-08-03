"""Backend adapter + data model.

Cellarium reasons over results produced by the *public* Covert-lab whole-cell E. coli model. Full runs are
expensive (~9 min / generation), so the demo reads from a committed cache of real results; a live-run hook is
left as an explicit extension point (`run_live`) rather than faked.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from .capability import DEFAULT_MODE, ELONGATION_MODES

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache"


class Design(BaseModel):
    """A proposed in-silico experiment."""

    perturbation: str = "wildtype"          # e.g. wildtype, gene_knockout, ppgpp_conc, timeline
    params: dict = Field(default_factory=dict)
    condition: str | None = None            # static media condition (e.g. "basal", "acetate")
    timeline: str | None = None             # media-shift events string (e.g. "0 minimal, 1200 minimal_acetate")
    seeds: int = 1
    generations: int = 1
    # WHICH ELONGATION MODEL produced this run. A string and not a bool: the checkout carries three today and
    # the set will grow, and a bool would have to be replaced the moment it did. It DEFAULTS to "steady_state",
    # which is not a convenience — every one of the ~300 historical design.json files on disk is validated back
    # through this class (`runner._evacuate`, `manifest._design_from_dir`), and without the default each of
    # them would fail validation: `_evacuate` would report "unreadable provenance", `run_one` would RAISE
    # rather than run, and `record_existing` would die outright. The default is what keeps the corpus loadable.
    #
    # It is load-bearing far beyond a label. The same 86-wide `GrowthLimits/fraction_trna_charged` column means
    # a broadcast identity under steady_state, 86 independent measurements under kinetic, and 86 exact zeros
    # under coarse_kinetic — so a row that cannot name its model cannot be pooled with, or told apart from,
    # a row from another one.
    elongation_model: str = DEFAULT_MODE

    @field_validator("elongation_model")
    @classmethod
    def _known_elongation_model(cls, v: str) -> str:
        """Reject an unknown mode HERE, loudly, rather than downstream.

        An unvalidated string reaches `runner._variant_args`, which maps it to a runSim flag. A typo would
        either emit a flag the model's argparse rejects (a container that dies minutes in) or — worse — fall
        through to emitting nothing, producing a steady-state run wearing another model's name in its label,
        its design tag and its manifest row. That is the WELL-NOOP-1 pattern (a wild type wearing a knockout's
        label) transplanted onto the elongation axis, and this repo has already paid for it once."""
        if v not in ELONGATION_MODES:
            raise ValueError(
                f"unknown elongation_model {v!r} — declared models are {list(ELONGATION_MODES)}. This is "
                f"refused rather than passed through, because an unrecognised value maps to no runSim flag "
                f"and would silently run the steady-state model under another model's name.")
        return v


class GenerationResult(BaseModel):
    """Per-generation record used by the QC guardrail (mirrors the real simOut signals)."""

    index: int
    full_chromosome_end: int = 2            # 2 = one clean round of replication
    divided: bool = True
    division_time_sec: float | None = None
    n_steps: int = 2500
    # First and last recorded timestep. Present so `qc.check_result` can test that generation n's data actually
    # REACHES generation n+1: an end-truncated generation still satisfies the division test (full_chromosome
    # ends at 2 over a long trajectory), so `divided` is True and `division_time_sec` quietly becomes the last
    # step that survived rather than the real division. Optional because pre-existing manifest rows have no
    # such fields — absent means "not checkable", never "continuous".
    t_start: float | None = None
    t_end: float | None = None
    fba_ok: bool = True
    is_dead: bool = False
    growth_mean: float | None = None        # per-generation means -> approach to steady state in multi-gen runs
    ppgpp_mean: float | None = None


class SimResult(BaseModel):
    id: str
    label: str = ""
    design: Design = Field(default_factory=Design)
    # summary channel means (µ, ppGpp, ribosome elongation, ...) grounded from real simOut
    channels: dict[str, float] = Field(default_factory=dict)
    units: dict[str, str] = Field(default_factory=dict)
    generations: list[GenerationResult] = Field(default_factory=list)
    note: str = ""
    # dynamics — so the corpus carries the transient a whole-run mean washes out (e.g. the stringent spike)
    channel_stats: dict = Field(default_factory=dict)   # {channel: {mean,min,max,first,last}}
    series: dict = Field(default_factory=dict)           # {channel: [[t_sec, value], ...] downsampled}
    media_segments: list = Field(default_factory=list)   # [{media, t0, t1, means:{channel: mean}}] per media window
    pathways: dict = Field(default_factory=dict)         # {pathway: proteome_fraction} — curated depth (P2.1)
    species_panel: dict = Field(default_factory=dict)    # {monomer_id: {mean, last, series}} per-species depth (scope A); panel members answer from the shard, others -> HF
    viability: dict = Field(default_factory=dict)        # {division_rate, gens_reached, terminal_divided, ...} §J


class ResultStore:
    """Loads cached real results. Keyed by id."""

    def __init__(self, cache_dir: Path = CACHE_DIR):
        self.cache_dir = cache_dir
        self._by_id: dict[str, SimResult] = {}
        self._load()

    def _load(self) -> None:
        for path in sorted(self.cache_dir.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, list):  # skip non-result JSON in data/cache (e.g. the variant map)
                continue
            for row in data:
                r = SimResult.model_validate(row)
                self._by_id[r.id] = r

    def list(self) -> list[SimResult]:
        return list(self._by_id.values())

    def get(self, result_id: str) -> SimResult | None:
        return self._by_id.get(result_id)


def run_live(design: Design, *, seeds: list[int] | None = None, generations: int | None = None,
             sim_path: str = "cellarium", append_manifest: bool = True) -> list[SimResult]:  # pragma: no cover - drives the external model
    """Run the public wcEcoli model live for an (uncached) design and return one SimResult per seed.

    Chains the existing execution pieces — ParCa (cached) -> runner.run_one per lineage -> reader -> a
    SimResult — and, by default, appends the fresh runs to the manifest so they become queryable by the
    grounded tools (survey, rigor.disconfirm). This is what lets a hypothesis be tested against NEW simulation
    output rather than only the committed cache.

    Requires the model to be reachable: set WCECOLI_DOCKER (a local model image) or WCECOLI_DIR (a native
    checkout) — see runner.py / docs/GENERATE.md. Feasibility and biosecurity are enforced inside
    runner.run_one (via envelope.check); an out-of-envelope design raises rather than running.

    GATING (see DECISIONS.md D5): this is the UNGATED, operator/eval launch path — it runs immediately, skipping
    the human-approval airlock. The gated, agent-facing path is launch.propose -> launch.approve_and_run (a human,
    not Cellwright, approves). Both enforce the same feasibility/biosecurity screen; they differ only in the human gate.

    seeds/generations default to the design's own `seeds`/`generations`. Real runs are slow (~9 min/generation,
    plus a one-time ParCa compile); size accordingly.
    """
    from . import manifest, runner  # lazy: manifest imports model -> avoid an import cycle

    gens = generations if generations is not None else design.generations
    seed_list = list(seeds) if seeds is not None else list(range(design.seeds))
    if not (runner._out_root(sim_path) / "kb" / "simData.cPickle").exists():
        runner.ensure_parca(sim_path)  # compile sim_data once; skip when already cached (ParCa is ~10-20 min)

    results: list[SimResult] = []
    rows: list[dict] = []
    for s in seed_list:
        run_root = runner.run_one(design, s, gens, sim_path)
        rec = manifest.build_record(run_root, design, s)
        results.append(rec)
        rows.append(manifest._flat_row(rec, s, run_root))
    if append_manifest and rows:
        manifest.append_shard(rows)  # fresh runs become visible to survey / disconfirm (the falsifier)
    return results
