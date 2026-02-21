import asyncio
import logging
import os
import json
import httpx
from datetime import datetime

logger = logging.getLogger(__name__)

AKASH_API = "https://akash-api.polkachu.com/akash/market/v1beta4"
CHECK_INTERVAL = 60  # seconds

class AkashBidder:
    def __init__(self):
        self.wallet = os.environ.get("AKASH_WALLET", "")
        self.key_name = os.environ.get("AKASH_KEY_NAME", "default")

    async def get_open_orders(self) -> list:
        """Βρες όλα τα ανοιχτά orders για CPU-only deployments"""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{AKASH_API}/orders",
                    params={"state": "open", "limit": 100}
                )
                orders = resp.json().get("orders", [])
                
                # Φίλτρο: μόνο CPU-only (χωρίς GPU)
                cpu_only = []
                for order in orders:
                    resources = order.get("spec", {}).get("resources", [])
                    has_gpu = any(
                        r.get("resources", {}).get("gpu", {}).get("units", {}).get("val", "0") != "0"
                        for r in resources
                    )
                    if not has_gpu:
                        cpu_only.append(order)
                
                logger.info(f"[akash] {len(cpu_only)} CPU-only orders found")
                return cpu_only
        except Exception as e:
            logger.error(f"[akash] Error fetching orders: {e}")
            return []

    async def get_existing_bids(self, order_id: dict) -> list:
        """Βρες τα υπάρχοντα bids για ένα order"""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{AKASH_API}/bids",
                    params={
                        "owner": order_id["owner"],
                        "dseq": order_id["dseq"],
                        "gseq": order_id["gseq"],
                        "oseq": order_id["oseq"],
                        "state": "open"
                    }
                )
                return resp.json().get("bids", [])
        except Exception as e:
            logger.error(f"[akash] Error fetching bids: {e}")
            return []

    def calculate_bid_price(self, bids: list, resources: list) -> float:
        """Υπολόγισε τιμή 5% κάτω από τον μέσο όρο"""
        if not bids:
            # Αν δεν υπάρχουν bids, υπολόγισε βάσει resources
            cpu = sum(
                int(r.get("resources", {}).get("cpu", {}).get("units", {}).get("val", 0))
                for r in resources
            )
            memory_gb = sum(
                int(r.get("resources", {}).get("memory", {}).get("quantity", {}).get("val", 0))
                for r in resources
            ) / (1024**3)
            # ~0.5 uakt per CPU unit per block + memory
            base_price = max(1.0, cpu * 0.5 + memory_gb * 0.1)
            return base_price

        prices = []
        for bid in bids:
            price_str = bid.get("bid", {}).get("price", {}).get("amount", "0")
            try:
                prices.append(float(price_str))
            except:
                pass

        if not prices:
            return 1.0

        avg = sum(prices) / len(prices)
        our_bid = avg * 0.95  # 5% κάτω από τον μέσο όρο
        logger.info(f"[akash] Avg price: {avg:.4f} | Our bid: {our_bid:.4f} (5% below)")
        return max(0.1, our_bid)

    async def place_bid(self, order: dict, price: float) -> bool:
        """Υποβολή bid μέσω akash CLI"""
        try:
            oid = order.get("order_id", {})
            dseq = oid.get("dseq", "")
            gseq = oid.get("gseq", 1)
            oseq = oid.get("oseq", 1)
            owner = oid.get("owner", "")

            cmd = (
                f"akash tx market bid create "
                f"--owner {owner} "
                f"--dseq {dseq} "
                f"--gseq {gseq} "
                f"--oseq {oseq} "
                f"--price {price:.6f}uakt "
                f"--from {self.key_name} "
                f"--chain-id akashnet-2 "
                f"--node WORKING_RPC_HERE "
                f"--yes -y"
            )

            import subprocess
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                logger.info(f"[akash] ✅ Bid placed: dseq={dseq} price={price:.4f}uakt")
                return True
            else:
                logger.warning(f"[akash] ❌ Bid failed: {result.stderr[:100]}")
                return False
        except Exception as e:
            logger.error(f"[akash] Bid error: {e}")
            return False

    async def run_forever(self):
        logger.info("[akash] Akash bidder started")
        placed_bids = set()  # Avoid duplicate bids

        while True:
            try:
                orders = await self.get_open_orders()
                new_bids = 0

                for order in orders:
                    oid = order.get("order_id", {})
                    order_key = f"{oid.get('dseq')}_{oid.get('gseq')}_{oid.get('oseq')}"
                    
                    if order_key in placed_bids:
                        continue

                    bids = await self.get_existing_bids(oid)
                    resources = order.get("spec", {}).get("resources", [])
                    price = self.calculate_bid_price(bids, resources)
                    
                    success = await self.place_bid(order, price)
                    if success:
                        placed_bids.add(order_key)
                        new_bids += 1
                    
                    await asyncio.sleep(2)  # Rate limit

                logger.info(f"[akash] Round complete — {new_bids} new bids placed")
                
                # Καθάρισε παλιά bids από το set κάθε ώρα
                if len(placed_bids) > 1000:
                    placed_bids.clear()

            except Exception as e:
                logger.error(f"[akash] Loop error: {e}")

            await asyncio.sleep(CHECK_INTERVAL)

