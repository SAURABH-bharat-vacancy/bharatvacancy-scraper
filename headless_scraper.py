"""Scraper for portals that block plain HTTP fetches with a real anti-bot
challenge — confirmed via direct testing (see bharatvacancy chat history,
not guessed):

- MPSC (mpsc.gov.in): a React SPA whose data comes from a JSON API
  (/web/api/v1/...) that rejects requests without a "CRC" header the
  frontend JS computes client-side. No documented algorithm, and reverse
  engineering a signing scheme is fragile (breaks silently on any frontend
  update) — rendering the page for real sidesteps it entirely.
- RBI (opportunities.rbi.org.in): fronted by an F5/Shape "TSPD" bot-challenge.
  Replaying the TS* cookies from a plain request (the trick that worked for
  RRB) was NOT enough here — confirmed empirically, still zero real content
  even with cookies replayed. This one genuinely needs JS execution.

Both problems have the same fix: a real browser. Playwright's Chromium runs
the challenge/app JS the same way a human's browser would, so by the time we
read the page it's already past whatever plain requests/curl can't get
through. Same extract_jobs_ai + link-inlining + ingest pipeline as every
other scraper after that — the only different part is how the raw HTML is
obtained.

Deliberately not *_scraper.py (see tier1_batch.py for why) and not merged
into tier1_batch.py — a headless browser is much heavier per-portal (real
page load, real render wait) than a plain requests.get(), so this runs on
its own schedule via scrape-headless.yml rather than piggybacking on
tier1_batch's cadence.
"""
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright
from extract_jobs_ai import extract_jobs
from ingest_client import post_jobs
from page_cache_client import page_unchanged_since_last_run

MIN_USEFUL_TEXT_LENGTH = 800

# (portal_name, organization, url, category)
PORTALS = [
    ("MPSC", "Maharashtra Public Service Commission", "https://mpsc.gov.in/", "State"),
    ("RBI", "Reserve Bank of India", "https://opportunities.rbi.org.in/scripts/index.aspx", "Banking"),
]


def fetch_rendered_text(page, url: str) -> str:
    """Loads the URL in a real browser context, waits for network activity
    to settle (the app's own API calls + any anti-bot challenge/redirect),
    then extracts text the same way fetch_page_text() does elsewhere —
    stripped to plain text, but with each link's resolved URL inlined next
    to its text (e.g. "Download Advertisement [https://.../notice.pdf]") so
    extract_jobs_ai can still report a pdf_url/source_url from a listing
    page rendered this way.
    """
    page.goto(url, wait_until="networkidle", timeout=45000)
    # Anti-bot challenges (RBI's TSPD) sometimes redirect/reload once more
    # after the initial "networkidle" — a short additional wait catches that
    # without needing to detect the specific challenge mechanism.
    page.wait_for_timeout(3000)
    html = page.content()
    final_url = page.url

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("javascript:") or href.startswith("#"):
            continue
        resolved = urljoin(final_url, href)
        text = a.get_text(strip=True)
        a.replace_with(f"{text} [{resolved}]" if text else f"[{resolved}]")
    return soup.get_text(separator="\n", strip=True)


if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()

        for portal_name, organization, url, category in PORTALS:
            try:
                text = fetch_rendered_text(page, url)
            except Exception as e:
                print(f"[headless_scraper] [{portal_name}] failed to fetch {url}: {e}")
                continue

            print(f"[headless_scraper] [{portal_name}] fetched {len(text)} chars from {url}")

            if len(text) < MIN_USEFUL_TEXT_LENGTH:
                print(f"[headless_scraper] [{portal_name}] SKIPPED extraction: content too short ({len(text)} chars), likely still blocked/stub")
                continue

            if page_unchanged_since_last_run(portal_name, text):
                print(f"[headless_scraper] [{portal_name}] SKIPPED extraction: page unchanged since last run")
                continue

            try:
                jobs = extract_jobs(text, portal_name, url)
            except Exception as e:
                print(f"[headless_scraper] [{portal_name}] extraction failed: {e}")
                continue

            for job in jobs:
                job["source_portal"] = portal_name
                job["category"] = category
                if not job.get("organization"):
                    job["organization"] = organization

            post_jobs(jobs, portal_name)

        browser.close()
