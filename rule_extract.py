"""Turns a fetched notice page into job rows without calling any AI model.

fetch_page_text() flattens a page to one line per element and appends every link's URL in
square brackets right after its text, e.g.

    Advertisement for the posts of Associate Consultants, Well Services [https://x.gov.in/a.pdf]
    12/10/2026 | Advt. No. 02/2026 recruitment notice [https://x.gov.in/n.html]

so most listing pages can be read with plain rules: a line that names a notice (recruitment,
advertisement, result, admit card and so on) and carries a link becomes one row. This gives
only a title, a link and a PDF address, which is also all the page itself offered; the
server's classifier then labels results, admit cards and the like from the title.

It is the fallback when the AI providers are rate limited, and it keeps the runner useful
without any API keys.
"""
import re

_URL = re.compile(r"\[(https?://[^\]\s]+)\]")
_KEYWORDS = re.compile(
    r"recruit|vacanc|advt|advertisement|notification|notice|posts? of|engagement|walk-?in|deputation|"
    r"apprentice|result|admit card|hall ticket|answer key|call letter|interview|selection|corrigendum|"
    r"examination|exam\b",
    re.I,
)
_NOISE_START = re.compile(r"^(home|contact|about|login|sitemap|skip to|click here|read more|view all|download|more)\b", re.I)
_PDF = re.compile(r"\.pdf(\?|#|$)", re.I)

MAX_JOBS_PER_PAGE = 40


def _clean_title(text: str) -> str:
    text = _URL.sub("", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"^[\s|:;,.\-]+|[\s|:;,.\-]+$", "", text)
    text = re.sub(r"\s*\|\s*", " | ", text)
    # Date or "new" badges at the very start add nothing to the title.
    text = re.sub(r"^(new\b[\s:!-]*)", "", text, flags=re.I)
    return text.strip()


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_PREFIXES = [
    (re.compile(r"^posting date\s*:?\s*(\d{4})-(\d{2})-(\d{2})\s*", re.I), "ymd"),
    (re.compile(r"^(\d{1,2})\s+([A-Za-z]{3})[a-z]*\.?,?\s+(20\d{2})\s*[-:|]?\s*"), "dmony"),
    (re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](20\d{2})\s*[-:|]?\s*"), "dmy"),
]
_FILLER_PREFIX = re.compile(r"^(update as on\s+[\d./-]+\s*[-:]?\s*|\d{1,2}\s*\|\s*)", re.I)


def _split_prefix(title: str) -> tuple[str, str | None]:
    """A date at the very start of a listing line is the date it was posted: use it as
    posted_date and drop it (and index numbers, "UPDATE AS ON ...") from the title."""
    posted = None
    title = _FILLER_PREFIX.sub("", title).strip()
    for pattern, kind in _PREFIXES:
        m = pattern.match(title)
        if not m:
            continue
        try:
            if kind == "ymd":
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            elif kind == "dmony":
                d, mo, y = int(m.group(1)), _MONTHS.get(m.group(2).lower()[:3], 0), int(m.group(3))
            else:
                d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        except ValueError:
            break
        if 1 <= d <= 31 and 1 <= mo <= 12:
            posted = f"{y:04d}-{mo:02d}-{d:02d}"
            title = title[m.end():].strip()
        break
    return title, posted


_LINK_SEGMENT = re.compile(r"([^\[\]]*?)\s*\[(https?://[^\]\s]+)\]")


def rule_based_jobs(lines: list[str], page_url: str) -> list[dict]:
    """Each link's own text is the text between the previous link and it. Adjacent links are
    often merged onto one very long line, so lines are split at the bracketed URLs.
    """
    jobs: list[dict] = []
    seen_titles: set[str] = set()
    pending_title: str | None = None  # a notice line whose link sits on the next line

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        segments = _LINK_SEGMENT.findall(line)

        if not segments:
            # A heading or notice with no link of its own: the link may be on the next line.
            text = _clean_title(line)
            pending_title = text if (20 <= len(text) <= 220 and _KEYWORDS.search(text)) else None
            continue

        for seg_text, url in segments:
            text = _clean_title(seg_text)
            title = pending_title if (len(text) < 20 and pending_title) else text
            pending_title = None
            title, posted = _split_prefix(title)

            # Menu links ("Recruitment Advertisements") are short; real notices either point at a
            # PDF or are written out in a full line.
            is_notice = (
                20 <= len(title) <= 220
                and not _NOISE_START.match(title)
                and _KEYWORDS.search(title)
                and (_PDF.search(url) or len(title.split()) >= 6)
            )
            if not is_notice:
                # "Advertisement (English)" style links: attach the PDF to the notice just before.
                if jobs and _PDF.search(url) and "pdf_url" not in jobs[-1]:
                    jobs[-1]["pdf_url"] = url
                continue

            key = re.sub(r"\W+", " ", title.lower()).strip()
            if key in seen_titles:
                continue
            seen_titles.add(key)

            job = {"title": title[:200], "source_url": url or page_url}
            if _PDF.search(url):
                job["pdf_url"] = url
            if posted:
                job["posted_date"] = posted  # only a date at the very start of the line, see _split_prefix
            jobs.append(job)
            if len(jobs) >= MAX_JOBS_PER_PAGE:
                return jobs
    return jobs
