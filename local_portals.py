"""Runs the portals that refuse data-centre IPs from a home connection in India instead.

Coal India, NTPC, BSF, BPCL and several state commissions answer 403 or refuse the
connection when asked from GitHub Actions or from Bluehost, but load fine from a normal
Indian broadband line. This script fetches them from the user's own PC and sends the result
through the same extraction and ingest path as every other scraper, so rows dedupe
against the ones the other pipelines add.

Meant to be started by a Windows scheduled task (see local_runner/install_task.ps1).
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
from page_cache_client import page_unchanged_since_last_run, forget_page_hash  # noqa: E402
from tier1_batch import fetch_page_text, MIN_USEFUL_TEXT_LENGTH  # noqa: E402

# Free Groq tiers allow few tokens per minute: send only the top of each page (newest notices
# come first) and leave a gap between portals.
EXTRACT_MAX_CHARS = 10000
EXTRACT_RETRY_CHARS = 5000
PAUSE_BETWEEN_PORTALS_SECONDS = 60

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


def main() -> int:
    if not os.environ.get("INGEST_API_KEY"):
        print("INGEST_API_KEY missing: create local_runner/.env or a .env next to this file", file=sys.stderr)
        return 1

    print(f"=== local portal run {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
    for index, (portal_name, organization, url, category) in enumerate(PORTALS):
        if index:
            time.sleep(PAUSE_BETWEEN_PORTALS_SECONDS)
        try:
            text = fetch_page_text(url)
        except Exception as e:
            print(f"[{portal_name}] failed to fetch {url}: {e}")
            continue

        print(f"[{portal_name}] fetched {len(text)} chars")
        if len(text) < MIN_USEFUL_TEXT_LENGTH:
            print(f"[{portal_name}] SKIPPED: content too short, likely blocked")
            continue

        if page_unchanged_since_last_run(portal_name, text):
            print(f"[{portal_name}] SKIPPED: page unchanged since last run")
            continue

        try:
            try:
                jobs = extract_jobs(text[:EXTRACT_MAX_CHARS], portal_name, url, raise_on_failure=True)
            except RuntimeError:
                # Usually Groq's request size limit on a link-heavy page: retry with less text.
                print(f"[{portal_name}] retrying with the first {EXTRACT_RETRY_CHARS} chars")
                time.sleep(20)
                jobs = extract_jobs(text[:EXTRACT_RETRY_CHARS], portal_name, url, raise_on_failure=True)
        except Exception as e:
            print(f"[{portal_name}] extraction failed: {e}")
            forget_page_hash(portal_name)
            continue

        for job in jobs:
            job["source_portal"] = portal_name
            job["category"] = category
            if not job.get("organization"):
                job["organization"] = organization
        try:
            post_jobs(jobs, portal_name)
        except SystemExit:
            # post_jobs() exits when the site can't be reached or refuses the batch. Keep going
            # with the other portals and read this page again next run.
            print(f"[{portal_name}] posting failed, will retry next run")
            forget_page_hash(portal_name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
