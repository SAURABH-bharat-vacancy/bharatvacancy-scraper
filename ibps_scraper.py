"""IBPS (Institute of Banking Personnel Selection) scraper.

Fetches the public site's notice-bearing pages as raw text and hands them to
extract_jobs_ai for structured extraction — this replaces the old keyword-matching
approach (which produced fake placeholder listings whenever it couldn't find a match).
"""
import requests
from bs4 import BeautifulSoup
from extract_jobs_ai import extract_jobs
from ingest_client import post_jobs

PORTAL_NAME = "IBPS"
PAGES = [
    "https://www.ibps.in/",
    "https://www.ibps.in/index.php/recruitment/",
    "https://www.ibps.in/index.php/careers/",
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
            print(f"[ibps_scraper] failed to fetch {url}: {e}")
            continue

        jobs = extract_jobs(text, PORTAL_NAME, url)
        all_jobs.extend(jobs)

    for job in all_jobs:
        job["source_portal"] = PORTAL_NAME

    post_jobs(all_jobs, PORTAL_NAME)
