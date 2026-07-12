"""Cellarium — a glass-box interface over the whole-cell reasoning pipeline (Streamlit).

Run:
    pip install -U streamlit
    ANTHROPIC_API_KEY=...  WCECOLI_DOCKER=wcecoli-sim:multiko  streamlit run apps/cellarium_ui.py

For one question it shows: the Socratic Council's Hypothesis (formed BLIND to the data), the grounded agent's
tool trace (every number from a real run), the answer, and a trust strip (provenance / rigor / safety). It is a
thin renderer over orchestrate.investigate(...) via the on_hypothesis / on_tool hooks — no new backend logic.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))  # importable via `streamlit run`

import streamlit as st

from cellarium import ui


def _render_hypothesis(hyp) -> None:
    view = ui.hypothesis_view(hyp)
    if not view:
        st.info("Direct mode — no Council; the question went straight to the grounded agent.")
        return
    st.markdown("**🧭 Socratic Council — hypothesis (operationalized *before* any result was read)**")
    st.success(view["brief"])
    for attr, label in [("claim", "Claim"), ("falsifier", "Falsifier"), ("rivals", "Rivals")]:
        if attr in view:
            st.markdown(f"- **{label}:** {view[attr]}")


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


st.set_page_config(page_title="Cellarium", layout="wide")
st.title("Cellarium — a glass box over whole-cell reasoning")
st.caption("The Council frames the question blind to data → the agent grounds every number in real runs → "
           "rigor & provenance ride alongside the answer.")

question = st.text_input("Ask a whole-cell question", "Is pfkA essential in E. coli?")
use_council = st.toggle("Use the Socratic Council (frame → falsifiable hypothesis)", value=True)

if st.button("Investigate", type="primary") and question.strip():
    from cellarium import orchestrate
    trace: list = []
    hyp_area = st.container()
    with st.status("Running the pipeline…", expanded=True) as status:
        def on_hyp(h):
            with hyp_area:
                _render_hypothesis(h)

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

    if not use_council:
        _render_hypothesis(None)
    st.divider()
    _render_trust(trace)
    _render_trace(trace)
    st.divider()
    st.markdown("**💬 Grounded answer**")
    st.markdown(inv.answer)
