import asyncio
import logging
import httpx
import os
import json
import glob

logger = logging.getLogger(__name__)

NEYNAR_API = "https://api.neynar.com/v2/farcaster"

class FarcasterPoster:
    def __init__(self):
        self.api_key = os.environ.get("NEYNAR_API_KEY", "")
        self.signer_uuid = os.environ.get("FARCASTER_SIGNER_UUID", "")
        self.fid = os.environ.get("FARCASTER_FID", "")
        self.posted_file = "/root/bounty_submissions/posted.json"
        self.posted = self._load_posted()

    def _load_posted(self):
        try:
            return set(json.load(open(self.posted_file)))
        except:
            return set()

    def _save_posted(self):
        os.makedirs("/root/bounty_submissions", exist_ok=True)
        json.dump(list(self.posted), open(self.posted_file, "w"))

    def _split_thread(self, text: str, max_len: int = 1024) -> list:
        """Σπάει το text σε posts."""
        # Καθάρισε markdown
        text = text.replace("**", "").replace("---", "").strip()
        
        # Αν έχει numbered sections (1/, 2/ κτλ), διάβασε τα
        import re
        parts = re.split(r'\n(?=\*\*\d+\/|\d+\/\s)', text)
        if len(parts) > 1:
            return [p.strip()[:1024] for p in parts if p.strip()]
        
        # Αλλιώς κόψε ανά παράγραφο
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        chunks = []
        current = ""
        for p in paragraphs:
            if len(current) + len(p) + 2 < max_len:
                current += ("\n\n" if current else "") + p
            else:
                if current:
                    chunks.append(current)
                current = p[:max_len]
        if current:
            chunks.append(current)
        return chunks or [text[:max_len]]

    async def post_cast(self, text: str, parent_hash: str = None) -> str:
        """Δημοσιεύει ένα cast και επιστρέφει το hash."""
        payload = {
            "signer_uuid": self.signer_uuid,
            "text": text[:1024],
        }
        if parent_hash:
            payload["parent"] = parent_hash

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{NEYNAR_API}/cast",
                json=payload,
                headers={"api_key": self.api_key, "Content-Type": "application/json"}
            )
            data = resp.json()
            if resp.status_code == 200:
                return data.get("cast", {}).get("hash", "")
            else:
                logger.error(f"[farcaster] Cast error: {data}")
                return ""

    async def post_submission(self, submission: dict, file_id: str) -> bool:
        """Δημοσιεύει ένα approved submission ως thread."""
        if file_id in self.posted:
            return False

        title = submission.get("title", "")[:60]
        work = submission.get("work", "")
        url = submission.get("url", "")
        reward = submission.get("reward_usd") or submission.get("reward", 0)

        if not work:
            return False
        # Φίλτρο reward $5-$600
        if reward < 5 or reward > 600:
            logger.info(f"[farcaster] Skipping ${reward} (out of range $5-$600)")
            self.posted.add(file_id)
            self._save_posted()
            return False

        logger.info(f"[farcaster] Posting: {title} (${reward})")

        # Πρώτο cast — intro
        intro = f"🎯 Bounty Submission: {title}\n\n💰 Reward: ${reward:.0f}\n\n🔗 {url}\n\n⬇️ My submission:"
        first_hash = await self.post_cast(intro)
        if not first_hash:
            return False

        await asyncio.sleep(1)

        # Thread με το work
        parts = self._split_thread(work)
        parent_hash = first_hash
        for i, part in enumerate(parts[:8], 1):  # max 8 parts
            numbered = f"{i}/{len(parts[:8])}\n\n{part}" if len(parts) > 1 else part
            hash_ = await self.post_cast(numbered, parent_hash=parent_hash)
            if hash_:
                parent_hash = hash_
            await asyncio.sleep(1)

        self.posted.add(file_id)
        self._save_posted()
        logger.info(f"[farcaster] Posted thread: {first_hash}")
        return True

    async def process_pending(self):
        """Δημοσιεύει όλα τα approved submissions που δεν έχουν posted."""
        # Από /root/bounty_submissions/*.json (approved)
        files = glob.glob("/root/bounty_submissions/*.json")
        posted_count = 0
        for f in files:
            file_id = os.path.basename(f).replace(".json", "")
            if file_id in self.posted:
                continue
            try:
                data = json.load(open(f))
                # Μόνο αν έχει work και approved review
                if data.get("review", {}).get("approved") and data.get("work"):
                    success = await self.post_submission(data, file_id)
                    if success:
                        posted_count += 1
                        await asyncio.sleep(5)  # Rate limit
            except Exception as e:
                logger.error(f"[farcaster] Error processing {f}: {e}")

        logger.info(f"[farcaster] Posted {posted_count} new submissions")
        return posted_count

    async def run_forever(self):
        logger.info("[farcaster] Auto-poster started")
        while True:
            try:
                await self.process_pending()
            except Exception as e:
                logger.error(f"[farcaster] Error: {e}")
            await asyncio.sleep(300)  # Έλεγχος κάθε 5 λεπτά
