"""SSC (Staff Selection Commission) scraper.

ssc.nic.in (the old domain) is unreachable from every network tested (local,
GitHub Actions, Anthropic infra, Bluehost) — a genuine, unresolved block.
ssc.gov.in is SSC's actual current domain and is fully reachable everywhere.
It's an Angular SPA (no notice content in the raw HTML), but it's backed by a
clean JSON API discovered via the browser's network tab:

    GET /api/general-website/portal/notice-boards?...

This gives structured data directly — headline, createdAt, and attachment
metadata — with zero AI extraction needed for the core fields, which is both
more reliable (no hallucination risk) and cheaper than the HTML+AI approach
used for other portals. PDF download URLs follow the pattern
/api/attachment/<path-with-forward-slashes>, reverse-engineered from the
compiled Angular bundle since it isn't documented anywhere.

Deeper fields (eligibility, fees, pay scale, selection process) would require
downloading and parsing each PDF's text, which isn't done here — a possible
future enhancement, not required for this to be useful today.
"""
import re
import requests
from datetime import datetime, timezone
from ingest_client import post_jobs

PORTAL_NAME = "SSC"
ORGANIZATION = "Staff Selection Commission"
API_URL = "https://ssc.gov.in/api/general-website/portal/notice-boards"
ATTACHMENT_BASE = "https://ssc.gov.in/api/attachment/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


def build_attachment_url(path: str) -> str:
    # path looks like "uploads\\masterData\\NoticeBoards\\Some File Name.pdf"
    normalized = path.replace("\\", "/")
    segments = normalized.split("/")
    encoded = "/".join(requests.utils.quote(seg) for seg in segments)
    return ATTACHMENT_BASE + encoded


def fetch_notices(limit: int = 20) -> list[dict]:
    params = {
        "page": 1,
        "limit": limit,
        "contentType": "notice-boards",
        "key": "createdAt",
        "order": "DESC",
        "isAttachment": "true",
        "language": "english",
        "attributes": "id,headline,examId,contentType,redirectUrl,startDate,endDate,language,createdAt",
    }
    resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=25)
    resp.raise_for_status()
    return resp.json().get("data", [])


def to_job(notice: dict) -> dict | None:
    headline = re.sub(r"\s+", " ", (notice.get("headline") or "")).strip()
    attachments = notice.get("attachments") or []
    if not headline or not attachments:
        return None

    pdf_url = build_attachment_url(attachments[0]["path"])
    posted_date = None
    if notice.get("createdAt"):
        try:
            posted_date = datetime.fromisoformat(notice["createdAt"].replace("Z", "+00:00")).astimezone(timezone.utc).strftime("%Y-%m-%d")
        except ValueError:
            pass

    return {
        "title": headline,
        "organization": ORGANIZATION,
        "source_portal": PORTAL_NAME,
        "category": "SSC",
        "location": "All India",
        "employment_type": "Permanent",
        "source_url": pdf_url,
        "pdf_url": pdf_url,
        "description": headline,
        "posted_date": posted_date,
    }


if __name__ == "__main__":
    try:
        notices = fetch_notices()
    except Exception as e:
        print(f"[ssc_scraper] failed to fetch notice list: {e}")
        notices = []

    jobs = [j for n in notices if (j := to_job(n)) is not None]
    post_jobs(jobs, PORTAL_NAME)
