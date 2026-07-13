"""The Claude tool-using loop (Anthropic Messages API).

The agent answers whole-cell questions strictly through the grounded tools, enforces the feasibility +
QC guardrails, and never reports a number it did not read from a tool result.
"""

from __future__ import annotations

import json
import os

import anthropic

from . import tools

MODEL = os.environ.get("CELLARIUM_MODEL", "claude-sonnet-4-5")

SYSTEM = (
    "You are Cellwright, the grounded reasoning agent of Cellarium — a whole-cell E. coli (K-12 MG1655) "
    "simulation platform. Cellarium is the platform; you are Cellwright, the agent who reasons over it.\n"
    "Rules:\n"
    "- SURVEY FIRST. For any question about results, call survey_corpus BEFORE forming a hypothesis, and "
    "reason from that whole ranked view. Do NOT anchor on the first run you look at or on the biggest single "
    "number — the survey ranks every design by computed effect size so your attention isn't what decides what "
    "matters. Only after the survey, drill in with read_series / read_species.\n"
    "- read_series gives the COARSE (~16-point) manifest trajectory. When a question needs full resolution or "
    "cross-seed variance, DRILL INTO THE RAW: raw_available shows what full-resolution simOut is on local disk for "
    "a design; read_raw_series gives one seed's every-timestep trajectory; variance_band gives the true per-timepoint "
    "mean±CI95 ACROSS all local seeds. For 'plot the variance / the spread over time', use chart(kind='band', ...) — "
    "it reads the raw and draws the cross-seed ribbon. These read local disk directly (no download). If a design has "
    "no local raw (raw_available says so), THEN fall back to data_availability for the HF/regenerate path — do not "
    "claim variance can't be computed without first checking raw_available.\n"
    "- Reading local data is free — never ask permission to read raw that is already on disk. But FETCHING raw from "
    "HF costs bandwidth, so it is GATED: call download_raw with confirm=false to get the size, tell the user 'this "
    "pulls ~N GB from HF, proceed?', and only call again with confirm=true AFTER they approve. Never confirm=true on "
    "your own. Launching a NEW simulation stays fully gated by the approval airlock (propose_experiment) — you never "
    "run one without human approval.\n"
    "- BE ECONOMICAL WITH TOOL CALLS (you have a limited turn budget). Do NOT call the same tool once per item when "
    "one call covers the set: viability(perturbation) with NO condition returns EVERY variant (all gene_knockouts) "
    "at once — call it ONCE, never per-KO. To queue a PANEL of designs, call propose_experiments(designs=[...]) ONCE "
    "— it vets each design (safety + feasibility + provenance) for you, so do NOT pre-vet the panel design-by-design "
    "with vet_hypothesis / check_feasibility / screen_design first (those are for a SINGLE ad-hoc design you are "
    "reasoning about, not for every row of a panel). Scope-check only the genes you actually need.\n"
    "- CORPUS MEMBERSHIP — never wrongly say a design is absent. To check 'are there results for X?', call "
    "list_results(gene='X') and read `n` (0 = truly absent); NEVER conclude absence from the unfiltered dump (it is "
    "truncated). Your tools read the SAME manifest as the Corpus Browser, so if the browser shows a run you can't "
    "find, YOUR QUERY is wrong (label/filter) — fix it, do not ask the user to read the ID off the screen. Two more "
    "traps: raw_available=0 / no-local-raw means no full-resolution raw ON DISK, NOT that the run is absent (the "
    "shard still has viability + summary channels); and design labels use '·' ('gene_knockout·KO:pfkA·s0') while "
    "read_series/chart also accept the 'perturbation/condition' form ('gene_knockout/KO:pfkA') — use those, not a made-up id.\n"
    "- A BENCHMARK / PRIOR / mechanistic_scope NOTE is NOT a measured result. If a note says a KO 'crashes ~gen-3', "
    "that is an expectation to VERIFY, not data to report: check for a deep-enough run or propose one, and until then "
    "say 'the note claims X; the run I have (1 gen) shows Y'. When a grounded result appears to disagree with the "
    "literature, report the disagreement HONESTLY and its likely cause (e.g. too-shallow depth) — do not rationalize "
    "it into agreement on an unverified mechanism. To cite a paper, GROUND it via use_skill/web_get; never recall a DOI from memory.\n"
    "- To interpret a KO/perturbation, use differential (what channels/pathways moved most vs control) and "
    "top_movers (which individual proteins) — do NOT pre-decide which molecules matter; let the data rank them.\n"
    "- When asked for the most INTERESTING findings (not merely the biggest effects), weight model-vs-reality "
    "DISAGREEMENTS as highly as large effect sizes: an essential gene the model calls viable (model_UNDER_predicts), "
    "or a channel that moves OPPOSITE to the textbook direction (e.g. an aaRS KO whose ppGpp FALLS when the "
    "stringent response should RAISE it). Ranking by |z| alone surfaces clean physiology and buries the model's "
    "limits — and the limits are the most scientifically valuable, honest result. Cross-check the essentiality "
    "benchmark and the expected direction, not just effect magnitude.\n"
    "- Before interpreting a gene KO, call mechanistic_scope: if the gene is expressed-but-inert (no modeled "
    "function), a null phenotype is model scope, NOT biological dispensability — say so, don't over-read it.\n"
    "- For a KO, judge lethality by VIABILITY (viability tool: does the lineage divide?), NOT growth rate — a "
    "metabolic KO reroutes so growth looks flat even when the gene is essential. And 'viable' is the MODEL; check "
    "mechanistic_scope's benchmark — if agreement=='model_UNDER_predicts', the gene is essential in vivo, so trust "
    "the benchmark over the sim.\n"
    "- To EXPLAIN why a viable metabolic KO shows no phenotype, use reroute_diagnosis: if reroute_is_artifact, the "
    "model bypasses an enzyme real biology can't (the objective never hard-requires that flux). To PROPOSE an "
    "experiment, call design_space first (runnable conditions/variants + the gene's ko_index) — don't guess indices.\n"
    "- READ COLD. Derive conclusions from tool results only. Do not assume anything from earlier conversation, "
    "external notes, or 'what we expected' — if a prior claim conflicts with the tools, the tools win. State "
    "how many runs/designs support each claim; don't generalise from a subset the survey shows is larger.\n"
    "- IN- vs OUT-OF-SAMPLE. Before saying the model 'predicts' or 'validates' anything, call provenance: a "
    "fitted condition (in_sample) agreeing with data is only CONSISTENCY; genuine prediction lives in "
    "out_of_sample perturbations (clamps, KOs, shifts). Never oversell in-sample agreement.\n"
    "- SEEK DISCONFIRMATION. Before committing to a causal claim, call disconfirm on it (is the effect bigger "
    "than replicate noise? does another design contradict it?), and call coverage_check before generalising — "
    "do not claim beyond the designs you actually deep-read. After forming a hypothesis, name what would "
    "falsify it and read exactly those "
    "channels/designs before concluding (e.g. to test 'ppGpp causes the slowdown', check ribosome_conc AND a "
    "design where ppGpp is decoupled).\n"
    "- Ground every quantitative claim in a tool result. Never state a number you did not read from a tool.\n"
    "- When a FIGURE would sharpen the answer — a channel's trajectory over the cell cycle, or a comparison of a "
    "channel across designs — call the `chart` tool to draw it inline (kind='line' for a trajectory, 'bar' for a "
    "comparison). It plots ONLY real run data; never chart a number you did not read. Draw a figure when it helps, "
    "not decoratively. Always pass a one-sentence `rationale` — a grounded takeaway — so the figure stands on its "
    "own in the investigation's Figures panel.\n"
    "- Before proposing to run anything, call check_feasibility AND screen_design. If out of the validated "
    "envelope (e.g. a mid-run carbon-source switch) or flagged by the biosecurity screen, do NOT run it — "
    "explain why and offer the in-envelope alternative. For a design ALREADY in the corpus, also call "
    "screen_phenotype: its simulated proteome can up-regulate a misuse signature (AMR efflux) even if the "
    "design never named those genes — flag that too.\n"
    "- QC has TWO meanings — do not conflate them. For a CONTINUOUS reading (growth rate, doubling time, a channel "
    "mean), a non-'ok' run is evidence-ABSENT: report the flag, never a number derived from it. But for a "
    "VIABILITY / LETHALITY / essentiality question a crash IS the readout — no_division, dead, fba_infeasible and "
    "crashed runs are POSITIVE evidence the KO is inviable (use the viability tool). Count them; never discard a "
    "crashed KO as 'unreportable', and never call a lethality hypothesis untestable BECAUSE its KOs crashed — the "
    "crashes are the data. (implausible_channel/over_replicated flag an untrustworthy NUMBER, not an absent run.)\n"
    "- The model gives the dynamic/regulatory/single-cell regime that steady-state FBA cannot. Prefer "
    "mechanistic explanation (e.g. ppGpp -> ribosome allocation -> growth) grounded in the channels.\n"
    "- Be concise and honest. Users are hypothesis generators, not decision-makers.\n"
    "\nABOUT YOURSELF (answer plainly if asked 'what are you / what is this platform / what is the model'):\n"
    "- You are CELLWRIGHT, the grounded agent. CELLARIUM is the platform: a corpus of whole-cell E. coli "
    "(K-12 MG1655) simulations with a reasoning layer. A Socratic Council first operationalizes a question into a "
    "falsifiable hypothesis BLIND to the data; then you (Cellwright) answer it strictly from real simulation runs "
    "via ~25 tools; you cannot state a number you did not read from a tool, and you cannot launch a simulation — a "
    "human approves every new run.\n"
    "- THE MODEL is the Covert-lab whole-cell model (wcEcoli): a mechanistic single-cell simulation integrating "
    "metabolism (FBA), transcription, translation, replication and regulation over a cell cycle. Its regime is "
    "dynamic/regulatory/single-cell, complementary to steady-state FBA. Its known boundary: the FBA objective is "
    "homeostatic (not growth-maximizing), so metabolic KOs tend to reroute (a viable-KO artifact) — trust the "
    "essentiality benchmark over the sim there. Be honest about scope and provenance (in- vs out-of-sample).\n"
    "- LITERATURE (use_skill + web_get): when the user asks what is already PUBLISHED, whether a grounded result "
    "AGREES with the literature, whether a finding is NOVEL or wet-lab-worthy, or where the model's prediction may "
    "be WRONG vs reality — call use_skill('literature-review' | 'paper-lookup' | 'bgpt-paper-search') to load the "
    "skill, then web_get its endpoints. HARD RULE: the literature is COMPARISON/annotation ONLY, always CITED and "
    "clearly marked external — it NEVER sources a primary number (every number you report still comes from a run). "
    "Don't search on routine read-this-channel turns; reach for it to reconcile sim vs reality, triage novelty, or "
    "probe a model limit. For a 'does it agree with the literature?' reconciliation PREFER use_skill('literature-review') "
    "(it searches AND synthesises a cited brief) over raw paper-lookup; ALWAYS read the skill's per-API reference doc "
    "before web_get — e.g. PubMed E-utilities return XML, so use efetch/esummary with rettype=xml (NOT json, which "
    "comes back empty), and URL-encode query terms. Read at least one abstract, don't reason from result counts alone."
)


def first_user_content(question: str, hypothesis=None) -> str:
    """The opening user turn. With a Council hypothesis, hand the agent the operationalized brief (never a result —
    the docs/SOCRATIC_COUNCIL.md quarantine); the agent still does ALL grounding itself."""
    if hypothesis is None:
        return question
    brief = hypothesis.brief() if hasattr(hypothesis, "brief") else str(hypothesis)
    return (f"{brief}\n\nTest this hypothesis against the corpus using the tools: survey first, then read "
            f"exactly the falsifier's channel(s), seek disconfirmation, and report whether the evidence "
            f"supports or refutes it — grounding every number in a tool result.")


def _system_blocks():
    # prompt caching: the (long, static) system prompt is a cache breakpoint — reused across every turn of a
    # conversation, so we pay to process it once, not on every follow-up.
    return [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}]


def _cached_tools():
    # cache the tool definitions too (they never change) by marking the final tool as a breakpoint.
    ts = [dict(t) for t in tools.TOOLS]
    if ts:
        ts[-1] = {**ts[-1], "cache_control": {"type": "ephemeral"}}
    return ts


# the fields each assistant block type accepts as INPUT. model_dump() also emits output-only fields (e.g. a text
# block's parsed_output / citations) which the API rejects when the history is sent back ("Extra inputs are not
# permitted"), so we whitelist. thinking keeps its signature (required to continue a thinking conversation).
_INPUT_FIELDS = {
    "text": ("type", "text"),
    "tool_use": ("type", "id", "name", "input"),
    "thinking": ("type", "thinking", "signature"),
    "redacted_thinking": ("type", "data"),
}


def _to_dict(block):
    """Anthropic content blocks -> plain, INPUT-VALID JSON dicts (SQLite-serializable + re-sendable to the API)."""
    d = block if isinstance(block, dict) else (block.model_dump() if hasattr(block, "model_dump") else None)
    if d is None:
        return block
    keep = _INPUT_FIELDS.get(d.get("type"))
    return {k: d[k] for k in keep if k in d} if keep else d


def _sanitize(messages: list) -> None:
    """Strip output-only fields from existing assistant content in place — repairs sessions persisted before the
    whitelist (so an in-progress conversation stops 400-ing without the user having to start over)."""
    for m in messages:
        c = m.get("content")
        if isinstance(c, list):
            m["content"] = [_to_dict(b) for b in c]


def _prefix_cached(messages: list) -> list:
    """Incremental prompt caching of the growing CONVERSATION prefix: mark the last content block as a cache
    breakpoint so every turn reuses the cached prefix (system + tools are already cached separately -> 3 of the
    4 allowed breakpoints). Returns a shallow copy for the request; the stored history stays free of the marker."""
    if not messages:
        return messages
    last = messages[-1]
    content = last.get("content")
    if isinstance(content, str):
        marked = {"role": last["role"], "content": [{"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}]}
    elif isinstance(content, list) and content and isinstance(content[-1], dict):
        blocks = list(content)
        blocks[-1] = {**blocks[-1], "cache_control": {"type": "ephemeral"}}
        marked = {"role": last["role"], "content": blocks}
    else:
        return messages
    return messages[:-1] + [marked]


# extended-thinking budgets (reasoning strength). budget_tokens must be >=1024 and < max_tokens.
_REASON = {"none": 0, "low": 2048, "high": 8000}
_TOOL_CAP = 6000   # trim a bulky tool_result before it re-enters the growing context (e.g. species panels)


def _is_thinking_error(exc) -> bool:
    s = str(exc).lower()
    return "thinking" in s or "budget_tokens" in s


# ---- summarization / context compaction -------------------------------------------------------------------
# Durable multi-turn chats grow without bound; past a budget we roll OLD turns into a summary (keeping recent
# turns verbatim) so token cost + latency stay flat and we never hit the context window. Compaction happens only
# at a turn boundary (start of converse), never mid-tool-loop, so tool_use/tool_result pairing is never broken.
_SUMMARY_MODEL = os.environ.get("CELLARIUM_SUMMARY_MODEL", "claude-haiku-4-5-20251001")
_COMPACT_TRIGGER = int(os.environ.get("CELLARIUM_COMPACT_TOKENS", "24000"))  # ~est input tokens
_KEEP_RECENT_TURNS = 3


def _estimate_tokens(messages: list) -> int:
    total = 0
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            total += len(c)
        elif isinstance(c, list):
            for b in c:
                total += len(json.dumps(b, default=str)) if isinstance(b, dict) else len(str(getattr(b, "text", "") or "")) + 40
    return total // 4


def _split_turns(messages: list) -> list:
    """Group the flat message list into turns; a turn STARTS at a user message with string content (a real
    question), so tool_use/tool_result cycles stay inside their turn."""
    turns: list = []
    cur: list = []
    for m in messages:
        if m.get("role") == "user" and isinstance(m.get("content"), str) and cur:
            turns.append(cur); cur = []
        cur.append(m)
    if cur:
        turns.append(cur)
    return turns


def _btype(b):
    return b.get("type") if isinstance(b, dict) else getattr(b, "type", None)


def _summarize(old_turns: list, model: str) -> str:
    """LLM summary of the older turns — faithful, compact, preserving questions, established claims, and the key
    grounded numbers. Bulky tool_results are dropped (only their existence is noted)."""
    parts: list = []
    for t in old_turns:
        for m in t:
            c = m.get("content")
            if isinstance(c, str):
                parts.append(f"{m.get('role', '').upper()}: {c}")
            elif isinstance(c, list):
                for b in c:
                    bt = _btype(b)
                    if bt == "text":
                        parts.append("ASSISTANT: " + (b.get("text") if isinstance(b, dict) else getattr(b, "text", "")))
                    elif bt == "tool_use":
                        parts.append("[called tool: " + str(b.get("name") if isinstance(b, dict) else getattr(b, "name", "")) + "]")
                    elif bt == "tool_result":
                        parts.append("[tool result]")
    transcript = "\n".join(parts)[:20000]
    client = anthropic.Anthropic(max_retries=2)
    resp = client.messages.create(
        model=model, max_tokens=900,
        system=("Summarize this whole-cell reasoning conversation into a compact brief that will REPLACE the raw "
                "history as the agent's memory. Preserve faithfully: the user's questions, the hypotheses/claims "
                "established, the key grounded findings WITH their numbers and the runs they came from, and any "
                "open threads. Be concise and do not invent anything."),
        messages=[{"role": "user", "content": transcript}])
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()


def _strip_tool_results(old_turns: list) -> list:
    """No-LLM fallback: keep every old message (alternation intact) but stub the bulky tool_result payloads."""
    out: list = []
    for t in old_turns:
        for m in t:
            if m.get("role") == "user" and isinstance(m.get("content"), list):
                out.append({"role": "user", "content": [
                    ({**b, "content": "[elided in compaction]"} if isinstance(b, dict) and b.get("type") == "tool_result" else b)
                    for b in m["content"]]})
            else:
                out.append(m)
    return out


def compact_history(messages: list, *, model: str | None = None, keep_recent_turns: int = _KEEP_RECENT_TURNS) -> list:
    """Return a compacted copy: OLD turns rolled into a summary (LLM; falls back to stubbing tool_results),
    recent turns kept verbatim. Alternation-safe: head is user(summary)->assistant(ack), then whole recent turns."""
    turns = _split_turns(messages)
    if len(turns) <= keep_recent_turns + 1:
        return messages
    old, recent = turns[:-keep_recent_turns], turns[-keep_recent_turns:]
    try:
        summary = _summarize(old, model or _SUMMARY_MODEL)
        head = [{"role": "user", "content": "[Summary of the earlier conversation]\n" + summary},
                {"role": "assistant", "content": "Understood — I'll continue with that context."}]
    except Exception:
        head = _strip_tool_results(old)
    return head + [m for t in recent for m in t]


def _run_turn(client, kw: dict, on_text):
    """One model turn, STREAMED. Forwards text deltas to on_text (token streaming) and returns the final message
    (with any tool_use / thinking blocks intact for the loop + history)."""
    with client.messages.stream(**kw) as stream:
        if on_text is not None:
            for delta in stream.text_stream:
                on_text(delta)
        else:
            stream.until_done()
        return stream.get_final_message()


def converse(messages: list, *, model: str | None = None, on_tool=None, on_text=None, on_note=None,
             max_turns: int = 12, verbose: bool = False, reasoning: str = "none") -> str:
    """Run the grounded tool loop over an EXISTING message history (ending in a user turn), mutating `messages`
    in place — appending the assistant + tool_result turns — so the caller can persist it for a MULTI-TURN
    conversation. Returns the final assistant text. This is what makes the chat remember: the same messages list
    carries prior turns, and prompt caching (system + tools) keeps the growing prefix cheap.

    on_text, if given, receives streamed answer-text deltas (token streaming). reasoning ('none'|'low'|'high')
    enables extended thinking on models that support it (falls back to the base model otherwise). The SDK retries
    429/5xx with exponential backoff; bulky tool results are trimmed."""
    from . import rigor

    rigor.reset()  # fresh coverage tracking per user turn
    client = anthropic.Anthropic(max_retries=4)   # exponential backoff on rate limits / transient 5xx
    mdl = model or MODEL
    system, tool_defs = _system_blocks(), _cached_tools()
    budget = _REASON.get(reasoning, 0)

    _sanitize(messages)   # repair any output-only fields from a session saved before the input-field whitelist

    if _estimate_tokens(messages) > _COMPACT_TRIGGER:   # bound the growing context at the turn boundary
        before = len(messages)
        messages[:] = compact_history(messages, model=_SUMMARY_MODEL)
        if on_note is not None and len(messages) < before:
            on_note(f"Compacted {before - len(messages)} earlier messages into a summary to keep the context lean.")

    for _ in range(max_turns):
        kw = dict(model=mdl, system=system, tools=tool_defs, messages=_prefix_cached(messages))
        # max_tokens is a CAP, not a target — the model stops when done, so a generous cap costs nothing on short
        # answers but stops a synthesis ('top 5 findings …') being truncated mid-item. With thinking, leave room for
        # the answer AFTER the reasoning budget.
        if budget:
            kw["thinking"] = {"type": "enabled", "budget_tokens": budget}
            kw["max_tokens"] = budget + 4000
        else:
            kw["max_tokens"] = 4096
        try:
            resp = _run_turn(client, kw, on_text)
        except Exception as exc:                      # extended thinking unsupported here -> retry as base model
            if budget and _is_thinking_error(exc):
                budget = 0
                kw.pop("thinking", None)
                kw["max_tokens"] = 4096
                resp = _run_turn(client, kw, on_text)
            else:
                raise
        messages.append({"role": "assistant", "content": [_to_dict(b) for b in resp.content]})
        tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]

        if resp.stop_reason != "tool_use" or not tool_uses:
            return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()

        results = []
        for tu in tool_uses:
            out = tools.dispatch(tu.name, tu.input)
            if verbose:
                print(f"  tool {tu.name}({json.dumps(tu.input)}) -> {json.dumps(out)[:160]}")
            if on_tool is not None:
                on_tool(tu.name, tu.input, out)   # glass-box hook: stream the grounded tool trace to the interface
            content = json.dumps(out)
            if len(content) > _TOOL_CAP:              # keep the growing context lean
                content = content[:_TOOL_CAP] + ' …[truncated]'
            results.append({"type": "tool_result", "tool_use_id": tu.id, "content": content})
        messages.append({"role": "user", "content": results})

    # Tool budget exhausted while the agent was still calling tools: force ONE final synthesis with tools DISABLED,
    # so a turn ALWAYS ends with a real answer instead of a dangling tool_result. Without this a hard/broad question
    # truncates with no conclusion (seen in ~1/3 of the eval Arm A sweep — 25-message sessions ending on tool_result).
    wrap_system = system + [{"type": "text", "text": (
        "You have reached the tool-call budget for this turn — do NOT request any more tools. Synthesize your FINAL "
        "answer now from the evidence already gathered, and state plainly what is still uncertain or was left "
        "unfinished. Do not fabricate results you did not read.")}]
    try:
        # tool_choice=none forbids further tool calls WITHOUT dropping the tool definitions — dropping them 400s
        # because the history contains tool_use blocks (tools must stay defined once used). Keeping tool_defs also
        # preserves the cached prefix. This is the path that produces the final answer when the budget is spent.
        resp = _run_turn(client, dict(model=mdl, system=wrap_system, tools=tool_defs,
                                      tool_choice={"type": "none"}, messages=_prefix_cached(messages),
                                      max_tokens=(budget + 4000 if budget else 4096)), on_text)
        messages.append({"role": "assistant", "content": [_to_dict(b) for b in resp.content]})
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
        return text or "(stopped: reached max turns without a synthesis)"
    except Exception:
        return "(stopped: reached max turns)"


def run(question: str, *, hypothesis=None, max_turns: int = 8, verbose: bool = True, on_tool=None,
        model: str | None = None) -> str:
    """One-shot convenience: seed a fresh conversation and run it to an answer (used by the CLI / orchestrate)."""
    messages: list = [{"role": "user", "content": first_user_content(question, hypothesis)}]
    return converse(messages, model=model, on_tool=on_tool, max_turns=max_turns, verbose=verbose)
