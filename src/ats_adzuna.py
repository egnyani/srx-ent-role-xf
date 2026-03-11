"""Adzuna job search — fallback for companies with no discovered ATS.

Requires ADZUNA_APP_ID and ADZUNA_APP_KEY in the environment.
Free tier: https://developer.adzuna.com  (sign up, then create an app)
"""

import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

_BASE = "https://api.adzuna.com/v1/api/jobs/us/search"
_RESULTS_PER_PAGE = 50
_MAX_PAGES = 4          # up to 200 results per company
_TIMEOUT = (5, 15)

# SWE-flavoured search terms — two passes covers most roles without
# burning too many API credits on a single company
_SEARCH_TERMS = [
    "software engineer",
    "software developer",
]


def _credentials() -> tuple[str, str]:
    return (
        os.environ.get("ADZUNA_APP_ID", ""),
        os.environ.get("ADZUNA_APP_KEY", ""),
    )


def is_configured() -> bool:
    app_id, app_key = _credentials()
    return bool(app_id and app_key)


def fetch_jobs(company: str) -> list[dict]:
    """Search Adzuna for SWE jobs at *company*; return our standard job dicts."""
    app_id, app_key = _credentials()
    if not app_id or not app_key:
        return []

    # Use just the first meaningful word of the company name as the search
    # term — Adzuna's company filter is fuzzy, shorter is better
    company_token = _first_word(company)

    jobs: list[dict] = []
    seen_urls: set[str] = set()

    for term in _SEARCH_TERMS:
        for page in range(1, _MAX_PAGES + 1):
            try:
                resp = requests.get(
                    f"{_BASE}/{page}",
                    params={
                        "app_id": app_id,
                        "app_key": app_key,
                        "what_phrase": term,
                        "company": company_token,
                        "results_per_page": _RESULTS_PER_PAGE,
                        "sort_by": "date",
                    },
                    timeout=_TIMEOUT,
                )
            except Exception as exc:
                logger.debug("Adzuna request error for %s: %s", company, exc)
                break

            if resp.status_code == 429:
                logger.debug("Adzuna rate-limited; sleeping 5 s")
                time.sleep(5)
                continue
            if resp.status_code != 200:
                logger.debug("Adzuna returned %s for %s", resp.status_code, company)
                break

            try:
                results = resp.json().get("results", [])
            except Exception:
                break

            if not results:
                break   # no more pages

            for r in results:
                url = r.get("redirect_url", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)

                created = r.get("created", "")
                date_posted = created[:10] if created else ""

                jobs.append({
                    "company_name": company,
                    "job_title": r.get("title", ""),
                    "location": r.get("location", {}).get("display_name", ""),
                    "url": url,
                    "date_posted": date_posted,
                    "description_text": r.get("description", ""),
                    "source": "adzuna",
                })

    return jobs


def _first_word(company: str) -> str:
    """Return the first non-trivial word from the company name."""
    skip = {"inc", "llc", "ltd", "corp", "co", "the", "and", "&"}
    for word in company.split():
        w = word.strip(".,").lower()
        if w and w not in skip:
            return w
    return company.split()[0]
