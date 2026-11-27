"""Close-the-loop with a HUMAN APPROVAL GATE.

Cellwright PROPOSES experiments (the `propose_experiment` tool); each is vetted (safety is the only hard gate) and
queued as PENDING. Only a human approval — `approve_and_run`, which is NOT an agent tool; the hackathon interface
calls it — actually launches sims. After a run the data is indexed (record_existing) so Cellwright can reason over it.
Cellwright can never launch autonomously: the queue is the airlock.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

from . import atomic
from .capability import DEFAULT_MODE
from .model import Design

# AG-1: root the queue at an ABSOLUTE, config-rooted path (env override, else the repo root derived from this file),
# not a CWD-relative 'data/...' — a job launched from a script run in a different directory used to write a stray
# queue the server never saw. src/cellarium/launch.py -> parents[2] is the repo root.
_ROOT = Path(__file__).resolve().parents[2]
QUEUE = Path(os.environ.get("CELLARIUM_QUEUE") or (_ROOT / "data" / "launch_queue.json"))

# AG-1: the queue was a LOCK-FREE read-modify-write — the server handles requests on threads (propose/revise/stamp/
# approve) and reconcile() runs at boot, so two concurrent load->mutate->save cycles could lose an update. A
# re-entrant lock serializes every mutation in-process (the only writer process); `_save` writes atomically
# (temp + os.replace), so even a crash mid-write, or a stray second process, can never leave a half-written queue
# (worst case is last-writer-wins, never corruption). Reads stay lock-free — os.replace means a reader always sees
# a complete file, old or new.
_LOCK = threading.RLock()


def _load() -> list[dict]:
    return json.loads(QUEUE.read_text(encoding="utf-8")) if QUEUE.exists() else []


# Windows refuses a rename onto a file that another process holds open for a moment, with "Access is denied"
# (PermissionError). The holder is usually a scanner or indexer, never this process (writes are serialized by
# _LOCK), and it lets go within milliseconds. Found 2026-11-23: two tests in tests/test_launch.py failed this way,
# intermittently, in separate full runs. So the rename is retried briefly on that one error; any other error, or
# one that outlasts the retries, still raises.
def _save(q: list[dict]) -> None:
    QUEUE.parent.mkdir(parents=True, exist_ok=True)
    tmp = QUEUE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(q, indent=2), encoding="utf-8")
    atomic.replace(tmp, QUEUE)   # atomic on POSIX + Windows — no half-written queue, ever


@contextlib.contextmanager
def _txn():
    """One atomic read-modify-write of the queue: hold the lock, load, hand the caller the list to mutate IN PLACE,
    then save. Serializes concurrent mutators so no update is lost. Use for single-step mutations; multi-step flows
    (revise, approve_and_run) hold `_LOCK` explicitly so they can release it around a long sim."""
    with _LOCK:
        q = _load()
        yield q
        _save(q)


def _resolve_ko(perturbation: str, params: dict | None, gene: str | None) -> tuple[dict, str | None]:
    """A gene KO runs on a variant INDEX, not a symbol: the runner reads params['variant_index'] / ['ko_indices']
    and IGNORES a symbolic 'target_genes'. Left unresolved, _variant_index falls back to a content HASH and the
    model silently knocks out the wrong gene. So resolve target gene(s) -> ko_index here (via scope), for BOTH
    interface- and agent-proposed designs. Returns (params_with_index, error_or_None); refuses if unresolvable."""
    params = dict(params or {})
    if perturbation not in ("gene_knockout", "multi_gene_knockout"):
        return params, None
    if "variant_index" in params or "ko_indices" in params:   # already correctly indexed — trust it
        return params, None
    genes = list(params.get("target_genes") or ([gene] if gene else []))
    if not genes:
        return params, f"{perturbation} needs a target gene (params.target_genes or gene=)."
    from . import scope
    idxs: list[int] = []
    for g in genes:
        ix = scope.classify_gene(g).get("ko_index")
        if ix is None:
            return params, f"could not resolve ko_index for gene '{g}' — check the symbol (design_space resolves it)."
        idxs.append(int(ix))
    params["target_genes"] = genes                            # keep the symbol for provenance
    if perturbation == "multi_gene_knockout":
        params["ko_indices"] = idxs
    else:
        params["variant_index"] = idxs[0]
    return params, None


def declared_params() -> set[str]:
    """The design parameters Cellarium reads: those its manifest declares as identity axes or as derived values. One
    source, so a parameter added to the runner without a declaration is refused here rather than silently queued."""
    from . import manifest
    return {k.split(".", 1)[1] for k in (*manifest.IDENTITY_AXES, *manifest.NOT_IDENTITY_AXES) if k.startswith("params.")}


def _check_vocabulary(params: dict | None) -> str | None:
    """2026-11-27 (discovery S1): an undeclared parameter is read by nothing that decides what a run IS, so the run
    would execute without it while the queue, and the person approving, saw it."""
    unknown = sorted(set(params or {}) - declared_params())
    if not unknown:
        return None
    return (f"params {unknown} are not read by anything that decides what a run is (the runner, its label or its "
            f"directory), so the run would execute without them while the queue showed them. Accepted params: "
            f"{sorted(declared_params())}.")


def _resolve_graded(perturbation: str, condition: str | None, params: dict,
                    gene: str | None) -> tuple[str | None, dict, str | None]:
    """A graded knockdown runs on `gene_ko_index * 10 + level` and the runner reads its gene from the condition
    ('KO:<gene>'). Resolve both from the design, or refuse with what is missing. Returns (condition, params, error)."""
    if perturbation != "graded_gene_knockout":
        return condition, params, None
    from . import factors, model, scope
    params = dict(params)
    # the knockout genes a condition names, through the fact's one registered reader (conformance family 9)
    from_condition = model.knockout_genes(f"{perturbation}/{condition or ''}")
    genes = list(params.get("target_genes") or ([gene] if gene else []) or from_condition)
    if len(genes) != 1:
        return condition, params, ("graded_gene_knockout suppresses one gene: name it as condition 'KO:<gene>' or "
                                    "params.target_genes [<gene>].")
    # level 1 is expression 0, a FULL knockout: "1: 0" alone was read as "no knockdown" (discovery S2, 2026-11-27)
    table = ", ".join(f"{k}: {v:g}" + (" (a full knockout)" if v == 0 else "")
                      for k, v in sorted(factors.GRADED_FACTORS.items()))
    level = params.get("level")
    if "variant_index" in params and level is None:
        level = int(params["variant_index"]) % 10
    if level not in factors.GRADED_FACTORS:
        return condition, params, (f"graded_gene_knockout needs params.level, which sets the gene's expression as a "
                                   f"fraction of wild type ({table}); got level={level!r}.")
    ix = scope.classify_gene(genes[0]).get("ko_index")
    if ix is None:
        return condition, params, f"could not resolve ko_index for gene '{genes[0]}' (design_space resolves it)."
    params.update(target_genes=genes, level=int(level), variant_index=int(ix) * 10 + int(level))
    return f"KO:{genes[0]}", params, None


# D24 (2026-11-27): variants that read their index as a MEANING (a gene, a dose, a condition, a factor). A design that
# reaches the runner without one runs on a content hash, which for these is a wrong experiment or a crash.
# `multi_gene_knockout` carries `ko_indices` instead and is resolved by `_resolve_ko`.
INDEXED_FAMILIES = ("gene_knockout", "graded_gene_knockout", "rrna_operon_knockout", "ppgpp_conc", "condition",
                    "tf_activity")
# upstream ppgpp_conc's own tables (models/ecoli/sim/variants/ppgpp_conc.py::FACTORS, CONDITIONS): index =
# group * len(multipliers) + the multiplier's position
PPGPP_MULTIPLIERS = (0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0)
PPGPP_GROUPS = ("basal", "with_aa")


def _resolve_indexed(perturbation: str, condition: str | None, timeline: str | None,
                     params: dict) -> tuple[str | None, dict, str | None]:
    """The index of an rRNA-operon knockout or a ppGpp clamp from the parameters that name it, and a refusal for any
    indexed family still without one. Returns (condition, params, error)."""
    params = dict(params)
    # The dose of these two families lives in the condition string ('minimal|rRNA_KO:4op', 'basal|ppGpp:1x'), which is
    # what labels them (factors.parse). So the condition is derived from the index EVEN WHEN the index is given: S4b's
    # re-proposal passed it with condition 'basal', and its 2-, 4- and 6-operon arms would have shared one label.
    if perturbation == "rrna_operon_knockout":
        n = params.get("num_operons_to_delete")
        if "variant_index" not in params:
            if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= 6:
                return condition, params, ("rrna_operon_knockout needs params.num_operons_to_delete, 1 to 6 (the "
                                           "variant removes that many of the seven operons, in minimal medium); "
                                           f"got {n!r}.")
            params["variant_index"] = n
        vi = int(params["variant_index"])
        if vi > 6 and timeline:
            return condition, params, (f"rrna_operon_knockout index {vi} sets the variant's own medium and timeline "
                                       "(7-12 rich, 13-18 a shift to rich), which override the design's timeline, so "
                                       "the shift would never happen. Use 1-6 with the timeline, and "
                                       "params.initial_condition for the physiology the cell starts in.")
        if 1 <= vi <= 6:
            if n is not None and n != vi:
                return condition, params, (f"params.num_operons_to_delete {n!r} and variant_index {vi} disagree; the "
                                           f"variant removes index operons (1-6).")
            params["num_operons_to_delete"] = vi
            condition = f"minimal|rRNA_KO:{vi}op"
    elif perturbation == "ppgpp_conc":
        m = params.get("multiplier")
        if "variant_index" not in params:
            group = (condition or "basal").split("|")[0]
            hit = [i for i, f in enumerate(PPGPP_MULTIPLIERS)
                   if isinstance(m, (int, float)) and not isinstance(m, bool) and abs(f - float(m)) < 1e-9]
            if group not in PPGPP_GROUPS or not hit:
                return condition, params, (f"ppgpp_conc needs a condition in {list(PPGPP_GROUPS)} and "
                                           f"params.multiplier from the variant's table {list(PPGPP_MULTIPLIERS)} "
                                           f"(1.0 holds ppGpp at the condition's fitted level); got {group!r}, {m!r}.")
            params["variant_index"] = PPGPP_GROUPS.index(group) * len(PPGPP_MULTIPLIERS) + hit[0]
        vi = int(params["variant_index"])
        if not 0 <= vi < len(PPGPP_GROUPS) * len(PPGPP_MULTIPLIERS):
            return condition, params, f"ppgpp_conc index {vi} is outside the variant's table (0 to 19)."
        group, mult = PPGPP_GROUPS[vi // len(PPGPP_MULTIPLIERS)], PPGPP_MULTIPLIERS[vi % len(PPGPP_MULTIPLIERS)]
        if m is not None and abs(float(m) - mult) > 1e-9:
            return condition, params, f"params.multiplier {m!r} and variant_index {vi} ({mult:g}x) disagree."
        params["multiplier"] = mult
        condition = f"{group}|ppGpp:{mult:g}x"
    return condition, params, None


def propose(perturbation: str = "wildtype", condition: str | None = None, timeline: str | None = None,
            params: dict | None = None, seeds: int = 4, generations: int = 4, gene: str | None = None,
            elongation_model: str = DEFAULT_MODE) -> dict:
    """Vet + queue a proposed experiment. Never runs. A safety-flagged design is queued 'blocked'; otherwise
    'pending_approval'. A gene KO with no resolvable index is REFUSED (not queued) so we never run the wrong gene.
    Returns the request (with the full vet result).

    `elongation_model` is stored ON the queued design rather than assumed at approval time. The airlock's whole
    purpose is that what a human approves and what executes cannot differ, and an axis the queue cannot carry
    is an axis on which they silently do."""
    from . import tools
    err = _check_vocabulary(params)
    if err:
        return {"status": "unresolved", "error": err,
                "note": "drop or rename the parameter; nothing was queued."}
    condition, params, err = _resolve_graded(perturbation, condition, dict(params or {}), gene)
    if err:
        return {"status": "unresolved", "error": err, "note": "nothing was queued."}
    condition, params, err = _resolve_indexed(perturbation, condition, timeline, params)
    if err:
        return {"status": "unresolved", "error": err, "note": "nothing was queued."}
    params, err = _resolve_ko(perturbation, params, gene)
    if err:
        return {"status": "unresolved", "error": err,
                "note": "gene_knockout runs on a variant index; resolve the gene -> ko_index (design_space) first."}
    if perturbation in INDEXED_FAMILIES and "variant_index" not in params:
        return {"status": "unresolved", "note": "nothing was queued.",
                "error": (f"{perturbation} reads its variant index as a meaning (a condition, a factor, a dose), so "
                          f"a design without params.variant_index would run on a content hash. Give it: "
                          f"design_space lists the conditions with their indices.")}
    vet = tools.vet_hypothesis(perturbation, condition, timeline, params, gene, elongation_model)
    req = {"id": "req_" + uuid.uuid4().hex[:8],
           "status": "blocked" if not vet.get("runnable") else "pending_approval",
           "design": {"perturbation": perturbation, "condition": condition, "timeline": timeline,
                      "params": params or {}, "elongation_model": elongation_model},
           "seeds": seeds, "generations": generations, "vet": vet, "ts": time.time()}
    with _txn() as q:
        q.append(req)
    return {"request_id": req["id"], "status": req["status"], "runnable": vet.get("runnable"),
            "recommendation": vet.get("recommendation"), "vet": vet,
            "note": ("SAFETY-BLOCKED — will not run without human override." if req["status"] == "blocked"
                     else "Queued PENDING human approval — Cellwright cannot launch; a human approves via the interface.")}


def kb_dependents(sim_path: str) -> dict:
    """Live corpus rows whose `kb_sha256` is the knowledge base CURRENTLY at `sim_path`.

    The gate for PARCA-3. ParCa writes to `runs/<sim_path>/kb/simData.cPickle` and OVERWRITES whatever is
    there, so a rebuild at an occupied path replaces the fit that existing rows point at — and a row whose
    parameters no longer exist anywhere cannot be compared against anything, including later runs of its own
    arm. Nothing in the model warns; the rebuild simply succeeds.

    CORRECTION 2026-08-08: this docstring cited "18 analysable rows already orphaned at `cellarium`" as
    evidence that the failure had happened. **It had not.** That reading came from `_sim_path_of`, which
    returns only the second path component and so collapses `runs/`, `runs_seed_aars/`, `runs_kinetic_seeds/`
    and `runs_depleting/` onto the single key `cellarium`. Each of those roots holds its OWN knowledge base;
    read root-aware (`manifest.kb_sha_for_run`), 297 of 297 rows whose kb is still on disk agree with their
    own row and none mismatches. The hazard this gate prevents is real and unchanged — overwriting a kb in use
    would destroy it — but it is PROSPECTIVE, not a past incident, and saying otherwise overstated the case.
    """
    from . import manifest, survey
    try:
        # arm="all" is deliberate here: this counts what DEPENDS on a knowledge base across every arm, which
        # is a coverage question about the corpus rather than a comparison within it.
        from . import hygiene
        rows, _ = hygiene.rows("analysis", arm="all")
        here = (manifest._kb_prov(sim_path) or {}).get("kb_sha256")
    except Exception as exc:
        return {"sim_path": sim_path, "error": str(exc)[:160], "n": 0, "kb_sha256": None}
    if not here:
        return {"sim_path": sim_path, "kb_sha256": None, "n": 0,
                "note": "no knowledge base at this path — building here orphans nothing"}
    dependents = [r for r in rows if r.get("kb_sha256") == here]
    return {"sim_path": sim_path, "kb_sha256": here, "n": len(dependents),
            "designs": sorted({survey.design_key(r) for r in dependents})[:12]}


def _free_sim_path(stem: str = "refit") -> str:
    """A destination that holds no knowledge base any live row depends on."""
    from . import manifest
    for n in range(1, 100):
        cand = f"{stem}{n}"
        if not (manifest._kb_prov(cand) or {}).get("kb_sha256"):
            return cand
    return f"{stem}_{uuid.uuid4().hex[:6]}"


def vet_rebuild(sim_path: str, operons: str = "on", retype_cistrons: dict | None = None) -> dict:
    """Vet a proposed knowledge-base rebuild. ONE hard gate: do not destroy a fit live rows depend on.

    Deliberately narrower than `vet_hypothesis`'s safety screen, because the hazard is different in kind. A
    rebuild runs no organism design — there is nothing to biosecurity-screen. What it CAN do is silently
    invalidate existing results, which no simulation can. So the hard gate is destination, and everything
    else — that this mints a NEW ARM whose rows are not poolable with the corpus, that operons is a ParCa-time
    option, that a rebuild with no edits is a reproducibility check rather than an experiment — is advisory,
    following the same principle as the simulation gate: safety blocks, epistemics inform.
    """
    # The destination is AGENT-SUPPLIED and becomes a directory name inside the mounted output tree, so it is
    # validated before it is used for anything — including before `kb_dependents` is asked about it. Two
    # reasons, and the second is the one that is easy to miss. `../../etc/evil` resolves to `out/../../etc/evil`
    # and writes 114 MB outside the tree. And a path that ALIASES a protected one — `./cellarium`,
    # `cellarium/.`, `a/../cellarium` — could read as a fresh destination to a string-compared gate while ParCa
    # writes to the corpus knowledge base. A strict charset closes both without having to reason about
    # normalisation on two operating systems.
    notes: list[str] = []
    runnable = True
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", str(sim_path or "")) or ".." in str(sim_path):
        return {"runnable": False, "sim_path": sim_path, "operons": operons,
                "retype_cistrons": dict(retype_cistrons or {}), "would_orphan": {"n": 0},
                "recommendation": "rebuild_refused",
                "notes": ["REFUSED: sim_path %r is not a plain name. It becomes a directory inside the model's "
                          "output tree, so a traversal would write outside it, and an alias of an existing path "
                          "would slip past the dependency check while ParCa overwrote a knowledge base in use. "
                          "Use letters, digits, '_', '-', '.'." % sim_path]}
    dep = kb_dependents(sim_path)
    if dep.get("n"):
        runnable = False
        notes.append("REFUSED: `%s` holds the knowledge base %s… that %d live corpus row(s) depend on. ParCa "
                     "OVERWRITES it, and a row whose fitted parameters no longer exist cannot be compared "
                     "against anything, including later runs of its own arm. Build at a fresh path."
                     % (sim_path, str(dep.get("kb_sha256"))[:8], dep["n"]))
    if operons not in ("on", "off"):
        runnable = False
        notes.append("REFUSED: operons must be 'on' or 'off' (a runParca-time option); got %r." % operons)
    elif operons == "off":
        notes.append("operons='off' is UNTESTED in this tree (BACKLOG OPERONS-1) and mints an arm with no "
                     "comparator: 366 of 366 live rows are operons='on'.")
    if retype_cistrons:
        notes.append("retypes %d cistron(s): %s. Rows are RETYPED, never deleted — deleting breaks referential "
                     "integrity and the build dies before any fitting."
                     % (len(retype_cistrons), ", ".join(sorted(retype_cistrons)[:6])))
    else:
        notes.append("no reconstruction edits: this rebuilds the SAME inputs, so it is a reproducibility check "
                     "(does ParCa give the same fit twice?), not an experiment.")
    notes.append("A rebuild MINTS A NEW ARM (kb_sha256 changes). Its runs are NOT poolable with the existing "
                 "corpus — budget the comparators, not just the rebuild.")
    return {"runnable": runnable, "sim_path": sim_path, "operons": operons,
            "retype_cistrons": dict(retype_cistrons or {}), "would_orphan": dep,
            "recommendation": "rebuild_ok" if runnable else "rebuild_refused", "notes": notes}


def propose_rebuild(reason: str, retype_cistrons: dict | None = None, operons: str = "on",
                    sim_path: str | None = None, cpus: int | None = None) -> dict:
    """PROPOSE a knowledge-base rebuild (PARCA-3). Never runs — queued behind the same human airlock as a sim.

    Cellwright could propose a SIMULATION but had no way to propose a REBUILD, so a whole class of question —
    "does this hold with the pseudogene reverted?" — was unreachable to the agent, and today's
    estimator-artefact finding needed 25 rebuilds launched by hand. A rebuild is ~7 minutes against hours for a
    campaign, which makes this the cheapest capability on the ARM/PARCA list.

    `reason` is REQUIRED and free text: a rebuild mints an arm, and an arm whose rationale is not recorded is
    the fragmentation this corpus already suffers from. `sim_path` defaults to the first free destination
    rather than to a name a caller might reuse.
    """
    if not (reason or "").strip():
        return {"status": "unresolved",
                "error": "a rebuild needs a reason — it mints a new comparability arm, and an arm nobody can "
                         "account for is exactly the corpus fragmentation this is meant to reduce."}
    sim_path = sim_path or _free_sim_path()
    vet = vet_rebuild(sim_path, operons, retype_cistrons)
    req = {"id": "req_" + uuid.uuid4().hex[:8],
           "kind": "parca_rebuild",
           "status": "pending_approval" if vet.get("runnable") else "blocked",
           # A `design` block is kept even though nothing is simulated: `list_requests` reads it unconditionally
           # and the interface renders it. `perturbation` is the job kind so it can never collide with a real
           # design in `_match_key`.
           "design": {"perturbation": "parca_rebuild", "condition": sim_path, "timeline": None,
                      "params": {"operons": operons, "retype_cistrons": dict(retype_cistrons or {}),
                                 "cpus": cpus, "reason": reason[:400]},
                      "elongation_model": None},
           "seeds": 0, "generations": 0, "vet": vet, "ts": time.time()}
    with _txn() as q:
        q.append(req)
    return {"request_id": req["id"], "status": req["status"], "runnable": vet.get("runnable"),
            "recommendation": vet.get("recommendation"), "vet": vet, "sim_path": sim_path,
            "note": ("REFUSED — see vet.notes; nothing was queued to run."
                     if not vet.get("runnable") else
                     "Queued PENDING human approval. Cellwright cannot launch a rebuild any more than a sim; "
                     "a human approves via the interface. ~7 minutes, ~114 MB.")}


def revise(request_id: str, *, perturbation: str | None = None, condition: str | None = None,
           timeline: str | None = None, params: dict | None = None, seeds: int | None = None,
           generations: int | None = None, gene: str | None = None, genes: list | None = None,
           elongation_model: str | None = None) -> dict:
    """REVISE a PENDING draft: mark the old one 'superseded' and queue a re-vetted new draft with the changed
    arg(s) merged over the old design. Keeps the human-approval airlock — only an UN-approved draft can be
    revised; a human still approves the result. Returns the new request (linked back via `revised_from`)."""
    with _LOCK:   # hold across the whole (fast, no-sim) revise so it can't interleave with another mutator
        q = _load()
        old = next((r for r in q if r["id"] == request_id), None)
        if not old:
            return {"error": f"no request '{request_id}'"}
        if old["status"] not in ("pending_approval", "blocked"):
            return {"error": f"request '{request_id}' is '{old['status']}' — only a pending draft can be revised."}
        d = old["design"]
        merged = dict(params) if params is not None else dict(d.get("params") or {})
        if genes:   # a gene-set change: drop stale indices so the new symbols are re-resolved
            merged["target_genes"] = list(genes)
            merged.pop("ko_indices", None); merged.pop("variant_index", None)
        old["status"] = "superseded"; _save(q)                       # withdraw the old draft (no duplicate left)
        res = propose(perturbation or d["perturbation"],             # re-acquires _LOCK (re-entrant); sees the save above
                      condition if condition is not None else d.get("condition"),
                      timeline if timeline is not None else d.get("timeline"),
                      merged,
                      seeds if seeds is not None else old["seeds"],
                      generations if generations is not None else old["generations"], gene,
                      # carried forward unless explicitly changed — a revise that silently reset the
                      # elongation model would turn a kinetic draft into a steady-state run at the airlock
                      elongation_model if elongation_model is not None
                      else d.get("elongation_model", DEFAULT_MODE))
        with _txn() as q:                                            # link old -> new for traceability
            for r in q:
                if r["id"] == request_id:
                    r["superseded_by"] = res.get("request_id")
    return {**res, "revised_from": request_id}


def list_requests(status: str | None = None) -> list[dict]:
    return [{"id": r["id"], "status": r["status"], "design": r["design"], "seeds": r["seeds"],
             "generations": r["generations"], "recommendation": r.get("vet", {}).get("recommendation"),
             "vet": r.get("vet"),   # the interface renders the approval gate (safety/feasibility/provenance) from this
             "session_id": r.get("session_id"), "hyp_id": r.get("hyp_id"),   # provenance: the chat OR the Hypothesis run that proposed it
             "from_question": r.get("from_question"),
             "ts": r.get("ts"), "shard": r.get("shard"), "error": r.get("error")}
            for r in _load() if status is None or r["status"] == status]


def stamp_provenance(request_id: str, session_id: str | None = None, question: str | None = None,
                     hyp_id: str | None = None) -> bool:
    """Record WHERE a queued job came from — an agent chat (session_id) or a Council/Hypothesis run (hyp_id) — plus
    the framing question. Powers the queue's click-to-jump-back-to-context (the agent stamps the sid; a Council
    falsifier queued from the surface stamps the hyp_id)."""
    with _txn() as q:
        for r in q:
            if r["id"] == request_id:
                if session_id:
                    r["session_id"] = session_id
                if hyp_id:
                    r["hyp_id"] = hyp_id
                if question:
                    r["from_question"] = question[:200]
                return True
    return False


# --- SP-1: per-design lifecycle — reflect the launch queue back onto a Hypothesis -------------------------
_LIFE_RANK = {"done": 6, "running": 5, "pending_approval": 4, "blocked": 3, "failed": 2, "superseded": 1,
              "rejected": 0, "unresolved": 0}


def _match_key(perturbation, condition, timeline, params, elongation_model=None) -> tuple:
    """A design's SEMANTIC identity for matching against queued/run jobs — perturbation/condition/timeline + the
    identifying params (gene set, ppGpp multiplier, operon count, TF targets). It deliberately EXCLUDES the resolved
    variant_index/ko_indices: a Council falsifier carries the gene SYMBOLS, and the queued job it spawns also carries
    the resolved index, so keying on the index would wrongly split them. Symbol-level identity matches both.

    The elongation model IS part of the identity: without it a kinetic proposal reports status 'done' with
    another job's request_id and shard because a steady-state job of the same design finished, and the
    Hypothesis surface then shows a falsifier as executed when it never ran."""
    p = params or {}
    genes = tuple(sorted(str(g).lower() for g in (p.get("target_genes") or ([p["gene"]] if p.get("gene") else []))))
    ident = {k: p[k] for k in ("multiplier", "num_operons_to_delete", "direction", "target_tfs",
                               "tf_occupancy_clamp", "ppgpp_clamp", "initiation_threshold") if k in p}
    if ident.get("initiation_threshold") == "medium":           # the model's own rule: the same job as no setting
        ident.pop("initiation_threshold")
    return (perturbation or "wildtype", condition or None, timeline or None, genes,
            json.dumps(ident, sort_keys=True, default=str), elongation_model or DEFAULT_MODE)


def lifecycle_for_designs(designs: list[dict]) -> list[dict]:
    """For each rendered design (a dict with perturbation/condition/timeline/params), find any launch-queue job of the
    same semantic identity and return its lifecycle, PARALLEL to `designs`: {status, request_id, shard}. The
    most-advanced matching job wins (done > running > pending_approval > blocked > failed). status is 'proposed' when
    nothing matches. Matched by DESIGN, not hyp_id, so a run submitted from the Council surface OR proposed by
    Cellwright is reflected back onto the Hypothesis. Corpus 'in_corpus' membership is the caller's concern."""
    q = _load()
    by_key: dict[tuple, list] = {}
    for r in q:
        d = r.get("design") or {}
        by_key.setdefault(_match_key(d.get("perturbation"), d.get("condition"), d.get("timeline"),
                                     d.get("params"), d.get("elongation_model")), []).append(r)
    out = []
    for dv in designs:
        jobs = by_key.get(_match_key(dv.get("perturbation"), dv.get("condition"), dv.get("timeline"),
                                     dv.get("params"), dv.get("elongation_model")), [])
        job = max(jobs, key=lambda r: _LIFE_RANK.get(r.get("status"), -1), default=None)
        out.append({"status": (job["status"] if job else "proposed"),
                    "request_id": (job["id"] if job else None),
                    "shard": (job.get("shard") if job else None)})
    return out


def reconcile() -> dict:
    """Heal jobs orphaned at 'running' by a server restart/crash. approve_and_run runs the sim in an in-process
    thread, so if the server dies between the sim finishing and the status write, the job is stuck at 'running'
    forever even though its data landed. On startup, for each 'running' job: if the manifest already has a run for
    its design -> 'done' (the data is indexed and agent-visible); otherwise it produced nothing -> 'failed'. We ask
    the manifest, not a recomputed run dir, because the raw output's location (out/ vs runs/) and the variant-index
    hash are both unreliable to reproduce. Idempotent; run once at boot."""
    from . import manifest
    from .model import Design

    healed = 0
    with _txn() as q:
        for r in q:
            if r.get("status") != "running":
                continue
            d = r.get("design") or {}
            # A REBUILD produces no manifest rows, so "did the data land" has to be asked of the knowledge base
            # rather than of `count_runs` — which would return 0 and heal a COMPLETED rebuild to 'failed',
            # reporting failure for work that succeeded and prompting a needless seven-minute re-run.
            if r.get("kind") == "parca_rebuild":
                from . import manifest as _m
                kb = (_m._kb_prov(d.get("condition")) or {}).get("kb_sha256")
                r["status"] = "done" if kb else "failed"
                if kb:
                    r.setdefault("result", {})["kb_sha256"] = kb
                else:
                    r["error"] = "orphaned at 'running' (server restart/crash mid-rebuild); no kb at this path"
                healed += 1
                continue
            landed = 0
            try:
                design = Design(perturbation=d["perturbation"], condition=d.get("condition"),
                                timeline=d.get("timeline"), params=d.get("params") or {},
                                elongation_model=d.get("elongation_model", DEFAULT_MODE))
                # count_runs matches on the label prefix, which now carries the elongation tag. Without the
                # field here a kinetic job that produced nothing would be healed to 'done' by the 26
                # steady-state `wildtype·basal·s*` rows that match the prefix.
                landed = manifest.count_runs(design)   # DISTINCT seeds indexed — not just ">=1" (the false-'done' bug)
            except Exception:
                landed = 0
            requested = int(r.get("seeds") or 0)
            # a multi-seed campaign that crashed after seed 0 must NOT report 'done' — that hid an incomplete run and
            # a null shard behind a green status. 'done' only when every requested seed landed; 'partial' otherwise.
            if landed <= 0:
                r["status"] = "failed"
                r["error"] = "orphaned at 'running' (server restart/crash mid-run); no indexed run found"
            elif requested and landed < requested:
                r["status"] = "partial"
                r["error"] = f"orphaned mid-campaign: only {landed}/{requested} seeds indexed (crash before completion)"
            else:
                r["status"] = "done"
            healed += 1
    return {"reconciled": healed}


def clear_finished() -> dict:
    """The queue's 'Clear': drop FINISHED/dismissed requests (done, failed, rejected, superseded) from the airlock,
    keeping live work (pending_approval, running, blocked). Called after the user has seen the results."""
    with _LOCK:
        q = _load()
        keep = [r for r in q if r["status"] in ("pending_approval", "running", "blocked")]
        n = len(q) - len(keep)
        _save(keep)
    return {"cleared": n, "remaining": len(keep)}


def clear_all() -> dict:
    """The queue's 'Clear ALL': drop every request EXCEPT one that is actively running (never orphan a live sim).
    For wiping a pile of accumulated pending drafts in one go."""
    with _LOCK:
        q = _load()
        keep = [r for r in q if r["status"] == "running"]
        n = len(q) - len(keep)
        _save(keep)
    return {"cleared": n, "remaining": len(keep)}


def approve_and_run(request_id: str, parallel: int = 1, index: bool = True) -> dict:
    """HUMAN APPROVAL — launches the vetted job. NOT an agent tool (the interface / a human calls it). Refuses a
    safety-blocked request. Indexes the result so Cellwright can then reason over it.

    TWO JOB KINDS since PARCA-3: a simulation campaign, and a knowledge-base rebuild (`kind='parca_rebuild'`).
    Entries queued before that carry no `kind` at all and must keep routing to the simulation path — hence the
    default rather than a lookup that would KeyError on every historical request.
    """
    from . import manifest
    with _LOCK:   # claim the job (validate + flip to 'running') atomically, then RELEASE before the long sim
        q = _load()
        req = next((r for r in q if r["id"] == request_id), None)
        if not req:
            return {"error": f"no request '{request_id}'"}
        if req["status"] == "blocked":
            return {"error": "request is SAFETY-BLOCKED — refusing to run (override requires editing the queue by hand)."}
        if req["status"] != "pending_approval":
            return {"error": f"request is '{req['status']}', not pending_approval."}
        d = req["design"]
        kind = req.get("kind", "simulation")     # entries written before PARCA-3 carry no `kind`
        seeds, generations = req["seeds"], req["generations"]
        req["status"] = "running"; _save(q)

    if kind == "parca_rebuild":
        return _run_rebuild(request_id, d)

    # Reconstructed with EXPLICIT kwargs, so anything not named here is dropped — which is why the elongation
    # model has to be named. Without it a human approves "run this kinetic" at the airlock and a steady-state
    # sim runs, defeating the one gate whose entire purpose is that the approval record and the executed run
    # cannot disagree.
    design = Design(perturbation=d["perturbation"], condition=d["condition"], timeline=d["timeline"],
                    params=d["params"], elongation_model=d.get("elongation_model", DEFAULT_MODE))
    shard: str | None = None
    error: str | None = None
    outcome: dict | None = None   # stays None if campaign raised, so the real error is what surfaces
    try:
        # campaign runs the sim AND indexes the new run into its own shard (one reader container per run) — that
        # alone makes it agent-visible. Then compact() consolidates shards WITHOUT re-reading every run on disk
        # (record_existing did, which spun a container per corpus run — the "blinking + seems-stuck" churn, and it
        # deleted the shard we then referenced). compact leaves ONE surviving shard, so point `shard` at it. Run OUTSIDE
        # the lock — a sim takes minutes and must not block propose/list/stamp on other threads.
        s = manifest.campaign([design], list(range(seeds)), generations, parallel)
        # campaign is crash-isolated ON PURPOSE — a failed sim is logged and skipped so a long unattended
        # batch still leaves a usable corpus. The consequence one layer up was not intended: a campaign in
        # which EVERY run failed still returns a shard path and raises nothing, so this reported
        # status="done", error=None for a request that produced no rows at all. MEASURED on a fresh clone
        # with no ParCa output: the sim died on a missing simData.cPickle and the caller was told "done".
        # Count what landed BEFORE compact() folds the shard into the corpus and the evidence is gone.
        outcome = manifest.shard_outcome(s)   # read BEFORE compact folds this shard into the corpus
        if index:
            res = manifest.compact()
            s = res.get("shard") or s
        shard, status = str(s), "done"
    except Exception as exc:
        from . import redact
        status, error = "failed", redact.scrub(str(exc))[:200]   # persisted to data/launch_queue.json + /api/queue
    with _LOCK:   # re-acquire to write the terminal status (re-find the job — the queue may have changed under us)
        q = _load()
        req = next((r for r in q if r["id"] == request_id), None)
        if req is not None:
            req["status"] = status
            if error is None:
                req["shard"] = shard
            else:
                req["error"] = error
        _save(q)
    out = {"request_id": request_id, "status": status, "shard": shard, "error": error}
    if outcome is not None:
        out["recorded"] = outcome
        # Gate on `read`, never on the counts alone. An unreadable shard also reports ok=0, and saying
        # "nothing passed QC" because we could not open a file is the failure this note exists to end.
        if outcome.get("read") and outcome["ok"] == 0:
            # Not an error, and not silence either: the request completed and nothing it produced is
            # usable. Whether that is a broken container or a genuinely inviable design is what the
            # crash breakdown is for, and it is the reader's call to make, not ours to guess.
            out["note"] = (f"0 of {outcome['rows']} recorded run(s) passed QC "
                           f"(qc={outcome['qc']}, crash={outcome['crash']}). crash_type 'container' is "
                           "ambiguous: a broken container and an inviable design exit alike. A checkout "
                           "that has never run the ParCa has no kb/simData.cPickle, which is the usual "
                           "cause of the former.")
    return out


def _run_rebuild(request_id: str, d: dict) -> dict:
    """Execute an APPROVED knowledge-base rebuild, then record what it produced.

    The gate is re-checked here rather than trusted from proposal time. A rebuild can sit pending for hours,
    and in that window another rebuild can land at the same path — at which point the destination the human
    approved as empty is holding a fit that live rows depend on. The vet is cheap; the failure it prevents is
    unrecoverable.
    """
    from . import runner
    p = d.get("params") or {}
    sim_path = d.get("condition")
    result: dict = {}
    error: str | None = None
    try:
        recheck = vet_rebuild(sim_path, p.get("operons") or "on", p.get("retype_cistrons"))
        if not recheck.get("runnable"):
            raise RuntimeError("destination stopped being safe while the request was pending: "
                               + "; ".join(recheck.get("notes") or []))
        result = runner.parca_rebuild(sim_path, p.get("retype_cistrons"), p.get("operons") or "on",
                                      p.get("cpus"))
        status = "done"
    except Exception as exc:
        from . import redact
        status, error = "failed", redact.scrub(str(exc))[:400]
    with _LOCK:
        q = _load()
        req = next((r for r in q if r["id"] == request_id), None)
        if req is not None:
            req["status"] = status
            if error is None:
                req["result"] = result
            else:
                req["error"] = error
        _save(q)
    return {"request_id": request_id, "status": status, "result": result, "error": error,
            "note": (None if error else
                     "Rebuilt at '%s' (kb_sha256 %s…). Runs against it form a NEW ARM and are NOT poolable "
                     "with the existing corpus. The arm does not appear in docs/CORPUS_ARMS.md yet — that "
                     "table is built from manifest ROWS, and this knowledge base has none until something is "
                     "simulated against it. Propose those comparators next."
                     % (sim_path, str(result.get("kb_sha256"))[:8]))}


def reject(request_id: str) -> dict:
    hit = False
    with _txn() as q:
        for r in q:
            if r["id"] == request_id and r["status"] in ("pending_approval", "blocked"):
                r["status"], hit = "rejected", True
    return {"request_id": request_id, "status": "rejected" if hit else "not_found_or_not_pending"}
