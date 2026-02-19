"""
Base scraper — όλοι οι scrapers κληρονομούν από εδώ.
"""
import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import AsyncIterator

import httpx

from ..models.bounty import Bounty

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """
    Abstract base για όλους τους bounty scrapers.

    Κάθε subclass υλοποιεί μόνο το `fetch()`.
    Το rate limiting, retry logic, και error handling
    γίνονται εδώ αυτόματα.
    """

    # Override στα subclasses
    SOURCE_NAME: str = "unknown"
    RATE_LIMIT_SECONDS: float = 2.0   # καθυστέρηση μεταξύ requests
    MAX_RETRIES: int = 3
    TIMEOUT_SECONDS: float = 15.0

    def __init__(self, config: dict = None):
        self.config = config or {}
        self._client: httpx.AsyncClient | None = None
        self._last_request_at: datetime | None = None
        self.stats = {
            "total_fetched": 0,
            "errors": 0,
            "last_run": None,
        }

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            timeout=self.TIMEOUT_SECONDS,
            headers=self._default_headers(),
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    def _default_headers(self) -> dict:
        return {
            "User-Agent": "Mozilla/5.0 BountyHunterBot/1.0",
            "Accept": "application/json",
        }

    async def _rate_limit(self):
        """Σέβεται το rate limit της πλατφόρμας."""
        if self._last_request_at:
            elapsed = (datetime.utcnow() - self._last_request_at).total_seconds()
            wait = self.RATE_LIMIT_SECONDS - elapsed
            if wait > 0:
                await asyncio.sleep(wait)
        self._last_request_at = datetime.utcnow()

    async def _get(self, url: str, **kwargs) -> httpx.Response:
        """HTTP GET με retry και rate limiting."""
        await self._rate_limit()
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                resp = await self._client.get(url, **kwargs)
                resp.raise_for_status()
                return resp
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    wait = 60 * attempt
                    logger.warning(f"[{self.SOURCE_NAME}] Rate limited. Wait {wait}s...")
                    await asyncio.sleep(wait)
                elif e.response.status_code >= 500:
                    logger.warning(f"[{self.SOURCE_NAME}] Server error {e.response.status_code}, retry {attempt}/{self.MAX_RETRIES}")
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                logger.warning(f"[{self.SOURCE_NAME}] Network error: {e}, retry {attempt}/{self.MAX_RETRIES}")
                await asyncio.sleep(2 ** attempt)
        raise RuntimeError(f"[{self.SOURCE_NAME}] Failed after {self.MAX_RETRIES} retries: {url}")

    async def _post(self, url: str, **kwargs) -> httpx.Response:
        """HTTP POST με retry."""
        await self._rate_limit()
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                resp = await self._client.post(url, **kwargs)
                resp.raise_for_status()
                return resp
            except (httpx.HTTPError, httpx.TimeoutException) as e:
                logger.warning(f"[{self.SOURCE_NAME}] POST error: {e}, retry {attempt}")
                await asyncio.sleep(2 ** attempt)
        raise RuntimeError(f"[{self.SOURCE_NAME}] POST failed: {url}")

    @abstractmethod
    async def fetch(self) -> AsyncIterator[Bounty]:
        """
        Yield bounties από την πλατφόρμα.
        Κάθε scraper υλοποιεί αυτή τη μέθοδο.
        """
        ...

    async def run(self) -> list[Bounty]:
        """Τρέχει τον scraper και επιστρέφει λίστα bounties."""
        bounties = []
        self.stats["last_run"] = datetime.utcnow()
        logger.info(f"[{self.SOURCE_NAME}] Starting scraper...")
        try:
            async with self:
                async for bounty in self.fetch():
                    bounties.append(bounty)
                    self.stats["total_fetched"] += 1
                    logger.debug(f"[{self.SOURCE_NAME}] Found: {bounty.title[:60]}")
        except Exception as e:
            self.stats["errors"] += 1
            logger.error(f"[{self.SOURCE_NAME}] Fatal error: {e}", exc_info=True)
        logger.info(f"[{self.SOURCE_NAME}] Done. Found {len(bounties)} bounties.")
        return bounties
