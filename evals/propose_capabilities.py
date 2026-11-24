"""K-1: candidate capability records proposed from the simulator's source, and how well they recover the hand-built ones.

The twelve hand-built records (fourteen since G-1) were written by reading source. Does that scale? The cheapest
automatic version reads the elongation models' source and proposes, as a candidate, every attribute that some
elongation models assign and others do not: a mechanism present in some modes only. It is static (no model reads the
source, so it costs nothing) and it admits nothing: a candidate is a line for a human to read, and a record joins the
registry only with its forced-fault tests.

Scored against the hand-built records that also hold in some modes but not all, the only ones a mode difference could
find (a record that holds everywhere or nowhere differs between no two modes). A record is rediscovered when one of its
markers is a candidate assigned in exactly the record's modes; precision counts candidates that are such a marker.
Exact names only: a near miss (`ppgpp` for the marker `ppgpp_conc`) is a miss, because a fuzzy match would score the
scorer's generosity.

    python evals/propose_capabilities.py    # needs the checkout (WCECOLI_DIR); writes capability_candidates.json

LIMITS. One file, three classes; a mechanism outside the elongation models (transcription, metabolism, the fit) is
invisible to it, which is where nine of the fourteen records live.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from cellarium import capability as C  # noqa: E402

ELONGATION_SOURCE = Path("models") / "ecoli" / "processes" / "polypeptide_elongation.py"
MODEL_CLASSES = {"steady_state": "SteadyStateElongationModel", "kinetic": "KineticTrnaChargingModel",
                 "coarse_kinetic": "CoarseKineticTrnaChargingModel"}
OUT = REPO / "evals" / "results" / "capability_candidates.json"


def _target_attr(t) -> list[str]:
    """`self.x = ...` and `self.process.x = ...` define x; a subscript store (`self.x[i] = ...`) does not."""
    if isinstance(t, (ast.Tuple, ast.List)):
        return [a for e in t.elts for a in _target_attr(e)]
    if isinstance(t, ast.Attribute):
        v = t.value
        if isinstance(v, ast.Name) and v.id == "self":
            return [t.attr]
        if (isinstance(v, ast.Attribute) and v.attr == "process" and isinstance(v.value, ast.Name)
                and v.value.id == "self"):
            return [t.attr]
    return []


def _assigned(cls: ast.ClassDef) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(cls):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = [node.target]
        else:
            continue
        for t in targets:
            out.update(_target_attr(t))
    return out


def candidates(source: str, model_classes: dict[str, str]) -> dict[str, tuple[str, ...]]:
    """{attribute: the modes whose model class (with its bases in the file) assigns it}, for every attribute some
    models assign and others do not."""
    classes = {n.name: n for n in ast.parse(source).body if isinstance(n, ast.ClassDef)}
    missing = sorted(set(model_classes.values()) - set(classes))
    if missing:
        raise ValueError(f"the source has no class {missing}: the scan would read nothing for that mode")

    def full(name: str, seen: tuple = ()) -> set[str]:
        c = classes.get(name)
        if c is None or name in seen:
            return set()
        out = _assigned(c)
        for b in c.bases:
            if isinstance(b, ast.Name):
                out |= full(b.id, seen + (name,))
        return out

    per_mode = {m: full(cls) for m, cls in model_classes.items()}
    modes = tuple(model_classes)
    out = {}
    for attr in sorted(set().union(*per_mode.values())):
        have = tuple(m for m in modes if attr in per_mode[m])
        if 0 < len(have) < len(modes):
            out[attr] = have
    return out


def reference_records() -> list[tuple[str, tuple, tuple]]:
    """The hand-built records a mode difference could find: those holding in some elongation models but not all."""
    return [(c.key, tuple(c.holds_in), tuple(c.markers)) for c in C.CAPABILITIES
            if 0 < len(c.holds_in) < len(C.ELONGATION_MODES)]


def score(cands: dict[str, tuple], records) -> dict:
    def found(holds_in, markers) -> bool:
        return any(m in cands and set(cands[m]) == set(holds_in) for m in markers)
    hit = sorted(k for k, h, m in records if found(h, m))
    marker_modes = {(m, frozenset(h)) for _, h, ms in records for m in ms}
    return {"n_reference": len(records), "n_rediscovered": len(hit), "rediscovered": hit,
            "missed": sorted(k for k, _, _ in records if k not in hit),
            "n_candidates": len(cands),
            "candidates_that_are_markers": sum((a, frozenset(ms)) in marker_modes for a, ms in cands.items())}


def scan(checkout: Path) -> dict:
    cands = candidates((checkout / ELONGATION_SOURCE).read_text(encoding="utf-8"), MODEL_CLASSES)
    by_modes: dict[str, list[str]] = {}
    for attr, modes in cands.items():
        by_modes.setdefault("+".join(modes), []).append(attr)
    return {"score": score(cands, reference_records()), "by_modes": by_modes}


def main() -> int:
    root = os.environ.get("WCECOLI_DIR")
    if not (root and Path(root).is_dir()):
        print("WCECOLI_DIR is not set to a model checkout; the source cannot be read, and nothing is written.",
              file=sys.stderr)
        return 2
    from cellarium import provenance
    checkout = Path(root)
    head = subprocess.run(["git", "-C", str(checkout), "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    out = {"spec": "K-1", "admitted": 0, "source": ELONGATION_SOURCE.as_posix(),
           "checkout_commit": head.stdout.strip() or None, "model_classes": MODEL_CLASSES, **scan(checkout),
           "computed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "environment": provenance.code_environment()}
    OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out["score"]), {k: len(v) for k, v in out["by_modes"].items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
