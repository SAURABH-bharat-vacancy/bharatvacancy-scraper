"""SSC (Staff Selection Commission) scraper.

KNOWN ISSUE: ssc.nic.in is currently unreachable from every network tested so far
(local dev machine, GitHub Actions runners, and Anthropic's own infrastructure) —
connection timeouts and outright refusals across all three, which points to the site
blocking non-residential/non-Indian-ISP traffic rather than a transient outage. A
residential-IP proxy service would likely fix this but costs real money on an ongoing
basis, so it's deliberately not wired up yet (see project notes on profit-first
sequencing). This scraper is left in place with retries in case the block turns out to
be intermittent rather than absolute — check ingest_log for repeated empty/failed runs
to see whether that assumption holds.
"""
import time
import requests
from bs4 import BeautifulSoup
from extract_jobs_ai import extract_jobs
from ingest_client import post_jobs

PORTAL_NAME = "Staff Selection Commission"
PAGES = [
    "https://ssc.nic.in/",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


def fetch_page_text(url: str, retries: int = 2) -> str:
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            for tag in soup(["script", "style", "nav", "footer"]):
                tag.decompose()
            return soup.get_text(separator="\n", strip=True)
        except Exception as e:
            last_error = e
            if attempt < retries:
                time.sleep(5)
    raise last_error


if __name__ == "__main__":
    all_jobs = []
    for url in PAGES:
        try:
            text = fetch_page_text(url)
        except Exception as e:
            print(f"[ssc_scraper] failed to fetch {url} after retries: {e}")
            continue

        jobs = extract_jobs(text, PORTAL_NAME, url)
        all_jobs.extend(jobs)

    for job in all_jobs:
        job["source_portal"] = "SSC"

    post_jobs(all_jobs, "SSC")
