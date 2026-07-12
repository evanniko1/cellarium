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

WEB = Path(__file__).resolve().parent / "web"

# user-selectable agent models (the model the user converses WITH; the Council keeps its own defaults)
MODELS = [
    {"id": "claude-opus-4-8", "label": "Opus 4.8", "note": "most capable"},
    {"id": "claude-sonnet-4-5", "label": "Sonnet 4.5", "note": "balanced (default)"},
    {"id": "claude-haiku-4-5-20251001", "label": "Haiku 4.5", "note": "fastest"},
]
DEFAULT_MODEL = "claude-sonnet-4-5"

# in-process conversation memory: session_id -> {messages, model, used_council}. This is what makes the chat
# remember — the same messages list carries every prior turn (see agent.converse).
SESSIONS: dict = {}


def _jsonsafe(o):
    return json.loads(json.dumps(o, default=str))


# ---------------------------------------------------------------- the investigation stream
async def investigate(request):
    """One turn of the conversation. First turn (new session_id) optionally runs the Council; follow-up turns
    continue the SAME agent message history (memory). Streams: council_round* -> hypothesis? -> tool* -> answer."""
    body = await request.json()
    question = (body.get("question") or "").strip()
    sid = body.get("session_id") or ("s_" + uuid.uuid4().hex[:8])
    use_council = bool(body.get("use_council", True))
    model = body.get("model") or DEFAULT_MODEL
    reasoning = body.get("reasoning") or "none"
    if not question:
        return JSONResponse({"error": "empty question"}, status_code=400)

    ev: "queue.Queue" = queue.Queue()

    def work():
        from cellarium import agent, council, ui
        sess = SESSIONS.get(sid)
        first_turn = sess is None
        trace: list = []

        def on_tool(name, inp, out):
            trace.append((name, inp, out))
            ev.put(("tool", {"tool": name, "input": _jsonsafe(inp), "output": _jsonsafe(out)}))

        def on_text(delta):
            ev.put(("text", {"delta": delta}))   # token streaming: forward the answer deltas as they arrive

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
                sess = {"messages": messages, "model": model, "used_council": use_council}
                SESSIONS[sid] = sess
            else:
                sess["messages"].append({"role": "user", "content": question})   # continue the conversation
                sess["model"] = model
            answer = agent.converse(sess["messages"], model=sess["model"], on_tool=on_tool, on_text=on_text,
                                     verbose=False, reasoning=reasoning)
            ev.put(("answer", {"answer": answer, "trust": ui.trust_signals(trace),
                              "session_id": sid, "model": sess["model"], "first_turn": first_turn}))
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
    SESSIONS.pop(b.get("session_id"), None)   # drop the in-process conversation memory
    return JSONResponse({"ok": True})


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
    reqs = [r for r in launch.list_requests() if r["status"] != "rejected"]   # dismissed requests leave the airlock
    for r in reqs:
        r["gate"] = ui.vet_summary(r.pop("vet", None))
    return JSONResponse({"queue": reqs})


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
    Route("/api/models", models_list, methods=["GET"]),
    Route("/api/session_delete", session_delete, methods=["POST"]),
    Route("/api/results", results_list, methods=["GET"]),
    Route("/api/result_availability", result_availability, methods=["GET"]),
    Route("/api/queue", queue_list, methods=["GET"]),
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
