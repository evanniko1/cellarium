"""Fail if a corpus read appears that nobody registered — the cheap 80% of a banned-call lint rule.

WHAT THIS IS AND IS NOT. The full version is a Semgrep/flake8 rule that makes an unregistered
`store.list_results(...)` or `read_parquet(` a BUILD ERROR at the moment it is written, with the registry as
its allowlist. That needs a generator, a sync test and a CI dependency, and it can make things worse if the
allowlist forks from the registry (see BACKLOG "TOATTEMPT — the banned-call lint rule"). This is the same
check with none of that: it calls `hygiene.registry_reconciliation()`, which already reconciles the AST
detector against the registry in both directions, and turns a mismatch into a non-zero exit.

WHY IT EXISTS AT ALL, given a test already asserts the same thing: the test runs in the suite, which takes
minutes; this runs in under a second and can sit in a pre-commit hook, so the answer arrives while the change
is still in your head. It also prints the reason, which a red test name does not.

    python scripts/check_read_sites.py           # exit 1 on any unregistered or stale site

As a git hook (optional, and deliberately not installed for you — a hook that appears without being asked for
is a hook people disable):

    printf '#!/bin/sh\\nexec python scripts/check_read_sites.py\\n' > .git/hooks/pre-commit
    chmod +x .git/hooks/pre-commit
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main() -> int:
    from cellarium import hygiene

    r = hygiene.registry_reconciliation()
    if r["ok"]:
        print(f"read sites OK — {r['n_detected']} registered "
              f"({r['n_consumer_sites']} consumer + {r['n_direct_sites']} direct)")
        return 0

    print("UNREGISTERED CORPUS READS — every read must be classified in hygiene.READ_SITE_REGISTRY or "
          "hygiene.DIRECT_READ_REGISTRY.\n")
    for site in r["unregistered"]:
        print(f"  NEW        {site}")
        print("             add an entry: is it a lookup, a purpose-shaped read, a primitive, "
              "maintenance, an aggregate, or a bespoke projection? Say which, and why.")
    for site in r["stale"]:
        print(f"  GONE       {site}")
        print("             the code moved or was deleted; remove or update the registry entry.")
    for site in r["invalid_kind"]:
        print(f"  BAD KIND   {site}")
    for site in r["missing_reason"]:
        print(f"  NO REASON  {site}  — a classification with no reason is a label, not a decision.")
    print("\nWhat this CANNOT catch: " + r["cannot_catch"])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
