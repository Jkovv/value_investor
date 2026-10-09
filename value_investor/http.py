"""03 · http: one shared, rate-limited session for the SEC APIs.

data.sec.gov allows 10 requests/second per client and answers 403 to
anything without a contact User-Agent. Every SEC call goes through get_json()
so the limit holds no matter how many threads are fetching.
"""

import logging
import threading
import time

import requests

from value_investor import config

logger = logging.getLogger(__name__)


class RateLimiter:
    def __init__(self, per_second: float):
        self.interval = 1.0 / per_second
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            if self._next > now:
                time.sleep(self._next - now)
                now = self._next
            self._next = now + self.interval


_limiter = RateLimiter(config.SEC_REQUESTS_PER_SECOND)
_local = threading.local()


def _session() -> requests.Session:
    if not hasattr(_local, "session"):
        config.check_sec_user_agent()
        s = requests.Session()
        s.headers.update({"User-Agent": config.SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"})
        _local.session = s
    return _local.session


class NotFound(Exception):
    pass


def get_json(url: str, retries: int = 4) -> dict:
    for attempt in range(retries + 1):
        _limiter.wait()
        try:
            resp = _session().get(url, timeout=30)
        except requests.RequestException as exc:
            if attempt == retries:
                raise
            logger.debug("retrying %s after %s", url, exc)
            time.sleep(2 ** attempt)
            continue
        if resp.status_code == 404:
            raise NotFound(url)
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries:
            time.sleep(2 ** attempt + 1)
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(f"gave up on {url}")
