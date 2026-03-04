"""Automatic ATS detection (Greenhouse, Lever, Ashby) via direct probing and search."""

import json
import logging
import re
import time
import urllib.parse
import requests as _requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from bs4 import BeautifulSoup

from .http_client import FetchError, get, post
from .search import SearchClient, get_search_client

# Short connect + read timeout for probing — we don't retry, just skip fast
_PROBE_TIMEOUT = (3, 4)  # (connect_seconds, read_seconds)

logger = logging.getLogger(__name__)

CACHE_PATH = Path("data/discovered_boards.json")

GREENHOUSE_PATTERNS = [
    re.compile(r"boards\.greenhouse\.io/([^/?#\s]+)", re.I),
    re.compile(r"boards-api\.greenhouse\.io/v1/boards/([^/?#\s]+)", re.I),
]
LEVER_PATTERNS = [
    re.compile(r"jobs\.lever\.co/([^/?#\s]+)", re.I),
    re.compile(r"api\.lever\.co/v0/postings/([^/?#\s]+)", re.I),
]
ASHBY_PATTERNS = [
    re.compile(r"jobs\.ashbyhq\.com/([^/?#\s]+)", re.I),
]

QUERIES = [
    ("greenhouse", "{company} careers greenhouse"),
    ("greenhouse", "{company} jobs greenhouse"),
    ("lever", "{company} careers lever"),
    ("lever", "{company} jobs lever"),
    ("ashby", "{company} careers ashby"),
    ("ashby", "{company} jobs ashby"),
]

# Legal suffixes to strip when generating ATS slugs
_LEGAL_SUFFIXES = [
    ", inc.", ", inc", ", llc.", ", llc", ", corp.", ", corp",
    ", ltd.", ", ltd", ", l.l.c.", ", l.l.c",
    " incorporated", " corporation", " limited", " company",
    " inc.", " inc", " llc.", " llc", " corp.", " corp",
    " ltd.", " ltd", " co.", " co", " group", " holdings",
    " technologies", " technology", " solutions", " services",
    " international", " worldwide",
]


def _generate_slugs(company: str) -> list[str]:
    """
    Generate candidate ATS board slugs from a company name.

    Tries multiple forms so we catch boards registered under the short brand
    name (e.g. 'cisco') as well as the full slug (e.g. 'cisco-systems').
    """
    name = company.lower().strip()

    # Strip legal suffixes (longest first to handle combinations)
    for suffix in sorted(_LEGAL_SUFFIXES, key=len, reverse=True):
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip().rstrip(",").strip()
            break

    slug_hyphen = re.sub(r"[^a-z0-9]+", "-", name).strip("-")
    slug_nospace = re.sub(r"[^a-z0-9]+", "", name)

    # First-word slug — many boards are registered under just the brand name
    # e.g. "CISCO SYSTEMS INC" → "cisco", "PALO ALTO NETWORKS INC" → "palo"
    first_word = re.split(r"[^a-z0-9]+", name)[0]

    seen: set[str] = set()
    slugs: list[str] = []
    for s in [slug_hyphen, slug_nospace, first_word]:
        if s and s not in seen:
            slugs.append(s)
            seen.add(s)
    return slugs


def _probe_greenhouse(slug: str) -> bool:
    """Return True if a live Greenhouse board exists for this slug."""
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    try:
        resp = _requests.get(url, timeout=_PROBE_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            return "jobs" in data
    except Exception:
        pass
    return False


def _probe_lever(slug: str) -> bool:
    """Return True if a live Lever board exists for this slug."""
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    try:
        resp = _requests.get(url, timeout=_PROBE_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            return isinstance(data, list)
    except Exception:
        pass
    return False


def _probe_ashby(slug: str) -> bool:
    """Return True if a live Ashby board exists for this slug."""
    try:
        resp = _requests.post(
            "https://api.ashbyhq.com/posting-public/job/list",
            json={"organizationHostedJobsPageName": slug},
            headers={"Content-Type": "application/json"},
            timeout=_PROBE_TIMEOUT,
        )
        if resp.status_code == 200:
            data = resp.json()
            return "results" in data
    except Exception:
        pass
    return False


def _probe_all_ats(company: str) -> dict:
    """
    Fire all ATS probes concurrently and return the first hit.
    All slug × ATS combinations run in parallel threads.  The overall wall
    clock is capped at _PROBE_TIMEOUT[1] + 2 seconds so no single company
    can block the main loop for more than ~6 seconds.
    """
    slugs = _generate_slugs(company)
    logger.debug("[%s] Probing slugs: %s", company, slugs)

    probe_map = {
        "greenhouse": _probe_greenhouse,
        "lever": _probe_lever,
        "ashby": _probe_ashby,
    }
    tasks: list[tuple[str, str]] = [
        (ats_name, slug)
        for slug in slugs
        for ats_name in ("greenhouse", "lever", "ashby")
    ]

    # Wall-clock cap = read timeout + 2 s buffer
    wall_cap = _PROBE_TIMEOUT[1] + 2

    result: dict = {"ats": None, "key": None}
    with ThreadPoolExecutor(max_workers=max(len(tasks), 1)) as pool:
        future_to_info = {
            pool.submit(probe_map[ats_name], slug): (ats_name, slug)
            for ats_name, slug in tasks
        }
        try:
            for future in as_completed(future_to_info, timeout=wall_cap):
                ats_name, slug = future_to_info[future]
                try:
                    if future.result():
                        result = {"ats": ats_name, "key": slug}
                        for f in future_to_info:
                            f.cancel()
                        break
                except Exception:
                    pass
        except Exception:
            # TimeoutError or other — treat as no ATS found
            pass

    if result["ats"]:
        logger.debug("[%s] Hit: %s / %s", company, result["ats"], result["key"])
    return result


def _extract_key_from_urls(urls: list[str], ats: str) -> str | None:
    if ats == "greenhouse":
        for pattern in GREENHOUSE_PATTERNS:
            for url in urls:
                m = pattern.search(url)
                if m:
                    return m.group(1).strip()
    elif ats == "lever":
        for pattern in LEVER_PATTERNS:
            for url in urls:
                m = pattern.search(url)
                if m:
                    return m.group(1).strip()
    elif ats == "ashby":
        for pattern in ASHBY_PATTERNS:
            for url in urls:
                m = pattern.search(url)
                if m:
                    return m.group(1).strip()
    return None


def _extract_ats_from_urls(urls: list[str]) -> dict | None:
    """Scan URLs for any ATS pattern; return first match as {ats, key} or None."""
    for url in urls:
        for ats, patterns in [
            ("greenhouse", GREENHOUSE_PATTERNS),
            ("lever", LEVER_PATTERNS),
            ("ashby", ASHBY_PATTERNS),
        ]:
            for pattern in patterns:
                m = pattern.search(url)
                if m:
                    return {"ats": ats, "key": m.group(1).strip()}
    return None


def _discover_via_careers_page(company: str, client: SearchClient) -> dict:
    """
    Search for company careers page, fetch it, parse HTML for ATS links.
    Returns first ATS match found in page links, or {ats: None, key: None}.
    """
    for query in [f"{company} careers", f"{company} jobs"]:
        urls = client.search(query)
        if not urls:
            continue
        # Try first few result URLs (likely careers pages)
        for page_url in urls[:3]:
            try:
                resp = _requests.get(
                    page_url,
                    timeout=(5, 10),
                    headers={"User-Agent": "Mozilla/5.0 (compatible)"},
                    allow_redirects=True,
                )
                if resp.status_code != 200:
                    continue
                soup = BeautifulSoup(resp.text, "html.parser")
                page_links: list[str] = []
                for a in soup.find_all("a", href=True):
                    href = a["href"].strip()
                    if not href or href.startswith("#") or href.startswith("mailto:"):
                        continue
                    full_url = urllib.parse.urljoin(page_url, href)
                    if full_url.startswith("http"):
                        page_links.append(full_url)
                result = _extract_ats_from_urls(page_links)
                if result:
                    logger.debug("[%s] Careers page discovery: %s", company, result)
                    return result
            except Exception:
                continue
            time.sleep(1)  # Brief pause between page fetches
    return {"ats": None, "key": None}


def _discover_via_search(company: str, client: SearchClient) -> dict:
    """Run search queries and extract ATS key from result URLs."""
    for ats, template in QUERIES:
        query = template.format(company=company)
        urls = client.search(query)
        key = _extract_key_from_urls(urls, ats)
        if key:
            return {"ats": ats, "key": key}
    return {"ats": None, "key": None}


def discover_ats(company: str, client: SearchClient, use_search_fallback: bool = False) -> dict:
    """
    Discover ATS for a company using strategies in order:
      1. Direct URL probing (no API key required, faster, more reliable).
      2. Careers page fetch: search for "{company} careers", fetch the page,
         parse HTML for links to Greenhouse/Lever/Ashby, extract board key.
      3. Search-based discovery (optional; runs when use_search_fallback=True).
    """
    result = _probe_all_ats(company)
    if result["ats"]:
        return result
    result = _discover_via_careers_page(company, client)
    if result["ats"]:
        return result
    if use_search_fallback:
        return _discover_via_search(company, client)
    return {"ats": None, "key": None}


def load_cache() -> dict:
    if not CACHE_PATH.exists():
        return {}
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)


def get_board(
    company: str,
    client: SearchClient,
    cache: dict,
    refresh: bool,
    use_search_fallback: bool = False,
) -> dict:
    if not refresh and company in cache:
        return cache[company]
    result = discover_ats(company, client, use_search_fallback=use_search_fallback)
    cache[company] = result
    save_cache(cache)
    return result
