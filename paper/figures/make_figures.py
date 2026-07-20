"""Generate the paper's data figures from committed result JSON (regenerable, no hidden state).

Fig 2 (the mechanism figure): (A) residual methodological defects per ablation config, both the Claude and the
cross-family GPT auditor, with 95% CIs; (B) per-case defect reduction of the full Council vs single-shot
(proposer_only), ordered — the value is largest where operationalization is hardest; (C) the two supporting
signals — binary operationalization-quality (saturated null) and mean deliberation rounds (the gradient).
Reads evals/results/ablation_summary.json. Output: paper/figures/fig2_mechanism.pdf (+ .png).
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SUM = json.loads((ROOT / "evals" / "results" / "ablation_summary.json").read_text())

CFGS = ["full", "no_skeptic", "proposer_only", "generic_judge"]
LABEL = {"full": "Full\nCouncil", "no_skeptic": "No\nskeptic", "proposer_only": "Proposer\nonly (1-shot)",
         "generic_judge": "Generic\njudge"}
CBLUE, CGREY, CRED = "#2166ac", "#b8b8b8", "#b2182b"
plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False,
                     "figure.dpi": 150})


def _mean_ci(entry, key):
    e = (entry or {}).get(key)
    if not e:
        return None, None, None
    lo, hi = e["ci95"]
    return e["mean"], e["mean"] - lo, hi - e["mean"]


def fig1_architecture():
    """Schematic: vague question -> Council (proposer<->skeptic->judge behind a quarantine wall) ->
    operationalized Hypothesis -> instrument test. The Council is the hero."""
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
    fig, ax = plt.subplots(figsize=(11, 4.3))
    ax.set_xlim(0, 100); ax.set_ylim(0, 44); ax.axis("off")

    def box(x, y, w, h, text, fc, ec="#333", fs=8.5, tc="black"):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.4,rounding_size=1.2",
                                    fc=fc, ec=ec, lw=1.2))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, color=tc, wrap=True)

    def arrow(x1, y1, x2, y2, colour="#333", style="-|>", lw=1.4, rad=0.0):
        ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style, mutation_scale=13,
                                     color=colour, lw=lw, connectionstyle=f"arc3,rad={rad}"))

    # input
    box(1, 18, 15, 8, "Vague research\nquestion\n\"do identical cells\nbehave differently?\"", "#f0f0f0", fs=8)
    arrow(16, 22, 22, 22)

    # Council container
    ax.add_patch(FancyBboxPatch((22, 6), 44, 32, boxstyle="round,pad=0.5,rounding_size=1.5",
                                fc="#eef4fb", ec=CBLUE, lw=1.6))
    ax.text(44, 40.2, "SOCRATIC COUNCIL", ha="center", fontsize=11, fontweight="bold", color=CBLUE)
    box(25, 24, 17, 9, "PROPOSER\n(maieutic / abduction)\noperationalize + falsifier\n+ rival hypotheses", "#dbe7f5", fs=7.2)
    box(46, 24, 17, 9, "SKEPTIC\n(Socratic ignorance)\ntyped objections;\nDuhem–Quine belt", "#f5dede", fs=7.2)
    box(35.5, 9, 17, 9, "JUDGE\n(falsifiability gate)\nfalsifiable ∧ operationalized\n∧ discriminating ∧ feasible", "#e6e6e6", fs=7.2)
    arrow(42, 28.5, 46, 28.5, CBLUE, rad=0.0); arrow(46, 26.5, 42, 26.5, CRED, rad=0.0)
    ax.text(44, 30.2, "propose", ha="center", fontsize=6.3, color=CBLUE)
    ax.text(44, 24.6, "object", ha="center", fontsize=6.3, color=CRED)
    arrow(53, 24, 47, 18.5, "#555"); arrow(37, 24, 41, 18.5, "#555")
    arrow(44, 9, 44, 5.2, "#555", rad=0.0)
    ax.text(45.5, 6.6, "converge on falsifiability\n(not agreement / Elo)", ha="left", fontsize=6.3, color="#333")

    # quarantine wall on the left edge of the Council
    ax.plot([21.2, 21.2], [6, 38], color="#888", lw=2.2, ls=(0, (4, 2)))
    ax.text(20.6, 34, "information quarantine", rotation=90, va="top", ha="center", fontsize=7, color="#555")
    ax.text(20.6, 12, "capabilities in · readings/answer-key out", rotation=90, va="bottom", ha="center",
            fontsize=6, color="#888")

    # output Hypothesis + instrument
    arrow(66, 22, 72, 22)
    box(72, 15, 15, 14, "Operationalized\nHYPOTHESIS\nH1/H0 · observable\n· executable falsifier\n· designs",
        "#e8f3e8", ec="#2e7d32", fs=7)
    arrow(79.5, 15, 79.5, 10.5, "#2e7d32", rad=0.0)
    box(72, 1.5, 15, 8, "Whole-cell\nsimulation\nfalsifier fires →\nconfirm / refute", "#f0f0f0", fs=7.2)

    # philosophy ribbon
    ax.text(44, 2.6, "discovery  →  operationalization  →  justification    (Reichenbach · Peirce · Bridgman · Popper · Platt)",
            ha="center", fontsize=6.6, color="#777", style="italic")
    fig.tight_layout()
    for ext in ("pdf", "png"):
        fig.savefig(ROOT / "paper" / "figures" / f"fig1_architecture.{ext}", bbox_inches="tight")
    print("wrote paper/figures/fig1_architecture.pdf (+ .png)")


def main():
    fig1_architecture()
    rd = SUM.get("residual_defects", {})
    cfg = SUM.get("configs", {})
    fig, (axA, axB, axC) = plt.subplots(1, 3, figsize=(11, 3.4))

    # --- A: residual defects per config, both auditors ---
    x = range(len(CFGS))
    for i, (grader, colour, dx) in enumerate([("defects_claude", CGREY, -0.16), ("defects_gpt", CBLUE, 0.16)]):
        ys, yerr = [], [[], []]
        for c in CFGS:
            m, lo, hi = _mean_ci(rd.get(c), grader)
            ys.append(m if m is not None else 0)
            yerr[0].append(lo or 0); yerr[1].append(hi or 0)
        axA.bar([xi + dx for xi in x], ys, width=0.3, color=colour,
                label=("Claude auditor" if "claude" in grader else "GPT auditor (cross-family)"))
        axA.errorbar([xi + dx for xi in x], ys, yerr=yerr, fmt="none", ecolor="#333", elinewidth=0.9, capsize=2)
    axA.set_xticks(list(x)); axA.set_xticklabels([LABEL[c] for c in CFGS], fontsize=7.5)
    axA.set_ylabel("Residual methodological defects\n(lower is better)")
    axA.set_title("A  Adversarial defect audit", loc="left", fontweight="bold")
    axA.legend(frameon=False, fontsize=7, loc="lower left")
    axA.set_ylim(0, 8)
    # significance annotations (GPT cross-family auditor, one-sided paired Wilcoxon vs full)
    po = rd.get("proposer_only", {}).get("vs_full_gpt", {})
    ns = rd.get("no_skeptic", {}).get("vs_full_gpt", {})
    lines = []
    if ns.get("wilcoxon_p_full_fewer") is not None:
        lines.append(f"full vs no-skeptic:  p={ns['wilcoxon_p_full_fewer']}")
    if po.get("wilcoxon_p_full_fewer") is not None:
        lines.append(f"full vs 1-shot:      p={po['wilcoxon_p_full_fewer']}")
    if lines:
        axA.text(0.97, 0.97, "GPT auditor (paired Wilcoxon)\n" + "\n".join(lines), transform=axA.transAxes,
                 ha="right", va="top", fontsize=6.8, color=CRED)

    # --- B: per-case full-vs-proposer_only reduction (GPT auditor) ---
    fpc = rd.get("full", {}).get("defects_gpt", {}).get("per_case", {})
    ppc = rd.get("proposer_only", {}).get("defects_gpt", {}).get("per_case", {})
    pairs = sorted(((c, ppc[c] - fpc[c]) for c in fpc if c in ppc), key=lambda t: t[1])
    axB.barh([c for c, _ in pairs], [d for _, d in pairs], color=CBLUE)
    axB.axvline(0, color="#333", lw=0.8)
    axB.set_xlabel("defects removed by full Council\n(vs 1-shot, GPT auditor)")
    axB.set_ylabel("case")
    axB.set_title("B  Largest where operationalization is hard", loc="left", fontweight="bold", fontsize=8.5)

    # --- C: the two supporting signals: binary quality (null) + rounds (gradient) ---
    q = [cfg.get(c, {}).get("quality_gpt", {}).get("mean", 0) for c in CFGS]
    r = [cfg.get(c, {}).get("mean_rounds", 0) for c in CFGS]
    axC2 = axC.twinx()
    axC.plot(range(len(CFGS)), q, "o-", color=CGREY, label="quality (0-6, GPT)")
    axC2.plot(range(len(CFGS)), r, "s--", color=CRED, label="mean rounds")
    axC.set_ylim(0, 6.4); axC.set_ylabel("operationalization quality", color=CGREY)
    axC2.set_ylabel("deliberation rounds", color=CRED)
    axC.set_xticks(range(len(CFGS))); axC.set_xticklabels([LABEL[c] for c in CFGS], fontsize=7.5)
    axC.set_title("C  Quality saturates; rounds scale", loc="left", fontweight="bold", fontsize=8.5)
    axC.spines["right"].set_visible(True); axC2.spines["top"].set_visible(False)

    fig.tight_layout()
    for ext in ("pdf", "png"):
        fig.savefig(ROOT / "paper" / "figures" / f"fig2_mechanism.{ext}", bbox_inches="tight")
    print("wrote paper/figures/fig2_mechanism.pdf (+ .png)")


if __name__ == "__main__":
    main()
