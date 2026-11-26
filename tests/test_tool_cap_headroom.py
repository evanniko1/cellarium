"""The registry reaches Cellwright whole. `model_capabilities` is the one tool whose output must never be cut: each
record carries its refusal verbatim, and an agent that saw 1 of 6 limits (v5, 2026-10-27) answered as though the
other five did not exist. The cap was raised twice after a record pushed the output to its edge (G-1: 20,184 of
24,000; BV-G2 and BV-AN: 23,903 of 24,000; BV-OF: 26,728 against 32,000; BV-EL: 28,905 against 36,000; CRIT: 34,215 against 40,000, each past this margin). This keeps a margin,
so the next record raises it deliberately."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cellarium import agent, tools  # noqa: E402


def test_the_registry_fits_its_cap_with_a_fifth_to_spare():
    size = len(json.dumps(tools.dispatch("model_capabilities", {})))
    cap = agent._TOOL_CAPS["model_capabilities"]
    assert size <= 0.8 * cap, f"model_capabilities is {size} characters against a cap of {cap}: raise the cap"
