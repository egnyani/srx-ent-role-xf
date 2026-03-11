"""Fetch jobs from SmartRecruiters public postings API."""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

from .date_utils import iso_to_date_str

logger = logging.getLogger(__name__)
BASE = "https://api.smartrecruiters.com/v1/companies/{slug}/postings"
_PROBE_TIMEOUT = (5, 10)
_DETAIL_WORKERS = 8


def _detail_url(slug: str, posting: dict) -> str:
    ref = posting.get("ref", "") or ""
    if ref.startswith("http"):
        return ref
    posting_id = posting.get("id", "") or ""
    if posting_id:
        return f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{posting_id}"
    return ""


def _description_text(detail: dict) -> str:
    sections = ((detail.get("jobAd") or {}).get("sections") or {})
    texts: list[str] = []
    for section in sections.values():
        if not isinstance(section, dict):
            continue
        raw = section.get("text", "") or ""
        if not raw:
            continue
        text = BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)
        if text:
            texts.append(text)
    return "\n\n".join(texts)


def _public_url(slug: str, posting: dict, detail: dict | None) -> str:
    if detail and detail.get("postingUrl"):
        return detail["postingUrl"]
    ref = posting.get("ref", "") or ""
    if ref.startswith("http"):
        posting_id = posting.get("id", "") or ""
        if posting_id:
            company = ((posting.get("company") or {}).get("identifier")) or slug
            title = (posting.get("name", "") or "").strip().lower()
            slug_title = "-".join(title.split())
            return f"https://jobs.smartrecruiters.com/{company}/{posting_id}-{slug_title}".rstrip("-")
        return ""
    if ref:
        return f"https://jobs.smartrecruiters.com/{slug}/{ref}"
    return ""


def _fetch_job_detail(slug: str, posting: dict) -> dict | None:
    url = _detail_url(slug, posting)
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=_PROBE_TIMEOUT)
    except Exception as e:
        logger.debug("SmartRecruiters detail fetch error for %s: %s", url, e)
        return None
    if resp.status_code != 200:
        logger.debug("SmartRecruiters detail non-200 for %s: %s", url, resp.status_code)
        return None
    try:
        data = resp.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _make_job(company_name: str, slug: str, posting: dict, detail: dict | None) -> dict:
    src = detail or posting
    location_obj = src.get("location", {}) or {}
    location = (
        location_obj.get("fullLocation")
        or ", ".join(filter(None, [location_obj.get("city", ""), location_obj.get("country", "")]))
    )
    date_raw = src.get("releasedDate", "") or posting.get("releasedDate", "")
    return {
        "company_name": company_name,
        "job_title": src.get("name", "") or posting.get("name", ""),
        "location": location,
        "url": _public_url(slug, posting, detail),
        "source": "smartrecruiters",
        "description_text": _description_text(detail) if detail else "",
        "updated_at": date_raw,
        "date_posted": iso_to_date_str(date_raw),
    }


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

        with ThreadPoolExecutor(max_workers=_DETAIL_WORKERS) as pool:
            future_map = {
                pool.submit(_fetch_job_detail, slug, posting): posting
                for posting in content
            }
            for future in as_completed(future_map):
                posting = future_map[future]
                try:
                    detail = future.result()
                except Exception as e:
                    logger.debug("SmartRecruiters detail future failed for %s: %s", company_name, e)
                    detail = None
                jobs.append(_make_job(company_name, slug, posting, detail))

        offset += len(content)
        if total_found is not None and offset >= total_found:
            break

    return jobs
