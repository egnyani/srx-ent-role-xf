"""Search client abstraction for ATS discovery."""

import logging
import os
import random
import time
import urllib.parse
from abc import ABC, abstractmethod

from bs4 import BeautifulSoup

from .http_client import FetchError, get, post

logger = logging.getLogger(__name__)
__all__ = [
    "SearchClient",
    "BingSearchClient",
    "TavilySearchClient",
    "DuckDuckGoSearchClient",
    "get_search_client",
]


class SearchClient(ABC):
    """Abstract base class for search. Returns list of URLs from search results."""

    @abstractmethod
    def search(self, query: str) -> list[str]:
        """Return a list of result URLs."""
        raise NotImplementedError


class BingSearchClient(SearchClient):
    """Uses Bing Web Search API when BING_API_KEY is set."""

    BASE = "https://api.bing.microsoft.com/v7.0/search"

    def __init__(self) -> None:
        self._key = os.environ.get("BING_API_KEY", "")
        if not self._key:
            raise ValueError("BING_API_KEY must be set for BingSearchClient")

    def search(self, query: str) -> list[str]:
        try:
            params = {"q": query, "count": 10}
            headers = {"Ocp-Apim-Subscription-Key": self._key}
            resp = get(self.BASE, params=params, headers=headers)
            data = resp.json()
            urls = []
            for item in data.get("webPages", {}).get("value", []):
                u = item.get("url")
                if u:
                    urls.append(u)
            return urls
        except Exception as e:
            logger.warning("BingSearchClient error: %s", e)
            return []


class TavilySearchClient(SearchClient):
    """Uses Tavily Search API when TAVILY_API_KEY is set."""

    BASE = "https://api.tavily.com/search"

    def __init__(self) -> None:
        key = os.environ.get("TAVILY_API_KEY", "").strip()
        if not key:
            raise ValueError("TAVILY_API_KEY must be set for TavilySearchClient")
        self._key = key if key.startswith("tvly-") else f"tvly-{key}"

    def search(self, query: str) -> list[str]:
        try:
            payload = {
                "query": query,
                "max_results": 10,
                "search_depth": "basic",
            }
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._key}",
            }
            resp = post(self.BASE, json=payload, headers=headers)
            if resp.status_code != 200:
                logger.warning("TavilySearchClient returned status %s", resp.status_code)
                return []
            data = resp.json()
            urls = []
            for item in data.get("results", []):
                u = item.get("url")
                if u:
                    urls.append(u)
            return urls
        except Exception as e:
            logger.warning("TavilySearchClient error: %s", e)
            return []


class DuckDuckGoSearchClient(SearchClient):
    """Uses DuckDuckGo HTML search when no API key is set (fallback)."""

    BASE = "https://html.duckduckgo.com/html/"
    MIN_SLEEP = 4
    MAX_SLEEP = 7
    RETRY_WAIT = 15

    # Rotate user-agents to reduce bot detection
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    ]

    def search(self, query: str) -> list[str]:
        time.sleep(random.uniform(self.MIN_SLEEP, self.MAX_SLEEP))
        headers = {
            "User-Agent": random.choice(self.USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        # Use POST form submission (more reliable than GET for DDG HTML)
        try:
            import requests as _req
            resp = _req.post(
                self.BASE,
                data={"q": query, "b": "", "kl": "us-en"},
                headers=headers,
                timeout=15,
                allow_redirects=True,
            )
        except Exception:
            return []

        if resp.status_code == 202 or resp.status_code == 429:
            time.sleep(self.RETRY_WAIT)
            try:
                import requests as _req
                resp = _req.post(
                    self.BASE,
                    data={"q": query, "b": "", "kl": "us-en"},
                    headers=headers,
                    timeout=15,
                    allow_redirects=True,
                )
            except Exception:
                return []

        if resp.status_code != 200:
            logger.warning("DuckDuckGo returned status %s", resp.status_code)
            return []

        try:
            soup = BeautifulSoup(resp.text, "html.parser")
            urls: list[str] = []

            # Primary: <a class="result__a"> — the title link (direct URL in href)
            for a in soup.select("a.result__a"):
                href = a.get("href", "")
                if href and href.startswith("http"):
                    urls.append(href)

            # Fallback: <a class="result__url"> — displayed URL text link
            if not urls:
                for a in soup.select("a.result__url"):
                    href = a.get("href", "")
                    if href:
                        # DDG sometimes wraps these in /l/?uddg=<encoded-url>
                        if "uddg=" in href:
                            encoded = href.split("uddg=")[-1].split("&")[0]
                            href = urllib.parse.unquote(encoded)
                        if href.startswith("http"):
                            urls.append(href)

            # Second fallback: any anchor whose href contains known ATS domains
            if not urls:
                ats_domains = (
                    "boards.greenhouse.io", "boards-api.greenhouse.io",
                    "jobs.lever.co", "api.lever.co",
                    "jobs.ashbyhq.com",
                )
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if any(d in href for d in ats_domains):
                        urls.append(href)

            return urls
        except Exception as e:
            logger.warning("DuckDuckGoSearchClient parse error: %s", e)
            return []


def get_search_client() -> SearchClient:
    if os.environ.get("TAVILY_API_KEY"):
        return TavilySearchClient()
    if os.environ.get("BING_API_KEY"):
        return BingSearchClient()
    return DuckDuckGoSearchClient()
