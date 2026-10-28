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
        req = (t.get("input_schema") or {}).get("required", [])
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

_COUNT_KEYS = {"n", "n_runs", "n_results", "n_designs", "n_compared", "count", "total", "n_seeds"}


def empty_success(out: dict) -> bool:
    """A result with no error that reports nothing found: a count of 0, or only empty lists. From a source that
    could not be read, this is the silent-absence shape."""
    if not isinstance(out, dict) or any(k in out for k in ("error", "_exception", "refusal")):
        return False
    counts = [v for k, v in out.items() if k in _COUNT_KEYS and isinstance(v, (int, float))]
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
            if _skip(name, heavy) or name not in measurement:
                continue
            out = call(name, args)
            rows.append({"tool": name, "empty_success": empty_success(out),
                         "kind": ("exception" if "_exception" in out else "error" if "error" in out else "result"),
                         "excerpt": json.dumps(out, default=str)[:160]})
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
