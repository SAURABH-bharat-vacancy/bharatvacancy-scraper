"""UPSC (Union Public Service Commission) direct-recruitment scraper.

upsc.gov.in used to serve a "please enable JavaScript" anti-bot stub
regardless of fetch origin (confirmed from GitHub Actions and Bluehost alike)
— a genuine JS-challenge problem, not an IP block. As of this rewrite the
site has been relaunched (Drupal-based, "New Online Application Portal
Launched" notice) and now serves real server-rendered HTML, so that workaround
is no longer needed.

Better still, UPSC publishes a dedicated RSS feed for direct-recruitment
notices (as opposed to exam notices like Civil Services, which aren't
relevant to a job board): https://upsc.gov.in/rss.php — "Recruitment
Advertisements of UPSC". This gives a clean title/link/date directly, no AI
extraction needed (same reasoning as ssc_scraper.py's JSON API: a structured
official feed beats HTML+AI whenever one exists). The feed is low-volume
(UPSC direct recruitment is infrequent) and occasionally repeats an item as a
second, mostly-empty <item> block — those are filtered out below by requiring
a non-empty guid and link.
"""
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests
from ingest_client import post_jobs

PORTAL_NAME = "UPSC"
ORGANIZATION = "Union Public Service Commission"
RSS_URL = "https://upsc.gov.in/rss.php"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


def fetch_items() -> list[dict]:
    resp = requests.get(RSS_URL, headers=HEADERS, timeout=25)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    return [
        {
            "guid": (item.findtext("guid") or "").strip(),
            "link": (item.findtext("link") or "").strip(),
            "pubDate": (item.findtext("pubDate") or "").strip(),
        }
        for item in root.iter("item")
    ]


def to_job(item: dict) -> dict | None:
    guid = re.sub(r"\s+", " ", item["guid"]).strip()
    link = item["link"]
    if not guid or not link:
        return None

    posted_date = None
    if item["pubDate"]:
        try:
            posted_date = parsedate_to_datetime(item["pubDate"]).astimezone(timezone.utc).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            pass

    return {
        "title": f"UPSC {guid}",
        "organization": ORGANIZATION,
        "source_portal": PORTAL_NAME,
        "category": "General",
        "location": "All India",
        "employment_type": "Permanent",
        "source_url": link,
        "pdf_url": link,
        "description": f"UPSC direct recruitment {guid}. See the official advertisement PDF for post-wise vacancy details, eligibility and how to apply.",
        "posted_date": posted_date,
    }


if __name__ == "__main__":
    try:
        items = fetch_items()
    except Exception as e:
        print(f"[upsc_scraper] failed to fetch RSS feed: {e}")
        items = []

    seen_guids = set()
    jobs = []
    for item in items:
        job = to_job(item)
        if job is None or job["title"] in seen_guids:
            continue
        seen_guids.add(job["title"])
        jobs.append(job)

    post_jobs(jobs, PORTAL_NAME)
