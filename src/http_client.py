"""Shared HTTP client with timeout and retry logic."""

import logging
import time

import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15
RETRY_DELAYS = (1, 2, 4)
RETRY_STATUSES = (429, 500, 502, 503, 504)


class FetchError(Exception):
    """Raised when all HTTP retries are exhausted."""
    pass


def get(url: str, **kwargs) -> requests.Response:
    """GET with timeout and retries. Raises FetchError on failure."""
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    return _request("get", url, **kwargs)


def post(url: str, **kwargs) -> requests.Response:
    """POST with timeout and retries. Raises FetchError on failure."""
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    return _request("post", url, **kwargs)


def _request(method: str, url: str, **kwargs) -> requests.Response:
    last_exc = None
    max_attempts = len(RETRY_DELAYS) + 1
    for attempt in range(max_attempts):
        try:
            resp = requests.request(method, url, **kwargs)
            if resp.status_code not in RETRY_STATUSES:
                return resp
            if attempt == max_attempts - 1:
                raise FetchError(
                    f"Failed {url} after 3 retries: {resp.status_code}"
                )
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                if retry_after and retry_after.strip().isdigit():
                    time.sleep(int(retry_after.strip()))
                else:
                    time.sleep(RETRY_DELAYS[attempt])
            else:
                time.sleep(RETRY_DELAYS[attempt])
        except requests.RequestException as e:
            last_exc = e
            if attempt == max_attempts - 1:
                raise FetchError(f"Request failed after retries: {url}") from last_exc
            time.sleep(RETRY_DELAYS[attempt])
    raise FetchError(f"Request failed: {url}") from last_exc
