# Bharat Vacancy - Government Job Scraper

Scrapes government job notifications from official portals and posts them directly to
bharatvacancy.com's ingest API. Runs on GitHub Actions every 15 minutes.

## How it works

1. Each `*_scraper.py` fetches its portal's notice page(s) as raw text.
2. `extract_jobs_ai.py` sends that text to Claude (Haiku 4.5) with a fixed JSON schema,
   which pulls out structured job listings — this replaces hand-written CSS selectors,
   so a portal redesigning its markup doesn't silently break extraction the way it did
   before.
3. `ingest_client.py` POSTs the results to `https://bharatvacancy.com/ingest.php`, which
   dedupes and inserts new listings into the site's database directly. No CSV files, no
   WordPress import plugin, no intermediate commit-to-repo step.

Add a new portal by copying `_template.py`-style structure from an existing
`*_scraper.py`, adjusting the portal name and URL(s) — the workflow auto-discovers any
file matching `*_scraper.py`, no registration step needed.

## Required secrets

Set these under repo **Settings → Secrets and variables → Actions**:

| Secret | Purpose |
|---|---|
| `INGEST_API_KEY` | Shared secret `ingest.php` checks — must match `INGEST_API_KEY` in the site's `config.php` |
| `ANTHROPIC_API_KEY` | Used by `extract_jobs_ai.py` for structured extraction |

## Run locally

```bash
git clone git@github.com:SAURABH-bharat-vacancy/bharatvacancy-scraper.git
cd bharatvacancy-scraper
pip install -r requirements.txt
export INGEST_API_KEY=...
export ANTHROPIC_API_KEY=...
python ibps_scraper.py
```

## Files

- `ibps_scraper.py`, `ssc_scraper.py` — one file per portal
- `extract_jobs_ai.py` — shared AI extraction logic
- `ingest_client.py` — shared HTTP client that posts to `ingest.php`
- `.github/workflows/scrape-jobs.yml` — runs every scraper every 15 minutes

## Status

Check the **Actions** tab for run history, or query `ingest_log` in the site's database
for a per-run summary (jobs received/inserted/duplicate, and any errors) — a scraper
that's silently broken shows up there instead of just going stale.

## Support

Visit: https://bharatvacancy.com
