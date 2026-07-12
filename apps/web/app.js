"use strict";
// Cellarium SPA — multi-turn chat, persistent investigations, drawers. Rigor lives in the backend; this renders.

const $ = (s, r = document) => r.querySelector(s);
function el(tag, cls, html) { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; }
const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const trunc = (s, n) => (String(s).length > n ? String(s).slice(0, n - 1) + "…" : String(s));
const newSid = () => "s_" + Math.random().toString(36).slice(2, 10);
const fmtElapsed = (ms) => { const s = Math.floor(ms / 1000); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
const KEY = "cellarium.invs";

const state = { invs: [], cur: null, model: null, reasoning: "none", poll: null, results: null,
                hypRuns: [], hypActive: null, hypRunning: false };
// streaming is per-investigation: each inv carries .running + ._live (its in-flight turn's DOM), so navigating
// away never orphans the stream or locks the UI — generation continues in the background and is saved to its inv.

// ---------------- markdown ----------------
function inlineMd(t) {
  return esc(t).replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([\s\S]+?)\*\*/g, "<strong>$1</strong>")   // non-greedy + allow nested * so **bold *italic* bold** renders
    .replace(/(^|[^*])\*([^*\s][^*]*?)\*(?!\*)/g, "$1<em>$2</em>")
    .replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
}
function md(src) {
  const lines = String(src).replace(/\r\n/g, "\n").split("\n"); let out = "", i = 0;
  const isUL = (l) => /^\s*[-*]\s+/.test(l), isOL = (l) => /^\s*\d+\.\s+/.test(l), isH = (l) => /^\s*#{1,6}\s+/.test(l);
  const isHR = (l) => /^\s*([-*_])(?:\s*\1){2,}\s*$/.test(l);   // --- *** ___  -> thematic break
  const isRow = (l) => /^\s*\|.*\|\s*$/.test(l);
  const isSep = (l) => l.includes("|") && /^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$/.test(l);
  const isTable = (j) => isRow(lines[j]) && j + 1 < lines.length && isSep(lines[j + 1]);
  const cells = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
  while (i < lines.length) {
    const l = lines[i];
    if (isTable(i)) {   // GFM table
      const head = cells(l); i += 2; const rows = [];
      while (i < lines.length && isRow(lines[i])) { rows.push(cells(lines[i])); i++; }
      out += `<table><thead><tr>${head.map((h) => `<th>${inlineMd(h)}</th>`).join("")}</tr></thead><tbody>` +
        rows.map((r) => `<tr>${r.map((c) => `<td>${inlineMd(c)}</td>`).join("")}</tr>`).join("") + "</tbody></table>";
      continue;
    }
    if (isHR(l)) { out += "<hr>"; i++; continue; }   // before paragraph so a lone --- becomes a rule, not literal text
    if (isH(l)) { const m = l.match(/^\s*(#{1,6})\s+(.*)$/), h = Math.min(m[1].length + 2, 5); out += `<h${h}>${inlineMd(m[2])}</h${h}>`; i++; continue; }
    if (isUL(l)) { let it = ""; while (i < lines.length && isUL(lines[i])) { it += `<li>${inlineMd(lines[i].replace(/^\s*[-*]\s+/, ""))}</li>`; i++; } out += `<ul>${it}</ul>`; continue; }
    if (isOL(l)) { let it = ""; while (i < lines.length && isOL(lines[i])) { it += `<li>${inlineMd(lines[i].replace(/^\s*\d+\.\s+/, ""))}</li>`; i++; } out += `<ol>${it}</ol>`; continue; }
    if (/^\s*$/.test(l)) { i++; continue; }
    const p = [lines[i]]; i++;
    while (i < lines.length && !/^\s*$/.test(lines[i]) && !isH(lines[i]) && !isUL(lines[i]) && !isOL(lines[i]) && !isHR(lines[i]) && !isTable(i)) { p.push(lines[i]); i++; }
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
  $("#convoTitle").textContent = ""; clearTimeout(state.poll);
  renderFigures(null); closeDrawers(); renderSidebar(); updateSend(); $("#q").focus();
}
function openInv(inv) {
  state.cur = inv; $("#thread").innerHTML = "";
  (inv.turns || []).forEach(replayTurn);
  if (inv.running && inv._live) $("#thread").appendChild(inv._live.root);   // re-attach the still-streaming turn (keeps updating live)
  $("#app").classList.toggle("app-chatting", (inv.turns || []).length > 0 || !!inv.running);
  $("#convoTitle").textContent = inv.title || "";
  renderFigures(inv);
  renderSidebar(); scrollToEnd(); refreshQueue(); updateSend(); maybeRunQueue(inv); markLastUserReask();
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

// ---------------- send / stream (per-investigation; never blocks navigation) ----------------
function scrollBottom(force) {   // sticky: streaming only auto-scrolls if the user is already near the bottom
  const s = $("#scroll");
  if (force || s.scrollHeight - s.scrollTop - s.clientHeight < 140) s.scrollTop = s.scrollHeight;
}
function scrollToEnd() {   // land on the LATEST message when opening a conversation — re-fire to catch async figures
  scrollBottom(true);
  requestAnimationFrame(() => scrollBottom(true));
  [120, 400, 900].forEach((ms) => setTimeout(() => { if ($("#scroll")) scrollBottom(true); }, ms));
}
// Was the user following the bottom? A figure (vega-embed) lays out AFTER we scroll and grows the thread by more than
// the sticky threshold, which a one-shot scroll can't follow — so we capture "were they following?" BEFORE the figure
// streams in, and force a scroll once it lays out (below, in the turn's figure()). This never yanks a scrolled-up user.
function nearBottom() { const s = $("#scroll"); return s ? s.scrollHeight - s.scrollTop - s.clientHeight < 200 : true; }
const isRunning = () => !!(state.cur && state.cur.running);
const ARROW_SVG = `<svg viewBox="0 0 24 24" width="18" height="18"><path d="M4 12h15M13 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
const FLASK_SVG = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3h6M10 3v6l-5 9a1.5 1.5 0 001.3 2.2h9.4A1.5 1.5 0 0023 18l-5-9V3M7.5 14h9"/></svg>`;
const STOP_SVG = `<svg viewBox="0 0 24 24" width="15" height="15"><rect x="6" y="6" width="12" height="12" rx="2.5" fill="currentColor"/></svg>`;
function updateSend() {   // the send button doubles as a STOP button while the current chat is generating
  const b = $("#send"), run = isRunning();
  b.innerHTML = run ? STOP_SVG : ARROW_SVG;
  b.title = run ? "Stop generating" : "Send";
  b.classList.toggle("stop", run);
  b.disabled = false;
}
function stopCurrent() { if (state.cur && state.cur._abort) state.cur._abort.abort(); }
function addUserBubble(q) { $("#thread").appendChild(el("div", "turn user", `<div class="bubble">${esc(q)}</div>`)); scrollBottom(); }

function send(q) {
  q = (q != null ? q : $("#q").value).trim();
  if (!q) return;
  ensureCur(q);
  $("#q").value = ""; autosize();
  if (state.cur.running) { queueQuestion(state.cur, q); return; }   // queue it to run after the current turn
  if (!state.cur.title) state.cur.title = trunc(q, 60);
  $("#app").classList.add("app-chatting"); $("#convoTitle").textContent = state.cur.title; renderSidebar(); saveInvs();
  addUserBubble(q);
  stream(q);
}
function addQueuedBubble(q) {
  const t = el("div", "turn user queued", `<div class="bubble">${esc(q)}<span class="q-tag">queued</span></div>`);
  $("#thread").appendChild(t); scrollBottom(); return t;
}
function queueQuestion(inv, q) {
  inv._queue = inv._queue || [];
  inv._queue.push({ q, bubble: state.cur === inv ? addQueuedBubble(q) : null });
}
function maybeRunQueue(inv) {
  if (inv.running || !inv._queue || !inv._queue.length || state.cur !== inv) return;
  const next = inv._queue.shift();
  if (next.bubble && next.bubble.isConnected) next.bubble.classList.remove("queued");   // promote the queued bubble
  else addUserBubble(next.q);
  stream(next.q);
}
function markLastUserReask() {   // put an "Edit & re-ask" control on the latest user turn (only when idle)
  document.querySelectorAll(".reask-btn").forEach((b) => b.remove());
  if (!state.cur || state.cur.running || !(state.cur.turns || []).length) return;
  const users = document.querySelectorAll("#thread .turn.user:not(.queued)");
  const last = users[users.length - 1];
  if (!last) return;
  const b = el("button", "reask-btn", `<svg viewBox="0 0 24 24" width="12" height="12"><path d="M4 20h4L18 10l-4-4L4 16z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg> Edit & re-ask`);
  b.onclick = reaskLast;
  last.appendChild(b);
}
function reaskLast() {
  const inv = state.cur;
  if (!inv || inv.running || !(inv.turns || []).length) return;
  const last = inv.turns.pop(); saveInvs();
  postJSON("/api/session_pop", { session_id: inv.sid });   // truncate the server/SQLite history to match
  openInv(inv);                                            // re-render without the last turn
  $("#q").value = last.q; autosize(); $("#q").focus();
}

function stream(question) {
  const inv = state.cur, firstTurn = (inv.turns || []).length === 0, usedCouncil = false;   // in-chat Council retired -> the Hypothesis surface
  const ac = new AbortController(); inv._abort = ac;   // so a Stop click can cancel this stream
  inv.running = true; updateSend();
  const turn = assistantTurn();
  inv._live = turn;   // remember the in-flight turn's DOM so we can re-attach it after navigating away and back
  const ct = { q: question, hyp: null, tools: [], answer: null, trust: null, model: null, routed: false };
  inv._ct = ct;   // expose the in-flight turn so the Figures panel can index charts before the turn is committed
  turn.status(usedCouncil && firstTurn ? "Convening the Socratic Council…" : "Thinking…");
  const t0 = Date.now(); const timer = setInterval(() => turn.setTimer(fmtElapsed(Date.now() - t0)), 500);
  (async () => {
    try {
      const resp = await fetch("/api/investigate", {
        method: "POST", headers: { "Content-Type": "application/json" }, signal: ac.signal,
        body: JSON.stringify({ session_id: inv.sid, question, use_council: usedCouncil, model: state.model, reasoning: state.reasoning }),
      });
      const reader = resp.body.getReader(), dec = new TextDecoder(); let buf = "";
      while (true) {
        const { value, done } = await reader.read(); if (done) break;
        buf += dec.decode(value, { stream: true }); let i;
        while ((i = buf.indexOf("\n")) >= 0) { const line = buf.slice(0, i); buf = buf.slice(i + 1); if (line.trim()) { const { kind, data } = JSON.parse(line); handle(kind, data, turn, ct, inv); } }
      }
    } catch (e) {
      if (e && e.name === "AbortError") turn.stopped(); else turn.error(esc(String(e)));
      turn.retry(() => { if (state.cur !== inv) openInv(inv); send(question); });   // resubmit a hanging/stopped question
    }
    finally {
      clearInterval(timer);
      inv.running = false; inv._live = null; inv._abort = null; inv._ct = null;
      if (ct.answer != null) { inv.turns.push(ct); saveInvs(); }   // persist only completed turns; failed/stopped stay retryable
      if (state.cur === inv) { updateSend(); scrollBottom(); renderFigures(inv); }
      maybeRunQueue(inv);   // run the next queued question, if any
      if (state.cur === inv) markLastUserReask();
    }
  })();
}

function handle(kind, data, turn, ct, inv) {
  const c = inv.council, viewing = state.cur === inv;   // events belong to the STREAM's inv, not the current view
  if (kind === "council_round") { c.rounds.push(data); if (viewing) { renderCouncil(); bumpBadge("councilBadge", c.rounds.length); } turn.status(`Council deliberating — round ${data.round}…`); }
  else if (kind === "hypothesis") { c.hyp = data; c.designs = data.candidate_designs || []; if (viewing) renderCouncil(); ct.hyp = { claim: data.claim }; turn.hyp(data); turn.status("Grounding against the corpus…"); }
  else if (kind === "tool") {
    ct.tools.push(data);
    if (isChart(data)) { data.fid = data.fid || nextFid(); turn.figure(data.output, data.fid); if (viewing) renderFigures(inv); }
    else turn.tool(data);
    turn.status(`Calling ${data.tool}…`);
  }
  else if (kind === "text") { turn.text(data.delta); turn.status("Responding…"); }
  else if (kind === "note") { turn.note(data.message); }
  else if (kind === "answer") {
    ct.answer = data.answer; ct.trust = data.trust || {}; ct.model = data.model; ct.routed = !!data.routed;
    turn.answer(data); turn.badge(data.model, data.routed); if (viewing) refreshQueue();
  }
  else if (kind === "error") { turn.error(esc(data.message) + (data.hint ? `<br><span style="opacity:.8">${esc(data.hint)}</span>` : "")); }
  else if (kind === "done") { turn.done(); }
}

// ---------------- an assistant turn ----------------
function assistantTurn(replay) {
  const root = el("div", "turn assistant");
  const statusEl = el("div", "status-line hidden", `<span class="dot-pulse"></span><span class="st"></span><span class="st-timer"></span>`);
  const noteSlot = el("div"), hypSlot = el("div"), trailSlot = el("div"), figSlot = el("div"), ansSlot = el("div");
  root.append(statusEl, noteSlot, hypSlot, trailSlot, figSlot, ansSlot);
  $("#thread").appendChild(root); let line = null, liveEl = null, liveRaw = "";
  const scroll = () => { if (root.isConnected) scrollBottom(); };   // a background stream must not scroll the current view
  const liveBody = () => { if (!liveEl) { liveEl = el("div", "answer"); liveEl.appendChild(el("div", "answer-body live", "")); ansSlot.appendChild(liveEl); liveRaw = ""; } return liveEl.querySelector(".answer-body"); };
  const dropLive = () => { if (liveEl) { liveEl.remove(); liveEl = null; liveRaw = ""; } };
  return {
    root,
    status(t) { statusEl.classList.remove("hidden"); statusEl.querySelector(".st").textContent = t; scroll(); },
    setTimer(t) { const e = statusEl.querySelector(".st-timer"); if (e) e.textContent = t; },
    done() { statusEl.remove(); },
    note(msg) { noteSlot.appendChild(el("div", "compact-note", esc(msg))); scroll(); },
    text(delta) { const b = liveBody(); liveRaw += delta; b.innerHTML = md(liveRaw); scroll(); },   // live markdown as it streams
    hyp(v) {
      const c = el("div", "hyp-chip");   // legacy: only fires when replaying an old investigation that used the in-chat Council
      c.appendChild(el("div", "hc-top", `<span class="label">Socratic Council · framed before any data</span>`));
      if (v.claim) c.appendChild(el("div", "hc-claim", `<span class="lbl">Hypothesis</span>${esc(v.claim)}`));
      hypSlot.appendChild(c); scroll();
    },
    tool(d) { dropLive(); if (!line) { const t = trailScaffold(); trailSlot.append(t.head, t.line); line = t.line; } line.appendChild(toolEl(d)); scroll(); },
    figure(out, fid) {   // capture "was the user following?" before the figure grows the thread; re-pin once it lays out
      const stick = root.isConnected && nearBottom();
      figSlot.appendChild(figureEl(out, fid, () => { if (stick) scrollBottom(true); }));
      scroll();
    },
    answer(d) { dropLive(); ansSlot.appendChild(el("div", "answer", `<div class="answer-body">${md(d.answer)}</div>`)); if (d.trust && Object.keys(d.trust).length) ansSlot.appendChild(trustEl(d.trust)); scroll(); },
    badge(id, routed) { const label = (state.modelLabels && state.modelLabels[id]) || id; ansSlot.appendChild(el("div", "model-badge", (routed ? "Auto → " : "answered by ") + esc(label))); },
    error(msg) { dropLive(); statusEl.remove(); ansSlot.appendChild(el("div", "errbox", msg)); },
    stopped() { statusEl.remove(); if (liveEl) liveEl.querySelector(".answer-body").classList.remove("live"); ansSlot.appendChild(el("div", "stopped-note", "Stopped.")); },
    retry(fn) {
      const b = el("button", "retry-btn", `<svg viewBox="0 0 24 24" width="13" height="13"><path d="M4 12a8 8 0 1 1 2.3 5.6M4 12V7m0 5h5" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg> Retry`);
      b.onclick = () => { b.remove(); fn(); }; ansSlot.appendChild(b); scroll();
    },
  };
}
const isChart = (d) => d && d.tool === "chart" && d.output && d.output.spec;
function replayTurn(t) {
  addUserBubble(t.q); const a = assistantTurn(true);
  if (t.hyp) a.hyp(t.hyp);
  (t.tools || []).forEach((d) => { if (isChart(d)) { d.fid = d.fid || nextFid(); a.figure(d.output, d.fid); } else a.tool(d); });
  if (t.answer != null) { a.answer({ answer: t.answer, trust: t.trust || {} }); if (t.model) a.badge(t.model, t.routed); }
}
function trailScaffold() { return { head: el("div", "trail-head", `<span class="label">Grounded reasoning</span><span class="sub">every number comes from a real run</span>`), line: el("div", "trail-line") }; }

// ---------------- grounded charts: a lightweight Vega-Lite subset renderer (line + bar), no heavy dependency ----------------
const CHART_COLORS = ["#C96442", "#3E6E9E", "#4F8A5B", "#B27E2A", "#7d5ba6", "#B4483C"];
function svgEl(tag, attrs, text) {
  const e = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (text != null) e.textContent = text;
  return e;
}
function fmtNum(v) {
  if (!isFinite(v)) return "";
  const a = Math.abs(v);
  if (a !== 0 && (a < 1e-3 || a >= 1e5)) return v.toExponential(1);
  return String(Math.round(v * 1000) / 1000);
}
function renderBand(spec) {   // SVG fallback for a layered mean±band spec (vega-embed handles it natively when loaded)
  const W = 660, H = 300, pad = { l: 66, r: 14, t: 12, b: 42 };
  const data = (spec.data && spec.data.values) || [], xf = (spec.encoding && spec.encoding.x && spec.encoding.x.field) || "t";
  const lyr = spec.layer || [], meanEnc = ((lyr[1] || {}).encoding || {}).y || { field: "mean" };
  const yf = meanEnc.field, loF = "lo", hiF = "hi";
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "vl-chart", width: "100%", preserveAspectRatio: "xMidYMid meet" });
  const x0 = pad.l, y0 = H - pad.b, iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
  const dom = meanEnc.scale && meanEnc.scale.domain;
  const allY = data.flatMap((d) => [d[loF], d[hiF], d[yf]]).filter((v) => isFinite(v));
  let ymin, ymax;
  if (Array.isArray(dom) && dom.length === 2) { ymin = +dom[0]; ymax = +dom[1]; } else { ymin = Math.min(0, ...allY); ymax = Math.max(...allY); }
  if (ymin === ymax) ymax = ymin + 1;
  const xv = data.map((d) => +d[xf]), xmin = Math.min(...xv), xmax = Math.max(...xv);
  const xs = (v) => x0 + ((v - xmin) / ((xmax - xmin) || 1)) * iw;
  const ys = (v) => y0 - ((Math.max(ymin, Math.min(ymax, v)) - ymin) / (ymax - ymin)) * ih;
  for (let i = 0; i <= 4; i++) { const v = ymin + (ymax - ymin) * i / 4, y = ys(v);
    svg.appendChild(svgEl("line", { x1: x0, y1: y, x2: x0 + iw, y2: y, class: "vl-grid" }));
    svg.appendChild(svgEl("text", { x: x0 - 8, y: y + 3.5, class: "vl-tick vl-ty" }, fmtNum(v))); }
  for (let i = 0; i <= 4; i++) { const v = xmin + (xmax - xmin) * i / 4; svg.appendChild(svgEl("text", { x: xs(v), y: y0 + 15, class: "vl-tick vl-tx" }, fmtNum(v))); }
  if (meanEnc.title) svg.appendChild(svgEl("text", { x: 13, y: pad.t + ih / 2, class: "vl-axis-title", transform: `rotate(-90 13 ${pad.t + ih / 2})` }, meanEnc.title));
  if (spec.encoding && spec.encoding.x && spec.encoding.x.title) svg.appendChild(svgEl("text", { x: x0 + iw / 2, y: H - 6, class: "vl-axis-title" }, spec.encoding.x.title));
  const up = data.filter((d) => isFinite(+d[hiF])).map((d) => `${xs(+d[xf]).toFixed(1)},${ys(+d[hiF]).toFixed(1)}`);
  const dn = data.filter((d) => isFinite(+d[loF])).map((d) => `${xs(+d[xf]).toFixed(1)},${ys(+d[loF]).toFixed(1)}`).reverse();
  svg.appendChild(svgEl("polygon", { points: up.concat(dn).join(" "), fill: CHART_COLORS[0], "fill-opacity": "0.22", stroke: "none" }));
  const mp = data.filter((d) => isFinite(+d[yf])).map((d) => `${xs(+d[xf]).toFixed(1)},${ys(+d[yf]).toFixed(1)}`).join(" ");
  svg.appendChild(svgEl("polyline", { points: mp, class: "vl-line", stroke: CHART_COLORS[0] }));
  return svg;
}
function renderChart(spec) {
  if (spec.layer) return renderBand(spec);   // layered mean±band
  const W = 660, H = 300, pad = { l: 66, r: 14, t: 12, b: 42 };
  const enc = spec.encoding || {}, data = (spec.data && spec.data.values) || [];
  const xf = enc.x && enc.x.field, yf = enc.y && enc.y.field, cf = enc.color && enc.color.field;
  const mark = typeof spec.mark === "string" ? spec.mark : (spec.mark && spec.mark.type) || "line";
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "vl-chart", width: "100%", preserveAspectRatio: "xMidYMid meet" });
  const x0 = pad.l, y0 = H - pad.b, iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
  const yv = data.map((d) => +d[yf]).filter((v) => isFinite(v));
  const dom = enc.y && enc.y.scale && enc.y.scale.domain;   // honor a robust/clamped y-domain from the spec
  let ymin, ymax;
  if (Array.isArray(dom) && dom.length === 2 && isFinite(+dom[0]) && isFinite(+dom[1])) { ymin = +dom[0]; ymax = +dom[1]; }
  else { ymin = Math.min(0, ...yv); ymax = Math.max(...yv); }
  if (ymin === ymax) ymax = ymin + 1;
  const ys = (v) => y0 - ((Math.max(ymin, Math.min(ymax, v)) - ymin) / (ymax - ymin)) * ih;   // clamp to domain
  for (let i = 0; i <= 4; i++) { const v = ymin + (ymax - ymin) * i / 4, y = ys(v);
    svg.appendChild(svgEl("line", { x1: x0, y1: y, x2: x0 + iw, y2: y, class: "vl-grid" }));
    svg.appendChild(svgEl("text", { x: x0 - 8, y: y + 3.5, class: "vl-tick vl-ty" }, fmtNum(v)));
  }
  if (enc.y && enc.y.title) svg.appendChild(svgEl("text", { x: 13, y: pad.t + ih / 2, class: "vl-axis-title", transform: `rotate(-90 13 ${pad.t + ih / 2})` }, enc.y.title));
  if (mark === "bar") {
    data.forEach((d, i) => { const cw = iw / data.length, cx = x0 + (i + 0.5) * cw, bw = Math.min(cw * 0.66, 60);
      svg.appendChild(svgEl("rect", { x: cx - bw / 2, y: ys(+d[yf]), width: bw, height: y0 - ys(+d[yf]), rx: 2, class: "vl-bar" }));
      svg.appendChild(svgEl("text", { x: cx, y: y0 + 15, class: "vl-tick vl-tx" }, trunc(String(d[xf]), 14)));
    });
  } else {
    const xv = data.map((d) => +d[xf]), xmin = Math.min(...xv), xmax = Math.max(...xv);
    const xs = (v) => x0 + ((v - xmin) / ((xmax - xmin) || 1)) * iw;
    for (let i = 0; i <= 4; i++) { const v = xmin + (xmax - xmin) * i / 4; svg.appendChild(svgEl("text", { x: xs(v), y: y0 + 15, class: "vl-tick vl-tx" }, fmtNum(v))); }
    if (enc.x && enc.x.title) svg.appendChild(svgEl("text", { x: x0 + iw / 2, y: H - 6, class: "vl-axis-title" }, enc.x.title));
    const groups = {}; data.forEach((d) => (groups[cf ? d[cf] : "_"] = groups[cf ? d[cf] : "_"] || []).push(d));
    const gk = Object.keys(groups);
    gk.forEach((g, gi) => { const pts = groups[g].filter((d) => isFinite(+d[yf])).map((d) => `${xs(+d[xf]).toFixed(1)},${ys(+d[yf]).toFixed(1)}`).join(" ");
      svg.appendChild(svgEl("polyline", { points: pts, class: "vl-line", stroke: CHART_COLORS[gi % CHART_COLORS.length] }));
    });
    if (cf && gk.length > 1) gk.forEach((g, gi) => { const ly = pad.t + 12 + gi * 15;
      svg.appendChild(svgEl("rect", { x: x0 + 8, y: ly - 8, width: 10, height: 10, rx: 2, fill: CHART_COLORS[gi % CHART_COLORS.length] }));
      svg.appendChild(svgEl("text", { x: x0 + 22, y: ly + 1, class: "vl-legend" }, trunc(String(g), 22)));
    });
  }
  return svg;
}
// vega config that matches the app palette so the interactive chart looks native (and matches the SVG fallback)
const VEGA_CONFIG = {
  background: "transparent", font: '-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,Roboto,Helvetica,Arial,sans-serif',
  view: { stroke: "transparent" }, range: { category: CHART_COLORS },
  axis: { labelColor: "#6B6862", titleColor: "#20201D", gridColor: "#EFEDE6", domainColor: "#E7E4DB", tickColor: "#E7E4DB", labelFontSize: 11, titleFontSize: 12, titleFontWeight: 600 },
  legend: { labelColor: "#6B6862", titleColor: "#20201D", labelFontSize: 11, titleFontSize: 11 },
  title: { color: "#20201D", fontSize: 14, fontWeight: 600, anchor: "start", font: '"Iowan Old Style",Palatino,Georgia,serif' },
  line: { strokeWidth: 2 }, point: { size: 24, filled: true }, bar: { color: "#C96442" },
};
function renderInto(container, spec, onDone) {   // interactive vega-embed when the vendored libs loaded; SVG fallback otherwise
  const done = () => onDone && onDone();          // fires AFTER layout so a streaming view can re-follow the taller content
  if (window.vegaEmbed) {
    const s = Object.assign({ width: "container", height: 280, autosize: { type: "fit", contains: "padding" }, config: VEGA_CONFIG }, spec);
    window.vegaEmbed(container, s, { actions: { export: true, source: true, compiled: false, editor: false }, tooltip: true, renderer: "svg" })
      .then(done).catch(() => { container.textContent = ""; container.appendChild(renderChart(spec)); done(); });
    return;
  }
  container.appendChild(renderChart(spec));
  done();
}
function figureEl(out, fid, onRender) {
  const wrap = el("div", "figure");
  if (fid) wrap.id = figDomId(fid);   // backlink target for the Figures panel
  if (out.error) { wrap.appendChild(el("div", "fig-err", esc(out.error))); return wrap; }
  const chart = el("div", "fig-chart"); wrap.appendChild(chart); renderInto(chart, out.spec, onRender);
  if (out.caption) wrap.appendChild(el("div", "fig-cap", esc(out.caption)));
  if (out.rationale) wrap.appendChild(el("div", "fig-why", esc(out.rationale)));   // the agent's grounded takeaway
  const prov = out.provenance || {}, runs = (prov.runs || []).join(", ");
  const d = el("details", "fig-prov");
  d.appendChild(el("summary", null, `grounded from ${esc(prov.grounded_from || "the corpus")}${runs ? " · " + esc(trunc(runs, 60)) : ""} · view spec`));
  d.appendChild(el("pre", null, esc(JSON.stringify(out.spec, null, 2)).slice(0, 3000)));
  wrap.appendChild(d); return wrap;
}

// ---------------- Figures panel: a navigable index projected from the inline figures (single source of truth) ----------------
let _figSeq = 0;
function nextFid() { return "f" + (++_figSeq); }
const figDomId = (fid) => "fig-" + fid;
function figuresOf(inv) {   // every chart in the investigation, in order — completed turns plus the in-flight one
  if (!inv) return [];
  const turns = (inv.turns || []).slice();
  if (inv.running && inv._ct) turns.push(inv._ct);
  const out = [];
  turns.forEach((t) => (t.tools || []).forEach((d) => {
    if (isChart(d) && !d.output.error) { d.fid = d.fid || nextFid(); out.push({ fid: d.fid, q: t.q, o: d.output }); }
  }));
  return out;
}
function renderFigures(inv) {
  const figs = figuresOf(inv), n = figs.length;
  const btn = $("#figuresBtn"); btn.style.display = n ? "" : "none";   // progressive disclosure — only once a figure exists
  bumpBadge("figuresBadge", n);
  const b = $("#figuresBody"); b.innerHTML = "";
  if (!n) { b.appendChild(el("div", "drawer-empty", "No figures yet. Cellwright draws one when a trajectory or comparison sharpens the answer.")); return; }
  figs.forEach((f, i) => {
    const prov = f.o.provenance || {}, runs = (prov.runs || []).join(", ");
    const card = el("button", "fig-card");
    card.appendChild(el("div", "fc-idx", `Figure ${i + 1}`));
    card.appendChild(el("div", "fc-title", esc((f.o.spec && f.o.spec.title) || f.o.caption || "figure")));
    if (f.q) card.appendChild(el("div", "fc-q", esc(trunc(f.q, 110))));
    if (f.o.rationale) card.appendChild(el("div", "fc-why", esc(f.o.rationale)));
    const meta = (prov.channel ? prov.channel : "") + (runs ? " · " + trunc(runs, 48) : "");
    if (meta) card.appendChild(el("div", "fc-meta", esc(meta)));
    card.onclick = () => scrollToFigure(f.fid);
    b.appendChild(card);
  });
}
function scrollToFigure(fid) {
  closeDrawers();
  const elx = document.getElementById(figDomId(fid));
  if (!elx) return;
  elx.scrollIntoView({ behavior: "smooth", block: "center" });
  elx.classList.remove("fig-flash"); void elx.offsetWidth; elx.classList.add("fig-flash");   // brief highlight
  setTimeout(() => elx.classList.remove("fig-flash"), 1400);
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
  const t = el("details", "tool"), v = verdictOf(d.output), arg = trunc(JSON.stringify(d.input), 50).replace(/^\{|\}$/g, "");
  if ((d.tool === "propose_experiment" || d.tool === "revise_experiment") && d.output && d.output.request_id) t.id = "job-" + d.output.request_id;   // backlink target for the launch queue
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
const CHEV_SVG = `<svg class="chev" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M9 6l6 6-6 6"/></svg>`;
function specAcc(title, count, build) {   // a collapsible spec section (rivals / defs / assumptions)
  const d = el("details", "spec-acc");
  const s = el("summary", null, `${CHEV_SVG}<span>${esc(title)}</span>` + (count != null ? `<span class="acc-cnt">${count}</span>` : ""));
  d.appendChild(s);
  const body = el("div", "spec-acc-body"); build(body); d.appendChild(body); return d;
}
function parseFalsifier(f) {   // structured dict from the backend; legacy runs stored a "key='value' …" string — parse it
  if (f && typeof f === "object") return f;
  const out = {}; let m; const re = /(\w+)='([^']*)'/g;
  while ((m = re.exec(String(f)))) out[m[1]] = m[2];
  return Object.keys(out).length ? out : { decision_rule: String(f) };
}
function parseRivals(rivals) {   // structured list from the backend; legacy string is a Rival(...) repr
  if (Array.isArray(rivals)) return rivals;
  return String(rivals).split(/Rival\(/).filter((x) => x.includes("claim=")).map((p) => {
    const cm = p.match(/claim=['"]([^'"]*)/), dm = p.match(/distinguishing_result=['"]([^'"]*)/);
    return { claim: cm ? cm[1] : trunc(p, 120), distinguishing_result: dm ? dm[1] : "" };
  });
}
function falsifierEl(f) {   // the decisive test, as human prose — never the disconfirm() call signature
  f = parseFalsifier(f);
  const box = el("div", "falsi");
  box.appendChild(el("div", "falsi-k", `${FLASK_SVG}<span>Falsifier — the decisive test</span>`));
  const body = el("div", "falsi-body");
  if (f.channel) body.appendChild(el("p", "falsi-line", `Measure <b>${esc(f.channel)}</b> for <b>${esc(f.target || "the target")}</b> against <b>${esc(f.reference || "the reference")}</b>.`));
  if (f.decision_rule) body.appendChild(el("p", "falsi-line", `<span class="fl">Test</span> ${esc(f.decision_rule)}`));
  if (f.refuting_result) body.appendChild(el("p", "falsi-line refute", `<span class="fl">Refuted if</span> ${esc(f.refuting_result)}`));
  box.appendChild(body);
  const copy = el("button", "falsi-copy", "Copy as disconfirm() call");
  copy.onclick = () => {
    const src = `disconfirm(target='${f.target || ""}', reference='${f.reference || ""}', channel='${f.channel || ""}')\n# decision rule: ${f.decision_rule || ""}\n# refuted if: ${f.refuting_result || ""}`;
    navigator.clipboard.writeText(src); copy.textContent = "Copied ✓"; setTimeout(() => (copy.textContent = "Copy as disconfirm() call"), 1300);
  };
  box.appendChild(copy); return box;
}
function hypBlockEl(hyp) {   // the operationalized-hypothesis SPEC CARD — shared by the Council drawer AND the surface
  const c = el("div", "spec");
  if (hyp.claim) { const cl = el("div", "spec-claim"); cl.appendChild(el("span", "spec-k", "Claim")); cl.appendChild(el("p", null, esc(hyp.claim))); c.appendChild(cl); }
  if (hyp.h1 || hyp.h0) {
    const hh = el("div", "spec-hh");
    const h1 = el("div", "hh-cell h1"); h1.appendChild(el("span", "hh-tag", "H1 · the claim")); h1.appendChild(el("p", null, esc(hyp.h1 || "—")));
    const h0 = el("div", "hh-cell h0"); h0.appendChild(el("span", "hh-tag", "H0 · the null")); h0.appendChild(el("p", null, esc(hyp.h0 || "—")));
    hh.append(h1, h0); c.appendChild(hh);
  }
  if (hyp.predicted_effect) { const pe = el("div", "spec-pred"); pe.appendChild(el("span", "spec-k", "Predicted effect")); pe.appendChild(el("p", null, esc(hyp.predicted_effect))); c.appendChild(pe); }
  if (hyp.falsifier) c.appendChild(falsifierEl(hyp.falsifier));
  const rivals = hyp.rivals ? parseRivals(hyp.rivals) : [];
  if (rivals.length) c.appendChild(specAcc("Rival explanations", rivals.length, (b) => rivals.forEach((r) => {
    const rv = el("div", "rival"); rv.appendChild(el("b", null, esc(r.claim)));
    if (r.distinguishing_result) rv.appendChild(el("span", "rival-disc", "Distinguished if: " + esc(r.distinguishing_result)));
    b.appendChild(rv);
  })));
  if (hyp.operational_defs && hyp.operational_defs.length) c.appendChild(specAcc("Operational definitions", hyp.operational_defs.length, (b) =>
    hyp.operational_defs.forEach((d) => b.appendChild(el("div", "def-item", `<b>${esc(d.term)}</b> → ${esc(d.observable)}${d.measure ? " · " + esc(d.measure) : ""}`)))));
  if (hyp.assumptions && hyp.assumptions.length) c.appendChild(specAcc("Ceteris-paribus assumptions", hyp.assumptions.length, (b) =>
    hyp.assumptions.forEach((a) => b.appendChild(el("div", "assum-item", esc(a))))));
  return c;
}
function renderCouncil() {
  const b = $("#councilBody"); if (!b) return;   // in-chat Council drawer retired
  b.innerHTML = ""; const { rounds, hyp, designs } = curCouncil();
  if (!rounds.length && !hyp) { b.appendChild(el("div", "empty", "No debate yet. Ask a question with the Socratic Council toggle on — the Proposer, Skeptic, and Judge operationalize it into a falsifiable hypothesis before any data is read.")); return; }
  if (hyp) b.appendChild(hypBlockEl(hyp));
  if (rounds.length) b.appendChild(el("div", "label", `The debate — ${rounds.length} round(s)`));
  rounds.forEach((r) => b.appendChild(roundEl(r)));
  if (designs.length) { b.appendChild(el("div", "label", "Falsifier designs — propose to the airlock")); designs.forEach((dv, i) => b.appendChild(designEl(dv, i))); }
}
function fillExpandable(container, text, limit) {
  limit = limit || 220; text = text || "";
  if (text.length <= limit) { container.appendChild(document.createTextNode(text)); return; }
  const span = el("span"); span.textContent = text.slice(0, limit - 1) + "…";
  const btn = el("button", "rt-more", "show full"); let open = false;
  btn.onclick = () => { open = !open; span.textContent = open ? text : text.slice(0, limit - 1) + "…"; btn.textContent = open ? "show less" : "show full"; };
  container.append(span, document.createTextNode(" "), btn);
}
function objThread(o, clean, resolutions) {   // an objection as a first-class thread: severity + type + resolution
  const sub = o.severity === "substantive";
  const resolvedRound = (resolutions && o.id != null) ? resolutions[o.id] : null;   // a round number, or null if open
  const d = el("details", "obj-thread");
  const sum = el("summary");
  sum.appendChild(el("span", "obj-sev " + (sub ? "substantive" : "minor"), sub ? "Substantive" : "Minor"));
  if (o.type) sum.appendChild(el("span", "obj-type", esc(o.type)));
  sum.appendChild(el("span", "obj-title", esc(trunc(o.issue || "", 64))));
  // prefer the TRUE per-objection resolution (the skeptic certified it); else fall back to the round-derived "carried"
  if (resolvedRound) sum.appendChild(el("span", "obj-status resolved", "✓ Resolved R" + resolvedRound));
  else if (sub && !clean) sum.appendChild(el("span", "obj-status carried", "◷ Carried"));
  d.appendChild(sum);
  d.appendChild(el("div", "obj-full", esc(o.issue || "")));
  return d;
}
function roundEl(r, isFinal, resolutions) {
  const clean = !!(r.judge && r.judge.converged);   // this round is adequate + no open substantive objection
  const converged = clean && isFinal;               // AND it's the round that actually terminated the debate
  const c = el("div", "c-round" + (clean ? "" : " held"));
  const head = el("div", "round-head");
  head.appendChild(el("span", "round-n", `Round ${r.round}`));
  const label = converged ? "✓ Converged" : clean ? "✓ Clean round" : "◷ Held — objections open";
  head.appendChild(el("span", "round-outcome " + (clean ? "pass" : "hold"), label));
  c.appendChild(head);
  const p = el("div", "role proposer", `<div class="role-name">Proposer</div>`);
  let full = r.proposer.claim || "";
  if (r.proposer.h1) full += "\n\nH1: " + r.proposer.h1;
  if (r.proposer.h0) full += "\nH0: " + r.proposer.h0;
  const pt = el("div", "role-text"); fillExpandable(pt, full, 220); p.appendChild(pt); c.appendChild(p);
  const objs = r.skeptic || [];
  const s = el("div", "role skeptic", `<div class="role-name">Skeptic · ${objs.length} objection(s)</div>`);
  if (!objs.length) s.appendChild(el("div", "role-text", "No new rubric-breaking objection this round."));
  objs.forEach((o) => s.appendChild(objThread(o, clean, resolutions)));
  c.appendChild(s);
  const j = el("div", "role judge", `<div class="role-name">Judge</div>`), g = el("div", "verdict-grid");
  ["falsifiable", "specified", "operationalized", "discriminating"].forEach((k) => { const y = !!r.judge[k]; g.appendChild(el("span", "vpill " + (y ? "yes" : "no"), (y ? "✓ " : "✗ ") + k)); });
  // the honest convergence verdict — not just four green rubric ticks
  g.appendChild(el("span", "vpill " + (clean ? "yes" : "no"), clean ? (converged ? "✓ converged" : "✓ clean") : "✗ objection open"));
  j.appendChild(g); c.appendChild(j); return c;
}
function designEl(dv, i) {
  const c = el("div", "design"), genes = (dv.genes && dv.genes.length) ? dv.genes.join("+") : "";
  // lead with the GENE for a KO (KO:gltX), not 'basal' — the gene is the identity of the experiment
  const isKO = String(dv.perturbation || "").includes("gene_knockout") && genes;
  const tag = isKO ? ("KO:" + genes + (dv.condition && dv.condition !== "basal" ? " · " + dv.condition : "")) : dv.condition;
  c.appendChild(el("div", "d-name", `<span class="pert">${esc(dv.perturbation)}</span>${tag ? " · " + esc(tag) : ""}`));
  c.appendChild(el("div", "d-meta", `${isKO ? "" : (genes || "control") + " · "}Council proposed ${dv.seeds}×${dv.generations} — override below`));
  const ctr = el("div", "d-controls");
  // default to the scale the Council PROPOSED (not 1×1) — a one-click queue must not silently underpower the test
  const sS = el("div", "stepper", `<label>seeds</label>`), iS = el("input"); iS.type = "number"; iS.min = 1; iS.value = dv.seeds || 1; sS.appendChild(iS);
  const sG = el("div", "stepper", `<label>gens</label>`), iG = el("input"); iG.type = "number"; iG.min = 1; iG.value = dv.generations || 1; sG.appendChild(iG);
  const btn = el("button", "btn primary", "Queue →");
  btn.onclick = async () => {
    btn.disabled = true; btn.textContent = "Queuing…";
    const res = await postJSON("/api/propose", { perturbation: dv.perturbation, condition: dv.condition, timeline: dv.timeline, params: dv.params || {}, gene: (dv.genes && dv.genes[0]) || null, seeds: +iS.value, generations: +iG.value, source: state._hypSource || {} });
    btn.disabled = false; btn.textContent = "Queue →";
    if (res.error) { alert(res.error); return; }
    await refreshQueue(); openDrawer("queue");
  };
  ctr.append(sS, sG, btn); c.appendChild(ctr); return c;
}
function designTable(run) {   // the falsifier panel as a scannable table — design · scale · in-corpus? · action (#5)
  const designs = run.designs, needs = designs.filter((d) => !d.in_corpus);
  const wrap = el("div", "panel");
  const head = el("div", "panel-head");
  head.appendChild(el("h3", null, `${designs.length} designs`));
  head.appendChild(el("span", "panel-sum", `${designs.length - needs.length} in corpus · ${needs.length} need running`));
  const flab = el("label", "panel-filter"); const fchk = el("input"); fchk.type = "checkbox";
  flab.append(fchk, document.createTextNode(" Needs running only"));
  head.appendChild(flab);
  const qall = el("button", "queue-all", `Queue all ${needs.length} → airlock`);
  qall.onclick = async () => {   // one atomic call — the whole panel at the Council's proposed scale, controls included
    qall.disabled = true; qall.textContent = "Queuing panel…";
    const res = await postJSON("/api/propose_panel", { hyp_id: run.id, question: run.question });
    if (res.error) { qall.disabled = false; qall.textContent = `Queue all ${needs.length} → airlock`; alert(res.error); return; }
    qall.textContent = "Panel queued ✓";
    await refreshQueue(); openDrawer("queue");
  };
  if (needs.length) head.appendChild(qall);
  wrap.appendChild(head);
  const tbl = el("div", "panel-tbl"), table = el("table");
  table.appendChild(el("thead", null, `<tr><th>Design</th><th class="num">Scale</th><th>In corpus?</th><th></th></tr>`));
  const tb = el("tbody");
  designs.forEach((dv) => tb.appendChild(designRow(dv)));
  table.appendChild(tb); tbl.appendChild(table); wrap.appendChild(tbl);
  fchk.onchange = () => tb.querySelectorAll("tr.in-yes").forEach((tr) => tr.classList.toggle("hide", fchk.checked));
  return wrap;
}
function designRow(dv) {
  const genes = (dv.genes && dv.genes.length) ? dv.genes.join("+") : "";
  const isMulti = dv.perturbation === "multi_gene_knockout";
  const isKO = String(dv.perturbation || "").includes("gene_knockout") && genes;
  const label = isKO ? (isMulti ? "multi_ko" : "gene_knockout") + " · KO:" + genes
    : `${dv.perturbation}${dv.condition ? " · " + dv.condition : ""}`;
  const role = dv.perturbation === "wildtype" ? "reference" : isMulti ? "discriminating control" : isKO ? "single knockout" : "perturbation";
  const tr = el("tr", dv.in_corpus ? "in-yes" : "in-no");
  const dcell = el("td");
  dcell.appendChild(el("div", "d-label", esc(label)));
  dcell.appendChild(el("div", "d-role" + (dv.perturbation === "wildtype" ? " ref" : isMulti ? " ctrl" : ""), role));
  tr.appendChild(dcell);
  tr.appendChild(el("td", "num", `${dv.seeds}×${dv.generations}`));
  const ic = el("td"); ic.appendChild(el("span", "incorp " + (dv.in_corpus ? "yes" : "no"), dv.in_corpus ? "✓ in corpus" : "◷ needs running")); tr.appendChild(ic);
  const act = el("td", "act-cell");
  if (dv.in_corpus) { act.appendChild(el("span", "act-note", "analyze in place")); }
  else {
    const q = el("button", "row-q", "Queue");
    q.onclick = async () => {   // proposes at the Council's scale (dv.seeds×dv.generations), not 1×1
      if (q.classList.contains("queued")) return;
      q.disabled = true; q.textContent = "…";
      const res = await postJSON("/api/propose", { perturbation: dv.perturbation, condition: dv.condition, timeline: dv.timeline,
        params: dv.params || {}, gene: (dv.genes && dv.genes[0]) || null, seeds: dv.seeds || 1, generations: dv.generations || 1, source: state._hypSource || {} });
      if (res.error) { q.disabled = false; q.textContent = "Queue"; alert(res.error); return; }
      q.classList.add("queued"); q.textContent = "✓ Queued"; await refreshQueue();
    };
    act.appendChild(q);
  }
  tr.appendChild(act); return tr;
}

// ---------------- queue drawer ----------------
async function refreshQueue() {
  let data; try { data = await (await fetch("/api/queue")).json(); } catch { return; }
  const q = data.queue || [];
  // badge counts what still needs attention: pending approvals AND finished jobs the user hasn't cleared yet
  const notify = q.filter((r) => ["pending_approval", "done", "failed"].includes(r.status)).length;
  bumpBadge("queueBadge", notify);
  const b = $("#queueBody"); b.innerHTML = "";
  if (q.some((r) => ["done", "failed"].includes(r.status))) {   // a Clear affordance once finished jobs pile up
    const c = el("button", "q-clear", "Clear finished");
    c.onclick = async () => { await postJSON("/api/queue_clear", {}); refreshQueue(); };
    b.appendChild(c);
  }
  if (!q.length) { b.appendChild(el("div", "empty", "Empty. Cellwright proposes experiments here for your approval — click a proposed job to jump back to the chat that raised it. Nothing runs without your approval.")); return; }
  let running = false; q.forEach((r) => { if (r.status === "running") running = true; b.appendChild(qitem(r)); });
  if (running) { clearTimeout(state.poll); state.poll = setTimeout(refreshQueue, 3000); }
}
function relTime(ts) {
  const s = Math.floor(Date.now() / 1000 - ts);
  if (s < 60) return "just now";
  if (s < 3600) return Math.floor(s / 60) + "m ago";
  if (s < 86400) return Math.floor(s / 3600) + "h ago";
  return Math.floor(s / 86400) + "d ago";
}
function jumpToJob(r) {   // backlink: open the proposing investigation and flash the propose tool-call (like the Figures panel)
  closeDrawers();
  if (r.hyp_id && !r.session_id) { openHyp().then(() => viewHypRun(r.hyp_id)); return; }   // queued from the Hypothesis surface
  const inv = r.session_id ? (state.invs || []).find((v) => v.sid === r.session_id) : null;
  const switching = inv && inv !== state.cur;
  if (switching) openInv(inv);
  setTimeout(() => {
    const elx = document.getElementById("job-" + r.id);
    if (!elx) return;
    if (elx.tagName === "DETAILS") elx.open = true;
    elx.scrollIntoView({ behavior: "smooth", block: "center" });
    elx.classList.remove("fig-flash"); void elx.offsetWidth; elx.classList.add("fig-flash");
    setTimeout(() => elx.classList.remove("fig-flash"), 1400);
  }, switching ? 250 : 0);
}
function qitem(r) {
  const d = r.design || {}, it = el("div", "qitem");
  const genes = (d.params && d.params.target_genes && d.params.target_genes.length) ? d.params.target_genes.join("+") : "";
  const meta = [genes, d.condition].filter(Boolean).map(esc).join(" · ");
  it.appendChild(el("div", "q-top", `<span class="q-id">${esc(r.id)}</span><span class="q-design"><b>${esc(d.perturbation)}</b>${meta ? " · " + meta : ""} · ${r.seeds}×${r.generations}</span><span class="status ${esc(r.status)}">${esc(r.status.replace(/_/g, " "))}</span>`));
  const inv = r.session_id ? (state.invs || []).find((v) => v.sid === r.session_id) : null;   // provenance: chat OR Hypothesis run
  const from = inv ? (inv.title || "an investigation") : (r.hyp_id ? "Hypothesis · " + (r.from_question || "a run") : r.from_question);
  if (from) {
    const prov = el("button", "q-prov", `<svg viewBox="0 0 24 24" width="11" height="11"><path d="M9 10L4 15l5 5M4 15h11a5 5 0 0 0 5-5V4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg> from <b>${esc(trunc(from, 42))}</b>${r.ts ? ` · ${relTime(r.ts)}` : ""}`);
    prov.title = "Jump to where this was proposed";
    prov.onclick = () => jumpToJob(r);
    it.appendChild(prov);
  }
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
  $("#corpusView").classList.add("open"); $("#corpusBtn").classList.add("active");
  if (state.results === null) {
    $("#corpusBody").innerHTML = `<div class="empty">Loading the corpus…</div>`;
    try { const j = await (await fetch("/api/results")).json(); state.results = j.results || []; }
    catch { state.results = []; }
  }
  state.corpusFacet = { type: null, qc: null, prov: null };   // always open on the full corpus
  $("#corpusSearch").value = "";
  renderCorpus("");
}
function closeCorpus() { $("#corpusView").classList.remove("open"); $("#corpusBtn").classList.remove("active"); }

// ---------------- Hypothesis-Generation surface (the Socratic Council, split out + persisted) ----------------
// top-level Cellarium nav (#1): the Investigations|Hypotheses switch lives in the SIDEBAR — one level up from the
// surfaces it toggles, not inside the hyp page. Keeping the sidebar toggle in sync here means every path that
// leaves the surface (Esc, opening a chat, a queue backlink) flips it back correctly.
function _navToggle(hyp) {
  $("#navSegInv").setAttribute("aria-selected", String(!hyp));
  $("#navSegHyp").setAttribute("aria-selected", String(hyp));
  $("#navSegThumb").className = "nav-seg-thumb " + (hyp ? "r" : "l");
  $("#navInv").hidden = hyp; $("#navHyp").hidden = !hyp;
}
async function openHyp() {
  _navToggle(true);
  $("#hypView").classList.add("open");
  await loadHypRuns();
  if (state.hypActive && state.hypActive !== "__live") { viewHypRun(state.hypActive); return; }  // keep the run in view
  if (state.hypRuns && state.hypRuns.length) viewHypRun(state.hypRuns[0].id);   // land on the latest run's detail
  else newHypComposer();                                         // no runs yet — the composer ("+ New hypothesis" also opens it)
}
function closeHyp() {
  _navToggle(false);
  $("#hypView").classList.remove("open");
}
async function loadHypRuns(activeId) {
  try { const j = await (await fetch("/api/hypotheses")).json(); state.hypRuns = j.runs || []; }
  catch { state.hypRuns = []; }
  renderHypRuns(activeId != null ? activeId : state.hypActive);
}
function renderHypRuns(activeId) {   // the Council run list — lives in the top-level sidebar (#1)
  const rail = $("#hypRuns"); if (!rail) return; rail.innerHTML = "";
  $("#hypCount").textContent = state.hypRuns.length ? `${state.hypRuns.length} run(s)` : "";
  if (!state.hypRuns.length) { rail.appendChild(el("div", "drawer-empty", "No hypotheses yet. Pose a research question — the Council operationalizes it into a falsifiable test, blind to the data.")); return; }
  state.hypRuns.forEach((r) => {
    const card = el("button", "hyp-run-card" + (r.id === activeId ? " active" : ""));
    card.appendChild(el("div", "hrc-q", esc(trunc(r.claim || r.question, 96))));
    const meta = el("div", "hrc-meta");
    meta.appendChild(el("span", "hrc-status " + r.status, r.status));
    if (r.n_designs) meta.appendChild(el("span", null, `${r.n_designs} falsifier(s)`));
    card.appendChild(meta);
    card.onclick = () => viewHypRun(r.id);
    rail.appendChild(card);
  });
}
function newHypComposer() {
  state.hypActive = null; renderHypRuns(null);
  const m = $("#hypMain"); m.innerHTML = "";
  const box = el("div", "hyp-composer");
  const ta = el("textarea"); ta.placeholder = "Pose a research question — e.g. Is the aaRS-KO survival spread a genuine biochemical difference in charged-tRNA depletion, or a generation-depth artifact?";
  box.appendChild(ta);
  const go = el("button", "hyp-run-go");
  go.innerHTML = `${ARROW_SVG} Convene the Council`;
  go.onclick = () => runHypothesis(ta.value.trim(), go);
  box.appendChild(go);
  m.appendChild(box);
  m.appendChild(el("div", "hyp-empty", "The Council runs blind to the corpus — it frames the hypothesis before any result is read, then hands it to Cellwright to test."));
  ta.focus();
}
function runHypothesis(question, goBtn) {
  if (!question || state.hypRunning) return;
  state.hypRunning = true;
  const live = { id: null, question, status: "running", rounds: [], hypothesis: {}, designs: [], meta: {} };
  state.hypActive = "__live"; renderHypDetail(live);
  (async () => {
    try {
      const resp = await fetch("/api/hypothesis", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, model: state.model }) });
      const reader = resp.body.getReader(), dec = new TextDecoder(); let buf = "";
      while (true) {
        const { value, done } = await reader.read(); if (done) break;
        buf += dec.decode(value, { stream: true }); let i;
        while ((i = buf.indexOf("\n")) >= 0) {
          const line = buf.slice(0, i); buf = buf.slice(i + 1);
          if (!line.trim()) continue;
          const { kind, data } = JSON.parse(line);
          if (kind === "round") { live.rounds.push(data); renderHypDetail(live); }
          else if (kind === "done" && data.run) { state.hypActive = data.run.id; renderHypDetail(data.run); await loadHypRuns(data.run.id); }
          else if (kind === "error") { live.status = "error"; live.meta = { error: data.message }; renderHypDetail(live); }
        }
      }
    } catch (e) { live.status = "error"; live.meta = { error: String(e) }; renderHypDetail(live); }
    finally { state.hypRunning = false; }
  })();
}
async function viewHypRun(id) {
  state.hypActive = id; renderHypRuns(id);
  const m = $("#hypMain"); m.innerHTML = `<div class="hyp-empty">Loading…</div>`;
  try { const run = await (await fetch("/api/hypothesis_get?id=" + encodeURIComponent(id))).json(); renderHypDetail(run); }
  catch { m.innerHTML = `<div class="hyp-empty">Could not load this run.</div>`; }
}
function needsSpecEl(run) {   // Phase 3(b): the gate found the question too broad — show SCOPE-ONLY asks + refine box
  const qs = (run.meta && run.meta.clarifying_questions) || [];
  const box = el("div", "needspec");
  box.appendChild(el("p", "needspec-lede", "The Socratic Council frames a hypothesis blind to the data, so it needs your question narrow enough to yield ONE decisive test. To keep it blind, it asks only for specification — never a hint at the answer:"));
  const ul = el("div", "needspec-qs");
  qs.forEach((q) => ul.appendChild(el("div", "needspec-q", esc(q))));
  box.appendChild(ul);
  box.appendChild(el("div", "label", "Refine your question"));
  const ta = el("textarea", "needspec-ta"); ta.value = run.question || ""; box.appendChild(ta);
  const go = el("button", "hyp-run-go"); go.innerHTML = `${ARROW_SVG} Re-convene the Council`;
  go.onclick = () => runHypothesis(ta.value.trim(), go);
  box.appendChild(go);
  return box;
}
function renderHypDetail(run) {
  const m = $("#hypMain"); m.innerHTML = "";
  m.appendChild(el("div", "hyp-q", esc(run.question)));
  const st = el("div", "hyp-status" + (run.status === "error" ? " err" : ""));
  if (run.status === "running") st.innerHTML = `<span class="dot-pulse"></span> The Council is deliberating${run.rounds.length ? " — round " + run.rounds.length : ""}…`;
  else if (run.status === "error") st.textContent = (run.meta && run.meta.error) || "The run failed.";
  else if (run.status === "needs_spec") st.textContent = "Needs specification — too broad for a decisive test yet.";
  else st.textContent = `Converged in ${(run.meta && run.meta.rounds_used) || run.rounds.length} round(s) · ${(run.meta && run.meta.substantive_objections) || 0} substantive objection(s)`;
  m.appendChild(st);
  if (run.status === "needs_spec") { m.appendChild(needsSpecEl(run)); return; }   // the sufficiency gate — refine & re-convene
  if (run.hypothesis && run.hypothesis.claim) m.appendChild(hypBlockEl(run.hypothesis));
  if (run.rounds && run.rounds.length) {
    const resolutions = (run.meta && run.meta.resolutions) || {};
    m.appendChild(el("div", "label", `The debate — ${run.rounds.length} round(s)`));
    run.rounds.forEach((r, i) => m.appendChild(roundEl(r, i === run.rounds.length - 1, resolutions)));
  }
  if (run.designs && run.designs.length) {
    state._hypSource = { hyp_id: run.id, question: run.question };   // so a queued falsifier remembers which hypothesis it came from
    m.appendChild(el("div", "label", "Falsifier panel"));
    m.appendChild(designTable(run));
  }
  if (run.status === "done" && run.hypothesis && run.hypothesis.claim) {
    const ho = el("div", "hyp-handover");
    const open = el("button", "hyp-open"); open.innerHTML = `Open in Cellwright ${ARROW_SVG}`;
    open.onclick = () => openInCellwright(run); ho.appendChild(open);
    const copy = el("button", "hyp-copy", "Copy spec");
    copy.onclick = () => { navigator.clipboard.writeText(hypSpec(run.hypothesis)); copy.textContent = "Copied ✓"; setTimeout(() => (copy.textContent = "Copy spec"), 1200); };
    ho.appendChild(copy);
    if (run.id) { const del = el("button", "hyp-del", "Delete"); del.onclick = () => deleteHypRun(run.id); ho.appendChild(del); }
    m.appendChild(ho);
  }
}
function hypSpec(hyp) {
  return [hyp.brief, hyp.claim && ("Claim: " + hyp.claim), hyp.h1 && ("H1: " + hyp.h1), hyp.h0 && ("H0: " + hyp.h0),
          hyp.falsifier && ("Falsifier: " + hyp.falsifier)].filter(Boolean).join("\n\n");
}
function openInCellwright(run) {
  const hyp = run.hypothesis || {};
  const brief = hyp.brief || hypSpec(hyp);
  const designs = (run.designs || []).map((d) => {
    const g = (d.genes && d.genes.length) ? "KO:" + d.genes.join("+") : (d.condition || "basal");
    return `- ${d.perturbation} · ${g} (${d.seeds}×${d.generations})`;
  }).join("\n");
  const msg = `The Socratic Council framed this falsifiable hypothesis blind to the data. Help me TEST it:\n\n${brief}` +
    (designs ? `\n\nThe Council's falsifier designs:\n${designs}` : "") +
    `\n\nApproach: survey the corpus for the falsifier's channel(s). If the runs the falsifier needs ALREADY EXIST, ` +
    `run the test and report support/refute, grounding every number in a tool result. If the corpus does NOT yet ` +
    `have those runs, DO NOT call the hypothesis untestable — instead propose the missing falsifier experiments to ` +
    `the launch airlock. Queue the WHOLE panel in ONE call with propose_experiments(designs=[...]) — including the ` +
    `discriminating controls — never one-at-a-time (that runs out of turns and drops the controls). A hypothesis ` +
    `whose data doesn't exist yet is a reason to RUN experiments, not grounds to reject it. Say clearly which of the two paths you're taking and why.`;
  closeHyp();
  resetToHero();
  const cb = $("#council"); if (cb) cb.checked = false;   // (legacy toggle retired; the Council already framed it)
  send(msg);
}
async function deleteHypRun(id) {
  await postJSON("/api/hypothesis_delete", { id });
  state.hypActive = null;
  await loadHypRuns(null);
  newHypComposer();
}

const PERT_LABEL = {
  wildtype: "Wildtype (baseline)", gene_knockout: "Gene knockouts", multi_gene_knockout: "Multi-gene knockouts",
  ppgpp_conc: "ppGpp sweep", rrna_operon_knockout: "rRNA operon knockouts", condition: "Media conditions",
};
const pertLabel = (p) => PERT_LABEL[p] || String(p).replace(/_/g, " ");
const geneOf = (r) => (String(r.condition || "").startsWith("KO:") ? r.condition.slice(3) : "");
function primaryLabel(r) {
  const g = geneOf(r);
  if (g) return g;
  if (r.perturbation === "wildtype") return "wildtype";
  return r.condition || r.timeline || r.perturbation;
}
function corpusStats(rows) {
  const byPert = {}, byQc = { ok: 0, flagged: 0 }, byProv = { in_sample: 0, out_of_sample: 0 };
  rows.forEach((r) => {
    byPert[r.perturbation] = (byPert[r.perturbation] || 0) + 1;
    r.qc === "ok" ? byQc.ok++ : byQc.flagged++;
    (r.provenance === "out_of_sample" ? byProv.out_of_sample++ : byProv.in_sample++);
  });
  return { byPert, byQc, byProv };
}
function facetChip(label, active, onclick) {
  const c = el("button", "facet" + (active ? " active" : ""), esc(label)); c.onclick = onclick; return c;
}
function renderFacets() {
  const f = state.corpusFacet, stats = corpusStats(state.results || []), box = $("#corpusFacets");
  box.innerHTML = "";
  const redo = () => renderCorpus($("#corpusSearch").value);
  const r1 = el("div", "facet-row"); r1.appendChild(el("span", "facet-lbl", "Design"));
  r1.appendChild(facetChip("all", !f.type, () => { f.type = null; redo(); }));
  Object.keys(stats.byPert).sort((a, b) => stats.byPert[b] - stats.byPert[a]).forEach((p) =>
    r1.appendChild(facetChip(`${pertLabel(p)} · ${stats.byPert[p]}`, f.type === p, () => { f.type = f.type === p ? null : p; redo(); })));
  box.appendChild(r1);
  const r2 = el("div", "facet-row"); r2.appendChild(el("span", "facet-lbl", "Filter"));
  const tog = (key, val) => () => { f[key] = f[key] === val ? null : val; redo(); };
  r2.appendChild(facetChip(`OK · ${stats.byQc.ok}`, f.qc === "ok", tog("qc", "ok")));
  r2.appendChild(facetChip(`flagged · ${stats.byQc.flagged}`, f.qc === "flagged", tog("qc", "flagged")));
  r2.appendChild(facetChip(`out-of-sample · ${stats.byProv.out_of_sample}`, f.prov === "out_of_sample", tog("prov", "out_of_sample")));
  r2.appendChild(facetChip(`in-sample · ${stats.byProv.in_sample}`, f.prov === "in_sample", tog("prov", "in_sample")));
  box.appendChild(r2);
}
function renderCorpus(search) {
  if (!state.corpusFacet) state.corpusFacet = { type: null, qc: null, prov: null };
  const f = state.corpusFacet, q = (search || "").trim().toLowerCase();
  const rows = (state.results || []).filter((r) => {
    if (f.type && r.perturbation !== f.type) return false;
    if (f.qc === "ok" && r.qc !== "ok") return false;
    if (f.qc === "flagged" && r.qc === "ok") return false;
    if (f.prov && (r.provenance || "in_sample") !== f.prov) return false;
    if (q && !`${r.perturbation} ${r.condition || ""} ${geneOf(r)} ${r.label || ""} ${r.id}`.toLowerCase().includes(q)) return false;
    return true;
  });
  $("#corpusCount").textContent = `${rows.length} of ${(state.results || []).length} runs`;
  renderFacets();
  const b = $("#corpusBody"); b.innerHTML = "";
  if (!rows.length) { b.appendChild(el("div", "empty", "No runs match. Clear a filter or the search above.")); return; }
  const groups = {};
  rows.forEach((r) => (groups[r.perturbation] = groups[r.perturbation] || []).push(r));
  Object.keys(groups).sort((a, c) => groups[c].length - groups[a].length).forEach((p) => {
    b.appendChild(el("div", "res-group", `${esc(pertLabel(p))}<span class="rg-count">${groups[p].length}</span>`));
    groups[p].forEach((r) => b.appendChild(resRow(r)));
  });
}
function resRow(r) {
  const d = el("details", "res");
  const g = geneOf(r), qcBad = r.qc && r.qc !== "ok";
  const sub = [r.perturbation.replace(/_/g, " "), (g ? "" : (r.condition || r.timeline || "")), `seed ${r.seed}`].filter(Boolean).join(" · ");
  d.appendChild(el("summary", null,
    `<span class="r-primary">${esc(primaryLabel(r))}</span>` +
    `<span class="r-sub">${esc(sub)}</span>` +
    `<span class="r-tags"><span class="tag ${qcBad ? "qc-bad" : "qc-ok"}">${esc(r.qc || "ok")}</span>` +
    `<span class="tag ${r.provenance === "out_of_sample" ? "oos" : ""}">${esc((r.provenance || "").replace("_", "-") || "—")}</span></span>` +
    `<span class="r-chev">›</span>`));
  const box = el("div", "avail", `<div class="empty" style="padding:0">Loading availability…</div>`);
  d.appendChild(box);
  d.addEventListener("toggle", async () => {
    if (!d.open || d.dataset.loaded) return;
    d.dataset.loaded = "1";
    try {
      const a = await (await fetch("/api/result_availability?id=" + encodeURIComponent(r.id))).json();
      box.innerHTML = ""; box.appendChild(availView(a));
    } catch (e) { box.innerHTML = `<span class="no">availability unavailable: ${esc(String(e))}</span>`; }
  });
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
const DRAWER_ID = { queue: "#queueDrawer", figures: "#figuresDrawer" };
function openDrawer(which) { closeDrawers(); $("#scrim").classList.add("show"); $(DRAWER_ID[which] || DRAWER_ID.queue).classList.add("open"); if (which === "council") clearBadge("councilBadge"); }
function closeDrawers() { $("#scrim").classList.remove("show"); Object.values(DRAWER_ID).forEach((id) => $(id).classList.remove("open")); }
function bumpBadge(id, n) { const b = $("#" + id); if (!b) return; if (n > 0) { b.textContent = n; b.classList.add("show"); } else b.classList.remove("show"); }
function clearBadge(id) { const b = $("#" + id); if (b) b.classList.remove("show"); }
async function postJSON(url, body) { return (await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })).json(); }
async function loadModels() {
  try {
    const j = await (await fetch("/api/models")).json();
    const ms = $("#model"); ms.innerHTML = ""; state.modelLabels = {};
    j.models.forEach((m) => { const o = el("option"); o.value = m.id; o.textContent = m.label; o.title = m.note; ms.appendChild(o); state.modelLabels[m.id] = m.label; });
    state.model = j.default; ms.value = j.default; ms.onchange = () => (state.model = ms.value);
    const rs = $("#reasoning"); rs.innerHTML = "";
    (j.reasoning || []).forEach((r) => { const o = el("option"); o.value = r.id; o.textContent = r.label; rs.appendChild(o); });
    state.reasoning = j.reasoning_default || "none"; rs.value = state.reasoning; rs.onchange = () => (state.reasoning = rs.value);
  } catch { /* offline */ }
}
function autosize() { const t = $("#q"); t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 200) + "px"; }

$("#send").onclick = () => (isRunning() ? stopCurrent() : send());
$("#q").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
$("#q").addEventListener("input", autosize);
$("#newBtn").onclick = resetToHero;
$("#corpusBtn").onclick = () => ($("#corpusView").classList.contains("open") ? closeCorpus() : openCorpus());
$("#corpusClose").onclick = closeCorpus;
$("#corpusSearch").addEventListener("input", (e) => renderCorpus(e.target.value));
$("#navSegInv").onclick = closeHyp;                 // top-level workspace switch (sidebar)
$("#navSegHyp").onclick = openHyp;
$("#hypClose").onclick = closeHyp;
$("#hypNewBtn").onclick = newHypComposer;
$("#sidebarCollapse").onclick = () => $("#app").classList.add("sidebar-collapsed");
$("#sidebarExpand").onclick = () => $("#app").classList.remove("sidebar-collapsed");
$("#queueBtn").onclick = () => openDrawer("queue");
$("#figuresBtn").onclick = () => { renderFigures(state.cur); openDrawer("figures"); };
$("#scrim").onclick = closeDrawers;
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeCorpus(); closeHyp(); closeDrawers(); } });
$("#scroll").addEventListener("scroll", () => {
  const s = $("#scroll"); $("#scrollDownBtn").classList.toggle("show", s.scrollHeight - s.scrollTop - s.clientHeight > 140);
});
$("#scrollDownBtn").onclick = () => { scrollBottom(true); $("#scrollDownBtn").classList.remove("show"); };
document.querySelectorAll("[data-close]").forEach((b) => (b.onclick = closeDrawers));
document.querySelectorAll(".chip").forEach((c) => (c.onclick = () => send(c.dataset.q)));

loadModels(); loadInvs(); renderSidebar(); refreshQueue(); updateSend();
