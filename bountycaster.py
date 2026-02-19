"""
BountyCaster Scraper
Χρησιμοποιεί το Farcaster/Neynar API για να βρει casts με bounties.

Docs: https://docs.neynar.com/
API key: https://dev.neynar.com (δωρεάν tier διαθέσιμο)
"""
import logging
import re
from datetime import datetime
from typing import AsyncIterator

from ..models.bounty import Bounty, BountyCategory
from .base import BaseScraper

logger = logging.getLogger(__name__)

# BountyCaster channel FID στο Farcaster
BOUNTYCASTER_CHANNEL = "bounties"
NEYNAR_API_BASE = "https://api.neynar.com/v2"


class BountyCasterScraper(BaseScraper):
    """
    Scraper για BountyCaster (https://bountycaster.xyz).

    Διαβάζει casts από το /bounties channel στο Farcaster
    μέσω του Neynar API και τα μετατρέπει σε Bounty objects.
    """

    SOURCE_NAME = "bountycaster"
    RATE_LIMIT_SECONDS = 1.0

    def __init__(self, api_key: str, config: dict = None):
        super().__init__(config)
        self.api_key = api_key
        self.min_reward_usd = config.get("min_reward_usd", 10) if config else 10
        self.max_results = config.get("max_results", 50) if config else 50

    def _default_headers(self) -> dict:
        return {
            **super()._default_headers(),
            "api_key": self.api_key,
        }

    async def fetch(self) -> AsyncIterator[Bounty]:
        """Fetch bounty casts από το Farcaster /bounties channel."""
        cursor = None
        fetched = 0

        while fetched < self.max_results:
            params = {
                "channel_id": BOUNTYCASTER_CHANNEL,
                "limit": min(25, self.max_results - fetched),
                "type": "long_form",  # περιλαμβάνει και short casts
            }
            if cursor:
                params["cursor"] = cursor

            resp = await self._get(
                f"{NEYNAR_API_BASE}/farcaster/feed/channels",
                params=params,
            )
            data = resp.json()
            casts = data.get("casts", [])

            if not casts:
                break

            for cast in casts:
                bounty = self._parse_cast(cast)
                if bounty:
                    yield bounty
                    fetched += 1

            cursor = data.get("next", {}).get("cursor")
            if not cursor:
                break

    def _parse_cast(self, cast: dict) -> Bounty | None:
        """Μετατρέπει ένα Farcaster cast σε Bounty."""
        try:
            text: str = cast.get("text", "")
            hash_id: str = cast.get("hash", "")
            author = cast.get("author", {})
            timestamp = cast.get("timestamp", "")

            # Ψάχνουμε για reward στο κείμενο
            reward_usd, reward_token, reward_amount = self._extract_reward(text)

            # Φιλτράρουμε αν είναι κάτω από το minimum
            if reward_usd and reward_usd < self.min_reward_usd:
                return None

            # Κατηγορία από keywords
            category = self._detect_category(text)

            posted_at = None
            if timestamp:
                try:
                    posted_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                except ValueError:
                    pass

            return Bounty(
                source=self.SOURCE_NAME,
                external_id=hash_id,
                url=f"https://bountycaster.xyz/bounty/{hash_id}",
                title=self._extract_title(text),
                description=text,
                category=category,
                reward_usd=reward_usd,
                reward_token=reward_token,
                reward_amount=reward_amount,
                posted_at=posted_at,
                poster_handle=author.get("username"),
                poster_platform="farcaster",
                contact_url=f"https://warpcast.com/{author.get('username')}/{hash_id}",
                tags=self._extract_tags(text),
                raw_data=cast,
            )
        except Exception as e:
            logger.warning(f"[bountycaster] Failed to parse cast: {e}")
            return None

    def _extract_reward(self, text: str) -> tuple[float | None, str | None, float | None]:
        """
        Εξάγει reward από κείμενο.
        Παραδείγματα: "$500 USDC", "0.1 ETH", "50 DAI"
        """
        # USD amount pattern: $500, $1,000, $1.5k
        usd_pattern = r'\$\s*([\d,]+(?:\.\d+)?)\s*k?'
        # Token amount: 100 USDC, 0.5 ETH, 50 GTC
        token_pattern = r'([\d,]+(?:\.\d+)?)\s+(USDC|USDT|ETH|DAI|GTC|OP|ARB|MATIC|WETH|wETH)\b'

        reward_usd = None
        reward_token = None
        reward_amount = None

        usd_match = re.search(usd_pattern, text, re.IGNORECASE)
        if usd_match:
            val_str = usd_match.group(1).replace(",", "")
            reward_usd = float(val_str)
            if "k" in usd_match.group(0).lower():
                reward_usd *= 1000

        token_match = re.search(token_pattern, text, re.IGNORECASE)
        if token_match:
            reward_amount = float(token_match.group(1).replace(",", ""))
            reward_token = token_match.group(2).upper()
            # Αν δεν βρήκαμε USD και το token είναι stable
            if not reward_usd and reward_token in ("USDC", "USDT", "DAI"):
                reward_usd = reward_amount

        return reward_usd, reward_token, reward_amount

    def _extract_title(self, text: str) -> str:
        """Παίρνει την πρώτη γραμμή ως τίτλο."""
        first_line = text.strip().split("\n")[0]
        return first_line[:100] if first_line else text[:100]

    def _detect_category(self, text: str) -> BountyCategory:
        text_lower = text.lower()
        if any(w in text_lower for w in ["code", "dev", "smart contract", "solidity", "python", "bug", "fix", "build"]):
            return BountyCategory.CODE
        if any(w in text_lower for w in ["write", "article", "blog", "thread", "content"]):
            return BountyCategory.WRITING
        if any(w in text_lower for w in ["design", "figma", "ui", "ux", "logo"]):
            return BountyCategory.DESIGN
        if any(w in text_lower for w in ["research", "analysis", "report"]):
            return BountyCategory.RESEARCH
        if any(w in text_lower for w in ["translate", "translation", "localize"]):
            return BountyCategory.TRANSLATION
        return BountyCategory.OTHER

    def _extract_tags(self, text: str) -> list[str]:
        """Εξάγει hashtags και σημαντικά keywords."""
        hashtags = re.findall(r'#(\w+)', text)
        keywords = ["web3", "defi", "nft", "dao", "solidity", "rust", "python"]
        found = [k for k in keywords if k in text.lower()]
        return list(set(hashtags + found))[:10]
