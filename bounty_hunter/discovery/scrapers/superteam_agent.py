import os
import logging
import httpx
from ..models.bounty import Bounty

logger = logging.getLogger(__name__)
API_KEY = os.environ.get("SUPERTEAM_API_KEY", "sk_fcb045f18b91e7f1e558519e9808ffec47bc3d0d4c698f8a0153ba6261b68c5b")
BASE_URL = "https://superteam.fun"

class SuperteamAgentScraper:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def fetch(self):
        headers = {"Authorization": f"Bearer {API_KEY}"}
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{BASE_URL}/api/agents/listings/live?take=20", headers=headers)
            if r.status_code != 200:
                logger.error(f"[superteam-agent] HTTP {r.status_code}")
                return
            for item in r.json():
                reward = (item.get("rewardAmount") or 0) / 100
                slug = item.get("slug", "")
                listing_type = item.get("type", "bounty")
                b = Bounty(
                    external_id=str(item["id"]),
                    title=item["title"],
                    description=item.get("description") or f"Superteam {listing_type}: {slug}",
                    reward_usd=reward,
                    url=f"{BASE_URL}/listings/{listing_type}s/{slug}",
                    source="superteam_agent",
                )
                logger.info(f"[superteam-agent] Found: ${reward} | {item['title'][:50]}")
                yield b

class SuperteamAgentSubmitter:
    async def submit(self, listing_id: str, slug: str, work: str, listing_type: str = "bounty") -> bool:
        headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
        payload = {"listingId": listing_id, "link": work[:200], "otherInfo": work[:3000], "eligibilityAnswers": [], "ask": None}
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(f"{BASE_URL}/api/agents/submissions/create", json=payload, headers=headers)
            success = r.status_code in (200, 201)
            logger.info(f"[superteam-agent] Submit {r.status_code}: {r.text[:100]}")
            return success
