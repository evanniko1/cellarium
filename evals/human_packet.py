"""Build a blinded human-evaluation packet for judge-validity (paper Workstream D2).

For each case we present a grader with two hypotheses in randomized order---one from the full Council, one from
the single-shot proposer_only baseline---and ask which is methodologically sounder (a blinded pairwise
preference). This directly tests whether human judgement agrees with the LLM auditor's ranking (which prefers
the full Council). Outputs a self-contained HTML packet (readable, print-friendly), an unblinding key, a
scoresheet CSV template, and a protocol. Run: python evals/human_packet.py [--src ablation.json --rep 0].
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _brief(h: dict) -> str:
    """Readable rendering of a hypothesis dict for a human grader."""
    L = [f"Claim (H1): {h.get('claim','')}", f"H0: {h.get('h0','')}",
         f"Predicted effect: {h.get('predicted_effect','')}"]
    for od in h.get("operational_defs", []):
        L.append(f"Operationalize '{od.get('construct', od.get('term',''))}' -> {od.get('observable','')} "
                 f"({od.get('measure','')})")
    f = h.get("falsifier") or {}
    if f:
        L.append(f"Falsifier: on channel '{f.get('channel','')}' compare {f.get('target','')} vs "
                 f"{f.get('reference','')}; {f.get('decision_rule','')}; refuted if {f.get('refuting_result','')}")
    for r in h.get("rivals", []):
        L.append(f"Rival: {r.get('claim','')} -> distinguished by: {r.get('distinguishing_result','')}")
    for d in h.get("candidate_designs", []):
        L.append(f"Design: perturbation={d.get('perturbation')} condition={d.get('condition')} "
                 f"seeds={d.get('seeds')} params={d.get('params')}")
    return "\n".join(L)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--src", default=str(ROOT / "evals" / "results" / "ablation.json"))
    p.add_argument("--rep", type=int, default=0)
    p.add_argument("--seed", type=int, default=20260711)
    p.add_argument("--out", default=str(ROOT / "paper" / "human_eval"))
    a = p.parse_args()
    rng = random.Random(a.seed)
    outdir = Path(a.out); outdir.mkdir(parents=True, exist_ok=True)

    recs = json.loads(Path(a.src).read_text())["results"]
    from cases import CASES  # question text
    import sys; sys.path.insert(0, str(ROOT / "evals"))
    qtext = {c["id"]: c["question"] for c in CASES}

    def pick(cid, cfg):
        for r in recs:
            if r["id"] == cid and r["config"] == cfg and r["rep"] == a.rep and r.get("hypothesis"):
                return r["hypothesis"]
        return None

    pairs, key_rows = [], []
    for cid in sorted(qtext):
        hf, hp = pick(cid, "full"), pick(cid, "proposer_only")
        if not (hf and hp):
            continue
        # randomize which is A vs B; grader is blind to which config
        if rng.random() < 0.5:
            A, B, a_cfg, b_cfg = hf, hp, "full", "proposer_only"
        else:
            A, B, a_cfg, b_cfg = hp, hf, "proposer_only", "full"
        pid = f"P{len(pairs)+1:02d}"
        pairs.append((pid, cid, qtext[cid], A, B))
        key_rows.append({"pair_id": pid, "case": cid, "A_config": a_cfg, "B_config": b_cfg})

    # --- HTML packet ---
    css = ("body{font:14px/1.5 -apple-system,Helvetica,Arial;max-width:820px;margin:2em auto;color:#111}"
           "h2{border-bottom:2px solid #2166ac;padding-bottom:3px;margin-top:2.4em}"
           ".q{background:#eef4fb;padding:8px 12px;border-radius:6px;font-weight:600}"
           ".hyp{white-space:pre-wrap;background:#fafafa;border:1px solid #ddd;border-radius:6px;padding:10px;margin:8px 0}"
           ".lab{font-weight:700;color:#2166ac}.score{background:#fff8e1;border:1px solid #e0c060;padding:8px 12px;"
           "border-radius:6px;margin:6px 0}")
    body = ["<h1>Socratic Council &mdash; blinded hypothesis evaluation</h1>",
            "<p>For each question you are shown two candidate hypotheses (<b>A</b> and <b>B</b>) produced for a "
            "whole-cell <i>E.&nbsp;coli</i> simulator. Judge only the <b>methodology</b>: which is more "
            "falsifiable, better operationalized onto measurable quantities, better at discriminating rival "
            "explanations, and more feasible to run? Do <b>not</b> reward a hypothesis for being (possibly) "
            "biologically correct &mdash; a well-formed but wrong hypothesis should still score well. Record your "
            "choice on the scoresheet.</p>"]
    for pid, cid, q, A, B in pairs:
        body.append(f"<h2>{pid}</h2><div class='q'>{html.escape(q)}</div>")
        body.append(f"<div class='hyp'><span class='lab'>Hypothesis A</span>\n{html.escape(_brief(A))}</div>")
        body.append(f"<div class='hyp'><span class='lab'>Hypothesis B</span>\n{html.escape(_brief(B))}</div>")
        body.append(f"<div class='score'>{pid}: sounder hypothesis = &#9744; A &nbsp; &#9744; B &nbsp; "
                    "&#9744; tie &nbsp;&nbsp;|&nbsp;&nbsp; rigor A (1&ndash;5) ____ &nbsp; rigor B (1&ndash;5) ____</div>")
    (outdir / "packet.html").write_text(f"<!doctype html><meta charset=utf-8><style>{css}</style>"
                                        + "".join(body), encoding="utf-8")

    # --- key + scoresheet + protocol ---
    with (outdir / "key.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["pair_id", "case", "A_config", "B_config"]); w.writeheader()
        w.writerows(key_rows)
    with (outdir / "scoresheet_template.csv").open("w", newline="") as f:
        w = csv.writer(f); w.writerow(["pair_id", "grader", "choice(A/B/tie)", "rigor_A(1-5)", "rigor_B(1-5)", "notes"])
        for pid, cid, *_ in pairs:
            w.writerow([pid, "", "", "", "", ""])
    (outdir / "PROTOCOL.md").write_text(
        "# Human evaluation protocol\n\n"
        "**Task.** Open `packet.html` in a browser. For each pair (P01, P02, ...) two hypotheses (A, B) are shown "
        "for the same question. Decide which is **methodologically sounder** (falsifiability, operationalization "
        "onto measurable quantities, rival discrimination, feasibility). Judge the method, not the biology.\n\n"
        "**Recording.** Fill one row per pair in a copy of `scoresheet_template.csv`: your choice (A / B / tie) "
        "and a 1--5 rigor rating for each. 2--3 independent graders, each scoring all pairs blind to the others.\n\n"
        "**Blinding.** You are not told which hypothesis came from which system; A/B order is randomized per pair. "
        "The unblinding key (`key.csv`) is held separately and only used after scoring.\n\n"
        "**Analysis (done for you).** We compute the rate at which graders prefer the full-Council hypothesis and "
        "compare it with the LLM auditor's ranking (inter-rater agreement), plus rigor-rating agreement.\n",
        encoding="utf-8")
    print(f"wrote {len(pairs)} blinded pairs -> {outdir}/packet.html (+ key.csv, scoresheet_template.csv, PROTOCOL.md)")


if __name__ == "__main__":
    main()
