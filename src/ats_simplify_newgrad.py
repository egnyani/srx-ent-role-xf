"""Fetch jobs from the SimplifyJobs new-grad GitHub repository."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

from bs4 import BeautifulSoup

from .http_client import FetchError, get

logger = logging.getLogger(__name__)

README_RAW_URL = "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/README.md"
_DAY_AGE_RE = re.compile(r"^\s*(\d+)\s*d\s*$", re.I)


def _clean_company_name(text: str) -> str:
    return text.replace("🔥", "").replace("🛂", "").strip()


def _extract_apply_url(cell) -> str:
    for link in cell.find_all("a", href=True):
        href = link["href"].strip()
        if href:
            return href
    return ""


def _estimate_date_posted(age_text: str) -> str:
    match = _DAY_AGE_RE.match(age_text or "")
    if not match:
        return ""
    days = int(match.group(1))
    return (datetime.utcnow().date() - timedelta(days=days)).isoformat()


def fetch_jobs() -> list[dict]:
    try:
        resp = get(README_RAW_URL)
    except FetchError as exc:
        logger.warning("Simplify new-grad fetch error: %s", exc)
        return []
    if resp.status_code != 200:
        logger.warning("Simplify new-grad non-200: %s", resp.status_code)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    jobs: list[dict] = []
    seen_urls: set[str] = set()
    last_company = ""

    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 5:
            continue
        company = _clean_company_name(cells[0].get_text(" ", strip=True))
        if company == "↳":
            company = last_company
        title = cells[1].get_text(" ", strip=True)
        location = cells[2].get_text(" ", strip=True)
        url = _extract_apply_url(cells[3])
        age_text = cells[4].get_text(" ", strip=True)
        if not company or not title or not url or url in seen_urls:
            continue
        last_company = company
        seen_urls.add(url)
        jobs.append(
            {
                "company_name": company,
                "job_title": title,
                "location": location,
                "url": url,
                "source": "simplify_newgrad",
                "description_text": "",
                "updated_at": age_text,
                "date_posted": _estimate_date_posted(age_text),
            }
        )

    logger.info("Simplify new-grad fetched %d jobs", len(jobs))
    return jobs
