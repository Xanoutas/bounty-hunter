"""
Discovery Orchestrator
Τρέχει όλους τους scrapers παράλληλα και τα στέλνει στην queue.

Χρήση:
    python -m bounty_hunter.discovery.orchestrator
"""
import asyncio
import logging
import os
from datetime import datetime

from .models.bounty import Bounty
from .queue.manager import BountyQueueManager
from .scrapers.bountycaster import BountyCasterScraper
from .scrapers.gitcoin import GitcoinScraper
from .scrapers.github_scraper import GitHubScraper
from .scrapers.dework_layer3 import DeworkScraper, Layer3Scraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("orchestrator")


class DiscoveryOrchestrator:
    """
    Κεντρικός συντονιστής για το Discovery Layer.

    - Τρέχει scrapers παράλληλα (asyncio gather)
    - Στέλνει bounties στην queue με dedup
    - Επαναλαμβάνεται κάθε N λεπτά (polling loop)
    """

    def __init__(self, config: dict):
        self.config = config
        self.queue = BountyQueueManager(
            redis_url=config.get("redis_url", "redis://localhost:6379")
        )
        self._scrapers_config = config.get("scrapers", {})
        self._poll_interval = config.get("poll_interval_minutes", 15) * 60
        self._run_count = 0

    def _build_scrapers(self) -> list:
        """Δημιουργεί scrapers βάσει config."""
        scrapers = []
        cfg = self._scrapers_config

        # BountyCaster
        if api_key := cfg.get("bountycaster", {}).get("api_key") or os.getenv("NEYNAR_API_KEY"):
            scrapers.append(
                BountyCasterScraper(
                    api_key=api_key,
                    config=cfg.get("bountycaster", {}),
                )
            )
            logger.info("✅ BountyCaster scraper enabled")
        else:
            logger.warning("⚠️  BountyCaster skipped — no NEYNAR_API_KEY")

        # Gitcoin
        scrapers.append(GitcoinScraper(config=cfg.get("gitcoin", {})))
        logger.info("✅ Gitcoin scraper enabled")

        # GitHub
        if gh_token := cfg.get("github", {}).get("token") or os.getenv("GITHUB_TOKEN"):
            scrapers.append(
                GitHubScraper(
                    token=gh_token,
                    config=cfg.get("github", {}),
                )
            )
            logger.info("✅ GitHub scraper enabled")
        else:
            logger.warning("⚠️  GitHub scraper skipped — no GITHUB_TOKEN")

        # Dework
        scrapers.append(DeworkScraper(config=cfg.get("dework", {})))
        logger.info("✅ Dework scraper enabled")

        # Layer3
        scrapers.append(Layer3Scraper(config=cfg.get("layer3", {})))
        logger.info("✅ Layer3 scraper enabled")

        return scrapers

    async def _run_scraper(self, scraper) -> list[Bounty]:
        """Τρέχει έναν scraper με error handling."""
        try:
            bounties = await scraper.run()
            logger.info(f"[{scraper.SOURCE_NAME}] → {len(bounties)} bounties found")
            return bounties
        except Exception as e:
            logger.error(f"[{scraper.SOURCE_NAME}] Scraper failed: {e}", exc_info=True)
            return []

    async def run_once(self) -> dict:
        """Ένας κύκλος discovery — τρέχει όλους τους scrapers."""
        self._run_count += 1
        start = datetime.utcnow()
        logger.info(f"\n{'='*50}")
        logger.info(f"🔍 Discovery Run #{self._run_count} — {start.strftime('%Y-%m-%d %H:%M:%S')} UTC")
        logger.info(f"{'='*50}")

        scrapers = self._build_scrapers()

        # Τρέχουν παράλληλα με asyncio.gather
        results = await asyncio.gather(
            *[self._run_scraper(s) for s in scrapers],
            return_exceptions=False,
        )

        # Flatten
        all_bounties: list[Bounty] = []
        for batch in results:
            all_bounties.extend(batch)

        logger.info(f"\n📦 Total bounties found: {len(all_bounties)}")

        # Push στην queue
        queue_stats = await self.queue.push_many(all_bounties)

        elapsed = (datetime.utcnow() - start).total_seconds()
        summary = {
            "run": self._run_count,
            "scrapers": len(scrapers),
            "total_found": len(all_bounties),
            "new_queued": queue_stats["new"],
            "duplicates": queue_stats["duplicates"],
            "elapsed_seconds": round(elapsed, 2),
            "queue_size": await self.queue.queue_size(),
            "bloom_filter": self.queue.stats["bloom_filter_count"],
        }

        logger.info(f"""
📊 Run Summary:
   ├─ Scrapers run  : {summary['scrapers']}
   ├─ Bounties found: {summary['total_found']}
   ├─ New queued    : {summary['new_queued']} ✅
   ├─ Duplicates    : {summary['duplicates']} 🔁
   ├─ Queue size    : {summary['queue_size']}
   └─ Elapsed       : {summary['elapsed_seconds']}s
""")
        return summary

    async def run_forever(self):
        """
        Polling loop — τρέχει κάθε poll_interval_minutes.
        Χρησιμοποιεί 16 cores του Ryzen 5950X μέσω asyncio.
        """
        await self.queue.connect()
        logger.info(f"🚀 Starting Discovery Loop (every {self._poll_interval//60} min)")

        try:
            while True:
                await self.run_once()
                logger.info(f"😴 Sleeping {self._poll_interval//60} min until next run...")
                await asyncio.sleep(self._poll_interval)
        except KeyboardInterrupt:
            logger.info("🛑 Stopping Discovery Orchestrator...")
        finally:
            await self.queue.disconnect()


# ---------------------------------------------------------------------------
# Default config — override με config.yaml ή env vars
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "redis_url": os.getenv("REDIS_URL", "redis://localhost:6379"),
    "poll_interval_minutes": int(os.getenv("POLL_INTERVAL_MIN", "15")),
    "scrapers": {
        "bountycaster": {
            "api_key": os.getenv("NEYNAR_API_KEY", ""),
            "min_reward_usd": 10,
            "max_results": 50,
        },
        "gitcoin": {
            "min_reward_usd": 20,
            "max_results": 50,
            "network": "1",   # Ethereum mainnet
        },
        "github": {
            "token": os.getenv("GITHUB_TOKEN", ""),
            "min_reward_usd": 0,
            "max_per_org": 15,
            "orgs": [
                "ethereum", "gitcoinco", "uniswap", "aave",
                "OpenZeppelin", "smartcontractkit", "thirdweb-dev",
            ],
        },
        "dework": {
            "min_reward_usd": 10,
            "max_results": 40,
        },
        "layer3": {
            "max_results": 30,
        },
    },
}


if __name__ == "__main__":
    orchestrator = DiscoveryOrchestrator(config=DEFAULT_CONFIG)
    asyncio.run(orchestrator.run_forever())
