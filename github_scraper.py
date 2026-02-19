"""
GitHub Issues Scraper
Ψάχνει GitHub issues με label "bounty" ή "good first issue" + reward.

Χρειάζεσαι GitHub Personal Access Token:
https://github.com/settings/tokens
"""
import logging
import re
from datetime import datetime
from typing import AsyncIterator

from ..models.bounty import Bounty, BountyCategory
from .base import BaseScraper

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"

# Labels που ψάχνουμε
BOUNTY_LABELS = ["bounty", "Bounty", "reward", "funded", "grant"]

# Γνωστά Web3 repos (μπορείς να προσθέσεις κι άλλα)
WEB3_ORGS = [
    "ethereum",
    "gitcoinco",
    "uniswap",
    "aave",
    "compound-finance",
    "OpenZeppelin",
    "smartcontractkit",
    "thirdweb-dev",
    "safe-global",
]


class GitHubScraper(BaseScraper):
    """
    Scraper για GitHub bounty issues.
    Ψάχνει issues με bounty labels σε Web3 orgs.
    """

    SOURCE_NAME = "github"
    RATE_LIMIT_SECONDS = 1.5  # GitHub: 30 requests/min για authenticated

    def __init__(self, token: str, config: dict = None):
        super().__init__(config)
        self.token = token
        self.orgs = (config or {}).get("orgs", WEB3_ORGS)
        self.extra_labels = (config or {}).get("labels", [])
        self.min_reward_usd = (config or {}).get("min_reward_usd", 0)
        self.max_per_org = (config or {}).get("max_per_org", 20)

    def _default_headers(self) -> dict:
        return {
            **super()._default_headers(),
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def fetch(self) -> AsyncIterator[Bounty]:
        """Ψάχνει σε κάθε org για bounty issues."""
        all_labels = list(set(BOUNTY_LABELS + self.extra_labels))

        for org in self.orgs:
            for label in all_labels:
                async for bounty in self._fetch_org_issues(org, label):
                    yield bounty

        # Επίσης global search
        async for bounty in self._global_search():
            yield bounty

    async def _fetch_org_issues(self, org: str, label: str) -> AsyncIterator[Bounty]:
        """Fetch issues από συγκεκριμένο GitHub org."""
        try:
            resp = await self._get(
                f"{GITHUB_API}/search/issues",
                params={
                    "q": f"org:{org} label:{label} is:open is:issue",
                    "sort": "created",
                    "order": "desc",
                    "per_page": self.max_per_org,
                },
            )
            data = resp.json()
            for item in data.get("items", []):
                bounty = self._parse_issue(item, org)
                if bounty:
                    yield bounty
        except Exception as e:
            logger.warning(f"[github] Error fetching {org}/{label}: {e}")

    async def _global_search(self) -> AsyncIterator[Bounty]:
        """Global GitHub search για web3 bounties."""
        queries = [
            'label:bounty is:open is:issue language:solidity',
            'label:bounty is:open is:issue "web3" OR "blockchain" OR "defi"',
            '"bounty" "$" is:open is:issue topic:web3',
        ]
        for query in queries:
            try:
                resp = await self._get(
                    f"{GITHUB_API}/search/issues",
                    params={
                        "q": query,
                        "sort": "created",
                        "order": "desc",
                        "per_page": 20,
                    },
                )
                data = resp.json()
                for item in data.get("items", []):
                    bounty = self._parse_issue(item)
                    if bounty:
                        yield bounty
            except Exception as e:
                logger.warning(f"[github] Global search error: {e}")

    def _parse_issue(self, item: dict, org: str = "") -> Bounty | None:
        """Μετατρέπει GitHub issue σε Bounty."""
        try:
            issue_id = str(item["id"])
            title = item.get("title", "")
            body = item.get("body", "") or ""
            url = item.get("html_url", "")
            repo_url = item.get("repository_url", "")
            repo_name = repo_url.split("/")[-1] if repo_url else ""

            # Ψάχνουμε reward στον τίτλο και το body
            reward_usd, reward_token, reward_amount = self._extract_reward(title + "\n" + body)

            if self.min_reward_usd > 0 and (not reward_usd or reward_usd < self.min_reward_usd):
                # Αν δεν βρέθηκε reward και έχουμε minimum, skip
                if not reward_usd:
                    # Συνεχίζουμε χωρίς reward — ίσως αξίζει
                    pass

            created_at = item.get("created_at")
            posted_at = None
            if created_at:
                try:
                    posted_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                except ValueError:
                    pass

            labels = [l["name"] for l in item.get("labels", [])]
            user = item.get("user", {})

            category = self._detect_category(title + " " + body + " " + repo_name)

            return Bounty(
                source=self.SOURCE_NAME,
                external_id=issue_id,
                url=url,
                title=f"[{repo_name}] {title}",
                description=body[:2000],
                category=category,
                reward_usd=reward_usd,
                reward_token=reward_token,
                reward_amount=reward_amount,
                posted_at=posted_at,
                poster_handle=user.get("login"),
                poster_platform="github",
                contact_url=url,
                tags=labels[:10],
                raw_data=item,
            )
        except Exception as e:
            logger.warning(f"[github] Failed to parse issue: {e}")
            return None

    def _extract_reward(self, text: str) -> tuple:
        """Εξάγει reward από issue text."""
        usd_match = re.search(r'\$\s*([\d,]+(?:\.\d+)?)\s*k?', text)
        token_match = re.search(
            r'([\d,]+(?:\.\d+)?)\s+(USDC|USDT|ETH|DAI|GTC|OP|ARB)\b',
            text, re.IGNORECASE
        )

        reward_usd = None
        if usd_match:
            val = float(usd_match.group(1).replace(",", ""))
            if "k" in usd_match.group(0).lower():
                val *= 1000
            reward_usd = val

        reward_token = None
        reward_amount = None
        if token_match:
            reward_amount = float(token_match.group(1).replace(",", ""))
            reward_token = token_match.group(2).upper()
            if not reward_usd and reward_token in ("USDC", "USDT", "DAI"):
                reward_usd = reward_amount

        return reward_usd, reward_token, reward_amount

    def _detect_category(self, text: str) -> BountyCategory:
        t = text.lower()
        if any(w in t for w in ["solidity", "smart contract", "evm", "rust", "typescript", "react", "bug", "fix", "implement"]):
            return BountyCategory.CODE
        if any(w in t for w in ["docs", "documentation", "write", "tutorial"]):
            return BountyCategory.WRITING
        if any(w in t for w in ["design", "ui", "ux", "figma"]):
            return BountyCategory.DESIGN
        return BountyCategory.OTHER
