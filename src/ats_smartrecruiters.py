"""Fetch jobs from SmartRecruiters public postings API."""

import logging

import requests

from .date_utils import iso_to_date_str

logger = logging.getLogger(__name__)
BASE = "https://api.smartrecruiters.com/v1/companies/{slug}/postings"
_PROBE_TIMEOUT = (5, 10)


def fetch_jobs(company_name: str, slug: str) -> list[dict]:
    """Paginate through all PUBLIC postings for a SmartRecruiters company slug."""
    jobs: list[dict] = []
    offset = 0
    limit = 100
    total_found = None

    while True:
        params = {
            "status": "PUBLIC",
            "limit": limit,
            "offset": offset,
        }
        try:
            resp = requests.get(
                BASE.format(slug=slug),
                params=params,
                timeout=_PROBE_TIMEOUT,
            )
        except Exception as e:
            logger.warning("SmartRecruiters fetch error for %s: %s", company_name, e)
            break

        if resp.status_code != 200:
            logger.warning("SmartRecruiters non-200 for %s: %s", company_name, resp.status_code)
            break

        try:
            data = resp.json()
        except ValueError:
            break

        if total_found is None:
            total_found = data.get("totalFound", 0)

        content = data.get("content", [])
        if not content:
            break

        for posting in content:
            location_obj = posting.get("location", {}) or {}
            city = location_obj.get("city", "") or ""
            country = location_obj.get("country", "") or ""
            location = ", ".join(filter(None, [city, country]))
            ref = posting.get("ref", "")
            job_url = f"https://jobs.smartrecruiters.com/{slug}/{ref}" if ref else ""
            date_str = iso_to_date_str(posting.get("releasedDate", ""))
            jobs.append({
                "company_name": company_name,
                "job_title": posting.get("name", ""),
                "location": location,
                "url": job_url,
                "source": "smartrecruiters",
                "description_text": "",
                "updated_at": posting.get("releasedDate", ""),
                "date_posted": date_str,
            })

        offset += len(content)
        if total_found is not None and offset >= total_found:
            break

    return jobs
