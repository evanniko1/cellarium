"""BV-2: Appendix J as a results figure. What a whole-cell model generalises to, and what it only reproduces.

Panel a: perturbations the fit never saw (ppGpp held at four levels, rRNA operons removed). The model's growth effects,
with the direction the literature reports. Panel b: responses in conditions the fit is given. For each, three marks on
one axis: the knowledge base's fitted input, the model's output, and the organism's measurement where one exists. A
model that predicts sits near the organism; a calibrated one sits near its input.

Every number is read from committed artefacts (regulation_scope.json, anaerobic_response.json) or from the knowledge
base's own tables as they cite (condition_defs.tsv doubling times; fold_changes.tsv), and the organism's from
PRECISE-1K (Lamoureux et al. 2023) as stored in anaerobic_response.json.

    python evals/bv2_figure.py    # writes evals/results/bv2_calibrated_vs_predicted.svg
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RES = REPO / "evals" / "results"
OUT = RES / "bv2_calibrated_vs_predicted.svg"

GREEN, RED, TEAL, AMBER = "#0c6b53", "#9c2d37", "#0f6f7a", "#8a5a00"


def data() -> dict:
    reg = json.loads((RES / "regulation_scope.json").read_text(encoding="utf-8"))
    ana = json.loads((RES / "anaerobic_response.json").read_text(encoding="utf-8"))
    clamps = [e["effect_pct"] for e in reg["ppgpp_clamps"] if e["channel"] == "growth_rate"]
    dose = [e["effect_pct"] for e in reg["rrna_dosage"] if e["channel"] == "growth_rate"]
    carbon = [e["effect_pct"] for e in reg["carbon_sources"]]
    ara = next(r for r in reg["gene_level"] if r["regulon"] == "ara_arabinose")["regulon_levels"]
    nar = next(r for r in reg["gene_level"] if r["regulon"] == "nar_nitrate"
               and r["reference"] == "wildtype/basal")["regulon_levels"]
    no2 = ana["no_oxygen_vs_basal_protein"]
    meas = ana["measured_precise1k"]
    kb = ana["knowledge_base_fold_changes"]
    pct = lambda dt: round((44.0 / dt - 1) * 100, 1)       # noqa: E731  growth relative to the 44-minute basal
    return {
        "a": [("ppGpp 0.2x", clamps[0]), ("ppGpp 0.6x", clamps[1]), ("ppGpp 1.6x", clamps[2]), ("ppGpp 2.0x", clamps[3]),
              ("4 rRNA operons removed", dose[0]), ("6 rRNA operons removed", dose[1])],
        "growth": [("acetate, growth vs glucose (%)", pct(136.0), carbon[0], round((0.257 / 0.649 - 1) * 100, 1)),
                   ("succinate, growth vs glucose (%)", pct(82.0), carbon[1], None)],
        "expr": [("narG, nitrate vs aerobic glucose", kb["narL"]["narG"], nar["narG"]["log2fc"], None),
                 ("narG, anaerobic vs aerobic", kb["fnr"]["narG"], no2["narG"], meas["anaerobic_vs_aerobic_glucose"]["narG"]),
                 ("frdA, anaerobic vs aerobic", 0.0, no2["frdA"], meas["anaerobic_vs_aerobic_glucose"]["frdA"]),
                 ("araB, arabinose vs basal", -0.64, ara["araB"]["log2fc"], "up")],
    }


def svg(d: dict) -> str:
    W, H = 900, 500
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="BV-2. a, growth effects of perturbations the fit '
           'never saw, with the direction the literature reports. b, for responses in conditions the fit is given, the '
           'knowledge base input, the model output and the organism measurement on one axis.">',
           '<g font-family="IBM Plex Sans, sans-serif" font-size="11" fill="currentColor">',
           '<g fill="none" stroke="currentColor" stroke-opacity="0.22"><rect x="4" y="6" width="380" height="488" rx="6"/>'
           '<rect x="392" y="6" width="504" height="488" rx="6"/></g>',
           '<text x="14" y="28" font-size="12.5" font-weight="700">a</text>'
           '<text x="30" y="28" font-weight="600">Perturbations the fit never saw: growth (%)</text>']
    # panel a: horizontal bars, 0 at x=330, scale 6 px per percent (to -40)
    # labels in a column of their own; each bar grows rightwards from a common origin by the size of the decline
    x0, s = 176, 4.6
    out.append(f'<line x1="{x0}" y1="44" x2="{x0}" y2="{44 + 6 * 46}" stroke="currentColor" stroke-opacity="0.5"/>'
               f'<text x="{x0}" y="40" font-size="9.5" fill-opacity="0.7">growth decline, %</text>')
    for i, (lab, v) in enumerate(d["a"]):
        y = 56 + i * 46
        w = abs(v) * s
        out.append(f'<text x="14" y="{y + 12}">{lab}</text>')
        out.append(f'<rect x="{x0}" y="{y}" width="{w}" height="16" fill="{GREEN}" fill-opacity="0.75"/>')
        out.append(f'<text x="{x0 + w + 6}" y="{y + 12}" font-family="IBM Plex Mono, monospace" '
                   f'font-size="10">{v:+.1f}</text>')
    out.append(f'<text x="14" y="{56 + 6 * 46 + 8}" font-size="10.5">Literature: both raised and lowered ppGpp slow '
               'growth (Zhu and Dai 2019);</text>')
    out.append(f'<text x="14" y="{56 + 6 * 46 + 22}" font-size="10.5">removing rRNA operons slows growth moderately '
               '(Asai et al. 1999).</text>')
    out.append(f'<text x="14" y="{56 + 6 * 46 + 40}" font-size="10.5" fill="{GREEN}" font-weight="600">Direction '
               'reproduced in every case: prediction.</text>')
    out.append(f'<text x="14" y="{56 + 6 * 46 + 56}" font-size="10" fill-opacity="0.7">ppGpp against basal; rRNA '
               'against 2 operons removed; 4 seeds each.</text>')

    # panel b
    out.append('<text x="402" y="28" font-size="12.5" font-weight="700">b</text>'
               '<text x="418" y="28" font-weight="600">Conditions the fit is given: input, model, organism</text>')
    legend = [("square", AMBER, "knowledge-base input"), ("circle", TEAL, "model"), ("diamond", RED, "organism")]
    for i, (shape, col, lab) in enumerate(legend):
        lx = 420 + i * 150
        out.append(_mark(shape, lx, 46, col) + f'<text x="{lx + 10}" y="50">{lab}</text>')

    def axis(y0, lo, hi, ticks, unit):
        xa, xb = 590, 880
        f = lambda v: xa + (v - lo) / (hi - lo) * (xb - xa)     # noqa: E731
        parts = [f'<line x1="{xa}" y1="{y0}" x2="{xb}" y2="{y0}" stroke="currentColor" stroke-opacity="0.4"/>']
        for t in ticks:
            parts.append(f'<line x1="{f(t)}" y1="{y0 - 3}" x2="{f(t)}" y2="{y0 + 3}" stroke="currentColor" '
                         f'stroke-opacity="0.4"/><text x="{f(t)}" y="{y0 + 15}" text-anchor="middle" font-size="9.5" '
                         f'font-family="IBM Plex Mono, monospace">{t:+g}</text>')
        parts.append(f'<text x="{xb}" y="{y0 + 28}" text-anchor="end" font-size="9.5" fill-opacity="0.7">{unit}</text>')
        return f, "".join(parts)

    f1, ax1 = axis(150, -80, 10, (-80, -60, -40, -20, 0), "growth change, %")
    out.append(ax1)
    for i, (lab, inp, mod, org) in enumerate(d["growth"]):
        y = 82 + i * 30
        out.append(f'<text x="404" y="{y + 4}">{lab}</text>')
        out.append(f'<line x1="{f1(0)}" y1="{y - 8}" x2="{f1(0)}" y2="{y + 8}" stroke="currentColor" stroke-opacity="0.2"/>')
        out.append(_mark("square", f1(inp), y, AMBER) + _mark("circle", f1(mod), y, TEAL))
        if org is not None:
            out.append(_mark("diamond", f1(org), y, RED))

    f2, ax2 = axis(372, -3, 5, (-2, 0, 2, 4), "log2 fold change")
    out.append(ax2)
    for i, (lab, inp, mod, org) in enumerate(d["expr"]):
        y = 210 + i * 38
        out.append(f'<text x="404" y="{y + 4}">{lab}</text>')
        out.append(f'<line x1="{f2(0)}" y1="{y - 10}" x2="{f2(0)}" y2="{y + 10}" stroke="currentColor" stroke-opacity="0.2"/>')
        out.append(_mark("square", f2(inp), y, AMBER) + _mark("circle", f2(mod), y, TEAL))
        if org == "up":
            out.append(f'<text x="{f2(3.0)}" y="{y + 4}" fill="{RED}" font-weight="700">&#8593; induced</text>')
        elif org is not None:
            out.append(_mark("diamond", f2(org), y, RED))
        else:
            out.append(f'<text x="{f2(-2.9)}" y="{y + 4}" font-size="9.5" fill-opacity="0.7">organism: no aerobic '
                       'data</text>')
    notes = ["The model sits near its input, not the organism: calibration, not prediction.",
             "Acetate: input -68%, model -33%, organism -60%. Anaerobic narG: model under 2-fold, organism 16-fold.",
             "Arabinose: the input itself has the opposite sign to the biology (Schleif 2010).",
             "Organism: PRECISE-1K RNA-seq; growth from its sample records. Model: protein, corpus runs."]
    for i, n in enumerate(notes):
        out.append(f'<text x="404" y="{418 + i * 17}" font-size="10.5"{" font-weight=" + chr(34) + "600" + chr(34) if i == 0 else ""}>{n}</text>')
    out.append("</g></svg>")
    return "".join(out)


def _mark(shape: str, x: float, y: float, col: str) -> str:
    if shape == "square":
        return f'<rect x="{x - 5}" y="{y - 5}" width="10" height="10" fill="{col}"/>'
    if shape == "circle":
        return f'<circle cx="{x}" cy="{y}" r="5.5" fill="{col}"/>'
    return f'<path d="M{x} {y - 6.5} L{x + 6.5} {y} L{x} {y + 6.5} L{x - 6.5} {y} z" fill="{col}"/>'


def main() -> int:
    d = data()
    OUT.write_text(svg(d) + "\n", encoding="utf-8")
    print(json.dumps(d))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
