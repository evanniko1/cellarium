"""Durable Council runs — the persistence SessionStore never had.

The Socratic Council's output (the rounds of debate + the operationalized hypothesis + the queue-ready falsifier
designs) was only ever streamed to the front-end and then thrown away — SessionStore keeps `{messages,
used_council, title}`, not the deliberation. This store keeps each run in data/sessions.db (a new `council_runs`
table) so the dedicated Hypothesis-Generation surface can list, re-read, and hand runs off to Cellwright. It is the
lab-notebook the Council was already producing. See docs/HYPOTHESIS_MODE_PLAN.md.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path

DB = Path("data/sessions.db")


class HypothesisStore:
    def __init__(self, path: Path = DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write("CREATE TABLE IF NOT EXISTS council_runs("
                    "id TEXT PRIMARY KEY, question TEXT, status TEXT, model TEXT, "
                    "rounds TEXT, hypothesis TEXT, designs TEXT, meta TEXT, created REAL)")

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
        carrying the SCOPE-ONLY clarifying questions (never a hint at the answer)."""
        self._write("UPDATE council_runs SET status='needs_spec', meta=? WHERE id=?",
                    (json.dumps({"clarifying_questions": gate.get("clarifying_questions") or [],
                                 "missing": gate.get("missing") or []}, default=str), run_id))

    def fail(self, run_id: str, error: str) -> None:
        self._write("UPDATE council_runs SET status='error', meta=? WHERE id=?",
                    (json.dumps({"error": error}), run_id))

    def get(self, run_id: str) -> dict | None:
        row = self._read("SELECT id,question,status,model,rounds,hypothesis,designs,meta,created "
                         "FROM council_runs WHERE id=?", (run_id,))
        return _full(row) if row else None

    def list(self, limit: int = 100) -> list[dict]:
        rows = self._read("SELECT id,question,status,model,rounds,hypothesis,designs,meta,created "
                          "FROM council_runs ORDER BY created DESC LIMIT ?", (int(limit),), many=True)
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
            "claim": hyp.get("claim"), "n_rounds": len(json.loads(r[4] or "[]")),
            "n_designs": len(json.loads(r[6] or "[]")), "converged": meta.get("converged")}


def run_council(store: HypothesisStore, question: str, model: str | None = None, on_round=None) -> dict:
    """Run ONE Council deliberation and persist the whole thing (rounds + operationalized hypothesis + falsifier
    designs + convergence meta). Blind by construction — deliberate() never sees corpus results (the paper's
    quarantine control; see docs/HYPOTHESIS_MODE_PLAN.md). Returns the stored run dict."""
    from cellarium import council, ui   # lazy: the store itself stays dependency-free + unit-testable

    run_id = store.new_id()
    store.create(run_id, question, model)

    def _round(payload):
        store.append_round(run_id, payload)
        if on_round:
            on_round(run_id, payload)

    try:
        # Phase 3(b): scope-only sufficiency gate — blind to the corpus, decide if the question is specified enough
        # to deliberate. If not, park it with clarifying questions (the user refines and re-convenes) — never deliberate
        # a question too vague to yield a decisive test, and never hint at the answer.
        gate = council.sufficiency_gate(question)
        if not gate.get("sufficient") and gate.get("clarifying_questions"):
            store.needs_spec(run_id, gate)
            return store.get(run_id)
        hyp = council.deliberate(question, verbose=False, on_round=_round)
        hview = ui.hypothesis_view(hyp)
        designs = [ui.design_view(d) for d in (getattr(hyp, "candidate_designs", None) or [])]
        ledger = getattr(hyp, "objection_ledger", None) or []
        meta = {"converged": getattr(hyp, "converged", None),
                "rounds_used": getattr(hyp, "rounds_used", None),
                "substantive_objections": getattr(hyp, "substantive_objections", None),
                # per-objection resolution: obj id -> the round that resolved it (null if still open) — the surface
                # renders "resolved in round N" per objection instead of the coarse round-derived "carried".
                "resolutions": {o["id"]: o.get("resolved_round") for o in ledger if o.get("id")}}
        store.complete(run_id, hview, designs, meta)
    except Exception as exc:
        store.fail(run_id, f"{type(exc).__name__}: {exc}")
        raise
    return store.get(run_id)
