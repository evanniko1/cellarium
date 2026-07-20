"""Record the demo's two direct-mode investigations as GENUINE live Cellwright runs — replacing the curated
reconstructions (s_rrna_clash, s_nitrate_control) with real agent transcripts, in place, so the ?demo=1 reel picks
them up automatically (same sids/titles).

This is the same seam the server uses: build a one-message history, run `agent.converse()` (which mutates it in
place with the real tool_use / tool_result / text turns), then persist via SessionStore. Nothing here is faked — the
tools read the real corpus; the literature-review skill fetches real papers.

REQUIREMENTS (why this can't run until you wire them — I don't handle API keys):
  1. ANTHROPIC_API_KEY   — put it in a repo-root .env (load_dotenv reads it) or export it. REQUIRED.
  2. Docker up + the wcEcoli image — the nitrate run's top_movers reads raw simOut through it (auto-set below).
  3. Web reachable — the literature-review step fetches Levin 2017 / Condon 1993 via the allow-listed web_get.

USAGE:
  # one command once the key is set:
  .venv/Scripts/python.exe scripts/record_demo_sessions.py            # both jobs -> data/sessions.db (review first)
  .venv/Scripts/python.exe scripts/record_demo_sessions.py --only nitrate      # just one
  .venv/Scripts/python.exe scripts/record_demo_sessions.py --seed             # after review: also write the seed DB
  #   --model claude-opus-4-8   for max-quality transcripts (default is the agent's own choice)

The runs are non-deterministic — review the transcripts (open them in the app, or re-run this) before --seed +
committing. If a run doesn't surface the clash / lit review cleanly, nudge the PROMPTS below and re-run.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("CELLARIUM_MANIFEST", "data/manifest/vmnik-compact.parquet")
os.environ.setdefault("WCECOLI_DOCKER", "wcecoli-sim:latest")   # nitrate top_movers needs the raw reader
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "apps"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")      # ANTHROPIC_API_KEY

# Prompts crafted to steer each direct-mode investigation toward the report's arc. The agent still does the work
# with its real tools; these just frame the question the way the demo needs.
JOBS = {
    "clash": {
        "sid": "s_rrna_clash",
        "title": "Delete rRNA operons: the numbers-vs-efficiency clash",
        "prompt": (
            "Delete the ribosomal-RNA operons one dose at a time — the rrna_operon_knockout designs on minimal "
            "(2, 4, and 6 of the 7 operons removed). Using disconfirm, track ribosome_conc, growth_rate, ppgpp_conc "
            "and rna_mass across the series (6op vs 2op, and note the 4op midpoint), and plot the dose-response with "
            "the chart tool. Then check the mechanism: does the model up-regulate the REMAINING operons to "
            "compensate? Compute per-operon rRNA output as rna_mass divided by the operons still present (5, 3, 1) "
            "and see whether it rises, and whether ppGpp stays flat. Finally, hold this NUMBERS-axis result against "
            "Scott's second growth law — where impairing ribosome EFFICIENCY (chloramphenicol) makes a cell "
            "over-build ribosomes. Then derive the experiment the clash implies — cut the numbers AND impair "
            "efficiency with a translation-inhibiting antibiotic — and run a FOCUSED literature review (use_skill "
            "literature-review, then only a FEW targeted web_get searches) on two questions: (1) has reducing rRNA "
            "operon number been shown to change a cell's sensitivity to ribosome-targeting antibiotics, and does that "
            "phenomenon have a name? (2) has it ever been reproduced in a whole-cell computational model? Then STOP "
            "searching and write a synthesis: the numbers-vs-efficiency clash, the compensation (with its citation), "
            "what the literature calls the synergy (with a citation + DOI), the computational gap, and what it would "
            "take to close it (a colony-scale simulator)."),
    },
    "nitrate": {
        "sid": "s_nitrate_control",
        "title": "Does nitrate switch on the nitrate-reductase genes? (reference-controlled)",
        "prompt": (
            "Does nitrate switch on the nitrate-reductase (nar) genes? Run top_movers for condition/plus_nitrate vs "
            "wildtype/basal at the protein level. Then be skeptical: the plus_nitrate condition also REMOVES OXYGEN, "
            "and anaerobiosis alone drives many of the same genes — so re-run top_movers for condition/plus_nitrate "
            "vs the anaerobic control condition/no_oxygen to isolate the nitrate-specific effect. In the controlled "
            "comparison report BOTH directions — the genes INDUCED and the genes REPRESSED by nitrate (the up and "
            "down movers) — since the NarL hierarchy has both arms. Conclude whether narGHJI is genuinely "
            "nitrate-induced or a confound of the anaerobic shift, and what the full nitrate-specific signature is "
            "(induced respiratory chain + repressed fermentation), with a citation for the mechanism."),
    },
}


def record(job: dict, model: str | None, write_seed: bool) -> None:
    from sessions import DB, SEED, SessionStore

    from cellarium import agent

    print(f"\n=== recording {job['sid']} — {job['title']} ===")
    messages = [{"role": "user", "content": agent.first_user_content(job["prompt"])}]

    def on_tool(name, inp, out):
        print(f"  · tool {name}({', '.join(f'{k}={v}' for k, v in list((inp or {}).items())[:3])})")

    answer = agent.converse(messages, model=model, on_tool=on_tool, verbose=True, max_turns=24)
    print(f"  → {len(messages)} messages; answer {len(answer)} chars")

    sess = {"messages": messages, "model": model or "(agent-default)", "used_council": False, "title": job["title"]}
    SessionStore(DB).put(job["sid"], sess)
    print(f"  saved to {DB}")
    if write_seed:
        SessionStore(SEED).put(job["sid"], sess)
        print(f"  saved to {SEED} (committed seed)")


def main() -> int:
    ap = argparse.ArgumentParser(description="Record the demo's two direct-mode sessions as genuine live runs.")
    ap.add_argument("--only", choices=sorted(JOBS), help="record just one job")
    ap.add_argument("--model", default=os.environ.get("CELLARIUM_MODEL", "claude-opus-4-8"),
                    help="model id (default: claude-opus-4-8 — best convergence for the demo transcript)")
    ap.add_argument("--seed", action="store_true", help="also write data/sessions.seed.db (do this AFTER reviewing)")
    a = ap.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. Put it in a repo-root .env (ANTHROPIC_API_KEY=…) or export it, then "
              "re-run. This script does not handle keys.", file=sys.stderr)
        return 2

    for key in ([a.only] if a.only else list(JOBS)):
        record(JOBS[key], a.model, a.seed)
    print("\nDone. Review the transcripts in the app (Investigations), then re-run with --seed to commit-ready the "
          "seed DB, and `git add data/sessions.seed.db && git commit`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
