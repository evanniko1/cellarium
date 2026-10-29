"""Agent-tool conformance sweeps: the bug classes the option-A discovery leg found, tested for every tool at once.

WHY THIS EXISTS. In one day (2026-10-27) a blind Cellwright run failed or misread its evidence because of eleven
faults, and every one was in Cellarium's tools or harness, not in the model or the simulation. Each was caught
by reading a transcript, after it had cost a run. They fall into four families, and the published guidance on
agent tooling names each of them:

  1. ABSENCE. "Could not read" returned as a finding: an empty gene map read as "INVALID", an unreadable store
     as "n = 0, genuinely absent", unwritten listener columns as 0.0, an underpowered test as "no response".
     Tool errors belong in the result as errors (MCP's `isError`; OpenAI: return success or failure), and an
     environment fault must not look like a result (Anthropic, "Demystifying evals for AI agents"; StableToolBench).
  2. SHAPE. Output cut by the context cap with no trace of what went: 22 of 24 survey channels, 5 of 6 entries of
     the capability registry. Paginate, filter or truncate with defaults, and say what was dropped and how to get
     it (Anthropic, "Writing effective tools for agents"; SWE-agent's interface design).
  3. DETERMINISM. The same call answered differently: a tie between arms broken by the order of a parallel scan.
     The environment must not add noise, and consistency is measured as pass^k (Anthropic; AWS AgentCore).
  4. CONTEXT. Behaviour that depends on where the process happens to run: caches read relative to the working
     directory. Each trial starts from a clean, known environment (Anthropic).

Each sweep below calls every read-only tool and checks one family. Side-effecting, network and model-calling
tools are never called. The sweeps report; the tests in tests/test_tool_conformance.py decide what must pass.
"""
from __future__ import annotations

import contextlib
import json
import os
import random
import re
from pathlib import Path

# Never called by a sweep: they launch simulations, download, write proposals, reach the network, or call a model.
SIDE_EFFECT_OR_EXTERNAL = {
    "run_experiment", "download_raw", "propose_experiment", "propose_experiments", "propose_rebuild",
    "revise_experiment", "use_skill", "web_get", "robustness_check", "data_availability", "rnaseq_concordance",
}
# Read-only but needs the simulation image (Docker) or a solver; called only when `heavy=True`.
HEAVY = {"top_movers", "regulon_response", "reroute_diagnosis", "fba_growth", "fba_gene_knockout", "fba_flux",
         "fba_essentiality_panel", "fba_synthetic_lethal", "fba_gene_deletion", "fba_sensitivity", "fba_qc",
         "generate_designs", "design_panel", "screen_phenotype", "vet_hypothesis", "deg_rate_provenance",
         "model_validation", "prune_candidates", "corpus_audit"}

# Keys whose values legitimately change between two identical calls.
_VOLATILE = re.compile(r"(time|seconds|latency|_ms$|timestamp|generated|elapsed|duration|uuid|session)", re.I)
# Tools that report the MACHINE rather than the corpus: free memory and disk move between two calls, and that is
# the measurement, not noise in it. Excluded from the determinism sweep only, and named so the exclusion is visible.
ENVIRONMENT_PROBES = {"system_resources", "estimate_sim_resources"}

# TOOLS WHOSE PURPOSE IS TO REPORT ABSENCE. `raw_available` answering `{"n_seeds_local": 0, "note": "no raw
# simOut on local disk for this design"}` is the correct answer, not a silent absence -- the question it was
# asked is "is the data here", and "no" is a result. The sweep's first exercised run flagged it, which was the
# sweep's error and not the tool's. Kept as a NAMED exemption, in the same spirit as ENVIRONMENT_PROBES above.
AVAILABILITY_PROBES = {"raw_available", "data_availability", "coverage_check", "provenance"}


def _canonical(x):
    """A value with volatile keys removed and lists sorted, so two answers compare by CONTENT, not by order."""
    if isinstance(x, dict):
        return {k: _canonical(v) for k, v in sorted(x.items()) if not _VOLATILE.search(str(k))}
    if isinstance(x, list):
        return sorted((_canonical(v) for v in x), key=lambda v: json.dumps(v, sort_keys=True, default=str))
    if isinstance(x, float):
        return round(x, 9)
    return x


def sample_args(design: str, reference: str, result_id: str | None, gene: str = "pfkA") -> dict[str, dict]:
    """One plausible call per tool, from its schema's required parameters, filled from the store at hand."""
    from . import tools
    fill = {
        "design": design, "design_a": design, "target": design, "design_or_id": design, "design_b": reference,
        "reference": reference, "channel": "growth_rate", "x_channel": "ppgpp_conc", "y_channel": "growth_rate",
        "result_id": result_id or design, "gene": gene, "symbol": gene, "genes": [gene],
        "perturbation": design.split("/")[0], "regulon": "pho_phosphate", "condition": "basal",
        "kind": "protein", "species_id": "PFKA-MONOMER[c]", "designs": [design, reference],
        "factors": {"perturbation": ["wildtype"]}, "contrast": "basal",
    }
    out = {}
    for t in tools.TOOLS:
        name = t["name"]
        if name in SIDE_EFFECT_OR_EXTERNAL:
            continue
        schema = t.get("input_schema") or {}
        req = list(schema.get("required") or [])
        # A one-of-N requirement is expressed as `anyOf: [{required: [...]}, ...]`, not as `required`. Taking
        # the first satisfiable branch is what lets a tool like `chart` be exercised at all: built from
        # `required` alone its sample call named no run, so every one of its enum values came back refused.
        for branch in (schema.get("anyOf") or []):
            need = list((branch or {}).get("required") or [])
            if need and all(r in fill for r in need):
                req += need
                break
        if all(r in fill for r in req):
            out[name] = {r: fill[r] for r in req}
    return out


def call(name: str, args: dict) -> dict:
    """Dispatch one tool; an exception becomes a result, so a sweep never stops on one tool."""
    from . import tools
    try:
        out = tools.dispatch(name, dict(args))
        return out if isinstance(out, dict) else {"_non_dict_result": repr(out)[:200]}
    except Exception as exc:
        return {"_exception": f"{type(exc).__name__}: {exc}"[:300]}


def _skip(name: str, heavy: bool) -> bool:
    return name in SIDE_EFFECT_OR_EXTERNAL or (name in HEAVY and not heavy)


# ---- 2. SHAPE: every result reaches the agent as valid JSON, and anything cut is named -------------------------

def budget_sweep(calls: dict[str, dict], heavy: bool = False) -> list[dict]:
    """For each tool: its raw size, its context cap, and what the agent would see. A failure is the last-resort
    string cut (invalid JSON, nothing named); a trim that names what it dropped is reported, not failed."""
    from . import agent
    rows = []
    for name, args in calls.items():
        if _skip(name, heavy):
            continue
        out = call(name, args)
        cap = agent._TOOL_CAPS.get(name, agent._TOOL_CAP)
        raw = json.dumps(out, default=str)
        seen = agent._truncate_tool_result(out, cap, name)
        try:
            parsed = json.loads(seen)
            valid = True
        except Exception:
            parsed, valid = None, False
        trimmed = len(seen) < len(raw) or (isinstance(parsed, dict) and ("_omitted" in parsed or "_truncated" in parsed))
        rows.append({"tool": name, "raw": len(raw), "cap": cap, "seen": len(seen), "valid_json": valid,
                     "trimmed": trimmed, "string_cut": "…[truncated]" in seen})
    return rows


# ---- 1. ABSENCE: an unreadable source is an error, never a well-formed empty answer -----------------------------

# A COUNT-LIKE KEY, by shape rather than by a list. The hand-listed set was {"n", "n_runs", "n_results",
# "n_designs", "n_compared", "count", "total", "n_seeds"}, and the run-grain sweep walked straight past
# `serialization_check` answering `{"n_runs_scanned": 0, "n_columns_flagged": 0, "n_high": 0, "ok": true}` with
# no run directory on the machine -- a clean bill of health issued over nothing, which is the exact shape this
# family exists to catch, missed because nobody had added that spelling. `all counts are zero` keeps it honest:
# with data present `n_runs_scanned` is non-zero, so flagging zero columns is not an empty success.
# The second half is DENOMINATOR counts -- how many things were looked at -- and not numerator counts like
# `n_events` or `n_columns_flagged`, where zero can be a true finding about real data. `channels_scanned` is
# the one that matters: the narrowing check was written for `scan_overview` going 5 -> 3 and could not see it,
# because the first half of this pattern matches neither `channels_scanned` nor anything else in that answer.
# Its own unit test caught that, which is the only reason it is not still broken.
_COUNT_KEY = re.compile(r"^(n|num|count|total)(_|$)|_(count|n|total)$"
                        r"|_(scanned|considered|checked|examined|compared|requested|returned)$", re.I)


def empty_success(out: dict) -> bool:
    """A result with no error that reports nothing found: a count of 0, or only empty lists. From a source that
    could not be read, this is the silent-absence shape."""
    if not isinstance(out, dict) or any(k in out for k in ("error", "_exception", "refusal")):
        return False
    counts = [v for k, v in out.items() if _COUNT_KEY.search(str(k)) and isinstance(v, (int, float))
              and not isinstance(v, bool)]
    lists = [v for v in out.values() if isinstance(v, list)]
    return (bool(counts) and all(c == 0 for c in counts)) or (bool(lists) and not counts and all(len(v) == 0 for v in lists))


@contextlib.contextmanager
def _unreadable_store(tmp: Path):
    """Run with NO manifest and NO caches: the working directory is empty, and the cache directory points at an
    empty folder. Restores both afterwards."""
    from . import factors, paths
    old_cwd, old_cache, old_fcache = os.getcwd(), paths.CACHE_DIR, factors._CACHE
    old_scope, old_fp = factors._SCOPE, factors._FP
    empty = tmp / "empty_cache"
    empty.mkdir(parents=True, exist_ok=True)
    os.chdir(tmp)
    paths.CACHE_DIR = factors._CACHE = empty
    factors._SCOPE = factors._FP = None
    try:
        yield
    finally:
        os.chdir(old_cwd)
        paths.CACHE_DIR, factors._CACHE = old_cache, old_fcache
        factors._SCOPE, factors._FP = old_scope, old_fp


def absence_sweep(calls: dict[str, dict], tmp: Path, heavy: bool = False) -> list[dict]:
    """Every CORPUS-READING tool, with its data unreadable. Reports the ones that answer with an empty success
    instead of an error.

    Scoped to `reconcile.MEASUREMENT_TOOLS`, which is the registry of tools that read this corpus. A guardrail
    that matched no biosecurity signature, or a resource estimate with no warnings, is a true empty answer about
    something other than the data, and failing those would train the reader to ignore this sweep."""
    from . import reconcile
    measurement = set(reconcile.MEASUREMENT_TOOLS)
    rows = []
    with _unreadable_store(tmp):
        for name, args in calls.items():
            # AVAILABILITY_PROBES are exempt here for the same reason as in the finer sweeps, and the exemption
            # had to be added when the count-key detector was widened by shape: `raw_available` answers
            # `n_seeds_local: 0`, which the hand-listed key set never recognised as a count, so family 1 had
            # been walking past it since it was written. Widening the detector exposed the blind spot; the
            # answer is still the right answer to the question that tool is asked.
            if _skip(name, heavy) or name not in measurement or name in AVAILABILITY_PROBES:
                continue
            out = call(name, args)
            rows.append({"tool": name, "empty_success": empty_success(out),
                         "kind": ("exception" if "_exception" in out else "error" if "error" in out else "result"),
                         "excerpt": json.dumps(out, default=str)[:160]})
    return rows


# ---- 1b. ABSENCE AT A FINER GRAIN: a readable store whose RUN, or whose CHANNEL, is not there -------------------
#
# Family 1 builds its own emptiness at the coarsest grain there is: no manifest, no caches, nothing to read at
# all. That grain found four faults and then stopped finding any -- and a tool that handles a wholly unreadable
# store correctly can still mishandle the two finer absences that are ORDINARY in this corpus:
#
#   RUN grain      the manifest row exists and the design is real, and the seed's run directory is not on this
#                  machine -- pruned to HuggingFace (WELL-PRUNE-2 deleted 17 seed dirs) or never downloaded.
#                  `_seed_root` returns None and `seed_runs` comes back empty.
#   CHANNEL grain  the run is here and the listener never wrote the column. The module-off arm of the kinetic
#                  campaign records none of ppGpp, RelA or ribosome concentration, and `_col_1d` already answers
#                  all-NaN for that case -- so this grain is forced with THE SAME VALUE the real condition
#                  produces, not with a synthetic one.
#
# The two grains have DIFFERENT correct classifications, and conflating them is itself a defect this checks: an
# absent run directory is `environment` (this machine could not look, and is never evidence about the model),
# while an unwritten column is `corpus` (`channel_not_recorded` -- the runs we hold genuinely do not carry it,
# which IS evidence, about coverage).
#
# WHY THIS EXISTS, dated: continuous integration found the motivating defect at the run grain on 2026-10-28.
# `shift_response` resolved the shift time from the declared timeline and then, finding no trajectory on the
# runner, returned only "no local raw simOut" and DROPPED the resolved time -- so "this design declares no shift"
# and "this machine does not hold its data" became indistinguishable one layer below the family-9 fix. The local
# suite could not reach that branch, because this machine has the data. Hence the third check below: a fact the
# tool resolved from the DECLARATION must survive an absent MEASUREMENT.

# A field whose presence means "something was left out, and here is what". A narrowed answer that carries none
# of these is presenting a partial read as a complete one.
_NAMES_AN_OMISSION = re.compile(
    r"(omit|not_recorded|unrecorded|not_measured|skip|unavailable|absent|missing|excluded|unwritten|"
    r"_dropped|not_scanned|no_local|why)", re.I)

_ABSENCE_GRAINS = ("run", "channel")
# grain -> the `about` class a refusal at that grain must carry, and why it is that one and not the other.
_GRAIN_ABOUT = {
    "run": ("environment", "the seed's run directory is not on this machine; nothing about that is evidence "
                           "about the model"),
    "channel": ("corpus", "the runs we hold genuinely do not record this column, which is evidence about "
                          "coverage"),
}


@contextlib.contextmanager
def _no_local_runs():
    """Readable store, real designs, and NO raw run directory on this machine.

    Patched at `_seed_root`, which is the exact predicate the real condition turns on (`Path(p).exists()`), so
    `seed_runs` reaches its empty answer through its own logic rather than being short-circuited."""
    from . import raw
    orig_root, orig_dirs = raw._seed_root, raw.simout_dirs
    raw._seed_root = lambda result_id: None
    raw.simout_dirs = lambda seed_root: []
    try:
        yield
    finally:
        raw._seed_root, raw.simout_dirs = orig_root, orig_dirs


@contextlib.contextmanager
def _unwritten_channel(*channels: str):
    """Runs present; the named channels' listener columns were never written.

    Returns all-NaN for those columns and leaves every other column -- `Main/time` above all -- untouched, which
    is precisely what `_col_1d` returns for a column `not_recorded` marks. A channel name not in `raw.CHANNELS`
    is ignored rather than raising: an unknown channel is a REQUEST fault and belongs to the contract sweep."""
    import numpy as np

    from . import raw
    targets = {raw.CHANNELS[c] for c in channels if c in raw.CHANNELS}
    orig = raw._col_1d

    def blind(simout: str, table: str, column: str):
        a = orig(simout, table, column)
        if (table, column) not in targets:
            return a
        return np.full(a.shape[0] if getattr(a, "ndim", 0) else 1, np.nan)

    raw._col_1d = blind
    try:
        yield
    finally:
        raw._col_1d = orig


def _grain_context(grain: str, channels):
    return _no_local_runs() if grain == "run" else _unwritten_channel(*channels)


def _counts(out: dict) -> dict:
    return {k: v for k, v in out.items()
            if _COUNT_KEY.search(str(k)) and isinstance(v, (int, float)) and not isinstance(v, bool)} \
        if isinstance(out, dict) else {}


def narrowed_silently(full: dict, blind: dict) -> list[str]:
    """Count-like keys that FELL when the source was taken away, in an answer that names no omission.

    This is the check that `scan_overview` needed and `empty_success` could not give: with two channels
    unwritten it answered `channels_scanned: 3` where the full read says 5, and nothing in the result said which
    two had gone -- so "no transient in growth_rate" and "growth_rate was never looked at" arrived identical. The
    answer was neither empty nor an error, which is exactly why a zero-count test misses it."""
    if not isinstance(blind, dict) or any(k in blind for k in ("error", "_exception", "refusal")):
        return []
    if any(_NAMES_AN_OMISSION.search(str(k)) for k in blind):
        return []
    fc, bc = _counts(full), _counts(blind)
    return sorted(k for k, v in fc.items() if k in bc and bc[k] < v)


def _declared_facts(out: dict) -> dict:
    """Every registered fact a result reports, by result key. Only facts resolvable from a design's DECLARATION
    are registered, which is what makes "it must survive an absent measurement" the right expectation."""
    found = {}
    if not isinstance(out, dict):
        return found
    for _fact, spec in FACTS.items():
        if not spec.get("from_declaration"):
            continue
        for key in spec.get("result_keys", ()):
            if out.get(key) is not None:
                found[key] = _canonical(out[key])
    return found


_RAW_BACKED: dict[tuple, list] = {}


def raw_backed_designs() -> list[tuple[int, str]]:
    """(n_local_seeds, design_key) for every design whose raw simOut is on this machine, most seeds first.

    23 of the corpus's 40 designs have local raw; 17 do not, because WELL-PRUNE-2 moved their seed directories
    to HuggingFace. A sweep probing one of those 17 takes away something that was already gone."""
    from . import raw, survey
    # MEMOISED BY WORKING DIRECTORY. Each call globs the filesystem for every design's simOut dirs, and several
    # tests and sweeps ask for it; uncached it dominated the conformance module's runtime. The key is the cwd
    # because `_unreadable_store` chdirs, and the answer is a property of the store it lands in.
    # Keyed on the resolver's identity as well as the cwd: `_no_local_runs` replaces `raw._seed_root` without
    # changing the directory, so a cwd-only key would hand a caller inside that context the pre-patch answer.
    cwd = (os.getcwd(), id(raw._seed_root))
    if cwd in _RAW_BACKED:
        return list(_RAW_BACKED[cwd])
    rows, _ = survey.analysis_rows()
    out = []
    for key in sorted({survey.design_key(r) for r in rows}):
        try:
            n = len(raw.seed_runs(key))
        except Exception:
            n = 0
        if n:
            out.append((n, key))
    _RAW_BACKED[cwd] = sorted(out, reverse=True)
    return list(_RAW_BACKED[cwd])


def fine_absence_sweep(calls: dict[str, dict], heavy: bool = False,
                       channels: tuple[str, ...] = ("growth_rate", "ppgpp_conc"),
                       design: str | None = None) -> list[dict]:
    """Each corpus-reading tool called with full data, then with the run absent, then with the channel unwritten.

    Three checks per grain, and a tool is only judged on a grain whose source it actually reads:

      `empty_success`   an absence must arrive as an error, not as a well-formed count of zero (family 1's
                        criterion, one and two grains finer).
      `about`           the refusal must carry the class the grain earns: `environment` for an absent run
                        directory, `corpus` for an unwritten column. The wrong class is not cosmetic -- an agent
                        is entitled to retry a `request` fault and to cite a `corpus` one as a finding.
      `facts_dropped`   any registered declaration-derived fact present in the full answer must still be present,
                        with the same value, in the refusal. This is the generalisation of the CI-caught
                        `shift_response` defect.
      `narrowed_silently`  a count that FELL with the source removed, in an answer that names no omission: a
                        partial read presented as a complete one. Neither empty nor an error, and so invisible
                        to the two checks above.

    `reads_source` is False when the two answers are identical: that tool does not read this grain's source, so
    the sweep reports it as not exercised rather than passing or failing it.

    `design` is the probe whose data is taken away, and it MUST have raw simOut on this machine. The sweep's own
    first run reported 34 of 36 tools at the run grain as not exercised, which looked like a clean result and was
    not one: the probe was `gene_knockout/KO:alaS`, whose seed directories WELL-PRUNE-2 had already deleted, so
    every answer was identical before and after because there had never been anything there. With no baseline
    every row is `no_baseline`, and the runner fails on it -- an unexercised sweep reported as a pass is the same
    defect as an unread store reported as a finding."""
    from . import raw, reconcile
    measurement = set(reconcile.MEASUREMENT_TOOLS)
    n_baseline = len(raw.seed_runs(design)) if design else 0
    if design and not n_baseline:
        return [{"tool": t, "grain": g, "reads_source": False, "verdict": "no_baseline", "design": design,
                 "n_baseline_seeds": 0}
                for t in sorted(set(calls) & measurement if not heavy else set(calls) & measurement)
                for g in _ABSENCE_GRAINS]
    rows = []
    for name, args in calls.items():
        if _skip(name, heavy) or name not in measurement or name in AVAILABILITY_PROBES:
            continue
        full = call(name, args)
        full_c, full_facts = _canonical(full), _declared_facts(full)
        for grain in _ABSENCE_GRAINS:
            want_about, why = _GRAIN_ABOUT[grain]
            with _grain_context(grain, channels):
                blind = call(name, args)
            if _canonical(blind) == full_c:
                rows.append({"tool": name, "grain": grain, "reads_source": False, "verdict": "not_exercised",
                             "n_baseline_seeds": n_baseline})
                continue
            refused = isinstance(blind, dict) and any(k in blind for k in ("error", "_exception", "refusal"))
            blind_facts = _declared_facts(blind)
            dropped = sorted(k for k, v in full_facts.items() if blind_facts.get(k) != v)
            narrowed = narrowed_silently(full, blind)
            got_about = blind.get("about") if isinstance(blind, dict) else None
            # `about` is only judged on a REFUSAL. A tool that still answers -- a wider read that simply has
            # fewer seeds to average -- is not refusing, and has no `about` to get wrong.
            about_ok = (got_about == want_about) if refused else None
            rows.append({
                "tool": name, "grain": grain, "reads_source": True, "n_baseline_seeds": n_baseline,
                "empty_success": empty_success(blind), "refused": refused,
                "about": got_about, "about_expected": want_about, "about_ok": about_ok, "why_that_class": why,
                "reason": blind.get("reason") if isinstance(blind, dict) else None,
                "facts_in_full": sorted(full_facts), "facts_dropped": dropped,
                "narrowed_silently": narrowed,
                "verdict": ("fail" if (empty_success(blind) or dropped or narrowed or about_ok is False)
                            else "ok"),
                "excerpt": json.dumps(blind, default=str)[:160]})
    return rows


# ---- 3. DETERMINISM: the same question gives the same answer, whatever order the rows arrive in -----------------

@contextlib.contextmanager
def _shuffled_rows(seed: int = 7):
    """Every row source returns its rows in a different, fixed order: the order a parallel scan may produce."""
    from . import store, survey
    rng = random.Random(seed)
    orig_dedup, orig_list, orig_duck = survey._deduped_rows, store.list_results, store._duck

    def shuffled(fn):
        def wrap(*a, **k):
            rows = fn(*a, **k)
            if isinstance(rows, list) and rows and not (isinstance(rows[0], dict) and "__error__" in rows[0]):
                rows = list(rows)
                rng.shuffle(rows)
            return rows
        return wrap

    survey._deduped_rows, store.list_results, store._duck = shuffled(orig_dedup), shuffled(orig_list), shuffled(orig_duck)
    survey._IDENT_CACHE.clear()
    try:
        yield
    finally:
        survey._deduped_rows, store.list_results, store._duck = orig_dedup, orig_list, orig_duck


def determinism_sweep(calls: dict[str, dict], heavy: bool = False) -> list[dict]:
    """Each tool twice as is, then once with every row source shuffled. A tool fails if its CONTENT changes
    (lists are compared as sets, so a different order alone is not a failure)."""
    rows = []
    for name, args in calls.items():
        if _skip(name, heavy) or name in ENVIRONMENT_PROBES:
            continue
        a, b = call(name, args), call(name, args)
        with _shuffled_rows():
            c = call(name, args)
        ca, cb, cc = _canonical(a), _canonical(b), _canonical(c)
        rows.append({"tool": name, "repeat_equal": ca == cb, "order_invariant": ca == cc,
                     "diff_hint": None if ca == cc else _first_difference(ca, cc)})
    return rows


def _first_difference(a, b, path="$"):
    if type(a) is not type(b):
        return f"{path}: {type(a).__name__} vs {type(b).__name__}"
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                return f"{path}.{k}: present in one answer only"
            d = _first_difference(a[k], b[k], f"{path}.{k}")
            if d:
                return d
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: {len(a)} vs {len(b)} items"
        for i, (x, y) in enumerate(zip(a, b)):
            d = _first_difference(x, y, f"{path}[{i}]")
            if d:
                return d
        return None
    return None if a == b else f"{path}: {str(a)[:60]} vs {str(b)[:60]}"


# ---- descriptions: a claim that "nothing found" means "absent" must be earned -------------------------------------

_ABSENCE_CLAIM = re.compile(r"(\b0\s*=|n\s*=\s*0|n_significant\s*~?0|zero)[^.]{0,60}\b(absent|absence|no real|genuinely|"
                            r"nothing (?:changed|moved)|does not exist)", re.I)


# A description may tell the agent to read nothing as absence only when the tool cannot be asked of an unreadable
# source — i.e. it errors instead. Each entry is the reason that claim is earned; the absence sweep is the check.
EARNED_ABSENCE_CLAIMS = {
    "list_results": "an unreadable or missing manifest returns an error with reason 'store_unreadable', never n=0",
    "trna_families": "the claim is about coarse_kinetic writing exact zeros — a property of the MODEL, not of a "
                     "failed read; the tool refuses that mode rather than reporting the zeros",
}


def description_claims() -> list[dict]:
    """Tool descriptions and docstrings that tell the agent to read an empty or zero result as absence. Each is
    acceptable only if the tool distinguishes an unreadable source from an empty one; the test keeps the list."""
    from . import tools
    found = []
    for t in tools.TOOLS:
        for where, text in (("description", t.get("description", "")),
                            ("docstring", (tools._DISPATCH.get(t["name"]).__doc__ or "") if t["name"] in tools._DISPATCH else "")):
            for m in _ABSENCE_CLAIM.finditer(text or ""):
                found.append({"tool": t["name"], "where": where, "claim": m.group(0)[:120],
                              "earned": EARNED_ABSENCE_CLAIMS.get(t["name"])})
    return found


# ---- 5. CONTRACT: a refusal says what KIND of refusal it is --------------------------------------------------
#
# The four families above catch a tool that reports absence AS a measurement. This one catches the other half:
# when a tool correctly refuses, the refusal must carry `errors.REASONS` — a reason, and an `about` that
# separates "the corpus does not contain this" from "this machine could not look". Four of the discovery leg's
# eleven faults were the model reading the second as the first.
#
# Practice: MCP carries a tool-level failure as a flagged, structured result the model can act on, distinct from
# a protocol error; Anthropic's "Writing effective tools for agents" asks that an error steer the agent to the
# right call; "Demystifying evals for AI agents" asks that an environment fault never be scored as an answer;
# TRAJECT-Bench (He et al., ICLR 2026) makes argument correctness its own axis and names "parameter-blind
# selection" as a failure mode, so an unresolvable argument has to come back as an argument error.

_UNRESOLVABLE = "__nope__"


def _bad_value(spec: dict):
    """A value of the right JSON type that cannot resolve to anything in any store."""
    t = (spec or {}).get("type")
    return {"array": [_UNRESOLVABLE], "integer": 999999, "number": 999999.0,
            "object": {_UNRESOLVABLE: _UNRESOLVABLE}}.get(t, _UNRESOLVABLE)


def contract_sweep(heavy: bool = False) -> list[dict]:
    """Call every read-only tool with an unresolvable value for every argument it accepts, and report what comes
    back. A FAILURE is: an exception instead of a result; an error whose reason the registry cannot name; or an
    answer that neither errors nor marks the unresolvable input as unknown. Booleans are left out: `True` is a
    legitimate value, not an unresolvable one."""
    from . import errors, tools
    rows = []
    for t in tools.TOOLS:
        name = t["name"]
        if _skip(name, heavy):
            continue
        props = {k: v for k, v in ((t.get("input_schema") or {}).get("properties") or {}).items()
                 if (v or {}).get("type") != "boolean"}
        if not props:
            rows.append({"tool": name, "verdict": "no_resolvable_arguments"})
            continue
        if all((v or {}).get("type") in ("integer", "number") for v in props.values()):
            # Nothing here CAN be unresolvable: an out-of-range number is a legitimate input, and the tool is
            # right to answer it. `estimate_sim_resources(parallel=999999)` returning a warning is correct.
            rows.append({"tool": name, "verdict": "numeric_arguments_only"})
            continue
        out = call(name, {k: _bad_value(v) for k, v in props.items()})
        row = {"tool": name, "n_args": len(props)}
        if "_exception" in out:
            rows.append({**row, "verdict": "fail", "why": "raised instead of returning", "detail": out["_exception"]})
            continue
        if "error" in out:
            reason = out.get("reason")
            ok = reason in errors.REASONS and reason != "unclassified"
            rows.append({**row, "verdict": "ok" if ok else "fail", "reason": reason,
                         "about": out.get("about"), "next_step": out.get("next_step"),
                         "why": None if ok else "error carries no registered reason",
                         "message": str(out.get("error"))[:160]})
            continue
        # It answered. That is allowed only if the answer SAYS the input was not recognised: `known: false`,
        # `n...: 0` with a note, an `unmapped_*` list. A catalogue tool that ignores its filters answers too.
        js = json.dumps(out, default=str).lower()
        marks = [m for m in ("\"known\": false", "unmapped", "not in the scope", "no raw simout",
                             "is not a declared capability", "out_of_sample", "no biosecurity signature",
                             _UNRESOLVABLE) if m in js]
        rows.append({**row, "verdict": "answered", "marks_unknown_input": bool(marks), "marks": marks[:3]})
    return rows


def unregistered_messages() -> list[dict]:
    """Every literal `{"error": "..."}` string in the package that `errors.classify` cannot name. This is the
    ratchet: the pattern table is applied at one boundary rather than written into 223 call sites, so it can only
    stay complete if an unregistered message fails a check. Static — it calls no tool and reads no store."""
    from . import errors
    src = Path(__file__).resolve().parent
    pat = re.compile(r'"error":\s*f?"([^"]{3,200})')
    found = []
    for f in sorted(src.glob("*.py")):
        if f.name in ("errors.py", "conformance.py"):
            continue
        for m in pat.finditer(f.read_text(encoding="utf-8")):
            # A placeholder stands in for a value: "9X" so that a pattern anchored on a digit and one anchored on
            # a word both still match ("HTTP {status}" -> "HTTP 9X" matches `^HTTP \d`).
            msg = re.sub(r"\{[^}]*\}|%[drs]", "9X", m.group(1))
            if re.search(r"[A-Za-z]{3,}", re.sub(r"9X", "", msg)) is None:
                # Nothing to classify on: the literal is only interpolation, as in f"{type(exc).__name__}: {exc}".
                # Those classify at RUNTIME, from the exception name — pinned by a test, not assumed here.
                found.append({"module": f.name, "message": msg[:160], "dynamic": True})
                continue
            if errors.classify(msg) == "unclassified":
                found.append({"module": f.name, "message": msg[:160], "dynamic": False})
    return found


# ---- 5b. CONTRACT, at the grain of ONE ABSENT ARGUMENT ------------------------------------------------------
#
# Family 5 passes every tool an UNRESOLVABLE value for every argument it accepts. It never leaves one OUT, and
# never passes `null`. Those two are what a model actually sends when it cannot fill a field, and both were
# misattributed — the first by the error table, the second by the tools:
#
#   * LEFT OUT. The pre-check's own message, `missing required argument(s) for '<tool>': <field>`, matched no
#     pattern, so it fell through to `unclassified` → `(environment, register_the_reason)`. The agent was told
#     this machine was at fault and handed a DEVELOPER's instruction as its next step, for a mistake it had
#     made itself and could have fixed in one retry. Its sibling, `unknown argument(s)`, classified correctly
#     all along, which is why the gap survived: the contract family looked covered.
#   * GIVEN AS `null`. The pre-check tested only for the KEY, so a null was passed through to the tool, which
#     resolved it, failed somewhere downstream, and reported THAT. 26 of the 36 (tool, argument) pairs answered
#     the caller's mistake with a statement about something else: 13 blamed this machine (10 `no_local_raw` →
#     `use_another_tool_or_download`, telling the agent to download data it already had, and 3 crashes on
#     `None.split`/`None.startswith` → `report_defect`); 7 blamed the CORPUS, which is the one class this
#     package treats as evidence — `disconfirm(target=null)` and `fit_relation(x_channel=null)` returning
#     `insufficient_data` is a fabricated negative result about a comparison whose target, or whose axis, was
#     never named — and it arrives in the one channel an agent is entitled to write down; and 6
#     ANSWERED, `provenance(perturbation=null)` replying `out_of_sample` being a claim about a perturbation
#     that was never named. Only 10 of 36 already said `request`.
#
#     Those 26 are what the sweep reports on the pre-fix tree, and they are the reason the remedy is one guard
#     at the boundary rather than 26 argument checks: the fault is the same in every one of them, and a guard
#     per tool is 26 chances to forget.
#
# The remedy is one guard at the pre-check — a required argument present as `null` is a required argument the
# caller has no value for, which is the same fault as omitting the key — plus one pattern in the error table.
# This sweep is what makes that stay true. Note what it does and does not establish: both grains are refused at
# the SAME boundary for every tool, so the 54 rows do not test 54 independent implementations, and this sweep
# would not have found 54 separate bugs. It is a ratchet. The per-tool grain is there so that a tool which
# later grows its own argument handling, or a dispatch path that stops running the pre-check, fails a check
# rather than passing one. `declared_required_matches_signature` below is the per-tool half.

_ARG_GRAINS = ("absent", "null")


def required_argument_sweep(heavy: bool = False) -> list[dict]:
    """For every tool with required arguments, leave each one out in turn and then pass each one as `null`, and
    report how the refusal is classified. A PASS is an error carrying a registered reason whose `about` is
    `request`: the caller's fault, with a caller-side remedy. Anything else is the failure — an answer, a raised
    exception, an unregistered reason, or a refusal that blames the environment, the corpus or a policy for an
    incomplete call. A tool whose requirement is a one-of-N `anyOf` branch is probed once with no branch
    satisfied, since the pre-check reads only top-level `required` and that case is the tool's own to handle."""
    from . import errors, tools
    rows = []
    for t in tools.TOOLS:
        name = t["name"]
        if _skip(name, heavy):
            continue
        schema = t.get("input_schema") or {}
        props = (schema.get("properties") or {})
        required = list(schema.get("required") or [])
        branches = [list((b or {}).get("required") or []) for b in (schema.get("anyOf") or [])]
        probes = [(k, g) for k in required for g in _ARG_GRAINS]
        if not required and any(branches):
            # No top-level requirement, but the schema says one of N groups is needed. Satisfy none of them.
            probes = [("|".join(sorted({k for b in branches for k in b})), "no_branch")]
        if not probes:
            rows.append({"tool": name, "verdict": "no_required_arguments"})
            continue
        for arg, grain in probes:
            if grain == "no_branch":
                args = {}
            else:
                args = {a: _bad_value(props.get(a)) for a in required}
                if grain == "absent":
                    args.pop(arg, None)
                else:
                    args[arg] = None
            out = call(name, args)
            row = {"tool": name, "argument": arg, "grain": grain}
            if "_exception" in out:
                rows.append({**row, "verdict": "fail", "why": "raised instead of refusing",
                             "detail": out["_exception"]})
                continue
            if "error" not in out:
                rows.append({**row, "verdict": "fail", "why": "answered an incomplete call",
                             "detail": json.dumps(out, default=str)[:200]})
                continue
            reason, about = out.get("reason"), out.get("about")
            registered = reason in errors.REASONS and reason != "unclassified"
            why = (None if registered and about == "request" else
                   "error carries no registered reason" if not registered else
                   f"an incomplete call blamed on {about!r}")
            rows.append({**row, "verdict": "ok" if why is None else "fail", "reason": reason, "about": about,
                         "next_step": out.get("next_step"), "why": why,
                         "message": str(out.get("error"))[:160]})
    return rows


def declared_required_matches_signature() -> list[dict]:
    """Where a tool's declared `required` set and its function's own un-defaulted parameters disagree. Static —
    it calls no tool and reads no store. Only ONE of the two directions is a defect:

      * `schema_omits_a_needed_argument` IS the defect. The agent is told a field is optional, omits it, the
        pre-check passes it through, and the call raises a TypeError. It is classified correctly today (the
        TypeError branch of `dispatch` produces `bad arguments for …`, which the table does name) — so the cost
        is not a misattribution but the message: a raw TypeError rather than a refusal naming the field.
      * `schema_is_stricter_than_the_signature` is DELIBERATE here, and is reported without being a failure.
        Three tools do it, each so the agent must be explicit about a choice that would otherwise be silent:
        `read_raw_series(channel)` would quietly default to growth_rate, `list_species(kind)` to protein. The
        Python default stays for direct calls in notebooks and tests; the schema is the agent's contract and is
        allowed to ask for more."""
    import inspect

    from . import tools
    rows = []
    for t in tools.TOOLS:
        name = t["name"]
        fn = tools._DISPATCH.get(name)
        if fn is None:
            continue
        try:
            sig = inspect.signature(fn)
        except (TypeError, ValueError):
            continue
        if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
            continue   # takes **kwargs; nothing is structurally required
        declared = set((t.get("input_schema") or {}).get("required") or [])
        needed = {k for k, p in sig.parameters.items()
                  if p.default is inspect.Parameter.empty
                  and p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)}
        for arg in sorted(needed - declared):
            rows.append({"tool": name, "argument": arg, "direction": "schema_omits_a_needed_argument",
                         "verdict": "fail",
                         "why": "the signature has no default, so omitting it raises instead of refusing"})
        for arg in sorted(declared - needed):
            rows.append({"tool": name, "argument": arg,
                         "direction": "schema_is_stricter_than_the_signature", "verdict": "declared",
                         "why": "the agent must choose explicitly; the Python default is for direct calls"})
    return rows

# ---- 6. SELECTION: no two tools are confusable without saying so --------------------------------------------
#
# TRAJECT-Bench (He et al., ICLR 2026) names "similar tool confusion" — the model picks a near-duplicate tool —
# as one of two failure modes that final-answer scoring cannot see, and makes tool selection its own metric.
# OpenAI's function-calling guidance asks for a small, clearly separated tool set for the same reason.
# Cellarium has 73 tools, so the mitigation cannot be "have fewer"; it is that any two tools a reader could
# confuse must each say when to use the other. This sweep measures the confusable pairs and checks they do.
#
# Measured on NAME TOKENS, not on descriptions. The descriptions here are already well separated (the highest
# first-sentence overlap over all 2,628 pairs is 0.25), while the names are what the model reads first in a list
# of 73 — and the one pair this found was identical in four of five name tokens with distinct descriptions.

NAME_OVERLAP_FLAG = 0.5   # Jaccard over `_`-separated name tokens


def confusable_pairs() -> list[dict]:
    """Tool pairs whose NAMES overlap at or above NAME_OVERLAP_FLAG, and whether each description names the
    other tool. A flagged pair that does not cross-reference is the finding."""
    from . import tools
    specs = {t["name"]: (t.get("description") or "") for t in tools.TOOLS}
    names = sorted(specs)
    out = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            ta, tb = set(a.split("_")), set(b.split("_"))
            j = len(ta & tb) / max(len(ta | tb), 1)
            if j < NAME_OVERLAP_FLAG:
                continue
            out.append({"a": a, "b": b, "name_overlap": round(j, 3),
                        "a_names_b": b in specs[a], "b_names_a": a in specs[b],
                        "cross_referenced": (b in specs[a]) or (a in specs[b])})
    return out


# ---- 7. AGREEMENT: two enumerations of one capability must not disagree -------------------------------------
#
# Found 2026-10-28, and NOT by families 1-6: every one of them passed. `design_space` answered a question about
# what can be run; `dial_labels` answered the same question for the Council; `envelope.VALIDATED_PERTURBATIONS`
# decided what `check_feasibility` would accept. All three were complete, deterministic, correctly shaped and
# correctly reasoned IN ISOLATION, and all three disagreed. The agent sees one of them per call and has no way
# to notice.
#
# The cost was measurable: `design_space` omitted `graded_gene_knockout` — 22 corpus rows, its own variant
# module, its own capability record — so an agent asking what it could run was told a launchable perturbation
# did not exist. It also OFFERED two metabolism objective levers that `check_feasibility` refuses, which is the
# tool surface proposing a design the gate rejects in the same turn.
#
# The rule is not "make every list identical" — the levers are deliberately outside the envelope (untested arm,
# FAIL-2/FAIL-3). It is that a disagreement must be DECLARED. A list that differs from the source of truth has
# to say which set it is and why, as `design_space.not_in_envelope` now does.
#
# MAST (Cemri et al. 2025) calls this family "inter-agent misalignment" / "information withholding": the system
# holds the right answer somewhere and the component that needed it was given another one.

def enumeration_agreement() -> list[dict]:
    """Every pair of views that claim to enumerate the same capability, and whether they agree. A disagreement
    is a finding unless the view declares it (an explicitly out-of-envelope list is a declaration)."""
    from . import envelope, instrument, tools
    space = tools.dispatch("design_space", {})
    declared = set(space.get("not_in_envelope") or {})
    views = {
        "envelope.VALIDATED_PERTURBATIONS": set(envelope.VALIDATED_PERTURBATIONS),
        "tools.design_space.variant_types": set(space.get("variant_types") or {}),
        "instrument.dial_labels.perturbations": set(instrument.dial_labels().get("perturbations") or {}),
    }
    truth = views["envelope.VALIDATED_PERTURBATIONS"]
    out = []
    for name, got in views.items():
        missing, extra = sorted(truth - got), sorted(got - truth - declared)
        out.append({"view": name, "n": len(got), "missing_from_view": missing, "not_in_envelope": extra,
                    "agrees": not missing and not extra})
    return out


def channels_declare_when_they_are_recorded() -> list[dict]:
    """A channel the agent can name but the chosen configuration never writes is the 2026-10-27 fault in its
    capability form. Every channel whose recording is conditional must say so where it is advertised."""
    from . import instrument
    conditional = {"ppgpp_conc", "ribosome_conc", "rela_conc"}
    return [{"channel": c, "conditional": c in conditional,
             "declares_recorded_when": bool((meta or {}).get("recorded_when")),
             "ok": (c not in conditional) or bool((meta or {}).get("recorded_when"))}
            for c, meta in instrument.CHANNELS.items()]


# ---- 8. DECLARED SETS: an enum must not lie ------------------------------------------------------------------
#
# Adding enums (ENUM-3 in tools.py) only helps if every declared value is one the tool actually accepts. An enum
# narrower than reality silently forbids valid calls, and the agent has no way to tell that from a real refusal —
# it is the absence family again, moved into the schema. So each declared value is CALLED.
#
# This check earned its place immediately: its first run flagged all eleven of `chart`'s channels, which turned
# out to be the probe failing to pass `result_id` rather than the enum lying. A check that cannot distinguish
# those two would be useless, so tools whose other required arguments cannot be filled are reported as
# `not_exercised` rather than counted as passes.

def every_string_parameter_says_what_it_means() -> list[dict]:
    """A string parameter with an empty description asks the model to guess a value out of nothing. 39 of them
    were doing exactly that on 2026-10-28, and the same names were described on OTHER tools — so what the model
    knew about `reference` depended on which tool it reached for. One row per remaining bare parameter."""
    from . import tools
    out = []
    for t in tools.TOOLS:
        props = ((t.get("input_schema") or {}).get("properties") or {})
        for param, meta in props.items():
            if not isinstance(meta, dict) or meta.get("type") != "string":
                continue
            described = bool((meta.get("description") or "").strip())
            out.append({"tool": t["name"], "param": param, "describes_itself": described,
                        "has_enum": bool(meta.get("enum")), "ok": described})
    return out


def glossary_sites_agree() -> list[dict]:
    """The guard on the glossary itself. One sentence keyed by a parameter NAME is only safe while every site it
    reached means the same thing by that name — `kind` is a species class on three tools and a chart type on
    `chart`. The sites that write their own sentence are not checked; the ones the glossary filled must share an
    enum, so a future bare `kind` on a chart-like tool fails here instead of inheriting the wrong sentence."""
    from . import tools
    out = []
    for param, sites in sorted(tools.glossary_sites().items()):
        enums = {e for _, e in sites}
        out.append({"param": param, "n_sites": len(sites), "tools": [t for t, _ in sites],
                    "distinct_enums": len(enums), "ok": len(enums) <= 1})
    return out


def enum_honesty(calls: dict[str, dict], heavy: bool = False) -> list[dict]:
    """Every enum value of every read-only tool, called. A failure is a declared value the tool rejects as a bad
    argument; `calls` supplies the plausible values for that tool's other arguments."""
    from . import tools
    rows = []
    for t in tools.TOOLS:
        name = t["name"]
        if _skip(name, heavy):
            continue
        props = ((t.get("input_schema") or {}).get("properties") or {})
        for param, meta in props.items():
            if not (isinstance(meta, dict) and meta.get("enum")):
                continue
            base = dict(calls.get(name) or {})
            required = set((t.get("input_schema") or {}).get("required") or [])
            if name not in calls or (required - set(base) - {param}):
                rows.append({"tool": name, "param": param, "verdict": "not_exercised",
                             "n_values": len(meta["enum"])})
                continue
            rejected = []
            for value in meta["enum"]:
                out = call(name, {**base, param: value})
                if out.get("reason") in ("bad_argument", "unknown_entity") or "_exception" in out:
                    rejected.append({"value": value, "error": str(out.get("error") or out.get("_exception"))[:120]})
            rows.append({"tool": name, "param": param, "n_values": len(meta["enum"]),
                         "verdict": "fail" if rejected else "ok", "rejected": rejected})
    return rows


# ---- 9. ONE FACT, ONE RESOLVER -------------------------------------------------------------------------------
#
# The last open item of the discovery-leg audit was `shift_response` refusing a design whose shift is built into
# its variant rather than declared in a timeline. The tool read ONE of the places the fact can live, and stated
# that as a fact about the design: "declares no nutrient shift".
#
# Families 1-8 cannot see this. The answer is complete, deterministic, correctly shaped, carries a registered
# reason and comes from an honest value set — and it is still wrong, because the question was asked of the wrong
# field. So the family is about FACTS rather than about calls: a fact that can be recorded in several places must
# have exactly one function that reads all of them, and nothing else may re-implement the read.
#
# Measured on 2026-10-28, which is why this exists. `multi_gene_knockout/KO:gltX+relA+spoT` is a real corpus
# design, and four parsers gave four answers: 'gltX' (dilution, first gene only), 'gltX+relA+spoT'
# (design_generator, as one gene name), 'gltx+rela+spot' (a lowercased substring key), and the design dropped
# entirely (ko_verify, which skips any key containing '+'). Only the first was a defect in itself; four parsers
# is four chances for the next one to be.

# fact -> what reads it, the marker a re-implementation would have to use, and who may still use that marker.
FACTS = {
    "knockout_genes": {
        "resolver": "model.knockout_genes",
        "places": ["the design label", "a design key with a suffix", "a corpus row's condition", "its label"],
        # Resolvable from the DESIGN alone, so `fine_absence_sweep` requires it to survive an absent
        # measurement: a tool that knows which genes a design knocks out does not stop knowing when the run
        # directory turns out not to be on this machine.
        "from_declaration": True,
        "result_keys": ("knocks_out",),
        "marker": r"""(?:\.split\(\s*["']KO:["']|\.replace\(\s*["']KO:["']|\.startswith\(\s*["']KO:["']"""
                  r"""|["']/?KO:["']\s+in\b)""",
        # Allowed to use the marker, each for a reason that is not "reads the gene list".
        "exempt": {
            "model.py": "defines the resolver",
            "tools.py": "a lowercased SUBSTRING key for a fallback label match, and a display label — neither "
                        "is a gene list",
            "conformance.py": "declares the marker",
            "factors.py": "a segment test (`tag.startswith`), and it must stay one: the resolver answers "
                          "`['4op']`-shaped questions with [] now, but `rRNA_KO:` and `KO:` have to be "
                          "told apart BEFORE the gene list is read, which is what startswith does",
        },
    },
    "shift_time": {
        "resolver": "dynamics.shift_sources",
        "places": ["a declared timeline", "a time encoded in the condition", "in the label", "the caller"],
        # The fact whose loss CI caught on 2026-10-28; see `fine_absence_sweep`.
        "from_declaration": True,
        "result_keys": ("declared_shift_s", "shift_time_from"),
        "marker": r"""declared_events\(""",
        "exempt": {
            "dynamics.py": "defines the resolver",
            "miase.py": "defines declared_events itself",
            "conformance.py": "declares the marker",
        },
    },
}


def one_fact_one_resolver() -> list[dict]:
    """Every module that re-implements a fact's read instead of calling its resolver."""
    import re as _re
    from pathlib import Path as _Path

    out = []
    pkg = _Path(__file__).resolve().parent
    for fact, spec in FACTS.items():
        pat = _re.compile(spec["marker"])
        offenders = []
        for p in sorted(pkg.glob("*.py")):
            if p.name in spec["exempt"]:
                continue
            try:
                lines = p.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith("#"):          # a comment ABOUT the old parse is not the old parse
                    continue
                if pat.search(line):
                    offenders.append({"module": p.name, "line": i, "code": stripped[:110]})
        out.append({"fact": fact, "resolver": spec["resolver"], "n_places": len(spec["places"]),
                    "exempt": sorted(spec["exempt"]), "reimplementations": offenders,
                    "ok": not offenders})
    return out


def a_resolver_reads_every_place_a_fact_can_live() -> list[dict]:
    """The other half: the resolver must actually answer from each declared place, not just exist."""
    from . import dynamics, model
    rows = [
        {"fact": "knockout_genes", "place": "a design label",
         "ok": model.knockout_genes("multi_gene_knockout/KO:gltX+relA+spoT") == ["gltX", "relA", "spoT"]},
        {"fact": "knockout_genes", "place": "a design key with a suffix",
         "ok": model.knockout_genes("gene_knockout/KO:thrC#tl:b0ae2f") == ["thrC"]},
        {"fact": "knockout_genes", "place": "a corpus row's condition",
         "ok": model.knockout_genes({"condition": "KO:pfkA+pfkB"}) == ["pfkA", "pfkB"]},
        {"fact": "knockout_genes", "place": "no knockout at all",
         "ok": model.knockout_genes("wildtype/basal") == []},
        {"fact": "shift_time", "place": "a declared timeline",
         "ok": dynamics.shift_sources("d", {"timeline": "0 minimal, 1200 minimal_plus_amino_acids"})[0][0] == 1200},
        {"fact": "shift_time", "place": "a time encoded in the condition",
         "ok": dynamics.shift_sources("d", {"condition": "with_aa_then_minus_LEU_at_600s"})[0][0] == 600},
        {"fact": "shift_time", "place": "the caller",
         "ok": dynamics.shift_sources("d", {}, at_seconds=900)[0][0] == 900},
        {"fact": "shift_time", "place": "nowhere",
         "ok": dynamics.shift_sources("d", {"condition": "basal"}) == []},
    ]
    return rows
