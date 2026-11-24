"""F-1: whether a Council falsifier can fire in the simulator its design runs on.

Three ways it cannot, each read from the capability registry or from a channel fact the Platform Map records:

  * the channel needs a capability the design's elongation model does not represent (ppGpp and RelA need
    `ppgpp_stringent_response`, which only steady-state elongation computes);
  * the design's condition is one the registry marks absent in every mode (phosphate depletion, no carbon source,
    a glucose dose), so every run returns a number that does not depend on the condition as stated;
  * the channel cannot separate two healthy designs: `division_rate` saturates at 1.0 for any fully dividing run,
    so it is reported as insensitive rather than unrealisable.

Only the falsifier's own channel and the design it names are checked; a falsifier written in free text with no
channel is out of scope and is reported as such.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cellarium import capability as C  # noqa: E402

CHANNEL_NEEDS = {"ppgpp_conc": "ppgpp_stringent_response", "rela_conc": "ppgpp_stringent_response",
                 "spot_conc": "ppgpp_stringent_response"}
CONDITION_NEEDS = {"minus_phosphate": "growth_under_phosphate_depletion",
                   "no_glucose": "growth_without_a_carbon_source",
                   "minimal_no_glucose": "growth_without_a_carbon_source",
                   "glc_2mM": "response_to_the_glucose_concentration",
                   "glc_5mM": "response_to_the_glucose_concentration",
                   "glc_20mM": "response_to_the_glucose_concentration"}
SATURATING = {"division_rate"}
LETHAL_HINTS = ("knockout", "ko:", "kd:")


def _condition(label: str | None) -> str:
    cond = (label or "").split("/", 1)[-1]
    return cond.split("|", 1)[0].split("#", 1)[0].strip()


def _mode(h: dict) -> str:
    modes = [d.get("elongation_model") for d in h.get("candidate_designs") or [] if d.get("elongation_model")]
    return modes[0] if modes else C.DEFAULT_MODE


def realisability(h: dict) -> dict:
    f = h.get("falsifier") or {}
    channel = f.get("channel")
    if not channel:
        return {"status": "no_falsifier", "reason": "no channel named"}
    mode = _mode(h)
    need = CHANNEL_NEEDS.get(channel)
    if need and mode not in C.get(need).holds_in:
        return {"status": "unrealisable", "reason": f"{channel} needs {need}, which {mode} does not represent"}
    for side in ("target", "reference"):
        cond_need = CONDITION_NEEDS.get(_condition(f.get(side)))
        if cond_need and not C.get(cond_need).holds_in:
            return {"status": "unrealisable",
                    "reason": f"{side} {f.get(side)} needs {cond_need}, absent in every elongation model"}
    if channel in SATURATING:
        lethal = any(h_ in str(f.get(s) or "").lower() for s in ("target", "reference") for h_ in LETHAL_HINTS)
        if not lethal:
            return {"status": "insensitive", "reason": f"{channel} saturates at 1.0 for any dividing run"}
    return {"status": "realisable", "reason": ""}


def summary(records: list[dict]) -> dict:
    out: dict = defaultdict(lambda: {"n": 0, "realisable": 0, "unrealisable": 0, "insensitive": 0,
                                     "no_falsifier": 0})
    for r in records:
        if "error" in r:
            continue
        s = out[r.get("config", "?")]
        s["n"] += 1
        s[realisability(r.get("hypothesis") or {})["status"]] += 1
    return {k: v for k, v in sorted(out.items())}


def main() -> int:
    import json

    from cellarium import provenance
    repo = Path(__file__).resolve().parents[1]
    recs = json.loads((repo / "evals" / "results" / "ablation_m1m2.json").read_text(encoding="utf-8"))["results"]
    rows = [{"id": r["id"], "config": r["config"], "rep": r["rep"], **realisability(r.get("hypothesis") or {})}
            for r in recs if "error" not in r]
    out = {"spec": "F-1", "source": "evals/results/ablation_m1m2.json", "by_config": summary(recs),
           "not_realisable": [x for x in rows if x["status"] != "realisable"],
           "environment": provenance.code_environment()}
    path = repo / "evals" / "results" / "falsifier_realisability.json"
    path.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out["by_config"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
