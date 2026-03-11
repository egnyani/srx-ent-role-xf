# VPS + Cron Setup

This repo can run on a small Linux VPS without GitHub Actions. The simplest model is:

- keep the repo checked out on the VPS
- create a Python virtualenv in the repo
- store API keys in the repo’s `.env`
- call `scripts/run_scraper.sh` from cron

## 1. Provision the VPS

Any always-on Ubuntu or Debian VPS is fine. A small instance is enough for this job.

Install base packages:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git
```

Optional, only if you plan to use `--playwright` later:

```bash
sudo apt install -y libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2
```

## 2. Copy the repo to the VPS

Example:

```bash
git clone <your-repo-url> ~/srx-ent-role-xf-main
cd ~/srx-ent-role-xf-main
```

## 3. Create the virtualenv

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

Optional Playwright install:

```bash
.venv/bin/pip install playwright
.venv/bin/playwright install chromium
```

## 4. Add the environment file

Create `.env` in the repo root:

```env
TAVILY_API_KEY=
BING_API_KEY=
ADZUNA_APP_ID=
ADZUNA_APP_KEY=
RESEND_API_KEY=
NOTIFY_EMAIL=
```

`main.py` already loads this file automatically when run from the repo.

## 5. Test the wrapper script

```bash
chmod +x scripts/run_scraper.sh
./scripts/run_scraper.sh
tail -n 50 logs/scraper.log
```

## 6. Add the cron schedule

Open the crontab:

```bash
crontab -e
```

Use this entry to run every hour from 8:00 AM through 8:00 PM New York time:

```cron
CRON_TZ=America/New_York
0 8-20 * * * /bin/bash /home/<your-user>/srx-ent-role-xf-main/scripts/run_scraper.sh
```

That schedule runs at:

- `08:00`
- `09:00`
- ...
- `20:00`

It does not run between `9:00 PM` and `7:59 AM`.

## 7. Persistence notes

This repo stores runtime state locally on disk:

- `data/discovered_boards.json`
- `data/emailed_urls.json`
- `data/last_summary_date.txt`
- `data/applied_jobs.json`
- `output/entry_roles.xlsx`

That works well on a VPS because the filesystem persists across cron runs.

## 8. Recommended hardening

- Use a dedicated non-root user for the job.
- Back up the `data/` and `output/` directories.
- Rotate or truncate `logs/scraper.log` occasionally.
- If email delivery matters, test `RESEND_API_KEY` and `NOTIFY_EMAIL` with a manual run first.

## Why This Is Better Than GitHub Actions For Your Case

- It keeps running when your laptop is off.
- Cron handles the local time window directly.
- The repo’s cache and Excel output stay on one persistent machine.
- You avoid GitHub Actions schedule jitter and branch/default-branch quirks.
