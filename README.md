# 🎯 Web3 Bounty Hunter — Discovery Layer

## Δομή αρχείων

```
bounty_hunter/
├── discovery/
│   ├── models/
│   │   └── bounty.py          # Bounty dataclass + enums
│   ├── scrapers/
│   │   ├── base.py            # BaseScraper (rate limit, retry, error handling)
│   │   ├── bountycaster.py    # BountyCaster via Neynar/Farcaster API
│   │   ├── gitcoin.py         # Gitcoin REST + GraphQL
│   │   ├── github_scraper.py  # GitHub Issues με label:bounty
│   │   └── dework_layer3.py   # Dework (GraphQL) + Layer3
│   ├── queue/
│   │   └── manager.py         # Redis Streams + Bloom Filter + Priority Heap
│   └── orchestrator.py        # Κεντρικός συντονιστής
└── requirements.txt
```

## Εγκατάσταση

```bash
# 1. Εγκατάσταση dependencies
pip install -r requirements.txt

# 2. Redis (Docker)
docker run -d -p 6379:6379 redis:alpine

# 3. Environment variables
cp .env.example .env
# Συμπλήρωσε:
#   NEYNAR_API_KEY=...      # από https://dev.neynar.com
#   GITHUB_TOKEN=...        # από https://github.com/settings/tokens
#   REDIS_URL=redis://localhost:6379
#   POLL_INTERVAL_MIN=15
```

## Εκκίνηση

```bash
# Μία εκτέλεση
python -m bounty_hunter.discovery.orchestrator

# Continuous loop (κάθε 15 λεπτά)
POLL_INTERVAL_MIN=15 python -m bounty_hunter.discovery.orchestrator
```

## Data Structures που χρησιμοποιούνται

| Δομή | Χρήση | Βιβλιοθήκη |
|------|-------|-------------|
| **Bloom Filter** | Fast deduplication (O(1)) | mmh3 + bytearray |
| **Redis Stream** | Persistent FIFO queue | redis-py async |
| **Min-Heap** | Priority queue (reward_usd) | heapq |
| **Redis Hash** | Full bounty storage | redis-py async |
| **Redis Set** | Bloom filter persistence | redis-py async |

## Πώς λειτουργεί

```
[BountyCaster] ──┐
[Gitcoin]      ──┤
[GitHub]       ──┤──→ asyncio.gather ──→ BloomFilter check ──→ Redis Stream
[Dework]       ──┤                              │
[Layer3]       ──┘                         Priority Heap
                                               │
                                      Layer 3 (AI Agent) ←────┘
```

## Επόμενα Βήματα

- [ ] Layer 3: AI Agent Core (Ollama + LLaMA)
- [ ] Layer 4: Submission automation
- [ ] Layer 5: Payment monitoring
