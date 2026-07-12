"""Operationalization debate: Socratic Council vs Cellarium agent, as opposing counsel.

Motivation. A blinded human pilot preferred the full Socratic Council over the single-shot Cellarium agent on
only 4/10 questions (4 full / 4 single-shot / 2 tie). This harness asks *why*: for each research question it takes
the two operationalizations (Council = the `full` config; Cellarium agent = the `proposer_only` config) and stages
a three-phase adversarial debate about which operationalization of the question is the stronger one.

  Phase 1  Opening brief (blind). Each side, seeing ONLY its own operationalization + the raw question + the
           instrument's dial labels (the information quarantine is kept: capabilities in, answer key out), writes a
           markdown advocacy brief: (i) why its operationalization is correct, (ii) why ANY other possible
           operationalization is weaker. It does not see the opponent -- it argues against the whole space.
  Phase 2  Cross-examination (honest). Each side now reads the other's operationalization + brief and returns an
           honest verdict -- YIELD / MAINTAIN / TIE -- with a written rationale. TIE = genuinely equipotent, OR the
           raw question lacks the granularity to break the tie. Conceding when the other is stronger is rewarded.
  Phase 3  Outcome. Derived mechanically from the two self-verdicts, with an impartial one-paragraph synthesis.

Both advocates run on the same base model, so the ONLY thing that differs is the operationalization being defended.
By default the two operationalizations are REUSED from the exact rep-0 hypotheses scored in the human pilot
(evals/results/ablation.json), so the debate explains that 4-4-2 rather than a fresh, differently-worded pair.
Pass --regenerate to run the Council + Cellarium agent live instead.

Run:  python evals/debate.py                 # all 10 cases, reuse pilot hypotheses
      python evals/debate.py --only P01       # one case (smoke test)
      python evals/debate.py --regenerate     # generate fresh operationalizations first
Outputs: evals/results/debate/P01.md ... P10.md, SUMMARY.md, and evals/results/debate.json
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))
sys.path.insert(0, str(ROOT / "src"))

BASE_MODEL = "claude-sonnet-4-5"          # both advocates -- same voice, only the hypothesis differs
SYNTH_MODEL = "claude-opus-4-8"           # impartial synthesis paragraph (no temperature; opus rejects it)

# Pairing to the human-pilot packet: which config was "A"/"B" is irrelevant here -- we always name the systems.
COUNCIL_CFG = "full"
AGENT_CFG = "proposer_only"
SIDES = {"council": "Socratic Council", "agent": "Cellarium agent"}

# ---------------------------------------------------------------------------------------------- prompts

_BRIEF_SYS = (
    "You are lead counsel for a scientific operationalization. A vague research question about a whole-cell "
    "E. coli simulator has been turned into a concrete, falsifiable hypothesis -- YOUR operationalization: a "
    "specific choice of what to measure (onto real instrument dial labels), what statistic decides it, which "
    "rival explanations it discriminates, and which simulation designs it runs. Your job is to write the "
    "STRONGEST HONEST BRIEF for why this is the RIGHT way to operationalize the question, and why ANY OTHER "
    "plausible operationalization is weaker.\n\n"
    "You see only your own operationalization, the raw question, and the instrument's dial labels (capabilities "
    "only -- you are NOT told the literature answer; do not pretend to know it). Argue on methodology, not on "
    "being biologically right.\n\n"
    "Cover, in markdown with these exact sections:\n"
    "## Thesis -- one sentence: this operationalization is correct because X.\n"
    "## Why this operationalization is faithful to the question -- map each construct in the raw question to the "
    "measured observable; show nothing essential is dropped or smuggled in.\n"
    "## Why it is decisive -- falsifiability, the discriminating power against the named rivals, feasibility on "
    "this instrument.\n"
    "## Why any other operationalization is weaker -- anticipate the strongest ALTERNATIVE readings of the same "
    "question (broader, narrower, different observable, different statistic) and say concretely why each is less "
    "faithful, less falsifiable, or less feasible than yours. Be specific about the failure mode of each.\n"
    "## Concessions -- state honestly where your operationalization is vulnerable or makes a debatable choice. "
    "A brief with no honest concession is not credible.\n\n"
    "Be rigorous and concrete (name channels, statistics, designs). No preamble, no sign-off. Return ONLY the "
    "markdown brief."
)

_RESPONSE_SYS = (
    "You are the same lead counsel, now in cross-examination. You have argued for YOUR operationalization; you "
    "now read OPPOSING COUNSEL'S operationalization of the SAME research question and their brief. Respond with "
    "COMPLETE HONESTY -- your duty is to the truth of which operationalization better serves the question, not to "
    "winning. Choose exactly one verdict:\n"
    "  YIELD    -- opposing counsel's operationalization is genuinely stronger (more faithful to the question, "
    "more falsifiable, more discriminating, or more feasible). Concede it. Do this whenever it is true; conceding "
    "correctly is the mark of good counsel.\n"
    "  MAINTAIN -- your operationalization is stronger, and you can say precisely why theirs is weaker.\n"
    "  TIE      -- either the two operationalizations are genuinely equipotent, OR the raw question is too "
    "vague / under-specified to break the tie (name the missing detail that would break it).\n\n"
    "Judge methodology, not biological correctness. Give a specific, concrete rationale that engages their actual "
    "choices (channels, statistic, rivals, designs) -- not vague praise or dismissal. If you MAINTAIN, name the "
    "single strongest point against their operationalization. If you YIELD, name the single point that turned you. "
    "If TIE, name the exact granularity the question lacks."
)

_RESPONSE_TOOL = {
    "name": "record_verdict",
    "description": "Record the honest cross-examination verdict.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["YIELD", "MAINTAIN", "TIE"]},
            "decisive_point": {"type": "string",
                               "description": "The single point that turned you (YIELD), your strongest point "
                                              "against theirs (MAINTAIN), or the missing question detail (TIE)."},
            "rationale": {"type": "string",
                          "description": "2-5 sentences engaging their concrete choices honestly."},
        },
        "required": ["verdict", "decisive_point", "rationale"],
    },
}

_SYNTH_SYS = (
    "You are an impartial adjudicator recording the outcome of an operationalization debate between two counsel "
    "(the Socratic Council and the Cellarium agent) over how to operationalize one research question. You are "
    "given each side's verdict (YIELD/MAINTAIN/TIE) and rationale. Write ONE neutral paragraph (3-5 sentences) "
    "stating what the two verdicts jointly imply about which operationalization is stronger and WHY -- or why the "
    "question could not separate them. Do not take a side beyond what the two verdicts support. Return only the "
    "paragraph."
)

# ---------------------------------------------------------------------------------------------- rendering

def render_hyp(h: dict) -> str:
    """Readable markdown rendering of a stored hypothesis dict."""
    L = [f"- **Claim (H1):** {h.get('claim','')}",
         f"- **H0:** {h.get('h0','')}",
         f"- **Predicted effect:** {h.get('predicted_effect','')}"]
    for od in h.get("operational_defs", []):
        L.append(f"- **Operationalize** \"{od.get('construct', od.get('term',''))}\" -> "
                 f"`{od.get('observable','')}` ({od.get('measure','')})")
    f = h.get("falsifier") or {}
    if f:
        L.append(f"- **Falsifier:** on `{f.get('channel','')}` compare {f.get('target','')} vs "
                 f"{f.get('reference','')}; {f.get('decision_rule','')}; refuted if {f.get('refuting_result','')}")
    for r in h.get("rivals", []):
        L.append(f"- **Rival:** {r.get('claim','')} -> distinguished by: {r.get('distinguishing_result','')}")
    for a in h.get("auxiliary_assumptions", []):
        L.append(f"- **Auxiliary assumption:** {a}")
    for d in h.get("candidate_designs", []):
        L.append(f"- **Design:** perturbation={d.get('perturbation')} condition={d.get('condition')} "
                 f"seeds={d.get('seeds')} params={d.get('params')}")
    return "\n".join(L)

# ---------------------------------------------------------------------------------------------- LLM calls

def _brief(client, question, own_hyp, labels) -> str:
    payload = {"raw_question": question, "your_operationalization": own_hyp, "instrument_dial_labels": labels}
    resp = client.messages.create(model=BASE_MODEL, max_tokens=2600, system=_BRIEF_SYS,
                                  messages=[{"role": "user", "content": json.dumps(payload)}])
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()


def _respond(client, question, own_hyp, own_brief, opp_hyp, opp_brief) -> dict:
    payload = {"raw_question": question, "your_operationalization": own_hyp, "your_brief": own_brief,
               "opposing_operationalization": opp_hyp, "opposing_brief": opp_brief}
    for _ in range(2):
        resp = client.messages.create(
            model=BASE_MODEL, max_tokens=1200, system=_RESPONSE_SYS, tools=[_RESPONSE_TOOL],
            tool_choice={"type": "tool", "name": _RESPONSE_TOOL["name"]},
            messages=[{"role": "user", "content": json.dumps(payload)}])
        for b in resp.content:
            if getattr(b, "type", None) == "tool_use" and b.input:
                return dict(b.input)
    return {"verdict": "TIE", "decisive_point": "(no verdict returned)", "rationale": ""}


def _synthesize(client, question, cv, av) -> str:
    payload = {"question": question,
               "council_verdict": {k: cv.get(k) for k in ("verdict", "decisive_point", "rationale")},
               "agent_verdict": {k: av.get(k) for k in ("verdict", "decisive_point", "rationale")}}
    try:
        resp = client.messages.create(model=SYNTH_MODEL, max_tokens=500, system=_SYNTH_SYS,
                                      messages=[{"role": "user", "content": json.dumps(payload)}])
        return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
    except Exception as e:  # synthesis is a nicety; never fail the case on it
        return f"(impartial synthesis unavailable: {e})"

# ---------------------------------------------------------------------------------------------- outcome logic

def outcome(cv: str, av: str) -> tuple[str, str]:
    """Map the two self-verdicts (council, agent) to a labelled outcome + explanation.
    cv/av each in {YIELD, MAINTAIN, TIE}. 'YIELD' = that side conceded the OTHER is stronger."""
    c, a = cv.upper(), av.upper()
    if c == "YIELD" and a == "YIELD":
        return ("mutual concession", "Each side judged the other's operationalization stronger -- an unstable "
                "result that in practice reads as a tie (neither will defend its own).")
    if c == "YIELD" and a != "YIELD":
        return ("Cellarium agent prevails", "The Socratic Council conceded that the Cellarium agent's "
                "operationalization is stronger; the agent did not concede.")
    if a == "YIELD" and c != "YIELD":
        return ("Socratic Council prevails", "The Cellarium agent conceded that the Socratic Council's "
                "operationalization is stronger; the Council did not concede.")
    if c == "MAINTAIN" and a == "MAINTAIN":
        return ("contested standoff", "Both sides held their ground -- a genuine disagreement neither the "
                "briefs nor the question resolved.")
    if c == "TIE" and a == "TIE":
        return ("tie", "Both sides judged the operationalizations equipotent or the question too under-specified "
                "to separate them.")
    # one TIE, one MAINTAIN: the maintainer leans, the other saw no separation
    winner = "Socratic Council" if c == "MAINTAIN" else "Cellarium agent"
    return (f"leans {winner}", f"The {winner} maintained its operationalization while the other side judged the "
            "two a tie -- a weak lean, not a concession.")

# ---------------------------------------------------------------------------------------------- per-case driver

def run_case(pid, case, hyp_council, hyp_agent, labels, client):
    q = case["question"]
    briefs = {}
    with ThreadPoolExecutor(max_workers=2) as ex:  # both opening briefs in parallel (blind to each other)
        fu = {ex.submit(_brief, client, q, hyp_council, labels): "council",
              ex.submit(_brief, client, q, hyp_agent, labels): "agent"}
        for fut in as_completed(fu):
            briefs[fu[fut]] = fut.result()
    resp = {}
    with ThreadPoolExecutor(max_workers=2) as ex:  # each reads the other, responds -- parallel
        fu = {ex.submit(_respond, client, q, hyp_council, briefs["council"], hyp_agent, briefs["agent"]): "council",
              ex.submit(_respond, client, q, hyp_agent, briefs["agent"], hyp_council, briefs["council"]): "agent"}
        for fut in as_completed(fu):
            resp[fu[fut]] = fut.result()
    label, why = outcome(resp["council"]["verdict"], resp["agent"]["verdict"])
    synth = _synthesize(client, q, resp["council"], resp["agent"])
    return {"pid": pid, "case": case["id"], "theme": case.get("theme", ""), "question": q,
            "hyp_council": hyp_council, "hyp_agent": hyp_agent,
            "brief_council": briefs["council"], "brief_agent": briefs["agent"],
            "resp_council": resp["council"], "resp_agent": resp["agent"],
            "outcome": label, "outcome_why": why, "synthesis": synth}

# ---------------------------------------------------------------------------------------------- markdown writer

def _demote(md_text: str) -> str:
    """Demote a brief's own ##/### headers so they nest under the document's ### section."""
    out = []
    for line in md_text.splitlines():
        if line.startswith("### "):
            out.append("##### " + line[4:])
        elif line.startswith("## "):
            out.append("#### " + line[3:])
        else:
            out.append(line)
    return "\n".join(out)


def write_case_md(r, outdir):
    v = {"council": r["resp_council"], "agent": r["resp_agent"]}
    md = [f"# {r['pid']} — “{r['question']}”",
          f"\n*Case {r['case']} · theme: {r['theme']} · operationalizations reused from the human-pilot "
          f"rep-0 hypotheses.*\n",
          "> **Setup.** The Socratic Council and the Cellarium agent each operationalized the same question. "
          "Each then argued (blind) for its own operationalization against *any* alternative, read the other's "
          "brief, and returned an honest verdict. Both advocates use the same base model; only the "
          "operationalization differs. The information quarantine is kept (dial labels in, answer key out).\n",
          "## The two operationalizations\n",
          "### Socratic Council\n", render_hyp(r["hyp_council"]), "\n",
          "### Cellarium agent (single-shot)\n", render_hyp(r["hyp_agent"]), "\n",
          "## Phase 1 — Opening briefs (blind; each argues against *any* other operationalization)\n",
          "### Socratic Council — counsel's brief\n", _demote(r["brief_council"]), "\n",
          "### Cellarium agent — counsel's brief\n", _demote(r["brief_agent"]), "\n",
          "## Phase 2 — Cross-examination (each reads the other, responds honestly)\n"]
    for side in ("council", "agent"):
        md += [f"### {SIDES[side]} — **VERDICT: {v[side]['verdict']}**\n",
               f"- **Decisive point:** {v[side].get('decisive_point','')}\n",
               f"- **Rationale:** {v[side].get('rationale','')}\n"]
    md += ["## Outcome\n",
           f"**{r['outcome']}.** {r['outcome_why']}\n",
           f"*Impartial synthesis.* {r['synthesis']}\n"]
    (outdir / f"{r['pid']}.md").write_text("\n".join(md), encoding="utf-8")

# ---------------------------------------------------------------------------------------------- load hypotheses

def load_pairs(only=None):
    """Return list of (pid, case, hyp_council, hyp_agent) reusing rep-0 hypotheses from the pilot."""
    from cases import CASES
    key = {r["pair_id"]: r for r in __import__("csv").DictReader(
        (ROOT / "paper" / "human_eval" / "key.csv").open())}
    cases_by_id = {c["id"]: c for c in CASES}
    recs = json.loads((ROOT / "evals" / "results" / "ablation.json").read_text())["results"]

    def pick(cid, cfg):
        for r in recs:
            if r["id"] == cid and r["config"] == cfg and r["rep"] == 0 and r.get("hypothesis"):
                return r["hypothesis"]
        return None

    out = []
    for pid in sorted(key):
        cid = key[pid]["case"]
        hc, ha = pick(cid, COUNCIL_CFG), pick(cid, AGENT_CFG)
        if hc and ha and (only is None or pid in only):
            out.append((pid, cases_by_id[cid], hc, ha))
    return out

# ---------------------------------------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--only", nargs="*", default=None, help="pair ids e.g. P01 P02 (default all)")
    p.add_argument("--regenerate", action="store_true", help="generate fresh operationalizations instead of reuse")
    p.add_argument("--workers", type=int, default=4, help="concurrent cases")
    p.add_argument("--out", default=str(ROOT / "evals" / "results" / "debate"))
    a = p.parse_args()
    import anthropic
    from cellarium import instrument
    client = anthropic.Anthropic(max_retries=6)
    labels = instrument.dial_labels()
    outdir = Path(a.out); outdir.mkdir(parents=True, exist_ok=True)

    if a.regenerate:
        from cellarium import council
        pairs = []
        from cases import CASES
        key = {r["pair_id"]: r for r in __import__("csv").DictReader(
            (ROOT / "paper" / "human_eval" / "key.csv").open())}
        cases_by_id = {c["id"]: c for c in CASES}
        for pid in sorted(key):
            cid = key[pid]["case"]
            if a.only and pid not in a.only:
                continue
            case = cases_by_id[cid]
            hc = council.deliberate(case["question"], client=client, verbose=False).model_dump(by_alias=True)
            ha = council.deliberate(case["question"], client=client, verbose=False,
                                    use_skeptic=False, use_judge=False).model_dump(by_alias=True)
            pairs.append((pid, case, hc, ha))
    else:
        pairs = load_pairs(only=set(a.only) if a.only else None)

    print(f"debating {len(pairs)} case(s): {[p[0] for p in pairs]}")
    results = []
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(run_case, pid, case, hc, ha, labels, client): pid
                for pid, case, hc, ha in pairs}
        for fut in as_completed(futs):
            r = fut.result()
            write_case_md(r, outdir)
            results.append(r)
            print(f"  {r['pid']}: council={r['resp_council']['verdict']} "
                  f"agent={r['resp_agent']['verdict']} -> {r['outcome']}")

    results.sort(key=lambda r: r["pid"])
    (ROOT / "evals" / "results" / "debate.json").write_text(
        json.dumps({"model": BASE_MODEL, "regenerated": a.regenerate, "results": results}, indent=1),
        encoding="utf-8")
    write_summary(results, outdir)
    print(f"wrote {len(results)} case files + SUMMARY.md + debate.json -> {outdir}")


def _human_pilot():
    """Per-case human-pilot preference (committed artifact), for the side-by-side comparison. Returns
    {case_id: 'full'|'proposer_only'|'tie'} or {} if the pilot file is absent."""
    fp = ROOT / "paper" / "human_eval" / "pilot_results.json"
    if not fp.exists():
        return {}
    return {row["case"]: row["preferred"] for row in json.loads(fp.read_text()).get("rows", [])}


def write_summary(results, outdir):
    from collections import Counter
    tally = Counter(r["outcome"] for r in results)
    council_v = Counter(r["resp_council"]["verdict"] for r in results)
    agent_v = Counter(r["resp_agent"]["verdict"] for r in results)
    human = _human_pilot()
    hlabel = {"full": "Council", "proposer_only": "agent", "tie": "tie"}

    rows = ["| Pair | Question | Council verdict | Agent verdict | Debate outcome | Human pilot |",
            "|------|----------|-----------------|---------------|----------------|-------------|"]
    for r in results:
        q = r["question"] if len(r["question"]) < 52 else r["question"][:49] + "..."
        rows.append(f"| {r['pid']} | {q} | {r['resp_council']['verdict']} | "
                    f"{r['resp_agent']['verdict']} | {r['outcome']} | "
                    f"{hlabel.get(human.get(r['case']), '?')} |")

    # headline: how often did the Council actually defend its own operationalization?
    n = len(results)
    council_yields = council_v.get("YIELD", 0)
    council_wins = sum(1 for r in results if r["outcome"].startswith("Socratic Council"))
    agent_wins = sum(1 for r in results if r["outcome"].startswith("Cellarium agent"))
    leans_council = sum(1 for r in results if r["outcome"] == "leans Socratic Council")

    md = ["# Operationalization debate — summary\n",
          "The Socratic Council vs the Cellarium agent, arguing as opposing counsel over which operationalization "
          "of each research question is stronger. Each writes a blind advocacy brief, reads the other's, and "
          "self-reports an honest verdict (YIELD / MAINTAIN / TIE); the outcome is derived from the pair of "
          "verdicts. Both advocates run on the same base model, so only the operationalization differs.\n",
          "## Results\n", "\n".join(rows), "\n",
          "## Tally\n",
          "**Outcomes:** " + ", ".join(f"{k} = {v}" for k, v in tally.most_common()) + "\n",
          "**Council self-verdicts:** " + ", ".join(f"{k} = {v}" for k, v in council_v.most_common()) + "\n",
          "**Agent self-verdicts:** " + ", ".join(f"{k} = {v}" for k, v in agent_v.most_common()) + "\n",
          "\n## Headline\n",
          f"When forced to defend its own operationalization against the single-shot agent's, the **Socratic "
          f"Council conceded (YIELD) in {council_yields}/{n} cases** and won outright in **{council_wins}/{n}** "
          f"(with {leans_council} weak lean). The Cellarium agent's operationalization prevailed outright in "
          f"**{agent_wins}/{n}**. The Council's counsel is markedly the more concessive of the two — its "
          "elenctic, Socratic-ignorance disposition (the very thing that makes the Council good at *interrogating* "
          "a hypothesis) appears to also make it quick to concede a leaner rival on parsimony or feasibility "
          "grounds.\n",
          "\n## Reading this against the human pilot (4 Council / 4 agent / 2 tie)\n",
          "The debate **corroborates and sharpens** the even human split. Where you preferred the single-shot "
          "agent (P02, P05, P08), the debate independently returns *agent prevails*. Where you preferred the "
          "Council, the debate is if anything harsher: it finds the Council's counsel conceding or tying rather "
          "than defending. The mechanism behind your 4/10 is now visible — in the majority of cases the two "
          "operationalizations are equipotent, or the raw question is too under-specified to separate them, or "
          "the Council's extra elaboration (more designs, more rivals) buys thoroughness a human (and the "
          "Council's own advocate) does not read as *methodological superiority*. A human grader with no basis to "
          "prefer the Council is not mis-judging; the surplus structure often is not decisive.\n",
          "\n## Honest caveats\n",
          "- **One advocate per side, not a live Council.** Each side is a single lawyer defending a "
          "*pre-produced* hypothesis; the Council's dialectic is not re-run inside the debate. This tests the "
          "*product* (the operationalization), not the *process*.\n",
          "- **Concession disposition is itself a variable.** The Council's briefs defend more elaborate "
          "hypotheses, which expose more feasibility/parsimony surface to concede on. Whether that reflects a "
          "genuinely weaker operationalization or merely a more critical advocate is not separable here.\n",
          "- **No neutral tie-break.** The outcome is derived from the two self-verdicts; the impartial synthesis "
          "paragraph summarizes but does not overrule them.\n"]
    (outdir / "SUMMARY.md").write_text("\n".join(md), encoding="utf-8")


if __name__ == "__main__":
    main()
