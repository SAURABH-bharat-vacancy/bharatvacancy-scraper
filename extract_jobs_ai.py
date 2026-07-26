"""AI-assisted extraction: turns a portal's raw notice-page text into structured job
listings. This replaces hand-written CSS selectors — a portal redesigning its markup
doesn't break this the way it broke selector-based scraping before.

Uses Haiku 4.5: this is a bounded, well-specified extraction task (not open-ended
reasoning), so the cheapest capable model is the right cost/quality tradeoff here.

NOTE: this used to use the Messages API's output_config json_schema feature for
guaranteed-valid-JSON output. That started failing every call with a 400
"Schema is too complex" error (confirmed reproducible even after trimming the
schema back down, so it wasn't a size/enum-count issue on our end — something
about that feature's validator). Switched to plain prompt-based JSON generation
with manual parsing instead, which sidesteps that feature entirely. Slightly
less strict than schema-enforced output, but the parsing below is defensive
about the common failure modes (markdown code fences, leading/trailing prose).
"""
import json
import os
import re
import urllib.request
import urllib.error
from anthropic import Anthropic

client = Anthropic()  # reads ANTHROPIC_API_KEY from env

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = "llama-3.3-70b-versatile"

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
# Model name matters a lot for this specific key — several otherwise-current
# names return 404 ("no longer available to new users") or 429 (zero quota).
# "gemini-flash-latest" is the one confirmed working; re-verify with
# bharatvacancy/_debug_google.php before changing this.
GOOGLE_MODEL = "gemini-flash-latest"

CATEGORIES = ["Banking", "SSC", "Railways", "Defence", "Police", "State", "General"]
EMPLOYMENT_TYPES = ["Permanent", "Contract", "Temporary", "Part Time"]


def _call_anthropic(prompt: str) -> str | None:
    """Returns None (never raises) on any failure so _call_llm_extract() can
    fall through to Groq instead of aborting extraction outright."""
    try:
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
            timeout=60.0,
        )
    except Exception as e:
        print(f"[extract_jobs_ai] Anthropic call failed: {e}")
        return None

    if response.stop_reason == "refusal":
        return None

    for block in response.content:
        if block.type == "text":
            return block.text
    return None


def _call_groq(prompt: str) -> str | None:
    """Fallback path: same prompt, OpenAI-compatible chat-completions shape.
    Only reached when Anthropic itself failed — see _call_llm_extract()."""
    if not GROQ_API_KEY:
        return None

    body = json.dumps({
        "model": GROQ_MODEL,
        "max_tokens": 8192,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {GROQ_API_KEY}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, KeyError, ValueError) as e:
        print(f"[extract_jobs_ai] Groq fallback call failed: {e}")
        return None


def _call_gemini(prompt: str) -> str | None:
    """Third fallback tier. Gemini's own response shape
    (candidates[0].content.parts[0].text) and auth (?key= query param, not
    a bearer header) - different from both Anthropic and Groq's shapes."""
    if not GOOGLE_API_KEY:
        return None

    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 8192},
    }).encode("utf-8")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GOOGLE_MODEL}:generateContent?key={GOOGLE_API_KEY}"
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, KeyError, IndexError, ValueError) as e:
        print(f"[extract_jobs_ai] Gemini fallback call failed: {e}")
        return None


def _call_llm_extract(prompt: str) -> str | None:
    """Tries Anthropic, then Groq, then Gemini — each only called if every
    prior tier failed outright (down, rate-limited, or credit balance
    exhausted). Never silently prefers a free tier when the primary is
    healthy."""
    text = _call_anthropic(prompt)
    if text is not None:
        return text

    print("[extract_jobs_ai] Anthropic call failed, falling back to Groq")
    text = _call_groq(prompt)
    if text is not None:
        return text

    print("[extract_jobs_ai] Groq call failed, falling back to Gemini")
    return _call_gemini(prompt)


def _recover_partial_jobs(text: str) -> list[dict]:
    """When a portal's page has enough distinct notices, the model's JSON
    response can get cut off mid-generation by hitting max_tokens before it
    finishes the array. Rather than discard the whole response, walk the
    "jobs" array with a brace-depth scanner and keep every object that's
    actually complete; only the last, truncated one gets dropped.
    """
    arr_start = text.find("[")
    if arr_start == -1:
        return []

    jobs = []
    i = arr_start + 1
    n = len(text)

    while i < n:
        while i < n and (text[i].isspace() or text[i] == ","):
            i += 1
        if i >= n or text[i] != "{":
            break

        obj_start = i
        depth = 0
        in_string = False
        escaped = False
        closed = False

        while i < n:
            ch = text[i]
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = not in_string
            elif not in_string:
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        i += 1
                        closed = True
                        break
            i += 1

        if not closed:
            break  # ran off the end mid-object — this is the truncated one, stop here

        try:
            jobs.append(json.loads(text[obj_start:i]))
        except json.JSONDecodeError:
            pass

    return jobs


def _parse_jobs_json(text: str) -> list[dict]:
    text = text.strip()
    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    else:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1:
            text = text[start:end + 1]

    try:
        data = json.loads(text)
        return data["jobs"]
    except (json.JSONDecodeError, KeyError):
        recovered = _recover_partial_jobs(text)
        if recovered:
            return recovered
        raise


def extract_jobs(page_text: str, portal_name: str, page_url: str) -> list[dict]:
    """Ask Claude to pull every distinct job/exam notification out of raw page text.

    Returns [] on no notifications found OR on any extraction failure — callers should
    treat an empty list as "nothing new this run", not necessarily an error, and rely on
    the ingest_log table (populated by ingest.php) to notice a portal that's gone
    persistently quiet.
    """
    prompt = f"""Here is the raw text of the "{portal_name}" notices page ({page_url}). Links found on the page are inlined right after their link text in square brackets, e.g. "Download Advertisement [https://example.gov.in/notice.pdf]" — use these bracketed URLs as the source of source_url and pdf_url values; don't guess a URL that isn't backed by one of these brackets.

Extract every distinct notification listed — this includes not just fresh vacancy/recruitment ads, but also exam results, merit lists, admit cards/hall tickets, and answer keys. A "marks and rank position published" or "result declared" announcement is just as much a notification to extract as a new job opening — don't skip it just because it isn't a vacancy. If a single link or line covers two or more distinct notices bundled together (e.g. "Advt. No. 048/2023 ... & Advt. No. 049/2023 ..."), split them into separate entries rather than one combined one — each should stand on its own with its own title. For each one, include these fields when known:
- title: the notification/exam name, as written on the page but trimmed to the essential identifying part — drop redundant boilerplate the source repeats across every listing on the page (e.g. a shared department name already captured in "organization"). Keep it under roughly 100 characters where possible without dropping information a reader needs to tell this notice apart from similar ones.
- organization: usually "{portal_name}" unless the text names a more specific body
- description: 1-3 sentences of real context about this specific notification, drawn only from text on the page near it (not the title restated, not invented) — e.g. what the post is for, why it was issued, who it affects. Omit entirely if the page has nothing beyond the title for this notification; never pad with generic filler.
- source_url: the bracketed link immediately after that notification's title/heading if present, otherwise use {page_url}
- pdf_url: the bracketed link for the notification PDF/advertisement document (usually near text like "Download", "Advertisement", "Notification", "Click here") if present — omit if not found, don't guess
- vacancy_count: total number of vacancies as stated (e.g. "4187" or "500+" or "Various") — omit if not stated
- category: one of exactly {CATEGORIES}
- employment_type: one of exactly {EMPLOYMENT_TYPES} — default to "Permanent" for government recruitment unless the text says otherwise
- min_qualification: the minimum educational qualification required, as stated (e.g. "Bachelor's degree in any discipline", "12th pass") — omit if not stated
- age_limit: the age eligibility as stated, including the reference date if given (e.g. "18-27 years as on 01-01-2026") — omit if not stated
- application_fee: the application fee, including category-wise variation if stated (e.g. "₹100 General/OBC, Exempted for SC/ST/PwD/Women") — omit if not stated
- pay_scale: the pay scale/salary as stated (e.g. "Level 4, ₹25,500 - ₹81,100") — omit if not stated
- selection_process: a brief description of the selection stages (e.g. "Written Exam, Physical Test, Document Verification") — omit if not stated
- how_to_apply: a brief summary of how to apply (e.g. "Apply online via the official website") — omit if not stated
- posted_date / apply_last_date: only if explicitly stated in the text, formatted YYYY-MM-DD — omit the field entirely if not stated, don't guess

For every field marked "omit if not stated" or "omit if not found": only include it when the source text actually states it. Never invent, estimate, or guess a value — an omitted field is far better than a wrong one.

Ignore navigation links, footers, ads, and anything that isn't an actual notification (job, result, admit card, or answer key).

Respond with ONLY a single JSON object of the exact form {{"jobs": [...]}} — no markdown code fences, no commentary before or after. If there are no notifications on this page, respond with {{"jobs": []}}.

PAGE TEXT:
{page_text[:60000]}
"""

    text = _call_llm_extract(prompt)
    if text is None:
        print(f"[extract_jobs_ai] API call failed for {portal_name} (Anthropic and Groq both unavailable)")
        return []

    try:
        jobs = _parse_jobs_json(text)
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        print(f"[extract_jobs_ai] failed to parse response for {portal_name}: {e}")
        return []

    # source_url is required downstream, but the model doesn't reliably
    # follow the prompt's "fall back to the page URL" instruction once it's
    # already supplied a pdf_url for the same notification — confirmed
    # dropping entire portals' worth of jobs silently. Enforce the fallback
    # here instead of trusting compliance.
    for job in jobs:
        if not job.get("source_url"):
            job["source_url"] = page_url
    return jobs
