# Job Scraper

Python scraper for finding roles across a large company list, exporting them to Excel, and optionally sending an email digest when new jobs appear.

## What It Does

- Loads companies from `data/companies.txt`
- Detects each company’s hiring platform
- Fetches jobs from supported ATS providers:
  - Greenhouse
  - Lever
  - Ashby
  - Workday
  - SmartRecruiters
  - iCIMS
- Falls back to:
  - search-based discovery via Tavily, Bing, or DuckDuckGo
  - Adzuna when no ATS is found and Adzuna credentials are configured
  - Playwright scraping for generic careers pages when enabled
- Filters for likely entry-level or strong skill-match roles
- Filters out obvious non-US postings
- Deduplicates against existing exported jobs
- Scores and sorts jobs by relevance
- Writes everything to `output/entry_roles.xlsx`
- Optionally emails a daily summary through Resend

## Repo Layout

```text
.
├── main.py                   # main scraper entry point
├── mark_applied.py           # track jobs you've already applied to
├── requirements.txt
├── data/
│   ├── companies.txt
│   ├── discovered_boards.json
│   ├── emailed_urls.json
│   └── last_summary_date.txt
├── output/
│   └── entry_roles.xlsx
└── src/
    ├── discovery.py
    ├── filters.py
    ├── scoring.py
    ├── io_export.py
    ├── notifier.py
    └── ats_*.py
```

## Requirements

- Python 3.11 recommended
- `pip`
- Optional: Playwright + Chromium for careers-page scraping fallback

Install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Optional Playwright setup:

```bash
pip install playwright
playwright install chromium
```

## Configuration

Create a `.env` file in the repo root if you want search APIs, Adzuna fallback, or email notifications:

```env
TAVILY_API_KEY=
BING_API_KEY=
ADZUNA_APP_ID=
ADZUNA_APP_KEY=
RESEND_API_KEY=
NOTIFY_EMAIL=
```

Notes:

- `TAVILY_API_KEY` enables Tavily for search-based ATS discovery.
- `BING_API_KEY` is used only if Tavily is not configured.
- With neither key set, the scraper falls back to DuckDuckGo HTML search.
- `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` enable Adzuna fallback when ATS discovery fails.
- `RESEND_API_KEY` and `NOTIFY_EMAIL` enable email digests.

## Company Input

Put one company name per line in `data/companies.txt`, for example:

```text
MICROSOFT CORPORATION
GOOGLE LLC
NVIDIA CORPORATION
```

Blank lines are ignored. Duplicate company names are skipped automatically.

## Usage

Basic run:

```bash
python main.py
```

Common options:

```bash
python main.py --max-companies 100
python main.py --concurrency 20
python main.py --refresh-discovery
python main.py --no-search-fallback
python main.py --playwright
python main.py --notify-email
python main.py --max-age-hours 0
python main.py --out output/entry_roles.xlsx
```

### CLI Flags

- `--max-companies`: limit how many companies are processed
- `--concurrency`: number of companies processed in parallel, default `10`
- `--out`: Excel output path, default `output/entry_roles.xlsx`
- `--refresh-discovery`: ignore cached ATS discovery results
- `--no-search-fallback`: disable search-based ATS discovery
- `--playwright`: enable Playwright fallback for generic careers pages
- `--notify-email`: send email digest for newly found jobs
- `--max-age-hours`: skip recently fetched companies, default `4.0`; set `0` to always refetch

## Output

The scraper writes all jobs to `output/entry_roles.xlsx`.

Excel columns:

- `company_name`
- `job_title`
- `location`
- `url`
- `date_posted`
- `score`
- `source`

The file is grouped by posting date and includes hyperlinks for job URLs.

## Filtering and Scoring

The scraper keeps jobs that look like entry-level SWE roles or strong skill-based matches.

It filters based on:

- software-engineering title keywords
- seniority exclusion (`senior`, `staff`, `lead`, `manager`, etc.)
- experience requirements in the description
- US location heuristics
- technical skill tokens for adjacent roles such as analyst or data/platform roles

Jobs are scored from `0-100` using:

- skill match
- role/title relevance
- entry-level signals
- posting recency

## Applied Job Tracking

Use `mark_applied.py` to track jobs you’ve already applied to so they are excluded from future email digests.

Examples:

```bash
python mark_applied.py "https://boards.greenhouse.io/company/jobs/123456"
python mark_applied.py --list
python mark_applied.py --remove "https://boards.greenhouse.io/company/jobs/123456"
```

Tracked data is stored in `data/applied_jobs.json`.

## Apply Queue

This repo also includes the first layer for a future supervised apply agent.

Build an application queue from exported jobs:

```bash
python scripts/build_apply_queue.py
python scripts/build_apply_queue.py --include-interesting
python scripts/queue_summary.py
python scripts/run_greenhouse_apply.py
python scripts/fill_greenhouse_form.py
```

Files:

- `data/apply_queue.json`: queued jobs for later application work
- `data/applicant_profile.template.json`: profile template for reusable application answers

Details are in `docs/APPLY_AGENT_SETUP.md`.

## Automation

This repo includes a GitHub Actions workflow at `.github/workflows/scraper.yml` that:

- runs hourly during the configured daytime/evening ET window
- supports manual runs through `workflow_dispatch`
- installs dependencies
- creates a `.env` file from GitHub Actions secrets
- runs the scraper with email notifications enabled
- commits updated cache and Excel artifacts back to the repo

Required GitHub secrets for the workflow depend on which integrations you want active:

- `TAVILY_API_KEY`
- `ADZUNA_APP_ID`
- `ADZUNA_APP_KEY`
- `RESEND_API_KEY`
- `NOTIFY_EMAIL`

## VPS Deployment

If you want the scraper to run even when your laptop is off, use a small VPS and cron instead of relying on GitHub Actions.

The repo now includes a cron-safe wrapper script:

```bash
./scripts/run_scraper.sh
```

Full setup instructions are in `docs/VPS_CRON_SETUP.md`.

Recommended cron entry:

```cron
CRON_TZ=America/New_York
0 8-20 * * * /bin/bash /home/<your-user>/srx-ent-role-xf-main/scripts/run_scraper.sh
```

That runs hourly from `8:00 AM` through `8:00 PM` Eastern and skips the `9:00 PM` to `8:00 AM` window.

## Data Files

- `data/discovered_boards.json`: ATS discovery cache
- `data/emailed_urls.json`: URLs already sent in email digests
- `data/last_summary_date.txt`: prevents duplicate no-new-jobs daily emails
- `data/applied_jobs.json`: jobs marked as applied

## Notes

- The scraper is designed around US-based entry-level SWE searches.
- Search-based discovery and public job APIs can be rate-limited or change behavior over time.
- Playwright is optional and only used when explicitly enabled.
