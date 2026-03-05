"""Fetch jobs from Workday career portals via the CXS API."""

import json
import logging

import requests

from .date_utils import slash_to_date_str

logger = logging.getLogger(__name__)
_PROBE_TIMEOUT = (5, 10)


def fetch_jobs(company_name: str, key: str) -> list[dict]:
    """
    key is a JSON string: {"subdomain": "amazon", "instance": 5, "board": "en-US_External_Career_Site"}
    Paginates via offset until postings is empty or offset >= total.
    """
    try:
        config = json.loads(key)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Workday: invalid key for %s: %r", company_name, key)
        return []

    subdomain = config.get("subdomain", "")
    instance = config.get("instance", 1)
    board = config.get("board", "")
    if not subdomain or not board:
        logger.warning("Workday: missing subdomain/board for %s", company_name)
        return []

    base_url = f"https://{subdomain}.wd{instance}.myworkdayjobs.com"
    api_url = f"{base_url}/wday/cxs/{subdomain}/{board}/jobs"
    job_base = f"{base_url}/{board}"

    jobs: list[dict] = []
    offset = 0
    limit = 20
    total = None

    while True:
        payload = {
            "limit": limit,
            "offset": offset,
            "searchText": "",
            "appliedFacets": {},
        }
        try:
            resp = requests.post(
                api_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=_PROBE_TIMEOUT,
            )
        except Exception as e:
            logger.warning("Workday fetch error for %s: %s", company_name, e)
            break

        if resp.status_code != 200:
            logger.warning("Workday non-200 for %s: %s", company_name, resp.status_code)
            break

        try:
            data = resp.json()
        except ValueError:
            break

        if total is None:
            total = data.get("total", 0)

        postings = data.get("jobPostings", [])
        if not postings:
            break

        for posting in postings:
            external_path = posting.get("externalPath", "")
            job_url = f"{job_base}{external_path}" if external_path else ""
            location = posting.get("locationsText", "")
            date_str = slash_to_date_str(posting.get("postedOn", ""))
            jobs.append({
                "company_name": company_name,
                "job_title": posting.get("title", ""),
                "location": location,
                "url": job_url,
                "source": "workday",
                "description_text": "",
                "updated_at": posting.get("postedOn", ""),
                "date_posted": date_str,
            })

        offset += len(postings)
        if total is not None and offset >= total:
            break

    return jobs
