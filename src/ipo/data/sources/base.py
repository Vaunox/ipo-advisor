"""Polite-scraper contract primitives (Deep Dive #1, Module 3).

Two source-agnostic building blocks every adapter shares:

* ``RawCache`` — an immutable, content-hashed, on-disk cache of raw responses.
  Parsing is a pure function of a cached raw; re-parsing never re-fetches.
* ``PoliteClient`` — a rate-limited, backing-off HTTP client with an honest
  ``User-Agent`` that respects ``robots.txt``.

Nothing here knows about a specific source; concrete adapters in this package
compose these. A single source's failure must degrade one field, never crash the
run — callers handle ``SourceError`` and continue (Deep Dive #1, Module 3).
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.robotparser
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

from ipo.core.calendar import now_ist
from ipo.core.logging import get_logger
from ipo.core.types import RawResponse

_log = get_logger("ipo.data.sources")


class SourceError(RuntimeError):
    """A recoverable failure fetching or parsing one source (does not crash the run)."""


def compute_hash(content: str) -> str:
    """Return the SHA-256 hex digest of ``content`` (the cache key and drift tripwire)."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RawCache:
    """Immutable on-disk cache of raw responses, keyed by ``source`` + content identity.

    A cached entry is written exactly once and never mutated; a correction is a new
    entry under a new key. ``get`` returns the stored ``RawResponse`` or ``None``;
    ``store`` persists one. The cache key is derived from the source and the request
    identity (URL + params), so an unchanged request re-reads rather than re-fetches.
    """

    root: Path

    def _key(self, source: str, request_id: str) -> str:
        return compute_hash(f"{source}::{request_id}")

    def _path(self, source: str, request_id: str) -> Path:
        return self.root / source / f"{self._key(source, request_id)}.json"

    def get(self, source: str, request_id: str) -> RawResponse | None:
        """Return the cached response for this request, or ``None`` if absent."""
        path = self._path(source, request_id)
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return RawResponse.model_validate(data)

    def store(self, response: RawResponse, *, request_id: str) -> None:
        """Persist ``response`` immutably. A second store for the same key is a no-op."""
        path = self._path(response.source, request_id)
        if path.exists():
            return  # immutable: never overwrite
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(response.model_dump_json(), encoding="utf-8")


class PoliteClient:
    """Rate-limited HTTP client with backoff, an honest UA, and robots awareness.

    Args:
        user_agent: Sent on every request (honest identification).
        rate_limit_per_sec: Maximum request rate; calls block to honor it.
        backoff_factor: Exponential backoff base between retries (seconds).
        max_retries: Attempts before raising ``SourceError``.
        timeout: Per-request timeout in seconds.
        respect_robots: When True, disallowed URLs raise ``SourceError``.
        session: Injectable ``requests.Session`` (for tests).
        sleep: Injectable sleep function (for deterministic tests).
    """

    def __init__(
        self,
        *,
        user_agent: str,
        rate_limit_per_sec: float = 0.5,
        backoff_factor: float = 2.0,
        max_retries: int = 4,
        timeout: float = 20.0,
        respect_robots: bool = True,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Build a polite client with the given rate/backoff/robots policy."""
        self._ua = user_agent
        self._min_interval = 1.0 / rate_limit_per_sec if rate_limit_per_sec > 0 else 0.0
        self._backoff = backoff_factor
        self._max_retries = max_retries
        self._timeout = timeout
        self._respect_robots = respect_robots
        self._session = session if session is not None else requests.Session()
        self._sleep = sleep
        self._last_request_at: float = 0.0
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}

    def _throttle(self) -> None:
        if self._min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        wait = self._min_interval - elapsed
        if wait > 0:
            self._sleep(wait)
        self._last_request_at = time.monotonic()

    def _robots_allows(self, url: str) -> bool:
        if not self._respect_robots:
            return True
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        parser = self._robots.get(origin)
        if parser is None:
            parser = urllib.robotparser.RobotFileParser()
            parser.set_url(urljoin(origin, "/robots.txt"))
            try:
                parser.read()
            except OSError:
                # If robots.txt is unreachable, be conservative but do not crash:
                # default-allow only the specific URL, logged for visibility.
                _log.warning("robots_unreachable", extra={"origin": origin})
                self._robots[origin] = parser
                return True
            self._robots[origin] = parser
        return parser.can_fetch(self._ua, url)

    def fetch(
        self,
        source: str,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> RawResponse:
        """Fetch ``url`` politely and return a hashed ``RawResponse``.

        Raises:
            SourceError: if robots disallows the URL or all retries fail.
        """
        if not self._robots_allows(url):
            raise SourceError(f"robots.txt disallows fetching {url}")

        request_headers = {"User-Agent": self._ua}
        if headers:
            request_headers.update(headers)

        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            self._throttle()
            try:
                resp = self._session.get(
                    url, params=params, headers=request_headers, timeout=self._timeout
                )
                resp.raise_for_status()
                content = resp.text
                return RawResponse(
                    source=source,
                    url=resp.url,
                    fetched_at=now_ist(),
                    content=content,
                    content_hash=compute_hash(content),
                )
            except requests.RequestException as exc:  # network/HTTP error -> retry
                last_exc = exc
                delay = self._backoff * (2**attempt)
                _log.warning(
                    "fetch_retry",
                    extra={"source": source, "url": url, "attempt": attempt + 1, "delay": delay},
                )
                self._sleep(delay)
        raise SourceError(f"failed to fetch {url} after {self._max_retries} attempts") from last_exc

    def fetch_bytes(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> bytes:
        """Fetch a binary resource (e.g. a bhavcopy zip) politely; returns raw bytes.

        Same rate-limit/backoff as ``fetch`` but returns ``resp.content`` (no caching;
        the caller decides how to cache the decoded payload).

        Raises:
            SourceError: if all retries fail.
        """
        request_headers = {"User-Agent": self._ua}
        if headers:
            request_headers.update(headers)

        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            self._throttle()
            try:
                resp = self._session.get(url, headers=request_headers, timeout=self._timeout)
                resp.raise_for_status()
                return resp.content
            except requests.RequestException as exc:
                last_exc = exc
                self._sleep(self._backoff * (2**attempt))
        raise SourceError(
            f"failed to fetch bytes {url} after {self._max_retries} attempts"
        ) from last_exc

    def get_or_fetch(
        self,
        cache: RawCache,
        source: str,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> RawResponse:
        """Return the cached raw for this request, fetching and caching it on a miss."""
        request_id = url if not params else f"{url}?{json.dumps(dict(params), sort_keys=True)}"
        cached = cache.get(source, request_id)
        if cached is not None:
            return cached
        response = self.fetch(source, url, params=params, headers=headers)
        cache.store(response, request_id=request_id)
        return response
