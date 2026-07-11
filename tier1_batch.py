"""Batch scraper for Tier 1 portals identified in PORTAL_RESEARCH.md — confirmed
server-rendered (simple HTTP fetch works, no headless browser needed), same
HTML+AI extraction pattern as army_scraper.py/ibps_scraper.py.

Deliberately NOT named *_scraper.py so the main every-15-minutes workflow
(scrape-jobs.yml, which globs *_scraper.py) does not pick this up. Running 17
portals' worth of AI extraction calls every 15 minutes would be wasteful —
none of these portals post new notices anywhere near that often. Instead this
runs on its own low-frequency schedule via scrape-tier1.yml.

Each portal is wrapped in its own try/except so one bad fetch (timeout, block,
site redesign) doesn't take down the whole batch — matches the pattern in
cron/run.php. A short-content guard skips the paid AI call on pages that
clearly didn't return real listings (blocked/stub/error page).
"""
import requests
from bs4 import BeautifulSoup
from extract_jobs_ai import extract_jobs
from ingest_client import post_jobs

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

MIN_USEFUL_TEXT_LENGTH = 800

# (portal_name, organization, url, category)
PORTALS = [
    ("RRB", "Railway Recruitment Board", "https://rrb.indianrailways.gov.in/", "Railways"),
    ("RRB Mumbai", "Railway Recruitment Board, Mumbai", "https://rrbmumbai.gov.in/", "Railways"),
    ("RRB Bhubaneswar", "Railway Recruitment Board, Bhubaneswar", "https://www.rrbbbs.gov.in/", "Railways"),
    ("Bihar Police", "Central Selection Board of Constable, Bihar", "https://csbc.bihar.gov.in/", "Police"),
    ("UP Police", "Uttar Pradesh Police Recruitment and Promotion Board", "https://uppbpb.gov.in/", "Police"),
    ("Rajasthan PSC", "Rajasthan Public Service Commission", "https://rpsc.rajasthan.gov.in/", "State"),
    ("Tamil Nadu PSC", "Tamil Nadu Public Service Commission", "https://www.tnpsc.gov.in/", "State"),
    ("ISRO", "Indian Space Research Organisation", "https://www.isro.gov.in/CurrentOpportunities.html", "PSU"),
    ("DRDO RAC", "Recruitment & Assessment Centre, DRDO", "https://rac.gov.in/", "PSU"),
    ("Join Indian Navy", "Indian Navy", "https://www.joinindiannavy.gov.in/", "Defence"),
    ("EPFO", "Employees' Provident Fund Organisation", "https://www.epfindia.gov.in/site_en/Recruitments.php", "PSU"),
    ("India Post", "Department of Posts", "https://www.indiapost.gov.in/vacancies", "PSU"),
    ("CRPF", "Central Reserve Police Force", "https://rect.crpf.gov.in/", "Police"),
    ("ONGC", "Oil and Natural Gas Corporation", "https://www.ongcindia.com/web/eng/career/recruitment-notice", "PSU"),
    ("NTPC", "NTPC Limited", "https://careers.ntpc.co.in/recruitment/", "PSU"),
    ("Coal India", "Coal India Limited", "https://www.coalindia.in/career-cil/jobs-coal-india/", "PSU"),
    ("SAIL", "Steel Authority of India Limited", "https://sailcareers.com/", "PSU"),
    ("Indian Coast Guard", "Indian Coast Guard", "https://www.indiancoastguard.gov.in/recruitment", "Defence"),
]


def fetch_page_text(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=25)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
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
