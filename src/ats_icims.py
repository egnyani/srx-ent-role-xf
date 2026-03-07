"""
Fetch jobs from iCIMS career portals.

iCIMS is one of the largest enterprise ATS platforms, used by companies
like Siemens, L3Harris, Booz Allen, General Dynamics, and many others
that aren't on Greenhouse/Lever/Ashby.

Discovery:  probe https://{slug}.icims.com/jobs/search
Fetch:      search API → parse JSON/HTML → normalise to standard schema

iCIMS has two common response formats depending on portal version:
  v1: HTML page with job listing table  (older portals)
  v2: JSON via /search/api/v1/jobs      (newer portals, preferred)
"""

import logging
import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_TIMEOUT = (5, 15)
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JobScraper/1.0)"}

# iCIMS search keywords for SWE roles
_SEARCH_KEYWORDS = [
    "software engineer",
    "software developer",
    "data engineer",
]


def _base_url(slug: str) -> str:
    return f"https://{slug}.icims.com"


# ---------------------------------------------------------------------------
# Discovery probe
# ---------------------------------------------------------------------------

def probe(slug: str) -> bool:
    """Return True if a live iCIMS board exists for this slug."""
    url = f"{_base_url(slug)}/jobs/search"
    try:
        resp = requests.get(url, timeout=_TIMEOUT, headers=_HEADERS, allow_redirects=True)
        return resp.status_code == 200 and "icims" in resp.text.lower()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# JSON API (iCIMS v2 / newer portals)
# ---------------------------------------------------------------------------

def _fetch_json_api(slug: str, company_name: str) -> list[dict] | None:
    """
    Try the newer iCIMS REST search API.
    Returns a list of job dicts on success, None if this portal doesn't
    support this endpoint.
    """
    url = f"{_base_url(slug)}/search/api/v1/jobs"
    params = {
        "in_iframe": 1,
        "in_jcat": 0,
        "in_status": "New",
        "in_keyword": "software engineer",
        "in_location": "United States",
        "ss": 1,
        "hd": "1",
        "pr": 0,
        "startrow": 0,
        "perpage": 200,
    }
    try:
        resp = requests.get(url, params=params, timeout=_TIMEOUT, headers=_HEADERS)
        if resp.status_code != 200:
            return None
        data = resp.json()
    except Exception:
        return None

    postings = data if isinstance(data, list) else data.get("jobs", data.get("postings", []))
    if not isinstance(postings, list):
        return None

    jobs = []
    for item in postings:
        title    = item.get("title") or item.get("jobtitle") or item.get("name") or ""
        job_id   = item.get("id") or item.get("jobid") or ""
        location = (
            item.get("location") or item.get("city") or
            item.get("locationName") or item.get("locationname") or ""
        )
        if isinstance(location, dict):
            location = location.get("name") or location.get("city") or ""
        date_raw = item.get("datePosted") or item.get("dateposted") or item.get("postingDate") or ""
        date_str = _parse_date(date_raw)
        job_url  = (
            item.get("detailUrl") or item.get("url") or
            (f"{_base_url(slug)}/jobs/{job_id}/job" if job_id else "")
        )
        desc = item.get("jobDescription") or item.get("description") or ""
        jobs.append(_make_job(company_name, title, location, job_url, date_str, desc, "icims"))

    return jobs if jobs else None


# ---------------------------------------------------------------------------
# HTML scrape fallback (iCIMS v1 / older portals)
# ---------------------------------------------------------------------------

def _fetch_html(slug: str, company_name: str) -> list[dict]:
    """Scrape the iCIMS HTML job board as a fallback."""
    jobs: list[dict] = []
    for keyword in _SEARCH_KEYWORDS:
        url = f"{_base_url(slug)}/jobs/search"
        params = {
            "pr": 0, "in": 0, "ss": 1,
            "searchKeyword": keyword,
            "searchLocation": "United States",
        }
        try:
            resp = requests.get(url, params=params, timeout=_TIMEOUT, headers=_HEADERS)
            if resp.status_code != 200:
                continue
            page_jobs = _parse_icims_html(resp.text, slug, company_name)
            for j in page_jobs:
                if j["url"] not in {x["url"] for x in jobs}:
                    jobs.append(j)
        except Exception as e:
            logger.debug("[iCIMS] HTML fetch error for %s / %s: %s", slug, keyword, e)
            continue
    return jobs


def _parse_icims_html(html: str, slug: str, company_name: str) -> list[dict]:
    """Parse iCIMS job listing HTML into job dicts."""
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[dict] = []

    # iCIMS HTML has multiple layout versions; try common selectors
    # Pattern 1: iCIMS_JobsTable rows
    table = soup.find(class_=re.compile(r"iCIMS_JobsTable", re.I))
    if table:
        for row in table.find_all(class_=re.compile(r"iCIMS_Anchor|iCIMS_JobTitle", re.I)):
            a = row.find("a", href=True)
            if not a:
                continue
            title = a.get_text(strip=True)
            href = a["href"]
            if not href.startswith("http"):
                href = f"{_base_url(slug)}{href}"
            # Location is often in the next sibling span
            loc_el = row.find_next(class_=re.compile(r"iCIMS.*location|location", re.I))
            location = loc_el.get_text(strip=True) if loc_el else ""
            jobs.append(_make_job(company_name, title, location, href, "", "", "icims"))
        if jobs:
            return jobs

    # Pattern 2: Generic link scan for /jobs/{id}/job URLs
    for a in soup.find_all("a", href=re.compile(r"/jobs/\d+/job")):
        title = a.get_text(strip=True)
        href = a["href"]
        if not href.startswith("http"):
            href = f"{_base_url(slug)}{href}"
        if not title or href in {j["url"] for j in jobs}:
            continue
        # Try to find location near the link
        parent = a.find_parent(["li", "div", "tr"])
        location = ""
        if parent:
            loc_el = parent.find(class_=re.compile(r"location|city|geo", re.I))
            location = loc_el.get_text(strip=True) if loc_el else ""
        jobs.append(_make_job(company_name, title, location, href, "", "", "icims"))

    return jobs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_date(raw: str) -> str:
    if not raw:
        return ""
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y"):
        try:
            return datetime.strptime(raw[:19], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return raw[:10] if len(raw) >= 10 else ""


def _make_job(company, title, location, url, date, desc, source) -> dict:
    return {
        "company_name":    company,
        "job_title":       title,
        "location":        location,
        "url":             url,
        "date_posted":     date,
        "description_text": desc,
        "source":          source,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def fetch_jobs(company_name: str, slug: str) -> list[dict]:
    """
    Fetch all jobs from the iCIMS portal for *slug*.
    Tries the JSON API first; falls back to HTML scraping.
    """
    # Try JSON API (newer portals)
    jobs = _fetch_json_api(slug, company_name)
    if jobs is not None:
        logger.info("[iCIMS] JSON API returned %d jobs for %s", len(jobs), company_name)
        return jobs

    # Fallback: HTML scrape
    jobs = _fetch_html(slug, company_name)
    logger.info("[iCIMS] HTML scrape returned %d jobs for %s", len(jobs), company_name)
    return jobs
