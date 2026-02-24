import json
import glob
import os
import httpx
import asyncio
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Load .env manually
try:
    for line in open("/root/.env"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
except:
    pass
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "")

async def send_daily_digest():
    # Βρες submissions από τις τελευταίες 24 ώρες
    files = (
        glob.glob("/root/bounty_submissions/manual/*.json") +
        glob.glob("/root/bounty_submissions/*.json")
    )
    files = [f for f in files if 'posted.json' not in f]
    
    cutoff = datetime.now() - timedelta(hours=24)
    top_submissions = []
    
    for f in files:
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(f))
            if mtime < cutoff:
                continue
            data = json.load(open(f))
            audit = data.get("audit", {}) or data.get("review", {})
            score = audit.get("score", 0) or audit.get("quality_score", 0)
            reward = data.get("reward_usd") or data.get("reward", 0)
            if score >= 70 and 5 <= float(reward or 0) <= 600:
                top_submissions.append({
                    "title": data.get("title", "")[:60],
                    "url": data.get("url", ""),
                    "reward": float(reward or 0),
                    "score": score,
                    "work": data.get("work", "")[:300],
                })
        except:
            pass
    
    if not top_submissions:
        logger.info("[digest] No new submissions today")
        return
    
    top_submissions.sort(key=lambda x: x["reward"], reverse=True)
    top5 = top_submissions[:5]
    
    # Φτιάξε Discord message
    lines = [
        f"📋 **Daily Bounty Digest** — {datetime.now().strftime('%d/%m/%Y')}",
        f"✅ {len(top_submissions)} approved submissions (showing top {len(top5)})",
        "━━━━━━━━━━━━━━━━━━━━━━━━"
    ]
    
    for i, s in enumerate(top5, 1):
        lines.append(f"\n**{i}. {s['title']}**")
        lines.append(f"💰 ${s['reward']:.0f} | 🎯 Score: {s['score']}/100")
        lines.append(f"🔗 {s['url']}")
        lines.append(f"📝 Preview: {s['work'][:150]}...")
        lines.append("─────────────────────")
    
    lines.append("\n⚡ Submissions ready for manual copy-paste in `/root/bounty_submissions/manual/`")
    
    message = "\n".join(lines)
    
    # Στείλε στο Discord (split αν > 2000 chars)
    async with httpx.AsyncClient() as client:
        chunks = [message[i:i+1900] for i in range(0, len(message), 1900)]
        for chunk in chunks:
            await client.post(DISCORD_WEBHOOK, json={"content": chunk})
            await asyncio.sleep(0.5)
    
    logger.info(f"[digest] Sent digest with {len(top5)} submissions")

async def run_forever():
    logger.info("[digest] Daily digest scheduler started")
    while True:
        now = datetime.now()
        # Στείλε κάθε μέρα στις 09:00
        next_run = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if now >= next_run:
            next_run += timedelta(days=1)
        wait_seconds = (next_run - now).total_seconds()
        logger.info(f"[digest] Next digest in {wait_seconds/3600:.1f} hours")
        await asyncio.sleep(wait_seconds)
        await send_daily_digest()
