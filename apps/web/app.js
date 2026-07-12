"use strict";
// Cellarium SPA — a real multi-turn chat over the streaming pipeline. Rigor lives in the backend; this only renders.

const $ = (s, r = document) => r.querySelector(s);
function el(tag, cls, html) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html != null) e.innerHTML = html;
  return e;
}
const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const trunc = (s, n) => (String(s).length > n ? String(s).slice(0, n - 1) + "…" : String(s));
const newSid = () => "s_" + Math.random().toString(36).slice(2, 10);

const state = {
  sid: newSid(), started: false, running: false, model: null, poll: null,
  council: { rounds: [], hyp: null, designs: [] },
};

// ---------------- markdown (headings, bold, italic, code, lists, links) ----------------
function inlineMd(t) {
  return esc(t)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\s][^*]*?)\*(?!\*)/g, "$1<em>$2</em>")
    .replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
}
function md(src) {
  const lines = String(src).replace(/\r\n/g, "\n").split("\n");
  let out = "", i = 0;
  const isUL = (l) => /^\s*[-*]\s+/.test(l), isOL = (l) => /^\s*\d+\.\s+/.test(l), isH = (l) => /^\s*#{1,6}\s+/.test(l);
  while (i < lines.length) {
    const l = lines[i];
    if (isH(l)) { const m = l.match(/^\s*(#{1,6})\s+(.*)$/); out += `<h${Math.min(m[1].length + 2, 5)}>${inlineMd(m[2])}</h${Math.min(m[1].length + 2, 5)}>`; i++; continue; }
    if (isUL(l)) { let it = ""; while (i < lines.length && isUL(lines[i])) { it += `<li>${inlineMd(lines[i].replace(/^\s*[-*]\s+/, ""))}</li>`; i++; } out += `<ul>${it}</ul>`; continue; }
    if (isOL(l)) { let it = ""; while (i < lines.length && isOL(lines[i])) { it += `<li>${inlineMd(lines[i].replace(/^\s*\d+\.\s+/, ""))}</li>`; i++; } out += `<ol>${it}</ol>`; continue; }
    if (/^\s*$/.test(l)) { i++; continue; }
    const para = []; while (i < lines.length && !/^\s*$/.test(lines[i]) && !isH(lines[i]) && !isUL(lines[i]) && !isOL(lines[i])) { para.push(lines[i]); i++; }
    out += `<p>${inlineMd(para.join(" "))}</p>`;
  }
  return out;
}

// ---------------- send / stream ----------------
function scrollBottom() { const s = $("#scroll"); s.scrollTop = s.scrollHeight; }
function setSend(on) { $("#send").disabled = !on; }

async function send() {
  const q = $("#q").value.trim();
  if (!q || state.running) return;
  $("#q").value = ""; autosize();
  if (!state.started) { $("#app").classList.add("app-chatting"); $("#convoTitle").textContent = q; addRecent(q); }
  $("#thread").appendChild(el("div", "turn user", `<div class="bubble">${esc(q)}</div>`));
  scrollBottom();
  await stream(q);
}

async function stream(question) {
  state.running = true; setSend(false);
  const usedCouncil = $("#council").checked, firstTurn = !state.started;
  const turn = assistantTurn();
  turn.status(usedCouncil && firstTurn ? "Convening the Socratic Council…" : "Thinking…");
  try {
    const resp = await fetch("/api/investigate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: state.sid, question, use_council: usedCouncil, model: state.model }),
    });
    const reader = resp.body.getReader(), dec = new TextDecoder(); let buf = "";
    while (true) {
      const { value, done } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true }); let i;
      while ((i = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, i); buf = buf.slice(i + 1); if (!line.trim()) continue;
        const { kind, data } = JSON.parse(line); handle(kind, data, turn);
      }
    }
  } catch (e) { turn.error(String(e)); }
  finally { state.running = false; state.started = true; setSend(true); scrollBottom(); }
}

function handle(kind, data, turn) {
  if (kind === "council_round") {
    state.council.rounds.push(data); renderCouncil(); bumpBadge("councilBadge", state.council.rounds.length);
    turn.status(`Council deliberating — round ${data.round}…`);
  } else if (kind === "hypothesis") {
    state.council.hyp = data; state.council.designs = data.candidate_designs || []; renderCouncil();
    turn.hyp(data); turn.status("Grounding against the corpus…");
  } else if (kind === "tool") {
    turn.tool(data); turn.status(`Calling ${data.tool}…`);
  } else if (kind === "answer") {
    turn.answer(data); if (data.model) setModelValue(data.model); refreshQueue();
  } else if (kind === "error") {
    turn.error(esc(data.message) + (data.hint ? `<br><span style="opacity:.8">${esc(data.hint)}</span>` : ""));
  } else if (kind === "done") {
    turn.done();
  }
}

// ---------------- an assistant turn (live status -> hypothesis -> trail -> answer) ----------------
function assistantTurn() {
  const root = el("div", "turn assistant");
  const statusEl = el("div", "status-line", `<span class="dot-pulse"></span><span class="st"></span>`);
  const hypSlot = el("div"), trailSlot = el("div"), ansSlot = el("div");
  root.append(statusEl, hypSlot, trailSlot, ansSlot);
  $("#thread").appendChild(root);
  let line = null;
  return {
    status(t) { statusEl.querySelector(".st").textContent = t; scrollBottom(); },
    done() { statusEl.remove(); },
    hyp(v) {
      const c = el("div", "hyp-chip");
      const top = el("div", "hc-top", `<span class="label">Socratic Council · framed before any data</span>`);
      const b = el("button", "linkbtn", "view debate →"); b.onclick = () => openDrawer("council");
      top.appendChild(b); c.appendChild(top);
      if (v.claim) c.appendChild(el("div", "hc-claim", `<span class="lbl">Hypothesis</span>${esc(v.claim)}`));
      hypSlot.appendChild(c); scrollBottom();
    },
    tool(d) {
      if (!line) { const t = trailScaffold(); trailSlot.append(t.head, t.line); line = t.line; }
      line.appendChild(toolEl(d)); scrollBottom();
    },
    answer(d) {
      ansSlot.appendChild(el("div", "answer", `<div class="answer-body">${md(d.answer)}</div>`));
      if (d.trust && Object.keys(d.trust).length) ansSlot.appendChild(trustEl(d.trust));
      scrollBottom();
    },
    error(msg) { statusEl.remove(); ansSlot.appendChild(el("div", "errbox", msg)); },
  };
}
function trailScaffold() {
  const head = el("div", "trail-head", `<span class="label">Grounded reasoning</span><span class="sub">every number comes from a real run</span>`);
  return { head, line: el("div", "trail-line") };
}
function verdictOf(o) {
  if (!o || typeof o !== "object") return "";
  if ("verdict" in o) return String(o.verdict);
  if ("adequately_powered" in o) return o.adequately_powered === false ? "under-powered" : "powered";
  if ("flags" in o) return o.flags && o.flags.length ? "flagged" : "clear";
  if ("provenance" in o) return String(o.provenance);
  if ("class" in o) return String(o.class);
  if ("in_envelope" in o) return o.in_envelope ? "in-envelope" : "boundary";
  if ("status" in o) return String(o.status);
  return "";
}
function toolEl(d) {
  const t = el("details", "tool");
  const v = verdictOf(d.output), arg = trunc(JSON.stringify(d.input), 50).replace(/^\{|\}$/g, "");
  t.appendChild(el("summary", null,
    `<span class="tname">${esc(d.tool)}</span><span class="targ">${esc(arg)}</span>` +
    (v ? `<span class="verdict">${esc(trunc(v, 22))}</span>` : "")));
  t.appendChild(el("pre", null, esc(JSON.stringify(d.output, null, 2))));
  return t;
}
const TRUST_CLASS = (v) => {
  v = String(v).toLowerCase();
  if (/flag/.test(v)) return "bad";
  if (/under-powered|challenged|refuted|dead|infeasible/.test(v)) return "warn";
  if (/out_of_sample|survived|powered|clear/.test(v)) return "good";
  return "";
};
function trustEl(sig) {
  const box = el("div", "trust");
  Object.keys(sig).forEach((k) => box.appendChild(el("div", "tchip " + TRUST_CLASS(sig[k]),
    `<span class="k">${esc(k)}</span><span class="v">${esc(trunc(String(sig[k]), 24))}</span>`)));
  return box;
}

// ---------------- Council drawer ----------------
function cleanRivals(v) {
  const parts = String(v).split(/Rival\(/).filter((x) => x.includes("claim="));
  if (!parts.length) return trunc(v, 300);
  return parts.map((p) => trunc(p.replace(/^claim=/, "").replace(/,\s*distinguishing_result=.*$/, "")
    .replace(/^['"]|['"]\)?,?\s*$/g, "").trim(), 150)).join("  ·  ");
}
function row(lbl, txt) { return el("div", "row", `<span class="lbl">${esc(lbl)}</span>${esc(txt)}`); }
function renderCouncil() {
  const b = $("#councilBody"); b.innerHTML = "";
  const { rounds, hyp, designs } = state.council;
  if (!rounds.length && !hyp) {
    b.appendChild(el("div", "empty", "No debate yet. Ask a question with the Socratic Council toggle on — the Proposer, Skeptic, and Judge operationalize it into a falsifiable hypothesis before any data is read."));
    return;
  }
  if (hyp) {
    const h = el("div", "c-hyp");
    h.appendChild(el("div", "label", "Operationalized hypothesis"));
    if (hyp.claim) h.appendChild(row("Claim", hyp.claim));
    if (hyp.falsifier) h.appendChild(row("Falsifier", hyp.falsifier));
    if (hyp.rivals) h.appendChild(row("Rivals", cleanRivals(hyp.rivals)));
    b.appendChild(h);
  }
  if (rounds.length) b.appendChild(el("div", "label", `The debate — ${rounds.length} round(s)`));
  rounds.forEach((r) => b.appendChild(roundEl(r)));
  if (designs.length) {
    b.appendChild(el("div", "label", "Falsifier designs — propose to the airlock"));
    designs.forEach((dv, i) => b.appendChild(designEl(dv, i)));
  }
}
function roundEl(r) {
  const c = el("div", "c-round");
  c.appendChild(el("div", "rn", `Round ${r.round}`));
  const p = el("div", "role proposer", `<div class="role-name">Proposer</div>`);
  p.appendChild(el("div", "role-text", esc(trunc(r.proposer.claim || "", 220)))); c.appendChild(p);
  const s = el("div", "role skeptic", `<div class="role-name">Skeptic · ${r.skeptic.length} objection(s)</div>`);
  (r.skeptic || []).slice(0, 4).forEach((o) =>
    s.appendChild(el("div", "obj" + (o.severity === "substantive" ? " substantive" : ""), esc(trunc(o.issue || "", 150)))));
  c.appendChild(s);
  const j = el("div", "role judge", `<div class="role-name">Judge</div>`);
  const g = el("div", "verdict-grid");
  ["falsifiable", "specified", "operationalized", "discriminating"].forEach((k) => {
    const yes = !!r.judge[k]; g.appendChild(el("span", "vpill " + (yes ? "yes" : "no"), (yes ? "✓ " : "✗ ") + k));
  });
  j.appendChild(g); c.appendChild(j);
  return c;
}
function designEl(dv, i) {
  const c = el("div", "design");
  const genes = (dv.genes && dv.genes.length) ? dv.genes.join(",") : "control";
  c.appendChild(el("div", "d-name", `<span class="pert">${esc(dv.perturbation)}</span>${dv.condition ? " · " + esc(dv.condition) : ""}`));
  c.appendChild(el("div", "d-meta", `${esc(genes)} · Council proposed ${dv.seeds}×${dv.generations}`));
  const ctr = el("div", "d-controls");
  const sS = el("div", "stepper", `<label>seeds</label>`), iS = el("input"); iS.type = "number"; iS.min = 1; iS.value = 1; sS.appendChild(iS);
  const sG = el("div", "stepper", `<label>gens</label>`), iG = el("input"); iG.type = "number"; iG.min = 1; iG.value = 1; sG.appendChild(iG);
  const btn = el("button", "btn primary", "Queue →");
  btn.onclick = async () => {
    btn.disabled = true; btn.textContent = "Queuing…";
    const res = await postJSON("/api/propose", {
      perturbation: dv.perturbation, condition: dv.condition, timeline: dv.timeline,
      params: dv.params || {}, gene: (dv.genes && dv.genes[0]) || null, seeds: +iS.value, generations: +iG.value,
    });
    btn.disabled = false; btn.textContent = "Queue →";
    if (res.error) { alert(res.error); return; }
    await refreshQueue(); openDrawer("queue");
  };
  ctr.append(sS, sG, btn); c.appendChild(ctr);
  return c;
}

// ---------------- Queue drawer ----------------
async function refreshQueue() {
  let data;
  try { data = await (await fetch("/api/queue")).json(); } catch { return; }
  const q = data.queue || [];
  const pending = q.filter((r) => r.status === "pending_approval").length;
  bumpBadge("queueBadge", pending);
  const b = $("#queueBody"); b.innerHTML = "";
  if (!q.length) { b.appendChild(el("div", "empty", "Empty. The Council's falsifier designs can be queued here for approval — open the Council drawer and hit Queue. Nothing runs without your approval.")); return; }
  let running = false;
  q.forEach((r) => { if (r.status === "running") running = true; b.appendChild(qitem(r)); });
  if (running) { clearTimeout(state.poll); state.poll = setTimeout(refreshQueue, 3000); }
}
function qitem(r) {
  const d = r.design || {}, it = el("div", "qitem");
  it.appendChild(el("div", "q-top",
    `<span class="q-id">${esc(r.id)}</span><span class="q-design"><b>${esc(d.perturbation)}</b>${d.condition ? " · " + esc(d.condition) : ""} · ${r.seeds}×${r.generations}</span>` +
    `<span class="status ${esc(r.status)}">${esc(r.status.replace(/_/g, " "))}</span>`));
  const g = r.gate || {};
  if (g.safety) {
    const gate = el("div", "gate");
    gate.appendChild(el("div", "g " + (g.safety === "clear" ? "ok" : "stop"), `safety <b>${esc(g.safety)}</b>`));
    gate.appendChild(el("div", "g", `feasibility <b>${esc(g.feasibility)}</b>`));
    gate.appendChild(el("div", "g", `provenance <b>${esc(g.provenance)}</b>`));
    it.appendChild(gate);
    if (g.why) it.appendChild(el("div", "gate-why", esc(g.why)));
  }
  if (r.status === "pending_approval") {
    const act = el("div", "q-actions");
    const ap = el("button", "btn primary", "Approve & run");
    ap.onclick = async () => { ap.disabled = true; ap.textContent = "Launching…"; await postJSON("/api/approve", { request_id: r.id }); setTimeout(refreshQueue, 600); };
    const rj = el("button", "btn ghost", "Reject");
    rj.onclick = async () => { await postJSON("/api/reject", { request_id: r.id }); refreshQueue(); };
    act.append(ap, rj); it.appendChild(act);
  } else if (r.status === "blocked") {
    it.appendChild(el("div", "q-note stop", "Safety-blocked — the biosecurity screen flagged this; it will not run."));
  } else if (r.status === "running") {
    it.appendChild(el("div", "q-note", "Running on the whole-cell model (Docker; a few minutes)…"));
  } else if (r.status === "done") {
    it.appendChild(el("div", "q-note ok", "Ran + indexed — the new data is agent-visible. Ask a follow-up."));
  } else if (r.status === "failed") {
    it.appendChild(el("div", "q-note stop", "Run failed — check Docker is up and the design resolves to a variant."));
  }
  return it;
}

// ---------------- drawers, models, plumbing ----------------
function openDrawer(which) {
  closeDrawers(); $("#scrim").classList.add("show");
  $(which === "council" ? "#councilDrawer" : "#queueDrawer").classList.add("open");
  if (which === "council") clearBadge("councilBadge");
}
function closeDrawers() {
  $("#scrim").classList.remove("show");
  $("#councilDrawer").classList.remove("open"); $("#queueDrawer").classList.remove("open");
}
function bumpBadge(id, n) { const b = $("#" + id); if (n > 0) { b.textContent = n; b.classList.add("show"); } else b.classList.remove("show"); }
function clearBadge(id) { $("#" + id).classList.remove("show"); }

async function postJSON(url, body) {
  return (await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })).json();
}
async function loadModels() {
  try {
    const { models, default: def } = await (await fetch("/api/models")).json();
    const sel = $("#model"); sel.innerHTML = "";
    models.forEach((m) => { const o = el("option"); o.value = m.id; o.textContent = `${m.label} — ${m.note}`; sel.appendChild(o); });
    state.model = def; sel.value = def;
    sel.onchange = () => { state.model = sel.value; };
  } catch { /* offline */ }
}
function setModelValue(id) { const sel = $("#model"); if (sel && [...sel.options].some((o) => o.value === id)) { sel.value = id; state.model = id; } }

function addRecent(q) {
  const box = $("#recents");
  const it = el("div", "recent", esc(q)); it.title = q;
  it.onclick = () => { newInvestigation(); $("#q").value = q; autosize(); $("#q").focus(); };
  box.prepend(it);
}
function newInvestigation() {
  state.sid = newSid(); state.started = false; state.council = { rounds: [], hyp: null, designs: [] };
  $("#thread").innerHTML = ""; $("#app").classList.remove("app-chatting"); $("#convoTitle").textContent = "";
  clearTimeout(state.poll); renderCouncil(); clearBadge("councilBadge"); closeDrawers(); $("#q").focus();
}
function autosize() { const t = $("#q"); t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 200) + "px"; }

$("#send").onclick = send;
$("#q").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
$("#q").addEventListener("input", autosize);
$("#newBtn").onclick = newInvestigation;
$("#councilBtn").onclick = () => openDrawer("council");
$("#queueBtn").onclick = () => openDrawer("queue");
$("#scrim").onclick = closeDrawers;
document.querySelectorAll("[data-close]").forEach((b) => (b.onclick = closeDrawers));
loadModels(); renderCouncil(); refreshQueue();
