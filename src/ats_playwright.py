"""Playwright fallback scraper for career pages without a known ATS."""

import logging
import threading
import urllib.parse
from typing import Optional

from .filters import is_entry_level_swe

logger = logging.getLogger(__name__)

# Shared browser singleton
_browser = None
_playwright_instance = None
_browser_lock = threading.Lock()

# Cached availability check
_playwright_available: Optional[bool] = None
_playwright_check_lock = threading.Lock()

# Common CSS selectors for job card elements
_JOB_SELECTORS = [
    "[class*='job-card']",
    "li[class*='job']",
    "[class*='job-listing']",
    "[class*='job-item']",
    "[class*='career-item']",
    "[class*='opening']",
    "[data-job-id]",
    ".job",
    "article[class*='job']",
]


def _check_playwright_available() -> bool:
    """Lazy import check; logs warning if not installed; cached result."""
    global _playwright_available
    with _playwright_check_lock:
        if _playwright_available is not None:
            return _playwright_available
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
            _playwright_available = True
        except ImportError:
            logger.warning(
                "Playwright is not installed. "
                "Run: pip install playwright && playwright install chromium"
            )
            _playwright_available = False
    return _playwright_available


def _get_browser():
    """Get or create the shared browser singleton."""
    global _browser, _playwright_instance
    with _browser_lock:
        if _browser is None:
            from playwright.sync_api import sync_playwright
            _playwright_instance = sync_playwright().start()
            _browser = _playwright_instance.chromium.launch(headless=True)
    return _browser


def shutdown_browser() -> None:
    """Close the shared browser and playwright instance. Call at exit."""
    global _browser, _playwright_instance
    with _browser_lock:
        if _browser is not None:
            try:
                _browser.close()
            except Exception:
                pass
            _browser = None
        if _playwright_instance is not None:
            try:
                _playwright_instance.stop()
            except Exception:
                pass
            _playwright_instance = None


def scrape_careers_page(company: str, careers_url: str) -> dict:
    """
    Scrape a careers page using Playwright.

    Step 1 — ATS link detection: Renders the page, extracts all links and
    iframe srcs, scans for all 5 ATS URL patterns.
    Returns {"ats": ..., "key": ...} if an ATS link is found.

    Step 2 — Generic extraction: Tries common CSS selectors to find job cards,
    extracts title + location + href, filters with is_entry_level_swe.
    Returns {"ats": "careers_page", "key": url, "jobs": [...]} if jobs found.

    Returns {"ats": None, "key": None} if nothing found.
    Each company gets its own BrowserContext (no state leak).
    """
    if not _check_playwright_available():
        return {"ats": None, "key": None}

    # Lazy import to avoid circular dependency at module load time
    from .discovery import _extract_ats_from_urls

    browser = _get_browser()
    context = None
    try:
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()
        try:
            page.goto(careers_url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)  # Allow JS to render
        except Exception as e:
            logger.warning("[%s] Playwright navigation error: %s", company, e)
            return {"ats": None, "key": None}

        # --- Step 1: ATS link detection ---
        all_urls: list[str] = []
        try:
            hrefs = page.eval_on_selector_all(
                "a[href]",
                "els => els.map(e => e.href).filter(h => h && h.startsWith('http'))"
            )
            all_urls.extend(hrefs)
        except Exception:
            pass
        try:
            iframe_srcs = page.eval_on_selector_all(
                "iframe[src]",
                "els => els.map(e => e.src).filter(s => s && s.startsWith('http'))"
            )
            all_urls.extend(iframe_srcs)
        except Exception:
            pass

        ats_result = _extract_ats_from_urls(all_urls)
        if ats_result and ats_result.get("ats"):
            return ats_result

        # --- Step 2: Generic extraction ---
        extracted_jobs: list[dict] = []
        for selector in _JOB_SELECTORS:
            try:
                elements = page.query_selector_all(selector)
                if not elements:
                    continue
                for el in elements[:100]:  # cap per selector
                    try:
                        text = el.inner_text().strip()
                        if not text:
                            continue
                        href = ""
                        try:
                            link_el = el.query_selector("a[href]")
                            if link_el:
                                href = link_el.get_attribute("href") or ""
                                if href and not href.startswith("http"):
                                    href = urllib.parse.urljoin(careers_url, href)
                        except Exception:
                            pass
                        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                        title = lines[0] if lines else text[:100]
                        location = lines[1] if len(lines) > 1 else ""
                        job = {
                            "company_name": company,
                            "job_title": title,
                            "location": location,
                            "url": href or careers_url,
                            "source": "careers_page",
                            "description_text": text,
                            "updated_at": "",
                            "date_posted": "",
                        }
                        if is_entry_level_swe(job)[0]:
                            extracted_jobs.append(job)
                    except Exception:
                        continue
                if extracted_jobs:
                    break
            except Exception:
                continue

        if extracted_jobs:
            return {"ats": "careers_page", "key": careers_url, "jobs": extracted_jobs}

        return {"ats": None, "key": None}

    except Exception as e:
        logger.warning("[%s] Playwright scrape error: %s", company, e)
        return {"ats": None, "key": None}
    finally:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
