"""Runs the portals that refuse data-centre IPs from a home connection in India instead.

Coal India, NTPC, BSF, BPCL and several state commissions answer 403 or refuse the
connection when asked from GitHub Actions or from Bluehost, but load fine from a normal
Indian broadband line. This script fetches them from the user's own PC and sends the result
through the same ingest path as every other scraper, so rows dedupe against the ones the
other pipelines add.

It needs very little AI quota:
  * the text of each page is remembered, and only lines that were not on the page last time
    are looked at, so an unchanged page costs nothing and a changed one costs a few lines;
  * those lines go to the AI extractor when a provider answers, and otherwise to the
    rule-based reader in rule_extract.py, so the run still adds rows with no API keys at all.

Meant to be started by a Windows scheduled task (see install_local_task.ps1).
Secrets are read from a git-ignored .env file next to this script, never from the repo.

truststore makes Python use the Windows certificate store. Several of these sites send an
incomplete certificate chain, which Python's own bundle rejects but Windows (like a browser)
completes by itself, so certificate verification stays ON.
"""
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # so the sibling scraper modules import however the script is started


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
os.environ.setdefault("ANTHROPIC_API_KEY", "unset")  # the client object needs a value; that tier is skipped when it fails

import truststore  # noqa: E402

truststore.inject_into_ssl()

from extract_jobs_ai import extract_jobs  # noqa: E402
from ingest_client import post_jobs  # noqa: E402
from rule_extract import rule_based_jobs  # noqa: E402
from tier1_batch import fetch_page_text, MIN_USEFUL_TEXT_LENGTH  # noqa: E402

# Free Groq tiers allow few tokens per minute, so the AI only gets the new lines, capped.
EXTRACT_MAX_CHARS = 10000
PAUSE_AFTER_AI_CALL_SECONDS = 45
STATE_DIR = HERE / ".page-state"

# (portal_name, organization, url, category). Names match the other pipelines so a notice
# found by two of them is stored once.
PORTALS = [
    ("Coal India", "Coal India Limited", "https://www.coalindia.in/career-cil/jobs-coal-india/", "PSU"),
    ("NTPC", "NTPC Limited", "https://careers.ntpc.co.in/recruitment/", "PSU"),
    ("BSF", "Border Security Force", "https://rectt.bsf.gov.in/", "Police"),
    ("BPCL", "Bharat Petroleum Corporation Limited", "https://www.bharatpetroleum.in/careers/job-openings", "PSU"),
    ("BPSC", "Bihar Public Service Commission", "https://bpsc.bihar.gov.in/", "State"),
    ("Punjab PSC", "Punjab Public Service Commission", "https://ppsc.gov.in/", "State"),
    ("JKPSC", "Jammu and Kashmir Public Service Commission", "https://jkpsc.nic.in/", "State"),
    ("Assam PSC", "Assam Public Service Commission", "https://apsc.nic.in/", "State"),
    # Added 2026-10-28: loaded fine from home while the Bluehost job stayed silent for weeks.
    # (EPFO moved to epfo.gov.in and renders its list by script, so it runs in headless_portals.py.)
    ("ONGC", "Oil and Natural Gas Corporation", "https://www.ongcindia.com/web/eng/career/recruitment-notice", "PSU"),
    ("Rajasthan PSC", "Rajasthan Public Service Commission", "https://rpsc.rajasthan.gov.in/", "State"),
]


def _state_file(portal_name: str) -> Path:
    safe = "".join(c if c.isalnum() else "-" for c in portal_name.lower())
    return STATE_DIR / f"{safe}.txt"


def load_seen_lines(portal_name: str) -> set[str] | None:
    path = _state_file(portal_name)
    if not path.exists():
        return None
    return set(path.read_text(encoding="utf-8").splitlines())


def save_seen_lines(portal_name: str, lines: set[str]) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    _state_file(portal_name).write_text("\n".join(sorted(lines)), encoding="utf-8")


def pick_new_lines(lines: list[str], seen: set[str] | None) -> list[str]:
    """Lines that were not on the page at the last successful run, in page order."""
    if seen is None:
        return lines
    return [line for line in lines if line not in seen]


def main() -> int:
    if not os.environ.get("INGEST_API_KEY"):
        print("INGEST_API_KEY missing: create a .env next to this file", file=sys.stderr)
        return 1

    print(f"=== local portal run {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
    ai_available = True  # switched off for the rest of the run once every provider has refused

    for portal_name, organization, url, category in PORTALS:
        try:
            text = fetch_page_text(url)
        except Exception as e:
            print(f"[{portal_name}] failed to fetch {url}: {e}")
            continue

        if len(text) < MIN_USEFUL_TEXT_LENGTH:
            print(f"[{portal_name}] SKIPPED: content too short ({len(text)} chars), likely blocked")
            continue

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        seen = load_seen_lines(portal_name)
        new_lines = pick_new_lines(lines, seen)
        print(f"[{portal_name}] {len(lines)} lines, {len(new_lines)} new")
        if not new_lines:
            continue

        # The AI sees as many new lines as fit; whatever does not fit stays "unseen" and is
        # picked up on a later run instead of being lost.
        chunk, used = [], 0
        for line in new_lines:
            if used + len(line) > EXTRACT_MAX_CHARS and chunk:
                break
            chunk.append(line)
            used += len(line) + 1
        chunk_text = "\n".join(chunk)

        jobs, handled_lines, method = None, chunk, "ai"
        if ai_available:
            try:
                jobs = extract_jobs(chunk_text[:EXTRACT_MAX_CHARS], portal_name, url, raise_on_failure=True)
            except RuntimeError as e:
                print(f"[{portal_name}] AI unavailable ({e}); using the rule-based reader")
                ai_available = False
        if jobs is None:
            # No AI: the rules read every new line, so nothing is left unseen.
            jobs, handled_lines, method = rule_based_jobs(new_lines, url), new_lines, "rules"

        for job in jobs:
            job["source_portal"] = portal_name
            job["category"] = category
            if not job.get("organization"):
                job["organization"] = organization
        print(f"[{portal_name}] {method}: {len(jobs)} notices found")

        try:
            post_jobs(jobs, portal_name)
        except SystemExit:
            # post_jobs() exits when the site can't be reached or refuses the batch. The lines are
            # not marked as seen, so the next run reads them again.
            print(f"[{portal_name}] posting failed, will retry next run")
            continue
        save_seen_lines(portal_name, (seen or set()) | set(handled_lines))

        if method == "ai":
            time.sleep(PAUSE_AFTER_AI_CALL_SECONDS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
