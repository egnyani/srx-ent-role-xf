"""Fetch jobs from Ashby public job list API."""

import logging

from bs4 import BeautifulSoup

from .date_utils import iso_to_date_str
from .http_client import FetchError, post

logger = logging.getLogger(__name__)
BASE = "https://api.ashbyhq.com/posting-public/job/list"


def fetch_jobs(company_name: str, company_key: str) -> list[dict]:
    payload = {"organizationHostedJobsPageName": company_key}
    headers = {"Content-Type": "application/json"}
    try:
        resp = post(BASE, json=payload, headers=headers)
    except FetchError as e:
        logger.warning("Ashby fetch error: %s", e)
        return []
    if resp.status_code != 200:
        logger.warning("Ashby non-200: %s", resp.status_code)
        return []
    try:
        data = resp.json()
    except ValueError:
        return []
    jobs = []
    for job in data.get("results", []):
        raw_desc = job.get("descriptionHtml", "")
        description_text = BeautifulSoup(raw_desc, "html.parser").get_text() if raw_desc else ""
        location = job.get("locationName", job.get("location", ""))
        jobs.append({
            "company_name": company_name,
            "job_title": job.get("title", ""),
            "location": location or "",
            "url": job.get("jobUrl", ""),
            "source": "ashby",
            "description_text": description_text,
            "updated_at": job.get("publishedDate", ""),
            "date_posted": iso_to_date_str(job.get("publishedDate", "")),
        })
    return jobs
