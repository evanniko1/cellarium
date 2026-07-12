"""Cellarium — a glass-box interface over the whole-cell reasoning pipeline (Streamlit).

Run:
    pip install -U streamlit
    ANTHROPIC_API_KEY=...  WCECOLI_DOCKER=wcecoli-sim:multiko  streamlit run apps/cellarium_ui.py

Two halves of the glass box:
  READ  — for one question: the Socratic Council's Hypothesis (formed BLIND to the data), the grounded agent's
          tool trace (every number from a real run), the answer, and a trust strip (provenance / rigor / safety).
  ACT   — the experiment loop: the Council's falsifier designs become runnable proposals; a human approves each
          one (the airlock — the agent can NEVER launch a sim), the model runs, the result is indexed, and the
          agent can then reason over the new data. propose -> gate -> approve -> run -> result.

A thin renderer over orchestrate.investigate(...) and launch.{propose,list_requests,approve_and_run,reject} —
no new backend logic; all rigor lives in the library.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))  # importable via `streamlit run`

import streamlit as st

from cellarium import ui


# ---------------------------------------------------------------- READ half: the investigation
def _render_hypothesis(hyp) -> None:
    view = ui.hypothesis_view(hyp)
    if not view:
        st.info("Direct mode — no Council; the question went straight to the grounded agent.")
        return
    st.markdown("**🧭 Socratic Council — hypothesis (operationalized *before* any result was read)**")
    for attr, label in [("claim", "Claim"), ("falsifier", "Falsifier"), ("rivals", "Rivals")]:
        if attr in view:
            st.markdown(f"- **{label}:** {view[attr]}")
    with st.expander("Full operationalized brief (H1/H0, operational defs, assumptions, candidate designs)"):
        st.text(view["brief"])


def _render_trust(trace) -> None:
    sig = ui.trust_signals(trace)
    if not sig:
        return
    st.markdown("**🛡️ Trust strip** — rides alongside the answer, never buried")
    cols = st.columns(len(sig))
    for col, (label, val) in zip(cols, sig.items()):
        col.metric(label, str(val)[:22])


def _render_trace(trace) -> None:
    st.markdown(f"**🔎 Grounded reasoning trail** — {len(trace)} tool call(s); every number comes from a real run")
    for i, item in enumerate(ui.trace_view(trace), 1):
        with st.expander(f"{i}. `{item['tool']}`  {json.dumps(item['input'])[:70]}"):
            st.code(json.dumps(item["output"], indent=2)[:2500], language="json")


# ---------------------------------------------------------------- ACT half: the experiment loop
def _queue_design(dv: dict, seeds: int, gens: int) -> None:
    """propose -> vet -> queue (the agent CANNOT do this itself; a human clicks). Never runs; only queues."""
    from cellarium import launch
    gene = dv["genes"][0] if dv["genes"] else None
    launch.propose(dv["perturbation"], dv["condition"], dv["timeline"], dv["params"], int(seeds), int(gens), gene)


def _render_candidate_designs(hyp) -> None:
    designs = getattr(hyp, "candidate_designs", None) or []
    if not designs:
        return
    st.markdown("**🧪 The Council's falsifier designs** — the runnable experiments that would test the hypothesis")
    st.caption("Tune seeds/generations (more seeds → more statistical power, but longer), then queue. Nothing runs "
               "until you approve it below — the agent has no launch button.")
    for i, d in enumerate(designs):
        dv = ui.design_view(d)
        with st.container(border=True):
            genes = f" · genes=`{', '.join(dv['genes'])}`" if dv["genes"] else ""
            cond = f"`{dv['condition']}`" if dv["condition"] else "—"
            st.markdown(f"**{dv['perturbation']}** · condition={cond}{genes}"
                        f"  <span style='opacity:.6'>(Council proposed {dv['seeds']}×{dv['generations']})</span>",
                        unsafe_allow_html=True)
            c1, c2, c3 = st.columns([1, 1, 2])
            seeds = c1.number_input("seeds", 1, max(dv["seeds"], 10), 1, key=f"seeds_{i}")
            gens = c2.number_input("generations", 1, max(dv["generations"], 8), 1, key=f"gens_{i}")
            if c3.button("Queue this experiment ▸", key=f"queue_{i}", use_container_width=True):
                _queue_design(dv, seeds, gens)
                st.rerun()


def _render_custom_proposer() -> None:
    from cellarium import launch
    with st.expander("➕ Propose a custom design"):
        p = st.selectbox("perturbation",
                         ["wildtype", "gene_knockout", "ppgpp_conc", "rrna_operon_knockout", "condition"])
        cond = st.text_input("condition", "basal")
        gene = st.text_input("gene (for a knockout; leave blank otherwise)", "")
        cs, cg = st.columns(2)
        seeds = cs.number_input("seeds", 1, 10, 1, key="custom_seeds")
        gens = cg.number_input("generations", 1, 8, 1, key="custom_gens")
        if st.button("Queue custom design ▸", key="queue_custom"):
            params = {"target_genes": [gene.strip()]} if gene.strip() else {}
            launch.propose(p, cond.strip() or None, None, params, int(seeds), int(gens), gene.strip() or None)
            st.rerun()


def _render_gate(vet: dict) -> None:
    s = ui.vet_summary(vet)
    if not s:
        return
    c1, c2, c3 = st.columns(3)
    c1.markdown(f"🛡️ **safety** · {'✅ ' if s['safety'] == 'clear' else '⛔ '}{s['safety']}")
    c2.markdown(f"📐 **feasibility** · {s['feasibility']}")
    c3.markdown(f"🔬 **provenance** · {s['provenance']}")
    if s["why"]:
        st.caption(s["why"])


def _render_queue() -> None:
    from cellarium import launch
    reqs = launch.list_requests()
    st.markdown("**📋 Launch queue — the human-approval airlock** (safety is the only hard gate; a flagged design "
                "will not run)")
    if not reqs:
        st.caption("Empty — queue one of the Council's designs above, or propose a custom one.")
        return
    for r in reqs:
        with st.container(border=True):
            d = r["design"]
            cond = f"`{d['condition']}`" if d.get("condition") else "—"
            params = f" · params={d['params']}" if d.get("params") else ""
            st.markdown(f"`{r['id']}` — **{d['perturbation']}** · cond={cond}{params} · "
                        f"{r['seeds']}×{r['generations']} — **{r['status']}**")
            if r["status"] == "pending_approval":
                _render_gate(r.get("vet"))
                c1, c2 = st.columns(2)
                if c1.button("✅ Approve & run on the model", key=f"approve_{r['id']}", type="primary"):
                    with st.status(f"Running {r['id']} on the whole-cell model… (Docker; a few minutes)",
                                   expanded=True) as s:
                        res = launch.approve_and_run(r["id"])
                        if res.get("status") == "done":
                            s.update(label=f"Done ✓ {r['id']} — result indexed; ask a follow-up above",
                                     state="complete")
                        else:
                            s.write(res.get("error") or res)
                            s.update(label=f"{res.get('status', 'error')} — {res.get('error', '')}", state="error")
                    st.rerun()
                if c2.button("✋ Reject", key=f"reject_{r['id']}"):
                    launch.reject(r["id"])
                    st.rerun()
            elif r["status"] == "blocked":
                _render_gate(r.get("vet"))
                st.error("SAFETY-BLOCKED — the biosecurity screen flagged this. It will not run (override requires "
                         "editing the queue by hand).")
            elif r["status"] == "done":
                st.success("Ran + indexed — the new data is now agent-visible. Ask a follow-up above and the agent "
                           "will reason over it.")
            elif r["status"] == "failed":
                st.warning("Run failed — check that Docker is up and the design resolves to a runnable variant.")


# ---------------------------------------------------------------- page
st.set_page_config(page_title="Cellarium", layout="wide")
st.title("Cellarium — a glass box over whole-cell reasoning")
st.caption("The Council frames the question blind to data → the agent grounds every number in real runs → "
           "rigor & provenance ride alongside the answer → you close the loop by approving new experiments.")

question = st.text_input("Ask a whole-cell question", "Is pfkA essential in E. coli?")
use_council = st.toggle("Use the Socratic Council (frame → falsifiable hypothesis)", value=True)

if st.button("Investigate", type="primary") and question.strip():
    from cellarium import orchestrate

    trace: list = []
    live = st.container()
    with st.status("Running the pipeline…", expanded=True) as status:
        def on_hyp(h):
            with live:
                _render_hypothesis(h)   # the blind hypothesis, while the tools stream below

        def on_tool(name, inp, out):
            trace.append((name, inp, out))
            status.write(f"⌥ {name}({json.dumps(inp)[:60]})")

        try:
            inv = orchestrate.investigate(question, use_council=use_council,
                                          on_hypothesis=on_hyp, on_tool=on_tool, verbose=False)
            status.update(label="Done ✓", state="complete")
        except Exception as exc:                       # missing API key / Docker / etc. — surface, don't crash
            status.update(label="Error", state="error")
            st.error(f"{type(exc).__name__}: {exc}\n\nLive runs need ANTHROPIC_API_KEY set and Docker up.")
            st.stop()

    st.session_state["inv"] = inv
    st.session_state["trace"] = trace
    st.session_state["council"] = use_council
    st.rerun()   # settle into a single clean render from session_state (survives the loop's button reruns)

# --- render the last investigation + the experiment loop (persist across Queue/Approve/Reject reruns) ---
inv = st.session_state.get("inv")
if inv is not None:
    trace = st.session_state.get("trace", [])
    _render_hypothesis(inv.hypothesis if st.session_state.get("council") else None)
    st.divider()
    _render_trust(trace)
    _render_trace(trace)
    st.divider()
    st.markdown("**💬 Grounded answer**")
    st.markdown(inv.answer)
    st.divider()
    _render_candidate_designs(inv.hypothesis)

# the queue is global + disk-backed — always available to approve/run, even before any question
_render_custom_proposer()
_render_queue()
