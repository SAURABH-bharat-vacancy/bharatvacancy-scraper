"""Cross-run change-detection for scrapers running on GitHub Actions' stateless
runners — see bharatvacancy/page-cache.php for the server side and
cron/lib.php's page_unchanged_since_last_run() for the equivalent file-backed
version used by the Bluehost crons.

Calling this costs one cheap HTTP round trip; skipping it costs a full paid
AI extraction call on content that's identical to last time. Always call it
right after fetching a page's text and before extract_jobs().
"""
import hashlib
import json
import urllib.request
import urllib.error
from ingest_client import INGEST_URL, INGEST_API_KEY

PAGE_CACHE_URL = INGEST_URL.rsplit("/", 1)[0] + "/page-cache.php"


def page_unchanged_since_last_run(portal_name: str, text: str) -> bool:
    """Returns True if this exact page text was already seen on the last
    successful check for this portal — callers should skip the AI call in
    that case. Best-effort: any failure talking to the cache endpoint is
    treated as "not cached" so a scraper never silently stops extracting
    just because this side-channel had a hiccup.
    """
    if not INGEST_API_KEY:
        return False

    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    body = json.dumps({"portal": portal_name, "hash": content_hash}).encode("utf-8")
    req = urllib.request.Request(
        PAGE_CACHE_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "BharatVacancyScraper/1.0 (+https://bharatvacancy.com)",
            "X-Api-Key": INGEST_API_KEY,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        return bool(result.get("unchanged"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError):
        return False
