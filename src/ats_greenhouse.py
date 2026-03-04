"""Fetch jobs from Greenhouse boards API."""

import logging

from .http_client import FetchError, get

logger = logging.getLogger(__name__)
BASE = "https://boards-api.greenhouse.io/v1/boards/{board_key}/jobs?content=true"


def fetch_jobs(company_name: str, board_key: str) -> list[dict]:
    url = BASE.format(board_key=board_key)
    try:
        resp = get(url)
    except FetchError as e:
        logger.warning("Greenhouse fetch error: %s", e)
        return []
    if resp.status_code != 200:
        logger.warning("Greenhouse non-200 for %s: %s", url, resp.status_code)
        return []
    try:
        data = resp.json()
    except ValueError:
        return []
    jobs = []
    for job in data.get("jobs", []):
        location = job.get("location") or {}
        location_name = location.get("name", "") if isinstance(location, dict) else ""
        jobs.append({
            "company_name": company_name,
            "job_title": job.get("title", ""),
            "location": location_name,
            "url": job.get("absolute_url", ""),
            "source": "greenhouse",
            "description_text": job.get("content", ""),
            "updated_at": job.get("updated_at", ""),
        })
    return jobs
