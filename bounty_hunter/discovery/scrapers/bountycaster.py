import logging
import re
from typing import AsyncIterator
from ..models.bounty import Bounty, BountyCategory
from .base import BaseScraper

logger = logging.getLogger(__name__)



class BountyCasterScraper(BaseScraper):
    SOURCE_NAME = "farcaster"
    RATE_LIMIT_SECONDS = 1.0
    
    SEARCH_QUERIES = ["bounty reward USDC", "bounty reward ETH", "bounty reward SOL", "open bounty apply"]

    def __init__(self, api_key: str, config: dict = None):
        super().__init__(config)
        self.api_key = api_key

    def _default_headers(self) -> dict:
        return {
            **super()._default_headers(),
            "x-api-key": self.api_key,
        }

    def _extract_reward(self, text: str):
        patterns = [
            r'\$(\d+(?:,\d+)?(?:\.\d+)?)\s*(?:USDC|USD|usdc)?',
            r'(\d+(?:,\d+)?(?:\.\d+)?)\s*USDC',
            r'(\d+(?:,\d+)?(?:\.\d+)?)\s*ETH',
            r'(\d+(?:,\d+)?(?:\.\d+)?)\s*SOL',
        ]
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                val = float(m.group(1).replace(",", ""))
                token = "ETH" if "ETH" in p else "SOL" if "SOL" in p else "USDC"
                return val, token
        return None, "USDC"

    async def fetch(self) -> AsyncIterator[Bounty]:
        seen = set()
        for query in self.SEARCH_QUERIES:
            try:
                resp = await self._get(
                    "https://api.neynar.com/v2/farcaster/cast/search",
                    params={"q": query, "limit": 25}
                )
                casts = resp.json().get("result", {}).get("casts", [])
                for cast in casts:
                    hash_ = cast.get("hash", "")
                    if hash_ in seen:
                        continue
                    seen.add(hash_)
                    text = cast.get("text", "")
                    if any(s in text.lower() for s in ["chung daily note", "memecoin", "meme coin", "degen alert", "just launched", "airdrop", "solarax", "new coin alert", "token just dropped", "0 taxes"]): continue
                    reward_usd, token = self._extract_reward(text)
                    # Find URL from embeds
                    url = None
                    for embed in cast.get("embeds", []):
                        if isinstance(embed, dict) and embed.get("url"):
                            url = embed["url"]
                            break
                    if not url:
                        url = f"https://warpcast.com/~/conversations/{hash_}"
                    yield Bounty(
                        source=self.SOURCE_NAME,
                        external_id=hash_,
                        title=text[:100],
                        description=text,
                        url=url,
                        reward_usd=reward_usd,
                        reward_token=token,
                        category=BountyCategory.OTHER,
                        tags=["farcaster", "web3"],
                    )
            except Exception as e:
                logger.error(f"[farcaster] Error for query '{query}': {e}")
