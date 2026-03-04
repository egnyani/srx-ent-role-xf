"""Fetch jobs from Lever postings API."""

import logging

from .http_client import FetchError, get

logger = logging.getLogger(__name__)
BASE = "https://api.lever.co/v0/postings/{account}?mode=json"


def fetch_jobs(company_name: str, account: str) -> list[dict]:
    try:
        url = BASE.format(account=account)
        resp = get(url)
    except FetchError as e:
        logger.warning("Lever fetch error: %s", e)
        return []
    if resp.status_code != 200:
        logger.warning("Lever non-200 for %s: %s", url, resp.status_code)
        return []
    data = resp.json() if resp.text else []
    if not isinstance(data, list):
        return []
    jobs = []
    for posting in data:
        categories = posting.get("categories") or {}
        location = categories.get("location", "") if isinstance(categories, dict) else ""
        jobs.append({
            "company_name": company_name,
            "job_title": posting.get("text", ""),
            "location": location,
            "url": posting.get("hostedUrl", ""),
            "source": "lever",
            "description_text": posting.get("descriptionPlain", ""),
            "updated_at": str(posting.get("createdAt", "")),
        })
    return jobs
