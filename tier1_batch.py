"""Batch scraper for Tier 1 portals identified in PORTAL_RESEARCH.md — confirmed
server-rendered (simple HTTP fetch works, no headless browser needed), same
HTML+AI extraction pattern as army_scraper.py/ibps_scraper.py.

Deliberately NOT named *_scraper.py so the main every-15-minutes workflow
(scrape-jobs.yml, which globs *_scraper.py) does not pick this up. Running
multiple portals' worth of AI extraction calls every 15 minutes would be
wasteful — none of these portals post new notices anywhere near that often.
Instead this runs on its own low-frequency schedule via scrape-tier1.yml.

Only lists portals confirmed reachable from GitHub Actions' cloud IPs — see
the comment above PORTALS for the ones deliberately excluded and why.

Each portal is wrapped in its own try/except so one bad fetch (timeout, block,
site redesign) doesn't take down the whole batch — matches the pattern in
cron/run.php. A short-content guard skips the paid AI call on pages that
clearly didn't return real listings (blocked/stub/error page).
"""
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from extract_jobs_ai import extract_jobs
from ingest_client import post_jobs
from page_cache_client import page_unchanged_since_last_run

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

MIN_USEFUL_TEXT_LENGTH = 800

# (portal_name, organization, url, category)
#
# RRB, RRB Mumbai, Rajasthan PSC, Tamil Nadu PSC, DRDO RAC, Join Indian Navy,
# EPFO, CRPF, ONGC, NTPC, and Coal India are deliberately NOT in this list —
# confirmed unreachable from GitHub Actions' cloud IP ranges (connection
# refused/timeout) or WAF-blocked (NTPC, Coal India: 403), every single run.
# cron/run-tier1.php on Bluehost's own IP already covers all of them; keeping
# them here just wastes the run on fetches that always fail. Only add a
# portal back here if it's independently confirmed reachable from GitHub
# Actions specifically, not just reachable in general.
PORTALS = [
    ("RRB Bhubaneswar", "Railway Recruitment Board, Bhubaneswar", "https://www.rrbbbs.gov.in/", "Railways"),
    ("Bihar Police", "Central Selection Board of Constable, Bihar", "https://csbc.bihar.gov.in/", "Police"),
    ("UP Police", "Uttar Pradesh Police Recruitment and Promotion Board", "https://uppbpb.gov.in/", "Police"),
    ("ISRO", "Indian Space Research Organisation", "https://www.isro.gov.in/CurrentOpportunities.html", "PSU"),
    ("India Post", "Department of Posts", "https://www.indiapost.gov.in/vacancies", "PSU"),
    ("SAIL", "Steel Authority of India Limited", "https://sailcareers.com/", "PSU"),
    ("Indian Coast Guard", "Indian Coast Guard", "https://www.indiancoastguard.gov.in/recruitment", "Defence"),
]


def _is_row_like(tag) -> bool:
    """Detects a per-notice "row" — either a literal <tr>, or (very common on
    Bootstrap-templated .gov.in sites; confirmed on ISRO's live
    CurrentOpportunities markup) a <div class="row ..."> wrapping two or more
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
    text of its own (an icon-only button — confirmed on ISRO's per-notice
    links, which ARE real, resolvable hrefs, just rendered as an eye icon
    with no link text) ends up as a bare "[url]" line with nothing tying it
    back to which notice it belongs to. Confirmed live: this dropped ISRO's
    flattened page from ~225k chars of mostly whitespace-fragmented noise
    down to ~42k of clean, row-per-line text, well inside the 60k-char
    extraction budget in extract_jobs_ai.py.

    Returns None (caller leaves the row's original markup untouched) rather
    than a joined string when the collapse would lose a meaningful chunk of
    the row's real text — confirmed happening on UP Police, where the
    row-detector matched a notice carousel whose actual Hindi title text
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
    resp = requests.get(url, headers=HEADERS, timeout=25)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()

    # Collapse each detected listing row into one line before the generic
    # anchor-inlining pass below — see _is_row_like()/_collapse_row().
    # Processed in reverse document order so a nested row (if any) collapses
    # before its ancestor row does, rather than the ancestor swallowing an
    # already-detached child.
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
    for portal_name, organization, url, category in PORTALS:
        try:
            text = fetch_page_text(url)
        except Exception as e:
            print(f"[tier1_batch] [{portal_name}] failed to fetch {url}: {e}")
            continue

        print(f"[tier1_batch] [{portal_name}] fetched {len(text)} chars from {url}")

        if len(text) < MIN_USEFUL_TEXT_LENGTH:
            print(f"[tier1_batch] [{portal_name}] SKIPPED extraction: content too short ({len(text)} chars), likely blocked/stub")
            continue

        if page_unchanged_since_last_run(portal_name, text):
            print(f"[tier1_batch] [{portal_name}] SKIPPED extraction: page unchanged since last run")
            continue

        try:
            jobs = extract_jobs(text, portal_name, url)
        except Exception as e:
            print(f"[tier1_batch] [{portal_name}] extraction failed: {e}")
            continue

        for job in jobs:
            job["source_portal"] = portal_name
            job["category"] = category
            if not job.get("organization"):
                job["organization"] = organization

        post_jobs(jobs, portal_name)
