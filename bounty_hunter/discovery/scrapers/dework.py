import logging
import httpx
from datetime import datetime, timezone, timedelta
from ..models.bounty import Bounty, BountyCategory
from .base import BaseScraper

logger = logging.getLogger(__name__)

class DeworkScraper(BaseScraper):
    SOURCE_NAME = "dework"

    async def fetch(self):
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        try:
            # Dework GraphQL API
            query = """
            {
              tasks(filter: {status: TODO, rewardType: BOUNTY}, first: 50) {
                edges {
                  node {
                    id
                    name
                    description
                    permalink
                    reward { amount currency { symbol } }
                    createdAt
                    tags { label }
                  }
                }
              }
            }
            """
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    "https://api.dework.xyz/graphql",
                    json={"query": query},
                    headers={"Content-Type": "application/json"}
                )
                data = resp.json()
                tasks = data.get("data", {}).get("tasks", {}).get("edges", [])
                logger.info(f"[dework] Found {len(tasks)} tasks")

                for edge in tasks:
                    task = edge.get("node", {})
                    created = task.get("createdAt", "")
                    try:
                        posted_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
                        if posted_at < cutoff:
                            continue
                    except:
                        pass

                    reward = task.get("reward", {})
                    amount = float(reward.get("amount", 0) or 0)
                    currency = reward.get("currency", {}).get("symbol", "USD")

                    yield Bounty(
                        source=self.SOURCE_NAME,
                        external_id=task.get("id", ""),
                        title=task.get("name", ""),
                        description=(task.get("description") or "")[:500],
                        url=f"https://app.dework.xyz{task.get('permalink', '')}",
                        reward_usd=amount,
                        reward_token=currency,
                        category=BountyCategory.OTHER,
                        tags=[t.get("label","") for t in task.get("tags", [])],
                    )
        except Exception as e:
            logger.warning(f"[dework] Error: {e}")
