import httpx
import os
import logging

logger = logging.getLogger(__name__)

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK", "")

class DiscordNotifier:
    def __init__(self):
        self.webhook = os.environ.get("DISCORD_WEBHOOK", "")
        self.enabled = bool(self.webhook)

    async def send(self, message: str, color: int = 0x00ff00):
        if not self.enabled:
            return
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(self.webhook, json={
                    "embeds": [{
                        "description": message,
                        "color": color
                    }]
                })
        except Exception as e:
            logger.warning(f"[discord] {e}")

    async def bounty_found(self, title, reward, url):
        await self.send(f"🎯 **New Bounty!**\n💰 ${reward}\n📌 {title[:80]}\n🔗 {url}", 0x3498db)

    async def work_submitted(self, title, reward, url):
        await self.send(f"✅ **Submitted!**\n💰 ${reward}\n📌 {title[:80]}\n🔗 {url}", 0x2ecc71)

    async def payment_received(self, title, amount, token):
        await self.send(f"💸 **PAYMENT RECEIVED!**\n💰 {amount} {token}\n📌 {title[:80]}", 0xf1c40f)

    async def error(self, msg):
        await self.send(f"⚠️ **Error:** {msg[:200]}", 0xe74c3c)
