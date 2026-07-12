"""Rewrite a distilled manifest parquet so simout_path is repo-RELATIVE (portable), not an absolute machine path.

The manifest embedded absolute paths like C:\\dev\\...\\runs\\cellarium\\<variant>\\<seed>, which leak the local
directory layout into the public HF dataset. This maps that column through manifest._portable_runpath in place.
Idempotent (already-relative paths are unchanged). After running, re-commit the parquet and re-upload it to HF.

    python scripts/sanitize_manifest_paths.py data/manifest/vmnik-compact.parquet
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pyarrow as pa
import pyarrow.parquet as pq

from cellarium.manifest import _portable_runpath


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "data/manifest/vmnik-compact.parquet")
    t = pq.read_table(path)
    if "simout_path" not in t.schema.names:
        print("no simout_path column — nothing to do")
        return 0
    col = t.column("simout_path").to_pylist()
    new = [(_portable_runpath(x) if x else x) for x in col]
    changed = sum(1 for a, b in zip(col, new) if a != b)
    i = t.schema.get_field_index("simout_path")
    t2 = t.set_column(i, "simout_path", pa.array(new, type=t.schema.field("simout_path").type))
    pq.write_table(t2, path)
    print(f"rewrote {changed}/{len(col)} paths -> repo-relative; wrote {path}")
    print("sample:", new[0] if new else "(empty)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
