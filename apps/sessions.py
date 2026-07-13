"""Durable conversation sessions — a local SQLite store so chats survive a server restart.

Single-user, clone-and-run-local: the server owns the message history (the agent's true context), and this
persists it to data/sessions.db. A hot in-memory cache fronts the DB; every turn write-throughs. Multi-user /
hosted is a documented known limitation (this store is single-writer, no auth).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import time
from pathlib import Path

DB = Path("data/sessions.db")
SEED = Path("data/sessions.seed.db")   # committed demo snapshot; a fresh clone is bootstrapped from it (see _bootstrap)


def _bootstrap(path: Path) -> None:
    """A fresh DEFAULT DB is seeded from the committed snapshot so a clone comes up POPULATED with the demo
    investigations + Council runs. The live DB (data/sessions.db) stays gitignored + mutable, so normal use never
    dirties git; only the frozen seed is tracked. Custom paths (tests) are never seeded."""
    if str(path) == str(DB) and not path.exists() and SEED.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SEED, path)


class SessionStore:
    def __init__(self, path: Path = DB):
        self.path = Path(path)
        self.mem: dict = {}   # sid -> {messages, model, used_council, title}
        _bootstrap(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write("CREATE TABLE IF NOT EXISTS sessions("
                    "sid TEXT PRIMARY KEY, model TEXT, used_council INTEGER, title TEXT, "
                    "messages TEXT, updated REAL)")

    def _write(self, sql: str, params: tuple = ()):   # own connection per op, always closed (no handle leak)
        db = sqlite3.connect(self.path)
        try:
            db.execute(sql, params)
            db.commit()
        finally:
            db.close()

    def _read(self, sql: str, params: tuple = ()):
        db = sqlite3.connect(self.path)
        try:
            return db.execute(sql, params).fetchone()
        finally:
            db.close()

    def get(self, sid: str):
        if sid in self.mem:
            return self.mem[sid]
        row = self._read("SELECT model, used_council, title, messages FROM sessions WHERE sid=?", (sid,))
        if not row:
            return None
        sess = {"model": row[0], "used_council": bool(row[1]), "title": row[2], "messages": json.loads(row[3])}
        self.mem[sid] = sess
        return sess

    def put(self, sid: str, sess: dict) -> None:
        self.mem[sid] = sess
        self._write("INSERT OR REPLACE INTO sessions(sid, model, used_council, title, messages, updated) "
                    "VALUES(?,?,?,?,?,?)",
                    (sid, sess.get("model"), int(bool(sess.get("used_council"))), sess.get("title"),
                     json.dumps(sess.get("messages", []), default=str), time.time()))

    def list(self, limit: int = 300) -> list[dict]:
        """Every persisted session, newest first — the server-side index the client's localStorage doesn't have.
        Powers the Investigations 'saved / backfilled sessions' list, so a session written by another process (the
        eval A/B runner) or lost from localStorage (a cleared / different browser) is still browsable."""
        db = sqlite3.connect(self.path)
        try:
            rows = db.execute("SELECT sid, title, model, updated, LENGTH(messages) FROM sessions "
                              "ORDER BY updated DESC LIMIT ?", (int(limit),)).fetchall()
        finally:
            db.close()
        return [{"sid": r[0], "title": r[1], "model": r[2], "updated": r[3], "bytes": r[4] or 0} for r in rows]

    def delete(self, sid: str) -> None:
        self.mem.pop(sid, None)
        self._write("DELETE FROM sessions WHERE sid=?", (sid,))
