#!/usr/bin/env python3
"""Entry-level SWE job scraper: discover ATS, fetch jobs, filter, export to Excel."""

import os
from pathlib import Path as _Path

# Load .env before any imports that read os.environ
_env_file = _Path(__file__).resolve().parent / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip("'\"")
            if key and val:
                os.environ.setdefault(key, val)

import argparse
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from src.ats_ashby import fetch_jobs as ashby_fetch_jobs
from src.ats_adzuna import fetch_jobs as adzuna_fetch_jobs, is_configured as adzuna_configured
from src.ats_greenhouse import fetch_jobs as greenhouse_fetch_jobs
from src.ats_lever import fetch_jobs as lever_fetch_jobs
from src.ats_playwright import shutdown_browser
from src.ats_smartrecruiters import fetch_jobs as smartrecruiters_fetch_jobs
from src.ats_workday import fetch_jobs as workday_fetch_jobs
from src.discovery import discover_ats, load_cache, save_cache
from src.filters import is_entry_level_swe, is_skill_match, is_us_location
from src.io_export import export_to_excel, load_existing_jobs
from src.notifier import send_new_jobs_email
from src.search import get_search_client

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

COMPANIES_PATH = Path("data/companies.txt")
DEFAULT_OUT = "output/entry_roles.xlsx"


def load_companies(path: str) -> list[str]:
    """Read company names, skip blank lines and the EMPLOYER_NAME header."""
    companies: list[str] = []
    if not Path(path).exists():
        logger.error("Companies file not found: %s", path)
        return companies
    seen: set[str] = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            name = line.strip()
            if not name or name.upper() == "EMPLOYER_NAME":
                continue
            key = name.upper()
            if key in seen:
                continue          # skip duplicates
            seen.add(key)
            companies.append(name)
    return companies


def _fetch_jobs_for_board(company: str, ats: str, key: str, board: dict) -> list[dict]:
    if ats == "greenhouse":
        return greenhouse_fetch_jobs(company, key)
    elif ats == "lever":
        return lever_fetch_jobs(company, key)
    elif ats == "ashby":
        return ashby_fetch_jobs(company, key)
    elif ats == "workday":
        return workday_fetch_jobs(company, key)
    elif ats == "smartrecruiters":
        return smartrecruiters_fetch_jobs(company, key)
    elif ats == "careers_page":
        return board.get("jobs", [])
    return []


def _is_recently_fetched(board: dict, max_age_hours: float) -> bool:
    """Return True if jobs were fetched for this company within max_age_hours."""
    last = board.get("last_fetched")
    if not last:
        return False
    return (time.time() - last) < max_age_hours * 3600


def _process_company(
    company: str,
    client,
    cache: dict,
    cache_lock: threading.Lock,
    refresh: bool,
    use_search_fallback: bool,
    use_playwright: bool = False,
    max_age_hours: float = 4.0,
) -> list[dict]:
    """Discover ATS, fetch jobs, and filter — returns matching jobs."""
    # Check cache first (thread-safe read)
    with cache_lock:
        if not refresh and company in cache:
            board = cache[company]
        else:
            board = None

    # Skip companies fetched very recently — saves time on frequent runs
    if not refresh and board and _is_recently_fetched(board, max_age_hours):
        logger.debug("[SKIP] %s fetched recently — skipping", company)
        return []

    # Re-discover if: no cache, or cached as careers_page (needs Playwright re-scrape)
    if board is None or (board.get("ats") == "careers_page" and use_playwright):
        board = discover_ats(
            company, client,
            use_search_fallback=use_search_fallback,
            use_playwright=use_playwright,
        )
        # Cache without the 'jobs' payload so cached entries stay small
        board_to_cache = {k: v for k, v in board.items() if k != "jobs"}
        with cache_lock:
            cache[company] = board_to_cache
            save_cache(cache)

    ats, key = board.get("ats"), board.get("key")
    if not ats or not key:
        # No ATS discovered — fall back to Adzuna job-search API if configured
        if adzuna_configured():
            logger.info("[ADZUNA] No ATS found for %s — searching Adzuna", company)
            jobs = adzuna_fetch_jobs(company)
            logger.info("[%s] Adzuna returned %d jobs", company, len(jobs))
            passed = [
                j for j in jobs
                if (is_entry_level_swe(j)[0] or is_skill_match(j)[0]) and is_us_location(j)
            ]
            # Stamp last_fetched so this company is skipped next time
            with cache_lock:
                cache.setdefault(company, {})["last_fetched"] = time.time()
                save_cache(cache)
            logger.info("[%s] %d passed filter (adzuna)", company, len(passed))
            return passed
        logger.info("[SKIP] No ATS found for %s", company)
        return []

    logger.info("[FOUND] %s → %s / %s", company, ats, key)
    jobs = _fetch_jobs_for_board(company, ats, key, board)
    logger.info("[%s] Fetched %d jobs", company, len(jobs))
    passed = [
        j for j in jobs
        if (is_entry_level_swe(j)[0] or is_skill_match(j)[0]) and is_us_location(j)
    ]
    # Stamp last_fetched so this company is skipped on the next frequent run
    with cache_lock:
        cache.setdefault(company, {}).update({"ats": ats, "key": key, "last_fetched": time.time()})
        save_cache(cache)
    logger.info("[%s] %d passed filter", company, len(passed))
    return passed


def main() -> None:
    parser = argparse.ArgumentParser(description="Entry-level SWE job scraper")
    parser.add_argument("--max-companies", type=int, default=None,
                        help="Cap the number of companies processed")
    parser.add_argument("--concurrency", type=int, default=10,
                        help="Number of companies to probe in parallel (default: 10)")
    parser.add_argument("--out", type=str, default=DEFAULT_OUT)
    parser.add_argument("--refresh-discovery", action="store_true",
                        help="Ignore the discovery cache and re-probe every company")
    parser.add_argument(
        "--no-search-fallback",
        action="store_true",
        help="Disable search-based ATS discovery (enabled by default). "
             "Uses TAVILY_API_KEY when available.",
    )
    parser.add_argument(
        "--playwright",
        action="store_true",
        help="Enable Playwright-based fallback scraping for companies with no known ATS. "
             "Requires: pip install playwright && playwright install chromium",
    )
    parser.add_argument(
        "--notify-email",
        action="store_true",
        help="Send an email digest when new jobs are found. "
             "Requires RESEND_API_KEY and NOTIFY_EMAIL in .env",
    )
    parser.add_argument(
        "--max-age-hours", type=float, default=4.0,
        help="Skip companies whose jobs were fetched within this many hours (default: 4). "
             "Set to 0 to always re-fetch every company.",
    )
    args = parser.parse_args()

    companies = load_companies(str(COMPANIES_PATH))
    if args.max_companies is not None:
        companies = companies[: args.max_companies]
    if not companies:
        logger.info("No companies to process")
        return

    os.makedirs("data", exist_ok=True)
    os.makedirs("output", exist_ok=True)

    client = get_search_client()
    cache = load_cache()
    cache_lock = threading.Lock()

    # Load jobs already saved in the output file so we can deduplicate
    existing_jobs = load_existing_jobs(args.out)
    seen_urls: set[str] = {j.get("url", "") for j in existing_jobs if j.get("url")}
    logger.info("Loaded %d existing jobs from %s (will skip duplicates)",
                len(existing_jobs), args.out)

    new_jobs: list[dict] = []

    logger.info("Processing %d companies (concurrency=%d)…",
                len(companies), args.concurrency)

    try:
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures = {
                pool.submit(
                    _process_company,
                    company, client, cache, cache_lock,
                    args.refresh_discovery,
                    not args.no_search_fallback,   # search-fallback on by default
                    args.playwright,
                    args.max_age_hours,
                ): company
                for company in companies
            }
            for future in as_completed(futures):
                company = futures[future]
                try:
                    jobs = future.result()
                    for job in jobs:
                        url = job.get("url", "")
                        if url and url in seen_urls:
                            continue          # already in Excel — skip
                        seen_urls.add(url)
                        new_jobs.append(job)
                except Exception as exc:
                    logger.warning("[ERROR] %s raised %s", company, exc)
    except KeyboardInterrupt:
        logger.info("\n[INTERRUPTED] Saving %d jobs collected so far…", len(new_jobs))
    finally:
        shutdown_browser()

    # Write existing + new jobs together so the file is always complete
    all_jobs = existing_jobs + new_jobs
    export_to_excel(all_jobs, args.out)
    print(f"\nDone. {len(new_jobs)} new jobs added → {len(all_jobs)} total in {args.out}")

    # Email digest — only fires when --notify-email is set and new jobs were found
    if args.notify_email and new_jobs:
        send_new_jobs_email(new_jobs, len(all_jobs), args.out)


if __name__ == "__main__":
    main()
