import asyncio
import logging
import os
from .queue.manager import BountyQueueManager
from .workers import AnalysisWorker, ClaimWorker, SubmitWorker, PaymentWorker
from ..models.bounty import BountyStatus

logger = logging.getLogger(__name__)


class BountyPipeline:
    def __init__(self, queue: BountyQueueManager, config: dict = None):
        self.queue = queue
        self.config = config or {}
        self.concurrency = self.config.get("concurrency", 4)
        self._semaphore = asyncio.Semaphore(self.concurrency)
        self._running = False
        self._tasks = []
        self.analysis = AnalysisWorker(queue, config.get("analysis", {}))
        self.claim    = ClaimWorker(queue, config.get("claim", {}))
        self.submit   = SubmitWorker(queue, config.get("submit", {}))
        self.payment  = PaymentWorker(queue, config.get("payment", {}))

    async def process_one(self, bounty) -> None:
        async with self._semaphore:
            title = bounty.title[:45]
            logger.info(f"Processing: [{bounty.source}] {title}")
            ok = await self.analysis.run(bounty)
            if not ok or bounty.status != BountyStatus.ANALYSED:
                return
            ok = await self.claim.run(bounty)
            if not ok or bounty.status != BountyStatus.CLAIMED:
                return
            logger.info(f"AI Agent generating work for: {title}")
            await asyncio.sleep(1)
            ok = await self.submit.run(bounty)
            if not ok or bounty.status != BountyStatus.SUBMITTED:
                return
            await self.payment.run(bounty)

    async def run_loop(self, poll_seconds: int = 10) -> None:
        self._running = True
        logger.info(f"Pipeline started | concurrency={self.concurrency}")
        while self._running:
            bounty = await self.queue.pop_next()
            if bounty:
                task = asyncio.create_task(self.process_one(bounty))
                self._tasks.append(task)
                self._tasks = [t for t in self._tasks if not t.done()]
            else:
                await asyncio.sleep(poll_seconds)

    def stop(self):
        self._running = False


async def run_full_system(config: dict) -> None:
    from .orchestrator import DiscoveryOrchestrator
    queue = BountyQueueManager(config.get("redis_url", "redis://localhost:6379"))
    await queue.connect()
    orchestrator = DiscoveryOrchestrator(config)
    orchestrator.queue = queue
    pipeline = BountyPipeline(queue, config.get("pipeline", {}))
    logger.info("Starting full Bounty Hunter system...")
    await asyncio.gather(orchestrator.run_forever(), pipeline.run_loop())


DEFAULT_CONFIG = {
    "redis_url": os.getenv("REDIS_URL", "redis://localhost:6379"),
    "poll_interval_minutes": 15,
    "pipeline": {
        "concurrency": 4,
        "analysis": {"min_score": 0.35, "min_reward_usd": 10},
        "payment": {"max_wait_hours": 72, "poll_interval_seconds": 300},
    },
}

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s", datefmt="%H:%M:%S")
    asyncio.run(run_full_system(DEFAULT_CONFIG))
