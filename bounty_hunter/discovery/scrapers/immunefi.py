import logging
from typing import AsyncIterator
from ..models.bounty import Bounty, BountyCategory
from .base import BaseScraper

logger = logging.getLogger(__name__)

class ImmunefiScraper(BaseScraper):
    SOURCE_NAME = "immunefi"
    RATE_LIMIT_SECONDS = 2.0
    API_URL = "https://immunefi.com/bounty/all/json/"

    async def fetch(self) -> AsyncIterator[Bounty]:
        try:
            resp = await self._get(self.API_URL)
            data = resp.json()
            for item in (data if isinstance(data, list) else data.get("bounties", [])):
                try:
                    max_reward = item.get("maximumReward", 0) or 0
                    yield Bounty(
                        source=self.SOURCE_NAME,
                        external_id=str(item.get("id", item.get("project", ""))),
                        title=item.get("project", "Unknown") + " Bug Bounty",
                        description=item.get("description", ""),
                        url=f"https://immunefi.com/bounty/{item.get('slug', '')}",
                        reward_usd=float(max_reward) if max_reward else None,
                        reward_token="USD",
                        category=BountyCategory.SECURITY,
                        tags=["security", "bug-bounty", "web3"],
                    )
                except Exception as e:
                    logger.warning(f"[immunefi] Parse error: {e}")
        except Exception as e:
            logger.error(f"[immunefi] Fetch error: {e}")
