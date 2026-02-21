import os
import logging
import re
from typing import AsyncIterator
from datetime import datetime, timezone, timedelta
from ..models.bounty import Bounty, BountyCategory
from .base import BaseScraper

logger = logging.getLogger(__name__)

WEB3_ORGS = [
    "ethereum",
    "gitcoinco",
    "uniswap",
    "aave",
    "compound-finance",
    "OpenZeppelin",
]

def get_labels() -> list:
    import json
    try:
        with open("/root/bounty_hunter/keywords.json") as f:
            return json.load(f).get("keywords", ["bounty", "funded", "grant", "reward"])[:15]
    except:
        return ["bounty", "Bounty", "funded", "grant", "reward"]

class GitHubScraper(BaseScraper):
    SOURCE_NAME = "github"
    RATE_LIMIT_SECONDS = 2.0

    def __init__(self, token: str = "", config: dict = None):
        import os
        super().__init__(config)
        self.token = token or os.environ.get("GITHUB_TOKEN", "")

    def _default_headers(self) -> dict:
        h = super()._default_headers()
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        h["Accept"] = "application/vnd.github+json"
        return h

    def _parse_reward(self, text: str):
        patterns = [
            r'\$(\d+(?:,\d+)?(?:\.\d+)?)\s*(?:USDC|USD)?',
            r'(\d+(?:,\d+)?)\s*USDC',
            r'(\d+(?:\.\d+)?)\s*ETH',
        ]
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                try:
                    return float(m.group(1).replace(",", ""))
                except:
                    pass
        return None

    def _detect_category(self, text: str) -> BountyCategory:
        text = text.lower()
        if any(w in text for w in ["solidity", "smart contract", "audit", "security"]):
            return BountyCategory.CODE
        if any(w in text for w in ["design", "ui", "ux"]):
            return BountyCategory.DESIGN
        if any(w in text for w in ["write", "doc", "article", "content"]):
            return BountyCategory.WRITING
        return BountyCategory.OTHER

    async def fetch(self) -> AsyncIterator[Bounty]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=90)
        seen = set()

        for org in WEB3_ORGS:
            for label in get_labels():
                url = (
                    f"https://api.github.com/search/issues"
                    f"?q=org%3A{org}+label%3A{label}+is%3Aopen+is%3Aissue"
                    f"&sort=created&order=desc&per_page=20"
                )
                try:
                    resp = await self._get(url)
                    if resp.status_code != 200:
                        continue
                    for item in resp.json().get("items", []):
                        issue_id = str(item.get("id", ""))
                        if issue_id in seen:
                            continue
                        seen.add(issue_id)

                        created_at = item.get("created_at", "")
                        try:
                            posted_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                            if posted_at < cutoff:
                                continue
                        except:
                            pass

                        title = item.get("title", "")
                        body = item.get("body", "") or ""
                        html_url = item.get("html_url", "")
                        repo = item.get("repository_url", "").split("/")[-1]
                        reward = self._parse_reward(title + " " + body) or 50.0

                        yield Bounty(
                            source=self.SOURCE_NAME,
                            external_id=issue_id,
                            title=f"[{repo}] {title}",
                            description=body[:500],
                            url=html_url,
                            reward_usd=reward,
                            reward_token="USDC",
                            category=self._detect_category(title + body),
                            tags=[label],
                        )
                except Exception as e:
                    logger.warning(f"[github] {org}/{label}: {e}")
