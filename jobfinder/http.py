"""One shared HTTP session with a polite user agent, timeouts and retries."""
from __future__ import annotations

import time

import requests

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36 job-finder (personal job search)"
)

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-CA,en;q=0.9"})


def get(url: str, **kw) -> requests.Response:
    return _request("GET", url, **kw)


def post(url: str, **kw) -> requests.Response:
    return _request("POST", url, **kw)


def _request(method: str, url: str, retries: int = 2, **kw) -> requests.Response:
    kw.setdefault("timeout", 30)
    last = None
    for attempt in range(retries + 1):
        try:
            r = _session.request(method, url, **kw)
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(3 * (attempt + 1))
                continue
            r.raise_for_status()
            time.sleep(0.5)  # be polite
            return r
        except requests.RequestException as e:  # noqa: PERF203
            last = e
            if attempt < retries:
                time.sleep(3 * (attempt + 1))
    raise last  # type: ignore[misc]
