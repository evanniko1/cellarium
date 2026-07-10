"""Backend adapter + data model.

Cellarium reasons over results produced by the *public* Covert-lab whole-cell E. coli model. Full runs are
expensive (~9 min / generation), so the demo reads from a committed cache of real results; a live-run hook is
left as an explicit extension point (`run_live`) rather than faked.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache"


class Design(BaseModel):
    """A proposed in-silico experiment."""

    perturbation: str = "wildtype"          # e.g. wildtype, gene_knockout, ppgpp_conc, timeline
    params: dict = Field(default_factory=dict)
    condition: str | None = None            # static media condition (e.g. "basal", "acetate")
    timeline: str | None = None             # media-shift events string (e.g. "0 minimal, 1200 minimal_acetate")
    seeds: int = 1
    generations: int = 1


class GenerationResult(BaseModel):
    """Per-generation record used by the QC guardrail (mirrors the real simOut signals)."""

    index: int
    full_chromosome_end: int = 2            # 2 = one clean round of replication
    divided: bool = True
    division_time_sec: float | None = None
    n_steps: int = 2500
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
