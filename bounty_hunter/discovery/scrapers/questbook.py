import logging
import httpx
from datetime import datetime, timezone, timedelta
from ..models.bounty import Bounty, BountyCategory
from .base import BaseScraper

logger = logging.getLogger(__name__)

class QuestbookScraper(BaseScraper):
    SOURCE_NAME = "questbook"

    GRANTS_API = "https://questbook-api.fly.dev/graphql"

    async def fetch(self):
        query = """
        {
          grants(filter: {acceptingApplications: true}, first: 50) {
            edges {
              node {
                id
                title
                summary
                link
                reward { committed asset }
                createdAt
                workspace { title }
              }
            }
          }
        }
        """
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    self.GRANTS_API,
                    json={"query": query},
                    headers={"Content-Type": "application/json"}
                )
                data = resp.json()
                grants = data.get("data", {}).get("grants", {}).get("edges", [])
                logger.info(f"[questbook] Found {len(grants)} grants")

                for edge in grants:
                    g = edge.get("node", {})
                    reward_raw = g.get("reward", {}).get("committed", 0)
                    try:
                        reward = float(reward_raw) / 1e18  # Convert from wei
                    except:
                        reward = 0

                    yield Bounty(
                        source=self.SOURCE_NAME,
                        external_id=g.get("id", ""),
                        title=g.get("title", ""),
                        description=(g.get("summary") or "")[:500],
                        url=g.get("link", "https://questbook.app"),
                        reward_usd=min(reward, 9999),
                        reward_token="USDC",
                        category=BountyCategory.OTHER,
                        tags=[],
                    )
        except Exception as e:
            logger.warning(f"[questbook] Error: {e}")
