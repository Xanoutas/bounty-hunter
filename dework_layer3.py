"""
Dework Scraper — Web3 task & bounty platform
https://dework.xyz / https://api.dework.xyz/graphql
"""
import logging
from datetime import datetime
from typing import AsyncIterator

from ..models.bounty import Bounty, BountyCategory
from .base import BaseScraper

logger = logging.getLogger(__name__)

DEWORK_GRAPHQL = "https://api.dework.xyz/graphql"

DEWORK_QUERY = """
query GetOpenTasks($limit: Int!, $offset: Int!) {
  tasks(
    filter: {
      statuses: [TODO]
      rewardNotNull: true
    }
    limit: $limit
    offset: $offset
    sortBy: CREATED_AT
    sortDirection: DESC
  ) {
    id
    name
    description
    status
    dueDate
    createdAt
    reward {
      amount
      currency
      token {
        symbol
        usdPrice
      }
    }
    project {
      name
      organization {
        name
      }
    }
    tags {
      label
    }
    permalink
    assignees {
      username
    }
  }
}
"""


class DeworkScraper(BaseScraper):
    """
    Scraper για Dework — Web3 native task management.
    Εδώ βρίσκονται DAOs που πληρώνουν για tasks/bounties.
    """

    SOURCE_NAME = "dework"
    RATE_LIMIT_SECONDS = 2.0

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.min_reward_usd = (config or {}).get("min_reward_usd", 10)
        self.max_results = (config or {}).get("max_results", 50)

    async def fetch(self) -> AsyncIterator[Bounty]:
        offset = 0
        limit = 25

        while offset < self.max_results:
            try:
                resp = await self._post(
                    DEWORK_GRAPHQL,
                    json={
                        "query": DEWORK_QUERY,
                        "variables": {
                            "limit": min(limit, self.max_results - offset),
                            "offset": offset,
                        },
                    },
                )
                data = resp.json()
                tasks = data.get("data", {}).get("tasks", [])

                if not tasks:
                    break

                for task in tasks:
                    bounty = self._parse_task(task)
                    if bounty:
                        yield bounty

                offset += limit
                if len(tasks) < limit:
                    break

            except Exception as e:
                logger.error(f"[dework] GraphQL error: {e}")
                break

    def _parse_task(self, task: dict) -> Bounty | None:
        try:
            reward_info = task.get("reward") or {}
            token_info = reward_info.get("token") or {}

            reward_amount = float(reward_info.get("amount", 0) or 0)
            reward_token = token_info.get("symbol", "USDC")
            usd_price = float(token_info.get("usdPrice") or 1)
            reward_usd = reward_amount * usd_price if reward_amount else None

            if reward_usd and reward_usd < self.min_reward_usd:
                return None

            project = task.get("project") or {}
            org = project.get("organization") or {}
            tags = [t["label"] for t in (task.get("tags") or [])]

            created_at = task.get("createdAt")
            due_date = task.get("dueDate")

            posted_at = None
            deadline = None
            if created_at:
                try:
                    posted_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                except ValueError:
                    pass
            if due_date:
                try:
                    deadline = datetime.fromisoformat(due_date.replace("Z", "+00:00"))
                except ValueError:
                    pass

            description = task.get("description") or ""
            title = task.get("name", "Dework Task")
            org_name = org.get("name", "")
            project_name = project.get("name", "")

            category = self._detect_category(title + " " + description)

            return Bounty(
                source=self.SOURCE_NAME,
                external_id=task["id"],
                url=task.get("permalink", f"https://app.dework.xyz/tasks/{task['id']}"),
                title=f"[{org_name}/{project_name}] {title}",
                description=description[:2000],
                category=category,
                reward_usd=reward_usd,
                reward_token=reward_token,
                reward_amount=reward_amount,
                posted_at=posted_at,
                deadline=deadline,
                poster_handle=org_name,
                poster_platform="dework",
                tags=tags[:10],
                raw_data=task,
            )
        except Exception as e:
            logger.warning(f"[dework] Failed to parse task: {e}")
            return None

    def _detect_category(self, text: str) -> BountyCategory:
        t = text.lower()
        if any(w in t for w in ["dev", "code", "smart contract", "frontend", "backend", "bug"]):
            return BountyCategory.CODE
        if any(w in t for w in ["design", "figma", "ui", "ux"]):
            return BountyCategory.DESIGN
        if any(w in t for w in ["write", "content", "blog", "docs"]):
            return BountyCategory.WRITING
        if any(w in t for w in ["community", "ambassador", "twitter", "discord"]):
            return BountyCategory.COMMUNITY
        return BountyCategory.OTHER


# ---------------------------------------------------------------------------
# Layer3 Scraper (quests / bounties)
# ---------------------------------------------------------------------------

LAYER3_API = "https://layer3.xyz/api"


class Layer3Scraper(BaseScraper):
    """
    Scraper για Layer3.xyz — quest & bounty platform.
    Χρησιμοποιεί το public REST API.
    """

    SOURCE_NAME = "layer3"
    RATE_LIMIT_SECONDS = 2.5

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.max_results = (config or {}).get("max_results", 30)

    async def fetch(self) -> AsyncIterator[Bounty]:
        try:
            resp = await self._get(
                f"{LAYER3_API}/bounties",
                params={"status": "active", "limit": self.max_results},
            )
            items = resp.json()
            if isinstance(items, dict):
                items = items.get("data", items.get("bounties", []))

            for item in items:
                bounty = self._parse(item)
                if bounty:
                    yield bounty
        except Exception as e:
            logger.error(f"[layer3] Fetch error: {e}")

    def _parse(self, item: dict) -> Bounty | None:
        try:
            reward = item.get("reward") or {}
            reward_usd = float(reward.get("usd_value") or reward.get("amount") or 0) or None
            reward_token = reward.get("currency", "USDC")

            return Bounty(
                source=self.SOURCE_NAME,
                external_id=str(item.get("id", "")),
                url=item.get("url", f"https://layer3.xyz/bounties/{item.get('slug','')}"),
                title=item.get("title", "Layer3 Quest"),
                description=item.get("description", "")[:2000],
                category=BountyCategory.COMMUNITY,
                reward_usd=reward_usd,
                reward_token=reward_token,
                poster_platform="layer3",
                tags=item.get("tags", [])[:10],
                raw_data=item,
            )
        except Exception as e:
            logger.warning(f"[layer3] Parse error: {e}")
            return None
