import asyncio
import logging
import os
import json
from .ai_agent import GPT4oAgent
from .queue.manager import BountyQueueManager
from .orchestrator import DiscoveryOrchestrator
from .models.bounty import BountyStatus
from .submitter import BountySubmitter
from .notifier import DiscordNotifier
from .payment_monitor import PaymentMonitor
from .farcaster_poster import FarcasterPoster
from .keyword_updater import run_forever as keyword_updater_loop
# from .akash_bidder import AkashBidder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

MIN_SCORE = 20
MIN_REWARD = 5
MAX_REWARD = 600

async def process_bounty(bounty, agent, submitter, notifier):
    title = bounty.title[:60]
    logger.info(f"🔍 Analyzing: {title}")

    # Step 1: AI Analysis
    analysis = await agent.analyze_bounty(bounty.title, bounty.description or "")
    score = analysis.get("score", 0)
    feasible = analysis.get("feasible", False)
    approach = analysis.get("approach", "")
    reward = bounty.reward_usd or 0

    logger.info(f"📊 Score: {score}/100 | Reward: ${reward} | Feasible: {feasible}")

    # Φίλτρο πολύπλοκων tasks
    desc_lower = (bounty.description or "").lower()
    title_lower = bounty.title.lower()
    too_complex = any(w in desc_lower + title_lower for w in [
        "full stack", "fullstack", "entire codebase", "rewrite", "migrate"
    ])
    if too_complex:
        logger.info(f"⏭️  Too complex, skipping: {bounty.title[:50]}")
        return

    if score < MIN_SCORE or not feasible or reward < MIN_REWARD or reward > MAX_REWARD:
        logger.info(f"⏭️  Skipping")
        return

    # Notify good bounty found
    await notifier.bounty_found(bounty.title, reward, bounty.url or "")

    # Step 2: Generate work
    logger.info(f"⚙️  Generating work for: {title}")
    work = await agent.generate_work(bounty.title, bounty.description or "", approach)
    if not work:
        return

    # Step 3: Review
    review = await agent.review_work(work, bounty.description or "")
    quality = review.get("quality_score", 0)
    approved = review.get("approved", False)
    logger.info(f"✅ Review: quality={quality}/100 approved={approved}")

    if quality < 50:
        logger.warning(f"❌ Quality too low ({quality}/100)")
        return

    # Step 4: Audit + Submit
    success = await submitter.process(bounty, work)
    if success:
        await notifier.work_submitted(bounty.title, reward, bounty.url or "")

async def run():
    queue = BountyQueueManager(os.environ.get("REDIS_URL", "redis://localhost:6379"))
    await queue.connect()
    agent = GPT4oAgent()
    submitter = BountySubmitter(queue)
    notifier = DiscordNotifier()
    payment_monitor = PaymentMonitor()
    orchestrator = DiscoveryOrchestrator()
    orchestrator.queue = queue

    logger.info("🚀 EPYC Bounty Hunter — FULL AUTO MODE")
    logger.info(f"   MIN_SCORE={MIN_SCORE} | MIN_REWARD=${MIN_REWARD}")
    logger.info(f"   EVM: {os.environ.get('EVM_WALLET', os.environ.get('EVM_ADDRESS','NOT SET'))}")
    logger.info(f"   SOL: {os.environ.get('SOLANA_WALLET','NOT SET')}")
    logger.info(f"   Telegram: {'✅' if notifier.enabled else '❌ not configured'}")

    async def pipeline_loop():
        while True:
            bounty = await queue.pop_next()
            if bounty:
                try:
                    await process_bounty(bounty, agent, submitter, notifier)
                except Exception as e:
                    logger.error(f"Pipeline error: {e}")
                    await notifier.error(str(e))
            else:
                await asyncio.sleep(10)

    await asyncio.gather(
        orchestrator.run_forever(),
        pipeline_loop(),
        payment_monitor.run_forever(),
        keyword_updater_loop(),
        # AkashBidder().run_forever(),  # Disabled - runs separately
    )

if __name__ == "__main__":
    asyncio.run(run())
