import asyncio
import logging
import os
from web3 import Web3
from .notifier import DiscordNotifier

logger = logging.getLogger(__name__)

# Fallback RPC endpoints
ETH_RPCS = [
    "https://eth.llamarpc.com",
    "https://rpc.ankr.com/eth",
    "https://ethereum.publicnode.com",
]
BASE_RPCS = [
    "https://base.llamarpc.com",
    "https://rpc.ankr.com/base",
    "https://base.publicnode.com",
]

def get_web3(rpcs: list) -> Web3:
    for rpc in rpcs:
        try:
            w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 10}))
            if w3.is_connected():
                logger.info(f"[payment] Connected to RPC: {rpc}")
                return w3
        except Exception:
            continue
    logger.warning("[payment] All RPCs failed!")
    return None

class PaymentMonitor:
    def __init__(self):
        self.notifier = DiscordNotifier()
        self.evm_wallet = os.environ.get("EVM_WALLET", "").lower()
        self.sol_wallet = os.environ.get("SOLANA_WALLET", "")
        self._last_eth_block = None
        self._last_base_block = None

    def _get_w3(self, chain: str) -> Web3:
        rpcs = ETH_RPCS if chain == "eth" else BASE_RPCS
        return get_web3(rpcs)

    async def check_evm_payments(self, chain: str):
        try:
            w3 = self._get_w3(chain)
            if not w3:
                return
            latest = w3.eth.block_number
            attr = f"_last_{chain}_block"
            last = getattr(self, attr, None)
            if not last:
                setattr(self, attr, latest)
                return
            # Max 20 blocks per check to avoid overload
            from_block = max(last + 1, latest - 20)
            for block_num in range(from_block, latest + 1):
                try:
                    block = w3.eth.get_block(block_num, full_transactions=True)
                    for tx in block.transactions:
                        to = tx.get("to") or ""
                        if to.lower() == self.evm_wallet:
                            value = w3.from_wei(tx["value"], "ether")
                            if float(value) > 0:
                                logger.info(f"💸 [{chain.upper()}] Received {value} ETH!")
                                await self.notifier.payment_received(
                                    f"{chain.upper()} Payment", value, "ETH"
                                )
                except Exception as e:
                    logger.warning(f"[payment] Block {block_num} error: {e}")
                    continue
            setattr(self, attr, latest)
        except Exception as e:
            logger.warning(f"[payment] {chain} check error: {e}")

    async def run_forever(self, interval: int = 1000):
        logger.info("💰 Payment monitor started (interval: 5min)")
        while True:
            await self.check_evm_payments("eth")
            await self.check_evm_payments("base")
            await asyncio.sleep(interval)
