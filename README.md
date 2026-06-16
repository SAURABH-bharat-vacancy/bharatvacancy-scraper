# Bharat Vacancy - Government Job Scraper

Automatically scrapes government job notifications from official websites and posts them to bharatvacancy.com

## Features

✓ Automated daily job scraping
✓ Posts to WordPress automatically  
✓ Supports: SSC, Banking, Railways, Defence jobs
✓ Runs on GitHub Actions (free)
✓ No manual intervention needed

## Supported Sources

- SSC (Staff Selection Commission)
- IBPS (Institute of Banking Personnel Selection)
- SBI (State Bank of India)
- RRB (Railway Recruitment Board)
- NDA (National Defence Academy)

## Setup

### Installation

```bash
git clone https://github.com/yourusername/bharatvacancy-scraper.git
cd bharatvacancy-scraper
pip install -r requirements.txt
```

### Run Manually

```bash
python job_scraper.py
```

### Automatic Daily Runs

GitHub Actions runs the scraper automatically:
- **Time:** 6:00 AM IST daily
- **No setup needed** - Just push code and it runs!

## Files

- `job_scraper.py` - Main scraper script
- `requirements.txt` - Python dependencies
- `.github/workflows/scrape-jobs.yml` - Automation workflow
- `jobs_data.json` - Output file with scraped jobs

## Output

Creates `jobs_data.json` with job data:

```json
[
  {
    "title": "SSC CGL 2024",
    "url": "https://ssc.nic.in/...",
    "source": "SSC",
    "category": "SSC Jobs",
    "location": "All India",
    "posted_date": "2024-06-15",
    "type": "Permanent"
  }
]
```

## Status

✓ Last run: Check "Actions" tab
✓ Jobs found: Check `jobs_data.json`

## Support

Visit: https://bharatvacancy.com
