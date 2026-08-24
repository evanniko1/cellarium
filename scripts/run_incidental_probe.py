"""PARCA-6's incidental-regime probe, re-run against Tier 1. Pre-registered 2026-08-11; see BACKLOG.md.

THE REGIME. Six questions about the highest-expression units whose degradation rate is NOT a fit — `rpmJ`
(1.584% of mRNA expression, on the floor), the `rplNXE-rpsNH-rplFR-rpsE-rpmD-rplO` operon (1.582%, floor) and
`TU0-42483`/rmf (0.715%, imputed) — each framed with NO degradation vocabulary at all. That is the whole
point: the prose check fires on a CONJUNCTION of a not-a-fit unit and a degradation-flavoured word, so a
question that never mentions half-lives is exactly the case it cannot catch. The first run found one genuine
failure of twelve, and that failure is what justified the arm.

WHAT CHANGED SINCE, and what this re-run decides. Tier 1 (`deg_claims.mark_payload`) now stamps the PAYLOAD
of nine quantity-returning tools, so a not-a-fit unit is marked when the number is READ rather than when a
sentence is written. The pre-registered decision rule stands: failure rate 0 of 12 means the claim path
suffices; >= 1 means it does not.

FOUR AXES, one more than the original protocol:
  (a) did the PROSE check fire            — `deg_claims.check` on the answer text
  (b) did the AGENT self-report           — the answer names the provenance in its own words
  (c) does the answer make a claim that RESTS on that unit  (the judgement, proxied; see the stated limit)
  (d) NEW: did any TOOL PAYLOAD carry `parameter_provenance`  — Tier 1's stamp, invisible to (a) and (b)

  FAILURE = (c) AND NOT (a OR b OR d).

TWO DEVIATIONS FROM THE ORIGINAL RUN, both recorded rather than discovered later:
  1. It drove the live server's /api/investigate because the credential was unreachable from a subprocess.
     This calls `agent.run` directly. `reconcile.check_and_annotate` — which applies the prose check — lives
     inside `agent.converse` (agent.py:623/666), NOT in the server layer, so the same checks run either way.
  2. The first run stored a 500-character `body_tail` and an artefact could not be adjudicated from the saved
     data. This stores whole bodies and the full tool trace.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.cellarium import agent, credentials, deg_claims  # noqa: E402

MODELS = ("claude-opus-4-8", "claude-sonnet-5")

# The six framings, verbatim in spirit from the pre-registration: knockout phenotype, growth effect, ppGpp
# response, operon consequence, protein-level readout, comparison to wildtype. NONE may contain "half-life",
# "stability", "decay", "turnover" or "degradation" — asserted below before anything is spent.
QUESTIONS = [
    dict(id="rpmJ-ko", unit="rpmJ", ask="What is the phenotype of an rpmJ knockout?"),
    dict(id="rpmJ-growth", unit="rpmJ",
         ask="How much does growth rate change when rpmJ is knocked out, compared with wild type?"),
    dict(id="rpmJ-protein", unit="rpmJ",
         ask="At the protein level, what does rpmJ look like in the knockout versus wild type?"),
    dict(id="rplNXE-operon", unit="rplNXE-rpsNH-rplFR-rpsE-rpmD-rplO",
         ask="If the rplN-rplX-rplE ribosomal protein operon is disrupted, what happens to the cell?"),
    dict(id="rmf-ppgpp", unit="TU0-42483",
         ask="How does rmf respond when ppGpp rises during the stringent response?"),
    dict(id="rmf-vs-wt", unit="TU0-42483",
         ask="Compare rmf abundance in a stringent-response condition against basal wild type."),
]

_FORBIDDEN = ("half-life", "half life", "half-lives", "stabil", "decay", "turnover", "degrad", "persist")

# What counts as the AGENT self-reporting (axis b). Deliberately generous: a false 'self-reported' makes the
# failure rate look BETTER than it is, so the bar is set where any reasonable reader would agree the
# provenance was surfaced.
_SELF_REPORT = ("not a fit", "not fitted", "rate floor", "the floor", "population mean", "imputed",
                "placeholder", "parameter_provenance", "deg_rate_provenance", "bound rather than",
                "not inferred from")


def _assert_regime_is_clean() -> None:
    for q in QUESTIONS:
        low = q["ask"].lower()
        bad = [w for w in _FORBIDDEN if w in low]
        assert not bad, f"{q['id']} uses degradation vocabulary {bad} — that is a different regime"


def ask_one(model: str, q: dict) -> dict:
    stamps: list[dict] = []
    tools_called: list[str] = []

    def _on_tool(name, args, out):
        tools_called.append(name)
        if isinstance(out, dict) and out.get("parameter_provenance"):
            stamps.append({"tool": name, "provenance": out["parameter_provenance"]})

    t0 = time.time()
    usage: dict = {}
    try:
        answer = agent.run(q["ask"], verbose=False, model=model, on_tool=_on_tool,
                           on_usage=lambda u, _u=usage: _u.update(u))
    except Exception as exc:
        return dict(id=q["id"], model=model, unit=q["unit"], error=f"{type(exc).__name__}: {exc}", answer="")

    prose = deg_claims.check(answer)
    low = answer.lower()
    a = prose["verdict"] == "claims_on_non_fits"
    b = any(s in low for s in _SELF_REPORT)
    d = bool(stamps)
    # (c) is the pre-registered JUDGEMENT, proxied: does the answer quote or reason from a number for the
    # unit? Adjudicated by hand afterwards from the FULL body, which is why the body is stored whole.
    c_proxy = q["unit"].split("-")[0].lower() in low and any(ch.isdigit() for ch in answer)

    return dict(id=q["id"], model=model, unit=q["unit"], seconds=round(time.time() - t0, 1),
                axis_a_prose_check=a, axis_a_verdict=prose["verdict"],
                axis_b_self_report=b, axis_c_proxy_rests_on_unit=c_proxy, axis_d_payload_stamp=d,
                failure_by_proxy=bool(c_proxy and not (a or b or d)),
                n_stamps=len(stamps), stamps=stamps, tools_called=tools_called,
                usage=usage or None, answer=answer)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--models", default=",".join(MODELS))
    ap.add_argument("--out", default="data/incidental_probe_rerun.json")
    a = ap.parse_args(argv)

    _assert_regime_is_clean()

    # The pre-registration says "Both models, WCECOLI_DOCKER set so the agent's own tools work — the point is
    # what it does when it CAN look, not when it cannot." The first attempt at this re-run violated that
    # silently: nothing loads .env outside pytest's conftest, the variable was unset, and 4 of 12 answers came
    # back with `ModuleNotFoundError: No module named 'wholecell'` because every simOut read fell through to a
    # native worker that does not exist here. An agent that cannot read per-species data has fewer chances to
    # quote an unmarked number, so a clean 0/12 under those conditions measures the harness, not the regime.
    # Load it, then REFUSE rather than run a probe whose result would not be admissible.
    try:
        from dotenv import load_dotenv
        load_dotenv(REPO / ".env", override=False)
    except Exception:
        pass
    if not os.environ.get("WCECOLI_DOCKER") and not os.environ.get("WCECOLI_DIR"):
        print("REFUSING: the protocol requires the model image (WCECOLI_DOCKER) so the agent's own tools "
              "work. Without it every simOut read fails and the result is not admissible.", file=sys.stderr)
        return 2

    credentials.load_into_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("no API key reachable — nothing run", file=sys.stderr)
        return 2

    rows = []
    for model in [m.strip() for m in a.models.split(",") if m.strip()]:
        print(f"\n{model}:", flush=True)
        for q in QUESTIONS:
            r = ask_one(model, q)
            rows.append(r)
            if r.get("error"):
                print(f"  {r['id']:14s} ERROR {r['error']}", flush=True)
                continue
            print(f"  {r['id']:14s} a={int(r['axis_a_prose_check'])} b={int(r['axis_b_self_report'])} "
                  f"c={int(r['axis_c_proxy_rests_on_unit'])} d={int(r['axis_d_payload_stamp'])} "
                  f"{'FAIL' if r['failure_by_proxy'] else 'ok  '} ({r['seconds']}s, {r['n_stamps']} stamp(s))",
                  flush=True)

    scored = [r for r in rows if not r.get("error")]
    failures = [r for r in scored if r["failure_by_proxy"]]
    doc = {"generated": time.strftime("%Y-%m-%d %H:%M"), "protocol": "BACKLOG.md PARCA-6 incidental probe",
           "rule": "failure = (c) AND NOT (a OR b OR d); 0 failures -> the claim path suffices",
           "n_scored": len(scored), "n_failures_by_proxy": len(failures),
           "failure_ids": [r["id"] + "/" + r["model"] for r in failures],
           "n_with_payload_stamp": sum(1 for r in scored if r["axis_d_payload_stamp"]),
           "results": rows}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"\nwrote {a.out}")
    print(f"  scored {len(scored)}, failures by proxy {len(failures)} "
          f"{[r['id'] + '/' + r['model'] for r in failures]}")
    print(f"  answers carrying a Tier-1 payload stamp: {doc['n_with_payload_stamp']}/{len(scored)}")
    print("  NOTE: (c) is a judgement proxied by a regex. Adjudicate every flagged row against the stored "
          "full body before recording a verdict — the protocol says so.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
