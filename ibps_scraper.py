"""IBPS (Institute of Banking Personnel Selection) scraper.

Fetches the public site's notice-bearing pages as raw text and hands them to
extract_jobs_ai for structured extraction — this replaces the old keyword-matching
approach (which produced fake placeholder listings whenever it couldn't find a match).
"""
import re
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


def _is_row_like(tag) -> bool:
    """Detects a per-notice "row" — either a literal <tr>, or (very common on
    Bootstrap-templated .gov.in sites; confirmed on ISRO's live
    CurrentOpportunities markup, same shared cause as this scraper's
    empty-pdf_url gap) a <div class="row ..."> wrapping two or more
    <div class="col-* ..."> cells. Requires >=2 "col"-classed children rather
    than matching any div with "row" in its class, so this doesn't also
    swallow generic layout wrappers that have nothing to do with a listing.
    """
    if tag.name == "tr":
        return True
    if tag.name in ("div", "li"):
        classes = tag.get("class") or []
        if not any("row" in c.lower() for c in classes):
            return False
        children = tag.find_all(recursive=False)
        if not children:
            return False
        col_children = sum(
            1 for c in children
            if any("col" in cl.lower() for cl in (c.get("class") or []))
        )
        return col_children >= 2
    return False


def _collapse_row(row, base_url: str):
    """Flattens one listing row into a single ' | '-joined line, inlining any
    real (non-JS, non-stub) link found in it right next to its own cell.
    Without this, a row's cells become separate lines once the whole page is
    flattened to text, and a "View Details"/"Download" link with no visible
    text of its own (an icon-only button) ends up as a bare "[url]" line
    with nothing tying it back to which notice it belongs to.

    Returns None (caller leaves the row's original markup untouched) rather
    than a joined string when the collapse would lose a meaningful chunk of
    the row's real text — confirmed happening on UP Police (a different
    portal's markup, but same shared fetch_page_text() logic as this file),
    where the row-detector matched a notice carousel whose actual title text
    lived outside what got treated as "cells" here, silently dropping every
    notice's title. Better to leave that row for the generic anchor-inlining
    pass below to handle exactly as it always has than risk that again.
    """
    original_len = len(re.sub(r"\s+", " ", row.get_text(" ", strip=True)).strip())

    cell_tags = row.find_all(["td", "th"]) if row.name == "tr" else row.find_all(recursive=False)
    if not cell_tags:
        cell_tags = [row]

    cells = []
    for cell in cell_tags:
        for a in cell.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith("javascript:") or href.startswith("#"):
                continue
            resolved = urljoin(base_url, href)
            text = a.get_text(strip=True)
            a.replace_with(f"{text} [{resolved}]" if text else f"[{resolved}]")
        cell_text = re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).strip()
        if cell_text:
            cells.append(cell_text)
    joined = " | ".join(cells)

    if original_len > 0 and len(joined) < original_len * 0.8:
        return None
    return joined


def fetch_page_text(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=20, verify=False)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()

    # Collapse each detected listing row into one line before the generic
    # anchor-inlining pass below — see _is_row_like()/_collapse_row() (same
    # fix as tier1_batch.py, kept in sync since this file duplicates that
    # one's fetch_page_text() rather than sharing it).
    for row in reversed([t for t in soup.find_all(["tr", "div", "li"]) if _is_row_like(t)]):
        if row.parent is None:
            continue
        joined = _collapse_row(row, resp.url)
        if joined:
            row.replace_with(joined)

    # Inline each remaining link's resolved URL next to its text (e.g.
    # "Download Advertisement [https://.../notice.pdf]") before stripping to
    # plain text — get_text() alone drops href attributes entirely, so the
    # AI extraction step had no way to report a pdf_url from a listing page.
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
