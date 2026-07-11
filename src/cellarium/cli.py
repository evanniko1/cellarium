"""CLI: run a question through Cellarium end-to-end.

The Socratic Council (upstream, docs/SOCRATIC_COUNCIL.md) first turns the raw question into a falsifiable,
operationalized hypothesis; the grounded agent then tests it. `--rounds` / `--quota` tune the Council's
debate; `--no-council` skips it and passes the raw question straight to the agent (the pre-Council behaviour).
"""

from __future__ import annotations

import argparse

from dotenv import load_dotenv

DEFAULT_Q = "Do genetically identical E. coli cells behave differently, and why?"


def main() -> None:
    load_dotenv()
    p = argparse.ArgumentParser(prog="cellarium")
    p.add_argument("question", nargs="*", help="the research question")
    p.add_argument("--rounds", type=int, default=4, help="max Socratic Council debate rounds (default 4)")
    p.add_argument("--quota", type=int, default=3,
                   help="min substantive objections before the Council may converge (default 3)")
    p.add_argument("--no-council", action="store_true", help="skip the Council; pass the raw question to the agent")
    a = p.parse_args()
    question = " ".join(a.question).strip() or DEFAULT_Q

    print(f"Q: {question}\n")

    hyp = None
    if not a.no_council:
        from .council import deliberate

        print("— Socratic Council —")
        hyp = deliberate(question, max_rounds=a.rounds, quota=a.quota,
                         ask_user=lambda q: input(f"\n? {q}\n> "))
        print("\n" + hyp.brief() + "\n")
        print("— Cellarium agent —")

    from .agent import run  # imported after load_dotenv so ANTHROPIC_API_KEY is present

    print(run(question, hypothesis=hyp))


if __name__ == "__main__":
    main()
