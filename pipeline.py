"""
Pipeline — Συνδέει όλους τους workers σε αλυσίδα.

Τρέχει παράλληλα χρησιμοποιώντας asyncio + τους 16 cores του Ryzen 5950X.

Flow:
  Queue → AnalysisWorker → ClaimWorker → [AI Agent Layer 3] → SubmitWorker → PaymentWorker
"""
import asyncio
import logging
import os
import signal
from datetime import datetime

from .queue.manager import BountyQueueManager
from .workers import AnalysisWorker, ClaimWorker, SubmitWorker, PaymentWorker
from ..models.bounty import BountyStatus

logger = logging.getLogger(__name__)


class BountyPipeline:
    """
    Κεντρικό pipeline που τρέχει όλους τους workers.

    Αρχιτεκτονική:
    - N concurrent workers (default: 4, ανάλογα με CPU cores)
    - Κάθε bounty περνά διαδοχικά από Analysis → Claim → Submit → Payment
    - asyncio.Semaphore ελέγχει concurrency
    """

    def __init__(self, queue: BountyQueueManager, config: dict = None):
        self.queue = queue
        self.config = config or {}
        self.concurrency = self.config.get("concurrency", 4)
        self._semaphore = asyncio.Semaphore(self.concurrency)
        self._running = False
        self._tasks: list[asyncio.Task] = []

        # Workers
        self.analysis = AnalysisWorker(queue, config.get("analysis", {}))
        self.claim    = ClaimWorker(queue, config.get("claim", {}))
        self.submit   = SubmitWorker(queue, config.get("submit", {}))
        self.payment  = PaymentWorker(queue, config.get("payment", {}))

    async def process_one(self, bounty) -> None:
        """Επεξεργάζεται ένα bounty μέσα από όλο το pipeline."""
        async with self._semaphore:
            uid = bounty.uid
            title = bounty.title[:45]
            logger.info(f"\n🎯 Processing: [{bounty.source}] {title}")

            # --- Step 1: Analysis ---
            ok = await self.analysis.run(bounty)
            if not ok or bounty.status != BountyStatus.ANALYSED:
                logger.info(f"⛔ Stopped at ANALYSIS: {title}")
                return

            # --- Step 2: Claim ---
            ok = await self.claim.run(bounty)
            if not ok or bounty.status != BountyStatus.CLAIMED:
                logger.info(f"⛔ Stopped at CLAIM: {title}")
                return

            # --- Step 3: AI Work (Layer 3 placeholder) ---
            logger.info(f"🤖 AI Agent generating work for: {title}")
            await asyncio.sleep(1)   # Layer 3 θα το αντικαταστήσει

            # --- Step 4: Submit ---
            ok = await self.submit.run(bounty)
            if not ok or bounty.status != BountyStatus.SUBMITTED:
                logger.info(f"⛔ Stopped at SUBMIT: {title}")
                return

            # --- Step 5: Payment monitoring ---
            await self.payment.run(bounty)

    async def run_loop(self, poll_seconds: int = 10) -> None:
        """
        Main loop — συνεχώς τραβά bounties από την queue και τα επεξεργάζεται.
        Τρέχει N bounties παράλληλα (concurrency).
        """
        self._running = True
        logger.info(f"🚀 Pipeline started | concurrency={self.concurrency}")

        while self._running:
            # Πάρε το επόμενο bounty από το priority heap
            bounty = await self.queue.pop_next()

            if bounty:
                # Τρέξε ασύγχρονα (non-blocking)
                task = asyncio.create_task(self.process_one(bounty))
                self._tasks.append(task)

                # Καθάρισε ολοκληρωμένα tasks
                self._tasks = [t for t in self._tasks if not t.done()]
            else:
                # Queue άδεια — περίμενε λίγο
                await asyncio.sleep(poll_seconds)

    def stop(self) -> None:
        self._running = False
        logger.info("🛑 Pipeline stopping...")

    def stats(self) -> dict:
        return {
            "analysis":  self.analysis.stats,
            "claim":     self.claim.stats,
            "submit":    self.submit.stats,
            "payment":   self.payment.stats,
            "active_tasks": len([t for t in self._tasks if not t.done()]),
        }


# ---------------------------------------------------------------------------
# Entry point — τρέξε pipeline + orchestrator μαζί
# ---------------------------------------------------------------------------

async def run_full_system(config: dict) -> None:
    """Τρέχει Discovery + Pipeline ταυτόχρονα."""
    from .orchestrator import DiscoveryOrchestrator

    queue = BountyQueueManager(config.get("redis_url", "redis://localhost:6379"))
    await queue.connect()

    orchestrator = DiscoveryOrchestrator(config)
    orchestrator.queue = queue

    pipeline = BountyPipeline(queue, config.get("pipeline", {}))

    logger.info("🌐 Starting full Bounty Hunter system...")

    # Τρέχουν παράλληλα: discovery loop + pipeline loop
    await asyncio.gather(
        orchestrator.run_forever(),
        pipeline.run_loop(),
    )


DEFAULT_CONFIG = {
    "redis_url": os.getenv("REDIS_URL", "redis://localhost:6379"),
    "poll_interval_minutes": 15,
    "pipeline": {
        "concurrency": 4,
        "analysis": {
            "min_score": 0.35,
            "min_reward_usd": 10,
        },
        "payment": {
            "max_wait_hours": 72,
            "poll_interval_seconds": 300,
        },
    },
}


if __name__ == "__main__":
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )
    asyncio.run(run_full_system(DEFAULT_CONFIG))
