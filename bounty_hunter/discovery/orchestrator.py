import asyncio
import logging
import os
from .scrapers.bountycaster import BountyCasterScraper
from .scrapers.gitcoin import GitcoinScraper
from .scrapers.github_scraper import GitHubScraper
from .scrapers.immunefi import ImmunefiScraper
from .scrapers.superteam import SuperteamScraper
from .scrapers.dework import DeworkScraper
from .scrapers.questbook import QuestbookScraper
from .scrapers.layer3 import Layer3Scraper

logger = logging.getLogger(__name__)

class DiscoveryOrchestrator:
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.queue = None
        self.poll_interval = self.config.get("poll_interval_minutes", 60) * 60
        self.scrapers = []

    def _init_scrapers(self):
        github_token = os.environ.get("GITHUB_TOKEN") or os.getenv("GITHUB_TOKEN") or "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"
        neynar_key = os.environ.get("NEYNAR_API_KEY", "")
        logger.info(f"GitHub token: {'YES' if github_token else 'NO'}")
        self.scrapers = [
            BountyCasterScraper(neynar_key),
            # GitcoinScraper(),  # API dead
            GitHubScraper(github_token),
            # ImmunefiScraper(),  # API changed
            # SuperteamScraper(),  # Disabled: 3 submissions/month limit
            DeworkScraper(),
            # QuestbookScraper(),  # API dead
            Layer3Scraper(),
        ]

    async def _collect(self, scraper):
        bounties = []
        try:
            async with scraper:
                async for bounty in scraper.fetch():
                    bounties.append(bounty)
        except Exception as e:
            logger.error(f"Scraper {scraper.__class__.__name__} error: {e}")
        return bounties

    async def run_once(self):
        if not self.scrapers:
            self._init_scrapers()
        tasks = [self._collect(s) for s in self.scrapers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        total_new = 0
        for result in results:
            if isinstance(result, Exception):
                continue
            if result and self.queue:
                stats = await self.queue.push_many(result)
                total_new += stats.get("new", 0)
        logger.info(f"Discovery round — {total_new} new bounties")
        return total_new

    async def run_forever(self):
        logger.info(f"Orchestrator started (poll every {self.poll_interval//60}min)")
        while True:
            await self.run_once()
            await asyncio.sleep(self.poll_interval)
