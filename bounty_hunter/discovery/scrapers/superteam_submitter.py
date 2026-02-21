import os
import json
import logging
import httpx
from solders.keypair import Keypair
from solders.message import Message
import base58
import base64

logger = logging.getLogger(__name__)

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
                self.keypair = None
                self.wallet = os.environ.get("SOLANA_WALLET", "")
        else:
            self.keypair = None
            self.wallet = os.environ.get("SOLANA_WALLET", "")

    def _sign_message(self, message: str) -> str:
        if not self.keypair:
            return ""
        msg_bytes = message.encode("utf-8")
        signature = self.keypair.sign_message(msg_bytes)
        return base64.b64encode(bytes(signature)).decode()

    async def submit(self, bounty_id: str, title: str, work: str, reward_usd: float) -> bool:
        try:
            # Superteam requires wallet signature for auth
            nonce = f"superteam_{bounty_id}_{self.wallet}"
            signature = self._sign_message(nonce)

            payload = {
                "listingId": bounty_id,
                "walletAddress": self.wallet,
                "signature": signature,
                "submissionLinks": [],
                "submissionText": work[:3000],
                "tweet": "",
            }

            headers = {
                "Content-Type": "application/json",
                "x-wallet-address": self.wallet,
                "x-signature": signature,
                "x-message": nonce,
            }

            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.post(self.API_URL, json=payload, headers=headers)
                if resp.status_code in (200, 201):
                    logger.info(f"[superteam] ✅ Submitted: {title[:50]}")
                    return True
                else:
                    logger.warning(f"[superteam] ❌ {resp.status_code}: {resp.text[:100]}")
                    return False
        except Exception as e:
            logger.error(f"[superteam] Error: {e}")
            return False
