"""Score recorded tool trajectories (TRAJ-1). Reference-free — see src/cellarium/trajectory.py for what that
means and why there is no gold trajectory to compare against.

    python scripts/trajectory_eval.py kinetic_port/optionA_ws/traces/cellwright_discovery_v*.json
    python scripts/trajectory_eval.py --out traj.json <traces...>

Exits 1 if any trace has a CONTRACT fault (an unknown tool, a schema-invalid call, or an argument that appears
nowhere in the question or in an earlier output). Redundancy and retries are printed but never fail the run:
calling a tool twice on a hard question can be the right thing to do.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cellarium import trajectory  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("traces", nargs="+")
    p.add_argument("--out", default="")
    a = p.parse_args()

    paths = [Path(t) for t in a.traces]
    missing = [str(t) for t in paths if not t.exists()]
    if missing:
        print("no such trace: " + ", ".join(missing))
        return 2

    rep = trajectory.score_set(paths)
    print(f"{rep['n_traces']} traces, {rep['n_calls']} tool calls")
    print(f"  clean trajectories (no unknown tool, no schema fault, every handle grounded, started on a "
          f"declared first step): {rep['clean_trajectories']}/{rep['n_traces']}  pass^k = {rep['pass_k']:.2f}")
    print(f"  per-call argument-fault rate   {rep['per_call_argument_fault_rate']:.3f}")
    print(f"  per-call ungrounded rate       {rep['per_call_ungrounded_rate']:.3f}")
    rr = rep["per_call_request_refusal_rate"]
    print(f"  per-call request-refusal rate  "
          f"{f'{rr:.3f}' if rr is not None else '--'}   ({rep['request_refusal_basis']})")
    print(f"  per-call redundancy rate       {rep['per_call_redundancy_rate']:.3f}  (descriptive, never a fault)")

    bad = 0
    for s in rep["traces"]:
        print(f"\n  {s['id']}: {s['n_calls']} calls, {s['distinct_tools']} distinct tools, "
              f"first={s['first_call']}")
        if s["unknown_tools"]:
            bad += 1
            print(f"    UNKNOWN TOOL  {s['unknown_tools']}")
        for f in s["argument_faults"]:
            bad += 1
            print(f"    ARGUMENT      call {f['i']} {f['tool']}: {', '.join(f['faults'])}")
        for f in s["ungrounded"]:
            bad += 1
            print(f"    UNGROUNDED    call {f['i']} {f['tool']}: {', '.join(f['args'])} appears neither in the "
                  f"question nor in any earlier output")
        if not s["first_call_is_a_declared_first_step"]:
            bad += 1
            print(f"    ORDER         started on {s['first_call']}, while {s['declared_first_steps']} "
                  f"declare themselves the first step")
        for f in s["request_refusals"]:
            print(f"    refused       call {f['i']} {f['tool']}: reason={f['reason']} (about=request)")
        if s["redundant_calls"]:
            print(f"    repeats       {len(s['redundant_calls'])} identical (tool, arguments) calls")
        if s["retries_after_an_error"]:
            print(f"    retries       {len(s['retries_after_an_error'])} immediately after that tool errored")

    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
        print(f"\nreport: {a.out}")
    print(f"{bad} contract fault(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
