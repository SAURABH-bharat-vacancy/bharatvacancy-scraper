"""Submits current Job-listing URLs to Google's Indexing API.

Google restricts the Indexing API to exactly two content types: JobPosting
and BroadcastEvent pages. job.php only emits JobPosting schema for
content_type='Job' postings that haven't passed their apply_last_date (see
job.php's own schema-suppression logic) — job-urls-feed.php (a small,
public, read-only PHP endpoint, same trust level as sitemap.php) mirrors
that exact filter, so every URL this script sees is one Google will accept
a notification for.

This exists because Search Console showed ~99% of this site's unindexed
pages have never actually been crawled by Google — a crawl-budget symptom
of perceived low site quality/authority, not a technical block (see
bharatvacancy chat history, 2026-09-08 Search Console diagnosis). The
Indexing API bypasses that starved discovery queue entirely for the one
content type it's allowed to: it notifies Google directly instead of
waiting for organic re-crawling.

Auth: a Google Cloud service account (indexing-submitter@bharat-vacancy,
added as Owner in Search Console for bharatvacancy.com) signs a JWT for the
'indexing' scope. Its key ships as the GOOGLE_INDEXING_SA_KEY secret (the
full JSON key file content, as one string).

State: indexing_state.json in this repo tracks which URLs have already been
submitted, so repeated runs don't re-notify the same ones and burn the daily
quota (200 requests/project/day, default) on already-covered content. The
workflow commits this file back to the repo after each run.
"""
import json
import os
import sys
from pathlib import Path

import requests
from google.oauth2 import service_account
from google.auth.transport.requests import Request

FEED_URL = "https://bharatvacancy.com/job-urls-feed.php"
# Bluehost's ModSecurity WAF blocks requests' default "python-requests/x.y"
# User-Agent as a bot signature (same issue documented in ingest_client.py) —
# a browser-like UA avoids the 406.
FEED_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"}
INDEXING_ENDPOINT = "https://indexing.googleapis.com/v3/urlNotifications:publish"
SCOPES = ["https://www.googleapis.com/auth/indexing"]
STATE_FILE = Path(__file__).parent / "indexing_state.json"
DAILY_LIMIT = 190  # default quota is 200/project/day; leave some headroom


def load_submitted() -> set[str]:
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text(encoding="utf-8")).get("submitted", []))
    return set()


def save_submitted(urls: set[str]) -> None:
    STATE_FILE.write_text(json.dumps({"submitted": sorted(urls)}, indent=2), encoding="utf-8")


def get_access_token() -> str:
    key_json = os.environ.get("GOOGLE_INDEXING_SA_KEY", "")
    if not key_json:
        print("[submit_indexing] ERROR: GOOGLE_INDEXING_SA_KEY is not set", file=sys.stderr)
        sys.exit(1)
    info = json.loads(key_json)
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    creds.refresh(Request())
    return creds.token


def fetch_eligible_urls() -> list[str]:
    resp = requests.get(FEED_URL, headers=FEED_HEADERS, timeout=30)
    resp.raise_for_status()
    return [line.strip() for line in resp.text.splitlines() if line.strip()]


if __name__ == "__main__":
    token = get_access_token()
    eligible = fetch_eligible_urls()
    submitted = load_submitted()

    pending = [u for u in eligible if u not in submitted]
    batch = pending[:DAILY_LIMIT]
    print(f"[submit_indexing] {len(eligible)} eligible, {len(submitted)} already submitted, {len(pending)} pending, submitting {len(batch)} now")

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    succeeded = 0
    for url in batch:
        try:
            resp = requests.post(INDEXING_ENDPOINT, headers=headers, json={"url": url, "type": "URL_UPDATED"}, timeout=15)
            if resp.status_code == 200:
                submitted.add(url)
                succeeded += 1
            else:
                print(f"[submit_indexing] FAILED {url}: {resp.status_code} {resp.text[:200]}", file=sys.stderr)
        except Exception as e:
            print(f"[submit_indexing] FAILED {url}: {e}", file=sys.stderr)

    save_submitted(submitted)
    print(f"[submit_indexing] submitted {succeeded}/{len(batch)} successfully; {len(submitted)} total submitted to date")
