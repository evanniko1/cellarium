"""Grounded tools exposed to the Claude agent.

Reads go through the unified `store` (DuckDB manifest, or the JSON demo cache). `list_species`/`read_species`
give the agent depth to ANY of the model's ~12,000 state variables via the public reader — as long as the
trajectory's full simOut is local (else deferred to HF sharing, DECISIONS D1). No tool invents numbers.
"""

from __future__ import annotations

from pathlib import Path

from . import biosecurity, differential as _diff, envelope, provenance as _prov, rigor, store, survey
from .model import Design

_SPECIES_KINDS = ["protein", "mrna", "metabolite", "reaction_flux", "exchange_flux", "unique"]


def list_results(gene: str | None = None, perturbation: str | None = None, contains: str | None = None) -> dict:
    """List simulation results (id, label, QC). FILTER rather than dump the whole corpus: gene='pfkA' returns just
    that KO's runs, perturbation='gene_knockout' narrows to KOs, contains='<label substring>' is a free search.
    The full unfiltered list is long and may be truncated in context — so to ask 'are there results for X?', pass
    gene=X and read `n` (0 = genuinely absent). Reads the same manifest as the Corpus Browser."""
    rows = store.list_results()
    if gene:
        g = gene.strip().lower().replace("ko:", "")
        rows = [r for r in rows if g in (r.get("label") or "").lower() or g in (r.get("condition") or "").lower()]
    if perturbation:
        rows = [r for r in rows if r.get("perturbation") == perturbation]
    if contains:
        c = contains.strip().lower()
        rows = [r for r in rows if c in (r.get("label") or "").lower()]
    return {"n": len(rows), "results": rows}


_VARIANT_TYPES = {
    "wildtype": "baseline / a named condition (--condition)",
    "condition": "static media steady state; variant_index -> ordered_conditions (see `conditions`)",
    "gene_knockout": "single-gene expression KO; variant_index = the gene's ko_index (resolve via design_space(gene=...))",
    "multi_gene_knockout": "simultaneous KO of a gene SET (reduced-genome style)",
    "ppgpp_conc": "clamp [ppGpp] — graded stringent-response lever (a CLEAN phenotype path, unlike a single KO)",
    "rrna_operon_knockout": "KO n of 7 rRNA operons — graded ribosome-capacity lever (clean phenotype path)",
    "timeline": "media-shift events over time (in-envelope shifts only — check_feasibility first)",
    "metabolism_kinetic_objective_weight": "graded objective lever (kinetic vs homeostatic weight; §K/D4)",
    "metabolism_secretion_penalty": "graded objective lever (secretion penalty)",
    "tf_activity": "set a modeled TF active/inactive — ONLY the 23 mechanistically-modeled TFs (not marA/soxS)",
}


def design_space(gene: str | None = None) -> dict:
    """Enumerate the RUNNABLE design space so a hypothesis can propose a REAL experiment: static conditions,
    perturbation/variant types, and gene-KO resolution. Pass `gene` to resolve its symbol -> ko_index PLUS its
    calibrated KO prior (so you propose the right index AND know what to expect). Call before proposing to run."""
    import json
    from pathlib import Path

    from . import scope

    out: dict = {"variant_types": _VARIANT_TYPES}
    vm = Path("data/cache/variant_map.json")
    if vm.exists():
        m = json.loads(vm.read_text(encoding="utf-8"))
        out["conditions"] = m.get("conditions", {})
        out["n_ko_genes"] = m.get("n_genes")
    else:
        out["conditions"] = {}
        out["note"] = "conditions/indices not cached — run `python -m cellarium.reader --variant-map`."
    if gene:
        c = scope.classify_gene(gene)
        out["gene"] = ({"symbol": gene, "ko_index": c.get("ko_index"), "role": c.get("role"),
                        "ko_effect_prior": c.get("ko_effect_prior"), "benchmark": c.get("benchmark")}
                       if c.get("known") else {"symbol": gene, "known": False, "note": c.get("note")})
    return out


def survey_corpus() -> dict:
    """Deterministic, ranked, whole-corpus survey — call FIRST, before forming any hypothesis."""
    return survey.survey_corpus()


def differential(target: str, reference: str = "wildtype/basal") -> dict:
    """Rank channels + pathways by fold-change of one design vs a reference — what moved most."""
    rigor.note_design(target)
    rigor.note_design(reference)
    return _diff.summary(target, reference)


def top_movers(target: str, reference: str = "wildtype/basal", kind: str = "protein", top: int = 12) -> dict:
    """Species that moved most between two DESIGNS (seed-averaged, count-floored, reproducibility-flagged)."""
    if kind not in _SPECIES_KINDS:
        return {"error": f"kind must be one of {_SPECIES_KINDS}"}
    rigor.note_design(target)
    rigor.note_design(reference)
    return _diff.top_movers(target, reference, kind, top)


def screen_design(perturbation: str = "wildtype", condition: str | None = None,
                  timeline: str | None = None, params: dict | None = None) -> dict:
    v = biosecurity.screen(Design(perturbation=perturbation, condition=condition, timeline=timeline,
                                  params=params or {}))
    return {"flagged": v.flagged, "signature": v.signature, "matched": v.matched,
            "severity": v.severity, "reason": v.reason}


def screen_phenotype(target: str, reference: str = "wildtype/basal") -> dict:
    """Phenotype-grounded biosecurity: does a design's simulated proteome up-regulate a misuse signature?"""
    v = biosecurity.screen_result(target, reference)
    return {"flagged": v.flagged, "signature": v.signature, "log2fc": v.log2fc,
            "severity": v.severity, "reason": v.reason}


def read_series(result_id: str, channel: str) -> dict:
    rid = _resolve_result(result_id) or result_id   # accept a design label ('gene_knockout/KO:pfkA') or gene, not just an id
    rigor.note_result(rid)
    out = store.read_channel(rid, channel)
    if isinstance(out, dict) and out.get("error") and "no result" in str(out.get("error")).lower():
        key = str(result_id).split("/")[-1].replace("KO:", "").strip().lower()
        hits = sorted({r.get("label") for r in store.list_results() if key and key in (r.get("label") or "").lower()})
        if hits:
            out["did_you_mean"] = hits[:8]   # help the agent to the real labels instead of a dead-end 404
    return out


_VL = "https://vega.github.io/schema/vega-lite/v5.json"


def _run_label(rid: str) -> str:
    r = next((x for x in store.list_results() if x.get("id") == rid), {})
    base = (r.get("condition") or "").replace("KO:", "") or r.get("perturbation") or rid
    return f"{base}·s{r.get('seed')}" if r.get("seed") is not None else base


def _resolve_result(x: str) -> str | None:
    """Accept a result_id OR a design label 'perturbation/condition' -> a representative result_id (qc-ok, lowest
    seed). Matches how differential/disconfirm speak in design labels, so chart doesn't fail on the agent's
    natural vocabulary."""
    rows = store.list_results()
    if any(r.get("id") == x for r in rows):
        return x
    pert, _, cond = str(x).partition("/")
    cands = [r for r in rows if r.get("perturbation") == pert
             and ((r.get("condition") or "") == cond or (cond and cond in (r.get("condition") or "")))]
    if not cands:   # fall back to a gene/substring match on the label, so 'pfkA' or 'KO:pfkA' also resolves
        key = str(x).split("/")[-1].replace("KO:", "").strip().lower()
        if key:
            cands = [r for r in rows if key in (r.get("label") or "").lower()]
    cands.sort(key=lambda r: (r.get("qc") != "ok", r.get("seed") if r.get("seed") is not None else 99))
    return cands[0]["id"] if cands else None


def _pct(a: list, p: float) -> float:
    if not a:
        return 0.0
    return a[min(len(a) - 1, max(0, int(round(p / 100 * (len(a) - 1)))))]


def read_raw_series(result_id: str, channel: str = "growth_rate", max_points: int = 60) -> dict:
    """DRILL DOWN into the local raw simOut: the FULL-RESOLUTION trajectory of `channel` for ONE seed, where
    read_series/the manifest only carry a coarse ~16-point downsample. Accepts a result_id or a design label (uses
    its lowest local seed). Reads wcEcoli listener columns directly from disk — no Docker. Returns a downsampled
    view (max_points) plus true stats over ALL timesteps. Use this when a question needs resolution the shard lacks
    (a transient, an exact rate at a time), or as the per-seed complement to variance_band."""
    from . import raw as rawmod
    runs = rawmod.seed_runs(result_id)
    if not runs:
        return {"error": f"no local raw simOut for '{result_id}' — see data_availability for the HF/regenerate path."}
    run = next((r for r in runs if r["result_id"] == result_id), runs[0])
    try:
        t, v = rawmod.seed_channel(run["root"], channel)
    except KeyError:
        return {"error": f"channel '{channel}' has no raw mapping; try {sorted(rawmod.CHANNELS)}."}
    if t.size == 0:
        return {"error": f"no readable '{channel}' trajectory in the raw simOut for that seed."}
    rigor.note_result(run["result_id"])
    k = max(2, min(int(max_points), 200))
    idx = range(t.size) if t.size <= k else (int(round(i * (t.size - 1) / (k - 1))) for i in range(k))
    series = [[round(float(t[i]), 1), round(float(v[i]), 8)] for i in idx]
    return {"result_id": run["result_id"], "seed": run["seed"], "channel": channel, "n_gens": run["n_gens"],
            "n_timesteps": int(t.size), "resolution_sec": round(float(t[-1] - t[-2]), 2) if t.size > 1 else None,
            "stats": {"mean": round(float(v.mean()), 8), "min": round(float(v.min()), 8),
                      "max": round(float(v.max()), 8), "first": round(float(v[0]), 8), "last": round(float(v[-1]), 8)},
            "series": series, "grounded_from": "raw simOut (local, full-resolution)"}


def variance_band(design: str, channel: str = "growth_rate", n_points: int = 40) -> dict:
    """The CROSS-SEED variance the coarse shard cannot express: read every LOCAL seed's full-resolution simOut for
    `channel`, resample onto a common time grid, and return per-timepoint mean, std, sem and CI95 ACROSS seeds
    (grounded numbers only — no fabricated spread). Pass a design label ('condition/no_oxygen'). Pair with
    chart(kind='band', ...) to draw it, or read the numbers here. Needs >=2 local seeds with the channel."""
    from . import raw as rawmod
    out = rawmod.cross_seed_band(design, channel, n_points)
    if "error" not in out:
        for s in out.get("seeds", []):
            rigor.note_result(s["result_id"])
    return out


def raw_available(design: str) -> dict:
    """What FULL-RESOLUTION raw simOut is reachable on LOCAL DISK right now for a design: which seeds, generations
    per seed, and which channels are readable. The drill-down discovery step before read_raw_series / variance_band
    (distinct from data_availability, which is about the HF download path)."""
    from . import raw as rawmod
    return rawmod.available(design)


def download_raw(design: str, confirm: bool = False) -> dict:
    """Fetch a design's missing raw simOut archives from HF into the local runs dir, so read_raw_series /
    variance_band can then read them. GATED BY SIZE: call it FIRST with confirm=False (default) — it downloads
    NOTHING and returns est_gb + a needs_confirmation message. Surface that size to the user ('this pulls ~N GB from
    HF, proceed?') and only call again with confirm=True AFTER they approve. Never pass confirm=True without the
    user's explicit go-ahead. Use only when raw_available shows the design isn't fully local."""
    from . import hf
    out = hf.download_raw(design, confirm)
    if confirm and out.get("downloaded"):
        for rid in out["downloaded"]:
            rigor.note_result(rid)
    return out


def _band_chart(design, channel, title, rationale):
    """chart(kind='band'): a cross-seed mean±CI95 ribbon over time, built from local raw simOut."""
    from . import raw as rawmod
    if not design:
        return {"error": "band needs a design label, e.g. result_id='condition/no_oxygen'."}
    b = rawmod.cross_seed_band(design, channel, 48)
    if "error" in b:
        return b
    for s in b.get("seeds", []):
        rigor.note_result(s["result_id"])
    ser = b["series"]
    values = [{"t": p["t"], "mean": p["mean"], "lo": p["lo"], "hi": p["hi"]}
              for p in ser if p["mean"] is not None]
    bounds = sorted(x for p in ser for x in (p["lo"], p["hi"]) if x is not None)
    ylo, yhi, ytop = _pct(bounds, 2), _pct(bounds, 98), (bounds[-1] if bounds else 0)
    n_clamp = sum(1 for x in bounds if x > yhi)
    yscale = {"domain": [min(0, ylo), yhi], "clamp": True} if (n_clamp and yhi < ytop) else None
    xenc = {"field": "t", "type": "quantitative", "title": "time since start (s)"}
    yenc = {"field": "mean", "type": "quantitative", "title": f"{channel} (mean ± CI95, n={b['n_seeds']})"}
    if yscale:
        yenc["scale"] = yscale
    area_y = {"field": "lo", "type": "quantitative"}
    if yscale:
        area_y["scale"] = yscale
    spec = {"$schema": _VL, "title": title or f"{channel}: cross-seed variance — {design}",
            "data": {"values": values}, "encoding": {"x": xenc},
            "layer": [
                {"mark": {"type": "area", "opacity": 0.22, "color": "#C96442", "tooltip": True},
                 "encoding": {"y": area_y, "y2": {"field": "hi"}}},
                {"mark": {"type": "line", "point": True, "color": "#C96442", "tooltip": True},
                 "encoding": {"y": yenc}}]}
    cap = title or f"{channel} — cross-seed mean ± CI95 band across {b['n_seeds']} seeds ({design})"
    if n_clamp:
        cap += f" · {n_clamp} early transient point(s) clamped (up to {ytop:.2g})"
    return {"spec": spec, "caption": cap, "rationale": rationale,
            "provenance": {"channel": channel, "design": design, "n_seeds": b["n_seeds"],
                           "runs": [s["result_id"] for s in b["seeds"]],
                           "grounded_from": "raw simOut (local, full-resolution)", "clamped_outliers": n_clamp}}


def chart(kind: str = "line", result_id: str | None = None, results: list | None = None,
          channel: str = "growth_rate", title: str | None = None, rationale: str | None = None,
          design: str | None = None) -> dict:
    """Draw a GROUNDED figure from real run data as a Vega-Lite spec (rendered inline, interactive). Every value
    comes from the manifest — never chart a number you did not read from a tool. Use it when a figure SHARPENS the
    answer (a trajectory, a comparison), not decoratively. Accepts result_ids OR design labels ('wildtype/basal',
    'ppgpp_conc/basal|ppGpp:0.2x') — labels resolve to a representative seed, like differential/disconfirm.
    - kind='line': the CHANNEL's trajectory over the cell cycle for result_id (pass results=[...] to overlay several).
      The x-axis is TIME-SINCE-START (each run aligned to t=0) so runs with different absolute clocks are comparable.
    - kind='bar':  compare the channel's value across results=[...].
    - rationale: ONE grounded sentence on why this figure matters to the answer — it becomes the figure's card in the
      investigation's Figures panel, so make it read on its own (what the reader should take away). Keep it to what the
      data shows; do not editorialize beyond it.
    Returns {spec, caption, rationale, provenance}."""
    if kind == "band":
        return _band_chart(design or result_id or (results[0] if results else None), channel, title, rationale)
    raw = [i for i in (results or ([result_id] if result_id else [])) if i]
    if not raw:
        return {"error": "give result_id/results (ids) or design labels like 'wildtype/basal'."}
    ids = [rid for rid in (_resolve_result(x) for x in raw) if rid]
    if not ids:
        return {"error": f"could not resolve any of {raw} to a run (use a result_id or 'perturbation/condition')."}
    for rid in ids:
        rigor.note_result(rid)

    if kind == "bar":
        vals = [{"run": _run_label(rid), channel: rc["value"]} for rid in ids
                for rc in [store.read_channel(rid, channel)] if isinstance(rc, dict) and rc.get("value") is not None]
        if not vals:
            return {"error": f"no '{channel}' values for those runs."}
        spec = {"$schema": _VL, "title": title or f"{channel} across runs", "data": {"values": vals},
                "mark": {"type": "bar", "tooltip": True},
                "encoding": {"x": {"field": "run", "type": "nominal", "sort": "-y"},
                             "y": {"field": channel, "type": "quantitative"}}}
        return {"spec": spec, "caption": title or f"{channel} across {len(vals)} run(s)", "rationale": rationale,
                "provenance": {"channel": channel, "runs": ids, "grounded_from": "manifest"}}

    # line: align each run's x to TIME-SINCE-START (t - t0) so runs on different clocks overlay comparably
    values, allys = [], []
    for rid in ids:
        ser = store.read_channel(rid, channel).get("series") or []
        pts = [p for p in ser if len(p) == 2 and p[1] is not None]
        if not pts:
            continue
        t0 = min(p[0] for p in ser)
        for p in pts:
            values.append({"t": p[0] - t0, channel: p[1], "run": _run_label(rid)}); allys.append(p[1])
    if not values:
        return {"error": f"no '{channel}' trajectory for those runs (try read_series or a different channel)."}
    allys.sort()
    ylo, yhi, ytop = _pct(allys, 2), _pct(allys, 98), allys[-1]
    n_clamp = sum(1 for v in allys if v > yhi)
    yenc = {"field": channel, "type": "quantitative", "title": channel}
    if n_clamp and yhi < ytop:                    # robust y: a division transient / spike shouldn't flatten the axis
        yenc["scale"] = {"domain": [min(0, ylo), yhi], "clamp": True}
    spec = {"$schema": _VL, "title": title or f"{channel} over the cell cycle", "data": {"values": values},
            "mark": {"type": "line", "point": True, "tooltip": True},
            "params": [{"name": "zoom", "select": "interval", "bind": "scales"}],
            "encoding": {"x": {"field": "t", "type": "quantitative", "title": "time since start (s)"},
                         "y": yenc, "color": {"field": "run", "type": "nominal", "title": "run"}}}
    cap = title or f"{channel} trajectory — {len(ids)} run(s)"
    if n_clamp:
        cap += f" · {n_clamp} transient point(s) clamped to the axis (up to {ytop:.2g})"
    return {"spec": spec, "caption": cap, "rationale": rationale,
            "provenance": {"channel": channel, "runs": ids, "grounded_from": "manifest", "clamped_outliers": n_clamp}}


def coverage_check() -> dict:
    """How much of the corpus you have deep-read this session — call before generalising a conclusion."""
    return rigor.coverage()


def corpus_audit() -> dict:
    """Read-only inventory of the WHOLE corpus: coverage (designs, seeds, generation depth, QC), redundancy
    (designs replicated beyond target -> GB prunable), supersession (older/crashed dead-weight rows), and gaps
    (power-thin designs + the disk-feasibility budget for new runs). Deletes nothing; separates safe-to-prune from
    irreplaceable. Use to plan pruning under storage pressure and to ground what-to-run-next proposals."""
    from . import audit
    return audit.audit_report()


def data_availability(result_id: str) -> dict:
    """For data BEYOND the distilled shard (an arbitrary non-panel species, a full-resolution trajectory, or FBA
    fluxes), where to get it: (1) download the run's raw simOut from the HF dataset, or (2) regenerate it locally.
    The shard already answers panel-species + summary questions with no download — only call this when a question
    needs a species/resolution the shard doesn't carry, and surface BOTH alternatives to the user."""
    from . import hf
    rid = _resolve_result(result_id) or result_id   # accept a design label ('gene_knockout/KO:pfkA'), not just an id,
    return hf.data_availability(rid)                 # so the HF-availability check matches download_raw (same resolution)


def prune_candidates() -> dict:
    """The SPECIFIC run dirs safe to prune: the excess seeds of designs redundancy marks 'prune-safe' (lowest seed
    indices KEPT), each with raw-on-disk + estimated GB. DELETES NOTHING — relay this grounded, deterministic list
    to the user; the deletion is THEIR confirmed, irreversible action, never yours. Use after corpus_audit when the
    user asks which files they can delete."""
    from . import audit
    return audit.prune_candidates()


def provenance(perturbation: str, condition: str | None = None) -> dict:
    """Is a design's result IN-SAMPLE (a ParCa-fitted condition — agreement is consistency) or OUT-OF-SAMPLE
    (a perturbation the fit did not target — a genuine prediction)? Check before claiming the model 'predicts'."""
    return _prov.classify(perturbation, condition)


def mechanistic_scope(symbol: str) -> dict:
    """Is a gene's function SIMULATED (metabolic enzyme / modeled TF / central-dogma machinery) or expressed-but-
    inert? Returns a calibrated `ko_effect_prior` for the three single-KO regimes: non-mechanistic -> no phenotype
    BY CONSTRUCTION; metabolic -> the model REROUTES; machinery (ribosome/RNAP/replisome/aaRS) -> the sim CRASHES.
    Also compares the prior against a GROUND-TRUTH essentiality benchmark (Baba/Joyce) in `benchmark`: watch for
    `agreement == "model_UNDER_predicts"` (benchmark-essential gene the model would call viable — trust the
    benchmark). Prior, not verdict; for a measurable in-silico effect use a graded perturbation."""
    from . import scope
    return scope.classify_gene(symbol)


def viability(perturbation: str, condition: str | None = None) -> dict:
    """Does a KO/perturbation produce a VIABLE, dividing cell? Cross-seed division verdict per design from the
    manifest — the KO readout that does NOT reroute away like a graded growth channel. Omit `condition` to get
    every variant under a perturbation. NOTE: 'viable' is the MODEL's behavior, not ground truth — for a KO also
    call mechanistic_scope; a viable verdict can be a `model_UNDER_predicts` case (essential in vivo, viable in
    silico: fabI/glmS/gltA)."""
    if condition is not None:
        rigor.note_design(f"{perturbation}/{condition}")
    out = store.viability(perturbation, condition)
    if "error" not in out:
        out["calibration"] = ("verdict is a cross-seed MIN/BOOL_AND rollup (one seed collapsing flags the design). "
                              "A metabolic KO is VIABLE because the FBA objective has no growth term so it reroutes; "
                              "a machinery KO (aaRS/ribosome/RNAP) collapses. 'viable' is the model, NOT reality — "
                              "for a KO cross-check mechanistic_scope: if benchmark.agreement == 'model_UNDER_predicts' "
                              "the gene is essential in vivo despite a viable in-silico KO. Trust the benchmark.")
    return out


def propose_experiment(perturbation: str = "wildtype", condition: str | None = None, timeline: str | None = None,
                       params: dict | None = None, seeds: int = 4, generations: int = 4, gene: str | None = None,
                       genes: list | None = None) -> dict:
    """PROPOSE an experiment to run — Cellwright CANNOT launch sims itself. The design is vetted (safety is the only hard
    gate) and QUEUED pending human approval; a human approves via the interface, then the result is indexed so you
    can reason over it. Use design_space first to resolve gene symbols.

    Single-gene KO: perturbation='gene_knockout', gene='pfkA'. MULTI-gene KO: perturbation='multi_gene_knockout',
    genes=['pfkA','pfkB'] (the ko_indices are resolved for you). Returns the request id + the full vet result
    (pending_approval, or blocked if it hits a misuse signature)."""
    from . import launch
    params = dict(params or {})
    if genes:
        params["target_genes"] = list(genes)   # -> launch._resolve_ko turns these into ko_indices
    return launch.propose(perturbation, condition, timeline, params, seeds, generations, gene)


def revise_experiment(request_id: str, perturbation: str | None = None, condition: str | None = None,
                      timeline: str | None = None, params: dict | None = None, seeds: int | None = None,
                      generations: int | None = None, gene: str | None = None, genes: list | None = None) -> dict:
    """REVISE a PENDING experiment draft (one you got from propose_experiment) when the user wants to CHANGE an
    argument — e.g. more seeds, a different condition, a different gene set. This SUPERSEDES the old draft (no
    duplicate is left in the queue) and returns a re-vetted new draft pending human approval. Pass request_id +
    ONLY the fields you're changing. Do NOT call propose_experiment again to change a draft — that leaves a stale
    duplicate in the queue."""
    from . import launch
    return launch.revise(request_id, perturbation=perturbation, condition=condition, timeline=timeline,
                         params=params, seeds=seeds, generations=generations, gene=gene, genes=genes)


def propose_experiments(designs: list | None = None) -> dict:
    """PROPOSE a WHOLE PANEL of experiments in ONE call — use this instead of many propose_experiment calls whenever
    you are queuing more than one design (e.g. the Socratic Council's full falsifier panel: a reference + N KOs +
    the discriminating controls). Queuing per-design one at a time exhausts the turn budget and can leave the panel
    HALF-queued (the discriminating controls dropped) — this queues them atomically. Each design is vetted and
    queued exactly as propose_experiment does (safety-gated, pending human approval). `designs` is a list of objects,
    each: {perturbation, condition?, timeline?, gene?, genes?, params?, seeds?, generations?}. Returns a per-design
    result list plus a summary (queued / blocked / refused counts)."""
    from . import launch
    designs = designs or []
    if not designs:
        return {"error": "propose_experiments needs a non-empty `designs` list."}
    results = []
    queued = blocked = refused = 0
    for d in designs:
        d = dict(d or {})
        params = dict(d.get("params") or {})
        if d.get("genes"):
            params["target_genes"] = list(d["genes"])
        res = launch.propose(d.get("perturbation", "wildtype"), d.get("condition"), d.get("timeline"),
                             params, int(d.get("seeds", 4)), int(d.get("generations", 4)), d.get("gene"))
        status = res.get("status")
        if status == "pending_approval":
            queued += 1
        elif status == "blocked":
            blocked += 1
        else:                       # unresolved gene, bad args, etc. — not queued
            refused += 1
        results.append({"design": {k: d.get(k) for k in ("perturbation", "condition", "gene", "genes")},
                        "request_id": res.get("request_id"), "status": status, "error": res.get("error")})
    return {"queued": queued, "blocked": blocked, "refused": refused, "total": len(designs),
            "requests": results,
            "note": f"Queued {queued}/{len(designs)} designs PENDING human approval (blocked {blocked}, refused "
                    f"{refused}). Cellwright cannot launch — a human approves the panel via the interface."}


def vet_hypothesis(perturbation: str = "wildtype", condition: str | None = None, timeline: str | None = None,
                   params: dict | None = None, gene: str | None = None) -> dict:
    """Vet a proposed experiment before running it. SAFETY is the ONLY hard gate — out-of-sample / predicted-to-
    reroute / likely-to-fail hypotheses are ENCOURAGED (they are the genuine model tests; a gate on 'likely to
    fail' would have killed the most valuable experiments, e.g. the H2 model-boundary result). Feasibility +
    provenance + scope are ADVISORY annotations that set expectations, never block. `runnable` reflects safety only."""
    d = Design(perturbation=perturbation, condition=condition, timeline=timeline, params=params or {})
    safety = biosecurity.screen(d)          # HARD GATE (safety only) — never auto-run a flagged misuse design
    feas = envelope.check(d)                 # advisory: out-of-envelope => boundary test, still allowed
    prov = _prov.classify(perturbation, condition)   # epistemic: out-of-sample is a STRENGTH
    oos = prov.get("provenance") == "out_of_sample"
    out = {
        "runnable": not safety.flagged,      # ONLY safety gates; epistemics never set this False
        "safety": {"flagged": safety.flagged, "severity": getattr(safety, "severity", None),
                   "signature": getattr(safety, "signature", None), "reason": safety.reason,
                   "action": "REQUIRES HUMAN REVIEW — do not auto-run" if safety.flagged else "clear"},
        "feasibility": {"in_envelope": feas.in_envelope, "reason": feas.reason, "suggestion": feas.suggestion,
                        "advisory": ("outside the VALIDATED regime — allowed; interpret as a boundary probe, not a "
                                     "validated prediction" if not feas.in_envelope else "in the validated regime")},
        "provenance": {**prov, "value": ("OUT-OF-SAMPLE — a genuine model test; high value even if it FAILS (that is "
                                         "the point). Run it." if oos else
                                         "in-sample — agreement is consistency, not prediction")},
        "principle": ("SAFETY is the only hard gate. Epistemic flags (out-of-sample, reroute-likely, inert-scope) "
                      "set expectations; they NEVER block. Out-of-sample and predicted-to-fail hypotheses are "
                      "encouraged — they are where the model can be wrong, which is the experiment's value."),
    }
    if gene:
        from . import scope
        c = scope.classify_gene(gene)
        out["scope"] = ({"role": c.get("role"), "ko_effect_prior": c.get("ko_effect_prior"),
                         "benchmark": c.get("benchmark"),
                         "expectation": "PRIOR only — judge the KO by VIABILITY + the benchmark, not growth rate"}
                        if c.get("known") else {"symbol": gene, "known": False})
    out["recommendation"] = ("BLOCK pending review: " + safety.reason if safety.flagged
                             else "SAFE to run. " + ("Out-of-sample — run it (a genuine test). " if oos else "")
                             + ("Out-of-envelope — interpret as a boundary probe. " if not feas.in_envelope else ""))
    return out


def metabolic_essentiality(gene: str) -> dict:
    """Metabolic-essentiality ORACLE — METABOLISM ONLY (FBA cannot speak to machinery/regulation). For a metabolic
    gene, combines the authoritative Baba/Joyce benchmark (the authority — the whole-cell homeostatic FBA
    UNDER-predicts by rerouting) with the model's FBA single-deletion structural check + KO prior. For a
    non-metabolic gene it says so and points to the right axis (machinery->viability, TF->mechanistic_scope)."""
    from . import reader, scope
    c = scope.classify_gene(gene)
    if not c.get("known"):
        return {"gene": gene, "known": False, "note": c.get("note")}
    b = c.get("benchmark") or {}
    if c.get("role") != "metabolic_enzyme":
        return {"gene": gene, "role": c.get("role"), "benchmark": b,
                "scope": ("NOT a metabolic gene — the FBA oracle does not apply. Machinery -> use viability (crash "
                          "timing); TF -> mechanistic_scope; inert -> no modeled function.")}
    fba = (reader.fba_essentiality([gene]).get("genes", {}) or {}).get(gene, {})
    ess = b.get("essential_reference")
    return {"gene": gene, "role": "metabolic_enzyme",
            "verdict": ("ESSENTIAL (benchmark)" if ess else "non-essential (benchmark)" if ess is False
                        else "unknown (not in the Baba/Joyce set)"),
            "benchmark_essential": ess, "benchmark_agreement": b.get("agreement"),
            "model_ko_prior": c.get("ko_effect_prior"),
            "fba_structural": {"n_reactions": fba.get("n_rxn"), "flags_essential": fba.get("essential"),
                               "caveat": "under-sensitive — the homeostatic FBA has no growth term and reroutes"},
            "scope": "METABOLISM ONLY. The benchmark is the authority here; the whole-cell sim under-predicts."}


def model_validation() -> dict:
    """How well does the model predict gene essentiality vs the 402-gene ground-truth benchmark? Corpus-level
    agreement counts + the `model_UNDER_predicts` number, so you know when to trust a KO 'viable' verdict (you
    mostly can't for essential-gene candidates). No sims."""
    from . import scope
    return scope.model_validation_summary()


def power_check(channel: str = "growth_rate", effect_pct: float = 10.0, n_seeds: int = 4) -> dict:
    """Is a comparison adequately powered? Uses the corpus's observed per-design replicate CV for `channel` to
    estimate the minimum detectable effect at `n_seeds` and the seeds needed to detect `effect_pct` (two-sample,
    alpha 0.05, power 0.8). Grounds 'how many seeds do I need' in real replicate noise rather than a guess."""
    import math
    import statistics as _st

    rows = survey._deduped_rows([channel])
    by_design: dict = {}
    for r in rows:
        v = r.get(channel)
        if v is not None:
            by_design.setdefault((r.get("perturbation"), r.get("condition")), []).append(float(v))
    cvs = [(_st.pstdev(vs) / abs(_st.fmean(vs))) for vs in by_design.values() if len(vs) > 1 and _st.fmean(vs)]
    if not cvs:
        return {"error": f"no replicated design has >=2 seeds for channel '{channel}' — cannot estimate noise."}
    cv = _st.median(cvs)
    rel = effect_pct / 100.0
    k = 2 * (1.96 + 0.84) ** 2            # two-sample n-per-group constant (alpha .05, power .8)
    seeds_needed = math.ceil(k * (cv / rel) ** 2) if rel > 0 else None
    mde_pct = round(cv * math.sqrt(k / n_seeds) * 100, 1)
    return {"channel": channel, "observed_replicate_cv": round(cv, 4), "n_designs_used": len(cvs),
            "n_seeds": n_seeds, "min_detectable_effect_pct_at_n": mde_pct,
            "target_effect_pct": effect_pct, "seeds_needed_for_target": seeds_needed,
            "adequately_powered": (seeds_needed is not None and n_seeds >= seeds_needed),
            "note": ("Two-sample, alpha 0.05, power 0.8, using the median per-design replicate CV from the corpus. "
                     "min_detectable_effect_pct_at_n = the smallest effect n_seeds can resolve; a KO with no "
                     "growth effect below this is UNDER-powered, not proven equivalent.")}


def reroute_diagnosis(gene: str, target: str, reference: str = "wildtype/basal") -> dict:
    """For a VIABLE metabolic KO, is the 'no phenotype' a genuine biological reroute or a MATHEMATICAL ARTIFACT?
    Checks whether the KO'd enzyme's FBA flux is 0 in the KO yet nonzero in WT on a dividing cell — the model
    bypassing an enzyme real biology can't (the soft homeostatic objective never hard-requires that flux). Pair
    with mechanistic_scope's essentiality benchmark: an artifact reroute on an essential gene = model_UNDER_predicts."""
    from . import differential as _d, reader

    ko = _d._design_run_roots(target)
    wt = _d._design_run_roots(reference)
    if not ko:
        return {"error": f"no local runs for target '{target}'."}
    if not wt:
        return {"error": f"no local runs for reference '{reference}'."}
    rigor.note_design(target)
    return reader.reroute_diagnosis(gene, ko, wt)


def disconfirm(target: str, reference: str, channel: str) -> dict:
    """Challenge a claimed target-vs-reference effect on a channel (per-seed spread, noise, corpus z)."""
    rigor.note_design(target)
    rigor.note_design(reference)
    return rigor.disconfirm(target, reference, channel)


def check_feasibility(perturbation: str = "wildtype", condition: str | None = None,
                      timeline: str | None = None, seeds: int = 1, generations: int = 1,
                      params: dict | None = None) -> dict:
    v = envelope.check(Design(perturbation=perturbation, condition=condition, timeline=timeline,
                              seeds=seeds, generations=generations, params=params or {}))
    return {"in_envelope": v.in_envelope, "reason": v.reason, "suggestion": v.suggestion}


def run_experiment(perturbation: str = "wildtype", condition: str | None = None,
                   timeline: str | None = None, seeds: int = 1, generations: int = 1,
                   params: dict | None = None) -> dict:
    design = Design(perturbation=perturbation, condition=condition, timeline=timeline,
                    seeds=seeds, generations=generations, params=params or {})
    v = envelope.check(design)
    if not v.in_envelope:
        return {"status": "refused", "reason": v.reason, "suggestion": v.suggestion,
                "note": "Out of the validated envelope — not run, no metric reported."}
    b = biosecurity.screen(design)
    if b.flagged:
        return {"status": "biosecurity_hold", "signature": b.signature, "matched": b.matched,
                "severity": b.severity, "reason": b.reason,
                "note": "Flagged by the biosecurity screen — not run; "
                        + ("refused." if b.severity == "block" else "requires review before running.")}
    matches = [r for r in store.list_results()
               if r.get("perturbation") == perturbation and r.get("condition") == condition
               and r.get("timeline") == timeline]
    if matches:
        return {"status": "in_corpus", "results": matches[:8],
                "note": "Already generated. Ground via read_series / read_species."}
    return {"status": "in_envelope_uncached",
            "note": "Valid, but not yet in the corpus. Generation happens offline via a campaign, not per query."}


def _run_root(result_id: str) -> Path | None:
    root = store.simout_path(result_id)
    return Path(root) if root and Path(root).exists() else None


def list_species(result_id: str, kind: str = "protein", search: str = "") -> dict:
    from . import reader
    if kind not in _SPECIES_KINDS:
        return {"error": f"kind must be one of {_SPECIES_KINDS}"}
    root = _run_root(result_id)
    if root is None:
        return {"error": "full simOut not available locally for this trajectory (see DECISIONS D1 — HF sharing)."}
    return {"result_id": result_id, **reader.list_species(root, kind, search)}


def read_species(result_id: str, species_id: str, kind: str = "protein") -> dict:
    from . import reader
    if kind not in _SPECIES_KINDS:
        return {"error": f"kind must be one of {_SPECIES_KINDS}"}
    rigor.note_result(result_id)
    root = _run_root(result_id)
    if root is None:
        return {"error": "full simOut not available locally for this trajectory (see DECISIONS D1)."}
    return reader.read_species(root, kind, species_id)


def use_skill(name: str) -> dict:
    """Load a vendored scientific Agent Skill (K-Dense, MIT) — its instructions + endpoint reference docs — so you
    can execute it with web_get. Use for LITERATURE questions the corpus can't answer: 'paper-lookup' (10 literature
    APIs with provenance), 'literature-review' (search + synthesise a cited brief), 'bgpt-paper-search' (structured
    fields: methods/results/sample sizes/quality). This is how you check what's already PUBLISHED, whether a sim
    result agrees with the literature, and whether a finding is novel/wet-lab-worthy — NEVER for the primary numbers
    (those stay grounded in a run)."""
    from . import skills
    return skills.load_skill(name)


def web_get(url: str, headers: dict | None = None) -> dict:
    """HTTP GET for the literature/bioinformatics skills — allow-listed scientific hosts only (PubMed/OpenAlex/etc.),
    size-capped. This is the fetch tool the vendored skills call. Read the skill's reference doc (use_skill) for the
    exact endpoint + parameters before calling."""
    from . import skills
    return skills.web_get(url, headers)


_DESIGN_PROPS = {
    "perturbation": {"type": "string", "description": "variant type (wildtype, gene_knockout, ppgpp_conc, timeline, ...)"},
    "condition": {"type": "string", "description": "static media condition, e.g. basal, acetate"},
    "timeline": {"type": "string", "description": "media-shift events, e.g. '0 minimal, 1200 minimal_acetate'"},
    "seeds": {"type": "integer"}, "generations": {"type": "integer"},
}

TOOLS = [
    {"name": "survey_corpus", "description": "FIRST STEP for any results question. Deterministic, ranked, whole-corpus survey: every design vs a reference per channel, ranked by effect size (|z|), a cross-channel notable set, and coverage. Ground your reasoning in this WHOLE view before drilling in — do not anchor on individual runs or prior conversation.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "differential", "description": "Rank channels + pathways by fold-change of a design (e.g. 'gene_knockout/KO:acrB') vs a reference (default 'wildtype/basal') — what moved most. Use to interpret a KO/perturbation without pre-declaring which molecules to look at.",
     "input_schema": {"type": "object", "properties": {"target": {"type": "string", "description": "design label 'perturbation/condition' (from survey_corpus/list_results)"},
                      "reference": {"type": "string"}}, "required": ["target"]}},
    {"name": "top_movers", "description": "Individual species (proteins by default) that changed between two DESIGNS ('perturbation/condition' labels), tested with a Welch t across replicates + Benjamini-Hochberg FDR; returns only FDR-significant movers (q<=0.10) with their q-value, plus n_significant_fdr10. Gene-symbol-annotated. Needs >=2 replicates per design. If n_significant is ~0, there is no real network response — do not read the fold-changes as signal.",
     "input_schema": {"type": "object", "properties": {"target": {"type": "string"}, "reference": {"type": "string"},
                      "kind": {"type": "string", "enum": _SPECIES_KINDS}, "top": {"type": "integer"}},
                      "required": ["target"]}},
    {"name": "list_results", "description": "List simulation results in the corpus (id, label, QC). FILTER rather than dump: gene='pfkA' returns just that KO's runs; perturbation='gene_knockout' narrows to KOs; contains='<label substring>' is a free search. To answer 'are there results for X?', pass gene=X and read `n` — n=0 means genuinely absent. The unfiltered list is long and can be TRUNCATED in context, so NEVER conclude a design is absent from an unfiltered dump — filter for it. Same manifest the Corpus Browser reads.",
     "input_schema": {"type": "object", "properties": {"gene": {"type": "string", "description": "a gene symbol, e.g. 'pfkA' — returns its KO runs"}, "perturbation": {"type": "string"}, "contains": {"type": "string", "description": "free substring match on the label"}}}},
    {"name": "design_space", "description": "Enumerate the RUNNABLE design space before proposing an experiment: static conditions (index->label), perturbation/variant types (with which give CLEAN graded phenotypes vs which reroute), and gene-KO resolution. Pass `gene` to get its ko_index PLUS its calibrated KO prior + essentiality benchmark. Use this so a hypothesis proposes a real, correctly-indexed experiment instead of guessing.",
     "input_schema": {"type": "object", "properties": {"gene": {"type": "string", "description": "optional gene symbol to resolve to its ko_index + KO prior"}}}},
    {"name": "read_series", "description": "Read one summary channel (growth_rate, ppgpp_conc, ...) for a result: overall mean PLUS its downsampled trajectory and per-media-segment means — use this to see transients (e.g. the ppGpp spike after a media downshift) that a single mean hides. This is the COARSE manifest view (~16 points); for the full-resolution raw trajectory use read_raw_series.",
     "input_schema": {"type": "object", "properties": {"result_id": {"type": "string"}, "channel": {"type": "string"}},
                      "required": ["result_id", "channel"]}},
    {"name": "read_raw_series", "description": "DRILL DOWN into the local raw simOut: the FULL-RESOLUTION trajectory of a channel for ONE seed (every timestep), where read_series/the manifest carry only a ~16-point downsample. Reads wcEcoli listener columns directly from local disk — no Docker. Use when a question needs resolution the shard lacks (a transient, an exact rate at a time). Accepts a result_id or a design label (lowest local seed). Only for designs with raw on local disk — check raw_available first.",
     "input_schema": {"type": "object", "properties": {"result_id": {"type": "string", "description": "a result_id or design label like 'condition/no_oxygen'"}, "channel": {"type": "string", "description": "growth_rate, cell_mass, dry_mass, protein_mass, rna_mass, ppgpp_conc, ribosome_conc, fraction_trna_charged, rela_conc, fba_objective"}, "max_points": {"type": "integer", "description": "downsample the returned series to at most this many points (default 60); stats are over ALL timesteps"}}, "required": ["result_id", "channel"]}},
    {"name": "variance_band", "description": "The CROSS-SEED variance the coarse shard cannot express: reads EVERY local seed's full-resolution simOut for a channel, resamples onto a common time grid, and returns per-timepoint mean, std, sem and CI95 ACROSS seeds — grounded numbers only, no fabricated spread. Pass a DESIGN label. This is how to honestly answer 'draw the variance over time/generations'. Pair with chart(kind='band') to draw it. Needs >=2 local seeds with the channel (check raw_available).",
     "input_schema": {"type": "object", "properties": {"design": {"type": "string", "description": "a design label like 'condition/no_oxygen'"}, "channel": {"type": "string", "description": "growth_rate, ppgpp_conc, cell_mass, ..."}, "n_points": {"type": "integer", "description": "grid resolution (default 40)"}}, "required": ["design"]}},
    {"name": "raw_available", "description": "What FULL-RESOLUTION raw simOut is reachable on LOCAL DISK right now for a design: which seeds, generations per seed, and which channels are readable. The drill-down discovery step before read_raw_series / variance_band. Distinct from data_availability (which is about the HF download path) — this reports what you can read WITHOUT any download.",
     "input_schema": {"type": "object", "properties": {"design": {"type": "string", "description": "a design label like 'condition/no_oxygen' or a result_id"}}, "required": ["design"]}},
    {"name": "download_raw", "description": "Fetch a design's MISSING raw simOut archives from HF into the local runs dir, so read_raw_series/variance_band can then read them. GATED BY SIZE (a bandwidth action, not a read): call it FIRST with confirm=false — it downloads NOTHING and returns est_gb + needs_confirmation. Tell the user 'this pulls ~N GB from HF, proceed?' and only call again with confirm=true AFTER they say yes. NEVER pass confirm=true without the user's explicit approval. Use only when raw_available shows the design isn't fully local but it's on HF.",
     "input_schema": {"type": "object", "properties": {"design": {"type": "string", "description": "a design label like 'condition/no_oxygen'"}, "confirm": {"type": "boolean", "description": "leave false/absent to get the size estimate; set true ONLY after the user approves the ~N GB pull"}}, "required": ["design"]}},
    {"name": "chart", "description": "Draw a GROUNDED figure from real run data — it renders inline as an interactive chart AND is indexed in the investigation's Figures panel. Every value comes from a tool read; never chart a number you did not read. Use it when a figure SHARPENS the answer, not decoratively. kind='line' plots the channel's trajectory over the cell cycle (x is time-since-start, so runs on different clocks overlay comparably); kind='bar' compares the channel's value across runs; kind='band' draws a cross-seed mean±CI95 ribbon over time from local raw simOut (the true per-timepoint variance — use for 'plot the variance'). Accepts result_ids OR design labels like 'wildtype/basal'.",
     "input_schema": {"type": "object", "properties": {"kind": {"type": "string", "enum": ["line", "bar", "band"], "description": "line = trajectory over time; bar = compare across runs; band = cross-seed variance ribbon over time (needs local raw)"}, "result_id": {"type": "string", "description": "the run to plot (line), or the DESIGN label for band — a result_id or a design label like 'wildtype/basal'"}, "design": {"type": "string", "description": "for kind='band': the design label whose seeds to band, e.g. 'condition/no_oxygen' (alias of result_id, matches variance_band/raw_available)"}, "results": {"type": "array", "items": {"type": "string"}, "description": "runs to overlay (line) or compare (bar) — result_ids or design labels"}, "channel": {"type": "string", "description": "channel to plot, e.g. growth_rate, cell_mass, division_rate, ppgpp_conc"}, "title": {"type": "string"}, "rationale": {"type": "string", "description": "ONE grounded sentence — why this figure matters to the answer / what the reader should take away. Becomes the figure's card in the Figures panel, so it must read on its own."}}}},
    {"name": "list_species", "description": "Resolve real model IDs for a molecule kind (protein/mrna/metabolite/reaction_flux/exchange_flux) matching a search — grounding before read_species.",
     "input_schema": {"type": "object", "properties": {"result_id": {"type": "string"},
                      "kind": {"type": "string", "enum": _SPECIES_KINDS}, "search": {"type": "string"}},
                      "required": ["result_id", "kind"]}},
    {"name": "read_species", "description": "Read the time-series of ONE state variable (any protein/mRNA/metabolite/flux) from a result's full simOut.",
     "input_schema": {"type": "object", "properties": {"result_id": {"type": "string"},
                      "species_id": {"type": "string"}, "kind": {"type": "string", "enum": _SPECIES_KINDS}},
                      "required": ["result_id", "species_id"]}},
    {"name": "disconfirm", "description": "Before committing to a causal claim, challenge it: given a claimed effect (target vs reference on a channel), returns the per-seed spread (is the effect bigger than replicate noise?), the corpus z-score, and a falsification checklist. Call this on your main claim before concluding.",
     "input_schema": {"type": "object", "properties": {"target": {"type": "string"}, "reference": {"type": "string"},
                      "channel": {"type": "string"}}, "required": ["target", "reference", "channel"]}},
    {"name": "coverage_check", "description": "How much of the corpus you have deep-read this session vs the full design grid. Call before generalising a conclusion; do not claim beyond the examined set.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "corpus_audit", "description": "Read-only inventory of the WHOLE corpus: coverage (designs, seeds, generation depth, QC), redundancy (designs replicated beyond a target -> estimated GB prunable), supersession (older/crashed dead-weight rows), and gaps (power-thin designs + the disk-feasibility budget for new runs). Deletes nothing; separates safe-to-prune from irreplaceable. Use to plan pruning under storage pressure and to ground what-to-run-next proposals with the disk budget.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "data_availability", "description": "For data BEYOND the distilled shard (an arbitrary non-panel species, a full-resolution trajectory, or FBA fluxes), tells the user the TWO ways to get it: (1) download the run's raw simOut from the HF dataset, or (2) regenerate it locally. The shard already answers panel-species + summary questions with no download; only use this when the question needs a species/resolution the shard doesn't carry, and present both alternatives.",
     "input_schema": {"type": "object", "properties": {"result_id": {"type": "string", "description": "the result id (from list_results/survey_corpus)"}}, "required": ["result_id"]}},
    {"name": "prune_candidates", "description": "The SPECIFIC run dirs safe to prune: the excess seeds of designs redundancy marks 'prune-safe' (lowest seed indices kept), each with raw-on-disk + estimated GB. DELETES NOTHING -- relay this grounded, deterministic list; the user confirms and deletes (irreversible), never you. Use after corpus_audit/redundancy when the user asks which files they can delete.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "provenance", "description": "Is a design's result IN-SAMPLE (a ParCa-fitted condition — model was calibrated to match it, so agreement is consistency NOT prediction) or OUT-OF-SAMPLE (a perturbation the fit didn't target — a genuine prediction)? Check before claiming the model 'predicts' or 'validates' something.",
     "input_schema": {"type": "object", "properties": {"perturbation": {"type": "string"}, "condition": {"type": "string"}},
                      "required": ["perturbation"]}},
    {"name": "mechanistic_scope", "description": "Is a gene's FUNCTION mechanistically simulated (metabolic enzyme or one of the ~23 modeled TFs) or expressed-but-inert? A knockout of a non-mechanistic gene shows no phenotype BY CONSTRUCTION — a null there is model scope, NOT biological dispensability. Check before interpreting a KO. Also returns a ground-truth essentiality benchmark (`benchmark`): watch for agreement=='model_UNDER_predicts' (essential gene the model would call viable).",
     "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}},
    {"name": "viability", "description": "Does a KO/perturbation produce a VIABLE, dividing cell? Cross-seed division verdict (viable/impaired/inviable) per design from the manifest — the KO readout that does NOT reroute away like a growth channel (a metabolic KO reroutes = viable; a machinery KO collapses). Omit condition to get every variant under a perturbation (e.g. all gene_knockouts). For a KO, pair with mechanistic_scope: a 'viable' verdict can be a model_UNDER_predicts case (essential in vivo, viable in silico).",
     "input_schema": {"type": "object", "properties": {"perturbation": {"type": "string"}, "condition": {"type": "string"}}, "required": ["perturbation"]}},
    {"name": "reroute_diagnosis", "description": "For a VIABLE metabolic KO, is the 'no phenotype' a genuine reroute or a MATHEMATICAL ARTIFACT? Checks whether the KO'd enzyme's FBA flux is 0 in the KO yet nonzero in WT on a dividing cell — the model bypassing an enzyme real biology can't. `gene` = the KO'd symbol; `target` = its design label; `reference` = WT (default). Explains WHY a viable KO is viable and flags model_UNDER_predicts at the flux level.",
     "input_schema": {"type": "object", "properties": {"gene": {"type": "string"}, "target": {"type": "string"}, "reference": {"type": "string"}}, "required": ["gene", "target"]}},
    {"name": "check_feasibility", "description": "Check whether a SINGLE proposed experiment is inside the model's validated envelope. For a one-off design, call before proposing it. For a PANEL, skip this — propose_experiments vets every design's feasibility for you; do not check_feasibility design-by-design.",
     "input_schema": {"type": "object", "properties": _DESIGN_PROPS}},
    {"name": "vet_hypothesis", "description": "Vet a proposed experiment in one step. SAFETY (biosecurity) is the ONLY hard gate — `runnable` reflects safety alone. Out-of-sample / predicted-to-reroute / likely-to-fail hypotheses are ENCOURAGED (they are the genuine model tests). Feasibility + provenance + scope are ADVISORY (set expectations, never block). Pass `gene` for a KO to also get its prior + essentiality benchmark. Use this instead of chaining the guardrails by hand.",
     "input_schema": {"type": "object", "properties": {**_DESIGN_PROPS, "gene": {"type": "string", "description": "optional: the KO'd gene, to add its scope prior + benchmark"}}}},
    {"name": "model_validation", "description": "How well does the model predict gene essentiality vs the 402-gene ground-truth benchmark? Corpus-level agreement counts + the model_UNDER_predicts number, so you know when to trust a KO 'viable' verdict (mostly you can't, for essential-gene candidates). Call to calibrate trust before generalising a KO result.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "metabolic_essentiality", "description": "Metabolic-essentiality ORACLE for a gene — METABOLISM ONLY. Returns the authoritative Baba/Joyce benchmark verdict (the authority; the whole-cell homeostatic FBA under-predicts by rerouting) + the model's FBA structural check + KO prior. For a non-metabolic gene it says the FBA doesn't apply and points to the right axis (machinery->viability, TF->mechanistic_scope). Use for 'is this METABOLIC gene essential?'.",
     "input_schema": {"type": "object", "properties": {"gene": {"type": "string"}}, "required": ["gene"]}},
    {"name": "power_check", "description": "Is a comparison adequately powered? Uses the corpus's observed per-design replicate CV for a channel to estimate the minimum detectable effect at n_seeds and the seeds needed for a target effect (two-sample, alpha .05, power .8). Use before reading a null (no effect) as real — a KO 'no growth effect' below min_detectable_effect is under-powered, not proven equivalent.",
     "input_schema": {"type": "object", "properties": {"channel": {"type": "string"}, "effect_pct": {"type": "number"}, "n_seeds": {"type": "integer"}}}},
    {"name": "use_skill", "description": "Load a vendored scientific Agent Skill (literature, MIT/K-Dense) to answer a LITERATURE question the corpus can't: 'paper-lookup' (10 APIs — PubMed/OpenAlex/bioRxiv/… with provenance), 'literature-review' (search + synthesise a cited brief), 'bgpt-paper-search' (structured methods/results/quality). Returns the skill's instructions + endpoint reference docs; then execute it with web_get. Use to check what's PUBLISHED, whether a grounded sim result agrees with the literature, and whether a finding is novel / wet-lab-worthy — the corpus stays the source of primary numbers; the literature is comparison only, always cited.",
     "input_schema": {"type": "object", "properties": {"name": {"type": "string", "description": "paper-lookup | literature-review | bgpt-paper-search"}}, "required": ["name"]}},
    {"name": "web_get", "description": "HTTP GET for the literature skills — allow-listed scientific hosts only (eutils.ncbi/PubMed, api.openalex.org, api.crossref.org, api.semanticscholar.org, export.arxiv.org, rest.uniprot.org, ...). Read the skill's reference doc (use_skill) for the exact endpoint + params first. Refuses any non-allow-listed host.",
     "input_schema": {"type": "object", "properties": {"url": {"type": "string"}, "headers": {"type": "object"}}, "required": ["url"]}},
    {"name": "screen_design", "description": "Biosecurity screen for a SINGLE proposed design (INTENT): flags engineering toward a misuse signature (AMR efflux up-regulation, toxin over-expression, virulence). Call for a one-off design before proposing it; for a PANEL, skip it — propose_experiments biosecurity-screens every design for you (it will block a flagged one).",
     "input_schema": {"type": "object", "properties": {"perturbation": {"type": "string"}, "condition": {"type": "string"},
                      "timeline": {"type": "string"}, "params": {"type": "object"}}}},
    {"name": "screen_phenotype", "description": "Phenotype-grounded biosecurity screen of a design's RESULTS (label 'perturbation/condition'): flags when the simulated proteome up-regulates a misuse signature (AMR efflux) vs a reference — catches an emergent AMR phenotype even if the design never named an efflux gene.",
     "input_schema": {"type": "object", "properties": {"target": {"type": "string"}, "reference": {"type": "string"}},
                      "required": ["target"]}},
    {"name": "run_experiment", "description": "Envelope- AND biosecurity-check a design and report whether it's already in the corpus. Enforces the guardrails; does not launch heavy sims per query.",
     "input_schema": {"type": "object", "properties": _DESIGN_PROPS}},
    {"name": "propose_experiment", "description": "PROPOSE a NEW experiment to run when the corpus lacks the data you need. Cellwright CANNOT launch sims itself — the design is vetted (safety-gated) and QUEUED pending HUMAN approval; after a human approves and it runs, the result is indexed so you can analyse it. Call design_space first to resolve gene symbols. Single-gene KO: perturbation='gene_knockout' + gene='pfkA'. MULTI-gene KO (e.g. a synthetic-lethal pair): perturbation='multi_gene_knockout' + genes=['pfkA','pfkB'] — the ko_indices are resolved for you, no need to guess indices. To CHANGE an argument on a draft you already proposed, use revise_experiment (NOT this — proposing again leaves a stale duplicate). Returns request id + vet result (pending_approval or blocked).",
     "input_schema": {"type": "object", "properties": {**_DESIGN_PROPS, "gene": {"type": "string", "description": "single KO gene (perturbation='gene_knockout') — also sets the scope prior"}, "genes": {"type": "array", "items": {"type": "string"}, "description": "gene SET for a multi_gene_knockout, e.g. ['pfkA','pfkB'] — each is resolved to its ko_index automatically"}}}},
    {"name": "propose_experiments", "description": "PROPOSE a WHOLE PANEL of experiments in ONE call — use this INSTEAD of many propose_experiment calls whenever you queue more than one design (e.g. the Socratic Council's full falsifier panel: a reference + N knockouts + the discriminating controls). One-at-a-time proposing burns the turn budget and can leave the panel HALF-queued with the discriminating controls dropped; this queues them atomically. Same vetting + human-approval airlock as propose_experiment. `designs` is a list; each item: {perturbation, condition?, timeline?, gene?, genes?, params?, seeds?, generations?}.",
     "input_schema": {"type": "object", "properties": {"designs": {"type": "array", "description": "the panel to queue", "items": {"type": "object", "properties": {**_DESIGN_PROPS, "gene": {"type": "string", "description": "single KO gene"}, "genes": {"type": "array", "items": {"type": "string"}, "description": "gene set for a multi_gene_knockout"}, "params": {"type": "object"}}}}}, "required": ["designs"]}},
    {"name": "revise_experiment", "description": "REVISE a PENDING experiment draft when the user asks to CHANGE an argument (more/fewer seeds, a different condition, a different gene set). This SUPERSEDES the old draft (no duplicate is left in the queue) and returns a re-vetted new draft pending human approval. Pass request_id plus ONLY the fields you're changing. Use THIS to change a draft — never propose_experiment again for the same intent.",
     "input_schema": {"type": "object", "properties": {"request_id": {"type": "string", "description": "the pending draft's req_ id"}, **_DESIGN_PROPS, "gene": {"type": "string"}, "genes": {"type": "array", "items": {"type": "string"}, "description": "new gene set for a multi_gene_knockout"}}, "required": ["request_id"]}},
]

_DISPATCH = {"survey_corpus": survey_corpus, "differential": differential, "top_movers": top_movers,
             "disconfirm": disconfirm, "coverage_check": coverage_check, "corpus_audit": corpus_audit,
             "data_availability": data_availability, "prune_candidates": prune_candidates, "provenance": provenance,
             "mechanistic_scope": mechanistic_scope, "viability": viability,
             "reroute_diagnosis": reroute_diagnosis,
             "list_results": list_results, "design_space": design_space,
             "read_series": read_series, "chart": chart, "list_species": list_species,
             "read_raw_series": read_raw_series, "variance_band": variance_band, "raw_available": raw_available,
             "download_raw": download_raw,
             "read_species": read_species, "screen_design": screen_design,
             "screen_phenotype": screen_phenotype,
             "check_feasibility": check_feasibility, "run_experiment": run_experiment,
             "vet_hypothesis": vet_hypothesis, "model_validation": model_validation, "power_check": power_check,
             "use_skill": use_skill, "web_get": web_get,
             "propose_experiment": propose_experiment, "propose_experiments": propose_experiments,
             "revise_experiment": revise_experiment,
             "metabolic_essentiality": metabolic_essentiality}


def dispatch(name: str, args: dict) -> dict:
    fn = _DISPATCH.get(name)
    if not fn:
        return {"error": f"unknown tool '{name}'"}
    try:
        return fn(**(args or {}))
    except TypeError as exc:
        return {"error": f"bad arguments for {name}: {exc}"}
