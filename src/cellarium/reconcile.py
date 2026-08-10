"""PLAT-1 — post-hoc CLAIM reconciliation: does the prose assert corpus facts the turn never read?

THE PREDICATE IS INVERTED FROM THE PLATFORM THIS CAME FROM. Theirs guards unexecuted ACTIONS and its predicate
is UI state ("did a confirmation card get created"). Ours guards unsupported CLAIMS and its predicate is the
CORPUS: a corpus identifier named in the answer is grounded when it resolves to a run or design the turn
actually read, and not otherwise.

WHY THE HAYSTACK IS THE CORPUS, NOT THE TOOL OUTPUT (PLAT-R1, recorded as a rejection with its reason). The
obvious implementation — serialize every tool result and ask whether the token appears somewhere in it — makes
presence in a JSON blob stand in for provenance. A seed, an index, a job id or a synthetic placeholder that a
tool happened to emit would pass. Here a mention is checked against the set of run ids and design keys the
MANIFEST knows, and then against what this turn read. A token that is not a corpus identifier at all is prose,
not a claim, and is left alone.

THE THREE RULES THIS FOLLOWS, each of which is a decision rather than an implementation detail:

  (a) ENVELOPE. A tool result that did not read the corpus says so, in the vocabulary D6 already uses. An FBA
      cross-check, a surrogate prediction, a proposed design, a literature fetch and a resource estimate are
      all useful and none of them is a measurement of this corpus. `NOT_A_MEASUREMENT` names every one with
      its reason, and `tests/test_reconcile.py` fails when a new tool is neither classified nor a measurement.
  (b) ANNOTATE, NEVER REWRITE. An unbacked claim gets a note naming which claim and what WAS read. Silently
      repairing the sentence would hide the failure, which is the opposite of recording it — and the note is
      appended, so the original text is always a prefix of the output. There is a test for that.
  (c) FAIL CLOSED. If the turn record is unavailable the verdict is `could_not_verify`, never `verified`.
      Reporting an unavailable check as a pass is the silent-absence bug class this project keeps meeting.

ONE DELIBERATE DEVIATION FROM THE BACKLOG SPEC, stated because it changes what "fail closed" is keyed to. The
spec says to key the check to the durable evidence ledger (`CELLARIUM_EVIDENCE`) and report "could not verify"
when it is off. But that ledger is OFF BY DEFAULT, so keying the check to it would disable the check by
default — a guard against silent absence that is itself silently absent. The turn record here is in-memory,
always on, and costs a set union per tool call; the file ledger remains the durable record and its state is
reported in the payload (`durable_ledger`). Fail-closed is keyed to the real precondition instead: no turn was
recorded, so nothing can be verified.
"""

from __future__ import annotations

import os
import re
import threading

# ------------------------------------------------------------------------------------------------------------
# (a) The EXECUTION envelope. Which tools do NOT read this corpus, and why.
#
# Named `mark_non_measurement` rather than `envelope` because `cellarium.envelope` already exists and means
# something else entirely — whether a proposed DESIGN is inside the model's validated perturbation set. Two
# unrelated senses of "envelope" one import apart is a bug waiting for a tired reader.
# ------------------------------------------------------------------------------------------------------------
# Explicit rather than inferred. A heuristic ("did the result contain run ids?") mislabels a real measurement
# that happens to aggregate, and mislabelling a measurement as a non-measurement makes the check refuse claims
# that are in fact grounded — the false positive that would get this whole feature switched off.
NOT_A_MEASUREMENT: dict[str, str] = {
    # A DIFFERENT MODEL. iML1515 flux balance is an independent oracle, deliberately — it is the cross-check,
    # not the corpus, and a number from it has never been through a whole-cell simulation.
    "fba_growth": "an iML1515 FBA prediction, not a simulation of this corpus",
    "fba_gene_knockout": "an iML1515 FBA/MOMA prediction, not a simulation of this corpus",
    "fba_gene_deletion": "an iML1515 FBA prediction, not a simulation of this corpus",
    "fba_flux": "an iML1515 flux solution, not a simulation of this corpus",
    "fba_essentiality_panel": "an iML1515 essentiality scan, not a simulation of this corpus",
    "fba_synthetic_lethal": "an iML1515 epistasis scan, not a simulation of this corpus",
    "fba_sensitivity": "an iML1515 sensitivity analysis, not a simulation of this corpus",
    "fba_qc": "a check on the FBA model itself",
    "rnaseq_concordance": "an external RNA-seq comparison, not a corpus measurement",
    # A PREDICTION ABOUT RUNS THAT DO NOT EXIST.
    "viability_surrogate": "a surrogate PREDICTION for an unrun design, not a measured outcome",
    "prune_candidates": "a prediction-driven filter over unrun candidates",
    # PROPOSALS. Nothing has been simulated.
    "design_panel": "a proposed panel; nothing here has been run",
    "generate_designs": "enumerated candidate designs; nothing here has been run",
    "propose_experiment": "a proposal; nothing here has been run",
    "propose_experiments": "proposals; nothing here has been run",
    "revise_experiment": "a revised proposal; nothing here has been run",
    "check_feasibility": "a feasibility judgement about an unrun design",
    "vet_hypothesis": "a guardrail check on a hypothesis, not evidence for it",
    "screen_design": "a guardrail screen on an unrun design",
    "screen_phenotype": "a guardrail screen on an unrun design",
    "run_experiment": "a launch; results do not exist until the run finishes and is indexed",
    "propose_rebuild": "a proposed ParCa rebuild; it changes PARAMETERS, it measures nothing",
    # STATEMENTS ABOUT THE INSTRUMENT, not about any run.
    "model_capabilities": "a statement about what the model can represent",
    "operon_mode_advice": "a statement about the model's configuration",
    "deg_rate_provenance": "a statement about a knowledge base's fitted parameters, not about a run",
    "system_resources": "a machine measurement, not a biological one",
    "estimate_sim_resources": "a resource ESTIMATE for work not yet done",
    # OUTSIDE THIS PROJECT ENTIRELY.
    "use_skill": "a literature/publication skill; its content is not this corpus",
    "web_get": "fetched web content; it is not this corpus",
}

_ENVELOPE_KEY = "not_a_measurement"


def mark_non_measurement(tool: str, out):
    """Stamp a non-corpus result with a standing marker saying what it is not.

    The marker rides ON the payload rather than being appended to the prose later, so it reaches the model in
    the same breath as the number — an advisory the agent reads after it has already written the sentence is
    an advisory it has already ignored.
    """
    if not isinstance(out, dict) or tool not in NOT_A_MEASUREMENT:
        return out
    if out.get("error"):
        return out
    out.setdefault(_ENVELOPE_KEY, NOT_A_MEASUREMENT[tool])
    return out


def unclassified_tools(tool_names) -> list[str]:
    """CI exhaustiveness, same shape as `test_registry.unclassified_tools`: every tool is either a corpus
    measurement or explicitly listed above with its reason. A new tool that is neither trips the test and
    forces a one-line decision at add-time rather than defaulting into "this grounds claims"."""
    return sorted(set(tool_names) - set(NOT_A_MEASUREMENT) - set(MEASUREMENT_TOOLS))


MEASUREMENT_TOOLS: frozenset[str] = frozenset({
    # Reads of the corpus itself: rows, series, species, comparisons, verdicts derived from real runs.
    "survey_corpus", "list_results", "design_space", "comparable_designs", "similar_designs",
    "read_series", "read_raw_series", "scan_series", "scan_overview", "variance_band", "trajectory",
    "compare_at_generation", "differential", "top_movers", "list_species", "read_species", "species",
    "exchange_flux", "regulon_response", "lethality_landscape", "viability", "metabolic_essentiality",
    "mechanistic_scope", "trna_families", "selective_charging", "dilution_clock", "shift_response",
    "segment_means", "serialization_check", "experiment_integrity", "reroute_diagnosis", "model_validation",
    "robustness_check", "coverage_check", "corpus_audit", "provenance", "data_availability",
    "raw_available", "download_raw", "chart",
    # Statistical tests over real per-seed evidence — the falsifier vocabulary.
    "disconfirm", "fit_relation", "bimodality", "power_check",
})


# ------------------------------------------------------------------------------------------------------------
# The turn record. What did this turn actually read?
# ------------------------------------------------------------------------------------------------------------
_lock = threading.Lock()
_turn: dict = {}


def start_turn(fresh: bool = True) -> None:
    """Begin recording. Called once per user turn, next to `rigor.reset()`.

    `fresh=False` KEEPS what earlier turns of the same conversation read, and that is not an optimisation —
    it is the difference between a useful check and one nobody reads. Scoped strictly per turn, a correct
    follow-up ("as shown above, KO:argS falls") names a design read in turn 1 and gets annotated in turn 2,
    every time. Found by running it, not by reasoning about it: after a `survey_corpus` the check behaved
    exactly as intended, and the multi-turn case was the one that would have cried wolf in normal use.
    `converse` passes `fresh=True` only for a conversation's first turn.
    """
    with _lock:
        if fresh or not _turn.get("armed"):
            _turn.clear()
            _turn.update({"armed": True, "ids": set(), "designs": set(),
                          "measurement_calls": 0, "non_measurement_calls": {}})
        else:
            _turn["non_measurement_calls"] = {}      # per-turn: which non-corpus tools ran just now


def record_call(tool: str, out) -> None:
    """Fold one tool result into the turn record. Never raises: a bookkeeping sink must not be able to break a
    live tool call, the same rule `evidence.record` and `observability.emit` follow."""
    try:
        with _lock:
            if not _turn.get("armed"):
                return
            if tool in NOT_A_MEASUREMENT:
                d = _turn["non_measurement_calls"]
                d[tool] = d.get(tool, 0) + 1
                return
            if isinstance(out, dict) and out.get("error"):
                return                      # a failed read read nothing
            from . import evidence
            ids: set = set()
            designs: set = set()
            evidence._harvest(out, ids, designs)      # the SAME extraction the durable ledger uses
            _turn["ids"] |= ids
            _turn["designs"] |= designs
            _turn["measurement_calls"] += 1
    except Exception:
        pass


def turn_record() -> dict:
    with _lock:
        return {"armed": bool(_turn.get("armed")),
                "ids": set(_turn.get("ids") or ()), "designs": set(_turn.get("designs") or ()),
                "measurement_calls": int(_turn.get("measurement_calls") or 0),
                "non_measurement_calls": dict(_turn.get("non_measurement_calls") or {})}


# ------------------------------------------------------------------------------------------------------------
# (b) Reconciliation.
# ------------------------------------------------------------------------------------------------------------
# A design key is `perturbation/tag` (survey.design_key). Matched loosely here and then RESOLVED against the
# manifest, so the regex only has to be permissive enough to catch candidates — it never decides anything.
_DESIGN_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9_]*/[A-Za-z0-9_:.+·-]+")
_ID_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9_.-]{3,}\b")

# Phrases that mark a mention as explicitly NOT a claim of having read it. "I did not examine
# gene_knockout/KO:pfkA" names a design the turn never read, correctly, and flagging it would train the reader
# to ignore the annotation.
_DISCLAIMED = ("did not", "didn't", "not read", "not examine", "unexamined", "no runs", "not in the corpus",
               "was not", "were not", "cannot", "can't", "unable", "absent", "no such", "not available")

_corpus_cache: dict | None = None


def corpus_identifiers(refresh: bool = False) -> dict:
    """Every run id and design key the manifest knows — the haystack a mention has to resolve against.

    Cached: this is a full manifest read and reconciliation runs once per turn. `refresh=True` for tests.
    """
    global _corpus_cache
    if _corpus_cache is not None and not refresh:
        return _corpus_cache
    ids: set = set()
    designs: set = set()
    try:
        from . import store, survey
        for r in store.list_results(include_dropped=True):
            if r.get("id"):
                ids.add(str(r["id"]))
            try:
                designs.add(survey.design_key(r))
            except Exception:
                continue
    except Exception:
        _corpus_cache = {"ids": set(), "designs": set(), "available": False}
        return _corpus_cache
    _corpus_cache = {"ids": ids, "designs": designs, "available": True}
    return _corpus_cache


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+|\n+", text or "") if s.strip()]


def reconcile(prose: str, *, corpus: dict | None = None) -> dict:
    """Cross-check the assembled answer against what this turn actually read.

    Returns a verdict, the mentions that did not resolve to this turn's evidence, and what WAS read. The
    verdict is one of:

      `could_not_verify` — no turn was recorded, or the manifest is unreadable. NEVER a pass.
      `no_corpus_claims` — the answer names no corpus identifier at all.
      `grounded`         — every corpus identifier it names was read this turn.
      `unbacked_claims`  — at least one was not.
    """
    rec = turn_record()
    corpus = corpus if corpus is not None else corpus_identifiers()
    base = {"read_run_ids": sorted(rec["ids"])[:40], "read_designs": sorted(rec["designs"])[:40],
            "scope": "this conversation",
            "n_measurement_calls": rec["measurement_calls"],
            "non_measurement_calls": rec["non_measurement_calls"],
            "durable_ledger": _durable_state()}

    if not rec["armed"] or not corpus.get("available"):
        return {**base, "verdict": "could_not_verify", "unbacked": [],
                "why": ("no turn record" if not rec["armed"] else "the manifest could not be read") +
                       " — this check reports that it could not run, never that the answer passed"}

    known_designs, known_ids = corpus["designs"], corpus["ids"]
    unbacked: list[dict] = []
    seen: set = set()
    n_mentions = 0
    for sent in _sentences(prose):
        low = sent.lower()
        disclaimed = any(p in low for p in _DISCLAIMED)
        cands = set(_DESIGN_RE.findall(sent)) | set(_ID_RE.findall(sent))
        for tok in cands:
            t = tok.strip(".,;:)")
            kind = "design" if t in known_designs else ("run_id" if t in known_ids else None)
            if kind is None:
                continue                       # not a corpus identifier -> prose, not a claim
            n_mentions += 1
            if t in (rec["designs"] if kind == "design" else rec["ids"]):
                continue
            if disclaimed or t in seen:
                continue
            seen.add(t)
            unbacked.append({"mention": t, "kind": kind, "sentence": sent.strip()[:240]})

    if not n_mentions:
        return {**base, "verdict": "no_corpus_claims", "unbacked": [],
                "why": "the answer names no run id or design key the manifest knows"}
    if not unbacked:
        return {**base, "verdict": "grounded", "unbacked": [], "n_mentions": n_mentions,
                "why": "every corpus identifier named in the answer was read by a tool call in this conversation"}
    return {**base, "verdict": "unbacked_claims", "unbacked": unbacked, "n_mentions": n_mentions,
            "why": ("these corpus identifiers are named in the answer but no tool call in this conversation "
                    "read them; "
                    "a value that resolves to the manifest is not the same as a value this answer measured")}


def _durable_state() -> str:
    try:
        from . import evidence
        return "on" if evidence.enabled() else "off (CELLARIUM_EVIDENCE=1 to persist)"
    except Exception:
        return "unknown"


# ------------------------------------------------------------------------------------------------------------
# (c) Annotate. Never rewrite.
# ------------------------------------------------------------------------------------------------------------
def annotation(result: dict) -> str:
    """The note to append, or "" when there is nothing to say.

    Deliberately silent on `grounded` and `no_corpus_claims`: a banner on every answer saying "checked, fine"
    trains the reader to skip the banner, and then the one that matters is skipped too.
    """
    v = result.get("verdict")
    if v == "unbacked_claims":
        read = ", ".join(result.get("read_designs") or result.get("read_run_ids") or []) or "nothing"
        lines = ["", "---", "**Provenance check — claims this conversation did not read.** The answer above "
                 "names corpus identifiers that no tool call in this conversation retrieved. They are left "
                 "exactly as written; "
                 "this note is the record, not a correction."]
        for u in result["unbacked"][:8]:
            lines.append(f"- `{u['mention']}` ({u['kind']}) — in: “{u['sentence']}”")
        extra = len(result["unbacked"]) - 8
        if extra > 0:
            lines.append(f"- …and {extra} more.")
        lines.append(f"\nWhat this turn actually read: {read}.")
        nm = result.get("non_measurement_calls") or {}
        if nm:
            lines.append("Non-corpus tools also ran this turn (their output is not a measurement of this "
                         "corpus): " + ", ".join(f"`{k}`×{v}" for k, v in sorted(nm.items())) + ".")
        return "\n".join(lines)
    if v == "could_not_verify":
        return ("\n\n---\n**Provenance check could not run** — " + str(result.get("why", "")) +
                ". Treat this as unverified, not as verified.")
    return ""


def enabled() -> bool:
    """On by default. A guard against silent absence that is itself off by default guards nothing; the escape
    hatch exists for evals that assert on exact answer text."""
    return os.environ.get("CELLARIUM_RECONCILE", "1").strip().lower() not in ("0", "false", "no")


def check_and_annotate(prose: str) -> str:
    """The one call `converse` makes. Returns the answer with a note appended when there is one to append —
    and returns the prose UNCHANGED on any internal failure, because a provenance check that can break the
    answer is worse than the absence it is guarding against."""
    if not enabled() or not prose:
        return prose
    try:
        return prose + annotation(reconcile(prose))
    except Exception:
        return prose
