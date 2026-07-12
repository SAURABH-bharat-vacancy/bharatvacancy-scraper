"""Join Indian Army scraper (Defence category).

KNOWN ISSUE: joinindianarmy.nic.in times out from GitHub Actions runners
(confirmed) even though it's reachable from residential networks — same
network-blocking pattern as ssc.nic.in. Left in place with the same "revisit
with a proxy once there's revenue" approach as SSC; see ssc_scraper.py.

Note: navy/air force have separate portals (joinindiannavy.gov.in,
careerindianairforce.cdac.in) — not yet added, same "verify content is real
before building" approach should apply there too.
"""
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from extract_jobs_ai import extract_jobs
from ingest_client import post_jobs
from page_cache_client import page_unchanged_since_last_run

PORTAL_NAME = "Join Indian Army"
PAGES = [
    "https://joinindianarmy.nic.in/",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


def fetch_page_text(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    # Inline each link's resolved URL next to its text (e.g. "Download
    # Advertisement [https://.../notice.pdf]") before stripping to plain
    # text — get_text() alone drops href attributes entirely, so the AI
    # extraction step had no way to report a pdf_url from a listing page.
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("javascript:") or href.startswith("#"):
            continue
        resolved = urljoin(resp.url, href)
        text = a.get_text(strip=True)
        a.replace_with(f"{text} [{resolved}]" if text else f"[{resolved}]")
    return soup.get_text(separator="\n", strip=True)


if __name__ == "__main__":
    all_jobs = []
    for url in PAGES:
        try:
            text = fetch_page_text(url)
        except Exception as e:
            print(f"[army_scraper] failed to fetch {url}: {e}")
            continue

        if page_unchanged_since_last_run(PORTAL_NAME, text):
            print(f"[army_scraper] skipped {url}: unchanged since last run")
            continue

        jobs = extract_jobs(text, PORTAL_NAME, url)
        all_jobs.extend(jobs)

    for job in all_jobs:
        job["source_portal"] = PORTAL_NAME
        job["category"] = "Defence"

    post_jobs(all_jobs, PORTAL_NAME)
