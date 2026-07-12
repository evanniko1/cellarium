"use strict";
// Cellarium SPA — a thin client over the streaming pipeline. No framework; the rigor lives in the backend.

const $ = (s, r = document) => r.querySelector(s);
function el(tag, cls, html) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html != null) e.innerHTML = html;
  return e;
}
const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const trunc = (s, n) => (s.length > n ? s.slice(0, n - 1) + "…" : s);

// minimal markdown -> HTML for the grounded answer (bold, code, lists, paragraphs)
function md(src) {
  let s = esc(src);
  s = s.replace(/`([^`]+)`/g, (_, c) => "<code>" + c + "</code>");
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  const blocks = s.split(/\n\n+/).map((b) => {
    if (/^\s*[-*]\s+/.test(b)) {
      const items = b.split(/\n/).filter((x) => x.trim())
        .map((x) => "<li>" + x.replace(/^\s*[-*]\s+/, "") + "</li>").join("");
      return "<ul>" + items + "</ul>";
    }
    return "<p>" + b.replace(/\n/g, "<br>") + "</p>";
  });
  return blocks.join("");
}

const state = { thread: $("#thread"), recents: [], candidates: [], trailLine: null, grounding: null, poll: null, running: false };

// ---------------- investigate (stream) ----------------
async function investigate(question) {
  if (state.running) return;
  state.running = true;
  const useCouncil = $("#council").checked;
  $("#composerWrap").classList.add("docked");
  $("#send").disabled = true;
  addRecent(question);

  state.thread.innerHTML = "";
  state.candidates = [];
  state.thread.appendChild(el("div", "userq", esc(question)));

  // reasoning trail scaffold
  const trail = el("section", "trail");
  trail.appendChild(el("div", "trail-head", '<span class="pill ghost">🔎 grounded reasoning trail</span>' +
    '<span class="card-title">every number comes from a real run</span>'));
  state.trailLine = el("div", "trail-line");
  trail.appendChild(state.trailLine);
  state.grounding = el("div", "grounding", '<span class="dot-pulse"></span> grounding against the corpus…');
  trail.appendChild(state.grounding);

  try {
    const resp = await fetch("/api/investigate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, use_council: useCouncil }),
    });
    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    let trailMounted = false;
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, i); buf = buf.slice(i + 1);
        if (!line.trim()) continue;
        const { kind, data } = JSON.parse(line);
        if (kind === "hypothesis") {
          renderHypothesis(data);
        }
        if (!trailMounted && (kind === "tool" || kind === "answer")) {
          state.thread.appendChild(trail); trailMounted = true;   // trail sits below the hypothesis
        }
        if (kind === "tool") addTool(data);
        if (kind === "answer") renderAnswer(data);
        if (kind === "error") renderError(data);
        if (kind === "done") { if (state.grounding) state.grounding.remove(); }
      }
    }
  } catch (e) {
    renderError({ message: String(e) });
  } finally {
    state.running = false;
    $("#send").disabled = false;
  }
}

// ---------------- renderers ----------------
function renderHypothesis(v) {
  state.candidates = v.candidate_designs || [];
  const c = el("section", "card hyp-card");
  c.appendChild(el("div", "card-head",
    '<span class="pill">🧭 Socratic Council</span>' +
    '<span class="card-title">operationalized before any result was read</span>'));
  if (v.claim) c.appendChild(el("div", "hyp-field", `<span class="label">Claim</span> ${esc(v.claim)}`));
  if (v.falsifier) c.appendChild(el("div", "hyp-field", `<span class="label">Falsifier</span> ${esc(v.falsifier)}`));
  if (v.rivals) {
    const wrap = el("div", "hyp-field", '<span class="label">Rivals</span>');
    const ul = el("ul", "rivals");
    String(v.rivals).split(/Rival\(/).filter((x) => x.trim() && x.includes("claim="))
      .forEach((r) => ul.appendChild(el("li", null, esc(trunc(r.replace(/^claim=/, "").replace(/'\)?,?\s*$/, ""), 220)))));
    if (!ul.children.length) ul.appendChild(el("li", null, esc(trunc(String(v.rivals), 260))));
    wrap.appendChild(ul); c.appendChild(wrap);
  }
  if (v.brief) {
    const d = el("details", "brief");
    d.appendChild(el("summary", null, "Full operationalized brief — H1/H0, defs, assumptions, candidate designs"));
    d.appendChild(el("pre", null, esc(v.brief)));
    c.appendChild(d);
  }
  state.thread.appendChild(c);
}

function verdictOf(out) {
  if (!out || typeof out !== "object") return "";
  if ("verdict" in out) return String(out.verdict);
  if ("adequately_powered" in out) return out.adequately_powered === false ? "under-powered" : "powered";
  if ("flags" in out) return out.flags && out.flags.length ? "flagged" : "clear";
  if ("provenance" in out) return String(out.provenance);
  if ("class" in out) return String(out.class);
  if ("in_envelope" in out) return out.in_envelope ? "in-envelope" : "boundary";
  if ("status" in out) return String(out.status);
  return "";
}

function addTool(d) {
  if (state.grounding) { state.grounding.remove(); state.trailLine.parentNode.appendChild(state.grounding); }
  const t = el("details", "tool");
  const v = verdictOf(d.output);
  const arg = trunc(JSON.stringify(d.input), 52).replace(/^\{|\}$/g, "");
  t.appendChild(el("summary", null,
    `<span class="tname">${esc(d.tool)}</span><span class="targ">${esc(arg)}</span>` +
    (v ? `<span class="verdict">${esc(trunc(v, 22))}</span>` : "")));
  t.appendChild(el("pre", null, esc(JSON.stringify(d.output, null, 2))));
  state.trailLine.appendChild(t);
}

function renderAnswer(d) {
  const c = el("section", "card answer-card");
  c.appendChild(el("div", "card-head", '<span class="pill">💬 grounded answer</span>'));
  c.appendChild(el("div", "answer-body", md(d.answer)));
  state.thread.appendChild(c);
  renderTrust(d.trust || {});
  renderCandidates();
  refreshQueue();
}

const TRUST_CLASS = (k, v) => {
  v = String(v).toLowerCase();
  if (/flag/.test(v)) return "bad";
  if (/under-powered|challenged|refuted|dead|infeasible/.test(v)) return "warn";
  if (/out_of_sample|survived|powered|clear/.test(v)) return "good";
  return "";
};
function renderTrust(sig) {
  const keys = Object.keys(sig);
  if (!keys.length) return;
  const box = el("div", "trust");
  keys.forEach((k) => box.appendChild(el("div", "tchip " + TRUST_CLASS(k, sig[k]),
    `<span class="k">${esc(k)}</span><span class="v">${esc(trunc(String(sig[k]), 24))}</span>`)));
  state.thread.appendChild(box);
}

// ---------------- experiment loop ----------------
function renderCandidates() {
  if (!state.candidates.length) return;
  const loop = el("section", "loop");
  loop.appendChild(el("div", "loop-title", "🧪 The Council's falsifier designs"));
  loop.appendChild(el("div", "loop-sub",
    "The runnable experiments that would test the hypothesis. Tune the run, then queue — the agent has no launch button; you approve every run below."));
  state.candidates.forEach((dv, i) => {
    const genes = (dv.genes && dv.genes.length) ? ` · genes=${dv.genes.join(",")}` : "";
    const row = el("div", "design");
    row.appendChild(el("div", "d-main",
      `<div class="d-name"><span class="pert">${esc(dv.perturbation)}</span>` +
      (dv.condition ? ` · ${esc(dv.condition)}` : "") + `</div>` +
      `<div class="d-meta">${esc(genes ? genes.slice(3) : "control")} · Council proposed ${dv.seeds}×${dv.generations}</div>`));
    const sSeeds = el("div", "stepper", `<label>seeds</label>`);
    const iSeeds = el("input"); iSeeds.type = "number"; iSeeds.min = 1; iSeeds.value = 1; sSeeds.appendChild(iSeeds);
    const sGens = el("div", "stepper", `<label>gens</label>`);
    const iGens = el("input"); iGens.type = "number"; iGens.min = 1; iGens.value = 1; sGens.appendChild(iGens);
    const btn = el("button", "btn primary", "Queue this experiment →");
    btn.onclick = () => queueDesign(dv, +iSeeds.value, +iGens.value, btn);
    row.append(sSeeds, sGens, btn);
    loop.appendChild(row);
  });
  state.thread.appendChild(loop);
}

async function queueDesign(dv, seeds, gens, btn) {
  btn.disabled = true; btn.textContent = "Queuing…";
  const res = await postJSON("/api/propose", {
    perturbation: dv.perturbation, condition: dv.condition, timeline: dv.timeline,
    params: dv.params || {}, gene: (dv.genes && dv.genes[0]) || null, seeds, generations: gens,
  });
  btn.disabled = false; btn.textContent = "Queue this experiment →";
  if (res.error) { alert(res.error); return; }
  refreshQueue();
}

async function refreshQueue() {
  const { queue } = await (await fetch("/api/queue")).json();
  let box = $("#queueBox");
  if (!box) {
    box = el("section", "loop"); box.id = "queueBox";
    state.thread.appendChild(box);
  }
  box.innerHTML = "";
  box.appendChild(el("div", "loop-title", "📋 Launch queue — the human-approval airlock"));
  box.appendChild(el("div", "loop-sub", "Safety is the only hard gate; a flagged design will not run."));
  if (!queue.length) { box.appendChild(el("div", "empty", "Empty — queue one of the Council's designs above.")); return; }
  let anyRunning = false;
  queue.forEach((r) => { if (r.status === "running") anyRunning = true; box.appendChild(qitem(r)); });
  if (anyRunning) { clearTimeout(state.poll); state.poll = setTimeout(refreshQueue, 3000); }
}

function qitem(r) {
  const d = r.design || {};
  const it = el("div", "qitem");
  const top = el("div", "q-top",
    `<span class="q-id">${esc(r.id)}</span>` +
    `<span class="q-design"><b>${esc(d.perturbation)}</b>` + (d.condition ? ` · ${esc(d.condition)}` : "") +
    ` · ${r.seeds}×${r.generations}</span>` +
    `<span class="status ${esc(r.status)}">${esc(r.status.replace(/_/g, " "))}</span>`);
  it.appendChild(top);

  const g = r.gate || {};
  if (g.safety) {
    const gate = el("div", "gate");
    gate.appendChild(el("div", "g " + (g.safety === "clear" ? "ok" : "stop"), `🛡️ safety <b>${esc(g.safety)}</b>`));
    gate.appendChild(el("div", "g", `📐 feasibility <b>${esc(g.feasibility)}</b>`));
    gate.appendChild(el("div", "g", `🔬 provenance <b>${esc(g.provenance)}</b>`));
    it.appendChild(gate);
    if (g.why) it.appendChild(el("div", "gate-why", esc(g.why)));
  }

  if (r.status === "pending_approval") {
    const act = el("div", "q-actions");
    const ap = el("button", "btn primary", "✅ Approve & run on the model");
    ap.onclick = () => approve(r.id, ap);
    const rj = el("button", "btn ghost", "Reject");
    rj.onclick = async () => { await postJSON("/api/reject", { request_id: r.id }); refreshQueue(); };
    act.append(ap, rj); it.appendChild(act);
  } else if (r.status === "blocked") {
    it.appendChild(el("div", "q-note stop", "SAFETY‑BLOCKED — the biosecurity screen flagged this; it will not run."));
  } else if (r.status === "running") {
    it.appendChild(el("div", "q-note", "Running on the whole‑cell model (Docker; a few minutes)…"));
  } else if (r.status === "done") {
    it.appendChild(el("div", "q-note ok", "Ran + indexed — the new data is agent‑visible. Ask a follow‑up above."));
  } else if (r.status === "failed") {
    it.appendChild(el("div", "q-note stop", "Run failed — check Docker is up and the design resolves to a variant."));
  }
  return it;
}

async function approve(id, btn) {
  btn.disabled = true; btn.textContent = "Launching…";
  await postJSON("/api/approve", { request_id: id });
  setTimeout(refreshQueue, 600);
}

// ---------------- plumbing ----------------
async function postJSON(url, body) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  return r.json();
}
function renderError(d) {
  const e = el("div", "errbox", `<b>${esc(d.message || "error")}</b>` + (d.hint ? `<br><span style="opacity:.8">${esc(d.hint)}</span>` : ""));
  state.thread.appendChild(e);
  if (state.grounding) state.grounding.remove();
}
function addRecent(q) {
  if (state.recents[0] === q) return;
  state.recents.unshift(q); state.recents = state.recents.slice(0, 12);
  const box = $("#recents"); box.innerHTML = "";
  state.recents.forEach((r) => {
    const it = el("div", "recent", esc(r));
    it.onclick = () => { $("#q").value = r; investigate(r); };
    box.appendChild(it);
  });
}

// ---------------- events ----------------
function submit() {
  const q = $("#q").value.trim();
  if (q) investigate(q);
}
$("#send").onclick = submit;
$("#q").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); }
});
$("#q").addEventListener("input", (e) => { e.target.style.height = "auto"; e.target.style.height = e.target.scrollHeight + "px"; });
$("#newBtn").onclick = () => {
  state.thread.innerHTML = ""; $("#q").value = ""; $("#composerWrap").classList.remove("docked");
  clearTimeout(state.poll); $("#q").focus();
};
refreshQueue();   // show any pending requests from a prior session on load
