"""Replace a file atomically, surviving the moment Windows refuses the rename.

Write-to-temp-then-rename is how this project saves state that must never be half-written: the job queue, the A/B
ledger. On Windows the rename fails with "Access is denied" (WinError 5) for a moment whenever another process --
an indexer, an antivirus scan, a reader -- has the destination open. Found 2026-11-23 twice: once in the job
queue's tests, and once in the A/B ledger's, where an unattended sweep would have died of it. A brief refusal is
retried with a short, growing pause; one that outlasts the retries is raised, never swallowed.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

REPLACE_TRIES = 8


def replace(tmp: Path, dest: Path) -> None:
    for attempt in range(REPLACE_TRIES):
        try:
            os.replace(tmp, dest)
            return
        except PermissionError:
            if attempt == REPLACE_TRIES - 1:
                raise
            time.sleep(0.02 * (attempt + 1))
