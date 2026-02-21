import logging
from typing import AsyncIterator
from ..models.bounty import Bounty, BountyCategory
from .base import BaseScraper

logger = logging.getLogger(__name__)

class SuperteamScraper(BaseScraper):
    SOURCE_NAME = "superteam"
    RATE_LIMIT_SECONDS = 2.0
    API_URL = "https://earn.superteam.fun/api/listings/?type=bounty&status=open&take=50"

    async def fetch(self) -> AsyncIterator[Bounty]:
        try:
            resp = await self._get(self.API_URL, follow_redirects=True)
            items = resp.json() if isinstance(resp.json(), list) else resp.json().get("bounties", [])
            for item in items:
                try:
                    yield Bounty(
                        source=self.SOURCE_NAME,
                        external_id=str(item.get("id", "")),
                        title=item.get("title", ""),
                        description=item.get("description", ""),
                        url=f"https://earn.superteam.fun/listings/bounties/{item.get('slug','')}",
                        reward_usd=float(item.get("rewardAmount", 0) or 0),
                        reward_token=item.get("token", "USDC"),
                        category=BountyCategory.OTHER,
                        tags=item.get("skills", []),
                    )
                except Exception as e:
                    logger.warning(f"[superteam] Parse error: {e}")
        except Exception as e:
            logger.error(f"[superteam] Fetch error: {e}")
