"""Host-side bridge to the container reader worker.

The model + TableReader live only in the wcEcoli image, so simOut reading runs there (see
`_reader_worker.py`) and we consume its JSON here. Docker mode bind-mounts the output dir + the worker
script into the image; native mode runs the worker directly (requires `wholecell` importable).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from . import deg_estimator, paths, redact

WCECOLI_DIR = os.environ.get("WCECOLI_DIR", "")
WCECOLI_DOCKER = os.environ.get("WCECOLI_DOCKER", "")
PY = os.environ.get("WCECOLI_PY", "python")
OUT_ROOT = Path(os.environ.get("CELLARIUM_OUT", "runs")).resolve()
_WORKER = Path(__file__).with_name("_reader_worker.py")


def _container_path(host_run_root: Path) -> str:
    """The run's path INSIDE the container, which exists only for runs under the mounted output root.

    AG-2 MEASURED 2026-09-08: `Path.relative_to` raises a bare `ValueError("... is not in the subpath of
    ...")`, and `reroute_diagnosis` and `regulon_response` surfaced exactly that string to the agent -- 4 of
    the 35 tool errors in the sweep. The run existed and was readable; it simply sat under `runs_seed_aars/`
    while `CELLARIUM_OUT` pointed at `runs/`, so the only mount (`{OUT_ROOT}:/wcEcoli/out`) could not see it.
    A Python-internal phrase cannot tell anyone that, which is this repo's recurring failure shape: a
    "could not read" reported as though it described the data. The condition is unchanged -- an unmountable
    path still cannot be read -- but the message now names both paths and the setting that reconciles them.
    """
    p = Path(host_run_root).resolve()
    try:
        rel = p.relative_to(OUT_ROOT)
    except ValueError:
        raise ValueError(
            f"run root {p} is outside the configured output root {OUT_ROOT}, so the reader container -- "
            f"which mounts only {OUT_ROOT} at /wcEcoli/out -- cannot see it. Point CELLARIUM_OUT at the "
            f"root that contains this run, or move the run under {OUT_ROOT}.") from None
    return "/wcEcoli/out/" + ("" if str(rel) == "." else str(rel).replace("\\", "/"))


def _reachable(roots, role: str) -> tuple[list[str], dict | None]:
    """Split run roots into the ones the reader mount can see and the ones it cannot, NAMING the misses.

    WHY THIS EXISTS RATHER THAN LETTING `_container_path` RAISE. The raise is correct for a single run — if
    you asked for THAT run, "cannot see it" is the answer. It is wrong for a SET: `wildtype/basal` has runs
    spread across four output trees on this machine (32 under `runs/`, 10 under `runs_kinetic_seeds/`,
    `runs_seed_aars/` and `runs_rebuild_p1/`), and one unreachable root aborted a comparison that 32
    reachable ones could have answered. Measured while running the acetate-vs-glucose RNA-seq concordance,
    which died on the first out-of-root reference seed.

    Dropping them silently would be worse than the crash, so this returns the omission alongside the paths:
    which roots, how many, which output trees they live under, and the setting that would include them. The
    caller attaches it to the result and REFUSES when too few survive — the PLAT-2 convention, applied to a
    dimension that had not been considered: not rows dropped for size, but runs dropped for reachability.
    """
    ok, missed = [], []
    for r in roots:
        try:
            ok.append(_container_path(Path(r)))
        except ValueError:
            missed.append(Path(r).resolve())
    if not missed:
        return ok, None
    trees = sorted({str(m).replace("\\", "/").split("/")[-4] if len(m.parts) >= 4 else str(m)
                    for m in missed})
    return ok, {
        "role": role,
        "n_reachable": len(ok),
        "n_unreachable": len(missed),
        "output_trees_not_mounted": trees,
        "runs": [str(m) for m in missed[:8]],
        "why": (f"the reader container mounts only {OUT_ROOT} at /wcEcoli/out, so runs under another "
                "output tree are invisible to it. They exist and are readable — they are not part of THIS "
                "comparison."),
        "how_to_include_them": "point CELLARIUM_OUT at a root that contains all of them, or move them under "
                               f"{OUT_ROOT}.",
    }


def _worker_cmd(mode: str, args: list[str]) -> list[str]:
    # mount the worker's dir (single-file binds are unreliable on Docker Desktop Windows) read-only
    return ["docker", "run", "--rm", "-v", f"{OUT_ROOT}:/wcEcoli/out",
            "-v", f"{_WORKER.parent}:/cellarium_reader:ro",
            "-e", "PYTHONPATH=/wcEcoli", "-w", "/wcEcoli", WCECOLI_DOCKER,
            "python", f"/cellarium_reader/{_WORKER.name}", mode, *args]


# A generous bound, because its only job is to turn a HANG into an answer: a real read of a large run takes
# minutes, an engine that never comes up takes forever. Measured 2026-11-20: with Docker Desktop mid-start,
# `docker run` blocked and the reader -- which then had no timeout at all -- hung for the full two minutes the
# shell allowed. Overridable for a corpus whose reads genuinely run longer.
READER_TIMEOUT_S = int(os.environ.get("CELLARIUM_READER_TIMEOUT_S", "1800"))

# The docker client's own wording for each failure, in both platform variants. The three causes are the ones
# `tests/conftest.py::_docker_reason` already told apart so the SUITE skipped correctly -- the production
# reader is held to the same standard here, rather than to a weaker one.
_ENGINE_DOWN = ("failed to connect to the docker api", "cannot connect to the docker daemon",
                "error during connect", "is the docker daemon running")
_IMAGE_ABSENT = ("unable to find image", "no such image", "pull access denied", "manifest unknown")


def _classify_docker_failure(stderr: str) -> str:
    """Which of the distinguishable causes a failed run's stderr names.

    `worker_fault` is the residual and it stays the honest default: a container that STARTED and then
    printed no JSON is our code's problem, and calling it an environment fault would hide real defects behind
    "start Docker".
    """
    s = (stderr or "").lower()
    if any(k in s for k in _ENGINE_DOWN):
        return "engine_unavailable"
    if any(k in s for k in _IMAGE_ABSENT):
        return "image_absent"
    return "worker_fault"


def _run_cmd(cmd: list[str], cwd: str | None) -> dict:
    """Run the reader worker and return its JSON, or an error that names the actual cause.

    BACKLOG M-13, MEASURED 2026-11-20. With the engine forced unreachable this returned "reader worker
    produced no JSON" while its own captured stderr read "failed to connect to the docker API ... check if
    the daemon is running". The cause was captured and nothing read it. And `errors.PATTERNS` routed that
    message to `runtime_fault`, remedy `report_defect` -- so the agent was told to report a bug in Cellarium
    when the fix was to start Docker. Each cause now gets its own message and its own reason code.
    """
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, env=redact.child_env(),
                              timeout=READER_TIMEOUT_S)
    except FileNotFoundError:
        return {"error": f"the {cmd[0]} client is not installed or not on PATH, so the reader container "
                         f"could not be started", "cause": "client_missing"}
    except subprocess.TimeoutExpired:
        return {"error": f"the reader worker did not finish within {READER_TIMEOUT_S} s -- the engine may be "
                         f"stalled, or the read is larger than the budget (CELLARIUM_READER_TIMEOUT_S raises "
                         f"it)", "cause": "timed_out"}
    for line in reversed(proc.stdout.splitlines()):
        if line.startswith("CELLARIUM_JSON:"):
            return json.loads(line[len("CELLARIUM_JSON:"):])
    tail = (proc.stderr or "")[-600:]
    cause = _classify_docker_failure(proc.stderr)
    msg = {
        "engine_unavailable": "the Docker engine is not responding, so the reader container could not "
                              "start -- start Docker Desktop (or the daemon) and retry. This is not a fault "
                              "in the reader",
        "image_absent": "the model image is not present on this machine, so the reader container could "
                        "not start -- build or pull it and retry",
        "worker_fault": "reader worker produced no JSON",
    }[cause]
    return {"error": msg, "cause": cause, "returncode": proc.returncode, "stderr": tail}


def _invoke(mode: str, host_run_root: Path, extra: list[str] | None = None) -> dict:
    extra = extra or []
    if WCECOLI_DOCKER:
        return _run_cmd(_worker_cmd(mode, [_container_path(host_run_root), *extra]), None)
    return _run_cmd([PY, str(_WORKER), mode, str(Path(host_run_root).resolve()), *extra], WCECOLI_DIR or None)


def read_run(host_run_root: Path) -> dict:
    return _invoke("run", host_run_root)


def gen_times(host_run_root: Path) -> dict:
    """Per-generation start/end time and chromosome count, read from raw simOut (item 4c)."""
    return _invoke("gen_times", host_run_root)


def viability(host_run_root: Path) -> dict:
    """Re-score a run by VIABILITY (does the lineage divide?) — the KO readout that doesn't reroute away like a
    graded growth channel. Aggregates the per-cell division signal (full_chromosome==2 + FBA-solver health) over
    seeds x generations into a run-level verdict (viable / impaired / inviable)."""
    return _invoke("viability", host_run_root)


def dump_schema(host_run_root: Path) -> dict:
    return _invoke("schema", host_run_root)


def read_species(host_run_root: Path, kind: str, species_id: str) -> dict:
    return _invoke("species", host_run_root, [kind, species_id])


def species_per_run(host_run_roots: list[Path], kind: str, species_ids: list[str]) -> dict:
    """Several species for several runs in one container call (`mode_species` per pair, last generation). Runs the
    reader mount cannot see are named in `_unreachable`, never silently dropped."""
    if WCECOLI_DOCKER:
        ok, missed = _reachable(host_run_roots, "runs")
        if not ok:
            return {"error": "no run is reachable by the reader container", "_unreachable": missed}
        out = _run_cmd(_worker_cmd("species_per_run", [",".join(ok), kind, ",".join(species_ids)]), None)
    else:
        roots = ",".join(str(Path(r).resolve()) for r in host_run_roots)
        out = _run_cmd([PY, str(_WORKER), "species_per_run", roots, kind, ",".join(species_ids)],
                       WCECOLI_DIR or None)
        missed = None
    if missed and isinstance(out, dict):
        out["_unreachable"] = missed
    return out


def channels_per_run(host_run_roots: list[Path], names: list[str]) -> dict:
    """Named summary channels for several runs in one container call (`mode_run`, last generation)."""
    if WCECOLI_DOCKER:
        ok, missed = _reachable(host_run_roots, "runs")
        if not ok:
            return {"error": "no run is reachable by the reader container", "_unreachable": missed}
        out = _run_cmd(_worker_cmd("channels_per_run", [",".join(ok), ",".join(names)]), None)
    else:
        roots = ",".join(str(Path(r).resolve()) for r in host_run_roots)
        out = _run_cmd([PY, str(_WORKER), "channels_per_run", roots, ",".join(names)], WCECOLI_DIR or None)
        missed = None
    if missed and isinstance(out, dict):
        out["_unreachable"] = missed
    return out


def initiation_mass(host_run_roots: list[Path]) -> dict:
    """BV-10: every replication initiation of each run (mass per origin before it, the critical mass used)."""
    if WCECOLI_DOCKER:
        ok, missed = _reachable(host_run_roots, "runs")
        if not ok:
            return {"error": "no run is reachable by the reader container", "_unreachable": missed}
        out = _run_cmd(_worker_cmd("initiation_mass", [",".join(ok)]), None)
    else:
        roots = ",".join(str(Path(r).resolve()) for r in host_run_roots)
        out = _run_cmd([PY, str(_WORKER), "initiation_mass", roots], WCECOLI_DIR or None)
        missed = None
    if missed and isinstance(out, dict):
        out["_unreachable"] = missed
    return out


def protein_noise(host_run_roots: list[Path], k: int = 5) -> dict:
    """BV-9: per-protein mean and CV2 over snapshot cells (k phases per generation), pooled over the runs given."""
    if WCECOLI_DOCKER:
        ok, missed = _reachable(host_run_roots, "runs")
        if not ok:
            return {"error": "no run is reachable by the reader container", "_unreachable": missed}
        out = _run_cmd(_worker_cmd("protein_noise", [",".join(ok), str(k)]), None)
    else:
        roots = ",".join(str(Path(r).resolve()) for r in host_run_roots)
        out = _run_cmd([PY, str(_WORKER), "protein_noise", roots, str(k)], WCECOLI_DIR or None)
        missed = None
    if missed and isinstance(out, dict):
        out["_unreachable"] = missed
    return out


def list_species(host_run_root: Path, kind: str, search: str = "") -> dict:
    return _invoke("list_species", host_run_root, [kind, search])


VARIANT_MAP_CACHE = paths.cache("variant_map.json")


def variant_map(sim_path: str = "cellarium") -> dict:
    """Gene-KO + condition index maps from sim_data (indices match the model's ordering). Heavy; cache it."""
    return _invoke("variant_map", OUT_ROOT / sim_path)


def kb_content_hash(sim_path: str = "cellarium") -> dict:
    """A hash of sim_data's CONTENT, stable across ParCa refits — unlike the file hash.

    `provenance.kb_provenance()["kb_sha256"]` hashes the pickle bytes and is therefore only sound in one
    direction: same hash => same kb, but a DIFFERENT hash does NOT mean a different experiment. Two fits of
    identical code produced different file hashes and bitwise-identical simulations (measured 2026-08-03).
    Use this when deciding whether two runs are comparable; use the file hash only to prove identity.

    Heavy — it unpickles sim_data and walks it. Cache the result."""
    return _invoke("kb_content_hash", OUT_ROOT / sim_path)


def deg_rate_provenance(sim_path: str = "cellarium", per_unit: bool = False) -> dict:
    """Is each mRNA degradation rate a FIT, a CONSTRAINT, or a population DEFAULT (PARCA-4)?

    RENAMED from `deg_rate_bounds`, which under-reported by ~3x. That name asked "which units sit on a bound",
    and answered 245 units / 4.59% of expression — but a unit whose cistrons were never measured does not sit
    on a bound at all: it is assigned `average_mRNA_cistron_half_life`, the MEAN of the reported half-lives.
    That class is larger (602 units, 7.48%), so the honest total is 847 of 3,133 units carrying 12.07% of
    transcription on a value that is not a fit. Reporting a third of that under a name that sounds complete is
    the failure this project keeps meeting; the name now says what it measures.

    `per_unit=True` additionally returns `units_not_a_fit` — the IDs in each of the three classes. Aggregate
    counts cannot score a candidate estimator: "did the units that were not fits improve" requires knowing
    WHICH units those were, so two fits can be intersected. Only the not-a-fit classes are listed; DETERMINED
    is their complement, which keeps it ~854 ids rather than 3,133. Off by default — the summary is what a
    human reads, and a thousand ids inside it is not a summary.

    Heavy (unpickles sim_data); cache it.
    """
    return _invoke("deg_rate_provenance", OUT_ROOT / sim_path, ["1"] if per_unit else None)


def deg_rate_units(sim_path: str = "cellarium") -> dict:
    """BV-8: every mRNA unit's final half-life with its class (fit, floor, ceiling, imputed) and every mRNA
    cistron's input half-life, with gene symbols. Heavy (unpickles sim_data twice)."""
    return _invoke("deg_rate_units", OUT_ROOT / sim_path)


DEG_RATE_VARIANTS = ("baseline", "ridge", "per_unit_bound", "hierarchical")
# Only these two carry a hyper-parameter, so only these two can be nested-tuned. Read from the
# estimator module rather than restated here: a second copy of the list is a second thing to
# forget to update.
TUNABLE_VARIANTS = tuple(deg_estimator.PARAM_GRIDS)


def deg_rate_resolve(sim_path: str = "cellarium", variant: str = "baseline",
                     param: float | str | None = None) -> dict:
    """Re-solve the degradation-rate estimator OFFLINE against a knowledge base (PARCA-4 Stage 2).

    The estimator is one nonnegative least-squares problem, and every input to it is in `sim_data` or
    recomputable from it — so a candidate estimator can be evaluated in a couple of minutes instead of a
    7-minute ParCa rebuild plus a comparability arm. That is the whole reason PARCA-4 is affordable to work
    on at all.

    Variants: `baseline` (the shipped procedure re-run here), `ridge` (soft prior instead of a hard floor,
    `param`=lambda), `per_unit_bound` (each TU floored by its own measured cistrons), `hierarchical`
    (unmeasured cistrons imputed from their operon, `param`=kappa).

    ALWAYS COMPARE A VARIANT AGAINST `variant="baseline"`, NOT against the shipped `deg_rate` vector. ParCa
    overwrites `cistron_expression['basal']` after the estimator runs (`fit_sim_data_1.py:964`), so the
    estimator's own input is not preserved in the artifact and the re-solve reconstructs it from the post-fit
    vector. That reproduces the shipped fit on 3,270 of 3,276 units, and every payload carries a `fidelity`
    block reporting the gap — but only the baseline re-solve shares a variant's inputs exactly.

    DESCRIPTIVE, NOT A SCORE. Any scheme can manufacture distinct values, so a point mass disappearing is not
    evidence of a better estimator. Held-out predictive accuracy is Stage 3.

    Heavy (unpickles sim_data and re-solves ~2,900 NNLS blocks); expect a minute or two.
    """
    if variant not in DEG_RATE_VARIANTS:
        return {"error": f"unknown variant {variant!r}; expected one of {list(DEG_RATE_VARIANTS)}"}
    return _invoke("deg_rate_resolve", OUT_ROOT / sim_path,
                   [variant, "" if param is None else str(param)])


def deg_rate_cv(sim_path: str = "cellarium", variant: str = "baseline", k: int = 10,
                param: float | str | None = None) -> dict:
    """Score a candidate degradation-rate estimator on measurements it never saw (PARCA-4 Stage 3).

    The protocol is pre-registered in BACKLOG.md and was committed before the first run: hold out a tenth of
    the 3,246 measured mRNA cistrons by a stable hash of their id, treat them as unmeasured EVERYWHERE
    (including in the global floor and in the imputation constant), re-solve, predict each held-out cistron
    as the abundance-weighted mixture of its units' rates, and score log2(predicted/measured).

    Held-out prediction rather than resolution, because any scheme can manufacture distinct values: add noise
    and every point mass disappears while the fit gets worse. Only predicting a measurement the fit never saw
    separates a more informative estimator from a more decorated one.

    Returns the variant's scores, the BASELINE's scores on the identical folds, a paired comparison (the same
    cistrons are scored by both, so the pairing is free and much stronger than comparing two medians), and
    `imputation_only_scores` — what the population mean alone would have predicted, which is the error the
    1,100 genuinely unmeasured cistrons carry with nothing marking it.

    ~10 s per variant once sim_data is unpickled; the cost is the unpickle, not the solves.
    """
    if variant not in DEG_RATE_VARIANTS:
        return {"error": f"unknown variant {variant!r}; expected one of {list(DEG_RATE_VARIANTS)}"}
    return _invoke("deg_rate_cv", OUT_ROOT / sim_path,
                   [variant, str(int(k)), "" if param is None else str(param)])


def deg_rate_nested_cv(sim_path: str = "cellarium", variant: str = "hierarchical",
                       k: int = 10, k_inner: int = 5) -> dict:
    """Tune a variant's hyper-parameter without letting it see the data it is scored on (PARCA-4 Stage 3b).

    Stage 3 ran `hierarchical` at kappa=5 and never tuned it. Running the Stage 3 cross-validation at several
    kappa and reporting the best would be a selection leak — the parameter chosen using the measurements it
    is then scored on. Here the OUTER folds are Stage 3's, bit-identical, and an independent inner split
    inside each outer training set picks kappa from the pre-registered grid before the outer fold is touched.

    Returns the nested score, the baseline on the identical folds, a paired comparison, kappa* PER OUTER FOLD
    (if it moves every fold, "the best kappa" is not a stable quantity whatever the score says), and the
    naive score the un-nested procedure would have reported, so the selection optimism is measured rather
    than asserted.

    ~45 s: k_outer x k_inner x |grid| solves.
    """
    if variant not in TUNABLE_VARIANTS:
        return {"error": f"{variant!r} has no hyper-parameter to tune; tunable variants are "
                         f"{list(TUNABLE_VARIANTS)}"}
    return _invoke("deg_rate_nested_cv", OUT_ROOT / sim_path, [variant, str(int(k)), str(int(k_inner))])


PROVENANCE_BASELINE = "data/parca/deg_rate_baseline.json"


def write_provenance_baseline(sim_path: str = "cellarium", path: str = PROVENANCE_BASELINE) -> dict:
    """Freeze the current fit's provenance as a COMMITTED reference for Stage 3 to score against.

    Without this, "compare the candidate against the current fit" means whatever `runs/cellarium/kb` happens
    to hold on the day — and that path is rebuilt (KB-ROOT-1 and the PARCA-3 gate both exist because it is).
    Two candidates evaluated a month apart would then be scored against different references with nothing
    saying so, which is the comparability problem ARM-1 solved for runs, one level down at the parameters.

    The snapshot therefore records the `kb_sha256` it describes. A baseline that cannot name its own fit is
    the same defect it exists to prevent.
    """
    import json
    import os

    from . import manifest
    r = deg_rate_provenance(sim_path, per_unit=True)
    if "error" in r:
        return r
    kb = (manifest._kb_prov(sim_path) or {}).get("kb_sha256")
    out = {"kb_sha256": kb, "sim_path": sim_path, "generated_by": "reader.write_provenance_baseline",
           "why": ("The reference Stage 3 scores candidate estimators against. Regenerate ONLY with a "
                   "deliberate decision to move the baseline, and say which kb_sha256 it moved to — a "
                   "silently-updated baseline makes every past comparison unreproducible."),
           **r}
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    return {"path": path, "kb_sha256": kb, "n_mrna_units": r["n_mrna_units"],
            "not_a_fit_pct_expression": r["not_a_fit"]["pct_expression"]}


def read_provenance_baseline(path: str = PROVENANCE_BASELINE) -> dict:
    """The committed baseline. Readable WITHOUT the model image — that is half its value: CI can check the
    reference is well-formed and names its fit even where it cannot unpickle sim_data."""
    import json
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:
        return {"error": f"no readable baseline at {path}: {exc}"}


def provenance_delta(fit_a: str, fit_b: str) -> dict:
    """Score one knowledge base's degradation table against another: what got RESCUED, what REGRESSED.

    THE Stage-3 primitive. Every candidate estimator is judged by this question — "did the units that were not
    fits become fits, and at what cost elsewhere" — so it lives in one function rather than being re-derived
    per caller. Two implementations of a set intersection that differ by one class (forgetting `ceiling`, say)
    would score two candidates under different rules with nothing saying so.

    Reported BOTH ways, because they disagree and the disagreement is the point. Measured on the corpus fit vs
    `refit2` (the declined coverage filter): 1 unit rescued against 45 regressed, which by expression is
    +3.295 percentage points. A count ratio of 45:1 and a mass of 3.3pp are different sentences, and the
    acceptance criteria are written in the second.

    WHICH FIT'S EXPRESSION WEIGHTS A UNIT. A rescued unit is weighted by its expression in `fit_a`, where it
    was still not-a-fit; a regressed unit by its expression in `fit_b`, where it now is. Expression is refit
    too, so the two differ — and weighting a unit by the fit in which it is BROKEN is what answers "how much
    transcription is resting on a non-fit", which is the question. Stated because the other choice is
    defensible and would give a different number.
    """
    a, b = deg_rate_provenance(fit_a, per_unit=True), deg_rate_provenance(fit_b, per_unit=True)
    for name, r in ((fit_a, a), (fit_b, b)):
        if "error" in r:
            return {"error": f"{name}: {r['error']}"}
    CLASSES = ("floor", "ceiling", "imputed")

    def flat(r):
        out = {}
        for c in CLASSES:
            out.update(r["units_not_a_fit"][c])
        return out

    wa, wb = flat(a), flat(b)
    A, B = set(wa), set(wb)
    rescued, regressed, both = A - B, B - A, A & B
    return {
        "fit_a": fit_a, "fit_b": fit_b,
        "rescued": {"n": len(rescued), "pct_expression_in_a": round(sum(wa[i] for i in rescued), 4),
                    "ids": sorted(rescued)[:40]},
        "regressed": {"n": len(regressed), "pct_expression_in_b": round(sum(wb[i] for i in regressed), 4),
                      "ids": sorted(regressed)[:40]},
        "not_a_fit_in_both": {"n": len(both)},
        "totals": {"not_a_fit_a": len(A), "not_a_fit_b": len(B), "net_units": len(B) - len(A),
                   "pct_expression_a": a["not_a_fit"]["pct_expression"],
                   "pct_expression_b": b["not_a_fit"]["pct_expression"],
                   "net_pct_expression": round(b["not_a_fit"]["pct_expression"]
                                               - a["not_a_fit"]["pct_expression"], 4)},
        "verdict": ("fit_b has FEWER units resting on a non-fit" if len(B) < len(A) else
                    "fit_b has MORE units resting on a non-fit" if len(B) > len(A) else
                    "no change in unit count"),
        "note": ("Counts and expression can disagree; read both. A variant that rescues few units but "
                 "high-expression ones may beat one that rescues many trivial ones, which is why the "
                 "acceptance criteria are written in expression terms."),
    }


def gene_map(sim_path: str = "cellarium") -> dict:
    """{symbol: monomer_id} from sim_data — for resolving the curated pathway panel. Heavy; cache it."""
    return _invoke("gene_map", OUT_ROOT / sim_path)


def gene_scope(sim_path: str = "cellarium") -> dict:
    """Per-gene mechanistic classification (is_metabolic / is_tf) + KO index from sim_data. Heavy; cache it."""
    return _invoke("gene_scope", OUT_ROOT / sim_path)


def fba_essentiality(genes: list[str], sim_path: str = "cellarium") -> dict:
    """DEPRECATED — under-sensitive (0/35 essential); NOT an essentiality oracle. The homeostatic FBA objective has
    no growth term, so it reroutes around every single-deletion. For an essentiality verdict use the ground-truth
    `essential_reference` flag in gene_scope (Baba/Joyce); for a measurable in-silico effect use a graded-capacity
    perturbation. Kept for the D4 finding; returns {"deprecated": True, "warning": ...}."""
    return _invoke("fba_essentiality", OUT_ROOT / sim_path, [",".join(genes)])


def _reachable_sides(target_roots, ref_roots) -> tuple[list[str], list[str], list[dict], dict | None]:
    """Both sides of a set comparison through `_reachable`, with the evidential floor applied to what survives.

    Returns (targets, references, omissions, refusal). A refusal is returned when either side keeps fewer than
    `support.MIN_SEEDS` reachable runs, so a comparison never answers from one run because the others were
    out of the mount. Shared by every reader that takes two run SETS: `gene_lfc` had this alone until
    2026-11-24, when `differential` (behind `top_movers` and `regulon_response`) aborted the arabinose
    re-derivation on one `wildtype/basal` seed under `runs_seed_aars/`.
    """
    from . import support
    t_ok, t_miss = _reachable(target_roots, "target")
    r_ok, r_miss = _reachable(ref_roots, "reference")
    omitted = [x for x in (t_miss, r_miss) if x]
    floor_n = getattr(support, "MIN_SEEDS", 2)
    for side, reachable in (("target", t_ok), ("reference", r_ok)):
        if len(reachable) < floor_n:
            return t_ok, r_ok, omitted, {
                "error": f"only {len(reachable)} {side} run(s) are reachable by the reader container, "
                         f"below the evidential floor of {floor_n} seeds — refusing at this scope "
                         "rather than answering from one run.",
                "unreachable": omitted}
    return t_ok, r_ok, omitted, None


def _with_omissions(out, omitted: list[dict]):
    if omitted and isinstance(out, dict):
        out["_unreachable_runs"] = omitted   # the omission rides ON the payload, never as a side note
    return out


def reroute_diagnosis(gene: str, ko_roots: list[Path], wt_roots: list[Path]) -> dict:
    """Diagnose a viable metabolic KO: is its 'reroute' a mathematical artifact (enzyme FBA flux = 0 in the KO yet
    nonzero in WT, on a viable cell)? Seed-averaged over the gene's own reactions, computed in the container."""
    if WCECOLI_DOCKER:
        k_ok, w_ok, omitted, refusal = _reachable_sides(ko_roots, wt_roots)
        if refusal:
            return refusal
        out = _run_cmd(_worker_cmd("reroute_diagnosis", [gene, ",".join(k_ok), ",".join(w_ok)]), None)
        return _with_omissions(out, omitted)
    k = ",".join(str(Path(r).resolve()) for r in ko_roots)
    w = ",".join(str(Path(r).resolve()) for r in wt_roots)
    return _run_cmd([PY, str(_WORKER), "reroute_diagnosis", gene, k, w], WCECOLI_DIR or None)


def differential(target_roots: list[Path], ref_roots: list[Path], kind: str = "protein",
                 top: int = 12, floor: float = 20.0) -> dict:
    """Seed-aware per-species fold-change: ALL target runs vs ALL reference runs (count-floored, reproducibility
    reported), computed in the container."""
    if WCECOLI_DOCKER:
        t_ok, r_ok, omitted, refusal = _reachable_sides(target_roots, ref_roots)
        if refusal:
            return refusal
        out = _run_cmd(_worker_cmd("differential", [",".join(t_ok), ",".join(r_ok), kind, str(top), str(floor)]),
                       None)
        return _with_omissions(out, omitted)
    t = ",".join(str(Path(r).resolve()) for r in target_roots)
    r = ",".join(str(Path(r).resolve()) for r in ref_roots)
    return _run_cmd([PY, str(_WORKER), "differential", t, r, kind, str(top), str(floor)], WCECOLI_DIR or None)


def gene_lfc(target_roots: list[Path], ref_roots: list[Path], kind: str = "mrna", floor: float = 20.0) -> dict:
    """All-gene seed-mean log2fc (SCI-2c): the FULL-distribution reader (every gene, not just the significant
    movers) for the sim-vs-RNA-seq concordance, computed in the container. Mirrors differential()."""
    if WCECOLI_DOCKER:
        t_ok, r_ok, omitted, refusal = _reachable_sides(target_roots, ref_roots)
        if refusal:
            return refusal
        out = _run_cmd(_worker_cmd("gene_lfc", [",".join(t_ok), ",".join(r_ok), kind, str(floor)]), None)
        return _with_omissions(out, omitted)
    t = ",".join(str(Path(r).resolve()) for r in target_roots)
    r = ",".join(str(Path(r).resolve()) for r in ref_roots)
    return _run_cmd([PY, str(_WORKER), "gene_lfc", t, r, kind, str(floor)], WCECOLI_DIR or None)


if __name__ == "__main__":  # schema dump (default) or `--variant-map` to derive + cache the KO/condition map
    import argparse

    ap = argparse.ArgumentParser(description="Inspect the model via the container reader.")
    ap.add_argument("--variant-map", action="store_true", help="dump + cache gene-KO/condition index maps")
    args = ap.parse_args()
    if args.variant_map:
        m = variant_map()
        if "error" not in m:
            VARIANT_MAP_CACHE.parent.mkdir(parents=True, exist_ok=True)
            VARIANT_MAP_CACHE.write_text(json.dumps(m), encoding="utf-8")
        preview = {k: (f"[{len(v)} genes -> cached]" if k == "genes" else v) for k, v in m.items()}
        print(json.dumps(preview, indent=2))
    else:
        print(json.dumps(dump_schema(OUT_ROOT), indent=2))
