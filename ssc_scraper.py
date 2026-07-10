"""SSC (Staff Selection Commission) scraper.

Note: ssc.nic.in was unreachable from local dev network during testing (connection
timeout) — this may be a transient/regional issue rather than the site being down, so
this is left in place for the GitHub Actions runner (different network) to actually
exercise. If it consistently fails there too, check ingest_log for repeated empty runs
and revisit the URL/approach.
"""
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


def fetch_page_text(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)


if __name__ == "__main__":
    all_jobs = []
    for url in PAGES:
        try:
            text = fetch_page_text(url)
        except Exception as e:
            print(f"[ssc_scraper] failed to fetch {url}: {e}")
            continue

        jobs = extract_jobs(text, PORTAL_NAME, url)
        all_jobs.extend(jobs)

    for job in all_jobs:
        job["source_portal"] = "SSC"

    post_jobs(all_jobs, "SSC")
