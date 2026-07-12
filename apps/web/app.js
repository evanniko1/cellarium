"use strict";
// Cellarium SPA — multi-turn chat, persistent investigations, drawers. Rigor lives in the backend; this renders.

const $ = (s, r = document) => r.querySelector(s);
function el(tag, cls, html) { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; }
const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const trunc = (s, n) => (String(s).length > n ? String(s).slice(0, n - 1) + "…" : String(s));
const newSid = () => "s_" + Math.random().toString(36).slice(2, 10);
const KEY = "cellarium.invs";

const state = { invs: [], cur: null, running: false, model: null, reasoning: "none", poll: null, curTurn: null, results: null };

// ---------------- markdown ----------------
function inlineMd(t) {
  return esc(t).replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\s][^*]*?)\*(?!\*)/g, "$1<em>$2</em>")
    .replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
}
function md(src) {
  const lines = String(src).replace(/\r\n/g, "\n").split("\n"); let out = "", i = 0;
  const isUL = (l) => /^\s*[-*]\s+/.test(l), isOL = (l) => /^\s*\d+\.\s+/.test(l), isH = (l) => /^\s*#{1,6}\s+/.test(l);
  while (i < lines.length) {
    const l = lines[i];
    if (isH(l)) { const m = l.match(/^\s*(#{1,6})\s+(.*)$/), h = Math.min(m[1].length + 2, 5); out += `<h${h}>${inlineMd(m[2])}</h${h}>`; i++; continue; }
    if (isUL(l)) { let it = ""; while (i < lines.length && isUL(lines[i])) { it += `<li>${inlineMd(lines[i].replace(/^\s*[-*]\s+/, ""))}</li>`; i++; } out += `<ul>${it}</ul>`; continue; }
    if (isOL(l)) { let it = ""; while (i < lines.length && isOL(lines[i])) { it += `<li>${inlineMd(lines[i].replace(/^\s*\d+\.\s+/, ""))}</li>`; i++; } out += `<ol>${it}</ol>`; continue; }
    if (/^\s*$/.test(l)) { i++; continue; }
    const p = []; while (i < lines.length && !/^\s*$/.test(lines[i]) && !isH(lines[i]) && !isUL(lines[i]) && !isOL(lines[i])) { p.push(lines[i]); i++; }
    out += `<p>${inlineMd(p.join(" "))}</p>`;
  }
  return out;
}

// ---------------- investigations (persistence) ----------------
function loadInvs() { try { state.invs = JSON.parse(localStorage.getItem(KEY)) || []; } catch { state.invs = []; } }
function saveInvs() {
  for (let a = 0; a < 6; a++) {
    try { localStorage.setItem(KEY, JSON.stringify(state.invs)); return; }
    catch (e) { if (state.invs.length > 1 && state.invs[state.invs.length - 1] !== state.cur) state.invs.pop();
      else state.invs.forEach((v) => (v.turns || []).forEach((t) => (t.tools || []).forEach((d) => (d.output = null)))); }
  }
}
function curCouncil() { return state.cur ? state.cur.council : { rounds: [], hyp: null, designs: [] }; }

function resetToHero() {
  state.cur = null; $("#thread").innerHTML = ""; $("#app").classList.remove("app-chatting");
  $("#convoTitle").textContent = ""; clearTimeout(state.poll); renderCouncil(); clearBadge("councilBadge");
  closeDrawers(); renderSidebar(); $("#q").focus();
}
function openInv(inv) {
  state.cur = inv; $("#thread").innerHTML = "";
  (inv.turns || []).forEach(replayTurn);
  $("#app").classList.toggle("app-chatting", (inv.turns || []).length > 0);
  $("#convoTitle").textContent = inv.title || "";
  renderCouncil(); const rn = curCouncil().rounds.length; bumpBadge("councilBadge", rn); clearBadge("councilBadge");
  renderSidebar(); scrollBottom(); refreshQueue();
}
function ensureCur(q) {
  if (state.cur) return;
  state.cur = { sid: newSid(), title: q ? trunc(q, 60) : "", council: { rounds: [], hyp: null, designs: [] }, turns: [] };
  state.invs.unshift(state.cur);
}
function renderSidebar() {
  const box = $("#recents"); box.innerHTML = "";
  state.invs.forEach((inv) => {
    const it = el("div", "recent" + (inv === state.cur ? " active" : ""));
    const title = el("span", "r-title", esc(inv.title || "New investigation"));
    it.appendChild(title);
    it.onclick = () => openInv(inv);
    const menu = el("span", "r-menu");
    const ren = el("button", "r-act", `<svg viewBox="0 0 24 24" width="13" height="13"><path d="M4 20h4L18 10l-4-4L4 16z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>`);
    ren.title = "Rename"; ren.onclick = (e) => { e.stopPropagation(); renameInv(inv, title); };
    const del = el("button", "r-act", `<svg viewBox="0 0 24 24" width="13" height="13"><path d="M5 7h14M9 7V5h6v2M7 7l1 12h8l1-12" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>`);
    del.title = "Delete"; del.onclick = (e) => { e.stopPropagation(); deleteInv(inv); };
    menu.append(ren, del); it.appendChild(menu);
    box.appendChild(it);
  });
}
function renameInv(inv, titleEl) {
  const inp = el("input"); inp.value = inv.title || "";
  titleEl.innerHTML = ""; titleEl.appendChild(inp); inp.focus(); inp.select();
  const commit = () => { inv.title = inp.value.trim() || inv.title || "Untitled"; saveInvs(); renderSidebar(); if (inv === state.cur) $("#convoTitle").textContent = inv.title; };
  inp.onkeydown = (e) => { if (e.key === "Enter") inp.blur(); if (e.key === "Escape") { inp.value = inv.title; inp.blur(); } };
  inp.onblur = commit; inp.onclick = (e) => e.stopPropagation();
}
function deleteInv(inv) {
  state.invs = state.invs.filter((v) => v !== inv);
  postJSON("/api/session_delete", { session_id: inv.sid });
  saveInvs();
  if (state.cur === inv) resetToHero(); else renderSidebar();
}

// ---------------- send / stream ----------------
function scrollBottom() { const s = $("#scroll"); s.scrollTop = s.scrollHeight; }
function setSend(on) { $("#send").disabled = !on; }
function addUserBubble(q) { $("#thread").appendChild(el("div", "turn user", `<div class="bubble">${esc(q)}</div>`)); scrollBottom(); }

async function send(q) {
  q = (q != null ? q : $("#q").value).trim();
  if (!q || state.running) return;
  $("#q").value = ""; autosize();
  ensureCur(q);
  if (!state.cur.title) state.cur.title = trunc(q, 60);
  $("#app").classList.add("app-chatting"); $("#convoTitle").textContent = state.cur.title; renderSidebar(); saveInvs();
  addUserBubble(q);
  await stream(q);
}

async function stream(question) {
  state.running = true; setSend(false);
  const inv = state.cur, firstTurn = (inv.turns || []).length === 0, usedCouncil = $("#council").checked;
  state.curTurn = { q: question, hyp: null, tools: [], answer: null, trust: null };
  const turn = assistantTurn();
  turn.status(usedCouncil && firstTurn ? "Convening the Socratic Council…" : "Thinking…");
  try {
    const resp = await fetch("/api/investigate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: inv.sid, question, use_council: usedCouncil, model: state.model, reasoning: state.reasoning }),
    });
    const reader = resp.body.getReader(), dec = new TextDecoder(); let buf = "";
    while (true) {
      const { value, done } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true }); let i;
      while ((i = buf.indexOf("\n")) >= 0) { const line = buf.slice(0, i); buf = buf.slice(i + 1); if (line.trim()) { const { kind, data } = JSON.parse(line); handle(kind, data, turn); } }
    }
  } catch (e) { turn.error(esc(String(e))); }
  finally {
    state.running = false; setSend(true);
    inv.turns.push(state.curTurn); saveInvs();
    scrollBottom();
  }
}

function handle(kind, data, turn) {
  const c = curCouncil();
  if (kind === "council_round") { c.rounds.push(data); renderCouncil(); bumpBadge("councilBadge", c.rounds.length); turn.status(`Council deliberating — round ${data.round}…`); }
  else if (kind === "hypothesis") { c.hyp = data; c.designs = data.candidate_designs || []; renderCouncil(); state.curTurn.hyp = { claim: data.claim }; turn.hyp(data); turn.status("Grounding against the corpus…"); }
  else if (kind === "tool") { state.curTurn.tools.push(data); turn.tool(data); turn.status(`Calling ${data.tool}…`); }
  else if (kind === "text") { turn.text(data.delta); turn.status("Responding…"); }
  else if (kind === "answer") { state.curTurn.answer = data.answer; state.curTurn.trust = data.trust || {}; turn.answer(data); if (data.model) setModelValue(data.model); refreshQueue(); }
  else if (kind === "error") { turn.error(esc(data.message) + (data.hint ? `<br><span style="opacity:.8">${esc(data.hint)}</span>` : "")); }
  else if (kind === "done") { turn.done(); }
}

// ---------------- an assistant turn ----------------
function assistantTurn(replay) {
  const root = el("div", "turn assistant");
  const statusEl = el("div", "status-line hidden", `<span class="dot-pulse"></span><span class="st"></span>`);
  const hypSlot = el("div"), trailSlot = el("div"), ansSlot = el("div");
  root.append(statusEl, hypSlot, trailSlot, ansSlot);
  $("#thread").appendChild(root); let line = null, liveEl = null;
  const liveBody = () => { if (!liveEl) { liveEl = el("div", "answer"); liveEl.appendChild(el("div", "answer-body live", "")); ansSlot.appendChild(liveEl); } return liveEl.querySelector(".answer-body"); };
  const dropLive = () => { if (liveEl) { liveEl.remove(); liveEl = null; } };
  return {
    status(t) { statusEl.classList.remove("hidden"); statusEl.querySelector(".st").textContent = t; scrollBottom(); },
    done() { statusEl.remove(); },
    text(delta) { liveBody().textContent += delta; scrollBottom(); },   // token streaming
    hyp(v) {
      const c = el("div", "hyp-chip");
      const top = el("div", "hc-top", `<span class="label">Socratic Council · framed before any data</span>`);
      const b = el("button", "linkbtn", "view debate →"); b.onclick = () => openDrawer("council"); top.appendChild(b); c.appendChild(top);
      if (v.claim) c.appendChild(el("div", "hc-claim", `<span class="lbl">Hypothesis</span>${esc(v.claim)}`));
      hypSlot.appendChild(c); scrollBottom();
    },
    tool(d) { dropLive(); if (!line) { const t = trailScaffold(); trailSlot.append(t.head, t.line); line = t.line; } line.appendChild(toolEl(d)); scrollBottom(); },
    answer(d) { dropLive(); ansSlot.appendChild(el("div", "answer", `<div class="answer-body">${md(d.answer)}</div>`)); if (d.trust && Object.keys(d.trust).length) ansSlot.appendChild(trustEl(d.trust)); scrollBottom(); },
    error(msg) { dropLive(); statusEl.remove(); ansSlot.appendChild(el("div", "errbox", msg)); },
  };
}
function replayTurn(t) {
  addUserBubble(t.q); const a = assistantTurn(true);
  if (t.hyp) a.hyp(t.hyp); (t.tools || []).forEach((d) => a.tool(d)); if (t.answer != null) a.answer({ answer: t.answer, trust: t.trust || {} });
}
function trailScaffold() { return { head: el("div", "trail-head", `<span class="label">Grounded reasoning</span><span class="sub">every number comes from a real run</span>`), line: el("div", "trail-line") }; }
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
  const t = el("details", "tool"), v = verdictOf(d.output), arg = trunc(JSON.stringify(d.input), 50).replace(/^\{|\}$/g, "");
  t.appendChild(el("summary", null, `<span class="tname">${esc(d.tool)}</span><span class="targ">${esc(arg)}</span>` + (v ? `<span class="verdict">${esc(trunc(v, 22))}</span>` : "")));
  t.appendChild(el("pre", null, esc(JSON.stringify(d.output, null, 2)))); return t;
}
const TRUST_CLASS = (v) => { v = String(v).toLowerCase(); if (/flag/.test(v)) return "bad"; if (/under-powered|challenged|refuted|dead|infeasible/.test(v)) return "warn"; if (/out_of_sample|survived|powered|clear/.test(v)) return "good"; return ""; };
function trustEl(sig) { const box = el("div", "trust"); Object.keys(sig).forEach((k) => box.appendChild(el("div", "tchip " + TRUST_CLASS(sig[k]), `<span class="k">${esc(k)}</span><span class="v">${esc(trunc(String(sig[k]), 24))}</span>`))); return box; }

// ---------------- council drawer ----------------
function cleanRivals(v) {
  const parts = String(v).split(/Rival\(/).filter((x) => x.includes("claim="));
  if (!parts.length) return trunc(v, 300);
  return parts.map((p) => trunc(p.replace(/^claim=/, "").replace(/,\s*distinguishing_result=.*$/, "").replace(/^['"]|['"]\)?,?\s*$/g, "").trim(), 150)).join("  ·  ");
}
function row(lbl, txt) { return el("div", "row", `<span class="lbl">${esc(lbl)}</span>${esc(txt)}`); }
function renderCouncil() {
  const b = $("#councilBody"); b.innerHTML = ""; const { rounds, hyp, designs } = curCouncil();
  if (!rounds.length && !hyp) { b.appendChild(el("div", "empty", "No debate yet. Ask a question with the Socratic Council toggle on — the Proposer, Skeptic, and Judge operationalize it into a falsifiable hypothesis before any data is read.")); return; }
  if (hyp) {
    const h = el("div", "c-hyp"); h.appendChild(el("div", "label", "Operationalized hypothesis"));
    if (hyp.claim) h.appendChild(row("Claim", hyp.claim));
    if (hyp.falsifier) h.appendChild(row("Falsifier", hyp.falsifier));
    if (hyp.rivals) h.appendChild(row("Rivals", cleanRivals(hyp.rivals)));
    b.appendChild(h);
  }
  if (rounds.length) b.appendChild(el("div", "label", `The debate — ${rounds.length} round(s)`));
  rounds.forEach((r) => b.appendChild(roundEl(r)));
  if (designs.length) { b.appendChild(el("div", "label", "Falsifier designs — propose to the airlock")); designs.forEach((dv, i) => b.appendChild(designEl(dv, i))); }
}
function roundEl(r) {
  const c = el("div", "c-round"); c.appendChild(el("div", "rn", `Round ${r.round}`));
  const p = el("div", "role proposer", `<div class="role-name">Proposer</div>`); p.appendChild(el("div", "role-text", esc(trunc(r.proposer.claim || "", 220)))); c.appendChild(p);
  const s = el("div", "role skeptic", `<div class="role-name">Skeptic · ${(r.skeptic || []).length} objection(s)</div>`);
  (r.skeptic || []).slice(0, 4).forEach((o) => s.appendChild(el("div", "obj" + (o.severity === "substantive" ? " substantive" : ""), esc(trunc(o.issue || "", 150))))); c.appendChild(s);
  const j = el("div", "role judge", `<div class="role-name">Judge</div>`), g = el("div", "verdict-grid");
  ["falsifiable", "specified", "operationalized", "discriminating"].forEach((k) => { const y = !!r.judge[k]; g.appendChild(el("span", "vpill " + (y ? "yes" : "no"), (y ? "✓ " : "✗ ") + k)); });
  j.appendChild(g); c.appendChild(j); return c;
}
function designEl(dv, i) {
  const c = el("div", "design"), genes = (dv.genes && dv.genes.length) ? dv.genes.join(",") : "control";
  c.appendChild(el("div", "d-name", `<span class="pert">${esc(dv.perturbation)}</span>${dv.condition ? " · " + esc(dv.condition) : ""}`));
  c.appendChild(el("div", "d-meta", `${esc(genes)} · Council proposed ${dv.seeds}×${dv.generations}`));
  const ctr = el("div", "d-controls");
  const sS = el("div", "stepper", `<label>seeds</label>`), iS = el("input"); iS.type = "number"; iS.min = 1; iS.value = 1; sS.appendChild(iS);
  const sG = el("div", "stepper", `<label>gens</label>`), iG = el("input"); iG.type = "number"; iG.min = 1; iG.value = 1; sG.appendChild(iG);
  const btn = el("button", "btn primary", "Queue →");
  btn.onclick = async () => {
    btn.disabled = true; btn.textContent = "Queuing…";
    const res = await postJSON("/api/propose", { perturbation: dv.perturbation, condition: dv.condition, timeline: dv.timeline, params: dv.params || {}, gene: (dv.genes && dv.genes[0]) || null, seeds: +iS.value, generations: +iG.value });
    btn.disabled = false; btn.textContent = "Queue →";
    if (res.error) { alert(res.error); return; }
    await refreshQueue(); openDrawer("queue");
  };
  ctr.append(sS, sG, btn); c.appendChild(ctr); return c;
}

// ---------------- queue drawer ----------------
async function refreshQueue() {
  let data; try { data = await (await fetch("/api/queue")).json(); } catch { return; }
  const q = data.queue || [], pending = q.filter((r) => r.status === "pending_approval").length;
  bumpBadge("queueBadge", pending);
  const b = $("#queueBody"); b.innerHTML = "";
  if (!q.length) { b.appendChild(el("div", "empty", "Empty. The Council's falsifier designs can be queued here for approval — open the Council drawer and hit Queue. Nothing runs without your approval.")); return; }
  let running = false; q.forEach((r) => { if (r.status === "running") running = true; b.appendChild(qitem(r)); });
  if (running) { clearTimeout(state.poll); state.poll = setTimeout(refreshQueue, 3000); }
}
function qitem(r) {
  const d = r.design || {}, it = el("div", "qitem");
  it.appendChild(el("div", "q-top", `<span class="q-id">${esc(r.id)}</span><span class="q-design"><b>${esc(d.perturbation)}</b>${d.condition ? " · " + esc(d.condition) : ""} · ${r.seeds}×${r.generations}</span><span class="status ${esc(r.status)}">${esc(r.status.replace(/_/g, " "))}</span>`));
  const g = r.gate || {};
  if (g.safety) {
    const gate = el("div", "gate");
    gate.appendChild(el("div", "g " + (g.safety === "clear" ? "ok" : "stop"), `safety <b>${esc(g.safety)}</b>`));
    gate.appendChild(el("div", "g", `feasibility <b>${esc(g.feasibility)}</b>`));
    gate.appendChild(el("div", "g", `provenance <b>${esc(g.provenance)}</b>`));
    it.appendChild(gate); if (g.why) it.appendChild(el("div", "gate-why", esc(g.why)));
  }
  if (r.status === "pending_approval") {
    const act = el("div", "q-actions");
    const ap = el("button", "btn primary", "Approve & run"); ap.onclick = async () => { ap.disabled = true; ap.textContent = "Launching…"; await postJSON("/api/approve", { request_id: r.id }); setTimeout(refreshQueue, 600); };
    const rj = el("button", "btn ghost", "Reject"); rj.onclick = async () => { await postJSON("/api/reject", { request_id: r.id }); refreshQueue(); };
    act.append(ap, rj); it.appendChild(act);
  } else if (r.status === "blocked") { it.appendChild(el("div", "q-note stop", "Safety-blocked — the biosecurity screen flagged this; it will not run.")); }
  else if (r.status === "running") { it.appendChild(el("div", "q-note", "Running on the whole-cell model (Docker; a few minutes)…")); }
  else if (r.status === "done") { it.appendChild(el("div", "q-note ok", "Ran + indexed — the new data is agent-visible. Ask a follow-up.")); }
  else if (r.status === "failed") { it.appendChild(el("div", "q-note stop", "Run failed — check Docker is up and the design resolves to a variant.")); }
  return it;
}

// ---------------- corpus browser ----------------
async function openCorpus() {
  $("#corpusView").classList.add("open");
  if (state.results === null) {
    $("#corpusBody").innerHTML = `<div class="empty">Loading the corpus…</div>`;
    try { const j = await (await fetch("/api/results")).json(); state.results = j.results || []; }
    catch { state.results = []; }
  }
  renderCorpus($("#corpusSearch").value);
}
function closeCorpus() { $("#corpusView").classList.remove("open"); }
function renderCorpus(filter) {
  const f = (filter || "").trim().toLowerCase();
  const rows = (state.results || []).filter((r) =>
    !f || `${r.perturbation} ${r.condition || ""} ${r.label || ""} ${r.id}`.toLowerCase().includes(f));
  $("#corpusCount").textContent = `${rows.length} of ${(state.results || []).length} runs`;
  const b = $("#corpusBody"); b.innerHTML = "";
  if (!rows.length) { b.appendChild(el("div", "empty", "No runs match that filter.")); return; }
  rows.forEach((r) => b.appendChild(resRow(r)));
}
function resRow(r) {
  const d = el("details", "res");
  const qcBad = r.qc && r.qc !== "ok";
  const tags = `<span class="tag ${qcBad ? "qc-bad" : "qc-ok"}">${esc(r.qc || "ok")}</span>` +
    `<span class="tag ${r.provenance === "out_of_sample" ? "oos" : ""}">${esc((r.provenance || "").replace("_", "-") || "—")}</span>`;
  const s = el("summary", null,
    `<span class="r-pert"><span class="pert">${esc(r.perturbation)}</span></span>` +
    `<span class="r-cond">${esc(r.condition || r.timeline || "—")} · seed ${esc(r.seed)} · ${esc(r.id)}</span>` +
    `<span class="r-tags">${tags}</span>`);
  d.appendChild(s);
  const box = el("div", "avail", `<div class="empty" style="padding:0">Loading availability…</div>`);
  d.appendChild(box);
  d.addEventListener("toggle", async () => {
    if (!d.open || d.dataset.loaded) return;
    d.dataset.loaded = "1";
    try {
      const a = await (await fetch("/api/result_availability?id=" + encodeURIComponent(r.id))).json();
      box.innerHTML = ""; box.appendChild(availView(a));
    } catch (e) { box.innerHTML = `<span class="no">availability unavailable: ${esc(String(e))}</span>`; }
  }, { once: false });
  return d;
}
function availView(a) {
  const wrap = el("div");
  const alt = a.alternatives || {};
  const local = el("div", "a-row");
  local.innerHTML = `<span class="a-lbl">Raw local</span>` + (a.raw_local
    ? `<span class="yes">available on this machine</span> <code>${esc(a.raw_local_path || "")}</code>`
    : `<span class="no">not on this machine</span>`);
  wrap.appendChild(local);
  const hf = alt["1_download_from_hf"] || {};
  const dl = el("div", "a-row");
  dl.innerHTML = `<span class="a-lbl">Download (HF)</span>` + (hf.available && hf.command
    ? `<span class="yes">on the dataset</span><code>${esc(hf.command)}</code>`
    : `<span class="no">${esc(hf.status || "not uploaded yet")}</span>`);
  wrap.appendChild(dl);
  const rg = alt["2_regenerate_locally"] || {};
  const re = el("div", "a-row");
  re.innerHTML = `<span class="a-lbl">Regenerate</span><span>${esc((rg.how || "").split(";")[0])} — you accept the wcEcoli license by running it yourself.</span>`;
  wrap.appendChild(re);
  if (a.note) wrap.appendChild(el("div", "gate-why", esc(a.note)));
  return wrap;
}

// ---------------- drawers / models / plumbing ----------------
function openDrawer(which) { closeDrawers(); $("#scrim").classList.add("show"); $(which === "council" ? "#councilDrawer" : "#queueDrawer").classList.add("open"); if (which === "council") clearBadge("councilBadge"); }
function closeDrawers() { $("#scrim").classList.remove("show"); $("#councilDrawer").classList.remove("open"); $("#queueDrawer").classList.remove("open"); }
function bumpBadge(id, n) { const b = $("#" + id); if (n > 0) { b.textContent = n; b.classList.add("show"); } else b.classList.remove("show"); }
function clearBadge(id) { $("#" + id).classList.remove("show"); }
async function postJSON(url, body) { return (await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })).json(); }
async function loadModels() {
  try {
    const j = await (await fetch("/api/models")).json();
    const ms = $("#model"); ms.innerHTML = "";
    j.models.forEach((m) => { const o = el("option"); o.value = m.id; o.textContent = m.label; o.title = m.note; ms.appendChild(o); });
    state.model = j.default; ms.value = j.default; ms.onchange = () => (state.model = ms.value);
    const rs = $("#reasoning"); rs.innerHTML = "";
    (j.reasoning || []).forEach((r) => { const o = el("option"); o.value = r.id; o.textContent = r.label; rs.appendChild(o); });
    state.reasoning = j.reasoning_default || "none"; rs.value = state.reasoning; rs.onchange = () => (state.reasoning = rs.value);
  } catch { /* offline */ }
}
function setModelValue(id) { const ms = $("#model"); if (ms && [...ms.options].some((o) => o.value === id)) { ms.value = id; state.model = id; } }
function autosize() { const t = $("#q"); t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 200) + "px"; }

$("#send").onclick = () => send();
$("#q").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
$("#q").addEventListener("input", autosize);
$("#newBtn").onclick = resetToHero;
$("#corpusBtn").onclick = openCorpus;
$("#corpusClose").onclick = closeCorpus;
$("#corpusSearch").addEventListener("input", (e) => renderCorpus(e.target.value));
$("#sidebarToggle").onclick = () => $("#app").classList.toggle("sidebar-collapsed");
$("#councilBtn").onclick = () => openDrawer("council");
$("#queueBtn").onclick = () => openDrawer("queue");
$("#scrim").onclick = closeDrawers;
document.querySelectorAll("[data-close]").forEach((b) => (b.onclick = closeDrawers));
document.querySelectorAll(".chip").forEach((c) => (c.onclick = () => send(c.dataset.q)));

loadModels(); loadInvs(); renderSidebar(); renderCouncil(); refreshQueue();
