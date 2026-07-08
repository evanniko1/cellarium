"""CLI: run a question through Cellarium end-to-end."""

from __future__ import annotations

import sys

from dotenv import load_dotenv

DEFAULT_Q = "Do genetically identical E. coli cells behave differently, and why?"


def main() -> None:
    load_dotenv()
    question = " ".join(sys.argv[1:]).strip() or DEFAULT_Q
    from .agent import run  # imported after load_dotenv so ANTHROPIC_API_KEY is present

    print(f"Q: {question}\n")
    print(run(question))


if __name__ == "__main__":
    main()
