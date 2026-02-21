"""
Bounty Queue Manager
Redis Streams + Bloom Filter για deduplication + Priority Heap

Εγκατάσταση:
    pip install redis redispy mmh3 bitarray
"""
import asyncio
import heapq
import json
import logging
import struct
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import mmh3        # MurmurHash3 για Bloom Filter
import redis.asyncio as aioredis

from ..models.bounty import Bounty, BountyStatus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Bloom Filter (in-memory) — deduplication χωρίς να αποθηκεύουμε όλα τα IDs
# ---------------------------------------------------------------------------

class BloomFilter:
    """
    In-memory Bloom Filter για fast deduplication.
    False positive rate: ~1% με 100k items και size=1MB.
    """

    def __init__(self, size: int = 1_000_000, hash_count: int = 7):
        self.size = size
        self.hash_count = hash_count
        self._bits = bytearray(size // 8 + 1)
        self._count = 0

    def _get_positions(self, item: str) -> list[int]:
        positions = []
        for seed in range(self.hash_count):
            h = mmh3.hash(item, seed, signed=False)
            positions.append(h % self.size)
        return positions

    def add(self, item: str) -> None:
        for pos in self._get_positions(item):
            self._bits[pos // 8] |= (1 << (pos % 8))
        self._count += 1

    def __contains__(self, item: str) -> bool:
        for pos in self._get_positions(item):
            if not (self._bits[pos // 8] & (1 << (pos % 8))):
                return False
        return True

    @property
    def count(self) -> int:
        return self._count


# ---------------------------------------------------------------------------
# Priority Queue Item
# ---------------------------------------------------------------------------

@dataclass(order=True)
class PrioritizedBounty:
    """Bounty με priority για το heap. Αρνητικό score = higher priority."""
    priority: float                            # heapq is min-heap → αρνητικό
    bounty: Bounty = field(compare=False)
    inserted_at: float = field(default_factory=time.time, compare=False)

    @classmethod
    def from_bounty(cls, bounty: Bounty) -> "PrioritizedBounty":
        # Score = reward_usd (0 αν άγνωστο) + bonus για deadline urgency
        score = bounty.reward_usd or 0
        if bounty.deadline:
            hours_left = (bounty.deadline - datetime.utcnow()).total_seconds() / 3600
            if 0 < hours_left < 48:
                score += 100   # Urgent bonus
        return cls(priority=-score, bounty=bounty)


# ---------------------------------------------------------------------------
# Queue Manager
# ---------------------------------------------------------------------------

class BountyQueueManager:
    """
    Κεντρικό σύστημα queue για bounties.

    Αρχιτεκτονική:
    - BloomFilter: fast dedup (in-memory)
    - Redis Stream "bounties:incoming": persistent queue
    - In-memory min-heap: priority ordering για processing
    - Redis Hash "bounty:{uid}": full bounty data
    """

    STREAM_KEY = "bounties:incoming"
    PROCESSING_KEY = "bounties:processing"
    DONE_KEY = "bounties:done"
    BLOOM_PERSIST_KEY = "bounties:bloom_seen"

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self._redis: Optional[aioredis.Redis] = None
        self._bloom = BloomFilter(size=2_000_000, hash_count=7)
        self._priority_heap: list[PrioritizedBounty] = []
        self._stats = {
            "total_received": 0,
            "duplicates_filtered": 0,
            "pushed_to_queue": 0,
        }

    async def connect(self):
        self._redis = await aioredis.from_url(
            self.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        # Φόρτωσε προηγούμενα seen UIDs στο bloom filter
        await self._restore_bloom()
        logger.info("BountyQueueManager connected to Redis.")

    async def disconnect(self):
        if self._redis:
            await self._redis.aclose()

    async def _restore_bloom(self):
        """Επαναφέρει τα seen UIDs από Redis στο Bloom Filter."""
        try:
            members = await self._redis.smembers(self.BLOOM_PERSIST_KEY)
            for uid in members:
                self._bloom.add(uid)
            logger.info(f"Restored {len(members)} UIDs to Bloom Filter.")
        except Exception as e:
            logger.warning(f"Could not restore bloom filter: {e}")

    async def push(self, bounty: Bounty) -> bool:
        """
        Προσθέτει bounty στην queue.
        Επιστρέφει True αν προστέθηκε, False αν ήταν duplicate.
        """
        self._stats["total_received"] += 1
        uid = bounty.uid

        # 1. Bloom Filter check (fast path)
        if uid in self._bloom:
            self._stats["duplicates_filtered"] += 1
            logger.debug(f"Duplicate (bloom): {uid} — {bounty.title[:40]}")
            return False

        # 2. Redis double-check (αποφεύγουμε false positives)
        exists = await self._redis.hexists(f"bounty:{uid}", "uid")
        if exists:
            self._bloom.add(uid)  # ανανέωση bloom
            self._stats["duplicates_filtered"] += 1
            return False

        # 3. Αποθήκευσε στο Redis Hash
        await self._redis.hset(f"bounty:{uid}", mapping={
            "data": bounty.to_json(),
            "status": BountyStatus.NEW.value,
            "uid": uid,
        })
        await self._redis.expire(f"bounty:{uid}", 60 * 60 * 24 * 30)  # 30 days TTL

        # 4. Push στο Redis Stream
        await self._redis.xadd(
            self.STREAM_KEY,
            {
                "uid": uid,
                "source": bounty.source,
                "title": bounty.title[:100],
                "reward_usd": str(bounty.reward_usd or 0),
                "category": bounty.category.value,
            }
        )

        # 5. Mark στο Bloom Filter + persistent set
        self._bloom.add(uid)
        await self._redis.sadd(self.BLOOM_PERSIST_KEY, uid)

        # 6. Add to in-memory priority heap
        heapq.heappush(self._priority_heap, PrioritizedBounty.from_bounty(bounty))

        self._stats["pushed_to_queue"] += 1
        logger.info(f"✅ Queued: [{bounty.source}] {bounty.title[:50]} | ${bounty.reward_usd or '?'}")
        return True

    async def push_many(self, bounties: list[Bounty]) -> dict:
        """Bulk push — επιστρέφει stats."""
        new_count = 0
        dup_count = 0
        for bounty in bounties:
            added = await self.push(bounty)
            if added:
                new_count += 1
            else:
                dup_count += 1
        return {"new": new_count, "duplicates": dup_count}

    async def pop_next(self) -> Optional[Bounty]:
        """
        Παίρνει το επόμενο bounty από το priority heap.
        Highest reward_usd πρώτα.
        """
        while self._priority_heap:
            item = heapq.heappop(self._priority_heap)
            uid = item.bounty.uid

            # Check αν έχει ήδη ληφθεί/ακυρωθεί
            status = await self._redis.hget(f"bounty:{uid}", "status")
            if status in (BountyStatus.CLAIMED.value, BountyStatus.SUBMITTED.value, BountyStatus.PAID.value):
                continue  # skip, already processed

            # Mark ως processing
            await self._redis.hset(f"bounty:{uid}", "status", BountyStatus.ANALYSED.value)
            return item.bounty

        return None

    async def update_status(self, uid: str, status: BountyStatus) -> None:
        """Ανανεώνει το status ενός bounty."""
        await self._redis.hset(f"bounty:{uid}", "status", status.value)
        logger.info(f"Status update: {uid} → {status.value}")

    async def get_bounty(self, uid: str) -> Optional[Bounty]:
        """Ανακτά bounty από Redis."""
        data = await self._redis.hget(f"bounty:{uid}", "data")
        if data:
            return Bounty.from_dict(json.loads(data))
        return None

    async def queue_size(self) -> int:
        """Μέγεθος Redis Stream."""
        return await self._redis.xlen(self.STREAM_KEY)

    def heap_size(self) -> int:
        return len(self._priority_heap)

    @property
    def stats(self) -> dict:
        return {
            **self._stats,
            "bloom_filter_count": self._bloom.count,
            "heap_size": self.heap_size(),
        }
