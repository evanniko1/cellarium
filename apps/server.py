"""Cellarium — the glass-box web interface (Starlette + a vanilla SPA, no new deps).

Run:
    pip install -U uvicorn            # (uvicorn + starlette are usually already present)
    ANTHROPIC_API_KEY=...  WCECOLI_DOCKER=wcecoli-sim:multiko  python apps/server.py
    # open http://127.0.0.1:8000

A thin transport over the SAME pipeline as the CLI — no rigor lives here:
  POST /api/investigate  -> streams the investigation as NDJSON: {kind, data} lines
                            (hypothesis -> each grounded tool call -> answer + trust strip).
  GET  /api/queue        -> the launch airlock (each request + its approval gate).
  POST /api/propose      -> vet + queue a design (the agent has no launch button).
  POST /api/approve      -> a human approves; the model runs in a background thread (poll /api/queue).
  POST /api/reject       -> drop a queued design.

The heavy imports (council, agent, Docker) are lazy + per-request, so the page serves even with no API key
and errors surface as an event instead of a 500.
"""

from __future__ import annotations

import asyncio
import json
import queue
import sys
import threading
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).resolve().parent))   # for the sibling `sessions` module
from sessions import SessionStore
import hypotheses   # dedicated Hypothesis-Generation surface — persisted Council runs (docs/HYPOTHESIS_MODE_PLAN.md)

WEB = Path(__file__).resolve().parent / "web"

# user-selectable agent models (the model the user converses WITH; the Council keeps its own defaults). "auto"
# routes per turn (see route_model); an explicit pick pins that model.
_OPUS, _SONNET, _HAIKU = "claude-opus-4-8", "claude-sonnet-4-5", "claude-haiku-4-5-20251001"
MODELS = [
    {"id": "auto", "label": "Auto", "note": "routes per question"},
    {"id": _OPUS, "label": "Opus 4.8", "note": "most capable"},
    {"id": _SONNET, "label": "Sonnet 4.5", "note": "balanced"},
    {"id": _HAIKU, "label": "Haiku 4.5", "note": "fastest"},
]
DEFAULT_MODEL = "auto"

# zero-cost per-turn router: reasoning-heavy questions (or a Council-framed investigation) -> Opus; simple
# lookups / very short asks -> Haiku; everything else -> Sonnet. Explicit model choice bypasses this entirely.
_HARD = ("why", "how does", "how do", "mechanism", "explain", "compare", "reroute", "essential", "predict",
         "hypothes", "cause", "versus", " vs ", "trade-off", "tradeoff", "interpret", "diagnos")
_LOOKUP = ("list", "show me", "browse", "what is", "what are", "define", "about the", "how many", "which ",
           "tell me about", "summariz", "look up")


def _route_heuristic(question: str, used_council: bool) -> str:
    q = (question or "").lower()
    if used_council or any(h in q for h in _HARD):
        return _OPUS
    if any(h in q for h in _LOOKUP) or len(q.split()) <= 6:
        return _HAIKU
    return _SONNET


def _classify(question: str):
    """A tiny Haiku call that sizes the question's reasoning difficulty up front. Returns 'lookup'|'moderate'|
    'hard', or None if unavailable (no key / error) so the caller falls back to the keyword heuristic."""
    try:
        import anthropic
        resp = anthropic.Anthropic(max_retries=1).messages.create(
            model=_HAIKU, max_tokens=8,
            system=("Classify the reasoning difficulty of a question about a whole-cell E. coli simulation into "
                    "exactly one lowercase word: 'lookup' (a fact, list, definition, or browse), 'moderate' (a "
                    "single-step analysis), or 'hard' (multi-step mechanistic reasoning, causal explanation, "
                    "comparison, or hypothesis testing). Reply with only that one word."),
            messages=[{"role": "user", "content": question or ""}])
        w = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip().lower()
        for t in ("lookup", "moderate", "hard"):
            if t in w:
                return t
    except Exception:
        return None
    return None


def route_model(question: str, used_council: bool) -> str:
    """Per-turn model selection when the user leaves the model on Auto. A Council-framed investigation is hard by
    construction (-> Opus, no classifier call); otherwise a Haiku classifier sizes it, falling back to the keyword
    heuristic if the classifier is unavailable."""
    if used_council:
        return _OPUS
    tier = _classify(question)
    if tier == "lookup":
        return _HAIKU
    if tier == "moderate":
        return _SONNET
    if tier == "hard":
        return _OPUS
    return _route_heuristic(question, used_council)

# durable conversation memory (SQLite, data/sessions.db): the same messages list carries every prior turn and
# survives a server restart. This is what makes the chat remember (see agent.converse + apps/sessions.py).
SESSIONS = SessionStore()
HYPOTHESES = hypotheses.HypothesisStore()   # persisted Socratic Council deliberations (the Hypothesis surface)


def _jsonsafe(o):
    return json.loads(json.dumps(o, default=str))


# ---------------------------------------------------------------- the investigation stream
async def investigate(request):
    """One turn of the conversation. First turn (new session_id) optionally runs the Council; follow-up turns
    continue the SAME agent message history (memory). Streams: council_round* -> hypothesis? -> tool* -> answer."""
    body = await request.json()
    question = (body.get("question") or "").strip()
    sid = body.get("session_id") or ("s_" + uuid.uuid4().hex[:8])
    use_council = bool(body.get("use_council", False))   # default OFF: the Council is expensive (multi-round, route-bumped) and most turns just want a grounded answer — opt in per investigation
    model = body.get("model") or DEFAULT_MODEL
    reasoning = body.get("reasoning") or "none"
    if not question:
        return JSONResponse({"error": "empty question"}, status_code=400)

    ev: "queue.Queue" = queue.Queue()

    def work():
        from cellarium import agent, council, ui
        sess = SESSIONS.get(sid)
        first_turn = sess is None
        council_signal = use_council if first_turn else bool(sess.get("used_council"))
        routed = model == "auto"
        chosen = route_model(question, council_signal) if routed else model   # per-turn model selection
        trace: list = []

        def on_tool(name, inp, out):
            trace.append((name, inp, out))
            if name in ("propose_experiment", "revise_experiment") and isinstance(out, dict) and out.get("request_id"):
                try:   # stamp the queued job with its provenance (this chat + turn) for click-to-jump-back
                    from cellarium import launch
                    launch.stamp_provenance(out["request_id"], sid, question)
                except Exception:
                    pass
            ev.put(("tool", {"tool": name, "input": _jsonsafe(inp), "output": _jsonsafe(out)}))

        def on_text(delta):
            ev.put(("text", {"delta": delta}))   # token streaming: forward the answer deltas as they arrive

        def on_note(msg):
            ev.put(("note", {"message": msg}))    # transparency: e.g. context compaction happened

        try:
            if first_turn:
                hyp = None
                if use_council:
                    hyp = council.deliberate(question, verbose=False,
                                             on_round=lambda r: ev.put(("council_round", _jsonsafe(r))))
                    view = ui.hypothesis_view(hyp)
                    view["candidate_designs"] = [ui.design_view(d)
                                                 for d in (getattr(hyp, "candidate_designs", None) or [])]
                    ev.put(("hypothesis", view))
                messages = [{"role": "user", "content": agent.first_user_content(question, hyp)}]
                sess = {"messages": messages, "model": chosen, "used_council": use_council, "title": question[:80]}
            else:
                sess["messages"].append({"role": "user", "content": question})   # continue the conversation
                sess["model"] = chosen
            answer = agent.converse(sess["messages"], model=chosen, on_tool=on_tool, on_text=on_text,
                                     on_note=on_note, verbose=False, reasoning=reasoning)
            SESSIONS.put(sid, sess)   # write-through so the conversation survives a restart
            ev.put(("answer", {"answer": answer, "trust": ui.trust_signals(trace), "session_id": sid,
                              "model": chosen, "routed": routed, "first_turn": first_turn}))
        except Exception as exc:                       # missing key / Docker / etc. — surface, don't 500
            ev.put(("error", {"message": f"{type(exc).__name__}: {exc}",
                              "hint": "Live runs need ANTHROPIC_API_KEY set (and Docker up for deep reads)."}))
        finally:
            ev.put(("done", {}))

    threading.Thread(target=work, daemon=True).start()

    async def stream():
        loop = asyncio.get_event_loop()
        while True:
            kind, data = await loop.run_in_executor(None, ev.get)
            yield json.dumps({"kind": kind, "data": data}) + "\n"
            if kind == "done":
                break

    return StreamingResponse(stream(), media_type="application/x-ndjson")


async def hypothesize(request):
    """Run ONE Socratic Council deliberation (blind) as a dedicated, PERSISTED Hypothesis-Generation run — the
    Council split out of the main chat (docs/HYPOTHESIS_MODE_PLAN.md). Streams: round* -> done{run}. The whole run
    (rounds + operationalized hypothesis + falsifier designs) is stored so the surface can re-read it and hand it
    to Cellwright. Blind by construction: the Council never sees corpus results (the quarantine control)."""
    body = await request.json()
    question = (body.get("question") or "").strip()
    model = body.get("model") or DEFAULT_MODEL
    if not question:
        return JSONResponse({"error": "empty question"}, status_code=400)

    ev: "queue.Queue" = queue.Queue()

    def work():
        try:
            run = hypotheses.run_council(HYPOTHESES, question, model=(None if model == "auto" else model),
                                         on_round=lambda rid, p: ev.put(("round", _jsonsafe(p))))
            ev.put(("done", {"run": _jsonsafe(run)}))
        except Exception as exc:
            ev.put(("error", {"message": f"{type(exc).__name__}: {exc}",
                              "hint": "Live Council runs need ANTHROPIC_API_KEY set."}))
            ev.put(("done", {}))

    threading.Thread(target=work, daemon=True).start()

    async def stream():
        loop = asyncio.get_event_loop()
        while True:
            kind, data = await loop.run_in_executor(None, ev.get)
            yield json.dumps({"kind": kind, "data": data}) + "\n"
            if kind == "done":
                break

    return StreamingResponse(stream(), media_type="application/x-ndjson")


async def hypotheses_list(request):
    return JSONResponse({"runs": HYPOTHESES.list()})


async def hypothesis_get(request):
    rid = request.query_params.get("id")
    run = HYPOTHESES.get(rid) if rid else None
    return JSONResponse(run if run else {"error": "not found"}, status_code=(200 if run else 404))


async def hypothesis_delete(request):
    b = await request.json()
    HYPOTHESES.delete(b.get("id"))
    return JSONResponse({"ok": True})


REASONING = [
    {"id": "none", "label": "Standard"},
    {"id": "low", "label": "Extended"},
    {"id": "high", "label": "Extended+"},
]


def models_list(request):
    return JSONResponse({"models": MODELS, "default": DEFAULT_MODEL,
                         "reasoning": REASONING, "reasoning_default": "none"})


async def session_delete(request):
    b = await request.json()
    SESSIONS.delete(b.get("session_id"))   # drop the persisted conversation memory
    return JSONResponse({"ok": True})


async def session_pop(request):
    """Remove the LAST turn (the last user question + its assistant response + tool cycles) from a session, so the
    user can re-ask it. Truncates the agent history back to before the last user(str) message and re-persists."""
    b = await request.json()
    sess = SESSIONS.get(b.get("session_id"))
    if not sess:
        return JSONResponse({"ok": False, "popped": False})
    msgs = sess.get("messages", [])
    last = next((i for i in range(len(msgs) - 1, -1, -1)
                 if msgs[i].get("role") == "user" and isinstance(msgs[i].get("content"), str)), None)
    if last is not None:
        sess["messages"] = msgs[:last]
        SESSIONS.put(b.get("session_id"), sess)
    return JSONResponse({"ok": True, "popped": last is not None})


def results_list(request):
    """The corpus: one deduped row per run (design + qc + provenance). Backs the results browser."""
    from cellarium import store
    try:
        rows = store.list_results()
    except Exception as exc:
        return JSONResponse({"results": [], "count": 0, "error": f"{type(exc).__name__}: {exc}"})
    return JSONResponse({"results": rows, "count": len(rows)})


def result_availability(request):
    """Per-result data availability: raw-local? download-from-HF? regenerate-locally? (wraps hf.data_availability)."""
    from cellarium import hf
    rid = request.query_params.get("id")
    if not rid:
        return JSONResponse({"error": "no id"}, status_code=400)
    try:
        return JSONResponse(hf.data_availability(rid))
    except Exception as exc:
        return JSONResponse({"error": f"{type(exc).__name__}: {exc}"})


# ---------------------------------------------------------------- the experiment loop (airlock)
def queue_list(request):
    from cellarium import launch, ui
    reqs = [r for r in launch.list_requests() if r["status"] not in ("rejected", "superseded")]   # dismissed / revised leave the airlock
    for r in reqs:
        r["gate"] = ui.vet_summary(r.pop("vet", None))
    return JSONResponse({"queue": reqs})


async def queue_clear(request):
    from cellarium import launch
    return JSONResponse(launch.clear_finished())


async def propose(request):
    from cellarium import launch
    b = await request.json()
    res = launch.propose(
        b.get("perturbation", "wildtype"), b.get("condition"), b.get("timeline"),
        b.get("params") or {}, int(b.get("seeds", 1)), int(b.get("generations", 1)), b.get("gene"))
    return JSONResponse(res)


_RUNS: dict = {}


async def approve(request):
    """Human approval. The run (Docker; minutes) goes to a background thread; the client polls /api/queue for
    the status flip (running -> done/failed). The agent still can NEVER reach this endpoint."""
    from cellarium import launch
    b = await request.json()
    rid = b.get("request_id")
    if not rid:
        return JSONResponse({"error": "no request_id"}, status_code=400)

    def run():
        try:
            launch.approve_and_run(rid)               # sets status running -> done/failed on disk
        except Exception:
            pass

    t = threading.Thread(target=run, daemon=True)
    t.start()
    _RUNS[rid] = t
    return JSONResponse({"started": True, "request_id": rid})


async def reject(request):
    from cellarium import launch
    b = await request.json()
    return JSONResponse(launch.reject(b.get("request_id")))


def index(request):
    return FileResponse(WEB / "index.html")


routes = [
    Route("/", index),
    Route("/api/investigate", investigate, methods=["POST"]),
    Route("/api/hypothesis", hypothesize, methods=["POST"]),          # run a Council deliberation (streams rounds, persists)
    Route("/api/hypotheses", hypotheses_list, methods=["GET"]),       # list persisted runs (the surface's run list)
    Route("/api/hypothesis_get", hypothesis_get, methods=["GET"]),    # full run by id
    Route("/api/hypothesis_delete", hypothesis_delete, methods=["POST"]),
    Route("/api/models", models_list, methods=["GET"]),
    Route("/api/session_delete", session_delete, methods=["POST"]),
    Route("/api/session_pop", session_pop, methods=["POST"]),
    Route("/api/results", results_list, methods=["GET"]),
    Route("/api/result_availability", result_availability, methods=["GET"]),
    Route("/api/queue", queue_list, methods=["GET"]),
    Route("/api/queue_clear", queue_clear, methods=["POST"]),
    Route("/api/propose", propose, methods=["POST"]),
    Route("/api/approve", approve, methods=["POST"]),
    Route("/api/reject", reject, methods=["POST"]),
    Mount("/static", app=StaticFiles(directory=str(WEB)), name="static"),
]

app = Starlette(routes=routes)


if __name__ == "__main__":
    import uvicorn

    print("Cellarium -> http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
