import os
import json
import logging
import httpx
from solders.keypair import Keypair

logger = logging.getLogger(__name__)

PRIVY_TOKEN = "eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6Ii14azNpN2lHUVVOekd0MGZHUlZiRE1OczhCQ0JQUmU4SEFGNWdVUVJIT0kifQ.eyJzaWQiOiJjbWx6bG45NHAwMDhqMGNsNWJydml5NmNlIiwiaXNzIjoicHJpdnkuaW8iLCJpYXQiOjE3NzE4NzY3MTIsImF1ZCI6ImNtNnNhdjkwOTAwbml4Y2g5bnp5N2M0MXYiLCJzdWIiOiJkaWQ6cHJpdnk6Y21sdmJzYnRwMDA3cTBjbDRyYzJxMnFoNyIsImV4cCI6MTc3MTg4MDMxMn0.a5JjqNqDpssuOjiNqknL1uAzCK84O5zccBwPEFqB7I23nWLjFFUR_5N6dgdHo4eJkRd2vzHTz8fFo4TwgKUg9w"

COOKIE = "_ga=GA1.1.332476087.1771876665; __Host-next-auth.csrf-token=0e155d1f12745eca075c113a2fd4cd9f814136e53a70d929bfc69f74ba425130%7Ce9d78fe28c01523edc22cdb4c6f06f5053f3cab1952164d01bc0377d702c5e3e; __Secure-next-auth.callback-url=https%3A%2F%2Fsuperteam.fun; privy-session=t; privy-token=eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6Ii14azNpN2lHUVVOekd0MGZHUlZiRE1OczhCQ0JQUmU4SEFGNWdVUVJIT0kifQ.eyJzaWQiOiJjbWx6bG45NHAwMDhqMGNsNWJydml5NmNlIiwiaXNzIjoicHJpdnkuaW8iLCJpYXQiOjE3NzE4NzY3MTIsImF1ZCI6ImNtNnNhdjkwOTAwbml4Y2g5bnp5N2M0MXYiLCJzdWIiOiJkaWQ6cHJpdnk6Y21sdmJzYnRwMDA3cTBjbDRyYzJxMnFoNyIsImV4cCI6MTc3MTg4MDMxMn0.a5JjqNqDpssuOjiNqknL1uAzCK84O5zccBwPEFqB7I23nWLjFFUR_5N6dgdHo4eJkRd2vzHTz8fFo4TwgKUg9w; user-id-hint=4b091bf6-45fb-4c56-900e-9952652a321e"

class SuperteamSubmitter:
    API_URL = "https://earn.superteam.fun/api/submission/create"

    def __init__(self):
        pk = os.environ.get("SOLANA_PRIVATE_KEY", "")
        if pk:
            try:
                self.keypair = Keypair.from_base58_string(pk)
                self.wallet = str(self.keypair.pubkey())
                logger.info(f"[superteam] Wallet: {self.wallet[:8]}...")
            except Exception as e:
                logger.error(f"[superteam] Keypair error: {e}")
                self.wallet = os.environ.get("SOLANA_WALLET", "")
        else:
            self.wallet = os.environ.get("SOLANA_WALLET", "")

    async def submit(self, bounty_id: str, title: str, work: str, reward_usd: float) -> bool:
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {PRIVY_TOKEN}",
                "Cookie": COOKIE,
                "Origin": "https://earn.superteam.fun",
                "Referer": f"https://earn.superteam.fun/listings/bounties/{bounty_id}",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            }

            payload = {
                "listingId": bounty_id,
                "walletAddress": self.wallet,
                "submissionLinks": [],
                "submissionText": work[:3000],
                "tweet": "",
            }

            async with httpx.AsyncClient() as client:
                r = await client.post(
                    self.API_URL,
                    json=payload,
                    headers=headers,
                    timeout=15,
                    follow_redirects=True
                )
                logger.info(f"[superteam] Status: {r.status_code}")
                if r.status_code in (200, 201):
                    logger.info(f"[superteam] ✅ Submitted: {title[:50]}")
                    return True
                else:
                    logger.warning(f"[superteam] ❌ {r.status_code}: {r.text[:200]}")
                    return False

        except Exception as e:
            logger.error(f"[superteam] Error: {e}")
            return False
