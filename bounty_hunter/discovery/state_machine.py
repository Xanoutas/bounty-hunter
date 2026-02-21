"""
State Machine — Bounty Lifecycle
Διαχειρίζεται τις μεταβάσεις κατάστασης κάθε bounty.

NEW → ANALYSED → CLAIMED → SUBMITTED → PAID
                         ↘ REJECTED
                    ↘ EXPIRED
"""
import logging
from datetime import datetime
from enum import Enum
from typing import Callable, Optional

from ..models.bounty import Bounty, BountyStatus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Transition rules — ποιες μεταβάσεις επιτρέπονται
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[BountyStatus, list[BountyStatus]] = {
    BountyStatus.NEW:       [BountyStatus.ANALYSED, BountyStatus.EXPIRED],
    BountyStatus.ANALYSED:  [BountyStatus.CLAIMED, BountyStatus.REJECTED, BountyStatus.EXPIRED],
    BountyStatus.CLAIMED:   [BountyStatus.SUBMITTED, BountyStatus.REJECTED],
    BountyStatus.SUBMITTED: [BountyStatus.PAID, BountyStatus.REJECTED],
    BountyStatus.PAID:      [],   # τερματική κατάσταση
    BountyStatus.REJECTED:  [],   # τερματική κατάσταση
    BountyStatus.EXPIRED:   [],   # τερματική κατάσταση
}

# Emoji για logging
STATUS_EMOJI = {
    BountyStatus.NEW:       "🆕",
    BountyStatus.ANALYSED:  "🔍",
    BountyStatus.CLAIMED:   "✋",
    BountyStatus.SUBMITTED: "📤",
    BountyStatus.PAID:      "💰",
    BountyStatus.REJECTED:  "❌",
    BountyStatus.EXPIRED:   "⏰",
}


class TransitionError(Exception):
    pass


class BountyStateMachine:
    """
    State Machine για ένα bounty.
    Εξασφαλίζει ότι μόνο έγκυρες μεταβάσεις γίνονται.
    """

    def __init__(self, bounty: Bounty):
        self.bounty = bounty
        self._history: list[dict] = []
        self._hooks: dict[BountyStatus, list[Callable]] = {}

    @property
    def state(self) -> BountyStatus:
        return self.bounty.status

    def can_transition_to(self, new_status: BountyStatus) -> bool:
        return new_status in VALID_TRANSITIONS.get(self.state, [])

    def transition(self, new_status: BountyStatus, reason: str = "") -> None:
        """Εκτελεί μετάβαση κατάστασης."""
        if not self.can_transition_to(new_status):
            raise TransitionError(
                f"Invalid transition: {self.state.value} → {new_status.value} "
                f"for bounty {self.bounty.uid}"
            )

        old_status = self.state
        self.bounty.status = new_status

        # Καταγραφή ιστορικού
        entry = {
            "from": old_status.value,
            "to": new_status.value,
            "at": datetime.utcnow().isoformat(),
            "reason": reason,
        }
        self._history.append(entry)

        emoji = STATUS_EMOJI.get(new_status, "➡️")
        logger.info(
            f"{emoji} [{self.bounty.uid}] {old_status.value} → {new_status.value}"
            + (f" | {reason}" if reason else "")
        )

        # Τρέξε hooks αν υπάρχουν
        for hook in self._hooks.get(new_status, []):
            try:
                hook(self.bounty)
            except Exception as e:
                logger.error(f"Hook error on {new_status}: {e}")

    def on(self, status: BountyStatus, callback: Callable) -> None:
        """Καταχώρηση hook για συγκεκριμένη κατάσταση."""
        self._hooks.setdefault(status, []).append(callback)

    @property
    def history(self) -> list[dict]:
        return self._history

    def is_terminal(self) -> bool:
        return self.state in (
            BountyStatus.PAID,
            BountyStatus.REJECTED,
            BountyStatus.EXPIRED,
        )
