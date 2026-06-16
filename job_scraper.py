#!/usr/bin/env python3
"""
SSC Notice Board Scraper for bharatvacancy.com
------------------------------------------------
Pulls the latest notices straight from SSC's official data feed
(the same feed ssc.gov.in uses to fill its own Notice Board),
sorts likely NEW JOB notices from answer-keys/results/admin noise,
and writes a clean CSV ready for review + WP All Import.

No WordPress posting here on purpose. This just makes the CSV.
"""

import requests
import csv
import sys
import json
from datetime import datetime

# ---- The official SSC feed you found in DevTools ----
SSC_API = "https://ssc.gov.in/api/general-website/portal/notice-boards"
SSC_PARAMS = {
    "page": 1,
    "limit": 40,  # pull the 40 most recent notices (feed has 600+ total)
    "contentType": "notice-boards",
    "key": "createdAt",
    "order": "DESC",
    "isAttachment": "true",
    "language": "english",
    "attributes": "id,headline,examId,contentType,redirectUrl,startDate,endDate,language,createdAt",
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

# A notice is almost certainly NOT a new job if its title mentions these.
# (Checked FIRST, so it wins over the job words below.)
SKIP_KEYWORDS = [
    "answer key", "tentative answer", "final answer", "response sheet",
    "result", "cut-off", "cut off", "cutoff", "marks of", "score card",
    "scorecard", "admit card", "status of", "list of candidates",
    "option-cum-preference", "option cum preference", "corrigendum",
    "withdrawal", "postpone", "reschedul", "declaration of result",
    "uploading of", "marks and", "writ petition", "court case",
    "schedule of examination", "time table", "time-table",
    "examination schedule", "exam schedule",
]

# A notice is likely a real recruitment opening if its title mentions these.
JOB_KEYWORDS = [
    "recruitment", "notification", "examination", "notice of", "advertisement",
    "vacancy", "vacancies", "apply online", "selection post", "combined",
    "phase-", "phase ", "junior engineer", "stenographer", "constable",
    "sub-inspector", "head constable", "multi tasking", "multi-tasking",
]


def classify(headline: str) -> str:
    h = headline.lower()
    if any(k in h for k in SKIP_KEYWORDS):
        return "skip"
    if any(k in h for k in JOB_KEYWORDS):
        return "job"
    return "review"


ATTACHMENT_BASE = "https://ssc.gov.in/api/attachment/uploads/masterData/NoticeBoards/"


def _url_from_string(s) -> str:
    """Turn any path/filename/URL string into a full clickable SSC link."""
    if not isinstance(s, str):
        return ""
    s = s.strip().replace("\\", "/")   # SSC stores paths with backslashes
    if not s:
        return ""
    if s.startswith("http"):
        return s
    if s.startswith("api/"):
        return "https://ssc.gov.in/" + s
    if s.startswith("/"):
        return "https://ssc.gov.in" + s
    if "uploads/" in s:
        return "https://ssc.gov.in/api/attachment/" + s.lstrip("/")
    if s.lower().endswith(".pdf"):
        return ATTACHMENT_BASE + s
    return ""


def build_link(rec: dict) -> str:
    """Best official link: the notice PDF (attachments) first, then redirectUrl."""
    # 1) Prefer the actual notice attachment (the PDF candidates apply from).
    atts = rec.get("attachments")
    if isinstance(atts, list) and atts:
        first = atts[0]
        if isinstance(first, dict):
            for key in ("url", "fileUrl", "filePath", "path", "location", "src",
                        "attachment", "downloadUrl", "fileName", "name", "file"):
                link = _url_from_string(first.get(key))
                if link:
                    return link
        else:
            link = _url_from_string(first)
            if link:
                return link
    # 2) Fall back to redirectUrl if present.
    link = _url_from_string(rec.get("redirectUrl") or "")
    if link:
        return link
    # 3) Last resort: the SSC notice board itself.
    return "https://ssc.gov.in"


def nice_date(rec: dict) -> str:
    raw = rec.get("startDate") or rec.get("createdAt") or ""
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw[:len(datetime.now().strftime(fmt))], fmt).strftime("%d %B %Y")
        except (ValueError, TypeError):
            continue
    return raw[:10] if raw else datetime.now().strftime("%d %B %Y")


def make_description(headline: str, date_str: str, link: str) -> str:
    """Original wrapper text (our own words) around the factual notice."""
    return (
        f"{headline} has been announced by the Staff Selection Commission (SSC). "
        f"This official notice was published on {date_str}. "
        f"Eligible candidates can check the full details \u2014 including eligibility, "
        f"important dates, vacancy information, and the step-by-step application process "
        f"\u2014 from the official SSC notice. Bharat Vacancy tracks the latest Government "
        f"of India job notifications so candidates never miss an opportunity. "
        f"Always verify final details on the official SSC website before applying."
    )


def fetch_notices():
    print("Connecting to the official SSC notice feed...")
    res = requests.get(SSC_API, params=SSC_PARAMS, headers=HEADERS, timeout=30)
    print(f"  -> HTTP {res.status_code} from ssc.gov.in")
    res.raise_for_status()
    payload = res.json()

    data = payload.get("data", [])
    print(f"  -> Feed returned {len(data)} notices "
          f"(total available: {payload.get('paginate', {}).get('totalRecords', '?')})")

    if data:
        # Show field names + the real attachment structure so links can be verified.
        print(f"  -> Fields on each notice: {sorted(data[0].keys())}")
        sample_att = json.dumps(data[0].get("attachments"))[:400]
        print(f"  -> Sample 'attachments': {sample_att}")
        print(f"  -> Sample built link  : {build_link(data[0])}")
    return data


def main():
    try:
        notices = fetch_notices()
    except Exception as e:
        print(f"ERROR talking to SSC: {e}")
        sys.exit(1)

    rows = []
    for rec in notices:
        headline = (rec.get("headline") or "").strip()
        if not headline:
            continue
        kind = classify(headline)
        date_str = nice_date(rec)
        link = build_link(rec)
        rows.append({
            "type_guess": {"job": "1_LIKELY_NEW_JOB",
                           "review": "2_REVIEW",
                           "skip": "3_answer_key_result_admin"}[kind],
            "title": headline[:180],
            "company": "Staff Selection Commission",
            "location": "All India",
            "category": "SSC Jobs",
            "job_type": "Permanent",
            "application_link": link,
            "notice_date": date_str,
            "description": make_description(headline, date_str, link),
        })

    # Sort so the likely-new-jobs sit at the very top for easy review.
    rows.sort(key=lambda r: r["type_guess"])

    # File 1: full review file (every notice + the type_guess column) for your eyes.
    review_file = "ssc_jobs.csv"
    review_fields = ["type_guess", "title", "company", "location", "category",
                     "job_type", "application_link", "notice_date", "description"]
    with open(review_file, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=review_fields)
        w.writeheader()
        w.writerows(rows)

    # File 2: clean import file -- ONLY likely-new-jobs, ONLY the 7 columns
    # WP All Import is mapped to. This is the feed WP All Import can pull from a URL.
    import_file = "ssc_import.csv"
    import_fields = ["title", "company", "location", "category",
                     "job_type", "application_link", "description"]
    job_rows = [r for r in rows if r["type_guess"].startswith("1")]
    with open(import_file, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=import_fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(job_rows)

    jobs = sum(1 for r in rows if r["type_guess"].startswith("1"))
    review = sum(1 for r in rows if r["type_guess"].startswith("2"))
    skip = sum(1 for r in rows if r["type_guess"].startswith("3"))
    print("\n==== DONE ====")
    print(f"Reviewed {len(rows)} notices from SSC.")
    print(f"  {jobs} look like NEW JOBS  -> written to ssc_import.csv (ready to import)")
    print(f"  {review} need a quick human look (see ssc_jobs.csv)")
    print(f"  {skip} are answer-keys / results / admin (ignored)")
    print("ssc_jobs.csv  = full list for your review")
    print("ssc_import.csv = clean job-only feed for WP All Import")


if __name__ == "__main__":
    main()
