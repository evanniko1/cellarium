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


def main():
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
