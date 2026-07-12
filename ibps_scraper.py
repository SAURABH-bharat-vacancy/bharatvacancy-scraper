"""IBPS (Institute of Banking Personnel Selection) scraper.

Fetches the public site's notice-bearing pages as raw text and hands them to
extract_jobs_ai for structured extraction — this replaces the old keyword-matching
approach (which produced fake placeholder listings whenever it couldn't find a match).
"""
import requests
import urllib3
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from extract_jobs_ai import extract_jobs
from ingest_client import post_jobs
from page_cache_client import page_unchanged_since_last_run

PORTAL_NAME = "IBPS"
PAGES = [
    "https://www.ibps.in/",
    "https://www.ibps.in/index.php/recruitment/",
    "https://www.ibps.in/index.php/careers/",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

# ibps.in's own server has an incomplete TLS certificate chain (confirmed from three
# independent networks, not a local/CA-store issue) — verification is disabled only
# for this domain, only because this scraper reads public data and never sends
# anything sensitive. User explicitly confirmed this tradeoff. Do not copy this
# pattern to any scraper that submits credentials or user data.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def fetch_page_text(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=20, verify=False)
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
            print(f"[ibps_scraper] failed to fetch {url}: {e}")
            continue

        if page_unchanged_since_last_run(f"{PORTAL_NAME} {url}", text):
            print(f"[ibps_scraper] skipped {url}: unchanged since last run")
            continue

        jobs = extract_jobs(text, PORTAL_NAME, url)
        all_jobs.extend(jobs)

    for job in all_jobs:
        job["source_portal"] = PORTAL_NAME

    post_jobs(all_jobs, PORTAL_NAME)
