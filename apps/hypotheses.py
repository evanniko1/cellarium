"""Durable Council runs — the persistence SessionStore never had.

The Socratic Council's output (the rounds of debate + the operationalized hypothesis + the queue-ready falsifier
designs) was only ever streamed to the front-end and then thrown away — SessionStore keeps `{messages,
used_council, title}`, not the deliberation. This store keeps each run in data/sessions.db (a new `council_runs`
table) so the dedicated Hypothesis-Generation surface can list, re-read, and hand runs off to Cellwright. It is the
lab-notebook the Council was already producing. See docs/HYPOTHESIS_MODE_PLAN.md.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import time
import uuid
from pathlib import Path

DB = Path("data/sessions.db")
SEED = Path("data/sessions.seed.db")   # committed demo snapshot; shared bootstrap with SessionStore (one DB file)


def _bootstrap(path: Path) -> None:
    """Seed a fresh DEFAULT DB from the committed snapshot (same DB file SessionStore uses) so a clone comes up with
    the demo Council runs + investigations. Whichever store is constructed first does the copy; the other sees the
    file and skips. Custom paths (tests) are never seeded. Mirrors apps/sessions._bootstrap."""
    if str(path) == str(DB) and not path.exists() and SEED.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SEED, path)


class HypothesisStore:
    def __init__(self, path: Path = DB):
        self.path = Path(path)
        _bootstrap(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write("CREATE TABLE IF NOT EXISTS council_runs("
                    "id TEXT PRIMARY KEY, question TEXT, status TEXT, model TEXT, "
                    "rounds TEXT, hypothesis TEXT, designs TEXT, meta TEXT, created REAL)")
        try:   # a user-set display label for the run list (migration for pre-existing DBs)
            self._write("ALTER TABLE council_runs ADD COLUMN title TEXT")
        except Exception:
            pass   # column already present

    def _write(self, sql: str, params: tuple = ()):   # own connection per op, always closed (mirrors SessionStore)
        db = sqlite3.connect(self.path)
        try:
            db.execute(sql, params)
            db.commit()
        finally:
            db.close()

    def _read(self, sql: str, params: tuple = (), many: bool = False):
        db = sqlite3.connect(self.path)
        try:
            cur = db.execute(sql, params)
            return cur.fetchall() if many else cur.fetchone()
        finally:
            db.close()

    def new_id(self) -> str:
        return "h_" + uuid.uuid4().hex[:10]

    def create(self, run_id: str, question: str, model: str | None) -> None:
        """Insert a run in 'running' state so the surface can show it live as rounds stream in."""
        self._write("INSERT OR REPLACE INTO council_runs"
                    "(id, question, status, model, rounds, hypothesis, designs, meta, created) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (run_id, question, "running", model, "[]", "{}", "[]", "{}", time.time()))

    def append_round(self, run_id: str, round_payload: dict) -> None:
        row = self._read("SELECT rounds FROM council_runs WHERE id=?", (run_id,))
        rounds = json.loads(row[0]) if row and row[0] else []
        rounds.append(round_payload)
        self._write("UPDATE council_runs SET rounds=? WHERE id=?", (json.dumps(rounds, default=str), run_id))

    def complete(self, run_id: str, hypothesis: dict, designs: list, meta: dict) -> None:
        self._write("UPDATE council_runs SET status='done', hypothesis=?, designs=?, meta=? WHERE id=?",
                    (json.dumps(hypothesis, default=str), json.dumps(designs, default=str),
                     json.dumps(meta, default=str), run_id))

    def needs_spec(self, run_id: str, gate: dict) -> None:
        """The sufficiency gate found the question underspecified: park the run awaiting the user's specification,
        carrying the SCOPE-ONLY clarifying questions (never a hint at the answer) + a concrete example. `capped`
        marks the cached firm nudge shown after a repeated insufficient reply."""
        self._write("UPDATE council_runs SET status='needs_spec', meta=? WHERE id=?",
                    (json.dumps({"clarifying_questions": gate.get("clarifying_questions") or [],
                                 "missing": gate.get("missing") or [],
                                 "example": gate.get("example"), "capped": bool(gate.get("capped"))},
                                default=str), run_id))

    def fail(self, run_id: str, error: str) -> None:
        self._write("UPDATE council_runs SET status='error', meta=? WHERE id=?",
                    (json.dumps({"error": error}), run_id))

    def get(self, run_id: str) -> dict | None:
        row = self._read("SELECT id,question,status,model,rounds,hypothesis,designs,meta,created "
                         "FROM council_runs WHERE id=?", (run_id,))
        return _full(row) if row else None

    def rename(self, run_id: str, title: str) -> None:
        self._write("UPDATE council_runs SET title=? WHERE id=?", (title, run_id))

    def list(self, limit: int = 100) -> list[dict]:
        # exclude 'needs_spec' — a parked gate result is a transient interaction, not a hypothesis; it lives in the
        # detail pane until the user specifies (or abandons it), and must not clutter the run list with dead-ends.
        rows = self._read("SELECT id,question,status,model,rounds,hypothesis,designs,meta,created,title "
                          "FROM council_runs WHERE status != 'needs_spec' ORDER BY created DESC LIMIT ?",
                          (int(limit),), many=True)
        return [_summary(r) for r in rows]

    def delete(self, run_id: str) -> None:
        self._write("DELETE FROM council_runs WHERE id=?", (run_id,))


def _full(r) -> dict:
    return {"id": r[0], "question": r[1], "status": r[2], "model": r[3],
            "rounds": json.loads(r[4] or "[]"), "hypothesis": json.loads(r[5] or "{}"),
            "designs": json.loads(r[6] or "[]"), "meta": json.loads(r[7] or "{}"), "created": r[8]}


def _summary(r) -> dict:
    """Compact list-view row for the surface's run list — no heavy rounds/designs blobs."""
    hyp, meta = json.loads(r[5] or "{}"), json.loads(r[7] or "{}")
    return {"id": r[0], "question": r[1], "status": r[2], "created": r[8],
            "title": (r[9] if len(r) > 9 else None),   # user-set display label (rename)
            "claim": hyp.get("claim"), "n_rounds": len(json.loads(r[4] or "[]")),
            "n_designs": len(json.loads(r[6] or "[]")), "converged": meta.get("converged")}


# Soft-nudge design (never block): the Council's job is to MIDWIFE a vague scientific question into a falsifiable
# hypothesis (Socratic maieutics), and it has its own D3 escalation for irreducible ambiguity — so we never refuse
# to deliberate. When the question is under-specified we carry a NON-BLOCKING advisory hint (council.sharpening_hint,
# a deterministic pre-pass, no model call) that names only the still-missing axes; the run still completes. The old
# blocking gate parked ~23/25 canonical questions — exactly the Council's own competency (evals/run_ab.py) — so a
# hard block was the wrong tool. M-7: on a re-convene the hint narrows progressively (asks only what's still missing).


def run_council(store: HypothesisStore, question: str, model: str | None = None, on_round=None,
                attempt: int = 0, reuse_id: str | None = None, prior_question: str | None = None) -> dict:
    """Run ONE Council deliberation and persist the whole thing (rounds + operationalized hypothesis + falsifier
    designs + convergence meta). Blind by construction — deliberate() never sees corpus results (the paper's
    quarantine control; see docs/HYPOTHESIS_MODE_PLAN.md). NEVER blocks: a broad question is still deliberated (the
    Council midwifes it) and only carries a non-blocking sharpening hint; genuine ambiguity is handled by the
    Council's own D3 escalation mid-deliberation, not by refusing up front. `attempt` is vestigial (kept for API
    compatibility with the old gate); `reuse_id` overwrites the same row on a re-convene. `prior_question` (M-7) is
    the previous attempt's text, so the nudge narrows progressively; if omitted it is recovered from `reuse_id`'s row
    BEFORE it is overwritten. Returns the stored run."""
    from cellarium import agent, council, observability, provenance, ui  # lazy: store stays dependency-free/testable

    # M-7: capture the prior question before create() overwrites the reused row, so the nudge can ask only what's new.
    if prior_question is None and reuse_id:
        prev = store.get(reuse_id)
        prior_question = prev.get("question") if prev else None

    run_id = reuse_id or store.new_id()
    store.create(run_id, question, model)

    def _round(payload):
        store.append_round(run_id, payload)
        if on_round:
            on_round(run_id, payload)

    try:
        broad = not council.looks_specific(question)   # deterministic, no model call — a soft nudge, not a gate
        nudge = council.sharpening_hint(question, prior_question)   # M-7: axis-targeted, progressive, blind, optional
        # a PICKED model drives the Council's roles; model=None (Auto) -> the Council's tuned default
        cmodels = {"proposer": model, "skeptic": model, "judge": model} if model else None
        temperature = agent.temperature_for(model)   # pinned for reproducibility (M-2); None for a picked reasoning model
        # LLM-2: meter this deliberation's proposer/skeptic/judge calls (tokens, est. USD, wall-time, per-role split)
        with observability.meter() as _meter:
            hyp = council.deliberate(question, verbose=False, on_round=_round, models=cmodels, temperature=temperature)
        hview = ui.hypothesis_view(hyp)
        designs = [ui.design_view(d) for d in (getattr(hyp, "candidate_designs", None) or [])]
        ledger = getattr(hyp, "objection_ledger", None) or []
        meta = {"converged": getattr(hyp, "converged", None),
                "rounds_used": getattr(hyp, "rounds_used", None),
                "substantive_objections": getattr(hyp, "substantive_objections", None),
                # per-objection resolution: obj id -> the round that resolved it (null if still open) — the surface
                # renders "resolved in round N" per objection instead of the coarse round-derived "carried".
                "resolutions": {o["id"]: o.get("resolved_round") for o in ledger if o.get("id")},
                # reproducibility provenance (M-2): the sampling variance source is now named + recorded
                "temperature": temperature, "model": (model or "auto"),
                # environment provenance (H-3): interpreter + git commit + pinned dep versions, so a run reproduces
                # against the exact code + stack (full pin set in requirements.lock)
                "environment": provenance.run_environment(),
                # observability (LLM-2): this run's model-call cost/latency aggregate (tokens, est. USD, per-role)
                "llm": _meter.summary(),
                # soft, non-blocking sharpening nudge (advisory only — the run still completed). M-7: the hint names
                # only the still-missing axes and, on a re-convene, acknowledges what the refinement already supplied.
                "broad_question": broad, "hint": (nudge["text"] if nudge else None),
                "missing_axes": (nudge["missing"] if nudge else []),
                "narrowing": (nudge["progress"] if nudge else None)}
        store.complete(run_id, hview, designs, meta)
        try:   # self-harness (M-1): file any Council-named test the toolkit can't run. Best-effort — the
            from cellarium import harness  # detector already swallows its own errors; a gap must never break a run.
            harness.scan_and_file(hyp, run_id)
        except Exception:
            pass
    except Exception as exc:
        store.fail(run_id, f"{type(exc).__name__}: {exc}")
        raise
    return store.get(run_id)
