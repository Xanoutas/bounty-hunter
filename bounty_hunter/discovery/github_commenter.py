import asyncio
import logging
import httpx
import os
import json
import glob

logger = logging.getLogger(__name__)

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

class GitHubCommenter:
    def __init__(self):
        self.token = GITHUB_TOKEN
        self.headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json"
        }
        self.posted_file = "/root/bounty_submissions/github_posted.json"
        self.posted = self._load_posted()

    def _load_posted(self):
        try:
            return set(json.load(open(self.posted_file)))
        except:
            return set()

    def _save_posted(self):
        json.dump(list(self.posted), open(self.posted_file, "w"))

    async def post_comment(self, repo: str, issue_number: int, body: str) -> bool:
        url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, headers=self.headers, json={"body": body})
            if resp.status_code == 201:
                logger.info(f"[github] Commented on {repo}#{issue_number}")
                return True
            else:
                logger.error(f"[github] Failed {repo}#{issue_number}: {resp.status_code}")
                return False

    def _format_comment(self, data: dict) -> str:
        work = data.get("work", "")
        # Καθάρισε markdown artifacts
        work = work.replace("Certainly!", "").replace("Sure!", "").strip()
        return f"""## Bounty Submission

{work[:4000]}

---
*Submitted via automated bounty hunter*"""

    async def process_pending(self):
        files = glob.glob("/root/bounty_submissions/manual/*.json")
        posted = 0
        for f in files:
            try:
                data = json.load(open(f))
                url = data.get("url", "")
                
                # Μόνο GitHub URLs
                if "github.com" not in url:
                    continue
                
                file_id = "gh_" + os.path.basename(f).replace(".json", "")
                if file_id in self.posted:
                    continue

                audit = data.get("audit", {})
                score = audit.get("score", 0)
                reward = data.get("reward", 0)

                if score < 75 or float(reward or 0) > 600:
                    continue

                # Εξαγωγή repo και issue number από URL
                # https://github.com/owner/repo/issues/123
                parts = url.replace("https://github.com/", "").split("/")
                if len(parts) >= 4 and parts[2] == "issues":
                    repo = f"{parts[0]}/{parts[1]}"
                    issue_number = int(parts[3])
                    comment = self._format_comment(data)
                    success = await self.post_comment(repo, issue_number, comment)
                    if success:
                        self.posted.add(file_id)
                        self._save_posted()
                        posted += 1
                        await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"[github] Error: {e}")

        logger.info(f"[github] Posted {posted} comments")
        return posted

    async def run_forever(self):
        logger.info("[github] Auto-commenter started")
        while True:
            try:
                await self.process_pending()
            except Exception as e:
                logger.error(f"[github] Error: {e}")
            await asyncio.sleep(300)
