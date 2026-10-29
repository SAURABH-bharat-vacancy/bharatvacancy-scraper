"""Fills in missing detail fields on new job pages from this PC.

enrich_backfill.py runs on GitHub every few hours, but GitHub's IP addresses cannot download
the notification PDFs of several portals (BPCL, NTPC, Coal India and some state commissions),
so the rows those portals add stay thin. From a home connection in India the PDFs download
fine, so this runs the same enrichment here, newest pages first, with its own state file.

Started by the same scheduled task as local_portals.py (see run_local_portals.cmd).
Secrets come from the git-ignored .env next to this file.
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


load_env(HERE / ".env")
os.environ.setdefault("ENRICH_STATE_FILE", str(HERE / ".enrich-state-local.json"))
os.environ.setdefault("ENRICH_LIMIT", "12")  # a single free Groq key: keep each run small
os.environ.setdefault("ENRICH_SKIP_MPSC", "1")  # MPSC's own list is handled by the GitHub run

import truststore  # noqa: E402

truststore.inject_into_ssl()

import enrich_backfill  # noqa: E402

if __name__ == "__main__":
    enrich_backfill.main()
