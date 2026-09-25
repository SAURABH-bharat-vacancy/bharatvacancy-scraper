"""Fills in missing detail fields on live job pages using Groq (no Anthropic).

Why this exists: enrichment used to depend on Anthropic (out of credits) with
Gemini's free tier as the only fallback (~20 PDFs/day), so most pages were
left with just a title, organization and date. Groq cannot read PDFs directly,
so this downloads each page's notification PDF, extracts its text layer with
pypdf, and asks Groq for the same fields pdf_enrich.php would have produced.

Flow per run: read the public job URL feed -> for each not-yet-tried page,
read its pdf link and check whether it already has detail sections -> fetch +
extract + Groq -> POST the fields to ingest.php with X-Action: enrich, which
only fills NULL/empty columns (COALESCE), never overwrites real data.

Scanned PDFs (no text layer) are recorded as 'notext' and skipped, not retried.
State lives in enrich_state.json and is committed back by the workflow.
"""
import html
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import requests
from pypdf import PdfReader

FEED_URL = "https://bharatvacancy.com/job-urls-feed.php"
INGEST_URL = os.environ.get("INGEST_URL", "https://bharatvacancy.com/ingest.php")
INGEST_API_KEY = os.environ.get("INGEST_API_KEY", "")
STATE_FILE = Path(__file__).parent / "enrich_state.json"
PER_RUN_LIMIT = int(os.environ.get("ENRICH_LIMIT", "40"))
DRY_RUN = os.environ.get("ENRICH_DRY_RUN") == "1"
MAX_PDF_BYTES = 8 * 1024 * 1024
MAX_TRIES = 3

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
BROWSER_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_KEYS = [k for k in (os.environ.get(n, "") for n in (
    "GROQ_API_KEY", "GROQ_API_KEY_2", "GROQ_API_KEY_3", "GROQ_API_KEY_4", "GROQ_API_KEY_5")) if k]

FIELDS = ["description", "vacancy_count", "min_qualification", "age_limit",
          "application_fee", "pay_scale", "selection_process", "how_to_apply", "apply_last_date"]
ENRICHED_MARKERS = ("Eligibility Criteria", "Selection Process", "How to Apply")


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")


def read_page(url: str):
    """Returns (title, pdf_url, already_enriched) for a live job page."""
    text = requests.get(url, headers=BROWSER_HEADERS, timeout=30).text
    title = re.search(r"<h1>(.*?)</h1>", text, re.S)
    pdf = re.search(r'class="pdf-btn" href="([^"]+)"', text)
    return (
        html.unescape(title.group(1)).strip() if title else "",
        html.unescape(pdf.group(1)) if pdf else None,
        any(m in text for m in ENRICHED_MARKERS),
    )


def pdf_text(pdf_url: str) -> str:
    try:
        resp = requests.get(pdf_url, headers={"User-Agent": UA}, timeout=40, stream=True)
    except requests.exceptions.SSLError:
        # Several .gov.in hosts (ibps.in confirmed) ship an incomplete cert chain.
        # Only public, read-only PDFs are fetched here, so retrying unverified is
        # acceptable; nothing sensitive is sent and only extracted text is used.
        import urllib3
        urllib3.disable_warnings()
        resp = requests.get(pdf_url, headers={"User-Agent": UA}, timeout=40, stream=True, verify=False)
    resp.raise_for_status()
    data = resp.raw.read(MAX_PDF_BYTES + 1, decode_content=True)
    if len(data) > MAX_PDF_BYTES or not data.startswith(b"%PDF"):
        return ""
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((p.extract_text() or "") for p in reader.pages[:12])


def groq_extract(title: str, text: str):
    prompt = (
        "From this Indian government notification text, extract JSON with ONLY these keys, "
        "and ONLY when the text explicitly states them (omit anything not stated, never guess): "
        "description (1-2 factual sentences about this notice, not the title restated), "
        "vacancy_count, min_qualification, age_limit, application_fee, pay_scale, "
        "selection_process, how_to_apply, apply_last_date (YYYY-MM-DD). "
        "Respond with a single JSON object and nothing else.\n"
        f"TITLE: {title}\nTEXT:\n{text[:12000]}"
    )
    body = json.dumps({"model": GROQ_MODEL, "max_tokens": 2000, "reasoning_effort": "low",
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    for key in GROQ_KEYS:
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions", data=body, method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}", "User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                content = json.loads(r.read())["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            if e.code == 429:
                continue  # this key is spent, try the next
            print(f"  groq HTTP {e.code}", file=sys.stderr)
            return None
        except Exception as e:
            print(f"  groq error {e}", file=sys.stderr)
            return None
        m = re.search(r"\{.*\}", content, re.S)
        try:
            return json.loads(m.group(0)) if m else {}
        except json.JSONDecodeError:
            return {}
    return "ratelimited"


def clean(fields: dict) -> dict:
    out = {}
    for k in FIELDS:
        v = fields.get(k)
        if v is None or isinstance(v, (dict, list)):
            continue
        v = re.sub(r"\s+", " ", str(v)).strip()
        if not v or v.lower() in ("n/a", "na", "not stated", "not mentioned", "null", "none"):
            continue
        if k == "apply_last_date" and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            continue
        out[k] = v[:1500]
    return out


def post_enrich(slug: str, fields: dict) -> bool:
    body = json.dumps([{"slug": slug, **fields}]).encode()
    req = urllib.request.Request(
        INGEST_URL, data=body, method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "BharatVacancyScraper/1.0 (+https://bharatvacancy.com)",
                 "X-Api-Key": INGEST_API_KEY, "X-Action": "enrich", "X-Scraper-Name": "enrich_backfill"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read()).get("updated", 0) > 0
    except Exception as e:
        print(f"  enrich POST failed: {e}", file=sys.stderr)
        return False


def main() -> None:
    if not GROQ_KEYS:
        print("[enrich_backfill] ERROR: no GROQ_API_KEY* set", file=sys.stderr)
        sys.exit(1)
    if not DRY_RUN and not INGEST_API_KEY:
        print("[enrich_backfill] ERROR: INGEST_API_KEY is not set", file=sys.stderr)
        sys.exit(1)

    urls = requests.get(FEED_URL, headers=BROWSER_HEADERS, timeout=30).text.split()
    state = load_state()
    todo = []
    for u in urls:
        slug = urllib.parse.parse_qs(urllib.parse.urlparse(u).query).get("slug", [""])[0]
        st = state.get(slug, {})
        if st.get("status") in ("ok", "nopdf", "notext", "enriched") or st.get("tries", 0) >= MAX_TRIES:
            continue
        todo.append((slug, u))
    print(f"[enrich_backfill] {len(urls)} pages in feed, {len(todo)} untried, doing up to {PER_RUN_LIMIT}")

    done = 0
    for slug, url in todo:
        if done >= PER_RUN_LIMIT:
            break
        try:
            title, pdf_url, enriched = read_page(url)
        except Exception as e:
            print(f"  page fetch failed {slug[:40]}: {e}", file=sys.stderr)
            continue
        if enriched:
            state[slug] = {"status": "enriched"}
            continue
        if not pdf_url or not pdf_url.lower().split("?")[0].endswith((".pdf",)) and "pdf" not in pdf_url.lower():
            state[slug] = {"status": "nopdf"}
            continue
        done += 1
        print(f"[{done}] {title[:70]}")
        try:
            text = pdf_text(pdf_url)
        except Exception as e:
            st = state.get(slug, {}); state[slug] = {"status": "fail", "tries": st.get("tries", 0) + 1}
            print(f"  pdf fetch/parse failed: {e}", file=sys.stderr)
            continue
        if len(text.strip()) < 200:
            state[slug] = {"status": "notext"}
            print("  no text layer (scanned) - skipped")
            continue
        res = groq_extract(title, text)
        if res == "ratelimited":
            print("  all Groq keys rate-limited - stopping this run")
            break
        if res is None:
            st = state.get(slug, {}); state[slug] = {"status": "fail", "tries": st.get("tries", 0) + 1}
            continue
        fields = clean(res)
        print("  fields:", ", ".join(fields) or "(none)")
        if DRY_RUN:
            print("  ", json.dumps(fields, ensure_ascii=False)[:400])
            continue
        if fields and post_enrich(slug, fields):
            state[slug] = {"status": "ok"}
        elif not fields:
            state[slug] = {"status": "ok"}
        else:
            st = state.get(slug, {}); state[slug] = {"status": "fail", "tries": st.get("tries", 0) + 1}
        time.sleep(1.5)

    if not DRY_RUN:
        save_state(state)
    print(f"[enrich_backfill] processed {done}")


if __name__ == "__main__":
    main()
