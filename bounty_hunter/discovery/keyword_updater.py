import asyncio
import json
import logging
import os
from datetime import datetime
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

KEYWORDS_FILE = "/root/bounty_hunter/keywords.json"

DEFAULT_KEYWORDS = [
    "bounty", "Bounty", "funded", "grant", "reward",
    "hackathon", "prize", "bounties"
]

async def fetch_trending_keywords() -> list:
    client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
    try:
        resp = await client.chat.completions.create(
            model="gpt-4o",
            max_tokens=500,
            messages=[{
                "role": "system",
                "content": "You are a Web3 bounty hunting expert. Return ONLY a JSON array of strings, no markdown, no explanation."
            }, {
                "role": "user",
                "content": f"""Today is {datetime.now().strftime('%Y-%m-%d')}.
List 20 real GitHub issue LABELS (not topics) that Web3 projects use to mark paid bounties.
Examples of valid labels: "bounty", "funded", "good first issue", "help wanted", "reward", "grant", "paid", "prize"
Return ONLY short label strings that actually appear as GitHub labels.
Return ONLY a JSON array like: ["bounty", "funded", ...]"""
            }]
        )
        text = resp.choices[0].message.content.strip()
        text = text.replace("```json", "").replace("```", "").strip()
        keywords = json.loads(text)
        logger.info(f"[keywords] Fetched {len(keywords)} trending keywords")
        return keywords
    except Exception as e:
        logger.error(f"[keywords] Error: {e}")
        return DEFAULT_KEYWORDS

def load_keywords() -> list:
    try:
        with open(KEYWORDS_FILE) as f:
            data = json.load(f)
            return data.get("keywords", DEFAULT_KEYWORDS)
    except:
        return DEFAULT_KEYWORDS

def save_keywords(keywords: list):
    with open(KEYWORDS_FILE, "w") as f:
        json.dump({
            "keywords": keywords,
            "updated_at": datetime.now().isoformat()
        }, f, indent=2)
    logger.info(f"[keywords] Saved {len(keywords)} keywords")

async def update_keywords():
    keywords = await fetch_trending_keywords()
    save_keywords(keywords)
    return keywords

async def run_forever():
    """Ενημερώνει keywords κάθε πρωί στις 6:00"""
    logger.info("[keywords] Keyword updater started")
    while True:
        now = datetime.now()
        # Πρώτη ενημέρωση αμέσως
        keywords = await update_keywords()
        logger.info(f"[keywords] Updated: {keywords[:5]}...")

        # Υπολόγισε ώρα μέχρι επόμενες 6:00
        from datetime import timedelta
        next_run = now.replace(hour=6, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        wait_seconds = (next_run - now).total_seconds()
        logger.info(f"[keywords] Next update in {wait_seconds/3600:.1f} hours")
        await asyncio.sleep(wait_seconds)
