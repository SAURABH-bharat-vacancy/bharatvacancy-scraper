"""UPSC (Union Public Service Commission) scraper.

Covers civil services exams as well as NDA/CDS (defence). The AI extraction
categorizes each individual notice rather than the whole portal, so a mix of
"General" and "Defence" listings from this one source is expected and correct.
"""
import requests
from bs4 import BeautifulSoup
from extract_jobs_ai import extract_jobs
from ingest_client import post_jobs

PORTAL_NAME = "UPSC"
PAGES = [
    "https://www.upsc.gov.in",
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
            print(f"[upsc_scraper] failed to fetch {url}: {e}")
            continue

        print(f"[upsc_scraper] fetched {len(text)} chars from {url}; preview: {text[:300]!r}")
        jobs = extract_jobs(text, PORTAL_NAME, url)
        all_jobs.extend(jobs)

    for job in all_jobs:
        job["source_portal"] = PORTAL_NAME

    post_jobs(all_jobs, PORTAL_NAME)
