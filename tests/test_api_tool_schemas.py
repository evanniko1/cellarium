"""Every tool schema Cellarium sends to the Messages API must be one the API accepts.

Found 2026-11-27 by the free token counter, before the first paid discovery run: `chart` carried a top-level `anyOf`
(its one-of-three run argument, ENUM-4, 2026-10-28), and the API answers any request containing it with 400
"input_schema does not support oneOf, allOf, or anyOf at the top level" (confirmed with a live one-tool call). Every
Cellwright turn sends the whole tool list, so every live Cellwright call had failed since 2026-10-28, and no offline
test could see it: the suite's clients are fakes that do not validate schemas.

The one-of-N requirement stays in Cellarium's own table (`tools.TOOLS`), which conformance and trajectory checks read;
the copy sent to the API states it in the description instead.
"""
from __future__ import annotations

import importlib
import pkgutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

COMBINATORS = ("oneOf", "anyOf", "allOf")


def _top_level_combinators(tool: dict) -> list[str]:
    return [k for k in COMBINATORS if k in (tool.get("input_schema") or {})]


def test_the_agents_tool_list_has_no_top_level_combinator():
    from cellarium import agent
    bad = {t["name"]: _top_level_combinators(t) for t in agent._cached_tools() if _top_level_combinators(t)}
    assert bad == {}


def test_charts_one_of_three_requirement_survives_in_the_description():
    from cellarium import agent, tools
    sent = next(t for t in agent._cached_tools() if t["name"] == "chart")
    assert "at least one of: result_id, results, design" in sent["description"]
    own = next(t for t in tools.TOOLS if t["name"] == "chart")
    # Cellarium's own table keeps the branches the conformance and trajectory checks read
    assert [b["required"] for b in own["input_schema"]["anyOf"]] == [["result_id"], ["results"], ["design"]]


def test_the_api_copy_does_not_alter_cellariums_own_table():
    from cellarium import agent, tools
    before = [dict(t["input_schema"]) for t in tools.TOOLS]
    agent._cached_tools()
    assert [dict(t["input_schema"]) for t in tools.TOOLS] == before


def test_every_other_tool_dict_in_the_package_is_accepted():
    """Forced tools of the Council, the gate and the other single-call modules. `tools.TOOLS` is the internal table
    and is checked through the agent's API copy above."""
    import cellarium
    found, bad = 0, {}
    for mod in pkgutil.iter_modules(cellarium.__path__):
        try:
            m = importlib.import_module(f"cellarium.{mod.name}")
        except Exception:                                   # noqa: BLE001 - an optional dependency is missing
            continue
        for name, val in vars(m).items():
            if mod.name == "tools" and name == "TOOLS":
                continue
            for d in (val if isinstance(val, list) else [val]):
                if isinstance(d, dict) and "input_schema" in d:
                    found += 1
                    if _top_level_combinators(d):
                        bad[f"{mod.name}.{name}"] = _top_level_combinators(d)
    assert found >= 3 and bad == {}
