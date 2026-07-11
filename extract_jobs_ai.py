"""AI-assisted extraction: turns a portal's raw notice-page text into structured job
listings. This replaces hand-written CSS selectors — a portal redesigning its markup
doesn't break this the way it broke selector-based scraping before.

Uses Haiku 4.5: this is a bounded, well-specified extraction task (not open-ended
reasoning), so the cheapest capable model is the right cost/quality tradeoff here.
"""
import json
from anthropic import Anthropic

client = Anthropic()  # reads ANTHROPIC_API_KEY from env

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "jobs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "organization": {"type": "string"},
                    "category": {
                        "type": "string",
                        "enum": ["Banking", "SSC", "Railways", "Defence", "Police", "State", "PSU", "General"],
                    },
                    "location": {"type": "string"},
                    "employment_type": {
                        "type": "string",
                        "enum": ["Permanent", "Contract", "Temporary", "Part Time"],
                    },
                    "source_url": {"type": "string"},
                    "pdf_url": {"type": "string"},
                    "vacancy_count": {"type": "string"},
                    "description": {"type": "string"},
                    "min_qualification": {"type": "string"},
                    "age_limit": {"type": "string"},
                    "application_fee": {"type": "string"},
                    "pay_scale": {"type": "string"},
                    "selection_process": {"type": "string"},
                    "how_to_apply": {"type": "string"},
                    "posted_date": {"type": "string"},
                    "apply_last_date": {"type": "string"},
                },
                "required": ["title", "organization", "source_url"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["jobs"],
    "additionalProperties": False,
}


def extract_jobs(page_text: str, portal_name: str, page_url: str) -> list[dict]:
    """Ask Claude to pull every distinct job/exam notification out of raw page text.

    Returns [] on no notifications found OR on any extraction failure — callers should
    treat an empty list as "nothing new this run", not necessarily an error, and rely on
    the ingest_log table (populated by ingest.php) to notice a portal that's gone
    persistently quiet.
    """
    prompt = f"""Here is the raw text of the "{portal_name}" recruitment notices page ({page_url}).

Extract every distinct job/exam notification listed. For each one:
- title: the notification/exam name, as written on the page
- organization: usually "{portal_name}" unless the text names a more specific body
- source_url: the direct link to that specific notification if present in the text, otherwise use {page_url}
- pdf_url: a direct link to the notification PDF/advertisement document, if one is present in the text — omit if not found, don't guess
- vacancy_count: total number of vacancies as stated (e.g. "4187" or "500+" or "Various") — omit if not stated
- category: your best guess from the fixed category list
- employment_type: default to "Permanent" for government recruitment unless the text says otherwise
- min_qualification: the minimum educational qualification required, as stated (e.g. "Bachelor's degree in any discipline", "12th pass") — omit if not stated
- age_limit: the age eligibility as stated, including the reference date if given (e.g. "18-27 years as on 01-01-2026") — omit if not stated
- application_fee: the application fee, including category-wise variation if stated (e.g. "₹100 General/OBC, Exempted for SC/ST/PwD/Women") — omit if not stated
- pay_scale: the pay scale/salary as stated (e.g. "Level 4, ₹25,500 - ₹81,100") — omit if not stated
- selection_process: a brief description of the selection stages (e.g. "Written Exam, Physical Test, Document Verification") — omit if not stated
- how_to_apply: a brief summary of how to apply (e.g. "Apply online via the official website") — omit if not stated
- posted_date / apply_last_date: only if explicitly stated in the text, formatted YYYY-MM-DD — omit the field entirely if not stated, don't guess

For every field above marked "omit if not stated" or "omit if not found": only include it when the source text actually states it. Never invent, estimate, or guess a value — an omitted field is far better than a wrong one.

Ignore navigation links, footers, ads, and anything that is not an actual job/exam notification. If there are no notifications on this page, return an empty jobs list.

PAGE TEXT:
{page_text[:60000]}
"""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=8192,
            output_config={"format": {"type": "json_schema", "schema": EXTRACTION_SCHEMA}},
            messages=[{"role": "user", "content": prompt}],
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
                return json.loads(block.text)["jobs"]
            except (json.JSONDecodeError, KeyError) as e:
                print(f"[extract_jobs_ai] failed to parse response for {portal_name}: {e}")
                return []

    return []
