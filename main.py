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
from collections import Counter
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from src.ats_ashby import fetch_jobs as ashby_fetch_jobs
from src.ats_adzuna import fetch_jobs as adzuna_fetch_jobs, is_configured as adzuna_configured
from src.ats_greenhouse import fetch_jobs as greenhouse_fetch_jobs
from src.ats_icims import fetch_jobs as icims_fetch_jobs
from src.ats_lever import fetch_jobs as lever_fetch_jobs
from src.ats_playwright import shutdown_browser
from src.ats_simplify_newgrad import fetch_jobs as simplify_newgrad_fetch_jobs
from src.ats_smartrecruiters import fetch_jobs as smartrecruiters_fetch_jobs
from src.ats_workday import fetch_jobs as workday_fetch_jobs
from src.dedup import deduplicate, job_fingerprint
from src.discovery import discover_ats, load_cache, save_cache
from src.filters import classify_job
from src.io_export import export_to_excel, load_existing_jobs
from src.notifier import send_new_jobs_email, send_no_new_jobs_email
from src.scoring import score_and_sort
from src.search import get_search_client

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

COMPANIES_PATH = Path("data/companies.txt")
DEFAULT_OUT = "output/entry_roles.xlsx"
DEFAULT_INTERESTING_OUT = "output/interesting_roles.xlsx"
COMPANY_ALIASES = {
    "AMAZON COM SERVICES LLC": "Amazon",
    "WAL MART ASSOCIATES INC": "Walmart",
    "JPMORGAN CHASE AND CO": "JPMorgan Chase",
}


def normalize_company_name(name: str) -> str:
    return COMPANY_ALIASES.get(name.upper(), name)


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
            name = normalize_company_name(name)
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
    elif ats == "icims":
        return icims_fetch_jobs(company, key)
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
) -> dict:
    """Discover ATS, fetch jobs, and classify them into buckets."""
    # Check cache first (thread-safe read)
    with cache_lock:
        if not refresh and company in cache:
            board = cache[company]
        else:
            board = None

    # Skip companies fetched very recently — saves time on frequent runs
    if not refresh and board and _is_recently_fetched(board, max_age_hours):
        logger.debug("[SKIP] %s fetched recently — skipping", company)
        return {"strict": [], "interesting": [], "rejections": {}}

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
            strict: list[dict] = []
            interesting: list[dict] = []
            rejections: Counter[str] = Counter()
            for job in jobs:
                bucket, reason = classify_job(job)
                if bucket == "strict":
                    strict.append(job)
                elif bucket == "interesting":
                    interesting.append(job)
                else:
                    rejections[reason] += 1
            # Stamp last_fetched so this company is skipped next time
            with cache_lock:
                cache.setdefault(company, {})["last_fetched"] = time.time()
                save_cache(cache)
            logger.info(
                "[%s] %d strict / %d interesting (adzuna)",
                company, len(strict), len(interesting),
            )
            return {"strict": strict, "interesting": interesting, "rejections": dict(rejections)}
        logger.info("[SKIP] No ATS found for %s", company)
        return {"strict": [], "interesting": [], "rejections": {"no ATS found": 1}}

    logger.info("[FOUND] %s → %s / %s", company, ats, key)
    jobs = _fetch_jobs_for_board(company, ats, key, board)
    logger.info("[%s] Fetched %d jobs", company, len(jobs))
    strict: list[dict] = []
    interesting: list[dict] = []
    rejections: Counter[str] = Counter()
    for job in jobs:
        bucket, reason = classify_job(job)
        if bucket == "strict":
            strict.append(job)
        elif bucket == "interesting":
            interesting.append(job)
        else:
            rejections[reason] += 1
    # Stamp last_fetched so this company is skipped on the next frequent run
    with cache_lock:
        cache.setdefault(company, {}).update({"ats": ats, "key": key, "last_fetched": time.time()})
        save_cache(cache)
    logger.info("[%s] %d strict / %d interesting", company, len(strict), len(interesting))
    return {"strict": strict, "interesting": interesting, "rejections": dict(rejections)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Entry-level SWE job scraper")
    parser.add_argument("--max-companies", type=int, default=None,
                        help="Cap the number of companies processed")
    parser.add_argument("--concurrency", type=int, default=10,
                        help="Number of companies to probe in parallel (default: 10)")
    parser.add_argument("--out", type=str, default=DEFAULT_OUT)
    parser.add_argument("--interesting-out", type=str, default=DEFAULT_INTERESTING_OUT)
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

    import json as _json

    # Load jobs already saved in the output files so we can deduplicate.
    existing_jobs = load_existing_jobs(args.out)
    existing_interesting_jobs = load_existing_jobs(args.interesting_out)
    strict_seen_urls: set[str] = {j.get("url", "") for j in existing_jobs if j.get("url")}
    strict_fingerprints: set[str] = {
        job_fingerprint(j) for j in existing_jobs if j.get("job_title")
    }
    interesting_seen_urls: set[str] = {
        j.get("url", "") for j in existing_interesting_jobs if j.get("url")
    }
    interesting_fingerprints: set[str] = {
        job_fingerprint(j) for j in existing_interesting_jobs if j.get("job_title")
    }
    logger.info("Loaded %d existing jobs from %s (will skip duplicates)",
                len(existing_jobs), args.out)
    logger.info("Loaded %d existing interesting jobs from %s",
                len(existing_interesting_jobs), args.interesting_out)

    # Load applied jobs — exclude these from the email digest
    _applied_path = Path("data/applied_jobs.json")
    _applied_urls: set[str] = set()
    if _applied_path.exists():
        try:
            _applied_urls = {j.get("job_url", "") for j in _json.loads(_applied_path.read_text())}
        except Exception:
            pass
    if _applied_urls:
        logger.info("Loaded %d applied job URLs (will exclude from email)", len(_applied_urls))

    # Load separate emailed-URLs log — prevents re-emailing jobs across runs
    # even if the Excel read fails or the file gets reset
    _emailed_path = Path("data/emailed_urls.json")
    if _emailed_path.exists():
        try:
            _emailed_urls: set[str] = set(_json.loads(_emailed_path.read_text()))
        except Exception:
            _emailed_urls = set()
    else:
        _emailed_urls = set()

    new_jobs: list[dict] = []
    new_interesting_jobs: list[dict] = []
    rejection_counts: Counter[str] = Counter()
    dedup_counts: Counter[str] = Counter()

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
                    result = future.result()
                    rejection_counts.update(result.get("rejections", {}))

                    for job in result.get("strict", []):
                        url = job.get("url", "")
                        fp = job_fingerprint(job)
                        if url and url in strict_seen_urls:
                            dedup_counts["deduped"] += 1
                            continue
                        if fp in strict_fingerprints:
                            dedup_counts["deduped"] += 1
                            continue
                        strict_seen_urls.add(url)
                        strict_fingerprints.add(fp)
                        new_jobs.append(job)

                    for job in result.get("interesting", []):
                        url = job.get("url", "")
                        fp = job_fingerprint(job)
                        if url and url in strict_seen_urls:
                            dedup_counts["deduped"] += 1
                            continue
                        if fp in strict_fingerprints:
                            dedup_counts["deduped"] += 1
                            continue
                        if url and url in interesting_seen_urls:
                            dedup_counts["deduped"] += 1
                            continue
                        if fp in interesting_fingerprints:
                            dedup_counts["deduped"] += 1
                            continue
                        interesting_seen_urls.add(url)
                        interesting_fingerprints.add(fp)
                        new_interesting_jobs.append(job)
                except Exception as exc:
                    logger.warning("[ERROR] %s raised %s", company, exc)
    except KeyboardInterrupt:
        logger.info("\n[INTERRUPTED] Saving %d jobs collected so far…", len(new_jobs))
    finally:
        shutdown_browser()

    # Ingest the SimplifyJobs new-grad GitHub feed after ATS scraping.
    try:
        simplify_jobs = simplify_newgrad_fetch_jobs()
        for job in simplify_jobs:
            bucket, reason = classify_job(job)
            if bucket == "strict":
                url = job.get("url", "")
                fp = job_fingerprint(job)
                if (url and url in strict_seen_urls) or fp in strict_fingerprints:
                    dedup_counts["deduped"] += 1
                    continue
                strict_seen_urls.add(url)
                strict_fingerprints.add(fp)
                new_jobs.append(job)
            elif bucket == "interesting":
                url = job.get("url", "")
                fp = job_fingerprint(job)
                if (
                    (url and url in strict_seen_urls)
                    or fp in strict_fingerprints
                    or (url and url in interesting_seen_urls)
                    or fp in interesting_fingerprints
                ):
                    dedup_counts["deduped"] += 1
                    continue
                interesting_seen_urls.add(url)
                interesting_fingerprints.add(fp)
                new_interesting_jobs.append(job)
            else:
                rejection_counts[reason] += 1
    except Exception as exc:
        logger.warning("[ERROR] Simplify new-grad ingestion raised %s", exc)

    # Score all new jobs so the Excel and email are sorted by relevance
    new_jobs = score_and_sort(new_jobs)
    new_interesting_jobs = score_and_sort(new_interesting_jobs)

    # Write existing + new jobs together so the files are always complete
    all_jobs = existing_jobs + new_jobs
    strict_all_fingerprints = {
        job_fingerprint(j) for j in all_jobs if j.get("job_title")
    }
    existing_interesting_jobs = [
        j for j in existing_interesting_jobs
        if job_fingerprint(j) not in strict_all_fingerprints
    ]
    all_interesting_jobs = existing_interesting_jobs + new_interesting_jobs
    export_to_excel(all_jobs, args.out)
    export_to_excel(all_interesting_jobs, args.interesting_out)
    print(
        f"\nDone. {len(new_jobs)} new strict jobs + {len(new_interesting_jobs)} new interesting jobs "
        f"added → {len(all_jobs)} strict / {len(all_interesting_jobs)} interesting"
    )
    if rejection_counts:
        logger.info("Rejected jobs by reason: %s", dict(rejection_counts.most_common()))
    if dedup_counts:
        logger.info("Deduped jobs by reason: %s", dict(dedup_counts.most_common()))

    # Email digest:
    #   - posted within last 7 days
    #   - not already emailed
    #   - not already applied to
    #   - sorted by score (highest first, already done above)
    if args.notify_email:
        _summary_path = Path("data/last_summary_date.txt")
        _today = datetime.now().strftime("%Y-%m-%d")
        _last_summary_date = _summary_path.read_text().strip() if _summary_path.exists() else ""

        cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        recent_jobs = [
            j for j in new_jobs
            if (not j.get("date_posted") or j.get("date_posted", "") >= cutoff)
            and j.get("url", "") not in _emailed_urls
            and j.get("url", "") not in _applied_urls
        ] if new_jobs else []

        if recent_jobs:
            send_new_jobs_email(recent_jobs, len(all_jobs), args.out)
            _emailed_urls.update(j.get("url", "") for j in recent_jobs)
            _emailed_path.write_text(_json.dumps(list(_emailed_urls), indent=2))
            logger.info("[NOTIFY] Saved %d emailed URLs to %s",
                        len(_emailed_urls), _emailed_path)
            _summary_path.write_text(_today)
        elif _last_summary_date != _today:
            # No new jobs today — send a once-per-day "nothing found" summary
            send_no_new_jobs_email(len(all_jobs), args.out)
            _summary_path.write_text(_today)
        else:
            logger.info("[NOTIFY] No new jobs and daily summary already sent today")


if __name__ == "__main__":
    main()
