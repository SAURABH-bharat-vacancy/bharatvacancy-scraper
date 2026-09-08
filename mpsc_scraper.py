"""MPSC (Maharashtra Public Service Commission) scraper.

mpsc.gov.in is a React SPA with almost nothing in the raw HTML — every other
approach tried for it (see headless_portals.py's git history) meant rendering
the page with Playwright and asking AI to guess a title from the homepage,
which is exactly the kind of thin, low-signal content Search Console flags.
The real data lives behind a JSON API the frontend calls directly
(/web/api/v1/getcontentdata/<mid>), and it hands back structured fields
(title, advertisement number, year, publication date) with zero AI guessing
needed — reverse-engineered from the site's own public JS bundle (the same
bundle every visitor's browser downloads and runs; no private endpoint or
authentication is bypassed):

1. Authorization header: anonymous GET requests send "|#|#" + hex(crc32
   (SECRET)). This is a CONSTANT, not a per-request signature — it only
   depends on a hardcoded secret string the frontend also ships in plain
   text. Recomputed here (rather than hardcoding the hex digest) so this
   keeps working if the secret ever changes. Same CRC-32 algorithm as
   Python's zlib.crc32 (the frontend uses the equivalent JS package).
2. Every response except downloadFile is AES-128-CBC encrypted with a
   hardcoded key/IV (also lifted from the JS bundle), base64-encoded on the
   wire — decrypt before json.loads-ing it.

Scope: only the Advertisements/Notifications category (mid=8), which is
where actual vacancy postings live (a separate mid handles exam results,
which aren't jobs to apply for). The category holds 1000+ entries going back
to 2009 with no "closed"/expiry field, so two filters keep this a feed of
current vacancies rather than a dump of a 15-year archive: a rolling
recency window, and dropping corrigendum notices (amendments to an
already-posted ad, not new vacancies — content_type.php has no bucket for
them, so untouched they'd get misclassified as fresh "Job" postings).

pdf_url is deliberately left unset: the underlying downloadFile endpoint
needs the same Authorization header, so a raw link would 401 for any real
visitor's browser and for ingest.php's own server-side PDF-enrichment fetch.
Fixing that needs a small PHP proxy deployed on Bluehost — not done here.
Real structured fields (advertisement number, year, publication date) are
used to build a short description instead, so pages aren't title-only.
"""
import base64
import json
import re
import zlib
from datetime import datetime

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

from ingest_client import post_jobs

PORTAL_NAME = "MPSC"
ORGANIZATION = "Maharashtra Public Service Commission"
CATEGORY_MID = 8
CATEGORY_URL = "https://mpsc.gov.in/adv_notification/8"
API_URL = f"https://mpsc.gov.in/web/api/v1/getcontentdata/{CATEGORY_MID}"

AES_KEY = b"1234567812345678"
CRC_SECRET = "S300cr3t!@#Key$%^&*()_+[]{}|;':,.<>?/~`"
RECENCY_WINDOW_YEARS = 3

HEADERS = {
    "Authorization": "|#|#" + format(zlib.crc32(CRC_SECRET.encode()) & 0xFFFFFFFF, "x"),
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


def decrypt(b64_ciphertext: str) -> str:
    raw = base64.b64decode(b64_ciphertext)
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_KEY)
    return unpad(cipher.decrypt(raw), AES.block_size).decode("utf-8")


def parse_date(value: str) -> str | None:
    if not value:
        return None
    # Observed format is "YYYY-MM-DD HH:MM:SS"; split rather than strptime
    # the whole thing so an unexpected time component doesn't break parsing.
    date_part = value.split(" ")[0]
    try:
        return datetime.strptime(date_part, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return None


def fetch_notices() -> list[dict]:
    resp = requests.get(API_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    payload = json.loads(decrypt(resp.text))
    return payload[str(CATEGORY_MID)]["webContentList"]


def to_job(entry: dict, min_year: int) -> dict | None:
    title = re.sub(r"\s+", " ", (entry.get("descInEnglish") or "")).strip()
    year = entry.get("yearOfAdvertisement")
    if not title or not isinstance(year, int) or year < min_year:
        return None
    if re.search(r"corrigendum", title, re.IGNORECASE):
        return None

    advt_no = (entry.get("advertisementNumber") or "").strip()
    posted_date = parse_date(entry.get("publicationDate"))

    description_bits = []
    if advt_no and advt_no.upper() != "NA":
        description_bits.append(f"Advertisement No. {advt_no}/{year}")
    else:
        description_bits.append(f"Advertisement, {year}")
    if posted_date:
        description_bits.append(f"published by MPSC on {posted_date}.")
    else:
        description_bits.append("published by MPSC.")

    return {
        "title": title,
        "organization": ORGANIZATION,
        "source_portal": PORTAL_NAME,
        "category": "State",
        "location": "Maharashtra",
        "employment_type": "Permanent",
        "source_url": CATEGORY_URL,
        "description": " ".join(description_bits),
        "posted_date": posted_date,
    }


if __name__ == "__main__":
    try:
        notices = fetch_notices()
    except Exception as e:
        print(f"[mpsc_scraper] failed to fetch/decrypt notice list: {e}")
        notices = []

    min_year = datetime.now().year - RECENCY_WINDOW_YEARS
    jobs = [j for n in notices if (j := to_job(n, min_year)) is not None]
    post_jobs(jobs, PORTAL_NAME)
