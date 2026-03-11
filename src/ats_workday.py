"""Fetch jobs from Workday career portals via the CXS API."""

import json
import logging
import re

import requests
from bs4 import BeautifulSoup

from .date_utils import iso_to_date_str, slash_to_date_str

logger = logging.getLogger(__name__)
_PROBE_TIMEOUT = (5, 10)
_TOKEN_RE = re.compile(r'token:\s*"([^"]+)"')


def _detail_headers(token: str, job_url: str) -> dict:
    return {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept-Language": "en-US",
        "X-CALYPSO-CSRF-TOKEN": token,
        "Referer": job_url,
    }


def _fetch_job_detail(
    session: requests.Session,
    base_url: str,
    subdomain: str,
    board: str,
    external_path: str,
    job_url: str,
) -> dict | None:
    try:
        page_resp = session.get(job_url, timeout=_PROBE_TIMEOUT)
        if page_resp.status_code != 200:
            return None
    except Exception as e:
        logger.debug("Workday page fetch error for %s: %s", job_url, e)
        return None

    token_match = _TOKEN_RE.search(page_resp.text)
    if not token_match:
        return None

    detail_url = f"{base_url}/wday/cxs/{subdomain}/{board}{external_path}"
    try:
        detail_resp = session.get(
            detail_url,
            timeout=_PROBE_TIMEOUT,
            headers=_detail_headers(token_match.group(1), job_url),
        )
    except Exception as e:
        logger.debug("Workday detail fetch error for %s: %s", detail_url, e)
        return None
    if detail_resp.status_code != 200:
        logger.debug("Workday detail non-200 for %s: %s", detail_url, detail_resp.status_code)
        return None
    try:
        data = detail_resp.json()
    except ValueError:
        return None
    return data.get("jobPostingInfo") if isinstance(data, dict) else None


def _description_text(job_info: dict | None) -> str:
    if not job_info:
        return ""
    raw = job_info.get("jobDescription", "") or ""
    if not raw:
        return ""
    return BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)


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

    session = requests.Session()

    while True:
        payload = {
            "limit": limit,
            "offset": offset,
            "searchText": "",
            "appliedFacets": {},
        }
        try:
            resp = session.post(
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
            detail = (
                _fetch_job_detail(session, base_url, subdomain, board, external_path, job_url)
                if external_path and job_url
                else None
            )
            location = (detail or {}).get("location", "") or posting.get("locationsText", "")
            date_raw = (detail or {}).get("startDate", "")
            date_str = iso_to_date_str(date_raw) if date_raw else slash_to_date_str(posting.get("postedOn", ""))
            jobs.append({
                "company_name": company_name,
                "job_title": (detail or {}).get("title", "") or posting.get("title", ""),
                "location": location,
                "url": (detail or {}).get("externalUrl", "") or job_url,
                "source": "workday",
                "description_text": _description_text(detail),
                "updated_at": date_raw or posting.get("postedOn", ""),
                "date_posted": date_str,
            })

        offset += len(postings)
        if total is not None and offset >= total:
            break

    return jobs
