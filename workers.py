"""
Workers — ένας worker για κάθε στάδιο του pipeline.

AnalysisWorker:   NEW → ANALYSED      (AI scoring)
ClaimWorker:      ANALYSED → CLAIMED  (κατάθεση claim στην πλατφόρμα)
SubmitWorker:     CLAIMED → SUBMITTED (υποβολή εργασίας)
PaymentWorker:    SUBMITTED → PAID    (ανίχνευση πληρωμής)
"""
import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

from ..models.bounty import Bounty, BountyStatus, BountyCategory
from .state_machine import BountyStateMachine, TransitionError
from .queue.manager import BountyQueueManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Base Worker
# ---------------------------------------------------------------------------

class BaseWorker(ABC):
    """
    Abstract base για όλους τους workers.
    Κάθε worker επεξεργάζεται bounties σε ένα συγκεκριμένο στάδιο.
    """

    WORKER_NAME: str = "base"

    def __init__(self, queue: BountyQueueManager, config: dict = None):
        self.queue = queue
        self.config = config or {}
        self.stats = {"processed": 0, "success": 0, "failed": 0}

    @abstractmethod
    async def process(self, bounty: Bounty, fsm: BountyStateMachine) -> bool:
        """
        Επεξεργάζεται ένα bounty.
        Επιστρέφει True αν επιτυχία, False αν αποτυχία.
        """
        ...

    async def run(self, bounty: Bounty) -> bool:
        """Wrapper με error handling και stats."""
        fsm = BountyStateMachine(bounty)
        self.stats["processed"] += 1
        try:
            success = await self.process(bounty, fsm)
            if success:
                self.stats["success"] += 1
                # Αποθήκευσε νέο status στο Redis
                await self.queue.update_status(bounty.uid, bounty.status)
            else:
                self.stats["failed"] += 1
            return success
        except TransitionError as e:
            logger.error(f"[{self.WORKER_NAME}] State error: {e}")
            self.stats["failed"] += 1
            return False
        except Exception as e:
            logger.error(f"[{self.WORKER_NAME}] Unexpected error: {e}", exc_info=True)
            self.stats["failed"] += 1
            return False


# ---------------------------------------------------------------------------
# 1. Analysis Worker — NEW → ANALYSED
# ---------------------------------------------------------------------------

class AnalysisWorker(BaseWorker):
    """
    Αναλύει ένα bounty και αποφασίζει αν αξίζει να γίνει claim.

    Scoring:
    - ROI score: reward / εκτιμώμενες ώρες
    - Skill match: κατηγορία vs ικανότητες agent
    - Deadline urgency
    - Competition (αν πολλοί το διεκδικούν)
    """

    WORKER_NAME = "analysis"

    # Ικανότητες που έχει ο agent (config-driven)
    DEFAULT_SKILLS = {
        BountyCategory.CODE:        0.9,
        BountyCategory.WRITING:     0.85,
        BountyCategory.RESEARCH:    0.8,
        BountyCategory.TRANSLATION: 0.7,
        BountyCategory.DESIGN:      0.4,
        BountyCategory.COMMUNITY:   0.6,
        BountyCategory.OTHER:       0.5,
    }

    def __init__(self, queue: BountyQueueManager, config: dict = None):
        super().__init__(queue, config)
        self.min_score = config.get("min_score", 0.4) if config else 0.4
        self.min_reward_usd = config.get("min_reward_usd", 10) if config else 10
        self.skills = config.get("skills", self.DEFAULT_SKILLS) if config else self.DEFAULT_SKILLS

    async def process(self, bounty: Bounty, fsm: BountyStateMachine) -> bool:
        logger.info(f"[analysis] Scoring: {bounty.title[:50]}")

        # --- ROI Score ---
        reward = bounty.reward_usd or 0
        if reward < self.min_reward_usd:
            fsm.transition(BountyStatus.REJECTED, f"Reward too low: ${reward}")
            return False

        roi_score = min(reward / 500.0, 1.0)   # normalize: $500 = max score

        # --- Skill Match ---
        skill_score = self.skills.get(bounty.category, 0.5)

        # --- Deadline Urgency (bonus για κοντινά deadlines) ---
        urgency_bonus = 0.0
        if bounty.deadline:
            hours = (bounty.deadline - datetime.now(timezone.utc)).total_seconds() / 3600
            if hours < 0:
                fsm.transition(BountyStatus.EXPIRED, "Deadline passed")
                return False
            elif hours < 24:
                urgency_bonus = 0.2
            elif hours < 72:
                urgency_bonus = 0.1

        # --- Final Score ---
        final_score = (roi_score * 0.5) + (skill_score * 0.4) + urgency_bonus
        final_score = min(final_score, 1.0)

        bounty.priority_score = final_score
        bounty.roi_score = roi_score
        bounty.skill_match_score = skill_score

        logger.info(
            f"[analysis] Score={final_score:.2f} "
            f"(ROI={roi_score:.2f}, Skill={skill_score:.2f}, Urgency={urgency_bonus:.2f}) "
            f"| {bounty.title[:40]}"
        )

        if final_score < self.min_score:
            fsm.transition(BountyStatus.REJECTED, f"Score too low: {final_score:.2f}")
            return False

        fsm.transition(BountyStatus.ANALYSED, f"Score: {final_score:.2f}")
        return True


# ---------------------------------------------------------------------------
# 2. Claim Worker — ANALYSED → CLAIMED
# ---------------------------------------------------------------------------

class ClaimWorker(BaseWorker):
    """
    Κάνει claim το bounty στην πλατφόρμα.
    Στέλνει μήνυμα/apply στον poster.

    Για τώρα: simulation mode.
    Layer 4 θα προσθέσει real platform API calls.
    """

    WORKER_NAME = "claim"

    async def process(self, bounty: Bounty, fsm: BountyStateMachine) -> bool:
        logger.info(f"[claim] Attempting claim: {bounty.title[:50]}")

        # Στέλνουμε claim ανάλογα με την πλατφόρμα
        success = await self._claim_on_platform(bounty)

        if success:
            fsm.transition(BountyStatus.CLAIMED, f"Claimed on {bounty.source}")
            logger.info(f"[claim] ✅ Successfully claimed: {bounty.url}")
        else:
            fsm.transition(BountyStatus.REJECTED, "Claim failed — already taken or closed")

        return success

    async def _claim_on_platform(self, bounty: Bounty) -> bool:
        """
        Platform-specific claim logic.
        TODO: Συνδέεται με Layer 4 (Submission Engine).
        """
        handlers = {
            "bountycaster": self._claim_bountycaster,
            "gitcoin":      self._claim_gitcoin,
            "github":       self._claim_github,
            "dework":       self._claim_dework,
        }
        handler = handlers.get(bounty.source, self._claim_generic)
        return await handler(bounty)

    async def _claim_bountycaster(self, bounty: Bounty) -> bool:
        # Cast reply στο Farcaster thread
        logger.info(f"[claim] → Farcaster reply to {bounty.contact_url}")
        await asyncio.sleep(0.5)   # placeholder για API call
        return True

    async def _claim_gitcoin(self, bounty: Bounty) -> bool:
        # Gitcoin "Start Work" API call
        logger.info(f"[claim] → Gitcoin start_work: {bounty.external_id}")
        await asyncio.sleep(0.5)
        return True

    async def _claim_github(self, bounty: Bounty) -> bool:
        # GitHub issue comment: "I'd like to work on this"
        logger.info(f"[claim] → GitHub comment on issue: {bounty.url}")
        await asyncio.sleep(0.5)
        return True

    async def _claim_dework(self, bounty: Bounty) -> bool:
        # Dework task assign
        logger.info(f"[claim] → Dework assign task: {bounty.external_id}")
        await asyncio.sleep(0.5)
        return True

    async def _claim_generic(self, bounty: Bounty) -> bool:
        logger.info(f"[claim] → Generic claim (manual): {bounty.url}")
        return True


# ---------------------------------------------------------------------------
# 3. Submit Worker — CLAIMED → SUBMITTED
# ---------------------------------------------------------------------------

class SubmitWorker(BaseWorker):
    """
    Υποβάλλει την ολοκληρωμένη εργασία.
    Σε αυτό το στάδιο το Layer 3 AI Agent έχει ήδη παράγει το output.
    """

    WORKER_NAME = "submit"

    async def process(self, bounty: Bounty, fsm: BountyStateMachine) -> bool:
        logger.info(f"[submit] Submitting work for: {bounty.title[:50]}")

        # Εδώ παίρνουμε το output από το Layer 3 AI Agent
        work_output = await self._get_ai_output(bounty)

        if not work_output:
            fsm.transition(BountyStatus.REJECTED, "No AI output available")
            return False

        # Υποβολή στην πλατφόρμα
        submitted = await self._submit_to_platform(bounty, work_output)

        if submitted:
            fsm.transition(BountyStatus.SUBMITTED, "Work submitted successfully")
            logger.info(f"[submit] ✅ Work submitted: {bounty.url}")
        else:
            fsm.transition(BountyStatus.REJECTED, "Submission failed")

        return submitted

    async def _get_ai_output(self, bounty: Bounty) -> Optional[str]:
        """
        Παίρνει το παραγμένο έργο από τον AI Agent (Layer 3).
        TODO: Σύνδεση με AI output queue.
        """
        # Placeholder — Layer 3 θα γεμίζει αυτό
        logger.info(f"[submit] Fetching AI output for {bounty.uid}...")
        await asyncio.sleep(0.3)
        return f"[AI Output for bounty {bounty.uid}] — Generated work placeholder"

    async def _submit_to_platform(self, bounty: Bounty, output: str) -> bool:
        """Υποβολή εργασίας στην πλατφόρμα."""
        logger.info(f"[submit] → Submitting to {bounty.source}: {len(output)} chars")
        await asyncio.sleep(0.5)
        return True


# ---------------------------------------------------------------------------
# 4. Payment Worker — SUBMITTED → PAID
# ---------------------------------------------------------------------------

class PaymentWorker(BaseWorker):
    """
    Παρακολουθεί αν πληρώθηκε το bounty.
    Polling on-chain + platform API.
    Layer 5 θα χειριστεί το crypto → FIAT conversion.
    """

    WORKER_NAME = "payment"

    def __init__(self, queue: BountyQueueManager, config: dict = None):
        super().__init__(queue, config)
        self.max_wait_hours = (config or {}).get("max_wait_hours", 72)
        self.poll_interval = (config or {}).get("poll_interval_seconds", 300)

    async def process(self, bounty: Bounty, fsm: BountyStateMachine) -> bool:
        logger.info(f"[payment] Monitoring payment for: {bounty.title[:50]}")

        # Έλεγξε αν ήδη πληρώθηκε
        paid = await self._check_payment(bounty)

        if paid:
            fsm.transition(BountyStatus.PAID, f"Payment confirmed | ${bounty.reward_usd}")
            logger.info(f"[payment] 💰 PAID! ${bounty.reward_usd} for {bounty.title[:40]}")
            await self._log_revenue(bounty)
            return True

        logger.info(f"[payment] ⏳ Payment pending for {bounty.uid}. Will re-check later.")
        # Δεν αλλάζουμε status — θα ξαναελεγχτεί στο επόμενο poll
        return False

    async def _check_payment(self, bounty: Bounty) -> bool:
        """
        Ελέγχει on-chain ή platform API για πληρωμή.
        TODO: Layer 5 wallet monitor integration.
        """
        await asyncio.sleep(0.3)
        # Placeholder — πάντα False μέχρι Layer 5
        return False

    async def _log_revenue(self, bounty: Bounty) -> None:
        """Καταγράφει έσοδα για P&L tracking."""
        logger.info(
            f"[payment] 📊 Revenue logged: "
            f"source={bounty.source} | "
            f"reward=${bounty.reward_usd} {bounty.reward_token or ''} | "
            f"uid={bounty.uid}"
        )
