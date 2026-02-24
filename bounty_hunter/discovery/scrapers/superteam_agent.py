import os
import logging
import httpx
from ..models.bounty import Bounty

logger = logging.getLogger(__name__)
API_KEY = os.environ.get("SUPERTEAM_API_KEY", "sk_fcb045f18b91e7f1e558519e9808ffec47bc3d0d4c698f8a0153ba6261b68c5b")
BASE_URL = "https://superteam.fun"

IMAGE_DOMAINS = ("imagedelivery.net", "imgur.com", "i.imgur.com", "cdn.", ".png", ".jpg", ".jpeg", ".gif", ".webp")

def _listing_url(listing_type: str, slug: str) -> str:
    # Superteam uses "bounties" not "bountys"
    type_map = {"bounty": "bounties", "project": "projects", "hackathon": "hackathons"}
    path = type_map.get(listing_type, f"{listing_type}s")
    return f"{BASE_URL}/earn/listing/{slug}"

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
                # Skip image-only bounties
                title = item.get("title", "")
                desc = item.get("description") or ""
                url = _listing_url(item.get("type", "bounty"), item.get("slug", ""))
                
                if any(d in url for d in IMAGE_DOMAINS):
                    logger.info(f"[superteam-agent] Skipping image bounty: {title[:40]}")
                    continue

                reward = (item.get("rewardAmount") or 0) / 100
                b = Bounty(
                    external_id=str(item["id"]),
                    title=title,
                    description=desc or f"Superteam {item.get('type', 'bounty')}: {item.get('slug', '')}",
                    reward_usd=reward,
                    url=url,
                    source="superteam_agent",
                )
                logger.info(f"[superteam-agent] Found: ${reward} | {title[:50]}")
                yield b


async def _create_gist(title: str, work: str) -> str:
    """Δημιουργεί GitHub Gist και επιστρέφει το URL."""
    import os
    token = os.environ.get("GITHUB_TOKEN", "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")
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    payload = {
        "description": title[:100],
        "public": True,
        "files": {
            "submission.md": {"content": work}
        }
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post("https://api.github.com/gists", json=payload, headers=headers)
        if r.status_code == 201:
            return r.json()["html_url"]
    return ""

class SuperteamAgentSubmitter:
    async def submit(self, listing_id: str, slug: str, work: str) -> bool:
        headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
        gist_url = await _create_gist(slug, work)
        payload = {
            "listingId": listing_id,
            "link": gist_url,
            "otherInfo": work[:3000],
            "eligibilityAnswers": [],
            "ask": None
        }
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(f"{BASE_URL}/api/agents/submissions/create", json=payload, headers=headers)
            success = r.status_code in (200, 201)
            logger.info(f"[superteam-agent] Submit {r.status_code}: {r.text[:150]}")
            return success
