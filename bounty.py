"""
Bounty data models — shared across all scrapers.
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
import hashlib
import json


class BountyStatus(str, Enum):
    NEW = "new"
    ANALYSED = "analysed"
    CLAIMED = "claimed"
    SUBMITTED = "submitted"
    PAID = "paid"
    REJECTED = "rejected"
    EXPIRED = "expired"


class BountyCategory(str, Enum):
    CODE = "code"
    WRITING = "writing"
    DESIGN = "design"
    RESEARCH = "research"
    TRANSLATION = "translation"
    COMMUNITY = "community"
    OTHER = "other"


@dataclass
class Bounty:
    # --- Ταυτοποίηση ---
    source: str                        # "bountycaster", "gitcoin", "github", ...
    external_id: str                   # ID στην πλατφόρμα
    url: str

    # --- Περιγραφή ---
    title: str
    description: str
    category: BountyCategory = BountyCategory.OTHER

    # --- Χρήματα ---
    reward_usd: Optional[float] = None
    reward_token: Optional[str] = None   # π.χ. "USDC", "ETH", "GTC"
    reward_amount: Optional[float] = None

    # --- Deadlines & Status ---
    status: BountyStatus = BountyStatus.NEW
    posted_at: Optional[datetime] = None
    deadline: Optional[datetime] = None
    discovered_at: datetime = field(default_factory=datetime.utcnow)

    # --- Επικοινωνία ---
    poster_handle: Optional[str] = None
    poster_platform: Optional[str] = None   # "farcaster", "github", "discord"
    contact_url: Optional[str] = None

    # --- Scoring (Layer 3 AI) ---
    priority_score: float = 0.0
    skill_match_score: float = 0.0
    roi_score: float = 0.0

    # --- Extra ---
    tags: list[str] = field(default_factory=list)
    raw_data: dict = field(default_factory=dict)

    @property
    def uid(self) -> str:
        """Μοναδικό ID για deduplication (Bloom Filter key)."""
        key = f"{self.source}:{self.external_id}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        d = {
            "uid": self.uid,
            "source": self.source,
            "external_id": self.external_id,
            "url": self.url,
            "title": self.title,
            "description": self.description[:500],  # truncate για Redis
            "category": self.category.value,
            "reward_usd": self.reward_usd,
            "reward_token": self.reward_token,
            "reward_amount": self.reward_amount,
            "status": self.status.value,
            "posted_at": self.posted_at.isoformat() if self.posted_at else None,
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "discovered_at": self.discovered_at.isoformat(),
            "poster_handle": self.poster_handle,
            "priority_score": self.priority_score,
            "tags": self.tags,
        }
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict) -> "Bounty":
        d = dict(d)
        if d.get("posted_at"):
            d["posted_at"] = datetime.fromisoformat(d["posted_at"])
        if d.get("deadline"):
            d["deadline"] = datetime.fromisoformat(d["deadline"])
        if d.get("discovered_at"):
            d["discovered_at"] = datetime.fromisoformat(d["discovered_at"])
        d.pop("uid", None)
        d["category"] = BountyCategory(d.get("category", "other"))
        d["status"] = BountyStatus(d.get("status", "new"))
        return cls(**d)

    def __repr__(self):
        return f"<Bounty [{self.source}] {self.title[:40]} | ${self.reward_usd or '?'}>"
