import logging
import httpx
from ..models.bounty import Bounty, BountyCategory
from .base import BaseScraper

logger = logging.getLogger(__name__)

class Layer3Scraper(BaseScraper):
    SOURCE_NAME = "layer3"

    async def fetch(self):
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(
                    "https://layer3.xyz/api/bounties",
                    params={"status": "active", "limit": 50},
                    headers={"Accept": "application/json"}
                )
                if resp.status_code != 200:
                    logger.warning(f"[layer3] HTTP {resp.status_code}")
                    return
                
                data = resp.json()
                bounties = data if isinstance(data, list) else data.get("bounties", data.get("data", []))
                logger.info(f"[layer3] Found {len(bounties)} bounties")

                for b in bounties:
                    reward = float(b.get("reward", 0) or b.get("rewardAmount", 0) or 0)
                    yield Bounty(
                        source=self.SOURCE_NAME,
                        external_id=str(b.get("id", "")),
                        title=b.get("title", b.get("name", "")),
                        description=(b.get("description", "") or "")[:500],
                        url=f"https://layer3.xyz/bounties/{b.get('slug', b.get('id', ''))}",
                        reward_usd=reward,
                        reward_token=b.get("rewardToken", "USDC"),
                        category=BountyCategory.OTHER,
                        tags=[],
                    )
        except Exception as e:
            logger.warning(f"[layer3] Error: {e}")
