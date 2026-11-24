"""A-1, controls first: before a new claim on a channel, reproduce a known result on that channel with the same reader.

Each control is a comparison whose direction is known from the literature and that lies outside the parameter fit: a
perturbation ParCa never saw, not a named condition (every condition reaches the fit with a doubling time, and some
with fitted transcription factors; Platform Map, Appendix J). It is read through `rigor.disconfirm`, the function a
claim on a summary channel uses, so a control that fails says the channel cannot be trusted for a new claim here.

A channel with no registered control returns `passed=None` with the reason, so a claim on it is reported as
uncontrolled rather than as controlled.
"""
from __future__ import annotations

from . import rigor

ALPHA = 0.05

CONTROLS: dict[str, dict] = {
    "growth_rate": {"target": "rrna_operon_knockout/minimal|rRNA_KO:6op",
                    "reference": "rrna_operon_knockout/minimal|rRNA_KO:2op", "expected": "down",
                    "anchor": "fewer rRNA operons, slower growth (Stevenson & Schmidt 2004)"},
    "ribosome_conc": {"target": "rrna_operon_knockout/minimal|rRNA_KO:6op",
                      "reference": "rrna_operon_knockout/minimal|rRNA_KO:2op", "expected": "down",
                      "anchor": "fewer rRNA operons, fewer ribosomes (Stevenson & Schmidt 2004)"},
    "ppgpp_conc": {"target": "ppgpp_conc/basal|ppGpp:2.0x", "reference": "ppgpp_conc/basal|ppGpp:0.2x",
                   "expected": "up", "anchor": "the clamp sets ppGpp: a manipulation check on the channel"},
}


def check(channel: str) -> dict:
    c = CONTROLS.get(channel)
    if c is None:
        return {"channel": channel, "passed": None,
                "reason": f"no control is registered for {channel}; a claim on it is uncontrolled"}
    r = rigor.disconfirm(c["target"], c["reference"], channel)
    base = {"channel": channel, "target": c["target"], "reference": c["reference"], "expected": c["expected"],
            "anchor": c["anchor"]}
    if "error" in r:
        return {**base, "passed": None, "reason": f"the control could not be read: {r['error']}"}
    eff, p = r.get("effect_pct"), r.get("welch_p")
    direction_ok = eff is not None and ((eff < 0) if c["expected"] == "down" else (eff > 0))
    passed = bool(direction_ok and p is not None and p < ALPHA)
    reason = "" if passed else ("wrong direction" if not direction_ok else f"not significant (p = {p})")
    return {**base, "observed_pct": eff, "welch_p": p, "passed": passed, "reason": reason,
            "n_target": (r.get("target") or {}).get("n_seeds"), "n_reference": (r.get("reference") or {}).get("n_seeds")}
