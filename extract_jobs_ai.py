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
import re
from anthropic import Anthropic

client = Anthropic()  # reads ANTHROPIC_API_KEY from env

CATEGORIES = ["Banking", "SSC", "Railways", "Defence", "Police", "State", "General"]
EMPLOYMENT_TYPES = ["Permanent", "Contract", "Temporary", "Part Time"]


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
    prompt = f"""Here is the raw text of the "{portal_name}" recruitment notices page ({page_url}).

Extract every distinct job/exam notification listed. For each one, include these fields when known:
- title: the notification/exam name, as written on the page
- organization: usually "{portal_name}" unless the text names a more specific body
- source_url: the direct link to that specific notification if present in the text, otherwise use {page_url}
- pdf_url: a direct link to the notification PDF/advertisement document, if one is present in the text — omit if not found, don't guess
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

Ignore navigation links, footers, ads, and anything that is not an actual job/exam notification.

Respond with ONLY a single JSON object of the exact form {{"jobs": [...]}} — no markdown code fences, no commentary before or after. If there are no notifications on this page, respond with {{"jobs": []}}.

PAGE TEXT:
{page_text[:60000]}
"""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
            timeout=60.0,
        )
    except Exception as e:
        print(f"[extract_jobs_ai] API call failed for {portal_name}: {e}")
        return []

    if response.stop_reason == "refusal":
        print(f"[extract_jobs_ai] extraction refused for {portal_name}")
        return []

    for block in response.content:
        if block.type == "text":
            try:
                return _parse_jobs_json(block.text)
            except (json.JSONDecodeError, KeyError, IndexError) as e:
                print(f"[extract_jobs_ai] failed to parse response for {portal_name}: {e}")
                return []

    return []
