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
                        "enum": ["Banking", "SSC", "Railways", "Defence", "Police", "State", "General"],
                    },
                    "location": {"type": "string"},
                    "employment_type": {
                        "type": "string",
                        "enum": ["Permanent", "Contract", "Temporary", "Part Time"],
                    },
                    "source_url": {"type": "string"},
                    "description": {"type": "string"},
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
- category: your best guess from the fixed category list
- employment_type: default to "Permanent" for government recruitment unless the text says otherwise
- posted_date / apply_last_date: only if explicitly stated in the text, formatted YYYY-MM-DD — omit the field entirely if not stated, don't guess

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
