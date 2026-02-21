"""
Gitcoin Scraper
Χρησιμοποιεί το Gitcoin GraphQL API για bounties & grants.

Gitcoin v2 API: https://indexer-production.fly.dev/graphql
"""
import logging
from datetime import datetime
from typing import AsyncIterator

from ..models.bounty import Bounty, BountyCategory
from .base import BaseScraper

logger = logging.getLogger(__name__)

GITCOIN_GRAPHQL = "https://indexer-production.fly.dev/graphql"

# GraphQL query για open applications / bounties
BOUNTIES_QUERY = """
query GetBounties($first: Int!, $offset: Int!) {
  applications(
    first: $first
    offset: $offset
    filter: {
      status: { in: [PENDING, IN_REVIEW] }
    }
    orderBy: CREATED_AT_BLOCK_DESC
  ) {
    id
    project {
      name
      description
      website
      projectType
    }
    round {
      roundMetadata
      matchingDistribution
    }
    metadata
    statusSnapshots {
      status
      updatedAtBlock
    }
    createdAtBlock
    totalAmountDonatedInUsd
  }
}
"""

# Gitcoin Bounties (legacy + new) μέσω REST
GITCOIN_REST = "https://gitcoin.co/api/v0.1/bounties"


class GitcoinScraper(BaseScraper):
    """
    Scraper για Gitcoin bounties.
    Χρησιμοποιεί REST API για bounties και GraphQL για grants.
    """

    SOURCE_NAME = "gitcoin"
    RATE_LIMIT_SECONDS = 2.0

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.min_reward_usd = (config or {}).get("min_reward_usd", 10)
        self.max_results = (config or {}).get("max_results", 50)
        self.network = (config or {}).get("network", None)  # π.χ. "1" για Ethereum mainnet

    async def fetch(self) -> AsyncIterator[Bounty]:
        """Fetch από REST API (bounties) και GraphQL (grants)."""
        async for bounty in self._fetch_rest_bounties():
            yield bounty

    async def _fetch_rest_bounties(self) -> AsyncIterator[Bounty]:
        """Gitcoin REST API — open bounties."""
        params = {
            "status": "open",
            "order_by": "-web3_created",
            "limit": min(50, self.max_results),
            "offset": 0,
        }
        if self.network:
            params["network"] = self.network

        fetched = 0
        while fetched < self.max_results:
            resp = await self._get(GITCOIN_REST, params=params)
            data = resp.json()

            # Gitcoin επιστρέφει list ή dict με "results"
            if isinstance(data, list):
                items = data
            else:
                items = data.get("results", [])

            if not items:
                break

            for item in items:
                bounty = self._parse_bounty(item)
                if bounty:
                    yield bounty
                    fetched += 1

            # Pagination
            if len(items) < params["limit"]:
                break
            params["offset"] += params["limit"]

    def _parse_bounty(self, item: dict) -> Bounty | None:
        """Μετατρέπει Gitcoin bounty JSON σε Bounty object."""
        try:
            bounty_id = str(item.get("pk") or item.get("id", ""))
            title = item.get("title", "Untitled")
            description = item.get("issue_description", "") or item.get("description", "")

            # Reward
            reward_usd = None
            reward_token = None
            reward_amount = None

            value_in_token = item.get("value_in_token")
            token_name = item.get("token_name", "ETH")
            value_in_usdt = item.get("value_in_usdt")

            if value_in_usdt:
                reward_usd = float(value_in_usdt)
            if value_in_token:
                reward_amount = float(value_in_token)
                reward_token = token_name

            # Φιλτράρισμα βάσει minimum reward
            if reward_usd and reward_usd < self.min_reward_usd:
                return None

            # Dates
            web3_created = item.get("web3_created")
            expires_date = item.get("expires_date")

            posted_at = None
            deadline = None
            if web3_created:
                try:
                    posted_at = datetime.fromisoformat(web3_created.replace("Z", "+00:00"))
                except ValueError:
                    pass
            if expires_date:
                try:
                    deadline = datetime.fromisoformat(expires_date.replace("Z", "+00:00"))
                except ValueError:
                    pass

            # Keywords → category
            keywords = item.get("keywords", [])
            if isinstance(keywords, str):
                keywords = [k.strip() for k in keywords.split(",")]
            category = self._detect_category(title + " " + " ".join(keywords))

            # Bounty URL
            github_url = item.get("github_url", "")
            gitcoin_url = f"https://gitcoin.co/issue/{bounty_id}" if bounty_id else github_url

            funder = item.get("funder_profile_handle") or item.get("org_name", "")

            return Bounty(
                source=self.SOURCE_NAME,
                external_id=bounty_id,
                url=gitcoin_url,
                title=title,
                description=description[:2000],
                category=category,
                reward_usd=reward_usd,
                reward_token=reward_token,
                reward_amount=reward_amount,
                posted_at=posted_at,
                deadline=deadline,
                poster_handle=funder,
                poster_platform="gitcoin",
                contact_url=github_url,
                tags=keywords[:10],
                raw_data=item,
            )
        except Exception as e:
            logger.warning(f"[gitcoin] Failed to parse bounty: {e}")
            return None

    def _detect_category(self, text: str) -> BountyCategory:
        t = text.lower()
        if any(w in t for w in ["smart contract", "solidity", "rust", "python", "javascript", "bug", "frontend", "backend", "dev"]):
            return BountyCategory.CODE
        if any(w in t for w in ["write", "documentation", "docs", "blog", "content"]):
            return BountyCategory.WRITING
        if any(w in t for w in ["design", "ui", "ux"]):
            return BountyCategory.DESIGN
        if any(w in t for w in ["research", "analysis"]):
            return BountyCategory.RESEARCH
        return BountyCategory.OTHER
