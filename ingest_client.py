"""Shared client every portal scraper uses to POST jobs to bharatvacancy.com.

Dedup happens server-side (by portal+title+url hash), so scrapers can be
sloppy about re-sending jobs they've seen before — the server just reports
them back as duplicates instead of erroring.
"""
import os
import sys
import json
import urllib.request
import urllib.error

INGEST_URL = os.environ.get("INGEST_URL", "https://bharatvacancy.com/ingest.php")
INGEST_API_KEY = os.environ.get("INGEST_API_KEY", "")


def post_jobs(jobs: list[dict], scraper_name: str) -> dict:
    """POST a list of job dicts to the ingest endpoint. Exits non-zero on failure
    so GitHub Actions marks the run as failed and you get notified.

    Each job dict should have: title, organization, source_portal, source_url,
    and optionally category, location, employment_type, description,
    posted_date (YYYY-MM-DD), apply_last_date.
    """
    if not INGEST_API_KEY:
        print(f"[{scraper_name}] ERROR: INGEST_API_KEY is not set", file=sys.stderr)
        sys.exit(1)

    if not jobs:
        print(f"[{scraper_name}] No jobs found this run — nothing to send.")
        return {"received": 0, "inserted": 0, "duplicate": 0, "errors": []}

    body = json.dumps(jobs).encode("utf-8")
    req = urllib.request.Request(
        INGEST_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Api-Key": INGEST_API_KEY,
            "X-Scraper-Name": scraper_name,
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"[{scraper_name}] ERROR: ingest.php returned HTTP {e.code}: {e.read().decode('utf-8', 'ignore')}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[{scraper_name}] ERROR: failed to reach ingest.php: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"[{scraper_name}] received={result['received']} inserted={result['inserted']} duplicate={result['duplicate']}")
    if result.get("errors"):
        for err in result["errors"]:
            print(f"[{scraper_name}] WARNING: {err}", file=sys.stderr)

    return result
